## Campaign context

Phase A (highest priority) of the **Repository Integration and Authority Consolidation Campaign** (2026-07-17). Full /context inventory, authority-overlap matrix, and branch disposition ledger: `reports/campaigns/2026-07-17-repo-integration-authority-consolidation.md` (in this PR).

Fixes the confirmed production defect: **post-success draft persistence fails** — execute step 7b referenced locals scoped inside `_build_convert_candidate`, the NameError was swallowed by a non-fatal try, and the draft row kept `wfirma_invoice_id NULL` / `draft_state='posted'` while the wFirma invoice + link row existed (draft 67 fully drifted, draft 52 partially drifted; remote invoice and issued link correct; duplicate creation already blocked).

## What this PR integrates (provenance preserved via cherry-pick)

Two previously parallel local-only packages + one consolidation commit:

1. **Forward persistence** (3 commits, from `claude/competent-lehmann-d564b3`): step-7b NameError fix, `draft_persisted` disclosure on the execute response (advisory, never blocks), WAL + busy_timeout on the conversion-persistence DB, privileged auth guard (`require_api_key_privileged`).
2. **R-2 split-brain recovery** (1 commit, from `claude/admiring-saha-dc6995`): remote **identity capture before local finalization** (`record_invoice_identity`), single shared `_verify_created_invoice` authority, read-only detection GET, operator-gated reconcile POST with read-only wFirma re-verify, V2 recovery panel.
3. **Consolidation commit** (matrix A of the campaign report): ONE reconciliation authority.

## The canonical reconciliation authority (after consolidation)

- **Deleted**: `POST /draft/{draft_id}/reconcile-conversion-link` (duplicate writer). No UI referenced it; tests retargeted.
- **`POST /invoice-links/{proforma_id}/reconcile`** — the ONE repair route, `dependencies=[_auth_write]` (read-only session roles rejected), confirm token `YES_RECONCILE_INVOICE_LINK`, operator attribution. Branches on link status:
  - `issued` → **draft-projection repair** (draft 67/52 class): local link→draft copy via `persist_invoice_to_draft` (the single post-conversion draft writer). **NO wFirma call.** Idempotent noop; conflicting draft invoice id → blocked; lock contention → structured `retryable` error, never a 500.
  - `pending`/`failed` → **split-brain repair**: read-only wFirma re-fetch (`invoices/get` only, never add/edit/delete), same `_build_convert_candidate` + `_verify_created_invoice` matrix, back-reference identity guard, conflicting supplied-vs-captured id → refused. On pass: `mark_issued` + draft projection.
- **`GET /invoice-links/split-brain`** — read-only detection now covers THREE classes: `confirmed_split_brain`, `suspected_split_brain`, and new **`stale_draft_projection`** (issued link whose draft never received the invoice identity — the production-defect class was previously invisible to the report).
- **One audit model**: both branches append the single event name `invoice_link_reconciled` to audit.json (`audit_persist`) AND the draft event log; the issued branch additionally restores a missing step-8 conversion record (idempotent on batch/proforma/invoice id).

Never recreate, never delete, never edit the remote invoice. `wfirma_write: false` disclosed on every repair response.

## Post-deploy production repair plan (operator-gated — NOT part of this PR)

After merge + deploy: read-only verify via `GET /invoice-links/split-brain` (expect draft 67 and draft 52 as `stale_draft_projection`), then with explicit operator approval call the canonical reconcile route for each, capture before/after, verify Convert disabled, re-run for noop proof. No wFirma write at any step.

## Tests

