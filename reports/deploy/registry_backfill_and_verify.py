"""Defect-2 fix WITH bolted-on verification (operator amendment, 2026-07-03).

Runs the C-3g registry backfill tool, then IMMEDIATELY verifies
service_product_registry exists and echoes the copied count.
If the verification query still errors after the tool run, prints the
operator-mandated STOP: the repository diagnosis is wrong — reinvestigate.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, r"C:\PZ-deploy-w12\service")
from tools.backfill_service_product_registry import backfill  # noqa: E402

STORAGE = Path(r"C:\PZ\app\storage")

result = backfill(STORAGE)
print("backfill result:", result)
print(f"copied count: {len(result['copied'])}")

try:
    con = sqlite3.connect(f"file:{STORAGE / 'proforma_links.db'}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM service_product_registry").fetchone()[0]
    rows = con.execute(
        "SELECT charge_type, product_name FROM service_product_registry").fetchall()
    con.close()
    print(f"service_product_registry EXISTS — rows: {n} {rows}")
    if n > 0 and len(result["copied"]) > 0:
        print("REGISTRY VERIFIED — Defect 2 cured (copied > 0).")
        sys.exit(0)
    if n > 0:
        print("REGISTRY ALREADY POPULATED before this run — idempotent success "
              "(criterion condition 5, second branch).")
        sys.exit(0)
    print("table exists but EMPTY and copied = 0 — STOP, paste this output "
          "to the session.")
    sys.exit(1)
except sqlite3.OperationalError as exc:
    print(f"VERIFICATION FAILED after tool run: {exc}")
    print("STOP — the repository diagnosis is wrong; reinvestigate. "
          "Do not continue the deployment.")
    sys.exit(2)
