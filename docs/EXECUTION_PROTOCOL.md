# EXECUTION_PROTOCOL.md — Lean Execution Protocol

> Permanent, repo-owned. Defines how one unit of work moves from idea to closed.
> Subordinate to CLAUDE.md GATES 1–6 and the 7-agent deploy gate; where this file
> and a CLAUDE.md GATE disagree, the GATE wins.

The goal of this protocol is narrow and load-bearing: **future work must not restart
solved problems, lose decisions, or close without evidence.** Every rule below exists
to defend one of those three.

---

## 1. One task = one PR-sized slice

A task is a single, reviewable, independently-shippable slice — the amount of change
one reviewer can hold in their head and one rollback command can revert. If a task
cannot be expressed as one PR-sized slice, it is not a task yet; decompose it first.

- No "while I'm in here" scope creep. Out-of-scope findings become a NEW task entry
  in `tasks/todo.md`, not extra commits on this branch.
- A slice that grows past its frozen scope mid-flight is split, not stretched.

## 2. Authority owner named before coding

Before a single code file is opened, name the **authority owner**: the one system that
owns the truth being changed. Candidates in this repo: Invoice · Customs · Warehouse ·
Sales · Customer Master · Product Master · PZ lifecycle · wFirma · DHL · the relevant
`*_authority.py` module. (Lesson I, Step 2.)

- If the authority owner cannot be named, root cause is not understood — **do not code.**
- If two systems appear to own the same truth, that is a **duplicate-authority** defect.
  Resolve the authority question first; do not paper over it with a second writer.

## 3. Acceptance criteria frozen before implementation

Write the acceptance criteria, agree them, and **freeze** them before implementation
begins. Frozen means: recorded in the task entry / PR before the first implementation
commit, and not edited afterward to match whatever got built.

- Criteria are observable and binary: "endpoint returns 200 with field X", not
  "endpoint works better."
- If reality forces a criteria change mid-task, stop, amend the frozen criteria
  explicitly (with a note on why), and have the reviewer re-baseline — never silently.

## 4. The builder cannot grade itself

The agent/person who implements a slice does not get to declare it done. Self-grading
is how fake-green ships. (CLAUDE.md GATE 1; Lesson A.)

- Builder produces evidence; a separate reviewer judges that evidence against the
  frozen criteria.
- "It compiles" and "unit tests pass" are inputs to the judgment, not the judgment.

## 5. Reviewer checks code against the frozen criteria

The reviewer's job is not "does this look reasonable" — it is "does this satisfy each
frozen acceptance criterion, with evidence." The reviewer walks the criteria list and
marks each PASS / FAIL / VERIFY-GAP against the actual diff and the actual evidence.

- A criterion with no evidence is not PASS — it is VERIFY-GAP, and VERIFY-GAP blocks
  closure until resolved or explicitly accepted by the operator.
- The reviewer also checks: no out-of-scope file edits; no capability suppressed
  without a cancellation record (Lesson M); no sensitive write without approval.

## 6. No closure without the full evidence set

A task is closed only when ALL of the following exist (see `PROJECT_STATE.md` →
Required Evidence Format and `.github/pull_request_template.md`):

1. Tests run with pass/fail counts vs baseline (failures stated honestly).
2. Browser/API verification (UI: load + console + network; backend/admin: curl +
   audit log; "N/A — no surface" only when literally true).
3. Rollback path (exact command / SHA).
4. `PROJECT_STATE.md` updated to move the slice to its correct section.

Missing any one → the task is **not closed.** "Recommendation noted" is not closure
(CLAUDE.md GATE 4). Evidence beats narrative.

## 7. Recurring bugs require authority review, not another patch

If a bug returns after it was "fixed," the problem is not the bug — it is the authority
model. Stop patching the symptom. (Lesson I.)

- A returning bug triggers a **duplicate-authority search**: who else writes/derives
  this truth? The fix consolidates authority, adds a guard or lifecycle state, and
  adds a regression test — it does not add a second patch in a second place.
- Convert the incident into a workflow-class rule (Lesson I, six-step framework), not
  a shipment-specific patch.

---

## Closure gate (checklist)

A slice is DONE only when every box is true:

- [ ] One PR-sized slice; no scope creep (out-of-scope → new `tasks/todo.md` entry)
- [ ] Authority owner named before coding
- [ ] Acceptance criteria frozen before implementation
- [ ] Built by builder, **graded by a different reviewer** against frozen criteria
- [ ] Tests run; counts vs baseline recorded; failures stated honestly
- [ ] Browser/API verification captured (or "N/A — no surface", truthfully)
- [ ] Rollback path written (command / SHA)
- [ ] `PROJECT_STATE.md` updated
- [ ] Sensitive-system impact declared (financial / customs / inventory / DHL /
      wFirma / accounting / production-write) + operator approval if touched
- [ ] No capability suppressed without a cancellation record (Lesson M)

## Relationship to CLAUDE.md gates

This protocol is the lightweight, per-task expression of the heavyweight governance in
CLAUDE.md. It does not replace it:

- **GATE 1** (PR open discipline) — §4–§6 here are its per-task form.
- **GATE 4** (salvage disposition) — §6 "no recommendation-noted closure."
- **Lesson A** (real return shapes) — §4 builder-can't-self-grade.
- **Lesson I** (workflow-class fixes) — §7 recurring-bug authority review.
- **Lesson M** (capability preservation) — closure-gate suppression check.
- **7-agent deploy gate** — unchanged; production sync is always operator-gated and
  out of scope for this protocol.
