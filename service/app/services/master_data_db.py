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
    deleted_at:     Optional[str] = None   # Phase 4B Wave 1 — soft-delete timestamp


@dataclass
class Unit:
    code:        str
    name_pl:     Optional[str] = None
    name_en:     Optional[str] = None
    unit_type:   Optional[str] = None    # e.g. piece / weight / volume
    active:      bool = True
    created_at:  Optional[str] = None
    updated_at:  Optional[str] = None
    deleted_at:  Optional[str] = None    # Phase 4B Wave 1


@dataclass
class ProductLocal:
    product_code:     str
    hs_code_override: Optional[str] = None
    unit_override:    Optional[str] = None
    design_code_link: Optional[str] = None
    notes:            Optional[str] = None
    # Phase 4 — origin country for customs (seeded 'IN' for all jewellery)
    origin_country:   str = "IN"
    created_at:       Optional[str] = None
    updated_at:       Optional[str] = None
    # Phase 4B Wave 4 — soft-delete lifecycle. active=False means the overlay
    # is NOT applied; consumers fall back to non-overlay behavior.
    active:           bool = True
    deleted_at:       Optional[str] = None


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
    deleted_at:          Optional[str] = None   # Phase 4B Wave 3a — soft-delete


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
    deleted_at:           Optional[str] = None   # Phase 4B Wave 1


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
    deleted_at:     Optional[str] = None   # Phase 4B Wave 1


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
    deleted_at:     Optional[str] = None   # Phase 4B Wave 1


@dataclass
class Design:
    """B-MD2 Designs master (MDOC-2026-05).

    Local additive master. Soft references only — ``product_ref``,
    ``hs_code``, ``unit`` are documented FK-by-value into wFirma products /
    ``hs_codes`` / ``units`` but no SQL FK constraint is enforced (consistent
    with the rest of the master-data style).

    ``product_identity_engine`` MUST NOT read this table; the engine remains
    a read-only consumer of its own raw inputs.
    """
    design_code:   str
    display_name:  Optional[str] = None
    product_ref:   Optional[str] = None
    design_family: Optional[str] = None
    collection:    Optional[str] = None
    metal:         Optional[str] = None
    stone_summary: Optional[str] = None
    hs_code:       Optional[str] = None
    unit:          Optional[str] = None
    active:        bool = True
    notes:         Optional[str] = None
    created_at:    Optional[str] = None
    updated_at:    Optional[str] = None
    deleted_at:    Optional[str] = None   # Phase 4B Wave 1


# ── Helpers ───────────────────────────────────────────────────────────────────

