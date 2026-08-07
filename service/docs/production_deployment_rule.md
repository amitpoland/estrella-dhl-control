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
| Git / verify tree | `C:\PZ-verify` (owns the repo `.git`; verification-read only — **never** a deploy source) |
| Deploy source | `C:\PZ-main` — clean `main`, ff-only; the ONLY source of deploy bytes |
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
6. **No ad hoc deletion, overwrite, or mirror operation.**  Production application files may be
   removed or overwritten only by the canonical gated convergence in `Deploy-PZ.ps1`, after the
   destination-only inventory has classified every extraneous path, with every protected path in
   Rule 8 excluded.  All other synchronization is non-destructive.
7. **Never invoke `robocopy /MIR` manually or outside the canonical gated convergence.**  There
   are no exceptions outside `Deploy-PZ.ps1`.
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

## Post-incident deployment source rules (PERMANENT — added 2026-07-07)

Origin: 2026-07-07 incident — a `robocopy /XO` sourced from a **feature-branch worktree**
(`feat/product-master-authority-tests`, not `main`) left `C:\PZ\app` version-skewed: a stale
`main.py` imported a 0-byte `routes_wfirma_reservation.py` → `ImportError` → PZService failed to
start. These rules are mandatory for every deploy AND every recovery sync.

1. **Never deploy from a feature-branch worktree.** The sync source app tree must be a
   checkout of clean `main` (or an explicitly approved release SHA) — never a feature/PR branch
   or a scratch worktree.
2. **Deployment source must be clean `main` or an explicitly approved release SHA** — fully
   merged, `git pull --ff-only`, internally consistent (no partial/held commits).
3. **No `/XO` — ever — for any production app sync.** `/XO` copies newer-only and SKIPS
   stale/mismatched files → version skew (the 2026-07-07 root cause); it lives in the executor's
   `forbidden_flags` without exception. Exact convergence to the reviewed source is achieved by
   the canonical gated `/MIR` in `Deploy-PZ.ps1` — after the destination-only inventory has
   classified every extraneous path, with every protected path in Rule 8 excluded — never by a
   manual overwrite or a `/XO` top-up.
4. **Verify the source BEFORE any sync** — all three must be clean/expected:
   ```bash
   git branch --show-current      # MUST be: main (or the approved release ref)
   git status --short             # MUST be empty (clean working tree)
   git rev-parse HEAD             # record + confirm the SHA being deployed
   ```
5. **Verify the deployed app IMPORTS cleanly AFTER sync, BEFORE any feature validation:**
   ```powershell
   sc.exe query PZService                          # STATE : RUNNING
   Get-Content C:\PZ\logs\pz_stderr.log -Tail 30   # NO ImportError / module-load traceback
   ```
   Any import failure → STOP, do not validate features; the tree is inconsistent — re-run the
   canonical `Deploy-PZ.ps1` convergence from clean `main` (never a `/XO` copy), then re-verify.

---

## Deployment Identity Gate (PERMANENT — added 2026-07-07)

**Before any sync, capture and record the deployment identity. ABORT if any field does not
match the approved deployment source.**

```bash
git remote -v | head -1          # Repository + Remote (must be the canonical origin)
git branch --show-current        # Branch — MUST be main (or the approved release ref)
git rev-parse HEAD               # HEAD SHA
git rev-parse origin/main        # origin/main SHA — HEAD MUST equal this (or the approved SHA)
git status --short               # Working-tree status — MUST be empty (clean)
```

Record all six: **Repository · Remote · Branch · HEAD SHA · origin/main SHA · Working-tree status.**
Proceed ONLY if: Branch = `main` (or approved SHA) · HEAD == origin/main (or approved SHA) · tree
clean. **Any mismatch → ABORT (do not sync).** This is the gate that would have stopped the
2026-07-07 feature-branch-source skew.

### Pre-backup production identity gate (PERMANENT — added 2026-07-31)

The identity check above governs the **source** side. The deployment authority also enforces
the **production** side automatically, at deploy time, before it stops the service or takes a
backup: it proves the current production application tree is exactly the tree of the commit
recorded in production's version marker.

Why it is required: the backup unit records `restored_sha` by *reading* the version marker, not
by re-deriving it from the bytes it backs up. If production were a HYBRID — marker says commit
X but some runtime files are actually commit Y, e.g. an out-of-band copy that bypassed the
authority — a normal deploy would back those bytes up mislabelled X, and a later rollback would
stamp production with an identity that does not match its own files. The gate makes that state
fail closed at the top of the deploy instead of minting a mislabelled, effectively
unrollbackable unit.

