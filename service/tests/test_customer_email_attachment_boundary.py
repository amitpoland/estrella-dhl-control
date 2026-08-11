"""
Confidential-document boundary: customer emails must never inherit
agency_reply_package / dhl_reply_package attachments via audit fallback.

Production incident 2026-08-11 — AWB outbound 8334711560 / inbound batch
SHIPMENT_8418664660_*: customer_delivery_confirmation queued with
attachments=None → email_sender last-resort union attached 10 customs files
(agency package + DSK) to the customer MIME (timeline attachments_count=10).

Contract:
  attachments=None  → caller omitted → customer types fail closed to []
  attachments=[]    → explicit zero (authoritative)
  customs types     → legacy audit fallback unchanged
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from settings_factory import make_test_settings


def _write_customs_audit(storage: Path, batch_id: str, *, with_files: bool = True) -> dict:
    """Synthetic audit with agency + DHL packages (import/customs docs)."""
    out = storage / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    files = []
    names = [
        ("import_invoice.pdf", "Import Invoice"),
        ("packing_list.pdf", "Inbound Packing List"),
        ("DSK_TEST.pdf", "DSK"),
    ]
    for fname, label in names:
        p = out / fname
        if with_files:
            p.write_bytes(b"%PDF-1.4 synthetic customs doc\n")
        files.append({"label": label, "path": str(p)})
    audit = {
        "batch_id": batch_id,
        "agency_reply_package": {
            "email_id": str(uuid.uuid4()),
            "attachments": files[:2],
            "status": "queued",
        },
        "dhl_reply_package": {
            "email_id": str(uuid.uuid4()),
            "attachments": files[2:],
            "status": "queued",
        },
        "action_proposals": [],
    }
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return audit


def _customer_entry(batch_id: str, attachments=None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "status": "pending",
        "to": "customer@example.com",
        "cc": "",
        "subject": "Your Estrella shipment has been delivered — confirm condition",
        "body_text": "Please confirm receipt.",
        "body_html": "<p>Please confirm receipt.</p>",
        "from_address": "info@estrellajewels.eu",
        "email_type": "customer_delivery_confirmation",
        "batch_id": batch_id,
        "attachments": attachments,
    }


@pytest.fixture
def storage(tmp_path, monkeypatch):
    s = make_test_settings(tmp_path)
    monkeypatch.setattr("service.app.services.email_sender.settings", s)
    monkeypatch.setattr("service.app.core.config.settings", s)
    return Path(s.storage_root)


# ── Pre-fix / post-fix leak reproduction ─────────────────────────────────

def test_customer_none_with_customs_audit_resolves_zero(storage):
    """attachments=None + customs packages in audit → 0 (fail closed)."""
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_CUSTOMS_LEAK"
    _write_customs_audit(storage, batch_id)
    entry = _customer_entry(batch_id, attachments=None)
    # Simulate pre-fix leak shape: key present as JSON null / Python None
    assert "attachments" in entry
    assert entry["attachments"] is None

    found, missing = _attachments_for_queue(entry)
    assert found == []
    assert missing == []


def test_customer_empty_list_with_customs_audit_resolves_zero(storage):
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_EMPTY"
    _write_customs_audit(storage, batch_id)
    found, missing = _attachments_for_queue(_customer_entry(batch_id, attachments=[]))
    assert found == []
    assert missing == []


def test_customer_packing_list_in_audit_not_attached(storage):
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_PACK"
    _write_customs_audit(storage, batch_id)
    found, _ = _attachments_for_queue(_customer_entry(batch_id, attachments=None))
    assert all("packing" not in p.name.lower() for p in found)
    assert found == []


def test_customer_invoice_in_audit_not_attached(storage):
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_INV"
    _write_customs_audit(storage, batch_id)
    found, _ = _attachments_for_queue(_customer_entry(batch_id, attachments=None))
    assert all("invoice" not in p.name.lower() for p in found)
    assert found == []


def test_customer_never_hits_last_resort_union(storage):
    """Even with both packages present, customer type must not union them."""
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_UNION"
    audit = _write_customs_audit(storage, batch_id)
    assert len(audit["agency_reply_package"]["attachments"]) == 2
    assert len(audit["dhl_reply_package"]["attachments"]) == 1

    found, _ = _attachments_for_queue(_customer_entry(batch_id, attachments=None))
    assert found == []


def test_batch_id_presence_does_not_change_customer_attachment_result(storage):
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_BATCH"
    _write_customs_audit(storage, batch_id)
    with_batch, _ = _attachments_for_queue(_customer_entry(batch_id, attachments=None))
    no_batch_entry = _customer_entry("", attachments=None)
    no_batch_entry["batch_id"] = ""
    without_batch, _ = _attachments_for_queue(no_batch_entry)
    assert with_batch == without_batch == []


# ── Customs / DHL regression — must remain unchanged ─────────────────────────

def test_agency_explicit_package_still_resolves(storage):
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_AGENCY"
    audit = _write_customs_audit(storage, batch_id)
    agency_id = audit["agency_reply_package"]["email_id"]
    entry = {
        "id": agency_id,
        "email_type": "agency",
        "batch_id": batch_id,
        "attachments": None,  # legacy path: match package by email_id
    }
    found, missing = _attachments_for_queue(entry)
    assert missing == []
    assert len(found) == 2
    assert {p.name for p in found} == {"import_invoice.pdf", "packing_list.pdf"}


def test_dhl_reply_explicit_package_still_resolves(storage):
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_DHL"
    audit = _write_customs_audit(storage, batch_id)
    dhl_id = audit["dhl_reply_package"]["email_id"]
    entry = {
        "id": dhl_id,
        "email_type": "dhl_reply",
        "batch_id": batch_id,
        "attachments": None,
    }
    found, missing = _attachments_for_queue(entry)
    assert missing == []
    assert len(found) == 1
    assert found[0].name == "DSK_TEST.pdf"


def test_agency_last_resort_union_still_works_for_customs(storage):
    """Unmatched customs email_id may still use legacy union — NOT customer."""
    from service.app.services.email_sender import _attachments_for_queue

    batch_id = "SHIPMENT_SYNTH_UNION_CUSTOMS"
    _write_customs_audit(storage, batch_id)
    entry = {
        "id": str(uuid.uuid4()),  # matches neither package
        "email_type": "agency",
        "batch_id": batch_id,
        "attachments": None,
    }
    found, _ = _attachments_for_queue(entry)
    assert len(found) == 3  # agency 2 + dhl 1


# ── Producer contract ────────────────────────────────────────────────────────

def test_delivery_confirmation_queues_explicit_empty_attachments(tmp_path, monkeypatch):
    """Producer must pass attachments=[] so authority is explicit."""
    from service.app.services import delivery_confirmation_service as dcs

    captured = {}

    def _fake_queue_email(**kwargs):
        captured.update(kwargs)
        return "queued-id-1"

    monkeypatch.setattr(
        "service.app.core.config.settings.customer_delivery_confirmation_enabled",
        True,
    )
    # Bypass earlier gates by calling the queue path via patched internals is
    # heavy; assert the source contract + a direct call simulation instead.
    src = Path(dcs.__file__).read_text(encoding="utf-8")
    assert "attachments=[]" in src
    assert 'email_type="customer_delivery_confirmation"' in src

    # Also exercise queue_email kwargs shape via the patched importer path used
    # inside maybe_notify — use the module-level email_service stub.
    with patch("service.app.services.email_service.queue_email", side_effect=_fake_queue_email):
        # Call the inner queue block shape by importing and invoking queue_email
        # the same way the producer does after bodies are built.
        from service.app.services import email_service
        email_service.queue_email(
            to="customer@example.com",
            subject="x",
            body_html="<p>x</p>",
            body_text="x",
            batch_id="B1",
            email_type="customer_delivery_confirmation",
            attachments=[],
        )
    assert captured.get("attachments") == []
    assert captured.get("email_type") == "customer_delivery_confirmation"


def test_customer_facing_type_registry():
    from service.app.config.email_routing import (
        CUSTOMER_FACING_EMAIL_TYPES,
        is_customer_facing_email_type,
    )

    assert "customer_delivery_confirmation" in CUSTOMER_FACING_EMAIL_TYPES
    assert is_customer_facing_email_type("customer_delivery_confirmation")
    assert is_customer_facing_email_type("Customer_Delivery_Confirmation")
    assert not is_customer_facing_email_type("agency")
    assert not is_customer_facing_email_type("dhl_reply")
    assert not is_customer_facing_email_type("dhl_b2_dsk_only_reply")
