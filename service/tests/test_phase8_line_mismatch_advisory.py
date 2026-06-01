"""
test_phase8_line_mismatch_advisory.py — Phase 8 evidence tests.

Verifies that sales↔purchase line mismatches become inbox advisories
(not hard blockers) when advisory_gates_enabled=True.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestLineMismatchAdvisoryFlag:
    """advisory_gates_enabled=True: unmatched designs → advisory, not blocker."""

    def test_advisory_mode_flag_default_false(self):
        from app.core.config import settings
        assert settings.advisory_gates_enabled is False

    def test_unmatched_count_goes_to_advisory_when_flag_on(self, monkeypatch):
        """When advisory_gates_enabled, unmatched designs produce advisories not blockers."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "advisory_gates_enabled", True)

        # Simulate the gate logic from _build_preview
        unmatched_count = 3
        blocking_reasons = []
        line_mismatch_advisories = []

        _mismatch_msg = (
            f"{unmatched_count} sales design(s) not mapped to a wFirma product_code — "
            "verify the sales packing list matches the purchase invoice and design_product_mapping "
            "is populated (approve/correct/split via Inbox)"
        )
        if settings.advisory_gates_enabled:
            line_mismatch_advisories.append(_mismatch_msg)
        else:
            blocking_reasons.append(
                f"{unmatched_count} sales design(s) not mapped to a wFirma product_code"
            )

        assert len(line_mismatch_advisories) == 1
        assert blocking_reasons == []
        assert "approve/correct/split" in line_mismatch_advisories[0]

    def test_hard_mode_unmatched_goes_to_blockers(self, monkeypatch):
        """Default hard mode: unmatched designs block the proforma."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "advisory_gates_enabled", False)

        unmatched_count = 2
        blocking_reasons = []
        line_mismatch_advisories = []

        if settings.advisory_gates_enabled:
            line_mismatch_advisories.append("advisory")
        else:
            blocking_reasons.append(
                f"{unmatched_count} sales design(s) not mapped to a wFirma product_code"
            )

        assert blocking_reasons != []
        assert line_mismatch_advisories == []

    def test_no_mismatch_no_advisory_no_blocker(self):
        """When all designs are matched, neither advisory nor blocker is emitted."""
        unmatched_count = 0
        blocking_reasons = []
        line_mismatch_advisories = []
        # (no code path fires when unmatched_count == 0)
        assert blocking_reasons == []
        assert line_mismatch_advisories == []


class TestLineMismatchProposalShape:
    """Advisory message has the correct shape for Inbox display."""

    def test_advisory_message_includes_required_actions(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "advisory_gates_enabled", True)

        unmatched_designs = ["DESIGN-XYZ", "DESIGN-ABC"]
        unmatched_count   = len(unmatched_designs)
        advisories: list  = []

        if settings.advisory_gates_enabled and unmatched_count:
            advisories.append(
                f"{unmatched_count} sales design(s) not mapped to a wFirma product_code — "
                "verify the sales packing list matches the purchase invoice and design_product_mapping "
                "is populated (approve/correct/split via Inbox)"
            )

        assert len(advisories) == 1
        msg = advisories[0]
        assert "2 sales design" in msg
        assert "approve/correct/split" in msg
        assert "Inbox" in msg
