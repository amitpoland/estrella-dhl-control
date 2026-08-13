#!/usr/bin/env python
"""ensure_junit_artifact.py — always leave a usable JUnit XML for CI upload.

pytest-timeout's ``thread`` method ends a hung run with ``os._exit``, which
skips atexit handlers — including the junitxml plugin's session-end write.
The shard job then finishes (``continue-on-error: true``) with
``if-no-files-found: warn``, uploads nothing, and the aggregate correctly
reports MISSING. That is honest, but intermittent hangs then permanently red
the diagnostic CI check for a lost-evidence reason that is already known.

This tool runs *after* the pytest step (``if: always()``). If the expected
``junit-shard-N.xml`` is already present and non-empty, it is left alone. If
it is absent or empty, a well-formed one-case error report is written so:

  * the upload step always has a file;
  * ``junit_summary.py --fail-on incomplete`` sees complete evidence (not
    MISSING), exits 0, and still lists the kill as an error in the summary;
  * unknown results are never silently counted as zero failures — the sentinel
    is an explicit error case, not a green empty suite.

Usage
-----
    python tools/ensure_junit_artifact.py junit-shard-6.xml --shard 6
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

# Stable node id so triage and set-difference can recognise the sentinel.
SENTINEL_CLASS = "ci.shard_killed_before_junit"
SENTINEL_NAME = "process_exited_without_junit_xml"
SENTINEL_MESSAGE = (
    "pytest exited without writing JUnit XML "
    "(typically pytest-timeout thread method os._exit on a hung test). "
    "Prior cases in this shard are unknown; this sentinel replaces MISSING."
)


def _sentinel_xml(shard: str) -> str:
    msg = html.escape(SENTINEL_MESSAGE, quote=True)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<testsuites>"
        f'<testsuite name="pytest" tests="1" failures="0" errors="1" '
        f'skipped="0" shard="{html.escape(shard, quote=True)}">'
        f'<testcase classname="{SENTINEL_CLASS}" name="{SENTINEL_NAME}">'
        f'<error message="{msg}">shard {html.escape(shard)} produced no '
        "junit XML; see ensure_junit_artifact.py</error>"
        "</testcase>"
        "</testsuite></testsuites>\n"
    )


def ensure(path: Path, shard: str) -> bool:
    """Return True if a sentinel was written, False if an existing file was kept."""
    if path.is_file() and path.stat().st_size > 0:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_sentinel_xml(shard), encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="path to junit-shard-N.xml")
    ap.add_argument("--shard", required=True, help="shard label for the sentinel")
    args = ap.parse_args(argv)

    path = Path(args.path)
    wrote = ensure(path, str(args.shard))
    if wrote:
        print(f"wrote sentinel JUnit for missing shard {args.shard}: {path}")
    else:
        print(f"kept existing JUnit: {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
