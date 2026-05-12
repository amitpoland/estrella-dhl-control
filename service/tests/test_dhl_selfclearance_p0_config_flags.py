"""
test_dhl_selfclearance_p0_config_flags.py — flag defaults and types.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


def test_p2_flags_default_off():
    assert settings.dhl_selfclearance_p2_live_enabled is False
    assert settings.dhl_selfclearance_p2_shadow_mode is True


def test_p3_flags_default_off():
    assert settings.dhl_selfclearance_p3_live_enabled is False
    assert settings.dhl_selfclearance_p3_shadow_mode is True
    assert settings.dhl_selfclearance_p3_tracker_paused is False


def test_p4_flags_default_off():
    assert settings.dhl_selfclearance_p4_live_enabled is False
    assert settings.dhl_selfclearance_p4_shadow_mode is True


def test_p5_flags_default_off():
    assert settings.dhl_selfclearance_p5_live_enabled is False
    assert settings.dhl_selfclearance_p5_shadow_mode is True
    assert settings.dhl_selfclearance_p5_pz_trigger_enabled is False


def test_classifier_thresholds_default_conservative():
    assert settings.dhl_selfclearance_p4_classifier_min_confidence == 0.85
    assert settings.dhl_selfclearance_p5_classifier_min_confidence == 0.95


def test_followup_cadence_defaults():
    assert settings.dhl_selfclearance_followup_working_interval_sec == 7200
    assert settings.dhl_selfclearance_followup_offhours_interval_sec == 21600
    assert settings.dhl_selfclearance_followup_working_hours_window == "08:00-16:00 CET"
    assert settings.dhl_selfclearance_followup_livelock_budget_hours == 168


def test_value_threshold_default():
    assert settings.dhl_selfclearance_value_threshold_usd == 2500


def test_all_boolean_flags_are_booleans():
    for name in [
        "dhl_selfclearance_p2_live_enabled",
        "dhl_selfclearance_p2_shadow_mode",
        "dhl_selfclearance_p3_live_enabled",
        "dhl_selfclearance_p3_shadow_mode",
        "dhl_selfclearance_p3_tracker_paused",
        "dhl_selfclearance_p4_live_enabled",
        "dhl_selfclearance_p4_shadow_mode",
        "dhl_selfclearance_p5_live_enabled",
        "dhl_selfclearance_p5_shadow_mode",
        "dhl_selfclearance_p5_pz_trigger_enabled",
    ]:
        assert isinstance(getattr(settings, name), bool), f"{name} must be bool"
