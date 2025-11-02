import sqlite3, os
db = os.path.join(os.path.dirname(__file__), "data.db")
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS workers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, name TEXT, phone TEXT, work_type TEXT, lat REAL, lon REAL)")
cur.execute("CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT, service TEXT, lat REAL, lon REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
conn.commit()
conn.close()
print('created', db)