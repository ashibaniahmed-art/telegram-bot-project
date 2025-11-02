import sqlite3
DB='data.db'
conn=sqlite3.connect(DB)
cur=conn.cursor()
cur.execute("SELECT id,user_id,name,phone,work_type,education_type,worker_code FROM workers WHERE user_id=?",(999999,))
row=cur.fetchone()
print(row)
conn.close()
