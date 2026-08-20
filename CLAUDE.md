# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository.

**This file is the always-loaded binding layer: rules, gates, authorities, prohibitions.** Origin narratives, incident write-ups, worked examples, verbatim operator rulings and reference specs live in the authoritative files cited inline. A pointer never weakens the rule above it — the rule here binds; the pointer only says where the evidence is.

---

## Commands

Root regression (before every live batch): `make verify` — fast unit tests + format checks (~2s). Before PRs: `make verify-full` — unit + golden PDF pipeline (~30s). Regenerate golden: `make reference` (only when intentionally changing golden constants). Install the pre-commit hook that blocks on test failure: `make install-hooks`.

Service dev: `cd service && make install` / `make dev` (uvicorn app.main:app --reload --port 8000) / `make verify`.

Individual tests: `pytest test_pz_regression.py -k "<test_name>" -v` (root); `cd service && pytest tests/test_routes_pz.py -v`; `cd service && pytest tests/ -m smoke -v` (fast smoke subset).

Root CLI: `python pz_import_processor.py --invoices <invoice.xlsx> --zc429 <zc429.pdf> --rate <r> --pdf --xlsx --doc-no <PZ/NNN/YYYY>`.

Full command surface: the Makefile at repo root and `service/Makefile`.

---

## Architecture

**Repo layout** — `service/app/` = FastAPI backend (production service, port 47213): `main.py` (imports 50+ route modules), `api/` (~70 `routes_*.py`), `services/` (~214 modules — all business logic), `agents/`, `core/` (config, audit, guards, circuit breaker, security), `auth/` (JWT + session), `static/` (V1 HTML + Vanilla JS; V2 under `static/v2/*.jsx`). `service/tests/` = 748 pytest files. Root engine files: `pz_import_processor.py` (standalone CLI + only calculation path), `pz_calculator.py`, `customs_description_engine.py`, `test_pz_regression.py` (90 golden regression tests). `reference_batch/` = golden expected outputs; `docs/` = operational markdown; `.claude/` = agents, campaigns, memory, contracts, skills.

**Calculation authority** — `process_batch()` in `pz_import_processor.py` is the ONLY calculation path for landed cost, freight allocation, duty and totals. Never recompute in routes, services or the Cliq layer.

**Databases** — SQLite only, one file per domain; each `service/app/services/*_db.py` owns its database. No shared ORM; direct `sqlite3` calls.

**Frontend** — V1 (`shipment-detail.html`, `dashboard.html`) and V2 (`static/v2/*.jsx`) are both Vanilla HTML + Babel JSX — no bundler, no TypeScript, no Tailwind; do NOT apply TypeScript/Tailwind defaults here. Shared primitives: `static/components.js`, `static/v2/components.jsx`.

**Route registration** — all routes import into `service/app/main.py`; a new route file requires its `include_router` call there.

**AI integration** — `services/ai_gateway.py` wraps the Anthropic API; `ai_bridge.py` dispatches structured tasks; tests isolate the gateway via `conftest.py` fixtures.

**Feature flags** — `service/app/core/config.py` exposes runtime flags (`audit_hardening_enabled`, `compliance_intelligence_resolver_enabled`, `series_bootstrap_enabled`). No `.env` file; configuration is environment-variable driven.

**Deploy layout** — the standard sync copies `service/app` to the production app directory; root-level engine files deploy to the production `engine\` directory via a SEPARATE sync (Lesson J).

---

## Production deployment rule (PERMANENT)

**Every Git-based production deploy requires the full 7-agent gate. No exceptions.** Full rule: `service/docs/production_deployment_rule.md` · slash command `/deploy` · agent files `.claude/agents/deploy_*.md`.

The 7 required agents (run in parallel before any sync): `deploy_lead_coordinator` (final go/no-go) · `deploy_git_diff_reviewer` (file classification, forbidden paths) · `deploy_backend_impact_reviewer` (routes, auth, imports) · `deploy_persistence_storage_reviewer` (schema, storage writes) · `deploy_security_reviewer` (credentials, auth removal, injection) · `deploy_qa_reviewer` (test pass/fail; counts in `.claude/contracts/test-baseline.md`) · `deploy_release_manager` (branch hygiene, rollback command).

Production: `C:\PZ` | Service: `PZService` (NSSM, port 47213) | Public: `https://pz.estrellajewels.eu`

---

## Working-tree registry (Windows host layout)

| Path | Role |
|---|---|
| `C:\PZ` | Production — NSSM AppDirectory (`PZService`, port 47213). Never `reset --hard`, never synced INTO. |
| `C:\PZ-main` | Deploy source — pinned to `main`, ff-only pulls. |
| `C:\PZ-verify` | Verification clone (primary git tree for file-hash checks). |
| `C:\PZ-active` | Current implementation campaign (one at a time). |
| `C:\PZ-archive` | Cold storage, read-only. |

**Commit-scoped reads (Lesson Q rule 7):** before any deploy-gate / PR-review read, confirm the tree's `HEAD` equals the SHA under review; if not, read `C:\PZ-main` at that SHA or a clean `git archive` export, and say in the verdict which tree and HEAD the finding came from. A verdict from the wrong revision is a false verdict.

One Claude session at a time operates against `C:\PZ-verify`; a second session is read-only or uses its own worktree. Campaign-branch writes are guarded by `.claude/hooks/campaign-branch-guard.py` (registry `.campaigns/`); an `expected_head` mismatch is an operator incident, never auto-corrected.

---

## APPLICATION AUTHORITY RULE (permanent, operator-ratified 2026-07-03)

There is only ONE application: **EJ Dashboard**. Every module belongs to it. "PZ App" is NOT an application — PZ is one workflow/module inside EJ Dashboard. Never create architecture treating PZ, Inventory, Sample, Consignment or Returns as separate applications.

