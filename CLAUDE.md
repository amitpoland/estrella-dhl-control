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

### Lesson A — Test stubs must match real production return shapes (2026-05-13)
**GATE 1.** Stubs MUST match the real builder return shape; stub authors must read the real function first. Every coordinator/builder PR MUST include a real-builder regression test (no stub) asserting the type contract. Coordinators MUST normalise polymorphic inputs via `_normalise_X`. Post-merge Lesson-A failure → **GATE 4** salvage (SCHEDULED / ISSUE / REJECTED).

### Lesson B — Mid-session git pull does NOT reliably refresh the subagent_type registry (2026-05-13)
**GATE 5.** New agent files added mid-session are NOT guaranteed invocable; treat as "available next session." Post-merge validation for agent-adding PRs MUST report VALIDATION-FAILED if the new agent cannot be dispatched. Silent meta-agent substitution is FORBIDDEN; escalate instead. Restart session after any agent-adding merge.

### Lesson C — Observer scorecard writes must be orchestrator-verified post-write (2026-05-13)
**RULES 2 + 6.** Orchestrator MUST verify the scorecard file exists on disk after the observer agent returns — not just self-reported. Missing file → dispatch FAILED; re-fire or escalate. `flow-context-keeper` MUST validate every cited scorecard exists before the run completes; citing an absent file is a RULE 6 violation.

### Lesson D — LOCAL-COMMIT-ONLY deploys must be disclosed and reconciled (2026-05-13)
**7-AGENT GATE.** Any LOCAL-COMMIT-ONLY deploy MUST include a disclosure header (SHA, "GitHub PR: NONE", bypass reason, reconciliation plan) before sync commands, visible to operator before any sync. Operator MUST acknowledge. Reconciliation PR MUST be filed before the next `git pull --ff-only origin main`. Every such deploy appends to `.claude/memory/local-commit-deploys.jsonl`.

### Lesson E — Background email automation requires five mandatory safety properties (2026-05-18)

**Origin**: MacBook `pz-launcher.py` incident (2026-05-18). A launchd agent running since
2026-05-10 held live SMTP credentials, ran live dev source on `0.0.0.0:8000`, and was
capable of sending real outbound emails from a dev/local process with no isolation from
production state. Contained by `launchctl unload` + plist disablement.

**Binding rule** — every background email automation (scheduler, launchd agent, cron,
cowork pipeline, follow-up SLA runner, or any process that may call `queue_email` or
`send`) MUST implement all five properties before being deployed:

1. **Execution-time validation** — validate shipment state, AWB, recipients, and
   attachment integrity at the moment the email is about to send, not just at schedule
   time. State may have changed between scheduling and execution.

2. **Idempotency** — a given email event (identified by AWB + email type + date window)
   must be sendable exactly once. Duplicate detection must be checked immediately before
   send, not only at enqueue time.

3. **Terminal-state suppression** — if the shipment is in a closed, cancelled, or
   otherwise terminal state at execution time, abort the send and log the suppression.
   Never rely on the caller to have checked terminal state earlier.

4. **Replay safety** — if the process restarts, crashes, or replays a queue, already-sent
   emails must not be re-sent. Sent state must be durably written before the send call
   returns, and checked on every replay path.

5. **Environment isolation** — dev, staging, and local processes must not send real SMTP
   emails. Environment must be asserted at startup (not inferred). A process without an
   explicit `ENV=production` guard must refuse to connect to the live SMTP server.

**Where it binds**: every new scheduler, launchd/cron/NSSM job, cowork pipeline action
runner, SLA follow-up service, or any module that imports `email_service`, `queue_email`,
or `smtplib`; every code review of background automation; every deploy gate where an
email-capable service is being restarted.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson E;
2026-05-18 containment: `launchctl unload ~/Library/LaunchAgents/eu.estrellajewels.pz-service.plist`,
plist moved to `~/LaunchAgent-Disabled/eu.estrellajewels.pz-service.plist.disabled`.

### Lesson J — Root-level engine files are outside the standard `service/app` robocopy (2026-05-22)

**7-AGENT GATE + Gate 7.** Origin: PR #295 (polish-desc Windows fonts). The standard `/deploy` robocopy syncs `service/app → C:\PZ\app` only. Repo-root engine files (`polish_description_generator.py`, `pz_import_processor.py`) deploy to `C:\PZ\engine\` and require a SEPARATE `robocopy "<repo>" "C:\PZ\engine" <file> /COPY:DAT` command. Without it, the engine binary stays stale while the rest of the deploy lands — silent skew between validator (deployed) and generator (stale).

