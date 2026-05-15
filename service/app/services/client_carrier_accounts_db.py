"""
client_carrier_accounts_db.py — Carrier account sub-resource for customer master.

Table:  client_carrier_accounts  (stored in customer_master.sqlite)
Key:    contractor_id → bill_to_contractor_id in customer_master table

One contractor can have many carrier accounts across carriers.
Unique constraint: (contractor_id, carrier, account_number).
Exactly one per contractor may have is_default=1 (enforced at write time).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_CARRIERS      = frozenset({"dhl", "fedex", "ups", "other"})
VALID_PAYMENT_TYPES = frozenset({"shipper", "receiver", "third_party"})


@dataclass
class CarrierAccount:
    contractor_id:  str
    carrier:        str          # dhl | fedex | ups | other
    account_number: str
    account_name:   Optional[str] = None
    payment_type:   Optional[str] = None   # shipper | receiver | third_party
    service_level:  Optional[str] = None
    is_default:     bool = False
    id:             Optional[int] = None
    created_at:     Optional[str] = None
    updated_at:     Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_acct(row: sqlite3.Row) -> CarrierAccount:
    return CarrierAccount(
        id             = row["id"],
        contractor_id  = row["contractor_id"],
        carrier        = row["carrier"],
        account_number = row["account_number"],
        account_name   = row["account_name"],
        payment_type   = row["payment_type"],
        service_level  = row["service_level"],
        is_default     = bool(int(row["is_default"])),
        created_at     = row["created_at"],
        updated_at     = row["updated_at"],
    )


def validate_account(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    carrier = (data.get("carrier") or "").strip().lower()
    if not carrier:
        errors.append("carrier is required")
    elif carrier not in VALID_CARRIERS:
        errors.append(f"carrier must be one of {sorted(VALID_CARRIERS)}, got {carrier!r}")
    acct_no = (data.get("account_number") or "").strip()
    if not acct_no:
        errors.append("account_number is required")
    payment_type = data.get("payment_type")
    if payment_type is not None and payment_type != "":
        if payment_type not in VALID_PAYMENT_TYPES:
            errors.append(
                f"payment_type must be one of {sorted(VALID_PAYMENT_TYPES)}, got {payment_type!r}"
            )
    return errors


def init_db(db_path: Path) -> None:
    """Create client_carrier_accounts table if it does not exist. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_carrier_accounts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                contractor_id  TEXT NOT NULL,
                carrier        TEXT NOT NULL,
                account_number TEXT NOT NULL,
                account_name   TEXT,
                payment_type   TEXT,
                service_level  TEXT,
                is_default     INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_cca_contractor
            ON client_carrier_accounts (contractor_id)
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_cca_unique
            ON client_carrier_accounts (contractor_id, carrier, account_number)
        """)


def create_account(db_path: Path, contractor_id: str, data: Dict[str, Any]) -> int:
    """Insert a new carrier account. Returns new row id.
    Raises ValueError('DUPLICATE_ACCOUNT') on unique constraint violation."""
    init_db(db_path)
    now = _now()
    carrier = (data.get("carrier") or "").strip().lower()
    acct_no = (data.get("account_number") or "").strip()
    is_default = bool(data.get("is_default", False))
    try:
        with sqlite3.connect(str(db_path)) as conn:
            if is_default:
                conn.execute(
                    "UPDATE client_carrier_accounts SET is_default=0 WHERE contractor_id=?",
                    (contractor_id,),
                )
            cur = conn.execute(
                """INSERT INTO client_carrier_accounts
                   (contractor_id, carrier, account_number, account_name,
                    payment_type, service_level, is_default, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    contractor_id, carrier, acct_no,
                    data.get("account_name") or None,
                    data.get("payment_type") or None,
                    data.get("service_level") or None,
                    1 if is_default else 0,
                    now, now,
                ),
            )
            return int(cur.lastrowid or 0)
    except sqlite3.IntegrityError:
        raise ValueError("DUPLICATE_ACCOUNT")


def list_accounts(db_path: Path, contractor_id: str) -> List[CarrierAccount]:
    """Return all accounts for a contractor, default first then by id."""
    if not Path(db_path).is_file():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM client_carrier_accounts
               WHERE contractor_id=?
               ORDER BY is_default DESC, id ASC""",
            (contractor_id,),
        ).fetchall()
    return [_row_to_acct(r) for r in rows]


def get_account(db_path: Path, acct_id: int, contractor_id: str) -> Optional[CarrierAccount]:
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM client_carrier_accounts WHERE id=? AND contractor_id=?",
            (acct_id, contractor_id),
        ).fetchone()
    return _row_to_acct(row) if row else None


def update_account(db_path: Path, acct_id: int, contractor_id: str,
                   data: Dict[str, Any]) -> Optional[CarrierAccount]:
    """Update fields. Returns updated record or None if not found.
    Raises ValueError('DUPLICATE_ACCOUNT') on unique constraint violation."""
    if not Path(db_path).is_file():
        return None
    now = _now()
    carrier = (data.get("carrier") or "").strip().lower()
    acct_no = (data.get("account_number") or "").strip()
    is_default = bool(data.get("is_default", False))
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT id FROM client_carrier_accounts WHERE id=? AND contractor_id=?",
                (acct_id, contractor_id),
            ).fetchone()
            if existing is None:
                return None
            if is_default:
                conn.execute(
                    "UPDATE client_carrier_accounts SET is_default=0 WHERE contractor_id=?",
                    (contractor_id,),
                )
            conn.execute(
                """UPDATE client_carrier_accounts
                   SET carrier=?, account_number=?, account_name=?,
                       payment_type=?, service_level=?, is_default=?, updated_at=?
                   WHERE id=? AND contractor_id=?""",
                (
                    carrier, acct_no,
                    data.get("account_name") or None,
                    data.get("payment_type") or None,
                    data.get("service_level") or None,
                    1 if is_default else 0,
                    now,
                    acct_id, contractor_id,
                ),
            )
    except sqlite3.IntegrityError:
        raise ValueError("DUPLICATE_ACCOUNT")
    return get_account(db_path, acct_id, contractor_id)


def delete_account(db_path: Path, acct_id: int, contractor_id: str) -> bool:
    """Hard delete. Returns True if a row was removed."""
    if not Path(db_path).is_file():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            "DELETE FROM client_carrier_accounts WHERE id=? AND contractor_id=?",
            (acct_id, contractor_id),
        )
        return cur.rowcount > 0


__all__ = [
    "CarrierAccount", "validate_account", "init_db",
    "create_account", "list_accounts", "get_account",
    "update_account", "delete_account",
    "VALID_CARRIERS", "VALID_PAYMENT_TYPES",
]
