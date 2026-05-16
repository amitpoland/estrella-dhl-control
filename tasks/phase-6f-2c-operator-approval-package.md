# Phase 6F.2.c — Operator Approval Package

> Required reading before approving the live backfill (6F.2.d).
> Generated 2026-05-16 from the 6F.2.b dry-run against a copy of production
> `C:\PZ\storage\proforma_links.db`.

---

## 1 — Summary at a glance

| Metric | Value |
|---|---|
| Mode | dry-run |
| Source DB | `C:\PZ\storage\snapshots-6F2b\proforma_links.snapshot.db` (copy of prod) |
| Source rows in `proforma_service_charges` | **0** |
| Eligible rows | 0 |
| Blocked rows | 0 |
| Skipped (zero amount) | 0 |
| Duplicate / idempotent-skip | 0 |
| Charges to create | 0 |
| Synthetic postings to create | 0 |
| Blocked reasons | (none) |
| Report file | `tasks/backfill-reports/2026-05-16-dryrun-phase-6f-2b-snapshot.json` |

---

## 2 — Unexpected but valid finding: production has no legacy rows yet

The legacy `proforma_service_charges` table exists in the production
`proforma_links.db` (217088 bytes, mtime 2026-05-15 12:21) but currently
contains **zero rows**. The new `finance_postings.sqlite` was created by
6F.3 deploy and is also empty (0 charges, 0 postings).

What this means:

- Today, a live backfill would be a no-op (nothing to write).
- The new schema is dormant in production exactly as designed (no posting/settlement engine wired).
- The backfill script has been exercised end-to-end against a real prod file shape — it correctly read the schema, classified zero rows, and produced a valid report.

Operator decision implied by this state:

- **Option 1 — Approve a no-op live run now** to lock in the backfill mechanism as a baseline, with a snapshot taken. Future operator-entered charges then get written via 6F.5 dual-write (when shipped). The baseline run produces a real `snapshot` file and a `mode: live` report with all counters zero.
- **Option 2 — Defer 6F.2.d** until operator-entered freight/insurance has actually accumulated in `proforma_service_charges`. Re-run 6F.2.b dry-run then.
- **Option 3 — Audit legacy data location** before deciding. If the operator believes freight/insurance was being captured elsewhere (a different DB file, a flat file, manual journals), 6F.2.d should be paused until that source is reconciled.

---

## 3 — What 6F.2.d would do *if* legacy rows existed

For every eligible legacy row in `proforma_service_charges`:

1. Insert one row into `finance_postings.sqlite::charges` with:
   - `source = 'legacy_backfill'`
   - `notes = '[backfill:sha1=<hash>]\n<original note>'` where `<hash>` is `sha1("legacy_psc:<batch_id>:<client_name>:<charge_type>")`
   - Monetary amount via `Decimal((amount * 100).quantize(ROUND_HALF_EVEN))` (no float arithmetic).
2. For each `(batch_id, client_name)` group, insert one synthetic posting:
   - `postings.wfirma_invoice_id = 'BACKFILL-<sha1[:16]>'` where the hash is `sha1("legacy_psc_posting:<batch_id>:<client_name>")`.
3. Commit per group (atomic charges + posting). Across groups, each group commits independently.
4. Re-runs are idempotent: existing `[backfill:sha1=...]` notes and `BACKFILL-...` posting IDs are detected and skipped.

Rows that would be classified as `blocked` (held back for operator triage) on a non-empty dataset:

- empty currency
- non-ISO-4217 currency code
- unknown charge_type (not `freight` or `insurance`)
- empty `batch_id` or `client_name`
- amount fails `Decimal` parse

Rows that would be classified as `skipped_zero`:

- `amount == 0` after Decimal coercion (preserved for audit, never written)

None of these surfaced in the current dry-run because the source had 0 rows.

---

## 4 — Exact live command (prepared but NOT run)

```powershell
# 1. Take a snapshot directory operator can name freely.
$ts = Get-Date -Format "yyyyMMddTHHmmssZ"
$snap = "C:\PZ\storage\snapshots-6F2d-$ts"
New-Item -ItemType Directory -Path $snap -Force | Out-Null

# 2. Run the backfill against the real production finance_postings.sqlite.
python service/scripts/backfill_finance_postings.py `
  --source-db "C:\PZ\storage\proforma_links.db" `
  --target-db "C:\PZ\storage\finance_postings.sqlite" `
  --report-path "tasks/backfill-reports/2026-05-16-live-phase-6f-2d.json" `
  --write `
  --snapshot-dir $snap `
  --chunk-size 100
```

Do NOT run this command until the operator has:

1. Read this package end-to-end.
2. Confirmed the production legacy data location is correct (or accepts the no-op baseline behaviour).
3. Confirmed no posting/settlement/FX/wFirma engine work is in flight that would race the backfill.
4. Confirmed PZService stability (carrier gate pending, no active deploys in the next 30 minutes).
5. Written explicit approval in the campaign tracker.

The script exits non-zero (code 1) if any row is blocked, so the live run
will fail-loud rather than partially apply. It exits with code 2 on any
unexpected exception. Exit 0 means success or eligible-but-zero work done.

