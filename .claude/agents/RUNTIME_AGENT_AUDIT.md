# RUNTIME_AGENT_AUDIT.md — Full Agent / Subagent / Skill / Command Audit

**Audit/documentation only.** Generated 2026-06-06 by direct filesystem +
runtime-metadata inspection. No product code changed, no deploy, no production
mutation. Companion to `AGENT_REGISTRY.md` (canonical 15) and the
`agent-orchestration-playbook.md`.

---

## Method & sources inspected

| Source | What it gave |
|---|---|
| `C:\PZ-verify\.claude\agents\*.md` | 15 **repo-installed** (canonical, version-controlled) agents — `tools:` frontmatter read directly |
| `C:\Users\Super Fashion\.claude\agents\*.md` | **54 user-level** runtime agents — `tools:` frontmatter read directly |
| Task/Agent tool runtime metadata (system prompt registry) | the dispatchable `subagent_type` menu + built-ins + plugin agents |
| `.claude/skills/` · `.claude/commands/` · `CLAUDE.md` · `PROJECT_STATE.md` | skills (3), commands (8), governance context |

Note: `/agents`, `/skills`, `/commands`, `/tasks` are interactive Claude Code CLI
commands not invocable from the model tool-set; their underlying data was obtained
by reading the filesystem + the Agent-tool registry metadata, which is authoritative
for dispatch.

---

## Counts (verified)

| Bucket | Count | Source |
|---|---|---|
| **Repo-installed (canonical)** | **15** | `C:\PZ-verify\.claude\agents` |
| **User-level (runtime-only)** | **54** | `~/.claude/agents` |
| **Built-in / helper** | ~6 | `claude`, `general-purpose`, `Explore`, `Plan`, `statusline-setup`, `claude-code-guide` |
| **Plugin (brand-voice family)** | 5 | marketplace plugin, not this repo |
| **Total dispatchable `subagent_type`** | **≈ 80** | sum of the above |
| **Overlap: repo ∩ dispatchable** | **15** | all repo agents are dispatchable |
| **Overlap: repo ∩ user-level** | **0** (as of 2026-06-06) | clean separation — no name collision. **SUPERSEDED 2026-07-08:** the `AGENT_REGISTRY.md` 2026-07-08 refresh found **5** repo∩user name overlaps (`final-consistency-review`, `gap-detection`, `integration-boundary`, `reviewer-challenge`, `ux-flow`) after 7 agents were added to the repo. Both facts preserved — the "0" was accurate on 2026-06-06; the "5" is current. |

**Plus skills:** 3 · **commands:** 8 (see SKILL_REGISTRY.md / COMMAND_REGISTRY.md).

---

## The 12 questions — answered

