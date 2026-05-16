# Estrella Real Operator E2E Validation Report

> **Generated:** 2026-05-16
> **Method:** Live Chrome session via `claude-in-chrome` MCP (CDP). Logged in
> as **`amitsaniya@gmail.com` (role: admin)** on the operator's local Windows
> Chrome browser.
> **Production SHAs walked:** `02aefa1` (initial walk) and `3a372cc` (after
> the single defect fix).
> **Truth standard:** Browser-rendered DOM. Not file hashes. Not API success.
> Not source-grep.

---

## 1 — Browser session evidence

| Item | Value |
|---|---|
| Tab URL | `https://pz.estrellajewels.eu/dashboard/dashboard.html` |
| Document title | `Estrella PZ Customs Control` |
| Page state | `document.readyState === 'complete'` |
| Logged-in user (DOM) | `Amit Saniya` |
| Role badge (DOM) | `ADMIN ✓` (top-right header) |
| Service workers active | observed via network log; all hits go through prod uvicorn |

**Initial walk caveat:** The first screenshot revealed a stale-cached page (Admin · Users missing from sidebar; "Designs / Roles structure-preview — backend pending" footer; KYC and Invoices tabs labelled "BACKEND PENDING"). A `Ctrl+Shift+R` hard reload immediately surfaced the correct B-MD3 content. The `Cache-Control: no-cache, no-store, must-revalidate` header on `.html` is present in production main.py, so the stale state was a one-time browser-cache artefact from before the B-MD3 deploy. Subsequent navigation always served fresh content.

## 2 — 12 surface walk (DOM truth)

| # | Surface | Result | DOM evidence |
|---|---|---|---|
| 1 | **Admin Users** | **LIVE_VISIBLE** | `data-testid="admin-users-page"` present · 2 user rows loaded (`tejal@estrellajewels.com` role=accounts; `amitsaniya@gmail.com` role=admin) · counters Total 2 / Pending 0 / Approved 2 / Inactive 0 · search + refresh + invite-disabled chip present · self-row shows `admin-users-self-noactions` (lockout guard active) · other row shows `admin-users-select-role` + `admin-users-btn-deactivate` |
| 2 | **Designs** | **LIVE_VISIBLE** | `master-designs-panel` + `master-designs-btn-new` present · 0 rows (empty production state) · header text "Designs — Local design master — code, display name, family/collection, soft refs only. product_identity_engine is read-only against this table." · clicked "+ New Design" → `master-designs-form` + `master-designs-input-code` + `master-designs-input-active` + `master-designs-btn-save` + `master-designs-btn-cancel` all appeared · Cancel closed form cleanly (no write) |
| 3 | **Roles explainer** | **LIVE_VISIBLE** | `master-roles-panel` + `master-roles-explainer` + `master-roles-enforcement-matrix` + `master-roles-btn-open-admin-users` all present · matrix has **5 rows** (admin / accounts / logistics / auditor / viewer) · only 2 buttons in panel (header refresh ↻, nav "Open Admin · Users →") — **zero role-write buttons** · explainer text contains "Enforcement today: only the admin role is differentially enforced" |
| 4 | **Suppliers** | **LIVE_VISIBLE** | `master-suppliers-panel` present · `+ New Supplier` button present · "No suppliers registered yet" empty state · subtitle "Goods exporters / consignment senders — local registry, no wFirma write" |
| 5 | **Product Local** | **LIVE_VISIBLE** | `master-product-local-panel` present · `+ New augmentation` button present · subtitle "Local overrides for wFirma products — HS code, unit, design link, notes" |
| 6 | **Finance posting breakdown (Diagnostics)** | **LIVE_VISIBLE** | `diagnostics-finance-posting-panel` + `diagnostics-finance-readonly-badge` + `diagnostics-finance-posting-id-input` + `diagnostics-finance-posting-fetch` + `diagnostics-finance-schema-chip` all present · only **1 button** (Fetch) · typed `999999` + Fetch → `diagnostics-finance-posting-empty` rendered with text "No posting with id 999999 ... By design: the finance posting store is dormant until backfill runs or a posting is created. This is expected when production has 0 postings. No system action is required." |
| 7 | **Customer Master modal: Company / Basic tab** | **LIVE_VISIBLE** with 5 inline pending fields | Form renders: Company name * / Country (ISO alpha-2) * / Short code (Backend pending) / Client type (Backend pending) / Company / Industry (Backend pending) / Default currency dropdown / VAT EU number / NIP / EORI number (Backend pending) / REGON (Backend pending). **5 individual fields marked "Backend pending"** — these are field-level, not tab-level. Tab itself renders correctly. |
| 8 | **Customer Master modal: Shipping tab** | **LIVE_VISIBLE** | Form: Bill-to address (wFirma contractor) — "Contractor ID: 90484280" displayed · Ship-to address section · Saved delivery addresses · "+ Add address" button · "No saved delivery addresses" empty state |
| 9 | **Customer Master modal: Carriers tab** | **LIVE_VISIBLE** | Section: Carrier accounts · "+ Add account" button · "No carrier accounts configured yet" empty state |
| 10 | **Customer Master modal: KYC / Compliance tab** | **LIVE_VISIBLE** | Form: KYC Status dropdown (approved/pending/review/rejected) · Approved on / Expiry date · Beneficial owner · Owner ID type (passport/id_card/drivers_license) · Owner ID number · AML risk rating (low/medium/high) · PEP check result (clear/flagged/pending) · Compliance notes |
| 11 | **Customer Master modal: KUKE & Credit tab** | **LIVE_VISIBLE** | Form: KUKE Insurance section (KUKE limit + Currency + Expiry + Policy + Self-retention %) · Credit section (Credit limit + Currency + Payment terms) · Risk status dropdown (low/medium/high/blocked) |
| 12 | **Customer Master modal: Invoices tab** | **LIVE_VISIBLE** | Form: wFirma document defaults (Preferred proforma series / Preferred invoice series / VAT mode 222 standard, 228 reverse charge, 229 export 0%) · Default language ID · Payment defaults (terms in days / Default currency) · Invoice & proforma history section |

