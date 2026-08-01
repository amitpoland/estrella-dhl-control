"""test_ci_shard_partition.py — the CI shard plan must be a true partition.

The sharded service-suite job trusts tools/shard_tests.py to cover every test
file exactly once.  A partition bug is invisible in CI: a dropped file just
stops being reported, and the run looks *greener* than the tree actually is.
These tests make the contract explicit.

Also pins tools/junit_summary.py's central honesty rule — a shard whose XML is
missing or truncated must be reported INCOMPLETE, never counted as zero
failures.  That rule is the whole reason sharding is safe to adopt: a shard
killed by pytest-timeout's thread method loses its results, and the aggregate
must say so rather than quietly under-count.

Run: python -m pytest tests/test_ci_shard_partition.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parent.parent
if str(_SERVICE / "tools") not in sys.path:
    sys.path.insert(0, str(_SERVICE / "tools"))

import classify_failures  # noqa: E402
import junit_summary  # noqa: E402
import shard_tests  # noqa: E402


# ── The partition contract ───────────────────────────────────────────────────

@pytest.mark.parametrize("of", [1, 2, 6, 7])
def test_every_test_file_lands_in_exactly_one_shard(of):
    files = shard_tests.discover()
    assert files, "no test files discovered — the glob or the path is wrong"
    shards = shard_tests.partition(files, of)
    assert len(shards) == of
    flat = [p for s in shards for p in s]
    assert len(flat) == len(files), "a file was dropped or duplicated"
    assert set(flat) == set(files), "the union of the shards must be the whole suite"
    assert len(set(flat)) == len(flat), "no file may appear in two shards"


def test_partition_is_deterministic():
    """Same tree in, same partition out — two runners must agree, or a file
    silently runs twice while another never runs at all."""
    files = shard_tests.discover()
    first = shard_tests.partition(files, 6)
    second = shard_tests.partition(list(reversed(files)), 6)
    assert first == second, "partitioning must not depend on input order"


def test_assignment_is_stable_across_processes():
    """The assignment must not depend on a per-process hash salt.

    ``hash()`` is salted by PYTHONHASHSEED, so a partition built on it differs
    between runners: some files would run twice and others not at all, with
    nothing in the output to reveal it. Recomputing the documented sha256 rule
    here pins that the tool uses a stable digest, not the built-in.
    """
    import hashlib

    for p in shard_tests.discover()[:50]:
        rel = p.relative_to(shard_tests.SERVICE_ROOT).as_posix()
        expected = int(hashlib.sha256(rel.encode("utf-8")).hexdigest(), 16) % 6
        assert shard_tests.assign(p, 6) == expected, rel


def test_membership_is_stable_when_other_files_change(tmp_path):
    """The reason this is hash-based and not bin-packed.

    Greedy largest-first packing made a file's shard a function of the WHOLE
    listing: adding one file — or merely growing one — re-sorted the size
    ordering and could move an arbitrary number of unrelated files. That breaks
    the comparison this suite is triaged by, since "shard 4 failed the same
    files it failed last run" only means something while shard 4 denotes the
    same set. Under hash assignment, churn moves the changed file and nothing
    else.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for i in range(40):
        (tests_dir / f"test_m{i}.py").write_text("x" * (100 * (i + 1)), encoding="utf-8")

    def plan():
        shards = shard_tests.partition(
            shard_tests.discover(tests_dir, tmp_path), 6, tmp_path)
        return {p: i for i, s in enumerate(shards) for p in s}

    before = plan()

    # Churn: one new large file, one deletion, and one existing file grown 50x.
    (tests_dir / "test_new_big.py").write_text("y" * 90_000, encoding="utf-8")
    (tests_dir / "test_m7.py").unlink()
    (tests_dir / "test_m3.py").write_text("z" * 50_000, encoding="utf-8")

    after = plan()

    survivors = before.keys() & after.keys()
    assert len(survivors) == 39
    moved = [p.name for p in survivors if before[p] != after[p]]
    assert not moved, f"unrelated files changed shard: {moved}"


