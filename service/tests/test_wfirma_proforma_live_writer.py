"""
test_wfirma_proforma_live_writer.py — guard tests for the proforma live writer.
NEVER hits wFirma. http_sender + fetch_terms_fn are injected.
"""
from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.models.proforma_resolver import ContractorTerms             # noqa: E402
from app.tools import send_wfirma_proforma_live_test as snd           # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────

def _good_terms_for_target():
    """Return contractor terms that pass resolution."""
    t = snd.get_target("sd-no-test")
    return ContractorTerms(
        contractor_id  = t.contractor_id,
        payment_method = "transfer",
        payment_days   = 7,
    )


# ── Constants are locked ──────────────────────────────────────────────────

def test_constants_locked():
    assert snd.REQUIRED_FLAG          == "--live-confirm-I-understand"
    assert snd.REQUIRED_CONFIRMATION  == "YES_CREATE_ONE_TEST_PROFORMA"
    assert snd.WFIRMA_INVOICES_MODULE == "invoices"
    assert snd.WFIRMA_INVOICES_ACTION == "add"
    assert snd.PROFORMA_SERIES_ID     == "15827088"
    assert snd.PROFORMA_WAREHOUSE_ID  == "0"


def test_target_registry_has_only_vetted_target():
    assert snd.list_targets() == ["sd-no-test"]


def test_target_sd_no_test_data_locked():
    t = snd.get_target("sd-no-test")
    assert t.contractor_id          == "38582303"
    assert t.customer_country       == "NO"
    assert t.wfirma_good_id         == "48461283"
    assert t.product_code           == "EJL/26-27/015-3"
    assert t.currency               == "USD"
    assert t.qty                    == Decimal("1")
    assert t.unit_price             == Decimal("25.00")
    assert "Wisiorek" in t.line_name
    assert "Silver LGD" in t.line_name


def test_unknown_target_rejected_at_argparse():
    with pytest.raises(SystemExit):
        snd.main(argv=["--target", "made-up"], input_stream=io.StringIO(""))


# ── XML body validation ────────────────────────────────────────────────────

def test_xml_well_formed_and_uses_invoices_wrapper():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(
        vat_code_id        = 229,
        language_id        = "1",
        company_account_id = "169589",
        payment_method     = "transfer",
        payment_days       = 7,
        payment_date       = date(2026, 5, 10),
    )
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    assert root.tag == "api"
    inv = root.find("invoices/invoice")
    assert inv is not None


def test_xml_required_document_fields():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(
        vat_code_id        = 229,
        language_id        = "1",
        company_account_id = "169589",
        payment_method     = "transfer",
        payment_days       = 7,
        payment_date       = date(2026, 5, 10),
    )
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    inv = root.find("invoices/invoice")

    assert inv.findtext("type")       == "proforma"
    assert inv.findtext("date")       == "2026-05-03"
    assert inv.findtext("paymentdate")== "2026-05-10"
    assert inv.findtext("currency")   == "USD"
    assert inv.findtext("vat_payer")  == "1"
    assert inv.findtext("price_type") == "netto"
    assert inv.findtext("paymentmethod") == "transfer"
    assert inv.find("contractor/id").text          == "38582303"
    assert inv.find("warehouse/id").text           == "0"
    assert inv.find("series/id").text              == snd.PROFORMA_SERIES_ID
    assert inv.find("company_account/id").text     == "169589"
    assert inv.find("translation_language/id").text == "1"


def test_xml_line_uses_invoicecontent_with_text_unit():
    """Line wrapper is <invoicecontent>; <unit> is plain text 'szt.' (NOT id ref).
    First line is the product."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    lines = root.findall("invoices/invoice/invoicecontents/invoicecontent")
    assert len(lines) == 3          # product + freight + insurance
    product = lines[0]
    assert product.findtext("unit") == "szt."
    assert product.find("good/id").text  == "48461283"
    assert product.find("vat_code/id").text == "229"
    assert product.findtext("name") == t.line_name
    assert product.findtext("unit_count") == "1.0000"
    assert product.findtext("price") == "25.00"


def test_xml_uses_dot_decimal_for_price_and_fx():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    assert "<price>25.00</price>" in xml
    assert "<price_currency_exchange>4.000000</price_currency_exchange>" in xml
    assert ",00" not in xml.split("<description>")[0]   # no comma decimal in numeric tags


def test_xml_does_not_have_invoice_finalization_fields():
    """Ensure no signature, fiscal, dispatch, or payment-recorded markers."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    forbidden = ["<signature>", "<fiscalization>", "<final_account>", "<paymentstate>",
                 "<alreadypaid>", "<receipt_fiscal>"]
    for tag in forbidden:
        assert tag not in xml, f"forbidden tag {tag!r} present"


