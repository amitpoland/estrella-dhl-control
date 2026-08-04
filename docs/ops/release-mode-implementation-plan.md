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

One operator command performs the whole production decision:

```powershell
.\.claude\deploy\Deploy-PZ.ps1 -Release -ReviewedSHA <full-sha> -GateEvidence <path>
```

Final line is exactly one of: `DEPLOYED`, `ALREADY CURRENT`, `ROLLED BACK`, `FAILED SAFE`.

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

Behavioural tests (single-use, evidence binding, wrong-SHA refusal, rollback exemption)
already exist in `service/tests/test_gate_evidence.py` — 37 tests, and the two tamper
tests were verified to fail when the use-time digest re-check is removed.

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
