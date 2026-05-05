"""
test_execution_engine.py — Unit + route tests for the centralized execution engine.

Coverage
--------
Engine unit tests (direct calls to execute_action):
  1. wfirma_create blocked — wfirma preview not ready → blocked response
  2. wfirma_create allowed — wfirma ready → calls create_one_reservation
  3. wfirma_create missing client_name → missing_field error
  4. duplicate call skipped — already_executed returns True → skipped
  5. execution log entry written — log file updated after successful create
  6. unknown action — returns unknown_action error
  7. closure_confirm blocked — not ready_for_closure → blocked
  8. closure_confirm calls apply when ready
  9. dhl_send_reply wrong state — not dhl_contacted → blocked
 10. dhl_send_reply success — calls builder + queue_email, ok=True
 10b. dhl_send_reply skipped — already_executed returns skipped
 10c. dhl_send_reply audit_not_found — no audit file
 10d. dhl_send_reply missing_attachments — blocks queue_email
 10e. dhl_send_reply success writes audit dhl_reply_sent + dhl_reply_package
 10f. dhl_send_reply success appends timeline event
 10g. dhl_send_reply queue failure — ok=False, execution log written as failed
 10h. dhl_send_reply missing_attachments — execution log written as failed

Route tests (FastAPI TestClient via POST /api/v1/execute/{action}):
 11. POST wfirma_create success — 200, ok=True, status=executed
 12. POST wfirma_create blocked — 200, ok=False, error=blocked
 13. POST unknown_action — 400
 14. POST missing batch_id — 400 (Pydantic validation)
 15. POST readiness_load_failed — 503
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_batch_ready() -> dict:
    return {
        "overall": {
            "ready_for_closure": True,
            "blocked_domains": [],
            "next_step": None,
        },
        "wfirma": {"status": "ok"},
    }


def _make_batch_not_ready_closure() -> dict:
    return {
        "overall": {
            "ready_for_closure": False,
            "blocked_domains": ["dhl"],
            "next_step": "Receive DHL reply",
        },
    }


def _make_wfirma_ready() -> dict:
    return {
        "ready_to_create": True,
        "blocking_reasons": [],
    }


def _make_wfirma_not_ready(reason: str = "wfirma not configured") -> dict:
    return {
        "ready_to_create": False,
        "blocking_reasons": [reason],
    }


def _make_dhl_contacted() -> dict:
    return {"dhl_status": "dhl_contacted"}


def _make_dhl_other() -> dict:
    return {"dhl_status": "awaiting_dhl_contact"}


def _make_dhl_audit(storage_root: Path, batch_id: str) -> Path:
    """Write a minimal audit.json sufficient for _call_dhl_reply audit load."""
    d = storage_root / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    audit = {
        "awb":                  "1234567890",
        "polish_desc_filename": "desc_test.pdf",
        "clearance_decision":   {"total_value_usd": 3500.0},
        "dhl_email":            {"ticket": "T123"},
    }
    p = d / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _clean_package() -> dict:
    """Minimal reply package with no missing attachments."""
    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_reply",
        "to":           "odprawacelna@dhl.com",
        "to_list":      ["odprawacelna@dhl.com"],
        "cc":           "internal@estrellajewels.eu",
        "cc_list":      ["internal@estrellajewels.eu"],
        "subject":      "Request for custom clearance – AWB 1234567890",
        "body_text":    "Dear DHL...",
        "body_html":    "<p>Dear DHL...</p>",
        "attachments":  [{"label": "Polish Customs Description", "path": "/tmp/desc_test.pdf"}],
        "missing":      [],
        "awb_attached": False,
        "ticket":       "T123",
    }


def _make_audit_with_closure(storage_root: Path, batch_id: str, *, completed: bool = False) -> Path:
    d = storage_root / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(
        json.dumps({
            "batch_id":               batch_id,
            "status":                 "completed" if completed else "open",
            # All four fields evaluate_closure needs to return ready=True
            "customs_docs":           {"received": True},
            "pz_generated":           True,
            "agency_invoice_received": True,
            "dhl_invoice_received":   True,
        }),
        encoding="utf-8",
    )
    return p


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_storage(tmp_path):
    return tmp_path


@pytest.fixture()
def engine(tmp_storage):
    """Return the execute_action callable with settings patched to tmp_storage."""
    from app.core.config import settings
    with patch.object(settings, "storage_root", tmp_storage):
        from app.services import execution_engine as ee
        yield ee


@pytest.fixture()
def client(tmp_storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── 1. wfirma_create blocked ──────────────────────────────────────────────────

def test_wfirma_create_blocked_when_not_ready(engine, tmp_storage):
    batch_id = "B_BLOCK_1"
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_not_ready("wfirma not configured")),
    ):
        result = engine.execute_action("wfirma_create", batch_id, {"client_name": "Acme"})

    assert result["ok"] is False
    assert result["error"] == "blocked"
    assert "wfirma" in result["reason"].lower()


# ── 2. wfirma_create allowed ──────────────────────────────────────────────────

def test_wfirma_create_calls_create_when_ready(engine, tmp_storage):
    batch_id = "B_READY_1"
    fake_result = {"ok": True, "wfirma_reservation_id": "WR-999", "code": "CREATED"}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_wfirma_create", return_value=fake_result) as mock_create,
    ):
        result = engine.execute_action("wfirma_create", batch_id, {"client_name": "Acme"})

    mock_create.assert_called_once_with(batch_id, "Acme")
    assert result["ok"] is True
    assert result["status"] == "executed"
    assert result["wfirma_reservation_id"] == "WR-999"


# ── 3. missing client_name ────────────────────────────────────────────────────

def test_wfirma_create_missing_client_name(engine, tmp_storage):
    batch_id = "B_MISSING_1"
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("wfirma_create", batch_id, {})

    assert result["ok"] is False
    assert result["error"] == "missing_field"
    assert result["field"] == "client_name"


# ── 4. duplicate call skipped ─────────────────────────────────────────────────

def test_wfirma_create_skipped_when_already_executed(engine, tmp_storage):
    batch_id = "B_DUP_1"
    payload = {"client_name": "DupClient"}
    key = f"wfirma_create::{batch_id}::DupClient"
    existing_entries = [
        {"key": key, "action_type": "wfirma_create", "batch_id": batch_id,
         "payload": payload, "status": "ok", "timestamp": "2026-01-01T00:00:00+00:00",
         "result": {"ok": True, "wfirma_reservation_id": "WR-OLD"}}
    ]
    log_path = tmp_storage / "execution_log.json"
    log_path.write_text(json.dumps(existing_entries), encoding="utf-8")

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("wfirma_create", batch_id, payload)

    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert result["reason"] == "already_executed"


# ── 5. execution log written ──────────────────────────────────────────────────

def test_execution_log_written_after_create(engine, tmp_storage):
    batch_id = "B_LOG_1"
    fake_result = {"ok": True, "wfirma_reservation_id": "WR-777"}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_wfirma_create", return_value=fake_result),
    ):
        engine.execute_action("wfirma_create", batch_id, {"client_name": "LogClient"})

    log_path = tmp_storage / "execution_log.json"
    assert log_path.exists(), "execution_log.json must be created"
    entries = json.loads(log_path.read_text())
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action_type"] == "wfirma_create"
    assert entry["batch_id"] == batch_id
    assert entry["status"] == "ok"
    assert entry["key"] == f"wfirma_create::{batch_id}::LogClient"


# ── 6. unknown action ─────────────────────────────────────────────────────────

def test_unknown_action_returns_error(engine, tmp_storage):
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("nonexistent_action", "B_UNK_1", {})

    assert result["ok"] is False
    assert result["error"] == "unknown_action"
    assert result["action_type"] == "nonexistent_action"


# ── 7. closure_confirm blocked ────────────────────────────────────────────────

def test_closure_confirm_blocked_when_not_ready(engine, tmp_storage):
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_not_ready_closure()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("closure_confirm", "B_CLOSE_BLOCK_1")

    assert result["ok"] is False
    assert result["error"] == "blocked"
    assert result["next_step"] == "Receive DHL reply"


# ── 8. closure_confirm calls apply when ready ────────────────────────────────

def test_closure_confirm_calls_apply_when_ready(engine, tmp_storage):
    """closure_confirm must invoke _call_closure_apply when ready_for_closure=True."""
    batch_id = "B_CLOSE_APPLY_1"
    batch_ready = {
        "overall": {
            "ready_for_closure": True,
            "blocked_domains": [],
            "next_step": None,
        }
    }
    fake_apply = {"ok": True, "status": "completed", "ready_for_accounting": True, "checks": {}}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_closure_apply", return_value=fake_apply) as apply_mock,
    ):
        result = engine.execute_action("closure_confirm", batch_id)

    apply_mock.assert_called_once_with(batch_id, approved_by="operator")
    assert result["ok"] is True


# ── 8b. closure_confirm calls closure_for_batch exactly once ─────────────────

def test_closure_confirm_calls_closure_for_batch_once(engine, tmp_storage):
    """closure_for_batch must be called exactly once per closure_confirm execution."""
    batch_id = "B_CLOSE_ONCE_1"
    _make_audit_with_closure(tmp_storage, batch_id)
    batch_ready = {
        "overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}
    }

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.shipment_closure.closure_for_batch",
              return_value={"ok": True, "status": "completed"}) as cfb_mock,
    ):
        engine.execute_action("closure_confirm", batch_id)

    cfb_mock.assert_called_once()


# ── 8c. closure_confirm duplicate returns skipped ────────────────────────────

def test_closure_confirm_duplicate_returns_skipped(engine, tmp_storage):
    """Second closure_confirm for the same batch must return skipped (idempotency)."""
    batch_id = "B_CLOSE_DUP_1"
    key = f"closure_confirm::{batch_id}::"
    existing = [
        {
            "key":         key,
            "action_type": "closure_confirm",
            "batch_id":    batch_id,
            "payload":     {},
            "status":      "ok",
            "timestamp":   "2026-01-01T00:00:00+00:00",
            "result":      {"ok": True, "status": "completed"},
        }
    ]
    (tmp_storage / "execution_log.json").write_text(json.dumps(existing), encoding="utf-8")

    with (
        patch("app.services.batch_readiness.get_batch_readiness",
              return_value={"overall": {"ready_for_closure": True, "blocked_domains": []}}),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("closure_confirm", batch_id)

    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert result["reason"] == "already_executed"


# ── 8d. closure_confirm execution log written on success ─────────────────────

def test_closure_confirm_execution_log_written(engine, tmp_storage):
    """Execution log must be written after a successful closure_confirm."""
    batch_id = "B_CLOSE_LOG_1"
    batch_ready = {
        "overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}
    }
    fake_apply = {"ok": True, "status": "completed", "checks": {}}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_closure_apply", return_value=fake_apply),
    ):
        engine.execute_action("closure_confirm", batch_id)

    log_path = tmp_storage / "execution_log.json"
    assert log_path.exists(), "execution_log.json must be created after closure_confirm"
    entries = json.loads(log_path.read_text())
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action_type"] == "closure_confirm"
    assert entry["batch_id"] == batch_id
    assert entry["status"] == "ok"


# ── 8e. closure_confirm no log written when blocked ──────────────────────────

def test_closure_confirm_not_logged_when_blocked(engine, tmp_storage):
    """Blocked closure_confirm must not produce an execution log entry."""
    with (
        patch("app.services.batch_readiness.get_batch_readiness",
              return_value=_make_batch_not_ready_closure()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("closure_confirm", "B_CLOSE_NOLOG_1")

    assert result["error"] == "blocked"
    assert not (tmp_storage / "execution_log.json").exists()


# ── 8f. evaluate_closure is read-only (service-level) ────────────────────────

def test_evaluate_closure_is_read_only():
    """evaluate_closure must never call apply_closure or write any file."""
    from app.services.shipment_closure import evaluate_closure
    audit = {
        "status": "open",
        "customs_docs": {"received": True},
        "pz_generated": True,
        "agency_invoice_received": True,
        "dhl_invoice_received": True,
    }
    write_mock = MagicMock()
    apply_mock = MagicMock()
    with (
        patch("app.services.shipment_closure.apply_closure", apply_mock),
        patch("app.services.shipment_closure.write_json_atomic", write_mock),
    ):
        result = evaluate_closure(audit)

    apply_mock.assert_not_called()
    write_mock.assert_not_called()
    assert result["ready"] is True
    assert "checks" in result
    assert "missing" in result
    assert "accounting_checks" in result
    assert "invoice_status" in result


# ── 8g. closure_confirm blocked when audit fields not ready (Gate 2) ─────────

def test_closure_blocked_when_audit_hard_fields_not_ready(engine, tmp_storage):
    """
    batch_readiness passes (Gate 1 clears) but evaluate_closure fails (Gate 2).
    Missing customs_docs blocks closure; missing invoices do NOT.
    """
    batch_id = "B_CLOSE_AUDIT_BLOCK"
    d = tmp_storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps({
        "batch_id":   batch_id,
        "status":     "open",
        # customs_docs absent → hard blocker; invoices absent → only accounting signal
    }), encoding="utf-8")

    batch_ready = {"overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}}
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("closure_confirm", batch_id)

    assert result["ok"] is False
    assert result["error"] == "blocked"
    assert "customs_docs_received" in result.get("reason", "")
    # invoices must NOT appear in the block reason
    assert "agency_invoice_received" not in result.get("reason", "")
    assert "dhl_invoice_received"    not in result.get("reason", "")


def test_closure_confirm_succeeds_with_invoices_missing(engine, tmp_storage):
    """
    closure_confirm must execute when customs+PZ are present but invoices absent.
    Result must include accounting_followup_required=True.
    """
    batch_id = "B_CLOSE_NO_INV"
    audit_path = tmp_storage / "outputs" / batch_id / "audit.json"
    (tmp_storage / "outputs" / batch_id).mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({
        "batch_id":     batch_id,
        "status":       "open",
        "customs_docs": {"received": True},
        "pz_generated": True,
        # no agency_invoice_received, no dhl_invoice_received
    }), encoding="utf-8")

    batch_ready = {"overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}}
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.shipment_closure.tl.log_event"),
    ):
        result = engine.execute_action("closure_confirm", batch_id)

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["accounting_followup_required"] is True
    assert result["invoice_status"] == "pending_accounting"
    audit_after = json.loads(audit_path.read_text())
    assert audit_after["status"]                       == "completed"
    assert audit_after["accounting_followup_required"] is True


# ── 8h. closure_confirm approved_by written to audit ─────────────────────────

def test_closure_approved_by_written_to_audit(engine, tmp_storage):
    """approved_by from payload must be recorded in audit.closure_approved_by."""
    batch_id = "B_CLOSE_APPBY"
    audit_path = _make_audit_with_closure(tmp_storage, batch_id)

    batch_ready = {"overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}}
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.shipment_closure.tl.log_event"),
    ):
        result = engine.execute_action(
            "closure_confirm", batch_id, {"approved_by": "  amadmin  "}
        )

    assert result["ok"] is True
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_after.get("closure_approved_by") == "amadmin"


# ── 8i. closure_confirm approved_by defaults to "operator" ───────────────────

def test_closure_approved_by_defaults_to_operator(engine, tmp_storage):
    """When approved_by is absent or blank, audit.closure_approved_by must be 'operator'."""
    batch_id = "B_CLOSE_APPBY_DEFAULT"
    audit_path = _make_audit_with_closure(tmp_storage, batch_id)

    batch_ready = {"overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}}
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.shipment_closure.tl.log_event"),
    ):
        result = engine.execute_action("closure_confirm", batch_id, {})

    assert result["ok"] is True
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_after.get("closure_approved_by") == "operator"


# ── 8j. closure_confirm both gates fail — reason references domain + fields ──

def test_closure_blocked_batch_readiness_takes_precedence(engine, tmp_storage):
    """When Gate 1 (batch_readiness) fails, blocked without reaching Gate 2."""
    batch_id = "B_CLOSE_BOTH_BLOCK"
    # Audit is not ready either — but Gate 1 should block first
    d = tmp_storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps({"batch_id": batch_id, "status": "open"}), encoding="utf-8")

    not_ready = {"overall": {"ready_for_closure": False, "blocked_domains": ["warehouse"], "next_step": None}}
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=not_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("closure_confirm", batch_id)

    assert result["ok"] is False
    assert result["error"] == "blocked"
    assert "warehouse" in result.get("reason", "")


# ── 9. dhl_send_reply wrong state ─────────────────────────────────────────────

def test_dhl_send_reply_blocked_wrong_state(engine, tmp_storage):
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("dhl_send_reply", "B_DHL_BLOCK_1", {})

    assert result["ok"] is False
    assert result["error"] == "blocked"


# ── 10. dhl_send_reply success ───────────────────────────────────────────────

def test_dhl_send_reply_calls_builder_and_queue_email(engine, tmp_storage):
    """dhl_contacted state + valid audit → builder called, queue_email called, ok=True."""
    batch_id = "B_DHL_OK_1"
    _make_dhl_audit(tmp_storage, batch_id)
    fake_email_id = "email-uuid-001"

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package",
              return_value=_clean_package()) as mock_builder,
        patch("app.services.email_service.queue_email",
              return_value=fake_email_id) as mock_queue,
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    mock_builder.assert_called_once()
    mock_queue.assert_called_once()
    assert result["ok"] is True
    assert result["status"] == "executed"
    assert result["queued"] is True
    assert result["email_id"] == fake_email_id


# ── 10b. dhl_send_reply skipped ──────────────────────────────────────────────

def test_dhl_send_reply_skipped_when_already_executed(engine, tmp_storage):
    """Second dhl_send_reply for the same batch must return skipped (idempotency)."""
    batch_id = "B_DHL_DUP_1"
    key = f"dhl_send_reply::{batch_id}::"
    existing = [
        {
            "key":         key,
            "action_type": "dhl_send_reply",
            "batch_id":    batch_id,
            "payload":     {},
            "status":      "ok",
            "timestamp":   "2026-01-01T00:00:00+00:00",
            "result":      {"ok": True, "email_queued": True, "email_id": "email-prev"},
        }
    ]
    (tmp_storage / "execution_log.json").write_text(json.dumps(existing), encoding="utf-8")

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package") as mock_builder,
        patch("app.services.email_service.queue_email") as mock_queue,
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    mock_builder.assert_not_called()
    mock_queue.assert_not_called()
    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert result["reason"] == "already_executed"


# ── 10c. dhl_send_reply audit_not_found ──────────────────────────────────────

def test_dhl_send_reply_returns_error_when_audit_missing(engine, tmp_storage):
    """No audit.json for the batch → ok=False, error=audit_not_found."""
    batch_id = "B_DHL_NOAUDIT_1"
    # Do NOT create audit file

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.email_service.queue_email") as mock_queue,
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    mock_queue.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "audit_not_found"


# ── 10d. dhl_send_reply missing_attachments ──────────────────────────────────

def test_dhl_send_reply_missing_attachments_blocks_queue(engine, tmp_storage):
    """package['missing'] non-empty → queue_email must not be called."""
    batch_id = "B_DHL_MISS_1"
    _make_dhl_audit(tmp_storage, batch_id)
    broken_package = {**_clean_package(), "missing": ["Polish description not generated"]}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package",
              return_value=broken_package),
        patch("app.services.email_service.queue_email") as mock_queue,
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    mock_queue.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "missing_required_attachments"
    assert "Polish description not generated" in result["missing"]


# ── 10e. dhl_send_reply success writes audit ─────────────────────────────────

def test_dhl_send_reply_success_writes_audit_fields(engine, tmp_storage):
    """After success, audit must contain dhl_reply_sent=True and dhl_reply_package."""
    batch_id = "B_DHL_AUDIT_1"
    audit_path = _make_dhl_audit(tmp_storage, batch_id)
    fake_email_id = "email-audit-write-001"

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package",
              return_value=_clean_package()),
        patch("app.services.email_service.queue_email", return_value=fake_email_id),
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    assert result["ok"] is True
    assert result["queued"] is True
    assert result["email_id"] == fake_email_id
    updated = json.loads(audit_path.read_text())
    drp = updated.get("dhl_reply_package") or {}
    assert drp.get("email_id") == fake_email_id
    assert drp.get("status") == "queued"
    assert drp.get("source") == "execution_engine"


# ── 10f. dhl_send_reply success appends timeline event ───────────────────────

def test_dhl_send_reply_success_appends_timeline_event(engine, tmp_storage):
    """After success, audit['timeline'] must contain a dhl_followup_sent event."""
    batch_id = "B_DHL_TL_1"
    audit_path = _make_dhl_audit(tmp_storage, batch_id)

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package",
              return_value=_clean_package()),
        patch("app.services.email_service.queue_email", return_value="email-tl-001"),
    ):
        engine.execute_action("dhl_send_reply", batch_id, {})

    updated = json.loads(audit_path.read_text())
    timeline = updated.get("timeline") or []
    events = [e.get("event") for e in timeline]
    assert "dhl_followup_sent" in events, f"dhl_followup_sent not in timeline events: {events}"


# ── 10g. dhl_send_reply queue failure → ok=False, logged as failed ──────────

def test_dhl_send_reply_queue_failure_returns_ok_false(engine, tmp_storage):
    """queue_email raising → ok=False, status=executed, execution_log status=failed."""
    batch_id = "B_DHL_QFAIL_1"
    _make_dhl_audit(tmp_storage, batch_id)

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package",
              return_value=_clean_package()),
        patch("app.services.email_service.queue_email",
              side_effect=ValueError("to is required")),
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    assert result["ok"] is False
    assert result["error"] == "email_queue_failed"
    assert result["status"] == "executed"

    log_path = tmp_storage / "execution_log.json"
    assert log_path.exists(), "execution log must be written even on queue failure"
    entries = json.loads(log_path.read_text())
    assert entries[-1]["status"] == "failed"
    assert entries[-1]["action_type"] == "dhl_send_reply"


# ── 10h. dhl_send_reply missing_attachments → logged as failed ───────────────

def test_dhl_send_reply_missing_attachments_logged_as_failed(engine, tmp_storage):
    """missing_attachments result must be logged as failed in execution_log."""
    batch_id = "B_DHL_MISS_LOG_1"
    _make_dhl_audit(tmp_storage, batch_id)
    broken_package = {**_clean_package(), "missing": ["Polish description not generated"]}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package",
              return_value=broken_package),
        patch("app.services.email_service.queue_email") as mock_queue,
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    assert result["ok"] is False
    assert result["error"] == "missing_required_attachments"
    mock_queue.assert_not_called()

    log_path = tmp_storage / "execution_log.json"
    assert log_path.exists(), "execution log must be written for missing_required_attachments"
    entries = json.loads(log_path.read_text())
    assert entries[-1]["status"] == "failed"
    assert entries[-1]["action_type"] == "dhl_send_reply"


# ── 11. Route: POST wfirma_create success ─────────────────────────────────────

def test_route_wfirma_create_success(client, tmp_storage):
    from app.core.config import settings
    fake_result = {"ok": True, "wfirma_reservation_id": "WR-ROUTE-1"}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_wfirma_create", return_value=fake_result),
    ):
        resp = client.post(
            "/api/v1/execute/wfirma_create",
            json={"batch_id": "B_ROUTE_1", "payload": {"client_name": "RouteClient"}},
            headers=_auth(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "executed"
    assert data["wfirma_reservation_id"] == "WR-ROUTE-1"


# ── 12. Route: POST wfirma_create blocked ─────────────────────────────────────

def test_route_wfirma_create_blocked(client, tmp_storage):
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_not_ready("missing config")),
    ):
        resp = client.post(
            "/api/v1/execute/wfirma_create",
            json={"batch_id": "B_ROUTE_BLOCK", "payload": {"client_name": "BlockedClient"}},
            headers=_auth(),
        )

    assert resp.status_code == 200  # engine returns 200 for blocked so dashboard can show reason
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "blocked"


# ── 13. Route: POST unknown action ────────────────────────────────────────────

def test_route_unknown_action_returns_400(client, tmp_storage):
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        resp = client.post(
            "/api/v1/execute/totally_fake_action",
            json={"batch_id": "B_ROUTE_UNK"},
            headers=_auth(),
        )

    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_action"


# ── 14. Route: POST missing batch_id ──────────────────────────────────────────

def test_route_missing_batch_id_returns_422(client):
    resp = client.post(
        "/api/v1/execute/wfirma_create",
        json={"payload": {"client_name": "NoBatch"}},
        headers=_auth(),
    )
    assert resp.status_code == 422  # Pydantic validation failure


# ── 15. Route: readiness_load_failed returns 503 ──────────────────────────────

def test_route_readiness_load_failed_returns_503(client, tmp_storage):
    with patch(
        "app.services.batch_readiness.get_batch_readiness",
        side_effect=RuntimeError("upstream down"),
    ):
        resp = client.post(
            "/api/v1/execute/wfirma_create",
            json={"batch_id": "B_ROUTE_FAIL", "payload": {"client_name": "X"}},
            headers=_auth(),
        )

    assert resp.status_code == 503
    assert resp.json()["error"] == "readiness_load_failed"


# ── 16. Skipped even when readiness service is down (P1 fix) ──────────────────

def test_skipped_when_readiness_fails_but_already_executed(engine, tmp_storage):
    """
    If an action was already executed successfully, return 'skipped' even when
    the readiness service raises — the idempotency check must run first.
    """
    batch_id = "B_SKIP_DOWN"
    payload  = {"client_name": "SkipClient"}
    key      = f"wfirma_create::{batch_id}::SkipClient"

    existing = [
        {
            "key":         key,
            "action_type": "wfirma_create",
            "batch_id":    batch_id,
            "payload":     payload,
            "status":      "ok",
            "timestamp":   "2026-01-01T00:00:00+00:00",
            "result":      {"ok": True, "wfirma_reservation_id": "WR-PREV"},
        }
    ]
    (tmp_storage / "execution_log.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )

    with patch(
        "app.services.batch_readiness.get_batch_readiness",
        side_effect=RuntimeError("readiness service down"),
    ):
        result = engine.execute_action("wfirma_create", batch_id, payload)

    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert result["reason"] == "already_executed"


# ── 17. Failed log entry does not block retry ─────────────────────────────────

def test_failed_log_entry_allows_retry(engine, tmp_storage):
    """
    A status='failed' entry in the log must NOT prevent a subsequent attempt.
    Only status='ok' entries count as executed.
    """
    batch_id = "B_RETRY_1"
    payload  = {"client_name": "RetryClient"}
    key      = f"wfirma_create::{batch_id}::RetryClient"

    failed_entry = [
        {
            "key":         key,
            "action_type": "wfirma_create",
            "batch_id":    batch_id,
            "payload":     payload,
            "status":      "failed",
            "timestamp":   "2026-01-01T00:00:00+00:00",
            "result":      {"ok": False, "error": "upstream_error"},
        }
    ]
    (tmp_storage / "execution_log.json").write_text(
        json.dumps(failed_entry), encoding="utf-8"
    )

    fake_result = {"ok": True, "wfirma_reservation_id": "WR-RETRY"}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_wfirma_create", return_value=fake_result),
    ):
        result = engine.execute_action("wfirma_create", batch_id, payload)

    assert result["ok"] is True
    assert result["status"] == "executed"
    assert result["wfirma_reservation_id"] == "WR-RETRY"


# ── 18. Execution log not written on missing_field ────────────────────────────

def test_execution_log_not_written_on_missing_field(engine, tmp_storage):
    """
    A missing_field validation error must not produce a log entry —
    no execution was attempted.
    """
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
    ):
        result = engine.execute_action("wfirma_create", "B_NOLOG_1", {})

    assert result["error"] == "missing_field"
    assert not (tmp_storage / "execution_log.json").exists()


# ── 19. Execution log not written when blocked ────────────────────────────────

def test_execution_log_not_written_on_blocked(engine, tmp_storage):
    """
    A blocked response (readiness gate not met) must not produce a log entry —
    no execution was attempted.
    """
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview",
              return_value=_make_wfirma_not_ready("missing config")),
    ):
        result = engine.execute_action("wfirma_create", "B_NOLOG_2", {"client_name": "Blocked"})

    assert result["error"] == "blocked"
    assert not (tmp_storage / "execution_log.json").exists()


# ── 20. Blocked response has status field (P2 fix) ────────────────────────────

def test_blocked_response_includes_status_field(engine, tmp_storage):
    """
    block() must return status='blocked' so callers can classify the response
    by status field alone, consistent with 'executed' and 'skipped'.
    """
    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview",
              return_value=_make_wfirma_not_ready("not configured")),
    ):
        result = engine.execute_action("wfirma_create", "B_STATUS_1", {"client_name": "X"})

    assert result["ok"] is False
    assert result["error"] == "blocked"
    assert result["status"] == "blocked"


# ── 21–24. Batch ID validation ────────────────────────────────────────────────

def test_invalid_batch_id_empty_string(engine):
    result = engine.execute_action("wfirma_create", "", {"client_name": "X"})
    assert result["ok"] is False
    assert result["error"] == "invalid_batch_id"


def test_invalid_batch_id_traversal_dotdot(engine):
    result = engine.execute_action("wfirma_create", "../other", {"client_name": "X"})
    assert result["ok"] is False
    assert result["error"] == "invalid_batch_id"


def test_invalid_batch_id_slash(engine):
    result = engine.execute_action("wfirma_create", "path/to/batch", {"client_name": "X"})
    assert result["ok"] is False
    assert result["error"] == "invalid_batch_id"


def test_invalid_batch_id_backslash(engine):
    result = engine.execute_action("wfirma_create", "path\\batch", {"client_name": "X"})
    assert result["ok"] is False
    assert result["error"] == "invalid_batch_id"


# ── 25. dhl_reply_sent audit flag skips re-send ───────────────────────────────

def test_dhl_send_reply_skipped_when_audit_flag_set(engine, tmp_storage):
    """audit already has dhl_reply_sent=True → returns skipped without calling queue_email."""
    batch_id = "B_DHL_ALREADY_SENT_1"
    d = tmp_storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps({
        "awb": "1234567890",
        "dhl_reply_sent": True,
        "polish_desc_filename": "desc.pdf",
    }), encoding="utf-8")

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package") as mock_builder,
        patch("app.services.email_service.queue_email") as mock_queue,
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    mock_builder.assert_not_called()
    mock_queue.assert_not_called()
    assert result["ok"] is True
    assert result["status"] == "skipped"
    assert result["reason"] == "already_sent"


# ── 26. dhl_reply_sent not written on queue failure ───────────────────────────

def test_dhl_reply_sent_not_written_on_queue_failure(engine, tmp_storage):
    """queue_email failure → dhl_reply_sent must NOT be written to audit."""
    batch_id = "B_DHL_QFAIL_NOSENT_1"
    audit_path = _make_dhl_audit(tmp_storage, batch_id)

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=_make_dhl_contacted()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.dhl_reply_builder.build_dhl_reply_package", return_value=_clean_package()),
        patch("app.services.email_service.queue_email", side_effect=ValueError("smtp error")),
    ):
        result = engine.execute_action("dhl_send_reply", batch_id, {})

    assert result["ok"] is False
    assert result["error"] == "email_queue_failed"
    updated = json.loads(audit_path.read_text())
    assert not updated.get("dhl_reply_sent"), "dhl_reply_sent must not be set after queue failure"


# ── 27. _save_log returns True on success ─────────────────────────────────────

def test_save_log_returns_true_on_success(tmp_storage):
    from app.core.config import settings
    with patch.object(settings, "storage_root", tmp_storage):
        from app.services.execution_engine import _save_log
        result = _save_log([{"key": "k", "action_type": "test", "status": "ok"}])
    assert result is True
    assert (tmp_storage / "execution_log.json").exists()


# ── 28. _save_log returns False on write failure ──────────────────────────────

def test_save_log_returns_false_on_write_failure(tmp_storage):
    from app.core.config import settings
    with patch.object(settings, "storage_root", tmp_storage):
        from app.services.execution_engine import _save_log
        with patch("pathlib.Path.replace", side_effect=OSError("disk full")):
            result = _save_log([{"key": "k", "action_type": "test", "status": "ok"}])
    assert result is False


# ── 29. execute_action surfaces log_write_failed when log write fails ─────────

def test_execute_action_surfaces_log_write_failed(engine, tmp_storage):
    """
    If the action succeeds but execution log write fails, the response must
    contain log_write_failed=True.  ok and status must not be changed.
    """
    batch_id = "B_LOGFAIL_1"
    fake_result = {"ok": True, "wfirma_reservation_id": "WR-LOGFAIL"}

    with (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness",     return_value=_make_dhl_other()),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_make_wfirma_ready()),
        patch("app.services.execution_engine._call_wfirma_create", return_value=fake_result),
        patch("app.services.execution_engine._save_log", return_value=False),
    ):
        result = engine.execute_action("wfirma_create", batch_id, {"client_name": "LogFail"})

    assert result["ok"] is True
    assert result["status"] == "executed"
    assert result.get("log_write_failed") is True


# ── 30. _load_log returns [] on corrupt log and logs error ────────────────────

def test_load_log_returns_empty_on_corrupt_file(tmp_storage, caplog):
    import logging
    from app.core.config import settings
    log_path = tmp_storage / "execution_log.json"
    log_path.write_text("not valid json {{{", encoding="utf-8")

    with patch.object(settings, "storage_root", tmp_storage):
        from app.services import execution_engine as ee
        with caplog.at_level(logging.ERROR, logger="app.services.execution_engine"):
            entries = ee._load_log()

    assert entries == []
    assert any("execution_log read error" in r.message for r in caplog.records), \
        "expected ERROR log for corrupt execution_log"


# ── Regression: warehouse_module_enabled=False blocks live wFirma write ──────

def test_wfirma_create_blocked_when_warehouse_module_flag_false(engine, tmp_storage):
    """
    Regression: setting wfirma_warehouse_module_enabled=False must block
    execute_action('wfirma_create', ...) and prevent the create write path
    from being reached.

    Locks in default-safe behavior — the warehouse module flag is the master
    gate for live reservation writes. If a future refactor stops honoring it
    in get_reservation_preview / capabilities, this test fails.
    """
    from app.core.config import settings
    batch_id = "B_FLAG_OFF"

    with (
        patch.object(settings, "wfirma_warehouse_module_enabled", False),
        patch.object(settings, "wfirma_access_key", "k"),
        patch.object(settings, "wfirma_secret_key", "s"),
        patch.object(settings, "wfirma_app_key",    "a"),
        patch.object(settings, "wfirma_company_id", "1"),
        patch.object(settings, "wfirma_warehouse_id", "1"),
        patch("app.services.batch_readiness.get_batch_readiness",
              return_value=_make_batch_ready()),
        patch("app.services.dhl_readiness.get_dhl_readiness",
              return_value=_make_dhl_other()),
        patch("app.services.execution_engine._call_wfirma_create") as mock_create,
        patch("app.services.wfirma_client.create_reservation") as mock_http,
    ):
        result = engine.execute_action(
            "wfirma_create", batch_id, {"client_name": "Acme"}
        )

    assert result["ok"] is False, result
    assert result["error"] == "blocked", result
    mock_create.assert_not_called()
    mock_http.assert_not_called()
