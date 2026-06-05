#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/pi/Web}"
SERVICE_NAME="${SERVICE_NAME:-face-backend}"
BRANCH="${BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5000/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-12}"
HEALTH_DELAY_SECONDS="${HEALTH_DELAY_SECONDS:-2}"

cd "$PROJECT_DIR"

echo "[1/5] Fetching latest code from $BRANCH..."
git fetch origin
git checkout "$BRANCH"
PREVIOUS_COMMIT="$(git rev-parse HEAD)"
git pull --ff-only origin "$BRANCH"

echo "[2/5] Activating virtual environment..."
source .venv/bin/activate

echo "[3/5] Installing/updating Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
if [[ -f requirements-pi.txt ]]; then
  pip install -r requirements-pi.txt
fi

echo "[4/5] Restarting services: $SERVICE_NAME ..."
sudo systemctl restart "$SERVICE_NAME"
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}-camera\.service"; then
  sudo systemctl restart "${SERVICE_NAME}-camera"
fi

echo "[5/5] Checking service health with retries..."
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

HEALTH_OK=0
for ((attempt=1; attempt<=HEALTH_RETRIES; attempt++)); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    HEALTH_OK=1
    break
  fi
  sleep "$HEALTH_DELAY_SECONDS"
done

if [[ "$HEALTH_OK" -eq 1 ]]; then
  echo "Health check passed."
  curl -fsS "$HEALTH_URL" && echo
  echo "Update complete."
  exit 0
fi

echo "Health check failed. Rolling back to previous commit: $PREVIOUS_COMMIT"
git reset --hard "$PREVIOUS_COMMIT"
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart "$SERVICE_NAME"
sleep 2
curl -fsS "$HEALTH_URL" && echo
echo "Rollback complete. Service restored to previous commit."

