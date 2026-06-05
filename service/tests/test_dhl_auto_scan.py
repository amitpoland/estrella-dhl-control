"""
test_dhl_auto_scan.py
======================
Source-grep + structural tests for DHL automation Lanes A and B,
kill switches, AWB exclusion, and the Task Scheduler PowerShell script.

Coverage:
  A. Lane A /scheduled-inbox-check
     - endpoint registered, kill switch, AWB exclusion, _is_active,
       ingestion cycle, cache apply, B2 trigger, structured summary

  B. Lane B /scheduled-followup-check
     - endpoint registered, kill switch, AWB exclusion, _is_active,
       skip when dhl_received, _process_dhl_followup, detect_tracking_triggers,
       followup_sent/stopped counters

  C. Config kill switches
     - dhl_auto_scan_enabled (default True)
     - dhl_followup_enabled (default False)

  D. PowerShell script
     - both lanes called, working hours check, API key from .env,
       no hardcoded credentials, logging, lanes independent

  E. Safety
     - no financial writes, no wFirma, carrier_arrived mapping preserved
"""
from __future__ import annotations

import re
from pathlib import Path

_ROUTE   = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"
_CONFIG  = Path(__file__).parent.parent / "app" / "core" / "config.py"
_SCRIPT  = Path(__file__).parent.parent / "scripts" / "dhl-email-auto-scan.ps1"


def _lane_a(src: str) -> str:
    idx = src.index("scheduled-inbox-check")
    end = src.find("\n@router.", idx)
    return src[idx:end] if end > idx else src[idx:]


def _lane_b(src: str) -> str:
    idx = src.index("scheduled-followup-check")
    end = src.find("\n@router.", idx)
    return src[idx:end] if end > idx else src[idx:]


# ══════════════════════════════════════════════════════════════════════════════
# A. Lane A
# ══════════════════════════════════════════════════════════════════════════════

def test_lane_a_endpoint_registered():
    assert "scheduled-inbox-check" in _ROUTE.read_text(encoding="utf-8", errors="replace")


def test_lane_a_kill_switch_present_before_loop():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_a(src)
    assert "dhl_auto_scan_enabled" in block
    assert block.index("dhl_auto_scan_enabled") < block.index("_audit_paths")


def test_lane_a_kill_switch_returns_skip_dict():
    """Kill switch must return a skip dict when disabled."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_a(src)
    # The skip string must appear somewhere in the block (may be past the docstring)
    assert "DHL_AUTO_SCAN_ENABLED=false" in block, (
        "Lane A kill switch must return {skipped: 'DHL_AUTO_SCAN_ENABLED=false'}"
    )


def test_lane_a_excludes_awb_5665916826():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "5665916826" in _lane_a(src)


def test_lane_a_skipped_excluded_counter():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "skipped_excluded" in _lane_a(src)


def test_lane_a_checks_is_active():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_a(src)
    assert "_batch_active" in block or "_is_active" in block


def test_lane_a_calls_ingestion_cycle():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_a(src)
    assert "run_ingestion_cycle" in block or "_run_ing" in block


def test_lane_a_applies_cache():
    assert "_apply_cache_to_audit" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_triggers_b2():
    assert "_ensure_dhl_reply" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_returns_b2_sent():
    assert "b2_sent" in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_a_has_lane_label():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_a(src)
    assert '"lane"' in block and '"A"' in block


# ══════════════════════════════════════════════════════════════════════════════
# B. Lane B
# ══════════════════════════════════════════════════════════════════════════════

def test_lane_b_endpoint_registered():
    assert "scheduled-followup-check" in _ROUTE.read_text(encoding="utf-8", errors="replace")


def test_lane_b_kill_switch_present_before_loop():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert "dhl_followup_enabled" in block
    assert block.index("dhl_followup_enabled") < block.index("_audit_paths")


def test_lane_b_kill_switch_returns_skip_dict():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    after = block[block.index("dhl_followup_enabled"):block.index("dhl_followup_enabled")+300]
    assert "DHL_FOLLOWUP_ENABLED=false" in after


def test_lane_b_excludes_awb_5665916826():
    assert "5665916826" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_checks_is_active():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert "_batch_active" in block or "_is_active" in block


def test_lane_b_skips_when_dhl_received_before_followup():
    """Lane B skipped_received counter must exist and the actual call must come after."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert "skipped_received" in block, "Lane B must track skipped_received"
    # Use actual call (not docstring) — "_process_dhl_followup(ap, audit" is unique
    actual_call_sig = "_process_dhl_followup(ap, audit"
    assert actual_call_sig in block, "Lane B must call _process_dhl_followup(ap, audit, ...)"
    # skipped_received must appear BEFORE the actual function call
    assert block.index("skipped_received") < block.index(actual_call_sig), (
        "skipped_received skip must precede the actual _process_dhl_followup call"
    )


