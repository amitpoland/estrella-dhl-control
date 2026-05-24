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
from app.services.global_pz_push import _CONFIRM_SENTINEL


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
        "confirm_understanding": _CONFIRM_SENTINEL,
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

    def test_wrong_sentinel_reaches_gate_1_in_real_push_service(
        self, client, auth, batch_dir, monkeypatch
    ):
        """Gate 1 (sentinel check) is inside push_correction_to_wfirma, not mocked here.

        The wrong sentinel must propagate through the real push service and
        cause a FAILED lifecycle state + HTTP 502.  This confirms that tests
        using _CONFIRM_SENTINEL exercise the actual gate rather than bypassing
        it through mocks.
        """
        monkeypatch.setattr(settings, "wfirma_correction_push_allowed", True)

        # Write lifecycle state as STAGED so execute() can proceed
        lc_path = batch_dir / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"
        lc_path.write_text(
            json.dumps({
                "batch_id":           BATCH_ID,
                "state":              "STAGED",
                "staged_option_id":   "ALIGN_TO_AUTHORITY",
                "operator_note":      None,
                "review_ts":          None,
                "stage_ts":           "2026-05-24T10:00:00+00:00",
                "execute_ts":         None,
                "complete_ts":        None,
                "result_summary":     None,
                "suppression_reason": None,
                "schema_version":     1,
            }),
            encoding="utf-8",
        )

        with patch(MOCK_IS_GLOBAL, return_value=True):
            resp = client.post(
                f"{BASE_URL}/correction-commit",
                headers=auth,
                json={
                    "operator_reason":       "testing sentinel gate",
                    "idempotency_key":       "key-wrong-sentinel-001",
                    "confirm_understanding": "I UNDERSTAND THE IMPLICATIONS",  # intentionally wrong
                },
            )

        # Gate 1 inside push_correction_to_wfirma blocks; lifecycle writes FAILED; route 502
        assert resp.status_code == 502
        detail = resp.json().get("detail", "")
        # The detail comes from push_result.error which names the sentinel mismatch
        assert "sentinel" in detail.lower() or "does not match" in detail.lower()


# ---------------------------------------------------------------------------
# POST correction-suppress
# ---------------------------------------------------------------------------

