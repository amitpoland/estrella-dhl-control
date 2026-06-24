"""
repair_product_descriptions_20260624.py
=========================================
Repair 42 product_descriptions rows written by the sales_packing_parser
generator (routes_packing.py "Fix 3" block) instead of the customs engine.

Safety:
  - Never touches source='manual' rows
  - Backs up before deleting
  - Regenerates via description_engine.get_description_block()
    → customs_description_engine.normalize_item_description()
  - Skips product codes with no invoice English description (advisory only)

Run from the repo root:
    python scripts/repair_product_descriptions_20260624.py

Dry-run (report only, no writes):
    python scripts/repair_product_descriptions_20260624.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
PROD_DB      = Path("C:/PZ/storage/documents.db")
BACKUP_CSV   = Path("C:/PZ/storage/product_descriptions_backup_20260624.csv")
SERVICE_ROOT = Path(__file__).resolve().parent.parent / "service"

# ── candidate filter (signature of generator-written rows) ───────────────────
CORRUPT_SQL = """
    SELECT product_code, item_type, description_en
    FROM product_descriptions
    WHERE source = 'auto'
      AND name_pl = description_pl
      AND material_pl LIKE 'Metal (srebro/stop metali)%'
    ORDER BY created_at
"""


def main(dry_run: bool) -> int:
    sys.path.insert(0, str(SERVICE_ROOT))
    sys.path.insert(0, "C:/PZ/engine")

    # Encoding safety for Polish output
    import io
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

    con = sqlite3.connect(str(PROD_DB))
    con.row_factory = sqlite3.Row

    corrupted = con.execute(CORRUPT_SQL).fetchall()
    print(f"Candidate corrupted rows: {len(corrupted)}")
    if not corrupted:
        print("Nothing to repair.")
        con.close()
        return 0

    # Build invoice-English lookup
    inv_map: dict[str, str] = {}
    for r in corrupted:
        pc = r["product_code"]
        stored_en = (r["description_en"] or "").strip()
        if stored_en:
            inv_map[pc] = stored_en
        else:
            inv = con.execute(
                "SELECT description FROM invoice_lines WHERE product_code=? LIMIT 1",
                (pc,),
            ).fetchone()
            inv_map[pc] = (inv["description"] if inv else "").strip() if inv else ""

    # Confirm no manual rows in candidate set
    manual_check = con.execute(
        "SELECT product_code FROM product_descriptions"
        " WHERE source='manual'"
        "   AND product_code IN ({})".format(",".join("?" * len(corrupted))),
        [r["product_code"] for r in corrupted],
    ).fetchall()
    if manual_check:
        print("ERROR: manual rows in candidate set — aborting.")
        for r in manual_check:
            print(f"  {r['product_code']}")
        con.close()
        return 1

    if dry_run:
        print("\n=== DRY RUN — no writes ===")
        for r in corrupted:
            pc     = r["product_code"]
            inv_en = inv_map.get(pc, "")
            status = "WOULD_REPAIR" if inv_en else "WOULD_SKIP (no invoice)"
            print(f"  {pc}: {status}")
            if inv_en:
                print(f"    invoice_en: {inv_en!r}")
        con.close()
        return 0

    # ── Write backup CSV ─────────────────────────────────────────────────────
    if not BACKUP_CSV.exists():
        full_rows = con.execute("""
            SELECT product_code, item_type, name_pl, description_pl, description_en,
                   material_pl, purpose_pl, description_block, description_line,
                   source, created_at, updated_at
            FROM product_descriptions
            WHERE product_code IN ({})
        """.format(",".join("?" * len(corrupted))),
            [r["product_code"] for r in corrupted],
        ).fetchall()
        with open(BACKUP_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([
                "product_code", "item_type", "name_pl", "description_pl", "description_en",
                "material_pl", "purpose_pl", "description_block", "description_line",
                "source", "created_at", "updated_at", "invoice_description_en",
            ])
            for row in full_rows:
                pc = row["product_code"]
                w.writerow([
                    row["product_code"], row["item_type"], row["name_pl"],
                    row["description_pl"], row["description_en"], row["material_pl"],
                    row["purpose_pl"], row["description_block"], row["description_line"],
                    row["source"], row["created_at"], row["updated_at"],
                    inv_map.get(pc, ""),
                ])
        print(f"Backup written: {BACKUP_CSV}")
    else:
        print(f"Backup already exists: {BACKUP_CSV} (skipping re-write)")

    # ── Delete corrupted rows ────────────────────────────────────────────────
    pcs = [r["product_code"] for r in corrupted]
    con.execute(
        "DELETE FROM product_descriptions WHERE product_code IN ({})".format(
            ",".join("?" * len(pcs))
        ),
        pcs,
    )
    con.commit()
    print(f"Deleted {len(pcs)} corrupted rows")
    con.close()

    # ── Regenerate via canonical engine ──────────────────────────────────────
    from app.services import document_db as ddb
    from app.services.description_engine import get_description_block

    ddb._db_path = PROD_DB

    repaired  = 0
    advisory  = 0
    failed    = 0

    print("\n=== BEFORE → AFTER ===")
    for r in corrupted:
        pc      = r["product_code"]
        item_tp = r["item_type"]
        inv_en  = inv_map.get(pc, "")

        if not inv_en:
            print(f"  ADVISORY (no invoice EN): {pc} — left blank, will populate on next customs package run")
            advisory += 1
            continue

        try:
            result      = get_description_block(pc, item_tp, description_en=inv_en)
            new_desc_pl = result.get("description_pl", "")
            new_mat_pl  = result.get("material_pl", "")
            print(f"  REPAIRED: {pc}")
            print(f"    BEFORE: generator artifact (e.g. 'pierścionek z diamentami')")
            print(f"    AFTER:  description_pl={new_desc_pl!r}")
            print(f"            material_pl={new_mat_pl!r}")
            repaired += 1
        except Exception as exc:
            print(f"  FAILED: {pc}: {exc}")
            failed += 1

    print(f"\n=== SUMMARY ===")
    print(f"  Repaired:            {repaired}")
    print(f"  Advisory (no inv):   {advisory}")
    print(f"  Failed:              {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.dry_run))
