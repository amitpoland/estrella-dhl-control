"""
test_dhl_documents_receipt.py — Tests for POST /api/v1/dhl-documents/{batch_id}/received
focusing on the evidence store bridge added to routes_dhl_documents.py.

Coverage
--------
  1.  Marking DHL docs received sets audit.dhl_documents_received.received = True
  2.  Evidence store summary.dhl_documents_received becomes True after receipt
  3.  Dashboard timeline key reflects 'received' (stage lookup logic)
  4.  Repeated call (idempotency) — no duplicate message in evidence store
  5.  Missing file paths reported but don't block the store write
  6.  Attachment filenames from request are stored in evidence message
  7.  Deterministic message_id: op_dhl_recv:{batch_id}
  8.  Batch linked in evidence store (awb → batch_id)
  9.  Missing AWB in audit — evidence write skipped gracefully (no crash)
 10.  link_batch called with correct awb + batch_id
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import require_api_key
from app.api.routes_dhl_documents import router


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_storage(tmp_path, monkeypatch):
    """Redirect settings.storage_root and email_evidence_store paths to tmp_path."""
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "storage_root", tmp_path, raising=False)

    # Patch evidence store to use tmp_path
    import app.services.email_evidence_store as evs
    monkeypatch.setattr(evs, "_store_root", lambda: tmp_path / "email_evidence", raising=False)
    monkeypatch.setattr(evs, "_master_index", lambda: tmp_path / "email_evidence" / "index.json", raising=False)
    monkeypatch.setattr(evs, "_attach_dir", lambda: tmp_path / "email_evidence" / "attachments", raising=False)

    yield tmp_path


def _make_batch(storage: Path, batch_id: str, awb: str = "9765416334") -> Path:
    """Create a minimal audit.json for a batch under outputs/."""
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "awb": awb, "carrier": "DHL", "status": "blocked"}
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return d / "audit.json"


def _make_file(storage: Path, name: str) -> Path:
    """Create a dummy file on disk so routes_dhl_documents passes the exists check."""
    p = storage / name
    p.write_bytes(b"dummy")
    return p


@pytest.fixture()
def client(tmp_storage, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_summary(awb: str):
    import app.services.email_evidence_store as evs
    return evs.get_by_awb(awb).get("summary", {})


def _get_messages(awb: str):
    import app.services.email_evidence_store as evs
    return [
        m
        for t in evs.get_by_awb(awb).get("threads", [])
        for m in t.get("messages", [])
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_audit_received_flag_set(client, tmp_storage):
    batch_id = "TEST_BATCH_001"
    audit_path = _make_batch(tmp_storage, batch_id)
    doc_file = _make_file(tmp_storage, "ZC429.pdf")

    r = client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "ZC429.pdf", "path": str(doc_file), "type": "ZC429"}],
    })
    assert r.status_code == 200

    audit = json.loads(audit_path.read_text())
    assert audit["dhl_documents_received"]["received"] is True
    assert audit["dhl_documents_received"]["files_count"] == 1


def test_evidence_summary_flips_to_received(client, tmp_storage):
    batch_id = "TEST_BATCH_002"
    _make_batch(tmp_storage, batch_id, awb="1234567890")
    doc_file = _make_file(tmp_storage, "DSK_doc.pdf")

    r = client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "DSK_doc.pdf", "path": str(doc_file), "type": "DSK"}],
    })
    assert r.status_code == 200

    summary = _get_summary("1234567890")
    assert summary.get("dhl_documents_received") is True, (
        f"Expected True, got {summary}"
    )


def test_dashboard_timeline_stage_reads_received(client, tmp_storage):
    """The evidence summary produced matches what the dashboard stage lookup uses."""
    batch_id = "TEST_BATCH_003"
    _make_batch(tmp_storage, batch_id, awb="9876543210")
    doc_file = _make_file(tmp_storage, "SAD.pdf")

    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "SAD.pdf", "path": str(doc_file), "type": "SAD"}],
    })

    summary = _get_summary("9876543210")
    # Dashboard stage: "received" if summary.get("dhl_documents_received") else "missing"
    stage_status = "received" if summary.get("dhl_documents_received") else "missing"
    assert stage_status == "received"


def test_idempotent_no_duplicate_message(client, tmp_storage):
    batch_id = "TEST_BATCH_004"
    _make_batch(tmp_storage, batch_id, awb="1111111111")
    doc_file = _make_file(tmp_storage, "PZC.pdf")

    payload = {"files": [{"name": "PZC.pdf", "path": str(doc_file), "type": "PZC"}]}

    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json=payload)
    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json=payload)

    messages = _get_messages("1111111111")
    op_msgs = [m for m in messages if m.get("message_id") == f"op_dhl_recv:{batch_id}"]
    assert len(op_msgs) == 1, f"Expected 1 message, got {len(op_msgs)}: {op_msgs}"


def test_missing_file_doesnt_block_evidence_write(client, tmp_storage):
    """Files that don't exist on disk are reported but evidence store is still written."""
    batch_id = "TEST_BATCH_005"
    _make_batch(tmp_storage, batch_id, awb="2222222222")
    real_file = _make_file(tmp_storage, "real_DSK.pdf")

    r = client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [
            {"name": "real_DSK.pdf", "path": str(real_file), "type": "DSK"},
            {"name": "missing.pdf",  "path": "/nonexistent/missing.pdf", "type": "SAD"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert "/nonexistent/missing.pdf" in body["missing_paths"]

    # Evidence store written for the real file
    summary = _get_summary("2222222222")
    assert summary.get("dhl_documents_received") is True


def test_attachment_filenames_stored_in_evidence(client, tmp_storage):
    batch_id = "TEST_BATCH_006"
    _make_batch(tmp_storage, batch_id, awb="3333333333")
    f1 = _make_file(tmp_storage, "ZC429_main.pdf")
    f2 = _make_file(tmp_storage, "DSK_clearance.pdf")

    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [
            {"name": "ZC429_main.pdf",   "path": str(f1), "type": "ZC429"},
            {"name": "DSK_clearance.pdf", "path": str(f2), "type": "DSK"},
        ],
    })

    messages = _get_messages("3333333333")
    op_msg = next((m for m in messages if m.get("message_id") == f"op_dhl_recv:{batch_id}"), None)
    assert op_msg is not None
    filenames = [a["filename"] for a in op_msg.get("attachments", [])]
    assert "ZC429_main.pdf" in filenames
    assert "DSK_clearance.pdf" in filenames


