# Phase-C Inventory Master — Campaign Manifest (MASTER_MANIFEST.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

**Campaign:** EJ Dashboard Phase-C Inventory Master Campaign
**Version:** 1.0 · **Created:** 2026-07-03 · **Launch ruling:** §5 (verbatim)
**Parent program:** `.claude/campaigns/ej-dashboard-master.md`
**Constitution:** R4 verbatim — CLAUDE.md §"EJ Dashboard Phase-C Constitution (Final)"
**Branch:** `deploy/latest` · **Docs location:** `.claude/campaigns/phase-c-master/`

---

## §1 Campaign Identity

Scope = Constitution §16 locked order, steps 1–10:
Product Master → Customer Master → Reservation → Inventory → Sample → Consignment →
Returns → Invoice Selection → MM Integration → Webhook Synchronization.
Step 1 (Product) = C-1a..C-1d (advisor reconciliation, CLAUDE.md); step 2 (Customer) = C-2;
MM = step 9; Webhook Sync = step 10.

Already complete before launch (evidence: git log `deploy/latest` + PROJECT_STATE DECISIONS):
C-1a `6c2fde43` · C-1b `1664e5de` · C-1b.1 `88b4816c` · C-1c stage-0 `e7927f4c` ·
C-1c-1a `eafc5504` · C-1c-1b `d284f9ab` · C-1c-1c `feeb1fbe` · C-1w1 `2c30b972` ·
B1 KPI tiles `a1708338` · B2+B3 `0602ddd3` · spread-rest sweep `98628d92` ·
Move-Location fold `0cee8173`.

## §2 Wave Map

| Wave | Name | Scope (slices) | Budget | Status |
|---|---|---|---|---|
| Phase 0 | Research + validation | Registers populated; OI evidence pass; KNOWLEDGE.md | — | **COMPLETE 2026-07-03** |
| **Wave 1** | **Authority** | C-1w2 · C-1e · C-1f · C-1d · C-2a · C-2b · C-2c | 8h | **ACTIVE** |
| **Wave 2** | **Backend** (ZERO UI) | C-3g · R2-census · R3-test-health · C-3a · C-3b · C-3c · C-3d · C-3e · C-3f · C-4a (OI-gated) | 11h | **ACTIVE — RATIFIED 2026-07-03** (four amendments, see §6 + DECISIONS.md) |
| **Wave 3** | **Entire UI** (built once, CP3) | census → page-by-page (U-1..U-6 mapped onto the census order) | 6h | **ACTIVE — RATIFIED 2026-07-03** ("WAVE 3 BEGINS" + verbatim directive, DECISIONS) |
| **Wave 4** | **Synchronization** | C-4b · C-4d · C-5a · C-6a · C-7a · C-8a/b/c · C-9a | 5h | RESTORED 2026-07-03 — awaiting ratification |

**WAVE STRUCTURE RESTORED (operator ruling, verbatim, 2026-07-03):** "Wave 1
Authority · Wave 2 Backend · Wave 3 Entire UI · Wave 4 Synchronization. UI is
never merged into backend. Backend complete first. UI exactly once."

### Wave 1 — Master Authority Completion (Constitution §16 steps 1–2 close)

| Slice | Name | Authority | Evidence |
|---|---|---|---|
| C-1w2 | Capabilities write path (+ inseparable reads) | Product Master | PROJECT_STATE C-1c residual (xfail 3→1 target) |
| C-1e | routes_wfirma reads(5)+writes(3) migration | Product Master | PROJECT_STATE C-1c "ADDED RESIDUAL (DEVIATION, needs ruling)" — operator ruling required before slice start |
| C-1f | Proforma fiscal reads (~12) — output-equivalence-gated; requires C-1w1+C-1w2+C-1e complete | Product Master | PROJECT_STATE C-1c "1d fiscal STOP" |
| C-1d | C-1 verification audit (Master-only greps, pin fully green, census append) | Product Master | Constitution §16 step 1 close |
| C-2a | Customer mirror consolidation → one `wfirma_customer_mirror(contractor_id PK)` | Customer Master | Audit §Q6 canonical set; V3; OI-13 affects keying |
| C-2b | Customer write-path reroute (violations V4 proforma fallback, V5 ledgers, V7 suppliers) | Customer Master | Audit §AUTHORITY VIOLATIONS V4/V5/V7 with call-site cites |
| C-2c | Customer verification (no direct wFirma customer calls from business modules; pin to zero) | Customer Master | Constitution §3; MASTER CONSUMPTION RULE |

### Wave 2 — Backend (ALL inventory backend; ZERO UI)