def test_shards_are_roughly_balanced():
    """Hash assignment balances only statistically — the tight bound that greedy
    packing guaranteed is the thing traded away for stable membership.

    So this is a lopsidedness alarm, not a packing contract. A breach means the
    real distribution drifted far enough that one shard dominates the wall
    clock; the answer is to look at ``--describe`` and consider the shard count,
    NOT to hand-move files (which would forfeit the stability above).
    """
    shards = shard_tests.partition(shard_tests.discover(), 6)
    sizes = [sum(f.stat().st_size for f in s) for s in shards]
    counts = [len(s) for s in shards]
    assert min(counts) > 0, f"an empty shard collects nothing: {counts}"
    assert max(sizes) <= min(sizes) * 2.0, f"shard sizes too uneven: {sizes}"


def test_shard_files_is_one_based_and_range_checked():
    of = 4
    assert shard_tests.shard_files(1, of) == shard_tests.partition(
        shard_tests.discover(), of)[0]
    for bad in (0, of + 1, -1):
        with pytest.raises(ValueError):
            shard_tests.shard_files(bad, of)


def test_shard_paths_are_posix_relative():
    """CI passes these straight to pytest on Windows and POSIX alike."""
    for p in shard_tests.shard_files(1, 6):
        rel = p.relative_to(shard_tests.SERVICE_ROOT).as_posix()
        assert rel.startswith("tests/")
        assert "\\" not in rel


def test_conftest_is_not_shardable():
    """conftest.py is loaded implicitly per shard; listing it as a target would
    make the shard plan wrong AND double-load the fixtures.

    Note this is a forward-guard, not a pin on active behaviour: `conftest.py`
    matches neither `test_*.py` nor `*_test.py`, so the filter in `discover()`
    never fires today. It earns its place only if the glob is later widened.
    """
    assert not any(p.name == "conftest.py" for p in shard_tests.discover())


def test_discover_matches_both_pytest_default_patterns(tmp_path):
    """`discover()` must agree with what pytest itself would collect.

    pytest's default `python_files` is `test_*.py` AND `*_test.py`, and
    `service/pytest.ini` does not override it. A `*_test.py` file that pytest
    collects but no shard runs would execute locally and in the deploy-gate
    subsets while being absent from the job that reports the verdict — the run
    looks greener than the tree, which is the whole failure class this tooling
    exists to remove.
    """
    tests_dir = tmp_path / "tests"
    (tests_dir / "sub").mkdir(parents=True)
    for name in ("test_alpha.py", "beta_test.py", "sub/test_gamma.py",
                 "sub/delta_test.py"):
        (tests_dir / name).write_text("def test_x(): pass\n", encoding="utf-8")
    # Neither collected by pytest, so neither may appear in a shard.
    (tests_dir / "conftest.py").write_text("", encoding="utf-8")
    (tests_dir / "helpers.py").write_text("", encoding="utf-8")

    found = {p.name for p in shard_tests.discover(tests_dir, tmp_path)}
    assert found == {"test_alpha.py", "beta_test.py", "test_gamma.py",
                     "delta_test.py"}, found


