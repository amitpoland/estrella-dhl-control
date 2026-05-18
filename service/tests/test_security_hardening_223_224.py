"""
test_security_hardening_223_224.py

Tests for Issue #223 (Lesson E Property 5 — email ENV isolation guard)
and Issue #224 (path traversal guard in save_file).

Both guards are pre-existing risks now fixed in:
  - service/app/services/email_sender.py  (_assert_production_env_for_smtp)
  - service/app/services/shipment_folder_manager.py  (save_file src validation)
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch


# ─── Issue #223 — Lesson E Property 5: ENV isolation ────────────────────────

class TestEmailEnvIsolationGuard:
    """_assert_production_env_for_smtp must raise when env != prod and SMTP configured."""

    def test_raises_when_smtp_configured_in_dev(self, tmp_path):
        """Dev environment with SMTP creds must not connect."""
        from app.services.email_sender import _assert_production_env_for_smtp

        with patch("app.services.email_sender.settings") as mock_settings:
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "secret"
            mock_settings.smtp_host = "smtp.zoho.com"
            mock_settings.environment = "dev"

            with pytest.raises(RuntimeError, match="SMTP credentials are configured but environment="):
                _assert_production_env_for_smtp()

    def test_no_raise_in_prod_with_smtp(self):
        """Production environment with SMTP creds is the intended state."""
        from app.services.email_sender import _assert_production_env_for_smtp

        with patch("app.services.email_sender.settings") as mock_settings:
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "secret"
            mock_settings.smtp_host = "smtp.zoho.com"
            mock_settings.environment = "prod"

            # Must not raise
            _assert_production_env_for_smtp()

    def test_no_raise_when_smtp_not_configured(self):
        """No SMTP creds → guard is a no-op (nothing to block)."""
        from app.services.email_sender import _assert_production_env_for_smtp

        with patch("app.services.email_sender.settings") as mock_settings:
            mock_settings.smtp_user = ""
            mock_settings.smtp_password = ""
            mock_settings.smtp_host = ""
            mock_settings.environment = "dev"

            # No creds → no SMTP risk → no raise
            _assert_production_env_for_smtp()

    def test_error_message_identifies_current_env(self):
        """Error message must include the actual environment value for debuggability."""
        from app.services.email_sender import _assert_production_env_for_smtp

        with patch("app.services.email_sender.settings") as mock_settings:
            mock_settings.smtp_user = "u"
            mock_settings.smtp_password = "p"
            mock_settings.smtp_host = "h"
            mock_settings.environment = "dev"

            with pytest.raises(RuntimeError) as exc_info:
                _assert_production_env_for_smtp()

            assert "'dev'" in str(exc_info.value)


# ─── Issue #224 — Path traversal guard in save_file ────────────────────────

class TestSaveFilePathTraversalGuard:
    """save_file must reject src_path outside storage_root."""

    def test_rejects_absolute_path_outside_storage_root(self, tmp_path):
        """Operator-supplied path outside storage_root must be blocked."""
        from app.services.shipment_folder_manager import save_file

        storage_root = tmp_path / "storage"
        storage_root.mkdir()

        # A file that exists on the filesystem but outside storage_root
        outside_file = tmp_path / "sensitive.txt"
        outside_file.write_text("sensitive data")

        with patch("app.services.shipment_folder_manager.settings") as mock_settings:
            mock_settings.storage_root = storage_root

            with pytest.raises(PermissionError, match="outside allowed storage root"):
                save_file("BATCH001", str(outside_file), "invoice")

    def test_rejects_etc_passwd_style_path(self, tmp_path):
        """Classic path traversal attempt must be blocked."""
        from app.services.shipment_folder_manager import save_file

        storage_root = tmp_path / "storage"
        storage_root.mkdir()

        with patch("app.services.shipment_folder_manager.settings") as mock_settings:
            mock_settings.storage_root = storage_root

            with pytest.raises(PermissionError):
                # /etc/hostname exists on most systems; use it as traversal target
                save_file("BATCH001", "/etc/hostname", "invoice")

    def test_allows_path_inside_storage_root(self, tmp_path):
        """Legitimate path under storage_root must be allowed."""
        from app.services.shipment_folder_manager import save_file

        storage_root = tmp_path / "storage"
        storage_root.mkdir()

        # Create source file inside storage_root
        incoming = storage_root / "incoming"
        incoming.mkdir()
        src_file = incoming / "invoice.pdf"
        src_file.write_bytes(b"%PDF-1.4 test")

        # Create target batch layout
        batch_dir = storage_root / "outputs" / "BATCH001"
        batch_dir.mkdir(parents=True)

        with patch("app.services.shipment_folder_manager.settings") as mock_settings:
            mock_settings.storage_root = storage_root
            # Mock folder_for to return a writable dir
            with patch("app.services.shipment_folder_manager.folder_for") as mock_folder:
                dest_dir = storage_root / "outputs" / "BATCH001" / "01_invoices"
                dest_dir.mkdir(parents=True)
                mock_folder.return_value = dest_dir

                result = save_file("BATCH001", str(src_file), "invoice")
                assert result.name == "invoice.pdf"
                assert result.exists()

    def test_rejects_path_traversal_via_dotdot(self, tmp_path):
        """Path traversal via .. must be caught after resolve()."""
        from app.services.shipment_folder_manager import save_file

        storage_root = tmp_path / "storage"
        storage_root.mkdir()

        # Create a file inside storage_root, then construct a path that traverses out
        inner = storage_root / "sub"
        inner.mkdir()
        traversal = str(inner) + "/../../sensitive.txt"

        # Create the "sensitive" file one level above storage_root
        (tmp_path / "sensitive.txt").write_text("outside")

        with patch("app.services.shipment_folder_manager.settings") as mock_settings:
            mock_settings.storage_root = storage_root

            with pytest.raises(PermissionError, match="outside allowed storage root"):
                save_file("BATCH001", traversal, "invoice")
