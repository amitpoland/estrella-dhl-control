# Authority SHA Matrix — deployment & rollback traceability (Campaign 02.75-FINAL)

**Last verified:** 2026-06-13. **TRAIN FULLY MERGED** — all post-squash SHAs recorded below.

## Anchor SHAs

| Ref | SHA | Role |
|---|---|---|
| production (`C:\PZ`) | `62810c247d88ebd628eab2bcc1df253547c58edd` | live; **pre-Deploy-#1 rollback target** |
| origin/main (post-train) | `65f9ea776c8abb29b607e4e2d4ef108711af08f3` | **Deploy #1 target** (= AWB post-squash; carries all 4 authority modules + B7) |
| `C:\PZ-verify` | `65f9ea776c8abb29b607e4e2d4ef108711af08f3` | ff-only synced to post-train main; enforced suite GREEN here |
| B7 backup (#574, merged) | `4c452100f2e2689a56885f3709023352fb2f1647` | in main since before train; rides Deploy #1 (un-deployed) |

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

## Deploy #2 (audit + drift)

| Branch | Tip SHA | Carries |
|---|---|---|
| `feat/c025-authority-audit-drift` | `2f12830` (C1 NFD fix committed; **pushed to origin 2026-06-13** — `origin/feat/c025-authority-audit-drift` == `2f12830f2d8c…`) | audit_audit.py, manifest, startup R1, drift_service R2/Phase4, contract tests |

✓ Audit-drift branch is now on origin (verified `git ls-remote` == local tip). The C1 fix `2f12830` is no longer local-only; worktree cleanup is now safe with respect to this branch. PR remains unopened (Deploy #2 follows Deploy #1 + stabilization).

## Deploy target sequence

```
62810c2 (prod now)
  └─ Deploy #1 → <AWB'> (post-train main; incl. B7)   [authority layer, flags OFF]
        └─ Deploy #2 → audit-drift merge SHA          [drift mechanization, R1 startup pin]
```

## Rollback quick-reference

| To undo | Target SHA | Method |
|---|---|---|
| Deploy #1 entirely | `62810c2` | re-sync C:\PZ\app + PYCACHE purge + restart |
| One authority | its `<X'>` | `git revert <X'>` + redeploy |
| Neutralize (no redeploy) | — | all flags OFF (default) |
