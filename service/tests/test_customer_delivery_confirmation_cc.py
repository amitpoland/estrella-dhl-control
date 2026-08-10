"""Customer delivery-confirmation: Estrella internal CC authority."""
from __future__ import annotations

from unittest.mock import patch

from app.config.email_routing import (
    INTERNAL_CC,
    resolve_customer_delivery_confirmation_cc,
    resolve_dhl_cc,
)
from app.core.config import settings
from app.services import delivery_confirmation_db as dcdb
from app.services import delivery_confirmation_service as dcs


AWB = "7712999001"
BATCH = "BATCH-CDC-CC-TEST"


def test_resolve_cc_uses_config_not_dhl_list():
    with patch.object(settings, "customer_delivery_confirmation_cc", "info@estrellajewels.eu"):
        assert resolve_customer_delivery_confirmation_cc("buyer@example.com") == (
            "info@estrellajewels.eu"
        )
    # DHL/customs INTERNAL_CC list is a different authority — still multi-address.
    dhl = resolve_dhl_cc()
    assert "import@estrellajewels.eu" in dhl or dhl == ""
    assert resolve_customer_delivery_confirmation_cc("buyer@example.com") != dhl or (
        "," not in resolve_customer_delivery_confirmation_cc("buyer@example.com")
    )


def test_eligible_event_queues_to_customer_and_cc(tmp_path, monkeypatch):
    captured = {}

    def _queue(**kw):
        captured.update(kw)
        return "email-cc-1"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"), \
         patch.object(settings, "customer_delivery_confirmation_cc",
                      "info@estrellajewels.eu"), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        res = dcs.maybe_notify_outbound_delivered(
            AWB, draft_id=1, batch_id=BATCH, client_name="ACME",
            delivered=True, carrier_delivered_at="2026-08-10T12:00:00Z",
            booking_created_at="2026-08-01T00:00:00.000Z",
            customer_email="buyer@example.com", customer_name="ACME",
        )
    assert res["notified"] is True
    assert captured["to"] == "buyer@example.com"
    assert captured["cc"] == "info@estrellajewels.eu"
    assert captured["email_type"] == "customer_delivery_confirmation"
    assert res["email_to"] == "buyer@example.com"
    assert res["email_cc"] == "info@estrellajewels.eu"

    row = dcdb.get_notification_by_awb(tmp_path / "delivery_confirmations.db", AWB)
    assert row is not None
    assert row["email_to"] == "buyer@example.com"
    assert row["email_cc"] == "info@estrellajewels.eu"


def test_disabled_feature_no_email(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "x"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", False), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"), \
         patch.object(settings, "customer_delivery_confirmation_cc",
                      "info@estrellajewels.eu"):
        res = dcs.maybe_notify_outbound_delivered(
            AWB, delivered=True, carrier_delivered_at="2026-08-10T12:00:00Z",
            customer_email="buyer@example.com",
        )
    assert res["notified"] is False and res["reason"] == "feature_disabled"
    assert calls["n"] == 0


def test_pre_activation_no_email(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "x"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-08-05T00:00:00.000Z"), \
         patch.object(settings, "customer_delivery_confirmation_cc",
                      "info@estrellajewels.eu"):
        res = dcs.maybe_notify_outbound_delivered(
            AWB, delivered=True,
            carrier_delivered_at="2026-08-01T12:00:00Z",
            customer_email="buyer@example.com",
        )
    assert res["notified"] is False and res["reason"] == "activation_boundary"
    assert calls["n"] == 0


def test_missing_customer_email_no_send(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: (calls.__setitem__("n", calls["n"] + 1) or "x"),
    )
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"):
        res = dcs.maybe_notify_outbound_delivered(
            AWB, delivered=True, carrier_delivered_at="2026-08-10T12:00:00Z",
            customer_email="",
        )
    assert res["notified"] is False and res["reason"] == "no_customer_email"
    assert calls["n"] == 0


def test_empty_cc_config_still_sends_to_customer(tmp_path, monkeypatch):
    captured = {}

    def _queue(**kw):
        captured.update(kw)
        return "email-no-cc"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"), \
         patch.object(settings, "customer_delivery_confirmation_cc", ""), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        res = dcs.maybe_notify_outbound_delivered(
            "AWB-NO-CC", delivered=True, carrier_delivered_at="2026-08-10T12:00:00Z",
            customer_email="buyer@example.com", customer_name="ACME",
            batch_id=BATCH,
        )
    assert res["notified"] is True
    assert captured["to"] == "buyer@example.com"
    assert captured.get("cc") == ""
    assert res["email_cc"] == ""


def test_cc_deduped_when_same_as_to():
    with patch.object(
        settings, "customer_delivery_confirmation_cc", "buyer@example.com",
    ):
        assert resolve_customer_delivery_confirmation_cc("buyer@example.com") == ""


def test_retry_does_not_duplicate(tmp_path, monkeypatch):
    calls = {"n": 0, "ccs": []}

    def _queue(**kw):
        calls["n"] += 1
        calls["ccs"].append(kw.get("cc") or "")
        return f"email-{calls['n']}"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    with patch.object(settings, "storage_root", tmp_path), \
         patch.object(settings, "customer_delivery_confirmation_enabled", True), \
         patch.object(settings, "customer_delivery_confirmation_activated_at",
                      "2026-01-01T00:00:00.000Z"), \
         patch.object(settings, "customer_delivery_confirmation_cc",
                      "info@estrellajewels.eu"), \
         patch.object(settings, "public_base_url", "https://pz.example.test"):
        r1 = dcs.maybe_notify_outbound_delivered(
            "AWB-RETRY", delivered=True, carrier_delivered_at="2026-08-10T12:00:00Z",
            customer_email="buyer@example.com", batch_id=BATCH,
        )
        r2 = dcs.maybe_notify_outbound_delivered(
            "AWB-RETRY", delivered=True, carrier_delivered_at="2026-08-10T12:00:00Z",
            customer_email="buyer@example.com", batch_id=BATCH,
        )
    assert r1["notified"] is True
    assert r2["notified"] is False and r2["reason"] == "already_notified"
    assert calls["n"] == 1
    assert calls["ccs"] == ["info@estrellajewels.eu"]


def test_dhl_resolve_unaffected_by_customer_cc_setting():
    """Unrelated DHL/customs CC authority must not pick up the customer CC field."""
    with patch.object(
        settings, "customer_delivery_confirmation_cc", "ops-only@estrellajewels.eu",
    ), patch.object(settings, "dhl_customs_cc", ""):
        dhl = resolve_dhl_cc()
        cust = resolve_customer_delivery_confirmation_cc("buyer@example.com")
    assert cust == "ops-only@estrellajewels.eu"
    assert "ops-only@estrellajewels.eu" not in dhl
    # DHL still uses INTERNAL_CC when present
    if INTERNAL_CC:
        assert "info@estrellajewels.eu" in dhl
