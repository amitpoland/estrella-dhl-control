# /deploy — Production Deploy Command

Triggers the full production deployment procedure defined in `service/docs/production_deployment_rule.md`.

**Never skip any step. Never skip the 7-agent gate.**

Deployment is **deterministic and artifact-based**. The bytes that reach production are the
bytes of an immutable staged release artifact — never a live git tree, never a
timestamp-heuristic copy.

---

## Step 0 — Deploy-source preflight (MANDATORY — fail closed)

`C:\PZ-main` is the **sole deployment source**. `C:\PZ-verify` owns the repository
`.git` and is the verification-read tree — it is **never** a deploy source. These are
deliberately different trees; see the canonical working-tree registry in `CLAUDE.md`.

```powershell
$SRC = "C:\PZ-main"
git -C $SRC fetch origin
$dirty  = git -C $SRC status --porcelain
$branch = git -C $SRC branch --show-current
$head   = git -C $SRC rev-parse HEAD
$remote = git -C $SRC rev-parse origin/main
if ($dirty)               { throw "BLOCKED: deploy source is dirty" }
if ($branch -ne "main")   { throw "BLOCKED: deploy source is not on main (is '$branch')" }
if ($head -ne $remote)    { throw "BLOCKED: HEAD $head != origin/main $remote" }
Write-Host "Deploy source OK: $SRC @ $head"
$SHA = $head
```

All three assertions must pass. A throw here stops the deploy — do not "just continue".

---

## Step 1 — Inspect

```powershell
cd "C:\PZ-main"
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

**Re-gate rule:** the gate certifies the `service/app` **tree hash**, not the commit SHA. If
`git rev-parse <SHA>:service/app` is unchanged, docs/governance commits landing on top do
**not** require a re-gate. Record the certified tree hash:

```powershell
$TREE = git -C "C:\PZ-main" rev-parse "$SHA`:service/app"
```

---

## Step 3 — Establish the production baseline (MANDATORY — before any write)

`C:\PZ` contains no `.git`, so it has no SHA to read. The baseline must be **measured**, never
assumed from mtime (`/XO`-style timestamps lie about content) and never inherited from a stale
memory note.

Bracket the baseline with content markers unique to candidate commits — a marker present proves
the commit is deployed; a marker absent proves it is not:

```powershell
# example bracketing; choose markers unique to the candidate commits
Select-String -Path "C:\PZ\app\services\invoice_packing_extractor.py" -Pattern "<marker-from-newer-PR>" -Quiet
Test-Path "C:\PZ\app\services\<file-introduced-by-newer-PR>.py"
```

Record the proven baseline SHA. **If the baseline cannot be proven, STOP** — the deploy delta is
ambiguous and no rollback target is defined.

---

## Step 4 — Test

Run from the deploy source. `PYTHONUTF8=1` is the canonical invocation (matches the Makefile
`verify` target and the pre-commit / post-edit hooks).

```powershell
cd "C:\PZ-main"
$env:PYTHONUTF8 = "1"
python test_pz_regression.py                      # root golden — script, not a pytest suite
```

```powershell
cd "C:\PZ-main\service"
$env:PYTHONUTF8 = "1"
python -m pytest tests/test_pz_*.py -q            # metered PZ suite
python -m pytest tests/test_carrier_*.py -q       # metered carrier suite
python -m pytest tests/ -m smoke -q               # smoke
```

Required counts and the documented exclusion list live in `.claude/contracts/test-baseline.md`
(single source of truth). Stop on any ERROR, any undocumented FAILED, or any count below floor.

---

## Step 5 — Stage the immutable release artifact

The artifact — not the git tree — is what deploys. Staging decouples the release bytes from any
later branch/checkout movement in `C:\PZ-main`.

```powershell
$ART = "C:\PZ-releases\app-$SHA"
if (Test-Path $ART) { throw "BLOCKED: artifact $ART already exists — releases are immutable" }
robocopy "C:\PZ-main\service\app" $ART /E /XD __pycache__ .pytest_cache storage /XF "*.pyc" "*.pyo"
if ($LASTEXITCODE -ge 8) { throw "BLOCKED: artifact staging failed ($LASTEXITCODE)" }

