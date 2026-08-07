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

**CI does not gate.** Branch protection is intentionally not set: this suite is a
diagnostic, and per the 2026-08-07 operator ruling CI may not gate merges or
production deploys. Enabling any required status check is an operator decision
requiring a PROJECT_STATE.md DECISIONS entry. Normative rule (not restated here):
`CLAUDE.md` § OPERATING MODEL — governance reset, subsection "CI authority —
diagnostic, never a gate".

### If branch protection is ever enabled by operator decision…

…the verdict lives in `Service pytest (aggregate)`, not in the shard jobs. Shard
steps are `continue-on-error: true` so a red or hung shard still uploads its XML,
which means a shard job can report success while its tests failed. Requiring a
shard job as a status check would be a green light with nothing behind it.

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

`tools/shard_tests.py` assigns whole FILES by **`sha256(relative posix path) %
6`**. Whole files because many files here share module-level fixtures and
per-file database state — splitting inside a file would invent failures that do
not exist. The key is relative and POSIX-style because an absolute or
backslashed path differs per checkout and per OS, which would give each runner a
different partition for the same tree.

```
python tools/shard_tests.py --of 6 --describe        # per-shard counts + sizes
python tools/shard_tests.py --shard 3 --of 6         # the files in shard 3
```

### Why hashing and not size-based packing

The original plan bin-packed greedily by size, which balanced the shards more
tightly. It was replaced because membership was a function of the **whole
listing**: adding a file, deleting one, or merely growing one re-sorted the size
ordering and could move an arbitrary number of *unrelated* files into different
shards.

That silently breaks the comparison this suite is triaged by. "Shard 4 failed
the same three files it failed last run" only means something while shard 4
denotes the same set of files; under packing it often did not, and nothing in
the output said so. Under hash assignment a file's shard depends on its own path
alone, so churn moves the changed file and leaves every other file where it was.

The trade is real and accepted: shards are now balanced only statistically, so
the slowest shard's wall clock will vary more. That is bounded by the job's
`timeout-minutes`. A reshuffled partition, by contrast, produced wrong
conclusions with no warning at all.

`test_shards_are_roughly_balanced` is a lopsidedness alarm on that trade, not a
packing contract. If it fires, read `--describe` first — do **not** hand-move
files, which would forfeit the stability the hash buys.

Renaming a test file does change its shard; that is inherent to keying on the
path, and it moves only that file.

### Changing the shard count resets all comparability

`assign()` is plain `% of`, not consistent hashing, so **changing `of` reshuffles
almost the whole suite** — measured 6 → 7, only **152 of 974 files (15.6%)** keep
their shard. That is the same wholesale reshuffle that made bin packing
unusable; it is merely rarer, because `of` changes on purpose and file contents
change constantly.

So a shard-count change is a **comparison-reset event**. Treat it accordingly:

- it invalidates every historical "shard N failed the same files" observation;
- it is not the first answer to a balance alarm, even though the alarm is about
  balance. Prefer investigating the slow shard's actual wall clock — bytes are
  what `--describe` measures, and bytes are only a proxy for runtime;
- when `of` does change, say so in the commit message and re-baseline rather
  than comparing across the boundary.

If a future run needs balance *and* stability together, the fix is consistent
hashing (a hash ring, or rendezvous hashing), where changing `of` moves only
~1/N of the files. That is a real option, not a hypothetical — it is simply not
needed while `of` stays at 6.

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
