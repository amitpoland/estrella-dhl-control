# COMMANDS.md — Atlas V2 Capability Registry: All Slash Commands

**Generated:** 2026-06-06 · **Source:** `.claude/commands/COMMAND_REGISTRY.md` + `~/.claude/commands/` inspection
**Canonical tree:** `C:\PZ-verify` · No product code modified.

---

## Overview

Slash commands are operator-invocable workflows. Capability tier is binding:
- **READ-ONLY** — may run without confirmation
- **REVIEW-ONLY** — structured review; edits nothing; no confirmation needed
- **WRITE-CAPABLE** — requires operator approval before merge/deploy
- **DEPLOY-CAPABLE** — requires operator approval + full 7-agent gate; highest risk

| # | Command | Source | Tier | Operator approval |
|---|---|---|---|---|
| 1 | `/inspect-route` | REPO | READ-ONLY | Not required |
| 2 | `/pz-audit-roadmap` | REPO | READ-ONLY | Not required |
| 3 | `/cowork-integration` | REPO | READ-ONLY reference | Not required |
| 4 | `/engineering-lessons` | REPO | READ-ONLY reference | Not required |
| 5 | `/review-execution` | REPO | REVIEW-ONLY | Not required |
| 6 | `/patch` | REPO | WRITE-CAPABLE | Required before merge/deploy |
| 7 | `/pz-shipment` | REPO | WRITE-CAPABLE | Required (live batch + Cliq) |
| 8 | `/deploy` | REPO | DEPLOY-CAPABLE | Required + full 7-agent gate |
| 9 | `/run` | USER | ORCHESTRATION | Task-dependent |
| 10 | `/pz-feature` | USER | ORCHESTRATION | Task-dependent |
| 11 | `/button-audit` | USER | REVIEW + WRITE | Approval before merge |
| 12 | `/legal-matter` | USER | WRITE-CAPABLE | Required (legal domain) |

---

## Repo Commands (`C:\PZ-verify\.claude\commands\`)

---

### C1. `/inspect-route` — READ-ONLY

| Field | Value |
|---|---|
| **Name** | `/inspect-route` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\inspect-route.md` |
| **Purpose** | Inspect an API endpoint — identify payload/validation/UI-safety properties. Pre-implementation discovery. Used to verify endpoints before wiring a V2 UI page (e.g. confirming the 4 DHL endpoints before Sprint 31). |
| **Capability** | READ-ONLY — explicitly forbids file edits |
| **Tools granted** | Read/Grep/Glob equivalent — inspection only |
| **R/W level** | READ-ONLY |
| **Production risk** | NONE |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Before wiring any V2 page to a new endpoint. Pre-sprint authority audit step. |
| **Forbidden use** | Editing files. Treating the inspection result as an authorization to deploy. |

---

### C2. `/pz-audit-roadmap` — READ-ONLY

| Field | Value |
|---|---|
| **Name** | `/pz-audit-roadmap` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\pz-audit-roadmap.md` |
| **Purpose** | Scan the full PZ codebase and produce a decision-ready audit roadmap. Authority inventory, gap identification, sprint planning input. |
| **Capability** | READ-ONLY — modifies nothing |
| **Tools granted** | Read/Grep/Glob |
| **R/W level** | READ-ONLY |
| **Production risk** | NONE |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Sprint planning, authority audits (e.g. the Atlas V2 Phase 0 authority audit). |
| **Forbidden use** | File modification. Treating the roadmap as an authorization to deploy. |

---

### C3. `/cowork-integration` — READ-ONLY reference

| Field | Value |
|---|---|
| **Name** | `/cowork-integration` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\cowork-integration.md` |
| **Purpose** | Cowork architecture reference: flow (Cowork Intelligence → PZ Validation → PZ Automation → SMTP → Audit), draft-type reference, allowed/forbidden Cowork result fields, action-runner rules. |
| **Capability** | READ-ONLY reference |
| **Tools granted** | None (reference document) |
| **R/W level** | READ-ONLY |
| **Production risk** | NONE |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Before touching any cowork-adjacent code. Before writing/reviewing `cowork_result_processor.py` or `cowork_action_runner.py`. |
| **Forbidden use** | Not an actor — does not run cowork. Cowork must never send emails / choose recipients / attach files / mutate finance (CLAUDE.md §9). |

---

### C4. `/engineering-lessons` — READ-ONLY reference

| Field | Value |
|---|---|
| **Name** | `/engineering-lessons` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\engineering-lessons.md` |
| **Purpose** | Full origin narratives, detection signals, and worked examples for Engineering Lessons A–K (CLAUDE.md permanent lessons). |
| **Capability** | READ-ONLY reference |
| **Tools granted** | None (reference document) |
| **R/W level** | READ-ONLY |
| **Production risk** | NONE |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Before any incident-driven fix. Before applying Lesson I's 6-step workflow-class framework. Before a Lesson A stub-shape check. Before a Lesson G stale-artifact investigation. Before any background email automation (Lesson E). Before any agent-prompt authoring (Lesson K). |
| **Forbidden use** | Reference only — no actions. |

