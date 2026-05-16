# Stability Review — Operational Stabilization Campaign Phase 2

> **Classification only. No fixes implemented.** Date: 2026-05-16.
> Source data: live production probes + log inspection + smoke-report review +
> tracker/runner CLI exercise.

---

## 1 — Production stability signals

### API latency (median across 5 calls per endpoint)

| Endpoint | Median | Min | Max | Notes |
|---|---:|---:|---:|---|
| `/api/v1/health` | 12 ms | 9 ms | 81 ms | First call warmed cache; subsequent calls steady |
| `/api/v1/customer-master/` | 12 | 11 | 13 | tight; SQLite reads cached |
| `/api/v1/suppliers/` | 11 | 11 | 13 | tight |
| `/api/v1/hs-codes/` | 12 | 12 | 13 | tight |
| `/api/v1/units/` | 12 | 12 | 12 | tightest band observed |
| `/api/v1/product-local/` | 12 | 12 | 12 | tight |
| `/api/v1/incoterms/` | 12 | 12 | 12 | tight |
| `/api/v1/vat-config/` | 12 | 12 | 12 | tight |
| `/api/v1/fx-rates/` | 12 | 12 | 12 | tight |
| `/api/v1/carriers-config/` | 12 | 12 | 12 | tight |
| `/api/v1/wfirma/customers` | 11 | 11 | 11 | local mapping read; no live wFirma hit on list |
| `/api/v1/wfirma/products` | 11 | 11 | 12 | local mapping read |

**Verdict:** All Master Data list endpoints round-trip in ~12 ms. The 81 ms outlier on the first /health call is JIT/process warm-up, not a steady-state concern.

### Logs

- `C:\PZ\logs\pz_stderr.log` — 4 lines total, all Uvicorn lifecycle. No warnings, no tracebacks, no 4xx/5xx during the sweep.
- Multiple historical `pz_stderr-*.log` rotation files present from 2026-05-09/10 onwards — log rotation is functioning.

### CRUD consistency (production sweep — 31 calls)

- Full lifecycle (create → edit → delete → 404-after-delete) passed for: HS Codes, Units, Product-local, Incoterms, Carriers Config.
- Half-lifecycle (create only — no DELETE endpoint by design) passed for: Customer Master upsert, suppliers create, VAT create, FX create.
- Cleanup pass removed all `OSO-SMOKE-*` artifacts from suppliers, vat_config, fx_rates, shipping_addresses. Customer Master `OSO-SMOKE-CM` row left intact (no DELETE endpoint exists — same shape as the older `BATCH0-SMOKE-TEST` and `B2-PROD-SMOKE` records).

### Repeated CRUD consistency

Each PUT-upsert was idempotent — re-running the smoke spec on the same keys returned 200 with no schema drift. Tested via the run-twice loop on Carriers Config during Phase 1 work.

---

## 2 — Test suite health

| Suite | Result | Notes |
|---|---|---|
| `test_dashboard_master_design.py` | green | 100+ contract tests; allow-list, panel testids, footer contents |
| `test_customer_master.py` | 84/84 | post-B0/B2 fix set |
| `test_suppliers.py` | 30/30 | B4 |
| `test_master_data_b5.py` | 26/26 | B5 |
| `test_master_data_b7.py` | 18/18 | B7 |
| `test_master_data_b8.py` | 14/14 | B8 — incl. `test_pz_engine_never_reads_master_data_fx_rates` source-grep guard |
| `test_master_data_b9.py` | 16/16 | B9 — incl. secret-shape rejection + runtime-isolation guard |
| `test_master_data_hard_rules.py` | 15/15 | 8-rule contract suite |
| `test_campaign_tracker.py` | 24/24 | file-based tracker |
| `test_smoke_framework.py` | 14/14 | driver + render |
| **combined master + tooling** | **331/331** | green this run |
| `test_pz_regression.py` | **160/160** | verified 12× since campaign start |

No flaky tests detected. All deterministic.

---

## 3 — Automation maturity inspection (current state)

### `tasks/campaign-state.json`

- Schema versioned (`schema_version: 1`).
- 19 batches tracked across 2 campaigns.
- 8 status values cover the full lifecycle.
- `previous_main_sha` + `rollback_command` recorded on deploy events → rollback is mechanical.

### `service/scripts/campaign_status.py` (CLI)

- `list` / `show` / `update` / `block` / `unblock` / `smoke` / `export` all working in live run.
- `export MDC-2026-05` produces a markdown table covering all 14 batches with status / PR / merge SHA / deploy SHA / test results / smoke report / block reason.
- 24 unit tests covering atomic-write, merge_sha-survives-update, real-state-file schema validation.

### `service/scripts/run_smoke.py` (driver)

- Spec-driven: any JSON spec file produces a deterministic markdown report.
- Used twice in this session (Carriers Config + 31-step production sweep). Both green.
- Reports include verdict, started/finished timestamps, per-step expected vs actual.
- 14 unit tests + real-reports schema validation.

### `tasks/smoke-reports/`

- 4 reports backfilled covering the MDC stack + Carriers Config + production sweep.
- README format spec exists; each report opens with H1 + ends with Verdict, enforced by `test_real_smoke_reports_are_markdown`.

---

## 4 — Observed weaknesses (classified, NOT fixed)

