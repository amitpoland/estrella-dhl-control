"""
Phase B tests — carrier_events webhook dedup store.

Verifies that duplicate event_ids are silently dropped and that
insert_event returns a boolean signal the caller can act on.
"""
import json
import pytest

from app.services.carrier.persistence.event_db import (
    get_event,
    get_events_for_batch,
    init_db,
    insert_event,
)


def _db(tmp_path):
    path = tmp_path / "events.db"
    init_db(path)
    return path


def _insert(db, event_id="evt-001", batch_id="batch-1", event_type="STATUS_UPDATE", payload=None):
    return insert_event(db, event_id, batch_id, event_type, payload or {"status": "ok"})


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_creates_db(tmp_path):
    assert _db(tmp_path).exists()


def test_init_idempotent(tmp_path):
    db = _db(tmp_path)
    init_db(db)


# ── insert ────────────────────────────────────────────────────────────────────


def test_insert_returns_true_for_new_event(tmp_path):
    db = _db(tmp_path)
    assert _insert(db, "e1") is True


def test_insert_returns_false_for_duplicate(tmp_path):
    """Second delivery of the same event_id must be silently dropped."""
    db = _db(tmp_path)
    assert _insert(db, "e-dup") is True
    assert _insert(db, "e-dup") is False


def test_duplicate_does_not_raise(tmp_path):
    """INSERT OR IGNORE — no exception on duplicate."""
    db = _db(tmp_path)
    _insert(db, "e-safe")
    _insert(db, "e-safe")  # must not raise


def test_different_event_ids_both_succeed(tmp_path):
    db = _db(tmp_path)
    assert _insert(db, "e-a") is True
    assert _insert(db, "e-b") is True


# ── get_event ─────────────────────────────────────────────────────────────────


def test_get_event_returns_dict(tmp_path):
    db = _db(tmp_path)
    _insert(db, "e-get", payload={"foo": "bar"})
    row = get_event(db, "e-get")
    assert row is not None
    assert row["event_id"] == "e-get"
    assert row["event_type"] == "STATUS_UPDATE"
    assert json.loads(row["payload_json"]) == {"foo": "bar"}


def test_get_event_returns_none_for_missing(tmp_path):
    db = _db(tmp_path)
    assert get_event(db, "no-such") is None


# ── get_events_for_batch ──────────────────────────────────────────────────────


def test_get_events_for_batch(tmp_path):
    db = _db(tmp_path)
    insert_event(db, "e1", "batch-X", "STATUS_UPDATE", {})
    insert_event(db, "e2", "batch-X", "DELIVERED", {})
    insert_event(db, "e3", "batch-Y", "STATUS_UPDATE", {})

    rows = get_events_for_batch(db, "batch-X")
    assert len(rows) == 2
    ids = {r["event_id"] for r in rows}
    assert ids == {"e1", "e2"}


def test_get_events_for_unknown_batch_returns_empty(tmp_path):
    db = _db(tmp_path)
    assert get_events_for_batch(db, "nobody") == []


# ── payload integrity ─────────────────────────────────────────────────────────


def test_complex_payload_roundtrip(tmp_path):
    db = _db(tmp_path)
    payload = {"nested": {"a": [1, 2, 3]}, "flag": True, "count": 0}
    insert_event(db, "e-complex", "b", "TYPE", payload)
    row = get_event(db, "e-complex")
    assert json.loads(row["payload_json"]) == payload
