"""
test_shipment_document_hub.py — Shipment Document Hub backend.

Covers the manifest aggregator, the label-package persistence resolver, the
complete-package ZIP route, and the public customer delivery-confirmation flow
(notification idempotency + activation boundary, token expiry/replay, receipt
submission, evidence validation + scoped access, and the structural guarantee
that the public path performs no fiscal writes).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import delivery_confirmation_db as dcdb
from app.services import delivery_confirmation_service as dcs
from app.services import shipment_document_manifest as sdm


# ── Helpers ───────────────────────────────────────────────────────────────────

BATCH = "BATCH-9158478722-2026"
AWB = "7712345678"

_SAMPLE_PDF = b"%PDF-1.4\n%hub test\n%%EOF\n"


def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _proforma_db(tmp_path) -> Path:
    return tmp_path / "proforma_links.db"


def _carrier_db(tmp_path) -> Path:
    return tmp_path / "carrier" / "carrier_shipments.db"


def _seed_draft(tmp_path, *, batch=BATCH, client="ACME", lines=True,
                contractor_id="", proforma_id=None, invoice_id=None):
    db = _proforma_db(tmp_path)
    line_rows = (
        [{"product_code": "RG-1", "design_no": "RG-1", "qty": 1,
          "unit_price": 10.0, "currency": "EUR"}] if lines else []
    )
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=batch, client_name=client, currency="EUR",
        lines=line_rows, client_contractor_id=contractor_id,
    )
    if proforma_id or invoice_id:
        with sqlite3.connect(str(db)) as c:
            if proforma_id:
                c.execute("UPDATE proforma_drafts SET wfirma_proforma_id=?, "
                          "wfirma_proforma_fullnumber=? WHERE id=?",
                          (proforma_id, "PRO 1/2026", draft.id))
            if invoice_id:
                c.execute("UPDATE proforma_drafts SET wfirma_invoice_id=?, "
                          "wfirma_invoice_number=? WHERE id=?",
                          (invoice_id, "WDT 1/2026", draft.id))
    return pildb.get_draft_by_id(db, draft.id)


def _seed_shipment(tmp_path, *, batch=BATCH, tracking_ref=AWB, client_ref="ACME",
                   created_at="2026-08-08T10:00:00.000Z"):
    from app.services.carrier.persistence import shipment_db
    cdb = _carrier_db(tmp_path)
    cdb.parent.mkdir(parents=True, exist_ok=True)
    shipment_db.init_db(cdb)
    with sqlite3.connect(str(cdb)) as c:
        c.execute(
            "INSERT INTO carrier_shipments "
            "(idempotency_key, batch_id, mode, state, client_ref, tracking_ref, created_at) "
            "VALUES (?, ?, 'shadow', 'complete', ?, ?, ?)",
            (f"idem-{tracking_ref}", batch, client_ref, tracking_ref, created_at),
        )


def _write_dhl_doc(tmp_path, kind_subdir, batch, awb):
    d = tmp_path / "carrier" / kind_subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{batch}-{awb}.pdf").write_bytes(_SAMPLE_PDF)


def _build(tmp_path, draft_id):
    # Force carrier soft-skip so unit tests never hit live MyDHL Get Image / ePOD.
    with patch.object(settings, "carrier_api_status", "pending"):
        return sdm.build_manifest(
            draft_id, storage_root=tmp_path,
            proforma_db=_proforma_db(tmp_path), carrier_db=_carrier_db(tmp_path),
        )


def _find(entries, doc_type):
    for e in entries:
        if e["document_type"] == doc_type:
            return e
    return None


@pytest.fixture()
def client(tmp_path):
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── 1. Draft proforma uses Estrella preview, not wFirma ─────────────────────────

def test_draft_proforma_uses_estrella_preview(tmp_path):
    """Draft Proforma must use canonical browser modal — not preview.html."""
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path)
        m = _build(tmp_path, d.id)
    entry = _find(m["groups"]["commercial"], "draft_proforma")
    assert entry["authority"] == "Estrella"
    assert entry["status"] == "Generated"
    assert entry["reason"] == "browser_preview"
    assert entry["preview_url"] is None
    assert entry["download_available"] is False
    # No parallel server HTML preview authority on the Documents card.
    assert "preview.html" not in str(entry)
    # Official wFirma proforma remains a distinct card.
    official = _find(m["groups"]["commercial"], "official_proforma")
    assert official["authority"] == "wFirma"
    assert official["status"] == "Pending"


def test_no_second_draft_proforma_renderer_in_hub_ui():
    """Documents hub must open onOpenPreview('proforma'), not preview.html."""
    jsx = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
    src = jsx.read_text(encoding="utf-8")
    # Hub previewClick routes draft_proforma to canonical modal.
    assert "document_type === 'draft_proforma'" in src
    assert "onOpenPreview('proforma')" in src or 'onOpenPreview("proforma")' in src
    # Manifest no longer pins draft card to preview.html (server HTML is not
    # the Documents-tab authority). Keep estrella-doc-proforma as the renderer.
    assert "estrella-doc-proforma" in src or "EJProforma" in src


# ── 2. Posted proforma exposes official wFirma PDF URL ──────────────────────────

def test_posted_proforma_exposes_official_pdf(tmp_path):
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
        m = _build(tmp_path, d.id)
    entry = _find(m["groups"]["commercial"], "official_proforma")
    assert entry["authority"] == "wFirma"
    assert entry["status"] == "Generated"
    assert entry["download_url"] == f"/api/v1/proforma/{BATCH}/ACME/document.pdf"
    assert entry["download_available"] is True


# ── 3. Invoice pending until wfirma_invoice_id ──────────────────────────────────

def test_invoice_pending_until_invoice_id(tmp_path):
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
        m1 = _build(tmp_path, d.id)
        inv = _find(m1["groups"]["commercial"], "invoice")
        assert inv["status"] == "Pending"
        assert inv["download_available"] is False

        d2 = _seed_draft(tmp_path, client="BETA", proforma_id="WF-PROF-2",
                         invoice_id="WF-INV-9")
        m2 = _build(tmp_path, d2.id)
    inv2 = _find(m2["groups"]["commercial"], "invoice")
    assert inv2["status"] == "Generated"
    assert inv2["download_url"] == f"/api/v1/proforma/draft/{d2.id}/invoice.pdf"


# ── 4. Client-scoped — no cross-client AWB leak ─────────────────────────────────

def test_client_scoped_no_cross_client_leak(tmp_path):
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d_a = _seed_draft(tmp_path, client="ACME")
        _seed_draft(tmp_path, client="BETA")   # same batch, second client
        # A shipment booked only for BETA.
        _seed_shipment(tmp_path, client_ref="BETA")
        m = _build(tmp_path, d_a.id)   # manifest for ACME
    assert m["awb"] is None, "ACME's manifest must not show BETA's AWB"
    assert m["tracking"]["awb"] is None


# ── 5. Historical unavailable waybill when AWB exists but file missing ──────────

def test_waybill_not_provided_does_not_block_complete_package(tmp_path, monkeypatch):
    """When Get Image is not authorized / empty, waybill is Pending — not a package blocker."""
    from app.services.carrier import document_image_service as dis

    class _Denied:
        status = "not_authorized"
        detail = "8032"
        path = None

    monkeypatch.setattr(dis, "ensure_waybill_persisted",
                        lambda *a, **k: _Denied())
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
        _seed_shipment(tmp_path, client_ref="ACME")
        _write_dhl_doc(tmp_path, "labels", BATCH, AWB)
        m = _build(tmp_path, d.id)
    assert m["awb"] == AWB
    wb = _find(m["groups"]["carrier"], "dhl_waybill")
    assert wb["status"] == "Pending"
    assert wb["required_for_complete_package"] is False
    assert "Not provided by DHL" in (wb["reason"] or "")
    cp = m["groups"]["complete_package"]
    assert cp["ready"] is True
    assert not any("Waybill" in x for x in cp["missing"])


def test_waybill_recoverable_path_persists_and_requires(tmp_path, monkeypatch):
    from app.services.carrier import document_image_service as dis
    target = tmp_path / "carrier" / "waybill_docs" / f"{BATCH}-{AWB}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_SAMPLE_PDF)

    class _Ok:
        status = "persisted"
        detail = None
        path = target

    monkeypatch.setattr(dis, "ensure_waybill_persisted",
                        lambda *a, **k: _Ok())
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-1")
        _seed_shipment(tmp_path, client_ref="ACME")
        _write_dhl_doc(tmp_path, "labels", BATCH, AWB)
        m = _build(tmp_path, d.id)
    wb = _find(m["groups"]["carrier"], "dhl_waybill")
    assert wb["status"] == "Generated"
    assert wb["required_for_complete_package"] is True
    assert wb["download_url"] == f"/api/v1/carrier/{BATCH}/waybill-doc/{AWB}"


# ── 6. Label package persistence resolver (client-scoped preference) ────────────

def test_doc_package_file_client_scoped_resolution(tmp_path):
    from app.api.routes_carrier_actions import _doc_package_file
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        pkg_dir = tmp_path / "carrier" / "doc_packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        # Client-scoped file present → preferred.
        (pkg_dir / f"{BATCH}__ACME.pdf").write_bytes(_SAMPLE_PDF)
        got = _doc_package_file(BATCH, "ACME")
        assert got is not None and got.name == f"{BATCH}__ACME.pdf"
        # Legacy batch-only fallback for an unknown client.
        (pkg_dir / f"{BATCH}.zip").write_bytes(b"PK\x03\x04zip")
        legacy = _doc_package_file(BATCH, "NOBODY")
        assert legacy is not None and legacy.name == f"{BATCH}.zip"


# ── 7. Complete package blocked when mandatory missing ──────────────────────────

def test_complete_package_blocked_when_missing(tmp_path, client):
    d = _seed_draft(tmp_path)   # lines yes, not posted, no AWB
    m = _build(tmp_path, d.id)
    cp = m["groups"]["complete_package"]
    assert cp["ready"] is False
    assert cp["missing"]
    r = client.get(
        f"/api/v1/shipment-documents/draft/{d.id}/complete-package",
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "COMPLETE_PACKAGE_NOT_READY"
    assert r.json()["detail"]["missing"]


# ── 8. Complete package ZIP ready when all present ──────────────────────────────

def test_complete_package_zip_ready(tmp_path, client, monkeypatch):
    d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
    _seed_shipment(tmp_path, client_ref="ACME")
    _write_dhl_doc(tmp_path, "labels", BATCH, AWB)
    _write_dhl_doc(tmp_path, "waybill_docs", BATCH, AWB)

    m = _build(tmp_path, d.id)
    assert m["groups"]["complete_package"]["ready"] is True

    from app.services import wfirma_client
    from app.services.carrier import doc_package
    monkeypatch.setattr(wfirma_client, "fetch_invoice_pdf", lambda _id: _SAMPLE_PDF)
    monkeypatch.setattr(doc_package, "_load_company_profile", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_load_proforma_draft", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_resolve_customer_from_batch", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "render_packing_list_pdf",
                        lambda *a, **k: b"%PDF-1.4 packing %%EOF")

    r = client.get(
        f"/api/v1/shipment-documents/draft/{d.id}/complete-package",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["cache-control"].startswith("no-store")
    import io, zipfile
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert any("proforma" in n for n in names)
    assert any("packing" in n for n in names)
    assert any("label" in n for n in names)


# ── 8b. Standalone Commercial Packing List PDF download ─────────────────────────

def test_packing_list_manifest_exposes_download(tmp_path):
    """Documents hub must offer Download via the commercial packing-list.pdf route."""
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path)
        m = _build(tmp_path, d.id)
    entry = _find(m["groups"]["commercial"], "packing_list")
    assert entry["status"] == "Generated"
    assert entry["preview_available"] is True
    assert entry["download_available"] is True
    assert entry["download_url"] == (
        f"/api/v1/shipment-documents/draft/{d.id}/packing-list.pdf"
    )


def test_packing_list_pdf_download_reuses_commercial_renderer(tmp_path, client, monkeypatch):
    """Standalone download must call doc_package.render_packing_list_pdf only."""
    d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
    from app.services.carrier import doc_package
    calls = {"n": 0}

    def _fake_render(*_a, **_k):
        calls["n"] += 1
        return b"%PDF-1.4 commercial packing %%EOF"

    monkeypatch.setattr(doc_package, "_load_company_profile", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_load_proforma_draft", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_resolve_customer_from_batch", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "render_packing_list_pdf", _fake_render)

    r = client.get(
        f"/api/v1/shipment-documents/draft/{d.id}/packing-list.pdf",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"].startswith("no-store")
    assert r.content.startswith(b"%PDF")
    assert "packing-list" in (r.headers.get("content-disposition") or "").lower()
    assert calls["n"] == 1


def test_packing_list_download_and_zip_share_same_render_path(tmp_path, client, monkeypatch):
    """Standalone PDF and Complete Package ZIP packing-list.pdf are the same authority."""
    d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
    _seed_shipment(tmp_path, client_ref="ACME")
    _write_dhl_doc(tmp_path, "labels", BATCH, AWB)
    _write_dhl_doc(tmp_path, "waybill_docs", BATCH, AWB)

    from app.services import wfirma_client
    from app.services.carrier import doc_package
    marker = b"%PDF-1.4 SAME-COMMERCIAL-PACKING %%EOF"
    monkeypatch.setattr(wfirma_client, "fetch_invoice_pdf", lambda _id: _SAMPLE_PDF)
    monkeypatch.setattr(doc_package, "_load_company_profile", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_load_proforma_draft", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_resolve_customer_from_batch", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "render_packing_list_pdf", lambda *a, **k: marker)

    r_pdf = client.get(
        f"/api/v1/shipment-documents/draft/{d.id}/packing-list.pdf",
        headers=_auth_headers(),
    )
    r_zip = client.get(
        f"/api/v1/shipment-documents/draft/{d.id}/complete-package",
        headers=_auth_headers(),
    )
    assert r_pdf.status_code == 200
    assert r_zip.status_code == 200
    assert r_pdf.content == marker
    import io, zipfile
    zf = zipfile.ZipFile(io.BytesIO(r_zip.content))
    assert zf.read("packing-list.pdf") == marker


def test_hub_ui_wires_packing_list_download_testid():
    jsx = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
    src = jsx.read_text(encoding="utf-8")
    assert "pf-doc-${d.document_type}-download" in src
    assert "packing_list" in src
    assert "onOpenPreview" in src and "packing" in src


# ── 9. Delivered triggers exactly one notification (idempotent) ─────────────────

def test_delivered_triggers_single_notification(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "email-id"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"):
        r1 = dcs.maybe_notify_outbound_delivered(
            AWB, draft_id=1, batch_id=BATCH, client_name="ACME",
            delivered=True, carrier_delivered_at="2026-08-08T12:00:00Z",
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com", customer_name="ACME",
        )
        r2 = dcs.maybe_notify_outbound_delivered(
            AWB, draft_id=1, batch_id=BATCH, client_name="ACME",
            delivered=True, carrier_delivered_at="2026-08-08T12:00:00Z",
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com", customer_name="ACME",
        )
    assert r1["notified"] is True
    assert r2["notified"] is False and r2["reason"] == "already_notified"
    assert calls["n"] == 1


def test_failed_notification_does_not_auto_retry(tmp_path, monkeypatch):
    """Failed queue must stay sticky — no re-spam from tracking/webhook loops."""
    calls = {"n": 0}

    def _queue(**kw):
        calls["n"] += 1
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        r1 = dcs.maybe_notify_outbound_delivered(
            "AWB-FAIL-STICKY", draft_id=9, batch_id=BATCH, client_name="ACME",
            delivered=True, carrier_delivered_at="2026-08-08T12:00:00Z",
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com", customer_name="ACME",
        )
        r2 = dcs.maybe_notify_outbound_delivered(
            "AWB-FAIL-STICKY", draft_id=9, batch_id=BATCH, client_name="ACME",
            delivered=True, carrier_delivered_at="2026-08-08T12:00:00Z",
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com", customer_name="ACME",
        )
    assert r1["notified"] is False and r1["reason"] == "email_queue_failed"
    assert r2["notified"] is False and r2["reason"] == "notification_failed"
    assert calls["n"] == 1


def test_delivery_email_redesign_has_cta_and_plaintext(tmp_path):
    html, text = dcs._delivery_email_bodies(
        "ACME", AWB, "https://pz.example.test/receipt/tok",
        carrier_delivered_at="2026-08-08T12:00:00Z",
    )
    assert "Your Estrella shipment has been delivered" in html
    assert "Confirm delivery condition" in html
    assert "https://pz.example.test/receipt/tok" in html
    assert "<script" not in html.lower()
    assert "Your Estrella shipment has been delivered" in text
    assert "https://pz.example.test/receipt/tok" in text
    assert "AWB" in text and AWB in text


LINK = "https://pz.example.test/receipt/tok"


def test_email_brand_tokens_and_no_internal_leakage():
    """Estrella house style, MIME parity, and nothing internal in either body."""
    html, text = dcs._delivery_email_bodies(
        "ACME", AWB, LINK,
        carrier_delivered_at="2026-08-08T12:00:00Z",
        delivery_location="WARSZAWA - PL",
    )

    # House palette — emerald primary, gold accent, cream paper, ink body.
    for token in ("#0B3D2E", "#C9A24B", "#FBF8F1", "#0F172A"):
        assert token in html, token
    assert "Estrella Jewels" in html

    # Operator's verbatim supporting sentence, in BOTH representations.
    assert dcs._SUPPORT_SENTENCE in text
    assert (
        "Please confirm that your shipment arrived safely. If there is any "
        "damage, missing item or packaging problem, you can report it and "
        "attach photographs."
    ) == dcs._SUPPORT_SENTENCE

    # Every outcome the secure link can report is named in both bodies.
    for outcome in dcs._REPORTABLE_OUTCOMES:
        assert outcome in text, outcome

    # Timestamp parity: the SAME formatted string in HTML and plain text.
    when_disp = dcs._format_delivered_at("2026-08-08T12:00:00Z")
    assert when_disp == "08 Aug 2026 12:00 UTC"
    assert when_disp in html and when_disp in text
    assert "2026-08-08T12:00:00Z" not in text  # never the raw ISO value

    # Optional location present here …
    assert "WARSZAWA - PL" in html and "WARSZAWA - PL" in text
    assert "LOCATION" in html

    # … and cleanly absent when the carrier did not report one.
    html2, text2 = dcs._delivery_email_bodies("ACME", AWB, LINK)
    assert "LOCATION" not in html2
    assert "Location" not in text2
    assert "DELIVERED" not in html2  # no timestamp either → row omitted together

    # The receipt URL appears in EVERY CTA branch emitted (VML + plain anchor).
    assert html.count(LINK) >= 3  # v:roundrect href, <a href>, bare-link fallback
    for branch in ("v:roundrect", "<a "):
        assert branch in html
    assert 'xmlns:v="urn:schemas-microsoft-com:vml"' in html

    # No internal identifiers, API paths, or operator terminology.
    for body in (html, text):
        for leak in ("/api/v1", "batch_id", "BATCH-", "draft_id",
                     "customer_delivery_confirmation", "activated_at"):
            assert leak not in body, leak


def test_outbound_delivery_hook_passes_delivered_event_location(tmp_path, monkeypatch):
    """Timestamp and location must come from ONE AND THE SAME delivered event."""
    from app.services import outbound_delivery_hook as hook
    from app.services.carrier import epod_service
    from app.services.carrier.persistence import shipment_db

    carrier_db = tmp_path / "carrier_shipments.db"
    carrier_db.write_bytes(b"")
    monkeypatch.setattr(hook, "_carrier_db_path", lambda: carrier_db)
    monkeypatch.setattr(
        shipment_db, "get_shipment_by_tracking_ref",
        lambda db, awb: {"batch_id": BATCH, "client_ref": None,
                         "created_at": "2026-08-01T00:00:00.000Z"},
    )
    monkeypatch.setattr(epod_service, "ensure_epod_persisted", lambda *a, **k: None)

    seen = {}

    def _spy(awb, **kw):
        seen.update(kw)
        seen["awb"] = awb
        return {"notified": True}

    monkeypatch.setattr(dcs, "maybe_notify_outbound_delivered", _spy)

    events = [
        {"timestamp": "2026-08-07T09:00:00Z", "location": "LEIPZIG - DE",
         "status": "transit", "description": "Processed at facility"},
        {"timestamp": "2026-08-08T12:04:00Z", "location": "WARSZAWA - PL",
         "status": "delivered", "description": "Delivered"},
    ]
    with patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "storage_root", tmp_path):
        hook.on_outbound_tracking_update(AWB, "delivered", events)

    assert seen["delivery_location"] == "WARSZAWA - PL"       # NOT the transit one
    assert seen["carrier_delivered_at"] == "2026-08-08T12:04:00Z"
    # Same event sourced both fields.
    assert hook._delivered_at_from_events(events) == events[1]["timestamp"]
    assert hook._delivered_location_from_events(events) == events[1]["location"]

    # A delivered event with no location yields None, never a guess.
    seen.clear()
    no_loc = [{"timestamp": "2026-08-08T12:04:00Z", "location": "",
               "status": "delivered", "description": "Delivered"}]
    with patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "storage_root", tmp_path):
        hook.on_outbound_tracking_update(AWB, "delivered", no_loc)
    assert seen["delivery_location"] is None
    assert seen["carrier_delivered_at"] == "2026-08-08T12:04:00Z"


def _receipt_page() -> str:
    page = (Path(__file__).resolve().parents[1]
            / "app" / "static" / "public" / "delivery-receipt.html")
    return page.read_text(encoding="utf-8")


def test_receipt_page_data_testids_survive_restyle():
    """The restyle is presentation-only — every operator/customer hook survives."""
    src = _receipt_page()
    for testid in (
        "receipt-loading", "receipt-done", "receipt-form", "receipt-awb",
        "receipt-customer", "condition-good", "condition-issue", "issue-block",
        "cat-package_box_damaged", "cat-packing_damaged", "cat-goods_damaged",
        "cat-item_missing", "cat-theft_tampering", "cat-other",
        "photos-input", "comments-input", "submit-btn",
    ):
        assert f'data-testid="{testid}"' in src, testid
    # Shares the email's identity tokens.
    assert "--accent: #0B3D2E" in src
    assert "--gold: #C9A24B" in src


def test_receipt_page_contract_unchanged():
    """Endpoint, category values and upload contract are byte-identical."""
    src = _receipt_page()
    assert "/api/v1/shipment-documents/public/receipt/" in src
    for value in ("package_box_damaged", "packing_damaged", "goods_damaged",
                  "item_missing", "theft_tampering", "other"):
        assert f'value="{value}"' in src, value
    assert 'accept="image/jpeg,image/png,image/webp,image/gif" multiple' in src
    assert '<meta name="robots" content="noindex,nofollow" />' in src


# ── 10. Delivery before activation does NOT notify (delivery-time gate) ─────────

def test_historical_delivered_before_activation_not_notified(tmp_path, monkeypatch):
    """Activation uses carrier_delivered_at when present (not booking date)."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "email-id"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-08-05T00:00:00.000Z"):
        res = dcs.maybe_notify_outbound_delivered(
            AWB, draft_id=1, batch_id=BATCH, client_name="ACME",
            delivered=True,
            carrier_delivered_at="2026-08-01T12:00:00Z",  # BEFORE activation
            booking_created_at="2026-08-08T00:00:00.000Z",  # after — must not win
            customer_email="buyer@example.com",
        )
    assert res["notified"] is False
    assert res["reason"] == "activation_boundary"
    assert calls["n"] == 0