| Slice | Name | Authority | Evidence |
|---|---|---|---|
| **C-3g** | **Slice #1 (ratification amendment 1):** transitional dual-write cleanup (routes_proforma C-1w1 region) + cache-passthrough retirement (get_cached_product/_batch/list_cached_products + C-1f non-identity cache reads + loud fallback) — product pin must reach TRUE 0 before C-3b onward; own equivalence check | Product Master | C-1d audit §Declared residuals 1+2; operator amendment 1 |
| **R2-census** | Residual-2 census (amendment 2): INSPECTOR verifies each of the 6 out-of-pin files; sync-layer → whitelist w/ file:line citation; business logic → migrate-slice proposal; dev tools → exempt-by-purpose documented | Product Master | C-1d audit §Declared residuals 3 |
| **R3-test-health** | Residual-3 (amendment 3): ONE batched test-health slice; first commit = storage-leak seeding fix (landed on deploy/latest, single-lane, side worktree closed); then shipment-detail assertions ×2, capabilities ×2, test_audit_proforma_converted ×3 (root-cause honest disposition) | — (test health) | C-1d audit §Declared residuals 4 |
| C-3a | returns_events migration apply — **verify tree only; prod apply = CP4/deploy operator ritual** (amendment) | Inventory V2 | Wireframe inspection §B; draft_20260512_175238 |
| C-3b | Sample READ/list endpoints (sample_out_events) — backend only, no stub wiring | Inventory V2 | Audit queue item 1 |
| C-3c | Returns READ/list endpoints (returns_events) — backend only | Inventory V2 | Audit queue item 1 |
| C-3d | SALES_TRANSIT write path — fire `invoice_issued` on proforma→invoice via shared `run_stock_issue()` | Inventory V2 (+ Invoice trigger) | Audit §Q3; wireframe §B; gap #2 |
| C-3e | Merchandising/batch joined-read endpoint (inventory_state ⋈ packing_lines) — backend only | Inventory V2 | Wireframe DELIVERABLE 2; gap #5 |
| C-3f | Movement/document-trail reads (piece movement events, promotion-note trail) | Inventory V2 | Operator restored-wave ruling ("movement, document trails") |
| C-4a | Consignment allocation MODEL (net-new table + routes) — proceeds only if OI-17 answered ("where OI permits") | Inventory V2 | Audit §Q4+Q5; wireframe §C3 |

ZERO UI in this wave (operator: "UI is never merged into backend").

### Wave 3 — Entire UI (the complete wireframe UI, built exactly once)

CP3 recognition gate applies to the whole wave (browser verification + screenshots).
UI authority = WIREFRAME_AUTHORITY.md (Constitution §12; never redesign/simplify/invent).

| Slice | Name | Owner (existing — §D no-duplicate) |
|---|---|---|
| U-1 | Sample Out / Sample Return tabs — promote-in-place stubs, wire to C-3b reads + live write routes | reserved slugs + wireframe-update.jsx stubs :492-526 |
| U-2 | Goods Return / Return to Producer tabs — wire to C-3c reads + live write routes | reserved slugs + stubs :528-562 |
| U-3 | Merchandising-grade columns (Karat/Color/Quality/Dia Wt/Qty/CTG/PK SR) in Stock Hub + Move Stock modal | inventory-page.jsx (C-3e read) |
| U-4 | Consignment ledger — mount the EXISTING ConsignmentTab, wire to C-4a routes (NO second component) | client-kyc-and-consignment.jsx:282 |
| U-5 | Real actions row (Export CSV of live tables; Upload → documents hub link; Move Stock per B×7-1b) — real backends only, Lesson M planned-state honesty | inventory-page.jsx + existing export idiom |
| U-6 | KPI tile completion (Consignment tile when C-4a live) | Stock Hub panel-stage2 (B1 restyle) |

### Wave 4 — Synchronization (MM integration + webhook synchronization)

| Slice | Name | Authority | Evidence |
|---|---|---|---|
| C-4b | Consignment issue MAIN→CONSIGNMENT (MM API per OI-1; else operator-UI MM + Atlas reconcile fallback) | wFirma + Inventory V2 | Audit §Q3; wireframe §C3 |
| C-4d | Return Consignment→Main (reverse MM; allocation close; due-back/days-out) | wFirma + Inventory V2 | Wireframe §C5 |
| C-5a | Invoice-from-consignment: consume CONSIGNMENT-warehouse stock ONLY; close allocation; double-stock-out guard | Invoice + Inventory V2 | Wireframe §C4; Constitution §10 |
| C-6a | WZ verification / SALES_TRANSIT close (WZ-add vs invoice-auto-WZ probe = OI-3) | wFirma + Inventory V2 | Audit §Q3 |
| C-7a | MM integration via API (OI-1); if unavailable → fallback documented permanent | wFirma + Inventory V2 | Audit §Q3 |
| C-8a | Goods webhook handler (Towary.*) (OI-10) | wFirma + Product Master | Audit §Q7 |
| C-8b | Contractor webhook handler (Kontrahenci.*) or keep Phase-3B poll (OI-11) | wFirma + Customer Master | Audit §Q7 |
| C-8c | WZ webhook / standalone add path (OI-3) | wFirma + Inventory V2 | Audit §Q3 |
| C-9a | get_stock enablement (double-stock-out verification read; stub wfirma_client:1161) | wFirma | Audit OI-4 |

