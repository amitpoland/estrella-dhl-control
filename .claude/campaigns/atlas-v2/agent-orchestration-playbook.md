# Atlas V2 — Agent & Skill Orchestration Playbook

**The single reference for how to use agents, skills, and commands on future
Atlas V2 work.** Governance/tooling only — this playbook authorizes no product
change by itself.

Generated 2026-06-06. Companion registries:
- `.claude/agents/AGENT_REGISTRY.md` (15 repo-installed agents)
- `.claude/skills/SKILL_REGISTRY.md` (3 skills)
- `.claude/commands/COMMAND_REGISTRY.md` (8 commands)

---

## 1. Core principles (binding)

1. **The 15 repo-installed agents are canonical.** They are version-controlled,
   their tool grants are guaranteed, and their boundaries are known. Use them for
   anything that influences a real decision.
2. **Runtime-registry agents are optional helpers only.** The runtime
   `subagent_type` menu may show ~70 names. Any agent with no file in
   `.claude/agents/` is NOT authoritative for this project. Use it only as an
   optional helper, and independently verify its output before it affects any
   production-affecting decision (Lesson B: the registry does not reliably refresh,
   and unverified agents can silently substitute).
3. **No reliance on unverified runtime-only agents for final authority.** A final
   verdict (plan approval, review sign-off, deploy GO) must come from a
   repo-installed agent, or — if no repo equivalent exists — from evidence that has
   been independently re-verified by the orchestrator.
4. **One lead coordinator owns the final decision.** For deploys that is
   `deploy-lead-coordinator`. For non-deploy work the orchestrator (you) is the
   coordinator. Many agents advise; exactly one decides.
5. **Agents provide evidence, not authority.** An agent's PASS is an input, not an
   action. Nothing an agent returns is itself a production mutation.
6. **Production actions require the deploy gate.** No production change without the
   full 7-agent gate returning READY-TO-DEPLOY (CLAUDE.md, no exceptions).
7. **Write-risk domains require safety review.** Any change touching a write path
   — customs, accounting, inventory, wFirma, DHL workflow, email send, Lane A/B —
   must pass `security-write-action-reviewer` (and usually `backend-safety-reviewer`)
   before it can proceed.

---

## 2. THE SAFETY RULE (quote verbatim into any task that uses agents)

> **Agents do not own production authority. Agents inspect, verify, and recommend.
> The operator and the explicit deploy gate own production action.**

Corollaries:
- A recommendation is never a deployment.
- The lead coordinator's GO authorizes the *gate to be satisfied*, not the operator's
  approval to be skipped.
- A `deploy-security-reviewer` BLOCK cannot be overridden by anyone, including the
  lead coordinator.

---

## 3. Standard agent groups

Dispatch these as named bundles. All members are repo-installed (canonical).

### Group A — Planning (run FIRST, before edits)
Purpose: understand state, surface gaps, define the plan + test plan before code.
- `flow-context-keeper`   — load current PROJECT_STATE (read its 4 sections first)
- `adr-historian`         — surface relevant prior ADRs (read), draft only if a decision lands
- `gap-hunter`            — what's missing / contradictory before we start
- `frontend-flow-reviewer`— if the task touches UI
- `backend-safety-reviewer`— if the task touches backend
- `test-coverage-reviewer`— define the test plan / coverage targets

### Group B — Implementation review (run AFTER edits, before PR)
Purpose: verify the edits are safe and complete.
- `frontend-flow-reviewer`       — UI flow correctness (if UI changed)
- `backend-safety-reviewer`      — unsafe writes / idempotency / boundary helpers (if backend changed)
- `security-write-action-reviewer`— **mandatory if any write path changed**
- `test-coverage-reviewer`       — coverage adequate, negative cases present
- `gap-hunter`                   — cross-phase contradictions, hidden assumptions

### Group C — Deploy gate (run ONLY before production deploy)
Purpose: the mandatory 7-agent production gate. Run the 6 reviewers in parallel,
then the coordinator. No deploy without READY-TO-DEPLOY.
- `deploy-git-diff-reviewer`
- `deploy-backend-impact-reviewer`
- `deploy-persistence-storage-reviewer`
- `deploy-security-reviewer`
- `deploy-qa-reviewer`
- `deploy-release-manager`
- `deploy-lead-coordinator` (final GO/NO-GO; cannot override a security block)

