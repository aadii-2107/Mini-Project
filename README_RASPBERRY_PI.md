# Run This Project on Raspberry Pi 4B

This guide helps you run the existing Flask + face recognition backend on Raspberry Pi OS (64-bit recommended).

There are **three modes** of operation:

| Mode | Backend runs on | Camera source | Speaker output | When to use |
|------|----------------|--------------|----------------|-------------|
| **Browser mode** | Pi (local) | Laptop/phone webcam via browser | Browser Web Speech API | Testing from another device |
| **Headless mode** | Pi (local) | Pi Camera Module | Speaker via `espeak` | Standalone kiosk / robot |
| **Cloud mode** | Cloud server | Pi Camera Module | Speaker via `espeak` | Production / remote backend |

> For **cloud mode** setup, see [README_CLOUD_PI_WORKFLOW.md](README_CLOUD_PI_WORKFLOW.md).

---

## 1) Prepare Raspberry Pi

Use Raspberry Pi OS Bookworm (64-bit), then update packages:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

After reboot:

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential cmake pkg-config \
  libatlas-base-dev libjpeg-dev libopenblas-dev liblapack-dev \
  libhdf5-dev libssl-dev libffi-dev \
  espeak alsa-utils \
  libcamera-apps python3-libcamera python3-picamera2
```

## 2) Hardware setup

### Pi Camera Module

1. Shut down the Pi and connect the camera ribbon cable to the CSI port.
2. Boot up and verify the camera is detected:

```bash
libcamera-hello --timeout 3000
```

You should see a 3-second preview window (or terminal confirmation on a headless Pi).

### Speaker

Connect a speaker to the 3.5 mm audio jack, USB audio adapter, or HDMI output.

Test audio output:

```bash
speaker-test -c2 -t wav
```

If no sound, force audio to the correct output:

```bash
# For 3.5 mm jack:
sudo raspi-config nonint do_audio 1
# For HDMI:
sudo raspi-config nonint do_audio 2
```

Test espeak:

```bash
espeak "Hello, this is a test"
```

## 3) Copy project to Pi

Clone or copy this project folder to your Pi, then enter the folder:

```bash
cd /path/to/Web
```

## 4) Create virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -r requirements-pi.txt
```

If `face-recognition` fails to build on your Pi, install `dlib` first and retry:

```bash
pip install dlib
pip install face-recognition
```

## 5) Run backend on network (browser mode)

The app is already configured to read host/port/debug from environment variables.

```bash
export FLASK_HOST=0.0.0.0
export FLASK_PORT=5000
export FLASK_DEBUG=false
export ENABLE_PI_TTS=true
python app.py
```

From another device on same network, open:

- `http://<RASPBERRY_PI_IP>:5000/`
- `http://<RASPBERRY_PI_IP>:5000/health`

Find Pi IP:

```bash
hostname -I
```

## 6) Run headless with Pi Camera + Speaker

Start the Flask backend first (in one terminal or as a service):

```bash
export FLASK_HOST=0.0.0.0
export FLASK_PORT=5000
export ENABLE_PI_TTS=true
python app.py
```

Then run the Pi Camera client (in another terminal):

```bash
export BACKEND_URL=http://127.0.0.1:5000
export CAPTURE_INTERVAL=1.0
export COOLDOWN_SECONDS=10
python pi_camera_client.py
```

The camera client will:

1. Capture frames from the Pi Camera Module every `CAPTURE_INTERVAL` seconds.
2. Send each frame to the backend `/api/identify-photo` endpoint.
3. When a known person is identified, speak the welcome message through the speaker.
4. Apply a cooldown so the same person is not greeted repeatedly.

### Environment variables for `pi_camera_client.py`

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_URL` | `http://127.0.0.1:5000` | Flask backend URL |
| `CAPTURE_INTERVAL` | `1.0` | Seconds between frame captures |
| `COOLDOWN_SECONDS` | `10` | Min seconds before re-greeting same person |
| `CAMERA_WIDTH` | `640` | Capture width in pixels |
| `CAMERA_HEIGHT` | `480` | Capture height in pixels |
| `ESPEAK_SPEED` | `145` | espeak words-per-minute |
| `ESPEAK_AMPLITUDE` | `180` | espeak volume (0-200) |
| `JPEG_QUALITY` | `80` | JPEG compression quality (1-100) |

## 7) Run as systemd services (auto-start on boot)

### Backend service

```bash
sudo nano /etc/systemd/system/face-backend.service
```

Paste and adjust paths/user:

```ini
[Unit]
Description=Face Recognition Backend (Flask)
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/Web
Environment="FLASK_HOST=0.0.0.0"
Environment="FLASK_PORT=5000"
Environment="FLASK_DEBUG=false"
Environment="ENABLE_PI_TTS=true"
ExecStart=/home/pi/Web/.venv/bin/python /home/pi/Web/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Camera client service

```bash
sudo nano /etc/systemd/system/face-backend-camera.service
```

```ini
[Unit]
Description=Pi Camera Client for Face Recognition
After=network.target face-backend.service
Requires=face-backend.service

[Service]
User=pi
WorkingDirectory=/home/pi/Web
Environment="BACKEND_URL=http://127.0.0.1:5000"
Environment="CAPTURE_INTERVAL=1.0"
Environment="COOLDOWN_SECONDS=10"
ExecStart=/home/pi/Web/.venv/bin/python /home/pi/Web/pi_camera_client.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable and start both services

```bash
sudo systemctl daemon-reload
sudo systemctl enable face-backend face-backend-camera
sudo systemctl start face-backend
sudo systemctl start face-backend-camera
```

### View logs

```bash
# Backend logs
journalctl -u face-backend -f

# Camera client logs
journalctl -u face-backend-camera -f
```

## 8) One-command setup

The `scripts/pi_first_setup.sh` script handles everything above automatically:

```bash
cd /home/pi/Web
chmod +x scripts/pi_first_setup.sh scripts/pi_preflight_check.sh scripts/update_on_pi.sh
PROJECT_DIR=/home/pi/Web SERVICE_NAME=face-backend ./scripts/pi_first_setup.sh
./scripts/pi_preflight_check.sh
```

## 9) Notes specific to Pi 4B

- For better recognition speed, use clear photos and avoid very high-resolution frames.
- Keep at least 2GB free RAM; 4GB or 8GB Pi models are more comfortable for `dlib`.
- Use Raspberry Pi OS 64-bit for better compatibility with Python scientific packages.
- Run `speaker-test -c2` once to verify speaker output before testing greeting voice.
- The Pi Camera Module v2 or v3 are recommended. USB webcams may work but need different configuration.
- If using a USB speaker, check `aplay -l` to confirm it is detected as an audio device.