# manifest + immutability
Get-ChildItem $ART -Recurse -File | Get-FileHash -Algorithm SHA256 |
  Select-Object Hash, @{n='Rel';e={$_.Path.Substring($ART.Length+1)}} |
  Sort-Object Rel | Export-Csv "$ART.manifest.csv" -NoTypeInformation -Encoding utf8
Get-ChildItem $ART -Recurse -File | ForEach-Object { $_.IsReadOnly = $true }
Write-Host "Artifact staged: $ART ($(Get-ChildItem $ART -Recurse -File).Count files)"
```

**Never deploy from `C:\PZ-main\service\app` directly. Never re-stage over an existing artifact.**

---

## Step 6 — Mandatory pre-deploy backup (the ONLY rollback source)

Rollback restores from this artifact and nothing else. If this step is skipped there is **no
compliant rollback path** — `C:\PZ-main` must never be mutated to recover production.

```powershell
$STAMP  = Get-Date -Format "yyyyMMdd-HHmmss"
$BACKUP = "C:\PZ-backups\app-baseline-$BASELINE_SHA-$STAMP"
robocopy "C:\PZ\app" $BACKUP /E /XD __pycache__ .pytest_cache storage /XF "*.pyc" "*.pyo"
if ($LASTEXITCODE -ge 8) { throw "BLOCKED: backup failed ($LASTEXITCODE)" }

# validate the backup before trusting it
Get-ChildItem $BACKUP -Recurse -File | Get-FileHash -Algorithm SHA256 |
  Select-Object Hash, @{n='Rel';e={$_.Path.Substring($BACKUP.Length+1)}} |
  Sort-Object Rel | Export-Csv "$BACKUP.manifest.csv" -NoTypeInformation -Encoding utf8

$srcCount = (Get-ChildItem "C:\PZ\app" -Recurse -File -Exclude *.pyc,*.pyo |
             Where-Object { $_.FullName -notmatch '\\(storage|__pycache__|\.pytest_cache)\\' }).Count
$bakCount = (Get-ChildItem $BACKUP -Recurse -File).Count
if ($bakCount -ne $srcCount) { throw "BLOCKED: backup incomplete ($bakCount vs $srcCount)" }
Write-Host "Backup validated: $BACKUP ($bakCount files)"
```

**A deploy may not proceed until the backup is validated.**

---

## Step 7 — Destination-only file inventory (gate for mirroring)

Convergence deletes destination-only files. That is the point — it is how a rollback removes
files a newer release introduced (e.g. `services/document_reconciler.py`). It is also the only
step that can destroy production state, so every destination-only path must be classified
**before** any mirror runs.

```powershell
$extraneous = robocopy $ART "C:\PZ\app" /E /L /NJH /NJS /NP /FP /XX /XD __pycache__ .pytest_cache storage logs cloudflared /XF ".env" |
              Select-String "\*EXTRA" 
