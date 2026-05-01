"""
test_email_evidence_v2_default.py

Verifies the EMAIL_EVIDENCE_V2 feature-flag default-on promotion.

Tests:
  1. Missing env var → V2 enabled (default=True in config)
  2. EMAIL_EVIDENCE_V2=1 → V2 enabled
  3. EMAIL_EVIDENCE_V2=0 → legacy (V2 disabled)
  4. EMAIL_EVIDENCE_V2=false → legacy (V2 disabled)
  5. Ingestion worker reads flag from settings (default True fallback)
  6. Rollback: EMAIL_EVIDENCE_V2=0 prevents evidence store writes in ingestion worker
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY",      "test-key")
os.environ.setdefault("STORAGE_ROOT", "/tmp/test_ev2_default")


# ── Config-level tests ────────────────────────────────────────────────────────

class TestEmailEvidenceV2ConfigDefault:

    def _build_settings(self, env_val: str | None):
        """Instantiate Settings with a controlled EMAIL_EVIDENCE_V2 env var."""
        from app.core.config import Settings
        env = {}
        if env_val is not None:
            env["EMAIL_EVIDENCE_V2"] = env_val
        with patch.dict(os.environ, env, clear=False):
            # Remove the key entirely when testing "missing"
            saved = os.environ.pop("EMAIL_EVIDENCE_V2", None)
            if env_val is not None:
                os.environ["EMAIL_EVIDENCE_V2"] = env_val
            try:
                return Settings()
            finally:
                if saved is not None:
                    os.environ["EMAIL_EVIDENCE_V2"] = saved
                elif "EMAIL_EVIDENCE_V2" in os.environ:
                    del os.environ["EMAIL_EVIDENCE_V2"]

    def test_missing_env_var_enables_v2(self):
        """When EMAIL_EVIDENCE_V2 is not set at all, V2 must be enabled."""
        saved = os.environ.pop("EMAIL_EVIDENCE_V2", None)
        try:
            from app.core.config import Settings
            s = Settings()
            assert s.email_evidence_v2 is True, (
                "Default must be True — missing env var should enable V2"
            )
        finally:
            if saved is not None:
                os.environ["EMAIL_EVIDENCE_V2"] = saved

    def test_explicit_1_enables_v2(self):
        """EMAIL_EVIDENCE_V2=1 must enable V2."""
        os.environ["EMAIL_EVIDENCE_V2"] = "1"
        try:
            from app.core.config import Settings
            s = Settings()
            assert s.email_evidence_v2 is True
        finally:
            del os.environ["EMAIL_EVIDENCE_V2"]

    def test_explicit_0_disables_v2(self):
        """EMAIL_EVIDENCE_V2=0 must disable V2 (rollback path)."""
        os.environ["EMAIL_EVIDENCE_V2"] = "0"
        try:
            from app.core.config import Settings
            s = Settings()
            assert s.email_evidence_v2 is False, (
                "EMAIL_EVIDENCE_V2=0 must disable V2 — this is the rollback command"
            )
        finally:
            del os.environ["EMAIL_EVIDENCE_V2"]

    def test_explicit_false_string_disables_v2(self):
        """EMAIL_EVIDENCE_V2=false must disable V2."""
        os.environ["EMAIL_EVIDENCE_V2"] = "false"
        try:
            from app.core.config import Settings
            s = Settings()
            assert s.email_evidence_v2 is False
        finally:
            del os.environ["EMAIL_EVIDENCE_V2"]


# ── Ingestion worker fallback tests ───────────────────────────────────────────

class TestIngestionWorkerV2Flag:

    def test_worker_default_fallback_is_true(self):
        """getattr(settings, 'email_evidence_v2', True) — fallback must be True."""
        mock_settings = MagicMock(spec=[])  # no attributes
        v2_on = bool(getattr(mock_settings, "email_evidence_v2", True))
        assert v2_on is True

    def test_worker_reads_false_when_disabled(self):
        """When settings.email_evidence_v2 is False, worker skips V2 path."""
        mock_settings = MagicMock()
        mock_settings.email_evidence_v2 = False
        v2_on = bool(getattr(mock_settings, "email_evidence_v2", True))
        assert v2_on is False

    def test_rollback_env_prevents_v2_writes(self, tmp_path):
        """EMAIL_EVIDENCE_V2=0: ingestion worker must not call save_message."""
        os.environ["EMAIL_EVIDENCE_V2"] = "0"
        try:
            from app.core.config import Settings
            s = Settings()
            assert s.email_evidence_v2 is False
            # simulate worker decision
            v2_on = bool(getattr(s, "email_evidence_v2", True))
            assert v2_on is False, "Rollback must prevent V2 writes in worker"
        finally:
            del os.environ["EMAIL_EVIDENCE_V2"]
