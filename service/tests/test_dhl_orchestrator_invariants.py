"""test_dhl_orchestrator_invariants.py — source-grep + flag-default invariants.

Verifies safety properties that must hold regardless of code changes:
  - all AUTO_SEND_* flags default False
  - dhl_orch_enabled defaults False
  - dhl_orch_shadow_mode defaults True
  - the orchestrator module never reads carrier_arrived_at_poland_at
  - the orchestrator module never writes carrier_arrived_at_poland_at
  - the orchestrator module never imports smtplib directly
  - all 7 dashboard test-ids are present in shipment-detail.html
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_ORCH_MODULE = Path(__file__).resolve().parent.parent / "app" / "services" / "dhl_orchestrator.py"
_DASHBOARD   = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"


def test_flag_defaults_safe():
    """Every flag MUST default to a safe value."""
    from app.core.config import Settings
    s = Settings()
    assert s.dhl_orch_enabled is False
    assert s.dhl_orch_shadow_mode is True
    assert s.dhl_orch_auto_refresh_tracking is False
    assert s.dhl_orch_auto_monitor_sweep is False
    assert s.dhl_orch_auto_email_ingest is False
    assert s.dhl_orch_auto_refresh_proposals is False
    assert s.dhl_orch_auto_build_packages is False
    assert s.dhl_orch_auto_send_agency is False
    assert s.dhl_orch_auto_send_dhl_reply is False
    assert s.dhl_orch_tick_interval_sec >= 60


def test_orchestrator_does_not_read_carrier_arrived_at_poland_at():
    """Source-grep invariant. This field has unreliable provenance —
    orchestrator must never branch on it."""
    src = _ORCH_MODULE.read_text(encoding="utf-8")
    # Allow mentions only in comments / docstrings.  Strip those.
    code_only = re.sub(r"#[^\n]*", "", src)
    code_only = re.sub(r'"""[\s\S]*?"""', "", code_only)
    assert "carrier_arrived_at_poland_at" not in code_only, (
        "orchestrator code references carrier_arrived_at_poland_at "
        "in non-comment code; this field must be ignored"
    )


def test_orchestrator_does_not_import_smtplib():
    """All sends must route through email_sender; no direct SMTP."""
    src = _ORCH_MODULE.read_text(encoding="utf-8")
    assert "import smtplib" not in src
    assert "from smtplib" not in src


def test_orchestrator_does_not_call_queue_email_directly_in_phase1():
    """Phase 1 does not call queue_email / send_queued_email from the
    orchestrator.  Future phases that do MUST go through the guarded
    pipeline — but Phase 1 keeps the boundary clean."""
    src = _ORCH_MODULE.read_text(encoding="utf-8")
    code_only = re.sub(r"#[^\n]*", "", src)
    code_only = re.sub(r'"""[\s\S]*?"""', "", code_only)
    assert "queue_email(" not in code_only
    assert "send_queued_email(" not in code_only


def test_dashboard_has_required_test_ids():
    """Operator UX surface must expose all 7 test-ids."""
    html = _DASHBOARD.read_text(encoding="utf-8")
    required = [
        "orchestrator-state-card",
        "orchestrator-next-action",
        "orchestrator-blocked-reason",
        "orchestrator-last-tick-at",
        "orchestrator-shadow-marker",
        "orchestrator-attachment-preview",
        "orchestrator-pending-count",
    ]
    missing = [t for t in required if t not in html]
    assert not missing, f"missing test-ids in shipment-detail.html: {missing}"


def test_dsk_generated_in_status_order():
    """dsk_generated must be ranked above draft (not 0)."""
    from app.services.active_shipment_monitor import _STATUS_ORDER
    assert _STATUS_ORDER.get("dsk_generated", 0) >= 3
    assert _STATUS_ORDER["dsk_generated"] >= _STATUS_ORDER["polish_description_generated"]


def test_state_constants_are_strings():
    from app.services import dhl_orchestrator as orch
    for s in orch.ALL_STATES:
        assert isinstance(s, str) and s == s.lower()
