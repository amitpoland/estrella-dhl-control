"""
test_wfirma_fetch_pz_by_id.py — read-side bug fix regression for
``wfirma_client.fetch_warehouse_pz``.

The bug:
  Previous implementation used ``warehouse_document_p_z/find`` with a
  ``<condition><field>id eq …>`` body. wFirma silently ignored that
  filter and returned the first 1000 PZ docs; the parser took the
  first node and yielded an unrelated 2020 document. Verified live
  against wFirma in the prior debug task.

The fix:
  Use path-based ``GET warehouse_document_p_z/get/{id}``. wFirma
  honours the URL-segment id; the response is a single doc envelope.

These tests pin:
  1. fetch_warehouse_pz calls the new path-based endpoint.
  2. A mocked single-PZ-with-9-lines response parses into the expected
     PZFetchResult shape.
  3. 404 / wFirma ERROR / parse error all return safe failure shapes,
     no exceptions raised.
  4. ``find_warehouse_pz_by_number`` (different code path) is NOT
     altered by this change.
  5. Empty / whitespace pz_doc_id still rejected without a network call.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import wfirma_client as wc


SAMPLE_OK_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_document_p_z>
    <warehouse_document>
      <id>183484963</id>
      <full_number>1/05/2026</full_number>
      <date>2026-05-08</date>
      <description>batch=SHIPMENT_6049349806_2026-05_7409ac77 | MRN 26PL44302D00AUCWR3</description>
      <contractor><id>38142296</id></contractor>
      <warehouse><id>347088</id></warehouse>
      <warehouse_document_contents>
        <warehouse_document_content><id>1</id><good><id>48792867</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>2</id><good><id>48792931</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>3</id><good><id>48792995</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>4</id><good><id>48793059</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>5</id><good><id>48793123</id></good><count>3</count></warehouse_document_content>
        <warehouse_document_content><id>6</id><good><id>48793187</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>7</id><good><id>48793251</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>8</id><good><id>48793315</id></good><count>1</count></warehouse_document_content>
        <warehouse_document_content><id>9</id><good><id>48793379</id></good><count>1</count></warehouse_document_content>
      </warehouse_document_contents>
    </warehouse_document>
  </warehouse_document_p_z>
  <status><code>OK</code></status>
</api>"""


