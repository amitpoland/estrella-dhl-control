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
| Deploy source | `C:\PZ-main` - clean `main`, ff-only; the ONLY source of deploy bytes |
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
7. **Never use `robocopy /MIR` outside the gated convergence.**  Forbidden without exception.
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
3. **No `/XO` for a full app sync or a recovery sync.** `/XO` copies newer-only and SKIPS
   stale/mismatched files → version skew (the 2026-07-07 root cause). A full/recovery app sync
   must OVERWRITE to match the source exactly (still no `/MIR`; still exclude the forbidden
   paths in Rule 8). `/XO` is permitted ONLY for a known-incremental top-up where the dest is
   already a consistent subset of the source.
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
   Any import failure → STOP, do not validate features; the tree is inconsistent — re-sync from
   clean `main` with an overwriting (non-`/XO`) copy, then re-verify.

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

### Level 2 — Revert last commit
```bash
Deploy-PZ.ps1 -Rollback -Unit <unit>
# then re-run deploy procedure from Step 5
```

### Level 3 — Revert a named merge
```bash
Deploy-PZ.ps1 -Rollback -Unit <unit>   # restores a manifest-validated backup; never mutates git
# then re-run deploy procedure from Step 5
```

### Emergency — restore from git directly
> Commands removed. Execution is `.claude/deploy/Deploy-PZ.ps1`;
> configuration is `.claude/deploy/windows_prod_v2.json`.
> This document defines governance only.


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
