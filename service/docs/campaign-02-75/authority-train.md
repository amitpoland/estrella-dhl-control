# Authority Train — single source of truth (Campaign 02.75-FINAL)

**Train = B5 → B6 → Tracking → AWB.** B7 (backup) is NOT part of the authority train but rides Deploy #1 (already merged, un-deployed). This document is the train authority; update it as each stage merges.

**Last verified:** 2026-06-13 · origin/main `65f9ea7` (post-train) · production `62810c2` · **TRAIN FULLY MERGED (#577→#578→#579→#580)**.

---

## 1. Merge order (operator-only merges)

| Step | Branch | PR | State | Post-squash SHA |
|---|---|---|---|---|
| 1 | `fix/c025-b5-name-normalization` | #577 | ✅ MERGED 2026-06-13 | `c3283f5` |
| 2 | `fix/c025-b6-followup-authority` | #578 | ✅ MERGED 2026-06-13 | `77bfba1` |
| 3 | `fix/c025-tracking-direction` | #579 | ✅ MERGED 2026-06-13 | `16c8d41` |
| 4 | `fix/c025-awb-address-authority` | #580 | ✅ MERGED 2026-06-13 (config union applied at rebase) | `65f9ea7` ← origin/main HEAD |

**Train complete.** All four merged in order; AWB owned the final `config.py` union (both flags + B7 backup flags preserved, diff-verified additive +3 lines). Next phase = Deploy #1 (operator-gated production sync).

## 2. Branch SHAs (pre-squash tips)

| Branch | Tip SHA | Pushed |
|---|---|---|
| B5 | `2920570` | ✓ origin == local |
| B6 | `ed92931` | ✓ |
| Tracking | `62a855d` | ✓ |
| AWB | `6d9ec3b` | ✓ |
| B7 (#574, merged) | `4c45210` | in main |
| origin/main | `1d4b712` | — |
| production | `62810c2` | C:\PZ-verify |

Post-squash merge SHAs (B5'…AWB') materialize at merge; record in `authority-sha-matrix.md` as they land.

## 3. Conflict map (verified by git merge-tree)

| Branch | config.py anchor | Conflict |
|---|---|---|
| B5 | none | clean always |
| B6 | ~L310 `dhl_followup_enabled` | clean — isolated region |
| Tracking | ~L336 `carrier_storage_root` | clean if merged **before** AWB |
| AWB | ~L336 `carrier_storage_root` | **unions with Tracking** — keep both flags |

All four merge clean against current main (merge-tree exit 0). The ONLY train conflict is AWB↔Tracking on `config.py`. No file conflict elsewhere (B5's `master_data_intelligence.py` edit and Tracking's edit are >1000 lines apart → auto-merge).

## 4. config.py union (AWB rebase resolution — Phase 3 authority)

Tracking merges first → main gains `outbound_tracking_registration_enabled`. AWB rebases → conflict at `carrier_storage_root`. **Resolution = union, both flags, this order:**

```python
    carrier_storage_root: Optional[Path] = Field(default=None)

    # Outbound tracking registration — records outbound shipment events to tracking_db
    outbound_tracking_registration_enabled: bool = Field(default=False)

    # AWB address authority repair (Campaign 02.5) — gate the Customer Master authority
    # derivation behind this flag. Default False = raw recipient_address behavior unchanged.
    awb_address_authority_enabled: bool = Field(default=False)

    # ── Cliq bot batch collection ──────────────────────────────────────────────
```

**Verify post-rebase:** `git diff main -- service/app/core/config.py` shows BOTH flags added, plus B7's backup flags preserved, nothing removed. Confirm Carrier 420 still green after rebase.

## 5. Rollback map

| Stage | Rollback |
|---|---|
| Any single authority | revert its squash commit (no schema, no migration) |
| Whole train (pre-deploy) | nothing in production yet — just don't deploy |
| Post-Deploy #1 | re-sync `C:\PZ\app` from `62810c2` + PYCACHE purge + restart PZService |
| Neutralize without revert | all flags default OFF — authority code is inert |

## 6. Deploy map (Lesson J)

- `service/app/** → C:\PZ\app\**` (standard robocopy) covers ALL train code (services, api routes, core/config.py, main.py).
- Out-of-app: `service/scripts/extract_name_corpus.py` (B5), `service/scripts/awb_resolution_audit.py` (AWB) — dev-only, not imported by app, **not deployed**. No extra sync.
- No repo-root engine files in this train.

## 7. Test evidence (orchestrator, independent, isolated single-process)

| Stage | Unit/Authority | Integration/Workflow | Regression | Idempotency | Result |
|---|---|---|---|---|---|
| B5 | parity suite green | delegate parity (real fns) | PZ 221+1known | n/a (pure fn) | GREEN |
| B6 | 13 (incl. flag-ON projector) | projector injection path | PZ 221+1known | additive projection | GREEN |
| Tracking | 22 (direction/dedup/registration) | coordinator→authority | Carrier 412 · PZ 221+1known | dedup idempotent (in suite) | GREEN |
| AWB | 32 (derivation + route ON/OFF) | carrier route flag paths | Carrier 420 · PZ 221+1known | flag-gated route | GREEN |

1 known failure throughout = `test_pz_batch.py::test_save_json_csv_ui_round_trip` (documented baseline).

## 8. Readiness state

| Stage | Branch health | Tests | Conflict | Rollback | Merge-ready |
|---|---|---|---|---|---|
| B5 | pushed, clean | GREEN | none | revert | **YES — PR #577 open** |
| B6 | pushed, clean | GREEN | none | revert | YES (open after #577) |
| Tracking | pushed, clean | GREEN | none vs main | revert | YES (open after B6) |
| AWB | pushed, clean | GREEN | union vs Tracking (patch ready) | revert | YES (rebase+open after Tracking) |

**Next legal action:** operator merge of #577. Train is otherwise fully prepared end-to-end.
