# Atlas-V2 Campaign Document

**Campaign:** Atlas-V2 — Fresh Frontend Shell  
**Branch prefix:** `atlas-v2/sprint-NN-<name>`  
**Campaign doc branch:** `atlas-v2/campaign-document`  
**Status:** PLANNING — no sprint has fired yet  
**Architecture reference:** `docs/v2-architecture-plan.md`  
**Design standard:** `.claude/skills/frontend-design.md`  
**Stack overrides:** `.claude/skills/ui-ux-pro-max/EJ_OVERRIDES.md`

---

## 1. Anti-Drift Gates — Read Before Firing Any Sprint

These must ALL be true before a sprint fires. If any fails, stop and resolve first.

| Gate | Check | Status |
|------|-------|--------|
| **PR #262 merged** | `gh pr view 262 --json state` → `"MERGED"` | ⚠️ OPEN at campaign-doc creation time |
| **EJ_OVERRIDES.md exists** | `ls .claude/skills/ui-ux-pro-max/EJ_OVERRIDES.md` | ✅ Exists |
| **`make verify` green** | `make verify` → 160/160 | Check before each sprint |
| **`test_proforma_v2_contract.py` green** | `pytest service/tests/test_proforma_v2_contract.py` → 44/44 | Check before each sprint |
| **Previous sprint PR merged** | `gh pr list --state open` shows no atlas-v2 sprint PR | Sprint N+1 does not fire until Sprint N merges |
| **Open PR count < 3** | Per GATE 2: max 3 simultaneous open PRs | Check before each sprint |
| **V1 freeze honoured** | No sprint edits `shipment-detail.html` or `dashboard.html` except critical fixes | Enforced by `reviewer-challenge` and `frontend-flow-reviewer` |

> **Note on PR #262:** The `fix/proforma-v2-operator-header-and-client-display` fix was authored
> before this campaign document was written. Sprint 01 (Proforma V2 Hardening) assumes PR #262
> has merged, because the header injection and client display fix are foundational to the page's
> correctness. Do not fire Sprint 01 until `gh pr view 262` returns `"MERGED"`.

---

## 2. Strategic Context

The backend is stable institutional infrastructure. What changes is the rendering shell:

- `shipment-detail.html` (~14,600 lines) is **frozen** — critical fixes only
- `dashboard.html` is **frozen** — critical fixes only
- Every new operator surface is a V2 page: isolated authority, layered architecture, single CDN delivery

The root cause of V1 fragmentation was **mixed authorities**: one file owning multiple domains,
each domain fetching and rendering independently. V2 fixes this structurally:
**one page = one domain authority**.

Full strategic rationale: `docs/v2-architecture-plan.md` §0, §2, §2b.

---

## 3. Stack Constraints (binding on every sprint)

| Constraint | Rule |
|------------|------|
| Framework | Vanilla HTML + Babel standalone (JSX in `<script type="text/babel" data-presets="env,react">`) |
| Bundler | None. Single-file CDN delivery only. |
| TypeScript | Forbidden. `.js` only, no type annotations. |
| Tailwind | Forbidden. CSS custom properties only (`--bg`, `--text-*`, `--badge-*`, `--accent`). |
| React source | `https://unpkg.com/react@18/umd/react.production.min.js` |
| Component library | `dashboard-shared.js` → `window.EstrellaShared` |
| ui-ux-pro-max | Supplemental only. Read `EJ_OVERRIDES.md` before applying any output. |
| Pattern reference | `service/app/static/proforma-v2.html` — every sprint follows this exactly |

Every sprint prompt contains a mandatory stack-constraint block. No agent may skip it.

---

## 4. Shared Layer Status

| File | Location | Current lines | Role | Rule |
|------|----------|--------------|------|------|
| `dashboard-shared.js` | `service/app/static/` | 517 | Visual atoms: `Badge`, `Card`, `Btn`, `Sel`, `Toast`, `SessionBanner`, `GateBlock`, `SectionHeader`, `CompactTable`, `StatusDot`, `EmptyState` | **Never** gains domain knowledge |
| `pz-api.js` | `service/app/static/` | 210 | Transport: fetch adapter, error normalisation, `window.PzApi` | Business logic forbidden |
| `pz-state.js` | `service/app/static/` | 125 | React hooks: `useProformaDrafts`, `useProformaPreview`, `useDraft`, `useCustomerMaster`, `useBatches`, `window.PzState` | Normalise only; no business rules |
| `pz-components.js` | `service/app/static/` | 343 | Domain-aware rendering: `DraftStateChip`, `ProformaReadinessGate`, `DraftLineRow`, `CustomerAuthorityCard`, `ProductAuthorityRow`, `DevBypassBanner`, `window.PzComponents` | Read-only rendering; no workflow decisions |

