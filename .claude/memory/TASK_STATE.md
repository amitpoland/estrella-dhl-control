# TASK_STATE.md

In-flight **single-task** tracker. Records the current task's goal,
completion criteria, status, and HOLD reason (if stopped). Ephemeral —
rewrite the `## Current task` block when a new task begins.

Rules and boundary vs PROJECT_STATE.md:
`docs/governance/anti-hold-and-completion.md` §5.

- **Do not** start a second task while the current one is in any active lifecycle
  state (`DISCOVERY`, `PLANNING`, `IMPLEMENTING`, `VALIDATING`, `EXECUTION_BLOCKED`,
  `READY_FOR_PR`, `UNDER_REVIEW`) — unless the operator explicitly redirects.
- **Do** record a one-line HOLD reason (one of the four valid conditions)
  whenever you stop, so the next session resumes without re-derivation.
- Lifecycle state (canonical axis — `.claude/TASK_EXECUTION_PROTOCOL.md`):
  `NOT_STARTED` · `DISCOVERY` · `PLANNING` · `IMPLEMENTING` · `VALIDATING` ·
  `EXECUTION_BLOCKED` · `READY_FOR_PR` · `UNDER_REVIEW` · `COMPLETE`.
  `EXECUTION_BLOCKED` is the resumable refinement of the former `BLOCKED-HOLD`; it
  requires one of the four §2 HOLD conditions AND a recorded checkpoint block
  (template below). Resume Rule + full semantics:
  `docs/governance/anti-hold-and-completion.md` §7. This is a **separate axis** from
  the `.campaigns/` branch-write registry state — neither derives from the other
  (mapping: `.claude/TASK_EXECUTION_PROTOCOL.md`).
- **Migration:** pre-existing entries below in old spellings (`IN_PROGRESS`,
  `BLOCKED-HOLD`) are **grandfathered** and NOT auto-reclassified; each is migrated
  only when its owner re-touches it (determine `suspended_from` + checkpoint
  completeness first). New task entries use the canonical lifecycle state.

### EXECUTION_BLOCKED checkpoint template (record on entering; no secrets / customer data)

```yaml
state: EXECUTION_BLOCKED
suspended_from: VALIDATING
blocked_reason_class: EXTERNAL_INFRASTRUCTURE
blocked_dependency: <named dependency>
recorded_branch: <branch>
recorded_head: <sha>
preserved_diff_hash: <optional; sha256 over the preserved_files contents, computed by the owner session at checkpoint time>
preserved_files:
  - <path>
authority_owner: <canonical authority>
next_command: <the single recorded resume command>
retry_policy: NO_REPEATED_RETRIES
checkpoint_recorded_at: <ISO-8601 timestamp>
```

---

## Current task

- **Task:** PR #1201 — prevent multi-party intake from seeding batch-level
  `packing_contractor_resolution`; then B-021 read-only historical measurement.
- **Started:** 2026-08-12 · **Status:** `VALIDATING` — rebased on production tip; adding 0b
  fallthrough assertion; seven-agent gate / merge / App-only deploy next; B-021 RO after smoke.
- **Baseline / production:** `0b2020a8a0eb76f437aff90f40e1c7acb081eb7a` (`C:\PZ\version.txt`).
- **Branch:** `fix/intake-multiparty-contractor-seed` rebased onto `0b2020a8` (was based on
  `0dc647af`). Tip includes `_sole_cid()` + multiparty seed tests; main still has first-non-empty
  seed — fix still required (not superseded by B-020).
- **Invariant (permanent):** `{A}`→seed · `{A,A}`→seed · `{A,B}`→**no seed** · `{}`→no seed.
  Per-document contractor is authoritative for multi-party batches; batch-level row is only a
  convenience for genuinely single-party batches. Empty-contractor tolerance stays intentional.
