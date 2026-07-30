"""
test_circuit_breaker.py — Unit tests for the circuit breaker core module.

These tests exercise state transitions, retry logic, and registry behaviour
without making any real network calls.
"""
from __future__ import annotations

import threading
import time
import pytest

import app.core.circuit_breaker as cb_mod
from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerProbeInProgress,
    CircuitState,
    ServiceConfig,
    get_circuit_breaker,
    get_all_stats,
    reset_all,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakeClock:
    """Controllable stand-in for the ``time`` module used inside circuit_breaker.

    Monkeypatch it in with ``monkeypatch.setattr(cb_mod, "time", clock)`` — the
    breaker's ``time.time()`` and ``time.sleep()`` then resolve to this object,
    so recovery-timeout behaviour is exercised deterministically without any
    real 90-second sleeps. Only the circuit_breaker module namespace is
    affected; the real ``time`` module is untouched everywhere else.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        # Deterministic: advance virtual time instead of blocking a real thread.
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds

def _fast_config(**overrides) -> ServiceConfig:
    """Return a ServiceConfig with no retries and a short (but non-zero) recovery timeout.

    recovery_timeout=0 means _maybe_transition() immediately leaves OPEN on the
    very next call, so tests that need a stable OPEN state must use a positive
    value (e.g. 999).  Tests that want instant recovery pass recovery_timeout=0
    explicitly.
    """
    defaults = dict(
        name              = "test_svc",
        failure_threshold = 3,
        recovery_timeout  = 999,  # stable OPEN by default; override when testing recovery
        call_timeout      = 5,
        retry_attempts    = 1,    # no retries — fail fast
    )
    defaults.update(overrides)
    return ServiceConfig(**defaults)


def _make_breaker(**overrides) -> CircuitBreaker:
    return CircuitBreaker(_fast_config(**overrides))


def _fail() -> None:
    raise ValueError("simulated failure")


def _ok() -> str:
    return "ok"


# ── State: CLOSED → normal operation ─────────────────────────────────────────

class TestClosedState:
    def test_successful_call_returns_value(self):
        cb = _make_breaker()
        assert cb.call(_ok) == "ok"

    def test_state_stays_closed_on_success(self):
        cb = _make_breaker()
        cb.call(_ok)
        assert cb.state == CircuitState.CLOSED

    def test_failure_is_propagated(self):
        cb = _make_breaker()
        with pytest.raises(ValueError, match="simulated failure"):
            cb.call(_fail)

    def test_failure_increments_counter(self):
        cb = _make_breaker()
        with pytest.raises(ValueError):
            cb.call(_fail)
        assert cb.get_stats().failure_count == 1

    def test_state_stays_closed_below_threshold(self):
        cb = _make_breaker(failure_threshold=3)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_fail)
        assert cb.state == CircuitState.CLOSED


# ── State: CLOSED → OPEN ──────────────────────────────────────────────────────

class TestOpenTransition:
    def test_opens_after_threshold_failures(self):
        cb = _make_breaker(failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_fail)
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        cb = _make_breaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(_fail)
        # Circuit is now open
        with pytest.raises(CircuitBreakerError):
            cb.call(_ok)

    def test_open_circuit_does_not_call_function(self):
        called = []

        def track() -> str:
            called.append(True)
            return "called"

        cb = _make_breaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(_fail)

        called.clear()
        with pytest.raises(CircuitBreakerError):
            cb.call(track)

        assert called == [], "Function must not be called when circuit is OPEN"


# ── State: OPEN → HALF_OPEN → CLOSED ─────────────────────────────────────────

class TestRecovery:
    def test_transitions_to_closed_after_successful_probe(self):
        """After opening, a successful probe (recovery_timeout=0) closes the circuit."""
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0)
        with pytest.raises(ValueError):
            cb.call(_fail)
        # Circuit is OPEN; with recovery_timeout=0 the next call is a HALF_OPEN probe
        result = cb.call(_ok)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_failed_probe_goes_back_to_open(self):
        """A failed probe in HALF_OPEN state transitions back to OPEN."""
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0)
        with pytest.raises(ValueError):
            cb.call(_fail)
        # Circuit is OPEN; probe via next call — force it into HALF_OPEN first
        cb._state = CircuitState.HALF_OPEN
        with pytest.raises(ValueError):
            cb.call(_fail)
        assert cb.state == CircuitState.OPEN

    def test_success_in_half_open_resets_failure_count(self):
        """Successful recovery probe resets the failure counter."""
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0)
        with pytest.raises(ValueError):
            cb.call(_fail)
        cb.call(_ok)  # probe succeeds → CLOSED
        assert cb.get_stats().failure_count == 0


# ── Force open / close ────────────────────────────────────────────────────────

class TestManualControl:
    def test_force_open(self):
        cb = _make_breaker()
        cb.force_open()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerError):
            cb.call(_ok)

    def test_force_close(self):
        cb = _make_breaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        cb.force_close()
        assert cb.state == CircuitState.CLOSED
        assert cb.call(_ok) == "ok"

    def test_force_close_resets_counters(self):
        cb = _make_breaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(_fail)
        cb.force_close()
        stats = cb.get_stats()
        assert stats.failure_count == 0
        assert stats.success_count == 0


# ── Stats ─────────────────────────────────────────────────────────────────────

class TestStats:
    def test_total_calls_counts_all_attempts(self):
        cb = _make_breaker(failure_threshold=10)
        cb.call(_ok)
        with pytest.raises(ValueError):
            cb.call(_fail)
        assert cb.get_stats().total_calls == 2

    def test_last_failure_time_updated(self):
        cb = _make_breaker()
        before = time.time()
        with pytest.raises(ValueError):
            cb.call(_fail)
        assert cb.get_stats().last_failure_time >= before

    def test_last_success_time_updated(self):
        cb = _make_breaker()
        before = time.time()
        cb.call(_ok)
        assert cb.get_stats().last_success_time >= before


# ── Registry ──────────────────────────────────────────────────────────────────

class TestRegistry:
    def setup_method(self):
        reset_all()

    def test_same_name_returns_same_instance(self):
        a = get_circuit_breaker("svc_a")
        b = get_circuit_breaker("svc_a")
        assert a is b

    def test_different_names_return_different_instances(self):
        a = get_circuit_breaker("svc_x")
        b = get_circuit_breaker("svc_y")
        assert a is not b

    def test_reset_all_closes_open_circuits(self):
        cb = get_circuit_breaker("svc_reset_test")
        cb.force_open()
        assert cb.state == CircuitState.OPEN

        reset_all()
        assert cb.state == CircuitState.CLOSED

    def test_get_all_stats_includes_registered(self):
        get_circuit_breaker("stat_svc_1")
        get_circuit_breaker("stat_svc_2")
        stats = get_all_stats()
        assert "stat_svc_1" in stats
        assert "stat_svc_2" in stats

    def test_known_service_gets_tuned_config(self):
        cb = get_circuit_breaker("wfirma")
        assert cb.config.failure_threshold == 4
        assert cb.config.recovery_timeout  == 90

    def test_unknown_service_gets_default_config(self):
        cb = get_circuit_breaker("totally_unknown_svc_xyz")
        assert cb.config.name == "totally_unknown_svc_xyz"
        # Should not raise
        assert cb.state == CircuitState.CLOSED


# ── Deterministic recovery-timeout behaviour (fake clock) ─────────────────────
#
# Regression suite for the stuck-OPEN defect (2026-07-30): an OPEN breaker must
# evaluate its recovery_timeout and admit a single HALF_OPEN probe once the
# window elapses, instead of staying OPEN until the process restarts. These
# tests drive time deterministically via _FakeClock — no real sleeps, no
# 90-second waits — and exercise the transitions through the PUBLIC ``call()``
# surface only (the same surface every real caller must use).

class TestRecoveryTimeoutFakeClock:
    def test_probe_in_progress_is_circuit_breaker_error_subclass(self):
        """Existing ``except CircuitBreakerError`` handlers must keep catching
        the concurrent-probe rejection unchanged."""
        assert issubclass(CircuitBreakerProbeInProgress, CircuitBreakerError)

    def test_open_stays_open_before_recovery_timeout(self, monkeypatch):
        """Before recovery_timeout elapses, an OPEN breaker rejects and does NOT
        admit a probe (no call reaches the wrapped function)."""
        clock = _FakeClock()
        monkeypatch.setattr(cb_mod, "time", clock)
        cb = _make_breaker(failure_threshold=1, recovery_timeout=90)

        with pytest.raises(ValueError):
            cb.call(_fail)                      # trip OPEN at t=1000
        assert cb.state == CircuitState.OPEN

        clock.advance(89)                       # still inside the 90s window
        called = []
        with pytest.raises(CircuitBreakerError):
            cb.call(lambda: called.append(True))
        assert called == [], "no probe may run before recovery_timeout"
        assert cb.state == CircuitState.OPEN

    def test_open_recovers_to_half_open_probe_after_recovery_timeout(self, monkeypatch):
        """THE core regression: once recovery_timeout elapses, the next call is
        admitted as a HALF_OPEN probe (reaches the function) and — on success —
        closes the circuit. Before the fix this transition was unreachable."""
        clock = _FakeClock()
        monkeypatch.setattr(cb_mod, "time", clock)
        cb = _make_breaker(failure_threshold=1, recovery_timeout=90)

        with pytest.raises(ValueError):
            cb.call(_fail)                      # OPEN at t=1000
        assert cb.state == CircuitState.OPEN

        clock.advance(90)                       # deadline reached
        called = []

        def _probe() -> str:
            called.append(True)
            return "probe-ok"

        assert cb.call(_probe) == "probe-ok", "recovery probe must actually run"
        assert called == [True]
        assert cb.state == CircuitState.CLOSED, "successful probe must CLOSE"

    def test_rejected_open_calls_do_not_move_recovery_deadline(self, monkeypatch):
        """Fast-fail rejections while OPEN must NOT push _last_failure forward,
        or a steady stream of rejected calls would postpone recovery forever
        (this is what 3,704 rejections did to the live wFirma breaker)."""
        clock = _FakeClock()
        monkeypatch.setattr(cb_mod, "time", clock)
        cb = _make_breaker(failure_threshold=1, recovery_timeout=90)

        with pytest.raises(ValueError):
            cb.call(_fail)                      # OPEN at t=1000
        deadline_anchor = cb.get_stats().last_failure_time
        assert deadline_anchor == 1000.0

        # Hammer it with rejections across the window — none may move the anchor.
        # Four rejections at t=1010, 1020, 1030, 1040 (all inside the 90s window).
        for _ in range(4):
            clock.advance(10)
            with pytest.raises(CircuitBreakerError):
                cb.call(_ok)
            assert cb.get_stats().last_failure_time == deadline_anchor

        # Advance to the anchor + 90 (t=1090): recovery is due, probe admitted.
        clock.advance(50)                       # 1040 → 1090
        assert cb.call(_ok) == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_failed_probe_reopens_and_resets_deadline_and_releases_slot(self, monkeypatch):
        """A failed HALF_OPEN probe returns to OPEN, resets the recovery clock
        (so it doesn't immediately re-probe), and — critically — releases the
        single-probe slot so the breaker can probe again next window rather than
        wedging on ``probe in flight``."""
        clock = _FakeClock()
        monkeypatch.setattr(cb_mod, "time", clock)
        cb = _make_breaker(failure_threshold=1, recovery_timeout=90)

        with pytest.raises(ValueError):
            cb.call(_fail)                      # OPEN at t=1000
        clock.advance(90)                       # probe eligible at t=1090
        with pytest.raises(ValueError):
            cb.call(_fail)                      # probe fails → OPEN, anchor=1090
        assert cb.state == CircuitState.OPEN
        assert cb.get_stats().last_failure_time == 1090.0

        # Just after the failed probe: still OPEN, no immediate re-probe.
        clock.advance(1)                        # t=1091
        called = []
        with pytest.raises(CircuitBreakerError):
            cb.call(lambda: called.append(True))
        assert called == []
        assert cb.state == CircuitState.OPEN

        # A full window after the FAILED probe → probe admitted again (slot was
        # released by the finally-clause even though the probe raised).
        clock.advance(89)                       # t=1180 == 1090 + 90
        assert cb.call(_ok) == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_admits_single_probe_rejects_concurrent(self, monkeypatch):
        """HALF_OPEN admits exactly one probe; a concurrent caller while the
        probe is still in flight is rejected with CircuitBreakerProbeInProgress
        — no stampede against a service that only just became eligible."""
        clock = _FakeClock()
        monkeypatch.setattr(cb_mod, "time", clock)
        cb = _make_breaker(failure_threshold=1, recovery_timeout=90)

        with pytest.raises(ValueError):
            cb.call(_fail)                      # OPEN at t=1000
        clock.advance(90)                       # probe eligible

        probe_entered = threading.Event()
        release_probe = threading.Event()

        def _slow_probe() -> str:
            probe_entered.set()                 # set AFTER probe_in_flight=True
            assert release_probe.wait(timeout=5), "probe was not released"
            return "probe-ok"

        box: dict[str, object] = {}

        def _run_probe() -> None:
            box["probe"] = cb.call(_slow_probe)

        t = threading.Thread(target=_run_probe)
        t.start()
        assert probe_entered.wait(timeout=5), "recovery probe never started"

        # The single probe is now in flight (HALF_OPEN). A concurrent call is
        # rejected with the typed subclass — and never reaches the function.
        assert cb.state == CircuitState.HALF_OPEN
        concurrent_called = []
        with pytest.raises(CircuitBreakerProbeInProgress):
            cb.call(lambda: concurrent_called.append(True))
        assert concurrent_called == []

        # Let the probe finish successfully → CLOSED, slot released.
        release_probe.set()
        t.join(timeout=5)
        assert not t.is_alive(), "probe thread did not finish"
        assert box["probe"] == "probe-ok"
        assert cb.state == CircuitState.CLOSED
        assert cb._probe_in_flight is False

    def test_probe_slot_released_after_successful_probe(self, monkeypatch):
        """Sanity: the single-probe slot is cleared after a SUCCESSFUL probe too
        (not only on failure), so a later OPEN→HALF_OPEN cycle can probe again."""
        clock = _FakeClock()
        monkeypatch.setattr(cb_mod, "time", clock)
        cb = _make_breaker(failure_threshold=1, recovery_timeout=90)

        with pytest.raises(ValueError):
            cb.call(_fail)                      # OPEN
        clock.advance(90)
        assert cb.call(_ok) == "ok"             # probe succeeds → CLOSED
        assert cb._probe_in_flight is False

        # Trip and recover a second time to prove the slot really is reusable.
        with pytest.raises(ValueError):
            cb.call(_fail)                      # OPEN again
        clock.advance(90)
        assert cb.call(_ok) == "ok"
        assert cb.state == CircuitState.CLOSED
