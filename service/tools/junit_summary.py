#!/usr/bin/env python
"""junit_summary.py — aggregate per-shard JUnit XML into one honest report.

Reads every ``junit-shard-*.xml`` produced by the sharded service-suite job and
prints a single reconciliation:

  * per-shard **evidence states** (never silent zero failures):
      COMPLETE | TEST_FAILURE | PROCESS_KILLED | STEP_TIMEOUT |
      MALFORMED_XML | MISSING_ARTIFACT | CANCELLED/UNKNOWN
  * the full failure list grouped by test file;
  * self-consistency checks (empty suite / short count / truncated XML).

Exit status (``--fail-on``)
---------------------------
  * ``any`` (default, local triage): exit 1 on incomplete evidence OR any
    failed/errored test.
  * ``incomplete`` (forensic): exit 1 only on MISSING / MALFORMED evidence;
    inherited test failures do not fail the process.
  * ``never`` (Actions diagnostic CI): **always exit 0** after printing the
    report. Diagnostic findings (inherited reds, killed shards, missing
    artifacts) stay visible in the summary but must not produce the recurring
    ``Process completed with exit code 1`` loop. CI is not a deploy gate —
    see CLAUDE.md § "CI authority — diagnostic, never a gate".

Nothing here suppresses a red result in the report — the point is to make the
whole red visible in one pass without turning diagnostic conditions into a
merge/deploy-style red gate.

Usage
-----
    python tools/junit_summary.py junit/ --of 6
    python tools/junit_summary.py junit/ --of 6 --fail-on never --markdown $GITHUB_STEP_SUMMARY
    python tools/junit_summary.py junit/ --of 6 --fail-on incomplete   # local forensic
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Evidence-state vocabulary (aggregate Status column). Keep stable — tests pin it.
STATE_COMPLETE = "COMPLETE"
STATE_TEST_FAILURE = "TEST_FAILURE"
STATE_PROCESS_KILLED = "PROCESS_KILLED"
STATE_STEP_TIMEOUT = "STEP_TIMEOUT"
STATE_MALFORMED_XML = "MALFORMED_XML"
STATE_MISSING_ARTIFACT = "MISSING_ARTIFACT"
STATE_CANCELLED_UNKNOWN = "CANCELLED/UNKNOWN"

# Imported lazily-safe constants from ensure_junit_artifact (same directory).
try:
    from ensure_junit_artifact import (  # type: ignore
        SENTINEL_CLASS,
        SENTINEL_NAMES,
        REASON_PROCESS_KILLED,
        REASON_STEP_TIMEOUT,
        REASON_EMPTY,
    )
except ImportError:  # pragma: no cover — running as a script with sibling import
    SENTINEL_CLASS = "ci.shard_evidence"
    SENTINEL_NAMES = {
        "PROCESS_KILLED": "process_exited_without_junit_xml",
        "STEP_TIMEOUT": "step_timed_out_without_junit_xml",
        "EMPTY_JUNIT": "empty_junit_normalized",
    }
    REASON_PROCESS_KILLED = "PROCESS_KILLED"
    REASON_STEP_TIMEOUT = "STEP_TIMEOUT"
    REASON_EMPTY = "EMPTY_JUNIT"


@dataclass
class Case:
    classname: str
    name: str
    status: str          # "failure" | "error" | "skipped" | "passed"
    message: str = ""

    @property
    def file(self) -> str:
        """Source file recovered from the JUnit classname.

        pytest writes the dotted module path, with any enclosing test class
        appended: ``tests.test_alpha`` or ``tests.test_alpha.TestFoo``.  Trailing
        class components (conventionally capitalised) are dropped so failures
        group by FILE — grouping by class would scatter one file's failures.
        """
        if not self.classname:
            return "<unknown>"
        parts = self.classname.split(".")
        while len(parts) > 1 and parts[-1][:1].isupper():
            parts.pop()
        return "/".join(parts) + ".py"

    @property
    def nodeid(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name


@dataclass
class ShardReport:
    label: str
    path: Path | None
    complete: bool
    reason: str = ""
    cases: list[Case] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {"passed": 0, "failure": 0, "error": 0, "skipped": 0}
        for c in self.cases:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    @property
    def bad(self) -> list[Case]:
        return [c for c in self.cases if c.status in ("failure", "error")]


def _shard_label(path: Path) -> str:
    stem = path.stem
    for token in stem.replace("-", "_").split("_"):
        if token.isdigit():
            return token
    return stem


def parse_report(path: Path) -> ShardReport:
    """Parse one JUnit XML, tolerating the truncation a hard-killed run leaves."""
    label = _shard_label(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return ShardReport(label, path, False, f"unreadable: {exc}")
    if not raw.strip():
        return ShardReport(label, path, False, "empty file (shard died before writing)")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        # pytest writes the XML at session end; a truncated document means the
        # process was killed mid-write — the shard's results are unknowable.
        return ShardReport(label, path, False, f"truncated/invalid XML: {exc}")

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    cases: list[Case] = []
    for suite in suites:
        for tc in suite.iter("testcase"):
            status, message = "passed", ""
            for tag in ("failure", "error", "skipped"):
                node = tc.find(tag)
                if node is not None:
                    status = tag
                    message = (node.get("message") or "").strip().splitlines()[0][:200] \
                        if (node.get("message") or "").strip() else ""
                    break
            cases.append(Case(tc.get("classname", ""), tc.get("name", ""), status, message))

    # A well-formed document is not yet a trustworthy one. Both checks below
    # would otherwise pass as "complete, 0 failures" — a green verdict from a
    # shard that reported nothing.
    if not cases:
        return ShardReport(
            label, path, False,
            "parsed but contains no testcases (shard collected or ran nothing)",
        )

    # pytest declares its own total on <testsuite tests="N">. Fewer <testcase>
    # elements than N means the document was cut short after the header — it
    # parses, but part of the run is missing.
    declared = 0
    for suite in suites:
        try:
            declared += int(suite.get("tests", "0"))
        except ValueError:  # a non-numeric attribute is itself untrustworthy
            return ShardReport(label, path, False,
                               "non-numeric tests= attribute on <testsuite>")
    if declared > len(cases):
        return ShardReport(
            label, path, False,
            f"short count: <testsuite tests=\"{declared}\"> but {len(cases)} "
            f"testcase elements present",
        )

    return ShardReport(label, path, True, cases=cases)


def classify_state(report: ShardReport | None, *, missing: bool = False) -> str:
    """Map a shard report (or its absence) to the normalized evidence state."""
    if missing or report is None:
        return STATE_MISSING_ARTIFACT
    if not report.complete:
        # Empty / truncated / unparseable — never "zero failures".
        return STATE_MALFORMED_XML

    killed_names = {
        SENTINEL_NAMES.get(REASON_PROCESS_KILLED, "process_exited_without_junit_xml"),
        SENTINEL_NAMES.get(REASON_EMPTY, "empty_junit_normalized"),
    }
    timeout_name = SENTINEL_NAMES.get(
        REASON_STEP_TIMEOUT, "step_timed_out_without_junit_xml")

    for c in report.cases:
        if c.classname == SENTINEL_CLASS or c.classname.startswith("ci.shard"):
            if c.name == timeout_name:
                return STATE_STEP_TIMEOUT
            if c.name in killed_names or "without_junit" in c.name or "empty_junit" in c.name:
                return STATE_PROCESS_KILLED
            # Unknown sentinel variant — still not COMPLETE.
            return STATE_PROCESS_KILLED

    if report.bad:
        return STATE_TEST_FAILURE
    return STATE_COMPLETE


def collect(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.xml")))
        elif p.exists():
            paths.append(p)
    # De-duplicate while preserving order.
    seen, unique = set(), []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def render(
    reports: list[ShardReport],
    expected_shards: int | None,
    fail_on: str = "any",
) -> tuple[str, bool]:
    """Return (markdown_report, suite_green).

    ``suite_green`` is True only when every shard is COMPLETE (no failures,
    no evidence problems).  Process exit is controlled separately by
    ``exit_status()`` / ``--fail-on``.
    """
    if fail_on not in ("any", "incomplete", "never"):
        raise ValueError(
            f"fail_on must be 'any', 'incomplete', or 'never', got {fail_on!r}")

    lines: list[str] = ["## Service suite — sharded run", ""]
    found = {r.label: r for r in reports}
    missing: list[str] = []
    if expected_shards:
        missing = [str(i) for i in range(1, expected_shards + 1) if str(i) not in found]

    total = {"passed": 0, "failure": 0, "error": 0, "skipped": 0}
    state_counts: dict[str, int] = {}
    lines += ["| Shard | Passed | Failed | Errored | Skipped | Evidence state |",
              "|---|---:|---:|---:|---:|---|"]

    ordered_labels: list[str] = []
    if expected_shards:
        ordered_labels = [str(i) for i in range(1, expected_shards + 1)]
    else:
        ordered_labels = sorted(found.keys(), key=lambda x: (len(x), x))

    for label in ordered_labels:
        if label in missing:
            state = STATE_MISSING_ARTIFACT
            state_counts[state] = state_counts.get(state, 0) + 1
            lines.append(
                f"| {label} | — | — | — | — | **{state}** — no XML produced |")
            continue
        r = found[label]
        state = classify_state(r)
        state_counts[state] = state_counts.get(state, 0) + 1
        if not r.complete:
            lines.append(
                f"| {r.label} | — | — | — | — | **{state}** — {r.reason} |")
            continue
        c = r.counts
        for k in total:
            total[k] += c.get(k, 0)
        lines.append(
            f"| {r.label} | {c['passed']} | {c['failure']} | {c['error']} | "
            f"{c['skipped']} | **{state}** |"
        )

    # Any unexpected extra labels (not in 1..N) still show.
    for r in sorted(reports, key=lambda r: (len(r.label), r.label)):
        if expected_shards and r.label in ordered_labels:
            continue
        if not expected_shards:
            continue
        state = classify_state(r)
        state_counts[state] = state_counts.get(state, 0) + 1
        c = r.counts if r.complete else None
        if c is None:
            lines.append(
                f"| {r.label} | — | — | — | — | **{state}** — {r.reason} |")
        else:
            lines.append(
                f"| {r.label} | {c['passed']} | {c['failure']} | {c['error']} | "
                f"{c['skipped']} | **{state}** |"
            )

    lines += ["", f"**Reported:** {sum(total.values())} tests — "
                  f"{total['passed']} passed, {total['failure']} failed, "
                  f"{total['error']} errored, {total['skipped']} skipped.", ""]

    if state_counts:
        parts = [f"{k}×{v}" for k, v in sorted(state_counts.items())]
        lines += [f"**Evidence states:** {', '.join(parts)}.", ""]

    incomplete = [r for r in reports if not r.complete]
    shards_parseable = not incomplete and not missing
    if not shards_parseable:
        lines += [
            "> **This total is a floor, not the suite result.** "
            f"{len(incomplete) + len(missing)} shard(s) have "
            f"{STATE_MALFORMED_XML}/{STATE_MISSING_ARTIFACT} evidence, "
            "so their tests are neither passed nor failed — they are unknown. "
            "Re-run those shards before treating any count as a baseline.",
            "",
        ]

    bad: list[Case] = [c for r in reports if r.complete for c in r.bad]
    if bad:
        by_file: dict[str, list[Case]] = {}
        for c in bad:
            by_file.setdefault(c.file, []).append(c)
        lines += [f"### Failures by file ({len(bad)} in {len(by_file)} files)", ""]
        for f in sorted(by_file, key=lambda k: (-len(by_file[k]), k)):
            cases = by_file[f]
            lines.append(f"<details><summary><code>{f}</code> — {len(cases)}</summary>")
            lines.append("")
            for c in sorted(cases, key=lambda c: c.name):
                suffix = f" — {c.message}" if c.message else ""
                lines.append(f"- `{c.name}` [{c.status}]{suffix}")
            lines += ["", "</details>", ""]

    suite_green = (
        shards_parseable
        and not bad
        and all(classify_state(r) == STATE_COMPLETE for r in reports)
        and not missing
    )
    if suite_green:
        result = "all shards COMPLETE, no failures."
    elif fail_on == "never":
        result = (
            f"diagnostic report only — workflow exit 0 "
            f"({total['failure']} failed, {total['error']} errored; "
            f"states: {', '.join(f'{k}×{v}' for k, v in sorted(state_counts.items()))})."
        )
    elif shards_parseable and fail_on == "incomplete":
        result = (
            f"all shards parseable — forensic report "
            f"({total['failure']} failed, {total['error']} errored; "
            f"job exit follows --fail-on incomplete)."
        )
    else:
        result = "see above — not green."
    lines.append("**Result:** " + result)
    return "\n".join(lines), suite_green


def exit_status(reports: list[ShardReport], expected_shards: int | None,
                fail_on: str = "any") -> int:
    """Map an aggregate to a process exit code.

    ``fail_on="any"`` — incomplete evidence OR any failed/errored test → 1.
    ``fail_on="incomplete"`` — only MISSING/MALFORMED evidence → 1.
    ``fail_on="never"`` — always 0 (Actions diagnostic CI).
    """
    if fail_on not in ("any", "incomplete", "never"):
        raise ValueError(
            f"fail_on must be 'any', 'incomplete', or 'never', got {fail_on!r}")
    if fail_on == "never":
        return 0

    found = {r.label for r in reports}
    missing: list[str] = []
    if expected_shards:
        missing = [str(i) for i in range(1, expected_shards + 1) if str(i) not in found]
    if any(not r.complete for r in reports) or missing:
        return 1
    if fail_on == "incomplete":
        return 0
    bad = [c for r in reports for c in r.bad]
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", help="JUnit XML files, or directories of them")
    ap.add_argument("--of", type=int, default=None,
                    help="expected shard count — shards with no XML are MISSING_ARTIFACT")
    ap.add_argument(
        "--fail-on",
        choices=("any", "incomplete", "never"),
        default="any",
        help=(
            "exit 1 when: 'any' = incomplete or failed tests (default); "
            "'incomplete' = only missing/malformed XML; "
            "'never' = always 0 (Actions diagnostic CI)"
        ),
    )
    ap.add_argument("--markdown", default=None,
                    help="also append the report to this file (e.g. $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args(argv)

    paths = collect(args.inputs)
    if not paths and not args.of:
        print("no JUnit XML found", file=sys.stderr)
        # Even 'never' cannot invent a report from zero inputs and no --of;
        # treat as a tool invocation error (infrastructure), not a suite red.
        return 2 if args.fail_on != "never" else 0

    reports = [parse_report(p) for p in paths]
    text, _suite_green = render(reports, args.of, fail_on=args.fail_on)
    print(text)
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return exit_status(reports, args.of, fail_on=args.fail_on)


if __name__ == "__main__":
    raise SystemExit(main())
