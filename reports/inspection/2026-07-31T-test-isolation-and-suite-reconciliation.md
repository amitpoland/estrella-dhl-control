# Test isolation + suite reconciliation — 2026-07-31

**Branch:** `claude/test-isolation-stale-settings-7wtm5i`
**Scope:** the operator's five-step sequence for the red/timing-out service suite.
**Measured on:** Linux, py3.11 (this session's container). CI meters on Windows,
py3.9 — platform-conditional rows will differ, and every count below is stated
with that caveat.

---

## 1. The timeout — repaired

**Reported cause:** `test_registry_sales_line_count.py` captures `settings` at
collection via a module-level `from app.core.config import settings`, then
patches that captured object; an earlier `importlib.reload(app.core.config)`
leaves the captured reference stale, so `app.main.lifespan` keeps the previous
`storage_root` and the shared session `reservation_queue.db`, blocking inside
`con.executescript(_DDL)`.

**Verified — with one correction.** The mechanism is real and now pinned by
test. The named trigger is not: `test_compliance_resolver_injection` **no longer
reloads** `app.core.config`. Its `test_settings_object_exposes_flag` carries an
explicit comment (line 44) saying the reload was removed precisely because it
"replaces the `settings` singleton for the rest of the session". No test in
`service/tests/` reloads that module today —
`grep -rn "reload(.*config" tests/` returns only the two stale conftest comments
that still name it.

So the fixture defect was **latent, not active**: the hazard is generic (any
future reload re-arms it), which is why the repair is generic rather than
pointed at one test.

Empirically confirmed, in `tests/test_settings_singleton_isolation.py`:

- after a reload, `app.core.config.settings is not app.main.settings`;
- patching the **reloaded** object and entering the lifespan creates **no**
  databases under `tmp_path` — the patch redirects nothing (this is the defect,
  now a passing pin, so a rewrite back to the module-level-import form fails
  loudly);
- patching **`app.main.settings`** creates both `reservation_queue.db` and
  `documents.db` under `tmp_path`.

**Repairs**

| Change | Effect |
|---|---|
| `test_registry_sales_line_count.py` — fixture + `_auth()` resolve settings via `app.main`, per call | corrective: the file can no longer patch a stale object |
| `conftest.py::_pin_settings_singleton` (autouse) | preventive: restores the `app.core.config.settings` binding after every test, bounding a reload's blast radius to the test that performed it |
| `test_settings_singleton_isolation.py` (7 tests) | pins both halves + the backstop + storage-root parity |

`_pin_settings_singleton` changes **no current failure count** — nothing reloads
config today. It is a guard against the defect returning, and it is what makes
the class order-independent instead of dependent on which files ran first.

**Not changed, deliberately:** `reservation_db._connect()` has no explicit
`busy_timeout`, and the repo-wide `with _connect() as con:` idiom commits but
does not close (CPython refcounting closes it on function return, so it is not
the leak it resembles). Neither was touched — the lock contention is caused by
two lifespans sharing a root, and redirecting the root is the fix. Changing
production DB code to paper over a test-isolation bug would be the wrong repair.

---

## 2–3. Sharding + JUnit — delivered

The suite ran as one pytest process. `pytest.ini` sets
`timeout_method = thread`; pytest-timeout's thread method cannot interrupt a
blocked C call, so it terminates the process — which is why a run that died at
77% reported one timeout and discarded the standing failures in the remaining
23%.

- `.github/workflows/ci.yml` — `service-suite` is now a 6-way matrix,
  `fail-fast: false`, each shard writing JUnit XML uploaded with `if: always()`.
- `service-suite-report` aggregates all six into the run summary.
- `tools/shard_tests.py` — **SUPERSEDED 2026-08-01: now hashes, does not pack.**
  Assignment is `sha256(relative posix path) % 6`, so a file keeps its shard
  while the tree changes around it; packing re-derived membership from the whole
  listing, and one added file could move unrelated files between shards,
  invalidating run-over-run comparison. Balance is looser as a result (143–174
  files, 1759.7–2347.9 KiB per shard, vs 162–163 files and 2188.8–2188.9 KiB
  under packing — the figure this line originally recorded). Changing the shard
  count reshuffles ~84% of files and is a comparison-reset event; see
  `service/docs/ops/ci-sharded-suite.md` § Shard membership.
- `tools/junit_summary.py` — **a shard whose XML is missing or truncated is
  reported INCOMPLETE, never as zero failures.** Pinned by
  `tests/test_ci_shard_partition.py`.
- `tools/classify_failures.py` — re-runs each failing file alone and splits
  `ISOLATED_FAIL` from `ORDER_CONTAMINATION`.

**Branch protection:** the verdict is `Service pytest (aggregate)`. Shard steps
are `continue-on-error: true`, so a shard job can report success while its tests
failed — requiring one would be a green light with nothing behind it.

---

## 4. Classification — corroborates PR #1059, independently

Step 4 was already performed by a prior session and is registered in open PR
**#1059** (`.claude/contracts/test-baseline.md`): full-suite measurement of
**789 failed / 20419 passed / 80 skipped / 0 errors**, split by per-file
isolation into **70 contamination-only** (17 files 100% green alone) and **719
reproducible-in-isolation**, with four signature groups traced to source and
proven test-side.

Rather than re-derive it, each registered class was re-measured here in
isolation. **All four reproduce at exactly the registered counts:**

| Class (as registered in #1059) | Registered | Measured here | File(s) |
|---|---:|---:|---|
| `ON CONFLICT … does not match any … constraint` | 29 | **29** (5 + 24) | `test_pr2c3b_customer_master.py`, `test_pr2c3c_bulk_price_recovery.py` |
| `'S' object has no attribute 'environment'` | 7 | **7** | `test_email_sender.py` |
| `no attribute '_c1f_mirror_good_id_with_fallback'` | 6 | **6** | `test_c1f_mirror_first_reads.py` |
| `too many values to unpack (expected 3)` | 13 | 5 in `test_intake_currency_and_pnd.py` (+ peers) | `test_intake_currency_and_pnd.py` + peers |

The classification in #1059 is sound and current. Step 4 is **complete**; it did
not need redoing.

### Two additional leak findings (new — not in #1059)

An interrupted full-suite run left artifacts in the working tree that name two
isolation leaks the existing storage guard does not catch:

1. **`service/c:\pz\storage/version.json`** — a test writes the **hardcoded
   Windows production path** `C:\PZ\storage`. On Windows that targets the live
   production root; on Linux it becomes a *relative* directory under `service/`,
   which is why `conftest._guard_storage_root` misses it (the guard watches
   resolved live roots, and this path never resolves to one). Content:
   `{"commit": "x", "deployed_at": …, "channel": "gate6-review"}`.
2. **11 files named `<MagicMock name='settings.carrier_storage_root.__truediv__()' id=…>`**
   in `service/` — a test passes an unconfigured `MagicMock` where a `Path` is
   expected; `str()` of the mock becomes a literal filename. Each run leaves new
   ones (the `id=` differs), so they accumulate.

Both write **outside** any tmp_path and outside the session sandbox. Neither
fails a test today, which is exactly why they persist.

**GATE 4 disposition — SCHEDULED**, into the same stale-suite repair campaign
already registered in #1059 (target: the `channel="gate6-review"` writer and the
`carrier_storage_root` mock). Artifacts were removed from the working tree in
this session; they are regenerated by any full-suite run until the writers are
fixed.

---

## 5. Repair — done on a separate branch

Not on this branch: it is a different class of work, and folding it in would turn
a test-isolation PR into an unrelated 9-file test rewrite. Operator-directed to a
fresh branch, **`claude/stale-test-classes-repair`** (based on `main`, independent
of this one). Summary of what landed there:

| Class | Recovered | Repair |
|---|---:|---|
| `extract_packing()` arity | 16 sites / 3 files | tests unpack 4, matching the function and all five production callers |
| `ON CONFLICT` | 29 | conflict target → `(batch_id, client_name, clone_generation)`, the live key |
| `settings.environment` stub | 7 | added to the stub; **+2 new tests** for the Lesson-E guard the drift was hiding |
| `_c1f_mirror_good_id_with_fallback` | 6 | rewritten to the post-C-3g mirror-only contract, strengthened to assert the cache is never read |
| `test_intake.py` false red | 1 | applied the file's own missing-fixture skip convention |
| MagicMock filename leak | leak | `carrier_storage_root` pinned in 2 carrier suites |

Two corrections to #1059's analysis, both leaving its verdict (test-side, not a
regression) intact:

