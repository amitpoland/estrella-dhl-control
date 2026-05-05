"""
test_check_wfirma_config.py — tests for check_wfirma_config.py

Covers:
  1. Config checks pass/fail depending on settings
  2. Missing required fields → config_ok=False, live checks skipped
  3. Secret values are NEVER present in any output string
  4. Live checks parse mocked XML responses correctly
  5. contractors/find reachable → check ok=True
  6. goods/find reachable → check ok=True
  7. warehouses/find parsed → warehouse_exists reflects WFIRMA_WAREHOUSE_ID match
  8. vat_codes/find reachable → check ok=True
  9. vat_code_23_id resolved from mocked response → returned in report
 10. HTTP error → live check ok=False with error message
 11. wFirma ERROR status → live check ok=False
 12. --config-only flag → live checks skipped regardless of config
 13. Missing .env file → env_file_present=False, tool still runs
 14. JSON output contains no secret values
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# bootstrap path so imports resolve from service/
import sys
_service = Path(__file__).resolve().parent.parent
if str(_service) not in sys.path:
    sys.path.insert(0, str(_service))

from app.core.config import settings
from app.tools.check_wfirma_config import _run_config_checks, _scan_env_file, diagnose


# ── Helpers ───────────────────────────────────────────────────────────────────

def _full_settings(**overrides):
    base = dict(
        wfirma_access_key="ACC-KEY",
        wfirma_secret_key="SEC-KEY",
        wfirma_app_key="APP-KEY-0123456789ABCDEF",
        wfirma_company_id="123456",
        wfirma_warehouse_id="WH-001",
        wfirma_warehouse_module_enabled=True,
    )
    base.update(overrides)
    return patch.multiple(settings, **base)


def _make_response(status_code: int, text: str) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


# XML fixtures
_XML_OK_CONTRACTORS = """<api>
  <contractors>
    <contractor><id>111</id><name>Dream Rings</name></contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""

_XML_OK_GOODS = """<api>
  <goods>
    <good><id>222</id><name>Pierścionek</name><code>EJL/001</code>
      <unit>szt.</unit><count>10.0000</count><reserved>2.0000</reserved>
    </good>
  </goods>
  <status><code>OK</code></status>
</api>"""

_XML_OK_WAREHOUSES = """<api>
  <warehouses>
    <warehouse><id>WH-001</id><name>Magazyn Główny</name></warehouse>
    <warehouse><id>WH-002</id><name>Magazyn B</name></warehouse>
  </warehouses>
  <status><code>OK</code></status>
</api>"""

_XML_OK_VATCODES_PROBE = """<api>
  <vat_codes>
    <vat_code><id>222</id><code>23</code><rate>23</rate></vat_code>
  </vat_codes>
  <status><code>OK</code></status>
</api>"""

_XML_OK_VATCODE_23 = """<api>
  <vat_codes>
    <vat_code><id>222</id><code>23</code><rate>23</rate><type>standard</type></vat_code>
  </vat_codes>
  <status><code>OK</code></status>
</api>"""

_XML_ERROR_AUTH = """<api>
  <status>
    <code>AUTH_FAILED</code>
    <description>Nieprawidłowy klucz API</description>
  </status>
</api>"""


def _all_ok_side_effect(method, url, **kwargs) -> MagicMock:
    """Route mock HTTP responses based on URL path."""
    if "contractors/find" in url:
        return _make_response(200, _XML_OK_CONTRACTORS)
    if "goods/find" in url:
        return _make_response(200, _XML_OK_GOODS)
    if "warehouses/find" in url:
        return _make_response(200, _XML_OK_WAREHOUSES)
    if "vat_codes/find" in url:
        return _make_response(200, _XML_OK_VATCODE_23)
    return _make_response(404, "<api><status><code>NOT_FOUND</code></status></api>")


# ── Tests: _scan_env_file ─────────────────────────────────────────────────────

