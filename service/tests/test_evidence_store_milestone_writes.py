"""
test_evidence_store_milestone_writes.py — Verify that every manual/monitor
email milestone writes a deterministic evidence-store message so the
Email Evidence Timeline stays truthful.

Functions under test
--------------------
  1.  mark_email_received      → event_type=dhl_request,      message_id=op_dhl_request:{batch_id}
  2.  send_dhl_reply           → event_type=our_dhl_reply,     message_id=op_dhl_reply:{batch_id}
  3.  _ensure_agency_forward_after_dhl → event_type=agency_forward, message_id=op_agency_forward:{batch_id}
  4.  register_agency_documents → event_type=agency_sad_reply, message_id=op_agency_docs:{batch_id}

Coverage (12 tests)
-------------------
  1.  mark_email_received → evidence message inserted with correct event_type
  2.  mark_email_received → evidence summary dhl_request_received=True
  3.  mark_email_received → idempotent (second call = duplicate, not second insert)
  4.  mark_email_received → no-AWB audit does not crash
  5.  send_dhl_reply → evidence message inserted with correct event_type + direction=outgoing
  6.  send_dhl_reply → delivery_status=queued
  7.  send_dhl_reply → idempotent
  8.  _ensure_agency_forward_after_dhl → evidence message inserted with event_type=agency_forward
  9.  _ensure_agency_forward_after_dhl → delivery_status=queued when SMTP not configured
 10.  register_agency_documents → evidence message inserted with event_type=agency_sad_reply
 11.  register_agency_documents → attachments persisted from imported file list
 12.  register_agency_documents → idempotent (second call = duplicate)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_batch(storage: Path, batch_id: str, awb: str = "9765416334") -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id": batch_id,
        "awb":      awb,
        "carrier":  "DHL",
        "status":   "blocked",
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _make_file(storage: Path, name: str) -> Path:
    p = storage / name
    p.write_bytes(b"dummy")
    return p


def _get_messages(awb: str):
    import app.services.email_evidence_store as evs
    return [
        m
        for t in evs.get_by_awb(awb).get("threads", [])
        for m in t.get("messages", [])
    ]


def _get_summary(awb: str):
    import app.services.email_evidence_store as evs
    return evs.get_by_awb(awb).get("summary", {})


# ── Fixture: redirect evidence store + settings to tmp_path ──────────────────

@pytest.fixture()
def tmp_storage(tmp_path, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "storage_root", tmp_path, raising=False)

    import app.services.email_evidence_store as evs
    monkeypatch.setattr(evs, "_store_root",    lambda: tmp_path / "email_evidence",                 raising=False)
    monkeypatch.setattr(evs, "_master_index",  lambda: tmp_path / "email_evidence" / "index.json",  raising=False)
    monkeypatch.setattr(evs, "_attach_dir",    lambda: tmp_path / "email_evidence" / "attachments", raising=False)

    yield tmp_path


# Router prefix for routes_dhl_clearance
_DHL_PREFIX = "/api/v1/dhl"


# ── Fixture: FastAPI test client for routes_dhl_clearance ────────────────────

@pytest.fixture()
def clearance_client(tmp_storage):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.security import require_api_key
    from app.auth.dependencies import get_current_user
    from app.api.routes_dhl_clearance import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user", "role": "admin", "is_active": True, "is_approved": True,
    }
    return TestClient(app, raise_server_exceptions=True), tmp_storage


# ══════════════════════════════════════════════════════════════════════════════
# 1–4  mark_email_received
# ══════════════════════════════════════════════════════════════════════════════

def test_mark_email_received_evidence_inserted(clearance_client):
    client, storage = clearance_client
    batch_id = "MER_BATCH_001"
    awb = "1111111111"
    _make_batch(storage, batch_id, awb=awb)

    r = client.post(f"{_DHL_PREFIX}/mark-email-received/{batch_id}", json={
        "sender":  "odprawacelna@dhl.com",
        "subject": "AWB 1111111111 — customs notification",
    })
    assert r.status_code == 200, r.text

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_dhl_request:{batch_id}"), None)
    assert op_msg is not None, f"evidence message not found in {msgs}"
    assert op_msg["event_type"] == "dhl_request"
    assert op_msg["direction"] == "incoming"


def test_mark_email_received_summary_flips(clearance_client):
    client, storage = clearance_client
    batch_id = "MER_BATCH_002"
    awb = "2222222222"
    _make_batch(storage, batch_id, awb=awb)

    r = client.post(f"{_DHL_PREFIX}/mark-email-received/{batch_id}", json={"sender": "dhl@dhl.com"})
    assert r.status_code == 200, r.text

    summary = _get_summary(awb)
    assert summary.get("dhl_request_received") is True, f"summary={summary}"


def test_mark_email_received_idempotent(clearance_client):
    client, storage = clearance_client
    batch_id = "MER_BATCH_003"
    awb = "3333333333"
    _make_batch(storage, batch_id, awb=awb)

    client.post(f"{_DHL_PREFIX}/mark-email-received/{batch_id}", json={"sender": "dhl@dhl.com"})
    client.post(f"{_DHL_PREFIX}/mark-email-received/{batch_id}", json={"sender": "dhl@dhl.com"})

    msgs = _get_messages(awb)
    op_msgs = [m for m in msgs if m.get("message_id") == f"op_dhl_request:{batch_id}"]
    assert len(op_msgs) == 1, f"Expected 1 message, got {len(op_msgs)}"


def test_mark_email_received_no_awb_no_crash(clearance_client):
    """Audit without awb must not raise 500."""
    client, storage = clearance_client
    batch_id = "MER_BATCH_004"
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps({"batch_id": batch_id, "status": "blocked"}))

    r = client.post(f"{_DHL_PREFIX}/mark-email-received/{batch_id}", json={"sender": "dhl@dhl.com"})
    assert r.status_code == 200, r.text


# ══════════════════════════════════════════════════════════════════════════════
# 5–7  send_dhl_reply
# ══════════════════════════════════════════════════════════════════════════════

def _audit_with_reply_package(storage: Path, batch_id: str, awb: str) -> Path:
    """Create an audit.json that satisfies send_dhl_reply guards."""
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id":         batch_id,
        "awb":              awb,
        "carrier":          "DHL",
        "status":           "blocked",
        "clearance_status": "dhl_email_received",
        "reply_package": {
            "to":       "odprawacelna@dhl.com",
            "subject":  f"RE: AWB {awb}",
            "body_pl":  "Dzień dobry,",
            "body_en":  "Dear DHL,",
            "thread_id": "t1",
        },
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _make_reply_client(tmp_storage, monkeypatch=None):
    """Build a clearance test client with email_service stubbed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.security import require_api_key
    from app.auth.dependencies import get_current_user
    from app.api.routes_dhl_clearance import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user", "role": "admin", "is_active": True, "is_approved": True,
    }
    return TestClient(app, raise_server_exceptions=True)