1. **Repo-installed agents:** 15.
2. **Runtime-dispatchable subagents:** ≈80 (15 repo + 54 user-level + ~6 built-in + 5 plugin).
3. **Project-specific:** the 15 repo agents (canonical) PLUS ~17 user-level EJ-domain-named agents (dhl-customs, wfirma-integration, pz-purchase-accounting, sales-proforma, inventory-state-machine, warehouse-ops, client-contractor-mapping, finance-accounting-logic, compliance, document-intelligence, email-evidence-recovery, dashboard-operations, button-functionality, deployment-windows-ops, readiness-closure, ux-flow, integration-boundary) — **but only the 15 repo agents are version-controlled / canonical.** The user-level EJ-named agents are project-*relevant* but runtime-only and unverified.
4. **Generic / runtime-only:** built-ins (claude, general-purpose, Explore, Plan, statusline-setup, claude-code-guide), generic process agents (chief-orchestrator, agent-router, natural-language-intake, intent-clarification, task-classification, context-resolution, assumption-builder, misunderstanding-prevention, product-owner-interpreter, system-architect, planning-task-breakdown, reviewer-challenge, gap-detection, flow-continuity, integration-boundary, final-consistency-review, deployment-readiness, security-permissions, release-manager, ci-runner, pr-author, escalation-filter, multimodal-evidence, memory-lessons, prompt-engineering), the **6 legal-\* agents (wrong domain)**, and the **5 brand-voice:\* plugin agents (wrong domain)**.
5. **Inspect-only:** all 12 inspect-only repo agents + ~30 read-only user-level agents (see table §A).
6. **Can write files:** 3 repo (docs-scoped: adr-historian, agent-performance-observer, flow-context-keeper) + **23 user-level write-capable** (see table §B — the risk surface).
7. **Can run Bash:** 2 repo (agent-performance-observer, flow-context-keeper) + ~33 user-level (all Write-capable ones plus ci-runner, gap-detection, button-functionality, flow-continuity, deployment-readiness, final-consistency-review, release-manager, security-permissions, integration-boundary, pr-author).
8. **Safe for EJ/Atlas V2:** the **15 repo agents** (canonical; 12 inspect-only + 3 docs-scoped). User-level agents are usable ONLY as independently-verified read helpers; **write-capable user-level agents are NOT safe as actors** (§B).
9. **Must never be final authority:** **every runtime-only agent** — all 54 user-level + all built-in + all plugin. Final authority rests with repo agents → the deploy gate → the operator.
10. **Suitability by function:** see §C matrix.
11. **Missing from repo registry (capability gaps):** browser QA (browser-verifier is runtime-only — yet browser smoke was load-bearing in Sprint 30/31), planning/architecture (system-architect, planning-task-breakdown, reviewer-challenge are runtime-only), CI (ci-runner), PR authoring (pr-author), git workflow (git-workflow), test *execution* (testing-verification). The repo intentionally installs *reviewers*, not *executors* — but **browser-verifier is the one genuine candidate to repo-install** given its proven load-bearing role. See §D.
12. **Stale/incomplete repo registry entries:** none. `AGENT_REGISTRY.md` (created `67707da`) was re-verified against disk frontmatter this audit — all 15 entries accurate, tool grants match. This audit is the companion that enumerates the runtime-only set the registry deliberately excluded.

---

## §A. User-level agents — INSPECT/READ tier (usable as verified helpers)

Source: runtime-only · Final authority: **NO** · Project-safe: as **read helper only, output must be independently verified**.

| Agent | Tools | Purpose (1-line) | Recommended group (helper) |
|---|---|---|---|
| chief-orchestrator | R/G/G | Master router/coordinator | Planning (helper) |
| agent-router | R/G/G | Maps task → agent list | Planning (helper) |
| natural-language-intake | R/G/G | Parse rough operator input | Planning (helper) |
| intent-clarification | R/G/G | Said-vs-wanted separation | Planning (helper) |
| task-classification | R/G/G | Classify work type | Planning (helper) |
| context-resolution | R/G/G | Resolve vague references | Planning (helper) |
| assumption-builder | R/G/G | Document assumptions | Planning (helper) |
| misunderstanding-prevention | R/G/G | Pre-code interpretation check | Planning (helper) |
| product-owner-interpreter | R/G/G | Business goal → scope | Planning (helper) |
| planning-task-breakdown | R/G/G | Impl plan / file map | Planning (helper) |
| system-architect | R/G/G/WF | Tech-structure design | Planning (helper) |
| reviewer-challenge | R/G/G | Devil's-advocate plan attack | Planning / Impl-review (helper) |
| gap-detection | R/G/G/B | Pre-work gap scan | Planning (helper) |
| flow-continuity | R/G/G/B | End-to-end chain check | Impl-review (helper) |
| integration-boundary | R/G/G/B | FE/BE/storage seam check | Impl-review (helper) |
| final-consistency-review | R/G/G/B | Last-gate completeness | Impl-review (helper) |
| escalation-filter | R/G/G | Block needless operator pings | Governance (helper) |
| multimodal-evidence | R/G/G | Read screenshots/PDFs | Planning (helper) |
| readiness-closure | R/G/G | Status/gate determination | Impl-review (helper) |
| ux-flow | R/G/G | UX sanity of UI | Impl-review (helper, EJ-relevant) |
| button-functionality | R/G/G/B | "every button works" audit | Impl-review (helper, EJ-relevant) |
| finance-accounting-logic | R/G/G | Accounting-treatment review | Impl-review (helper, EJ-relevant) |
| compliance | R/G/G/WF/WS | VAT/AML/audit review | Impl-review (helper, EJ-relevant) |
| security-permissions | R/G/G/B | Credential/write-gate review | Impl-review (helper) |
| deployment-readiness | R/G/G/B | E2E execution report | Governance (helper) |
| release-manager | R/G/G/B | Go/no-go synthesis (generic) | **Deploy: use repo deploy-release-manager instead** |
| ci-runner | R/B/G/G | Run CI locally | Helper only (can exec) |
| pr-author | R/B/G/G/WF | Create PRs | Helper only (can exec) |

