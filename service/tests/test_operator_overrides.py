"""
test_operator_overrides.py — Operator override backend tests.

Coverage
--------
_compute_effective_blocked() unit tests:
  1.  Non-blocked audit → always False
  2.  Blocked with no overrides → True
  3.  Blocked, cn_match overridden, cn_match was the only failure → False
  4.  Blocked, cn_match overridden, cif_match still failing → True
  5.  Blocked, exporter_match overridden, cn_match still failing → True
  6.  invoice_number_parse_warning clears Parse warning flags but not failed_checks
  7.  batch_id mismatch in override → override ignored
  8.  Forbidden check in overrides list → ignored (never clears)
  9.  All allowed checks overridden, no remaining failures → False
 10.  Parse warning override: no remaining parse flags AND no remaining failed_checks → False

POST /dashboard/batches/{batch_id}/operator-override route tests:
 11.  Forbidden check → 400
 12.  Unknown check → 400
 13.  reason too short → 400
 14.  Batch not found → 404
 15.  Batch not blocked → 409
 16.  check not in failed_checks → 409
 17.  invoice_number_parse_warning with no parse flags → 409
 18.  Duplicate override → 400
 19.  Valid cn_match override → 200, override_id returned, audit written
 20.  X-Operator-Id header stored in override record
 21.  operator_overrides is append-only (two sequential calls succeed)
 22.  audit.status / failed_checks / verification / amendment_flags NOT modified
 23.  invoice_number_parse_warning with parse flags → 200
 24.  timeline event logged after successful override
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import require_api_key
from app.services.batch_state_normalizer import (
    _compute_effective_blocked,
    ALLOWED_OVERRIDE_TYPES,
    FORBIDDEN_OVERRIDE_TYPES,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _override(check: str, batch_id: str = "B1", **kw) -> dict:
    return {
        "override_id": str(uuid.uuid4()),
        "check":       check,
        "reason":      "Test reason — at least 20 chars",
        "operator":    "operator",
        "timestamp":   "2026-01-01T00:00:00+00:00",
        "batch_id":    batch_id,
        **kw,
    }


def _blocked_audit(
    failed_checks: list | None = None,
    amendment_flags: list | None = None,
    verification: dict | None = None,
    operator_overrides: list | None = None,
    batch_id: str = "B1",
) -> dict:
    return {
        "batch_id":          batch_id,
        "status":            "blocked",
        "failed_checks":     failed_checks or [],
        "amendment_flags":   amendment_flags or [],
        "verification":      verification or {},
        "operator_overrides": operator_overrides or [],
    }


# ── Shared TestClient fixture ─────────────────────────────────────────────────

def _make_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Return a TestClient for routes_dashboard with auth bypassed and storage patched."""
    from app.api import routes_dashboard as rd
    from app.core.config import settings as s

    monkeypatch.setattr(s, "storage_root", tmp_path)
    monkeypatch.setattr(rd, "_OUTPUTS", tmp_path / "outputs")

    app = FastAPI()
    app.include_router(rd.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


def _write_audit(outputs: Path, batch_id: str, data: dict) -> Path:
    d = outputs / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _read_audit(outputs: Path, batch_id: str) -> dict:
    return json.loads((outputs / batch_id / "audit.json").read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
# _compute_effective_blocked() unit tests  (1–10)
# ═══════════════════════════════════════════════════════════════════════════════

def test_non_blocked_always_false():
    """1. Non-blocked status → False regardless of everything else."""
    audit = {
        "batch_id": "B1",
        "status": "success",
        "failed_checks": ["cn_match"],
        "amendment_flags": ["Parse warning: x"],
    }
    assert _compute_effective_blocked(audit) is False


def test_blocked_no_overrides_true():
    """2. Blocked with no overrides and failing check → True."""
    audit = _blocked_audit(failed_checks=["cn_match"])
    assert _compute_effective_blocked(audit) is True


def test_cn_match_override_sole_failure_false():
    """3. cn_match overridden and was the only failure → effectively unblocked."""
    overrides = [_override("cn_match", batch_id="B1")]
    audit = _blocked_audit(failed_checks=["cn_match"], operator_overrides=overrides)
    assert _compute_effective_blocked(audit) is False


def test_cn_match_override_cif_still_failing_true():
    """4. cn_match overridden but cif_match still failing → still blocked."""
    overrides = [_override("cn_match", batch_id="B1")]
    audit = _blocked_audit(
        failed_checks=["cn_match", "cif_match"],
        operator_overrides=overrides,
    )
    assert _compute_effective_blocked(audit) is True


def test_exporter_override_cn_still_failing_true():
    """5. exporter_match overridden but cn_match still in failed_checks → True."""
    overrides = [_override("exporter_match", batch_id="B1")]
    audit = _blocked_audit(
        failed_checks=["cn_match"],
        operator_overrides=overrides,
    )
    assert _compute_effective_blocked(audit) is True


def test_parse_warning_override_clears_flags_not_failed_checks():
    """6. invoice_number_parse_warning clears Parse warning flags only."""
    overrides = [_override("invoice_number_parse_warning", batch_id="B1")]
    # Parse flag cleared; non-parse flag remains
    audit = _blocked_audit(
        failed_checks=[],
        amendment_flags=["Parse warning: inv-123", "Missing field: foo"],
        operator_overrides=overrides,
    )
    # "Missing field: foo" remains → still blocked
    assert _compute_effective_blocked(audit) is True


def test_batch_id_mismatch_override_ignored():
    """7. Override with wrong batch_id is silently ignored."""
    overrides = [_override("cn_match", batch_id="WRONG")]
    audit = _blocked_audit(failed_checks=["cn_match"], batch_id="B1",
                           operator_overrides=overrides)
    assert _compute_effective_blocked(audit) is True


def test_forbidden_check_in_overrides_ignored():
    """8. Forbidden check in overrides list is ignored — cannot clear failures."""
    overrides = [_override("cif_match", batch_id="B1")]
    audit = _blocked_audit(
        failed_checks=["cif_match"],
        operator_overrides=overrides,
    )
    # cif_match is FORBIDDEN — must not clear failure
    assert _compute_effective_blocked(audit) is True


def test_all_allowed_checks_overridden_no_failures():
    """9. All checks overridden, no remaining failures → False."""
    overrides = [
        _override("cn_match", batch_id="B1"),
        _override("exporter_match", batch_id="B1"),
    ]
    audit = _blocked_audit(
        failed_checks=["cn_match", "exporter_match"],
        amendment_flags=[],
        operator_overrides=overrides,
    )
    assert _compute_effective_blocked(audit) is False


def test_parse_warning_override_only_parse_flags_false():
    """10. Parse warning override, only parse flags remain → False (effectively unblocked)."""
    overrides = [_override("invoice_number_parse_warning", batch_id="B1")]
    audit = _blocked_audit(
        failed_checks=[],
        amendment_flags=["Parse warning: inv-123", "Parse warning: inv-456"],
        operator_overrides=overrides,
    )
    assert _compute_effective_blocked(audit) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Route tests  (11–24)
# ═══════════════════════════════════════════════════════════════════════════════

def test_forbidden_check_rejected(tmp_path, monkeypatch):
    """11. Forbidden check → 400."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(failed_checks=["cif_match"], batch_id="BX"))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cif_match", "reason": "This reason is long enough to pass"},
    )
    assert r.status_code == 400
    assert "forbidden" in r.json()["detail"].lower()


def test_unknown_check_rejected(tmp_path, monkeypatch):
    """12. Unknown check → 400."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(batch_id="BX"))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "totally_made_up", "reason": "This reason is long enough to pass"},
    )
    assert r.status_code == 400


def test_reason_too_short_rejected(tmp_path, monkeypatch):
    """13. reason shorter than 20 chars → 400."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(failed_checks=["cn_match"], batch_id="BX"))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "Too short"},
    )
    assert r.status_code == 400
    assert "20" in r.json()["detail"]


def test_batch_not_found_404(tmp_path, monkeypatch):
    """14. Non-existent batch → 404."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post(
        "/dashboard/batches/NO_SUCH_BATCH/operator-override",
        json={"check": "cn_match", "reason": "This reason is long enough to pass"},
    )
    assert r.status_code == 404


