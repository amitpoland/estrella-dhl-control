"""
test_dhl_selfclearance_p0_carrier_predicate.py — is_awb_stable predicate.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.carrier import coordinator as cc  # noqa: E402
from app.services.carrier.models.shipment import ShipmentState  # noqa: E402


def test_is_state_stable_submitted_true():
    assert cc.is_state_stable(ShipmentState.SUBMITTED.value) is True


def test_is_state_stable_complete_true():
    assert cc.is_state_stable(ShipmentState.COMPLETE.value) is True


def test_is_state_stable_pending_false():
    assert cc.is_state_stable(ShipmentState.PENDING.value) is False


def test_is_state_stable_failed_false():
    assert cc.is_state_stable(ShipmentState.FAILED.value) is False


def test_is_state_stable_none_false():
    assert cc.is_state_stable(None) is False


def test_is_state_stable_empty_string_false():
    assert cc.is_state_stable("") is False


def test_is_awb_stable_override_submitted_true():
    assert cc.is_awb_stable("AWB1", state_override="submitted") is True


def test_is_awb_stable_override_pending_false():
    assert cc.is_awb_stable("AWB1", state_override="pending") is False


def test_is_awb_stable_no_db_path_returns_false():
    assert cc.is_awb_stable("AWB1") is False


def test_is_awb_stable_empty_awb_returns_false():
    assert cc.is_awb_stable("", state_override="submitted") is True  # override takes precedence
    assert cc.is_awb_stable("") is False  # no override + no awb → false


def test_is_awb_stable_no_row_returns_false(tmp_path):
    from app.services.carrier.persistence.shipment_db import init_db
    db = tmp_path / "shipments.db"
    init_db(db)
    assert cc.is_awb_stable("UNKNOWN_AWB", db_path=db) is False
