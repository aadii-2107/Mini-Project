#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/Web}"
SERVICE_NAME="${SERVICE_NAME:-face-backend}"

echo "=== Raspberry Pi Preflight Check ==="
echo "Project: $PROJECT_DIR"
echo "Service: $SERVICE_NAME"
echo

check_ok() { echo "[OK]   $1"; }
check_warn() { echo "[WARN] $1"; }
check_fail() { echo "[FAIL] $1"; }

if [[ -d "$PROJECT_DIR" ]]; then
  check_ok "Project directory exists"
else
  check_fail "Project directory missing"
  exit 1
fi

if [[ -f "$PROJECT_DIR/app.py" ]]; then
  check_ok "app.py exists"
else
  check_fail "app.py missing"
fi

if [[ -d "$PROJECT_DIR/.venv" ]]; then
  check_ok "Virtual environment exists"
else
  check_warn ".venv missing"
fi

if command -v espeak >/dev/null 2>&1; then
  check_ok "espeak installed"
else
  check_warn "espeak not installed (sudo apt install espeak)"
fi

# --- Speaker check ---
if command -v aplay >/dev/null 2>&1; then
  if aplay -l 2>/dev/null | grep -q "card"; then
    check_ok "Audio output device detected"
  else
    check_warn "No audio output device found — connect a speaker or enable HDMI/headphone audio"
  fi
else
  check_warn "aplay not installed (sudo apt install alsa-utils)"
fi

# --- Pi Camera check ---
if command -v libcamera-hello >/dev/null 2>&1; then
  check_ok "libcamera-hello available"
else
  check_warn "libcamera tools not installed (sudo apt install libcamera-apps)"
fi

if [[ -e /dev/video0 ]] || [[ -e /dev/media0 ]]; then
  check_ok "Camera device node found"
else
  check_warn "No camera device node — check Pi Camera cable and enable camera in raspi-config"
fi

if [[ -f "$PROJECT_DIR/pi_camera_client.py" ]]; then
  check_ok "pi_camera_client.py exists"
else
  check_warn "pi_camera_client.py missing"
fi

# --- Backend service checks ---
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
  check_ok "Backend systemd service installed"
else
  check_warn "Backend systemd service not installed"
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
  check_ok "Backend service is running"
else
  check_warn "Backend service not running"
fi

if curl -fsS "http://127.0.0.1:5000/health" >/dev/null 2>&1; then
  check_ok "Health endpoint is reachable"
else
  check_warn "Health endpoint not reachable"
fi

# --- Camera client service checks ---
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}-camera\.service"; then
  check_ok "Camera client systemd service installed"
else
  check_warn "Camera client systemd service not installed"
fi

if systemctl is-active --quiet "${SERVICE_NAME}-camera"; then
  check_ok "Camera client service is running"
else
  check_warn "Camera client service not running"
fi

echo
echo "Preflight check complete."
