# ej-dashboard-master (Claude Code project skill)

Master **router / orchestration** skill for EJ Dashboard Portal (Estrella Jewels / Atlas-v2)
work. Scoped to this repo only — installed at `.claude/skills/ej-dashboard-master/`, not
globally.

## Purpose

This is **NOT** a design, backend, refactor, or testing skill, and it does **not** duplicate,
replace, or restate any existing skill. It is only the orchestration/router layer. Its single
responsibility is to: **inspect → classify → select the minimum required skills → enforce the
execution workflow → delegate → verify completion.** All implementation authority stays with the
routed skills.

## Routing philosophy

Classify first, then activate the smallest valid skill set for that class of work — and get out
of the way. The router owns no craft rules; on any conflict the **owning skill wins**, CLAUDE.md
GATES 1–6 + Engineering Lessons win over all, and the 7-agent deploy gate owns production.

```
User Request
    ↓
Master Router
    ↓
Classification
    ↓
Minimum Skill Selection
    ↓
Execution
    ↓
Verification
    ↓
Done
```

## Session lifecycle (bootstrap → dynamic routing → release)

The router is session-aware. It bootstraps once at session start (inspect + build the routing
table, **without** loading any implementation skill), then per task it selects the minimum
skills, executes, verifies, and **releases** those skills from active context. Active skills are
not fixed — they change dynamically as the task changes.

```
             Session Start
                   │
                   ▼
           Repository Inspect
                   │
                   ▼
           Routing Table Build
                   │
                   ▼
           Wait for User Task
                   │
                   ▼
           Task Classification
                   │
                   ▼
           Minimum Skill Selection
                   │
                   ▼
               Execute
                   │
                   ▼
               Verify
                   │
                   ▼
           Release Active Skills
```

- **Session Bootstrap** — at session start: inspect the repo, detect available skills, build +
  cache the routing table. No implementation skill is activated until the first task is classified.
- **Dynamic Routing** — when the user pivots (UI → browser verify → backend …), the router
  unloads the previous task's skills and loads only the new minimum set. Keeps context minimal.
- **Skill Lifecycle** — `Available → Selected → Active → Completed → Released`. On task close,
  every Active skill is released from context.

## Skills it routes to

| Skill | Role |
|---|---|
| `frontend-design` | Primary frontend design authority (tokens, styling, spacing, typography, craft) |
| `ej-dashboard-design` | Frontend governance / single-page authority (routing, duplicate prevention) |
| `ej-dashboard-fullstack-governance` | Backend / API / persistence / protected-domain authority |
| `ej-dashboard-clean-code` | Refactoring, code quality, small scoped, repository-safe changes |
| `ej-dashboard-webapp-testing` | Browser / Playwright / smoke verification |
| `ui-ux-pro-max` | **Reference only — NEVER an authority** (accessibility, layouts, spacing, typography, visual ideas); never overrides a project rule |

## Minimum Skill Principle

Never activate more than **two** project skills at once unless the task genuinely spans multiple
domains (a true full-stack task). Always choose the smallest valid set. Discussion, planning, and
architecture-review requests load **no** implementation skills and are answered directly.

## Protected domains

If a task affects **Financial, Customs, Accounting, Inventory, Shipment, Document generation, API
authority, Database persistence, or Business calculations**, the router **stops and asks for
explicit approval before implementation** and routes the change to
`ej-dashboard-fullstack-governance`. It never bypasses `process_batch()` or the
Master→Mirror→wFirma chain.

## Conflict resolution

- Visual craft (tokens, styling, spacing, typography) → `frontend-design`
- Page authority, routing, governance, duplicate prevention → `ej-dashboard-design`
- Backend, API, persistence, business logic → `ej-dashboard-fullstack-governance`
- Refactoring, simplicity, repository safety → `ej-dashboard-clean-code`
- Browser verification, Playwright, smoke tests → `ej-dashboard-webapp-testing`
- `ui-ux-pro-max` → never overrides anything

## Workflow

```
Inspect → Classify → Skill Selection → Plan → Implement → Verify → Close
```

No step is skipped for an implementation task. A short **confidence report** (classification +
per-category percentages + selected skills + reason) is shown before any edit. Full task-type →
skills mapping, approval/verification requirements, and worked examples are in
`ARCHITECTURE_DECISION_MATRIX.md`.

## Install

```bash
mkdir -p .claude/skills/ej-dashboard-master
cp SKILL.md .claude/skills/ej-dashboard-master/SKILL.md
```

Restart Claude Code (or start a new session) so the skill is picked up, then verify:

```bash
claude skills list
# expect to see: ej-dashboard-master (plus the five skills it routes to)
```

## Usage

```
/context
/ej-dashboard-master
```

Invoke at the **start** of a non-trivial EJ Dashboard task. The router classifies the request,
shows a confidence report, and activates the minimum skills — then those skills do the work.

## Maintaining this skill

- Keep `SKILL.md` a thin router — any craft/authority rule belongs in the owning skill, not here.
- Re-validate against the prompts in `tests/` after any change to the routing rules or matrix.
- This file (`README.md`) is for humans only — Claude Code does not read it as instructions.
