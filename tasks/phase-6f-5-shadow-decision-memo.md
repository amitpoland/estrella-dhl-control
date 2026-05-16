# Phase 6F.5 Shadow Activation — Operator Decision Memo

> **Status:** decision-aid for operator. NOT a sign-off. NOT an activation
> kick-off. The operator must sign §11 of `phase-6f-5-shadow-activation-approval.md`
> for env vars to be set on production.
> **Date:** 2026-05-16.

This memo is a one-page traffic-light review of the shadow-activation gate.

---

## 1 — Where we are today

| Item | State |
|---|---|
| 6F.5 dual-write code | **DEPLOYED** (PR #121, merge `0f67d34`, 2026-05-16T13:40Z) |
| Production flags | **OFF** (verified at 4 sources: env, .env, NSSM, deployed config defaults) |
| Production runtime behavior | **Unchanged** vs pre-deploy (`finance_postings.sqlite` still 81,920 bytes, 0 `finance_dual_write` log lines) |
| Shadow-activation approval package | **MERGED** (PR #122, merge `3029fbe`) |
| Operator §11 sign-off | **NOT SIGNED** |
| 6F.5-shadow-activation batch | **BLOCKED** awaiting sign-off |
| 6F.2.d live backfill | **BLOCKED** (deferred — production has 0 legacy rows) |

PZ regression: **160/160** across this session's runs.
Hard-rule contract suites: **all green** (88 + 46 = 134 in the latest sweep).

---

## 2 — What shadow activation actually does

Shadow mode is the SAFEST possible activation step. With both flags set:

- `FINANCE_DUAL_WRITE_ENABLED=true` → the hook fires (instead of early-returning).
- `FINANCE_DUAL_WRITE_SHADOW=true` → the hook computes the full payload + sha1 keys and logs at INFO, but **does NOT call create_charge or create_posting**.

Side effects:
- `finance_postings.sqlite` size **unchanged** during shadow mode.
- 0 new rows in `charges` or `postings`.
- 1 INFO log line per charge in each posted proforma, plus 1 aggregate log line per posting.
- Operator UX unchanged. /post response shape unchanged.
- Legacy `proforma_service_charges` table unchanged.

Reversal is a 30-second NSSM env-var clear + PZService restart (`§5 Path A`).

---

## 3 — Risk register (residual)

The deploy already produced full evidence of correctness. The residual
operator-level risks are operational:

| # | Risk | Severity | Mitigation in approval package |
|---|---|---|---|
| R1 | Operator sets `ENABLED=true` without `SHADOW=true` — skips shadow gate, writes live | HIGH if it happens | §1 mandates setting BOTH together; §6 marks `finance_dual_write_committed` log line as hard stop; immediate-disable Path A reverses in 30s |
| R2 | `/post` route currently blocks non-empty `service_charges_json` (line ~3538), so shadow log volume is low (only `synthetic_posting_id=LIVE-...` summary lines per /post; zero per-charge `finance_dual_write_shadow` entries until block-lift) | MEDIUM (UX surprise, not data risk) | §4 R1 of approval package documents this; operator may see fewer logs than the §4 E1 target of 50 and need to either accept this or block-lift first |
| R3 | An NSSM reinstall would clear the flags (safe — defaults to OFF) but operator might assume flags persist | LOW | §10 of decision memo (this doc) flags the assumption explicitly |
| R4 | Operator forgets to take the §12 baseline snapshots before activating | LOW (snapshots are precautionary; rollback works without them) | §12 of approval package lists the snapshot command as the first step |
| R5 | First-post latency spike (`init_db` lazy creation on first live call) | LOW — sub-second on local SSD, and not triggered in shadow mode at all | shadow does not call `init_db`; the latency concern only applies post-shadow |

No HIGH-severity risk has a >0% probability under the operator runbook in
§12 of the approval package.

---

## 4 — Operator's options

### Option A — APPROVE SHADOW ACTIVATION

Proceed to shadow mode with the binding conditions from approval-package §1–§12:

1. Set **both** NSSM env vars:
   - `FINANCE_DUAL_WRITE_ENABLED=true`
   - `FINANCE_DUAL_WRITE_SHADOW=true`
2. Restart PZService.
3. Observe logs for ≥ 5 distinct /post events OR 7 days, whichever first.
4. No committed writes expected. **STOP IMMEDIATELY** if any of these appear:
   - `finance_dual_write_committed`
   - `finance_dual_write_failed`
   - `finance_postings.sqlite` size grows past 81,920 bytes
5. Hard stops HS1–HS10 in §10 of approval package remain in force.

**Recommended IF:** operator is ready to begin the rollout and has 15 minutes of attention to monitor the first /post event live.

### Option B — DEFER

Keep flags OFF. Pick exactly **one** safe parallel batch with zero implementation risk:

| Sub-option | Batch | Effort | Risk |
|---|---|---|---|
| **B1** *(top recommendation if deferring)* | **6F.2.f freeze/audit** | 1 PR, ~200 lines of docs | Zero — closes 6F.2 sub-campaign tidily |
| **B2** | **6F.4 browser smoke completion** | 30 min operator session at https://pz.estrellajewels.eu/login → Diagnostics | Zero — observation only |
| **B3** | **`/post` block-lift inspection** | 1 PR, ~150 lines of `tasks/phase-6f-post-block-lift-inspection.md` | Zero — read-only docs; addresses R2 by scoping a future block-lift batch |

**Recommended IF:** operator wants to stabilize 6F.5 in production for ≥ 1 week before flipping ANY flag, even the shadow one.

### Option C — REJECT

Keep 6F.5 deployed but permanently inactive. Mark `6F.5-shadow-activation` and `6F.5-live-activation` permanently blocked (or convert to a custom `rejected` state). The deployed code remains inert and produces no runtime effect.

Downstream impact:
- 6F.6 (settlement-close + FX delta) becomes unreachable without a separate dual-write implementation.
- 6F.7 (legacy `proforma_service_charges` deprecation) becomes unreachable.
- The 6F.4 Diagnostics panel remains as the only finance posting surface (read-only, currently empty in production).

**Recommended IF:** operator has new data-quality evidence indicating the approach is unsafe. No such evidence has surfaced in this session.

---

## 5 — Recommendation

**Recommend Option B1 — DEFER (run 6F.2.f freeze/audit).**

Rationale:

- Shadow activation is technically low-risk, but R2 (the `/post` route's hard block on non-empty `service_charges_json`) means the shadow log volume will be sparse. The operator would gain little evidence in shadow mode beyond what the existing 191/191 test suite already proves.
- The `/post` block-lift is the prerequisite for shadow mode producing meaningful evidence. Scoping that work (Option B3) is a safer prerequisite to shadow activation than activating immediately.
- 6F.2.f closes the 6F.2 sub-campaign with a final freeze doc, leaving Phase 6F in a tidy paused state.
- 6F.5 already DEPLOYED + verified OFF means the operator can come back to shadow activation at any time without further code work.

**Defensible alternative: Option A** if the operator has 30+ minutes to actively monitor the first activated /post live, accepts that shadow log volume will be low until a future block-lift, and has signed §11.

**Not recommended: Option C.** No data-quality justification has surfaced. Rejecting forfeits 6F.6/6F.7 without operational gain.

---

## 6 — Sign-off (operator response required)

```
( ) APPROVE SHADOW ACTIVATION
    Implementer: proceed with §7 of this memo (exact next command).
    Confirms read of approval-package §1–§10.
    Confirms intent to monitor first /post event live.

( ) DEFER. Chosen sub-option: ___ (B1 / B2 / B3)
    Reason: ______________________________
    Re-evaluate after: ____________________________

( ) REJECT. Reason: ______________________________
    Permanently block 6F.5-shadow-activation and 6F.5-live-activation.
```

Signed: __________________________
Date/time: __________________________

---

## 7 — Exact next command if shadow activation is approved

```powershell
# 1. Snapshot baselines.
$ts = Get-Date -Format "yyyyMMddTHHmmssZ"
New-Item -ItemType Directory -Force -Path "C:\PZ\storage\snapshots-6F5-shadow" | Out-Null
Copy-Item "C:\PZ\storage\proforma_links.db"        "C:\PZ\storage\snapshots-6F5-shadow\proforma_links.pre-shadow-$ts.db" -Force
Copy-Item "C:\PZ\storage\finance_postings.sqlite"  "C:\PZ\storage\snapshots-6F5-shadow\finance_postings.pre-shadow-$ts.sqlite" -Force

# 2. Set BOTH flags via NSSM (AppEnvironmentExtra is currently empty).
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
# 8. If "finance_dual_write_committed" OR "finance_dual_write_failed"
#    appears, execute §5 Path A of approval-package (IMMEDIATE DISABLE).

# 9. After ≥ 5 distinct /post events OR 7 days, collect §4 E1-E8 evidence
#    from approval-package and produce tasks/phase-6f-5-live-activation-approval.md.
```

## 8 — Exact next command if deferred

```powershell
# Record the deferral reason in campaign-state.json:
python service/scripts/campaign_status.py block P6F-2026-05 6F.5-shadow-activation `
  --reason "Operator deferred shadow activation. Reason: <operator-supplied>. Re-evaluate after <criterion>."

# Then pick exactly ONE safe parallel batch.

#    Option B1 (top recommendation — 6F.2.f freeze/audit):
git checkout main && git pull --ff-only origin main
git checkout -b docs/phase-6f-2f-freeze
# Create tasks/phase-6f-2f-freeze.md documenting:
#   - 6F.2.d deferred state (production proforma_service_charges = 0 rows)
#   - Three sha1 namespace conventions (BACKFILL- / LIVE- / real wFirma)
#   - Phase 6F.2 sub-batch closure summary
#   - Operator playbook for re-running 6F.2.b dry-run when source rows exist
# Edit tasks/campaign-state.json: 6F.2.f planned -> active -> pr_open
# Open tasks/-only PR, merge. No deploy.

#    Option B2 (6F.4 browser smoke):
# Open https://pz.estrellajewels.eu/login -> Diagnostics tab.
# Walk the 10 smoke steps in tasks/smoke-reports/2026-05-16-phase-6f-4-finance-panel.md §5.
# Append screenshots + outcomes to that smoke report. Commit via tasks/-only PR.

#    Option B3 (/post block-lift inspection):
git checkout -b docs/phase-6f-post-block-lift-inspection
# Inspect service/app/api/routes_proforma.py around line ~3538.
# Write tasks/phase-6f-post-block-lift-inspection.md scoping what a future
# block-lift batch would change (no code change). Open tasks/-only PR.
```

---

## 9 — Hard stops still in effect (regardless of decision)

| Hard stop | Reason | Status |
|---|---|---|
| No live backfill | 6F.2.d deferred (production has 0 source rows) | BLOCKED |
| No /post response shape change | 6F.5 contract | ENFORCED by source-grep contract |
| No wFirma/PZ/FX/settlement change | 6F.5 hard stops H1-H13 | ENFORCED |
| No UI write button | 6F.4 + 6F.5 contracts | ENFORCED |
| No env vars set yet | Awaiting §11 sign-off | ENFORCED |
| Default-OFF flags | Verified at 4 sources | ENFORCED |
| Activation status = NOT_ACTIVATED | Awaiting operator decision | ENFORCED |

## 10 — Notes for the operator

- An NSSM reinstall would clear `AppEnvironmentExtra` and revert flags to OFF (the Pydantic Settings defaults take over). This is fail-safe but operator should re-set flags after any NSSM maintenance.
- Shadow mode produces ZERO writes. The only evidence is log volume. If the operator cannot or does not want to spot-check log lines, Option B is the better path.
- The 8-evidence list (E1-E8) in §4 of approval-package is the gate to live activation, not shadow activation. Shadow activation itself only requires §11 sign-off.
- Promotion from shadow to live is a separate operator decision and requires its own approval document (`tasks/phase-6f-5-live-activation-approval.md`, to be authored if/when shadow yields satisfactory evidence).
