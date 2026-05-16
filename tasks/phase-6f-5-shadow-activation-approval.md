# Phase 6F.5 — Shadow Activation Approval Package

> **Status:** awaiting operator sign-off. DO NOT SET ENV VARS until §11 is signed.
> **Predecessor:** PR #121 merged, deployed `0f67d342e74c93145a96ef34aeb3b01fc4431606`, flags verified OFF on 2026-05-16T13:42:00Z (smoke report: `tasks/smoke-reports/2026-05-16-phase-6f-5-dual-write-deploy.md`).
> **Generated:** 2026-05-16.

This document is the operator runbook for the FIRST activation step in the 6F.5
rollout: **shadow mode**. Shadow mode computes the dual-write payload + sha1
idempotency keys and logs at INFO without persisting any rows. It is reversible
within seconds and produces zero side effects on the new finance store.

Implementation is already in production (deploy `0f67d34`). This package
governs only the env-var flip + observation window.

---

## 1 — Exact env vars to set

Set **both** env vars at the NSSM service level so they survive PZService
restarts and inherit to the uvicorn process:

```powershell
$nssm = "C:\Users\Super Fashion\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"
# Read current AppEnvironmentExtra to preserve any existing entries.
$current = & $nssm get PZService AppEnvironmentExtra 2>$null
# Append the two flags (newline-separated KEY=VALUE format).
$new = ($current + "`r`nFINANCE_DUAL_WRITE_ENABLED=true`r`nFINANCE_DUAL_WRITE_SHADOW=true").Trim()
& $nssm set PZService AppEnvironmentExtra $new
```

**Critical:** both flags MUST be set together. Setting only `FINANCE_DUAL_WRITE_ENABLED=true` without `FINANCE_DUAL_WRITE_SHADOW=true` would activate LIVE persistence, skipping the shadow gate. Do not do this.

Sanity check immediately after setting (no restart yet):

```powershell
& $nssm get PZService AppEnvironmentExtra
# Expected to show both KEY=VALUE lines.
```

---

## 2 — Exact restart steps

```powershell
sc.exe stop PZService
$t=0; while ((Get-Service PZService).Status -ne 'Stopped' -and $t -lt 15) { Start-Sleep -Seconds 1; $t++ }
sc.exe start PZService
Start-Sleep -Seconds 10
(Get-Service PZService).Status   # must say "Running"
```

Verify the running process inherits both flags. The cleanest method is to hit a
real /post call once the operator has at least one charge-free draft ready (see
§3 observation window), then look for the `finance_dual_write_shadow` log line.
The flags themselves are not exposed via a diagnostic endpoint today.

If you must verify before the first /post, query the process command line:

```powershell
Get-WmiObject Win32_Process | Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "uvicorn" } | Select-Object ProcessId, CommandLine
```

The command line does NOT show env vars. To see them, query `Get-Process | %{ $_.StartInfo.EnvironmentVariables }` is unreliable across PS versions; the authoritative source is the first `finance_dual_write_shadow` log line.

---

## 3 — Exact observation window

| Phase | Duration | Trigger |
|---|---|---|
| Boot soak | **30 minutes** after restart | No actions required. Verify zero new log lines mentioning `finance_dual_write_failed`. The breakdown endpoint still serves cleanly. |
| Real /post observation | **≥ 5 distinct proforma posts** OR **7 calendar days**, whichever comes FIRST | Every operator /post triggers the hook. Watch the log stream. |

Operator activity is normal: post proformas as usual. The dual-write hook is invisible to the operator — no UI change, no response change, no extra prompts. Shadow logs accumulate as a side stream.

---

## 4 — Minimum evidence required before progressing to live activation

Operator must collect ALL of the following before opening the
6F.5-live-activation gate:

