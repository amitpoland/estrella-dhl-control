---
name: engineering-lessons
description: >
  Binding engineering lessons from real production campaigns (A–E).
  Each lesson states what broke, why, the permanent rule that prevents
  recurrence, and where in the governance gates it binds. These are
  append-only. Invoke when writing test stubs, wiring coordinators to
  builders, adding new agent files, producing scorecard artefacts,
  preparing LOCAL-COMMIT-ONLY deploys, or building background email
  automation.
triggers:
  - "test stub"
  - "builder wiring"
  - "type contract"
  - "subagent registry"
  - "agent dispatch"
  - "scorecard write"
  - "local commit"
  - "local-commit-only"
  - "engineering lessons"
  - "lesson A"
  - "lesson B"
  - "lesson C"
  - "lesson D"
  - "lesson E"
  - "background email"
  - "email automation"
  - "scheduler"
  - "launchd"
  - "email safety"
---

# Engineering Lessons (permanent)

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

## Lesson A — Test stubs must match real production return shapes (2026-05-13)

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

## Lesson B — Mid-session git pull does NOT reliably refresh the subagent_type registry (2026-05-13)

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

## Lesson C — Observer scorecard writes must be orchestrator-verified post-write (2026-05-13)

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

## Lesson D — LOCAL-COMMIT-ONLY deploys must be disclosed and reconciled (2026-05-13)

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

## Lesson E — Background email automation requires five mandatory safety properties (2026-05-18)

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
