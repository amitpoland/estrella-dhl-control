"""Per-piece inventory read service.

Wraps inventory_state_engine + warehouse_db readers and composes the
response shape for GET /api/v1/inventory/pieces/{piece_id}. Read-only.
Never raises on missing piece — returns the same envelope with
state=None, empty timeline, empty history.

Phase B.2 — Unified piece timeline:
  Three append-only event sources are merged into a single
  chronologically-sorted `timeline` array (see
  docs/operational-memory/inventory/PIECE_TIMELINE_DESIGN.md):

    kind='lifecycle' — inventory_state_events (via inventory_state_engine)
    kind='movement'  — inventory_movement_events (via warehouse_db)
    kind='sample'    — sample_out_events (via warehouse_db)

  The legacy `history` field is preserved verbatim (= lifecycle events
  only) for backward compatibility with existing UI/test consumers
  for one release. The `location` snapshot is added so callers don't
  have to round-trip to /warehouse/inventory.

  Each source is wrapped in its own try/except: a single failing
  reader degrades only its kind's events, populates `limitations[]`
  and flips top-level `degraded=True`, while the other two kinds and
  the snapshots still render.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import inventory_state_engine
from . import warehouse_db


# kind ordering for tie-break when two events share occurred_at.
# Mirrors causality: a state transition logically precedes the side-effect
# write that records it, which precedes any sample evidence row.
_KIND_PRIORITY: Dict[str, int] = {
    "lifecycle": 0,
    "movement":  1,
    "sample":    2,
}


def _lifecycle_summary(row: Dict[str, Any]) -> str:
    frm = (row.get("from_state") or "").strip()
    to  = (row.get("to_state")   or "").strip()
    if frm:
        return f"{frm} -> {to}"
    return f"-> {to}"


def _movement_summary(row: Dict[str, Any]) -> str:
    frm = (row.get("from_location") or "").strip()
    to  = (row.get("to_location")   or "").strip()
    action = (row.get("action") or "MOVE").strip()
    if not to:
        return f"{action.lower()}"
    if frm:
        return f"moved {frm} -> {to}"
    return f"moved to {to}"


def _sample_summary(row: Dict[str, Any]) -> str:
    direction = (row.get("direction") or "").strip()
    if direction == "out":
        recipient = (row.get("recipient_client_name") or "").strip() or "unknown"
        reason    = (row.get("sample_reason") or "").strip()
        if reason:
            return f"sample-out to {recipient} ({reason})"
        return f"sample-out to {recipient}"
    if direction == "return":
        return "sample-return to warehouse"
    return f"sample event ({direction or 'unknown'})"


def _lifecycle_entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append({
            "kind":        "lifecycle",
            "occurred_at": r.get("occurred_at") or "",
            "operator":    r.get("operator")    or "",
            "event_id":    r.get("id")          or "",
            "summary":     _lifecycle_summary(r),
            "detail": {
                "from_state": r.get("from_state") or "",
                "to_state":   r.get("to_state")   or "",
                "trigger":    r.get("trigger")    or "",
                "note":       r.get("note")      or "",
            },
        })
    return out


def _movement_entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        # Movement table uses `event_time`, not `occurred_at`. Normalise
        # at the API boundary so the merged array has one sort key.
        out.append({
            "kind":        "movement",
            "occurred_at": r.get("event_time") or "",
            "operator":    r.get("operator")   or "",
            "event_id":    r.get("id")         or "",
            "summary":     _movement_summary(r),
            "detail": {
                "action":        r.get("action")        or "",
                "from_location": r.get("from_location") or "",
                "to_location":   r.get("to_location")   or "",
                "note":          r.get("note")          or "",
            },
        })
    return out


def _sample_entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append({
            "kind":        "sample",
            "occurred_at": r.get("occurred_at") or "",
            "operator":    r.get("operator")   or "",
            "event_id":    r.get("id")         or "",
            "summary":     _sample_summary(r),
            "detail": {
                "direction":              r.get("direction")              or "",
                "recipient_client_name":  r.get("recipient_client_name")  or "",
                "recipient_client_id":    r.get("recipient_client_id")    or "",
                "sample_reason":          r.get("sample_reason")          or "",
                "expected_return_date":   r.get("expected_return_date")   or "",
                "linked_origin_event_id": r.get("linked_origin_event_id") or "",
                "notes":                  r.get("notes")                  or "",
            },
        })
    return out


def _sort_key(entry: Dict[str, Any]) -> Tuple[str, int, str]:
    return (
        entry.get("occurred_at") or "",
        _KIND_PRIORITY.get(entry.get("kind", ""), 99),
        entry.get("event_id")   or "",
    )


def get_piece_detail(piece_id: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Return state + location + unified timeline + legacy history for one scan_code.

    Response shape (Phase B.2):
      {
        "piece_id":    <str>,
        "as_of":       <ISO8601 str>,
        "found":       True | False,
        "degraded":    True | False,
        "state":       <inventory_state row | None>,
        "location":    <inventory_current_location row | None>,
        "history":     [<lifecycle event row>, ...],  # legacy alias
        "timeline":    [
          {"kind": "lifecycle"|"movement"|"sample",
           "occurred_at": <ISO8601 str>,
           "operator": <str>,
           "event_id": <str>,
           "summary": <str>,
           "detail": {...}},
          ...
        ],
        "limitations": [<str>, ...],  # one per degraded source
      }

    Honest empty: unknown piece -> found=False, state=None, location=None,
    history=[], timeline=[], degraded=False (unless a reader raised).
    Honest degraded: any reader that raises sets degraded=True and adds
    a "<source>: <reason>" entry to limitations[]; the other readers
    still contribute their events.
    """
    ts = as_of or datetime.now(timezone.utc).isoformat()
    limitations: List[str] = []

    # 1. State snapshot. If the state reader fails, we degrade the whole
    #    envelope — without state we cannot honestly say `found`.
    try:
        state = inventory_state_engine.get_state(piece_id)
    except Exception as e:
        return {
            "piece_id":    piece_id,
            "as_of":       ts,
            "found":       False,
            "degraded":    True,
            "state":       None,
            "location":    None,
            "history":     [],
            "timeline":    [],
            "limitations": [f"inventory_state: {e!s}" or "inventory_state: reader failed"],
        }

    # 2. Location snapshot.
    try:
        location = warehouse_db.get_current_location(piece_id)
    except Exception as e:
        location = None
        limitations.append(f"inventory_current_location: {e!s}"
                           or "inventory_current_location: reader failed")

    # 3. Three event readers — independent failure isolation.
    try:
        lifecycle_rows = inventory_state_engine.get_history(piece_id)
    except Exception as e:
        lifecycle_rows = []
        limitations.append(f"inventory_state_events: {e!s}"
                           or "inventory_state_events: reader failed")

    try:
        movement_rows = warehouse_db.get_movement_history(piece_id)
    except Exception as e:
        movement_rows = []
        limitations.append(f"inventory_movement_events: {e!s}"
                           or "inventory_movement_events: reader failed")

    try:
        sample_rows = warehouse_db.get_sample_out_history(piece_id)
    except Exception as e:
        sample_rows = []
        limitations.append(f"sample_out_events: {e!s}"
                           or "sample_out_events: reader failed")

    # 4. Compose unified timeline. Server-side merge + sort by
    #    (occurred_at asc, kind priority asc, event_id asc).
    merged: List[Dict[str, Any]] = []
    merged.extend(_lifecycle_entries(lifecycle_rows))
    merged.extend(_movement_entries(movement_rows))
    merged.extend(_sample_entries(sample_rows))
    merged.sort(key=_sort_key)

    return {
        "piece_id":    piece_id,
        "as_of":       ts,
        "found":       state is not None,
        "degraded":    bool(limitations),
        "state":       state,
        "location":    location,
        # Legacy alias preserved for one release. Existing consumers
        # that read `pieceDetail.history` keep working.
        "history":     lifecycle_rows,
        "timeline":    merged,
        "limitations": limitations,
    }
