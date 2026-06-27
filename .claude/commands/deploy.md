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

```powershell
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health
Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health
Invoke-WebRequest http://127.0.0.1:47213/api/v1/carrier/status
Invoke-WebRequest http://127.0.0.1:47213/api/v1/carrier/STAGE0-TEST/shipment `
  -Method POST -Body '{"shipper_account":"TEST","recipient_address":{},"declared_value":100,"currency":"EUR","weight_kg":1,"dimensions":{}}' `
  -ContentType "application/json"
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20
```

Carrier gate POST must return 503 (gate closed).

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
Tests:           PZ [x/160]  Carrier [x/469]
Sync result:     robocopy exit [n]
Service status:  [RUNNING | ERROR]
Local health:    [200 | ERROR]
Public health:   [200 | ERROR]
Carrier gate:    [pending | other]
Gate POST 503:   [yes | no]
Rollback:        git revert <sha> --no-edit
READY / BLOCKED:
```