How it decides (EOL-robust): the deploy artifact is synced from a working tree, so runtime text
files carry the platform CRLF while committed blobs are LF; a raw byte compare would
false-mismatch on every text file. The gate instead compares **git object ids** — the committed
blob id of each tracked application file versus the id produced by hashing each runtime file
through the same repository's clean filter — so a byte-correct file matches regardless of line
endings. That normalisation depends on the source repo's `core.autocrlf` being `true` or
`input`; the gate reads the setting first and **fails closed** if it is anything else, rather
than risk an inconclusive compare. Runtime-only state (storage, logs, `.env`, `__pycache__`,
everything named in `protected_dirs` / `protected_files`, plus the leaves of
`protected_runtime_paths`) is excluded on both sides. The check is read-only and runs in plan
mode too — it writes nothing and drives no service.

It **fails closed** (BLOCKED, deploy aborts with production untouched and the service still
running) when: the version marker is absent or is not a single 40-hex SHA; the recorded SHA is
not a commit in the source repository; the production application tree is missing; or any single
runtime file is changed, missing, or extraneous relative to the recorded commit. An identity is
never inferred from a partial match. The gate is skipped only for a first-ever `-Bootstrap`
deploy, where there is no prior tree to verify.

**Recovery from a BLOCKED identity gate.** A block means production is not the single tree its
marker claims — do **not** retry the straight deploy, which would only re-hit the gate (or, if
the gate were bypassed, bake the hybrid into a mislabelled backup). The gate's invariant is
runtime bytes **==** the *recorded marker*, so reconciliation has to restore BOTH sides to one
provable commit, not just the files — converging the tree while leaving the marker stale would
still block (now correctly, runtime ≠ marker). Concretely: establish which known commit
production *should* be (call it `Z`); run an operator-authorised convergence of the runtime tree
to `Z` through the deployment authority (gated mirror convergence — see the mirror-convergence
rules above) **and** have the authority write the version marker to `Z` in the same
operator-authorised action, so the tree and its marker are made consistent together. Re-run the
gate: it passes only when the freshly converged tree matches the freshly written marker `Z`.
Only then may an ordinary forward deploy be reconsidered. Reconciliation is a separate
operator-approved action; it never activates carrier APIs and never alters financial, customs,
inventory, accounting, or shipment data.

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
- [ ] Tests pass - required counts from `.claude/contracts/test-baseline.md` (never hardcoded here)
- [ ] No data-loss risk identified
- [ ] Rollback command is written and verified
- [ ] Lead Coordinator has issued written approval
- [ ] The round's outcome is recorded as **gate evidence** and the signed authorization
      is minted from it (below)

### Gate evidence — the machine-checkable record of this round

The checklist above is a human procedure. Since PR #1094 the outcome of a passing round
must additionally be recorded as a strict-JSON **gate evidence** file, because
`sign_deploy_authorization.py` will not mint a `deploy` or `reconcile` authorization
without one — it is validated *before* the signing key is loaded.

- **Schema, storage location, validity window, and the transcription mapping:**
  `.claude/contracts/seven-agent-evidence.md`. Do not re-derive the rules here; that
  file is the authority and this section is a pointer to it.
- **The file records approval only.** A round in which any agent returned HOLD, BLOCK or
  FAIL produces **no evidence file at all**. There is no way to record a non-approving
  verdict, so "the gate ran" and "the gate approved" cannot be confused.
- **Authority model:** evidence gates *signing*; the signed HMAC artifact gates the
  *write*. Evidence never replaces the signature — a file on disk cannot be single-use,
  key-protected, or revoked.
- **It is digest-bound.** The evidence file's SHA-256 is inside the signed body and
  re-checked at deploy time for `deploy` and `reconcile`. Editing, reformatting, moving,
  renaming or deleting it between minting and deploying is a **denial**, not a warning.
  `rollback` is exempt at both ends: it needs no evidence, and any digest recorded for
  one is audit trail that is never re-read.
- **CI is not consulted** by any of this. A red inherited baseline is not a production
  hold; node-ID comparison remains a test-PR merge tool.

