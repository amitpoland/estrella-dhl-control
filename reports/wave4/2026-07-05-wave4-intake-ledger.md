# Wave 4 Intake Ledger — genuine backend work discovered in Wave 3

**Date:** 2026-07-05 · **Type:** implementation ledger only — no design, no implementation, no estimates. This is the official Wave 4 intake. Every item is a genuine backend gap surfaced while porting the UI to the pinned wireframe (all rendered with honest `Backend Pending` / `Authority Gap`).

| # | Page | Workflow | Panel | Control | Authority | Existing endpoint | Missing endpoint | R/W | Financial? | Inventory? | Accounting? | wFirma? | Owner | Priority | Reuse opportunity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Accounting | Overview | KPI tiles | Sales Receivable / Sales Overdue / Supplier Payable / Last-Sync | Accounting Authority | — | `GET /accounting/summary` (aggregate) | R | Yes | No | Yes | Yes | pz-purchase-accounting | P2 | Aggregate existing invoice/ledger reads |
| 2 | Accounting | Overview | Sales/Warehouse doc-count panels | count rows (12/28/1/18 · 9/1/2/4) | Accounting Authority | — | `GET /accounting/counts` | R | No | No | Yes | Yes | pz-purchase-accounting | P3 | Count existing docs by type |
| 3 | Accounting | Document grids | Invoice / Credit Note / WZ / PW / RW / MM grids | table rows + View | Accounting Authority | — | `GET /accounting/{type}` | R | Yes | Partial (WZ/PZ/PW/RW/MM) | Yes | Yes | pz-purchase-accounting + wfirma-integration | P1 | Mirror `/dashboard/batches` (PZ) + `/proforma/search` (PI) shape |
| 4 | Accounting | Ledgers | Client Balance | table (Open/Overdue/YTD) | Accounting + Customer Master | — | `GET /ledger/clients` | R | Yes | No | Yes | Yes | finance-accounting-logic | P1 | Join customer_master + invoice/payment |
| 5 | Accounting | Ledgers | Supplier Ledger | dropdown + Debit/Credit/Balance | Accounting + Supplier Master | — | `GET /ledger/suppliers` | R | Yes | No | Yes | Yes | finance-accounting-logic | P2 | Supplier data + PZ postings |
| 6 | Accounting | Ledgers | Client Ledger | (LIVE — reused) | Accounting | LedgersPage (existing) | — | R | Yes | No | Yes | Yes | — | Done | Already wired |
| 7 | Accounting | System | wFirma Sync (inline) | Sync-all-now · Re-sync per row · mapping table | wFirma | webhook status (partial) | `POST /wfirma/sync/{type}` + `GET /wfirma/sync/status` | R+W | No | No | Yes | Yes | wfirma-integration | P2 | Existing `wfirma_client` + webhook scheduler |
| 8 | Proforma | Import | Import Packing List wizard | Create-draft (step 4) | Proforma Authority + Customer/Product Master | extraction + create paths (partial) | `POST /proforma/upload-packing-list` (DC-12) | W | Yes (creates draft) | No | No | No | sales-proforma + document-intelligence | P1 | Existing extraction + `/proforma/create` + `/import-sales-prices` |
| 9 | Proforma | List | toolbar | Print | Proforma Authority | — | `GET /proforma/{id}/print` (or reuse doc-output) | R | No | No | No | No | document-intelligence | P3 | Existing document-output / Print Preview modal |
| 10 | Proforma | List | selection toolbar | bulk Push to wFirma / Send | Proforma + wFirma / Email | per-draft `/post`, `/send-email` | bulk wrapper endpoint (or client loop) | W | Yes | No | No | Yes | sales-proforma + wfirma-integration | P3 | Loop existing per-draft confirmed flows |
| 11 | Proforma Detail | tabs | Source & Extraction | extraction data | Proforma + Customer/Product Master | draft read (partial) | `GET /proforma/draft/{id}/extraction` | R | No | No | No | No | document-intelligence | P2 | Draft `editable_lines` + extraction engine |
| 12 | Proforma Detail | tabs | Logistics | carrier/AWB/CMR/weights | Carrier + Shipment Authority | draft/shipment read (partial) | `GET /proforma/draft/{id}/logistics` | R | No | No | No | No | dhl-customs | P3 | Shipment/packing data already in the batch |
| 13 | Proforma Detail | tabs | Documents | generated PDFs list | Proforma Authority | Print Preview modal (existing) | `GET /proforma/draft/{id}/documents` | R | No | No | No | No | document-intelligence | P3 | Existing doc-generation output |

## Notes
- Items 6 (Client Ledger) is already wired (reuse) — listed for completeness, not Wave-4 work.
- Every UI for the above is already built and renders `Backend Pending` / `Authority Gap` (UI-before-backend); Wave 4 only wires execution.
- No new authority, master, or write path is proposed here — this ledger only identifies. Priority is relative (P1 = unblocks the most UI), not an estimate.
- Gating OIs (from `phase-c-master/OPEN_ITEMS.md`) still apply to the wFirma-write items (OI-1 MM API, OI-3 WZ, OI-4 get_stock, OI-7/9/10/11 webhooks).

