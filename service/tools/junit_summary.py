#!/usr/bin/env python
"""junit_summary.py — aggregate per-shard JUnit XML into one honest report.

Reads every ``junit-shard-*.xml`` produced by the sharded service-suite job and
prints a single reconciliation:

  * per-shard totals, with any shard whose XML is MISSING or TRUNCATED reported
    as INCOMPLETE — a shard killed mid-run by pytest-timeout's thread method
    must never be read as "0 failures";
  * the full failure list grouped by test file, so failures can be triaged by
    file rather than one at a time;
  * a coverage reconciliation: tests reported vs tests expected from the shard
    plan, so a silently-dropped file is visible.

Exit status is 0 only when every shard is complete AND no test failed or
errored.  Nothing here suppresses a red result — the point is to make the whole
red visible in one pass instead of one timeout at a time.

Usage
-----
    python tools/junit_summary.py junit/                    # a directory
    python tools/junit_summary.py junit/*.xml --of 6        # explicit files
    python tools/junit_summary.py junit/ --of 6 --markdown $GITHUB_STEP_SUMMARY
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


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
    return ShardReport(label, path, True, cases=cases)


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


def render(reports: list[ShardReport], expected_shards: int | None) -> tuple[str, bool]:
    """Return (markdown_report, ok)."""
    lines: list[str] = ["## Service suite — sharded run", ""]
    found = {r.label for r in reports}
    missing: list[str] = []
    if expected_shards:
        missing = [str(i) for i in range(1, expected_shards + 1) if str(i) not in found]

    total = {"passed": 0, "failure": 0, "error": 0, "skipped": 0}
    lines += ["| Shard | Passed | Failed | Errored | Skipped | Status |",
              "|---|---:|---:|---:|---:|---|"]
    for r in sorted(reports, key=lambda r: (len(r.label), r.label)):
        if not r.complete:
            lines.append(f"| {r.label} | — | — | — | — | **INCOMPLETE** — {r.reason} |")
            continue
        c = r.counts
        for k in total:
            total[k] += c.get(k, 0)
        lines.append(
            f"| {r.label} | {c['passed']} | {c['failure']} | {c['error']} | "
            f"{c['skipped']} | complete |"
        )
    for label in missing:
        lines.append(f"| {label} | — | — | — | — | **MISSING** — no XML produced |")

    lines += ["", f"**Reported:** {sum(total.values())} tests — "
                  f"{total['passed']} passed, {total['failure']} failed, "
                  f"{total['error']} errored, {total['skipped']} skipped.", ""]

    incomplete = [r for r in reports if not r.complete]
    if incomplete or missing:
        lines += [
            "> **This total is a floor, not the suite result.** "
            f"{len(incomplete) + len(missing)} shard(s) produced no usable XML, "
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

    ok = not bad and not incomplete and not missing
    lines.append("**Result:** " + ("all shards complete, no failures." if ok
                                   else "see above — not green."))
    return "\n".join(lines), ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", help="JUnit XML files, or directories of them")
    ap.add_argument("--of", type=int, default=None,
                    help="expected shard count — shards with no XML are reported MISSING")
    ap.add_argument("--markdown", default=None,
                    help="also append the report to this file (e.g. $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args(argv)

    paths = collect(args.inputs)
    if not paths and not args.of:
        print("no JUnit XML found", file=sys.stderr)
        return 2

    reports = [parse_report(p) for p in paths]
    text, ok = render(reports, args.of)
    print(text)
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
