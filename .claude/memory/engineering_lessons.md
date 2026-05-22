# Engineering Lessons (permanent)

Lessons captured here are binding rules learned from real campaigns. Each lesson cites its origin (PR / commit / agent verdict) and states the rule that should prevent recurrence.

This file is owned by the orchestrator and may be appended to after any campaign that surfaces a permanent lesson. Do not delete prior lessons; supersede with a new dated entry instead.

Cross-reference: `CLAUDE.md` "Engineering Lessons (permanent)" section mirrors the binding rules in summary form.

---

## Lesson A — Test stubs must match real production function signatures and return shapes (2026-05-13)

**Origin**: PR #46 (W-5 P2 proactive customs dispatch). Integration-boundary canonical agent flagged a CRITICAL type-contract bug during pre-merge review.

**What happened**

The P2 coordinator wired `dispatch_proactive` to consume the existing `build_dhl_proactive_dispatch` builder. The builder's real return shape for `pkg["to"]` is a **comma-separated string** (output of `email_routing.resolve_dhl_to()`). The coordinator's first implementation did:

```python
recipient = ",".join(pkg.get("to") or [])
```

The 37 unit tests for the coordinator stubbed the builder with `_stub_pkg(to=["odprawacelna@dhl.com"])` — a `List[str]`. Under the stub, `",".join([...])` produced a clean `"odprawacelna@dhl.com"`. Under the real builder, `",".join("odprawacelna@dhl.com")` would iterate over **characters** and produce a corrupt `"o,d,p,r,a,w,a,c,e,l,n,a,@,d,h,l,.,c,o,m"` recipient that would silently fail at SMTP delivery time.

All 37 tests passed; the bug shipped past testing-verification, security-write-action, and backend-safety reviews. Only integration-boundary's whole-graph audit caught it.

**Binding rule** (apply to every PR that introduces a new coordinator / builder / consumer wiring):

1. **Synthetic test stubs MUST match the real production function's return shape.** If the real function returns `str`, the stub returns `str`. If it returns `List[str]`, the stub returns `List[str]`. Stub authors must read the real function before writing the stub.

2. **Integration-boundary tests MUST include at least one real-builder path when the real builder is available.** Add a test that does NOT stub the builder; it asserts the type contract directly:
   ```python
   def test_real_builder_returns_expected_type():
       pkg = build_dhl_proactive_dispatch(audit, batch_id="X")
       assert isinstance(pkg["to"], str), f"resolve_dhl_to() returns str; got {type(pkg['to']).__name__}"
   ```

3. **Coordinators/consumers MUST normalise polymorphic inputs at the boundary.** Add a `_normalise_recipient` (or equivalent) helper that handles both `str` and `List[str]` and produces the canonical downstream shape. Don't assume — convert.

4. **Do not allow tests to mask `str` / `list` / payload-shape mismatches.** When a finding shows up as "test passes but production breaks," it is a Lesson-A failure. Add the real-builder regression test in the same PR.

**Where the rule binds**:
- All future P3, P4, P5 coordinator wiring that consumes builder packages
- Any new builder/consumer pair across W-5, W-6, future workstreams
- Any test fixture that approximates a service boundary
- Code review checklist when reviewing a coordinator that imports a builder
- **Pattern, not example**: `_normalise_recipient` is the W-5 P2 instance; the same rule applies to `process_batch` result-object consumers in PZ renderers (`_normalise_line_items`), wFirma idempotency-key consumers (`_normalise_idempotency_key`), Cowork action runner consuming Cowork result processor (already a documented coordinator/consumer pair), and any future builder/consumer wiring.

**Network-bound boundary carve-out**:
- The "real-builder regression test" requirement applies to **in-process builders** (pure-Python functions inside the service).
- For network-bound boundaries (DHL Express API, wFirma API, SMTP, Zoho Cliq) where a real-builder test would require live credentials and violate test isolation, substitute a **contract test against a recorded response fixture**: capture a real response once (with a real call, in a one-off integration test gated by env var), store it as a fixture, and assert that production code consumes the fixture's actual shape.
- The carve-out is NOT an escape hatch: contract tests must still exercise the type contract that production code depends on. Without a contract test, the boundary is uncovered by Lesson A and any failure becomes a GATE 4 salvage finding.

**Post-merge failures**:
- A Lesson-A failure detected AFTER merge is a **GATE 4 salvage finding** requiring SCHEDULED / ISSUE / REJECTED disposition. "Recommendation noted" is not a valid disposition.

