# AGENTS.md — Atlas V2 Capability Registry: All Agents

**Generated:** 2026-06-06 · **Source:** direct filesystem + AGENT_REGISTRY.md + RUNTIME_AGENT_AUDIT.md inspection
**Canonical tree:** `C:\PZ-verify` · No product code modified.

---

## Legend

| Field | Meaning |
|---|---|
| Source | `REPO` = version-controlled in `C:\PZ-verify\.claude\agents\`; `USER` = `~/.claude/agents/`; `BUILTIN` = Claude Code built-in; `PLUGIN` = marketplace plugin |
| R/W Level | INSPECT = Read/Grep/Glob only; DOCS-WRITE = scoped docs write; FULL-WRITE = can write any file; EXEC = can run Bash/shell |
| Production risk | LOW / MEDIUM / HIGH / CRITICAL |
| Dispatchable | YES (confirmed) / PENDING (Lesson B: fresh-session required) |
| Tested | ✅ dispatch-verified / ⚠️ Lesson-B-pending / ❌ not tested |
| Classification | See classification key at bottom |

---

## PART A — Repo-Installed (Canonical) Agents

These 20 agents are version-controlled in `C:\PZ-verify\.claude\agents\`. They are the only
agents whose behaviour, tool grants, and boundaries are guaranteed by this project.
**15 original + 5 installed 2026-06-06 (Lesson-B fresh-session confirmation pending).**

---

### A1. `gap-hunter`
| Field | Value |
|---|---|
| **Name** | `gap-hunter` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\gap-hunter.md` |
| **Version** | original repo install |
| **Purpose** | Hunts hidden bugs, unfinished states, silent downgrades, concurrency holes, security drift, stale routes, hidden assumptions. Cross-phase contradiction finder. Read-only. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — cannot mutate |
| **Dispatchable** | YES (confirmed) |
| **Tested** | ✅ |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Planning (before edits) and implementation review (after edits). Any sprint where "what did we miss?" matters. |
| **Forbidden use** | Not a deploy-gate substitute. Not a test runner. |

---

