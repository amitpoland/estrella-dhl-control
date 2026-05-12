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
