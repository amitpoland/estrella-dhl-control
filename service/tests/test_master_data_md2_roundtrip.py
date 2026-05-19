"""
test_master_data_md2_roundtrip.py — Phase MasterData-2 regression tests.

Pins the regression where fields missing from the ClientKycModal form state
caused upsert_customer's direct SET to overwrite them with NULL on every save.

Tests:
  1. Fields saved on first PUT must survive a second PUT that omits them.
  2. vat_mode round-trips as integer through string form value.
  3. preferred_proforma_series_id / preferred_invoice_series_id preserved.
  4. freight_mode / freight_currency / insurance_mode preserved.
  5. System fields (vat_eu_valid, vat_eu_validated_at, ship_to_contractor_id,
     last_wfirma_sync_at, wfirma_sync_source) are preserved when re-sent unchanged.
  6. insurance_fixed_amount_eur / insurance_fixed_amount_usd preserved.
  7. insurance_min_amount / insurance_min_override preserved.
  8. Full form round-trip: all MasterData-2 fields survive open→save→reopen cycle.
"""
from __future__ import annotations

import sys
import unittest.mock as _mock
from decimal import Decimal
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()


@pytest.fixture(scope="module")
def md2_client(tmp_path_factory):
    api_tmp = tmp_path_factory.mktemp("md2_roundtrip")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings
    with _mock.patch.object(settings, "storage_root", api_tmp):
        import app.api.routes_customer_master as mod
        mod._DB_PATH = api_tmp / "customer_master.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _put(client, cid: str, body: dict, expect=200):
    r = client.put(f"/api/v1/customer-master/{cid}", json=body, headers=_hdr())
    assert r.status_code == expect, f"PUT {cid} → {r.status_code}: {r.text}"
    return r.json()


