# ADR-015: DHL self-clearance — thread-based clarification (P5)

Status: Accepted
Date:   2026-05-10
Phase:  W-5 / P5

## Context

After ADR-014's scheduler enters `dhl_requested_clarification`,
DHL has asked for additional information (typically: goods
description, invoice clarification, authorization, or sometimes
a SAD-receipt confirmation). The team had to decide *where* to
reply:

- in the existing thread DHL opened (or that ADR-013's dispatch
  email seeded),
- in a new thread keyed by request type.

Operational memory recorded the strict rule: **one AWB = one
thread**, no exceptions. ADR-012 hard lock 4 already states the
invariant; ADR-015 attaches the operational behaviour to it.

The secondary decision was *what to classify in the
clarification request*. Memory enumerated four intent classes:
goods description, invoice, authorization, SAD received.

## Decision

**Reply locus.** All clarification replies are sent in the same
thread DHL used to request clarification. The engine MUST NOT
open a new thread for any reason. If the engine cannot identify
the existing thread for a given AWB, it stops and flags the
shipment for operator review rather than guessing.

**Intent classification on the inbound clarification.** When DHL
sends a clarification request, the engine classifies the
request into one of four intents:

| Intent | Reply contents |
|---|---|
| `goods_description` | Bilingual product description aligned to the *customs* description (CIF context — see ADR-016 cross-ref) |
| `invoice` | Re-attached commercial invoice (FOB structure preserved); never a regenerated value |
| `authorization` | Clearance authorization document (operator-facing prerequisite) |
| `sad_received` | Acknowledgement; transitions to `awaiting_sad` if SAD itself is the next inbound, else closes clarification |

Unclassified requests go to operator review. The classifier
never invents a fifth intent.

**State transitions.**

- On clarification-reply send → `clarification_sent`.
- On SAD / PZC inbound → `awaiting_sad` then `sad_received`
  (handled by ADR-016).
- On further DHL clarification while in `clarification_sent` →
  re-enter `dhl_requested_clarification`; same thread.

**Audit obligations.** The audit trail records:

- the inbound clarification message-id + classified intent,
- the outbound reply message-id + thread-id,
- a hash of the reply contents (never the contents themselves —
  ADR-006).

**Hard lock recap.** ADR-012 hard lock 4 (one AWB = one thread)
is binding here. ADR-015 codifies the operational behaviour
that satisfies it.

## Rejected alternatives

- **Open a new thread keyed by intent.** Rejected — DHL's
  customs operators chase context through thread history; a new
  thread loses that history and risks contradictory replies.
- **Auto-reply on any inbound DHL email regardless of intent.**
  Rejected — non-clarification inbounds (status updates,
  confirmations) must not be answered, or DHL stops reading our
  replies.
- **LLM-only classification.** Rejected as an architectural
  default — implementation may use a classifier (see ADR-014
  cross-ref to memory) but unclassified requests must always
  fall back to operator review, never to a guess.

## Risks

- **Thread-id loss.** If the engine loses the thread-id (mail
  account migration, label rebuild), the reply locus is
  unknown. Mitigation: persist the thread-id on the shipment
  manifest at every inbound classification.
- **Classifier drift.** Adding new intent types in the future
  is a behaviour change; it requires a new ADR superseding
  ADR-015's intent table.
- **Operator override race.** If an operator replies manually
  while the engine is preparing an automated reply, two replies
  land in the thread. Mitigation: the engine takes a per-thread
  reply lock; operator manual reply releases the lock and the
  engine yields. (Implementation detail — codified in the
  eventual phase.)

## Rollback

Disabling the clarification-reply feature flag (default-OFF per
ADR-010) reverts the engine to "flag for operator review" on
every inbound clarification. The thread-id persistence remains
useful for operator visibility and is not rolled back with the
flag.

## Future impact

- Establishes the operational discipline that any
  carrier-customs interaction is thread-keyed. If a future
  carrier (FedEx, UPS) is added, the same model applies until a
  successor ADR amends it.
- The intent classifier becomes a small, audited subsystem with
  a fixed taxonomy. New intents = new ADR.

## Related

- ADR-012 (hard lock 4: one AWB = one thread)
- ADR-013 (seeds the thread)
- ADR-014 (entry: `dhl_requested_clarification`)
- ADR-016 (exit: SAD / PZC handling)
- ADR-006 (audit hashes only, not content)
- ADR-010 (default-OFF feature flags)
