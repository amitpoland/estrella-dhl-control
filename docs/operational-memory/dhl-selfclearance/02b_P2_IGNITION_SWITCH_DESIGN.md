# P2 Ignition Switch — Design Recommendation

| Field | Value |
|---|---|
| **Phase** | W-5 / P2 (ignition layer) |
| **Source ADRs** | ADR-012, ADR-013, ADR-014, ADR-018 |
| **New ADR** | **ADR-019 required** (sweeper-primary + admin-override dedup contract) |
| **Designed** | 2026-05-13 |
| **Status** | DESIGN-DELIVERED-AWAITING-OPERATOR-DECISION |
| **Implementation branch** | TBD (next session, after operator confirms model) |
| **Author** | system-architect + adr-historian + gap-hunter + business-process + final-consistency-review (5-agent panel) |

---

## TL;DR

> **Recommendation: Model C — sweep primary + admin-only HTTP override route.** Sweep extends `active_shipment_monitor.py`; override route is `POST /api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}` (X-API-Key, audit-logged). Mac stays at the read-only state pill per the P2 plan; trigger-UI surface (if any) belongs to Windows Atlas later. Five preconditions (P0/P1) below MUST be answered before implementation fires.
>
> ADR-019 needed to lock the dedup contract between the two surfaces (sweep + override).
> Effort: M (1-3 days, 5-6 files, ~25 tests).

---

## §1. Problem statement

P2 coordinator's `dispatch_proactive(inp: DispatchInput) -> Dict[str, Any]` is on main (PR #46), tested (47 P2 tests), behind the ADR-018 flag stack (combined-state validator + per-phase lock + override-flag predecessor enforcement). **Nothing currently CALLS it from production flow.** The decision: which upstream caller pattern.

The underlying architectural question:

> **Is the operator authorising shipments individually, or authorising the system to decide which shipments qualify?**

---

## §2. Three candidate models

### Model A — HTTP route trigger (operator-pulled)

- `POST /api/v1/dhl-clearance/proactive-dispatch/{batch_id}` invokes coordinator synchronously
- Each shipment requires explicit operator-initiated call
- Implies: dashboard button (forbidden on Mac per P2 plan; allowed on Atlas), templated 4xx/5xx error responses

### Model B — `active_shipment_monitor` sweep (system-pushed)

- Existing background sweep extends to identify shipments eligible (Path A + state=`awaiting_preemptive_send` + AWB-stable + flags satisfy SHADOW or LIVE per ADR-018 truth table)
- Sweep invokes coordinator asynchronously, no per-shipment operator action
- Implies: idempotency guarantee per batch, sweep cadence inheritance, full-corpus shadow accumulation

### Model C — Hybrid (sweep primary + admin route as override)

- Sweep is primary path (automatic, system-pushed)
- Admin HTTP route exists as operator override / replay / rescue mechanism
- "Automatic with escape valve" framing — NOT two equal paths
- Implies: both A + B surfaces; dedup contract documented in ADR-019; result-shape carries `triggered_by` field for audit transparency

---

## §3. Constraint analysis (per-model table)

