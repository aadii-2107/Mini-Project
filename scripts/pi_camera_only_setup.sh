#!/usr/bin/env bash
set -euo pipefail

# Pi-only setup: installs only the camera client and speaker.
# The Flask backend runs on a separate cloud server.
#
# Usage:
#   BACKEND_URL=https://your-cloud-server.com PROJECT_DIR=/home/pi/Web ./scripts/pi_camera_only_setup.sh

PROJECT_DIR="${PROJECT_DIR:-$HOME/Web}"
PI_USER_NAME="${PI_USER_NAME:-$USER}"
SERVICE_NAME="${SERVICE_NAME:-face-backend}"
BACKEND_URL="${BACKEND_URL:-}"

if [[ -z "$BACKEND_URL" ]]; then
  echo "ERROR: BACKEND_URL is required. Set it to your cloud server URL."
  echo "Example: BACKEND_URL=https://your-server.com PROJECT_DIR=$PROJECT_DIR $0"
  exit 1
fi

echo "=== Pi Camera-Only Setup (Cloud Backend Mode) ==="
echo "Project dir : $PROJECT_DIR"
echo "Backend URL : $BACKEND_URL"
echo

echo "[1/6] Installing system packages..."
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  espeak alsa-utils \
  libcamera-apps python3-libcamera python3-picamera2

echo "[2/6] Entering project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"

echo "[3/6] Creating virtual environment (if missing)..."
if [[ ! -d ".venv" ]]; then
  python3 -m venv --system-site-packages .venv
fi

echo "[4/6] Installing Python dependencies for camera client..."
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements-pi.txt

echo "[5/6] Writing camera-client systemd service..."
sudo tee "/etc/systemd/system/${SERVICE_NAME}-camera.service" >/dev/null <<EOF
[Unit]
Description=Pi Camera Client for Face Recognition (Cloud Mode)
After=network-online.target
Wants=network-online.target

[Service]
User=${PI_USER_NAME}
WorkingDirectory=${PROJECT_DIR}
Environment="BACKEND_URL=${BACKEND_URL}"
Environment="CAPTURE_INTERVAL=1.0"
Environment="COOLDOWN_SECONDS=10"
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/pi_camera_client.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[6/6] Enabling and starting camera service..."
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}-camera"
sudo systemctl restart "${SERVICE_NAME}-camera"

sleep 3
if systemctl is-active --quiet "${SERVICE_NAME}-camera"; then
  echo "Camera client service is running."
else
  echo "WARNING: Camera client service failed to start. Check logs:"
  echo "  journalctl -u ${SERVICE_NAME}-camera -n 30"
fi

echo
echo "Pi camera-only setup complete."
echo "Camera is sending frames to: $BACKEND_URL"
echo "View logs: journalctl -u ${SERVICE_NAME}-camera -f"
