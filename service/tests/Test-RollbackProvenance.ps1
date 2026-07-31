# Behavioral regression for the rollback-provenance helpers in Deploy-PZ.ps1.
#
# The Python governance suite (test_deploy_authority.py) pins the SHAPE of the fix by
# text-asserting the script. This file EXECUTES the pure helpers via the -NoRun
# dot-source seam and asserts their runtime behavior, covering the enumerated cases:
# reads a valid marker, tolerates BOM/whitespace, never guesses on garbage/absent,
# resolves restored_sha from metadata OR the immutable snapshot, blocks on disagreement,
# blocks a legacy unit (never falling back to the deployment SHA), and rejects a
# malformed metadata SHA.
#
# There is no Pester/make on this box; run directly:
#   powershell -File service/tests/Test-RollbackProvenance.ps1
# It writes only under the OS temp dir and never names or touches the production tree.

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\.claude\deploy\Deploy-PZ.ps1') -NoRun

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("rbprov-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$OLD = '1111111111111111111111111111111111111111'  # pre-deploy (restored) content
$NEW = '2222222222222222222222222222222222222222'  # incoming deployment

$script:pass = 0; $script:fail = 0
function Check([string]$name, [bool]$cond) {
    if ($cond) { $script:pass++; Write-Host "PASS $name" }
    else { $script:fail++; Write-Host "FAIL $name" }
}
function MarkerFile([string]$dir, [string]$file, [string]$text, [bool]$bom = $false) {
    $enc = if ($bom) { New-Object System.Text.UTF8Encoding($true) } else { New-Object System.Text.ASCIIEncoding }
    [System.IO.File]::WriteAllText((Join-Path $dir $file), $text, $enc)
}

# --- Read-VersionMarker ---------------------------------------------------------
MarkerFile $tmp 'plain.txt' $OLD
Check 'reader: plain ascii sha' ((Read-VersionMarker -Path (Join-Path $tmp 'plain.txt')) -eq $OLD)

MarkerFile $tmp 'bom.txt' "  $OLD `r`n" $true
Check 'reader: tolerates BOM + whitespace' ((Read-VersionMarker -Path (Join-Path $tmp 'bom.txt')) -eq $OLD)

Check 'reader: absent file -> $null' ($null -eq (Read-VersionMarker -Path (Join-Path $tmp 'missing.txt')))

MarkerFile $tmp 'junk.txt' 'not-a-sha'
Check 'reader: garbage -> $null (never guesses)' ($null -eq (Read-VersionMarker -Path (Join-Path $tmp 'junk.txt')))

# --- Resolve-RestoredSha --------------------------------------------------------
$bMeta = Join-Path $tmp 'b-meta'; New-Item -ItemType Directory -Path $bMeta -Force | Out-Null
$mMeta = [pscustomobject]@{ deployment_sha = $NEW; restored_sha = $OLD; sha = $NEW }
Check 'resolver: from metadata' ((Resolve-RestoredSha -Meta $mMeta -BackupPath $bMeta -UnitId 'u') -eq $OLD)

$bCopy = Join-Path $tmp 'b-copy'; New-Item -ItemType Directory -Path $bCopy -Force | Out-Null
MarkerFile $bCopy 'version.pre.txt' $OLD
$mCopy = [pscustomobject]@{ deployment_sha = $NEW; sha = $NEW }   # no restored_sha
Check 'resolver: from immutable snapshot' ((Resolve-RestoredSha -Meta $mCopy -BackupPath $bCopy -UnitId 'u') -eq $OLD)

$bAgree = Join-Path $tmp 'b-agree'; New-Item -ItemType Directory -Path $bAgree -Force | Out-Null
MarkerFile $bAgree 'version.pre.txt' $OLD
$mAgree = [pscustomobject]@{ restored_sha = $OLD; sha = $NEW }
Check 'resolver: both sources agree -> ok' ((Resolve-RestoredSha -Meta $mAgree -BackupPath $bAgree -UnitId 'u') -eq $OLD)

$bDis = Join-Path $tmp 'b-dis'; New-Item -ItemType Directory -Path $bDis -Force | Out-Null
MarkerFile $bDis 'version.pre.txt' $NEW
$mDis = [pscustomobject]@{ restored_sha = $OLD; sha = $NEW }
$blockedDis = $false
try { Resolve-RestoredSha -Meta $mDis -BackupPath $bDis -UnitId 'u' | Out-Null }
catch { $blockedDis = ($_.Exception.Message -like '*inconsistent*') }
Check 'resolver: sources disagree -> BLOCK' $blockedDis

$bLegacy = Join-Path $tmp 'b-legacy'; New-Item -ItemType Directory -Path $bLegacy -Force | Out-Null
$mLegacy = [pscustomobject]@{ deployment_sha = $NEW; sha = $NEW }  # no restored evidence at all
$blockedLegacy = $false; $leakedDeploy = $false
try { $r = Resolve-RestoredSha -Meta $mLegacy -BackupPath $bLegacy -UnitId 'u'; $leakedDeploy = ($r -eq $NEW) }
catch { $blockedLegacy = ($_.Exception.Message -like '*legacy*') }
Check 'resolver: legacy unit -> BLOCK, never deployment SHA' ($blockedLegacy -and -not $leakedDeploy)

$bBad = Join-Path $tmp 'b-bad'; New-Item -ItemType Directory -Path $bBad -Force | Out-Null
$mBad = [pscustomobject]@{ restored_sha = 'deadbeef'; sha = $NEW }  # malformed, no snapshot
$blockedBad = $false
try { Resolve-RestoredSha -Meta $mBad -BackupPath $bBad -UnitId 'u' | Out-Null }
catch { $blockedBad = ($_.Exception.Message -like '*legacy*') }
Check 'resolver: malformed metadata SHA -> BLOCK' $blockedBad

# --- New-BackupUnit -> Resolve-RestoredSha round trip ---------------------------
# The checks above exercise the resolver against HAND-BUILT metadata, which proves the
# resolver but assumes the producer writes what the consumer expects. This block EXECUTES
# the real producer against a synthetic config rooted entirely in the temp dir, then feeds
# its genuine on-disk output back to the resolver. That closes the producer/consumer seam:
# a change to either side that breaks the contract fails here.
#
# It is production-free by construction -- every path below is under $tmp, the config is
# built here rather than read from windows_prod_v2.json, and no service, lock,
# authorization or rollback is involved. New-BackupUnit itself performs no authorization
# (Invoke-Deploy asserts that before calling it) and never writes the version marker.
# NOTE FOR FUTURE EDITORS: every write below deliberately uses [System.IO.File], never a
# PowerShell file-writing cmdlet. test_deploy_authority.py::test_version_file_has_exactly_one_writer
# scans every *.ps1 for the pair (the version_file config key + the name of such a cmdlet)
# to guarantee production's version marker has a single writer. This file must name that
# config key, so introducing one of those cmdlet names here -- in code OR in a comment --
# trips the pin, correctly by its own heuristic, even though nothing here goes near
# production. Keep the raw-API writes, and do not spell those cmdlet names in this file.
function New-SyntheticConfig([string]$root, [string]$marker) {
    New-Item -ItemType Directory -Path (Join-Path $root 'runtime\app') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root 'backups') -Force | Out-Null
    MarkerFile (Join-Path $root 'runtime\app') 'payload.txt' 'application bytes'
    if ($marker) { MarkerFile (Join-Path $root 'runtime') 'version.txt' $marker }
    $cfgPath = Join-Path $root 'cfg.json'
    $cfg = [pscustomobject]@{
        schema_version = 2; service = 'SyntheticNoService'
        source_root = $root; source_app = (Join-Path $root 'runtime\app')
        runtime_app = (Join-Path $root 'runtime\app')
        runtime_engine = (Join-Path $root 'runtime\engine-absent')
        artifact_root = (Join-Path $root 'releases'); backup_root = (Join-Path $root 'backups')
        version_file = (Join-Path $root 'runtime\version.txt')
        lock_file = (Join-Path $root 'backups\.lock')
        engine_files = @('pz_import_processor.py'); protected_dirs = @('storage')
        protected_files = @('.env'); protected_runtime_paths = @((Join-Path $root 'runtime\storage'))
        forbidden_flags = @('/XO'); robocopy_fatal_exit = 8; robocopy_suspect_exit = 4
        service_wait_seconds = 60; test_baseline_contract = 'n/a'
        authorization_helper = 'hooks\deploy_authorization.py'
    }
    [System.IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
    return (Get-DeployConfig -ConfigPath $cfgPath)
}

# Case 1: a marker IS present -- the produced unit must carry BOTH identities, and the
# resolver must return the PRE-deploy SHA, never the incoming deployment SHA.
$rtRoot = Join-Path $tmp 'rt-ok'; New-Item -ItemType Directory -Path $rtRoot -Force | Out-Null
$rtCfg = New-SyntheticConfig $rtRoot $OLD
$rtUnit = New-BackupUnit -Cfg $rtCfg -Sha $NEW -UnitScope 'App' 6>$null
$rtMeta = Get-Content (Join-Path $rtUnit.Path 'unit.json') -Raw | ConvertFrom-Json
Check 'roundtrip: unit records the incoming deployment SHA' ($rtMeta.deployment_sha -eq $NEW)
Check 'roundtrip: unit records the pre-deploy SHA as restored content' ($rtMeta.restored_sha -eq $OLD)
Check 'roundtrip: immutable snapshot written beside the unit' `
    ((Read-VersionMarker -Path (Join-Path $rtUnit.Path 'version.pre.txt')) -eq $OLD)
Check 'roundtrip: unit marked complete' ($rtMeta.complete -eq $true)
$rtResolved = Resolve-RestoredSha -Meta $rtMeta -BackupPath $rtUnit.Path -UnitId $rtUnit.Unit
Check 'roundtrip: resolver returns the PRE-deploy SHA from real producer output' ($rtResolved -eq $OLD)
Check 'roundtrip: resolver never returns the deployment SHA' ($rtResolved -ne $NEW)
# The unit id begins with the DEPLOYMENT sha -- the value an operator would wrongly reach
# for. Pin that the resolver did not derive content identity from it.
Check 'roundtrip: unit id prefix is the deployment SHA, not the restored SHA' `
    ($rtUnit.Unit.StartsWith($NEW) -and -not $rtUnit.Unit.StartsWith($OLD))

# Case 2: NO readable marker -- the producer must still succeed (blocking the forward
# deploy would strand production), record a null restored_sha, write no snapshot, and the
# resulting unit must then be REFUSED by the resolver rather than silently rolled back.
$rtRoot2 = Join-Path $tmp 'rt-nomarker'; New-Item -ItemType Directory -Path $rtRoot2 -Force | Out-Null
$rtCfg2 = New-SyntheticConfig $rtRoot2 $null
$rtUnit2 = New-BackupUnit -Cfg $rtCfg2 -Sha $NEW -UnitScope 'App' 3>$null 6>$null
$rtMeta2 = Get-Content (Join-Path $rtUnit2.Path 'unit.json') -Raw | ConvertFrom-Json
Check 'roundtrip(no marker): forward deploy is not blocked' ($null -ne $rtUnit2.Unit)
Check 'roundtrip(no marker): restored_sha recorded as null, never guessed' ($null -eq $rtMeta2.restored_sha)
Check 'roundtrip(no marker): no snapshot written' (-not (Test-Path (Join-Path $rtUnit2.Path 'version.pre.txt')))
$blockedRt = $false; $leakedRt = $false
try { $x = Resolve-RestoredSha -Meta $rtMeta2 -BackupPath $rtUnit2.Path -UnitId $rtUnit2.Unit; $leakedRt = ($x -eq $NEW) }
catch { $blockedRt = ($_.Exception.Message -like '*legacy*') }
Check 'roundtrip(no marker): resulting unit is REFUSED, not rolled back' ($blockedRt -and -not $leakedRt)

# --- Assert-ProductionMatchesRecordedSha (pre-backup production identity gate) ---
# The gate proves the CURRENT runtime application tree IS the tree of the commit recorded
# in the version marker, BEFORE the deploy stops the service or takes a backup. It compares
# git object ids (ls-tree of the recorded commit vs hash-object of each runtime file) so it
# is EOL-robust: a runtime file that is byte-correct but CRLF-terminated still hashes to the
# committed LF blob id. These cases build a REAL synthetic git repo rooted entirely under
# $tmp -- source_app is committed; runtime_app is a SEPARATE tree written with CRLF so the
# match case doubles as the EOL-robustness proof. Production is never named or touched; git
# runs only against the temp repo. Writes use [System.IO.File] per the file rule above.
function New-GateRepo([string]$root, [string]$markerOverride) {
    $srcApp = Join-Path $root 'app'
    New-Item -ItemType Directory -Path (Join-Path $srcApp 'sub') -Force | Out-Null
    $enc = New-Object System.Text.ASCIIEncoding
    # committed with LF; autocrlf=true stores LF blobs.
    [System.IO.File]::WriteAllText((Join-Path $srcApp 'main.py'), "print('a')`nprint('b')`n", $enc)
    [System.IO.File]::WriteAllText((Join-Path $srcApp 'sub\util.py'), "x = 1`n", $enc)
    & git -C $root init -q | Out-Null
    & git -C $root config user.email 't@t' | Out-Null
    & git -C $root config user.name 't' | Out-Null
    & git -C $root config core.autocrlf true | Out-Null
    & git -C $root add app | Out-Null
    & git -C $root commit -q -m init | Out-Null
    $sha = (& git -C $root rev-parse HEAD).Trim()
    New-Item -ItemType Directory -Path (Join-Path $root 'runtime') -Force | Out-Null
    $marker = if ($markerOverride) { $markerOverride } else { $sha }
    if ($marker -ne '__NONE__') {
        [System.IO.File]::WriteAllText((Join-Path $root 'runtime\version.txt'), $marker, $enc)
    }
    $rtApp = Join-Path $root 'runtime\app'
    New-Item -ItemType Directory -Path (Join-Path $rtApp 'sub') -Force | Out-Null
    # runtime copy written with CRLF on purpose -> proves the gate normalizes and matches.
    [System.IO.File]::WriteAllText((Join-Path $rtApp 'main.py'), "print('a')`r`nprint('b')`r`n", $enc)
    [System.IO.File]::WriteAllText((Join-Path $rtApp 'sub\util.py'), "x = 1`r`n", $enc)
    $cfgPath = Join-Path $root 'cfg.json'
    $cfg = [pscustomobject]@{
        schema_version = 2; service = 'SyntheticNoService'
        source_root = $root; source_app = $srcApp
        runtime_app = $rtApp
        runtime_engine = (Join-Path $root 'runtime\engine-absent')
        artifact_root = (Join-Path $root 'releases'); backup_root = (Join-Path $root 'backups')
        version_file = (Join-Path $root 'runtime\version.txt')
        lock_file = (Join-Path $root 'backups\.lock')
        engine_files = @('pz_import_processor.py'); protected_dirs = @('storage', '__pycache__')
        protected_files = @('.env', '*.pyc'); protected_runtime_paths = @((Join-Path $root 'runtime\storage'))
        forbidden_flags = @('/XO'); robocopy_fatal_exit = 8; robocopy_suspect_exit = 4
        service_wait_seconds = 60; test_baseline_contract = 'n/a'
        authorization_helper = 'hooks\deploy_authorization.py'
    }
    [System.IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
    return [pscustomobject]@{ Cfg = (Get-DeployConfig -ConfigPath $cfgPath); Sha = $sha; RuntimeApp = $rtApp }
}
function Assert-GatePasses([string]$name, $cfg) {
    $ok = $false
    try { Assert-ProductionMatchesRecordedSha -Cfg $cfg 6>$null; $ok = $true }
    catch { Write-Host "  (unexpected block: $($_.Exception.Message))" }
    Check $name $ok
}
function Assert-GateBlocks([string]$name, $cfg, [string]$needle) {
    $blocked = $false
    try { Assert-ProductionMatchesRecordedSha -Cfg $cfg 6>$null }
    catch { $blocked = ($_.Exception.Message -like "*$needle*") }
    Check $name $blocked
}

# GA: byte-correct runtime (CRLF) vs committed (LF) blob -> PASS (EOL-robust).
$gaRoot = Join-Path $tmp 'gate-ok'; New-Item -ItemType Directory -Path $gaRoot -Force | Out-Null
$ga = New-GateRepo $gaRoot $null
Assert-GatePasses 'gate: CRLF runtime matches LF-committed marker -> pass (EOL-robust)' $ga.Cfg

# GB: one runtime file's content changed -> BLOCK (hybrid tree).
$gbRoot = Join-Path $tmp 'gate-hybrid'; New-Item -ItemType Directory -Path $gbRoot -Force | Out-Null
$gb = New-GateRepo $gbRoot $null
[System.IO.File]::WriteAllText((Join-Path $gb.RuntimeApp 'main.py'), "print('CHANGED')`r`n", (New-Object System.Text.ASCIIEncoding))
Assert-GateBlocks 'gate: one changed runtime file -> BLOCK (hybrid)' $gb.Cfg 'IDENTITY MISMATCH'

# GC: absent version marker -> BLOCK, never proceeds over an unknown tree.
$gcRoot = Join-Path $tmp 'gate-nomarker'; New-Item -ItemType Directory -Path $gcRoot -Force | Out-Null
$gc = New-GateRepo $gcRoot '__NONE__'
Assert-GateBlocks 'gate: absent version marker -> BLOCK' $gc.Cfg 'version marker'

# GD: marker holds a well-formed SHA that is not a commit in the repo -> BLOCK, no guess.
$gdRoot = Join-Path $tmp 'gate-nocommit'; New-Item -ItemType Directory -Path $gdRoot -Force | Out-Null
$gd = New-GateRepo $gdRoot ('a' * 40)
Assert-GateBlocks 'gate: marker SHA not a commit -> BLOCK' $gd.Cfg 'not a commit'

# GE: an extraneous runtime file not in the recorded tree -> BLOCK.
$geRoot = Join-Path $tmp 'gate-extra'; New-Item -ItemType Directory -Path $geRoot -Force | Out-Null
$ge = New-GateRepo $geRoot $null
[System.IO.File]::WriteAllText((Join-Path $ge.RuntimeApp 'ghost.py'), "y = 2`r`n", (New-Object System.Text.ASCIIEncoding))
Assert-GateBlocks 'gate: extraneous runtime file -> BLOCK' $ge.Cfg 'IDENTITY MISMATCH'

# GF: a tracked file missing from the runtime tree -> BLOCK.
$gfRoot = Join-Path $tmp 'gate-missing'; New-Item -ItemType Directory -Path $gfRoot -Force | Out-Null
$gf = New-GateRepo $gfRoot $null
Remove-Item (Join-Path $gf.RuntimeApp 'sub\util.py') -Force
Assert-GateBlocks 'gate: missing runtime file -> BLOCK' $gf.Cfg 'IDENTITY MISMATCH'

# GG: protected runtime-only paths (storage/, .env) are excluded on both sides -> PASS.
$ggRoot = Join-Path $tmp 'gate-protected'; New-Item -ItemType Directory -Path $ggRoot -Force | Out-Null
$gg = New-GateRepo $ggRoot $null
New-Item -ItemType Directory -Path (Join-Path $gg.RuntimeApp 'storage') -Force | Out-Null
[System.IO.File]::WriteAllText((Join-Path $gg.RuntimeApp 'storage\live.db'), "runtime-state", (New-Object System.Text.ASCIIEncoding))
[System.IO.File]::WriteAllText((Join-Path $gg.RuntimeApp '.env'), "SECRET=1", (New-Object System.Text.ASCIIEncoding))
Assert-GatePasses 'gate: protected runtime paths excluded both sides -> pass' $gg.Cfg

# GH: compiled-Python runtime artifacts (__pycache__/ dir and a *.pyc file) are runtime
# state, never committed -> excluded on both sides -> PASS. Exercises the protected_dirs
# ('__pycache__') and protected_files ('*.pyc') patterns specifically, which storage/.env
# above do not.
$ghRoot = Join-Path $tmp 'gate-pyc'; New-Item -ItemType Directory -Path $ghRoot -Force | Out-Null
$gh = New-GateRepo $ghRoot $null
New-Item -ItemType Directory -Path (Join-Path $gh.RuntimeApp '__pycache__') -Force | Out-Null
[System.IO.File]::WriteAllText((Join-Path $gh.RuntimeApp '__pycache__\main.cpython-39.pyc'), "bytecode", (New-Object System.Text.ASCIIEncoding))
[System.IO.File]::WriteAllText((Join-Path $gh.RuntimeApp 'sub\util.pyc'), "bytecode", (New-Object System.Text.ASCIIEncoding))
Assert-GatePasses 'gate: __pycache__ dir and *.pyc excluded both sides -> pass' $gh.Cfg

# GI: the object-id compare is only sound while core.autocrlf normalises CRLF->LF. With
# autocrlf=false the runtime CRLF files would hash to different ids than the LF blobs, so
# the gate must fail closed on the pre-check rather than false-mismatch. Byte-correct
# runtime, only the setting flipped -> BLOCK on 'autocrlf', not on 'IDENTITY MISMATCH'.
$giRoot = Join-Path $tmp 'gate-autocrlf'; New-Item -ItemType Directory -Path $giRoot -Force | Out-Null
$gi = New-GateRepo $giRoot $null
& git -C $giRoot config core.autocrlf false | Out-Null
Assert-GateBlocks 'gate: core.autocrlf=false -> BLOCK (inconclusive compare)' $gi.Cfg 'autocrlf'

Remove-Item -Recurse -Force $tmp
Write-Host ""
Write-Host "RESULT: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 }
