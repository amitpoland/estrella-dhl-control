# /pz-loop — Bounded Engineering Loop

Task: $ARGUMENTS

Run the Engineering OS **bounded iterative loop** for a stated task — the iterative counterpart
to the linear `/feature` protocol, for work that converges through repeated apply→verify cycles
(a diagnostic hunt, a flaky-test fix, a refactor toward a metric).

**All loop mechanics are governed by `.engineering-os/00_ENGINEERING_CONSTITUTION.md §13`.
Read §13 before executing any iteration.** This file is the entry point; it does not restate the
protocol (same pattern as `/feature` → `TASK_EXECUTION_PROTOCOL.md`).

---

## Required inputs (state all four before iteration 1)

```
OBJECTIVE:        <one sentence; the convergence goal, VERIFIED-checkable>
STOP_CONDITIONS:  <at least one explicit, objective exit condition>
ITERATION_CAP:    <max iterations — default 5; state it even when accepting the default>
VERIFY_CMD:       <the real executable command(s) run after each iteration>
```

## Refuse to start if

- OBJECTIVE is not stated.
- STOP_CONDITIONS is not stated, or is aspirational ("until it works" / "until it's good" is
  **not** a stop condition).
- ITERATION_CAP is not stated.
- VERIFY_CMD is not stated or is not an actually-executable command.
- No objective verifier exists (nothing VERIFY_CMD can measure).
- `.claude/memory/TASK_STATE.md` shows `IN_PROGRESS` for a **different** task (one-task rule).
- The Engineering OS authority is not loaded, repository ownership/canonical authority is
  unclear, another worktree already owns overlapping work, or the requested first action begins
  **beyond an operator gate** (see §13 + `CLAUDE.md` ANTI-HOLD).

If any input cannot be derived safely from repository evidence, **STOP and request the missing
decision** — do not invent it.

## Per-iteration output (one block per iteration)

```
ITERATION <N>/<CAP>
CHANGE:     <one-line description of the smallest change applied (§12)>
VERIFY:     PASS | FAIL | PARTIAL — <VERIFY_CMD result summary>
EVIDENCE:   VERIFIED | PRIOR EVIDENCE | UNVERIFIED (per §11)
STOP_CHECK: MET | NOT MET — <which condition if met, else "continuing">
STATUS:     CONTINUING | CONVERGED | CAP_REACHED | HOLD_TRIGGERED
HOLD:       <condition name if HOLD_TRIGGERED (per CLAUDE.md ANTI-HOLD); omit otherwise>
NEXT:       <exact next step, or "hand to operator">
```

## Loop-exit output

```
LOOP_RESULT: CONVERGED | CAP_REACHED | HOLD_TRIGGERED
ITERATIONS:  <N completed of CAP>
EVIDENCE:    VERIFIED | PRIOR EVIDENCE | UNVERIFIED (per §11)
STATE:       <one sentence on where the work stands>
ROLLBACK:    <rollback point for any change committed>
OPERATOR:    <required action, or "none — loop closed">
```

At CAP_REACHED: stop, preserve the worktree, report completed work + the remaining failure with
evidence, and recommend the exact next step. Do not run past the cap; do not restart solved work.

## Authority cross-references

| Concern | Authority |
|---|---|
| Loop protocol (the rules) | `.engineering-os/00_ENGINEERING_CONSTITUTION.md §13` |
| Smallest per-iteration change | `00 §12` (MODULAR-MINIMAL + Anti-Bloat gate) |
| Evidence classification | `00 §11` (Evidence Contract) |
| Operator gates / HOLD within a loop | `CLAUDE.md` ANTI-HOLD + `docs/governance/anti-hold-and-completion.md` + `00 §7.6` |
| Worktree / ownership / concurrency | `00 §7.3–§7.5` + `CLAUDE.md` Canonical working-tree registry |
| Prior-work continuity | `00 §11` (classify) + `00 §7.2` (delta-verify) |
| Task tracking | `.claude/memory/TASK_STATE.md` |

## Capability

**READ-OR-WRITE-CAPABLE — depends on VERIFY_CMD and the per-iteration change:**
- READ-ONLY iterations (inspect / grep / test only, no file mutation): run freely.
- WRITE-CAPABLE iterations (edit files, commit): **GATE 1 applies at loop exit** before any PR
  opens; **operator approval is required before any iteration that would mutate production** or
  cross any operator gate named in §13 / `CLAUDE.md` ANTI-HOLD. The loop may *prepare and verify*
  a gated action but must never cross the gate on its own.
