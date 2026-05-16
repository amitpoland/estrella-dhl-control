# Live Task Queue

> Master Data campaign closed B11 audit on 2026-05-16.
> Operational Integrity + Automation campaign closed P0-P5 on 2026-05-16 (PR #108 merged).
> Operational Stabilization + Observation campaign closed P0-P4 on 2026-05-16.
> **Phase 6F PAUSED at steady-state (2026-05-16).** 14 batches, 6 deployed (5 live + 6F.5 deployed default-OFF), 4 operator-gated blocks. Resume: **`tasks/phase-6f-campaign-close.md`**.
>
> **MDOC-2026-05 CLOSED (mechanical closure accepted)** at 2026-05-16T17:00Z. Operator acceptance note: `tasks/mdoc-operator-acceptance-note.md`. 5 capabilities live: AdminUsersPage, Designs CRUD, Roles read-only explainer, UI cleanup, mechanical B-MD4 smoke (14/20 surfaces). 6+1 visual surfaces remain `[ ]` deferred (operator-only browser walks; NOT claimed passed). Zero failures. Zero regressions. PZ 160/160 throughout. 6F.5 default-OFF; Phase 6F paused.
>
> See `tasks/campaign-state.json` for the canonical state of all 3 campaigns (23 batches tracked).
> See `tasks/campaign-runner.md` for the controller doc.
> See `tasks/phase-6f-architecture.md` for the Phase 6F inspection proposal.
> See `tasks/phase-6f-readiness-2026-05-16.md` for the readiness verification (safest first batch = 6F.1).
> See `tasks/stability-review-2026-05-16.md` for production stability classification.

## CURRENT STATE — B11 CLOSURE

- **Campaign:** MDC-2026-05 — Master Data Completion
- **Status:** **MAJORITY-COMPLETE** · 13/15 panels live · 2 operator-gated
- **Open work for operator:**
  - Merge PR #106 (B9 — Carriers Config)
  - Merge this PR (B11 — audit docs)
  - Deploy once via robocopy + PZService restart
  - Run final browser smoke (HS / Units / Product local / Incoterms / VAT / FX / Carriers Config — one row lifecycle each)
- **Remaining operator-gated batches:**
  - B3 — Users + Roles writes (security contract relaxation needed)
  - B6 — Designs Master (schema sign-off needed)
- **Permanently forbidden:** MDC-071 FX override into PZ landed-cost (hard rule)

---

## FINAL QUEUE STATE

| Batch | PR | Outcome |
|---|---|---|
| B0 — CM 422 save fix | #98 | ✅ MERGED + DEPLOYED |
| B1 — Campaign controller | shipped in #99 | ✅ DONE |
| B2 — KycModal completion | #99 | ✅ MERGED + DEPLOYED |
| B3 — Users + Roles wiring | — | 🔴 BLOCKED (B3 gate) |
| B4 — Suppliers | #101 | ✅ MERGED + DEPLOYED |
| B5 — HS + Units + Product local | #102 | ✅ MERGED + DEPLOYED |
| B6 — Designs Master | — | 🔴 BLOCKED (B6 gate) |
| B7 — Incoterms + VAT | #103 | ✅ MERGED (via #105 forward) + DEPLOYED |
| B8 — FX rates reference | #104 | ✅ MERGED (via #105 forward) + DEPLOYED |
| (forward-merge B7+B8 onto main) | #105 | ✅ MERGED + DEPLOYED |
| B9 — Carrier Configuration | #106 | 🟢 OPEN MERGEABLE |
| B10 — wFirma sync visibility | #100 | ✅ MERGED + DEPLOYED |
| B11 — Final audit | this PR | 🟢 OPEN |

---

## LATEST BATCH SUMMARIES

### B9 — Carrier Configuration (2026-05-16) · PR #106 OPEN
- New backend: `master_data_db.CarrierConfig` + `carriers_config` table; `routes_master_data.carriers_config_router` at `/api/v1/carriers-config/`; main.py wires router
- `validate_carrier_config` enforces: lowercase code regex, api_type enum, email format on inbox, **rejects 7 secret-shape field names** (`api_key`, `api_secret`, `password`, `token`, `client_secret`, `credentials`, `auth_secret`)
- UI: 1 PendingPanel → live panel with table + form; visible disclaimer "credentials live in .env and are NEVER stored here"
- Tests: 16 new (test_master_data_b9.py) + 4 new master-design contract tests
- Suite: 278/278 master · 160/160 PZ regression
- Risk: LOW — additive only; carrier runtime untouched (source-grep guard)

### B11 — Final audit (this PR)
- Updated `tasks/master-data-campaign.md` to final-state doc with timeline, entity registry, button registry, hard-rules audit, test budget
- Updated `tasks/todo.md` (this file) to closure state
- Appended B9 + B11 lessons to `tasks/lessons.md`
- No code changes; documentation only

---

## DEPLOYED PRODUCTION STATE

- **Public:** https://pz.estrellajewels.eu
- **Service:** PZService (NSSM)
- **Last deploy SHA:** `d6ae3f7` (post B7+B8 forward-merge #105)
- **Last deploy time:** 2026-05-16
- **Smoke result:** 6/6 entity lifecycles green (HS, Units, Product-local, Incoterms, VAT, FX)
- **Logs:** clean after each deploy (no new tracebacks)

---

## TEST RESULTS — FINAL

| Run | Result |
|---|---|
| `test_customer_master.py` | 84 tests, all green |
| `test_dashboard_master_design.py` | (large; 100+ contract tests, all green) |
| `test_suppliers.py` | 30/30 |
| `test_master_data_b5.py` | 26/26 |
| `test_master_data_b7.py` | 18/18 |
| `test_master_data_b8.py` | 14/14 |
| `test_master_data_b9.py` | 16/16 (awaiting #106 merge to land in main) |
| `test_client_addresses.py` | unchanged ✓ |
| `test_client_carrier_accounts.py` | unchanged ✓ |
| `test_pz_regression.py` | **160/160** (verified 9×) |

---

## NEXT CAMPAIGN — recommended

1. Operator: merge #106 (B9) + this PR (B11) → `/deploy` once → browser smoke 7th entity (Carriers Config) + verify B11 docs landed.
2. Then operator decision on **B3 (Users + Roles writes)** — requires security review of auth-write allow-list relaxation.
3. Then operator decision on **B6 (Designs Master)** — requires schema sign-off + read-only-consumer guarantee on `product_identity_engine`.
4. MDC-071 FX override stays FORBIDDEN.

## 2026-05-16 — B0 wFirma identity cache (deployed, awaiting operator validation)

- **Status:** PRs #141 + #142 merged. Production SHA `ad82ab6`. Flags default-OFF. Smoke 10/10 PASS.
- **Operator follow-up (browser):**
  - Master Data → Suppliers → click "Fetch suppliers from wFirma" → confirm review table loads with 221 proposals (211 new / 10 skipped).
  - Master Data → Customer Master → click "Fetch customers from wFirma" → confirm review table loads with 218 proposals (214 new / 4 review).
  - Skip / Save-Assign / View / Edit row actions behave as expected.
  - Save-Assign with flag OFF → blocked alert appears.
- **Next batch (gated):** Operator flips `WFIRMA_SYNC_SUPPLIERS_ALLOWED=true`, applies a small selected subset via the review panel, confirms only chosen rows wrote. Mirror for customers flag.
- **Deferred:** packing-list contractor resolver — do not start until both flag-on validations pass.
- **Open lesson:** L-040 (router file name ≠ mount prefix) added — consider follow-up patch adding a "URLs resolve" contract test.

## 2026-05-17 — B0 Client Master bulk re-sync (closed)

- **PR #156 merged** — 21 / 21 real client rows backfilled via per-id apply (no bulk Assign-all, no new client creation, 0 preservation violations on operator-owned columns).
- **Second-pass verification (2026-05-17):** 14 rows still flagged by the candidate detector — confirmed at wFirma ceiling (10 real rows where wFirma carries no language/email/postal for the contractor; 4 synthetic test rows NOT FOUND in wFirma). No additional fills possible. Re-running apply would be a no-op.
- **Reports:** `tasks/reports/client-master-bulk-resync-dryrun.md` + `tasks/reports/client-master-bulk-resync-result.md`.
- **Next batch (deferred, requires operator green-light):**
  1. **Live wFirma dictionary refresh** — probe `invoiceseries/find` / `proformaseries/find` / `languages/find` with live creds, add parsers to `wfirma_client.py`, wire `wfirma_dictionary_cache.refresh_from_wfirma()` to merge live entries on top of baseline. Adds a `POST /api/v1/customer-master/dictionaries/refresh` route.
  2. **Symmetric supplier deep-fetch** — mirror the Client Master deep-fetch plumbing on `suppliers_db.sync_from_wfirma` so supplier addresses populate too.
  3. **Operator hand-entry pass** for the 10 wFirma-ceiling rows (language / email / postal) — these can only be filled by the operator since wFirma has no source data.
- **Permanent hard stops still in force:** no wFirma write, no packing-list resolver, no proforma/PZ/DHL/customs/finance change, no .env change.
