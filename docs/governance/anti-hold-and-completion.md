# Anti-HOLD and Workflow Completion Governance

Status: ACTIVE · Introduced 2026-06-19 · Owner: orchestrator
Summary rule in `CLAUDE.md` → §ANTI-HOLD AND WORKFLOW COMPLETION.
In-flight task tracker: `.claude/memory/TASK_STATE.md`.

This document is the full specification behind the concise CLAUDE.md rule.
It exists to prevent two opposite failure modes:

- **Premature HOLD** — stopping to ask the operator about work that should
  have proceeded autonomously (a repo search, a test run, a doc update).
- **Task drift** — abandoning an in-flight task to start a different one
  before the first reaches its completion checklist.

These rules are **subordinate** to:

- **GATES 1–6** (CLAUDE.md) — a gate block is always a valid stop.
- The **regression stop-gate** (`.claude/hooks/pz-stop-gate.py`) — a RED
  regression suite always blocks finishing, never overridden by Anti-HOLD.
- The **7-agent deploy gate** — production sync always requires the gate.

Anti-HOLD never weakens a gate. It only removes *unjustified* stops.

---

## 1. The Anti-HOLD principle

> Continuing autonomous work is the default. Stopping is the exception and
> must be justified by a named HOLD condition.

"I could check with the operator" is not, by itself, a reason to stop.
Only the four HOLD conditions in §2 justify a stop. When you do stop,
name the condition explicitly and record it in `TASK_STATE.md`.

---

## 2. Decision table — when to stop vs continue

| Situation | Decision | Why |
|-----------|----------|-----|
| Reading/searching/tracing code | **CONTINUE** | Inspection is free and reversible |
| Running `make verify`, pytest, smoke | **CONTINUE** | Tests are non-destructive |
| Running app locally, curl, inspecting artifacts | **CONTINUE** | Local verification is non-destructive |
| Editing docs, PROJECT_STATE.md, TASK_STATE.md, scorecards | **CONTINUE** | Documentation is non-destructive |
| Rename/extract/refactor inside a feature branch | **CONTINUE** | Branch-local, reversible |
| Commit to a feature branch / open a draft PR | **CONTINUE** | Non-destructive; GATE 1 still applies |
| Technical ambiguity with a sensible default | **CONTINUE** (pick default, note it) | Wrong guess is cheap and reversible |
| Next step deletes/overwrites production or a booked external record | **HOLD** | Destructive production action |
| Next step needs a secret/token/access not available | **HOLD** | Missing credentials |
| Next step has legal/financial consequence needing sign-off | **HOLD** | Legal/financial approval |
| Task depends on a business choice the repo cannot resolve, wrong guess is costly | **HOLD** | Unclear business decision |

### The four valid HOLD conditions (stop)

1. **Destructive production action** — delete/overwrite/irreversible
   mutation of production data, a live service, or a booked external
   record. Examples: `C:\PZ` robocopy or `git reset --hard`, dropping a
   SQLite table, editing a booked wFirma PZ, sending a real email,
   restarting `PZService` in a way that risks data.
2. **Missing credentials / access** — a required secret, token, or
   permission the session does not hold and cannot safely obtain.
3. **Legal / financial approval** — booking a value correction, sending a
   customs declaration (SAD/DSK), money movement, anything with
   legal/financial weight requiring a human signature.
4. **Unclear business decision** — a business choice not resolvable from
   code, repo, or PROJECT_STATE, where a wrong guess has real cost.
   A purely technical fork with a reasonable default is NOT this.

### The must-continue list (never a valid HOLD)

Code inspection · repo search · test execution · local verification ·
documentation/state updates · non-destructive refactor · committing to a
feature branch · opening a draft PR (GATE 1 satisfied).

---

## 3. Worked HOLD decision examples

**Example A — "Should I run the full carrier suite to confirm counts?"**
→ **CONTINUE.** Test execution is non-destructive. Run it; report results.
Stopping to ask would be a premature HOLD.

**Example B — "The duplicate-guard flagged a basename collision; should I
rename the new file or extend the existing module?"**
→ **CONTINUE** (technical ambiguity, sensible default). Extend the existing
module per the guard's intent; note the choice. Only HOLD if extending
would change a business rule the repo can't confirm.

**Example C — "Ready to robocopy `service/app` into `C:\PZ` and restart
PZService."**
→ **HOLD** (destructive production action). Production sync requires the
7-agent gate and operator execution. Stop, present the gate result and the
exact commands, hand to operator.

**Example D — "The booked wFirma PZ value is 2280.14 but corrected is
2736.87 — should I push the correction via API?"**
→ **HOLD** (legal/financial approval + destructive external record).
Editing a booked accounting document needs operator sign-off and sandbox
proof. Stop and surface the decision.

**Example E — "The vision extractor needs an Anthropic API key to run live;
the session env doesn't have one."**
→ **HOLD** (missing credentials). State exactly what is missing and how to
provide it; do not fabricate a key or a result.

