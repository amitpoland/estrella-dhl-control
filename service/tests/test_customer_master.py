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


# ── MasterData-2: KYC / Compliance + KUKE extras + payment terms ─────────────

def test_kyc_fields_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        kyc_status       = "approved",
        kyc_approved_on  = "2025-01-15",
        kyc_expiry       = "2027-01-15",
        beneficial_owner = "Jane Doe",
        owner_id_type    = "passport",
        owner_id_number  = "XY123456",
        aml_risk_rating  = "low",
        pep_check_result = "clear",
        compliance_notes = "All checks passed",
    ))
    got = get_customer(db, "38582303")
    assert got.kyc_status       == "approved"
    assert got.kyc_approved_on  == "2025-01-15"
    assert got.kyc_expiry       == "2027-01-15"
    assert got.beneficial_owner == "Jane Doe"
    assert got.owner_id_type    == "passport"
    assert got.owner_id_number  == "XY123456"
    assert got.aml_risk_rating  == "low"
    assert got.pep_check_result == "clear"
    assert got.compliance_notes == "All checks passed"


def test_kuke_extras_round_trip(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _minimal(
        kuke_approved           = True,
        kuke_limit              = Decimal("50000"),
        kuke_policy_number      = "POL-2024-001",
        kuke_self_retention_pct = Decimal("10"),
        payment_terms_days      = 30,
    ))
    got = get_customer(db, "38582303")
    assert got.kuke_policy_number      == "POL-2024-001"
    assert got.kuke_self_retention_pct == Decimal("10")
    assert got.payment_terms_days      == 30


def test_validate_kyc_status_enum_rejected():
    blockers = validate(_minimal(kyc_status="invalid"))
    assert any("kyc_status" in b for b in blockers)


def test_validate_kyc_status_valid_values_pass():
    for v in ("approved", "pending", "review", "rejected"):
        assert validate(_minimal(kyc_status=v)) == [], f"expected {v!r} to pass"


def test_validate_owner_id_type_enum_rejected():
    blockers = validate(_minimal(owner_id_type="nric"))
    assert any("owner_id_type" in b for b in blockers)


def test_validate_aml_risk_rating_enum_rejected():
    blockers = validate(_minimal(aml_risk_rating="extreme"))
    assert any("aml_risk_rating" in b for b in blockers)


def test_validate_pep_check_result_enum_rejected():
    blockers = validate(_minimal(pep_check_result="unknown"))
    assert any("pep_check_result" in b for b in blockers)


def test_validate_self_retention_pct_range():
    assert any("kuke_self_retention_pct" in b
               for b in validate(_minimal(kuke_self_retention_pct=Decimal("101"))))
    assert any("kuke_self_retention_pct" in b
               for b in validate(_minimal(kuke_self_retention_pct=Decimal("-1"))))
    # Boundary values must pass
    assert validate(_minimal(kuke_self_retention_pct=Decimal("0")))   == []
    assert validate(_minimal(kuke_self_retention_pct=Decimal("100"))) == []


def test_validate_payment_terms_days_negative_rejected():
    blockers = validate(_minimal(payment_terms_days=-1))
    assert any("payment_terms_days" in b for b in blockers)
    assert validate(_minimal(payment_terms_days=0))  == []
    assert validate(_minimal(payment_terms_days=30)) == []


# ── MasterData-2 API tests ────────────────────────────────────────────────────

import unittest.mock as _mock  # noqa: E402


