"""(3) POST-CHECK — read-only. Proves zero remaining matches + backup counts."""
import sqlite3

CODES = ("EJL/26-27/254-1", "EJL/26-27/257-2")

def one(db, sql, args=()):
    con = sqlite3.connect(f"file:C:/PZ/app/storage/{db}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchone()[0]
    finally:
        con.close()

remaining_cache = one("wfirma.db",
    "SELECT COUNT(*) FROM wfirma_products "
    "WHERE wfirma_product_id='99' AND product_code IN (?,?)", CODES)
remaining_mirror = one("reservation_queue.db",
    "SELECT COUNT(*) FROM wfirma_product_mirror "
    "WHERE wfirma_id='99' OR (product_code=? AND wfirma_id='')", (CODES[1],))
backup_cache = one("wfirma.db", "SELECT COUNT(*) FROM wfirma_products_collision_backup")
backup_mirror = one("reservation_queue.db",
                    "SELECT COUNT(*) FROM wfirma_product_mirror_collision_backup")

print(f"remaining cache matches:  {remaining_cache}   (required: 0)")
print(f"remaining mirror matches: {remaining_mirror}   (required: 0)")
print(f"backup rows preserved:    cache={backup_cache}, mirror={backup_mirror}   (expected: 2 + 2)")
print("POST-CHECK OK — re-run the 2c mirror backfill (expect wfirma_id_collisions: 0)"
      if remaining_cache == 0 and remaining_mirror == 0
         and backup_cache == 2 and backup_mirror == 2 else
      "POST-CHECK FAILED — STOP, paste this output to the session")
