# Phase-C Inventory Master — Campaign Manifest (MASTER_MANIFEST.md)

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
| Phase 0 | Research + validation | Populate registers; OI evidence pass; KNOWLEDGE.md | — | **COMPLETE 2026-07-03** |
| **Wave 1** | Master Authority Completion | C-1w2 · C-1e · C-1f · C-1d · C-2a · C-2b · C-2c | 8h | **ACTIVE** |
| **Wave 2** | Sample/Returns Reads + Inventory Parity | C-3a · C-3b · C-3c · C-3d · C-3e | 11h | PENDING |
| **Wave 3** | Consignment + Invoice-from-Consignment | C-4a · C-4b · C-4c · C-4d · C-5a · C-6a | 6h | PENDING |
| **Wave 4** | MM Sync + Webhook Synchronization | C-7a · C-8a · C-8b · C-8c · C-9a | 5h | PENDING |

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

### Wave 2 — Sample/Returns Reads + Inventory Parity (steps 4–5 read side)

| Slice | Name | Authority | Evidence |
|---|---|---|---|
| C-3a | returns_events migration apply (deploy-gated → CP4) | Inventory V2 | Wireframe inspection §B "returns migration pending"; draft_20260512_175238 |
| C-3b | Sample READ/list endpoints (sample_out_events) + wire stubs wireframe-update.jsx:492-526 | Inventory V2 | Audit queue item 1; wireframe §DELIVERABLE 2 Sample |
| C-3c | Returns READ/list endpoints (returns_events) + wire stubs :528-562 | Inventory V2 | Audit queue item 1; wireframe §DELIVERABLE 2 Returns |
| C-3d | SALES_TRANSIT write path — fire `invoice_issued` on proforma→invoice via shared `run_stock_issue()` | Inventory V2 (+ Invoice trigger) | Audit §Q3 lifecycle edge; wireframe §B "transition does not exist"; gap #2 |
| C-3e | Merchandising-grade columns — joined read (inventory_state ⋈ packing_lines) for Stock Hub / Move modal | Inventory V2 | Wireframe §DELIVERABLE 2 Stock Hub table; gap #5 |

TBD — populate from Phase 0: exact list-endpoint paths/shapes; whether C-3a bundles with
C-3c or ships as its own deploy-gated step.

### Wave 3 — Consignment + Invoice-from-Consignment (steps 6–8)

| Slice | Name | Authority | Evidence |
|---|---|---|---|
| C-4a | Consignment allocation model (net-new table: Cons.ID/client/issued/due-back) — model decision = OI-CONSIGNMENT-MODEL | Inventory V2 | Audit §Q4+Q5; wireframe §C3 |
| C-4b | Consignment issue MAIN→CONSIGNMENT: MM API if OI-1 answered; else operator-UI MM + Atlas reconcile fallback | Inventory V2 + wFirma | Audit §Q3 (NET-NEW + WFIRMA-GATED); wireframe §C3 |
| C-4c | ConsignmentTab mount (existing component client-kyc-and-consignment.jsx:282; NO second component, §13/§D) | Inventory V2 | Audit §Q0 "UNUSED stub"; wireframe §D |
| C-4d | Return Consignment→Main (reverse MM; allocation close; due-back/days-out) | Inventory V2 + wFirma | Wireframe §C5 |
| C-5a | Invoice-from-consignment: consume CONSIGNMENT-warehouse stock ONLY; close allocation; double-stock-out guard | Invoice + Inventory V2 | Wireframe §C4; Constitution §10 |
| C-6a | WZ verification / SALES_TRANSIT close (WZ-add vs invoice-auto-WZ probe = OI-3) | wFirma + Inventory V2 | Audit §Q3 "PARTIAL/GATED"; wireframe §C2/§C6 |

TBD — C-4b and C-6a cannot be implementation-scoped until OI-1 / OI-3 are answered.

### Wave 4 — MM Sync + Webhook Synchronization (steps 9–10)

