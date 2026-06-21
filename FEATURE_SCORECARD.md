# FEATURE_SCORECARD.md

One row per `/feature` invocation. Fill in immediately after CLOSE phase.
Do not aggregate — raw rows are more useful than summaries during the observation period.

---

## Scorecard rows

| Date | Task | Selected Skill | Confidence | Authority | Protocol Completed | Unnecessary HOLD | Scope Drift | Backlog Items | Outcome | Lessons | Duration | Files Read | Files Chg | Test Time | RC Findings | Fallback | GATE 6 Pend | Ctx Pressure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | HIGH/MEDIUM/LOW | | Y/N | Y/N | Y/N | | SUCCESS/PARTIAL/FAILED | | ~Nm | ~N | N | Ns / N/A | N (verdict) | Y/N | Y/N | text |
| 2026-06-21 | Proforma readiness status display in V2 shipment detail tab | `backend-route-and-service-builder` (PROFORMA fallback; `proforma-engine` MISSING) | MEDIUM | proforma domain: `routes_proforma.py` / `getDraftReadiness` single authority | Y | N | N | B-002: MISSING_SKILL proforma-engine (SCHEDULED) | PARTIAL — PR #687 draft; GATE 6 pending operator browser verification | reviewer-challenge returned REVISE on plan (draft_state field name, 8 lifecycle states, write-on-read stagger) — all resolved before implementation; no HOLD; GATE 6 cannot complete in remote container | — | — | — | — | — | — | — | — |
| 2026-06-21 | Improve DHL shipment detail diagnostics and operator visibility | `frontend-design` + `pz-shipment` (HIGH confidence; UI_FRONTEND + DHL_CUSTOMS tie) | HIGH | DHL domain: `routes_dhl_readiness.py` / `get_dhl_readiness` single authority | Y | N | N | none | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | reviewer-challenge returned FAIL (4 findings: batch_id slash encoding safe — confirmed SHIPMENT_ format; BACKEND_GAP_REGISTER.md citation removed; cancelled-flag pattern added; 401 auth-error distinction added); gap-detection surfaced 9 gaps (7 auto-resolved, 2 escalated: scope=DHL-domain-only per Lesson F, dual-authority coexistence explicitly labeled); no HOLD; GATE 6 cannot complete in remote container | — | — | — | — | — | — | — | — |
| 2026-06-21 | Improve Proforma draft blocker visibility and operator guidance in V2 shipment detail | FALLBACK → `backend-route-and-service-builder` (PROFORMA; `proforma-engine` MISSING); UI impl via `frontend-design` | HIGH (single-keyword "proforma" override; MISSING_SKILL confirms B-002 pattern for 3rd time) | proforma domain: `routes_proforma.py` / `_derive_draft_readiness` single authority; `draft.error_hint` from `_draft_to_summary` | Y | N | N | B-002: MISSING_SKILL proforma-engine confirmed again (SCHEDULED) | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | reviewer-challenge returned Ship-with-mitigations (4 findings resolved: error_hint raw text → always-show with fallback; falsy-check silencing → always-show; cancelled-draft banner gap → "active" qualifier; test under-specified → T9/T10/T11 fully specified); gap-detection gap [2] auto-resolved (authority already named in repair_action text — no backend change needed); 11/11 tests pass; no HOLD; GATE 6 cannot complete in remote container | — | — | — | — | — | — | — | — |
| 2026-06-21 | Improve shipment intake diagnostics and operator troubleshooting visibility | `frontend-design` + `pz-api.js` transport (HIGH; UI_FRONTEND + INTAKE/dashboard domain) | HIGH | Intake domain: `routes_dashboard.py:batch_detail` single authority; `clearance_status`, `action_reason`, `failed_checks`, `sales_status_hint`, `files_detail.source_files` from batch detail response | Y | N | N | none | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | gap-detection found batch_id field name discrepancy (batch_id not shipment_id — verified from existing DHL card usage, no HOLD); reviewer-challenge auto-resolved (stale-mount cancelled flag + 404 → isProcessing pattern adopted; auth errType distinction carried over from DHL card; sales_status_hint as tri-state unavailable-sales packing field); 15/15 tests pass (T12–T15 added); old Shipment PanelCard with hardcoded '3 uploaded' removed; GATE 6 cannot complete in remote container | — | — | — | — | — | — | — | — |
| 2026-06-21 | Add observation-only performance metrics to FEATURE_SCORECARD | (no runtime skill) — GOVERNANCE domain; direct implementation | HIGH (3 keyword hits: protocol, gate, rule) | governance docs — `FEATURE_SCORECARD.md` sole write target; no AUTHORITY_MAP forbidden zone | Y | N | N | none | SUCCESS — 8 metric columns added; Row #5 self-referential fill; GATE 6 N/A (docs-only) | reviewer-challenge SHIP (3 mitigations resolved: GATE 6 Pend disambiguation via legend; Fallback parenthetical added; Row #5 design decision — Fallback + GATE 6 Pend accepted as deliberately redundant fast-queryable signals); gap-detection skipped (trivial docs task — Phase 1 parenthetical "for non-trivial tasks"); Smoke N/A (docs-only); no HOLD | ~20m | ~4 | 2 | N/A | 3 (SHIP) | N | N | session re-started after Task #4 compaction; no pressure; lightweight task |

---

### Metric column legend

| Column | Meaning | Format |
|---|---|---|
| **Duration** | Approximate wall-clock session time for the task | `~Nm` (minutes) |
| **Files Read** | Approximate count of source files read in DISCOVERY + PLAN phases | `~N` |
| **Files Chg** | Count of files modified by this task (TASK_STATE.md governance updates not counted) | `N` |
| **Test Time** | Test suite elapsed time; `N/A` = docs-only task (no suite runs); `—` = not recorded at time of run | `Ns` / `N/A` |
| **RC Findings** | reviewer-challenge finding count and verdict code | `N (FAIL\|REVISE\|SHIP\|CLEAR)` |
| **Fallback** | `Y` = skill-routing invoked a fallback because the named skill is MISSING_SKILL; `N` = named skill used directly | `Y/N` |
| **GATE 6 Pend** | `Y` = browser verification still outstanding; `N` = not applicable or completed. NOTE: `Y` in remote-container sessions is a structural constraint (no browser access), not a workflow failure — see Lessons column for context | `Y/N` |
| **Ctx Pressure** | Notes on token/context usage: compaction events, session restarts, large file reads | free text |
| **`—`** | Value was not tracked at time of task execution (historical rows #1–#4) | — |

*First run populates row 1. After 10 rows, review failure patterns before building /bug or domain skills.*