## §B. User-level agents — WRITE-CAPABLE tier ⚠️ (NOT safe as actors)

Source: runtime-only · Inspect-or-write: **WRITE** · Final authority: **NO** ·
Project-safe as actor: **NO** · Allowed: read-only consultation after independent
verification · **Forbidden: any autonomous file edit, any production mutation,
any use as authority.** These look authoritative and several match EJ write-risk
domains, but none are version-controlled, verified, or gate-bound.

| Agent | Tools | Domain | Why dangerous |
|---|---|---|---|
| **dhl-customs** | R/W/E/B/WF | DHL/customs | ⚠️ can mutate DHL workflow + fetch web — Lane A/B authority is the engine, not this |
| **wfirma-integration** | R/W/E/B/WF | wFirma | ⚠️ can issue wFirma API writes (financial) |
| **pz-purchase-accounting** | R/W/E/B | PZ | ⚠️ can mutate goods receipt / wFirma docs |
| **sales-proforma** | R/W/E/B | proforma | ⚠️ can mutate proforma/invoice |
| **inventory-state-machine** | R/W/E/B | inventory | ⚠️ can mutate inventory transitions |
| **warehouse-ops** | R/W/E/B | warehouse | ⚠️ can mutate scan/stock records |
| **client-contractor-mapping** | R/W/E/B/WF | customer master | ⚠️ can mutate contractor master + wFirma |
| **email-evidence-recovery** | R/W/E/B | email | ⚠️ email path — Lesson E (5 safety properties) |
| **database-storage** | R/W/E/B | storage/schema | ⚠️ can mutate schema/storage |
| **deployment-windows-ops** | R/W/E/B | deploy/service | ⚠️ can touch NSSM/service/.env — production blast radius |
| document-intelligence | R/W/E/B | doc parsing | write-capable |
| dashboard-operations | R/W/E | dashboard | write-capable |
| backend-api | R/W/E/B | generic backend | can edit product backend |
| frontend-ui | R/W/E/B | generic frontend | can edit product frontend (also defaults to TS/Tailwind — wrong stack) |
| git-workflow | R/W/E/B | git | can branch/commit/push |
| testing-verification | R/W/E/B | tests | can write/run tests |
| browser-verifier | R/W/E/B | browser QA | write+exec; the one worth repo-installing (§D) |
| memory-lessons | R/W/E | memory | can write memory files |
| prompt-engineering | R/W/E | prompts | can rewrite prompts |
| legal-argument-builder | R/W/E | legal ❌ | wrong domain |
| legal-case-intake | R/W/E | legal ❌ | wrong domain |
| legal-drafting | R/W/E | legal ❌ | wrong domain |
| legal-evidence-binder | R/W/E | legal ❌ | wrong domain |

## §C. Suitability-by-function matrix (prefer repo / canonical)

