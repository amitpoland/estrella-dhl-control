# BACKLOG.md

Side-discoveries captured during task execution that are out of scope for the current task.
Each entry must receive a SCHEDULED / ISSUE / REJECTED disposition (GATE 4) before the
next task closes.

---

## Entries

| # | Discovery | Found during | Disposition | Notes |
|---|---|---|---|---|
| B-001 | PR #661 (`ci/auto-merge-approved`) is non-draft and unreviewed — appears stale since 2026-06-20 | /feature DISCOVERY | SCHEDULED — review before next merge sprint | Verify it doesn't conflict with governance gates before approving |
| B-002 | MISSING_SKILL: `proforma-engine` — planned but not installed; `backend-route-and-service-builder` used as fallback for PROFORMA domain | /feature DISCOVERY (proforma readiness task) | SCHEDULED — **CONFIRMED GAP** (Rows #1+#3 both Proforma, both fallback); leading post-observation improvement candidate; build after 10-run mark | Routing table has placeholder entry; SKILL_ROUTING.md §Missing skills; 3-run pattern: Row #1 MEDIUM fallback, Row #3 HIGH + MISSING_SKILL — deterministic, not drift |
| B-003 | `test_real_smoke_reports_are_markdown` failing on `b0-wfirma-identity-cache-review-assign.md` (missing "Verdict" field) — pre-existing noise, appeared in both Row #1 and Row #2 sessions | /feature VERIFY (DHL diagnostics task) | SCHEDULED — fix before 10-run mark; recurring framework noise hides real failures | Add "Verdict: PASS" to that smoke report file; or relax the check to allow legacy reports predating the Verdict requirement |

---

_Maintained per TASK_EXECUTION_PROTOCOL.md §Standing Rules — BACKLOG rule._
