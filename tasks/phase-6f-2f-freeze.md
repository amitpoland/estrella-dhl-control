# Phase 6F.2.f — Freeze & Audit

> **Status:** docs-only. Closes the 6F.2 sub-campaign with a final freeze
> snapshot. No code change. No engine touch. No write surface.
> **Date:** 2026-05-16.

This document is the closing audit for Phase 6F.2 (backfill from
`proforma_service_charges` → `finance_postings.sqlite::charges`).
It records the deferred state, the namespace conventions used in production,
the operator playbook for re-running the dry-run, and the reopening criteria.

---

## 1 — 6F.2 sub-campaign closure summary

| Sub-batch | Title | Status | Evidence |
|---|---|---|---|
| 6F.2.a | Backfill engine implementation (dry-run-first) | **MERGED** | PR #117 (merge `2f67290`). 33 unit tests + 12 source-grep contracts + 7 finance-postings contracts + 27 master-data hard-rule + 12 runner-v2 + 160 PZ = full gate green. |
| 6F.2.b | Dry-run against production snapshot | **DONE** | Executed 2026-05-16T12:28:31Z against snapshot of `C:\PZ\storage\proforma_links.db`. Source rows: **0**. Report: `tasks/backfill-reports/2026-05-16-dryrun-phase-6f-2b-snapshot.json`. |
| 6F.2.c | Dry-run review + operator approval package | **MERGED** | PR #117 carried the package; PR #119 carried the decision memo. |
| 6F.2.d | Live backfill execution against production | **BLOCKED — DEFERRED** | Production has zero source rows. No data to migrate. |
| 6F.2.e | Post-backfill verification via 6F.3 breakdown endpoint | **BLOCKED — DOWNSTREAM** | Cannot verify breakdown for postings that don't exist. |
| 6F.2.f | **This document.** Freeze + audit + reopening criteria | **DONE** (this PR) | — |

The 6F.2 sub-campaign is **closed for now**. The backfill engine sits on
`main`, dormant, idempotent, and verified by 6F.1.5 dormancy contracts +
6F.2.a's own contract suite.

---

## 2 — 6F.2.a backfill engine status

- File: `service/scripts/backfill_finance_postings.py` (~410 lines)
- Tests: `service/tests/test_backfill_finance_postings.py` (33 tests, green on main)
- Default mode: `--dry-run` (live mode requires `--write` AND `--snapshot-dir`)
- Empty currency → BLOCKED (operator triage)
- Zero amount → SKIPPED (preserved for audit, never inserted)
- Idempotency keys:
  - Charges: `[backfill:sha1=<sha1("legacy_psc:<batch>:<client>:<type>")>]` in `charges.notes`
  - Postings: `BACKFILL-<sha1("legacy_psc_posting:<batch>:<client>")[:16]>` in `wfirma_invoice_id`
- Monetary safety: `Decimal(str(x)) * 100` quantized `ROUND_HALF_EVEN`; pinned by source-grep contract.
- Chunking: 100 rows / chunk; one transaction per `(batch_id, client_name)` group.

The engine has never run against production except in dry-run mode.

---

## 3 — 6F.2.b dry-run result

```jsonc
// tasks/backfill-reports/2026-05-16-dryrun-phase-6f-2b-snapshot.json
{
  "started_at":  "2026-05-16T12:28:31+00:00",
  "finished_at": "2026-05-16T12:28:31+00:00",
  "mode":        "dry-run",
  "source_db":   "C:\\PZ\\storage\\snapshots-6F2b\\proforma_links.snapshot.db",
  "target_db":   "C:\\PZ\\storage\\snapshots-6F2b\\finance_postings.dryrun.sqlite",
  "source_rows":        0,
  "eligible_rows":      0,
  "blocked_rows":       0,
  "skipped_zero":       0,
  "duplicate_skipped":  0,
  "charges_to_create":  0,
  "postings_to_create": 0,
  "blocked_reasons":    {},
  "blocked_examples":   [],
  "synthetic_postings": []
}
```

**Production probe of `proforma_service_charges`:** table exists in
`C:\PZ\storage\proforma_links.db` (217088 bytes, mtime 2026-05-15 12:21).
It contains **zero rows**. The legacy table was created by the proforma
editor schema, but no operator-entered freight/insurance charge has been
recorded against any batch in production to date.

