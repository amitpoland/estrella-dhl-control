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
    preferred_payment_method:      Optional[str] = None      # wFirma payment method: transfer|cash|card|compensation
    vat_mode:                      Optional[int] = None      # 222 | 228 | 229

    # Freight defaults
    freight_service_id:      Optional[str] = "13002743"   # wFirma good_id (Fedex Courier)
    freight_last_amount:     Optional[Decimal] = None
    freight_avg_amount:      Optional[Decimal] = None
    freight_currency:        Optional[str] = None
    freight_mode:            Optional[str] = None         # fixed | variable | manual | no_data

    # Freight — currency-safe standing amounts (PR 2C.3a)
    # EUR draft → freight_fixed_amount_eur.  USD draft → freight_fixed_amount_usd.
    # No cross-currency fallback.  2D reads freight_service_id as wFirma invoicecontent good_id.
    freight_fixed_amount_eur: Optional[Decimal] = None
    freight_fixed_amount_usd: Optional[Decimal] = None
    freight_label_pl:         Optional[str] = None        # Polish billing label
    freight_label_en:         Optional[str] = None        # English billing label

    # Insurance defaults
    insurance_service_id:    Optional[str] = "13102217"   # wFirma good_id
    insurance_min_amount:    Optional[Decimal] = None     # auto-detected min (legacy)
    insurance_min_override:  Optional[Decimal] = None     # operator override beats _amount (legacy)
    insurance_rate:          Optional[Decimal] = Decimal("0.0035")
    insurance_mode:          Optional[str] = None         # fixed | formula | manual | no_data

    # Insurance — currency-safe amounts (PR 2C.3a)
    # EUR draft → insurance_min_eur / insurance_fixed_amount_eur.
    # USD draft → insurance_min_usd / insurance_fixed_amount_usd.
    # No cross-currency fallback.  2D reads insurance_service_id as wFirma invoicecontent good_id.
    insurance_fixed_amount_eur: Optional[Decimal] = None
    insurance_fixed_amount_usd: Optional[Decimal] = None
    insurance_min_eur:          Optional[Decimal] = None  # formula floor for EUR drafts
    insurance_min_usd:          Optional[Decimal] = None  # formula floor for USD drafts
    insurance_label_pl:         Optional[str] = None      # Polish billing label
    insurance_label_en:         Optional[str] = None      # English billing label
    insurance_enabled:          bool = True               # False → suggest-insurance returns blocked

    # Credit / Kuke (stored only — Layer 1 does NOT enforce)
    credit_limit:            Optional[Decimal] = None
    credit_currency:         Optional[str] = None
    kuke_approved:           Optional[bool] = None
    kuke_limit:              Optional[Decimal] = None
    kuke_currency:           Optional[str] = None
    kuke_expiry_date:        Optional[str] = None      # ISO date
    risk_status:             Optional[str] = None      # e.g. "low","medium","high","blocked"
    kuke_policy_number:      Optional[str] = None
    kuke_self_retention_pct: Optional[Decimal] = None  # 0–100
    payment_terms_days:      Optional[int] = None      # ≥ 0

    # KYC / Compliance (operator-managed; no AML integration in Layer 1)
    kyc_status:              Optional[str] = None      # approved|pending|review|rejected
    kyc_approved_on:         Optional[str] = None      # ISO date
    kyc_expiry:              Optional[str] = None      # ISO date
    beneficial_owner:        Optional[str] = None
    owner_id_type:           Optional[str] = None      # passport|id_card|drivers_license
    owner_id_number:         Optional[str] = None
    aml_risk_rating:         Optional[str] = None      # low|medium|high
    pep_check_result:        Optional[str] = None      # clear|flagged|pending
    compliance_notes:        Optional[str] = None

    # Audit
    notes:                   Optional[str] = None
    id:                      Optional[int] = None
    created_at:              Optional[str] = None
    updated_at:              Optional[str] = None

    # B0 (MDOC-cache) 2026-05-16 — wFirma enrichment fields. Operator-facing
    # billing contact info (distinct from ship_to_*). Filled-when-empty by
    # the identity-only upsert; never overwrites operator-entered values.
    bill_to_email:           Optional[str] = None
    bill_to_phone:           Optional[str] = None
    bill_to_mobile:          Optional[str] = None
    bank_account:            Optional[str] = None    # IBAN / account_payments
    last_wfirma_sync_at:     Optional[str] = None    # ISO timestamp of last apply
    wfirma_sync_source:      Optional[str] = None    # "review_assign" | "manual" | "auto"

    # B0 deep-enrichment 2026-05-17 — wFirma billing address (verified in
    # live <contractor> response for id 75483443). Filled-when-empty.
    bill_to_street:          Optional[str] = None
    bill_to_city:            Optional[str] = None
    bill_to_postal_code:     Optional[str] = None
    regon:                   Optional[str] = None    # Polish REGON; often empty in wFirma
    # Operator-entered profile fields. wFirma does NOT carry these — the
    # columns are wired so the dashboard can drop the BACKEND PENDING badge.
    short_code:              Optional[str] = None
    client_type:             Optional[str] = None    # e.g. "client" | "supplier" | "both"
    industry:                Optional[str] = None
    eori:                    Optional[str] = None


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
    if c.kuke_approved is True and c.kuke_limit is None:
        blockers.append("kuke_approved=True requires kuke_limit to be set")
    # KUKE extras
    if c.kuke_self_retention_pct is not None:
        pct = Decimal(c.kuke_self_retention_pct)
        if pct < 0 or pct > 100:
            blockers.append(f"kuke_self_retention_pct must be between 0 and 100, got {pct}")
    if c.payment_terms_days is not None and c.payment_terms_days < 0:
        blockers.append(f"payment_terms_days must be >= 0, got {c.payment_terms_days}")
    # KYC / Compliance enum checks
    _KYC_STATUS    = {"approved", "pending", "review", "rejected"}
    _OWNER_ID_TYPE = {"passport", "id_card", "drivers_license"}
    _AML_RATING    = {"low", "medium", "high"}
    _PEP_RESULT    = {"clear", "flagged", "pending"}
    if c.kyc_status and c.kyc_status not in _KYC_STATUS:
        blockers.append(
            f"kyc_status must be one of {sorted(_KYC_STATUS)}, got {c.kyc_status!r}")
    if c.owner_id_type and c.owner_id_type not in _OWNER_ID_TYPE:
        blockers.append(
            f"owner_id_type must be one of {sorted(_OWNER_ID_TYPE)}, got {c.owner_id_type!r}")
    if c.aml_risk_rating and c.aml_risk_rating not in _AML_RATING:
        blockers.append(
            f"aml_risk_rating must be one of {sorted(_AML_RATING)}, got {c.aml_risk_rating!r}")
    if c.pep_check_result and c.pep_check_result not in _PEP_RESULT:
        blockers.append(
            f"pep_check_result must be one of {sorted(_PEP_RESULT)}, got {c.pep_check_result!r}")
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
    # PR 2C.3a: currency-safe amounts must be positive (> 0) if set
    for label, value in (
        ("freight_fixed_amount_eur",   c.freight_fixed_amount_eur),
        ("freight_fixed_amount_usd",   c.freight_fixed_amount_usd),
        ("insurance_fixed_amount_eur", c.insurance_fixed_amount_eur),
        ("insurance_fixed_amount_usd", c.insurance_fixed_amount_usd),
        ("insurance_min_eur",          c.insurance_min_eur),
        ("insurance_min_usd",          c.insurance_min_usd),
    ):
        if value is not None and Decimal(value) <= 0:
            blockers.append(f"{label} must be > 0, got {value}")
    # Service IDs must be non-empty strings if provided
    if c.freight_service_id is not None and not str(c.freight_service_id).strip():
        blockers.append("freight_service_id must be a non-empty string if provided")
    if c.insurance_service_id is not None and not str(c.insurance_service_id).strip():
        blockers.append("insurance_service_id must be a non-empty string if provided")
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
                preferred_payment_method       TEXT,
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
                kuke_policy_number       TEXT,
                kuke_self_retention_pct  TEXT,
                payment_terms_days       INTEGER,
                kyc_status               TEXT,
                kyc_approved_on          TEXT,
                kyc_expiry               TEXT,
                beneficial_owner         TEXT,
                owner_id_type            TEXT,
                owner_id_number          TEXT,
                aml_risk_rating          TEXT,
                pep_check_result         TEXT,
                compliance_notes         TEXT,

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
            # PR 2C.3a — currency-safe freight/insurance standing amounts
            ("freight_fixed_amount_eur",   "TEXT"),
            ("freight_fixed_amount_usd",   "TEXT"),
            ("freight_label_pl",           "TEXT"),
            ("freight_label_en",           "TEXT"),
            ("insurance_fixed_amount_eur", "TEXT"),
            ("insurance_fixed_amount_usd", "TEXT"),
            ("insurance_min_eur",          "TEXT"),
            ("insurance_min_usd",          "TEXT"),
            ("insurance_label_pl",         "TEXT"),
            ("insurance_label_en",         "TEXT"),
            ("insurance_enabled",          "INTEGER NOT NULL DEFAULT 1"),
            # MasterData-2 — KUKE extras + KYC/Compliance
            ("kuke_policy_number",        "TEXT"),
            ("kuke_self_retention_pct",   "TEXT"),
            ("payment_terms_days",        "INTEGER"),
            ("kyc_status",                "TEXT"),
            ("kyc_approved_on",           "TEXT"),
            ("kyc_expiry",                "TEXT"),
            ("beneficial_owner",          "TEXT"),
            ("owner_id_type",             "TEXT"),
            ("owner_id_number",           "TEXT"),
            ("aml_risk_rating",           "TEXT"),
            ("pep_check_result",          "TEXT"),
            ("compliance_notes",          "TEXT"),
            # B0 (MDOC-cache) 2026-05-16 — wFirma enrichment fields
            ("bill_to_email",             "TEXT"),
            ("bill_to_phone",             "TEXT"),
            ("bill_to_mobile",            "TEXT"),
            ("bank_account",              "TEXT"),
            ("last_wfirma_sync_at",       "TEXT"),
            ("wfirma_sync_source",        "TEXT"),
            # B0 deep-enrichment 2026-05-17 — wFirma billing address +
            # operator-entered profile fields
            ("bill_to_street",            "TEXT"),
            ("bill_to_city",              "TEXT"),
            ("bill_to_postal_code",       "TEXT"),
            ("regon",                     "TEXT"),
            ("short_code",                "TEXT"),
            ("client_type",               "TEXT"),
            ("industry",                  "TEXT"),
            ("eori",                      "TEXT"),
            # B2a — wFirma payment method default
            ("preferred_payment_method",  "TEXT"),
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
        preferred_payment_method      = _row_get(row, "preferred_payment_method"),
        vat_mode                      = _row_get(row, "vat_mode"),
        freight_service_id            = _row_get(row, "freight_service_id", "13002743"),
        freight_last_amount           = _str_to_dec(_row_get(row, "freight_last_amount")),
        freight_avg_amount            = _str_to_dec(_row_get(row, "freight_avg_amount")),
        freight_currency              = _row_get(row, "freight_currency"),
        freight_mode                  = _row_get(row, "freight_mode"),
        freight_fixed_amount_eur      = _str_to_dec(_row_get(row, "freight_fixed_amount_eur")),
        freight_fixed_amount_usd      = _str_to_dec(_row_get(row, "freight_fixed_amount_usd")),
        freight_label_pl              = _row_get(row, "freight_label_pl"),
        freight_label_en              = _row_get(row, "freight_label_en"),
        insurance_service_id          = _row_get(row, "insurance_service_id", "13102217"),
        insurance_min_amount          = _str_to_dec(_row_get(row, "insurance_min_amount")),
        insurance_min_override        = _str_to_dec(row["insurance_min_override"]),
        insurance_rate                = _str_to_dec(_row_get(row, "insurance_rate")) or Decimal("0.0035"),
        insurance_mode                = _row_get(row, "insurance_mode"),
        insurance_fixed_amount_eur    = _str_to_dec(_row_get(row, "insurance_fixed_amount_eur")),
        insurance_fixed_amount_usd    = _str_to_dec(_row_get(row, "insurance_fixed_amount_usd")),
        insurance_min_eur             = _str_to_dec(_row_get(row, "insurance_min_eur")),
        insurance_min_usd             = _str_to_dec(_row_get(row, "insurance_min_usd")),
        insurance_label_pl            = _row_get(row, "insurance_label_pl"),
        insurance_label_en            = _row_get(row, "insurance_label_en"),
        insurance_enabled             = bool(int(_row_get(row, "insurance_enabled", 1))),
        credit_limit                  = _str_to_dec(row["credit_limit"]),
        credit_currency               = row["credit_currency"],
        kuke_approved                 = _to_bool(row["kuke_approved"]),
        kuke_limit                    = _str_to_dec(row["kuke_limit"]),
        kuke_currency                 = row["kuke_currency"],
        kuke_expiry_date              = row["kuke_expiry_date"],
        risk_status                   = row["risk_status"],
        kuke_policy_number            = _row_get(row, "kuke_policy_number"),
        kuke_self_retention_pct       = _str_to_dec(_row_get(row, "kuke_self_retention_pct")),
        payment_terms_days            = _row_get(row, "payment_terms_days"),
        kyc_status                    = _row_get(row, "kyc_status"),
        kyc_approved_on               = _row_get(row, "kyc_approved_on"),
        kyc_expiry                    = _row_get(row, "kyc_expiry"),
        beneficial_owner              = _row_get(row, "beneficial_owner"),
        owner_id_type                 = _row_get(row, "owner_id_type"),
        owner_id_number               = _row_get(row, "owner_id_number"),
        aml_risk_rating               = _row_get(row, "aml_risk_rating"),
        pep_check_result              = _row_get(row, "pep_check_result"),
        compliance_notes              = _row_get(row, "compliance_notes"),
        notes                         = row["notes"],
        created_at                    = row["created_at"],
        updated_at                    = row["updated_at"],
        # B0 enrichment fields
        bill_to_email                 = _row_get(row, "bill_to_email"),
        bill_to_phone                 = _row_get(row, "bill_to_phone"),
        bill_to_mobile                = _row_get(row, "bill_to_mobile"),
        bank_account                  = _row_get(row, "bank_account"),
        last_wfirma_sync_at           = _row_get(row, "last_wfirma_sync_at"),
        wfirma_sync_source            = _row_get(row, "wfirma_sync_source"),
        # B0 deep-enrichment 2026-05-17
        bill_to_street                = _row_get(row, "bill_to_street"),
        bill_to_city                  = _row_get(row, "bill_to_city"),
        bill_to_postal_code           = _row_get(row, "bill_to_postal_code"),
        regon                         = _row_get(row, "regon"),
        short_code                    = _row_get(row, "short_code"),
        client_type                   = _row_get(row, "client_type"),
        industry                      = _row_get(row, "industry"),
        eori                          = _row_get(row, "eori"),
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def upsert_customer(db_path: Path, c: CustomerMaster) -> int:
    """Insert or update by bill_to_contractor_id. Returns row id.

    ⚠  FULL-SET SEMANTICS (CAMPAIGN 6 T5 NOTE):
    This function performs a full UPDATE — every payload field is written,
    including None/NULL values.  The caller MUST supply ALL fields, either
    from the operator form (which shows all fields) or from a prior GET.

    Requirement: the API route that calls this function must read the stored
    record first (GET), merge with the operator edits, and PUT the complete
    merged object — never a partial payload.  A partial PUT silently wipes
    unincluded optional fields (kuke_limit, credit_limit, freight_service_id,
    etc.) to NULL.

    For wFirma-initiated writes, use upsert_identity_only() which uses
    COALESCE semantics (fill-when-empty, never wipe).
    """
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
        "preferred_payment_method":     c.preferred_payment_method,
        "vat_mode":                     int(c.vat_mode) if c.vat_mode is not None else None,
        "freight_service_id":           c.freight_service_id,
        "freight_last_amount":          _dec_to_str(c.freight_last_amount),
        "freight_avg_amount":           _dec_to_str(c.freight_avg_amount),
        "freight_currency":             c.freight_currency,
        "freight_mode":                 c.freight_mode,
        "freight_fixed_amount_eur":     _dec_to_str(c.freight_fixed_amount_eur),
        "freight_fixed_amount_usd":     _dec_to_str(c.freight_fixed_amount_usd),
        "freight_label_pl":             c.freight_label_pl,
        "freight_label_en":             c.freight_label_en,
        "insurance_service_id":         c.insurance_service_id,
        "insurance_min_amount":         _dec_to_str(c.insurance_min_amount),
        "insurance_min_override":       _dec_to_str(c.insurance_min_override),
        "insurance_rate":               _dec_to_str(c.insurance_rate),
        "insurance_mode":               c.insurance_mode,
        "insurance_fixed_amount_eur":   _dec_to_str(c.insurance_fixed_amount_eur),
        "insurance_fixed_amount_usd":   _dec_to_str(c.insurance_fixed_amount_usd),
        "insurance_min_eur":            _dec_to_str(c.insurance_min_eur),
        "insurance_min_usd":            _dec_to_str(c.insurance_min_usd),
        "insurance_label_pl":           c.insurance_label_pl,
        "insurance_label_en":           c.insurance_label_en,
        "insurance_enabled":            1 if c.insurance_enabled else 0,
        "credit_limit":                 _dec_to_str(c.credit_limit),
        "credit_currency":              c.credit_currency,
        "kuke_approved":                _to_int(c.kuke_approved),
        "kuke_limit":                   _dec_to_str(c.kuke_limit),
        "kuke_currency":                c.kuke_currency,
        "kuke_expiry_date":             c.kuke_expiry_date,
        "risk_status":                  c.risk_status,
        "kuke_policy_number":           c.kuke_policy_number,
        "kuke_self_retention_pct":      _dec_to_str(c.kuke_self_retention_pct),
        "payment_terms_days":           int(c.payment_terms_days) if c.payment_terms_days is not None else None,
        "kyc_status":                   c.kyc_status,
        "kyc_approved_on":              c.kyc_approved_on,
        "kyc_expiry":                   c.kyc_expiry,
        "beneficial_owner":             c.beneficial_owner,
        "owner_id_type":                c.owner_id_type,
        "owner_id_number":              c.owner_id_number,
        "aml_risk_rating":              c.aml_risk_rating,
        "pep_check_result":             c.pep_check_result,
        "compliance_notes":             c.compliance_notes,
        "notes":                        c.notes,
        # ── B0 operator-entered enrichment fields (added 2026-05-19) ──────────
        # These were present in the CustomerMaster dataclass, returned by GET,
        # loaded into the dashboard form, and editable by the operator — but
        # were NOT in the original upsert_customer payload.  Any Save from the
        # dashboard silently discarded operator edits.  Fixed here.
        # upsert_identity_only() (wFirma sync path) handles these with COALESCE
        # semantics; upsert_customer() (operator Save path) now writes them
        # directly — operator value wins on explicit Save.
        "bill_to_email":               c.bill_to_email,
        "bill_to_phone":               c.bill_to_phone,
        "bill_to_mobile":              c.bill_to_mobile,
        "bill_to_street":              c.bill_to_street,
        "bill_to_city":                c.bill_to_city,
        "bill_to_postal_code":         c.bill_to_postal_code,
        "regon":                       c.regon,
        "short_code":                  c.short_code,
        "client_type":                 c.client_type,
        "industry":                    c.industry,
        "eori":                        c.eori,
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


