const resultEl = document.getElementById("result");
const newPersonNameEl = document.getElementById("newPersonName");
const addPersonBtn = document.getElementById("addPersonBtn");
const uploadPersonNameEl = document.getElementById("uploadPersonName");
const photoEl = document.getElementById("photoFile");
let cameraStream = null;
let capturedBlob = null;
const urlParams = new URLSearchParams(window.location.search || "");
const prefillName = (urlParams.get("name") || "").trim();
if (prefillName) uploadPersonNameEl.value = prefillName;
function switchTab(tab) {
  document.getElementById("panelChoose").classList.toggle("active", tab === "choose");
  document.getElementById("panelCapture").classList.toggle("active", tab === "capture");
  document.getElementById("tabChoose").classList.toggle("active", tab === "choose");
  document.getElementById("tabCapture").classList.toggle("active", tab === "capture");
  if (tab === "choose") stopCamera();
}
async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    const video = document.getElementById("cameraPreview");
    video.srcObject = cameraStream;
    video.style.display = "block";
    document.getElementById("startCamBtn").style.display = "none";
    document.getElementById("captureBtn").style.display = "inline-block";
    document.getElementById("stopCamBtn").style.display = "inline-block";
    document.getElementById("capturedPreview").style.display = "none";
    document.getElementById("retakeBtn").style.display = "none";
    document.getElementById("uploadCaptureBtn").style.display = "none";
    capturedBlob = null;
  } catch (err) {
    resultEl.textContent = "Camera error: " + err.message + ". Try 'Choose Photo' instead.";
  }
}
function capturePhoto() {
  const video = document.getElementById("cameraPreview");
  const canvas = document.getElementById("snapshotCanvas");
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.toBlob((blob) => {
    capturedBlob = blob;
    const img = document.getElementById("capturedPreview");
    img.src = URL.createObjectURL(blob);
    img.style.display = "block";
    video.style.display = "none";
    document.getElementById("captureBtn").style.display = "none";
    document.getElementById("retakeBtn").style.display = "inline-block";
    document.getElementById("uploadCaptureBtn").style.display = "inline-block";
    resultEl.textContent = "Photo captured! Click Upload to save.";
  }, "image/jpeg", 0.92);
}
function retakePhoto() {
  capturedBlob = null;
  document.getElementById("capturedPreview").style.display = "none";
  document.getElementById("cameraPreview").style.display = "block";
  document.getElementById("captureBtn").style.display = "inline-block";
  document.getElementById("retakeBtn").style.display = "none";
  document.getElementById("uploadCaptureBtn").style.display = "none";
  resultEl.textContent = "Ready to capture.";
}
function stopCamera() {
  if (cameraStream) { cameraStream.getTracks().forEach((t) => t.stop()); cameraStream = null; }
  const video = document.getElementById("cameraPreview");
  video.srcObject = null;
  video.style.display = "none";
  document.getElementById("startCamBtn").style.display = "inline-block";
  document.getElementById("captureBtn").style.display = "none";
  document.getElementById("stopCamBtn").style.display = "none";
}
async function getOrCreatePersonIdByName(name) {
  const normalizedName = String(name || "").trim();
  if (!normalizedName) throw new Error("Please enter a person name.");
  const listResponse = await fetch("/api/persons");
  const persons = await listResponse.json();
  if (!listResponse.ok) throw new Error(persons.error || "Could not load persons");
  const existing = Array.isArray(persons)
    ? persons.find((p) => String(p.name || "").toLowerCase() === normalizedName.toLowerCase())
    : null;
  if (existing && existing.id) return existing.id;
  const createResponse = await fetch("/api/persons", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: normalizedName }),
  });
  const created = await createResponse.json();
  if (!createResponse.ok) throw new Error(created.error || "Failed to create person");
  return created.id;
}
async function doUpload(formData, label) {
  const name = String(uploadPersonNameEl.value || "").trim();
  if (!name) { resultEl.textContent = "Please enter a person name first."; return; }
  resultEl.textContent = "Uploading " + label + "...";
  try {
    const personId = await getOrCreatePersonIdByName(name);
    const response = await fetch(`/api/persons/${personId}/photo`, { method: "POST", body: formData });
    let data = {};
    try { data = await response.json(); } catch (_) { data = { error: "Invalid server response" }; }
    if (response.ok) {
      resultEl.textContent = "✅ Saved!\n" + JSON.stringify(data, null, 2);
    } else {
      resultEl.textContent = "❌ HTTP " + response.status + "\n" + JSON.stringify(data, null, 2);
    }
  } catch (err) {
    resultEl.textContent = "Upload failed: " + err.message;
  }
}
document.getElementById("uploadChooseBtn").addEventListener("click", async () => {
  const files = photoEl.files ? Array.from(photoEl.files) : [];
  if (files.length === 0) { resultEl.textContent = "Please select one or more photo files."; return; }
  const formData = new FormData();
  for (const file of files) formData.append("photo", file);
  await doUpload(formData, files.length + " file(s)");
});
async function uploadCaptured() {
  if (!capturedBlob) { resultEl.textContent = "No photo captured yet."; return; }
  const formData = new FormData();
  formData.append("photo", capturedBlob, "capture.jpg");
  stopCamera();
  await doUpload(formData, "captured photo");
}
async function addPerson() {
  const name = (newPersonNameEl.value || "").trim();
  if (!name) { resultEl.textContent = "Enter person name before adding."; return; }
  addPersonBtn.disabled = true;
  resultEl.textContent = "Adding person...";
  try {
    const response = await fetch("/api/persons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Failed to add person");
    resultEl.textContent = "✅ Added: " + data.name;
    newPersonNameEl.value = "";
    uploadPersonNameEl.value = data.name || "";
  } catch (err) {
    resultEl.textContent = "Failed: " + err.message;
  } finally {
    addPersonBtn.disabled = false;
  }
}
addPersonBtn.addEventListener("click", addPerson);