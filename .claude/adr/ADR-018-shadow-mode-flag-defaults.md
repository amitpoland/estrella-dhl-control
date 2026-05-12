# ADR-018: Shadow-mode flag defaults are a distinct flag category from live-enabled flag defaults

Status: Accepted
Date:   2026-05-13
Amends: ADR-010 (default-OFF feature flags)
Related: ADR-012, ADR-013, ADR-014, ADR-015, ADR-016 (DHL self-clearance phases)

## Context

ADR-010 established that every feature flag ships `default=False`
"without exception." This rule was authored when flags were
single-dimensional: a flag is ON or OFF, where ON = real action
and OFF = no action.

The DHL self-clearance program (ADR-012..016, W-5 P0 foundation
in PR #33) introduced a two-dimensional flag model:
- `shadow_mode`: whether the phase observes and logs without acting
- `live_enabled`: whether the phase performs real action

These dimensions are independent. The intended safe default state
for a new phase is:
- `shadow_mode = True` (observation enabled)
- `live_enabled = False` (execution disabled)

This means the phase code RUNS during shadow_mode=True, but produces
only logs and audit entries — no real emails, no real state advances,
no real external writes. The phase only takes real action when
`live_enabled` flips to True (with `shadow_mode` remaining True).

If we apply ADR-010 verbatim and default `shadow_mode=False`, the
phase code never runs at all until the operator manually flips
`shadow_mode=True` before any observation can begin. This adds
friction to every shadow rollout and partially defeats the purpose
of shadow mode.

Canonical adr-historian flagged this contradiction during PR #33
review on 2026-05-13 as a HIGH severity finding. This ADR resolves
the contradiction at the architectural layer.

## Decision

Amend ADR-010 to recognize two flag categories with different default
rules:

### Category A — Action-bearing flags (default=False, no exception)

Flags whose True state produces real-world side effects.

Examples:
- `*_live_enabled` flags (P2, P3, P4, P5 live activation)
- `*_pz_trigger_enabled` flags (P5 auto-PZ inner gate)
- `*_tracker_paused` flags (kill switches — semantically inverted:
  paused=True is the safe state; default=False means "not paused
  which means tracker is permitted to run, but only if its live
  flag is also True")
- Any flag whose True state causes external API write, outbound
  email, financial mutation, inventory mutation, or audit-irreversible
  state advance

### Category B — Observation flags (default=True)

Flags whose only effect is to enable logging, audit recording, or
observation without real-world side effects.

Examples:
- `*_shadow_mode` flags
- Any flag whose True state enables observation/logging only

A phase is "safe to ship" when:
- All Category A flags default False
- All Category B flags default True
- The combination means: phase code runs in observation mode but
  produces no real-world side effects

## Truth table — canonical state semantics

For any phase with both shadow_mode and live_enabled flags, exactly
four combinations exist. Three are valid; one is forbidden.

| shadow_mode | live_enabled | State name             | Behavior                                                                |
|-------------|--------------|------------------------|-------------------------------------------------------------------------|
| False       | False        | DORMANT                | Phase code does not run. No observation, no execution.                  |
| True        | False        | SHADOW                 | Phase observes and logs. No external side effects allowed.              |
| False       | True         | INVALID — FORBIDDEN    | Configuration error. Must be rejected at startup or admin-flag-update time. |
| True        | True         | LIVE                   | Live execution permitted. Shadow logging continues alongside.           |

### Invariants (binding)

1. `live_enabled=True` REQUIRES `shadow_mode=True`. The combination
   `shadow_mode=False + live_enabled=True` is FORBIDDEN at all times.

2. Any external side effect (outbound email, customs submission,
   PZ creation, inventory state advance, third-party API write)
   REQUIRES `live_enabled=True`.

3. `shadow_mode=True` alone, without `live_enabled=True`, MUST NEVER
   produce:
   - Outbound email to DHL, Agency, or any external recipient
   - Customs submission of any kind
   - PZ document creation or mutation
   - Inventory state advancement (transitions in inventory_state_engine)
   - Customs state advancement that would unblock downstream phases
   - Any external API write or third-party system mutation

4. Shadow mode produces ONLY:
   - Log entries
   - Audit JSONL records
   - Internal counters and metrics
   - Manifest writes WITHIN `dhl_clearance.*` namespace (no cross-namespace
     writes that could affect non-W-5 systems). The sub-schemas of the
     `dhl_clearance.*` namespace are frozen at P0 per
     `docs/operational-memory/dhl-selfclearance/01_P0_FOUNDATION.md`
     §"Files to be created" (manifest writer helper section): phases
     may NOT add fields without an ADR amendment. Adding a
     `dhl_clearance.p2_new_diagnostic_field` under shadow_mode is
     therefore a schema-fence violation, not merely a namespace-fence
     compliance.
   - **State_history entries written under shadow_mode MUST carry
     `shadow: True` on the entry record.** State_history is
     append-only by construction (audit-irreversible), so shadow runs
     would otherwise leave indistinguishable transition records
     alongside live transitions. The `shadow: True` tag lets audit
     consumers filter cleanly. Appending to state_history under
     shadow_mode does NOT count as "customs state advancement that
     would unblock downstream phases" (Invariant 3) provided no
     downstream code path reads the shadow-tagged entries as
     gating signals — phase implementers must verify this in their
     own PR.

## Runtime enforcement recommendation

This ADR does not introduce code changes. It establishes the
semantic model. Subsequent phases (P2, P3, P4, P5) SHOULD implement
runtime assertion checks that:

a) Reject the FORBIDDEN configuration at service startup time:
   - If `shadow_mode=False AND live_enabled=True` for any phase,
     log CRITICAL and refuse to start the phase coordinator
   - Service may continue running other phases; affected phase is
     held in DORMANT state until configuration corrected

b) Reject the FORBIDDEN configuration at admin-flag-update time:
   - Admin runtime-flags endpoint POST handler validates the
     resulting state across both dimensions for the affected phase
   - If POST would produce `shadow_mode=False AND live_enabled=True`,
     reject with 400 Bad Request, error_code = `INVALID_FLAG_COMBINATION`,
     hint = "live_enabled=True requires shadow_mode=True"
   - No state mutation occurs; audit log records the rejection

