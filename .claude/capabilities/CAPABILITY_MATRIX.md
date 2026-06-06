# CAPABILITY_MATRIX.md — Atlas V2 Capability Matrix

**Generated:** 2026-06-06 · **Purpose:** Map every capability to every Atlas V2 domain task so future sessions can auto-assemble the correct agent/skill/command/connector team.
**Canonical tree:** `C:\PZ-verify` · No product code modified.

---

## Reading the matrix

- **Bolded** = canonical (repo-installed or CLAUDE.md-named) — use these first
- `(rt)` = runtime-only — helper/output must be independently verified
- `(sk)` = skill reference — read before implementing
- `(cmd)` = slash command
- `(cn)` = MCP connector
- `(pl)` = plugin
- `⚠️` = write-capable; explicit operator approval required before use
- `❌` = forbidden for this domain (wrong domain, wrong stack, or no authority)
- `✅` = confirmed working in this project

---

## Domain Definitions

| Domain | What it covers |
|---|---|
| **Planning** | Sprint selection, Phase 0 authority audit, gap identification, task breakdown |
| **Architecture** | System design, API contract, component structure, authority mapping |
| **Frontend** | V2 JSX pages, index.html, mock-badge, shared components, testids |
| **Backend** | FastAPI routes, services, Python logic, API layer |
| **Testing** | Test authoring, coverage review, regression suite, source-grep tests |
| **Browser QA** | GATE 6 browser verification, network/console inspection, DOM check |
| **Security** | Auth guards, credential safety, write gates, injection, secrets |
| **Deploy** | 7-agent gate, robocopy sync, service restart, rollback |
| **DHL** | DHL API, customs clearance, ZC429, SAD, MRN, AWB, Lane A/B |
| **Inventory** | Piece-level tracking, state transitions, reservations, warehouse |
| **Proforma** | Sales lines, proforma/invoice lifecycle, wFirma proforma push |
| **Accounting** | PZ creation, wFirma, VAT, financial control, ledger posting |
| **wFirma** | wFirma API integration, credentials gate, XML/JSON mapping |
| **Database** | SQLite schema, migrations, storage files, audit DB |
| **AI** | Intelligence endpoints, ai-bridge, compliance resolver, learning |
| **Automation** | Cowork pipeline, action proposals, background jobs, scheduler |
| **Reporting** | Batch summaries, Cliq posting, WorkDrive uploads, dashboards |

---

## Full Capability Matrix

### PLANNING

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`gap-hunter` (A1)** | Repo agent | Hunt hidden gaps, contradictions, stale assumptions before sprint begins | ✅ SAFE_READ_ONLY |
| **`gap-detection` (A19)** | Repo agent ⚠️Lesson-B | 10-category pre-work gap scan | ✅ SAFE_READ_ONLY |
| **`flow-context-keeper` (A15)** | Repo agent | Read PROJECT_STATE.md — RULE 1 (every session start) | ✅ SAFE_READ_ONLY |
| **`/pz-audit-roadmap` (C2)** | Repo cmd | Full codebase audit → decision-ready roadmap | ✅ SAFE_READ_ONLY |
| **`/inspect-route` (C1)** | Repo cmd | Endpoint authority audit pre-implementation | ✅ SAFE_READ_ONLY |
| **`/engineering-lessons` (C4)** | Repo cmd | Engineering lesson reference before incident fixes | ✅ SAFE_READ_ONLY |
| `system-architect` (rt) | Runtime agent | Tech structure design helper | helper only |
| `planning-task-breakdown` (rt) | Runtime agent | File impact map helper | helper only |
| `product-owner-interpreter` (rt) | Runtime agent | Business goal → scope helper | helper only |
| `assumption-builder` (rt) | Runtime agent | Document assumptions | helper only |
| `misunderstanding-prevention` (rt) | Runtime agent | Pre-code interpretation check | helper only |
| `senior-architect` skill (S4) | User skill | Architecture diagrams + patterns | reference only (EJ stack overrides apply) |

---