## Item 3 split — DOCUMENTED vs UNDOCUMENTED (operator ruling 2026-07-05)

Item 3 (Accounting document grids) is split by wFirma documentation status:

- **Item 3A — DOCUMENTED — DONE.** Invoice + Credit Note grids read live via wFirma
  `invoices/find` (`invoice`→`normal`, `credit_note`→`correction`). Endpoint
  `GET /api/v1/accounting/documents/{doc_type}`; transport `wfirma_client.list_invoices_by_type`.
  No local mirror — wFirma is the authority. Commit `1094a9f9`. Golden 160/160; 4 unit + 4 route tests green.
- **Item 3B — UNDOCUMENTED — NOT IMPLEMENTED.** WZ/PW/RW/MM warehouse-document reads.
  The wFirma API reference (skill `wfirma-api-integration`, `references/warehouse-goods.md` +
  `gotchas.md`) states warehouse **documents** (PZ/WZ/RW/PW/MM) are **not** a general read/write
  API surface — WZ is emitted only as an invoice side-effect and downloaded via
  `/invoices/download?warehouse_documents=1`; only single-doc PZ get is confirmed
  (`warehouse_document_p_z/get/{id}`). No documented list/find endpoint exists for WZ/PW/RW/MM.
  The UI keeps honest `Backend Pending`; the route returns 404 for these types. → Sandbox task below.

## Item 4 — Client Balance roster — DONE (SPLIT) (2026-07-05)

`GET /api/v1/ledgers/clients` (existing **ledgers** authority — no new `/ledger`
prefix, no duplicate authority). Joins the **Customer Master** roster with
per-client balances computed by REUSING the documented **Statement authority**
(`aggregate_statement` over `invoices/find` + `payments/find`). No local mirror;
balances computed live per client and fault-isolated. Commit `4e0b58b3`.
Golden 160/160; 11 tests (4 reducer + 7 route). UI: `AccClientBalance` live roster.

Column authority split:
- **Open / Currency / State / YTD (invoiced in period) / Overdue (invoice-age)** — DOCUMENTED, done.
- **Overdue (due-date)** — BACKEND PENDING → blocked by the PHASE10A.5 payment-state
  probe (see `routes_ledgers.py` header TODO). Invoice-age figure substituted, basis
  disclosed in UI + `column_status`, never relabelled as due-date overdue.
- **Last 30d (rolling receipts)** — BACKEND PENDING → no existing authority emits a
  rolling-window receipts figure; would require a second windowed statement pass.

### Backend-Pending follow-ups recorded (Item 4)

| Ref | Gap | Authority owner | Blocker / needed | Affected UI |
|---|---|---|---|---|
| I4-BP1 | Client Balance **due-date Overdue** column | Statement authority | PHASE10A.5 probe: confirm `<paymentdate>`/`<paymentstate>` on invoice reads before due-date aging is allowed (architecture §7) | `AccClientBalance` Overdue cell (invoice-age shown, disclosed) |
| I4-BP2 | Client Balance **Last 30d** column | Statement authority | Rolling 30-day receipts aggregation — needs a second windowed `aggregate_statement` pass or a new documented aggregator; not invented here | `AccClientBalance` Last 30d cell (`—`, Backend Pending) |

## Item 8 — Import Packing List wizard — DONE (REUSE-ONLY) (2026-07-05)

Operator ruling: REUSE-ONLY — no `/proforma/upload-packing-list`, no new parser,
no new authority, no thin wrapper. The wizard is wired directly to the EXISTING
authority `POST /api/v1/packing/{batch_id}/upload` (parses file → upserts packing
lines → idempotently creates/syncs proforma drafts by `(batch_id, client_name)`;
no wFirma write; no schema change). Commit `eef901eb`. Golden 160/160; smoke 63.

- `pz-api.uploadPackingList(batchId, file)` — multipart POST, batchId verbatim.
- `PfImportWizardModal` — real file picker + upload + honest result/error;
  DC-12 Authority-Gap placeholder removed.
- **Batch discipline:** batchId flows from `ProformaListPage` (`?batch_id=`,
  guaranteed non-empty by its batch-required landing). No batch → batch-required
  state, upload blocked; cross-batch entry never auto-picks. Transport proof:
  `uploadPackingList('BATCH_ALPHA/…')` → `POST /packing/BATCH_ALPHA%2F…/upload`;
  distinct batch id → distinct URL. Reused endpoint auth = `get_current_user`
  (session) — write path is operator-authenticated server-side.

## Item 1 — Accounting Overview KPIs — SPLIT (2026-07-05)

Operator ruling: no `/accounting/summary` engine; reuse existing endpoints only.