def test_delivery_after_activation_notifies_even_if_booked_earlier(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "email-id"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-08-05T00:00:00.000Z"), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        res = dcs.maybe_notify_outbound_delivered(
            "7712345699", draft_id=1, batch_id=BATCH, client_name="ACME",
            delivered=True,
            carrier_delivered_at="2026-08-08T12:00:00Z",  # AFTER activation
            booking_created_at="2026-07-01T00:00:00.000Z",  # before — ignored
            customer_email="buyer@example.com",
        )
    assert res["notified"] is True
    assert calls["n"] == 1


def _mint_token(tmp_path, *, expires_delta_days=30, awb=AWB, draft_id=1):
    db = tmp_path / "delivery_confirmations.db"
    token = "test-token-" + str(draft_id)
    import hashlib
    th = hashlib.sha256(token.encode()).hexdigest()
    exp = (datetime.now(timezone.utc) + timedelta(days=expires_delta_days)).strftime(
        "%Y-%m-%dT%H:%M:%fZ")
    dcdb.create_receipt_token_row(
        db, token_hash=th, awb=awb, draft_id=draft_id, batch_id=BATCH,
        client_name="ACME", customer_name="ACME", expires_at=exp,
    )
    return token


# ── 11. Token expiry + replay 409 ───────────────────────────────────────────────