Implication: a live backfill executed today would be a no-op. There is
literally nothing to migrate.

---

## 4 — 6F.2.c approval package summary

- File: `tasks/phase-6f-2c-operator-approval-package.md` (10 sections, on main)
- Documents: counters, zero-row finding, exact PowerShell live command (prepared but NOT run), §5 snapshot plan, §6 two-path rollback (SQL delete + snapshot restore), §7 hard-rule re-check, §10 operator approval block.
- Status: produced and reviewed. The operator has elected NOT to sign §10 because the live run would be a no-op.

---

## 5 — 6F.2.d live backfill deferred reason

Block reason recorded in `tasks/campaign-state.json`:

> "Live backfill deferred: production proforma_service_charges has 0
> source rows. Re-run dry-run when rows exist or after legacy source
> location audit."

Why this is the right call:

1. **Nothing to migrate.** Running the backfill against an empty table
   produces no rows in `finance_postings.sqlite`. The exercise is
   instrumentation-only.
2. **No data lost.** The backfill is idempotent and re-runnable. When
   production starts accumulating `proforma_service_charges` rows, the
   operator can re-run the 6F.2.b dry-run (see §8), confirm counts, and
   then re-evaluate live execution.
3. **Snapshot discipline preserved.** The §5 snapshot plan and §6
   rollback plan in the approval package remain valid for any future
   live run.
4. **The new finance store is not bypassed.** 6F.5 dual-write (PR #121,
   deployed `0f67d34`) provides the forward path for *new* charges
   recorded after activation. Backfill is for *legacy* rows only — and
   there are none.

---

## 6 — 6F.2.e blocked downstream reason

`6F.2.e` (post-backfill verification via the 6F.3 breakdown endpoint)
cannot run until `6F.2.d` produces at least one synthetic posting.
Recorded in `tasks/campaign-state.json` as:

> "Cannot verify breakdown for postings that do not exist. Blocked
> until 6F.2.d unblocks and produces at least one synthetic posting."

When `6F.2.d` reopens (per §12 reopening conditions), `6F.2.e` becomes
the natural follow-up smoke step.

---

## 7 — Three namespace conventions (live in production)

The `finance_postings.sqlite` schema (in production since PR #112,
empty since deploy) must distinguish three origin types via
disjoint prefixes and disjoint sha1 input strings. They are
guaranteed not to collide.

| Origin | `postings.wfirma_invoice_id` | `charges.notes` prefix | `charges.source` | sha1 input pattern |
|---|---|---|---|---|
| **6F.2.a backfill** | `BACKFILL-<sha1[:16]>` | `[backfill:sha1=<hex>]` | `legacy_backfill` | `legacy_psc:<batch>:<client>:<type>` (charges) · `legacy_psc_posting:<batch>:<client>` (postings) |
| **6F.5 dual-write** | `LIVE-<sha1[:16]>` | `[live:sha1=<hex>]` | `operator` | `live_psc:<batch>:<client>:<type>` (charges) · `live_psc_posting:<batch>:<client>` (postings) |
| **Real wFirma path** (future) | numeric wFirma invoice id (no prefix) | (no prefix in notes) | (other) | n/a — wFirma assigns id directly |

Disjointness proofs:
- **Prefix disjointness:** `BACKFILL-` and `LIVE-` and a numeric string are mutually exclusive on the first byte.
- **sha1 input disjointness:** `legacy_psc:...` and `live_psc:...` differ in the first 7 characters of the input string, so sha1 collision is cryptographically negligible.
- **Source-column disjointness:** `legacy_backfill` and `operator` are distinct allow-listed values in `CHARGE_SOURCES` (`service/app/services/finance_postings_db.py`).

Source-grep contracts that pin this (currently green on main):
- `service/tests/test_finance_dual_write_no_collision_with_backfill.py` (4 tests)
- `service/tests/test_dual_write_source_grep.py::test_helper_namespaces_disjoint_from_backfill`
- `service/tests/test_backfill_finance_postings.py` (the backfill side)

---

## 8 — Operator playbook: re-running the dry-run when source rows exist

When production starts accumulating `proforma_service_charges` rows (via
the existing proforma editor UPSERT endpoints), the operator can re-run
the 6F.2.b dry-run safely without any code change:

