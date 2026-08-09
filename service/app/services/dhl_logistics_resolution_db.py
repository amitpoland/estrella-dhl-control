"""dhl_logistics_resolution_db.py — Control Tower reporting-resolution authority.

Admin-only manual resolve/reopen for stale logistics rows. Reporting exception
authority ONLY — never mutates tracking_cache, tracking_db, carrier shipments,
audit DHL events, customs, PZ, financial, or inventory records.

Storage: ``<storage_root>/dhl_logistics_resolutions.db``
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RESOLUTION_HISTORICAL_DELIVERED = "historical_delivered"
RESOLUTION_CLOSED = "closed_no_longer_operational"
RESOLUTION_REOPENED = "reopened"

_ACTIVE_STATUSES = frozenset({RESOLUTION_HISTORICAL_DELIVERED, RESOLUTION_CLOSED})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    from ..core.config import settings
    return Path(settings.storage_root) / "dhl_logistics_resolutions.db"


def init_db(path: Optional[Path] = None) -> Path:
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(p)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dhl_logistics_resolution (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                awb TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
                resolution_status TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT,
                comment TEXT,
                manual_delivered_at TEXT,
                manual_location TEXT,
                previous_projection_json TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (direction, awb)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dhl_logistics_resolution_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                awb TEXT NOT NULL,
                direction TEXT NOT NULL,
                action TEXT NOT NULL,
                resolution_status TEXT,
                comment TEXT,
                manual_delivered_at TEXT,
                manual_location TEXT,
                previous_projection_json TEXT,
                actor TEXT NOT NULL,
                at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlr_active ON dhl_logistics_resolution (active)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlr_awb ON dhl_logistics_resolution (awb)"
        )
        conn.commit()
    return p


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = init_db(path)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    prev = d.pop("previous_projection_json", None)
    if prev:
        try:
            d["previous_projection"] = json.loads(prev)
        except Exception:
            d["previous_projection"] = None
    else:
        d["previous_projection"] = None
    d["active"] = bool(d.get("active"))
    return d


def get_active_resolution(
    awb: str,
    direction: str,
    *,
    path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    awb = str(awb or "").strip()
    direction = str(direction or "").strip().lower()
    if not awb or direction not in ("inbound", "outbound"):
        return None
    with _connect(path) as conn:
        row = conn.execute(
            """
            SELECT * FROM dhl_logistics_resolution
            WHERE awb = ? AND direction = ? AND active = 1
            """,
            (awb, direction),
        ).fetchone()
    return _row_to_dict(row)


def list_active_resolutions(*, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM dhl_logistics_resolution WHERE active = 1"
        ).fetchall()
    return [r for r in (_row_to_dict(x) for x in rows) if r]


def resolve(
    *,
    awb: str,
    direction: str,
    resolution_status: str,
    comment: str,
    resolved_by: str,
    manual_delivered_at: Optional[str] = None,
    manual_location: Optional[str] = None,
    previous_projection: Optional[Dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    awb = str(awb or "").strip()
    direction = str(direction or "").strip().lower()
    resolution_status = str(resolution_status or "").strip()
    comment = str(comment or "").strip()
    resolved_by = str(resolved_by or "").strip() or "anonymous"

    if not awb:
        raise ValueError("awb required")
    if direction not in ("inbound", "outbound"):
        raise ValueError("direction must be inbound or outbound")
    if resolution_status not in _ACTIVE_STATUSES:
        raise ValueError("unsupported resolution_status")
    if not comment:
        raise ValueError("comment required")
    if resolution_status == RESOLUTION_HISTORICAL_DELIVERED and not manual_delivered_at:
        raise ValueError("manual_delivered_at required for historical_delivered")

    now = _now()
    prev_json = json.dumps(previous_projection or {}, default=str)
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO dhl_logistics_resolution (
                awb, direction, resolution_status, resolved_at, resolved_by,
                comment, manual_delivered_at, manual_location,
                previous_projection_json, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(direction, awb) DO UPDATE SET
                resolution_status = excluded.resolution_status,
                resolved_at = excluded.resolved_at,
                resolved_by = excluded.resolved_by,
                comment = excluded.comment,
                manual_delivered_at = excluded.manual_delivered_at,
                manual_location = excluded.manual_location,
                previous_projection_json = excluded.previous_projection_json,
                active = 1,
                updated_at = excluded.updated_at
            """,
            (
                awb,
                direction,
                resolution_status,
                now,
                resolved_by,
                comment,
                manual_delivered_at,
                manual_location,
                prev_json,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO dhl_logistics_resolution_audit (
                awb, direction, action, resolution_status, comment,
                manual_delivered_at, manual_location, previous_projection_json,
                actor, at_utc
            ) VALUES (?, ?, 'resolve', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                awb,
                direction,
                resolution_status,
                comment,
                manual_delivered_at,
                manual_location,
                prev_json,
                resolved_by,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM dhl_logistics_resolution WHERE awb = ? AND direction = ?",
            (awb, direction),
        ).fetchone()
    out = _row_to_dict(row)
    assert out is not None
    return out


def reopen(
    *,
    awb: str,
    direction: str,
    comment: str,
    resolved_by: str,
    previous_projection: Optional[Dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    awb = str(awb or "").strip()
    direction = str(direction or "").strip().lower()
    comment = str(comment or "").strip()
    resolved_by = str(resolved_by or "").strip() or "anonymous"
    if not awb:
        raise ValueError("awb required")
    if direction not in ("inbound", "outbound"):
        raise ValueError("direction must be inbound or outbound")
    if not comment:
        raise ValueError("comment required")

    now = _now()
    prev_json = json.dumps(previous_projection or {}, default=str)
    with _connect(path) as conn:
        existing = conn.execute(
            "SELECT * FROM dhl_logistics_resolution WHERE awb = ? AND direction = ?",
            (awb, direction),
        ).fetchone()
        if existing is None:
            raise KeyError("no resolution to reopen")
        conn.execute(
            """
            UPDATE dhl_logistics_resolution SET
                resolution_status = ?,
                active = 0,
                comment = ?,
                resolved_by = ?,
                resolved_at = ?,
                updated_at = ?,
                previous_projection_json = ?
            WHERE awb = ? AND direction = ?
            """,
            (
                RESOLUTION_REOPENED,
                comment,
                resolved_by,
                now,
                now,
                prev_json,
                awb,
                direction,
            ),
        )
        conn.execute(
            """
            INSERT INTO dhl_logistics_resolution_audit (
                awb, direction, action, resolution_status, comment,
                manual_delivered_at, manual_location, previous_projection_json,
                actor, at_utc
            ) VALUES (?, ?, 'reopen', ?, ?, NULL, NULL, ?, ?, ?)
            """,
            (awb, direction, RESOLUTION_REOPENED, comment, prev_json, resolved_by, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM dhl_logistics_resolution WHERE awb = ? AND direction = ?",
            (awb, direction),
        ).fetchone()
    out = _row_to_dict(row)
    assert out is not None
    return out


def list_audit(awb: str, direction: str, *, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM dhl_logistics_resolution_audit
            WHERE awb = ? AND direction = ?
            ORDER BY id DESC
            """,
            (str(awb).strip(), str(direction).strip().lower()),
        ).fetchall()
    return [dict(r) for r in rows]
