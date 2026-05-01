"""
test_cowork_concurrent.py — Concurrent execution safety tests for cowork action runner.

Tests:
  1. Concurrent run_actions() on same batch serialises (no duplicate actions)
  2. Second concurrent call waits and sees lock set by first call
  3. Lock is released after exception inside run_actions()
  4. Different batches do not block each other
  5. Timeout raises clear TimeoutError when lock cannot be acquired
"""
from __future__ import annotations

import json
import os
import sys
import fcntl
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

# ── Path + env setup ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point settings.storage_root at tmp_path so all service code is isolated."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_batch(root: Path, batch_id: str, **extra) -> Path:
    """Create a minimal batch for testing."""
    batch_dir = root / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id":    batch_id,
        "awb":         "1234567890",
        "tracking_no": "1234567890",
        "status":      "processing",
        "clearance_decision": {
            "total_value_usd": 800.0,
            "clearance_path":  "carrier_self_clearance",
        },
        "timeline": [],
    }
    audit.update(extra)
    (batch_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False), encoding="utf-8"
    )
    return batch_dir


def _read_audit(batch_dir: Path) -> Dict[str, Any]:
    return json.loads((batch_dir / "audit.json").read_text(encoding="utf-8"))


# ── Test 1: Concurrent run_actions() on same batch — no duplicate execution ──

class TestConcurrentSameBatch:
    def test_concurrent_run_actions_serialises(self, tmp_path):
        """Two threads calling run_actions on the same batch must serialise.

        We register a slow mock handler that takes 0.2s.  Two threads call
        run_actions simultaneously.  Because of the batch lock, only one
        thread executes at a time.  Both should succeed (the second waits),
        and the handler should be called exactly twice (once per thread),
        but never concurrently.
        """
        _seed_batch(tmp_path, "B_CONC")

        from app.services import cowork_action_runner as runner
        from app.core.config import settings

        concurrent_count = {"max": 0, "current": 0}
        lock = threading.Lock()

        original_handlers = dict(runner._ACTION_HANDLERS)

        def _slow_handler(batch_id, action_desc):
            with lock:
                concurrent_count["current"] += 1
                concurrent_count["max"] = max(
                    concurrent_count["max"], concurrent_count["current"]
                )
            time.sleep(0.2)
            with lock:
                concurrent_count["current"] -= 1
            return {"ok": True}

        runner._ACTION_HANDLERS["test_slow_action"] = _slow_handler
        try:
            actions = [{"action": "test_slow_action", "task_id": "t1", "reason": "test"}]

            results = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(runner.run_actions, "B_CONC", actions)
                    for _ in range(2)
                ]
                for f in as_completed(futures):
                    results.append(f.result())

            # Both should succeed
            assert all(r["ok"] for r in results)
            # Max concurrency should be 1 (serialised by batch lock)
            assert concurrent_count["max"] == 1
        finally:
            runner._ACTION_HANDLERS = original_handlers


# ── Test 2: Second call sees lock set by first call ──────────────────────────

class TestSecondCallSeesLock:
    def test_second_call_sees_action_lock_from_first(self, tmp_path):
        """First run_actions sets action_lock; second call on same batch
        sees the lock and skips the action."""
        _seed_batch(tmp_path, "B_LOCK_SEQ")

        from app.services import cowork_action_runner as runner

        original_handlers = dict(runner._ACTION_HANDLERS)

        call_count = {"n": 0}

        def _counting_handler(batch_id, action_desc):
            call_count["n"] += 1
            return {"ok": True}

        runner._ACTION_HANDLERS["build_and_send_dhl_reply"] = _counting_handler
        try:
            actions = [{"action": "build_and_send_dhl_reply", "task_id": "t1", "reason": "test"}]

            # First call — should execute
            r1 = runner.run_actions("B_LOCK_SEQ", actions)
            assert r1["ok"] is True
            assert len(r1["executed"]) == 1

            # Second call — same action on same batch — should be skipped
            r2 = runner.run_actions("B_LOCK_SEQ", actions)
            assert r2["ok"] is True
            assert len(r2["skipped"]) == 1
            assert r2["skipped"][0]["reason"] == "action_lock_active"

            # Handler called only once
            assert call_count["n"] == 1
        finally:
            runner._ACTION_HANDLERS = original_handlers


