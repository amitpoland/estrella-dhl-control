"""
backfill_service_product_registry.py — one-time C-3g data migration.

Copies service-charge emission metadata (product_name, vat_rate, unit) for
the ALLOWED_SERVICE_CHARGE_TYPES rows ("freight", "insurance") from the
legacy wfirma_products cache (wfirma.db) into the PROFORMA authority's
service_product_registry (proforma_links.db).

Why: C-3g (Phase-C Wave-2, ratification amendment 1) retired the legacy
cache from the proforma service-charge path. Identity (wfirma_product_id)
already lives in wfirma_product_mirror (C-1w1 wrote it mirror-first);
metadata previously lived ONLY in the cache — this script moves it.

Idempotent: safe to re-run; upserts by charge_type. Reads the cache
read-only. Part of the C-3g deploy ritual (run AFTER the robocopy, BEFORE
the service restart), alongside the mirror backfill re-run:

    python tools/backfill_service_product_registry.py --storage-root C:\\PZ\\app\\storage

Exit codes: 0 = OK (including nothing-to-do), 1 = error.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # service/ so `app.` imports work

from app.services import proforma_invoice_link_db as pildb  # noqa: E402


def backfill(storage_root: Path) -> dict:
    wf = storage_root / "wfirma.db"
    links = storage_root / "proforma_links.db"
    result = {"copied": [], "skipped": [], "cache_absent": not wf.exists()}
    if not wf.exists():
        return result
    with sqlite3.connect(f"file:{wf}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT product_code, product_name_pl, product_name, vat_rate, unit "
                "FROM wfirma_products WHERE product_code IN ('freight','insurance')"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []  # table absent in a fresh tree — nothing to migrate
    for r in rows:
        ct = r["product_code"]
        name = (r["product_name_pl"] or r["product_name"] or "").strip()
        pildb.upsert_service_product_meta(
            links, ct,
            product_name=name,
            vat_rate=(r["vat_rate"] or "23").strip(),
            unit=(r["unit"] or "szt.").strip(),
        )
        result["copied"].append({"charge_type": ct, "product_name": name})
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage-root", required=True, type=Path)
    args = ap.parse_args()
    res = backfill(args.storage_root)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
