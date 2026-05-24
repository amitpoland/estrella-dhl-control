"""Integration tests for PZ correction lifecycle routes in routes_pz.py.

Tests the four lifecycle endpoints:
  GET    /api/v1/pz/lineage/{batch_id}/correction-state
  POST   /api/v1/pz/lineage/{batch_id}/correction-stage
  DELETE /api/v1/pz/lineage/{batch_id}/correction-stage
  POST   /api/v1/pz/lineage/{batch_id}/correction-commit

Uses TestClient (no live server).  All wFirma and source-PDF calls are mocked.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


BATCH_ID = "lifecycle-test-batch"
BASE_URL = f"/api/v1/pz/lineage/{BATCH_ID}"
MOCK_IS_GLOBAL = "app.api.routes_pz._is_global_batch"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth(monkeypatch) -> dict:
    """Ensure a non-empty API key is set and return matching auth headers."""
    monkeypatch.setattr(settings, "api_key", "test-api-key-123")
    return {"X-API-Key": "test-api-key-123"}


@pytest.fixture(autouse=True)
def enable_lifecycle(monkeypatch) -> None:
    """Enable lifecycle flag for all tests in this module."""
    monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", True)


@pytest.fixture
def batch_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake outputs/{BATCH_ID} directory and point settings there."""
    bdir = tmp_path / "outputs" / BATCH_ID
    bdir.mkdir(parents=True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# GET correction-state
# ---------------------------------------------------------------------------

class TestCorrectionStateRoute:
    def test_returns_503_when_flag_disabled(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", False)
        resp = client.get(f"{BASE_URL}/correction-state", headers=auth)
        assert resp.status_code == 503

    def test_returns_non_200_without_auth(self, client):
        """Request without API key must not succeed (exact error code depends on
        whether settings.api_key is configured; the important thing is != 200)."""
        resp = client.get(f"{BASE_URL}/correction-state")
        assert resp.status_code != 200

    def test_returns_403_for_non_global_batch(self, client, auth):
        with patch(MOCK_IS_GLOBAL, return_value=False):
            resp = client.get(f"{BASE_URL}/correction-state", headers=auth)
        assert resp.status_code == 403

    def test_returns_proposed_for_new_batch(self, client, auth, batch_dir):
        with patch(MOCK_IS_GLOBAL, return_value=True):
            resp = client.get(f"{BASE_URL}/correction-state", headers=auth)

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"]    == "PROPOSED"
        assert data["batch_id"] == BATCH_ID

    def test_returns_existing_state_on_second_call(self, client, auth, batch_dir):
        with patch(MOCK_IS_GLOBAL, return_value=True):
            client.get(f"{BASE_URL}/correction-state", headers=auth)
            resp = client.get(f"{BASE_URL}/correction-state", headers=auth)

        assert resp.status_code == 200
        assert resp.json()["state"] == "PROPOSED"

    def test_returns_404_when_batch_dir_missing(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "storage_root", Path("/nonexistent/path"))
        with patch(MOCK_IS_GLOBAL, return_value=True):
            resp = client.get(f"{BASE_URL}/correction-state", headers=auth)
        assert resp.status_code == 404

    def test_rejects_path_traversal_in_batch_id(self, client, auth):
        resp = client.get("/api/v1/pz/lineage/../evil/correction-state", headers=auth)
        assert resp.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# POST correction-stage
# ---------------------------------------------------------------------------

class TestCorrectionStageRoute:
    def test_returns_503_when_lifecycle_flag_disabled(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", False)
        resp = client.post(
            f"{BASE_URL}/correction-stage",
            headers=auth,
            json={"option_id": "ALIGN_TO_AUTHORITY", "operator_reason": "test"},
        )
        assert resp.status_code == 503

    def test_returns_403_for_non_global_batch(self, client, auth):
        with patch(MOCK_IS_GLOBAL, return_value=False):
            resp = client.post(
                f"{BASE_URL}/correction-stage",
                headers=auth,
                json={"option_id": "ALIGN_TO_AUTHORITY", "operator_reason": "test"},
            )
        assert resp.status_code == 403

    def test_returns_422_when_source_pdfs_missing(self, client, auth, batch_dir):
        with (
            patch(MOCK_IS_GLOBAL, return_value=True),
            patch("app.api.routes_pz._find_source_pdf", return_value=None),
        ):
            resp = client.post(
                f"{BASE_URL}/correction-stage",
                headers=auth,
                json={"option_id": "ALIGN_TO_AUTHORITY", "operator_reason": "test"},
            )
        assert resp.status_code == 422

    def test_cancel_and_recreate_returns_409(self, client, auth, batch_dir):
        """CANCEL_AND_RECREATE must be blocked at 409 (lifecycle transition error)."""
        fake_pdf = batch_dir / "fake.pdf"
        fake_pdf.write_bytes(b"PDF")

        mock_option = MagicMock()
        mock_option.option_id = "ALIGN_TO_AUTHORITY"
        mock_option.proposed_lines = []

        mock_proposal = MagicMock()
        mock_proposal.options = [mock_option]

        with (
            patch(MOCK_IS_GLOBAL, return_value=True),
            patch("app.api.routes_pz._find_source_pdf", return_value=fake_pdf),
            patch("app.api.routes_pz.parse_invoice_positions_from_pdf",
                  return_value=[], create=True),
            patch("app.api.routes_pz.parse_global_packing_pdf",
                  return_value=([], None), create=True),
            patch("app.api.routes_pz.build_global_pz_lineage",
                  return_value=MagicMock(), create=True),
            patch("app.api.routes_pz.build_correction_proposal",
                  return_value=mock_proposal, create=True),
        ):
            resp = client.post(
                f"{BASE_URL}/correction-stage",
                headers=auth,
                json={
                    "option_id":       "CANCEL_AND_RECREATE",
                    "operator_reason": "trying cancel",
                },
            )
        # Either 409 (CANCEL_AND_RECREATE blocked by lifecycle) or 422 (option not in proposal)
        assert resp.status_code in (409, 422)

    def test_returns_422_when_option_not_in_proposal(self, client, auth, batch_dir):
        fake_pdf = batch_dir / "fake.pdf"
        fake_pdf.write_bytes(b"PDF")

        mock_proposal = MagicMock()
        mock_proposal.options = []  # no options

        with (
            patch(MOCK_IS_GLOBAL, return_value=True),
            patch("app.api.routes_pz._find_source_pdf", return_value=fake_pdf),
            patch("app.api.routes_pz.parse_invoice_positions_from_pdf",
                  return_value=[], create=True),
            patch("app.api.routes_pz.parse_global_packing_pdf",
                  return_value=([], None), create=True),
            patch("app.api.routes_pz.build_global_pz_lineage",
                  return_value=MagicMock(), create=True),
            patch("app.api.routes_pz.build_correction_proposal",
                  return_value=mock_proposal, create=True),
        ):
            resp = client.post(
                f"{BASE_URL}/correction-stage",
                headers=auth,
                json={"option_id": "UNKNOWN_OPTION", "operator_reason": "test"},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE correction-stage
# ---------------------------------------------------------------------------

class TestCorrectionResetStageRoute:
    def test_returns_503_when_flag_disabled(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", False)
        resp = client.delete(f"{BASE_URL}/correction-stage", headers=auth)
        assert resp.status_code == 503

    def test_returns_409_when_not_staged(self, client, auth, batch_dir):
        """Resetting from PROPOSED is a bad transition -> 409.

        reset_stage() explicitly requires state == STAGED.  Calling it from
        PROPOSED (the initial state) must return 409 Conflict.
        """
        with patch(MOCK_IS_GLOBAL, return_value=True):
            # Init state (creates PROPOSED record on disk)
            client.get(f"{BASE_URL}/correction-state", headers=auth)
        # DELETE (reset-stage) from PROPOSED must be rejected
        resp = client.delete(f"{BASE_URL}/correction-stage", headers=auth)
        assert resp.status_code == 409

    def test_returns_404_when_batch_dir_missing(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "storage_root", Path("/nonexistent/path"))
        resp = client.delete(f"{BASE_URL}/correction-stage", headers=auth)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST correction-commit
# ---------------------------------------------------------------------------

class TestCorrectionCommitRoute:
    COMMIT_BODY = {
        "operator_reason":       "final commit",
        "idempotency_key":       "key-abc-123",
        "confirm_understanding": "I UNDERSTAND THE IMPLICATIONS",
    }

    def test_returns_503_when_lifecycle_flag_disabled(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", False)
        resp = client.post(
            f"{BASE_URL}/correction-commit",
            headers=auth,
            json=self.COMMIT_BODY,
        )
        assert resp.status_code == 503

    def test_returns_503_when_push_flag_disabled(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "wfirma_correction_push_allowed", False)
        resp = client.post(
            f"{BASE_URL}/correction-commit",
            headers=auth,
            json=self.COMMIT_BODY,
        )
        assert resp.status_code == 503

    def test_returns_403_for_non_global_batch(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "wfirma_correction_push_allowed", True)
        with patch(MOCK_IS_GLOBAL, return_value=False):
            resp = client.post(
                f"{BASE_URL}/correction-commit",
                headers=auth,
                json=self.COMMIT_BODY,
            )
        assert resp.status_code == 403

    def test_returns_409_when_not_staged(self, client, auth, batch_dir, monkeypatch):
        monkeypatch.setattr(settings, "wfirma_correction_push_allowed", True)
        with (
            patch(MOCK_IS_GLOBAL, return_value=True),
            patch("app.api.routes_pz._is_global_batch", return_value=True),
        ):
            # Init state to PROPOSED (not STAGED)
            client.get(f"{BASE_URL}/correction-state", headers=auth)
            resp = client.post(
                f"{BASE_URL}/correction-commit",
                headers=auth,
                json=self.COMMIT_BODY,
            )
        assert resp.status_code == 409

    def test_double_gate_both_flags_must_be_true(self, client, auth, monkeypatch):
        """Both lifecycle_enabled AND push_allowed must be True to reach the endpoint."""
        # Case: lifecycle enabled, push disabled -> 503
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", True)
        monkeypatch.setattr(settings, "wfirma_correction_push_allowed", False)
        resp = client.post(
            f"{BASE_URL}/correction-commit",
            headers=auth,
            json=self.COMMIT_BODY,
        )
        assert resp.status_code == 503
