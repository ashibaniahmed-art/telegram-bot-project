import os, sqlite3, argparse

DB = os.path.join(os.path.dirname(__file__), "data.db")

parser = argparse.ArgumentParser()
parser.add_argument("codes", nargs="*", help="codes to search (optional)")
args = parser.parse_args()

print("DB path:", os.path.abspath(DB))
if not os.path.exists(DB):
    print("data.db not found.")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()
total = cur.execute("SELECT COUNT(*) FROM coupons").fetchone()[0]
print("Total coupons:", total)
print("--- sample (first 50, repr to show hidden chars) ---")
for row in cur.execute("SELECT id, code, amount, used FROM coupons ORDER BY id LIMIT 50"):
    print(row[0], repr(row[1]), row[2], "used=" + str(row[3]))

if args.codes:
    print("\n--- search results ---")
    for code in args.codes:
        c = code.strip().upper()
        print(f"Search exact (UPPER) for: {c}")
        cur.execute("SELECT id, code, amount, used FROM coupons WHERE UPPER(code)=?", (c,))
        r = cur.fetchone()
        print(" exact ->", r)
        cur.execute("SELECT id, code, amount, used FROM coupons WHERE code LIKE ?", ("%"+c.split("-")[-1]+"%",))
        print(" partial ->", cur.fetchall())

conn.close()