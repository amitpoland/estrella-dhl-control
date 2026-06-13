# Production Deployment Rule
**Status:** PERMANENT — applies to every deployment, every session  
**Date installed:** 2026-05-10  
**Scope:** All Git-based updates to the Windows production PZ app

---

## Production identity

| Item | Value |
|------|-------|
| Production host | Windows machine (local) |
| Live app root | `C:\PZ` |
| Service | `PZService` (NSSM, port 47213) |
| Public URL | `https://pz.estrellajewels.eu` |
| Git repo (verify) | `C:\PZ-verify` (canonical — `C:\Users\Super Fashion\PZ APP` RETIRED 2026-06-04) |
| Production secrets | `C:\PZ\.env` |
| Production data | `C:\PZ\storage` |
| Production logs | `C:\PZ\logs` |
| Carrier gate default | `pending` (closed) |

The git repository is a **staging workspace only**.  
`C:\PZ` is **production** — treat it as untouchable except through the controlled sync path below.

---

## Permanent discipline (10 rules, no exceptions)

1. **No direct coding inside `C:\PZ`.**  All code changes happen in the git repo.
2. **No manual production edits** except emergency rollback documented below.
3. **No `git pull` directly followed by sync.**  Agents inspect first; sync second.
4. **No sync before agents inspect changed files.**  The 7-agent gate is mandatory.
5. **No restart before rollback path is defined.**  Rollback command must be written down first.
6. **No deletion, overwrite, or mirror copy.**  Additive sync only.
7. **Never use `robocopy /MIR`.**  Forbidden without exception.
8. **Never overwrite these production paths:**
   - `C:\PZ\.env`
   - `C:\PZ\storage\`
   - `C:\PZ\logs\`
   - `C:\PZ\cloudflared\`
   - Any `*.db` file
   - Any `outputs\` subdirectory
9. **Always preserve carrier gate** (`carrier_api_status=pending`) unless explicit activation is separately approved by the coordinator.
10. **Always verify public health** (`https://pz.estrellajewels.eu/api/v1/health`) after every deploy.

---

## 7-Agent pre-deploy gate

Every deployment **must** run these agents before any sync or restart.  
All 7 agents run in parallel.  No deployment proceeds until all 7 return clear.

| # | Agent | File | Focus |
|---|-------|------|-------|
| 1 | Lead Coordinator | `deploy_lead_coordinator.md` | Go/no-go, conflict resolution, final approval |
| 2 | Git/Diff Reviewer | `deploy_git_diff_reviewer.md` | Changed files, risk classification, migration flags |
| 3 | Backend Impact Reviewer | `deploy_backend_impact_reviewer.md` | Route changes, service imports, breaking changes |
| 4 | Persistence/Storage Reviewer | `deploy_persistence_storage_reviewer.md` | DB schema, storage writes, migration requirements |
| 5 | Security Reviewer | `deploy_security_reviewer.md` | Auth, secrets, injection, credential exposure |
| 6 | QA Reviewer | `deploy_qa_reviewer.md` | Test coverage, regression risk, pass/fail |
| 7 | Release Manager | `deploy_release_manager.md` | Branch hygiene, rollback command, sync plan |

**Deployment can proceed only if:**
- [ ] Working tree is clean (`git status` shows no staged/unstaged changes)
- [ ] All 7 agents have returned findings
- [ ] No agent has raised a blocker
- [ ] Tests pass (PZ regression 160/160, carrier suite 366/366)
- [ ] No data-loss risk identified
- [ ] Rollback command is written and verified
- [ ] Lead Coordinator has issued written approval

---

## Deployment procedure (every time)

### Step 1 — Inspect

```bash
git status                                    # must be clean
git branch --show-current                     # must be main
git fetch origin
git log --oneline HEAD..origin/main           # commits to pull
git diff --name-status HEAD..origin/main      # files changed
```

**Stop immediately if:**
- Working tree is dirty
- Branch is not `main`
- Merge conflicts detected

