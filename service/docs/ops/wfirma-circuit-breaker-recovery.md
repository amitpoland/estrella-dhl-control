# wFirma circuit breaker — stuck-OPEN recovery

**Incident:** 2026-07-30. The wFirma circuit breaker tripped OPEN at 01:44 and stayed
OPEN for ~15 hours, fast-failing 3,704 requests with zero recovery attempts, until
`PZService` was restarted. Every wFirma operation (contractor lookup, product resolve,
PZ preview, "Resolve mapping" on proforma drafts) returned `503 circuit_breaker_open`
the entire time — even though wFirma itself was healthy again within minutes.

**Root cause — split admission authority.** `wfirma_client._http_request` read the
breaker's raw `.state` and returned the OPEN fallback *before* ever calling
`breaker.call()`:

```python
# BEFORE (defective):
if breaker.state.value == "open":
    return 503, "circuit_breaker_open"      # returns here — call() never runs
return breaker.call(_do_request)
```

The OPEN→HALF_OPEN recovery transition lives **only** inside `CircuitBreaker.call()`
(via `_maybe_transition()`). Reading `.state` is a plain getter — it never evaluates the
recovery timeout. So once the client took the `.state == "open"` fast path, `call()` was
never reached, the 90-second recovery deadline was never checked, and the breaker could
never move to HALF_OPEN to probe wFirma. Only a process restart (which rebuilds the
in-memory breaker CLOSED) cleared it. This was not a missing timer — the timer existed
and was correct; it was **unreachable** because admission authority was duplicated
between the caller and the state machine.

## The fix

`CircuitBreaker.call()` is now the **sole admission authority**. All request admission
flows through it; no caller gates on raw `.state`.

- `_http_request` calls `breaker.call(_do_request)` unconditionally and translates the
  typed result into the existing `(status, body)` contract:
  - `CircuitBreakerError` (OPEN, or HALF_OPEN concurrent-probe rejection) →
    `(503, "circuit_breaker_open")` — the same fallback shape as before, so every
    `status, body = _http_request(...)` call site is unaffected.
  - `requests.RequestException` → `ConnectionError` (unchanged).
- The PDF-fetch path had the same `.state` fast-path; it now also routes through
  `breaker.call()` and raises `RuntimeError("wFirma circuit open — PDF fetch
  unavailable")` on `CircuitBreakerError`.
- Header construction (`_headers_for_module`) now runs **before** admission so behaviour
  is uniform across CLOSED/OPEN paths.

Because admission goes through `call()`, an OPEN breaker whose `recovery_timeout` (90 s
for wFirma) has elapsed transitions to HALF_OPEN and admits **one** probe request to
wFirma. A successful probe closes the circuit (`HALF_OPEN → CLOSED`); a failed probe
reopens it and resets the recovery deadline (`HALF_OPEN → OPEN`).

### HALF_OPEN single-probe concurrency

Recovery must not let a burst of queued callers stampede a service that has only just
become eligible to retry. `call()` admits exactly one probe: under the lock it sets
`_probe_in_flight = True` for the admitted caller and raises
`CircuitBreakerProbeInProgress` (a `CircuitBreakerError` subclass, so existing fallback
handlers are unaffected) for any concurrent caller. The slot is cleared in a `finally`
guarded by the local `admitted_probe`, so a failed or crashing probe can never wedge
HALF_OPEN in permanent "probe in flight" rejection.

## The invariant (do not regress)

> **Never gate a request on the breaker's raw `.state`. All admission must go through
> `CircuitBreaker.call()`.**

A `.state` read never runs `_maybe_transition()`. Any code path that short-circuits on
`.state == OPEN` and returns before `call()` reintroduces this exact stuck-OPEN defect.
`.state` / `get_stats()` / `get_all_stats()` remain fine for **telemetry and display** —
just never for admission decisions. Regression pins:

- `service/tests/test_circuit_breaker.py::TestRecoveryTimeoutFakeClock` — deterministic
  fake-clock proof of OPEN→HALF_OPEN→CLOSED recovery, deadline behaviour on rejected
  calls, and single-probe concurrency (no real sleeps).
- `service/tests/test_circuit_breaker_wrapper_contracts.py` —
  `test_wfirma_client_rejects_while_open_before_recovery` (OPEN pre-recovery still
  fast-fails without contacting wFirma) and `test_wfirma_client_probes_after_recovery_timeout`
  (post-recovery request reaches wFirma through `call()` and closes the circuit).

## Operator guidance

- **A wFirma breaker OPEN is now self-healing.** After `recovery_timeout` (90 s) the next
  request probes wFirma automatically; no restart is required to recover. Restart is no
  longer the remedy for a stuck breaker — it was only ever masking the unreachable-timeout
  bug.
- **What tripped it still matters.** Recovery does not explain the *cause*. When a breaker
  opens, check the service log for the preceding `circuit[wfirma] → OPEN after N
  consecutive failures` line and the failures before it (network, wFirma 5xx, rate-limit).
- **Transition evidence** is logged for every edge: `→ OPEN`, `→ HALF_OPEN (recovery
  probe)`, `→ CLOSED (recovered)`, `→ OPEN (probe failed)`, plus OPEN rejections and
  concurrent-probe rejections. Grep `circuit[wfirma]` in the service log to reconstruct a
  recovery timeline.

## Known related latent bug (separate campaign)

`cliq_service.py:278` (the `zoho_cliq` breaker) has the **same** `.state` fast-path
pattern and the same latent stuck-OPEN risk. It is out of scope for this PR and filed as a
GATE-4 finding for a separate campaign — do not fold it in here (one isolated PR must be
revertable on its own).
