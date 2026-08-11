"""
Layer 2: customer delivery communication identity.

Canonical key = outbound AWB + client_ref.
Import/sales parent batch is origin_batch_id provenance only — never
email_queue.batch_id / customs audit namespace.

Does NOT change #1192 attachment fail-closed policy.
Does NOT mutate carrier booking parent batch_id.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import delivery_confirmation_db as dcdb
from app.services import delivery_confirmation_service as dcs
from app.services.email_sender import _attachments_for_queue
from settings_factory import make_test_settings


PARENT = "SHIPMENT_8418664660_2026-08_6cbbed33"
AWB_A = "8334711560"
AWB_B = "8334711561"
CLIENT = "Clear-Diamonds"


def _enable(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "customer_delivery_confirmation_enabled", True)
    monkeypatch.setattr(
        settings, "customer_delivery_confirmation_activated_at", "2026-01-01T00:00:00.000Z"
    )
    monkeypatch.setattr(settings, "customer_delivery_confirmation_cc", "info@example.test")
    monkeypatch.setattr(settings, "public_base_url", "https://pz.example.test")


def test_outbound_with_import_parent_does_not_set_email_batch_authority(
    tmp_path, monkeypatch,
):
    captured = {}

    def _queue(**kw):
        captured.update(kw)
        return "eid-1"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    _enable(monkeypatch, tmp_path)

    res = dcs.maybe_notify_outbound_delivered(
        AWB_A,
        draft_id=76,
        origin_batch_id=PARENT,
        client_name=CLIENT,
        delivered=True,
        carrier_delivered_at="2026-08-11T10:00:00Z",
        booking_created_at="2026-08-03T11:00:00.000Z",
        customer_email="buyer@example.com",
        customer_name=CLIENT,
    )
    assert res["notified"] is True
    assert res["origin_batch_id"] == PARENT
    assert captured["batch_id"] == ""
    assert captured["email_type"] == "customer_delivery_confirmation"
    assert captured["attachments"] == []

    db = tmp_path / "delivery_confirmations.db"
    notif = dcdb.get_notification_by_awb(db, AWB_A)
    assert notif["awb"] == AWB_A
    assert notif["client_name"] == CLIENT
    assert not (notif.get("batch_id") or "").strip()
    assert notif.get("origin_batch_id") == PARENT

    receipt = dcdb.get_receipt_for_awb(db, AWB_A)
    assert receipt["awb"] == AWB_A
    assert receipt["client_name"] == CLIENT
    assert not (receipt.get("batch_id") or "").strip()
    assert receipt.get("origin_batch_id") == PARENT


def test_two_outbound_awbs_same_parent_remain_distinct(tmp_path, monkeypatch):
    ids = []

    def _queue(**kw):
        eid = f"eid-{len(ids)+1}"
        ids.append(eid)
        return eid

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    _enable(monkeypatch, tmp_path)

    r1 = dcs.maybe_notify_outbound_delivered(
        AWB_A, origin_batch_id=PARENT, client_name=CLIENT,
        delivered=True, carrier_delivered_at="2026-08-11T10:00:00Z",
        booking_created_at="2026-08-03T11:00:00.000Z",
        customer_email="buyer@example.com", customer_name=CLIENT,
    )
    r2 = dcs.maybe_notify_outbound_delivered(
        AWB_B, origin_batch_id=PARENT, client_name=CLIENT,
        delivered=True, carrier_delivered_at="2026-08-11T11:00:00Z",
        booking_created_at="2026-08-03T12:00:00.000Z",
        customer_email="buyer@example.com", customer_name=CLIENT,
    )
    assert r1["notified"] and r2["notified"]
    assert r1["email_id"] != r2["email_id"]

    db = tmp_path / "delivery_confirmations.db"
    n1 = dcdb.get_notification_by_awb(db, AWB_A)
    n2 = dcdb.get_notification_by_awb(db, AWB_B)
    assert n1["id"] != n2["id"]
    assert n1["origin_batch_id"] == n2["origin_batch_id"] == PARENT
    assert dcdb.get_receipt_for_awb(db, AWB_A)["awb"] == AWB_A
    assert dcdb.get_receipt_for_awb(db, AWB_B)["awb"] == AWB_B


def test_duplicate_notification_still_prevented(tmp_path, monkeypatch):
    calls = {"n": 0}

    def _queue(**kw):
        calls["n"] += 1
        return f"eid-{calls['n']}"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    _enable(monkeypatch, tmp_path)
    kwargs = dict(
        origin_batch_id=PARENT, client_name=CLIENT, delivered=True,
        carrier_delivered_at="2026-08-11T10:00:00Z",
        booking_created_at="2026-08-03T11:00:00.000Z",
        customer_email="buyer@example.com", customer_name=CLIENT,
    )
    assert dcs.maybe_notify_outbound_delivered(AWB_A, **kwargs)["notified"] is True
    again = dcs.maybe_notify_outbound_delivered(AWB_A, **kwargs)
    assert again["notified"] is False
    assert again["reason"] == "already_notified"
    assert calls["n"] == 1


def test_receipt_token_bound_to_outbound_awb_customer(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_service.queue_email", lambda **kw: "eid")
    _enable(monkeypatch, tmp_path)
    dcs.maybe_notify_outbound_delivered(
        AWB_A, origin_batch_id=PARENT, client_name=CLIENT,
        delivered=True, carrier_delivered_at="2026-08-11T10:00:00Z",
        booking_created_at="2026-08-03T11:00:00.000Z",
        customer_email="buyer@example.com", customer_name=CLIENT,
    )
    db = tmp_path / "delivery_confirmations.db"
    # Token plaintext is not stored — verify row identity fields only.
    receipt = dcdb.get_receipt_for_awb(db, AWB_A)
    assert receipt["awb"] == AWB_A
    assert receipt["customer_name"] == CLIENT or receipt["client_name"] == CLIENT
    # Public metadata path uses token hash lookup — simulate stored hash row.
    meta = dcdb.get_receipt_by_token_hash(db, receipt["token_hash"])
    assert meta["awb"] == AWB_A
    assert not (meta.get("batch_id") or "").strip()


def test_customs_audit_still_zero_attachments_for_customer(tmp_path, monkeypatch):
    s = make_test_settings(tmp_path)
    monkeypatch.setattr("app.services.email_sender.settings", s)
    monkeypatch.setattr("app.core.config.settings", s)

    out = Path(s.storage_root) / "outputs" / PARENT
    out.mkdir(parents=True)
    files = []
    for name in [f"Invoice-{i}.pdf" for i in range(9)] + ["DSK.pdf"]:
        p = out / name
        p.write_bytes(b"%PDF-1.4 x")
        files.append({"label": name, "path": str(p)})
    audit = {
        "agency_reply_package": {
            "email_id": str(uuid.uuid4()), "attachments": files[:9],
        },
        "dhl_reply_package": {
            "email_id": str(uuid.uuid4()), "attachments": files[9:],
        },
        "action_proposals": [],
    }
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    # Even if a buggy caller still put the import batch on the queue entry,
    # customer type + attachments=[] / None must stay at 0 (#1192 + empty batch).
    for atts in ([], None):
        found, _ = _attachments_for_queue({
            "id": str(uuid.uuid4()),
            "batch_id": PARENT,
            "email_type": "customer_delivery_confirmation",
            "attachments": atts,
        })
        assert found == []

    # Empty batch_id (correct post-fix queue shape) also yields 0.
    found, _ = _attachments_for_queue({
        "id": str(uuid.uuid4()),
        "batch_id": "",
        "email_type": "customer_delivery_confirmation",
        "attachments": None,
    })
    assert found == []


def test_legacy_rows_with_import_batch_id_remain_readable(tmp_path):
    """Old Clear-Diamonds-shaped rows stay readable; do not rewrite history."""
    db = tmp_path / "delivery_confirmations.db"
    dcdb.init_db(db)
    # Simulate pre-fix insert shape (batch_id = import parent, no origin).
    with dcdb._connect(db) as conn:
        conn.execute(
            """
            INSERT INTO delivery_notifications
                (awb, draft_id, batch_id, client_name, email_to,
                 activation_cutoff_ok, status)
            VALUES (?, ?, ?, ?, ?, 1, 'queued')
            """,
            (AWB_A, 76, PARENT, CLIENT, "buyer@example.com"),
        )
        conn.execute(
            """
            INSERT INTO delivery_receipts
                (token_hash, awb, draft_id, batch_id, client_name, customer_name,
                 expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("hash-legacy", AWB_A, 76, PARENT, CLIENT, CLIENT,
             "2026-09-10T00:00:00.000Z"),
        )
    # Migration adds origin_batch_id column without destroying rows.
    dcdb.init_db(db)
    notif = dcdb.get_notification_by_awb(db, AWB_A)
    assert notif["batch_id"] == PARENT  # historical trail preserved
    assert notif["awb"] == AWB_A
    assert "origin_batch_id" in notif  # column present
    receipt = dcdb.get_receipt_by_token_hash(db, "hash-legacy")
    assert receipt["batch_id"] == PARENT
    assert receipt["awb"] == AWB_A


