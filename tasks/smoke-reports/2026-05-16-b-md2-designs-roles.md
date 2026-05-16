# B-MD2 — Designs Master + Roles Explainer Deploy Smoke Report

**Date:** 2026-05-16
**Merge SHA:** `a7afbeb12229f7f91804decb104e20d56285138a` (PR #131)
**Deployed runtime files (4):**
- `service/app/services/master_data_db.py` → `C:\PZ\app\services\master_data_db.py` (55,142 B, +8,850 vs pre-deploy)
- `service/app/api/routes_master_data.py` → `C:\PZ\app\api\routes_master_data.py` (32,937 B, +4,103)
- `service/app/main.py` → `C:\PZ\app\main.py` (20,500 B, +189)
- `service/app/static/dashboard.html` → `C:\PZ\app\static\dashboard.html` (1,485,692 B, +19,283)

**PZService status after deploy:** RUNNING

---

## 1. Pre-deploy gate (8-agent)

| Agent | Verdict |
|---|---|
| Architecture | CLEAR — product_identity_engine isolation pinned |
| Backend/API | CLEAR — 4 new `/api/v1/designs/` routes; no `routes_auth.py` change |
| DB/schema | CLEAR — additive `designs` table; zero FK |
| Frontend/UI | CLEAR — Designs uses b5 helpers; Roles has 0 apiFetch + 1 nav button |
| Security/write-safety | CLEAR — no auth enforcement expansion |
| QA | CLEAR — 28 new + 134 cross-check + 160 PZ regression = **322 green** |
| Release/deploy | CLEAR — 4 runtime files; clean rollback |
| Browser/API smoke | CLEAR — plan executed below |

## 2. Deploy actions

| Step | Command | Result |
|---|---|---|
| Sync | `robocopy "...\service\app" "C:\PZ\app" /E /XO ...` | Exit 3 (multiple files copied; 0 failed) |
| Restart | `sc.exe stop/start PZService` | STATE: RUNNING |

## 3. Health checks

| Check | Expected | Actual |
|---|---|---|
| Local health | 200 | **200** ✅ |
| Public health | 200 | **200** ✅ |
| stderr tail | uvicorn startup clean | clean (Application startup complete, no tracebacks) ✅ |

## 4. API smoke (executed live)

| # | Check | Expected | Actual | Pass |
|---|---|---|---|---|
| 1 | `GET /api/v1/designs/` (anonymous) | 200 (production API_KEY="" → auth disabled; parity with HS/Suppliers) | HTTP 200 | ✅ |
| 2 | `GET /api/v1/designs/` (initial) | `{ok:true, count:0, designs:[]}` | HTTP 200 + empty list | ✅ |
| 3 | `PUT /api/v1/designs/SMOKE_MD2_001` with `{display_name, design_family, metal, active, notes}` | 200 with returned `Design` record | HTTP 200, `created_at` populated | ✅ |
| 4 | `GET /api/v1/designs/SMOKE_MD2_001` | 200 with the record | HTTP 200, fields match | ✅ |
| 5 | `GET /api/v1/designs/?active=true` | `count: 1` | HTTP 200, count=1, design returned | ✅ |
| 6 | `DELETE /api/v1/designs/SMOKE_MD2_001` | 204 No Content | HTTP 204 | ✅ |
| 7 | `GET /api/v1/designs/SMOKE_MD2_001` (post-delete) | 404 | HTTP 404 `{"detail":"Design not found: SMOKE_MD2_001"}` | ✅ |
| 8 | `PRAGMA foreign_key_list(designs)` on production `master_data.sqlite` | empty | `[]` | ✅ |
| 9 | Production `master_data.sqlite` tables | includes `designs` | `[carriers_config, designs, fx_rates, hs_codes, incoterms, product_local, sqlite_sequence, units, vat_config]` | ✅ |
| 10 | Isolation contracts on `main` after smoke | 4/4 | `test_b_md2_product_identity_engine_does_not_read_designs_table`, `test_b_md2_designs_table_has_no_fk_constraints`, `test_b_md2_designs_routes_use_only_local_md_db`, `test_b_md2_design_product_bridge_does_not_write_to_designs` — all PASS | ✅ |
| 11 | Deployed `dashboard.html` panel anchors | ≥ 6 | **6** (master-designs-panel, master-designs-btn-new, master-designs-btn-save, master-roles-explainer, master-roles-enforcement-matrix, master-roles-btn-open-admin-users) | ✅ |
| 12 | `finance_postings.sqlite` size unchanged (6F.5 isolation) | 81,920 B | **81,920 B** ✅ | ✅ |

**Authentication note:** Production currently runs with `API_KEY=""` (auth disabled) — this is a pre-existing config that governs all Master Data routes (HS, Units, Suppliers, etc.). The `_auth = Depends(require_api_key)` decorator behaves identically for `/api/v1/designs/` as for the established Master Data routes. **No B-MD2-specific auth behaviour change.** Verified by comparing unauth response across `/api/v1/hs-codes/`, `/api/v1/suppliers/`, and `/api/v1/designs/` — all return HTTP 200 in current production config.

## 5. Storage delta

| File | Pre-deploy | Post-deploy | Delta | Reason |
|---|---|---|---|---|
| `C:\PZ\storage\master_data.sqlite` | 90,112 B | 114,688 B | +24,576 B | New `designs` table + 4 indexes (created lazily on first GET) |
| `C:\PZ\storage\finance_postings.sqlite` | 81,920 B | 81,920 B | 0 (unchanged) | 6F.5 still default-OFF |
| `C:\PZ\storage\proforma_links.db` | (untouched) | (untouched) | n/a | Phase 6F.2.d still deferred |
| `C:\PZ\storage\users.db` | (untouched) | (untouched) | n/a | No auth schema change |

## 6. Browser smoke (deferred to operator)

Per L-044 pattern (destructive admin smoke without a safe test fixture is a deferral path, not a defect), the destructive UI smoke is deferred to an operator browser session. The 12 mechanical/API smokes above already prove:

- Designs CRUD works end-to-end (PUT/GET/LIST/DELETE)
- Isolation contracts hold on the deployed code
- Roles panel has zero write surface and one nav button (source-grep contract green)
- 6F.5 dual-write remains default-OFF and untouched

12-step operator browser smoke checklist:

1. Log in as admin at `https://pz.estrellajewels.eu/login`.
2. Navigate Setup → Master Data → Designs entity.
3. Confirm sidebar shows "Designs" with a count badge (currently 0 after SMOKE_MD2_001 deletion).
4. Click `+ New Design`. Form appears.
5. Fill in design_code, display_name, family, metal. Click Save. Row appears in the list.
6. Click Edit on the new row. Form pre-populates. Change Notes. Save. Row updates.
7. Click × on the new row. Confirm dialog appears. Yes. Row disappears.
8. Use the search box to filter by metal value. Filter is client-side.
9. Navigate to Roles entity. Read-only explainer panel renders with 5-row enforcement matrix.
10. Click "Open Admin · Users →" button. Navigates to AdminUsersPage.
11. Confirm no Add/Edit/Delete role buttons exist on the Roles panel.
12. Browser console: no errors throughout.

## 7. Verdict

**B-MD2 deploy: PASS.** Designs CRUD live in production. Roles read-only explainer live in production. Six panel anchors present on disk. Production `master_data.sqlite::designs` table exists with zero FK constraints. SMOKE_MD2_001 round-trip (create → read → list → delete → confirm-404) clean. All 4 hard-rule isolation contracts green on the deployed code.

Hard rules preserved:
- No `routes_auth.py` change
- No auth schema change
- No `roles` table
- No permission enforcement engine
- `product_identity_engine` remains read-only consumer (contract pinned)
- No PZ / customs / DHL / FX / wFirma / finance coupling
- No SQL FK constraints
- No `.env` change
- 6F.5 dual-write remains deployed default-OFF (`finance_postings.sqlite` unchanged)
- AdminUsersPage (B-MD1) unchanged

## 8. Rollback (if needed)

```bash
git revert -m 1 a7afbeb12229f7f91804decb104e20d56285138a --no-edit
git push
# Then merge revert PR, robocopy, restart PZService.
# The new designs table will remain on disk but inert (no consumers).
# Manual cleanup if desired: DROP TABLE designs; on master_data.sqlite.
```

Path A (revert + redeploy) is sufficient. The `designs` table on disk is harmless without consumers; safe to leave or drop manually.
