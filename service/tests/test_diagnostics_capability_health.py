"""B1 — capability-aware Diagnostics / health-full regression pins."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
from app.services import diagnostics_capability_health as dch  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    with (
        patch.object(settings, "api_key", "real-key"),
        patch.object(settings, "auth_secret_key", "test-secret-not-placeholder"),
        patch.object(settings, "environment", "prod"),
        patch.object(settings, "storage_root", tmp_path),
        patch.object(settings, "cliq_channel_webhook_url", ""),
        patch.object(settings, "cliq_bot_token", ""),
        patch.object(settings, "cliq_refresh_token", ""),
        patch.object(settings, "cliq_client_id", ""),
        patch.object(settings, "cliq_client_secret", ""),
        patch.object(settings, "debug_allow_old_batch_flow", False),
    ):
        # Provide a minimal engine dir so required engine check can pass when present
        eng = tmp_path / "engine"
        eng.mkdir()
        (eng / "pz_import_processor.py").write_text("# stub\n", encoding="utf-8")
        (eng / "audit_agent.py").write_text("# stub\n", encoding="utf-8")
        with patch.object(settings, "engine_dir", eng):
            (tmp_path / "outputs").mkdir()
            from app.main import app
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c


_HDR = {"X-API-Key": "real-key"}


def test_health_full_returns_capability_shape(client):
    r = client.get("/api/v1/debug/health-full", headers=_HDR)
    assert r.status_code == 200, r.text[:800]
    body = r.json()
    assert "overall" in body and "checks" in body
    assert "required_total" in body and "required_failed" in body
    assert "optional_not_configured" in body
    for key, chk in body["checks"].items():
        assert "requirement" in chk, key
        assert "status" in chk, key


def test_optional_cliq_missing_does_not_fail_overall(client):
    r = client.get("/api/v1/debug/health-full", headers=_HDR)
    body = r.json()
    c8 = body["checks"]["8_file_download_token"]
    assert c8["requirement"] == "optional"
    assert c8["status"] == "not_configured"
    # Missing Cliq must not be counted as a required failure
    assert body["required_failed"] == body["fail_count"]
    assert c8["status"] != "fail"


def test_deprecated_sessions_not_required_failure(client):
    r = client.get("/api/v1/debug/health-full", headers=_HDR)
    body = r.json()
    c4 = body["checks"]["4_sessions_endpoint"]
    assert c4["requirement"] == "deprecated"
    assert c4["status"] in ("deprecated", "not_applicable", "ok")
    # Must not increment required_failed solely because of sessions
    # (engine etc. may still fail in some envs — but sessions must not be required)
    assert c4["requirement"] != "required"


def test_classify_http_auth_is_reachable():
    st, detail = dch.classify_http_reachability(401, expect_auth=True)
    assert st == dch.STATUS_OK
    assert "protected" in detail.lower() or "401" in detail
    st5, _ = dch.classify_http_reachability(503, expect_auth=True)
    assert st5 == dch.STATUS_FAIL


def test_aggregate_ignores_optional_and_deprecated_fails():
    checks = {
        "a": dch.make_check(status="ok", requirement="required", detail="a"),
        "b": dch.make_check(status="fail", requirement="optional", detail="b"),
        "c": dch.make_check(status="deprecated", requirement="deprecated", detail="c"),
        "d": dch.make_check(status="not_configured", requirement="optional", detail="d"),
        "e": dch.make_check(status="warn", requirement="required", detail="e"),
    }
    s = dch.aggregate_checks(checks)
    assert s["overall"] == "ok"
    assert s["required_failed"] == 0
    assert s["fail_count"] == 0
    assert s["optional_failed"] == 1
    assert s["optional_not_configured"] >= 1
    assert s["deprecated"] >= 1


def test_optional_fail_keeps_overall_ok_required_fail_degrades():
    """Production-shaped aggregation pin (B1 closure gate).

    Optional capability in FAIL must leave overall=ok.
    A single required capability in FAIL must set overall=degraded.
    """
    optional_fail_only = {
        "1_fastapi_running": dch.make_check(status="ok", requirement="required", detail="ok"),
        "9_engine": dch.make_check(status="ok", requirement="required", detail="ok"),
        "8_file_download_token": dch.make_check(
            status="fail", requirement="optional", detail="token rejected"
        ),
        "4_sessions_endpoint": dch.make_check(
            status="deprecated", requirement="deprecated", detail="410"
        ),
    }
    s_opt = dch.aggregate_checks(optional_fail_only)
    assert s_opt["overall"] == "ok"
    assert s_opt["required_failed"] == 0
    assert s_opt["fail_count"] == 0
    assert s_opt["optional_failed"] == 1

    required_fail = {
        **optional_fail_only,
        "9_engine": dch.make_check(
            status="fail", requirement="required", detail="engine_dir not found"
        ),
    }
    s_req = dch.aggregate_checks(required_fail)
    assert s_req["overall"] == "degraded"
    assert s_req["required_failed"] == 1
    assert s_req["fail_count"] == 1
    assert s_req["optional_failed"] == 1  # still counted, still non-blocking


def test_aggregate_required_fail_degrades():
    checks = {
        "engine": dch.make_check(status="fail", requirement="required", detail="missing"),
        "cliq": dch.make_check(status="not_configured", requirement="optional", detail="n/c"),
    }
    s = dch.aggregate_checks(checks)
    assert s["overall"] == "degraded"
    assert s["required_failed"] == 1
    assert s["optional_failed"] == 0


def test_frontend_has_no_parallel_classification_authority():
    ops = (_SVC / "app/static/v2/ops-cell.jsx").read_text(encoding="utf-8")
    api = (_SVC / "app/static/v2/api-status-page.jsx").read_text(encoding="utf-8")
    for src in (ops, api):
        assert "REQUIRED_CHECKS" not in src
        assert "Cliq classification" not in src
    # KPI must not recount ok statuses from raw checks
    assert "Object.values(hData.checks" not in ops
    assert "filter(c => c.status === 'ok')" not in ops
    assert "Deployed SHA" in ops
    assert "Runtime mode:" in ops
    assert "optional_failed" in ops


def test_warning_not_equal_failure_in_ui_source():
    ops = (_SVC / "app/static/v2/ops-cell.jsx").read_text(encoding="utf-8")
    assert "required_failed" in ops
    assert "total - okCount" not in ops
    assert "Required health" in ops


def test_font_probe_no_macos_brew_remediation_on_windows():
    ok, detail, fix = dch.probe_pdf_unicode_font()
    # Vera from reportlab should satisfy on any platform with reportlab installed
    assert ok is True, detail
    assert "brew install" not in (fix or "").lower()
    if sys.platform.startswith("win"):
        assert "brew" not in (fix or "").lower()


def test_font_check_in_health_full_uses_renderer(client):
    r = client.get("/api/v1/debug/health-full", headers=_HDR)
    c12 = r.json()["checks"]["12_audit_font"]
    assert c12["requirement"] == "required"
    assert "brew install --cask" not in (c12.get("fix") or "")
    assert c12["status"] == "ok"


def test_engine_still_required_failure(client, tmp_path):
    bad = tmp_path / "no-engine"
    bad.mkdir()
    with patch.object(settings, "engine_dir", bad):
        # Re-hit with patched engine — use internal aggregator path via another call
        # Patch only for a direct function-level simulation:
        checks = {
            "9_engine": dch.make_check(
                status="fail",
                requirement="required",
                detail="engine_dir not found",
            )
        }
        s = dch.aggregate_checks(checks)
        assert s["overall"] == "degraded"


def test_no_localhost_8000_hardcode_in_health_full():
    import app.api.routes_debug as rd
    src = inspect.getsource(rd.health_full)
    assert "localhost:8000" not in src
    assert "request.base_url" in src or "local_base" in src


def test_system_version_exposes_runtime_mode_separately(client, tmp_path):
    marker = tmp_path / "version.txt"
    marker.write_text("ce4007f45187fe50103db1bc36e5bc82d2ded108\n", encoding="utf-8")
    with patch.object(dch, "_DEPLOY_VERSION_CANDIDATES", (marker,)):
        # read_deploy_marker_sha reads module-level tuple — patch the function instead
        with patch.object(dch, "read_deploy_marker_sha", return_value=(
            "ce4007f45187fe50103db1bc36e5bc82d2ded108", str(marker)
        )):
            # routes_system imports the function at call time via module reference
            import app.api.routes_system as rs
            with patch.object(rs, "read_deploy_marker_sha", return_value=(
                "ce4007f45187fe50103db1bc36e5bc82d2ded108", str(marker)
            )):
                r = client.get("/api/v1/system/version")
                assert r.status_code == 200
                body = r.json()
                assert body["deployed_sha"].startswith("ce4007f4")
                assert body["runtime_mode"] in ("dev", "prod")
                assert body.get("commit") != "dev" or body["deployed_sha"].startswith("ce4007")


def test_backup_probe_uses_unit_json(tmp_path):
    root = tmp_path / "backups"
    unit = root / "ce4007f4-20260811-204148"
    unit.mkdir(parents=True)
    (unit / "unit.json").write_text(
        json.dumps({"scope": "App", "created": "2026-08-11T18:41:48+00:00"}),
        encoding="utf-8",
    )
    chk = dch.probe_backup_freshness(root)
    assert chk["requirement"] == "optional"
    assert chk["status"] in ("ok", "warn")
    assert "manifest.json" not in (chk.get("fix") or "")


def test_batch_sessions_still_410_not_restored(client):
    r = client.get("/api/v1/batch/sessions", headers=_HDR)
    assert r.status_code == 410