- **B-020:** CLOSED on production (PR #1202 / `document_party_authority`). Do not reopen or
  expand #1201 into consumer customs/carrier paths.
- **B-021:** after #1201 deploy — **read-only only**. No DELETE/UPDATE/backfill of historical
  `packing_contractor_resolution` rows without a separate mutation campaign.
- **Production writes for #1201:** NONE (authority logic only). Rollback = revert merge.
- **Commercial-description WIP:** stashed separately
  (`wip-commercial-description-convergence-20260812`); do not mix into this campaign.

## Prior task — Product-description authority (PR #1178) (COMPLETE; CLOSED)

- **Task:** Repair product-description authority (material-component semantics + `name_pl`
  provenance) — PR #1178 — and converge the affected draft through the normal authority path.
- **Started:** 2026-08-09 · **Closed:** 2026-08-11
- **Status:** `COMPLETE` — merged, deployed, operator-verified. **Campaign CLOSED. Do not
  reopen, do not re-implement, do not re-run the draft convergence.**
- **Merged:** `3710aa12` (PR #1178, branch `claude/product-description-authority-0126d8`).
  Independently gated **7/7 GO** at `1707e630`, whose runtime payload is byte-identical to the
  merge commit.
- **Deployed:** production runtime SHA **`7150996b75eb12174df3ee79f896bd5510d2eec5`**, deployed
  2026-08-11 UTC by the operator from `C:\PZ-main` via `Deploy-PZ.ps1 -Release -Scope Both`
  (elevated Admin shell). Pre-deploy marker in `C:\PZ\version.txt` was `d32efd3a`.
- **Ride-along disclosed, not hidden:** `-Release` self-resolves `origin/main`, so the
  deployable unit was the **tip**, not our merge. Composite payload `d32efd3a..7150996b` =
  **9 files** — 4 from #1178 (`description_grammar.py`, `pz_import_processor.py`,
  `customs_description_engine.py`, `service/app/services/proforma_invoice_link_db.py`) + 5 from
  PR #1180 (DHL notify audit). Measured **file-disjoint** (`comm -12` empty); #1180's files are
  blob-identical to its own gated head `43488f29`, whose parent IS `d32efd3a`. **Lesson J
  applies** — three of #1178's four files are governed `engine_files`; `-Scope Both` covered the
  separate engine sync.
- **Gate evidence:** `latest.json` names `target_sha=7150996b…`, 7/7 `GO`, empty blockers;
  `python .claude/hooks/gate_evidence.py <file> 7150996b…` → `VALID seven-agent GO`, EXIT=0.
  **Authored by a concurrent session, not by this campaign session** — recorded per Lesson Q
  rule 1 (attribute; never present another session's round as your own).
- **Metered floors at the tip** (`.claude/contracts/test-baseline.md`): PZ `283 passed`
  (floor 260) · Carrier `646 passed, 4 failed` (floor 604). The 4
  `test_carrier_config_defaults.py` failures are the registered ENVIRONMENTAL class (real DHL
  credentials present in the host env), not regressions.
- **What was fixed** — two defects in one authority layer: (a) lossy single-metal normalization
  dropped a real material from combination rows and invented a `925` purity on bare `SILVER`;
  (b) `_birth_resolve_name_pl()` stamped `name_pl_source='operator'` on machine-born names,
  which then made the row permanently uncorrectable by enrichment. Shape: **ONE** shared
  multi-metal tokenizer `parse_material_components()` in `description_grammar.py` (stdlib-only
  leaf) with both engines as consumers — no third generator; `check_material_completeness()` on
  both paths; `NAME_PL_SOURCE_MACHINE_BIRTH = "machine_birth"` with precedence
  `operator > product_descriptions > machine_birth > missing_pd/blank`; `update_draft_line`
  remains the SOLE minter of `operator`; `classify_legacy_name_pl_verdict()` is **fail-closed**
  — `unknown` ALWAYS preserves `operator`.
- **Governing invariant (permanent):** *normalization may improve language; it may never remove
  a material component present in the source.* ≥2 metals with no combination marker ⇒
  `description_review_required`, never a confident guess.
- **Operator-verified convergence (2026-08-11), normal authority path only** — no direct SQL, no
  draft-ID-specific rule: all 4 #1178 + all 5 #1180 runtime files hash-match `C:\PZ-main`
  (Lesson P content parity, never a robocopy count); promotion dry-run `conflicts=0,
  skipped_protected=0`; real promotion wrote **29 rows**; `reset-from-sales-packing` run
  **twice** with identical results (idempotency proven); the two combination lines carry
  corrected multi-material descriptions with **no invented `925`**; the two single-metal lines
  unchanged; **draft totals unchanged (4 lines)**; no Post, no Convert, no wFirma mutation.
- **Layer note (not a discrepancy):** the brief's 29-line / net / gross / duty figures are
  **source-batch / invoice-level** (matching the 29 promoted rows); the 4-line draft total is
  **draft-level**. Different layers of the same flow.
- **Deliberately NOT touched:** the four wFirma goods created 2026-08-07 still carry the OLD
  wrong names. They are live external **PRODUCT-authority** records; correcting them is a
  separate, explicit operator action via the gated
  `POST /api/v1/wfirma/goods/{product_code}/update-and-adopt` (`WFIRMA_EDIT_PRODUCT_ALLOWED`),
  outside this closed campaign.
- **Nothing owed.** No deploy, no follow-up PR, no re-verification.

## Prior task — Deploy PR #1043 tracking `last_event` hotfix (COMPLETE; SUPERSEDED)

> **SUPERSEDED 2026-08-11 — retained for audit, not for reliance (Lesson Q rule 5: correct by
> marking, never by deleting).** The `1ce0e76d` / `423fa3cb` HYBRID production state described
> below was reconciled by the operator's `-Reconcile -FromSha 423fa3cb -ToSha f43796bc` run on
> 2026-08-07, and production has since advanced twice more; it is now `7150996b` (see the
> current task above). **Every production-SHA claim in this block is historical. Re-measure
> `C:\PZ\version.txt` and `git -C C:\PZ-main rev-parse origin/main` before acting on any of it.**

- **Task:** Deploy PR #1043 (tracking `last_event` React-#31 hotfix) to production.
- **Started:** 2026-07-31
- **Status:** `EXECUTION_BLOCKED` — **agent-side COMPLETE, operator handoff** (merge DONE +
  gate re-confirmed READY-TO-DEPLOY; deploy NOT performed — prod still `1ce0e76d`, no signed
  auth for candidate, no new backup unit). Awaiting operator sign+sync. See the
  "AGENT-SIDE COMPLETE — operator handoff" note under the checkpoint block below.
- **Merged:** squash `a14a9eae741077af42cb2b2d353e19b4af986172` (`e950475a` is NOT an
  ancestor — verify by content). `C:\PZ-main` fast-forwarded, clean.
- **No re-verification owed:** merged tree = `baf7c87acbc9dedfefa3bd607ed532fde04d2eba`,
  byte-identical to the tree the 7-agent gate, the PZ 260 / Carrier 604 floors, the
  160/160 golden run and GATE-6 already passed against. Do NOT re-run them.
- **7-agent gate RE-CONFIRMED 2026-07-31 (this session):** re-ran the full read-only gate
  against the current `origin/main` tip **`423fa3cb0d599b29dc5e7da0efbf1d057e7d7aa0`**
  (advanced past `a14a9eae` only by docs-only PR #1055 — `production_deployment_rule.md`,
  2 lines; `a14a9eae` is a confirmed ancestor of `423fa3cb`, runtime payload identical).
  **Verdict: READY-TO-DEPLOY, risk LOW** — all 6 reviewers CLEAR/GO, deploy-lead-coordinator
  GO. Metered floors re-measured green this run: **PZ 260/260**, **Carrier 646 pass** (4
  env-conditional DHL-cred fails; floor 604 satisfied), **golden 160/160**
  (`PYTHONIOENCODING=utf-8`). The 16 tracking-subset failures were proven **pre-existing
  baseline** by revert-and-compare (reverting the 2 payload files to prod `1ce0e76d` yields
  identical failures) — NOT introduced by #1043. Deploy candidate is the **tip `423fa3cb`**
  (deploy origin/main HEAD, not the older merge commit).
- **Deploy delta vs prod `1ce0e76d`:** 2 files, +42/−3, both under `service/app/`
  (`services/tracking_service.py`, `static/v2/shipment-detail-page.jsx`). Lesson J N/A.
- **Production state — CURRENT-STATE FACT (2026-07-31, disk-measured; supersedes the earlier
  "consistent at 1ce0e76d" reading):** production is a **HYBRID**. Recorded provenance and
  filesystem content disagree. Detail in [[project-prod-outofband-copy-1043-anomaly]]. Four
  facts, observed state kept separate from required remediation:

  1. **Canonical deployment has NOT occurred.** No signed deploy authorization was consumed,
     no `app-423fa3cb` release artifact exists in `C:\PZ-releases`, no deployment backup unit
     was created after the 00:34 rollback, and `C:\PZ\version.txt` still records `1ce0e76d`.
     By every canonical-provenance signal, prod is still `1ce0e76d`.
  2. **Observed filesystem state — CORRECTED 2026-08-01 (operator ruling).** The two #1043
     application files (`app/services/tracking_service.py`,
     `app/static/v2/shipment-detail-page.jsx`) are byte-identical (sha256) to the reviewed
     `423fa3cb` content and carry mtime `2026-07-31 02:00:01`. Their presence is the result of
     an **out-of-band manual copy** (operator-console `robocopy … /MIR`, forensics resolved —
     NOT a canonical deploy, NOT the agent). **The earlier "`1ce0e76d` tree + 2 files at
     `423fa3cb`" / "non-commit mosaic" reading is WITHDRAWN.** The operator confirmed
     2026-08-01 that `C:\PZ\app` matches the `service/app` subtree of `423fa3cb` across **all
     529 files**; **only `version.txt` is false**. The hybrid is therefore a **deployment-
     provenance defect** (marker disagrees with bytes), not an unexplained runtime overlay.
  3. **Operational consequence.** Hash parity alone is **no longer sufficient evidence** that
     a canonical deployment occurred — the fixed bytes are already on disk without any
     canonical provenance behind them. Canonical-deployment evidence must now come from the
     deployment **artifact**, **updated provenance** (`version.txt`), **backup creation**
     (a new backup unit with a coherent `restored_sha`), and **version stamping** — not from
     a file-content match.
  4. **Required reconciliation (governance-level, NOT a prescribed sequence).** The hybrid
     state must be **reconciled through the approved signed deployment process before
     subsequent releases**, so that deployment provenance is once again consistent with
     filesystem content. This is deliberately stated at the governance level: no specific
     recovery sequence (e.g. "re-converge to `1ce0e76d` first") is encoded here as a rule —
     any such sequence is a proposal only until it is formally approved and encoded in the
     deployment governance. `PZService` is Running; nothing is lost (pre-fix `1ce0e76d`
     content still exists in git and in backup unit `1ce0e76d…-003346`).

```yaml
state: EXECUTION_BLOCKED
suspended_from: VALIDATING
blocked_reason_class: OPERATOR_ONLY_ACTION
blocked_dependency: signed deploy authorization for 423fa3cb (sign_deploy_authorization.py — operator shell only; agent is denied by pz-deploy-guard)
recorded_branch: main
recorded_head: 423fa3cb0d599b29dc5e7da0efbf1d057e7d7aa0
merge_provenance: a14a9eae741077af42cb2b2d353e19b4af986172 (PR #1043 squash; ancestor of tip 423fa3cb — later commits docs-only)
preserved_files: []
authority_owner: production deploy (7-agent gate re-confirmed 2026-07-31, verdict READY-TO-DEPLOY, risk LOW)
next_command: OPERATOR HANDOFF — no valid single agent command; task is agent-side COMPLETE. Operator-first chain: (1) provision signing key C:\PZ-secrets\deploy-auth.key (not on box); (2) reconcile the HYBRID prod tree via the approved signed deployment process — the old straight `sign_deploy_authorization.py 423fa3cb … →then→ Deploy-PZ.ps1 -ReviewedSHA 423fa3cb` is INVALID as-recorded (snapshots the hybrid into the pre-deploy backup → #1039 backup-provenance stop fires; see Hybrid resume caution below); (3) THEN agent runs post-deploy verification (see "Post-deploy (owed)"). Do NOT run the old command without operator reconciliation of the hybrid first.
next_command_superseded: python .claude/hooks/sign_deploy_authorization.py 423fa3cb0d599b29dc5e7da0efbf1d057e7d7aa0 deploy Both --ttl 60   →then→   .claude\deploy\Deploy-PZ.ps1 -ReviewedSHA 423fa3cb0d599b29dc5e7da0efbf1d057e7d7aa0   # SUPERSEDED — retained for provenance only, DO NOT RUN. Invalid for TWO independent reasons: (1) against the HYBRID prod tree it snapshots the hybrid into the pre-deploy backup; (2) since PR #1094 the mint itself exits 2 — --gate-evidence is mandatory for deploy and reconcile. Reason (2) applies even once the hybrid is reconciled, so resolving the hybrid caveat does NOT make this line runnable.
retry_policy: NO_REPEATED_RETRIES
checkpoint_recorded_at: 2026-07-31T02:20:00+02:00
gate_reconfirmed_at: 2026-07-31T (this session; READY-TO-DEPLOY, LOW)
```

- **AGENT-SIDE COMPLETE — operator handoff (recorded 2026-07-31, this session):** every
  action that belongs to an agent session on this task is finished. Done and verified:
  (1) merge landed (`a14a9eae`, ancestor of tip `423fa3cb`); (2) 7-agent gate RE-CONFIRMED
  against `423fa3cb` → READY-TO-DEPLOY, risk LOW, all 6 reviewers CLEAR/GO + coordinator GO;
  (3) metered floors green this run — PZ 260/260, Carrier 646 pass (floor 604), golden 160/160;
  (4) the 16 tracking-subset failures proven pre-existing baseline (revert-and-compare);
  (5) both state files (this file + PROJECT_STATE.md) reconciled to the tip SHA with
  `a14a9eae` preserved as merge_provenance. **The task is NOT `COMPLETE`** — disk measured
  this session shows production still at `1ce0e76d` (`C:\PZ\version.txt`), NO signed
  authorization for `423fa3cb`/`a14a9eae` in `C:\PZ-secrets\deploy-auth`, and no new backup
  unit for the candidate. It stays `EXECUTION_BLOCKED` on the operator-only sign+sync (HOLD
  #2). **Nothing further for an agent to do until the operator acts;** the only remaining
  work is (a) provisioning the signing key + running the signed reconciliation of the hybrid
  (operator shell), then (b) the agent post-deploy verification listed under "Post-deploy
  (owed)" below. Do NOT record this task as done until prod `version.txt` reads the deployed
  SHA and the post-deploy checks pass.
- **HOLD reason:** condition #2 (missing access) — minting the deploy authorization and
  running `Deploy-PZ.ps1` are operator-only; the signing key is never readable by an
  agent session and `gh pr merge` / the deploy script are denied by `pz-deploy-guard`.
  Note: on this box the signing key (`C:\PZ-secrets\deploy-auth.key`) is **not provisioned**,
  which is why the canonical signed deploy of #1043 kept failing (blocked 02:01:27 / 02:03:29)
  and the operator fell back to the out-of-band manual copy. Provisioning the key is a
  prerequisite for any signed reconciliation.
- **⚠ Hybrid resume caution (added 2026-07-31; REWRITTEN 2026-08-01 after the operator
  correction — the prior version's mechanism was wrong in the operator's favour):** the
  recorded `next_command` (straight signed `Deploy-PZ.ps1 -ReviewedSHA 423fa3cb`) was written
  **before** the provenance defect was understood, and is still **not valid as-recorded** — but
  for a different and more dangerous reason than first written.
  - **WITHDRAWN claim.** The earlier text said running it would make "the post-#1039
    content-derived `restored_sha` resolve to no single clean SHA → the backup-provenance stop
    condition fires by design." **Both halves are wrong.** `restored_sha` is **marker-derived,
    not content-derived**: `New-BackupUnit` sets it from `Read-VersionMarker -Path
    $Cfg.version_file`. And under the corrected facts the marker is perfectly readable and
    well-formed (`1ce0e76d…`), so nothing resolves to "no single clean SHA" and **no stop
    condition fires**.
  - **What would actually happen.** A straight signed deploy against the current runtime mints
    a backup unit labelled `restored_sha = 1ce0e76d…` whose bytes are `423fa3cb…` — an
    **untruthfully-labelled unit, minted silently**. `Resolve-RestoredSha` refuses only on
    (a) `unit.json` vs `version.pre.txt` disagreement or (b) both absent; neither applies here,
    so the defect does not surface at deploy time at all. It surfaces later, as a rollback that
    restores `423fa3cb` bytes and then stamps production `1ce0e76d`. **Do not rely on the
    tooling to stop this on current `main`.**
  - **What does catch it.** `Assert-ProductionMatchesRecordedSha` — it runs before the backup,
    compares runtime bytes to the marker by git object id, and fails closed on exactly this
    state. ~~It is in **PR #1062, still OPEN and NOT on `main`**. Until #1062 merges, the
    protection described here does not exist in the deploy authority.~~
    **WITHDRAWN 2026-08-05** (corrected by marking, not deleting — Lesson Q rule 5). #1062
    has merged. Measured at `12376dc6`: the function is present at
    `.claude/deploy/Deploy-PZ.ps1:337` and wired into the deploy and reconcile paths, and
    `Deploy-PZ.ps1` is not in PR #1094's diff, so that content is inherited from `main`.
    **The protection exists in the deploy authority today.** The withdrawn claim erred
    pessimistically — it asserted an absent guard where one is present, which costs a
    wasted stop rather than removing one (Lesson Q rule 6, lower-severity direction) — but
    a session reading it would have held a deploy for a reason that no longer applies.
  - **Correct repair, once #1062 is merged and a signer is provisioned:**
    `-Reconcile -FromSha 423fa3cb0d599b29dc5e7da0efbf1d057e7d7aa0 -ToSha
    c3629786e9ccf66cabddd41ccdfa2a5f3b8badb9` — proves runtime == FromSha (twice, the second
    time immediately pre-backup), records `restored_sha = FromSha` from the **proof** rather
    than the false marker, converges only to ToSha, verifies against ToSha, and writes the
    version marker last. `-ToSha` above is the current `origin/main` tip carrying #1043 + #1052;
    confirm it is still the tip before use.
  - Remediation remains **governance-level and operator-authorized**: the above is the shape the
    tooling now supports, not a standing instruction to execute. Do not treat the recorded
    `next_command` as still-valid.
- **⚠ Resume caution:** four operator status reports this session (merge ×2, deploy,
  auth-mint with `jti=3f8a2c1e`) each described state that disk measurement disproved.
  `sign_deploy_authorization.py` writes the JSON artifact **before** printing
  `Authorization written` + `jti`, so a reported jti with no file in
  `C:\PZ-secrets\deploy-auth` is structurally impossible. **Verify auth artifact →
  backup unit → `version.txt` → file hashes against disk before treating any deploy
  step as done.** Env needs no provisioning: `PZ_DEPLOY_AUTH_KEY_FILE` and
  `PZ_DEPLOY_AUTH_DIR` are persisted at User scope and demonstrably work (they minted
  the `1ce0e76d` artifacts); `PZ_DEPLOY_AUTH_KEY` is correctly unset.
- **Post-deploy (owed):** Lesson-P `Get-FileHash` parity on the 2 files vs `C:\PZ-main`
  (content diff must be 0 — robocopy's copied-file count is NOT the blast radius);
  new backup unit must carry `restored_sha` = `1ce0e76d` and an agreeing
  `version.pre.txt`; then a prod smoke-confirm of the "Latest event" render (a fresh
  GATE-6 is NOT required — it is pre-satisfied). Cache constraint still holds: do NOT
  clear or migrate the tracking cache.

---

## Prior task — GATE-4 disposition: chore/lean-execution-workflow (COMPLETE)

- **Status:** COMPLETE — disposition recorded + committed; **PR #1057 SQUASH-MERGED `49fc5ff4`** (2026-07-31; base `main`, docs-only, deploy N/A).
- **Branch:** `claude/clever-dirac-578aee` (commit `5d463c4c`, base `main`; pushed, MERGEABLE, 1 file/+85).
- **What:** GATE-4 salvage disposition of the unmerged branch `chore/lean-execution-workflow`
  (`44813371`, docs-only, 2026-06-14). **REJECTED** as a duplicate-authority / competing
  governance surface (second execution protocol `docs/EXECUTION_PROTOCOL.md` + a second
  repo-root `PROJECT_STATE.md`) violating "one authority per concept" — not superseded-by-content
  by #953, no unique reconcile payload, 5-week-stale state. **GATE 3:** archive tag
  `archive/chore--lean-execution-workflow-2026-07-19` → `44813371` (LOCAL-ONLY, no push);
  branch ARCHIVED. **Docs-only** — zero code/schema/engine; GATE-2 doc allowance (does not
  displace impl queue #1052/#1053).
- **Deliverable:** PII-free committed mirror `docs/governance/gate4-disposition-lean-execution-workflow-2026-07-19.md`
  (85 lines). Operational copy in local-only `.claude/memory/PROJECT_STATE.md` DECISIONS (2026-07-19 block).
- **Recovery note:** an aborted first attempt committed onto a **detached HEAD in `C:\PZ-verify`**
  (`525d4b55`, stray `@`-mangled subject from PowerShell heredoc in the Bash tool); re-committed
  clean as `5d463c4c` (byte-identical blob `17b1d3d6`). Orphan is reflog-pinned (no branch/tag),
  force-prune declined (would expire the concurrent session's reflog); self-cleaning deferred note
  left in PROJECT_STATE keyed on `git cat-file -t 525d4b55` going missing.
- **Completion criteria:** [x] branch inspected vs canonical authorities; [x] exactly one
  disposition (GATE 4 — REJECTED); [x] GATE-3 archive tag before abandon; [x] PII-free committed
  mirror; [x] PROJECT_STATE DECISIONS recorded; [x] PII + scope + linear-base checks; [x] pushed +
  PR opened (#1057). [x] operator merged #1057 → `49fc5ff4` (2026-07-31). PR-template follow-up chip
  `task_2c18eee3` is independently scoped.

## Prior task — PR #1049 proforma stub drift (COMPLETE)

- **Status:** COMPLETE — merged `4f775b37`, PR closed.
- **Branch:** `claude/jolly-chaplygin-5f2c92` (commit `ef03797d`, base `main`; pushed).
- **What:** `_fake_resolve` stub never updated when WF-3 Slice 3A/3B added the
  `client_contractor_id` kwarg to `_resolve_customer` → `TypeError` on every stubbed POST
  test (13 failed / 21 passed at tree tip `f7d27230`); whole posting path unexercised.
  Fixed two test files (`test_proforma_drafts_lifecycle_phase5.py`,
  `test_proforma_draft_customer_surface.py`); added two end-to-end POST tests pinning the
  id-first contract. **Test-only — no production code touched.**
- **Verification:** phase5 36 passed; both files together 42 passed; root PZ 160/160;
  mutation check confirms the new tests fail when production id-first threading is stripped.
- **GATE 4 disposition:** same-class grep-test drift in `test_customer_master_resolver.py`
  (fixed-offset source-grep windows, `+4500` window already overrun by the 4562-char
  function) filed as ISSUE — GitHub #1048. Out of scope for #1049.
- **Completion criteria:** [x] stub signature parity + genuine id-first assertion;
  [x] sibling-module sweep; [x] regression green; [x] GATE 4 disposition filed;
  [x] committed; [x] pushed + PR opened (#1049). Remaining: operator merge (not mine).

## Held task (operator redirect 2026-07-16 — preserved verbatim)

- **Task:** Phase-C Inventory Master Campaign (platform `.claude/campaigns/phase-c-master/`) —
  launched 2026-07-03 per operator FINAL PRE-LAUNCH AMENDMENT (verbatim R4).
- **Started:** 2026-07-03
- **Status:** BLOCKED-HOLD (CP4/CP5 — operator executes the prod deploy runbook)
- **Deploy state:** gate READY-TO-DEPLOY (7/7); Lesson-D ACKNOWLEDGED; candidate
  `84c292de` in C:\PZ-deploy-w12; pz-deploy-guard makes the sync operator-only →
  runbook = reports/deploy/2026-07-03-wave12-operator-runbook.md (REVISED to the
  operator's 5-section spec: backup-first w/ EstrellaDBBackup RED warning —
  task confirmed ABSENT; ordered deploy steps; collision report file + ruling
  table; post-deploy verification incl. prod output-equivalence + C-1f
  mapped-charge exercise; .bak rollback). **Wave order LOCKED (operator verdict,
  verbatim R4):** Wave 3 only after (1) production deploy (2) post-deploy
  verification (3) mirror collision report CLEAN (4) SEPARATE Wave-3
  ratification. On operator "deploy done + verification green + collision
  report clean": jsonl append + W3-A1 → VALID, then WAIT for ratification (4).
  Lesson recorded: LESSONS_LEARNED.md #4 (gate coverage proven, not assumed).
- **HOLD reason:** §5a ratification rule: every wave of the reconstructed
  manifest needs operator ratification at the preceding boundary. WAVE 2
  (Backend) COMPLETE 2026-07-03 under "RATIFIED. Wave 2 begins." (+4
  amendments, recorded `0d12fa60`). Wave-2 ledger: R3 storage-leak `2f44ffba`
  · C-3g `568c05b2` · R2-census `be0b1252` · R3 batch `9044640e` · C-3a/b/c
  `fee3b087` · C-3d `e8d275cd` · C-3e/f + boundary docs (git log tail).
  C-4a SKIPPED per ratification (OI-17 OPEN — "wave completes without it").
  Confidence Gate at boundary: NO INVALIDATED assumptions; W3-A1 AT-RISK
  (prod deploy of the Wave-2 backend = operator 7-agent ritual + CP4; payload
  `service/docs/ops/c3g-deploy-note.md` — mirror backfill + collision check +
  service-registry backfill + returns/sample migrations). Resume: operator
  ratifies Wave 3 (Entire UI) → U-1..U-6; W3-A1 must be LIVE before UI slices
  close (CP3). Runtime: `.claude/campaigns/phase-c-master/RUNTIME.md`.

## Prior task — Architecture Review (COMPLETE)

- **Task:** Architecture Review — gate between Phase A and Phase C/D.
- **Started:** 2026-06-28
- **Status:** COMPLETE
- **Branch / worktree:** read-only investigation, no branch needed.
- **Findings:**
  1. draft_state='converted' is overwritten by _ensure_drafts_table() backfill (status='issued' → draft_state='posted'). Root cause: 'converted' absent from DRAFT_LIFECYCLE_STATES. Non-blocking because 3 guards use wfirma_invoice_id. Phase C fix: add 'converted' to lifecycle states + backfill guard.
  2. Two field conflicts: payment_method and payment_days — CM fields exist but route uses wFirma config fallback. Phase C must make CM win.
  3. Series model: keep flat fields. ADR for mapping table as Phase E future work.
  4. Write-policy: upsert_identity_only() (wFirma sync) uses COALESCE fill-when-empty — cannot overwrite operator series. upsert_customer() (operator UI) is full write — no guard needed yet. Phase C: advisory on series mismatch at convert-readiness.

### Next task — Phase C (write-policy guards + authority cleanup)
- **Known inputs from Phase A production verification (2026-06-28):**
  - SHA: `d3c9bd14e0`, deploy gate 8/8
  - Draft 52: wfirma_invoice_id=484110947, invoice=FV 12/2026, Convert button disabled ✅
  - draft_state='posted' (not 'converted') — persist_invoice_to_draft() ran but state column not updated; non-blocking because three guards active (wfirma_invoice_id + proforma_invoice_links row + _link_already_exists())
  - FV 12/2026: correct WDT VAT code, wrong FV series prefix — KSeF-registered; accounting correction is operator/accounting decision, no automation
  - Customer Master WDT/export series fields visible in UI ✅

### Prior task — Phase A: COMPLETE, deployed, Tier 1 verified (2026-06-28)

- PR #785 squash-merged as `bb9acf0`, deployed prod SHA `d3c9bd14e0`, gate 8/8. 11 files, 18 tests, zero React/Vite. WDT series resolver + payment date guard + conversion persistence + Convert button guard. Smoke 63/63. Tier 1 (Draft 52) verified: Convert guard active, wfirma_invoice_id=484110947. Accounting issue (FV 12/2026 wrong series prefix, KSeF-registered) — operator/accounting decision, no code action.

### Prior task — AWB 9158478722 reconciliation (BLOCKED-HOLD)

- **Task:** End-to-end batch reconciliation post-PZ — AWB 9158478722, batch `SHIPMENT_9158478722_2026-06_924c4e59`, PZ 5/6/2026 (doc 189897571). Verify PZ + sales packing + drafts #34–#43 readiness/reservation; backfill `design_product_mapping`; over-bill check; advisory-vs-blocker per (operator-asserted) Lesson N. **No PZ/product/proforma/reservation/wFirma/fiscal writes.**
- **Started:** 2026-06-23
- **Status:** BLOCKED-HOLD (local half COMPLETE; live half needs prod)
- **HOLD reason (if BLOCKED-HOLD):** Missing access (condition #2) — drafts #34–#43, `pz_rows.json`, `audit.json`, `design_product_mapping` live only in prod `C:\PZ`. Re-confirmed: shipment absent from all local DBs; `localhost:47213`→000; public `pz.estrellajewels.eu`→401 (no token, not hunting for one). Live readiness GETs + over-bill (needs pz_rows qty authority) + PZ-exists-in-wFirma can't run here.
- **Branch / worktree:** `chore/governance-pr719-observe` (Mac) — analysis artifacts only, no code edits.
- **Notes (KEY mechanism):** `GET /draft/{id}/readiness` SELF-POPULATES `design_product_mapping` (write-on-read, routes_proforma.py:5691 docstring) → steps 4+6 are ONE action; operator's "parse → re-run → mapping self-heals" theory CONFIRMED in code. Drafts bind 1:1 to invoices by client header (all evidence-verified): 34→299 Customer-A, 35→296 Customer-B, 36→294 Customer-C, 37→293 Customer-D, 38→292 Customer-E, 39→300 Customer-F, 40→298 Customer-G, 41→291 Customer-H/Customer-L 2, 42→290 Customer-I, 43→297 Customer-J/Customer-K. 80 real SKU lines, 66 distinct designs, 3 PND advisories (inv299 sr3/7/8 PO LM). PZ arithmetic internally consistent (21×409.03=8589.63; net×1.23=gross; VAT 23%). Bridge: `design_product_bridge.populate_from_packing`; mapping DB=`reservation_queue.db`. Lesson N NOT in CLAUDE.md (stops at M) — flagged for codification. Prod runner: `.claude/campaigns/sales-packing-290-300-reconcile/prod_reconcile.py` (read-only, 10 readiness GETs + pz_rows over-bill). Artifacts in that campaign's `artifacts/`.

### Earlier sub-task (COMPLETE) — Draft #34 sales-packing parse

- 10/10 packing lists parsed; same campaign artifacts (packing_authority.json, reconciliation_input.json). Superseded by this end-to-end task.

### Prior task — DHL DSK/cesja auto-forward VERIFICATION (BLOCKED-HOLD, same AWB)

- Determine failure path (A poll-latency / B ingest-classify / C SMTP-gate / D monitor-not-running). Same access boundary: prod state on `C:\PZ`. Awaiting Kaushal to run `.claude/campaigns/dhl-agency-forward-verify/collect-evidence.ps1`. Shipment operationally UNBLOCKED (manual notify-to-proceed msg `1782120964135130200`, delivered). Send gate = `_smtp_configured()`+`ENV=prod` (`email_sender.py:517`); triggers `active_shipment_monitor.py:1702-1735`.

### Prior task (PR open) — Proforma draft authority UI (V1)

- `feat/proforma-authority-ui` @ `C:\PZ-pf-ui` (base origin/main `dc58ad4`). Display-only customer-authority summary + canonical product-description + blocked draft-birth records; V2 inspected/reported not switched. GATE-6 = JSX compiles (offline Babel) + 46 structural tests; browser verify deferred to deploy. reviewer-challenge + frontend-flow CLEAR. BACKLOG B-012..B-014.

### Prior task (COMPLETE) — PR-3 Dropdown selection wins

- PR #675 squash-merged at `7b94a73`; backfill verified in prod on SHIPMENT_9158478722. PR-2+PR-3 DEPLOYED to C:\PZ @ 7b94a73, hashes match.

### Completion criteria (PR-3)

- [x] Forward: grouping uses canonical CM bill_to_name (overrides parsed); sales chain canonicalized (no split-brain); re-upload no dup
- [x] Resolver contractor-id-first (`derive_customer_authority_for_draft`); routes_proforma threads it
- [x] Migration (operator-triggered backfill, EDITABLE only): rename/supersede per clone_generation; charges money-safe (frozen canonical never drops); reservation canonical-wins; full disclosure (dropped/orphan/ambiguous)
- [x] Fixed latent NameError (`log` unbound in proforma_invoice_link_db.py — also affected PR-2 block helpers)
- [x] 16 real-builder tests; 208-test regression + smoke 63; full reviewer battery (3 implementation bugs + 1 latent NameError caught & fixed)
- [x] No valuation / CIF / PZ / accounting / booking / wFirma-API change
- [ ] Deploy PR-2 + PR-3 to production (C:\PZ) via 7-agent gate + operator backfill of SHIPMENT_9158478722 — PENDING (operator-run)

### Prior task (COMPLETE) — PR-2 Contractor-at-Birth Projection

- PR #673 squash-merged at `f652de0`. Carried `shipment_documents.client_contractor_id` through sales → draft → reservation; visible blocked draft-birth records; idempotent backfill. FEATURE_SCORECARD Row #1.


---

## History (most recent first)

- 2026-08-11 — **PR #1178 product-description authority MERGED (`3710aa12`) and DEPLOYED inside
  the `7150996b` tip; campaign CLOSED.** One shared multi-metal tokenizer
  (`parse_material_components()` in `description_grammar.py`) replaced two independent
  first-match-wins single-metal parsers that had been silently discarding a real material from
  combination rows, and inventing a `925` purity on bare `SILVER`; `NAME_PL_SOURCE_MACHINE_BIRTH`
  ended the `operator`-provenance lie that made machine-born names uncorrectable by enrichment,
  with `unknown` fail-closed to `operator`. Gated 7/7 GO at `1707e630` (payload-identical to the
  merge). **Release-targeting lesson recorded:** `-Release` self-resolves `origin/main`
  (`Deploy-PZ.ps1:1531`) and `Assert-ReviewedTarget` refuses any SHA the tip has advanced beyond
  (`:793`), so a merged PR is **not** a deployable unit — #1180 landed on top and the deploy
  necessarily carried both. The two changesets were proven **file-disjoint** by measurement
  before the gate, and the ride-along was disclosed to the operator rather than shipped
  silently. Operator deployed `-Release -Scope Both` (Lesson J: 3 of 4 files are governed
  `engine_files`), then converged the draft through the **normal** `reset-from-sales-packing`
  authority — dry-run `conflicts=0 skipped_protected=0`, 29 rows promoted, reset run twice with
  identical results, draft totals unchanged, no Post/Convert, no wFirma mutation. The four
  wFirma goods keep their old wrong names by design; fixing them is a separate gated operator
  action. Detail in the current-task block above.
- 2026-08-07 — **PR #1104 rebased to main + CMR stale-test repair folded in (test-only;
  no new PR — GATE 2 exactly full at #1110/#1109/#1104).** New state: base `main`, head
  `8ddc80c1`, 2 commits, diff vs main = exactly 2 test files
  (`service/tests/test_sales_packing_reingest.py` +117/−3,
  `service/tests/test_cmr_packing_lines.py` +38/−9). Mechanics: old base branch
  `fix/sales-pnd-candidate-authority` had merged as `f43796bc` (= then-main tip), so the
  single coverage commit was replayed `--onto origin/main f9008292` (clean), the PR base
  retargeted to `main`, and the CMR repair cherry-picked on top (its parent was exactly
  the main tip). Force-pushed `--force-with-lease`; disclosure comment posted on the PR.
  **CMR diagnosis — stale test, NOT a regression (Lesson O-style triage; zero production
  files touched):** 3 tests grepped `proforma-detail.jsx` for `l.item_type` / `l.metal` /
  `l.stone_type` / `l.quantity` / `l.net_weight`, identifiers dead since `0de180f1`
  (PR #699 rewrote `_cmrAggPackingLines` to aggregate draft `editable_lines` as `ln`
  [billed-qty authority `ln.qty`] enriched by `pk = _enrichPacking(ln)` [`pk.metal`,
  `pk.stone_type`, `pk.net_weight`, `pk.item_type` fallback]); the aggregation contract
  is intact. Red ~2 months unnoticed — file sits outside the metered floors (same
  governance class as `test_pnd_tiebreak_persists`, which this PR also fixes). Migrated
  tests now pin the ln/pk contract and are scoped to the `_cmrAggPackingLines` IIFE body
  (`_agg_src()` helper) instead of the whole 6k-line file. **Verification at `8ddc80c1`:**
  `test_cmr_packing_lines.py` + `test_sales_packing_reingest.py` 90/90; adjacent
  `test_sales_pnd_candidate_authority.py` + `test_intake_currency_and_pnd.py` 23/23.
  **Merge deferred (operator rule): #1104 merges after the current production deployment
  target is no longer held stable; it is NOT a deploy blocker.**

- 2026-08-06 — **PR #1094 CLOSED (merged)** — `feat(deploy): make seven-agent gate evidence a
  machine-checked, tamper-bound precondition of signing`. **Merged SHA
  `77ded8e23e8d92e627e2d77c7f032a9144cfc8b7`**, merged by `amitpoland` 2026-08-06T06:38:34Z,
  now `origin/main` tip (parent `6e1de8b1`, single-parent — a squash merge). **Ruled head
  `9be5970055e481bef6df0b6c226730e4fd3d3adf`** — round 9's frozen head. Ancestry check
  `git merge-base --is-ancestor 9be59700 origin/main` returns **NO** (exit 1) because the
  merge was a squash: the squash commit records none of the branch's commits as parents, so
  `9be59700` is unreachable from `origin/main` by any path, not merely off the first-parent
  chain (`--is-ancestor` walks all parents, so this is a genuine absence) — **but**
  `git rev-parse 77ded8e2^{tree}` and `git rev-parse 9be59700^{tree}` are **both
  `dc892ead813e8a316166895fbf102f4700293ca0`**: byte-identical trees. Record both halves —
  ancestry alone would wrongly read as "the ruled head never shipped"; tree equality is what
  proves it did. Diff: 11 files, 12 commits on the branch, +3305/−45, touching only
  `.claude/commands/deploy.md`, `.claude/contracts/{seven-agent-evidence.md,test-baseline.md}`,
  `.claude/hooks/{deploy_authorization.py,gate_evidence.py,sign_deploy_authorization.py}`,
  `.claude/memory/TASK_STATE.md`, `docs/ops/release-mode-implementation-plan.md`,
  `service/docs/production_deployment_rule.md`,
  `service/tests/{test_deploy_reconcile_signing.py,test_gate_evidence.py}` — zero files under
  `service/app`, `.claude/deploy`, or any root engine module.

  **Round 9 outcome**: six specialists CLEAR/PASS + `deploy_lead_coordinator` **GO** ("READY
  FOR OPERATOR MERGE"). Operator merged. **What shipped**: seven-agent gate evidence is now
  strict JSON, validated by `.claude/hooks/gate_evidence.py`, digest-bound into the signed
  authorization body by `.claude/hooks/sign_deploy_authorization.py`, and re-checked at
  use-time by `.claude/hooks/deploy_authorization.py` for the `deploy` and `reconcile` actions
  (NOT `rollback`). Evidence gates SIGNING; the HMAC artifact gates the DEPLOY.

  **Corrected numbering (Lesson Q rule 5 — marked, not silently replaced):** an earlier
  in-session narration said the tolerant Markdown parser was abandoned after round 7. That was
  **wrong**; corrected from the commit log — `ed62ed59` ("the tolerant parser was the defect")
  lands after three fix commits, so the parser was abandoned after **round 3**. Rounds 4–8
  reviewed the strict-JSON rewrite; round 9 was the narrowed final round.

  **PRODUCTION STATUS — unverified and unchanged.** No deployment was performed, no Windows
  service touched, no signed authorization minted. The merge changed the repository only.
  Production's actual running SHA is **unknown to this session** and must not be inferred from
  merge history; treat production identity as unestablished until measured on the host.

  **Scorecards on disk (RULE 6 citation)**:
  `.claude/memory/scorecards/2026-08-06-pr1094-gate-evidence-nine-rounds.md` (65 KB) and
  `.claude/memory/scorecards/self-eval-2026-08-06.md` (18 KB, verdict **SELF-DEGRADATION
  DETECTED**, 28/35 down from 31).

  **GATE-4 dispositions carried forward** (from the campaign scorecard, verified against
  `2026-08-06-pr1094-gate-evidence-nine-rounds.md` §D-1..D-5): **D-1 ISSUE** — make Lesson Q
  rule 6's `reviewer-challenge` second pass mandatory rather than advisory (it was never run
  in nine rounds); **D-2 ISSUE** — `deploy_lead_coordinator` needs a recurrence-aware exit
  criterion; **D-3 ISSUE** — `deploy_git_diff_reviewer` needs an absence-claim protocol;
  **D-4 SCHEDULED** — charter gap: no agent in the registry is chartered to challenge a
  *design* rather than a diff; **D-5 SCHEDULED** — a live contradiction shipped in the merged
  tree: `.claude/contracts/seven-agent-evidence.md:240` claims the chain is "bounded at 24
  hours from the moment the round concluded", while `.claude/hooks/sign_deploy_authorization.py:248`
  states of that exact claim "It is not. It is bounded at 24h from the `created_at` the
  evidence ASSERTS, and nothing ties that field to when the round actually ran" — and the
  contract also contradicts itself at line 240 vs. lines 141–144. This is an optimistic
  (permitting) safety claim, Lesson Q rule 6's higher-scrutiny class, and it passed six
  CLEAR/PASS verdicts plus a lead GO undetected.

  **Four follow-up buckets — NOT executed, recorded only:**
  1. Re-mint pre-existing `deploy` / `reconcile` authorization artifacts on the Windows host —
     including artifacts that "look fine." An artifact digest-bound to a Markdown-era evidence
     file still *passes* the use-time check (it re-hashes bytes, does not re-validate against
     the new schema), so a stale artifact can deploy citing evidence that would no longer pass
     the gate which produced it. `rollback` artifacts are unaffected — incident capability
     survives.
  2. File two GATE-4 ISSUEs: (a) `Deploy-PZ.ps1:1308` consumes the single-use `jti` *before*
     the identity gate at `:1321` — inherited from `main`, explicitly NOT fixed inside #1094;
     (b) the unpinned 5-argument reconcile CLI shape.
  3. One docs-only PR carrying the ~26 enumerated round-9 prose follow-ups, per the lead
     coordinator's condition that each item be transcribed verbatim from the six round-9
     reports — fold D-5 (instance #14) into this PR.
  4. (folded into #3 above) D-5 instance #14 contradiction fix.

  Written by `flow-context-keeper` in an ephemeral remote container; `.claude/memory/PROJECT_STATE.md`
  is gitignored and absent here — see the companion `PROJECT_STATE.md` initialized this session
  for the disclaimer. No git commit/push performed by this agent.

- 2026-08-01 — **PR #1062 AMENDED** (base `main`, head `fix/deploy-production-identity-gate`,
  tip **`70e1e883`**) after the operator ruling *"#1062 must not merge in its present form —
  the missing reconciliation authority is a genuine blocker."* Closure-2 is now **in** this PR
  rather than held. Adds `-Reconcile -FromSha X -ToSha Y` implementing all 9 contract
  guarantees (authorization binds action + **both** SHAs via a signed `from_sha` field;
  runs under the deploy lock; PROOF 1 runtime==FromSha; PROOF 2 repeated after service stop
  immediately pre-backup, closing the mutation window; backup records `restored_sha = FromSha`
  from the proof, never the marker; converge only to ToSha; PROOF 3 vs ToSha; version marker
  written only after PROOF 3; any failure before PROOF 3 leaves the old marker intact and mints
  no target-labelled unit). **`-Bootstrap` over an existing non-empty runtime now FAILS CLOSED**
  — it was the one path that skipped the identity gate. Hardening covers the four required
  review checks: git filters applied via repository-relative path (not `core.autocrlf` alone);
  ordinal dict + separate ordinal-ignore-case set for collision detection, blocking **before**
  compare with `CASE-DIFFERS` its own class; reparse points detected **before** recursive
  descent via an explicit queue. Reviewed mainline `c3629786` merged in first (file sets
  disjoint, no conflicts), then all three suites rerun against a clean `git archive HEAD`
  export of `70e1e883`: **47/0** behavioural, **71/71** static pins, **160/160** golden.
  **Real defect found by the new tests:** a local `$restoredSha` case-folded onto the
  `$RestoredSha` parameter (PowerShell variable names are case-INSENSITIVE) — ordinary deploys
  were labelled `mode=reconcile` and the no-marker case recorded `restored_sha: ""`; rollback
  safety never breached (the resolver shape-checks and still refused) but the metadata was
  untruthful. **The static pins were all green while this shipped** — only the behavioural
  control case caught it. Amendment summary posted as a PR comment for operator review
  (`#issuecomment-5150438353`), genericized for the public repo. **Deploy tooling + tests only
  — no production file, service, or runtime byte touched.** Status: **OPEN, operator-merge-only**;
  the forward prod re-converge stays HELD — no signer is provisioned, so every authorization
  evaluation returns DENY by design, which is why an agent cannot run `-Reconcile`. The existing
  runtime is preserved as evidence, not a trusted rollback unit.
  Detail: [[project-deploy-identity-gate-campaign]].

- 2026-07-31 — **PR #1061 OPEN** (base `main`, head `state/task-register-checkpoint-2026-07-31`):
  publishes THIS accurate register to main, correcting main's stale copy (which showed #1049 as
  `UNDER_REVIEW`) and preserving the load-bearing #1043 `EXECUTION_BLOCKED` resume checkpoint.
  Checkpoint commit `f8a7225f` (cherry-pick of `d56a17ae` onto `origin/main` `423fa3cb`),
  docs/governance-only. GATE-2 doc allowance (does not displace the impl queue). Provenance:
  existed only as an uncommitted edit in the `C:\PZ-verify` root tree; archived cmp-identical to
  cold storage (`evidence-2026-07-31`) before commit. **Refreshed this session** to fold in the
  #1043 agent-side-complete / operator-handoff delta + HYBRID prod current-state fact + 7-agent
  gate re-confirmation + #1052/#1057/#1059 history. Operator merge owed (merge/deploy operator-only).

- 2026-07-31 — tracking_cache inner-record fix: **PR #1052 SQUASH-MERGED `c3629786`**
  (2026-07-31T06:06:38Z, base `main`; now origin/main HEAD). AWB-keyed `tracking_cache.json`
  read at the wrong nesting level → tracking status silently `""`; fix adds 2 shared helpers at
  both read sites. +18 tests; golden 160/160; 19-fail pre-existing baseline unchanged.
  **Production surface — DEPLOY OWED**, blocked behind the open #1043 HYBRID hold (merge/deploy
  operator-only). Detail: [[project-tracking-cache-inner-record-pr1052]].

- 2026-07-31 — test-baseline stale-classes: commit `f5b99dd4`, **PR #1059 OPEN** (base `main`,
  docs-only — 1 file `.claude/contracts/test-baseline.md`, +25). Registers 4 stale-test-contract
  classes (ON CONFLICT ×29 / settings.environment ×7 / _c1f_mirror_good_id_with_fallback ×6 /
  extract_packing arity ×13) from full `service/tests` reconciliation; zero new prod regressions,
  no floor change (PZ 260/260, Carrier 646/604, golden 160/160). GATE-4 SCHEDULED. Isolated off
  #1058's `a97ec20d` via rebase --onto (no git-stash). Docs-only → GATE-2 doc allowance; operator
  merge owed. Detail: [[project-test-baseline-stale-classes-pr1059]].

- 2026-07-31 — Lesson A stub-drift fix: commit `ef03797d`, PR #1049 opened (base `main`,
  test-only). GATE 4 grep-drift disposition filed as issue #1048. GATE 2 → 3/3 open.

- 2026-06-21 — Task #4 COMPLETE: PR #687 updated (intake diagnostics, IntakeDiagnosticsCard, T12–T15)
- 2026-06-21 — Task #3 COMPLETE: PR #687 updated (proforma draft blocker visibility in V2 proforma tab)
- 2026-06-21 — Task #2 COMPLETE: PR #687 updated (DHL clearance pipeline diagnostics in V2 DHL tab)
- 2026-06-21 — Task #1 COMPLETE: PR #687 draft (proforma readiness display in V2 proforma tab)

- 2026-06-20 — /feature command created at .claude/commands/feature.md.

- 2026-06-21 — PR #675 squash-merged at `7b94a73`: PR-3 Dropdown selection wins.
  Scorecard `2026-06-21-pr3-dropdown-selection-authority.md` (6 agents, 5 EXEMPLARY / 1 ACCEPTABLE).
  Battery caught 3 implementation bugs + 1 latent NameError, all fixed pre-merge. BACKLOG B-009..B-011 filed.

- 2026-06-20 — PR #673 squash-merged at `f652de0`: PR-2 Contractor-at-Birth Projection.
  Scorecard `2026-06-20-pr2-contractor-at-birth-projection.md` (9 agents, 6 EXEMPLARY / 3 ACCEPTABLE).
  BACKLOG B-002..B-008 filed (all SCHEDULED). PROJECT_STATE updated.

- 2026-06-20 — /feature command created at .claude/commands/feature.md.

  COMMAND_REGISTRY.md updated. BACKLOG B-001 (PR #661 review) filed.
- 2026-06-20 — TASK_EXECUTION_PROTOCOL.md created and merged via draft PR.
  Canonical DISCOVERY→PLAN→IMPLEMENT→VERIFY→CLOSE protocol. BACKLOG.md seeded.
- 2026-06-20 — PR #630 squash-merged at a40c7c5. PR-1A closes B1–B5 governance
  gaps post PR-1 (#626). PR-2 (ADR-022 Snapshot Layer) now unblocked.
- 2026-06-20 — PR #659 + PR #660 merged (governance package). GATE 2 back to 0/3.
- 2026-06-20 — Task opened: Finalize PR #630.