**Load order per V2 page (mandatory):**
```html
<script type="text/babel" data-presets="env,react" src="/dashboard/dashboard-shared.js"></script>
<script type="text/babel" data-presets="env,react" src="/dashboard/pz-api.js"></script>
<script type="text/babel" data-presets="env,react" src="/dashboard/pz-state.js"></script>
<script type="text/babel" data-presets="env,react" src="/dashboard/pz-components.js"></script>
```

**Shared layer extension rule:** Add to `dashboard-shared.js` only if ≥2 V2 pages need the primitive
AND it carries zero domain knowledge. Add to `pz-components.js` if domain-aware and needed by
≥2 pages. New hooks to `pz-state.js`. New fetches to `pz-api.js`. Do not create new shared files.

---

## 5. Agent Roster — 70 Agents Mapped to Sprint Roles

### 5.1 Every-Sprint Agents (mandatory, no exceptions)

| `subagent_type` | Sprint role | Notes |
|-----------------|-------------|-------|
| `chief-orchestrator` | Task routing, anti-escalation | First agent on every non-trivial sprint. Opus-class. |
| `gap-detection` | Pre-implementation gap scan | Fires before any coding. Opus-class. Detects missing APIs, missing backend, missing tests. |
| `reviewer-challenge` | Plan attack before coding | Fires on every plan and V2 PR. Specifically attacks V1-freeze violations and authority bleed. |
| `frontend-ui` | V2 page implementation | **Override required**: read `frontend-design.md` first. Ignores "React" default. Uses Vanilla HTML + Babel. |
| `testing-verification` | Write tests alongside implementation | Tests never skipped. |
| `browser-verifier` | Real browser verification after implementation | Mandatory. "Tests pass" ≠ "feature works". |
| `git-workflow` | Branch, commit, push | Fires after implementation + tests pass. |
| `pr-author` | Open PR with description | Fires after git-workflow. PR title ≤70 chars. |
| `agent-performance-observer` | Post-sprint scorecard | Fires after FINAL REPORT. Writes to `.claude/memory/scorecards/`. |
| `flow-context-keeper` | Update PROJECT_STATE.md | Fires after observer, after PR merges, after issue closes. |

### 5.2 Project-Agent Reviewers (mandatory per review layer)

| `subagent_type` | Review scope | Fires when |
|-----------------|-------------|------------|
| `frontend-flow-reviewer` | dashboard.html broken flow, unsafe API calls, hidden actions, disabled reasons | After every frontend implementation |
| `backend-safety-reviewer` | Unsafe writes, fake paths, missing idempotency, false evidence | After every backend change |
| `test-coverage-reviewer` | Missing negative tests, weak source-grep coverage | After every test write |
| `gap-hunter` | Hidden bugs, cross-phase contradictions, silent downgrades | After implementation, before PR opens |
| `adr-historian` | ADR creation for architectural decisions | When a new architectural decision is made |

### 5.3 Sprint-Conditional Agents (activate when sprint scope requires)

| `subagent_type` | Condition | Sprint relevance |
|-----------------|-----------|-----------------|
| `system-architect` | New page, new shared-layer extension, new API contract | Sprints 01–13 (all new pages) |
| `backend-api` | Sprint needs a new backend endpoint | Sprints 02, 03, 04, 07, 08, 09, 10 likely |
| `integration-boundary` | Full-stack wiring between new page and backend | After implementation, before browser-verifier |
| `ux-flow` | UX quality check on new operator surfaces | All UI sprints |
| `button-functionality` | Every-button audit on completed page | After browser-verifier confirms page loads |
| `deployment-windows-ops` | Post-PR production deploy | After each sprint PR merges |
| `release-manager` | Go/no-go before `/deploy` | After PR merges, before `/deploy` fires |
| `final-consistency-review` | Final gate: no incomplete work, no fake assumptions | Before PR opens |
| `misunderstanding-prevention` | Verify system understood task before coding | When sprint scope is ambiguous |
| `planning-task-breakdown` | File impact map, risk list, execution sequence | For sprints with broad scope |
| `flow-continuity` | Full execution chain check | After implementation, before testing |
| `assumption-builder` | Document assumptions, prevent operator interruption | Throughout execution |

