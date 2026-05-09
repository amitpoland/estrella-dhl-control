"""
test_wfirma_fetch_invoice_by_id.py — read-side bug fix regression for
``wfirma_client.fetch_invoice_xml``.

The bug:
  Previous implementation used ``invoices/find`` with a
  ``<condition><field>id eq …>`` body. Same wFirma-silently-ignores-id
  pattern that broke ``fetch_warehouse_pz``. Could cause
  ``create_proforma_draft``'s verify-after-create to compare the
  just-added Proforma's expected line count against an unrelated
  invoice's persisted line count → spurious "partial persistence"
  RuntimeErrors.

The fix:
  Use path-based ``GET invoices/get/{id}``. Empty body. Mirrors the
  ``fetch_warehouse_pz`` fix.

These tests pin:
  1. fetch_invoice_xml calls ``invoices/get/{id}`` with empty body.
  2. Single-invoice OK response is returned verbatim.
  3. 404 / 5xx / wFirma ERROR / XML parse error raise clean RuntimeError.
  4. Empty / whitespace id raises ValueError, no network call.
  5. Source-grep: no ``<field>id</field>`` remains in wfirma_client.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import wfirma_client as wc


SAMPLE_OK_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>9876543</id>
      <fullnumber>PROF/05/2026/001</fullnumber>
      <date>2026-05-08</date>
      <invoicecontents>
        <invoicecontent><id>1</id><good><id>48792867</id></good><count>1</count></invoicecontent>
        <invoicecontent><id>2</id><good><id>48792931</id></good><count>1</count></invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


SAMPLE_ERROR_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>ERROR</code><description>Not authorised</description></status>
</api>"""


# ── Endpoint contract ─────────────────────────────────────────────────────

class TestEndpointContract:
    def test_uses_path_based_get_by_id(self):
        captured = {}
        def _fake(method, module, op, body):
            captured["method"] = method
            captured["module"] = module
            captured["op"]     = op
            captured["body"]   = body
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_fake):
            xml = wc.fetch_invoice_xml("9876543")
        assert xml == SAMPLE_OK_RESPONSE
        assert captured["method"] == "GET"
        assert captured["module"] == "invoices"
        assert captured["op"]     == "get/9876543"
        assert captured["body"]   == ""

    def test_does_not_use_find_with_id_condition(self):
        """The legacy 'find' + id-condition pattern must be gone."""
        captured = {}
        def _fake(method, module, op, body):
            captured["op"]   = op
            captured["body"] = body
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_fake):
            wc.fetch_invoice_xml("9876543")
        assert captured["op"] != "find", \
            "Must use path-based get/{id}, not find with id-condition"
        assert "<field>id</field>" not in (captured["body"] or "")


# ── Happy path ────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_single_invoice_response_returned_verbatim(self):
        with patch.object(wc, "_http_request",
                          return_value=(200, SAMPLE_OK_RESPONSE)):
            xml = wc.fetch_invoice_xml("9876543")
        # Verbatim — caller may need <invoicecontents> for restate edits
        assert xml == SAMPLE_OK_RESPONSE

    def test_response_carries_expected_invoice_node(self):
        with patch.object(wc, "_http_request",
                          return_value=(200, SAMPLE_OK_RESPONSE)):
            xml = wc.fetch_invoice_xml("9876543")
        assert "<invoice>" in xml
        assert "<id>9876543</id>" in xml
        assert xml.count("<invoicecontent>") == 2


# ── Failure paths (all raise RuntimeError, never silent) ─────────────────

class TestFailureSafety:
    def test_404_raises_clean_runtime_error(self):
        with patch.object(wc, "_http_request",
                          return_value=(404, "<api><status><code>ERROR</code></status></api>")):
            with pytest.raises(RuntimeError) as exc:
                wc.fetch_invoice_xml("999")
        assert "not found" in str(exc.value).lower()

    def test_500_raises_clean_runtime_error(self):
        with patch.object(wc, "_http_request",
                          return_value=(500, "internal error")):
            with pytest.raises(RuntimeError) as exc:
                wc.fetch_invoice_xml("9876543")
        assert "HTTP 500" in str(exc.value)

    def test_wfirma_error_status_raises_runtime_error(self):
        with patch.object(wc, "_http_request",
                          return_value=(200, SAMPLE_ERROR_RESPONSE)):
            with pytest.raises(RuntimeError) as exc:
                wc.fetch_invoice_xml("9876543")
        msg = str(exc.value)
        assert "ERROR" in msg or "Not authorised" in msg

    def test_xml_parse_error_raises_runtime_error(self):
        # Status returns OK from _parse_status but root XML is malformed.
        # _parse_status itself returns ("PARSE_ERROR", ...) on bad XML, so
        # we get a RuntimeError("invoices/get wFirma status=PARSE_ERROR …").
        with patch.object(wc, "_http_request",
                          return_value=(200, "this is not xml")):
            with pytest.raises(RuntimeError):
                wc.fetch_invoice_xml("9876543")

    def test_no_invoice_node_raises_runtime_error(self):
        # OK status but no <invoice> in body — defensive check.
        almost_ok = """<?xml version="1.0"?>
<api>
  <invoices></invoices>
  <status><code>OK</code></status>
</api>"""
        with patch.object(wc, "_http_request",
                          return_value=(200, almost_ok)):
            with pytest.raises(RuntimeError) as exc:
                wc.fetch_invoice_xml("9876543")
        assert "no <invoice>" in str(exc.value)

    def test_empty_id_raises_value_error_without_network(self):
        called = {"n": 0}
        def _spy(*a, **kw):
            called["n"] += 1
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_spy):
            for bad in ("", "   "):
                with pytest.raises(ValueError):
                    wc.fetch_invoice_xml(bad)
        assert called["n"] == 0, "no HTTP call must be made for empty id"


# ── Source-level invariant ────────────────────────────────────────────────

class TestSourceInvariant:
    def test_no_unsafe_field_id_remains_in_wfirma_client(self):
        """Pin: zero ``<field>id</field>`` occurrences anywhere in
        wfirma_client.py. This catches future regressions where a new
        helper accidentally re-introduces the unsafe pattern."""
        src = Path(wc.__file__).read_text(encoding="utf-8")
        assert "<field>id</field>" not in src, (
            "Unsafe id-condition pattern reintroduced — use path-based "
            "/get/{id} instead. wFirma silently ignores `id` in `find` "
            "condition bodies and returns the full collection.")

    def test_safe_business_field_finds_unchanged(self):
        """Confirm the legitimate `find` calls (by nip / code / name /
        full_number) are still in place — those use wFirma-supported
        searchable fields and must NOT be changed."""
        src = Path(wc.__file__).read_text(encoding="utf-8")
        for safe_field in ("<field>nip</field>",
                           "<field>code</field>",
                           "<field>name</field>",
                           "<field>full_number</field>"):
            assert safe_field in src, (
                f"Expected safe-field find pattern {safe_field} missing "
                "— this audit may have removed too much")