def test_legacy_batch_id_kwarg_treated_as_origin_only(tmp_path, monkeypatch):
    """Callers still passing batch_id= get provenance-only behaviour."""
    captured = {}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: captured.update(kw) or "eid",
    )
    _enable(monkeypatch, tmp_path)
    res = dcs.maybe_notify_outbound_delivered(
        AWB_A, batch_id=PARENT, client_name=CLIENT,
        delivered=True, carrier_delivered_at="2026-08-11T10:00:00Z",
        booking_created_at="2026-08-03T11:00:00.000Z",
        customer_email="buyer@example.com", customer_name=CLIENT,
    )
    assert res["notified"]
    assert res["origin_batch_id"] == PARENT
    assert captured["batch_id"] == ""
    notif = dcdb.get_notification_by_awb(
        tmp_path / "delivery_confirmations.db", AWB_A,
    )
    assert not (notif.get("batch_id") or "").strip()
    assert notif["origin_batch_id"] == PARENT


def test_hook_passes_origin_not_operative_batch(tmp_path, monkeypatch):
    from app.services import outbound_delivery_hook as hook
    import app.services.carrier.persistence.shipment_db as shipment_db_mod

    monkeypatch.setattr(settings, "customer_delivery_confirmation_enabled", True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    carrier_dir = tmp_path / "carrier"
    carrier_dir.mkdir()
    (carrier_dir / "carrier_shipments.db").write_bytes(b"")
    monkeypatch.setattr(settings, "carrier_storage_root", str(carrier_dir))

    captured = {}

    def _notify(awb, **kw):
        captured["awb"] = awb
        captured.update(kw)
        return {"notified": False, "reason": "test_stub"}

    monkeypatch.setattr(
        shipment_db_mod,
        "get_shipment_by_tracking_ref",
        lambda db, awb: {
            "tracking_ref": awb,
            "batch_id": PARENT,
            "client_ref": CLIENT,
            "created_at": "2026-08-03T11:04:39.383Z",
        },
    )
    monkeypatch.setattr(
        "app.services.delivery_confirmation_service.maybe_notify_outbound_delivered",
        _notify,
    )
    monkeypatch.setattr(
        "app.services.carrier.epod_service.ensure_epod_persisted",
        lambda *a, **k: None,
    )

    result = hook.on_outbound_tracking_update(
        AWB_A, "delivered",
        events=[{"description": "Delivered", "timestamp": "2026-08-11T10:25:55"}],
    )
    assert result.get("reason") == "test_stub"
    assert captured["awb"] == AWB_A
    assert captured.get("origin_batch_id") == PARENT
    assert not (captured.get("batch_id") or "")
    assert captured.get("client_name") == CLIENT
