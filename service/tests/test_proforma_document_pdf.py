"""
test_proforma_document_pdf.py — Phase 8:
real Download Proforma PDF endpoint (read-only).

Covers:
  - wfirma_client.fetch_invoice_pdf
      * uses path-based GET invoices/download/{id} (read-only)
      * rejects empty id
      * decodes base64-XML envelope shape (dbojdo / webit SDK shape)
      * returns raw bytes when wFirma streams binary directly
      * surfaces 404 / non-OK / parse errors as RuntimeError
  - GET /api/v1/proforma/{batch}/{client}/document.pdf
      * 404 when no draft / no wfirma_proforma_id
      * 502 when wFirma fetch fails
      * 200 with application/pdf + correct filename when posted
      * existing JSON /document endpoint still works
  - dashboard.html
      * has the Download PDF button wired to /document.pdf
      * has no Email / Statement / CMR / XLSX buttons in the posted toolbar
"""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client


# ── Helpers ─────────────────────────────────────────────────────────────────

def _auth_headers(operator: str = "alice"):
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_posted_draft(db: Path, *,
                        batch="B1", client_name="ACME",
                        wfirma_id="WF-PROF-9001",
                        fullnumber="PRO 12_2026"):
    """Create a draft that LOOKS posted, without going through Phase 5."""
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=batch, client_name=client_name, currency="EUR",
        lines=[{"product_code": "X", "design_no": "X", "qty": 1,
                "unit_price": 5.0, "currency": "EUR"}],
    )
    # Promote directly: editing → approved → posting → posted (Phase 5 flow).
    e = pildb.update_draft_fields(
        db, d.id, {"remarks": "ready"}, "alice", d.updated_at,
    )
    a = pildb.approve_draft(
        db, d.id, "alice", e.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    p = pildb.start_post(
        db, d.id, "alice", a.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    return pildb.mark_post_succeeded(
        db, d.id,
        wfirma_proforma_id         = wfirma_id,
        wfirma_proforma_fullnumber = fullnumber,
        operator                   = "alice",
    )


_SAMPLE_PDF_BYTES = b"%PDF-1.4\n%fake test pdf\n%%EOF\n"


def _xml_envelope_with_pdf(pdf_bytes: bytes) -> str:
    """Build a wFirma-shaped XML envelope wrapping a base64-encoded PDF.
    NB: the real wFirma collection responses wrap items in numerically-
    named elements (``<0>``, ``<1>`` …) which ``xml.etree.ElementTree``
    cannot parse. Single-document responses (``invoices/get/{id}`` and
    ``invoices/download/{id}``) do NOT use the numeric wrapper — they
    return ``<invoice>`` directly under ``<invoices>``. This mirrors the
    shape ``fetch_invoice_xml`` already relies on."""
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<api>'
          '<invoices>'
            '<invoice>'
              '<id>9001</id>'
              f'<file>{b64}</file>'
            '</invoice>'
          '</invoices>'
          '<status><code>OK</code><description>OK</description></status>'
        '</api>'
    )


# ════════════════════════════════════════════════════════════════════════
#  fetch_invoice_pdf — service-level tests
# ════════════════════════════════════════════════════════════════════════

def test_fetch_pdf_uses_read_only_endpoint(monkeypatch):
    """The helper MUST call invoices/download (read-only). It must NEVER
    call invoices/add, invoices/edit, invoices/send, invoices/fiscalise,
    or any other write/state-changing endpoint."""
    captured = {}

    def _fake(method, module, action, body=""):
        captured["method"] = method
        captured["module"] = module
        captured["action"] = action
        captured["body"]   = body
        return 200, _xml_envelope_with_pdf(_SAMPLE_PDF_BYTES)

    monkeypatch.setattr(wfirma_client, "_http_request", _fake)
    pdf = wfirma_client.fetch_invoice_pdf("12345")
    assert pdf == _SAMPLE_PDF_BYTES
    assert captured["method"]            == "GET"
    assert captured["module"]            == "invoices"
    assert captured["action"].startswith("download/")
    assert "12345" in captured["action"]
    assert captured["body"]              == ""
    # Defence: forbidden actions never appear.
    for forbidden in ("add", "edit", "send", "fiscalise", "delete"):
        assert forbidden not in captured["action"]


def test_fetch_pdf_rejects_empty_id():
    for bad in ("", "  ", None):
        with pytest.raises(ValueError) as exc:
            wfirma_client.fetch_invoice_pdf(bad)
        assert "invoice_id is required" in str(exc.value)


def test_fetch_pdf_decodes_base64_envelope(monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, _xml_envelope_with_pdf(_SAMPLE_PDF_BYTES)),
    )
    out = wfirma_client.fetch_invoice_pdf("9001")
    assert out.startswith(b"%PDF-")
    assert b"%%EOF" in out


