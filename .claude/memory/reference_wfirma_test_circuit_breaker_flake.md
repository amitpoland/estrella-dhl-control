---
name: reference_wfirma_test_circuit_breaker_flake
description: Why the wFirma registry circuit breaker leaks OPEN between tests, why the conftest reset can still be raced, and the per-suite reset_all() isolation pattern
metadata:
  type: reference
---

# wFirma test-isolation circuit-breaker flake — full closure record

Cross-referenced by `PROJECT_STATE.md` (PR #706 + #711 FACTS block). This is the
durable mechanism + remediation record so future sessions don't re-derive it.

## The breaker is a process-global singleton

`app/core/circuit_breaker.py` keeps every named breaker in a module-level
`_REGISTRY: Dict[str, CircuitBreaker]`. `get_circuit_breaker("wfirma")` returns the
SAME object for the whole process. Config: `failure_threshold=4`,
`recovery_timeout=90s` (NOT the 5/60 zoho defaults). Once 4 consecutive failures
trip it, it stays OPEN for 90s and `_http_request` short-circuits every wFirma call
with `(503, "circuit_breaker_open")` BEFORE dispatching — so even a
`patch.object(_wc, "fetch_warehouse_pz", ...)` test sees a 503/502, not its mock.

## How it leaks between tests

`test_wfirma_reservation_create.py::test_gate_blocks_when_diagnostic_unreachable`
(and any test that drives the real `_http_request` path into ≥4 connection errors)
trips the global `wfirma` breaker OPEN. With no reset, it leaks OPEN into every
later test in the session → spurious 503/502, ERROR or FAILED. Each such test
passes in isolation (breaker never tripped) — the signature of this flake class.

## The conftest reset (PR #706) and its residual race

`service/tests/conftest.py::_isolate_ai_gateway` (autouse, function scope) calls
`app.core.circuit_breaker.reset_all()` at BOTH setup and teardown, but **guarded**:
```python
_cb = sys.modules.get('app.core.circuit_breaker')
if _cb is not None:
    _cb.reset_all()
```
The guard exists so the fixture is a no-op for the 10,000+ tests that never import
the module. It covers the normal poison→victim case (any breaker-tripping test has
already imported the module, so the victim's setup reset fires).

**Residual race:** a test whose `client` fixture imports `app.main` *lazily inside
the fixture body* (e.g. `test_pz_canonical_mapping.py`) can be the FIRST in a fresh
session to pull `app.core.circuit_breaker` into `sys.modules` — AFTER
`_isolate_ai_gateway`'s setup guard has already run and skipped the reset. A breaker
left OPEN by a prior session/test then survives into that test's request.

## Remediation pattern — per-suite reset after import

When a test module imports the app lazily and exercises wFirma routes, reset the
registry breaker INSIDE the `client` fixture, AFTER `from app.main import app`:
```python
@pytest.fixture()
def client(storage):
    from app.main import app
    from app.core.circuit_breaker import reset_all
    reset_all()                     # runs post-import → guard race cannot skip it
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
```
This is deterministic and local — do NOT widen the shared conftest guard (10k+ test
blast radius). Applied to `test_pz_canonical_mapping.py` in the PR that fixes the
PR #720 GATE-4 baseline finding.

## Regression guard

`service/tests/test_conftest_registry_breaker_isolation.py` (PR #711): `test_a`
trips the `wfirma` breaker OPEN; `test_b` asserts it is CLOSED on the next test —
fails loudly if the conftest `reset_all()` is ever reverted.