**One-time migration, before the first deploy after this landed.** List
`PZ_DEPLOY_AUTH_DIR` and re-mint every `deploy` and `reconcile` authorization minted
beforehand — **regardless of what its `gate_evidence_ref` looks like**. Two independent
reasons: an artifact with no `@sha256:` digest is denied outright, and an artifact that
*does* carry a digest but bound to a Markdown evidence file is still **accepted**,
because the use-time check re-hashes the bytes rather than re-validating the document.
`rollback` artifacts are unaffected, so incident capability survives. Full operator
sequence: `.claude/commands/deploy.md`.

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
PYTHONIOENCODING=utf-8 python test_pz_regression.py    # root golden: must exit 0
python -m pytest tests/test_carrier_*.py -q            # required count: .claude/contracts/test-baseline.md
```

> Counts are NOT recorded here. `.claude/contracts/test-baseline.md` is the sole
> authority; hardcoding them across deploy surfaces is what let three different
> required carrier counts coexist in this repository.
> The deploy source is `C:\PZ-main`, never the verification tree.

**Stop if any test fails.**

### Step 4.5 — Pre-deploy backup

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`, which creates the
> manifest-verified backup unit automatically as part of every deploy.


**Abort deploy on backup failure.** Maximum timeout: 10 minutes. If backup fails or times out, investigate storage health before proceeding. A failed backup means restore capability is compromised.

### Step 5 — Safe sync to production

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


**Forbidden sync operations:**
> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


### Step 6 — Restart PZService (as Administrator)

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


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

### Step 7.5 — V2 runtime boot gate (PERMANENT — added 2026-07-07)

**Vendor authority.** `service/scripts/download-v2-vendor.ps1` is the **canonical vendor
authority** for the /v2/ runtime — it owns the pinned versions of React, ReactDOM, and
`@babel/standalone`. The files under `service/app/static/v2/vendor/` are **generated
artifacts** produced by that script: never hand-edit them; regenerate via the script and keep
it in lock-step with the CDN-fallback pins in `static/v2/index.html`. Guard:
`service/tests/test_v2_babel_pin.py`.

**V2 boots React/ReactDOM/Babel local-first with a CDN fallback. On EVERY V2 deployment,
after sync + restart and BEFORE the V2 module deployment is considered complete, verify ALL:**

```powershell
# 1. Vendor present (real files, not just .gitkeep)
Get-ChildItem C:\PZ\app\static\v2\vendor\*.js | Select Name,Length
#    -> react.production.min.js, react-dom.production.min.js, babel.min.js (all non-zero)
```
Then load `https://pz.estrellajewels.eu/v2/index.html` and confirm in the browser console:
- [ ] **Vendor present** — the three `*.js` above exist and are non-zero.
- [ ] **React loaded** — `window.React.version` is defined.
- [ ] **ReactDOM loaded** — `window.ReactDOM` is defined.
- [ ] **Babel loaded** — `window.Babel` is defined.
- [ ] **Atlas shell booted** — page renders (no boot-guard "Estrella Atlas — JavaScript error").
- [ ] **Local-first confirmed** — `window.__vnd_react`, `__vnd_rdom`, `__vnd_babel` are all **false**
      (vendor served locally; CDN fallback not exercised).

**If any check fails: STOP — do not proceed with V2 module deployment.** The V2 runtime is
broken (missing/mismatched vendor). Regenerate via `download-v2-vendor.ps1` on `C:\PZ`,
re-sync, restart, and re-verify. A true `__vnd_*` flag in production means vendor is absent and
the shell is depending on the external CDN — a reliability regression, not an acceptable state.

---

## Rollback procedures

### Level 1 — Gate-only rollback (instant, no code change)
Revert carrier status to pending via `.env` and restart.

> **Before using Level 2 or Level 3:** a unit created before rollback-provenance
> tracking has no `restored_sha` and no `version.pre.txt`, and the command below will
> **refuse** rather than restore. That refusal is deliberate — see *Rollback provenance*
> and *Legacy unit recovery* below for the two-step preparation that makes such a unit
> restorable. Check the unit first; do not discover this mid-incident.

### Level 2 — Revert last commit
```bash
.\.claude\deploy\Deploy-PZ.ps1 -Rollback -Unit <unit>
# then re-run deploy procedure from Step 5
```

### Level 3 — Revert a named merge
```bash
.\.claude\deploy\Deploy-PZ.ps1 -Rollback -Unit <unit>   # restores a manifest-validated backup; never mutates git
# then re-run deploy procedure from Step 5
```

### Emergency — restore from git directly
> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.

### Rollback provenance (which SHA is which)

A rollback deals with **two distinct SHAs**, and conflating them is a defect:

- **Deployment SHA** (`unit.json.deployment_sha`) — the commit whose deployment
  *created* the backup unit. This is the **authorization** identity: a rollback is
  authorized against the deployment SHA recorded when the backup was taken, never
  against the content being restored. This binding is security-reviewed; it does not
  change without a separate security review.
- **Restored-content SHA** (`unit.json.restored_sha`, corroborated by the write-once
  `version.pre.txt` snapshot beside the backup) — the commit the backed-up bytes
  *actually represent*. This is the value production's version marker is stamped with
  **after** a restore, so the marker matches the bytes on disk.

The two legitimately differ: rolling a newer deployment back to older bytes means
authorizing against the newer deployment SHA while stamping the older content SHA. The
backup records the pre-deployment marker **before** any mutation, because the forward
deploy rewrites the marker at the end and that is the only moment the prior identity is
observable.

**Legacy units and fail-closed behavior.** A backup unit created before provenance
tracking (or one whose pre-deployment marker was unreadable when the backup was taken)
carries no trusted restored-content SHA. Such a rollback is **refused** with an
operator-disposition error rather than proceeding: the deployment SHA is never used as a
silent fallback, and a SHA is never inferred from a filename. When both the metadata
field and the immutable snapshot are present they must agree; a disagreement is refused
as unresolved provenance. Recovery of a legacy unit is operator-directed — establish the
pre-deployment SHA from an independent record before restoring.

**Legacy unit recovery (operator procedure).** Every backup unit created before this
change is legacy. To make one restorable, the operator supplies the missing provenance
by hand, from evidence — never by guessing:

1. **Establish the pre-deployment SHA from an independent record.** Acceptable evidence,
   in order of preference: the deployment closure report for that deploy (records
   "Previous production SHA"); the unit-id prefix of the *immediately preceding* backup
   unit (that unit's deployment SHA is what production was running when this unit was
   cut); the deploy transcript. The unit's **own** id prefix is the deployment SHA — it
   is the wrong value and must not be used. If **no** preceding unit exists — this is the
   oldest unit in the store — the closure report or the deploy transcript is the only
   acceptable evidence; there is nothing on disk to derive it from, and a unit whose
   pre-deployment identity cannot be evidenced is correctly unrecoverable.
2. **Corroborate it.** Confirm the chosen SHA is a real commit (`git cat-file -e <sha>`)
   and that its tree is what production plausibly ran. If the evidence is ambiguous, stop
   — an unrecoverable unit is a correct outcome, a wrongly-stamped one is not.
   Confirm too that the **unit itself** has not been altered since it was created, before
   trusting anything found inside it: its manifests must still validate against its own
   `app\` and `engine\` trees, and its file timestamps should fall inside the deploy
   window recorded in the closure report. Evidence read out of a modified unit is not
   evidence.
3. **Write the snapshot** into that unit only — 40 lowercase hex characters, nothing
   else, at `<backup_root>\<unit>\version.pre.txt`. Leading/trailing whitespace and a
   BOM are tolerated by the reader; any other content is refused. This writes inside the
   backup unit, never to production's version marker.
4. **Re-run the rollback.** The resolver now finds the snapshot and proceeds. If
   `unit.json` also carries a `restored_sha`, the two must agree — a disagreement is
   refused, and reconciling it is an evidence question, not a file-editing one.
   The rollback authorization minted for the first (refused) attempt is normally still
   **unconsumed**: a legacy unit throws out of provenance resolution *before* the
   authorization is checked, so nothing was spent. Re-check its TTL rather than assuming
   it must be re-minted — and equally, do not assume it survived, since a refusal later
   than provenance resolution would have consumed it.

Recording this in the deployment evidence for the recovery is mandatory: name the
independent record the SHA came from. A restored production whose provenance was
asserted without evidence corrupts every later rollback decision that reads it.

**Closure check.** A rollback verifies its own result: after stamping the marker it
reads the marker back and requires it to equal the restored-content SHA. A mismatch
throws and leaves the service stopped for inspection rather than reporting success on an
inconsistent state.


---

## Required output format for every deployment (Deployment Evidence)

Every deployment report MUST contain all of the following. The first seven are the mandatory
**Deployment Evidence** fields (added 2026-07-07).

> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


---

## Carrier activation — separate protocol

Setting `CARRIER_API_STATUS=shadow` or `CARRIER_API_STATUS=live` in `C:\PZ\.env`
**requires separate coordinator sign-off** per `carrier_production_activation_protocol.md`.
It is not part of the standard deployment procedure.
