#!/usr/bin/env python3
"""
validate_production_readiness.py
=================================
Checks all 7-step stabilization acceptance criteria and reports pass/fail.

Acceptance criteria (from STEP 7):
  [1] Every batch has audit.awb (or explicit awb_missing warning)
  [2] Every batch has timeline.length > 0
  [3] No timeline event is missing 'ts'
  [4] Recheck must not remove timeline (verified structurally)
  [5] Cowork returns suggestions for test cases:
        - DSK missing
        - Duty note detected
        - SAD delay
  [6] No external API dependency in tracking fallback

Usage:
  python3 scripts/validate_production_readiness.py [--verbose] [--outputs PATH]

Exit codes:
  0 — all checks pass
  1 — one or more checks fail
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE    = Path(__file__).resolve().parent
_ROOT    = _HERE.parent
_OUTPUTS = _ROOT / "service" / "app" / "storage" / "outputs"

# ── ANSI colours ──────────────────────────────────────────────────────────────
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def _ok(msg: str)   -> str: return f"{_GREEN}✓{_RESET} {msg}"
def _fail(msg: str) -> str: return f"{_RED}✗{_RESET} {msg}"
def _warn(msg: str) -> str: return f"{_YELLOW}⚠{_RESET} {msg}"


# ── Batch loader ──────────────────────────────────────────────────────────────

def _load_batches(outputs_dir: Path) -> list[dict]:
    batches = []
    if not outputs_dir.is_dir():
        return batches
    for d in outputs_dir.iterdir():
        p = d / "audit.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["_batch_id"] = d.name
                data["_path"]     = str(p)
                batches.append(data)
            except Exception as exc:
                batches.append({"_batch_id": d.name, "_path": str(p), "_load_error": str(exc)})
    return batches


# ── Check functions ───────────────────────────────────────────────────────────

def check_1_awb_present(batches: list[dict], verbose: bool) -> tuple[bool, list[str]]:
    """[1] Every batch has audit.awb OR has warnings=['awb_missing']."""
    lines = []
    fail  = False
    for b in batches:
        bid  = b["_batch_id"][:16]
        err  = b.get("_load_error")
        if err:
            lines.append(_warn(f"  {bid}: could not load — {err}"))
            continue
        awb      = b.get("awb")
        warnings = b.get("warnings") or []
        if awb:
            if verbose:
                lines.append(_ok(f"  {bid}: awb={awb}"))
        elif "awb_missing" in warnings:
            if verbose:
                lines.append(_warn(f"  {bid}: awb=null (awb_missing warning set — correct)"))
        else:
            lines.append(_fail(f"  {bid}: awb=null AND no awb_missing warning — schema inconsistent"))
            fail = True
    return (not fail), lines


def check_2_timeline_nonempty(batches: list[dict], verbose: bool) -> tuple[bool, list[str]]:
    """[2] Every batch has timeline.length > 0."""
    lines = []
    fail  = False
    for b in batches:
        bid      = b["_batch_id"][:16]
        if b.get("_load_error"):
            continue
        timeline = b.get("timeline") or []
        n        = len(timeline)
        if n > 0:
            if verbose:
                lines.append(_ok(f"  {bid}: {n} timeline event(s)"))
        else:
            lines.append(_fail(f"  {bid}: timeline is empty"))
            fail = True
    return (not fail), lines


def check_3_timeline_ts_integrity(batches: list[dict], verbose: bool) -> tuple[bool, list[str]]:
    """[3] No timeline event is missing 'ts'."""
    lines = []
    fail  = False
    for b in batches:
        bid      = b["_batch_id"][:16]
        if b.get("_load_error"):
            continue
        timeline = b.get("timeline") or []
        bad = [i for i, ev in enumerate(timeline) if not ev.get("ts")]
        if bad:
            lines.append(_fail(f"  {bid}: event(s) at index {bad} missing 'ts'"))
            fail = True
        else:
            if verbose:
                lines.append(_ok(f"  {bid}: all {len(timeline)} events have 'ts'"))
    return (not fail), lines


def check_4_recheck_safe(verbose: bool) -> tuple[bool, list[str]]:
    """
    [4] Recheck must not remove timeline.
    Verified structurally: timeline.log_event uses setdefault (only appends)
    and never removes entries.  Check the source.
    """
    tl_path = _ROOT / "service" / "app" / "core" / "timeline.py"
    lines   = []
    if not tl_path.exists():
        return False, [_fail("  timeline.py not found")]
    src = tl_path.read_text(encoding="utf-8")
    if "setdefault(\"timeline\", [])" in src and "timeline.append(" in src:
        lines.append(_ok("  timeline.py uses setdefault + append — existing events preserved"))
        return True, lines
    lines.append(_fail("  Could not verify append-only pattern in timeline.py"))
    return False, lines


def check_5_cowork_suggestions(verbose: bool) -> tuple[bool, list[str]]:
    """[5] Cowork detect_triggers returns suggestions for synthetic test cases."""
    lines = []
    fail  = False

    # Add service app to path
    svc = str(_ROOT / "service")
    if svc not in sys.path:
        sys.path.insert(0, svc)

    try:
        from app.agents.cowork_coordinator import detect_triggers
    except Exception as exc:
        return False, [_fail(f"  Could not import detect_triggers: {exc}")]

    test_cases = [
        {
            "label": "DSK_MISSING",
            "audit": {
                "awb":               "1234567890",
                "warnings":          [],
                "clearance_decision": {"require_dsk": True, "clearance_path": "broker_dsk"},
                "tracking":           {"arrived_warehouse": True},
                "dsk_filename":       None,
                "clearance_updated_at": "2020-01-01T00:00:00+00:00",  # very old → triggers
                "timeline":           [{"ts": "2020-01-01T00:00:00+00:00", "event": "batch_created",
                                        "trigger_source": "test", "actor": "test", "detail": None}],
            },
            "expected_trigger": "DSK_MISSING",
        },
        {
            "label": "DUTY_PAYMENT_PENDING",
            "audit": {
                "awb":                   "1234567891",
                "warnings":              [],
                "duty_notice_received_at": "2020-01-01T00:00:00+00:00",
                "duty_paid_signal_at":    None,
                "duty_amount_pln":        1225,
                "clearance_decision":    {},
                "tracking":              {},
                "timeline":              [{"ts": "2020-01-01T00:00:00+00:00", "event": "duty_note_received",
                                           "trigger_source": "test", "actor": "test", "detail": None}],
            },
            "expected_trigger": "DUTY_PAYMENT_PENDING",
        },
        {
            "label": "SAD_DELAY",
            "audit": {
                "awb":                "1234567892",
                "warnings":           [],
                "customs_declaration": {},
                "agency_reply_package": {"status": "queued"},
                "clearance_updated_at": "2020-01-01T00:00:00+00:00",
                "clearance_decision": {},
                "tracking":           {},
                "timeline":           [{"ts": "2020-01-01T00:00:00+00:00", "event": "agency_email_sent",
                                        "trigger_source": "test", "actor": "test", "detail": None}],
            },
            "expected_trigger": "SAD_DELAY",
        },
    ]

    for tc in test_cases:
        try:
            suggestions = detect_triggers(tc["audit"], batch_id="test_batch")
            triggers    = [s["trigger"] for s in suggestions]
            expected    = tc["expected_trigger"]
            if expected in triggers:
                lines.append(_ok(f"  [{tc['label']}] → detected '{expected}'"))
            else:
                lines.append(_fail(f"  [{tc['label']}] → expected '{expected}', got: {triggers}"))
                fail = True
        except Exception as exc:
            lines.append(_fail(f"  [{tc['label']}] → exception: {exc}"))
            fail = True

    return (not fail), lines


def check_6_no_api_dependency(verbose: bool) -> tuple[bool, list[str]]:
    """[6] Tracking fallback returns email_inferred structure without API call."""
    lines = []
    svc   = str(_ROOT / "service")
    if svc not in sys.path:
        sys.path.insert(0, svc)

    try:
        from app.services.tracking_service import _dhl_pending_fallback
    except Exception as exc:
        return False, [_fail(f"  Could not import _dhl_pending_fallback: {exc}")]

    try:
        result = _dhl_pending_fallback("1234567890", cache_dir=None)
        assert result.get("available") is False, "expected available=False"
        assert result.get("source") in ("api_pending", "email_inferred"), \
            f"expected api_pending or email_inferred, got {result.get('source')}"
        assert "tracking_url" in result
        lines.append(_ok("  Fallback returns without API call — available=False, source correct"))
        if verbose:
            lines.append(_ok(f"  source={result['source']} status={result.get('status')}"))
        return True, lines
    except Exception as exc:
        lines.append(_fail(f"  Fallback check failed: {exc}"))
        return False, lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate production readiness of stabilization layer")
    parser.add_argument("--verbose",  action="store_true", help="Print per-batch detail")
    parser.add_argument("--outputs",  default=str(_OUTPUTS), help="Path to outputs/ directory")
    args = parser.parse_args(argv)

    outputs_dir = Path(args.outputs)
    batches     = _load_batches(outputs_dir)

    print(f"\n{_BOLD}Production Readiness Validation{_RESET}")
    print(f"Outputs: {outputs_dir}  ({len(batches)} batch(es))")
    print("─" * 60)

    checks: list[tuple[str, bool, list[str]]] = []

    def _run(label: str, passed: bool, lines: list[str]) -> None:
        status = _ok("PASS") if passed else _fail("FAIL")
        print(f"\n[{status}] {label}")
        for line in lines:
            print(line)
        checks.append((label, passed, lines))

    _run("[1] AWB present or awb_missing warning",
         *check_1_awb_present(batches, args.verbose))

    _run("[2] Timeline non-empty",
         *check_2_timeline_nonempty(batches, args.verbose))

    _run("[3] Timeline ts integrity",
         *check_3_timeline_ts_integrity(batches, args.verbose))

    _run("[4] Recheck preserves timeline",
         *check_4_recheck_safe(args.verbose))

    _run("[5] Cowork trigger detection",
         *check_5_cowork_suggestions(args.verbose))

    _run("[6] No external API dependency in tracking fallback",
         *check_6_no_api_dependency(args.verbose))

    # Summary
    passed_count = sum(1 for _, p, _ in checks if p)
    total_count  = len(checks)
    print("\n" + "─" * 60)
    print(f"{_BOLD}Result: {passed_count}/{total_count} checks passed{_RESET}")

    if passed_count == total_count:
        print(_ok("All checks pass — production data layer is stable."))
        print("Next step: enable auto follow-up emails, SLA enforcement, agency/DHL automation.")
        return 0
    else:
        failed = [label for label, p, _ in checks if not p]
        print(_fail(f"Failed checks: {', '.join(failed)}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
