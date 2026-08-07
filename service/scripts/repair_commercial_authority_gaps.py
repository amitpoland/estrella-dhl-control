"""Repair commercial-authority gaps where upstream data already exists.

Safe rules (never invent):
  1. Blank-fill sales_packing_lines variants from purchase packing only.
     Client PO is never taken from purchase.
  2. Reset editable drafts (draft/editing/post_failed) from sales packing
     via the same reshape used by the operator reset endpoint — only for
     drafts classified as stale or sales-thin (after backfill).
  3. Posted/converted drafts are reported, not mutated.
  4. Origin gaps require Product Master completion — listed, never invented.

Usage (from service/):
  python scripts/repair_commercial_authority_gaps.py --storage-root <path>
  python scripts/repair_commercial_authority_gaps.py --storage-root <path> --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-root", required=True, type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    storage = args.storage_root.resolve()
    docs = storage / "documents.db"
    packing = storage / "packing.db"
    proforma = storage / "proforma_links.db"
    for p in (docs, packing, proforma):
        if not p.exists():
            print(f"MISSING: {p}", file=sys.stderr)
            return 2

    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import proforma_invoice_link_db as pildb
    from app.services.commercial_authority import (
        backfill_sales_variants_from_purchase,
        repair_editable_draft_from_sales,
    )
    from scripts.audit_commercial_authority_gaps import scan_gaps

    ddb.init_document_db(docs)
    pdb.init_packing_db(packing)
    pildb.init_db(proforma)

    report = scan_gaps(storage)
    thin_cohort = (
        report.get("cohorts", {})
        .get("SALES_PACKING_LACKS_VARIANTS", {})
        .get("drafts", [])
        or []
    )
    stale_cohort = (
        report.get("cohorts", {})
        .get("STALE_DRAFT_SALES_VARIANTS_AVAILABLE", {})
        .get("drafts", [])
        or []
    )

    batches_need_sales_backfill = sorted({
        d["batch_id"] for d in thin_cohort if d.get("batch_id")
    })
    with sqlite3.connect(str(docs)) as con:
        for r in con.execute(
            """
            SELECT DISTINCT batch_id FROM sales_packing_lines
            WHERE TRIM(COALESCE(karat,''))=''
              AND TRIM(COALESCE(quality_string,''))=''
              AND TRIM(COALESCE(metal_color,''))=''
              AND TRIM(COALESCE(size,''))=''
              AND COALESCE(diamond_weight,0)=0
              AND COALESCE(color_weight,0)=0
            """
        ):
            if r[0] not in batches_need_sales_backfill:
                batches_need_sales_backfill.append(r[0])

    editable = {"draft", "editing", "post_failed", ""}
    reset_ids = set()
    locked_stale = []
    for entry in stale_cohort + thin_cohort:
        did = int(entry["draft_id"])
        st = (entry.get("state") or "").strip()
        if st in editable:
            reset_ids.add(did)
        else:
            locked_stale.append({
                "draft_id": did,
                "state": st,
                "batch_id": entry.get("batch_id"),
                "client": entry.get("client"),
                "reason": "locked — operator rematch/amend required",
            })

    result = {
        "mode": "apply" if args.apply else "dry-run",
        "storage_root": str(storage),
        "sales_backfill": [],
        "draft_resets": [],
        "locked_stale_drafts": locked_stale,
        "origin_skus_need_master": {
            "count": report.get("product_master_origin_missing_skus", {}).get("count"),
            "sample": report.get("product_master_origin_missing_skus", {}).get("sample"),
        },
        "pre_repair_cohort_counts": report.get("cohort_counts"),
    }

    print(f"[{result['mode']}] sales blank-fill batches: "
          f"{len(batches_need_sales_backfill)}")
    for bid in batches_need_sales_backfill:
        if not args.apply:
            result["sales_backfill"].append({"batch_id": bid, "planned": True})
            continue
        out = backfill_sales_variants_from_purchase(bid)
        result["sales_backfill"].append(out)
        print(f"  backfill {bid}: updated={out.get('updated')} "
              f"hits={out.get('field_hits')}")

    print(f"[{result['mode']}] draft resets planned: {len(reset_ids)}")
    for did in sorted(reset_ids):
        if not args.apply:
            result["draft_resets"].append({"draft_id": did, "planned": True})
            continue
        out = repair_editable_draft_from_sales(
            proforma, int(did), operator="commercial_authority_repair",
        )
        result["draft_resets"].append(out)
        print(f"  reset draft#{did}: ok={out.get('ok')} err={out.get('error')}")

    if args.apply:
        result["post_repair_cohort_counts"] = scan_gaps(storage).get("cohort_counts")

    out_path = args.out
    if out_path is None:
        out_path = (
            Path(__file__).resolve().parents[2]
            / "tasks/smoke-reports/commercial-authority-audit"
            / ("repair_apply.json" if args.apply else "repair_dry_run.json")
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    print(f"Wrote {out_path}")
    print(json.dumps({
        "mode": result["mode"],
        "sales_backfill_batches": len(batches_need_sales_backfill),
        "draft_resets": len(reset_ids),
        "locked_stale": len(locked_stale),
        "origin_skus": result["origin_skus_need_master"]["count"],
        "out": str(out_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