### ARCHITECTURE

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`gap-hunter` (A1)** | Repo agent | Detect architecture contradictions | ✅ SAFE_READ_ONLY |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review API contract and service boundaries | ✅ SAFE_REVIEW |
| **`integration-boundary` (A18)** | Repo agent ⚠️Lesson-B | Verify FE/BE/storage/external seams | ✅ SAFE_REVIEW |
| **`reviewer-challenge` (A16)** | Repo agent | Attack architectural decisions before code | ✅ SAFE_REVIEW |
| **`/inspect-route` (C1)** | Repo cmd | Inspect endpoint payload/validation | ✅ SAFE_READ_ONLY |
| **`frontend-design` skill (S1)** | Repo skill | V2 authority-layer rules (no domain-blurring) | ✅ SAFE_READ_ONLY |
| `system-architect` (rt) | Runtime agent | System architecture helper | helper only |
| `senior-architect` skill (S4) | User skill | Generic architecture reference | reference only |

---

### FRONTEND (V2 Shell — Vanilla HTML + Babel JSX)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`frontend-flow-reviewer` (A3)** | Repo agent | Review operator flow, dead actions, unsafe API calls | ✅ SAFE_REVIEW |
| **`ux-flow` (A17)** | Repo agent ⚠️Lesson-B | UX sanity — confusing buttons, dead paths, orphan states | ✅ SAFE_REVIEW |
| **`reviewer-challenge` (A16)** | Repo agent | V2 PR mandatory review (CLAUDE.md Lesson F §8) | ✅ SAFE_REVIEW |
| **`test-coverage-reviewer` (A5)** | Repo agent | Verify testid/source-grep test coverage | ✅ SAFE_REVIEW |
| **`frontend-design` skill (S1)** | Repo skill | CSS vars, shared components, testids, no auto-save | ✅ SAFE_READ_ONLY |
| **`ui-ux-pro-max` skill (S3)** | Repo skill | UI/UX reference (with EJ_OVERRIDES.md filter) | ✅ SAFE_READ_ONLY |
| **`atlas-v2-render-gate` skill (S2)** | Repo skill | Post-deploy eyeball checklist | ✅ SAFE_READ_ONLY |
| **Claude Preview MCP (CN10)** | Connector | Browser smoke — GATE 6 | ✅ SAFE_READ_ONLY |
| `frontend-ui` (rt) ⚠️ | Runtime agent ⚠️ | Build frontend code | WRITE_RISK — defaults to TS+Tailwind (wrong stack) |
| `button-functionality` (rt) | Runtime agent | Button wiring audit helper | helper only |
| `ux-flow` (rt) | Runtime agent | UX review helper (also repo A17) | helper only |
| `/button-audit` (C11) | User cmd | Comprehensive button audit | SAFE_REVIEW |
| ❌ `TypeScript` | — | FORBIDDEN — not this project's stack | — |
| ❌ `Tailwind` | — | FORBIDDEN — not this project's stack | — |
| ❌ `Next.js` / bundlers | — | FORBIDDEN — vanilla HTML + CDN only | — |

---

### BACKEND (FastAPI / Python)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`backend-safety-reviewer` (A2)** | Repo agent | Review routes for unsafe writes, false evidence, fake paths | ✅ SAFE_REVIEW |
| **`security-write-action-reviewer` (A4)** | Repo agent | Review write actions for gates, idempotency, audit | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect stale routes, security drift, concurrency holes | ✅ SAFE_READ_ONLY |
| **`integration-boundary` (A18)** | Repo agent ⚠️Lesson-B | Verify FE→BE connection is real, not assumed | ✅ SAFE_REVIEW |
| **`reviewer-challenge` (A16)** | Repo agent | Attack backend design before implementation | ✅ SAFE_REVIEW |
| **`/review-execution` (C5)** | Repo cmd | Review execution-engine use, idempotency, readiness | ✅ SAFE_REVIEW |
| **`/patch` (C6)** ⚠️ | Repo cmd | Smallest safe backend patch | WRITE_RISK — approval before merge |
| `backend-api` (rt) ⚠️ | Runtime agent ⚠️ | Generic backend implementation | WRITE_RISK — not canonical, not EJ-domain-aware |
| `security-permissions` (rt) | Runtime agent | Security review helper | helper only |
| `finance-accounting-logic` (rt) | Runtime agent | Accounting treatment review (read-only helper) | helper only |

---

### TESTING

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`test-coverage-reviewer` (A5)** | Repo agent | Review coverage, negative cases, source-grep tests | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Verify test contracts match real builder shapes (Lesson A) | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect missing test scenarios | ✅ SAFE_READ_ONLY |
| **`/review-execution` (C5)** | Repo cmd | Review execution-safety test coverage | ✅ SAFE_REVIEW |
| `testing-verification` (rt) ⚠️ | Runtime agent ⚠️ | Write and execute tests | WRITE_RISK — can execute, not canonical |
| `ci-runner` (rt) | Runtime agent | Run CI locally (orchestrator runs `make verify` directly) | helper only |

