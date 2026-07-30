# PR #958 — Deploy Single-Authority Reconciliation — Campaign Brief

**Repo:** `amitpoland/estrella-dhl-control` · **Branch:** `fix/deploy-single-authority`
**Branch head:** `7846fc46` · **origin/main:** `f12f9c90` · **Merge-base:** `a4da80b2`
**PR #958 state:** OPEN · mergeable=CONFLICTING · mergeStateStatus=DIRTY
**Prepared:** 2026-07-29 · **Verification tree:** `C:\PZ-verify` (on `main`, clean, == origin/main)
**Mode:** inspection + planning only — **no branch edits made, no deploy, no writes to `C:\PZ`.**

---

## 1. Task

Prepare PR #958 for a safe deploy-authority *replacement*: reconcile the branch with current
`origin/main`, dispose of every outstanding review concern with code-backed evidence, and prove
the final design leaves **exactly one** deployment authority (one config, one executor, one
validator, one policy — no per-SHA manifest, closure script, hook, command, agent, or markdown
independently executable as a second deploy path).

This brief is the required Phase-5 deliverable. Per the operator's editing rule, **no branch
mutation happens until this brief + the authority map are accepted.**

## 2. Scope

**In scope (this campaign):** rebase/merge-conflict resolution for PR #958; disposition of all
review comments; the single-authority replacement design; the governance test that makes
re-duplication a failing test; the test plan (syntax, schema, dry-run against a **disposable
non-production** target, rollback simulation, concurrency-lock, forbidden-production-path,
repo-wide zero-live-caller proof, hook block-not-execute proof, root regression gate). May
prepare and, after all gates + operator approval, **merge** #958.

**Out of scope (explicitly deferred):**
- **Production rollout** — separate `/security-review`, operator approval, pinned merge SHA,
  dry-run evidence, rollback rehearsal, and a dedicated deployment campaign. This campaign does
  **not** deploy, does **not** restart `PZService`, does **not** write to `C:\PZ`.
- **The ungoverned `C:\PZ\.env` writers** (`env_config_manager.ps1`, `activate_pz_lifecycle.py`)
  — tracked honestly in `PRODUCTION_WRITER_ALLOWLIST` as a *separate* campaign, not silently
  absorbed here.

## 3. Current State

**One deploy authority already exists on the branch and every competitor is deleted by it.**
Branch-vs-merge-base name-status (deploy-relevant paths only):

- **Added (the single authority):** `.claude/deploy/Deploy-PZ.ps1` (executor+rollback),
  `.claude/deploy/Test-PZDeployClose.ps1` (read-only validator),
  `.claude/deploy/windows_prod_v2.json` is *modified* (sole config),
  `.claude/hooks/deploy_authorization.py` + `.claude/hooks/sign_deploy_authorization.py`
  (HMAC authorization), `service/tests/test_deploy_authority.py` (the Replacement Proof).
- **Deleted (the second/Nth authorities):** `.claude/manifests/verify_deploy_close.ps1` (a full
  280-line second deployer), **~28** `windows_deploy_*.ps1` per-SHA manifests,
  `windows_hygiene_cleanup_phase10.ps1`, 4 × `deploy_delta_pr*.md`, `reports/deploy/verify_sync.py`.
- **Modified (kept, brought into line):** `.claude/commands/deploy.md` (→ governance-only),
  `service/docs/production_deployment_rule.md`, `.claude/agents/deploy_release_manager.md`,
  `service/docs/windows-deploy-runbook-template.md`, `.claude/hooks/pz-deploy-guard.py` (+deny
  rules), `service/app/tools/verify_runtime_sync.py` (**now refuses production destinations**),
  `service/app/api/routes_webhooks_wfirma_status.py` (stale `verify_deploy_close.ps1` comment
  → `Deploy-PZ.ps1`).

**Two merge conflicts** vs current `origin/main`, both resolving cleanly toward the branch
(details §7). PR is DIRTY only because of these two.

**PR #1030 (the prior GATE-2 impl PR) is MERGED & CLOSED** (squash `f12f9c90`, test-only, no
deploy owed) — #958 is the sole remaining implementation PR (GATE-2 = 1/3, compliant).

