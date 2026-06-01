# Atlas Campaign 2–11 — Running Evidence Log

**Branch:** feat/atlas-campaign-2-11  
**Base:** c09fdfa (origin/main post-#417 merge)  
**Started:** 2026-06-01  
**Invariants:** all wFirma write flags OFF · live_enabled OFF · frozen files untouched · no merge/deploy/C:\PZ

---

## Phase 0 — Base ✓

| Check | Result |
|---|---|
| origin/main HEAD | c09fdfa |
| docs/ATLAS_BUILD_CAMPAIGN.md | Present |
| docs/ATLAS_WORKFLOW_MAP.md | Present |
| Open PRs | 1 (#416 customs-identity, flag-gated OFF) |
| Tree | Clean |
| Stashes | 11 intact |

---

## Phase 2 — Soften three hard-stops (MED)

### INSPECTOR

Touch-points confirmed:
- `service/app/core/guards.py` — `guard_pz_requires_sad`, `guard_dhl_requires_email`  
- `service/app/api/routes_proforma.py` — `_check_proforma_export_prerequisites`, `missing_products` ValueError
- `service/app/api/routes_dhl_clearance.py` — `guard_dhl_requires_email` call site
- `service/app/api/routes_pz.py` — `guard_pz_requires_sad` call site

Plan:
1. Add `advisory_gates_enabled: bool = Field(default=False)` to `config.py`
2. Modify `guard_pz_requires_sad` + `guard_dhl_requires_email` in `guards.py` — when advisory mode ON, return advisory dict instead of raising
3. Modify `_check_proforma_export_prerequisites` in `routes_proforma.py` — advisory flag → treat PZ-before-proforma as warning not blocker
4. Modify `_build_proforma_request_from_draft` missing_products path → advisory warning not 400
5. Tests: each gate warns instead of blocks; carrier baseline 381/381