**Test baseline:** 160/160 PZ golden + ≥381 carrier. Must never drop. `make verify` before any deploy.

---

### BROWSER QA (GATE 6)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **Claude Preview MCP (CN10)** | Connector | Start dev server, screenshot, console/network log, click, inspect | ✅ SAFE_READ_ONLY |
| **`atlas-v2-render-gate` skill (S2)** | Repo skill | Post-deploy eyeball checklist | ✅ SAFE_READ_ONLY |
| **`frontend-flow-reviewer` (A3)** | Repo agent | Review operator flow (source-level) | ✅ SAFE_REVIEW |
| **`ux-flow` (A17)** | Repo agent | UX sanity check (source-level) | ✅ SAFE_REVIEW |
| Claude in Chrome (CN11) | Connector | DOM inspection, form testing | SAFE_REVIEW / WRITE_RISK |
| Computer Use (CN13) | Connector | Desktop screenshot/verification | PRODUCTION_RISK |
| `browser-verifier` (rt) ⚠️ | Runtime agent | Browser automation | **Not as actor** — orchestrator uses Preview MCP |
| ❌ No repo browser agent | — | Accepted gap — Preview MCP is the path | — |

**GATE 6 is orchestrator-driven.** Browser verification requires: dev server on isolated port, `apiFetch` with `API_KEY=""`, automation flags OFF, `ENVIRONMENT=dev`. Sprint 30/31/32 all used Preview MCP successfully.

---

### SECURITY

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Primary write-risk reviewer — gates/idempotency/audit | ✅ SAFE_REVIEW |
| **`deploy-security-reviewer` (A9)** | Repo agent | Credential exposure, auth bypass, injection | ✅ SAFE_DEPLOY_SUPPORT |
| **`backend-safety-reviewer` (A2)** | Repo agent | Unsafe writes, false evidence, fake paths | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Security drift, concurrency holes, stale routes | ✅ SAFE_READ_ONLY |
| **`reviewer-challenge` (A16)** | Repo agent | Attack security design assumptions | ✅ SAFE_REVIEW |
| `security-permissions` (rt) | Runtime agent | Credential/auth review helper | helper only |
| `compliance` (rt) | Runtime agent | VAT/AML/audit review helper | helper only |

**Security blocker rule:** `deploy-security-reviewer` blocks cannot be overridden by anyone, including `deploy-lead-coordinator`. This is absolute.

---

### DEPLOY (7-Agent Gate — Production Sync to C:\PZ)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`deploy-git-diff-reviewer` (A6)** | Repo agent | File classification, forbidden paths, Lesson J engine files | ✅ SAFE_DEPLOY_SUPPORT |
| **`deploy-backend-impact-reviewer` (A7)** | Repo agent | Route auth, router registration, imports | ✅ SAFE_DEPLOY_SUPPORT |
| **`deploy-persistence-storage-reviewer` (A8)** | Repo agent | Schema mutations, storage writes, migration plan | ✅ SAFE_DEPLOY_SUPPORT |
| **`deploy-security-reviewer` (A9)** | Repo agent | Credentials, auth bypass, injection — **unconditional block authority** | ✅ SAFE_DEPLOY_SUPPORT |
| **`deploy-qa-reviewer` (A10)** | Repo agent | Regression count (160 PZ + ≥381 carrier) | ✅ SAFE_DEPLOY_SUPPORT |
| **`deploy-release-manager` (A11)** | Repo agent | Branch hygiene, rollback command, sync plan | ✅ SAFE_DEPLOY_SUPPORT |
| **`deploy-lead-coordinator` (A12)** | Repo agent | GO/NO-GO — final authority | ✅ SAFE_DEPLOY_SUPPORT |
| **`/deploy` (C8)** | Repo cmd | Invokes all 7 in parallel | PRODUCTION_RISK — full gate required |
| Computer Use (CN13) ⚠️ | Connector | Execute robocopy to C:\PZ, sc.exe service restart | PRODUCTION_RISK — operator executes |
| `deployment-windows-ops` (rt) ⚠️ | Runtime agent ⚠️ | NSSM/.env/service management | PRODUCTION_RISK — **quarantined, NOT safe as actor** |