def test_token_expiry_and_replay(tmp_path):
    with patch.object(settings, "storage_root", tmp_path):
        # Expired token → 410.
        expired = _mint_token(tmp_path, expires_delta_days=-1, draft_id=11)
        with pytest.raises(dcs.ReceiptError) as e1:
            dcs.submit_receipt(expired, condition="good")
        assert e1.value.status == 410

        # Fresh token → first submit ok, replay → 409.
        tok = _mint_token(tmp_path, draft_id=12)
        ok = dcs.submit_receipt(tok, condition="good")
        assert ok["ok"] is True
        with pytest.raises(dcs.ReceiptError) as e2:
            dcs.submit_receipt(tok, condition="good")
        assert e2.value.status == 409


# ── 12. Good condition receipt ──────────────────────────────────────────────────

def test_good_condition_receipt(tmp_path):
    with patch.object(settings, "storage_root", tmp_path):
        tok = _mint_token(tmp_path, draft_id=20)
        res = dcs.submit_receipt(tok, condition="good",
                                 categories=["goods_damaged"], comments="thanks")
    assert res["ok"] is True
    assert res["condition"] == "good"
    # A clean receipt carries no issue categories even if some were sent.
    assert res["issue_categories"] == []


# ── 13. Damage report with photo validation (reject exe, oversized) ─────────────

