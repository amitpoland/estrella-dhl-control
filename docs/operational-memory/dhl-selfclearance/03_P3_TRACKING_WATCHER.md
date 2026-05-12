# P3 — Tracking Watcher + Arrival Follow-up Scheduler

| Field | Value |
|---|---|
| **Phase** | W-5 / P3 (combined watcher + scheduler per ADR-014) |
| **Source ADR** | ADR-014 |
| **Depends on** | P0 (foundation) + P2 (live for ≥48h) |
| **Designed** | 2026-05-12 |
| **Shadow window** | 1 week (168h) |

---

## TASK

Implement W-5 / Phase P3 — DHL self-clearance tracking watcher (continuous) + arrival-driven follow-up scheduler, in shadow mode first, then promote to live behind default-OFF flags. ADR-014 combines the watcher (P3a) and scheduler (P3b) into one logical phase.

## SCOPE BOUNDARY

- Path A only.
- Watcher monitors tracking events for shipments in `awaiting_poland_arrival`. Activates scheduler on Poland-arrival scan, customs-processing-state entry, customs-hold, delay, rejected-paperwork.
- Scheduler re-checks DHL email thread + tracking state on cadence: 2h working hours (CET 08-16, configurable), slower overnight + weekend + holidays.
- Out of scope: P2 dispatch, P4 reply build, P5 SAD trigger.

## PATH COVERAGE

Path A only. Watcher's activation list is restricted to `audit.dhl_clearance.state == "awaiting_poland_arrival"`.

## UI COMMITMENT

Minimal Mac UI — extend the read-only state pill from P2 to surface `followup_active` state + elapsed time since last DHL signal. NO operator controls to manually fire / pause the scheduler on Mac (Windows Atlas defers).

## PREREQUISITES (BLOCK if not met)

- P0 scaffolding shipped (per P2 instruction).
- P2 has shipped live AND has run shadow + live for ≥48h (real shipments in `awaiting_poland_arrival` exist in the manifest).
- `tracking_normalizer.py` extended with customs-signal vocabulary (`poland_arrival`, `customs_processing`, `customs_hold`, `delay`, `rejected_paperwork`) — P0 work.
- Policy decision on `dhl_followup_sla.py` made: P0 created `dhl_selfclearance_followup_v2.py` alongside; coordinator routes by `clearance_path` (operator decision logged in commit body).

## TEST DEPTH (hardened)

- ≥30 test cases for the tracking watcher:
  - Each new event-token classification (5 signal types)
  - Non-customs events ignored (departure, in_transit — no-op)
  - Per-AWB activation idempotency
  - DHL tracking API rate-limit response handling
  - Quota cap interaction with carrier creation
- ≥25 test cases for the scheduler:
  - Working-hours cadence (mock clock at 09:00, 12:00, 14:00 CET → tick at +2h)
  - Off-hours cadence (mock clock at 22:00 → next tick slower)
  - Livelock budget exceeded → escalates to operator review
  - State transitions out of `followup_active`:
    - → `dhl_requested_clarification` (DHL email inbound)
    - → `awaiting_sad` (SAD-direct inbound without clarification)
    - → operator review (release with no paperwork)
  - No new email thread is ever opened (hard lock 4 invariant)

## FILES TO BE MODIFIED

- `service/app/services/dhl_clearance_coordinator.py` (add `on_tracking_event` + `tick_followup` methods)
- `service/app/services/dhl_clearance_state_engine.py` (transitions out of `followup_active`)
- `service/app/services/tracking_normalizer.py` (extend signal vocabulary — P0 may have done this; verify)
- `service/app/services/dhl_selfclearance_followup_v2.py` (P0 scaffold — implement the ADR-014 cadence behaviour)
- `service/app/static/dashboard.html` (extend state pill with `followup_active` + elapsed-time read-only display; no controls)
- `service/tests/test_dhl_clearance_tracking_watcher_p3.py` (NEW)
- `service/tests/test_dhl_clearance_followup_scheduler_p3.py` (NEW)

## FILES NOT TO BE MODIFIED

- `service/app/services/dhl_reply_builder.py` (P1 / P4 territory)
- `service/app/services/dhl_proactive_dispatch_builder.py` (P2 closed)
- `service/app/services/agency_*.py` (Path B)
- `service/app/services/inventory_*.py` (P5 territory)
- `service/app/services/warehouse_db.py` (P5 territory)
- `service/app/services/carrier/*` (read-only consumer of `is_awb_stable`)
- `service/app/services/dhl_followup_sla.py` — P0 policy decision was "v2 alongside"; legacy untouched

## ACCEPTANCE CRITERIA

1. `dhl_selfclearance_p3_live_enabled` defaults to `False`. `dhl_selfclearance_p3_tracker_paused` independent pause flag exists.
2. Watcher activates scheduler ONLY on the 5 named signals. Departure / in-transit events: no-op.
3. Scheduler cadence respects working-hours config (`selfclearance.followup.working_interval_sec`, `.offhours_interval_sec`, `.working_hours_window`).
4. Livelock budget honored: after `selfclearance.followup.livelock_budget_hours`, scheduler escalates shipment to operator review state.
5. No new email thread opened in any test (verify by grep — reply functions always pass `thread_id` from manifest).
6. Shadow mode: signal classification logged; scheduler ticks logged; no state transition out of `awaiting_poland_arrival` without explicit shadow→live flag flip.
7. Legacy `dhl_followup_sla.py` untouched; tests for that service unchanged.
8. `make verify`: 160/160 unchanged. `pytest -k "p3 or tracker or followup"` → green.

## SHADOW→LIVE PROMOTION GATE

- Shadow window: 1 week (168h) continuous on live shipment volume.
- Required evidence:
  - 0 DHL tracking-API rate-limit violations
  - 0 mail-account quota breaches
  - Signal classifier ≥98% precision/recall on labelled set ≥200 events
  - Livelock-budget escalation fired correctly in ≥1 synthetic test in shadow
  - ≥1 weekend transition observed without scheduler regression
- Reviewer sign-off:
  - Operator Safety Reviewer
  - Carrier Ops Reviewer (subagent + named human)
  - Backend Safety Reviewer
- Promotion: flip `dhl_selfclearance_p3_live_enabled=True` via admin runtime-flags endpoint; `shadow_mode=False` on the scheduler.

## ROLLBACK PROCEDURE

- Flip `dhl_selfclearance_p3_live_enabled=False` via admin endpoint (restartless).
- For rate-limit incident only: flip `dhl_selfclearance_p3_tracker_paused=True` independently (preserves scheduler state).
- In-flight shipments in `followup_active` fall back to manual operator follow-up.
- No data migration. No manifest cleanup needed.

## CONSTRAINTS

- No code edits to `dhl_proactive_dispatch_builder.py` (P2 closed).
- No code edits to `agency_*.py`.
- Hard lock 4 (one thread per AWB) is binding: never queue an email without `thread_id` from manifest.
- Honor `engineering_discipline_rules.md`: error responses templated, no raw exceptions.
- Honor Windows Atlas memory: no operator controls on Mac UI.

## ESCALATION CRITERIA

- DHL changes a tracking event name (token vocabulary breaks).
- DHL tracking API quota cap is exhausted by P3 polling.
- The `dhl_followup_sla.py` policy reconciliation surfaces an active legacy customer or test depending on the old cadence.
- Livelock budget value contested by Customs Compliance Reviewer.

## FINAL REPORT

Same 9-section shape as P2.
