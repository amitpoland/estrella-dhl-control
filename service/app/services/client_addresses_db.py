"""
client_addresses_db.py — Shipping address sub-resource for customer master.

Table:  client_shipping_addresses  (stored in customer_master.sqlite)
Key:    contractor_id → bill_to_contractor_id in customer_master table

One contractor can have many shipping addresses.
Exactly one per contractor may have is_default=1 (enforced at write time).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ShippingAddress:
    contractor_id: str
    label:         str
    name:          Optional[str] = None
    person:        Optional[str] = None
    street:        Optional[str] = None
    city:          Optional[str] = None
    zip:           Optional[str] = None
    country:       Optional[str] = None   # ISO-3166 alpha-2
    phone:         Optional[str] = None
    email:         Optional[str] = None
    is_default:    bool = False
    id:            Optional[int] = None
    created_at:    Optional[str] = None
    updated_at:    Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_addr(row: sqlite3.Row) -> ShippingAddress:
    return ShippingAddress(
        id            = row["id"],
        contractor_id = row["contractor_id"],
        label         = row["label"],
        name          = row["name"],
        person        = row["person"],
        street        = row["street"],
        city          = row["city"],
        zip           = row["zip"],
        country       = row["country"],
        phone         = row["phone"],
        email         = row["email"],
        is_default    = bool(int(row["is_default"])),
        created_at    = row["created_at"],
        updated_at    = row["updated_at"],
    )


def validate_address(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = (data.get("label") or "").strip()
    if not label:
        errors.append("label is required")
    country = data.get("country")
    if country is not None and country != "":
        if not re.fullmatch(r"[A-Z]{2}", country):
            errors.append("country must be ISO-3166 alpha-2 (two uppercase letters), e.g. 'DE'")
    return errors


def init_db(db_path: Path) -> None:
    """Create client_shipping_addresses table if it does not exist. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_shipping_addresses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                contractor_id TEXT NOT NULL,
                label         TEXT NOT NULL,
                name          TEXT,
                person        TEXT,
                street        TEXT,
                city          TEXT,
                zip           TEXT,
                country       TEXT,
                phone         TEXT,
                email         TEXT,
                is_default    INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_csa_contractor
            ON client_shipping_addresses (contractor_id)
        """)


def create_address(db_path: Path, contractor_id: str, data: Dict[str, Any]) -> int:
    """Insert a new address. Returns new row id."""
    init_db(db_path)
    now = _now()
    country = (data.get("country") or "").upper() or None
    is_default = bool(data.get("is_default", False))
    with sqlite3.connect(str(db_path)) as conn:
        if is_default:
            conn.execute(
                "UPDATE client_shipping_addresses SET is_default=0 WHERE contractor_id=?",
                (contractor_id,),
            )
        cur = conn.execute(
            """INSERT INTO client_shipping_addresses
               (contractor_id, label, name, person, street, city, zip, country,
                phone, email, is_default, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                contractor_id,
                (data.get("label") or "").strip(),
                data.get("name") or None,
                data.get("person") or None,
                data.get("street") or None,
                data.get("city") or None,
                data.get("zip") or None,
                country,
                data.get("phone") or None,
                data.get("email") or None,
                1 if is_default else 0,
                now, now,
            ),
        )
        return int(cur.lastrowid or 0)


def list_addresses(db_path: Path, contractor_id: str) -> List[ShippingAddress]:
    """Return all addresses for a contractor, default first then by id."""
    if not Path(db_path).is_file():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM client_shipping_addresses
               WHERE contractor_id=?
               ORDER BY is_default DESC, id ASC""",
            (contractor_id,),
        ).fetchall()
    return [_row_to_addr(r) for r in rows]


def get_address(db_path: Path, addr_id: int, contractor_id: str) -> Optional[ShippingAddress]:
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM client_shipping_addresses WHERE id=? AND contractor_id=?",
            (addr_id, contractor_id),
        ).fetchone()
    return _row_to_addr(row) if row else None


def update_address(db_path: Path, addr_id: int, contractor_id: str,
                   data: Dict[str, Any]) -> Optional[ShippingAddress]:
    """Update fields of an existing address. Returns updated record or None if not found."""
    if not Path(db_path).is_file():
        return None
    now = _now()
    country = (data.get("country") or "").upper() or None
    is_default = bool(data.get("is_default", False))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM client_shipping_addresses WHERE id=? AND contractor_id=?",
            (addr_id, contractor_id),
        ).fetchone()
        if existing is None:
            return None
        if is_default:
            conn.execute(
                "UPDATE client_shipping_addresses SET is_default=0 WHERE contractor_id=?",
                (contractor_id,),
            )
        conn.execute(
            """UPDATE client_shipping_addresses
               SET label=?, name=?, person=?, street=?, city=?, zip=?, country=?,
                   phone=?, email=?, is_default=?, updated_at=?
               WHERE id=? AND contractor_id=?""",
            (
                (data.get("label") or "").strip(),
                data.get("name") or None,
                data.get("person") or None,
                data.get("street") or None,
                data.get("city") or None,
                data.get("zip") or None,
                country,
                data.get("phone") or None,
                data.get("email") or None,
                1 if is_default else 0,
                now,
                addr_id, contractor_id,
            ),
        )
    return get_address(db_path, addr_id, contractor_id)


def delete_address(db_path: Path, addr_id: int, contractor_id: str) -> bool:
    """Hard delete. Returns True if a row was removed."""
    if not Path(db_path).is_file():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            "DELETE FROM client_shipping_addresses WHERE id=? AND contractor_id=?",
            (addr_id, contractor_id),
        )
        return cur.rowcount > 0


__all__ = [
    "ShippingAddress", "validate_address", "init_db",
    "create_address", "list_addresses", "get_address",
    "update_address", "delete_address",
]
