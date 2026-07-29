# PZ Correction Lifecycle — Phase 1 Activation Runbook

**Document version:** 1.1  
**Produced:** 2026-05-25 (v1.0) — updated 2026-05-25 (v1.1: M3 fix — Step 4b correct endpoint)  
**Author:** Deployment automation pipeline (session 2398098c)  
**Status:** READY — all backend blockers resolved (PR C merged SHA `9d044c5`, deployed SHA `5bcb492`)

---

## MANDATORY READ-FIRST CONSTRAINTS

These constraints are non-negotiable and govern the entire runbook.
Violating any one of them is grounds for immediate abort.

```
✗  Do NOT enable WFIRMA_CORRECTION_PUSH_ALLOWED in this activation window
✗  Do NOT start Phase 2 UI work during or after this activation
✗  Do NOT proceed past Step 4 without an explicit operator decision
✗  Do NOT call correction-commit (/lineage/{id}/correction-commit) at any point
✗  Do NOT touch wfirma_client.py
✗  Do NOT change or add any UI
```

Phase 1 activates **state visibility and staging logic only**.
wFirma write paths remain unreachable by design — the push flag is a
separate controlled window requiring a separate operator decision.

---

## Production Baseline (as of deploy SHA `5bcb492`)

| Item | State |
|------|-------|
| Service | PZService, NSSM, port 47213 |
| Public URL | `https://pz.estrellajewels.eu` |
| Local health endpoint | `http://127.0.0.1:47213/api/v1/health` |
| `PZ_CORRECTION_LIFECYCLE_ENABLED` | **ABSENT from .env → defaults False → DORMANT** |
| `WFIRMA_CORRECTION_PUSH_ALLOWED` | **ABSENT from .env → defaults False → wFirma write BLOCKED** |
| Lifecycle routes registered | Yes (always registered; guarded by flag at runtime) |
| correction-state endpoint | Returns 503 `lifecycle_disabled` when flag is OFF |
| correction-commit endpoint | Returns 503 `lifecycle_disabled` when flag is OFF |
| correction-commit additional guard | `wfirma_correction_push_allowed` check (Phase 2 gate) |
| STARTUP_AI_AUDIT | Fires in pz_stdout.log on every restart |
| Backend PRs merged | A (`da097f1`), B (`c9e7f9c`), C (`9d044c5`) |

Confirm this baseline before running Step 1:

```powershell
# Run from an elevated PowerShell on the production host (C:\PZ)
.\scripts\env_config_manager.ps1 -Action Show
```

**Expected output (DORMANT baseline):**
```
[STATE] Current .env flag configuration
  PZ_CORRECTION_LIFECYCLE_ENABLED  = (absent → false)
  WFIRMA_CORRECTION_PUSH_ALLOWED   = (absent → false)
  PZService state                  = RUNNING
  Phase 1: DORMANT (both flags off)
```

If `WFIRMA_CORRECTION_PUSH_ALLOWED` shows anything other than absent/false: **ABORT. Do not proceed.**

---

## External System Reachability

Before activating, confirm the following external systems are reachable
and that you have a suitable test batch available.

| System | Check | Required for |
|--------|-------|--------------|
| wFirma API | `GET /invoices` returns 200 | Phase 2 only — NOT required for Phase 1 |
| Global batch infrastructure | At least one Global batch exists in the DB | Step 3 smoke test |
| PZ App health | `/api/v1/health` returns 200 | All steps |
| Email routing (SMTP) | Not required | Phase 1 does not send emails |
| WorkDrive | Not required | Phase 1 does not upload documents |

**Phase 1 has zero external write dependencies.**
Only PZService itself needs to be healthy. wFirma reachability is
irrelevant until Phase 2.

To find a suitable test batch (Global shipment):

```powershell
# Query the PZ App API for any Global batch
$k = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^AUTH_SECRET_KEY=" } | ForEach-Object { $_.Split("=",2)[1] })
Invoke-WebRequest -Uri "http://127.0.0.1:47213/api/v1/pz/batches?limit=20" `
    -Headers @{"X-API-Key"=$k} -UseBasicParsing | Select-Object -ExpandProperty Content
