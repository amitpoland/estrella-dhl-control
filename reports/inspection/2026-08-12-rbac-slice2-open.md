# RBAC Slice 2 — OPEN record (operator: OPEN SLICE 2)

**Opened:** 2026-08-12  
**Pin / tip:** `0dc647afa8608f49f52783b652e5e5074cd09a25`  
**Continuity:** `C:\PZ-secrets\deploy-gate\r1-1199\R1_CLOSURE.md`  
**Definition:** `reports/inspection/2026-08-11-rbac-slice2-definition.md`  
**Charter:** `.claude/campaigns/rbac-authority-consolidation.md` (AMD-B)

## Sub-slice disposition at open

| Sub-slice | Status | Notes |
|---|---|---|
| **2a** | **ALREADY ON TIP** | `require_permission` + `reports.financial` ledgers (`032fb00a`); deny tests in `test_reports_financial_permission.py` |
| **2b** | **THIS PR** | Stack `require_users_admin` / `require_system_settings_admin` on `/auth/users*` + `/api/v1/admin*` |
| **2c** | **DEFERRED** | customs / DHL / AWB — mandatory `/security-review` before binding |
| **2d** | **DEFERRED** | financial PZ/proforma/wFirma — mandatory `/security-review` |
| **2e** | **DEFERRED** | inventory / warehouse — mandatory `/security-review` |

## Production deploy

**HOLD** — Slice 2 coding must not claim Deploy-PZ / production sync as closure.

## No widening

User/system admin composition keeps `require_admin` so X-API-Key alone cannot enter these routes.
