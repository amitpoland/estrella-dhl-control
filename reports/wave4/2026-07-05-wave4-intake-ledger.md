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
