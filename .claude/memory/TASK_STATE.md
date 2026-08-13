# TASK_STATE.md

In-flight **single-task** tracker. Records the current task's goal,
completion criteria, status, and HOLD reason (if stopped). Ephemeral —
rewrite the `## Current task` block when a new task begins.

Rules and boundary vs PROJECT_STATE.md:
`docs/governance/anti-hold-and-completion.md` §5.

---

## Current task

- **Task:** none in-flight. **B-011 → B-018 master campaign COMPLETE** (2026-08-13).
- **Status:** `COMPLETE`
- **origin/main tip:** `1cd35e5701d58a59e0408f777e061d0d7a6d8ea8`
- **Production (measured `C:\PZ\version.txt`):** `15cd1057cdebfac5e161ad12ea7c5514767fe554` pending App-only deploy of B-012+B-014 static payload → tip `1cd35e57`
- **Do not reopen:** B-008..B-018, #1218, #1220, #1221, #1222, #1223
- **Next open backlog after B-018:** **B-019** (prod DB backup schtask / restore drill)
- **Suspended (not abandoned):** PR #1201 intake multiparty seed — resume after operator redirect; re-measure prod first

### B-011..B-018 dispositions (closed)

| ID | Disposition |
|---|---|
| B-011 | CLOSED_REAL_DEFECT — PR #1221 / `15cd1057` (`__all__` exports) |
| B-012 | CLOSED_REAL_DEFECT — PR #1222 / `ac39bfdd` (Save to draft label) — App deploy owed |
| B-013 | CLOSED_OPERATOR_DECISION — keep design_no/product_code line names |
| B-014 | CLOSED_FEATURE_COMPLETE — V2 birth-block parity; V1 cutover HOLD |
| B-015 | CLOSED_STALE_BACKLOG — proforma-engine CANCELLED (Skill Freeze) |
| B-016 | CLOSED_REAL_DEFECT — smoke report Verdict added |
| B-017 | CLOSED_ALREADY_FIXED — PR #1207; dual-run silence ×2 |
| B-018 | CLOSED_GOVERNANCE_ONLY — Phase-2B prune target RETIRED; ratchet kept |

### B-008/B-009 App deploy debt

**CLOSED** on Windows (operator 2026-08-13). Prior EXECUTION_BLOCKED checkpoint superseded. Do not reopen.

## Prior task — B-010 set_sales_client_name scope pin (COMPLETE; test-only)

- **Merged:** `4857d992`. No App deploy.
