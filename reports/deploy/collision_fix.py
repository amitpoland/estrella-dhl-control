"""(2) BACKUP THEN DELETE — transactional per database (single connection,
backup table + delete committed together; rollback on any count mismatch)."""
import sqlite3
import sys

CODES = ("EJL/26-27/254-1", "EJL/26-27/257-2")
ok = True

# ── wfirma.db: cache claims ──
con = sqlite3.connect(r"C:\PZ\app\storage\wfirma.db")
try:
    con.execute("BEGIN")
    con.execute(
        "CREATE TABLE IF NOT EXISTS wfirma_products_collision_backup AS "
        "SELECT * FROM wfirma_products "
        "WHERE wfirma_product_id='99' AND product_code IN (?,?)", CODES)
    backed = con.execute(
        "SELECT COUNT(*) FROM wfirma_products_collision_backup").fetchone()[0]
    cur = con.execute(
        "DELETE FROM wfirma_products "
        "WHERE wfirma_product_id='99' AND product_code IN (?,?)", CODES)
    deleted = cur.rowcount
    print(f"wfirma.db: backup rows={backed}  deleted rows={deleted}")
    if backed == deleted == 2:
        con.commit()
        print("wfirma.db: COMMITTED")
    else:
        con.rollback()
        ok = False
        print("wfirma.db: COUNT MISMATCH -> ROLLED BACK. STOP; paste output.")
finally:
    con.close()

# ── reservation_queue.db: mirror rows ──
con = sqlite3.connect(r"C:\PZ\app\storage\reservation_queue.db")
try:
    con.execute("BEGIN")
    con.execute(
        "CREATE TABLE IF NOT EXISTS wfirma_product_mirror_collision_backup AS "
        "SELECT * FROM wfirma_product_mirror "
        "WHERE wfirma_id='99' OR (product_code=? AND wfirma_id='')", (CODES[1],))
    backed = con.execute(
        "SELECT COUNT(*) FROM wfirma_product_mirror_collision_backup").fetchone()[0]
    cur = con.execute(
        "DELETE FROM wfirma_product_mirror "
        "WHERE wfirma_id='99' OR (product_code=? AND wfirma_id='')", (CODES[1],))
    deleted = cur.rowcount
    print(f"reservation_queue.db: backup rows={backed}  deleted rows={deleted}")
    if backed == deleted == 2:
        con.commit()
        print("reservation_queue.db: COMMITTED")
    else:
        con.rollback()
        ok = False
        print("reservation_queue.db: COUNT MISMATCH -> ROLLED BACK. STOP; paste output.")
finally:
    con.close()

sys.exit(0 if ok else 1)