---

### C5. `/review-execution` — REVIEW-ONLY

| Field | Value |
|---|---|
| **Name** | `/review-execution` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\review-execution.md` |
| **Purpose** | Review execution safety: confirm `execution_engine` is used (not reimplemented), no direct unsafe POST from UI, idempotency exists, `execution_log` written, readiness guards present. |
| **Capability** | REVIEW-ONLY — does not edit; does not run the engine |
| **Tools granted** | Read/Grep/Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | NONE |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | After any change touching the execution path. Pairs with `security-write-action-reviewer`. |
| **Forbidden use** | Does not edit files. Does not run the engine. |

---

### C6. `/patch` — WRITE-CAPABLE

| Field | Value |
|---|---|
| **Name** | `/patch` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\patch.md` |
| **Purpose** | Make the smallest safe patch for a task — inspect first, edit only required files, no unrelated refactor. |
| **Capability** | WRITE-CAPABLE — edits product files |
| **Tools granted** | Read/Grep/Glob/Write/Edit |
| **R/W level** | FULL-WRITE (scoped to task) |
| **Production risk** | MEDIUM — product code mutation |
| **Classification** | WRITE_RISK |
| **Recommended use** | Small, scoped fixes after inspection. Pair with implementation-review group afterward. |
| **Forbidden use** | Large refactors without gate. Touching customs/accounting/inventory/wFirma/Lane A-B without safety review + deploy gate. Merging or deploying on its own. **Operator approval required before any resulting change merges or deploys.** |

---

### C7. `/pz-shipment` — WRITE-CAPABLE (live batch)

