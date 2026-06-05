import sqlite3
conn = sqlite3.connect('project.db')
conn.execute("DELETE FROM persons WHERE LOWER(name)=LOWER(?)", ('BugFixUser',))
conn.commit()
print('cleaned')
