# P2 — Proactive Customs Dispatch

| Field | Value |
|---|---|
| **Phase** | W-5 / P2 |
| **Source ADR** | ADR-013 |
| **Depends on** | P0 (foundation scaffolding merged) |
| **Designed** | 2026-05-12 |
| **Shadow window** | 48 hours continuous |

---

## TASK

Implement W-5 / Phase P2 — DHL self-clearance proactive customs dispatch, in shadow mode first, then promote to live behind a default-OFF flag.

## SCOPE BOUNDARY

- Path A (under USD 2500 self-clearance) ONLY. Path B (over 2500 agency_clearance) must be hard-skipped at the coordinator entrypoint.
- Triggers the proactive customs email send when AWB is stable AND scope-gate is open.
- Out of scope: P3 tracking watcher, P4 clarification handling, P5 SAD trigger. Those are separate sessions.

## PATH COVERAGE

Path A only. Coordinator must call `is_dhl_self_clearance(audit["clearance_decision"]["clearance_path"])` and raise `OutOfScopeError` on Path B.

## UI COMMITMENT

Minimal Mac UI only — emit observability events to existing timeline + audit; surface a single read-only status pill on `BatchDetailPage` showing current self-clearance state. **Full operator control UI is deferred to Windows Atlas** per the 2026-05-12 strategic decision (memory: `windows_atlas_ui_primary_2026-05-12.md`). Do NOT build proactive-dispatch trigger buttons, override controls, or operator-facing reply forms on Mac.

## PREREQUISITES (BLOCK if not met)

- P0 scaffolding shipped: `dhl_clearance_state_engine.py` exists, `dhl_clearance_coordinator.py` exists, manifest namespace `audit.dhl_clearance.*` exists, 6 config flags exist (default-OFF), intent classifier scaffold exists, per-thread reply lock primitive exists. Verify by grep before any code edit.
- `service/app/services/carrier/coordinator.py` has `is_awb_stable(awb)` method exists and is green-tested.

## TEST DEPTH (hardened)