**Deploy invariants:** No deploy without all 7 agents in parallel. Security block = absolute stop. `__pycache__` cleared before backend restart. Engine files (outside `service/app/**`) need separate robocopy to `C:\PZ\engine\` (Lesson J).

---

### DHL (Customs / Clearance / Shipment Tracking)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Review any DHL write action for safety gates | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review DHL route safety | ✅ SAFE_REVIEW |
| **`/inspect-route` (C1)** | Repo cmd | Audit DHL endpoints before wiring | ✅ SAFE_READ_ONLY |
| **`/cowork-integration` (C3)** | Repo cmd | Cowork → DHL action reference | ✅ SAFE_READ_ONLY |
| **`integration-boundary` (A18)** | Repo agent | Verify DHL ↔ app wiring | ✅ SAFE_REVIEW |
| Zoho Mail admin (CN5) | Connector | Read DHL email evidence (read-only) | SAFE_READ_ONLY (read tools only) |
| PDF Viewer plugin (P6) | Plugin | Read customs PDFs (ZC429, SAD) | SAFE_READ_ONLY |
| `dhl-customs` (rt) ⚠️ | Runtime agent ⚠️ | DHL API calls, customs mutations | **QUARANTINED — NOT safe as actor** |

**Authority rule:** Lane A/B authority is the deterministic engine. DHL endpoints are: `GET /api/v1/dhl/status`, `GET /api/v1/dhl/shipments` (confirmed real). `auto-scan-status` and `daily-summary` were hallucinated in one audit — always verify endpoints against `@router.get` registrations.

---

### INVENTORY

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Review inventory state transitions for readiness gates | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review inventory route safety | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect inventory state machine gaps | ✅ SAFE_READ_ONLY |
| **`reviewer-challenge` (A16)** | Repo agent | Attack inventory lifecycle design | ✅ SAFE_REVIEW |
| **`/review-execution` (C5)** | Repo cmd | Review `inventory_state_engine.transition()` usage | ✅ SAFE_REVIEW |
| `inventory-state-machine` (rt) ⚠️ | Runtime agent ⚠️ | State transitions, reservations, piece-level mutations | **QUARANTINED** |
| `warehouse-ops` (rt) ⚠️ | Runtime agent ⚠️ | Scan records, stock mutations | **QUARANTINED** |

**Authority rule:** All inventory writes must go through `inventory_state_engine.transition()`. No direct state mutation. 409 WRONG_STATE is the idempotency guard.

---

### PROFORMA (Sales Documents)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Review proforma write actions | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review proforma route safety | ✅ SAFE_REVIEW |
| **`frontend-flow-reviewer` (A3)** | Repo agent | Review proforma V2 UI flow | ✅ SAFE_REVIEW |
| **`reviewer-challenge` (A16)** | Repo agent | Attack proforma design (Lesson F §8 — first V2 PR is critical) | ✅ SAFE_REVIEW |
| **`frontend-design` skill (S1)** | Repo skill | Proforma V2 page authority rules | ✅ SAFE_READ_ONLY |
| **`integration-boundary` (A18)** | Repo agent | Verify proforma FE↔BE connection | ✅ SAFE_REVIEW |
| `sales-proforma` (rt) ⚠️ | Runtime agent ⚠️ | Proforma/invoice mutations | **QUARANTINED** |

---

### ACCOUNTING (wFirma / PZ / VAT)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Review accounting writes — highest priority gate | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review accounting route safety | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect stale accounting logic | ✅ SAFE_READ_ONLY |
| `finance-accounting-logic` (rt) | Runtime agent | Accounting treatment review (read-only helper) | helper only — read, no writes |
| `compliance` (rt) | Runtime agent | VAT/customs compliance review (read-only helper) | helper only |
| `pz-purchase-accounting` (rt) ⚠️ | Runtime agent ⚠️ | PZ document creation in wFirma | **QUARANTINED** |
| `wfirma-integration` (rt) ⚠️ | Runtime agent ⚠️ | Direct wFirma API calls | **QUARANTINED** |

**Financial rules (immutable):** Freight/insurance: proportional by value, never by piece. Duty: from ZC429/A00 only. B00 VAT: reference-only. Notes/UWAGI: from engine only. `process_batch()` is the only calculation path.

---

### wFirma Integration

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Review wFirma write calls for safety gates | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review wFirma API route safety | ✅ SAFE_REVIEW |
| **`/review-execution` (C5)** | Repo cmd | Review wFirma API call idempotency | ✅ SAFE_REVIEW |
| `wfirma-integration` (rt) ⚠️ | Runtime agent ⚠️ | Live wFirma API reads/writes | **QUARANTINED** — can issue financial mutations |
| `client-contractor-mapping` (rt) ⚠️ | Runtime agent ⚠️ | Contractor master mutations + wFirma | **QUARANTINED** |

**Credential rule:** wFirma credentials must be gated behind `require_api_key`. Never exposed in logs or responses. Lesson K applies to any agent prompt with wFirma write access.

---

### DATABASE (SQLite / Storage)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`deploy-persistence-storage-reviewer` (A8)** | Repo agent | Schema mutation detection, migration plan | ✅ SAFE_DEPLOY_SUPPORT |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review storage writes for safety | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect schema drift, stale queries | ✅ SAFE_READ_ONLY |
| `database-storage` (rt) ⚠️ | Runtime agent ⚠️ | Schema changes, migrations | **QUARANTINED** — can DROP TABLE |

**Storage invariant:** `documents.db`, `packing.db`, `audit.json` — no direct mutation without migration plan. All schema changes require a separate migration + `deploy-persistence-storage-reviewer` sign-off.

---

### AI (Intelligence / Advisory)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`backend-safety-reviewer` (A2)** | Repo agent | Review AI advisory routes | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect AI endpoint gaps | ✅ SAFE_READ_ONLY |
| **`/inspect-route` (C1)** | Repo cmd | Audit AI endpoints before wiring | ✅ SAFE_READ_ONLY |
| **`integration-boundary` (A18)** | Repo agent | Verify AI ↔ frontend connection | ✅ SAFE_REVIEW |

**Sprint 33 target:** `routes_intelligence.py` GET endpoints (`/status`, `/suggestions`, `/config`, `/actors`, `/insights`, `/graph`) + `routes_learning.py` (`/summary`, `/patterns/{supplier_key}`). All read-only. No writes. Feature flags `ai_advisory_llm_enabled=False` by default.

---

### AUTOMATION (Cowork / Action Proposals / Background Jobs)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **`security-write-action-reviewer` (A4)** | Repo agent | Review automation write actions — Lesson E mandatory | ✅ SAFE_REVIEW |
| **`backend-safety-reviewer` (A2)** | Repo agent | Review cowork pipeline routes | ✅ SAFE_REVIEW |
| **`/cowork-integration` (C3)** | Repo cmd | Cowork architecture + rules reference | ✅ SAFE_READ_ONLY |
| **`/review-execution` (C5)** | Repo cmd | Review action-runner execution safety | ✅ SAFE_REVIEW |
| **Scheduled Tasks (CN20)** ⚠️ | Connector ⚠️ | Create/manage scheduled tasks | PRODUCTION_RISK — all 5 Lesson E properties required |

**Automation invariant:** Cowork must NEVER send emails, choose recipients, attach files, or mutate finance directly. All 5 Lesson E safety properties (execution-time validation, idempotency, terminal-state suppression, replay safety, environment isolation) required for any background email automation.

---

### REPORTING (Batch Results / Cliq / WorkDrive)

| Capability | Type | Role | Safe? |
|---|---|---|---|
| **Zoho Cliq (CN1)** ⚠️ | Connector | Post batch results to `#PZ` — production channel | WRITE_RISK — sends real messages |
| **Zoho WorkDrive (CN4)** ⚠️ | Connector | Upload PDFs/XLSXs, create share links | WRITE_RISK — publishes files |
| **`/pz-shipment` (C7)** ⚠️ | Repo cmd | Full batch run + Cliq post | PRODUCTION_RISK — operator approval required |
| **`frontend-flow-reviewer` (A3)** | Repo agent | Review reporting V2 UI (dashboard/shipments) | ✅ SAFE_REVIEW |
| **`gap-hunter` (A1)** | Repo agent | Detect stale reporting logic | ✅ SAFE_READ_ONLY |

