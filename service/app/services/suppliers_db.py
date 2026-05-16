"""
suppliers_db.py — Master Data: Suppliers registry.

Goods exporters and consignment senders. Maps supplier names on invoices to
canonical records used during SAD/ZC429 verification.

This module is additive and local-only. It DOES NOT write to wFirma, does
NOT participate in PZ/customs/landed-cost calculation, and does NOT modify
any existing schema.

Storage: <storage_root>/suppliers.sqlite
Table:   suppliers (single)
Key:     supplier_code (UNIQUE)
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Domain ────────────────────────────────────────────────────────────────────

_ISO_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")
_EMAIL_RE      = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Supplier:
    supplier_code: str
    name:          str
    country:       str                       # ISO alpha-2, normalised to upper
    vat_id:        Optional[str] = None
    eori:          Optional[str] = None
    address:       Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    active:        bool          = True
    notes:         Optional[str] = None
    id:            Optional[int] = None
    created_at:    Optional[str] = None
    updated_at:    Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_supplier(row: sqlite3.Row) -> Supplier:
    return Supplier(
        id            = row["id"],
        supplier_code = row["supplier_code"],
        name          = row["name"],
        country       = row["country"],
        vat_id        = row["vat_id"],
        eori          = row["eori"],
        address       = row["address"],
        contact_email = row["contact_email"],
        contact_phone = row["contact_phone"],
        active        = bool(int(row["active"])),
        notes         = row["notes"],
        created_at    = row["created_at"],
        updated_at    = row["updated_at"],
    )


def _clean(v: Any) -> Optional[str]:
    """Normalise input: '' or whitespace-only → None; trim others."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# ── Validation ────────────────────────────────────────────────────────────────

def validate_supplier(data: Dict[str, Any]) -> List[str]:
    """Return list of error strings; empty list = OK."""
    errors: List[str] = []

    code = _clean(data.get("supplier_code"))
    if not code:
        errors.append("supplier_code is required")
    elif len(code) > 64:
        errors.append("supplier_code must be ≤ 64 characters")

    name = _clean(data.get("name"))
    if not name:
        errors.append("name is required")

    country = _clean(data.get("country"))
    if not country:
        errors.append("country is required")
    elif not _ISO_ALPHA2_RE.match(country.upper()):
        errors.append(f"country must be ISO alpha-2, got {country!r}")

    email = _clean(data.get("contact_email"))
    if email is not None and not _EMAIL_RE.match(email):
        errors.append(f"contact_email is malformed: {email!r}")

    return errors


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create suppliers table if it does not exist. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_code   TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL,
                country         TEXT NOT NULL,
                vat_id          TEXT,
                eori            TEXT,
                address         TEXT,
                contact_email   TEXT,
                contact_phone   TEXT,
                active          INTEGER NOT NULL DEFAULT 1,
                notes           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_country ON suppliers (country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_active  ON suppliers (active)")
        conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_supplier(db_path: Path, data: Dict[str, Any]) -> int:
    """Create a new supplier. Raises ValueError on validation or DUPLICATE_CODE."""
    errs = validate_supplier(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    now = _now()
    payload = {
        "supplier_code": _clean(data.get("supplier_code")),
        "name":          _clean(data.get("name")),
        "country":       _clean(data.get("country")).upper(),
        "vat_id":        _clean(data.get("vat_id")),
        "eori":          _clean(data.get("eori")),
        "address":       _clean(data.get("address")),
        "contact_email": _clean(data.get("contact_email")),
        "contact_phone": _clean(data.get("contact_phone")),
        "active":        1 if data.get("active", True) else 0,
        "notes":         _clean(data.get("notes")),
    }
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("""
                INSERT INTO suppliers
                    (supplier_code, name, country, vat_id, eori, address,
                     contact_email, contact_phone, active, notes,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (payload["supplier_code"], payload["name"], payload["country"],
                  payload["vat_id"], payload["eori"], payload["address"],
                  payload["contact_email"], payload["contact_phone"],
                  payload["active"], payload["notes"], now, now))
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ValueError(f"DUPLICATE_CODE: supplier_code={payload['supplier_code']!r} already exists")
            raise


def get_supplier(db_path: Path, supplier_id: int) -> Optional[Supplier]:
    """Return supplier by primary key id, or None if missing / table absent."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM suppliers WHERE id = ?", (supplier_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_supplier(row) if row else None


def get_supplier_by_code(db_path: Path, supplier_code: str) -> Optional[Supplier]:
    """Return supplier by unique supplier_code."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM suppliers WHERE supplier_code = ?", (supplier_code,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_supplier(row) if row else None


def list_suppliers(
    db_path: Path,
    *,
    active:  Optional[bool] = None,
    country: Optional[str] = None,
    limit:   int = 200,
) -> List[Supplier]:
    """List suppliers ordered by most recently updated."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where: List[str] = []
    params: List[Any] = []
    if active is not None:
        where.append("active = ?")
        params.append(1 if active else 0)
    if country:
        where.append("country = ?")
        params.append(country.strip().upper())
    sql = "SELECT * FROM suppliers"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_row_to_supplier(r) for r in rows]


def update_supplier(db_path: Path, supplier_id: int, data: Dict[str, Any]) -> Optional[Supplier]:
    """Update supplier. Returns updated row, or None if no row affected.

    Validates the full payload as if creating (since callers send the entire form).
    Preserves supplier_code if not present in payload (silent no-op on code field).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    existing = get_supplier(db_path, supplier_id)
    if existing is None:
        return None
    # Merge over existing so partial PUTs don't unset other fields
    merged = {
        "supplier_code": data.get("supplier_code", existing.supplier_code),
        "name":          data.get("name",          existing.name),
        "country":       data.get("country",       existing.country),
        "vat_id":        data.get("vat_id",        existing.vat_id),
        "eori":          data.get("eori",          existing.eori),
        "address":       data.get("address",       existing.address),
        "contact_email": data.get("contact_email", existing.contact_email),
        "contact_phone": data.get("contact_phone", existing.contact_phone),
        "active":        data.get("active",        existing.active),
        "notes":         data.get("notes",         existing.notes),
    }
    errs = validate_supplier(merged)
    if errs:
        raise ValueError("; ".join(errs))
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        try:
            conn.execute("""
                UPDATE suppliers SET
                    supplier_code = ?, name = ?, country = ?, vat_id = ?,
                    eori = ?, address = ?, contact_email = ?, contact_phone = ?,
                    active = ?, notes = ?, updated_at = ?
                WHERE id = ?
            """, (_clean(merged["supplier_code"]), _clean(merged["name"]),
                  _clean(merged["country"]).upper(),
                  _clean(merged["vat_id"]), _clean(merged["eori"]),
                  _clean(merged["address"]), _clean(merged["contact_email"]),
                  _clean(merged["contact_phone"]),
                  1 if merged["active"] else 0, _clean(merged["notes"]),
                  now, supplier_id))
            conn.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ValueError(f"DUPLICATE_CODE: supplier_code={merged['supplier_code']!r} already exists")
            raise
    return get_supplier(db_path, supplier_id)


def delete_supplier(db_path: Path, supplier_id: int) -> bool:
    """Hard delete. Returns True if a row was removed."""
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False
