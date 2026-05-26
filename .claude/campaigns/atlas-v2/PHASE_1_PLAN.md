# Atlas V2 — Phase One Implementation Plan

**Date:** 2026-05-26
**Author:** orchestrator session (autonomous master campaign)
**Scope:** read-only frontend Phase One. Zero backend writes. Zero V1 edits.
**Inputs:** PHASE_0_AUDIT.md + design-files/Estrella Dashboard.html (origin/atlas-v2/source-bundle) + full route inspection.

---

## 1. Atlas V2 URL Map (10 Phase One pages)

All pages served by the existing auth-gated static handler at
`service/app/main.py:541` (`/dashboard/{path:path}` → `service/app/static/<path>`).
No new Python routes required.

| # | URL | File on disk | Current status |
|---|-----|--------------|----------------|
| 1 | `/dashboard/atlas/dashboard-v2.html` | `service/app/static/atlas/dashboard-v2.html` | **NEW** — refactored from existing `/dashboard/dashboard-v2.html` to use shared shell |
| 2 | `/dashboard/atlas/api-status-v2.html` | `service/app/static/atlas/api-status-v2.html` | **NEW** — functional read-only |
| 3 | `/dashboard/atlas/search-v2.html` | `service/app/static/atlas/search-v2.html` | **NEW** — functional read-only |
| 4 | `/dashboard/atlas/ledgers-v2.html` | `service/app/static/atlas/ledgers-v2.html` | **NEW** — functional read-only |
| 5 | `/dashboard/atlas/inbox-v2.html` | `service/app/static/atlas/inbox-v2.html` | **NEW STUB** — visual shell, all actions disabled |
| 6 | `/dashboard/atlas/shipments-v2.html` | `service/app/static/atlas/shipments-v2.html` | **NEW STUB** — read-only batch list + disabled write actions |
| 7 | `/dashboard/atlas/documents-v2.html` | `service/app/static/atlas/documents-v2.html` | **NEW STUB** — visual shell |
| 8 | `/dashboard/atlas/pz-v2.html` | `service/app/static/atlas/pz-v2.html` | **NEW STUB** — visual shell, PZ writes deferred |
| 9 | `/dashboard/atlas/proforma-v2.html` | `service/app/static/atlas/proforma-v2.html` | **NEW STUB** — distinct from existing live `/dashboard/proforma-v2.html` (which remains operational) |
| 10 | `/dashboard/atlas/accounting-v2.html` | `service/app/static/atlas/accounting-v2.html` | **NEW STUB** — visual shell |

**Backward compatibility:** the existing `/dashboard/dashboard-v2.html` (single-file 455 LOC version) is **kept in place unchanged** for backward compatibility with any bookmarks. The new canonical Atlas version lives at `/dashboard/atlas/dashboard-v2.html`. No redirect logic added — both paths return valid pages (different LOC, same data, same authority).

**The live operational `/dashboard/proforma-v2.html`** (797 LOC, currently used by operators) is **not touched**. The new `/dashboard/atlas/proforma-v2.html` is a visual shell preview of the future re-skinned proforma; the operational page remains the source of truth until a separate Sprint formally migrates it.

---

## 2. Page Authority Map

| URL | Visual source | Backend routes consumed | Data model |
|-----|--------------|--------------------------|------------|
| atlas/dashboard-v2.html | `design-files/Estrella Dashboard.html` (root view) + `dashboard-kanban.jsx` | `GET /dashboard/batches` | Batch summaries with derived status / clearance_status / sad_status / pz_status / tracking_status_key (from `_batch_summary()` at `routes_dashboard.py:369`) |
| atlas/api-status-v2.html | `design-files/api-status-page.jsx` | `GET /api/v1/system/version`, `GET /api/v1/debug/health-full`, `GET /api/v1/debug/storage/health`, `GET /api/v1/debug/storage/locks` | System version + service health + storage state |
| atlas/search-v2.html | `design-files/global-search.jsx` | `GET /api/v1/search?q=` | Authority-data search results (customers, suppliers, products, documents, shipments) |
| atlas/ledgers-v2.html | `design-files/ledgers-page.jsx` | `GET /api/v1/ledgers/clients/{id}/invoice-ledger.json`, `GET /api/v1/ledgers/clients/{id}/statement.json`, `GET /api/v1/customer-master/` (list clients), `GET /api/v1/ledgers/clients/{id}/statement.pdf` (download) | Client invoice ledger, statement (read-only) |
| atlas/inbox-v2.html | `design-files/inbox-page.jsx` | (Phase 2) `GET /api/v1/admin/email-queue`, `GET /api/v1/action-proposals`, `GET /api/v1/dashboard/batches` filtered by clearance pending | unified queue: emails + proposals + customs holds |
| atlas/shipments-v2.html | `design-files/dashboard-page.jsx` | `GET /dashboard/batches` (list view) | Batch summaries (read-only) |
| atlas/documents-v2.html | `design-files/documents-hub.jsx` | (Phase 2) per-doc-type lists; today only `GET /dashboard/batches/{id}/files` exists | Document type filter, per-batch file list |
| atlas/pz-v2.html | (per-PZ extension of `design-files/pages.jsx`) | `GET /api/v1/pz/lineage/{batch_id}` (read), `GET /api/v1/pz/correction-state` (read). Writes deferred. | PZ lineage + correction state read-only |
| atlas/proforma-v2.html | `design-files/proforma-list.jsx` + `proforma-detail.jsx` | shell only — defers to live `/dashboard/proforma-v2.html` for actual operations | n/a (shell) |
| atlas/accounting-v2.html | `design-files/accounting-hub.jsx` | (Phase 2) consolidated reads of routes_proforma + routes_wfirma + routes_finance_postings + routes_sales + routes_suppliers + routes_ledgers. Today only individual surfaces exist. | n/a (shell) |

