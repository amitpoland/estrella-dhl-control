"""wFirma PZ document — PDF access closure (2026-05-22).

wFirma exposes no warehouse-document PDF endpoint (confirmed: no
warehouse_document_p_z/download, no warehousedocuments/download).
The confirmed available PDF path is invoices/download/{id}, used for
proforma PDFs only.

This module pins:
  1.  PZ viewer UI note is present in shipment-detail.html.
  2.  Note has a data-testid for test hooks.
  3.  Generated-PDF download button wired to correct /pz_document.pdf route.
  4.  Backend route /pz_document.pdf exists in routes_wfirma.py (source-grep).
  5.  PDF route raises 404 when no PZ doc_id is linked.
  6.  PDF route returns PDF bytes when wFirma fetch succeeds.
  7.  Generated PDF is labelled correctly (not "Original wFirma PDF").
  8.  PDF route raises 502 when wFirma fetch fails.
  9.  Proforma PDF button already present in HTML (regression lock).
  10. Generated PDF download anchor has safe link attributes.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"
HTML   = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api>
    <warehouse_documents>
        <warehouse_document>
            <id>185759075</id>
            <fullnumber>PZ 9/5/2026</fullnumber>
            <date>2026-05-21</date>
            <netto>11885.68</netto>
            <brutto>14619.39</brutto>
            <currency>PLN</currency>
            <status>pending</status>
            <description>INV:088/2026-2027\nAWB:4789974092</description>
            <warehouse><id>347088</id></warehouse>
            <contractor><id>71554001</id><altname>Global Jewellery Pvt. Ltd.</altname></contractor>
            <warehouse_document_contents>
                <warehouse_document_content>
                    <id>666562211</id>
                    <name>Gold Bracelet</name>
                    <count>2</count>
                    <price>1131.64</price>
                    <good><id>49514211</id><name>Gold Bracelet</name></good>
                </warehouse_document_content>
            </warehouse_document_contents>
        </warehouse_document>
    </warehouse_documents>
</api>"""

_AUDIT_WITH_PZ = {
    "wfirma_export": {"wfirma_pz_doc_id": "185759075", "pz_source": "created_via_app"},
}
_AUDIT_NO_PZ = {"wfirma_export": {}}


def _fetch_ok():
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=True, pz_doc_id="185759075",
                         pz_number="PZ 9/5/2026", raw_response=SAMPLE_XML)


def _fetch_fail():
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=False, error="timeout")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── 1. UI note text present ───────────────────────────────────────────────────

def test_ui_pdf_unavailability_note_text():
    src = HTML.read_text(encoding="utf-8")
    assert "PZ PDF download is not available through confirmed wFirma API" in src, (
        "PZ viewer must include PDF unavailability note"
    )
    assert "Verified PZ data shown from wFirma document API" in src, (
        "PZ viewer note must state verified data source"
    )


# ── 2. Note has data-testid ───────────────────────────────────────────────────

def test_ui_pdf_note_has_testid():
    src = HTML.read_text(encoding="utf-8")
    assert 'data-testid="pz-document-pdf-note"' in src, (
        "PZ PDF note must have data-testid=pz-document-pdf-note"
    )


# ── 3. Generated-PDF download button wired to correct route ──────────────────

def test_ui_generated_pdf_button_wired():
    src = HTML.read_text(encoding="utf-8")
    assert 'data-testid="btn-pz-download-generated-pdf"' in src, (
        "Generated PDF button must have data-testid"
    )
    assert "/wfirma/pz_document.pdf" in src, (
        "Generated PDF button must link to /wfirma/pz_document.pdf"
    )
    # Must use the confirmed router prefix
    btn_idx = src.find("btn-pz-download-generated-pdf")
    vicinity = src[btn_idx:btn_idx + 300]
    assert "api/v1/upload/shipment" in vicinity, (
        "Generated PDF link must use /api/v1/upload/shipment/ prefix"
    )


# ── 4. Backend route exists (source-grep) ────────────────────────────────────

