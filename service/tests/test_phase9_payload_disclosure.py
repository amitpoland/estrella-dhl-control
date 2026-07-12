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


class TestInvoiceConvertDisclosure:
    """build_invoice_convert_disclosure for WF2.5."""

    def _make_snap(self) -> dict:
        return {
            "proforma_number": "PROF 92/2026",
            "contractor_id":   "99990001",
            "currency":        "EUR",
            "series_id":       "555",
            "lines": [
                {"wfirma_good_id": "G001", "qty": 2, "unit_price": 100.0, "currency": "EUR"},
            ],
        }

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
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        d = build_invoice_convert_disclosure(self._make_snap())
        assert len(d["lines"]) == 1
        assert d["lines"][0]["good_id"] == "G001"

    # ── payment_resolved block ────────────────────────────────────────────────

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
        snap = {**self._make_snap(), "paymentmethod": "przelew", "paymentdate": "2026-07-28"}
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
            snap = {**self._make_snap(), "paymentmethod": wf_form}
            d = build_invoice_convert_disclosure(snap)
            assert d["payment_resolved"]["method"] == en_form, \
                f"Expected {en_form!r} for wFirma form {wf_form!r}"

    def test_payment_resolved_falls_back_to_customer_master(self):
        """When snap has no paymentmethod, customer_default_method is used."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {**self._make_snap(), "paymentmethod": "", "paymentdate": ""}
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
        snap = {**self._make_snap(), "paymentmethod": "kompensata"}
        d = build_invoice_convert_disclosure(
            snap, customer_default_method="transfer", customer_default_days=30
        )
        pr = d["payment_resolved"]
        assert pr["method"] == "compensation"
        assert pr["source"] == "wfirma_proforma"

    def test_payment_resolved_source_not_set_when_no_data(self):
        """source == 'not_set' when neither snap nor customer master has a method."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {**self._make_snap(), "paymentmethod": ""}
        d = build_invoice_convert_disclosure(snap)
        assert d["payment_resolved"]["source"] == "not_set"
        assert d["payment_resolved"]["method"] == ""

    def test_payment_method_in_fields_to_write(self):
        """Resolved payment_method is mirrored into fields_to_write for audit."""
        from app.services.payload_disclosure import build_invoice_convert_disclosure
        snap = {**self._make_snap(), "paymentmethod": "przelew"}
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
