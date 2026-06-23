# /context-pr

PR-focused context for code review, merge decisions, and release checks.
**Token budget: < 25k tokens.**

## When to use

- Reviewing a PR before merge
- Checking GATE 1 completeness for a PR
- Deciding merge order when multiple PRs are queued
- Checking GATE 2 status before opening a new PR
- Running the 7-agent deploy gate
- Post-merge state verification

## What to load

```
1. .claude/memory/TASK_STATE.md              — active task
2. .claude/memory/PROJECT_STATE_SUMMARY.md   — open PRs, blockers, GATE 2 status
3. git log --oneline -10                     — recent commits on this branch
4. git diff --stat main...HEAD               — what this branch changes
```

For a specific PR number: additionally fetch `gh pr view <N>` and `gh pr diff <N>`.

Do NOT load:
- `PROJECT_STATE.md` full file (unless full DECISIONS history is needed for a specific review question)
- `engineering_lessons.md` (load via `/engineering-lessons` only if a specific lesson is in question)

## How to invoke

```
/context-pr
Review PR #726 before merge
```

Or for a GATE 1 check on the current branch:
```
/context-pr
GATE 1 check: is this branch ready to open a PR?
```

## GATE 1 checklist (auto-applied)

Claude checks these against the diff and PROJECT_STATE_SUMMARY.md:

- [ ] All named subagents returned verdicts
- [ ] All HIGH/CRITICAL findings resolved or escalated
- [ ] Browser verification complete (if UI changes)
- [ ] Regression tests run with verdict (`make verify`)
- [ ] Forbidden-files check (no out-of-scope edits)
- [ ] GATE 2: ≤3 open impl PRs after this one opens

## Output format

```
PR: #<N> / branch: <branch>
GATE 1: PASS / FAIL / PARTIAL — <reason>
GATE 2: <N>/3 impl PRs — SLOT AVAILABLE / AT LIMIT
Key findings: <list blockers if any>
```
