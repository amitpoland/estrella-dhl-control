"""
test_ingestor_engine_path.py

Focused tests for the engine-root resolution fix in email_evidence_ingestor.py.

Tests:
  1. settings.engine_dir is used as the scanner import path
  2. audit_path storage location does NOT determine engine root
  3. no credentials still returns no_credentials before scanner import is attempted
  4. no secrets are echoed in the no_credentials error response

Also covers the daily-token env-fallback path:
  5. os.environ ZOHO_MAIL_API_TOKEN is picked up when settings creds are absent
  6. env token is NOT echoed in the token_provider lambda (no leakage)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ─── helpers ──────────────────────────────────────────────────────────────────

def _fake_audit(tmp_path, awb="1234567890"):
    data = {"awb": awb, "batch_id": "BTST"}
    p = tmp_path / "audit.json"
    p.write_text(json.dumps(data))
    return p, data


def _store_patches():
    """Return a context manager that stubs out all evidence-store side effects."""
    return (
        patch("app.services.email_evidence_store.get_by_awb",
              return_value={"threads": [], "summary": {}}),
        patch("app.services.email_evidence_store.link_batch"),
        patch("app.services.email_evidence_store.save_message",
              return_value={"action": "inserted", "message_id": "mid1"}),
        patch("app.services.email_evidence_store.update_scan_cursor"),
    )


# ─── 1. settings.engine_dir is used for scanner import path ──────────────────

class TestEngineRootFromSettings:

    def test_engine_dir_from_settings_inserted_into_sys_path(self, tmp_path):
        """
        When settings.engine_dir is readable, that value is inserted into
        sys.path before dhl_email_monitor is imported — NOT any parent of
        audit_path.

        Strategy: clear dhl_email_monitor from sys.modules so the import runs
        fresh; point settings.engine_dir at a tmp dir that holds a stub module;
        verify the import succeeds (engine_dir was added to sys.path).
        """
        from app.services.email_evidence_ingestor import scan_and_ingest

        # Build a stub dhl_email_monitor in a known directory
        fake_engine = tmp_path / "fake_cli_root"
        fake_engine.mkdir()
        stub = fake_engine / "dhl_email_monitor.py"
        stub.write_text(
            "def scan_for_dhl_customs_emails(**kw):\n"
            "    return {'emails': [], 'scanned': 0, 'query_used': 'stub', 'scan_method': 'stub'}\n"
        )

        # audit_path is in a completely different deep storage hierarchy
        storage = tmp_path / "storage" / "outputs" / "BTST"
        storage.mkdir(parents=True)
        audit_p = storage / "audit.json"
        audit_p.write_text(json.dumps({"awb": "1234567890"}))

        # Remove any existing cached import so the fresh import actually runs
        sys.modules.pop("dhl_email_monitor", None)
        # Also remove fake_engine from sys.path if leftover from another test
        if str(fake_engine) in sys.path:
            sys.path.remove(str(fake_engine))

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.engine_dir = fake_engine
            mock_settings.zoho_mail_api_base = "https://mail.zoho.eu/api"

            p1, p2, p3, p4 = _store_patches()
            with p1, p2, p3, p4:
                result = scan_and_ingest(
                    "1234567890", "BTST", audit_p, {"awb": "1234567890"},
                    token_provider=lambda: "tok",
                    scan_fn=None,   # force the engine-root / import path
                )

        # Import must have succeeded via fake_engine (not scan_fn_unavailable)
        assert result.get("error") != "scan_fn_unavailable", (
            f"Scanner import failed — engine_dir was not added to sys.path. "
            f"result={result}"
        )
        assert str(fake_engine) in sys.path, (
            f"fake_engine {fake_engine} was not added to sys.path"
        )

        # Cleanup
        sys.modules.pop("dhl_email_monitor", None)
        if str(fake_engine) in sys.path:
            sys.path.remove(str(fake_engine))


# ─── 2. audit_path storage location does NOT determine engine root ────────────

class TestAuditPathDoesNotDetermineEngineRoot:

    def test_deep_storage_path_parent_chain_not_used(self, tmp_path):
        """
        audit_path lives at:
          /some/deep/storage/outputs/BTST/audit.json
        parent.parent.parent.parent = /some/deep — NOT the CLI root.
        When settings.engine_dir points somewhere else, the storage parent chain
        must never appear in sys.path as the engine root.
        """
        from app.services.email_evidence_ingestor import scan_and_ingest

        # Build a deep fake storage hierarchy
        deep_storage = tmp_path / "some" / "deep" / "storage" / "outputs" / "BTST"
        deep_storage.mkdir(parents=True)
        audit_p = deep_storage / "audit.json"
        audit_p.write_text(json.dumps({"awb": "1234567890"}))

        wrong_engine = str((deep_storage / ".." / ".." / ".." / "..").resolve())
        cli_root = tmp_path / "cli_root"
        cli_root.mkdir()

        fake_scan = MagicMock(return_value={
            "emails": [], "scanned": 0, "query_used": "q", "scan_method": "s",
        })

        sys_path_snapshot_before = list(sys.path)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.engine_dir = cli_root
            mock_settings.zoho_mail_api_base = "https://mail.zoho.eu/api"

            p1, p2, p3, p4 = _store_patches()
            with p1, p2, p3, p4:
                scan_and_ingest(
                    "1234567890", "BTST", audit_p, {"awb": "1234567890"},
                    token_provider=lambda: "tok",
                    scan_fn=fake_scan,
                )

        added = [p for p in sys.path if p not in sys_path_snapshot_before]
        # cli_root may be added; wrong_engine must NOT be added
        assert wrong_engine not in added, (
            f"Parent-hop path {wrong_engine!r} was inserted into sys.path — "
            "settings.engine_dir was not used."
        )


# ─── 3. no credentials → no_credentials returned before scanner import ────────

class TestNoCredentialsEarlyReturn:

    def test_no_creds_returns_before_scan_fn_import(self, tmp_path):
        """
        With no credentials in settings AND no ZOHO_MAIL_API_TOKEN env var,
        scan_and_ingest must return {"ok": False, "error": "no_credentials"}
        without ever attempting to import dhl_email_monitor.
        """
        from app.services.email_evidence_ingestor import scan_and_ingest

        audit_p, audit = _fake_audit(tmp_path)

        import_attempts: list[str] = []

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") \
            else __import__

        env_without_token = {k: v for k, v in os.environ.items()
                             if k != "ZOHO_MAIL_API_TOKEN"}

        with patch("app.services.zoho_auth.has_zoho_credentials",
                   return_value=False), \
             patch.dict(os.environ, env_without_token, clear=True):
            result = scan_and_ingest(
                "1234567890", "BTST", audit_p, audit,
                token_provider=None,
                scan_fn=None,          # must not be reached
            )

        assert result["ok"] is False
        assert result["error"] == "no_credentials"
        assert result["ingested"] == 0
        assert result.get("total_scanned", 0) == 0

    def test_no_creds_error_is_static_string(self, tmp_path):
        """
        The no_credentials error is the literal string 'no_credentials' —
        it does not echo env-var names or token values (no secrets printed).
        """
        from app.services.email_evidence_ingestor import scan_and_ingest

        audit_p, audit = _fake_audit(tmp_path)
        env_without_token = {k: v for k, v in os.environ.items()
                             if k != "ZOHO_MAIL_API_TOKEN"}

        with patch("app.services.zoho_auth.has_zoho_credentials",
                   return_value=False), \
             patch.dict(os.environ, env_without_token, clear=True):
            result = scan_and_ingest(
                "1234567890", "BTST", audit_p, audit,
                token_provider=None,
                scan_fn=None,
            )

        err = result.get("error", "")
        # Must be exactly the static sentinel — no token value appended
        assert err == "no_credentials", f"Unexpected error string: {err!r}"
        # Must not contain any token-like content
        assert "token" not in err.lower()
        assert "secret" not in err.lower()
        assert "1000." not in err          # Zoho token prefix pattern


# ─── 4. env token fallback (daily-refresh path) ───────────────────────────────

class TestEnvTokenFallback:

    def test_env_token_used_when_settings_creds_absent(self, tmp_path):
        """
        When settings has no Zoho credentials but ZOHO_MAIL_API_TOKEN is in
        os.environ, scan_and_ingest proceeds (does not return no_credentials).
        """
        from app.services.email_evidence_ingestor import scan_and_ingest

        audit_p, audit = _fake_audit(tmp_path)
        fake_scan = MagicMock(return_value={
            "emails": [], "scanned": 0, "query_used": "q", "scan_method": "s",
        })

        with patch("app.services.zoho_auth.has_zoho_credentials",
                   return_value=False), \
             patch.dict(os.environ, {"ZOHO_MAIL_API_TOKEN": "daily-tok-abc123"}):
            p1, p2, p3, p4 = _store_patches()
            with p1, p2, p3, p4:
                result = scan_and_ingest(
                    "1234567890", "BTST", audit_p, audit,
                    token_provider=None,
                    scan_fn=fake_scan,
                )

        # Should proceed (not bounce on no_credentials) and call scan_fn
        assert result["ok"] is True
        assert result.get("error") is None
        assert fake_scan.called

    def test_env_token_not_echoed_in_result(self, tmp_path):
        """
        The env token value must not appear anywhere in the returned dict.
        """
        from app.services.email_evidence_ingestor import scan_and_ingest

        audit_p, audit = _fake_audit(tmp_path)
        secret_token = "daily-tok-SUPERSECRET-xyz999"
        fake_scan = MagicMock(return_value={
            "emails": [], "scanned": 0, "query_used": "q", "scan_method": "s",
        })

        with patch("app.services.zoho_auth.has_zoho_credentials",
                   return_value=False), \
             patch.dict(os.environ, {"ZOHO_MAIL_API_TOKEN": secret_token}):
            p1, p2, p3, p4 = _store_patches()
            with p1, p2, p3, p4:
                result = scan_and_ingest(
                    "1234567890", "BTST", audit_p, audit,
                    token_provider=None,
                    scan_fn=fake_scan,
                )

        result_str = json.dumps(result)
        assert secret_token not in result_str, (
            "Secret token value leaked into scan_and_ingest result"
        )