| Function | Canonical (repo) choice | Runtime helper (verify, never authority) |
|---|---|---|
| Planning | flow-context-keeper, gap-hunter | system-architect, planning-task-breakdown, reviewer-challenge, product-owner-interpreter, intent-clarification |
| Implementation review | backend-safety-reviewer, frontend-flow-reviewer, gap-hunter | flow-continuity, integration-boundary, final-consistency-review, ux-flow |
| Frontend | frontend-flow-reviewer (review) | frontend-ui (build — runtime-only, wrong-stack default; **do not autopilot**) |
| Backend | backend-safety-reviewer (review) | backend-api (build — runtime-only; **do not autopilot**) |
| Security | security-write-action-reviewer, deploy-security-reviewer | security-permissions (helper) |
| Testing | test-coverage-reviewer (review) | testing-verification (execute — runtime-only) |
| Browser QA | **none in repo** (gap) → use Preview MCP manually (as Sprint 30/31) | browser-verifier (runtime-only) |
| Deploy | the 7 repo deploy-* agents + deploy-lead-coordinator | release-manager, deployment-readiness, ci-runner, pr-author (helpers only) |
| Governance | agent-performance-observer, flow-context-keeper, adr-historian | memory-lessons, escalation-filter, deployment-readiness |

## §D. Gaps & recommendations

- **Browser QA is the one real repo gap.** Browser smoke was load-bearing in Sprint 30 (caught dead write buttons) and Sprint 31 (caught 3 defects), yet there is no repo-installed browser agent — it was done manually via Preview MCP. **Recommendation (future, not now):** consider authoring a repo-installed `browser-verifier` scoped to read-only verification (Preview MCP + console/network inspection), so browser QA becomes canonical rather than runtime-only. File as a candidate, do not auto-create.
- **Wrong-domain noise:** 6 legal-* + 5 brand-voice:* agents are dispatchable but belong to other products. **Never use for EJ.** Their presence is registry clutter, not capability.
- **The dispatch menu is a hazard surface, not a capability win.** ~23 write-capable runtime agents — several named exactly like EJ write-risk domains — are one `subagent_type` typo away from an unverified production-mutating actor. The playbook's "runtime = helpers only" rule is the mitigation; this audit makes the specific danger list explicit.

---

## Per-agent record key (applies to all runtime-only agents above)

```
source:          runtime-only (user-level ~/.claude/agents or built-in/plugin)
final-authority: NO  (only repo agents → deploy gate → operator hold authority)
project-safe:    read-helper-only after independent verification;
                 write-capable ones: NOT safe as actors, NEVER mutate production
forbidden:       autonomous edits, deploys, production mutation, final verdicts,
                 wFirma/customs/inventory/email/storage/service writes
```

## Safety verdict

The 15 repo agents remain the only canonical, version-controlled, gate-bound agents.
Everything else in the ~80-entry dispatch menu is an optional helper at best and a
hazard at worst. **No runtime-only agent may be final authority or mutate production.**
Use the `agent-orchestration-playbook.md` groups; treat the dispatch menu as untrusted.

---

# ADDENDUM — Install & Classification Pass (2026-06-06)

## Install summary

| Metric | Value |
|---|---|
| Repo agents BEFORE | 15 |
| Repo agents AFTER | **20** (+5 installed) |
| Installed this pass | reviewer-challenge, ux-flow, integration-boundary, gap-detection, final-consistency-review |
| Intentionally NOT installed | ~49 user-level (see classification) |
| Quarantined (write-risk) | 12 EJ-domain write-capable + 7 generic write/builders |
| Wrong-domain (never install) | 6 legal-* + 5 brand-voice:* |

All 5 installs were authored **inspect-only (`tools: Read, Grep, Glob`)**; the 3 that
had `Bash` upstream (integration-boundary, gap-detection, final-consistency-review)
had Bash **removed** for repo-canonical safety, with provenance documented in each file.

## Phase-4 dispatchability test (honest result — Lesson B)