$extraneous
```

Classify **every** line:

| Class | Action |
|---|---|
| Runtime-owned (see Step 8 protected list) | Must be excluded by `/XD`/`/XF` — never deleted |
| Superseded release file (present in baseline, absent in this release) | Deletion intended — this is correct convergence |
| Unknown / unclassified | **STOP.** Do not mirror until identified. |

**If any line is unclassified, the deploy is BLOCKED.** An unreviewed `/MIR` is how production
state gets destroyed.

---

## Step 8 — Protected runtime-owned paths (never synced, never deleted)

These are owned by the running service, not by the release. They must appear in the exclusion
list of **every** convergence and **every** rollback:

| Path | Owner |
|---|---|
| `storage\` | runtime data — databases, generated artifacts |
| `logs\` | runtime logs |
| `__pycache__\` | interpreter |
| `.pytest_cache\` | test tooling |
| `.env` | operator-owned secrets/config |
| `cloudflared\` | tunnel config |

Canonical exclusion fragment — reuse verbatim:

```powershell
$PROTECT = @("/XD","__pycache__",".pytest_cache","storage","logs","cloudflared","/XF",".env","*.pyc","*.pyo")
```

Any new runtime-owned path must be added here **and** to `.claude/deploy/windows_prod_v2.json`
before its first deploy.

---

## Step 9 — Stop PZService (before convergence, elevated shell)

Convergence must not race a running service. Stop first, converge second.

```powershell
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) { Start-Sleep -Seconds 1; $tries++ }
if ((Get-Service PZService).Status -ne 'Stopped') { throw "BLOCKED: PZService did not stop" }
```

---

## Step 10 — Converge production to the artifact (exact, deterministic)

`/MIR` makes the destination *exactly* the artifact. **`/XO` is forbidden** — it skips files it
judges "not newer", which silently leaves stale destination files and produces a partial,
version-skewed release (2026-07-07 incident: `ImportError` on start).

```powershell
robocopy $ART "C:\PZ\app" /MIR @PROTECT
if ($LASTEXITCODE -ge 8) { throw "DEPLOYMENT_FAILED: convergence failed ($LASTEXITCODE) — roll back" }
```

Exit codes 0–7 acceptable (0–3 normal; 4–7 indicate mismatches worth reading). 8+ = failure.

---

## Step 10b — Engine sync (Lesson J — SEPARATE robocopy, not covered by Step 10)

Root-level engine files live outside `service/app` and are **not** carried by the Step 10
sync. Skipping this step ships a backend that runs against a stale calculation engine.

```powershell
robocopy "C:\PZ-main" "C:\PZ\engine" pz_import_processor.py polish_description_generator.py /COPY:DAT
```

Verify by **content**, not by Python import (Lesson J — an import check passes against the
stale copy already on `sys.path`):

```powershell
(Get-FileHash "C:\PZ-main\pz_import_processor.py").Hash -eq (Get-FileHash "C:\PZ\engine\pz_import_processor.py").Hash
(Get-FileHash "C:\PZ-main\polish_description_generator.py").Hash -eq (Get-FileHash "C:\PZ\engine\polish_description_generator.py").Hash
```

Both must print `True`.

---

## Step 11 — Hash-verify runtime files BEFORE restart

Verify against the **artifact manifest**, while the service is still stopped. A hash mismatch
here means production is version-skewed — roll back rather than start it.

```powershell
$man  = Import-Csv "$ART.manifest.csv"
$bad  = foreach ($row in $man) {
  $dst = Join-Path "C:\PZ\app" $row.Rel
  if (-not (Test-Path $dst))                              { "MISSING : $($row.Rel)" }
  elseif ((Get-FileHash $dst).Hash -ne $row.Hash)         { "MISMATCH: $($row.Rel)" }
}
if ($bad) { $bad; throw "DEPLOYMENT_FAILED: runtime hash verification failed — roll back" }
Write-Host "Hash verification PASSED ($($man.Count) files)"
```

Additionally confirm every file of the release delta (the N runtime files named by the gate)
appears in the verified set.

---

## Step 12 — Start PZService

```powershell
sc.exe start PZService
Start-Sleep -Seconds 10
sc.exe query PZService     # must show RUNNING
```

---

## Step 13 — Post-deploy verification

```powershell
Get-Content C:\PZ\logs\pz_stderr.log -Tail 30      # startup complete, no traceback
Invoke-WebRequest http://127.0.0.1:47213/api/v1/health
Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health
Invoke-WebRequest http://127.0.0.1:47213/api/v1/carrier/status
Invoke-WebRequest http://127.0.0.1:47213/api/v1/carrier/STAGE0-TEST/shipment `
  -Method POST -Body '{"shipper_account":"TEST","recipient_address":{},"declared_value":100,"currency":"EUR","weight_kg":1,"dimensions":{}}' `
  -ContentType "application/json"
```

Unauthenticated request to a protected endpoint must return **401**. Carrier gate POST must
return **503** (gate closed). Any feature flag shipped OFF must still be absent/false in
`C:\PZ\.env` and its endpoint must return **503**.

---

## Step 14 — Close-condition gate

```powershell
cd "C:\PZ-main"
.\.claude\manifests\verify_deploy_close.ps1 -ExpectedSHA $SHA
```

Exit 0 = all close conditions passed. Exit 1 = investigate; do not mark closed.

---

## Rollback — restore from the backup artifact ONLY

