"""
test_dhl_selfclearance_p0_email_evidence_rfc822.py — DHL self-clearance
threads use RFC822 References; non-DHL traffic keeps subject-keyed logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import email_evidence_store as ees  # noqa: E402
from app.core.config import settings  # noqa: E402


def test_dhl_selfclearance_message_detected_by_sender():
    msg = {"sender": "odprawacelna@dhl.com", "subject": "Clearance request"}
    assert ees._is_dhl_selfclearance_message(msg) is True


def test_dhl_selfclearance_message_detected_by_to():
    msg = {"to": "odprawacelna@dhl.com", "subject": "x"}
    assert ees._is_dhl_selfclearance_message(msg) is True


def test_dhl_selfclearance_message_detected_in_formatted_envelope():
    msg = {"sender": "DHL Customs <odprawacelna@dhl.com>"}
    assert ees._is_dhl_selfclearance_message(msg) is True


def test_non_dhl_message_returns_false():
    msg = {"sender": "biuro@acspedycja.pl", "to": "import@estrellajewels.eu"}
    assert ees._is_dhl_selfclearance_message(msg) is False


def test_derive_dhl_thread_id_from_references(monkeypatch):
    msg = {
        "sender": "odprawacelna@dhl.com",
        "References": "<root@dhl.com> <reply@dhl.com>",
    }
    tid = ees._derive_dhl_thread_id(msg, awb="AWB1")
    assert tid and tid.startswith("thr:")


def test_save_message_uses_rfc822_for_dhl(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    msg = {
        "message_id": "m1",
        "sender": "odprawacelna@dhl.com",
        "to": "import@estrellajewels.eu",
        "subject": "Clearance Information Required - AWB 9999",
        "References": "<root@dhl.com>",
        "direction": "incoming",
        "timestamp": "2026-05-12T10:00:00",
    }
    result = ees.save_message("9999", msg)
    assert result["action"] in ("inserted", "promoted")
    doc = ees.get_by_awb("9999")
    threads = doc.get("threads", [])
    assert any(t["thread_id"].startswith("thr:") for t in threads)


def test_save_message_keeps_subject_keyed_for_non_dhl(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    msg = {
        "message_id": "m2",
        "sender": "biuro@acspedycja.pl",
        "subject": "Agency forward - AWB 8888",
        "direction": "incoming",
        "timestamp": "2026-05-12T10:00:00",
    }
    ees.save_message("8888", msg)
    doc = ees.get_by_awb("8888")
    threads = doc.get("threads", [])
    # Non-DHL → subject-keyed thread_id (sub: prefix), not RFC822 (thr: prefix).
    assert any(t["thread_id"].startswith("sub:") for t in threads)