**Item 1A — DONE.** Commit `75f096eb`. Overview KPIs wired to existing endpoints:
- **Sales Receivable** — CURRENCY-AWARE via `GET /api/v1/ledgers/clients`. Pure
  reducer `accReceivableByCurrency` sums outstanding **per currency** and NEVER
  across currencies; mixed currencies render separately, labelled "Per currency —
  not summed". Reducer unit test (`service/tests/js/test_acc_receivable_reducer.mjs`,
  `node --test`, 6/6) pins the no-cross-currency-sum rule; in-browser proof
  (USD+EUR → 2 entries, no combined total).
- **Last wFirma Sync** — reuses `GET /api/v1/analytics/phase-a`
  `wfirma_sync.last_exported_at`. No new endpoint.

**Item 1B — BACKEND PENDING (honest labels):**

| Ref | KPI | Label shown | Blocker |
|---|---|---|---|
| I1-BP1 | Sales Overdue (due-date) | "Backend Pending — due-date authority pending" | due-date aging blocked by PHASE10A.5 wFirma payment-state probe ([[I4-BP1]]); invoice-age never presented as due-date |
| I1-BP2 | Supplier Payable | "Backend Pending — supplier ledger authority pending" | no supplier-ledger / AP authority exists (Item 5 unbuilt); source = undocumented wFirma expenses/wydatki reads (SVT-class) |

## Item 7 — wFirma Sync — SPLIT: PULL-ONLY slice DONE (2026-07-05)

Operator ruling: PULL-ONLY; no generic push-capable `POST /wfirma/sync/{type}`;
all PUSH remains CP4-gated. Commit `6835c642`. Golden 160/160; smoke 63; 7/7 tests.

**Pull actions wired:**
- **Payments-pull** — NEW `POST /api/v1/wfirma/sync/payments-pull {contractor_id}`
  (only net-new trigger). READ-ONLY wFirma (`payments/find` GET) → local
  `payment_state.db` snapshot. Fixed path, no `{type}` dispatcher.
- **Customer ← wFirma** — REUSES `GET /customer-master/sync-from-wfirma/preview`
  (+ admin `apply`), not duplicated (Item 8 rule).
- **Webhook status** — REUSES `GET /webhooks/wfirma/status`.
- **Invoice read** — REUSES Item 3A `accounting/documents/{invoice|credit_note}`.

**Stock-pull guard outcome:** `get_stock` is read-only (`GET goods/find`) — PROVEN —
but `wfirma_stock_sync_processor` is a no-op stub with **no persistence target (OI-10)**.
No safe pull path to reuse → **stock-pull Backend Pending** (no no-op route shipped).

**No-push proof:** source-safety tests (no `goods/edit`, no `create_*`, no
`_http_request` POST/PUT, no `wfirma_create_*`/`_allowed`, imports only the pull
processor) + behavioural 404s for `customer-push`/`product-push`/`goods-edit`/…;
in-browser `customer-push`→404, `goods-edit`→404, `payments-pull` empty→400.

**UI:** `AccWfirmaSyncInline` = per-source PULL cards + PUSH section visible-but-
DISABLED (CP4-gated); no single unified synced indicator.

### Remaining CP4-gated PUSH (each needs separate explicit operator approval)
| Ref | Push | Write gate |
|---|---|---|
| I7-CP4-1 | Customer → wFirma | `wfirma_create_customer_allowed` |
| I7-CP4-2 | Product → wFirma (resolve / goods create) | `wfirma_create_product_allowed` |
| I7-CP4-3 | Goods edit (names/descriptions, `goods/edit`) | product-write |
| I7-CP4-4 | Invoice / Proforma create | `wfirma_create_invoice_allowed` / `wfirma_create_proforma_allowed` |
| I7-BP1 | Stock-pull | Backend Pending — no persistence target (OI-10) |

## Sandbox Verification Tasks (permanent — NO execution without explicit operator approval)

These probe UNDOCUMENTED wFirma capabilities against the sandbox company
(`test.api2.wfirma.pl`). Recording only — per operator ruling, do **not** execute
any sandbox request until the operator explicitly approves it.

### SVT-1 — WZ/PW/RW/MM warehouse-document list reads (blocks Item 3B)

