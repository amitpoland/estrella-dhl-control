#!/usr/bin/env python
"""shard_tests.py — deterministic file-level partitioning of the service suite.

Why this exists
---------------
The service suite ran as ONE pytest process.  pytest-timeout's ``thread`` method
(pytest.ini: ``timeout_method = thread``) cannot interrupt a blocked C call, so
it terminates the whole process — one hung test therefore discards every result
after it.  A run that died at 77% reported a single timeout and hid the standing
failures in the remaining 23%, which is why "re-run" kept costing an hour and
still ended red without new information.

Sharding bounds that blast radius: a hang costs one shard's results, the other
shards still produce complete JUnit XML, and tools/junit_summary.py reports the
lost shard as INCOMPLETE instead of silently under-counting.

Partitioning
------------
Whole FILES, never individual tests — many files in this suite share module-level
fixtures and per-file database state, so splitting inside a file would invent
failures that do not exist.

Files are bin-packed greedily by size (largest first) into ``--of`` shards, which
tracks runtime better than round-robin without needing a recorded-durations file.
The result is a pure function of the file listing: same tree in, same partition
out, on every runner and every OS.

Cross-shard ordering caveat
---------------------------
Shards run in separate processes, so order-dependent failures WILL differ from
the monolithic run — a test that only fails after some earlier file polluted
global state may pass here, and vice versa.  That difference is diagnostic, not
noise: it is how order contamination gets separated from genuine regressions.
Compare a shard result against the same files run alone before calling anything
fixed.

Usage
-----
    python tools/shard_tests.py --shard 3 --of 6        # newline-separated paths
    python tools/shard_tests.py --shard 3 --of 6 --count
    python tools/shard_tests.py --of 6 --describe       # per-shard sizes

Paths are printed relative to ``service/`` with forward slashes, so the output
can be passed straight to pytest on Windows and POSIX alike.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = SERVICE_ROOT / "tests"


def discover(tests_dir: Path = TESTS_DIR) -> list[Path]:
    """Every collectable test file, in a stable OS-independent order.

    Sorted by the POSIX-style relative path so Windows and Linux agree; conftest
    is excluded because pytest loads it implicitly for whichever files run.
    """
    files = [
        p for p in tests_dir.rglob("test_*.py")
        if p.is_file() and p.name != "conftest.py"
    ]
    return sorted(files, key=lambda p: p.relative_to(SERVICE_ROOT).as_posix())


def partition(files: list[Path], of: int) -> list[list[Path]]:
    """Greedy largest-first bin packing into *of* shards.

    Deterministic: the sort key is (-size, posix path), so equal-sized files
    always land in the same order, and each file goes to the shard with the
    smallest accumulated size (ties broken by lowest shard index).
    """
    if of < 1:
        raise ValueError("--of must be >= 1")
    ordered = sorted(
        files,
        key=lambda p: (-p.stat().st_size, p.relative_to(SERVICE_ROOT).as_posix()),
    )
    shards: list[list[Path]] = [[] for _ in range(of)]
    weights = [0] * of
    for f in ordered:
        target = min(range(of), key=lambda i: (weights[i], i))
        shards[target].append(f)
        weights[target] += f.stat().st_size
    # Emit each shard in collection order, not packing order.
    return [
        sorted(s, key=lambda p: p.relative_to(SERVICE_ROOT).as_posix())
        for s in shards
    ]


def shard_files(shard: int, of: int, tests_dir: Path = TESTS_DIR) -> list[Path]:
    """The files belonging to *shard* (1-based) of *of*."""
    if not 1 <= shard <= of:
        raise ValueError(f"--shard must be in 1..{of}, got {shard}")
    return partition(discover(tests_dir), of)[shard - 1]


def _rel(p: Path) -> str:
    return p.relative_to(SERVICE_ROOT).as_posix()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shard", type=int, help="1-based shard index")
    ap.add_argument("--of", type=int, required=True, help="total shard count")
    ap.add_argument("--count", action="store_true", help="print the file count only")
    ap.add_argument("--describe", action="store_true",
                    help="print every shard's file count and total size")
    args = ap.parse_args(argv)

    if args.describe:
        shards = partition(discover(), args.of)
        for i, s in enumerate(shards, start=1):
            kb = sum(f.stat().st_size for f in s) / 1024
            print(f"shard {i}/{args.of}: {len(s):4d} files  {kb:9.1f} KiB")
        total = sum(len(s) for s in shards)
        print(f"total: {total} files across {args.of} shards")
        return 0

    if args.shard is None:
        ap.error("--shard is required unless --describe is given")

    files = shard_files(args.shard, args.of)
    if args.count:
        print(len(files))
        return 0
    if not files:
        # An empty shard is a configuration error (more shards than files), not
        # a silent pass — pytest would exit 5 "no tests collected" anyway.
        print(f"shard {args.shard}/{args.of} is empty", file=sys.stderr)
        return 1
    try:
        for f in files:
            print(_rel(f))
    except BrokenPipeError:  # `| head`, and similar
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
