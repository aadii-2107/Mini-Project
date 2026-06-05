from flask import Flask, jsonify, render_template, request, session, redirect, url_for, send_file, after_this_request
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import tempfile
import zipfile

import numpy as np
from PIL import Image

try:
    import face_recognition
except ImportError:
    face_recognition = None

app = Flask(__name__)
app.secret_key = os.getenv("SESSION_SECRET", "change-me-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Robo@2026")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated
def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized", "login": "/login"}), 401
        return f(*args, **kwargs)
    return decorated
@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("upload_page"))
        error = "Wrong password. Try again."
    return render_template("login.html", error=error)
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", "")) if os.getenv("DATA_DIR") else BASE_DIR
DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = DATA_DIR / "project.db"
KNOWN_FACES_DIR = DATA_DIR / "known_faces"
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MIN_ENROLLMENT_PHOTOS = 10
IDENTIFY_COOLDOWN_SECONDS = 10
FACE_MATCH_THRESHOLD = 0.48
FACE_MATCH_MIN_GAP = 0.03
MATCH_CONFIRMATION_FRAMES = 1
ENABLE_PI_TTS = os.getenv("ENABLE_PI_TTS", "false").strip().lower() in {"1", "true", "yes", "on"}

_pending_match_name: str | None = None
_pending_match_count = 0
_known_face_encodings_cache: list[np.ndarray] = []
_known_face_names_cache: list[str] = []
_known_faces_signature_cache: tuple[int, int] | None = None


def maybe_migrate_persistent_data() -> None:
    if not os.getenv("DATA_DIR"):
        return

    try:
        if DATA_DIR.resolve() == BASE_DIR.resolve():
            return
    except Exception:
        return

    source_db = BASE_DIR / "project.db"
    if source_db.exists() and not DB_PATH.exists():
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_db, DB_PATH)
        except Exception:
            pass

    source_faces = BASE_DIR / "known_faces"
    if source_faces.exists() and not KNOWN_FACES_DIR.exists():
        try:
            KNOWN_FACES_DIR.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_faces, KNOWN_FACES_DIR)
        except Exception:
            pass


maybe_migrate_persistent_data()


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def face_engine_ready() -> bool:
    return face_recognition is not None


