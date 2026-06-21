"""Regression pin: conftest must reset registry circuit breakers between tests.

The autouse ``_isolate_ai_gateway`` fixture in conftest.py resets BOTH the
ai_gateway breakers AND the process-global registry breakers in
``app.core.circuit_breaker`` (wfirma, dhl, zoho_*) at setup and teardown.

Before that registry reset existed, a breaker tripped OPEN in one test leaked
OPEN into later tests: wFirma re-probes then returned a spurious
``circuit_breaker_open`` 503 -> DIAGNOSTIC_FAILED.  test_wfirma_reservation_create.py
ran 18 failed / 9 passed as a full file while every test passed in isolation
(poison source: its ``test_gate_blocks_when_diagnostic_unreachable``, which trips
the "wfirma" breaker by failing >= failure_threshold probes inside breaker.call).

The two tests below reproduce the cross-test leak deterministically: the first
trips the shared "wfirma" registry breaker OPEN and leaves it that way; the
second asserts it is CLOSED on entry.  They rely on pytest's default
definition-order execution and run consecutively within this module.  Remove the
conftest registry reset and ``test_b`` fails — that is the regression this file
guards against.
"""
import sys

from app.core import circuit_breaker as cb

_BREAKER = "wfirma"  # the registry breaker that caused the original leak


def test_a_trips_registry_breaker_open():
    """Trip the shared "wfirma" registry breaker OPEN and leave it OPEN."""
    breaker = cb.get_circuit_breaker(_BREAKER)
    breaker.force_open()
    assert breaker.state is cb.CircuitState.OPEN
    # Importing the module above guarantees the conftest guard
    # (sys.modules.get('app.core.circuit_breaker')) sees it and fires.
    assert sys.modules.get("app.core.circuit_breaker") is not None


def test_b_registry_breaker_closed_for_next_test():
    """The autouse conftest fixture must reset the breaker between tests."""
    breaker = cb.get_circuit_breaker(_BREAKER)
    assert breaker.state is cb.CircuitState.CLOSED, (
        "registry 'wfirma' breaker leaked OPEN from a prior test — the "
        "_isolate_ai_gateway autouse fixture is not resetting registry breakers"
    )
