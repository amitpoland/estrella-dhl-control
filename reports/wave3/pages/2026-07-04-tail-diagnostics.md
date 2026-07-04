# Wave-3 Build Record: Diagnostics R-Q3 CLI Triad Labels

**Date:** 2026-07-04
**Branch:** deploy/latest
**Sub-slice:** (b) R-Q3 Diagnostics honest labels
**Criterion 10 (control matrix gate):** PASS — Wireframe-Required Missing = 0

---

## Summary

Per R-Q3: "Diagnostics tools are not removed. Shown as Disabled / Planned /
Backend Required. Honest UI is our policy."

The `_DiagCliSection` in `ops-cell.jsx` previously showed "CLI only" / "POST available"
chips. Replaced with the exact R-Q3 triad: **Disabled** / **Planned** / **Backend Required**.
No tools were removed. All 4 CLI tools remain visible.

---

## Files Changed

| File | Change |
|---|---|
| `service/app/static/v2/ops-cell.jsx` | `CLI_TOOLS`: added `rq3Label` field per tool; `_DiagCliSection`: chip now reads `rq3Label` (Disabled/Planned/Backend Required) |

---

## Control Matrix — CLI Tool Status per R-Q3 Triad

| Tool | Was | Now (R-Q3) | Rationale |
|---|---|---|---|
| `check_dhl_config` | "CLI only" (neutral) | **Disabled** (neutral) | No HTTP route — CLI only |
| `check_wfirma_config` | "CLI only" (neutral) | **Disabled** (neutral) | No HTTP route — CLI only |
| `regenerate_stale_batches` | "CLI only" (neutral) | **Disabled** (neutral) | No HTTP route — CLI only |
| `run_active_shipment_monitor` | "POST available" (info) | **Backend Required** (amber) | POST exists but requires explicit operator approval |

Wireframe-Required Missing = **0** — criterion 10 PASS.

The `DiagnosticsPage` itself remains WIRED (in WIRED_PAGES since Sprint 42). All 5 live
read endpoints unchanged (health-full, storage/health, storage/locks, system/version,
debug/pending). Only the CLI section chip labels changed.

---

## R-Q3 Compliance

Rule: "Diagnostics tools are not removed. Shown as Disabled / Planned / Backend Required.
Honest UI is our policy."

- All 4 tools present and visible: PASS
- Labels match R-Q3 triad exactly: PASS
- Run buttons remain disabled with appropriate tooltip: PASS
- No tool removed or hidden: PASS

---

## Tree Count

**Before / After:** 11 / 11 modified tracked files
