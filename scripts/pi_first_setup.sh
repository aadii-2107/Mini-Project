#!/usr/bin/env bash
set -euo pipefail

# One-time Raspberry Pi software setup for this project.
# Run on Pi after cloning the repo.

PROJECT_DIR="${PROJECT_DIR:-$HOME/Web}"
SERVICE_NAME="${SERVICE_NAME:-face-backend}"
PI_USER_NAME="${PI_USER_NAME:-$USER}"

echo "[1/9] Installing system packages..."
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential cmake pkg-config \
  libatlas-base-dev libjpeg-dev libopenblas-dev liblapack-dev \
  libhdf5-dev libssl-dev libffi-dev \
  espeak alsa-utils curl git \
  libcamera-apps python3-libcamera python3-picamera2

echo "[2/9] Entering project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"

echo "[3/9] Creating virtual environment (if missing)..."
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

echo "[4/9] Installing Python dependencies..."
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
if [[ -f requirements-pi.txt ]]; then
  pip install -r requirements-pi.txt
fi

echo "[5/9] Making deploy script executable..."
chmod +x scripts/update_on_pi.sh

echo "[6/9] Writing systemd service: $SERVICE_NAME"
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=Face Recognition Backend (Flask)
After=network.target

[Service]
User=${PI_USER_NAME}
WorkingDirectory=${PROJECT_DIR}
Environment="FLASK_HOST=0.0.0.0"
Environment="FLASK_PORT=5000"
Environment="FLASK_DEBUG=false"
Environment="ENABLE_PI_TTS=true"
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[7/9] Writing camera-client systemd service..."
sudo tee "/etc/systemd/system/${SERVICE_NAME}-camera.service" >/dev/null <<EOF
[Unit]
Description=Pi Camera Client for Face Recognition
After=network.target ${SERVICE_NAME}.service
Requires=${SERVICE_NAME}.service

[Service]
User=${PI_USER_NAME}
WorkingDirectory=${PROJECT_DIR}
Environment="BACKEND_URL=http://127.0.0.1:5000"
Environment="CAPTURE_INTERVAL=1.0"
Environment="COOLDOWN_SECONDS=10"
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/pi_camera_client.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[8/9] Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl enable "${SERVICE_NAME}-camera"
sudo systemctl restart "${SERVICE_NAME}-camera"

echo "[9/9] Verifying health endpoint..."
sleep 3
curl -fsS "http://127.0.0.1:5000/health" && echo
echo "Pi first setup complete."
