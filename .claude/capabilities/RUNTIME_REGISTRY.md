# RUNTIME_REGISTRY.md — Atlas V2 Capability Registry: Runtime Capabilities

**Generated:** 2026-06-06 · **Source:** RUNTIME_AGENT_AUDIT.md + AGENT_REGISTRY.md + session dispatch metadata
**Canonical tree:** `C:\PZ-verify` · No product code modified.

> This document maps the **full runtime dispatch surface** — everything that can be invoked
> in a Claude Code session. It distinguishes canonical (version-controlled) from runtime-only
> capabilities, and identifies hazards in the dispatch menu.

---

## Runtime Counts

| Bucket | Count | Source of truth |
|---|---|---|
| Repo-installed canonical agents | 20 | `C:\PZ-verify\.claude\agents\` |
| User-level runtime agents | 54 | `C:\Users\Super Fashion\.claude\agents\` |
| Built-in agents | ~6 | Claude Code built-ins |
| Plugin agents | 5 | brand-voice marketplace plugin |
| **Total dispatchable `subagent_type`** | **≈85** | sum |
| Active MCP connectors | 21 | this session deferred-tools list |
| Repo skills | 3 | `C:\PZ-verify\.claude\skills\` |
| User skills | 1 | `C:\Users\Super Fashion\.claude\skills\` |
| Repo commands | 8 | `C:\PZ-verify\.claude\commands\` |
| User commands | 4 | `C:\Users\Super Fashion\.claude\commands\` |

---

## Dispatch Readiness (by agent)

### Confirmed Dispatchable (repo-canonical)

| Agent | Dispatch test result | Notes |
|---|---|---|
| `gap-hunter` | ✅ confirmed | R/G/G inspect-only |
| `backend-safety-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `frontend-flow-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `security-write-action-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `test-coverage-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `deploy-git-diff-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `deploy-backend-impact-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `deploy-persistence-storage-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `deploy-security-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `deploy-qa-reviewer` | ✅ confirmed | R/G/G inspect-only |
| `deploy-release-manager` | ✅ confirmed | R/G/G inspect-only |
| `deploy-lead-coordinator` | ✅ confirmed | R/G/G inspect-only |
| `adr-historian` | ✅ confirmed | R/G/G/W/E docs-write |
| `agent-performance-observer` | ✅ confirmed | R/G/G/B/W docs-write |
| `flow-context-keeper` | ✅ confirmed | R/G/G/B/W/E docs-write |
| `reviewer-challenge` | ✅ confirmed — ⚠️ Lesson B | May run user-level copy mid-session |
| `ux-flow` | ⚠️ Lesson B pending | Repo copy unconfirmed; user-level copy dispatches |
| `integration-boundary` | ⚠️ Lesson B pending | User copy has Bash; repo copy Bash-stripped |
| `gap-detection` | ⚠️ Lesson B pending | User copy has Bash; repo copy Bash-stripped |
| `final-consistency-review` | ✅ dispatched — ⚠️ ran USER COPY | User-level Bash-capable copy ran, not repo inspect-only |

### Key Runtime-Only Agents (usable as helpers)

| Agent | Dispatch status | EJ-safe use |
|---|---|---|
| system-architect | ✅ runtime | Read helper for planning |
| planning-task-breakdown | ✅ runtime | Read helper for planning |
| product-owner-interpreter | ✅ runtime | Read helper for intake |
| reviewer-challenge | ✅ runtime (also repo) | Review helper (also available as repo A16) |
| readiness-closure | ✅ runtime | Review helper |
| ux-flow | ✅ runtime (also repo) | Review helper |
| button-functionality | ✅ runtime | Review helper |
| finance-accounting-logic | ✅ runtime | Read helper (read-only) |
| compliance | ✅ runtime | Read helper (read-only) |
| security-permissions | ✅ runtime | Review helper |
| browser-verifier | ✅ runtime | **NOT as actor** — orchestrator drives via Preview MCP instead |
| ci-runner | ✅ runtime | Helper only (orchestrator usually runs CI directly) |
| pr-author | ✅ runtime | Helper only (orchestrator authors PRs via `gh`) |

---

## Hazard Map — Runtime-Only Write-Capable Agents

> These agents are one `subagent_type` call away from autonomous production mutation.
> The dispatch menu does not warn you. This registry makes the specific danger explicit.

| Agent | What it can do WITHOUT additional gates | Blast radius |
|---|---|---|
| `dhl-customs` | Mutate DHL workflow state, fetch real customs data via web, call DHL API | Customs flow corruption |
| `wfirma-integration` | Issue live wFirma API calls (POST/PUT) — create invoices, update records | Financial mutation (irreversible) |
| `pz-purchase-accounting` | Create/modify PZ documents in wFirma | Financial mutation |
| `sales-proforma` | Create/modify proforma invoices | Financial mutation |
| `inventory-state-machine` | Transition inventory states | Inventory corruption |
| `warehouse-ops` | Write scan records, modify stock | Inventory corruption |
| `client-contractor-mapping` | Create/update contractor records in wFirma | Customer master corruption |
| `email-evidence-recovery` | Compose and route emails (Lesson E scope) | Live SMTP send if misconfigured |
| `database-storage` | Execute schema migrations, DROP TABLE | Irreversible data loss |
| `deployment-windows-ops` | Restart NSSM service, modify `.env`, run robocopy | Full production blast |
| `backend-api` | Edit any backend `.py` file | Product code corruption |
| `frontend-ui` | Edit any frontend file (defaults to wrong stack) | Product code corruption + wrong-stack drift |
| `git-workflow` | Create branches, commit, push to remote | Repo state corruption |
| `testing-verification` | Write and execute tests | Test suite corruption |

**Mitigation in force:** CLAUDE.md GATES 1–6; per-sprint scope isolation; orchestrator-level
prompt boundaries; explicit `-DO NOT call X` language in all dispatched prompts (Lesson K).

---

## Runtime Capabilities by Phase

### Phase: Intake / Planning

| Capability | Type | Canonical? | Recommended action |
|---|---|---|---|
| Read PROJECT_STATE.md | Direct Read tool | N/A (orchestrator) | Always first (RULE 1) |
| `gap-detection` (A19) | Agent | YES (repo, Lesson-B) | Pre-work gap scan |
| `gap-hunter` (A1) | Agent | YES (repo) | Hidden bugs / contradictions |
| `system-architect` (runtime) | Agent | NO | Planning helper |
| `planning-task-breakdown` (runtime) | Agent | NO | File impact map |
| `product-owner-interpreter` (runtime) | Agent | NO | Business → scope |
| `/inspect-route` (C1) | Command | YES (repo) | Endpoint authority audit |
| `/pz-audit-roadmap` (C2) | Command | YES (repo) | Full codebase audit |
| `/engineering-lessons` (C4) | Command | YES (repo) | Lesson reference |

### Phase: Implementation Review (Pre-PR)

| Capability | Type | Canonical? | Recommended action |
|---|---|---|---|
| `reviewer-challenge` (A16) | Agent | YES (repo/Lesson-B) | **Mandatory on V2 PRs** |
| `backend-safety-reviewer` (A2) | Agent | YES (repo) | Backend changes |
| `frontend-flow-reviewer` (A3) | Agent | YES (repo) | Frontend changes |
| `security-write-action-reviewer` (A4) | Agent | YES (repo) | Write-risk domains |
| `test-coverage-reviewer` (A5) | Agent | YES (repo) | Test coverage |
| `ux-flow` (A17) | Agent | YES (repo/Lesson-B) | UI/UX quality |
| `integration-boundary` (A18) | Agent | YES (repo/Lesson-B) | FE/BE seam |
| `final-consistency-review` (A20) | Agent | YES (repo/⚠️Lesson-B) | Pre-operator gate |
| `/review-execution` (C5) | Command | YES (repo) | Execution-path review |
| `frontend-design` skill (S1) | Skill | YES (repo) | UI standard check |

### Phase: Browser Verification (GATE 6)

| Capability | Type | Canonical? | Recommended action |
|---|---|---|---|
| Claude Preview MCP (CN10) | Connector | N/A | Start dev server, screenshot, console/network |
| `atlas-v2-render-gate` skill (S2) | Skill | YES (repo) | Post-deploy eyeball checklist |
| Claude in Chrome (CN11) | Connector | N/A | Optional: DOM inspection, form testing |
| Computer Use (CN13) | Connector | N/A | Native desktop QA if needed |

### Phase: Production Deploy

| Capability | Type | Canonical? | Recommended action |
|---|---|---|---|
| `deploy-git-diff-reviewer` (A6) | Agent | YES (repo) | Mandatory gate — run in parallel |
| `deploy-backend-impact-reviewer` (A7) | Agent | YES (repo) | Mandatory gate — run in parallel |
| `deploy-persistence-storage-reviewer` (A8) | Agent | YES (repo) | Mandatory gate — run in parallel |
| `deploy-security-reviewer` (A9) | Agent | YES (repo) | Mandatory gate — run in parallel |
| `deploy-qa-reviewer` (A10) | Agent | YES (repo) | Mandatory gate — run in parallel |
| `deploy-release-manager` (A11) | Agent | YES (repo) | Mandatory gate — run in parallel |
| `deploy-lead-coordinator` (A12) | Agent | YES (repo) | LAST — synthesises all verdicts |
| `/deploy` (C8) | Command | YES (repo) | Invokes the full gate pipeline |
| Computer Use (CN13) | Connector | N/A | Execute robocopy sync to C:\PZ |

### Phase: Post-Run Governance (RULES 2/3/6)

| Capability | Type | Canonical? | Recommended action |
|---|---|---|---|
| `agent-performance-observer` (A14) | Agent | YES (repo) | **Mandatory after FINAL REPORT (RULE 2)** |
| `flow-context-keeper` (A15) | Agent | YES (repo) | **After observer (RULE 3)** |
| `adr-historian` (A13) | Agent | YES (repo) | After architectural decisions only |
| Zoho Cliq (CN1) | Connector | N/A | PZ batch result posting |
| Zoho WorkDrive (CN4) | Connector | N/A | PDF/XLSX upload + share links |

### Phase: EJ Domain Operations

| Capability | Type | Canonical? | Recommended action |
|---|---|---|---|
| `/pz-shipment` (C7) | Command | YES (repo) | Live batch run — operator approval required |
| `/cowork-integration` (C3) | Command | YES (repo) | Cowork architecture reference |
| Zoho Mail admin (CN5) | Connector | N/A | Email evidence (read-only path) |
| Zoho CRM (CN8) | Connector | N/A | Customer/contractor lookup (read-only) |
| PDF Viewer plugin (P6) | Plugin | N/A | Customs document reading |

---

## One-Session Rule (ENFORCED)

Only one Claude Code session may operate against `C:\PZ-verify` at a time.
A second concurrent session on the same tree races branch state and produces duplicate commits.
(Incident 2026-06-04: two sessions → `0c22cfb` direct-to-main + `6ad62a6` competing branch.)

A second session must be:
- Read-only (no commits, no writes), OR
- Operating on a separate git worktree

Source: CLAUDE.md "working-tree convention" rule 6.

---

## Fresh-Session Rule (Lesson B)

After any PR that adds new agent files to `.claude/agents/`, the current session's
dispatch registry does NOT automatically reload. New agent files will NOT be invocable
in the current session. They become available in the **next Claude Code session** only.

Applies to: A16–A20 (installed 2026-06-06 in a prior session).
Status: pending fresh-session confirmation of project-over-user precedence.

---

## Capability Gaps (Known + Accepted)

| Gap | Impact | Status | Recommendation |
|---|---|---|---|
| No repo browser-verification agent | GATE 6 is orchestrator-driven, not agent-driven | **ACCEPTED** — Preview MCP is the path | File as candidate; do not auto-install (needs Bash/exec) |
| A16–A20 Lesson-B dispatch uncertainty | May run user-level copies (with Bash) instead of repo copies (inspect-only) | **TRACKED** — fresh-session confirmation pending | Open new session to verify repo precedence |
| No repo CI runner | Orchestrator runs `make verify` directly via Bash | **ACCEPTED** — no agent needed | Non-issue |
| No repo git agent | Orchestrator issues git commands directly | **ACCEPTED** — git-workflow is runtime helper | Non-issue |
| No repo PR author | Orchestrator uses `gh` CLI directly | **ACCEPTED** — pr-author is runtime helper | Non-issue |
