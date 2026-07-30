# PR #1039 — rollback provenance: merge, deploy, closure

**Date:** 2026-07-31
**Campaign:** `rollback-provenance`
**Authority owner:** `Deploy-PZ.ps1` and its backup-unit provenance model
**Outcome:** CLOSED — merged, deployed, verified. First provenance-aware backup unit exists.

---

## 1. What shipped

`Invoke-Rollback` reused a single field (`unit.json.sha`) for two different authorities:
the **authorization target** and the **restored-content identity**. After a rollback,
production held the OLD bytes but advertised the NEWER deployment SHA in `version.txt` —
the bytes went back while the advertised identity went forward.

The fix separates the two identities:

| field | meaning | written by |
|---|---|---|
| `deployment_sha` | authorization identity — what the HMAC artifact binds to | deploy |
| `restored_sha` | content identity — what gets stamped into `version.txt` | deploy (captured from the pre-deploy marker BEFORE any mutation) |
| `version.pre.txt` | write-once corroborating snapshot at the unit root | deploy |

`version.pre.txt` exists because `unit.json` is rewritten when `complete` flips true; a
second, write-once source lets rollback cross-check the identity it is about to stamp.

Rollback now resolves `restored_sha` from trusted evidence, stamps it, reads it back and
asserts equality. **Fail-closed throughout:** no trusted `restored_sha` → BLOCK; the
deployment SHA is never a silent fallback; no SHA is inferred from a directory name; both
sources present but disagreeing → BLOCK. Authorization binding is UNCHANGED.

Five files, 715 insertions / 7 deletions. Zero application code.

---

## 2. Operator decision — legacy compatibility (recorded before merge)

> APPROVED: Merge and deploy PR #1039 with fail-closed legacy compatibility. Existing
> legacy governed backup units must remain immutable and unusable; no provenance backfill
> is authorized. The deployment must create and verify a new provenance-aware backup unit
> before the campaign may close.

Both pre-existing selectable units (`92222849…-20260730-220450`,
`c7903686…-20260730-194654`) carry only the legacy `sha` field — no `deployment_sha`, no
`restored_sha`, no `version.pre.txt`. After this ship, `-Rollback` on either is REFUSED.

That was accepted deliberately rather than backfilled: those units hold no reliable
prior-production provenance, and reconstructing it from filenames, current state, git
history or deploy ordering would manufacture historical truth outside the immutable
backup process — weakening the very authority model this PR introduces. The exposure
lasted only until this deployment minted a provenance-aware unit.

The 14 date-named directories were **not** part of the decision: they fail `UNIT_RX`
(`^[0-9a-f]{40}-\d{8}-\d{6}$`) and were never selectable. No regression there.

Verified live: the closure validator reports `rollback unit available  units:
1ce0e76d…-20260731-003346` — the legacy units are no longer offered. Fail-closed refusal
is working as designed.

---

## 3. Merge

Pre-merge recheck (immediately before merge): `state=OPEN`, `isDraft=false`,
`headRefOid=719c28fa21cad400ac07a28c09b872280bef1c51`, `mergeable=MERGEABLE`,
`mergeStateStatus=CLEAN` — all five required conditions held.

- **Merge commit:** `1ce0e76d4b31c6cdd9b309c03517e92be719ed89`
- **Parents:** `92222849` (main) + `719c28fa` (reviewed head) — a true merge commit, not a squash
- **Ancestry:** `git merge-base --is-ancestor 719c28fa 1ce0e76d` → OK; reviewed head preserved
- `C:\PZ-main` fast-forwarded to `1ce0e76d`, working tree clean

Merge, authorization minting, and deploy were executed **by the operator**. The agent is
denied all three by `pz-deploy-guard` (`gh-pr-merge`, `deploy-script-invocation`) and has
no signing key. See §7.

---

## 4. Deployment

Deployed at 2026-07-31 00:33:47 (+02:00) from the post-merge, provenance-aware
`Deploy-PZ.ps1`. New backup unit:

```
1ce0e76d4b31c6cdd9b309c03517e92be719ed89-20260731-003346
```

`unit.json`:

| field | value | required | verdict |
|---|---|---|---|
| `deployment_sha` | `1ce0e76d…719ed89` | merge SHA | PASS |
| `restored_sha` | `922228499746e694c7e261171ac6bc055aa79932` | prior production | PASS |
| `sha` (legacy) | `1ce0e76d…719ed89` | present | PASS |
| `complete` | `true` | true | PASS |
| `scope` | `Both` | — | — |
| `app_backed_up` / `engine_backed_up` | `true` / `true` | — | — |

