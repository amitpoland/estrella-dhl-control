# Wave 1+2 Production Deploy — THE Operator Runbook (candidate 84c292de)

> **🔴 RED — NO AUTOMATED DB BACKUP EXISTS ON THIS HOST.**
> The scheduled task **`EstrellaDBBackup` DOES NOT EXIST** (verified
> 2026-07-03: `schtasks /query /tn EstrellaDBBackup` → not found; only
> unrelated Windows system backup tasks are registered). **A production
> migration without a fresh backup is FORBIDDEN by this runbook.** Section 1
> below IS the backup — it must complete with every file verified before any
> later section may run. If Section 1 fails, STOP; nothing else runs.

Gate: 7-agent **READY-TO-DEPLOY** (2026-07-03) · Lesson-D LOCAL-COMMIT-ONLY
disclosure acknowledged · CP4/CP5 payload. Wave order (operator verdict,
verbatim): *"Wave 3 begins only after: (1) Production deploy (2) Post-deploy
verification (3) Mirror collision report clean (4) Wave 3 ratification.
This order will not change."*

- **Source:** `C:\PZ-deploy-w12` — clean worktree @ `84c292de`
  (deploy/latest ⊕ origin/main #809–#814, zero conflicts). Never deploy from
  `C:\PZ-verify` (operator-dirty files must not ship).
- **Target:** `C:\PZ` · service `PZService` (NSSM, port 47213) · prod base
  fingerprinted `c7c0e14e`.
- Every step is **OPERATOR-ONLY** (pz-deploy-guard). Elevated PowerShell,
  one block at a time, in order. Engine sync NOT required (Lesson J: root
  engine files unchanged in range). No requirements.txt change in range.

---

## 1 — PRE-DEPLOY: backup + baseline capture (FIRST; abort on any failure)

### 1a. Full DB file-copy set → named `.bak` paths

```powershell
$stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$bakdir = "C:\PZ-backups\db-pre-wave12-$stamp"
New-Item -ItemType Directory -Force $bakdir | Out-Null
# Stop the service FIRST so WAL files are quiesced and copies are consistent:
sc.exe stop PZService; Start-Sleep 8; sc.exe query PZService   # expect STOPPED
Get-ChildItem "C:\PZ\app\storage" -File |
  Where-Object { $_.Name -match '\.(db|sqlite)(-wal|-shm)?$' } |
  ForEach-Object { Copy-Item $_.FullName (Join-Path $bakdir ($_.Name + ".bak")) }
# VERIFY: every source file has a .bak with identical size
$src = Get-ChildItem "C:\PZ\app\storage" -File | Where-Object { $_.Name -match '\.(db|sqlite)(-wal|-shm)?$' }
$ok  = $true
foreach ($f in $src) {
  $b = Join-Path $bakdir ($f.Name + ".bak")
  if (-not (Test-Path $b) -or ((Get-Item $b).Length -ne $f.Length)) { $ok = $false; Write-Host "MISSING/SIZE-MISMATCH: $($f.Name)" -ForegroundColor Red }
}
if ($ok) { Write-Host "BACKUP VERIFIED: $($src.Count) files -> $bakdir" -ForegroundColor Green } else { Write-Host "BACKUP FAILED - STOP. Do not proceed." -ForegroundColor Red }
```

**STOP CONDITION:** anything other than the green `BACKUP VERIFIED` line.
Expected set (18 DB files as of 2026-07-03 + any WAL/SHM sidecars):
correction_registry.db · customer_master.db · customer_master.sqlite ·
documents.db · intake_lineage.db · master_audit.sqlite · master_data.sqlite ·
packing.db · packing_resolutions.sqlite · proforma_links.db ·
reservation_queue.db · suppliers.sqlite · tracking_events.db · users.db ·
warehouse.db · warehouse_receipt.db · wfirma.db · wfirma_webhook_events.db.

### 1b. Code backup

```powershell
robocopy "C:\PZ\app" "C:\PZ-backups\app-pre-wave12-$stamp" /E /XD __pycache__ storage /XF *.pyc /NFL /NDL /NP
# robocopy exit codes 0-3 = OK; anything else = STOP
```

### 1c. Pre-deploy proforma baseline (for the production output-equivalence diff)

The service is stopped; start it briefly on OLD code to capture the baseline,
then stop it again:

```powershell
sc.exe start PZService; Start-Sleep 10
# Pick ONE recent real batch/client you know (ideally one carrying freight/insurance
# charges). To list candidates:
Invoke-RestMethod -Headers @{"X-API-KEY"=$env:PZ_API_KEY} "http://127.0.0.1:47213/api/v1/proforma/drafts/recent?limit=10" | ConvertTo-Json -Depth 4
# Capture the baseline preview (REPLACE <BATCH> and <CLIENT>):
Invoke-RestMethod -Method Post -Headers @{"X-API-KEY"=$env:PZ_API_KEY} `
  "http://127.0.0.1:47213/api/v1/proforma/preview/<BATCH>/<CLIENT>" |
  ConvertTo-Json -Depth 8 | Out-File "$bakdir\preview-pre-deploy.json" -Encoding utf8
# Also capture the service-products mapping state:
Invoke-RestMethod -Headers @{"X-API-KEY"=$env:PZ_API_KEY} `
  "http://127.0.0.1:47213/api/v1/proforma/service-products" |
  ConvertTo-Json -Depth 5 | Out-File "$bakdir\service-products-pre-deploy.json" -Encoding utf8
sc.exe stop PZService; Start-Sleep 8; sc.exe query PZService   # expect STOPPED
```

---

## 2 — DEPLOY STEPS (exact order; service stays STOPPED throughout)

### 2a. Code sync (NO /MIR; storage excluded)

```powershell
robocopy "C:\PZ-deploy-w12\service\app" "C:\PZ\app" /E /XO /XD __pycache__ .pytest_cache storage /XF *.pyc *.pyo *.zip
# exit codes 0-3 = OK; 4+ = STOP, go to Section 5 (Rollback)
```

### 2b. Event-table migrations (idempotent; returns + sample)

```powershell
python "C:\PZ-deploy-w12\service\app\db\migrations\draft_20260512_175238_returns_events.py.draft"    "C:\PZ\app\storage\warehouse.db" up
python "C:\PZ-deploy-w12\service\app\db\migrations\draft_20260512_122327_sample_out_events.py.draft" "C:\PZ\app\storage\warehouse.db" up
# Both print "Created ..." or "... already exists" — anything else = STOP → Rollback
```

### 2c. C-1a product-authority backfill re-run → **collision report to file**

```powershell
cd C:\PZ
python -c "from pathlib import Path; from datetime import datetime, timezone; from app.services.reservation_db import backfill_product_authority; sr = Path(r'C:\PZ\app\storage'); print(backfill_product_authority(sr / 'reservation_queue.db', sr / 'wfirma.db', sr / 'master_data.db', now_iso=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))" `
  | Tee-Object "$bakdir\mirror-backfill-collision-report.txt"
# Then list any colliding rows explicitly:
python -c "import sqlite3; c=sqlite3.connect(r'C:\PZ\app\storage\wfirma.db'); r=sqlite3.connect(r'C:\PZ\app\storage\reservation_queue.db'); import collections; ids=collections.defaultdict(list); [ids[w].append(p) for p,w in c.execute(\"SELECT product_code, wfirma_product_id FROM wfirma_products WHERE COALESCE(wfirma_product_id,'')<>''\")]; [print('COLLISION good_id', w, 'claimed by', ps, '| mirror owner:', (r.execute('SELECT product_code FROM wfirma_product_mirror WHERE wfirma_id=?',(w,)).fetchone() or ['<none>'])[0]) for w,ps in ids.items() if len(ps)>1]" `
  | Tee-Object -Append "$bakdir\mirror-backfill-collision-report.txt"
```

**CAMPAIGN RULE (operator verdict): EVERY prod collision is an operator
per-product decision — which code truly owns the goods id in wFirma.** The
deploy may not finish with an unresolved collision (Wave 3 gate (3) requires
this report CLEAN). Record each ruling here (or in the report file), fix the
loser's mapping, re-run 2c (idempotent) until `wfirma_id_collisions: 0`:

| good_id | code A | code B | operator ruling (owner + action) |
|---|---|---|---|
| 99 (known verify-tree candidate) | EJL/26-27/254-1 | EJL/26-27/257-2 | ______________________ |
|   |   |   |   |

### 2d. Service-charge registry backfill

```powershell
python C:\PZ-deploy-w12\service\tools\backfill_service_product_registry.py --storage-root C:\PZ\app\storage
# STOP CONDITION: `copied` EMPTY on prod → do NOT start the service; investigate
# (freight/insurance labels would degrade to the fallback "freight") → session.
```

### 2e. NSSM service restart

```powershell
sc.exe start PZService; Start-Sleep 10; sc.exe query PZService   # expect RUNNING
```

---

## 3 — COLLISION REPORT (gate (3) of the operator verdict)

Artifact: `$bakdir\mirror-backfill-collision-report.txt` (written in 2c).
CLEAN means: final 2c run printed `wfirma_id_collisions: 0` AND the explicit
lister printed no `COLLISION` lines AND the ruling table above has an entry
for every collision that appeared along the way. Keep the file — it is part
of the deploy record and the Wave-3 gate evidence.

---

## 4 — POST-DEPLOY VERIFICATION (single checklist; all must pass)

```powershell
# 4a. Service up + health + access log alive
sc.exe query PZService                                                   # RUNNING
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health | Select StatusCode   # 200
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20    # no new Tracebacks
Get-ChildItem C:\PZ\logs | Sort-Object LastWriteTime -Descending | Select -First 3   # log freshness = access log live

# 4b. Prod schema presence (the pins' schema assumptions, checked against PROD)
python -c "import sqlite3; rq=sqlite3.connect(r'C:\PZ\app\storage\reservation_queue.db'); cols={r[1] for r in rq.execute('PRAGMA table_info(wfirma_product_mirror)')}; print('mirror six-cols:', cols=={'wfirma_id','product_code','sync_version','last_sync','hash','deleted_flag'}); pl=sqlite3.connect(r'C:\PZ\app\storage\proforma_links.db'); print('service_product_registry rows:', pl.execute('SELECT COUNT(*) FROM service_product_registry').fetchone()[0]); wh=sqlite3.connect(r'C:\PZ\app\storage\warehouse.db'); t={r[0] for r in wh.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")}; print('returns_events:', 'returns_events' in t, '| sample_out_events:', 'sample_out_events' in t)"
# Expect: mirror six-cols: True · registry rows >= 1 · both event tables True

# 4c. Production output-equivalence: regenerate the SAME proforma preview, diff values
Invoke-RestMethod -Method Post -Headers @{"X-API-KEY"=$env:PZ_API_KEY} `
  "http://127.0.0.1:47213/api/v1/proforma/preview/<BATCH>/<CLIENT>" |
  ConvertTo-Json -Depth 8 | Out-File "$bakdir\preview-post-deploy.json" -Encoding utf8
python -c "import json,io,sys; a=json.load(io.open(sys.argv[1],encoding='utf-8-sig')); b=json.load(io.open(sys.argv[2],encoding='utf-8-sig')); key=lambda d:{'currency':d.get('currency'),'exchange_rate':d.get('exchange_rate'),'lines':[{k:l.get(k) for k in ('product_code','qty','unit_price','currency')} for l in d.get('lines',[])],'service_charge_total':(d.get('totals') or {}).get('service_charge_total', d.get('service_charge_total'))}; ka,kb=key(a),key(b); print('VALUE-EQUIVALENT' if ka==kb else 'VALUE DIFF - STOP:'); import difflib; ka==kb or print('\n'.join(difflib.unified_diff(json.dumps(ka,indent=1).splitlines(), json.dumps(kb,indent=1).splitlines(), 'pre','post')))" `
  "$bakdir\preview-pre-deploy.json" "$bakdir\preview-post-deploy.json"
# Expect: VALUE-EQUIVALENT. Any VALUE DIFF = STOP -> bring both files to the session.
# (Readiness/advisory fields MAY legitimately differ - values must not.)

# 4d. C-1f path exercised: mapped freight/insurance emission (read-only, no wFirma call)
cd C:\PZ
python -c "from app.services import packing_db, warehouse_db, document_db, wfirma_db; from pathlib import Path; sr=Path(r'C:\PZ\app\storage'); wfirma_db.init_wfirma_db(sr/'wfirma.db'); from app.api.routes_proforma import _build_service_charge_lines; lines, note = _build_service_charge_lines([{'charge_type':'freight','amount':'1.00','currency':'EUR'},{'charge_type':'insurance','amount':'1.00','currency':'EUR'}], 'EUR'); print('emitted lines:', [(l.product_code, l.wfirma_good_id, l.product_name, l.unit) for l in lines]); print('note:', note or '<none>')"
# Expect: NO exception (the C-1f defect was a NameError here); every charge type that
# is mapped in prod emits a line with its registered label; unmapped -> note, not crash.

# 4e. New Wave-2 read endpoints reachable
Invoke-RestMethod -Headers @{"X-API-KEY"=$env:PZ_API_KEY} "http://127.0.0.1:47213/api/v1/inventory/samples?limit=5"  | ConvertTo-Json -Depth 3
Invoke-RestMethod -Headers @{"X-API-KEY"=$env:PZ_API_KEY} "http://127.0.0.1:47213/api/v1/inventory/returns?limit=5"  | ConvertTo-Json -Depth 3
# Expect: {"ok":true,...} from both (empty registers are fine; 503 = migration step 2b missed)
Invoke-RestMethod -Headers @{"X-API-KEY"=$env:PZ_API_KEY} "http://127.0.0.1:47213/api/v1/proforma/service-products" | ConvertTo-Json -Depth 5
# Compare against $bakdir\service-products-pre-deploy.json: same mappings, same labels.
```

Then report to the session: **"deploy done + verification green + collision
report clean"** (attach `$bakdir` path). The session appends the Lesson-D
record to `local-commit-deploys.jsonl`, flips W3-A1 → VALID, and the campaign
waits for your **separate Wave-3 ratification** (operator verdict step (4)).

---

## 5 — ROLLBACK (exact restore from the .bak set)

```powershell
sc.exe stop PZService; Start-Sleep 8
# 5a. Code restore
robocopy "C:\PZ-backups\app-pre-wave12-$stamp" "C:\PZ\app" /E /XD storage
# 5b. DB restore from the named .bak set (full set, strip the .bak suffix)
Get-ChildItem "C:\PZ-backups\db-pre-wave12-$stamp" -Filter *.bak |
  ForEach-Object { Copy-Item $_.FullName ("C:\PZ\app\storage\" + ($_.Name -replace '\.bak$','')) -Force }
sc.exe start PZService; Start-Sleep 10; sc.exe query PZService   # RUNNING
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health | Select StatusCode
```

Schema note: the new tables are additive and ignored by old code, so a
code-only rollback (5a) is sufficient unless a backfill mis-wrote data — the
DB restore (5b) returns storage to the pre-deploy byte state. Git-level:
`git revert -m 1 84c292de` on the campaign branch if the candidate itself
must be unwound.