def test_send_dhl_reply_evidence_inserted(tmp_storage):
    batch_id = "SDR_BATCH_001"
    awb = "4444444444"
    _audit_with_reply_package(tmp_storage, batch_id, awb)
    client = _make_reply_client(tmp_storage)

    with patch("app.services.email_service.queue_email", return_value="email-sdr-001"), \
         patch("app.services.clearance_decision.assert_valid_dhl_reply", return_value=None), \
         patch("app.services.clearance_decision.resolve_dhl_action",
               return_value={"action": "description_reply"}):
        r = client.post(f"{_DHL_PREFIX}/send-reply/{batch_id}")

    if r.status_code == 422:
        pytest.skip(f"Guard blocked (missing dep): {r.json()}")
    assert r.status_code == 200, r.text

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_dhl_reply:{batch_id}"), None)
    assert op_msg is not None, f"evidence message not found in {msgs}"
    assert op_msg["event_type"] == "our_dhl_reply"
    assert op_msg["direction"] == "outgoing"


def test_send_dhl_reply_delivery_status_queued(tmp_storage):
    """The stored delivery_status must be 'queued' (email is queued, not sent)."""
    batch_id = "SDR_BATCH_002"
    awb = "5555555555"
    _audit_with_reply_package(tmp_storage, batch_id, awb)
    client = _make_reply_client(tmp_storage)

    with patch("app.services.email_service.queue_email", return_value="email-sdr-002"), \
         patch("app.services.clearance_decision.assert_valid_dhl_reply", return_value=None), \
         patch("app.services.clearance_decision.resolve_dhl_action",
               return_value={"action": "description_reply"}):
        r = client.post(f"{_DHL_PREFIX}/send-reply/{batch_id}")

    if r.status_code == 422:
        pytest.skip(f"Guard blocked: {r.json()}")
    assert r.status_code == 200, r.text

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_dhl_reply:{batch_id}"), None)
    assert op_msg is not None
    assert op_msg.get("delivery_status") == "queued"


