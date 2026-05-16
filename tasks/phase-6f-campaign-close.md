# Phase 6F — Campaign Closure (Paused / Operator-Gated)

> **Status:** Phase 6F is paused at a steady-state, fully-documented audit
> point. The campaign is **not abandoned** and **not complete** — it is
> halted at the threshold of two write-bearing gates (shadow activation
> and block-lift), each waiting for explicit operator approval.
> **Date:** 2026-05-16.

This document is the closing audit for the Phase 6F implementation
campaign (campaign id `P6F-2026-05`). It records what shipped, what
sits dormant, what is blocked, the reopening criteria for each gate,
the exact commands the next operator/session will need, and the final
risk register.

---

## 1 — What is live in production

The following capabilities are running today on production
(`https://pz.estrellajewels.eu`):

| Capability | Where | Shipped by | Deployed SHA |
|---|---|---|---|
| 5 additive SQLite tables (`charges`, `postings`, `payments`, `payment_allocations`, `settlements`) + `schema_version` | `C:\PZ\storage\finance_postings.sqlite` (81,920 bytes, empty) | 6F.1 (PR #112) | `f8b17a1` |
| Source-grep dormancy contracts pinning the additive nature | `service/tests/test_finance_postings_contracts.py` (38 tests on main) | 6F.1.5 (PR #113) | `d3bbff3` |
| Read-only `GET /api/v1/finance/postings/{posting_id}/breakdown` endpoint | `service/app/api/routes_finance_postings.py` | 6F.3 (PR #115) | `ba9017d` |
| Read-only Diagnostics finance posting breakdown panel | `service/app/static/dashboard.html` → `DiagnosticsPage` | 6F.4 (PR #118) | `acc92dc` |
| Backfill engine (CLI script, dry-run by default) | `service/scripts/backfill_finance_postings.py` | 6F.2.a (PR #117) | `2f67290` |
| Dual-write hook scaffolding (default-OFF) | `service/app/services/finance_dual_write.py` + 18-line hook in `routes_proforma.py` | 6F.5 (PR #121) | `0f67d34` |

All six capabilities pass their contract suites on `main`. The
`finance_postings.sqlite` file contains zero charges and zero postings.
The 6F.4 panel, when queried with any posting id, returns HTTP 404
cleanly — this is the by-design empty state.

PZ regression: **160/160** verified ≥ 10 times across the campaign.

---

## 2 — What is deployed but OFF

| Capability | Flag(s) | Default | Verified OFF |
|---|---|---|---|
| 6F.5 dual-write hook in `post_proforma_draft_to_wfirma` | `FINANCE_DUAL_WRITE_ENABLED` + `FINANCE_DUAL_WRITE_SHADOW` | both `false` via `Field(default=False, env=...)` | At **4 sources** on 2026-05-16T13:42Z: operator session env, `C:\PZ\.env` file, NSSM `AppEnvironmentExtra` (empty), deployed `config.py` field defaults |

When both flags are false, the hook executes a single early-return
guard before opening any DB file or computing any payload. The
`finance_postings.sqlite` is not touched. The /post HTTP response is
bit-identical to pre-deploy. The legacy `proforma_service_charges`
table is not mutated. There is no observable runtime difference vs
pre-6F.5-deploy.

---

## 3 — What is blocked

Each blocked batch in `tasks/campaign-state.json` has an explicit
`block_reason`. Summary:

| Batch | Block reason | Class |
|---|---|---|
| **6F.2.d** | Live backfill deferred: production `proforma_service_charges` has 0 source rows. Re-run dry-run when rows exist or after legacy source location audit. | Data-state gate |
| **6F.2.e** | Cannot verify breakdown for postings that do not exist. Blocked until 6F.2.d unblocks and produces at least one synthetic posting. | Downstream of 6F.2.d |
| **6F.5-shadow-activation** | Operator deferred shadow activation. Production remains default-OFF. Re-evaluate after 6F.2.f freeze/audit and explicit operator approval. | Operator-decision gate |
| **6F.5-live-activation** | Cannot be considered until shadow run produces ≥ 50 entries across ≥ 5 distinct draft posts with zero `finance_dual_write_failed` log lines. | Downstream of shadow |
| **MDC-2026-05/B3** (carry-over) | Users + Roles writes — security contract relaxation needed | Out-of-scope for P6F |
| **MDC-2026-05/B6** (carry-over) | Designs Master — schema sign-off + product_identity_engine read-only-consumer guarantee | Out-of-scope for P6F |
| **MDC-2026-05/MDC-071** (permanent) | HARD RULE — FX override into PZ landed-cost FORBIDDEN_NOW | Permanent |

The **two P6F gates** (`6F.5-shadow-activation` + `6F.2.d`) are the
only blocks the operator can unblock with a single decision each.
Everything else is downstream of one of those two, or carried over
from a prior campaign.

---

## 4 — What requires operator approval

The operator has three live decisions, each independent of the others:

| Decision | Where | Source-of-truth doc |
|---|---|---|
| **Shadow activation** of 6F.5 dual-write | `tasks/phase-6f-5-shadow-activation-approval.md` §11 | Decision memo: `tasks/phase-6f-5-shadow-decision-memo.md` |
| **Block-lift** of `/post` non-empty `service_charges_json` guard | Future approval package (not yet authored) | Scoping doc: `tasks/phase-6f-post-block-lift-inspection.md` (recommendation: DEFER) |
| **Live backfill** of legacy `proforma_service_charges` rows | `tasks/phase-6f-2c-operator-approval-package.md` §10 | Freeze: `tasks/phase-6f-2f-freeze.md` §12 (recommendation: DEFER until rows exist) |

None of the three is required to keep production stable. All three
are eligible for indefinite deferral. The campaign is structured so
that no time-sensitive deadline forces a decision.

---

## 5 — Reopening conditions

### 5.1 — 6F.5-shadow-activation

Reopen when ANY of these becomes true:

- Operator signs §11 of `tasks/phase-6f-5-shadow-activation-approval.md`.
- A meaningful operator workflow produces non-empty `service_charges_json` drafts (would require block-lift first; see §5.2 below).
- 6F.5 dual-write code change requires a re-deploy and operator wants to validate the new hook in shadow mode first.

### 5.2 — Block-lift of `/post` `service_charges_json` guard

Reopen when ALL of these are true (per inspection doc §11):

- An operator workflow has emerged that requires posting a proforma with explicit freight/insurance lines visible in wFirma (not just stored locally).
- wFirma service-product master data has been seeded by the operator (one good per charge type, plus VAT codes).
- The operator has signed off on a new `tasks/phase-6f-post-block-lift-approval-package.md` (to be authored at reopening time).

### 5.3 — 6F.2.d live backfill

Reopen when ALL of these are true (per freeze doc §12):

1. Production `proforma_service_charges` has ≥ 1 row (probe via §8 step 1 below).
2. A fresh dry-run shows `eligible_rows > 0` AND `blocked_rows == 0`.
3. A new operator approval package (or signed §10 of the existing one) authorises the live run.
4. The `--snapshot-dir` location exists with ≥ 2× the legacy DB's free disk space.
5. PZService is in steady-state; no PR is in the middle of a 7-agent deploy gate.
6. Carrier gate is `pending`; no active carrier write campaign on the same host.

### 5.4 — 6F.5-live-activation (downstream)

Auto-reopens when shadow activation produces ≥ 50 `finance_dual_write_shadow` entries across ≥ 5 distinct posting events with zero `finance_dual_write_failed` lines (per approval-package §4 E1–E8). At that point, a separate `tasks/phase-6f-5-live-activation-approval.md` is authored and signed.

### 5.5 — 6F.2.e post-backfill verification (downstream)

Auto-reopens when 6F.2.d produces ≥ 1 synthetic posting in production. Verification is read-only: hit `GET /api/v1/finance/postings/{id}/breakdown` for each new synthetic posting and confirm the charges array matches the legacy source counts.

---

## 6 — Exact command for shadow activation (if approved later)

Source-of-truth: `tasks/phase-6f-5-shadow-activation-approval.md` §12. Reproduced verbatim here for at-hand convenience.

```powershell
# 1. Snapshot baselines.
$ts = Get-Date -Format "yyyyMMddTHHmmssZ"
New-Item -ItemType Directory -Force -Path "C:\PZ\storage\snapshots-6F5-shadow" | Out-Null
Copy-Item "C:\PZ\storage\proforma_links.db"        "C:\PZ\storage\snapshots-6F5-shadow\proforma_links.pre-shadow-$ts.db" -Force
Copy-Item "C:\PZ\storage\finance_postings.sqlite"  "C:\PZ\storage\snapshots-6F5-shadow\finance_postings.pre-shadow-$ts.sqlite" -Force

# 2. Set BOTH flags via NSSM (AppEnvironmentExtra is empty at closure time).
$nssm = "C:\Users\Super Fashion\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"
& $nssm set PZService AppEnvironmentExtra "FINANCE_DUAL_WRITE_ENABLED=true`r`nFINANCE_DUAL_WRITE_SHADOW=true"

# 3. Verify.
& $nssm get PZService AppEnvironmentExtra
#    Expected: two KEY=VALUE lines, both true.

# 4. Restart.
sc.exe stop PZService
$t=0; while ((Get-Service PZService).Status -ne 'Stopped' -and $t -lt 15) { Start-Sleep -Seconds 1; $t++ }
sc.exe start PZService
Start-Sleep -Seconds 10
(Get-Service PZService).Status   # must be "Running"

# 5. Begin live log monitoring.
Get-Content C:\PZ\logs\pz_stderr.log -Wait | Select-String "finance_dual_write"

# 6. Make the FIRST proforma post via the normal operator workflow.
# 7. Within 5 seconds, expect "finance_dual_write_shadow" INFO line(s).
# 8. If "finance_dual_write_committed" OR "finance_dual_write_failed" appears,
#    execute approval-package §5 Path A (IMMEDIATE DISABLE).

# 9. After ≥ 5 distinct /post events OR 7 days, collect approval-package
#    §4 E1-E8 evidence and produce tasks/phase-6f-5-live-activation-approval.md.
```

Hard stops HS1–HS10 from approval package §10 remain in force.

---

## 7 — Exact command for block-lift implementation (if approved later)

Source-of-truth: `tasks/phase-6f-post-block-lift-inspection.md` (sections 3, 6–11). The implementation has NOT been approved; the inspection recommends DEFER. If a future operator approves it:

```bash
# 1. Author the approval package + decision memo BEFORE writing code.
#    Mirror the 6F.5 pattern: docs PR first, implementation PR second.
cd "C:/Users/Super Fashion/PZ APP"
git checkout main && git pull --ff-only origin main
git checkout -b docs/phase-6f-post-block-lift-approval
#    Create tasks/phase-6f-post-block-lift-approval-package.md
#    Create tasks/phase-6f-post-block-lift-decision-memo.md
#    (Each document follows the structure of its 6F.5 sibling.)

# 2. Operator signs the approval package before any implementation begins.

# 3. After sign-off, the implementer creates the implementation branch:
git checkout main && git pull --ff-only origin main
git checkout -b feat/phase-6f-post-block-lift

#    Allowed files (no others without re-approval):
#    - service/app/core/config.py
#         +1 line: proforma_service_charges_enabled: bool = Field(
#                       default=False, env="PROFORMA_SERVICE_CHARGES_ENABLED")
#    - service/app/services/charge_type_wfirma_mapping_db.py (NEW)
#         read-only DAO over a new SQLite table
#    - service/app/api/routes_proforma.py
#         replace lines 3538-3542 (the ValueError raise) with the
#         flag-guarded mapping lookup + ReservationLine injection
#         described in inspection §3.3
#    - service/app/services/wfirma_client.py (if ProformaRequest needs extension)
#    - service/tests/test_block_lift_*.py (NEW, 8 contracts per inspection §7)
#    - service/tests/test_block_lift_real_builder.py (NEW, ≥2 per Lesson A §8)
#    - tasks/campaign-state.json

# 4. Run gate tests before push:
cd service
python -m pytest tests/test_block_lift_*.py -v
python -m pytest tests/test_finance_postings_contracts.py \
                 tests/test_finance_panel_contracts.py \
                 tests/test_master_data_hard_rules.py \
                 tests/test_runner_v2_hard_rules.py -q
cd ..
PYTHONIOENCODING=utf-8 python test_pz_regression.py   # must be 160/160

# 5. After all green: open PR, run 7-agent deploy gate.
# 6. Deploy lands with PROFORMA_SERVICE_CHARGES_ENABLED=false. Activation is
#    a SEPARATE operator decision (mirror the 6F.5 deploy/activation split).
```

Lessons L-037 (deployed != activated) and L-040 (inspection-only batches close decisions without writing code) both apply.

---

## 8 — Exact command for re-running 6F.2 dry-run if legacy rows appear

Source-of-truth: `tasks/phase-6f-2f-freeze.md` §8. Read-only against the legacy DB; safe at any time without operator approval.

```powershell
# 1. Probe production for row count (read-only).
python -c "import sqlite3; c=sqlite3.connect('C:/PZ/storage/proforma_links.db'); print('rows:', c.execute('SELECT COUNT(*) FROM proforma_service_charges').fetchone()[0])"

# If output is > 0, proceed. If 0, no work to do — close.

# 2. Snapshot the legacy DB to a non-shared location.
$ts = Get-Date -Format "yyyyMMddTHHmmssZ"
$snapDir = "C:\PZ\storage\snapshots-6F2b-rerun"
New-Item -ItemType Directory -Force -Path $snapDir | Out-Null
Copy-Item "C:\PZ\storage\proforma_links.db" "$snapDir\proforma_links.snapshot-$ts.db" -Force

# 3. Run dry-run against the snapshot (NOT the live file).
cd "C:\Users\Super Fashion\PZ APP"
python service/scripts/backfill_finance_postings.py `
  --source-db "$snapDir\proforma_links.snapshot-$ts.db" `
  --target-db "$snapDir\finance_postings.dryrun-$ts.sqlite" `
  --report-path "tasks/backfill-reports/$(Get-Date -Format yyyy-MM-dd)-dryrun-phase-6f-2b-rerun.json" `
  --dry-run

# 4. Inspect the report.
Get-Content "tasks/backfill-reports/$(Get-Date -Format yyyy-MM-dd)-dryrun-phase-6f-2b-rerun.json"

# 5. If counts look right (eligible_rows > 0, blocked_rows = 0, charges_to_create > 0):
#    Author tasks/phase-6f-2c-operator-approval-package-rerun.md (or update the
#    existing approval package with new counters), then proceed through 6F.2.d's
#    exact live command in §4 of that package.
```

The dry-run is non-destructive. It does NOT modify
`C:\PZ\storage\proforma_links.db` (operates on a snapshot). It does
NOT modify `C:\PZ\storage\finance_postings.sqlite` (writes to a fresh
snapshot target). It is safe to run during business hours.

---

## 9 — Hard-rule status (final)

All hard rules from prior campaigns + Phase 6F additions remain
enforced. Verified on `main` at closure (PZ regression 160/160,
contract suites 76/76 + 46/46 = 122 green in the final sweep).

| Rule | Enforced | Source of evidence |
|---|---|---|
| No wFirma live posting added | ✅ | Source-grep across P6F campaign diffs |
| No proforma posting/approval mutation | ✅ | `test_hook_fires_after_mark_post_succeeded`; hook is post-commit only |
| No PZ/customs/DHL calculation change | ✅ | PZ regression 160/160 verified ≥ 10× this campaign |
| No `.env` changes | ✅ | `git diff` confirms across all 14 P6F PRs |
| No direct production DB/storage edits | ✅ | All deploys via robocopy + restart; backfill is dry-run-only |
| No destructive schema operation | ✅ | Phase 6F is additive-only |
| No fake backend data | ✅ | Lesson A real-builder tests in PR #121 |
| External integrations read-only | ✅ | 6F.4 panel calls only `GET /api/v1/finance/postings/{id}/breakdown` |
| Backend-pending buttons disabled with clear reason | ✅ | 6F.4 panel has Read-only badge + empty-state copy |
| Preserve existing /post response shape | ✅ | Pinned by `test_dual_write_source_grep.py` |
| Credentials never stored in master data | ✅ | Carry-over from MDC-2026-05/B9 |
| VAT does NOT override wFirma invoice path | ✅ | Hard-rule contract test green |
| FX does NOT override PZ engine (MDC-071) | ✅ | PERMANENT FORBIDDEN rule |
| Carrier runtime not touched | ✅ | B9 isolation guard green |
| **Default-OFF feature flags (6F.5)** | ✅ | Verified at 4 sources on 2026-05-16T13:42Z |
| **No env vars set in production for P6F flags** | ✅ | NSSM `AppEnvironmentExtra` empty at closure |
| **Three sha1 namespace conventions disjoint** | ✅ | `BACKFILL-` vs `LIVE-` vs real wFirma — pinned by `test_finance_dual_write_no_collision_with_backfill.py` |
| **Activation status NOT_ACTIVATED** | ✅ | Recorded in `tasks/campaign-state.json` |

---

## 10 — Final risk register

| # | Risk | Severity | Status at closure |
|---|---|---|---|
| FR1 | Operator flips `FINANCE_DUAL_WRITE_ENABLED=true` without `SHADOW=true`, skipping the shadow gate | HIGH (if it happens) | Mitigated by approval-package §1 mandating BOTH flags together; §10 HS condition triggers immediate disable; rollback in 30 seconds via Path A |
| FR2 | Future regression places dual-write hook BEFORE `mark_post_succeeded` | MEDIUM | Pinned by `test_hook_fires_after_mark_post_succeeded` source-grep contract; CI fails on any future PR that reorders it |
| FR3 | Decimal-vs-float conversion drift on amount → minor units | LOW | Pinned by `test_source_grep_no_naive_int_times_100` and 13 `test_finance_dual_write_decimal_safety` cases |
| FR4 | `BACKFILL-` / `LIVE-` namespace collision | NEGLIGIBLE | Cryptographically impossible (sha1-input-disjoint AND prefix-disjoint); pinned by `test_finance_dual_write_no_collision_with_backfill.py` |
| FR5 | NSSM reinstall clears the flags | LOW (fail-safe) | Reverts to `Field(default=False)`; operator runbook documents re-set |
| FR6 | Operator confuses `BACKFILL-` / `LIVE-` / real wFirma postings in 6F.4 panel | LOW | Panel's `schema_version` chip + `wfirma_invoice_id` display make the prefix obvious; freeze doc §7 documents all three namespaces |
| FR7 | Future 6F.6 settlement-close assumes block-lift active | LOW (timing only) | 6F.6 approval package must declare dependency explicitly |
| FR8 | An operator manually edits `finance_postings.sqlite` | LOW (out-of-process) | File location is operator-visible; recommend ACL hardening separately if concern arises |
| FR9 | Phase 6F documentation drifts as future batches reopen | LOW | This closure doc is the single point of entry; future reopening commits should update its §3/§5 tables in the same PR |
| FR10 | A future "auto-fix" PR removes the /post block without seeding the wFirma service-product mapping first | MEDIUM | `tasks/phase-6f-post-block-lift-inspection.md` §3 + §7 describe the prerequisite work; future PRs that touch line 3538 should reference the inspection doc in their description |

No HIGH-severity risk has a >0% probability under current operator
discipline + the contract test surface. Phase 6F is shipped to a
**defensible, auditable, low-residual-risk paused state**.

---

## 11 — Campaign metrics (P6F-2026-05)

| Metric | Value |
|---|---|
| Started | 2026-05-16T10:49:30Z (campaign-state.json) |
| Closed (paused) | 2026-05-16 (this PR) |
| Batches in campaign | 14 (6F.1 / 6F.1.5 / 6F.2 umbrella + 6F.2.a/b/c/d/e/f / 6F.3 / 6F.4 / 6F.5 / 6F.5-* / 6F.6 / 6F.7 / 6F-post-block-lift-inspection) |
| Deployed to production | 6 (6F.1 / 6F.1.5 / 6F.3 / 6F.4 / 6F.5 default-OFF / 6F.2.a engine on main) |
| Blocked (operator-gated) | 4 (6F.2.d / 6F.2.e / 6F.5-shadow-activation / 6F.5-live-activation) |
| Planned but not started | 2 (6F.6 / 6F.7) |
| PRs merged in campaign | 14 (PR #112, #113, #115, #117, #118, #119, #120, #121, #122, #123, #124, #125, plus deploy SHAs and forward-merges) |
| Tests added | 90+ contract tests + real-builder tests across all P6F PRs |
| Lessons logged | 4 (L-037 deployed≠activated, L-038 zero-row dry-run is valid, L-039 DEFER is first-class, L-040 inspection-only batches close decisions) |
| PZ regression breakage during campaign | **Zero** (160/160 verified every gate sweep) |
| Production behaviour change at closure | **None observable** (dual-write code present but default-OFF; everything else read-only or empty) |

---

## 12 — Closing statement

Phase 6F is **paused, not abandoned**. The campaign produced:

- A working dormant data store (`finance_postings.sqlite`, 5 tables).
- A read-only HTTP surface (`/api/v1/finance/postings/{id}/breakdown`).
- A read-only operator UI (`DiagnosticsPage` finance breakdown panel).
- A complete backfill engine (verified by dry-run; legacy table is empty).
- A complete dual-write scaffolding (deployed default-OFF).
- Comprehensive approval packages and decision memos for every gate.
- Three sha1 namespace conventions documented and contract-pinned.
- A `/post` block-lift inspection scoping the next implementation batch.
- Zero production-behaviour change.
- Zero regression.

The next session can resume Phase 6F at any time using §6 (shadow
activation), §7 (block-lift implementation), or §8 (6F.2 dry-run
rerun) without re-deriving any of the analysis above. All decisions
are recorded as docs PRs merged into `main`.

The campaign is **CLOSED PENDING REOPENING**. Operator discretion
controls all three gates; none of them is time-sensitive.