**Binding rule** — every PR touching files outside `service/app/**`:
1. PR body MUST declare the additional sync command, not just file paths
2. `deploy_release_manager` (Gate 7) MUST walk the modified-file list and surface any file outside `service/app/**` against the deploy layout map
3. Deploy verification MUST file-content grep the deployed file (`Select-String`), NOT Python-import a symbol — symbols can survive a stale deploy
4. Generator/renderer changes need practical end-to-end verification (generate a real output via deployed code path, inspect it)
5. `flow-context-keeper` records engine-file syncs separately under FACTS

**Deploy layout map**: `service/app/**` → `C:\PZ\app\**` ✓ standard · root `polish_description_generator.py` / `pz_import_processor.py` → `C:\PZ\engine\` ✗ explicit sync required · `service/requirements.txt` declared not synced · `.claude/**`, `service/tests/**`, repo docs not deployed.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson J; PR #295 (`fix/polish-desc-windows-fonts-and-validator` → squash-merge `926ed2f` at 2026-05-22).

### Lesson I — Production incidents must become workflow-class rules, never shipment-specific patches (2026-05-22)

**GATE 1 + reviewer-challenge.** Origin: Global Jewellery PZ campaign (PRs #269–#283). Six workflow-class failures were exposed by one batch and resolved as permanent workflow hardening.

**Six workflow failures, all shipment-class:**
1. Product names created from stale authority (cached description, not invoice-position authority)
2. PZ manually deleted in wFirma; audit mapping lost after `/process` run
3. `clear-mapping` idempotency used wrong authority (`wfirma_export` field, not timeline)
4. `pz_create` guard did not understand `PZ_RECONCILED` lifecycle state
5. UI showed contradictory banners simultaneously (multi-authority rendering)
6. Compact audit notes missing from PZ description field

**Six-step execution framework (apply before every incident fix):**

**Step 1 — Classify** (before touching code):

| Observation | Classification |
|---|---|
| Wrong data generated | Authority chain |
| Data lost after generation | Persistence / recovery |
| Conflicting statuses | Lifecycle state machine |
| Operator confusion | Single authority renderer |
| Manual external intervention | Reconciliation workflow |
| Repeat operator action | Automation candidate |
| Supplier-specific parsing | Supplier authority module |
| Missing audit evidence | Notes / evidence layer |

**Step 2 — Find authority owner.** Which system owns truth? No code before this is named. Candidates: Invoice · Customs · Warehouse · Sales · Customer Master · Product Master · PZ lifecycle · wFirma · DHL.

**Step 3 — Cardinal question:** "What workflow class allowed this to happen, and how do we make that class impossible or self-recovering?"

**Step 4 — Convert to platform behavior.** Fix must produce: authority rule · lifecycle state · recovery path · guard · validation · automation · regression test.

**Step 5 — Verify broader impact.** "Can this affect another shipment / supplier / warehouse / customs / accounting flow?" If yes, fix at workflow level.

**Step 6 — Closure requirements** (campaign only closed when all six pass):
- Root cause (one sentence)
- Authority owner named
- Workflow class named
- Recovery path verified end-to-end
- Regression tests added (synthetic audits, not batch-specific files)
- Existing workflows verified unaffected

**Incident classification (triage before coding):**

| Incident type | Fix target |
|---|---|
| Wrong data generated | Authority chain |
| Data lost after generation | Persistence / recovery |
| Conflicting statuses | Lifecycle state machine |
| Operator confusion | Single authority renderer |
| Manual external intervention | Reconciliation workflow |
| Repeat operator action | Automation or guided workflow |
| Supplier-specific parsing | Supplier authority module |
| Audit/compliance visibility | Notes / evidence layer |

Complete this sentence before opening a code file: *"This is a [bucket] incident. The fix target is [component]. The workflow class is [description]. Another batch could hit this if [condition]."* If the sentence cannot be completed, root cause is not understood — do not code.

**Cardinal question:** "What class of workflow allowed this to happen, and how do we make that class impossible in the future?" Not: "How do we fix this shipment?"

**Enforcement**: reviewer-challenge fires automatically on every incident-driven PR. A PR that names only the incident batch without naming a workflow class and adding regression tests is incomplete by this lesson.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson I; operator governance statements 2026-05-22.

### Lesson F — V2 frontend migration requires frozen V1 and strict authority isolation (2026-05-20)

**GATE 1 + V1-FREEZE.** Origin: MASTER-CLOSE-AND-START-V2 architectural directive.

**Binding rules — enforced on every V2 PR and every `shipment-detail.html` PR:**

1. **V1 is frozen.** `shipment-detail.html` and `dashboard.html` accept critical fixes only (production broken or data at risk). No new features, tabs, rendering surfaces, or refactors while V2 is being built. Any PR touching these files triggers reviewer-challenge automatically.

2. **Do not evolve V1 and V2 simultaneously.** Enterprise migrations fail precisely because teams keep both generations moving. The freeze is what makes the migration work.

3. **ONE PAGE = ONE DOMAIN AUTHORITY.** Every V2 page owns exactly one business domain. If a proposed V2 change requires touching another domain's APIs or state, it belongs on a different page.

4. **NO PAGE MAY OWN ANOTHER PAGE'S BUSINESS LOGIC.** Proforma logic stays in proforma-v2. PZ logic stays in pz-v2. Cross-page logic goes into the shared layer (transport → normalization → primitives), never into a page component.

5. **Shared layer responsibility is bounded and asymmetric — `dashboard-shared.js` and `pz-state.js` have absolute forbidden zones:**

   - `pz-api.js` — transport only. No business logic, no state, no rendering.
   - `pz-state.js` — ALLOWED: normalize, cache, derive UI-friendly structure, coordinate view state. FORBIDDEN: silently decide workflow legality; redefine accounting readiness; reinterpret customs truth; bypass backend authority. Business legality stays backend-authoritative. The frontend reflects truth; it does not produce it.
   - `pz-components.js` — rendering primitives, domain-aware, stateless. No fetching, no workflow decisions.
   - `dashboard-shared.js` — visual atoms only (Badge, Card, Btn). MUST NEVER gain domain knowledge of any kind — shipment states, customs rules, PZ readiness, wFirma semantics are all forbidden. Once visual primitives know domain state, every importing page becomes coupled and V2 collapses back into V1.

6. **Authority-clean before visual polish.** Build in order: deterministic → inspectable → authority-clean → workflow-safe → cache-safe → deployment-safe → visually polished. Do not skip ahead to polish.

7. **Dashboard-v2 is built last.** It aggregates domain pages; those domain pages must be stable authority surfaces first. Building dashboard-v2 early means depending on unstable contracts — exactly how V1 fragmentation started.

8. **The first Proforma V2 implementation PR is the critical review moment.** That is where delivery pressure first appears to shortcut the layer rules. Reviewer-challenge MUST fire on any V2 PR automatically. Block any PR containing: V1 logic imported into V2; state hook computing `ready:true/false` locally; `dashboard-shared.js` receiving domain props (`shipmentStatus`, `clearancePath`, etc.); proforma page calling DHL or warehouse APIs; any `// TODO: refactor later` on a layer-blurring line.

**Danger phrases in PR descriptions — treat as review flags requiring explicit layer-rule justification before merge:**
> "temporarily" / "quick fix" / "reuse this renderer" / "one more section" / "copy this state logic"

**Forbidden patterns (reviewer-challenge must reject these in V2 PRs):**
- Reusing a V1 renderer directly in a V2 page
- Duplicating state transforms from V1 "temporarily"
- Adding a section to `shipment-detail.html` instead of building the V2 page
- Mixing two domain authorities in a single V2 page component
- Auto-saving, auto-fetching on mount without explicit operator action

**Where it binds**: every V2 page PR; every `shipment-detail.html` PR; every `dashboard-shared.js` PR; every new file in `app/static/` that touches proforma/PZ/customs/warehouse domains. Full detail: `docs/v2-architecture-plan.md` §9 (first V2 PR review gate).

**Reference**: `docs/v2-architecture-plan.md` (full spec, authority map, phase plan, discipline rules).

### Lesson G — Generated-artifact stale-display bugs are first a cache / atomicity problem, not a generator problem (2026-05-21)

**Origin**: Global Jewellery AWB 4789974092 Polish Description regeneration incident. Operator
repeatedly reported "the stale PDF keeps returning after delete and regenerate." Three diagnostic
passes patched the wrong layer (audit cache, packing rows, documents.db) before browser-side
header inspection revealed `Cache-Control: max-age=14400` — FastAPI's `FileResponse` default of
4-hour browser caching. The on-disk file was always correct; the browser was serving its cached
copy. PR #265 fixed the actual cause.

**Binding rule** — when any generated artifact (PDF / XLSX / JSON export) appears stale after a
delete-and-regenerate cycle, follow this checklist BEFORE patching the generator:

1. **Inspect the disk artifact first.** Read directly from the file path, bypass HTTP.
   If on-disk content is correct, stop suspecting the generator.

2. **Walk the reference layers in order**:
   disk file → audit pointers → registry rows (`documents.db`, `packing.db`, …) →
   download-endpoint resolver → HTTP response headers → browser cache.
   Do not patch layer N without ruling out layers 1..N-1.

3. **When disk content is correct but rendered output is old, root cause is almost always
   HTTP / browser caching.** The download endpoint MUST set
   `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` + `Pragma: no-cache` +
   `Expires: 0`. FastAPI's `FileResponse` default of multi-hour caching is a footgun for any
   regenerable artifact.

4. **Overwrite-safe generation (validate-then-rollback)** for every fixed-filename
   generator: write file → validate against forbidden-token list → on hit unlink + return
   422 + do NOT update audit pointers → on success atomically replace + update audit
   pointers (including `<artifact>_generated_at` timestamp). Audit pointer update MUST be
   the LAST step.

5. **Regression test** pinning that the download endpoint emits `no-store` and the
   generation path runs validate-then-rollback before audit update.

**Where it binds**: every generated artifact + download endpoint. Apply to Polish Description,
PZ PDFs, PZ Calc XLSX, Audit EN/PL, Memo PDFs, Corrections PDFs, Proforma PDFs, DSK PDFs,
SAD-ready JSON, and any other DHL / customs / wFirma generated outputs that share a filename
across regenerations.

**Do not solve future stale-output bugs by manual file deletion only.** Deletion masks the
symptom; the cache / atomicity gap remains.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson G (full detail, 5 properties +
detection signals); PR #265 (cache headers + validate-then-rollback in `routes_dhl_clearance.py`
`download_dhl_file` + `generate_description`); `service/tests/test_polish_desc_cache_and_overwrite.py`
(11 tests pinning the contract); PR #260 + #261 (wrong-layer patches that the checklist would
have prevented).

### Lesson K — Agent prompt templates with broad tool grants must include explicit negative-scope language (2026-05-23)

**GATE 5 + orchestrator prompt composition.** Origin: PR #303 + PR #304 sequence — 4 consecutive data points 2026-05-23. Same `release-manager` agent, same Bash/gh/sc.exe grants: exhibited scope drift (autonomous `gh pr merge`) when prompt said "verdict only" implicitly; respected boundary when prompt said "DO NOT call gh / Bash / sc.exe — verdict only" explicitly. Pattern reproducible in both directions; prompt-template specificity is the corrective mechanism, not agent substitution.

**Binding rule** — every prompt template dispatched to an agent with write-capable tool grants (Bash, Write, Edit, gh, sc.exe, robocopy, MCP write tools, POST/PUT/DELETE) MUST include explicit negative-scope language naming specific forbidden commands or tool families. Generic phrasing ("verdict only", "just review") is INSUFFICIENT. Required form: `"Verdict only — DO NOT call <named command 1>, <named command 2>, ..."`. Forbidden-command list MUST cover every write-capable tool in the grant set (grant-set parity). Every `.claude/agents/*.md` with a write-capable grant MUST include a "Boundary clause" section enumerating default forbidden actions. Post-violation: GATE 4 salvage finding (SCHEDULED / ISSUE / REJECTED) — correct outcome from out-of-scope action is the failure mode this lesson exists to prevent.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson K; scorecards `2026-05-23-pr303-merge-gate-register-one-refit.md` (DP1 drift), `2026-05-23-pr303-deploy-register-one-pending-adoption.md` (DP2 corrected), `2026-05-23-pr304-merge-gate-pending-adoption-ui.md` (DP3 sustained), `2026-05-23-pr304-deploy-pending-adoption-ui.md` (DP4 sustained).

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