def test_scan_env_file_present(tmp_path):
    env = tmp_path / ".env"
    env.write_text("WFIRMA_API_LOGIN=test@example.com\nWFIRMA_COMPANY_ID=123456\n")
    view = _scan_env_file(env)
    assert view["WFIRMA_API_LOGIN"] == len("test@example.com")
    assert view["WFIRMA_COMPANY_ID"] == len("123456")
    # Value itself is NOT in the dict keys — only the length
    assert "test@example.com" not in view


def test_scan_env_file_missing(tmp_path):
    view = _scan_env_file(tmp_path / "nonexistent.env")
    assert view == {}


def test_scan_env_file_ignores_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nWFIRMA_API_LOGIN=user\n")
    view = _scan_env_file(env)
    assert "# comment" not in view
    assert view["WFIRMA_API_LOGIN"] == len("user")


# ── Tests: _run_config_checks ─────────────────────────────────────────────────

def test_config_checks_all_present(tmp_path):
    with _full_settings():
        checks, config_ok = _run_config_checks({})
    assert config_ok is True
    for c in checks:
        if c["required"]:
            assert c["present"] is True, f"Expected {c['check']} to be present"


def test_config_checks_all_missing():
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
        wfirma_company_id="",
        wfirma_warehouse_id="",
    ):
        checks, config_ok = _run_config_checks({})
    assert config_ok is False
    required = [c for c in checks if c["required"]]
    assert all(not c["present"] for c in required)


def test_config_check_no_secrets_in_values():
    with _full_settings():
        checks, _ = _run_config_checks({})
    serialized = json.dumps(checks)
    # Secret values must not appear
    assert "APP-KEY-0123456789ABCDEF" not in serialized
    assert "super-secret-password" not in serialized
    assert "test@estrella.eu" not in serialized


def test_config_warehouse_id_optional():
    """WFIRMA_WAREHOUSE_ID is optional — its absence does NOT make config_ok=False."""
    with _full_settings(wfirma_warehouse_id=""):
        checks, config_ok = _run_config_checks({})
    assert config_ok is True
    wh_check = next(c for c in checks if c["check"] == "WFIRMA_WAREHOUSE_ID")
    assert wh_check["required"] is False


# ── Tests: diagnose() — config only ──────────────────────────────────────────

def test_diagnose_config_only_flag(tmp_path):
    with _full_settings():
        report = diagnose(tmp_path / ".env", config_only=True)
    assert report["live_skipped"] is True
    assert "config_only" in report["live_skip_reason"]
    assert report["live_checks"] == []


def test_diagnose_skips_live_when_config_missing(tmp_path):
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
        wfirma_company_id="",
        wfirma_warehouse_id="",
    ):
        report = diagnose(tmp_path / ".env")
    assert report["config_ok"] is False
    assert report["live_skipped"] is True
    assert report["live_checks"] == []


