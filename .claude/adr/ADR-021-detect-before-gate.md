# ADR-021: Detect convert dead-ends before the write-enable gate

**Status:** Proposed
**Date:** 2026-05-31
**Deciders:** Amit

## Context
In `proforma_to_invoice()`, `_check_invoice_approval_gates()` (which checks `WFIRMA_CREATE_INVOICE_ALLOWED`) runs before the series-resolution fallback chain. With the convert flag off, the function returns early, so the series check — and every other dead-end (B1–B9) — is never reached. Consequences today: (1) recovery proposals can only be created when the convert flag is on, so the recovery layer's first real exercise will be a production event; (2) the flow can't be triggered or tested with the flag off — a flag-off retry short-circuits at the gate, so a changed error proves nothing about series; (3) detection (spotting bad/missing data) is coupled to authorization (permission to write to wFirma), though they are independent concerns.

## Decision
Move dead-end detection — series resolution and the other validation checks — ahead of the write-enable gate. Build the conversion plan and run all dead-end checks, create recovery proposals on any dead-end, then check `WFIRMA_CREATE_INVOICE_ALLOWED` at the actual wFirma write boundary. The flag guards only the write, not the validation that precedes it.

## Options Considered
### Option A: Keep gate-first (status quo)
**Pros:** no change, no risk. **Cons:** recovery untestable with flag off; first real exercise is in prod; detection coupled to authorization.
### Option B: Detection-before-gate (proposed)
**Pros:** dead-ends detected and proposals created independent of the flag; recovery testable and pre-loadable before go-live; detection decoupled from authorization; the convert-on event isn't also the first-ever recovery exercise. **Cons:** does plan-building/validation work even when convert is disabled (minor compute); requires careful placement so no wFirma write can occur before the gate.

## Trade-off Analysis
B does a little throwaway work when convert is off in exchange for a testable, pre-loadable recovery layer and a safer go-live. The invariant: the gate must remain immediately before every wFirma write path, so detection-before-gate must never allow a write to slip through.

## Consequences
- Easier: testing the recovery loop with the flag off; pre-loading proposals before go-live; reasoning about detection vs authorization separately.
- Harder: must prove no wFirma write occurs in the pre-gate path (needs a test).
- Revisit: at convert go-live, confirm the gate still fences every write path.

## Action Items
1. [ ] Relocate series resolution + dead-end checks ahead of `_check_invoice_approval_gates()`.
2. [ ] Keep the flag gate immediately before the wFirma write; add a test asserting no write occurs pre-gate with the flag off.
3. [ ] Re-verify B1 (and future B2–B9) proposals are created with the flag off after the reorder.
