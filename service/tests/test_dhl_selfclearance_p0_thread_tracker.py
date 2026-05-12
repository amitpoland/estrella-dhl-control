"""
test_dhl_selfclearance_p0_thread_tracker.py — RFC822 References-based threading.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clearance_manifest as mf  # noqa: E402
from app.services import dhl_thread_tracker as tt  # noqa: E402


def test_parse_message_ids_extracts_angle_bracketed():
    ids = tt.parse_message_ids("<a@x.com> <b@x.com>")
    assert ids == ["a@x.com", "b@x.com"]


def test_parse_message_ids_empty_returns_empty():
    assert tt.parse_message_ids(None) == []
    assert tt.parse_message_ids("") == []


def test_derive_root_prefers_references_over_in_reply_to():
    headers = {
        "References": "<root@dhl.com> <next@dhl.com>",
        "In-Reply-To": "<next@dhl.com>",
        "Message-ID": "<this@us.com>",
    }
    assert tt.derive_root_message_id(headers) == "root@dhl.com"


def test_derive_root_falls_back_to_in_reply_to():
    assert tt.derive_root_message_id({
        "In-Reply-To": "<parent@dhl.com>",
        "Message-ID": "<this@us.com>",
    }) == "parent@dhl.com"


def test_derive_root_falls_back_to_message_id():
    assert tt.derive_root_message_id({
        "Message-ID": "<solo@us.com>",
    }) == "solo@us.com"


def test_derive_root_no_headers_returns_none():
    assert tt.derive_root_message_id({}) is None


def test_resolve_thread_id_uses_references(monkeypatch):
    tid, src = tt.resolve_thread_id(
        {"References": "<root@dhl.com>"}, awb="AWB123",
    )
    assert tid.startswith("thr:")
    assert src == "references"


def test_resolve_thread_id_uses_message_id_for_first_message():
    tid, src = tt.resolve_thread_id(
        {"Message-ID": "<first@dhl.com>"}, awb="AWB123",
    )
    assert tid.startswith("thr:")
    assert src == "message_id"


def test_resolve_thread_id_awb_fallback(monkeypatch):
    # Patch evidence.get_by_awb to return a stored thread
    from app.services import dhl_thread_tracker as ttmod

    def fake_get_by_awb(awb):
        return {"threads": [{"thread_id": "thr:stored_primary"}]}

    monkeypatch.setattr(ttmod.evidence, "get_by_awb", fake_get_by_awb)
    tid, src = tt.resolve_thread_id({}, awb="AWB123")
    assert tid == "thr:stored_primary"
    assert src == "awb_fallback"


def test_resolve_thread_id_no_evidence(monkeypatch):
    from app.services import dhl_thread_tracker as ttmod

    def fake_get_by_awb(awb):
        return {"threads": []}

    monkeypatch.setattr(ttmod.evidence, "get_by_awb", fake_get_by_awb)
    tid, src = tt.resolve_thread_id({}, awb="AWB123")
    assert tid == ""
    assert src == "no_evidence"


def test_record_alias_if_new_sets_primary_first():
    audit = {}
    appended = tt.record_alias_if_new(audit, "thr:first")
    # First call establishes primary; not an alias.
    assert appended is False
    assert audit[mf.MANIFEST_KEY]["thread_id"] == "thr:first"


def test_record_alias_if_new_records_distinct_alias():
    audit = {mf.MANIFEST_KEY: {
        "state": "awaiting_preemptive_send",
        "state_history": [],
        "thread_id": "thr:primary",
        "thread_id_aliases": [],
        "p2_dispatch": {}, "p3_tracking": {}, "p4_followup": {},
        "p5_clarifications": [], "p6_sad": {}, "p7_pz": {},
    }}
    assert tt.record_alias_if_new(audit, "thr:alt") is True
    assert "thr:alt" in audit[mf.MANIFEST_KEY]["thread_id_aliases"]


def test_record_alias_dedupes_existing():
    audit = {mf.MANIFEST_KEY: {
        "state": "awaiting_preemptive_send",
        "state_history": [],
        "thread_id": "thr:primary",
        "thread_id_aliases": ["thr:alt"],
        "p2_dispatch": {}, "p3_tracking": {}, "p4_followup": {},
        "p5_clarifications": [], "p6_sad": {}, "p7_pz": {},
    }}
    assert tt.record_alias_if_new(audit, "thr:alt") is False


def test_record_alias_same_as_primary_returns_false():
    audit = {mf.MANIFEST_KEY: {
        "state": "awaiting_preemptive_send",
        "state_history": [],
        "thread_id": "thr:primary",
        "thread_id_aliases": [],
        "p2_dispatch": {}, "p3_tracking": {}, "p4_followup": {},
        "p5_clarifications": [], "p6_sad": {}, "p7_pz": {},
    }}
    assert tt.record_alias_if_new(audit, "thr:primary") is False
