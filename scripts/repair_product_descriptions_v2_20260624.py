"""
repair_product_descriptions_v2_20260624.py
============================================
Second pass: the v1 script used product_descriptions.description_en (which was
the generator's English, e.g. 'ring with diamonds') instead of the richer
invoice_lines.description ('PCS, 14KT Gold, LGD Stud Jewell Ring').

This script fixes the 42 rows that got the generic fallback
'Wyrób jubilerski — wyrób jubilerski do noszenia.' by:
  1. Looking up invoice_lines.description for each product code (mandatory — not stored description_en)
  2. Deleting the under-specified row
  3. Re-running get_description_block() with the real invoice English

Safety:
  - Only touches source='auto' rows with the generic fallback description_pl
  - Never touches GLOBAL/* aggregate rows or source='manual' rows
  - Skips any product code with no invoice_lines.description row
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROD_DB      = Path("C:/PZ/storage/documents.db")
SERVICE_ROOT = Path(__file__).resolve().parent.parent / "service"

GENERIC_FALLBACK = "Wyrób jubilerski — wyrób jubilerski do noszenia."

TARGET_SQL = """
    SELECT product_code, item_type
    FROM product_descriptions
    WHERE source = 'auto'
      AND description_pl = ?
      AND product_code NOT LIKE 'GLOBAL%'
    ORDER BY product_code
"""


def main() -> int:
    sys.path.insert(0, str(SERVICE_ROOT))

    import io
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

    con = sqlite3.connect(str(PROD_DB))
    con.row_factory = sqlite3.Row

    targets = con.execute(TARGET_SQL, (GENERIC_FALLBACK,)).fetchall()
    print(f"Rows with generic fallback description: {len(targets)}")

    if not targets:
        print("Nothing to fix.")
        con.close()
        return 0

    # Build invoice_lines.description lookup (always from invoice_lines, never stored description_en)
    inv_en_map: dict[str, str] = {}
    for r in targets:
        pc = r["product_code"]
        inv = con.execute(
            "SELECT description FROM invoice_lines WHERE product_code=? LIMIT 1",
            (pc,),
        ).fetchone()
        inv_en_map[pc] = (inv["description"] if inv else "").strip() if inv else ""

    # Delete the rows that will be regenerated
    pcs_to_regen = [r["product_code"] for r in targets if inv_en_map.get(r["product_code"])]
    pcs_skip     = [r["product_code"] for r in targets if not inv_en_map.get(r["product_code"])]

    if pcs_skip:
        print(f"\nSKIP (no invoice_lines.description): {pcs_skip}")

    con.execute(
        "DELETE FROM product_descriptions WHERE product_code IN ({})".format(
            ",".join("?" * len(pcs_to_regen))
        ),
        pcs_to_regen,
    )
    con.commit()
    print(f"Deleted {len(pcs_to_regen)} under-specified rows")
    con.close()

    # Regenerate with real invoice English
    from app.services import document_db as ddb
    from app.services.description_engine import get_description_block

    ddb._db_path = PROD_DB

    repaired = 0
    failed   = 0

    print("\n=== BEFORE → AFTER (invoice_lines.description as authority) ===")
    for r in targets:
        pc     = r["product_code"]
        item_t = r["item_type"]
        inv_en = inv_en_map.get(pc, "")

        if not inv_en:
            print(f"  SKIP: {pc} (no invoice row)")
            continue

        try:
            result      = get_description_block(pc, item_t, description_en=inv_en)
            new_desc_pl = result.get("description_pl", "")
            new_mat_pl  = result.get("material_pl",    "")
            print(f"  REPAIRED: {pc}")
            print(f"    invoice_en:    {inv_en!r}")
            print(f"    description_pl: {new_desc_pl!r}")
            print(f"    material_pl:    {new_mat_pl!r}")
            repaired += 1
        except Exception as exc:
            print(f"  FAILED: {pc}: {exc}")
            failed += 1

    print(f"\n=== SUMMARY ===")
    print(f"  Repaired:  {repaired}")
    print(f"  Skipped:   {len(pcs_skip)}")
    print(f"  Failed:    {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
