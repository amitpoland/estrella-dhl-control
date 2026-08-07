# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

Root regression (before every live batch): `make verify` — fast unit tests + format checks (~2s). Before PRs: `make verify-full` — unit + golden PDF pipeline (~30s). Regenerate golden: `make reference` (only when intentionally changing golden constants). Install pre-commit hook that blocks on test failure: `make install-hooks`.

Service dev: `cd service && make install` (pip install requirements) / `make dev` (uvicorn app.main:app --reload --port 8000) / `make verify` (PZ regression inside service/).

Individual tests: `pytest test_pz_regression.py -k "<test_name>" -v` (root); `cd service && pytest tests/test_routes_pz.py -v` (FastAPI suite, 748 files); `cd service && pytest tests/ -m smoke -v` (fast smoke subset).

Root-level CLI: `python pz_import_processor.py --invoices <invoice.xlsx> --zc429 <zc429.pdf> --rate <r> --pdf --xlsx --doc-no <PZ/NNN/YYYY>`.

Full command surface: see the Makefile at repo root and `service/Makefile`.

---

## Architecture

### Repo layout

- `service/app/` — FastAPI backend (production service, port 47213). Entry `main.py` (imports 50+ route modules); `api/` (~70 `routes_*.py`); `services/` (~214 service modules — all business logic); `agents/` (decision engines); `core/` (config, audit, guards, circuit breaker, security); `auth/` (JWT + session); `static/` (V1 HTML + Vanilla JS; V2 under `static/v2/*.jsx`).
- `service/tests/` — 748 pytest files.
- Root engine files — `pz_import_processor.py` (standalone CLI + only calculation path), `pz_calculator.py`, `customs_description_engine.py`, `test_pz_regression.py` (90 golden regression tests).
- `reference_batch/` — golden expected outputs. `docs/` — operational markdown (52 files). `.claude/` — agents, campaigns, memory, contracts, skills.

### Key architectural facts

**Calculation authority** — `process_batch()` in `pz_import_processor.py` is the ONLY calculation path for landed cost, freight allocation, duty, and totals. Never recompute in routes, services, or the Cliq layer.

**Databases** — SQLite only, one file per domain. Each `service/app/services/*_db.py` module owns its database. No shared ORM; queries are direct `sqlite3` calls.

**Frontend** — V1 pages (`shipment-detail.html`, `dashboard.html`) are Vanilla HTML + Babel JSX. V2 pages (`static/v2/*.jsx`) are also Babel JSX — no bundler, no TypeScript, no Tailwind. Do NOT apply TypeScript/Tailwind defaults here. Shared primitives live in `static/components.js` and `static/v2/components.jsx`.

**Route registration** — All routes import into `service/app/main.py`. Adding a new route file requires adding its `include_router` call there.

**AI integration** — `service/app/services/ai_gateway.py` wraps the Anthropic Claude API. `service/app/services/ai_bridge.py` handles structured task dispatch. Tests isolate the AI gateway via `conftest.py` fixtures.

**Feature flags** — `service/app/core/config.py` exposes runtime flags (`audit_hardening_enabled`, `compliance_intelligence_resolver_enabled`, `series_bootstrap_enabled`). No `.env` file; configuration is environment-variable driven.

**Deploy layout** — Standard robocopy syncs `service/app → C:\PZ\app`. Root-level engine files (`pz_import_processor.py`, `polish_description_generator.py`) deploy to `C:\PZ\engine\` via a SEPARATE sync command (Lesson J).

---

# Estrella PZ Processor + Zoho Cliq Integration

You are operating as the orchestration layer for Estrella's PZ processing workflow.

---

## Production deployment rule (PERMANENT)

**Every Git-based production deploy requires the full 7-agent gate. No exceptions.**

Full rule: `service/docs/production_deployment_rule.md`  
Slash command: `/deploy`  
Agent files: `.claude/agents/deploy_*.md`

The 7 required agents (run in parallel before any sync):
1. `deploy_lead_coordinator.md` — final go/no-go
2. `deploy_git_diff_reviewer.md` — file classification, forbidden paths
3. `deploy_backend_impact_reviewer.md` — routes, auth, imports
4. `deploy_persistence_storage_reviewer.md` — schema, storage writes
5. `deploy_security_reviewer.md` — credentials, auth removal, injection
6. `deploy_qa_reviewer.md` — test pass/fail (counts: `.claude/contracts/test-baseline.md`)
7. `deploy_release_manager.md` — branch hygiene, rollback command

Production: `C:\PZ` | Service: `PZService` (NSSM, port 47213) | Public: `https://pz.estrellajewels.eu`

---

## Working-tree registry (Windows host layout)

| Path | Role |
|---|---|
| `C:\PZ` | Production — NSSM AppDirectory (`PZService`, port 47213). Never `reset --hard`, never robocopy'd INTO. |
| `C:\PZ-main` | Deploy source — pinned to `main`, ff-only pulls. |
| `C:\PZ-verify` | Verification clone (primary git tree for file-hash checks). |
| `C:\PZ-active` | Current implementation campaign (one at a time). |
| `C:\PZ-archive` | Cold storage, read-only. |

**Commit-scoped reads (Lesson Q rule 7):** before any deploy-gate / PR-review read,
confirm the tree's `HEAD` equals the SHA under review; if not, read `C:\PZ-main` at
that SHA or a clean `git archive` export, and say in the verdict which tree and HEAD
the finding came from. A verdict from the wrong revision is a false verdict.

One Claude session at a time operates against `C:\PZ-verify`; a second session is
read-only or uses its own worktree. Campaign-branch writes are guarded by
`.claude/hooks/campaign-branch-guard.py` (registry: `.campaigns/`); an
`expected_head` mismatch is an operator incident, never auto-corrected.


## EJ Dashboard Phase-C Constitution (Final) — standing Phase-C preamble (operator-ratified 2026-07-03, VERBATIM R4)

> The text below is the operator's exact wording (R4 — not reconstructed, not
> paraphrased). It is the governing preamble for all Phase-C work.

**EJ Dashboard Phase-C Constitution (Final)**

**0. Mission**
Implement only inside the existing EJ Dashboard architecture. The objective is not to create software. The objective is to extend the existing business system without introducing any new authority.

**1. Existing Authorities (Immutable)**
Claude must first identify the authority before writing a single line of code. There are only these authorities.
wFirma → (API / Webhook) → Mirror Layer → EJ Dashboard Masters (Product Master, Customer Master, Warehouse, Invoice, Packing, Inventory) → All business modules
Nothing is allowed to bypass this chain.

**2. Product Authority**
This is now fixed forever.
wFirma Product → Product Mirror (sync only) → Product Master (EJ Dashboard authority) → Inventory, Reservation, Packing, Invoice, Sample, Consignment, Returns
Inventory MUST NEVER read directly from wFirma.

**3. Customer Authority**
wFirma Customer → Customer Mirror → Customer Master → Inventory, Invoice, Packing, Consignment, Returns
Inventory must never call wFirma customer APIs.

**4. Design Number Rule (NEW)**
Product Code remains the immutable system identifier. Design Number becomes the business identifier. Mapping: Product Code → Design Number. Product Master owns this mapping. Only Product Master may edit it. Everything else reads it. No module may maintain another Design Number table.

**5. wFirma Custom Field Rule**
The new custom field created inside wFirma becomes the sync source. Example: Product Code ABC001 → Custom Field Design Number = RG-10025 → Mirror → Product Master → Inventory. Inventory never asks wFirma for Design Number. It always comes through Product Master.

**6. Product Master Structure**
Minimal authority: wFirma ID, Product Code, Design Number, Status, Sync Version, Last Sync, Active. No duplicated business information. No second master.

