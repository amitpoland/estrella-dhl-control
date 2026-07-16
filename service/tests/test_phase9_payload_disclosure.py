"""
test_phase9_payload_disclosure.py — Phase 9 evidence tests.

Verifies the payload-disclosure module for WF2.4 and WF2.5.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestProformaPostDisclosure:
    """build_proforma_post_disclosure returns a complete, JSON-serialisable dict."""

    def _make_draft(self) -> dict:
        return {
            "id": 42,
            "batch_id": "BATCH_001",
            "client_name": "Global Jewellery Pvt. Ltd.",
            "currency": "EUR",
            "incoterm": "DAP",
            "remarks": "",
            "editable_lines_json": json.dumps([
                {"product_code": "EJL/26-27/100-1", "design_no": "RING-A",
                 "qty": 5, "unit_price": 120.0, "currency": "EUR"},
                {"product_code": "EJL/26-27/100-2", "design_no": "EARRING-B",
                 "qty": 10, "unit_price": 80.0, "currency": "EUR"},
            ]),
            "service_charges_json": "[]",
            "draft_state": "approved",
            "status": "approved",
        }

    def test_disclosure_is_json_serialisable(self):
        from app.services.payload_disclosure import build_proforma_post_disclosure
        d = build_proforma_post_disclosure(self._make_draft())
        json_str = json.dumps(d)
        assert "disclosure_type" in json_str
        assert "proforma_post" in json_str

    def test_disclosure_has_required_fields(self):
        from app.services.payload_disclosure import build_proforma_post_disclosure
        d = build_proforma_post_disclosure(self._make_draft())
        assert d["disclosure_type"] == "proforma_post"
        assert d["flag_required"]   == "WFIRMA_CREATE_PROFORMA_ALLOWED"
        assert d["confirm_token_required"] == "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"
        assert "warning" in d
        assert "lines" in d
        assert len(d["lines"]) == 2

    def test_disclosure_shows_client_name(self):
        from app.services.payload_disclosure import build_proforma_post_disclosure
        d = build_proforma_post_disclosure(self._make_draft())
        assert d["fields_to_write"]["client_name"] == "Global Jewellery Pvt. Ltd."

    def test_disclosure_never_calls_wfirma(self):
        """No wFirma live call in the source — confirmed by source-grep."""
        src = (Path(__file__).parent.parent / "app" / "services" / "payload_disclosure.py"
               ).read_text(encoding="utf-8")
        assert "wfirma_client" not in src
        assert "_http_request" not in src
        # The string "invoices/add" appears in the docstring describing WHAT will be
        # written (disclosure text) — it's fine as a label. The key check is no API call.
        # Verify no actual HTTP call pattern exists:
        assert "requests." not in src
        assert "httpx." not in src


def _proforma_xml_3lines(pnum="PROF 92/2026", pid="99990001snap",
                          contractor_id="99990001", currency="EUR") -> str:
    """3-line proforma XML fixture reused across disclosure tests.
    Lines: Silver pendant 25.00 + Fedex Courier 75.00 + Insurance 20.00 = 120.00.
    Mirrors the fixture in test_proforma_to_invoice.py (Lesson A real-builder).
    """
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{pid}</id>
      <fullnumber>{pnum}</fullnumber>
      <type>proforma</type>
      <date>2026-05-03</date>
      <paymentdate>2026-05-10</paymentdate>
      <paymentmethod>transfer</paymentmethod>
      <currency>{currency}</currency>
      <price_currency_exchange>1.000000</price_currency_exchange>
      <total>120.00</total>
      <netto>120.00</netto>
      <description>Test proforma</description>
      <contractor><id>{contractor_id}</id></contractor>
      <series><id>15827088</id></series>
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
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


class TestInvoiceConvertDisclosure:
    """build_invoice_convert_disclosure for WF2.5.

    Lesson A (real-builder test): _make_snap() builds a REAL ProformaSnapshot
    via parse_proforma_xml() — no dict stub.  The 3-line fixture (pendant 25.00 +
    courier 75.00 + insurance 20.00 = 120.00) matches the canonical fixture in
    test_proforma_to_invoice.py.
    """

    def _make_snap(self):
        """Build a real ProformaSnapshot from live-shape XML (Lesson A)."""
        from app.services.proforma_to_invoice import parse_proforma_xml
        return parse_proforma_xml(_proforma_xml_3lines())

    def test_invoice_disclosure_has_required_fields(self):
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap(), final_series_id="777",
                                             operator="amit")
        assert d["disclosure_type"] == "invoice_convert"
        assert d["flag_required"]   == "WFIRMA_CREATE_INVOICE_ALLOWED"
        assert d["confirm_token_required"] == "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
        assert d["source_proforma"]  == "PROF 92/2026"
        assert d["fields_to_write"]["series_id"] == "777"
        assert "IRREVERSIBLE" in d["warning"]

    def test_invoice_disclosure_shows_lines(self):
        """RC-1 fix: disclosure reads snap.contents (not snap.lines) and uses
        correct LineItem field names (good_id, unit_count, price)."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        assert len(d["lines"]) == 3, (
            "Disclosure must expose all 3 lines from snap.contents; "
            f"got {len(d['lines'])}"
        )
        assert d["lines"][0]["good_id"] == "48461283"

    # ── RC-1 new tests (Lesson A regression pins) ─────────────────────────────

    def test_line_count_matches_real_snap(self):
        """line_count in fields_to_write == len(snap.contents) == 3."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        assert d["fields_to_write"]["line_count"] == 3

    def test_lines_use_correct_field_names(self):
        """Each line dict has good_id / name / unit_count / price — not wfirma_good_id / qty."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        line0 = d["lines"][0]
        assert "good_id"    in line0, "RC-1: good_id missing from line projection"
        assert "unit_count" in line0, "RC-1: unit_count missing from line projection"
        assert "price"      in line0, "RC-1: price missing from line projection"
        assert "name"       in line0, "RC-1: name missing from line projection"
        # Old stub field names must NOT appear
        assert "wfirma_good_id" not in line0
        assert "qty"            not in line0
        assert "unit_price"     not in line0

    def test_grand_total_sums_all_three_lines(self):
        """grand_total = 25.00 + 75.00 + 20.00 = 120.00 (freight + insurance included)."""
        from decimal import Decimal
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        assert "grand_total" in d, "RC-4 prerequisite: grand_total key must be present"
        assert Decimal(d["grand_total"]) == Decimal("120.00"), (
            f"Expected 120.00, got {d['grand_total']} — freight/insurance lines may be missing"
        )
        assert d["grand_total_currency"] == "EUR"

    def test_empty_resolved_series_hashes_empty_not_snap_series(self):
        """Opus review D-1 regression: final_series_id="" (ADR-027 D6 step 3 —
        validly resolved to EMPTY) must hash "" and must NOT fall back to the
        proforma's own series. Otherwise the disclosure hash never matches the
        execute hash and every hash-guarded convert is blocked for customers
        without a Customer Master invoice series."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        from app.services.proforma_to_invoice import compute_conversion_core_hash
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(snap, final_series_id="")
        assert d["fields_to_write"]["series_id"] == "", (
            "Resolved-empty series must not fall back to the proforma's series"
        )
        assert d["fields_to_write"]["series_name"] == "wFirma contractor default"
        expected = compute_conversion_core_hash(
            snap.contractor_id, snap.currency, "", snap.contents,
        )
        assert d["payload_core_hash"] == expected, (
            "Disclosure hash must equal the execute-path hash for empty series"
        )

    def test_legacy_none_series_falls_back_to_snap_series(self):
        """final_series_id=None (unspecified) keeps the legacy fallback to the
        snap's own series — only the explicit empty string means D6 step 3."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(snap)
        assert d["fields_to_write"]["series_id"] == snap.series_id

    def test_payload_core_hash_present_and_stable(self):
        """RC-4: payload_core_hash is present, non-empty, and deterministic."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d1 = build_invoice_convert_disclosure(snap, final_series_id="777")
        d2 = build_invoice_convert_disclosure(snap, final_series_id="777")
        assert "payload_core_hash" in d1, "RC-4: payload_core_hash key must be present"
        assert len(d1["payload_core_hash"]) == 64, (
            "Expected SHA-256 hex digest (64 chars)"
        )
        assert d1["payload_core_hash"] == d2["payload_core_hash"], (
            "Hash must be deterministic for the same inputs"
        )

    def test_payload_core_hash_changes_when_series_changes(self):
        """Different series_id produces different hash."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d_a = build_invoice_convert_disclosure(snap, final_series_id="AAA")
        d_b = build_invoice_convert_disclosure(snap, final_series_id="BBB")
        assert d_a["payload_core_hash"] != d_b["payload_core_hash"]

    def test_series_name_key_present(self):
        """RC-4: series_name key present (may be empty if cache cold)."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap(), final_series_id="777")
        assert "series_name" in d, "series_name key must be present in disclosure"

    # ── payment_resolved block ────────────────────────────────────────────────
    # NOTE: These tests use inline dicts (not self._make_snap()) because they
    # test payment-method resolution logic, not line content. build_invoice_convert_disclosure
    # accepts Any via _get(), so dict input is valid for these cases.

    def test_payment_resolved_key_present(self):
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        assert "payment_resolved" in d
        pr = d["payment_resolved"]
        assert "method" in pr
        assert "payment_date" in pr
        assert "source" in pr

    def test_payment_resolved_wfirma_polish_mapped_to_english(self):
        """snap.paymentmethod in wFirma Polish form → English in disclosure."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {"currency": "EUR", "paymentmethod": "przelew", "paymentdate": "2026-07-28"}
        d = build_invoice_convert_disclosure(snap)
        pr = d["payment_resolved"]
        assert pr["method"] == "transfer"
        assert pr["payment_date"] == "2026-07-28"
        assert pr["source"] == "wfirma_proforma"

    def test_payment_resolved_all_polish_forms(self):
        """All four wFirma payment codes map to their English equivalents."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        mapping = {
            "przelew": "transfer",
            "gotowka": "cash",
            "karta": "card",
            "kompensata": "compensation",
        }
        for wf_form, en_form in mapping.items():
            snap = {"currency": "EUR", "paymentmethod": wf_form}
            d = build_invoice_convert_disclosure(snap)
            assert d["payment_resolved"]["method"] == en_form, \
                f"Expected {en_form!r} for wFirma form {wf_form!r}"

    def test_payment_resolved_falls_back_to_customer_master(self):
        """When snap has no paymentmethod, customer_default_method is used."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {"currency": "EUR", "paymentmethod": "", "paymentdate": ""}
        d = build_invoice_convert_disclosure(
            snap, customer_default_method="cash", customer_default_days=14
        )
        pr = d["payment_resolved"]
        assert pr["method"] == "cash"
        assert pr["source"] == "customer_master"
        assert pr["customer_default_method"] == "cash"
        assert pr["customer_default_days"] == 14

    def test_payment_resolved_snap_takes_priority_over_customer_master(self):
        """wFirma proforma payment method wins over customer master default."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {"currency": "EUR", "paymentmethod": "kompensata"}
        d = build_invoice_convert_disclosure(
            snap, customer_default_method="transfer", customer_default_days=30
        )
        pr = d["payment_resolved"]
        assert pr["method"] == "compensation"
        assert pr["source"] == "wfirma_proforma"

    def test_payment_resolved_source_not_set_when_no_data(self):
        """source == 'not_set' when neither snap nor customer master has a method."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {"currency": "EUR", "paymentmethod": ""}
        d = build_invoice_convert_disclosure(snap)
        assert d["payment_resolved"]["source"] == "not_set"
        assert d["payment_resolved"]["method"] == ""

    def test_payment_method_in_fields_to_write(self):
        """Resolved payment_method is mirrored into fields_to_write for audit."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {"currency": "EUR", "paymentmethod": "przelew"}
        d = build_invoice_convert_disclosure(snap)
        assert d["fields_to_write"]["payment_method"] == "transfer"

    def test_customer_default_days_exposed(self):
        """customer_default_days is present in payment_resolved."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(
            self._make_snap(), customer_default_days=45
        )
        assert d["payment_resolved"]["customer_default_days"] == 45

    def test_pm_maps_roundtrip(self):
        """_PM_MAP_TO_EN and _PM_MAP_TO_WF are strict inverses of each other."""
        from app.services.payload_disclosure import _PM_MAP_TO_EN, _PM_MAP_TO_WF
        assert len(_PM_MAP_TO_EN) == 4
        assert len(_PM_MAP_TO_WF) == 4
        for wf, en in _PM_MAP_TO_EN.items():
            assert _PM_MAP_TO_WF[en] == wf, f"Round-trip failed for {wf!r}"


