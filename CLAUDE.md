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
6. `deploy_qa_reviewer.md` — test pass/fail (160/160 PZ, 366/366 carrier)
7. `deploy_release_manager.md` — branch hygiene, rollback command

Production: `C:\PZ` | Service: `PZService` (NSSM, port 47213) | Public: `https://pz.estrellajewels.eu`

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

The "Production deployment rule (PERMANENT)" section above (the
7-agent gate) is a **specialisation of GATE 1** for production
deploys: it adds named-agent + named-test requirements but does not
relax any GATE-1 condition. Where the two could be read in tension,
GATE 1 controls.

The "Operating rules" and "When asked to run a shipment" sections
below are operational guidance — subordinate to GATES 1–6. If a
shipment-run step would skip a GATE check, the GATE wins.

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

Binding rules learned from real campaigns. Each lesson cites its
origin (PR / commit / agent verdict) and states the rule that
should prevent recurrence. Full text + detection signals + work-
arounds live in `.claude/memory/engineering_lessons.md`. The
summaries below are the binding-rule layer that every implementing
agent and reviewer must apply.

This section is append-only. Do not delete prior lessons; supersede
with a new dated entry instead. Cross-reference: see also
`memory-lessons` agent (`.claude/agents/memory-lessons.md`) and the
`engineering_discipline_rules` auto-memory entry for related
discipline patterns.

**Enforcement surfaces**: Lesson A binds at GATE 1 (PR open
discipline — real-builder regression test is a precondition;
integration-boundary owns the verdict, testing-verification
adds the test, backend-safety-reviewer flags missing
`_normalise_X` boundary helpers). Lesson B binds at GATE 5
(substitution disclosure — meta-agent substitution forbidden) and
at the orchestrator's first-task-of-session diagnostic. A Lesson-A
failure detected AFTER merge is a GATE 4 salvage finding requiring
SCHEDULED / ISSUE / REJECTED disposition.

### Lesson A — Test stubs must match real production return shapes (2026-05-13)

**Origin**: PR #46 W-5 P2 proactive customs dispatch; integration-
boundary canonical agent flagged a CRITICAL type-contract bug that
37 unit tests had masked.

**Binding rule**:
1. Synthetic test stubs MUST match the real production function's
   return shape (str vs List[str] vs dict). Stub authors must read
   the real function before writing the stub.
2. Every PR that wires a coordinator/consumer to a builder MUST
   include at least one regression test that exercises the REAL
   builder (no stub) and asserts the type contract directly.
3. Coordinators/consumers MUST normalise polymorphic inputs at the
   boundary via a `_normalise_X` helper rather than assuming a
   single shape.
4. "Tests pass but production breaks" on a stub/real mismatch is a
   Lesson-A failure; add the real-builder regression test in the
   same PR.

**Where it binds**: every coordinator/builder/consumer wiring in
W-5 P3/P4/P5 and beyond, every test fixture that approximates a
service boundary, every code review of a coordinator that imports
a builder.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson A;
canonical regression test
`service/tests/test_dhl_proactive_dispatch_p2.py::test_real_builder_to_field_is_str_not_list`.

### Lesson B — Mid-session git pull does NOT reliably refresh the subagent_type registry (2026-05-13)

**Origin**: PR #41 meta-agent observation layer foundation; post-
merge validation could not dispatch the newly-merged
`agent-performance-observer` and `flow-context-keeper` even though
both files were on disk.

**Binding rule**:
1. A new agent file added via `git pull` mid-session is NOT
   guaranteed to be invocable in the same session. Treat as
   "available next session, not this one."
2. Post-merge validation tasks for agent-adding PRs MUST report
   VALIDATION-FAILED if the new agent cannot be dispatched in the
   post-merge session, even when all other steps succeed. Refresh
   sometimes succeeds (PR #35 precedent); the rule mandates
   *validating dispatch*, not assuming failure.
3. For the meta-agents (`agent-performance-observer`,
   `flow-context-keeper`), silent substitution is FORBIDDEN per
   GATE 5; escalate instead.
4. Operator should restart the Claude Code session after any PR
   that adds new agent files merges, before launching the next
   campaign that depends on those agents.

**Where it binds**: every PR that creates `.claude/agents/*.md` or
`~/.claude/agents/*.md`; every "post-merge validation" or "fresh-
session smoke" task; the first task of every session that follows
an agent-adding merge.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson B;
this PR's first dispatch (campaign
`chore/observation-layer-verification-and-lessons`) confirmed both
meta-agents are dispatchable in the current session, closing the
prior VALIDATION-FAILED signal.

### Lesson C — Observer scorecard writes must be orchestrator-verified post-write (2026-05-13)

**Origin**: PR #50 silent-loss anomaly; observation-layer audit closure
task. `agent-performance-observer` reported `SCORECARD WRITTEN: <path>`
but the file never reached disk. Confirmed recurrence in the audit-
closure run itself (intermittent silent loss).

