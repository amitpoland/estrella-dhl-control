"""
proforma_service_charges_db.py — Operator-entered freight & insurance.

Why
---
Customer Proformas may include freight and insurance the customer is paying
for. These charges must NOT be silently derived from the import-side cost
allocation (CIF freight, customs insurance) — that mixes supplier-cost
context with customer-billing context. Instead, the operator enters them
explicitly per (batch_id, client_name).

Schema is one row per (batch_id, client_name, charge_type). UPSERT
semantics so the operator can update an amount; DELETE removes it.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ALLOWED_CHARGE_TYPES = frozenset({"freight", "insurance"})

_db_path: Optional[Path] = None
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(db_path: Path) -> None:
    """Idempotent init. Reuses the proforma_links.db file."""
    global _db_path
    _db_path = Path(db_path)
    with sqlite3.connect(str(_db_path)) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS proforma_service_charges (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id     TEXT NOT NULL,
                client_name  TEXT NOT NULL,
                charge_type  TEXT NOT NULL,
                amount       REAL NOT NULL DEFAULT 0,
                currency     TEXT NOT NULL DEFAULT '',
                note         TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                created_by   TEXT NOT NULL DEFAULT '',
                updated_at   TEXT NOT NULL,
                UNIQUE(batch_id, client_name, charge_type)
            );
            CREATE INDEX IF NOT EXISTS idx_psc_batch_client
                ON proforma_service_charges (batch_id, client_name);
        """)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("proforma_service_charges_db not initialised")
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def list_charges(batch_id: str, client_name: str) -> List[Dict[str, Any]]:
    """All current charges for (batch, client). Empty list if none."""
    if _db_path is None:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM proforma_service_charges
               WHERE batch_id=? AND client_name=?
               ORDER BY charge_type""",
            (batch_id, client_name),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_charge(
    *,
    batch_id:    str,
    client_name: str,
    charge_type: str,
    amount:      float,
    currency:    str,
    note:        str = "",
    created_by:  str = "",
) -> Dict[str, Any]:
    """Insert or update one charge. Returns the persisted row."""
    if charge_type not in ALLOWED_CHARGE_TYPES:
        raise ValueError(
            f"charge_type {charge_type!r} not in {sorted(ALLOWED_CHARGE_TYPES)}"
        )
    if amount is None or float(amount) < 0:
        raise ValueError("amount must be a non-negative number")
    cur = (currency or "").strip().upper()
    if not cur:
        raise ValueError("currency is required (3-letter ISO)")
    now = _now()
    with _lock, _connect() as con:
        con.execute(
            """INSERT INTO proforma_service_charges
               (batch_id, client_name, charge_type, amount, currency,
                note, created_at, created_by, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(batch_id, client_name, charge_type)
               DO UPDATE SET
                 amount=excluded.amount,
                 currency=excluded.currency,
                 note=excluded.note,
                 updated_at=excluded.updated_at""",
            (batch_id, client_name, charge_type, float(amount), cur,
             note or "", now, created_by or "", now),
        )
        row = con.execute(
            """SELECT * FROM proforma_service_charges
               WHERE batch_id=? AND client_name=? AND charge_type=?""",
            (batch_id, client_name, charge_type),
        ).fetchone()
    return dict(row) if row else {}


def delete_charge(batch_id: str, client_name: str,
                  charge_type: str) -> bool:
    """Remove one charge. Returns True if a row was deleted."""
    if _db_path is None:
        return False
    with _lock, _connect() as con:
        cur = con.execute(
            """DELETE FROM proforma_service_charges
               WHERE batch_id=? AND client_name=? AND charge_type=?""",
            (batch_id, client_name, charge_type),
        )
        return cur.rowcount > 0


def move_charges_client_name(
    batch_id: str, old_client_name: str, new_client_name: str,
) -> List[Dict[str, Any]]:
    """PR-3 rename mode: move every charge from old_client_name → new_client_name.

    Used when the draft is being RENAMED in place (no canonical-named draft
    pre-existed) — the charges belong to the same draft and must travel with it.
    On a charge_type collision (the target already has that type — defensive,
    shouldn't happen in pure-rename), the TARGET (canonical) value is kept and
    the old row is dropped. Returns the list of DROPPED non-zero charges for
    operator disclosure (empty in the normal rename path).
    """
    if _db_path is None or not batch_id or not old_client_name:
        return []
    if old_client_name == new_client_name:
        return []
    now = _now()
    dropped: List[Dict[str, Any]] = []
    with _lock, _connect() as con:
        target_types = {r["charge_type"] for r in con.execute(
            "SELECT charge_type FROM proforma_service_charges "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, new_client_name),
        ).fetchall()}
        old_rows = con.execute(
            "SELECT charge_type, amount, currency, note FROM proforma_service_charges "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, old_client_name),
        ).fetchall()
        for r in old_rows:
            ct = r["charge_type"]
            if ct in target_types:
                # canonical already holds this type → canonical wins; drop old.
                if float(r["amount"] or 0) > 0:
                    dropped.append({
                        "charge_type": ct, "amount": float(r["amount"]),
                        "currency": r["currency"], "note": r["note"],
                        "old_client_name": old_client_name,
                        "reason": "canonical_already_has_charge_type",
                    })
            else:
                con.execute(
                    "UPDATE proforma_service_charges "
                    "SET client_name=?, updated_at=? "
                    "WHERE batch_id=? AND client_name=? AND charge_type=?",
                    (new_client_name, now, batch_id, old_client_name, ct),
                )
        # Remove any old rows not moved (the collision ones).
        con.execute(
            "DELETE FROM proforma_service_charges "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, old_client_name),
        )
    return dropped


def drop_charges_client_name(
    batch_id: str, old_client_name: str,
) -> List[Dict[str, Any]]:
    """PR-3 canonical-wins (collision) mode: delete every charge under
    old_client_name because a canonical-named draft already owns the authority.

    Returns the list of DROPPED non-zero charges for operator disclosure — the
    discard is never silent (operator chose 'canonical always wins').
    """
    if _db_path is None or not batch_id or not old_client_name:
        return []
    dropped: List[Dict[str, Any]] = []
    with _lock, _connect() as con:
        rows = con.execute(
            "SELECT charge_type, amount, currency, note FROM proforma_service_charges "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, old_client_name),
        ).fetchall()
        for r in rows:
            if float(r["amount"] or 0) > 0:
                dropped.append({
                    "charge_type": r["charge_type"], "amount": float(r["amount"]),
                    "currency": r["currency"], "note": r["note"],
                    "old_client_name": old_client_name,
                    "reason": "canonical_wins_collision",
                })
        con.execute(
            "DELETE FROM proforma_service_charges WHERE batch_id=? AND client_name=?",
            (batch_id, old_client_name),
        )
    return dropped


def replace_all(
    *,
    batch_id:    str,
    client_name: str,
    charges:     List[Dict[str, Any]],
    created_by:  str = "",
) -> List[Dict[str, Any]]:
    """Replace all charges for (batch, client) with *charges*. Idempotent."""
    seen: set = set()
    for c in charges or []:
        ct = (c.get("charge_type") or "").strip().lower()
        if ct in seen:
            raise ValueError(f"duplicate charge_type {ct!r} in input")
        seen.add(ct)
        upsert_charge(
            batch_id=batch_id, client_name=client_name,
            charge_type=ct, amount=float(c.get("amount") or 0),
            currency=str(c.get("currency") or ""),
            note=str(c.get("note") or ""),
            created_by=created_by,
        )
    # Remove any charge_type not in the new set.
    if _db_path is not None:
        with _lock, _connect() as con:
            current = [r["charge_type"] for r in con.execute(
                """SELECT charge_type FROM proforma_service_charges
                   WHERE batch_id=? AND client_name=?""",
                (batch_id, client_name),
            ).fetchall()]
            for ct in current:
                if ct not in seen:
                    con.execute(
                        """DELETE FROM proforma_service_charges
                           WHERE batch_id=? AND client_name=? AND charge_type=?""",
                        (batch_id, client_name, ct),
                    )
    return list_charges(batch_id, client_name)