**Reporting invariant:** `process_batch()` is the only calculation path. Never recompute in the Cliq layer. Always post to Cliq immediately — WorkDrive state does not block notification. Never send local file paths or localhost URLs.

---

## Recommended Team Templates (copy-paste for sprint planning)

### T1. V2 Read-Only Shell Sprint (pattern: Sprint 30/31/32)

```
Agents (parallel, review phase):
  - reviewer-challenge (A16) — MANDATORY on V2 PRs
  - frontend-flow-reviewer (A3)
  - ux-flow (A17)
  - test-coverage-reviewer (A5)
  - integration-boundary (A18)

Skills (read before implementation):
  - frontend-design (S1)
  - atlas-v2-render-gate (S2) [after deploy]

Browser QA (GATE 6):
  - Claude Preview MCP (CN10) — isolated dev server

Deploy gate (all 7 in parallel):
  - deploy-git-diff-reviewer (A6)
  - deploy-backend-impact-reviewer (A7)
  - deploy-persistence-storage-reviewer (A8)
  - deploy-security-reviewer (A9) — NEVER overridable
  - deploy-qa-reviewer (A10) — must have pre-run test output
  - deploy-release-manager (A11)
  - deploy-lead-coordinator (A12) — LAST

Post-run governance:
  - agent-performance-observer (A14) — RULE 2
  - flow-context-keeper (A15) — RULE 3
```

