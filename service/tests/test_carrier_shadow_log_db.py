"""
Phase B tests — shadow_log SQLite store.

Verifies append-only semantics, JSON serialisation, and that
the module never exposes UPDATE or DELETE operations.
"""
import json
import pytest

from app.services.carrier.persistence.shadow_log_db import (
    append_entry,
    count,
    get_entries_for_batch,
    init_db,
)


def _db(tmp_path):
    path = tmp_path / "shadow.db"
    init_db(path)
    return path


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_creates_db(tmp_path):
    assert _db(tmp_path).exists()


def test_init_idempotent(tmp_path):
    db = _db(tmp_path)
    init_db(db)  # second call must not raise


# ── append ────────────────────────────────────────────────────────────────────


def test_append_returns_row_id(tmp_path):
    db = _db(tmp_path)
    row_id = append_entry(db, "batch-1", "k-1", {"req": 1}, {"resp": 2})
    assert isinstance(row_id, int)
    assert row_id >= 1


def test_append_increments_row_id(tmp_path):
    db = _db(tmp_path)
    id1 = append_entry(db, "batch-1", "k-1", {}, {})
    id2 = append_entry(db, "batch-1", "k-2", {}, {})
    assert id2 > id1


def test_count_reflects_inserts(tmp_path):
    db = _db(tmp_path)
    assert count(db) == 0
    append_entry(db, "b", "k1", {}, {})
    append_entry(db, "b", "k2", {}, {})
    assert count(db) == 2


# ── get_entries_for_batch ─────────────────────────────────────────────────────


def test_get_entries_for_batch_returns_correct_rows(tmp_path):
    db = _db(tmp_path)
    append_entry(db, "batch-A", "k-1", {"x": 1}, {"y": 2})
    append_entry(db, "batch-A", "k-2", {"x": 3}, {"y": 4})
    append_entry(db, "batch-B", "k-3", {"x": 5}, {"y": 6})

    rows = get_entries_for_batch(db, "batch-A")
    assert len(rows) == 2
    keys = [r["idempotency_key"] for r in rows]
    assert "k-1" in keys
    assert "k-2" in keys


def test_get_entries_for_unknown_batch_returns_empty(tmp_path):
    db = _db(tmp_path)
    assert get_entries_for_batch(db, "no-batch") == []


def test_json_roundtrip(tmp_path):
    """Payload is stored as JSON and round-trips cleanly."""
    db = _db(tmp_path)
    req = {"carrier": "DHL", "weight": 1.5, "nested": {"a": [1, 2]}}
    resp = {"status": "ok", "simulated": True}
    append_entry(db, "batch-rt", "k-rt", req, resp)
    rows = get_entries_for_batch(db, "batch-rt")
    assert json.loads(rows[0]["request_json"]) == req
    assert json.loads(rows[0]["response_json"]) == resp


# ── append-only enforcement ───────────────────────────────────────────────────


def test_no_update_method_exposed():
    """Module must not export any update function."""
    import app.services.carrier.persistence.shadow_log_db as mod
    assert not hasattr(mod, "update_entry")
    assert not hasattr(mod, "update")
    assert not hasattr(mod, "delete_entry")
    assert not hasattr(mod, "delete")


def test_duplicate_idempotency_key_allowed():
    """Same idempotency_key can appear multiple times — shadow log is a log, not a map."""
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        db = pathlib.Path(td) / "s.db"
        init_db(db)
        append_entry(db, "b", "k-dup", {"attempt": 1}, {})
        append_entry(db, "b", "k-dup", {"attempt": 2}, {})
        assert count(db) == 2