```

Record a `batch_id` that has `is_global_batch: true` in the response.
You will need it for Steps 3 and 4.

```
RECORDED BATCH ID FOR THIS ACTIVATION: ______________________________
```

---

## Step 1 — Enable PZ_CORRECTION_LIFECYCLE_ENABLED=true

**What this does:** Activates correction-state, correction-stage, correction-reset,
and correction-suppress endpoints. correction-commit remains blocked by the push flag.

**What this does NOT do:** It does not touch wFirma. It does not write any PZ documents.
It does not send emails. It does not change any existing batch state.

**Reversible:** Yes — rollback command is in the abort section below.

### Pre-step gate

```powershell
# 1a. Confirm baseline
.\scripts\env_config_manager.ps1 -Action Show

# 1b. Assert push flag is off (abort if this fails)
.\scripts\env_config_manager.ps1 -Action AssertPushOff
```

**Expected:**
```
[OK] WFIRMA_CORRECTION_PUSH_ALLOWED = (absent → false)
     correction-commit is unreachable (push gate holding).
```

If 1b does not print `[OK]`: **ABORT. Do not touch the lifecycle flag.**

### Execute

```powershell
# Option A — PowerShell (recommended for manual activation)
.\scripts\env_config_manager.ps1 -Action ActivateLifecycle

# Option B — Python automation (dry-run first, then execute)
python scripts\activate_pz_lifecycle.py            # dry-run (default)
python scripts\activate_pz_lifecycle.py --execute  # live write
```

**Expected (Option A):**
```
[ACTIVATE] Enabling PZ_CORRECTION_LIFECYCLE_ENABLED=true
[CHECKPOINT] Saved: C:\PZ\env-checkpoints\env-checkpoint-YYYYMMDD-HHMMSS.bak
[OK] Flag written to C:\PZ\.env
[NEXT] Run: .\env_config_manager.ps1 -Action RestartService
[NEXT] Then: .\env_config_manager.ps1 -Action AssertHealth
```

### Success criteria

- `.env` contains `PZ_CORRECTION_LIFECYCLE_ENABLED=true`
- A checkpoint `.bak` file exists in `C:\PZ\env-checkpoints\`
- `WFIRMA_CORRECTION_PUSH_ALLOWED` is still absent/false in `.env`

### Abort criteria (before proceeding to Step 2)

- Script reports `[ABORT]` for any reason → stop, investigate
- `.env` write failed → `.env` is unchanged (atomic write guarantee); safe to retry
- Checkpoint directory could not be created → resolve permissions first

---

## Step 2 — Restart PZService

**What this does:** Loads the new flag value into the running process.
The service must restart to pick up `.env` changes.

**Reversible:** Yes — rollback restores flag and restarts clean.

### Execute

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


**Expected:**
```
[SERVICE] Stopping PZService ...
[SERVICE] Starting PZService ...
[SERVICE] State: RUNNING
[OK] Service RUNNING and healthy.
```

### Success criteria

All of the following must be true before proceeding:

| Check | Command | Expected |
|-------|---------|----------|
| Service RUNNING | `sc.exe query PZService` | `STATE: 4 RUNNING` |
| Health 200 | `Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -Headers @{"X-API-Key"=$k}` | `StatusCode: 200` |
| STARTUP_AI_AUDIT fired | `Select-String "STARTUP_AI_AUDIT" C:\PZ\logs\pz_stdout.log \| Select -Last 3` | 3 lines present with current timestamp |
| Flag loaded | `Select-String "lifecycle" C:\PZ\logs\pz_stdout.log \| Select -Last 5` | Should show lifecycle enabled log entry |

### Abort criteria

- Service reaches `STOPPED` and does not recover within 30 seconds
- Health check fails after 3 attempts (30-second wait between each)
- Any `ERROR` in `pz_stderr.log` that was not present before restart

**Abort procedure (Step 2):**
```powershell
# Rollback the flag and restart clean
.\scripts\env_config_manager.ps1 -Action RollbackLifecycle
# Verify service came back up
.\scripts\env_config_manager.ps1 -Action AssertHealth
```

---

## Step 3 — Smoke Test correction-state on a Real Global Batch

**What this does:** Confirms the lifecycle flag is active and the correction-state
endpoint returns a valid response for a known Global batch.

**What this does NOT do:** Does not stage, commit, or modify any batch.
This is a read-only probe.

**Reversible:** N/A — this step makes no writes.

### Prerequisites

- You recorded a `batch_id` with `is_global_batch: true` in the Pre-Activation section
- PZService is RUNNING (Step 2 passed)

### Execute

```powershell
$k = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^AUTH_SECRET_KEY=" } | ForEach-Object { $_.Split("=",2)[1] })
$batch_id = "YOUR_BATCH_ID_HERE"   # replace with recorded batch_id

