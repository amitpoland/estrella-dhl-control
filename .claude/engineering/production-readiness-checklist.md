# Production Readiness Checklist

This checklist is the **only** path to flipping
`carrier_dhl_live_enabled=True` in production. Every item is a
hard gate. The Production Readiness Reviewer (Opus) and the
Coordinator both sign off in writing before the flag flips.

This document does NOT cover phase-level gates — see
`promotion-gates.md`. This document covers the **production
cutover** moment specifically.

## Gate 1 — Engineering

- [ ] All campaign phases (DL-A through DL-G) merged on the
      release branch.
- [ ] Carrier suite ≥ baseline + all new tests, green at HEAD.
- [ ] `make verify` 160/160 at HEAD.
- [ ] No `TODO` / `FIXME` / `HACK` in any carrier file.
- [ ] No new module-scope adapter import outside the local-factory
      pattern (source-grep clean).
- [ ] No new credential / PDF leak surface (source-grep clean).
- [ ] Idempotency guarantee proven for `create_shipment`
      (DL-F3.5a sentinel).
- [ ] Per-AWB lock + atomic CAS on transition (DL-G).
- [ ] Schema version table + .bak snapshot helper (DL-G).

## Gate 2 — Observability

- [ ] Shadow diff dashboard live and accessible to on-call.
- [ ] Match-rate ≥ 98% over the last 7 operator-days of shadow.
- [ ] p95 live latency < 4 s over the last 7 operator-days.
- [ ] Quota counter visible on dashboard; alarm at < 50 remaining.
- [ ] All forbidden-token leak tests green
      (Authorization, documentImages, password, secret,
      account_number).
- [ ] Correlation `request_hash` present on every persisted record
      from the last 24 h of shadow runs.

## Gate 3 — Security

- [ ] IP allowlist non-empty in production `.env`.
- [ ] DHL-API-Key set in production `.env`.
- [ ] PLT path containment to `settings.storage_root` enforced
      (DL-F3.5).
- [ ] CarrierEvent.raw redacted (no full shipment dict; DL-F3.5).
- [ ] `_summarise()` redacts credentials and `documentImages`
      from DHL error echoes (DL-F3.5).
- [ ] Webhook activate handshake tested in production with the
      DHL relationship manager observing.
- [ ] Secret rotation procedure documented and exercised.

## Gate 4 — DHL account readiness (Operations)

- [ ] DHL Poland production credentials issued.
- [ ] `dhl_express_api_username`, `_password`, `_account_number`
      set in production `.env`.
- [ ] EORI on file with DHL.
- [ ] PLT enrollment confirmed by DHL relationship manager
      (signed email or formal acknowledgement).
- [ ] `paperless_trade_signature_name` constant matches the name
      Estrella registered with DHL.
- [ ] Webhook subscription configured on DHL's side, pointing at
      Estrella's production webhook URL.
- [ ] At least one test AWB issued in production sandbox-mode and
      exercised end-to-end (label printed, handed, delivered
      tracked) via the dashboard.
- [ ] Customs broker briefed on the PLT flow.

## Gate 5 — Operator readiness

- [ ] On-call operator has read this checklist.
- [ ] On-call operator has read `rollback-doctrine.md`.
- [ ] On-call operator has rehearsed Layer 1 (flag flip) in
      staging.
- [ ] On-call operator knows how to access the shadow diff
      dashboard.
- [ ] On-call operator knows the DHL operator portal URL for
      manual cancel (Layer 4 recovery).
- [ ] Operator Safety Reviewer green light: no UX path lets an
      operator accidentally trigger live shipment when intending
      shadow.

## Gate 6 — Coordinator approval

- [ ] Coordinator has reviewed all gates 1-5 and signed off.
- [ ] Production Readiness Reviewer (Opus) has independently
      reviewed and signed off.
- [ ] Cutover window scheduled; not a Friday afternoon.
- [ ] Customer-facing impact statement prepared (what does the
      shipping label arrival time SLA look like during cutover?).
- [ ] Post-cutover monitoring window assigned: 48 h with on-call
      visibility.

## Cutover procedure

When all gates are green:

1. Backup `carrier_*.db` files (Layer 3 of the rollback doctrine).
2. Edit `.env` in the production environment:
   ```
   CARRIER_DHL_LIVE_ENABLED=True
   CARRIER_DHL_SHADOW_MODE=False    # final cutover
   DHL_EXPRESS_API_STATUS=production
   ```
3. Restart workers.
4. Verify on the dashboard:
   - Adapter selection panel shows "live" not "stub".
   - Base URL shown is the production URL.
5. The first operator-driven `create_shipment` after the flag
   flip is the live signal. Watch it complete; verify the AWB
   appears in DHL's portal.
6. Post-cutover monitoring (48 h):
   - H+0 → H+4: confirm at least one live AWB lands cleanly.
   - H+4 → H+24: 4xx rate within 2× baseline; latency p95 < 4 s.
   - H+24 → H+48: p95 stays under threshold; manual check of
     a sample of live AWBs in the DHL portal vs the registry.
7. If any threshold is breached, execute the rollback doctrine
   immediately. Cutover failure is not a slow-recovery scenario.

## What this checklist does NOT cover

- Day-to-day operations after cutover (lives in the operations
  runbook, not this checklist).
- Customer comms during cutover (lives in the customer-comms
  playbook).
- Insurance / liability arrangements (lives in the legal docs).