class TestBuildFinalInvoicePlanPaymentMethod:
    """build_final_invoice_plan — paymentmethod override parameter."""

    def _make_snap(self):
        """Minimal ProformaSnapshot with one billable line."""
        from decimal import Decimal
        from app.services.proforma_to_invoice import ProformaSnapshot, LineItem
        return ProformaSnapshot(
            proforma_id="99001",
            proforma_number="PROF 1/2026",
            type="proforma",
            contractor_id="99990001",
            currency="EUR",
            price_currency_exchange=None,
            paymentmethod="przelew",
            paymentdate="2026-07-28",
            date="2026-06-28",
            description="",
            series_id=None,
            company_account_id=None,
            translation_language_id=None,
            contractor_receiver_id=None,
            total=Decimal("200.00"),
            netto=Decimal("200.00"),
            contents=[
                LineItem(
                    name="Test product",
                    good_id="G001",
                    unit="szt",
                    unit_count="2",
                    price="100.00",
                    vat_code_id="0",
                )
            ],
        )

    def test_default_uses_snap_paymentmethod(self):
        """Without override, plan inherits snap.paymentmethod unchanged."""
        from app.services.proforma_to_invoice import build_final_invoice_plan
        plan = build_final_invoice_plan(self._make_snap(), final_series_id="")
        assert plan.paymentmethod == "przelew"

    def test_override_paymentmethod_replaces_snap(self):
        """When paymentmethod override is provided it wins over snap."""
        from app.services.proforma_to_invoice import build_final_invoice_plan
        plan = build_final_invoice_plan(
            self._make_snap(), final_series_id="", paymentmethod="gotowka"
        )
        assert plan.paymentmethod == "gotowka"

    def test_none_override_falls_back_to_snap(self):
        """Explicit None override still falls back to snap."""
        from app.services.proforma_to_invoice import build_final_invoice_plan
        plan = build_final_invoice_plan(
            self._make_snap(), final_series_id="", paymentmethod=None
        )
        assert plan.paymentmethod == "przelew"

    def test_empty_string_override_falls_back_to_snap(self):
        """Empty-string override falls back to snap (falsy guard)."""
        from app.services.proforma_to_invoice import build_final_invoice_plan
        plan = build_final_invoice_plan(
            self._make_snap(), final_series_id="", paymentmethod=""
        )
        assert plan.paymentmethod == "przelew"

    def test_paymentdate_override_independent(self):
        """paymentdate override works independently of paymentmethod override."""
        from app.services.proforma_to_invoice import build_final_invoice_plan
        plan = build_final_invoice_plan(
            self._make_snap(), final_series_id="", paymentdate="2026-09-01"
        )
        assert plan.paymentdate == "2026-09-01"
        assert plan.paymentmethod == "przelew"

    # ── invoice_date / sale_date separation ───────────────────────────────────

    def test_override_invoice_date_sets_plan_date_independently(self):
        """override_invoice_date → plan.date; does not affect plan.paymentdate."""
        from datetime import date
        from app.services.proforma_to_invoice import build_final_invoice_plan
        plan = build_final_invoice_plan(
            self._make_snap(),
            final_series_id="",
            invoice_date=date(2026, 9, 1),
        )
        assert plan.date == "2026-09-01"
        # paymentdate unchanged — still the snap's original value
        assert plan.paymentdate == "2026-07-28"

    def test_override_sale_date_plus_days_computes_paymentdate(self):
        """Route computes paymentdate = sale_date + payment_days, passes it in.
        Verify plan stores the computed result correctly."""
        from datetime import date, timedelta
        from app.services.proforma_to_invoice import build_final_invoice_plan
        sale_date = date(2026, 8, 15)
        days = 30
        expected_payment = (sale_date + timedelta(days=days)).isoformat()  # 2026-09-14
        plan = build_final_invoice_plan(
            self._make_snap(),
            final_series_id="",
            paymentdate=expected_payment,
        )
        assert plan.paymentdate == "2026-09-14"

    def test_invoice_date_fallback_as_payment_base_when_no_sale_date(self):
        """When no sale_date override, route uses invoice_date as payment base.
        i.e. paymentdate = invoice_date + days."""
        from datetime import date, timedelta
        from app.services.proforma_to_invoice import build_final_invoice_plan
        invoice_dt = date(2026, 9, 1)
        days = 30
        # Route computes: _payment_base = _invoice_date (no sale_date override)
        #                 _paymentdate  = _payment_base + days
        computed_payment = (invoice_dt + timedelta(days=days)).isoformat()  # 2026-10-01
        plan = build_final_invoice_plan(
            self._make_snap(),
            final_series_id="",
            invoice_date=invoice_dt,
            paymentdate=computed_payment,
        )
        assert plan.date == "2026-09-01"
        assert plan.paymentdate == "2026-10-01"