def test_discover_does_not_double_count_a_file_matching_both_patterns(tmp_path):
    """`test_thing_test.py` matches both globs — it must still be ONE entry.

    A duplicate would run the file twice in the same shard and break the
    exactly-once partition contract above.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_thing_test.py").write_text("def test_x(): pass\n",
                                                  encoding="utf-8")
    files = shard_tests.discover(tests_dir, tmp_path)
    assert len(files) == 1, files


# ── The watchdog must not outrace a blocking wait ────────────────────────────

def _connect_arglists(text: str) -> list[str]:
    """Yield the raw argument text of every ``sqlite3.connect(...)`` call.

    Depth-counted rather than regex-matched: the first positional argument is
    routinely ``str(db_path)``, and a naive ``[^)]*`` stops at that inner
    close-paren before ever reaching the ``timeout=`` keyword — silently finding
    zero call sites and turning this pin into a no-op.
    """
    out: list[str] = []
    for m in re.finditer(r"sqlite3\.connect\(", text):
        i = m.end()
        depth = 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        out.append(text[m.end():i - 1])
    return out


def test_connect_arglist_scanner_sees_past_nested_parens():
    """Guard for the guard: the scanner must not stop at ``str(db_path)``."""
    calls = _connect_arglists(
        "conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)"
    )
    assert calls == ["str(db_path), timeout=30.0, check_same_thread=False"]
    assert _connect_arglists("no calls here") == []


def test_pytest_timeout_exceeds_sqlite_busy_timeouts():
    """The per-test watchdog must be strictly greater than the longest SQLite
    busy-wait any test can enter.

    `timeout_method = thread` is mandatory on Windows (the `signal` method is
    POSIX-only) and cannot interrupt a blocked C call — it kills the whole pytest
    process, which writes NO JUnit XML. So if the watchdog and a
    `sqlite3.connect(..., timeout=N)` are both N seconds, a locked database is a
    race between "one test fails with OperationalError" and "the entire shard's
    results are lost".

    CI run 30640385564 lost all of shard 2 to exactly that tie (watchdog 30s vs
    connect timeout 30.0s), so this is a pin on a defect that has already
    happened once, not a hypothetical.

    If a new `sqlite3.connect(timeout=...)` is added with a longer wait, raise
    the pytest timeout above it rather than relaxing this test.

    SCOPE — read this before trusting the name. This pin covers exactly one
    class of blocking wait: `sqlite3.connect(timeout=<literal>)` under
    `service/app/`. It does NOT cover, and must not be cited as covering:

      * unbounded waits — `threading.Lock.acquire()` with no timeout and
        `fcntl.flock(..., LOCK_EX)` without `LOCK_NB` (four such sites live in
        `email_evidence_store.py` / `email_evidence_processor.py`). No watchdog
        value can exceed an unbounded wait;
      * `PRAGMA busy_timeout=<ms>`, a second SQLite mechanism that overrides the
        connect-time value entirely;
      * non-SQLite waits — `asyncio.wait_for`, smtplib/httpx timeouts,
        `Thread.join(timeout=)`, `socket.create_connection`. `routes_bot.py`
        already carries a 300s `asyncio.wait_for`, above this watchdog.

    Those are tracked as GATE 4 findings, not silently assumed safe. What this
    test does guarantee is that the one wait class that has ALREADY destroyed a
    shard (CI run 30640385564) cannot tie with the watchdog again.
    """
    ini = (_SERVICE / "pytest.ini").read_text(encoding="utf-8")
    m = re.search(r"^timeout\s*=\s*([0-9]+)\s*$", ini, re.MULTILINE)
    assert m, "pytest.ini must declare an explicit per-test timeout"
    pytest_timeout = int(m.group(1))

    waits: dict[str, float] = {}
    unparseable: list[str] = []
    for src in (_SERVICE / "app").rglob("*.py"):
        text = src.read_text(encoding="utf-8", errors="ignore")
        for call in _connect_arglists(text):
            rel = str(src.relative_to(_SERVICE))
            m2 = re.search(r"\btimeout\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*[,)]?\s*$"
                           r"|\btimeout\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*,", call)
            if not m2:
                # A timeout that is a name, an expression, scientific notation,
                # or passed positionally reads as "no wait to check" to the
                # regex. Skipping it would let an unbounded value be added right
                # next to a literal one and keep this test green — the exact
                # shape of a pin that passes while what it names is broken.
                if "timeout" in call:
                    unparseable.append(f"{rel}: timeout=... not a literal ({call.strip()[:80]})")
                continue
            waits[rel] = max(float(m2.group(1) or m2.group(2)), waits.get(rel, 0.0))

    assert not unparseable, (
        "sqlite3.connect() call site(s) whose timeout this pin cannot read — "
        "make the value a literal or extend this test; do not leave it unchecked:\n"
        + "\n".join(unparseable)
    )
    assert waits, "expected to find sqlite3.connect(timeout=...) call sites"
    worst_file = max(waits, key=lambda k: waits[k])
    worst = waits[worst_file]
    assert pytest_timeout > worst, (
        f"pytest.ini timeout={pytest_timeout}s does not exceed the longest SQLite "
        f"busy-wait ({worst}s, in {worst_file}). The thread-method watchdog would "
        f"kill the process mid-connect and the shard would upload no JUnit XML — "
        f"losing every result in that shard, not just this test's."
    )


# ── The aggregation honesty contract ─────────────────────────────────────────

_GOOD_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="0" skipped="1">
<testcase classname="tests.test_alpha" name="test_ok"/>
<testcase classname="tests.test_alpha" name="test_bad"><failure message="assert 1 == 2">x</failure></testcase>
<testcase classname="tests.test_beta" name="test_skipped"><skipped message="no creds"/></testcase>
</testsuite></testsuites>
"""