**Example F — "I finished the gap-detection hook; the PROJECT_STATE update
is uncommitted."**
→ **CONTINUE.** Committing docs/state to a feature branch and opening a
draft PR are non-destructive. Complete the workflow before stopping.

**Example G — "Tests pass, PR is open. Should I now also refactor the
unrelated `routes_dashboard` module I noticed?"**
→ **Do NOT drift.** The current task is complete; a new, unrelated refactor
is a *separate* task. Finish/close the current TASK_STATE entry, then
either start the new task as its own entry or surface it as a suggestion.
Anti-HOLD means "don't stop unnecessarily," not "wander into new scope."

---

## 4. Workflow completion checklist (definition of done)

A task is **not done** until every applicable item passes. Drive to this
state before stopping; do not start a second task while one is in an active lifecycle
state (any state other than `COMPLETE`).

- [ ] The stated goal is fully implemented (no `TODO`/placeholder left in
      the delivered surface unless explicitly deferred and recorded).
- [ ] Only intended files changed (verify with `git status` /
      `git diff --name-only`); no out-of-scope edits.
- [ ] Relevant tests run with a verdict (smoke / targeted suite / full
      regression as the change warrants), results reported honestly.
- [ ] Regression is GREEN (or the stop-gate override is justified and
      recorded).
- [ ] Changes committed to the designated feature branch.
- [ ] Pushed to remote; PR opened (draft) if a PR is the deliverable, with
      GATE 1 satisfied.
- [ ] State recorded: `TASK_STATE.md` updated to `COMPLETE`; if a PR merged
      to main, `flow-context-keeper` fires per Observation RULE 3.
- [ ] If stopping on a HOLD: the HOLD condition is named and written to
      `TASK_STATE.md` so the next session resumes without re-derivation.

If an item legitimately does not apply (e.g. backend-only change has no
browser step), mark it N/A — do not silently skip.

---

## 5. TASK_STATE.md protocol — and its boundary with PROJECT_STATE.md

`.claude/memory/TASK_STATE.md` tracks the **single in-flight task**: its
goal, completion criteria, current status, and HOLD reason (if any). It is
ephemeral and rewritten per task.

`.claude/memory/PROJECT_STATE.md` tracks **durable, cross-session project
execution state** (FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS), owned
by `flow-context-keeper`.

**These are not duplicate systems.** The boundary is granularity and
lifetime:

| | TASK_STATE.md | PROJECT_STATE.md |
|---|---|---|
| Scope | One in-flight task | Whole project / campaigns |
| Lifetime | Ephemeral (per task) | Durable (append-only FACTS) |
| Owner | Active session | `flow-context-keeper` |
| Answers | "Is *this* task done? Why did it stop?" | "Where is the project overall?" |

A task's completion does not by itself produce a FACT; only a PR merge,
issue close, or observer scorecard does (per Observation RULES 2–3). When a
task completes and merges, update TASK_STATE.md → `COMPLETE` AND let
`flow-context-keeper` record the durable FACT in PROJECT_STATE.md.

### Status values — the single-task lifecycle

The in-flight task moves along one canonical lifecycle axis, defined once in
`.claude/TASK_EXECUTION_PROTOCOL.md` (the lifecycle authority) — this list mirrors it.
Underscore form is canonical; pre-existing `TASK_STATE.md` entries in old spellings
(`IN_PROGRESS`, `BLOCKED-HOLD`, `READY FOR PR`, `UNDER REVIEW`) are grandfathered and
NOT auto-reclassified (see §7 and the migration note in `TASK_STATE.md`); new entries
use the canonical state.

