# FEATURE_SCORECARD.md

One row per `/feature` invocation. Fill in immediately after CLOSE phase.
Do not aggregate — raw rows are more useful than summaries during the observation period.

---

## Status

**Observation Status: ACTIVE**
**Development Status: ACTIVE**

**Rule:** A completed `/feature` execution creates a scorecard entry.
The absence of scorecard entries must **never** prevent development work.
Observation runs in parallel with development; it is informational only and
never a gate. See `docs/governance/OBSERVATION_IS_NOT_A_GATE.md`.

---

## Scorecard rows

| Date | Task | Selected Skill | Confidence | Authority Correct | Protocol Completed | Unexpected HOLD | Scope Drift | Drift Started At | Session Length | Backlog Items | Outcome | Lessons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | HIGH/MEDIUM/LOW | Y/N | Y/N | Y/N | Y/N | None/Discovery/Plan/Implement/Verify | <30m/30-60m/1-2h/2-4h/4h+ | | SUCCESS/PARTIAL/FAILED | |
| 2026-06-20 | PR-2 Contractor-at-Birth Projection (#673, merged f652de0) | AUTHORITY_MAP §1/§9/§12 (proforma/wfirma/readiness domain skills planned-not-built — substituted per SKILL_ROUTING) | HIGH | Y | Y | N | N | None | 2-4h | 7 (B-002..B-008, all SCHEDULED) | SUCCESS | (1) Don't re-key client_name-keyed tables — contractor_id is a reference, not the storage key (service charges + authority joins would orphan). (2) Centralised derive-from-shipment_documents self-heals every birth call site (avoided editing 5 routes). (3) Broad single-process `pytest -k` is unreliable in a bare worktree — pre-existing failures reproduce on clean origin/main; isolated/smoke suites are the authoritative signal. (4) PLAN-stage reviewer-challenge + gap-detection caught the design-defining constraint before any code was written. |

---

## Success thresholds (review after 10 runs)

| Metric | Target |
|---|---|
| Correct skill selection | > 80% |
| Protocol completion | > 80% |
| Unexpected HOLD | < 10% |
| Scope drift | < 20% |

If targets are met → build `/bug`. If domain failures cluster (proforma, DHL, wFirma) → build that domain skill first.

---

*First run populates row 1. After 10 rows, review failure patterns before next engineering investment.*
