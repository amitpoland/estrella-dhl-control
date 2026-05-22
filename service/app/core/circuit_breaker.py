"""
circuit_breaker.py — Resilience patterns for external API integrations.

Provides circuit breaker protection for DHL Express, Zoho APIs, and wFirma ERP.
Uses in-memory state with configurable failure thresholds and recovery timers.

States:
    CLOSED    — normal operation; calls pass through
    OPEN      — failing; calls are rejected immediately, fallback used
    HALF_OPEN — recovery probe; one call allowed through to test the service

Usage:
    breaker = get_circuit_breaker("zoho_cliq")
    try:
        result = breaker.call(my_func, arg1, arg2)
    except CircuitBreakerError:
        # service is down — use fallback
        result = my_fallback()
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

from .logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


# ── States ────────────────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class ServiceConfig:
    """Per-service circuit breaker configuration."""
    name:               str
    failure_threshold:  int   = 5    # consecutive failures before opening
    recovery_timeout:   int   = 60   # seconds before attempting HALF_OPEN probe
    call_timeout:       int   = 15   # per-call timeout injected into requests
    retry_attempts:     int   = 2    # retries before counting as a failure


# ── Stats ─────────────────────────────────────────────────────────────────────

@dataclass
class CircuitStats:
    state:             CircuitState
    failure_count:     int
    success_count:     int
    total_calls:       int
    last_failure_time: float
    last_success_time: float


# ── Errors ────────────────────────────────────────────────────────────────────

class CircuitBreakerError(Exception):
    """Raised when the circuit is OPEN and no fallback is registered."""


# ── Core circuit breaker ──────────────────────────────────────────────────────

class CircuitBreaker:
    """Thread-safe circuit breaker with automatic state transitions."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config           = config
        self._state           = CircuitState.CLOSED
        self._failure_count   = 0
        self._success_count   = 0
        self._total_calls     = 0
        self._last_failure    = 0.0
        self._last_success    = 0.0
        self._lock            = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute *func* with circuit breaker protection.

        Raises CircuitBreakerError if the circuit is OPEN.
        Propagates the original exception if the call fails.
        """
        with self._lock:
            self._total_calls += 1
            self._maybe_transition()

            if self._state == CircuitState.OPEN:
                log.warning(
                    "circuit[%s] OPEN — rejecting call to %s",
                    self.config.name,
                    getattr(func, "__name__", repr(func)),
                )
                raise CircuitBreakerError(
                    f"Circuit breaker is open for service '{self.config.name}'"
                )

            if self._state == CircuitState.HALF_OPEN:
                log.info(
                    "circuit[%s] HALF_OPEN — probing recovery",
                    self.config.name,
                )

        # Execute outside the lock so other threads aren't blocked during I/O
        try:
            result = self._execute(func, *args, **kwargs)
            self._on_success()
            return result
        except CircuitBreakerError:
            raise
        except Exception:
            self._on_failure()
            raise

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    def get_stats(self) -> CircuitStats:
        with self._lock:
            return CircuitStats(
                state             = self._state,
                failure_count     = self._failure_count,
                success_count     = self._success_count,
                total_calls       = self._total_calls,
                last_failure_time = self._last_failure,
                last_success_time = self._last_success,
            )

    def force_open(self) -> None:
        """Manually open the circuit (for testing or operator override)."""
        with self._lock:
            self._state        = CircuitState.OPEN
            self._last_failure = time.time()
        log.warning("circuit[%s] force-opened by operator", self.config.name)

    def force_close(self) -> None:
        """Manually close the circuit and reset counters."""
        with self._lock:
            self._state         = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
        log.info("circuit[%s] force-closed by operator", self.config.name)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _maybe_transition(self) -> None:
        """Called inside the lock — decide if state should change."""
        now = time.time()

        if self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                log.warning(
                    "circuit[%s] → OPEN after %d consecutive failures",
                    self.config.name, self._failure_count,
                )

        elif self._state == CircuitState.OPEN:
            if now - self._last_failure >= self.config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                log.info(
                    "circuit[%s] → HALF_OPEN (recovery probe)",
                    self.config.name,
                )

    def _execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run with simple retry logic (no tenacity dependency)."""
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < self.config.retry_attempts:
                    wait = min(2 ** (attempt - 1), 8)  # 1s, 2s, 4s …
                    log.debug(
                        "circuit[%s] attempt %d/%d failed (%s) — retrying in %ds",
                        self.config.name, attempt, self.config.retry_attempts,
                        type(exc).__name__, wait,
                    )
                    time.sleep(wait)

        assert last_exc is not None
        raise last_exc

    def _on_success(self) -> None:
        with self._lock:
            self._success_count += 1
            self._last_success   = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state         = CircuitState.CLOSED
                self._failure_count = 0
                log.info("circuit[%s] → CLOSED (recovered)", self.config.name)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure   = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                log.warning(
                    "circuit[%s] → OPEN (probe failed)",
                    self.config.name,
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.config.failure_threshold
            ):
                self._state = CircuitState.OPEN
                log.warning(
                    "circuit[%s] → OPEN after %d consecutive failures",
                    self.config.name, self._failure_count,
                )


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY:      Dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK: threading.Lock            = threading.Lock()

