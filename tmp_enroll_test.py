import json
import sqlite3
import urllib.request
import uuid
from pathlib import Path

boundary = '----' + uuid.uuid4().hex
img_path = Path(r'C:\Users\ASUS\OneDrive\Documents\Desktop\Mini Project\face-recognition-main\known_faces\Aditya\1076e80fe9a04a6a8c1782c88cdbf3ad.jpeg')
img = img_path.read_bytes()
name = 'BugFixUser'
parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode()]
parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="face-{i+1}.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + img + b'\r\n' for i in range(10)]
parts.append(f'--{boundary}--\r\n'.encode())
body = b''.join(parts)
req = urllib.request.Request('http://127.0.0.1:5000/api/enroll', data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
with urllib.request.urlopen(req) as response:
    payload = json.loads(response.read().decode())
    print('HTTP', response.status)
    print(json.dumps(payload, indent=2))

conn = sqlite3.connect('project.db')
row = conn.execute("SELECT id, name FROM persons WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
print('DB_ROW', row)
photos_dir = Path('known_faces') / name
count = len([path for path in photos_dir.iterdir() if path.is_file()]) if photos_dir.exists() else 0
print('PHOTO_DIR_EXISTS', photos_dir.exists())
print('PHOTO_COUNT', count)
