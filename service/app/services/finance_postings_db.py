"""
finance_postings_db.py — Phase 6F.1 — Explicit payment-charge posting registry.

> **STATUS: SCHEMA + DB MODULE ONLY. No posting engine integration. No UI.**
>
> This is Batch 6F.1 of the Phase 6F implementation campaign. It introduces
> the additive SQLite schema and pure-CRUD module proposed in
> `tasks/phase-6f-architecture.md`. It does NOT wire any behaviour into:
>   - wFirma posting paths
>   - proforma issuance
>   - PZ landed-cost calculation
>   - settlement close
>   - FX delta computation
>   - dashboard UI
>
> Five tables, schema version 1:
>   1. charges               — typed components of an amount due
>   2. postings              — snapshots of charges issued to wFirma
>   3. payments              — inbound cash events
>   4. payment_allocations   — payment ↔ charge attribution
>   5. settlements           — postings reaching fully-paid status
>
> Plus a schema_version table for forward-compatibility.
>
> Storage: ``<storage_root>/finance_postings.sqlite`` (NEW FILE; nothing else
> reads it). Idempotent ``init_db``. Pure CRUD/helper functions only.

CHARGE_TYPES allow-list (architecture §5.1):
    net_goods, freight, insurance, customs_duty,
    vat_eu, vat_pl, rounding_adjustment, fx_delta_at_settlement
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Allow-lists ──────────────────────────────────────────────────────────────

#: Frozen set of allowed charge_type values. Adding a new type requires a
#: deliberate update + a passing contract test.
CHARGE_TYPES = frozenset({
    "net_goods",
    "freight",
    "insurance",
    "customs_duty",
    "vat_eu",
    "vat_pl",
    "rounding_adjustment",
    "fx_delta_at_settlement",
})

#: Where a charge value originated. ``operator`` = manually entered;
#: ``derived`` = computed from another charge (e.g. VAT from net_goods);
#: ``wfirma`` = pulled back from wFirma at posting time;
#: ``legacy_backfill`` = migrated from proforma_service_charges (Batch 6F.2).
CHARGE_SOURCES = frozenset({"operator", "derived", "wfirma", "legacy_backfill"})

POSTING_KINDS = frozenset({"proforma", "invoice", "correction"})

PAYMENT_SOURCES = frozenset({"wfirma", "bank_recon", "operator"})

ALLOCATION_METHODS = frozenset({"proportional", "operator_directed"})

#: This module's schema version. Used by forward-compatibility checks.
SCHEMA_VERSION = 1

_ISO_DATE_RE     = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}.*)?$")
_ISO_4217_RE     = re.compile(r"^[A-Z]{3}$")


# ── Domain dataclasses (read-only views) ─────────────────────────────────────

@dataclass
class Charge:
    id:           Optional[int]
    batch_id:     str
    client_name:  str
    charge_type:  str
    amount_minor: int          # minor units (cents) — float NEVER used
    currency:     str
    source:       str
    posting_id:   Optional[int]
    notes:        Optional[str]
    created_at:   str
    updated_at:   str


@dataclass
class Posting:
    id:                  Optional[int]
    batch_id:            str
    client_name:         str
    wfirma_invoice_id:   Optional[str]
    wfirma_doc_number:   Optional[str]
    posting_kind:        str
    posted_at:           Optional[str]
    issued_total_minor:  int
    currency:            str
    fx_rate_at_issue:    Optional[str]   # Decimal-as-string
    created_at:          str
    updated_at:          str


@dataclass
class Payment:
    id:                 Optional[int]
    posting_id:         int
    paid_at:            str
    amount_minor:       int
    currency:           str
    fx_rate_at_payment: Optional[str]
    wfirma_payment_id:  Optional[str]
    source:             str
    created_at:         str
    updated_at:         str


@dataclass
class PaymentAllocation:
    id:                 Optional[int]
    payment_id:         int
    charge_id:          int
    applied_minor:      int
    fx_delta_minor:     int
    allocation_method:  str
    created_at:         str


@dataclass
class Settlement:
    id:                       Optional[int]
    posting_id:               int
    settled_at:               str
    fx_delta_total_minor:     int
    rounding_diff_minor:      int
    created_at:               str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# ── Validation ───────────────────────────────────────────────────────────────

def validate_charge(data: Dict[str, Any]) -> List[str]:
    """Validate a charge row payload. Returns list of error strings."""
    errs: List[str] = []
    if not _clean(data.get("batch_id")):
        errs.append("batch_id is required")
    if not _clean(data.get("client_name")):
        errs.append("client_name is required")
    ct = _clean(data.get("charge_type"))
    if not ct:
        errs.append("charge_type is required")
    elif ct not in CHARGE_TYPES:
        errs.append(f"charge_type must be one of {sorted(CHARGE_TYPES)}, got {ct!r}")
    amount = data.get("amount_minor")
    if amount is None:
        errs.append("amount_minor is required")
    elif not isinstance(amount, int):
        errs.append(f"amount_minor must be int (minor units), got {type(amount).__name__}")
    currency = _clean(data.get("currency"))
    if not currency:
        errs.append("currency is required")
    elif not _ISO_4217_RE.match(currency.upper()):
        errs.append(f"currency must be ISO 4217, got {currency!r}")
    source = _clean(data.get("source"))
    if not source:
        errs.append("source is required")
    elif source not in CHARGE_SOURCES:
        errs.append(f"source must be one of {sorted(CHARGE_SOURCES)}, got {source!r}")
    return errs


def validate_posting(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not _clean(data.get("batch_id")):
        errs.append("batch_id is required")
    if not _clean(data.get("client_name")):
        errs.append("client_name is required")
    kind = _clean(data.get("posting_kind"))
    if not kind:
        errs.append("posting_kind is required")
    elif kind not in POSTING_KINDS:
        errs.append(f"posting_kind must be one of {sorted(POSTING_KINDS)}, got {kind!r}")
    if not isinstance(data.get("issued_total_minor"), int):
        errs.append("issued_total_minor must be int (minor units)")
    currency = _clean(data.get("currency"))
    if not currency:
        errs.append("currency is required")
    elif not _ISO_4217_RE.match(currency.upper()):
        errs.append(f"currency must be ISO 4217, got {currency!r}")
    return errs


def validate_payment(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not isinstance(data.get("posting_id"), int):
        errs.append("posting_id is required (int)")
    paid_at = _clean(data.get("paid_at"))
    if not paid_at:
        errs.append("paid_at is required")
    elif not _ISO_DATE_RE.match(paid_at):
        errs.append(f"paid_at must be ISO 8601, got {paid_at!r}")
    if not isinstance(data.get("amount_minor"), int):
        errs.append("amount_minor must be int (minor units)")
    currency = _clean(data.get("currency"))
    if not currency:
        errs.append("currency is required")
    elif not _ISO_4217_RE.match(currency.upper()):
        errs.append(f"currency must be ISO 4217, got {currency!r}")
    source = _clean(data.get("source"))
    if not source:
        errs.append("source is required")
    elif source not in PAYMENT_SOURCES:
        errs.append(f"source must be one of {sorted(PAYMENT_SOURCES)}, got {source!r}")
    return errs


def validate_allocation(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not isinstance(data.get("payment_id"), int):
        errs.append("payment_id must be int")
    if not isinstance(data.get("charge_id"), int):
        errs.append("charge_id must be int")
    if not isinstance(data.get("applied_minor"), int):
        errs.append("applied_minor must be int")
    elif data["applied_minor"] < 0:
        errs.append("applied_minor must be >= 0")
    method = _clean(data.get("allocation_method"))
    if not method:
        errs.append("allocation_method is required")
    elif method not in ALLOCATION_METHODS:
        errs.append(f"allocation_method must be one of {sorted(ALLOCATION_METHODS)}")
    if "fx_delta_minor" in data and not isinstance(data["fx_delta_minor"], int):
        errs.append("fx_delta_minor must be int")
    return errs


# ── Schema (idempotent) ──────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create the 6F.1 schema. Idempotent — re-running is a no-op.

    Order of creation matters for FK declarations but SQLite does not enforce
    FK by default. We declare them so future audits can see the structure.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        # Schema version registry — first table created so we can write a row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER NOT NULL,
                description TEXT,
                applied_at  TEXT NOT NULL
            )
        """)
        cur = conn.execute("SELECT MAX(version) FROM schema_version")
        existing = cur.fetchone()[0]
        if existing is None:
            conn.execute(
                "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
                (SCHEMA_VERSION, "6F.1 — finance_postings initial schema", _now()),
            )

        # 1. charges — typed components of an amount due
        conn.execute("""
            CREATE TABLE IF NOT EXISTS charges (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id      TEXT NOT NULL,
                client_name   TEXT NOT NULL,
                charge_type   TEXT NOT NULL,
                amount_minor  INTEGER NOT NULL,
                currency      TEXT NOT NULL,
                source        TEXT NOT NULL,
                posting_id    INTEGER,
                notes         TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                FOREIGN KEY (posting_id) REFERENCES postings(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_charges_batch_client ON charges (batch_id, client_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_charges_posting     ON charges (posting_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_charges_type        ON charges (charge_type)")

        # 2. postings — snapshot of charges issued to wFirma at moment T
        conn.execute("""
            CREATE TABLE IF NOT EXISTS postings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id            TEXT NOT NULL,
                client_name         TEXT NOT NULL,
                wfirma_invoice_id   TEXT,
                wfirma_doc_number   TEXT,
                posting_kind        TEXT NOT NULL,
                posted_at           TEXT,
                issued_total_minor  INTEGER NOT NULL,
                currency            TEXT NOT NULL,
                fx_rate_at_issue    TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_postings_batch_client ON postings (batch_id, client_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_postings_wfirma_id    ON postings (wfirma_invoice_id)")

        # 3. payments — inbound cash events
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                posting_id          INTEGER NOT NULL,
                paid_at             TEXT NOT NULL,
                amount_minor        INTEGER NOT NULL,
                currency            TEXT NOT NULL,
                fx_rate_at_payment  TEXT,
                wfirma_payment_id   TEXT,
                source              TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY (posting_id) REFERENCES postings(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_posting ON payments (posting_id)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_wfirma_unique "
            "ON payments (posting_id, wfirma_payment_id) "
            "WHERE wfirma_payment_id IS NOT NULL"
        )

        # 4. payment_allocations — one row per (payment_id, charge_id) pair
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_allocations (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id         INTEGER NOT NULL,
                charge_id          INTEGER NOT NULL,
                applied_minor      INTEGER NOT NULL,
                fx_delta_minor     INTEGER NOT NULL DEFAULT 0,
                allocation_method  TEXT NOT NULL,
                created_at         TEXT NOT NULL,
                FOREIGN KEY (payment_id) REFERENCES payments(id),
                FOREIGN KEY (charge_id)  REFERENCES charges(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_payment ON payment_allocations (payment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_charge  ON payment_allocations (charge_id)")

        # 5. settlements — a posting becomes fully-paid (event-only, append)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settlements (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                posting_id            INTEGER NOT NULL UNIQUE,
                settled_at            TEXT NOT NULL,
                fx_delta_total_minor  INTEGER NOT NULL DEFAULT 0,
                rounding_diff_minor   INTEGER NOT NULL DEFAULT 0,
                created_at            TEXT NOT NULL,
                FOREIGN KEY (posting_id) REFERENCES postings(id)
            )
        """)

        conn.commit()


# ── Row mapping ──────────────────────────────────────────────────────────────

def _row_to_charge(r: sqlite3.Row) -> Charge:
    return Charge(
        id=r["id"], batch_id=r["batch_id"], client_name=r["client_name"],
        charge_type=r["charge_type"], amount_minor=int(r["amount_minor"]),
        currency=r["currency"], source=r["source"],
        posting_id=r["posting_id"], notes=r["notes"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _row_to_posting(r: sqlite3.Row) -> Posting:
    return Posting(
        id=r["id"], batch_id=r["batch_id"], client_name=r["client_name"],
        wfirma_invoice_id=r["wfirma_invoice_id"], wfirma_doc_number=r["wfirma_doc_number"],
        posting_kind=r["posting_kind"], posted_at=r["posted_at"],
        issued_total_minor=int(r["issued_total_minor"]), currency=r["currency"],
        fx_rate_at_issue=r["fx_rate_at_issue"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _row_to_payment(r: sqlite3.Row) -> Payment:
    return Payment(
        id=r["id"], posting_id=int(r["posting_id"]),
        paid_at=r["paid_at"], amount_minor=int(r["amount_minor"]),
        currency=r["currency"], fx_rate_at_payment=r["fx_rate_at_payment"],
        wfirma_payment_id=r["wfirma_payment_id"], source=r["source"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _row_to_alloc(r: sqlite3.Row) -> PaymentAllocation:
    return PaymentAllocation(
        id=r["id"], payment_id=int(r["payment_id"]),
        charge_id=int(r["charge_id"]),
        applied_minor=int(r["applied_minor"]),
        fx_delta_minor=int(r["fx_delta_minor"]),
        allocation_method=r["allocation_method"],
        created_at=r["created_at"],
    )


def _row_to_settlement(r: sqlite3.Row) -> Settlement:
    return Settlement(
        id=r["id"], posting_id=int(r["posting_id"]),
        settled_at=r["settled_at"],
        fx_delta_total_minor=int(r["fx_delta_total_minor"]),
        rounding_diff_minor=int(r["rounding_diff_minor"]),
        created_at=r["created_at"],
    )


def _conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    return c


# ── Charges CRUD ─────────────────────────────────────────────────────────────

def create_charge(db_path: Path, data: Dict[str, Any]) -> Charge:
    errs = validate_charge(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    p = {
        "batch_id":     _clean(data.get("batch_id")),
        "client_name":  _clean(data.get("client_name")),
        "charge_type":  _clean(data.get("charge_type")),
        "amount_minor": int(data["amount_minor"]),
        "currency":     _clean(data.get("currency")).upper(),
        "source":       _clean(data.get("source")),
        "posting_id":   data.get("posting_id"),
        "notes":        _clean(data.get("notes")),
    }
    now = _now()
    with _conn(db_path) as c:
        cur = c.execute(
            """INSERT INTO charges (batch_id, client_name, charge_type, amount_minor,
                currency, source, posting_id, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["batch_id"], p["client_name"], p["charge_type"], p["amount_minor"],
             p["currency"], p["source"], p["posting_id"], p["notes"], now, now),
        )
        c.commit()
        return get_charge(db_path, int(cur.lastrowid))


def get_charge(db_path: Path, charge_id: int) -> Optional[Charge]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _conn(db_path) as c:
        try:
            r = c.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_charge(r) if r else None


def list_charges(db_path: Path, *, batch_id: Optional[str] = None,
                 client_name: Optional[str] = None,
                 posting_id: Optional[int] = None,
                 charge_type: Optional[str] = None,
                 limit: int = 500) -> List[Charge]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if batch_id:    where.append("batch_id=?");    params.append(batch_id)
    if client_name: where.append("client_name=?"); params.append(client_name)
    if posting_id is not None:
        where.append("posting_id=?"); params.append(posting_id)
    if charge_type: where.append("charge_type=?"); params.append(charge_type)
    sql = "SELECT * FROM charges"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(int(limit))
    with _conn(db_path) as c:
        try:
            return [_row_to_charge(r) for r in c.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def link_charge_to_posting(db_path: Path, charge_id: int, posting_id: int) -> Optional[Charge]:
    """After a posting is created, attach existing charges to it. Pure data
    update — no behaviour change downstream."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    existing = get_charge(db_path, charge_id)
    if existing is None:
        return None
    now = _now()
    with _conn(db_path) as c:
        c.execute("UPDATE charges SET posting_id=?, updated_at=? WHERE id=?",
                  (posting_id, now, charge_id))
        c.commit()
    return get_charge(db_path, charge_id)


# ── Postings CRUD ────────────────────────────────────────────────────────────

def create_posting(db_path: Path, data: Dict[str, Any]) -> Posting:
    errs = validate_posting(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    p = {
        "batch_id":           _clean(data.get("batch_id")),
        "client_name":        _clean(data.get("client_name")),
        "wfirma_invoice_id":  _clean(data.get("wfirma_invoice_id")),
        "wfirma_doc_number":  _clean(data.get("wfirma_doc_number")),
        "posting_kind":       _clean(data.get("posting_kind")),
        "posted_at":          _clean(data.get("posted_at")),
        "issued_total_minor": int(data["issued_total_minor"]),
        "currency":           _clean(data.get("currency")).upper(),
        "fx_rate_at_issue":   _clean(data.get("fx_rate_at_issue")),
    }
    now = _now()
    with _conn(db_path) as c:
        cur = c.execute(
            """INSERT INTO postings (batch_id, client_name, wfirma_invoice_id,
               wfirma_doc_number, posting_kind, posted_at, issued_total_minor,
               currency, fx_rate_at_issue, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["batch_id"], p["client_name"], p["wfirma_invoice_id"],
             p["wfirma_doc_number"], p["posting_kind"], p["posted_at"],
             p["issued_total_minor"], p["currency"], p["fx_rate_at_issue"],
             now, now),
        )
        c.commit()
        return get_posting(db_path, int(cur.lastrowid))


def get_posting(db_path: Path, posting_id: int) -> Optional[Posting]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _conn(db_path) as c:
        try:
            r = c.execute("SELECT * FROM postings WHERE id=?", (posting_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_posting(r) if r else None


def list_postings(db_path: Path, *, batch_id: Optional[str] = None,
                  client_name: Optional[str] = None,
                  limit: int = 500) -> List[Posting]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if batch_id:    where.append("batch_id=?");    params.append(batch_id)
    if client_name: where.append("client_name=?"); params.append(client_name)
    sql = "SELECT * FROM postings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(int(limit))
    with _conn(db_path) as c:
        try:
            return [_row_to_posting(r) for r in c.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


# ── Payments CRUD ────────────────────────────────────────────────────────────

def create_payment(db_path: Path, data: Dict[str, Any]) -> Payment:
    errs = validate_payment(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    p = {
        "posting_id":         int(data["posting_id"]),
        "paid_at":            _clean(data.get("paid_at")),
        "amount_minor":       int(data["amount_minor"]),
        "currency":           _clean(data.get("currency")).upper(),
        "fx_rate_at_payment": _clean(data.get("fx_rate_at_payment")),
        "wfirma_payment_id":  _clean(data.get("wfirma_payment_id")),
        "source":             _clean(data.get("source")),
    }
    now = _now()
    with _conn(db_path) as c:
        try:
            cur = c.execute(
                """INSERT INTO payments (posting_id, paid_at, amount_minor, currency,
                   fx_rate_at_payment, wfirma_payment_id, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["posting_id"], p["paid_at"], p["amount_minor"], p["currency"],
                 p["fx_rate_at_payment"], p["wfirma_payment_id"], p["source"], now, now),
            )
            c.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ValueError(f"DUPLICATE_PAYMENT: wfirma_payment_id "
                                 f"{p['wfirma_payment_id']!r} already linked "
                                 f"to posting {p['posting_id']}")
            raise
        return get_payment(db_path, int(cur.lastrowid))


def get_payment(db_path: Path, payment_id: int) -> Optional[Payment]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _conn(db_path) as c:
        try:
            r = c.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_payment(r) if r else None


def list_payments(db_path: Path, *, posting_id: Optional[int] = None,
                  limit: int = 500) -> List[Payment]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if posting_id is not None:
        where.append("posting_id=?"); params.append(posting_id)
    sql = "SELECT * FROM payments"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(int(limit))
    with _conn(db_path) as c:
        try:
            return [_row_to_payment(r) for r in c.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


# ── Allocations CRUD ─────────────────────────────────────────────────────────

def create_allocation(db_path: Path, data: Dict[str, Any]) -> PaymentAllocation:
    errs = validate_allocation(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    p = {
        "payment_id":        int(data["payment_id"]),
        "charge_id":         int(data["charge_id"]),
        "applied_minor":     int(data["applied_minor"]),
        "fx_delta_minor":    int(data.get("fx_delta_minor", 0)),
        "allocation_method": _clean(data.get("allocation_method")),
    }
    now = _now()
    with _conn(db_path) as c:
        cur = c.execute(
            """INSERT INTO payment_allocations (payment_id, charge_id,
               applied_minor, fx_delta_minor, allocation_method, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (p["payment_id"], p["charge_id"], p["applied_minor"],
             p["fx_delta_minor"], p["allocation_method"], now),
        )
        c.commit()
    return get_allocation(db_path, int(cur.lastrowid))


def get_allocation(db_path: Path, alloc_id: int) -> Optional[PaymentAllocation]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _conn(db_path) as c:
        try:
            r = c.execute("SELECT * FROM payment_allocations WHERE id=?", (alloc_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_alloc(r) if r else None


def list_allocations(db_path: Path, *, payment_id: Optional[int] = None,
                     charge_id: Optional[int] = None,
                     limit: int = 500) -> List[PaymentAllocation]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if payment_id is not None:
        where.append("payment_id=?"); params.append(payment_id)
    if charge_id is not None:
        where.append("charge_id=?"); params.append(charge_id)
    sql = "SELECT * FROM payment_allocations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(int(limit))
    with _conn(db_path) as c:
        try:
            return [_row_to_alloc(r) for r in c.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


# ── Settlements (append-only event) ──────────────────────────────────────────

def record_settlement(db_path: Path, data: Dict[str, Any]) -> Settlement:
    if not isinstance(data.get("posting_id"), int):
        raise ValueError("posting_id must be int")
    init_db(db_path)
    p = {
        "posting_id":            int(data["posting_id"]),
        "settled_at":            _clean(data.get("settled_at")) or _now(),
        "fx_delta_total_minor":  int(data.get("fx_delta_total_minor", 0)),
        "rounding_diff_minor":   int(data.get("rounding_diff_minor", 0)),
    }
    now = _now()
    with _conn(db_path) as c:
        try:
            cur = c.execute(
                """INSERT INTO settlements (posting_id, settled_at,
                   fx_delta_total_minor, rounding_diff_minor, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (p["posting_id"], p["settled_at"],
                 p["fx_delta_total_minor"], p["rounding_diff_minor"], now),
            )
            c.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ValueError(f"SETTLEMENT_EXISTS: posting {p['posting_id']} already settled")
            raise
    return get_settlement_for_posting(db_path, p["posting_id"])


def get_settlement_for_posting(db_path: Path, posting_id: int) -> Optional[Settlement]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _conn(db_path) as c:
        try:
            r = c.execute("SELECT * FROM settlements WHERE posting_id=?",
                          (posting_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_settlement(r) if r else None


# ── Pure helpers (no DB writes) ──────────────────────────────────────────────

def compute_sum_charges_minor(db_path: Path, posting_id: int) -> int:
    """Sum of charges attached to a posting. Read-only."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    with _conn(db_path) as c:
        try:
            r = c.execute(
                "SELECT COALESCE(SUM(amount_minor), 0) FROM charges WHERE posting_id=?",
                (posting_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
    return int(r[0])


def compute_sum_payments_minor(db_path: Path, posting_id: int) -> int:
    """Sum of payments attached to a posting. Read-only."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    with _conn(db_path) as c:
        try:
            r = c.execute(
                "SELECT COALESCE(SUM(amount_minor), 0) FROM payments WHERE posting_id=?",
                (posting_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
    return int(r[0])


def is_fully_paid(db_path: Path, posting_id: int, *,
                  tolerance_minor: int = 1) -> bool:
    """Read-only check: does the sum of payments cover the sum of charges
    (within rounding tolerance)? Does NOT mutate; settlement-close is a
    separate explicit operator action (Batch 6F.6)."""
    charges = compute_sum_charges_minor(db_path, posting_id)
    payments = compute_sum_payments_minor(db_path, posting_id)
    return abs(charges - payments) <= tolerance_minor


def current_schema_version(db_path: Path) -> Optional[int]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _conn(db_path) as c:
        try:
            r = c.execute("SELECT MAX(version) FROM schema_version").fetchone()
        except sqlite3.OperationalError:
            return None
    return int(r[0]) if r and r[0] is not None else None
