"""(1) PRE-CHECK — read-only. Prints the exact rows the cleanup would touch.
Operator confirms ONLY the two expected test rows (+ mirror rows) appear."""
import sqlite3

CODES = ("EJL/26-27/254-1", "EJL/26-27/257-2")

def rows(db, sql, args=()):
    con = sqlite3.connect(f"file:C:/PZ/app/storage/{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()

print("== wfirma_products rows matching the delete predicate ==")
cache = rows("wfirma.db",
    "SELECT rowid, product_code, wfirma_product_id, product_name_pl, sync_status, "
    "created_at, updated_at FROM wfirma_products "
    "WHERE wfirma_product_id='99' AND product_code IN (?,?)", CODES)
for r in cache: print(" ", r)
print(f"cache rows matched: {len(cache)}   (expected: 2)")

print("== wfirma_product_mirror rows matching the delete predicate ==")
mirror = rows("reservation_queue.db",
    "SELECT rowid, wfirma_id, product_code, sync_version, last_sync, deleted_flag "
    "FROM wfirma_product_mirror "
    "WHERE wfirma_id='99' OR (product_code=? AND wfirma_id='')", (CODES[1],))
for r in mirror: print(" ", r)
print(f"mirror rows matched: {len(mirror)}   (expected: 2)")

print("PRE-CHECK OK — proceed to (2) collision_fix.py"
      if len(cache) == 2 and len(mirror) == 2 else
      "PRE-CHECK MISMATCH — STOP, paste this output to the session")