**7. Customer Master Structure**
Existing Customer Master remains authority. Mirror only synchronizes. No new customer tables. No duplicate cache.

**8. Warehouse Documents**
These stay inside wFirma: PZ, WZ, MM, Warehouse, Invoice. The app mirrors them. The app never becomes the fiscal authority.

**9. Sample Workflow**
Main Warehouse → MM → Sample Warehouse → Customer → Return → MM → Main Warehouse. Every movement produces a document. Inventory stores workflow state. wFirma stores warehouse documents.

**10. Consignment Workflow**
Main Warehouse → MM → Consignment Warehouse → Customer. Monthly: Customer reports sold items → Select sold pieces → Create Invoice → Invoice creates WZ only from Consignment Warehouse. No second WZ from Main Warehouse. This permanently removes the double-WZ problem.

**11. Product Selection**
Never type IDs. Never paste IDs. Always: Customer → Product → Design Number → Checkbox → Execute. Barcode remains optional. Search remains optional.

**12. Inventory UI**
Inventory UI is exactly the supplied wireframe. Never redesign. Never simplify. Never invent. Wireframe is the UI authority.

**13. Existing Pages Rule**
No new pages. Never. If functionality belongs to Inventory, extend Inventory. Do not create Inventory2, MoveStockPage2, SamplePage2, ProductPage2. Everything extends the existing authority page.

**14. Existing Backend Rule**
No duplicate services. No duplicate APIs. No duplicate routes. No duplicate mirrors. Extend existing services.

**15. Authority Violation**
Immediately STOP if code does this: Inventory → wFirma API. Correct path: Inventory → Product Master → Mirror → wFirma.

**16. Implementation Order (Locked)**
1. Product Master Authority → 2. Customer Master Authority → 3. Reservation → 4. Inventory → 5. Sample → 6. Consignment → 7. Returns → 8. Invoice Selection → 9. MM Integration → 10. Webhook Synchronization. Nothing may skip this order.

**17. Scope Rules**
Every slice must declare: Authority owner, Existing page, Existing API, Existing DB, Existing service. If any of these cannot be identified, STOP.

**18. No Creativity Rule**
Claude must not invent architecture, invent workflow, invent fields, invent tables, invent pages, invent APIs. If information is missing, STOP.

**19. Research Rule**
If work involves wFirma, Claude must search wFirma API documentation, webhook documentation, existing repository, existing mirror — before proposing code. Never guess a wFirma capability.

**20. Final Rule**
Before writing code Claude must prove: This feature extends EXISTING AUTHORITY → EXISTING PAGE → EXISTING SERVICE → EXISTING DATABASE → EXISTING API. If any arrow cannot be proven, STOP and ask.

**Application Authority Rule**
The EJ Dashboard application is the operational authority. wFirma is an external ERP. Claude must always start by identifying which existing EJ Dashboard module owns the business process. The implementation must extend that module. It must never start from wFirma and build inward. It must start from the existing EJ Dashboard authority and extend outward to wFirma only through the approved sync layer.

