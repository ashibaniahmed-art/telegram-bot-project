import sqlite3, os
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT id, user_id, name, phone, created_at FROM subscribers ORDER BY id")
rows = cur.fetchall()
if not rows:
    print("No subscribers found.")
else:
    for r in rows:
        print(f"id={r[0]}  user_id={r[1]}  name={r[2]!s}  phone={r[3]!s}  created_at={r[4]!s}")
conn.close()


