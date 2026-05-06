"""
test_wfirma_pz_document_view.py — unit tests for read-only document view endpoints.

GET /api/v1/upload/shipment/{batch_id}/wfirma/pz_document
GET /api/v1/proforma/{batch_id}/{client_name}/document

Tests:
  1. pz_document — 404 when no linked PZ (wfirma_pz_doc_id absent)
  2. pz_document — 502 when wFirma fetch fails
  3. pz_document — returns structured data (header + lines) from XML
  4. pz_document — returns empty lines gracefully when XML has no contents
  5. proforma_document — 404 when no draft in DB
  6. proforma_document — 404 when draft has no wfirma_proforma_id
  7. proforma_document — returns proforma data when fetch succeeds
  8. proforma_document — 409 when wFirma doc is not type=proforma
  9. proforma_document — 502 when wFirma fetch raises
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Shared fixtures ────────────────────────────────────────────────────────────

_BATCH       = "TEST_DOC_VIEW_001"
_CLIENT      = "ACME Corp"
_DOC_ID      = "183167843"
_PZ_NUMBER   = "PZ 3/5/2026"
_PROFORMA_ID = "465997347"

_AUDIT_LINKED = {
    "batch_id":      _BATCH,
    "status":        "processed",
    "inputs":        {"zc429": "sad.pdf"},
    "wfirma_export": {
        "wfirma_pz_doc_id": _DOC_ID,
        "pz_source":        "adopted_existing",
    },
}

_AUDIT_NO_PZ = {
    "batch_id":      _BATCH,
    "status":        "processed",
    "inputs":        {"zc429": "sad.pdf"},
    "wfirma_export": {},
}


# ── Minimal wFirma XML for PZ document ────────────────────────────────────────

_PZ_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>OK</code><description></description></status>
  <warehouse_document>
    <id>{_DOC_ID}</id>
    <full_number>{_PZ_NUMBER}</full_number>
    <date>2026-05-01</date>
    <contractor><id>9</id><name>Estrella Jewels LLP</name></contractor>
    <warehouse><id>42</id><name>Main Warehouse</name></warehouse>
    <description>batch={_BATCH} | MRN 26PL123456789</description>
    <warehouse_document_contents>
      <warehouse_document_content>
        <good><id>7001</id><name>Ring Gold 18k</name></good>
        <count>3</count>
        <price>850.00</price>
      </warehouse_document_content>
      <warehouse_document_content>
        <good><id>7002</id><name>Bracelet Silver</name></good>
        <count>5</count>
        <price>320.00</price>
      </warehouse_document_content>
    </warehouse_document_contents>
  </warehouse_document>
</api>"""

_PZ_XML_NO_CONTENTS = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>OK</code><description></description></status>
  <warehouse_document>
    <id>{_DOC_ID}</id>
    <full_number>{_PZ_NUMBER}</full_number>
    <date>2026-05-01</date>
    <contractor><id>9</id></contractor>
    <warehouse><id>42</id></warehouse>
  </warehouse_document>
</api>"""


# ── Minimal wFirma XML for proforma invoice ───────────────────────────────────

_PROFORMA_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>OK</code><description></description></status>
  <invoice>
    <id>{_PROFORMA_ID}</id>
    <type>proforma</type>
    <full_number>PROF 94/2026</full_number>
    <date>2026-05-05</date>
    <contractor><id>99</id><name>ACME Corp</name></contractor>
    <currency>PLN</currency>
    <status>issued</status>
    <invoicecontents>
      <invoicecontent>
        <name>Ring Gold 18k</name>
        <count>3</count>
        <price_netto>2550.00</price_netto>
        <netto>7650.00</netto>
        <vat><code>WDT</code></vat>
      </invoicecontent>
    </invoicecontents>
  </invoice>
</api>"""

_REGULAR_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>OK</code><description></description></status>
  <invoice>
    <id>999</id>
    <type>invoice</type>
    <full_number>FV 10/2026</full_number>
    <date>2026-05-05</date>
  </invoice>
</api>"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fetch_ok(raw_xml=_PZ_XML):
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=True, pz_doc_id=_DOC_ID, pz_number=_PZ_NUMBER,
                         raw_response=raw_xml)


def _make_fetch_fail(error="document not found"):
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=False, error=error)


def _make_draft(wfirma_proforma_id=None):
    from app.services.proforma_invoice_link_db import ProformaDraft
    return ProformaDraft(
        batch_id=_BATCH,
        client_name=_CLIENT,
        status="issued",
        source_lines_json="[]",
        wfirma_proforma_id=wfirma_proforma_id,
    )


def _run_pz_doc(batch_id=_BATCH):
    import asyncio
    from app.api.routes_wfirma import wfirma_pz_document
    return asyncio.get_event_loop().run_until_complete(wfirma_pz_document(batch_id))


def _run_proforma_doc(batch_id=_BATCH, client_name=_CLIENT):
    import asyncio
    from app.api.routes_proforma import proforma_document
    return asyncio.get_event_loop().run_until_complete(
        proforma_document(batch_id, client_name)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PZ Document endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_pz_document_404_when_no_linked_pz():
    """
    wfirma_export.wfirma_pz_doc_id is empty → HTTPException 404.
    """
    from fastapi import HTTPException
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_NO_PZ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_pz_doc()
    assert exc_info.value.status_code == 404
    assert "PZ_NOT_LINKED" in str(exc_info.value.detail)


def test_pz_document_502_when_wfirma_fetch_fails():
    """
    wFirma returns ok=False → HTTPException 502.
    """
    from fastapi import HTTPException
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_LINKED),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_fail("PZ not found in wFirma")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_pz_doc()
    assert exc_info.value.status_code == 502
    assert "PZ_FETCH_FAILED" in str(exc_info.value.detail)