def test_deterministic_message_id(client, tmp_storage):
    batch_id = "TEST_BATCH_007"
    _make_batch(tmp_storage, batch_id, awb="4444444444")
    doc_file = _make_file(tmp_storage, "doc.pdf")

    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "doc.pdf", "path": str(doc_file), "type": "DSK"}],
    })

    messages = _get_messages("4444444444")
    assert any(m.get("message_id") == f"op_dhl_recv:{batch_id}" for m in messages)


def test_batch_linked_in_evidence_store(client, tmp_storage):
    batch_id = "TEST_BATCH_008"
    _make_batch(tmp_storage, batch_id, awb="5555555555")
    doc_file = _make_file(tmp_storage, "link_test.pdf")

    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "link_test.pdf", "path": str(doc_file), "type": "SAD"}],
    })

    import app.services.email_evidence_store as evs
    doc = evs.get_by_awb("5555555555")
    assert batch_id in doc.get("batch_ids", [])


def test_missing_awb_in_audit_no_crash(client, tmp_storage):
    """If audit has no AWB, evidence write is skipped gracefully — no 500."""
    batch_id = "TEST_BATCH_009"
    d = tmp_storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    # Audit without awb
    (d / "audit.json").write_text(json.dumps({"batch_id": batch_id, "status": "draft"}))
    doc_file = _make_file(tmp_storage, "no_awb_doc.pdf")

    r = client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "no_awb_doc.pdf", "path": str(doc_file), "type": "DSK"}],
    })
    assert r.status_code == 200


def test_event_type_is_dhl_documents(client, tmp_storage):
    """Message stored in evidence must have event_type='dhl_documents'."""
    batch_id = "TEST_BATCH_010"
    _make_batch(tmp_storage, batch_id, awb="6666666666")
    doc_file = _make_file(tmp_storage, "ev_type_test.pdf")

    client.post(f"/api/v1/dhl-documents/{batch_id}/received", json={
        "files": [{"name": "ev_type_test.pdf", "path": str(doc_file), "type": "DSK"}],
    })

    messages = _get_messages("6666666666")
    op_msg = next((m for m in messages if m.get("message_id") == f"op_dhl_recv:{batch_id}"), None)
    assert op_msg is not None
    assert op_msg["event_type"] == "dhl_documents"
    assert op_msg["direction"] == "incoming"
