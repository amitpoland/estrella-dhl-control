"""Customer Master Incoterm review + contractor-scoped draft reseed.

Authority model:
  Customer Master.default_incoterm  = canonical commercial default
  editable draft.incoterm           = optional explicit override
  posted/converted drafts           = frozen (never reseeded)

Classification (never invents from country):
  SET         — hard evidence with one unique Incoterm for this contractor_id
  REVIEW      — soft/orphan name hints or conflicting hard codes
  NO EVIDENCE — nothing proven
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.config import settings

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


def _storage() -> Path:
    return Path(settings.storage_root)


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


def collect_incoterm_evidence(*, storage: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Gather historical Incoterm mentions across authorities (read-only)."""
    root = Path(storage) if storage else _storage()
    out: List[Dict[str, Any]] = []

    for r in _q(
        root / "proforma_links.db",
        """
        SELECT id, draft_state, client_contractor_id, client_name, incoterm,
               batch_id, notes, remarks, payment_terms_json
        FROM proforma_drafts
        """,
    ):
        cid = (r["client_contractor_id"] or "").strip() or None
        code = _norm(r["incoterm"])
        if code:
            out.append({
                "source": "proforma_draft.incoterm",
                "draft_id": r["id"],
                "draft_state": r["draft_state"],
                "contractor_id": cid,
                "client_name": r["client_name"],
                "incoterm": code,
                "batch_id": r["batch_id"],
                "hard": bool(cid),
            })
        blob = " ".join(str(r[c] or "") for c in ("notes", "remarks", "payment_terms_json"))
        for m in INCOTERM_RE.finditer(blob):
            c = m.group(1).upper()
            if c == "CIF" and "incoterm" not in blob.lower():
                continue
            out.append({
                "source": "proforma_draft_text",
                "draft_id": r["id"],
                "draft_state": r["draft_state"],
                "contractor_id": cid,
                "client_name": r["client_name"],
                "incoterm": c,
                "hard": bool(cid),
            })

    for r in _q(
        root / "customer_master.sqlite",
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
        root / "documents.db",
        """
        SELECT id, batch_id, client_name, client_contractor_id, remarks
        FROM sales_packing_lines
        WHERE TRIM(COALESCE(remarks,'')) != ''
        """,
    ):
        cid = (r["client_contractor_id"] or "").strip() or None
        for m in INCOTERM_RE.finditer(r["remarks"] or ""):
            out.append({
                "source": "sales_packing.remarks",
                "row_id": r["id"],
                "batch_id": r["batch_id"],
                "contractor_id": cid,
                "client_name": r["client_name"],
                "incoterm": m.group(1).upper(),
                "hard": bool(cid),
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


def _orphan_name_hints(
    customer_name: str,
    orphans: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    name = (customer_name or "").strip().upper()
    if not name:
        return []
    hints = []
    for o in orphans:
        oname = (o.get("client_name") or "").strip().upper()
        if oname and oname in name:
            hints.append({
                "hint_incoterm": o.get("incoterm"),
                "source": o.get("source"),
                "draft_id": o.get("draft_id"),
                "client_name_fragment": o.get("client_name"),
                "note": "name-only orphan — not unique; do not auto-select",
            })
    return hints


def classify_customer_incoterm(
    *,
    contractor_id: str,
    customer_name: str,
    current_default: Optional[str],
    hard_rows: Sequence[Dict[str, Any]],
    orphans: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    hard_codes = Counter(r["incoterm"] for r in hard_rows if r.get("incoterm"))
    hints = _orphan_name_hints(customer_name, orphans)
    recommended: Optional[str] = None
    if hard_codes and len(hard_codes) == 1:
        status = "SET"
        recommended = next(iter(hard_codes))
    elif len(hard_codes) > 1 or hints:
        status = "REVIEW"
    else:
        status = "NO EVIDENCE"

    return {
        "contractor_id": contractor_id,
        "customer_name": customer_name,
        "classification": status,
        "current_default": (current_default or "").strip().upper() or None,
        # Never preselect from soft hints (UAB/DAP case).
        "recommended_incoterm": recommended if status == "SET" else None,
        "hard_codes": dict(hard_codes),
        "historical_evidence": list(hard_rows)[:10],
        "orphan_name_hints": hints or None,
        "preselect_incoterm": None,  # UI must not invent; operator chooses
    }


def build_incoterm_review(
    *,
    storage: Optional[Path] = None,
    q: Optional[str] = None,
    country: Optional[str] = None,
    contractor_id: Optional[str] = None,
    missing_incoterm: Optional[bool] = None,
    classification: Optional[str] = None,
    limit: int = 1000,
) -> Dict[str, Any]:
    """Operator review payload for Customer Master Incoterm workflow."""
    from . import customer_master_db as cmdb

    root = Path(storage) if storage else _storage()
    cm_path = root / "customer_master.sqlite"
    cmdb.init_db(cm_path)

    customers = cmdb.list_customers(
        cm_path,
        country=(country.upper() if country else None),
        limit=max(1, min(int(limit), 5000)),
        q=q,
        active=True,
    )
    if contractor_id:
        cid = str(contractor_id).strip()
        customers = [c for c in customers if c.bill_to_contractor_id == cid]

    evidence = collect_incoterm_evidence(storage=root)
    by_cid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    orphans: List[Dict[str, Any]] = []
    for e in evidence:
        if e.get("hard") and e.get("contractor_id"):
            by_cid[str(e["contractor_id"])].append(e)
        elif not e.get("contractor_id"):
            orphans.append(e)

    rows: List[Dict[str, Any]] = []
    counts = Counter()
    for c in customers:
        cid = c.bill_to_contractor_id
        cur = (c.default_incoterm or "").strip().upper() or None
        if missing_incoterm is True and cur:
            continue
        if missing_incoterm is False and not cur:
            continue
        classified = classify_customer_incoterm(
            contractor_id=cid,
            customer_name=c.bill_to_name,
            current_default=cur,
            hard_rows=by_cid.get(cid, []),
            orphans=orphans,
        )
        classified["country"] = c.country
        if classification:
            want = classification.strip().upper().replace("_", " ")
            if want in ("NOEVIDENCE",):
                want = "NO EVIDENCE"
            if classified["classification"].upper() != want:
                continue
        counts[classified["classification"]] += 1
        rows.append(classified)

    # stable operator order: REVIEW first, then NO EVIDENCE, then SET; name
    order = {"REVIEW": 0, "NO EVIDENCE": 1, "SET": 2}
    rows.sort(key=lambda r: (
        order.get(r["classification"], 9),
        (r.get("country") or ""),
        (r.get("customer_name") or "").lower(),
    ))

    return {
        "count": len(rows),
        "classification_counts": dict(counts),
        "orphan_evidence_global": orphans,
        "customers": rows,
        "authority": {
            "canonical": "customer_master.default_incoterm",
            "draft_override": "proforma_drafts.incoterm (editable only)",
            "catalogue": "master_data.incoterms",
            "never_infer_from_country": True,
        },
    }


def seed_blank_draft_incoterms_for_contractors(
    contractor_ids: Sequence[str],
    *,
    proforma_db: Optional[Path] = None,
    operator: str = "customer_master_incoterm",
    storage: Optional[Path] = None,
) -> Dict[str, Any]:
    """Re-seed blank editable drafts for the given CM contractors only."""
    from . import customer_master_db as cmdb
    from . import proforma_invoice_link_db as pildb

    root = Path(storage) if storage else _storage()
    pf = Path(proforma_db) if proforma_db else (root / "proforma_links.db")
    cm_path = root / "customer_master.sqlite"
    ids = [str(x).strip() for x in contractor_ids if str(x).strip()]
    if not ids or not pf.exists():
        return {"seeded": [], "skipped": [{"reason": "no_targets_or_db"}], "seeded_count": 0}

    editable = getattr(pildb, "EDITABLE_STATES", ("draft", "editing", "post_failed"))
    seeded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    # Load CM defaults once
    defaults: Dict[str, str] = {}
    cmdb.init_db(cm_path)
    for cid in ids:
        cm = cmdb.get_customer(cm_path, cid)
        val = (getattr(cm, "default_incoterm", None) or "").strip().upper() if cm else ""
        if val:
            defaults[cid] = val

    placeholders = ",".join("?" for _ in ids)
    rows = _q(
        pf,
        f"""
        SELECT id, draft_state, client_contractor_id, incoterm, batch_id, updated_at
        FROM proforma_drafts
        WHERE client_contractor_id IN ({placeholders})
        """,
        tuple(ids),
    )
    for r in rows:
        state = (r["draft_state"] or "").strip()
        if state not in editable and state != "":
            skipped.append({"draft_id": r["id"], "reason": "locked_state", "state": state})
            continue
        if (r["incoterm"] or "").strip():
            skipped.append({"draft_id": r["id"], "reason": "draft_already_set"})
            continue
        cid = (r["client_contractor_id"] or "").strip()
        cm_def = defaults.get(cid)
        if not cm_def:
            skipped.append({"draft_id": r["id"], "reason": "cm_default_unset"})
            continue
        try:
            d = pildb.get_draft_by_id(pf, int(r["id"]))
            if d is None:
                skipped.append({"draft_id": r["id"], "reason": "draft_missing"})
                continue
            pildb.update_draft_fields(
                pf, int(d.id),
                {"incoterm": cm_def},
                operator=operator,
                expected_updated_at=d.updated_at,
            )
            seeded.append({
                "draft_id": d.id,
                "contractor_id": cid,
                "incoterm": cm_def,
                "source": "customer_master",
                "batch_id": r["batch_id"],
            })
        except Exception as exc:
            skipped.append({"draft_id": r["id"], "reason": f"write:{exc}"[:160]})

    return {"seeded": seeded, "skipped": skipped, "seeded_count": len(seeded)}


def apply_customer_incoterms(
    assignments: Dict[str, str],
    *,
    operator: str = "customer_master_incoterm",
    storage: Optional[Path] = None,
    reseed_editable: bool = True,
) -> Dict[str, Any]:
    """Set CM.default_incoterm for explicit contractor→code map; reseed blanks.

    ``assignments`` values may be empty string to clear. Codes must be 3-letter
    ICC tokens present in / validated like the CM PUT path.
    """
    from . import customer_master_db as cmdb
    from . import master_data_db as mdb

    root = Path(storage) if storage else _storage()
    cm_path = root / "customer_master.sqlite"
    md_path = root / "master_data.sqlite"
    cmdb.init_db(cm_path)

    updated: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    touched_ids: List[str] = []

    for cid, raw in assignments.items():
        cid = str(cid).strip()
        code = (raw or "").strip().upper() or None
        if code is not None:
            if not CODE_ONLY_RE.match(code):
                errors.append({"contractor_id": cid, "error": "invalid_incoterm"})
                continue
            if md_path.exists():
                rec = mdb.get_incoterm(md_path, code)
                if rec is not None and not rec.active:
                    errors.append({"contractor_id": cid, "error": "incoterm_inactive"})
                    continue
        cm = cmdb.get_customer(cm_path, cid)
        if cm is None:
            errors.append({"contractor_id": cid, "error": "customer_not_found"})
            continue
        before = (cm.default_incoterm or "").strip().upper() or None
        if before == code:
            updated.append({
                "contractor_id": cid, "default_incoterm": code,
                "changed": False,
            })
            continue
        cm = replace(cm, default_incoterm=code)
        cmdb.upsert_customer(cm_path, cm)
        updated.append({
            "contractor_id": cid, "default_incoterm": code,
            "changed": True, "before": before,
        })
        touched_ids.append(cid)

    seed: Dict[str, Any] = {"seeded_count": 0, "seeded": [], "skipped": []}
    if reseed_editable and touched_ids:
        seed = seed_blank_draft_incoterms_for_contractors(
            touched_ids, operator=operator, storage=root,
        )

    return {
        "updated": updated,
        "errors": errors,
        "draft_reseed": seed,
        "operator": operator,
    }
