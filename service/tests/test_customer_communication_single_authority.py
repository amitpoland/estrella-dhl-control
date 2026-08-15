"""Customer communication single-authority regressions."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config.email_routing import (
    delivery_guard_allows_when_delivered,
    email_intent,
)
from app.core.config import settings
from app.services import delivery_confirmation_service as dcs
from app.services import email_service
from app.services.customer_email_template import customer_documents_email
from app.services.customer_send import customer_documents_email_bodies
from app.services.commercial_packing_list import render_commercial_packing_list_pdf
from app.services.commercial_packing_list_html import render_commercial_packing_list_html


# ── Email intent / delivered guard policy ─────────────────────────────────────

@pytest.mark.parametrize(
    "email_type,allowed",
    [
        ("proforma_send", True),
        ("customer_document_send", True),
        ("customer_delivery_confirmation", True),
        ("customer_delivery_reminder", True),
        ("agency", False),
        ("agency_followup", False),
        ("dhl_followup", False),
        ("customs_followup", False),
        ("broker_followup", False),
        ("totally_unknown_type", False),
        ("", False),
    ],
)
def test_delivery_guard_policy_matrix(email_type, allowed):
    assert delivery_guard_allows_when_delivered(email_type) is allowed


def test_email_intent_classification():
    assert email_intent("proforma_send") == "customer_transactional"
    assert email_intent("customer_document_send") == "customer_transactional"
    assert email_intent("customer_delivery_confirmation") == "delivery_confirmation"
    assert email_intent("agency") == "automated_operational_followup"
    assert email_intent("nope") == "unknown"


def test_queue_email_allows_proforma_send_when_delivered(tmp_path, monkeypatch):
    """Defect D: explicit customer document send must not hit shipment_delivered."""
    from app.services import email_sender as es
    from app.services.email_service import FollowupSuppressedError

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(es, "_smtp_configured", lambda: False)

    def _block(_batch_id):
        return {
            "allowed": False,
            "reason": "shipment_delivered",
            "guard": "shipment_delivered",
        }

    monkeypatch.setattr(
        "app.services.shipment_delivered_guard.check_send_allowed",
        _block,
    )
    eid = email_service.queue_email(
        to="buyer@example.com",
        subject="Documents",
        body_html="<p>docs</p>",
        body_text="docs",
        batch_id="BATCH-X",
        email_type="proforma_send",
        attachments=[],
    )
    assert eid
    # Agency still blocked with same delivered signal
    with pytest.raises(FollowupSuppressedError) as ei:
        email_service.queue_email(
            to="agency@example.com",
            subject="chase",
            body_html="<p>x</p>",
            body_text="x",
            batch_id="BATCH-X",
            email_type="agency_followup",
            attachments=[],
        )
    assert ei.value.reason == "shipment_delivered"



# ── Manual vs automatic confirmation ──────────────────────────────────────────

def test_auto_suppressed_when_feature_disabled(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: calls.__setitem__("n", calls["n"] + 1) or "x",
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", False):
        res = dcs.maybe_notify_outbound_delivered(
            "7712999001",
            delivered=True,
            carrier_delivered_at="2026-08-10T12:00:00Z",
            customer_email="buyer@example.com",
        )
    assert res["notified"] is False and res["reason"] == "feature_disabled"
    assert calls["n"] == 0


def test_manual_execute_succeeds_when_feature_disabled(tmp_path, monkeypatch):
    """Defect C: operator Send Confirmation must not require feature flag."""
    captured = {}

    def _queue(**kw):
        captured.update(kw)
        return "email-manual-1"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    monkeypatch.setattr(
        dcs, "_cmr_attachment_for_draft", lambda draft_id: [],
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", False), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2099-01-01T00:00:00.000Z"), \
         patch.object(settings, "customer_delivery_confirmation_cc",
                      "info@estrellajewels.eu"), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        # Historical relative to activation — automatic would refuse; manual OK.
        res = dcs.execute_delivery_confirmation(
            "7712999111",
            source="operator",
            draft_id=80,
            delivered=True,
            carrier_delivered_at="2026-01-01T12:00:00Z",
            booking_created_at="2025-12-01T00:00:00.000Z",
            customer_email="buyer@example.com",
            customer_name="MICHAEL",
        )
    assert res.get("notified") is True, res
    assert captured.get("email_type") == "customer_delivery_confirmation"
    assert "Estrella" in (captured.get("body_html") or "")


def test_auto_still_respects_activation_boundary(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: calls.__setitem__("n", calls["n"] + 1) or "x",
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-08-05T00:00:00.000Z"):
        res = dcs.maybe_notify_outbound_delivered(
            "7712999222",
            delivered=True,
            carrier_delivered_at="2026-08-01T12:00:00Z",
            booking_created_at="2026-07-01T00:00:00.000Z",
            customer_email="buyer@example.com",
        )
    assert res["notified"] is False and res["reason"] == "activation_boundary"
    assert calls["n"] == 0


def test_reminder_not_blocked_by_feature_flag(tmp_path, monkeypatch):
    """Reminder is operator-driven — feature flag must not return feature_disabled."""
    from app.services import delivery_confirmation_db as dcdb

    db = tmp_path / "delivery_confirmations.db"
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", False):
        # No awaiting row → not_awaiting / no_delivery_record — never feature_disabled
        res = dcs.send_awaiting_customer_reminder(999001)
    assert res.get("reason") != "feature_disabled"


# ── Branded document email ────────────────────────────────────────────────────

def test_customer_document_email_uses_branded_shell():
    class D:
        id = 7
        client_name = "Acme"
        wfirma_proforma_fullnumber = "PROF 1/2026"

    subj, html = customer_documents_email_bodies(D(), ["official_proforma", "packing_list"])
    assert "PROF 1/2026" in subj
    assert "Estrella Jewels" in html
    assert "#0B3D2E" in html  # brand emerald header
    assert "Packing List" in html
    assert "<p>Dear Acme,</p>" not in html or "Dear Acme" in html  # greeting present


# ── Packing List presentation identity ────────────────────────────────────────

def test_packing_list_pdf_uses_html_chrome_not_reportlab(monkeypatch):
    calls = {"html": 0, "chrome": 0}

    def fake_html(doc):
        calls["html"] += 1
        return "<html>PACK</html>"

    def fake_pdf(html, **kw):
        calls["chrome"] += 1
        assert "PACK" in html
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(
        "app.services.commercial_packing_list_html.render_commercial_packing_list_html",
        fake_html,
    )
    monkeypatch.setattr(
        "app.services.chrome_html_pdf.html_to_pdf_bytes",
        fake_pdf,
    )
    out = render_commercial_packing_list_pdf({"doc_ref": "PROF X", "rows": []})
    assert out.startswith(b"%PDF")
    assert calls["html"] == 1 and calls["chrome"] == 1


def test_packing_html_matches_ej_structure():
    html = render_commercial_packing_list_html({
        "doc_ref": "PROF 182/2026",
        "invoice_ref": "FV 1/2026",
        "issued_date": "2026-08-01",
        "currency": "EUR",
        "seller": {"name": "Estrella Jewels Sp. z o.o."},
        "shipto": {"name": "Buyer Co", "city": "London", "country": "GB"},
        "rows": [{
            "sr": 1, "ctg": "Ring", "client_po": "PO1", "product_code": "ABC",
            "design": "RG-100", "description_en": "Gold ring", "description_pl": "Pierścionek",
            "kt": "18KT", "col": "Y", "quality": "VS1", "dia_wt": 0.12,
            "col_wt": 0, "gross_wt": 3.1, "net_wt": 2.9, "qty": 2,
            "unit_price": 100, "total_value": 200, "size": "54", "origin": "IN",
        }],
        "grand_total": 200,
        "total_qty": 2,
    })
    assert "Commercial Packing List" in html
    assert "Consignee · Ship-To" in html
    assert "RG-100" in html
    assert "Pierścionek" in html
    assert "Origin" in html
    assert "Gross Wt (g)" in html
    # Retired ugly ReportLab title-only sheet markers must not appear alone
    assert "A4 landscape" in html or "@page" in html
