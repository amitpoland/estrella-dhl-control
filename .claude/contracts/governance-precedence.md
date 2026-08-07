# Governance Precedence — Estrella PZ Processor

Single source of truth for which rule wins when rules appear to conflict.
Applies to all agents, all sessions, all deploy decisions.

---

## Precedence ladder (highest → lowest)

1. **GATES 1–6** (`CLAUDE.md` § MANDATORY GOVERNANCE GATES)
   Hard blocking conditions for implementation work and PR opening.
   Cannot be overridden by any rule below.

2. **7-agent deploy gate** (`commands/deploy.md` + `agents/deploy_*.md`)
   Specialisation of GATE 1 for production syncs. Adds named-agent requirements.
   Does NOT relax GATE 1 — both apply simultaneously to production deploys.

3. **Engineering Lessons A–E** (`CLAUDE.md` § Engineering Lessons)
   Bind at the specific gate listed in each lesson header (e.g., "GATE 1", "GATE 5").
   Lessons narrow or add requirements within a gate; they never relax one.

4. **Operating rules and workflow sequences** (`CLAUDE.md` §§ Operating rules, Required workflow, When asked to run a shipment)
   Convenience sequences for day-to-day operation.
   Subordinate to GATES 1–6 and the deploy gate. If a workflow step would skip a gate, the gate wins.

**CI appears at no level of this ladder.** GitHub Actions CI is evidence, never
authority: it may not gate PR merges or production deploys, and no repository
configuration may elevate it without an operator DECISIONS entry. Normative rule (sole
authority): `CLAUDE.md` § PRODUCTION DELIVERY AUTHORITY — CI IS NOT A GATE. That section
also specialises level 2 (the 7-agent deploy gate) with the post-GO freeze and the
once-per-runtime-payload rule; it is summarized, never restated, everywhere else.

---

## Resolved conflicts

### GATE 1 vs LOCAL-COMMIT-ONLY (Lesson D)

GATE 1 governs **PR opening**. LOCAL-COMMIT-ONLY deploys have no PR, so GATE 1 is not triggered.
The governing gate for LOCAL-COMMIT-ONLY is the **7-agent deploy gate**.
Lesson D adds a **disclosure header requirement** on top of the 7-agent gate. It does not bypass any gate.
Test pass criteria (`.claude/contracts/test-baseline.md`) apply to ALL deploys regardless of commit origin.
A LOCAL-COMMIT-ONLY deploy with failing tests is blocked by the QA Reviewer. Lesson D disclosure cannot unblock a test failure.

### "Supersede" language in CLAUDE.md

"These gates supersede any older governance language" means: operational guidance sections are
subordinate to GATES 1–6. It does NOT mean GATES 1–6 supersede the 7-agent deploy gate or
Engineering Lessons — those bind at the same or higher layer.

### Lesson A vs Lesson D

Lesson A: every coordinator/builder PR must include a real-builder regression test. Binds at GATE 1 (PR opening).
Lesson D: LOCAL-COMMIT-ONLY deploys must carry a disclosure header. Binds at the 7-agent deploy gate.
Different triggers, different layers. No conflict.

### Post-GO freeze vs OBSERVATION LAYER RULES 2–3 (2026-08-07)

During the post-GO deployment window, `agent-performance-observer` and
`flow-context-keeper` auto-fires are **deferred, not cancelled**: they fire immediately
after successful smoke verification or rollback completion. Outside that window RULES 2–3
apply unchanged. Normative rule: `CLAUDE.md` § PRODUCTION DELIVERY AUTHORITY, B4/B6.

### Post-GO freeze vs GATE 4 disposition timing (2026-08-07)

A GATE-4 disposition owed during a post-GO window is deferred until after smoke
verification or rollback completion. The disposition obligation itself is unchanged —
deferral is timing, not exemption. Normative rule: `CLAUDE.md` § PRODUCTION DELIVERY
AUTHORITY, B4/B6.

### GATE 2 open-PR arithmetic vs deployment (2026-08-07)

GATE 2 governs **opening PRs**; it never delays a production deployment. Clearing the PR
queue is backlog work that resumes after the release closes. Normative rule: `CLAUDE.md`
§ PRODUCTION DELIVERY AUTHORITY, B6.

---

## What this file does NOT define

- Gate content: `CLAUDE.md` § MANDATORY GOVERNANCE GATES
- Test pass thresholds: `.claude/contracts/test-baseline.md`
- Forbidden deploy paths: `.claude/contracts/forbidden-paths.md`
- LOCAL-COMMIT-ONLY detection and disclosure: `.claude/contracts/local-commit-policy.md`
