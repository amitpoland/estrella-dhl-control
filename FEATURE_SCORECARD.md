# FEATURE_SCORECARD.md

One row per `/feature` invocation. Fill in immediately after CLOSE phase.
Do not aggregate — raw rows are more useful than summaries during the observation period.

---

## Scorecard rows

| Date | Task | Selected Skill | Confidence | Authority Correct | Protocol Completed | Unexpected HOLD | Scope Drift | Drift Started At | Session Length | Backlog Items | Outcome | Lessons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | HIGH/MEDIUM/LOW | Y/N | Y/N | Y/N | Y/N | None/Discovery/Plan/Implement/Verify | <30m/30-60m/1-2h/2-4h/4h+ | | SUCCESS/PARTIAL/FAILED | |

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
