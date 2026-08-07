"""System-wide editable-draft commercial authority convergence.

Deterministic repair only — never invents descriptions or wfirma_product_id.
Uses converge_batch_draft_authority per unique batch among editable drafts.

Usage (production):
  set STORAGE_ROOT=C:\\PZ\\storage
  python scripts/repair_proforma_draft_authority.py [--dry-run] [--batch BATCH_ID]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))


def _list_editable_draft_ids(links: Path, batch_id: str = "") -> List[int]:
    con = sqlite3.connect(str(links))
    try:
        q = (
            "SELECT id FROM proforma_drafts "
            "WHERE COALESCE(draft_state, '') IN ('draft', 'editing', 'post_failed', '')"
        )
        params: List[Any] = []
        if batch_id:
            q += " AND batch_id = ?"
            params.append(batch_id)
        q += " ORDER BY id"
        return [int(r[0]) for r in con.execute(q, params).fetchall()]
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", default="")
    ap.add_argument(
        "--storage-root",
        default=os.environ.get("STORAGE_ROOT") or os.environ.get("PZ_STORAGE_ROOT") or "",
    )
    args = ap.parse_args()
    if not args.storage_root:
        print("STORAGE_ROOT / --storage-root required", file=sys.stderr)
        return 2

    storage = Path(args.storage_root)
    os.environ["STORAGE_ROOT"] = str(storage)
    os.environ["PZ_STORAGE_ROOT"] = str(storage)

    from app.core.config import settings
    settings.storage_root = storage

    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import proforma_invoice_link_db as pildb
    from app.services.commercial_authority import converge_batch_draft_authority

    docs = storage / "documents.db"
    pack = storage / "packing.db"
    links = storage / "proforma_links.db"
    if not links.exists():
        print(f"missing {links}", file=sys.stderr)
        return 2

    ddb.init_document_db(docs)
    pdb.init_packing_db(pack)

    ids = _list_editable_draft_ids(links, args.batch)
    drafts = []
    for did in ids:
        d = pildb.get_draft_by_id(links, did)
        if d is not None:
            drafts.append(d)

    batches = sorted({d.batch_id for d in drafts if d.batch_id})
    report: Dict[str, Any] = {
        "storage_root": str(storage),
        "editable_drafts": len(drafts),
        "batches": len(batches),
        "dry_run": args.dry_run,
        "results": [],
        "pre": [],
        "post": [],
    }

    def _gap_summary(d) -> dict:
        lines = json.loads(d.editable_lines_json or "[]") or []
        blank_pl = sum(1 for ln in lines if not str(ln.get("name_pl") or "").strip())
        blank_pc = sum(1 for ln in lines if not str(ln.get("product_code") or "").strip())
        missing_wf = sum(
            1 for ln in lines
            if str(ln.get("product_code") or "").strip()
            and not str(ln.get("wfirma_product_id") or "").strip()
        )
        return {
            "draft_id": d.id,
            "batch_id": d.batch_id,
            "client": d.client_name,
            "state": d.draft_state,
            "lines": len(lines),
            "blank_name_pl": blank_pl,
            "blank_product_code": blank_pc,
            "missing_wfirma_product_id": missing_wf,
        }

    for d in drafts:
        report["pre"].append(_gap_summary(d))

    if args.dry_run:
        sales_gaps = []
        for bid in batches:
            rows = ddb.get_sales_packing_lines(bid) or []
            empty = [r for r in rows if not str(r.get("product_code") or "").strip()]
            if empty:
                sales_gaps.append({
                    "batch_id": bid,
                    "empty_sales_pc": len(empty),
                    "designs": sorted({
                        str(r.get("design_no") or "").strip() for r in empty
                    }),
                })
        report["sales_pc_gaps"] = sales_gaps
        out = storage / "outputs" / "_repair_draft_authority_dry_run.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "editable_drafts": len(drafts),
            "batches": len(batches),
            "pre_blank_name_pl_drafts": sum(1 for g in report["pre"] if g["blank_name_pl"]),
            "pre_blank_pc_drafts": sum(1 for g in report["pre"] if g["blank_product_code"]),
            "pre_missing_wfirma_drafts": sum(
                1 for g in report["pre"] if g["missing_wfirma_product_id"]
            ),
            "sales_pc_gap_batches": len(sales_gaps),
            "report": str(out),
        }, indent=2))
        return 0

    for bid in batches:
        try:
            result = converge_batch_draft_authority(
                bid,
                proforma_db=links,
                operator="repair_proforma_draft_authority",
                reset_editable=True,
            )
            report["results"].append(result)
        except Exception as exc:
            report["results"].append({
                "batch_id": bid, "ok": False, "error": str(exc)[:300],
            })

    drafts2 = []
    for did in _list_editable_draft_ids(links, args.batch):
        d = pildb.get_draft_by_id(links, did)
        if d is not None:
            drafts2.append(d)
    for d in drafts2:
        report["post"].append(_gap_summary(d))

    out = storage / "outputs" / "_repair_draft_authority_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "editable_drafts": len(drafts2),
        "batches_converged": len(batches),
        "pre_blank_name_pl_drafts": sum(1 for g in report["pre"] if g["blank_name_pl"]),
        "post_blank_name_pl_drafts": sum(1 for g in report["post"] if g["blank_name_pl"]),
        "pre_blank_pc_drafts": sum(1 for g in report["pre"] if g["blank_product_code"]),
        "post_blank_pc_drafts": sum(1 for g in report["post"] if g["blank_product_code"]),
        "pre_missing_wfirma_drafts": sum(
            1 for g in report["pre"] if g["missing_wfirma_product_id"]
        ),
        "post_missing_wfirma_drafts": sum(
            1 for g in report["post"] if g["missing_wfirma_product_id"]
        ),
        "report": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