- `test_convert_persist_scope_and_reconcile.py` — S1–S3 + R1–R16 (retargeted at the canonical route; adds lock-contention retryable, privileged-guard + route-deletion pin, stale-projection detection incl. disappearance-after-repair, draft-52 partial-write shape, confirm-token gate).
- `test_invoice_link_reconcile.py` — forward capture, detection classes, split-brain repair/refusal matrix, operator/confirm gates, **no-wFirma-write proof for both branches** (the old "issued → blocked" pin replaced by the issued-branch projection-repair pin with a no-wFirma-call assertion).
- Results: 59 passed (both suites + `test_audit_proforma_converted.py`); adjacent suites 102 passed + 1 pre-existing known-failing exclusion (`test_dashboard_renders_two_step_convert_flow`, Issue #927 baseline row — deleted by PR #931); root PZ regression all golden checks pass; smoke 63 passed (also enforced by the pre-commit hook on the consolidation commit).

## Review gate (GATE 1) — four verdicts, all mitigations applied

- **backend-safety-reviewer: PASS-WITH-FINDINGS** — HIGH (convert-execute routes admitted read-only session roles) → **FIXED**: both `POST /to-invoice/...` routes upgraded to `_auth_write`, allowlist updated, pinned by S4. MEDIUM (split-brain silent persist failure) → **FIXED** (`draft_persisted` + advisory on the response). LOWs fixed (retryable mark_issued error, BOM-safe audit read). INFO `_link_already_exists` broad except → **REJECTED with reasoning**: defense-in-depth only; the UNIQUE(proforma_id) constraint is the real duplicate gate, and converting DB errors to 503 here would block conversions on a transient preflight read.
- **reviewer-challenge: PASS-WITH-MITIGATIONS** — MEDIUM-1 = backend MEDIUM (fixed as above, + behavioral test); MEDIUM-2 (silent scan truncation) → **FIXED** (`truncated` + `scan_limit` in the GET response); LOW-1 multi-draft-per-proforma newest-first heuristic → docstring disclosure now + **GATE-4 follow-up** (store draft_id on the link row at mark_issued); LOW-2 healthy-issued detection exclusion → **test added**. Its "question nobody asked" (repaired draft keeps `sale_date`/`payment_due`/`payment_method` NULL) → **disclosed** as `unrestored_fields` in the repair response and in the runbook note below. Lesson N/M, authority coherence (one writer, one event, one route), and draft 67/52 repair reachability: PASS.
- **security-write-action-reviewer: PASS-WITH-FINDINGS** — F-1 (path injection via operator-supplied invoice id) → **FIXED** (`isdigit` gate before any wFirma call, test-pinned); F-2 (missing draft-conflict pre-check in split-brain branch) → **FIXED** (mirrors the issued-branch guard, fires before any wFirma fetch or link write, test-pinned); F-3 (draft event log append-only, non-idempotent) → by-design for an event log, audit.json records deduplicate.
- **test-coverage-reviewer** — both HIGHs fixed (execute-path `draft_persisted=False` behavioral test; issued-branch body-id conflict test); MEDIUMs fixed (healthy-issued exclusion, cross-branch second-call noop, audit_persist unit idempotency); LOW-6 fixed (unrecognized status blocked); S3 upgraded from substring to AST dict-key pin. LOW-7 (behavioral read-only-role 403 test) → **REJECTED with reasoning**: requires standing up the session store to mint a viewer-role cookie; the guard's role matrix is core-security scope, and S4/R15 pin the wiring. Recorded as acceptable residual.

## Pre-existing failure disclosure (RESOLVED since the original gate run)

At the original GATE-1 run (base `d5a453fd`) the 18 affected suites showed 483 passed / 32 failed, all 32 proven identical on clean `origin/main`. That cluster has since been **resolved on main**: **PR #935** (merged `be111bad`) repaired 26 of the 29 stale-suite failures and registered the remaining 3 as defect pins, and **PR #936** (merged `71a2a757`) fixed the underlying fail-open design-ambiguity readiness gate (dead since #684) and un-registered those pins. This branch was **rebased onto post-#936 main** (`71a2a757`); the only remaining tracked reds are the 2 known RBAC drift failures (task_6a5ee6b3), which are untouched here. Zero regressions from this branch (re-verified after rebase — see test results below).

**Repair-runbook note**: a projection-repaired draft keeps `sale_date`/`payment_due`/`payment_method` NULL (the link table doesn't carry them; only the forward path writes them). For draft 67 this means Finance-visible payment metadata stays empty after repair — disclosed in the response `unrestored_fields`; restoring them, if wanted, is a separate operator-approved enrichment step.

## Deploy notes

Standard `service/app` sync only — no root-engine files (Lesson J N/A). No schema change (post-conversion columns are additive and already created idempotently by both init paths — pinned by R11). No new env vars. Remember the PYCACHE clear rule. **Merge/deploy operator-only; the draft 67/52 production repair additionally requires explicit operator approval per the campaign safety gates.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
