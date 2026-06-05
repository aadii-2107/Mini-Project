# Cloud + Raspberry Pi Workflow

This is the recommended flow for your face-recognition robot project.

## Architecture

```
┌──────────────────────────┐         ┌──────────────────────────┐
│      Cloud Server        │         │     Raspberry Pi 4B      │
│                          │  HTTP   │                          │
│  Flask backend (app.py)  │◄────────│  Pi Camera client        │
│  SQLite database         │         │  (pi_camera_client.py)   │
│  Face encodings          │────────►│                          │
│  Web UI                  │  JSON   │  Speaker (espeak)        │
│                          │         │  Pi Camera Module        │
└──────────────────────────┘         └──────────────────────────┘
```

**Cloud server** handles:
- Face recognition (encoding, matching)
- Person database (SQLite)
- Web UI for managing persons and uploading photos
- API endpoints (`/api/identify-photo`, `/api/persons`, etc.)

**Raspberry Pi** handles:
- Capturing frames from Pi Camera Module
- Sending frames to cloud backend for identification
- Speaking welcome greetings through the connected speaker

## 1) Deploy backend to cloud

### Option A: Render (one-click deploy)

1. Go to [https://render.com](https://render.com) and sign up (free).
2. Click **New → Web Service**.
3. Connect your GitHub account and select this repo (`jaykar22/face-recognition`).
4. Render auto-detects `render.yaml` and configures everything.
5. Click **Create Web Service**.

Your backend URL will be: `https://face-recognition-backend-XXXX.onrender.com`

> **Note:** Render free tier sleeps after 15 min of inactivity. The first request after sleep takes ~30 seconds. For 24/7 uptime, upgrade to the Starter plan ($7/month) or use a keep-alive ping service.

### Option B: Docker (any cloud provider)

A `Dockerfile` is included for deploying to any provider that supports Docker (AWS, DigitalOcean, Railway, Fly.io, etc.):

```bash
docker build -t face-recognition .
docker run -p 5000:5000 -v face-data:/data -e DATA_DIR=/data face-recognition
```

### Option C: Manual VPS

```bash
# On cloud server
git clone https://github.com/jaykar22/face-recognition.git
cd face-recognition
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

### Verify deployment

```bash
curl https://your-cloud-server.com/health
# Should return: {"status":"ok"}
```

## 2) Branch strategy

- Use `dev` for ongoing changes.
- Use `main` only for stable code.

## 3) GitHub CI

A workflow is added at `.github/workflows/ci.yml`:

- Runs on push/PR.
- Checks Python syntax.
- Runs a health-route smoke test (`/health`).

This ensures basic app correctness before deployment.

## 4) Set up Raspberry Pi (camera-only mode)

On your Pi, clone the repo and run the camera-only setup:

```bash
git clone https://github.com/jaykar22/face-recognition.git ~/Web
cd ~/Web
chmod +x scripts/pi_camera_only_setup.sh scripts/pi_preflight_check.sh
BACKEND_URL=https://your-cloud-server.com PROJECT_DIR=$HOME/Web ./scripts/pi_camera_only_setup.sh
```

This installs only what the Pi needs (picamera2, espeak, requests) and creates a systemd service that:
1. Captures frames from the Pi Camera Module
2. Sends them to your cloud backend
3. Speaks greetings through the speaker when a person is identified

### Verify on Pi

```bash
# Check camera
libcamera-hello --timeout 3000

# Check speaker
espeak "Hello, this is a test"

# Check service
systemctl status face-backend-camera
journalctl -u face-backend-camera -f
```

## 5) Register people (from any device)

Open the cloud backend web UI from any browser:

- `https://your-cloud-server.com/` — camera preview (browser mode)
- `https://your-cloud-server.com/upload` — add person + upload photos
- `https://your-cloud-server.com/persons` — view registered people

Or use the API directly:

```bash
# Add person
curl -X POST https://your-cloud-server.com/api/persons \
  -H "Content-Type: application/json" \
  -d '{"name":"Viraj"}'

# Upload photo (person id = 1)
curl -X POST https://your-cloud-server.com/api/persons/1/photo \
  -F "photo=@/path/to/viraj.jpg"
```

## 6) Auto-deploy cloud from GitHub

An auto-deploy workflow is added at `.github/workflows/deploy-pi.yml`.

It deploys only when:

- CI workflow is successful on `main`, or
- You manually trigger deployment from GitHub Actions (`workflow_dispatch`).

### Required GitHub Secrets

In GitHub repo -> Settings -> Secrets and variables -> Actions, add:

- `PI_HOST` : Raspberry Pi public IP / DNS
- `PI_USER` : SSH username (example: `pi`)
- `PI_SSH_KEY` : private key content (the key that can SSH into Pi)
- `PI_PORT` : SSH port (usually `22`)
- `PI_PROJECT_DIR` : project path on Pi (example: `/home/pi/Web`)

### First-time Pi SSH setup (one time)

On your Raspberry Pi:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Paste your GitHub Actions deploy public key into `authorized_keys`.

## 7) Update Pi camera client remotely

When you push code changes that affect `pi_camera_client.py`, update the Pi:

```bash
# SSH into Pi
ssh pi@<PI_IP>
cd ~/Web
git pull
sudo systemctl restart face-backend-camera
```

Or use the existing deploy workflow which handles this automatically.

## 8) Full-stack setup (both on Pi)

If you prefer to run **everything on the Pi** (no cloud server), use the full setup instead:

```bash
cd ~/Web
PROJECT_DIR=$HOME/Web SERVICE_NAME=face-backend ./scripts/pi_first_setup.sh
./scripts/pi_preflight_check.sh
```

This installs the Flask backend + camera client together on the Pi.

## 9) Safety recommendation

- Always deploy from tested `main`.
- Keep last known working commit tag.
- Rollback is now automatic if `/health` fails after deploy.
- For cloud mode, ensure your cloud server has HTTPS enabled.
