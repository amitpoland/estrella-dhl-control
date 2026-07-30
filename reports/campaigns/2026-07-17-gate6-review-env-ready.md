# GATE-6 Review Environment — REVIEW_ENV_READY (2026-07-17)

Campaign: supply the missing GATE-6 review environment for PR #940 (OPEN/DRAFT @ 13d442e9).
OS v1.4 active. Sole session. Registry NOT transferred (owner still M1-gate session);
C:\PZ-pr7 untouched; #940 code unchanged; carrier baseline unchanged; no deployment.

## Outcome: REVIEW_ENV_READY

A reusable, fail-closed, non-production review bootstrap now serves commit `13d442e9` with
isolated storage, generated non-production auth, provably-off live writes, and a deterministic
two-client transport scenario. Branch `review/gate6-bootstrap` @ `dcfa8d16` (off main `9d137850`).

## Proven (runtime evidence, this environment)

| Property | Evidence |
|---|---|
| Serves exact commit | `GET /api/v1/system/version` → `{"commit":"13d442e9"}`; startup log `Engine dir: C:\PZ-wt\review-940-tree`; served `/v2/proforma-detail.jsx` sha256 == extracted-tree file (byte-identical); `_CMR_COUNTRY_NAMES` present |
| Isolated storage | all DBs under `C:\PZ-wt\review-940-storage` (outside repo + every live root) |
| Non-production auth | generated `rev_…` key; API 401 without key; ENVIRONMENT=dev; fresh JWT secret |
| Live writes OFF | startup `all wFirma write flags FALSE`; `SERIES_BOOTSTRAP_ENABLED=false` (no wFirma fetch); carrier `shadow` + empty allowlist; no `mydhlapi` in logs; no server errors |
| Cross-client isolation (#940) | `?client_ref=REV-A`→AWB1000000001; `?client_ref=REV-B`→AWB2000000002 (distinct); no `client_ref` on multi-client batch → **404** (legacy NULL row not leaked) |
| Representative data | Alpha full invoice `FV 7/2026`; Beta honest-null; legacy AWB `AWB0000000000`; origin `IN`→CMR India |
| Deterministic + reset | re-seed yields identical manifest; `--reset-review-data` removes only the isolated storage |

## Tests

`service/tests/test_review_bootstrap.py`: **13 passed** vs the served tree (`REVIEW_APP_DIR=13d442e9`);
8 passed + 3 gated-skips vs the older repo tree (portability). Pre-commit smoke 63 passed/1 skipped.
Root golden 160/160 (additions are new files only).

## Reviews (read-only) + fixes applied

reviewer-challenge SHIP-WITH-MITIGATIONS · security-permissions PASS-WITH-MITIGATIONS ·
backend-safety-reviewer SAFE-WITH-NOTES. **Two HIGH findings fixed inline before READY:**
1. Hardcoded production roots `C:\PZ[\storage|\app\storage]` into the isolation guard (was reachable
   for a destructive `--reset` if the shell lacked `STORAGE_ROOT`) — now refused unconditionally + case-insensitive.
2. Expanded credential neutralisation from DHL/wFirma-only to **all** external services (Cliq,
   WorkDrive, Zoho Mail, SMTP, Anthropic, DHL-tracking) + fresh JWT secret; narrowed the docstring claim.
Also: PLT status asserted; commit-fingerprint advisory; stale comment fixed;
`WFIRMA_SYNC_CUSTOMERS_ALLOWED` added. All pinned by tests.

## Exact commands (runbook: docs/ops/gate6-review-environment.md)

```
# 1. extract the exact tree (SHA, not the campaign branch)
mkdir -p C:/PZ-wt/review-940-tree && git archive 13d442e9 | tar -x -C C:/PZ-wt/review-940-tree
# 2. seed (before serving)
python service/scripts/review_seed.py --app-dir C:/PZ-wt/review-940-tree/service \
  --storage-root C:/PZ-wt/review-940-storage --commit 13d442e9 --reset-review-data
# 3. serve (preview manager)
preview_start name="pz-review-940"        # http://127.0.0.1:8137
# 4. login/auth: capture REVIEW_API_KEY from preview_logs (search "REVIEW_API_KEY"); use -H "X-API-Key: <key>"
# 5. reset:   python service/scripts/review_seed.py --storage-root C:/PZ-wt/review-940-storage --reset-review-data
# 6. shutdown: preview_stop serverId=<id>
```

## Disposition

Review environment READY and proven safe.

**PR #941 (integration campaign) — ✅ MERGED (operator squash) 2026-07-17T21:13:56Z.**
Source head `2c8d980d13f4332c5ad08acd00d3c4be89d706b9`; **squash SHA
`74a354a43d902e56a7c5f69b00c2d5fd7746b696`**; **new main SHA = `74a354a4`** (squash = main tip).
Branch `review/gate6-bootstrap`, 2 commits, exactly 5 changed files (launch.json, docs runbook,
review_launch.py, review_seed.py, test_review_bootstrap.py) — no #940/business-logic. Head `2c8d980d`
hardened the initial `dcfa8d16` after the review battery: FedEx-tracking + AI-Cowork + webhook-HMAC
creds neutralised, AI exec flags forced off, other permanent worktrees protected
(PZ-main/-active/-verify/-archive), fail-closed partial-delete, `--commit` required.

**Post-merge verification on main `74a354a4`:** all 5 bootstrap files present on main (ls-tree);
`test_review_bootstrap.py` **15 passed**; `git diff --check` clean. Pre-merge exact-head evidence
(no GitHub status checks registered → local verification): golden 160/160, smoke 63/1-skip; serves
`13d442e9` with isolation REV-A→AWB1000000001 / REV-B→AWB2000000002 / no-client_ref→404 / no-key→401;
manifest holds no secret (sha256 fingerprint only). No secret literals in any committed file.
**No deployment occurred** (merge to main only; production sync is a separate operator-gated step).

Unresolved LOW (non-blocking): WFIRMA_SYNC_SUPPLIERS_ALLOWED flag (local suppliers.sqlite only);
`_warn_if_commit_unverified` advisory fires after version.json (extracted archives have no .git).

**#940 browser verification is the SEPARATE next execution** against this environment; #940 stays DRAFT.
No deployment; no live writes; registry untouched.