@pytest.fixture(scope="module")
def cm_api_client(tmp_path_factory):
    api_tmp = tmp_path_factory.mktemp("cm_api_md2")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings
    with _mock.patch.object(settings, "storage_root", api_tmp):
        import app.api.routes_customer_master as mod
        mod._DB_PATH = api_tmp / "customer_master.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _cm_hdr():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_put_kyc_fields_persisted(cm_api_client):
    r = cm_api_client.put(
        "/api/v1/customer-master/KYC_TEST_01",
        json={
            "bill_to_name":    "KYC Corp",
            "country":         "PL",
            "kyc_status":      "approved",
            "kyc_approved_on": "2025-03-01",
            "kyc_expiry":      "2027-03-01",
            "beneficial_owner": "Ana Smith",
            "owner_id_type":   "passport",
            "owner_id_number": "AB999888",
            "aml_risk_rating": "low",
            "pep_check_result": "clear",
            "compliance_notes": "Verified by compliance team",
        },
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    r2 = cm_api_client.get("/api/v1/customer-master/KYC_TEST_01", headers=_cm_hdr())
    data = r2.json()
    assert data["kyc_status"]       == "approved"
    assert data["kyc_approved_on"]  == "2025-03-01"
    assert data["kyc_expiry"]       == "2027-03-01"
    assert data["beneficial_owner"] == "Ana Smith"
    assert data["owner_id_type"]    == "passport"
    assert data["owner_id_number"]  == "AB999888"
    assert data["aml_risk_rating"]  == "low"
    assert data["pep_check_result"] == "clear"
    assert data["compliance_notes"] == "Verified by compliance team"


def test_api_put_kuke_extras_persisted(cm_api_client):
    r = cm_api_client.put(
        "/api/v1/customer-master/KUKE_TEST_01",
        json={
            "bill_to_name":             "KUKE Corp",
            "country":                  "DE",
            "kuke_approved":            True,
            "kuke_limit":               "50000",
            "kuke_policy_number":       "POL-2024-001",
            "kuke_self_retention_pct":  "10",
            "payment_terms_days":       30,
        },
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    r2 = cm_api_client.get("/api/v1/customer-master/KUKE_TEST_01", headers=_cm_hdr())
    data = r2.json()
    assert data["kuke_policy_number"]      == "POL-2024-001"
    assert data["kuke_self_retention_pct"] == "10"
    assert data["payment_terms_days"]      == 30


def test_api_put_payment_terms_empty_string_becomes_null(cm_api_client):
    """Empty string for payment_terms_days must be stored as null, not 422."""
    r = cm_api_client.put(
        "/api/v1/customer-master/PT_NULL_TEST",
        json={"bill_to_name": "PT Corp", "country": "DE", "payment_terms_days": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["payment_terms_days"] is None


def test_api_put_ship_to_blank_strings_coerce_to_null(cm_api_client):
    """Operator complaint 2026-05-19: clearing a previously-set ship_to_*
    string field round-tripped as '' instead of NULL because ship_to_* keys
    were missing from _OPTIONAL_STR_FIELDS.  This test pins the contract:
    a PUT that sends '' for every ship_to_* string must yield JSON-null on
    reload, not the empty string."""
    # Seed with a populated alternate address.  Use the alternate-address
    # shape (ship_to_use_alternate=True) WITHOUT a separate receiver id —
    # validate() blocks setting both shapes simultaneously.
    seed = cm_api_client.put(
        "/api/v1/customer-master/SHIP_NULL_TEST",
        json={
            "bill_to_name":         "Ship Null Corp",
            "country":              "PL",
            "ship_to_use_alternate": True,
            "ship_to_name":          "Alt Receiver Sp z o.o.",
            "ship_to_person":        "Jan Kowalski",
            "ship_to_street":        "ul. Testowa 1",
            "ship_to_city":          "Warszawa",
            "ship_to_zip":           "00-001",
            "ship_to_country":       "PL",
            "ship_to_phone":         "+48 22 000 0000",
            "ship_to_email":         "alt@example.com",
        },
        headers=_cm_hdr(),
    )
    assert seed.status_code == 200, seed.text

    # Operator clears every ship_to_* string via the modal.  These reach the
    # backend as the empty string from the UI form inputs.  Backend MUST
    # coerce them to NULL so the stored record matches the operator intent.
    clear = cm_api_client.put(
        "/api/v1/customer-master/SHIP_NULL_TEST",
        json={
            "ship_to_use_alternate": False,
            "ship_to_name":          "",
            "ship_to_person":        "",
            "ship_to_street":        "",
            "ship_to_city":          "",
            "ship_to_zip":           "",
            "ship_to_country":       "",
            "ship_to_phone":         "",
            "ship_to_email":         "",
        },
        headers=_cm_hdr(),
    )
    assert clear.status_code == 200, clear.text
    data = clear.json()
    for k in ("ship_to_name", "ship_to_person", "ship_to_street",
              "ship_to_city", "ship_to_zip", "ship_to_country",
              "ship_to_phone", "ship_to_email"):
        assert data[k] is None, f"{k} must be null, got {data[k]!r}"
    assert data["ship_to_use_alternate"] is False
    # Identity fields preserved by Campaign 5/6 hydration (PR #227).
    assert data["bill_to_name"] == "Ship Null Corp"
    assert data["country"]      == "PL"


def test_api_kyc_enum_validation_422(cm_api_client):
    """Invalid enum values must be rejected with 422."""
    r = cm_api_client.put(
        "/api/v1/customer-master/BAD_KYC_01",
        json={"bill_to_name": "X", "country": "PL", "kyc_status": "verified"},
        headers=_cm_hdr(),
    )
    assert r.status_code == 422, r.text


# ── MasterData-2.1 blank-normalisation regression tests ──────────────────────
# These guard against the "422 on normal save" regression where the UI sends
# empty strings for optional fields and the backend incorrectly rejects them.

def test_api_freight_service_id_empty_string_becomes_null(cm_api_client):
    """PUT with freight_service_id='' must return 200 and store null, not 422."""
    r = cm_api_client.put(
        "/api/v1/customer-master/BLANK_FREIGHT_01",
        json={"bill_to_name": "Blank Freight", "country": "PL",
              "freight_service_id": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["freight_service_id"] is None


def test_api_insurance_service_id_empty_string_becomes_null(cm_api_client):
    """PUT with insurance_service_id='' must return 200 and store null, not 422."""
    r = cm_api_client.put(
        "/api/v1/customer-master/BLANK_INS_01",
        json={"bill_to_name": "Blank Insurance", "country": "PL",
              "insurance_service_id": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["insurance_service_id"] is None


def test_api_kuke_approved_false_blank_limit_is_200(cm_api_client):
    """kuke_approved=false with blank kuke_limit must return 200."""
    r = cm_api_client.put(
        "/api/v1/customer-master/KUKE_FALSE_01",
        json={"bill_to_name": "KUKE False", "country": "FI",
              "kuke_approved": False, "kuke_limit": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["kuke_approved"] is False
    assert data["kuke_limit"] is None


def test_api_kuke_approved_true_blank_limit_is_422(cm_api_client):
    """kuke_approved=true with missing kuke_limit must return 422 with clear message."""
    r = cm_api_client.put(
        "/api/v1/customer-master/KUKE_TRUE_NOLIMIT",
        json={"bill_to_name": "KUKE True", "country": "FI",
              "kuke_approved": True, "kuke_limit": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail", "")
    assert "kuke_approved" in str(detail).lower() or "kuke_limit" in str(detail).lower()


def test_api_payment_terms_empty_string_null_via_route(cm_api_client):
    """PUT with payment_terms_days='' returns 200 and stores null (route layer)."""
    r = cm_api_client.put(
        "/api/v1/customer-master/PT_NULL_ROUTE",
        json={"bill_to_name": "PT Route", "country": "DE",
              "payment_terms_days": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment_terms_days"] is None


def test_api_kuke_self_retention_empty_string_becomes_null(cm_api_client):
    """PUT with kuke_self_retention_pct='' returns 200 and stores null."""
    r = cm_api_client.put(
        "/api/v1/customer-master/KSR_NULL_01",
        json={"bill_to_name": "KSR Null", "country": "DE",
              "kuke_self_retention_pct": ""},
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["kuke_self_retention_pct"] is None


def test_api_all_blank_optional_fields_200(cm_api_client):
    """A payload that mimics the UI sending '' for every optional field must return 200.

    This is the exact scenario that caused the 422 regression: the ClientKycModal
    opens for a client with no customer master record (custMasterRec=null → cm={})
    and every optional field defaults to ''.
    """
    r = cm_api_client.put(
        "/api/v1/customer-master/ALL_BLANK_UI",
        json={
            "bill_to_name":           "All Blank UI Client",
            "country":                "PL",
            "freight_service_id":     "",
            "insurance_service_id":   "",
            "freight_mode":           "",
            "freight_currency":       "",
            "freight_label_pl":       "",
            "freight_label_en":       "",
            "insurance_mode":         "",
            "insurance_label_pl":     "",
            "insurance_label_en":     "",
            "kuke_policy_number":     "",
            "kuke_currency":          "",
            "kuke_expiry_date":       "",
            "risk_status":            "",
            "credit_currency":        "",
            "kyc_status":             "",
            "kyc_approved_on":        "",
            "kyc_expiry":             "",
            "beneficial_owner":       "",
            "owner_id_type":          "",
            "owner_id_number":        "",
            "aml_risk_rating":        "",
            "pep_check_result":       "",
            "compliance_notes":       "",
            "kuke_limit":             "",
            "credit_limit":           "",
            "kuke_self_retention_pct": "",
            "payment_terms_days":     "",
            "kuke_approved":          False,
        },
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["freight_service_id"]   is None
    assert data["insurance_service_id"] is None
    assert data["kuke_limit"]           is None
    assert data["payment_terms_days"]   is None


def test_api_existing_service_ids_preserved_on_roundtrip(cm_api_client):
    """When freight/insurance service IDs are already configured, a round-trip
    PUT (GET → re-send) must preserve them, not wipe them."""
    # First PUT with explicit service IDs
    r1 = cm_api_client.put(
        "/api/v1/customer-master/PRESERVE_IDS",
        json={
            "bill_to_name":          "Preserve IDs Corp",
            "country":               "FI",
            "freight_service_id":    "13002743",
            "insurance_service_id":  "13102217",
            "freight_fixed_amount_eur": "35",
        },
        headers=_cm_hdr(),
    )
    assert r1.status_code == 200, r1.text

    # Second PUT re-sends the same IDs (simulating round-trip from GET)
    r2 = cm_api_client.put(
        "/api/v1/customer-master/PRESERVE_IDS",
        json={
            "bill_to_name":          "Preserve IDs Corp",
            "country":               "FI",
            "freight_service_id":    "13002743",
            "insurance_service_id":  "13102217",
            "freight_fixed_amount_eur": "35",
        },
        headers=_cm_hdr(),
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["freight_service_id"]   == "13002743"
    assert data["insurance_service_id"] == "13102217"


# ── B2: Invoices-tab round-trip ──────────────────────────────────────────────
# The Invoices tab (KycModal) writes wFirma document defaults via the existing
# PUT /api/v1/customer-master/{cid} — no new endpoint. These tests guard the
# round-trip for the fields the new tab body binds.

def test_api_invoices_tab_round_trip(cm_api_client):
    """Proforma/invoice series ids, vat_mode, language_id, payment_terms,
    default_currency must round-trip through PUT → GET cleanly.
    vat_mode must be a valid wFirma code (222/228/229)."""
    r = cm_api_client.put(
        "/api/v1/customer-master/INV_TAB_RT",
        json={
            "bill_to_name":                 "Invoices RT Co",
            "country":                      "FR",
            "preferred_proforma_series_id": "WF_PROF_1",
            "preferred_invoice_series_id":  "WF_INV_2",
            "vat_mode":                     222,
            "default_language_id":          "en",
            "payment_terms_days":           45,
            "default_currency":             "EUR",
        },
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    g = cm_api_client.get("/api/v1/customer-master/INV_TAB_RT", headers=_cm_hdr())
    assert g.status_code == 200
    data = g.json()
    assert data["preferred_proforma_series_id"] == "WF_PROF_1"
    assert data["preferred_invoice_series_id"]  == "WF_INV_2"
    assert data["vat_mode"]                     == 222
    assert data["default_language_id"]          == "en"
    assert data["payment_terms_days"]           == 45
    assert data["default_currency"]             == "EUR"


def test_api_invoices_tab_blank_optionals_200(cm_api_client):
    """Blank optional series ids and language id from the form must store as null
    rather than '', mirroring B0 normalisation."""
    r = cm_api_client.put(
        "/api/v1/customer-master/INV_TAB_BLANK",
        json={
            "bill_to_name":                 "Invoices Blank Co",
            "country":                      "DE",
            "preferred_proforma_series_id": "",
            "preferred_invoice_series_id":  "",
            "default_language_id":          "",
            "payment_terms_days":           "",
            "default_currency":             "EUR",
        },
        headers=_cm_hdr(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["preferred_proforma_series_id"] is None
    assert data["preferred_invoice_series_id"]  is None
    assert data["default_language_id"]          is None
    assert data["payment_terms_days"]           is None
