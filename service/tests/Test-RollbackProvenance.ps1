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

Remove-Item -Recurse -Force $tmp
Write-Host ""
Write-Host "RESULT: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 }
