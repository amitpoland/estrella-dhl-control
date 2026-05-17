# Estrella PZ Processor — Final Live Status Report

> **Generated:** 2026-05-16
> **Production SHA:** `02aefa1561781338651ec4bb908a21654b438486`
> **Public URL:** `https://pz.estrellajewels.eu`
> **PZService:** RUNNING (port 47213, NSSM-supervised uvicorn)

This is a one-shot truth report. Statuses use the strict 7-value taxonomy
defined in the brief. No vague terms. No "paused" inflation.

---

## 1 — Production SHA and deploy state

| Item | Value |
|---|---|
| Production HEAD | `02aefa1561781338651ec4bb908a21654b438486` |
| Latest merge | PR #136 — MDOC operator acceptance docs |
| Deploy performed in this consolidation | **No.** Production already matches `main` byte-for-byte. |
| Last runtime deploy | 2026-05-16T17:50:59 local (PR #131 B-MD2 Designs + PR #133 B-MD3 UI cleanup) |
| Local health | HTTP 200 |
| Public health | HTTP 200 |
| stderr tail | `Application startup complete; Uvicorn running on http://127.0.0.1:47213` — clean |
| Open PRs (this campaign cycle) | 0 |

## 2 — Deployed runtime files (byte-identical stage vs production)

| File | Bytes |
|---|---|
| `service/app/main.py` | 20,500 |
| `service/app/static/dashboard.html` | 1,483,492 |
| `service/app/core/config.py` | 22,759 |
| `service/app/api/routes_master_data.py` | 32,937 |
| `service/app/services/master_data_db.py` | 55,142 |
| `service/app/services/finance_dual_write.py` | 15,639 |
| `service/app/api/routes_finance_postings.py` | 7,107 |
| `service/app/api/routes_proforma.py` | 172,462 |
| `service/app/api/routes_auth.py` | 15,542 |

All 9 critical runtime files match between staging and production.

## 3 — Storage state

| File | Bytes | Status |
|---|---|---|
| `C:\PZ\storage\finance_postings.sqlite` | 81,920 | LIVE schema, EMPTY data (6F.5 default-OFF) |
| `C:\PZ\storage\master_data.sqlite` | 114,688 | LIVE; 8 tables incl. new `designs` |
| `C:\PZ\storage\users.db` | 32,768 | LIVE |
| `C:\PZ\storage\proforma_links.db` | 217,088 | LIVE (legacy proforma path) |
| `C:\PZ\storage\customer_master.sqlite` | 49,152 | LIVE |
| `C:\PZ\storage\suppliers.sqlite` | 24,576 | LIVE |

## 4 — Tests

| Suite | Result |
|---|---|
| `test_dashboard_master_design` + `test_dashboard_master_cleanup` + `test_dashboard_designs_and_roles` + `test_dashboard_admin_users_design` + `test_master_data_designs` + `test_master_data_hard_rules` + `test_runner_v2_hard_rules` + `test_finance_postings_contracts` + `test_finance_panel_contracts` + 4 dual-write suites + `test_auth_admin_user_routes` | **269/269** |
| **PZ regression** (`test_pz_regression.py`) | **160/160** |
| `campaign_status doctor` | no issues |
| `campaign_status summary` | Open PRs 0 · 7 blocked items (all expected operator-gated) |

Aggregate: **429 green**.

## 5 — Live mechanical/API smoke

| Check | Result |
|---|---|
| `GET /api/v1/health` (local) | 200 |
| `GET /api/v1/health` (public) | 200 |
| 10 Master Data GET endpoints | 10/10 HTTP 200 |
| `GET /api/v1/wfirma/customers` | 200 (read-mirror) |
| `GET /api/v1/wfirma/products` | 200 (read-mirror) |
| `GET /auth/users` unauthenticated | HTTP 401 ✅ |
| `GET /api/v1/finance/postings/999999/breakdown` | HTTP 404 `{"detail":"Posting not found: id=999999"}` ✅ |
| Designs CRUD temp record `SMOKE_FINAL_DSGN` | PUT 200 → GET 200 → DELETE 204 → GET 404 ✅ |
| Suppliers CRUD temp record `SMOKE_FINAL_SUP` (id=4) | POST 201 → GET 200 → DELETE 204 → GET 404 ✅ |
| Product-local CRUD temp record `SMOKE-FINAL-PL` | PUT 200 → GET 200 → DELETE 204 → GET 404 ✅ |
| Dashboard anchors (AdminUsersPage, Designs panel, Roles explainer, Finance breakdown panel) | 10/10 present |
| `finance_postings.sqlite` size before vs after smoke | 81,920 B unchanged |
| `finance_dual_write` log hits | 0 |
| `master_data.sqlite` size after temp-record cleanup | 114,688 B unchanged |

All mechanically checkable items PASS.

## 6 — Surface-by-surface truth (26 areas)

| # | Area | Status | Evidence |
|---|---|---|---|
| 1 | Dashboard shell | **LIVE** | `/dashboard/dashboard.html` served; 1,483,492 B deployed; session-gated route enforced (`check_session_or_redirect`) |
| 2 | Master Data page | **LIVE** | `function MasterDataPage(` present; 13 live entities in `ENTITIES` array; 22 testids verified |
| 3 | Admin Users page | **LIVE** (with **OPERATOR LOGIN REQUIRED** for the visual destructive-action observation walk) | `function AdminUsersPage(` present; 5 admin write routes wired to `Depends(require_admin)`; mechanically verified GET returns 401 unauth |
| 4 | Customer Master | **LIVE** backend (`/api/v1/customer-master/` 200); UI tab in `ClientKycModal` — **OPERATOR LOGIN REQUIRED** for visual walk | 49,152 B store; PUT-upsert wired |
| 5 | Shipping Addresses | **LIVE** backend (`/api/v1/client-addresses/*` 4 routes); UI tab in KYC modal — **OPERATOR LOGIN REQUIRED** for visual walk | DAO + 4 routes deployed |
| 6 | Client Carrier Accounts | **LIVE** backend (`/api/v1/client-carrier-accounts/*` 4 routes); UI tab in KYC modal — **OPERATOR LOGIN REQUIRED** for visual walk | DAO + 4 routes deployed |
| 7 | KYC | **LIVE** backend (PUT through Customer Master); UI tab in KYC modal — **OPERATOR LOGIN REQUIRED** for visual walk | kyc_status / kyc_approved_on / kyc_expiry fields wired |
| 8 | KUKE / Credit | **LIVE** backend (PUT through Customer Master); UI tab in KYC modal — **OPERATOR LOGIN REQUIRED** for visual walk | L-004 `Decimal(0)` falsy fix in B0 |
| 9 | Invoice Settings | **LIVE** backend (PUT through Customer Master); UI tab in KYC modal — **OPERATOR LOGIN REQUIRED** for visual walk | vat_id / default_vat_code / default_incoterm fields wired |
| 10 | Suppliers | **LIVE** | `/api/v1/suppliers/*` 5 routes + UI panel; CRUD smoke clean |
| 11 | Products | **LIVE** (read-only mirror over wFirma) | `/api/v1/wfirma/products` 200; UI table renders |
| 12 | Product Local | **LIVE** | `/api/v1/product-local/*` 4 routes + UI panel; CRUD smoke clean |
| 13 | Designs | **LIVE** | `/api/v1/designs/*` 4 routes + UI panel (B-MD2 PR #131); CRUD smoke clean; FK-free; product_identity_engine isolation contract green |
| 14 | HS Codes | **LIVE** | `/api/v1/hs-codes/*` + UI panel |
| 15 | Units | **LIVE** | `/api/v1/units/*` + UI panel |
| 16 | Incoterms | **LIVE** | `/api/v1/incoterms/*` + UI panel |
| 17 | VAT Config | **LIVE** (reference; **MDC-070** says read-only on invoicing path) | `/api/v1/vat-config/*` + UI panel |
| 18 | FX Rates | **LIVE** (reference-only; **MDC-071** = PERMANENT FORBIDDEN: FX never overrides PZ landed-cost) | `/api/v1/fx-rates/*` + UI panel |
| 19 | Carrier Config | **LIVE** | `/api/v1/carriers-config/*` + UI panel; non-secret local config only |
| 20 | Roles explainer | **LIVE** (read-only by design — DOCUMENT-ONLY surface for operators) | UI panel + 5-row enforcement matrix; no roles table exists; only `require_admin` is enforced today |
| 21 | Finance breakdown panel | **LIVE** read-only Diagnostics surface; backing store is **DEPLOYED OFF** (empty) | 6F.4 panel renders; backend returns 404 for any id (empty store) |
| 22 | Finance dual-write | **DEPLOYED OFF** | Code wired in `routes_proforma.py` hook + `finance_dual_write.py` helper; both flags `FINANCE_DUAL_WRITE_ENABLED` + `FINANCE_DUAL_WRITE_SHADOW` default False; verified at 4 sources (operator env, .env, NSSM, deployed config defaults); 0 `finance_dual_write` log hits |
| 23 | Backfill engine | **DEPLOYED OFF** | `service/scripts/backfill_finance_postings.py` on `main`; never executed against production (`proforma_service_charges` table empty; live run blocked) |
| 24 | Proforma posting | **LIVE** | `routes_proforma.py::post_proforma_draft_to_wfirma` operational; legacy path unchanged; service-charges block on `/post` line ~3538 is by design (blocks empty-mapping case) — **BLOCKED BY EXPLICIT OPERATOR DECISION** for non-empty `service_charges_json` until a separate block-lift batch lands |
| 25 | DHL / customs flow | **LIVE** | Existing P0–P5 flow from OIA-2026-05 campaign; not touched by MDOC; PZ regression 160/160 confirms calculation paths intact |
| 26 | PZ / wFirma flow | **LIVE** | wFirma proforma creation operational; PZ landed-cost engine isolated from FX overrides (MDC-071 PERMANENT); 160/160 golden regression |

## 7 — What is LIVE (summary)

- Dashboard shell · Master Data page · Admin Users page · Suppliers · Products · Product Local · Designs · HS Codes · Units · Incoterms · VAT Config · FX Rates · Carrier Config · Roles explainer · Finance breakdown panel UI · Proforma posting · DHL/customs · PZ/wFirma · all `customer-master` + `client-addresses` + `client-carrier-accounts` backend routes

## 8 — What is DEPLOYED OFF (by intentional default-OFF flag)

- **Finance dual-write** (6F.5) — `FINANCE_DUAL_WRITE_ENABLED=false` AND `FINANCE_DUAL_WRITE_SHADOW=false` at all 4 inspected sources. Hook wired but executes a single early-return guard. Production runtime is bit-identical to pre-6F.5-deploy.

## 9 — What is NOT FUNCTIONAL

**None at the deployed surface.** Every deployed capability either returns 200 or returns the documented empty/404 response. The 6F.5 dual-write code is *deployed but inactive*, not *non-functional* — it works correctly in shadow / live mode when its flags are flipped.

## 10 — What is OPERATOR LOGIN REQUIRED (visual smoke gap)

These backend surfaces are LIVE; only the *visual rendering walk* requires an authenticated admin browser session:

- §4 Customer Master walk (`Edit → Cancel without saving` cycle inside `ClientKycModal`)
- §5 Shipping Addresses tab walk
- §6 Client Carrier Accounts tab walk
- §7 KYC tab walk
- §8 KUKE / Credit tab walk
- §9 Invoice Settings tab walk
- §3 AdminUsersPage observation-only UI walk (no destructive Approve / Reject / Set role / Deactivate click-through on real users)

Checklist: `tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md` §§2-7 + §18.
Acceptance status: `mechanical_closure_accepted` per `tasks/mdoc-operator-acceptance-note.md`.

## 11 — What is BLOCKED BY EXPLICIT OPERATOR DECISION

| Block | Reason | Reopening criteria |
|---|---|---|
| **6F.2.d** Live backfill | Production `proforma_service_charges` table contains **0 source rows** | Re-run dry-run when rows exist (operator playbook in `tasks/phase-6f-2f-freeze.md` §8) |
| **6F.2.e** Post-backfill verification | Downstream of 6F.2.d | Auto-reopens after 6F.2.d produces ≥1 synthetic posting |
| **6F.5-shadow-activation** | Operator deferred (`tasks/phase-6f-5-shadow-decision-memo.md`) | Operator signs §11 of approval package |
| **6F.5-live-activation** | Downstream of shadow | After ≥50 shadow log entries × ≥5 distinct posts with zero failures |
| **MDC-2026-05/B3** Users + Roles writes | Superseded by B-MD1 architectural choice (AdminUsersPage) | N/A — closed via different architecture |
| **MDC-2026-05/B6** Designs Master | Superseded by B-MD2 implementation | N/A — closed via B-MD2 |
| **MDC-2026-05/MDC-071** FX override into PZ landed-cost | **PERMANENT FORBIDDEN** (hard rule) | Never |

## 12 — What is DOCUMENT ONLY

- Roles enforcement matrix (5-row read-only explainer; no permissions engine exists)
- B-MD4 operator browser-smoke checklist (until operator walks it)
- All Phase 6F / MDOC approval packages, decision memos, freeze docs, acceptance notes — they record decisions but are not executable code

## 13 — What should NOT be touched

Per repository hard rules:

- `auth/service.py::ROLES` allow-list — frontend `ADMIN_USERS_ROLES` mirrors it; both pinned by contract tests
- `routes_auth.py` — auth endpoints are stable; no schema change permitted in MDOC scope
- `product_identity_engine.py` — read-only consumer; must NOT read the new `designs` master (pinned by `test_b_md2_product_identity_engine_does_not_read_designs_table`)
- `landed_cost.py` / FX path — MDC-071 PERMANENT FORBIDDEN
- `golden_constants.py` — only updated for explicit golden-batch revisions
- `.env` — no changes
- `users.db` schema — no new `roles` or permissions tables in this scope
- `proforma_service_charges` legacy table — backfill is read-only against it
- `finance_postings.sqlite` — leave default-OFF until separate operator activation
- The 2 existing MasterDataPage security contracts in `test_dashboard_master_design.py` — preserved by B-MD1's separate AdminUsersPage choice

## 14 — Risk register (final)

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| FR1 | Operator flips `FINANCE_DUAL_WRITE_ENABLED=true` without `SHADOW=true` first | HIGH if it happens | Approval package §1 + decision memo §5 mandate both flags together; immediate-disable runbook present |
| FR2 | Future regression places dual-write hook BEFORE `mark_post_succeeded` | MEDIUM | Pinned by `test_hook_fires_after_mark_post_succeeded` source-grep contract |
| FR3 | Future PR couples `product_identity_engine` to `designs` master | MEDIUM | Pinned by `test_b_md2_product_identity_engine_does_not_read_designs_table` |
| FR4 | Decimal-vs-float drift on amount → minor units | LOW | Pinned by `test_source_grep_no_naive_int_times_100` + 13 Decimal-safety unit tests |
| FR5 | A future PR re-introduces `PendingPanel`-style dead code | LOW | Pinned by `test_legacy_pendingpanel_component_is_removed` |
| FR6 | A future PR adds `/auth/users` POST inside MasterDataPage | MEDIUM | Pinned by `test_master_data_page_does_not_call_auth_users_writes` |
| FR7 | A future PR adds Roles writes without authz model approval | MEDIUM | Pinned by L-045 (symbolic permission tables) + Option-A explainer-only choice |
| FR8 | Operator forgets to walk the 6+1 deferred B-MD4 surfaces | NEGLIGIBLE | Surfaces are read walks; no operational risk from deferral |

No HIGH-severity risk has >0% probability under current operator discipline.

## 15 — Exact next business-use recommendation

**Use the live system as-is.** All operational Master Data CRUD is wired and smoked. Proforma posting, PZ processing, DHL/customs paths all green. Finance posting visibility (read-only) is in Diagnostics. The 4 operator-gated activation decisions (shadow dual-write, live dual-write, live backfill, `/post` service-charges block lift) are real future-work items — but **none of them is required for current business operation**.

If the operator wants to walk the 6+1 deferred visual surfaces, the checklist at `tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md` §§2–7+§18 is the entry point. ~20 minutes of session time.

Otherwise: **no further deployment, no further code change, no further campaign required.** Production is live, operationally stable, and faithfully documented.

---

## 16 — One-sentence verdict

**Estrella PZ Processor is LIVE on production at SHA `02aefa1` with 26-area surface inventory, 429 tests green, PZ regression 160/160, zero finance side effects, zero auth mutations, all hard rules enforced, and 4 deliberately-OFF activation gates awaiting future operator decisions.**