**Binding rule**:
1. Orchestrator MUST verify the scorecard file exists on disk after
   the observer agent returns (`ls` or `Read` of expected path) BEFORE
   composing final report or dispatching downstream consumers.
2. If the file is missing, treat the dispatch as FAILED — re-fire OR
   escalate. Do not silently rely on the observer's self-reported
   success.
3. Meta-agent prompts SHOULD use absolute paths derived from the
   orchestrator's repo root, not relative paths that depend on agent
   runtime cwd.
4. Meta-agent prompts SHOULD include a post-write Read self-verification
   step. Agent reports `SCORECARD WRITTEN AND VERIFIED: <path>` only
   after both succeed.
5. `flow-context-keeper` MUST validate every scorecard cited in
   PROJECT_STATE.md FACTS exists on disk before the keeper run
   completes. Citing a non-existent file is a RULE 6 violation.

**Where it binds**: every dispatch of `agent-performance-observer`
(RULE 2 auto-fire OR `/observe`); every dispatch of
`flow-context-keeper` that cites scorecards (RULE 3 auto-fire OR
`/update-state`); every meta-agent that produces file artefacts;
every code review of new meta-agent definitions.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson C;
retroactive scorecard
`.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md`;
gap-hunter root-cause hunt verdict
(ROOT-CAUSE-INCONCLUSIVE / SYSTEMIC-ISSUE-DETECTED, MEDIUM).
Future hardening proposal: amend
`.claude/agents/agent-performance-observer.md` to require absolute
Write target + post-Write Read self-verification (tracked as OPEN
QUESTION in PROJECT_STATE.md, decision pending operator).

### Lesson D — LOCAL-COMMIT-ONLY deploys must be disclosed and reconciled (2026-05-13)

**Origin**: Wave 1 closure cycle (2026-05-13). SHA `4c797e4`
deployed to Windows production via inline 7-agent gate + robocopy
without a GitHub PR. Deploy was sound (all smokes passed) but the
SHA had no public PR trail — invisible to GitHub audit. Discovered
post-deploy via SHA lineage verification (`git log 0b4e381..4c797e4`
returned only `4c797e4`; `git merge-base` confirmed divergence).
`deploy_release_manager` did not flag the deviation. The gap was
codified as Lesson D during the Wave 1 governance closure cycle.

**Gate types distinguished**:
- *PR gate*: SHA lands on `origin/main` via GitHub PR. Publicly auditable.
- *Inline gate (LOCAL-COMMIT-ONLY)*: SHA on local working tree only. 7-agent review
  runs, code ships via robocopy, but no GitHub PR trail exists. Both involve agent
  review; the distinguishing fact is whether the SHA has a public PR trail.

**Binding rule**:
1. Any LOCAL-COMMIT-ONLY deploy must include a disclosure header at
   the top of the gate report (before sync commands): SHA, "GitHub PR: NONE",
   bypass reason, reconciliation plan. Visible to operator before any sync executes.
2. Operator must explicitly acknowledge the disclosure before sync proceeds.
3. Reconciliation PR must be filed and merged before the next
   `git pull --ff-only origin main` on the same production machine.
4. Reconciliation PR body must confirm byte-identical content via
   `git diff <local-sha> <reconcile-pr-head> -- service/app/`.
5. Every LOCAL-COMMIT-ONLY deploy appends an entry to
   `.claude/memory/local-commit-deploys.jsonl` (see schema there).

**Valid bypass reasons** (enumerated; all others trigger escalation):
production incident timing, operator on production-only machine,
toolchain failure preventing PR creation.

**Invalid**: convenience, speed preference, avoiding CI, review friction.

**Where it binds**: every 7-agent gate call where `git log origin/main..HEAD`
returns commits; `deploy_release_manager.md` § Branch hygiene item 5
(detection logic already embedded); orchestrator pre-sync checklist.

**Reference**: `.claude/memory/engineering_lessons.md` Lesson D;
`docs/governance/lesson-d-local-commit-only-deploys.md`;
`.claude/memory/local-commit-deploys.jsonl`;
Wave 1 closure scorecard `.claude/memory/scorecards/2026-05-13-wave1-deploy-closure.md` § 4.

---

## Available integration

The Zoho Cliq MCP connector for Estrella is:
- **Connector ID:** `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`
- **Org ID:** `60014108075`
- **Tool:** `ZohoCliq_Post_message_in_a_channel`
- **Production delivery target:** channel `pz` (ID: `O190928000006027001`)

Always use that connector when the workflow requires posting results or updates into Zoho Cliq.

### Delivery split