### A2. `backend-safety-reviewer`
| Field | Value |
|---|---|
| **Name** | `backend-safety-reviewer` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\backend-safety-reviewer.md` |
| **Version** | original repo install |
| **Purpose** | Reviews backend routes/services for unsafe writes, false evidence, fake paths, missing idempotency, missing `_normalise_X` boundary helpers (Lesson A). |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — cannot mutate |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Planning + implementation review on any change touching `service/app/api/**` or services. Mandatory for write-risk backend PRs. |
| **Forbidden use** | Pure frontend-only changes. Not a deploy-gate substitute. |

---

### A3. `frontend-flow-reviewer`
| Field | Value |
|---|---|
| **Name** | `frontend-flow-reviewer` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\frontend-flow-reviewer.md` |
| **Version** | original repo install |
| **Purpose** | Reviews dashboard/V2 pages for broken operator flow, hidden actions, direct unsafe API calls, missing disabled reasons. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — cannot mutate |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Any UI change (V2 shell pages, dashboard). Pairs with the `frontend-design` skill. Pairs with browser smoke (GATE 6). |
| **Forbidden use** | Backend-only changes. |

---

### A4. `security-write-action-reviewer`
| Field | Value |
|---|---|
| **Name** | `security-write-action-reviewer` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\security-write-action-reviewer.md` |
| **Version** | original repo install |
| **Purpose** | Reviews write actions for readiness gates, confirmation, idempotency, audit trace. The write-risk reviewer for wFirma/inventory/email/customs writes. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — cannot mutate (guards others that can) |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Mandatory on any PR introducing or modifying a write action (POST/PUT/PATCH/DELETE, wFirma push, inventory transition, email send). |
| **Forbidden use** | Read-only/observer surfaces where zero write risk exists (optional there). |

---

### A5. `test-coverage-reviewer`
| Field | Value |
|---|---|
| **Name** | `test-coverage-reviewer` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\test-coverage-reviewer.md` |
| **Version** | original repo install |
| **Purpose** | Reviews tests for missing negative cases and weak source-grep coverage around execution, agents, readiness. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — cannot mutate |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Planning (define test plan) + implementation review (verify coverage). Every sprint. |
| **Forbidden use** | Not a test runner (reviews coverage; does not execute tests). |

---

### A6–A12. 7-Agent Deploy Gate (all INSPECT-ONLY)

All 7 must run in parallel before every production deploy. All verdict-only — none may call
git/Bash/robocopy/sc.exe/Copy-Item. Security blocks cannot be overridden by anyone.

#### A6. `deploy-git-diff-reviewer`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_git_diff_reviewer.md` (dispatch: `deploy-git-diff-reviewer`) |
| **Purpose** | Classifies every changed file by risk level. Flags forbidden paths, Lesson J engine-file gaps. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Gate 1 of the 7-agent deploy gate — always, no exceptions. |
| **Forbidden use** | git commands, Bash, any write — DO NOT call these. |

#### A7. `deploy-backend-impact-reviewer`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_backend_impact_reviewer.md` |
| **Purpose** | Route auth guards, router registration in main.py, service-interface breaks, missing requirements.txt, platform imports, carrier gate. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Gate 2 of the 7-agent deploy gate. |
| **Forbidden use** | Not for planning; not standalone reviewer. |

#### A8. `deploy-persistence-storage-reviewer`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_persistence_storage_reviewer.md` |
| **Purpose** | Schema mutations (CREATE/ALTER/DROP TABLE), storage path writes, hardcoded prod paths, missing migration plan. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Gate 3. Any deploy touching DB/storage. |
| **Forbidden use** | Bash, storage file writes. |

#### A9. `deploy-security-reviewer`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_security_reviewer.md` |
| **Purpose** | Credential exposure, auth guard removal/bypass, carrier gate bypass, injection, committed secrets. Security blocks cannot be overridden by anyone. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only (its blocks are CRITICAL authority) |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Gate 4. Every deploy. Security block = absolute stop. |
| **Forbidden use** | Cannot be overridden. Do not modify security config. |

#### A10. `deploy-qa-reviewer`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_qa_reviewer.md` |
| **Purpose** | Verifies PZ regression (160 required) + carrier suite (≥381) from PRE-RUN output. Any failure = unconditional block. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Gate 5. Receives pre-run test output. Do not run tests inside this agent. |
| **Forbidden use** | Running tests. Bash. |

#### A11. `deploy-release-manager`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_release_manager.md` |
| **Purpose** | Branch hygiene, exact rollback command for the deploy SHA, robocopy sync plan, post-deploy verification checklist. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Gate 6. Produces the exact deploy + rollback script (which operator then runs). |
| **Forbidden use** | DO NOT call sc.exe, robocopy, git push, gh, Write/Edit. |

#### A12. `deploy-lead-coordinator`
| Field | Value |
|---|---|
| **Source** | REPO · `deploy_lead_coordinator.md` |
| **Purpose** | Collects findings from other 6, resolves conflicts, issues the written GO / NO-GO. Final authority for the deploy step. Cannot override a security block. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW — verdict only |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_DEPLOY_SUPPORT |
| **Recommended use** | Always last in the 7-agent gate. Synthesises all 6 verdicts. |
| **Forbidden use** | Bash, git, robocopy, sc.exe. Cannot override deploy-security-reviewer blocks. |

---

### A13. `adr-historian`
| Field | Value |
|---|---|
| **Name** | `adr-historian` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\adr-historian.md` |
| **Version** | original repo install |
| **Purpose** | Drafts new ADRs from coordinator-approved decisions; maintains the ADR index. Append-only; never rewrites historical ADRs. |
| **Tools granted** | Read, Grep, Glob, Write, Edit |
| **R/W level** | DOCS-WRITE — scoped to `.claude/adr/` only |
| **Production risk** | LOW — cannot touch product code |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_READ_ONLY (effectively) |
| **Recommended use** | Post-run governance — only when an architecture decision was made during the task. |
| **Forbidden use** | Editing product code. Routine sprints without architectural decisions. Rewriting existing ADRs. |

---

### A14. `agent-performance-observer`
| Field | Value |
|---|---|
| **Name** | `agent-performance-observer` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\agent-performance-observer.md` |
| **Version** | original repo install |
| **Purpose** | Scores each subagent on 6 dimensions after a FINAL REPORT. Produces scorecards. Surfaces NEEDS-TUNING verdicts (GATE 4 salvage). Self-evaluates on 7-day cadence (RULE 5). |
| **Tools granted** | Read, Grep, Glob, Bash, Write |
| **R/W level** | DOCS-WRITE + EXEC — scoped to `.claude/memory/scorecards/` |
| **Production risk** | LOW — cannot touch product code |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_READ_ONLY (effectively) |
| **Recommended use** | Mandatory after any report with ≥3 subagents or FINAL REPORT (RULE 2). Orchestrator MUST verify file exists on disk post-write (Lesson C). |
| **Forbidden use** | Mid-task. Never to mutate agent prompts. |

---

### A15. `flow-context-keeper`
| Field | Value |
|---|---|
| **Name** | `flow-context-keeper` |
| **Source** | REPO · `C:\PZ-verify\.claude\agents\flow-context-keeper.md` |
| **Version** | original repo install |
| **Purpose** | Maintains `PROJECT_STATE.md` (FACTS/DECISIONS/ASSUMPTIONS/OPEN QUESTIONS). FACTS append-only. Must record every scorecard produced by observer (RULE 6). |
| **Tools granted** | Read, Grep, Glob, Bash, Write, Edit |
| **R/W level** | DOCS-WRITE + EXEC — scoped to `.claude/memory/PROJECT_STATE.md` |
| **Production risk** | LOW — cannot touch product code |
| **Dispatchable** | YES |
| **Tested** | ✅ |
| **Classification** | SAFE_READ_ONLY (effectively) |
| **Recommended use** | After observer (RULE 3), after any PR merges to main, after any issue closes, on `/update-state`. Must validate every cited scorecard exists on disk. |
| **Forbidden use** | Mid-task. Editing product code. Demoting FACTS to ASSUMPTIONS. |

---

### A16–A20. Installed 2026-06-06 (Lesson-B fresh-session pending)

> These 5 agents exist in the repo as inspect-only copies, but due to Lesson B (mid-session
> agent registry refresh), the USER-LEVEL copies (with Bash) may dispatch instead until a
> fresh session is opened. Treat as runtime-backed until confirmed.

#### A16. `reviewer-challenge`
| Field | Value |
|---|---|
| **Source** | REPO · `reviewer-challenge.md` (also USER-level copy exists) |
| **Purpose** | Devil's advocate — attacks weak plans before implementation. Finds hidden risks, false assumptions, fake UI, missing backend, bad abstractions. CLAUDE.md-mandated on all V2 PRs. |
| **Tools granted** | Read, Grep, Glob (repo copy; user copy adds Bash) |
| **R/W level** | INSPECT-ONLY (repo copy) |
| **Production risk** | LOW |
| **Dispatchable** | YES (confirmed — dispatches successfully) |
| **Tested** | ✅ (ran repo copy per dispatch test) |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Every V2 PR (CLAUDE.md Lesson F §8). Every incident fix (Lesson I). Every plan before implementation. |
| **Forbidden use** | Not a substitute for the deploy gate. |

#### A17. `ux-flow`
| Field | Value |
|---|---|
| **Source** | REPO · `ux-flow.md` (also USER-level) |
| **Purpose** | Checks whether UI actually makes sense for a real operator. Finds confusing buttons, dead paths, missing next actions, unclear labels, orphan states. |
| **Tools granted** | Read, Grep, Glob |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW |
| **Dispatchable** | PENDING (Lesson B) |
| **Tested** | ⚠️ |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Alongside frontend-flow-reviewer on any UI sprint. Pairs with frontend-design skill. |
| **Forbidden use** | Backend-only changes. Not a substitute for browser verification (GATE 6). |

#### A18. `integration-boundary`
| Field | Value |
|---|---|
| **Source** | REPO · `integration-boundary.md` (Bash stripped from repo copy) |
| **Purpose** | Checks that frontend, backend, storage, DHL, wFirma, email, and documents connect without fake assumptions. Detects gaps where systems should integrate but don't. |
| **Tools granted** | Read, Grep, Glob (Bash stripped in repo copy) |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW |
| **Dispatchable** | PENDING (Lesson B; user copy runs Bash) |
| **Tested** | ⚠️ |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | After implementation, before PR opens. Verifies real wiring vs assumed wiring. |
| **Forbidden use** | Not an implementation agent. |

#### A19. `gap-detection`
| Field | Value |
|---|---|
| **Source** | REPO · `gap-detection.md` (Bash stripped) |
| **Purpose** | Searches for hidden gaps BEFORE work begins. Unclear instructions, missing context, missing files, missing backend endpoints, missing business rules, missing test coverage, fake/placeholder risk. |
| **Tools granted** | Read, Grep, Glob (Bash stripped in repo copy) |
| **R/W level** | INSPECT-ONLY |
| **Production risk** | LOW |
| **Dispatchable** | PENDING (Lesson B) |
| **Tested** | ⚠️ |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | First detection layer after intake on every non-trivial task. |
| **Forbidden use** | Not a build agent. |

#### A20. `final-consistency-review`
| Field | Value |
|---|---|
| **Source** | REPO · `final-consistency-review.md` (Bash stripped; user copy still Bash-capable per Lesson B test) |
| **Purpose** | Final gate before result returns to operator. Verifies no incomplete work, no fake assumptions, no disconnected UI, no missing backend, no broken tests, no uncommitted confusion. |
| **Tools granted** | Read, Grep, Glob (Bash stripped in repo copy) |
| **R/W level** | INSPECT-ONLY (repo copy; ⚠️ user copy confirmed Bash-capable by dispatch test) |
| **Production risk** | LOW (repo copy); MEDIUM risk of running wrong copy |
| **Dispatchable** | YES (confirmed — but ran user-level Bash copy, not repo inspect-only) |
| **Tested** | ⚠️ LESSON B: user-level copy ran, not repo copy |
| **Classification** | SAFE_REVIEW |
| **Recommended use** | Last check after release-manager, before operator receives output. |
| **Forbidden use** | Mid-task. Not a build agent. |

---

## PART B — User-Level Runtime Agents (NOT canonical)

Source: `C:\Users\Super Fashion\.claude\agents\` · **NOT version-controlled in this project.**
Final authority: **NO** · Use as read helper only after independent verification.

### B1. Read-Only Helpers (INSPECT tier — safe as helpers)

| Agent | Tools | Purpose | Recommended use (helper only) | Classification |
|---|---|---|---|---|
| chief-orchestrator | R/G/G | Master router/coordinator | Planning helper | SAFE_READ_ONLY |
| agent-router | R/G/G | Maps task → agent list | Planning helper | SAFE_READ_ONLY |
| natural-language-intake | R/G/G | Parse rough operator input | Intake helper | SAFE_READ_ONLY |
| intent-clarification | R/G/G | Said-vs-wanted separation | Intake helper | SAFE_READ_ONLY |
| task-classification | R/G/G | Classify work type | Intake helper | SAFE_READ_ONLY |
| context-resolution | R/G/G | Resolve vague references | Planning helper | SAFE_READ_ONLY |
| assumption-builder | R/G/G | Document assumptions | Planning helper | SAFE_READ_ONLY |
| misunderstanding-prevention | R/G/G | Pre-code interpretation check | Planning helper | SAFE_READ_ONLY |
| product-owner-interpreter | R/G/G | Business goal → scope | Planning helper | SAFE_READ_ONLY |
| planning-task-breakdown | R/G/G | Impl plan / file map | Planning helper | SAFE_READ_ONLY |
| system-architect | R/G/G/WF | Tech-structure design | Planning helper | SAFE_READ_ONLY |
| reviewer-challenge | R/G/G | Devil's-advocate plan attack | Review helper | SAFE_REVIEW |
| flow-continuity | R/G/G/B | End-to-end chain check | Review helper | SAFE_REVIEW |
| integration-boundary | R/G/G/B | FE/BE/storage seam check | Review helper | SAFE_REVIEW |
| final-consistency-review | R/G/G/B | Last-gate completeness | Review helper | SAFE_REVIEW |
| escalation-filter | R/G/G | Block needless operator pings | Governance helper | SAFE_READ_ONLY |
| multimodal-evidence | R/G/G | Read screenshots/PDFs | Evidence helper | SAFE_READ_ONLY |
| readiness-closure | R/G/G | Status/gate determination | Review helper | SAFE_READ_ONLY |
| ux-flow | R/G/G | UX sanity of UI | Review helper | SAFE_REVIEW |
| button-functionality | R/G/G/B | "every button works" audit | Review helper | SAFE_REVIEW |
| finance-accounting-logic | R/G/G | Accounting-treatment review | Review helper | SAFE_READ_ONLY |
| compliance | R/G/G/WF/WS | VAT/AML/audit review | Review helper | SAFE_READ_ONLY |
| security-permissions | R/G/G/B | Credential/write-gate review | Review helper | SAFE_REVIEW |
| deployment-readiness | R/G/G/B | E2E execution report | Governance helper | SAFE_DEPLOY_SUPPORT |
| release-manager | R/G/G/B | Go/no-go synthesis (generic) | Use REPO deploy-release-manager instead | SAFE_DEPLOY_SUPPORT |
| business-process | R/G/G | Business-reality converter | Planning helper | SAFE_READ_ONLY |
| ci-runner | R/B/G/G | Run CI locally | Orchestrator runs CI directly | SAFE_REVIEW |
| pr-author | R/B/G/G/WF | Create PRs via gh | Orchestrator authors PRs | SAFE_REVIEW |

### B2. Write-Capable (QUARANTINED — NOT safe as actors)

> These agents can write product files and/or call live APIs. They match EJ write-risk domains.
> **Never use as autonomous actors. Never as final authority. Consultation only after independent verification.**

| Agent | Tools | Domain | Why quarantined | Classification |
|---|---|---|---|---|
| **dhl-customs** | R/W/E/B/WF | DHL/customs | Can mutate DHL workflow + web-fetch — Lane A/B authority is the engine | CUSTOMS_RISK |
| **wfirma-integration** | R/W/E/B/WF | wFirma | Can issue live wFirma API writes (financial) | FINANCIAL_RISK |
| **pz-purchase-accounting** | R/W/E/B | PZ | Can mutate goods receipt / wFirma docs | FINANCIAL_RISK |
| **sales-proforma** | R/W/E/B | proforma | Can mutate proforma/invoice | FINANCIAL_RISK |
| **inventory-state-machine** | R/W/E/B | inventory | Can mutate inventory state transitions | PRODUCTION_RISK |
| **warehouse-ops** | R/W/E/B | warehouse | Can mutate scan/stock records | PRODUCTION_RISK |
| **client-contractor-mapping** | R/W/E/B/WF | customer master | Can mutate contractor master + wFirma | FINANCIAL_RISK |
| **email-evidence-recovery** | R/W/E/B | email | Email path — Lesson E 5 safety properties | PRODUCTION_RISK |
| **database-storage** | R/W/E/B | storage/schema | Can mutate schema/storage | PRODUCTION_RISK |
| **deployment-windows-ops** | R/W/E/B | deploy/service | Can touch NSSM/.env/service — full production blast radius | PRODUCTION_RISK |
| **document-intelligence** | R/W/E/B | doc parsing | Write-capable | WRITE_RISK |
| **dashboard-operations** | R/W/E | dashboard | Write-capable | WRITE_RISK |
| **backend-api** | R/W/E/B | generic backend | Can edit product backend (generic, wrong-stack defaults) | WRITE_RISK |
| **frontend-ui** | R/W/E/B | generic frontend | Can edit frontend; defaults to TypeScript+Tailwind (wrong stack) | WRITE_RISK |
| **git-workflow** | R/W/E/B | git | Can branch/commit/push | PRODUCTION_RISK |
| **testing-verification** | R/W/E/B | tests | Can write/run tests | WRITE_RISK |
| **browser-verifier** | R/W/E/B | browser QA | Write+exec; orchestrator drives via Preview MCP instead | WRITE_RISK |
| **memory-lessons** | R/W/E | memory | Can write memory files | WRITE_RISK |
| **prompt-engineering** | R/W/E | prompts | Can rewrite agent prompts | WRITE_RISK |
| **legal-argument-builder** | R/W/E | legal | WRONG DOMAIN | UNKNOWN |
| **legal-case-intake** | R/W/E | legal | WRONG DOMAIN | UNKNOWN |
| **legal-drafting** | R/W/E | legal | WRONG DOMAIN | UNKNOWN |
| **legal-evidence-binder** | R/W/E | legal | WRONG DOMAIN | UNKNOWN |

---

## PART C — Built-In Agents

| Agent | Source | Purpose | Classification |
|---|---|---|---|
| `claude` | BUILTIN | Default general-purpose | SAFE_READ_ONLY |
| `general-purpose` | BUILTIN | Open-ended research, multi-step | SAFE_IMPLEMENTATION |
| `Explore` | BUILTIN | Fast read-only codebase search | SAFE_READ_ONLY |
| `Plan` | BUILTIN | Software architecture / planning | SAFE_READ_ONLY |
| `statusline-setup` | BUILTIN | Configure Claude Code status line | SAFE_READ_ONLY |
| `claude-code-guide` | BUILTIN | Claude Code / SDK / API questions | SAFE_READ_ONLY |

---

## PART D — Plugin Agents (WRONG DOMAIN)

| Agent family | Source | Domain | EJ-applicable | Classification |
|---|---|---|---|---|
| `brand-voice:conversation-analysis` | PLUGIN | Brand/marketing | NO | UNKNOWN |
| `brand-voice:discover-brand` | PLUGIN | Brand/marketing | NO | UNKNOWN |
| `brand-voice:document-analysis` | PLUGIN | Brand/marketing | NO | UNKNOWN |
| `brand-voice:quality-assurance` | PLUGIN | Brand/marketing | NO | UNKNOWN |
| `brand-voice:content-generation` | PLUGIN | Brand/marketing | NO | UNKNOWN |

---

## Classification Key

| Code | Meaning |
|---|---|
| SAFE_READ_ONLY | Inspect/read only. Cannot mutate anything. Zero production risk. |
| SAFE_REVIEW | Review only. Returns findings/verdicts. Cannot mutate product files. |
| SAFE_DEPLOY_SUPPORT | Deploy-gate reviewer. Verdict only. Cannot execute deploys. |
| SAFE_IMPLEMENTATION | Can write code files under operator oversight. Gate-bound. |
| WRITE_RISK | Can write files. Requires operator oversight. Not for autonomous use. |
| FINANCIAL_RISK | Touches wFirma/accounting/proforma/invoice writes. Requires explicit safety review. |
| CUSTOMS_RISK | Touches DHL/customs/MRN. Requires explicit safety review. |
| PRODUCTION_RISK | Touches NSSM/service/inventory/deploy. Highest blast radius. |
| UNKNOWN | Unverified domain or wrong-domain. Do not dispatch for EJ work. |

---

## Safety contract (binding)

1. **Only repo agents (Part A) may be final authority** on any production-affecting decision.
2. **User-level agents (Part B) are helpers only** — outputs must be independently verified before influencing any production decision (Lesson B).
3. **No runtime-only agent may mutate production**, issue wFirma writes, or trigger deploys.
4. **GATE 6 (browser verification) remains orchestrator-driven** via Preview MCP — no repo browser-verification agent exists; this is an accepted gap (RUNTIME_AGENT_AUDIT §D).
5. **Lesson B (fresh-session rule)**: A16–A20 are repo-installed but mid-session the user-level copies may dispatch. A fresh Claude Code session is required to confirm repo precedence.
