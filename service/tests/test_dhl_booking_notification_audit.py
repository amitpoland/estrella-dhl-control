"""Booking-time MyDHL shipmentNotification audit + Estrella Delivered pins.

No live customer email/SMS. Shadow coordinator only. Tracking logic untouched.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import delivery_confirmation_service as dcs
from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import ShipmentRequest, ShipmentState
from app.services.carrier.notification_audit import (
    RECIPIENT_AUTHORITY,
    PROVIDER,
    build_notification_audit,
    build_shipment_notifications,
    mask_email,
)
from app.services.carrier.persistence import shipment_db as sdb
from app.services.carrier.adapters.live import _build_shipment_body


def _coord(tmp_path: Path) -> CarrierCoordinator:
    return CarrierCoordinator(
        CoordinatorConfig(
            carrier_config=CarrierConfig(status="shadow"),
            shipment_db_path=tmp_path / "shipments.db",
            shadow_log_db_path=tmp_path / "shadow.db",
        )
    )


def _req(**recipient) -> ShipmentRequest:
    return ShipmentRequest(
        batch_id="BATCH-NOTIFY-AUDIT",
        shipper_account="427294774",
        recipient_address={
            "name": "Buyer",
            "country": "DE",
            "city": "Berlin",
            "street": "Unter den Linden 1",
            "phone": "+491701234567",
            **recipient,
        },
        declared_value=100.0,
        currency="EUR",
        weight_kg=0.5,
        dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 5},
    )


# ── builder: email / SMS request shape ───────────────────────────────────────


def test_email_requested_when_valid_email():
    notes = build_shipment_notifications({"email": "buyer@example.com", "phone": "123"})
    assert any(n["typeCode"] == "email" and n["receiverId"] == "buyer@example.com" for n in notes)
    assert not any(n["typeCode"] == "sms" for n in notes)


def test_sms_e164_requested():
    notes = build_shipment_notifications({"phone": "+48123456789"})
    assert any(n["typeCode"] == "sms" and n["receiverId"] == "+48123456789" for n in notes)


def test_sms_invalid_skipped():
    notes = build_shipment_notifications({"phone": "48123456789"})  # no +
    assert not any(n["typeCode"] == "sms" for n in notes)
    notes2 = build_shipment_notifications({"phone": "+48abc"})
    assert not any(n["typeCode"] == "sms" for n in notes2)


def test_audit_masks_never_store_raw_secrets():
    audit = build_notification_audit(
        {"email": "buyer@example.com", "phone": "+48123456789"},
        requested_at="2026-08-10T12:00:00.000Z",
    )
    blob = str(audit)
    assert "buyer@example.com" not in blob
    assert "+48123456789" not in blob
    assert audit["dhl_notify_email_requested"] == 1
    assert audit["dhl_notify_sms_requested"] == 1
    assert audit["dhl_notify_email_masked"] == mask_email("buyer@example.com")
    assert audit["dhl_notify_recipient_source"] == RECIPIENT_AUTHORITY
    assert audit["dhl_notify_provider"] == PROVIDER
    assert audit["dhl_notify_requested_at"] == "2026-08-10T12:00:00.000Z"


# ── persistence + idempotency ────────────────────────────────────────────────


def test_booking_persists_notification_audit(tmp_path):
    coord = _coord(tmp_path)
    r = coord.create_shipment(
        _req(email="ops@customer.eu", phone="+491701234567")
    )
    assert r.state == ShipmentState.COMPLETE
    row = sdb.get_shipment(tmp_path / "shipments.db", r.idempotency_key)
    assert row is not None
    assert int(row["dhl_notify_email_requested"]) == 1
    assert int(row["dhl_notify_sms_requested"]) == 1
    assert row["dhl_notify_email_masked"]
    assert "ops@customer.eu" not in (row["dhl_notify_email_masked"] or "")
    assert "+491701234567" not in (row["dhl_notify_sms_masked"] or "")
    assert row["dhl_notify_recipient_source"] == RECIPIENT_AUTHORITY
    assert row["dhl_notify_provider"] == PROVIDER
    assert row["dhl_notify_requested_at"]


def test_booking_audit_idempotent_on_replay(tmp_path):
    coord = _coord(tmp_path)
    req = _req(email="ops@customer.eu", phone="+491701234567")
    r1 = coord.create_shipment(req)
    row1 = sdb.get_shipment(tmp_path / "shipments.db", r1.idempotency_key)
    stamp = row1["dhl_notify_requested_at"]
    r2 = coord.create_shipment(req)
    assert r2.replayed is True
    row2 = sdb.get_shipment(tmp_path / "shipments.db", r1.idempotency_key)
    assert row2["dhl_notify_requested_at"] == stamp
    assert int(row2["dhl_notify_email_requested"]) == 1


def test_persist_notification_audit_first_write_wins(tmp_path):
    db = tmp_path / "shipments.db"
    sdb.init_db(db)
    from app.services.carrier.models.shipment import ShipmentMode, ShipmentResult

    key = "idem-notify-1"
    sdb.insert_shipment(
        db,
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
            simulated=True,
        ),
        "BATCH-X",
    )
    sdb.update_state(db, key, ShipmentState.COMPLETE, tracking_ref="AWB1")
    first = build_notification_audit(
        {"email": "a@example.com"},
        requested_at="2026-08-10T10:00:00.000Z",
    )
    second = build_notification_audit(
        {"email": "b@example.com"},
        requested_at="2026-08-10T11:00:00.000Z",
    )
    sdb.persist_notification_audit(db, key, first)
    sdb.persist_notification_audit(db, key, second)
    row = sdb.get_shipment(db, key)
    assert row["dhl_notify_requested_at"] == "2026-08-10T10:00:00.000Z"
    assert "a@" in (row["dhl_notify_email_masked"] or "") or "***@" in (
        row["dhl_notify_email_masked"] or ""
    )


# ── live body still carries shipmentNotification (no HTTP) ───────────────────


def test_live_body_includes_email_and_e164_sms():
    class _S:
        dhl_express_shipper_postal_code = "00-001"
        dhl_express_shipper_city = "Warsaw"
        dhl_express_shipper_country_code = "PL"
        dhl_express_shipper_address1 = "Street 1"
        dhl_express_shipper_name = "Estrella"
        dhl_express_shipper_phone = "+48111"
        dhl_express_account_number = "123"

    req = _req(email="buyer@example.com", phone="+48123456789", country_code="DE")
    req.incoterm = "DAP"
    body = _build_shipment_body(req, _S())
    notes = body.get("shipmentNotification") or []
    assert any(n["typeCode"] == "email" for n in notes)
    assert any(n["typeCode"] == "sms" for n in notes)


# ── Estrella Delivered path unchanged ────────────────────────────────────────


def test_no_estrella_email_before_delivered(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "email-id"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(
             settings,
             "customer_delivery_confirmation_activated_at",
             "2026-01-01T00:00:00.000Z",
         ):
        r = dcs.maybe_notify_outbound_delivered(
            "AWB-NOT-YET",
            draft_id=1,
            batch_id="B1",
            client_name="ACME",
            delivered=False,
            carrier_delivered_at=None,
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com",
            customer_name="ACME",
        )
    assert r["notified"] is False
    assert r["reason"] == "not_delivered"
    assert calls["n"] == 0


def test_estrella_cc_is_info_estrellajewels():
    from app.config.email_routing import resolve_customer_delivery_confirmation_cc

    assert (settings.customer_delivery_confirmation_cc or "").strip().lower() == (
        "info@estrellajewels.eu"
    )
    cc = resolve_customer_delivery_confirmation_cc("buyer@example.com")
    assert "info@estrellajewels.eu" in cc.lower()


def test_estrella_activation_boundary_unchanged(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "email-id"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(
             settings,
             "customer_delivery_confirmation_activated_at",
             "2026-08-08T16:50:08.000Z",
         ):
        r = dcs.maybe_notify_outbound_delivered(
            "AWB-PRE-ACT",
            draft_id=1,
            batch_id="B1",
            client_name="ACME",
            delivered=True,
            carrier_delivered_at="2026-08-05T12:00:00Z",
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com",
            customer_name="ACME",
        )
    assert r["notified"] is False
    assert r["reason"] == "activation_boundary"
    assert calls["n"] == 0


def test_estrella_receipt_exactly_once(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "email-id"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(
             settings,
             "customer_delivery_confirmation_activated_at",
             "2026-01-01T00:00:00.000Z",
         ), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        r1 = dcs.maybe_notify_outbound_delivered(
            "AWB-ONCE",
            draft_id=1,
            batch_id="B1",
            client_name="ACME",
            delivered=True,
            carrier_delivered_at="2026-08-09T12:00:00Z",
            booking_created_at="2026-08-09T00:00:00.000Z",
            customer_email="buyer@example.com",
            customer_name="ACME",
        )
        r2 = dcs.maybe_notify_outbound_delivered(
            "AWB-ONCE",
            draft_id=1,
            batch_id="B1",
            client_name="ACME",
            delivered=True,
            carrier_delivered_at="2026-08-09T12:00:00Z",
            booking_created_at="2026-08-09T00:00:00.000Z",
            customer_email="buyer@example.com",
            customer_name="ACME",
        )
    assert r1["notified"] is True
    assert r2["notified"] is False and r2["reason"] == "already_notified"
    assert calls["n"] == 1


def test_outbound_hook_only_on_carrier_delivered():
    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "outbound_delivery_hook.py"
    ).read_text(encoding="utf-8")
    assert "maybe_notify_outbound_delivered" in src
    assert "delivered" in src
    # Must not invent Estrella mail from booking alone
    assert "shipmentNotification" not in src