| # | Evidence | Where to find it |
|---|---|---|
| E1 | ≥ 50 `finance_dual_write_shadow` log lines | `Select-String -Path C:\PZ\logs\pz_stderr.log -Pattern "finance_dual_write_shadow"` |
| E2 | ≥ 5 distinct synthetic_posting_ids (`LIVE-<hex>`) observed | Extract `target_posting_id=LIVE-` values from log; `Group-Object` and count distinct |
| E3 | **Zero** `finance_dual_write_failed` log lines | `Select-String -Path ... -Pattern "finance_dual_write_failed"` returns nothing |
| E4 | **Zero** new entries in `C:\PZ\storage\finance_postings.sqlite` (size unchanged from 81,920 bytes baseline) | `stat C:\PZ\storage\finance_postings.sqlite` |
| E5 | Spot-check ≥ 3 shadow entries: `amount_minor` matches `Decimal(amount) * 100` for the same draft's `service_charges_json` | Manual cross-reference against the proforma editor view |
| E6 | `sha1` keys are stable: same draft re-posted (if reproducible) yields the same `sha1=<hex>` and same `target_posting_id` | Manual log review |
| E7 | PZ regression 160/160 unchanged | `python test_pz_regression.py` post-activation |
| E8 | Public health 200 throughout window | `Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health` checked daily |

If E3 fails AT ANY POINT during the window, jump to §8 (immediate disable).

---

## 5 — Rollback steps

### Path A — Disable flags (preferred; takes ~ 30 seconds)

```powershell
$nssm = "C:\Users\Super Fashion\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"
# Clear both env vars from NSSM AppEnvironmentExtra.
$current = & $nssm get PZService AppEnvironmentExtra
$cleaned = ($current -split "`r`n" | Where-Object { $_ -notmatch "^FINANCE_DUAL_WRITE_" }) -join "`r`n"
& $nssm set PZService AppEnvironmentExtra $cleaned
sc.exe stop PZService; Start-Sleep -Seconds 5; sc.exe start PZService
```

After restart, both flags fall back to `Field(default=False)`. The next /post
will NOT log `finance_dual_write_shadow`. State returns to pre-activation
identical.

### Path B — Revert the code

```bash
git checkout main && git pull
git revert -m 1 0f67d34 --no-edit
git push
# Then merge the revert PR, robocopy, restart.
```

Use Path B only if Path A fails or the deployed code itself is suspected
(extremely unlikely given the contract tests). Path A is reversible in
seconds; Path B is a full deploy cycle.

### Path C — Manual cleanup

Shadow mode does NOT persist, so there is nothing to delete from the finance
DB. If a future test set `FINANCE_DUAL_WRITE_SHADOW=false` by mistake (skipping
the gate), use:

```sql
-- finance_postings.sqlite — purge anything the dual-write may have written
DELETE FROM charges  WHERE notes LIKE '[live:sha1=%';
DELETE FROM postings WHERE wfirma_invoice_id LIKE 'LIVE-%';
```

These predicates target ONLY the dual-write rows. 6F.2.a backfill rows
(`BACKFILL-` / `[backfill:sha1=...]`) and real wFirma postings are untouched.

---

## 6 — Log patterns to watch

| Pattern | Meaning | Expected count during shadow |
|---|---|---|
| `finance_dual_write_shadow ` (followed by `batch_id=... charge_type=... amount_minor=...`) | One charge per posted draft entered shadow mode | ≥ 50 across the window |
| `finance_dual_write_shadow posting batch=... synthetic_posting_id=LIVE-...` | Aggregate per-posting shadow summary | One per /post event |
| `finance_dual_write skipping unknown charge_type=...` | A charge with `charge_type` outside `{freight, insurance}` was skipped | Probably zero; investigate if non-zero |
| `finance_dual_write skipped: missing batch_id/client/currency` | Mandatory field missing — defensive log | Probably zero |
| `finance_dual_write_failed` | Helper hit an exception (caught) — failure isolation triggered | **Must be zero. Non-zero ⇒ immediate disable per §8** |
| `finance_dual_write payload build failed` | Payload shaping itself raised | Must be zero |
| `finance_dual_write init_db failed` | Could not open finance_postings.sqlite | Shadow mode does not call init_db; should not appear |
| `finance_dual_write committed` | LIVE write committed | **Must NOT appear in shadow mode.** If seen, `FINANCE_DUAL_WRITE_SHADOW` is not set — STOP IMMEDIATELY |

