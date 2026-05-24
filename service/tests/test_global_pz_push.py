"""
test_global_pz_push.py
Unit tests for global_pz_push.py service.

Coverage:
  01. Blocked: wrong/missing confirm_understanding sentinel
  02. Blocked: empty operator_reason
  03. Blocked: wfirma_correction_push_allowed=False (default)
  04. Blocked: missing staged correction execution record
  05. Blocked: staged option is KEEP_CURRENT
  06. Blocked: staged option is NO_ACTION
  07. Blocked: terminal PZ event already in audit timeline (EV_WFIRMA_PZ_CREATED)
  08. Blocked: terminal PZ event already in audit timeline (wfirma_pz_adopted)
  09. Blocked: pz_rows.json missing or empty
  10. Blocked: product_map empty (no mappings)
  11. Blocked: all rows unmapped (no good_id for any product_code)
  12. Idempotency: second call with same (option_id, idempotency_key) -> already_pushed
  13. Success: ALIGN_TO_AUTHORITY -> pushed, push record written, audit patched
  14. Success: SPLIT_TO_STYLE_LEVEL -> pushed, push record written
  15. Failed: wFirma returns ok=False -> status=failed, no push record written
  16. Warnings: partially unmapped rows (some resolved, some skipped)
  17. No routes_* import (no circular dependency)
  18. Push record format: all required keys present
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path to the service under test (for AST checks)
# ---------------------------------------------------------------------------

_SVC = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "global_pz_push.py"
)

# ---------------------------------------------------------------------------
# Constants mirrored from the service
# ---------------------------------------------------------------------------

_CONFIRM_SENTINEL = (
    "I confirm this will create a new wFirma PZ document "
    "and cannot be undone without manual wFirma intervention"
)

_PRODUCT_MAP: Dict[str, str] = {"INV-01": "GID_001", "INV-02": "GID_002"}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_batch_dir(tmp_path: Path, batch_id: str = "BATCH_001") -> Path:
    bdir = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True)
    return bdir


def _write_exec_record(bdir: Path, option_id: str = "ALIGN_TO_AUTHORITY") -> None:
    record = {
        "batch_id":         "BATCH_001",
        "option_id":        option_id,
        "operator_reason":  "test run",
        "executed_at":      "2026-05-24T10:00:00+00:00",
        "pre_line_count":   3,
        "post_line_count":  3,
        "backup_path":      "",
        "rollback_command": "No rollback needed.",
        "wfirma_action":    "product_code_rename_in_staging",
        "notes":            [],
    }
    (bdir / "correction_execution_record.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )


def _write_pz_rows(bdir: Path, rows: Optional[List[Dict]] = None) -> None:
    if rows is None:
        rows = [
            {"product_code": "INV-01", "quantity": 10.0, "unit_netto_pln": 50.0},
            {"product_code": "INV-02", "quantity": 5.0,  "unit_netto_pln": 80.0},
        ]
    (bdir / "pz_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )


def _write_audit(bdir: Path, timeline: Optional[List] = None) -> None:
    audit: Dict[str, Any] = {
        "batch_id":      "BATCH_001",
        "timeline":      timeline or [],
        "wfirma_export": {},
    }
    (bdir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture()
def svc():
    from service.app.services import global_pz_push as _mod
    return _mod


def _call_push(
    svc,
    tmp_path: Path,
    batch_id: str = "BATCH_001",
    push_allowed: bool = True,
    confirm: str = _CONFIRM_SENTINEL,
    operator_reason: str = "test push",
    idempotency_key: str = "idem-key-001",
    product_map: Optional[Dict] = None,
    wfirma_ok: bool = True,
    wfirma_doc_id: str = "PZ_WFIRMA_999",
):
    """Call push_correction_to_wfirma with mocked settings and wFirma client."""
    pz_result_mock = SimpleNamespace(
        ok=wfirma_ok,
        wfirma_pz_doc_id=wfirma_doc_id if wfirma_ok else "",
        error=None if wfirma_ok else "wFirma API error",
    )

    mock_settings = MagicMock()
    mock_settings.wfirma_correction_push_allowed = push_allowed
    mock_settings.wfirma_supplier_contractor_id  = "CONTRACTOR_999"
    mock_settings.wfirma_warehouse_id            = "WH_001"
    mock_settings.storage_root                   = tmp_path

    if product_map is None:
        product_map = _PRODUCT_MAP

    with (
        patch.object(svc, "settings", mock_settings),
        patch.object(svc, "_log_timeline_event", return_value="ev:1"),
        patch(
            "service.app.services.wfirma_client.create_warehouse_pz",
            return_value=pz_result_mock,
        ),
    ):
        return svc.push_correction_to_wfirma(
            batch_id=batch_id,
            execution_record_id=batch_id,
            operator_reason=operator_reason,
            idempotency_key=idempotency_key,
            confirm_understanding=confirm,
            storage_root=tmp_path,
            contractor_id="CONTRACTOR_999",
            warehouse_id="WH_001",
            product_map=product_map,
        )


# ---------------------------------------------------------------------------
# 01 — Blocked: wrong confirm sentinel
# ---------------------------------------------------------------------------

def test_01_blocked_wrong_confirm(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, confirm="wrong sentinel")
    assert result.ok is False
    assert result.status == "blocked"
    assert "sentinel" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 02 — Blocked: empty operator_reason
# ---------------------------------------------------------------------------

def test_02_blocked_empty_reason(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, operator_reason="   ")
    assert result.ok is False
    assert result.status == "blocked"
    assert "operator_reason" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 03 — Blocked: write flag disabled
# ---------------------------------------------------------------------------

def test_03_blocked_flag_disabled(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, push_allowed=False)
    assert result.ok is False
    assert result.status == "blocked"
    assert "wfirma_correction_push_allowed" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 04 — Blocked: missing staged execution record
# ---------------------------------------------------------------------------

def test_04_blocked_missing_execution_record(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    # Intentionally no correction_execution_record.json
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path)
    assert result.ok is False
    assert result.status == "blocked"
    assert "correction-execute" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 05 — Blocked: KEEP_CURRENT option
# ---------------------------------------------------------------------------

def test_05_blocked_keep_current(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir, option_id="KEEP_CURRENT")
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path)
    assert result.ok is False
    assert result.status == "blocked"
    assert result.staged_option == "KEEP_CURRENT"
    assert "KEEP_CURRENT" in (result.error or "")


# ---------------------------------------------------------------------------
# 06 — Blocked: NO_ACTION option
# ---------------------------------------------------------------------------

def test_06_blocked_no_action(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir, option_id="NO_ACTION")
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path)
    assert result.ok is False
    assert result.status == "blocked"
    assert result.staged_option == "NO_ACTION"


# ---------------------------------------------------------------------------
# 07 — Blocked: terminal PZ event EV_WFIRMA_PZ_CREATED
# ---------------------------------------------------------------------------

def test_07_blocked_terminal_pz_created(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir, timeline=[{"event": "wfirma_pz_created", "ts": "2026-05-24"}])

    result = _call_push(svc, tmp_path)
    assert result.ok is False
    assert result.status == "blocked"
    assert "already exists" in (result.error or "").lower()
    assert result.action_required is not None


# ---------------------------------------------------------------------------
# 08 — Blocked: terminal PZ event wfirma_pz_adopted
# ---------------------------------------------------------------------------

def test_08_blocked_terminal_pz_adopted(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir, timeline=[{"event": "wfirma_pz_adopted", "ts": "2026-05-24"}])

    result = _call_push(svc, tmp_path)
    assert result.ok is False
    assert result.status == "blocked"
    assert "already exists" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 09 — Blocked: pz_rows.json missing
# ---------------------------------------------------------------------------

def test_09_blocked_missing_pz_rows(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    # No pz_rows.json written
    _write_audit(bdir)

    result = _call_push(svc, tmp_path)
    assert result.ok is False
    assert result.status == "blocked"
    assert "pz_rows" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 10 — Blocked: product_map empty
# ---------------------------------------------------------------------------

def test_10_blocked_empty_product_map(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, product_map={})
    assert result.ok is False
    assert result.status == "blocked"
    assert "product map" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 11 — Blocked: all rows unmapped
# ---------------------------------------------------------------------------

def test_11_blocked_all_rows_unmapped(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir, rows=[
        {"product_code": "MISSING-01", "quantity": 5.0,  "unit_netto_pln": 10.0},
        {"product_code": "MISSING-02", "quantity": 3.0,  "unit_netto_pln": 20.0},
    ])
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, product_map={"INV-01": "GID_001"})
    assert result.ok is False
    assert result.status == "blocked"
    assert "No PZ lines" in (result.error or "")
    assert len(result.warnings) >= 2


# ---------------------------------------------------------------------------
# 12 — Idempotency: second call returns already_pushed
# ---------------------------------------------------------------------------

def test_12_idempotency_already_pushed(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    # Pre-write a push record simulating a prior successful push
    push_record = {
        "batch_id":             "BATCH_001",
        "option_id":            "ALIGN_TO_AUTHORITY",
        "idempotency_key":      "idem-key-001",
        "operator_reason":      "prior push",
        "pushed_at":            "2026-05-24T10:00:00+00:00",
        "wfirma_document_id":   "PZ_WFIRMA_777",
        "pre_push_line_count":  2,
        "post_push_line_count": 2,
        "action_taken":         "created_wfirma_pz_via_correction_align_to_authority",
        "audit_event_id":       "wfirma_pz_created:PZ_WFIRMA_777",
        "audit_patch_error":    None,
    }
    (bdir / "correction_push_record.json").write_text(
        json.dumps(push_record, ensure_ascii=False), encoding="utf-8"
    )

    result = _call_push(svc, tmp_path)
    assert result.ok is True
    assert result.status == "already_pushed"
    assert result.already_pushed is True
    assert result.wfirma_document_id == "PZ_WFIRMA_777"


# ---------------------------------------------------------------------------
# 13 — Success: ALIGN_TO_AUTHORITY
# ---------------------------------------------------------------------------

def test_13_success_align_to_authority(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir, option_id="ALIGN_TO_AUTHORITY")
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, wfirma_ok=True, wfirma_doc_id="PZ_WFIRMA_999")

    assert result.ok is True
    assert result.status == "pushed"
    assert result.wfirma_document_id == "PZ_WFIRMA_999"
    assert result.staged_option == "ALIGN_TO_AUTHORITY"
    assert result.pre_push_line_count == 2
    assert result.post_push_line_count == 2
    assert result.already_pushed is False
    assert "cannot be deleted" in result.rollback_note

    # Push record must be on disk
    push_rec_path = bdir / "correction_push_record.json"
    assert push_rec_path.exists(), "correction_push_record.json not written"
    rec = json.loads(push_rec_path.read_text(encoding="utf-8"))
    assert rec["wfirma_document_id"] == "PZ_WFIRMA_999"
    assert rec["option_id"] == "ALIGN_TO_AUTHORITY"
    assert rec["idempotency_key"] == "idem-key-001"


# ---------------------------------------------------------------------------
# 14 — Success: SPLIT_TO_STYLE_LEVEL
# ---------------------------------------------------------------------------

def test_14_success_split_to_style_level(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir, option_id="SPLIT_TO_STYLE_LEVEL")
    _write_pz_rows(bdir, rows=[
        {"product_code": "INV-01", "quantity": 10.0, "unit_netto_pln": 50.0},
        {"product_code": "INV-02", "quantity": 5.0,  "unit_netto_pln": 80.0},
        {"product_code": "INV-01", "quantity": 8.0,  "unit_netto_pln": 45.0},
    ])
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, wfirma_ok=True, wfirma_doc_id="PZ_SPLIT_001")

    assert result.ok is True
    assert result.status == "pushed"
    assert result.staged_option == "SPLIT_TO_STYLE_LEVEL"
    assert result.wfirma_document_id == "PZ_SPLIT_001"
    assert result.pre_push_line_count == 3

    push_rec_path = bdir / "correction_push_record.json"
    assert push_rec_path.exists()


# ---------------------------------------------------------------------------
# 15 — Failed: wFirma returns ok=False
# ---------------------------------------------------------------------------

def test_15_failed_wfirma_error(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    result = _call_push(svc, tmp_path, wfirma_ok=False)

    assert result.ok is False
    assert result.status == "failed"
    assert "wFirma API error" in (result.error or "")

    # Push record must NOT exist
    push_rec_path = bdir / "correction_push_record.json"
    assert not push_rec_path.exists(), (
        "correction_push_record.json must NOT be written when wFirma call fails"
    )


# ---------------------------------------------------------------------------
# 16 — Warnings: partially unmapped rows
# ---------------------------------------------------------------------------

def test_16_partial_unmapped_rows(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir, rows=[
        {"product_code": "INV-01",  "quantity": 10.0, "unit_netto_pln": 50.0},
        {"product_code": "MISSING", "quantity": 5.0,  "unit_netto_pln": 80.0},
    ])
    _write_audit(bdir)

    # Only INV-01 in map; MISSING has no entry
    result = _call_push(svc, tmp_path, product_map={"INV-01": "GID_001"})

    assert result.ok is True
    assert result.status == "pushed"
    # MISSING row produces a warning
    assert any("MISSING" in w for w in result.warnings)
    # Only 1 line pushed
    assert result.post_push_line_count == 1


# ---------------------------------------------------------------------------
# 17 — No routes_* import (no circular dependency)
# ---------------------------------------------------------------------------

def test_17_no_routes_import():
    """global_pz_push.py must not import from any routes_* module."""
    import ast as _ast
    tree = _ast.parse(_SVC.read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            module = ""
            if isinstance(node, _ast.Import):
                module = " ".join(a.name for a in node.names)
            elif isinstance(node, _ast.ImportFrom):
                module = node.module or ""
            assert "routes_" not in module, (
                f"global_pz_push.py must not import from {module!r}"
            )


# ---------------------------------------------------------------------------
# 18 — Push record format: all required keys present
# ---------------------------------------------------------------------------

def test_18_push_record_format(svc, tmp_path):
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    _call_push(svc, tmp_path)

    push_rec_path = bdir / "correction_push_record.json"
    assert push_rec_path.exists(), "Push record must be written on success"

    rec = json.loads(push_rec_path.read_text(encoding="utf-8"))
    required_keys = {
        "batch_id", "option_id", "idempotency_key", "operator_reason",
        "pushed_at", "wfirma_document_id", "pre_push_line_count",
        "post_push_line_count", "action_taken", "audit_event_id",
    }
    missing = required_keys - set(rec.keys())
    assert not missing, f"Push record missing keys: {missing}"


# ---------------------------------------------------------------------------
# PR B — Atomicity tests (19–22)
# ---------------------------------------------------------------------------

def test_19_write_json_atomic_imported():
    """global_pz_push.py must import write_json_atomic from utils.io (PR B)."""
    import ast as _ast
    tree = _ast.parse(_SVC.read_text(encoding="utf-8"))
    found = False
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            names  = [a.name for a in node.names]
            if "utils.io" in module and "write_json_atomic" in names:
                found = True
                break
    assert found, (
        "global_pz_push.py must import write_json_atomic from ..utils.io "
        "(PR B atomicity hardening)"
    )


def test_20_push_record_uses_write_json_atomic(svc, tmp_path):
    """push_correction_to_wfirma must write correction_push_record.json
    via write_json_atomic, not _write_json_file (PR B)."""
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    atomic_calls: List[Any] = []

    original_atomic = svc.write_json_atomic

    def _capture_atomic(path, data, **kw):
        atomic_calls.append(str(path))
        return original_atomic(path, data, **kw)

    with patch.object(svc, "write_json_atomic", side_effect=_capture_atomic):
        _call_push(svc, tmp_path)

    push_rec_path = str(bdir / "correction_push_record.json")
    assert any(push_rec_path in c for c in atomic_calls), (
        f"correction_push_record.json must be written via write_json_atomic; "
        f"calls seen: {atomic_calls}"
    )


def test_21_audit_patch_uses_write_json_atomic(svc, tmp_path):
    """_patch_audit_pz_doc_id must write audit.json via write_json_atomic (PR B)."""
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    atomic_calls: List[Any] = []

    original_atomic = svc.write_json_atomic

    def _capture_atomic(path, data, **kw):
        atomic_calls.append(str(path))
        return original_atomic(path, data, **kw)

    with patch.object(svc, "write_json_atomic", side_effect=_capture_atomic):
        _call_push(svc, tmp_path)

    audit_path = str(bdir / "audit.json")
    assert any(audit_path in c for c in atomic_calls), (
        f"audit.json must be written via write_json_atomic; "
        f"calls seen: {atomic_calls}"
    )


def test_22_write_json_file_not_called_on_success_path(svc, tmp_path):
    """_write_json_file must not be called on the success write path (PR B).

    After PR B, all safety-critical writes (push record, audit patch) use
    write_json_atomic. _write_json_file may still exist as a helper but must
    not be reached on the wFirma success path.
    """
    bdir = _make_batch_dir(tmp_path)
    _write_exec_record(bdir)
    _write_pz_rows(bdir)
    _write_audit(bdir)

    legacy_calls: List[Any] = []

    original_legacy = svc._write_json_file

    def _capture_legacy(path, data):
        legacy_calls.append(str(path))
        return original_legacy(path, data)

    with patch.object(svc, "_write_json_file", side_effect=_capture_legacy):
        result = _call_push(svc, tmp_path)

    assert result.ok is True, f"Push should succeed; got error: {result.error}"
    assert legacy_calls == [], (
        f"_write_json_file must not be called on the success path after PR B; "
        f"calls seen: {legacy_calls}"
    )