| Field | Value |
|---|---|
| **Capability under test** | Read a list of WZ / PW / RW / MM warehouse documents via the wFirma API |
| **Authority owner** | wFirma (Accounting / Warehouse Authority) — no local mirror permitted |
| **Hypothesis** | wFirma exposes no general `find`/list endpoint for WZ/PW/RW/MM; they are side-effects of invoices (WZ) or internal warehouse ops (MM/PW/RW), not independently queryable |
| **Expected endpoint(s) to probe** | `warehouse_document_w_z/find`, `warehouse_document_p_w/find`, `warehouse_document_r_w/find`, `warehouse_document_m_m/find` (existence unknown); fallback `/invoices/download?warehouse_documents=1` for WZ only |
| **Expected response (if the hypothesis holds)** | `ERROR` / `ACTION NOT FOUND` / `DENIED_SCOPE_REQUESTED`, or a documented "no such module" status |
| **Success criterion** | A documented `find`/list action returns `OK` with parseable rows for at least one of WZ/PW/RW/MM → the type graduates to a documented read and can wire like Item 3A |
| **Failure criterion** | Any of: `ACTION NOT FOUND` / non-OK status / no `find` action for the module → confirms undocumented; Item 3B stays `Backend Pending`, UI unchanged |
| **Affected UI** | Accounting hub `AccDocGrid` for `wz`/`pw`/`rw`/`mm` (currently `_AccPendingTable` → Backend Pending) |
| **Affected workflow** | Accounting document review (read-only). No fiscal write — read probe only |
| **Environment** | `test.api2.wfirma.pl` sandbox company ONLY. Never production |
| **Gating OIs** | OI-1 (MM API), OI-3 (WZ add vs invoice-auto-emit) — see `phase-c-master/OPEN_ITEMS.md` |
| **Status** | RECORDED — awaiting explicit operator approval to execute |

## Item 11 — Source & Extraction tab — DONE (REUSE-ONLY) (2026-07-05)

Operator ruling: REUSE-ONLY — no new authority, DB, parser, matcher, or
duplicate service; no financial/inventory/accounting/wFirma write. The Proforma
Detail **Source & Extraction** `Backend Pending` placeholder is replaced with a
live **advisory** read. Feature commit `dd36cbf7`. Golden 160/160; smoke 63;
3 new route tests.

**New thin endpoint** `GET /api/v1/proforma/draft/{draft_id}/extraction`
(`routes_proforma.py`, `require_api_key`, read-only) — a composition over
EXISTING authorities, joined by `product_code` within the draft's `batch_id`:

- **Proforma draft** — `_draft_to_full(d).editable_lines` (the authority record).
- **Customer Master** — `_resolve_customer` + `_enrich_customer_resolution_with_email`
  (the SAME block the draft GET returns; local `wfirma_customers` mirror only).
- **Product Master** — `reservation_db.list_product_masters` (product_code → matched).
- **Import/Packing** — `packing_db.get_packing_lines_for_batch` (`extracted_confidence`,
  `requires_manual_review`) + `get_packing_documents_for_batch` (source docs).

**Advisory (Lesson N):** the payload is `advisory:true` and carries no
`blocking_reasons`/`blockers` — nothing here gates Approve/Post/Convert. Every
downstream read is wrapped; a partial batch degrades to advisory nulls and the
endpoint never 500s (404 only when the draft id is absent).

- Frontend `SourceExtractionTab` (`proforma-detail.jsx`) fetches via the existing
  `EstrellaShared.apiFetch` pattern (same as `disclose-post`); **`pz-api.js` untouched.**
  Renders packing-list source, per-row confidence, Customer/Product Master match,
  and an `N unmatched` advisory badge. `data-testid` on panel + rows.
