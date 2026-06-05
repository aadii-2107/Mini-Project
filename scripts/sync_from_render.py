import argparse
import datetime as dt
import http.cookiejar
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


def normalized_base_url(value: str) -> str:
    base = str(value or "").strip()
    if not base:
        raise ValueError("base_url is required")
    return base.rstrip("/")


def login_and_download_backup(base_url: str, password: str, output_zip: Path) -> None:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    opener.addheaders = [("User-Agent", "face-recognition-sync/1.0")]

    login_url = f"{base_url}/login"
    login_payload = urllib.parse.urlencode({"password": password}).encode("utf-8")
    login_request = urllib.request.Request(login_url, data=login_payload, method="POST")
    opener.open(login_request).read()

    backup_url = f"{base_url}/api/admin/backup"
    response = opener.open(backup_url)
    if getattr(response, "status", 200) != 200:
        body = response.read(2000)
        raise RuntimeError(f"Backup request failed: HTTP {getattr(response, 'status', 'unknown')} {body!r}")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with open(output_zip, "wb") as f:
        shutil.copyfileobj(response, f)


def apply_backup_to_local(backup_zip: Path, target_dir: Path) -> None:
    if not backup_zip.exists():
        raise FileNotFoundError(str(backup_zip))

    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    db_path = target_dir / "project.db"
    faces_path = target_dir / "known_faces"

    if db_path.exists():
        shutil.move(str(db_path), str(target_dir / f"project.db.bak-{timestamp}"))
    if faces_path.exists():
        shutil.move(str(faces_path), str(target_dir / f"known_faces.bak-{timestamp}"))

    with zipfile.ZipFile(backup_zip, "r") as archive:
        archive.extractall(target_dir)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--apply-local", action="store_true")
    parser.add_argument("--target-dir", default="")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    base_url = normalized_base_url(args.base_url)
    output_zip = Path(args.output).expanduser() if args.output else (project_root / "face-data-backup.zip")
    target_dir = Path(args.target_dir).expanduser() if args.target_dir else project_root

    login_and_download_backup(base_url, args.password, output_zip)

    if args.apply_local:
        apply_backup_to_local(output_zip, target_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