| Path | Tool | Target |
|------|------|--------|
| "Processing…" acknowledgment | webhook (`CLIQ_WEBHOOK_URL`) | bot chat |
| Final batch result | Estrella Cliq MCP → `Post_message_in_a_channel` | `#PZ` channel |
| Resend from dashboard | webhook → `post_to_channel` (OAuth fallback) | `#PZ` channel |

---

## System architecture

### 1. Source of truth

`process_batch()` is the only calculation path. Never recalculate landed cost, freight, duty, totals, or notes outside the Python engine.

### 2. Output renderers

All outputs must render from the same validated `process_batch()` result object.

### 3. Zoho Cliq role

Do not treat Cliq as the calculation engine.

> For full architecture detail: invoke `pz-shipment`.

---

## Required workflow

### Step A — Validate engine before live batch

Before processing a live shipment, run `make verify`. If it fails: stop, do not process the batch, report failure reason.

### Step B — Process uploaded shipment

Run the engine via CLI or `process_batch()`. For CLI syntax and optional flags: invoke `pz-shipment`.

### Step C — Generate outputs

Always generate: final PZ PDF + calculation XLSX. If either is not produced when requested: treat the run as failed, report failure honestly, exit non-zero.

### Step D — Post results to Zoho Cliq using "Estrella Cliq"

After successful processing: post a concise summary into Cliq, attach or send the generated PDF and XLSX. If there are amendment flags or verification failures: say so explicitly in the Cliq message, do not hide them.

---

## Financial rules (must never change)

### Freight allocation

Freight and insurance are allocated proportionally by value within each invoice.
Never allocate freight by piece count.

### Duty allocation

Duty is never assumed as a fixed customs %.
Duty must always come from ZC429 / A00 Kwota należnej opł., then distributed proportionally across rows by before-duty value.

### VAT

B00 VAT is reference-only and not included in landed cost.

### Notes / UWAGI

Build from the engine only. Do not reconstruct independently.

Dynamic note 4 logic:
- if art33a → `Import towarów rozliczany zgodnie z art. 33a ustawy o VAT.`
- else if agent exists → `Odprawa celna przez: <agent>`
- else if carrier provided → carrier
- else fallback

Also include: `Koszty frachtu i cła rozliczono proporcjonalnie do wartości pozycji.`

---

## Verification rules

The engine returns structured verification. Treat verification states exactly as follows:
- `True` = verified
- `False` = confirmed mismatch
- `None` = could not verify from SAD format

If a check is `None`, it may produce a correction log line prefixed with `[VERIFY-GAP]`.
This is visible to humans, not a mismatch, and not an amendment flag by itself.

### Amendment flags

Escalate only on confirmed `False`, not on `None`.

### Strict mode

If `--strict-match` is enabled: any confirmed mismatch must fail the run.

---

## Required Cliq posting format

Three scenarios: success, partial (VERIFY-GAP present), and failure. Each must include doc_no, line count, net, gross, and duty totals. Failure messages must state "No final files were posted." Partial messages must list all gaps explicitly. Amendment flags must not be hidden.

> For exact format blocks: invoke `pz-shipment`.

---

## WorkDrive automation flow

### Architecture (permanent — do not revert)

```
Local storage  = source of truth
WorkDrive REST = primary cloud upload  (via workdrive_uploader.py)
TrueSync       = optional convenience mirror only — NEVER a success condition
Cliq           = notification layer — posts immediately, never waits for WorkDrive
Audit          = final record
```

> For the full MCP step sequence and Cliq posting format variants: invoke `pz-shipment`.

### Rules

- **Never search WorkDrive for files** — resource IDs come from the API response
- **Never wait for TrueSync** — TrueSync is an optional mirror, not a cloud upload path
- **Never block Cliq notification** because WorkDrive failed — always post immediately
- **Never send local file paths or localhost URLs** in Cliq
- TrueSync folder = convenience backup only; its visibility state is irrelevant to PZ outcome
- If share link creation fails: report it explicitly, state "WorkDrive pending retry"

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

Do this in order:
1. confirm inputs are present
2. run verification gate (`make verify`)
3. call `/api/v1/pz/process` (without `post_to_cliq`)
4. read `workdrive_pdf_resource_id` + `workdrive_xlsx_resource_id` from the response
5. if resource IDs present → create WorkDrive share links via `ZohoWorkdrive_createExternalShareLink`
6. post concise result + links (or "WorkDrive pending") via Estrella Cliq to `#PZ`
7. surface mismatches or verification gaps honestly

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

```
Use the Claude connector named "Estrella Cliq" only for messaging and file return.
Keep all calculations in the Python engine via process_batch().
For every shipment: run make verify, process invoices + ZC429, generate both PDF and XLSX,
and post a concise summary plus both files back to Cliq.
Treat A00 as the only duty source, allocate freight and duty proportionally by value,
preserve three-state verification (True / False / None+[VERIFY-GAP]),
and fail honestly if any requested deliverable is not produced.
```