# ── Pre-flight resolution ─────────────────────────────────────────────────

def test_preflight_uses_injected_fetch():
    t = snd.get_target("sd-no-test")
    captured_id = []
    def fake_fetch(cid):
        captured_id.append(cid)
        return _good_terms_for_target()
    terms, res = snd.preflight(t, date(2026, 5, 3), fetch_terms_fn=fake_fetch)
    assert captured_id == [t.contractor_id]
    assert res.vat_code_id == 229      # Norway → EXP 0%
    assert res.company_account_id == "169589"  # USD bank
    assert res.payment_method == "transfer"


def test_preflight_blocks_on_missing_payment_method():
    t = snd.get_target("sd-no-test")
    bad_terms = ContractorTerms(t.contractor_id, payment_method=None, payment_days=7)
    with pytest.raises(snd.ProformaResolutionBlocked, match="payment_method"):
        snd.preflight(t, date(2026, 5, 3), fetch_terms_fn=lambda _: bad_terms)


def test_preflight_blocks_on_missing_payment_days():
    t = snd.get_target("sd-no-test")
    bad_terms = ContractorTerms(t.contractor_id, payment_method="transfer", payment_days=None)
    with pytest.raises(snd.ProformaResolutionBlocked, match="payment_days"):
        snd.preflight(t, date(2026, 5, 3), fetch_terms_fn=lambda _: bad_terms)


# ── Dry-run path: no flag → no HTTP, but pre-flight runs ──────────────────

def test_dry_run_without_flag(capsys):
    sent = []
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75"],
        input_stream=io.StringIO(""),
        http_sender=lambda x: sent.append(x) or pytest.fail("must not send"),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert sent == []
    assert "DRY-RUN" in out
    assert "EXPECTED RESULT" in out
    assert "ROLLBACK" in out
    assert "EJL/26-27/015-3" in out
    # The plan must show every required field
    for required in ["endpoint", "contractor id", "country", "currency",
                     "vat_code_id", "company_account_id", "translation_language",
                     "payment_method", "payment_days", "paymentdate"]:
        assert required in out, f"missing {required!r} in dry-run output"


def test_dry_run_blocked_by_preflight_returns_7(capsys):
    bad_terms = ContractorTerms("38582303", payment_method=None, payment_days=None)
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: bad_terms,
    )
    err = capsys.readouterr().err
    assert rc == 7
    assert "PRE-FLIGHT BLOCKED" in err


def test_dry_run_connection_error_returns_5(capsys):
    def bad_fetch(_): raise ConnectionError("network down")
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=bad_fetch,
    )
    err = capsys.readouterr().err
    assert rc == 5
    assert "PRE-FLIGHT ERROR" in err


# ── Confirmation phrase guard ─────────────────────────────────────────────

@pytest.mark.parametrize("typed", [
    "", "yes", "Y", "YES_CREATE_ONE_TEST_proforma",
    " YES_CREATE_ONE_TEST_PROFORMA", "YES_CREATE_ONE_TEST_PROFORMA ",
    "YES_CREATE_ONE_TEST_PZ",          # the OTHER confirmation
    "YES_CREATE_ONE_TEST_GOOD",
    "YES_CREATE_ONE_TEST_RESERVATION",
])
def test_wrong_confirmation_aborts(capsys, typed):
    sent = []
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(typed + "\n"),
        http_sender=lambda x: sent.append(x),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 4
    assert sent == []
    assert "ABORTED" in err


# ── Happy path: exact phrase + resolved → exactly one send ────────────────

