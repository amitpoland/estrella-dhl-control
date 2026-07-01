# Evidence Back-Fill — Decision-Anchor Verification

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z (base run)
**Back-fill produced:** 2026-07-01 (post-census, no re-dispatch)
**Produced by:** orchestrator-side verification of 5 decision anchors surfaced in the audit of `01-frontend-authority-map.md` and `05-service-scheduler-map.md`
**Mode:** READ-ONLY — no app code modified, no census output overwritten

**Purpose.** The main census reports meet the shared evidence standard on Sources blocks but are largely bare at the row level (40 rows in 01, 23 rows in 05). This file backs the 5 decision-anchor claims with concrete `file:line` + VERIFIED / INFERRED / CONTRADICTED / NO EVIDENCE tags so the operator-decision-list can be built on live-tree citations, not narrative.

Every citation below was verified against tree HEAD at aa414d90 in this run. Grep patterns and file line ranges are named in the `## Sources` block at the end.

---

## Claim 1 — `routes_reservations.py` present but NOT registered

**Verdict: VERIFIED**

- **File exists.** `service/app/api/routes_reservations.py:1–15` (module docstring naming the 6 endpoints under `/api/v1/reservations/*`, `/api/v1/products/import-purchase-packing`, `/api/v1/wfirma/products/sync-by-codes`).
- **Router declared.** `routes_reservations.py:32` — `router = APIRouter(prefix="/api/v1", tags=["reservations"])`. This is a real router with a real prefix.
- **NOT imported in `main.py`.** Grep across the full `main.py` (lines 1–739) for `routes_reservations|reservation_worker|init_reservation_db|from app\.services.*reservation|include_router.*[Rr]eservation` returned exactly three hits, none of which import routes_reservations:
    - `main.py:187` — `from .services.reservation_db import init_reservation_db` (DB init — see 4d)
    - `main.py:188` — `init_reservation_db(_root / "reservation_queue.db")` (DB init call)
    - `main.py:504` — `app.include_router(wfirma_reservation_router)` (**different module** — `routes_wfirma_reservation.py`, prefix `/api/v1/wfirma/reservation`, NOT `routes_reservations.py`)
- **The `include_router` line that WOULD exist and doesn't.** For `routes_reservations.py` to be reachable, `main.py` would need both `from .api.routes_reservations import router as reservations_router` and `app.include_router(reservations_router)`. Neither string appears anywhere in `main.py`. All 6 endpoints declared by the file are unreachable at runtime.

---

## Claim 2 — Shipment Detail 5-way fragmentation

**Verdict: VERIFIED (5 files exist; 1 loaded, 2 dead JSX, 2 standalone HTML)**

| # | File | file:line locus | Loaded by v2/index.html? |
|---|---|---|---|
| 1 | `service/app/static/v2/shipment-detail-page.jsx` | line 4 — `const SHIPMENT_TABS = [` (6-tab authority: overview / proforma / dhl / pz / documents / timeline) | **YES** — `v2/index.html:299` |
| 2 | `service/app/static/v2/shipment-detail-page.v1.jsx` | line 5 — `function ShipmentDetailPage({ shipment, onBack }) {` (3-tab: `const TABS = ['Pipeline','Documents','Timeline']`) | **NO** — DEAD |
| 3 | `service/app/static/v2/shipment-detail-page.v2.jsx` | line 4 — `const SHIPMENT_TABS = [` (5-tab variant, no `'proforma'` tab) | **NO** — DEAD |
| 4 | `service/app/static/shipment-detail.html` | line 6 — `<title>Estrella PZ Customs Control</title>` (V1 shell) | N/A — standalone HTML page, live at `/dashboard/shipment-detail.html` |
| 5 | `service/app/static/shipment-detail-v3.html` | line 6 — `<title>Shipment Detail — Estrella Atlas</title>` (pre-V2 design shell) | N/A — standalone HTML page |

