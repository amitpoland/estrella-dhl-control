# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

### Root-level regression (run before ANY live batch or PR)
```bash
make verify        # Fast gate: unit tests + format checks (~2s) — required before every batch
make verify-full   # Full gate: unit + golden PDF pipeline (~30s) — required before PRs
make reference     # Regenerate reference_batch/ expected outputs (only when intentionally changing golden constants)
make install-hooks # Install pre-commit hook that blocks on test failure
```

### Service development
```bash
cd service
make install  # pip install -r requirements.txt
make dev      # uvicorn app.main:app --reload --port 8000
make verify   # Run PZ regression tests inside service/
```

### Running individual tests
```bash
# From repo root (targets root-level test suite)
pytest test_pz_regression.py -k "test_golden_duty_totals" -v

# From service/ (targets FastAPI test suite, 748 files)
cd service && pytest tests/test_routes_pz.py -v
cd service && pytest tests/ -m smoke -v   # Fast smoke subset only
```

### Root-level PZ engine CLI
```bash
python pz_import_processor.py --invoices invoice.xlsx --zc429 zc429.pdf --rate 4.2 --pdf --xlsx --doc-no PZ/001/2026
```

---

## Architecture

### Repo layout
```
estrella-dhl-control/
├── service/              # FastAPI backend (production service, port 47213)
│   ├── app/
│   │   ├── main.py       # FastAPI entry point — imports 50+ route modules
│   │   ├── api/          # 70 route modules (routes_*.py)
│   │   ├── services/     # 214 service modules — all business logic lives here
│   │   ├── agents/       # Decision engines (proposal, cowork coordinator)
│   │   ├── core/         # Config, audit, guards, circuit breaker, security
│   │   ├── auth/         # JWT + session authentication
│   │   └── static/       # HTML + vanilla JS (V1) and React/JSX (V2 under static/v2/)
│   └── tests/            # 748 pytest files
├── pz_import_processor.py     # Standalone CLI: invoice → PDF/XLSX export
├── customs_description_engine.py  # Polish customs description generator
├── pz_calculator.py           # Landed-cost calculation engine
├── test_pz_regression.py      # 90 golden regression tests
├── reference_batch/           # Golden expected outputs for regression
├── docs/                      # Operational markdown (52 files)
└── .claude/                   # Agents, campaigns, memory, contracts, skills
```

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

## Canonical working-tree registry (PATH GUARD — permanent)

All subagent file reads, hash verification, and git operations must target exactly one of these paths.
Reading from any path not listed below is a source-drift risk.

| Path | Role | Status |
|---|---|---|
| `C:\PZ` | Production — NSSM AppDirectory (`PZService`, port 47213) | LIVE — never `reset --hard`, never robocopy'd INTO |
| `C:\PZ-verify` | Verification clone — tracks `origin/main` | SOURCE OF TRUTH for all git/file-hash checks |
| `C:\Users\Super Fashion\PZ APP` | Former scratch clone | **RETIRED 2026-06-04** — not a source of truth |

**Subagent reading rule (enforced):** All verification reads and git operations must use `C:\PZ-verify`.
Reading from `C:\Users\Super Fashion\PZ APP` is **forbidden** — that tree is retired, diverged from
`origin/main`, and returned false-negative verification results on four separate runs (2026-06-04).
It is NOT the NSSM AppDirectory and NOT safe to read, verify, or deploy from. If any subagent
or skill needs to inspect the repo, the path is `C:\PZ-verify`, not the scratch clone.

**One-session rule (enforced):** Only one Claude Code session may operate against
`C:\PZ-verify` at a time. A second concurrent session on the same tree races branch
state and produces duplicate commits (incident 2026-06-04: two sessions on VERIFY_DIR
produced `0c22cfb` direct-to-main and `6ad62a6` on a competing branch). A second
session must be read-only or must use a separate git worktree.

Elaboration: `service/docs/ops/working-tree-convention.md` (rule 6).

---

## MANDATORY GOVERNANCE GATES

These gates apply to ALL implementation work in this repository.
They are not optional and not negotiable per-task. The cost of a
broken gate is real production damage; the cost of honoring a gate
is a few minutes of disciplined waiting.

These gates **supersede** any older governance language elsewhere in
this file. Where prior language survives below as operational
guidance (workflow steps, posting formats, etc.), it is subordinate
to GATES 1–6.

