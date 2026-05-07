"""
test_cowork_concurrent.py — Concurrent execution safety tests for cowork action runner.

Tests:
  1. Concurrent run_actions() on same batch serialises (no duplicate actions)
  2. Second concurrent call waits and sees lock set by first call
  3. Lock is released after exception inside run_actions()
  4. Different batches do not block each other
  5. Timeout raises clear TimeoutError when lock cannot be acquired
  6. Concurrent run_cowork_cycle() writes for same batch do not lose updates
  7. suggest_only=True does not create a lock file or write to audit
  8. submit_cowork_tracking_result under concurrent load does not corrupt audit
  9. No stale .audit.lock remains after exception inside run_cowork_cycle
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
            "clearance_path":  "dhl_self_clearance",
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


# ── Test 6: Concurrent run_cowork_cycle() writes for same batch ───────────────

class TestConcurrentCoworkCycle:
    def test_concurrent_cycles_do_not_lose_updates(self, tmp_path):
        """Two concurrent run_cowork_cycle() calls for the same batch must
        serialise their audit writes — neither should clobber the other's data."""
        _seed_batch(tmp_path, "B_CYCLE")

        from app.agents import cowork_coordinator as coord

        # Patch _OUTPUTS so coordinator writes to tmp_path
        coord._OUTPUTS = tmp_path / "outputs"

        write_count = {"n": 0}
        original_save = coord._save_audit

        def _counting_save(batch_id, audit):
            write_count["n"] += 1
            original_save(batch_id, audit)

        # Patch _save_audit, update_tracking (no-op), and all action senders
        with (
            patch.object(coord, "_save_audit", side_effect=_counting_save),
            patch.object(coord, "update_tracking",    return_value=False),
            patch.object(coord, "send_followup_dhl",  return_value=None),
            patch.object(coord, "trigger_agency",     return_value=False),
            patch.object(coord, "send_followup_agency", return_value=None),
            patch("app.api.routes_action_proposals.generate_action_proposals",
                  return_value=[], create=True),
        ):
            errors = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(coord.run_cowork_cycle, False)
                    for _ in range(2)
                ]
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        errors.append(str(e))

        assert not errors, f"run_cowork_cycle raised: {errors}"
        # audit.json must still be readable (not corrupted) after concurrent writes
        audit_path = tmp_path / "outputs" / "B_CYCLE" / "audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit["batch_id"] == "B_CYCLE"


# ── Test 7: suggest_only=True does not create a lock file ────────────────────

class TestSuggestOnlyNoWrite:
    def test_suggest_only_creates_no_lock_and_no_write(self, tmp_path):
        """suggest_only=True is pure read — must not create .audit.lock or
        modify audit.json."""
        _seed_batch(tmp_path, "B_SUGGEST")

        from app.agents import cowork_coordinator as coord
        coord._OUTPUTS = tmp_path / "outputs"

        audit_path  = tmp_path / "outputs" / "B_SUGGEST" / "audit.json"
        lock_path   = tmp_path / "outputs" / "B_SUGGEST" / ".audit.lock"
        before_mtime = audit_path.stat().st_mtime

        result = coord.run_cowork_cycle(suggest_only=True)

        assert result["mode"] == "suggest_only"
        assert result["batches_checked"] >= 1
        # audit.json must not have been modified
        assert audit_path.stat().st_mtime == before_mtime
        # .audit.lock must not exist (suggest_only never acquires write lock)
        assert not lock_path.exists()


# ── Test 8: submit_cowork_tracking_result under concurrent load ───────────────

class TestTrackingResultUnderLock:
    def test_concurrent_tracking_submit_does_not_corrupt_audit(self, tmp_path):
        """Two concurrent submit_cowork_tracking_result() calls for the same batch
        must serialise — final audit must have a valid tracking block."""
        _seed_batch(tmp_path, "B_TR_LOCK",
                    awb="9876543210", tracking_no="9876543210")

        from app.api import routes_tracking
        from app.api.routes_tracking import submit_cowork_tracking_result, CoworkTrackingResult

        # Patch module-level _OUTPUTS so the route finds the test batch
        routes_tracking._OUTPUTS = tmp_path / "outputs"

        statuses = ["in_transit", "customs"]
        results  = []

        def _submit(status):
            body = CoworkTrackingResult(
                status=status,
                last_event=f"Event for {status}",
                last_location="WARSAW - PL",
                source="test",
                batch_id="B_TR_LOCK",
            )
            return submit_cowork_tracking_result("9876543210", body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_submit, s) for s in statuses]
            for f in as_completed(futures):
                results.append(f.result())

        assert all(r["ok"] for r in results)

        # Audit must be valid JSON with a tracking block
        audit = json.loads(
            (tmp_path / "outputs" / "B_TR_LOCK" / "audit.json").read_text(encoding="utf-8")
        )
        assert "tracking" in audit
        assert audit["tracking"]["status"] in statuses
        assert audit["tracking"]["cowork_result_received"] is True
        assert audit["tracking"]["cowork_tracking_required"] is False

        # Lock file may exist on disk (POSIX convention) but flock must be released:
        # verify we can acquire LOCK_EX | LOCK_NB without blocking.
        lock = tmp_path / "outputs" / "B_TR_LOCK" / ".audit.lock"
        if lock.exists():
            fd = open(lock, "w")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # must not raise
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                fd.close()


# ── Test 9: No stale .audit.lock after exception in run_cowork_cycle ──────────

class TestNoStaleLockAfterCoworkException:
    def test_stale_lock_not_left_after_cycle_exception(self, tmp_path):
        """If an exception is raised inside the batch_write_lock block of
        run_cowork_cycle(), the lock must still be released so the next
        call can proceed."""
        _seed_batch(tmp_path, "B_CYCLE_EXC")

        from app.agents import cowork_coordinator as coord
        coord._OUTPUTS = tmp_path / "outputs"

        # Force an exception inside the locked block by blowing up update_tracking
        with patch.object(coord, "update_tracking",
                          side_effect=RuntimeError("boom")):
            result = coord.run_cowork_cycle(suggest_only=False)

        # The error is captured in summary, not re-raised
        assert len(result["errors"]) >= 1
        assert "boom" in result["errors"][0]

        # Lock FILE may persist on disk (POSIX convention) but the flock
        # advisory lock must be released — verify it can be re-acquired.
        lock = tmp_path / "outputs" / "B_CYCLE_EXC" / ".audit.lock"
        if lock.exists():
            fd = open(lock, "w")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # must not raise
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                fd.close()

        # Second call must succeed (can acquire the lock)
        with (
            patch.object(coord, "update_tracking",      return_value=False),
            patch.object(coord, "send_followup_dhl",    return_value=None),
            patch.object(coord, "trigger_agency",       return_value=False),
            patch.object(coord, "send_followup_agency", return_value=None),
        ):
            result2 = coord.run_cowork_cycle(suggest_only=False)

        assert len(result2["errors"]) == 0