---

## 5 — Snapshot plan

- The live command creates `C:\PZ\storage\snapshots-6F2d-<UTC-timestamp>\` before any writes.
- Inside that directory, the script writes:
  - `finance_postings.pre-6F2.<UTC-timestamp>.sqlite` — `shutil.copy2()` of the target DB before the first INSERT.
  - If the target DB does not yet exist on disk, the script writes an empty marker file at the snapshot path so the report's `snapshot` field is non-null.
- The snapshot path is recorded verbatim in the live report's `snapshot` field. Rule (per `tasks/backfill-reports/README.md`): a `mode: live` report with `snapshot == null` is a contract failure — investigate immediately.

---

## 6 — Rollback plan

Two independent rollback paths, either of which fully reverses the backfill:

### Path A — Targeted SQL deletes (idempotent, surgical)

```sql
-- finance_postings.sqlite
DELETE FROM charges  WHERE source = 'legacy_backfill';
DELETE FROM postings WHERE wfirma_invoice_id LIKE 'BACKFILL-%';
```

Both predicates are exact: the backfill is the only writer of `source='legacy_backfill'` charges and the only writer of `BACKFILL-`-prefixed synthetic posting IDs (the wFirma path uses real invoice IDs and never the `BACKFILL-` prefix).

### Path B — Snapshot restore

```powershell
Stop-Service PZService    # only if a process holds the DB open
Copy-Item -Force `
  "C:\PZ\storage\snapshots-6F2d-<UTC>\finance_postings.pre-6F2.<UTC>.sqlite" `
  "C:\PZ\storage\finance_postings.sqlite"
Start-Service PZService
```

Use Path A by default. Reserve Path B for the case where Path A returns
unexpected row counts (e.g. concurrent posting/settlement writes hit the
DB between backfill and rollback).

The legacy `proforma_service_charges` table is **never** mutated by the
backfill (read-only). No rollback step is needed on the legacy side.

---

## 7 — Hard-rule re-check (from `proforma_invoice_charge_hard_rules.md`)

| Rule | Backfill behaviour | Verified by |
|---|---|---|
| No live wFirma write | Backfill only reads source DB and writes local sqlite | Manual + source-grep contract test |
| No posting / settlement / FX engine touch | Backfill is a standalone CLI script; no engine imports | `test_finance_postings_contracts.py::test_6F1_no_existing_module_imports_finance_postings` |
| No legacy table mutation | Source-grep contract: no `UPDATE/DELETE/INSERT` against `proforma_service_charges` | `test_backfill_finance_postings.py::test_source_grep_no_legacy_table_writes` |
| Default mode is read-only | argparse requires `--dry-run` XOR `--write`; `--write` requires `--snapshot-dir` | `test_backfill_finance_postings.py::test_cli_requires_one_mode`, `test_live_requires_snapshot_dir` |
| Idempotent re-runs | sha1 key in `charges.notes` + sha1 key in `postings.wfirma_invoice_id`; tests cover round-trips | `test_backfill_finance_postings.py::test_live_idempotent_rerun` |
| Monetary safety (no float * 100) | `Decimal((d * 100).quantize(ROUND_HALF_EVEN))` everywhere | `test_backfill_finance_postings.py::test_decimal_amount_minor_safety`, `test_source_grep_decimal_usage` |

All checks pass on PR #117.

---

## 8 — Test evidence

| Suite | Result | Source |
|---|---|---|
| `service/tests/test_backfill_finance_postings.py` | 33/33 | PR #117 CI |
| `service/tests/test_finance_postings_contracts.py` | 7/7 (allow-list extended for backfill files) | PR #117 CI |
| `service/tests/test_finance_postings_db.py` | 38/38 | unchanged from 6F.1 |
| `service/tests/test_master_data_hard_rules.py` | 69/69 (allow-list extended for backfill files) | PR #117 CI |
| Full master-data suite | 147/147 | PR #117 CI |
| PZ regression | 160/160 | `test_pz_regression.py` |

---

## 9 — What happens after operator approval

When the operator writes explicit approval (e.g. "Approved 6F.2.d live"
in the campaign tracker), the next steps are:

1. Operator (or campaign runner with operator present) executes the exact PowerShell block in §4.
2. Capture stdout/stderr + the new `tasks/backfill-reports/2026-05-16-live-phase-6f-2d.json` file.
3. Verify the report has `mode == "live"`, `snapshot != null`, and `charges_created` / `postings_created` match the dry-run's `*_to_create` counters (or both zero if the source is still empty).
4. Commit the live report (append-only — never rewrite a prior report).
5. Mark `6F.2.d` `smoked` and proceed to `6F.2.e` (verify via 6F.3 breakdown endpoint).

---

## 10 — Approval block (operator to sign)

```
6F.2.d Live Backfill — Operator Approval

Reviewed: ___ (yes / no)
Decision: ___ (run-now / defer / audit-first)
Approved by: ____________________
Date / time:  ____________________
Notes:
```

Until this block is filled in and merged into the campaign tracker,
`6F.2.d` remains `blocked` with reason
**"Awaiting operator approval for live backfill execution."**
