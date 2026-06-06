# AGENT_REGISTRY.md — Atlas V2 Canonical Agent Registry

**Source of truth for the agents that are version-controlled in THIS repository.**
Generated 2026-06-06 by direct inspection of `.claude/agents/*.md` frontmatter
(not the runtime dispatch menu). 15 repo-installed agents.

> **Canonical rule:** These 15 agents are the only agents whose behaviour,
> tool grants, and boundaries are guaranteed by version control. The runtime
> `subagent_type` menu may show ~70 names; those are NOT authoritative for this
> project unless independently verified per task. See
> `.claude/campaigns/atlas-v2/agent-orchestration-playbook.md`.

> **Capability legend (derived from the `tools:` frontmatter — the binding fact):**
> - **INSPECT-ONLY** = `Read, Grep, Glob` only. Cannot mutate any file. Returns a verdict.
> - **DOCS-WRITE** = has `Write`/`Edit` but prompt-scoped to a specific docs/memory artifact (ADRs, scorecards, PROJECT_STATE). Cannot touch product code.
> - No repo-installed agent has product-code (`service/app/**` non-doc) write access.

---

## Quick matrix

| # | Agent (`subagent_type`) | Capability | Write target | Safe for customs/accounting/inventory/wFirma? | Group |
|---|---|---|---|---|---|
| 1 | `gap-hunter` | INSPECT-ONLY | — | ✅ cannot mutate | Planning, Impl-review |
| 2 | `backend-safety-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Planning, Impl-review |
| 3 | `frontend-flow-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Planning, Impl-review |
| 4 | `security-write-action-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate (this is the write-risk reviewer) | Impl-review |
| 5 | `test-coverage-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Planning, Impl-review |
| 6 | `deploy-git-diff-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Deploy gate |
| 7 | `deploy-backend-impact-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Deploy gate |
| 8 | `deploy-persistence-storage-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Deploy gate |
| 9 | `deploy-security-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate (security blocker authority) | Deploy gate |
| 10 | `deploy-qa-reviewer` | INSPECT-ONLY | — | ✅ cannot mutate | Deploy gate |
| 11 | `deploy-release-manager` | INSPECT-ONLY | — | ✅ cannot mutate | Deploy gate |
| 12 | `deploy-lead-coordinator` | INSPECT-ONLY | — | ✅ cannot mutate (decision authority) | Deploy gate |
| 13 | `adr-historian` | DOCS-WRITE | `.claude/adr/*` (append-only) | ✅ cannot mutate product | Post-run governance |
| 14 | `agent-performance-observer` | DOCS-WRITE (+Bash) | `.claude/memory/scorecards/*` | ✅ cannot mutate product | Post-run governance |
| 15 | `flow-context-keeper` | DOCS-WRITE (+Bash) | `.claude/memory/PROJECT_STATE.md` | ✅ cannot mutate product | Post-run governance |

> **Filename ↔ subagent_type note:** the deploy files are named with underscores
> on disk (`deploy_git_diff_reviewer.md`) but dispatch with hyphens
> (`deploy-git-diff-reviewer`). Use the hyphen form in `subagent_type`.

---

## Per-agent detail