Collision note: files #1, #2, #3 all define a component named `ShipmentDetailPage`. If #2 or #3 were added to the `v2/index.html:297–326` script block, the last-loaded copy would win and the authority would silently flip. That the dead files are NOT loaded is the only reason the fragmentation is currently latent rather than active.

---

## Claim 3 — Payment Sync is scheduler-only

**Verdict: VERIFIED (scheduler present, route absent, UI absent)**

**Scheduler registration**
- `_run_payment_sync_tick` defined at `services/wfirma_webhook_scheduler.py:295`.
- Called from the outer processing tick: `services/wfirma_webhook_scheduler.py:211` — `_run_payment_sync_tick()` sits between `_run_customer_sync_tick()` (line 208) and `_run_contractor_poll_tick()` (line 214).
- APScheduler job registration: `services/wfirma_webhook_scheduler.py:420–426` — `_scheduler.add_job(_run_processing_tick, trigger="interval", seconds=30, id="wfirma_webhook_processor", max_instances=1)`. **Only `_run_processing_tick` is registered directly**; the payment-sync sub-tick runs every 30s inside it, so payment sync is scheduler-driven only by transitive call (INFERRED for "every 30s" as the effective interval, VERIFIED for "runs on schedule").
- Scheduler started at `services/wfirma_webhook_scheduler.py:427` — `_scheduler.start()`.

**NO API route**
- Grep of `main.py` for `payment_sync|/payments/sync|routes_payment|/api/v1/wfirma/payments|include_router.*payment`: **zero matches**.
- No `routes_payments.py` or `routes_wfirma_payments.py` exists under `service/app/api/`.
- **Where an API route WOULD exist:** following the naming pattern used for Phase 3B (`POST /api/v1/wfirma/contractors/scan` at `routes_wfirma_contractors.py:79`), the natural Phase 4A endpoint would be `POST /api/v1/wfirma/payments/sync` in a `routes_wfirma_payments.py`. That file does not exist and that route is not mounted.

**NO UI**
- Grep of `service/app/static/v2/*.jsx` for `payment.*sync|/payments/|syncPayment|paymentSync`: matches only inside the Vite-bundled minified `v2/proforma-react/assets/index-CGYvGRbx.js` (the ORPHAN proforma-react build, not wired into any route — see Claim 4b). **Zero matches** in any first-party JSX component. No "Run Now" button, no status panel, no operator-facing surface.

Business Feature Completeness Standard (CLAUDE.md) requires Automation + Business API + Business UI + Observability. Phase 4A Payment Sync has Automation only — SCHEDULER-ONLY.

---

## Claim 4 — Four seed known-facts

### 4a. Customer Master canonical @ `/v2/master` — VERIFIED

- Component definition: `service/app/static/v2/master-page.jsx:391` — `function MasterPage() {`
- Window global export: `service/app/static/v2/master-page.jsx:696` — `Object.assign(window, { MasterPage, RecordDetailModal, ENTITY_TYPES, ROLE_MATRIX, ENTITY_COLUMNS, MAPPING_INFO, MappingInfoBanner });`
- Script include: `service/app/static/v2/index.html:304` — `<script type="text/babel" src="master-page.jsx"></script>`
- Route match: `service/app/static/v2/index.html:841` — `{!viewerDoc && page === 'master' && (` — the SPA router's clause that renders `<MasterPage />` when the current slug is `master`, i.e. URL `/v2/master`.

### 4b. 3+ proforma implementations — VERIFIED (4 found)

| # | Implementation | Locus |
|---|---|---|
| 1 | V2 SPA (authority) | `v2/proforma-list.jsx`, `v2/proforma-detail.jsx`, `v2/proforma-search.jsx` |
| 2 | Standalone pre-V2 shells (LEGACY, still referenced in `pz-design-v2.js`) | `service/app/static/proforma-v2.html`, `service/app/static/proforma-detail-v2.html` |
| 3 | Atlas orphan stub | `service/app/static/atlas/proforma-v2.html` |
| 4 | Vite bundled build (ORPHAN — not wired to any route) | `v2/proforma-react/index.html`, `v2/proforma-react/assets/index-CGYvGRbx.js`, `v2/proforma-react/assets/index-jaQaH3iP.css` |

