# OBSERVATION_IS_NOT_A_GATE

Status: ACTIVE · Introduced 2026-06-20 · Owner: orchestrator
Related: `.claude/TASK_EXECUTION_PROTOCOL.md` §Observation Period Policy ·
`FEATURE_SCORECARD.md` ·
`docs/governance/anti-hold-and-completion.md` (Anti-HOLD) ·
`CLAUDE.md` §MANDATORY OBSERVATION LAYER (RULES 1–6)

---

## Definition

Observation measures process quality.

Observation **never** authorizes, delays, blocks, freezes, pauses, or restricts
feature development.

If observation is ever interpreted as a reason to stop work, that interpretation
is **invalid** and must be removed.

The `/feature` observation period is passive measurement. Its sole function is to
record completed `/feature` executions in `FEATURE_SCORECARD.md` and to evaluate
the collected evidence later. It runs in parallel with development.

Observation does not require waiting for calendar time, a minimum number of days,
or a minimum number of scorecard rows before development may proceed.

---

## Acceptance Criteria

- No document contains language implying development must wait for observation.
- No workflow step creates a HOLD because observation is active.
- PR-2, future features, and future deployments may proceed immediately when
  business priority requires.
- Observation continues automatically in parallel with development.

---

## Relationship to other governance

- **Anti-HOLD (`anti-hold-and-completion.md` §2):** observation adds **no** new
  HOLD condition. Only the four documented HOLD conditions stop work; "observation
  is active" is not one of them.
- **Separate business holds:** a deliberate hold on a specific item (e.g. PR-2,
  `/bug`, domain-skill creation) is a business/roadmap decision recorded by the
  operator. Such holds are **not** consequences of observation, and lifting them
  is a business decision — observation neither imposes nor sustains them.
- **Observation RULES 1–6 (`CLAUDE.md`):** unchanged. Those govern the meta-agent
  observation layer (scorecards, PROJECT_STATE). This rule clarifies that none of
  them gate roadmap execution.

---

_This rule is binding. Any future document, workflow step, or agent prompt that
treats observation as a gate is non-conformant and must be corrected on first
contact._
