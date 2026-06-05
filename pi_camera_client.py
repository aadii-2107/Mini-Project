#!/usr/bin/env python3
"""Headless Raspberry Pi camera client for face recognition.

Captures frames from the Pi Camera Module, sends them to the Flask
backend ``/api/identify-photo`` endpoint, and speaks greetings through
the connected speaker using ``espeak``.

Configuration is done through environment variables (see below).

Usage::

    export BACKEND_URL=http://127.0.0.1:5000
    python pi_camera_client.py
"""

import io
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000").rstrip("/")
CAPTURE_INTERVAL = float(os.getenv("CAPTURE_INTERVAL", "1.0"))
COOLDOWN_SECONDS = float(os.getenv("COOLDOWN_SECONDS", "10"))
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "480"))
ESPEAK_SPEED = os.getenv("ESPEAK_SPEED", "145")
ESPEAK_AMPLITUDE = os.getenv("ESPEAK_AMPLITUDE", "180")
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "80"))

_running = True
_last_greeted_name: str | None = None
_last_greeted_at: float = 0.0


def _log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{timestamp}] {message}", flush=True)


def _shutdown(signum: int, _frame: object) -> None:
    global _running
    _log(f"Received signal {signum}, shutting down...")
    _running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def _check_imports() -> bool:
    missing: list[str] = []
    try:
        import picamera2  # noqa: F401
    except ImportError:
        missing.append("picamera2")
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")
    if missing:
        _log(
            f"Missing required packages: {', '.join(missing)}. "
            "Install with: pip install " + " ".join(missing)
        )
        return False
    return True


def speak(text: str) -> None:
    """Speak *text* through the connected speaker using espeak."""
    safe_text = text.strip()
    if not safe_text:
        return
    try:
        subprocess.Popen(
            ["espeak", "-s", ESPEAK_SPEED, "-a", ESPEAK_AMPLITUDE, safe_text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        _log("espeak not found — install with: sudo apt install espeak")
    except Exception as exc:
        _log(f"TTS error: {exc}")


def create_camera() -> "picamera2.Picamera2":
    """Initialise and start the Pi Camera."""
    from picamera2 import Picamera2

    camera = Picamera2()
    config = camera.create_still_configuration(
        main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"},
    )
    camera.configure(config)
    camera.start()
    time.sleep(2)
    _log(f"Camera started ({CAMERA_WIDTH}x{CAMERA_HEIGHT})")
    return camera


def capture_jpeg(camera: "picamera2.Picamera2") -> bytes:
    """Capture a single frame and return JPEG bytes."""
    from PIL import Image

    frame = camera.capture_array()
    image = Image.fromarray(frame)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def send_frame(jpeg_data: bytes) -> dict | None:
    """POST the JPEG frame to the backend and return JSON response."""
    import requests

    url = f"{BACKEND_URL}/api/identify-photo"
    try:
        resp = requests.post(
            url,
            files={"photo": ("capture.jpg", jpeg_data, "image/jpeg")},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        _log(f"Cannot reach backend at {url} — is the Flask server running?")
    except requests.Timeout:
        _log("Backend request timed out")
    except Exception as exc:
        _log(f"Request error: {exc}")
    return None


def handle_response(data: dict) -> None:
    """Process the identification response — log and speak greeting."""
    global _last_greeted_name, _last_greeted_at

    state = data.get("state")
    name = data.get("name")
    message = data.get("welcomeMessage", "")

    if state == "waiting":
        return

    if state == "cooldown":
        return

    if state == "identified":
        confidence = data.get("confidence")
        is_known = data.get("is_known", False)
        conf_str = f" (confidence {confidence:.2f})" if confidence else ""
        _log(f"Identified: {name}{conf_str} — {'known' if is_known else 'guest'}")

        now = time.monotonic()
        if name == _last_greeted_name and (now - _last_greeted_at) < COOLDOWN_SECONDS:
            return
        _last_greeted_name = name
        _last_greeted_at = now

        if message:
            _log(f"Speaking: {message}")
            speak(message)


def main() -> None:
    if not _check_imports():
        sys.exit(1)

    _log(f"Backend URL: {BACKEND_URL}")
    _log(f"Capture interval: {CAPTURE_INTERVAL}s")
    _log(f"Cooldown: {COOLDOWN_SECONDS}s")

    camera = create_camera()
    _log("Pi Camera client running — press Ctrl+C to stop")

    try:
        while _running:
            jpeg_data = capture_jpeg(camera)
            data = send_frame(jpeg_data)
            if data is not None:
                handle_response(data)
            time.sleep(CAPTURE_INTERVAL)
    finally:
        _log("Stopping camera...")
        camera.stop()
        camera.close()
        _log("Camera stopped. Goodbye.")


if __name__ == "__main__":
    main()
