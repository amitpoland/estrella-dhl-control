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

## Production deploy record (2026-07-03)

- DEPLOYED: 84c292de (deploy/wave12 = Waves 1+2 + origin/main) — operator-executed
  runbook; SYNC VERIFIED (493/0/0 + 3 named MATCH); live-root backfills complete
  (mirror 140/collisions 0; registry 2); /health 200; four-check gate 4xGREEN.
- W3-A1 -> VALID. Campaign HOLDS for the operator's separate Wave-3 ratification words.
- Paid lessons this deploy: #6 (/XO partial sync), #7 (storage-root assumption) —
  v1.1-001/-003 queued; Platform v1.0 untouched.

## Wave 3 (Entire UI) — ACTIVE (ratified 2026-07-03, verbatim directive in DECISIONS)

- Wireframe authority re-confirmed against the operator's attachment (sha256
  f7dd5e3889… IDENTICAL) — W3-A2 VALID.
- Current slice: W3-P0 — PAGE-BY-PAGE GAP CENSUS (read-only; BUILD / REMOVE /
  WFIRMA-GATED / OUT; orders the wave, Inventory first).
- Exit: CP3 recognition gate (unlabeled side-by-side composites). NO DEPLOY in-wave.

- W3-P0 census COMPLETE: 101 gaps (BUILD 67 · REMOVE 16 · WFIRMA-GATED 5 · OUT 10 ·
  QUESTION 3). Wave order: Inventory tabs 1-12 first (U-1..U-6 mapped), then
  Accounting hub, Dashboard, Shipment Detail, Proforma, Setup, Reports, rest.
  Q-1/Q-2/Q-3 posed to operator (dhl placement · automation slug owner ·
  diagnostics CLI tools) — none block pages 1-12.