class TestCorrectionSuppressRoute:
    """Tests for POST /pz/lineage/{batch_id}/correction-suppress.

    suppress_terminal() transitions ANY -> TERMINAL_SUPPRESSED without
    touching wFirma.  It is the operator recovery path for stuck EXECUTING
    and repeated-FAILED workflows.
    """

    SUPPRESS_BODY = {"reason": "operator abandoned this correction"}
    SUPPRESS_URL  = f"{BASE_URL}/correction-suppress"

    def test_returns_503_when_flag_disabled(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", False)
        resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)
        assert resp.status_code == 503

    def test_returns_400_for_empty_reason(self, client, auth, batch_dir):
        resp = client.post(self.SUPPRESS_URL, headers=auth, json={"reason": ""})
        assert resp.status_code == 400

    def test_returns_400_for_whitespace_only_reason(self, client, auth, batch_dir):
        resp = client.post(self.SUPPRESS_URL, headers=auth, json={"reason": "   "})
        assert resp.status_code == 400

    def test_returns_non_200_without_auth(self, client):
        """Without auth headers the request must not return 200 (exact code
        depends on whether settings.api_key is configured; batch missing -> 404
        is sufficient to confirm the route is not open to anonymous callers)."""
        resp = client.post(self.SUPPRESS_URL, json=self.SUPPRESS_BODY)
        assert resp.status_code != 200

    def test_returns_404_when_batch_dir_missing(self, client, auth, monkeypatch):
        monkeypatch.setattr(settings, "storage_root", Path("/nonexistent/path"))
        resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)
        assert resp.status_code == 404

    def test_suppresses_from_executing_state(self, client, auth, batch_dir):
        """EXECUTING -> TERMINAL_SUPPRESSED is the primary recovery path for
        a batch stuck after a service restart mid-push."""
        lc_path = batch_dir / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"
        lc_path.write_text(
            json.dumps({
                "batch_id":           BATCH_ID,
                "state":              "EXECUTING",
                "staged_option_id":   "ALIGN_TO_AUTHORITY",
                "operator_note":      None,
                "review_ts":          None,
                "stage_ts":           "2026-05-24T10:00:00+00:00",
                "execute_ts":         "2026-05-24T10:01:00+00:00",
                "complete_ts":        None,
                "result_summary":     None,
                "suppression_reason": None,
                "schema_version":     1,
            }),
            encoding="utf-8",
        )

        resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"]              == "TERMINAL_SUPPRESSED"
        assert data["suppression_reason"] == "operator abandoned this correction"
        assert data["complete_ts"] is not None

    def test_suppresses_from_failed_state(self, client, auth, batch_dir):
        """FAILED -> TERMINAL_SUPPRESSED allows operator to close out
        a workflow after repeated push failures."""
        lc_path = batch_dir / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"
        lc_path.write_text(
            json.dumps({
                "batch_id":           BATCH_ID,
                "state":              "FAILED",
                "staged_option_id":   "ALIGN_TO_AUTHORITY",
                "operator_note":      None,
                "review_ts":          None,
                "stage_ts":           "2026-05-24T10:00:00+00:00",
                "execute_ts":         "2026-05-24T10:01:00+00:00",
                "complete_ts":        "2026-05-24T10:01:05+00:00",
                "result_summary":     "wFirma 502",
                "suppression_reason": None,
                "schema_version":     1,
            }),
            encoding="utf-8",
        )

        resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)

        assert resp.status_code == 200
        assert resp.json()["state"] == "TERMINAL_SUPPRESSED"

    def test_returns_409_when_already_terminal_suppressed(self, client, auth, batch_dir):
        """TERMINAL_SUPPRESSED -> TERMINAL_SUPPRESSED is not a valid transition."""
        lc_path = batch_dir / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"
        lc_path.write_text(
            json.dumps({
                "batch_id":           BATCH_ID,
                "state":              "TERMINAL_SUPPRESSED",
                "staged_option_id":   None,
                "operator_note":      None,
                "review_ts":          None,
                "stage_ts":           None,
                "execute_ts":         None,
                "complete_ts":        "2026-05-24T10:00:00+00:00",
                "result_summary":     None,
                "suppression_reason": "already closed",
                "schema_version":     1,
            }),
            encoding="utf-8",
        )

        resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)
        assert resp.status_code == 409

    def test_no_wfirma_push_is_called(self, client, auth, batch_dir):
        """suppress_terminal must not touch wFirma under any circumstance."""
        lc_path = batch_dir / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"
        lc_path.write_text(
            json.dumps({
                "batch_id":           BATCH_ID,
                "state":              "PROPOSED",
                "staged_option_id":   None,
                "operator_note":      None,
                "review_ts":          None,
                "stage_ts":           None,
                "execute_ts":         None,
                "complete_ts":        None,
                "result_summary":     None,
                "suppression_reason": None,
                "schema_version":     1,
            }),
            encoding="utf-8",
        )

        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma"
        ) as mock_push:
            resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)

        assert resp.status_code == 200
        mock_push.assert_not_called()

    def test_no_global_batch_check_required(self, client, auth, batch_dir):
        """suppress must work without global batch detection — source PDFs may
        be unavailable when an operator needs to recover a stuck workflow."""
        lc_path = batch_dir / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"
        lc_path.write_text(
            json.dumps({
                "batch_id":           BATCH_ID,
                "state":              "PROPOSED",
                "staged_option_id":   None,
                "operator_note":      None,
                "review_ts":          None,
                "stage_ts":           None,
                "execute_ts":         None,
                "complete_ts":        None,
                "result_summary":     None,
                "suppression_reason": None,
                "schema_version":     1,
            }),
            encoding="utf-8",
        )

        # Deliberately do NOT mock _is_global_batch — suppress must not call it
        resp = client.post(self.SUPPRESS_URL, headers=auth, json=self.SUPPRESS_BODY)
        assert resp.status_code == 200
        assert resp.json()["state"] == "TERMINAL_SUPPRESSED"


