"""
test_dashboard_status_label_mapping.py — source-grep assertions for mapOverall()
in dashboard.html.

Pins the exact JS status → display-label mappings so any future change to
mapOverall is caught before it reaches production.

Tests:
  1. partial maps to 'Ready for Booking' (not 'Action Required')
  2. success maps to 'Ready for Booking'
  3. blocked maps to 'Action Required'
  4. failed maps to 'Action Required'
  5. ready maps to 'Ready for PZ'
  6. action_reason tooltip scoped to Action Required badges only
  7. Badge component accepts title prop
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(__file__).parents[1] / "app" / "static" / "dashboard.html"


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _mapoverall_block(src: str) -> str:
    """Extract the mapOverall function body for targeted assertions."""
    m = re.search(r"function mapOverall\(status\)\s*\{(.+?)\}", src, re.DOTALL)
    assert m, "mapOverall not found in dashboard.html"
    return m.group(1)


class TestMapOverallMappings:
    def test_partial_maps_to_ready_for_booking(self):
        block = _mapoverall_block(_src())
        assert "partial: 'Ready for Booking'" in block, (
            "partial must map to 'Ready for Booking' — VERIFY-GAP batches have PZ generated"
        )

    def test_partial_does_not_map_to_action_required(self):
        block = _mapoverall_block(_src())
        assert "partial: 'Action Required'" not in block

    def test_success_maps_to_ready_for_booking(self):
        block = _mapoverall_block(_src())
        assert "success: 'Ready for Booking'" in block

    def test_blocked_maps_to_action_required(self):
        block = _mapoverall_block(_src())
        assert "blocked: 'Action Required'" in block

    def test_failed_maps_to_action_required(self):
        block = _mapoverall_block(_src())
        assert "failed: 'Action Required'" in block

    def test_ready_maps_to_ready_for_pz(self):
        block = _mapoverall_block(_src())
        assert "ready: 'Ready for PZ'" in block


class TestTooltipScoping:
    def test_action_reason_tooltip_scoped_to_action_required(self):
        src = _src()
        assert "row.overall === 'Action Required' && row.action_reason" in src, (
            "action_reason tooltip must only render when badge label is 'Action Required'"
        )

    def test_plain_action_reason_not_used_as_badge_title(self):
        src = _src()
        assert "title={row.action_reason || undefined}" not in src, (
            "Bare action_reason must not be used as badge title — it leaks engine errors onto non-blocked badges"
        )

    def test_badge_accepts_title_prop(self):
        src = _src()
        assert "function Badge({ status, small, title })" in src