| Field | Value |
|---|---|
| **Name** | `/pz-shipment` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\pz-shipment.md` |
| **Purpose** | Run a live PZ shipment batch: `make verify` → `process_batch()` → PDF+XLSX → Cliq post → optional WorkDrive share links. Also the reference for full CLI syntax, flags, Cliq posting format, dynamic note 4 logic, and UWAGI text. |
| **Capability** | WRITE-CAPABLE — live batch run + Cliq post (external side effects) |
| **Tools granted** | Full tool set including Bash + MCP connectors |
| **R/W level** | FULL-WRITE + EXTERNAL (Cliq, WorkDrive) |
| **Production risk** | HIGH — live financial calculation + external posting |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Processing a real shipment batch when inputs are present and `make verify` passes. `process_batch()` is the only calculation path. |
| **Forbidden use** | Recomputing landed cost/freight/duty/notes outside the engine. Posting local paths/localhost to Cliq. Processing if `make verify` fails. Dry runs (live external side effects — not for testing). **Operator approval required.** |
| **Safety preconditions** | (1) `make verify` must pass · (2) Inputs must be present · (3) Operator confirmed |

---

### C8. `/deploy` — DEPLOY-CAPABLE

| Field | Value |
|---|---|
| **Name** | `/deploy` |
| **Source** | REPO · `C:\PZ-verify\.claude\commands\deploy.md` |
| **Purpose** | Trigger the full production deployment procedure via the mandatory 7-agent gate. Coordinates all deploy-gate agents, issues the sync command (robocopy to `C:\PZ`), and manages the health watchdog. |
| **Capability** | DEPLOY-CAPABLE — production mutation |
| **Tools granted** | Full tool set; 7-agent gate dispatched in parallel |
| **R/W level** | PRODUCTION-WRITE (`C:\PZ` — live service) |
| **Production risk** | CRITICAL |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Production deploy AFTER: PR merged to main, 7-agent gate returns READY-TO-DEPLOY, operator has authorized. Static-only deploys still run the full gate. |
| **Forbidden use** | Any deploy without the 7-agent gate. Deploying a dirty tree. Deploying engine/root files without the separate sync (Lesson J). Bypassing a `deploy-security-reviewer` block — IMPOSSIBLE by rule. **Operator approval + full gate mandatory — no exceptions.** |
| **Gate sequence** | (1) `deploy-git-diff-reviewer` · (2) `deploy-backend-impact-reviewer` · (3) `deploy-persistence-storage-reviewer` · (4) `deploy-security-reviewer` · (5) `deploy-qa-reviewer` · (6) `deploy-release-manager` · (7) `deploy-lead-coordinator` → GO/NO-GO |

---

## User Commands (`C:\Users\Super Fashion\.claude\commands\`)

---

### C9. `/run` — Universal Orchestration

| Field | Value |
|---|---|
| **Name** | `/run` |
| **Source** | USER · `C:\Users\Super Fashion\.claude\commands\run.md` |
| **Purpose** | Universal slash command. Replaces `/pz-feature`, `/legal-matter`, `/button-audit`. Reads CLAUDE.md + agent registry, classifies the task, selects agents, runs: Understand → Architect → Implement → Verify → Fix → Report. |
| **Capability** | ORCHESTRATION — delegates to appropriate agents based on task classification |
| **R/W level** | Depends on task (may be READ-ONLY or WRITE-CAPABLE) |
| **Production risk** | Task-dependent |
| **Classification** | SAFE_IMPLEMENTATION (orchestration) |
| **Recommended use** | Any task in any language (business or technical). The default entry point for all new work. |
| **Forbidden use** | Claude Code should not ask implementation questions when `/run` is used — if it does, file a memory-lessons entry. |
| **Escalation triggers** | Budget commitments >$500 · irreversible production decisions · legal risk acceptance · strategic direction only. |

---

### C10. `/pz-feature` — PZ Feature Pipeline

| Field | Value |
|---|---|
| **Name** | `/pz-feature` |
| **Source** | USER · `C:\Users\Super Fashion\.claude\commands\pz-feature.md` |
| **Purpose** | Dispatch a PZ app feature through a structured 12-agent pipeline: product-owner-interpreter → system-architect → planning-task-breakdown → reviewer-challenge → domain agents → backend-api → frontend-ui → button-functionality → testing-verification → security-permissions → integration-boundary → release-manager. |
| **Capability** | ORCHESTRATION (full implementation pipeline) |
| **R/W level** | FULL-WRITE (through implementation agents) |
| **Production risk** | HIGH — full feature implementation including write-capable agents |
| **Classification** | WRITE_RISK |
| **Recommended use** | PZ app feature development — structured pipeline for complex features. |
| **Forbidden use** | Read-only audits (use `/pz-audit-roadmap`). Superseded by `/run` as the universal entry point. |
| **Warning** | Activates quarantined write-capable agents (wfirma-integration, dhl-customs, pz-purchase-accounting, inventory-state-machine, client-contractor-mapping, backend-api, frontend-ui) — these are runtime-only, not canonical. Treat their output as helpers requiring independent verification. |

---

### C11. `/button-audit` — UI Button Audit

| Field | Value |
|---|---|
| **Name** | `/button-audit` |
| **Source** | USER · `C:\Users\Super Fashion\.claude\commands\button-audit.md` |
| **Purpose** | Comprehensive "every button must work" audit. Builds button registry (button → endpoint → state → test), detects dead buttons, identifies missing wiring. |
| **Capability** | REVIEW + limited WRITE (via testing-verification for test fixes) |
| **R/W level** | READ-first, WRITE for gap remediation |
| **Production risk** | MEDIUM |
| **Classification** | SAFE_REVIEW (audit phase) / WRITE_RISK (remediation phase) |
| **Recommended use** | After any major UI sprint. Before production release of a new page. |
| **Agent pipeline** | button-functionality → frontend-ui → backend-api → integration-boundary → ux-flow → testing-verification → release-manager |
| **Forbidden use** | Operator approval required before any remediations merge. |

---

### C12. `/legal-matter` — Legal Matter Pipeline

| Field | Value |
|---|---|
| **Name** | `/legal-matter` |
| **Source** | USER · `C:\Users\Super Fashion\.claude\commands\legal-matter.md` |
| **Purpose** | Legal matter handling pipeline. Likely activates legal-* agents. |
| **Capability** | WRITE-CAPABLE (legal documents) |
| **R/W level** | WRITE (legal domain only) |
| **Production risk** | MEDIUM (legal document risk) |
| **Classification** | UNKNOWN |
| **Recommended use** | Legal matters only — WRONG DOMAIN for EJ Atlas V2 technical work. |
| **Forbidden use** | Do not use for EJ product/technical work. Legal agents are wrong-domain. |

---

## Command Safety Matrix

| Command | Runs freely | Needs approval | Full deploy gate |
|---|---|---|---|
| `/inspect-route` | ✅ | — | — |
| `/pz-audit-roadmap` | ✅ | — | — |
| `/cowork-integration` | ✅ | — | — |
| `/engineering-lessons` | ✅ | — | — |
| `/review-execution` | ✅ | — | — |
| `/patch` | — | ✅ before merge | — |
| `/pz-shipment` | — | ✅ live batch | — |
| `/deploy` | — | ✅ always | ✅ always |
| `/run` | task-dependent | task-dependent | if deploy task |
| `/pz-feature` | — | ✅ before merge | if deploy included |
| `/button-audit` | audit phase | ✅ remediation | — |
| `/legal-matter` | — | ✅ | — |