def speak_on_pi(text: str) -> None:
    """Best-effort Raspberry Pi speech output using espeak."""
    if not ENABLE_PI_TTS:
        return
    safe_text = text.strip()
    if not safe_text:
        return
    try:
        subprocess.Popen(
            ["espeak", "-s", "145", "-a", "180", safe_text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # Avoid blocking recognition if TTS command is unavailable.
        return


def ensure_face_engine() -> tuple | None:
    if face_engine_ready():
        return None
    return (
        jsonify(
            {
                "error": "face_recognition is not installed",
                "hint": "Install dependencies from requirements.txt",
            }
        ),
        500,
    )


def allowed_image_filename(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_IMAGE_EXTENSIONS


def resolve_person_dir(person_name: str) -> Path:
    direct = KNOWN_FACES_DIR / person_name
    if direct.exists():
        return direct
    if not KNOWN_FACES_DIR.exists():
        return direct
    needle = person_name.casefold()
    for candidate in KNOWN_FACES_DIR.iterdir():
        if candidate.is_dir() and candidate.name.casefold() == needle:
            return candidate
    return direct


def count_person_photos(person_name: str) -> int:
    person_dir = resolve_person_dir(person_name)
    if not person_dir.exists() or not person_dir.is_dir():
        return 0
    return sum(
        1 for path in person_dir.iterdir() if path.is_file() and path.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def get_person_by_name(conn, name: str):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, created_at FROM persons WHERE LOWER(name) = LOWER(%s)",
        (name,),
    )
    return cursor.fetchone()


def get_or_create_person(conn, name: str):
    existing = get_person_by_name(conn, name)
    if existing:
        return existing, False

    created_at = utc_now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO persons (name, created_at) VALUES (%s, %s) RETURNING id, name, created_at",
        (name, created_at),
    )
    created = cursor.fetchone()
    conn.commit()
    return created, True


def known_faces_signature() -> tuple[int, int]:
    if not KNOWN_FACES_DIR.exists():
        return 0, 0

    file_count = 0
    latest_mtime_ns = 0
    for person_dir in KNOWN_FACES_DIR.iterdir():
        if not person_dir.is_dir():
            continue
        for image_path in person_dir.iterdir():
            if not image_path.is_file() or image_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                continue
            file_count += 1
            image_mtime_ns = image_path.stat().st_mtime_ns
            if image_mtime_ns > latest_mtime_ns:
                latest_mtime_ns = image_mtime_ns

    return file_count, latest_mtime_ns


def compute_face_encodings_fast(image: np.ndarray) -> list[np.ndarray]:
    """Fast face encoding with compatibility fallback across library versions."""
    try:
        locations = face_recognition.face_locations(image, number_of_times_to_upsample=0, model="hog")
        return face_recognition.face_encodings(image, known_face_locations=locations, model="small")
    except TypeError:
        # Older wrappers may not support these kwargs.
        return face_recognition.face_encodings(image)


def load_known_face_encodings() -> tuple[list[np.ndarray], list[str]]:
    global _known_face_encodings_cache, _known_face_names_cache, _known_faces_signature_cache

    current_signature = known_faces_signature()
    if _known_faces_signature_cache == current_signature:
        return _known_face_encodings_cache, _known_face_names_cache

    encodings: list[np.ndarray] = []
    names: list[str] = []

    if not KNOWN_FACES_DIR.exists():
        _known_face_encodings_cache = encodings
        _known_face_names_cache = names
        _known_faces_signature_cache = current_signature
        return encodings, names

    for person_dir in KNOWN_FACES_DIR.iterdir():
        if not person_dir.is_dir():
            continue

        person_name = person_dir.name
        for image_path in person_dir.iterdir():
            if image_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                continue
            try:
                image = face_recognition.load_image_file(str(image_path))
                face_encodings = compute_face_encodings_fast(image)
                if face_encodings:
                    encodings.append(face_encodings[0])
                    names.append(person_name)
            except Exception:
                continue

    _known_face_encodings_cache = encodings
    _known_face_names_cache = names
    _known_faces_signature_cache = current_signature
    return encodings, names


def validate_saved_photo(saved_path: Path) -> str | None:
    if face_engine_ready():
        try:
            image = face_recognition.load_image_file(str(saved_path))
            face_encodings = compute_face_encodings_fast(image)
            if len(face_encodings) == 0:
                return "no face found in uploaded photo"
            if len(face_encodings) > 1:
                return "multiple faces found; upload single-face photo"
            return None
        except Exception:
            return "invalid image data"

    try:
        with Image.open(saved_path) as image:
            image.verify()
        return None
    except Exception:
        return "invalid image data"


def save_person_photos(person_name: str, photo_files) -> tuple[list[str], list[dict]]:
    person_dir = resolve_person_dir(person_name)
    person_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    skipped_files: list[dict] = []

    for photo_file in photo_files:
        filename = (photo_file.filename or "").strip()
        if not filename:
            skipped_files.append({"file": "<missing>", "reason": "photo filename is missing"})
            continue
        if not allowed_image_filename(filename):
            skipped_files.append({"file": filename, "reason": "only .jpg, .jpeg, .png files are allowed"})
            continue

        file_ext = Path(filename).suffix.lower()
        saved_name = f"{uuid.uuid4().hex}{file_ext}"
        saved_path = person_dir / saved_name
        photo_file.save(saved_path)

        validation_error = validate_saved_photo(saved_path)
        if validation_error:
            saved_path.unlink(missing_ok=True)
            skipped_files.append({"file": filename, "reason": validation_error})
            continue

        saved_paths.append(str(Path("known_faces") / person_dir.name / saved_name))

    return saved_paths, skipped_files


def is_reliable_face_match(distances: np.ndarray, best_match_index: int) -> tuple[bool, float]:
    best_distance = float(distances[best_match_index])
    if best_distance >= FACE_MATCH_THRESHOLD:
        return False, best_distance

    if len(distances) == 1:
        return True, best_distance

    sorted_distances = np.sort(distances)
    distance_gap = float(sorted_distances[1] - sorted_distances[0])
    if distance_gap < FACE_MATCH_MIN_GAP:
        return False, best_distance

    return True, best_distance


def best_person_match(known_names: list[str], distances: np.ndarray) -> tuple[str | None, float | None, float | None]:
    if len(distances) == 0:
        return None, None, None

    per_person_distances: dict[str, list[float]] = defaultdict(list)
    for index, distance in enumerate(distances):
        per_person_distances[known_names[index]].append(float(distance))

    person_scores: list[tuple[str, float]] = []
    for person_name, person_distance_list in per_person_distances.items():
        person_scores.append((person_name, min(person_distance_list)))

    person_scores.sort(key=lambda item: item[1])
    best_name, best_distance = person_scores[0]
    second_distance = person_scores[1][1] if len(person_scores) > 1 else None
    return best_name, best_distance, second_distance


def init_db() -> None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS persons (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS detections (
                id SERIAL PRIMARY KEY,
                person_id INTEGER,
                raw_name TEXT NOT NULL,
                is_known INTEGER NOT NULL,
                confidence REAL,
                message TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                FOREIGN KEY (person_id) REFERENCES persons(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                phone TEXT,
                department TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                preferred_tone TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_interactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                input_text TEXT,
                response_text TEXT,
                confidence REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def person_as_dict(row: dict) -> dict:
    person_name = row["name"]
    return {
        "id": row["id"],
        "name": person_name,
        "created_at": row["created_at"],
        "photo_count": count_person_photos(person_name),
    }


def detection_as_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "person_id": row["person_id"],
        "name": row["raw_name"],
        "is_known": bool(row["is_known"]),
        "confidence": row["confidence"],
        "welcomeMessage": row["message"],
        "detected_at": row["detected_at"],
    }


def user_as_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "department": row["department"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def user_preference_as_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "preferred_tone": row["preferred_tone"],
        "language": row["language"],
        "updated_at": row["updated_at"],
    }


def user_interaction_as_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "input_text": row["input_text"],
        "response_text": row["response_text"],
        "confidence": row["confidence"],
        "created_at": row["created_at"],
    }


@app.route("/health", methods=["GET"])
def health() -> tuple:
    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def root() -> tuple:
    return render_template("camera.html")


@app.route("/collect", methods=["GET"])
def collect_page() -> str:
    return render_template("collect.html")


@app.route("/api", methods=["GET"])
def api_index() -> tuple:
    return (
        jsonify(
            {
                "message": "Backend is running",
                "health": "/health",
                "collect": "/collect",
                "persons": "/api/persons",
                "upload_photo": "/api/persons/<id>/photo",
                "enroll_person": "/api/enroll",
                "recognize": "/api/recognize",
                "identify_photo": "/api/identify-photo",
                "status": "/api/status",
                "logs": "/api/logs",
                "users": "/api/users",
                "user_details": "/api/users/<id>",
                "user_preferences": "/api/users/<id>/preferences",
                "user_interactions": "/api/users/<id>/interactions",
            }
        ),
        200,
    )


@app.route("/upload", methods=["GET"])
@login_required
def upload_page() -> str:
    return render_template("upload.html")


@app.route("/persons", methods=["GET"])
@login_required
def persons_page() -> str:
    return render_template("persons.html")


@app.route("/api/admin/backup", methods=["GET"])
@login_required
def admin_backup() -> tuple:
    return jsonify({"error": "backup functionality moved to cloud storage"}), 501


@app.route("/api/admin/storage-info", methods=["GET"])
@login_required
def admin_storage_info() -> tuple:
    info: dict = {
        "database_url_set": bool(DATABASE_URL),
        "known_faces_dir": str(KNOWN_FACES_DIR),
        "known_faces_exists": KNOWN_FACES_DIR.exists(),
    }

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt FROM persons")
            row = cursor.fetchone()
            if row:
                info["persons_count"] = int(row["cnt"])
        finally:
            conn.close()
    except Exception as e:
        info["connection_error"] = str(e)

    return jsonify(info), 200


@app.route("/api/admin/restore-faces", methods=["POST"])
@login_required
def admin_restore_faces() -> tuple:
    mode = str(request.form.get("mode", "merge")).strip().lower()
    if mode not in {"merge", "replace"}:
        return jsonify({"error": "mode must be merge or replace"}), 400

    faces_zip = request.files.get("faces_zip")
    if not faces_zip:
        return jsonify({"error": "faces_zip file is required"}), 400

    tmp_zip_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_zip_path = Path(tmp_zip_handle.name)
    tmp_zip_handle.close()

    tmp_extract_dir = Path(tempfile.mkdtemp(prefix="faces-restore-"))

    def cleanup_paths():
        try:
            tmp_zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            shutil.rmtree(tmp_extract_dir, ignore_errors=True)
        except Exception:
            pass

    try:
        faces_zip.save(tmp_zip_path)

        def safe_member_path(member: str) -> Path | None:
            name = str(member or "").replace("\\", "/").lstrip("/")
            if not name or name.endswith("/"):
                return None
            parts = [p for p in name.split("/") if p not in {"", "."}]
            if any(p == ".." for p in parts):
                raise ValueError("unsafe zip path")
            return Path(*parts)

        with zipfile.ZipFile(tmp_zip_path, "r") as archive:
            for member in archive.namelist():
                rel = safe_member_path(member)
                if rel is None:
                    continue
                target_path = tmp_extract_dir / rel
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        faces_root = tmp_extract_dir / "known_faces"
        if not faces_root.exists():
            matches = [p for p in tmp_extract_dir.rglob("known_faces") if p.is_dir()]
            if matches:
                faces_root = matches[0]
            else:
                faces_root = tmp_extract_dir

        if not faces_root.exists() or not faces_root.is_dir():
            return jsonify({"error": "known_faces directory not found in zip"}), 400

        KNOWN_FACES_DIR.mkdir(parents=True, exist_ok=True)

        if mode == "replace" and KNOWN_FACES_DIR.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup_dir = KNOWN_FACES_DIR.parent / f"known_faces.bak-{timestamp}"
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            if KNOWN_FACES_DIR.exists():
                shutil.move(str(KNOWN_FACES_DIR), str(backup_dir))
            KNOWN_FACES_DIR.mkdir(parents=True, exist_ok=True)

        copied = 0
        skipped = 0
        for file_path in faces_root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                skipped += 1
                continue

            try:
                rel = file_path.relative_to(faces_root)
            except ValueError:
                skipped += 1
                continue

            if len(rel.parts) < 2:
                skipped += 1
                continue

            dest_path = KNOWN_FACES_DIR / rel
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.exists() and mode == "merge":
                skipped += 1
                continue
            shutil.copy2(file_path, dest_path)
            copied += 1

        global _known_faces_signature_cache
        _known_faces_signature_cache = None

        return jsonify({"restored": True, "mode": mode, "copied": copied, "skipped": skipped}), 200
    except ValueError as e:
        cleanup_paths()
        return jsonify({"error": str(e)}), 400
    except Exception:
        cleanup_paths()
        return jsonify({"error": "restore failed"}), 500
    finally:
        cleanup_paths()


@app.route("/api/persons", methods=["GET"])
def list_persons() -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, created_at FROM persons ORDER BY id DESC"
        )
        rows = cursor.fetchall()
        return jsonify([person_as_dict(row) for row in rows]), 200
    finally:
        conn.close()


@app.route("/api/persons", methods=["POST"])
@api_login_required
def create_person() -> tuple:
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    conn = get_db_connection()
    try:
        existing = get_person_by_name(conn, name)
        if existing:
            return jsonify({"error": "person already exists"}), 409

        created_at = utc_now()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO persons (name, created_at) VALUES (%s, %s) RETURNING id",
            (name, created_at),
        )
        result = cursor.fetchone()
        conn.commit()

        return (
            jsonify(
                {
                    "id": result["id"],
                    "name": name,
                    "created_at": created_at,
                }
            ),
            201,
        )
    finally:
        conn.close()


@app.route("/api/enroll", methods=["POST"])
def enroll_person() -> tuple:
    global _known_faces_signature_cache

    name = str(request.form.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    photo_files = request.files.getlist("photo")
    if len(photo_files) < MIN_ENROLLMENT_PHOTOS:
        return (
            jsonify(
                {
                    "error": f"at least {MIN_ENROLLMENT_PHOTOS} images are required",
                    "minimum_required": MIN_ENROLLMENT_PHOTOS,
                    "received": len(photo_files),
                }
            ),
            400,
        )

    conn = get_db_connection()
    try:
        person, was_created = get_or_create_person(conn, name)
    finally:
        conn.close()
    
    person_id = person["id"] if isinstance(person, dict) else person[0]
    person_name = person["name"] if isinstance(person, dict) else person[1]


    saved_paths, skipped_files = save_person_photos(person_name, photo_files)
    total_photos = count_person_photos(person_name)

    if not saved_paths:
        if was_created and total_photos == 0:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM persons WHERE id = %s", (person_id,))
                conn.commit()
            finally:
                conn.close()
            person_dir = KNOWN_FACES_DIR / person_name
            if person_dir.exists():
                shutil.rmtree(person_dir)
        return (
            jsonify(
                {
                    "saved": False,
                    "person_id": person_id,
                    "person_name": person_name,
                    "photo_paths": [],
                    "saved_count": 0,
                    "total_photos": total_photos,
                    "minimum_required": MIN_ENROLLMENT_PHOTOS,
                    "skipped": skipped_files,
                    "error": "no valid photos were uploaded",
                }
            ),
            400,
        )

    _known_faces_signature_cache = None
    completed = total_photos >= MIN_ENROLLMENT_PHOTOS
    status_code = 201 if completed else 400
    return (
        jsonify(
            {
                "saved": completed,
                "person_id": person_id,
                "person_name": person_name,
                "photo_paths": saved_paths,
                "saved_count": len(saved_paths),
                "total_photos": total_photos,
                "minimum_required": MIN_ENROLLMENT_PHOTOS,
                "completed": completed,
                "face_engine_ready": face_engine_ready(),
                "skipped": skipped_files,
                "message": (
                    f"{person_name} has been registered successfully."
                    if completed
                    else f"{person_name} currently has {total_photos} valid photos. At least {MIN_ENROLLMENT_PHOTOS} are required."
                ),
            }
        ),
        status_code,
    )


@app.route("/api/persons/<int:person_id>", methods=["DELETE"])
@api_login_required
def delete_person(person_id: int) -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM persons WHERE id = %s", (person_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "person not found"}), 404
        person_name = row["name"]
        cursor.execute("DELETE FROM persons WHERE id = %s", (person_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "person not found"}), 404
        import shutil
        person_dir = KNOWN_FACES_DIR / person_name
        if person_dir.exists():
            shutil.rmtree(person_dir)
        return jsonify({"deleted": True}), 200
    finally:
        conn.close()

@app.route("/api/persons/<int:person_id>/photos", methods=["GET"])
@api_login_required
def list_person_photos(person_id: int) -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM persons WHERE id = %s", (person_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "person not found"}), 404
        person_name = row["name"]
        person_dir = resolve_person_dir(person_name)
        photos = []
        if person_dir.exists():
            for f in sorted(person_dir.iterdir()):
                if f.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                    photos.append(f.name)
        return jsonify({"person_id": person_id, "person_name": person_name, "photos": photos}), 200
    finally:
        conn.close()


@app.route("/api/persons/<int:person_id>/photo/<path:photo_name>", methods=["DELETE"])
@api_login_required
def delete_person_photo(person_id: int, photo_name: str) -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM persons WHERE id = %s", (person_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "person not found"}), 404
        person_name = row["name"]
        photo_path = resolve_person_dir(person_name) / Path(photo_name).name
        if not photo_path.exists():
            return jsonify({"error": "photo not found"}), 404
        photo_path.unlink()
        return jsonify({"deleted": True, "photo": photo_name}), 200
    finally:
        conn.close()

@app.route("/api/persons/<int:person_id>/photo/<path:photo_name>", methods=["GET"])
@api_login_required
def serve_person_photo(person_id: int, photo_name: str) -> tuple:
    from flask import send_file
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM persons WHERE id = %s", (person_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "person not found"}), 404
        person_name = row["name"]
        photo_path = resolve_person_dir(person_name) / Path(photo_name).name
        if not photo_path.exists():
            return jsonify({"error": "photo not found"}), 404
        return send_file(photo_path)
    finally:
        conn.close()

@app.route("/api/persons/<int:person_id>/photo", methods=["POST"])
@api_login_required
def upload_person_photo(person_id: int) -> tuple:
    global _known_faces_signature_cache

    photo_files = request.files.getlist("photo")
    if not photo_files:
        return jsonify({"error": "photo file is required"}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name FROM persons WHERE id = %s",
            (person_id,),
        )
        person = cursor.fetchone()
    finally:
        conn.close()

    if not person:
        return jsonify({"error": "person not found"}), 404

    person_name = person["name"]
    saved_paths, skipped_files = save_person_photos(person_name, photo_files)

    if not saved_paths:
        return (
            jsonify(
                {
                    "saved": False,
                    "person_id": person_id,
                    "person_name": person_name,
                    "photo_paths": [],
                    "skipped": skipped_files,
                    "error": "no valid photos were uploaded",
                }
            ),
            400,
        )

    _known_faces_signature_cache = None
    return (
        jsonify(
            {
                "saved": True,
                "person_id": person_id,
                "person_name": person_name,
                "photo_paths": saved_paths,
                "saved_count": len(saved_paths),
                "face_engine_ready": face_engine_ready(),
                "skipped": skipped_files,
            }
        ),
        201,
    )


@app.route("/api/recognize", methods=["POST"])
def recognize() -> tuple:
    data = request.get_json(silent=True) or {}
    raw_name = str(data.get("name", "")).strip()
    confidence = data.get("confidence")

    if not raw_name:
        return jsonify({"error": "name is required"}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name FROM persons WHERE LOWER(name) = LOWER(%s)",
            (raw_name,),
        )
        person = cursor.fetchone()

        if person:
            resolved_name = person["name"]
            person_id = person["id"]
            is_known = 1
            message = f"Welcome {resolved_name} to Computer Science Department"
        else:
            resolved_name = "Guest"
            person_id = None
            is_known = 0
            message = "Welcome Guest to Computer Science Department"

        detected_at = utc_now()
        cursor.execute(
            """
            INSERT INTO detections (person_id, raw_name, is_known, confidence, message, detected_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (person_id, resolved_name, is_known, confidence, message, detected_at),
        )
        result = cursor.fetchone()
        conn.commit()

        return (
            jsonify(
                {
                    "id": result["id"],
                    "name": resolved_name,
                    "is_known": bool(is_known),
                    "welcomeMessage": message,
                    "detected_at": detected_at,
                }
            ),
            201,
        )
    finally:
        conn.close()


@app.route("/api/identify-photo", methods=["POST"])
def identify_photo() -> tuple:
    global _pending_match_name, _pending_match_count

    engine_error = ensure_face_engine()
    if engine_error:
        return engine_error

    if "photo" not in request.files:
        return jsonify({"error": "photo file is required"}), 400

    photo_file = request.files["photo"]
    filename = (photo_file.filename or "").strip()
    if not filename:
        return jsonify({"error": "photo filename is missing"}), 400
    if not allowed_image_filename(filename):
        return jsonify({"error": "only .jpg, .jpeg, .png files are allowed"}), 400

    image = face_recognition.load_image_file(photo_file.stream)
    face_encodings = compute_face_encodings_fast(image)
    if len(face_encodings) == 0:
        return (
            jsonify(
                {
                    "state": "waiting",
                    "name": None,
                    "welcomeMessage": "No face found",
                }
            ),
            200,
        )
    if len(face_encodings) > 1:
        return (
            jsonify(
                {
                    "state": "waiting",
                    "name": None,
                    "welcomeMessage": "Multiple faces found",
                }
            ),
            200,
        )

    probe_encoding = face_encodings[0]
    known_encodings, known_names = load_known_face_encodings()

    resolved_name = "Guest"
    person_id = None
    is_known = 0
    confidence = 0.0
    message = "Welcome Guest to Computer Science Department"

    if known_encodings:
        distances = face_recognition.face_distance(known_encodings, probe_encoding)
        best_match_index = int(np.argmin(distances))
        is_reliable_match, best_distance = is_reliable_face_match(distances, best_match_index)
        best_person_name, best_person_distance, second_person_distance = best_person_match(
            known_names, distances
        )
        if best_person_distance is not None and best_person_distance <= FACE_MATCH_THRESHOLD:
            if second_person_distance is None or (second_person_distance - best_person_distance) >= FACE_MATCH_MIN_GAP:
                is_reliable_match = True
                best_distance = best_person_distance

        if is_reliable_match:
            candidate_name = best_person_name or known_names[best_match_index]
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, name FROM persons WHERE LOWER(name) = LOWER(%s)",
                    (candidate_name,),
                )
                person = cursor.fetchone()
            finally:
                conn.close()

            if person:
                if _pending_match_name == candidate_name:
                    _pending_match_count += 1
                else:
                    _pending_match_name = candidate_name
                    _pending_match_count = 1

                if _pending_match_count < MATCH_CONFIRMATION_FRAMES:
                    return (
                        jsonify(
                            {
                                "state": "waiting",
                                "name": candidate_name,
                                "welcomeMessage": "Hold still for confirmation",
                            }
                        ),
                        200,
                    )

                resolved_name = person["name"]
                person_id = person["id"]
                is_known = 1
                confidence = max(0.0, min(1.0, 1.0 - best_distance))
                message = f"Welcome {resolved_name} to Computer Science Department"
                speak_on_pi(message)
                _pending_match_name = None
                _pending_match_count = 0
        else:
            _pending_match_name = None
            _pending_match_count = 0

    detected_at = utc_now()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, person_id, raw_name, is_known, confidence, message, detected_at
            FROM detections
            ORDER BY id DESC
            LIMIT 1
            """
        )
        latest_row = cursor.fetchone()
        if latest_row:
            latest_time = datetime.fromisoformat(latest_row["detected_at"])
            current_time = datetime.fromisoformat(detected_at)
            seconds_since_last = (current_time - latest_time).total_seconds()
            same_person = latest_row["raw_name"] == resolved_name
            if same_person and seconds_since_last < IDENTIFY_COOLDOWN_SECONDS:
                return (
                    jsonify(
                        {
                            "state": "cooldown",
                            "id": latest_row["id"],
                            "name": latest_row["raw_name"],
                            "is_known": bool(latest_row["is_known"]),
                            "confidence": round(float(latest_row["confidence"] or 0.0), 4),
                            "welcomeMessage": latest_row["message"],
                            "detected_at": latest_row["detected_at"],
                            "cooldown_active": True,
                        }
                    ),
                    200,
                )

        cursor.execute(
            """
            INSERT INTO detections (person_id, raw_name, is_known, confidence, message, detected_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (person_id, resolved_name, is_known, confidence, message, detected_at),
        )
        result = cursor.fetchone()
        conn.commit()
    finally:
        conn.close()

    return (
        jsonify(
            {
                "state": "identified",
                "id": result["id"],
                "name": resolved_name,
                "is_known": bool(is_known),
                "confidence": round(confidence, 4),
                "welcomeMessage": message,
                "detected_at": detected_at,
            }
        ),
        201,
    )


@app.route("/api/status", methods=["GET"])
def latest_status() -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, person_id, raw_name, is_known, confidence, message, detected_at
            FROM detections
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()

        if not row:
            return (
                jsonify(
                    {
                        "name": "Waiting...",
                        "is_known": False,
                        "welcomeMessage": "System ready.",
                        "detected_at": None,
                    }
                ),
                200,
            )

        return jsonify(detection_as_dict(row)), 200
    finally:
        conn.close()


@app.route("/api/logs", methods=["GET"])
def logs() -> tuple:
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, person_id, raw_name, is_known, confidence, message, detected_at
            FROM detections
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()

        return jsonify([detection_as_dict(row) for row in rows]), 200
    finally:
        conn.close()


@app.route("/api/users", methods=["GET"])
def list_users() -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, email, phone, department, created_at, updated_at
            FROM users
            ORDER BY id DESC
            """
        )
        rows = cursor.fetchall()
        return jsonify([user_as_dict(row) for row in rows]), 200
    finally:
        conn.close()


@app.route("/api/users", methods=["POST"])
def create_user() -> tuple:
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip() or None
    phone = str(data.get("phone", "")).strip() or None
    department = str(data.get("department", "")).strip() or None

    if not name:
        return jsonify({"error": "name is required"}), 400

    now = utc_now()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (name, email, phone, department, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, name, email, phone, department, created_at, updated_at
            """,
            (name, email, phone, department, now, now),
        )
        row = cursor.fetchone()
        conn.commit()
        return jsonify(user_as_dict(row)), 201
    except psycopg2.IntegrityError:
        return jsonify({"error": "email already exists"}), 409
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id: int) -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, email, phone, department, created_at, updated_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "user not found"}), 404
        return jsonify(user_as_dict(row)), 200
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>", methods=["PUT"])
def update_user(user_id: int) -> tuple:
    data = request.get_json(silent=True) or {}

    updates: list[str] = []
    values: list = []

    if "name" in data:
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        updates.append("name = ?")
        values.append(name)

    if "email" in data:
        email = str(data.get("email", "")).strip() or None
        updates.append("email = ?")
        values.append(email)

    if "phone" in data:
        phone = str(data.get("phone", "")).strip() or None
        updates.append("phone = ?")
        values.append(phone)

    if "department" in data:
        department = str(data.get("department", "")).strip() or None
        updates.append("department = ?")
        values.append(department)

    if not updates:
        return jsonify({"error": "no valid fields to update"}), 400

    updates.append("updated_at = ?")
    values.append(utc_now())
    values.append(user_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        update_clause = ', '.join(updates)
        cursor.execute(
            f"UPDATE users SET {update_clause} WHERE id = %s",
            tuple(values),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"error": "user not found"}), 404
        conn.commit()

        cursor.execute(
            """
            SELECT id, name, email, phone, department, created_at, updated_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        return jsonify(user_as_dict(row)), 200
    except psycopg2.IntegrityError:
        return jsonify({"error": "email already exists"}), 409
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id: int) -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_preferences WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_interactions WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "user not found"}), 404
        return jsonify({"deleted": True}), 200
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/preferences", methods=["GET"])
def get_user_preferences(user_id: int) -> tuple:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "user not found"}), 404

        cursor.execute(
            """
            SELECT id, user_id, preferred_tone, language, updated_at
            FROM user_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"user_id": user_id, "preferred_tone": None, "language": "en"}), 200
        return jsonify(user_preference_as_dict(row)), 200
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/preferences", methods=["POST"])
def upsert_user_preferences(user_id: int) -> tuple:
    data = request.get_json(silent=True) or {}
    preferred_tone = str(data.get("preferred_tone", "")).strip() or None
    language = str(data.get("language", "en")).strip() or "en"
    updated_at = utc_now()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "user not found"}), 404

        cursor.execute(
            "SELECT id FROM user_preferences WHERE user_id = %s",
            (user_id,),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE user_preferences
                SET preferred_tone = %s, language = %s, updated_at = %s
                WHERE user_id = %s
                """,
                (preferred_tone, language, updated_at, user_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO user_preferences (user_id, preferred_tone, language, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, preferred_tone, language, updated_at),
            )
        conn.commit()

        cursor.execute(
            """
            SELECT id, user_id, preferred_tone, language, updated_at
            FROM user_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        return jsonify(user_preference_as_dict(row)), 200
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/interactions", methods=["GET"])
def list_user_interactions(user_id: int) -> tuple:
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "user not found"}), 404

        cursor.execute(
            """
            SELECT id, user_id, input_text, response_text, confidence, created_at
            FROM user_interactions
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        return jsonify([user_interaction_as_dict(row) for row in rows]), 200
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/interactions", methods=["POST"])
def create_user_interaction(user_id: int) -> tuple:
    data = request.get_json(silent=True) or {}
    input_text = str(data.get("input_text", "")).strip() or None
    response_text = str(data.get("response_text", "")).strip() or None
    confidence = data.get("confidence")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "user not found"}), 404

        created_at = utc_now()
        cursor.execute(
            """
            INSERT INTO user_interactions (user_id, input_text, response_text, confidence, created_at)
            VALUES (%s, %s, %s, %s, %s) RETURNING id, user_id, input_text, response_text, confidence, created_at
            """,
            (user_id, input_text, response_text, confidence, created_at),
        )
        row = cursor.fetchone()
        conn.commit()
        return jsonify(user_interaction_as_dict(row)), 201
    finally:
        conn.close()


init_db()

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)
