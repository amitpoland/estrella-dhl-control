"""
test_dhl_auto_scan.py
======================
Source-grep + structural tests for DHL automation Lane A (PR #456).

Lane B (follow-up automation) tests are in PR #457 and will be
added after Lane A has run cleanly for one production cycle.

Coverage:
  A. Lane A /scheduled-inbox-check
     - endpoint registered, kill switch, AWB exclusion, _is_active,
       ingestion cycle, cache apply, B2 trigger, structured summary

  B. Config kill switch
     - dhl_auto_scan_enabled (default True)

  C. PowerShell script (Lane A only)
     - endpoint called, API key from .env, no hardcoded credentials, logging

  D. Safety
     - no financial writes, no wFirma, carrier_arrived mapping preserved
"""
from __future__ import annotations

import re
from pathlib import Path

_ROUTE   = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"
_CONFIG  = Path(__file__).parent.parent / "app" / "core" / "config.py"
_SCRIPT  = Path(__file__).parent.parent / "scripts" / "dhl-email-auto-scan.ps1"


def _lane_a(src: str) -> str:
    """Extract Lane A function body."""
    idx = src.index("scheduled-inbox-check")
    end = src.find("\n@router.", idx)
    return src[idx:end] if end > idx else src[idx:]


# ══════════════════════════════════════════════════════════════════════════════
# A. Lane A — /scheduled-inbox-check
# ══════════════════════════════════════════════════════════════════════════════

def test_lane_a_endpoint_registered():
    assert "scheduled-inbox-check" in _ROUTE.read_text(encoding="utf-8", errors="replace")


def test_lane_a_kill_switch_present_before_loop():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_a(src)
    assert "dhl_auto_scan_enabled" in block
    assert block.index("dhl_auto_scan_enabled") < block.index("_audit_paths")


def test_lane_a_kill_switch_returns_skip_dict():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "DHL_AUTO_SCAN_ENABLED=false" in _lane_a(src)


def test_lane_a_excludes_awb_5665916826():
    """AWB 5665916826 must be in the exclusion list."""
    assert "5665916826" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_skipped_excluded_counter():
    assert "skipped_excluded" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_checks_is_active():
    block = _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "_batch_active" in block or "_is_active" in block


def test_lane_a_calls_ingestion_cycle():
    block = _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "run_ingestion_cycle" in block or "_run_ing" in block


def test_lane_a_applies_cache():
    assert "_apply_cache_to_audit" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_triggers_b2():
    assert "_ensure_dhl_reply" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_returns_b2_sent():
    assert "b2_sent" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_has_lane_label():
    block = _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert '"lane"' in block and '"A"' in block


def test_lane_b_not_in_this_pr():
    """Lane B endpoint must NOT be present — deferred to PR #457."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "scheduled-followup-check" not in src, (
        "Lane B (scheduled-followup-check) must not be in PR #456 — "
        "it belongs in PR #457, deployed after Lane A is verified"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B. Config kill switch
# ══════════════════════════════════════════════════════════════════════════════

def test_config_dhl_auto_scan_enabled_defaults_true():
    src = _CONFIG.read_text(encoding="utf-8", errors="replace")
    assert "dhl_auto_scan_enabled" in src
    idx = src.index("dhl_auto_scan_enabled")
    assert "True" in src[idx:idx+80]


# ══════════════════════════════════════════════════════════════════════════════
# C. PowerShell script (Lane A only)
# ══════════════════════════════════════════════════════════════════════════════

def test_script_exists():
    assert _SCRIPT.exists()


def test_script_calls_lane_a():
    assert "scheduled-inbox-check" in _SCRIPT.read_text(encoding="utf-8", errors="replace")


def test_script_does_not_call_lane_b():
    """Lane B endpoint must NOT be in the PR #456 script."""
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "scheduled-followup-check" not in src, (
        "Lane B call must not be in the PR #456 script — "
        "it belongs in PR #457"
    )


def test_script_reads_api_key_from_env():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert ".env" in src and "API_KEY" in src


def test_script_no_hardcoded_credentials():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert len(re.findall(r'"[A-Za-z0-9_\-]{40,}"', src)) == 0


def test_script_has_logging():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert ".log" in src or "Write-Log" in src


# ══════════════════════════════════════════════════════════════════════════════
# D. Safety
# ══════════════════════════════════════════════════════════════════════════════

def test_lane_a_no_financial_writes():
    block = _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    for t in ["total_value", "cif_", "duty_", "freight_", "proforma"]:
        assert t not in block.lower()


def test_lane_a_no_wfirma():
    assert "wfirma" not in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace")).lower()


def test_carrier_arrived_mapping_preserved():
    classifier = Path(__file__).parent.parent / "app" / "services" / "email_classifier.py"
    src = classifier.read_text(encoding="utf-8", errors="replace")
    assert '"dhl_arrival":         "carrier_arrived"' in src