- **Live proof** (verify server, real draft #1 / `BATCH_PR3B`): tab click →
  `GET …/draft/1/extraction → 200` → 4 source docs (basenames, no path leak) +
  11 rows + `Unmatched — needs operator mapping`; console clean; 404 on a
  nonexistent draft; confidence surfaced on draft #2; nulls (no 500) on drafts
  with no packing data.

### Working-tree note (not Item 11 scope)

An unrelated uncommitted deletion of `pz-api.uploadPackingList` sat in the tree
(`service/app/static/v2/pz-api.js`, −21 lines) — it would regress shipped Item 8
(`eef901eb`). It was **excluded** from this commit and left untouched for the
operator to reconcile; Item 11 deliberately routes around `pz-api.js`.

> Follow-up (2026-07-05): re-investigated — HEAD held `uploadPackingList`
> **twice** (duplicate object key at lines 152 & 173); the operator's WIP deletes
> the duplicate and keeps the canonical helper at 152 (→ `POST
> /api/v1/packing/{batch_id}/upload`, still called by the Import wizard). It is a
> legitimate dedup, **not** an Item 8 regression. No restoration required; the
> file remains operator WIP. Investigation closed — do not revisit.

## Item 12 — Logistics tab — DONE (REUSE-ONLY, UI-only) (2026-07-05)

Operator ruling: REUSE-ONLY — no new authority, DB, endpoint, service, or write
path; no shipment mutation; no wFirma write. The Proforma Detail **Logistics**
`Backend Pending` placeholder is replaced with a live **advisory** read view
composed ENTIRELY from data `ProformaDetailPage` already computes. **No new
fetch, no new endpoint, `pz-api.js` untouched.** Frontend commit — see SHA below.

**Authority analysis (§17/§20):** authority owner = **CMR document authority**
(`cmrPreviewData`) + the draft's billed `editable_lines` + matched batch
**packing** rows (net/gross-weight enrichment). Existing page = Proforma Detail
`logistics` tab. No arrow requires a new authority.

Reused, in-component (all already consumed by the rendering CMR preview modal):
- **Carrier / route / CMR no. / pieces** — `cmrPreviewData.carrier` (name,
  service, incoterm, origin→destination) + `cmrPreviewData.cmr_no`
  (`CMR-EJ-{batchId}`) + `_cmrTotalPcs`.
- **Net weight by item type + total** — `_cmrAggPackingLines` (aggregated ONLY
  from this draft's billed lines; batch packing rows enrich, never add lines).
- **Gross weight total** — summed via the same `_enrichPacking(ln).gross_weight`
  used for the Packing List / CMR.
- **Goods summary** — `cmrPreviewData.goods_summary`.

**Advisory (Lesson N):** header states "never a fiscal gate"; nothing here gates
Approve/Post/Convert; empty/missing packing degrades to `—` and an empty-state,
never an error.

**Honest Backend-Pending (surfaced, not fabricated):** live **AWB tracking
number** and the **per-shipment box / package profile** are NOT shown — the real
AWB is held in the secure label store (`carrier_shipments` intentionally omits
`tracking_ref`; `shipment_db.py:7`), and box selection is captured at
label-generation time only. The tab points the operator to the toolbar AWB
generator. (`GET /api/v1/carrier/{batch_id}/shipment` exists but returns only
state/mode/service and 404s for un-shipped drafts — not wired, to keep this slice
zero-fetch.)

- `data-testid`: `pf-detail-logistics`, `pf-logistics-carrier[-name]`,
  `pf-logistics-service|incoterm|route|cmr-no|pieces`, `pf-logistics-weights`
  (+ `-row`, `-total`, `-empty`), `pf-logistics-gross-total`,
  `pf-logistics-goods-summary`, `pf-logistics-pending`.
- **Verification:** exact file transforms clean under `@babel/preset-react`
  (matches the pinned 7.26.4 in-browser standalone); served 200 by the verify
  server with all 14 test IDs present; every referenced identifier proven
  in-scope (already consumed by the CMR preview modal). Structural pins green
  (`test_v2_no_spread_rest`, `test_v2_design_baseline`,
  `test_sprint36_proforma_detail_authority` — 183 passed). Golden/smoke
  unaffected (frontend-only; no engine/route/calc change). Pre-existing unrelated
  red: `test_toolbar_authority_map::test_print_uses_window_open` (`window.open`
  absent at HEAD too — not introduced by this slice). Full click-through blocked
  in the verify clone by session login + no seeded draft; not fabricated.

## Item 13 — Documents tab — DONE (REUSE-ONLY, UI-only) (2026-07-05)

Operator ruling: REUSE-ONLY / read-only — no new authority, DB, endpoint,
service, fetch, or write path; no wFirma write; no duplicate document authority;
existing Print/Download flows preserved (reused, not replaced). The Proforma
Detail **Documents** `Backend Pending` placeholder is replaced with a real
read-only **document manifest** — each row shows the document's true authority
and the EXISTING action to view/download it. **`pz-api.js` untouched.**

**Authority analysis (§17/§20):** no single new authority — the tab is a manifest
over the documents this draft already produces, each owned by its existing
authority. Existing page = Proforma Detail `documents` tab.

Per-document reuse (all state/handlers already in `ProformaDetailPage` scope,
already driven by the toolbar / preview modal that render in production):
- **Proforma PDF** — authority `GET /api/v1/proforma/{batch}/{cn}/document.pdf`
  (`routes_proforma.py:2862`). Available iff `canPrint` (`wfirma_proforma_id`);
  action reuses the existing `handleDownloadPdf` (same URL, same error banner).
  Not posted → advisory reason.
- **CMR** — frontend CMR renderer (`cmrPreviewData`); action reuses the existing
  Print Preview modal via `setPreviewDocType('cmr')` + `setShowPreview(true)`.
- **Packing List** — frontend packing renderer (`packingListData`); same Preview
  modal via `setPreviewDocType('packing')`.
- **Invoice PDF** — wFirma (external). `alreadyConverted` (`wfirma_invoice_id`)
  surfaces the invoice number; **Backend Pending** to download (served by wFirma;
  no app invoice-PDF endpoint). Not converted → "after Convert to Invoice".

**Backend Pending (surfaced, not fabricated):** invoice-PDF download (wFirma-served,
no app endpoint); the toolbar's bundle **Generate Documents** remains the known
write gap `POST /api/v1/proforma/draft/{id}/generate-documents`
(`BACKEND_GAP_REGISTER §2`, LOW) — out of scope (write).

- `data-testid`: `pf-detail-documents`, `pf-doc-row-{proforma|cmr|packing|invoice}`,
  `pf-doc-proforma-download`, `pf-doc-cmr-preview`, `pf-doc-packing-preview`,
  `pf-doc-pending-{key}`, `pf-doc-unavailable-{key}`.
- **Verification:** exact file transforms clean under `@babel/preset-react`
  (matches pinned 7.26.4 standalone); served 200 with all new test IDs; every
  referenced identifier proven in-scope (`canPrint`, `handleDownloadPdf`,
  `setShowPreview`, `setPreviewDocType`, `alreadyConverted`, `cmrPreviewData`).
  Structural pins green (`test_v2_no_spread_rest`, `test_v2_design_baseline`,
  `test_sprint36_proforma_detail_authority` — 128 passed). Golden/smoke
  unaffected (frontend-only). Full click-through blocked in the verify clone by
  session login + no seeded draft; not fabricated. Commit SHA below.

## Item 2 — Accounting Overview doc-count panels — DONE (REUSE-ONLY, read-only) (2026-07-05)

Operator ruling: REUSE-ONLY / read-only — no new authority, endpoint, aggregate
engine, cache, mirror, or cross-currency sum; no wFirma write. The Accounting
**Overview** Sales-documents + Warehouse-documents count panels now show a LIVE
count **only where one is provable from an existing endpoint**; every other row
stays honestly Backend Pending with a precise per-row reason. **`pz-api.js`
untouched** (reuses existing wrappers). Frontend commit — see SHA below.

**Endpoint-semantics analysis (why only one count is wired):**
- **Proforma issued** → `GET /api/v1/proforma/search` (`searchProformaDrafts`,
  `page_size:1`) → `data.total`. `search_drafts` computes `total = SELECT
  COUNT(*) FROM proforma_drafts {where}` — a **true unbounded count**
  (`proforma_invoice_link_db.py:1775`). Authority = `proforma_drafts`. **WIRED**
  (live proof: verify server returns `total=6`). Source disclosed in the row
  `title` ("proforma_drafts, all states").
- **Invoices issued / Credit notes** → `GET /api/v1/accounting/documents/{type}`
  returns `count = len(rows)` for ONE page (`wfirma_client.list_invoices_by_type`
  → `{"rows", "count": len(rows)}`, `wfirma_client.py:2419`); wFirma
  `invoices/find` gives a page, **not a grand total**. A true count is not
  provable read-only → **Backend Pending** (reason surfaced).
- **PZ (external receipt)** → no warehouse-document total authority. The only
  existing read (`dashboard/batches`) is a capped import pipeline proxy
  (`_MAX_LIST=300`, deduped, `pz_status` derived from `wfirma_pz_doc_id`), **not**
  the wFirma PZ-document count → **Backend Pending** (reason surfaced).
- **WZ / PW / RW / MM** → Item 3B — undocumented wFirma warehouse-doc reads →
  **Backend Pending**.

**Layout preserved:** same wireframe rows, same jump-to-tab buttons
(`acc-ov-jump-{to}`). New per-row value cell `acc-ov-count-{to}` shows the live
number (bold) or `— ›` with a `title` reason. Panel-level "· Backend Pending"
chip now shows only when EVERY row in that panel is still pending (Warehouse
panel = all pending → chip stays; Sales panel = has one live count → chip drops).

**Verification:** exact file transforms clean under `@babel/preset-react`
(matches pinned 7.26.4 standalone); served 200 with the new `acc-ov-count-*` test
IDs; reused endpoint returns a real `total` at the API layer (reuses the same
`res.ok`/`res.data.*` pattern already driving the Overview KPI tiles). Structural
+ contract pins green (`test_v2_no_spread_rest`, `test_v2_design_baseline`,
`test_accounting_hub_v2_contract` [other assertions], `test_routes_accounting` —
85 passed). Golden/smoke unaffected (frontend-only). Pre-existing unrelated reds
(reproduced at HEAD with this change stashed): `test_no_forbidden_endpoints_in_hub`
(the `/api/v1/accounting/{type}` note string predates this slice) and
`test_pipeline_summary_panel_preserved` (asserts against an HTML shell, not this
file). Full click-through blocked in the verify clone by session login; not
fabricated. Commit SHA below.

## Item 9 — Proforma Print (list toolbar) — DONE (REUSE-ONLY, read-only) (2026-07-05)

Operator ruling: REUSE-ONLY / read-only — no new print engine, no duplicate PDF
route, no wFirma write, no invoice creation, no bulk print. The Proforma **list**
toolbar Print button (`pf-tb-print`) was disabled with a stale "no print
endpoint" reason; it now routes a **single selected draft** to the EXISTING
draft-detail Print/Preview/Download flow via `onDrill(selRow)` — the identical
pattern the list's Push/Send buttons already use. **`pz-api.js` untouched.**

**Authority analysis (§17/§20):** the print authority already exists in
`proforma-detail.jsx` — `handleDownloadPdf` → `GET /api/v1/proforma/{batch}/{cn}/
document.pdf` (`routes_proforma.py:2862`) for a posted proforma, plus the
client-rendered Print Preview modal (`setPreviewDocType` + `setShowPreview`) for
any draft. The list Print does NOT introduce a second print path; it navigates to
that existing detail flow (which honestly gates Download-PDF on
`wfirma_proforma_id` and always offers Preview — see Item 13). No new endpoint,
document authority, or wFirma download dependency.

- **Single selection** → button enabled, `onDrill(selRow)` opens the draft detail
  where the operator Prints / Previews / Downloads (existing flow). Title:
  "Open the selected draft to Print / Preview / Download its PDF (existing detail
  flow)".
- **Multi-select** → disabled, "Bulk print needs existing bulk authority (none
  yet)" — Backend Pending (no bulk print authority exists; mirrors Push/Send bulk
  gating).
