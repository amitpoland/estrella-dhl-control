# /context-task

Full governance context for implementation work, architecture, and multi-file changes.
**Token budget: < 55k tokens.**

## When to use

- Starting a new feature or bug fix
- Architecture decision needed
- Multi-file change spanning 2+ domains
- Any task that triggers skill routing
- Any task that touches AUTHORITY_MAP, BACKLOG, or TASK_STATE

## What to load

```
1. .claude/memory/TASK_STATE.md              — active task, IN_PROGRESS check
2. .claude/memory/PROJECT_STATE_SUMMARY.md   — compact project state (≤150 lines)
3. .claude/SKILL_ROUTING.md                  — domain → skill mapping
4. git log --oneline -10
5. git status
```

Load on demand (only if task specifically requires):
- `docs/governance/AUTHORITY_MAP.md` — when touching write authorities
- `BACKLOG.md` — when side-discoveries need to be captured
- Full `PROJECT_STATE.md` — when task requires full DECISIONS or OPEN QUESTIONS history

Do NOT load by default:
- `PROJECT_STATE.md` full file (773 KB) — use PROJECT_STATE_SUMMARY.md instead
- `engineering_lessons.md` — invoke `/engineering-lessons` when a specific lesson applies
- Capability files (`.claude/capabilities/*.md`) — load via skill invocations

## How to invoke

```
/context-task
Task: Add warehouse receipt confirmation to the import PZ readiness check
```

Or with a skill hint:
```
/context-task
/inspect-route POST /api/v1/pz/create
Task: Why is pz_create missing the warehouse receipt fiscal gate?
```

## Startup sequence (Claude follows this order)

1. Check TASK_STATE.md — if `IN_PROGRESS` on a different task, STOP and report (Anti-HOLD rule)
2. Read PROJECT_STATE_SUMMARY.md — load open PRs, blockers, GATE 2 status
3. Check GATE 2: if 3/3 impl PRs open, BLOCK new implementation; suggest merge queue first
4. Identify affected domain → consult SKILL_ROUTING.md → load relevant skill
5. Proceed with task

## TASK_STATE update (required on task start)

Before any code changes, update TASK_STATE.md:
- Set status: `IN_PROGRESS`
- Record branch and worktree
- Write one-line goal

## Upgrade path for full project history

If the task requires the full DECISIONS section or all OPEN QUESTIONS:
```python
# Load only when explicitly needed
read(".claude/memory/PROJECT_STATE.md", offset=5695)  # DECISIONS
read(".claude/memory/PROJECT_STATE.md", offset=6432)  # OPEN QUESTIONS
```

Never load the full 773 KB file on a routine task start.