$r = Invoke-WebRequest `
    -Uri "http://127.0.0.1:47213/api/v1/pz/lineage/$batch_id/correction-state" `
    -Headers @{"X-API-Key"=$k} `
    -UseBasicParsing
Write-Host "Status: $($r.StatusCode)"
$r.Content | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

**Using the smoke test suite:**

```powershell
python scripts\lifecycle_smoke_tests.py --batch $batch_id
```

### Success criteria

**HTTP 200** with a JSON body containing at minimum:

```json
{
  "batch_id": "<your-batch-id>",
  "lifecycle_enabled": true,
  "current_state": "...",
  "push_allowed": false
}
```

Key assertions:
- `lifecycle_enabled` must be `true` (confirms flag loaded)
- `push_allowed` must be `false` (confirms Phase 2 gate holding)
- `current_state` is any valid state string (not an error)
- No `lifecycle_disabled` in the response body

### Abort criteria

| Response | Meaning | Action |
|----------|---------|--------|
| 503 `lifecycle_disabled` | Flag not loaded — service needs restart | Repeat Step 2 |
| 404 `batch not found` | Wrong batch_id | Use correct Global batch_id |
| 500 | Backend error | Check `pz_stderr.log`; rollback |
| `push_allowed: true` | Push flag is set — CRITICAL | **IMMEDIATE ROLLBACK** (see Emergency Abort) |
| Any `wfirma` key in response with write data | Unexpected wFirma call | **IMMEDIATE ROLLBACK** |

---

## Step 4 — Test Stage / Reset / Suppress (No Commit)

**What this does:** Exercises the full correction lifecycle flow — stage an option,
then reset it back, then suppress — to verify state transitions work correctly.

**What this does NOT do:** Does not call correction-commit. Does not touch wFirma.
The stage operation moves the batch to STAGED state but no wFirma write is attempted
because WFIRMA_CORRECTION_PUSH_ALLOWED is false.

**Reversible:** Yes — reset and suppress are both available as escape hatches.

### 4a. Stage an option

```powershell
$k = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^AUTH_SECRET_KEY=" } | ForEach-Object { $_.Split("=",2)[1] })
$batch_id = "YOUR_BATCH_ID_HERE"

# First: get available options from correction-state
$state = Invoke-WebRequest `
    -Uri "http://127.0.0.1:47213/api/v1/pz/lineage/$batch_id/correction-state" `
    -Headers @{"X-API-Key"=$k} -UseBasicParsing | Select-Object -ExpandProperty Content | ConvertFrom-Json

# Pick a stageable option_id from $state.available_options
# Choose one that is NOT KEEP_CURRENT and NOT NO_ACTION
# (those raise 409 by design — testing them separately in 4c)
$option_id = "YOUR_OPTION_ID"   # e.g. "CREATE_NEW_PZ" if available

$body = @{option_id=$option_id; operator_note="Step 4 activation test"; line_ids=@()} | ConvertTo-Json
Invoke-WebRequest `
    -Uri "http://127.0.0.1:47213/api/v1/pz/lineage/$batch_id/correction-stage" `
    -Method POST -Headers @{"X-API-Key"=$k; "Content-Type"="application/json"} `
    -Body $body -UseBasicParsing
```