def test_diagnose_missing_env_file_reports_false(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")
    assert report["env_file_present"] is False
    # Should still run config checks (settings loaded from .env in service dir)


# ── Tests: live checks with mocked HTTP ──────────────────────────────────────

def test_live_checks_all_ok(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    assert report["live_skipped"] is False
    assert len(report["live_checks"]) == 5

    for c in report["live_checks"]:
        assert c["ok"] is True, f"Check {c['check']} expected ok=True, got {c}"


def test_live_checks_contractors_find_ok(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    check = next(c for c in report["live_checks"] if c["check"] == "contractors/find")
    assert check["ok"] is True
    assert check["http_status"] == 200
    assert check["wfirma_status"] == "OK"
    assert check["auth_mode"] == "api_key_headers"


def test_live_checks_goods_find_ok(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    check = next(c for c in report["live_checks"] if c["check"] == "goods/find")
    assert check["ok"] is True
    assert check["auth_mode"] == "api_key_headers"


def test_live_checks_warehouses_find_ok_and_warehouse_exists(tmp_path):
    with _full_settings(wfirma_warehouse_id="WH-001"):
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    check = next(c for c in report["live_checks"] if c["check"] == "warehouses/find")
    assert check["ok"] is True
    assert report["warehouse_exists"] is True
    assert report["warehouse_id"] == "WH-001"


def test_live_checks_warehouse_id_not_in_response(tmp_path):
    """WFIRMA_WAREHOUSE_ID set to a value that doesn't appear in the mocked response."""
    with _full_settings(wfirma_warehouse_id="WH-UNKNOWN"):
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    assert report["warehouse_exists"] is False


def test_live_checks_vat_codes_find_ok(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    check = next(c for c in report["live_checks"] if c["check"] == "vat_codes/find")
    assert check["ok"] is True


def test_live_checks_vat_code_23_resolved(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    check = next(c for c in report["live_checks"] if c["check"] == "vat_code_23_id")
    assert check["ok"] is True
    assert report["vat_code_23_id"] == "222"
    assert "222" in check["info"]


# ── Tests: failure scenarios ──────────────────────────────────────────────────

def test_live_checks_auth_failed(tmp_path):
    """wFirma returns AUTH_FAILED → all live checks ok=False."""
    def _auth_fail(method, url, **kwargs):
        return _make_response(200, _XML_ERROR_AUTH)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_auth_fail):
            report = diagnose(tmp_path / ".env")

    for c in report["live_checks"]:
        assert c["ok"] is False, f"Check {c['check']} should be ok=False on AUTH_FAILED"


def test_live_checks_http_500(tmp_path):
    """HTTP 500 → live check ok=False, http_status=500."""
    def _server_error(method, url, **kwargs):
        return _make_response(500, "<html>Server Error</html>")

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_server_error):
            report = diagnose(tmp_path / ".env")

    contractors = next(c for c in report["live_checks"] if c["check"] == "contractors/find")
    assert contractors["ok"] is False
    assert contractors["http_status"] == 500


def test_live_checks_connection_error(tmp_path):
    """Network failure → live check ok=False with CONNECTION_ERROR status."""
    import requests as req_lib

    def _conn_fail(method, url, **kwargs):
        raise req_lib.exceptions.ConnectionError("Connection refused")

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_conn_fail):
            report = diagnose(tmp_path / ".env")

    contractors = next(c for c in report["live_checks"] if c["check"] == "contractors/find")
    assert contractors["ok"] is False
    assert contractors["wfirma_status"] == "CONNECTION_ERROR"


def test_live_vat_code_23_not_found(tmp_path):
    """vat_codes/find returns OK but no vat_code element → vat_code_23_id=None."""
    _xml_no_vat = """<api>
  <vat_codes></vat_codes>
  <status><code>OK</code></status>
</api>"""

    def _no_vat(method, url, **kwargs):
        if "vat_codes/find" in url:
            return _make_response(200, _xml_no_vat)
        return _all_ok_side_effect(method, url, **kwargs)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_no_vat):
            report = diagnose(tmp_path / ".env")

    assert report["vat_code_23_id"] is None
    check = next(c for c in report["live_checks"] if c["check"] == "vat_code_23_id")
    assert check["ok"] is False


# ── Tests: no secrets in output ───────────────────────────────────────────────

def test_no_secret_values_in_json_output(tmp_path):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")

    serialized = json.dumps(report)
    # Actual credential values must NOT appear in any output
    assert "APP-KEY-0123456789ABCDEF" not in serialized
    assert "super-secret-password" not in serialized
    assert "test@estrella.eu" not in serialized


def test_no_secret_values_in_human_output(tmp_path, capsys):
    from app.tools.check_wfirma_config import _print_human

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok_side_effect):
            report = diagnose(tmp_path / ".env")
        _print_human(report)

    captured = capsys.readouterr().out
    assert "APP-KEY-0123456789ABCDEF" not in captured
    assert "super-secret-password" not in captured
    assert "test@estrella.eu" not in captured