def test_damage_report_photo_validation(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with patch.object(settings, "storage_root", tmp_path):
        tok = _mint_token(tmp_path, draft_id=30)
        res = dcs.submit_receipt(
            tok, condition="issue", categories=["goods_damaged"],
            files=[{"filename": "p.png", "content_type": "image/png", "content": png}],
        )
        assert res["ok"] is True and res["evidence_saved"] == 1

        # Executable masquerading as an image → rejected.
        tok2 = _mint_token(tmp_path, draft_id=31)
        with pytest.raises(dcs.ReceiptError) as e_exe:
            dcs.submit_receipt(
                tok2, condition="issue",
                files=[{"filename": "x.png", "content_type": "image/png",
                        "content": b"MZ\x90\x00 this is a PE exe"}],
            )
        assert e_exe.value.status == 422

        # Oversized image → rejected, and the token is NOT consumed.
        tok3 = _mint_token(tmp_path, draft_id=32)
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 10)
        with pytest.raises(dcs.ReceiptError) as e_big:
            dcs.submit_receipt(
                tok3, condition="issue",
                files=[{"filename": "big.png", "content_type": "image/png",
                        "content": big}],
            )
        assert e_big.value.status == 413
        # Token still usable (validation happens before the token is claimed).
        ok = dcs.submit_receipt(tok3, condition="good")
        assert ok["ok"] is True


