"""
master_data_db.py — Shared local SQLite for B5 master-data entities:
  - hs_codes
  - units
  - product_local (local augmentation of wFirma products)

This module is additive and local-only. It does NOT write to wFirma, does NOT
participate in PZ/customs/landed-cost calculation, and does NOT modify any
existing schema. Each table is independent; tables only share a file for
operational convenience.

Storage: <storage_root>/master_data.sqlite
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Domain dataclasses ───────────────────────────────────────────────────────

@dataclass
class HsCode:
    hs_code:        str
    description_pl: Optional[str] = None
    description_en: Optional[str] = None
    duty_rate_pct:  Optional[str] = None   # Decimal-as-string for JSON
    vat_rate_pct:   Optional[str] = None
    active:         bool = True
    notes:          Optional[str] = None
    created_at:     Optional[str] = None
    updated_at:     Optional[str] = None


@dataclass
class Unit:
    code:        str
    name_pl:     Optional[str] = None
    name_en:     Optional[str] = None
    unit_type:   Optional[str] = None    # e.g. piece / weight / volume
    active:      bool = True
    created_at:  Optional[str] = None
    updated_at:  Optional[str] = None


@dataclass
class ProductLocal:
    product_code:     str
    hs_code_override: Optional[str] = None
    unit_override:    Optional[str] = None
    design_code_link: Optional[str] = None
    notes:            Optional[str] = None
    created_at:       Optional[str] = None
    updated_at:       Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

_HS_CODE_RE = re.compile(r"^[0-9]{4,12}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _to_decimal_str(v: Any) -> Optional[str]:
    """Coerce to Decimal-string; '' / None → None; invalid → ValueError."""
    if v is None or v == "":
        return None
    try:
        return str(Decimal(str(v)))
    except (InvalidOperation, ValueError):
        raise ValueError(f"cannot parse {v!r} as Decimal")


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create all three master-data tables. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hs_codes (
                hs_code        TEXT PRIMARY KEY,
                description_pl TEXT,
                description_en TEXT,
                duty_rate_pct  TEXT,
                vat_rate_pct   TEXT,
                active         INTEGER NOT NULL DEFAULT 1,
                notes          TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hs_active ON hs_codes (active)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS units (
                code       TEXT PRIMARY KEY,
                name_pl    TEXT,
                name_en    TEXT,
                unit_type  TEXT,
                active     INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_local (
                product_code      TEXT PRIMARY KEY,
                hs_code_override  TEXT,
                unit_override     TEXT,
                design_code_link  TEXT,
                notes             TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
        """)
        conn.commit()


# ── HS Codes ──────────────────────────────────────────────────────────────────