| Dimension | Model A (HTTP only) | Model B (sweep only) | **Model C (sweep + admin override)** |
|---|---|---|---|
| Automation semantics | Operator-per-shipment, explicit | System decides, no per-shipment consent | System decides primary; operator can force a single batch |
| Replay behavior | Trivial — operator re-POSTs; idempotent guard returns prior result | Sweep retries on next tick if `dispatch_failed`; no surgical re-fire | Same as B, plus admin route to force-run one batch (force-flag bypasses idempotency with explicit audit) |
| P3 chaining | Manual handoff — nothing automatically wires P3 | State-driven via manifest (`awaiting_poland_arrival` → P3 watcher reads it) | State-driven (same as B); admin route doesn't change handoff |
| Observability quality | Operator-biased corpus (only triggered subset) — UNSAFE for shadow gate | Full-corpus shadow — every eligible batch flows through, satisfies gate | Full-corpus shadow + on-demand replay for spot-check — satisfies gate |
| Deployment timing | 3-step: ship route + ship trigger UI on Atlas + flag flip | 2-step: ship sweep extension + flag flip | 2-step: ship sweep + admin route in one PR + flag flip |
| Operator safety guarantee | Explicit consent per shipment (lowest blast radius if bug) | Trust the eligibility filter (Path A + AWB-stable + flag stack + per-phase lock) | Trust the filter; admin route as escape valve preserves operator authority |
| Mac UI compatibility | **Violates "no Mac buttons"** if exposed there; OK only if Atlas-only | Compatible — pill renders state, no buttons | Compatible — pill is read-only, admin route is curl/Atlas only |
| Atlas UI compatibility | Atlas can call route directly | Atlas reads state pill (no per-shipment trigger needed) | Atlas reads state primarily, calls admin route for replay/rescue |

---

## §4. Operator safety analysis (Tejal / Jeff / Jigar)

| Operator | Daily P2 burden — Model A | Daily P2 burden — Model B | Daily P2 burden — **Model C** | Best fit |
|---|---|---|---|---|
| **Tejal** (accounts/Saldeo, 6-12 PZ shipments/day, Polish-native) | 6-12 deliberate clicks/day. Adds a customs-email composing routine she does NOT have today. Friction insert with no cognitive anchor. | 0 clicks. State pill on Mac shows what happened; she does her morning PZ review and sees the audit. | 0 baseline; ~0-2 hold-overrides per week. Best matches her existing Cowork-style "system acts on the mechanical decision, operator owns content review" pattern. | **C** |
| **Jeff** (operations, on/off floor, intervention-mode) | Better than Tejal (he can click), but if he catches a voided AWB AFTER auto-dispatch he can't un-send. Model A doesn't help his actual intervention shape. | If sweep has already fired, Jeff has no surgical hold path. | Hold-override path lets him suppress a specific batch BEFORE sweep fires. After-fire recovery is the same as B. The C control must be framed as **"hold this dispatch"**, not "trigger now". | **C** |
| **Jigar** (warehouse, mobile-first, scan-in) | Not in P2 loop (P2 fires pre-arrival; Jigar is post-arrival). | Same — no impact. | Same — no impact. | Any |

Estrella precedent: **Model C aligns with the Cowork pattern** (system owns routing and timing; operator owns content review and exceptions). Model A inverts the precedent — heavily-operator-gated only fits inventory/scan workflows where physical-world ambiguity requires a human signal.

**Recoverability cost** (from business-process review):
- Model A "I forgot" failure: ~15-30 min per incident; cumulative leakage; silent until downstream notices
- Model B/C false-positive failure: 1-3 hours per incident (DHL hold release); bounded by the ADR-018 gate stack quality (AWB-stable + scope + flag-pair + predecessor-live + per-phase lock)
- Model C hold-override (pre-sweep): near-zero cost; operator clicks hold; sweep skips; audit recorded

---

## §5. Recommendation with reasoning

### Pick Model C.

**Against Model A (pure operator-pulled).** The shadow-promotion gate requires ≥50 dispatches across ≥10 distinct AWBs in a continuous 48 h window with zero duplicate sends and zero AWB-unstable misfires (per `02_P2_PROACTIVE_DISPATCH.md` § "SHADOW→LIVE PROMOTION GATE"). Model A turns operator behavior into the rate-limiter for the gate — a 4-day operator absence = no gate progress. Shadow corpus is structurally biased to "shipments operator remembered to click." Promotion data quality drops. **Reject A as primary.** (Confirmed by gap-hunter F8.)

**Against Model B (pure sweep).** Once a batch enters `dispatch_failed` state (e.g., transient SMTP error, missing attachments cleared by operator manually), there is no surgical re-fire path — operator waits for next sweep tick or mutates state by hand. Replay during the shadow window for spot-check ("re-dispatch this same batch and verify hash matches") needs a direct invocation. Reject B-pure for missing the escape valve.

