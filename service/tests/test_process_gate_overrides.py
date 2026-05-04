"""
test_process_gate_overrides.py — PZ process endpoint gate respects operator overrides.

Problem fixed:
  The /api/v1/upload/shipment/{batch_id}/process endpoint previously gated on
  raw audit.status == "blocked" and rejected all blocked batches with 409.
  It now uses _compute_effective_blocked(audit) so that batches blocked only
  by operator-overridden non-financial checks can be reprocessed.

Coverage
--------
  1. blocked batch without any override → 409
  2. blocked batch with valid cn_match override → accepted (202 or 200, not 409)
  3. blocked batch with exporter_match override only → accepted
  4. blocked batch with forbidden cif_match in overrides (not in failed_checks path) → 409
     (forbidden checks are rejected by the override POST route; this verifies the gate
      does not open when the remaining blocker is a forbidden check)
  5. status=ready → accepted
  6. status=partial → accepted
  7. status=success → accepted
  8. status=draft → 409 (not a valid processing state)
  9. batch not found → 404
 10. blocked with cn_match override but cn_match NOT in failed_checks → 409
     (override present but no matching failure → still effectively blocked)
 11. blocked with two failed checks; only one overridden → 409
 12. blocked with both failed checks overridden → accepted
 13. audit.status field untouched in audit.json after gate acceptance
     (engine runs async; we just verify the gate passed and audit was not pre-mutated)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import require_api_key


# ── Helpers ───────────────────────────────────────────────────────────────────

def _override(check: str, batch_id: str) -> dict:
    return {
        "override_id":        str(uuid.uuid4()),
        "check":              check,
        "reason":             "Accepted by operator after review — long enough reason",
        "operator":           "operator",
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "evidence_reference": "",
        "batch_id":           batch_id,
        "original_value":     False,
    }


def _write_audit(outputs: Path, batch_id: str, data: dict) -> Path:
    d = outputs / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _blocked(batch_id: str, failed_checks: list, overrides: list | None = None) -> dict:
    return {
        "batch_id":            batch_id,
        "status":              "blocked",
        "failed_checks":       failed_checks,
        "amendment_flags":     [],
        "verification":        {c: False for c in failed_checks},
        "operator_overrides":  overrides or [],
        # customs_declaration with mrn → has_xml_customs = True → bypasses SAD PDF check
        "customs_declaration": {"mrn": "TESTMRN", "customs_source": "xml_validated"},
        "inputs":              {},
    }


def _ready(batch_id: str, status: str = "ready") -> dict:
    return {
        "batch_id":            batch_id,
        "status":              status,
        "failed_checks":       [],
        "amendment_flags":     [],
        "verification":        {},
        "operator_overrides":  [],
        # customs_declaration with mrn → has_xml_customs = True → bypasses SAD PDF check
        "customs_declaration": {"mrn": "TESTMRN", "customs_source": "xml_validated"},
        "inputs":              {},
    }


def _seed_invoices(outputs: Path, batch_id: str) -> None:
    """Create a minimal source/invoices/invoice.pdf so the invoice-dir guard passes."""
    inv_dir = outputs / batch_id / "source" / "invoices"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "invoice.pdf").write_bytes(b"%PDF-1.4 stub")


# ── TestClient factory ────────────────────────────────────────────────────────

def _make_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    """Return (client, outputs_dir) with auth bypassed, storage patched, engine mocked."""
    from app.api import routes_upload as ru
    from app.services import batch_service as bs
    from app.core.config import settings as s

    outputs = tmp_path / "outputs"
    outputs.mkdir()

    # Patch storage_root on both settings instances so get_output_dir resolves correctly
    monkeypatch.setattr(s, "storage_root", tmp_path)
    monkeypatch.setattr(bs.settings, "storage_root", tmp_path)

    # Mock the actual pipeline background task (_run_pipeline is what background.add_task uses)
    monkeypatch.setattr(ru, "_run_pipeline", AsyncMock(return_value=None), raising=False)

    app = FastAPI()
    app.include_router(ru.router)
    app.dependency_overrides[require_api_key] = lambda: None

    return TestClient(app, raise_server_exceptions=True), outputs


# ═══════════════════════════════════════════════════════════════════════════════
# Gate tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_blocked_no_override_rejected(tmp_path, monkeypatch):
    """1. blocked batch without any override → 409."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B1", _blocked("B1", ["cn_match"]))

    r = client.post("/api/v1/upload/shipment/B1/process")
    assert r.status_code == 409
    assert "blocked" in r.json()["detail"]


def test_blocked_cn_match_override_accepted(tmp_path, monkeypatch):
    """2. blocked batch with valid cn_match override → accepted (not 409)."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    overrides = [_override("cn_match", "B2")]
    _write_audit(outputs, "B2", _blocked("B2", ["cn_match"], overrides=overrides))
    _seed_invoices(outputs, "B2")

    r = client.post("/api/v1/upload/shipment/B2/process")
    assert r.status_code != 409, f"Expected gate to pass, got 409: {r.json()}"


def test_blocked_exporter_match_override_accepted(tmp_path, monkeypatch):
    """3. blocked batch with exporter_match override → accepted."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    overrides = [_override("exporter_match", "B3")]
    _write_audit(outputs, "B3", _blocked("B3", ["exporter_match"], overrides=overrides))
    _seed_invoices(outputs, "B3")

    r = client.post("/api/v1/upload/shipment/B3/process")
    assert r.status_code != 409, f"Expected gate to pass, got 409: {r.json()}"


