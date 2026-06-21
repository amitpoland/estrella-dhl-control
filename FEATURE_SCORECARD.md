# FEATURE_SCORECARD.md

One row per `/feature` invocation. Fill in immediately after CLOSE phase.
Do not aggregate — raw rows are more useful than summaries during the observation period.

---

## Scorecard rows

| Date | Task | Selected Skill | Confidence | Authority | Protocol Completed | Unnecessary HOLD | Scope Drift | Backlog Items | Outcome | Lessons |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | HIGH/MEDIUM/LOW | | Y/N | Y/N | Y/N | | SUCCESS/PARTIAL/FAILED | |
| 2026-06-21 | Proforma readiness status display in V2 shipment detail tab | `backend-route-and-service-builder` (PROFORMA fallback; `proforma-engine` MISSING) | MEDIUM | proforma domain: `routes_proforma.py` / `getDraftReadiness` single authority | Y | N | N | B-002: MISSING_SKILL proforma-engine (SCHEDULED) | PARTIAL — PR #687 draft; GATE 6 pending operator browser verification | reviewer-challenge returned REVISE on plan (draft_state field name, 8 lifecycle states, write-on-read stagger) — all resolved before implementation; no HOLD; GATE 6 cannot complete in remote container |
| 2026-06-21 | Improve DHL shipment detail diagnostics and operator visibility | `frontend-design` + `pz-shipment` (HIGH confidence; UI_FRONTEND + DHL_CUSTOMS tie) | HIGH | DHL domain: `routes_dhl_readiness.py` / `get_dhl_readiness` single authority | Y | N | N | none | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | reviewer-challenge returned FAIL (4 findings: batch_id slash encoding safe — confirmed SHIPMENT_ format; BACKEND_GAP_REGISTER.md citation removed; cancelled-flag pattern added; 401 auth-error distinction added); gap-detection surfaced 9 gaps (7 auto-resolved, 2 escalated: scope=DHL-domain-only per Lesson F, dual-authority coexistence explicitly labeled); no HOLD; GATE 6 cannot complete in remote container |

---

*First run populates row 1. After 10 rows, review failure patterns before building /bug or domain skills.*
