# Infra hardening — health findings #2 + #3 (report d67d3722): build + test record

- **Date:** 2026-07-03 · backend only, zero UI, zero schema change · no deploy
- **Declared:** PROJECT_STATE DECISIONS "infra hardening per health pass
  d67d3722" (appended before any edit).

## Finding #2 — WAL + busy_timeout on the four unprotected multi-writer DBs

Each of the four flagged modules gained a `_connect(db_path)` helper following
the dhl_thread_lock idiom (dhl_thread_lock.py:126-129, cited in each
docstring), with one deliberate improvement: **busy_timeout=10000 is set
BEFORE journal_mode=WAL**, so the WAL flip itself waits out a competing
writer instead of failing. `timeout=30.0` on the connect call. All of each
module's own connect sites route through the helper:

| Module | Sites converted | Notes |
|---|---|---|
| customer_master_db.py | 9/9 | |
| proforma_invoice_link_db.py | 28 uniform + 2 `isolation_level="DEFERRED"` sites (:1200, :1971 pre-fix) | helper takes `isolation_level` (default matches sqlite3.connect's own) |
| wfirma_payment_db.py | 6/6 | |
| wfirma_contractor_poll_db.py | 5/5 | |

Post-edit each module contains exactly ONE `sqlite3.connect(` (inside
`_connect`) — pinned so a bare connect can't silently return. WAL is
persistent per file: the first production connection after deploy flips
proforma_links.db / payment_state.db / contractor_poll.db /
customer_master.sqlite from DELETE journal to WAL permanently (verified in
tests via a PLAIN pragma-less connection + header bytes 18-19 == 2/2).
The other 263 no-timeout connect sites across the codebase were deliberately
NOT touched (finding #6 — phased, later, opportunistic, per instruction).

## Finding #3 — lane-a NameError

**Fix shape: MISSING IMPORT** (the function exists — utils/io.py:57, the
canonical tmp+os.replace atomic writer). `_write_scan_status`
(routes_dhl_clearance.py:2130) called `write_json_atomic` bare while every
other call site in that file uses a local aliased import (:2038, :2874).
Every lane-a DHL auto-scan status write in production has been failing with
a swallowed NameError (live WARNING 2026-07-02 14:06). Fixed with the file's
local-import idiom + a comment citing the finding.

## Tests (service/tests/test_infra_hardening_pragmas.py, 15 tests)

- Per module (×4): init flips the FILE to WAL persistently (plain
  connection sees 'wal'; header bytes 2/2) · `_connect` returns
  busy_timeout=10000 + wal · drop-can't-return pin (exactly one
  sqlite3.connect, with timeout=30.0).
- proforma_link DEFERRED isolation preserved through the helper.
- NameError regression: `_write_scan_status` writes the status JSON with no
  warning, content round-trips, no temp-file residue (atomic) — plus a
  source pin that the import stays inside the function.
- One test-only iteration during the build: the "no residue" assertion
  initially counted side-effect DIRECTORIES other modules create under
  storage_root (dsk_outputs/ etc.); narrowed to files only.

## Gates

```
tests/test_infra_hardening_pragmas.py               15 passed
Touched-module suites, standalone:
  wfirma_phase2a1 + phase3b_api + phase3b_contractor_poll +
  phase4_payment_sync                                99 passed
Combined 12-suite run (customer_master×3, contractor_at_birth,
  dhl_auto_scan, wfirma_webhook, 6 phase suites):    332 passed, 4 failed
  TRIAGE: identical 4 failures reproduce at HEAD with the delta stashed
  (test_customer_master_resolver whitespace, test_dhl_auto_scan
  lane_b/config "not_in_this_pr" ×2, test_wfirma_phase2a1 scheduler tick)
  — pre-existing cross-suite interaction flakiness (all 4 PASS when their
  suites run standalone); zero caused by this slice.
PYTHONUTF8=1 python test_pz_regression.py            160/160 golden PASS
```

## Deploy notes (rides the normal gate)

- WAL flip happens at first post-deploy connection — deploy reviewer should
  expect new `-wal`/`-shm` companions beside the four DBs in C:\PZ\storage.
- Backup interplay: the B7 backup service already checkpoints WAL before
  copying (wal_checkpoint(TRUNCATE)) — compatible.
- Health finding #1 (schedule the existing backup task) remains the
  operator's action, recorded separately once confirmed running.