def test_exact_confirmation_sends_exactly_once(capsys):
    sent = []
    def stub_sender(xml_body):
        sent.append(xml_body)
        return snd.ProformaSendResult(
            ok=True, http_status=200, wfirma_status="OK", wfirma_message="",
            invoice_id="700001",
            raw_response='<api><status><code>OK</code></status>'
                         '<invoices><invoice><id>700001</id></invoice></invoices></api>',
        )
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        http_sender=stub_sender,
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert len(sent) == 1
    assert "invoice ID     : 700001" in out
    assert "✓ OK" in out
    # The XML sent must contain expected hard-coded values
    body = sent[0]
    assert "<type>proforma</type>" in body
    assert "<series>\n        <id>15827088</id>" in body
    assert "<warehouse>\n        <id>0</id>" in body
    assert "<good>\n            <id>48461283</id>" in body
    assert "<vat_code>\n            <id>229</id>" in body


# ── Failure response is non-zero ──────────────────────────────────────────

def test_failure_response_returns_nonzero(capsys):
    def stub_sender(xml_body):
        return snd.ProformaSendResult(
            ok=False, http_status=200, wfirma_status="INPUT ERROR",
            wfirma_message="", invoice_id=None,
            raw_response='<api><status><code>INPUT ERROR</code></status></api>',
        )
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        http_sender=stub_sender,
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "✗ FAILED" in out
    assert "INPUT ERROR" in out


# ── Response parser ──────────────────────────────────────────────────────

def test_parse_response_picks_up_invoice_id():
    body = ('<?xml version="1.0"?><api><status><code>OK</code></status>'
            '<invoices><invoice><id>4242</id></invoice></invoices></api>')
    r = snd._parse_response(200, body)
    assert r.ok is True
    assert r.invoice_id == "4242"


def test_parse_response_handles_input_error():
    body = ('<?xml version="1.0"?><api><status><code>INPUT ERROR</code>'
            '<message>bad payload</message></status></api>')
    r = snd._parse_response(200, body)
    assert r.ok is False
    assert r.invoice_id is None
    assert r.wfirma_status == "INPUT ERROR"
    assert "bad payload" in r.wfirma_message


def test_parse_response_handles_unparseable_text():
    r = snd._parse_response(500, "<<not xml>>")
    assert r.ok is False
    assert r.invoice_id is None


# ── Date override ────────────────────────────────────────────────────────

def test_date_override_changes_doc_and_payment_date(capsys):
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75", "--date", "2027-01-15"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "<date>2027-01-15</date>" in out
    # payment_days=7 → paymentdate=2027-01-22
    assert "<paymentdate>2027-01-22</paymentdate>" in out


# ── Insurance line ────────────────────────────────────────────────────────

def test_insurance_constants_locked():
    assert snd.INSURANCE_SERVICE_ID == "13102217"
    assert snd.INSURANCE_RATE       == Decimal("0.0035")
    # Per-customer min by VAT code
    assert snd.INSURANCE_MIN_BY_VAT_CODE == {
        222: Decimal("10"),
        228: Decimal("10"),
        229: Decimal("20"),
    }


def test_freight_constants_locked():
    assert snd.FREIGHT_SERVICE_ID == "13002743"
    assert snd.FREIGHT_LINE_NAME  == "Fedex Courier"


# EU (WDT 228) — minimum 10
@pytest.mark.parametrize("base,expected", [
    (Decimal("0"),       Decimal("10.00")),    # min
    (Decimal("100"),     Decimal("10.00")),    # 0.35 → min
    (Decimal("309.03"),  Decimal("10.00")),    # user's EU example
    (Decimal("2857.14"), Decimal("10.00")),    # 0.35% ≈ 10.00 — min holds
    (Decimal("2858"),    Decimal("10.00")),    # just past min boundary
    (Decimal("3000"),    Decimal("10.50")),    # pct kicks in
    (Decimal("5000"),    Decimal("17.50")),    # canonical
    (Decimal("47382.99"),Decimal("165.84")),
])
def test_calc_insurance_eu_wdt_min_10(base, expected):
    assert snd.calc_insurance(base, vat_code_id=228) == expected