| Agent | Dispatched? | Response? | Finding |
|---|---|---|---|
| reviewer-challenge | YES | YES (VERDICT: PASS, named C:\PZ-verify) | R/G/G in both copies — behaviour identical |
| final-consistency-review | YES | YES (VERDICT: PASS) | ⚠️ **ran the USER-LEVEL copy — still reported Bash.** My repo inspect-only (Bash-stripped) copy is NOT the one dispatched this session. |

**Conclusion (Lesson B confirmed):** these names were already dispatchable as
user-level runtime agents, so dispatch "works" — but the **repo copies are not
guaranteed to be the version that runs mid-session**. `final-consistency-review`
proved the user-level (un-stripped, Bash-capable) copy is what dispatched, not the
new repo inspect-only copy. **Fresh-session requirement:** a new Claude Code session
is required to (a) reload the registry and (b) verify whether project-level repo
copies take precedence over the user-level copies of the same name. Until then,
dispatching these 5 names uses the user-level versions; treat tool-stripping as
**pending fresh-session confirmation**, not yet in force.

## Classification of all 54 user-level agents

Status key: SAFE = INSTALL_SAFE · REV = INSTALL_REVIEW_ONLY · NO = DO_NOT_INSTALL · Q = QUARANTINE_WRITE_RISK.
"Installed" = copied into repo this pass.

