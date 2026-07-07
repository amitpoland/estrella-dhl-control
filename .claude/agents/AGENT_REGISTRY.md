# AGENT_REGISTRY.md — Atlas V2 Canonical Agent Registry

**Source of truth for the agents that are version-controlled in THIS repository.**
Generated 2026-06-06; **refreshed 2026-07-08** by read-only filesystem inspection.
**27 repo-installed agents** on disk (`.claude/agents/*.md`, excluding the two
registry docs). The canonical body below (entries 1–20) is unchanged; the **7
agents added since 2026-06-06** and the current governance notes (model-pins,
duplicate registrations, the new scoped-implementer class, Senior Execution
Council, skill-to-agent matrix, by-package guidance) are in the
**`## 2026-07-08 Registry Refresh`** section at the end of this file. Read that
section for the current-state view; read the per-agent bodies for detail.

Historical note (kept): the original count was **20** = 15 original + 5 installed
2026-06-06 (reviewer-challenge, ux-flow, integration-boundary, gap-detection,
final-consistency-review — all inspect-only).

> **Fresh-session caveat (Lesson B):** the 5 agents installed 2026-06-06 were already
> dispatchable as user-level runtime agents. Dispatch tests confirmed they respond, but
> `final-consistency-review` ran the **user-level copy (still Bash-capable)**, not the
> repo inspect-only copy. The repo copies' tool-stripping is **pending fresh-session
> confirmation** of project-over-user precedence. Until a fresh session verifies this,
> treat these 5 as runtime-backed. Full detail: `RUNTIME_AGENT_AUDIT.md` addendum.

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
| 16 | `reviewer-challenge` | INSPECT-ONLY | — | ✅ cannot mutate | Planning, Impl-review (CLAUDE.md-mandated on V2 PRs) |
| 17 | `ux-flow` | INSPECT-ONLY | — | ✅ cannot mutate | Impl-review (UI/UX) |
| 18 | `integration-boundary` | INSPECT-ONLY (Bash stripped) | — | ✅ cannot mutate | Impl-review (FE/BE seams) |
| 19 | `gap-detection` | INSPECT-ONLY (Bash stripped) | — | ✅ cannot mutate | Planning (pre-work 10-cat scan) |
| 20 | `final-consistency-review` | INSPECT-ONLY (Bash stripped) | — | ✅ cannot mutate | Post-run (pre-operator last gate) |

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
(2026-06-06). It documents the dispatchable agents: repo-canonical (this file),
54 user-level runtime-only (write-capable domain actors that are FORBIDDEN as
actors), plus built-ins and wrong-domain plugin agents. Read it before dispatching
any non-repo `subagent_type`.

---

## 2026-07-08 Registry Refresh

Docs-only refresh (read-only inventory; no agent files changed, none created/removed).
Supersedes stale counts above. System snapshot:
**repo agents 27 · global (user-level) agents 54 · skills 9 · commands 14 · hooks 9.**

### 1. Updated agent registry — the 7 agents added since 2026-06-06

The canonical body (entries 1–20) is accurate. These 7 were added afterward and were
NOT in the original matrix. Five are inspect-only; **two are a NEW capability class —
scoped implementers** (they carry `Edit`/`Write`/`Bash` but are hard-fenced by
`.claude/hooks/implement-guard.py` + an `EJ_IMPLEMENT=1` env flag + a one-slice-then-STOP
prompt contract; they cannot commit/push/PR/deploy).

| # | Agent (`subagent_type`) | Capability | Write target | Group |
|---|---|---|---|---|
| 21 | `api-wrapper-inspector` | INSPECT-ONLY | — | Impl-review (pz-api.js vs v2 parity) |
| 22 | `backend-route-inspector` | INSPECT-ONLY | — | Impl-review (routes vs main.py registration) |
| 23 | `frontend-authority-inspector` | INSPECT-ONLY | — | Impl-review (one-URL-per-module authority map) |
| 24 | `navigation-inspector` | INSPECT-ONLY | — | Impl-review (router slug ↔ component) |
| 25 | `service-scheduler-inspector` | INSPECT-ONLY | — | Impl-review (orphan schedulers/startup jobs) |
| 26 | `reports-authority-implementer` | **SCOPED-IMPLEMENTER** (Edit/Write/Bash) | slice-03 files only, guarded | Implementation (one slice, then STOP) |
| 27 | `shipment-authority-implementer` | **SCOPED-IMPLEMENTER** (Edit/Write/Bash/PowerShell) | slice-01 files only, guarded | Implementation (one slice, then STOP) |

> **Capability-legend addendum:** the pre-2026-07 statement "no repo-installed agent has
> product-code write access" is now qualified — entries 26–27 CAN edit product code, but
> **only** the specific slice named in their prompt, under `implement-guard.py`, and only
> when invoked via `/implement-slice`. They cannot commit, push, open a PR, or deploy.
> Everything else in the repo set remains INSPECT-ONLY or DOCS-WRITE.

### 2. Senior Execution Council (recommended standing mapping)