_HS_CODE_RE = re.compile(r"^[0-9]{4,12}$")
_DESIGN_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./]{0,63}$")


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
        # Phase 4 — additive ALTER: origin_country defaults to 'IN'
        # so all existing jewellery rows (sourced from India) are seeded.
        try:
            conn.execute(
                "ALTER TABLE product_local ADD COLUMN origin_country "
                "TEXT NOT NULL DEFAULT 'IN'"
            )
        except sqlite3.OperationalError as _e:
            if "duplicate column" not in str(_e).lower():
                raise
        # Phase 4B Wave 4 — additive soft-delete columns.
        for _pl_col in (
            "ALTER TABLE product_local ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE product_local ADD COLUMN deleted_at TEXT",
        ):
            try:
                conn.execute(_pl_col)
            except sqlite3.OperationalError as _e:
                if "duplicate column" not in str(_e).lower():
                    raise
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pl_active ON product_local (active)")

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

        # ── B-MD2 Designs master (MDOC-2026-05) ────────────────────────
        # Additive local master. Soft references only — no SQL FK.
        # product_identity_engine MUST NOT read this table.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS designs (
                design_code    TEXT PRIMARY KEY,
                display_name   TEXT,
                product_ref    TEXT,
                design_family  TEXT,
                collection     TEXT,
                metal          TEXT,
                stone_summary  TEXT,
                hs_code        TEXT,
                unit           TEXT,
                active         INTEGER NOT NULL DEFAULT 1,
                notes          TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_designs_active ON designs (active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_designs_family ON designs (design_family)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_designs_collection ON designs (collection)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_designs_product_ref ON designs (product_ref)")

        # ── Phase D — box_types master (outbound label / Path-DOC) ──────────
        # Operator-maintained packaging catalogue. Drives dims + tare for the
        # label-package endpoint. No seed data; operator populates via API.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS box_types (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                code             TEXT NOT NULL UNIQUE,
                name             TEXT,
                length_cm        REAL,
                width_cm         REAL,
                height_cm        REAL,
                tare_weight_kg   REAL,
                active           INTEGER NOT NULL DEFAULT 1,
                notes            TEXT,
                created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_box_types_code ON box_types (code)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_box_types_active ON box_types (active)"
        )

        # ── Description mappings — operator-approved metal/purity resolver ──
        # Stores known token → facts approved by a human via Inbox proposal.
        # Resolver reads this table before falling through to the engine.
        # Governance: only approved Inbox actions write here; AI never writes.
        # Auditability: approved_by / approved_at / source_proposal_id are
        # non-nullable — every row is permanently answerable.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS description_mappings (
                id                 TEXT PRIMARY KEY,
                token              TEXT NOT NULL,
                canonical_metal    TEXT,
                purity             TEXT,
                material_pl        TEXT NOT NULL,
                purity_gen         TEXT,
                description_pl     TEXT,
                approved_by        TEXT NOT NULL,
                approved_at        TEXT NOT NULL,
                source_proposal_id TEXT NOT NULL,
                source_text        TEXT NOT NULL,
                confidence         TEXT NOT NULL DEFAULT 'medium',
                supplier_scope     TEXT DEFAULT NULL,
                active             INTEGER NOT NULL DEFAULT 1,
                created_at         TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_dm_token_supplier "
            "ON description_mappings(token, COALESCE(supplier_scope, ''))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_dm_active ON description_mappings (active)"
        )

        # ── Phase 4B Wave 1 — soft-delete deleted_at column migration ─────
        # Idempotent ALTER TABLE for each of the six Wave 1 entities.
        # Tables created on Wave 1 deploy already include deleted_at via
        # CREATE TABLE; pre-Wave-1 DBs need the ALTER. SQLite has no
        # IF NOT EXISTS on ALTER — we swallow only the "duplicate column"
        # error and re-raise anything else.
        for _tbl in ("hs_codes", "units", "incoterms",
                     "vat_config", "fx_rates", "designs",
                     # Phase 4B Wave 3a — carriers_config soft-delete.
                     "carriers_config"):
            try:
                conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN deleted_at TEXT")
            except sqlite3.OperationalError as _exc:
                if "duplicate column" not in str(_exc).lower():
                    raise

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
    keys = row.keys() if hasattr(row, "keys") else []
    return CarrierConfig(
        carrier_code=row["carrier_code"], name=row["name"],
        parser_type=row["parser_type"], inbox_email=row["inbox_email"],
        api_type=row["api_type"], supported_services=row["supported_services"],
        notes=row["notes"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
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
    keys = row.keys() if hasattr(row, "keys") else []
    return FxRate(
        id=row["id"], rate_date=row["rate_date"],
        from_currency=row["from_currency"], to_currency=row["to_currency"],
        rate=row["rate"], source=row["source"], table_number=row["table_number"],
        notes=row["notes"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
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
    keys = row.keys() if hasattr(row, "keys") else []
    return Incoterm(
        code=row["code"], name=row["name"],
        risk_transfer_point=row["risk_transfer_point"],
        freight_included=bool(int(row["freight_included"])),
        insurance_included=bool(int(row["insurance_included"])),
        customs_included=bool(int(row["customs_included"])),
        notes=row["notes"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
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
    keys = row.keys() if hasattr(row, "keys") else []
    return VatConfig(
        id=row["id"], country=row["country"], product_type=row["product_type"],
        rate_pct=row["rate_pct"], rate_code=row["rate_code"],
        effective_from=row["effective_from"], effective_to=row["effective_to"],
        active=bool(int(row["active"])), notes=row["notes"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
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
    keys = row.keys() if hasattr(row, "keys") else []
    return HsCode(
        hs_code=row["hs_code"], description_pl=row["description_pl"],
        description_en=row["description_en"], duty_rate_pct=row["duty_rate_pct"],
        vat_rate_pct=row["vat_rate_pct"], active=bool(int(row["active"])),
        notes=row["notes"], created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
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
    keys = row.keys() if hasattr(row, "keys") else []
    return Unit(
        code=row["code"], name_pl=row["name_pl"], name_en=row["name_en"],
        unit_type=row["unit_type"], active=bool(int(row["active"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
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
    keys = row.keys() if hasattr(row, "keys") else []
    return ProductLocal(
        product_code     = row["product_code"],
        hs_code_override = row["hs_code_override"],
        unit_override    = row["unit_override"],
        design_code_link = row["design_code_link"],
        notes            = row["notes"],
        # Phase 4 — origin_country: fall back to 'IN' if column absent
        origin_country   = (row["origin_country"] if "origin_country" in keys else "IN") or "IN",
        created_at       = row["created_at"],
        updated_at       = row["updated_at"],
        # Phase 4B Wave 4 — soft-delete (tolerant of legacy rows → active).
        active           = (bool(int(row["active"])) if "active" in keys
                            and row["active"] is not None else True),
        deleted_at       = (row["deleted_at"] if "deleted_at" in keys else None),
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
        # Phase 4 — origin_country; default 'IN' when not supplied
        "origin_country":   (_clean(data.get("origin_country")) or "IN"),
    }
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        existing = conn.execute("SELECT 1 FROM product_local WHERE product_code=?",
                                (payload["product_code"],)).fetchone()
        if existing:
            conn.execute(
                """UPDATE product_local SET hs_code_override=?, unit_override=?,
                   design_code_link=?, notes=?, origin_country=?, updated_at=?
                   WHERE product_code=?""",
                (payload["hs_code_override"], payload["unit_override"],
                 payload["design_code_link"], payload["notes"],
                 payload["origin_country"], now,
                 payload["product_code"]))
        else:
            conn.execute(
                """INSERT INTO product_local (product_code, hs_code_override,
                   unit_override, design_code_link, notes, origin_country,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (payload["product_code"], payload["hs_code_override"],
                 payload["unit_override"], payload["design_code_link"],
                 payload["notes"], payload["origin_country"], now, now))
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


def list_product_local(db_path: Path, *, active: Optional[bool] = None,
                       limit: int = 500) -> List[ProductLocal]:
    """List product_local overlays.

    Phase 4B Wave 4: ``active`` filter — None=no filter (all); True=active
    only; False=soft-deleted only. The route layer applies its own default
    (active-only when the query param is omitted).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where = ""
    params: List[Any] = []
    if active is not None:
        where = " WHERE active = ?"
        params.append(1 if active else 0)
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT * FROM product_local{where} "
                "ORDER BY updated_at DESC, product_code ASC LIMIT ?",
                params,
            ).fetchall()
            return [_row_to_pl(r) for r in rows]
        except sqlite3.OperationalError:
            # Legacy DB without the active column: fall back to no filter.
            try:
                rows = conn.execute(
                    "SELECT * FROM product_local "
                    "ORDER BY updated_at DESC, product_code ASC LIMIT ?",
                    (int(limit),)).fetchall()
                return [_row_to_pl(r) for r in rows]
            except sqlite3.OperationalError:
                return []


def delete_product_local(db_path: Path, product_code: str) -> bool:
    """Hard delete primitive. The route layer chooses soft (default) vs hard."""
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


# ── Phase 4B Wave 4 — product_local soft-delete + restore ───────────────────
#
# Inactive overlay = "stop applying overlay". Pure-local; no wFirma / PZ /
# customs side effects. Consumers (proforma_draft_sync, routes_proforma,
# proforma_intelligence) skip inactive overlays and fall back.

def soft_delete_product_local(db_path: Path, product_code: str) -> bool:
    return _soft_delete_by_pk(db_path, "product_local", "product_code", product_code)

def restore_product_local(db_path: Path, product_code: str) -> bool:
    return _restore_by_pk(db_path, "product_local", "product_code", product_code)

def hard_delete_product_local(db_path: Path, product_code: str) -> bool:
    return delete_product_local(db_path, product_code)


# ── B-MD2 Designs master (MDOC-2026-05) ───────────────────────────────────────
#
# Soft references only — no SQL FK constraint. ``product_identity_engine``
# MUST NOT read this table; this isolation is pinned by a source-grep
# contract in test_master_data_hard_rules.py.

def validate_design(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    code = _clean(data.get("design_code"))
    if not code:
        errs.append("design_code is required")
    elif not _DESIGN_CODE_RE.match(code):
        errs.append(
            "design_code must be 1-64 chars of letters/digits/_-./, "
            "starting with letter or digit"
        )
    # hs_code is optional; if present, follow the same shape as hs_codes table
    hs = _clean(data.get("hs_code"))
    if hs and not _HS_CODE_RE.match(hs):
        errs.append("hs_code (when set) must be 4-12 digits")
    return errs


def _row_to_design(row: sqlite3.Row) -> Design:
    keys = row.keys() if hasattr(row, "keys") else []
    return Design(
        design_code   = row["design_code"],
        display_name  = row["display_name"],
        product_ref   = row["product_ref"],
        design_family = row["design_family"],
        collection    = row["collection"],
        metal         = row["metal"],
        stone_summary = row["stone_summary"],
        hs_code       = row["hs_code"],
        unit          = row["unit"],
        active        = bool(row["active"]),
        notes         = row["notes"],
        created_at    = row["created_at"],
        updated_at    = row["updated_at"],
        deleted_at    = (row["deleted_at"] if "deleted_at" in keys else None),
    )


def upsert_design(db_path: Path, data: Dict[str, Any]) -> Design:
    """Insert or update a design record by design_code.

    ⚠  PARTIAL-UPDATE SEMANTICS (CAMPAIGN 6 T5):
    On UPDATE, only fields explicitly present in `data` are written.
    Fields absent from `data` are left unchanged in the DB (no NULL-wipe).
    This is safe for partial dashboard edits (e.g., editing only hs_code
    without resetting stone_summary).

    On INSERT, all fields default to None for missing keys.
    """
    errs = validate_design(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    now = _now()
    # Build INSERT payload with all fields (None for missing = correct for new rows).
    p = {
        "design_code":   _clean(data.get("design_code")),
        "display_name":  _clean(data.get("display_name")),
        "product_ref":   _clean(data.get("product_ref")),
        "design_family": _clean(data.get("design_family")),
        "collection":    _clean(data.get("collection")),
        "metal":         _clean(data.get("metal")),
        "stone_summary": _clean(data.get("stone_summary")),
        "hs_code":       _clean(data.get("hs_code")),
        "unit":          _clean(data.get("unit")),
        "active":        1 if (data.get("active", True) is not False
                               and str(data.get("active", "true")).lower()
                               not in ("false", "0", "no")) else 0,
        "notes":         _clean(data.get("notes")),
    }
    # Build UPDATE payload — only fields present in `data` to avoid NULL-wipe.
    _UPDATABLE = {"display_name", "product_ref", "design_family", "collection",
                  "metal", "stone_summary", "hs_code", "unit", "active", "notes"}
    update_p: Dict[str, Any] = {}
    for k in _UPDATABLE:
        if k in data:
            update_p[k] = p[k]
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT created_at FROM designs WHERE design_code=?",
            (p["design_code"],),
        ).fetchone()
        if existing:
            if update_p:
                set_clause = ", ".join(f"{k}=?" for k in update_p)
                conn.execute(
                    f"UPDATE designs SET {set_clause}, updated_at=? WHERE design_code=?",
                    (*update_p.values(), now, p["design_code"]),
                )
        else:
            conn.execute(
                """INSERT INTO designs (design_code, display_name, product_ref,
                                         design_family, collection, metal,
                                         stone_summary, hs_code, unit, active,
                                         notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["design_code"], p["display_name"], p["product_ref"],
                 p["design_family"], p["collection"], p["metal"],
                 p["stone_summary"], p["hs_code"], p["unit"], p["active"],
                 p["notes"], now, now),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM designs WHERE design_code=?", (p["design_code"],)
        ).fetchone()
    return _row_to_design(row)


def get_design(db_path: Path, design_code: str) -> Optional[Design]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM designs WHERE design_code=?", (design_code,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_design(row) if row else None


def list_designs(db_path: Path, *, active: Optional[bool] = None,
                 design_family: Optional[str] = None,
                 collection: Optional[str] = None,
                 limit: int = 500) -> List[Design]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where, params = [], []
    if active is not None:
        where.append("active=?")
        params.append(1 if active else 0)
    if design_family:
        where.append("design_family=?")
        params.append(design_family)
    if collection:
        where.append("collection=?")
        params.append(collection)
    sql = "SELECT * FROM designs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY design_code ASC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [_row_to_design(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []


def delete_design(db_path: Path, design_code: str) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute(
                "DELETE FROM designs WHERE design_code=?", (design_code,),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── BoxTypes (Phase D — outbound label packaging catalogue) ──────────────────

@dataclass
class BoxType:
    """One row in box_types — operator-maintained packaging catalogue."""
    code:            str
    name:            Optional[str] = None
    length_cm:       Optional[float] = None
    width_cm:        Optional[float] = None
    height_cm:       Optional[float] = None
    tare_weight_kg:  Optional[float] = None
    active:          bool = True
    notes:           Optional[str] = None
    id:              Optional[int] = None
    created_at:      Optional[str] = None
    updated_at:      Optional[str] = None


def _row_to_box_type(row: sqlite3.Row) -> BoxType:
    keys = row.keys() if hasattr(row, "keys") else []
    def _f(k: str) -> Optional[float]:
        v = row[k] if k in keys else None
        return float(v) if v is not None else None
    return BoxType(
        id             = row["id"]   if "id"   in keys else None,
        code           = row["code"] if "code" in keys else "",
        name           = row["name"] if "name" in keys else None,
        length_cm      = _f("length_cm"),
        width_cm       = _f("width_cm"),
        height_cm      = _f("height_cm"),
        tare_weight_kg = _f("tare_weight_kg"),
        active         = bool(row["active"]) if "active" in keys else True,
        notes          = row["notes"] if "notes" in keys else None,
        created_at     = row["created_at"] if "created_at" in keys else None,
        updated_at     = row["updated_at"] if "updated_at" in keys else None,
    )


def get_box_type(db_path: Path, box_type_id: int) -> Optional[BoxType]:
    """Fetch a box_type row by primary key. Returns None if absent."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM box_types WHERE id=? AND active=1",
            (int(box_type_id),),
        ).fetchone()
    return _row_to_box_type(row) if row else None


def get_box_type_by_code(db_path: Path, code: str) -> Optional[BoxType]:
    """Fetch a box_type row by code. Returns None if absent or inactive."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM box_types WHERE code=? AND active=1",
            (code,),
        ).fetchone()
    return _row_to_box_type(row) if row else None


def list_box_types(db_path: Path, *, active: Optional[bool] = True,
                   limit: int = 200) -> List[BoxType]:
    """List all box_types, optionally filtered by active state."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if active is None:
            rows = conn.execute(
                "SELECT * FROM box_types ORDER BY code ASC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM box_types WHERE active=? ORDER BY code ASC LIMIT ?",
                (int(active), limit),
            ).fetchall()
    return [_row_to_box_type(r) for r in rows]


def upsert_box_type(db_path: Path, data: Dict[str, Any]) -> BoxType:
    """Insert or update a box_type row. Returns the resulting row."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    code = _clean(data.get("code"))
    if not code:
        raise ValueError("box_type code is required")
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM box_types WHERE code=?", (code,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE box_types SET name=?, length_cm=?, width_cm=?, height_cm=?,
                   tare_weight_kg=?, active=?, notes=?, updated_at=? WHERE code=?""",
                (
                    _clean(data.get("name")),
                    data.get("length_cm"),
                    data.get("width_cm"),
                    data.get("height_cm"),
                    data.get("tare_weight_kg"),
                    1 if data.get("active", True) else 0,
                    _clean(data.get("notes")),
                    now,
                    code,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO box_types
                   (code, name, length_cm, width_cm, height_cm, tare_weight_kg,
                    active, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    code,
                    _clean(data.get("name")),
                    data.get("length_cm"),
                    data.get("width_cm"),
                    data.get("height_cm"),
                    data.get("tare_weight_kg"),
                    1 if data.get("active", True) else 0,
                    _clean(data.get("notes")),
                    now, now,
                ),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM box_types WHERE code=?", (code,)
        ).fetchone()
    return _row_to_box_type(row)


# ── CompanyProfile (Phase 7 — commercial document platform) ──────────────────

@dataclass
class CompanyProfile:
    # Identity
    legal_name:        str
    short_name:        Optional[str] = None
    street:            Optional[str] = None
    postal_city:       Optional[str] = None
    country:           str           = "PL"
    nip:               Optional[str] = None
    vat_eu:            Optional[str] = None
    regon:             Optional[str] = None
    # Contact
    email:             Optional[str] = None
    phone:             Optional[str] = None
    # Bank — Estrella as payee
    iban_eur:          Optional[str] = None
    iban_usd:          Optional[str] = None
    iban_pln:          Optional[str] = None
    swift:             Optional[str] = None
    bank_name:         Optional[str] = None
    # Legal boilerplate
    place_of_issue:    Optional[str] = None
    signatory_name:    Optional[str] = None
    signatory_title:   Optional[str] = None
    returns_policy_pl: Optional[str] = None
    gdpr_text_pl:      Optional[str] = None
    # Legal identifiers (Phase D — additive)
    krs:               Optional[str] = None   # KRS registration number (PL)
    eori:              Optional[str] = None   # EORI customs identifier (EU)
    # Meta
    updated_at:        Optional[str] = None


def _row_to_company_profile(row: sqlite3.Row) -> "CompanyProfile":
    return CompanyProfile(
        legal_name        = row["legal_name"],
        short_name        = row["short_name"],
        street            = row["street"],
        postal_city       = row["postal_city"],
        country           = row["country"] or "PL",
        nip               = row["nip"],
        vat_eu            = row["vat_eu"],
        regon             = row["regon"],
        email             = row["email"],
        phone             = row["phone"],
        iban_eur          = row["iban_eur"],
        iban_usd          = row["iban_usd"],
        iban_pln          = row["iban_pln"],
        swift             = row["swift"],
        bank_name         = row["bank_name"],
        place_of_issue    = row["place_of_issue"],
        signatory_name    = row["signatory_name"],
        signatory_title   = row["signatory_title"],
        returns_policy_pl = row["returns_policy_pl"],
        gdpr_text_pl      = row["gdpr_text_pl"],
        krs               = row["krs"]  if "krs"  in row.keys() else None,
        eori              = row["eori"] if "eori" in row.keys() else None,
        updated_at        = row["updated_at"],
    )


_COMPANY_PROFILE_COLUMNS = [
    "legal_name", "short_name", "street", "postal_city", "country",
    "nip", "vat_eu", "regon", "email", "phone",
    "iban_eur", "iban_usd", "iban_pln", "swift", "bank_name",
    "place_of_issue", "signatory_name", "signatory_title",
    "returns_policy_pl", "gdpr_text_pl",
    "krs", "eori",  # Phase D — additive (KRS registration, EORI customs id)
    "updated_at",
]


def _ensure_company_profile_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_profile (
            id                INTEGER PRIMARY KEY,
            legal_name        TEXT NOT NULL DEFAULT '',
            short_name        TEXT,
            street            TEXT,
            postal_city       TEXT,
            country           TEXT NOT NULL DEFAULT 'PL',
            nip               TEXT,
            vat_eu            TEXT,
            regon             TEXT,
            email             TEXT,
            phone             TEXT,
            iban_eur          TEXT,
            iban_usd          TEXT,
            iban_pln          TEXT,
            swift             TEXT,
            bank_name         TEXT,
            place_of_issue    TEXT,
            signatory_name    TEXT,
            signatory_title   TEXT,
            returns_policy_pl TEXT,
            gdpr_text_pl      TEXT,
            krs               TEXT,
            eori              TEXT,
            updated_at        TEXT
        )
    """)
    # Additive ALTER for future columns — same pattern as the rest of the file
    for col, col_type in [
        ("short_name",        "TEXT"),
        ("street",            "TEXT"),
        ("postal_city",       "TEXT"),
        ("country",           "TEXT NOT NULL DEFAULT 'PL'"),
        ("nip",               "TEXT"),
        ("vat_eu",            "TEXT"),
        ("regon",             "TEXT"),
        ("email",             "TEXT"),
        ("phone",             "TEXT"),
        ("iban_eur",          "TEXT"),
        ("iban_usd",          "TEXT"),
        ("iban_pln",          "TEXT"),
        ("swift",             "TEXT"),
        ("bank_name",         "TEXT"),
        ("place_of_issue",    "TEXT"),
        ("signatory_name",    "TEXT"),
        ("signatory_title",   "TEXT"),
        ("returns_policy_pl", "TEXT"),
        ("gdpr_text_pl",      "TEXT"),
        ("krs",               "TEXT"),   # Phase D — KRS registration number (PL)
        ("eori",              "TEXT"),   # Phase D — EORI customs identifier (EU)
        ("updated_at",        "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE company_profile ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


def get_company_profile(db_path: Path) -> Optional[CompanyProfile]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            _ensure_company_profile_table(conn)
            row = conn.execute(
                "SELECT * FROM company_profile WHERE id=1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_company_profile(row) if row else None


def upsert_company_profile(db_path: Path, **fields) -> CompanyProfile:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Filter to only known fields (exclude id and updated_at — we set updated_at ourselves)
    allowed = set(_COMPANY_PROFILE_COLUMNS) - {"updated_at"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_company_profile_table(conn)
        existing = conn.execute(
            "SELECT * FROM company_profile WHERE id=1"
        ).fetchone()
        if existing:
            # Merge: start from existing values, overlay with supplied fields
            merged: Dict[str, Any] = {col: existing[col] for col in _COMPANY_PROFILE_COLUMNS}
            merged.update(payload)
        else:
            merged = {col: None for col in _COMPANY_PROFILE_COLUMNS}
            merged["legal_name"] = ""
            merged["country"]    = "PL"
            merged.update(payload)

        cols   = ["id"] + _COMPANY_PROFILE_COLUMNS
        values = [1]    + [merged[c] for c in _COMPANY_PROFILE_COLUMNS]
        placeholders = ", ".join(["?"] * len(cols))
        col_list     = ", ".join(cols)
        conn.execute(
            f"INSERT OR REPLACE INTO company_profile ({col_list}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM company_profile WHERE id=1"
        ).fetchone()
    return _row_to_company_profile(row)


# ════════════════════════════════════════════════════════════════════════════
# Phase 4B Wave 1 — soft-delete + restore primitives for six legacy entities
# ════════════════════════════════════════════════════════════════════════════
#
# Authority: each helper mutates ONLY its own table. Route handlers choose
# between soft-delete (default) and hard-delete (gated by flag + role).
# The legacy ``delete_X`` functions remain hard-delete primitives so callers
# that test the low-level contract continue to work without change.

def _soft_delete_by_pk(db_path: Path, table: str, pk_column: str,
                       pk_value: Any) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            f"UPDATE {table} SET active = 0, deleted_at = ?, updated_at = ? "
            f"WHERE {pk_column} = ?",
            (now, now, pk_value),
        )
        conn.commit()
        return cur.rowcount > 0


def _restore_by_pk(db_path: Path, table: str, pk_column: str,
                   pk_value: Any) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            f"UPDATE {table} SET active = 1, deleted_at = NULL, updated_at = ? "
            f"WHERE {pk_column} = ?",
            (now, pk_value),
        )
        conn.commit()
        return cur.rowcount > 0


# ── HS codes ────────────────────────────────────────────────────────────────
def soft_delete_hs_code(db_path: Path, hs_code: str) -> bool:
    return _soft_delete_by_pk(db_path, "hs_codes", "hs_code", hs_code)

def restore_hs_code(db_path: Path, hs_code: str) -> bool:
    return _restore_by_pk(db_path, "hs_codes", "hs_code", hs_code)

def hard_delete_hs_code(db_path: Path, hs_code: str) -> bool:
    return delete_hs_code(db_path, hs_code)


# ── Units ───────────────────────────────────────────────────────────────────
def soft_delete_unit(db_path: Path, code: str) -> bool:
    return _soft_delete_by_pk(db_path, "units", "code", code)

def restore_unit(db_path: Path, code: str) -> bool:
    return _restore_by_pk(db_path, "units", "code", code)

def hard_delete_unit(db_path: Path, code: str) -> bool:
    return delete_unit(db_path, code)


# ── Incoterms ───────────────────────────────────────────────────────────────
def soft_delete_incoterm(db_path: Path, code: str) -> bool:
    return _soft_delete_by_pk(db_path, "incoterms", "code", code)

def restore_incoterm(db_path: Path, code: str) -> bool:
    return _restore_by_pk(db_path, "incoterms", "code", code)

def hard_delete_incoterm(db_path: Path, code: str) -> bool:
    return delete_incoterm(db_path, code)


# ── VAT config (surrogate id) ──────────────────────────────────────────────
def soft_delete_vat_config(db_path: Path, vat_id: int) -> bool:
    return _soft_delete_by_pk(db_path, "vat_config", "id", int(vat_id))

def restore_vat_config(db_path: Path, vat_id: int) -> bool:
    return _restore_by_pk(db_path, "vat_config", "id", int(vat_id))

def hard_delete_vat_config(db_path: Path, vat_id: int) -> bool:
    return delete_vat_config(db_path, vat_id)


# ── FX rates (surrogate id) ────────────────────────────────────────────────
def soft_delete_fx_rate(db_path: Path, fx_id: int) -> bool:
    return _soft_delete_by_pk(db_path, "fx_rates", "id", int(fx_id))

def restore_fx_rate(db_path: Path, fx_id: int) -> bool:
    return _restore_by_pk(db_path, "fx_rates", "id", int(fx_id))

def hard_delete_fx_rate(db_path: Path, fx_id: int) -> bool:
    return delete_fx_rate(db_path, fx_id)


# ── Designs ─────────────────────────────────────────────────────────────────
def soft_delete_design(db_path: Path, design_code: str) -> bool:
    return _soft_delete_by_pk(db_path, "designs", "design_code", design_code)

def restore_design(db_path: Path, design_code: str) -> bool:
    return _restore_by_pk(db_path, "designs", "design_code", design_code)

def hard_delete_design(db_path: Path, design_code: str) -> bool:
    return delete_design(db_path, design_code)


# ── Carriers config (Phase 4B Wave 3a) ──────────────────────────────────────
def soft_delete_carrier_config(db_path: Path, carrier_code: str) -> bool:
    return _soft_delete_by_pk(db_path, "carriers_config", "carrier_code", carrier_code)

def restore_carrier_config(db_path: Path, carrier_code: str) -> bool:
    return _restore_by_pk(db_path, "carriers_config", "carrier_code", carrier_code)

def hard_delete_carrier_config(db_path: Path, carrier_code: str) -> bool:
    return delete_carrier_config(db_path, carrier_code)
