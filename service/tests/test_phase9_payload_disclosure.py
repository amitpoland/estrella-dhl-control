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
            "contractor_id":   "75483443",
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
