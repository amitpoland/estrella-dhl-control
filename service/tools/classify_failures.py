#!/usr/bin/env python
"""classify_failures.py — split a red suite into order contamination vs real.

The suite's failures are not one problem.  Triaging them one test at a time is
what makes a red baseline permanent: every session re-derives the same
distinction by hand and runs out of budget before fixing anything.

This automates the only split that can be made mechanically, and it is the one
that matters most:

    ISOLATED_FAIL   the file fails when run entirely alone.  Nothing else
                    caused it — the test and the code genuinely disagree.  This
                    is where stale source-grep pins, obsolete API contracts,
                    missing stub fields and real regressions live.  Fix the test
                    or fix the code; either way the work is local to one file.

    ORDER_CONTAMINATION
                    the file passes alone but failed in the aggregate run.  The
                    test is not wrong — an EARLIER file left process-global state
                    behind (a replaced settings singleton, an open database
                    handle, a patched module attribute, a live background
                    thread).  Fixing the test here is almost always the wrong
                    move: it hides a leak that will resurface elsewhere.

    RECOVERED       failed in the aggregate run and passes alone, with the whole
                    file green — same as order contamination, reported
                    separately when the aggregate failure list for the file is
                    empty (e.g. the file was killed mid-run rather than failing).

Isolation runs use a fresh interpreter per file, so no state can carry.

Usage
-----
    python tools/classify_failures.py junit/ --of 6 --out reports/triage.md
    python tools/classify_failures.py junit/ --limit 20        # sample first
    python tools/classify_failures.py junit/ --jobs 4          # parallel

Read the output as a work queue, not a verdict: ISOLATED_FAIL still needs a
human to decide whether the test or the code is wrong, and that decision is not
mechanical.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT / "tools"))

import junit_summary  # noqa: E402

ISOLATED_FAIL = "ISOLATED_FAIL"
ORDER_CONTAMINATION = "ORDER_CONTAMINATION"
RECOVERED = "RECOVERED"
UNRUNNABLE = "UNRUNNABLE"


@dataclass
class FileVerdict:
    file: str
    aggregate_failures: list[str]
    classification: str
    isolated_failures: list[str]
    detail: str = ""


def _run_isolated(rel_path: str, timeout: int) -> tuple[int, str]:
    """Run one test file in a fresh interpreter. Returns (returncode, tail)."""
    cmd = [sys.executable, "-m", "pytest", rel_path,
           "-p", "no:cacheprovider", "-q", "--no-header", "-rf"]
    try:
        proc = subprocess.run(
            cmd, cwd=SERVICE_ROOT, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"isolated run exceeded {timeout}s — the file hangs on its own"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, "\n".join(out.strip().splitlines()[-25:])


def _failed_names(tail: str) -> list[str]:
    names = []
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith(("FAILED ", "ERROR ")):
            names.append(line.split(" ", 1)[1].split(" - ")[0])
    return names


def classify(files: dict[str, list[str]], timeout: int, jobs: int) -> list[FileVerdict]:
    verdicts: list[FileVerdict] = []

    def work(item):
        rel, agg = item
        if not (SERVICE_ROOT / rel).exists():
            return FileVerdict(rel, agg, UNRUNNABLE, [], "file not found in the tree")
        rc, tail = _run_isolated(rel, timeout)
        isolated = _failed_names(tail)
        if rc == 124:
            return FileVerdict(rel, agg, UNRUNNABLE, [], tail)
        if rc == 0:
            return FileVerdict(rel, agg, ORDER_CONTAMINATION if agg else RECOVERED, [],
                               "green in isolation — an earlier file caused this")
        if rc == 5:
            return FileVerdict(rel, agg, UNRUNNABLE, [], "no tests collected")
        return FileVerdict(rel, agg, ISOLATED_FAIL, isolated,
                           "fails alone — test and code genuinely disagree")

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for v in pool.map(work, sorted(files.items())):
            verdicts.append(v)
            print(f"  {v.classification:20s} {v.file}", file=sys.stderr)
    return verdicts


def render(verdicts: list[FileVerdict]) -> str:
    order = [ORDER_CONTAMINATION, ISOLATED_FAIL, RECOVERED, UNRUNNABLE]
    buckets: dict[str, list[FileVerdict]] = {k: [] for k in order}
    for v in verdicts:
        buckets.setdefault(v.classification, []).append(v)

    lines = ["# Failure triage — aggregate run vs isolated run", "",
             "Each failing FILE from the sharded run was re-run alone in a fresh",
             "interpreter. The classification is mechanical; the repair decision is not.",
             "",
             "| Class | Files | Meaning |", "|---|---:|---|",
             f"| ORDER_CONTAMINATION | {len(buckets.get(ORDER_CONTAMINATION, []))} "
             "| passes alone — an earlier file leaked state; fix the LEAK, not this test |",
             f"| ISOLATED_FAIL | {len(buckets.get(ISOLATED_FAIL, []))} "
             "| fails alone — stale assertion, obsolete contract, or a real regression |",
             f"| RECOVERED | {len(buckets.get(RECOVERED, []))} "
             "| green alone, no aggregate failure list (killed mid-run) |",
             f"| UNRUNNABLE | {len(buckets.get(UNRUNNABLE, []))} "
             "| hangs, collects nothing, or is missing |",
             ""]

    for cls in order:
        group = buckets.get(cls) or []
        if not group:
            continue
        lines += [f"## {cls} ({len(group)} files)", ""]
        for v in sorted(group, key=lambda v: v.file):
            lines.append(f"### `{v.file}`")
            if v.aggregate_failures:
                lines.append(f"- aggregate run: {len(v.aggregate_failures)} failing — "
                             + ", ".join(f"`{n}`" for n in sorted(v.aggregate_failures)[:8])
                             + (" …" if len(v.aggregate_failures) > 8 else ""))
            if v.isolated_failures:
                lines.append(f"- isolated run: {len(v.isolated_failures)} failing — "
                             + ", ".join(f"`{n.split('::')[-1]}`"
                                         for n in v.isolated_failures[:8])
                             + (" …" if len(v.isolated_failures) > 8 else ""))
            if v.detail:
                lines.append(f"- {v.detail}")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", help="JUnit XML files or directories")
    ap.add_argument("--of", type=int, default=None, help="expected shard count")
    ap.add_argument("--limit", type=int, default=None,
                    help="classify only the first N failing files (sampling)")
    ap.add_argument("--jobs", type=int, default=4, help="parallel isolated runs")
    ap.add_argument("--timeout", type=int, default=600, help="per-file timeout (s)")
    ap.add_argument("--out", default=None, help="write the markdown report here")
    args = ap.parse_args(argv)

    reports = [junit_summary.parse_report(p)
               for p in junit_summary.collect(args.inputs)]
    incomplete = [r for r in reports if not r.complete]
    if incomplete:
        print(f"WARNING: {len(incomplete)} shard(s) incomplete — their files cannot "
              f"be triaged from this data", file=sys.stderr)

    failing: dict[str, list[str]] = {}
    for r in reports:
        for c in r.bad:
            failing.setdefault(c.file, []).append(c.name)
    if not failing:
        print("no failures to classify", file=sys.stderr)
        return 0

    selected = dict(sorted(failing.items())[: args.limit] if args.limit
                    else sorted(failing.items()))
    print(f"classifying {len(selected)} failing file(s) with {args.jobs} workers…",
          file=sys.stderr)
    verdicts = classify(selected, args.timeout, args.jobs)
    text = render(verdicts)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
