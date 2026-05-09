"""
test_carrier_event_db.py — DL-E1 SQLite schema for inbound events +
subscriptions.

Required coverage:
  1. init creates event and subscription tables.
  2. insert event once returns inserted (True).
  3. duplicate insert returns deduped (False) and adds no row.
  4. stored event outcome updates (mark_outcome).
  5. subscription stores secret_hash, NEVER raw secret.
  6. subscription confirmation updates confirmed_at.
  7. event id is deterministic (same inputs → same id).
  8. raw_json is persisted.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.services.carrier import carrier_event_db as ced


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "carrier_events.db"
    ced.init_db(p)
    return p


# ── 1. init creates both tables ────────────────────────────────────────────

def test_init_creates_event_and_subscription_tables(db):
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('carrier_webhook_events', "
        "'carrier_webhook_subscriptions')"
    ).fetchall()
    con.close()
    names = sorted(r[0] for r in rows)
    assert names == [
        "carrier_webhook_events",
        "carrier_webhook_subscriptions",
    ]


# ── 2. insert once returns True ────────────────────────────────────────────

def test_insert_once_returns_inserted(db):
    eid = ced.compute_event_id(
        carrier="dhl", awb="A1", status_code="transit",
        occurred_at="2026-04-01T10:00:00+00:00",
    )
    inserted = ced.insert_event_or_ignore(
        event_id=eid, carrier="dhl", awb="A1",
        status_code="transit", occurred_at="2026-04-01T10:00:00+00:00",
        raw_json="{}",
    )
    assert inserted is True


# ── 3. duplicate insert returns False, no second row ───────────────────────

def test_duplicate_insert_returns_false(db):
    eid = ced.compute_event_id(
        carrier="dhl", awb="A2", status_code="transit",
        occurred_at="2026-04-01T10:00:00+00:00",
    )
    a = ced.insert_event_or_ignore(
        event_id=eid, carrier="dhl", awb="A2",
        status_code="transit", occurred_at="2026-04-01T10:00:00+00:00",
    )
    b = ced.insert_event_or_ignore(
        event_id=eid, carrier="dhl", awb="A2",
        status_code="transit", occurred_at="2026-04-01T10:00:00+00:00",
    )
    assert a is True
    assert b is False
    # And the events table has exactly one row for this id
    con = sqlite3.connect(str(db))
    n = con.execute(
        "SELECT COUNT(*) FROM carrier_webhook_events WHERE id=?", (eid,),
    ).fetchone()[0]
    con.close()
    assert n == 1


# ── 4. mark_outcome ───────────────────────────────────────────────────────

def test_mark_outcome_updates_row(db):
    eid = ced.compute_event_id(
        carrier="dhl", awb="A3", status_code="delivered",
        occurred_at="2026-04-01T11:00:00+00:00",
    )
    ced.insert_event_or_ignore(
        event_id=eid, carrier="dhl", awb="A3",
        status_code="delivered", occurred_at="2026-04-01T11:00:00+00:00",
    )
    ced.mark_outcome(eid, "applied", shipment_id="ship-uuid-1")
    row = ced.get_event(eid)
    assert row is not None
    assert row["outcome"] == "applied"
    assert row["shipment_id"] == "ship-uuid-1"
    assert row["applied_at"]


def test_mark_outcome_without_shipment_id(db):
    eid = ced.compute_event_id(
        carrier="dhl", awb="A4", status_code="exception",
        occurred_at="2026-04-01T12:00:00+00:00",
    )
    ced.insert_event_or_ignore(
        event_id=eid, carrier="dhl", awb="A4",
        status_code="exception",
        occurred_at="2026-04-01T12:00:00+00:00",
    )
    ced.mark_outcome(eid, "no_shipment")
    row = ced.get_event(eid)
    assert row["outcome"] == "no_shipment"
    assert row["shipment_id"] == ""


# ── 5. subscription stores secret_hash, not raw secret ─────────────────────

def test_subscription_stores_only_hash(db):
    raw_secret = "totally-secret-value-do-not-leak"
    h = ced.hash_secret(raw_secret)
    ced.upsert_subscription(subscription_id="sub-1", secret_hash=h)
    rows = ced.get_subscription("sub-1")
    assert len(rows) == 1
    assert rows[0]["secret_hash"] == h
    # Raw secret must NEVER appear in the persisted store
    con = sqlite3.connect(str(db))
    contents = con.execute(
        "SELECT secret_hash FROM carrier_webhook_subscriptions"
    ).fetchall()
    con.close()
    for r in contents:
        assert raw_secret not in r[0]


def test_hash_secret_is_sha256():
    import hashlib
    raw = "abc123"
    assert ced.hash_secret(raw) == hashlib.sha256(raw.encode()).hexdigest()


# ── 6. confirmation updates confirmed_at ───────────────────────────────────

def test_confirm_subscription_updates_confirmed_at(db):
    h = ced.hash_secret("secret-x")
    ced.upsert_subscription(subscription_id="sub-conf", secret_hash=h)
    rows = ced.get_subscription("sub-conf")
    assert rows[0]["confirmed_at"] == ""
    ced.confirm_subscription(subscription_id="sub-conf", secret_hash=h)
    rows = ced.get_subscription("sub-conf")
    assert rows[0]["confirmed_at"]


def test_has_active_secret(db):
    h = ced.hash_secret("yes-active")
    ced.upsert_subscription(subscription_id="sub-act", secret_hash=h)
    assert ced.has_active_secret("sub-act", h) is True
    assert ced.has_active_secret("sub-act", "wrong-hash") is False
    assert ced.has_active_secret("nope", h) is False


# ── 7. event id is deterministic ──────────────────────────────────────────

def test_event_id_is_deterministic():
    a = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="transit",
        occurred_at="2026-04-01T10:00:00Z",
    )
    b = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="transit",
        occurred_at="2026-04-01T10:00:00Z",
    )
    assert a == b


def test_event_id_changes_with_inputs():
    a = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="transit",
        occurred_at="2026-04-01T10:00:00Z",
    )
    b = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="delivered",
        occurred_at="2026-04-01T10:00:00Z",
    )
    c = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="transit",
        occurred_at="2026-04-01T11:00:00Z",
    )
    assert a != b
    assert a != c


def test_event_id_is_case_insensitive_on_carrier_and_status():
    """Same logical event, capitalisation differences → same id."""
    a = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="transit",
        occurred_at="2026-04-01T10:00:00Z",
    )
    b = ced.compute_event_id(
        carrier="DHL", awb="X", status_code="TRANSIT",
        occurred_at="2026-04-01T10:00:00Z",
    )
    assert a == b


# ── 8. raw_json persisted ─────────────────────────────────────────────────

def test_raw_json_is_persisted(db):
    payload = {"carrier": "dhl", "shipment": {"id": "X", "extra": "evidence"}}
    raw = json.dumps(payload, sort_keys=True)
    eid = ced.compute_event_id(
        carrier="dhl", awb="X", status_code="transit",
        occurred_at="2026-04-01T10:00:00Z",
    )
    ced.insert_event_or_ignore(
        event_id=eid, carrier="dhl", awb="X",
        status_code="transit", occurred_at="2026-04-01T10:00:00Z",
        raw_json=raw,
    )
    row = ced.get_event(eid)
    assert json.loads(row["raw_json"]) == payload


def test_get_event_missing_returns_none(db):
    assert ced.get_event("nonexistent") is None


def test_list_events_for_awb(db):
    for code, ts in [
        ("transit",   "2026-04-01T10:00:00Z"),
        ("delivered", "2026-04-01T12:00:00Z"),
    ]:
        eid = ced.compute_event_id(
            carrier="dhl", awb="LIST", status_code=code,
            occurred_at=ts,
        )
        ced.insert_event_or_ignore(
            event_id=eid, carrier="dhl", awb="LIST",
            status_code=code, occurred_at=ts,
        )
    rows = ced.list_events_for_awb("dhl", "LIST")
    assert len(rows) == 2


# ── Init guard ────────────────────────────────────────────────────────────

def test_insert_without_init_raises(monkeypatch):
    monkeypatch.setattr(ced, "_db_path", None, raising=False)
    with pytest.raises(RuntimeError):
        ced.insert_event_or_ignore(
            event_id="eee", carrier="dhl", awb="X",
            status_code="transit", occurred_at="t",
        )
