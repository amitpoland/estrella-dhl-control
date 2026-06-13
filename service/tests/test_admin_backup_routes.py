"""
test_admin_backup_routes.py — Admin Backup Routes Tests

Tests admin authentication for backup endpoints.
"""
from fastapi.testclient import TestClient
from unittest.mock import patch


def test_backup_endpoints_require_admin_auth():
    """Backup endpoints return 401/403 without admin credentials."""
    from app.main import app

    client = TestClient(app)

    # Test endpoints without authentication
    response = client.post("/api/v1/admin/backup/run")
    assert response.status_code in [401, 403]

    response = client.get("/api/v1/admin/backup/list")
    assert response.status_code in [401, 403]

    response = client.post("/api/v1/admin/backup/validate", json={"backup_id": "test"})
    assert response.status_code in [401, 403]

    response = client.post("/api/v1/admin/backup/prune")
    assert response.status_code in [401, 403]


def test_backup_run_with_mock_auth():
    """Backup run endpoint works with mock admin authentication.

    FastAPI binds Depends(require_admin) at route-definition time, so
    mock.patch on the module attribute has no effect — dependency_overrides
    is the supported substitution mechanism.
    """
    from app.main import app
    from app.auth.dependencies import require_admin

    app.dependency_overrides[require_admin] = lambda: {"id": "test-admin", "role": "admin"}
    try:
        # run_backup is imported by name into routes_admin_backup, so patch it there.
        with patch("app.api.routes_admin_backup.run_backup") as mock_backup:
            mock_backup.return_value = {
                "backup_id": "2026-06-12-143022",
                "started_at": "2026-06-12T14:30:22+00:00",
                "finished_at": "2026-06-12T14:30:25+00:00",
                "summary": {
                    "total_files": 5,
                    "success_count": 5,
                    "total_size_bytes": 1024000
                }
            }

            client = TestClient(app)
            response = client.post("/api/v1/admin/backup/run")

            assert response.status_code == 200
            result = response.json()
            assert result["success"] is True
            assert result["backup_id"] == "2026-06-12-143022"
            assert "summary" in result
    finally:
        app.dependency_overrides.pop(require_admin, None)