```powershell
# 1. Confirm production has source rows.
$ts = Get-Date -Format "yyyyMMddTHHmmssZ"
$snapDir = "C:\PZ\storage\snapshots-6F2b-rerun"
New-Item -ItemType Directory -Force -Path $snapDir | Out-Null

# Probe how many rows exist (read-only).
python -c "import sqlite3; c=sqlite3.connect('C:/PZ/storage/proforma_links.db'); print('rows:', c.execute('SELECT COUNT(*) FROM proforma_service_charges').fetchone()[0])"

# 2. Snapshot the legacy DB to a non-shared location.
Copy-Item "C:\PZ\storage\proforma_links.db" "$snapDir\proforma_links.snapshot-$ts.db" -Force

# 3. Run dry-run against the snapshot (NOT the live file).
cd "C:\Users\Super Fashion\PZ APP"
python service/scripts/backfill_finance_postings.py `
  --source-db "$snapDir\proforma_links.snapshot-$ts.db" `
  --target-db "$snapDir\finance_postings.dryrun-$ts.sqlite" `
  --report-path "tasks/backfill-reports/$(Get-Date -Format yyyy-MM-dd)-dryrun-phase-6f-2b-rerun.json" `
  --dry-run

# 4. Inspect the report:
Get-Content "tasks/backfill-reports/$(Get-Date -Format yyyy-MM-dd)-dryrun-phase-6f-2b-rerun.json"

# 5. If counts look right (eligible_rows > 0, blocked_rows = 0, charges_to_create > 0):
#    Produce a fresh `tasks/phase-6f-2c-operator-approval-package.md` (overwrite
#    or version-suffix the existing one) with updated counters, then proceed
#    through 6F.2.d's exact live command in §4 of THAT package.
```

The dry-run is read-only against the legacy DB. It does NOT touch
production `finance_postings.sqlite` (it writes to a snapshot target).
It is safe to run at any time without operator approval — only the live
execution is gated.

---

## 9 — Snapshot requirements before any future write

Both write-bearing paths (6F.2.d backfill, 6F.5 live activation) must
snapshot before persisting. The snapshot rule is uniform:

| Source | Snapshot before | Snapshot dir convention | Verified by |
|---|---|---|---|
| 6F.2.d backfill | The backfill script's `--snapshot-dir` flag (mandatory in `--write` mode) | `C:\PZ\storage\snapshots-6F2d-<UTC>` | `take_snapshot()` in `backfill_finance_postings.py`; non-null `snapshot` field in the live report |
| 6F.5 shadow activation | Pre-activation `Copy-Item` step from approval-package §12 | `C:\PZ\storage\snapshots-6F5-shadow` | Operator-driven; documented in `tasks/phase-6f-5-shadow-activation-approval.md` §12 |
| 6F.5 live activation (future) | TBD when `tasks/phase-6f-5-live-activation-approval.md` is authored | `C:\PZ\storage\snapshots-6F5-live` | Future approval doc |