def test_summary_counts_a_complete_shard(tmp_path):
    p = tmp_path / "junit-shard-1.xml"
    p.write_text(_GOOD_XML, encoding="utf-8")
    rep = junit_summary.parse_report(p)
    assert rep.complete and rep.label == "1"
    assert rep.counts == {"passed": 1, "failure": 1, "error": 0, "skipped": 1}
    assert [c.name for c in rep.bad] == ["test_bad"]


def test_truncated_shard_xml_is_incomplete_not_zero_failures(tmp_path):
    """The load-bearing rule: a hard-killed shard must not read as a clean shard."""
    p = tmp_path / "junit-shard-2.xml"
    p.write_text(_GOOD_XML[: len(_GOOD_XML) // 2], encoding="utf-8")
    rep = junit_summary.parse_report(p)
    assert not rep.complete
    assert rep.cases == [], "an unparseable shard reports no results at all"
    text, ok = junit_summary.render([rep], expected_shards=1)
    assert not ok, "an incomplete shard can never produce a green aggregate"
    assert "INCOMPLETE" in text
    assert "floor, not the suite result" in text


def test_empty_shard_xml_is_incomplete(tmp_path):
    p = tmp_path / "junit-shard-3.xml"
    p.write_text("", encoding="utf-8")
    assert not junit_summary.parse_report(p).complete


def test_valid_but_empty_shard_xml_is_incomplete_not_green(tmp_path):
    """The false-GREEN case, which the truncated/missing tests do NOT cover.

    A shard that collected nothing — pytest exit 5, a bad file list, a filter
    matching no tests — writes a perfectly well-formed ``<testsuite tests="0"/>``.
    Unparseable input fails loudly; THIS input used to aggregate as "complete,
    0 failures" and turn the whole run green off a shard whose tests never ran.
    That is the silent downgrade the aggregate exists to prevent, so it must be
    INCOMPLETE.
    """
    p = tmp_path / "junit-shard-4.xml"
    p.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        '<testsuite name="pytest" tests="0" failures="0" errors="0" skipped="0"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    rep = junit_summary.parse_report(p)
    assert not rep.complete, "a shard that ran nothing is unknowable, not clean"
    assert "no testcases" in rep.reason
    text, ok = junit_summary.render([rep], expected_shards=1)
    assert not ok, "an empty shard can never produce a green aggregate"
    assert "INCOMPLETE" in text


def test_short_count_shard_xml_is_incomplete(tmp_path):
    """Declared-vs-present mismatch: the document parses but is missing cases.

    pytest writes its own total on ``<testsuite tests="N">``. A process killed
    after the header was flushed can leave valid XML holding fewer ``<testcase>``
    elements than N. Counting that as a full shard under-reports the run.
    """
    p = tmp_path / "junit-shard-5.xml"
    p.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        '<testsuite name="pytest" tests="400" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_alpha" name="test_ok"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    rep = junit_summary.parse_report(p)
    assert not rep.complete
    assert "short count" in rep.reason
    _, ok = junit_summary.render([rep], expected_shards=1)
    assert not ok


def test_declared_count_matching_case_count_stays_complete(tmp_path):
    """Guard for the guard: the new checks must not reject a healthy shard."""
    p = tmp_path / "junit-shard-6.xml"
    p.write_text(_GOOD_XML, encoding="utf-8")
    rep = junit_summary.parse_report(p)
    assert rep.complete, rep.reason
    assert len(rep.cases) == 3


def test_missing_shard_is_reported_against_the_expected_count(tmp_path):
    """Shard 2 of 2 never wrote an XML — the report must name it, not skip it."""
    (tmp_path / "junit-shard-1.xml").write_text(_GOOD_XML, encoding="utf-8")
    reports = [junit_summary.parse_report(p) for p in junit_summary.collect([str(tmp_path)])]
    text, ok = junit_summary.render(reports, expected_shards=2)
    assert not ok
    assert "MISSING" in text


def test_all_green_shards_produce_a_green_aggregate(tmp_path):
    # Drop the failing case AND correct the declared total — pytest always emits
    # a tests= that matches the cases it wrote, and the short-count check now
    # holds the aggregate to that.
    green = _GOOD_XML.replace(
        '<testcase classname="tests.test_alpha" name="test_bad">'
        '<failure message="assert 1 == 2">x</failure></testcase>', "").replace(
        'tests="3"', 'tests="2"')
    (tmp_path / "junit-shard-1.xml").write_text(green, encoding="utf-8")
    reports = [junit_summary.parse_report(p) for p in junit_summary.collect([str(tmp_path)])]
    text, ok = junit_summary.render(reports, expected_shards=1)
    assert ok, text
    assert "no failures" in text


def test_failures_are_grouped_by_file(tmp_path):
    (tmp_path / "junit-shard-1.xml").write_text(_GOOD_XML, encoding="utf-8")
    reports = [junit_summary.parse_report(p) for p in junit_summary.collect([str(tmp_path)])]
    text, _ = junit_summary.render(reports, expected_shards=1)
    assert "Failures by file" in text
    assert "tests/test_alpha.py" in text and "test_bad" in text


def test_failure_triage_report_separates_the_two_classes():
    """The triage report must keep order contamination and isolated failures in
    SEPARATE buckets — collapsing them is what makes a red baseline permanent,
    because "fix the test" is the right answer for one and the wrong answer for
    the other."""
    V = classify_failures.FileVerdict
    text = classify_failures.render([
        V("tests/test_leaky.py", ["test_a"], classify_failures.ORDER_CONTAMINATION,
          [], "green in isolation"),
        V("tests/test_stale.py", ["test_b"], classify_failures.ISOLATED_FAIL,
          ["tests/test_stale.py::test_b"], "fails alone"),
    ])
    assert "ORDER_CONTAMINATION (1 files)" in text
    assert "ISOLATED_FAIL (1 files)" in text
    assert "tests/test_leaky.py" in text and "tests/test_stale.py" in text
    assert "fix the LEAK, not this test" in text


def test_pytest_failure_lines_are_parsed_into_node_ids():
    """Isolated-run triage reads pytest's -rf summary; both FAILED and ERROR
    count, and the trailing ' - <message>' must be stripped."""
    tail = (
        "FAILED tests/test_x.py::test_one - AssertionError: assert 1 == 2\n"
        "ERROR tests/test_x.py::test_two\n"
        "1 failed, 2 passed in 0.10s\n"
    )
    assert classify_failures._failed_names(tail) == [
        "tests/test_x.py::test_one", "tests/test_x.py::test_two",
    ]
    assert classify_failures._failed_names("3 passed in 0.01s") == []


def test_classname_resolves_to_the_source_file_not_the_class():
    """Grouping key must be the FILE — a class-scoped classname would otherwise
    split one file's failures across several groups."""
    assert junit_summary.Case("tests.test_alpha", "t", "failure").file == "tests/test_alpha.py"
    assert junit_summary.Case("tests.test_alpha.TestFoo", "t", "failure").file == "tests/test_alpha.py"
    assert junit_summary.Case("", "t", "error").file == "<unknown>"