**Start every feature with the question:** which existing EJ Dashboard module am I extending? (operator's wording: "मैं EJ Dashboard के किस existing module को extend कर रहा हूँ?") No answer = **STOP**. No new page, no new authority, no new master, no direct wFirma mapping.

**The only permitted path to wFirma:** `<module> → EJ Dashboard <Master> → Mirror → wFirma`. A module that calls wFirma product/customer APIs directly, or grows its own customer/product table, is an **AUTHORITY VIOLATION** — STOP immediately.

**MASTER-FIRST RULE** — before building any new module or API, prove which existing Master it consumes. Product and Customer facts come ONLY from **Product Master** / **Customer Master**. Direct wFirma queries are forbidden in Inventory, Sample, Returns, Consignment, Invoice, Packing, PZ and WZ. If the existing Master is insufficient, **STOP** and extend the Master — never bypass it.

**MASTER CONSUMPTION RULE** — every business module must consume Masters; none may consume Mirrors; none may consume wFirma. Mirrors exist only for synchronization, Masters only for business logic. A **Mirror** holds ONLY `wfirma_id, product_code, sync_version, last_sync, hash, deleted_flag` — nothing else, never business logic. A **Master** holds design number, product code, category, status, active, business mapping. **Inventory NEVER reads the Mirror — only the Master.** Standing pin: `service/tests/test_master_consumption_rule.py` (mirror schema = exactly those six columns; the known-violation list shrinks per C-1 sub-slice and must reach zero by C-1d; new violations fail immediately).

**Scope note** — architectural, not a rename mandate. It does NOT authorize renaming files, paths, services or tables containing "PZ"; any such rename is a separate operator-approved slice. Violation cleanup list: `reports/inspection/2026-07-03T-integration-architecture-audit.md`.

**Phase-C Constitution** — the operator-ratified 20-clause preamble governing all Phase-C work (authority chain; Product and Customer authority; Design Number rule; wFirma custom-field rule; Master structures; warehouse documents; Sample and Consignment workflows; product selection; Inventory UI wireframe authority; existing-pages and existing-backend rules; authority violation; locked implementation order; scope rules; no-creativity; research rule) is recorded VERBATIM (R4), with the advisor reconciliation, at **`docs/governance/phase-c-constitution.md`**. Binding summary that always applies: **no new page · no new master · no new authority · extend the existing module · Inventory UI is exactly the supplied wireframe · never type or paste IDs (always Customer → Product → Design Number → Checkbox → Execute) · warehouse documents (PZ, WZ, MM, Warehouse, Invoice) stay in wFirma and the app NEVER becomes the fiscal authority · implementation order is locked · if any of {authority owner, existing page, existing API, existing DB, existing service} cannot be identified, STOP · never invent architecture, workflow, fields, tables, pages or APIs · never guess a wFirma capability — research first.**

---

## OPERATING MODEL — governance reset (operator-ratified 2026-08-07)

REPLACES the former GATES 1-6 ratchet. Every incident-derived control that protects production bytes survives; every control that merely sequenced paperwork is gone. Historical references resolve: "GATE 1" → the one seven-agent gate below · "GATE 2" → retired (open-PR count is never a deploy blocker) · "GATE 3" → retired · "GATE 4" → findings go to the issue backlog · "GATE 5" → the substitution-disclosure line below · "GATE 6" → browser verification for UI changes (mode 1).

**Two permanent rules (operator's words, verbatim):**

> Production runtime fix that has passed one seven-agent gate must proceed directly to merge and deploy. Unrelated test, documentation, governance, queue, memory, or inherited-CI work must not delay deployment.

> Do not create a new governance PR while a validated production fix is waiting to deploy, unless the new finding proves that deployment itself is unsafe.

**Three operating modes — there are no others.**
1. **Normal bug / feature (runtime change):** fix → targeted tests → **seven-agent gate, once** → merge → deploy → smoke test → done. UI changes additionally get browser verification (flow, console, network, full click→API→DB→UI chain) before the gate. The gate reviews one frozen head; a subsequent **test-only or docs-only commit does not invalidate the verdict** and does not restart the gate — the gate binds to the production bytes it reviewed, not to the commit SHA.
2. **Test-only / docs-only:** fix → targeted tests → merge. **No seven-agent gate. No deploy.**
3. **Sensitive change** — extended review applies ONLY to: destructive DB migration, accounting writes, inventory mutation, customs submission, auth/security authority change. Everything else is mode 1 or 2.

**The seven-agent gate (the one gate).** Runs ONCE per runtime change, on a frozen head, all seven `deploy_*` agents. Reviewers **classify risk, they do not stop deploys**: only a **HIGH/CRITICAL executable defect** blocks the current task; LOW/MEDIUM findings become **backlog issues** — never a fix-batch, never a gate re-run, never a new PR in the same campaign; the same production bytes are never re-gated (a re-run happens only when the runtime content actually changed); a named subagent that cannot be dispatched is disclosed and substituted **openly, never silently**.

**Never a deploy blocker:** inherited CI red (the aggregate carries a tracked red set; only the metered floors in `.claude/contracts/test-baseline.md` gate) · open-PR count · docs/test PRs · observer, scorecard or memory updates · reviewer LOW/MEDIUM findings · queue arithmetic or historical sequential deploy ordering. **When a fix is production-ready, deploying it is priority #1; cleanup comes after.**

**CI authority — diagnostic, never a gate.** CI exists to detect regressions from a changed file, detect platform-specific (Windows / py3.9) failures, and provide evidence for later cleanup. It never authorizes and never blocks a merge or deployment. The only CI question ever asked of a PR: *did this PR introduce a NEW failure?* If no, proceed; for test-only and docs-only PRs, CI is ignored for production purposes. Node-ID set-difference classification is a **test-PR merge tool** only, never deployment ceremony. **Do not wait for CI. Do not poll CI. Do not require green checks. Do not classify historical CI failures unless a changed file is implicated.** **No repository configuration may elevate CI** — branch protection, required status checks, merge queues, auto-merge or any future platform mechanism may not give CI merge or deployment authority without an explicit operator governance decision recorded in PROJECT_STATE.md DECISIONS. The check-name note inside `.github/workflows/ci.yml` (naming `Service pytest (aggregate)`) is a hypothetical technical fact, not an intent.

**Runtime payload — what a gate verdict binds to.** *Runtime payload* = every file copied to production by the governed deployment procedure: the `service/app` tree plus the governed engine files enumerated by `engine_files` in `.claude/deploy/windows_prod_v2.json` (16 entries at ratification). Documentation, tests, CI workflows, GitHub metadata, review notes and memory/state files are explicitly excluded. **A previous seven-agent GO remains valid only when a byte-for-byte comparison between the previously approved runtime payload and the pending one is empty**; any non-empty payload diff requires a fresh round. Between a GO and completed smoke verification the release track permits exactly: the deployment, smoke verification, rollback, and rollback preparation — rollback work never violates the deploy-first rules. Deferred obligations (observer, scorecards, backlog dispositions, memory/state updates) fire immediately after successful smoke verification or rollback completion.

**Safety kept in full (non-negotiable):** seven-agent review (once) · forbidden-path check · production backup · rollback · production identity proof · app + engine sync (Lesson J) · service stop/start health verification. One deployment authority: `.claude/deploy/Deploy-PZ.ps1` behind one gate. Financial, customs, inventory and accounting writes remain hard-gated and operator-approved.

> The **complete verbatim reset instruction** (operator's words, 2026-08-07) — normative source for the CI-authority and runtime-payload paragraphs above — is at **`docs/governance/operating-model-reset-2026-08-07.md`**. Read it when the excerpt is disputed or a boundary case is being interpreted.

**Engineering OS.** Repository-canonical execution framework: **EJ Engineering OS v1.4** at `.engineering-os/` (docs-only; version delta in `.engineering-os/VERSION_HISTORY.md`). `00 §11` Evidence Contract, `00 §12` MODULAR-MINIMAL + Anti-Bloat gate, `00 §13` Bounded Engineering Loop — governance over Claude Code's native `/loop` and `/goal`; **there is no project loop command** — and `00 §14` OS-load arming + output hygiene. It is **subordinate** to this OPERATING MODEL, the Engineering Lessons, the seven-agent gate, and operator approval. The single authoritative definition of feature completeness remains the **Business Feature Completeness Standard** below — the OS points to it and never redefines it.

---

**Delivery fast path (risk lanes).** One entry point: `python .claude/hooks/deliver.py plan` classifies the changeset into **L0** (outside the runtime payload -- never deploys, targeted tests only), **L1** (ordinary `service/app` change -- targeted + metered floors + the one seven-agent gate), **L2** (auth/security, schema, runtime config, engine files, governance -- adds golden regression + extended review) or **BLOCKED** (forbidden paths). Lane and `deploy_required` are **independent axes**: an L2 changeset carrying zero runtime bytes still deploys nothing. `deliver.py` classifies, validates and reports -- it **cannot** deploy, authorize, merge or sign; that authority stays solely with `deploy_authorization.py` + `gate_evidence.py`. Config unreadable or path unrecognised inside the payload = fail closed to L2. Full architecture, measurements and residual risks: `docs/governance/delivery-fast-path.md`.

**A process exit status is execution evidence, never authorization.** Exit 0 proves a command ran; it authorizes nothing. Test verdicts come from `.claude/contracts/test-baseline.md` (floors + registered known-failures) with *content* read from `--junitxml`, never from pytest summary formatting (Lesson S rule 8). Measured: the carrier suite exits **1** with 758 passed / 3 registered failures against a 604 floor -- an exit-code gate would wrongly block that deploy.

**Self-healing is the default; stopping is the exception.** On failure: capture the exact failure -> classify it (campaign-introduced / pre-existing / environmental / operator-only / transient / evidence the design is wrong) -> find root cause, reading primary documentation when it is a platform question -> smallest sound repair -> re-run the **narrowest decisive** validation -> continue. **A retry must follow either a repair or evidence the failure was transient** -- arbitrary retry loops are prohibited. Stop only at the four HOLD conditions or a genuine operator-only boundary; never manufacture a boundary because a task is inconvenient, and never route around a security control, deploy guard or permission boundary to avoid one.

**Session performance guard (measured 2026-08-20).** Effective context window is **1,000,000**; the static floor is ~123K (12%), so compaction should be rare -- **repeated rapid compaction is a performance incident**, diagnosed per `docs/governance/session-performance-guard.md` §6.4, never by reflexively shrinking CLAUDE.md or re-running `/compact`. **Full evidence to disk, bounded decisive evidence to the conversation** -- and that binds the agent's own reports, not only its tools: measured, whole-file `Read` is 48% of all tool tokens (never read a large file whole; locate, then read a range; never re-read an unchanged path) while test output is 1.6%, and `PROJECT_STATE.md` (1.06 MB, ~300K tokens) is **never** read whole -- use `PROJECT_STATE_SUMMARY.md` or grep. Hooks (~107 ms, parallel), the auto-mode classifier and MCP schemas were each measured and are **not** the cost -- **no security, permission or governance control is disabled for speed, and no performance claim is made without before/after measurement**. A session is DEGRADED at >=80% context, >=3 compactions, or two compactions inside 10 minutes (age alone never counts): checkpoint via `python .claude/scripts/session-handoff.py`, exit, resume in a fresh session from `.claude/memory/TASK_STATE.md`. Transcripts are preserved by default.

## OBSERVATION LAYER (post-merge, never a release condition)

Read `.claude/memory/PROJECT_STATE.md` at session start when present — it is the source of truth for current project state; do not re-derive state from lossy chat history. After a merge to main, `agent-performance-observer` (scorecard) and `flow-context-keeper` (state update) run **in the background**. They are memory and telemetry, NOT gates: **no deploy, merge or task waits on an observer, scorecard or memory update.** Scorecards live in `.claude/memory/scorecards/` and are cited by path. Both run automatically; to run either by hand, dispatch the agent by name (`agent-performance-observer`, `flow-context-keeper`) — there is no project slash command for them.

---

## AUTONOMY AND STOPPING

Continuing autonomous work is the default; stopping is the exception. A session may stop and hand back to the operator ONLY on one of four HOLD conditions, named explicitly when stopping:

1. **Destructive production action** — the next step would delete, overwrite or irreversibly mutate production data, a live service, or a booked external record (wFirma posted PZ, sent email, production sync, production `reset --hard`, DB drop). Confirm first.
2. **Missing credentials / access** the session cannot safely obtain.
3. **Legal / financial approval** (value corrections, customs declarations, money).
4. **Unclear business decision** where a wrong guess has real cost — a merely technical ambiguity with a sensible default is NOT this; pick the default and note it.

Code inspection, tests, local verification, docs/state updates, non-destructive refactors and opening a PR are never HOLD reasons. Record a one-line HOLD reason in `.claude/memory/TASK_STATE.md` when stopping (lifecycle states: `.claude/TASK_EXECUTION_PROTOCOL.md`). **A production-ready fix deploys before any cleanup, backlog or governance work begins.**

**Resumable stops:** a stop on an external dependency that preserves a verified checkpoint is `EXECUTION_BLOCKED` — **resumable, not restartable**: on return, validate the checkpoint (branch / HEAD / diff) and execute the single recorded resume command; do not re-plan or re-implement work that is still valid. Full rule: `docs/governance/anti-hold-and-completion.md` §7.

---

## Business Feature Completeness Standard (permanent)

A business capability cannot be marked **Production Complete** until all seven requirements are satisfied and signed off by the named Business Owner. Governs every module: Customer Master, Accounting, Product Master, DHL, Inventory, KSeF, Reports, AI. The scheduler, the API endpoint and the UI button all call the **same** `run_<capability>()` function — diverging into "Logic A" and "Logic B" is forbidden.

**The seven requirements.** (1) **Automation** — a scheduler or webhook triggers `run_<capability>()` automatically. (2) **Shared Service** — one `run_<capability>()` reused by scheduler, API and UI button. (3) **Business API** — `POST /api/v1/.../action` + `GET .../status`. (4) **Business UI** — operator button + status panel, no developer intervention needed. (5) **Observability** — last run / processed / created / updated / skipped / errors visible. (6) **Browser Verification** — end-to-end test in a real browser with real production data. (7) **Business Verification** — the named Business Owner confirms the workflow is usable without developer help.

Requirements 1–5 are implementation requirements; 6–7 are acceptance gates. An exception to any requirement requires an explicit ADR in `docs/decisions/`. **"Not built yet" is not an exception — it is an incomplete feature.**

**Feature lifecycle (seven stages, none may be skipped):** `Design → Implementation` (code written, tests passing, PR open) `→ Technical Complete` (reqs 1–5; PR merged to main) `→ Deployed` (running in production; endpoints respond; scheduler fires) `→ Browser Verified` (req 6; happy path + idempotency confirmed) `→ Business Verified` (req 7; owner sign-off recorded) `→ Production Complete` (all seven; feature closed). A feature can be Technical Complete but not Deployed, or Deployed but not Browser Verified — these are distinct states. **"Scheduler written" = Technical Complete at best. "Tests pass" = Implementation. Neither is "done."**

**The four questions every sync screen must answer**, all immediately visible when an operator opens it: (1) what is the current state (running / healthy / error)? (2) when did it last run (`last_completed_at`)? (3) what happened (processed / created / updated / skipped / errors)? (4) can I run it now (Run Now button, always enabled)?

**Contracts and registry (pointers).** The **Business Owner registry** (module → owner; required for requirement 7), the **canonical status API response shape** for `GET /api/v1/.../status`, and the **canonical UI layout** (Client Master reference toolbar + status panel) live in `docs/patterns/status-endpoint.md`. Per-feature lifecycle stage: PROJECT_STATE.md FACTS. When a feature reaches Business Verified, record date, Business Owner name and conditions.

**Enforcement.** `reviewer-challenge` and `frontend-flow-reviewer` must flag any PR claiming "feature complete" or "Production Complete" that has not passed all seven requirements. A scheduler-only implementation is at most Technical Complete — never Production Complete.

---

## FRONTEND AUTHORITY CONSTITUTION (V2 = consolidation authority)

V2 is the current frontend authority for all consolidation and new development. This is the consolidation authority, NOT a commitment to V2 as the permanent architecture; a future rebuild is a separate, separately-approved decision and does not weaken these rules while V2 is the authority.

**PROHIBITIONS (hard — no exception without a formal PROJECT_STATE.md DECISIONS entry):** no duplicate page for a module that already has a canonical page · no new standalone HTML page (login / auth / static shell excepted) · no new parallel React app · no feature work in legacy / frozen pages · no "temporary" second implementation.

**ONE-AUTHORITY REQUIREMENT** — every business module has exactly one canonical URL, one canonical React file/folder, one API wrapper path, one backend authority.

**PRE-DEVELOPMENT CHECK (before ANY frontend work; all five must pass):** (1) identify the module; (2) identify the canonical URL; (3) identify the canonical frontend file/folder; (4) identify the backend authority; (5) prove no duplicate page is being created.

**STOP CONDITION:** if canonical authority is unclear, STOP and ask the operator. Do not develop in both places; do not pick a canonical silently. Binds: the seven-agent gate, `frontend-flow-reviewer`, Lesson F, Lesson M.

---

## Engineering Lessons (permanent)

Append-only; supersede with a new dated entry, never delete. **Letters are unique and this file shares one letter space with `.claude/memory/engineering_lessons.md`** — grep **both** before adding one. On a collision the *later-published* entry moves to the next free letter (content, date, position unchanged) and carries a **letter note** naming its former letter. Never renumber to close a gap; never reuse a retired letter.

Every rule below binds as written. Origin narratives, detection signals, examples and incident evidence: **`.claude/memory/engineering_lessons.md`** (same letters); `memory-lessons` agent; `engineering_discipline_rules` auto-memory.

**A — Test stubs must match real production return shapes (2026-05-13).** *Binds the seven-agent gate; `integration-boundary` owns the verdict, `testing-verification` adds the test, `backend-safety-reviewer` flags missing `_normalise_X` helpers.* Stubs MUST match the real builder return shape; stub authors MUST read the real function first. Every coordinator/builder PR MUST include a real-builder regression test (no stub) asserting the type contract. Coordinators MUST normalise polymorphic inputs via `_normalise_X`. A post-merge Lesson-A failure is a salvage finding needing a SCHEDULED / ISSUE / REJECTED disposition.

**B — Mid-session `git pull` does NOT reliably refresh the subagent_type registry (2026-05-13).** *Binds substitution disclosure + the first-task-of-session diagnostic.* Agent files added mid-session are NOT guaranteed invocable — treat as "available next session". Post-merge validation for an agent-adding PR MUST report VALIDATION-FAILED if the new agent cannot be dispatched. **Silent meta-agent substitution is FORBIDDEN** — escalate. Restart the session after any agent-adding merge.

**C — Observer scorecard writes must be orchestrator-verified post-write (2026-05-13).** The orchestrator MUST confirm the scorecard exists on disk after the observer returns; self-report is not evidence. Missing file → dispatch FAILED, re-fire or escalate. `flow-context-keeper` MUST validate every cited scorecard exists before the run completes; citing an absent file is a violation.

**D — LOCAL-COMMIT-ONLY deploys must be disclosed and reconciled (2026-05-13).** *Binds the seven-agent gate.* Such a deploy MUST show a disclosure header (SHA, "GitHub PR: NONE", bypass reason, reconciliation plan) **before** any sync command and visible to the operator, who MUST acknowledge. A reconciliation PR MUST be filed before the next `git pull --ff-only origin main`. Every such deploy appends to `.claude/memory/local-commit-deploys.jsonl`. Detail: `docs/governance/lesson-d-local-commit-only-deploys.md`.

**E — Background email automation requires five mandatory safety properties (2026-05-18).** *Binds the gate + every email-capable background process.* All five required: (1) execution-time validation; (2) idempotency keyed on AWB + type + date window; (3) terminal-state suppression; (4) replay safety — durable sent-state written before return; (5) environment isolation via an `ENV=production` guard.

**F — V2 frontend migration requires frozen V1 and strict authority isolation (2026-05-20).** *Binds the gate + V1-FREEZE.* V1 frozen (critical fixes only). **ONE PAGE = ONE DOMAIN AUTHORITY.** `pz-api.js` = transport only; `pz-state.js` = normalize/cache and is **FORBIDDEN** to decide workflow legality or redefine accounting readiness; `pz-components.js` = stateless rendering; `dashboard-shared.js` = visual atoms only, zero domain knowledge. Dashboard-v2 is built last. Danger phrases: "temporarily", "reuse this renderer", "copy this state logic".

**G — Generated-artifact stale-display bugs are first a cache / atomicity problem (2026-05-21).** *Binds every generated-artifact and download-endpoint PR: `backend-safety-reviewer` must flag any `FileResponse`/`StreamingResponse` for a regenerable file that does not explicitly set `Cache-Control: no-store`, and any generator that updates audit pointers without an intermediate forbidden-token validation step.* Diagnostic order: disk file → reference layers → HTTP headers → browser cache. Download endpoints MUST set `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` + `Pragma: no-cache` + `Expires: 0`. Overwrite-safe generation: write → validate → on failure unlink + 422 + **NO** audit-pointer update → on success replace atomically → update audit pointers **LAST**.

**I — Production incidents become workflow-class rules, never shipment-specific patches (2026-05-22).** *Binds the gate + `reviewer-challenge`.* Six steps: classify → name the authority owner → cardinal question → convert to platform behaviour → verify broader impact → closure (root cause + workflow class + regression tests + unaffected workflows confirmed). Complete **before coding**: *"This is a [bucket] incident. The fix target is [component]. The workflow class is [description]."*

**J — Root-level engine files are outside the standard `service/app` sync (2026-05-22).** *Binds the seven-agent gate.* `pz_import_processor.py` and `polish_description_generator.py` deploy to `C:\PZ\engine\` via a **SEPARATE** sync not covered by the standard `service/app → C:\PZ\app` sync. The PR body MUST declare the additional sync command. Verify via `Select-String`, never a Python import.

**K — Broad tool grants require explicit negative-scope language (2026-05-23).** Every prompt dispatched with write-capable grants (Bash, Write, Edit, gh, sc.exe, file-sync, MCP write tools) MUST name forbidden commands explicitly: *"DO NOT call \<X\>, \<Y\> — read and report only."* Generic phrasing ("verdict only", "just review") is INSUFFICIENT. Grant-set parity required.

**M — Planned operator-visible capability must not be removed, hidden, collapsed, replaced or silently relocated (2026-06-07).** *Binds the gate + `reviewer-challenge` + `frontend-flow-reviewer` on every V2 page PR and every PR touching an operator-visible capability* (buttons, menu items, tabs, panels, sections, workflow actions, roadmap placeholders). Five-state UI truth model: `available` / `unavailable` / `planned` / `backend-pending` / `deprecated`. Removal ONLY with a formal cancellation in PROJECT_STATE.md DECISIONS (date + reason + capability named). **Suppression without a cancellation record = incomplete PR.**

**N — Advisory-class readiness signals must never block fiscal actions (2026-06-23).** *Binds the gate + `reviewer-challenge` + `readiness-closure`; every readiness/gating change in `sales-proforma`, `pz-purchase-accounting`, `readiness-closure`; every PR adding, removing or reclassifying a blocking reason on Approve / Post / Convert / Reservation.*
- **Advisory-only — NEVER block; surface and let the action proceed:** sales linkage (sales design ↔ wFirma `product_code`) · missing warehouse scan · missing warehouse confirmation · PND / placeholder-design source rows.
- **True blockers — the ONLY conditions that may block:** (1) customer unmatched or ambiguous; (2) missing price; (3) over-bill — sales allocated qty > PZ / import authority qty per `product_code`; (4) VAT / WDT fiscal failure; (5) duplicate document risk; (6) live write-gate disabled; (7) `product_code` missing for actual posting; (8) sales allocated qty exceeds PZ / import authority.
- Anything not on that list is advisory; **default-classify as advisory**. A new hard gate must name which fiscal/tax/duplication risk it protects against, else `reviewer-challenge` rejects it. `routes_proforma.py:1000` (under `settings.advisory_gates_enabled`) routing the unmapped-sales-design signal to `line_mismatch_advisories`, not `blocking_reasons`, is the permanent default, not a flag-gated exception. Promoting an advisory to a blocker, or demoting a true blocker, is an incomplete PR. **Distinct from Lesson R**, which held the letter `N` until 2026-08-04.

**O — Tightening a route's auth breaks every test that authenticated the old way; migrate the tests in the same PR, never weaken the route (2026-07-22).** *Binds the gate + `security-permissions` + `reviewer-challenge`; every PR changing a route's `dependencies=[...]` guard and every route test sending `X-API-Key`.* After tightening (`require_api_key` → `require_admin`, or `require_role(...)` added), `X-API-Key` tests return **401 "Not authenticated"** because those guards flow through `get_current_user`, which raises 401 with no `pz_session` cookie — a **stale-test signal, not a route bug**.
1. **Same-PR test migration** — migrate every test exercising that route in the same PR; grep the route path across `tests/` before merging.
2. **Diagnose the 401 correctly** — read the current dependency and its `git log -S`; if the tightening was intentional, the *test* is stale.
3. **Never downgrade the route to green a test** — that is a security regression.
4. **Canonical fix:** `app.dependency_overrides[require_admin] = lambda: {"role": "admin", ...}` (or `get_current_user` for `require_role` routes), popped in a `finally`; prove leak-free by interleaving with an auth-denial suite.

**P — A timestamp-based sync from a fresh worktree re-copies the whole tree; verify deployed content, never the "blast radius" (2026-07-23).** *Binds the seven-agent gate + the Step 5 sync, especially a deploy run from a `C:\PZ-wt\*` worktree instead of `C:\PZ-verify`.* The exclude-older flag copies by **timestamp, not content**, and `git worktree add` stamps every file's mtime at checkout, so a fresh worktree makes the whole `service/app` tree look newer; `C:\PZ-verify` is persistent, which is why the standard command is incremental there.
1. **Content is the deploy truth** — before declaring a blast radius, diff by hash (`Get-FileHash` / `diff -rq`) between `C:\PZ\app` and the source `service/app`; state the **content** delta to the gate and re-verify **content diff == 0** after the sync. Never report the copied-file count as the blast radius.
2. **A whole-tree re-copy is acceptable only when content-verified** — post-sync diff 0 means production == the deploy SHA and the over-copy is a no-op; non-zero and unexplained → **STOP**, the source diverged from what was reviewed.
3. **Prefer an incremental source** — deploy from `C:\PZ-verify` when clean and on-SHA; if a worktree must be used, scope the sync to the explicit changed files or accept the whole-tree copy *after* the hash-diff proof.

**Q — A safety claim is worthless without a source citation, and a citation is worthless if resolved against the wrong revision (2026-08-01).** *Binds the gate, salvage findings, every state-file / handoff register, and every commit-scoped reviewer verdict. `reviewer-challenge` must flag any claim that a gate blocks / a guard fires / an operation is safe-by-design that names no implementing function, treating an* optimistic *uncited claim (one permitting proceeding) as the higher-severity case. Rule 7 additionally binds all seven `deploy_*` agents, every `reviewer-challenge` on a diff, and any finding that a symbol, flag or guard is **absent**.*
1. **A safety-property claim in a state file requires a citation** naming the **function** (and file) that implements it. Uncited = an assumption, and must be written as one.
2. **Cite the function, not just a line number** — line numbers drift across branches; a citation unresolvable on the reader's branch is not a citation.
3. **Verify before relying, not before writing** — re-verify when the claim is *acted on* (resume, handoff, deploy decision). State files are memory; the code is the authority.
4. **Name where the protection lives** — "this is caught" and "this is caught by an unmerged PR" are opposite operational facts.
5. **Correct by marking, never deleting** — mark a wrong claim **WITHDRAWN** with the corrected mechanism beside it; deleting destroys the audit trail of why the reasoning changed.
6. **Wrong-in-your-favour is the severe class** — an optimistic error removes a stop the operator believed they had; any claim that *permits* proceeding needs the citation and a `reviewer-challenge` second pass before commit.
7. **A citation must be resolved against the revision under review.** A path is not a revision: before any commit-scoped read, confirm the tree's `HEAD` **is** the SHA under review, else read `C:\PZ-main` at that SHA or a clean `git archive` export. Every such verdict must state **which tree and which HEAD** it read; one that cannot name its revision must be re-run, not weighed. An **absence** claim ("the flag does not exist", "there is no guard") is the highest-risk form — a stale tree produces it silently and it reads as decisive; confirm an absence on the reviewed SHA before it may block anything. Check ancestry with `git merge-base --is-ancestor` (behind, not diverged).

**R — Import, product master, proforma, warehouse receipt, barcode traceability and sales linkage are SEPARATE authorities (2026-06-22).** *Letter note (2026-08-04): published as Lesson N until found to collide with the advisory-vs-blocker Lesson N (2026-06-23); content, date and position unchanged, only the letter moved. A historical "Lesson N" meaning* authority separation / six separate authorities / single-authority rule / wrong authority — *including docstrings in `service/tests/**` and dated records under `reports/**`, left as written — means **R**; meaning* advisory vs blocker *or the true-blocker list, means **N**.* *Binds the gate + `reviewer-challenge` + `frontend-flow-reviewer` + `backend-safety-reviewer`; every readiness/blocker producer (`routes_proforma`, `wfirma_reservation`, `sales_linkage`, `routes_wfirma` product-resolve + pz_preview, `warehouse_receipt`) and every PR adding or moving a readiness gate.* Six authorities — source of truth · MAY hard-block on · must NOT block on:
- **PRODUCT** — supplier invoice / import rows · missing product code, duplicate conflict, invalid accounting fields, live-create approval (`WFIRMA_CREATE_PRODUCT_ALLOWED`) · stock, scan, sales packing, PZ status, SAD, proforma.
- **PROFORMA** — customer + product master + pricing · customer unmatched/ambiguous, missing price, design ambiguity, over-bill, WDT EU-VAT, margin-mask · inventory / stock / PZ / scan (advisory only).
- **IMPORT_PZ** — import invoice/packing + customs evidence + mapped products + confirmed received qty · unmapped products, no SAD/customs evidence, duplicate PZ, price conflict, live-write approval (`WFIRMA_CREATE_PZ_ALLOWED`) · sales packing list, customer allocation, per-piece barcode scan.
- **WAREHOUSE** — operator quantity confirmation by line/batch (`warehouse_receipt`) · advisory, quantity-risk only · mandatory per-piece scan unless `serial_controlled`.
- **SALES** — sales packing / allocation / reservation · final dispatch and sales posting; reservation needs customer matched + product mapped + stock dispatched per billed line · product creation, proforma, product adoption, import qty confirmation, import PZ.
1. **Every guard declares its authority** — structured blockers carry `authority` ∈ {PRODUCT, PROFORMA, IMPORT_PZ, WAREHOUSE, SALES}; guard functions name it in the docstring.
2. **A warning may NOT become a hard blocker** without (a) an explicit business rule naming a real accounting / customs / duplicate-write / quantity risk and (b) a regression test pinning it. Default for missing information is ADVISORY.
3. **Warehouse receipt = operator quantity confirmation**, not per-piece scan; scan stays optional traceability unless the shipment is `serial_controlled` (from `audit.json`).
4. Fiscal writes (`WFIRMA_CREATE_PRODUCT/PZ/PROFORMA/INVOICE`) stay hard-gated and operator-approved regardless of any advisory demotion. Pin: `service/tests/test_authority_separation.py`.

**S — A waiter is infrastructure, not evidence: background completion is a sentinel plus an exit code, never formatted output (2026-08-19).** *Binds the gate + `reviewer-challenge` on every PR adding or modifying a background job, waiter, test harness, verification process or long-running shell orchestration; and the release-closure checklist via rule 9.*
1. **Formatted stdout/stderr is never the authoritative completion signal** — `-q`, `--no-header`, `-p no:cacheprovider`, non-tty stdout and terminal width all change whether pytest pads its summary.
2. **The producer owns an explicit completion sentinel** (flag file or equivalent structured status) written in a fixed order: **exit code and completion metadata durably recorded FIRST, sentinel only after that state is on disk**, so the sentinel is the producer's LAST action and any waiter that sees it finds complete metadata behind it. Waiters test the sentinel's **existence**, never the shape of its content.
3. **Capture PID, exit code, start time, finish time, session identity and worktree identity** for every background job; exit code recorded *separately* from command output and flushed durably **before** the sentinel appears.
4. **Every waiter has a finite timeout.** No exceptions.
5. **Unbounded polling loops are prohibited** — an `until … ; do sleep … ; done` with no iteration cap is a defect on sight, whatever it polls.
6. **On timeout, inspect the producer's PID / process tree and artifacts before retrying** — diagnose by parent chain, command line, creation time and port, never by process name, never with an image-wide kill.
7. **Never launch a duplicate test/build/deploy job** while the original's PID or completion artifact is unresolved.
8. **Never infer pytest completion from summary-line formatting.**
9. **Before release closure, reconcile Desktop / background-task state against actual OS process state** — a required closure step.
10. **A waiter is not evidence** — the producer's exit code plus its result artifacts are; a waiter that returned proves only that a waiter returned.
11. **Orphaned session-owned processes must not survive a completed campaign** unless the survival is explicitly justified and recorded.

`reviewer-challenge` must REJECT any PR introducing an unbounded wait loop · a grep/regex completion check against human-formatted output · a background job with no timeout · a job with no explicit exit-status capture · a long-running job with no session / worktree / PID ownership metadata. **Prefer reusable helper infrastructure over ad-hoc shell loops** — the safest waiter is the one nobody wrote; prefer the harness's own completion notification where it exists.

---

## Frontend Design Standard

Governed by `.claude/skills/frontend-design.md` and the FRONTEND AUTHORITY CONSTITUTION above; see also Lesson F. Stack (both V1 and V2): Vanilla HTML + Babel JSX — **no bundler, no TypeScript, no Tailwind.** The generic `frontend-ui` agent defaults to TypeScript + Tailwind — those do NOT apply here.

Unique hard rules (verbatim; full detail in the skill file):
- Use CSS custom properties (`--bg`, `--text`, `--badge-*`, `--accent`) — never hardcoded hex
- Use shared components from `dashboard-shared.js` (`Btn`, `Badge`, `Card`, `Sel`, `Toast`)
- Every write button must label exactly what it writes; no auto-save
- No fake readiness, no hidden blockers, no duplicate renderers
- Legacy sections in `<details>` — collapsed by default
- Every interactive element needs a `data-testid`

Invoke the skill before any UI implementation and before any `frontend-flow-reviewer` run. Design intelligence layer: `.claude/skills/ui-ux-pro-max` is a supplemental search tool for accessibility, UX guidelines, layout best practices — subordinate to `frontend-design.md`. Read `EJ_OVERRIDES.md` inside that skill directory before applying any output; its stack defaults (Tailwind, TypeScript) do not apply here.

---

## EJ Dashboard orchestration default (skill routing)

For every coding request in this repository: (1) start with the project orchestration skill `ej-dashboard-master`; (2) let the master classify the task; (3) load only the minimum required project skills; (4) never bypass the master unless explicitly requested by the user.

Routing table, conflict resolution, protected-domain gates, and skill lifecycle (Session Bootstrap → Dynamic Routing → Release): `.claude/skills/ej-dashboard-master/SKILL.md`. The seven-skill EJ Dashboard skill architecture is **FROZEN** — consult the **Skill Freeze Policy** in `.claude/skills/SKILL_REGISTRY.md` before proposing any new skill, and never install a generic third-party skill raw.

---

## Integration + system architecture + required workflow

Zoho Cliq MCP connector (all Cliq operations): connector `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`, org `60014108075`, tool `ZohoCliq_Post_message_in_a_channel`, production channel `pz` (ID `O190928000006027001`). Webhook fallback: `CLIQ_WEBHOOK_URL`. "Processing…" acknowledgment via webhook → bot chat; final batch result via Estrella Cliq MCP → `#PZ` channel; dashboard resend via webhook (OAuth fallback) → `#PZ`.

`process_batch()` in the Python engine is the ONLY calculation path — never recalculate landed cost, freight, duty, totals, or notes outside it. All outputs render from the same validated `process_batch()` result object. Cliq is not the calculation engine.

Live batch: **Step A** `make verify` (stop on failure) → **Step B** engine (CLI or `process_batch()`) → **Step C** generate PDF + XLSX (both required — either absent = failed, exit non-zero) → **Step D** post summary + files to Cliq (amendment flags explicit, not hidden).

Full architecture, CLI flags, MCP step sequence, Cliq posting formats, and the dynamic note-4 / UWAGI text: invoke `/pz-shipment`.

---

## Financial rules (must never change)

- Freight and insurance: proportional by value within each invoice. Never allocate by piece count.
- Duty: from ZC429 / A00 only, proportional by before-duty value. Never assume a fixed %.
- B00 VAT: reference-only. Not included in landed cost.
- Notes/UWAGI: from the engine only. Never reconstruct independently.

---

## Verification rules

Three-state semantics: `True` = verified · `False` = confirmed mismatch → escalate as amendment flag · `None` = could not verify → may emit `[VERIFY-GAP]` prefix; NOT a mismatch, NOT an amendment flag. Escalate only on confirmed `False`. If `--strict-match` is enabled, any confirmed mismatch must fail the run.

---

## Cliq posting + WorkDrive automation

Three Cliq posting scenarios (success / partial VERIFY-GAP / failure); each includes doc_no, line count, net, gross, duty totals. Failure messages must state "No final files were posted." Partial messages must list all gaps explicitly. Amendment flags must not be hidden. Full format blocks: invoke `/pz-shipment`.

WorkDrive architecture: local storage = truth; WorkDrive REST = primary upload; TrueSync = optional mirror only (NEVER a success condition); Cliq = immediate notification layer.

Hard one-liners (verbatim):
- **Never search WorkDrive for files** — resource IDs come from the API response
- **Never wait for TrueSync** — it is not a cloud upload path
- **Never block Cliq notification** because WorkDrive failed — always post immediately
- **Never send local file paths or localhost URLs** in Cliq
- If share link creation fails: report explicitly, state "WorkDrive pending retry"

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

## Action execution after Cowork result

Chain: **Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit.** Coworker returns exact structured data only; it does NOT send emails.

Cowork must NEVER directly: modify CIF / duty / invoice totals · send emails · close shipments · delete or move emails · choose email recipients (PZ App controls routing) · attach files to emails (PZ App controls attachments) · override sender identity.

Full architecture, draft validation, execution rules, draft type reference: invoke `/cowork-integration`.

---

## Active campaigns

**Atlas-V2 — Fresh Frontend Shell.** Campaign document `.claude/campaigns/atlas-v2.md`; sprint files `.claude/campaigns/atlas-v2/sprint-NN-<name>.md` (13 sprints). Status: PLANNING. To start a sprint, copy the `/run` prompt from the sprint file into a fresh session. Anti-drift gate: read §1 of the campaign document before firing any sprint.

---

## Short instruction version

> Full operational summary: invoke `/pz-shipment`.
