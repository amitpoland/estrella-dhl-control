"""
Test dhl_followup_authority.py — B6 advisory authority module.

Coverage:
1. Derivation: one representative row per state; precedence test; sparse-row totality
2. Flag OFF: projector outputs contain NO authority keys
3. Flag ON: per-row keys present; authority_summary counts equal recount
4. Lesson E isolation: source-grep test for forbidden imports
5. Purity: module imports stdlib + typing only
"""
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.dhl_followup_authority import (
    derive_followup_authority,
    summarize_followup_authority
)


def test_derive_followup_authority_completed_dsk():
    """COMPLETED state: DSK received."""
    row = {
        "awb": "123456789",
        "dsk_received_at": "2026-06-12T10:00:00+00:00",
        "mode_state": "manual",
        "status": "Monitoring"
    }
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "completed"
    assert "DSK received" in result["authority_reason"]
    assert result["authority_evidence"]["dsk_received_at"] == "2026-06-12T10:00:00+00:00"


def test_derive_followup_authority_blocked_customs():
    """BLOCKED state: waiting for customs docs."""
    row = {
        "awb": "123456789",
        "waiting_for": "customs-docs condition",
        "status": "Monitoring",
        "next_due_at": "2026-06-12T08:00:00+00:00"
    }
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "blocked"
    assert "customs docs" in result["authority_reason"]
    assert result["authority_evidence"]["waiting_for"] == "customs-docs condition"


def test_derive_followup_authority_blocked_suppressed():
    """BLOCKED state: guard suppressed."""
    row = {
        "awb": "123456789",
        "sad_followup_reason": "guard suppression rule applied",
        "status": "Suppressed"
    }
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "blocked"
    assert "Guard suppressed" in result["authority_reason"]
    assert result["authority_evidence"]["sad_followup_reason"] == "guard suppression rule applied"


def test_derive_followup_authority_eligible_past_due():
    """ELIGIBLE state: actively monitored, next_due in past."""
    from datetime import datetime, timezone, timedelta
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    row = {
        "awb": "123456789",
        "next_due_at": past_time,
        "status": "Eligible"
    }
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "eligible"
    assert "Next due in past" in result["authority_reason"]
    assert result["authority_evidence"]["next_due_at"] == past_time


def test_derive_followup_authority_waiting_future_due():
    """WAITING state: next_due in future."""
    from datetime import datetime, timezone, timedelta
    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    row = {
        "awb": "123456789",
        "next_due_at": future_time,
        "status": "Monitoring"
    }
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "waiting"
    assert "Next due in future" in result["authority_reason"]
    assert result["authority_evidence"]["next_due_at"] == future_time


def test_derive_followup_authority_waiting_no_schedule():
    """WAITING state: actively monitored but no schedule."""
    row = {
        "awb": "123456789",
        "status": "Waiting",
        "next_due_at": None
    }
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "waiting"
    assert "no schedule yet" in result["authority_reason"]
    assert result["authority_evidence"]["next_due_at"] is None


def test_derive_followup_authority_precedence():
    """Precedence test: completed+blocked → completed."""
    row = {
        "awb": "123456789",
        "dsk_received_at": "2026-06-12T10:00:00+00:00",  # completed
        "waiting_for": "customs-docs condition",          # blocked
        "status": "Monitoring"
    }
    result = derive_followup_authority(row)
    # Should be completed due to precedence
    assert result["followup_authority"] == "completed"
    assert "DSK received" in result["authority_reason"]


def test_derive_followup_authority_sparse_row():
    """Totality test: empty dict → waiting, no exception."""
    row = {}
    result = derive_followup_authority(row)
    assert result["followup_authority"] == "waiting"
    assert "Default fallback" in result["authority_reason"]
    assert result["authority_evidence"] == {
        "dsk_received_at": None,
        "mode_state": None,
        "waiting_for": None,
        "sad_followup_reason": None,
        "next_due_at": None,
        "status": None
    }


def test_summarize_followup_authority():
    """Summary counts equal recount of rows."""
    rows = [
        {"dsk_received_at": "2026-06-12T10:00:00+00:00", "status": "Completed"},  # completed
        {"waiting_for": "customs docs", "status": "Blocked"},                      # blocked
        {"next_due_at": "2026-06-12T08:00:00+00:00", "status": "Eligible"},      # eligible (past)
        {"status": "Waiting", "next_due_at": None},                               # waiting
        {},  # default fallback → waiting
    ]

    summary = summarize_followup_authority(rows)

    # Manual recount
    expected = {"completed": 1, "blocked": 1, "eligible": 1, "waiting": 2}
    assert summary == expected


