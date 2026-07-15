# SKILL_ROUTING.md — Automatic Skill Selection for /feature

Invoked at the start of Phase 1 DISCOVERY before any code is read.
Authority: this file is the single source for keyword → skill mapping.
`feature.md` references this file; it does not duplicate the tables.

---

## Algorithm

1. Tokenize `$ARGUMENTS` (lowercase, split on spaces and punctuation).
2. Score each domain row below — count keyword hits.
3. Pick the domain with the highest score. If two domains tie, pick both skills.
4. Set CONFIDENCE:
   - **HIGH** — ≥ 2 keyword hits in the winning domain
   - **MEDIUM** — 1 keyword hit in the winning domain
   - **LOW** — 0 hits (no domain matches); fall back to safest available skill
5. Output the routing block (see §Output format).
6. Low confidence → continue DISCOVERY, do not HOLD.
7. No match / MISSING skill → recommend missing skill, use `backend-route-and-service-builder` as universal fallback.

---

## Routing table

| TASK_TYPE | Keywords (any match scores +1) | PRIMARY_SKILL | SECONDARY_SKILL | Notes |
|---|---|---|---|---|
| `UI_FRONTEND` | ui, frontend, v2, dashboard, component, layout, css, page, visual, render, html, style, button, modal, tab, panel, form, chart, design, improve ui, fix ui, redesign, restyle, polish, modernize, clean up | `frontend-design` + `ej-dashboard-design` | `ui-ux-pro-max` | Always consult `ej-dashboard-design` (project governance layer) together with `frontend-design` — no automatic inheritance, both must be active. Read `EJ_OVERRIDES.md` before applying `ui-ux-pro-max` output. V1 frozen — check Lesson F. |
| `PROFORMA` | proforma, conflict, draft, snapshot, series, workspace, readiness, wired, pregate, pre-gate | `backend-route-and-service-builder` | *(planned: `proforma-engine`)* | `proforma-engine` planned but not installed. Use `backend-route-and-service-builder` until built. |
| `DHL_CUSTOMS` | dhl, customs, clearance, awb, carrier, label, sad, invoice line, customs duty, tariff, packing | `pz-shipment` | `customs-pz-safety-checker` | `customs-pz-safety-checker` mandatory for any PZ guard changes. |
| `WFIRMA_PZ` | wfirma, accounting, tax, vat, booked, pz calc, pz doc, pz number, pz import, zc429 | `backend-route-and-service-builder` | `wfirma-api-integration` (reference) | `wfirma-api-integration` reference skill **INSTALLED 2026-07-04** — read it for wFirma API behavior (auth, invoices, webhooks, gotchas). Implementation authority stays `ej-dashboard-fullstack-governance`; protected-domain approval (invoices/VAT/accounting/webhooks/persistence) is NOT bypassed. `pz-shipment` for PZ specifics. |
| `BACKEND_API` | backend, api, route, endpoint, service, database, db, sqlite, model, schema, migration | `backend-route-and-service-builder` | — | Read-only planner — produces plan, does not write code directly. |
| `AUDIT_EVIDENCE` | audit, evidence, timeline, log, trace, event, history, immutable | `audit-trace-reporter` | — | Read-only inspection only. |
| `DEPLOY_RELEASE` | deploy, release, production, sync, rollback, gate, pzservice, robocopy, nssm | `deploy` | — | Requires full 7-agent gate. Never skip. |
| `COWORK_EMAIL` | email, smtp, cowork, notification, sla, follow-up, followup, outbound, queue | `cowork-integration` | — | Lesson E binding: 5 safety properties mandatory for background email automation. |
| `TEST_REGRESSION` | test, regression, coverage, suite, pytest, golden, stub, fixture | `regression-test-guard` | — | Lesson A binding: stubs must match real builder return shapes. |
| `UI_REVIEW` | ui safety, review ui, flow review, usability, ux check, broken button, dead path | `dashboard-ui-consistency` | `ux-flow` agent | Pairs with `frontend-flow-reviewer` agent automatically. |
| `ZOHO` | zoho, cliq, workdrive, mail, oauth, token, webhook | `zoho-context-research` | — | Read-only research; does not call external APIs. |
| `GOVERNANCE` | governance, claude.md, command, protocol, rule, gate, lesson, adr | *(no runtime skill)* | `engineering-lessons` | Use AUTHORITY_MAP + TASK_EXECUTION_PROTOCOL.md directly. |
| `AI_BRIDGE` | ai bridge, ai task, anthropic api, tool use, claude api, prompt, model | `ai-bridge-result-validator` | `ai-bridge-task-generator` | ADR-020 binding: Anthropic is sole AI provider. |

---

## Output format

Every `/feature` invocation must emit this block at the start of Phase 1 DISCOVERY,
before any other output:

```
SKILL_ROUTING
─────────────────────────────────────────
TASK_TYPE:      <type from table above>
SELECTED_SKILL: <primary skill name(s)>
SECONDARY:      <secondary skill or "none">
REASON:         <which keywords matched>
CONFIDENCE:     HIGH | MEDIUM | LOW
─────────────────────────────────────────
```

