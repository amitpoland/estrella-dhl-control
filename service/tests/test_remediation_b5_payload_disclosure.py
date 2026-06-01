"""
test_remediation_b5_payload_disclosure.py — Integration tests for B5.

Verifies the payload-disclosure endpoint is registered and returns the correct
payload shape without making any wFirma write.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestDisclosureEndpointRegistered:
    """disclose-post endpoint is registered in routes_proforma."""

    def test_disclose_post_endpoint_in_source(self):
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
               ).read_text(encoding="utf-8")
        assert "/disclose-post" in src
        assert "build_proforma_post_disclosure" in src
        assert "disclose_proforma_post" in src

    def test_disclose_convert_endpoint_in_source(self):
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
               ).read_text(encoding="utf-8")
        assert "/disclose-convert" in src
        assert "build_invoice_convert_disclosure" in src

    def test_post_disclosure_modal_in_html(self):
        src = (Path(__file__).parent.parent / "app" / "static" / "proforma-detail-v2.html"
               ).read_text(encoding="utf-8")
        assert "PostDisclosureModal" in src
        assert "disclose-post" in src
        assert "Confirm Payload" in src

    def test_post_modal_replaces_plain_confirm(self):
        """The post button now uses PostDisclosureModal not plain Confirm."""
        src = (Path(__file__).parent.parent / "app" / "static" / "proforma-detail-v2.html"
               ).read_text(encoding="utf-8")
        # PostDisclosureModal must be present
        assert "PostDisclosureModal" in src
        # btn-post-confirm-disclosure test ID must be present
        assert "btn-post-confirm-disclosure" in src


class TestDisclosureServiceNoWrites:
    """payload_disclosure never calls wFirma or writes anything."""

    def test_disclose_post_no_wfirma_in_source(self):
        src = (Path(__file__).parent.parent / "app" / "services" / "payload_disclosure.py"
               ).read_text(encoding="utf-8")
        assert "wfirma_client" not in src
        assert "_http_request" not in src
        assert "requests." not in src

    def test_disclose_post_returns_correct_shape(self):
        from app.services.payload_disclosure import build_proforma_post_disclosure
        import json as _json
        draft = {
            "id": 99, "batch_id": "B", "client_name": "Test Client",
            "currency": "EUR", "incoterm": "DAP", "remarks": "",
            "editable_lines_json": _json.dumps([
                {"product_code": "PC-1", "design_no": "D1",
                 "qty": 3, "unit_price": 100.0, "currency": "EUR"},
            ]),
            "service_charges_json": "[]",
            "draft_state": "approved",
        }
        d = build_proforma_post_disclosure(draft)
        assert d["disclosure_type"] == "proforma_post"
        assert d["flag_required"] == "WFIRMA_CREATE_PROFORMA_ALLOWED"
        assert d["confirm_token_required"] == "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"
        assert len(d["lines"]) == 1
        assert "warning" in d
        # Must be JSON-serialisable
        _json.dumps(d)
