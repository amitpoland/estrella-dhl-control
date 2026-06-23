# /context-lite

Minimal orientation for quick fixes, PR checks, and short reviews.
**Token budget: < 8k tokens.**

## When to use

- "What's the active task?" / "What branch am I on?"
- Quick bug fix that doesn't touch multiple domains
- Checking if GATE 2 has a slot
- Reviewing a small diff
- Anything that doesn't require project-level decision history

## What to load

```
1. .claude/memory/TASK_STATE.md          — active task, branch, HOLD state
2. git log --oneline -5                  — recent commits
3. git status                            — uncommitted changes
```

Do NOT load:
- `PROJECT_STATE.md` (full 773 KB file)
- `PROJECT_STATE_SUMMARY.md` (unless GATE 2 check needed — then load it)
- `engineering_lessons.md`
- Agent files or capability files

## How to invoke

```
/context-lite
```

Then your actual request, e.g.:
```
/context-lite
Task: Why is pz_quantity_validator throwing on oz units?
```

## Output format

Claude reads TASK_STATE.md + git state and reports in ≤5 lines:

```
Branch: <branch>
Active task: <one line>
Last commit: <sha> <message>
Uncommitted: <N files changed> / clean
GATE 2: <N>/3 impl PRs open
```

Then proceeds directly to the task.

## Upgrade path

If the task turns out to need project-level context (decisions, open PRs, blockers):
use `/context-pr` or `/context-task` instead.