**Expected:** HTTP 200, state transitions to `STAGED`.

### 4b. Reset back to OPERATOR_REVIEWED

```powershell
# M3 fix (runbook v1.1): reset is DELETE on /correction-stage — NOT POST /correction-reset.
# The path /correction-reset does not exist in the backend (returns 404).
# Correct backend route: DELETE /api/v1/pz/lineage/{batch_id}/correction-stage
Invoke-WebRequest `
    -Uri "http://127.0.0.1:47213/api/v1/pz/lineage/$batch_id/correction-stage" `
    -Method DELETE -Headers @{"X-API-Key"=$k} -UseBasicParsing
```

**Expected:** HTTP 200, state transitions back to `OPERATOR_REVIEWED`.

### 4c. Verify KEEP_CURRENT / NO_ACTION raise 409 (not commit)

```powershell
$body = @{option_id="KEEP_CURRENT"; operator_note="test"; line_ids=@()} | ConvertTo-Json
try {
    Invoke-WebRequest `
        -Uri "http://127.0.0.1:47213/api/v1/pz/lineage/$batch_id/correction-stage" `
        -Method POST -Headers @{"X-API-Key"=$k; "Content-Type"="application/json"} `
        -Body $body -UseBasicParsing
    Write-Host "[FAIL] Expected 409 but got success" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 409) {
        Write-Host "[PASS] KEEP_CURRENT correctly returned 409" -ForegroundColor Green
        $_.ErrorDetails.Message
    } else {
        Write-Host "[FAIL] Unexpected status $code" -ForegroundColor Red
    }
}
```

**Expected:** 409 response containing text about `correction-suppress`.

### 4d. Suppress the workflow (cleanup)

```powershell
Invoke-WebRequest `
    -Uri "http://127.0.0.1:47213/api/v1/pz/lineage/$batch_id/correction-suppress" `
    -Method POST -Headers @{"X-API-Key"=$k} -UseBasicParsing
```

**Expected:** HTTP 200, state transitions to `TERMINAL_SUPPRESSED`.

**Using the full smoke test suite for Step 4:**

```powershell
python scripts\lifecycle_smoke_tests.py --batch $batch_id --full-lifecycle
```

### Success criteria (all of 4a–4d)

| Sub-step | Expected | PASS if |
|----------|----------|---------|
| 4a stage | 200 | `current_state == STAGED` |
| 4b reset | 200 | `current_state == OPERATOR_REVIEWED` |
| 4c KEEP_CURRENT | 409 | response body mentions `correction-suppress` |
| 4c NO_ACTION | 409 | response body mentions `correction-suppress` |
| 4d suppress | 200 | `current_state == TERMINAL_SUPPRESSED` |
| Throughout | No 2xx from correction-commit | correction-commit was never called |
| Throughout | No wFirma API calls | `push_allowed` stayed false in all responses |

### Abort criteria (Step 4)

- correction-commit returns 2xx at any point → **CRITICAL: IMMEDIATE ROLLBACK**
- 4a stage returns 500 → check logs, rollback if service is unstable
- 4c KEEP_CURRENT returns 200 (not 409) → backend guard missing, rollback and investigate
- Service becomes unhealthy mid-step → rollback

---

## ⛔ DECISION GATE — Between Step 4 and Step 5

**Do not proceed automatically. This is an explicit operator checkpoint.**

After Step 4 passes, you have confirmed:
- The lifecycle state machine works correctly
- Stage → reset → suppress transitions are verified
- KEEP_CURRENT and NO_ACTION correctly reject with 409
- The push gate is holding (correction-commit never reached wFirma)

Before continuing to Step 5, the operator must acknowledge:

```
[ ] Step 3 correction-state smoke test: PASSED
[ ] Step 4a stage: PASSED
[ ] Step 4b reset: PASSED
[ ] Step 4c KEEP_CURRENT 409: PASSED
[ ] Step 4c NO_ACTION 409: PASSED
[ ] Step 4d suppress: PASSED
[ ] No wFirma writes occurred (push_allowed=false throughout)
[ ] No correction-commit 2xx occurred
[ ] Service is healthy (HTTP 200 from /health)