# Non-EU (EXP 229) — minimum 20
@pytest.mark.parametrize("base,expected", [
    (Decimal("0"),       Decimal("20.00")),    # min
    (Decimal("465"),     Decimal("20.00")),    # user's NO example, 2020
    (Decimal("477"),     Decimal("20.00")),
    (Decimal("5000"),    Decimal("20.00")),    # 0.35% = 17.50 — min still wins
    (Decimal("5714.28"), Decimal("20.00")),    # 0.35% = 19.999... — still min
    (Decimal("5715"),    Decimal("20.00")),    # 20.0025 → still min after quantise
    (Decimal("6000"),    Decimal("21.00")),    # pct kicks in
    (Decimal("100000"),  Decimal("350.00")),
])
def test_calc_insurance_non_eu_exp_min_20(base, expected):
    assert snd.calc_insurance(base, vat_code_id=229) == expected


# PL domestic (222) — minimum 10
def test_calc_insurance_pl_domestic_min_10():
    assert snd.calc_insurance(Decimal("100"),  vat_code_id=222) == Decimal("10.00")
    assert snd.calc_insurance(Decimal("5000"), vat_code_id=222) == Decimal("17.50")


def test_calc_insurance_unknown_vat_blocks():
    with pytest.raises(ValueError, match="no insurance minimum"):
        snd.calc_insurance(Decimal("1000"), vat_code_id=999)


def test_calc_insurance_negative_base_raises():
    with pytest.raises(ValueError, match="must be >= 0"):
        snd.calc_insurance(Decimal("-1"), vat_code_id=228)


def test_insurance_min_for_vat_helper():
    assert snd.insurance_min_for_vat(222) == Decimal("10")
    assert snd.insurance_min_for_vat(228) == Decimal("10")
    assert snd.insurance_min_for_vat(229) == Decimal("20")
    with pytest.raises(ValueError, match="no insurance minimum"):
        snd.insurance_min_for_vat(7777)


def test_xml_contains_three_invoicecontent_lines():
    """Product line + freight line + insurance line = 3 invoicecontent entries."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    lines = root.findall("invoices/invoice/invoicecontents/invoicecontent")
    assert len(lines) == 3


def test_xml_insurance_line_has_correct_fields():
    """Second line is the insurance service: good_id=13102217, unit_count=1,
    price=insurance_amount, vat_code matches the proforma's vat_code."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("17.50"))
    root = ET.fromstring(xml)
    lines = root.findall("invoices/invoice/invoicecontents/invoicecontent")
    insurance = lines[2]    # product=0, freight=1, insurance=2
    assert insurance.find("good/id").text   == "13102217"
    assert insurance.find("vat_code/id").text == "229"   # matches proforma's vat_code
    assert insurance.findtext("unit_count") == "1.0000"
    assert insurance.findtext("price") == "17.50"
    assert insurance.findtext("unit") == "szt."
    assert "Insurance" in insurance.findtext("name")
    assert "Ubezpieczenie" in insurance.findtext("name")


def test_xml_insurance_vat_code_matches_for_eu_wdt():
    """If proforma is WDT (228), insurance line must also be 228 — never 222."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(228, "1", "194483", "transfer", 14, date(2026, 5, 17))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    lines = root.findall("invoices/invoice/invoicecontents/invoicecontent")
    assert lines[0].find("vat_code/id").text == "228"
    assert lines[1].find("vat_code/id").text == "228"   # freight
    assert lines[2].find("vat_code/id").text == "228"   # insurance


def test_xml_insurance_vat_code_matches_for_pl_domestic():
    """PL → both lines vat_code 222 (23%)."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(222, "1", "180686", "transfer", 14, date(2026, 5, 17))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    for ln in root.findall("invoices/invoice/invoicecontents/invoicecontent"):
        assert ln.find("vat_code/id").text == "222"


def test_build_xml_blocks_when_insurance_service_id_missing():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    for missing in ("", None):
        with pytest.raises(ValueError, match="insurance_service_id is required"):
            snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                   insurance_service_id=missing,
                                   insurance_amount=Decimal("10.00"))


def test_build_xml_blocks_when_insurance_amount_zero_or_negative():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    for amount in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="insurance_amount must be > 0"):
            snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                   insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                   insurance_amount=amount)


def test_main_blocks_when_module_insurance_id_blank(monkeypatch, capsys):
    monkeypatch.setattr(snd, "INSURANCE_SERVICE_ID", "")
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 7
    assert "INSURANCE_SERVICE_ID" in err
    assert "not configured" in err


