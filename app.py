import os
import json
import base64
import mimetypes
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)

APP_NAME = os.environ.get("APP_NAME", "FollowUp")

DRAFT_PROMPT = """You are an expert project manager.

From the following meeting notes, create a DRAFT action plan that includes:

1. Clear action items
2. An owner for each item (use “Unassigned” if unclear)
3. A realistic deadline for each item
4. A simple execution schedule broken into steps
5. Any risks, blockers, or missing information

Assume this is a draft that the user will review before finalizing.
Write clearly, professionally, and concisely.
"""

FINAL_POLISH_PROMPT = """You are an expert project manager.

You will receive an action plan that a user has reviewed and edited. Your job:
- keep the same meaning
- ensure it is professionally formatted
- ensure deadlines and schedules read clearly
- do NOT invent owners or deadlines that are missing; keep "Unassigned" if present.

Return clean markdown suitable for email.
"""

app = Flask(__name__, static_folder="static", static_url_path="")

def _headers():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return {"Authorization": f"Bearer {OPENAI_API_KEY}"}

def openai_transcribe(audio_bytes: bytes, filename: str):
    """
    Uses OpenAI Audio API /audio/transcriptions
    """
    url = f"{OPENAI_BASE_URL}/audio/transcriptions"
    files = {
        "file": (filename, audio_bytes, mimetypes.guess_type(filename)[0] or "application/octet-stream")
    }
    data = {
        "model": os.environ.get("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    }
    r = requests.post(url, headers=_headers(), files=files, data=data, timeout=120)
    r.raise_for_status()
    return r.json().get("text", "")

def openai_make_action_plan(notes_text: str):
    """
    Uses OpenAI Responses API /responses
    """
    url = f"{OPENAI_BASE_URL}/responses"
    payload = {
        "model": os.environ.get("TEXT_MODEL", "gpt-4o-mini"),
        "input": [
            {"role": "system", "content": "You produce structured, accurate work outputs and avoid hallucinating specifics."},
            {"role": "user", "content": DRAFT_PROMPT + "\n\nMEETING NOTES:\n" + notes_text}
        ],
        "temperature": 0.2
    }
    r = requests.post(url, headers={**_headers(), "Content-Type": "application/json"}, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    # Extract output_text in a tolerant way
    out = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    out += c.get("text", "")
    return out.strip()

def openai_polish(final_text: str):
    url = f"{OPENAI_BASE_URL}/responses"
    payload = {
        "model": os.environ.get("TEXT_MODEL", "gpt-4o-mini"),
        "input": [
            {"role": "system", "content": "You are a careful formatter. Do not add facts."},
            {"role": "user", "content": FINAL_POLISH_PROMPT + "\n\nACTION PLAN (USER-EDITED):\n" + final_text}
        ],
        "temperature": 0.1
    }
    r = requests.post(url, headers={**_headers(), "Content-Type": "application/json"}, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    out = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    out += c.get("text", "")
    return out.strip()

def send_email(to_email: str, subject: str, markdown_body: str):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and FROM_EMAIL):
        raise RuntimeError("SMTP settings not set. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, FROM_EMAIL.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{APP_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email

    # Simple plain-text fallback
    plain = markdown_body.replace("**", "").replace("#", "").replace("•", "-")
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(f"<pre style='font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; white-space: pre-wrap'>{markdown_body}</pre>", "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

@app.get("/")
def index():
    return send_from_directory("static", "index.html")

@app.post("/api/draft")
def api_draft():
    """
    Accepts:
      - notes (string) OR
      - audio (file upload)
    Returns:
      - draft_text
      - source_text (transcript/notes used)
    """
    notes = request.form.get("notes", "").strip()
    email = request.form.get("email", "").strip()

    if not notes and "audio" in request.files:
        f = request.files["audio"]
        audio_bytes = f.read()
        filename = f.filename or "recording.webm"
        transcript = openai_transcribe(audio_bytes, filename)
        notes = transcript

    if not notes:
        return jsonify({"error": "No notes or audio provided."}), 400

    draft = openai_make_action_plan(notes)
    return jsonify({"draft_text": draft, "source_text": notes, "email": email})

@app.post("/api/finalize")
def api_finalize():
    """
    Accepts JSON:
      {
        "email": "...",
        "final_text": "..."
      }
    Sends email and returns polished text.
    """
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    final_text = (data.get("final_text") or "").strip()

    if not final_text:
        return jsonify({"error": "final_text missing"}), 400

    polished = openai_polish(final_text)

    if email:
        subject = "Action Items & Schedule from Your Meeting"
        send_email(email, subject, polished + f"\n\n—\nGenerated by {APP_NAME}")
    return jsonify({"polished_text": polished})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