# ── Test 3: Lock is released after exception ─────────────────────────────────

class TestLockReleasedAfterException:
    def test_lock_released_after_handler_exception(self, tmp_path):
        """If a handler raises, the batch lock must still be released so the
        next call can acquire it."""
        _seed_batch(tmp_path, "B_EXC")

        from app.services import cowork_action_runner as runner

        original_handlers = dict(runner._ACTION_HANDLERS)
        runner._ACTION_HANDLERS["test_failing"] = lambda bid, ad: (_ for _ in ()).throw(
            RuntimeError("intentional test failure")
        )
        try:
            actions = [{"action": "test_failing", "task_id": "t1", "reason": "test"}]

            # First call — handler raises, but lock should be released
            r1 = runner.run_actions("B_EXC", actions)
            assert r1["ok"] is False
            assert len(r1["failed"]) == 1

            # Second call should acquire the lock without timeout
            runner._ACTION_HANDLERS["test_failing"] = lambda bid, ad: {"ok": True}
            r2 = runner.run_actions("B_EXC", actions)
            assert r2["ok"] is True
        finally:
            runner._ACTION_HANDLERS = original_handlers


# ── Test 4: Different batches do not block each other ────────────────────────

class TestDifferentBatchesIndependent:
    def test_different_batches_run_in_parallel(self, tmp_path):
        """Actions on different batches should execute concurrently."""
        _seed_batch(tmp_path, "B_PAR_A")
        _seed_batch(tmp_path, "B_PAR_B")

        from app.services import cowork_action_runner as runner

        original_handlers = dict(runner._ACTION_HANDLERS)

        concurrent_count = {"max": 0, "current": 0}
        lock = threading.Lock()

        def _slow_handler(batch_id, action_desc):
            with lock:
                concurrent_count["current"] += 1
                concurrent_count["max"] = max(
                    concurrent_count["max"], concurrent_count["current"]
                )
            time.sleep(0.2)
            with lock:
                concurrent_count["current"] -= 1
            return {"ok": True}

        runner._ACTION_HANDLERS["test_slow_action"] = _slow_handler
        try:
            actions = [{"action": "test_slow_action", "task_id": "t1", "reason": "test"}]

            results = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(runner.run_actions, "B_PAR_A", actions),
                    pool.submit(runner.run_actions, "B_PAR_B", actions),
                ]
                for f in as_completed(futures):
                    results.append(f.result())

            assert all(r["ok"] for r in results)
            # Max concurrency should be 2 (different batches, independent locks)
            assert concurrent_count["max"] == 2
        finally:
            runner._ACTION_HANDLERS = original_handlers


# ── Test 5: Timeout raises clear TimeoutError ────────────────────────────────

class TestLockTimeout:
    def test_timeout_raises_timeout_error(self, tmp_path):
        """If the batch lock cannot be acquired within timeout, raise TimeoutError."""
        _seed_batch(tmp_path, "B_TIMEOUT")

        from app.utils.batch_lock import batch_write_lock, _lock_path

        # Manually hold the lock from the main thread
        lp = _lock_path("B_TIMEOUT")
        lp.parent.mkdir(parents=True, exist_ok=True)
        held_fd = open(lp, "w")
        fcntl.flock(held_fd, fcntl.LOCK_EX)

        try:
            # Try to acquire from another thread with a short timeout
            error_holder = {}

            def _try_lock():
                try:
                    with batch_write_lock("B_TIMEOUT", timeout_seconds=1):
                        pass  # should not reach here
                except TimeoutError as e:
                    error_holder["exc"] = e

            t = threading.Thread(target=_try_lock)
            t.start()
            t.join(timeout=5)

            assert "exc" in error_holder
            assert "B_TIMEOUT" in str(error_holder["exc"])
            assert "1s" in str(error_holder["exc"])
        finally:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            held_fd.close()