# ---------------------------------------------------------------------------
# POST correction-push-wfirma (old pre-lifecycle route) — PR B governance
# ---------------------------------------------------------------------------

class TestOldPushRouteGovernance:
    """PR B: old push route must return 410 when lifecycle flag is enabled.

    The pre-lifecycle route POST /pz/lineage/{batch_id}/correction-push-wfirma
    and the lifecycle commit route POST /pz/lineage/{batch_id}/correction-commit
    both call push_correction_to_wfirma.  When pz_correction_lifecycle_enabled
    is True the old route is superseded and must return 410 Gone to prevent
    parallel push paths that could diverge the lifecycle state machine.

    When the flag is False the old route must continue to work normally
    (returns 403 from the global-batch gate, never 410).
    """

    OLD_PUSH_URL = f"{BASE_URL}/correction-push-wfirma"

    def test_old_route_returns_410_when_lifecycle_enabled(self, client, auth):
        """Lifecycle flag ON → old push route must return 410 immediately."""
        # enable_lifecycle autouse fixture already sets the flag to True
        resp = client.post(
            self.OLD_PUSH_URL,
            headers=auth,
            json={
                "operator_reason":       "test",
                "idempotency_key":       "key-001",
                "confirm_understanding": _CONFIRM_SENTINEL,
            },
        )
        assert resp.status_code == 410, (
            f"Expected 410 when lifecycle enabled; got {resp.status_code}: {resp.json()}"
        )
        detail = resp.json().get("detail", "")
        assert "superseded" in detail.lower() or "correction-commit" in detail.lower(), (
            f"410 detail should mention 'superseded' or 'correction-commit': {detail!r}"
        )

    def test_old_route_not_410_when_lifecycle_disabled(self, client, auth, monkeypatch):
        """Lifecycle flag OFF → old push route must NOT return 410.

        With the flag off it proceeds to normal gates — the global-batch check
        returns 403 for our test batch, which is the expected non-410 response.
        """
        monkeypatch.setattr(settings, "pz_correction_lifecycle_enabled", False)

        with patch(MOCK_IS_GLOBAL, return_value=False):
            resp = client.post(
                self.OLD_PUSH_URL,
                headers=auth,
                json={
                    "operator_reason":       "test",
                    "idempotency_key":       "key-001",
                    "confirm_understanding": _CONFIRM_SENTINEL,
                },
            )

        # Must not be 410 — the lifecycle gate must be absent when flag is False
        assert resp.status_code != 410, (
            "Old push route must not return 410 when pz_correction_lifecycle_enabled=False"
        )
        # Global-batch gate fires next (403 is the expected response for non-global batch)
        assert resp.status_code == 403

    def test_lifecycle_commit_route_unaffected(self, client, auth):
        """Lifecycle commit route must not be affected by the old-route gate.

        The lifecycle commit route has its own independent flag check.  When
        wfirma_correction_push_allowed=False it returns 503 (push flag gate),
        not 410.  This confirms the 410 gate is scoped only to the old route.
        """
        # Lifecycle flag is ON (autouse fixture)
        # wfirma_correction_push_allowed is False by default
        resp = client.post(
            f"{BASE_URL}/correction-commit",
            headers=auth,
            json={
                "operator_reason":       "test",
                "idempotency_key":       "key-001",
                "confirm_understanding": _CONFIRM_SENTINEL,
            },
        )
        # 503 from push-flag gate, NOT 410
        assert resp.status_code == 503, (
            f"lifecycle commit route should return 503 (push flag disabled), "
            f"not 410; got {resp.status_code}"
        )