- **Zero selection** → disabled, "Select exactly one draft to print".
- Button stays visible per wireframe; selection count preserved in the label.

**Verification:** exact file transforms clean under `@babel/preset-react`; served
200 with `disabled={!selRow}` + `onDrill(selRow)` + the new honest title; stale
"no print endpoint" string gone. Proforma-list + V2 structural pins green
(`test_proforma_drilldown_contract`, `test_proforma_search_ui`,
`test_v2_proforma_list_retry_btn`, `test_atlas_v2_sprint1`, `test_v2_no_spread_rest`,
`test_v2_design_baseline` — 170 passed). `test_toolbar_authority_map` (detail
Print) unaffected — it reads `proforma-detail.jsx`, not the list. Golden/smoke
unaffected (frontend-only). One environmental setup error
(`test_v2_prod_unauth_redirects_to_login` — prod-mode fixture needs `API_KEY`
env; unrelated). Full click-through blocked in the verify clone by session login;
not fabricated. Commit SHA below.

## Item 10 — Proforma bulk Push / bulk Send — AUTHORITY ANALYSIS ONLY (STOP) (2026-07-05)

Analysis only — no code, no endpoint, no bulk wire, no DB change. This is a
protected financial-write surface.

**Classification: B** — a bulk surface would be a NEW endpoint over the EXISTING
single-draft write authority; operator approval required. (Not C: the
financial-write engine already exists. Not A: no bulk authority exists. Not D:
wFirma writes are documented and already used per-draft.)

