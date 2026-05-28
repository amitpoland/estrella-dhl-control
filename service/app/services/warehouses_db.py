"""warehouses_db.py — Local stock-location authority (Phase 3).

Storage: <storage_root>/warehouses.sqlite

Authority: LOCAL stock-location authority. Inventory logic reads this as
reference; this module does NOT mutate inventory state.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


CATEGORIES = ("own", "supplier", "customer_consignment", "transit", "customs_hold")

_CODE_RE    = re.compile(r"^[A-Z0-9_-]{2,32}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


@dataclass
class Warehouse:
    code:         str
    name:         Optional[str] = None
    category:     Optional[str] = None
    country_code: Optional[str] = None
    city:         Optional[str] = None
    address_line: Optional[str] = None
    active:       bool          = True
    notes:        Optional[str] = None
    created_at:   Optional[str] = None
    updated_at:   Optional[str] = None
    deleted_at:   Optional[str] = None      # Phase 4A — soft-delete timestamp


def warehouse_to_dict(w: Warehouse) -> Dict[str, Any]:
    return asdict(w)


# ── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS warehouses (
    code         TEXT PRIMARY KEY,
    name         TEXT,
    category     TEXT,
    country_code TEXT,
    city         TEXT,
    address_line TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    notes        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    deleted_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_warehouses_category ON warehouses (category);
CREATE INDEX IF NOT EXISTS ix_warehouses_country  ON warehouses (country_code);
CREATE INDEX IF NOT EXISTS ix_warehouses_active   ON warehouses (active);
"""


def _migrate_add_deleted_at(cx: sqlite3.Connection) -> None:
    try:
        cx.execute("ALTER TABLE warehouses ADD COLUMN deleted_at TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as cx:
        cx.executescript(_SCHEMA)
        _migrate_add_deleted_at(cx)


# ── Validation ──────────────────────────────────────────────────────────────

def validate_warehouse(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    code = (data.get("code") or "").strip()
    if not code:
        errs.append("code is required")
    elif not _CODE_RE.match(code):
        errs.append("code must match ^[A-Z0-9_-]{2,32}$ (uppercase)")
    cat = data.get("category")
    if cat is not None and cat != "" and cat not in CATEGORIES:
        errs.append(f"category must be one of {list(CATEGORIES)}")
    cc = data.get("country_code")
    if cc is not None and cc != "":
        if not _COUNTRY_RE.match(str(cc)):
            errs.append("country_code must be ISO-2 uppercase (^[A-Z]{2}$)")
    return errs


# ── Read ────────────────────────────────────────────────────────────────────

def _row_to_warehouse(r: sqlite3.Row) -> Warehouse:
    keys = r.keys() if hasattr(r, "keys") else []
    return Warehouse(
        code=r["code"], name=r["name"], category=r["category"],
        country_code=r["country_code"], city=r["city"],
        address_line=r["address_line"], active=bool(r["active"]),
        notes=r["notes"], created_at=r["created_at"],
        updated_at=r["updated_at"],
        deleted_at=(r["deleted_at"] if "deleted_at" in keys else None),
    )


def get_warehouse(path: Path, code: str) -> Optional[Warehouse]:
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        r = cx.execute("SELECT * FROM warehouses WHERE code = ?", (code,)).fetchone()
    return _row_to_warehouse(r) if r else None


def list_warehouses(path: Path, *, active: Optional[bool] = None,
                    category: Optional[str] = None,
                    limit: int = 500) -> List[Warehouse]:
    where: List[str] = []
    args:  List[Any] = []
    if active is not None:
        where.append("active = ?")
        args.append(1 if active else 0)
    if category:
        where.append("category = ?")
        args.append(category)
    sql = "SELECT * FROM warehouses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY code LIMIT ?"
    args.append(limit)
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        rows = cx.execute(sql, args).fetchall()
    return [_row_to_warehouse(r) for r in rows]


# ── Write ───────────────────────────────────────────────────────────────────

def upsert_warehouse(path: Path, data: Dict[str, Any]) -> Warehouse:
    errs = validate_warehouse(data)
    if errs:
        raise ValueError("; ".join(errs))
    code = data["code"].strip()
    now  = datetime.now(timezone.utc).isoformat()
    active = data.get("active", True)
    active = 1 if (active is True or str(active).lower() in ("true","1","yes")) else 0
    with sqlite3.connect(path) as cx:
        cx.execute("BEGIN IMMEDIATE")
        cur = cx.execute("SELECT created_at FROM warehouses WHERE code = ?", (code,))
        existing = cur.fetchone()
        if existing:
            cx.execute(
                """UPDATE warehouses SET name=?, category=?, country_code=?,
                       city=?, address_line=?, active=?, notes=?, updated_at=?
                   WHERE code = ?""",
                (data.get("name"), data.get("category"), data.get("country_code"),
                 data.get("city"), data.get("address_line"), active,
                 data.get("notes"), now, code),
            )
        else:
            cx.execute(
                """INSERT INTO warehouses
                   (code, name, category, country_code, city, address_line,
                    active, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, data.get("name"), data.get("category"),
                 data.get("country_code"), data.get("city"),
                 data.get("address_line"), active, data.get("notes"), now, now),
            )
        cx.commit()
    rec = get_warehouse(path, code)
    assert rec is not None
    return rec


def delete_warehouse(path: Path, code: str) -> bool:
    """Phase 3 alias kept for backwards compatibility. HARD delete."""
    with sqlite3.connect(path) as cx:
        cur = cx.execute("DELETE FROM warehouses WHERE code = ?", (code,))
        cx.commit()
        return cur.rowcount > 0


# ── Phase 4A — soft-delete + restore ────────────────────────────────────────

def soft_delete_warehouse(path: Path, code: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            "UPDATE warehouses SET active = 0, deleted_at = ?, updated_at = ? "
            "WHERE code = ?",
            (now, now, code),
        )
        cx.commit()
        return cur.rowcount > 0


def restore_warehouse(path: Path, code: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            "UPDATE warehouses SET active = 1, deleted_at = NULL, updated_at = ? "
            "WHERE code = ?",
            (now, code),
        )
        cx.commit()
        return cur.rowcount > 0


def hard_delete_warehouse(path: Path, code: str) -> bool:
    return delete_warehouse(path, code)
