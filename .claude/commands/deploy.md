# /deploy — Production Deploy Command

Triggers the full production deployment procedure defined in `service/docs/production_deployment_rule.md`.

**Never skip any step. Never skip the 7-agent gate.**

---

## Step 1 — Inspect

```powershell
cd "C:\PZ-verify"
git status
git branch --show-current
git fetch origin
git log --oneline HEAD..origin/main
git diff --name-status HEAD..origin/main
```

Stop immediately if:
- Working tree is dirty
- Branch is not `main`
- Any merge conflict detected

---

## Step 2 — Run 7-agent pre-deploy gate (parallel)

Spawn all 7 agents simultaneously with the diff output from Step 1.

| # | Agent file | Focus |
|---|-----------|-------|
| 1 | `.claude/agents/deploy_lead_coordinator.md` | Go/no-go, conflict resolution |
| 2 | `.claude/agents/deploy_git_diff_reviewer.md` | File classification, forbidden paths |
| 3 | `.claude/agents/deploy_backend_impact_reviewer.md` | Route changes, auth, imports |
| 4 | `.claude/agents/deploy_persistence_storage_reviewer.md` | DB schema, storage writes |
| 5 | `.claude/agents/deploy_security_reviewer.md` | Credentials, auth removal, injection |
| 6 | `.claude/agents/deploy_qa_reviewer.md` | Test pass/fail, regression risk |
| 7 | `.claude/agents/deploy_release_manager.md` | Branch hygiene, rollback command |

Wait for all 7 findings. Do not proceed until Lead Coordinator issues written approval.

---

## Step 3 — Pull

```bash
git pull --ff-only origin main
git rev-parse HEAD
```

---

## Step 4 — Test

```powershell
cd "C:\PZ-verify"
$env:PYTHONIOENCODING = "utf-8"
python test_pz_regression.py
```

```powershell
cd "C:\PZ-verify\service"
python -m pytest tests/test_carrier_*.py -q
```

Required: counts per `.claude/contracts/test-baseline.md`. Stop if any test fails.

---

## Step 5 — Safe sync to production

```powershell
robocopy "C:\PZ-verify\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache storage `
  /XF "*.pyc" "*.pyo" "*.zip"
```

Exit codes 0–3 = success. Exit 4+ = error, stop immediately.

**Never use `/MIR`. Never sync `.env`, `storage\`, `logs\`, `cloudflared\`.**

---

## Step 6 — Restart PZService (requires elevated Administrator shell)

```powershell
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) { Start-Sleep -Seconds 1; $tries++ }
sc.exe start PZService
Start-Sleep -Seconds 10
sc.exe query PZService
```

---

## Step 7 — Post-deploy verification

### 7a — Liveness (no credentials needed)

The root path is unauthenticated. These are the same two probes
`verify_deploy_close.ps1` uses for conditions 6 and 7.

```powershell
Invoke-WebRequest 'http://127.0.0.1:47213/'       -UseBasicParsing -TimeoutSec 10
Invoke-WebRequest 'https://pz.estrellajewels.eu/' -UseBasicParsing -TimeoutSec 15
```

Both must return 200.

### 7b — API health (REQUIRES the API key)

`/api/v1/*` sits behind `require_api_key`. A bare `Invoke-WebRequest` with no
header returns **401**, and PowerShell throws on 4xx — so an unauthenticated
probe looks like a deploy failure when it is only a missing header. Load the
key from `.env` into a variable; never echo it.

```powershell
$k = (Select-String -Path C:\PZ\.env -Pattern '^API_KEY=' | Select-Object -First 1).Line -replace '^API_KEY=',''
$h = @{ 'X-API-Key' = $k }

Invoke-WebRequest 'http://127.0.0.1:47213/api/v1/health'         -Headers $h -UseBasicParsing -TimeoutSec 25
Invoke-WebRequest 'https://pz.estrellajewels.eu/api/v1/health'   -Headers $h -UseBasicParsing -TimeoutSec 25
Invoke-WebRequest 'http://127.0.0.1:47213/api/v1/carrier/status' -Headers $h -UseBasicParsing -TimeoutSec 25
```

All three must return 200.

### 7c — Carrier gate probe — READ BEFORE RUNNING

> **Do NOT send a well-formed shipment payload.**
> Production runs with `carrier_api_status='live'` and
> `carrier_live_allowlist='*'`. A schema-valid POST passes the gate, reaches
> the DHL adapter, and can **create a real shipment**. The payload previously
> printed in this runbook was schema-valid and must not be used.
>
> The old "must return 503" expectation is wrong on this host: 503 fires only
> when `carrier_api_status='pending'`, which is not the production setting.

Use a deliberately **schema-invalid** body so FastAPI rejects it at validation
(**422**) before any gate or adapter is reached:

```powershell
try {
    Invoke-WebRequest 'http://127.0.0.1:47213/api/v1/carrier/STAGE0-TEST/shipment' `
      -Method POST -Headers $h -Body '{"__invalid_probe__":true}' `
      -ContentType 'application/json' -UseBasicParsing -TimeoutSec 25
    Write-Host "UNEXPECTED: invalid probe was accepted - investigate before closing" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Write-Host "carrier probe -> $code  (expect 422)"
}
```

Expected: **422**. Anything else — especially a 2xx — means the invalid body
was accepted; stop and investigate before closing the deploy.

### 7d — Version marker and logs

```powershell
python -c "d=open(r'C:\PZ\version.txt','rb').read(); print('BOM!' if d[:3]==b'\xef\xbb\xbf' else 'no-bom', d.decode('utf-8-sig'))"
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20
```

`version.txt` must print `no-bom` and match the deployed SHA. The log tail must
show `Application startup complete` and no traceback.

---

## Step 8 — Close-condition gate

After all steps above complete, run the reusable verification script to
confirm all 8 close conditions pass before marking the deploy closed.

```powershell
cd "C:\PZ-verify"
.\.claude\manifests\verify_deploy_close.ps1 -ExpectedSHA <SHA>
```

Exit 0 = all 8 conditions passed — deploy is closed.
Exit 1 = one or more conditions failed — do not mark closed, investigate output.

Use `-SkipRobocopy` if the robocopy sync was already run in Step 5 and you
only want to verify the post-deploy state.

---

## Required output

```
Pulled SHA:
Tests:           PZ regression [x/160]  Carrier [x/604]  PZ suite [x/257]
Sync result:     robocopy exit [n]
Service status:  [RUNNING | ERROR]
Root liveness:   local [200] public [200]          (7a, unauthenticated)
API health:      local [200] public [200]          (7b, with X-API-Key)
Carrier status:  [200 | other]
Carrier probe:   [422 expected | other]            (7c, schema-invalid body)
version.txt:     [no-bom + matches SHA | PROBLEM]
Backup path:     C:\PZ\bak\app-pre-deploy-<ts>     (restores the PREVIOUS SHA)
Rollback:        robocopy <backup> C:\PZ\app /E  +  restart PZService
READY / BLOCKED:
```

Carrier floor is **604** per the table in `.claude/contracts/test-baseline.md`,
which is the single source of truth. `git revert` is deliberately NOT the
rollback line: it rewrites the repo, not `C:\PZ`, and production is not a git
checkout. Rollback is a robocopy restore from the pre-deploy backup taken in
Step 5, followed by a service restart.