def test_fetch_pdf_handles_raw_binary_response(monkeypatch):
    """Some wFirma installations stream the PDF directly. Magic header
    must trigger the bytes branch."""
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, _SAMPLE_PDF_BYTES.decode("latin-1")),
    )
    out = wfirma_client.fetch_invoice_pdf("9001")
    assert out.startswith(b"%PDF-")


def test_fetch_pdf_404(monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (404, "<api><status><code>NOT_FOUND</code></status></api>"),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_invoice_pdf("nope")
    assert "not found" in str(exc.value).lower()


def test_fetch_pdf_http_500(monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (500, "internal error"),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_invoice_pdf("9001")
    assert "HTTP 500" in str(exc.value)


def test_fetch_pdf_wfirma_status_error(monkeypatch):
    err_xml = (
        '<api><status><code>ERROR</code>'
        '<description>access denied</description></status></api>'
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, err_xml),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_invoice_pdf("9001")
    assert "access denied" in str(exc.value)


def test_fetch_pdf_missing_payload_raises(monkeypatch):
    """OK status but no <file> blob — defensive RuntimeError, not silent."""
    no_blob = (
        '<api><invoices><invoice><id>9001</id></invoice></invoices>'
        '<status><code>OK</code></status></api>'
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, no_blob),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_invoice_pdf("9001")
    assert "no base64 PDF payload" in str(exc.value)


def test_fetch_pdf_decoded_payload_not_a_pdf(monkeypatch):
    """Base64 decodes to non-PDF bytes — defensive RuntimeError."""
    junk = base64.b64encode(b"this is not a pdf, just garbage padding 1234567890" * 3).decode()
    bad_xml = (
        f'<api><invoice><file>{junk}</file></invoice>'
        '<status><code>OK</code></status></api>'
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, bad_xml),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_invoice_pdf("9001")
    msg = str(exc.value)
    # New error shape: every candidate tried but none decoded to a PDF.
    assert "no base64 PDF payload" in msg
    assert "not %PDF-" in msg


def test_fetch_pdf_unparseable_response(monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, "<<not xml at all"),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_invoice_pdf("9001")
    # The shared _parse_status helper catches malformed XML first and
    # surfaces it as wFirma status=PARSE_ERROR. Either error path is
    # acceptable — what matters is that the helper raises RuntimeError
    # rather than returning bad bytes.
    msg = str(exc.value)
    assert ("neither PDF nor parseable XML" in msg
            or "PARSE_ERROR" in msg)


# ════════════════════════════════════════════════════════════════════════
#  Route — GET /api/v1/proforma/{batch}/{client}/document.pdf
# ════════════════════════════════════════════════════════════════════════

def test_route_404_when_no_draft(client, tmp_path):
    r = client.get(
        "/api/v1/proforma/B1/ACME/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["code"] == "PROFORMA_NOT_LINKED"


def test_route_404_when_draft_has_no_wfirma_id(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME", currency="EUR",
        lines=[{"product_code": "X", "design_no": "X", "qty": 1,
                "unit_price": 5.0, "currency": "EUR"}],
    )
    # Draft exists but has not been posted → no wfirma_proforma_id
    r = client.get(
        "/api/v1/proforma/B1/ACME/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "PROFORMA_NOT_LINKED"


def test_route_returns_pdf_bytes_with_correct_media_type(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    posted = _seed_posted_draft(db,
                                  wfirma_id="WF-9001",
                                  fullnumber="PRO 12_2026")
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_pdf",
        lambda invoice_id: _SAMPLE_PDF_BYTES if invoice_id == "WF-9001"
                            else (_ for _ in ()).throw(AssertionError(
                                f"unexpected id={invoice_id}")),
    )
    r = client.get(
        f"/api/v1/proforma/{posted.batch_id}/{posted.client_name}/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == _SAMPLE_PDF_BYTES
    # Filename uses fullnumber (sanitised).
    cd = r.headers.get("content-disposition", "")
    assert "PRO 12_2026.pdf" in cd


def test_route_filename_falls_back_to_wfirma_id(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    posted = _seed_posted_draft(db, wfirma_id="WF-7777", fullnumber="")
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_pdf",
        lambda invoice_id: _SAMPLE_PDF_BYTES,
    )
    r = client.get(
        f"/api/v1/proforma/{posted.batch_id}/{posted.client_name}/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "proforma-WF-7777.pdf" in cd


def test_route_filename_sanitises_slashes_in_fullnumber(client, tmp_path, monkeypatch):
    """wFirma fullnumbers can include '/' (e.g. 'PRO 12/2026') which is
    invalid in Content-Disposition / on most filesystems. The route
    must replace it with a safe character."""
    db = tmp_path / "proforma_links.db"
    posted = _seed_posted_draft(db, wfirma_id="WF-9", fullnumber="PRO 12/2026")
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_pdf",
        lambda invoice_id: _SAMPLE_PDF_BYTES,
    )
    r = client.get(
        f"/api/v1/proforma/{posted.batch_id}/{posted.client_name}/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "/" not in cd.split("filename=", 1)[1]


def test_route_handles_wfirma_error_safely(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    posted = _seed_posted_draft(db, wfirma_id="WF-BAD")

    def _boom(invoice_id):
        raise RuntimeError("invoices/download HTTP 500: boom")
    monkeypatch.setattr(wfirma_client, "fetch_invoice_pdf", _boom)

    r = client.get(
        f"/api/v1/proforma/{posted.batch_id}/{posted.client_name}/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["code"]               == "PROFORMA_PDF_FETCH_FAILED"
    assert detail["wfirma_proforma_id"] == "WF-BAD"


def test_route_handles_connection_error(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    posted = _seed_posted_draft(db)

    def _boom(invoice_id):
        raise ConnectionError("wFirma HTTP error: timeout")
    monkeypatch.setattr(wfirma_client, "fetch_invoice_pdf", _boom)

    r = client.get(
        f"/api/v1/proforma/{posted.batch_id}/{posted.client_name}/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert "wFirma PDF fetch failed" in r.json()["detail"]["error"]


def test_route_does_not_call_wfirma_when_no_draft(client, tmp_path, monkeypatch):
    """Defence: if there's nothing to fetch, the wFirma call must not happen."""
    called = {"n": 0}
    def _stub(invoice_id):
        called["n"] += 1
        return _SAMPLE_PDF_BYTES
    monkeypatch.setattr(wfirma_client, "fetch_invoice_pdf", _stub)

    r = client.get(
        "/api/v1/proforma/B1/ACME/document.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    assert called["n"] == 0


# ════════════════════════════════════════════════════════════════════════
#  Existing JSON /document endpoint — regression
# ════════════════════════════════════════════════════════════════════════

def test_json_document_endpoint_still_works(client, tmp_path, monkeypatch):
    """The new .pdf route must not have broken the existing JSON /document
    route. They share the same prefix; FastAPI must dispatch them
    distinctly."""
    db = tmp_path / "proforma_links.db"
    posted = _seed_posted_draft(db, wfirma_id="WF-3000")
    sample_xml = (
        '<api><invoice><id>3000</id><type>proforma</type>'
        '<fullnumber>PRO 1_2026</fullnumber>'
        '<date>2026-01-01</date>'
        '<currency>EUR</currency>'
        '<contractor><id>C-1</id></contractor>'
        '<status>D</status>'
        '<invoicecontents><invoicecontent>'
        '<name>Test line</name><count>1</count><price>5.0</price>'
        '<netto>5.0</netto><vat>0</vat></invoicecontent></invoicecontents>'
        '</invoice><status><code>OK</code></status></api>'
    )
    monkeypatch.setattr(wfirma_client, "fetch_invoice_xml",
                         lambda _id: sample_xml)
    r = client.get(
        f"/api/v1/proforma/{posted.batch_id}/{posted.client_name}/document",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wfirma_proforma_id"] == "WF-3000"
    assert "raw_xml" in body


# ════════════════════════════════════════════════════════════════════════
#  Dashboard wiring (source-grep)
# ════════════════════════════════════════════════════════════════════════

DASHBOARD = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


@pytest.fixture(scope="module")
def html() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_dashboard_has_download_pdf_button(html):
    assert 'data-testid="draft-download-proforma-pdf"' in html, (
        "Dashboard must expose a Download PDF button next to View Proforma"
    )


def test_dashboard_download_pdf_wired_to_real_endpoint(html):
    """The button must point to /document.pdf — the real new route. No
    other URL is acceptable."""
    idx = html.find('data-testid="draft-download-proforma-pdf"')
    assert idx > 0
    window = html[idx:idx + 600]
    assert "/document.pdf" in window
    # Same template-literal pattern as the JSON viewer
    assert "encodeURIComponent(openDraft.batch_id)" in window
    assert "encodeURIComponent(openDraft.client_name)" in window


def test_dashboard_download_pdf_only_inside_posted_banner(html):
    """The button must live inside the posted banner block so it only
    renders for posted drafts (where wfirma_proforma_id exists). It
    must NOT appear elsewhere in the panel."""
    banner_idx = html.find('data-testid="draft-posted-banner"')
    assert banner_idx > 0
    end = html.find('</div>\n              )}', banner_idx)
    assert end > banner_idx
    block = html[banner_idx:end]
    assert 'data-testid="draft-download-proforma-pdf"' in block, (
        "Download PDF link must be inside the posted-banner block"
    )
    # And nowhere else
    other = html[:banner_idx] + html[end:]
    assert 'data-testid="draft-download-proforma-pdf"' not in other


def test_dashboard_does_not_have_email_button(html):
    assert 'data-testid="draft-email-proforma"'   not in html
    assert "Email Proforma"                        not in html


def test_dashboard_does_not_have_statement_button(html):
    assert 'data-testid="draft-download-statement"' not in html
    assert "Download Statement"                     not in html


def test_dashboard_does_not_have_cmr_button(html):
    assert 'data-testid="draft-download-cmr"'       not in html
    assert "Download CMR"                           not in html


def test_dashboard_does_not_have_xlsx_button(html):
    """No Proforma XLSX endpoint exists, so no button should claim one."""
    # The PZ workflow has its own XLSX (separate panel). The Proforma
    # draft panel must NOT add a Proforma XLSX button.
    panel_idx = html.find('data-testid="proforma-draft-panel"')
    end_idx = html.find('function ProformaDraftLineRow', panel_idx)
    assert panel_idx > 0 and end_idx > panel_idx
    panel_block = html[panel_idx:end_idx]
    assert "Download XLSX"      not in panel_block
    assert "Download Excel"     not in panel_block
    assert "draft-download-xlsx" not in panel_block


def test_dashboard_view_proforma_link_unchanged(html):
    """The Phase 6/7 testid for the JSON viewer stays present."""
    assert 'data-testid="draft-view-proforma-link"' in html
