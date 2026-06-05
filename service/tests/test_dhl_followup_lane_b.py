"""
test_dhl_followup_lane_b.py — Lane B: DHL follow-up SLA automation.

All tests are source-grep or light functional tests. No emails are sent.
Kill switch dhl_followup_enabled defaults False — Lane B is dormant until
operator explicitly enables it.

Guard chain (all enforced inside _process_dhl_followup + dhl_followup_guard):
  1. dhl_followup_enabled kill switch (outer — this endpoint)
  2. DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP (inner — validate_followup_send_preconditions)
  3. _is_active(audit) — not delivered / terminal
  4. dhl_email.received != True — DHL hasn't replied yet
  5. customs_docs.received != True — docs not received
  6. customs_trigger from tracking events — shipment at customs stage
  7. 4h initial wait (calculate_first_followup_at)
  8. 1h repeat interval (calculate_next_followup_at)
  9. Working hours 08:00-16:00 Warsaw (dhl_followup_sla.is_due)
 10. Idempotency key per time slot (validate_followup_send_preconditions)
"""
from __future__ import annotations

import re
from pathlib import Path

_ROUTE  = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"
_CONFIG = Path(__file__).parent.parent / "app" / "core" / "config.py"
_SCRIPT = Path(__file__).parent.parent / "scripts" / "dhl-email-auto-scan.ps1"
_SLA    = Path(__file__).parent.parent / "app" / "services" / "dhl_followup_sla.py"
_GUARD  = Path(__file__).parent.parent / "app" / "services" / "dhl_followup_guard.py"


def _lane_b(src: str) -> str:
    idx = src.index("scheduled-followup-check")
    end = src.find("\n@router.", idx + 10)
    return src[idx:end] if end > idx else src[idx:]


# ══════════════════════════════════════════════════════════════════════════════
# A. Config kill switch
# ══════════════════════════════════════════════════════════════════════════════

def test_config_dhl_followup_enabled_present():
    assert "dhl_followup_enabled" in _CONFIG.read_text(encoding="utf-8", errors="replace")


def test_config_dhl_followup_enabled_defaults_false():
    """Lane B must default OFF — requires explicit operator opt-in."""
    src = _CONFIG.read_text(encoding="utf-8", errors="replace")
    idx = src.index("dhl_followup_enabled")
    assert "False" in src[idx:idx+80], (
        "dhl_followup_enabled must default to False — opt-in only"
    )