### 5.4 Domain Agents (NOT activated in this campaign — out of scope)

These agents exist in the registry but their domains are backend infrastructure, not frontend rendering.
Do not activate unless a sprint explicitly uncovers a backend dependency.

| `subagent_type` | Why not activated |
|-----------------|-------------------|
| `dhl-customs` | DHL API work — backend only, no frontend changes |
| `wfirma-integration` | wFirma writes — frontend may NEVER enable new write flags |
| `pz-purchase-accounting` | PZ creation — gated at backend, not a frontend concern |
| `warehouse-ops` | Physical warehouse scan operations — separate from UI sprint |
| `document-intelligence` | PDF parsing — backend pipeline, not a V2 page domain |
| `email-evidence-recovery` | Email mailbox recovery — background process |
| `client-contractor-mapping` | wFirma contractor matching — backend-only |
| `inventory-state-machine` | Piece-level tracking engine — backend state machine |
| `sales-proforma` | Proforma backend lifecycle — backend routes |
| `compliance` | VAT/AML/sanctions — not a frontend concern |
| `finance-accounting-logic` | Accounting treatment — backend only |
| `legal-*` (6 agents) | Legal research/drafting — different domain entirely |
| `dhl-customs` | Customs evidence chains — backend pipeline |

### 5.5 Intake + Routing Agents (absorbed by `/run` command)

These fire automatically inside the `/run` command flow. Sprint prompts do not need to invoke them explicitly.

`natural-language-intake`, `intent-clarification`, `context-resolution`, `task-classification`,
`agent-router`, `escalation-filter`, `multimodal-evidence`, `product-owner-interpreter`

### 5.6 Deploy Gate Agents (7 agents — fire via `/deploy`)

These fire as a parallel gate inside `/deploy`. Sprint prompts end with `/deploy`; the command
triggers all 7 automatically.

| File | Role |
|------|------|
| `.claude/agents/deploy_lead_coordinator.md` | Final go/no-go |
| `.claude/agents/deploy_git_diff_reviewer.md` | File classification, forbidden paths |
| `.claude/agents/deploy_backend_impact_reviewer.md` | Route changes, auth, imports |
| `.claude/agents/deploy_persistence_storage_reviewer.md` | DB schema, storage writes |
| `.claude/agents/deploy_security_reviewer.md` | Credentials, auth removal, injection |
| `.claude/agents/deploy_qa_reviewer.md` | Test pass/fail, regression risk |
| `.claude/agents/deploy_release_manager.md` | Branch hygiene, rollback command |

---

## 6. Test Baseline (binding — do not lower)

Source of truth: `.claude/contracts/test-baseline.md`

| Suite | Required | Failure action |
|-------|----------|----------------|
| `make verify` (PZ regression) | 160/160 | Unconditional block |
| `pytest service/tests/test_proforma_v2_contract.py` | 44/44 | Unconditional block |
| Carrier suite (`tests/test_carrier_*.py`) | 366/366 | Unconditional block |

Each sprint must: (a) run all three before opening PR, (b) not reduce any count, (c) add tests for new code paths.

---

## 7. Governance Bindings

| Gate | Binding |
|------|---------|
| **GATE 1** (PR open discipline) | Every sprint PR requires: all reviewers returned verdict, HIGH/CRITICAL findings resolved, browser verification complete with console + network reviewed, regression tests green, forbidden-files check |
| **GATE 2** (max 3 open PRs) | If 3 atlas-v2 sprint PRs are open simultaneously, pause until at least 1 merges before opening another |
| **GATE 3** (branch status) | Sprint branches are ACTIVE until merged; mark ARCHIVED after merge + 30 days |
| **GATE 4** (salvage findings) | Any `gap-hunter` or `agent-performance-observer` NEEDS-TUNING verdict requires SCHEDULED / ISSUE / REJECTED disposition |
| **GATE 5** (agent substitution) | If a named agent is not in the registry, substituting agent must be disclosed in Section 2 of final report |
| **GATE 6** (browser verification) | No sprint is complete without: real browser flow, console errors checked, network requests verified, full button→API→DB chain observed |
| **Lesson F** (V2 freeze) | Every sprint PR triggers `reviewer-challenge` automatically. Block any PR touching V1 for non-critical reasons. |
| **Financial rules** | No sprint changes: freight/duty allocation, VAT calculation, landed cost formula, PZ creation, wFirma write flags |
| **Observation rules** | `agent-performance-observer` fires after every FINAL REPORT. `flow-context-keeper` fires after observer. |

