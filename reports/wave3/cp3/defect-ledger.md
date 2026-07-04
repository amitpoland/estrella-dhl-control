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

## PERMANENT RULE — Reclassify before writing code (operator, 2026-07-04)

**If investigation disproves the reported defect, STOP. Reclassify it before
writing any code.** The ledger is a permanent engineering record, not a change
log — separating *bugs*, *works-as-designed*, and *UX improvements* preserves
its integrity (else a future reader sees "Fixed Export bug" when there was no
export bug — the #002/#003 correction below).

A code change never lands under a record whose investigation disproved it.

### Classification model (operator, 2026-07-04 — FINAL, complete)

| Category | Meaning | Code change? |
|---|---|---|
| **Bug** | System behavior contradicts the specification / expected behavior. | Yes |
| **Works as Designed (WAD)** | The report is disproved. Current behavior is correct. | No |
| **UX Improvement** | Behavior is correct, but the experience can be made clearer/easier. | Yes |
| **Feature Request** | New capability that does not exist today. | Yes — but **not** under the original defect ID |

Classification gate (run before any code):

```
Report received → Investigate
        ├── Spec violated?           → Bug
        ├── Spec satisfied?
        │      ├── UX could improve? → UX Improvement
        │      └── No               → Works as Designed
        └── Capability doesn't exist? → Feature Request (new ID, not the report's)
```

Consequences (why this matters): **Defect IDs never change meaning · commits
always correspond to the correct category · the audit trail stays trustworthy.**
The classification model is now complete — no further process changes.

## Defects

### Defect #003
- **Type:** UX Improvement (not a bug)
- **Page:** Inventory · **Control:** Header "↓ Export" button
- **Severity:** Medium (3) · **Class:** INTERACTION/UX
- **Title:** Export button should explain why export is unavailable.
- **Origin:** reclassified from the #002 investigation — the export works, but a disabled button with no visible reason reads as broken.
- **Change:** Export is always clickable. With loaded rows → downloads the filtered CSV (the existing, correct path — unchanged). With none → renders an inline `inv-hdr-export-hint` message naming exactly what to do (open a data tab / load records), so the control always produces a visible response. Muted styling stays as a "nothing to export yet" cue. No wireframe redesign — the header Export control is preserved.
- **Fix commit:** `4f6d75e5` (`service/app/static/v2/inventory-page.jsx`).
- **Verification checklist:**
  - Behavior in Preview (localhost:60991): ✅ button enabled (cursor pointer) on Overview + Sample Out; both hint variants render on click; all 11 inventory tabs re-walked — Export present + responsive on each.
  - No related console errors: ✅ (clean across the tab walk).
  - Wireframe match holds: ✅ header Export control present per wireframe; inline hint is interaction feedback, not a layout change.
  - Affected CP3 screenshot regenerated: ✅ `pair-08-inventory.png` live-right refreshed.
- **Status:** CLOSED (commit `4f6d75e5`; no regression — all 11 Inventory tabs re-walked clean).

### Defect #002
- **Page:** Inventory
- **Control:** Header "↓ Export" button
- **Reported:** "The Export button doesn't do anything." Expected: export the currently filtered rows.
- **Disposition:** **CLOSED — Works As Designed (WAD).**
- **Reason:** Investigation disproved the report. The export implementation was already correct: it exports the filtered rows, the `exportCsv` download path works, and the button is *intentionally* disabled when the active tab has no rows to export (Overview always; data tabs until records load — empty in dev). No functional defect found.
- **Record-keeping note:** the reported symptom is a UX shortcoming (the disabled state gives no obvious feedback), NOT an export bug. That UX work is tracked separately as **Defect #003** — see below. No code changed under this record.

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