If MISSING (skill exists in plan but not installed):

```
SKILL_ROUTING
─────────────────────────────────────────
TASK_TYPE:      <type>
SELECTED_SKILL: FALLBACK → backend-route-and-service-builder
SECONDARY:      none
REASON:         Matched <type> but <skill-name> not installed.
MISSING_SKILL:  <planned skill name>
CONFIDENCE:     LOW
─────────────────────────────────────────
```

---

## Sample routing resolutions

| Prompt | TASK_TYPE | SELECTED_SKILL | SECONDARY | CONFIDENCE | Notes |
|---|---|---|---|---|---|
| "Improve V2 UI" | `UI_FRONTEND` | `frontend-design` | `ui-ux-pro-max` | HIGH | "v2" + "ui" = 2 hits |
| "Fix proforma readiness" | `PROFORMA` | `backend-route-and-service-builder` | *(proforma-engine planned)* | MEDIUM | "proforma" + "readiness" = 2 hits; MISSING_SKILL: proforma-engine |
| "Check DHL customs" | `DHL_CUSTOMS` | `pz-shipment` | `customs-pz-safety-checker` | HIGH | "dhl" + "customs" = 2 hits |
| "Add backend route" | `BACKEND_API` | `backend-route-and-service-builder` | — | HIGH | "backend" + "route" = 2 hits |
| "Prepare deployment" | `DEPLOY_RELEASE` | `deploy` | — | HIGH | "deploy" = 1 strong hit (HIGH by single-keyword strength rule for deploy domain) |

---

## Single-keyword HIGH overrides

The following keywords are strong enough that 1 hit = HIGH confidence (not MEDIUM):

| Keyword | Domain |
|---|---|
| `deploy`, `release`, `production` | DEPLOY_RELEASE |
| `dhl` | DHL_CUSTOMS |
| `proforma` | PROFORMA |
| `wfirma` | WFIRMA_PZ |
| `cowork` | COWORK_EMAIL |

---

## Missing skills — planned but not yet installed

| Planned skill | Domain | Target domain | Status |
|---|---|---|---|
| `proforma-engine` | PROFORMA | Proforma / conflict / workspace | PLANNED — file when B2–B9 types designed |
| `dhl-customs` | DHL_CUSTOMS | DHL clearance / customs | PLANNED |
| `wfirma-api-integration` | WFIRMA_PZ | wFirma API / PZ accounting | **INSTALLED 2026-07-04** — reference-only (`.claude/skills/wfirma-api-integration/`), subordinate to `ej-dashboard-fullstack-governance`; no protected-domain bypass |
| `frontend-design` (global) | UI_FRONTEND | V1/V2 frontend | EXISTS as repo skill; invoke directly |

When `MISSING_SKILL` appears in routing output, record in `BACKLOG.md` with disposition SCHEDULED unless already present.

---

## Skill capability tiers

| Skill | Tier | Notes |
|---|---|---|
| `frontend-design` | SAFE_READ_ONLY | Governance reference |
| `ej-dashboard-design` | SAFE_READ_ONLY | Project governance layer; consult together with `frontend-design`; read `EJ_OVERRIDES.md` |
| `ui-ux-pro-max` | SAFE_READ_ONLY | Search tool; read EJ_OVERRIDES first |
| `audit-trace-reporter` | SAFE_READ_ONLY | Read-only inspection |
| `backend-route-and-service-builder` | SAFE_READ_ONLY | Plan-only; never writes code directly |
| `customs-pz-safety-checker` | SAFE_READ_ONLY | Guard audit only |
| `dashboard-ui-consistency` | SAFE_READ_ONLY | Review only |
| `zoho-context-research` | SAFE_READ_ONLY | Research only; no external API calls |
| `regression-test-guard` | READ + RUN | Executes tests; no code writes |
| `ai-bridge-result-validator` | SAFE_READ_ONLY | Validation only |
| `ai-bridge-task-generator` | WRITE_CAPABLE | Generates task files |
| `pz-shipment` | WRITE_CAPABLE | Live batch + Cliq post |
| `cowork-integration` | READ_ONLY (reference) | Architecture reference |
| `engineering-lessons` | READ_ONLY (reference) | Lesson narratives |
| `deploy` | DEPLOY_CAPABLE | Full 7-agent gate; highest risk |

---

## Handoff to agent selection

Skills and agents are **separate routing layers**:
- Selected skills define the **standards and constraints** for the package layer. Skills inform;
  they do **not** select agents.
- **Agent selection follows `.engineering-os/03_AGENT_ROUTER.md`** (§2 by-package routing).
- Select the **minimum** sufficient set: one lead + the named reviewer council + one gate.
  **Never activate all available agents** (`agent-router` quality gate; `chief-orchestrator`
  anti-pattern).
- Only **session-available installed skills** may be selected. An unavailable required skill is
  **reported explicitly** — never fabricated, never silently replaced by a similarly named skill.