---

## 8. V2 Page Authority Map

Each page owns exactly one domain. Crossing this boundary is a GATE 1 block.

| Page | Authority domain | Never |
|------|-----------------|-------|
| `proforma-v2.html` | Draft rendering, customer mapping display, readiness gate, approve/cancel | DHL, warehouse, customs, PZ creation, wFirma writes |
| `inbox-v2.html` | DHL email status, clearance pipeline inbox, pending customs items | Any write to customs docs, shipment state mutations |
| `shipment-v2.html` | Shipment pipeline, DHL tracking, timeline, document links | Draft editing, PZ creation, wFirma writes |
| `documents-v2.html` | SAD/ZC429/packing/invoice viewer per shipment | Customs calculation, PZ, wFirma |
| `customer-master-v2.html` | Customer CRUD, NIP/address, wFirma customer matching | Proforma drafts, PZ, products |
| `products-v2.html` | SKU → wFirma product mapping, Polish name, VAT rate, sync status | Customer mapping, proforma, PZ |
| `pz-v2.html` | PZ lifecycle display, warehouse gate status, wFirma reservation preview | Proforma draft editing, customer authority editing, DHL clearance |
| `warehouse-v2.html` | Scan-in workflow, packing-list verification, physical movement display | PZ creation, proforma, customer master |
| `inventory-v2.html` | Piece-level stock display, reservation status, dispatch state | Scan operations, PZ, wFirma writes |
| `batch-v2.html` | Batch management: create, status, linked shipments | Shipment editing, proforma drafts, PZ |
| `admin-v2.html` | User management, runtime flags (read), system settings | No domain data writes |
| `login.html` / `signup.html` / `forgot-password.html` | Auth flows only | No business domain data |
| `dashboard-v2.html` | Batch list aggregation (read-only), filter pills, search | Any editing surface, any write operation |

---

## 9. Sprint Sequence (23 sprints — operator-priority order)

Expanded 2026-05-26 from 13 → 23 sprints to cover the full design bundle in
`origin/atlas-v2/source-bundle:design-files/`. Sprints 14–23 added to map every
remaining JSX design source to a V2 surface.

