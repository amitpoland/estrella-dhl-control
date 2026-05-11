"""
Regression: email_evidence_store must import without error on Windows
(no bare top-level `import fcntl`).

Covers the HTTP 500 bug where routes_dashboard.email_evidence_for_batch
crashed on every call because email_evidence_store.py had an unconditional
`import fcntl` at module level — a POSIX-only module absent on Windows.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def test_module_imports_without_fcntl_error(tmp_path, monkeypatch):
    """email_evidence_store must import successfully regardless of platform."""
    import app.services.email_evidence_store as evs  # noqa: F401 — import is the test


def test_awb_lock_works_on_current_platform(tmp_path, monkeypatch):
    """_awb_lock must acquire and release without raising on the current platform."""
    monkeypatch.setattr(
        "app.core.config.settings.storage_root", tmp_path, raising=False
    )
    import app.services.email_evidence_store as evs
    importlib.reload(evs)  # pick up patched storage_root

    with evs._awb_lock("TEST123456") as p:
        assert p.exists()


def test_save_and_get_roundtrip(tmp_path, monkeypatch):
    """Basic save_message + get_by_awb round-trip must work after the locking fix."""
    monkeypatch.setattr(
        "app.core.config.settings.storage_root", tmp_path, raising=False
    )
    import app.services.email_evidence_store as evs
    importlib.reload(evs)

    result = evs.save_message(
        "1234567890",
        {
            "message_id": "msg-001",
            "thread_id": "thread-001",
            "direction": "incoming",
            "event_type": "dhl_request",
            "sender": "dhl@dhl.com",
            "subject": "Test",
            "timestamp": "2026-05-10T12:00:00",
        },
    )
    assert result["action"] == "inserted"
    assert result["message_id"] == "msg-001"

    doc = evs.get_by_awb("1234567890")
    assert doc["awb"] == "1234567890"
    assert len(doc["threads"]) == 1
    assert doc["summary"]["dhl_request_received"] is True
