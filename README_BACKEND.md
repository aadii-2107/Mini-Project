# Backend Working Model

This project is now backend-first with a SQLite database.

## Setup (Windows PowerShell)

1. Create virtual environment:
   - `python -m venv .venv`
2. If activation is blocked by PowerShell policy, allow it for current terminal only:
   - `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
3. Activate environment:
   - `.venv\Scripts\Activate.ps1`
4. Install dependencies:
   - `pip install -r requirements.txt`
5. Run server:
   - `python app.py`

### No-Activation Alternative

If you do not want to change PowerShell policy, run using venv Python directly:

- `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- `.\.venv\Scripts\python.exe app.py`

Server runs at `http://127.0.0.1:5000`.

SQLite database file: `project.db` (auto-created on first run).

## API Endpoints

- `GET /health` -> service status
- `GET /api/persons` -> list registered persons
- `POST /api/persons` -> add known person
- `DELETE /api/persons/<id>` -> delete person
- `POST /api/persons/<id>/photo` -> upload training photo for person
- `POST /api/recognize` -> log recognition event
- `POST /api/identify-photo` -> identify person from uploaded image
- `GET /api/status` -> latest recognition
- `GET /api/logs?limit=20` -> recent logs

## Example Requests

Add person:

```bash
curl -X POST http://127.0.0.1:5000/api/persons ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Rahul\"}"
```

Recognize person:

```bash
curl -X POST http://127.0.0.1:5000/api/recognize ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Rahul\",\"confidence\":0.93}"
```

Recognize unknown person:

```bash
curl -X POST http://127.0.0.1:5000/api/recognize ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Unknown\"}"
```

Upload photo for a person (id = 1):

```bash
curl -X POST http://127.0.0.1:5000/api/persons/1/photo ^
  -F "photo=@D:\path\to\viraj.jpg"
```

Identify person using photo:

```bash
curl -X POST http://127.0.0.1:5000/api/identify-photo ^
  -F "photo=@D:\path\to\test.jpg"
```

## Notes for Photo Recognition

- Install all dependencies from `requirements.txt`.
- `face-recognition` may require C++ build tools on Windows for first install.
- Upload clear single-face photos only.
