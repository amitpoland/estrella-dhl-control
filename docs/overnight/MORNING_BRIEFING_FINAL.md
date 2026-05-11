# Estrella Campaign Morning Briefing

## TL;DR

- **Today's work:** open 5 PRs (Group B + Move stock), then merge 7 Group A + 4 Group B in dependency order. ~45 minutes of operator clicking; everything else is decisions.
- **Blocked on operator only:** PR opening (browser), merge decisions, migration timing for Move stock, Group B deploy timing. Nothing is blocked on technical work.
- **Estimated operator time to clear today's queue: 2–3 hours** (heavy on review/decision; light on execution).

## State of all branches

| Branch | Status | Operator action | ETA |
|---|---|---|---|
| `feat/inspection-report` @ `761c204` | OPEN-AS-PR (Group A) | review + merge (merge commit) | 5 min |
| `feat/doc-1-v2-allocation-ledger` @ `1f2112d` | OPEN-AS-PR (Group A) | review + merge | 3 min |
| `feat/doc-2-button-registry` @ `d7e4262` | OPEN-AS-PR (Group A) | review + merge | 3 min |
| `feat/doc-3-data-source-mapping` @ `e4dff18` | OPEN-AS-PR (Group A) | review + merge | 3 min |
| `feat/doc-4-failure-modes` @ `0b3de6e` | OPEN-AS-PR (Group A) | review + merge | 3 min |
| `feat/inventory-risk2-designs` @ `62e7b08` | OPEN-AS-PR (Group A) | review + merge | 2 min |
| `feat/inventory-risk34-stubs` @ `b346ff8` | OPEN-AS-PR (Group A) | review + merge | 2 min |
| `feat/inventory-state-batch-read` @ `2d57e70` | PR-BODY-READY (B.1) | open PR via `GROUP_B_PR_BODIES.md`, merge | 5 min |
| `feat/inventory-ui-shipment-state-strip` @ `12849fb` | PR-BODY-READY (B.2) | open PR, merge (depends on B.1) | 5 min |
| `feat/inventory-piece-detail-read` @ `95404ee` | PR-BODY-READY (B.3) | open PR, merge | 5 min |
| `feat/inventory-ui-piece-detail-drawer` @ `7ee9d09` | PR-BODY-READY (B.4) | open PR, merge (depends on B.3) | 5 min |
| `feat/inventory-button-move-stock` @ `50f7101` | PR-BODY-READY (Group C) | **DO NOT OPEN until Group A merged**; then `MOVE_STOCK_PR_BODY.md` | 10 min + migration |
| `feat/hybrid-auth-prep` @ `6dd485a` | OPEN-AS-PR (pre-campaign) | untouched per spec; operator decides when to PR | — |
| `feat/overnight-orchestrator-report` @ `a214c39` | pushed | optional archival — can stay un-PR'd | — |
| `feat/overnight-test-validation-report` | pushed (this commit chain) | optional archival | — |

**Status legend:**
- **OPEN-AS-PR** = operator already opened the PR on GitHub last night
- **PR-BODY-READY** = body written in `docs/overnight/`; operator pastes into GitHub UI
- **MERGED** = should be 0 entries; if any branch shows MERGED here without explicit operator action, investigate

## Today's recommended sequence

1. **(0–5 min) Pre-flight sanity check.** Confirm the 7 items in the "Pre-morning sanity check" section below.
2. **(5–25 min) Review and merge Group A PRs** (7 PRs). Merge-commit method on each. Dependency order is the same as the table above — Inspector first, then Doc 1 v2, then Doc 2 / Doc 3 / Doc 4 / Risk-2 / Risk-3-4. They touch different files; no merge conflicts expected.
3. **(25–35 min) Open Group B PRs** via the 4 bodies in `GROUP_B_PR_BODIES.md`. Paste each title + body into the URL listed.
4. **(35–55 min) Merge Group B PRs** in dependency order: B.1 → B.2 → B.3 → B.4. Merge-commit method.
5. **(55–65 min) Open Move stock PR** via `MOVE_STOCK_PR_BODY.md`. Body explicitly notes it depends on Group A being merged (already done by this point).
6. **(65–75 min) Decision: when to run the Move stock migration.** Two options:
   - (a) Now — apply migration to `C:\PZ\storage\warehouse.db` (the file-only, idempotent migration is in `service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft`).
   - (b) Hold — keep the Move stock PR open until the next deploy window.
7. **(75–105 min) Decision: when to deploy Group B + Move stock to production.** Same Path-2-style 7-agent gate (file copy → elevated PowerShell → `C:\PZ\restart.ps1` → loopback smoke → operator browser checklist).
8. **(105+ min) Optional: pick next campaign target.** See "Suggested next campaign" below.

## Hard halt log

Empty. No hard halts triggered during the final wrap-up. Working tree was clean on `main` @ `07f41ad` throughout. No PRs were merged overnight (per spec). No production was touched. No migration was applied. The Move stock branch at `50f7101` is untouched.

## Test stability summary

Total new tests added across the 11 PR-ready branches: **4** new test files (Group B reads/UI), **1** test file modified (`test_dashboard_inventory_design.py` — relaxed to allow the second user-triggered apiFetch with an explicit allowlist).

| Metric | Count |
|---|---|
| Path 2 baseline (`test_inventory_stage2_aggregate.py` + 4 UI suites) | 150/150 preserved on every Group B branch |
| Atlas composition suite (22 dashboard files) | 658/658 preserved; 674/674 on the drawer branch which added 11 + 5 |
| Pre-existing wider-repo failures (~441) | NOT re-run during the campaign — out-of-scope environment issues |
| Branches where tests fail today | none |

