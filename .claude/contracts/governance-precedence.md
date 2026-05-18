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

---

## What this file does NOT define

- Gate content: `CLAUDE.md` § MANDATORY GOVERNANCE GATES
- Test pass thresholds: `.claude/contracts/test-baseline.md`
- Forbidden deploy paths: `.claude/contracts/forbidden-paths.md`
- LOCAL-COMMIT-ONLY detection and disclosure: `.claude/contracts/local-commit-policy.md`
