# Windows Deploy Runbook — Standard Template

Every deploy to `C:\PZ` on the production Windows box follows this template.
Each numbered step is mandatory; steps marked **OPERATOR** require a human to read the output
and make a go/no-go decision before proceeding.

---

## 0. Pre-deploy: disable the health watchdog

**Do this FIRST, before any snapshot or the application sync.**

```powershell
schtasks /Change /TN "PZService-HealthWatchdog" /DISABLE
```

**Why:** The watchdog probes `http://127.0.0.1:47213/login` every 60 s and restarts
PZService on 2 consecutive misses. A probe firing during the application sync (service momentarily
unresponsive) or during the deploy's own `sc.exe restart` creates two restart authorities
racing against an in-progress file copy — the "serve half-written files" failure class.

**Task name must be exact:** `PZService-HealthWatchdog` (confirm with
`schtasks /Query /FO LIST | Select-String TaskName | Where-Object { $_ -match 'PZService' }`).
A `/Change` against a wrong name fails **silently** — the watchdog stays armed.

---

## 1. Sync VERIFY_DIR

```powershell
Set-Location "C:\PZ-verify"
git fetch origin
git reset --hard origin/main
git log -1 --oneline   # confirm expected merge commit is HEAD
```

---

## 2. Snapshot EVERY file being modified (before touching prod)

```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
# Repeat for each file being deployed:
Copy-Item "C:\PZ\app\...\<file>" "C:\PZ\app\...\<file>.bak-$ts" -Force
# NEW files have no snapshot — rollback = Remove-Item
```

Record `$ts` — needed for `ROLLBACK` at the end.

---

## 3. Fingerprint EXPECTED from VERIFY_DIR

```powershell
$EXPECTED_<X> = (Get-FileHash "C:\PZ-verify\service\app\...\<file>" -Algorithm SHA256).Hash
Write-Output "EXPECTED: $EXPECTED_<X>"
```

Compute one hash per file being deployed.

---

## 4. the application sync

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


---

## 5. Restart PZService (ONLY if backend changed; skip for static-only deploys)

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


If not STATE 4 RUNNING: run **ROLLBACK** immediately — do not proceed.

---

## 6. Hash gate (OPERATOR reads both lines)

```powershell
$ACTUAL_<X> = (Get-FileHash "C:\PZ\app\...\<file>" -Algorithm SHA256).Hash
Write-Output "EXPECTED: $EXPECTED_<X>"
Write-Output "ACTUAL  : $ACTUAL_<X>"
```

**OPERATOR:** `EXPECTED == ACTUAL` for every file → proceed.
Any mismatch → **ROLLBACK** immediately.

---

## 7. Re-enable the health watchdog (SUCCESS PATH)

```powershell
schtasks /Change /TN "PZService-HealthWatchdog" /ENABLE
```

**Must run LAST, after STATE 4 confirmed + hash gates passed.**
A re-armed watchdog on a healthy service is the intended end-state.

---

## 8. Post-deploy smokes

Minimum smokes after every backend restart:

```powershell
# Bare call must 401 (enforcement active):
try { Invoke-WebRequest -Uri "http://127.0.0.1:47213/api/v1/customer-master/" -UseBasicParsing -ErrorAction Stop }
catch { Write-Output "Bare call: $($_.Exception.Response.StatusCode.value__)" }   # expect 401

# Cookie path must 200 (UI not locked out):
# Load /v2/proforma in browser -> confirm drafts render, no 401.
```

Run any PR-specific smokes (render gate, API smoke, etc.) from the PR's runbook.

---

## ROLLBACK (any step fails)

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


**The watchdog ENABLE is the first rollback step** so that a deploy that aborts
after DISABLE but before the normal ENABLE does not leave production unmonitored.

---

## Deploy log

Append one single-line JSON to `C:\PZ-verify\.claude\memory\local-commit-deploys.jsonl`
after confirming all smokes pass:

```json
{
  "timestamp": "<ISO-8601>",
  "sha": "<post-merge-main-SHA>",
  "pr": <N>,
  "files_deployed": ["service/app/.../file.py"],
  "prod_hash_<x>": "<SHA256>",
  "prod_size_<x>": <bytes>,
  "restart": true,
  "watchdog_disabled_during_deploy": true,
  "environment": "windows-prod",
  "deployed_at": "<ISO-8601>",
  "gate_mode": "standard",
  "note": "..."
}
```

`prod_size_bytes` as a bare number (not quoted). Secret values never in the log.
Append locally only — batch into the next docs PR.

---

## Checklist summary (copy per deploy)

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.

