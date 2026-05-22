"""
test_circuit_breaker.py — Unit tests for the circuit breaker core module.

These tests exercise state transitions, retry logic, and registry behaviour
without making any real network calls.
"""
from __future__ import annotations

import time
import pytest

from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    ServiceConfig,
    get_circuit_breaker,
    get_all_stats,
    reset_all,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

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
