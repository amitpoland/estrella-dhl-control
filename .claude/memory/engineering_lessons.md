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