def test_main_blocks_when_module_freight_id_blank(monkeypatch, capsys):
    monkeypatch.setattr(snd, "FREIGHT_SERVICE_ID", "")
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 7
    assert "FREIGHT_SERVICE_ID" in err


def test_main_blocks_when_no_freight_history_and_no_override(tmp_path, capsys, monkeypatch):
    """If --freight is omitted AND DB is empty AND wFirma has no freight match,
    the resolver raises FreightUnresolved → main returns rc=8."""
    # Force resolver to use a fresh tmp DB (empty)
    empty_db = tmp_path / "empty.sqlite"
    # And stub the live wFirma search to return None for both invoice + proforma
    from app.services import freight_resolver as fr
    monkeypatch.setattr(fr, "find_freight_in_wfirma", lambda *a, **k: None)

    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight-db", str(empty_db)],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 8
    assert "No freight history" in err or "PRE-FLIGHT BLOCKED" in err


def test_main_freight_resolved_from_db_no_arg_needed(tmp_path, capsys, monkeypatch):
    """If freight history exists in DB, --freight is NOT required."""
    from app.services.freight_history_db import FreightRecord, init_db, save_freight_history
    db = tmp_path / "f.db"
    init_db(db)
    save_freight_history(db, FreightRecord(
        contractor_id="38582303", contractor_name="SD", country="NO", currency="USD",
        freight_service_id="13002743",
        freight_amount=Decimal("75.00"), source_type="invoice",
        source_doc_number="EXPORT 1/2020/EX", source_doc_date="2020-05-27",
    ))

    # wFirma must NOT be called when DB hit succeeds
    from app.services import freight_resolver as fr
    monkeypatch.setattr(fr, "find_freight_in_wfirma",
                        lambda *a, **k: pytest.fail("wFirma must not be called when DB has data"))

    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight-db", str(db)],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "75.00 USD" in out
    assert "source=db" in out
    assert "EXPORT 1/2020/EX" in out


@pytest.mark.parametrize("bad_freight", ["0", "-5", "abc", "0.0"])
def test_main_blocks_invalid_freight_amount(capsys, bad_freight):
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", bad_freight],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert ("--freight" in err or "valid decimal" in err)


def test_xml_contains_freight_line_with_correct_fields():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("85.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    root = ET.fromstring(xml)
    lines = root.findall("invoices/invoice/invoicecontents/invoicecontent")
    freight = lines[1]   # product=0, freight=1, insurance=2
    assert freight.find("good/id").text     == "13002743"
    assert freight.find("vat_code/id").text == "229"
    assert freight.findtext("unit_count")   == "1.0000"
    assert freight.findtext("price")        == "85.00"
    assert freight.findtext("unit")         == "szt."
    assert "Fedex" in freight.findtext("name")


def test_build_xml_blocks_when_freight_missing():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    for bad_id in ("", None):
        with pytest.raises(ValueError, match="freight_service_id is required"):
            snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                   freight_service_id=bad_id,
                                   freight_amount=Decimal("75"),
                                   insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                   insurance_amount=Decimal("10"))
    for bad_amt in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="freight_amount must be > 0"):
            snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                   freight_service_id=snd.FREIGHT_SERVICE_ID,
                                   freight_amount=bad_amt,
                                   insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                   insurance_amount=Decimal("10"))


