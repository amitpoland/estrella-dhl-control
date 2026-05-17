"""packing_resolution_db.py — B0.X R2 persistence for resolver verdicts.

Stores one row per (batch_id, role) holding the resolver's verdict + any
operator override + audit trail.

Hard rules:
- Additive table only. No FK constraints (soft references).
- Per-batch unique constraint: each batch has at most one client and one
  supplier resolution.
- No mutation of customer_master / suppliers tables here. The resolver
  is read-only against those (R1 contract).
- No wFirma call. No proforma / PZ / DHL / customs / finance import.

Storage: ``<storage_root>/packing_resolutions.sqlite``
Table:   packing_contractor_resolution
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_VALID_ROLES = ("client", "supplier")
_VALID_STATUSES = ("auto", "unresolved", "confirmed", "overridden")


# ── Schema ───────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create the resolution table if it does not exist. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS packing_contractor_resolution (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id              TEXT NOT NULL,
                role                  TEXT NOT NULL
                    CHECK (role IN ('client','supplier')),
                parsed_name           TEXT NOT NULL,
                parsed_tax_id         TEXT,
                parsed_country        TEXT,
                matched_master_type   TEXT,
                matched_master_id     INTEGER,
                matched_wfirma_id     TEXT,
                tier                  INTEGER NOT NULL,
                confidence            REAL NOT NULL,
                reason                TEXT NOT NULL,
                evidence_json         TEXT,
                candidates_json       TEXT,
                status                TEXT NOT NULL
                    CHECK (status IN ('auto','unresolved','confirmed','overridden')),
                operator_override     INTEGER NOT NULL DEFAULT 0,
                operator_user         TEXT,
                operator_at           TEXT,
                created_at            TEXT NOT NULL,
                updated_at            TEXT NOT NULL,
                UNIQUE (batch_id, role)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pcr_batch  ON packing_contractor_resolution (batch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pcr_role   ON packing_contractor_resolution (role)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pcr_status ON packing_contractor_resolution (status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pcr_wfirma ON packing_contractor_resolution (matched_wfirma_id)")
        conn.commit()


# ── CRUD ─────────────────────────────────────────────────────────────────────


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Hydrate a SQLite row into the API-facing dict (JSON columns decoded)."""
    out: Dict[str, Any] = dict(row)
    try:
        out["evidence"] = json.loads(out.pop("evidence_json") or "{}")
    except Exception:
        out["evidence"] = {}
        out.pop("evidence_json", None)
    try:
        out["candidates"] = json.loads(out.pop("candidates_json") or "[]")
    except Exception:
        out["candidates"] = []
        out.pop("candidates_json", None)
    out["operator_override"] = bool(out.get("operator_override"))
    return out


def upsert_resolution(
    db_path: Path,
    *,
    batch_id: str,
    role: str,
    verdict: Dict[str, Any],
    operator_user: Optional[str] = None,
    operator_override: bool = False,
    status_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a resolver verdict for (batch_id, role).

    Parameters
    ----------
    batch_id, role
        Composite identity. ``UNIQUE (batch_id, role)`` enforces 1 row each.
    verdict
        Output of ``packing_contractor_resolver.resolve_contractor``.
    operator_user
        Audit trail. None / empty → stored as 'anonymous'.
    operator_override
        True when the operator picked a row different from the resolver's
        suggestion. Sets ``status='overridden'`` if not explicitly told otherwise.
    status_override
        When the operator merely confirms a suggested auto match, the route
        passes ``status_override='confirmed'``. Otherwise the verdict's own
        ``status`` is used.

    Returns the persisted row as a dict (with evidence + candidates decoded).
    Raises ValueError on missing required fields.
    """
    if not (batch_id or "").strip():
        raise ValueError("batch_id is required")
    if role not in _VALID_ROLES:
        raise ValueError(f"role must be one of {_VALID_ROLES}, got {role!r}")
    if not isinstance(verdict, dict):
        raise ValueError("verdict must be a dict")

    status = (status_override or verdict.get("status") or "unresolved").strip()
    if operator_override and status_override is None:
        status = "overridden"
    if status not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {_VALID_STATUSES}, got {status!r}")

    parsed_name = (verdict.get("parsed_name") or "").strip()
    if not parsed_name:
        raise ValueError("verdict.parsed_name is required")

    init_db(db_path)
    now = _now()
    user = (operator_user or "").strip() or "anonymous"

    payload = {
        "batch_id":            batch_id.strip(),
        "role":                role,
        "parsed_name":         parsed_name,
        "parsed_tax_id":       verdict.get("parsed_tax_id") or None,
        "parsed_country":      verdict.get("parsed_country") or None,
        "matched_master_type": verdict.get("matched_master_type"),
        "matched_master_id":   verdict.get("matched_master_id"),
        "matched_wfirma_id":   verdict.get("matched_wfirma_id"),
        "tier":                int(verdict.get("tier") or 6),
        "confidence":          float(verdict.get("confidence") or 0.0),
        "reason":              verdict.get("reason") or "no_match",
        "evidence_json":       json.dumps(verdict.get("evidence") or {}, ensure_ascii=False),
        "candidates_json":     json.dumps(verdict.get("candidates") or [], ensure_ascii=False),
        "status":              status,
        "operator_override":   1 if operator_override else 0,
        "operator_user":       user,
        "operator_at":         now if (operator_override or status_override) else None,
        "updated_at":          now,
    }

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id, created_at FROM packing_contractor_resolution "
            "WHERE batch_id = ? AND role = ?",
            (payload["batch_id"], payload["role"]),
        ).fetchone()
        if existing is None:
            payload["created_at"] = now
            cols = ",".join(payload.keys())
            placeholders = ",".join("?" for _ in payload)
            conn.execute(
                f"INSERT INTO packing_contractor_resolution ({cols}) VALUES ({placeholders})",
                tuple(payload.values()),
            )
        else:
            # Preserve original created_at on UPDATE.
            set_clause = ",".join(f"{k} = ?" for k in payload.keys())
            conn.execute(
                f"UPDATE packing_contractor_resolution SET {set_clause} WHERE id = ?",
                tuple(payload.values()) + (int(existing["id"]),),
            )
        conn.commit()

    return get_resolution(db_path, batch_id=batch_id, role=role) or {}


def get_resolution(
    db_path: Path,
    *,
    batch_id: str,
    role: str,
) -> Optional[Dict[str, Any]]:
    """Read a single resolution by (batch_id, role)."""
    if not (batch_id or "").strip():
        return None
    if role not in _VALID_ROLES:
        return None
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM packing_contractor_resolution "
            "WHERE batch_id = ? AND role = ?",
            (batch_id.strip(), role),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_resolutions_for_batch(
    db_path: Path,
    batch_id: str,
) -> List[Dict[str, Any]]:
    """Return all resolutions (client + supplier if both stored) for a batch."""
    if not (batch_id or "").strip():
        return []
    if not Path(db_path).is_file():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM packing_contractor_resolution "
            "WHERE batch_id = ? ORDER BY role",
            (batch_id.strip(),),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


__all__ = [
    "init_db",
    "upsert_resolution",
    "get_resolution",
    "list_resolutions_for_batch",
]
