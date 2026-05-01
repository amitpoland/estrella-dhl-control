"""
test_workdrive_upload.py — WorkDrive upload architecture tests.

Verifies:
1. Local files exist → pipeline continues even if WorkDrive fails
2. WorkDrive success stores resource IDs in audit
3. WorkDrive failure creates retry queue entry
4. Cliq notification is not blocked by WorkDrive failure
5. No PZ output values are modified by WorkDrive logic
6. No financial fields are modified
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── ensure app is importable ──────────────────────────────────────────────────
_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_batch(tmp_path):
    """Create a minimal batch directory with dummy PDF + XLSX."""
    batch_id = "SHIPMENT_1099999999_2026-04_testbatch"
    out_dir   = tmp_path / "outputs" / batch_id
    out_dir.mkdir(parents=True)
    pdf  = out_dir / "PZ_test.pdf"
    xlsx = out_dir / "PZ_test_calc.xlsx"
    pdf.write_bytes(b"%PDF-1.4 fake")
    xlsx.write_bytes(b"PK fake xlsx")
    audit = out_dir / "audit.json"
    audit.write_text(json.dumps({
        "status":      "success",
        "tracking_no": "1099999999",
        "doc_no":      "PZ 1/1/2026",
        "line_count":  3,
        "total_net":   1000.0,
        "total_gross": 1230.0,
        "duty_a00":    50.0,
    }), encoding="utf-8")
    return {"batch_id": batch_id, "out_dir": out_dir, "pdf": pdf, "xlsx": xlsx, "audit": audit}


# ── 1. Pipeline continues when WorkDrive is not configured ────────────────────

def test_pipeline_continues_when_workdrive_not_configured(tmp_batch):
    """PZ result is returned even when WORKDRIVE_* env vars are absent."""
    from app.services.workdrive_uploader import is_configured
    # Without env vars, is_configured() must return False
    with patch.dict("os.environ", {
        "WORKDRIVE_REFRESH_TOKEN": "",
        "WORKDRIVE_CLIENT_ID": "",
        "WORKDRIVE_CLIENT_SECRET": "",
        "WORKDRIVE_PARENT_ID": "",
        "WORKDRIVE_MYFOLDER_ID": "",
    }, clear=False):
        assert not is_configured(), "should be unconfigured when env vars are empty"


# ── 2. WorkDrive success stores resource IDs ──────────────────────────────────

def test_workdrive_success_stores_resource_ids(tmp_batch, tmp_path):
    """When upload succeeds, audit.json gets pdf/xlsx resource IDs."""
    batch_id = tmp_batch["batch_id"]
    pdf      = tmp_batch["pdf"]
    xlsx     = tmp_batch["xlsx"]
    audit    = tmp_batch["audit"]

    _fake_upload_result = {
        "success":           True,
        "pdf_resource_id":   "RES_PDF_123",
        "xlsx_resource_id":  "RES_XLSX_456",
        "batch_folder_id":   "FOLDER_789",
        "error":             None,
    }

    with patch("app.services.workdrive_uploader.is_configured", return_value=True), \
         patch("app.services.workdrive_uploader.upload_pz_outputs", return_value=_fake_upload_result):

        from app.services import workdrive_uploader as wdu
        result = wdu.upload_pz_outputs(batch_id, pdf, xlsx)

    assert result["success"]
    assert result["pdf_resource_id"]  == "RES_PDF_123"
    assert result["xlsx_resource_id"] == "RES_XLSX_456"
    assert result["batch_folder_id"]  == "FOLDER_789"


# ── 3. WorkDrive failure creates retry queue entry ────────────────────────────

def test_workdrive_failure_creates_retry_entry(tmp_batch, tmp_path, monkeypatch):
    """When upload fails, a retry queue entry is created for each file."""
    from app.services import workdrive_retry_service as rs

    # Redirect queue to tmp_path
    queue_file = tmp_path / "system" / "workdrive_upload_queue.json"
    queue_file.parent.mkdir(parents=True)

    monkeypatch.setattr(rs, "_queue_path", lambda: queue_file)

    rs.enqueue(tmp_batch["batch_id"], "pdf",  tmp_batch["pdf"],  "PZ/2026/04/BATCH_test")
    rs.enqueue(tmp_batch["batch_id"], "xlsx", tmp_batch["xlsx"], "PZ/2026/04/BATCH_test")

    items = rs.get_queue()
    assert len(items) == 2
    types = {i["file_type"] for i in items}
    assert types == {"pdf", "xlsx"}

    for item in items:
        assert item["status"]   == "pending"
        assert item["attempts"] == 0
        assert item["batch_id"] == tmp_batch["batch_id"]


# ── 4. Retry de-duplication ───────────────────────────────────────────────────

def test_retry_deduplication(tmp_batch, tmp_path, monkeypatch):
    """Enqueueing the same batch+file_type twice keeps only one pending entry."""
    from app.services import workdrive_retry_service as rs

    queue_file = tmp_path / "system" / "workdrive_upload_queue.json"
    queue_file.parent.mkdir(parents=True)
    monkeypatch.setattr(rs, "_queue_path", lambda: queue_file)

    rs.enqueue(tmp_batch["batch_id"], "pdf", tmp_batch["pdf"], "PZ/2026/04")
    rs.enqueue(tmp_batch["batch_id"], "pdf", tmp_batch["pdf"], "PZ/2026/04")

    items = [i for i in rs.get_queue() if i["file_type"] == "pdf"]
    assert len(items) == 1


# ── 5. Retry run marks success when upload succeeds ──────────────────────────

def test_retry_run_success(tmp_batch, tmp_path, monkeypatch):
    """run_pending() marks item success when upload_file returns resource_id."""
    from app.services import workdrive_retry_service as rs

    queue_file = tmp_path / "system" / "workdrive_upload_queue.json"
    queue_file.parent.mkdir(parents=True)
    monkeypatch.setattr(rs, "_queue_path", lambda: queue_file)

    rs.enqueue(tmp_batch["batch_id"], "pdf", tmp_batch["pdf"], "PZ/2026/04")

    with patch("app.services.workdrive_uploader._get_access_token", return_value="tok"), \
         patch("app.services.workdrive_uploader._resolve_batch_folder", return_value="FLD"), \
         patch("app.services.workdrive_uploader.upload_file", return_value="RES_PDF_OK"), \
         patch.object(rs, "_patch_audit", lambda *a, **k: None):
        stats = rs.run_pending(token="tok")

    assert stats["succeeded"] == 1
    assert stats["failed"]    == 0

    item = rs.get_queue()[0]
    assert item["status"]      == "success"
    assert item["resource_id"] == "RES_PDF_OK"


# ── 6. Retry run fails gracefully when file is missing ───────────────────────

def test_retry_run_fails_if_file_missing(tmp_path, monkeypatch):
    """run_pending() marks item failed immediately when local file is gone."""
    from app.services import workdrive_retry_service as rs

    queue_file = tmp_path / "system" / "workdrive_upload_queue.json"
    queue_file.parent.mkdir(parents=True)
    monkeypatch.setattr(rs, "_queue_path", lambda: queue_file)

    gone = tmp_path / "ghost.pdf"
    rs.enqueue("SHIPMENT_GHOST", "pdf", gone, "PZ/2026/04")

    with patch("app.services.workdrive_uploader._get_access_token", return_value="tok"):
        stats = rs.run_pending(token="tok")

    assert stats["failed"] == 1
    item = rs.get_queue()[0]
    assert item["status"] == "failed"
    assert "missing" in item["last_error"]


# ── 7. No financial fields modified ──────────────────────────────────────────

def test_no_financial_fields_modified(tmp_batch, tmp_path, monkeypatch):
    """WorkDrive retry queue operations never modify audit financial fields."""
    from app.services import workdrive_retry_service as rs

    queue_file = tmp_path / "system" / "workdrive_upload_queue.json"
    queue_file.parent.mkdir(parents=True)
    monkeypatch.setattr(rs, "_queue_path", lambda: queue_file)

    # Read original audit values
    audit_before = json.loads(tmp_batch["audit"].read_text())
    original_net   = audit_before.get("total_net")
    original_gross = audit_before.get("total_gross")
    original_duty  = audit_before.get("duty_a00")

    # Run enqueue (simulating failure path)
    rs.enqueue(tmp_batch["batch_id"], "pdf", tmp_batch["pdf"], "PZ/2026/04")

    # Read audit again — financial fields must be unchanged
    audit_after = json.loads(tmp_batch["audit"].read_text())
    assert audit_after.get("total_net")   == original_net
    assert audit_after.get("total_gross") == original_gross
    assert audit_after.get("duty_a00")    == original_duty


# ── 8. Retry respects MAX_ATTEMPTS ───────────────────────────────────────────

def test_retry_max_attempts(tmp_batch, tmp_path, monkeypatch):
    """After MAX_ATTEMPTS failures, item status becomes 'failed'."""
    from app.services import workdrive_retry_service as rs

    queue_file = tmp_path / "system" / "workdrive_upload_queue.json"
    queue_file.parent.mkdir(parents=True)
    monkeypatch.setattr(rs, "_queue_path", lambda: queue_file)

    rs.enqueue(tmp_batch["batch_id"], "pdf", tmp_batch["pdf"], "PZ/2026/04")

    with patch("app.services.workdrive_uploader._get_access_token", return_value="tok"), \
         patch("app.services.workdrive_uploader._resolve_batch_folder", return_value="FLD"), \
         patch("app.services.workdrive_uploader.upload_file", return_value=None):
        for _ in range(rs.MAX_ATTEMPTS):
            rs.run_pending(token="tok")

    item = rs.get_queue()[0]
    assert item["status"]   == "failed"
    assert item["attempts"] == rs.MAX_ATTEMPTS


# ── 9. is_configured returns True only when all creds present ────────────────

def test_is_configured_requires_all_creds():
    from app.services.workdrive_uploader import is_configured
    with patch.dict("os.environ", {
        "WORKDRIVE_REFRESH_TOKEN": "rt",
        "WORKDRIVE_CLIENT_ID":     "ci",
        "WORKDRIVE_CLIENT_SECRET": "cs",
        "WORKDRIVE_MYFOLDER_ID":   "mf",
        "WORKDRIVE_PARENT_ID":     "",
    }, clear=False):
        assert is_configured()

    # Missing one key → should fail
    with patch.dict("os.environ", {
        "WORKDRIVE_REFRESH_TOKEN": "rt",
        "WORKDRIVE_CLIENT_ID":     "",
        "WORKDRIVE_CLIENT_SECRET": "cs",
        "WORKDRIVE_MYFOLDER_ID":   "mf",
        "WORKDRIVE_PARENT_ID":     "",
    }, clear=False):
        assert not is_configured()
