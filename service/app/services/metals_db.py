"""metals_db.py — Local metals master (Phase 3).

Storage: <storage_root>/metals.sqlite (separate file per operator instruction
2026-05-28 — don't grow master_data.sqlite further).

Authority: LOCAL valuation reference. Does NOT overwrite wFirma products;
PZ landed-cost engine does NOT read this table.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Domain ──────────────────────────────────────────────────────────────────

METAL_TYPES = ("gold", "silver", "platinum", "palladium", "other")

# Allowed purity per metal type. "other" accepts 1..999.
_ALLOWED_PURITY: Dict[str, frozenset] = {
    "gold":      frozenset({375, 585, 750, 916, 999}),
    "silver":    frozenset({800, 925, 999}),
    "platinum":  frozenset({850, 900, 950, 999}),
    "palladium": frozenset({850, 900, 950, 999}),
}

_CODE_RE = re.compile(r"^[A-Z0-9_-]{2,32}$")


@dataclass
class Metal:
    code:         str
    name:         Optional[str] = None
    metal_type:   Optional[str] = None
    purity_pct:   Optional[int] = None      # integer per millage (e.g. 750)
    purity_label: Optional[str] = None
    active:       bool          = True
    notes:        Optional[str] = None
    created_at:   Optional[str] = None
    updated_at:   Optional[str] = None
    deleted_at:   Optional[str] = None      # Phase 4A — soft-delete timestamp


def metal_to_dict(m: Metal) -> Dict[str, Any]:
    return asdict(m)


# ── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metals (
    code         TEXT PRIMARY KEY,
    name         TEXT,
    metal_type   TEXT,
    purity_pct   INTEGER,
    purity_label TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    notes        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    deleted_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_metals_type  ON metals (metal_type);
CREATE INDEX IF NOT EXISTS ix_metals_active ON metals (active);
"""