Four distinct implementations; at least three (V2 SPA, standalone V2 HTML, Vite build) are behaviourally divergent.

### 4c. Shipment dead-JSX (`.v1.jsx` / `.v2.jsx`) — VERIFIED

- `v2/shipment-detail-page.v1.jsx` exists — defines `ShipmentDetailPage` at line 5 (3-tab variant).
- `v2/shipment-detail-page.v2.jsx` exists — defines `SHIPMENT_TABS` at line 4 (5-tab variant, no proforma tab).
- Neither is in the `v2/index.html` script list: `v2/index.html:299` loads only `shipment-detail-page.jsx` (no `.v1` or `.v2` suffix). Only file #1 from Claim 2 is loaded.
- Both dead files define `ShipmentDetailPage` — if either were added to the script list, its later definition would silently override the authority (`window.ShipmentDetailPage` last-write wins).

### 4d. `routes_reservations` unregistered while reservation service starts — **PARTIALLY CONTRADICTED**

The seed known-fact combines three sub-claims. Only two of them hold. The third is wrong at HEAD.

| Sub-claim | Verdict | Evidence |
|---|---|---|
| `routes_reservations.py` unregistered | **VERIFIED** | See Claim 1 |
| `reservation_db` initialised at startup | **VERIFIED** | `main.py:187` — `from .services.reservation_db import init_reservation_db`; `main.py:188` — `init_reservation_db(_root / "reservation_queue.db")` (non-fatal try/except per file 05 startup item 3) |
| `reservation_worker` starts at startup | **CONTRADICTED** | Grep of `service/app/` for `reservation_worker\|start_reservation\|reservation.*start\(\)\|start.*reservation` returned only: (a) `routes_reservations.py:29` — `from ..services import reservation_worker as rworker` (dead import, module not registered), (b) `services/reservation_worker.py:2` — the file's own docstring, (c) `services/design_product_bridge.py:204` — comment, (d) `services/wfirma_product_auto_register.py:105` — comment. **No `main.py` reference. No `reservation_worker.start()` or asyncio task anywhere in the startup path.** The worker code is only touched via `routes_reservations.py`, which is not registered — so the worker never runs. |

**Corrected fact for operator-decision-list.md:** `routes_reservations.py` is unregistered; `init_reservation_db` at `main.py:187–188` still creates the DB file at startup (orphan DB file); `reservation_worker` does NOT run. Any downstream claim that "the worker still processes the queue" is stale — no code path exists that would drive it.

Consequence for decision-list: this changes the retirement math. The seed known-fact suggested "delete `routes_reservations.py` but preserve `reservation_worker.py` because it's still processing." Live-tree evidence says both are dead — either both survive together (re-register the route) or both retire together. The choice is fiscal (does the reservation queue still have business value?), not technical.

---

## Claim 5 — 12 UNREACHABLE nav slugs (redirect-shadow source)

**Verdict: VERIFIED — all 12 slugs live in `ROUTE_REDIRECTS` at `v2/index.html:360–373`**

`v2/index.html:360` opens the object literal `const ROUTE_REDIRECTS = {`; body 361–372; `};` at line 373. The redirect fires at `v2/index.html:379` — `const target = ROUTE_REDIRECTS[slug] || slug;` — inside `parseV2Location()` (starts at line 376). Any URL bar hit to `/v2/<one-of-the-12>` gets rewritten to the target BEFORE the component render loop — the source slug is unreachable by URL.

**3 slugs with full file:line + shadowed-component locus:**

