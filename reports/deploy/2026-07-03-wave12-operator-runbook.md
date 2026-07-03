# Wave 1+2 Production Deploy — Operator Runbook (84c292de)

Gate: 7-agent READY-TO-DEPLOY (2026-07-03) · Lesson-D acknowledged
("I acknowledge LOCAL-COMMIT-ONLY") · CP4 payload = service/docs/ops/c3g-deploy-note.md.
Source: **C:\PZ-deploy-w12** (clean worktree @ 84c292de). Target: C:\PZ (PZService :47213).
Prod base: c7c0e14e. The pz-deploy-guard makes every step below OPERATOR-ONLY —
run in an **elevated** PowerShell, one block at a time.

## 0 — Backup (abort if it fails)

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
robocopy "C:\PZ\app" "C:\PZ-backups\app-pre-wave12-$stamp" /E /XD __pycache__ storage /XF *.pyc /NFL /NDL /NP
# exit codes 0-3 = OK
```

## 1 — Stop the service

```powershell
sc.exe stop PZService; Start-Sleep 8; sc.exe query PZService   # expect STOPPED
```

## 2 — Sync (NO /MIR; storage excluded)

```powershell
robocopy "C:\PZ-deploy-w12\service\app" "C:\PZ\app" /E /XO /XD __pycache__ .pytest_cache storage /XF *.pyc *.pyo *.zip
# exit codes 0-3 = OK; 4+ = STOP, do not start the service
```

Engine sync NOT required (Lesson J check: engine files unchanged in range).

## 3 — Ritual step A: mirror backfill + COLLISION STOP

```powershell
cd C:\PZ
python -c "from pathlib import Path; from datetime import datetime, timezone; from app.services.reservation_db import backfill_product_authority; sr = Path(r'C:\PZ\app\storage'); print(backfill_product_authority(sr / 'reservation_queue.db', sr / 'wfirma.db', sr / 'master_data.db', now_iso=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))"
```

**STOP CONDITION:** if the printed dict shows `wfirma_id_collisions > 0` — do NOT
start the service; bring the collision list back to the session (known candidate:
EJL/26-27/254-1 vs EJL/26-27/257-2 both claiming goods id 99; decide which code
truly owns it in wFirma, fix the loser's mapping, re-run step 3 — idempotent).

## 4 — Ritual step B: service-charge registry backfill + EMPTY STOP

```powershell
python C:\PZ-deploy-w12\service\tools\backfill_service_product_registry.py --storage-root C:\PZ\app\storage
```

**STOP CONDITION:** if `copied` is EMPTY on prod — do NOT start; investigate
(freight/insurance labels would degrade to the fallback "freight").

## 5 — Ritual step C: returns_events migration (idempotent)

```powershell
python "C:\PZ-deploy-w12\service\app\db\migrations\draft_20260512_175238_returns_events.py.draft" "C:\PZ\app\storage\warehouse.db" up
```

## 6 — Start + verify

```powershell
sc.exe start PZService; Start-Sleep 10; sc.exe query PZService   # expect RUNNING
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health | Select-Object StatusCode
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20   # no new Tracebacks
```

Then tell the session "deployed" — it runs the remaining read-only verification
(public health, carrier gate 503-closed, service-products smoke vs pre-deploy,
version/deploy records, local-commit-deploys.jsonl append) and, on green,
**Wave 3 starts per your ruling** (already ratified for post-deploy).

## Rollback (if anything goes wrong)

```powershell
sc.exe stop PZService
robocopy "C:\PZ-backups\app-pre-wave12-<stamp>" "C:\PZ\app" /E /XD storage
sc.exe start PZService
```
(git-level: `git revert -m 1 84c292de` on the campaign branch; schema is additive —
old code ignores the new tables.)