def upsert_identity_only(
    db_path: Path,
    *,
    bill_to_contractor_id: str,
    bill_to_name:          str,
    country:               str,
    nip:                   Optional[str] = None,
    # B0 enrichment — opportunistic fill-when-empty. Every extra field is
    # written via COALESCE(NULLIF(?, ''), col), so operator-entered values
    # are preserved verbatim and only empty local columns are populated.
    bill_to_email:         Optional[str] = None,
    bill_to_phone:         Optional[str] = None,
    bill_to_mobile:        Optional[str] = None,
    bank_account:                  Optional[str] = None,
    default_currency:              Optional[str] = None,
    payment_terms_days:            Optional[int] = None,
    # B0 deep-enrichment 2026-05-16 — wFirma commercial defaults (fill-when-empty)
    default_language_id:           Optional[str] = None,
    preferred_proforma_series_id:  Optional[str] = None,
    preferred_invoice_series_id:   Optional[str] = None,
    # B0 deep-enrichment 2026-05-17 — wFirma billing address (fill-when-empty)
    bill_to_street:                Optional[str] = None,
    bill_to_city:                  Optional[str] = None,
    bill_to_postal_code:           Optional[str] = None,
    regon:                         Optional[str] = None,
    sync_source:           str           = "review_assign",
) -> Dict[str, Any]:
    """B0 (MDOC-cache): wFirma identity-only upsert with enrichment.

    INSERTS a new customer_master row with the minimum required fields, or
    UPDATES the matching row by ``bill_to_contractor_id``.

    ON UPDATE: every column is written via ``COALESCE(NULLIF(?, ''), col)``
    so a non-empty incoming value fills an empty local column, and an empty
    incoming value never blanks an existing value. This guarantees:
      - operator-entered freight / insurance / KYC / KUKE / shipping /
        invoice fields are preserved verbatim (never written here);
      - operator-entered bill_to_email / phone / bank_account are
        preserved if already set;
      - first-time fill from wFirma populates empty fields.

    Required-field validation (``bill_to_contractor_id``, ``bill_to_name``,
    ``country``) runs FIRST so a missing field is rejected cleanly before
    any DB write — no TypeError leak from the dataclass constructor.

    Returns ``{"id", "action", "row"}`` where ``action`` ∈ {"inserted", "updated"}.
    """
    bid = (bill_to_contractor_id or "").strip()
    bnm = (bill_to_name or "").strip()
    cty = (country or "").strip().upper()

    blockers: List[str] = []
    if not bid:
        blockers.append("bill_to_contractor_id is required")
    if not bnm:
        blockers.append("bill_to_name is required")
    if not cty or len(cty) != 2:
        blockers.append("country must be ISO-3166 alpha-2 (2 letters)")
    if blockers:
        raise ValueError("customer_master identity validation failed: " + "; ".join(blockers))

    # Normalise enrichment values.
    email = (bill_to_email or "").strip()
    phone = (bill_to_phone or "").strip()
    mobile = (bill_to_mobile or "").strip()
    bank = (bank_account or "").strip()
    curr = (default_currency or "").strip().upper()
    pterm = payment_terms_days if (payment_terms_days is not None) else None
    lang = (default_language_id or "").strip()
    pro_series = (preferred_proforma_series_id or "").strip()
    inv_series = (preferred_invoice_series_id or "").strip()
    bstreet = (bill_to_street or "").strip()
    bcity   = (bill_to_city or "").strip()
    bzip    = (bill_to_postal_code or "").strip()
    breg    = (regon or "").strip()
    src = (sync_source or "review_assign").strip() or "review_assign"

    init_db(db_path)
    now = _now_iso()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM customer_master WHERE bill_to_contractor_id = ?",
            (bid,),
        ).fetchone()
        if existing is None:
            # INSERT minimum stub + opportunistic enrichment. All other
            # columns left at SQL NULL or table default.
            cur = conn.execute(
                """INSERT INTO customer_master
                       (bill_to_contractor_id, bill_to_name, country, nip,
                        bill_to_email, bill_to_phone, bill_to_mobile,
                        bank_account, default_currency, payment_terms_days,
                        default_language_id,
                        preferred_proforma_series_id,
                        preferred_invoice_series_id,
                        bill_to_street, bill_to_city, bill_to_postal_code,
                        regon,
                        last_wfirma_sync_at, wfirma_sync_source,
                        insurance_enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (bid, bnm, cty, (nip or None),
                 email or None, phone or None, mobile or None,
                 bank or None, curr or None, pterm,
                 lang or None, pro_series or None, inv_series or None,
                 bstreet or None, bcity or None, bzip or None,
                 breg or None,
                 now, src,
                 now, now),
            )
            row_id = int(cur.lastrowid or 0)
            action = "inserted"
        else:
            row_id = int(existing["id"])
            # UPDATE — COALESCE-NULLIF for every column so empty incoming
            # values never blank an existing value. bill_to_name and
            # country are required and always rewritten (operator may want
            # to refresh the official name from wFirma).
            # FILL-WHEN-EMPTY semantics: local non-empty value beats incoming.
            # Order of args inside COALESCE is (local_col, incoming_value):
            # if local is non-NULL it wins; only NULL local cells are
            # backfilled from wFirma. NULLIF strips empty strings so an
            # accidental "" never replaces NULL with empty string.
            #
            # bill_to_name and country are required and ALWAYS rewritten so
            # the operator can refresh the canonical wFirma name. nip uses
            # fill-when-empty so an existing local nip is never overwritten.
            conn.execute(
                """UPDATE customer_master
                       SET bill_to_name        = ?,
                           country             = ?,
                           nip                          = COALESCE(NULLIF(nip, ''),                          NULLIF(?, '')),
                           bill_to_email                = COALESCE(NULLIF(bill_to_email, ''),                 NULLIF(?, '')),
                           bill_to_phone                = COALESCE(NULLIF(bill_to_phone, ''),                 NULLIF(?, '')),
                           bill_to_mobile               = COALESCE(NULLIF(bill_to_mobile, ''),                NULLIF(?, '')),
                           bank_account                 = COALESCE(NULLIF(bank_account, ''),                  NULLIF(?, '')),
                           default_currency             = COALESCE(NULLIF(default_currency, ''),              NULLIF(?, '')),
                           payment_terms_days           = COALESCE(payment_terms_days, ?),
                           default_language_id          = COALESCE(NULLIF(default_language_id, ''),           NULLIF(?, '')),
                           preferred_proforma_series_id = COALESCE(NULLIF(preferred_proforma_series_id, ''), NULLIF(?, '')),
                           preferred_invoice_series_id  = COALESCE(NULLIF(preferred_invoice_series_id, ''),  NULLIF(?, '')),
                           bill_to_street               = COALESCE(NULLIF(bill_to_street, ''),                NULLIF(?, '')),
                           bill_to_city                 = COALESCE(NULLIF(bill_to_city, ''),                  NULLIF(?, '')),
                           bill_to_postal_code          = COALESCE(NULLIF(bill_to_postal_code, ''),           NULLIF(?, '')),
                           regon                        = COALESCE(NULLIF(regon, ''),                         NULLIF(?, '')),
                           last_wfirma_sync_at = ?,
                           wfirma_sync_source  = ?,
                           updated_at          = ?
                       WHERE id = ?""",
                (bnm, cty, (nip or ""),
                 email, phone, mobile, bank, curr, pterm,
                 lang, pro_series, inv_series,
                 bstreet, bcity, bzip, breg,
                 now, src, now, row_id),
            )
            action = "updated"
        conn.commit()
    rec = get_customer(db_path, bid)
    return {"id": row_id, "action": action, "row": rec}


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
    "upsert_identity_only",
    "get_customer",
    "list_customers",
    "delete_customer",
    "get_effective_defaults",
]


# ── B0 deep-enrichment 2026-05-16 — deterministic inheritance helper ─────────
#
# Formalises the precedence order documented in
# tasks/wfirma-enrichment-ownership-model.md. This helper is consumed by the
# operator-facing dashboard (e.g. "what currency will my draft use?") and is
# safe for any future consumer to read. It is NOT yet used by the proforma
# posting path — that is intentional and matches the "no proforma flow change"
# hard rule. When a future PR wants to switch proforma to read from this
# helper, the inheritance order is already locked in code + tested.


def get_effective_defaults(customer: "CustomerMaster") -> Dict[str, Any]:
    """Return the deterministic effective defaults for a Client Master record.

    Precedence (highest first):
      1. Local operator override (non-empty value on the CustomerMaster row).
      2. wFirma-sourced default (filled into the same column by
         ``upsert_identity_only``).
      3. System fallback (None / sentinel — caller decides).

    Levels 1 and 2 share the same DB column because ``upsert_identity_only``
    uses fill-when-empty semantics. The effective value is therefore simply
    the column value — but this helper exists to:
      (a) document the rule in code,
      (b) handle the ship-to inheritance (if ``ship_to_use_alternate`` is
          False, ship-to fields inherit bill-to verbatim),
      (c) give every downstream consumer one shared call site.

    Returns a flat dict; missing fields are None.
    """
    if customer is None:
        return {}
    c = customer

    # Bill-to identity + commercial defaults are direct column reads.
    out: Dict[str, Any] = {
        "bill_to_contractor_id":         c.bill_to_contractor_id,
        "bill_to_name":                  c.bill_to_name,
        "country":                       c.country,
        "nip":                           c.nip,
        "regon":                         c.regon,
        "bill_to_email":                 c.bill_to_email,
        "bill_to_phone":                 c.bill_to_phone,
        "bill_to_mobile":                c.bill_to_mobile,
        "bill_to_street":                c.bill_to_street,
        "bill_to_city":                  c.bill_to_city,
        "bill_to_postal_code":           c.bill_to_postal_code,
        "bank_account":                  c.bank_account,
        "default_currency":              c.default_currency,
        "payment_terms_days":            c.payment_terms_days,
        "default_language_id":           c.default_language_id,
        "preferred_proforma_series_id":  c.preferred_proforma_series_id,
        "preferred_invoice_series_id":   c.preferred_invoice_series_id,
        "vat_mode":                      c.vat_mode,
        "short_code":                    c.short_code,
        "client_type":                   c.client_type,
        "industry":                      c.industry,
        "eori":                          c.eori,
    }

    # Ship-to inheritance. When the operator has NOT enabled the alternate
    # ship-to override, the effective ship-to is the bill-to identity.
    if c.ship_to_use_alternate:
        out["ship_to_use_alternate"] = True
        out["ship_to_name"]    = c.ship_to_name    or c.bill_to_name
        out["ship_to_country"] = c.ship_to_country or c.country
        out["ship_to_email"]   = c.ship_to_email   or c.bill_to_email
        out["ship_to_phone"]   = c.ship_to_phone   or c.bill_to_phone
        out["ship_to_street"]  = c.ship_to_street
        out["ship_to_city"]    = c.ship_to_city
        out["ship_to_zip"]     = c.ship_to_zip
        out["ship_to_person"]  = c.ship_to_person
        out["ship_to_contractor_id"] = c.ship_to_contractor_id
    else:
        # B0 deep-enrichment 2026-05-17 — bill-to address NOW lives in
        # customer_master (bill_to_street / bill_to_city / bill_to_postal_code),
        # so the inherited ship-to surfaces the real address.
        out["ship_to_use_alternate"] = False
        out["ship_to_name"]    = c.bill_to_name
        out["ship_to_country"] = c.country
        out["ship_to_email"]   = c.bill_to_email
        out["ship_to_phone"]   = c.bill_to_phone
        out["ship_to_street"]  = c.bill_to_street
        out["ship_to_city"]    = c.bill_to_city
        out["ship_to_zip"]     = c.bill_to_postal_code
        out["ship_to_person"]  = None
        out["ship_to_contractor_id"] = None

    # Freight + insurance defaults — local-only territory; expose verbatim.
    out["freight_service_id"]        = c.freight_service_id
    out["freight_fixed_amount_eur"]  = c.freight_fixed_amount_eur
    out["freight_fixed_amount_usd"]  = c.freight_fixed_amount_usd
    out["freight_currency"]          = c.freight_currency
    out["freight_mode"]              = c.freight_mode
    out["insurance_service_id"]      = c.insurance_service_id
    out["insurance_rate"]            = c.insurance_rate
    out["insurance_enabled"]         = c.insurance_enabled

    return out
