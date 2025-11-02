import sqlite3, os, random, string, argparse
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), "data.db")

def make_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate(amount, count, prefix=None):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    created = []
    for _ in range(count):
        code = (prefix or "") + make_code(8)
        try:
            cur.execute("INSERT INTO coupons (code, amount) VALUES (?, ?)", (code, amount))
            created.append(code)
        except Exception:
            # duplicate or db error, try next
            continue
    conn.commit()
    conn.close()
    return created

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--amount", type=int, choices=[60,100], required=True, help="60 أو 100")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--prefix", type=str, help="بادئة اختيارية")
    args = parser.parse_args()
    codes = generate(args.amount, args.count, args.prefix)
    out = f"coupons_{args.amount}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.txt"
    with open(out, "w", encoding="utf-8") as f:
        for c in codes:
            f.write(f"{c}\n")
    print("Generated:", len(codes), "saved to", out)