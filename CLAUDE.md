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
SCHEDULED / ISSUE / REJECTED disposition.

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
