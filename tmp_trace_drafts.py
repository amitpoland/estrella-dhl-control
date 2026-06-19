import sqlite3, json

con = sqlite3.connect(r"file:C:\PZ\storage\proforma_links.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=== draft_events for 32/33 ===")
for r in cur.execute("SELECT * FROM proforma_draft_events WHERE draft_id IN (32,33) ORDER BY id"):
    d = dict(r)
    dj = d.get("detail_json") or ""
    if len(dj) > 300:
        d["detail_json"] = dj[:300] + "...[TRUNC]"
    print(json.dumps(d, ensure_ascii=False, default=str))

print()
print("=== draft 32 editable_lines: design_no J4007R08118 lines ===")
row = cur.execute("SELECT editable_lines_json FROM proforma_drafts WHERE id=32").fetchone()
lines = json.loads(row[0])
print("total lines:", len(lines))
for ln in lines:
    if "J4007R08118" in (ln.get("design_no") or ""):
        print(json.dumps(ln, ensure_ascii=False))
print()
print("all design_no -> product_code pairs (draft 32):")
from collections import defaultdict
m = defaultdict(set)
for ln in lines:
    m[ln.get("design_no")].add(ln.get("product_code"))
for k, v in m.items():
    flag = "  <-- AMBIGUOUS" if len(v) > 1 else ""
    print(f"  {k}: {sorted(v)}{flag}")
