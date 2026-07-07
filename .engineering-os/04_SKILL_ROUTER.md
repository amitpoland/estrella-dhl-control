# 04 — Skill Router

**Source of truth:** `.claude/skills/SKILL_REGISTRY.md` (9 registered project skills; **FROZEN
2026-07-04**). This file is the *routing view*: which skill standard governs which package
layer, and the minimum-set rule. Skills **define standards**; agents (`03`) execute within them.

> Skills inform; they never act. A skill never authorizes a production mutation or a deploy.
> On conflict, the owning skill wins within its domain, but `CLAUDE.md` GATES 1–6 + Engineering
> Lessons win over all, and the 7-agent deploy gate owns production.

---

## 1. Registered skills (from SKILL_REGISTRY.md)

| Skill | Governs | Class |
|---|---|---|
| `ej-dashboard-master` | task classification + minimum-skill activation + workflow gates | orchestration / router |
| `frontend-design` | tokens, components, testids, write-button labeling, visual craft | governance / standard |
| `ej-dashboard-design` | V2 page authority, canonical-file resolution, duplicate prevention | governance / project layer |
| `ej-dashboard-fullstack-governance` | cross-layer route→service→model, stack-lock, protected domains, tests+rollback | governance / fullstack |
| `ej-dashboard-clean-code` | behavior-preserving refactor, authority preservation, repo-real verify | governance / refactor |
| `ej-dashboard-webapp-testing` | safe `/v2/` browser verification (read-only) | governance / verification |
| `ui-ux-pro-max` | UI/UX reference search — **never an authority** (read `EJ_OVERRIDES.md` first) | reference / search |
| `atlas-v2-render-gate` | post-deploy `/v2/` eyeball checklist (not a deploy authority) | review / checklist |
| `wfirma-api-integration` | wFirma API/behavior reference — informs, never acts | reference / knowledge |

---

## 2. Minimum Skill Principle (from `ej-dashboard-master`)

Select the **smallest valid skill set** — **never more than TWO** project skills unless the
task genuinely spans multiple domains (a true full-stack change).

| Package category | Minimum skills |
|---|---|
| UI Implementation | `frontend-design` + `ej-dashboard-design` |
| Backend Implementation | `ej-dashboard-fullstack-governance` + `ej-dashboard-clean-code` |
| Full Stack (only >2 case) | design pair + `ej-dashboard-fullstack-governance` |
| Refactoring | `ej-dashboard-clean-code` + the relevant domain skill |
| Code Review | `ej-dashboard-clean-code` |
| Browser Verification | `ej-dashboard-webapp-testing` |
| wFirma work | `wfirma-api-integration` (reference) + `ej-dashboard-fullstack-governance` (authority) |
| Architecture / Discussion / Planning / Question | **none** (answer directly; discussion-only) |
| Deployment | **none here** — the 7-agent deploy gate owns it |
| Documentation (explanatory) | none, unless it edits code (then the domain skill) |

`ui-ux-pro-max` is **never counted** as an activated authority — reference lookup only, filtered
through `frontend-design` + `EJ_OVERRIDES.md`. `atlas-v2-render-gate` is a post-deploy checklist,
not a deploy authority.

---

## 3. Conflict resolution (which skill wins)

| Concern | Winner |
|---|---|
| tokens, styling, spacing, typography | `frontend-design` |
| page authority, routing, duplicate prevention | `ej-dashboard-design` |
| backend, API, persistence, protected domains | `ej-dashboard-fullstack-governance` |
| refactor, simplicity, repo safety | `ej-dashboard-clean-code` |
| browser verification | `ej-dashboard-webapp-testing` |
| wFirma API mechanics | `wfirma-api-integration` (reference) → authority still `fullstack-governance` |
| anything | `ui-ux-pro-max` **never overrides** |

Above all: `CLAUDE.md` GATES 1–6 + Engineering Lessons > any skill; the 7-agent deploy gate
owns production.

---

## 4. Skill lifecycle (release discipline — token economy, `09`)

`Available → Selected → Active → Completed → Released`. At the **Close** step of a package,
**release every Active skill** from context so the next package starts from a clean minimum set.
On a pivot, unload the prior task's skills before loading the new set (Dynamic Routing).

---

## 5. Freeze policy (binding)

The 7-skill EJ Dashboard architecture is **FROZEN (2026-07-04)**. No new project skill may be
added unless (a) a recurring real problem is observed, (b) existing skills cannot solve it, and
(c) an architectural review approves it. Generic third-party skills are **never** installed raw.
The Engineering OS adds **no skill** — it routes the existing ones.
