"""
test_customer_master.py — unit tests for Layer 1 customer master.

NEVER hits wFirma. Pure DB + pure helpers.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.models.vat_resolver import CustomerForVAT             # noqa: E402
from app.services.customer_master_db import (                  # noqa: E402
    CustomerMaster, delete_customer, get_customer, init_db,
    list_customers, upsert_customer, validate,
)
from app.services.customer_master import (                     # noqa: E402
    CustomerMasterResolver, CustomerNotFound,
    SHIP_TO_ALTERNATE_ADDRESS, SHIP_TO_NONE, SHIP_TO_SEPARATE_CONTRACTOR,
    pick_currency, pick_freight, pick_freight_service_id,
    pick_insurance_min, pick_insurance_service_id,
    pick_invoice_series_id, pick_language_id, pick_proforma_series_id,
    pick_vat_mode, ship_to_shape, to_vat_input,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _minimal(**overrides):
    base = dict(
        bill_to_contractor_id = "38582303",
        bill_to_name          = "Scandinavian Diamond",
        country               = "NO",
    )
    base.update(overrides)
    return CustomerMaster(**base)


def _full_customer(**overrides):
    base = dict(
        bill_to_contractor_id   = "38582303",
        bill_to_name            = "Scandinavian Diamond Exchange",
        country                 = "NO",
        nip                     = "VAT ID 854785362",
        vat_eu_number           = None,
        vat_eu_valid            = None,
        ship_to_use_alternate   = False,
        ship_to_name            = None,
        ship_to_person          = None,
        default_currency        = "USD",
        default_language_id     = "1",
        insurance_min_override  = None,
        credit_limit            = Decimal("50000"),
        credit_currency         = "USD",
        kuke_approved           = True,
        kuke_limit              = Decimal("100000"),
        kuke_currency           = "USD",
        kuke_expiry_date        = "2027-12-31",
        risk_status             = "approved",
        notes                   = "test",
    )
    base.update(overrides)
    return CustomerMaster(**base)


# ── Validation ───────────────────────────────────────────────────────────────

def test_validate_accepts_minimal_customer():
    assert validate(_minimal()) == []


def test_validate_blocks_missing_contractor_id():
    assert "bill_to_contractor_id" in "; ".join(validate(_minimal(bill_to_contractor_id="")))


def test_validate_blocks_missing_name():
    assert "bill_to_name" in "; ".join(validate(_minimal(bill_to_name="")))


@pytest.mark.parametrize("bad", ["", "P", "POL", "polska"])
def test_validate_blocks_bad_country(bad):
    blockers = validate(_minimal(country=bad))
    assert any("country" in b for b in blockers), f"expected country block for {bad!r}"


def test_validate_blocks_invalid_currency():
    assert "default_currency" in "; ".join(validate(_minimal(default_currency="JPY")))


def test_validate_blocks_both_ship_to_shapes_set():
    c = _minimal(ship_to_use_alternate=True, ship_to_contractor_id="9999")
    blockers = validate(c)
    assert any("ship_to_use_alternate" in b for b in blockers)


def test_validate_blocks_negative_credit_limit():
    blockers = validate(_minimal(credit_limit=Decimal("-1")))
    assert any("credit_limit" in b for b in blockers)


def test_validate_blocks_kuke_approved_without_limit():
    blockers = validate(_minimal(kuke_approved=True, kuke_limit=None))
    assert any("kuke_limit" in b for b in blockers)


# ── DB CRUD ──────────────────────────────────────────────────────────────────

def test_init_db_creates_table_idempotent(tmp_path: Path):
    db = tmp_path / "cm.db"
    init_db(db)
    init_db(db)
    assert db.is_file()


def test_upsert_inserts_then_updates(tmp_path: Path):
    db = tmp_path / "cm.db"
    id1 = upsert_customer(db, _minimal())
    id2 = upsert_customer(db, _minimal(bill_to_name="renamed"))
    assert id1 == id2
    got = get_customer(db, "38582303")
    assert got is not None
    assert got.bill_to_name == "renamed"


def test_get_customer_returns_none_for_unknown(tmp_path: Path):
    db = tmp_path / "cm.db"
    init_db(db)
    assert get_customer(db, "99999999") is None


def test_get_customer_returns_none_when_db_missing(tmp_path: Path):
    assert get_customer(tmp_path / "missing.db", "X") is None


def test_round_trip_full_record(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _full_customer())
    got = get_customer(db, "38582303")
    assert got.country         == "NO"
    assert got.nip             == "VAT ID 854785362"
    assert got.default_currency == "USD"
    assert got.kuke_approved   is True
    assert got.kuke_limit      == Decimal("100000")
    assert got.risk_status     == "approved"
    assert got.notes           == "test"


def test_country_normalised_to_upper(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(country="no"))
    got = get_customer(db, "38582303")
    assert got.country == "NO"


def test_ship_to_country_normalised_to_upper(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(ship_to_country="de"))
    got = get_customer(db, "38582303")
    assert got.ship_to_country == "DE"


def test_decimal_round_trip_preserves_precision(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        insurance_min_override = Decimal("17.50"),
        credit_limit           = Decimal("99999.99"),
    ))
    got = get_customer(db, "38582303")
    assert got.insurance_min_override == Decimal("17.50")
    assert got.credit_limit           == Decimal("99999.99")


def test_upsert_validation_blocks_bad_record(tmp_path: Path):
    db = tmp_path / "cm.db"
    with pytest.raises(ValueError, match="customer_master validation failed"):
        upsert_customer(db, _minimal(country="POLAND"))


def test_list_customers_empty_db(tmp_path: Path):
    assert list_customers(tmp_path / "missing.db") == []


def test_list_customers_filters_by_country(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(bill_to_contractor_id="A", bill_to_name="A", country="NO"))
    upsert_customer(db, _minimal(bill_to_contractor_id="B", bill_to_name="B", country="DE"))
    upsert_customer(db, _minimal(bill_to_contractor_id="C", bill_to_name="C", country="DE"))
    no_only = list_customers(db, country="NO")
    de_only = list_customers(db, country="DE")
    assert {c.bill_to_contractor_id for c in no_only} == {"A"}
    assert {c.bill_to_contractor_id for c in de_only} == {"B", "C"}


def test_list_customers_filters_by_risk_status(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(bill_to_contractor_id="A", bill_to_name="A", risk_status="approved"))
    upsert_customer(db, _minimal(bill_to_contractor_id="B", bill_to_name="B", risk_status="blocked"))
    blocked = list_customers(db, risk_status="blocked")
    assert {c.bill_to_contractor_id for c in blocked} == {"B"}


def test_delete_customer_removes_row(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal())
    assert delete_customer(db, "38582303") is True
    assert get_customer(db, "38582303") is None


def test_delete_customer_unknown_returns_false(tmp_path: Path):
    db = tmp_path / "cm.db"
    init_db(db)
    assert delete_customer(db, "no-such") is False


# ── Unique constraint ────────────────────────────────────────────────────────

def test_unique_constraint_per_bill_to(tmp_path: Path):
    """Two records with same bill_to_contractor_id should result in ONE row (upsert)."""
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(bill_to_name="first"))
    upsert_customer(db, _minimal(bill_to_name="second"))
    upsert_customer(db, _minimal(bill_to_name="third"))
    rows = list_customers(db)
    assert len(rows) == 1
    assert rows[0].bill_to_name == "third"


# ── Helper functions ─────────────────────────────────────────────────────────

def test_to_vat_input_projects_fields():
    c = _full_customer(country="DE", vat_eu_number="DE123", vat_eu_valid=True)
    v = to_vat_input(c)
    assert isinstance(v, CustomerForVAT)
    assert v.country       == "DE"
    assert v.vat_eu_number == "DE123"
    assert v.vat_eu_valid  is True


def test_pick_currency_prefers_customer_default():
    c = _full_customer(default_currency="EUR")
    assert pick_currency(c, target_default="USD") == "EUR"


def test_pick_currency_falls_back_to_target_default():
    c = _full_customer(default_currency=None)
    assert pick_currency(c, target_default="USD") == "USD"


def test_pick_language_id_prefers_customer():
    c = _full_customer(default_language_id="3")
    assert pick_language_id(c, target_default="1") == "3"


def test_pick_language_id_falls_back():
    c = _full_customer(default_language_id=None)
    assert pick_language_id(c, target_default="1") == "1"


def test_pick_insurance_min_uses_override():
    c = _full_customer(insurance_min_override=Decimal("25"))
    assert pick_insurance_min(c, vat_based_default=Decimal("20")) == Decimal("25")


def test_pick_insurance_min_falls_back_to_vat_default():
    c = _full_customer(insurance_min_override=None)
    assert pick_insurance_min(c, vat_based_default=Decimal("20")) == Decimal("20")


# ── pick_freight: master.fixed used, override always wins ───────────────────

def test_pick_freight_override_always_wins_even_when_master_has_fixed():
    c = _full_customer(freight_last_amount=Decimal("80"), freight_mode="fixed")
    assert pick_freight(c, override=Decimal("123.45")) == Decimal("123.45")


def test_pick_freight_uses_master_when_mode_is_fixed():
    c = _full_customer(freight_last_amount=Decimal("85"), freight_mode="fixed")
    assert pick_freight(c) == Decimal("85")


def test_pick_freight_returns_none_when_mode_is_variable():
    """Variable customers must NOT auto-reuse last freight — operator decides."""
    c = _full_customer(freight_last_amount=Decimal("85"), freight_mode="variable")
    assert pick_freight(c) is None


def test_pick_freight_returns_none_when_mode_is_manual():
    c = _full_customer(freight_last_amount=Decimal("85"), freight_mode="manual")
    assert pick_freight(c) is None


def test_pick_freight_returns_none_when_mode_is_no_data():
    c = _full_customer(freight_last_amount=Decimal("85"), freight_mode="no_data")
    assert pick_freight(c) is None


def test_pick_freight_returns_none_when_no_amount():
    c = _full_customer(freight_last_amount=None, freight_mode="fixed")
    assert pick_freight(c) is None


def test_pick_freight_returns_none_when_mode_blank_even_with_amount():
    c = _full_customer(freight_last_amount=Decimal("85"), freight_mode=None)
    assert pick_freight(c) is None


def test_pick_freight_override_works_when_master_empty():
    c = _full_customer(freight_last_amount=None, freight_mode=None)
    assert pick_freight(c, override=Decimal("70")) == Decimal("70")


# ── pick_freight_service_id / pick_insurance_service_id ──────────────────────

def test_pick_freight_service_id_uses_customer_value():
    c = _full_customer(freight_service_id="13002743")
    assert pick_freight_service_id(c, default="OTHER") == "13002743"


def test_pick_freight_service_id_falls_back_to_default():
    c = _full_customer(freight_service_id=None)
    assert pick_freight_service_id(c, default="13002743") == "13002743"


def test_pick_insurance_service_id_uses_customer_value():
    c = _full_customer(insurance_service_id="13102217")
    assert pick_insurance_service_id(c, default="OTHER") == "13102217"


def test_pick_insurance_service_id_falls_back_to_default():
    c = _full_customer(insurance_service_id=None)
    assert pick_insurance_service_id(c, default="13102217") == "13102217"


# ── pick_invoice_series_id / pick_proforma_series_id ─────────────────────────

def test_pick_invoice_series_id_prefers_customer():
    c = _full_customer(preferred_invoice_series_id="15827921")
    assert pick_invoice_series_id(c, default="15827088") == "15827921"


def test_pick_invoice_series_id_falls_back():
    c = _full_customer(preferred_invoice_series_id=None)
    assert pick_invoice_series_id(c, default="15827088") == "15827088"


def test_pick_proforma_series_id_prefers_customer():
    c = _full_customer(preferred_proforma_series_id="99999")
    assert pick_proforma_series_id(c, default="15827088") == "99999"


def test_pick_proforma_series_id_falls_back():
    c = _full_customer(preferred_proforma_series_id=None)
    assert pick_proforma_series_id(c, default="15827088") == "15827088"


# ── pick_vat_mode ────────────────────────────────────────────────────────────

def test_pick_vat_mode_returns_stored_value():
    c = _full_customer(vat_mode=228)
    assert pick_vat_mode(c) == 228


def test_pick_vat_mode_returns_none_when_unset():
    c = _full_customer(vat_mode=None)
    assert pick_vat_mode(c) is None


# ── Ship-to shape detection ──────────────────────────────────────────────────

def test_ship_to_shape_none_when_neither_set():
    c = _minimal()
    assert ship_to_shape(c) == SHIP_TO_NONE


def test_ship_to_shape_alternate_when_flag_set():
    c = _minimal(ship_to_use_alternate=True, ship_to_street="Different street 1")
    assert ship_to_shape(c) == SHIP_TO_ALTERNATE_ADDRESS


def test_ship_to_shape_separate_contractor_when_id_set():
    c = _minimal(ship_to_contractor_id="99999999")
    assert ship_to_shape(c) == SHIP_TO_SEPARATE_CONTRACTOR


def test_ship_to_shape_both_set_is_blocked_at_validate():
    """validate() blocks this combination — but the function still returns
    the separate-contractor shape since that's the more explicit signal."""
    c = _minimal(ship_to_use_alternate=True, ship_to_contractor_id="9999")
    assert ship_to_shape(c) == SHIP_TO_SEPARATE_CONTRACTOR
    # And validation rejects it
    assert any("ship_to_use_alternate" in b for b in validate(c))


