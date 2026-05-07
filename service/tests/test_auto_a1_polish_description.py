"""
test_auto_a1_polish_description.py — Phase 2.1 auto-A1 observer.

Pins the audit-state observer that auto-generates the Polish customs
description PDF for Path A shipments after upload. Spec ref: docs/
dhl_clearance_paths.md row A1 ("Operator action or auto after upload").
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
    return S()


def _write_audit(tmp_path: Path, batch_id: str, audit: dict) -> Path:
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit), encoding="utf-8")
    return ap


def _path_a_audit(awb: str = "1012178215") -> dict:
    return {
        "batch_id":     "B_A1_TEST",
        "awb":          awb,
        "tracking_no":  awb,
        "clearance_decision": {
            "clearance_path":  "dhl_self_clearance",
            "total_value_usd": 1500.0,
        },
        "invoice_totals": {"total_cif_usd": 1500.0},
    }


def _path_b_audit(awb: str = "1012178215") -> dict:
    a = _path_a_audit(awb)
    a["clearance_decision"]["clearance_path"] = "agency_clearance"
    a["clearance_decision"]["total_value_usd"] = 5000.0
    a["invoice_totals"]["total_cif_usd"] = 5000.0
    return a


def _fake_pkg_success(filename: str = "POLISH_DESC.pdf"):
    return {
        "pdf":  {"generated": True, "filename": filename,
                 "output_path": f"/tmp/{filename}"},
        "json": {"generated": False},
    }


def _patch_engine(success=True, exc: Exception | None = None):
    """Patch customs_description_engine.generate_customs_description_package."""
    if exc is not None:
        return patch("customs_description_engine.generate_customs_description_package",
                     side_effect=exc)
    if success:
        return patch("customs_description_engine.generate_customs_description_package",
                     return_value=_fake_pkg_success())
    return patch("customs_description_engine.generate_customs_description_package",
                 return_value={"pdf": {"generated": False, "error": "stub"}, "json": {}})


# ── 1. Path A + no PDF yet → fires + writes audit ──────────────────────────

def test_path_a_first_pass_generates_polish_desc(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    ap = _write_audit(tmp_path, "B_A1_OK", _path_a_audit())
    audit = json.loads(ap.read_text())

    with _patch_engine(success=True):
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is True
    assert result["skipped"] is False
    assert result["error"] is None
    assert result["filename"] == "POLISH_DESC.pdf"
    persisted = json.loads(ap.read_text())
    assert persisted["polish_desc_filename"] == "POLISH_DESC.pdf"
    assert persisted.get("polish_desc_generated_at")


# ── 2. Path B → does NOT fire ──────────────────────────────────────────────

def test_path_b_skipped(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    ap = _write_audit(tmp_path, "B_A1_PATHB", _path_b_audit())
    audit = json.loads(ap.read_text())

    with _patch_engine(success=True) as m:
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is False
    assert result["skipped"] is True
    m.assert_not_called()


# ── 3. polish_desc_filename already set → idempotent skip ──────────────────

def test_idempotent_when_already_generated(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    a = _path_a_audit()
    a["polish_desc_filename"] = "EXISTING.pdf"
    ap = _write_audit(tmp_path, "B_A1_IDEM", a)
    audit = json.loads(ap.read_text())

    with _patch_engine(success=True) as m:
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is False
    assert result["skipped"] is True
    m.assert_not_called()


# ── 4. clearance_decision absent → does NOT fire ───────────────────────────

def test_no_clearance_decision_skipped(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    a = _path_a_audit()
    del a["clearance_decision"]
    ap = _write_audit(tmp_path, "B_A1_NO_CD", a)
    audit = json.loads(ap.read_text())

    with _patch_engine(success=True) as m:
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is False
    assert result["skipped"] is True
    m.assert_not_called()


# ── 5. Engine raises → failure marker written, no propagation ──────────────

def test_failure_writes_marker_does_not_raise(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    ap = _write_audit(tmp_path, "B_A1_FAIL", _path_a_audit())
    audit = json.loads(ap.read_text())

    with _patch_engine(exc=ValueError("invoice rows missing")):
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is False
    assert result["skipped"] is False
    assert "invoice rows missing" in result["error"]
    persisted = json.loads(ap.read_text())
    err = persisted.get("polish_desc_generation_error")
    assert err is not None
    assert err["exception_type"] == "ValueError"
    assert "invoice rows missing" in err["reason"]
    assert err.get("timestamp")
    # No filename written
    assert "polish_desc_filename" not in persisted


# ── 6. Re-run after success is a no-op ─────────────────────────────────────

def test_rerun_after_success_is_noop(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    ap = _write_audit(tmp_path, "B_A1_RERUN", _path_a_audit())

    with _patch_engine(success=True) as m:
        # First pass — generates
        first = asm._ensure_polish_description(ap, json.loads(ap.read_text()))
        assert first["generated"] is True
        assert m.call_count == 1
        # Second pass — idempotent skip
        second = asm._ensure_polish_description(ap, json.loads(ap.read_text()))
        assert second["generated"] is False
        assert second["skipped"] is True
        assert m.call_count == 1  # engine not called again


# ── 7. Prior failure marker blocks re-run (operator must explicitly retry) ──

def test_prior_failure_blocks_auto_retry(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    a = _path_a_audit()
    a["polish_desc_generation_error"] = {
        "timestamp": "2026-05-07T10:00:00+00:00",
        "reason": "prior failure",
        "exception_type": "RuntimeError",
    }
    ap = _write_audit(tmp_path, "B_A1_PRIOR_FAIL", a)
    audit = json.loads(ap.read_text())

    with _patch_engine(success=True) as m:
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is False
    assert result["skipped"] is True
    m.assert_not_called()


# ── 8. CIF zero → skipped (no error marker; engine guard) ──────────────────

def test_cif_zero_skipped(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "settings", _settings(tmp_path))

    a = _path_a_audit()
    a["invoice_totals"]["total_cif_usd"] = 0.0
    ap = _write_audit(tmp_path, "B_A1_CIF0", a)
    audit = json.loads(ap.read_text())

    with _patch_engine(success=True) as m:
        result = asm._ensure_polish_description(ap, audit)

    assert result["generated"] is False
    assert result["skipped"] is True
    assert "polish_desc_generation_error" not in json.loads(ap.read_text())
    m.assert_not_called()
