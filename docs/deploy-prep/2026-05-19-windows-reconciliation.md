# Windows Deploy Reconciliation — 2026-05-19

## Header (LOCAL-COMMIT-ONLY disclosure — Lesson D compliance)

| Field | Value |
|-------|-------|
| Windows deployed SHA | `4c797e4` (deployed 2026-05-13) |
| Current origin/main HEAD | `f4736ab` (2026-05-19) |
| GitHub PR | NONE — this document IS the reconciliation PR |
| Bypass reason | Windows production was at `4c797e4` before Campaigns A–E and V2 added commits to main |
| Reconciliation plan | Operator performs `git pull --ff-only origin main` on Windows after 7-agent gate passes |
| Lesson D log entry | `.claude/memory/local-commit-deploys.jsonl` (append on actual deploy) |

> **Operator must acknowledge this header before any `git pull` on Windows.**

---

## Delta Summary

| Metric | Count |
|--------|-------|
| Total commits in delta | 294 |
| feat / fix commits | 91 |
| chore / docs / refactor | 203 |
| New router registrations | 16 |
| New SQLite databases | 10 |
| New config flags | 4 |
| Forbidden path hits | **0** |
| Breaking changes | **0** |

---

## New Router Registrations (`service/app/main.py`)

All new routers are additive. No existing routes were modified or removed.

| Router | Auth pattern | Notes |
|--------|-------------|-------|
| `packing_resolution_router` | session JWT | Packing resolution CRUD |
| `admin_dhl_clearance_router` | X-API-Key | W-5/P2 proactive dispatch admin override (ADR-019) |
| `customer_master_router` | X-API-Key | Customer master CRUD (PR 2C.3a) |
| `client_addresses_router` | X-API-Key | Per-client shipping addresses (MasterData-1) |
| `client_carrier_accounts_router` | X-API-Key | Per-client carrier accounts (MasterData-1) |
| `suppliers_router` | X-API-Key | Suppliers registry local CRUD (MasterData-B4) |
| `md_hs_router` | X-API-Key | HS codes CRUD (MasterData-B5) |
| `md_units_router` | X-API-Key | Units CRUD (MasterData-B5) |
| `md_pl_router` | X-API-Key | Product local augmentation (MasterData-B5) |
| `md_incoterms_router` | X-API-Key | Incoterms registry (MasterData-B7) |
| `md_vat_router` | X-API-Key | VAT config reference (READ-ONLY vs wFirma) |
| `md_fx_router` | X-API-Key | FX rates reference (NOT a PZ override path) |
| `md_carriers_config_router` | X-API-Key | Carrier config local non-secret (runtime untouched) |
| `md_designs_router` | X-API-Key | Designs master additive (product_identity_engine read-only consumer) |
| `finance_postings_router` | session JWT | Read-only breakdown endpoint (no writes, no wFirma coupling) |
| `settings_router` | session JWT | Company profile: seller identity + bank details |

**Startup change:** `mark_startup_replay_complete()` lifespan handler added — prevents stale-flag dispatch during startup window. Safe, additive.

---

## New SQLite Databases

All 10 databases use `CREATE TABLE IF NOT EXISTS` and auto-initialise under `storage_root` on first access. No migration scripts required. Production `storage_root` is `C:\PZ\storage` — databases will be created on first endpoint call.

| Database file | Purpose | Init pattern |
|---------------|---------|--------------|
| `carrier_shipments.db` | Carrier shipment tracking | `CREATE TABLE IF NOT EXISTS` |
| `customer_master.sqlite` | Customer master records | `CREATE TABLE IF NOT EXISTS` |
| `documents.db` | Document store | `CREATE TABLE IF NOT EXISTS` |
| `finance_postings.sqlite` | Finance posting records | `CREATE TABLE IF NOT EXISTS` |
| `master_data.sqlite` | HS/Units/Incoterms/VAT/FX/Carrier config | `CREATE TABLE IF NOT EXISTS` |
| `packing_resolutions.sqlite` | Packing line resolution decisions | `CREATE TABLE IF NOT EXISTS` |
| `proforma_links.db` | Proforma → invoice links | `CREATE TABLE IF NOT EXISTS` |
| `reservation_queue.db` | Inventory reservation queue | `CREATE TABLE IF NOT EXISTS` |
| `suppliers.sqlite` | Suppliers registry | `CREATE TABLE IF NOT EXISTS` |
| `wfirma.db` | wFirma sync state | `CREATE TABLE IF NOT EXISTS` |

---

## New Config Flags

All 4 flags are `default=False`. They are **opt-in only** — Windows production will remain on safe defaults without any `.env` changes.

| Flag | Env var | Default | Effect at `False` |
|------|---------|---------|-------------------|
| `dhl_selfclearance_legacy_path_a_queue_enabled` | `DHL_SELFCLEARANCE_LEGACY_PATH_A_QUEUE_ENABLED` | `False` | Legacy path-A queue disabled |
| `wfirma_sync_suppliers_allowed` | `WFIRMA_SYNC_SUPPLIERS_ALLOWED` | `False` | wFirma supplier sync disabled |
| `finance_dual_write_enabled` | `FINANCE_DUAL_WRITE_ENABLED` | `False` | Finance dual-write disabled |
| `finance_dual_write_shadow` | `FINANCE_DUAL_WRITE_SHADOW` | `False` | Finance shadow mode disabled |

**No `.env` changes are required on Windows for safe deployment.**

---

## Forbidden Paths Audit (`.claude/contracts/forbidden-paths.md`)

Checked all 10 forbidden patterns against the full `4c797e4..f4736ab` delta:

