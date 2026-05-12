"""
test_dhl_selfclearance_p0_manifest.py — Frozen sub-schema writer helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clearance_manifest as mf  # noqa: E402
from app.services import dhl_clearance_state_engine as se  # noqa: E402


def _fresh_audit():
    return {}


# ── Init ──────────────────────────────────────────────────────────────────────

def test_init_creates_manifest_block_with_initial_state():
    audit = _fresh_audit()
    mf.init_manifest(audit)
    assert audit[mf.MANIFEST_KEY]["state"] == se.INITIAL_STATE
    assert audit[mf.MANIFEST_KEY]["state_history"] == []
    assert audit[mf.MANIFEST_KEY]["thread_id"] == ""
    assert audit[mf.MANIFEST_KEY]["thread_id_aliases"] == []


def test_init_is_idempotent():
    audit = {mf.MANIFEST_KEY: {"state": se.STATE_FOLLOWUP_ACTIVE}}
    mf.init_manifest(audit)
    assert audit[mf.MANIFEST_KEY]["state"] == se.STATE_FOLLOWUP_ACTIVE


# ── State transitions ────────────────────────────────────────────────────────

def test_record_transition_appends_history_and_updates_state():
    audit = _fresh_audit()
    mf.record_transition(audit, se.STATE_AWAITING_POLAND_ARRIVAL, reason="awb_stable")
    block = audit[mf.MANIFEST_KEY]
    assert block["state"] == se.STATE_AWAITING_POLAND_ARRIVAL
    assert len(block["state_history"]) == 1
    assert block["state_history"][0]["to"] == se.STATE_AWAITING_POLAND_ARRIVAL


def test_record_transition_illegal_raises():
    audit = _fresh_audit()
    with pytest.raises(se.IllegalTransition):
        mf.record_transition(audit, se.STATE_SHIPMENT_CLOSED)


# ── Thread id + aliases ──────────────────────────────────────────────────────

def test_set_thread_id_writes_string():
    audit = _fresh_audit()
    mf.set_thread_id(audit, "thr:abc123")
    assert audit[mf.MANIFEST_KEY]["thread_id"] == "thr:abc123"


def test_set_thread_id_empty_raises():
    audit = _fresh_audit()
    with pytest.raises(mf.ManifestSchemaError):
        mf.set_thread_id(audit, "")


def test_add_thread_alias_dedupes():
    audit = _fresh_audit()
    mf.add_thread_alias(audit, "thr:alt1")
    mf.add_thread_alias(audit, "thr:alt1")
    mf.add_thread_alias(audit, "thr:alt2")
    assert audit[mf.MANIFEST_KEY]["thread_id_aliases"] == ["thr:alt1", "thr:alt2"]


# ── Phase block writers ──────────────────────────────────────────────────────

def test_write_p2_dispatch_round_trips():
    audit = _fresh_audit()
    mf.write_p2_dispatch(
        audit,
        shadow=False,
        message_id="m1",
        recipient="odprawacelna@dhl.com",
        sent_at="2026-05-12T10:00:00Z",
        content_sha256="a" * 64,
    )
    block = audit[mf.MANIFEST_KEY]["p2_dispatch"]
    assert block["message_id"] == "m1"
    assert block["recipient"] == "odprawacelna@dhl.com"


def test_write_p2_dispatch_rejects_extra_field():
    audit = _fresh_audit()
    with pytest.raises(mf.ManifestSchemaError):
        mf.write_p2_dispatch(audit, shadow=True, undocumented_field="x")


def test_write_p2_dispatch_rejects_bad_sha256():
    audit = _fresh_audit()
    with pytest.raises(mf.ManifestSchemaError):
        mf.write_p2_dispatch(audit, content_sha256="too_short")


def test_write_p3_tracking_accumulates_fields():
    audit = _fresh_audit()
    mf.write_p3_tracking(audit, tick_count=1, watcher_active=True)
    mf.write_p3_tracking(audit, last_tick_at="2026-05-12T10:00:00Z")
    block = audit[mf.MANIFEST_KEY]["p3_tracking"]
    assert block["tick_count"] == 1
    assert block["watcher_active"] is True
    assert block["last_tick_at"] == "2026-05-12T10:00:00Z"


def test_write_p4_followup_round_trips():
    audit = _fresh_audit()
    mf.write_p4_followup(
        audit, activated_at="2026-05-12T10:00:00Z",
        livelock_budget_until="2026-05-19T10:00:00Z",
    )
    block = audit[mf.MANIFEST_KEY]["p4_followup"]
    assert block["activated_at"] == "2026-05-12T10:00:00Z"


def test_append_p5_clarification_appends():
    audit = _fresh_audit()
    mf.append_p5_clarification(
        audit,
        inbound_message_id="dhl-1",
        intent="goods_description",
        confidence=0.92,
        reply_message_id="our-1",
        reply_sha256="b" * 64,
        at="2026-05-12T10:00:00Z",
    )
    mf.append_p5_clarification(
        audit, inbound_message_id="dhl-2", intent="sad_received", confidence=0.97,
    )
    block = audit[mf.MANIFEST_KEY]["p5_clarifications"]
    assert len(block) == 2
    assert block[1]["intent"] == "sad_received"


def test_append_p5_clarification_rejects_bad_intent():
    audit = _fresh_audit()
    with pytest.raises(mf.ManifestSchemaError):
        mf.append_p5_clarification(audit, intent="random_intent")


def test_append_p5_clarification_rejects_confidence_out_of_range():
    audit = _fresh_audit()
    with pytest.raises(mf.ManifestSchemaError):
        mf.append_p5_clarification(audit, intent="invoice", confidence=1.5)
    with pytest.raises(mf.ManifestSchemaError):
        mf.append_p5_clarification(audit, intent="invoice", confidence=-0.1)


def test_write_p6_sad_validates_type():
    audit = _fresh_audit()
    mf.write_p6_sad(audit, type="SAD", sha256="c" * 64, doc_id="d1",
                    arrived_at="2026-05-12T10:00:00Z")
    block = audit[mf.MANIFEST_KEY]["p6_sad"]
    assert block["type"] == "SAD"
    with pytest.raises(mf.ManifestSchemaError):
        mf.write_p6_sad(audit, type="OTHER")


def test_write_p7_pz_validates_status():
    audit = _fresh_audit()
    mf.write_p7_pz(audit, last_status="succeeded", last_run_at="2026-05-12T10:00:00Z")
    assert audit[mf.MANIFEST_KEY]["p7_pz"]["last_status"] == "succeeded"
    with pytest.raises(mf.ManifestSchemaError):
        mf.write_p7_pz(audit, last_status="weird")


# ── Get state convenience ─────────────────────────────────────────────────────

def test_get_state_returns_initial_for_empty_audit():
    audit = _fresh_audit()
    assert mf.get_state(audit) == se.INITIAL_STATE
