# Deployment Runbook — PR #643 (single resolved-CIF authority)

**Target PR:** [#643](https://github.com/amitpoland/estrella-dhl-control/pull/643) `feat/cif-authority-consistency-guard`
**Deploy surface:** `service/app/**` only (6 files) → `C:\PZ\app` standard robocopy. No schema, no `.env`, no root-engine files.
**Environment:** Production `C:\PZ` · service `PZService` (NSSM, port 47213) · public `https://pz.estrellajewels.eu` · git/hash source-of-truth `C:\PZ-verify`
**Hard ordering rule:** Steps 1→2→3→D-1→4 are sequential gates. **Step 6 (PZ / wFirma) is BLOCKED until Steps 1–4 + D-1 are each VERIFIED.** Step 5 (state update) runs after Step 4.

> **Authority boundary (permanent):** prod writes into `C:\PZ` are **operator-only** — the deploy-guard hook blocks agent writes. The agent prepares, stages, and hands the operator the exact command blocks, then performs **read-only** post-deploy verification. The agent never reports "deployed" until D-1 cryptographic hash proof passes.

---

## Validated facts (confirmed before this runbook governs)

| Fact | Status |
|---|---|
| PR #643 is **independent of** PR #640 (`fix/invoice-image-only-lineitem-extraction`) | ✅ — #643 may be reviewed, merged, deployed, and verified without #640. Separate branches, non-overlapping diffs. |
| PR #640 is the prerequisite for the invoice-confirmation workflow + eventual AWB 2315714531 **accounting recovery path** | ✅ — but NOT for the CIF authority deploy. Different stream. |
| DEPLOY CHECKPOINT D-1 **replaces** operator-reported deploys | ✅ — LF-normalized SHA256 proof is the only accepted "deployed" signal. |
| Path A (merge #643 → gate → deploy → D-1 → AWB) is the approved path | ✅ |
| `RELEASE_WORKTREE` is a **clean detached git worktree at `SQUASH_SHA`**, not a fixed filesystem path | ✅ — resolve dynamically via `git rev-parse HEAD` inside it. |

---

## THE 5 HARD RULES (enforced, numbered, non-negotiable)

1. **D-1 hash verification must PASS before any AWB verification attempt.** A reported deploy is not a verified deploy.
2. **No AWB 2315714531 verification until D-1 passes.** The shipment fixture proves the authority is live *only after* the prod hash flip is cryptographically confirmed.
3. **No PZ / wFirma progression until AWB verification passes.** `pz_create`, PZ preview/adopt, any wFirma document write stays hard-blocked through Step 4 sign-off.
4. **No new campaigns while #643, #640, #630, #637 fill the queue.** This rule governs *opening new implementation work* — it is **not** a deploy gate (see Step 0).
5. **#640 and #643 must NEVER be mixed in the same deployment.** Separate branches, separate gates, separate deploys, separate verifications.

---

## STEP 0 — Pre-flight (owner: agent prep; approval: operator)

1. **Confirm no new implementation campaign has been opened since the validated governance snapshot.**
   GATE 2 is **not** a deploy gate — a full queue (#643 / #640 / #630 / #637 already open) does **not** block deploying an already-open PR. The check here is only that no *additional* campaign slipped in since the snapshot that this deploy was validated against.
2. Confirm `C:\PZ-verify` is clean and on `main`:
   ```
   cd C:\PZ-verify
   git status --short                # must be empty
   git rev-parse --abbrev-ref HEAD   # must be main
   ```
3. Record the **current production SHA** (rollback anchor) — read-only:
   ```
   cd C:\PZ-verify && git rev-parse origin/main
   ```
   Capture as `PROD_SHA_BEFORE`. (Used as a rollback anchor only — **not** as the deploy-surface source; see D-1.)

**VERIFIED when:** no new campaign opened since snapshot, `C:\PZ-verify` clean on main, `PROD_SHA_BEFORE` recorded.
**STOP if:** verify tree dirty or not on main → do not proceed; reconcile first.

---

## STEP 1 — Merge #643, capture squash SHA (owner: operator)

**Decision point:** proceed only if the governance review is COMPLIANT and PR is MERGEABLE/CLEAN.

1. Operator squash-merges:
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

**Rule 5 guard:** confirm the merged headline is the CIF guard, NOT the image-only extraction PR (#640). If #640 merged by mistake → halt; this deploy is #643-only.
**VERIFIED when:** `gh pr view 643 --json state -q .state` == `MERGED`; `SQUASH_SHA` recorded; `C:\PZ-verify` fast-forwarded with a clean tree.
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
| 6 | `deploy_qa_reviewer` | Validates the **current approved baseline for the target `SQUASH_SHA`** (per `.claude/contracts/test-baseline.md`) | NO-GO on any regression against that baseline |
| 7 | `deploy_release_manager` | Branch hygiene, ff-only, robocopy plan, **rollback command for `SQUASH_SHA`**, post-deploy checklist | NO-GO on dirty tree |

> **QA baseline is not hard-coded in this runbook.** The approved test counts live in the versioned gate contract (`.claude/contracts/test-baseline.md`) and evolve with the project (history: PZ 160 → 221, Carrier 420). `deploy_qa_reviewer` reads the contract value for `SQUASH_SHA`; this document never pins a number.

**What GO looks like — all of:**
- `deploy_lead_coordinator` issues a written **GO** decision naming `SQUASH_SHA`.
- Agents 2–4: diff is `service/app/**`-only (6 files), auth decorators intact, **no** schema/storage writes, **no** forbidden paths.
- Agent 5 (security): no credential/auth/injection finding — **GO**.
- Agent 6 (QA): current approved baseline met, **zero** new regressions.
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
2. **Clean release worktree** (robocopy clean-tree rule — never sync from a dev checkout). `RELEASE_WORKTREE` is detached at `SQUASH_SHA`; verify, do not assume:
   ```
   git worktree add --detach <RELEASE_WORKTREE> <SQUASH_SHA>
   cd <RELEASE_WORKTREE>
   git rev-parse HEAD                # MUST equal SQUASH_SHA
   git status --short                # MUST be empty
   ```
3. **Sync `service/app` → `C:\PZ\app`** (operator):
   ```
   robocopy <RELEASE_WORKTREE>\service\app C:\PZ\app /MIR /XD __pycache__ /XF *.pyc
   ```
   (No engine-root / requirements / schema sync — none in this diff.)
4. **Restart service** (operator):
   ```
   nssm restart PZService
   ```

**Rollback condition (any):** service fails to start, health check fails, or D-1 fails → restore:
```
robocopy C:\PZ-backup-<...> C:\PZ /MIR /XD .git ; nssm restart PZService
```
Then `git revert SQUASH_SHA` (release_manager's exact command) → new PR. Do not advance to Step 4 on a failed deploy or a failed D-1.

---

## DEPLOY CHECKPOINT D-1 — cryptographic hash proof (owner: agent, read-only) — **RULE 1**

**This gate replaces all operator-reported "it's deployed" claims.** Status stays `MERGED, DEPLOY REPORTED` until every row passes, then transitions to `MERGED, DEPLOY VERIFIED, HASH VERIFIED`.

**Authority for the deploy surface is the merged SHA, NOT production history.** Deriving the surface from `PROD_SHA_BEFORE` would assume production faithfully reflects git history — the exact robocopy-drift assumption this checkpoint exists to defeat. Derive from `SQUASH_SHA`:

```
DEPLOY_SURFACE = git show --name-only --pretty="" <SQUASH_SHA> -- service/app/
```

| # | Check | Command / method | PASS criterion |
|---|---|---|---|
| D-1.1 | origin/main at SQUASH_SHA | `cd C:\PZ-verify && git rev-parse origin/main` | == `SQUASH_SHA` |
| D-1.2 | Release worktree at SQUASH_SHA | `cd <RELEASE_WORKTREE> && git rev-parse HEAD` | == `SQUASH_SHA` |
| D-1.3 | **Deploy surface enumerated from the merge** | `git show --name-only --pretty="" <SQUASH_SHA> -- service/app/` | Yields the full merged surface (the 6 files). Surface is **derived**, never hand-transcribed — if a Step-2 remediation changed it, D-1 re-derives. |
| D-1.4 | **LF-normalized SHA256 — every file in DEPLOY_SURFACE** | For **each** file: (1) exists in `C:\PZ\app\…`, (2) exists in `<RELEASE_WORKTREE>\service\app\…`, (3) LF-normalized SHA256 of prod == LF-normalized SHA256 of release worktree | **All** rows pass. Partial-surface match = FAIL. |

> **CRLF note (permanent):** manifest pins are LF; Windows checkout/deploy is CRLF. **LF-normalize before hashing** or D-1.4 false-positives on day one. Record both raw-CRLF (transfer) and LF (authority) hashes.

- **D-1 PASS** → status `MERGED, DEPLOY VERIFIED, HASH VERIFIED`. Only now may Step 4 run.
- **D-1 FAIL** → deploy is NOT live regardless of what the operator reports → roll back (Step 3) → re-deploy. **Rule 2 blocks AWB verification until this passes.**

---

## STEP 4 — Real-shipment verification: AWB 2315714531 (owner: agent, read-only; sign-off: operator) — **RULE 2 gates entry**

Entry precondition: **D-1 PASSED.** The canonical regression fixture. All assertions read-only against the live service.

| # | Assertion | How to confirm | PASS criterion |
|---|---|---|---|
| 4.1 | **Resolved CIF == USD 732** | `get_cif_authority(audit)` / action_diagnostics for the batch | `cif_usd == 732.0`, `cif_source == awb_customs.value_usd`, `cif_state == resolved` |
| 4.2 | **`total_value_usd` ≠ 0.0** | Customs/DSK action surfaces | No surface returns `total_value_usd=0.0`; no "CIF = 0.00" false block |
| 4.3 | **DSK uses resolved authority** | DSK button + `generate_dsk` | Button **enabled**, reason "Ready — CIF value available"; generate succeeds with `value_source=cif_authority:awb_customs.value_usd` |
| 4.4 | **Polish Description uses resolved authority** | `generate_description` | Proceeds (no 422 on resolved); document reflects 732, not 0 |
| 4.5 | **Negative control** | A genuinely unresolved shipment (no invoice total, AWB gap) | Still **blocks** with `422 code=cif_unresolved` + next-action; never silent zero |

**VERIFIED when:** 4.1–4.5 all PASS and operator signs off.
**Rollback condition:** 4.1–4.4 fail (resolved shipment still blocked or shows 0) → the authority model is not live → roll back per Step 3, file a follow-up. A 4.5 failure (unresolved shipment now proceeds) is a **security/compliance** regression → immediate rollback.

---

## STEP 5 — PROJECT_STATE update via flow-context-keeper (owner: agent; RULE 3)

Fire **after** Step 4 sign-off. Carry on a PR branch (direct-to-main `chore(memory)` is denied).

Record into `PROJECT_STATE.md`:
- **FACTS (append):** "#643 squash-merged as `SQUASH_SHA`, deployed to `C:\PZ\app`, D-1 hash verified; AWB 2315714531 verified resolved CIF=732 / `total_value_usd`≠0 / DSK + Polish-desc on resolved authority; negative control blocks `cif_unresolved`." Record `PROD_SHA_BEFORE` → `SQUASH_SHA` transition.
- **OPEN QUESTIONS:** resolve `OQ-PR643-MERGE` (merged + verified); `OQ-PR643-TEST-COVERAGE-REVIEWER` carries forward unchanged.

**VERIFIED when:** `flow-context-keeper` returns, the FACTS block exists on disk (Lesson C), and the cited scorecard path resolves. Step 5 does **not** gate Step 6; Steps 1–4 + D-1 do.

---

## STEP 6 — BLOCKER: no PZ / wFirma until Steps 1–4 + D-1 are VERIFIED — **RULE 3**

**Explicit gate.** No `pz_create`, PZ preview/adopt, wFirma document write, or any customs/PZ posting may run until:

- [ ] Step 1 — #643 MERGED, `SQUASH_SHA` recorded (Rule 5: confirmed #643, not #640)
- [ ] Step 2 — coordinator GO on `SQUASH_SHA`, all 6 sub-agents non-blocking
- [ ] Step 3 — deploy executed, `PZService` healthy
- [ ] **D-1 — LF-normalized hash match PASSED across the full merge surface (Rule 1)**
- [ ] Step 4 — AWB 2315714531: 4.1–4.5 all PASS, operator signed off (Rule 2 cleared)

Until every box is checked, treat PZ/wFirma actions as **hard-blocked**. Rationale: this PR makes the resolved CIF the single customs-value authority; running a PZ/wFirma write before the authority is live-verified risks posting against the exact stale/zero customs value the campaign exists to eliminate.

---

## Stream separation & conflict handling (Rule 5)

- **#643 deploys alone.** If #640 is also ready, it runs a **separate** merge → gate → deploy → D-1 → its own verification. Never the same robocopy, never the same gate run.
- If #640 lands first and creates a merge conflict on #643's branch: rebase #643 on updated main, re-run its full gate against the new `SQUASH_SHA`.
- AWB 2315714531 **accounting recovery** depends on #640's invoice-confirmation workflow; AWB 2315714531 **CIF-authority verification** (Step 4 here) depends only on #643. Do not conflate them.

---

## Ownership & escalation summary

| Concern | Owner |
|---|---|
| Merge decision, all `C:\PZ` writes, restart, sign-off | **Operator** |
| GO/NO-GO synthesis | `deploy_lead_coordinator` |
| Security veto (non-overridable) | `deploy_security_reviewer` |
| Test baseline for `SQUASH_SHA` (per versioned contract) | `deploy_qa_reviewer` |
| Rollback command + robocopy plan | `deploy_release_manager` |
| Release-worktree prep, D-1 hash proof, read-only AWB verification, PROJECT_STATE update | Agent |

**Global rollback anchor:** `PROD_SHA_BEFORE` (Step 0) + `C:\PZ-backup-<...>`. Helper is additive; revert restores prior inline logic with no resolver/routing change — the only consequence is the raw-zero false-block returning for AWB-only-resolved shipments.