TBD — Wave 4 re-scopes from OI answers; if OI-1 = "no MM API", C-4b/C-7a become
fallback-documentation and the wave shrinks.

## §3 WAVE ASSUMPTIONS Register (Architecture Confidence Gate)

Operator amendment item 1: each wave lists the named assumptions it depends on. Verified
at every wave boundary AND every health check against the NEXT wave. States:
VALID / AT-RISK / INVALIDATED. Any INVALIDATED → STOP at the wave boundary, manifest
amendment proposed, operator ruling awaited. Mid-wave future-wave invalidations recorded
here immediately; the current wave finishes only unaffected slices.

### Wave 1
- **W1-A1** — Frozen architecture per integration audit (`b9f5664c` + amendment) holds; no
  new authority violations since. — State: **VALID** (Phase 0: pin 8/8, baseline = declared 3-file residual)
- **W1-A2** — C-1b/C-1w1 write-sequence semantics (operator rulings, PROJECT_STATE) remain
  the pattern for C-1w2/C-1e; transitional dual-write accepted. — State: **VALID** (Phase 0: rulings in PROJECT_STATE)
- **W1-A3** — customer_master.sqlite is the identity/VAT/commercial authority;
  `contractor_id` stable across wFirma responses (OI-13 — if unstable, C-2a keying
  changes). — State: **VALID** (Phase 0: bill_to_contractor_id already REQUIRED in customer_master_db.py:46,175; production reliance) — OI-13 stays OPEN for formal confirmation
- **W1-A4** — Wave 1 has no wFirma API dependency (app-side only). — State: **VALID** (Phase 0)

### Wave 2 — Backend (re-derived 2026-07-03 for the restored structure; original operator wording preserved: "sample/returns event tables sufficient for reads, movement model per audit, MM answer state")
- **W2-A1** — `sample_out_events` sufficient for Sample reads. — State: **VALID** (Phase 0: schema in warehouse_db.py; writer + piece-view readers on disk)
- **W2-A2** — returns_events migration draft apply-safe (deploy-gated CP4 at C-3a). — State: **VALID** as draft (Phase 0)
- **W2-A3** — Movement model per audit: inventory_state_engine single-writer intact after Wave 1. — State: [verify at Wave-1 boundary]
- **W2-A4** — MM answer state: OPEN acceptable for Wave 2 (MM legs are Wave 4; no UI and no wFirma dependency in Wave 2). — State: VALID by construction
- **W2-A5** — Consignment MODEL decision (OI-17) answered before C-4a starts; the wave may complete WITHOUT C-4a if OI-17 stays open ("where OI permits"). — State: AT-RISK (OI-17 OPEN — non-fatal, slice-gated)
- **W2-A6** — packing_lines carries the merchandising fields (karat/stone/weights/qty) for the C-3e join. — State: **VALID** (wireframe inspection DELIVERABLE 2: "data already in packing_lines")

### Wave 3 — Entire UI (re-derived 2026-07-03; original wording preserved: "Wave-2 reads live, wireframe unchanged")
- **W3-A1** — Wave-2 backend reads deployed and live (sample/returns lists, merchandising join, trails). — State: **VALID** (2026-07-03: production deployed at 84c292de — SYNC VERIFIED census 493/0/0; live-root mirror 140 rows collisions 0; registry 2 rows; /health 200; four-check gate 4xGREEN)
- **W3-A2** — Wireframe unchanged: docs/design/estrella-dashboard-wireframe.html sha256:f7dd5e3889660fdc1ef76da0f1424a11cad512e7202650db10c031a57799699a. — State: **VALID** (Wave-2 boundary re-hash: MATCH. Canonical method: hash the GIT BLOB (LF) — `git show HEAD:<path>` — not the checked-out file; Windows CRLF checkout changes the raw-file hash and produced a false INVALIDATED reading at this boundary before normalization.)
- **W3-A3** — UI exactly once: every wireframe surface maps to its EXISTING owner (§D no-duplicate plan); no new page/app/HTML. — State: VALID by construction (WIREFRAME_AUTHORITY.md)
- **W3-A4** — CP3 recognition gate available (browser verification per GATE 6). — State: VALID
- **W3-A5** — Consignment ledger UI (U-4) requires C-4a shipped; if C-4a was OI-deferred, U-4 defers with it (planned-state honesty, Lesson M). — State: tracks W2-A5