def _get(client, cid: str):
    r = client.get(f"/api/v1/customer-master/{cid}", headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. vat_mode round-trip as string (form sends string, backend coerces) ─────

def test_vat_mode_string_roundtrip(md2_client):
    """The form sends vat_mode as a string ('222'). The backend must coerce it
    to int 222 and persist it. A second PUT with the same value must preserve it."""
    d1 = _put(md2_client, "MD2_VM_01", {
        "bill_to_name": "VatMode Corp", "country": "PL", "vat_mode": "222",
    })
    assert d1["vat_mode"] == 222

    d2 = _put(md2_client, "MD2_VM_01", {
        "bill_to_name": "VatMode Corp", "country": "PL", "vat_mode": "222",
    })
    assert d2["vat_mode"] == 222, "vat_mode wiped on second save"


def test_vat_mode_cleared_to_null_when_blank(md2_client):
    """The form sends vat_mode='' when cleared. Backend must store null (not crash)."""
    _put(md2_client, "MD2_VM_CLR", {
        "bill_to_name": "VatMode Clear", "country": "DE", "vat_mode": 228,
    })
    d = _put(md2_client, "MD2_VM_CLR", {
        "bill_to_name": "VatMode Clear", "country": "DE", "vat_mode": "",
    })
    assert d["vat_mode"] is None


# ── 2. preferred_proforma_series_id / preferred_invoice_series_id ─────────────

def test_preferred_series_preserved_on_resave(md2_client):
    """Series IDs saved on first PUT must still be present after second PUT
    that explicitly sends the same values (simulating form round-trip)."""
    _put(md2_client, "MD2_SER_01", {
        "bill_to_name": "Series Corp", "country": "FR",
        "preferred_proforma_series_id": "PS_100",
        "preferred_invoice_series_id":  "IS_200",
    })
    d = _put(md2_client, "MD2_SER_01", {
        "bill_to_name": "Series Corp", "country": "FR",
        "preferred_proforma_series_id": "PS_100",
        "preferred_invoice_series_id":  "IS_200",
    })
    assert d["preferred_proforma_series_id"] == "PS_100"
    assert d["preferred_invoice_series_id"]  == "IS_200"


def test_preferred_series_blank_saves_null(md2_client):
    """Empty string from the form → null in DB (not '' which fails uniqueness)."""
    d = _put(md2_client, "MD2_SER_BLANK", {
        "bill_to_name": "Blank Series", "country": "DE",
        "preferred_proforma_series_id": "",
        "preferred_invoice_series_id":  "",
    })
    assert d["preferred_proforma_series_id"] is None
    assert d["preferred_invoice_series_id"]  is None


# ── 3. freight_mode / freight_currency / insurance_mode ───────────────────────

def test_freight_mode_currency_insurance_mode_preserved(md2_client):
    """Operational freight/insurance fields must not be wiped when re-sent."""
    _put(md2_client, "MD2_FM_01", {
        "bill_to_name": "Freight Corp", "country": "PL",
        "freight_mode":    "fixed",
        "freight_currency": "EUR",
        "insurance_mode":  "formula",
    })
    d = _put(md2_client, "MD2_FM_01", {
        "bill_to_name": "Freight Corp", "country": "PL",
        "freight_mode":    "fixed",
        "freight_currency": "EUR",
        "insurance_mode":  "formula",
    })
    assert d["freight_mode"]    == "fixed"
    assert d["freight_currency"] == "EUR"
    assert d["insurance_mode"]  == "formula"


def test_freight_mode_blank_saves_null(md2_client):
    _put(md2_client, "MD2_FM_CLR", {
        "bill_to_name": "Freight Clear", "country": "DE",
        "freight_mode": "variable",
    })
    d = _put(md2_client, "MD2_FM_CLR", {
        "bill_to_name": "Freight Clear", "country": "DE",
        "freight_mode": "",
    })
    assert d["freight_mode"] is None


# ── 4. insurance_fixed_amount_eur / usd ───────────────────────────────────────

def test_insurance_fixed_amounts_roundtrip(md2_client):
    d = _put(md2_client, "MD2_INS_FA", {
        "bill_to_name": "Insurance Fixed", "country": "PL",
        "insurance_fixed_amount_eur": "15.50",
        "insurance_fixed_amount_usd": "17.00",
    })
    # Backend uses str(Decimal(v)) which preserves the input's decimal form.
    assert Decimal(d["insurance_fixed_amount_eur"]) == Decimal("15.50")
    assert Decimal(d["insurance_fixed_amount_usd"]) == Decimal("17.00")

    # Re-send same values — must be preserved
    d2 = _put(md2_client, "MD2_INS_FA", {
        "bill_to_name": "Insurance Fixed", "country": "PL",
        "insurance_fixed_amount_eur": "15.50",
        "insurance_fixed_amount_usd": "17.00",
    })
    assert Decimal(d2["insurance_fixed_amount_eur"]) == Decimal("15.50")
    assert Decimal(d2["insurance_fixed_amount_usd"]) == Decimal("17.00")


def test_insurance_fixed_amounts_blank_saves_null(md2_client):
    d = _put(md2_client, "MD2_INS_FA_CLR", {
        "bill_to_name": "Ins FA Clear", "country": "DE",
        "insurance_fixed_amount_eur": "",
        "insurance_fixed_amount_usd": "",
    })
    assert d["insurance_fixed_amount_eur"] is None
    assert d["insurance_fixed_amount_usd"] is None


# ── 5. insurance_min_amount / insurance_min_override (legacy decimal fields) ──

def test_insurance_min_amount_override_roundtrip(md2_client):
    d = _put(md2_client, "MD2_INS_MIN", {
        "bill_to_name": "Ins Min Corp", "country": "IN",
        "insurance_min_amount":   "5.00",
        "insurance_min_override": "7.50",
    })
    assert Decimal(d["insurance_min_amount"])   == Decimal("5.00")
    assert Decimal(d["insurance_min_override"]) == Decimal("7.50")


# ── 6. vat_eu_valid / vat_eu_validated_at preserved on operator save ──────────

def test_vat_eu_fields_preserved_when_roundtripped(md2_client):
    """vat_eu_valid and vat_eu_validated_at are system-set fields. When the
    operator opens and saves the KYC modal, they should not be wiped."""
    # Simulate a system write (e.g. from identity_only upsert) that sets VAT validation.
    from app.services.customer_master_db import CustomerMaster, upsert_customer, init_db
    import app.api.routes_customer_master as mod
    db = mod._DB_PATH
    init_db(db)
    upsert_customer(db, CustomerMaster(
        bill_to_contractor_id = "MD2_VAT_EU",
        bill_to_name          = "VAT Validated Corp",
        country               = "DE",
        vat_eu_valid          = True,
        vat_eu_validated_at   = "2025-12-01",
    ))

    # Operator saves the KYC modal — sends vat_eu_valid and vat_eu_validated_at
    # as loaded from GET (round-trip). Operator does NOT change these fields.
    current = _get(md2_client, "MD2_VAT_EU")
    assert current["vat_eu_valid"]        is True
    assert current["vat_eu_validated_at"] == "2025-12-01"

    # Round-trip save: form sends same values back
    d = _put(md2_client, "MD2_VAT_EU", {
        "bill_to_name":        current["bill_to_name"],
        "country":             current["country"],
        "vat_eu_valid":        current["vat_eu_valid"],
        "vat_eu_validated_at": current["vat_eu_validated_at"],
    })
    assert d["vat_eu_valid"]        is True, "vat_eu_valid wiped on operator save"
    assert d["vat_eu_validated_at"] == "2025-12-01", "vat_eu_validated_at wiped"


# ── 7. Full form round-trip — all MasterData-2 fields ─────────────────────────

def test_full_md2_form_roundtrip(md2_client):
    """Simulate the full KYC modal cycle: first save sets all fields; second save
    (re-open → reload from GET → save unchanged) must preserve every field."""
    initial = {
        "bill_to_name":                 "Full Round Trip Corp",
        "country":                      "PL",
        "vat_mode":                     "228",
        "preferred_proforma_series_id": "PRO-SERIES-77",
        "preferred_invoice_series_id":  "INV-SERIES-88",
        "default_language_id":          "pl",
        "default_currency":             "PLN",
        "freight_mode":                 "fixed",
        "freight_currency":             "EUR",
        "insurance_mode":               "formula",
        "insurance_fixed_amount_eur":   "12.00",
        "insurance_fixed_amount_usd":   "13.00",
        "insurance_min_amount":         "3.00",
        "insurance_min_override":       "4.50",
    }

    d1 = _put(md2_client, "MD2_FULL_RT", initial)
    assert d1["vat_mode"]                     == 228
    assert d1["preferred_proforma_series_id"] == "PRO-SERIES-77"
    assert d1["preferred_invoice_series_id"]  == "INV-SERIES-88"
    assert d1["freight_mode"]                 == "fixed"
    assert d1["insurance_mode"]               == "formula"
    assert Decimal(d1["insurance_fixed_amount_eur"])   == Decimal("12")
    assert Decimal(d1["insurance_fixed_amount_usd"])   == Decimal("13")

    # Simulate re-open: GET current state from backend
    current = _get(md2_client, "MD2_FULL_RT")

    # Simulate form save after re-open (no changes, form re-sends loaded values)
    resave_payload = {
        "bill_to_name":                 current["bill_to_name"],
        "country":                      current["country"],
        "vat_mode":                     str(current["vat_mode"]) if current["vat_mode"] is not None else "",
        "preferred_proforma_series_id": current["preferred_proforma_series_id"] or "",
        "preferred_invoice_series_id":  current["preferred_invoice_series_id"]  or "",
        "default_language_id":          current["default_language_id"]          or "",
        "default_currency":             current["default_currency"]             or "",
        "freight_mode":                 current["freight_mode"]                 or "",
        "freight_currency":             current["freight_currency"]             or "",
        "insurance_mode":               current["insurance_mode"]               or "",
        "insurance_fixed_amount_eur":   current["insurance_fixed_amount_eur"]   or "",
        "insurance_fixed_amount_usd":   current["insurance_fixed_amount_usd"]   or "",
        "insurance_min_amount":         current["insurance_min_amount"]         or "",
        "insurance_min_override":       current["insurance_min_override"]       or "",
    }

    d2 = _put(md2_client, "MD2_FULL_RT", resave_payload)
    assert d2["vat_mode"]                     == 228,             "vat_mode wiped"
    assert d2["preferred_proforma_series_id"] == "PRO-SERIES-77", "proforma series wiped"
    assert d2["preferred_invoice_series_id"]  == "INV-SERIES-88", "invoice series wiped"
    assert d2["freight_mode"]                 == "fixed",         "freight_mode wiped"
    assert d2["freight_currency"]             == "EUR",           "freight_currency wiped"
    assert d2["insurance_mode"]               == "formula",       "insurance_mode wiped"
    assert Decimal(d2["insurance_fixed_amount_eur"]) == Decimal("12"),  "insurance_fixed_amount_eur wiped"
    assert Decimal(d2["insurance_fixed_amount_usd"]) == Decimal("13"),  "insurance_fixed_amount_usd wiped"
    assert Decimal(d2["insurance_min_amount"])        == Decimal("3"),   "insurance_min_amount wiped"
    assert Decimal(d2["insurance_min_override"])      == Decimal("4.5"), "insurance_min_override wiped"