---

## 3 — Defect found and fixed in this run

**One UI defect detected, fixed, deployed, re-verified all in the same operator session.**

### Defect description
Master Data top KPI strip showed:
- **Number: 3** (numerically literal)
- **Subtitle: "Suppliers · Designs · HS · FX · Roles"** (5 names)

Root cause (`service/app/static/dashboard.html` line 3746 pre-fix):
```js
const PENDING_TYPES = ['designs','fx_rates','roles'];
```
And the hint string was hard-coded as `'Suppliers · Designs · HS · FX · Roles'` — both reflected MDC-era state before B-MD2/B8 landed.

### Truth
- `designs` is LIVE since B-MD2 (PR #131)
- `fx_rates` is LIVE since MDC-B8 (reference-only; MDC-071 forbids PZ override)
- `roles` is **intentionally** a read-only explainer panel (B-MD2c) — not "pending"
- `suppliers` / `hs_codes` were never in the array, only stale in the hint text

### Fix (PR #139, merged `3a372cc`)
- `PENDING_TYPES = [];`
- Hint string now derives from the array: `PENDING_TYPES.length === 0 ? 'All entity types live (Roles is read-only explainer)' : PENDING_TYPES.join(' · ')`
- 2 regression tests added in `service/tests/test_dashboard_master_cleanup.py`:
  - `test_pending_types_kpi_array_is_empty` (pins `PENDING_TYPES = []`)
  - `test_pending_types_kpi_hint_is_accurate` (forbids the stale MDC-era name list as a literal KPI hint string)

### Deploy
Robocopy `dashboard.html` → `C:\PZ\app\static\dashboard.html` + `sc.exe stop/start PZService` + 12-sec wait + health check. Local + public health 200/200.

### Browser re-verification (DOM after hard-reload at SHA `3a372cc`)
Production browser now reads literally: **"PENDING TYPES 0 / All entity types live (Roles is read-only explainer)"**. Stale text `Suppliers · Designs · HS · FX · Roles` is GONE. Screenshot captured.

---

## 4 — Console and network

| Channel | Result |
|---|---|
| Browser console | Read with pattern `error\|warning\|exception\|fail\|Uncaught\|TypeError\|ReferenceError` — **no messages matched**. CDP `read_console_messages` returned: "No console messages found for this tab." |
| Network requests | 33 API calls observed during the walk — **all 200** except `/api/v1/finance/postings/999999/breakdown → 404` (intentional empty-state probe in Surface 6). Two `pending` status entries for `/customer-master/{id}/shipping-addresses/` and `/carrier-accounts/` were in-flight at the moment of read — they were follow-up loads, not failures. |

API endpoints observed working:
`/api/v1/health` · `/api/v1/admin/email-queue` · `/api/v1/system/version` · `/api/v1/debug/health-full` · `/api/v1/debug/storage/health` · `/api/v1/debug/storage/locks` · `/api/v1/debug/pending` · `/api/v1/wfirma/customers` · `/api/v1/wfirma/products` · `/api/v1/customer-master/` · `/api/v1/customer-master/90484280/shipping-addresses` · `/api/v1/customer-master/90484280/carrier-accounts` · `/api/v1/designs/` · `/api/v1/suppliers/` · `/api/v1/product-local/` · `/api/v1/carrier/status` · `/api/v1/carrier/shadow/log` · `/api/v1/finance/postings/999999/breakdown` (intentional 404).

---

## 5 — Data mutation discipline

**Zero real data mutated** during this run:
- No user approve/reject/role/activate/deactivate clicked (Surface 1 was DOM inspection only)
- No supplier saved (Surface 4 verified empty state only)
- No product local saved (Surface 5 verified empty state only)
- No design saved (Surface 2 form opened + cancelled cleanly)
- No customer master saved (Surface 7 form opened, fields read, modal cancelled)
- No finance flag flipped, no env var set
- No wFirma/PZ/DHL/customs/FX touched

**One temp record CRUD round-trip** was performed via API curl during the initial parity sweep (PR #138, before this run): `SMOKE_FINAL_DSGN` design — created, fetched, deleted, 404-confirmed. No stale row.

---

## 6 — Final browser-truth status table

Using the strict 7-value taxonomy required by the brief:

| Feature | Status |
|---|---|
| Admin Users | **LIVE_VISIBLE** |
| Designs | **LIVE_VISIBLE** |
| Roles explainer | **LIVE_VISIBLE** |
| Suppliers | **LIVE_VISIBLE** |
| Product Local | **LIVE_VISIBLE** |
| Finance breakdown panel | **LIVE_VISIBLE** |
| Customer Master modal | **LIVE_VISIBLE** |
| Shipping tab | **LIVE_VISIBLE** |
| Carrier Accounts tab | **LIVE_VISIBLE** |
| KYC tab | **LIVE_VISIBLE** |
| KUKE tab | **LIVE_VISIBLE** |
| Invoice Settings tab | **LIVE_VISIBLE** |
| Pending Types KPI (post-fix) | **LIVE_VISIBLE** ("PENDING TYPES 0 / All entity types live") |

**All 12 brief-required surfaces: LIVE_VISIBLE.** Plus 1 KPI defect (`PENDING_TYPES` stale) found and fixed inside the same operator session, with PR #139 merged at `3a372cc` and deploy verified in the browser.

---

## 7 — Honest caveats

1. **Initial stale-cache moment.** The first screenshot showed stale content. This was the operator's existing browser tab that loaded before B-MD3 deployed. A single hard-reload fixed it. The production server correctly sends `Cache-Control: no-cache, no-store, must-revalidate` on `.html` responses, so the stale state cannot persist past the next request.
2. **Five "Backend pending" inline labels remain on the Company / Basic tab** — these are field-level (Short code, Client type, Industry, EORI, REGON) and are NOT a defect of this campaign. They are documented design state: those wFirma-side fields haven't been wired yet. The TAB renders correctly; only those 5 fields show inline placeholders. No campaign promised wiring those fields.
3. **CDP `Page.captureScreenshot` timed out** twice during the run (~30-sec timeout on a slow renderer). Mitigated by reading the DOM directly via JavaScript injection. Screenshots that did succeed are saved.
4. **The walk was operator-session-driven on the local Windows browser** ("Browser 1" device id `f3a3ecfc-…`). The operator chose this browser. No mobile / no remote `wokr laptop` browser walked.

---

## 8 — Production SHA after this run

- `main` HEAD: `3a372cc6229b022c8f1d5f705f3e446fe750d990` (PR #139 merged)
- Production `C:\PZ\app\static\dashboard.html`: deployed at 2026-05-16T17:37 local, contains the post-fix bytes
- All previously-deployed runtime files (`main.py`, `routes_master_data.py`, `master_data_db.py`, `finance_dual_write.py`, `routes_finance_postings.py`, `routes_proforma.py`, `routes_auth.py`, `core/config.py`) unchanged
- `finance_postings.sqlite` 81,920 B unchanged · `users.db` 32,768 B unchanged · `master_data.sqlite` 114,688 B (no schema or data changes from this run)

---

## 9 — Verdict

**Production UI is verified LIVE_VISIBLE on all 12 surfaces the operator asked about, via real Chrome DOM inspection with admin session.** One UI cosmetic defect (stale `PENDING_TYPES` KPI) was found, fixed in PR #139, merged at `3a372cc`, deployed, and re-verified in the same browser session — the new "PENDING TYPES 0 / All entity types live (Roles is read-only explainer)" KPI was confirmed rendering. No console errors. No unexpected 4xx/5xx. No data mutated. Phase 6F paused-state guarantees intact (6F.5 default-OFF; `finance_postings.sqlite` unchanged; zero `finance_dual_write` log hits).

The previous parity audit (PR #138) had concluded "production faithfully deployed" based on file hashes + API reachability — that conclusion was 95% right. The 5% gap was this single cosmetic KPI defect that only a real browser walk could detect. The audit is now corrected; subsequent reports may cite it without the asterisk.
