import sqlite3, os
DB = os.path.join(os.path.dirname(__file__), "data.db")
code = "VIP100-JW44VD8I".upper().strip()   # غيّر هنا للكود الذي جرّبته
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT id,code,amount,used,used_by_worker_user_id,created_at,used_at FROM coupons WHERE code = ?", (code,))
row = cur.fetchone()
print("exact match ->", row)
cur.execute("SELECT id,code,amount,used FROM coupons WHERE code LIKE ?", ("%"+code.split("-")[-1]+"%",))
print("partial matches ->", cur.fetchall())
conn.close()