## Architectural decisions made this campaign

- **Extend-existing** (not greenfield ledger). `inventory_state.state` stays canonical; per-piece allocation table (`allocation_groups` + `allocation_pieces`) is DESIGN ONLY in Doc 1 v2 §5.
- **Hybrid identity model.** SKU-level `reservation_queue` retains its current purpose (price + customer + qty per SKU); per-piece identity moves into the future allocation tables.
- **Option A for idempotency** (partial UNIQUE index on `(scan_code, idempotency_key)` WHERE non-empty). Lock-free, durable, multi-process safe.
- **Single-writer discipline preserved.** All state transitions through `inventory_state_engine.transition()`. Move stock writes location metadata only, never lifecycle.
- **`inventory_state.state` stays canonical.** No parallel state store. Stage 2 aggregator reads from this column.

## What's still BLOCKED

- **Sample-out, Sample-return, Consignment flows, Goods-return, Return-to-producer** (Risk-3 and Risk-4 buttons): need allocation schema migration + new states added to `STATES` enum + (for Return-to-producer) customs SME session.
- **States that don't exist today:** `SAMPLE_OUT`, `SAMPLE_RETURNED`, `CONSIGNMENT_OUT`, `CONSIGNMENT_RETURN`, `RETURNED_*`, `QUARANTINE`, `RETURN_TO_PRODUCER`. Doc 1 v2 §3 enumerates these as PENDING.
- **Production API key cutover:** `settings.api_key` is empty in `C:\PZ\.env`. Once flipped non-empty, every `Depends(require_api_key)` route requires `X-API-Key`. The `feat/hybrid-auth-prep` branch (untouched, `6dd485a`) is the safety mechanism for the SPA — cookie auth becomes a fallback.
- **Cowork callback authentication.** Currently the Cowork agent posts to `/api/v1/tracking/{awb}/cowork-result` without an API key (works because `api_key=""`). After the cutover, the operator's MCP setup needs an `X-API-Key` injection point.
- **Cliq webhook authentication.** Same posture as Cowork. Likely needs HMAC-style verification rather than a static header.

## Suggested next campaign (operator picks; not authorized)

**Option A — Sample-out implementation** (~3–5 days).
- Prerequisite: allocation schema migration applied; new `SAMPLE_OUT` state added to `STATES` and `LEGAL_TRANSITIONS`.
- Risk: first real lifecycle-changing write on the inventory surface.
- Reuses the Move stock idempotency pattern, so cost amortizes nicely.

**Option B — Direct dispatch UI implementation** (~1–2 days).
- Wires the orphaned `POST /api/v1/lifecycle/inventory-state/mark-direct-dispatch` endpoint into the New Shipment modal.
- Lower risk: endpoint already exists, security review already happened upstream.
- Bridges the packing list flow to `inventory_state` for the direct-dispatch path.

**Option C — Hybrid auth cutover** (~1 day execution + smoke).
- Merge `feat/hybrid-auth-prep`, set `settings.api_key` in `C:\PZ\.env`, restart, smoke.
- Smallest blast-radius increase. Closes the open-API posture for all read-only endpoints in one move.
- Cowork and Cliq webhooks need their auth-injection plumbed FIRST (separate small task each).

**Recommendation:** in the operator's place, I'd do **C → B → A** in that order. Each step unblocks the next.

## Files written during this final overnight wrap-up

- `docs/overnight/TEST_VALIDATION_TABLE.md` — per-branch file impact + merge-order guidance
- `docs/overnight/GROUP_B_PR_BODIES.md` — 4 PR bodies for paste-into-browser
- `docs/overnight/MOVE_STOCK_PR_BODY.md` — held-for-Group-A-merge body + migration step
- `docs/overnight/MORNING_BRIEFING_FINAL.md` (this file) — operator's day-1 reading

## Resume hooks (for tomorrow morning's Claude Code session)

- Campaign base SHA: **`07f41ad`**
- Move stock branch SHA: **`50f7101`** (security-passed, ready to PR after Group A merges)
- All 14 feature branches pushed to origin (13 from prior phases + `feat/overnight-test-validation-report` from this final wrap-up)
- Working tree clean on `main` @ `07f41ad`
- All hard halts honored throughout the campaign — 0 production touches, 0 main commits, 0 `.env` modifications, 0 migrations applied, 0 live external API writes

## Pre-morning sanity check

Confirm these are TRUE before signing off (operator runs `bash`/`git` checks):

- [ ] `git rev-parse main` → `07f41ad...` (campaign base unchanged)
- [ ] No PRs merged overnight (check GitHub PR list)
- [ ] No production touched (`C:\PZ` last-modified times unchanged for `.py` files)
- [ ] No migration applied (`C:\PZ\storage\warehouse.db` has no `idempotency_key` column yet — verify with `sqlite3` if curious)
- [ ] No `.env` modified
- [ ] `feat/hybrid-auth-prep` still at `6dd485a` (`git rev-parse origin/feat/hybrid-auth-prep`)
- [ ] Move stock branch at `50f7101` (`git rev-parse origin/feat/inventory-button-move-stock`)

## Operator's first prompt tomorrow (suggested)

Paste this into Claude Code to resume:

```
Read docs/overnight/MORNING_BRIEFING_FINAL.md and confirm:
1. All pre-morning sanity checks pass
2. No hard halts logged
3. Working tree state
Then hold for operator direction.
```

That prompt is about 30 seconds of work. After that, operator picks the day's first action: merge Group A, open Group B, run migration, deploy, or hold.