| Agent | tools | write? | bash? | domain | EJ-safe | status | installed |
|---|---|---|---|---|---|---|---|
| reviewer-challenge | R/G/G | no | no | review | yes | SAFE | ✅ |
| ux-flow | R/G/G | no | no | UI/UX | yes | SAFE | ✅ |
| integration-boundary | R/G/G/B | no | yes→stripped | integration | yes | REV | ✅ |
| gap-detection | R/G/G/B | no | yes→stripped | planning | yes | REV | ✅ |
| final-consistency-review | R/G/G/B | no | yes→stripped | governance | yes | REV | ✅ |
| readiness-closure | R/G/G | no | no | status/gate | yes | SAFE | deferred* |
| business-process | R/G/G | no | no | business | yes | SAFE | deferred* |
| finance-accounting-logic | R/G/G | no | no | accounting | yes(read) | SAFE | deferred* |
| product-owner-interpreter | R/G/G | no | no | planning | yes | SAFE | deferred* |
| planning-task-breakdown | R/G/G | no | no | planning | yes | SAFE | deferred* |
| multimodal-evidence | R/G/G | no | no | evidence | yes | SAFE | deferred* |
| system-architect | R/G/G/WF | no | no(WF) | architecture | yes | REV | deferred* |
| compliance | R/G/G/WF/WS | no | no(WF/WS) | compliance | yes(read) | REV | deferred* |
| button-functionality | R/G/G/B | no | yes | UI audit | yes | REV | deferred* |
| security-permissions | R/G/G/B | no | yes | security | yes | REV | deferred* |
| reviewer-challenge … (above) | | | | | | | |
| assumption-builder | R/G/G | no | no | intake | neutral | NO (generic scaffolding) | — |
| intent-clarification | R/G/G | no | no | intake | neutral | NO (generic scaffolding) | — |
| natural-language-intake | R/G/G | no | no | intake | neutral | NO (generic scaffolding) | — |
| task-classification | R/G/G | no | no | intake | neutral | NO (generic scaffolding) | — |
| context-resolution | R/G/G | no | no | intake | neutral | NO (generic scaffolding) | — |
| misunderstanding-prevention | R/G/G | no | no | intake | neutral | NO (generic scaffolding) | — |
| chief-orchestrator | R/G/G | no | no | orchestration | neutral | NO (orchestrator = main loop) | — |
| agent-router | R/G/G | no | no | routing | neutral | NO (orchestrator covers) | — |
| escalation-filter | R/G/G | no | no | governance | neutral | NO (generic) | — |
| flow-continuity | R/G/G/B | no | yes | integration | yes | NO (covered by integration-boundary) | — |
| deployment-readiness | R/G/G/B | no | yes | governance | yes | NO (covered by deploy gate) | — |
| release-manager | R/G/G/B | no | yes | deploy | yes | NO (repo deploy-release-manager is canonical) | — |
| ci-runner | R/B/G/G | no | yes | CI | yes | NO (orchestrator runs CI) | — |
| pr-author | R/B/G/G/WF | gh-write | yes | git | caution | NO (orchestrator authors PRs) | — |
| dhl-customs | R/W/E/B/WF | YES | yes | DHL/customs | NO as actor | Q | — |
| wfirma-integration | R/W/E/B/WF | YES | yes | wFirma | NO as actor | Q | — |
| pz-purchase-accounting | R/W/E/B | YES | yes | PZ | NO as actor | Q | — |
| sales-proforma | R/W/E/B | YES | yes | proforma | NO as actor | Q | — |
| inventory-state-machine | R/W/E/B | YES | yes | inventory | NO as actor | Q | — |
| warehouse-ops | R/W/E/B | YES | yes | warehouse | NO as actor | Q | — |
| client-contractor-mapping | R/W/E/B/WF | YES | yes | customer master | NO as actor | Q | — |
| email-evidence-recovery | R/W/E/B | YES | yes | email | NO as actor (Lesson E) | Q | — |
| database-storage | R/W/E/B | YES | yes | storage/schema | NO as actor | Q | — |
| deployment-windows-ops | R/W/E/B | YES | yes | deploy/service | NO as actor | Q | — |
| document-intelligence | R/W/E/B | YES | yes | doc parsing | NO as actor | Q | — |
| dashboard-operations | R/W/E | YES | no | dashboard | NO as actor | Q | — |
| backend-api | R/W/E/B | YES | yes | generic backend | NO (builder) | NO | — |
| frontend-ui | R/W/E/B | YES | yes | generic frontend | NO (builder, wrong stack) | NO | — |
| git-workflow | R/W/E/B | YES | yes | git | NO (orchestrator) | NO | — |
| testing-verification | R/W/E/B | YES | yes | tests | NO (builder) | NO | — |
| browser-verifier | R/W/E/B | YES | yes | browser QA | gap — needs exec; can't be pure-inspect | NO (see gap note) | — |
| memory-lessons | R/W/E | YES | no | memory | NO (flow-context-keeper owns memory) | NO | — |
| prompt-engineering | R/W/E | YES | no | prompts | NO | NO | — |
| legal-argument-builder | R/W/E | YES | no | legal ❌ | wrong domain | NO | — |
| legal-case-intake | R/W/E | YES | no | legal ❌ | wrong domain | NO | — |
| legal-drafting | R/W/E | YES | no | legal ❌ | wrong domain | NO | — |
| legal-evidence-binder | R/W/E | YES | no | legal ❌ | wrong domain | NO | — |
| legal-research | R/G/G/WF/WS | no | no | legal ❌ | wrong domain | NO | — |
| legal-risk-review | R/G/G | no | no | legal ❌ | wrong domain | NO | — |

`*deferred` = classified INSTALL_SAFE/REV and approved for repo install, but **not
installed this pass** to avoid premature canonical bloat. Install when the relevant
domain sprint begins (e.g. finance-accounting-logic + compliance when the Accounting
Hub sprint starts; button-functionality + system-architect when needed). This keeps
the canonical set lean and every installed agent justified by active need.

## Browser-QA gap (unchanged, important)

`browser-verifier` cannot be installed as a pure-inspect agent — browser verification
genuinely needs exec (run a dev server) + possibly Write (test harness). A Read/Grep/Glob
shadow would be non-functional. **Browser QA therefore remains an orchestrator-driven
activity via the Preview MCP (as in Sprint 30/31), not a repo agent.** Documented as a
known, accepted gap.