### Step 2 — Run 7-agent gate

Spawn all 7 pre-deploy agents in parallel with the diff output.  
Wait for all findings.  Resolve any blockers before proceeding.

### Step 3 — Pull

```bash
git pull --ff-only origin main    # fast-forward only, never merge commit
git rev-parse HEAD                # record exact deployed SHA
```

### Step 4 — Test

```bash
# PZ regression
cd "C:\PZ-verify"
PYTHONIOENCODING=utf-8 python test_pz_regression.py    # must be 160/160

# Carrier suite
cd service
python -m pytest tests/test_carrier_*.py -q            # must be 412/412
```

**Stop if any test fails.**

### Step 4.5 — Pre-deploy backup

```powershell
# Create backup before any production changes
cd "C:\PZ\service"
python scripts\run_backup.py --backup-root "C:\PZ-backups"
```

**Abort deploy on backup failure.** Maximum timeout: 10 minutes. If backup fails or times out, investigate storage health before proceeding. A failed backup means restore capability is compromised.

### Step 5 — Safe sync to production

```powershell
# Allowed: /E /XO (newer-only, no deletes, no overwrite)
robocopy "C:\PZ-verify\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache storage `
  /XF "*.pyc" "*.pyo" "*.zip"

# Robocopy exit codes: 0=nothing to copy, 1=copied, 2=extras retained, 3=both
# All are SUCCESS.  Exit 4+ = error, stop immediately.
```

**Forbidden sync operations:**
```
robocopy /MIR                            ← NEVER
robocopy ... C:\PZ\.env                  ← NEVER
robocopy ... C:\PZ\storage               ← NEVER
robocopy ... C:\PZ\logs                  ← NEVER
robocopy ... C:\PZ\cloudflared           ← NEVER
Copy-Item -Recurse (without -Force /XO)  ← NEVER without review
```

### Step 6 — Restart PZService (as Administrator)

```powershell
# Must be run from an elevated (Administrator) PowerShell session
sc.exe stop PZService
timeout /t 8 /nobreak
sc.exe start PZService
timeout /t 10 /nobreak
sc.exe query PZService    # verify STATE: RUNNING
```

### Step 7 — Post-deploy verification

```powershell
# Local health
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health

# Public health (must return 200)
Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health

# Carrier gate (must return pending unless activation separately approved)
Invoke-WebRequest http://127.0.0.1:47213/api/v1/carrier/status

# Closed-gate POST (must return 503 if carrier_api_status=pending)
Invoke-WebRequest http://127.0.0.1:47213/api/v1/carrier/STAGE0-TEST/shipment `
  -Method POST -Body '{"shipper_account":"TEST","recipient_address":{},"declared_value":100,"currency":"EUR","weight_kg":1,"dimensions":{}}' `
  -ContentType "application/json"

# Check logs for fresh traceback
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20
```

---

## Rollback procedures

### Level 1 — Gate-only rollback (instant, no code change)
Revert carrier status to pending via `.env` and restart.

### Level 2 — Revert last commit
```bash
git revert HEAD --no-edit
# then re-run deploy procedure from Step 5
```

### Level 3 — Revert a named merge
```bash
git revert -m 1 <merge-commit-sha> --no-edit
# then re-run deploy procedure from Step 5
```

### Emergency — restore from git directly
```bash
git checkout <last-known-good-sha> -- service/app/
# then robocopy /E /XO to C:\PZ\app, then restart
```

---

## Required output format for every deployment

```
Pulled SHA:
Tests:
Sync result:
Service status:
Local health:
Public health:
Carrier gate:
Production mutation:
Rollback command:
Final decision:
READY / BLOCKED:
```

---

## Carrier activation — separate protocol

Setting `CARRIER_API_STATUS=shadow` or `CARRIER_API_STATUS=live` in `C:\PZ\.env`
**requires separate coordinator sign-off** per `carrier_production_activation_protocol.md`.
It is not part of the standard deployment procedure.