def test_batch_not_blocked_409(tmp_path, monkeypatch):
    """15. Batch with status=success → 409."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", {
        "batch_id": "BX",
        "status": "success",
        "failed_checks": [],
    })
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "This reason is long enough to pass"},
    )
    assert r.status_code == 409


def test_check_not_in_failed_checks_409(tmp_path, monkeypatch):
    """16. cn_match not in failed_checks → 409."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(failed_checks=["exporter_match"], batch_id="BX"))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "This reason is long enough to pass"},
    )
    assert r.status_code == 409


def test_parse_warning_no_flags_409(tmp_path, monkeypatch):
    """17. invoice_number_parse_warning with no Parse warning: flags → 409."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(
        amendment_flags=["Some other flag"],
        batch_id="BX",
    ))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "invoice_number_parse_warning",
              "reason": "This reason is long enough to pass"},
    )
    assert r.status_code == 409


def test_duplicate_override_400(tmp_path, monkeypatch):
    """18. Same check overridden twice → 400."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(failed_checks=["cn_match"], batch_id="BX"))

    r1 = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "This reason is long enough to pass"},
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "This reason is long enough to pass"},
    )
    assert r2.status_code == 400
    assert "already been overridden" in r2.json()["detail"]


def test_valid_cn_match_override_200(tmp_path, monkeypatch):
    """19. Valid cn_match override → 200, override_id returned, audit written."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(
        failed_checks=["cn_match"],
        verification={"cn_match": False},
        batch_id="BX",
    ))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "CN parent code accepted — known customs aggregation"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "override_id" in data
    assert data["check"] == "cn_match"
    assert data["batch_id"] == "BX"

    audit = _read_audit(outputs, "BX")
    assert len(audit.get("operator_overrides", [])) == 1
    rec = audit["operator_overrides"][0]
    assert rec["check"] == "cn_match"
    assert rec["original_value"] is False
    assert rec["batch_id"] == "BX"


def test_operator_id_header_stored(tmp_path, monkeypatch):
    """20. X-Operator-Id header is stored in the override record."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(failed_checks=["cn_match"], batch_id="BX"))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "CN parent code accepted — known customs aggregation"},
        headers={"X-Operator-Id": "anna.kowalska"},
    )
    assert r.status_code == 200
    audit = _read_audit(outputs, "BX")
    assert audit["operator_overrides"][0]["operator"] == "anna.kowalska"