def test_config_dhl_followup_enabled_comment_mentions_inner_guard():
    """Config comment must mention that the inner guard is also required."""
    src = _CONFIG.read_text(encoding="utf-8", errors="replace")
    idx = src.index("dhl_followup_enabled")
    context = src[max(0, idx-500):idx+200]
    assert "DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP" in context, (
        "Config comment must explain that DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP "
        "is also required to actually send emails"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B. Endpoint structure
# ══════════════════════════════════════════════════════════════════════════════

def test_lane_b_endpoint_registered():
    assert "scheduled-followup-check" in _ROUTE.read_text(encoding="utf-8", errors="replace")


def test_lane_b_outer_kill_switch():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert "dhl_followup_enabled" in block
    assert block.index("dhl_followup_enabled") < block.index("_audit_paths")


def test_lane_b_returns_skip_dict_when_disabled():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b(src)
    assert "DHL_FOLLOWUP_ENABLED=false" in block


def test_lane_b_excludes_awb_5665916826():
    assert "5665916826" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_checks_is_active():
    block = _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "_batch_active" in block or "_is_active" in block


def test_lane_b_skips_when_dhl_received():
    """Guard 4: skip batches where DHL has already replied."""
    block = _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "skipped_received" in block
    assert "dhl_email" in block


def test_lane_b_calls_process_dhl_followup():
    assert "_process_dhl_followup" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_passes_customs_trigger():
    """Guard 6: customs_trigger passed from tracking events."""
    block = _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "_process_dhl_followup(ap, audit, customs_trigger)" in block


def test_lane_b_uses_detect_tracking_triggers():
    """Guard 6: customs trigger detected from tracking events."""
    assert "detect_tracking_triggers" in _lane_b(
        _ROUTE.read_text(encoding="utf-8", errors="replace")
    )


def test_lane_b_has_followup_sent_counter():
    assert "followup_sent" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_has_followup_stopped_counter():
    assert "followup_stopped" in _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_lane_b_no_financial_writes():
    block = _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    for t in ["total_value", "cif_", "duty_", "freight_", "proforma", "landed_cost"]:
        assert t not in block.lower()


def test_lane_b_no_wfirma_imports():
    """No wFirma imports or function calls in Lane B — only mentioned in docstring."""
    block = _lane_b(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "import wfirma" not in block.lower()
    assert "from .wfirma" not in block.lower()
    assert "wfirma_api" not in block.lower()
    # 'wfirma' in docstring (explaining what NOT to touch) is acceptable


# ══════════════════════════════════════════════════════════════════════════════
# C. Existing SLA infrastructure guards (source-grep on sla + guard modules)
# ══════════════════════════════════════════════════════════════════════════════

def test_sla_module_initial_wait_is_4h():
    """Guard 7: first follow-up at trigger + 4 hours."""
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "INITIAL_WAIT_HOURS" in src
    idx = src.index("INITIAL_WAIT_HOURS")
    assert "4" in src[idx:idx+40], "INITIAL_WAIT_HOURS must be 4"


def test_sla_module_repeat_interval_is_1h():
    """Guard 8: repeat once per hour."""
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "REPEAT_FOLLOWUP_HOURS" in src
    idx = src.index("REPEAT_FOLLOWUP_HOURS")
    assert "1" in src[idx:idx+40], "REPEAT_FOLLOWUP_HOURS must be 1"


def test_sla_module_working_hours_defined():
    """Guard 9: Warsaw working hours enforced by SLA module."""
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "WORK_START" in src
    assert "WORK_END" in src
    assert "08:00" in src or "time(8" in src, "Working hours must start at 08:00"
    assert "16:00" in src or "time(16" in src, "Working hours must end at 16:00"


def test_sla_module_stop_on_dhl_received():
    """Guard 4: SLA stops when DHL email received."""
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "STOP_DHL_EMAIL_RECEIVED" in src


def test_sla_module_stop_on_customs_docs():
    """Guard 5: SLA stops when customs docs received."""
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "STOP_CUSTOMS_DOCS_RECEIVED" in src


def test_sla_module_stop_on_terminal():
    """SLA stops on terminal/delivered status."""
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "STOP_TERMINAL" in src


def test_guard_module_checks_orch_auto_send_flag():
    """Guard 2 (inner): DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP must be True to send."""
    src = _GUARD.read_text(encoding="utf-8", errors="replace")
    assert "DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP" in src


def test_guard_module_idempotency_key():
    """Guard 10: idempotency key prevents duplicate sends for same time slot."""
    src = _GUARD.read_text(encoding="utf-8", errors="replace")
    assert "idempotency_key" in src


# ══════════════════════════════════════════════════════════════════════════════
# D. PowerShell scheduler — Lane B wiring
# ══════════════════════════════════════════════════════════════════════════════

def test_script_calls_lane_b():
    assert "scheduled-followup-check" in _SCRIPT.read_text(encoding="utf-8", errors="replace")


def test_script_lane_b_gated_by_working_hours():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "Test-WorkingHours" in src or "WorkStart" in src


def test_script_lane_b_gated_by_60min_interval():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "Test-LaneBDue" in src or "LaneBIntervalMin" in src


def test_script_lane_b_tracks_last_run_time():
    """Lane B last-run timestamp must be written so 60-min interval is enforced."""
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "LaneBStamp" in src or "last-run" in src


def test_script_lane_b_logs_followup_sent():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "followup_sent" in src


def test_script_lanes_independent():
    """Lane A failure must not prevent Lane B."""
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    a_idx = src.index("LaneAEndpoint")
    b_idx = src.index("LaneBEndpoint")
    assert a_idx < b_idx
    between = src[a_idx:b_idx]
    assert "exit 1" not in between