# ── 14. Unauthorized / cross-draft evidence access blocked ──────────────────────

def test_evidence_access_scoped_and_authed(tmp_path, client):
    # Seed a receipt + evidence for draft 40.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    tok = _mint_token(tmp_path, draft_id=40)
    dcs.submit_receipt(tok, condition="issue", categories=["goods_damaged"],
                       files=[{"filename": "a.png", "content_type": "image/png",
                               "content": png}])
    db = tmp_path / "delivery_confirmations.db"
    receipt = dcdb.get_receipt_for_draft(db, 40)
    ev = dcdb.list_evidence_for_receipt(db, receipt["id"])[0]

    # Correct draft → 200.
    ok = client.get(
        f"/api/v1/shipment-documents/draft/40/delivery/evidence/{ev['id']}",
        headers=_auth_headers(),
    )
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/")

    # Wrong draft id for the same evidence → 404 (scope guard).
    wrong = client.get(
        f"/api/v1/shipment-documents/draft/999/delivery/evidence/{ev['id']}",
        headers=_auth_headers(),
    )
    assert wrong.status_code == 404


def test_evidence_requires_auth_when_api_key_set(tmp_path):
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None), \
         patch.object(settings, "api_key", "secret-key"), \
         patch.object(settings, "environment", "prod"):
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/shipment-documents/draft/1/delivery/evidence/1")
    assert r.status_code == 401


