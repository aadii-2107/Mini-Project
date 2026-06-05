import argparse
import http.cookiejar
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path


def normalized_base_url(value: str) -> str:
    base = str(value or "").strip()
    if not base:
        raise ValueError("base_url is required")
    return base.rstrip("/")


def zip_known_faces(source_dir: Path, output_zip: Path) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(str(source_dir))

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(Path("known_faces") / file_path.relative_to(source_dir))
                archive.write(file_path, arcname=arcname)


def build_multipart_form(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----faceform-{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for key, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        lines.append(f"{value}\r\n".encode("utf-8"))

    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/zip"

    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
    )
    lines.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    lines.append(file_path.read_bytes())
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(lines)
    content_header = f"multipart/form-data; boundary={boundary}"
    return body, content_header


def login(opener: urllib.request.OpenerDirector, base_url: str, password: str) -> None:
    login_url = f"{base_url}/login"
    login_payload = urllib.parse.urlencode({"password": password}).encode("utf-8")
    login_request = urllib.request.Request(login_url, data=login_payload, method="POST")
    opener.open(login_request).read()


def upload_faces(opener: urllib.request.OpenerDirector, base_url: str, zip_path: Path, mode: str) -> bytes:
    restore_url = f"{base_url}/api/admin/restore-faces"
    body, content_type = build_multipart_form({"mode": mode}, "faces_zip", zip_path)
    request = urllib.request.Request(restore_url, data=body, method="POST")
    request.add_header("Content-Type", content_type)
    request.add_header("Content-Length", str(len(body)))
    response = opener.open(request)
    return response.read()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--faces-dir", default="")
    parser.add_argument("--zip-output", default="")
    parser.add_argument("--mode", default="merge", choices=["merge", "replace"])
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    base_url = normalized_base_url(args.base_url)
    faces_dir = Path(args.faces_dir).expanduser() if args.faces_dir else (project_root / "known_faces")
    zip_output = Path(args.zip_output).expanduser() if args.zip_output else (project_root / "known_faces.zip")

    zip_known_faces(faces_dir, zip_output)

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    opener.addheaders = [("User-Agent", "face-recognition-upload/1.0")]

    login(opener, base_url, args.password)
    response_body = upload_faces(opener, base_url, zip_output, args.mode)
    sys.stdout.buffer.write(response_body)
    if not response_body.endswith(b"\n"):
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main(sys.argv[1:]))
