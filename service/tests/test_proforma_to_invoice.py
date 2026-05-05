"""
test_proforma_to_invoice.py — pure-function tests for the proforma-to-invoice
projection. NEVER hits wFirma. Builds XML via the live-shape fixture below.
"""
from __future__ import annotations

import sys
from datetime import date
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

from app.services.proforma_to_invoice import (         # noqa: E402
    BACK_REFERENCE_TEMPLATE, FinalInvoicePlan, LineItem,
    NotAProforma, ProformaParseError, ProformaSnapshot,
    build_final_invoice_plan, build_final_invoice_xml,
    lines_match, parse_proforma_xml,
)


# ── Fixture: a minimal but realistic proforma XML response ──────────────────

def _proforma_xml(*,
                  pid: str = "98712989",
                  pnum: str = "PROF 90/2026",
                  ptype: str = "proforma",
                  contractor_id: str = "38582303",
                  currency: str = "USD",
                  fx: str = "4.000000",
                  pm: str = "transfer",
                  paydate: str = "2026-05-10",
                  pdate: str = "2026-05-03",
                  series: str = "15827088",
                  ca: str = "169589",
                  lang: str = "1",
                  receiver: str = "",
                  description: str = "Test proforma",
                  total: str = "120.00",
                  netto: str = "120.00",
                  extra_lines: str = "") -> str:
    receiver_block = (f"<contractor_receiver><id>{receiver}</id></contractor_receiver>"
                      if receiver else "")
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{pid}</id>
      <fullnumber>{pnum}</fullnumber>
      <type>{ptype}</type>
      <date>{pdate}</date>
      <paymentdate>{paydate}</paymentdate>
      <paymentmethod>{pm}</paymentmethod>
      <currency>{currency}</currency>
      <price_currency_exchange>{fx}</price_currency_exchange>
      <total>{total}</total>
      <netto>{netto}</netto>
      <description>{description}</description>
      <contractor><id>{contractor_id}</id></contractor>
      {receiver_block}
      <series><id>{series}</id></series>
      <company_account><id>{ca}</id></company_account>
      <translation_language><id>{lang}</id></translation_language>
      <invoicecontents>
        <invoicecontent>
          <name>Silver pendant</name>
          <good><id>48461283</id></good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>25.00</price>
          <vat_code><id>229</id></vat_code>
        </invoicecontent>
        <invoicecontent>
          <name>Fedex Courier</name>
          <good><id>13002743</id></good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>75.00</price>
          <vat_code><id>229</id></vat_code>
        </invoicecontent>
        <invoicecontent>
          <name>Insurance</name>
          <good><id>13102217</id></good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>20.00</price>
          <vat_code><id>229</id></vat_code>
        </invoicecontent>
        {extra_lines}
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


# ── parse_proforma_xml ──────────────────────────────────────────────────────

def test_parse_extracts_all_fields():
    snap = parse_proforma_xml(_proforma_xml())
    assert snap.proforma_id == "98712989"
    assert snap.proforma_number == "PROF 90/2026"
    assert snap.type == "proforma"
    assert snap.contractor_id == "38582303"
    assert snap.currency == "USD"
    assert snap.price_currency_exchange == "4.000000"
    assert snap.paymentmethod == "transfer"
    assert snap.paymentdate == "2026-05-10"
    assert snap.date == "2026-05-03"
    assert snap.series_id == "15827088"
    assert snap.company_account_id == "169589"
    assert snap.translation_language_id == "1"
    assert snap.contractor_receiver_id is None
    assert snap.total == Decimal("120.00")
    assert snap.netto == Decimal("120.00")
    assert len(snap.contents) == 3


def test_parse_extracts_contractor_receiver_when_present():
    snap = parse_proforma_xml(_proforma_xml(receiver="99999"))
    assert snap.contractor_receiver_id == "99999"


def test_parse_treats_zero_id_as_none():
    """wFirma uses <id>0</id> as a sentinel for 'no value' on optional id
    fields. Treat zero exactly like missing — never emit <id>0</id>."""
    snap = parse_proforma_xml(_proforma_xml(receiver="0", ca="0", lang="0"))
    assert snap.contractor_receiver_id is None
    assert snap.company_account_id is None
    assert snap.translation_language_id is None