| Slice | Name | Authority | Evidence |
|---|---|---|---|
| C-7a | MM integration via API (OI-1); if unavailable → fallback documented as permanent | wFirma + Inventory V2 | Audit §Q3 "MM absent from every layer" |
| C-8a | Goods webhook handler (Towary.*) — currently would dead-letter (OI-10) | wFirma + Product Master | Audit §Q7 |
| C-8b | Contractor webhook handler (Kontrahenci.*) or keep Phase-3B poll (OI-11) | wFirma + Customer Master | Audit §Q7 |
| C-8c | WZ webhook / standalone add path (OI-3) | wFirma + Inventory V2 | Audit §Q3 |
| C-9a | get_stock enablement (goods count/reserved read for double-stock-out guard; stub wfirma_client:1161) | wFirma | Audit OI-4 |

TBD — entire Wave 4 re-scopes from Phase-0/operator OI answers; if OI-1 = "no MM API",
C-7a becomes documentation-only and the wave shrinks.

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

### Wave 2 (operator amendment wording: "sample/returns event tables sufficient for reads, movement model per audit, MM answer state")
- **W2-A1** — `sample_out_events` table sufficient for Sample reads. — State: **VALID** (Phase 0: schema in warehouse_db.py; writer + piece-view readers on disk)
- **W2-A2** — returns_events migration draft is apply-safe (deploy-gated). — State: **VALID** as draft (Phase 0: draft_20260512_175238 on disk; apply-safety re-proven at C-3a under CP4)
- **W2-A3** — Movement model per audit: inventory_state_engine single-writer discipline
  intact after Wave 1. — State: [verify at Wave-1 boundary]
- **W2-A4** — MM answer state: OPEN is acceptable for Wave 2 (no MM dependency in
  Wave-2 scope). — State: **VALID** (Phase 0)
- **W2-A5** — Wireframe authority unchanged (docs/design/estrella-dashboard-wireframe.html,
  sha256:f7dd5e3889660fdc1ef76da0f1424a11cad512e7202650db10c031a57799699a). — State: **VALID** (Phase 0: hashed)

### Wave 3 (operator amendment wording: "Wave-2 reads live, wireframe unchanged")
- **W3-A1** — Wave-2 sample/returns reads deployed and live. — State: [verify at Wave-2 boundary]
- **W3-A2** — Wireframe unchanged (same hash as W2-A5). — State: [verify at Wave-2 boundary]
- **W3-A3** — Consignment allocation model decided (state vs warehouse-dimension) —
  OI-CONSIGNMENT-MODEL. — State: AT-RISK until operator answers
- **W3-A4** — MM BUSINESS model settled (= internal transfer, not WZ; PROJECT_STATE
  2026-07-03 "wFirma MM: BUSINESS model answered"). — State: VALID
- **W3-A5** — MM API vehicle (OI-1): may remain OPEN — C-4b has the operator-UI + Atlas
  reconcile fallback; if wFirma answers "no API", C-4b re-scopes. — State: [OI-1]

### Wave 4 (operator amendment wording: "webhook/API capabilities per Phase 0 findings")
- **W4-A1** — Webhook/API capabilities confirmed: OI-7 (WFIRMA_WEBHOOK_KEY), OI-9
  (invoice webhook registration), OI-10 (goods webhooks), OI-11 (contractor webhooks). —
  State: AT-RISK until answered
- **W4-A2** — Wave-3 consignment + invoice-from-consignment deployed. — State: [verify at Wave-3 boundary]
- **W4-A3** — MM API (OI-1) either confirmed or fallback documented as permanent. —
  State: [verify at Wave-3 boundary]

## §4 CAMPAIGN BUDGET (operator amendment item 3)

Expected durations — initial estimates, amendable:

| Wave | Budget | Consumed | Remaining | Forecast |
|---|---|---|---|---|
| Wave 1 | 8h | 0h | 8h | — |
| Wave 2 | 11h | 0h | 11h | — |
| Wave 3 | 6h | 0h | 6h | — |
| Wave 4 | 5h | 0h | 5h | — |
| **Total** | **30h** | **0h** | **30h** | — |

Every health check records Consumed / Remaining / Forecast per wave (live copy in
RUNTIME.md; this table updated at wave boundaries). A wave exceeding **1.5×** its budget
triggers a self-assessment ledger entry (scope-vs-estimate, SELF_ASSESSMENT.md); at
**2×**, a manifest-revision proposal at the next boundary. **Budget overrun alone is
never a silent scope cut** — the proposal states options, the evidence decides or the
operator rules.

Pre-launch risk note: Wave 3's 6h likely undercounts (consignment = zero backend today);
see SELF_ASSESSMENT.md preamble.

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