def test_backend_route_pz_document_pdf_exists():
    src = ROUTES.read_text(encoding="utf-8")
    assert 'async def wfirma_pz_document_pdf(' in src, (
        "wfirma_pz_document_pdf route must be defined in routes_wfirma.py"
    )
    assert '"/shipment/{batch_id}/wfirma/pz_document.pdf"' in src, (
        "Route decorator must use /pz_document.pdf path"
    )
    assert "Generated from verified wFirma PZ data" in src, (
        "PDF must carry the correct 'generated from verified data' label"
    )


# ── 5. PDF route 404 when no PZ linked ───────────────────────────────────────

def test_pdf_route_404_when_no_pz():
    from fastapi import HTTPException
    from app.api.routes_wfirma import wfirma_pz_document_pdf
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_NO_PZ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run(wfirma_pz_document_pdf("NOLINK"))
    assert exc_info.value.status_code == 404
    assert "PZ_NOT_LINKED" in str(exc_info.value.detail)


# ── 6. PDF route returns PDF bytes on success ────────────────────────────────

def test_pdf_route_returns_pdf_bytes():
    from app.api.routes_wfirma import wfirma_pz_document_pdf
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_PZ),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_fetch_ok()),
    ):
        resp = _run(wfirma_pz_document_pdf("B1"))
    assert resp.status_code == 200
    assert resp.media_type == "application/pdf"
    assert len(resp.body) > 100
    assert resp.body[:4] == b"%PDF"


# ── 7. PDF filename in Content-Disposition derived from PZ number ─────────────

def test_pdf_content_disposition_uses_pz_number():
    """Content-Disposition filename must derive from the PZ full number,
    not a generic name, confirming the route reads the correct PZ data."""
    from app.api.routes_wfirma import wfirma_pz_document_pdf
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_PZ),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_fetch_ok()),
    ):
        resp = _run(wfirma_pz_document_pdf("B2"))
    assert resp.status_code == 200
    disposition = resp.headers.get("content-disposition", "")
    assert "PZ" in disposition or "pz" in disposition.lower(), (
        "Content-Disposition filename must reference the PZ number"
    )
    assert ".pdf" in disposition, (
        "Content-Disposition filename must end with .pdf"
    )
    # Source-level: label must be in the route code, not the original PDF claim
    src = ROUTES.read_text(encoding="utf-8")
    assert "Generated from verified wFirma PZ data" in src
    assert "Original wFirma PDF" not in src


# ── 8. PDF route 502 when wFirma fetch fails ─────────────────────────────────

def test_pdf_route_502_on_fetch_failure():
    from fastapi import HTTPException
    from app.api.routes_wfirma import wfirma_pz_document_pdf
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_PZ),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_fetch_fail()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run(wfirma_pz_document_pdf("B3"))
    assert exc_info.value.status_code == 502
    assert "PZ_FETCH_FAILED" in str(exc_info.value.detail)


# ── 9. Proforma PDF download button present (regression lock) ─────────────────

def test_proforma_pdf_download_button_present():
    src = HTML.read_text(encoding="utf-8")
    assert 'data-testid="draft-download-proforma-pdf"' in src, (
        "Proforma PDF download button must remain in shipment-detail.html"
    )
    assert "/document.pdf" in src, (
        "Proforma PDF route /document.pdf must be referenced in UI"
    )


# ── 10. Generated PDF link has safe anchor attributes ────────────────────────

def test_ui_generated_pdf_link_has_safe_attributes():
    src = HTML.read_text(encoding="utf-8")
    assert 'rel="noopener noreferrer"' in src, (
        "Generated PDF link must use rel=noopener noreferrer"
    )
    pdf_idx = src.find("btn-pz-download-generated-pdf")
    assert pdf_idx > 0
    vicinity = src[pdf_idx:pdf_idx + 300]
    assert 'target="_blank"' in vicinity, (
        "Generated PDF link must use target=_blank"
    )