### 1. `gap-hunter` — INSPECT-ONLY
- **Purpose:** Hunts hidden bugs, unfinished states, silent downgrades, concurrency holes, security drift, stale routes, hidden assumptions. Cross-phase contradiction finder.
- **When to use:** Planning (before edits) and implementation review (after edits). Any sprint where "what did we miss?" matters.
- **When NOT to use:** As a verdict authority for deploy (that's the deploy gate). Not a substitute for tests.
- **Capability:** Inspect-only (Read/Grep/Glob). Recommends; never edits.
- **Domain safety:** Safe everywhere — cannot mutate.
- **Output contract:** PASS / FAIL / BLOCKED · findings with file:line · risks · recommendation · operator-approval-required flag.

### 2. `backend-safety-reviewer` — INSPECT-ONLY
- **Purpose:** Reviews backend routes/services for unsafe writes, false evidence, fake paths, missing idempotency, missing `_normalise_X` boundary helpers (Lesson A).
- **When to use:** Planning + implementation review on any change touching `service/app/api/**` or services.
- **When NOT to use:** Pure frontend-only changes (use frontend-flow-reviewer). Not a deploy-gate substitute.
- **Capability:** Inspect-only. Recommends; never edits.
- **Domain safety:** Safe — cannot mutate. This is a *reviewer of* customs/accounting/inventory/wFirma backend safety.
- **Output contract:** PASS / FAIL / BLOCKED · unsafe-write findings · risks · recommendation · operator-approval flag.

### 3. `frontend-flow-reviewer` — INSPECT-ONLY
- **Purpose:** Reviews dashboard/V2 pages for broken operator flow, hidden actions, direct unsafe API calls, missing disabled reasons.
- **When to use:** Any UI change (V2 shell pages, dashboard). Pairs with the `frontend-design` skill.
- **When NOT to use:** Backend-only changes.
- **Capability:** Inspect-only. Recommends; never edits.
- **Domain safety:** Safe — cannot mutate.
- **Output contract:** PASS / FAIL / BLOCKED · flow defects · risks · recommendation · operator-approval flag.

### 4. `security-write-action-reviewer` — INSPECT-ONLY
- **Purpose:** Reviews write actions for readiness gates, confirmation, idempotency, audit trace. The write-risk reviewer.
- **When to use:** Any change that introduces or modifies a write action (POST/PUT/PATCH/DELETE, wFirma push, inventory transition, email send). **Mandatory** for write-risk domains.
- **When NOT to use:** Read-only / observer surfaces (e.g. Sprint 30/31 were read-only — this reviewer is optional there but cheap insurance).
- **Capability:** Inspect-only. Recommends; never edits.
- **Domain safety:** Safe — cannot mutate. This is the gate that *guards* customs/accounting/inventory/wFirma writes.
- **Output contract:** PASS / FAIL / BLOCKED · write-safety findings · risks · recommendation · operator-approval flag.

### 5. `test-coverage-reviewer` — INSPECT-ONLY
- **Purpose:** Reviews tests for missing negative cases and weak source-grep coverage around execution, agents, readiness.
- **When to use:** Planning (define test plan) + implementation review (verify coverage).
- **When NOT to use:** As the test runner (it reviews coverage; it does not execute tests).
- **Capability:** Inspect-only. Recommends; never edits.
- **Domain safety:** Safe — cannot mutate.
- **Output contract:** PASS / FAIL / BLOCKED · coverage gaps · risks · recommendation · operator-approval flag.

### 6–12. The 7-agent Deploy Gate — all INSPECT-ONLY
These run **together** as the production deploy gate (see CLAUDE.md "Production deployment rule"). All verdict-only; none may call git/Bash/robocopy/sc.exe/Copy-Item.

- **6. `deploy-git-diff-reviewer`** — classifies every changed file by risk (SAFE_CODE / CONFIG_RISK / DB_SCHEMA / FORBIDDEN_PATH / ENGINE_CORE …); flags must-not-deploy files; checks Lesson J (files outside `service/app/static/**` or `service/app/**` needing separate sync).
- **7. `deploy-backend-impact-reviewer`** — route auth guards, router registration in main.py, service-interface breaks, missing requirements.txt, platform imports, carrier gate.
- **8. `deploy-persistence-storage-reviewer`** — schema mutations (CREATE/ALTER/DROP), storage path writes, hardcoded prod paths, missing migration plan.
- **9. `deploy-security-reviewer`** — credential exposure, auth guard removal/bypass, carrier gate bypass, injection, committed secrets. **Security blockers cannot be overridden by anyone, including the lead coordinator.**
- **10. `deploy-qa-reviewer`** — verifies PZ regression (160) + carrier suite (381) from PRE-RUN output (does not run tests). Any test failure/error is an unconditional block.
- **11. `deploy-release-manager`** — branch hygiene, exact rollback command for the deploy SHA, sync plan, post-deploy checklist.
- **12. `deploy-lead-coordinator`** — collects the other 6, resolves conflicts, issues the written GO / NO-GO. Final authority for the deploy step (but cannot override a security block).
- **When to use:** ONLY before a production deploy. All 7, in parallel, then coordinator.
- **When NOT to use:** For non-deploy reviews (use the impl-review group). Never as planning agents.
- **Domain safety:** Safe — all inspect-only.
- **Output contract:** each returns PASS/CLEAR / FAIL / BLOCKED · risk classification · evidence (file:line) · recommendation. Coordinator returns READY-TO-DEPLOY / BLOCKED.

### 13. `adr-historian` — DOCS-WRITE (`.claude/adr/*`, append-only)
- **Purpose:** Drafts new ADRs from coordinator-approved decisions; maintains the ADR index. Never rewrites historical ADRs.
- **When to use:** Post-run governance, **only when an architecture decision was made** during the task.
- **When NOT to use:** Routine sprints with no architectural decision. Never to edit product code.
- **Capability:** Write/Edit — scoped to `.claude/adr/`. Append-only discipline.
- **Domain safety:** Safe for product domains — cannot touch product code.
- **Output contract:** PASS / FAIL · ADR file path created · decision summarised · recommendation.

### 14. `agent-performance-observer` — DOCS-WRITE (`.claude/memory/scorecards/*`, +Bash)
- **Purpose:** Scores each participating subagent on 6 dimensions after a FINAL REPORT; produces per-agent scorecards; surfaces weak verdicts; self-evaluates on cadence (RULE 5).
- **When to use:** Post-run governance — **mandatory** after any report with ≥3 subagents or a FINAL REPORT (RULE 2).
- **When NOT to use:** Mid-task. Never to mutate agent prompts (it observes; it does not refine).
- **Capability:** Write (scorecards) + Bash (read-only verification). Does NOT edit agent prompts.
- **Domain safety:** Safe for product domains.
- **Output contract:** scorecard file path · per-agent verdicts (EXEMPLARY/ACCEPTABLE/NEEDS-TUNING/UNRELIABLE) · GATE 4 dispositions for weak verdicts · self-eval if due. **Orchestrator must verify the file exists on disk (Lesson C).**

### 15. `flow-context-keeper` — DOCS-WRITE (`.claude/memory/PROJECT_STATE.md`, +Bash)
- **Purpose:** Maintains PROJECT_STATE.md (FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS). FACTS append-only; never demote a fact to an assumption.
- **When to use:** Post-run governance — after the observer (RULE 3), after any PR merge to main, after any issue closes, on `/update-state`.
- **When NOT to use:** Mid-task. Never to edit product code.
- **Capability:** Write/Edit (PROJECT_STATE) + Bash (read-only verification).
- **Domain safety:** Safe for product domains.
- **Output contract:** PASS / FAIL · PROJECT_STATE sections updated · scorecards cited (RULE 6) · recommendation.

---

## Universal output contract (every agent)

Every agent invocation in this project must return:

```
VERDICT:            PASS | FAIL | BLOCKED   (deploy agents: CLEAR | BLOCKED; coordinator: READY-TO-DEPLOY | BLOCKED)
EVIDENCE:           concrete findings, each with file:line where possible
FILES INSPECTED:    explicit list
RISKS:              enumerated, with severity
RECOMMENDATION:     what to do next
ACTION SAFE?:       yes / no  (is it safe to proceed without human review?)
OPERATOR APPROVAL:  required / not-required
```

---

## Safety rule (binding)

**Agents do not own production authority.** Agents inspect, verify, and recommend.
The operator and the explicit 7-agent deploy gate own production action. A recommendation
from any agent — including the lead coordinator — is never itself a production mutation.

## Runtime-registry rule (binding)

The ~80-entry runtime `subagent_type` menu is a convenience surface, not an authority.
For final verdicts, use a repo-installed agent from this registry. A runtime-only agent
(no file in `.claude/agents/`) may be used only as an optional helper, and its output must
be independently verified before it influences any production-affecting decision (Lesson B).

**Full runtime enumeration + hazard list:** `.claude/agents/RUNTIME_AGENT_AUDIT.md`
(2026-06-06). It documents all ~80 dispatchable agents: 15 repo-canonical (this file),
54 user-level runtime-only (~23 write-capable, incl. EJ-domain-named actors that are
FORBIDDEN as actors), plus built-ins and wrong-domain plugin agents. Read it before
dispatching any non-repo `subagent_type`.