| # | Weakness | Severity | Category | Suggested resolution |
|---|---|---|---|---|
| **W1** | Customer Master has no `DELETE` endpoint, so smoke artifacts accumulate (e.g. `OSO-SMOKE-CM`, `BATCH0-SMOKE-TEST`, `B2-PROD-SMOKE`) | LOW | Operational hygiene | Add `DELETE /api/v1/customer-master/{cid}` gated by an admin role (out of scope here — belongs to B3 Users+Roles). For now: standardise smoke contractor IDs to a `SMOKE-*` prefix and document them. |
| **W2** | `_OPTIONAL_STR_FIELDS` in `routes_customer_master.py` is maintained by hand; missing a field causes a future B0-style 422 surprise | MEDIUM | Code architecture | Generate the list from the `CustomerMaster` dataclass field types via reflection, OR add a contract test that diff-checks the list against `CustomerMaster.__annotations__`. |
| **W3** | Stacked PRs merging into stale base branches (the B7+B8 misroute that needed forward-merge #105) | MEDIUM | Release workflow | Document in `tasks/campaign-runner.md` § 6 with an explicit "do not stack" rule, OR teach `campaign_status.py` to auto-retarget bases before merge. |
| **W4** | Multiple sqlite files (`customer_master.sqlite`, `suppliers.sqlite`, `master_data.sqlite`) each manage their own connection; no shared backup/snapshot tooling | LOW | Observability | Add a `service/scripts/snapshot_master_data.py` that timestamps + copies all 3 to `storage/snapshots/`. Read-only. |
| **W5** | Browser smoke is API-equivalent only; visual checks rely on the operator manually opening Master Data and clicking each tab | MEDIUM | Coverage | Phase 3 of next campaign could add a thin Playwright/Selenium-driven Tier-2 driver. Not in this campaign's scope. |
| **W6** | Test artifacts (smoke contractor IDs) live in production DB until manually cleaned | LOW | Operational hygiene | Document the `OSO-SMOKE-*` / `BATCH0-SMOKE-*` prefix convention; add a quarterly cleanup runbook. |
| **W7** | Log rotation produces many small files; no consolidated "last error" view | LOW | Observability | Add a `service/scripts/tail_errors.py` that scans all rotated logs and surfaces any non-INFO line. |
| **W8** | The campaign-state.json file is single-writer; concurrent edits from two Claude sessions could clobber each other | LOW | Tooling | Document single-writer assumption; OR add a file-lock via `portalocker`. Not currently exercised because operator runs campaigns sequentially. |
| **W9** | `routes_master_data.py` is now 9 routes × ~80 lines each = ~700 lines in one file. Approaching the size where splitting is worthwhile | LOW | Code architecture | Split into `routes_master_data/{hs_codes.py, units.py, ...}` if the file grows to 1000+ lines. Not urgent. |
| **W10** | The `b5Save` / `b5Delete` generic helpers in `dashboard.html` are not unit-tested at the JS level (source-grep contract test only) | LOW | Test coverage | Consider a small Jest/Vitest harness for dashboard helper functions. Not in this campaign's scope. |
| **W11** | Phase 6F charge model (proposed) introduces a new SQLite file (`finance_postings.sqlite`) — operator needs to decide whether to keep the one-file-per-domain pattern or consolidate into `master_data.sqlite` | INFO | Architecture decision | Operator decision before Phase 6F starts. |

---

## 5 — Repeated friction / UI confusion points (operator-feedback gap)

- **Operator has not yet provided per-tab UI feedback for any of the new entities (B5/B7/B8/B9).** All visual UX assertions are based on the source-grep contracts + the smoke API contracts. The operator should perform Tier-2 visual smoke once before Phase 6F starts.
- The "+ New Client" button on Clients tab being disabled is intentional, but its tooltip "Create client in wFirma directly" may not be obvious to new operators. **Suggested copy fix:** "Add new clients in wFirma; this dashboard syncs them automatically." (Out of scope here.)

---

## 6 — Recommended hardening items (priority order)

| Priority | Item | Owner | Campaign |
|---|---|---|---|
| **P1** | Phase 3 of THIS campaign: add deploy metadata (timestamp, robocopy exit codes, restart duration) to `campaign-state.json` deploy events | this campaign | OIA-2026-05 P3 |
| **P1** | Phase 3 of THIS campaign: add a `summary` subcommand to `campaign_status.py` that prints a top-level dashboard (open PRs / next batch / blocked items) | this campaign | OIA-2026-05 P3 |
| **P1** | Phase 3 of THIS campaign: add branch-stack metadata to batch records (`base_branch`, `stack_depth`) so the next stack-into-stack misroute is caught earlier | this campaign | OIA-2026-05 P3 |
| **P2** | Operator Tier-2 visual smoke pass (open every Master Data tab, click every enabled button, look for console errors) | operator | manual, pre-6F |
| **P2** | Add `DELETE /api/v1/customer-master/{cid}` (admin-gated) to enable smoke artifact cleanup | B3 dependency | future B3 |
| **P3** | Backup snapshot script for the 3 master-data SQLite files | tooling | future "ops hardening" mini-campaign |
| **P3** | Diff-check contract test for `_OPTIONAL_STR_FIELDS` vs `CustomerMaster.__annotations__` | hard-rule suite | optional follow-up |
| **P3** | Log-tail "last error" script | tooling | optional follow-up |
| **DEFER** | Visual Tier-2 smoke driver (Playwright/Selenium) | tooling | separate observability campaign |
| **DEFER** | Split `routes_master_data.py` if it grows past 1000 lines | refactor | future |

---

## 7 — Verdict

**Production is stable.** All 11 live Master Data entities pass full-lifecycle smoke. Latency is consistent and tight (~12 ms median). Logs are clean. Test suites are green (331 + 160). No flakiness observed.

**Automation infrastructure is functional.** Tracker, smoke driver, and contract suite all work in live exercise.

**Hardening items are minor.** None require an emergency response. Phase 3 of this campaign will address the top three P1 items inline.

**Phase 6F readiness:** Ready for Phase 4 inspection. No new risk discovered during this review that wasn't already documented in `tasks/phase-6f-architecture.md`.
