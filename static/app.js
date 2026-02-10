let mediaRecorder;
let chunks = [];
let audioBlob = null;

const statusEl = document.getElementById("status");
const reviewEl = document.getElementById("review");
const finalEl = document.getElementById("final");
const draftEl = document.getElementById("draft");
const finalTextEl = document.getElementById("finalText");
const playback = document.getElementById("playback");

const emailEl = document.getElementById("email");
const notesEl = document.getElementById("notes");
const fileEl = document.getElementById("file");

function showStatus(msg){
  statusEl.textContent = msg;
  statusEl.classList.remove("hidden");
}
function hideStatus(){
  statusEl.classList.add("hidden");
}

function resetAll(){
  hideStatus();
  reviewEl.classList.add("hidden");
  finalEl.classList.add("hidden");
  draftEl.value = "";
  finalTextEl.textContent = "";
  notesEl.value = "";
  fileEl.value = "";
  audioBlob = null;
  playback.classList.add("hidden");
  playback.src = "";
}

async function startRecording(){
  const stream = await navigator.mediaDevices.getUserMedia({ audio:true });
  chunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e)=> chunks.push(e.data);
  mediaRecorder.onstop = ()=>{
    audioBlob = new Blob(chunks, { type: "audio/webm" });
    const url = URL.createObjectURL(audioBlob);
    playback.src = url;
    playback.classList.remove("hidden");
  };
  mediaRecorder.start();
}

function stopRecording(){
  mediaRecorder.stop();
  mediaRecorder.stream.getTracks().forEach(t=>t.stop());
}

async function generateDraftFromForm(formData){
  showStatus("Creating your action plan draft…");
  reviewEl.classList.add("hidden");
  finalEl.classList.add("hidden");

  const res = await fetch("/api/draft", { method:"POST", body: formData });
  const data = await res.json();
  if(!res.ok){
    hideStatus();
    alert(data.error || "Something went wrong.");
    return;
  }
  hideStatus();
  draftEl.value = data.draft_text || "";
  reviewEl.classList.remove("hidden");
  reviewEl.scrollIntoView({behavior:"smooth"});
}

document.getElementById("recordBtn").addEventListener("click", async (e)=>{
  const btn = e.target;
  try{
    if(btn.dataset.state !== "recording"){
      await startRecording();
      btn.dataset.state = "recording";
      btn.textContent = "Stop Recording";
    }else{
      stopRecording();
      btn.dataset.state = "idle";
      btn.textContent = "Start Recording";

      // If we have audio, generate draft from audio
      const fd = new FormData();
      const email = emailEl.value.trim();
      if(email) fd.append("email", email);
      if(audioBlob){
        fd.append("audio", audioBlob, "recording.webm");
      }
      await generateDraftFromForm(fd);
    }
  }catch(err){
    alert("Microphone permission failed or not available.");
    console.error(err);
  }
});

document.getElementById("generateBtn").addEventListener("click", async ()=>{
  const fd = new FormData();
  const email = emailEl.value.trim();
  if(email) fd.append("email", email);

  const notes = notesEl.value.trim();
  const file = fileEl.files[0];

  if(file){
    // For simplicity, we just read text files in the browser; PDFs/DOCX should be handled server-side later.
    // If it's not a text file, ask user to paste notes for this prototype.
    if(!file.type.startsWith("text/")){
      alert("Prototype tip: for PDFs/DOCX, paste the text into the box for now.");
      return;
    }
    const text = await file.text();
    fd.append("notes", text);
  }else if(notes){
    fd.append("notes", notes);
  }else{
    alert("Paste notes or upload a text file.");
    return;
  }

  await generateDraftFromForm(fd);
});

document.getElementById("finalizeBtn").addEventListener("click", async ()=>{
  const email = emailEl.value.trim();
  const final_text = draftEl.value.trim();
  if(!final_text){
    alert("Draft is empty.");
    return;
  }
  showStatus("Finalizing & sending…");
  const res = await fetch("/api/finalize", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ email, final_text })
  });
  const data = await res.json();
  hideStatus();
  if(!res.ok){
    alert(data.error || "Failed to finalize.");
    return;
  }
  finalTextEl.textContent = data.polished_text || final_text;
  finalEl.classList.remove("hidden");
  finalEl.scrollIntoView({behavior:"smooth"});
});

document.getElementById("resetBtn").addEventListener("click", resetAll);
