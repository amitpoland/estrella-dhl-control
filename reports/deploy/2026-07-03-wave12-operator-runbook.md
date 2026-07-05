# Wave 1+2 Production Deploy — Operator Runbook (candidate 84c292de) — CORRECTED FINAL

> **🔴 NO AUTOMATED DB BACKUP EXISTS ON THIS HOST** (`EstrellaDBBackup`
> schtask absent, verified 2026-07-03). Section 1 IS the backup — a production
> migration without it is FORBIDDEN. If Section 1 fails, STOP; nothing else runs.

- **Source:** `C:\PZ-deploy-w12` (clean worktree @ `84c292de`). Never deploy from `C:\PZ-verify`.
- **Target:** `C:\PZ` · service `PZService` (NSSM, :47213) · prod base `c7c0e14e`.
- Elevated PowerShell, sections in order. Every step operator-only (pz-deploy-guard).
- Engine sync NOT required (root engine files unchanged in range). requirements.txt unchanged.
- All commands verified against SHA `84c292de`:
  mirror backfill = `service/app/services/reservation_db.py:260`
  `backfill_product_authority(reservation_db_path, wfirma_db_path, master_data_db_path, *, now_iso)` ·
  migrations = both drafts accept `<db> up` (returns :149-157, sample :144-152) ·
  registry tool = `--storage-root` required (tools/backfill_service_product_registry.py:64-65).
  Do NOT use `POST /api/v1/admin/product-master/backfill` for Section 4 — a different
  backfill (invoice-lines projection, session-cookie auth) that never touches the mirror.

---

## 1 — Backup (mandatory; auto-aborts on any failure)

```powershell
& {
  $stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
  $global:bakdir = "C:\PZ-backups\db-pre-wave12-$stamp"
  New-Item -ItemType Directory -Force $bakdir | Out-Null
  sc.exe stop PZService | Out-Null; Start-Sleep 8
  Get-ChildItem "C:\PZ\app\storage" -File |
    Where-Object { $_.Name -match '\.(db|sqlite)(-wal|-shm)?$' } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $bakdir ($_.Name + ".bak")) }
  $src = Get-ChildItem "C:\PZ\app\storage" -File | Where-Object { $_.Name -match '\.(db|sqlite)(-wal|-shm)?$' }
  foreach ($f in $src) {
    $b = Join-Path $bakdir ($f.Name + ".bak")
    if (-not (Test-Path $b) -or ((Get-Item $b).Length -ne $f.Length)) { throw "BACKUP FAILED: $($f.Name) - STOP" }
  }
  robocopy "C:\PZ\app" "C:\PZ-backups\app-pre-wave12-$stamp" /E /XD __pycache__ storage /XF *.pyc /NFL /NDL /NP | Out-Null
  if ($LASTEXITCODE -ge 4) { throw "CODE BACKUP FAILED ($LASTEXITCODE) - STOP" }
  Write-Host "BACKUP VERIFIED: $($src.Count) DB files + code -> $bakdir" -ForegroundColor Green
}
```

## 2 — Sync + verification (single block; auto-aborts unless SYNC VERIFIED)

```powershell
& {
  sc.exe query PZService | Select-String STATE   # must show STOPPED
  robocopy "C:\PZ-deploy-w12\service\app" "C:\PZ\app" /E /XD __pycache__ .pytest_cache storage /XF *.pyc *.pyo *.zip
  if ($LASTEXITCODE -ge 4) { throw "ROBOCOPY FAILED (exit $LASTEXITCODE) - ABORT" }
  python "C:\PZ-verify\reports\deploy\verify_sync.py"
  if ($LASTEXITCODE -ne 0) { throw "SYNC NOT VERIFIED - ABORT. Re-run this block; do NOT run Section 3." }
  Write-Host "SYNC VERIFIED - continue with Section 3" -ForegroundColor Green
}
```

Gate conditions (all enforced by `verify_sync.py`, which exits non-zero otherwise):
MISSING=0 · DIFF=0 · `main.py` MATCH · `services\reservation_db.py` MATCH ·
`api\routes_proforma.py` MATCH.

## 3 — Migrations (idempotent; service still STOPPED)

```powershell
python "C:\PZ-deploy-w12\service\app\db\migrations\draft_20260512_175238_returns_events.py.draft"    "C:\PZ\app\storage\warehouse.db" up
python "C:\PZ-deploy-w12\service\app\db\migrations\draft_20260512_122327_sample_out_events.py.draft" "C:\PZ\app\storage\warehouse.db" up
# Each prints "Created ..." or "... already exists" — anything else = STOP -> Section 7
```

## 4 — Mirror backfill → collision report (service still STOPPED)

```powershell
cd C:\PZ
python -c "from pathlib import Path; from datetime import datetime, timezone; from app.services.reservation_db import backfill_product_authority; sr = Path(r'C:\PZ\app\storage'); print(backfill_product_authority(sr / 'reservation_queue.db', sr / 'wfirma.db', sr / 'master_data.db', now_iso=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))" | Tee-Object "$bakdir\mirror-backfill-collision-report.txt"
```

⛔ **STOP:** `wfirma_id_collisions > 0` (goods-id 99 expected: EJL/26-27/254-1 vs
EJL/26-27/257-2). Paste the report to the session — evidence + recommendation
per row comes back; you rule per row; fix the loser's mapping; re-run this
section (idempotent) until collisions = 0.

## 5 — Registry backfill (service still STOPPED)

```powershell
python "C:\PZ-deploy-w12\service\tools\backfill_service_product_registry.py" --storage-root C:\PZ\app\storage
```

⛔ **STOP:** `copied` EMPTY on prod → do NOT start the service; paste the output.

## 6 — Restart + health

```powershell
sc.exe start PZService; Start-Sleep 10; sc.exe query PZService | Select-String STATE   # RUNNING
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -UseBasicParsing | Select-Object StatusCode
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20
```

Then reply to the session: `deployed` — or paste any STOP output.

If any earlier attempt partially ran: after Section 2 verifies, Sections 3–5
re-run in full, in order — idempotent steps are safe, skipped code is not.

## 7 — Rollback

```powershell
sc.exe stop PZService
robocopy "C:\PZ-backups\app-pre-wave12-<stamp>" "C:\PZ\app" /E /XD storage
# DBs only if a migration/backfill must be undone (schema is additive; old code ignores new tables):
#   copy the needed .bak files from $bakdir back over C:\PZ\app\storage\
sc.exe start PZService
```
