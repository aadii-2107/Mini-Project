import sqlite3
conn = sqlite3.connect('project.db')
row = conn.execute("SELECT id, name FROM persons WHERE LOWER(name)=LOWER(?)", ('BugFixUser',)).fetchone()
print(row)
