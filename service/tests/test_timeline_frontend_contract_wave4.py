"""
test_timeline_frontend_contract_wave4.py — Wave 4 frontend contract.

Source-contract: the V2 TimelineTab consumes the canonical backend milestone
read-model (timeline_milestones) instead of inferring completion from raw events
with a stale alias map, and deriveDetail threads it through.
"""
from __future__ import annotations

from pathlib import Path

import pytest

DETAIL = Path(__file__).parents[1] / "app" / "static" / "v2" / "shipment-detail-page.jsx"


def _src():
    if not DETAIL.exists():
        pytest.skip("shipment-detail-page.jsx missing")
    return DETAIL.read_text(encoding="utf-8")


def test_derivedetail_threads_timeline_milestones():
    src = _src()
    assert "timeline_milestones" in src, "deriveDetail must read audit.timeline_milestones"
    assert "timelineMilestones" in src, "deriveDetail must expose timelineMilestones"


def test_timelinetab_renders_backend_read_model():
    src = _src()
    assert "d.timelineMilestones" in src, "TimelineTab must consume the backend read-model"
    # canonical path renders per-milestone rows with stable keyed testids …
    assert "timeline-milestone-${m.key}" in src or "timeline-milestone-`" in src or "timeline-milestones" in src
    # … and honours the audit_field source (completion with no timeline event).
    assert "audit_field" in src, "TimelineTab must handle field-sourced completion honestly"


def test_timelinetab_keeps_legacy_fallback():
    src = _src()
    # The canonical path is guarded on the read-model being present …
    assert "if (milestones && milestones.length)" in src, "canonical path must be guarded on read-model presence"
    # … and the legacy fallback below it is real, load-bearing code (not just a
    # comment): it renders raw events + pending milestones when the read-model
    # is absent. Assert on the structural tokens, not the human comment.
    assert "_TIMELINE_MILESTONES" in src, "legacy fallback must derive pending milestones from _TIMELINE_MILESTONES"
    assert "pendingMilestones" in src, "legacy fallback must compute the pending-milestone list"
    assert 'data-testid="timeline-events"' in src or "timeline-event-done" in src, "legacy fallback must render the raw-event list"