Operator signature: _________________________ Date/Time: _____________
```

If any box is unchecked: **STOP. Do not run Step 5.**

---

## Step 5 — Confirm WFIRMA_CORRECTION_PUSH_ALLOWED Remains false

**What this does:** Final read-only safety assertion. Confirms the push flag
was not accidentally set during any of the previous steps.

```powershell
.\scripts\env_config_manager.ps1 -Action AssertPushOff
```

**Expected:**
```
[SAFETY] Asserting WFIRMA_CORRECTION_PUSH_ALLOWED is OFF
[OK] WFIRMA_CORRECTION_PUSH_ALLOWED = (absent → false)
     correction-commit is unreachable (push gate holding).
```

**Also run the full gate for belt-and-suspenders:**

```powershell
.\scripts\env_config_manager.ps1 -Action FullGate
```

**Expected:** `[FULL GATE] All checks passed.`

### Abort criteria

- `WFIRMA_CORRECTION_PUSH_ALLOWED` shows `true`, `1`, or `yes` → **CRITICAL.
  Do not proceed. Initiate emergency rollback immediately.**

---

## Step 6 — Document Decision Point for Push Enablement

**What this does:** Creates a durable record that Phase 1 is complete and
describes exactly what a future operator must do to enable Phase 2.

**This step makes no system changes.** It is documentation only.

### Record Phase 1 completion

Create a timestamped checkpoint of the current `.env`:

```powershell
.\scripts\env_config_manager.ps1 -Action Checkpoint
```

### Document the current state

```
PHASE 1 ACTIVATION COMPLETE
============================
Date/Time:        ____________________________
Operator:         ____________________________
Batch tested:     ____________________________
All steps passed: YES / NO (circle one)

Final .env state:
  PZ_CORRECTION_LIFECYCLE_ENABLED  = true
  WFIRMA_CORRECTION_PUSH_ALLOWED   = false (absent)

Checkpoint file:  C:\PZ\env-checkpoints\env-checkpoint-<timestamp>.bak
```

### Phase 2 — Decision criteria for push enablement

**Phase 2 is a SEPARATE controlled window. It requires:**

1. A separate explicit operator decision — not a continuation of this runbook
2. Verification that wFirma API is reachable and credentials are valid
3. A specific candidate correction batch that has been operator-reviewed
4. A separate rollback plan for wFirma partial-write scenarios
5. The `WFIRMA_CORRECTION_PUSH_ALLOWED` flag set only after all Phase 2 preconditions are met

**To enable Phase 2 in a future session:**

```powershell
# ONLY when all Phase 2 preconditions are met:
# 1. Checkpoint current state
.\scripts\env_config_manager.ps1 -Action Checkpoint
# 2. Manually add to C:\PZ\.env:
#    WFIRMA_CORRECTION_PUSH_ALLOWED=true
# 3. Restart service
.\scripts\env_config_manager.ps1 -Action RestartService
# 4. Verify health
.\scripts\env_config_manager.ps1 -Action AssertHealth
# 5. Run a single correction with a non-production batch first
```

Phase 2 push enablement must NOT happen in this activation window.

---

## Emergency Rollback

### Rollback script (fastest path)

```powershell
# Reverts PZ_CORRECTION_LIFECYCLE_ENABLED to false and restarts service
.\scripts\env_config_manager.ps1 -Action RollbackLifecycle
```

### Manual rollback (if scripts unavailable)

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


### Restore from checkpoint

```powershell
# List available checkpoints
Get-ChildItem C:\PZ\env-checkpoints\

# Restore a specific checkpoint
Copy-Item "C:\PZ\env-checkpoints\env-checkpoint-YYYYMMDD-HHMMSS.bak" "C:\PZ\.env" -Force
# Then restart service (as above)
```

---

## Monitoring During and After Activation

### Log files to watch

| File | What to check |
|------|---------------|
| `C:\PZ\logs\pz_stdout.log` | STARTUP_AI_AUDIT lines, lifecycle flag loaded message |
| `C:\PZ\logs\pz_stderr.log` | Any ERROR lines introduced after restart |
| `C:\PZ\logs\pz_access.log` (if exists) | No unexpected `/correction-commit` calls |

### Real-time monitoring commands

```powershell
# Watch stdout for errors (run in a separate window during activation)
Get-Content "C:\PZ\logs\pz_stdout.log" -Wait -Tail 50

