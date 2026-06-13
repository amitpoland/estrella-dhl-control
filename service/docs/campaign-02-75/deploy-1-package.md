# Deploy #1 Package — Authority Layer (Campaign 02.75-FINAL)

**Status:** PREPARED — awaiting merge train completion + operator deploy execution.
**Deploy type:** Git-based production sync → requires the full 7-agent gate (no exceptions).
**Production:** `C:\PZ` | Service: `PZService` (NSSM, port 47213) | Public: `https://pz.estrellajewels.eu`
**Source of truth for git/hash checks:** `C:\PZ-verify` (currently `62810c2`).

---

## 1. What Deploy #1 actually carries

Production is at `62810c2`. Current `origin/main` is `1d4b712`. Deploy #1 syncs the **post-AWB train head** to production, which carries everything from `62810c2` forward:

| Source | Content | Deploy surface |
|---|---|---|
| #574 (already merged `4c45210`, **not yet deployed**) | B7 automated backup program | `backup_service.py`, `backup_validator.py`, `routes_admin_backup.py`, `routes_debug.py`, `main.py` (router reg), `config.py` (backup flags) |
| #576 (`1d4b712`) | chore(memory) — `.claude/**` only | **not deployed** (outside robocopy) |
| B5 (#577) | name normalization authority | `services/name_normalization.py` (new) + 7 delegate hosts |
| B6 | DHL follow-up authority | `services/dhl_followup_authority.py` (new) + projector + config flag |
| Tracking | tracking direction/dedup authority | `services/tracking_db.py` (modified) + coordinator + readers + config flag |
| AWB | AWB address authority | `services/awb_address_authority.py` (new) + `routes_carrier_actions.py` + config flag |

**Disclosure:** Deploy #1 is NOT authority-only. It also lands the **B7 backup program** (merged but never deployed). The 7-agent gate MUST review the B7 surface (`backup_service.py`, `backup_validator.py`, `routes_admin_backup.py`, `main.py`) as part of this deploy, not just the authority modules.

## 2. Behavior-change profile

All four authority modules are **flag-gated, default OFF**:

| Flag | Default | Effect when OFF |
|---|---|---|
| `dhl_followup_authority_advisory` | False | projector output byte-identical to today |
| `outbound_tracking_registration_enabled` | False | no outbound event registration write |
| `awb_address_authority_enabled` | False | raw `recipient_address` behavior unchanged |
| (B5 name_normalization) | n/a — pure refactor, parity-pinned | delegates produce identical output |

**Net:** Deploy #1 is a **zero-behavior-change deploy for the authority layer** (all flags OFF; B5 is parity-preserving). The only new *active* behavior is the B7 backup program from #574 (review its default-on/off posture in the gate).

## 3. Merge order + SHA sequence (operator-only merges)

```
1d4b712 (current main)
  → merge #577 (B5)         → main' = <SHA-B5>
  → open + merge B6         → main'' = <SHA-B6>
  → open + merge Tracking   → main''' = <SHA-TRK>
  → rebase AWB onto main''' (config.py union) → open + merge AWB → main'''' = <SHA-AWB>   ← Deploy #1 target
```

SHAs are squash-merge commits; they materialize at merge time. Record each in PROJECT_STATE FACTS as it lands.

## 4. Required sync paths (Lesson J)

- Standard robocopy: `service/app/** → C:\PZ\app\**` — covers ALL deployable changes in this train (authority modules in `app/services/`, `app/api/` routes, `app/core/config.py`, `app/main.py`).
- **No extra engine sync required.** The only out-of-`app` files are dev scripts — `service/scripts/extract_name_corpus.py` (B5) and `service/scripts/awb_resolution_audit.py` (AWB) — neither imported by `service/app` (grep-verified), neither deployed. No repo-root engine files in this train (Lesson J root-engine case N/A).
- `.claude/**` (from #576) not deployed.

## 5. Pre-restart hygiene

- PYCACHE purge before `C:\PZ` restart (remove `__pycache__` under `C:\PZ\app`) — prevents stale-bytecode skew.
- Confirm `.env` carries no new required keys (all 4 authority flags default OFF in code → no `.env` entry needed to deploy safely).

## 6. Rollback points

- Pre-deploy production SHA: `62810c2` (current `C:\PZ-verify`). Rollback = re-sync `C:\PZ\app` from `62810c2` + restart `PZService`.
- Each authority is independently revertable (squash revert; no schema/migration).
- Fastest neutralize without redeploy: leave all flags OFF (already the default) — the authority code is inert.
- Exact rollback command is produced by `deploy_release_manager` against the specific Deploy #1 SHA at gate time.

## 7. 7-agent gate (run in parallel before any sync — operator triggers `/deploy`)

1. `deploy_lead_coordinator` — final go/no-go
2. `deploy_git_diff_reviewer` — file classification, forbidden paths (expect: B7 + 4 authority modules + config union)
3. `deploy_backend_impact_reviewer` — routes, auth, imports (B7 `routes_admin_backup` router reg in main.py; carrier route change in AWB)
4. `deploy_persistence_storage_reviewer` — schema, storage writes (tracking_db registration write path; backup_service writes)
5. `deploy_security_reviewer` — credentials, auth removal, injection (B7 admin API auth guard)
6. `deploy_qa_reviewer` — test pass/fail vs baseline (PZ 221+1known, Carrier 420)
7. `deploy_release_manager` — branch hygiene, rollback command

**Gate baseline (test-baseline.md):** PZ `tests/test_pz_*.py` = 221 (+1 known fail `test_save_json_csv_ui_round_trip`); Carrier `tests/test_carrier_*.py` = 420 post-AWB (412 + 8 new). Any ERROR or below-count = unconditional block.

## 8. Smoke plan (post-deploy)

### 8a. Authority smoke (disk + import, flags OFF)
- Disk presence (Select-String, NOT python-import — Lesson J): confirm 4 modules exist under `C:\PZ\app\services\` with manifest SHAs:
  - `name_normalization.py` 815111e4… · `dhl_followup_authority.py` adb94aec… · `awb_address_authority.py` 0e7a60e3… · `tracking_db.py` 429fd3d8…
- `GET /health` (or service status) 200; service starts with all flags OFF (no crash on import of new modules).
- Confirm flags read OFF at runtime (admin/debug echo or config introspection).

### 8b. Workflow smoke (zero-change confirmation, flags OFF)
- Run one real PZ batch through `/api/v1/pz/process` (no `post_to_cliq`) → totals/notes identical to pre-deploy (B5 parity).
- Confirm DHL follow-up projector output unchanged (B6 flag OFF).
- Confirm an outbound carrier action produces the same AWB recipient block as before (AWB flag OFF).
- Confirm no outbound tracking registration row is written (Tracking flag OFF).

### 8c. Browser smoke (GATE 6) — backend-only train
- Authority modules have **no UI surface** in Deploy #1 (all flags OFF, no new operator-visible capability). GATE 6 browser verification is **N/A for the authority layer**.
- **B7 backup admin API** (from #574): curl + audit-log verification substitutes for browser (admin endpoint, no UI) — verify admin auth guard rejects unauthenticated, accepts authorized; confirm audit-log entry.

### 8d. B7 backup smoke
- `backup_service` start posture (scheduled vs manual) verified; if scheduled, confirm it does not run live-destructive ops on first tick.
- `backup_validator` runs against a real backup artifact; admin API returns validator verdict.

## 9. Go / No-Go inputs for `deploy_lead_coordinator`
- [ ] All 4 train PRs merged; origin/main = post-AWB SHA
- [ ] Post-train enforced suite green on origin/main (PZ 221+1known, Carrier 420)
- [ ] config.py union (AWB) correctly carries all flags (B7 backup + 4 authority)
- [ ] 7-agent gate: 6 reviewers PASS + lead GO
- [ ] Rollback command pinned to Deploy #1 SHA
- [ ] PYCACHE purge step in runbook
