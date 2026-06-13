"""
test_authority_drift_runtime.py — Authority drift runtime tests (Part B)

Tests for R1, R2, R3 runtime components:
- R1: Startup authority manifest generation
- R2: Authority drift detection endpoint
- R3: Config flag behavior

Design reference: designs/audit-drift-design.md v2 Part B (APPROVED)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestAuthorityRuntimeComponents:
    """Runtime authority drift detection tests."""

    def test_r1_startup_manifest_generation(self):
        """R1: Startup manifest writes advisory manifest to storage."""
        from app.services.authority_startup import generate_startup_authority_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)

            # Generate manifest
            manifest = generate_startup_authority_manifest(storage_root)

            # Verify manifest structure
            assert manifest["format_version"] == "1.0"
            assert manifest["generated_by"] == "authority_startup.py"
            assert manifest["generated_at_startup"] is True
            assert "modules" in manifest

            # Verify manifest file was written
            manifest_path = storage_root / "authority_manifest.json"
            assert manifest_path.exists()

            # Verify file content
            written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert written_manifest["format_version"] == "1.0"
            assert "modules" in written_manifest

    def test_r1_never_blocks_on_exception(self):
        """R1: Manifest generation never blocks startup on error."""
        from app.services.authority_startup import generate_startup_authority_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)

            # Make storage_root read-only to force write error
            storage_root.chmod(0o555)

            try:
                # Should not raise exception
                manifest = generate_startup_authority_manifest(storage_root)

                # Should still return manifest even if write failed
                assert "modules" in manifest
                assert manifest["format_version"] == "1.0"

            finally:
                # Restore permissions
                storage_root.chmod(0o755)

    def test_r2_flag_off_returns_503_with_reason(self):
        """R3: When authority_drift_detection=False, endpoint returns 503 with explicit reason."""
        from app.main import app
        from app.auth.dependencies import require_admin

        client = TestClient(app)

        # Override admin auth dependency
        app.dependency_overrides[require_admin] = lambda: {"email": "test@example.com", "role": "admin"}

        try:
            # Mock settings to have flag OFF
            with patch("app.api.routes_admin.settings") as mock_settings:
                mock_settings.authority_drift_detection = False

                response = client.get("/api/v1/admin/authority-drift")

                assert response.status_code == 503
                data = response.json()
                assert "authority_drift_detection=False" in data["reason"]
                assert data["action"].startswith("Set AUTHORITY_DRIFT_DETECTION=true")

                # Verify Lesson G cache headers
                assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"

        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_r2_flag_on_no_drift_response(self):
        """R2: When flag=ON and no drift, returns clean response."""
        from app.main import app
        from app.auth.dependencies import require_admin

        client = TestClient(app)

        # Override admin auth dependency
        app.dependency_overrides[require_admin] = lambda: {"email": "test@example.com", "role": "admin"}

        try:
            with patch("app.api.routes_admin.settings") as mock_settings:
                mock_settings.authority_drift_detection = True

                # Mock the drift check to return no drift
                with patch("app.services.authority_drift_service.check_authority_drift") as mock_check:
                    mock_check.return_value = {
                        "drift_detected": False,
                        "drift_count": 0,
                        "total_modules": 4,
                        "modules": {}
                    }

                    response = client.get("/api/v1/admin/authority-drift")

                    assert response.status_code == 200
                    data = response.json()
                    assert data["drift_detected"] is False
                    assert data["drift_count"] == 0

                    # Verify Lesson G cache headers
                    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"

        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_r2_flag_on_drift_detection_and_alerting(self):
        """R2: When flag=ON and drift detected, emits alert and returns drift report."""
        from app.main import app
        from app.auth.dependencies import require_admin

        client = TestClient(app)

        # Override admin auth dependency
        app.dependency_overrides[require_admin] = lambda: {"email": "test@example.com", "role": "admin"}

        try:
            with patch("app.api.routes_admin.settings") as mock_settings:
                mock_settings.authority_drift_detection = True

                # Mock drift detected
                mock_drift_report = {
                    "drift_detected": True,
                    "drift_type": "hash_mismatch",
                    "drift_count": 1,
                    "total_modules": 4,
                    "modules": {
                        "name_normalization.py": {
                            "status": "drift",
                            "expected_hash": "abc123",
                            "actual_hash": "def456"
                        }
                    }
                }

                with patch("app.services.authority_drift_service.check_authority_drift") as mock_check:
                    mock_check.return_value = mock_drift_report

                    with patch("app.services.authority_drift_service.emit_drift_alert") as mock_alert:

                        response = client.get("/api/v1/admin/authority-drift")

                        assert response.status_code == 200
                        data = response.json()
                        assert data["drift_detected"] is True
                        assert data["drift_count"] == 1

                        # Verify alert was emitted
                        mock_alert.assert_called_once()
                        alert_args = mock_alert.call_args
                        assert alert_args[0][0] == mock_drift_report  # drift_report
                        assert alert_args[0][1] == "test@example.com"  # operator email

        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_r2_no_store_headers_applied(self):
        """R2: Endpoint applies Lesson G no-store cache headers."""
        from app.main import app
        from app.auth.dependencies import require_admin

        client = TestClient(app)

        # Override admin auth dependency
        app.dependency_overrides[require_admin] = lambda: {"email": "test@example.com", "role": "admin"}

        try:
            with patch("app.api.routes_admin.settings") as mock_settings:
                mock_settings.authority_drift_detection = True

                with patch("app.services.authority_drift_service.check_authority_drift") as mock_check:
                    mock_check.return_value = {"drift_detected": False}

                    response = client.get("/api/v1/admin/authority-drift")

                    # Verify all Lesson G headers are present
                    expected_headers = {
                        "cache-control": "no-store, no-cache, must-revalidate, max-age=0",
                        "pragma": "no-cache",
                        "expires": "0"
                    }

                    for header, expected_value in expected_headers.items():
                        assert response.headers.get(header) == expected_value

        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_r3_config_flag_defaults_off(self):
        """R3: authority_drift_detection config flag defaults to False."""
        from app.core.config import Settings

        # Create fresh settings instance
        settings = Settings()

        # Verify default is False
        assert settings.authority_drift_detection is False

    def test_drift_service_handles_missing_manifest(self):
        """R2: Drift service handles missing pinned manifest gracefully."""
        from app.services.authority_drift_service import check_authority_drift

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.storage_root = Path("/nonexistent")

            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.return_value = False  # Simulate missing manifest

                result = check_authority_drift()

                assert result["drift_detected"] is True
                assert result["drift_type"] == "missing_manifest"
                assert "Pinned manifest not found" in result["error"]

    def test_drift_service_alert_emission(self):
        """Phase 4: Alert emission writes structured records to audit log."""
        from app.services.authority_drift_service import emit_drift_alert

        drift_report = {
            "drift_detected": True,
            "drift_type": "hash_mismatch",
            "drift_count": 1,
            "total_modules": 4,
            "errors": ["Hash mismatch: name_normalization.py"],
            "modules": {"name_normalization.py": {"status": "drift"}}
        }

        with patch("logging.getLogger") as mock_get_logger:
            # Mock both the audit logger and regular logger
            mock_audit_logger = mock_get_logger.return_value

            emit_drift_alert(drift_report, "operator@test.com")

            # Verify getLogger was called with "audit"
            mock_get_logger.assert_any_call("audit")

            # Verify audit log warning was called
            mock_audit_logger.warning.assert_called_once()

            # Verify log message format and arguments
            call_args = mock_audit_logger.warning.call_args
            log_template = call_args[0][0]
            log_args = call_args[0][1:]

            assert "AUTHORITY_DRIFT_ALERT" in log_template
            assert "severity=%s" in log_template
            assert "drift_type=%s" in log_template
            assert "modules_affected=%d" in log_template

            # Verify the actual values passed
            assert log_args[0] == "authority_drift_detected"  # alert_type
            assert log_args[1] == "HIGH"  # severity
            assert log_args[2] == "hash_mismatch"  # drift_type
            assert log_args[3] == 1  # modules_affected