SAMPLE_ERROR_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>ERROR</code><description>Not authorised</description></status>
</api>"""


# ── Endpoint contract ─────────────────────────────────────────────────────

class TestEndpointContract:
    def test_uses_path_based_get_by_id(self):
        """fetch_warehouse_pz must call _http_request with module
        ``warehouse_document_p_z`` and operation ``get/{id}``."""
        captured = {}
        def _fake_req(method, module, op, body):
            captured["method"] = method
            captured["module"] = module
            captured["op"]     = op
            captured["body"]   = body
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_fake_req):
            res = wc.fetch_warehouse_pz("183484963")
        assert res.ok is True
        assert captured["method"] == "GET"
        assert captured["module"] == "warehouse_document_p_z"
        assert captured["op"]     == "get/183484963"
        # The new call sends NO body (path-based id lookup)
        assert captured["body"]   == ""

    def test_does_not_use_find_with_id_condition(self):
        """The legacy 'find' + id-condition pattern must be gone — that
        was the silent-filter-ignored bug."""
        captured = {}
        def _fake_req(method, module, op, body):
            captured["op"]   = op
            captured["body"] = body
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_fake_req):
            wc.fetch_warehouse_pz("183484963")
        assert captured["op"] != "find", \
            "Must use path-based get/{id}, not find with id-condition"
        assert "<field>id</field>" not in (captured["body"] or "")


# ── Happy path ────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_returns_correct_id_and_number(self):
        with patch.object(wc, "_http_request",
                          return_value=(200, SAMPLE_OK_RESPONSE)):
            res = wc.fetch_warehouse_pz("183484963")
        assert res.ok is True
        assert res.pz_doc_id == "183484963"
        assert res.pz_number == "1/05/2026"
        assert res.raw_response == SAMPLE_OK_RESPONSE

    def test_response_carries_nine_line_items(self):
        """Sanity — downstream parser will count 9 line items."""
        with patch.object(wc, "_http_request",
                          return_value=(200, SAMPLE_OK_RESPONSE)):
            res = wc.fetch_warehouse_pz("183484963")
        assert res.raw_response.count("<warehouse_document_content>") == 9
        # All 9 expected good_ids present
        for gid in ("48792867", "48792931", "48792995", "48793059",
                    "48793123", "48793187", "48793251", "48793315",
                    "48793379"):
            assert f"<id>{gid}</id>" in res.raw_response


# ── Failure paths ─────────────────────────────────────────────────────────

class TestFailureSafety:
    def test_404_returns_not_found_without_raising(self):
        with patch.object(wc, "_http_request",
                          return_value=(404, "<api><status><code>ERROR</code></status></api>")):
            res = wc.fetch_warehouse_pz("999999999")
        assert res.ok is False
        assert "not found" in (res.error or "").lower()

    def test_500_returns_http_error_safely(self):
        with patch.object(wc, "_http_request",
                          return_value=(500, "internal error")):
            res = wc.fetch_warehouse_pz("183484963")
        assert res.ok is False
        assert "HTTP 500" in (res.error or "")

    def test_wfirma_error_status_returned_safely(self):
        with patch.object(wc, "_http_request",
                          return_value=(200, SAMPLE_ERROR_RESPONSE)):
            res = wc.fetch_warehouse_pz("183484963")
        assert res.ok is False
        assert "ERROR" in (res.error or "") or "Not authorised" in (res.error or "")

    def test_xml_parse_error_caught(self):
        with patch.object(wc, "_http_request",
                          return_value=(200, "this is not xml")):
            res = wc.fetch_warehouse_pz("183484963")
        # Either status-parse or XML-parse fails — either way ok=False
        assert res.ok is False

    def test_connection_error_caught(self):
        with patch.object(wc, "_http_request",
                          side_effect=ConnectionError("boom")):
            res = wc.fetch_warehouse_pz("183484963")
        assert res.ok is False
        assert "connection" in (res.error or "").lower()

    def test_empty_id_rejected_without_network(self):
        called = {"n": 0}
        def _spy(*a, **kw):
            called["n"] += 1
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_spy):
            for bad in ("", "   ", None):
                res = wc.fetch_warehouse_pz(bad)
                assert res.ok is False
                assert "required" in (res.error or "").lower()
        assert called["n"] == 0, "no HTTP call must be made for empty id"


# ── find_warehouse_pz_by_number unchanged ────────────────────────────────

class TestFindByNumberUnchanged:
    def test_find_by_number_still_uses_find_op(self):
        """The other code path (full_number search) must remain on the
        ``find`` operation — that is wFirma-supported for full_number."""
        captured = {}
        def _fake(method, module, op, body):
            captured["op"]   = op
            captured["body"] = body
            return 200, SAMPLE_OK_RESPONSE
        with patch.object(wc, "_http_request", side_effect=_fake):
            wc.find_warehouse_pz_by_number("1/05/2026")
        assert captured["op"] == "find"
        assert "<field>full_number</field>" in (captured["body"] or "")


# ── Route still consumes client output (source-level invariant) ──────────

class TestRouteConsumesClient:
    def test_route_calls_fetch_warehouse_pz(self):
        """The /wfirma/pz_document route must still call
        ``wfirma_client.fetch_warehouse_pz`` with the audit-derived
        pz_doc_id. Source-grep avoids the event-loop pollution that an
        end-to-end route test would cause when patching _http_request."""
        from pathlib import Path as _P
        src_path = _P(__file__).resolve().parents[1] / "app" / "api" / "routes_wfirma.py"
        text = src_path.read_text(encoding="utf-8")
        # Locate the route function and slice its body
        start = text.index("async def wfirma_pz_document(")
        # The next async def (or end-of-file) terminates this function
        end_match = text.find("\nasync def ", start + 1)
        if end_match == -1:
            end_match = len(text)
        body = text[start:end_match]
        # Route still pulls the doc id from audit.wfirma_export
        assert 'wfirma_export.get("wfirma_pz_doc_id"' in body \
            or "wfirma_export.get('wfirma_pz_doc_id'" in body
        # Route still calls the client
        assert "wfirma_client.fetch_warehouse_pz(pz_doc_id)" in body
        # Route still parses the raw_xml via _parse_pz_doc_from_xml
        assert "_parse_pz_doc_from_xml(" in body

    def test_route_response_keys_unchanged(self):
        """Confirm the route's documented response schema (what the
        dashboard reads) is unchanged. The keys come from the JSONResponse
        body inside wfirma_pz_document."""
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parents[1] / "app" / "api"
               / "routes_wfirma.py").read_text(encoding="utf-8")
        for key in ('"pz_doc_id"', '"pz_number"', '"date"',
                    '"contractor_id"', '"warehouse_id"', '"description"',
                    '"line_count"', '"lines"', '"pz_source"', '"raw_xml"'):
            assert key in src, f"route response key {key} missing — schema regression"