---

### T2. Write-Risk Backend Sprint

```
Additional agents (above T1):
  - backend-safety-reviewer (A2) — MANDATORY
  - security-write-action-reviewer (A4) — MANDATORY
  - gap-hunter (A1) — pre-sprint
  - deploy-persistence-storage-reviewer (A8) — if schema changes

Commands:
  - /review-execution (C5) — execution safety
  - /inspect-route (C1) — verify endpoint before coding
  - /engineering-lessons (C4) — before incident fixes
```

---

### T3. Production Deploy

```
Sequence:
  1. Confirm PR merged to main (GATE 1 must be complete)
  2. Run all 7 deploy-gate agents in parallel (A6–A11)
  3. deploy-lead-coordinator (A12) synthesises — GO/NO-GO
  4. If GO: operator runs robocopy sync to C:\PZ
  5. If backend: clear __pycache__, restart PZService
  6. Post-deploy smoke: Preview MCP + atlas-v2-render-gate skill
  7. agent-performance-observer (A14) — RULE 2
  8. flow-context-keeper (A15) — RULE 3

Command: /deploy (C8)
```

---

### T4. Incident Fix (Lesson I framework)

```
Step 0: /engineering-lessons (C4) — load Lesson I 6-step framework
Step 1: Classify (authority chain / persistence / lifecycle / etc.)
Step 2: Name authority owner
Step 3: Cardinal question: workflow class

Agents:
  - gap-hunter (A1) — scope contradictions
  - reviewer-challenge (A16) — attack the fix
  - backend-safety-reviewer (A2) — route safety
  - security-write-action-reviewer (A4) — if write path
  - test-coverage-reviewer (A5) — regression tests required

Closure gate:
  - Root cause (1 sentence)
  - Authority owner named
  - Workflow class named
  - Recovery path verified end-to-end
  - Regression tests added
  - Existing workflows verified unaffected
```

---

## Classification Summary

| Classification | Description | Agent examples |
|---|---|---|
| SAFE_READ_ONLY | Zero production risk. Inspect/search/reference only. | gap-hunter, gap-detection, all deploy reviewers |
| SAFE_REVIEW | Returns verdicts/findings. No product mutation. | backend-safety-reviewer, frontend-flow-reviewer, reviewer-challenge |
| SAFE_DEPLOY_SUPPORT | Deploy gate reviewer. Verdict only. Cannot execute deploys. | All 7 deploy-gate agents |
| SAFE_IMPLEMENTATION | Can write code under operator oversight (gate-bound). | /patch (with approval) |
| WRITE_RISK | Can write product files. Requires operator oversight. Not for autonomous use. | frontend-ui(rt), backend-api(rt), testing-verification(rt) |
| FINANCIAL_RISK | wFirma/accounting/proforma writes. Requires explicit safety review. | wfirma-integration(rt), pz-purchase-accounting(rt), sales-proforma(rt) |
| CUSTOMS_RISK | DHL/customs/MRN writes. Requires explicit safety review. | dhl-customs(rt) |
| PRODUCTION_RISK | NSSM/service/inventory/deploy. Full blast radius. | deployment-windows-ops(rt), /deploy, Scheduled Tasks |
| UNKNOWN | Unverified domain or wrong domain. Do not dispatch for EJ work. | brand-voice:*, bio-research:*, legal-* |
