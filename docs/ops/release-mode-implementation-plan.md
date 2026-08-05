# `Deploy-PZ.ps1 -Release` — implementation plan

**Status:** plan only. The PowerShell in this document is **not written yet** and must be
authored in a session with PowerShell available, because it cannot be parse-checked
otherwise (see *Why this is a plan* below).

**Already landed** (Python, fully tested on any OS):
`.claude/hooks/gate_evidence.py`, the signer/verifier wiring, and
`.claude/contracts/seven-agent-evidence.md`. `-Release` consumes these; it does not
reimplement them.

---

## Goal

One operator command, run **on the Windows production host**, performs the whole
production decision:

```powershell
.\.claude\deploy\Deploy-PZ.ps1 -Release -ReviewedSHA <full-sha>
```

Final line is exactly one of: `DEPLOYED`, `ALREADY CURRENT`, `ROLLED BACK`, `FAILED SAFE`.

**Windows-specific by design.** Production runtime `C:\PZ`; source checkout `C:\PZ-main`;
service `PZService`; surfaces `C:\PZ\app` and `C:\PZ\engine`; tooling is PowerShell,
robocopy and Windows service control. Browser verification happens only after the service
is restarted and closure passes.

### No `-GateEvidence` parameter — the script finds the approval

The command takes only `-ReviewedSHA`. `-Release` therefore has to **locate** the
seven-agent approval for that SHA rather than be handed a path, which needs a
convention:

- Add `gate_evidence_dir` to `windows_prod_v2.json` (e.g. `C:\PZ-secrets\gate-evidence`).
- `-Release` reads `<gate_evidence_dir>\<sha>.json` and validates it via `gate_evidence.py`.
  Evidence is strict JSON — schema in `.claude/contracts/seven-agent-evidence.md`.
  A Markdown report is not evidence and is refused outright, not partially read.
- Absent or invalid → `FAILED SAFE` before any lock, artifact, backup or service change.

**Config-schema caution.** `Get-DeployConfig` requires every key in its `$required`
list and pins `schema_version -eq 2`. Adding `gate_evidence_dir` to that list makes
every existing config file invalid. Either add it as optional-with-default, or bump
`schema_version` to 3 and update the config in the same change — do not add it to
`$required` silently.

Evidence still gates **signing**, not the write: `-Release` validates the file, then
mints the signed single-use authorization internally, which is what `Assert-Authorization`
consumes. The operator never runs the signer by hand.

## Authority model (settled)

Evidence gates **signing**; the signature gates the **deploy**. `-Release` mints the
existing signed, single-use, SHA-bound authorization internally after validating
evidence — it does not replace it. CI is never consulted.

## Why this is a plan, not a patch

`Deploy-PZ.ps1` is 1441 lines and is the sole production execution and rollback
authority: it stops `PZService` and writes `C:\PZ`. The 73-test deploy-authority suite
verifies it by **reading it as text**, never by parsing or executing it — so that suite
goes green on PowerShell that does not parse. There is no automated check anywhere in
this repository that would catch a syntax error in new `-Release` code. Author it where
`pwsh -NoProfile -Command { … }` parse validation is available.

---

## Most of the 13-step sequence already exists

`Invoke-Deploy` (line 1289) already implements the ordinary path in almost exactly the
requested order, with the safety reasoning written into the code:

