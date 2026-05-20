"""Inventory batch-state read service.

Wraps `inventory_state_engine.count_by_state(batch_id=)` and adds a
`scan_code -> state` listing for the same batch. Read-only. Never raises
on missing batch — returns empty counts + empty pieces list.

C13A (2026-05-20): when a batch has zero real inventory_state rows but
its audit/tracking shows the shipment is in DHL/customs flight, this
service emits a READ-ONLY synthetic PURCHASE_TRANSIT projection from
the packing lines.  See
``inventory_state_engine.derive_purchase_transit_projection`` for the
authority rules.  Synthetic rows NEVER mutate any DB.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from . import inventory_state_engine
from . import packing_db


def get_batch_state(batch_id: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Return the inventory state summary for one batch.

    Response shape:
      {
        "batch_id": <str>,
        "as_of": <ISO8601 str>,
        "counts": {state_name: int, ...},        # disjoint per-state counts
        "pieces": [{"scan_code": str, "state": str, "product_code": str,
                     "design_no": str, "updated_at": str,
                     "synthetic"?: bool, "source"?: str}, ...],
        "total": int,                             # sum of counts; len(pieces)
        "synthetic": bool,                        # True when all pieces are
                                                  # synthetic transit projection
                                                  # (C13A); False when real
                                                  # inventory_state rows
                                                  # populated the response.
        "source": str,                            # "inventory_state" |
                                                  # "audit.tracking" |
                                                  # "empty"
      }

    Honest empty: missing batch and no transit signal -> counts all zero,
    pieces=[], synthetic=False, source="empty".
    """
    try:
        counts = inventory_state_engine.count_by_state(batch_id=batch_id)
    except Exception:
        # Honest empty when warehouse_db is unavailable. Same posture as
        # inventory_stage2_aggregator: never 500, never invented zero — but
        # caller can read it. Status flag lives in `degraded`.
        counts = {s: 0 for s in inventory_state_engine.STATES}
        return {
            "batch_id":  batch_id,
            "as_of":     as_of or datetime.now(timezone.utc).isoformat(),
            "counts":    counts,
            "pieces":    [],
            "total":     0,
            "synthetic": False,
            "source":    "empty",
            "degraded":  True,
        }
    try:
        pieces = _list_pieces_for_batch(batch_id)
    except Exception:
        pieces = []
    real_total = sum(counts.values())

    # ── C13A — synthetic PURCHASE_TRANSIT projection ─────────────────────────
    # If we have zero real rows, attempt the read-only projection from
    # audit.json + packing lines.  Real rows always win — if any are present,
    # we do NOT mix them with synthetic ones.
    synthetic = False
    source    = "inventory_state" if real_total > 0 else "empty"
    if real_total == 0:
        projection = _try_purchase_transit_projection(batch_id)
        if projection:
            pieces = projection
            # Refresh counts to reflect the synthetic projection so dashboards
            # can render a meaningful PURCHASE_TRANSIT count.  We do NOT call
            # count_by_state again — that would re-read the DB and return 0.
            counts = {s: 0 for s in inventory_state_engine.STATES}
            counts[inventory_state_engine.PURCHASE_TRANSIT] = len(projection)
            synthetic = True
            source    = "audit.tracking"

    return {
        "batch_id":  batch_id,
        "as_of":     as_of or datetime.now(timezone.utc).isoformat(),
        "counts":    counts,
        "pieces":    pieces,
        "total":     sum(counts.values()),
        "synthetic": synthetic,
        "source":    source,
        "degraded":  False,
    }


def _list_pieces_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    """All inventory_state rows for a batch, projected to a compact shape."""
    if not batch_id:
        return []
    with inventory_state_engine._connect() as con:
        rows = con.execute(
            "SELECT scan_code, state, product_code, design_no, updated_at "
            "FROM inventory_state WHERE batch_id=? ORDER BY scan_code",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── C13A helpers ─────────────────────────────────────────────────────────────

def _try_purchase_transit_projection(batch_id: str) -> List[Dict[str, Any]]:
    """Read audit.json + packing lines and call the engine projector.

    Returns [] on any error — projection is best-effort and must NEVER
    break the underlying state endpoint.
    """
    if not batch_id:
        return []
    audit = _read_audit_safe(batch_id)
    if not isinstance(audit, dict):
        return []
    try:
        lines = packing_db.get_packing_lines_for_batch(batch_id)
    except Exception:
        return []
    try:
        return inventory_state_engine.derive_purchase_transit_projection(
            batch_id=batch_id, audit=audit, packing_lines=lines,
        )
    except Exception:
        return []


def _read_audit_safe(batch_id: str) -> Optional[Dict[str, Any]]:
    """Read storage_root/outputs/<batch>/audit.json. None on any error."""
    try:
        audit_path = Path(settings.storage_root) / "outputs" / batch_id / "audit.json"
        if not audit_path.exists():
            return None
        with audit_path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