---

## 3. API Availability Matrix

Read-only Phase One uses only endpoints classified **safe**.

| Route file | Endpoint | Method | R/W | Stability | Phase One safe? |
|-----------|----------|--------|-----|-----------|------------------|
| routes_dashboard.py | `/dashboard/batches` | GET | R | stable, used by V1 | ✅ YES |
| routes_dashboard.py | `/dashboard/batches/{id}` | GET | R | stable | ✅ YES |
| routes_dashboard.py | `/dashboard/batches/{id}/files` | GET | R | stable | ✅ YES |
| routes_dashboard.py | `/dashboard/batches/{id}/files/{filename}` | DELETE | W | stable | ❌ NO (write) |
| routes_dashboard.py | `/dashboard/batches/{id}/regenerate` | POST | W | stable | ❌ NO (write) |
| routes_search.py | `/api/v1/search` | GET | R | stable | ✅ YES |
| routes_ledgers.py | `/api/v1/ledgers/clients/{id}/invoice-ledger.json` | GET | R | stable | ✅ YES |
| routes_ledgers.py | `/api/v1/ledgers/clients/{id}/statement.json` | GET | R | stable | ✅ YES |
| routes_ledgers.py | `/api/v1/ledgers/clients/{id}/statement.pdf` | GET | R (artifact) | stable, **Lesson G applies** | ✅ YES (verify cache headers downstream) |
| routes_customer_master.py | `/api/v1/customer-master/` | GET | R | stable | ✅ YES |
| routes_customer_master.py | `/api/v1/customer-master/{id}` | PUT | W | stable | ❌ NO (write) |
| routes_system.py | `/api/v1/system/version` | GET | R | stable | ✅ YES |
| routes_debug.py | `/api/v1/debug/health-full` | GET | R | stable | ✅ YES |
| routes_debug.py | `/api/v1/debug/storage/health` | GET | R | stable | ✅ YES |
| routes_debug.py | `/api/v1/debug/storage/locks` | GET | R | stable | ✅ YES |
| routes_debug.py | `/api/v1/debug/post-pz-test` | POST | W | dev tool | ❌ NO (write) |
| routes_admin.py | `/api/v1/admin/email-queue` | GET | R | stable | ✅ YES |
| routes_admin.py | `/api/v1/admin/email-queue/{id}/send` | POST | W | stable | ❌ NO (write) |
| routes_pz.py | `/api/v1/pz/lineage/{batch_id}` | GET | R | stable | ✅ YES |
| routes_pz.py | 8 correction-state endpoints | GET/POST | mixed | stable, behind feature flag | ⚠ READ-ONLY ones safe; writes excluded |
| routes_proforma.py | `/api/v1/proforma/drafts` | GET | R | stable | ✅ YES |
| routes_proforma.py | proforma write endpoints | POST | W | stable | ❌ NO (write) |
| routes_wfirma.py | 10+ POST endpoints (pz_create / pz_adopt / pz_confirm etc.) | POST | W | stable | ❌ NO (write) |
| routes_dhl_clearance.py | `/dhl/clearance/...` reads | GET | R | stable | ✅ YES |
| routes_dhl_followup.py | followup state reads | GET | R | stable | ✅ YES |
| routes_dhl_followup.py | followup send/enable | POST | W | gated by feature flag | ❌ NO (write) |
| routes_inventory*.py | all endpoints | mixed | mixed | stable, behind state machine | ❌ NO (write paths exist; safer to defer) |
| routes_carrier*.py | all endpoints | mixed | mixed | stable | ❌ NO (write paths exist; safer to defer) |
| routes_action_proposals.py | proposal reads | GET | R | stable | ✅ YES |
| routes_batch.py | `/api/v1/batch/sessions` | GET | R | stable | ✅ YES |