# ── 15. Public receipt path performs no fiscal writes (structural) ──────────────

def test_public_receipt_no_fiscal_writes_structural():
    src = Path(dcs.__file__).read_text(encoding="utf-8")
    forbidden = [
        "wfirma_client",
        "create_invoice", "create_pz", "create_product", "create_proforma",
        "invoices/add", "invoices/edit",
        "inventory", "reservation_db", "wfirma_reservation",
    ]
    for token in forbidden:
        assert token not in src, (
            f"delivery_confirmation_service must not reference {token!r} — "
            "the public receipt path must never mutate fiscal / inventory state"
        )


# ── 16. MyDHL ePOD — persist, manifest, optional ZIP include ────────────────────

def test_epod_extract_and_persist(tmp_path, monkeypatch):
    import base64
    from app.services.carrier.adapters.live import _extract_epod_pdf_bytes
    from app.services.carrier import epod_service

    encoded = base64.b64encode(_SAMPLE_PDF).decode()
    assert _extract_epod_pdf_bytes({"documents": [{"content": encoded}]}) == _SAMPLE_PDF
    assert _extract_epod_pdf_bytes({"content": "not-pdf"}) is None

    class _Fake:
        def fetch_electronic_pod(self, tracking_ref, content="epod-summary"):
            return _SAMPLE_PDF

    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None), \
         patch.object(settings, "carrier_api_status", "live"), \
         patch("app.services.carrier.factory.get_adapter", lambda cfg: _Fake()):
        path = epod_service.ensure_epod_persisted(BATCH, AWB)
        assert path is not None and path.is_file()
        assert path.read_bytes() == _SAMPLE_PDF
        # Idempotent — second call returns same file without re-fetch.
        again = epod_service.ensure_epod_persisted(BATCH, AWB)
        assert again == path


