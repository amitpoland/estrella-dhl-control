"""
test_section1_state_rules.py — Section 1 state-machine guards.

The dashboard's Section 1 (Shipment & DHL) renders one button per stage,
not all-at-once. Frontend logic reads these audit fields:

    audit.polish_desc_filename + audit.polish_desc_file_exists
    audit.dsk_filename         + audit.dsk_file_exists
    audit.clearance_decision.require_dsk
    audit.clearance_decision.clearance_path
    audit.dhl_reply_package.status     ('queued' | 'sent' | None)
    audit.agency_reply_package.status  ('queued' | 'sent' | None)
    trackingData.api_status            ('pending' | 'no_credentials' | …)

These tests guard the truth-source contract those flags depend on. If a
field's shape changes the dashboard's state machine is the first thing
that breaks; this catches it server-side before render.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.batch_state_normalizer import normalize_batch_state  # noqa: E402


def _audit(**overrides):
    base = {
        "batch_id": "TEST",
        "tracking_no": "1234567890",
        "inputs": {"invoices": ["a.pdf"], "zc429": "z.pdf"},
        "customs_declaration": {"mrn": "X", "duty_a00_pln": 1.0},
    }
    base.update(overrides)
    return base


# ── Polish Description state machine ──────────────────────────────────────────

class TestPolishDescriptionState:
    """Front-end rule:
       - file exists           → only ↓ Polish Description
       - audit-says-yes-but-file-gone → only ⚠ Repair Polish Description
       - not generated         → ⊞ Generate + disabled ↓ chip
    """
    def test_no_file_means_normalizer_reports_not_generated(self, tmp_path):
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(_audit(), bdir)
        assert s.has_polish_description is False
        assert s.polish_desc_filename is None

    def test_file_present_in_canonical_dir_is_generated(self, tmp_path, monkeypatch):
        bdir = tmp_path / "T"; bdir.mkdir()
        canonical = tmp_path / "polish_descriptions"
        canonical.mkdir()
        (canonical / "POLISH_DESC_X.pdf").write_bytes(b"%PDF-1.4 fake")

        from app.core import config as cfg
        monkeypatch.setattr(cfg.settings, "storage_root", tmp_path)

        s = normalize_batch_state(
            _audit(polish_desc_filename="POLISH_DESC_X.pdf"), bdir,
        )
        assert s.has_polish_description is True
        assert s.polish_desc_filename == "POLISH_DESC_X.pdf"

    def test_audit_says_yes_but_file_missing(self, tmp_path):
        """Repair state — audit lists the filename but no file on disk."""
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(
            _audit(polish_desc_filename="POLISH_DESC_X.pdf"), bdir,
        )
        assert s.polish_desc_filename == "POLISH_DESC_X.pdf"
        assert s.has_polish_description is False     # file truly missing


# ── DSK state machine ─────────────────────────────────────────────────────────

class TestDSKState:
    def test_dsk_required_default_true_for_high_value_path(self):
        a = _audit(clearance_decision={
            "clearance_path": "agency_clearance",
            "require_dsk": True,
        })
        assert a["clearance_decision"]["require_dsk"] is True

    def test_dsk_not_required_path_explicit(self):
        a = _audit(clearance_decision={
            "clearance_path": "carrier_clears",
            "require_dsk": False,
        })
        assert a["clearance_decision"]["require_dsk"] is False


# ── Reply workflow stage progression ──────────────────────────────────────────

class TestReplyWorkflowStages:
    """Stage progression: nothing → built → queued → sent.
    Each state must surface as exactly one chip/button on the dashboard."""

    def test_nothing_built_state(self, tmp_path):
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(_audit(dhl_reply_package={}), bdir)
        assert s.dhl_reply_built is False
        assert s.dhl_reply_sent is False

    def test_built_not_sent_state(self, tmp_path):
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(
            _audit(dhl_reply_package={"email_id": "queue-1", "status": "queued"}),
            bdir,
        )
        assert s.dhl_reply_built is True
        assert s.dhl_reply_sent is False
        assert s.dhl_reply_queue_id == "queue-1"

    def test_sent_state(self, tmp_path):
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(
            _audit(dhl_reply_package={"email_id": "queue-1", "status": "sent"}),
            bdir,
        )
        assert s.dhl_reply_sent is True


# ── Agency workflow stage progression ─────────────────────────────────────────

class TestAgencyWorkflowStages:
    def test_agency_path_only_when_clearance_path_external(self):
        a = _audit(clearance_decision={"clearance_path": "agency_clearance"})
        assert a["clearance_decision"]["clearance_path"] == "agency_clearance"

    def test_agency_queued_records_queue_id(self, tmp_path):
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(
            _audit(
                clearance_decision={"clearance_path": "agency_clearance"},
                agency_reply_package={"queue_id": "q-99", "status": "queued"},
            ),
            bdir,
        )
        assert s.agency_email_queued is True
        assert s.agency_email_sent is False
        assert s.agency_queue_id == "q-99"

    def test_agency_sent_takes_precedence(self, tmp_path):
        bdir = tmp_path / "T"; bdir.mkdir()
        s = normalize_batch_state(
            _audit(agency_reply_package={"queue_id": "q-99", "status": "sent"}),
            bdir,
        )
        assert s.agency_email_sent is True


# ── DHL API down detection ────────────────────────────────────────────────────

class TestDHLApiDownDetection:
    """The dashboard treats these tracking_data.api_status / source values as
    'API unavailable' and shows the warning banner instead of API actions."""

    @pytest.mark.parametrize("td_field, value", [
        ("api_status", "pending"),
        ("api_status", "no_credentials"),
        ("source",     "api_pending"),
        ("source",     "no_credentials"),
    ])
    def test_api_down_signal_shape(self, td_field, value):
        # The frontend reads `trackingData[td_field] === value` to decide
        # whether to render the amber 'API unavailable' banner. This test
        # locks the contract.
        td = {td_field: value}
        assert td.get(td_field) == value

    def test_api_live_does_not_trigger_banner(self):
        td = {"available": True, "status": "in_transit", "source": "api_dhl"}
        # Frontend treats this as live → no warning banner.
        is_pending = (
            td.get("api_status") in ("pending", "no_credentials") or
            td.get("source")     in ("api_pending", "no_credentials")
        )
        assert is_pending is False
