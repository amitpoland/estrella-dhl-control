"""
customer_master_db.py — local Customer Master layer (Layer 1).

This is the brain that sits between the operator's intent (sell to customer X)
and the wFirma proforma writer. It carries everything that is NOT directly
on the wFirma contractor record but is needed for proforma generation:

    - Ship-to (Inny odbiorca) — both shapes wFirma supports
    - Commercial defaults — currency, language id, insurance override
    - Credit / Kuke fields — stored but NOT enforced in Layer 1
                              (enforcement waits for the open-exposure probe)

Schema decisions, locked from the 2026-05-03 wFirma probe:

  Ship-to in wFirma is supported in TWO shapes; we store fields for BOTH and
  leave the writer (Layer 2) to pick:
    Shape A  — alternate address on the same legal entity
               wFirma fields: contact_*, different_contact_address
               Stored here:    ship_to_address_*  +  ship_to_use_alternate (bool)
    Shape B  — separate legal entity acts as receiver
               wFirma:        <contractor_receiver><id>NNN</id></contractor_receiver>
               Stored here:    ship_to_contractor_id

  At most one of (ship_to_use_alternate, ship_to_contractor_id) should be set
  per customer. Both unset means "ship to the bill-to address" (the default).

DB path is a Path argument (no globals). All functions are pure CRUD;
proforma orchestration lives in customer_master.py (resolver).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator, List, Optional


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CustomerMaster:
    """One customer record. Most fields are optional — store what you know."""
    # Identity (required)
    bill_to_contractor_id:   str             # wFirma contractor id
    bill_to_name:            str
    country:                 str             # ISO-3166 alpha-2

    # VAT
    nip:                     Optional[str] = None
    vat_eu_number:           Optional[str] = None
    vat_eu_valid:            Optional[bool] = None     # None=unknown, True=verified, False=invalid
    vat_eu_validated_at:     Optional[str] = None      # ISO date

    # Ship-to — Shape A: alternate address on same legal entity
    ship_to_use_alternate:   bool = False
    ship_to_name:            Optional[str] = None
    ship_to_person:          Optional[str] = None
    ship_to_street:          Optional[str] = None
    ship_to_city:            Optional[str] = None
    ship_to_zip:             Optional[str] = None
    ship_to_country:         Optional[str] = None
    ship_to_phone:           Optional[str] = None
    ship_to_email:           Optional[str] = None

    # Ship-to — Shape B: separate wFirma contractor as receiver
    ship_to_contractor_id:   Optional[str] = None

    # Commercial defaults (optional, used by proforma resolver if set)
    default_currency:              Optional[str] = None      # PLN | USD | EUR
    default_language_id:           Optional[str] = None      # wFirma translation_language_id
    preferred_proforma_series_id:  Optional[str] = None      # wFirma series id for proformas
    preferred_invoice_series_id:   Optional[str] = None      # wFirma series id for final invoices
    vat_mode:                      Optional[int] = None      # 222 | 228 | 229

    # Freight defaults
    freight_service_id:      Optional[str] = "13002743"   # wFirma good_id (Fedex Courier)
    freight_last_amount:     Optional[Decimal] = None
    freight_avg_amount:      Optional[Decimal] = None
    freight_currency:        Optional[str] = None
    freight_mode:            Optional[str] = None         # fixed | variable | manual | no_data

    # Insurance defaults
    insurance_service_id:    Optional[str] = "13102217"   # wFirma good_id
    insurance_min_amount:    Optional[Decimal] = None     # auto-detected min
    insurance_min_override:  Optional[Decimal] = None     # operator override beats _amount
    insurance_rate:          Optional[Decimal] = Decimal("0.0035")
    insurance_mode:          Optional[str] = None         # fixed | formula | manual | no_data

    # Credit / Kuke (stored only — Layer 1 does NOT enforce)
    credit_limit:            Optional[Decimal] = None
    credit_currency:         Optional[str] = None
    kuke_approved:           Optional[bool] = None
    kuke_limit:              Optional[Decimal] = None
    kuke_currency:           Optional[str] = None
    kuke_expiry_date:        Optional[str] = None      # ISO date
    risk_status:             Optional[str] = None      # e.g. "approved","watch","blocked"

    # Audit
    notes:                   Optional[str] = None
    id:                      Optional[int] = None
    created_at:              Optional[str] = None
    updated_at:              Optional[str] = None


def validate(c: CustomerMaster) -> List[str]:
    """Return a list of blockers (empty list = OK). Does not raise."""
    blockers: List[str] = []
    if not c.bill_to_contractor_id or not c.bill_to_contractor_id.strip():
        blockers.append("bill_to_contractor_id is required")
    if not c.bill_to_name or not c.bill_to_name.strip():
        blockers.append("bill_to_name is required")
    if not c.country or len(c.country.strip()) != 2:
        blockers.append("country must be ISO-3166 alpha-2 (2 letters)")
    if c.default_currency and c.default_currency not in ("PLN", "USD", "EUR"):
        blockers.append(f"default_currency must be one of PLN/USD/EUR, got {c.default_currency!r}")
    if c.ship_to_use_alternate and c.ship_to_contractor_id:
        blockers.append(
            "ship_to_use_alternate AND ship_to_contractor_id are both set — "
            "pick one shape (alternate address on same entity OR separate receiver entity)"
        )
    for label, value in (
        ("insurance_min_override", c.insurance_min_override),
        ("insurance_min_amount",   c.insurance_min_amount),
        ("freight_last_amount",    c.freight_last_amount),
        ("freight_avg_amount",     c.freight_avg_amount),
        ("credit_limit",           c.credit_limit),
        ("kuke_limit",             c.kuke_limit),
    ):
        if value is not None and Decimal(value) < 0:
            blockers.append(f"{label} must be >= 0, got {value}")
    if c.kuke_approved and not c.kuke_limit:
        blockers.append("kuke_approved=True requires kuke_limit to be set")
    if c.vat_mode is not None and c.vat_mode not in (222, 228, 229):
        blockers.append(f"vat_mode must be one of 222/228/229, got {c.vat_mode!r}")
    if c.freight_currency and c.freight_currency not in ("PLN", "USD", "EUR"):
        blockers.append(f"freight_currency must be PLN/USD/EUR, got {c.freight_currency!r}")
    if c.freight_mode and c.freight_mode not in ("fixed", "variable", "manual", "no_data"):
        blockers.append(f"freight_mode must be fixed/variable/manual/no_data, got {c.freight_mode!r}")
    if c.insurance_mode and c.insurance_mode not in ("fixed", "formula", "manual", "no_data"):
        blockers.append(f"insurance_mode must be fixed/formula/manual/no_data, got {c.insurance_mode!r}")
    if c.insurance_rate is not None:
        rate = Decimal(c.insurance_rate)
        if rate < 0 or rate > 1:
            blockers.append(f"insurance_rate must be in [0,1], got {rate}")
    return blockers


# ── DB helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db(db_path: Path) -> None:
    """Create the customer_master table. Idempotent.

    Schema includes ALL commercial fields. For pre-existing databases that
    were created before the commercial-fields extension, ALTER TABLE ADD
    COLUMN runs per missing column (graceful — already-existing columns are
    skipped via try/except)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_master (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_to_contractor_id    TEXT NOT NULL UNIQUE,
                bill_to_name             TEXT NOT NULL,
                country                  TEXT NOT NULL,
                nip                      TEXT,
                vat_eu_number            TEXT,
                vat_eu_valid             INTEGER,
                vat_eu_validated_at      TEXT,

                ship_to_use_alternate    INTEGER NOT NULL DEFAULT 0,
                ship_to_name             TEXT,
                ship_to_person           TEXT,
                ship_to_street           TEXT,
                ship_to_city             TEXT,
                ship_to_zip              TEXT,
                ship_to_country          TEXT,
                ship_to_phone            TEXT,
                ship_to_email            TEXT,
                ship_to_contractor_id    TEXT,

                default_currency               TEXT,
                default_language_id            TEXT,
                preferred_proforma_series_id   TEXT,
                preferred_invoice_series_id    TEXT,
                vat_mode                       INTEGER,

                freight_service_id        TEXT DEFAULT '13002743',
                freight_last_amount       TEXT,
                freight_avg_amount        TEXT,
                freight_currency          TEXT,
                freight_mode              TEXT,

                insurance_service_id      TEXT DEFAULT '13102217',
                insurance_min_amount      TEXT,
                insurance_min_override    TEXT,
                insurance_rate            TEXT DEFAULT '0.0035',
                insurance_mode            TEXT,

                credit_limit             TEXT,
                credit_currency          TEXT,
                kuke_approved            INTEGER,
                kuke_limit               TEXT,
                kuke_currency            TEXT,
                kuke_expiry_date         TEXT,
                risk_status              TEXT,

                notes                    TEXT,
                created_at               TEXT NOT NULL,
                updated_at               TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_customer_master_country
            ON customer_master (country)
        """)

        # Migration — add new columns to legacy DBs that pre-date them
        _migrate_add_columns(conn, [
            ("preferred_proforma_series_id", "TEXT"),
            ("preferred_invoice_series_id",  "TEXT"),
            ("vat_mode",                     "INTEGER"),
            ("freight_service_id",           "TEXT DEFAULT '13002743'"),
            ("freight_last_amount",          "TEXT"),
            ("freight_avg_amount",           "TEXT"),
            ("freight_currency",             "TEXT"),
            ("freight_mode",                 "TEXT"),
            ("insurance_service_id",         "TEXT DEFAULT '13102217'"),
            ("insurance_min_amount",         "TEXT"),
            ("insurance_rate",               "TEXT DEFAULT '0.0035'"),
            ("insurance_mode",               "TEXT"),
        ])


def _migrate_add_columns(conn: sqlite3.Connection,
                          cols: List) -> None:
    """ALTER TABLE ADD COLUMN for each (name, type_decl). Skips if exists."""
    cur = conn.execute("PRAGMA table_info(customer_master)")
    existing = {row[1] for row in cur.fetchall()}
    for name, type_decl in cols:
        if name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE customer_master ADD COLUMN {name} {type_decl}")
        except sqlite3.OperationalError:
            # column exists or other migration race; ignore
            pass


def _to_int(b: Optional[bool]) -> Optional[int]:
    if b is None: return None
    return 1 if b else 0


def _to_bool(i) -> Optional[bool]:
    if i is None: return None
    return bool(int(i))


def _dec_to_str(d: Optional[Decimal]) -> Optional[str]:
    if d is None: return None
    return str(Decimal(d))


def _str_to_dec(s) -> Optional[Decimal]:
    if s is None or s == "": return None
    return Decimal(str(s))


def _row_get(row: sqlite3.Row, key: str, default=None):
    """Like row[key] but tolerant of legacy DBs missing newer columns."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _row_to_customer(row: sqlite3.Row) -> CustomerMaster:
    return CustomerMaster(
        id                            = row["id"],
        bill_to_contractor_id         = row["bill_to_contractor_id"],
        bill_to_name                  = row["bill_to_name"],
        country                       = row["country"],
        nip                           = row["nip"],
        vat_eu_number                 = row["vat_eu_number"],
        vat_eu_valid                  = _to_bool(row["vat_eu_valid"]),
        vat_eu_validated_at           = row["vat_eu_validated_at"],
        ship_to_use_alternate         = bool(row["ship_to_use_alternate"]),
        ship_to_name                  = row["ship_to_name"],
        ship_to_person                = row["ship_to_person"],
        ship_to_street                = row["ship_to_street"],
        ship_to_city                  = row["ship_to_city"],
        ship_to_zip                   = row["ship_to_zip"],
        ship_to_country               = row["ship_to_country"],
        ship_to_phone                 = row["ship_to_phone"],
        ship_to_email                 = row["ship_to_email"],
        ship_to_contractor_id         = row["ship_to_contractor_id"],
        default_currency              = row["default_currency"],
        default_language_id           = row["default_language_id"],
        preferred_proforma_series_id  = _row_get(row, "preferred_proforma_series_id"),
        preferred_invoice_series_id   = _row_get(row, "preferred_invoice_series_id"),
        vat_mode                      = _row_get(row, "vat_mode"),
        freight_service_id            = _row_get(row, "freight_service_id", "13002743"),
        freight_last_amount           = _str_to_dec(_row_get(row, "freight_last_amount")),
        freight_avg_amount            = _str_to_dec(_row_get(row, "freight_avg_amount")),
        freight_currency              = _row_get(row, "freight_currency"),
        freight_mode                  = _row_get(row, "freight_mode"),
        insurance_service_id          = _row_get(row, "insurance_service_id", "13102217"),
        insurance_min_amount          = _str_to_dec(_row_get(row, "insurance_min_amount")),
        insurance_min_override        = _str_to_dec(row["insurance_min_override"]),
        insurance_rate                = _str_to_dec(_row_get(row, "insurance_rate")) or Decimal("0.0035"),
        insurance_mode                = _row_get(row, "insurance_mode"),
        credit_limit                  = _str_to_dec(row["credit_limit"]),
        credit_currency               = row["credit_currency"],
        kuke_approved                 = _to_bool(row["kuke_approved"]),
        kuke_limit                    = _str_to_dec(row["kuke_limit"]),
        kuke_currency                 = row["kuke_currency"],
        kuke_expiry_date              = row["kuke_expiry_date"],
        risk_status                   = row["risk_status"],
        notes                         = row["notes"],
        created_at                    = row["created_at"],
        updated_at                    = row["updated_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def upsert_customer(db_path: Path, c: CustomerMaster) -> int:
    """Insert or update by bill_to_contractor_id. Returns row id."""
    blockers = validate(c)
    if blockers:
        raise ValueError("customer_master validation failed: " + "; ".join(blockers))

    init_db(db_path)
    now = _now_iso()
    payload = {
        "bill_to_contractor_id":   c.bill_to_contractor_id.strip(),
        "bill_to_name":            c.bill_to_name.strip(),
        "country":                 c.country.strip().upper(),
        "nip":                     c.nip,
        "vat_eu_number":           c.vat_eu_number,
        "vat_eu_valid":            _to_int(c.vat_eu_valid),
        "vat_eu_validated_at":     c.vat_eu_validated_at,
        "ship_to_use_alternate":   _to_int(c.ship_to_use_alternate),
        "ship_to_name":            c.ship_to_name,
        "ship_to_person":          c.ship_to_person,
        "ship_to_street":          c.ship_to_street,
        "ship_to_city":            c.ship_to_city,
        "ship_to_zip":             c.ship_to_zip,
        "ship_to_country":         (c.ship_to_country or "").upper() or None,
        "ship_to_phone":           c.ship_to_phone,
        "ship_to_email":           c.ship_to_email,
        "ship_to_contractor_id":   c.ship_to_contractor_id,
        "default_currency":             c.default_currency,
        "default_language_id":          c.default_language_id,
        "preferred_proforma_series_id": c.preferred_proforma_series_id,
        "preferred_invoice_series_id":  c.preferred_invoice_series_id,
        "vat_mode":                     int(c.vat_mode) if c.vat_mode is not None else None,
        "freight_service_id":           c.freight_service_id,
        "freight_last_amount":          _dec_to_str(c.freight_last_amount),
        "freight_avg_amount":           _dec_to_str(c.freight_avg_amount),
        "freight_currency":             c.freight_currency,
        "freight_mode":                 c.freight_mode,
        "insurance_service_id":         c.insurance_service_id,
        "insurance_min_amount":         _dec_to_str(c.insurance_min_amount),
        "insurance_min_override":       _dec_to_str(c.insurance_min_override),
        "insurance_rate":               _dec_to_str(c.insurance_rate),
        "insurance_mode":               c.insurance_mode,
        "credit_limit":                 _dec_to_str(c.credit_limit),
        "credit_currency":         c.credit_currency,
        "kuke_approved":           _to_int(c.kuke_approved),
        "kuke_limit":              _dec_to_str(c.kuke_limit),
        "kuke_currency":           c.kuke_currency,
        "kuke_expiry_date":        c.kuke_expiry_date,
        "risk_status":             c.risk_status,
        "notes":                   c.notes,
        "updated_at":              now,
    }

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM customer_master WHERE bill_to_contractor_id = ?",
            (payload["bill_to_contractor_id"],),
        ).fetchone()
        if existing is None:
            cols = ",".join(payload.keys()) + ",created_at"
            placeholders = ",".join("?" for _ in payload) + ",?"
            cur = conn.execute(
                f"INSERT INTO customer_master ({cols}) VALUES ({placeholders})",
                tuple(payload.values()) + (now,),
            )
            return int(cur.lastrowid or 0)
        # Update
        set_clause = ",".join(f"{k} = ?" for k in payload.keys())
        conn.execute(
            f"UPDATE customer_master SET {set_clause} WHERE id = ?",
            tuple(payload.values()) + (int(existing["id"]),),
        )
        return int(existing["id"])


def get_customer(db_path: Path, bill_to_contractor_id: str) -> Optional[CustomerMaster]:
    """Read by wFirma contractor id. Returns None if absent."""
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customer_master WHERE bill_to_contractor_id = ?",
            (bill_to_contractor_id,),
        ).fetchone()
    return _row_to_customer(row) if row else None


def list_customers(db_path: Path,
                   country: Optional[str] = None,
                   risk_status: Optional[str] = None,
                   limit: int = 200) -> List[CustomerMaster]:
    """Read with optional filters."""
    if not Path(db_path).is_file():
        return []
    sql = "SELECT * FROM customer_master WHERE 1=1"
    params: list = []
    if country:
        sql += " AND country = ?"; params.append(country.upper())
    if risk_status:
        sql += " AND risk_status = ?"; params.append(risk_status)
    sql += " ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_customer(r) for r in rows]


def delete_customer(db_path: Path, bill_to_contractor_id: str) -> bool:
    """Hard delete (test/admin use). Returns True if a row was removed."""
    if not Path(db_path).is_file():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            "DELETE FROM customer_master WHERE bill_to_contractor_id = ?",
            (bill_to_contractor_id,),
        )
        return cur.rowcount > 0


__all__ = [
    "CustomerMaster",
    "validate",
    "init_db",
    "upsert_customer",
    "get_customer",
    "list_customers",
    "delete_customer",
]
