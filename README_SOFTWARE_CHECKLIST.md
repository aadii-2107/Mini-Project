# Software Completion Checklist (Before Hardware)

Use this checklist to finish software setup end-to-end.

## A) GitHub

- [ ] Push current project changes to `main`
- [ ] Confirm CI passes in GitHub Actions
- [ ] Add Secrets:
  - [ ] `PI_HOST`
  - [ ] `PI_USER`
  - [ ] `PI_SSH_KEY`
  - [ ] `PI_PORT`
  - [ ] `PI_PROJECT_DIR`

## B) Raspberry Pi First Setup

On Raspberry Pi:

```bash
cd /home/pi/Web
chmod +x scripts/pi_first_setup.sh scripts/pi_preflight_check.sh scripts/update_on_pi.sh
PROJECT_DIR=/home/pi/Web SERVICE_NAME=face-backend ./scripts/pi_first_setup.sh
./scripts/pi_preflight_check.sh
```

## C) Functional App Testing

- [ ] `GET /health` returns `{"status":"ok"}`
- [ ] Create person via `/api/persons`
- [ ] Upload person photo via `/api/persons/<id>/photo`
- [ ] Identify photo via `/api/identify-photo`
- [ ] Speaker says greeting with detected name

## C2) Pi Camera + Speaker Testing

- [ ] `libcamera-hello --timeout 3000` shows camera preview
- [ ] `espeak "Hello test"` plays through speaker
- [ ] `python pi_camera_client.py` captures frames and sends to backend
- [ ] Known person identified → greeting spoken through speaker
- [ ] `face-backend-camera` systemd service running

## D) Deployment Testing

- [ ] Push small code change to `main`
- [ ] Confirm `CI` workflow success
- [ ] Confirm `Deploy to Raspberry Pi` workflow success
- [ ] Confirm Pi app auto-updated

## E) Safety Testing

- [ ] Test manual update: `./scripts/update_on_pi.sh`
- [ ] Simulate bad deploy and confirm rollback happens
- [ ] Tag stable release (`v1-software-stable`)

## F) Ready for Hardware

Start hardware integration only after all checkboxes above are complete.