### GATE 1 — PR OPEN DISCIPLINE
A PR may not be opened until ALL of the following are true:
- Every named subagent has returned a verdict block (or explicitly
  failed dispatch with disclosure)
- Every HIGH or CRITICAL finding has been resolved inline OR
  explicitly escalated to operator
- Required browser verification (if UI changes) completed with
  console + network logs reviewed
- Regression tests have run with verdict (make verify or pytest -k
  targeted suite)
- Forbidden-files check confirms no out-of-scope edits

If any of these is incomplete at PR-open time, BLOCK and report
instead of opening.

### GATE 2 — MAXIMUM OPEN PR COUNT
Hard limit: 3 simultaneous open PRs from this repository.
- If 3 PRs are already open when a new implementation task begins,
  switch to merge-and-review mode: clear at least 1 PR from the
  queue before opening another.
- This applies across sessions. A future session inheriting 3 open
  PRs must close at least 1 before opening a 4th.
- Exception: governance-only / docs-only PRs may stack 1 additional
  beyond the limit (so 3 implementation + 1 docs = 4 max), since
  docs PRs are zero blast radius.

### GATE 3 — BRANCH STATUS DESIGNATION
Every branch must carry one of three explicit status labels:
- ACTIVE: work in progress, may merge to main
- REFERENCE_ONLY: preserved for design history, never merges
- ARCHIVED: frozen, may merge nothing, may delete after retention
  period

Branches that pass salvage audit with "FULL ABANDON" verdict MUST
receive an archive tag of form:
`git tag archive/<branch-name>-<YYYY-MM-DD>`
before being marked ARCHIVED.

A branch with no status designation is treated as ACTIVE by default
and assumed merge-eligible — this is unsafe and must be corrected on
first contact.

### GATE 4 — SALVAGE FINDING DISPOSITION
Every salvage opportunity surfaced by an audit must receive exactly
one of:
- SCHEDULED: filed as a task with a specific target session
- ISSUE: filed as a GitHub issue with appropriate labels
- REJECTED: explicit operator rejection with reasoning logged in
  the audit report

"Recommendation noted" is not a valid disposition. A salvage finding
without disposition becomes lost governance debt.

