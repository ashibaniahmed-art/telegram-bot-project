import sqlite3
DB='data.db'
conn=sqlite3.connect(DB)
cur=conn.cursor()
cols=[r[1] for r in cur.execute('PRAGMA table_info(workers)').fetchall()]
print('existing cols:', cols)
if 'education_type' not in cols:
    cur.execute("ALTER TABLE workers ADD COLUMN education_type TEXT")
    conn.commit()
    print('added education_type')
else:
    print('education_type already exists')
conn.close()