The snapshot rule applies regardless of expected row count. Even a
no-op live backfill produces a snapshot file (the script writes an
empty marker if the target DB doesn't yet exist) so the report's
`snapshot` field is always non-null.

---

## 10 — Rollback options

| Path | Used when | Cost | Reversibility |
|---|---|---|---|
| **6F.2.a backfill rollback — Path A (SQL)** | Live backfill produced unwanted rows | seconds | full |
| `DELETE FROM charges WHERE source='legacy_backfill';` | | | |
| `DELETE FROM postings WHERE wfirma_invoice_id LIKE 'BACKFILL-%';` | | | |
| **6F.2.a backfill rollback — Path B (snapshot restore)** | Path A produces unexpected counts (e.g. concurrent posting/settlement writes raced) | minutes (service stop, copy, restart) | full |
| **6F.5 dual-write rollback — Path A (flag flip)** | Operator wants to disable activation | 30 seconds | full |
| Clear `FINANCE_DUAL_WRITE_*` from NSSM `AppEnvironmentExtra`; restart PZService | | | |
| **6F.5 dual-write rollback — Path B (SQL)** | Live rows already written and need purging | seconds | full |
| `DELETE FROM charges WHERE notes LIKE '[live:sha1=%';` | | | |
| `DELETE FROM postings WHERE wfirma_invoice_id LIKE 'LIVE-%';` | | | |
| **6F.5 dual-write rollback — Path C (code revert)** | Path A and B insufficient | full deploy cycle | full |
| `git revert -m 1 0f67d34 --no-edit` + robocopy + restart | | | |

The legacy `proforma_service_charges` table is never mutated by any of
the above paths. It is, and remains, the legacy system of record.

---

## 11 — Hard-rule status

All hard rules from `tasks/proforma_invoice_charge_hard_rules.md` (and the
14 hard rules from MDC-2026-05 final audit) remain enforced and re-verified:

| Rule | Status | Evidence on main |
|---|---|---|
| No wFirma live posting added | ✅ | No new POSTs to wFirma in P6F campaign |
| No proforma posting/approval mutation | ✅ | 6F.5 hook is post-`mark_post_succeeded`, never inside the path; source-grep contract `test_hook_fires_after_mark_post_succeeded` |
| No PZ/customs/DHL calculation change | ✅ | PZ regression 160/160 verified ≥ 8 times this session |
| No `.env` changes | ✅ | `git diff` confirms; flags read via Pydantic Settings with `Field(default=False, env=...)` |
| No direct production DB/storage edits | ✅ | All deploys via robocopy + restart; backfill is dry-run-only |
| No destructive schema operation | ✅ | Phase 6F is additive-only; 6F.7 deprecation is `planned`, not started |
| No fake backend data | ✅ | 6F.5 helper uses real `finance_postings_db.create_charge` / `create_posting` (Lesson A) |
| External integrations stay read-only | ✅ | 6F.4 panel calls only `GET /api/v1/finance/postings/{id}/breakdown`; ledger aggregator reads-only |
| Backend-pending buttons disabled with clear reason | ✅ | 6F.4 panel has explicit Read-only badge + empty-state copy |
| Preserve existing working behaviour | ✅ | /post response shape unchanged (pinned by `test_dual_write_source_grep.py`) |
| Credentials never stored in master data | ✅ | B9 secret-shape guard intact |
| VAT does NOT override wFirma invoice path | ✅ | Hard-rule contract test green |
| FX does NOT override PZ engine | ✅ | Source-grep guard + B8 guard green |
| Carrier runtime not touched | ✅ | B9 isolation guard green |
| Default-OFF feature flags (6F.5) | ✅ | Verified at 4 sources on 2026-05-16T13:42Z |

---

## 12 — Recommended reopening conditions

Reopen `6F.2.d` (live backfill) when ALL of the following are true:

1. **Source data exists.** Production `proforma_service_charges` has
   ≥ 1 row. Verified via the read-only probe in §8 step 1.
2. **Fresh dry-run.** A new dry-run report (§8 step 3) shows
   `eligible_rows > 0` AND `blocked_rows == 0`.
3. **Operator approval.** A new operator approval package (or an
   updated §10 sign-off on the existing one) explicitly authorises the
   live run.
4. **Snapshot directory prepared.** The `--snapshot-dir` location
   exists on the deploy host and has free disk space ≥ 2× the size of
   the legacy DB.
5. **No active deploy.** PZService is in steady-state; no PR is in the
   middle of a 7-agent deploy gate.
6. **Carrier gate `pending`.** No active carrier write campaign is in
   flight on the same machine.

When all 6 are true, the operator runs the exact PowerShell block in
§4 of `tasks/phase-6f-2c-operator-approval-package.md`, captures the
live report, marks `6F.2.d` `smoked`, and proceeds to `6F.2.e`
(verification via the 6F.3 breakdown endpoint).

Reopen `6F.2.e` automatically when `6F.2.d` produces ≥ 1 synthetic
posting. The verification is read-only: hit
`GET /api/v1/finance/postings/{id}/breakdown` for each new synthetic
posting id and confirm the charges array matches the legacy source
counts.

---

## 13 — Closing statement

Phase 6F.2 is frozen in a clean state:

- Engine on `main`, dormant, idempotent.
- Approval package on `main`.
- Decision memo on `main`.
- One dry-run executed and reported.
- Zero live writes performed.
- Three namespace conventions documented and enforced by contract tests.
- Production behaviour bit-identical to pre-Phase-6F.

The next safe write-bearing batch is **6F.5-shadow-activation** (separate
gate), not 6F.2.d. 6F.5 is for *new* charges entered after operator
activation; 6F.2.d is for *historical* charges that don't yet exist.
The two batches are independent — neither blocks the other.

Phase 6F.2 sub-campaign: **CLOSED PENDING REOPENING CONDITIONS §12**.