def test_operator_overrides_append_only(tmp_path, monkeypatch):
    """21. Two sequential overrides both persist (append-only, no clobber)."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(
        failed_checks=["cn_match", "exporter_match"],
        batch_id="BX",
    ))
    r1 = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "CN parent code accepted — known customs aggregation"},
    )
    r2 = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "exporter_match", "reason": "Exporter SAD truncation is acceptable here"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    audit = _read_audit(outputs, "BX")
    checks = [o["check"] for o in audit.get("operator_overrides", [])]
    assert "cn_match" in checks
    assert "exporter_match" in checks
    assert len(checks) == 2


def test_immutable_fields_not_modified(tmp_path, monkeypatch):
    """22. audit.status, failed_checks, verification, amendment_flags are unchanged."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    original = _blocked_audit(
        failed_checks=["cn_match"],
        amendment_flags=["Parse warning: inv-001"],
        verification={"cn_match": False, "cif_match": True},
        batch_id="BX",
    )
    _write_audit(outputs, "BX", original)

    client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "CN parent code accepted — known customs aggregation"},
    )

    audit = _read_audit(outputs, "BX")
    assert audit["status"] == "blocked"
    assert audit["failed_checks"] == ["cn_match"]
    assert audit["amendment_flags"] == ["Parse warning: inv-001"]
    assert audit["verification"] == {"cn_match": False, "cif_match": True}


def test_parse_warning_override_succeeds(tmp_path, monkeypatch):
    """23. invoice_number_parse_warning with existing Parse warning: flags → 200."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(
        failed_checks=[],
        amendment_flags=["Parse warning: could not parse invoice number from filename"],
        batch_id="BX",
    ))
    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={
            "check": "invoice_number_parse_warning",
            "reason": "Invoice filename non-standard but manually verified correct",
        },
    )
    assert r.status_code == 200
    audit = _read_audit(outputs, "BX")
    assert len(audit["operator_overrides"]) == 1
    assert audit["operator_overrides"][0]["check"] == "invoice_number_parse_warning"


def test_timeline_event_logged(tmp_path, monkeypatch):
    """24. Successful override logs operator_override_added timeline event."""
    client = _make_client(tmp_path, monkeypatch)
    outputs = tmp_path / "outputs"
    _write_audit(outputs, "BX", _blocked_audit(failed_checks=["cn_match"], batch_id="BX"))

    r = client.post(
        "/dashboard/batches/BX/operator-override",
        json={"check": "cn_match", "reason": "CN parent code accepted — known customs aggregation"},
    )
    assert r.status_code == 200

    audit = _read_audit(outputs, "BX")
    events = [e.get("event") for e in (audit.get("timeline") or [])]
    assert "operator_override_added" in events