# Known service defaults — tuned per service characteristics
_SERVICE_DEFAULTS: Dict[str, ServiceConfig] = {
    "dhl": ServiceConfig(
        name              = "dhl",
        failure_threshold = 3,
        recovery_timeout  = 120,   # DHL is slow to recover
        call_timeout      = 30,    # DHL calls can be slow
        retry_attempts    = 2,     # strict rate limits
    ),
    "zoho_cliq": ServiceConfig(
        name              = "zoho_cliq",
        failure_threshold = 5,
        recovery_timeout  = 60,
        call_timeout      = 15,
        retry_attempts    = 3,
    ),
    "zoho_workdrive": ServiceConfig(
        name              = "zoho_workdrive",
        failure_threshold = 5,
        recovery_timeout  = 60,
        call_timeout      = 30,    # file uploads take time
        retry_attempts    = 2,
    ),
    "zoho_mail": ServiceConfig(
        name              = "zoho_mail",
        failure_threshold = 5,
        recovery_timeout  = 60,
        call_timeout      = 15,
        retry_attempts    = 3,
    ),
    "wfirma": ServiceConfig(
        name              = "wfirma",
        failure_threshold = 4,
        recovery_timeout  = 90,    # ERP systems slower to recover
        call_timeout      = 20,
        retry_attempts    = 2,
    ),
}


def get_circuit_breaker(
    service_name: str,
    config: Optional[ServiceConfig] = None,
) -> CircuitBreaker:
    """Return the singleton CircuitBreaker for *service_name*, creating it if needed."""
    with _REGISTRY_LOCK:
        if service_name not in _REGISTRY:
            resolved = config or _SERVICE_DEFAULTS.get(
                service_name, ServiceConfig(name=service_name)
            )
            _REGISTRY[service_name] = CircuitBreaker(resolved)
        return _REGISTRY[service_name]


def get_all_stats() -> Dict[str, CircuitStats]:
    """Return stats snapshot for every registered circuit breaker."""
    with _REGISTRY_LOCK:
        return {name: cb.get_stats() for name, cb in _REGISTRY.items()}


def reset_all() -> None:
    """Force-close every registered circuit breaker (for testing)."""
    with _REGISTRY_LOCK:
        for cb in _REGISTRY.values():
            cb.force_close()
    log.info("All circuit breakers reset to CLOSED")


# ── Decorator ─────────────────────────────────────────────────────────────────

def with_circuit_breaker(
    service_name: str,
    fallback: Optional[Callable[..., Any]] = None,
) -> Callable:
    """Decorator that wraps a function with circuit breaker protection.

    Example::

        @with_circuit_breaker("zoho_cliq", fallback=lambda *a, **kw: False)
        def post_to_cliq(text: str) -> bool:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            breaker = get_circuit_breaker(service_name)
            try:
                return breaker.call(func, *args, **kwargs)
            except CircuitBreakerError:
                if fallback is not None:
                    log.info(
                        "circuit[%s] using fallback for %s",
                        service_name, func.__name__,
                    )
                    return fallback(*args, **kwargs)
                raise
        return wrapper
    return decorator
