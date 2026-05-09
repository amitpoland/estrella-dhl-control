# Execution Modes

The Coordinator operates in **exactly one** of three modes at a
time. Mode is declared at session start. Mixing modes is the
single biggest cause of drift.

This file is the formal mode contract. It supersedes the
"strategic vs execution" distinction in `engineering/session-discipline.md`
by *adding* RELEASE as a first-class mode and naming explicit
allowed/forbidden actions per mode.

> **No mode = no work.** A session that has not declared its mode
> is not a session — it is a context leak.

---

## Mode 1 — PRE-IMPLEMENTATION

**Goal:** understand reality before touching code.

**Required outputs (the dry-run artifact):**
1. Current state — every active workstream and its column on the
   program board.
2. Blockers — what's red on the board.
3. Ownership — which role owns each file the next phase touches.
4. Dependency map — what depends on what (workstream → workstream).
5. Rollback impact — what reverting the next phase would undo.
6. Risk matrix — P0 / P1 / P2 risks pulled from each reviewer
   role, scoped to the next phase.
7. Execution plan — the phase split for IMPLEMENTATION mode, with
   a per-phase commit boundary.

**Allowed actions:**
- Read every source file, every ADR, every test.
- Run agents (Explore, Plan, reviewer agents) in read-only mode.
- Update `program_board.md` to reflect *observed* reality.
- Draft new ADRs (via Decision Historian).
- Write the dry-run artifact to `.claude/org/dry_runs/YYYY-MM-DD-<scope>.md`.

**Forbidden actions:**
- Editing any production source file (`service/app/**`, `ui/**`).
- Editing tests.
- Speculative implementation ("let me just sketch the route").
- Running `make verify` or pushing commits — there is nothing to
  verify until IMPLEMENTATION exits.

**Exit condition:**
The Coordinator approves the execution plan and the operator
greenlights. Session ends. Next session enters IMPLEMENTATION.

---

## Mode 2 — IMPLEMENTATION

**Goal:** execute the approved plan. Nothing else.

**Required outputs per phase:**
- One commit on a feature branch.
- Phase test file (focused).
- Source-grep guards where applicable.
- Telemetry additions where applicable.
- Updated program board row reflecting the new state.

**Allowed actions:**
- Edit only the file globs allowed for the in-flight phase's
  owning role (per `roles.md`).
- Run the full test gate stack: focused → regression → suite →
  `make verify`.
- Spawn reviewer agents on the diff after gates pass (QA, Security,
  Execution Guard, Dashboard if UI touched).

**Forbidden actions:**
- Roadmap expansion. If a new requirement appears, it goes on the
  program board as a new row in state `pending`. The current
  phase does not absorb it.
- Architecture drift. If the design doesn't fit, the phase pauses
  and re-enters PRE-IMPLEMENTATION via a fresh session.
- Unrelated fixes. "While I'm here" is forbidden.
- Skipping the gate stack.
- Self-approval — the implementer never reviews their own diff.

**Exit condition:**
All phases of the approved plan have shipped clean commits, all
gates green, all reviewers signed off via the Coordinator.
Session ends. Next session enters RELEASE (if cutover-relevant)
or PRE-IMPLEMENTATION (if more design needed).

---

## Mode 3 — RELEASE

**Goal:** validate that what was implemented is safe to ship.

**Required outputs:**
- Regression matrix — full test suites at HEAD vs. the campaign
  baseline commit.
- Invariant confirmation — every campaign-defined invariant
  (e.g. "live AWB never persisted before adapter returns") still
  holds.
- Rollback delta — exact list of files / migrations / flags to
  revert if production fires a regression.
- Production readiness diff — diff of the readiness checklist
  outcome before and after the campaign.
- Release recommendation — go / hold / no-go with named
  conditions.

**Allowed actions:**
- Verification (read + run tests).
- Documentation: release notes, commit message hygiene, ADR
  cross-references.
- Deployment preparation: tagging, branch state, rollback
  rehearsal.

**Forbidden actions:**
- Feature edits.
- Opportunistic fixes ("found a bug, fixing it" — it goes on the
  board, not in this commit).
- Live-flag flips (those are a separate Coordinator decision after
  Production Readiness Reviewer signs off).
- Squash / rebase that loses phase commit boundaries.

**Exit condition:**
A signed release recommendation is written. If `go`, the next
session may flip the live flag (still a separate Coordinator
decision, gated on Production Readiness Reviewer + Operator
Safety Reviewer per the charter). If `hold` or `no-go`, the
recommendation names the workstream rows that must move on the
program board before re-entering RELEASE.

---

## Cross-cutting rules

### Mode declaration
The Coordinator's first message in a session declares:

```
MODE: <PRE-IMPLEMENTATION | IMPLEMENTATION | RELEASE>
SCOPE: <workstream rows from program_board.md>
BASELINE COMMIT: <sha>
```

A session without this header is a governance bug.

### Mode boundaries
- A PRE-IMPLEMENTATION session NEVER ends with an implementation
  commit. The exit is a written plan.
- An IMPLEMENTATION session NEVER edits ADRs, the program board's
  *strategy* columns (Owner, Live-risk gate), or the charter.
  It edits the *progress* columns (State, Tests, Telemetry, UI,
  Debt) on its own row only.
- A RELEASE session NEVER edits source. If it finds a bug, the
  bug becomes a row; release recommendation goes to `hold`.

### Reviewer activation
Reviewers (Security, Audit Evidence, Customs Compliance, Operator
Safety, Gap Hunter, Production Readiness) activate per the
triggers in `roles.md`. The Coordinator decides on their reports;
reviewers never approve their own findings into action.

### Lane serialization
At most **one** workstream may have an active edit on `service/**`
or `ui/**` at any time. Governance / docs lanes (edits scoped to
`.claude/**`) and release-inspection lanes (RELEASE-mode sessions
that produce no source changes) run unrestricted in parallel.
When a code lane is active, no second code lane opens until the
first commits, reverts, or pauses on the program board. The
Coordinator enforces this at session-header time: a new session
declaring code edits is rejected if another code lane is already
in flight.

### Length cap
A session that exceeds ~3 hours of compute time exits cleanly
regardless of mode. Symptoms of context poisoning override mode
goals (see `engineering/session-discipline.md`).

---

## Decision tree on session start

```
Is there pending implementation work approved by the Coordinator?
├── No  → Is there a campaign awaiting validation?
│         ├── Yes → MODE: RELEASE
│         └── No  → MODE: PRE-IMPLEMENTATION
└── Yes → MODE: IMPLEMENTATION
```

If unsure: PRE-IMPLEMENTATION. The cost of a dry-run is one
session; the cost of mid-flight redesign is much higher.
