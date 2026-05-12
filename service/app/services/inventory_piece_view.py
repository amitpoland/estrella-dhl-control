"""Per-piece inventory read service.

Wraps inventory_state_engine.get_state() + get_history() and composes
the response shape for GET /api/v1/inventory/pieces/{piece_id}. Read-only.
Never raises on missing piece — returns the same envelope with state=None
and empty history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import inventory_state_engine


def get_piece_detail(piece_id: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Return state + history for one scan_code.

    Response shape:
      {
        "piece_id": <str>,         # echo of input
        "as_of": <ISO8601 str>,
        "found": True | False,
        "state": <dict | None>,    # full inventory_state row, or None if absent
        "history": [<event row>, ...],   # chronological list, [] if absent
        "degraded": True | False,  # True if warehouse_db unavailable
      }

    Honest empty: unknown piece -> found=False, state=None, history=[],
    HTTP 200. Honest degraded: warehouse_db unavailable -> degraded=True,
    state=None, history=[].
    """
    ts = as_of or datetime.now(timezone.utc).isoformat()
    try:
        state = inventory_state_engine.get_state(piece_id)
    except Exception:
        return {
            "piece_id": piece_id,
            "as_of": ts,
            "found": False,
            "state": None,
            "history": [],
            "degraded": True,
        }
    try:
        history = inventory_state_engine.get_history(piece_id)
    except Exception:
        history = []
    return {
        "piece_id": piece_id,
        "as_of": ts,
        "found": state is not None,
        "state": state,
        "history": history,
        "degraded": False,
    }