**Lineage (why #958 is the consolidation heir).** #958 absorbed two now-closed siblings via
archive tags: **#955** (`fix/deploy-source-authority`, tag `archive/pr955-…-2026-07-19`) donated
the preflight/ancestor/gate-then-ff sequencing; **#956** (`fix/deterministic-artifact-deploy`,
tag `archive/pr956-…`) donated the immutable-artifact + gated-`/MIR` + `/XO`-forbidden model.
Since the 07-19 fork, the **only** deploy-machinery commits to land on main are **#969**
(BOM-free `version.txt` write + BOM-tolerant read + 604 floor + wrong-SHA fast-fail, all inside
the *legacy* `verify_deploy_close.ps1`) and **#970** (runnable, DHL-safe Step 7 probes in
`deploy.md`). Both patch the legacy path #958 removes; the merge subsumes them (§7).

**Sibling still open — `fix/deploy-xo-flag-consistency` (likely PR #961, unmerged).** It patches
the *same* legacy `verify_deploy_close.ps1` that #958 deletes → scope-overlap. **GATE-3
disposition:** if #958 merges, #961 is fully subsumed and must be **closed + archive-tagged**
(`archive/pr961-xo-flag-consistency-<date>`); if #958 closes, #961 becomes the fallback. This is
an **operator decision** carried in Review Disposition R9.

## 4. Root Cause

The repository accumulated **~29 independently-executable production writers**: a family of
per-SHA `windows_deploy_<sha>.ps1` manifests **plus** `verify_deploy_close.ps1`, which had
silently grown from a validator into a *second full deployer* (its own robocopy L165-167, its
own `version.txt` writer L186-187, its own `sc.exe` service restart L191-196). "Prose-as-script"
runbooks (`deploy.md` Step 5/6/8 on main) were a **third** executable path. Any of the three
could converge production independently, with divergent guards (e.g. `verify_deploy_close.ps1`
raised its own `MinCarrierTests` default 469→604 out of band). Multiple authorities = no single
place where a safety control is guaranteed to run.

## 5. Architectural Goal

Exactly one authority per deploy responsibility, everything else data or documentation:

| Responsibility | Sole owner |
|---|---|
| Configuration (every path, engine filename, robocopy flag) | `.claude/deploy/windows_prod_v2.json` |
| Execution + rollback | `.claude/deploy/Deploy-PZ.ps1` |
| Validation (read-only) | `.claude/deploy/Test-PZDeployClose.ps1` |
| Policy / governance (prose only) | `service/docs/production_deployment_rule.md` |
| Required test counts | `.claude/contracts/test-baseline.md` |
| Pre-deploy review | the 7 `.claude/agents/deploy_*.md` agents |
| Authorization (mint) / block (agent) | `sign_deploy_authorization.py` / `pz-deploy-guard.py` |

No hardcoded production path, engine filename, or test count lives anywhere but the config /
baseline contract. No markdown contains a runnable deploy command. No per-SHA manifest exists.

### 5a. Deployment Authority Map (Phase 2 — component ledger)

Every component that can converge/verify/authorize a production deploy. "Dup?" = is it a second
authority for a responsibility another component already owns.

| Component | Current main authority | #958 proposed | Dup? | Disposition | Reason | Rollback consequence if removed |
|---|---|---|---|---|---|---|
| `windows_deploy_<sha>.ps1` ×~28 | each = a full per-SHA executor (robocopy+version+restart) | — | **YES** (N executors) | **DELETE** | Per-SHA copies of the one deploy path; drift risk (divergent guards) | None — pre-removal state frozen in tag `archive/deploy-manifests-2026-07-19`; 0 live callers |
| `.claude/manifests/verify_deploy_close.ps1` | 2nd full deployer (own robocopy L165, version writer L186, `sc.exe` restart L191) **and** validator | — | **YES** (exec+valid) | **DELETE** (`git rm`) | The core duplication; grew validator→deployer | None — execution→`Deploy-PZ.ps1`, validation→`Test-PZDeployClose.ps1`; #969 patches preserved (R10) |
| `.claude/manifests/deploy_delta_pr*.md` ×4 | per-PR deploy delta notes | — | YES (scope authority) | **DELETE** | Per-PR scope now derived from artifact manifest | None — 0 live callers; historical only |
| `windows_hygiene_cleanup_phase10.ps1` | ad-hoc prod mutator | — | YES | **DELETE** | One-off prod writer outside any authority | None — 0 references repo-wide |
| `reports/deploy/verify_sync.py` | wave-12 sync verifier (hardcoded `C:\PZ-deploy-w12` src) | — | YES (validation) | **DELETE** | Wave-12 complete; unreusable path literal | None — replaced by `verify_runtime_sync.py`; caller is a closed runbook |
| `.claude/commands/deploy.md` | **prose-as-script** (runnable robocopy/sc.exe/py, Step 8 calls retired script) | governance-only table | **YES** (3rd exec path) | **REPLACE** (take branch) | Runnable markdown = executable 2nd/3rd path | N/A — governance doc; execution moves to `Deploy-PZ.ps1` |
| Configuration | split across `deploy.md` + manifests + `windows_prod_v2.json` | `windows_prod_v2.json` (only) | was YES | **CONSOLIDATE** | One config for every path/flag/engine file | Restore config from git; artifacts self-describe via manifest |
| Execution + rollback | manifests + `verify_deploy_close.ps1` + prose | `Deploy-PZ.ps1` (only) | was YES | **CREATE (sole)** | ReviewedSHA pin, artifact converge, lock, backup unit | Backup units carry `*.manifest.csv`; manual restore documented (deploy.md §DR) |
| Validation (read-only) | `verify_deploy_close.ps1` + `verify_sync.py` + deploy.md Step 7/8 | `Test-PZDeployClose.ps1` (only) | was YES | **CREATE (sole)** | 8 read-only checks; no copy/restart/POST | N/A — validation never mutates |
| Policy / governance | `production_deployment_rule.md` (+ prose in deploy.md) | `production_deployment_rule.md` (only) | partial | **KEEP (prose-only)** | Single narrative authority; no commands | N/A |
| Authorization (mint) | none (presence-only env gate) | `sign_deploy_authorization.py` + `deploy_authorization.py` | — | **CREATE** | HMAC-SHA256, SHA-bound, single-use, key off-repo; fail-closed | No signer today ⇒ every deploy DENY (intended default) |
| Agent block | `pz-deploy-guard.py` (path-based) | `pz-deploy-guard.py` (+deny deploy-script-by-name, `gh pr merge`, `git push main`, runtime-config writers) | — | **STRENGTHEN** | Config-driven script carries no path token → name-match needed | Removing weakens agent containment; keep |
| Runtime tool `verify_runtime_sync.py` | live sync tool (could target prod) | + `_is_production` refusal | — | **KEEP + NEUTER** | Kept for its real use; refuses prod destinations | Still usable for non-prod; prod path blocked |
| `routes_webhooks_wfirma_status.py` reader | comment names `verify_deploy_close.ps1`; #969 `utf-8-sig` reader | comment→`Deploy-PZ.ps1`; reader unchanged | no | **MERGE (auto)** | 3-way keeps #969 reader + branch comment | N/A — read path only |
| **Surviving invocations audit** | `deploy.md:178` was the *only* live caller of `verify_deploy_close.ps1` | replaced by branch deploy.md | — | resolved | census: `windows_deploy_*`/`deploy_delta_*`/`verify_sync.py` = 0 live callers | — |
| `test_wfirma_status.py` BOM test | reads `verify_deploy_close.ps1` from disk | untouched (has `pytest.skip` guard) | no | **NON-BLOCKING (SCHEDULED cleanup)** | Degrades to skip; BOM coverage moved to `test_deploy_authority.py` | N/A — test-only |

## 6. Governance Rules (binding on this campaign)

- **CLAUDE.md GATES 1-6**; **7-agent deploy gate** specialises GATE 1 for the eventual sync (not
  this campaign — we do not deploy).
- **Lesson J** — root engine files (`pz_import_processor.py`, `polish_description_generator.py`)
  deploy separately to `C:\PZ\engine\`; encoded in config `engine_files` + `Invoke-EngineSync`.
- **Lesson P** — robocopy `/XO` copies by mtime not content; `/XO` is in `forbidden_flags`, and
  the executor converges from an immutable hash-manifested artifact + verifies content.
- **Lesson D** — no local-only commits before deploy; preflight enforces it.
- **Lesson N / N(authority)** — advisory signals never block; not touched here (no readiness change).
- **Path guard** — all reads/git ops target `C:\PZ-verify`. **One-session rule** honored.
- **Editing rule** — reuse the existing PR branch; no competing replacement PR; no branch edits
  until this brief is accepted; if conflict resolution becomes ambiguous around production safety,
  **stop and ask** (it did not — §7).

## 7. Implementation Plan (rebase / conflict resolution — proposed, not yet executed)

Reconcile via **merge of `origin/main` into the branch** (preserves the branch's deletions as
deletions; avoids a blind rebase replaying 3 commits over a moved main). Two conflicts:

**CONFLICT 1 — `.claude/commands/deploy.md` (modify/modify).**
- *main (210L):* prose-as-script — runnable `robocopy … /E /XO` (Step 5), `sc.exe stop/start`
  (Step 6), inline `version.txt` python, Step 8 invokes the retired
  `.claude\manifests\verify_deploy_close.ps1`.
- *branch (110L):* governance-only authority-model table + "what the operator runs" (Deploy-PZ.ps1
  `-WhatIf`/`-ReviewedSHA`, `sign_deploy_authorization.py`, `Test-PZDeployClose.ps1`); zero
  runnable robocopy/sc.exe.
- **Resolution: take the BRANCH wholesale.** main's version would *fail*
  `test_no_executable_deploy_logic_in_prescriptive_markdown`. main's only substantive recent
  addition — the 7c carrier-live-POST safety warning — is **moot** under the branch model
  (Test-PZDeployClose.ps1 performs **no** carrier POST at all; the hazard it warns about cannot occur).

**CONFLICT 2 — `.claude/manifests/verify_deploy_close.ps1` (modify/delete).**
- *main:* still present, still a second deployer; main's recent edits raised `MinCarrierTests`
  469→604 and added a wrong-SHA abort — real improvements, but to a file that must not exist.
- *branch:* **deletes** it (execution → Deploy-PZ.ps1, validation → Test-PZDeployClose.ps1).
- **Resolution: take the DELETE (`git rm`).** This file *is* the second authority. Its main-side
  improvements are **preserved or strengthened** in the survivors: the 604 carrier floor lives in
  `.claude/contracts/test-baseline.md` (single source of truth, referenced by the branch); the
  wrong-SHA abort is *strengthened* into `Assert-ReviewedTarget` + `-ReviewedSHA` pinning that
  refuses any SHA the gate did not review (not merely a post-hoc check).

**No third conflict — and one clean merge worth naming.** `routes_webhooks_wfirma_status.py` was
touched by both main (#969) and the branch, but **merge-tree reports no conflict** and the actual
merged tree (`2734de9f`) is the *strongest* combination, verified by three-way inspection:
- merge-base reader = `utf-8`; **branch left the read line untouched** (only fixed the header
  comment → `Deploy-PZ.ps1`); main #969 changed the reader to `utf-8-sig` + BOM-tolerance block.
- three-way merge therefore **keeps #969's `utf-8-sig` BOM-tolerant reader** *and* the branch's
  corrected comment — layered on top of the branch's BOM-free, byte-validated **writer**.
- Result: belt-and-suspenders BOM defense (safe writer **and** tolerant reader), **zero manual
  reconciliation** for this file. This directly satisfies "preserve/strengthen all safety controls."

`production_deployment_rule.md`'s surviving `C:\PZ-verify` reference is **correct** — it labels the
"Git repo (verify)" role, not a deploy source (the 07-19 inspection's stale-source concern is
resolved on the branch; source_root is `C:\PZ-main`).

Neither conflict is ambiguous around production safety → no operator stop required for resolution.
After resolution: run the test plan (§8), then GATE-1 checklist, then request operator merge approval.

## 8. Safety Gates (test plan — to run after conflict resolution, before PR-ready)

Validate the **commit**, not a dirty tree (`git archive`/checkout of the merged head into a temp
dir; explicit paths). None of these touch `C:\PZ`.

1. **PowerShell syntax** — parse `Deploy-PZ.ps1`, `Test-PZDeployClose.ps1` via
   `[ScriptBlock]::Create`/AST — zero parse errors.
2. **Config schema** — `windows_prod_v2.json` loads; all required keys present; `forbidden_flags`
   contains `/XO`; `engine_files` == the two Lesson-J files.
3. **`test_deploy_authority.py`** — the full Replacement Proof suite green (§9).
4. **Dry-run** — `Deploy-PZ.ps1 -WhatIf -ReviewedSHA <head>` against a **disposable non-prod
   target** (temp dir as `runtime_app`); writes nothing; emits a plan.
5. **Rollback-path simulation** — build a fake backup unit + manifest in temp; `-Rollback -Unit`
   restores and validates against `app.manifest.csv`/`engine.manifest.csv`.
6. **Concurrency lock** — second `Enter-DeployLock` while a live PID holds it → refuse;
   `-ForceUnlock` only clears a provably-dead PID.
7. **Forbidden-production-path** — assert the executor refuses if `runtime_app` resolves under a
   production literal without authorization; `verify_runtime_sync.py` `_is_production` refuses.
8. **Authorization fail-closed** — with no signing key: every `deploy`/`rollback` DENY.
9. **Guard block-not-execute** — `pz-deploy-guard.py` denies Deploy-PZ.ps1 invocation by name,
   copy-into-`C:\PZ`, `gh pr merge`, `git push main`, runtime-config writers; hooks **validate/
   block**, never deploy.
10. **Root regression** — `python test_pz_regression.py` (root) green; targeted
    `test_wfirma_status.py` (expect the BOM test to **skip** gracefully — §9 disposition).

**Not run:** any production deploy against `C:\PZ`; any `PZService` restart; any carrier POST.

## 9. Review Disposition

| # | Review concern | Disposition | Code-backed evidence |
|---|---|---|---|
| R1 | `version.txt` BOM (op's #1 concern; "line 359 `Out-File -Encoding utf8`") | **ALREADY RESOLVED + double-tested; merge makes it belt-and-suspenders** | The op saw commit 1/3 (`aa29af7d`) mid-rebase. Branch tip `7846fc46`: `Write-VersionFile` uses `[System.IO.File]::WriteAllText(..., ASCIIEncoding)` then re-reads raw bytes and throws on `EF BB BF`. Pinned by `test_version_file_written_bom_free_and_validated_by_bytes` **and** `test_version_file_has_exactly_one_writer`. **Verified:** the 3-way merge also retains #969's `utf-8-sig` BOM-tolerant *reader* (merged tree `2734de9f`) → safe writer **and** tolerant reader after merge. |
| R2 | `deploy.md` still contains runnable robocopy/sc.exe (prose-as-script) | **MUST FIX — fixed by taking branch deploy.md** | Conflict 1 resolution; enforced by `test_no_executable_deploy_logic_in_prescriptive_markdown`. |
| R3 | `verify_deploy_close.ps1` is a second deployer | **MUST FIX — fixed by delete** | Conflict 2 resolution; enforced by `test_exactly_one_execution_authority` + `test_retired_deployment_scripts_are_gone`. |
| R4 | main's 604 carrier floor / wrong-SHA abort would be lost on delete | **OBSOLETE (preserved elsewhere)** | 604 → `.claude/contracts/test-baseline.md`; wrong-SHA → `Assert-ReviewedTarget` + `-ReviewedSHA` pin (stronger). |
| R5 | main's 7c carrier-live-POST warning dropped | **OBSOLETE (hazard cannot occur)** | `Test-PZDeployClose.ps1` performs no carrier POST; nothing to warn about. |
| R6 | `test_wfirma_status.py` BOM test references the deleted script | **OBSOLETE — non-blocking; SCHEDULED follow-up** | Test has `pytest.skip("… not present …")` guard → degrades to skip, not fail. BOM coverage superseded by `test_deploy_authority.py`. GATE-4 disposition: **SCHEDULED** doc/test-cleanup to delete the dead skip. |
| R7 | Ungoverned `C:\PZ\.env` writers still exist | **OPERATOR DECISION — out of scope (honestly tracked)** | `PRODUCTION_WRITER_ALLOWLIST` flags `env_config_manager.ps1` + `activate_pz_lifecycle.py` as a separate campaign; not silently absorbed. |
| R8 | Stale prose refs to deleted scripts survive (campaign/scorecard md, PROJECT_STATE) | **OBSOLETE — non-blocking; append-only history** | Refs live in `.claude/campaigns/*` + `.claude/memory/scorecards/*` + `PROJECT_STATE.md` — **not** in any prescriptive-scanned dir (`commands|agents|contracts|runbooks|deploy`), so no test fails. Historical records are append-only. Optional doc-cleanup = SCHEDULED. |
| R9 | Sibling `fix/deploy-xo-flag-consistency` (PR #961) patches the legacy file #958 deletes | **OPERATOR DECISION (GATE-3)** | Scope fully overlaps #958 and targets the legacy `verify_deploy_close.ps1`. If #958 merges → close #961 + `archive/pr961-xo-flag-consistency-<date>`. Not merged today; carried as an explicit operator disposition, not silently ignored. |
| R10 | #969/#970 improvements to legacy deploy path | **SUBSUMED (verified preserved)** | #969's 604 floor → `test-baseline.md`; #969's BOM-tolerant reader → kept by the merge (R1); #969's wrong-SHA fast-fail → `Assert-ReviewedTarget`; #970's DHL-safe post-deploy probe → structurally satisfied (`Test-PZDeployClose.ps1` performs no carrier POST). No safety control lost. |

## 10. Replacement Proof (why re-duplication cannot silently return)

`service/tests/test_deploy_authority.py` makes single-authority a **failing test** on regression:

- `test_exactly_one_execution_authority` — no `windows_deploy_*.ps1`, no manifests deployer, no
  `verify_deploy_close.ps1`.
- `test_exactly_one_validation_authority` / `test_exactly_one_configuration_authority`.
- `test_no_executable_deploy_logic_in_prescriptive_markdown` — scans fenced blocks in
  `.claude/{commands,agents,contracts,runbooks,deploy}` + POLICY for `robocopy`/`sc.exe`/`nssm`.
- `test_no_deployment_path_literals_outside_config` / `test_engine_filenames_only_in_config` /
  `test_test_counts_only_in_baseline_contract` (bans 412/469/584/604 in deploy surfaces).
- `test_version_file_has_exactly_one_writer` + `test_version_file_written_bom_free_and_validated_by_bytes`.
- `test_reviewed_sha_is_explicit_and_never_recomputed` (bans `Get-IncomingRange`).
- `test_guard_denies_deploy_script_invocation`; lock/backup/rollback ordering tests.
- `test_no_undeclared_production_writers` — **whole-repo** `PROD_PATH_RX ∧ WRITE_RX` scan against
  `PRODUCTION_WRITER_ALLOWLIST`; any new undeclared production writer fails immediately.

**Caller census (repo-wide, origin/main) confirms zero live callers survive the merge:** the only
live caller of `verify_deploy_close.ps1` was `deploy.md:178` — the very file the branch replaces.
`windows_deploy_*`, `deploy_delta_*`, `verify_sync.py`, `windows_hygiene_cleanup_phase10.ps1` →
0 live callers (all doc/historical/self-referential). `verify_runtime_sync.py` kept + neutered.

## 11. Next Exact Step

**Await operator acceptance of this brief + authority map.** On acceptance, execute the Phase-7
conflict resolution (§7) on branch `fix/deploy-single-authority` in `C:\PZ-verify`
(merge `origin/main`; take branch `deploy.md`; `git rm` `verify_deploy_close.ps1`), then run the
§8 test plan against the merged **commit**. Do **not** deploy, restart `PZService`, or write to
`C:\PZ`. Production rollout remains a separate operator-gated campaign (`/security-review` +
pinned SHA + dry-run + rollback rehearsal + 7-agent gate).
