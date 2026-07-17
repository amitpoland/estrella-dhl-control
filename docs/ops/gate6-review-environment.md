# GATE-6 Review Environment (non-production, safety-gated)

A reusable bootstrap that serves an **exact git commit** of the service with isolated storage,
a generated non-production API key, all live DHL/wFirma writes **provably off**, and a
deterministic representative dataset — so an operator can browser-verify user-visible behaviour
(e.g. PR #940 transport authority) without any production risk.

Reusable for any GATE-6 campaign: pass a different `--commit`/tree. #940 is the first consumer.

## Components (all additive, canonical-service-reuse only)

| File | Role |
|---|---|
| `service/scripts/review_launch.py` | Fail-closed launcher: neutralises live creds/flags, forces carrier SHADOW + empty allowlist, isolated storage, writes `version.json` (commit fingerprint), serves the extracted tree in-process. |
| `service/scripts/review_seed.py` | Deterministic seeder via canonical service APIs + manifest + `--reset-review-data`. Version-tolerant (degrades gracefully on trees predating #940 `client_ref`). |
| `.claude/launch.json` → `pz-review-940` | `preview_start` entry that runs the launcher for commit `13d442e9`. |
| `service/tests/test_review_bootstrap.py` | Safety + determinism + isolation + reset tests. |

## Safety model (fail-closed)

The launcher **refuses to start** if the storage root overlaps a live root
(`service/app/storage`, `service/storage`, or the host `STORAGE_ROOT`), or if `--app-dir` is
invalid. It then force-clears every DHL/wFirma credential to empty, forces every
`WFIRMA_*_ALLOWED` flag off, sets `CARRIER_API_STATUS=shadow` + empty `CARRIER_LIVE_ALLOWLIST`
(the shadow carrier adapter makes **no** outbound HTTP), disables the wFirma startup refresh,
and asserts none survived. The seeder shares this exact gate.

## Runbook (commit 13d442e9 = PR #940)

**1. Extract the exact tree** (SHA, not the campaign branch — no C:\PZ-pr7, no registry, no guard):
```
mkdir -p C:/PZ-wt/review-940-tree
git archive 13d442e9 | tar -x -C C:/PZ-wt/review-940-tree
```

**2. Seed the isolated review storage** (do this BEFORE serving — the server auto-creates empty DBs):
```
python service/scripts/review_seed.py \
  --app-dir C:/PZ-wt/review-940-tree/service \
  --storage-root C:/PZ-wt/review-940-storage \
  --commit 13d442e9 --reset-review-data
```
Writes `C:/PZ-wt/review-940-storage/review-manifest.json` (served commit, storage paths, seeded
draft IDs, expected AWB/invoice values, live-write-disabled proof).

**3. Serve** via the preview manager (do **not** use the wrong-worktree preview):
```
preview_start name="pz-review-940"     # → http://127.0.0.1:8137
```
Capture the generated key from the launcher banner in the server logs:
`preview_logs (search "REVIEW_API_KEY")` → `REVIEW_API_KEY=rev_…`.

**4. Prove it serves 13d442e9:**
```
curl http://127.0.0.1:8137/api/v1/system/version         # → {"commit":"13d442e9",...}
# served JSX hash == extracted file hash:
sha256sum C:/PZ-wt/review-940-tree/service/app/static/v2/proforma-detail.jsx
curl -s http://127.0.0.1:8137/v2/proforma-detail.jsx | sha256sum
```

**5. Authenticate** API calls with `-H "X-API-Key: <REVIEW_API_KEY>"`. The `/v2/*` pages render
without a login in review (dev-tier); API routes require the key. (No key → 401.)

**Seeded scenario (batch `REVIEW-GATE6-940`):**
- Client **Alpha** (`client_ref=REV-A`): AWB `AWB1000000001`, full invoice number `FV 7/2026`.
- Client **Beta** (`client_ref=REV-B`): AWB `AWB2000000002`, **honest-null** invoice number.
- **Legacy** row (`client_ref=NULL`): AWB `AWB0000000000` — must NOT leak in a multi-client batch.
- Product origin ISO `IN` → CMR renders **India**.

**6. Reset / teardown** (removes only the isolated review storage):
```
python service/scripts/review_seed.py --storage-root C:/PZ-wt/review-940-storage --reset-review-data
```

**7. Shutdown:** `preview_stop serverId=<id>`.

## Notes
- The review API key is **generated per run** and printed to the launcher banner — never
  committed to any repo file.
- The extracted tree and review storage live under `C:/PZ-wt/` — outside the repo and every
  live storage root.
- Browser verification of #940 is a **separate** execution once this environment is confirmed.
