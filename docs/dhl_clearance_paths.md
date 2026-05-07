# DHL Clearance Paths — Canonical Business Spec

This document is the locked business contract for DHL customs clearance
in the Estrella Jewels operations system. Every code change touching
DHL clearance, customs dispatch, agency routing, or the dashboard
readiness cascade must conform to this spec. Deviations require an
explicit spec amendment in this file before code lands.

## Stage 0 — Upload (shared by both paths)

| Step | Action | Output |
|---|---|---|
| 0.1 | Operator uploads shipment documents to the system with batch number | Batch record created |
| 0.2 | System reads total invoice value | Numeric total |
| 0.3 | System classifies clearance path based on value | `clearance_path = "dhl_self_clearance"` if total < USD 2500, else `clearance_path = "agency_clearance"` |
| 0.4 | Path is recorded on the batch and does not change unless invoice value is corrected and re-evaluated | Path is fixed for downstream logic |

## Path A — `dhl_self_clearance` (value < USD 2500)

DHL Agencja Celna handles clearance themselves. No agency involvement.
No DSK.

| Stage | Trigger | TO | CC | Attachments |
|---|---|---|---|---|
| **A1** Generate Polish Description | Operator action (or auto after upload) | — | — | Polish Description PDF created |
| **A2a** Proactive dispatch to DHL | Automatic — system does not wait for DHL | `odprawacelna@dhl.com` | `info@estrellajewels.eu`, `import@estrellajewels.eu`, `account@estrellajewels.eu` | AWB + invoice + Polish Description + clearance-type instruction |
| **A2b** Same-thread reply to DHL | DHL sends `T#... Agencja Celna DHL` email | Same thread | Internal CC as above | AWB + invoice + Polish Description + clearance-type instruction (same payload as A2a) |

**Closure:** DHL Agencja Celna clears the shipment. Path A complete.

### Path A reply payload — clearance-type instruction

The reply payload for both A2a and A2b must include an explicit
clearance-type designation addressing item 4 of DHL's customs
clearance email template ("Indicate the type of customs clearance").

Default value: **"release for free circulation"** (Polish:
**"dopuszczenie do obrotu"**).

The system uses this default unless an operator explicitly selects
a different procedure (transit / special procedure / shipment
transfer / returned goods). Default selection requires no operator
action.

## Path B — `agency_clearance` (value ≥ USD 2500)

AC Spedycja handles clearance. We notify the agency at upload, send
DSK to DHL only when DHL asks, then forward the complete package to
the agency once DHL issues the official DSK.

| Stage | Trigger | TO | CC | Attachments |
|---|---|---|---|---|
| **B1** Agency notification at upload | Automatic at upload — no operator approval | `piotr@acspedycja.pl`, `ciagarlak@ganther.com.pl` | `biuro@acspedycja.pl`, `roman@acspedycja.pl` + `info@estrellajewels.eu`, `import@estrellajewels.eu`, `account@estrellajewels.eu` | AWB + invoice + product description |
| **B2** Reply to DHL when DHL asks | DHL sends email asking about goods/material — system waits, no proactive send. Operator generates DSK via the "Generate DSK" dashboard action; the observer fires automatically on the next sweep once `audit.dsk_filename` is populated. | DHL same thread | `info@estrellajewels.eu`, `import@estrellajewels.eu`, `account@estrellajewels.eu` | Operator-generated DSK PDF only — no description, no invoice, no AWB, nothing else |
| **B3** DHL issues official DSK | DHL sends back the official DSK to us and AC Spedycja directly | — | — | DHL's email reaches both parties via DHL's own routing |
| **B4** Forward complete package to agency | After we receive DHL's official DSK | `piotr@acspedycja.pl`, `ciagarlak@ganther.com.pl` | `biuro@acspedycja.pl`, `roman@acspedycja.pl` + `info@estrellajewels.eu`, `import@estrellajewels.eu`, `account@estrellajewels.eu` | AWB + invoice + product description + DSK from DHL |

**Closure:** AC Spedycja has full document set. Agency processes
customs clearance. Path B complete.

## Recipients reference

### DHL
- `odprawacelna@dhl.com` — DHL Agencja Celna customs intake

### AC Spedycja (Path B agency)
- `piotr@acspedycja.pl` — AC Spedycja primary contact (TO)
- `biuro@acspedycja.pl` — AC Spedycja office (CC)
- `roman@acspedycja.pl` — AC Spedycja (CC)
- `ciagarlak@ganther.com.pl` — Grzegorz Ciągarlak, forwarder, intermediary between Estrella and AC Spedycja (TO on every agency-bound send — B1, B4, and agency follow-up reminders — alongside Piotr)

### Estrella internal
- `info@estrellajewels.eu`
- `import@estrellajewels.eu`
- `account@estrellajewels.eu`

These three are CC on every dispatch in both paths.

## Tracking-driven triggers

The DHL Unified API tracking stream is the authoritative signal for
shipment progression. The system uses specific tracking events to
trigger spec actions and to refine operator UX in the cascade.

### Empirical timing reference

Observed Path A timing for AWB 6049349806 (locked as the canonical
reference case):

| Event | Time |
|---|---|
| Arrived at DHL Sort Facility WARSAW | 06:50 |
| Processed for clearance / Clearance Event at WARSAW | 07:25 |
| DHL Agencja Celna email arrives | 07:41 |