### Group D — Post-run governance (run AFTER completion)
Purpose: observe, score, persist state.
- `agent-performance-observer` — mandatory after any FINAL REPORT / ≥3-subagent run (RULE 2); orchestrator must verify the scorecard file exists on disk (Lesson C)
- `flow-context-keeper`        — update PROJECT_STATE; cite the scorecard (RULE 6)
- `adr-historian`              — **only if an architecture decision was made**

---

## 4. Standard sequence for a typical Atlas V2 sprint

```
Group A (Planning)
      ↓   plan + test plan + gap list
[ implement edits — allowed-file list only ]
      ↓
Group B (Implementation review)   ← fix findings inline; re-run until clean
      ↓
[ browser smoke if UI — isolated dev server, automation OFF ]
      ↓
[ open PR — GATE 1: every finding resolved, tests run, forbidden-files clean ]
      ↓
Group C (Deploy gate)             ← only if deploying; READY-TO-DEPLOY required
      ↓
[ merge → static/agreed deploy → post-deploy verify + render-gate skill ]
      ↓
Group D (Post-run governance)     ← observer → flow-context-keeper → (adr-historian if decision)
```

Skills layer in: read `frontend-design` before any UI edit; run `atlas-v2-render-gate`
after a V2 deploy; use `ui-ux-pro-max` (via EJ_OVERRIDES) only as design search.

---

## 5. Output contract for every agent (enforced)

Every agent invocation must return:

```
VERDICT:            PASS | FAIL | BLOCKED
                    (deploy reviewers: CLEAR | BLOCKED; coordinator: READY-TO-DEPLOY | BLOCKED)
EVIDENCE:           concrete findings, each with file:line where possible
FILES INSPECTED:    explicit list
RISKS:              enumerated, with severity
RECOMMENDATION:     what to do next
ACTION SAFE?:       yes | no
OPERATOR APPROVAL:  required | not-required
```

If an agent cannot produce this contract, treat its output as advisory only and
re-verify independently.

---

## 6. Runtime-only agent policy

> **Concrete hazard list (from `.claude/agents/RUNTIME_AGENT_AUDIT.md`, 2026-06-06):**
> The dispatch menu contains ~80 agents — only **15 are repo-canonical**; **54 are
> user-level runtime-only** and **~23 of those are write-capable**. The following
> runtime-only agents are named like EJ write-risk domains and CAN mutate production —
> **they are FORBIDDEN as actors; never dispatch them to act, never treat as authority:**
> `dhl-customs` · `wfirma-integration` · `pz-purchase-accounting` · `sales-proforma` ·
> `inventory-state-machine` · `warehouse-ops` · `client-contractor-mapping` ·
> `email-evidence-recovery` · `database-storage` · `deployment-windows-ops`.
> Also wrong-domain (never use for EJ): the 6 `legal-*` and 5 `brand-voice:*` agents.

If a task seems to need a capability with no repo-installed agent:
1. Prefer a repo-installed agent that covers the scope (see AGENT_REGISTRY matrix).
2. If genuinely none exists, a runtime-only agent MAY be used as a helper, but:
   - disclose the substitution explicitly in the final report (GATE 5),
   - state the capability-equivalence claim,
   - **independently re-verify its findings** before they affect any
     production-affecting decision,
   - never let it issue a final GO.
3. Log the registry gap for follow-up (so a repo agent can be authored later).

---

## 7. Future task template (copy/paste)

```
[TASK]: <name>

Use agent orchestration per `.claude/campaigns/atlas-v2/agent-orchestration-playbook.md`.

Dispatch:
- Planning group (A) first
- Implementation review group (B) after edits
- Deploy gate group (C) only before production deploy
- Post-run governance group (D) after completion

Do not use runtime-only agents as final authority unless a repo-installed
equivalent is absent AND the evidence is independently verified.

Honor the safety rule: agents inspect, verify, and recommend; the operator and
the deploy gate own production action. Write-risk domains
(customs/accounting/inventory/wFirma/DHL/Lane A-B/email) require
security-write-action-reviewer before proceeding.
```

After this exists, a future Claude Code task can simply say:

> **Use the Atlas V2 agent orchestration playbook.**

…and get structured, canonical agent use without trying to make ~70 runtime agents
act blindly.

---

## 8. What this playbook is NOT

- Not a license to deploy (that's `/deploy` + the 7-agent gate + operator approval).
- Not a product spec (no features defined here).
- Not a runtime-registry endorsement (only the 15 repo agents are canonical).
- Not a substitute for browser verification on UI work, or for `make verify` /
  PZ-regression / carrier baselines on deploys.