def test_xml_omits_blocks_when_wfirma_sent_zero_sentinel():
    snap = parse_proforma_xml(_proforma_xml(receiver="0", ca="0", lang="0"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<contractor_receiver>" not in xml
    assert "<company_account>" not in xml
    assert "<translation_language>" not in xml


def test_parse_extracts_line_items_verbatim():
    snap = parse_proforma_xml(_proforma_xml())
    assert snap.contents[0].good_id == "48461283"
    assert snap.contents[0].price == "25.00"
    assert snap.contents[1].good_id == "13002743"      # freight
    assert snap.contents[1].price == "75.00"
    assert snap.contents[2].good_id == "13102217"      # insurance
    assert snap.contents[2].price == "20.00"
    for line in snap.contents:
        assert line.vat_code_id == "229"
        assert line.unit_count == "1.0000"


def test_parse_blocks_non_proforma_type():
    with pytest.raises(NotAProforma):
        parse_proforma_xml(_proforma_xml(ptype="normal"))


@pytest.mark.parametrize("missing_tag", [
    "<id>98712989</id>",
    "<fullnumber>PROF 90/2026</fullnumber>",
    "<type>proforma</type>",
    "<currency>USD</currency>",
    "<paymentmethod>transfer</paymentmethod>",
    "<paymentdate>2026-05-10</paymentdate>",
    "<date>2026-05-03</date>",
])
def test_parse_blocks_missing_required_field(missing_tag):
    xml = _proforma_xml().replace(missing_tag, "")
    with pytest.raises(ProformaParseError):
        parse_proforma_xml(xml)


def test_parse_blocks_missing_contractor_id():
    xml = _proforma_xml().replace("<contractor><id>38582303</id></contractor>",
                                  "<contractor></contractor>")
    with pytest.raises(ProformaParseError, match="contractor"):
        parse_proforma_xml(xml)


def test_parse_blocks_zero_lines():
    xml = _proforma_xml()
    # Strip all line items
    import re
    xml2 = re.sub(r"<invoicecontents>.*</invoicecontents>",
                  "<invoicecontents></invoicecontents>", xml, flags=re.DOTALL)
    with pytest.raises(ProformaParseError, match="invoicecontent"):
        parse_proforma_xml(xml2)


def test_parse_blocks_line_missing_good_id():
    bad_line = """<invoicecontent>
        <name>Bad</name><unit>szt.</unit><unit_count>1</unit_count>
        <price>1</price><vat_code><id>229</id></vat_code>
    </invoicecontent>"""
    xml = _proforma_xml(extra_lines=bad_line)
    with pytest.raises(ProformaParseError, match="good"):
        parse_proforma_xml(xml)


def test_parse_blocks_garbage_input():
    with pytest.raises(ProformaParseError):
        parse_proforma_xml("not xml at all")


# ── build_final_invoice_plan ────────────────────────────────────────────────

def test_plan_type_flips_to_normal():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    assert plan.type == "normal"


def test_plan_uses_operator_series_not_proforma_series():
    snap = parse_proforma_xml(_proforma_xml(series="15827088"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    assert plan.series_id == "15827921"


def test_plan_back_reference_always_prepended():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    expected = BACK_REFERENCE_TEMPLATE.format(pnum="PROF 90/2026", pid="98712989")
    assert plan.description.startswith(expected)


def test_plan_back_reference_appears_with_operator_description():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(
        snap, final_series_id="15827921", invoice_date=date(2026, 6, 1),
        operator_description="Final invoice for shipment May 2026",
    )
    assert plan.description.startswith("Final invoice issued based on proforma PROF 90/2026")
    assert "shipment May 2026" in plan.description


def test_plan_back_reference_appears_when_proforma_description_blank():
    snap = parse_proforma_xml(_proforma_xml(description=""))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    assert plan.description.startswith("Final invoice issued based on proforma")


def test_plan_uses_proforma_paymentdate_by_default():
    snap = parse_proforma_xml(_proforma_xml(paydate="2026-05-10"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    assert plan.paymentdate == "2026-05-10"


def test_plan_paymentdate_overridable():
    snap = parse_proforma_xml(_proforma_xml(paydate="2026-05-10"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1),
                                    paymentdate="2026-07-01")
    assert plan.paymentdate == "2026-07-01"


def test_plan_invoice_date_defaults_to_today():
    """Without invoice_date, use today (UTC). We just check it's an iso date."""
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921")
    # Confirm it's parseable as ISO date
    assert date.fromisoformat(plan.date) is not None


def test_plan_copies_lines_unchanged():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    assert len(plan.contents) == 3
    ok, diffs = lines_match(plan.contents, snap.contents)
    assert ok, diffs


def test_plan_blocks_missing_series_id():
    snap = parse_proforma_xml(_proforma_xml())
    with pytest.raises(ValueError, match="final_series_id is required"):
        build_final_invoice_plan(snap, final_series_id="",
                                 invoice_date=date(2026, 6, 1))


def test_plan_carries_source_proforma_for_audit():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    assert plan.source_proforma_id == "98712989"
    assert plan.source_proforma_number == "PROF 90/2026"
    assert plan.expected_total == Decimal("120.00")


# ── build_final_invoice_xml ─────────────────────────────────────────────────

def test_xml_starts_with_declaration_and_root():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<api>" in xml and "</api>" in xml.rstrip()
    assert "<invoices>" in xml and "</invoices>" in xml


def test_xml_contains_type_normal_not_proforma():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<type>normal</type>" in xml
    assert "<type>proforma</type>" not in xml


def test_xml_contains_back_reference_in_description():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "based on proforma PROF 90/2026" in xml


def test_xml_carries_all_lines_with_correct_good_ids():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    # All three good ids must appear
    for gid in ("48461283", "13002743", "13102217"):
        assert f"<id>{gid}</id>" in xml


def test_xml_uses_operator_series_id():
    snap = parse_proforma_xml(_proforma_xml(series="15827088"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<series><id>15827921</id></series>" in xml
    # The proforma series id should NOT appear
    assert "<id>15827088</id>" not in xml


def test_xml_carries_company_account_and_language_when_present():
    snap = parse_proforma_xml(_proforma_xml(ca="169589", lang="3"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<company_account><id>169589</id></company_account>" in xml
    assert "<translation_language><id>3</id></translation_language>" in xml


def test_xml_omits_company_account_when_absent():
    xml_in = _proforma_xml().replace(
        "<company_account><id>169589</id></company_account>", "")
    snap = parse_proforma_xml(xml_in)
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<company_account>" not in xml


def test_xml_carries_contractor_receiver_when_present():
    snap = parse_proforma_xml(_proforma_xml(receiver="99999"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<contractor_receiver><id>99999</id></contractor_receiver>" in xml


def test_xml_omits_contractor_receiver_when_absent():
    snap = parse_proforma_xml(_proforma_xml(receiver=""))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<contractor_receiver>" not in xml


def test_xml_carries_currency_and_fx():
    snap = parse_proforma_xml(_proforma_xml(currency="EUR", fx="4.300000"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    xml = build_final_invoice_xml(plan)
    assert "<currency>EUR</currency>" in xml
    assert "<price_currency_exchange>4.300000</price_currency_exchange>" in xml


def test_xml_uses_operator_invoice_date():
    snap = parse_proforma_xml(_proforma_xml(pdate="2026-05-03"))
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 15))
    xml = build_final_invoice_xml(plan)
    assert "<date>2026-06-15</date>" in xml


def test_xml_emission_blocks_when_type_not_normal():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(snap, final_series_id="15827921",
                                    invoice_date=date(2026, 6, 1))
    bad = FinalInvoicePlan(**{**plan.__dict__, "type": "proforma"})
    with pytest.raises(ValueError, match="must be 'normal'"):
        build_final_invoice_xml(bad)


def test_xml_escapes_special_chars_in_description():
    snap = parse_proforma_xml(_proforma_xml())
    plan = build_final_invoice_plan(
        snap, final_series_id="15827921", invoice_date=date(2026, 6, 1),
        operator_description="Bracket <test> & 'quote' \"double\"",
    )
    xml = build_final_invoice_xml(plan)
    assert "&lt;test&gt;" in xml
    assert "&amp;" in xml
    assert "&apos;" in xml
    assert "&quot;" in xml


# ── lines_match ──────────────────────────────────────────────────────────────

def test_lines_match_identical():
    snap = parse_proforma_xml(_proforma_xml())
    ok, diffs = lines_match(snap.contents, snap.contents)
    assert ok is True
    assert diffs == []


def test_lines_match_detects_price_change():
    snap = parse_proforma_xml(_proforma_xml())
    altered = list(snap.contents)
    altered[0] = LineItem(**{**altered[0].__dict__, "price": "30.00"})
    ok, diffs = lines_match(snap.contents, altered)
    assert ok is False
    assert any("price" in d for d in diffs)


def test_lines_match_detects_count_mismatch():
    snap = parse_proforma_xml(_proforma_xml())
    ok, diffs = lines_match(snap.contents, snap.contents[:2])
    assert ok is False
    assert any("count" in d for d in diffs)


# ── No I/O leak ──────────────────────────────────────────────────────────────

def test_module_does_not_import_wfirma_client():
    import app.services.proforma_to_invoice as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "wfirma_client" not in src
    assert "import requests" not in src
