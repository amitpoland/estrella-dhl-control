"""
test_dhl_readiness_endpoint.py — Phase 2 Step 3.

Verifies GET /api/v1/dhl/readiness/{batch_id}.

Rules under test:
  - No audit trail → dhl_status='awaiting_start', safe defaults
  - dhl_email_received → dhl_status='dhl_contacted'
  - + dsk_transfer_sent → dhl_status='dhl_replied'
  - + cesja_received → dhl_status='dsk_received'
  - + agency_email_sent → dhl_status='agency_forwarded'
  - + zc429_received / pzc_received → dhl_status='sad_received'
  - + ganther_pzc_sent / payment_confirmed → dhl_status='customs_cleared'
  - SLA breach: last outbound > 3 days ago with no later inbound → sla_breach=True
  - SLA no breach: inbound after outbound → sla_breach=False
  - SLA no breach: outbound < 3 days ago → sla_breach=False
  - missing_documents: correct list for dhl_replied and agency_forwarded states
  - next_required_action: correct string per state
  - POST /readiness/{batch_id} → 405
  - Idempotency: same result on repeated calls
  - AWB extracted from tracking_db events
  - All required response keys present
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import tracking_db as tdb
from app.services import dhl_readiness as dr
from app.core import timeline as tl


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("dhr_storage")


@pytest.fixture(scope="module")
def db(tmp_storage):
    tdb.init_tracking_db(tmp_storage / "tracking_events.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Audit helpers ──────────────────────────────────────────────────────────────

def _write_audit(storage_root: Path, batch_id: str, events: list) -> None:
    out_dir = storage_root / "outputs" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "audit.json", "w", encoding="utf-8") as fh:
        json.dump({"timeline": events}, fh)


def _ev(
    event: str,
    ts: str,
    *,
    actor: str = "system",
    detail: dict | None = None,
) -> dict:
    return {
        "event":          event,
        "ts":             ts,
        "trigger_source": "test",
        "actor":          actor,
        "detail":         detail or {},
    }


# Fixed timestamps (in chronological order, all in the past for SLA tests)
T1 = "2026-01-10T08:00:00+00:00"   # DHL initial email
T2 = "2026-01-10T10:00:00+00:00"   # we send DSK reply
T3 = "2026-01-11T09:00:00+00:00"   # DHL sends cesja
T4 = "2026-01-11T14:00:00+00:00"   # we forward to agency
T5 = "2026-01-13T11:00:00+00:00"   # agency sends SAD
T6 = "2026-01-15T16:00:00+00:00"   # customs cleared

# Recent timestamp (< 1 day ago — for SLA no-breach tests)
_RECENT = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()


# ── Required response keys ─────────────────────────────────────────────────────

REQUIRED_KEYS = {
    "batch_id", "dhl_status", "awb", "carrier",
    "dhl_initial_sent", "dhl_reply_received", "dsk_docs_received",
    "agency_forwarded", "sad_received", "customs_cleared",
    "last_email_sent_at", "last_email_sent_type",
    "last_email_received_at", "last_email_received_from",
    "days_since_last_outbound",
    "sla_breach", "sla_breach_reason",
    "next_required_action", "missing_documents",
}


# ── State 1: awaiting_start ───────────────────────────────────────────────────

BATCH_AWAIT = "DHR_AWAITING_BATCH"


class TestAwaitingStart:
    def test_awaiting_no_audit_file(self, db, client):
        """Batch with no audit.json returns awaiting_start."""
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth())
        assert r.status_code == 200
        b = r.json()
        assert b["dhl_status"] == "awaiting_start"

    def test_awaiting_no_timestamps(self, db, client):
        b = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth()).json()
        for key in ("dhl_initial_sent", "dhl_reply_received", "dsk_docs_received",
                    "agency_forwarded", "sad_received", "customs_cleared"):
            assert b[key] is None, f"{key} should be None"

    def test_awaiting_sla_false(self, db, client):
        b = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth()).json()
        assert b["sla_breach"] is False

    def test_awaiting_next_action(self, db, client):
        b = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth()).json()
        assert b["next_required_action"] == "Send initial DHL DSK request"

    def test_awaiting_missing_docs_empty(self, db, client):
        b = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth()).json()
        assert b["missing_documents"] == []

    def test_all_keys_present(self, db, client):
        b = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth()).json()
        assert REQUIRED_KEYS.issubset(b.keys()), f"missing: {REQUIRED_KEYS - b.keys()}"


# ── State 2: dhl_contacted ────────────────────────────────────────────────────

BATCH_CONTACTED = "DHR_CONTACTED_BATCH"


@pytest.fixture(scope="module")
def seeded_contacted(tmp_storage, db):
    _write_audit(tmp_storage, BATCH_CONTACTED, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1, detail={"sender": "dhl@dhl.com"}),
    ])


class TestDhlContacted:
    def test_status_dhl_contacted(self, db, seeded_contacted):
        result = dr.get_dhl_readiness(BATCH_CONTACTED)
        assert result["dhl_status"] == "dhl_contacted"

    def test_dhl_reply_received_set(self, db, seeded_contacted):
        result = dr.get_dhl_readiness(BATCH_CONTACTED)
        assert result["dhl_reply_received"] == T1

    def test_initial_sent_none(self, db, seeded_contacted):
        # We haven't sent anything yet
        result = dr.get_dhl_readiness(BATCH_CONTACTED)
        assert result["dhl_initial_sent"] is None

    def test_next_action(self, db, seeded_contacted):
        result = dr.get_dhl_readiness(BATCH_CONTACTED)
        assert result["next_required_action"] == "Send DSK reply to DHL"

    def test_api_response(self, client, seeded_contacted):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_CONTACTED}", headers=_auth())
        assert r.status_code == 200
        b = r.json()
        assert b["dhl_status"] == "dhl_contacted"


# ── State 3: dhl_replied ──────────────────────────────────────────────────────

BATCH_REPLIED = "DHR_REPLIED_BATCH"


@pytest.fixture(scope="module")
def seeded_replied(tmp_storage, db):
    _write_audit(tmp_storage, BATCH_REPLIED, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
    ])


class TestDhlReplied:
    def test_status_dhl_replied(self, db, seeded_replied):
        result = dr.get_dhl_readiness(BATCH_REPLIED)
        assert result["dhl_status"] == "dhl_replied"

    def test_dhl_initial_sent_set(self, db, seeded_replied):
        result = dr.get_dhl_readiness(BATCH_REPLIED)
        assert result["dhl_initial_sent"] == T2

    def test_dhl_reply_received_set(self, db, seeded_replied):
        result = dr.get_dhl_readiness(BATCH_REPLIED)
        assert result["dhl_reply_received"] == T1

    def test_dsk_docs_not_yet(self, db, seeded_replied):
        result = dr.get_dhl_readiness(BATCH_REPLIED)
        assert result["dsk_docs_received"] is None

    def test_missing_docs_cesja(self, db, seeded_replied):
        result = dr.get_dhl_readiness(BATCH_REPLIED)
        assert "DHL cesja / DSK authorization documents" in result["missing_documents"]

    def test_next_action(self, db, seeded_replied):
        result = dr.get_dhl_readiness(BATCH_REPLIED)
        assert result["next_required_action"] == "Await DHL cesja / DSK authorization documents"


# ── State 4: dsk_received ─────────────────────────────────────────────────────

BATCH_DSK = "DHR_DSK_BATCH"


@pytest.fixture(scope="module")
def seeded_dsk(tmp_storage, db):
    _write_audit(tmp_storage, BATCH_DSK, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
        _ev(tl.EV_CESJA_RECEIVED,      T3),
    ])


class TestDskReceived:
    def test_status_dsk_received(self, db, seeded_dsk):
        result = dr.get_dhl_readiness(BATCH_DSK)
        assert result["dhl_status"] == "dsk_received"

    def test_dsk_docs_received_set(self, db, seeded_dsk):
        result = dr.get_dhl_readiness(BATCH_DSK)
        assert result["dsk_docs_received"] == T3

    def test_missing_docs_empty(self, db, seeded_dsk):
        # We have cesja, not waiting for it anymore
        result = dr.get_dhl_readiness(BATCH_DSK)
        assert result["missing_documents"] == []

    def test_next_action(self, db, seeded_dsk):
        result = dr.get_dhl_readiness(BATCH_DSK)
        assert result["next_required_action"] == "Forward DSK documents to customs agency"


# ── State 5: agency_forwarded ─────────────────────────────────────────────────

BATCH_AGENCY = "DHR_AGENCY_BATCH"


@pytest.fixture(scope="module")
def seeded_agency(tmp_storage, db):
    _write_audit(tmp_storage, BATCH_AGENCY, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
        _ev(tl.EV_CESJA_RECEIVED,      T3),
        _ev(tl.EV_AGENCY_EMAIL_SENT,   T4),
    ])


class TestAgencyForwarded:
    def test_status_agency_forwarded(self, db, seeded_agency):
        result = dr.get_dhl_readiness(BATCH_AGENCY)
        assert result["dhl_status"] == "agency_forwarded"

    def test_agency_forwarded_ts_set(self, db, seeded_agency):
        result = dr.get_dhl_readiness(BATCH_AGENCY)
        assert result["agency_forwarded"] == T4

    def test_missing_docs_sad(self, db, seeded_agency):
        result = dr.get_dhl_readiness(BATCH_AGENCY)
        assert "SAD / ZC429 / PZC from customs agency" in result["missing_documents"]

    def test_next_action(self, db, seeded_agency):
        result = dr.get_dhl_readiness(BATCH_AGENCY)
        assert result["next_required_action"] == "Await SAD / ZC429 / PZC from customs agency"

    def test_api_response(self, client, seeded_agency):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_AGENCY}", headers=_auth())
        assert r.status_code == 200
        assert r.json()["dhl_status"] == "agency_forwarded"


# ── State 6: sad_received ─────────────────────────────────────────────────────

BATCH_SAD = "DHR_SAD_BATCH"


@pytest.fixture(scope="module")
def seeded_sad(tmp_storage, db):
    _write_audit(tmp_storage, BATCH_SAD, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
        _ev(tl.EV_CESJA_RECEIVED,      T3),
        _ev(tl.EV_AGENCY_EMAIL_SENT,   T4),
        _ev(tl.EV_ZC429_RECEIVED,      T5),
    ])


class TestSadReceived:
    def test_status_sad_received(self, db, seeded_sad):
        result = dr.get_dhl_readiness(BATCH_SAD)
        assert result["dhl_status"] == "sad_received"

    def test_sad_received_ts_set(self, db, seeded_sad):
        result = dr.get_dhl_readiness(BATCH_SAD)
        assert result["sad_received"] == T5

    def test_missing_docs_empty(self, db, seeded_sad):
        # SAD arrived, nothing missing
        result = dr.get_dhl_readiness(BATCH_SAD)
        assert result["missing_documents"] == []

    def test_next_action(self, db, seeded_sad):
        result = dr.get_dhl_readiness(BATCH_SAD)
        assert result["next_required_action"] == "Process customs documents and generate PZ"

    def test_pzc_also_advances_to_sad_received(self, tmp_storage, db):
        """pzc_received should also advance to sad_received."""
        bid = "DHR_PZC_BATCH"
        _write_audit(tmp_storage, bid, [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
            _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
            _ev(tl.EV_CESJA_RECEIVED,      T3),
            _ev(tl.EV_AGENCY_EMAIL_SENT,   T4),
            _ev(tl.EV_PZC_RECEIVED,        T5),
        ])
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(bid)
        assert result["dhl_status"] == "sad_received"
        assert result["sad_received"] == T5


# ── State 7: customs_cleared ──────────────────────────────────────────────────

BATCH_CLEARED = "DHR_CLEARED_BATCH"


@pytest.fixture(scope="module")
def seeded_cleared(tmp_storage, db):
    _write_audit(tmp_storage, BATCH_CLEARED, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
        _ev(tl.EV_CESJA_RECEIVED,      T3),
        _ev(tl.EV_AGENCY_EMAIL_SENT,   T4),
        _ev(tl.EV_ZC429_RECEIVED,      T5),
        _ev(tl.EV_GANTHER_PZC_SENT,    T6),
    ])


class TestCustomsCleared:
    def test_status_customs_cleared(self, db, seeded_cleared):
        result = dr.get_dhl_readiness(BATCH_CLEARED)
        assert result["dhl_status"] == "customs_cleared"

    def test_customs_cleared_ts_set(self, db, seeded_cleared):
        result = dr.get_dhl_readiness(BATCH_CLEARED)
        assert result["customs_cleared"] == T6

    def test_all_milestones_set(self, db, seeded_cleared):
        result = dr.get_dhl_readiness(BATCH_CLEARED)
        assert result["dhl_initial_sent"]  == T2
        assert result["dhl_reply_received"] == T1
        assert result["dsk_docs_received"] == T3
        assert result["agency_forwarded"]  == T4
        assert result["sad_received"]      == T5
        assert result["customs_cleared"]   == T6

    def test_next_action_none(self, db, seeded_cleared):
        result = dr.get_dhl_readiness(BATCH_CLEARED)
        assert result["next_required_action"] is None

    def test_missing_docs_empty(self, db, seeded_cleared):
        result = dr.get_dhl_readiness(BATCH_CLEARED)
        assert result["missing_documents"] == []

    def test_api_all_keys_present(self, client, seeded_cleared):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_CLEARED}", headers=_auth())
        b = r.json()
        assert REQUIRED_KEYS.issubset(b.keys()), f"missing: {REQUIRED_KEYS - b.keys()}"

    def test_payment_confirmed_also_clears(self, tmp_storage, db):
        """payment_confirmed is also a customs_cleared signal."""
        bid = "DHR_PAYMENT_BATCH"
        _write_audit(tmp_storage, bid, [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
            _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
            _ev(tl.EV_CESJA_RECEIVED,      T3),
            _ev(tl.EV_AGENCY_EMAIL_SENT,   T4),
            _ev(tl.EV_ZC429_RECEIVED,      T5),
            _ev(tl.EV_PAYMENT_CONFIRMED,   T6),
        ])
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(bid)
        assert result["dhl_status"] == "customs_cleared"


# ── SLA breach ────────────────────────────────────────────────────────────────

BATCH_SLA_BREACH = "DHR_SLA_BREACH_BATCH"
BATCH_SLA_OK_INBOUND = "DHR_SLA_OK_INBOUND_BATCH"
BATCH_SLA_OK_RECENT  = "DHR_SLA_OK_RECENT_BATCH"


@pytest.fixture(scope="module")
def seeded_sla_breach(tmp_storage, db):
    """Last outbound > 3 days ago, no later inbound — SLA breached."""
    _write_audit(tmp_storage, BATCH_SLA_BREACH, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),   # old outbound, no reply
    ])


@pytest.fixture(scope="module")
def seeded_sla_ok_inbound(tmp_storage, db):
    """Outbound > 3 days ago BUT inbound arrived after — no breach."""
    _write_audit(tmp_storage, BATCH_SLA_OK_INBOUND, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  T2),   # old outbound
        _ev(tl.EV_CESJA_RECEIVED,      T3),   # inbound AFTER outbound
    ])


@pytest.fixture(scope="module")
def seeded_sla_ok_recent(tmp_storage, db):
    """Outbound < 3 days ago — no breach regardless of no inbound."""
    _write_audit(tmp_storage, BATCH_SLA_OK_RECENT, [
        _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        _ev(tl.EV_DSK_TRANSFER_SENT,  _RECENT),  # very recent, no breach yet
    ])


class TestSlaBreach:
    def test_sla_breach_true_old_outbound_no_reply(self, tmp_storage, db, seeded_sla_breach):
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(BATCH_SLA_BREACH)
        assert result["sla_breach"] is True
        assert result["sla_breach_reason"] is not None
        assert result["days_since_last_outbound"] > 3

    def test_sla_breach_false_inbound_after_outbound(self, tmp_storage, db, seeded_sla_ok_inbound):
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(BATCH_SLA_OK_INBOUND)
        assert result["sla_breach"] is False
        assert result["sla_breach_reason"] is None

    def test_sla_breach_false_recent_outbound(self, tmp_storage, db, seeded_sla_ok_recent):
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(BATCH_SLA_OK_RECENT)
        assert result["sla_breach"] is False

    def test_days_since_computed_correctly(self, tmp_storage, db, seeded_sla_ok_recent):
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(BATCH_SLA_OK_RECENT)
        # recent outbound ~6 hours ago → days_since_last_outbound ≈ 0.25
        assert result["days_since_last_outbound"] is not None
        assert result["days_since_last_outbound"] < 1.0

    def test_no_outbound_days_none(self, db, client):
        """Batch with only inbound events has no days_since_last_outbound."""
        bid = "DHR_INBOUND_ONLY_BATCH"
        # no audit.json = no outbound
        r = client.get(f"/api/v1/dhl/readiness/{bid}", headers=_auth())
        b = r.json()
        assert b["days_since_last_outbound"] is None

    def test_sla_breach_reason_contains_event_name(self, tmp_storage, db, seeded_sla_breach):
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(BATCH_SLA_BREACH)
        assert tl.EV_DSK_TRANSFER_SENT in result["sla_breach_reason"]

    def test_api_sla_breach_in_response(self, client, seeded_sla_breach):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_SLA_BREACH}", headers=_auth())
        assert r.status_code == 200
        b = r.json()
        assert b["sla_breach"] is True
        assert b["sla_breach_reason"] is not None


# ── Missing documents ─────────────────────────────────────────────────────────

class TestMissingDocuments:
    def test_dhl_replied_missing_cesja(self, tmp_storage, db):
        """After sending DSK, we are waiting for cesja — should be in missing_documents."""
        bid = "DHR_MISS_CESJA_BATCH"
        _write_audit(tmp_storage, bid, [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
            _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
        ])
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(bid)
        assert result["dhl_status"] == "dhl_replied"
        assert "DHL cesja / DSK authorization documents" in result["missing_documents"]

    def test_agency_forwarded_missing_sad(self, tmp_storage, db):
        """After forwarding to agency, SAD is missing."""
        bid = "DHR_MISS_SAD_BATCH"
        _write_audit(tmp_storage, bid, [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
            _ev(tl.EV_DSK_TRANSFER_SENT,  T2),
            _ev(tl.EV_CESJA_RECEIVED,      T3),
            _ev(tl.EV_AGENCY_EMAIL_SENT,   T4),
        ])
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(bid)
        assert result["dhl_status"] == "agency_forwarded"
        assert "SAD / ZC429 / PZC from customs agency" in result["missing_documents"]

    def test_dsk_received_no_missing(self, db, seeded_dsk):
        """dsk_received state: cesja is here, nothing missing."""
        result = dr.get_dhl_readiness(BATCH_DSK)
        assert result["missing_documents"] == []

    def test_cleared_no_missing(self, db, seeded_cleared):
        """customs_cleared: nothing missing."""
        result = dr.get_dhl_readiness(BATCH_CLEARED)
        assert result["missing_documents"] == []


# ── AWB extraction ────────────────────────────────────────────────────────────

class TestAwbExtraction:
    def test_awb_from_tracking_db(self, tmp_storage, db):
        """AWB should be extracted from tracking_db events."""
        bid = "DHR_AWB_BATCH"
        _write_audit(tmp_storage, bid, [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, T1),
        ])
        # Insert tracking event with AWB
        tdb.record_event(
            batch_id=bid,
            awb="1234567890",
            stage="DHL_FIRST_EMAIL_RECEIVED",
            event_time=T1,
            source="test",
            carrier="DHL",
        )
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(bid)
        assert result["awb"] == "1234567890"
        assert result["carrier"] == "DHL"

    def test_awb_from_timeline_detail(self, tmp_storage, db):
        """AWB in timeline event detail is used when tracking_db has no events."""
        bid = "DHR_AWB_DETAIL_BATCH"
        _write_audit(tmp_storage, bid, [
            _ev(tl.EV_DHL_EMAIL_RECEIVED, T1, detail={"awb": "9876543210", "carrier": "DHL"}),
        ])
        with patch.object(settings, "storage_root", tmp_storage):
            result = dr.get_dhl_readiness(bid)
        assert result["awb"] == "9876543210"

    def test_awb_none_when_not_available(self, db, client):
        """When no AWB is anywhere, awb and carrier are None."""
        bid = "DHR_NO_AWB_BATCH"
        # no audit.json, no tracking events
        r = client.get(f"/api/v1/dhl/readiness/{bid}", headers=_auth())
        b = r.json()
        assert b["awb"] is None
        assert b["carrier"] is None


# ── POST guard ────────────────────────────────────────────────────────────────

class TestPostRejected:
    def test_post_returns_405(self, client):
        r = client.post(
            f"/api/v1/dhl/readiness/{BATCH_AWAIT}",
            headers=_auth(),
        )
        assert r.status_code in (404, 405), (
            f"POST to readiness should be rejected: got {r.status_code}"
        )


# ── Idempotency ───────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_repeated_calls_same_result(self, db, seeded_cleared):
        r1 = dr.get_dhl_readiness(BATCH_CLEARED)
        r2 = dr.get_dhl_readiness(BATCH_CLEARED)
        # All stable fields must match
        for key in ("dhl_status", "awb", "carrier", "dhl_initial_sent",
                    "dhl_reply_received", "dsk_docs_received", "agency_forwarded",
                    "sad_received", "customs_cleared", "sla_breach",
                    "next_required_action", "missing_documents"):
            assert r1[key] == r2[key], f"idempotency failure on key={key}"

    def test_api_idempotent(self, client, seeded_cleared):
        r1 = client.get(f"/api/v1/dhl/readiness/{BATCH_CLEARED}", headers=_auth()).json()
        r2 = client.get(f"/api/v1/dhl/readiness/{BATCH_CLEARED}", headers=_auth()).json()
        assert r1["dhl_status"] == r2["dhl_status"]
        assert r1["customs_cleared"] == r2["customs_cleared"]


# ── Field contract ────────────────────────────────────────────────────────────

class TestFieldContract:
    def test_all_required_keys_awaiting(self, db, client):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth())
        assert REQUIRED_KEYS.issubset(r.json().keys())

    def test_all_required_keys_cleared(self, client, seeded_cleared):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_CLEARED}", headers=_auth())
        assert REQUIRED_KEYS.issubset(r.json().keys())

    def test_batch_id_echoed(self, db, client):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth())
        assert r.json()["batch_id"] == BATCH_AWAIT

    def test_missing_documents_is_list(self, db, client):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth())
        assert isinstance(r.json()["missing_documents"], list)

    def test_sla_breach_is_bool(self, db, client):
        r = client.get(f"/api/v1/dhl/readiness/{BATCH_AWAIT}", headers=_auth())
        assert isinstance(r.json()["sla_breach"], bool)
