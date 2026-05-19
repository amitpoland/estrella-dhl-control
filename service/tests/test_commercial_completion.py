"""
test_commercial_completion.py — Campaign commercial-completion verification tests.

Covers:
  W01 — warsaw_today() returns a date (not datetime), in correct range
  W02 — ProformaRequest.date field exists; _build_proforma_xml emits <date> when set
  W03 — _build_proforma_xml omits <date> when date is empty/invalid
  PM01 — ProformaRequest.payment_method exists; _build_proforma_xml emits <paymentmethod> for known values
  PM02 — unrecognised and empty payment_method values omit <paymentmethod> element
  PM03 — preferred_payment_method round-trip through CustomerMaster DB (write + read)
  PM04 — preferred_payment_method = None clears the field
  S01 — ship_to_name blank-to-null coercion in _parse_body
  S02 — preferred_payment_method blank-to-null coercion in _parse_body
  SER01 — pick_proforma_series_id returns preferred_proforma_series_id or default
  GATE01 — WFIRMA_CREATE_INVOICE_ALLOWED guard text present in routes_proforma source
  DESC01 — build_description_line produces Polish / English slash format
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest


# ── W01-W03: Warsaw date ──────────────────────────────────────────────────────

def test_warsaw_today_returns_date():
    from app.core.timezone_utils import warsaw_today
    from datetime import date
    d = warsaw_today()
    assert isinstance(d, date)
    assert d.year >= 2024

def test_proforma_request_date_field_defaults_empty():
    from app.services.wfirma_client import ProformaRequest
    r = ProformaRequest(client_name="x", client_zip="", client_city="")
    assert r.date == ""
    assert r.payment_method == ""

def test_build_proforma_xml_emits_date_when_set():
    from app.services.wfirma_client import ProformaRequest, _build_proforma_xml
    r = ProformaRequest(
        client_name="test", client_zip="", client_city="",
        wfirma_contractor_id="999", vat_code_id="1",
        date="2026-05-19",
    )
    xml = _build_proforma_xml(r)
    assert "<date>2026-05-19</date>" in xml, f"<date> not in XML: {xml[:400]}"

def test_build_proforma_xml_omits_date_when_empty():
    from app.services.wfirma_client import ProformaRequest, _build_proforma_xml
    r = ProformaRequest(
        client_name="test", client_zip="", client_city="",
        wfirma_contractor_id="999", vat_code_id="1",
        date="",
    )
    xml = _build_proforma_xml(r)
    assert "<date>" not in xml, "<date> element should be omitted when date is empty"

def test_build_proforma_xml_omits_date_when_invalid():
    from app.services.wfirma_client import ProformaRequest, _build_proforma_xml
    r = ProformaRequest(
        client_name="test", client_zip="", client_city="",
        wfirma_contractor_id="999", vat_code_id="1",
        date="not-a-date",
    )
    xml = _build_proforma_xml(r)
    assert "<date>not-a-date</date>" not in xml


# ── PM01-PM04: Payment method ─────────────────────────────────────────────────

@pytest.mark.parametrize("ui_value,expected_xml", [
    ("transfer",     "<paymentmethod>przelew</paymentmethod>"),
    ("cash",         "<paymentmethod>gotowka</paymentmethod>"),
    ("card",         "<paymentmethod>karta</paymentmethod>"),
    ("compensation", "<paymentmethod>kompensata</paymentmethod>"),
])
def test_build_proforma_xml_emits_paymentmethod(ui_value, expected_xml):
    from app.services.wfirma_client import ProformaRequest, _build_proforma_xml
    r = ProformaRequest(
        client_name="test", client_zip="", client_city="",
        wfirma_contractor_id="999", vat_code_id="1",
        payment_method=ui_value,
    )
    xml = _build_proforma_xml(r)
    assert expected_xml in xml, f"Expected {expected_xml} in XML, got: {xml[:400]}"

@pytest.mark.parametrize("pm", ["other", "", "OTHER", "  "])
def test_build_proforma_xml_omits_paymentmethod_for_other_or_empty(pm):
    from app.services.wfirma_client import ProformaRequest, _build_proforma_xml
    r = ProformaRequest(
        client_name="test", client_zip="", client_city="",
        wfirma_contractor_id="999", vat_code_id="1",
        payment_method=pm,
    )
    xml = _build_proforma_xml(r)
    assert "<paymentmethod>" not in xml, f"<paymentmethod> should be omitted for pm={pm!r}"

def test_preferred_payment_method_db_roundtrip(tmp_path):
    from app.services.customer_master_db import init_db, upsert_customer, get_customer, CustomerMaster
    db = tmp_path / "cm.db"
    init_db(db)
    c = CustomerMaster(
        bill_to_contractor_id="PM001", bill_to_name="PM Test", country="PL",
        preferred_payment_method="cash",
    )
    upsert_customer(db, c)
    got = get_customer(db, "PM001")
    assert got.preferred_payment_method == "cash"

def test_preferred_payment_method_clear_to_none(tmp_path):
    from app.services.customer_master_db import init_db, upsert_customer, get_customer, CustomerMaster
    db = tmp_path / "cm.db"
    init_db(db)
    upsert_customer(db, CustomerMaster(
        bill_to_contractor_id="PM002", bill_to_name="PM Test2", country="PL",
        preferred_payment_method="transfer",
    ))
    upsert_customer(db, CustomerMaster(
        bill_to_contractor_id="PM002", bill_to_name="PM Test2", country="PL",
        preferred_payment_method=None,
    ))
    assert get_customer(db, "PM002").preferred_payment_method is None


# ── S01-S02: Null coercion ────────────────────────────────────────────────────

def test_ship_to_name_blank_becomes_none():
    """blank ship_to_name from UI must be stored as None, not empty string."""
    from app.api.routes_customer_master import _OPTIONAL_STR_FIELDS
    assert "ship_to_name" in _OPTIONAL_STR_FIELDS, "ship_to_name must be in _OPTIONAL_STR_FIELDS"

def test_preferred_payment_method_blank_becomes_none():
    from app.api.routes_customer_master import _OPTIONAL_STR_FIELDS
    assert "preferred_payment_method" in _OPTIONAL_STR_FIELDS

def test_ship_to_fields_all_in_optional_str():
    from app.api.routes_customer_master import _OPTIONAL_STR_FIELDS
    for field in ("ship_to_name", "ship_to_person", "ship_to_street",
                  "ship_to_city", "ship_to_zip", "ship_to_country",
                  "ship_to_phone", "ship_to_email"):
        assert field in _OPTIONAL_STR_FIELDS, f"{field} not in _OPTIONAL_STR_FIELDS"


# ── SER01: Series pick ────────────────────────────────────────────────────────

def test_pick_proforma_series_id_returns_preferred():
    from app.services.customer_master import pick_proforma_series_id
    from app.services.customer_master_db import CustomerMaster
    c = CustomerMaster(
        bill_to_contractor_id="S001", bill_to_name="Test", country="PL",
        preferred_proforma_series_id="42",
    )
    assert pick_proforma_series_id(c) == "42"

def test_pick_proforma_series_id_returns_default_when_none():
    from app.services.customer_master import pick_proforma_series_id
    from app.services.customer_master_db import CustomerMaster
    c = CustomerMaster(bill_to_contractor_id="S002", bill_to_name="Test", country="PL")
    assert pick_proforma_series_id(c, default="99") == "99"
    assert pick_proforma_series_id(c) is None


# ── GATE01: Invoice gate source-grep ─────────────────────────────────────────

def test_invoice_gate_present_in_source():
    src = pathlib.Path(__file__).parents[1] / "app" / "api" / "routes_proforma.py"
    text = src.read_text()
    assert "WFIRMA_CREATE_INVOICE_ALLOWED" in text, "Invoice gate missing from routes_proforma"
    assert "wfirma_create_invoice_allowed" in text.lower(), "Config field missing"
    # Ensure the blocking response still exists (gate not removed)
    assert '"ok": False' in text or '"ok":False' in text or "'ok': False" in text or '"ok":             False' in text

def test_no_auto_invoice_path():
    """The runtime gate must appear before the live invoices/add HTTP call.

    The live POST to wFirma is ``wfirma_client._http_request(... "invoices", "add" ...)``.
    The gate is ``settings.wfirma_create_invoice_allowed``.  Find the first runtime
    guard check and the first live invoices/add call and assert ordering.
    """
    src = pathlib.Path(__file__).parents[1] / "app" / "api" / "routes_proforma.py"
    text = src.read_text()
    # Runtime guard: the if-not check, not the comment or doc reference
    gate_pos = text.find("if not settings.wfirma_create_invoice_allowed")
    # Live call: the actual HTTP POST to invoices/add (not a comment)
    # Identified by the _http_request call with "invoices", "add" arguments
    live_call_pos = text.find('"invoices", "add"')
    assert gate_pos != -1, "Runtime gate 'if not settings.wfirma_create_invoice_allowed' not found"
    assert live_call_pos != -1, "Live invoices/add call not found in routes_proforma"
    assert gate_pos < live_call_pos, (
        f"Gate (pos {gate_pos}) must appear before live invoices/add call (pos {live_call_pos})"
    )


# ── DESC01: Description format ───────────────────────────────────────────────

def test_build_description_line_slash_format():
    from app.services.description_engine import build_description_line
    result = build_description_line(
        "pierścionek z platyny próby 950",
        "Platinum Ring PT950"
    )
    assert " / " in result
    assert result.startswith("pierścionek z platyny próby 950")
    assert result.endswith("Platinum Ring PT950")

def test_build_description_line_no_english():
    from app.services.description_engine import build_description_line
    result = build_description_line("pierścionek", "")
    assert result == "pierścionek"
    assert " / " not in result