- Add ≥40 test cases covering:
  - AWB-stable signal positive/negative branches
  - Scope-gate positive/negative (Path A vs Path B)
  - Idempotency (second call for same AWB is no-op)
  - Manifest write completeness (`message_id`, `recipient`, `timestamp`, content `sha256`)
  - Shadow mode (flag OFF or `shadow_mode=True` → build + log, don't send)
  - Live mode (flag ON and `shadow_mode=False` → send via `email_service.queue_email`)
  - Error path (state remains `awaiting_preemptive_send` if send fails; state advances to `dispatch_failed` if scope-gate becomes invalid mid-flow)
  - Default-OFF discipline (flag absent → no send)
- Shadow tests must verify the email payload would have been semantically correct (recipient = `odprawacelna@dhl.com`, subject format, attachments include AWB + invoice + Polish Description + clearance-type instruction per `docs/dhl_clearance_paths.md` A2a row).
- Test fixture: synthetic Path A shipment audit + label-printed AWB.

## FILES TO BE MODIFIED

- `service/app/services/dhl_proactive_dispatch_builder.py` (existing 237 lines — keep API; ensure manifest write hook + AWB-stable gate)
- `service/app/services/dhl_clearance_coordinator.py` (P0 scaffold; add `dispatch_proactive(batch_id)` entrypoint)
- `service/app/services/dhl_clearance_state_engine.py` (P0 scaffold; add transitions `awaiting_preemptive_send → awaiting_poland_arrival` on success, `→ dispatch_failed` on error)
- `service/app/api/routes_dhl_clearance.py` (optional: add a read-only `GET /api/v1/dhl-clearance/state/{batch_id}` so dashboard pill can read state — no write surface)
- `service/app/static/dashboard.html` (minimal: read-only state pill on `BatchDetailPage` Overview, behind a new testid `data-testid="selfclearance-state-pill"` + read-only fetch of new GET route; NO write buttons)
- `service/tests/test_dhl_proactive_dispatch_p2.py` (NEW — test matrix above)
- `service/tests/test_dhl_clearance_state_engine_p2.py` (NEW — state transitions specific to P2)

## FILES NOT TO BE MODIFIED

- `service/app/services/dhl_reply_builder.py` (P1 reactive path; out of scope)
- `service/app/services/agency_*.py` (Path B; explicitly forbidden by ADR-012 hard lock 3)
- `service/app/services/dhl_followup_sla.py` (P3/P4 territory; out of scope here — but if P0 deprecated it, this instruction honors that)
- `service/app/services/inventory_state_engine.py` (P5 territory; ADR-012 hard lock 2 means no inventory mutation in P2)
- `service/app/services/warehouse_db.py` (P5 territory; PZ trigger not in P2)
- Any `service/app/services/carrier/*` (carrier subsystem; P2 only reads `is_awb_stable()`)

## ACCEPTANCE CRITERIA (testable)

1. `config.dhl_selfclearance_p2_live_enabled` defaults to `False`.
2. With flag OFF: builder runs, manifest writes `audit.dhl_clearance.p2_dispatch.{shadow:true, message_id_candidate, recipient, sent_at:null, content_sha256}`; `email_service` NOT called.
3. With flag ON + `shadow_mode=False`: `email_service.queue_email` called exactly once per AWB; manifest writes `audit.dhl_clearance.p2_dispatch.{shadow:false, message_id, recipient, sent_at, content_sha256}`; state transitions to `awaiting_poland_arrival`.
4. With Path B audit (`clearance_path=agency_clearance`): `OutOfScopeError` raised; no email sent; no manifest write.
5. With AWB-unstable: builder no-ops; state stays at `awaiting_preemptive_send`.
6. Second call with same AWB after successful first call: no-op (idempotency); no second email; manifest unchanged.
7. All targeted tests pass; `pytest -k "p2 or proactive"` → green; `make verify` → 160/160 unchanged.
8. `dashboard.html`: state pill renders correctly for state ∈ {`awaiting_preemptive_send`, `awaiting_poland_arrival`, `dispatch_failed`, `n/a`}; reads from new GET route; no writes.

## SHADOW→LIVE PROMOTION GATE

- Shadow window: 48 hours continuous on live shipment volume with flag ON + `shadow_mode=True`.
- Required evidence:
  - ≥50 shadow dispatches across ≥10 distinct AWBs
  - 0 duplicate sends per AWB
  - 0 dispatches where `is_awb_stable` was False
  - 100% of shadow payloads pass operator-review spot-check (≥10 spot-checked manually)
  - manifest hashes match a replay-rebuild
- Reviewer sign-off required (all named):
  - Customs Compliance Reviewer (subagent + named human review — Tejal primary)
  - Operator Safety Reviewer
  - Backend Safety Reviewer (post-implementation pass)
- Promotion: flip `shadow_mode=False` via admin runtime-flags endpoint (flag stays ON). Operator approval recorded in audit log entry.

## ROLLBACK PROCEDURE

- Flip `dhl_selfclearance_p2_live_enabled=False` via admin runtime-flags endpoint (restartless).
- In-flight shipments in `awaiting_preemptive_send` fall back to manual operator dispatch (existing UI / API path remains compiled in).
- Manifest records remain intact for audit reconstruction.
- No data migration needed.

## CONSTRAINTS

- Do NOT touch `main` directly. New branch, PR-only.
- Default-OFF per ADR-010.
- Do NOT modify `dhl_followup_sla.py`, `agency_*.py`, `inventory_*.py`, `warehouse_db.py`.
- Do NOT add operator-facing write buttons on Mac dashboard (Windows Atlas memory rule).
- Honor `engineering_discipline_rules.md` memory: any new error path on `routes_dhl_clearance.py` must template-format error details (`error_code` + `field` + `hint`) — NEVER raw exception strings.
- Doc-vs-code consistency: if this PR touches `docs/dhl_clearance_paths.md` Path A row, run a re-read consistency check before merge.

## ESCALATION CRITERIA (true business decisions only)

- DHL's customs mailbox address has changed (config update).
- AWB-stable definition is contested between carrier-state-engine intent and DHL contract-of-carriage void rules.
- Path A shipments are mixing with Path B audit entries in unexpected ways (data quality issue).
- Customs Compliance Reviewer flags the customs-type instruction ("release for free circulation" Polish default) as incorrect for any shipment class.

## FINAL REPORT SHAPE (9 sections)

1. Understanding
2. Agents activated (≥3 distinct)
3. What Was Implemented
4. Test results (targeted + full dashboard + make verify)
5. Shadow log analysis (after the 48h window)
6. Operator review evidence (≥10 spot-checks)
7. STATUS: SHADOW-COMPLETE / LIVE / BLOCKED with reasons
8. Assumptions made
9. Rollback evidence (single command + recovery time estimate)
