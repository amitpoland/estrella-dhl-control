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


def test_shards_are_size_balanced():
    """Greedy largest-first packing keeps shards within a wide but real bound;
    a wildly lopsided plan means one shard dominates the wall clock."""
    shards = shard_tests.partition(shard_tests.discover(), 6)
    sizes = [sum(f.stat().st_size for f in s) for s in shards]
    assert min(sizes) > 0
    assert max(sizes) <= min(sizes) * 1.5, f"shard sizes too uneven: {sizes}"


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
    make the shard plan wrong AND double-load the fixtures."""
    assert not any(p.name == "conftest.py" for p in shard_tests.discover())


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


def test_missing_shard_is_reported_against_the_expected_count(tmp_path):
    """Shard 2 of 2 never wrote an XML — the report must name it, not skip it."""
    (tmp_path / "junit-shard-1.xml").write_text(_GOOD_XML, encoding="utf-8")
    reports = [junit_summary.parse_report(p) for p in junit_summary.collect([str(tmp_path)])]
    text, ok = junit_summary.render(reports, expected_shards=2)
    assert not ok
    assert "MISSING" in text


def test_all_green_shards_produce_a_green_aggregate(tmp_path):
    green = _GOOD_XML.replace(
        '<testcase classname="tests.test_alpha" name="test_bad">'
        '<failure message="assert 1 == 2">x</failure></testcase>', "")
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