- **`ON CONFLICT`** — #1059 recorded that `proforma_drafts` has "no UNIQUE/PK on
  `(batch_id, client_name)`". It does have one; the clone/reissue migration
  (`proforma_invoice_link_db.py:743`) simply widened it to include
  `clone_generation`. The seeds named the pre-migration key.
- **`_c1f_mirror_good_id_with_fallback`** — #1059 called this a stale symbol
  reference, implying a rename. It is not: **C-3g removed the cache fallback**.
  Three of the six tests asserted "mirror absent → return the cache id", which is
  the behaviour the MASTER CONSUMPTION RULE deliberately deleted. Renaming alone
  would have left those three failing; blindly rewriting them to match the old
  helper would have re-legitimised a second product-identity authority.

Leak finding 1 (`c:\PZ\storage`) was **not** repaired: open PR **#1053** already
fixes it, with a sharper diagnosis — the guard tests pass a hardcoded Windows
path that POSIX resolves relative to the CWD — using a CWD sandbox. Not
duplicated.

Verification on that branch: 131 passed / 11 skipped across the seven repaired
files; carrier 650 passed with **0** leaked artifacts (was 11); PZ 260/260;
golden 160/160.

**GATE 2 still blocks both PRs.** Four are open (#1062, #1053 implementation;
#1061, #1059 docs-only) — the cap is 3 implementation + 1 docs-only. Both
branches are pushed and waiting for a slot; opening either would make five.

> **Superseded 2026-08-01.** #1059 was closed at operator request, which freed
> the slot this branch now occupies as **#1063**. The count is again 3
> implementation (#1062, #1053, #1063) + 1 docs-only (#1061) = the cap, so
> GATE 2 is satisfied. The paragraph above describes the state on 2026-07-31 and
> is kept as the record of why the branch waited.

---

## Verification run in this session

| Check | Result |
|---|---|
| `tests/test_settings_singleton_isolation.py` | 7 passed |
| `tests/test_registry_sales_line_count.py` | 7 passed |
| `tests/test_ci_shard_partition.py` | 16 passed *(2026-07-31 measurement)* — **27 passed as of 2026-08-01**, after the hash-assignment and reviewer-repair commits added tests |
| reload-first ordering (isolation → 3 registry files) | 29 passed, 1 failed — `test_registry_purchase_line_count::test_registry_counts_are_per_document_not_batch_total`, which **also fails standalone**; pre-existing, unrelated to this branch |
| root `make verify` (golden regression) | 160/160 |
| pre-commit smoke set | 63 passed |

A full-suite run and a post-fix shard-1 regression run were both killed by a
container restart mid-flight; the shard-1 run was repeated. No count in this
report comes from a truncated run.

---

## Reviewer pass 2026-08-01 — GATE 1 verdicts and GATE 4 dispositions

Four read-only reviewer subagents ran against `d0d8b1e`: `reviewer-challenge`,
`test-coverage-reviewer`, `gap-hunter`, `final-consistency-review`. Verdicts:
three APPROVE-WITH-FINDINGS, one CHANGES REQUESTED (`gap-hunter`, on the
false-green hole below). Findings were verified against the tree before being
accepted — two were re-scoped as a result, recorded honestly here.

### Repaired in this branch

| Finding | Repair |
|---|---|
| **Valid-but-empty shard XML aggregated GREEN.** `<testsuite tests="0"/>` parses fine, so a shard that collected nothing (pytest exit 5, bad file list) read as "complete, 0 failures" — the exact silent downgrade the aggregate exists to prevent | `parse_report` marks a zero-case shard INCOMPLETE; pinned by `test_valid_but_empty_shard_xml_is_incomplete_not_green` |
| **Valid-but-partial shard XML.** A document cut short after the header parses but holds fewer `<testcase>` elements than its own `tests=` declares | declared-vs-present check, INCOMPLETE on short count; pinned by `test_short_count_shard_xml_is_incomplete`. Caught a stale `tests="3"` in an existing test fixture on first run |
| **`junit_summary` docstring advertised a coverage reconciliation `render()` never implemented** | docstring now describes the checks that exist |
| **`discover()` globbed only `test_*.py`**, while pytest's default `python_files` is `test_*.py` AND `*_test.py` — a `*_test.py` file would run locally and in deploy-gate subsets but in no shard | both patterns globbed, de-duplicated; pinned by two new tests. Latent, not active: 0 such files exist under `tests/` today |
| **`classify_failures.py --of` declared and never read** — a shard with no XML was silently absent from triage | wired to a MISSING-shard warning, matching `junit_summary`'s behaviour |
| **`UNRUNNABLE` was unreachable.** The child inherits `pytest.ini`'s 120s watchdog, below the 600s subprocess timeout, so a hanging file always returned an ordinary non-zero code and was misfiled `ISOLATED_FAIL` — the opposite diagnosis | child runs with `-p no:timeout` so our timeout wins and rc 124 → UNRUNNABLE is reachable |
| **The watchdog pin silently skipped** any non-literal or positional `sqlite3.connect` timeout, so an unbounded value could be added beside a literal one and keep the test green | unparseable timeouts now FAIL the pin; scope limits stated in the docstring and in `pytest.ini` |
| **`_pin_settings_singleton` rested on an unenforced ordering invariant** — `app.main` bound pristine before any reload was true by convention (other modules' imports), not construction | `conftest.py` imports `app.main` at module scope, before any test can run |
| **Shard-count changes silently reset comparability.** `% of` is not consistent hashing: 6→7 keeps only 152/974 files (15.6%). The ops doc's own remedy for the balance alarm was "reconsider the shard count" — which defeats the stability the change is sold on | remedy rewritten; a `--of` change is documented as a comparison-reset event, with consistent hashing named as the real fix if balance and stability are ever needed together |
| Stale: `ci.yml` "Two independent jobs" / "neither job is required" (three jobs now; one IS the intended required check); "973 files" (974, and drifting); report's `16 passed` and bin-packing-as-current-fact; unused `import pytest` | all corrected |

### GATE 4 dispositions — NOT repaired here

| Finding | Disposition |
|---|---|
| **Nine sibling `_db_path` module globals** (`document_db`, `wfirma_db`, `packing_db`, `warehouse_db`, `tracking_db`, `correction_registry`, `proforma_service_charges_db`, `warehouse_receipt_db`, `intake_lineage`) are set by fixtures and never restored — the same defect class this branch fixes for `settings`, left standing for ten other globals. A first-class ORDER_CONTAMINATION generator | **SCHEDULED** — own slice. Fixing ten globals' isolation is not a rider on a CI-sharding PR, and each needs its own restore semantics |
| **Unbounded waits in production code**: `lock.acquire()` with no timeout and `flock(LOCK_EX)` without `LOCK_NB` at 4 sites in `email_evidence_store.py` / `email_evidence_processor.py`. On the Windows runner this is a live recurrence path for the incident class this branch addresses — no watchdog can exceed an unbounded wait | **SCHEDULED** — production locking change, needs its own review. Scope disclosed in `pytest.ini` and the pin docstring so it is not mistaken for covered |
| **`routes_bot.py` 300s `asyncio.wait_for`** exceeds the 120s watchdog | **SCHEDULED** — with the item above; same "widen the invariant" slice |
| **`classify_failures.py --jobs 4` self-contaminates** — concurrent runs share the real live storage roots, so one process's write trips another's guard and a green file is reported ISOLATED_FAIL, corrupting the tool's central distinction | **SCHEDULED** — triage-tool correctness, no CI impact (the tool is operator-invoked) |
| **`atexit` sandbox cleanup never runs on `os._exit()`** — i.e. on every hung shard, the scenario this branch is built around — and Windows `rmtree` over open WAL files fails silently under `ignore_errors=True`, so `pz_test_storage_*` accumulates on the verify host | **SCHEDULED** |
| **First-import-during-divergence escapes the pin.** A module imported for the first time while the binding is diverged caches the orphaned object permanently; the fixture cannot reach it. The docstring's "bounds divergence to the single test" is stronger than what it delivers for that case | **SCHEDULED** — needs a session-level guarantee, not a per-test restore |
| **`CLAUDE.md` records 748 pytest files**; actual is 974 | **SCHEDULED** — governance-doc drift, predates this branch; belongs with the #1061 register reconciliation |
| **Balance is measured in bytes, not wall clock**, while the thing actually bounded is runtime against `timeout-minutes` | **REJECTED for now** — recorded as a known proxy. A durations file would track runtime properly but needs a recorded-timings artifact this repo does not yet produce; bytes remain a usable lopsidedness alarm meanwhile |
| **Shard count hardcoded in three places in `ci.yml`** (`matrix.shard`, `--of` twice) with no single source of truth | **REJECTED for now** — the mismatch that matters fails loud (`shard_files()` raises), and GitHub Actions has no clean way to derive a matrix from a scalar without a setup job. Revisit if the count ever changes |
