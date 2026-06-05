const statusEl = document.getElementById("status");
const videoEl = document.getElementById("camera");
const resultEl = document.getElementById("result");

const CLIENT_COOLDOWN_MS = 10000;
let identifyInProgress = false;
let lastIdentifiedName = null;
let waitingCount = 0;
let nextIdentifyAt = 0;
let identifyTimerId = null;

let isSpeakingGreeting = false;
const greetingQueue = [];
const lastQueuedGreetingAt = new Map();

function processGreetingQueue() {
  if (!("speechSynthesis" in window) || isSpeakingGreeting || greetingQueue.length === 0) {
    return;
  }

  const nextGreeting = greetingQueue.shift();
  if (!nextGreeting) {
    return;
  }

  isSpeakingGreeting = true;
  const utterance = new SpeechSynthesisUtterance(nextGreeting);
  utterance.rate = 0.8;
  utterance.pitch = 1.0;
  utterance.volume = 1.0;
  utterance.onend = () => {
    isSpeakingGreeting = false;
    processGreetingQueue();
  };
  utterance.onerror = () => {
    isSpeakingGreeting = false;
    processGreetingQueue();
  };
  window.speechSynthesis.speak(utterance);
}

function speakGreeting(name, text) {
  if (!("speechSynthesis" in window)) {
    return;
  }
  const greeting = String(text || "").trim();
  const speakerKey = `${String(name || "").trim()}::${greeting}`;
  const now = Date.now();
  const lastQueuedAt = lastQueuedGreetingAt.get(speakerKey) || 0;
  if (!greeting || (now - lastQueuedAt) < 1500) {
    return;
  }
  lastQueuedGreetingAt.set(speakerKey, now);
  greetingQueue.push(greeting);
  processGreetingQueue();
}

async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    videoEl.srcObject = stream;
    statusEl.className = "ok";
    statusEl.textContent = "Camera started successfully.";
    identifyTimerId = setInterval(identifyCurrentFrame, 800);
  } catch (err) {
    statusEl.className = "err";
    statusEl.textContent = "Camera access failed: " + err.message;
  }
}

async function identifyCurrentFrame() {
  if (!videoEl.videoWidth || !videoEl.videoHeight) {
    resultEl.textContent = "Camera frame is not ready yet.";
    return;
  }

  if (Date.now() < nextIdentifyAt) {
    return;
  }

  if (identifyInProgress) {
    return;
  }
  identifyInProgress = true;
  try {
    const scale = Math.min(1, 640 / videoEl.videoWidth);
    const targetWidth = Math.max(1, Math.floor(videoEl.videoWidth * scale));
    const targetHeight = Math.max(1, Math.floor(videoEl.videoHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
    if (!blob) {
      throw new Error("Unable to capture image");
    }

    const formData = new FormData();
    formData.append("photo", blob, "capture.jpg");

    const response = await fetch("/api/identify-photo", {
      method: "POST",
      body: formData
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Identification failed");
    }
    if (data.state === "waiting") {
      waitingCount += 1;
      if (waitingCount >= 2) {
        lastIdentifiedName = null;
        nextIdentifyAt = 0;
        resultEl.textContent = "Waiting for face...";
      }
      return;
    }
    waitingCount = 0;

    if (data.state === "cooldown" && data.name === lastIdentifiedName) {
      nextIdentifyAt = Date.now() + CLIENT_COOLDOWN_MS;
      return;
    }

    const confidence = typeof data.confidence === "number" ? ` (confidence ${data.confidence})` : "";
    const cooldownText = data.cooldown_active ? " [recently identified]" : "";
    resultEl.textContent = `Detected: ${data.name} - ${data.welcomeMessage}${confidence}${cooldownText}`;
    lastIdentifiedName = data.name || null;
    speakGreeting(data.name, data.welcomeMessage);
    nextIdentifyAt = Date.now() + CLIENT_COOLDOWN_MS;
  } catch (err) {
    if (String(err.message).toLowerCase().includes("no face found")) {
      resultEl.textContent = "Waiting for face...";
    } else {
      resultEl.textContent = "Error: " + err.message;
    }
  } finally {
    identifyInProgress = false;
  }
}

startCamera();