def test_projector_flag_off_no_authority_keys():
    """Flag OFF: projector outputs contain NO authority keys."""
    # This is a simpler test - just verify that when the flag path import fails,
    # no authority keys appear (since they're in try/except blocks)
    from app.services.dhl_followup_status_projector import project_automation_status, project_shipment_rows

    # Mock to have no audit files, so we get empty results but verify structure
    with patch("app.services.dhl_followup_status_projector._audit_paths", return_value=[]), \
         patch("app.services.dhl_followup_status_projector._flag_on", return_value=False):

        status = project_automation_status()
        rows = project_shipment_rows()

        # Authority keys must be absent when flag OFF (and no mock injection)
        assert "authority_summary" not in status
        for row in rows:
            assert "followup_authority" not in row
            assert "authority_reason" not in row
            assert "authority_evidence" not in row


def test_projector_flag_on_authority_keys_present(tmp_path):
    """Flag ON: per-row keys present; authority_summary in status."""
    from unittest.mock import patch, Mock
    import app.services.dhl_followup_status_projector as proj

    # Create a synthetic audit file for testing
    audit_data = {
        "awb": "123456789",
        "batch_id": "TEST123",
        "clearance_status": "ACTIVE",
        "tracking_no": "123456789"
    }

    audit_file = tmp_path / "audit_123456789.json"
    audit_file.write_text(json.dumps(audit_data))

    def _fake_paths():
        return [audit_file]

    def _fake_read(path):
        return json.loads(path.read_text())

    def _fake_active(audit):
        return True, "active"

    def _fake_flag_on():
        return True

    with patch("app.services.dhl_followup_status_projector._audit_paths", _fake_paths), \
         patch("app.services.dhl_followup_status_projector._read_audit", _fake_read), \
         patch("app.services.dhl_followup_status_projector._is_active", _fake_active), \
         patch("app.services.dhl_followup_status_projector._flag_on", _fake_flag_on), \
         patch("app.core.config.settings.dhl_followup_authority_advisory", True):

        # Test project_automation_status includes authority_summary when flag ON
        status = proj.project_automation_status()
        assert "authority_summary" in status
        assert isinstance(status["authority_summary"], dict)
        assert all(key in status["authority_summary"] for key in ["waiting", "eligible", "blocked", "completed"])
        assert all(isinstance(status["authority_summary"][key], int) for key in ["waiting", "eligible", "blocked", "completed"])

        # Test project_shipment_rows includes authority keys when flag ON
        rows = proj.project_shipment_rows()
        assert len(rows) > 0  # Should have at least our synthetic audit
        for row in rows:
            assert "followup_authority" in row
            assert "authority_reason" in row
            assert "authority_evidence" in row
            assert row["followup_authority"] in ["waiting", "eligible", "blocked", "completed"]


def test_lesson_e_isolation_source_grep():
    """Lesson E isolation: module source contains no forbidden imports."""
    module_path = Path(__file__).parent.parent / "app" / "services" / "dhl_followup_authority.py"
    source = module_path.read_text(encoding="utf-8")

    forbidden_patterns = [
        r"\bsmtplib\b",
        r"\bemail_service\b",
        r"\bqueue_email\b",
        r"\broutes_"
    ]

    for pattern in forbidden_patterns:
        matches = re.findall(pattern, source, re.IGNORECASE)
        assert not matches, f"Forbidden pattern '{pattern}' found in source: {matches}"


def test_module_purity_imports():
    """Purity: module imports stdlib + typing only."""
    module_path = Path(__file__).parent.parent / "app" / "services" / "dhl_followup_authority.py"
    source = module_path.read_text(encoding="utf-8")

    # Extract import lines
    import_lines = []
    for line in source.split("\n"):
        line = line.strip()
        if line.startswith(("import ", "from ")) and not line.startswith("#"):
            import_lines.append(line)

    # Should only import stdlib modules
    allowed_modules = ["datetime", "typing"]

    for line in import_lines:
        # Skip relative imports and __future__
        if line.startswith("from __future__") or line.startswith("from ."):
            continue

        # Extract module name
        if line.startswith("from "):
            module = line.split()[1].split(".")[0]
        elif line.startswith("import "):
            module = line.split()[1].split(".")[0]
        else:
            continue

        assert module in allowed_modules, f"Non-stdlib import detected: {line}"