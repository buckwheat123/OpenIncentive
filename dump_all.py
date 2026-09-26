"""一次性导出数据库全部表：行数 + 列名 + 前 N 行样本。
用法：  .venv\\Scripts\\python dump_all.py [每表行数, 默认5]
输出：  data/_dump.txt （UTF-8，可直接用记事本/VSCode 打开）
"""
import sqlite3, sys, io

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
db = sqlite3.connect("data/app.db")
db.row_factory = sqlite3.Row
cur = db.cursor()
out = io.StringIO()

tabs = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

for t in tabs:
    total = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{t}')")]
    out.write(f"\n===== {t}  (共 {total} 行) =====\n")
    out.write("列: " + ", ".join(cols) + "\n")
    rows = cur.execute(f"SELECT * FROM '{t}' LIMIT {N}").fetchall()
    for r in rows:
        out.write("  " + " | ".join(f"{k}={r[k]}" for k in r.keys()) + "\n")
    if total > N:
        out.write(f"  ...（省略其余 {total - N} 行）\n")

text = out.getvalue()
open("data/_dump.txt", "w", encoding="utf-8").write(text)
print(text)
print(f"\n[已写入 data/_dump.txt]")
db.close()