---

## 4. Missing Functions / Endpoint Gaps

Endpoints a Phase One page would want but that **do not exist today**. Severity = blast radius if missing.

| Page | Gap | Severity | Phase Two owner |
|------|-----|----------|-----------------|
| atlas/api-status-v2.html | No aggregated `/api/v1/admin/api-status` endpoint that returns per-integration health in one call. Today, health must be assembled from 4 separate calls (system/version + debug/health-full + debug/storage/health + debug/storage/locks). Phase One assembles client-side. | MEDIUM | backend-api (Sprint 22) |
| atlas/api-status-v2.html | No `/api/v1/admin/api-status/endpoints` registry endpoint. Design shows a searchable endpoint registry; today no backend produces it. | MEDIUM | backend-api (Sprint 22) |
| atlas/api-status-v2.html | No `/api/v1/admin/api-status/errors` recent-errors endpoint. Design shows recent errors panel. | LOW | backend-api (Sprint 22) |
| atlas/api-status-v2.html | No synthetic-probe POST. Design shows "Re-probe" button; today no equivalent. Phase One renders button **disabled**. | LOW | backend-api (Sprint 22) |
| atlas/search-v2.html | No "recent search" endpoint. Design shows recents on empty state; Phase One shows empty state instead. | LOW | backend-api (Sprint 18) |
| atlas/ledgers-v2.html | No `/api/v1/ledgers/suppliers/{id}` symmetric supplier-ledger endpoint. Clients-only today. Phase One shows Clients tab; Suppliers tab disabled with tooltip. | MEDIUM | backend-api (Sprint 15) |
| atlas/ledgers-v2.html | No aging-bucket aggregator endpoint. Design shows aging strip; Phase One derives client-side from statement transactions. | LOW | optional Sprint 15 |
| atlas/inbox-v2.html | No unified `/api/v1/inbox` endpoint. Inbox combines emails + proposals + customs-pending. Phase One: STUB. | HIGH (blocks functional inbox) | backend-api (Sprint 02) |
| atlas/shipments-v2.html | `/dashboard/batches` exists but lacks several fields the design shows (clearance email received timestamp, last operator note). Phase One: render available fields, leave columns blank where data missing. | LOW | optional read-only field addition (Sprint 03) |
| atlas/documents-v2.html | No `/api/v1/documents` cross-batch list endpoint. Documents are per-batch today via `/dashboard/batches/{id}/files`. Phase One: STUB. | HIGH (blocks functional docs hub) | backend-api (Sprint 04) |
| atlas/pz-v2.html | PZ V2 needs PZ list endpoint (not yet exposed publicly). `routes_pz.py` is per-batch. Phase One: STUB. | MEDIUM | backend-api (Sprint 07) |
| atlas/accounting-v2.html | Consolidated accounting reader doesn't exist; data lives across 6 route files. Phase One: STUB with deep-links to per-doc-type V1 surfaces. | MEDIUM | backend-api (Sprint 14) |

---

## 5. Duplicate Authority Risks

Every place where the frontend could create business truth or duplicate backend authority. **Phase One mitigation column states how each is avoided.**

| Risk | Where it would happen | Mitigation in Phase One |
|------|----------------------|--------------------------|
| Lane derivation in dashboard | Frontend could compute "lane=customs" from raw fields | `deriveLane()` reads ONLY backend-derived `status`/`clearance_status`/`sad_status`/`pz_status`/`tracking_status_key`. Mapper is a pure visual bucketing — if backend semantics change, mapper changes. Backend stays the truth source. |
| Priority badge (urgent/high/normal) | Frontend could invent urgency thresholds | `derivePriority()` reads ONLY backend signals (`status==blocked`, `failed_checks` non-empty, `clearance_status` non-cleared, `sad_status==missing`). No client-side date math, no thresholds invented. |
| Total-value KPI | Frontend could sum from invented exchange rates | Phase One sums `gross` field as-is (mixed-FX disclaimer in tile hint). No FX conversion attempted. |
| Active-shipment count | Frontend could invent "active" definition | "Active" = `deriveLane() !== 'done'`. Same backend authority chain. |
| Aging buckets in ledger | Frontend could compute aging from raw dates | Phase One: aging derived only if backend already exposes due-date fields per row. If absent, aging chip disabled. |
| Document status in docs hub | Frontend could classify "Open" / "Closed" / "Pending" | Phase One docs-v2 is STUB — no classification rendered. |
| PZ lifecycle phase | Frontend could re-derive PROPOSED→OPERATOR_REVIEWED→STAGED→etc. | Phase One pz-v2 STUB; functional version goes through `pz-state.js correctionUiPhase()` (already exists). |
| Inbox priority | Frontend could rank queue items | Phase One inbox-v2 STUB. |
| Search ranking | Backend returns ranked list; frontend re-rank could distort | Phase One renders backend order verbatim, no client-side re-rank. |
| API health "healthy/degraded/down" rollup | Frontend could compute roll-up from sub-signals | Phase One displays each sub-signal independently. Aggregate "healthy %" label deferred to Phase Two backend aggregator. |