| Sprint | Page | Branch | Dependency | Sprint file |
|--------|------|--------|------------|-------------|
| 01 | Proforma V2 Hardening | `atlas-v2/sprint-01-proforma-hardening` | PR #262 merged | `atlas-v2/sprint-01-proforma-v2-hardening.md` |
| 02 | Inbox V2 | `atlas-v2/sprint-02-inbox-v2` | Sprint 01 merged | `atlas-v2/sprint-02-inbox-v2.md` |
| 03 | Shipment V2 | `atlas-v2/sprint-03-shipment-v2` | Sprint 02 merged | `atlas-v2/sprint-03-shipment-v2.md` |
| 04 | Documents V2 | `atlas-v2/sprint-04-documents-v2` | Sprint 03 merged | `atlas-v2/sprint-04-documents-v2.md` |
| 05 | Customer Master V2 | `atlas-v2/sprint-05-customer-master-v2` | Sprint 04 merged | `atlas-v2/sprint-05-customer-master-v2.md` |
| 06 | Products V2 | `atlas-v2/sprint-06-products-v2` | Sprint 05 merged | `atlas-v2/sprint-06-products-v2.md` |
| 07 | PZ V2 | `atlas-v2/sprint-07-pz-v2` | Sprint 06 merged | `atlas-v2/sprint-07-pz-v2.md` |
| 08 | Warehouse V2 | `atlas-v2/sprint-08-warehouse-v2` | Sprint 07 merged | `atlas-v2/sprint-08-warehouse-v2.md` |
| 09 | Inventory V2 | `atlas-v2/sprint-09-inventory-v2` | Sprint 08 merged | `atlas-v2/sprint-09-inventory-v2.md` |
| 10 | Batch V2 | `atlas-v2/sprint-10-batch-v2` | Sprint 09 merged | `atlas-v2/sprint-10-batch-v2.md` |
| 11 | Admin V2 | `atlas-v2/sprint-11-admin-v2` | Sprint 10 merged | `atlas-v2/sprint-11-admin-v2.md` |
| 12 | Auth V2 | `atlas-v2/sprint-12-auth-v2` | Sprint 11 merged | `atlas-v2/sprint-12-auth-v2.md` |
| 14 | Accounting Hub V2 | `atlas-v2/sprint-14-accounting-hub-v2` | Sprint 02 merged | `atlas-v2/sprint-14-accounting-hub-v2.md` |
| 15 | Ledgers V2 | `atlas-v2/sprint-15-ledgers-v2` | Sprint 14 merged | `atlas-v2/sprint-15-ledgers-v2.md` |
| 16 | Carriers V2 | `atlas-v2/sprint-16-carriers-v2` | Sprint 02 merged | `atlas-v2/sprint-16-carriers-v2.md` |
| 17 | Shipping Ops V2 | `atlas-v2/sprint-17-shipping-ops-v2` | Sprint 16 merged | `atlas-v2/sprint-17-shipping-ops-v2.md` |
| 18 | Global Search V2 | `atlas-v2/sprint-18-global-search-v2` | Sprints 02/03/04/05 merged | `atlas-v2/sprint-18-global-search-v2.md` |
| 19 | Dashboard Kanban V2 | `atlas-v2/sprint-19-dashboard-kanban-v2` | Sprints 02 + 03 merged | `atlas-v2/sprint-19-dashboard-kanban-v2.md` |
| 20 | Ops Cell V2 | `atlas-v2/sprint-20-ops-cell-v2` | Sprints 08 + 11 merged | `atlas-v2/sprint-20-ops-cell-v2.md` |
| 21 | Client KYC + Consignment V2 | `atlas-v2/sprint-21-client-kyc-consignment-v2` | Sprints 05 + 09 merged | `atlas-v2/sprint-21-client-kyc-consignment-v2.md` |
| 22 | API Status V2 | `atlas-v2/sprint-22-api-status-v2` | Sprints 11 + 16 merged | `atlas-v2/sprint-22-api-status-v2.md` |
| 13 | Dashboard V2 (aggregator) | `atlas-v2/sprint-13-dashboard-v2` | ALL domain sprints merged | `atlas-v2/sprint-13-dashboard-v2.md` |
| 23 | Documents Suite V2 (final) | `atlas-v2/sprint-23-docs-suite-v2` | Sprints 01/04/14/15 merged | `atlas-v2/sprint-23-docs-suite-v2.md` |

**Ordering note:** Sprint 13 (Dashboard V2) is the aggregator — it depends on all
domain pages being stable, so it executes near the end. Sprints 14–22 can run in
parallel-eligible windows once their named dependencies merge, but GATE 2 still
limits to ≤ 3 simultaneously open PRs. Sprint 23 is the final closing sprint.

---

## 10. How to Fire a Sprint

1. **Verify anti-drift gates** — all 6 gates in §1 are green
2. **Open a fresh Claude Code session** — NOT any session that has previous sprint context
3. **Paste the sprint prompt** from the relevant `atlas-v2/sprint-NN-<name>.md` file
4. **Let it run** — the session handles agents, tests, PR, and ends with `/deploy`
5. **Review the PR** on GitHub — check file diff, description, test results
6. **Merge the PR** — operator merges manually after review
7. **Execute `/deploy`** on Windows — the sprint file specifies the exact deploy steps
8. **Verify in browser** at `https://pz.estrellajewels.eu/dashboard/<page>-v2.html`
9. **Fire next sprint** — only after current sprint PR is merged and deployed

---

## 11. CLAUDE.md Discoverability Entry

After this PR merges, the following line should be added to `CLAUDE.md` under **Operating rules**:

```
8. Atlas-V2 campaign: `.claude/campaigns/atlas-v2.md` — 13-sprint frontend migration.
   Sprint prompts: `.claude/campaigns/atlas-v2/sprint-NN-*.md`. Fire one at a time in fresh sessions.
   Prerequisite: PR #262 merged. Next sprint: 01.
```

---

## 12. What This Campaign Does NOT Do

- Does not start any sprint (sprints fire one at a time, by operator, in fresh sessions)
- Does not touch `shipment-detail.html` or `dashboard.html` beyond critical fixes
- Does not enable new wFirma write flags
- Does not change financial calculation logic (freight, duty, VAT, landed cost)
- Does not create new PZ documents
- Does not modify existing backend routes (may add new read-only endpoints where unavoidable)
- Does not bypass the 7-agent deploy gate
- Does not create a V2 dashboard before all domain pages are stable