- `NOT_STARTED` — task defined, no work begun.
- `DISCOVERY` — inspecting repo, establishing authority (protocol Phase 1).
- `PLANNING` — producing the implementation plan (Phase 2).
- `IMPLEMENTING` — modifying code (Phase 3).
- `VALIDATING` — tests, reviews, governance (Phase 4).
- `EXECUTION_BLOCKED` — suspended on an external dependency while a verified
  checkpoint is preserved; the **resumable** refinement of the former `BLOCKED-HOLD`.
  It still requires one of the four §2 HOLD conditions (primarily #2, missing access).
  Checkpoint + Resume Rule: §7.
- `READY_FOR_PR` — validation complete, GATE 1 satisfied, PR not yet open (Phase 5).
- `UNDER_REVIEW` — PR open (Phase 5).
- `COMPLETE` — completion checklist passed; merged.

This lifecycle is a **separate axis** from the `.campaigns/` branch-write registry
state (`IN_PROGRESS` / `FROZEN` / `PR_OPEN` / …); neither derives mechanically from the
other (mapping table: `.claude/TASK_EXECUTION_PROTOCOL.md`).

---

## 6. What this governance deliberately does NOT do

- It does **not** add a session-blocking hook. A blocking Anti-HOLD hook
  could wedge a session and contradicts the ANTI-HOLD principle itself
  (fail-open is mandatory). Enforcement is by documented protocol plus the
  existing non-blocking stop-gate.
- It does **not** override any GATE, the regression stop-gate, or the
  7-agent deploy gate.
- It does **not** replace PROJECT_STATE.md or flow-context-keeper.

---

## 7. EXECUTION_BLOCKED and the Resume Rule

`EXECUTION_BLOCKED` is the resumable form of a stop. It applies when work halts on an
**external dependency** (missing prod access/token, an unmerged upstream PR, an
unavailable environment or service) **while a verified checkpoint is preserved** — i.e.
the stop is one of the four §2 HOLD conditions (primarily #2, missing credentials/
access) AND the work up to the stop is frozen and still valid. It is the resumable
refinement of the former `BLOCKED-HOLD`.

> **EXECUTION_BLOCKED is resumable, not restartable.**

### 7.1 What is frozen while blocked

Architecture is frozen · implementation is frozen · the existing diff is preserved ·
the authority decision is preserved. While blocked, do **not**: run new discovery, new
planning, or new coding; retry the execution repeatedly; rewrite an ADR solely because
of the interruption; or launch a fresh broad `/context` pass. The single recorded
resume command is the only campaign-execution command permitted.

### 7.2 The checkpoint (recorded on entering EXECUTION_BLOCKED)

Record, in `TASK_STATE.md`, a checkpoint block carrying: the state suspended from
(`suspended_from`), the blocking dependency, the recorded branch and HEAD SHA
(`recorded_branch`, `recorded_head`), the preserved file set, the canonical authority
owner, the single resume command (`next_command`), a `NO_REPEATED_RETRIES` policy, and
a timestamp. The checkpoint carries **no** secrets, tokens, customer data, or document
payloads. (Template: `.claude/memory/TASK_STATE.md`.)

### 7.3 The Resume Rule — bounded pre-resume validation (six checks)

Before executing the recorded `next_command`, run only this bounded validation:

1. Current branch == recorded branch.
2. Current HEAD == recorded HEAD.
3. The preserved file set (`preserved_files`) is unchanged — verified against the
   recorded `preserved_diff_hash` when present, otherwise by re-hashing those paths; a
   change to any file within the task's declared scope fails this check.
4. Recorded authority owner still canonical.
5. External dependency now available.
6. No conflicting campaign writer has claimed the branch.

**All six pass → execute `next_command` directly** — do not re-run discovery, re-plan,
or re-implement work that is still valid. If `next_command` opens a PR or triggers a
production sync/deploy, GATE 1 and the 7-agent deploy gate apply as normal before
execution — the resumable path never bypasses them. **Any check fails → do not restart
automatically.** Identify the **earliest invalid checkpoint** and transition to that
lifecycle state *only*; never fall back to DISCOVERY/PLANNING/IMPLEMENTING unless those
assumptions specifically became invalid. A changed HEAD/diff that does not invalidate
the plan resumes at `VALIDATING`, re-verifies, and proceeds.

### 7.4 Operator ruling + preserved diff (hard rules)

- **Require an operator ruling** for: unexpected HEAD movement, an authority conflict, or
  concurrent branch ownership (checks 2 / 4 / 6). These are not auto-resolved — they
  mirror the campaign-branch-guard posture that `expected_head` ≠ actual is an INCIDENT.
  **Unexpected** = any HEAD movement not initiated by the owner session or explicitly
  pre-authorized by the operator in the checkpoint; a session must not self-classify a
  HEAD change as "expected" to skip this ruling.
- **Never** silently `rebase`, `reset`, `cherry-pick`, or discard the preserved diff to
  force the stored command to run.
- `EXECUTION_BLOCKED` never becomes a branch-write authority; branch-write governance
  stays with `.campaigns/` (its state enum and guard are unchanged by this rule).

### 7.5 Worked example

A campaign reaches `VALIDATING` and blocks because a required test needs prod
infrastructure that is down. It records `suspended_from: VALIDATING`,
`next_command: python -m pytest service/tests/test_routes_2b_manual_link.py -q`,
plus `recorded_head` / `recorded_branch`. On resume: if branch/HEAD/diff are unchanged,
authority still canonical, infra back, and no other writer — run the stored command
directly. If `main` advanced and the branch was rebased in the interim (HEAD changed),
do **not** re-run discovery or re-plan: re-enter `VALIDATING`, confirm the plan
assumptions still hold, and re-run the suite — after an operator ruling if the HEAD
movement was unexpected.

### 7.6 Subordination

This rule adds no hook and weakens no gate. `EXECUTION_BLOCKED` still requires a §2 HOLD
condition; GATES 1–6, the regression stop-gate, and the 7-agent deploy gate are
unaffected. Deterministic enforcement (a Stop hook) is explicitly out of scope (see §6
and the Engineering OS §13.E honesty boundary) and would be a separate approved campaign.
