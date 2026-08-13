#!/usr/bin/env python
"""ensure_junit_artifact.py — always leave a usable JUnit XML for CI upload.

pytest-timeout's ``thread`` method ends a hung run with ``os._exit``, which
skips atexit handlers — including the junitxml plugin's session-end write.
A GitHub Actions step-level timeout similarly kills the pytest step before
session-end. Either way the shard job can finish without a JUnit file.

This tool runs *after* the pytest step (``if: always() && !cancelled()``).
If the expected ``junit-shard-N.xml`` is already present and non-empty, it is
left alone. If it is absent or empty, a well-formed one-case error report is
written so:

  * the upload step has a file when the job survived;
  * the aggregate can classify the shard as PROCESS_KILLED / STEP_TIMEOUT
    (never as a silent zero-failure suite);
  * diagnostic CI does not go MISSING-red merely because pytest crashed.

Runner cancellation (``cancelled()``) skips this step on purpose — do not
invent evidence after the runner is gone.

Usage
-----
    python tools/ensure_junit_artifact.py junit-shard-6.xml --shard 6
    python tools/ensure_junit_artifact.py junit-shard-6.xml --shard 6 \\
        --reason STEP_TIMEOUT
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

# Stable node ids so triage / set-difference / aggregate state classification
# can recognise sentinels without guessing from free-text messages.
SENTINEL_CLASS = "ci.shard_evidence"

REASON_PROCESS_KILLED = "PROCESS_KILLED"
REASON_STEP_TIMEOUT = "STEP_TIMEOUT"
REASON_EMPTY = "EMPTY_JUNIT"

_VALID_REASONS = (REASON_PROCESS_KILLED, REASON_STEP_TIMEOUT, REASON_EMPTY)

SENTINEL_NAMES = {
    REASON_PROCESS_KILLED: "process_exited_without_junit_xml",
    REASON_STEP_TIMEOUT: "step_timed_out_without_junit_xml",
    REASON_EMPTY: "empty_junit_normalized",
}

SENTINEL_MESSAGES = {
    REASON_PROCESS_KILLED: (
        "pytest exited without writing JUnit XML "
        "(typically pytest-timeout thread method os._exit on a hung test). "
        "Prior cases in this shard are unknown; this sentinel replaces MISSING."
    ),
    REASON_STEP_TIMEOUT: (
        "GitHub Actions step timeout killed the pytest step before JUnit XML "
        "was written. Prior cases in this shard are unknown; this sentinel "
        "replaces MISSING."
    ),
    REASON_EMPTY: (
        "JUnit XML path existed but was empty; normalized to an explicit "
        "error sentinel so the aggregate never treats empty as zero failures."
    ),
}

# Back-compat alias used by older pins / docs.
SENTINEL_NAME = SENTINEL_NAMES[REASON_PROCESS_KILLED]
SENTINEL_MESSAGE = SENTINEL_MESSAGES[REASON_PROCESS_KILLED]


def _sentinel_xml(shard: str, reason: str) -> str:
    if reason not in _VALID_REASONS:
        raise ValueError(f"unknown reason {reason!r}; expected one of {_VALID_REASONS}")
    name = SENTINEL_NAMES[reason]
    msg = html.escape(SENTINEL_MESSAGES[reason], quote=True)
    shard_e = html.escape(shard, quote=True)
    reason_e = html.escape(reason, quote=True)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<testsuites>"
        f'<testsuite name="pytest" tests="1" failures="0" errors="1" '
        f'skipped="0" shard="{shard_e}" evidence_state="{reason_e}">'
        f'<testcase classname="{SENTINEL_CLASS}" name="{name}">'
        f'<error message="{msg}">shard {html.escape(shard)} state={reason_e}; '
        "see ensure_junit_artifact.py</error>"
        "</testcase>"
        "</testsuite></testsuites>\n"
    )


def ensure(path: Path, shard: str, reason: str = REASON_PROCESS_KILLED) -> bool:
    """Return True if a sentinel was written, False if an existing file was kept."""
    if path.is_file() and path.stat().st_size > 0:
        return False
    # Empty file → EMPTY reason unless caller already chose STEP_TIMEOUT.
    if path.is_file() and path.stat().st_size == 0 and reason == REASON_PROCESS_KILLED:
        reason = REASON_EMPTY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_sentinel_xml(shard, reason), encoding="utf-8")
    return True


def infer_reason(pytest_outcome: str | None) -> str:
    """Map a GitHub step outcome to a sentinel reason.

    ``cancelled`` on the pytest step is the usual step-timeout signal when the
    job itself was not cancelled (ensure runs under ``!cancelled()``).
    ``failure`` covers os._exit / nonzero / crash with no XML.
    """
    if (pytest_outcome or "").lower() == "cancelled":
        return REASON_STEP_TIMEOUT
    return REASON_PROCESS_KILLED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="path to junit-shard-N.xml")
    ap.add_argument("--shard", required=True, help="shard label for the sentinel")
    ap.add_argument(
        "--reason",
        choices=_VALID_REASONS,
        default=None,
        help="explicit evidence state (default: infer from --pytest-outcome)",
    )
    ap.add_argument(
        "--pytest-outcome",
        default="",
        help="GitHub steps.<id>.outcome — used when --reason is omitted",
    )
    args = ap.parse_args(argv)

    reason = args.reason or infer_reason(args.pytest_outcome)
    path = Path(args.path)
    wrote = ensure(path, str(args.shard), reason=reason)
    if wrote:
        print(f"wrote {reason} sentinel for shard {args.shard}: {path}")
    else:
        print(f"kept existing JUnit: {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
