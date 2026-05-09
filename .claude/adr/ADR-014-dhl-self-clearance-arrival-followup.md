# ADR-014: DHL self-clearance — Poland-arrival follow-up scheduler (P3 + P4)

Status: Accepted
Date:   2026-05-10
Phase:  W-5 / P3 + P4

## Context

After ADR-013's proactive dispatch fires, the shipment is in
`awaiting_poland_arrival`. There are two operational questions:

- *When* does the engine know the package has arrived in Poland?
- *How often* does it follow up if DHL has not yet replied
  with clarification or with the SAD / PZC?

The naive approaches both fail. Polling DHL email constantly
floods the mail account; firing follow-ups on a wall-clock
schedule (e.g., daily) loses the time-compression benefit ADR-013
won.

Operational memory recorded a two-part decision: a continuous
*tracking watcher* (P3) and a *follow-up scheduler* (P4) keyed
on Poland-arrival or customs-processing state. ADR-014 captures
both as one decision because they are inseparable — the tracker
is what triggers the scheduler.

## Decision

**P3 — Tracking watcher.** A continuous (engine-driven, not
operator-driven) process monitors DHL tracking state for every
shipment in `awaiting_poland_arrival`. Watched signals:

- Poland-arrival scan,
- customs-processing state entry,
- customs-hold state entry,
- delay or rejected-paperwork events.

The watcher does not act on transit-only events (departure, in
transit). It activates the follow-up scheduler only when one of
the named signals fires.

**P4 — Follow-up scheduler.** Once activated, the scheduler
enters `followup_active`. Cadence:

- Working hours (CET): every 2 hours.
- Outside working hours (overnight, weekend, holiday): slower
  (the implementation phase will codify the exact slower
  interval; ADR-014 fixes the policy, not the seconds).

What "follow-up" means: re-check the DHL email thread *and* the
DHL tracking state. **Never** open a new email thread; ADR-012
hard lock 4 still binds.

**State transitions out of `followup_active`:**

- DHL replies with a clarification request → `dhl_requested_clarification`
  (handled by ADR-015).
- SAD / PZC arrives directly without further clarification →
  `awaiting_sad` then `sad_received` (handled by ADR-016).
- Tracking shows release without paperwork in mail → engine flags
  for operator review; not auto-progressed.

**Operator visibility.** Every state entry is timeline-logged
(per the project's existing audit pattern). The dashboard surface
for this is W-2 work, out of scope here.

## Rejected alternatives

- **Cron-only follow-up (no tracking watcher).** Rejected —
  fires follow-ups uniformly across shipments regardless of
  customs state, wasting DHL goodwill and operator attention.
- **Webhook-only (push from DHL).** Rejected — DHL's customs
  mail flow is not a push API; tracking webhooks exist but do
  not reliably surface customs-state transitions.
- **Email-poll-every-N-minutes.** Rejected — floods the mail
  account; cadence is not customs-state-aware.

## Risks

- **Tracking-event lag.** DHL's tracking event for Poland
  arrival can lag the physical event. Mitigation: the watcher
  also activates on customs-processing-state entry, which
  cannot fire before arrival.
- **Working-hours definition drift.** "Working hours" must be a
  config constant, not hardcoded in scheduler code. The
  implementation phase will name the config key.
- **Scheduler livelock.** If a shipment lingers in
  `followup_active` indefinitely (DHL silent, no SAD), the
  engine must escalate to operator review after a configurable
  budget (the implementation phase decides the budget; ADR-014
  fixes the requirement that one exists).

## Rollback

The follow-up scheduler is a service-level component with its
own feature flag (default-OFF per ADR-010). Disabling the flag
freezes the scheduler; in-flight shipments fall back to manual
operator follow-up. The tracking watcher can be paused
independently if it overruns DHL's allowed query rate.

## Future impact

- Establishes the model for any future carrier-watcher: pair a
  state-aware tracker with a state-driven scheduler.
- The `followup_active` state will be the single "lingering"
  state visible to operators on the dashboard W-2 surface; UX
  must surface elapsed time + last DHL signal.
- Any future DHL push channel (if DHL exposes one) supersedes
  the tracking watcher via a new ADR; the scheduler logic
  survives.

## Related

- ADR-012 (umbrella)
- ADR-013 (the prior phase; transitions us into
  `awaiting_poland_arrival`)
- ADR-015 (the next phase; consumes
  `dhl_requested_clarification`)
- ADR-010 (default-OFF feature flags)
