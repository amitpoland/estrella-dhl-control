"""
carrier_shipment_db.py — SQLite registry for outbound carrier shipments.

Schema
------
  carrier_shipments
    id              TEXT PRIMARY KEY        (uuid4)
    batch_id        TEXT NOT NULL DEFAULT '' (parent PZ batch, may be empty
                                             for ad-hoc carrier shipments)
    carrier         TEXT NOT NULL            ("dhl" / "fedex" / "ups")
    awb             TEXT NOT NULL
    state           TEXT NOT NULL            (one of carrier_state_engine.STATES)
    label_sha256    TEXT NOT NULL DEFAULT ''
    manifest_path   TEXT NOT NULL DEFAULT ''
    created_at      TEXT NOT NULL
    updated_at      TEXT NOT NULL
    UNIQUE (carrier, awb)                    -- one row per (carrier, AWB)

  carrier_shipment_transitions
    id              TEXT PRIMARY KEY
    shipment_id     TEXT NOT NULL            -> carrier_shipments.id
    from_state      TEXT NOT NULL DEFAULT '' (empty on first row)
    to_state        TEXT NOT NULL
    reason          TEXT NOT NULL DEFAULT ''
    actor           TEXT NOT NULL DEFAULT 'system'
    created_at      TEXT NOT NULL

Hard rules
----------
1. Composite uniqueness on ``(carrier, awb)``: a single AWB can never
   represent two different shipments. ``upsert_shipment`` is the only
   write entry point and enforces this.
2. State validation lives in ``carrier_state_engine``. The DB layer
   only persists what it is told. Callers MUST validate via
   :func:`carrier_state_engine.transition` before calling
   :func:`record_transition`.
3. ``carrier_shipment_transitions`` is append-only. There is no
   ``delete_transition`` and no UPDATE path. Reversing a state change
   appends a new transition row going the other way.
4. The DB does NOT touch the label store and does NOT enqueue email,
   audit, or execution work. It is the persistence layer for the
   coordinator and nothing else.

Public API
----------
  init_db(db_path: Path) -> None
  upsert_shipment(...)                       -> Dict
  get_by_id(shipment_id)                     -> Dict | None
  get_by_awb(carrier, awb)                   -> Dict | None
  get_by_batch(batch_id)                     -> List[Dict]
  list_by_state(state, batch_id=None)        -> List[Dict]
  count_by_state(batch_id=None)              -> Dict[str, int]
  record_transition(...)                     -> Dict
  get_transitions(shipment_id)               -> List[Dict]
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import is_known_carrier
from .carrier_state_engine import STATES

_lock: threading.Lock = threading.Lock()
_db_path: Optional[Path] = None


# ── Init ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Idempotent schema setup for the carrier registry."""
    global _db_path
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS carrier_shipments (
                id              TEXT PRIMARY KEY,
                batch_id        TEXT NOT NULL DEFAULT '',
                carrier         TEXT NOT NULL,
                awb             TEXT NOT NULL,
                state           TEXT NOT NULL,
                label_sha256    TEXT NOT NULL DEFAULT '',
                manifest_path   TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_cs_carrier_awb
                ON carrier_shipments (carrier, awb);
            CREATE INDEX IF NOT EXISTS idx_cs_batch
                ON carrier_shipments (batch_id);
            CREATE INDEX IF NOT EXISTS idx_cs_state
                ON carrier_shipments (state);

            CREATE TABLE IF NOT EXISTS carrier_shipment_transitions (
                id              TEXT PRIMARY KEY,
                shipment_id     TEXT NOT NULL,
                from_state      TEXT NOT NULL DEFAULT '',
                to_state        TEXT NOT NULL,
                reason          TEXT NOT NULL DEFAULT '',
                actor           TEXT NOT NULL DEFAULT 'system',
                created_at      TEXT NOT NULL,
                FOREIGN KEY (shipment_id)
                    REFERENCES carrier_shipments(id)
            );

            CREATE INDEX IF NOT EXISTS idx_cst_shipment
                ON carrier_shipment_transitions (shipment_id, created_at);
        """)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError(
            "carrier_shipment_db not initialised — call init_db() first"
        )
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(r) if r else None


# ── Writers ─────────────────────────────────────────────────────────────────

def upsert_shipment(
    *,
    carrier:        str,
    awb:            str,
    state:          str,
    batch_id:       str = "",
    label_sha256:   str = "",
    manifest_path:  str = "",
) -> Dict[str, Any]:
    """Insert-or-update a shipment row keyed by ``(carrier, awb)``.

    On insert the ``id`` is a freshly generated uuid4. On update the
    existing ``id`` is preserved and only the mutable fields change.
    State validation is the caller's responsibility — pass a value
    from :data:`carrier_state_engine.STATES`.
    """
    if not is_known_carrier(carrier):
        raise ValueError(f"Unknown carrier {carrier!r}")
    if not (awb or "").strip():
        raise ValueError("awb is required")
    if state not in STATES:
        raise ValueError(
            f"Unknown carrier state {state!r}. Allowed: {sorted(STATES)}"
        )
    now = _now()
    with _lock, _connect() as con:
        prev = con.execute(
            "SELECT * FROM carrier_shipments WHERE carrier=? AND awb=?",
            (carrier, awb),
        ).fetchone()
        if prev:
            con.execute(
                """UPDATE carrier_shipments SET
                       batch_id      = CASE WHEN ?='' THEN batch_id      ELSE ? END,
                       state         = ?,
                       label_sha256  = CASE WHEN ?='' THEN label_sha256  ELSE ? END,
                       manifest_path = CASE WHEN ?='' THEN manifest_path ELSE ? END,
                       updated_at    = ?
                   WHERE id=?""",
                (batch_id, batch_id,
                 state,
                 label_sha256, label_sha256,
                 manifest_path, manifest_path,
                 now,
                 prev["id"]),
            )
            row_id = prev["id"]
        else:
            row_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO carrier_shipments
                       (id, batch_id, carrier, awb, state,
                        label_sha256, manifest_path,
                        created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (row_id, batch_id, carrier, awb, state,
                 label_sha256, manifest_path,
                 now, now),
            )
        row = con.execute(
            "SELECT * FROM carrier_shipments WHERE id=?", (row_id,),
        ).fetchone()
    return dict(row)


def record_transition(
    *,
    shipment_id:    str,
    from_state:     str,
    to_state:       str,
    reason:         str = "",
    actor:          str = "system",
) -> Dict[str, Any]:
    """Append a transition row.

    The DB layer does not validate (from_state → to_state) legality —
    that is :func:`carrier_state_engine.transition`'s job. Callers
    MUST validate before reaching this function. The empty-string
    *from_state* is allowed (and conventional) for the very first
    transition row of a shipment.
    """
    if not (shipment_id or "").strip():
        raise ValueError("shipment_id is required")
    if to_state not in STATES:
        raise ValueError(
            f"Unknown to_state {to_state!r}. Allowed: {sorted(STATES)}"
        )
    if from_state and from_state not in STATES:
        raise ValueError(
            f"Unknown from_state {from_state!r}. Allowed: {sorted(STATES)}"
        )
    rid = str(uuid.uuid4())
    now = _now()
    with _lock, _connect() as con:
        con.execute(
            """INSERT INTO carrier_shipment_transitions
                   (id, shipment_id, from_state, to_state,
                    reason, actor, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (rid, shipment_id, from_state or "", to_state,
             reason, actor, now),
        )
        row = con.execute(
            "SELECT * FROM carrier_shipment_transitions WHERE id=?", (rid,),
        ).fetchone()
    return dict(row)


# ── Readers ─────────────────────────────────────────────────────────────────

def get_by_id(shipment_id: str) -> Optional[Dict[str, Any]]:
    if not (shipment_id or "").strip():
        return None
    with _connect() as con:
        return _row(con.execute(
            "SELECT * FROM carrier_shipments WHERE id=?",
            (shipment_id,),
        ).fetchone())


def get_by_awb(carrier: str, awb: str) -> Optional[Dict[str, Any]]:
    if not is_known_carrier(carrier) or not (awb or "").strip():
        return None
    with _connect() as con:
        return _row(con.execute(
            "SELECT * FROM carrier_shipments WHERE carrier=? AND awb=?",
            (carrier, awb),
        ).fetchone())


def get_by_batch(batch_id: str) -> List[Dict[str, Any]]:
    if not (batch_id or "").strip():
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM carrier_shipments WHERE batch_id=? "
            "ORDER BY created_at",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_by_batch_and_reference(
    batch_id: str,
    reference: str,
) -> Optional[Dict[str, Any]]:
    """Find the shipment row in *batch_id* whose manifest's
    ``request.reference`` matches *reference*.

    DL-F3.5a — idempotency lookup. Empty *reference* returns None
    (does NOT collapse all batches into one). Empty *batch_id*
    returns None.

    The shipments table itself does not store the operator-supplied
    reference (it lives in the per-AWB manifest JSON written by
    ``carrier_label_store.write_manifest``). This helper scans the
    batch's rows and reads each manifest_path to find the match.
    Typical batch carries 1-3 shipments; the scan is cheap.

    A row whose ``manifest_path`` is missing on disk or whose
    manifest JSON is corrupt is skipped silently — the caller's
    coordinator path then falls through to a fresh adapter call,
    which re-creates the manifest cleanly.
    """
    if not (batch_id or "").strip() or not (reference or "").strip():
        return None
    rows = get_by_batch(batch_id)
    for row in rows:
        manifest_path = (row.get("manifest_path") or "").strip()
        if not manifest_path:
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        existing_ref = (
            (payload.get("request") or {}).get("reference") or ""
        )
        if existing_ref == reference:
            return row
    return None


def list_all(
    *,
    state:  Optional[str] = None,
    limit:  Optional[int] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return shipment rows ordered by ``created_at``.

    Optional ``state`` narrows to a single state (validated). Optional
    ``limit`` / ``offset`` paginate. Used by the read-only routes —
    keeps the SQL inside the DB module instead of leaking it to the
    API layer.
    """
    if state is not None and state not in STATES:
        raise ValueError(
            f"Unknown carrier state {state!r}. Allowed: {sorted(STATES)}"
        )
    sql = "SELECT * FROM carrier_shipments"
    params: List[Any] = []
    if state is not None:
        sql += " WHERE state=?"
        params.append(state)
    sql += " ORDER BY created_at"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    with _connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_by_state(state: str, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if state not in STATES:
        raise ValueError(
            f"Unknown carrier state {state!r}. Allowed: {sorted(STATES)}"
        )
    with _connect() as con:
        if batch_id:
            rows = con.execute(
                "SELECT * FROM carrier_shipments WHERE state=? AND batch_id=? "
                "ORDER BY created_at",
                (state, batch_id),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM carrier_shipments WHERE state=? "
                "ORDER BY created_at",
                (state,),
            ).fetchall()
    return [dict(r) for r in rows]


def count_by_state(batch_id: Optional[str] = None) -> Dict[str, int]:
    counts: Dict[str, int] = {s: 0 for s in STATES}
    with _connect() as con:
        if batch_id:
            rows = con.execute(
                "SELECT state, COUNT(*) AS n FROM carrier_shipments "
                "WHERE batch_id=? GROUP BY state",
                (batch_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT state, COUNT(*) AS n FROM carrier_shipments "
                "GROUP BY state"
            ).fetchall()
    for r in rows:
        if r["state"] in counts:
            counts[r["state"]] = r["n"]
    return counts


def get_transitions(shipment_id: str) -> List[Dict[str, Any]]:
    if not (shipment_id or "").strip():
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM carrier_shipment_transitions "
            "WHERE shipment_id=? ORDER BY created_at, id",
            (shipment_id,),
        ).fetchall()
    return [dict(r) for r in rows]
