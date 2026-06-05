const MIN_REQUIRED_IMAGES = 10;

const personNameEl = document.getElementById("personName");
const photoPickerEl = document.getElementById("photoPicker");
const captureVideoEl = document.getElementById("captureVideo");
const captureCanvasEl = document.getElementById("captureCanvas");
const imageGalleryEl = document.getElementById("imageGallery");
const imageCounterEl = document.getElementById("imageCounter");
const collectionHelpEl = document.getElementById("collectionHelp");
const resultEl = document.getElementById("result");
const startCameraBtn = document.getElementById("startCameraBtn");
const captureImageBtn = document.getElementById("captureImageBtn");
const stopCameraBtn = document.getElementById("stopCameraBtn");
const clearAllBtn = document.getElementById("clearAllBtn");
const submitEnrollmentBtn = document.getElementById("submitEnrollmentBtn");

const urlParams = new URLSearchParams(window.location.search || "");
const prefillName = (urlParams.get("name") || "").trim();
if (prefillName) {
  personNameEl.value = prefillName;
}

let cameraStream = null;
let collectedImages = [];

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function revokeImageUrls() {
  for (const image of collectedImages) {
    if (image?.previewUrl) {
      URL.revokeObjectURL(image.previewUrl);
    }
  }
}

function updateCollectionState() {
  const count = collectedImages.length;
  imageCounterEl.textContent = `${count} / ${MIN_REQUIRED_IMAGES} images`;
  const remaining = Math.max(0, MIN_REQUIRED_IMAGES - count);
  collectionHelpEl.textContent = remaining === 0
    ? "Minimum reached. Review the images and save the user to the database."
    : `Add ${remaining} more image(s) to reach the minimum of ${MIN_REQUIRED_IMAGES}.`;
  submitEnrollmentBtn.disabled = count < MIN_REQUIRED_IMAGES;

  if (count === 0) {
    imageGalleryEl.innerHTML = '<div class="muted">No images added yet.</div>';
    return;
  }

  imageGalleryEl.innerHTML = collectedImages.map((image, index) => `
    <div class="image-card">
      <img src="${image.previewUrl}" alt="Collected image ${index + 1}" />
      <div class="image-meta">
        <strong>${escapeHtml(image.label)}</strong>
        <span>${escapeHtml(image.source)}</span>
      </div>
      <button type="button" class="btn danger remove-image-btn" data-image-id="${image.id}">Remove</button>
    </div>
  `).join("");

  document.querySelectorAll(".remove-image-btn").forEach((button) => {
    button.addEventListener("click", () => removeImage(button.dataset.imageId));
  });
}

function addImage(blob, label, source) {
  if (!blob) {
    return;
  }
  collectedImages.push({
    id: crypto.randomUUID(),
    blob,
    label,
    source,
    previewUrl: URL.createObjectURL(blob)
  });
  updateCollectionState();
}

function removeImage(imageId) {
  const match = collectedImages.find((image) => image.id === imageId);
  if (match?.previewUrl) {
    URL.revokeObjectURL(match.previewUrl);
  }
  collectedImages = collectedImages.filter((image) => image.id !== imageId);
  updateCollectionState();
}

async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    captureVideoEl.srcObject = cameraStream;
    captureImageBtn.disabled = false;
    stopCameraBtn.disabled = false;
    startCameraBtn.disabled = true;
    resultEl.textContent = "Camera started. Capture clear single-face images.";
  } catch (error) {
    resultEl.textContent = "Camera error: " + error.message;
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
  }
  cameraStream = null;
  captureVideoEl.srcObject = null;
  captureImageBtn.disabled = true;
  stopCameraBtn.disabled = true;
  startCameraBtn.disabled = false;
}

function captureImage() {
  if (!captureVideoEl.videoWidth || !captureVideoEl.videoHeight) {
    resultEl.textContent = "Camera is not ready yet.";
    return;
  }

  captureCanvasEl.width = captureVideoEl.videoWidth;
  captureCanvasEl.height = captureVideoEl.videoHeight;
  const ctx = captureCanvasEl.getContext("2d");
  ctx.drawImage(captureVideoEl, 0, 0, captureCanvasEl.width, captureCanvasEl.height);

  captureCanvasEl.toBlob((blob) => {
    if (!blob) {
      resultEl.textContent = "Unable to capture image.";
      return;
    }
    addImage(blob, `Capture ${collectedImages.length + 1}`, "Camera");
    resultEl.textContent = "Image captured and added to the collection.";
  }, "image/jpeg", 0.92);
}

function clearAllImages() {
  revokeImageUrls();
  collectedImages = [];
  updateCollectionState();
  resultEl.textContent = "All collected images have been cleared.";
}

async function addSelectedFiles() {
  const files = photoPickerEl.files ? Array.from(photoPickerEl.files) : [];
  if (files.length === 0) {
    return;
  }

  for (const file of files) {
    addImage(file, file.name || `Upload ${collectedImages.length + 1}`, "Upload");
  }

  photoPickerEl.value = "";
  resultEl.textContent = `${files.length} image(s) added to the collection.`;
}

async function submitEnrollment() {
  const name = String(personNameEl.value || "").trim();
  if (!name) {
    resultEl.textContent = "Please enter the person's name.";
    personNameEl.focus();
    return;
  }

  if (collectedImages.length < MIN_REQUIRED_IMAGES) {
    resultEl.textContent = `Please collect at least ${MIN_REQUIRED_IMAGES} images before saving.`;
    return;
  }

  submitEnrollmentBtn.disabled = true;
  resultEl.textContent = "Saving face data to the database...";

  try {
    const formData = new FormData();
    formData.append("name", name);
    collectedImages.forEach((image, index) => {
      const extension = image.blob.type === "image/png" ? "png" : "jpg";
      formData.append("photo", image.blob, `face-${index + 1}.${extension}`);
    });

    const response = await fetch("/api/enroll", {
      method: "POST",
      body: formData
    });

    let data = {};
    try {
      data = await response.json();
    } catch (_) {
      data = { error: "Invalid server response" };
    }

    if (!response.ok) {
      throw new Error(data.error || data.message || "Failed to save face data");
    }

    resultEl.textContent = `${data.message}\nSaved ${data.saved_count} image(s). Total stored: ${data.total_photos}.`;
    clearAllImages();
  } catch (error) {
    resultEl.textContent = "Save failed: " + error.message;
  } finally {
    updateCollectionState();
  }
}

photoPickerEl.addEventListener("change", addSelectedFiles);
startCameraBtn.addEventListener("click", startCamera);
captureImageBtn.addEventListener("click", captureImage);
stopCameraBtn.addEventListener("click", stopCamera);
clearAllBtn.addEventListener("click", clearAllImages);
submitEnrollmentBtn.addEventListener("click", submitEnrollment);

window.addEventListener("beforeunload", () => {
  revokeImageUrls();
  stopCamera();
});

updateCollectionState();