**For Model C.** Sweep is the ignition engine — every Path A batch in `awaiting_preemptive_send` with AWB-stable=True flows through `dispatch_proactive` automatically, satisfying the corpus requirement. The admin route at `POST /api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}` (X-API-Key auth, same pattern as the ADR-018 admin runtime-flags endpoint) is **not an operator-facing UI button**; it is a curl/Atlas/cron rescue tool. "Automatic with escape valve" is the standard pattern across the codebase (`active_shipment_monitor` already follows this — cron + manual `/api/v1/monitor/active-shipments/run`).

### Direct answers to the framing questions

- **"No Mac buttons" rules out a Mac dashboard widget, NOT an admin-authenticated HTTP route.** P2 plan §29 forbids "trigger buttons, override controls, operator-facing reply forms on Mac." An admin endpoint reachable via curl or Atlas is not a Mac control.
- **`active_shipment_monitor` is the natural host.** It already has `_is_active`, `COOLDOWN_MINUTES = 10`, terminal-state skip, scope filter, and writes only safe audit fields. Adding a P2 hook is an additional conditional branch in the sweep loop, not new infrastructure.
- **"Automatic with escape valve" does not conflict with operator authority.** Discipline: admin route logs every invocation with operator identity; if log shows >X% of dispatches came from admin route during shadow, that's a regression signal — the sweep is broken, not the design.
- **Is the operator authorising shipments individually, or authorising the system to decide which shipments qualify?** The operator authorises **the system** (via the `dhl_selfclearance_p2_live_enabled` flag flip + Tejal's spot-check sign-off). Per-shipment authorisation does not match Estrella's automation precedent at this cadence.

---

## §6. Builder/consumer signature for the trigger layer (Lesson A discipline)

The coordinator API is on main and tested. Both Model C surfaces (sweep + admin route) MUST consume it without re-wrapping or re-shaping.

### Signature trigger calls (frozen contract on main)

```python
coordinator.dispatch_proactive(inp: DispatchInput) -> Dict[str, Any]
```

### `DispatchInput` shape the trigger MUST build (frozen `@dataclass`)

```python
@dataclass(frozen=True)
class DispatchInput:
    batch_id: str                # primary key for carrier DB lookup
    awb:      str                # current AWB string from audit
    audit:    Dict[str, Any]     # mutated in-place for manifest writes
```

### Return shape the trigger MUST consume

```python
{
  "status":         "shadow" | "sent" | "skipped" | "blocked",
  "reason":         str,             # "dormant_state" | "awb_unstable" | "build_failed" | "queue_failed" | "missing_attachments" | "shadow_logged" | "queued" | "already_dispatched"
  "message_id":     str | None,
  "content_sha256": str,             # "" on skip/block-pre-build
  "idempotent":     bool,
  # Lesson A binding rule extension for Model C (NEW):
  "triggered_by":   "sweep" | "admin_route",  # source of this dispatch attempt — operator-visible audit field
}
```

### Trigger-layer normalisation rules (Lesson A binding)

- Sweep MUST treat `status="blocked"` as a per-batch failure: log it, do NOT mark sweep-tick failed (other batches must continue).
- Sweep MUST treat `status="skipped" + reason="awb_unstable"` as expected (try again next tick, no escalation).
- Admin route MUST surface `OutOfScopeError` as HTTP 422 and `ForbiddenFlagCombination` as HTTP 409.
- **Trigger MUST NOT read `dhl_selfclearance_p2_*` flags itself** — coordinator handles all flag inspection internally. Trigger reads only the eligibility predicates (path, state, AWB-stable indirectly via coordinator's gate).

### Canonical regression test (Lesson A binding rule 2)

Required in the implementation PR: `service/tests/test_p2_ignition_real_coordinator.py::test_sweep_passes_real_dispatch_input_shape`

Instantiates real `DhlClearanceCoordinator`, calls sweep against a synthetic Path A audit, asserts:
- `DispatchInput.batch_id` is `str` (not `None`, not `int`)
- `DispatchInput.awb` is `str` (not `None`, not `list`)
- `DispatchInput.audit` is `dict` (not `OrderedDict`, not `Mapping[Any]`)
- Return-shape dict has exactly the 6 keys above (`status`, `reason`, `message_id`, `content_sha256`, `idempotent`, `triggered_by`)

---

## §7. Risks + edge cases for Model C

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R-C1** | Operator triggers admin route while sweep is mid-tick → double dispatch | LOW | Coordinator's idempotency guard (`prior.get("message_id")`) covers within-batch race; per-phase lock (PR #57) serialises within process; sweep + admin share same coordinator singleton |
| **R-C2** | Replay desire (operator wants to re-dispatch after `dispatch_failed`) | MEDIUM | Admin route accepts `?force_retry=true` which calls a recovery transition `dispatch_failed → awaiting_preemptive_send` then invokes coordinator. Without `force_retry`, idempotent no-op. This is a NEW behaviour on the coordinator and needs a test. |
| **R-C3** | P3 handoff timing | LOW | P3 watcher reads `audit.dhl_clearance.state == awaiting_poland_arrival` AND `p2_dispatch.shadow == False` (or shadow-OK if P3 also in shadow). Manifest is the bus. No new event plumbing. |
| **R-C4** | Sweep cadence | LOW | Inherit `active_shipment_monitor` cron cadence (existing). Add a P2-specific COOLDOWN per-batch (e.g., 5 min) to avoid retry-storm on transient SMTP. Skip terminal + `scope_gate_violated` states. |
| **R-C5** | Concurrency: two sweep instances racing | LOW | Coordinator's per-phase lock (PR #57) is the inner serialiser. Sweep itself should hold the existing single-flight pattern (`_running` flag in `active_shipment_monitor`). |
| **R-C6** | Shadow-window observability | NONE | Sweep over full corpus → satisfies ≥50 dispatches / ≥10 AWBs / 48 h on production volume. Manifest writes content_sha256 → replay-rebuild check is mechanical. |
| **R-C7** | Operator opt-out / suspend a specific batch | MEDIUM | Add a single batch-level "freeze" flag in audit (`dhl_clearance.operator_hold == True`) that sweep checks before dispatching. Atlas-side hold control writes this flag; sweep skips. Audit-logged. |
| **R-C8** | Admin route accidentally hits Path B | LOW | Coordinator already raises `OutOfScopeError` — route returns 422 cleanly. |
| **R-C9** | Sweep-vs-route confusing UX (operator clicks dispatch, sees `idempotent: True` because sweep just fired 2s ago) | MEDIUM | Result-shape includes `triggered_by` field; operator UI renders "DHL was dispatched 2 seconds ago by the auto-sweeper" instead of "Idempotent (already dispatched)" |
| **R-C10** | Boot-replay race against immediate sweep fire | LOW | Add `_STARTUP_REPLAY_COMPLETE: bool = False` set True at end of `load_persisted_flags_into_settings`; sweep substrate consults it and no-ops if False. (Coordinator re-reads flags at dispatch time, so this is defense-in-depth.) |

---

## §8. Critical preconditions surfaced by gap-hunter (P0/P1)

These MUST be answered by the operator before implementation fires. Each blocks Model C's correctness.

### P0-PREC1 — Disposition of legacy `_ensure_path_a_auto_queue`

`active_shipment_monitor.py:816` already runs a Path A auto-queue at the first Departed-origin event, gated by `enable_path_a_auto_queue` flag. It calls `build_dhl_proactive_dispatch` + `queue_email` DIRECTLY, writes legacy `proactive_dispatch_sent_at` audit field, does NOT advance the new state-engine, does NOT honor ADR-018 `shadow_mode`.

**If P2's ignition wires the coordinator into the SAME sweep without first deprecating or migrating this legacy path, every Path A batch will be dispatched twice** (once via legacy path → real email; once via coordinator → second real email or shadow tagged with non-matching state). Coordinator's idempotency check looks at `audit.dhl_clearance.p2_dispatch.message_id` and does NOT see the legacy path's `proactive_dispatch_sent_at`.

**Three options for operator decision**:

| Option | Approach | Blast radius | Recommendation |
|---|---|---|---|
| **(a) Delete** | Remove `_ensure_path_a_auto_queue` from sweep loop in same PR as coordinator wiring | LARGE — already in production with `enable_path_a_auto_queue` flag; existing operators rely on it | Reject — too risky in same PR |
| **(b) Gate-flip** | `_ensure_path_a_auto_queue` becomes a thin wrapper that calls `coordinator.dispatch_proactive` instead of the legacy direct path | MEDIUM — preserves entry point, swaps internals | **Recommended** — cleanest migration; legacy flag continues to gate; coordinator owns logic |
| **(c) Co-exist** | Both paths coexist; coordinator reads BOTH `proactive_dispatch_sent_at` AND `dhl_clearance.p2_dispatch.message_id` for idempotency | LOW for ignition PR; HIGH ongoing maintenance cost (two state machines to reason about) | Acceptable as transitional state for ≤1 month, then remove |

**Operator must decide between (b) and (c) before ignition PR opens.**

### P0-PREC2 — Coordinator-aware sweep filter

Sweep's existing eligibility filter (`_is_active`, `_TERMINAL_CLEARANCE_STATUSES`, `_STATUS_ORDER`) reads the legacy `clearance_status` audit field. The coordinator state machine writes to `audit.dhl_clearance.state` (a different field). Without alignment:

- Sweep would dispatch against shipments stuck in coordinator state `dispatch_failed` (not in legacy terminal set)
- Sweep would dispatch against shipments where `clearance_status == "agency_email_sent"` (terminal in legacy) but coordinator state is `awaiting_preemptive_send`

**Required**: ignition PR adds a coordinator-aware filter step:
```python
if not coordinator.is_in_scope(audit):
    continue
if audit.get("dhl_clearance", {}).get("state") != "awaiting_preemptive_send":
    continue
```
**before** calling `coordinator.dispatch_proactive`.

### P1-PREC3 — Operator re-dispatch path (force-flag or admin-clear)

Coordinator currently has no `force=True` parameter. After successful first dispatch, every subsequent call returns `idempotent: True`. Operator scenario "DHL bounced our email; resend" has zero supported path today.

**Two options**:
- **(a) `force=True` parameter on `dispatch_proactive(inp, *, force=False)`** — simpler; bypasses idempotency check; writes `p2_dispatch_history[]` audit array
- **(b) Admin "clear-p2-dispatch" endpoint** — nulls `dhl_clearance.p2_dispatch.message_id` with operator-required reason; safer (two-step) but adds latency

**Recommendation**: (a). Force-flag is a single-call recovery; (b) adds a second authentication round-trip without safety gain (operator still must intend the re-dispatch).

### P1-PREC4 — P3 handoff contract

Coordinator's `on_tracking_event` is currently `NotImplementedYet`. P3 watcher (next session) must subscribe to coordinator state transitions. The ignition PR documents the contract:

> Every sweep iteration calls coordinator method per phase, sequenced by `audit.dhl_clearance.state`. Phase methods are: P2 = `dispatch_proactive`; P3 = `on_tracking_event` (when state == `awaiting_poland_arrival`); P4 = `on_inbound_clarification` (when state == `clarification_received`); P5 = `on_sad_inbound` (when state == `sad_received`).

**Required**: ignition PR adds this contract as a comment block at the top of `active_shipment_monitor.py` so P3 author knows the slot.

### P1-PREC5 — Per-batch lock at sweep substrate

Per-phase lock (PR #57) prevents concurrent admin-flag-flips for the same phase. It does NOT prevent two sweep workers (or sweep + admin route) from racing on the same batch.

**Required**: ignition PR adds per-batch lock around `coordinator.dispatch_proactive` call site at the sweep substrate (mirror `proposal_write_lock(batch_id)` pattern already used in `active_shipment_monitor.py`).

---

## §9. Implementation effort estimate

**M (1-3 days, 5-6 files, ~25 tests).**

### Files to be modified

| File | Change | Lines (est.) |
|---|---|---|
| `service/app/services/active_shipment_monitor.py` | Add `_dispatch_p2_if_eligible(audit, batch_id)` branch in sweep loop; add coordinator-aware filter; add per-batch lock; gate-flip `_ensure_path_a_auto_queue` per P0-PREC1 option (b) | ~80 |
| `service/app/services/dhl_clearance_coordinator.py` | Add `dispatch_proactive(inp, *, force=False)` parameter per P1-PREC3 (a); add `triggered_by` to return shape per Lesson A | ~30 |
| `service/app/api/routes_admin_dhl_clearance.py` (NEW) | Admin POST `/api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}` with X-API-Key, audit log, `?force_retry` query param | ~120 |
| `.claude/adr/ADR-019-p2-ignition-pattern.md` (NEW) | Lock the dedup contract: when both surfaces fire, who wins; how `triggered_by` is recorded; how `force_retry` interacts with idempotency | ~120 |
| `service/tests/test_p2_ignition_sweep.py` (NEW) | Sweep eligibility filter, status routing, idempotency-across-ticks, scope-skip, AWB-unstable-skip, dispatch_failed handling, force_retry recovery, P0-PREC1 gate-flip behaviour | ~15 tests |
| `service/tests/test_p2_ignition_admin_route.py` (NEW) | Auth, 422 OutOfScope, 409 Forbidden, idempotency on double-POST, force_retry behaviour, audit-log presence, `triggered_by="admin_route"` field | ~8 tests |
| `service/tests/test_p2_ignition_real_coordinator.py` (NEW) | Lesson A canonical: real coordinator + synthetic audit, asserts DispatchInput shape and return-shape contract; force=True path | ~3 tests |

### No schema changes. No new external dependencies.

### Dependent follow-up issues to file

| # | Title | GATE 4 disposition | Severity |
|---|---|---|---|
| **F-IGN-1** | Atlas-side P2 hold/rescue UI (Model C operator surface) — Atlas team picks up `POST /api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}?force_retry` + reads `dhl_clearance.operator_hold` flag | **SCHEDULED** | MEDIUM |
| **F-IGN-2** | Sweep heartbeat audit + dead-man's switch alarm for cron stoppage (gap-hunter F11) | **SCHEDULED** | LOW |
| **F-IGN-3** | Unify or document legacy `clearance_status` vs new `dhl_clearance.state` field relationship (gap-hunter F2 followup) | **SCHEDULED** | LOW |
| **F-IGN-4** | `resolve_audit_awb(audit)` shared helper (deduplicate AWB extraction across `_resolve_proactive_awb` / `_run_path_a_validation_gate` / new sweep filter) (gap-hunter F12) | **SCHEDULED** | LOW |
| **F-IGN-5** | Sweep cooldown tuning post-shadow-window observation (calibrate `COOLDOWN_MINUTES` for P2 specifically vs the existing 10-min email_scan default) | **SCHEDULED** | LOW |

---

## §10. ADR-019 question — needed

**Yes. ADR-019 required.**

### Title
**ADR-019 — DHL self-clearance: proactive dispatch trigger surfaces and dedup contract (P2 ignition switch)**

### Context (3-5 lines for next session to author from)
> ADR-013 fixed the proactive-dispatch decision and idempotency-by-AWB rule but did not specify the upstream caller — sweep, HTTP route, or hybrid. P2 implementation lands `dispatch_proactive()` on the coordinator behind the ADR-018 flag stack; choosing a hybrid trigger (sweep + admin HTTP override) introduces a dedup-contract question that ADR-013's manifest-message_id idempotency does not fully resolve: (a) flag-state honour across surfaces, (b) AWB-stable gate honour across surfaces, (c) race resolution on simultaneous fire, (d) `force_retry` semantics that bypass idempotency. ADR-019 sequesters these into a single decision so future sessions inheriting the hybrid model do not re-derive surface semantics from code.

### Cross-references
- **ADR-012** — scope gate, hard locks, one-AWB-one-thread
- **ADR-013** — proactive dispatch decision; idempotency by AWB
- **ADR-014** — paired tracker+scheduler pattern this ADR extends
- **ADR-018** — truth table; trigger surfaces must evaluate flag state at coordinator, not at surface
- **ADR-010** — default-OFF flags; trigger surface inherits
- **ADR-006** — manifest sha256 unaffected by trigger surface
- **Operational memory** — `windows_atlas_ui_primary_2026-05-12.md` for the no-Mac-button rationale

### Why not "fits within existing ADRs"
- ADR-013 is silent on caller pattern — it specifies WHAT and WHEN, not WHO-INVOKES
- The two-paths-to-one-coordinator dedup contract (Model C specific) is not a property of any existing ADR
- `force_retry` semantics that bypass the idempotency clause of ADR-013 require explicit ADR-level acknowledgment

---

## §11. Operator decision point

**Operator confirms which model; next session implements.**

To proceed to implementation, the operator confirms each of the following:

| # | Decision | Default if operator stays silent |
|---|---|---|
| 1 | **Model selected** | Model C |
| 2 | **P0-PREC1 disposition of `_ensure_path_a_auto_queue`** | (b) gate-flip — wrap legacy entry point to call coordinator |
| 3 | **P1-PREC3 re-dispatch path** | (a) `force=True` parameter on coordinator |
| 4 | **ADR-019 authored in implementation PR or separate PR?** | Same PR (smaller surface; one review cycle) |
| 5 | **Atlas-side hold/rescue UI scope** | F-IGN-1 deferred to Atlas team; ignition PR does not block on it |
| 6 | **Shadow window opens immediately on first deploy of ignition PR?** | Yes — sweep fires under `shadow_mode=True` (default per ADR-018); ≥48h corpus accumulates; Tejal spot-checks ≥10 payloads before flag-flip to LIVE |

After operator confirms (or accepts defaults): next session opens, branches `feat/p2-ignition-c-sweep-and-admin-override`, implements per §9, runs full agent gate including `business-process` reviewer for operator-safety re-check, opens PR. **This session stops at recommendation.**

---

## §12. References

- `service/app/services/dhl_clearance_coordinator.py:162` — `dispatch_proactive` (frozen contract)
- `service/app/services/active_shipment_monitor.py:816` — legacy `_ensure_path_a_auto_queue` (must be gate-flipped per P0-PREC1)
- `service/app/services/active_shipment_monitor.py:36` — `COOLDOWN_MINUTES = 10`
- `service/app/services/active_shipment_monitor.py:2034` — sweep loop call site for `_ensure_path_a_auto_queue`
- `service/app/api/routes_admin_runtime_flags.py:524` — `_PHASE_LOCKS` (per-phase lock template)
- `service/app/api/routes_admin_runtime_flags.py:204` — `_enforce_startup_combined_states` (boot-replay reference for P-C10)
- `docs/operational-memory/dhl-selfclearance/02_P2_PROACTIVE_DISPATCH.md:29` — "no operator-facing buttons on Mac" constraint
- `docs/operational-memory/dhl-selfclearance/00_MASTER_PLAN.md:§4.4` — coordinator pattern locked
- `.claude/memory/engineering_lessons.md` — Lessons A, B, C (binding rules)
- `.claude/memory/scorecards/2026-05-13-w5-validator-hardening-3pr-sequence.md` — agent verdicts on the validator stack this design depends on
