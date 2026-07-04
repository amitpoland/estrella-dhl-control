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

## Ledger

| # | Page (slug/tab) | Control | Expected behavior | Actual behavior | Screenshot | Severity | Class | Status | Fix commit |
|---|---|---|---|---|---|---|---|---|---|
| _(empty — awaiting the operator's first defect batch)_ | | | | | | | | | |

---

## Working rules (per the operator execution order)

1. Each operator finding → one row here (verbatim expected/actual + the screenshot the operator provides or a filename under `reports/wave3/cp3/defects/`).
2. INTERACTION rows fixed first, in severity order (BLOCKER → MAJOR → MINOR), each fix a slice through the ten-criterion gate, committed with a `fix(w3-cp3-<n>)` message referencing the row.
3. VISUAL rows accumulate; the **Visual Bug Sweep** slice runs only once every INTERACTION row is CLOSED.
4. After a fix, regenerate ONLY the affected page's CP3 composite(s); update INDEX.md.
5. Status values: OPEN · IN-PROGRESS · FIXED (verified in Preview + gate) · WONT-FIX (operator-ruled) · DEFERRED-VISUAL.
6. No deployment activity until the operator's acceptance word.
