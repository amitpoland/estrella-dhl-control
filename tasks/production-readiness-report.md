# Production Readiness Report — Campaign Runner v2

> Snapshot of system readiness state for Phase 6F implementation.
> 2026-05-16 · post Campaign Runner v2 build.

---

## 1 — Production code state

- **Deployed SHA:** `8b3f6f7dda4446c0f8a174eced87284cbcd367c0`
- **Public health:** https://pz.estrellajewels.eu/api/v1/health → 200
- **Local health:** http://127.0.0.1:47213/api/v1/health → 200
- **Service:** PZService (NSSM, port 47213) RUNNING
- **Logs:** `C:\PZ\logs\pz_stderr.log` clean (Uvicorn lifecycle only)

## 2 — Master Data coverage

| Entity | Live | Test coverage |
|---|---|---|
| Customer Master | ✅ | 84/84 + B0 422 fix verified |
| Shipping addresses | ✅ | covered |
| Per-client carrier accounts | ✅ | covered |
| KycModal (6 tabs) | ✅ | all tabs wired |
| Suppliers | ✅ | 30/30 |
| HS Codes | ✅ | covered |
| Units | ✅ | covered |
| Product local | ✅ | covered |
| Incoterms | ✅ | covered |
| VAT Config | ✅ | read-only on wFirma invoicing (contract-guarded) |
| FX Rates | ✅ | REFERENCE-ONLY (contract-guarded; PZ engine NEVER reads) |
| Carriers Config | ✅ | LOCAL, NON-SECRET (contract-guarded) |
| Clients sync chip | ✅ | read-only |
| Designs | 🟡 STUB | B6 gated on schema sign-off |
| Roles | 🟡 STUB | B3 gated on security review |

**13 of 15 entity panels live in production. 2 stubs operator-gated.**

## 3 — Hard-rule status (mechanically verified)

| Rule | Test file | Status |
|---|---|---|
| Master Data hard rules (8) | `test_master_data_hard_rules.py` | 15/15 |
| Runner v2 hard rules (11) | `test_runner_v2_hard_rules.py` | 17/17 |
| PZ regression | `test_pz_regression.py` | 160/160 (verified 15× since campaign start) |

## 4 — Automation maturity

### Campaign tracker
- **File-based state** (`tasks/campaign-state.json`) — 3 campaigns / 24 batches tracked
- **CLI** (`service/scripts/campaign_status.py`) — 17 subcommands
- **Tests** — 70/70 (tracker base 36 + runner v2 34)

### Smoke framework
- **Spec-driven driver** (`service/scripts/run_smoke.py`)
- **P6 metadata extensions** — required_entities, expected_console, expected_api, required_cleanup
- **6 production smoke reports** under `tasks/smoke-reports/`
- **Tests** — 14/14

### Operator dashboard
- `python service/scripts/campaign_status.py dashboard` — full markdown
- Renders: active campaigns, next batches, blockers, stuck batches, branch-stack risks, interrupted campaigns, recent deploys

### Doctor
- `python service/scripts/campaign_status.py doctor` — health check, exit 1 if issues
- Detects: stuck batches (3 thresholds), stack misroutes, interrupted campaigns, schema drift

## 5 — Blockers (operator-gated, by design)

| Blocker | Reason |
|---|---|
| B3 (Users + Roles writes) | Security contract relaxation needed — `test_only_allowed_writes_in_master` forbids `POST /auth/users/{id}/*` from MasterDataPage |
| B6 (Designs Master) | Schema sign-off + read-only-consumer guarantee on `product_identity_engine` |
| MDC-071 (FX override → PZ landed-cost) | **HARD RULE — FORBIDDEN_NOW.** Mutates landed-cost calculation path. |
| Phase 6F implementation | Operator approval of `tasks/phase-6f-architecture.md` §10.1-§10.3 required |

## 6 — Outstanding test surface

| Suite | Count | Status |
|---|---:|---|
| `test_customer_master.py` | 84 | green |
| `test_dashboard_master_design.py` | many | green |
| `test_suppliers.py` | 30 | green |
| `test_master_data_b5.py` | 26 | green |
| `test_master_data_b7.py` | 18 | green |
| `test_master_data_b8.py` | 14 | green |
| `test_master_data_b9.py` | 16 | green |
| `test_master_data_hard_rules.py` | 15 | green |
| `test_campaign_tracker.py` | 36 | green |
| `test_campaign_runner_v2.py` | 34 | green |
| `test_runner_v2_hard_rules.py` | 17 | green |
| `test_smoke_framework.py` | 14 | green |
| `test_pz_regression.py` | 160/160 | green |
| **TOTAL master+tooling+regression** | **~378** | green |

## 7 — Open PRs

| PR | Title | State |
|---|---|---|
| #109 | OSO stabilization + Phase 3 hardening + Phase 6F readiness | OPEN MERGEABLE |
| (this PR) | Campaign Runner v2 — autonomous orchestration | OPEN, in this commit |

## 8 — Readiness verdict

### For continued ops work (next safe campaigns)

**READY.** All hard rules intact. Automation infrastructure operational.
Operator dashboard renders the next-batch recommendation for any active
campaign. Stuck-batch detection + stack misroute detection automated.

### For Phase 6F implementation

**READY pending operator approval.**
- Architecture proposed (`tasks/phase-6f-architecture.md`)
- Readiness verified (`tasks/phase-6f-readiness-2026-05-16.md`)
- Safest first batch identified: **6F.1 schema + DB module**
- Migration order refined with `6F.1.5` contract-test pinning batch
- 8 risks classified · 0 HIGH · 4 MEDIUM (mitigated) · 4 LOW
- Rollback plan exists for every batch

### For autonomous execution

**SUPERVISED-AUTONOMOUS READY.**
The runner can drive a campaign batch-by-batch with operator-in-the-loop
at merge, deploy, and approve gates. It cannot — by mechanical contract
test — auto-merge, auto-deploy, run a daemon, or touch production state.

## 9 — Recommended next campaign

After operator approves Phase 6F architecture §10.1-§10.3:

1. **6F.1** — new SQLite schema + DB module (no behaviour change)
2. **6F.1.5** — contract-test pinning (additive)
3. **6F.3** — read-only `/breakdown` endpoint
4. **6F.2** — backfill from `proforma_service_charges`
5. **6F.4** — UI panel
6. **6F.5** — `/post` dual-write (feature flag OFF default)
7. **6F.6** — settlement-close + FX delta capture
8. **6F.7** — legacy table cleanup

Each batch tracked in `tasks/campaign-state.json` via the runner v2 CLI.
Operator drives merge + deploy. Runner verifies gates.

## 10 — Sign-off

This report is the snapshot at commit (this PR). Subsequent merges will be
recorded under `tasks/campaign-state.json` and reflected in future
dashboard renders.
