# ADR-012: DHL self-clearance — flow overview

Status: Accepted
Date:   2026-05-10
Phase:  W-5 — DSK forward + DHL self-clearance (memory sequestration)

## Context

For low-value DHL shipments where no external customs agency is
engaged and no Direct Send Kit (DSK) applies, the customs path is
the sender's responsibility (self-clearance). Operational memory
(`dhl_selfclearance_flow.md`, revised 2026-05-07) captured a
seven-phase workflow but lived in agent memory only — risk of
drift if memory is lost. Per program-board debt **D-6**, the
operational decisions need permanent ADR capture without
implementation speculation.

ADR-012 is the umbrella: it names the scope gate, the phase
sequence, the hard locks, and the automation states. Phase-level
decisions (P2 dispatch, P3+P4 follow-up, P5 clarification, P6+P7
SAD unlock + PZ) are sequestered into ADR-013 through ADR-016.

## Decision

**Scope gate.** The self-clearance flow applies *only* when all
hold:

- carrier = DHL,
- declared shipment value below the self-clearance threshold,
- no external customs agency engaged,
- no DSK in scope.

If any condition fails, the shipment falls back to the existing
agency-forward / DSK paths (out of scope for ADR-012..016).

**Canonical phase sequence (reference only — execution is
defined in the per-phase ADRs):**

| Phase | Trigger | Effect |
|---|---|---|
| P1 | Shipment created; AWB known | (auth + identity prerequisites; out of scope here) |
| P2 | Immediately after AWB | Proactive customs package dispatched to DHL customs mailbox |
| P3 | Continuous | Tracking watcher monitors transit events |
| P4 | Poland arrival OR customs-processing state observed | Follow-up loop activates (2h working hours; slower overnight) |
| P5 | DHL sends clarification request | Reply in the same thread |
| P6 | SAD / PZC received | Store docs, link to shipment, unlock PZ |
| P7 | SAD / PZC linked | Run PZ pipeline |

**Automation state machine.** The ordered states the engine
moves a shipment through:

```
awaiting_preemptive_send
  → awaiting_poland_arrival
  → followup_active
  → dhl_requested_clarification
  → clarification_sent
  → awaiting_sad
  → sad_received
  → pz_unlocked
  → shipment_closed
```

State transitions are append-only; no backward transition is
permitted in production state. Human override is a separate
operator action (out of scope here).

**Hard locks (invariants that bind every phase).**

1. Never generate PZ before SAD / PZC exists.
2. Never move inventory lifecycle before customs completion is
   confirmed.
3. Never use the agency-forward flow on a self-clearance path.
4. Never open a second DHL customs thread — one AWB = one
   thread.

**Workflow shape.** The flow is *thread-centric* (DHL email
thread is the source of truth for clarification state),
*AWB-centric* (AWB is the join key across mail, tracking, and
customs state), and *customs-state-driven* (transitions fire on
observed customs state, not on operator clicks or dashboard
actions).

## Rejected alternatives

- **Manual operator-driven dispatch.** Rejected because it
  defers customs initiation to operator availability; the whole
  point of self-clearance automation is to compress the
  customs-delay window by firing dispatch the moment the AWB is
  known.
- **Per-event new email thread.** Rejected because DHL's
  clarification model assumes one thread per AWB; opening a
  second thread fragments the audit trail and risks
  contradictory clarifications.
- **Agency-forward-with-fallback.** Rejected because mixing
  paths inside one shipment makes evidence reconstruction
  ambiguous; self-clearance is its own end-to-end flow.

## Risks

- **Memory-only spec.** Closed by this ADR series.
- **Cross-flow drift.** If the agency-forward flow evolves
  separately, scope-gate boundaries can blur. Mitigation: the
  per-phase ADRs (013-016) name the specific files / functions
  to be touched if/when the flow is implemented; agency-forward
  changes that affect those surfaces require a successor ADR.
- **Implementation speculation.** This ADR records *what was
  decided*, not *how to build it*. Implementation phases that
  follow must satisfy the invariants here without re-deciding
  them.

## Rollback

The ADR is rollback-cheap: it captures decisions, not code. If a
future ADR supersedes this overview, this file remains in place
with a "Superseded by ADR-NNN" header. Any code path implemented
on top of these decisions has its own rollback per the
phase-level ADR.

## Future impact

- ADR-013 through ADR-016 inherit this overview's scope gate,
  state machine, and hard locks.
- Any later proposal to relax a hard lock (e.g., allow PZ before
  SAD under a constrained exception) requires a new ADR with an
  explicit supersession.
- Implementation must persist `awaiting_poland_arrival=true` on
  the shipment manifest after P2 fires, so recovery / replay can
  reconstruct state from manifest alone.

## Related

- ADR-001 (carrier abstraction)
- ADR-005 (no live AWB persistence — does not apply here because
  self-clearance is a customs flow, not a label-issue flow, but
  the "evidence-only" discipline transfers)
- ADR-006 (no PDF bytes / credentials in evidence stores)
- ADR-013, ADR-014, ADR-015, ADR-016 (per-phase decisions)