**Authority map:** list toolbar `pf-tb-push` / `pf-tb-send` → (single select)
`onDrill(selRow)` → detail confirmed per-draft flow →
`POST /api/v1/proforma/draft/{id}/post` (`routes_proforma.py:8238`) +
`POST /api/v1/proforma/draft/{id}/send-email` (`:6688`) → wFirma proforma create /
SMTP queue.

**Existing single-draft authority (both heavily guarded):**
- Post: settings gate `wfirma_create_proforma_allowed` (default False, CP4);
  `confirm_token=YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA`; `expected_updated_at`
  optimistic lock; `X-Operator`; forced readiness revalidation at post-time;
  zero-price + hs_code + live receiver preflight; state machine
  approved→posting→posted/post_failed; already-posted → 409.
- Send: `confirm_token`; terminal-state guard; requires `wfirma_proforma_id`
  (must be posted first); recipient resolve; CRLF sanitisation; durable queue
  before SMTP (Lesson E); duplicate-pending → 409.

**Bulk authority exists:** NO — no bulk endpoint; `start_post` /
`send_proforma_email` are strictly per-draft; `searchProformaDrafts` is read-only.

**Idempotency verdict:** per-draft SAFE (post: `expected_updated_at`→409
DraftConflict + already-posted `wfirma_proforma_id`→409; send:
`queue_email._find_pending_duplicate`→409). Bulk-level: NO batch idempotency key
— a bulk trigger has no dedupe of its own.

**Partial-failure verdict:** UNDEFINED — a loop yields mixed outcomes
(posted / 400 blocked / 409 conflict / post_failed) with no aggregated contract;
fabricated-batch-success risk if the UI claims success while some drafts failed.

**Status-guard verdict:** STRONG per-draft (approved-state + forced revalidation +
already-posted 409 for post; posted + non-terminal + PDF + recipient for send) —
prevents re-push/re-send per draft, but only within a single call.

**Risk level:** HIGH — protected financial-write surface; a bulk auto-confirm
would bypass the per-draft explicit confirm-token guard; partial-failure + bulk
idempotency are undesigned.

**Approval required:** YES.

**Recommendation:** Keep bulk Push/Send buttons VISIBLE but disabled on
multi-select with the existing honest Authority-Gap reason (current React already
complies — `proforma-list.jsx` disables both on `selRows.length > 1` with "Bulk
push/send needs operator approval (new financial write)"; single-select routes to
the confirmed per-draft flow, Item 9). Do NOT build a client-side loop or a bulk
endpoint without operator approval AND a design that (a) preserves per-draft
confirmation, (b) defines partial-failure/aggregation semantics, (c) adds a bulk
idempotency key, (d) respects the CP4 `wfirma_create_proforma_allowed` gate.
Disposition (GATE 4): SCHEDULED — pending operator approval. **STOP for
implementation.** No React change made (current gating already correct).