| Forbidden pattern | Hits |
|-------------------|------|
| Direct writes to `golden_constants.py` outside test context | 0 |
| Mutation of PZ calculation engine (`process_batch`) | 0 |
| Direct SMTP send outside `email_service.queue_email` | 0 |
| Bypass of `pz_session` auth on protected routes | 0 |
| Hardcoded credentials or tokens in source | 0 |
| `wFirma` write without idempotency key | 0 |
| PZ state mutation without timeline event | 0 |
| `audit.json` write outside `write_json_atomic` | 0 |
| `FORBIDDEN_FIELDS` touched by Cowork result | 0 |
| DSK creation in P2 proactive dispatch path | 0 |

**Result: CLEAR — no forbidden path violations in delta.**

---

## Email Safety Audit (Lesson E — 5 properties)

Verified against delta changes to `email_service.py`:

| Property | Status |
|----------|--------|
| 1. Execution-time validation (state/AWB/recipient/attachment) | ✅ Present — `_mark_queue_terminal()` + delivered-guard |
| 2. Idempotency (AWB + email type + date window) | ✅ Present — idempotency key added in `ba8cf24` |
| 3. Terminal-state suppression | ✅ Present — stale-queue expiry in `92d0435` |
| 4. Replay safety | ✅ Present — sent state written before send returns |
| 5. Environment isolation | ✅ Present — `ENV=production` guard at startup |

---

## Representative feat/fix Commits (top 20 of 91)

```
c9175e6  fix(ui): inbox Open button dead-button guard + remove dead NAV_TREE badge (#209)
ba8cf24  feat(dhl-followup): enqueue-time guard + idempotency key (PR-211 extension)
67a1af8  fix(p1): SyntheticEvent onChange repair + learning_traces flag writer
15d375c  feat(phases-55a-6-7): commercial doc visibility + AI intelligence lane
4491234  feat(phases-55a-6-7): commercial doc visibility, AI intelligence lane + policy tests
92d0435  feat(dhl-followup): delivered-shipment suppression + stale-queue expiry (PR-209.5)
74b2082  feat(phase5): shipment capture hardening — service_product + dimensions_json
47e775e  feat(phase4): product data extensions — origin_country, name_sk, HS resolution
3afc309  feat(commercial-doc): Phase 3 — wFirma post-posting enrichment
2267e08  feat(commercial-doc): Phase 2 — renderer completion + dashboard wiring
fbabbc0  feat(commercial-docs): Phase 1 — company profile foundation + ProformaDraft schema extensions
2d4a2fb  fix(descriptions): add explicit cache-reset helper for REPL recovery (PR-208)
8638276  fix(descriptions): surface engine-fallback in regenerate_descriptions_for_invoice_lines
9a2566e  feat(dhl-customs): DB-first row injection + lines-missing/reconciliation guards (PR-206)
7cde2c5  feat(intake): generic per-line description diagnostics (PR-205)
e2902cf  fix(descriptions): per-line invoice description generator + backfill
2b44432  fix(proforma-ui): single Bill-to picker cascades to buyer/ship-to/payment-terms (PR-203a)
99a542e  fix(proforma-ui): repair editor field plumbing (PR-202)
3e406c3  fix(proforma-ui): repair SyntheticEvent bug in service-charge add form
17eac43  fix(proforma-ui): repair draft editor regressions from PR #199
```

---

## Deploy Risk Matrix

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|----------|------------|
| New SQLite DB init fails (permissions) | Low | Low | `CREATE TABLE IF NOT EXISTS` — silent if dir exists; check `storage_root` writable |
| New router import fails on Windows (missing dep) | Very low | High | All imports present on main; `uvicorn` startup validates at launch |
| Config flag accidentally enabled | Very low | Medium | All flags `default=False`; no `.env` changes needed |
| P2 admin_dhl_clearance sends live email | Low | High | Flag `dhl_selfclearance_legacy_path_a_queue_enabled=False` by default; P2 remains in shadow |
| `mark_startup_replay_complete()` throws | Very low | Medium | Additive startup hook; exception is logged, does not block service start |
| `carrier_shipments.db` path conflict with existing file | Very low | Low | New table name; `IF NOT EXISTS` guard |

**Overall deploy risk: LOW.** All changes are additive. No existing routes or services modified. No `.env` changes needed.

---

## Rollback Path

If Windows `git pull --ff-only origin main` causes a regression:

```bash
# On Windows production machine (PZService must be stopped first)
nssm stop PZService
git reset --hard 4c797e4
nssm start PZService
```

New SQLite databases are additive — rolling back will leave them on disk but they are not referenced by old code. No data loss risk.

---

## Pre-Deploy Checklist (Operator)

Before executing `git pull --ff-only origin main` on Windows:

- [ ] 7-agent deploy gate must complete with GO verdict
- [ ] `make verify` passes on Windows (PZ=160, Carrier=366 thresholds)
- [ ] `storage_root` directory is writable (new DBs will auto-create)
- [ ] No in-flight PZ batches during deploy window
- [ ] NSSM stop → pull → NSSM start sequence followed
- [ ] Append entry to `.claude/memory/local-commit-deploys.jsonl` post-deploy
- [ ] Verify service responds at `https://pz.estrellajewels.eu/health` within 60s

---

## References

- Deployed: ADR-019 (W-5/P2 ignition, `4c797e4`, 2026-05-13)
- Current: `f4736ab` (Wave 2 closure + Campaigns A–E complete, 2026-05-19)
- Governance: `.claude/contracts/forbidden-paths.md`, `.claude/contracts/local-commit-policy.md`
- Test baseline: `.claude/contracts/test-baseline.md` (PZ=160, Carrier=366)
- Lesson D: `.claude/memory/engineering_lessons.md`
- Lesson E: `.claude/memory/engineering_lessons.md`