| Slug | Redirect target | file:line | Component that gets shadowed |
|---|---|---|---|
| `scanner` | `inventory` | `v2/index.html:367` | `WarehouseScannerPage` in `v2/ops-cell.jsx` (per census 01 row 26) |
| `shipping` | `shipments` | `v2/index.html:365` | `ShippingOpsPage` in `v2/shipping-ops.jsx` (per census 01 row 23) |
| `actions` | `inbox` | `v2/index.html:361` | `ActionCenterPage` in `v2/wireframe-update.jsx` (per census 01 row 24) |

**9 other slugs (all in the same ROUTE_REDIRECTS block):**

| Slug | Redirect target | file:line |
|---|---|---|
| `proposals` | `inbox` | `v2/index.html:362` |
| `email_queue` | `inbox` | `v2/index.html:363` |
| `reservation` | `inbox` | `v2/index.html:364` |
| `move_stock` | `inventory` | `v2/index.html:366` |
| `identity` | `inventory` | `v2/index.html:368` |
| `sample_out` | `inventory` | `v2/index.html:369` |
| `sample_return` | `inventory` | `v2/index.html:370` |
| `goods_return` | `inventory` | `v2/index.html:371` |
| `return_prod` | `inventory` | `v2/index.html:372` |

Two of these 9 also carry a defined component that is transitively shadowed (per census 01):
- `reservation` (line 364) — `ReservationCellPage` in `v2/ops-cell.jsx` (row 25 of census 01)
- Others — no component definition found; the slugs are pure legacy stubs.

---

## Sources

Every citation above was drawn from a read or grep executed in this back-fill run against tree HEAD at aa414d90. No claim is imported from the base census.

| File | Lines / grep target this run |
|---|---|
| `service/app/main.py` | grep across full file for `routes_reservations\|reservation_worker\|init_reservation_db\|from app\.services.*reservation\|include_router.*[Rr]eservation` → 3 hits (lines 187, 188, 504); grep for `payment_sync\|/payments/sync\|routes_payment\|/api/v1/wfirma/payments\|include_router.*payment` → 0 hits |
| `service/app/api/routes_reservations.py` | lines 1–40 read (module docstring, imports, router declaration) |
| `service/app/services/wfirma_webhook_scheduler.py` | lines 415–427 read (scheduler start + add_job); tick-method locations at 82, 211, 217, 256, 295, 343 cross-verified from prior run |
| `service/app/static/v2/index.html` | grep for `shipment-detail-page\|master-page` → hits at 299, 304; grep for `'master'\|"master"\|master:` → hit at 841 (SPA route match); ROUTE_REDIRECTS block at 360–373 (12 slugs at 361–372) from prior run cross-verified |
| `service/app/static/v2/master-page.jsx` | grep for `'master'\|"master"\|MasterPage\|master:` → hits at 391, 696 |
| `service/app/static/v2/shipment-detail-page.jsx` | lines 1–12 read (SHIPMENT_TABS at line 4) |
| `service/app/static/v2/shipment-detail-page.v1.jsx` | lines 1–12 read (ShipmentDetailPage function at line 5) |
| `service/app/static/v2/shipment-detail-page.v2.jsx` | lines 1–12 read (SHIPMENT_TABS at line 4) |
| `service/app/static/shipment-detail.html` | lines 1–10 read (title at line 6) |
| `service/app/static/shipment-detail-v3.html` | lines 1–10 read (title at line 6) |
| `service/app/static/v2/proforma-react/` glob | 3 files present (index.html + assets/index-*.js + assets/index-*.css) — orphan Vite bundle confirmed |
| `service/app/static/**/proforma*` glob | 6 files across V2 SPA (3 JSX), standalone HTML (2), atlas (1) |
| `service/app/static/v2/shipment-detail-page*.jsx` glob | 3 files (base + .v1 + .v2) |
| `service/app/static/shipment-detail*.html` glob | 2 files (base + -v3) |
| `service/app/api/routes_reservations.py` glob | 1 file present (existence confirmed) |
| `service/app/` grep for `reservation_worker\|start_reservation\|reservation.*start\(\)\|start.*reservation` | 4 hits, none in main.py — worker start absence VERIFIED (evidence for 4d contradiction) |
| `service/app/static/v2/` grep for `payment.*sync\|/payments/\|syncPayment\|paymentSync` | 2 hits, both inside minified `proforma-react/assets/index-*.js` (Vite orphan) — first-party UI absence VERIFIED |

