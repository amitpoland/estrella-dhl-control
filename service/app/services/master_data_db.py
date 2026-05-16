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


# B7 ─────────────────────────────────────────────────────────────────────────

@dataclass
class CarrierConfig:
    """Carrier configuration registry — LOCAL, NON-SECRET only. Holds the
    operator-facing description of how each carrier integrates with the
    shipping pipeline. Credentials live in .env and are NOT stored here.
    The PZ + DHL runtime subsystem is NOT touched by this table; it is a
    documentation / parser-routing reference only."""
    carrier_code:        str               # e.g. dhl, fedex, ups
    name:                Optional[str] = None
    parser_type:         Optional[str] = None  # e.g. dhl_emea, fedex_classic
    inbox_email:         Optional[str] = None  # operator-facing inbox label
    api_type:            Optional[str] = None  # api | portal | email_only
    supported_services:  Optional[str] = None  # CSV list, free-form
    notes:               Optional[str] = None
    active:              bool = True
    created_at:          Optional[str] = None
    updated_at:          Optional[str] = None


@dataclass
class Incoterm:
    code:                 str               # e.g. EXW, FOB, CIF, DDP
    name:                 Optional[str] = None
    risk_transfer_point:  Optional[str] = None
    freight_included:     bool = False
    insurance_included:   bool = False
    customs_included:     bool = False
    notes:                Optional[str] = None
    active:               bool = True
    created_at:           Optional[str] = None
    updated_at:           Optional[str] = None


@dataclass
class FxRate:
    """Local FX rate observation table. PURE REFERENCE — does NOT override
    NBP rates used by the PZ landed-cost / customs calculation engine.
    The PZ engine consumes NBP rates live; this table records observed /
    audited rate values for operator review only."""
    rate_date:      str               # YYYY-MM-DD
    from_currency:  str               # ISO 4217 (3-letter)
    to_currency:    str               # ISO 4217 (3-letter)
    rate:           str               # Decimal-as-string
    source:         Optional[str] = None
    table_number:   Optional[str] = None
    notes:          Optional[str] = None
    active:         bool = True
    id:             Optional[int] = None
    created_at:     Optional[str] = None
    updated_at:     Optional[str] = None


