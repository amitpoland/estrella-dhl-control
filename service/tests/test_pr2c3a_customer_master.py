"""
test_pr2c3a_customer_master.py — PR 2C.3a: currency-safe schema + REST API foundation.

Pins:
  1.  Migration idempotency — new columns added to a legacy DB without
      destroying existing data.
  2.  EUR freight round trip: freight_fixed_amount_eur stores and reads back.
  3.  USD freight round trip: freight_fixed_amount_usd stores and reads back.
  4.  EUR insurance round trip: insurance_fixed_amount_eur + insurance_min_eur.
  5.  USD insurance round trip: insurance_fixed_amount_usd + insurance_min_usd.
  6.  Labels round trip: freight_label_pl/en + insurance_label_pl/en.
  7.  insurance_enabled = False persists and reads back as False.
  8.  insurance_enabled = True by default when not specified.
  9.  validate() rejects currency-safe amounts <= 0.
  10. validate() rejects blank service_id strings.
  11. GET by id: get_customer returns correct record.
  12. PUT create: upsert_customer inserts row with all new fields.
  13. PUT update: upsert_customer overwrites all new fields in-place.
  14. GET list: list_customers includes new fields on returned records.
  15. New fields default to None / True on a minimal legacy-style create.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

import sys

def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

_ensure_path()

from app.services.customer_master_db import (   # noqa: E402
    CustomerMaster,
    delete_customer,
    get_customer,
    init_db,
    list_customers,
    upsert_customer,
    validate,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _minimal(**overrides) -> CustomerMaster:
    base = dict(
        bill_to_contractor_id = "38582303",
        bill_to_name          = "Scandinavian Diamond",
        country               = "NO",
    )
    base.update(overrides)
    return CustomerMaster(**base)


def _with_2c3a(**overrides) -> CustomerMaster:
    """CustomerMaster with a representative set of all 2C.3a fields."""
    base = dict(
        bill_to_contractor_id    = "38582303",
        bill_to_name             = "Scandinavian Diamond",
        country                  = "NO",
        freight_fixed_amount_eur = Decimal("120.00"),
        freight_fixed_amount_usd = Decimal("130.00"),
        freight_label_pl         = "Transport FedEx",
        freight_label_en         = "FedEx Courier",
        insurance_fixed_amount_eur = Decimal("35.00"),
        insurance_fixed_amount_usd = Decimal("38.00"),
        insurance_min_eur          = Decimal("10.00"),
        insurance_min_usd          = Decimal("11.00"),
        insurance_label_pl         = "Ubezpieczenie",
        insurance_label_en         = "Insurance",
        insurance_enabled          = True,
    )
    base.update(overrides)
    return CustomerMaster(**base)


# ── 1. Migration idempotency ─────────────────────────────────────────────────

def test_migration_idempotency_new_columns_on_legacy_db(tmp_path: Path):
    """Running init_db against a DB that already has the old schema silently
    adds the 11 new columns without destroying existing rows."""
    db = tmp_path / "cm_legacy.db"

    # Create the DB with the schema from BEFORE PR 2C.3a.
    # This is the full original CREATE TABLE, PLUS the previously-migrated
    # columns (preferred_*_series_id, vat_mode, freight_mode, etc.) but
    # WITHOUT the 11 new 2C.3a columns (freight_fixed_amount_eur, etc.).
    with sqlite3.connect(str(db)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
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
        conn.execute(
            "INSERT INTO customer_master "
            "(bill_to_contractor_id, bill_to_name, country, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("LEGACY001", "Legacy Customer", "DE", "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        )

    # init_db (which runs _migrate_add_columns) must not error
    init_db(db)

    # Pre-existing row must still be readable
    got = get_customer(db, "LEGACY001")
    assert got is not None
    assert got.bill_to_name == "Legacy Customer"
    assert got.country == "DE"

    # New fields must default to None / True
    assert got.freight_fixed_amount_eur is None
    assert got.freight_fixed_amount_usd is None
    assert got.insurance_fixed_amount_eur is None
    assert got.insurance_min_eur is None
    assert got.freight_label_pl is None
    assert got.insurance_label_en is None
    assert got.insurance_enabled is True   # DEFAULT 1


def test_migration_runs_twice_without_error(tmp_path: Path):
    """Double init_db is safe (idempotency check)."""
    db = tmp_path / "cm.db"
    init_db(db)
    init_db(db)
    assert db.is_file()


# ── 2. EUR freight round trip ────────────────────────────────────────────────

def test_freight_fixed_amount_eur_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    c = _minimal(freight_fixed_amount_eur=Decimal("120.50"))
    upsert_customer(db, c)
    got = get_customer(db, "38582303")
    assert got.freight_fixed_amount_eur == Decimal("120.50")


def test_freight_fixed_amount_eur_null_round_trip(tmp_path: Path):
    """None is stored and read back as None."""
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal())
    got = get_customer(db, "38582303")
    assert got.freight_fixed_amount_eur is None


# ── 3. USD freight round trip ────────────────────────────────────────────────

def test_freight_fixed_amount_usd_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(freight_fixed_amount_usd=Decimal("131.00")))
    got = get_customer(db, "38582303")
    assert got.freight_fixed_amount_usd == Decimal("131.00")


# ── 4. EUR insurance round trip ──────────────────────────────────────────────

def test_insurance_fixed_amount_eur_and_min_eur_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        insurance_fixed_amount_eur = Decimal("35.00"),
        insurance_min_eur          = Decimal("10.00"),
    ))
    got = get_customer(db, "38582303")
    assert got.insurance_fixed_amount_eur == Decimal("35.00")
    assert got.insurance_min_eur          == Decimal("10.00")


# ── 5. USD insurance round trip ──────────────────────────────────────────────

def test_insurance_fixed_amount_usd_and_min_usd_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        insurance_fixed_amount_usd = Decimal("38.50"),
        insurance_min_usd          = Decimal("11.00"),
    ))
    got = get_customer(db, "38582303")
    assert got.insurance_fixed_amount_usd == Decimal("38.50")
    assert got.insurance_min_usd          == Decimal("11.00")


# ── 6. Labels round trip ─────────────────────────────────────────────────────

def test_freight_labels_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        freight_label_pl = "Transport FedEx",
        freight_label_en = "FedEx Courier",
    ))
    got = get_customer(db, "38582303")
    assert got.freight_label_pl == "Transport FedEx"
    assert got.freight_label_en == "FedEx Courier"


def test_insurance_labels_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        insurance_label_pl = "Ubezpieczenie",
        insurance_label_en = "Insurance",
    ))
    got = get_customer(db, "38582303")
    assert got.insurance_label_pl == "Ubezpieczenie"
    assert got.insurance_label_en == "Insurance"


# ── 7. insurance_enabled = False ─────────────────────────────────────────────

def test_insurance_enabled_false_persists(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(insurance_enabled=False))
    got = get_customer(db, "38582303")
    assert got.insurance_enabled is False


# ── 8. insurance_enabled = True (default) ───────────────────────────────────

def test_insurance_enabled_defaults_to_true(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal())   # insurance_enabled not specified → default True
    got = get_customer(db, "38582303")
    assert got.insurance_enabled is True


# ── 9. validate() rejects amounts <= 0 ──────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("freight_fixed_amount_eur",   Decimal("0")),
    ("freight_fixed_amount_eur",   Decimal("-1")),
    ("freight_fixed_amount_usd",   Decimal("0")),
    ("freight_fixed_amount_usd",   Decimal("-5.50")),
    ("insurance_fixed_amount_eur", Decimal("0")),
    ("insurance_fixed_amount_usd", Decimal("-0.01")),
    ("insurance_min_eur",          Decimal("0")),
    ("insurance_min_usd",          Decimal("-10")),
])
def test_validate_rejects_non_positive_currency_amounts(field, value):
    c = _minimal(**{field: value})
    blockers = validate(c)
    assert any(field in b for b in blockers), (
        f"Expected {field!r} to be rejected for value {value!r}, got blockers: {blockers}"
    )


def test_validate_accepts_positive_currency_amounts():
    c = _with_2c3a()
    assert validate(c) == []


# ── 10. validate() rejects blank service_id ──────────────────────────────────

def test_validate_rejects_blank_freight_service_id():
    c = _minimal(freight_service_id="")
    blockers = validate(c)
    assert any("freight_service_id" in b for b in blockers)


def test_validate_rejects_blank_insurance_service_id():
    c = _minimal(insurance_service_id="")
    blockers = validate(c)
    assert any("insurance_service_id" in b for b in blockers)


def test_validate_accepts_none_service_id():
    """None service_id is allowed (not provided — resolver falls back to default)."""
    c = _minimal(freight_service_id=None, insurance_service_id=None)
    assert validate(c) == []


# ── 11. GET by id (get_customer) ─────────────────────────────────────────────

def test_get_customer_returns_all_new_fields(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _with_2c3a())
    got = get_customer(db, "38582303")
    assert got is not None
    assert got.freight_fixed_amount_eur    == Decimal("120.00")
    assert got.freight_fixed_amount_usd    == Decimal("130.00")
    assert got.freight_label_pl            == "Transport FedEx"
    assert got.freight_label_en            == "FedEx Courier"
    assert got.insurance_fixed_amount_eur  == Decimal("35.00")
    assert got.insurance_fixed_amount_usd  == Decimal("38.00")
    assert got.insurance_min_eur           == Decimal("10.00")
    assert got.insurance_min_usd           == Decimal("11.00")
    assert got.insurance_label_pl          == "Ubezpieczenie"
    assert got.insurance_label_en          == "Insurance"
    assert got.insurance_enabled           is True


# ── 12. PUT create ───────────────────────────────────────────────────────────

def test_upsert_creates_row_with_all_2c3a_fields(tmp_path: Path):
    db = tmp_path / "cm.db"
    row_id = upsert_customer(db, _with_2c3a())
    assert row_id > 0
    got = get_customer(db, "38582303")
    assert got is not None
    assert got.freight_fixed_amount_eur == Decimal("120.00")
    assert got.insurance_enabled        is True


# ── 13. PUT update (overwrite in place) ──────────────────────────────────────

def test_upsert_update_overwrites_2c3a_fields(tmp_path: Path):
    db = tmp_path / "cm.db"
    # First write
    id1 = upsert_customer(db, _with_2c3a())
    # Second write — different amounts, insurance disabled
    id2 = upsert_customer(db, _with_2c3a(
        freight_fixed_amount_eur = Decimal("200.00"),
        insurance_enabled        = False,
    ))
    assert id1 == id2   # same row
    got = get_customer(db, "38582303")
    assert got.freight_fixed_amount_eur == Decimal("200.00")
    assert got.insurance_enabled        is False


# ── 14. GET list ─────────────────────────────────────────────────────────────

def test_list_customers_includes_new_fields(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _with_2c3a(
        bill_to_contractor_id = "A",
        bill_to_name          = "Acme",
        country               = "DE",
    ))
    upsert_customer(db, _with_2c3a(
        bill_to_contractor_id = "B",
        bill_to_name          = "Beta",
        country               = "FI",
        freight_fixed_amount_eur = Decimal("99.00"),
        insurance_enabled        = False,
    ))
    rows = list_customers(db)
    assert len(rows) == 2
    by_id = {r.bill_to_contractor_id: r for r in rows}
    assert by_id["A"].freight_fixed_amount_eur == Decimal("120.00")
    assert by_id["B"].freight_fixed_amount_eur == Decimal("99.00")
    assert by_id["B"].insurance_enabled        is False


# ── 15. New fields default on minimal create ─────────────────────────────────

def test_new_fields_default_to_none_on_minimal_create(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal())
    got = get_customer(db, "38582303")
    # All new 2C.3a Decimal fields default to None
    assert got.freight_fixed_amount_eur    is None
    assert got.freight_fixed_amount_usd    is None
    assert got.insurance_fixed_amount_eur  is None
    assert got.insurance_fixed_amount_usd  is None
    assert got.insurance_min_eur           is None
    assert got.insurance_min_usd           is None
    # Labels default to None
    assert got.freight_label_pl   is None
    assert got.freight_label_en   is None
    assert got.insurance_label_pl is None
    assert got.insurance_label_en is None
    # Bool defaults to True
    assert got.insurance_enabled  is True
