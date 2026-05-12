"""
test_dhl_selfclearance_p0_thread_lock.py — per-thread reply lock primitive.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_thread_lock as tl  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "thread_locks.db"


def test_acquire_first_call_returns_true(db):
    assert tl.acquire("thr:1", "engine", db_path=db) is True


def test_acquire_second_call_different_actor_returns_false(db):
    assert tl.acquire("thr:1", "engine", db_path=db) is True
    assert tl.acquire("thr:1", "operator", db_path=db) is False


def test_acquire_same_actor_refreshes(db):
    assert tl.acquire("thr:1", "engine", ttl_sec=10, db_path=db) is True
    assert tl.acquire("thr:1", "engine", ttl_sec=10, db_path=db) is True


def test_release_clears_lock(db):
    tl.acquire("thr:1", "engine", db_path=db)
    tl.release("thr:1", "engine", db_path=db)
    assert tl.is_locked("thr:1", db_path=db) is False


def test_release_owner_mismatch_raises(db):
    tl.acquire("thr:1", "engine", db_path=db)
    with pytest.raises(tl.LockOwnershipMismatch):
        tl.release("thr:1", "operator", db_path=db)


def test_force_release_always_succeeds_and_logs(db):
    tl.acquire("thr:1", "engine", db_path=db)
    tl.force_release("thr:1", reason="operator_manual_reply", db_path=db)
    assert tl.is_locked("thr:1", db_path=db) is False
    audit = tl.get_audit("thr:1", db_path=db)
    assert any(row["event"] == "force_released" for row in audit)


def test_force_release_requires_reason(db):
    with pytest.raises(ValueError):
        tl.force_release("thr:1", reason="", db_path=db)


def test_get_holder_returns_owner(db):
    tl.acquire("thr:1", "engine", db_path=db)
    assert tl.get_holder("thr:1", db_path=db) == "engine"


def test_get_holder_after_release_is_none(db):
    tl.acquire("thr:1", "engine", db_path=db)
    tl.release("thr:1", "engine", db_path=db)
    assert tl.get_holder("thr:1", db_path=db) is None


def test_acquire_after_force_release_succeeds(db):
    tl.acquire("thr:1", "engine", db_path=db)
    tl.force_release("thr:1", reason="op", db_path=db)
    assert tl.acquire("thr:1", "engine", db_path=db) is True


def test_concurrent_acquire_only_one_wins(db):
    results = []
    lock = threading.Lock()

    def attempt(actor):
        ok = tl.acquire("thr:concurrent", actor, db_path=db)
        with lock:
            results.append((actor, ok))

    threads = [threading.Thread(target=attempt, args=(f"worker_{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    successes = [r for r in results if r[1] is True]
    assert len(successes) == 1, f"Expected exactly one winner, got {successes}"


def test_audit_log_records_acquire_and_release(db):
    tl.acquire("thr:audit", "engine", db_path=db)
    tl.release("thr:audit", "engine", db_path=db)
    rows = tl.get_audit("thr:audit", db_path=db)
    events = [r["event"] for r in rows]
    assert "acquired" in events
    assert "released" in events


def test_audit_log_records_denied(db):
    tl.acquire("thr:audit2", "engine", db_path=db)
    tl.acquire("thr:audit2", "operator", db_path=db)
    rows = tl.get_audit("thr:audit2", db_path=db)
    assert any(r["event"] == "denied" for r in rows)


def test_acquire_empty_thread_id_raises(db):
    with pytest.raises(ValueError):
        tl.acquire("", "engine", db_path=db)


def test_acquire_empty_actor_raises(db):
    with pytest.raises(ValueError):
        tl.acquire("thr:x", "", db_path=db)


def test_acquire_invalid_ttl_raises(db):
    with pytest.raises(ValueError):
        tl.acquire("thr:x", "engine", ttl_sec=0, db_path=db)
