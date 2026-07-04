---
name: ej-dashboard-master
metadata:
  version: 1.2.0
description: >
  Master ROUTER / orchestration skill for EJ Dashboard Portal (Estrella Jewels / Atlas-v2)
  work. This is NOT a design, backend, refactor, or testing skill and owns NO implementation
  rules of its own — those belong to the skills it routes to. Its only job: inspect, classify
  the request, select the MINIMUM required project skills, enforce the execution workflow,
  delegate, and verify completion. Use it at the START of any non-trivial EJ Dashboard task.
  It routes among frontend-design (UI craft), ej-dashboard-design (frontend governance /
  single-page authority), ej-dashboard-fullstack-governance (backend / API / persistence /
  protected-domain authority), ej-dashboard-clean-code (refactor / small scoped edits), and
  ej-dashboard-webapp-testing (browser / Playwright verification); ui-ux-pro-max is
  reference-only and NEVER an authority. It answers discussion/planning directly without
  loading implementation skills, never activates more than two skills unless a task genuinely
  spans domains, stops and asks before touching protected domains, and forbids duplicate
  pages/routes/APIs/state/components without explicit approval.
---

# EJ Dashboard — Master Router / Orchestration

A **dispatcher**, not an implementer. It classifies an EJ Dashboard request, selects the
minimum skills, enforces the workflow, delegates, and verifies. It has **no craft or
implementation rules of its own** and never duplicates, replaces, or restates the skills it
routes to. On any conflict the **owning skill wins**; CLAUDE.md GATES 1–6 + Engineering Lessons
win over all; the 7-agent deploy gate owns production.

## The skills it routes to (used exactly as they are)

| Skill | Authority for | Role |
|---|---|---|
| `frontend-design` | tokens, styling, spacing, typography, visual craft | Primary frontend design authority |
| `ej-dashboard-design` | page authority, routing, governance, duplicate prevention | Frontend governance / single-page authority |
| `ej-dashboard-fullstack-governance` | backend, API, persistence, business logic, protected domains | Backend / fullstack authority |
| `ej-dashboard-clean-code` | refactoring, simplicity, repository safety | Refactor / code-quality authority |
| `ej-dashboard-webapp-testing` | browser / Playwright / smoke verification | Verification authority |
| `ui-ux-pro-max` | — | **Reference only. NEVER an authority.** Accessibility / layout / spacing / typography / visual ideas; never overrides a project rule |

## Session Bootstrap

At the **beginning of every new Claude Code session**:

1. **Inspect the repository.**
2. **Detect available project skills.**
3. **Build the routing table** (category → minimum skill set, from §4 / the decision matrix).
4. **Cache the routing decision.**

**Do NOT activate implementation skills yet.** Only activate skills after the **first user task
is classified** (§2). Bootstrap makes the router *ready to dispatch* — it loads no
design/backend/refactor/testing skill until a real task arrives. This prevents unnecessary
loading and keeps a fresh session at minimum context.

## 1. Inspect first

Begin every task with **`/context`** before planning. Never assume repository state.
(Exception: pure discussion — see §3 — where repository inspection is often unnecessary.)

## 2. Classify the request (before loading any skill)

Assign the request to exactly ONE primary category:

`Discussion` · `Question` · `Planning` · `Architecture Review` · `Code Review` ·
`UI Implementation` · `Backend Implementation` · `Full Stack Implementation` · `Refactoring` ·
`Browser Verification` · `Bug Investigation` · `Deployment` · `Documentation`

Classification drives skill selection — never load a skill before the request is classified.

## 3. Discussion-only mode (no implementation skills)

If the request is ONLY discussion, brainstorming, explanation, planning, or an architecture
conversation (categories `Discussion` / `Question` / `Planning` / `Architecture Review`):

- **Do NOT activate any implementation skill** (frontend-design, ej-dashboard-design,
  fullstack-governance, clean-code, webapp-testing).
- **Answer directly.** Avoid unnecessary repository inspection — reason from known architecture;
  only inspect if a specific factual claim requires it.
- Documentation that is purely explanatory is discussion-class; documentation that edits code
  comments/behavior is not.

## 4. Minimum Skill Principle

Select the **smallest valid skill set**. **Never activate more than TWO project skills
simultaneously unless the task genuinely spans multiple domains** (a true full-stack task).

| Category | Skills (minimum) |
|---|---|
| UI Implementation | `frontend-design` + `ej-dashboard-design` |
| Backend Implementation | `ej-dashboard-fullstack-governance` + `ej-dashboard-clean-code` |
| Full Stack Implementation | design pair + `ej-dashboard-fullstack-governance` (spans domains — the only >2 case) |
| Refactoring | `ej-dashboard-clean-code` + the relevant domain skill |
| Code Review | `ej-dashboard-clean-code` |
| Browser Verification | `ej-dashboard-webapp-testing` |
| Architecture Review / Discussion / Planning / Question | **none** (discussion-only, §3) |
| Bug Investigation | start read-only (none); add the one domain skill the fix will need |
| Deployment | **none here** — the 7-agent deploy gate owns it |
| Documentation | none, unless it edits code (then the domain skill) |

