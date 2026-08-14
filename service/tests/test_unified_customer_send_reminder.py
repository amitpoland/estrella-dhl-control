"""Reminder + confirmation action gates for unified customer Send."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import delivery_confirmation_db as dcdb
from app.services import delivery_confirmation_service as dcs


@pytest.fixture()
def dc_db(tmp_path, monkeypatch):
    monkeypatch.setattr(dcs, "_storage_root", lambda: tmp_path)
    monkeypatch.setattr(dcs, "_db_path", lambda: tmp_path / "delivery_confirmations.db")
    monkeypatch.setattr(
        "app.core.config.settings.customer_delivery_confirmation_enabled", True, raising=False
    )
    from app.core.config import settings
    monkeypatch.setattr(settings, "customer_delivery_confirmation_enabled", True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    db = tmp_path / "delivery_confirmations.db"
    dcdb.init_db(db)
    return db


def test_reminder_denied_without_awaiting(dc_db, monkeypatch):
    result = dcs.send_awaiting_customer_reminder(99)
    assert result["reminded"] is False
    assert result["reason"] == "no_delivery_record"


def test_reminder_allowed_for_awaiting_and_preserves_status(dc_db, monkeypatch):
    awb = "9990001110"
    dcdb.create_notification_if_absent(
        dc_db,
        awb=awb,
        draft_id=42,
        batch_id=None,
        origin_batch_id="ORIGIN",
        client_name="Acme",
        email_to="buyer@example.com",
        activation_cutoff_ok=True,
    )
    dcdb.mark_notification_queued(
        dc_db, awb, email_id="e1", email_to="buyer@example.com", email_cc="", queued_at="2026-01-01T00:00:00Z",
    )
    dcdb.create_receipt_token_row(
        dc_db,
        token_hash="abc",
        awb=awb,
        draft_id=42,
        batch_id=None,
        origin_batch_id="ORIGIN",
        client_name="Acme",
        customer_name="Acme",
        expires_at="2099-01-01T00:00:00Z",
        carrier_delivered_at=None,
    )
    before = dcdb.get_delivery_summary_for_draft(dc_db, 42)
    assert before["operator_status"] == "awaiting_customer"

    calls = {}

    def _queue(**kw):
        calls.update(kw)
        return "email-reminder-1"

    monkeypatch.setattr("app.services.email_service.queue_email", _queue)
    result = dcs.send_awaiting_customer_reminder(42)
    assert result["reminded"] is True
    assert calls.get("email_type") == "customer_delivery_reminder"
    assert calls.get("attachments") == []
    after = dcdb.get_delivery_summary_for_draft(dc_db, 42)
    assert after["operator_status"] == "awaiting_customer"


def test_confirmation_retry_only_for_failed(dc_db, monkeypatch):
    awb = "9990002220"
    dcdb.create_notification_if_absent(
        dc_db,
        awb=awb,
        draft_id=7,
        batch_id=None,
        origin_batch_id=None,
        client_name="Acme",
        email_to="buyer@example.com",
        activation_cutoff_ok=True,
    )
    dcdb.mark_notification_queued(
        dc_db, awb, email_id="e2", email_to="buyer@example.com", email_cc="", queued_at="2026-01-01T00:00:00Z",
    )
    result = dcs.retry_failed_confirmation_for_draft(7)
    assert result["notified"] is False
    assert result["reason"] == "not_failed"