**Detection signals**:
- A PR's tests use stubs for the immediate dependency but no test exercises the real function
- A coordinator imports a builder and consumes its return value with `",".join(...)`, `format_X(...)`, or other polymorphic-iteration syntax without a normaliser
- Type hints are missing or are `Any` / `dict` on the boundary

**Reference**: integration-boundary verdict on PR #46 (commit `de1cc80` applied the inline fix); regression test `test_real_builder_to_field_is_str_not_list` in `service/tests/test_dhl_proactive_dispatch_p2.py` is the canonical example of the rule's enforcement test.

---

## Lesson B — Mid-session git pull does NOT reliably refresh Claude Code's subagent_type registry (2026-05-13)

**Origin**: PR #41 (meta-agent observation layer foundation). Post-merge validation task attempted to dispatch the newly-merged `agent-performance-observer` and `flow-context-keeper` agents via the Task tool and received `Agent type 'agent-performance-observer' not found` errors, even though the agent files were verifiably on disk and identical in structure to the working `gap-hunter` and `adr-historian` agents added via PR #35 earlier in the same session.

**What happened**

Claude Code's `subagent_type` registry — the set of names that the Task tool's `subagent_type` parameter will accept — is built once at session start by enumerating `~/.claude/agents/` (global) and `<repo>/.claude/agents/` (project). When new agent files appear on disk via `git pull` mid-session, the registry MAY refresh (it did for PR #35 agents earlier in the same session) or MAY NOT refresh (it did not for PR #41 agents later in the same session). The behaviour is non-deterministic from the orchestrator's perspective.

In the PR #41 case: 4 of 4 dispatch attempts against the new meta-agents failed; the remaining session had to compose results manually rather than via auto-fire. The post-merge validation reported VALIDATION-FAILED. The agents themselves were correct; only the registry handle was missing.

In the next session (this one), both agents were dispatchable from the start because the session loaded fresh.

**Binding rule** (apply to every campaign that adds new agents and immediately depends on them):

1. **A new agent file added via `git pull` mid-session is NOT guaranteed to be invocable in the same session.** Treat the agent as "available next session, not this one."

2. **Validate agent dispatchability in a fresh session before any campaign depends on it.** The first task of the next session should be a registry diagnostic that attempts `Task(subagent_type=<new-agent>)` for each newly-added agent. If the dispatch succeeds, the agent is live; if `Agent type ... not found` is returned, the registry has not refreshed and any campaign relying on the agent must defer.

3. **Post-merge validation tasks for agent-adding PRs MUST report VALIDATION-FAILED if the new agent cannot be dispatched in the post-merge session, even if all other validation steps succeed.** This is the only signal the operator gets that registry refresh failed.

4. **Do not silently substitute when a meta-agent (agent-performance-observer or flow-context-keeper) fails to dispatch.** Per GATE 5, substitution must be disclosed. For these two specifically, substitution is forbidden — the entire point of the observation layer is that THOSE agents run, not just any agent. Escalate instead.

5. **Operator should restart Claude Code session after any PR that adds new agent files merges**, before launching the next campaign that relies on those agents.

**Where the rule binds**:
- Every PR that creates a new file at `.claude/agents/*.md`
- Every PR that creates or modifies `~/.claude/agents/*.md` from within Claude Code
- Every "post-merge validation" or "fresh-session smoke" task following such a merge
- The first task of every session that follows an agent-adding merge

**Detection signals**:
- A Task tool dispatch returns `Agent type '<name>' not found. Available agents: ...` AND the agent file is verifiably on disk via `ls .claude/agents/<name>.md`
- A scorecard or PROJECT_STATE update fails to fire after the merge of a PR that added the meta-agents
- The first validation dispatch in a post-merge task immediately errors

**Workaround for current session if validation fails**:
- Compose the would-be agent's output manually (write the scorecard / PROJECT_STATE update directly)
- File the dispatchability failure as VALIDATION-FAILED status
- Do not proceed with downstream campaign work
- Recommend operator restart Claude Code session and re-run the validation task in fresh state

**Reference**: PR #41 post-merge validation task surfaced this; PR #46 confirmed (in a different session) that the agents work fine after fresh load. This validation task (PR for `chore/observation-layer-verification-and-lessons`) confirms the agents are dispatchable in the current session, closing the prior VALIDATION-FAILED signal.

---

## Lesson C — Observer scorecard writes must be orchestrator-verified post-write (2026-05-13)

**Origin**: Observation-layer audit closure task following the validator-hardening 3-PR sequence. After PR #50 (`chore/admin-runtime-flags-combined-state-validator`) merged at commit `8cd7188`, `agent-performance-observer` was dispatched per RULE 2 auto-fire and reported `SCORECARD WRITTEN: <path>`. Filesystem-wide search across all worktrees + git history + reflog + fsck-lost-found revealed the file NEVER reached disk anywhere. The `2026-05-13-w5-pd-admin-runtime-flags-validator.md` scorecard had to be reconstructed retroactively in this audit-closure cycle.

The same failure mode recurred in the audit-closure run itself: `final-consistency-review` initially reported NOT-READY HIGH because the two new scorecards (RETROACTIVE PR #50 + audit-closure) were absent from disk at its read time — even though `agent-performance-observer` had reported `SCORECARD WRITTEN`. Direct disk inspection 30 seconds later confirmed both files DID land. This is intermittent silent-loss, not deterministic failure.

**Root cause** (per gap-hunter F1+F5 root-cause hunt, MEDIUM severity, ROOT-CAUSE-INCONCLUSIVE but SYSTEMIC-ISSUE-DETECTED):

Two structural gaps combine to produce silent loss:
1. The `agent-performance-observer.md` prompt instructs the agent to print `SCORECARD WRITTEN: <path>` based on its own internal tool-call success state. There is NO post-write read-back self-verification step.
2. The agent's prompt uses a relative-path target (`.claude/memory/scorecards/<YYYY-MM-DD>-<campaign-slug>.md`). If the agent's runtime cwd at dispatch time differs from the orchestrator's worktree root (e.g., a sandbox dir), a relative-path Write resolves elsewhere and lands invisibly.

The file usually lands correctly. The intermittent failure pattern means there's no signal until a downstream consumer (`flow-context-keeper`, `final-consistency-review`, or a future operator) tries to cite the path and finds nothing.

**Binding rule** (apply to every observer auto-fire and to every meta-agent that produces a file artefact):

1. **Orchestrator MUST verify the scorecard file exists on disk after the observer agent returns.** A simple `ls .claude/memory/scorecards/<expected-filename>` (or `Read` of the path) is sufficient. The verification runs BEFORE composing the final report or dispatching downstream agents that depend on the scorecard.

2. **If the file is missing, treat the observer dispatch as FAILED — re-fire OR escalate.** Do not proceed with downstream work that assumes the file exists. Do not silently rely on the observer's self-reported success.

3. **Meta-agent prompts SHOULD use absolute paths derived from the orchestrator's repo root**, not relative paths that depend on agent runtime cwd. The orchestrator should pass the absolute target path into the agent prompt rather than letting the agent compute it.

4. **Meta-agent prompts SHOULD include a post-write self-verification step**: after Write, the agent does Read on the same path and confirms the file content matches what it intended to write. The agent reports `SCORECARD WRITTEN AND VERIFIED: <path>` only after both succeed.

5. **flow-context-keeper MUST validate every scorecard cited in PROJECT_STATE.md FACTS exists on disk** before the keeper run completes. Citing a non-existent file is a RULE 6 violation (the cited scorecard is invisible to future operators); the keeper should either (a) confirm the file exists, (b) re-fire the observer, or (c) record the citation as `PENDING` rather than as a confirmed FACT.

**Where the rule binds**:
- Every dispatch of `agent-performance-observer` (RULE 2 auto-fire OR manual `/observe`)
- Every dispatch of `flow-context-keeper` that cites scorecards (RULE 3 auto-fire OR manual `/update-state`)
- Every meta-agent that produces file artefacts (current: 2; future: pattern-historian, agent-prompt-refiner)
- Code review of any new meta-agent definition added to `.claude/agents/`
- The orchestrator's standard post-merge auto-fire workflow

**Detection signals**:
- An observer dispatch returns `SCORECARD WRITTEN: <path>` but `ls <path>` returns no such file
- A keeper run cites a scorecard in PROJECT_STATE.md FACTS that doesn't exist on disk
- A `final-consistency-review` reports RULE 6 violations because cited scorecards are missing
- A future operator (or task) cannot find a scorecard the citation chain promises

**Workaround for current session if Lesson C fires**:
- Re-dispatch the observer with an absolute-path target
- If re-dispatch also fails: produce the scorecard manually based on the campaign's known agent verdicts (use the RETROACTIVE convention with `-RETROACTIVE` suffix and explicit header note)
- Update PROJECT_STATE.md to record the recovery + add an OPEN QUESTION about whether the agent prompt needs hardening
- File a GATE 4 ISSUE (label `agent-tuning`) against `agent-performance-observer.md`

**Reference**: PR #50 silent-loss anomaly (2026-05-13); audit-closure task that produced the retroactive scorecard at `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md`; gap-hunter root-cause hunt (`ROOT-CAUSE-INCONCLUSIVE / SYSTEMIC-ISSUE-DETECTED, MEDIUM`); audit-closure scorecard at `.claude/memory/scorecards/2026-05-13-observation-audit-closure.md`. The intermittent recurrence in the audit-closure run itself (where `final-consistency-review` reported missing files that landed seconds later) is the second confirmed instance.

**Future hardening proposal** (not binding in this lesson; tracked as OPEN QUESTION in PROJECT_STATE.md): amend `agent-performance-observer.md` to (a) require absolute Write target derived from a `${ORCHESTRATOR_REPO_ROOT}` placeholder the orchestrator interpolates at dispatch time, and (b) require post-Write Read self-verification before printing `SCORECARD WRITTEN`. Same hardening applies to `flow-context-keeper.md` for PROJECT_STATE.md writes.

---

## Lesson D — LOCAL-COMMIT-ONLY deploys must be disclosed and reconciled (2026-05-13)

**Origin**: Wave 1 closure cycle (2026-05-13). SHA `4c797e46ff40b09f51292f05e13baef2882622a0` was deployed to Windows production via the 7-agent inline gate and robocopy sync without first landing on `origin/main` via a GitHub PR. The deploy itself was sound — all 7 gate agents returned CLEAR, all smokes passed, no rollback needed. But the SHA had no GitHub PR trail, making it invisible to any audit of `origin/main` history. The `deploy_release_manager` agent running inline did not flag this deviation. The gap was discovered post-deploy during SHA lineage verification (`git merge-base 0b4e381 4c797e4` returned `1b38ea0`, and `git log 0b4e381..4c797e4` showed only `4c797e4`, confirming it had no PR ancestry).

**What happened**

The Wave 1 hotfix (`fix(email): prevent outbound customs emails sending without attachments`) was built directly on the Windows staging machine under time pressure — the attachment integrity guard needed to reach production before customs emails could be queued. The correct 7-agent gate was run inline (reading agent files, not spawning agents), tests passed 160/160 + 366/366 + 12/12 (new attachment tests), and robocopy synced the code to `C:\PZ\app`. But the commit remained on the Windows local branch only; no PR was opened on GitHub. Consequence: `origin/main` has no record of this change. Any future audit of what code is running in production would require direct access to the Windows machine's git history or explicit documentation — neither of which is discoverable via the canonical GitHub interface.

Three of the four previously-documented "local hotfix commits" (`4d595ca`, `80e3469`, `1b38ea0`) were already on `origin/main` (reachable from `0b4e381`), confirming that SHA lineage verification is a reliable discriminator for this pattern.

**Gate types distinguished**

*PR gate*: Code lands on `origin/main` via GitHub PR. CI runs. Agent review fires per CLAUDE.md GATE 1. Merge via "Create a merge commit." SHA is publicly attributable to a PR number with full reviewer trail on GitHub.

*Inline gate (LOCAL-COMMIT-ONLY)*: Code exists as a commit on a local working tree without a GitHub PR. 7-agent review fires against the local state. Agents produce verdicts. Lead coordinator issues verdict. Code ships to production via local sync (robocopy/scp/equivalent) without GitHub PR review surface. **Both gate types involve agent review. The distinguishing fact is whether the SHA has a public PR trail.**

**Binding rule** (apply to every deploy where the SHA to deploy is not on `origin/main`):

1. **Disclosure required**: Any LOCAL-COMMIT-ONLY deploy must include in its gate report header, before any sync commands execute:
   ```
   ⚠ LOCAL-COMMIT-ONLY DEPLOY
   SHA being deployed:    <full SHA>
   GitHub PR:             NONE — this SHA is not on origin/main
   Bypass reason:         <reason from enumerated list below>
   Reconciliation plan:   <when and how the reconciliation PR will be filed>
   ```
   This header must appear at the top of the gate report, visible to the operator before deploy commands are executed.

2. **Operator must acknowledge**: The disclosure header must elicit an explicit operator acknowledgment before sync proceeds. "I acknowledge LOCAL-COMMIT-ONLY" or equivalent. Tacit approval (proceeding without acknowledgment) is not sufficient.

3. **Reconciliation required before next origin-pull deploy** (SOFT rule): A reconciliation PR must be filed and merged to `origin/main` before any subsequent `git pull --ff-only origin main` is executed on the same production machine. Pre-check command for any future deploy: `git log origin/main..HEAD` — if any commits appear AND those commits are currently deployed to production, reconciliation must precede the pull.

4. **Reconciliation PR body must include**:
   - Original LOCAL-COMMIT-ONLY deploy date and SHA
   - Bypass reason from the inline gate
   - The 7-agent gate verdicts produced during inline review (summarised)
   - Verification command confirming byte-identical content: `git diff <local-sha> <reconcile-pr-head> -- service/app/`
   - Explicit statement: "The code in this PR is byte-identical to what was deployed on [date]."

5. **Audit trail**: Every LOCAL-COMMIT-ONLY deploy creates an entry in `.claude/memory/local-commit-deploys.jsonl` immediately after the gate report is produced (before sync). The JSONL schema is documented in that file's header comment.

**Valid reasons justifying inline gate** (enumerated; all others are automatically invalid):
- Production incident requiring fix faster than PR review cycle permits — operator must document the incident in the disclosure header
- Operator on production-only machine (Mac dev environment unavailable for PR filing) — state which machine
- Toolchain failure preventing PR creation (e.g., GitHub API unreachable, `gh` CLI broken) — cite the specific failure

**Reasons that do NOT justify inline gate** (automatic escalation triggers):
- Convenience or speed preference
- Avoiding review friction or CI wait time
- Bypassing failing tests

**Where the rule binds**:
- Every call to the 7-agent deploy gate where `git log origin/main..HEAD` returns any commits
- `deploy_release_manager.md` § Branch hygiene item 5 (already updated with detection logic)
- The orchestrator's pre-sync checklist before any robocopy/production-sync command
- `.claude/memory/local-commit-deploys.jsonl` (append on every LOCAL-COMMIT-ONLY gate invocation)

**Detection signals**:
- `git log origin/main..HEAD` returns commits AND `git branch -r --contains <sha>` does NOT list `origin/main`
- The `deploy_release_manager` reports CLEAR but `git rev-parse origin/main` ≠ `git rev-parse HEAD`
- A post-deploy SHA lineage check (`git merge-base`) confirms divergence between production and origin

**Workaround if disclosure was skipped (retroactive application)**:
1. Create the `local-commit-deploys.jsonl` entry retroactively (use `"reconciliation_status": "PENDING_RETROACTIVE"`)
2. File the reconciliation PR with `-RETROACTIVE` suffix in title
3. Add an OPEN QUESTION in PROJECT_STATE.md: "Is reconciliation PR filed for this LOCAL-COMMIT-ONLY deploy?"
4. Do not proceed with any subsequent origin-pull deploy until reconciliation is merged

**Reference**: Wave 1 closure cycle (2026-05-13); SHA `4c797e4`; SHA lineage verification section of `PROJECT_STATE.md`; Wave 1 closure scorecard `.claude/memory/scorecards/2026-05-13-wave1-deploy-closure.md` § 4 (Lesson D candidate). Governance reference: `docs/governance/lesson-d-local-commit-only-deploys.md`. Audit record: `.claude/memory/local-commit-deploys.jsonl` (first entry: `4c797e4` retroactive).

---

## Lesson E — Background email automation requires five mandatory safety properties (2026-05-18)

**Origin**: MacBook `pz-launcher.py` incident (2026-05-18). A launchd agent (`eu.estrellajewels.pz-service`) had been running since 2026-05-10, binding to `0.0.0.0:8000`, loading live dev source from `/Downloads/CLI/service`, and holding live SMTP credentials in `~/Library/Application Support/estrellajewels/.env`. The process was capable of sending real outbound emails with no isolation guard between the dev environment and production SMTP. Contained by `launchctl unload` + plist moved to `~/LaunchAgent-Disabled/`.

**Root cause**: No environment isolation check at startup; no idempotency guard in the follow-up scheduler; no terminal-state suppression in the SLA runner. The process treated itself as production because no explicit `ENV=production` assertion existed.

**Binding rule** — every background email automation MUST implement all five properties:

**Property 1 — Execution-time validation**
Validate shipment state, AWB, recipients, and attachment integrity at execution time — the moment the email is about to be sent. Do not rely solely on validation done at schedule/enqueue time. State may have changed in the interval.

Detection signal: any `queue_email()` call not preceded by a fresh audit-state read in the same function scope.

**Property 2 — Idempotency**
A given email event (identified by `AWB + email_type + date_window`) must be sendable exactly once. Duplicate detection must be checked immediately before the send call, not only at enqueue time. The sent-state record must be written atomically with (or before) the SMTP call.

Detection signal: `queue_email()` called without a preceding `already_sent(awb, type, window)` check; or sent-state written after the SMTP call returns.

**Property 3 — Terminal-state suppression**
If the shipment is closed, cancelled, or in any terminal state at execution time, abort the send and log the suppression event. Never rely on the caller to have checked terminal state earlier in the call chain.

Detection signal: `queue_email()` reachable from a code path where `audit["status"]` is not re-read in the same function; or no `if status in TERMINAL_STATES: return` guard before the send.

**Property 4 — Replay safety**
If the process restarts, crashes, or replays a queue, already-sent emails must not be re-sent. Sent state must be durably persisted (audit.json write or DB commit) before the send call returns. Every queue-drain path must check sent state before acting.

Detection signal: scheduler that re-reads the full pending queue on startup without filtering by already-sent; or crash-recovery path that does not re-check sent state.

**Property 5 — Environment isolation**
Dev, staging, and local processes must not connect to the live SMTP server. The environment must be asserted explicitly at startup (e.g., `assert os.environ["ENV"] == "production"` or equivalent guard in `email_service.py`). A missing or ambiguous `ENV` value must default to dry-run (log only, no send).

Detection signal: `email_service.py` or `smtplib` import reachable without an environment assertion; `ENV` read from `.env` without a startup-time check that aborts on non-production values.

**Where it binds**: every scheduler, launchd/cron/NSSM/systemd job, cowork pipeline action runner, SLA follow-up service, or any module that imports `email_service`, `queue_email`, or `smtplib`; every code review of background automation; every deploy gate where an email-capable service is being restarted or added.

**Reference**: 2026-05-18 MacBook containment; `CLAUDE.md` Lesson E summary; plist archived at `~/LaunchAgent-Disabled/eu.estrellajewels.pz-service.plist.disabled`.

---

## Lesson H — Production `.env` must be pure UTF-8 and never carry placeholder literals (2026-05-22)

**Origin**: Global PZ wFirma posting readiness campaign (2026-05-22). During Step 3 (warehouse config) the operator pasted the documentation example lines `WFIRMA_WAREHOUSE_ID=REAL_ID_HERE` and `WFIRMA_WAREHOUSE_MODULE_ENABLED=true` into `C:\PZ\.env` using PowerShell `Add-Content`. PZService entered `STATE: 7 PAUSED`; health endpoint stopped responding. The pasted text was a red herring; the real failure surfaced in `pz_stderr.log`:

```
File ".../pydantic_settings/sources/providers/dotenv.py", line 81, in _read_env_file
  ...
File ".../codecs.py", line 322, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97 in position 1256: invalid start byte
```

Two bare `0x97` bytes (Windows-1252 em-dashes `–`) were sitting in two DHL-Tracking-API comment lines (line 48 + line 58 of `.env`). pydantic-settings reads `.env` strictly as UTF-8 — any single non-UTF-8 byte raises `UnicodeDecodeError` before settings finish loading. uvicorn fails to import the app; NSSM marks the service PAUSED. Every API call returns connection-refused. Recovery required byte-level repair of `.env` because the agent shell could not write to `C:\PZ\.env` (operator-only path) and PowerShell's default `Set-Content` produces UTF-16-LE which would make the problem worse.

**Binding rule** — every production `.env` edit MUST satisfy all four properties:

**Property 1 — Strict UTF-8 encoding (without BOM)**
`.env` must be encoded as UTF-8 without a byte-order mark. pydantic-settings rejects Windows-1252 / Latin-1 / UTF-16. PowerShell 5.1's `Set-Content -Encoding UTF8` writes a BOM (which pydantic-settings tolerates but other dotenv libs may not); `Out-File -Encoding utf8` and `Add-Content` (no `-Encoding`) default to UTF-16-LE on Windows PowerShell — never use them for `.env`. Always pass `-Encoding UTF8` explicitly, OR use `[System.IO.File]::WriteAllBytes` with a known byte stream, OR edit in a UTF-8-only editor (Notepad++, VS Code with EOL=LF + Encoding=UTF-8).

Detection signal: any byte in `[0x80..0xC1]` that is not part of a valid UTF-8 multibyte sequence; presence of `0xFE 0xFF` or `0xFF 0xFE` BOM bytes at file head.

**Property 2 — No placeholder literals**
Documentation patterns like `WFIRMA_WAREHOUSE_ID=REAL_ID_HERE`, `<id-from-wFirma>`, `<your-token-here>`, `XXX`, `TODO`, `FIXME`, or `<value>` must never appear in production `.env`. Pydantic accepts any string; downstream code may treat the literal as a "configured" value and silently send `?warehouse=REAL_ID_HERE` to wFirma, hit a SQL injection trap, or produce an apparently-successful response with garbage data. The example patterns in docs MUST be marked clearly as documentation-only (e.g., enclosed in a "do not paste verbatim" warning), OR the docs must omit the example value entirely and instruct the operator to substitute their actual value before pasting.

Detection signal: regex `(?i)real_id|real_value|<[^>]*>|xxx|todo|fixme|placeholder|your[-_]?(id|key|token|value)` matching any `.env` value after `=`.

**Property 3 — Service-startup pre-flight check on `.env`**
On every PZService startup, the application MUST validate `.env` is parseable as UTF-8 and contains no placeholder patterns BEFORE attempting to load settings. A failed pre-flight must log a clear, structured error to `pz_stderr.log` (file path, byte offset, character class) rather than letting pydantic-settings crash with a generic `UnicodeDecodeError`. The check is read-only and fast.

Detection signal: `Settings()` construction reachable from `main.py` import without a preceding `_validate_env_file()` call that asserts UTF-8 decode + placeholder absence.

**Property 4 — Backup before edit, byte-level rollback path**
Every production `.env` edit MUST be preceded by `Copy-Item C:\PZ\.env "C:\PZ\.env.bak_$(Get-Date -Format yyyyMMdd_HHmmss)"`. If a restart fails health, the operator restores the last good backup via `Copy-Item C:\PZ\.env.bak_<timestamp> C:\PZ\.env -Force` and re-runs the service. The agent never writes to production `.env` directly — every edit is operator-typed in elevated PowerShell, with the backup and the change in the same transaction.

Detection signal: any `.env`-editing instruction in chat that omits the backup step; any deploy procedure that touches `.env` without an explicit rollback command listed alongside.

**Where it binds**: every operator instruction set that involves editing `C:\PZ\.env` (or any `.env`); every campaign that requests new env keys; every doc snippet that uses example values; every PR that adds a new `Settings` field expecting a value from `.env`. Documentation example values must be inert (e.g., `<replace-this-with-actual-id-do-not-paste-literally>`) so accidental paste produces a regex-detectable string that pre-flight rejects.

**Reference**: 2026-05-22 PZService PAUSED incident on Global PZ wFirma readiness campaign; recovery via byte-level `0x97 → "--"` replacement + placeholder-line removal; PowerShell `[System.IO.File]::ReadAllBytes` / `WriteAllBytes` pattern used for repair.

---

## Lesson I — Production incidents must become workflow-class rules, never shipment-specific patches (2026-05-22)

**Origin**: Global Jewellery PZ campaign (2026-05-22, PRs #269–#283). Six separate production failures occurred on a single batch (`SHIPMENT_4789974092_2026-05_999deef1`) and were resolved in sequence. After the final fix (PR #283), the operator codified the meta-lesson: every incident is a signal about a class of shipments, not a property of the specific batch that surfaced it.

**What happened — six workflow-class failures exposed by one batch**

| # | Failure | Root class |
|---|---|---|
| 1 | Product names created from cached description authority, not invoice-position authority | Authority-chain violation |
| 2 | PZ manually deleted in wFirma; audit mapping lost after a subsequent `/process` run | Lifecycle gap — no "operator deleted" signal |
| 3 | `clear-mapping` returned `already_cleared` when `wfirma_export` was empty but timeline had no clearing event | Idempotency guard used wrong authority (export field vs timeline) |
| 4 | `pz_create` blocked with `PZ_ALREADY_CREATED` after `PZ_RECONCILED` was correctly set | Create guard did not understand the reconciled lifecycle state |
| 5 | UI showed contradictory banners simultaneously (recovery + creation disabled + ready=true) | Multiple UI authority sources, no single lifecycle source |
| 6 | Compact audit notes missing from PZ description field | Notes helper not wired into the create path |

None of these are Global-specific. All can recur on Estrella, any future supplier, or any batch where an operator performs a manual wFirma edit.

**Binding rule** — six principles, all permanent:

**Principle 1 — Every incident must be converted to a workflow rule before the fix PR closes**

Root cause analysis must answer: "Can this happen on a different batch?" If yes, the fix must be expressed as a guard, lifecycle state, authority check, or regression test — not as a one-time data correction.

Detection signal: a PR description that names the specific batch ID (`SHIPMENT_XXX`) as the scope of the fix without naming a workflow class that the fix protects. Flag immediately with reviewer-challenge.

Forbidden pattern:
```python
if batch_id == "SHIPMENT_4789974092_2026-05_999deef1":
    # special case
```

**Principle 2 — Authority chain must flow top-to-bottom, never sideways**

The canonical authority chain for every PZ is:

```
Invoice positions (parsed from PDF)
    ↓  bridge: _try_invoice_from_authority_rows
Polish description authority (pz_rows.json)
    ↓
wFirma goods (product names + IDs)
    ↓  guard: STALE_AUTHORITY_REFUSED
PZ creation (wFirma warehouse document)
    ↓
audit.wfirma_export (local state record)
```

At no step may a lower-level authority feed back upward to a higher level. At no step may a cached intermediate (description block, prior audit state) substitute for the live top-level authority when that authority is available.

Detection signal: any call to `description_engine.get_description_block()` from a code path that has access to `_pz_engine_authority_rows`. The description engine is downstream of the authority rows — using it in that context is an inversion.

**Principle 3 — PZ lifecycle is a state machine with exactly one authority: `pz_lifecycle.state`**

The canonical lifecycle for every shipment is:

```
PZ_NOT_READY
    ↓ (all gates pass + flag on)
PZ_READY_TO_CREATE
    ↓ (pz_create succeeds)
PZ_CREATED

Recovery branch:
PZ_CREATED → [wfirma_export wiped by /process] → PZ_RECOVERY_REQUIRED
    ↓ confirm_existing_pz (audit-write recovery)
PZ_CREATED

Deletion branch:
PZ_CREATED → [operator deletes in wFirma + calls clear-mapping] → PZ_RECONCILED
    ↓ recreate
PZ_CREATED
```

Every UI surface, every create/adopt guard, and every audit-write decision must consult `pz_lifecycle.state` as the single authority. Any guard that checks `wfirma_export.wfirma_pz_doc_id` without also consulting `_has_pz_mapping_cleared_after_create` is incomplete.

Detection signal: a `pz_create` or `pz_adopt` guard that calls `_has_pz_terminal_event` without also calling `_has_pz_mapping_cleared_after_create`. Flag in every code review of these endpoints.

**Principle 4 — Five mandatory protections for every future shipment**

These five protections must be present for any supplier, any batch:

| Protection | Trigger | Response |
|---|---|---|
| 1. Product-name drift detection | `authority_name ≠ wFirma product name` | Surface drift, offer sync via `/products/sync-names`. Never silently continue. |
| 2. Audit-write loss detection | `wfirma_pz_created` in timeline AND `wfirma_pz_doc_id` missing from export | Auto-classify `PZ_RECOVERY_REQUIRED`. `confirm_existing_pz` is primary action. |
| 3. Manual-deletion detection | `wfirma_pz_created` in timeline AND `wfirma_pz_mapping_cleared` is latest mapping event | Auto-classify `PZ_RECONCILED`. Recreation allowed. |
| 4. Single-authority UI | `pz_lifecycle.state` is the only banner/button authority | No dual banner systems. No `pz_lock_status` as primary source when lifecycle is alarming. |
| 5. Compact audit notes | `build_wfirma_pz_notes(audit, batch_id)` injected into every `pz_create`/`pz_adopt` call | INV, AWB, MRN, SAD, VAT, NBP, SUP, CA — sourced from current shipment authority, no hardcoded values. |

**Principle 5 — Fix scope must be the workflow class, not the incident batch**

When a fix is written, ask: "Does this PR protect every future shipment, or only this one?" The answer must be "every future shipment." If it is not, the PR is incomplete.

After every fix:
1. Identify root cause (one sentence).
2. State the workflow class ("any batch where wfirma_export is wiped before clear-mapping is called").
3. Write the guard or state-machine change that protects the class.
4. Write regression tests using synthetic audits — not the specific batch's real audit.json.
5. Verify Estrella reference batch is unaffected.
6. Deploy as permanent workflow behavior.

**Principle 6 — The platform improves with every real shipment**

Every production incident is the system teaching itself what it missed. The correct response is not to patch the incident and move on — it is to make that class of incident structurally impossible for the next batch. Guards, lifecycle states, authority checks, and regression tests are the artifacts of that learning. PRs that produce these artifacts are the unit of platform maturity.

**Where it binds**: every PR that fixes a production incident; every reviewer-challenge invocation on any incident-driven PR; every `agent-performance-observer` scorecard that evaluates an incident campaign; every `flow-context-keeper` update following an incident resolution. If a PR does not name a workflow class and does not add at least one regression test, it is incomplete by this lesson regardless of whether the immediate incident is resolved.

**Reference**: Global Jewellery PZ campaign 2026-05-22, PRs #269–#283; operator governance statement 2026-05-22: "Every real shipment should improve the platform for the next shipment."