def test_dry_run_plan_shows_freight_insurance_and_grand_total(capsys):
    """The CLI plan must show subtotal, freight, insurance calc, and grand total."""
    rc = snd.main(
        argv=["--target", "sd-no-test", "--freight", "75"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    out = capsys.readouterr().out
    assert rc == 0
    # target unit_price=25 USD qty=1 → subtotal 25; vat=229 (NO non-EU) → ins min 20
    # → freight 75 → grand total 25 + 75 + 20 = 120
    assert "product subtotal" in out
    assert "25.00 USD" in out
    assert "freight" in out.lower()
    assert "75.00 USD" in out
    assert "insurance amount" in out
    assert "20.00 USD" in out
    assert "GRAND TOTAL" in out
    assert "120.00 USD" in out


def test_xml_does_not_create_warehouse_or_reservation_side_effects():
    """Sanity: proforma XML never references warehouse_document, reservation,
    WZ, or any stock-modifying element. Insurance is a service (good_id pointing
    to type=service good) — it must not allocate stock."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10.00"))
    forbidden = [
        "<warehouse_document>", "<warehouse_documents>",
        "<warehouse_document_content>", "<warehouse_good_parcel",
        "<reservation>", "<warehouse_document_r>",
        "<warehouse_document_w_z>", "<final_account>",
    ]
    for tag in forbidden:
        assert tag not in xml, f"forbidden tag {tag!r} present in proforma XML"


# ── Layer 2: customer-master driven path ────────────────────────────────────

def _seed_cm(db_path, **overrides):
    """Helper: insert a customer master record for tests."""
    from app.services.customer_master_db import CustomerMaster, upsert_customer
    base = dict(
        bill_to_contractor_id  = "38582303",
        bill_to_name           = "Scandinavian Diamond",
        country                = "NO",
        default_currency       = "USD",
        default_language_id    = "1",
        insurance_min_override = Decimal("20"),
    )
    base.update(overrides)
    upsert_customer(db_path, CustomerMaster(**base))


def _stub_product_lookup(product_code, good_id):
    """Test stub: never hit wFirma."""
    return {
        "wfirma_good_id": "48461283",
        "name":           "Wisiorek ze srebra próby 925 z diamentami laboratoryjnymi / SL925 Silver LGD Diamond Pendant",
        "unit":           "szt.",
    }


def test_build_target_from_customer_master_uses_customer_defaults(tmp_path):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db)
    from app.services.customer_master import CustomerMasterResolver
    cm = CustomerMasterResolver(cm_db).require("38582303")

    target = snd.build_target_from_customer_master(
        cm,
        product_code     = "EJL/26-27/015-3",
        good_id          = None,
        qty              = Decimal("1"),
        unit_price       = Decimal("25.00"),
        fx_rate          = Decimal("4.0"),
        product_lookup_fn = _stub_product_lookup,
    )
    assert target.contractor_id          == "38582303"
    assert target.customer_country       == "NO"
    assert target.currency               == "USD"          # from cm
    assert target.wfirma_good_id         == "48461283"
    assert target.qty                    == Decimal("1")
    assert target.unit_price             == Decimal("25.00")
    assert target.price_currency_exchange == Decimal("4.0")
    assert "Wisiorek" in target.line_name


def test_build_target_blocks_when_customer_has_no_currency(tmp_path):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db, default_currency=None)
    from app.services.customer_master import CustomerMasterResolver
    cm = CustomerMasterResolver(cm_db).require("38582303")

    with pytest.raises(ValueError, match="default_currency"):
        snd.build_target_from_customer_master(
            cm, product_code="X", good_id=None, qty=Decimal("1"), unit_price=Decimal("1"),
            product_lookup_fn=_stub_product_lookup,
        )


def test_build_target_pln_skips_fx_requirement(tmp_path):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db, default_currency="PLN")
    from app.services.customer_master import CustomerMasterResolver
    cm = CustomerMasterResolver(cm_db).require("38582303")

    target = snd.build_target_from_customer_master(
        cm, product_code="X", good_id=None,
        qty=Decimal("1"), unit_price=Decimal("100"),
        product_lookup_fn=_stub_product_lookup,
    )
    assert target.currency == "PLN"
    assert target.price_currency_exchange == Decimal("1")


def test_build_target_non_pln_requires_fx_rate(tmp_path):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db)   # USD
    from app.services.customer_master import CustomerMasterResolver
    cm = CustomerMasterResolver(cm_db).require("38582303")
    with pytest.raises(ValueError, match="fx-rate is required"):
        snd.build_target_from_customer_master(
            cm, product_code="X", good_id=None,
            qty=Decimal("1"), unit_price=Decimal("25"),
            product_lookup_fn=_stub_product_lookup,
        )


# ── Ship-to XML rendering — all 3 shapes ────────────────────────────────────

def test_contractor_receiver_block_none_emits_id_zero():
    block = snd.build_contractor_receiver_block("none", None)
    assert "<contractor_receiver>" in block
    assert "<id>0</id>" in block


def test_contractor_receiver_block_alternate_emits_id_zero():
    """Alternate-address shape: ship-to lives on the contractor's contact_*
    fields, so the proforma XML still uses id=0."""
    block = snd.build_contractor_receiver_block("alternate_address", None)
    assert "<id>0</id>" in block


def test_contractor_receiver_block_separate_emits_specific_id():
    block = snd.build_contractor_receiver_block("separate_contractor", "99999999")
    assert "<id>99999999</id>" in block


def test_contractor_receiver_block_separate_blocks_when_id_missing():
    with pytest.raises(ValueError, match="non-empty ship_to_contractor_id"):
        snd.build_contractor_receiver_block("separate_contractor", "")
    with pytest.raises(ValueError, match="non-empty ship_to_contractor_id"):
        snd.build_contractor_receiver_block("separate_contractor", None)


def test_xml_contains_contractor_receiver_block_default_none():
    """Every proforma XML must carry <contractor_receiver> (id=0 for shape none)."""
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("75"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("20"))
    root = ET.fromstring(xml)
    cr = root.find("invoices/invoice/contractor_receiver")
    assert cr is not None
    assert cr.findtext("id") == "0"


def test_xml_contractor_receiver_separate_contractor_id():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(228, "3", "194483", "transfer", 14, date(2026, 5, 17))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("85"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10"),
                                 ship_to_shape="separate_contractor",
                                 ship_to_contractor_id="44444444")
    root = ET.fromstring(xml)
    assert root.find("invoices/invoice/contractor_receiver/id").text == "44444444"


def test_xml_contractor_receiver_alternate_address_still_id_zero():
    t = snd.get_target("sd-no-test")
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(228, "3", "194483", "transfer", 14, date(2026, 5, 17))
    xml = snd.build_proforma_xml(t, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("85"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=Decimal("10"),
                                 ship_to_shape="alternate_address")
    root = ET.fromstring(xml)
    assert root.find("invoices/invoke/contractor_receiver") is None  # sanity: not under wrong path
    assert root.find("invoices/invoice/contractor_receiver/id").text == "0"


# ── Layer 2 main() integration tests ─────────────────────────────────────────

def test_main_bill_to_path_resolves_currency_lang_insurance_from_cm(tmp_path, capsys, monkeypatch):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db)   # USD, lang=1, insurance_min_override=20
    # Empty freight DB but inject manual freight via --freight
    fr_db = tmp_path / "fr.db"

    from app.services import freight_resolver as fr
    monkeypatch.setattr(fr, "find_freight_in_wfirma", lambda *a, **k: pytest.fail("must not search"))

    rc = snd.main(
        argv=["--bill-to", "38582303",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/26-27/015-3",
              "--qty", "1",
              "--unit-price", "25",
              "--fx-rate", "4.0",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # Customer master defaults applied
    assert "USD" in out
    assert "229" in out                                    # vat_code (Norway → EXP)
    assert "169589" in out                                 # USD bank account
    assert "20.00 USD" in out                              # insurance min from cm override
    assert "ship_to              : none" in out


def test_main_bill_to_emits_no_extra_ship_to_for_shape_none(tmp_path, capsys):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db)   # default ship_to_use_alternate=False, ship_to_contractor_id=None → none
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "38582303",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/26-27/015-3",
              "--qty", "1", "--unit-price", "25", "--fx-rate", "4",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # XML carries <contractor_receiver><id>0</id></contractor_receiver>
    assert "<contractor_receiver>" in out
    assert "<id>0</id>" in out
    # Plan label shows shape=none
    assert "ship_to              : none" in out


def test_main_bill_to_emits_separate_contractor_when_cm_has_ship_to_id(tmp_path, capsys):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db, ship_to_contractor_id="44444444")   # → SHIP_TO_SEPARATE_CONTRACTOR
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "38582303",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/26-27/015-3",
              "--qty", "1", "--unit-price", "25", "--fx-rate", "4",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # XML carries the separate receiver id
    assert "<contractor_receiver>" in out
    assert "<id>44444444</id>" in out
    assert "ship_to              : separate_contractor" in out
    assert "contractor_receiver.id = 44444444" in out


def test_main_bill_to_alternate_address_label_in_plan(tmp_path, capsys):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db,
             ship_to_use_alternate=True,
             ship_to_name="Warehouse",
             ship_to_street="Industrial Way 5",
             ship_to_city="Oslo",
             ship_to_country="NO")
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "38582303",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/26-27/015-3",
              "--qty", "1", "--unit-price", "25", "--fx-rate", "4",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # XML for alternate-address still uses id=0 (delivery comes from contractor's contact_* fields)
    assert "<id>0</id>" in out
    assert "ship_to              : alternate_address" in out
    assert "different_contact_address=1" in out


def test_main_bill_to_blocks_unknown_customer(tmp_path, capsys):
    cm_db = tmp_path / "cm.db"
    # No record inserted
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "99999999",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/X",
              "--qty", "1", "--unit-price", "25", "--fx-rate", "4",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    err = capsys.readouterr().err
    assert rc == 7
    assert "99999999" in err


def test_main_bill_to_requires_qty_and_unit_price(tmp_path, capsys):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db)
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "38582303",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/X", "--fx-rate", "4",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "qty" in err or "unit-price" in err


def test_main_blocks_both_target_and_bill_to(tmp_path, capsys):
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db)
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "38582303", "--target", "sd-no-test",
              "--customer-master-db", str(cm_db), "--freight-db", str(fr_db),
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "mutually exclusive" in err


def test_main_blocks_when_neither_target_nor_bill_to(tmp_path, capsys):
    rc = snd.main(
        argv=["--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "either --bill-to" in err


def test_main_bill_to_applies_insurance_min_override(tmp_path, capsys):
    """customer master insurance_min_override=20 wins for small subtotal."""
    cm_db = tmp_path / "cm.db"
    _seed_cm(cm_db, insurance_min_override=Decimal("50"))   # operator-set higher minimum
    fr_db = tmp_path / "fr.db"
    rc = snd.main(
        argv=["--bill-to", "38582303",
              "--customer-master-db", str(cm_db),
              "--freight-db", str(fr_db),
              "--product-code", "EJL/X",
              "--qty", "1", "--unit-price", "25", "--fx-rate", "4",
              "--freight", "85"],
        input_stream=io.StringIO(""),
        fetch_terms_fn=lambda _: _good_terms_for_target(),
        product_lookup_fn=_stub_product_lookup,
    )
    out = capsys.readouterr().out
    assert rc == 0
    # Customer override (50) beats vat-based default (20)
    assert "50.00 USD" in out
    assert "<price>50.00</price>" in out


def test_full_proforma_xml_for_5000usd_yields_17_50_insurance():
    """End-to-end shape: when product subtotal is 5000 USD, insurance line price is 17.50."""
    # Build a fresh target with USD 5000 on a single line for this test.
    big_target = snd.ProformaTarget(
        key                     = "big-test",
        target_description      = "Synthetic big test target (not registered)",
        contractor_id           = "38582303",
        customer_country        = "NO",
        customer_vat_eu_valid   = None,
        customer_vat_eu_number  = None,
        wfirma_good_id          = "48461283",
        product_code            = "EJL/26-27/015-3",
        line_name               = "test product",
        currency                = "USD",
        qty                     = Decimal("1"),
        unit_price              = Decimal("5000.00"),
        price_currency_exchange = Decimal("4.0000"),
        doc_description         = "synthetic",
    )
    from app.models.proforma_resolver import ProformaResolution
    res = ProformaResolution(229, "1", "169589", "transfer", 7, date(2026, 5, 10))
    subtotal = (big_target.qty * big_target.unit_price).quantize(Decimal("0.01"))
    # Non-EU customer (NO) uses vat 229 → min 20; 0.35% × 5000 = 17.50 → min wins → 20.00
    insurance = snd.calc_insurance(subtotal, vat_code_id=229)
    assert insurance == Decimal("20.00")
    xml = snd.build_proforma_xml(big_target, res, date(2026, 5, 3),
                                 freight_service_id=snd.FREIGHT_SERVICE_ID,
                                 freight_amount=Decimal("100.00"),
                                 insurance_service_id=snd.INSURANCE_SERVICE_ID,
                                 insurance_amount=insurance)
    assert "<price>20.00</price>" in xml
    assert "<price>5000.00</price>" in xml
    assert "<price>100.00</price>" in xml   # freight