### Wave 4 — Synchronization (re-derived 2026-07-03; original wording preserved: "webhook/API capabilities per Phase 0 findings")
- **W4-A1** — Webhook/API capabilities per Phase 0 + operator answers: OI-7 (WFIRMA_WEBHOOK_KEY), OI-9 (invoice webhooks), OI-10 (goods), OI-11 (contractor). — State: AT-RISK until answered
- **W4-A2** — MM API vehicle (OI-1) answered, or fallback (operator-UI MM + Atlas reconcile) ratified as permanent. — State: AT-RISK (OI-1 OPEN; business model VALID per PROJECT_STATE 2026-07-03)
- **W4-A3** — Waves 2–3 deployed (backend reads + UI) so the sync legs have surfaces to land on. — State: [verify at Wave-3 boundary]
- **W4-A4** — WZ shape decided by the OI-3 probe (add-vs-auto). — State: AT-RISK (OI-3 OPEN)

## §4 CAMPAIGN BUDGET (operator amendment item 3)

Expected durations — initial estimates, amendable:

| Wave | Budget | Consumed | Remaining | Forecast |
|---|---|---|---|---|
| Wave 1 | 8h | ~4h — COMPLETE | closed | closed at 50% |
| Wave 2 | 11h | ~5.5h — COMPLETE (C-3g, R2, R3, C-3a..C-3f; C-4a OI-deferred) | closed | closed at ~50% |
| Wave 3 | 6h | 0h | 6h | awaiting ratification |
| Wave 4 | 5h | 0h | 5h | — |
| **Total** | **30h** | **~9.5h** | **~20.5h** | under budget |

Every health check records Consumed / Remaining / Forecast per wave (live copy in
RUNTIME.md; this table updated at wave boundaries). A wave exceeding **1.5×** its budget
triggers a self-assessment ledger entry (scope-vs-estimate, SELF_ASSESSMENT.md); at
**2×**, a manifest-revision proposal at the next boundary. **Budget overrun alone is
never a silent scope cut** — the proposal states options, the evidence decides or the
operator rules.

Budget mapping under the restored structure (operator budgets unchanged): Wave 2
Backend 11h · Wave 3 Entire UI 6h · Wave 4 Synchronization 5h. The scope-vs-estimate
risk moves with the consignment scope: the consignment MODEL (Wave 2 C-4a, OI-gated) +
movement legs (Wave 4) remain the highest overrun risk; see SELF_ASSESSMENT.md preamble.

## §5 LAUNCH RULING (operator, verbatim — amendment item 4)

> "Launch Master Campaign. Campaign auto-continues through successive waves
> only while the validated architecture remains consistent with the next
> wave. If evidence invalidates the assumptions of a future wave, the
> campaign stops, proposes a manifest amendment, and waits for that
> architectural decision before proceeding."

Date: 2026-07-03 · Source: FINAL PRE-LAUNCH AMENDMENT (verbatim R4), item 4 ·
Recorded also in: DECISIONS.md · PROJECT_STATE.md `# DECISIONS` (repo-canonical).

## §6 Amendment History

| Date | Amendment | Source |
|---|---|---|
| 2026-07-03 | Platform created; FINAL PRE-LAUNCH AMENDMENT items 1–5 (Confidence Gate, CP Status Summary, Wave Assumptions register, Campaign Budget, launch ruling) incorporated at creation | Operator, verbatim R4 |
| 2026-07-03 | OPERATOR VERDICT: wave structure RESTORED (W1 Authority · W2 Backend · W3 Entire UI · W4 Synchronization); registers + budgets re-derived; UI items moved W2→W3; ratification rule + stop-line active (Waves 2–4 need operator ratification after C-1d) | Operator, verbatim R4 (DECISIONS.md verdict entry) |
| 2026-07-03 | **WAVE 2 RATIFIED** ("RATIFIED. Wave 2 begins.") with four amendments: (1) C-3g = slice #1, pin → true 0 before C-3b; (2) Residual-2 census w/ INSPECTOR verdicts per file; (3) Residual-3 batched test-health slice, storage-leak fix = first commit on deploy/latest, single-lane; (4) users.db → LESSONS_LEARNED #3 + BACKLOG B-017, not chased. C-3a verify-tree-only clarified; C-4a stays OI-17-gated ("wave completes without it otherwise") | Operator ratification (DECISIONS.md Wave-2 entry) |