| Seat | Repo agent(s) | Backing skill |
|---|---|---|
| Router / chair | *(orchestrator)* → routes via `ej-dashboard-master` skill | ej-dashboard-master |
| Architecture | *(runtime)* `system-architect` + `reviewer-challenge` | senior-architect |
| Backend authority | `backend-safety-reviewer` (+ `backend-route-inspector`, `service-scheduler-inspector`, `api-wrapper-inspector`) | ej-dashboard-fullstack-governance |
| Frontend authority | `frontend-flow-reviewer` (+ `frontend-authority-inspector`, `navigation-inspector`, `ux-flow`) | frontend-design + ej-dashboard-design |
| Persistence | `deploy-persistence-storage-reviewer` | ej-dashboard-fullstack-governance |
| Write-risk / security | `security-write-action-reviewer` + `deploy-security-reviewer` (blocker authority) | fullstack-governance |
| Devil's advocate | `reviewer-challenge` + `gap-hunter` + `gap-detection` | — |
| Integration seams | `integration-boundary` | — |
| Test authority | `test-coverage-reviewer` (+ runtime `browser-verifier`, `testing-verification`) | ej-dashboard-webapp-testing |
| Deploy authority | the 7 `deploy-*` agents → `deploy-lead-coordinator` (go/no-go) | /deploy gate |
| Last gate | `final-consistency-review` | — |
| State / observation | `flow-context-keeper` + `agent-performance-observer` + `adr-historian` | — |

> Rule: council **seats recommend**; the operator + the 7-agent deploy gate own production
> action. Runtime-only seats (`system-architect`, `browser-verifier`, `testing-verification`)
> are helpers whose output must be independently verified (Lesson B).

### 3. Skill-to-agent matrix

Agents don't load skills (skills scope the main session); this is the intended pairing.

| Skill | Authority for | Paired agents |
|---|---|---|
| `ej-dashboard-master` | routing / minimum-skill selection | *(orchestrator)*, `agent-router` (runtime) |
| `ej-dashboard-fullstack-governance` | backend / API / persistence / protected domains | `backend-safety-reviewer`, `backend-route-inspector`, `deploy-persistence-storage-reviewer`, `security-write-action-reviewer` |
| `ej-dashboard-clean-code` | refactor / simplicity / repo safety | any impl-review agent |
| `frontend-design` + `ej-dashboard-design` | tokens, page authority, duplicate prevention | `frontend-flow-reviewer`, `frontend-authority-inspector`, `navigation-inspector`, `ux-flow` |
| `ej-dashboard-webapp-testing` | browser / smoke verification | `test-coverage-reviewer` (+ runtime `browser-verifier`) |
| `ui-ux-pro-max` | **reference only, never authority** (read `EJ_OVERRIDES.md` first) | `ux-flow`, `frontend-flow-reviewer` |
| `wfirma-api-integration` | wFirma API/webhook/mirror knowledge | runtime `wfirma-integration` (never final authority) |
| `data-analysis` | cross-DB operational debugging | any inspector |
| `senior-architect` (global) | architecture patterns | runtime `system-architect` |

### 4. Broken / model-pinned notes

- **Broken:** none — all 27 repo entries verified present on disk; tool grants match frontmatter.
- **Model-pinned (repo, 7):** `final-consistency-review`, `flow-context-keeper`, `gap-detection`,
  `integration-boundary`, `reviewer-challenge`, `shipment-authority-implementer`, `ux-flow`.
- **Model-pinned (global, all 54):** 39 `sonnet`, 11 `opus`, 4 `haiku`.
- **Duplicate registrations (repo ∩ global — 5):** `final-consistency-review`, `gap-detection`,
  `integration-boundary`, `reviewer-challenge`, `ux-flow` exist in BOTH trees. The 2026-06-06
  "0 overlap" note is stale. Hazard: a dispatch may hit the **user-level (Bash-capable) copy**
  instead of the repo inspect-only copy (Lesson B / the fresh-session caveat at the top). Prefer
  a fresh session after any agent-file change; treat these 5 as runtime-backed until confirmed.
- **Availability caveat (Lesson B):** agents added mid-session are not reliably invocable until a
  session restart. Only repo/canonical agents are governed; runtime-only (global/plugin/built-in)
  agents are **never final authority**.

### 5. Which agents to use — by package type

| Package type | Lead / primary | Reviewers (parallel) | Gate |
|---|---|---|---|
| **Frontend / UI** | runtime `frontend-ui` | `frontend-flow-reviewer`, `frontend-authority-inspector`, `navigation-inspector`, `ux-flow`, `reviewer-challenge` | browser verify → deploy gate |
| **Backend / API** | runtime `backend-api` | `backend-safety-reviewer`, `backend-route-inspector`, `service-scheduler-inspector`, `api-wrapper-inspector` | `test-coverage-reviewer` → deploy gate |
| **Database / schema** | runtime `database-storage` | `deploy-persistence-storage-reviewer`, `backend-safety-reviewer` | deploy gate (persistence reviewer) |
| **wFirma** | runtime `wfirma-integration` (+ `wfirma-api-integration` skill) | `security-write-action-reviewer`, `deploy-security-reviewer` | deploy gate |
| **Write-action / fiscal** | domain actor | `security-write-action-reviewer` (mandatory), `reviewer-challenge`, `integration-boundary` | deploy gate |
| **Deployment** | the 7 `deploy-*` agents | — | `deploy-lead-coordinator` go/no-go |
| **Testing** | runtime `testing-verification`, `browser-verifier` | `test-coverage-reviewer`, `deploy-qa-reviewer` | — |
| **Architecture / design** | runtime `system-architect` (+ `senior-architect` skill) | `reviewer-challenge`, `integration-boundary`, `gap-hunter` | — |
| **UX / product review** | `ux-flow` | `frontend-flow-reviewer`, `reviewer-challenge` (+ `ui-ux-pro-max` reference) | — |
| **Scoped code slice** | `reports-authority-implementer` / `shipment-authority-implementer` (via `/implement-slice`, guarded) | matching domain reviewer | deploy gate |
| **Governance / post-run** | `flow-context-keeper` | `agent-performance-observer`, `adr-historian` | — |