| requested step | already implemented | where |
|---|---|---|
| 1 read seven-agent approval | **NO — new** | — |
| 2 prove running runtime identity | yes | `Assert-ProductionMatchesRecordedSha`, under the lock, before any write (1320) |
| 3 compare app + engine files by hash | yes | `Test-RuntimeUnchanged` (1361); hashes all 16 engine files |
| 4 stop if everything matches | yes | runtime no-op short-circuit, returns without stopping the service (1361–1385) |
| 5 create backup | yes | `New-BackupUnit` (1392) |
| 6 stop `PZService` | yes | `Set-ServiceState -Target Stopped` (1388) |
| 7 robocopy the immutable artifact | yes | `Invoke-Converge` (1408) |
| 8 sync governed engine files | yes | `Invoke-EngineSync` (1409) |
| 9 verify hashes | yes | `Test-AgainstManifest` (1411) |
| 10 update `version.txt` | yes | `Write-VersionFile` (1413) |
| 11 start `PZService` | yes | `Set-ServiceState -Target Running` (1414) |
| 12 run closure automatically | **NO — new** (currently a printed hint, 1432) |
| 13 one final result line | **NO — new** (prints `DEPLOY COMPLETE` + hints) |

So `-Release` is genuinely an orchestrator: steps 2–11 exist and are already correctly
ordered. The new work is steps 1, 12, 13, internal signing, and identity *resolution*.

### One ordering correction

The requested sequence lists **backup (5) before stop (6)**. The existing code does the
reverse — `Set-ServiceState -Target Stopped` (1388) then `New-BackupUnit` (1392) — and
that order is the safer one: backing up a **running** service risks a torn copy of files
being written (SQLite databases mid-transaction, open logs), producing a backup that
cannot be restored cleanly. The rollback path is the one thing that must never be
subtly corrupt.

**Recommendation: keep stop-before-backup.** If the intent behind 5-before-6 was "take
the backup before anything destructive happens", that property already holds — the
backup is taken before `Invoke-Converge`, which is the first step that modifies
production. Nothing is written between the stop and the backup.

What *must* stay ahead of the backup is the identity gate, and it does (1320): backing
up an unproved tree is how a unit gets minted with one commit's label and another
commit's bytes.

## Reuse map — every step already has an implementation

| Plan step | Existing function | Notes |
|---|---|---|
| SHA is on `origin/main` | `Assert-ReviewedTarget` | already refuses recomputing the target |
| source tree sane | `Invoke-Preflight` | branch/dirty/local-only checks |
| prove runtime identity | `Assert-ProductionMatchesRecordedSha` | the identity gate |
| detect real delta | `Test-RuntimeUnchanged` | **already hashes all 16 engine files** and fails safe toward *deploy* on any uncertainty |
| authorization | `Assert-Authorization` | calls `deploy_authorization.py`, which now enforces the evidence digest |
| stage artifact | `New-ReleaseArtifact` | immutable, hash-manifested |
| backup | `New-BackupUnit` | |
| converge app | `Invoke-Converge` | |
| converge engine | `Invoke-EngineSync` | |
| record identity | `Write-VersionFile` | |
| ordinary path | `Invoke-Deploy` | |
| drift repair | `Invoke-Reconcile` | pair-bound |
| closure | `Test-PZDeployClose.ps1` | currently a separate operator step |

Only two genuinely new pieces are required.

### New piece 1 — `Assert-SevenAgentEvidence`

Do **not** reimplement the rules in PowerShell. Shell out to the tested Python, exactly
as `Assert-Authorization` already shells out to `deploy_authorization.py`:

```powershell
function Assert-SevenAgentEvidence {
    param($Cfg, [string]$Sha, [string]$EvidencePath)
    $helper = Join-Path (Split-Path $PSScriptRoot -Parent) "hooks\gate_evidence_cli.py"
    $out = & python $helper $EvidencePath $Sha 2>&1
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: $out" }
    Write-Host "  gate evidence: $out"
}
```

This needs a thin CLI wrapper (`gate_evidence_cli.py`, ~15 lines) around
`validate_evidence()`. Two implementations of these rules would be two sources of truth,
and the PowerShell copy is the one that cannot be unit-tested.

### New piece 2 — deterministic runtime identity resolver

`Assert-ProductionMatchesRecordedSha` answers *"does production match **this** SHA?"*.
`-Release` needs *"**which** SHA is production?"* so it can choose deploy vs reconcile
without the operator supplying `-FromSha`.