**Forbidden in rollback:** `git revert`, `git checkout`, `git reset`, or **any** mutation of
`C:\PZ-main`. The deployment source is never rewound to recover production — it is a source of
truth, not a recovery mechanism. Rollback is a filesystem convergence from the validated Step 6
backup.

`/MIR` is required: `/E` alone would **leave files the newer release introduced** (e.g.
`services/document_reconciler.py` would survive a rollback and run against baseline code).

```powershell
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) { Start-Sleep -Seconds 1; $tries++ }
if ((Get-Service PZService).Status -ne 'Stopped') { throw "BLOCKED: PZService did not stop" }

robocopy $BACKUP "C:\PZ\app" /MIR @PROTECT
if ($LASTEXITCODE -ge 8) { throw "ROLLBACK FAILED ($LASTEXITCODE)" }

# prove newer-release files are GONE
$introduced = @("services\document_reconciler.py")   # files added by the rolled-back release
foreach ($f in $introduced) {
  if (Test-Path (Join-Path "C:\PZ\app" $f)) { throw "ROLLBACK FAILED: $f survived" }
}

# prove exact convergence to the backup manifest
$man = Import-Csv "$BACKUP.manifest.csv"
$bad = foreach ($row in $man) {
  $dst = Join-Path "C:\PZ\app" $row.Rel
  if (-not (Test-Path $dst))                      { "MISSING : $($row.Rel)" }
  elseif ((Get-FileHash $dst).Hash -ne $row.Hash) { "MISMATCH: $($row.Rel)" }
}
if ($bad) { $bad; throw "ROLLBACK FAILED: backup convergence incomplete" }

sc.exe start PZService
Start-Sleep -Seconds 10
sc.exe query PZService
```

Then re-run Step 13. Emit `ROLLBACK_VERIFIED` only when convergence, file-removal, and health
all pass.

---

## Deployment states

| State | Meaning |
|---|---|
| `DEPLOYMENT_READY_AWAITING_OPERATOR` | Steps 0–8 complete, gate approved, artifact staged, backup validated, inventory classified. No production write has occurred. The agent is hard-blocked from Steps 9–12 by `pz-deploy-guard`; the operator executes them. |
| `DEPLOYMENT_VERIFIED` | Steps 9–14 complete; hashes match, service RUNNING, health/401/503 all pass. |
| `DEPLOYMENT_FAILED` | Any convergence, hash-verification, startup, or verification failure. Roll back. |
| `ROLLBACK_VERIFIED` | Backup convergence exact, newer-release files proven removed, service healthy. |

---

## Required output

```
Deploy source:     C:\PZ-main @ <SHA>   (clean, on main, == origin/main)
Certified tree:    service/app <TREE-HASH>
Baseline (proven): <BASELINE_SHA>   (measured by marker bracketing, not mtime)
Artifact:          C:\PZ-releases\app-<SHA>        [staged | immutable | N files]
Backup:            C:\PZ-backups\app-baseline-<BASELINE_SHA>-<STAMP>   [validated | N files]
Dest-only files:   [none | N classified | UNCLASSIFIED -> BLOCKED]
Tests:             Root Golden 160/160
                   PZ 257 (+ documented #613 exclusion)
                   Carrier 619 (contract floor 604, documented env exclusions)
                   Smoke 63 passed / 1 skipped   (canonical PYTHONUTF8=1)
Service stopped:   [yes | no]
Sync result:       robocopy /MIR exit [n]        (/XO is forbidden)
Engine sync:       [hashes True/True | n/a]
Hash verify:       [PASSED n files | FAILED]
Service status:    [RUNNING | ERROR]
Local health:      [200 | ERROR]
Public health:     [200 | ERROR]
Unauth 401:        [yes | no]
Carrier gate:      [pending | other]
Gate POST 503:     [yes | no]
Rollback source:   C:\PZ-backups\app-baseline-<BASELINE_SHA>-<STAMP>   (never git)
STATE:             [DEPLOYMENT_READY_AWAITING_OPERATOR | DEPLOYMENT_VERIFIED | DEPLOYMENT_FAILED | ROLLBACK_VERIFIED]
```
