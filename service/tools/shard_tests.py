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

Each file is assigned to ``sha256(relative posix path) % of``.  A file's shard
therefore depends on its OWN path and nothing else: same path in, same shard out,
on every runner, every OS, and every run.

This replaced greedy largest-first bin packing.  Packing balanced shard sizes
better, but membership was a function of the WHOLE listing — adding, deleting, or
merely growing one file re-sorted the size ordering and could move an arbitrary
number of unrelated files into different shards.  That silently destroys the
comparison this suite is triaged by: "shard 4 failed the same 3 files it failed
last run" is only meaningful while shard 4 still means the same set of files.
Hash assignment keeps every other file exactly where it was.

The cost is honest and accepted: shards are balanced only in the statistical
sense, so the wall clock of the slowest shard will vary more than under packing.
Runtime is bounded by the job's own ``timeout-minutes``, whereas a reshuffled
partition produces wrong conclusions with no warning at all.

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
import hashlib
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = SERVICE_ROOT / "tests"


def _rel(p: Path, root: Path = SERVICE_ROOT) -> str:
    """The hash key and the sort key: a path relative to *root*, POSIX-style.

    Relative and POSIX are both load-bearing. An absolute path differs per
    checkout (``C:\\PZ-verify`` vs ``/home/runner/work/...``) and a backslash
    path differs per OS — either one would give each runner a different
    partition for the same tree.
    """
    return p.relative_to(root).as_posix()


def discover(tests_dir: Path = TESTS_DIR, root: Path = SERVICE_ROOT) -> list[Path]:
    """Every collectable test file, in a stable OS-independent order.

    Both of pytest's default ``python_files`` patterns are globbed — ``test_*.py``
    AND ``*_test.py``. Matching only the first would mean a ``*_test.py`` file is
    collected by a local ``pytest tests/`` and by the deploy-gate subsets, but
    belongs to no shard: it runs everywhere except the job that reports the
    verdict, and nothing says so. ``service/pytest.ini`` sets no ``python_files``
    override, so these two patterns are the contract to match.

    Sorted by the POSIX-style relative path so Windows and Linux agree.

    The ``conftest.py`` exclusion is defensive, not active: that name matches
    neither pattern today, so the filter never fires. It is kept because pytest
    loads conftest implicitly for whichever files run, so listing it as a shard
    target would both break the plan and double-load the fixtures — and this
    glob is exactly the kind of thing a later change widens.
    """
    seen: set[Path] = set()
    for pattern in ("test_*.py", "*_test.py"):
        for p in tests_dir.rglob(pattern):
            if p.is_file() and p.name != "conftest.py":
                seen.add(p)
    return sorted(seen, key=lambda p: _rel(p, root))


def assign(path: Path, of: int, root: Path = SERVICE_ROOT) -> int:
    """The 0-based shard index owning *path*.

    sha256 of the POSIX-relative path, taken modulo *of*.  Deliberately NOT the
    built-in ``hash()``: that is salted per process (PYTHONHASHSEED), so two
    runners would compute different partitions — some files running twice while
    others never run at all, with nothing in the output to reveal it.
    """
    if of < 1:
        raise ValueError("--of must be >= 1")
    digest = hashlib.sha256(_rel(path, root).encode("utf-8")).hexdigest()
    return int(digest, 16) % of


def partition(files: list[Path], of: int,
              root: Path = SERVICE_ROOT) -> list[list[Path]]:
    """Group *files* into *of* shards by ``assign()``.

    Each file's shard depends only on its own path, so the plan is stable under
    churn elsewhere in the tree: adding or deleting a file moves that file alone.
    Shards are emitted in collection order.
    """
    if of < 1:
        raise ValueError("--of must be >= 1")
    shards: list[list[Path]] = [[] for _ in range(of)]
    for f in files:
        shards[assign(f, of, root)].append(f)
    return [sorted(s, key=lambda p: _rel(p, root)) for s in shards]


def shard_files(shard: int, of: int, tests_dir: Path = TESTS_DIR,
                root: Path = SERVICE_ROOT) -> list[Path]:
    """The files belonging to *shard* (1-based) of *of*."""
    if not 1 <= shard <= of:
        raise ValueError(f"--shard must be in 1..{of}, got {shard}")
    return partition(discover(tests_dir, root), of, root)[shard - 1]


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
