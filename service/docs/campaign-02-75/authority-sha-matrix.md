# Authority SHA Matrix — deployment & rollback traceability (Campaign 02.75-FINAL)

**Last verified:** 2026-06-13. **TRAIN FULLY MERGED + DEPLOY #1 + DEPLOY #2 SUCCESS** — all post-squash SHAs recorded below.

## Anchor SHAs

| Ref | SHA | Role |
|---|---|---|
| production (`C:\PZ`) | `f36bef4084f085e7118fdbd0b2f7312d9e2f1f60` | **live — DEPLOY #2 SUCCESS 2026-06-13** (audit+drift layer; drift flag OFF, endpoint gated, B7 401, hashes clean at boot) |
| rollback anchor (pre-Deploy-#2) | `65f9ea776c8abb29b607e4e2d4ef108711af08f3` | re-sync C:\PZ\app + PYCACHE purge + restart to revert Deploy #2 (authority layer only, Deploy #1 SUCCESS) |
| rollback anchor (pre-Deploy-#1) | `62810c247d88ebd628eab2bcc1df253547c58edd` | full-revert anchor to before the authority train |
| origin/main | `f36bef4084f085e7118fdbd0b2f7312d9e2f1f60` | = production (Deploy #2 deployed; PR #581 merged) |
| `C:\PZ-verify` | `f36bef4084f085e7118fdbd0b2f7312d9e2f1f60` | ff-only synced to f36bef4 |
| B7 backup (#574, merged) | `4c452100f2e2689a56885f3709023352fb2f1647` | in main since before train; deployed; `/api/v1/admin/backup/list` → 401 unauthenticated |

## Train branch tips (pre-squash → post-squash MERGED)

| Branch | PR | Pre-squash tip | Post-squash merge SHA (on main) |
|---|---|---|---|
| B5 name_normalization | #577 ✅ MERGED | `2920570` | **`c3283f5`** |
| B6 followup_authority | #578 ✅ MERGED | `ed92931` | **`77bfba1`** |
| Tracking direction | #579 ✅ MERGED | `62a855d` | **`16c8d41`** |
| AWB address_authority | #580 ✅ MERGED | `3eb7d45` (post config-union rebase) | **`65f9ea7`** ← origin/main HEAD |

**Merged-tree enforced suite @ `65f9ea7` (C:\PZ-verify, isolated single-process):** PZ `tests/test_pz_*.py` = 221 passed + 1 known fail (`test_save_json_csv_ui_round_trip`) · Carrier `tests/test_carrier_*.py` = 420 passed. GREEN.

## Authority module hash pins (`authority_manifest_pinned.json`)

| Module | SHA-256 | size |
|---|---|---|
| `name_normalization.py` | `815111e47afe59b7ab58ea164d9c7da92acda6a9a962aebf393c0339c666a1d6` | 7864 |
| `dhl_followup_authority.py` | `adb94aecd9d4ffd0f82cdacbc706c636bd612c0b0a0fba0298234b2291e60075` | 5997 |
| `awb_address_authority.py` | `0e7a60e39f4802071070c22c7e2e370afb7f499454e9cbab11f8bf96e6097b33` | 6504 |
| `tracking_db.py` | `429fd3d8f590796c6b8c09012c4319a5951d74e04687616b307d146fd81eb3df` | 10826 |

Deploy #1 smoke MUST `Select-String`/hash-verify each deployed module against these pins (Lesson J: file-content check, NOT python-import).

## Deploy #2 (audit + drift) — SUCCESS 2026-06-13

| Field | Value |
|---|---|
| PR | #581 ✅ MERGED (`Campaign 02.76 — Deploy #2: authority audit + runtime drift layer`) |
| Pre-squash branch tip | `feat/c025-authority-audit-drift` `2f12830` (C1 NFD fix) — rebased onto `65f9ea7` |
| Post-squash merge SHA | **`f36bef4084f085e7118fdbd0b2f7312d9e2f1f60`** ← origin/main HEAD = production |
| Deployed to `C:\PZ\app` | 2026-06-13 15:41 — `authority_manifest_pinned.json`, `services/authority_drift_service.py`, `services/authority_startup.py` all PRESENT |
| Drift flag | `authority_drift_detection: bool = Field(default=False)` (deployed) — OFF |
| Drift endpoint (flag OFF) | `/api/v1/admin/authority/drift` → 404 (gated) |
| Startup | `STARTUP_AUTHORITY_AUDIT: authority_drift_detection=False, no manifest generated` — R1 hook clean, no false-positive, no startup crash |
| Hash authority | all 4 modules LF-normalized hash == pins (manifest authority); CRLF on disk by design — see `project_authority_hash_eol_normalization` |
| 3-layer Completion Gate | Layer 1 GitHub ✅ · Layer 2 backend ✅ · Layer 3 browser 9/9 ✅ |

Note: the only stderr traceback at verification was the **pre-existing out-of-scope** `routes_debug.py:134` `health_full` `UnboundLocalError` (NOT in the Deploy #2 diff `65f9ea7..f36bef4`; request-time, not startup). Tracked as a separate follow-up, not a Deploy #2 regression.

## Deploy target sequence (ACHIEVED)

```
62810c2 (pre-train)
  └─ Deploy #1 → 65f9ea7 (post-train main; incl. B7)   [authority layer, flags OFF]   ✅ SUCCESS
        └─ Deploy #2 → f36bef4 (#581 audit-drift merge) [drift mechanization, R1 startup pin]  ✅ SUCCESS — LIVE
```

## Rollback quick-reference

| To undo | Target SHA | Method |
|---|---|---|
| Deploy #2 (keep Deploy #1) | `65f9ea7` | re-sync C:\PZ\app + PYCACHE purge + restart |
| Deploy #1 + #2 (full) | `62810c2` | re-sync C:\PZ\app + PYCACHE purge + restart |
| One authority | its `<X'>` | `git revert <X'>` + redeploy |
| Neutralize drift (no redeploy) | — | `authority_drift_detection` OFF (default) |