# Check for any ERROR lines since restart
$restart_time = Get-Date  # record before restart
# After restart:
Get-Content "C:\PZ\logs\pz_stderr.log" -Tail 100 | Where-Object { $_ -match "ERROR|CRITICAL|Exception" }
```

### Continuous smoke monitoring (optional, post-activation)

```powershell
# Run smoke tests every 5 minutes for 30 minutes after activation
python scripts\lifecycle_smoke_tests.py --batch $batch_id --watch --interval 300
```

### Alert thresholds

| Metric | Alert if |
|--------|----------|
| Health endpoint | Returns non-200 for more than 2 consecutive checks |
| correction-commit | Returns any 2xx response — CRITICAL |
| pz_stderr.log | Any new ERROR line after restart |
| Service state | Any state other than RUNNING |

### Escalation path

If an alert fires during activation:

1. **Service unhealthy or crashed** → Manual rollback (procedure above) → Notify operator
2. **correction-commit returns 2xx** → Emergency rollback immediately → Investigate whether wFirma was called → Document
3. **State machine in unexpected state** → Do not suppress → Take a screenshot of the response → Rollback → Investigate before any retry
4. **Cannot rollback via script** → Stop service (`the service stop step PZService`) → Manually restore checkpoint `.bak` file → Start service → Verify health

---

## Automation Companion Scripts

All scripts in `service/scripts/`. Run from elevated PowerShell with working directory `C:\PZ`.

| Script | Purpose | Key flags |
|--------|---------|-----------|
| `env_config_manager.ps1` | .env flag management, checkpoints, service restart | `-Action Show\|ActivateLifecycle\|RollbackLifecycle\|AssertHealth\|AssertPushOff\|Checkpoint\|RestartService\|FullGate` |
| `activate_pz_lifecycle.py` | Full Python automation of this runbook | `--execute` (live), `--rollback`, `--smoke-batch BATCH_ID` |
| `lifecycle_smoke_tests.py` | Smoke tests for all lifecycle endpoints | `--batch ID`, `--full-lifecycle`, `--watch`, `--json-metrics` |

**Dry-run first, always:**

```powershell
python scripts\activate_pz_lifecycle.py              # prints plan, writes nothing
python scripts\activate_pz_lifecycle.py --execute    # executes live
```

---

## Completion Checklist

```
PHASE 1 ACTIVATION — FINAL COMPLETION RECORD
=============================================
Date/Time completed:          ____________________________
Operator who ran activation:  ____________________________
Test batch_id used:           ____________________________
Checkpoint file created:      ____________________________

Steps completed:
  [ ] Step 1 — PZ_CORRECTION_LIFECYCLE_ENABLED=true written to .env
  [ ] Step 2 — PZService restarted, health 200
  [ ] Step 3 — correction-state smoke test PASSED on real Global batch
  [ ] Step 4 — Stage/reset/suppress PASSED; KEEP_CURRENT/NO_ACTION 409 PASSED
  [ ] DECISION GATE — Operator acknowledged all Step 4 results
  [ ] Step 5 — WFIRMA_CORRECTION_PUSH_ALLOWED confirmed absent/false
  [ ] Step 6 — Checkpoint created, Phase 2 decision criteria documented

Post-activation state:
  PZ_CORRECTION_LIFECYCLE_ENABLED  = true
  WFIRMA_CORRECTION_PUSH_ALLOWED   = false (absent)
  PZService                        = RUNNING
  correction-commit reachability   = BLOCKED (push flag off)
  wFirma write path                = UNREACHABLE

Phase 1 verdict: COMPLETE / ROLLED BACK (circle one)

If ROLLED BACK — reason: ________________________________________
```