def test_pz_document_returns_structured_data():
    """
    Successful fetch with XML containing lines → structured JSON with header + lines.
    """
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_LINKED),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
    ):
        result = _run_pz_doc()
        body = json.loads(result.body)

    assert body["pz_doc_id"] == _DOC_ID, body
    assert body["pz_number"] == _PZ_NUMBER, body
    assert body["date"] == "2026-05-01", body
    assert body["contractor_id"] == "9", body
    assert body["warehouse_id"] == "42", body
    assert body["pz_source"] == "adopted_existing", body
    assert body["line_count"] == 2, body
    lines = body["lines"]
    assert len(lines) == 2
    assert lines[0]["good_id"] == "7001"
    assert lines[0]["name"] == "Ring Gold 18k"
    assert lines[0]["count"] == 3.0
    assert lines[0]["price_netto"] == 850.0
    assert lines[1]["good_id"] == "7002"
    assert lines[1]["count"] == 5.0


def test_pz_document_empty_lines_when_no_contents():
    """
    XML has no warehouse_document_content nodes → lines=[], line_count=0.
    """
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_LINKED),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok(raw_xml=_PZ_XML_NO_CONTENTS)),
    ):
        result = _run_pz_doc()
        body = json.loads(result.body)

    assert body["line_count"] == 0, body
    assert body["lines"] == [], body
    assert body["pz_doc_id"] == _DOC_ID
    assert body["date"] == "2026-05-01"


# ═══════════════════════════════════════════════════════════════════════════════
# Proforma Document endpoint tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_proforma_document_404_when_no_draft():
    """
    No draft in DB for batch/client → HTTPException 404.
    """
    from fastapi import HTTPException
    with (
        patch("app.api.routes_proforma._proforma_db_path", return_value="/tmp/nope.db"),
        patch("app.api.routes_proforma.pildb.get_draft", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_proforma_doc()
    assert exc_info.value.status_code == 404
    assert "PROFORMA_NOT_LINKED" in str(exc_info.value.detail)


def test_proforma_document_404_when_no_wfirma_proforma_id():
    """
    Draft exists but wfirma_proforma_id is None → HTTPException 404.
    """
    from fastapi import HTTPException
    draft = _make_draft(wfirma_proforma_id=None)
    with (
        patch("app.api.routes_proforma._proforma_db_path", return_value="/tmp/nope.db"),
        patch("app.api.routes_proforma.pildb.get_draft", return_value=draft),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_proforma_doc()
    assert exc_info.value.status_code == 404
    assert "PROFORMA_NOT_LINKED" in str(exc_info.value.detail)


def test_proforma_document_returns_proforma_data():
    """
    Draft has wfirma_proforma_id; wFirma returns proforma XML → structured JSON.
    """
    draft = _make_draft(wfirma_proforma_id=_PROFORMA_ID)
    with (
        patch("app.api.routes_proforma._proforma_db_path", return_value="/tmp/nope.db"),
        patch("app.api.routes_proforma.pildb.get_draft", return_value=draft),
        patch("app.api.routes_proforma.wfirma_client.fetch_invoice_xml",
              return_value=_PROFORMA_XML),
    ):
        result = _run_proforma_doc()
        body = json.loads(result.body)

    assert body["wfirma_proforma_id"] == _PROFORMA_ID, body
    assert body["invoice_type"] == "proforma", body
    assert body["full_number"] == "PROF 94/2026", body
    assert body["date"] == "2026-05-05", body
    assert body["contractor_id"] == "99", body
    assert body["currency"] == "PLN", body
    assert body["line_count"] == 1, body
    lines = body["lines"]
    assert len(lines) == 1
    assert lines[0]["name"] == "Ring Gold 18k"
    assert lines[0]["quantity"] == 3.0
    assert lines[0]["unit_price"] == 2550.0
    assert lines[0]["total_net"] == 7650.0
    assert lines[0]["vat_rate"] == "WDT"


def test_proforma_document_409_when_not_proforma_type():
    """
    wFirma doc is type='invoice' (not proforma) → HTTPException 409.
    """
    from fastapi import HTTPException
    draft = _make_draft(wfirma_proforma_id="999")
    with (
        patch("app.api.routes_proforma._proforma_db_path", return_value="/tmp/nope.db"),
        patch("app.api.routes_proforma.pildb.get_draft", return_value=draft),
        patch("app.api.routes_proforma.wfirma_client.fetch_invoice_xml",
              return_value=_REGULAR_INVOICE_XML),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_proforma_doc()
    assert exc_info.value.status_code == 409
    assert "NOT_A_PROFORMA" in str(exc_info.value.detail)


def test_proforma_document_502_when_wfirma_fetch_raises():
    """
    wfirma_client.fetch_invoice_xml raises → HTTPException 502.
    """
    from fastapi import HTTPException
    draft = _make_draft(wfirma_proforma_id=_PROFORMA_ID)
    with (
        patch("app.api.routes_proforma._proforma_db_path", return_value="/tmp/nope.db"),
        patch("app.api.routes_proforma.pildb.get_draft", return_value=draft),
        patch("app.api.routes_proforma.wfirma_client.fetch_invoice_xml",
              side_effect=RuntimeError("invoices/find HTTP 503")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_proforma_doc()
    assert exc_info.value.status_code == 502
    assert "PROFORMA_FETCH_FAILED" in str(exc_info.value.detail)