**Lesson F binding:** atlas-shared.js (the new shared module created in this campaign) contains visual primitives only. **No domain knowledge.** Lane colors, status badges, KPI tiles — all receive props, never inspect business meaning. `dashboard-shared.js` is **not modified** by this campaign.

**Lesson I binding:** Every aggregation / mapping function is workflow-class, not shipment-class. `deriveLane()` works for any shipment; `deriveApiHealth()` works for any integration. No batch-specific paths anywhere.

---

## 6. Phase One Implementation Order

### Tier A — safe to build now (functional, read-only)

| Order | Page | Why safe |
|-------|------|----------|
| 1 | `atlas-shared.js` | New shared file. Visual primitives only. No domain knowledge. Establishes pattern for all other pages. |
| 2 | `atlas/dashboard-v2.html` | Already proven in production (existing `/dashboard/dashboard-v2.html`). Refactor to consume atlas-shared.js. Identical API surface. |
| 3 | `atlas/api-status-v2.html` | 4 read-only endpoints exist (`/api/v1/system/version`, `/api/v1/debug/health-full`, `/api/v1/debug/storage/health`, `/api/v1/debug/storage/locks`). Synthetic-probe button disabled with tooltip. |
| 4 | `atlas/search-v2.html` | `/api/v1/search` endpoint exists. Renders results in design layout. Recent-search list shows empty state pending Phase Two. |
| 5 | `atlas/ledgers-v2.html` | `/api/v1/ledgers/clients/{id}/...` 3 endpoints exist + customer-master list. Clients tab functional. Suppliers tab disabled with tooltip. Statement PDF download verified to set `Cache-Control: no-store` headers (Lesson G). |

### Tier B — visual shells now, functional later

| Order | Page | Backend gap forcing shell status |
|-------|------|----------------------------------|
| 6 | `atlas/shipments-v2.html` | Could be functional (uses `/dashboard/batches`), but the design adds columns whose data isn't ready. Shell with read-only batch list + disabled action buttons. |
| 7 | `atlas/inbox-v2.html` | No unified inbox endpoint; spans 3 backend domains. Shell. |
| 8 | `atlas/documents-v2.html` | No cross-batch documents endpoint. Shell. |
| 9 | `atlas/pz-v2.html` | Per-batch PZ endpoint exists but no list; correction writes deferred. Shell. |
| 10 | `atlas/proforma-v2.html` | Working V2 already exists at `/dashboard/proforma-v2.html`. Atlas shell is preview-only until the live one is migrated. Shell points operators to the working page. |
| 11 | `atlas/accounting-v2.html` | Data spans 6 route files; no consolidated reader. Shell with deep links. |

### Tier C — tests

| Order | File | Purpose |
|-------|------|---------|
| 12 | `service/tests/test_atlas_v2_phase1.py` | Render-smoke tests: every page returns 200 with auth, every page contains its title testid, all-buttons-visible structural assertions, no V1 regression |

---

## Safety gates — affirmed before any work fires

| Gate | Status |
|------|--------|
| No backend write paths modified | ✅ affirmed (zero Python edits) |
| No DHL / customs / PZ / wFirma / inventory / accounting write logic touched | ✅ affirmed (no service files touched) |
| `dashboard.html` (V1) untouched | ✅ affirmed |
| `dashboard-shared.js` untouched | ✅ affirmed |
| Existing `/dashboard/proforma-v2.html` (live operator surface) untouched | ✅ affirmed |
| Lesson F (V1 freeze + one-page-one-domain) | ✅ affirmed |
| GATE 2 (≤3 open PRs) | check at PR-open time; this campaign produces ONE PR for all 10 pages + shared module + tests |