`ui-ux-pro-max` is never counted as an activated authority — it is reference lookup only,
filtered through `frontend-design` + `ej-dashboard-design`.

## 5. Protected domains — STOP and ask

If the task affects **Financial, Customs, Accounting, Inventory, Shipment, Document generation,
API authority, Database persistence, or Business calculations** → **STOP and request explicit
approval before implementation**, even when framed as small/cosmetic. Route the actual change to
`ej-dashboard-fullstack-governance` (protected-domain authority); never bypass `process_batch()`
or the Master→Mirror→wFirma chain. Approval in one area does not extend to another.

## 6. Never create duplicate authority

Never create a `*New` / `*Modern` / `*V2` / `*Next` parallel **page, API, route, state,
component, or business logic**, without the user's explicit approval. Resolve the canonical owner
(via `ej-dashboard-design` for frontend, `ej-dashboard-fullstack-governance` for backend) and
extend in place. An unpropagated rename is a silent duplicate authority — reject it.

## 7. Execution workflow (never skip a step)

```
Inspect → Classify → Skill Selection → Plan → Implement → Verify → Close
```

Every implementation task runs the full chain. Discussion-class requests stop after answering
(no Implement/Verify). Verify uses the repo-real gate the activated skill requires
(`make verify` / targeted `pytest`, or `ej-dashboard-webapp-testing` for a browser surface);
never self-authorize a deploy. **Close = release every Active skill** from context (§11 Skill
Lifecycle) so the next task starts from a clean minimum set.

## 8. Confidence reporting (show before implementing)

Before implementation, show a short routing summary:

```
Classification
  UI Implementation

Confidence
  UI ............. 98%
  Backend ........  4%
  Testing ........  2%

Selected Skills
  frontend-design
  ej-dashboard-design

Reason
  Visual-only task. No backend changes detected.
```

Keep it brief. It makes the routing decision auditable before any edit.

## 9. Conflict resolution (which skill wins)

| Concern | Winner |
|---|---|
| tokens, styling, spacing, typography, visual craft | `frontend-design` |
| page authority, routing, governance, duplicate prevention | `ej-dashboard-design` |
| backend, API, persistence, business logic | `ej-dashboard-fullstack-governance` |
| refactoring, simplicity, repository safety | `ej-dashboard-clean-code` |
| browser verification, Playwright, smoke tests | `ej-dashboard-webapp-testing` |
| anything | `ui-ux-pro-max` **never overrides** |

Above all: CLAUDE.md GATES 1–6 + Engineering Lessons win over any skill; the 7-agent deploy gate
owns production.

## 10. Dynamic Routing

Active skills are **not fixed for the session** — they change as the task changes. When the user
pivots to a new task type, **UNLOAD** the skills the previous task needed and **LOAD** only the
new minimum set. Re-classify (§2) and re-select (§4) on **every** new task; never carry a prior
task's skills forward by inertia. This keeps context usage minimal.

Example (one continuous session):

```
User: "Fix UI spacing."
  → LOAD  frontend-design + ej-dashboard-design
------------------------------------------------------------
User: "Now verify in browser."
  → UNLOAD frontend-design + ej-dashboard-design
  → LOAD   ej-dashboard-webapp-testing
------------------------------------------------------------
User: "Now fix the backend API."
  → UNLOAD ej-dashboard-webapp-testing
  → LOAD   ej-dashboard-fullstack-governance + ej-dashboard-clean-code
```

## 11. Skill Lifecycle

Every skill moves through explicit states — the router is responsible for advancing and, at the
end, releasing them:

```
Available → Selected → Active → Completed → Released
```

- **Available** — installed and discoverable; not loaded.
- **Selected** — chosen for the current task by classification (§2/§4); not yet doing work.
- **Active** — loaded and governing the in-flight work.
- **Completed** — the task's Implement + Verify steps are done.
- **Released** — removed from active context when the task closes.

At the **Close** step of the workflow (§7), **RELEASE every Active skill** from context so the
next task starts from a clean minimum set. A skill left Active after its task has completed is
context debt — release it. (This is the mechanism behind Dynamic Routing §10: a pivot Completes +
Releases the old set before Selecting the new one.)

## 12. What this router does NOT do

Author UI/backend/refactor changes by its own judgment; restate or override the routed skills'
rules; load every skill per task; edit protected domains before approval; create duplicate
authority; or authorize a deploy. It classifies, selects, delegates, and verifies — nothing more.

## 13. Test cases

`tests/` covers the routing contract (discussion/planning load no implementation skills; UI →
design pair; backend → fullstack + clean-code; browser → webapp-testing only; protected-domain
stop-and-ask; duplicate-authority rejection; Minimum Skill Principle; conflict resolution).
The task-type → skills mapping lives in `ARCHITECTURE_DECISION_MATRIX.md`. Re-validate both after
any edit.
