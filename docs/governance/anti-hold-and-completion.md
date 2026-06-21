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
state before stopping; do not start a second task while one is `IN_PROGRESS`.

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

### Status values

- `NOT_STARTED` — task defined, no work begun.
- `IN_PROGRESS` — actively working; do not start another task.
- `BLOCKED-HOLD` — stopped on a named HOLD condition (record which one).
- `COMPLETE` — completion checklist passed.

---

## 6. What this governance deliberately does NOT do

- It does **not** add a session-blocking hook. A blocking Anti-HOLD hook
  could wedge a session and contradicts the ANTI-HOLD principle itself
  (fail-open is mandatory). Enforcement is by documented protocol plus the
  existing non-blocking stop-gate.
- It does **not** override any GATE, the regression stop-gate, or the
  7-agent deploy gate.
- It does **not** replace PROJECT_STATE.md or flow-context-keeper.