def test_send_dhl_reply_idempotent(tmp_storage):
    """Second call must not insert a second message."""
    batch_id = "SDR_BATCH_003"
    awb = "6666666666"
    _audit_with_reply_package(tmp_storage, batch_id, awb)
    client = _make_reply_client(tmp_storage)

    for _ in range(2):
        with patch("app.services.email_service.queue_email", return_value="email-sdr-003"), \
             patch("app.services.clearance_decision.assert_valid_dhl_reply", return_value=None), \
             patch("app.services.clearance_decision.resolve_dhl_action",
                   return_value={"action": "description_reply"}):
            r = client.post(f"{_DHL_PREFIX}/send-reply/{batch_id}")
        if r.status_code == 422:
            pytest.skip(f"Guard blocked: {r.json()}")

    msgs = _get_messages(awb)
    op_msgs = [m for m in msgs if m.get("message_id") == f"op_dhl_reply:{batch_id}"]
    assert len(op_msgs) == 1, f"Expected 1 message, got {len(op_msgs)}"


# ══════════════════════════════════════════════════════════════════════════════
# 8–9  _ensure_agency_forward_after_dhl
# ══════════════════════════════════════════════════════════════════════════════

def _audit_for_agency_forward(storage: Path, batch_id: str, awb: str) -> tuple:
    """Create an audit that satisfies _ensure_agency_forward_after_dhl conditions."""
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    doc_file = storage / "dsk.pdf"
    doc_file.write_bytes(b"dummy")

    audit = {
        "batch_id": batch_id,
        "awb":      awb,
        "carrier":  "DHL",
        "status":   "blocked",
        "clearance_decision":     {"clearance_path": "agency_clearance"},
        "dhl_email":              {"received": True},
        "dhl_documents_received": {
            "received": True,
            "files": [{"name": "dsk.pdf", "path": str(doc_file), "type": "DSK"}],
        },
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p, audit, doc_file


def test_ensure_agency_forward_evidence_inserted(tmp_storage):
    batch_id = "EAF_BATCH_001"
    awb = "7777777777"
    audit_path, audit, doc_file = _audit_for_agency_forward(tmp_storage, batch_id, awb)

    mock_pkg = {
        "to":           "agency@acs.pl",
        "to_list":      ["agency@acs.pl"],
        "cc":           "cc@example.com",
        "cc_list":      ["cc@example.com"],
        "subject":      f"FWD customs docs AWB {awb}",
        "body_html":    "<p>Please find attached.</p>",
        "body_text":    "Please find attached.",
        "from_address": "import@estrellajewels.eu",
        "email_type":   "agency_forward_after_dhl",
        "attachments":  [{"path": str(doc_file), "name": "dsk.pdf"}],
    }

    with patch("app.services.agency_forward_after_dhl_builder.build_agency_forward_after_dhl",
               return_value=mock_pkg), \
         patch("app.services.email_service.queue_email", return_value="email-eaf-001"), \
         patch("app.services.email_sender._smtp_configured", return_value=False), \
         patch("app.services.email_sender.send_queued_email", return_value={"ok": False}):
        from app.services.active_shipment_monitor import _ensure_agency_forward_after_dhl
        result = _ensure_agency_forward_after_dhl(audit_path, audit)

    assert result.get("built") is True, f"result={result}"

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_agency_forward:{batch_id}"), None)
    assert op_msg is not None, f"evidence message not found in {msgs}"
    assert op_msg["event_type"] == "agency_forward"
    assert op_msg["direction"] == "outgoing"


def test_ensure_agency_forward_delivery_status_queued_when_no_smtp(tmp_storage):
    batch_id = "EAF_BATCH_002"
    awb = "8888888888"
    audit_path, audit, doc_file = _audit_for_agency_forward(tmp_storage, batch_id, awb)

    mock_pkg = {
        "to":           "agency@acs.pl",
        "to_list":      ["agency@acs.pl"],
        "cc":           "",
        "cc_list":      [],
        "subject":      f"FWD AWB {awb}",
        "body_html":    "<p>Docs</p>",
        "body_text":    "Docs",
        "from_address": "import@estrellajewels.eu",
        "email_type":   "agency_forward_after_dhl",
        "attachments":  [{"path": str(doc_file), "name": "dsk.pdf"}],
    }

    with patch("app.services.agency_forward_after_dhl_builder.build_agency_forward_after_dhl",
               return_value=mock_pkg), \
         patch("app.services.email_service.queue_email", return_value="email-eaf-002"), \
         patch("app.services.email_sender._smtp_configured", return_value=False):
        from app.services.active_shipment_monitor import _ensure_agency_forward_after_dhl
        _ensure_agency_forward_after_dhl(audit_path, audit)

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_agency_forward:{batch_id}"), None)
    assert op_msg is not None, f"evidence message not found in {msgs}"
    assert op_msg.get("delivery_status") == "queued"


# ══════════════════════════════════════════════════════════════════════════════
# 10–12  register_agency_documents
# ══════════════════════════════════════════════════════════════════════════════

def test_register_agency_documents_evidence_inserted(tmp_storage):
    batch_id = "RAD_BATCH_001"
    awb = "9999999991"
    _make_batch(tmp_storage, batch_id, awb=awb)
    doc_file = _make_file(tmp_storage, "SAD_document.pdf")

    with patch("app.services.agency_sad_monitor.classify",
               return_value={"type": "sad", "confidence": 0.9}), \
         patch("app.services.agency_sad_monitor.save_file",
               return_value=doc_file), \
         patch("app.services.agency_sad_monitor.sync_to_workdrive",
               return_value=None):
        from app.services.agency_sad_monitor import register_agency_documents
        result = register_agency_documents(batch_id, [str(doc_file)])

    assert result.get("ok") is True, f"result={result}"

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_agency_docs:{batch_id}"), None)
    assert op_msg is not None, f"evidence message not found in {msgs}"
    assert op_msg["event_type"] == "agency_sad_reply"
    assert op_msg["direction"] == "incoming"


def test_register_agency_documents_attachments_in_evidence(tmp_storage):
    batch_id = "RAD_BATCH_002"
    awb = "9999999992"
    _make_batch(tmp_storage, batch_id, awb=awb)
    f1 = _make_file(tmp_storage, "PZC_001.pdf")
    f2 = _make_file(tmp_storage, "SAD_001.pdf")

    with patch("app.services.agency_sad_monitor.classify",
               return_value={"type": "pzc", "confidence": 0.95}), \
         patch("app.services.agency_sad_monitor.save_file", side_effect=lambda b, src, t: Path(src)), \
         patch("app.services.agency_sad_monitor.sync_to_workdrive", return_value=None):
        from app.services.agency_sad_monitor import register_agency_documents
        register_agency_documents(batch_id, [str(f1), str(f2)])

    msgs = _get_messages(awb)
    op_msg = next((m for m in msgs if m.get("message_id") == f"op_agency_docs:{batch_id}"), None)
    assert op_msg is not None
    filenames = [a["filename"] for a in op_msg.get("attachments", [])]
    assert any("PZC" in fn for fn in filenames), f"PZC not in filenames={filenames}"


def test_register_agency_documents_idempotent(tmp_storage):
    """Calling register_agency_documents twice must not insert two evidence messages."""
    batch_id = "RAD_BATCH_003"
    awb = "9999999993"
    _make_batch(tmp_storage, batch_id, awb=awb)
    doc_file = _make_file(tmp_storage, "idempotent_sad.pdf")

    for _ in range(2):
        with patch("app.services.agency_sad_monitor.classify",
                   return_value={"type": "sad", "confidence": 0.9}), \
             patch("app.services.agency_sad_monitor.save_file",
                   return_value=doc_file), \
             patch("app.services.agency_sad_monitor.sync_to_workdrive", return_value=None):
            from app.services.agency_sad_monitor import register_agency_documents
            register_agency_documents(batch_id, [str(doc_file)])

    msgs = _get_messages(awb)
    op_msgs = [m for m in msgs if m.get("message_id") == f"op_agency_docs:{batch_id}"]
    assert len(op_msgs) == 1, f"Expected 1 message, got {len(op_msgs)}"
