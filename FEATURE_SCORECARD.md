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

| Date | Task | Selected Skill | Confidence | Authority | Protocol Completed | Unnecessary HOLD | Scope Drift | Backlog Items | Outcome | Lessons |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | HIGH/MEDIUM/LOW | | Y/N | Y/N | Y/N | | SUCCESS/PARTIAL/FAILED | |

---

*First run populates row 1. After 10 rows, review failure patterns before building /bug or domain skills.*
