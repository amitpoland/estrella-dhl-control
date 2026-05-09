# Promotion Gates

Every phase ships through gates. A phase that fails any gate stops;
the cell convenes to diagnose; no Phase N+1 fires until N is green.

## Phase-level gates (every phase)

A phase is approved for merge when **all** of the following are true:

1. **Tests green at HEAD.** Carrier suite count ≥ baseline + new tests.
   `make verify` exits 0 (currently 160/160).
2. **No default flag flipped.** `grep "default=False"` on the four
   carrier feature flags in `service/app/core/config.py` returns the
   same set as before the phase.
3. **No new TODOs / FIXMEs / HACKs** in any file the phase touched.
4. **No new module-scope adapter imports** outside the local-factory
   pattern. Source-grep on every route file enforces this.
5. **No new credential / PDF leak surface.** Source-grep on
   `print(`, `log.`, `logger.` near `Authorization`, `documentImages`,
   `password`, `secret`, `account_number` returns the same set as
   before.
6. **No new env reads** in service modules (adapters, coordinator,
   state engine). Settings are read at the route or factory layer
   only.
7. **Live-AWB-never-in-registry invariant holds.** The end-to-end
   sentinel test passes.
8. **No squash-merge.** Phase commit is a single discrete commit on
   the campaign branch.
9. **Reviewer sign-off:** QA Lead green, Security Reviewer green,
   Release Manager green. None of the three is the same agent that
   implemented the phase (no-self-approval).
10. **ADR review.** If the phase introduces an architectural change
    not covered by an existing ADR, the ADR Historian drafts a new
    one before merge.

## Phase-level promotion sequence

```
Phase N implementation diff
        │
        ├──► QA Lead runs full focused + carrier-suite + make verify
        │       └─ all green? continue, else block.
        │
        ├──► Security Reviewer source-greps the diff
        │       └─ no new leak surface? continue, else block.
        │
        ├──► Release Manager checks gates 1-10
        │       └─ all gates green? continue, else block.
        │
        └──► Coordinator approves Phase N+1 fire
                └─ otherwise convene cell, no Phase N+1 until resolved.
```

## Production readiness gate (live cutover)

A separate, stricter gate when flipping `carrier_dhl_live_enabled=True`.
**The Production Readiness Reviewer (Opus) holds blocking authority
in addition to the Coordinator.**

Required before flag flip:

1. **All phase gates green** for every phase from DL-A through DL-G.
2. **DHL Poland account readiness verified** — production credentials
   issued, account number confirmed, EORI on file, signature name
   matches `_PLT_DEFAULT_SIGNATURE_NAME`, PLT enrollment confirmed
   by DHL relationship manager.
3. **Sandbox shadow run logged for ≥ 1 operator-week** with
   match-rate ≥ 98%, p95 live latency < 4 s, no diff_outcome=
   `stub_only_error` rows.
4. **Production shadow run logged for ≥ 1 operator-week** with the
   same thresholds.
5. **IP allowlist non-empty** in production `.env`. Webhook routes
   defended by IP gate.
6. **Rollback dry-run** — flip the flag back to `False` in a staging
   environment under simulated load; confirm < 5 s recovery time.
7. **Operator runbook reviewed** — the operator who will be on call
   has read the rollback doctrine and confirmed acknowledgment.
8. **Customs Compliance Reviewer green light** — Estrella's customs
   broker has reviewed the PLT signature flow.
9. **Operator Safety Reviewer green light** — no UX path lets an
   operator accidentally trigger a live shipment when they intend
   shadow.
10. **Coordinator + Production Readiness Reviewer joint approval
    captured in writing.**

Any single missing item blocks the cutover. No exceptions.

## Hot-fix exception

A P0 security finding **after** a phase has merged but **before**
the next phase fires may bypass the no-self-approval rule with
explicit Coordinator approval and an ADR explaining the bypass.
This exception is logged in the rollback doctrine.
