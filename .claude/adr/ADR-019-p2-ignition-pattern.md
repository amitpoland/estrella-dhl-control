# ADR-019: DHL self-clearance — proactive dispatch trigger surfaces and dedup contract (P2 ignition switch)

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-05-13 |
| **Phase** | W-5 / P2 (ignition layer) |
| **Amends** | ADR-013 (idempotency-bypass clause for force-path; see §"Relationship to ADR-013 idempotency") |
| **Related** | ADR-012, ADR-014, ADR-018 |
| **Implements operator decision** | Model C (sweep primary + admin override route) per design doc `02b_P2_IGNITION_SWITCH_DESIGN.md` |

## Context

ADR-013 fixed the proactive-dispatch decision and idempotency-by-AWB rule but did not specify the upstream caller — sweep, HTTP route, or hybrid. P2 implementation lands `dispatch_proactive()` on the coordinator behind the ADR-018 flag stack; choosing a hybrid trigger (sweep + admin HTTP override) introduces a dedup-contract question that ADR-013's manifest-message_id idempotency does not fully resolve:

(a) flag-state honor across surfaces,
(b) AWB-stable gate honor across surfaces,
(c) race resolution on simultaneous fire,
(d) `force_retry` semantics that bypass idempotency.

ADR-019 sequesters these into a single decision so future sessions inheriting the hybrid model do not re-derive surface semantics from code.

## Decision

**Sweep is the primary path; admin HTTP route is the override / replay / rescue mechanism with explicit `force` parameter.**

### Surfaces

| Surface | Module | Trigger | Audit field `triggered_by` |
|---------|--------|---------|----------------------------|
| Sweep | `service/app/services/active_shipment_monitor.py` (`_dispatch_p2_via_coordinator`) | `scan_active_shipments()` cron tick | `"sweep"` |
| Admin route (normal) | `POST /api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}` body `{force: false}` | Operator/Atlas/curl with X-API-Key | `"admin_override_normal"` |
| Admin route (force) | Same route, body `{force: true, reason: "...", actor: "..."}` | Operator/Atlas/curl with X-API-Key + reason ≥10 chars + actor ≥3 chars | `"admin_override_force"` |

### Truth table for `triggered_by` field

| Caller | force | Result `triggered_by` | Idempotency check |
|--------|-------|------------------------|-------------------|
| sweep | n/a (always False) | `"sweep"` | Subject to `message_id` guard |
| admin route | False | `"admin_override_normal"` | Subject to `message_id` guard |
| admin route | True | `"admin_override_force"` | Bypassed; prior dispatch archived to `p2_dispatch_history[]` |

### Validation order

The admin route validates in this order before invoking the coordinator:
1. **Auth** — `require_api_key` (X-API-Key header) per canonical admin pattern
2. **Body schema** — `ForceDispatchBody` (Pydantic)
3. **Force contract** — when `force=true`, both `reason` (≥10 chars) AND `actor` (≥3 chars) MUST be present; rejected as `MISSING_REASON` / `REASON_TOO_SHORT` / `MISSING_ACTOR` / `ACTOR_TOO_SHORT`
4. **Audit load** — `audit.json` for the batch must exist (404 if missing)
5. **Coordinator invocation** — `dispatch_proactive(inp, caller="admin_route", force=force, actor=actor)`

The coordinator then enforces:
- ADR-018 truth-table state (DORMANT / SHADOW / LIVE / FORBIDDEN)
- Path A scope gate (raises `OutOfScopeError` on Path B)
- AWB-stability gate
- Idempotency (unless `force=True`)
- Force contract belt-and-braces (`ForceRequiresActor`, `CallerRejectsForce`)

## Invariants

1. **Single source of truth.** Both surfaces invoke the same `coordinator.dispatch_proactive()`. No surface-local re-implementation of dispatch logic. Lesson A discipline: tests bind to the real coordinator function.

2. **Force-contract field requirements.** `force=True` REQUIRES `reason` (≥10 chars) AND `actor` (≥3 chars). Both validated at the route layer; coordinator's `ForceRequiresActor` is belt-and-braces.

3. **WARNING-level audit on force.** Successful `force=True` dispatch emits `admin_dispatch_override` audit entry tagged `log_level="WARNING"` with full forensic context (actor, reason, batch_id, prior `message_id`, new `message_id`, `triggered_by`).

4. **Sweep never sets `force=True`.** `coordinator.dispatch_proactive(caller="sweep", force=True)` raises `CallerRejectsForce`. Sweep is the automatic primary path; force is reserved for the admin override route. Mixing these would mask sweep bugs as operator actions.

5. **Per-batch lock serializes simultaneous calls.** Two simultaneous calls (sweep + admin) on the same `batch_id` are serialized by the per-batch `threading.Lock` in `active_shipment_monitor._P2_BATCH_LOCKS`. Sweep acquires non-blocking; if held by the admin route, sweep skips this iteration and retries next tick. The coordinator's idempotency check (manifest `message_id` guard) is the inner safety; this lock is defense-in-depth.

6. **Force does NOT bypass ADR-018 combined-state validator.** `force=True` does NOT bypass DORMANT short-circuit, FORBIDDEN raise, OutOfScope raise, or AWB-stability gate. Force ONLY bypasses the per-batch `message_id` idempotency check. FORBIDDEN flag combinations remain rejected at every entry point (admin runtime-flags endpoint AND admin dispatch endpoint).

