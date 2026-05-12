# ADR-013: DHL self-clearance — proactive customs dispatch (P2)

Status: Accepted
Date:   2026-05-10
Phase:  W-5 / P2

## Context

When a self-clearance DHL shipment is created and the AWB is
known, the team had two options for when to dispatch the
customs package to DHL's customs mailbox:

1. Wait for DHL to email asking for documents (reactive).
2. Send the customs package immediately on AWB issuance
   (proactive).

Option 1 makes the customs-delay window unbounded — DHL's
request can arrive hours or days after the package is in
transit, by which time the shipment is already stuck in customs
hold. Option 2 compresses the delay window because the customs
package is on DHL's side before they even ask.

Operational memory (revised 2026-05-07) recorded the decision to
adopt option 2. ADR-013 sequesters that decision.

## Decision

**Trigger.** Immediately after the shipment row reaches a state
in which the AWB is known and stable. No waiting on DHL's first
clarification email.

**Action.** Send a single proactive customs dispatch email to
the DHL customs mailbox, in the *same* thread that all future
clarifications will use (per ADR-012 hard lock 4).

**State on entry.** `awaiting_preemptive_send`.
**State on success.** `awaiting_poland_arrival`.
**State on failure.** Error state (out of scope here); the
shipment remains in `awaiting_preemptive_send` and the operator
sees the failure on the dashboard.

**Manifest contract.** After successful dispatch, the shipment
manifest must persist:

- the message-id of the dispatch email,
- the recipient mailbox (constant — DHL customs),
- the dispatch timestamp,
- a hash of the customs-package contents (for replay
  verification; never the contents themselves — see ADR-006).

**Idempotency.** A second proactive dispatch attempt for the
same AWB is a no-op when the manifest already records a
successful dispatch message-id. This is the same idempotency
principle adopted in ADR-005 / DL-F3.5a for shipment creation:
the trigger is keyed by AWB, not by request count.

## Rejected alternatives

- **Wait for DHL's first clarification email** (reactive).
  Rejected — it makes the customs-delay window operator-blind
  and unbounded.
- **Dispatch from the dashboard manually.** Rejected — defers
  the action to operator availability and breaks the
  one-AWB-one-thread invariant when the operator forgets which
  thread to reply in.
- **Dispatch via a separate per-event email per document.**
  Rejected — fragments the audit trail and fights ADR-012 hard
  lock 4.

## Risks

- **Dispatch-before-AWB-stable.** If the AWB is later voided or
  re-issued, the proactive email refers to a stale AWB.
  Mitigation: gate the trigger on the carrier state engine's
  AWB-stable signal, not on the bare presence of an AWB string.
- **DHL customs mailbox change.** A future change to the DHL
  customs mailbox address requires a config update; the manifest
  records the recipient at dispatch time so replay against an
  old shipment is unambiguous.
- **Customs-package content drift.** Future product / customs
  description changes must continue to align with CIF valuation
  context (see ADR-016 cross-reference); proactive dispatch must
  not pre-bake stale descriptions.

## Rollback

Disable the proactive trigger via config (the implementation
phase will land it default-OFF per ADR-010). Reverting to
reactive dispatch is one config flip; existing in-flight
shipments continue to be served by the manual / reactive path
that remains compiled in.

## Future impact

- Implementation will need a coordinator-level guard that the
  AWB is stable (analogous to the carrier coordinator's lock
  pattern). The implementation ADR / commit will reference this
  ADR-013 and not re-decide the dispatch trigger.
- The "same thread" obligation here is what ADR-015 enforces in
  the clarification phase; the dispatch email seeds that thread.

## Related

- ADR-012 (umbrella; hard locks)
- ADR-010 (default-OFF feature flags — applies to the dispatch
  trigger)
- ADR-006 (no credentials in evidence; manifest stores a hash
  not the package)
- ADR-015 (thread-based clarification — depends on this ADR's
  thread seeding)