def _migrate_add_deleted_at(cx: sqlite3.Connection) -> None:
    """Idempotent column add for tables that existed before Phase 4A.
    SQLite ALTER TABLE has no IF NOT EXISTS; we swallow only the
    'duplicate column' error and re-raise anything else."""
    try:
        cx.execute("ALTER TABLE metals ADD COLUMN deleted_at TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as cx:
        cx.executescript(_SCHEMA)
        _migrate_add_deleted_at(cx)


# ── Validation ──────────────────────────────────────────────────────────────

def validate_metal(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    code = (data.get("code") or "").strip()
    if not code:
        errs.append("code is required")
    elif not _CODE_RE.match(code):
        errs.append("code must match ^[A-Z0-9_-]{2,32}$ (uppercase)")
    mt = data.get("metal_type")
    if mt is not None and mt != "" and mt not in METAL_TYPES:
        errs.append(f"metal_type must be one of {list(METAL_TYPES)}")
    purity = data.get("purity_pct")
    if purity is not None and purity != "":
        try:
            p = int(purity)
        except (TypeError, ValueError):
            errs.append("purity_pct must be an integer (millage)")
        else:
            if isinstance(p, bool):                  # bool is int subclass
                errs.append("purity_pct must be an integer (millage)")
            elif p < 1 or p > 999:
                errs.append("purity_pct must be in 1..999")
            elif mt in _ALLOWED_PURITY and p not in _ALLOWED_PURITY[mt]:
                errs.append(
                    f"purity_pct {p} not allowed for {mt}; "
                    f"allowed: {sorted(_ALLOWED_PURITY[mt])}"
                )
    return errs


# ── Read ────────────────────────────────────────────────────────────────────

def _row_to_metal(r: sqlite3.Row) -> Metal:
    keys = r.keys() if hasattr(r, "keys") else []
    return Metal(
        code=r["code"], name=r["name"], metal_type=r["metal_type"],
        purity_pct=r["purity_pct"], purity_label=r["purity_label"],
        active=bool(r["active"]), notes=r["notes"],
        created_at=r["created_at"], updated_at=r["updated_at"],
        deleted_at=(r["deleted_at"] if "deleted_at" in keys else None),
    )


def get_metal(path: Path, code: str) -> Optional[Metal]:
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        r = cx.execute("SELECT * FROM metals WHERE code = ?", (code,)).fetchone()
    return _row_to_metal(r) if r else None


def list_metals(path: Path, *, active: Optional[bool] = None,
                metal_type: Optional[str] = None,
                limit: int = 500) -> List[Metal]:
    where: List[str] = []
    args:  List[Any] = []
    if active is not None:
        where.append("active = ?")
        args.append(1 if active else 0)
    if metal_type:
        where.append("metal_type = ?")
        args.append(metal_type)
    sql = "SELECT * FROM metals"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY code LIMIT ?"
    args.append(limit)
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        rows = cx.execute(sql, args).fetchall()
    return [_row_to_metal(r) for r in rows]


# ── Write ───────────────────────────────────────────────────────────────────

def upsert_metal(path: Path, data: Dict[str, Any]) -> Metal:
    errs = validate_metal(data)
    if errs:
        raise ValueError("; ".join(errs))
    code = data["code"].strip()
    now  = datetime.now(timezone.utc).isoformat()
    active = data.get("active", True)
    active = 1 if (active is True or str(active).lower() in ("true","1","yes")) else 0
    purity = data.get("purity_pct")
    if purity is not None and purity != "":
        purity = int(purity)
    else:
        purity = None
    with sqlite3.connect(path) as cx:
        cx.execute("BEGIN IMMEDIATE")
        cur = cx.execute("SELECT created_at FROM metals WHERE code = ?", (code,))
        existing = cur.fetchone()
        if existing:
            cx.execute(
                """UPDATE metals SET name=?, metal_type=?, purity_pct=?,
                       purity_label=?, active=?, notes=?, updated_at=?
                   WHERE code = ?""",
                (data.get("name"), data.get("metal_type"), purity,
                 data.get("purity_label"), active, data.get("notes"), now, code),
            )
        else:
            cx.execute(
                """INSERT INTO metals
                   (code, name, metal_type, purity_pct, purity_label,
                    active, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, data.get("name"), data.get("metal_type"), purity,
                 data.get("purity_label"), active, data.get("notes"), now, now),
            )
        cx.commit()
    rec = get_metal(path, code)
    assert rec is not None
    return rec


def delete_metal(path: Path, code: str) -> bool:
    """Phase 3 alias kept for backwards compatibility. Performs HARD delete.

    Phase 4A introduces ``soft_delete_metal`` / ``restore_metal``; the route
    layer chooses between them. This function remains the hard-delete primitive
    so the existing DB-layer tests retain their contract.
    """
    with sqlite3.connect(path) as cx:
        cur = cx.execute("DELETE FROM metals WHERE code = ?", (code,))
        cx.commit()
        return cur.rowcount > 0


# ── Phase 4A — soft-delete + restore ────────────────────────────────────────

def soft_delete_metal(path: Path, code: str) -> bool:
    """Set active=0 and deleted_at=utcnow. Returns True if a row was
    touched, False if the code does not exist. Already-inactive rows are
    refreshed with a new deleted_at — idempotent for retry safety."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            "UPDATE metals SET active = 0, deleted_at = ?, updated_at = ? "
            "WHERE code = ?",
            (now, now, code),
        )
        cx.commit()
        return cur.rowcount > 0


def restore_metal(path: Path, code: str) -> bool:
    """Set active=1 and clear deleted_at. Returns True if a row existed."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            "UPDATE metals SET active = 1, deleted_at = NULL, updated_at = ? "
            "WHERE code = ?",
            (now, code),
        )
        cx.commit()
        return cur.rowcount > 0


def hard_delete_metal(path: Path, code: str) -> bool:
    """Permanent removal. Alias for the legacy ``delete_metal`` primitive."""
    return delete_metal(path, code)
