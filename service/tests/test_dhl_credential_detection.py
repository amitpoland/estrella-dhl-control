"""
test_dhl_credential_detection.py — DHL credential resolution + diagnostic CLI.

Guards:
  - canonical env names (DHL_TRACKING_API_KEY / SECRET) are detected
  - alias env names (DHL_CLIENT_ID / DHL_CLIENT_SECRET) are detected
  - legacy DHL_API_KEY is treated as credential present
  - missing creds → mode=disabled
  - never logs / returns secret values from check_dhl_config
"""
from __future__ import annotations

import io
import json
import sys
import contextlib
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core import config as cfg               # noqa: E402
from app.services import tracking_service as ts  # noqa: E402
from app.tools import check_dhl_config           # noqa: E402


# ── Credential resolution ────────────────────────────────────────────────────

class TestCredentialResolution:
    def test_canonical_keys_detected(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "canon-key")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "canon-sec")
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")
        monkeypatch.delenv("DHL_CLIENT_ID", raising=False)
        monkeypatch.delenv("DHL_CLIENT_SECRET", raising=False)
        assert ts.get_tracking_mode() == "active"

    def test_alias_oauth_names_detected(self, monkeypatch):
        """Operator may have set DHL_CLIENT_ID/SECRET — must resolve too."""
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")
        monkeypatch.setenv("DHL_CLIENT_ID", "oauth-id-xyz")
        monkeypatch.setenv("DHL_CLIENT_SECRET", "oauth-sec-xyz")
        assert ts.get_tracking_mode() == "active"

    def test_legacy_api_key_alone_treated_as_present(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "legacy-header-key")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")
        monkeypatch.delenv("DHL_CLIENT_ID", raising=False)
        monkeypatch.delenv("DHL_CLIENT_SECRET", raising=False)
        assert ts.get_tracking_mode() == "active"

    def test_no_credentials_returns_disabled(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")
        monkeypatch.delenv("DHL_CLIENT_ID", raising=False)
        monkeypatch.delenv("DHL_CLIENT_SECRET", raising=False)
        assert ts.get_tracking_mode() == "disabled"

    def test_creds_present_but_status_failed(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "s")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "failed")
        assert ts.get_tracking_mode() == "failed"

    def test_legacy_pending_collapses_when_creds_present(self, monkeypatch):
        """Even with credentials, legacy 'pending' string maps to disabled."""
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "k")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "s")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "pending")
        assert ts.get_tracking_mode() == "disabled"


# ── Diagnostic CLI ────────────────────────────────────────────────────────────

class TestDiagnosticCLI:
    def _run(self, env_path: Path, json_mode: bool = False) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            argv = ["--env", str(env_path)]
            if json_mode:
                argv.append("--json")
            check_dhl_config.main(argv)
        return buf.getvalue()

    def test_cli_runs_clean_with_missing_env(self, tmp_path, monkeypatch):
        # Empty .env → mode=disabled, root cause stated
        env = tmp_path / ".env"; env.write_text("")
        # Force the loader to see no creds
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "")
        monkeypatch.delenv("DHL_CLIENT_ID", raising=False)
        monkeypatch.delenv("DHL_CLIENT_SECRET", raising=False)

        out = self._run(env)
        assert "DHL TRACKING CREDENTIAL DIAGNOSTIC" in out
        assert "ROOT CAUSE" in out
        assert "absent or empty" in out

    def test_cli_json_output_shape(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"; env.write_text("DHL_TRACKING_API_STATUS=disabled\n")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", "")
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "disabled")
        monkeypatch.delenv("DHL_CLIENT_ID", raising=False)
        monkeypatch.delenv("DHL_CLIENT_SECRET", raising=False)

        out = self._run(env, json_mode=True)
        data = json.loads(out)
        assert data["env_file_present"] is True
        assert data["tracking_mode"] == "disabled"
        assert "fields" in data and len(data["fields"]) == 4
        # No secret values in any field
        for f in data["fields"]:
            assert "value" not in f                # never present
            assert "primary_value_length" in f     # only length

    def test_cli_never_prints_secret_values(self, tmp_path, monkeypatch):
        secret_marker = "ABRACADABRA_SECRET_TOKEN"
        env = tmp_path / ".env"
        env.write_text(
            "DHL_TRACKING_API_KEY=" + secret_marker + "\n"
            "DHL_TRACKING_API_SECRET=" + secret_marker + "\n"
            "DHL_TRACKING_API_STATUS=active\n"
        )
        # Loader is patched empty so the test doesn't depend on settings.cache
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_key", secret_marker)
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_secret", secret_marker)
        monkeypatch.setattr(cfg.settings, "dhl_api_key", "")
        monkeypatch.setattr(cfg.settings, "dhl_tracking_api_status", "active")

        text = self._run(env)
        json_text = self._run(env, json_mode=True)
        for blob in (text, json_text):
            assert secret_marker not in blob, "secret leaked into diagnostic output"
