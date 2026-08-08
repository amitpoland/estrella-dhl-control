"""System-wide Incoterm authority: catalogue restore + CM audit + editable reseed.

Does NOT invent DAP/EXW for customers. Does NOT patch individual drafts by id.
Proof rule for Customer Master.default_incoterm:
  - hard evidence must carry a real bill_to_contractor_id
  - all hard evidence for that customer must agree on one code
  - orphan name-only hits (e.g. posted draft client_name=\"UAB\") never auto-resolve

Usage:
  python service/scripts/populate_incoterm_authority.py           # dry-run
  python service/scripts/populate_incoterm_authority.py --apply   # write production
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STORAGE = Path(os.environ.get("STORAGE_ROOT", r"C:\PZ\storage"))
SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

os.environ.setdefault("STORAGE_ROOT", str(STORAGE))

INCOTERM_RE = re.compile(
    r"\b(EXW|FCA|CPT|CIP|DAP|DPU|DDP|FAS|FOB|CFR|CIF)\b",
    re.IGNORECASE,
)
CODE_ONLY_RE = re.compile(
    r"^(EXW|FCA|CPT|CIP|DAP|DPU|DDP|FAS|FOB|CFR|CIF)$", re.I,
)


def _norm(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    s = str(code).strip().upper()
    if CODE_ONLY_RE.match(s):
        return s
    m = INCOTERM_RE.search(s)
    return m.group(1).upper() if m else None


def _q(db: Path, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        return list(con.execute(sql, params).fetchall())
    except sqlite3.Error:
        return []
    finally:
        con.close()


def active_customers() -> List[Dict[str, Any]]:
    rows = _q(
        STORAGE / "customer_master.sqlite",
        """
        SELECT bill_to_contractor_id AS contractor_id,
               bill_to_name AS name,
               default_incoterm,
               country
        FROM customer_master
        WHERE COALESCE(active, 1) = 1
          AND deleted_at IS NULL
        ORDER BY bill_to_name COLLATE NOCASE
        """,
    )
    return [dict(r) for r in rows]


def collect_evidence() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for r in _q(
        STORAGE / "proforma_links.db",
        """
        SELECT id, draft_state, client_contractor_id, client_name, incoterm,
               batch_id, notes, remarks, payment_terms_json
        FROM proforma_drafts
        """,
    ):
        code = _norm(r["incoterm"])
        if code:
            out.append({
                "source": "proforma_draft.incoterm",
                "draft_id": r["id"],
                "draft_state": r["draft_state"],
                "contractor_id": (r["client_contractor_id"] or "").strip() or None,
                "client_name": r["client_name"],
                "incoterm": code,
                "batch_id": r["batch_id"],
                "hard": bool((r["client_contractor_id"] or "").strip()),
            })
        blob = " ".join(
            str(r[c] or "")
            for c in ("notes", "remarks", "payment_terms_json")
        )
        for m in INCOTERM_RE.finditer(blob):
            c = m.group(1).upper()
            if c == "CIF" and "incoterm" not in blob.lower():
                continue
            out.append({
                "source": "proforma_draft_text",
                "draft_id": r["id"],
                "draft_state": r["draft_state"],
                "contractor_id": (r["client_contractor_id"] or "").strip() or None,
                "client_name": r["client_name"],
                "incoterm": c,
                "hard": bool((r["client_contractor_id"] or "").strip()),
            })

    for r in _q(
        STORAGE / "customer_master.sqlite",
        """
        SELECT bill_to_contractor_id, bill_to_name, notes, compliance_notes
        FROM customer_master
        WHERE COALESCE(active,1)=1 AND deleted_at IS NULL
        """,
    ):
        blob = f"{r['notes'] or ''} {r['compliance_notes'] or ''}"
        for m in INCOTERM_RE.finditer(blob):
            out.append({
                "source": "customer_master_notes",
                "contractor_id": str(r["bill_to_contractor_id"]),
                "client_name": r["bill_to_name"],
                "incoterm": m.group(1).upper(),
                "hard": True,
            })

    for r in _q(
        STORAGE / "documents.db",
        """
        SELECT id, batch_id, client_name, client_contractor_id, remarks
        FROM sales_packing_lines
        WHERE TRIM(COALESCE(remarks,'')) != ''
        """,
    ):
        for m in INCOTERM_RE.finditer(r["remarks"] or ""):
            out.append({
                "source": "sales_packing.remarks",
                "row_id": r["id"],
                "batch_id": r["batch_id"],
                "contractor_id": (r["client_contractor_id"] or "").strip() or None,
                "client_name": r["client_name"],
                "incoterm": m.group(1).upper(),
                "hard": bool((r["client_contractor_id"] or "").strip()),
            })

    outputs = STORAGE / "outputs"
    if outputs.is_dir():
        for audit in outputs.glob("*/audit.json"):
            try:
                text = audit.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            near = set()
            for m in re.finditer(r"incoterm[s]?\W{0,40}([A-Z]{3})", text, re.I):
                near.add(_norm(m.group(1)))
            for m in re.finditer(r"([A-Z]{3})\W{0,40}incoterm", text, re.I):
                near.add(_norm(m.group(1)))
            near.discard(None)
            for code in near:
                out.append({
                    "source": "batch_audit",
                    "batch_id": audit.parent.name,
                    "incoterm": code,
                    "contractor_id": None,
                    "hard": False,
                })

    # de-dupe
    seen = set()
    uniq = []
    for e in out:
        key = json.dumps(e, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return uniq


def prove_defaults(
    evidence: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    by_cid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    orphans: List[Dict[str, Any]] = []
    for e in evidence:
        cid = e.get("contractor_id")
        if cid and e.get("hard", True):
            by_cid[str(cid)].append(e)
        elif not cid:
            orphans.append(e)

    resolved: List[Dict[str, Any]] = []
    needs: List[Dict[str, Any]] = []
    for cust in active_customers():
        cid = str(cust["contractor_id"])
        rows = by_cid.get(cid, [])
        hard_codes = Counter(r["incoterm"] for r in rows if r.get("incoterm"))
        if hard_codes and len(hard_codes) == 1:
            code = next(iter(hard_codes))
            resolved.append({
                "contractor_id": cid,
                "name": cust.get("name"),
                "incoterm": code,
                "evidence_count": hard_codes[code],
                "current_default": cust.get("default_incoterm"),
                "country": cust.get("country"),
            })
        else:
            needs.append({
                "contractor_id": cid,
                "name": cust.get("name"),
                "country": cust.get("country"),
                "current_default": cust.get("default_incoterm"),
                "reason": (
                    "conflicting_evidence" if len(hard_codes) > 1
                    else "no_proven_customer_level_incoterm"
                ),
                "hard_codes": dict(hard_codes),
                "evidence_count": len(rows),
            })
    return resolved, needs, orphans


def apply_cm(resolved: List[Dict[str, Any]]) -> Dict[str, Any]:
    from app.services import customer_master_db as cmdb

    db = STORAGE / "customer_master.sqlite"
    cmdb.init_db(db)
    updated, skipped = [], []
    for r in resolved:
        cur = (r.get("current_default") or "").strip().upper() or None
        want = r["incoterm"]
        if cur == want:
            skipped.append({"contractor_id": r["contractor_id"], "reason": "already_set"})
            continue
        if cur and cur != want:
            skipped.append({
                "contractor_id": r["contractor_id"],
                "reason": "existing_default_differs",
                "current": cur,
                "proven": want,
            })
            continue
        cm = cmdb.get_customer(db, r["contractor_id"])
        if cm is None:
            skipped.append({"contractor_id": r["contractor_id"], "reason": "cm_missing"})
            continue
        cm.default_incoterm = want
        cmdb.upsert_customer(db, cm)
        updated.append({"contractor_id": r["contractor_id"], "incoterm": want})
    return {"updated": updated, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--report",
        default=str(STORAGE / "reports" / "incoterm_authority_audit.json"),
    )
    args = ap.parse_args()

    from app.services.master_data_db import (
        seed_default_incoterms,
        list_incoterms,
        init_db as md_init,
    )
    from app.services.commercial_authority import seed_blank_draft_incoterms_all

    md = STORAGE / "master_data.sqlite"
    before = [
        {"code": r["code"], "active": r["active"], "deleted_at": r["deleted_at"]}
        for r in _q(md, "SELECT code, active, deleted_at FROM incoterms")
    ]

    evidence = collect_evidence()
    resolved, needs, orphans = prove_defaults(evidence)

    catalogue_result: Dict[str, Any] = {"apply": False, "before": before}
    cm_result: Dict[str, Any] = {"apply": False}
    seed_result: Dict[str, Any] = {"apply": False}

    if args.apply:
        md_init(md)
        catalogue_result = seed_default_incoterms(md)
        catalogue_result["apply"] = True
        catalogue_result["before"] = before
        active = list_incoterms(md, active=True, limit=100)
        catalogue_result["active_codes"] = [i.code for i in active]
        catalogue_result["active_count"] = len(active)

        cm_result = apply_cm(resolved)
        cm_result["apply"] = True

        pf = STORAGE / "proforma_links.db"
        seed_result = seed_blank_draft_incoterms_all(
            proforma_db=pf, operator="incoterm_authority_populate",
        )
        seed_result["apply"] = True
    else:
        catalogue_result["planned_codes"] = [
            "EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP",
            "FAS", "FOB", "CFR", "CIF",
        ]

    report = {
        "storage": str(STORAGE),
        "apply": bool(args.apply),
        "evidence_total": len(evidence),
        "evidence_by_source": dict(Counter(e["source"] for e in evidence)),
        "orphan_evidence": orphans,
        "customers_auto_resolved": len(resolved),
        "customers_needing_decision": len(needs),
        "resolved": resolved,
        "needs_decision": needs,
        "catalogue": catalogue_result,
        "cm_apply": cm_result,
        "editable_drafts_seed": seed_result,
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    summary = {
        "customers_auto_resolved": len(resolved),
        "customers_needing_decision": len(needs),
        "catalogue_status": (
            {
                "active_count": catalogue_result.get("active_count"),
                "active_codes": catalogue_result.get("active_codes"),
                "created": catalogue_result.get("created"),
                "restored": catalogue_result.get("restored"),
            }
            if args.apply
            else {"before": before, "dry_run": True}
        ),
        "editable_drafts_updated": (
            seed_result.get("seeded_count", 0) if args.apply else 0
        ),
        "report_path": str(report_path),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