### GATE 5 — AGENT SUBSTITUTION DISCLOSURE
If a named subagent is not in the current registry, the substituting
agent must:
- Be named explicitly in Section 2 of the final report
- Have capability equivalence stated ("X-detection covers the gap
  identification scope of gap-hunter; X-review covers ADR conformance
  scope of adr-historian")
- Have the registry mismatch logged for follow-up registry repair

Silent substitution is forbidden. A missing agent surfaces as a
disclosure, not as a reduced report.

### GATE 6 — BROWSER VERIFICATION COMPLETENESS
Implementation is not complete until:
- Browser flow tested end-to-end through every modified path
- Console errors checked (no new red entries)
- Network requests verified (no 4xx/5xx on happy path; expected
  errors confirmed on error paths)
- Execution path verified (button click → API call → DB change →
  UI update — full chain)

Code that compiles + passes unit tests is not the same as code that
works in the browser. The latter is the bar for "shipped."

For backend-only changes (no UI surface), this gate is N/A. For
admin endpoints (curl-able but no UI), curl + audit-log verification
substitutes.

### Subordinate-language note

Rule hierarchy and all resolved conflicts: `.claude/contracts/governance-precedence.md`.

Summary: GATES 1–6 supersede operating guidance. The 7-agent deploy gate specialises GATE 1 for
production syncs. Engineering Lessons bind at the specific gate named in each lesson header.
Operating rules and workflow sequences are subordinate to all gates.

---

## MANDATORY OBSERVATION LAYER

These rules govern the meta-agent layer that observes and improves
the rest of the agent system. They are non-negotiable and apply to
every session — including new sessions resuming from cold start.

### RULE 1 — Read PROJECT_STATE.md first

Every new session, **before any task work begins**, must read
`.claude/memory/PROJECT_STATE.md` to load current project state.
This is the source of truth for "where are we in the project right
now." Do not re-derive state from chat history; chat history is
lossy across sessions.

The four mandatory sections (FACTS / DECISIONS / ASSUMPTIONS /
OPEN QUESTIONS) are owned by `flow-context-keeper`. Read all four
before opening a task; the OPEN QUESTIONS section in particular
flags items that the operator may want resolved before new work
fires.

### RULE 2 — `agent-performance-observer` auto-fires

After any task report containing a `FINAL REPORT` section header,
OR any report showing ≥3 distinct subagents in Section 2 "Agents
activated", fire `agent-performance-observer` to produce a
scorecard. Output is stored at
`.claude/memory/scorecards/<YYYY-MM-DD>-<campaign-slug>.md`.

The observer is mandatory regardless of campaign outcome — even
BLOCKED campaigns produce quality signals worth scoring. Silent
observation is no observation.

### RULE 3 — `flow-context-keeper` auto-fires

After `agent-performance-observer` completes, OR after any PR
merges to main, OR after any GitHub issue closes, fire
`flow-context-keeper` to update `.claude/memory/PROJECT_STATE.md`.

The four-section structure (FACTS / DECISIONS / ASSUMPTIONS /
OPEN QUESTIONS) is the load-bearing invariant. FACTS are
append-only — never demoted to ASSUMPTIONS. See
`.claude/agents/flow-context-keeper.md` for the full movement-rule
matrix.

### RULE 4 — Observer can be invoked manually

The operator may invoke `/observe` to force
`agent-performance-observer` to run against the most recent report.
The operator may invoke `/update-state` to force
`flow-context-keeper` to refresh `PROJECT_STATE.md`.

### RULE 5 — Self-evaluation cadence (calendar-driven)

`agent-performance-observer` must self-evaluate on a calendar-driven
cadence. Trigger self-evaluation if:
- The most recent self-eval file (`.claude/memory/scorecards/self-eval-*.md`) is older than 7 calendar days, OR
- The most recent self-eval flagged `SELF-DEGRADATION DETECTED` and this is the 3rd campaign scorecard run since it.

When triggered: read the previous 5 campaign scorecards, score self on the same 6 dimensions, report degradation if any. Output goes to `.claude/memory/scorecards/self-eval-<YYYY-MM-DD>.md`. Self-blind agents degrade silently; the calendar-driven cadence is the system's anti-blind-spot.

### RULE 6 — Observer outputs must be visible

Scorecards must be referenced in subsequent task reports (cite the
file path). `PROJECT_STATE.md` must be readable at the start of
every session. Hidden observation = no observation.

If a task report cites a scorecard, the citation must include the
scorecard's file path so an operator can audit it directly.

Enforcement mechanism: `flow-context-keeper` must record every
scorecard file produced by `agent-performance-observer` in the
FACTS section of `PROJECT_STATE.md`, with date and file path. If
a scorecard exists in `.claude/memory/scorecards/` but is not
cited in PROJECT_STATE.md, that scorecard is invisible to future
operators — RULE 6 has failed.

**NEEDS-TUNING / UNRELIABLE verdicts are GATE 4 salvage findings.**
When `agent-performance-observer` produces a scorecard with any
NEEDS-TUNING or UNRELIABLE verdict, that verdict is structurally
analogous to a salvage finding and MUST receive exactly one
disposition per GATE 4: SCHEDULED, ISSUE, or REJECTED. "Recommendation
noted" is not a valid disposition for an observer verdict either.

### Deferred meta-agents (logged here for traceability)

Two meta-agents are intentionally deferred until two campaigns under
this observation layer establish a baseline:

- `agent-prompt-refiner` — reads scorecards across a 7-day window,
  drafts refined prompts as PRs (never mutates prompts directly).
- `pattern-historian` — scans recent campaign reports for repeated
  patterns and proposes CLAUDE.md amendments or new gates.

Decision criteria + implementation rules captured in the deferred
issue filed alongside the PR that introduces this section.

---

## ANTI-HOLD AND WORKFLOW COMPLETION

These rules govern when a session may stop and what "done" means. They
exist to prevent two opposite failures: (a) stopping prematurely on work
that should have continued autonomously, and (b) drifting onto a second
task before the first is complete. Full checklist, decision table, and
worked examples: `docs/governance/anti-hold-and-completion.md`. In-flight
single-task tracking: `.claude/memory/TASK_STATE.md`.

These rules are **subordinate to GATES 1–6** and to the existing
regression stop-gate (`.claude/hooks/pz-stop-gate.py`): a gate block or a
RED regression is always a valid stop, never overridden by Anti-HOLD.

### The Anti-HOLD principle

Continuing autonomous work is the default. Stopping is the exception and
must be justified by a named HOLD condition. "I could ask the operator"
is not a reason to stop; only the four HOLD conditions below are.

### Claude MAY stop (valid HOLD conditions)

A session may stop and hand back to the operator ONLY when at least one of
these is true. Name the condition explicitly when you stop.

1. **Destructive production action** — the next step would delete,
   overwrite, or irreversibly mutate production data, a live service, or a
   booked external record (wFirma posted PZ, sent email, `C:\PZ`
   robocopy/`reset --hard`, DB drop). Confirm first.
2. **Missing credentials / access** — the task genuinely cannot proceed
   without a secret, token, or access the session does not have and cannot
   safely obtain.
3. **Legal / financial approval** — the action has legal or financial
   consequence requiring human sign-off (booking a value correction,
   sending a customs declaration, money movement).
4. **Unclear business decision** — the task depends on a business choice
   the code, repo, and PROJECT_STATE cannot resolve, where a wrong guess
   has real cost. (A merely technical ambiguity with a sensible default is
   NOT this — pick the default and proceed, noting it.)

### Claude MUST continue (never a valid HOLD)

These are normal autonomous work. Do not stop to ask permission for them:

- **Code inspection / repo search** — reading files, grepping, tracing.
- **Test execution** — running `make verify`, pytest, smoke suites.
- **Local verification** — running the app locally, curling endpoints,
  inspecting on-disk artifacts.
- **Documentation / state updates** — editing docs, PROJECT_STATE.md,
  TASK_STATE.md, scorecards.
- **Non-destructive refactor** — renames, extractions, and edits inside a
  branch that do not touch production or external systems.
- **Opening a PR / committing to a feature branch** — provided GATE 1 is
  satisfied; a draft PR is non-destructive.

### Workflow completion discipline

A task is not done until its completion checklist
(`docs/governance/anti-hold-and-completion.md` §Completion Checklist)
passes. Do not begin a second task while a first is `IN_PROGRESS` in
`.claude/memory/TASK_STATE.md` unless the operator explicitly redirects.
Record a one-line HOLD reason in TASK_STATE.md whenever you stop on a
valid HOLD condition, so the next session can resume without re-deriving
context.

---

## Engineering Lessons (permanent)

Append-only — do not delete prior lessons; supersede with a new dated entry.
Cross-reference: `memory-lessons` agent; `engineering_discipline_rules` auto-memory.
Full origin narratives, detection signals, and worked examples: invoke `engineering-lessons`.

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
Lesson M.

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

### Lesson N — Import, product master, proforma, warehouse receipt, barcode traceability, and sales linkage are SEPARATE authorities (2026-06-22)
**GATE 1 + reviewer-challenge + frontend-flow-reviewer + backend-safety-reviewer.** Six separate authorities (PRODUCT / PROFORMA / IMPORT_PZ / WAREHOUSE / SALES) each own their own gates. Warning → hard blocker requires: (a) named business rule (accounting/customs/duplicate-write/quantity-risk) AND (b) a regression test. Warehouse receipt = operator quantity confirmation, NOT mandatory per-piece scan (unless `serial_controlled=true`). Full detail: invoke `/engineering-lessons`.

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

**Reference**: operator governance directive 2026-06-23 (AWB 9158478722 post-PZ reconciliation); `service/app/api/routes_proforma.py:1000` (`advisory_gates_enabled` advisory routing); `.claude/memory/engineering_lessons.md` Lesson N.

### Lesson N — Import, product master, proforma, warehouse receipt, barcode traceability, and sales linkage are SEPARATE authorities (2026-06-22)

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

---

## Frontend Design Standard

**V1 pages** (`shipment-detail.html`, `dashboard.html`) — frozen except critical fixes (Lesson F). Work governed by `.claude/skills/frontend-design.md`.

**V2 pages** (`proforma-v2.html` and later) — governed by `docs/v2-architecture-plan.md` + Lesson F discipline rules. Authority-clean first, visual polish last.

**Stack (both V1 and V2)**: Vanilla HTML + Babel JSX (no bundler, no TypeScript, no Tailwind). Generic frontend-ui agent defaults to TypeScript + Tailwind — those do not apply here.

Key rules (full detail in skill file):
- Use CSS custom properties (`--bg`, `--text`, `--badge-*`, `--accent`) — never hardcoded hex
- Use shared components from `dashboard-shared.js` (`Btn`, `Badge`, `Card`, `Sel`, `Toast`)
- Every write button must label exactly what it writes; no auto-save
- No fake readiness, no hidden blockers, no duplicate renderers
- Legacy sections in `<details>` — collapsed by default
- Every interactive element needs a `data-testid`

Invoke skill: before any UI implementation, before any `frontend-flow-reviewer` run.

**Design intelligence layer**: `.claude/skills/ui-ux-pro-max` is installed as a supplemental search tool for accessibility, UX guidelines, and layout best practices. It is subordinate to `frontend-design.md`. Use via `python3 .claude/skills/ui-ux-pro-max/scripts/search.py`. Read `EJ_OVERRIDES.md` inside the skill directory before applying any output — stack defaults (Tailwind, TypeScript) do not apply here.

---

## Available integration

Zoho Cliq MCP connector (use for all Cliq operations):
- **Connector ID:** `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`
- **Org ID:** `60014108075`
- **Tool:** `ZohoCliq_Post_message_in_a_channel`
- **Production channel:** `pz` (ID: `O190928000006027001`)

| Path | Tool | Target |
|------|------|--------|
| "Processing…" acknowledgment | webhook (`CLIQ_WEBHOOK_URL`) | bot chat |
| Final batch result | Estrella Cliq MCP → `Post_message_in_a_channel` | `#PZ` channel |
| Resend from dashboard | webhook → `post_to_channel` (OAuth fallback) | `#PZ` channel |

---

## System architecture

- `process_batch()` is the only calculation path. Never recalculate landed cost, freight, duty, totals, or notes outside the Python engine.
- All outputs must render from the same validated `process_batch()` result object.
- Do not treat Cliq as the calculation engine.

> For full architecture detail: invoke `pz-shipment`.

---

## Required workflow

- **Step A:** Run `make verify` before any live batch. If it fails: stop, do not process, report reason.
- **Step B:** Run engine via CLI or `process_batch()`. For CLI syntax and flags: invoke `pz-shipment`.
- **Step C:** Always generate PDF + XLSX. If either absent: treat as failed, report honestly, exit non-zero.
- **Step D:** Post summary + files to Cliq. If amendment flags present: say so explicitly. Do not hide.

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

## Required Cliq posting format

Three scenarios: success, partial (VERIFY-GAP present), and failure. Each must include doc_no, line count, net, gross, and duty totals. Failure messages must state "No final files were posted." Partial messages must list all gaps explicitly. Amendment flags must not be hidden.

> For exact format blocks: invoke `pz-shipment`.

---

## WorkDrive automation flow

Architecture: local storage = truth; WorkDrive REST = primary upload; TrueSync = optional mirror only (NEVER a success condition); Cliq = immediate notification layer. For MCP step sequence: invoke `pz-shipment`.

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

### Architecture

```
Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit
```

Coworker should NOT directly send emails. It returns exact structured data only.

For full architecture, flow, implementation details, and draft type reference: invoke `cowork-integration`.

### Cowork result validation rules

`cowork_result_processor.py` must reject any financial field mutation.

`cowork_action_runner.py` executes only through existing PZ App services.

**Draft validation (cowork_result_processor.py):**
- Type must be in `ALLOWED_DRAFT_TYPES`
- Must NOT contain forbidden fields: `to`, `cc`, `bcc`, `from`, `attachments`, `files`
- AWB in draft must match audit AWB
- Must have `subject` and `body`
- Invalid drafts are dropped (not blocking — evidence still written)

**Draft execution (cowork_action_runner.py):**
- PZ App injects correct recipients from `email_routing.py` based on draft type
- PZ App decides attachments from audit state (never from Cowork)
- PZ App sends via `email_service.queue_email` only
- Sender always `import@estrellajewels.eu`

### Cowork must NEVER directly

- Modify CIF / duty / invoice totals
- Send emails
- Close shipments
- Delete or move emails
- Choose email recipients (PZ App controls routing)
- Attach files to emails (PZ App controls attachments)
- Override sender identity

---

## Short instruction version

> Full operational summary: invoke `pz-shipment`.