**Total time from Warsaw arrival to DHL email: ~51 minutes.**
**Time from `Clearance Event` to DHL email: ~16 minutes.**

These intervals inform the cascade's confidence levels and overdue
escalation thresholds.

### Path A triggers

| Tracking event | Spec stage | System behaviour |
|---|---|---|
| Upload completes + invoice classified as Path A | A1 | Generate Polish Description (auto) |
| `Departed origin` (first occurrence per AWB) | A2a | If validation passes: auto-create + auto-approve + auto-queue proactive dispatch. If validation fails: create proposal for operator approval. |
| `Arrived at DHL Sort Facility WARSAW` | — | Cascade enters "DHL processing" sub-state. No new action. |
| `Clearance Event` at Warsaw | — | Cascade enters "DHL email imminent" sub-state. Operator UX shows "expected within minutes." |
| DHL email arrives (subject contains `T#... Agencja Celna DHL`) | A2b | Cascade switches primary action to "Reply to DHL in same thread." Reply payload identical to A2a. |
| `Clearance Event` fired >2h ago, no DHL email matched | — | Cascade escalates to "Run Find DHL Emails — overdue." |

### Path B triggers

| Tracking event | Spec stage | System behaviour |
|---|---|---|
| Upload completes + invoice classified as Path B | B1 | Auto-send agency notification (no proposal, no approval). |
| `Departed origin` | — | No action. Path B waits for DHL. |
| `Arrived at WARSAW` | — | No action. Cascade shows "awaiting DHL goods inquiry." |
| `Clearance Event` at Warsaw | — | No action. Cascade shows "DHL likely to inquire shortly." |
| DHL email arrives asking about goods | B2 | Cascade switches primary action to "Send DSK to DHL in same thread." Reply payload: DSK only. |
| DHL replies with official DSK | B4 | Cascade switches primary action to "Forward complete package to AC Spedycja." |

### Validation rules for Path A auto-queue

Auto-queue at `Departed origin` requires all of the following checks
to pass:

- Invoice value is present and numeric
- Path classification is `dhl_self_clearance`
- Polish Description PDF generated successfully and file exists on disk
- Invoice files attached and file count >= 1
- AWB PDF attached
- Recipient `odprawacelna@dhl.com` resolved at queue time
- Internal CC addresses (`info@`, `import@`, `account@estrellajewels.eu`) all resolved at queue time

If any check fails, the tracking event creates a proposal instead of
auto-queuing. The proposal carries a `validation_failure_reason`
field explaining which check failed. Operator must approve and queue
the proposal manually.

### Tracking event idempotency

Tracking events can re-fire across polling cycles. All tracking-
driven triggers must check existing batch state before firing:

- `Departed origin` → A2a: skip if proactive dispatch already
  queued/sent for this AWB.
- DHL email → A2b: skip if our_dhl_reply already sent for this
  thread.
- DHL email → B2: skip if DSK reply already queued/sent for this
  thread.

Each trigger is "fire exactly once per AWB per spec stage."

## Hard rules

1. **Path classification is value-driven and immutable.** Set once at upload from invoice total. Re-evaluation requires invoice correction — not an operator override.
2. **Path A has no agency involvement.** Stage B1 does not exist for Path A.
3. **Path B has no proactive DHL send.** Stage B2 fires only when DHL asks. The system waits.
4. **Path B Stage B1 is automatic.** No proposal, no operator approval, no queue gate. Upload completion triggers it.
5. **Stage B2 attachment is the operator-generated DSK PDF only**, sent on the same email thread DHL initiated. CC layout is Estrella internal only (`info@`, `import@`, `account@estrellajewels.eu`). No description, no invoice, no AWB on the B2 reply. The DSK is generated via the operator-clicked dashboard action ("Generate DSK"); the B2 observer skips silently when `audit.dsk_filename` is absent and re-evaluates on the next sweep once the operator has generated it.
6. **Internal CC is on every send in both paths.**
7. **Agency recipient layout is identical for all agency-bound emails (B1, B4, and agency follow-up reminders).** TO is `piotr@acspedycja.pl` and `ciagarlak@ganther.com.pl` on every send. CC is `biuro@acspedycja.pl`, `roman@acspedycja.pl`, plus the three Estrella internal addresses.
8. **No customs/financial value modification anywhere.** The `customs-value-freeze` skill applies to every step.
9. **No auto-send for any approval-gated action.** Stage B1 and Path A A2a (when validation passes) are the only automatic dispatches in the system. Both are gated by deterministic upload/tracking triggers, not by clearance state guesswork.
10. **Path A reply payload includes explicit clearance-type instruction.** Default "release for free circulation" / "dopuszczenie do obrotu". Applies to A2a and A2b identically.
11. **Tracking-driven triggers are idempotent.** Each trigger fires exactly once per AWB per spec stage. Re-polling does not re-fire.
12. **Path A auto-queue is gated by validation.** When validation fails at the `Departed origin` event, the trigger creates a proposal for operator approval instead of auto-queuing.

## Amendment policy

This spec is the authoritative reference. Code that contradicts it is
incorrect, regardless of how long the contradicting code has existed.
To change the spec:

1. Open a discussion with the operations owner.
2. Update this file in the same change-set as any code that depends on
   the new behaviour.
3. Cite the commit hash of the spec amendment in the implementing
   commit message.

Code-only changes that contradict this spec must be rejected at review.