7. **Boot-replay race guard.** Sweep's P2 ignition branch is a no-op until `mark_startup_replay_complete()` fires from `main.py` lifespan, immediately after `load_persisted_flags_into_settings()` completes. This prevents stale-flag dispatch during the lifespan startup window.

8. **History append on force.** When `force=True` finds a prior `p2_dispatch.message_id`, the prior entry is archived into `audit.dhl_clearance.p2_dispatch_history[]` with `archived_at`, `archived_by`, and `archive_reason="force_redispatch"` before the manifest is overwritten. Forensic reconstruction always possible.

## Relationship to ADR-013 idempotency

ADR-013 §Idempotency states: *"A second proactive dispatch attempt for the same AWB is a no-op when the manifest already records a successful dispatch message-id."*

ADR-019's `force=True` path introduces a documented bypass of this rule, intentionally bounded by:
- **Auth surface**: bypass is only reachable via the admin HTTP route (X-API-Key). Sweep cannot trigger it (Invariant 4).
- **Operator accountability**: bypass requires `actor` (≥3 chars) AND `reason` (≥10 chars). Both validated at the route layer; coordinator's `ForceRequiresActor` is belt-and-braces.
- **Forensic preservation**: prior dispatch is archived to `audit.dhl_clearance.p2_dispatch_history[]` with `archived_at`, `archived_by`, `archive_reason="force_redispatch"` before the manifest is overwritten (Invariant 8). The prior message_id is never lost.
- **Audit visibility**: every force-bypass emits a WARNING-level `admin_dispatch_override` audit entry (Invariant 3).
- **Defense-in-depth**: force=True does NOT bypass ADR-018's combined-state validator, ADR-012's scope gate, or the AWB-stability gate (Invariant 6).

ADR-013's idempotency rule remains the DEFAULT behavior. The bypass is the EXCEPTION, gated by all the above. This ADR amends ADR-013 by carving out this specific exception, not by replacing the default behavior.

## Gate-flip migration (P0-PREC1)

Legacy `_ensure_path_a_auto_queue` in `active_shipment_monitor.py` is preserved in code but gated behind a new config flag `dhl_selfclearance_legacy_path_a_queue_enabled` (default: **False**).

- **Default state (post-deploy)**: legacy path does NOT run; new coordinator-based ignition is the sole P2 ignition source.
- **Rollback escape valve**: operator may set `dhl_selfclearance_legacy_path_a_queue_enabled=True` via env to re-enable the legacy path. Should NEVER be enabled simultaneously with the new path — would double-dispatch.
- **Mutual exclusion** is enforced in code: `scan_active_shipments` `if/else` branch chooses one path per sweep iteration based on the flag.

## Consequences

- **Forward**: P3, P4, P5 inherit this caller pattern. Each phase exposes its own coordinator entrypoint (`on_tracking_event`, `on_inbound_clarification`, `on_sad_inbound`); sweep iterates and dispatches based on `audit.dhl_clearance.state`.
- **Atlas**: when the Windows Atlas UI is built, it becomes a third caller of the same admin route (X-API-Key from Atlas backend). No coordinator changes required.
- **Mac**: read-only state pill only. No proactive-dispatch trigger button. Per `02_P2_PROACTIVE_DISPATCH.md` UI commitment.
- **Shadow corpus**: sweep over full eligible corpus → satisfies the 48h ≥50/≥10 promotion gate. Operator does not bottleneck the gate.
- **Audit completeness**: every dispatch carries `triggered_by`; force events carry `actor` + `reason`; manifest carries `message_id` + `content_sha256`; history array preserves overwritten dispatches.
- **Operator UX (post-Atlas)**: operator triggers admin route → sees response carrying `triggered_by` field. Even on `idempotent: True` (sweep just fired 2 seconds prior), UI can render "DHL was dispatched 2s ago by the auto-sweeper" rather than confusing "Idempotent (already dispatched)".

## Open items (deferred to GitHub issues)

- **F-IGN-1** — Atlas-side P2 hold/rescue UI (Atlas team picks up the admin route + reads `dhl_clearance.operator_hold` flag).
- **F-IGN-2** — Sweep heartbeat audit + dead-man's-switch alarm for cron stoppage.
- **F-IGN-3** — Document or unify legacy `clearance_status` vs new `dhl_clearance.state` field relationship.
- **F-IGN-4** — Extract `resolve_audit_awb(audit)` shared helper (deduplicate AWB extraction across `_resolve_proactive_awb`, `_run_path_a_validation_gate`, new sweep filter, new admin route).
- **F-IGN-5** — Sweep cooldown tuning post-shadow-window observation (calibrate `COOLDOWN_MINUTES` for P2 specifically vs the existing 10-min default).

## References

- `service/app/services/dhl_clearance_coordinator.py` — `dispatch_proactive(inp, *, caller, force, actor)` signature; `ForceRequiresActor`, `CallerRejectsForce` exception classes; force-bypass-with-history logic
- `service/app/services/active_shipment_monitor.py:_dispatch_p2_via_coordinator` — sweep helper
- `service/app/api/routes_admin_dhl_clearance.py` — admin override route
- `docs/operational-memory/dhl-selfclearance/02b_P2_IGNITION_SWITCH_DESIGN.md` — the design recommendation that produced this ADR
- `.claude/memory/engineering_lessons.md` — Lesson A real-builder discipline binding for the trigger layer
- `.claude/adr/ADR-013-dhl-self-clearance-proactive-dispatch.md` — original dispatch decision (this ADR extends without amending)
- `.claude/adr/ADR-018-shadow-mode-flag-defaults.md` — flag truth table (this ADR honors without amending)