def validate_hs_code(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    code = _clean(data.get("hs_code"))
    if not code:
        errors.append("hs_code is required")
    elif not _HS_CODE_RE.match(code):
        errors.append(f"hs_code must be 4-12 digits, got {code!r}")
    for field in ("duty_rate_pct", "vat_rate_pct"):
        v = data.get(field)
        if v is not None and v != "":
            try:
                _to_decimal_str(v)
            except ValueError as e:
                errors.append(f"{field}: {e}")
    return errors


def _row_to_hs(row: sqlite3.Row) -> HsCode:
    return HsCode(
        hs_code=row["hs_code"], description_pl=row["description_pl"],
        description_en=row["description_en"], duty_rate_pct=row["duty_rate_pct"],
        vat_rate_pct=row["vat_rate_pct"], active=bool(int(row["active"])),
        notes=row["notes"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def upsert_hs_code(db_path: Path, data: Dict[str, Any]) -> HsCode:
    errs = validate_hs_code(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    payload = {
        "hs_code":        _clean(data.get("hs_code")),
        "description_pl": _clean(data.get("description_pl")),
        "description_en": _clean(data.get("description_en")),
        "duty_rate_pct":  _to_decimal_str(data.get("duty_rate_pct")),
        "vat_rate_pct":   _to_decimal_str(data.get("vat_rate_pct")),
        "active":         1 if data.get("active", True) else 0,
        "notes":          _clean(data.get("notes")),
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        existing = conn.execute("SELECT created_at FROM hs_codes WHERE hs_code=?",
                                (payload["hs_code"],)).fetchone()
        if existing:
            conn.execute("""
                UPDATE hs_codes SET description_pl=?, description_en=?, duty_rate_pct=?,
                  vat_rate_pct=?, active=?, notes=?, updated_at=? WHERE hs_code=?
            """, (payload["description_pl"], payload["description_en"],
                  payload["duty_rate_pct"], payload["vat_rate_pct"],
                  payload["active"], payload["notes"], now, payload["hs_code"]))
        else:
            conn.execute("""
                INSERT INTO hs_codes (hs_code, description_pl, description_en,
                  duty_rate_pct, vat_rate_pct, active, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (payload["hs_code"], payload["description_pl"], payload["description_en"],
                  payload["duty_rate_pct"], payload["vat_rate_pct"],
                  payload["active"], payload["notes"], now, now))
        conn.commit()
    return get_hs_code(db_path, payload["hs_code"])


def get_hs_code(db_path: Path, hs_code: str) -> Optional[HsCode]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM hs_codes WHERE hs_code=?", (hs_code,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_hs(row) if row else None


def list_hs_codes(db_path: Path, *, active: Optional[bool] = None,
                  limit: int = 500) -> List[HsCode]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if active is not None:
        where.append("active=?")
        params.append(1 if active else 0)
    sql = "SELECT * FROM hs_codes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY hs_code ASC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_hs(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def delete_hs_code(db_path: Path, hs_code: str) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM hs_codes WHERE hs_code=?", (hs_code,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── Units ─────────────────────────────────────────────────────────────────────

def validate_unit(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    code = _clean(data.get("code"))
    if not code:
        errors.append("code is required")
    elif len(code) > 16:
        errors.append("code must be ≤ 16 chars")
    return errors


def _row_to_unit(row: sqlite3.Row) -> Unit:
    return Unit(
        code=row["code"], name_pl=row["name_pl"], name_en=row["name_en"],
        unit_type=row["unit_type"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def upsert_unit(db_path: Path, data: Dict[str, Any]) -> Unit:
    errs = validate_unit(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    payload = {
        "code":      _clean(data.get("code")),
        "name_pl":   _clean(data.get("name_pl")),
        "name_en":   _clean(data.get("name_en")),
        "unit_type": _clean(data.get("unit_type")),
        "active":    1 if data.get("active", True) else 0,
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        existing = conn.execute("SELECT 1 FROM units WHERE code=?", (payload["code"],)).fetchone()
        if existing:
            conn.execute("""UPDATE units SET name_pl=?, name_en=?, unit_type=?, active=?,
                            updated_at=? WHERE code=?""",
                         (payload["name_pl"], payload["name_en"], payload["unit_type"],
                          payload["active"], now, payload["code"]))
        else:
            conn.execute("""INSERT INTO units (code, name_pl, name_en, unit_type, active,
                            created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (payload["code"], payload["name_pl"], payload["name_en"],
                          payload["unit_type"], payload["active"], now, now))
        conn.commit()
    return get_unit(db_path, payload["code"])


def get_unit(db_path: Path, code: str) -> Optional[Unit]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM units WHERE code=?", (code,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_unit(row) if row else None


def list_units(db_path: Path, *, active: Optional[bool] = None,
               limit: int = 200) -> List[Unit]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if active is not None:
        where.append("active=?")
        params.append(1 if active else 0)
    sql = "SELECT * FROM units"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY code ASC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_unit(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def delete_unit(db_path: Path, code: str) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM units WHERE code=?", (code,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── Product Local ────────────────────────────────────────────────────────────

def validate_product_local(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    pc = _clean(data.get("product_code"))
    if not pc:
        errors.append("product_code is required")
    return errors


def _row_to_pl(row: sqlite3.Row) -> ProductLocal:
    return ProductLocal(
        product_code=row["product_code"], hs_code_override=row["hs_code_override"],
        unit_override=row["unit_override"], design_code_link=row["design_code_link"],
        notes=row["notes"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def upsert_product_local(db_path: Path, data: Dict[str, Any]) -> ProductLocal:
    errs = validate_product_local(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    payload = {
        "product_code":     _clean(data.get("product_code")),
        "hs_code_override": _clean(data.get("hs_code_override")),
        "unit_override":    _clean(data.get("unit_override")),
        "design_code_link": _clean(data.get("design_code_link")),
        "notes":            _clean(data.get("notes")),
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        existing = conn.execute("SELECT 1 FROM product_local WHERE product_code=?",
                                (payload["product_code"],)).fetchone()
        if existing:
            conn.execute("""UPDATE product_local SET hs_code_override=?, unit_override=?,
                            design_code_link=?, notes=?, updated_at=? WHERE product_code=?""",
                         (payload["hs_code_override"], payload["unit_override"],
                          payload["design_code_link"], payload["notes"], now,
                          payload["product_code"]))
        else:
            conn.execute("""INSERT INTO product_local (product_code, hs_code_override,
                            unit_override, design_code_link, notes, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (payload["product_code"], payload["hs_code_override"],
                          payload["unit_override"], payload["design_code_link"],
                          payload["notes"], now, now))
        conn.commit()
    return get_product_local(db_path, payload["product_code"])


def get_product_local(db_path: Path, product_code: str) -> Optional[ProductLocal]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM product_local WHERE product_code=?",
                               (product_code,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_pl(row) if row else None


def list_product_local(db_path: Path, *, limit: int = 500) -> List[ProductLocal]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM product_local ORDER BY updated_at DESC, product_code ASC LIMIT ?",
                (int(limit),)
            ).fetchall()
            return [_row_to_pl(r) for r in rows]
        except sqlite3.OperationalError:
            return []


def delete_product_local(db_path: Path, product_code: str) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM product_local WHERE product_code=?", (product_code,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False
