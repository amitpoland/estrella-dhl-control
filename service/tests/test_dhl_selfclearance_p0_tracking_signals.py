"""
test_dhl_selfclearance_p0_tracking_signals.py — extract_selfclearance_signals.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import tracking_normalizer as tn  # noqa: E402


def test_five_signal_tokens_locked():
    assert tn.SELFCLEARANCE_SIGNAL_TOKENS == frozenset({
        "poland_arrival",
        "customs_processing",
        "customs_hold",
        "delay",
        "rejected_paperwork",
    })


def test_poland_arrival_from_location_country_code():
    signals = tn.extract_selfclearance_signals({
        "description": "ARRIVED",
        "location": "WARSAW - POLAND - PL",
    })
    assert "poland_arrival" in signals


def test_customs_processing_emitted_from_description():
    signals = tn.extract_selfclearance_signals({
        "description": "under customs review",
        "location": "WARSAW - POLAND - PL",
    })
    assert "customs_processing" in signals


def test_customs_hold_emitted():
    signals = tn.extract_selfclearance_signals({
        "description": "Shipment on hold by customs.",
    })
    assert "customs_hold" in signals


def test_delay_emitted():
    signals = tn.extract_selfclearance_signals({
        "description": "Shipment delayed at facility.",
    })
    assert "delay" in signals


def test_rejected_paperwork_emitted():
    signals = tn.extract_selfclearance_signals({
        "description": "documents rejected by customs",
    })
    assert "rejected_paperwork" in signals


def test_no_signal_on_unrelated_event():
    signals = tn.extract_selfclearance_signals({
        "description": "Picked up",
    })
    assert signals == frozenset()


def test_multiple_signals_can_fire_simultaneously():
    signals = tn.extract_selfclearance_signals({
        "description": "held by customs; shipment delayed",
    })
    assert "customs_hold" in signals
    assert "delay" in signals


def test_existing_stage_normalization_unchanged():
    # Regression: the legacy STAGE_ORDER vocabulary must NOT shift under P0.
    expected_count = 18
    assert len(tn.STAGE_ORDER) == expected_count


def test_existing_delivered_normalization_unchanged():
    ev = tn.normalize_tracking_event(
        {"description": "Delivered"}, source="dhl_api", awb="A",
    )
    assert ev["normalized_stage"] == "DELIVERED"