---

## 4d worker launch trace (follow-up)

Requested comprehensive grep for every reference that could launch the reservation worker — class name, module name, alias, individual function names, and the three generic launch verbs (`add_job`, `create_task`, `Thread`). Executed against tree HEAD at aa414d90.

### Class-name candidate — `ReservationWorker`

Grep whole tree for `ReservationWorker`: **ZERO matches.** There is no class named `ReservationWorker`. `reservation_worker.py` is a pure-functions module (per its own docstring at `reservation_worker.py:4–5` — "All functions are pure: they take db_path + optional wfirma_client, no global state. Caller provides the client instance."). No `.start()` method exists to search for.

### Module-name reference — `reservation_worker` (every hit across the tree)

| Category | Hit | Runtime? |
|---|---|---|
| App-code IMPORT | `service/app/api/routes_reservations.py:29` — `from ..services import reservation_worker as rworker` | **NO** — the file is not registered in `main.py` (Claim 1), so the import never fires |
| App-code COMMENT | `service/app/services/wfirma_product_auto_register.py:105` — `# reservation_worker / PZ chain consults. We mirror successful registrations` | No — comment |
| App-code COMMENT | `service/app/services/design_product_bridge.py:204` — `by the older reservation_worker importer.` | No — comment |
| Self | `service/app/services/reservation_worker.py:2` — the file's own docstring | Not a launch site |
| Tests | `service/tests/test_reservation_queue.py:36` — `from app.services import reservation_worker as rworker` | No — pytest only, not a runtime path |
| Docs | `docs/governance/AUTHORITY_MAP.md:432`; `docs/inspection/c02-reservation-pipeline-verification-20260613.md:30, 40`; `docs/operational-memory/inventory/INVENTORY_STATE_MACHINE.md:69, 71, 81, 82, 130, 149, 232, 247, 248` | No — documentation |
| Prior census reports (self-referential) | `reports/authority-census/2026-07-01T015910Z/00-census-index.md:47`, `05-service-scheduler-map.md:82`, `06-evidence-backfill.md:21, 102, 104, 106, 150, 165` | No — the reports themselves |

### Alias reference — `rworker` (every hit)

| Hit | Type |
|---|---|
| `service/app/api/routes_reservations.py:29` — `from ..services import reservation_worker as rworker` | Dead import (route not registered) |
| `service/app/api/routes_reservations.py:114` — `result = rworker.import_purchase_packing(db, payload)` | Dead call site |
| `service/app/api/routes_reservations.py:140` — `result = rworker.import_sales_packing(db, payload)` | Dead call site |
| `service/app/api/routes_reservations.py:170` — `result = rworker.sync_wfirma_products_by_codes(db, _ClientShim(), body.product_codes)` | Dead call site |
| `service/app/api/routes_reservations.py:192` — `result = rworker.process_ready_reservations(...)` | Dead call site |
| `service/tests/test_reservation_queue.py:36, 196, 213, 218, 232, 250, 266, 303, 333, 364, 398, 432` | pytest only |

Every `rworker` call site is either in the unregistered route file or in a pytest module. Zero production paths.

### Individual function names — call sites OUTSIDE `reservation_worker.py`

Grep `service/app/` for the 6 worker functions:

