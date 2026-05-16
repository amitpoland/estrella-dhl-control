# Master Data Completion Campaign — Controller

> Campaign ID: **MDC-2026-05**
> Worktree: `.claude/worktrees/magical-cerf-a108ee`
> Start branch: `fix/proforma-module-purity` (campaign tasks branch from `main` after PR #98 merges)
> Created: 2026-05-16
> Status: **PLANNING COMPLETE — AWAITING BATCH-0 MERGE**

This is the single source of truth for the Master Data completion effort. Execution agents read this file, work the queue in order, and complete one PR batch at a time. Do not implement off-queue tasks.

---

## 1 — Source inventory (authoritative)

| Surface | File | Notes |
|---|---|---|
| Dashboard UI | `service/app/static/dashboard.html` (21 609 lines) | `MasterDataPage` @ L3271; `ClientKycModal` @ L2341; `CarriersPage` @ L4286 |
| CM REST | `service/app/api/routes_customer_master.py` | live |
| Shipping addresses REST | `service/app/api/routes_client_addresses.py` | live GET/POST/PUT/DELETE |
| Carrier accounts REST | `service/app/api/routes_client_carrier_accounts.py` | live GET/POST/PUT/DELETE |
| Auth/Users REST | `service/app/api/routes_auth.py` | `/auth/users`, `/auth/users/{id}/{approve\|reject\|role\|activate\|deactivate}` |
| wFirma read-only | `service/app/api/routes_wfirma.py` (+capabilities, +reservation) | `/api/v1/wfirma/{customers,products}` |
| Carrier runtime | `routes_carrier_actions.py`, `routes_carrier_shadow.py`, `routes_carrier_webhook.py` | NOT master data — runtime only |
| CM DB | `service/app/services/customer_master_db.py` (`customer_master.sqlite`) | live |
| Client addresses DB | `service/app/services/client_addresses_db.py` | live |
| Carrier accounts DB | `service/app/services/client_carrier_accounts_db.py` | live |
| Master contract tests | `service/tests/test_dashboard_master_design.py` (769 lines) | MUST keep green |
| CM tests | `service/tests/test_customer_master.py` (816 lines, 82 tests post-Batch-0) | MUST keep green |
| Carrier-account tests | `service/tests/test_client_carrier_accounts.py` | MUST keep green |
| Auth tests | `service/tests/test_*auth*.py` (TBD scan in B3) | MUST keep green |
| Lessons | `tasks/lessons.md` | append-only |
| Todo queue | `tasks/todo.md` | task-state mirror of this file |

---

## 2 — Domain status matrix (20 domains)

| # | Domain | UI | API | DB | Status |
|---|---|---|---|---|---|
| 1 | Clients (wFirma read) | live | live | live (wF) | ✅ LIVE |
| 2 | Customer Master config | live | live | live | ✅ LIVE (pending B0 deploy) |
| 3 | Shipping addresses | live tab | live | live | ✅ LIVE |
| 4 | Per-client carrier accounts | live tab | live | live | ✅ LIVE |
| 5 | Carrier configuration (global) | stub | none | none | 🟡 STUB |
| 6 | Users | read-only table | full | live | 🟠 PARTIAL (writes unwired) |
| 7 | Roles / permissions | stub | partial (role on user) | partial | 🟡 STUB |
| 8 | Suppliers | stub | none | none | 🟡 STUB |
| 9 | Products (wFirma read) | live | live | live (wF) | ✅ LIVE |
| 10 | Product local augmentation | none | none | none | 🟡 STUB |
| 11 | Designs | stub | none | none | 🟡 STUB |
| 12 | HS codes | stub | none | none | 🟡 STUB |
| 13 | Units | stub | none | none | 🟡 STUB |
| 14 | Incoterms | stub | none | none | 🟡 STUB |
| 15 | VAT config | stub | none | none | 🟡 STUB |
| 16 | FX rates | stub | live NBP source | none (override store) | 🟠 PARTIAL |
| 17 | wFirma sync visibility | per-row chip | live | n/a | 🟠 PARTIAL |
| 18 | KUKE / Credit | live tab | live (CM) | live (CM) | ✅ LIVE |
| 19 | KYC / Compliance | tab marked `pending: true` | live (CM) | live (CM) | 🟠 COSMETIC PENDING |
| 20 | Invoice settings (per-client) | tab marked `pending: true` | live (CM) | live (CM) | 🟠 COSMETIC PENDING |

---

## 3 — Task queue

Format: `[id] PAGE/DOMAIN — surface — current → target — backend req — DB req — UI req — tests — risk — batch — stop-cond — classification`

### Batch 0 — Customer Master 422 save bug — **IN FLIGHT**
- **MDC-001** · CM-blank-string normalisation · `_parse_body` decimal/bool/optional-string guards · DONE in PR #98 · backend: existing route · DB: none · UI: handleSave normalisation · tests: 8 new → 82/82 · risk: LOW · batch B0 · stop: merge + deploy + browser smoke · **AUTO_SAFE** (already done)

### Batch 1 — Campaign controller (this doc) — **DONE**
- **MDC-002** · Build registry & queue · this file · DONE · no app code touched · **AUTO_SAFE**

### Batch 2 — KycModal cosmetic + CM-tab rationalisation — **NEXT, AUTO_SAFE**
- **MDC-010** · KycModal · clear `pending: true` from `kyc` and `invoices` tabs (data already wired in CM) · backend: existing · DB: none · UI: edit `KYC_TABS` array @ L2342 · tests: update `test_dashboard_master_design.py` "pending tab" assertions · risk: LOW · batch B2 · stop: source-grep + browser smoke · **AUTO_SAFE**
- **MDC-011** · KycModal Invoices tab · render actual form bound to fields (`preferred_proforma_series_id`, `preferred_invoice_series_id`, `vat_mode`, `default_currency`, `default_language_id`, `payment_terms_days`) · backend: existing PUT CM · DB: existing columns · UI: new tab body · tests: new source-grep + 2 PUT round-trip tests · risk: LOW · batch B2 · stop: tests green · **AUTO_SAFE**
- **MDC-012** · KycModal KYC tab · render bound form (`kyc_status`, `kyc_approved_on`, `kyc_expiry`, `beneficial_owner`, `owner_id_type`, `owner_id_number`, `aml_risk_rating`, `pep_check_result`, `compliance_notes`) · backend: existing · DB: existing columns · UI: new tab body · tests: source-grep + PUT round-trip · risk: LOW · batch B2 · stop: tests green · **AUTO_SAFE**
- **MDC-013** · CM-tab vs KycModal · keep inline freight/insurance edit (quick path); add "Open full profile" button on CM row → triggers KycModal · backend: none · DB: none · UI: button + onClick · tests: source-grep · risk: LOW · batch B2 · stop: tests green · **AUTO_SAFE**
- **MDC-014** · Clients tab · disabled `+ New Client` retains tooltip "Create client in wFirma directly" · already correct · verify only · risk: NONE · batch B2 · **AUTO_SAFE**

### Batch 3 — Users + Roles wiring — **AUTO_SAFE with security review**
- **MDC-020** · Users table · add Action column with buttons: Approve / Reject / Set Role / Deactivate / Activate · backend: existing `/auth/users/{id}/*` POST routes · DB: existing · UI: per-row action buttons + small modals · tests: new browser-action tests + source-grep · risk: MEDIUM (auth-adjacent) · batch B3 · stop: security-review sign-off + browser smoke · **NEEDS_SECURITY_REVIEW**
- **MDC-021** · Roles panel · replace `PendingPanel` with role enumeration derived from `/auth/users` (distinct roles) plus a read-only legend of what each role permits · backend: derive client-side from users payload (no new endpoint) · DB: none · UI: new render branch for `roles` · tests: source-grep · risk: LOW · batch B3 · stop: tests green · **AUTO_SAFE**
- **MDC-022** · Reject NEW invite/signup flow from this batch · invite/signup writes deferred · **BLOCKED_EXTERNAL** until B3 security review approves additions

### Batch 4 — Suppliers — **NEEDS_SCHEMA_APPROVAL**
- **MDC-030** · `suppliers_db.py` new module · table: `suppliers(id, supplier_code UNIQUE, name, country, vat_id, eori, address, contact_email, contact_phone, active, notes, created_at, updated_at)` · CRUD functions · validate() · risk: MEDIUM (new sqlite + schema) · batch B4 · stop: schema sign-off · **NEEDS_SCHEMA_APPROVAL**
- **MDC-031** · `routes_suppliers.py` new module · GET list / GET by id / POST / PUT / DELETE · auth via `_auth` · risk: MEDIUM · batch B4 · stop: backend reviewer · **NEEDS_SECURITY_REVIEW**
- **MDC-032** · MasterData suppliers panel · replace `PendingPanel` with real table + add/edit modal · risk: LOW · batch B4 · stop: tests green · **AUTO_SAFE-AFTER-B4-30**
- **MDC-033** · Suppliers tests · DB-layer + API-layer + dashboard source-grep, mirrors `test_client_carrier_accounts.py` shape · risk: LOW · batch B4 · stop: 30+ tests pass · **AUTO_SAFE-AFTER-B4-30**

### Batch 5 — Products local + HS codes + Units — **NEEDS_SCHEMA_APPROVAL**
- **MDC-040** · HS codes DB + routes + UI · `hs_codes(hs_code PK, description_pl, description_en, duty_rate_pct, vat_rate_pct, active, notes, ...)` · risk: MEDIUM (customs-adjacent metadata; not calculation path) · batch B5 · **NEEDS_SCHEMA_APPROVAL**
- **MDC-041** · Units DB + routes + UI · `units(code PK, name_pl, name_en, unit_type, active)` · risk: LOW · batch B5 · **NEEDS_SCHEMA_APPROVAL**
- **MDC-042** · Product local augmentation · `product_local(product_code PK, hs_code_override, unit_override, design_id_link, ...)` · joins to wFirma product list at read time; **never overrides wFirma master** · risk: MEDIUM · batch B5 · **NEEDS_SCHEMA_APPROVAL**
- **MDC-043** · Tests for 040-042 · risk: LOW · batch B5

### Batch 6 — Design Master — **NEEDS_SCHEMA_APPROVAL**
- **MDC-050** · `design_master_db.py` · `designs(design_code PK, design_family, item_type, karat, material, stone_type, stone_weight_ct, color, name_pl, name_en, hs_code FK, unit FK, active, notes, created_at, updated_at)` · risk: MEDIUM (touches product_identity_engine semantics — must remain read-only consumer) · batch B6 · **NEEDS_SCHEMA_APPROVAL** + **NEEDS_SECURITY_REVIEW** (write path must not retroactively rewrite PZ history)
- **MDC-051** · routes + UI · risk: LOW · batch B6
- **MDC-052** · Compatibility audit · `design_product_bridge.py` must keep read-only behaviour; no calculation change · batch B6 · **FORBIDDEN_NOW for write to runtime** (read-only consumer only)

### Batch 7 — Incoterms + VAT config — **NEEDS_SCHEMA_APPROVAL**
- **MDC-060** · Incoterms DB + routes + UI · static codeset; rare changes · risk: LOW · batch B7 · **NEEDS_SCHEMA_APPROVAL**
- **MDC-061** · VAT config DB + routes + UI · `vat_config(country, product_type, rate_pct, rate_code, effective_from, effective_to, active)` · risk: HIGH (VAT directly affects invoicing) · batch B7 · **NEEDS_SCHEMA_APPROVAL** + **NEEDS_SECURITY_REVIEW** + write protection: VAT used in wFirma invoice writes — **must stay read-only in this batch; no write integration to invoice flow**

### Batch 8 — FX Rates override layer — **FORBIDDEN_NOW**
- **MDC-070** · FX history view (read-only of NBP cache) · risk: MEDIUM · batch B8 · **NEEDS_SECURITY_REVIEW**
- **MDC-071** · FX manual override store · **FORBIDDEN_NOW** — directly mutates landed-cost calculation path (`pz_import_processor.py` reads FX rate; override would silently change duty/freight allocation totals). Hard-rule violation: "No PZ/customs/DHL calculation changes". Defer to a separate operator-scoped campaign.

### Batch 9 — Carrier configuration page — **NEEDS_SECURITY_REVIEW**
- **MDC-080** · Carrier config DB + routes + UI · `carrier_config(carrier_code PK, name, parser_type, inbox_email, api_type, supported_services, active, notes)` · must NOT collide with carrier-runtime (`routes_carrier_*`) · UX agent must rule on naming to avoid operator confusion with existing Carriers nav page · risk: HIGH (carrier safety-gated) · batch B9 · **NEEDS_SECURITY_REVIEW** + **NEEDS_SCHEMA_APPROVAL**

### Batch 10 — wFirma sync visibility panel — **AUTO_SAFE**
- **MDC-090** · New right-rail panel under existing Clients + Products tabs showing per-row `sync_status`, `last_sync_ts`, `sync_error` from existing wFirma read endpoints · no writes · risk: LOW · batch B10 · stop: tests green · **AUTO_SAFE**
- **MDC-091** · Source-grep tests for sync chip presence · batch B10

### Batch 11 — Final Master Data browser audit + cleanup — **AUTO_SAFE**
- **MDC-100** · Browser sweep · open each entity tab, click each enabled button, capture screenshot · risk: NONE · batch B11
- **MDC-101** · Remove dead `cmEdit*` state if `MDC-013` superseded it · risk: LOW · batch B11
- **MDC-102** · Update `test_dashboard_master_design.py` "pending entities" list to match final state · batch B11
- **MDC-103** · Update CLAUDE.md memory: mark Master Data campaign complete · batch B11

---

## 4 — PR batch sequence

| Batch | Title | Classification | Dependencies | Estimated PRs |
|---|---|---|---|---|
| **B0** | CM 422 save fix | AUTO_SAFE | — | 1 (PR #98, OPEN) |
| **B1** | Campaign controller (planning only) | AUTO_SAFE | — | 0 (docs only) |
| **B2** | KycModal cosmetic + tab completion | AUTO_SAFE | B0 deployed | 1 |
| **B3** | Users + Roles wiring | NEEDS_SECURITY_REVIEW | B2 merged | 1 |
| **B4** | Suppliers | NEEDS_SCHEMA_APPROVAL | B3 merged | 1 |
| **B5** | HS + Units + Product-local | NEEDS_SCHEMA_APPROVAL | B4 merged | 1 |
| **B6** | Designs | NEEDS_SCHEMA_APPROVAL + NEEDS_SECURITY_REVIEW | B5 merged | 1 |
| **B7** | Incoterms + VAT | NEEDS_SCHEMA_APPROVAL + NEEDS_SECURITY_REVIEW | B6 merged | 1 |
| **B8** | FX rates (read-only history only; override layer **FORBIDDEN_NOW**) | NEEDS_SECURITY_REVIEW | B7 merged | 1 |
| **B9** | Carrier config | NEEDS_SECURITY_REVIEW + NEEDS_SCHEMA_APPROVAL | B8 merged | 1 |
| **B10** | wFirma sync visibility | AUTO_SAFE | B2 merged (independent of B3-B9) | 1 |
| **B11** | Final audit + cleanup | AUTO_SAFE | all above | 1 |

**Recommended execution order** if maximising autonomous safe progress: **B0 → B1 → B2 → B10 → B11**, then operator decides B3+.

**Sequential dependency order** if user wants full completion: **B0 → B1 → B2 → B3 → B4 → B5 → B6 → B7 → B8(read-only) → B9 → B10 → B11**.

---

## 5 — Classification summary

### AUTO_SAFE (8 tasks)
- MDC-001 (DONE), MDC-002 (DONE)
- MDC-010, MDC-011, MDC-012, MDC-013, MDC-014 (B2)
- MDC-021 (B3 partial)
- MDC-032/033 conditional on MDC-030/031 (B4)
- MDC-090, MDC-091 (B10)
- MDC-100, MDC-101, MDC-102, MDC-103 (B11)

### NEEDS_SCHEMA_APPROVAL (10 tasks)
MDC-030, 040, 041, 042, 050, 060, 061, 070 (data only), 080 — each introduces a new SQLite table

### NEEDS_SECURITY_REVIEW (8 tasks)
MDC-020 (auth writes), MDC-031 (supplier writes), MDC-050 (design rewrites), MDC-061 (VAT write protection), MDC-070 (FX read), MDC-080 (carrier config), MDC-052 (design-runtime read-only enforcement)

### BLOCKED_EXTERNAL (1 task)
MDC-022 (signup/invite — deferred)

### FORBIDDEN_NOW (1 task)
MDC-071 (FX manual override — mutates landed-cost path; hard-rule violation)

---

## 6 — Stop conditions (apply to every batch)

A batch MUST stop and surface to operator when ANY of the following hit:
1. wFirma live write would be needed
2. Proforma posting/approval touched
3. PZ/customs/DHL calculation change required
4. `.env` change required
5. Direct production DB/storage edit attempted
6. New table needs creation and batch is NOT classified `NEEDS_SCHEMA_APPROVAL` (i.e. unplanned schema work)
7. Test count drops below previous baseline (PZ regression must stay 160/160; CM tests ≥ 82/82; master design tests must stay green)
8. Existing test fails after change
9. Browser smoke shows console error on changed page
10. Source-grep contract in `test_dashboard_master_design.py` would have to be loosened to pass

---

## 7 — Per-batch execution protocol

Each batch follows this loop:

```
1. Read this controller file + tasks/todo.md to find next batch
2. For each task in batch (in MDC-id order):
   a. inspect relevant files
   b. implement (smallest possible diff)
   c. run focused tests for that file
3. After all tasks in batch complete:
   a. run full master test suite: pytest service/tests/test_*master*.py service/tests/test_dashboard_master_design.py service/tests/test_client_carrier_accounts.py service/tests/test_client_addresses.py -q
   b. run PZ regression: python test_pz_regression.py
   c. browser smoke if UI changed (open Master Data, click changed surface, capture console)
4. Commit, push, create PR via gh
5. Write batch summary to tasks/todo.md (mark batch complete, queue next)
6. Append lessons learned to tasks/lessons.md
7. STOP at merge gate — operator merges + deploys
```

---

## 8 — Hard rules (from CLAUDE.md, restated)

- No wFirma live posting
- No proforma posting / approval
- No PZ / customs / DHL calculation changes
- No `.env` changes
- No direct production DB / storage edits
- No fake backend data
- Backend-pending buttons may stay disabled only with a visible reason
- External integrations stay read-only unless explicitly approved
- Preserve existing working behaviour unless UX agent justifies removal

---

## 9 — Recommended first implementation batch

**B2 — KycModal cosmetic + CM-tab rationalisation**, dependencies: PR #98 (Batch 0) merged + deployed.

Why B2 first (not B3):
- Lowest risk: cosmetic + UI-only, zero new schema
- Highest user-visible value: completes the visible "KYC pending" and "Invoices pending" tabs that look broken
- Unlocks confidence for B3 (Users/Roles), which is the next AUTO_SAFE candidate after security review of auth-write wiring

Operator action required before B2 starts:
1. Merge PR #98 (Batch 0)
2. Run `/deploy` (the 7-agent gate enforces final safety)
3. Browser smoke: open ClientKycModal on a client without CM record → save without error
4. Give /plan command pointing at this controller to begin B2

---

## 10 — Lessons captured so far (see tasks/lessons.md)

1. Explore agent rejects long prompts — keep agent prompts ≤ 600 words and avoid embedded enumerations of 15+ items.
2. The dashboard's `MasterDataPage` already has all 13 entity panels structured; only 4 use real data, 9 render `PendingPanel`.
3. `test_dashboard_master_design.py` is a 769-line source-grep contract — every UI change must keep these greps green, especially the 6-tab KYC_TABS structure and the "9 pending entities" list.
4. CM fields cover KYC, KUKE, invoice settings entirely — pending tabs are cosmetic only.
5. /auth/users has full write surface; UI only renders read-only — wiring is small, but security review is mandatory.
6. FX override layer touches landed-cost path → FORBIDDEN under campaign hard rules.
