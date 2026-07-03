# Phase-C Inventory Master — Runtime State (RUNTIME.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

**Updated:** 2026-07-03 (platform creation) · updated at EVERY slice boundary
**Branch:** `deploy/latest`

## Current State

- **Phase:** Wave 2 — Backend (ZERO UI) — **RATIFIED 2026-07-03** ("RATIFIED. Wave 2
  begins.", four amendments — DECISIONS.md Wave-2 entry)
- **Current slice:** C-3g (dual-write cleanup + cache-passthrough retirement; pin → true 0)
- **Slice order:** C-3g → R2-census → R3-test-health (first commit = storage-leak fix)
  → C-3a (verify tree only) → C-3b → C-3c → C-3d → C-3e → C-3f · C-4a only if OI-17 answers
- **Blocked by:** C-4a gated on OI-17 (OPEN — non-fatal, wave completes without it)
- **C-3g COMPLETE** `568c05b2` — pin TRUE 0; equivalence gates green (pin 11/11,
  registry 33/33, targeted 291, golden 160/160, smoke 63); baseline-diffed full
  sweep: 7 pre-existing fixed, 0 introduced. C-1f NameError defect (mapped
  service charges) found + fixed in-slice. Deploy note = c3g-deploy-note.md (CP4).
- **R2-census COMPLETE** — INSPECTOR verdicts: 3 SYNC-LAYER whitelisted w/
  citations (global_pz_push, wfirma_reservation, wfirma_reservation_create),
  3 DEV-TOOL exempt-by-purpose (build_pz_batch, send_wfirma_good/proforma
  _live_test); ZERO business logic → no migrate slice. DECISIONS.md entry.
- **R3-test-health COMPLETE** — storage-leak fix `2f44ffba` (first commit);
  capabilities 2× (subset pin + explicit flag-off patch); audit_proforma_converted
  3× (commercial-basis seeding for the SINGLE READINESS AUTHORITY convert gate);
  shipment-detail 2× (prune budget → growth ratchet; breach filed B-018);
  pr2c2 storage isolation. Side worktrees: eager-diffie + musing-volhard removed
  (musing husk dir handle-locked, git metadata pruned); eager-swirles kept
  (2 dirty entries, foreign uncommitted work); intelligent-wilson removed at
  session end.
- **C-3a COMPLETE** — returns_events migration applied to the VERIFY TREE
  (table + 3 indexes; ensure_returns_schema()=True). sample_out_events draft
  applied too (same verify-tree-only class; C-3b local verification needs it).
  PROD apply remains CP4/deploy operator ritual (both drafts idempotent).
- **C-3b + C-3c COMPLETE** — GET /api/v1/inventory/samples (paired out/return
  register, status open|returned, recipient filter) + GET /api/v1/inventory/returns
  (direction register; to_producer open→resolved via linked producer_restock).
  Read-only, on the EXISTING routers (§20 chain: Inventory V2 → wireframe stub
  tabs → warehouse_db → warehouse.db → existing routers); 503 MIGRATION_PENDING
  gates preserved. Suite test_c3b_c3c_inventory_read_endpoints 9/9; adjacent
  writer/piece-view/pin suites 92 green.
- **C-3d COMPLETE** — services/stock_issue.py run_stock_issue() (ONE shared
  function, BE-1 idiom): billed pieces WAREHOUSE_STOCK → SALES_TRANSIT on
  proforma→invoice conversion (trigger invoice_issued, previously unreachable);
  idempotent replay, shortfall advisory (Lesson N — never blocks the invoice),
  never-raise, summary mirror EV_INVENTORY_SALES_TRANSIT_ISSUED. Piece
  selection = deterministic scan_code order per billed product_code (documented
  default — piece↔line binding is preview-time-only). Suite
  test_stock_issue_c3d 12/12; adjacent convert/promotion suites green
  (dashboard two-step-convert HTML assertion failure is pre-existing, both
  sweeps); pin 11/11; smoke 63.
- **C-3e COMPLETE** — GET /api/v1/inventory/merchandising/{batch_id}:
  packing_lines ⋈ inventory_state per piece with the DELIVERABLE-2 columns
  (pack_sr/ctg/client_po/design/karat/color/quality/dia_wt/qty); client_po =
  best-effort sales-side advisory. Read-only; UI = Wave 3 / U-3.
- **C-3f COMPLETE** — GET /api/v1/inventory/movements/{batch_id}: engine
  lifecycle trail (new read-only ise.list_events_for_batch) newest-first +
  document-trail pointers (promotion notes count/endpoint, samples/returns
  registers). Suite test_c3e_c3f 6/6; adjacent suites 66 green.
- **C-4a SKIPPED per ratification** — OI-17 (consignment model) still OPEN;
  "the wave completes without it otherwise."
- **WAVE 2 (Backend) slice work COMPLETE** — boundary CP2 + Confidence Gate
  check done; Wave 3 requires operator ratification (CAMPAIGN_OS §5a).
- **WAVE ORDER LOCKED (operator verdict 2026-07-03, verbatim R4):** "Wave 3
  begins only after: (1) Production deploy (2) Post-deploy verification
  (3) Mirror collision report clean (4) Wave 3 ratification. This order will
  not change." Deploy runbook (single, 5-section, operator-executed):
  reports/deploy/2026-07-03-wave12-operator-runbook.md. Campaign HOLDS at
  CP4/CP5 until the operator reports deploy done + verification green +
  collision report clean; ratification is a separate step after that.

## Completed Slices (append-only ledger)

Pre-launch (recorded at platform creation from git log + PROJECT_STATE):

| Date | Slice | Commit |
|---|---|---|
| 2026-07-03 | C-1a Product Master schema + wfirma_product_mirror + backfill | `6c2fde43` |
| 2026-07-03 | C-1b product write paths through the Master (V1+V6) | `1664e5de` |
| 2026-07-03 | C-1b.1 reservations router registration (GATE-4 finding) | `88b4816c` |
| 2026-07-03 | C-1c stage-0 consumption pin (REAL access + honest baseline) | `e7927f4c` |
| 2026-07-03 | C-1c-1a dashboard proforma-readiness count via Master | `eafc5504` |
| 2026-07-03 | C-1c-1b packing lane-readiness via Master | `d284f9ab` |
| 2026-07-03 | C-1c-1c capabilities diagnostic reads via sync layer | `feeb1fbe` |
| 2026-07-03 | C-1w1 proforma service-product registration mirror-complete | `2c30b972` |
| 2026-07-02 | B1 KPI tiles restyle (InvStatTile) | `a1708338` |
| 2026-07-02 | B2 Promotion Notes panel + B3 real client_po | `0602ddd3` |
| 2026-07-02 | V2-wide spread-rest collision sweep | `98628d92` |
| 2026-07-02 | Move Location fold → Inventory Move Stock modal (Lesson M) | `0cee8173` |

Campaign slices:

| Date | Slice | Commit |
|---|---|---|
| 2026-07-03 | Platform launch (docs-only; 8 documents + PROJECT_STATE ruling) | `575bb3f3` |
| 2026-07-03 | Phase 0 evidence pass (registers populated; W1/W2 VALID) | `be0783c8` |
| 2026-07-03 | C-1w2 capabilities write path + inseparable reads → sync layer; pin 3→2; golden 160/160; capabilities 69+2 pre-existing | `3833627c` |
| 2026-07-03 | C-2a wfirma_customer_mirror schema (contractor_id PK) + collision-safe upsert + idempotent 2-source backfill; pin 9/9; golden 160/160 | `18fb89ad` |
| 2026-07-03 | C-2b V4/V5/V7 customer call-path reroute → Customer Master passthroughs; pin 10/10; smoke 63; golden 160/160 | `60a34f9e` |
| 2026-07-03 | C-2c customer verification sweep — full-app pin (zero business violations); pin 11/11; C-2 COMPLETE | `0d0bf78d` |
| 2026-07-03 | Operator verdict recorded (6 rulings + stop-line); waves restored; platform doc #9 | `a4231850` |
| 2026-07-03 | C-1e routes_wfirma 5 reads + 3 mirror-first dual-writes → sync layer; pin 2→1; resolve suite 10/10 (7 stale patch targets repaired); smoke 63; golden green | `7c4f6f0b` |
| 2026-07-03 | Mirror Completeness Proof (ratified check): census of ALL product writers; 3 gaps found + FIXED; verdict COMPLETE | `37aaaf27` |
| 2026-07-03 | C-1f — 12 proforma fiscal reads → mirror-first w/ logged fallback; output-equivalence gate PASS | `6a781ee4` |
| 2026-07-03 | C-1d verification audit — 8/8 success criteria; residuals declared; WAVE 1 COMPLETE | see git log `docs(c1d-…)` |

## Budget Tracking (live; boundary snapshots go to MASTER_MANIFEST §4)

| Wave | Consumed | Budget | Forecast |
|---|---|---|---|
| Wave 1 | ~4h — COMPLETE (C-1w2, C-2a/b/c, C-1e, MC-proof, C-1f, C-1d) | 8h | closed at 50% of budget |
| Wave 2 | 0h | 11h | — |
| Wave 3 | 0h | 6h | — |
| Wave 4 | 0h | 5h | — |

## Architecture Confidence (mirror of MASTER_MANIFEST §3 states)

- Wave 1: COMPLETE
- Wave 2: COMPLETE (slice work; prod deploy of the wave = operator ritual)
- Wave 3: NO INVALIDATED assumptions at the Wave-2 boundary. W3-A1 AT-RISK
  (deploy-gated: backend reads code-complete, prod deploy pending — must be
  live before UI slices close); W3-A2 VALID (git-blob re-hash MATCH; hash
  the blob, not the CRLF checkout); W3-A3/A4 VALID; W3-A5 tracks OI-17
  (C-4a deferred → U-4 defers, Lesson M planned-state honesty).
- Wave 4: AT-RISK (W4-A1 OI-7/9/10/11 open; OI-1/OI-3 open)

## Open OI Blockers (abbreviated — full ledger in OPEN_ITEMS.md)

- OI-1 MM-via-API — gates C-4b (fallback exists), C-7a
- OI-CONSIGNMENT-MODEL — gates C-4a (Wave 3)
- OI-13 contractor_id stability — C-2a shipped with contractor_id PK; formal confirmation still open
- OI-18 C-1e ruling — ANSWERED 2026-07-03 (Option (a)); Wave-1 remainder unblocked
- OI-3 WZ add-vs-auto — gates C-6a, C-8c
- OI-7/9/10/11 webhook config — gate Wave 4