```
Resolve-RuntimeIdentity($Cfg) -> <40-hex> | "UNKNOWN"
```

- Candidates: the version marker's SHA first, then commits on `origin/main` reachable
  from the target (bounded — do not walk all history).
- For each candidate, compare `C:\PZ\app` by **git object id**, the same mechanism the
  existing identity gate uses.
- Compare all 16 governed engine files by hash.
- Return the single exact match, or `UNKNOWN`.
- **Never infer identity from `version.txt` alone** — that is the Lesson Q episode-1
  failure: the marker is what a previous deploy *claimed*, not what the bytes *are*.

## Decision table

| runtime identity | vs target | action | final line |
|---|---|---|---|
| resolves, bytes == target | equal | nothing: no stop, no copy, no restart | `ALREADY CURRENT` |
| resolves, == marker, differs from target | behind | ordinary deploy | `DEPLOYED` |
| resolves to another known SHA (marker disagrees) | drifted | reconcile, pair-bound | `DEPLOYED` |
| `UNKNOWN` | — | stop before any write; **do not consume authorization** | `FAILED SAFE` |
| any failure after convergence began | — | rollback | `ROLLED BACK` |

`ALREADY CURRENT` must be reached **before** `Enter-DeployLock`, service stop, artifact
staging or authorization minting. A no-op that restarts the service is not a no-op.

## Ordering constraints

1. Preflight → evidence → target assertion → **identity resolution** → delta check.
   Only then mint authorization. Minting before the decision would burn a single-use
   artifact on a run that turns out to be `ALREADY CURRENT`.
2. Identity must be proved **before** `New-BackupUnit`. A backup minted against an
   unproved runtime is the mislabelled-backup failure that `-Reconcile` exists to
   prevent.
3. Closure (`Test-PZDeployClose.ps1`) runs **before** `DEPLOYED` is printed. A closure
   failure must print `ROLLED BACK` or `FAILED SAFE`, never `DEPLOYED`.

## Tests to add to `test_deploy_authority.py`

Text assertions in the existing style (these do not need PowerShell):

- `-Release` and `-GateEvidence` exist in the param block.
- `-Release` sets `-Reconcile`/`-FromSha`/`-ToSha` internally and does not require them.
- The script contains no reference to CI, workflow runs, or node IDs.
- `Assert-SevenAgentEvidence` is called before `Assert-Authorization`.
- `Resolve-RuntimeIdentity` returning `UNKNOWN` reaches no write function.
- `Test-PZDeployClose.ps1` is invoked on the `-Release` path.
- All 16 `engine_files` participate in identity and closure.
- Still exactly one `.ps1` deployer.

Behavioural tests (schema validation, single-use, evidence binding, wrong-SHA refusal,
rollback exemption) already exist in `service/tests/test_gate_evidence.py` — 134 tests,
each mutating one field of a valid document and asserting refusal. Twelve independent
mutations of `gate_evidence.py` (duplicate-key hook removed, unknown-field checks
disabled, agent names normalised, expiry ignored, SHA comparison skipped, second read
reintroduced, …) were each verified to fail the suite, so it distinguishes a strict
validator from a permissive one rather than only exercising the happy path.

## Documentation to update

`CLAUDE.md` production deployment rule and `service/docs/production_deployment_rule.md`:
state that the seven-agent gate authorizes production, CI does not, and a red inherited
baseline is not a hold. Node-ID comparison stays described as a test-PR merge tool.

## First live use

1. `-Release -WhatIf` — confirm the decision line only; no lock, no artifact, no write.
2. Same command without `-WhatIf`.
3. Read-only Chrome smoke test. No wFirma posting, invoice conversion, customs
   submission, inventory mutation, or accounting write.

Operator approval remains required before merging deploy-authority changes, using the
real signing key, stopping `PZService`, writing `C:\PZ\app` or `C:\PZ\engine`, or
executing rollback.