## Wave 4 CLOSEOUT & DECISION LEDGER (2026-07-05)

Every Wave 4 intake item is now in exactly one terminal state. No safe,
documented, read-only implementation item remains — all remaining work is blocked
on an operator decision, a new authority, an undocumented-wFirma sandbox probe, or
a CP4 fiscal-write gate. Each remaining UI is already visible with honest
`Backend Pending` / `Authority Gap`.

### 1. DONE (safe reuse shipped)
| Item | What | Commit |
|---|---|---|
| 1A | Overview KPIs: Sales Receivable (per-currency) + Last wFirma Sync | `75f096eb` |
| 2  | Overview doc-count panels: Proforma count wired; rest honest pending | `ca30ed55` |
| 3A | Invoice + Credit Note grids (wFirma `invoices/find`) | `1094a9f9` |
| 4  | Client Balance roster (Open/YTD/Overdue-age) | `4e0b58b3` |
| 6  | Client Ledger — already reused (not Wave-4 work) | — |
| 7  | wFirma Sync PULL-ONLY slice (payments-pull + per-source cards) | `6835c642` |
| 8  | Import Packing List wizard (reuse `packing/{batch}/upload`) | `eef901eb` |
| 9  | Proforma list Print → existing detail flow | `4bd1dbe4` |
| 11 | Proforma Detail → Source & Extraction | `dd36cbf7` |
| 12 | Proforma Detail → Logistics | `8f708047` |
| 13 | Proforma Detail → Documents | `17ac9299` |

### 2. STOP-gated (each keeps its UI visible + honest reason; no code)
| Item / Ref | Control | State | Reason |
|---|---|---|---|
| **10** | bulk Push / Send | **STOP — operator approval required** | Class B: new bulk endpoint over existing per-draft write; partial-failure + bulk idempotency undesigned; would bypass per-draft confirm-token. GATE 4 SCHEDULED. |
| **5** | Supplier Ledger + Supplier Payable KPI (I1-BP2) | **STOP — new authority required** | No Supplier Master / AP authority exists; source (wFirma `expenses`/`wydatki`) is undocumented → also SVT-class. |
| **3B** | WZ / PW / RW / MM grids | **STOP — undocumented wFirma / sandbox required** | No documented list/find for warehouse docs; SVT-1 RECORDED, awaiting operator approval to probe sandbox. |
| I1-BP1 / I4-BP1 | Sales Overdue (due-date) + Client Balance due-date Overdue | **STOP — undocumented wFirma / sandbox required** | Blocked by PHASE10A.5 payment-state probe (`<paymentdate>`/`<paymentstate>`); invoice-age shown + disclosed, never relabelled. |
| I4-BP2 | Client Balance Last 30d | **Backend Pending already rendered** | No authority emits a rolling-window receipts figure; would need a new windowed aggregator — not invented. |
| I7-BP1 | Stock-pull | **Backend Pending already rendered** | `get_stock` is read-only but the sync processor has no persistence target (OI-10). |
| **CP4** I7-CP4-1..4 | Customer / Product / Goods-edit / Invoice·Proforma push | **CP4 — fiscal write gated** | Each behind its `wfirma_create_*_allowed` flag; separate explicit operator approval each. |

### 3. Operator decisions required
1. **Item 10** — approve (or decline) a bulk Push/Send orchestration endpoint (with the 4 design conditions), or leave disabled.
2. **Item 3B / SVT-1** — approve the sandbox probe of WZ/PW/RW/MM `find` on `test.api2.wfirma.pl`.
3. **Item 5** — approve creating a Supplier Master / AP authority (+ SVT-2 probe of wFirma `expenses`/`wydatki`) or defer.
4. **Due-date aging (I1-BP1/I4-BP1)** — approve the PHASE10A.5 payment-state field probe.
5. **CP4 pushes (I7-CP4-1..4)** — approve per-flag as needed.

### 4. Recommended next operator action
Approve **SVT-1 (Item 3B warehouse-doc probe)** first — it is a read-only sandbox
probe (lowest risk) that either unblocks four grids like Item 3A or permanently
confirms them as Authority Gap. Defer the financial-write decisions (10, 5, CP4)
until the read surface is fully closed.

### 5. Is Wave 4 safe implementation complete?
**YES.** All safe, documented, read-only reuse is shipped (items 1A, 2, 3A, 4, 7,
8, 9, 11, 12, 13). Verified at closeout: no remaining safe read-only item; no
hidden/removed wireframe control (every gated control stays visible with a
reason); no fabricated data (counts/logistics/documents show `—`/Backend Pending
where unproven); no duplicate authority; no accidental CP4 write path (all pushes
flag-gated, pull-only slice proven no-push); operator `pz-api.js` duplicate-removal
WIP remains untouched (` M`, unstaged). Everything left is a governance decision,
not an engineering gap.
