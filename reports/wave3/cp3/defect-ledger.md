# Wave-3 CP3 — Operator Defect Ledger

**Mode:** CP3 defect-driven (operator execution order 2026-07-04). Implementation
FROZEN; no page rebuilds absent an operator finding. Interaction defects fixed
first (each through the 10-criterion gate); Visual Bug Sweep runs only after the
interaction rows below are all CLOSED; only affected CP3 composites regenerate.
CP4/deploy waits for the operator's acceptance word.

**Live review:** current Preview URL (localhost:54494 as of the hold; the
8135 zombie socket is NOT a release blocker per the ruling).

**Severity scale:** BLOCKER (wrong data / broken write / dead primary action) ·
MAJOR (wrong behavior, workaround exists) · MINOR (interaction rough edge) ·
VISUAL (alignment/spacing/overflow/typography — deferred to the Visual Bug Sweep).

**Class:** INTERACTION (fixed first) · VISUAL (Visual Bug Sweep, after interaction closed).

---

## Defect template (operator, verbatim — every defect uses this)

> Defect #NNN · Page · Control · Severity (Critical/High/Medium/Low) ·
> Expected · Actual · Screenshot · Root cause · Fix · Verification checklist ·
> Status (OPEN → FIXED → VERIFIED)

Each defect is recorded as a `### Defect #NNN` block (below) with those exact
fields. Severity = Critical / High / Medium / Low. Class stays a note
(INTERACTION vs VISUAL) so the ordering rule still applies.

## TWO ENFORCED RULES (operator, verbatim)

1. **NO BATCHING** — even 20 problems on one page = 20 separate defect rows.
   One change never masks another; each verifies independently.
2. **VERIFIED is behavioral, not code-state.** OPEN → FIXED when the code
   changes; FIXED → VERIFIED ONLY when ALL are true:
   - behavior confirmed in the Preview UI (localhost:54494)
   - no console errors related to the change
   - the wireframe match holds
   - the affected CP3 screenshot regenerated and reflects the fix

   "Code changed" alone is FIXED, never VERIFIED.

## Ordering (per the execution order)

- INTERACTION defects fixed first, in severity order (Critical → High → Medium → Low).
- VISUAL defects accumulate; the **Visual Bug Sweep** runs only once every
  INTERACTION defect is VERIFIED.
- Each fix is one slice through the ten-criterion gate, committed
  `fix(w3-cp3-<NNN>)` referencing the defect.
- No deployment activity until the operator's acceptance word.

---

## Defects

_(empty — awaiting the operator's first defect. One defect = one #NNN block below.)_