def test_epod_manifest_and_complete_package_optional(tmp_path, client, monkeypatch):
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
        _seed_shipment(tmp_path, client_ref="ACME")
        m0 = _build(tmp_path, d.id)
        ep0 = _find(m0["groups"]["carrier"], "dhl_epod")
        assert ep0["status"] == "Pending"
        assert ep0["required_for_complete_package"] is False
        assert "Available after eligible DHL delivery" in (ep0["reason"] or "")

        _write_dhl_doc(tmp_path, "labels", BATCH, AWB)
        _write_dhl_doc(tmp_path, "epods", BATCH, AWB)
        m1 = _build(tmp_path, d.id)
        ep1 = _find(m1["groups"]["carrier"], "dhl_epod")
        assert ep1["status"] == "Generated"
        assert ep1["download_url"] == f"/api/v1/carrier/{BATCH}/epod/{AWB}"
        # Label alone is enough — waybill not required when DHL never provided one.
        assert m1["groups"]["complete_package"]["ready"] is True

    from app.services import wfirma_client
    from app.services.carrier import doc_package
    monkeypatch.setattr(wfirma_client, "fetch_invoice_pdf", lambda _id: _SAMPLE_PDF)
    monkeypatch.setattr(doc_package, "_load_company_profile", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_load_proforma_draft", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "_resolve_customer_from_batch", lambda *a, **k: None)
    monkeypatch.setattr(doc_package, "render_packing_list_pdf",
                        lambda *a, **k: b"%PDF-1.4 packing %%EOF")
    r = client.get(
        f"/api/v1/shipment-documents/draft/{d.id}/complete-package",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "dhl-epod.pdf" in names


def test_epod_not_eligible_after_delivered(tmp_path, monkeypatch):
    from app.services.carrier import epod_service as es

    class _No:
        status = "not_eligible"
        detail = "404"
        path = None

    monkeypatch.setattr(es, "ensure_epod_result", lambda *a, **k: _No())
    monkeypatch.setattr(sdm, "_tracking_says_delivered", lambda *a, **k: True)
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path)
        _seed_shipment(tmp_path, client_ref="ACME")
        m = _build(tmp_path, d.id)
    ep = _find(m["groups"]["carrier"], "dhl_epod")
    assert ep["status"] == "Pending"
    assert "Not provided by DHL" in (ep["reason"] or "")


def test_commercial_package_generate_meta(tmp_path):
    from app.services.master_data_db import init_db, upsert_box_type
    md = tmp_path / "master_data.sqlite"
    init_db(md)
    upsert_box_type(md, {
        "code": "DHL-RING", "name": "Ring",
        "length_cm": 20, "width_cm": 15, "height_cm": 10,
        "tare_weight_kg": 0.1, "carrier": "DHL", "active": 1,
    })
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-1")
        _seed_shipment(tmp_path, client_ref="ACME")
        # Attach box_type_code on shipment
        import sqlite3
        with sqlite3.connect(str(_carrier_db(tmp_path))) as c:
            c.execute("UPDATE carrier_shipments SET box_type_code=? WHERE tracking_ref=?",
                      ("DHL-RING", AWB))
        m = _build(tmp_path, d.id)
    pkg = _find(m["groups"]["carrier"], "dhl_commercial_package")
    assert "generate" in pkg
    assert pkg["generate"]["can_generate"] is True
    assert pkg["generate"]["box_type_id"] is not None


def test_cmr_never_required_for_complete_package(tmp_path):
    """CMR authority remains browser JSX — no server PDF, never a package blocker."""
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "carrier_storage_root", None):
        d = _seed_draft(tmp_path, proforma_id="WF-PROF-1")
        _seed_shipment(tmp_path, client_ref="ACME")
        m = _build(tmp_path, d.id)
    cmr = _find(m["groups"]["transport"], "cmr")
    assert cmr["required_for_complete_package"] is False
    assert cmr["download_available"] is False
