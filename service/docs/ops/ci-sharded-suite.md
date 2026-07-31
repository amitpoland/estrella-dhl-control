# CI — sharded service suite

**Workflow:** `.github/workflows/ci.yml`, jobs `service-suite` (matrix 1–6) and
`service-suite-report`.
**Tools:** `service/tools/shard_tests.py`, `service/tools/junit_summary.py`,
`service/tools/classify_failures.py`.
**Pinned by:** `service/tests/test_ci_shard_partition.py`.

---

## The problem it solves

The service suite ran as one pytest process. `pytest.ini` sets
`timeout_method = thread`, and pytest-timeout's thread method cannot interrupt a
blocked C call — it terminates the whole process. One hung test therefore
discarded every result after it.

A run that died at 77% reported a single timeout and hid the standing failures in
the remaining 23%. Re-running cost another 1–2 hours and produced the same
single line of information. That is the failure this layout removes: not the
hang itself, but the fact that one hang destroyed the entire run's evidence.

## What changed

Six independent shards, `fail-fast: false`, each writing its own JUnit XML and
uploading it with `if: always()`. A hang now costs one shard. The
`service-suite-report` job downloads every shard's XML and prints one
reconciliation into the run summary.

The honesty rule the aggregation enforces: **a shard whose XML is missing or
truncated is reported INCOMPLETE, never as zero failures.** A hard-killed
process writes no XML — counting that as clean would make a worse run look
greener. `test_ci_shard_partition.py` pins this.

**Branch protection:** the verdict lives in `Service pytest (aggregate)`, not in
the shard jobs. Shard steps are `continue-on-error: true` so a red or hung shard
still uploads its XML, which means a shard job can report success while its tests
failed. Requiring a shard job as a status check would be a green light with
nothing behind it.

## The watchdog must outlast the longest blocking wait

`timeout_method = thread` is mandatory on Windows (`signal` is POSIX-only) and
**cannot interrupt a blocked C call** — it terminates the whole pytest process,
which writes no JUnit XML. So the per-test timeout must stay strictly above the
longest wait a test can enter, or a locked database becomes a coin flip between
"one test fails" and "this shard's entire result set is lost".

The suite had `pytest.ini timeout = 30` against six
`sqlite3.connect(..., timeout=30.0)` call sites — a guaranteed tie. CI run
`30640385564` lost all of shard 2 to it: the watchdog fired inside
`sqlite3.connect()` during
`test_inbox_proforma_draft_source.py::test_posting_is_high`, killed the process,
and the shard uploaded nothing. The aggregate correctly reported it MISSING.

`timeout = 120` makes the SQLite wait always lose the race: `connect` raises
`OperationalError: database is locked` at 30s, that one test fails normally, and
the shard still produces a complete report. Pinned by
`test_ci_shard_partition.py::test_pytest_timeout_exceeds_sqlite_busy_timeouts` —
if a longer `sqlite3.connect(timeout=…)` is ever added, raise the pytest timeout
above it rather than relaxing the test.

This changes *legibility*, not correctness: a lock contention that used to
destroy a shard now shows up as an ordinary failing test that can be diagnosed.

## Shard membership

`tools/shard_tests.py` bin-packs whole FILES greedily by size. Whole files
because many files here share module-level fixtures and per-file database state —
splitting inside a file would invent failures that do not exist. The partition is
a pure function of the file listing, so every runner computes the same one.

```
python tools/shard_tests.py --of 6 --describe        # per-shard sizes
python tools/shard_tests.py --shard 3 --of 6         # the files in shard 3
```

Adding or deleting a test file re-balances the shards. That is expected; nothing
records shard membership anywhere else.

## Cross-shard ordering caveat

Shards are separate processes, so order-dependent failures **will** differ from a
monolithic run: a test that only failed after some earlier file polluted global
state may pass in its shard, and vice versa.

That difference is diagnostic, not noise. Do not tune shard membership to make a
failure go away — a failure that moves when you move files is an isolation bug in
the code under test or in the leaking test, and it is telling you exactly that.

## Triage

```
python tools/junit_summary.py junit --of 6              # what failed, by file
python tools/classify_failures.py junit --of 6 --out reports/triage.md
```

`classify_failures.py` re-runs each failing file alone in a fresh interpreter and
splits the result:

| Class | Meaning | Correct response |
|---|---|---|
| `ISOLATED_FAIL` | fails alone — the test and the code genuinely disagree | read both, then fix whichever is wrong (stale assertion, obsolete contract, or a real regression) |
| `ORDER_CONTAMINATION` | passes alone — an earlier file leaked process-global state | fix the **leak**, not this test |
| `RECOVERED` | green alone, no aggregate failure list | the file was killed mid-run; re-check its shard |
| `UNRUNNABLE` | hangs alone, collects nothing, or is missing | investigate directly — this is the class that kills shards |

Making a test pass by weakening it is not a repair. Neither is quarantining an
`ORDER_CONTAMINATION` file: the leak stays and resurfaces somewhere else, in a
file whose owner has no idea why.

## Known leak class: the Settings singleton

`importlib.reload(app.core.config)` rebinds that module's `settings` name to a
new object. app.main and the ~70 route modules keep the original, so a fixture
that patches the reloaded object redirects nothing app.main can see — startup
initialises its ~20 databases under the *previous* root and contends with an
earlier lifespan's still-running background threads. On Windows that surfaces as
a hang inside `con.executescript(_DDL)` (reservation_queue.db), i.e. exactly the
`UNRUNNABLE` class above.

Guards, all in `service/tests/`:

- `conftest.py` exports `STORAGE_ROOT` so a reload-created `Settings()` still
  resolves to the session sandbox (no writes reach a real live root);
- `conftest.py::_pin_settings_singleton` restores the binding after every test,
  bounding a reload's blast radius to the test that performed it;
- `test_settings_singleton_isolation.py` pins both halves — that patching the
  reloaded object redirects nothing, and that patching `app.main.settings` works.

**Writing a client fixture:** resolve the settings object through `app.main`, and
do not bind it at module import.

```python
@pytest.fixture()
def client(storage):
    import app.main as main_module
    with patch.object(main_module.settings, "storage_root", storage):
        with TestClient(main_module.app) as c:
            yield c
```

## Relationship to the deploy gate

Unchanged. `.claude/contracts/test-baseline.md` remains the single source of
truth for deploy pass criteria, and `deploy_qa_reviewer` still reads it. Sharding
changes how results are *collected*, not what counts as a pass — and the
aggregate job is red whenever any shard is red or incomplete.