Live monitoring command (PowerShell):

```powershell
Get-Content C:\PZ\logs\pz_stderr.log -Wait | Select-String "finance_dual_write"
```

---

## 7 — How to verify no legacy rollback impact

The legacy `proforma_service_charges` table lives in `C:\PZ\storage\proforma_links.db`. Shadow mode does NOT touch it. Verify by snapshotting before shadow activation and comparing after:

```powershell
# Before activation
Copy-Item "C:\PZ\storage\proforma_links.db" "C:\PZ\storage\proforma_links.pre-shadow.db"

# After observation window ends
Get-FileHash "C:\PZ\storage\proforma_links.db" -Algorithm SHA256
Get-FileHash "C:\PZ\storage\proforma_links.pre-shadow.db" -Algorithm SHA256
# Note: the legacy DB may legitimately grow during the window from regular
# proforma editor activity (UPSERT to proforma_service_charges, drafts, etc.).
# A drift here is EXPECTED and not a dual-write impact.
```

Stronger isolation evidence: the contract test `test_legacy_db_byte_identical_before_and_after` in `service/tests/test_finance_dual_write_legacy_isolation.py` already proved the dual-write helper does not mutate the legacy DB. Production behaviour mirrors the test.

The conclusive check is **§4 E4**: `finance_postings.sqlite` size unchanged at 81,920 bytes. If size is unchanged, no rows were inserted on either side of any join — the shadow path is provably side-effect-free.

---

## 8 — How to disable immediately

If ANY of the following happens during the window:

- `finance_dual_write_failed` appears in logs
- `finance_dual_write_committed` appears in logs (means SHADOW=false was set by mistake)
- `finance_postings.sqlite` grows beyond 81,920 bytes
- Public health drops to non-200
- PZ regression breaks (160/160 → less)
- Any 5xx response from /post that did not exist before activation
- Any operator complaint that posting "feels different"

**Action: execute §5 Path A immediately.** Do not investigate first. The flag-flip-and-restart sequence takes ~30 seconds and produces zero data loss. Investigate after flags are back to OFF.

---

## 9 — Who approves moving from shadow to live

| Step | Requirement |
|---|---|
| Shadow → Live | Operator collects all 8 evidence items in §4 + signs a SEPARATE approval document `tasks/phase-6f-5-live-activation-approval.md` (does not yet exist; create at promotion time). |
| Live activation env-var flip | `FINANCE_DUAL_WRITE_SHADOW=false` (keep `FINANCE_DUAL_WRITE_ENABLED=true`). NSSM set + restart. |
| Live → Shadow (rollback) | Set `FINANCE_DUAL_WRITE_SHADOW=true` again, restart. Live rows remain in `finance_postings.sqlite` (purgeable via §5 Path C SQL). |
| Live → Disabled (rollback) | §5 Path A. |

The operator is the sole approver. No code change, no PR, no deploy is needed
to promote shadow→live — only the env-var flip + restart. The promotion step
is therefore reversible in seconds.

---

## 10 — Hard stop conditions

Operator MUST stop the activation flow and execute §8 disable if any of these
become true at ANY point:

| # | Hard stop |
|---|---|
| HS1 | `finance_dual_write_failed` log line appears |
| HS2 | `finance_postings.sqlite` size grows during shadow mode (size MUST stay 81,920 bytes) |
| HS3 | Any new traceback in `pz_stderr.log` mentioning `finance_dual_write`, `finance_postings_db`, or `routes_proforma.py:post_proforma_draft_to_wfirma` |
| HS4 | /post HTTP response shape changes (any new key, any missing key, any status code change) |
| HS5 | wFirma starts rejecting proforma posts at a higher rate than baseline |
| HS6 | Public health endpoint drops to 5xx |
| HS7 | PZ regression test count drops from 160/160 |
| HS8 | Any unexplained log volume increase (e.g. `finance_dual_write` lines flooding faster than /post call rate) |
| HS9 | Operator observes a discrepancy between shadow log payload and the draft's actual `service_charges_json` |
| HS10 | A second activation of the same draft produces a DIFFERENT `target_posting_id` (would indicate sha1 instability) |

If a hard stop fires AND §8 disable does not restore health within 5 minutes,
escalate to Path B (code revert) per §5.

---

## 11 — Approval block (operator to sign)

```
6F.5 Shadow Activation — Operator Approval

Read this entire document:                              ___ (yes / no)
Production flags currently OFF (verified 2026-05-16):   ___ (yes / no)
PR #121 deployed (SHA 0f67d34):                         ___ (yes / no)
Approves §1 NSSM env var set (BOTH flags together):     ___ (yes / no)
Approves §3 observation window (≥ 5 posts OR 7 days):   ___ (yes / no)
Approves §4 evidence requirements (E1-E8):              ___ (yes / no)
Approves §5 rollback paths (A primary, B secondary):    ___ (yes / no)
Approves §10 hard stops (HS1-HS10):                     ___ (yes / no)
Plans to keep flags OFF until signed:                   ___ (yes / no)

Approved by:        __________________________
Date/time:          __________________________
Notes:
```

Until this block is signed and merged, `6F.5-shadow-activation` remains
`blocked` with reason **"Awaiting operator sign-off on tasks/phase-6f-5-shadow-activation-approval.md. Setting env vars on production is gated."**

---

## 12 — Exact next command if shadow activation is approved

```powershell
# 1. Snapshot baselines for later comparison.
$ts = Get-Date -Format "yyyyMMddTHHmmssZ"
Copy-Item "C:\PZ\storage\proforma_links.db" "C:\PZ\storage\snapshots-6F5-shadow\proforma_links.pre-shadow-$ts.db" -Force
Copy-Item "C:\PZ\storage\finance_postings.sqlite" "C:\PZ\storage\snapshots-6F5-shadow\finance_postings.pre-shadow-$ts.sqlite" -Force

# 2. Set BOTH flags via NSSM. The pre-existing AppEnvironmentExtra is empty.
$nssm = "C:\Users\Super Fashion\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"
& $nssm set PZService AppEnvironmentExtra "FINANCE_DUAL_WRITE_ENABLED=true`r`nFINANCE_DUAL_WRITE_SHADOW=true"

# 3. Verify the set took.
& $nssm get PZService AppEnvironmentExtra
# Expected output:
#   FINANCE_DUAL_WRITE_ENABLED=true
#   FINANCE_DUAL_WRITE_SHADOW=true

# 4. Restart.
sc.exe stop PZService
$t=0; while ((Get-Service PZService).Status -ne 'Stopped' -and $t -lt 15) { Start-Sleep -Seconds 1; $t++ }
sc.exe start PZService
Start-Sleep -Seconds 10
(Get-Service PZService).Status   # must be "Running"

# 5. Begin live monitoring of the log stream.
Get-Content C:\PZ\logs\pz_stderr.log -Wait | Select-String "finance_dual_write"

# 6. Make the FIRST proforma post via the normal operator workflow.
# 7. Within 5 seconds, expect one or more "finance_dual_write_shadow" INFO lines.
# 8. If "finance_dual_write_committed" appears OR "finance_dual_write_failed" appears, execute §8 IMMEDIATE DISABLE.

# 9. After ≥ 5 distinct /post events (OR 7 days), execute the live-activation
#    promotion documented in §9 (requires a separate approval document).
```

Until the operator signs §11 and explicitly chooses to run this command, the
activation step remains `blocked`. The PZService continues to run with both
flags OFF (current state).
