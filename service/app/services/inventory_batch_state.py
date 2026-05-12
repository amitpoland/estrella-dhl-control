"""Inventory batch-state read service.

Wraps `inventory_state_engine.count_by_state(batch_id=)` and adds a
`scan_code -> state` listing for the same batch. Read-only. Never raises
on missing batch — returns empty counts + empty pieces list.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import inventory_state_engine


def get_batch_state(batch_id: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Return the inventory state summary for one batch.

    Response shape:
      {
        "batch_id": <str>,
        "as_of": <ISO8601 str>,
        "counts": {state_name: int, ...},        # disjoint per-state counts
        "pieces": [{"scan_code": str, "state": str, "product_code": str,
                     "design_no": str, "updated_at": str}, ...],
        "total": int                              # sum of counts; len(pieces)
      }

    Honest empty: missing batch -> counts all zero, pieces=[].
    """
    try:
        counts = inventory_state_engine.count_by_state(batch_id=batch_id)
    except Exception:
        # Honest empty when warehouse_db is unavailable. Same posture as
        # inventory_stage2_aggregator: never 500, never invented zero — but
        # caller can read it. Status flag lives in `degraded`.
        counts = {s: 0 for s in inventory_state_engine.STATES}
        return {
            "batch_id": batch_id,
            "as_of": as_of or datetime.now(timezone.utc).isoformat(),
            "counts": counts,
            "pieces": [],
            "total": 0,
            "degraded": True,
        }
    try:
        pieces = _list_pieces_for_batch(batch_id)
    except Exception:
        pieces = []
    return {
        "batch_id": batch_id,
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "pieces": pieces,
        "total": sum(counts.values()),
        "degraded": False,
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