class TestDraftPaymentFieldsAuthority:
    """Draft saved payment_terms fields take priority over snap and customer master."""

    def _make_snap(self) -> dict:
        return {
            "proforma_number": "PROF 10/2026",
            "contractor_id":   "99001",
            "currency":        "EUR",
            "series_id":       "555",
            "lines": [],
        }

    def test_draft_method_beats_snap_in_disclosure(self):
        """draft_method wins over wFirma snap paymentmethod."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {**self._make_snap(), "paymentmethod": "przelew"}
        d = build_invoice_convert_disclosure(snap, draft_method="cash")
        pr = d["payment_resolved"]
        assert pr["method"] == "cash"
        assert pr["source"] == "draft_saved"

    def test_draft_method_beats_customer_master(self):
        """draft_method wins over customer_default_method when snap is blank."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {**self._make_snap(), "paymentmethod": ""}
        d = build_invoice_convert_disclosure(
            snap, draft_method="compensation", customer_default_method="transfer"
        )
        pr = d["payment_resolved"]
        assert pr["method"] == "compensation"
        assert pr["source"] == "draft_saved"

    def test_snap_wins_when_no_draft_method(self):
        """Without draft_method, snap still takes priority over customer master."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {**self._make_snap(), "paymentmethod": "karta"}
        d = build_invoice_convert_disclosure(
            snap, draft_method="", customer_default_method="transfer"
        )
        pr = d["payment_resolved"]
        assert pr["method"] == "card"
        assert pr["source"] == "wfirma_proforma"

    def test_draft_invoice_date_in_payment_resolved(self):
        """draft_invoice_date surfaces in payment_resolved.invoice_date."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(snap, draft_invoice_date="2026-09-01")
        assert d["payment_resolved"]["invoice_date"] == "2026-09-01"

    def test_draft_sale_date_in_payment_resolved(self):
        """draft_sale_date surfaces in payment_resolved.sale_date."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(snap, draft_sale_date="2026-08-15")
        assert d["payment_resolved"]["sale_date"] == "2026-08-15"

    def test_draft_days_in_payment_resolved(self):
        """draft_days surfaces in payment_resolved.payment_days."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(snap, draft_days=30)
        assert d["payment_resolved"]["payment_days"] == 30

    def test_no_draft_fields_yields_none_in_payment_resolved(self):
        """When no draft fields provided, invoice_date/sale_date/payment_days are None."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(snap)
        pr = d["payment_resolved"]
        assert pr["invoice_date"] is None
        assert pr["sale_date"] is None
        assert pr["payment_days"] is None


class TestPreFlightReadiness:
    """check_proforma_post_readiness gate checks."""

    def test_ready_when_client_and_lines_present(self):
        from app.services.payload_disclosure import check_proforma_post_readiness
        import json
        draft = {
            "client_name": "Test Client",
            "editable_lines_json": json.dumps([
                {"product_code": "PC-1", "unit_price": 50.0, "qty": 1}
            ]),
            "draft_state": "approved",
        }
        result = check_proforma_post_readiness(draft)
        assert result["ready"] is True
        assert result["blockers"] == []

    def test_blocked_when_no_client(self):
        from app.services.payload_disclosure import check_proforma_post_readiness
        import json
        draft = {
            "client_name": "",
            "editable_lines_json": json.dumps([{"unit_price": 50.0}]),
        }
        result = check_proforma_post_readiness(draft)
        assert result["ready"] is False
        assert any("client" in b.lower() for b in result["blockers"])

    def test_blocked_when_already_posted(self):
        from app.services.payload_disclosure import check_proforma_post_readiness
        import json
        draft = {
            "client_name": "Test",
            "editable_lines_json": json.dumps([{"unit_price": 50.0}]),
            "draft_state": "posted",
        }
        result = check_proforma_post_readiness(draft)
        assert result["ready"] is False
        assert any("posted" in b.lower() for b in result["blockers"])

    def test_blocked_when_zero_price_lines(self):
        from app.services.payload_disclosure import check_proforma_post_readiness
        import json
        draft = {
            "client_name": "Test",
            "editable_lines_json": json.dumps([
                {"product_code": "PC-1", "unit_price": 0.0}
            ]),
        }
        result = check_proforma_post_readiness(draft)
        assert result["ready"] is False
        assert any("zero" in b.lower() or "price" in b.lower() for b in result["blockers"])


# ── Phase 9 description_preview passthrough tests ─────────────────────────────

class TestDescriptionPreviewPassthrough:
    """build_invoice_convert_disclosure: description_preview and
    payload_core_hash_override new parameters (Phase 9 / RC-4)."""

    def _make_snap(self):
        from app.services.proforma_to_invoice import parse_proforma_xml
        return parse_proforma_xml(_proforma_xml_3lines())

    def test_description_preview_absent_when_not_passed(self):
        """Without description_preview= the key must NOT appear in the result."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        assert "description_preview" not in d, (
            "description_preview must not appear unless explicitly passed"
        )

    def test_description_preview_present_when_passed(self):
        """When description_preview= is supplied it is forwarded as-is."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        preview_text = "Dotyczy faktury pro forma nr PROF 92/2026.\nWarunki płatności: przelew 30 dni."
        d = build_invoice_convert_disclosure(
            self._make_snap(), description_preview=preview_text
        )
        assert "description_preview" in d, "description_preview key must be present when passed"
        assert d["description_preview"] == preview_text

    def test_description_preview_none_is_absent(self):
        """Explicit None is the same as omitted — key must NOT appear."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap(), description_preview=None)
        assert "description_preview" not in d

    def test_description_preview_empty_string_is_forwarded(self):
        """Empty string is a valid (if unusual) description_preview — forwarded as ''."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap(), description_preview="")
        assert "description_preview" in d
        assert d["description_preview"] == ""

    def test_payload_core_hash_override_replaces_computed_hash(self):
        """When payload_core_hash_override= is supplied it wins over the internally
        computed hash.  This ensures disclose and execute use the SAME description-
        covering hash rather than each computing their own."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        fixed_hash = "a" * 64
        d = build_invoice_convert_disclosure(
            self._make_snap(),
            final_series_id="777",
            payload_core_hash_override=fixed_hash,
        )
        assert d["payload_core_hash"] == fixed_hash, (
            "payload_core_hash_override must replace the internally computed hash"
        )

    def test_payload_core_hash_override_none_uses_computed(self):
        """When payload_core_hash_override is None, the module computes the hash normally."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        from app.services.proforma_to_invoice import compute_conversion_core_hash
        snap = self._make_snap()
        d = build_invoice_convert_disclosure(
            snap, final_series_id="777", payload_core_hash_override=None
        )
        expected = compute_conversion_core_hash(
            snap.contractor_id, snap.currency, "777", snap.contents
        )
        assert d["payload_core_hash"] == expected

    def test_description_covering_hash_differs_from_bare_hash(self):
        """A hash computed WITH a description must differ from one without,
        confirming that the description_preview is cryptographically bound."""
        from app.services.proforma_to_invoice import compute_conversion_core_hash
        snap = self._make_snap()
        h_no_desc = compute_conversion_core_hash(
            snap.contractor_id, snap.currency, "777", snap.contents
        )
        h_with_desc = compute_conversion_core_hash(
            snap.contractor_id, snap.currency, "777", snap.contents,
            description="Dotyczy faktury pro forma nr PROF 92/2026.",
        )
        assert h_no_desc != h_with_desc, (
            "Hash with description must differ from hash without — description must be in payload"
        )