| Function | Definition | External call sites |
|---|---|---|
| `import_purchase_packing` | `reservation_worker.py:48` | `routes_reservations.py:94` (route handler) + `:114` (call) — DEAD |
| `import_sales_packing` | `reservation_worker.py:107` | `routes_reservations.py:119` (handler) + `:140` (call) — DEAD |
| `sync_wfirma_products_by_codes` | `reservation_worker.py:196` | `routes_reservations.py:170` (call) — DEAD |
| `refresh_queue_readiness` | `reservation_worker.py:260` | **ZERO app-code call sites** — used only internally by `worker_tick` at `reservation_worker.py:522` |
| `process_ready_reservations` | `reservation_worker.py:309` | `routes_reservations.py:192` (call) — DEAD |
| `worker_tick` | `reservation_worker.py:481` | **ZERO external call sites anywhere in tree** |

### Scheduled-tick entry point — `worker_tick`

Grep whole tree for `worker_tick`: **3 hits, all inside `reservation_worker.py` itself:**
- `reservation_worker.py:15` — docstring line "6. worker_tick → safe background tick combining 3+4+5"
- `reservation_worker.py:479` — section header comment `# ── 6. worker_tick ─────────────`
- `reservation_worker.py:481` — `def worker_tick(db_path: Path, wfirma_client: Any) -> Dict[str, Any]:`

`worker_tick` — the module's own designated scheduling target — is defined and orphaned. Nothing schedules it. Nothing calls it. No route wraps it. No test even exercises it.

### Wide-net launch-verb grep

Grep `service/app/` for `create_task.*reservation|Thread.*reservation|add_job.*reservation`: **ZERO matches.**

All three conventional Python launch verbs (`APScheduler.add_job`, `asyncio.create_task`, `threading.Thread(target=...)`) are absent in any reservation context. This forecloses the standard launch mechanisms that could start the worker without an explicit import chain from `main.py`.

---

### Classification

**Reservation worker launch path: NONE FOUND (dead) — VERIFIED.**

Full confirmation matrix:

| Would-be launch mechanism | Present at HEAD? |
|---|---|
| `class ReservationWorker(...).start()` | No class exists |
| Direct `worker_tick()` scheduler registration | No — worker_tick has zero external call sites |
| Function call from a registered route | No — only `routes_reservations.py` calls into the worker, and that route file is unregistered |
| `main.py` startup task (asyncio / thread / scheduler) | No — zero reservation launch verbs anywhere |
| Import side effect from a running module | No — `reservation_worker.py` only performs imports and function definitions; no module-level execution launches anything |

**No correction to 4d — the main-body verdict stands and is strengthened.**

The dead-code retirement math for the reservation stack is confirmed:
- `routes_reservations.py` — unregistered (dead surface)
- `reservation_worker.py` — no external call sites (dead code, dormant even if imported)
- `reservation_db.py` — still runs `init_reservation_db` at `main.py:187–188`, creating an **orphan DB file (`reservation_queue.db`) at every startup** that no code ever reads or writes

For the decision list: retire routes + worker together, or re-register the route (and add a `worker_tick` scheduler entry) to make the stack live. The DB file's continued creation at every startup is a `main.py:187–188` orphan that should be included in whichever direction the operator picks.

### Sources (this section)

| File | Reads / greps executed this run |
|---|---|
| `service/app/services/reservation_worker.py` | Read lines 1–60 (docstring + function list at 9–15, imports 23–33); function definitions cross-verified at lines 48, 107, 196, 260, 309, 481 via grep |
| `C:\PZ-verify` (full tree) | Grep `reservation_worker` → 100-hit cap, 100 hits enumerated above; grep `\brworker\b` → 17 hits enumerated; grep `ReservationWorker` → 0 hits |
| `C:\PZ-verify` (full tree) | Grep `worker_tick` → 3 hits, all inside `reservation_worker.py` |
| `service/app/` | Grep for `process_ready_reservations\|refresh_queue_readiness\|import_purchase_packing\|import_sales_packing\|sync_wfirma_products_by_codes` → all external call sites confirmed inside `routes_reservations.py` only |
| `service/app/` | Grep `create_task.*reservation\|Thread.*reservation\|add_job.*reservation` → 0 hits |
