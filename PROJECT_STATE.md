# PROJECT_STATE.md — Execution Control Surface

> **Single source of truth for *current execution state*.** What is done, what is
> moving, what is blocked, what is next. Update this file in the SAME PR as any
> work that changes execution state. If a state change is not recorded here, it
> did not happen (see `tasks/lessons.md`).

## Authority relationship (read before editing)

This repo intentionally runs **two** state files with different cadences — they do
**not** duplicate each other:

| File | Role | Cadence | Owner |
|---|---|---|---|
| **`PROJECT_STATE.md`** (this file) | Lean execution control surface — current slice, blockers, next step, evidence contract | Updated every PR that changes execution state | Whoever ships the slice |
| **`.claude/memory/PROJECT_STATE.md`** | Append-only historical governance ledger — FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS, full PR history | Append-only; never demote a FACT | `flow-context-keeper` (CLAUDE.md RULES 1/3/6) |

**Rule to avoid duplicate authority:** the memory ledger is authoritative for
*historical facts and decisions*; this file is authoritative for *what is active
right now*. Every entry below cites the memory ledger, a PR, or runtime evidence —
it never invents state. When in doubt about history, the memory ledger wins; when
in doubt about "what is the current slice," this file wins.

Execution rules: `docs/EXECUTION_PROTOCOL.md`. Per-task template: `tasks/todo.md`.
Permanent rules: `tasks/lessons.md`. PR closure contract: `.github/pull_request_template.md`.

---

## Completed

- **Lean execution workflow** (2026-06-14, this slice) — created the repo-owned
  execution control surface and rules so future work cannot restart solved problems,
  lose decisions, or close without evidence. **Added:** this `PROJECT_STATE.md`,
  `docs/EXECUTION_PROTOCOL.md` (7-rule protocol + closure gate),
  `.github/pull_request_template.md` (closure contract), `tasks/todo.md` workflow
  template, `tasks/lessons.md` permanent rules L-EXEC-1..6. **Why:** chat memory is
  lossy across sessions; the repo is not. **Scope:** docs/process only — zero product
  logic, no sensitive-system writes. Open disagreement: dual PROJECT_STATE files (see
  below). Next slice: 2026-06-20 Campaign 03 readiness re-review.
- **Authority train Deploy #1** (2026-06-13) — 4 authority modules consolidated and
  deployed, flags OFF: `name_normalization.py` (#578 lineage), `dhl_followup_authority.py`
  (#578), `tracking_db.py` (#579), `awb_address_authority.py` (#580). Evidence: LF-normalized
  deployed hashes match `authority_manifest_pinned.json` pins (`815111e4…`, `adb94aec…`,
  `429fd3d8…`, `0e7a60e3…`).
- **Authority train Deploy #2** (`f36bef4`, 2026-06-13 15:39) — runtime drift layer
  (`authority_drift_service.py`, `authority_startup.py`) deployed 15:41, `authority_drift_detection=False`.
  Startup log 15:44:51: `STARTUP_AUTHORITY_AUDIT: authority_drift_detection=False, no manifest generated`.
- **PR #582** — debug-health endpoint 500s hotfix (`health-full` UnboundLocalError +
  `storage/health` lazy-import race). **Squash-merged to main `6665597`** (2026-06-13).
  Classification: stabilization-safe / no authority-window reset. Memory ledger line 58.
- **PR #563** — non-ASCII `X-API-Key` auth 500→401 fix, deployed (`ff1f4b5`).

## In Progress

- **Authority stabilization window** — OPENED 2026-06-13 (Deploy #1). Closing trigger:
  **≥7 calendar days (target checkpoint 2026-06-20) OR ≥100 production shipments**,
  whichever the operator elects. Status as of last review: ~0 days elapsed, <100 shipments,
  0 authority incidents, 0 drift events, 0 rollbacks. Window definition:
  `service/docs/campaign-02-75/stabilization-package.md`.

## Blocked

- **Campaign 03** — `NO-GO / BLOCKED`. Hard blocker: stabilization window not yet
  satisfied (see In Progress). Unblocks ONLY on (a) 2026-06-20 checkpoint reached +
  fresh readiness review, OR (b) ≥100 shipments + fresh readiness review. Not blocked by
  any technical defect in the authority train.
- **PR #582 deployment** — merged to main, intentionally NOT deployed. Production stays
  `f36bef4`; the two debug-probe 500s remain visible in the System Health panel until a
  separate operator-gated `/deploy`. Deploying #582 does NOT advance the stabilization clock.

## Next

- **2026-06-20** — re-run Campaign 03 readiness review (the independent release-board
  format). Re-verify production identity, authority hashes (LF-normalized), drift posture,
  shipment volume, and operator-facing surfaces. Decide GO / NO-GO from fresh evidence.

## Open Disagreements

- **Dual PROJECT_STATE files.** This task created a repo-root `PROJECT_STATE.md`
  (execution surface) while the governance-mandated `.claude/memory/PROJECT_STATE.md`
  (append-only ledger) already exists. Recommendation: **keep both** — they serve
  different cadences and the "Authority relationship" table above prevents drift.
  Operator to confirm, or direct a consolidation. *Status: documented, awaiting operator
  ruling. Not blocking.*
- **#582 deploy timing.** Deploy now to clear System Health 500s, or hold to the
  2026-06-20 checkpoint to maximize change-freeze during stabilization. Operator decision.
  *Status: open, LOW urgency (debug probes only; non-authority, non-workflow, non-financial).*

## Last Verified Deploy

| Field | Value |
|---|---|
| Production SHA | **`f36bef4`** (robocopy deploy; `C:\PZ` is not a git tree — identity confirmed by deployed-file evidence, not git) |
| main SHA | `6665597` (1 commit ahead: #582, merged not deployed) |
| Authority layer | PASS — 4 modules LF-hash-match the pinned manifest |
| Drift layer | PASS — deployed, `authority_drift_detection=False` (inert by design until flag ON) |
| Service | `PZService` Running; clean startup; no manifest mismatch; no drift alert |
| Known production exceptions | 2 — `/api/v1/debug/health-full` + `/api/v1/debug/storage/health` 500 (fixed in #582, undeployed). Non-authority, non-workflow, non-financial. |
| Production risk | LOW |
| Verified | 2026-06-13 via LF-normalized hash check + live service logs |

## Required Evidence Format

No slice may be marked **Completed** here without all of the following, pasted or
linked in its PR (see `.github/pull_request_template.md`):

1. **Authority owner** — the single system that owns the truth being changed, named
   before code was written.
2. **Frozen acceptance criteria** — the criteria as agreed BEFORE implementation
   (not back-filled to match what was built).
3. **Tests** — command(s) run + pass/fail counts vs the documented baseline
   (PZ regression, carrier suite, or targeted suite). Failures stated honestly.
4. **Browser/API verification** — for UI: page loads + console + network evidence.
   For backend-only/admin: curl + audit-log evidence. State "N/A — no surface" only
   when literally true.
5. **Rollback path** — the exact command/SHA to revert this slice.
6. **PROJECT_STATE.md update** — this file moved the slice to its correct section.
7. **Sensitive-system impact** — explicit declaration if the slice touches financial /
   customs / inventory / DHL / wFirma / accounting / production-write logic (and proof
   of operator approval if so).

Three-state verification semantics (from CLAUDE.md): `True`=verified, `False`=confirmed
mismatch (escalate), `None`=could not verify (`[VERIFY-GAP]`, not a failure).