`version.pre.txt` = `922228499746e694c7e261171ac6bc055aa79932`.

**Both prior-production identities agree.** This is the first backup unit in the repository's
history that can be rolled back to without the identity defect.

---

## 5. Closure validation — 10/10 PASS

`Test-PZDeployClose.ps1 -ExpectedSHA 1ce0e76d…` (no `-Verbose`, outside `Start-Transcript`):

```
PASS  version_file is BOM-free
PASS  version_file matches ExpectedSHA
PASS  source_root HEAD == ExpectedSHA
PASS  production matches artifact manifest   0 discrepancies
PASS  engine files match source
PASS  protected runtime paths intact
PASS  PZService Running
PASS  health http://127.0.0.1:47213/api/v1/health   HTTP 200
PASS  health https://pz.estrellajewels.eu/api/v1/health   HTTP 200
PASS  rollback unit available   units: 1ce0e76d…-20260731-003346
```

Content parity (Lesson P): manifest diff = 0 discrepancies, engine files match source —
verified by content, not by robocopy's copy count.

**Runtime:** NSSM PID 19416 up since 00:34:05 with a single child (python PID 23308,
00:34:06). One continuous run, one child — no restart loop. `pz_stderr.log` contains only
the clean uvicorn startup banner; no traceback, no ERROR. The health watchdog logged
exactly one `FAIL [1/2]` at 00:33:49 (the governed restart window), `RECOVERED` at
00:34:47, and unbroken `OK HTTP 200` since; watchdog state `0`.

---

## 6. Authorization state

| artifact | jti | consumed |
|---|---|---|
| `1ce0e76d….deploy.json` | `6a587e2a-2621-44c1-b171-6eeb832bce8f` | **True** (expected) |
| `1ce0e76d….rollback.json` | `01ead337-86f0-43e0-92a6-5d018daa8fbb` | **False** (required) |

The rollback authorization remains unconsumed and valid until 2026-07-31T22:33Z.
Consumption state was read from the filesystem (artifact JSON + `consumed/<jti>.used`);
`evaluate()` was **never** called for the rollback action, because it consumes on success.

**No rollback was executed at any point in this campaign.** No existing backup unit was
written to. No legacy metadata was backfilled. No historical SHA was inferred.

---

## 7. Governance

**Operator boundary.** Three steps of the plan are structurally unavailable to the agent
and were correctly handed back rather than worked around:

- **merge** — `pz-deploy-guard` rule `gh-pr-merge`. The Council-authorized path is
  default-OFF with no signer, and even when armed permits **squash only**, which this
  directive forbade.
- **mint** — `PZ_DEPLOY_AUTH_KEY_FILE` / `PZ_DEPLOY_AUTH_KEY` absent from the agent
  environment.
- **deploy** — rule `deploy-script-invocation`; `Deploy-PZ.ps1` is operator-only by name,
  `-WhatIf` included.

The agent declined to run its own wrapper script (`operator-1039-merge-deploy.ps1`), which
would have slipped both guarded actions past the name-based rules on a filename
technicality — and would have merged, then failed at the mint step for want of a key,
stranding the campaign mid-flight.

**Gates.** GATE 1 satisfied at PR open (48 pytest pins + 21 behavioural checks + root
golden 160/160, proven on the post-merge tree `f223589c`). GATE 6 N/A — deployment tooling,
no UI surface. GATE 2: this closes the last open implementation PR.

**GATE 4 dispositions** (9, in `active-campaigns.json` → `rollback-provenance.gate4_dispositions`):
M-1 legacy-unit compatibility RESOLVED by the operator decision in §2; M-2 closure-assertion
integration test SCHEDULED (executing it requires a real rollback, which was forbidden);
M-3 + LOW-1 fixed in `719c28fa`; LOW-2 + L-3 ACCEPTED; F-2 (`-RestoredSha` override)
deferred to a separate PR with its own security review; H-1 + H-2 fixed and pinned.

---

## 8. Residual state

- Production runs `1ce0e76d4b31c6cdd9b309c03517e92be719ed89`.
- Exactly one rollback target is available, and it is provenance-complete.
- The two legacy units remain immutable and refused. Recovering them, if ever wanted,
  requires the separately governed procedure in
  `service/docs/production_deployment_rule.md` §"Legacy unit recovery" — an operator
  action, not a maintenance task.
- M-2 remains the one scheduled follow-up: an integration test that exercises the closure
  assertion end-to-end, which needs a real rollback in a non-production harness.