c) Add tests for each phase covering:
   - DORMANT → SHADOW transition (admin endpoint flips shadow_mode
     True with live_enabled False)
   - SHADOW → LIVE transition (admin endpoint flips live_enabled
     True with shadow_mode already True)
   - LIVE → SHADOW transition (admin endpoint flips live_enabled
     False; shadow_mode remains True)
   - SHADOW → DORMANT transition (admin endpoint flips shadow_mode
     False with live_enabled already False)
   - FORBIDDEN attempt rejection: any admin endpoint POST that would
     produce shadow_mode=False AND live_enabled=True returns 400
     `INVALID_FLAG_COMBINATION`

These runtime checks are NOT part of this ADR's PR. They are
PHASE-SPECIFIC requirements that each P2/P3/P4/P5 instruction will
include as acceptance criteria. File as Issue #38 addendum or
separate tracking item.

## Consequences

- ADR-010 §"Default values" amended: the "without exception" clause
  now applies only to Category A (action-bearing) flags. Category B
  (observation) flags follow the opposite default rule.

- PR #33 (W-5 P0 foundation) becomes ADR-conformant after this
  amendment merges. The 4 `*_shadow_mode = True` defaults in P0
  config are correct under the two-category model.

- Future phases (P2, P3, P4, P5) follow the same two-category pattern.
  Their flag declarations must explicitly map each flag to Category
  A or Category B in code comments or config docs.

- The FORBIDDEN state combination is now structurally rejected.
  Future operator error (manually setting `shadow_mode=False` while
  `live_enabled=True` remains) cannot silently activate live mode
  without observation.

- adr-historian agent prompt should be updated (separate PR, future
  follow-up) to recognize this two-category distinction on subsequent
  reviews. Until then, adr-historian may flag Category B flags as
  ADR-010 violations; reviewers can resolve by citing ADR-018.

## Open items (for future ADRs or issues)

- Whether other flag categories exist beyond A and B (e.g.,
  diagnostic-only flags, deprecation toggles). Defer until concrete
  examples arise.

- Whether the FORBIDDEN state enforcement should be hard-failing
  (refuse service start) or graceful-degrading (hold affected phase
  in DORMANT, continue others). ADR recommends graceful-degrading;
  implementation may revisit.

- adr-historian prompt update timing. Track as follow-up issue if
  not addressed within 2 weeks of this ADR's merge.