- Current slice: W3-page1 — Inventory / Sample Out tab (U-1; census #1).
- W3-page1 COMPLETE (Sample Out tab, U-1): 9/9 page-gate criteria evidence-cited
  (build record reports/wave3/pages/2026-07-03-page1-sample-out.md); INV_TABS strip
  introduced; slice-only staging (operator pz-api.js WIP excluded via surgical blob).
  Next: W3-page2 — Sample Return tab.
- W3-page2 COMPLETE (Sample Return tab, U-1): 9/9 gate; Record Return now LIVE
  cross-tab; QC fields Lesson-M pending (no backend). Next: W3-page3 Client Return.
- W3-page3 COMPLETE (Client Return tab, U-2): 9/9 gate (criterion-7 cold-origin 200
  completed by orchestrator on port 8129 — agent had stated-only). PLANNED: one
  consolidated real-browser render gate (Preview) after the Inventory family,
  before page 13. Next: W3-page4 Return to Producer.
- W3-page4 COMPLETE (Return to Producer tab, U-2): 9/9 gate (criterion 7 actually
  run: uvicorn:8131 200; criterion 9 re-run by orchestrator: pin 11/11, smoke 63).
  U-1+U-2 CLOSED. Next: W3-page5 Temp Sale tab (U-3).
- W3-page5 COMPLETE (Temp Sale tab, U-3): 9/9 gate (7+9 actually run). Honest
  architecture: batch-scoped reads only (no cross-batch endpoint invented);
  View-proforma + Issue-invoice Lesson-M disabled (census IV-TS-1). Next:
  W3-page6 Overview KPI/quick-actions (U-6).
- W3-page6 COMPLETE (Overview tab, U-6): 9/9 gate incl. REAL browser verification
  (0 console errors, tab-switch + modal verified). Consignment tile WFIRMA-GATED
  honest badge; pieces-on-hand + cross-batch ledger honestly deferred (no backend).
  Legacy panels kept reachable in a collapsed details block (census OUT).
  All 6 built tabs wired. Next: W3-page7 Temp Purchase (L, C-3e merchandising read).
- W3-page7 COMPLETE (Temp Purchase tab, U-3): browser-verified 13-col
  merchandising register on C-3e; Receive opens the EXISTING MoveStockModal
  (no second implementation); Upload-packing Lesson-M (IV-TP-2). Orchestrator
  re-ran pin 11/11 + smoke 63 (agent table had drifted from the operator's 9).
  Next: W3-page8 Temp Warehouse tab.
- W3-page8 COMPLETE (Temp Warehouse tab, U-3): 9/9 gate (browser 0-errors, pin,
  smoke run by agent). DISCLOSED MODEL GAP -> Q-4: engine has a single
  WAREHOUSE_STOCK state; wireframe splits stage-1 (awaiting count) vs stage-2
  (final). Page 9 (Final Stock) BLOCKED on the Q-4 ruling (else identical rows in
  two tabs). Proposed default: location/bag-assigned = Final, unassigned = Temp.
  Next unblocked: W3-page10 Consignment gated surface (census #10).
- W3-page10 COMPLETE (Consignment WFIRMA-GATED surface, U-4): 9/9 gate; wireframe
  structure (3 sub-tabs, exact columns) with ZERO fake rows; OI-1/2/17 cited on
  banner + every disabled action; browser 0-errors. Next: W3-page11 Identity/
  Mapping; page 9 still holds on Q-4.
- W3-page11 COMPLETE (Identity/Mapping tab): 9/9 gate; SS-D honored (reuses
  WfirmaMappingPage's endpoints, nothing rebuilt); page-6 dangling quick-action
  REPAIRED (mapping tab now exists); 6/8 wireframe fields honest em-dash
  [IV-ID-1] (no backend). Next: W3-page12 MoveStock stage-transition tab —
  then the Inventory-family browser render gate + health check.
- W3-page12 COMPLETE (MoveStockModal Stage-Transition tab, census #12, scope S):
  9/9 gate; disabled tab became honest document-driven guide + exception/correction
  path per operator lifecycle rule (KNOWLEDGE.md); all 12 inventory_state_engine
  transitions listed with real triggers + endpoint names; 5 deep-link buttons
  (inv:jump CustomEvent) to dedicated tabs (Sample Out, Sample Return, Client
  Return, Return to Producer, Temp Sale); Lesson-M IV-ST-1 disclosed (wireframe
  Consignment/TempSale "Confirm move" has no backend POST route); wh→wh tab
  fully preserved; pin 11/11, smoke 63/63, 0 console errors. Build record:
  reports/wave3/pages/2026-07-04-page12-movestock-transition.md. NO COMMIT.
  Next: Inventory-family browser render gate + Wave-3 health check (page 9
  Final Stock still holds on Q-4 ruling).
- W3-page12 COMPLETE (MoveStock stage-transition tab): 9/9 gate; silently-disabled
  control -> honest document-driven-transitions guide (engine LEGAL_TRANSITIONS
  rendered w/ real triggers/endpoints; 5 deep-links; IV-ST-1 Lesson-M panel; no
  manual-transition route exists = none invented); wh->wh preserved. Inventory
  family: 10 of 11 tabs + modal DONE; page 9 holds on Q-4. Family render gate next.

## Wave-3 Inventory-family boundary (2026-07-04) — health check

- FAMILY RENDER GATE PASS: cold Preview pass, all 10 built tabs walked, ZERO
  console errors (server inventory-dev:8200).
- Inventory family: 10/11 tabs + modal COMPLETE (pages 1-8, 10-12); page 9
  (Final Stock) HOLDS on Q-4 (stage-split criterion).
- Confidence Gate re-check → Wave 4: unchanged AT-RISK (OI-1/2/3/4/7/9/10/11
  still open; no new evidence). W3 assumptions: all still VALID.
- BUDGET: ~2.0× trigger fired → SELF_ASSESSMENT entry + manifest-revision
  proposal DUE at this boundary report (operator rules; no silent scope cut).
- Next unblocked: census #13 Accounting hub (L) — awaits the operator's word on
  the budget proposal; Q-1/Q-2/Q-3/Q-4 outstanding.
- W3-page6b COMPLETE (Inventory header actions row): 9/9 gate; Upload -> real
  documents-hub navigation (dangling inv:upload REMOVED at both sites); Export ->
  context-sensitive live CSV of the active tab; Cycle count Lesson-M (IV-HDR-1).
  Census amended: 116 gaps, all source-tagged (WIREFRAME-REQUIRED w/ bundle cites
  vs OPERATOR-RULED Entry-Point). DocumentsHub delta re-audited: 13 wireframe
  controls -> 0 live (read-only observer; incl. fiscal-class Post-to-wFirma).
  CAMPAIGN HOLDS at the family boundary: budget ruling + Q-1..Q-4 awaited.

## Boundary rulings received (2026-07-04) — wave RESUMED

- R-BUDGET: Wave 3 re-budgeted 6h -> 30h, scope unchanged. R-Q4: Final Stock =
  location-assigned / Temp Warehouse = unassigned (existing authority, no new
  state). R-Q1: DHL standalone + entry-point sub-tab only. R-Q2: /automation ->
  Action Center (operator authority) -> AI Bridge (backend capability).
  R-Q3: Diagnostics tools stay, honest Disabled/Planned/Backend-Required.
- NEW criterion 10: per-page CONTROL MATRIX (Wireframe/Implemented/Gated/
  Operator-ruled/Out/Missing=0); retroactive matrices for pages 1-8,10-12,6b.
- Execution order: page 9 -> retro matrices -> Documents Hub (13 controls,
  existing authorities only, write-gates untouched, STOP on any new-write-path
  need) -> Accounting -> Shipment Detail -> Dashboard -> Proforma -> rest -> CP3.
- Current slices: W3-page9 (Final Stock) + retro-matrix pass (parallel).
- W3-page9 + matrix-repair COMPLETE (one interleaved commit): FinalStockTab per
  R-Q4 (location-assigned; TempWarehouse amended to the complementary predicate,
  provably disjoint via shared isAssigned()); Overview = wireframe 5-tile set +
  clearly-labelled non-wireframe secondary row (authority resolution: canonical
  HTML > extract; Lesson-M preserved Returns tile); rtp-btn-view-docs added.
  ALL 13 completed pages read Wireframe-Required Missing: 0.
  INVENTORY FAMILY CLOSED. Next per operator order: Documents Hub (13 controls,
  write-gate constraint).