# ── CustomerMasterResolver class ─────────────────────────────────────────────

def test_resolver_get_returns_none_for_unknown(tmp_path: Path):
    r = CustomerMasterResolver(tmp_path / "cm.db")
    assert r.get("99999999") is None


def test_resolver_require_raises_for_unknown(tmp_path: Path):
    r = CustomerMasterResolver(tmp_path / "cm.db")
    with pytest.raises(CustomerNotFound):
        r.require("99999999")


def test_resolver_upsert_then_get(tmp_path: Path):
    r = CustomerMasterResolver(tmp_path / "cm.db")
    r.upsert(_full_customer())
    got = r.require("38582303")
    assert got.bill_to_name == "Scandinavian Diamond Exchange"
    assert got.country      == "NO"
    assert got.kuke_approved is True


# ── Credit / Kuke fields stored but NOT enforced (Layer 1) ──────────────────

def test_credit_and_kuke_fields_persist_but_are_not_enforced(tmp_path: Path):
    """Layer 1 stores credit/Kuke fields without checking them. Enforcement
    is Layer 3. This test pins the boundary so a future change of behaviour
    is intentional."""
    db = tmp_path / "cm.db"
    c = _full_customer(
        credit_limit  = Decimal("1000"),
        kuke_approved = True,
        kuke_limit    = Decimal("500"),
        risk_status   = "approved",
    )
    upsert_customer(db, c)
    got = get_customer(db, "38582303")
    assert got.credit_limit  == Decimal("1000")
    assert got.kuke_limit    == Decimal("500")
    assert got.kuke_approved is True
    # No exposure check happens here. (Verified by absence of any HTTP / API call —
    # this entire test runs against a local SQLite file with no network at all.)


# ── No I/O leaks ─────────────────────────────────────────────────────────────

def test_module_does_not_import_wfirma_client():
    """customer_master_db must not depend on wFirma. Confirms the layer
    boundary: storage is wFirma-free."""
    import app.services.customer_master_db as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "wfirma_client" not in src
    assert "import requests" not in src   # only sqlite3 + stdlib


def test_resolver_module_does_not_import_wfirma_client():
    import app.services.customer_master as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "wfirma_client" not in src
