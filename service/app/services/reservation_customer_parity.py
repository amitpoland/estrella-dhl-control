"""
reservation_customer_parity.py — WF-3 Slice 2B-1 reservation parity harness (READ-ONLY).

De-risks the reservation consumer migration BEFORE any behavior change. It
compares, per reservation draft, the TWO customer-resolution answers:

  1. current NAME-based resolution — exactly what reservation Gate 6 / preview do
     today: ``wfdb.get_customer(client_name)`` → ``wfirma_customer_id``.
  2. canonical CONTRACTOR.ID resolution — ``customer_identity_resolver.
     resolve_by_contractor_id(draft.client_contractor_id)`` (the operator's
     upload-time selection).

It REPORTS differences only. It changes no reservation, proforma, or invoice
behavior, enables no fiscal write, and performs no wFirma call.

CLASSIFICATION per draft (exactly the operator-specified set):
  * no_selection        — the draft carries no client_contractor_id.
  * agree               — id resolves AND name resolves AND name_id == selected id.
  * diverge_id_vs_name  — id resolves AND name resolves AND name_id != selected id.
                          ANY occurrence BLOCKS Slice 2B-2.
  * id_only_resolves     — selected id resolves; name lookup returns nothing.
  * name_only_resolves   — name lookup returns an id; the selected id does not resolve.
  * unresolved          — id present but neither the id nor the name resolves.

SAFETY: reads only — reservation drafts (``wfirma_reservation_drafts``) via a
``PRAGMA query_only=ON`` connection that never creates the file, plus the two
read-only resolvers. No INSERT/UPDATE/DELETE, no new DB, no audit write, no
wFirma API call.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import wfirma_db as wfdb
from . import customer_identity_resolver as cir

# Classification labels (the operator-specified set).
C_NO_SELECTION = "no_selection"
C_AGREE = "agree"
C_DIVERGE = "diverge_id_vs_name"
C_ID_ONLY = "id_only_resolves"
C_NAME_ONLY = "name_only_resolves"
C_UNRESOLVED = "unresolved"
CLASSES = (C_AGREE, C_ID_ONLY, C_NAME_ONLY, C_DIVERGE, C_NO_SELECTION, C_UNRESOLVED)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ro_connect(path: Optional[Path]) -> Optional[sqlite3.Connection]:
    """READ-ONLY connection; never creates the file; hard-blocks writes."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _read_drafts(wfirma_db_path: Optional[Path], batch_id: Optional[str]) -> List[Dict[str, Any]]:
    """Read reservation drafts (batch_id, client_name, client_contractor_id)."""
    con = _ro_connect(wfirma_db_path)
    if con is None:
        return []
    try:
        if batch_id:
            rows = con.execute(
                "SELECT batch_id, client_name, client_contractor_id "
                "FROM wfirma_reservation_drafts WHERE batch_id = ?",
                (batch_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT batch_id, client_name, client_contractor_id "
                "FROM wfirma_reservation_drafts"
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def classify(cid: Optional[str], name_id: Optional[str], id_resolved: bool) -> str:
    """Pure classification (no I/O). ``cid`` = the draft's selected contractor.id,
    ``name_id`` = the id the name lookup returned, ``id_resolved`` = whether the
    canonical resolver resolved ``cid``."""
    cid = (cid or "").strip()
    name_id = (name_id or "").strip()
    if not cid:
        return C_NO_SELECTION
    if id_resolved and name_id:
        return C_AGREE if name_id == cid else C_DIVERGE
    if id_resolved and not name_id:
        return C_ID_ONLY
    if name_id and not id_resolved:
        return C_NAME_ONLY
    return C_UNRESOLVED


def run_reservation_parity(
    *,
    batch_id: Optional[str] = None,
    wfirma_db_path: Optional[Path] = None,
    cm_path: Optional[Path] = None,
    res_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Read-only entry point. Enumerates reservation drafts and classifies each.

    ``blocked`` is True iff any ``diverge_id_vs_name`` exists — the critical
    rule that gates Slice 2B-2.
    """
    from ..core.config import settings
    wpath = Path(wfirma_db_path) if wfirma_db_path else Path(settings.storage_root) / "wfirma.db"

    drafts = _read_drafts(wpath, batch_id)
    counts = {c: 0 for c in CLASSES}
    rows: List[Dict[str, Any]] = []
    diverge: List[Dict[str, Any]] = []

    for d in drafts:
        name = (d.get("client_name") or "").strip()
        cid = (d.get("client_contractor_id") or "").strip()

        # 1. Current NAME-based resolution — the exact call reservation uses.
        name_rec = None
        try:
            if name and wfdb._db_path is not None:
                name_rec = wfdb.get_customer(name)
        except Exception:
            name_rec = None
        name_id = (name_rec.get("wfirma_customer_id") or "").strip() if name_rec else ""

        # 2. Canonical CONTRACTOR.ID resolution.
        id_rec = None
        try:
            if cid:
                id_rec = cir.resolve_by_contractor_id(cid, cm_path=cm_path, res_path=res_path)
        except Exception:
            id_rec = None

        cls = classify(cid, name_id, id_rec is not None)
        counts[cls] += 1
        row = {
            "batch_id": d.get("batch_id", ""),
            "client_name": name,
            "selected_contractor_id": cid,
            "name_resolved_id": name_id,
            "id_resolves": id_rec is not None,
            "id_source": (id_rec.get("source") if id_rec else None),
            "classification": cls,
        }
        rows.append(row)
        if cls == C_DIVERGE:
            diverge.append(row)

    return {
        "generated_at": _now_iso(),
        "total": len(drafts),
        "counts": counts,
        "blocked": counts[C_DIVERGE] > 0,
        "blocked_reason": (
            f"{counts[C_DIVERGE]} draft(s) resolve to a different id by name than "
            f"the operator-selected contractor.id — Slice 2B-2 is blocked until zero."
            if counts[C_DIVERGE] > 0 else None
        ),
        "diverge_details": diverge,
        "drafts": rows,
    }
