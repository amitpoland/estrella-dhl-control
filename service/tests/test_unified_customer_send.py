"""Unified customer Send — eligibility, options, boundary, reminder gates."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.config.email_routing import (
    CUSTOMER_FACING_EMAIL_TYPES,
    is_customer_facing_email_type,
)
from app.services import customer_send as cs
from app.services.shipment_document_manifest import GENERATED, PENDING, MISSING


def _entry(doc_type, status=GENERATED, download=True, url="/x.pdf", reason=None):
    return {
        "document_type": doc_type,
        "status": status,
        "download_available": download,
        "download_url": url if download else None,
        "reason": reason,
    }


def test_customer_sendable_whitelist():
    assert cs.is_customer_sendable_document(_entry("official_proforma"))
    assert cs.is_customer_sendable_document(_entry("invoice"))
    assert cs.is_customer_sendable_document(_entry("packing_list"))


@pytest.mark.parametrize(
    "doc_type",
    [
        "cmr",
        "dhl_label",
        "dhl_waybill",
        "dhl_receipt",
        "dhl_epod",
        "draft_proforma",
        "customs_sad",
        "agency_package",
        "totally_unknown",
        "",
    ],
)
def test_customer_sendable_denies_internal(doc_type):
    assert not cs.is_customer_sendable_document(_entry(doc_type))


def test_customer_sendable_requires_generated_and_download():
    assert not cs.is_customer_sendable_document(_entry("invoice", status=PENDING))
    assert not cs.is_customer_sendable_document(
        _entry("packing_list", status=MISSING, download=False, url=None)
    )
    assert not cs.is_customer_sendable_document(None)
    assert not cs.is_customer_sendable_document({})


def test_normalize_dedupes_and_orders():
    assert cs.normalize_document_types(
        ["packing_list", "official_proforma", "packing_list", "invoice"]
    ) == ["official_proforma", "invoice", "packing_list"]


def test_assert_types_rejects_unknown_and_unavailable():
    manifest = {
        "groups": {
            "commercial": [
                _entry("official_proforma"),
                _entry("invoice", status=PENDING, download=False, url=None, reason="no inv"),
                _entry("packing_list"),
            ],
            "transport": [_entry("cmr")],
            "carrier": [_entry("dhl_label")],
        }
    }
    assert cs.assert_types_customer_sendable(
        manifest, ["packing_list", "official_proforma"]
    ) == ["official_proforma", "packing_list"]
    with pytest.raises(ValueError, match="not customer-sendable"):
        cs.assert_types_customer_sendable(manifest, ["cmr"])
    with pytest.raises(ValueError, match="not available"):
        cs.assert_types_customer_sendable(manifest, ["invoice"])
    with pytest.raises(ValueError, match="No document"):
        cs.assert_types_customer_sendable(manifest, [])


def test_proforma_send_in_customer_facing_boundary():
    assert "proforma_send" in CUSTOMER_FACING_EMAIL_TYPES
    assert "customer_delivery_reminder" in CUSTOMER_FACING_EMAIL_TYPES
    assert is_customer_facing_email_type("proforma_send")
    assert is_customer_facing_email_type("customer_delivery_reminder")


def test_proforma_send_attachments_none_fail_closed(tmp_path, monkeypatch):
    """proforma_send + attachments=None must not inherit customs audit union."""
    from settings_factory import make_test_settings
    from service.app.services import email_sender

    s = make_test_settings(tmp_path)
    monkeypatch.setattr("service.app.services.email_sender.settings", s)
    monkeypatch.setattr("service.app.core.config.settings", s)

    batch_id = "SHIPMENT_TEST_PROFORMA_SEND"
    out = tmp_path / "outputs" / batch_id
    out.mkdir(parents=True)
    customs = out / "DSK.pdf"
    customs.write_bytes(b"%PDF customs")
    import json, uuid
    (out / "audit.json").write_text(json.dumps({
        "agency_reply_package": {
            "email_id": str(uuid.uuid4()),
            "attachments": [{"label": "DSK", "path": str(customs)}],
        },
        "dhl_reply_package": {"attachments": []},
        "action_proposals": [],
    }), encoding="utf-8")

    entry = {
        "id": str(uuid.uuid4()),
        "email_type": "proforma_send",
        "batch_id": batch_id,
        "attachments": None,
    }
    found, missing = email_sender._attachments_for_queue(entry)
    assert found == []
    assert missing == []


def test_ui_has_unified_send_surface():
    src = Path("app/static/v2/proforma-detail.jsx").read_text(encoding="utf-8")
    assert "send-documents-submit" in src
    assert "send-confirmation-submit" in src
    assert "send-reminder-submit" in src
    assert "getProformaSendOptions" in src
    assert "r.data" in src or "payload = r.data" in src
    assert "Objectassign" not in src
    assert "Object.assign" in src
    assert 'data-testid="tb-generate"' not in src
    assert "➤ Send Proforma Email" not in src
    api = Path("app/static/v2/pz-api.js").read_text(encoding="utf-8")
    assert "getProformaSendOptions" in api
    assert "document_types" in api


def test_customer_documents_email_bodies_order():
    class D:
        id = 7
        client_name = "Acme"
        wfirma_proforma_fullnumber = "PROF 1/2026"

    subj, html = cs.customer_documents_email_bodies(
        D(), ["official_proforma", "packing_list"]
    )
    assert "Proforma" in subj or "Documents" in subj
    assert "Proforma" in html and "Packing List" in html
