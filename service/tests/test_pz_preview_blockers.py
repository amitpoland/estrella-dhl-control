"""PZ Preview Authority Audit (2026-05-21).

Tests `_collect_pz_preview_blockers` — the read-only structured-blockers
authority for `/wfirma/pz_preview`. Each test exercises one root cause and
asserts the corresponding blocker code is emitted (or suppressed when an
upstream cause already explains the same fault).
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def routes_wfirma():
    """Import the module once per test so feature-flag toggles take effect."""
    import service.app.api.routes_wfirma as m
    return importlib.reload(m)


def _audit(**overrides):
    base = {
        "status": "success",
        "inputs": {"zc429": "any/path.pdf"},
        "engine_error": None,
    }
    base.update(overrides)
    return base


def test_emits_wfirma_no_sad_when_zc429_missing(tmp_path: Path, routes_wfirma):
    audit = _audit(inputs={})
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    codes = [b["code"] for b in blockers]
    assert "WFIRMA_NO_SAD" in codes
    sad = next(b for b in blockers if b["code"] == "WFIRMA_NO_SAD")
    assert sad["severity"] == "error"
    assert sad["source"] == "audit.inputs.zc429"


def test_emits_pz_not_generated_when_status_failed_no_engine_error(tmp_path: Path, routes_wfirma):
    # No engine_error set, but status failed → emit WFIRMA_PZ_NOT_GENERATED.
    audit = _audit(status="failed")
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    codes = [b["code"] for b in blockers]
    assert "WFIRMA_PZ_NOT_GENERATED" in codes


def test_emits_engine_error_with_verbatim_message(tmp_path: Path, routes_wfirma):
    msg = "Total before-duty PLN is zero — check invoice FOB values"
    audit = _audit(status="failed", engine_error=msg)
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    eng = [b for b in blockers if b["code"] == "ENGINE_ERROR"]
    assert len(eng) == 1
    assert eng[0]["message"] == msg
    assert eng[0]["source"] == "audit.engine_error"


def test_engine_error_suppresses_duplicate_pz_not_generated(tmp_path: Path, routes_wfirma):
    # When ENGINE_ERROR is the root cause, do not double-emit
    # WFIRMA_PZ_NOT_GENERATED — they describe the same fault.
    audit = _audit(status="failed", engine_error="something failed")
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    codes = [b["code"] for b in blockers]
    assert codes.count("ENGINE_ERROR") == 1
    assert "WFIRMA_PZ_NOT_GENERATED" not in codes


def test_engine_error_suppresses_no_rows(tmp_path: Path, routes_wfirma):
    # Same suppression rule applies for WFIRMA_NO_ROWS — they share a cause.
    audit = _audit(status="failed", engine_error="parser bug")
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    codes = [b["code"] for b in blockers]
    assert "WFIRMA_NO_ROWS" not in codes


def test_emits_no_rows_when_no_engine_error_and_outputs_missing(tmp_path: Path, routes_wfirma):
    # success status, no engine_error, but no pz_rows.json / xlsx on disk.
    audit = _audit(status="success", engine_error=None)
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    codes = [b["code"] for b in blockers]
    assert "WFIRMA_NO_ROWS" in codes


def test_no_blockers_when_all_prerequisites_pass(tmp_path: Path, routes_wfirma):
    # Make pz_rows.json exist.
    (tmp_path / "pz_rows.json").write_text("[]", encoding="utf-8")
    audit = _audit(status="success", engine_error=None)
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    assert blockers == []


def test_feature_flag_default_on(routes_wfirma, monkeypatch):
    monkeypatch.delenv("PZ_PREVIEW_STRUCTURED_BLOCKERS", raising=False)
    assert routes_wfirma._pz_preview_structured_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "False", "no", "off"])
def test_feature_flag_off_values(routes_wfirma, monkeypatch, val):
    monkeypatch.setenv("PZ_PREVIEW_STRUCTURED_BLOCKERS", val)
    assert routes_wfirma._pz_preview_structured_enabled() is False


def test_blocker_shape_is_stable(tmp_path: Path, routes_wfirma):
    # Every blocker must carry these four keys — the frontend depends on
    # this shape. Treat as part of the public API contract.
    audit = _audit(inputs={}, status="failed", engine_error="x")
    blockers = routes_wfirma._collect_pz_preview_blockers(audit, tmp_path)
    assert len(blockers) >= 2
    for b in blockers:
        assert set(b.keys()) == {"code", "message", "severity", "source"}
        assert b["severity"] in ("error", "warning")