@dataclass
class VatConfig:
    """Local VAT rate reference. READ-ONLY w.r.t. wFirma invoice path —
    this table does NOT override VAT codes used by wFirma invoice generation."""
    country:        str                 # ISO alpha-2
    product_type:   Optional[str] = None
    rate_pct:       Optional[str] = None   # Decimal-as-string
    rate_code:      Optional[str] = None
    effective_from: Optional[str] = None
    effective_to:   Optional[str] = None
    active:         bool = True
    notes:          Optional[str] = None
    id:             Optional[int] = None
    created_at:     Optional[str] = None
    updated_at:     Optional[str] = None


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

        # ── B7 ─────────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incoterms (
                code                 TEXT PRIMARY KEY,
                name                 TEXT,
                risk_transfer_point  TEXT,
                freight_included     INTEGER NOT NULL DEFAULT 0,
                insurance_included   INTEGER NOT NULL DEFAULT 0,
                customs_included     INTEGER NOT NULL DEFAULT 0,
                notes                TEXT,
                active               INTEGER NOT NULL DEFAULT 1,
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS vat_config (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                country         TEXT NOT NULL,
                product_type    TEXT,
                rate_pct        TEXT,
                rate_code       TEXT,
                effective_from  TEXT,
                effective_to    TEXT,
                active          INTEGER NOT NULL DEFAULT 1,
                notes           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vat_country ON vat_config (country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vat_active  ON vat_config (active)")

        # ── B8 FX rates (reference observation only) ───────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fx_rates (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                rate_date     TEXT NOT NULL,
                from_currency TEXT NOT NULL,
                to_currency   TEXT NOT NULL,
                rate          TEXT NOT NULL,
                source        TEXT,
                table_number  TEXT,
                notes         TEXT,
                active        INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fx_date ON fx_rates (rate_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fx_pair ON fx_rates (from_currency, to_currency)")

        # ── B9 Carrier configuration (LOCAL, NON-SECRET only) ──────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS carriers_config (
                carrier_code        TEXT PRIMARY KEY,
                name                TEXT,
                parser_type         TEXT,
                inbox_email         TEXT,
                api_type            TEXT,
                supported_services  TEXT,
                notes               TEXT,
                active              INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_carriers_active ON carriers_config (active)")

        conn.commit()


# ── B9 Carrier Config (LOCAL, NON-SECRET) ────────────────────────────────────

_CARRIER_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_VALID_API_TYPES = frozenset({"api", "portal", "email_only", "manual"})
_EMAIL_RE        = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_carrier_config(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    code = _clean(data.get("carrier_code"))
    if not code:
        errors.append("carrier_code is required")
    elif not _CARRIER_CODE_RE.match(code):
        errors.append(f"carrier_code must be lowercase a-z 0-9 _ (2-32 chars), got {code!r}")
    api_type = _clean(data.get("api_type"))
    if api_type is not None and api_type not in _VALID_API_TYPES:
        errors.append(f"api_type must be one of {sorted(_VALID_API_TYPES)}, got {api_type!r}")
    email = _clean(data.get("inbox_email"))
    if email is not None and not _EMAIL_RE.match(email):
        errors.append(f"inbox_email is malformed: {email!r}")
    # Guard: refuse to store secret-looking fields
    for forbidden in ("api_key", "api_secret", "password", "token", "client_secret",
                      "credentials", "auth_secret"):
        if forbidden in data:
            errors.append(f"carriers_config must not store secrets (rejected field: {forbidden})")
    return errors


def _row_to_carrier(row: sqlite3.Row) -> CarrierConfig:
    return CarrierConfig(
        carrier_code=row["carrier_code"], name=row["name"],
        parser_type=row["parser_type"], inbox_email=row["inbox_email"],
        api_type=row["api_type"], supported_services=row["supported_services"],
        notes=row["notes"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def upsert_carrier_config(db_path: Path, data: Dict[str, Any]) -> CarrierConfig:
    errs = validate_carrier_config(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    code = _clean(data.get("carrier_code")).lower()
    p = {
        "name":               _clean(data.get("name")),
        "parser_type":        _clean(data.get("parser_type")),
        "inbox_email":        _clean(data.get("inbox_email")),
        "api_type":           _clean(data.get("api_type")),
        "supported_services": _clean(data.get("supported_services")),
        "notes":              _clean(data.get("notes")),
        "active":             1 if data.get("active", True) else 0,
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        existing = conn.execute("SELECT 1 FROM carriers_config WHERE carrier_code=?",
                                (code,)).fetchone()
        if existing:
            conn.execute("""UPDATE carriers_config SET name=?, parser_type=?,
                inbox_email=?, api_type=?, supported_services=?, notes=?,
                active=?, updated_at=? WHERE carrier_code=?""",
                (p["name"], p["parser_type"], p["inbox_email"], p["api_type"],
                 p["supported_services"], p["notes"], p["active"], now, code))
        else:
            conn.execute("""INSERT INTO carriers_config (carrier_code, name,
                parser_type, inbox_email, api_type, supported_services, notes,
                active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, p["name"], p["parser_type"], p["inbox_email"],
                 p["api_type"], p["supported_services"], p["notes"],
                 p["active"], now, now))
        conn.commit()
    return get_carrier_config(db_path, code)


def get_carrier_config(db_path: Path, carrier_code: str) -> Optional[CarrierConfig]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM carriers_config WHERE carrier_code=?",
                               (carrier_code.lower(),)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_carrier(row) if row else None


def list_carrier_configs(db_path: Path, *, active: Optional[bool] = None,
                         limit: int = 100) -> List[CarrierConfig]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if active is not None:
        where.append("active=?")
        params.append(1 if active else 0)
    sql = "SELECT * FROM carriers_config"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY carrier_code ASC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_carrier(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def delete_carrier_config(db_path: Path, carrier_code: str) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM carriers_config WHERE carrier_code=?",
                               (carrier_code.lower(),))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── B8 FX Rates (reference observation only — NOT a PZ override path) ───────

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DATE_RE     = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_fx_rate(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    rd = _clean(data.get("rate_date"))
    if not rd:
        errors.append("rate_date is required")
    elif not _DATE_RE.match(rd):
        errors.append(f"rate_date must be YYYY-MM-DD, got {rd!r}")
    for f in ("from_currency", "to_currency"):
        v = _clean(data.get(f))
        if not v:
            errors.append(f"{f} is required")
        elif not _CURRENCY_RE.match(v.upper()):
            errors.append(f"{f} must be 3-letter ISO 4217, got {v!r}")
    rate = data.get("rate")
    if rate is None or rate == "":
        errors.append("rate is required")
    else:
        try:
            _to_decimal_str(rate)
        except ValueError as e:
            errors.append(f"rate: {e}")
    return errors


def _row_to_fx(row: sqlite3.Row) -> FxRate:
    return FxRate(
        id=row["id"], rate_date=row["rate_date"],
        from_currency=row["from_currency"], to_currency=row["to_currency"],
        rate=row["rate"], source=row["source"], table_number=row["table_number"],
        notes=row["notes"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def create_fx_rate(db_path: Path, data: Dict[str, Any]) -> FxRate:
    errs = validate_fx_rate(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    p = {
        "rate_date":     _clean(data.get("rate_date")),
        "from_currency": _clean(data.get("from_currency")).upper(),
        "to_currency":   _clean(data.get("to_currency")).upper(),
        "rate":          _to_decimal_str(data.get("rate")),
        "source":        _clean(data.get("source")),
        "table_number":  _clean(data.get("table_number")),
        "notes":         _clean(data.get("notes")),
        "active":        1 if data.get("active", True) else 0,
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute("""INSERT INTO fx_rates (rate_date, from_currency,
            to_currency, rate, source, table_number, notes, active,
            created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["rate_date"], p["from_currency"], p["to_currency"], p["rate"],
             p["source"], p["table_number"], p["notes"], p["active"], now, now))
        conn.commit()
        return get_fx_rate(db_path, int(cur.lastrowid))


def get_fx_rate(db_path: Path, fx_id: int) -> Optional[FxRate]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM fx_rates WHERE id=?", (fx_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_fx(row) if row else None


def list_fx_rates(db_path: Path, *, from_currency: Optional[str] = None,
                  to_currency: Optional[str] = None, rate_date: Optional[str] = None,
                  active: Optional[bool] = None, limit: int = 500) -> List[FxRate]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if from_currency:
        where.append("from_currency=?"); params.append(from_currency.upper())
    if to_currency:
        where.append("to_currency=?"); params.append(to_currency.upper())
    if rate_date:
        where.append("rate_date=?"); params.append(rate_date)
    if active is not None:
        where.append("active=?"); params.append(1 if active else 0)
    sql = "SELECT * FROM fx_rates"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rate_date DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_fx(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def update_fx_rate(db_path: Path, fx_id: int, data: Dict[str, Any]) -> Optional[FxRate]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    existing = get_fx_rate(db_path, fx_id)
    if existing is None:
        return None
    merged = {
        "rate_date":     data.get("rate_date",     existing.rate_date),
        "from_currency": data.get("from_currency", existing.from_currency),
        "to_currency":   data.get("to_currency",   existing.to_currency),
        "rate":          data.get("rate",          existing.rate),
        "source":        data.get("source",        existing.source),
        "table_number":  data.get("table_number",  existing.table_number),
        "notes":         data.get("notes",         existing.notes),
        "active":        data.get("active",        existing.active),
    }
    errs = validate_fx_rate(merged)
    if errs:
        raise ValueError("; ".join(errs))
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""UPDATE fx_rates SET rate_date=?, from_currency=?, to_currency=?,
            rate=?, source=?, table_number=?, notes=?, active=?, updated_at=?
            WHERE id=?""",
            (_clean(merged["rate_date"]), _clean(merged["from_currency"]).upper(),
             _clean(merged["to_currency"]).upper(), _to_decimal_str(merged["rate"]),
             _clean(merged["source"]), _clean(merged["table_number"]),
             _clean(merged["notes"]), 1 if merged["active"] else 0, now, fx_id))
        conn.commit()
    return get_fx_rate(db_path, fx_id)


def delete_fx_rate(db_path: Path, fx_id: int) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM fx_rates WHERE id=?", (fx_id,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── B7 Incoterms ─────────────────────────────────────────────────────────────

_INCOTERM_RE = re.compile(r"^[A-Z]{3}$")


def validate_incoterm(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    code = _clean(data.get("code"))
    if not code:
        errors.append("code is required")
    elif not _INCOTERM_RE.match(code.upper()):
        errors.append(f"code must be 3 uppercase letters, got {code!r}")
    return errors


def _row_to_incoterm(row: sqlite3.Row) -> Incoterm:
    return Incoterm(
        code=row["code"], name=row["name"],
        risk_transfer_point=row["risk_transfer_point"],
        freight_included=bool(int(row["freight_included"])),
        insurance_included=bool(int(row["insurance_included"])),
        customs_included=bool(int(row["customs_included"])),
        notes=row["notes"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def upsert_incoterm(db_path: Path, data: Dict[str, Any]) -> Incoterm:
    errs = validate_incoterm(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    code = _clean(data.get("code")).upper()
    p = {
        "name":                _clean(data.get("name")),
        "risk_transfer_point": _clean(data.get("risk_transfer_point")),
        "freight_included":    1 if data.get("freight_included") else 0,
        "insurance_included":  1 if data.get("insurance_included") else 0,
        "customs_included":    1 if data.get("customs_included") else 0,
        "notes":               _clean(data.get("notes")),
        "active":              1 if data.get("active", True) else 0,
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        exists = conn.execute("SELECT 1 FROM incoterms WHERE code=?", (code,)).fetchone()
        if exists:
            conn.execute("""UPDATE incoterms SET name=?, risk_transfer_point=?,
                freight_included=?, insurance_included=?, customs_included=?,
                notes=?, active=?, updated_at=? WHERE code=?""",
                (p["name"], p["risk_transfer_point"], p["freight_included"],
                 p["insurance_included"], p["customs_included"],
                 p["notes"], p["active"], now, code))
        else:
            conn.execute("""INSERT INTO incoterms (code, name, risk_transfer_point,
                freight_included, insurance_included, customs_included,
                notes, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, p["name"], p["risk_transfer_point"], p["freight_included"],
                 p["insurance_included"], p["customs_included"],
                 p["notes"], p["active"], now, now))
        conn.commit()
    return get_incoterm(db_path, code)


def get_incoterm(db_path: Path, code: str) -> Optional[Incoterm]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM incoterms WHERE code=?", (code.upper(),)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_incoterm(row) if row else None


def list_incoterms(db_path: Path, *, active: Optional[bool] = None,
                   limit: int = 100) -> List[Incoterm]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if active is not None:
        where.append("active=?")
        params.append(1 if active else 0)
    sql = "SELECT * FROM incoterms"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY code ASC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_incoterm(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def delete_incoterm(db_path: Path, code: str) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM incoterms WHERE code=?", (code.upper(),))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── B7 VAT Config (READ-ONLY w.r.t. wFirma invoicing) ────────────────────────

_ISO2_RE = re.compile(r"^[A-Z]{2}$")


def validate_vat_config(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    country = _clean(data.get("country"))
    if not country:
        errors.append("country is required")
    elif not _ISO2_RE.match(country.upper()):
        errors.append(f"country must be ISO alpha-2, got {country!r}")
    rate = data.get("rate_pct")
    if rate is not None and rate != "":
        try:
            _to_decimal_str(rate)
        except ValueError as e:
            errors.append(f"rate_pct: {e}")
    return errors


def _row_to_vat(row: sqlite3.Row) -> VatConfig:
    return VatConfig(
        id=row["id"], country=row["country"], product_type=row["product_type"],
        rate_pct=row["rate_pct"], rate_code=row["rate_code"],
        effective_from=row["effective_from"], effective_to=row["effective_to"],
        active=bool(int(row["active"])), notes=row["notes"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def create_vat_config(db_path: Path, data: Dict[str, Any]) -> VatConfig:
    errs = validate_vat_config(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    p = {
        "country":        _clean(data.get("country")).upper(),
        "product_type":   _clean(data.get("product_type")),
        "rate_pct":       _to_decimal_str(data.get("rate_pct")),
        "rate_code":      _clean(data.get("rate_code")),
        "effective_from": _clean(data.get("effective_from")),
        "effective_to":   _clean(data.get("effective_to")),
        "active":         1 if data.get("active", True) else 0,
        "notes":          _clean(data.get("notes")),
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute("""INSERT INTO vat_config (country, product_type, rate_pct,
            rate_code, effective_from, effective_to, active, notes,
            created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["country"], p["product_type"], p["rate_pct"], p["rate_code"],
             p["effective_from"], p["effective_to"], p["active"], p["notes"],
             now, now))
        conn.commit()
        return get_vat_config(db_path, int(cur.lastrowid))


def get_vat_config(db_path: Path, vat_id: int) -> Optional[VatConfig]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM vat_config WHERE id=?", (vat_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_vat(row) if row else None


def list_vat_config(db_path: Path, *, country: Optional[str] = None,
                    active: Optional[bool] = None, limit: int = 500) -> List[VatConfig]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if country:
        where.append("country=?")
        params.append(country.upper())
    if active is not None:
        where.append("active=?")
        params.append(1 if active else 0)
    sql = "SELECT * FROM vat_config"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY country ASC, updated_at DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_vat(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def update_vat_config(db_path: Path, vat_id: int, data: Dict[str, Any]) -> Optional[VatConfig]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    existing = get_vat_config(db_path, vat_id)
    if existing is None:
        return None
    merged = {
        "country":        data.get("country", existing.country),
        "product_type":   data.get("product_type", existing.product_type),
        "rate_pct":       data.get("rate_pct", existing.rate_pct),
        "rate_code":      data.get("rate_code", existing.rate_code),
        "effective_from": data.get("effective_from", existing.effective_from),
        "effective_to":   data.get("effective_to", existing.effective_to),
        "active":         data.get("active", existing.active),
        "notes":          data.get("notes", existing.notes),
    }
    errs = validate_vat_config(merged)
    if errs:
        raise ValueError("; ".join(errs))
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""UPDATE vat_config SET country=?, product_type=?, rate_pct=?,
            rate_code=?, effective_from=?, effective_to=?, active=?, notes=?,
            updated_at=? WHERE id=?""",
            (_clean(merged["country"]).upper(), _clean(merged["product_type"]),
             _to_decimal_str(merged["rate_pct"]), _clean(merged["rate_code"]),
             _clean(merged["effective_from"]), _clean(merged["effective_to"]),
             1 if merged["active"] else 0, _clean(merged["notes"]), now, vat_id))
        conn.commit()
    return get_vat_config(db_path, vat_id)


def delete_vat_config(db_path: Path, vat_id: int) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM vat_config WHERE id=?", (vat_id,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


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