def test_lane_b_calls_process_dhl_followup():
    assert "_process_dhl_followup" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_uses_detect_tracking_triggers():
    assert "detect_tracking_triggers" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_passes_customs_trigger():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert "_process_dhl_followup(ap, audit, customs_trigger)" in block


def test_lane_b_followup_sent_counter():
    assert "followup_sent" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_followup_stopped_counter():
    assert "followup_stopped" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_has_lane_label():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert '"lane"' in block and '"B"' in block


# ══════════════════════════════════════════════════════════════════════════════
# C. Config kill switches
# ══════════════════════════════════════════════════════════════════════════════

def test_config_dhl_auto_scan_enabled_defaults_true():
    src = _CONFIG.read_text(encoding="utf-8", errors="replace")
    assert "dhl_auto_scan_enabled" in src
    idx = src.index("dhl_auto_scan_enabled")
    assert "True" in src[idx:idx+80]


def test_config_dhl_followup_enabled_defaults_false():
    src = _CONFIG.read_text(encoding="utf-8", errors="replace")
    assert "dhl_followup_enabled" in src
    idx = src.index("dhl_followup_enabled")
    assert "False" in src[idx:idx+80]


def test_config_kill_switches_same_section():
    src = _CONFIG.read_text(encoding="utf-8", errors="replace")
    a_idx = src.index("dhl_auto_scan_enabled")
    b_idx = src.index("dhl_followup_enabled")
    assert abs(a_idx - b_idx) < 600


# ══════════════════════════════════════════════════════════════════════════════
# D. PowerShell script
# ══════════════════════════════════════════════════════════════════════════════

def test_script_exists():
    assert _SCRIPT.exists()


def test_script_calls_lane_a():
    assert "scheduled-inbox-check" in _SCRIPT.read_text(encoding="utf-8", errors="replace")


def test_script_calls_lane_b():
    assert "scheduled-followup-check" in _SCRIPT.read_text(encoding="utf-8", errors="replace")


def test_script_working_hours_gate_for_lane_b():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "WorkStart" in src or "working hours" in src.lower() or "WorkingHours" in src


def test_script_reads_api_key_from_env():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert ".env" in src and "API_KEY" in src


def test_script_no_hardcoded_credentials():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert len(re.findall(r'"[A-Za-z0-9_\-]{40,}"', src)) == 0


def test_script_has_logging():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert ".log" in src or "Write-Log" in src


def test_script_lane_a_before_lane_b():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert src.index("LaneAEndpoint") < src.index("LaneBEndpoint")


def test_script_no_hard_exit_between_lanes():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    a_idx = src.index("LaneAEndpoint")
    b_idx = src.index("LaneBEndpoint")
    assert "exit 1" not in src[a_idx:b_idx], "No hard exit between Lane A and Lane B"


# ══════════════════════════════════════════════════════════════════════════════
# E. Safety
# ══════════════════════════════════════════════════════════════════════════════

def test_lane_a_no_financial_writes():
    block = _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    for t in ["total_value", "cif_", "duty_", "freight_", "proforma"]:
        assert t not in block.lower()


def test_lane_b_no_financial_writes():
    block = _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    for t in ["total_value", "cif_", "duty_", "freight_", "proforma"]:
        assert t not in block.lower()


def test_lane_a_no_wfirma():
    assert "wfirma" not in _lane_a(_ROUTE.read_text(encoding="utf-8", errors="replace")).lower()


def test_lane_b_no_wfirma():
    assert "wfirma" not in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace")).lower()


def test_carrier_arrived_mapping_preserved():
    classifier = Path(__file__).parent.parent / "app" / "services" / "email_classifier.py"
    src = classifier.read_text(encoding="utf-8", errors="replace")
    assert '"dhl_arrival":         "carrier_arrived"' in src
