import sqlite3
DB='data.db'
conn=sqlite3.connect(DB)
cur=conn.cursor()
cur.execute("PRAGMA table_info(workers)")
rows=cur.fetchall()
for r in rows:
    print(r)
conn.close()
