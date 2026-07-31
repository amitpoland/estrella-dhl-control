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
- `tools/shard_tests.py` — deterministic file-level bin-packing (measured:
  162–163 files, 2188.8–2188.9 KiB per shard).
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

## 5. Repair — scoped, not done

Not attempted here, and deliberately so:

- The four classes above (55 failures across ~6 files) are **already SCHEDULED**
  under #1059's GATE-4 disposition. They are a different class of work from this
  branch's subject, and folding them in would make a test-isolation PR into an
  unrelated 6-file test rewrite.
- **GATE 2 blocks a second PR.** Four PRs are open (#1062, #1061, #1059, #1053 —
  two implementation, two docs-only), which is the cap (3 implementation + 1
  docs-only). A slot must clear before another implementation PR opens.

The repair queue, in the order it should be taken:

1. `extract_packing()` 3-tuple unpacks → 4-tuple (13). All five production
   callers already unpack 4; the tests are stale.
2. `ON CONFLICT(batch_id, client_name)` seed helpers (29). `proforma_drafts` has
   no matching UNIQUE constraint; no route or service runs that statement.
3. `test_email_sender::_settings()` stub missing `environment` (7). The real
   `Settings` has it; the SMTP guard at `email_sender.py:528` is correct.
4. `_c1f_mirror_good_id_with_fallback` → `_c1f_mirror_good_id` (6).
5. The two leak writers above.

Each is a stale test meeting correct production code. None is repaired by
weakening an assertion, and none should be quarantined — quarantine leaves the
leak and moves the failure to a file whose owner has no context for it.

---

## Verification run in this session

| Check | Result |
|---|---|
| `tests/test_settings_singleton_isolation.py` | 7 passed |
| `tests/test_registry_sales_line_count.py` | 7 passed |
| `tests/test_ci_shard_partition.py` | 16 passed |
| reload-first ordering (isolation → 3 registry files) | 29 passed, 1 failed — `test_registry_purchase_line_count::test_registry_counts_are_per_document_not_batch_total`, which **also fails standalone**; pre-existing, unrelated to this branch |
| root `make verify` (golden regression) | 160/160 |
| pre-commit smoke set | 63 passed |

A full-suite run and a post-fix shard-1 regression run were both killed by a
container restart mid-flight; the shard-1 run was repeated. No count in this
report comes from a truncated run.
