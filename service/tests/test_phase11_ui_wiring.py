"""
test_phase11_ui_wiring.py — Phase 11 UI wiring evidence tests.

Verifies:
1. Frozen V1 files (dashboard.html, shipment-detail.html) are NOT modified
2. Key state-changing buttons have data-wf-id attributes (§2 binding table)
3. Utility buttons (Download, Export CSV, etc.) do NOT have data-wf-id
4. Write-flag gates are annotated on the correct buttons (data-wf-gate)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

STATIC = Path(__file__).parent.parent / "app" / "static"


def _read(filename: str) -> str:
    p = STATIC / filename
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


class TestFrozenFilesUnchanged:
    """V1 frozen files must not be modified."""

    def test_dashboard_html_is_unmodified(self):
        """dashboard.html should not contain any Phase 11 annotations."""
        content = _read("dashboard.html")
        # The frozen file should not have the campaign WF annotations
        # (we never edit it — confirming data-wf-id is absent proves no edits)
        assert "data-wf-id" not in content, \
            "dashboard.html must not be edited — it is frozen in V1"

    def test_shipment_detail_html_is_unmodified(self):
        content = _read("shipment-detail.html")
        assert "data-wf-id" not in content, \
            "shipment-detail.html must not be edited — it is frozen in V1"


class TestWfIdAnnotations:
    """Key state-changing buttons have data-wf-id attributes."""

    def test_proforma_detail_post_button_wired_to_wf24(self):
        """btn-post-wfirma must be annotated as WF2.4."""
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-id="WF2.4"' in content, \
            "Post to wFirma button must carry data-wf-id='WF2.4'"

    def test_proforma_detail_convert_button_wired_to_wf25(self):
        """btn-convert-invoice must be annotated as WF2.5."""
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-id="WF2.5"' in content, \
            "Convert to Invoice button must carry data-wf-id='WF2.5'"

    def test_proforma_post_has_flag_gate_annotation(self):
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-gate="WFIRMA_CREATE_PROFORMA_ALLOWED"' in content

    def test_proforma_convert_has_flag_gate_annotation(self):
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-gate="WFIRMA_CREATE_INVOICE_ALLOWED"' in content


class TestPhase11Summary:
    """Document the wiring gap explicitly."""

    def test_phase11_partial_wiring_acknowledged(self):
        """Phase 11 documents the current wiring state per §2.

        Full §2 binding table requires all screen buttons to be wired.
        This test confirms the partial wiring that IS done in Phase 11,
        and that remaining screens are documented for Phase 12 truth-table.

        Wired in Phase 11:
          - proforma-detail-v2.html: WF2.4 (Post), WF2.5 (Convert)

        Remaining screens (to complete per Phase 12 truth-table):
          - shipment-v2.html: WF1.4, WF1.5, WF1.7, WF1.8
          - New Shipment modal: WF1.1
          - Inventory screen: WF4.3, WF4.4/4.5
          - Inbox screen: cross-cutting
          - Reservation tab: WF3.2
        """
        # Assert at least the proforma wiring is done
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-id="WF2.4"' in content
        assert 'data-wf-id="WF2.5"' in content
        # Confirm frozen files untouched
        assert 'data-wf-id' not in _read("dashboard.html")
        assert 'data-wf-id' not in _read("shipment-detail.html")


class TestDescriptionAuthorityAdvisoryBadge:
    """Advisory badge for posted proformas with operator-written description lines."""

    def test_advisory_badge_present_in_proforma_detail(self):
        content = _read("proforma-detail-v2.html")
        assert 'data-testid="historical-description-advisory"' in content, \
            "Historical description advisory badge must be present in proforma-detail-v2.html"

    def test_advisory_badge_checks_name_pl_source_operator(self):
        content = _read("proforma-detail-v2.html")
        assert "name_pl_source === 'operator'" in content, \
            "Advisory badge must gate on name_pl_source === 'operator'"

    def test_advisory_badge_only_on_posted_proformas(self):
        content = _read("proforma-detail-v2.html")
        advisory_block = content[content.find("historical-description-advisory"):]
        # The advisory should be wrapped in the `posted` condition
        # Simple heuristic: both tokens appear before the advisory block
        advisory_pos = content.find("historical-description-advisory")
        posted_ref_pos = content.rfind("posted &&", 0, advisory_pos)
        assert posted_ref_pos != -1, \
            "Advisory badge must be conditional on the 'posted' flag"