def test_blocked_forbidden_check_remaining_rejected(tmp_path, monkeypatch):
    """4. blocked with forbidden check (cif_match) still in failed_checks → 409.
    Forbidden checks cannot be cleared by any override; gate must stay closed."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    # cn_match is overridden but cif_match is FORBIDDEN and still in failed_checks
    overrides = [_override("cn_match", "B4")]
    audit = _blocked("B4", ["cn_match", "cif_match"], overrides=overrides)
    _write_audit(outputs, "B4", audit)

    r = client.post("/api/v1/upload/shipment/B4/process")
    assert r.status_code == 409


def test_status_ready_accepted(tmp_path, monkeypatch):
    """5. status=ready → accepted."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B5", _ready("B5", "ready"))
    _seed_invoices(outputs, "B5")

    r = client.post("/api/v1/upload/shipment/B5/process")
    assert r.status_code != 409


def test_status_partial_accepted(tmp_path, monkeypatch):
    """6. status=partial → accepted."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B6", _ready("B6", "partial"))
    _seed_invoices(outputs, "B6")

    r = client.post("/api/v1/upload/shipment/B6/process")
    assert r.status_code != 409


def test_status_success_accepted(tmp_path, monkeypatch):
    """7. status=success → accepted."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B7", _ready("B7", "success"))
    _seed_invoices(outputs, "B7")

    r = client.post("/api/v1/upload/shipment/B7/process")
    assert r.status_code != 409


def test_status_draft_rejected(tmp_path, monkeypatch):
    """8. status=draft → 409 (not a valid processing state, no override applies)."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    _write_audit(outputs, "B8", _ready("B8", "draft"))

    r = client.post("/api/v1/upload/shipment/B8/process")
    assert r.status_code == 409


def test_batch_not_found_404(tmp_path, monkeypatch):
    """9. Non-existent batch → 404."""
    client, outputs = _make_client(tmp_path, monkeypatch)

    r = client.post("/api/v1/upload/shipment/NO_SUCH_BATCH/process")
    assert r.status_code == 404


def test_blocked_override_check_not_in_failed_checks_rejected(tmp_path, monkeypatch):
    """10. Override present for cn_match but cn_match NOT in failed_checks → 409.
    The remaining blocker is a different check — gate must stay closed."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    # exporter_match is the actual blocker; cn_match override is irrelevant
    overrides = [_override("cn_match", "B10")]
    _write_audit(outputs, "B10", _blocked("B10", ["exporter_match"], overrides=overrides))

    r = client.post("/api/v1/upload/shipment/B10/process")
    assert r.status_code == 409


def test_blocked_two_checks_one_overridden_rejected(tmp_path, monkeypatch):
    """11. Two failed checks; only one overridden → 409 (remaining hard failure)."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    overrides = [_override("cn_match", "B11")]
    _write_audit(outputs, "B11", _blocked("B11", ["cn_match", "exporter_match"], overrides=overrides))

    r = client.post("/api/v1/upload/shipment/B11/process")
    assert r.status_code == 409


def test_blocked_two_checks_both_overridden_accepted(tmp_path, monkeypatch):
    """12. Two allowed failed checks; both overridden → accepted."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    overrides = [_override("cn_match", "B12"), _override("exporter_match", "B12")]
    _write_audit(outputs, "B12", _blocked("B12", ["cn_match", "exporter_match"], overrides=overrides))
    _seed_invoices(outputs, "B12")

    r = client.post("/api/v1/upload/shipment/B12/process")
    assert r.status_code != 409, f"Expected gate to pass, got 409: {r.json()}"


def test_audit_status_not_pre_mutated_by_gate(tmp_path, monkeypatch):
    """13. Gate acceptance writes 'processing' to audit.status (engine queued); final
    status change (ready/partial/success) is made by the engine, not the gate.
    Verifies the gate passed AND that audit.status is exactly 'processing' — not
    left as 'blocked' and not jumped ahead to 'success'/'ready'."""
    client, outputs = _make_client(tmp_path, monkeypatch)
    overrides = [_override("cn_match", "B13")]
    _write_audit(outputs, "B13", _blocked("B13", ["cn_match"], overrides=overrides))
    _seed_invoices(outputs, "B13")

    r = client.post("/api/v1/upload/shipment/B13/process")
    assert r.status_code != 409, f"Expected gate to pass, got 409: {r.json()}"

    # Gate stamps "processing" immediately; engine (mocked here) updates it later.
    # Must NOT be "blocked" (gate pre-cleared) and must NOT be "success"/"ready"
    # (engine not yet run). "processing" is the only correct intermediate value.
    audit = json.loads((outputs / "B13" / "audit.json").read_text(encoding="utf-8"))
    assert audit["status"] == "processing", (
        f"Gate must stamp audit.status='processing' before dispatching engine; got: {audit['status']}"
    )
