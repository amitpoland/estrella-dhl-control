# Inspection — "Resolve mapping" gateway error on proforma `EJL/26-27/453`: wFirma circuit breaker stuck OPEN (recovery path unreachable)

**Date:** 2026-07-30
**Trigger:** Operator report — proforma-detail for invoice `EJL/26-27/453` blocks Approve/Post/Convert/Export because `EJL/26-27/453-1`, `-2`, `-3` have no `wfirma_product_id`; clicking **Resolve mapping** returns *"wFirma is temporarily unavailable (gateway error). Wait a moment, then click Resolve mapping to retry."*
**Scope:** read-only diagnosis (Part A of plan `hat-s-blocking-2-synchronous-cake.md`). No production mutation performed.

---

## Verdict

The blocker on `EJL/26-27/453` is **correct and must stay** (Lesson N #7 — a billed `product_code` with no wFirma good-id is a true fiscal blocker). The failing part is the **remedy path** (Resolve mapping), and its live cause is:

> **The wFirma circuit breaker has been stuck OPEN since 2026-07-30 01:44:01 and will NOT self-recover.** It was tripped by a transient burst of `ConnectTimeoutError`s to `api2.wfirma.pl:443`, but it stays open because the breaker's 90s auto-recovery path is **unreachable** through `wfirma_client._http_request`. The network path to wFirma is healthy again (direct TLS connect succeeds), so a **PZService restart** will immediately clear it.

This is **NOT** missing credentials, **NOT** a defect in the readiness gate, and **NOT** a genuinely-absent product. Retry advice is ineffective *while the breaker is stuck* — the true remedy is a service restart (and a code fix so the breaker auto-recovers).

---

## Evidence (production log `C:\PZ\logs\pz_stdout.log`, span 2026-07-28 18:12 → 2026-07-30 16:46)

**1. Exactly one breaker transition in ~46h of log:**
```
2026-07-30 01:44:01,639  WARNING  app.core.circuit_breaker  circuit[wfirma] → OPEN after 4 consecutive failures
```
Zero `→ HALF_OPEN`, zero `→ OPEN (probe failed)`, zero force-close/close.

**2. What tripped it (01:43:28–01:44:01):** the `wfirma_payment_sync_processor` scheduler hit 4 consecutive real connect timeouts:
```
01:43:28  payments/find … Max retries exceeded … ConnectTimeoutError(api2.wfirma.pl:443)
01:43:39  payments/find … ConnectTimeoutError(api2.wfirma.pl:443)
01:43:50  payments/find … ConnectTimeoutError(api2.wfirma.pl:443)
01:44:01  payments/find … ConnectTimeoutError(api2.wfirma.pl:443)   → breaker OPEN
```

**3. Fast-fail ever since — no recovery attempt:** **3,704** `wfirma circuit OPEN — request rejected` lines, continuous from `01:44:01,647` (8 ms after open) to `16:46:58,407` (15 hours). Every wFirma call in that window returned `503 circuit_breaker_open` without contacting wFirma.

**4. Zero genuine upstream contact after the open:** grep for `api2.wfirma.pl | ConnectTimeout | Max retries | HTTPSConnectionPool` after line 45529 = **0 matches**. (The `wFirma status=TOTAL REQUESTS LIMIT EXCEEDED` lines are from **2026-07-28 21:41**, an unrelated earlier rate-limit event.)

**5. Network healthy now:** direct `curl`/TLS connect to `api2.wfirma.pl:443` returns HTTP 200, connect ~0.04s, DNS → 46.248.166.9.

---

## Root cause of the stuck-open (confirmed code defect)

`service/app/services/wfirma_client.py::_http_request` (line ~500):
```python
if breaker.state.value == "open":
    log.warning("wfirma circuit OPEN — request rejected (%s %s/%s)", …)
    return 503, "circuit_breaker_open"          # ← bails BEFORE breaker.call()
...
return breaker.call(_do_request)                # ← only reached when NOT open
```
`service/app/core/circuit_breaker.py`:
- `.state` property (line 128) returns `self._state` under the lock and **does not** call `_maybe_transition()`.
- `_maybe_transition()` (line 164) is the **only** place OPEN→HALF_OPEN happens (after `recovery_timeout`), and it is called **only** from `call()` (line ~110).

**Consequence:** while OPEN, `_http_request` reads the plain `.state` property and returns `503` before ever reaching `breaker.call()`. `_maybe_transition()` therefore never runs, the 90s `recovery_timeout` is never evaluated, and the circuit stays OPEN **forever** until the process restarts. The auto-recovery is effectively dead code for the wFirma breaker. Any transient wFirma blip that trips the breaker wedges **all** wFirma functionality (payment sync, contractor lookup, goods lookup, PZ, proforma resolve-mapping) until an operator restarts `PZService`.

---

## Remedies

### Immediate (operator — HOLD: production service restart)
Restart `PZService`. The breaker re-initialises CLOSED; since the network path is healthy, wFirma calls resume immediately and Resolve mapping works. No safer in-process lever exists (no breaker-reset endpoint is exposed).

### After the breaker clears — resolving the three codes
If `EJL/26-27/453-1/-2/-3` are genuinely not present in wFirma, clearing the blocker requires **Create & adopt**, a live fiscal write gated by `WFIRMA_CREATE_PRODUCT_ALLOWED` — **operator HOLD** (I stop and report before any wFirma write).

### Code fix (GATE-4 finding — see below)
Make the breaker auto-recover: either drop the `.state`-property short-circuit and let `breaker.call()` raise `CircuitBreakerError` (which runs `_maybe_transition()` first), or have an explicit `allow_request()` that runs the transition under the lock, or make the `.state` read run `_maybe_transition()`. Any of these restores the 90s recovery. This belongs in **its own PR** — `circuit_breaker.py` is shared resilience infra used by every external integration (wFirma, DHL, …); it must not be folded into the unrelated error-classification PR #1040.

---

## GATE-4 disposition

**Finding:** wFirma circuit breaker recovery path is unreachable (`wfirma_client` `.state` fast-path bypasses `_maybe_transition()`) → permanent stuck-OPEN on any transient failure until restart. **Confirmed** (not benign flapping).

**Disposition:** SCHEDULED — dedicated fix PR against `circuit_breaker.py` + `wfirma_client.py` with a regression test that (a) opens a breaker, (b) advances a fake clock past `recovery_timeout`, (c) asserts the next wFirma request probes (HALF_OPEN) instead of fast-failing. Operator may elect ISSUE instead (public repo → sanitise contractor_ids / `company_id` before any GitHub post).

**Relationship to PR #1040 (Part B):** #1040's `unavailable_503` message ("wait ~1 min, then retry") is accurate **once** the breaker auto-recovers. Land the breaker-recovery fix so that advice becomes true; keep #1040's message. Do not rewrite #1040 to say "ask an operator to restart" — that would bake in the assumption that the recovery bug is permanent.
