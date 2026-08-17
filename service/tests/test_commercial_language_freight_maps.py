"""Canonical language + freight-method maps (Polish=0, English=1,
Freight=17833901, Fedex Courier=13002743).

One authority: commercial_lookup. These ids are never aliases for each other.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import commercial_lookup as cl
from app.services.customer_master import pick_freight_service_id
from app.services.customer_master_db import CustomerMaster
from app.services.wfirma_client import ProformaRequest, ReservationLine, _build_proforma_xml


ROOT = Path(__file__).resolve().parents[1]
CLIENT_DETAIL = ROOT / "app" / "static" / "v2" / "client-detail.jsx"
PROFORMA_DETAIL = ROOT / "app" / "static" / "v2" / "proforma-detail.jsx"


def _cm(**overrides) -> CustomerMaster:
    base = dict(
        bill_to_contractor_id="C1",
        bill_to_name="Test",
        country="PL",
    )
    base.update(overrides)
    return CustomerMaster(**base)


def _req(**overrides) -> ProformaRequest:
    kwargs = dict(
        client_name="Test Client",
        client_zip="",
        client_city="",
        lines=[
            ReservationLine(
                product_code="TST-001",
                wfirma_good_id="WFG-001",
                product_name="Test",
                qty=1.0,
                unit_price=10.0,
                unit="szt.",
                currency="PLN",
            )
        ],
        currency="PLN",
        wfirma_contractor_id="WFC-001",
        vat_code_id="VAT-23",
    )
    kwargs.update(overrides)
    return ProformaRequest(**kwargs)


# ── Language map ──────────────────────────────────────────────────────────────


def test_canonical_language_ids_are_not_inverted():
    assert cl.WFIRMA_LANG_POLISH == "0"
    assert cl.WFIRMA_LANG_ENGLISH == "1"
    assert cl.WFIRMA_LANG_POLISH != cl.WFIRMA_LANG_ENGLISH
    assert cl.INTENDED_TRANSLATION_LANGUAGE_ID == "1"


@pytest.mark.parametrize("selection,expected", [
    ("Polish", "0"),
    ("polish", "0"),
    ("PL", "0"),
    ("pl", "0"),
    ("0", "0"),
    ("English", "1"),
    ("english", "1"),
    ("EN", "1"),
    ("en", "1"),
    ("1", "1"),
])
def test_map_language_selection(selection, expected):
    assert cl.map_language_selection(selection) == expected


def test_language_selection_does_not_invert_0_and_1():
    assert cl.map_language_selection("Polish") == "0"
    assert cl.map_language_selection("English") == "1"
    assert cl.map_language_selection("0") != "1"
    assert cl.map_language_selection("1") != "0"


def test_resolve_language_explicit_selection_wins_over_customer():
    assert cl.resolve_language_id(selection="Polish", customer_override="1") == "0"
    assert cl.resolve_language_id(selection="English", customer_override="0") == "1"


def test_resolve_language_customer_override_when_no_selection():
    assert cl.resolve_language_id(selection=None, customer_override="0") == "0"
    assert cl.resolve_language_id(selection=None, customer_override="1") == "1"
    assert cl.resolve_language_id(selection="", customer_override="2") == "2"


def test_invoice_languages_dropdown_is_polish_and_english():
    by_id = {str(x["id"]): x["label"] for x in cl.invoice_languages()}
    assert by_id["0"] == "Polish"
    assert by_id["1"] == "English"
    assert "2" not in by_id  # legacy English id is not a second selectable English


# ── Freight map ───────────────────────────────────────────────────────────────


def test_canonical_freight_ids_are_distinct():
    assert cl.FREIGHT_METHOD_FREIGHT == "17833901"
    assert cl.FREIGHT_METHOD_FEDEX_COURIER == "13002743"
    assert cl.FREIGHT_METHOD_DEFAULT == "13002743"
    assert cl.FREIGHT_METHOD_FREIGHT != cl.FREIGHT_METHOD_FEDEX_COURIER


@pytest.mark.parametrize("selection,expected", [
    ("Freight", "17833901"),
    ("freight", "17833901"),
    ("17833901", "17833901"),
    ("Fedex Courier", "13002743"),
    ("fedex courier", "13002743"),
    ("13002743", "13002743"),
])
def test_map_freight_method_selection(selection, expected):
    assert cl.map_freight_method_selection(selection) == expected


def test_freight_ids_are_never_translated_into_each_other():
    assert cl.map_freight_method_selection("17833901") == "17833901"
    assert cl.map_freight_method_selection("13002743") == "13002743"
    assert cl.resolve_freight_method_id(selection="Freight") != "13002743"
    assert cl.resolve_freight_method_id(selection="Fedex Courier") != "17833901"


def test_customer_freight_override_survives():
    assert cl.resolve_freight_method_id(
        selection="Fedex Courier",
        customer_override="17833901",
    ) == "17833901"
    assert cl.resolve_freight_method_id(
        selection="Freight",
        customer_override="13002743",
    ) == "13002743"


def test_freight_default_applies_only_when_no_override_or_selection():
    assert cl.resolve_freight_method_id() == "13002743"
    assert cl.resolve_freight_method_id(selection=None, customer_override=None) == "13002743"
    assert cl.resolve_freight_method_id(customer_override="17833901") == "17833901"


def test_pick_freight_service_id_preserves_customer_freight_override():
    c = _cm(freight_service_id="17833901")
    assert pick_freight_service_id(c, default="13002743") == "17833901"


def test_pick_freight_service_id_default_only_when_unset():
    c = _cm(freight_service_id=None)
    assert pick_freight_service_id(c, default="13002743") == "13002743"


def test_no_runtime_remap_between_freight_ids():
    """Source-grep: never assign one canonical freight id from the other."""
    needles = (
        'FREIGHT_METHOD_FREIGHT = "13002743"',
        'FREIGHT_METHOD_FEDEX_COURIER = "17833901"',
        '"17833901": "13002743"',
        '"13002743": "17833901"',
    )
    src = (ROOT / "app" / "services" / "commercial_lookup.py").read_text(encoding="utf-8")
    for n in needles:
        assert n not in src, n


# ── Serialized wFirma payload ─────────────────────────────────────────────────


def test_proforma_xml_emits_polish_as_0():
    xml = _build_proforma_xml(_req(translation_language_id="0"))
    assert "<translation_language><id>0</id></translation_language>" in xml
    assert "<translation_language><id>1</id></translation_language>" not in xml


def test_proforma_xml_emits_english_as_1():
    xml = _build_proforma_xml(_req(translation_language_id="1"))
    assert "<translation_language><id>1</id></translation_language>" in xml
    assert "<translation_language><id>0</id></translation_language>" not in xml


def test_proforma_xml_omits_language_when_blank():
    xml = _build_proforma_xml(_req(translation_language_id=""))
    assert "<translation_language>" not in xml


def test_proforma_xml_freight_line_keeps_freight_id():
    xml = _build_proforma_xml(_req(lines=[
        ReservationLine(
            product_code="FRT",
            wfirma_good_id="17833901",
            product_name="Freight",
            qty=1.0,
            unit_price=25.0,
        )
    ]))
    assert "<id>17833901</id>" in xml
    assert "13002743" not in xml


def test_proforma_xml_freight_line_keeps_fedex_courier_id():
    xml = _build_proforma_xml(_req(lines=[
        ReservationLine(
            product_code="FRT",
            wfirma_good_id="13002743",
            product_name="Fedex Courier",
            qty=1.0,
            unit_price=25.0,
        )
    ]))
    assert "<id>13002743</id>" in xml
    assert "17833901" not in xml


# ── UI read/edit surface ──────────────────────────────────────────────────────


def test_client_detail_language_dropdown_uses_canonical_labels():
    src = CLIENT_DETAIL.read_text(encoding="utf-8")
    assert 'data-testid="cd-default_language_id"' in src
    assert "dicts.languages" in src
    assert "cd-language-unresolved" in src


def test_client_detail_freight_method_is_named_dropdown():
    src = CLIENT_DETAIL.read_text(encoding="utf-8")
    assert 'data-testid="cd-freight_service_id"' in src
    assert "dicts.freight_methods" in src
    assert "Freight method" in src
    assert "inp('freight_service_id')" not in src
    assert "cd-freight-method-unresolved" in src


def test_proforma_language_fallback_is_polish_0_english_1():
    src = PROFORMA_DETAIL.read_text(encoding="utf-8")
    assert "{ id: '0', label: 'Polish' }" in src
    assert "{ id: '1', label: 'English' }" in src
    assert "{ id: '1', label: 'Polish (Polski)' }" not in src
    assert "{ id: '2', label: 'English' }" not in src
