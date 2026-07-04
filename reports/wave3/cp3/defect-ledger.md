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

## RULE 3 — CLOSURE GATE (operator, verbatim)

A defect cannot be CLOSED until:
- Status = VERIFIED
- The affected page still passes all previously verified defects
- No new defect was introduced on that page
- The ledger entry references the commit that fixed it

**Lifecycle (final, frozen):** OPEN → FIXED (code changed) → VERIFIED
(Preview + console + CP3 screenshot) → CLOSED (no regressions on the page +
fixing commit SHA recorded in the row). When a page's every defect is CLOSED,
the page is re-walked once to confirm no cross-defect regression before
moving on.

## Ordering (per the execution order)

- INTERACTION defects fixed first, in severity order (Critical → High → Medium → Low).
- VISUAL defects accumulate; the **Visual Bug Sweep** runs only once every
  INTERACTION defect is VERIFIED.
- Each fix is one slice through the ten-criterion gate, committed
  `fix(w3-cp3-<NNN>)` referencing the defect.
- No deployment activity until the operator's acceptance word.

---

## Triage rule — OPERATOR REVIEW HEURISTIC (operator, verbatim)

"Don't hunt for defects — use the application naturally. If something
interrupts your workflow or makes you hesitate, that is a more valuable
defect than ten cosmetic observations. Before logging any defect ask:
'Would this slow me down if I used this application every day?' Yes ->
log it. No -> it waits for the visual polish phase.
Severity ladder: 1 Critical (crashes, broken workflows, incorrect
behavior) · 2 High (confusing UX, missing actions, wrong navigation) ·
3 Medium (layout inconsistencies affecting usability) · 4 Low (visual
polish, e.g. Defect #001).
Defect #001 stays OPEN but is not worked until interaction issues are
exhausted."

Severity = 1 Critical / 2 High / 3 Medium / 4 Low (replaces the earlier
Critical/High/Medium/Low labels 1:1). No hunting, no automated sweep; work only
operator-logged defects in interaction→severity order; #001 (Low) last, in the
visual-polish phase.

## Defects

### Defect #001
- **Page:** Global shell
- **Control:** Navigation / header icons
- **Severity:** Low · **Class:** VISUAL
- **Expected:** Consistent EJ icon system (SVG/glyph icons only, per the EJ design overrides — no emoji icons)
- **Actual:** Mixed emoji (🧾 🌿 🔔) and geometric glyph icons (▦ ◫ ≡ ⚙) in the same nav/header
- **Screenshot:** automated review 2026-07-04 (nav header, `/v2/dashboard` @ 1440px)
- **Root cause:** _(fill on fix)_
- **Fix:** _(fill on fix)_
- **Verification checklist:** _(on fix)_ Preview behavior · no console errors · wireframe match holds · CP3 shell composite regenerated
- **Status:** OPEN

> Queue note: Low/VISUAL — does NOT jump the queue. Interaction defects from the
> operator's review are worked first (frozen ordering); #001 is worked when the
> operator reaches visual polish, or immediately on the operator's word.
