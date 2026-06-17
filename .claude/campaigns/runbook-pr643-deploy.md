# Deployment Runbook — PR #643 (single resolved-CIF authority)

**Target PR:** [#643](https://github.com/amitpoland/estrella-dhl-control/pull/643) `feat/cif-authority-consistency-guard`
**Pre-merge tip:** `f4dbae2` · base `main` · state OPEN / MERGEABLE / CLEAN
**Deploy surface:** `service/app/**` only (6 files) → `C:\PZ\app` standard robocopy. No schema, no `.env`, no root-engine files.
**Environment:** Production `C:\PZ` · service `PZService` (NSSM, port 47213) · public `https://pz.estrellajewels.eu` · git/hash source-of-truth `C:\PZ-verify`
**Hard ordering rule:** Steps 1→2→3→4 are sequential gates. **Step 6 (PZ / wFirma) is BLOCKED until Steps 1–4 are each VERIFIED.** Step 5 (state update) runs after Step 4.

> **Authority boundary (permanent):** prod writes into `C:\PZ` are **operator-only** — the deploy-guard hook blocks agent writes. The agent prepares, stages, and hands the operator the exact command blocks, then performs **read-only** post-deploy verification. The agent never reports "deployed" until the production hash flips.

---

## STEP 0 — Pre-flight (owner: agent; approval: operator)

**Do before anything merges.**

1. Confirm GATE 2 has a free slot (≤3 implementation PRs open).
2. Confirm `C:\PZ-verify` is clean and on `main`:
   ```
   cd C:\PZ-verify
   git status --short            # must be empty
   git rev-parse --abbrev-ref HEAD   # must be main
   ```
3. Record the **current production SHA** (rollback anchor) — read-only:
   ```
   cd C:\PZ-verify && git rev-parse origin/main
   ```
   Capture as `PROD_SHA_BEFORE`. Also snapshot the deployed hash of one touched file for the post-deploy flip check:
   ```
   Get-FileHash C:\PZ\app\services\cif_authority.py  # expect: file ABSENT pre-deploy (new file)
   Get-FileHash C:\PZ\app\api\routes_dsk.py          # capture pre-deploy hash
   ```

**VERIFIED when:** free GATE-2 slot confirmed, `C:\PZ-verify` clean on main, `PROD_SHA_BEFORE` recorded, pre-deploy hashes captured.
**STOP if:** verify tree dirty or not on main → do not proceed; reconcile first.

---

## STEP 1 — Merge #643, capture squash SHA (owner: operator)

**Decision point:** proceed only if the governance review is COMPLIANT and PR is MERGEABLE/CLEAN.

1. Operator squash-merges via GitHub UI or:
   ```
   gh pr merge 643 --squash --delete-branch
   ```
2. Capture the **real squash SHA** on main:
   ```
   cd C:\PZ-verify
   git fetch origin
   git checkout main && git pull --ff-only origin main
   git rev-parse HEAD                # → SQUASH_SHA  (record this)
   git log -1 --oneline              # confirm headline = the #643 squash commit
   ```

**VERIFIED when:** `gh pr view 643 --json state -q .state` == `MERGED`; `SQUASH_SHA` recorded; `C:\PZ-verify` fast-forwarded to it with a clean tree.
**Rollback condition:** none yet — nothing deployed. If the wrong PR merged, `git revert SQUASH_SHA` on a branch → new PR.

---

## STEP 2 — 7-agent deploy gate against `SQUASH_SHA` (owner: deploy_lead_coordinator)

Run `/deploy` so the gate evaluates **the real merged SHA on main**, not the pre-merge branch tip. All 7 run in parallel; each returns a verdict block.

| # | Agent | Owns | Blocker authority |
|---|---|---|---|
| 1 | `deploy_lead_coordinator` | Final GO/NO-GO synthesis | Decides; cannot override #5 |
| 2 | `deploy_git_diff_reviewer` | File classification, forbidden paths | NO-GO on forbidden path |
| 3 | `deploy_backend_impact_reviewer` | Routes, auth guards, router registration, imports | NO-GO on broken route/auth |
| 4 | `deploy_persistence_storage_reviewer` | Schema/storage writes | NO-GO on unmigrated schema |
| 5 | `deploy_security_reviewer` | Credentials, auth removal, injection | **Absolute** — cannot be overridden |
| 6 | `deploy_qa_reviewer` | Test pass/fail vs `.claude/contracts/test-baseline.md` (PZ regression 160 required) | NO-GO on any test failure |
| 7 | `deploy_release_manager` | Branch hygiene, ff-only, robocopy plan, **rollback command for `SQUASH_SHA`**, post-deploy checklist | NO-GO on dirty tree |

**What GO looks like — all of:**
- `deploy_lead_coordinator` issues a written **GO** decision naming `SQUASH_SHA`.
- Agents 2–4: diff is `service/app/**`-only (6 files), auth decorators intact, **no** schema/storage writes, **no** forbidden paths.
- Agent 5 (security): no credential/auth/injection finding — **GO**.
- Agent 6 (QA): test baseline met, **zero** new failures (the 73 targeted pass; pre-existing env failures unchanged).
- Agent 7: `C:\PZ-verify` clean on `main` at `SQUASH_SHA`, robocopy plan + exact rollback command produced.

**VERIFIED when:** coordinator's written GO references `SQUASH_SHA` and all 6 sub-agents are non-blocking.
**Recognize NO-GO:** any single agent returns BLOCK; security BLOCK is final. → halt, remediate (likely a follow-up PR), re-merge, re-run gate. Do **not** deploy on a partial gate.

---

## STEP 3 — Deployment execution (owner: operator; prerequisite: Step 2 GO)

> Agent prepares the clean release worktree and **hands the operator** the command block. Operator executes the `C:\PZ` writes. Agent does not touch `C:\PZ`.

1. **Backup current prod** (operator):
   ```
   robocopy C:\PZ C:\PZ-backup-<SQUASH_SHA-short> /MIR /XD .git
   ```
2. **Clean release tree** (robocopy clean-tree rule — never sync from a dev checkout):
   ```
   git worktree add C:\PZ-release origin/main      # at SQUASH_SHA
   cd C:\PZ-release && git status --short           # MUST be empty
   ```
3. **Sync `service/app` → `C:\PZ\app`** (operator):
   ```
   robocopy C:\PZ-release\service\app C:\PZ\app /MIR /XD __pycache__ /XF *.pyc
   ```
   (No engine-root / requirements / schema sync — none in this diff.)
4. **Restart service** (operator):
   ```
   nssm restart PZService
   ```

**VERIFIED when (read-only, agent performs):**
- Production hash **flips** to match the release tree:
  ```
  Get-FileHash C:\PZ\app\services\cif_authority.py   # now PRESENT, matches C:\PZ-release
  Get-FileHash C:\PZ\app\api\routes_dsk.py           # differs from pre-deploy hash
  ```
  (LF-normalize before comparing to manifest pins — Windows checkout is CRLF.)
- `PZService` is RUNNING on port 47213; health endpoint responds.

**Rollback condition (any):** service fails to start, health check fails, or hash does not flip → restore:
```
robocopy C:\PZ-backup-<...> C:\PZ /MIR /XD .git ; nssm restart PZService
```
Then `git revert SQUASH_SHA` (release_manager's exact command) → new PR. Do not advance to Step 4 on a failed deploy.

---

## STEP 4 — Real-shipment verification: AWB 2315714531 (owner: agent, read-only; sign-off: operator)

The canonical regression fixture. All assertions are read-only against the live service.

| # | Assertion | How to confirm | PASS criterion |
|---|---|---|---|
| 4.1 | **Resolved CIF == USD 732** | Inspect `get_cif_authority(audit)` / action_diagnostics for the batch | `cif_usd == 732.0`, `cif_source == awb_customs.value_usd`, `cif_state == resolved` |
| 4.2 | **`total_value_usd` ≠ 0.0** | Customs/DSK action surfaces for the shipment | No surface returns `total_value_usd=0.0`; no "CIF = 0.00" false block |
| 4.3 | **DSK uses resolved authority** | DSK button + `generate_dsk` | Button **enabled**, reason "Ready — CIF value available"; generate succeeds with `value_source=cif_authority:awb_customs.value_usd` |
| 4.4 | **Polish Description uses resolved authority** | `generate_description` | Proceeds (no 422 on resolved); document reflects 732, not 0 |
| 4.5 | **Negative control** | A genuinely unresolved shipment (no invoice total, AWB gap) | Still **blocks** with `422 code=cif_unresolved` + next-action; never silent zero |

**VERIFIED when:** 4.1–4.5 all PASS and operator signs off.
**Rollback condition:** 4.1–4.4 fail (resolved shipment still blocked or shows 0) → the authority model is not live → roll back per Step 3, file a follow-up. A 4.5 failure (unresolved shipment now proceeds) is a **security/compliance** regression → immediate rollback.

---

## STEP 5 — PROJECT_STATE update via flow-context-keeper (owner: agent; RULE 3)

Fire **after** Step 4 sign-off. Carry on a PR branch (direct-to-main `chore(memory)` is denied).

Record into `PROJECT_STATE.md`:
- **FACTS (append):** "#643 squash-merged as `SQUASH_SHA`, deployed to `C:\PZ\app`, prod hash flipped; AWB 2315714531 verified resolved CIF=732 / `total_value_usd`≠0 / DSK + Polish-desc on resolved authority; negative control blocks `cif_unresolved`." Record `PROD_SHA_BEFORE` → `SQUASH_SHA` transition.
- **OPEN QUESTIONS:** resolve `OQ-PR643-MERGE` (merged + verified); `OQ-PR643-TEST-COVERAGE-REVIEWER` carries forward unchanged.

**VERIFIED when:** `flow-context-keeper` returns, the FACTS block exists on disk (Lesson C), and the cited scorecard path resolves.

---

## STEP 6 — BLOCKER: no PZ / wFirma action until Steps 1–4 are VERIFIED

**Explicit gate.** No `pz_create`, PZ preview/adopt, wFirma document write, or any customs/PZ posting may run until:

- [ ] Step 1 — #643 MERGED, `SQUASH_SHA` recorded
- [ ] Step 2 — coordinator GO on `SQUASH_SHA`, all 6 sub-agents non-blocking
- [ ] Step 3 — prod hash flipped, `PZService` healthy
- [ ] Step 4 — AWB 2315714531: 4.1–4.5 all PASS, operator signed off

Until every box is checked, treat PZ/wFirma actions as **hard-blocked**. Rationale: this PR makes the resolved CIF the single customs-value authority; running a PZ/wFirma write before the authority is live-verified risks posting against the exact stale/zero customs value the campaign exists to eliminate. Step 5 (state) does **not** gate Step 6, but Steps 1–4 do.

---

## Ownership & escalation summary

| Concern | Owner |
|---|---|
| Merge decision, all `C:\PZ` writes, restart, sign-off | **Operator** |
| GO/NO-GO synthesis | `deploy_lead_coordinator` |
| Security veto (non-overridable) | `deploy_security_reviewer` |
| Test baseline | `deploy_qa_reviewer` |
| Rollback command + robocopy plan | `deploy_release_manager` |
| Release-tree prep, read-only verification, PROJECT_STATE update | Agent |

**Global rollback anchor:** `PROD_SHA_BEFORE` (Step 0) + `C:\PZ-backup-<...>`. Helper is additive; revert restores prior inline logic with no resolver/routing change — the only consequence is the raw-zero false-block returning for AWB-only-resolved shipments.