**Advisor reconciliation (NOT operator text — advisor notes, recorded 574a6932):**
(a) §6 = the LOGICAL view of the product authority; the physical layering stays as built (Mirror = the six sync fields only; Master = business fields incl. status / is_active). Reversible on operator word. (b) §16 mapping to execution: step 1 (Product) = C-1a..C-1d; step 2 (Customer) = C-2; steps 3–10 renumber the old queue (MM = step 9, Webhook Sync = step 10). (c) §4/§5 Design Number custom-field sync = NEW scope, gated on OPERATOR-INPUT (field created in wFirma + its API name + whether the goods API returns custom fields — wFirma email item #3, after MM (#1) and contractor_id (#2)); §19 research rule applies.

---

## APPLICATION AUTHORITY RULE (permanent, operator-ratified 2026-07-03)

There is only ONE application: **EJ Dashboard**. Every module belongs to EJ
Dashboard. "PZ App" is NOT an application. "PZ" is only one workflow/module
inside EJ Dashboard. Claude Code must never create architecture that treats
PZ, Inventory, Sample, Consignment or Returns as separate applications.
Everything extends the existing EJ Dashboard authority.

**Companion rule (start every feature with this question):** *"मैं EJ
Dashboard के किस existing module को extend कर रहा हूँ?"* ("Which existing EJ
Dashboard module am I extending?") — no answer = **STOP**. No new page, no new
authority, no new master, no direct wFirma mapping. Every module reaches wFirma
only through: `<module> → EJ Dashboard <Master> → Mirror → wFirma`. A module
that calls wFirma product/customer APIs directly, or grows its own
customer/product table, is an **AUTHORITY VIOLATION**.

**Scope note (this rule is architectural, not a rename mandate):** it governs
architecture decisions and documents going forward. It does NOT authorize
renaming files, paths, services, or tables containing "PZ" — any such rename
is a separate operator-approved slice. The violation cleanup list lives in
`reports/inspection/2026-07-03T-integration-architecture-audit.md` (amendment).

**MASTER-FIRST RULE (permanent, operator-ratified 2026-07-03):** कोई भी नया
module या API बनाने से पहले Claude Code यह सिद्ध करेगा कि वह किस existing EJ
Dashboard Master को consume कर रहा है। यदि Product या Customer की जानकारी
चाहिए, तो केवल EJ Dashboard **Product Master** या **Customer Master** से
मिलेगी। Inventory, Sample, Returns, Consignment, Invoice, Packing, PZ और WZ
में **direct wFirma queries निषिद्ध हैं।** यदि किसी feature के लिए existing
Master पर्याप्त नहीं है, तो **STOP** करके Master Authority बढ़ाई जाएगी।
Feature उस Master को bypass करके नहीं बनेगा। (In short: prove which Master you
consume before building; Product/Customer facts come only from the Product
Master / Customer Master; direct wFirma queries from any module are
forbidden; if the Master is insufficient, STOP and extend the Master — never
bypass it.)

**MASTER CONSUMPTION RULE (permanent, operator-ratified 2026-07-03):** "Every
business module must consume Masters. No business module may consume Mirrors.
No business module may consume wFirma. Mirrors exist only for synchronization.
Masters exist only for business logic." **LAYER RESPONSIBILITIES:** a **Mirror**
holds ONLY `wfirma_id, product_code, sync_version, last_sync, hash,
deleted_flag` — nothing else, never business logic. A **Master** holds design
number, product code, category, status, active, business mapping. **Inventory
NEVER reads the Mirror — only the Master.** Enforced by the standing pin
`service/tests/test_master_consumption_rule.py` (mirror schema = exactly the six
columns; no business module reads wFirma/mirror for product data — the known
violation list shrinks per C-1 sub-slice and must reach zero by C-1d; new
violations fail immediately).

---

## OPERATING MODEL — governance reset (operator-ratified 2026-08-07)

This section REPLACES the former GATES 1-6 ratchet. The reset removed ceremony, not
safety: every incident-derived control that protects production bytes survives; every
control that merely sequenced paperwork is gone. Historical references resolve as
follows: "GATE 1" -> the one seven-agent gate below; "GATE 2" -> retired (open-PR
count is never a deploy blocker); "GATE 3" -> retired; "GATE 4" -> findings go to the
issue backlog (see the gate rules below); "GATE 5" -> the substitution-disclosure line
below; "GATE 6" -> browser verification for UI changes (unchanged in substance,
listed under mode 1).

### Two permanent rules (operator's words, verbatim)

> Production runtime fix that has passed one seven-agent gate must proceed directly
> to merge and deploy. Unrelated test, documentation, governance, queue, memory, or
> inherited-CI work must not delay deployment.

> Do not create a new governance PR while a validated production fix is waiting to
> deploy, unless the new finding proves that deployment itself is unsafe.

### Three operating modes — there are no others

**1. Normal bug / feature (runtime change):**
fix -> targeted tests -> **seven-agent gate, once** -> merge -> deploy -> smoke test
-> done. UI changes additionally get browser verification (flow, console, network,
full click->API->DB->UI chain) before the gate. The gate reviews one frozen head; a
subsequent **test-only or docs-only commit does not invalidate the verdict** and does
not restart the gate — the gate binds to the production bytes it reviewed, not to the
commit SHA.

**2. Test-only / docs-only:**
fix -> targeted tests -> merge. **No seven-agent gate. No deploy.** (On the
production host these merges surface as the runtime no-op.)

**3. Sensitive change** — extended review applies ONLY to: destructive DB migration,
accounting writes, inventory mutation, customs submission, auth/security authority
change. Everything else is mode 1 or 2.

### The seven-agent gate (the one gate)

Runs ONCE per runtime change, on a frozen head, all seven `deploy_*` agents. The
reviewers' job is to **classify risk, not to stop deploys**:

- Only a **HIGH/CRITICAL executable defect** blocks the current task.
- LOW/MEDIUM findings are recorded as **backlog issues** — never a fix-batch, never
  a re-run of the gate, never a new PR in the same campaign.
- Same production bytes are never re-gated. A re-run happens only when the runtime
  content under review actually changed.
- A named subagent that cannot be dispatched is disclosed and substituted openly,
  never silently.

### What is never a deploy blocker

Inherited CI red (the aggregate carries a tracked red set; only the metered floors in
`.claude/contracts/test-baseline.md` gate) - open-PR count - docs/test PRs -
observer, scorecard, or memory updates - reviewer LOW/MEDIUM findings - queue
arithmetic or historical sequential deploy ordering. **When a fix is
production-ready, deploying it is priority #1; cleanup comes after.**

### The full reset instruction (operator's words, verbatim, 2026-08-07)

The two permanent rules above are excerpts of this ruling. The complete instruction is
recorded here verbatim and is the normative source for the CI-authority and
runtime-payload subsections below.

> RESET OPERATING MODEL.
>
> Production delivery authority is:
>
> Fix → targeted tests → ONE seven-agent gate → merge → deploy → smoke test → close.
>
> GitHub Actions CI is diagnostic only and MUST NOT gate production. Never wait for
> aggregate-green when main carries inherited failures. Do not classify historical CI
> failures unless a changed file is implicated.
>
> After seven-agent GO, production deployment becomes Priority 1. No test-only PR, docs
> PR, GATE-4 task, observer, scorecard, memory update, queue arithmetic, CI run, or
> unrelated finding may delay it.
>
> Only a new HIGH/CRITICAL executable defect in the pending runtime change may stop
> deployment.
>
> LOW/MEDIUM findings go to backlog and are not implemented during the active release.
>
> Test-only changes do not invalidate a prior production-code gate when production bytes
> are unchanged.
>
> Seven-agent review runs once per runtime payload, not once per subsequent bookkeeping
> commit.
>
> After deployment and smoke verification, resume backlog work.

### CI authority — diagnostic, never a gate

CI's positive purpose: detect regressions introduced by a changed file, detect
platform-specific (Windows / py3.9) failures, and provide evidence for later cleanup.
It never authorizes and never blocks a merge or a deployment. The only CI question ever
asked of a PR is: *"did this PR introduce a NEW failure?"* If no, proceed; for
test-only and docs-only PRs, CI is ignored for production purposes. Node-ID
set-difference classification remains a **test-PR merge tool** only — never deployment
ceremony.

**No repository configuration may elevate CI.** Branch protection, required status
checks, merge queues, auto-merge, or any future platform mechanism may not give CI
merge or deployment authority without an explicit operator governance decision recorded
in PROJECT_STATE.md DECISIONS. The check-name note inside `.github/workflows/ci.yml`
(naming `Service pytest (aggregate)`) is a hypothetical technical fact, not an intent.

### Runtime payload — what a gate verdict binds to

*Runtime payload* = every file copied to production by the governed deployment
procedure: the `service/app` tree plus the governed engine files enumerated by the
deploy config (`engine_files` in `.claude/deploy/windows_prod_v2.json`; 16 entries at
ratification). Documentation, tests, CI workflows, GitHub metadata, review notes, and
memory/state files are explicitly excluded. **A previous seven-agent GO remains valid
only when a byte-for-byte comparison between the previously approved runtime payload
and the pending runtime payload is empty.** Any non-empty payload diff requires a fresh
round; an empty diff means the prior GO stands. (Precedent: the PR #1100 gate —
"payload diff vs gated head verified EMPTY".)

Between a seven-agent GO and completed smoke verification, the release track permits
exactly: the deployment itself, smoke verification, rollback, and rollback preparation
— rollback work never violates the deploy-first rules. Deferred obligations (observer,
scorecards, backlog dispositions, memory/state updates) fire immediately after
successful smoke verification or rollback completion.

### Safety kept in full (the non-negotiables)

Seven-agent review (once) - forbidden-path check - production backup - rollback -
production identity proof - app + engine sync (Lesson J) - service stop/start health
verification. One deployment authority: `Deploy-PZ.ps1` behind one gate. Financial,
customs, inventory and accounting writes remain hard-gated and operator-approved.


### Engineering OS (canonical version pointer)

The repository-canonical execution framework is **EJ Engineering OS v1.4** at
`.engineering-os/` (docs-only; version delta + evidence in
`.engineering-os/VERSION_HISTORY.md`; v1.4 adds `00 §11` Evidence Contract, `00 §12`
MODULAR-MINIMAL + Anti-Bloat gate, `00 §13` Bounded Engineering Loop (governance over Claude
Code's native `/loop` + `/goal` — no project loop command), and `00 §14` OS-load arming +
output hygiene). It is **subordinate** to this file's OPERATING MODEL, the
Engineering Lessons, the 7-agent deploy gate, and operator approval. The single authoritative
definition of feature completeness remains this file's **Business Feature Completeness
Standard** (seven requirements) — the OS points to it and never redefines it.

---

## OBSERVATION LAYER (post-merge, never a release condition)

Read `.claude/memory/PROJECT_STATE.md` at session start when present — it is the
source of truth for current project state; do not re-derive state from lossy chat
history. After a merge to main, `agent-performance-observer` (scorecard) and
`flow-context-keeper` (state update) run **in the background**. They are memory and
telemetry, NOT gates: **no deploy, merge, or task waits on an observer, scorecard, or
memory update.** Scorecards live in `.claude/memory/scorecards/` and are cited by
path. `/observe` and `/update-state` invoke them manually.


## AUTONOMY AND STOPPING

Continuing autonomous work is the default; stopping is the exception. A session may
stop and hand back to the operator ONLY on one of four HOLD conditions, named
explicitly when stopping:

1. **Destructive production action** — the next step would delete, overwrite, or
   irreversibly mutate production data, a live service, or a booked external record
   (wFirma posted PZ, sent email, production robocopy/reset, DB drop). Confirm first.
2. **Missing credentials / access** the session cannot safely obtain.
3. **Legal / financial approval** (value corrections, customs declarations, money).
4. **Unclear business decision** where a wrong guess has real cost — a merely
   technical ambiguity with a sensible default is NOT this; pick the default and note it.

Code inspection, tests, local verification, docs/state updates, non-destructive
refactors, and opening a PR are never HOLD reasons. Record a one-line HOLD reason in
`.claude/memory/TASK_STATE.md` when stopping (lifecycle states:
`.claude/TASK_EXECUTION_PROTOCOL.md`). **A production-ready fix deploys before any
cleanup, backlog, or governance work begins** — see the two permanent rules above.

**Resumable stops:** a stop on an external dependency that preserves a verified
checkpoint is `EXECUTION_BLOCKED` — **resumable, not restartable**: on return,
validate the checkpoint (branch / HEAD / diff) and execute the single recorded resume
command; do not re-plan or re-implement work that is still valid. Full rule:
`docs/governance/anti-hold-and-completion.md` §7.


## Business Feature Completeness Standard (permanent)

A business capability cannot be marked **Production Complete** until all seven requirements
are satisfied and signed off by the named Business Owner. This governs every module:
Customer Master, Accounting, Product Master, DHL, Inventory, KSeF, Reports, AI.

```
Scheduler / Webhook
        │
        ▼
run_<capability>()        ← the ONE shared function (Shared Service)
        ▲
        │
POST /api/v1/.../action   ← Business API (FastAPI endpoint)
        ▲
        │
[ Run Now ] button        ← Business UI (operator-facing)
```

The scheduler, the API endpoint, and the UI button all call the **same**
`run_<capability>()` function. Diverging into "Logic A" and "Logic B" is forbidden.

### The seven requirements

| # | Requirement | Mandatory |
|---|---|---|
| 1 | **Automation** | Scheduler or webhook triggers `run_<capability>()` automatically |
| 2 | **Shared Service** | One `run_<capability>()` function reused by scheduler, API, and UI button |
| 3 | **Business API** | `POST /api/v1/.../action` + `GET .../status` |
| 4 | **Business UI** | Operator button + status panel — no developer intervention needed |
| 5 | **Observability** | Last run / processed / created / updated / skipped / errors visible |
| 6 | **Browser Verification** | End-to-end test in a real browser with real production data |
| 7 | **Business Verification** | Named Business Owner confirms workflow is usable without developer help |

Requirements 1–5 are implementation requirements. Requirements 6–7 are acceptance gates.
Exception to any requirement requires an explicit ADR in `docs/decisions/`.
"Not built yet" is not an exception — it is an incomplete feature.

### Feature lifecycle (seven stages)

A feature moves through these stages in order. No stage may be skipped.

```
Design
    ↓
Implementation          ← code written, tests passing, PR open
    ↓
Technical Complete      ← requirements 1–5 satisfied; PR merged to main
    ↓
Deployed                ← running in production; endpoints respond; scheduler fires
    ↓
Browser Verified        ← requirement 6 satisfied; happy path + idempotency confirmed
    ↓
Business Verified       ← requirement 7 satisfied; Business Owner sign-off recorded
    ↓
Production Complete     ← all seven requirements satisfied; feature is closed
```

A feature can be Technical Complete but not yet Deployed (still in PR).
A feature can be Deployed but not yet Browser Verified (not yet validated).
These are distinct states — the lifecycle makes that unambiguous.

**"Scheduler written" = Technical Complete at best. "Tests pass" = Implementation.
Neither is "done."**

### Business Owner registry

The Business Owner signs off on requirement 7. Without a named owner, Business
Verification cannot happen.

| Module | Business Owner |
|---|---|
| Customer Master | Operations |
| Accounting | Finance |
| DHL Shipping | Shipping |
| Inventory | Warehouse |
| Product Master | Product Team |
| KSeF | Finance / Compliance |
| Reports | Operations + Finance |
| AI | Operations |

When a feature reaches Business Verified, record: date, Business Owner name, and conditions.

### The four questions every sync screen must answer

When an operator opens a screen, all four must be immediately visible:

1. **What is the current state?** (running / healthy / error)
2. **When did it last run?** (`last_completed_at`)
3. **What happened?** (processed / created / updated / skipped / errors)
4. **Can I run it now?** (Run Now button, always enabled)

### Canonical status API response shape

`GET /api/v1/.../status` returns JSON with fields: `healthy` (bool), `running` (bool — derived from `last_started_at > last_completed_at`), `last_started_at` (ISO 8601), `last_completed_at` (ISO 8601), `duration_ms` (int), `processed` (total seen), `created` (new inserts), `updated` (COALESCE fills), `skipped` (rejected: bad country/name/etc.), `errors` (exception count), `last_error` (string or null). Full contract + example: `docs/patterns/status-endpoint.md`.

### Canonical UI layout (Client Master as reference)

Toolbar row: `+ New Client   ↻ Sync from wFirma   ⇅ Full Contractor Scan`. Status panel below: last automatic scan (timestamp + health icon), last manual scan, contractors imported / updated / skipped / errors counts, `[View Log]` link. Full mockup + spec: `docs/patterns/status-endpoint.md`.

### Current feature lifecycle status

Per-feature lifecycle stage: see PROJECT_STATE.md FACTS.

### Enforcement

`reviewer-challenge` and `frontend-flow-reviewer` must flag any PR claiming "feature
complete" or "Production Complete" that has not passed all seven requirements. A
scheduler-only implementation is at most Technical Complete — never Production Complete.

---

## FRONTEND AUTHORITY CONSTITUTION (V2 = consolidation authority)

V2 is the current frontend authority for all consolidation and new development.
This is the consolidation authority, NOT a commitment to V2 as the permanent
architecture. A future rebuild is a separate, separately-approved decision and
does not weaken these rules while V2 is the authority.

PROHIBITIONS (hard — no exception without a formal PROJECT_STATE.md DECISIONS entry):
- No duplicate page for a module that already has a canonical page.
- No new standalone HTML page (login / auth / static shell excepted).
- No new parallel React app.
- No feature work in legacy / frozen pages.
- No "temporary" second implementation.

ONE-AUTHORITY REQUIREMENT — every business module has exactly:
- one canonical URL
- one canonical React file/folder
- one API wrapper path
- one backend authority

PRE-DEVELOPMENT CHECK (run before ANY frontend work; all five must pass):
1. Identify the module.
2. Identify the canonical URL.
3. Identify the canonical frontend file/folder.
4. Identify the backend authority.
5. Prove no duplicate page is being created.

STOP CONDITION: if canonical authority is unclear, STOP and ask the operator.
Do not develop in both places. Do not pick a canonical silently.

Binds: GATE 1, frontend-flow-reviewer, Lesson F, Lesson M.

---

## Engineering Lessons (permanent)

Append-only — do not delete prior lessons; supersede with a new dated entry.
Cross-reference: `memory-lessons` agent; `engineering_discipline_rules` auto-memory.
Full origin narratives, detection signals, and worked examples: invoke `engineering-lessons`.

**Letters are unique identifiers, and this file shares one letter space with
`.claude/memory/engineering_lessons.md`.** Before adding a lesson, grep **both** files for the
next free letter — a letter that labels two different lessons makes every downstream reference
("per Lesson X") ambiguous, and the ambiguity is invisible until someone reads the wrong entry.
On a collision, the *later-published* entry is relettered to the next free letter; its content,
its date, and its position in the file are preserved, and it carries a **letter note** naming its
former letter so historical references still resolve. Never renumber a lesson to close a gap, and
never reuse a retired letter.

**Enforcement surfaces**: Lesson A binds at GATE 1 (PR open
discipline — real-builder regression test is a precondition;
integration-boundary owns the verdict, testing-verification
adds the test, backend-safety-reviewer flags missing
`_normalise_X` boundary helpers). Lesson B binds at GATE 5
(substitution disclosure — meta-agent substitution forbidden) and
at the orchestrator's first-task-of-session diagnostic. A Lesson-A
failure detected AFTER merge is a GATE 4 salvage finding requiring
SCHEDULED / ISSUE / REJECTED disposition. **Lesson G binds at every
generated-artifact PR and every download-endpoint PR** —
backend-safety-reviewer must flag any `FileResponse` /
`StreamingResponse` for a regenerable file that does not explicitly
set `Cache-Control: no-store`, and any generator that updates audit
pointers without an intermediate forbidden-token validation step.
**Lesson M binds at every V2 page PR and every PR that removes,
hides, collapses, replaces, or relocates any operator-visible
capability** (buttons, menu items, tabs, panels, sections, workflow
actions, roadmap placeholders) — reviewer-challenge and
frontend-flow-reviewer must flag any capability suppression that
lacks a formal cancellation recorded in PROJECT_STATE.md DECISIONS.
Suppression without cancellation documentation is incomplete by
Lesson M. **Lesson Q binds at every state-file write that asserts a
safety property** — `reviewer-challenge` must flag any claim that a
gate blocks / a guard fires / an operation is safe-by-design when the
claim names no implementing function, and must treat an *optimistic*
uncited claim (one that permits proceeding) as the higher-severity
case. **Lesson Q rule 7 additionally binds every commit-scoped
reviewer verdict** — a reviewer that reports what a SHA contains must
name the tree and HEAD it read, and the deploy gate must reject a
verdict read from a tree whose HEAD is not the reviewed SHA.

### Lesson A — Test stubs must match real production return shapes (2026-05-13)
**GATE 1.** Stubs MUST match the real builder return shape; stub authors must read the real function first. Every coordinator/builder PR MUST include a real-builder regression test (no stub) asserting the type contract. Coordinators MUST normalise polymorphic inputs via `_normalise_X`. Post-merge Lesson-A failure → **GATE 4** salvage (SCHEDULED / ISSUE / REJECTED).

### Lesson B — Mid-session git pull does NOT reliably refresh the subagent_type registry (2026-05-13)
**GATE 5.** New agent files added mid-session are NOT guaranteed invocable; treat as "available next session." Post-merge validation for agent-adding PRs MUST report VALIDATION-FAILED if the new agent cannot be dispatched. Silent meta-agent substitution is FORBIDDEN; escalate instead. Restart session after any agent-adding merge.

### Lesson C — Observer scorecard writes must be orchestrator-verified post-write (2026-05-13)
**RULES 2 + 6.** Orchestrator MUST verify the scorecard file exists on disk after the observer agent returns — not just self-reported. Missing file → dispatch FAILED; re-fire or escalate. `flow-context-keeper` MUST validate every cited scorecard exists before the run completes; citing an absent file is a RULE 6 violation.

### Lesson D — LOCAL-COMMIT-ONLY deploys must be disclosed and reconciled (2026-05-13)
**7-AGENT GATE.** Any LOCAL-COMMIT-ONLY deploy MUST include a disclosure header (SHA, "GitHub PR: NONE", bypass reason, reconciliation plan) before sync commands, visible to operator before any sync. Operator MUST acknowledge. Reconciliation PR MUST be filed before the next `git pull --ff-only origin main`. Every such deploy appends to `.claude/memory/local-commit-deploys.jsonl`.

### Lesson E — Background email automation requires five mandatory safety properties (2026-05-18)
**GATE 1 + every email-capable background process.** Five mandatory properties: (1) execution-time validation, (2) idempotency (AWB+type+date window), (3) terminal-state suppression, (4) replay safety (durable sent-state before return), (5) environment isolation (`ENV=production` guard required). Full detail: invoke `/engineering-lessons`.

### Lesson J — Root-level engine files are outside the standard `service/app` robocopy (2026-05-22)
**7-AGENT GATE.** `pz_import_processor.py` and `polish_description_generator.py` deploy to `C:\PZ\engine\` via a SEPARATE robocopy — NOT covered by standard `service/app → C:\PZ\app` sync. PR body must declare the additional sync command. Verify via `Select-String` (not Python-import). Full detail: invoke `/engineering-lessons`.

### Lesson I — Production incidents must become workflow-class rules, never shipment-specific patches (2026-05-22)
**GATE 1 + reviewer-challenge.** Six-step framework: (1) classify → (2) name authority owner → (3) cardinal question → (4) convert to platform behavior → (5) verify broader impact → (6) closure (root cause + workflow class + regression tests + unaffected workflows confirmed). Complete before coding: *"This is a [bucket] incident. The fix target is [component]. The workflow class is [description]."* Full detail: invoke `/engineering-lessons`.

### Lesson F — V2 frontend migration requires frozen V1 and strict authority isolation (2026-05-20)
**GATE 1 + V1-FREEZE.** V1 frozen (critical fixes only). ONE PAGE = ONE DOMAIN AUTHORITY. Layer rules: `pz-api.js` = transport only; `pz-state.js` = normalize/cache (FORBIDDEN: decide workflow legality, redefine accounting readiness); `pz-components.js` = stateless rendering; `dashboard-shared.js` = visual atoms only (zero domain knowledge). Dashboard-v2 built last. Danger phrases: "temporarily" / "reuse this renderer" / "copy this state logic". Full detail: invoke `/engineering-lessons`.

### Lesson G — Generated-artifact stale-display bugs are first a cache / atomicity problem, not a generator problem (2026-05-21)
**GATE 1 + every download endpoint.** Diagnostic order: inspect disk file first → walk reference layers → HTTP headers → browser cache. Download endpoints MUST set `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` + `Pragma: no-cache` + `Expires: 0`. Overwrite-safe generation: write → validate → on fail unlink + 422 + NO audit pointer update → on success atomically replace → update audit pointers LAST. Full detail: invoke `/engineering-lessons`.

### Lesson K — Agent prompt templates with broad tool grants must include explicit negative-scope language (2026-05-23)
**GATE 5.** Every prompt dispatched with write-capable tool grants (Bash, Write, Edit, gh, sc.exe, robocopy, MCP write tools) MUST name forbidden commands explicitly: `"DO NOT call <X>, <Y> — read and report only."` Generic phrasing ("verdict only", "just review") is INSUFFICIENT. Grant-set parity required. Full detail: invoke `/engineering-lessons`.

### Lesson M — Planned operator-visible capability must not be removed, hidden, collapsed, replaced, or silently relocated (2026-06-07)
**GATE 1 + reviewer-challenge + frontend-flow-reviewer.** Five-state UI truth model: `available` / `unavailable` / `planned` / `backend-pending` / `deprecated`. Removal only when formal cancellation is recorded in PROJECT_STATE.md DECISIONS (date + reason + capability named). Capability suppression without cancellation record = incomplete PR. Full detail: invoke `/engineering-lessons`.

### Lesson N — Advisory-class readiness signals must never block fiscal actions; only true fiscal risk blocks Approve / Post / Convert / Reservation (2026-06-23)

**GATE 1 + reviewer-challenge + readiness-closure.** Origin: operator governance directive asserted 2026-06-23 during the AWB 9158478722 post-PZ reconciliation. The platform had been treating soft, non-fiscal signals (sales linkage, scan state, warehouse confirmation, placeholder-design source rows) as hard gates — blocking legitimate fiscal actions when no money, tax, or duplicate-document risk existed. This lesson codifies the governing principle behind the AWB 9158478722 authority-separation work.

**Binding rule** — readiness signals fall into exactly two classes, and the class determines whether a signal may block a fiscal action (Approve / Post / Convert / Reservation).

**Advisory-only — NEVER block; surface as advisory and let the action proceed:**
- Sales linkage (sales design ↔ wFirma `product_code` mapping)
- Missing warehouse scan
- Missing warehouse confirmation
- PND / placeholder-design (PND = placeholder-design) source rows

These are informational. They MAY be surfaced as advisories so the operator can correct them, but they MUST NOT prevent Approve / Post / Convert / Reservation. There is no fiscal consequence to proceeding while one of these is unresolved.

**True blockers — the ONLY conditions that may block Approve / Post / Convert / Reservation, because each carries real fiscal, tax, or duplication risk:**
1. Customer unmatched or ambiguous
2. Missing price
3. Over-bill — sales allocated qty > PZ / import authority qty per `product_code`
4. VAT / WDT fiscal failure
5. Duplicate document risk
6. Live write-gate disabled
7. `product_code` missing for actual posting
8. Sales allocated qty exceeds PZ / import authority

Anything not on the true-blocker list is advisory. Default-classify a signal as advisory unless it maps to one of the named fiscal / tax / duplication risks above. Adding a new hard gate requires naming which of these fiscal risks it protects against; a gate with no fiscal-risk justification is an advisory wearing a blocker's clothes and must be rejected by reviewer-challenge.

**Where it binds**: every readiness / gating change in `sales-proforma`, `pz-purchase-accounting`, and `readiness-closure` surfaces; every PR that adds, removes, or reclassifies a blocking reason on Approve / Post / Convert / Reservation; every reviewer-challenge on an authority / readiness PR. This aligns with existing code: `service/app/api/routes_proforma.py:1000` already routes the "sales design(s) not mapped to a wFirma product_code" signal to `line_mismatch_advisories` (advisory) rather than `blocking_reasons` when `settings.advisory_gates_enabled` is on — Lesson N makes that the permanent intended default for all advisory-class signals, not a flag-gated exception. A PR that promotes any advisory-class signal to a hard blocker, or demotes any true blocker to advisory, is incomplete by this lesson.

**Reference**: operator governance directive 2026-06-23 (AWB 9158478722 post-PZ reconciliation); `service/app/api/routes_proforma.py:1000` (`advisory_gates_enabled` advisory routing); `.claude/memory/engineering_lessons.md` Lesson N. **Distinct from Lesson R** (2026-06-22, authority separation), which carried the letter `N` until 2026-08-04 — see the letter note on Lesson R below.

### Lesson R — Import, product master, proforma, warehouse receipt, barcode traceability, and sales linkage are SEPARATE authorities (2026-06-22)

> **Letter note (2026-08-04).** This lesson was published as **Lesson N** and carried that letter
> until 2026-08-04, when it was found to collide with the advisory-vs-blocker Lesson N above
> (2026-06-23). Content, date, and position are unchanged; only the letter moved, to the next free
> letter **R**. The advisory lesson keeps `N` because `.claude/memory/engineering_lessons.md` and
> `.engineering-os/07_BUSINESS_OPERABILITY.md` already bind that letter to it.
> **Resolving a historical reference:** "Lesson N" meaning *authority separation* / *six separate
> authorities* / *single-authority rule* / *wrong authority* — including the docstrings in
> `service/tests/**` and the dated records under `reports/**`, which are historical and were left
> as written — means **this** lesson, Lesson R. "Lesson N" meaning *advisory vs blocker* or the
> *true-blocker list* means Lesson N above.

**GATE 1 + reviewer-challenge + frontend-flow-reviewer + backend-safety-reviewer.**
Origin: recurring defect on AWB 9158478722 (batch `SHIPMENT_9158478722_2026-06_924c4e59`,
Draft #38) — 31 "products unmapped", 84 pcs "PURCHASE_TRANSIT / not scanned", sales linkage
"action-needed", "PZ preview blocked". Root cause: purchase-domain **warehouse scan counts**
and sales-domain **SKU linkage** were promoted into hard blockers on product creation,
proforma readiness, and the wFirma reservation gate, conflating six distinct authorities.

**Binding rule — six separate authorities, each owns its own gates:**

| Authority | Source of truth | May hard-block on | Must NOT block on |
|---|---|---|---|
| **PRODUCT** | supplier invoice / import rows | missing product code, duplicate conflict, invalid accounting fields, live-create approval (`WFIRMA_CREATE_PRODUCT_ALLOWED`) | stock, scan, sales packing, PZ status, SAD, proforma |
| **PROFORMA** | customer + product master + pricing | customer unmatched/ambiguous, missing price, design ambiguity, over-bill, WDT EU-VAT, margin-mask | inventory / stock / PZ / scan (advisory only) |
| **IMPORT_PZ** | import invoice/packing + customs evidence + mapped products + confirmed received qty | unmapped products, no SAD/customs evidence, duplicate PZ, price conflict, live-write approval (`WFIRMA_CREATE_PZ_ALLOWED`) | sales packing list, customer allocation, per-piece barcode scan |
| **WAREHOUSE** | operator quantity confirmation by line/batch (`warehouse_receipt` service) | (advisory; quantity-risk only) | mandatory per-piece scan unless `serial_controlled` |
| **SALES** | sales packing / allocation / reservation | final dispatch / sales posting; reservation: customer matched + product mapped + stock dispatched per billed line | product creation, proforma, product adoption, import qty confirmation, import PZ |

**Enforcement:**
1. **Every guard must declare its authority.** Structured blockers carry an `authority`
   field ∈ {PRODUCT, PROFORMA, IMPORT_PZ, WAREHOUSE, SALES}; guard functions name it in the docstring.
2. **A warning may NOT be promoted into a hard blocker** without (a) an explicit business
   rule naming a real accounting / customs / duplicate-write / quantity-risk reason, AND
   (b) a regression test pinning it. Default for missing information is an ADVISORY.
3. **Warehouse receipt = operator quantity confirmation**, not per-piece scan. Scan stays
   optional traceability unless the shipment is `serial_controlled` (read from `audit.json`).
4. Fiscal writes (`WFIRMA_CREATE_PRODUCT/PZ/PROFORMA/INVOICE`) remain hard-gated and
   operator-approved regardless of any advisory demotion.

**Where it binds**: every readiness/blocker producer (`routes_proforma`, `wfirma_reservation`,
`sales_linkage`, `routes_wfirma` product-resolve + pz_preview, `warehouse_receipt`); every PR
that adds or moves a readiness gate. A new guard that blocks across authority boundaries without
a named business rule + test is incomplete by this lesson.

**Reference**: PR `fix/authority-model-separation` (2026-06-22); `service/tests/test_authority_separation.py`; PROJECT_STATE.md DECISIONS section.

### Lesson O — Tightening a route's auth breaks every test that authenticated the old way; migrate the tests in the same PR, never weaken the route (2026-07-22)

**GATE 1 + security-permissions + reviewer-challenge.** When a route's auth dependency is tightened — `require_api_key` → `require_admin` (session/cookie only), or `require_role(...)` added on top of `require_api_key` — every existing test that authenticated via `X-API-Key` starts returning **401 "Not authenticated"**, because `require_admin` / `require_role` both flow through `get_current_user`, which raises 401 with no `pz_session` cookie. This is a **stale-test signal, not a route bug**.

**Binding rules:**
1. **Same-PR test migration.** Any PR that changes a route's auth dependency MUST, in the same PR, migrate every test exercising that route to the new mechanism. Grep the route path across `tests/` before merging — `X-API-Key`-only tests against a now-session-guarded route are incomplete by this lesson.
2. **Diagnose 401 correctly.** A route-test 401 after an auth change is triaged by reading the route's current dependency + its `git log -S`, not by assuming a regression. If the tightening was intentional (destructive deletes, operator-explicit actions), the **test** is stale.
3. **Never downgrade the route to make a test pass.** Fixing a stale-auth test means giving the test an admin session, not relaxing the endpoint. Weakening auth to green a test is a security regression.
4. **Canonical test fix:** override the session dependency, with cleanup so it cannot leak —
   `app.dependency_overrides[require_admin] = lambda: {"role": "admin", ...}` (or `get_current_user` for `require_role` routes), popped in a `finally`. Verify leak-free by interleaving with an auth-denial suite (e.g. `test_hr5_privileged_auth`).

**Where it binds**: every PR that adds/changes a route `dependencies=[...]` auth guard; every route test that sends `X-API-Key`.

**Reference**: PR #1004 `fix/dashboard-auth-tests-stale` (2026-07-22) — `test_dashboard_polish_desc_delete` (route hardened `require_api_key`→`require_admin` since introduction `3046186f`) and `test_dashboard_repair` (dhl-followup routes gained `require_role("admin","logistics")`); +10 tests recovered. Related recurring class: X-API-Key automation vs `require_api_key_privileged` (Issue #502 / `test_hr5_privileged_auth`).

### Lesson P — robocopy `/XO` from a fresh git worktree re-copies the whole tree (mtime, not content); verify the deployed content diff, never trust the "blast radius" (2026-07-23)

**7-AGENT GATE + Step 5 sync.** `robocopy /XO` ("exclude older") decides what to copy by **file timestamp**, not content. A `git worktree add` checkout stamps **every** file's mtime to the moment of checkout, so a deploy run from a *fresh* worktree makes robocopy see the entire `service/app` tree as "newer" and re-copy all of it — even when only 1–2 files differ in content. Origin `C:\PZ-verify` is a *persistent* checkout where only pulled files get fresh mtimes, which is why the standard `/XO` command is incremental there; a throwaway worktree defeats that.

**Binding rules:**
1. **Content, not the copy list, is the deploy truth.** Before declaring a blast radius, diff by hash: `Get-FileHash` (or `diff -rq`) between `C:\PZ\app` and the source `service/app`. State the **content** delta to the gate, and re-verify **content diff == 0** (source-identical) after the sync — do not report robocopy's copied-file count as the blast radius.
2. **A whole-tree re-copy is acceptable only when content-verified.** If the post-sync content diff is 0, production == the deploy SHA and the over-copy is a functional no-op. If it is non-zero and unexplained, STOP — the source diverged from what was reviewed.
3. **Prefer an incremental source, or copy the changed files explicitly.** Deploy from the persistent `C:\PZ-verify` checkout when it is clean and on-SHA; when it is not (and a worktree is used), either scope robocopy to the explicit changed files or accept the whole-tree copy *after* the hash-diff proof.

**Where it binds**: every Step 5 robocopy sync, especially any deploy run from a `C:\PZ-wt\*` worktree instead of `C:\PZ-verify`.

**Reference**: PR #1006 deploy (2026-07-23) — deployed from worktree `C:\PZ-wt\deploy1006` because `C:\PZ-verify` was detached/dirty; `/XO` re-copied the full app tree though only 2 CSV-writer files differed. Caught by the post-sync `Get-FileHash` parity check (content diff = 0 → correct), not by the copy log.

### Lesson Q — A claim about a safety property is worthless without a source citation, and a citation is worthless if it is resolved against the wrong revision (2026-08-01)

**GATE-1 + GATE-4 + every state-file / handoff register + every commit-scoped reviewer verdict.** A resume note recorded in `TASK_STATE.md` asserted that a straight signed deploy against the HYBRID production runtime would be caught: that the post-#1039 `restored_sha` was **content-derived**, would "resolve to no single clean SHA", and that "the backup-provenance stop condition fires by design." Read against the deploy tooling, **both halves were false.** `restored_sha` is **marker-derived** — `New-BackupUnit` takes it from `Read-VersionMarker` — and the production marker was perfectly readable and well-formed, so nothing resolved to "no single clean SHA" and **no stop condition fired.** `Resolve-RestoredSha` refuses on only two conditions (`unit.json` disagreeing with `version.pre.txt`, or both absent); neither applied. The claim was not merely wrong, it was wrong **in the operator's favour**: it described a tripwire where there was none, and so concealed the real hazard — a straight deploy would have **silently** minted a backup unit labelled with the old marker while holding different bytes, surfacing only later as a rollback that restores one commit's files and then stamps a different commit's SHA.

The lesson recurred in its mirror form three days later, which is why rule 7 exists. In the 2026-08-03 deploy gate, `deploy-lead-coordinator` returned a **HARD BLOCKER** stating that `sign_deploy_authorization.py` has no `--from-sha` flag, therefore no valid reconcile authorization could ever be minted, therefore the deploy needed a preceding fix-PR. It had cited the source. The citation was simply resolved against the wrong revision: obeying the then-unqualified subagent reading rule, it read `C:\PZ-verify`, which was parked on a feature branch **21 commits behind `main`** at a pre-amendment commit where the flag genuinely does not exist (0 occurrences). On the reviewed SHA the flag is fully implemented (8 occurrences). A correct-looking citation produced a false blocker.

**Binding rules:**
1. **A safety-property claim in a state file requires a source citation.** Any assertion that a gate blocks, a guard fires, a check refuses, or an operation is "safe by design" must name the **function** (and file) that implements it — e.g. "`Resolve-RestoredSha` refuses when …". A claim with no citation is an **assumption wearing a fact's clothes** and must be written as one.
2. **Cite the function, not just a line number.** Line numbers drift across branches: `Assert-ProductionMatchesRecordedSha` sits at a given line on the feature branch and **does not exist at all** on `main`. A citation that cannot be resolved on the reader's branch is not a citation.
3. **Verify before relying, not before writing.** A recorded safety claim must be re-verified against source at the moment it is about to be *acted on* — a resume, a handoff, a deploy decision — not trusted because a prior session wrote it down. State files are memory, not authority; the code is the authority.
4. **Name where the protection lives.** If the protection exists only on an unmerged branch, the state file must say so. "This is caught" and "this is caught by an open PR that has not merged" are opposite operational facts.
5. **Correct by marking, never by deleting.** When a recorded claim is found wrong, mark it **WITHDRAWN** with the corrected mechanism beside it. Deleting the old claim destroys the audit trail of *why the reasoning changed* — which is the part a future session needs in order to not re-derive the same error.
6. **Wrong-in-your-favour is the severe class.** A pessimistic error (claiming a block that is really permitted) costs a wasted stop. An optimistic error (claiming a tripwire that does not exist) removes a stop the operator believed they had. Treat any safety claim that *permits* proceeding as the higher-scrutiny case: it needs the citation, and it warrants a `reviewer-challenge` second pass before commit.
7. **A citation must be resolved against the revision under review.** A path is not a revision. Before any commit-scoped read (deploy gate, PR review, "what does this SHA contain"), confirm the tree's `HEAD` **is** the SHA under review; if it is not, read `C:\PZ-main` at that SHA or a clean `git archive` export instead. Every such verdict must state **which tree and which HEAD** it was read from — a verdict that cannot name its revision is unverifiable and must be re-run, not weighed. An absence claim ("the flag does not exist", "there is no guard") is the highest-risk form, because a stale tree produces it silently and it reads as decisive; confirm an absence on the reviewed SHA before it may block anything.

**Where it binds**: every `TASK_STATE.md` / `PROJECT_STATE.md` entry asserting a gate, guard, block, or stop condition; every handoff `next_command` or resume note; every `EXECUTION_BLOCKED` checkpoint validation; and — for rule 7 — every one of the 7 `deploy_*` gate agents, every `reviewer-challenge` on a PR diff, and any finding that a symbol, flag, or guard is absent. `reviewer-challenge` must flag an uncited safety claim in any state-file diff; the deploy gate must reject a verdict whose source tree HEAD ≠ the reviewed SHA.

**Reference**: (rules 1–6) 2026-08-01 register refresh (`b5853935`, PR #1061) — caution recorded 2026-07-31, found wrong 2026-08-01 by reading `.claude/deploy/Deploy-PZ.ps1` (`Read-VersionMarker`, `New-BackupUnit`, `Resolve-RestoredSha`) rather than trusting the register; it had sat wrong for one day, over a HYBRID production runtime, while the only real protection (`Assert-ProductionMatchesRecordedSha`) existed solely in the then-unmerged PR #1062. Observer scorecard: `.claude/memory/scorecards/2026-08-01-pr1062-amendment-register-refresh.md`. (rule 7) 2026-08-03 deploy gate — `deploy-lead-coordinator` HB-1 withdrawn after measurement: `C:\PZ-main` @ `4e9301b6` (main) = 8 `--from-sha` occurrences vs `C:\PZ-verify` @ `cf04f472` (`fix/deploy-production-identity-gate`) = 0; `git merge-base --is-ancestor` confirmed behind, not diverged. Fix landed in the same PR as this lesson: the **Subagent reading rule** in the canonical working-tree registry now carries the commit-scoped exception.

---

## Frontend Design Standard

Governed by `.claude/skills/frontend-design.md` and the FRONTEND AUTHORITY CONSTITUTION above. Also see Lesson F. Stack (both V1 and V2): Vanilla HTML + Babel JSX — no bundler, no TypeScript, no Tailwind. Generic frontend-ui agent defaults to TypeScript + Tailwind — those do NOT apply here.

Unique hard rules (verbatim; full detail in skill file):
- Use CSS custom properties (`--bg`, `--text`, `--badge-*`, `--accent`) — never hardcoded hex
- Use shared components from `dashboard-shared.js` (`Btn`, `Badge`, `Card`, `Sel`, `Toast`)
- Every write button must label exactly what it writes; no auto-save
- No fake readiness, no hidden blockers, no duplicate renderers
- Legacy sections in `<details>` — collapsed by default
- Every interactive element needs a `data-testid`

Invoke skill: before any UI implementation, before any `frontend-flow-reviewer` run.

Design intelligence layer: `.claude/skills/ui-ux-pro-max` is a supplemental search tool for accessibility, UX guidelines, layout best practices. Subordinate to `frontend-design.md`. Read `EJ_OVERRIDES.md` inside the skill directory before applying any output — stack defaults (Tailwind, TypeScript) do not apply here.

---

## EJ Dashboard orchestration default (skill routing)

For every coding request in this repository:
1. Start with the project orchestration skill: `ej-dashboard-master`.
2. Let the master classify the task.
3. Load only the minimum required project skills.
4. Never bypass the master unless explicitly requested by the user.

The routing table, conflict resolution, protected-domain gates, and skill lifecycle
(Session Bootstrap → Dynamic Routing → Release) live in
`.claude/skills/ej-dashboard-master/SKILL.md`. The seven-skill EJ Dashboard skill
architecture is **FROZEN** — consult the **Skill Freeze Policy** in
`.claude/skills/SKILL_REGISTRY.md` before proposing any new skill, and never install a
generic third-party skill raw.

---

## Available integration + System architecture + Required workflow

Zoho Cliq MCP connector (all Cliq operations): connector `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`, org `60014108075`, tool `ZohoCliq_Post_message_in_a_channel`, production channel `pz` (ID `O190928000006027001`). Webhook fallback: `CLIQ_WEBHOOK_URL`. "Processing…" acknowledgment via webhook → bot chat; final batch result via Estrella Cliq MCP → `#PZ` channel; dashboard resend via webhook (OAuth fallback) → `#PZ`.

`process_batch()` in the Python engine is the ONLY calculation path — never recalculate landed cost, freight, duty, totals, or notes outside it. All outputs render from the same validated `process_batch()` result object. Cliq is not the calculation engine.

Live batch: **Step A** `make verify` (stop on failure) → **Step B** engine (CLI or `process_batch()`; CLI syntax via `/pz-shipment`) → **Step C** generate PDF + XLSX (both required — either absent = failed, exit non-zero) → **Step D** post summary + files to Cliq (amendment flags explicit, not hidden).

Full architecture, CLI flags, MCP step sequence: invoke `/pz-shipment`.

---

## Financial rules (must never change)

- Freight and insurance: proportional by value within each invoice. Never allocate by piece count.
- Duty: from ZC429 / A00 only, proportional by before-duty value. Never assume a fixed %.
- B00 VAT: reference-only. Not included in landed cost.
- Notes/UWAGI: from the engine only. Never reconstruct independently.

> For dynamic note 4 logic, required UWAGI text, and examples: invoke `pz-shipment`.

---

## Verification rules

Three-state semantics (treat exactly as follows):
- `True` = verified
- `False` = confirmed mismatch → escalate as amendment flag
- `None` = could not verify → may emit `[VERIFY-GAP]` prefix; NOT a mismatch, NOT an amendment flag

Escalate only on confirmed `False`. `None` is not an escalation trigger.

If `--strict-match` enabled: any confirmed mismatch must fail the run.

---

## Required Cliq posting format + WorkDrive automation flow

Three Cliq posting scenarios (success / partial VERIFY-GAP / failure): each includes doc_no, line count, net, gross, duty totals. Failure messages must state "No final files were posted." Partial messages must list all gaps explicitly. Amendment flags must not be hidden. Full format blocks: invoke `pz-shipment`.

WorkDrive architecture: local storage = truth; WorkDrive REST = primary upload; TrueSync = optional mirror only (NEVER a success condition); Cliq = immediate notification layer. Full MCP step sequence: invoke `pz-shipment`.

WorkDrive / Cliq hard one-liners (verbatim):
- **Never search WorkDrive for files** — resource IDs come from the API response
- **Never wait for TrueSync** — it is not a cloud upload path
- **Never block Cliq notification** because WorkDrive failed — always post immediately
- **Never send local file paths or localhost URLs** in Cliq
- If share link creation fails: report explicitly, state "WorkDrive pending retry"

---

## Active Campaigns

### Atlas-V2 — Fresh Frontend Shell
Campaign document: `.claude/campaigns/atlas-v2.md`  
Sprint files: `.claude/campaigns/atlas-v2/sprint-NN-<name>.md` (13 sprints)  
Status: PLANNING — fire Sprint 01 after PR #262 merges  
To start a sprint: copy the `/run` prompt from the sprint file and paste into a fresh Claude Code session.  
Anti-drift gate: read §1 of `.claude/campaigns/atlas-v2.md` before firing any sprint.

---

## Operating rules

1. `process_batch()` is the only calculation path
2. Never recompute in the Cliq layer
3. Always run `make verify` before a live batch
4. If `golden_constants.py` is updated for a new golden batch: tests must fail first, workbook must be validated, tests must go green after update
5. Use the connector named exactly: **Estrella Cliq**
6. WorkDrive: resource IDs come from the API response — never search, never wait for TrueSync
7. Cliq notification is always sent immediately after PZ completion — WorkDrive state does not block it

---

## When asked to run a shipment

1. Confirm inputs are present.
2. Run `make verify`. Stop if it fails.
3. Call `/api/v1/pz/process` (without `post_to_cliq`).
4. Read `workdrive_pdf_resource_id` + `workdrive_xlsx_resource_id` from the response.
5. If resource IDs present → create WorkDrive share links via `ZohoWorkdrive_createExternalShareLink`.
6. Post concise result + links (or "WorkDrive pending") via Estrella Cliq to `#PZ`.
7. Surface mismatches or verification gaps honestly.

---

## 9. Action execution after Cowork result

Chain: **Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit.** Coworker returns exact structured data only; it does NOT send emails.

Cowork must NEVER directly:
- Modify CIF / duty / invoice totals
- Send emails
- Close shipments
- Delete or move emails
- Choose email recipients (PZ App controls routing)
- Attach files to emails (PZ App controls attachments)
- Override sender identity

Full architecture, draft validation, execution rules, draft type reference: invoke `cowork-integration`.

---

## Short instruction version

> Full operational summary: invoke `pz-shipment`.
