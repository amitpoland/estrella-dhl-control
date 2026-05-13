"""
test_proforma_pipeline_endpoint.py — GET /api/v1/proforma/pipeline/{batch_id}

Tests for the batch-level proforma pipeline aggregation endpoint introduced in
the "pipeline completion" task. The endpoint aggregates draft lifecycle states,
reservation draft cross-join, queue stats, and high-level flags.

Coverage:
- Empty state (no drafts)
- by_state counts with single draft
- by_state counts with multiple drafts across states
- needs_attention when post_failed draft exists
- has_posted / all_posted flags
- pipeline_stage derivation
- reservation_status cross-joined per-draft
- queue_stats (absent DB handled gracefully)
- error_hint present for post_failed draft
- posting metadata surfaced in draft entries
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_db as wfdb


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    from app.main import app
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


def _seed_draft(db_path: Path, *, batch_id="B1", client_name="ACME",
                currency="EUR", state=None, operator="test") -> "pildb.ProformaDraft":
    """Create a draft then optionally transition it to a target state."""
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db_path,
        batch_id=batch_id,
        client_name=client_name,
        currency=currency,
        lines=[
            {"product_code": "RNG-001", "design_no": "D001",
             "qty": 1, "unit_price": 100.0, "currency": currency},
        ],
        operator=operator,
    )
    if state == "approved":
        d = pildb.approve_draft(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
        )
    elif state == "cancelled":
        d = pildb.cancel_draft(db_path, d.id, operator, d.updated_at,
                               reason="test cancellation")
    elif state == "post_failed":
        # approve → posting → post_failed
        d = pildb.approve_draft(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
        )
        d = pildb.start_post(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.POST_CONFIRM_TOKEN,
        )
        d = pildb.mark_post_failed(
            db_path, d.id,
            error="wFirma connection timeout",
            operator=operator,
        )
    elif state == "posting":
        # approve → posting (left in-flight — simulates active wFirma write)
        d = pildb.approve_draft(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
        )
        d = pildb.start_post(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.POST_CONFIRM_TOKEN,
        )
    elif state == "posted":
        # approve → posting → posted
        d = pildb.approve_draft(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
        )
        d = pildb.start_post(
            db_path, d.id, operator, d.updated_at,
            confirm_token=pildb.POST_CONFIRM_TOKEN,
        )
        d = pildb.mark_post_succeeded(
            db_path, d.id,
            wfirma_proforma_id="WF-123",
            wfirma_proforma_fullnumber="PN/001/2026",
            operator=operator,
        )
    return d


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPipelineEmpty:
    """No drafts for the batch."""

    def test_returns_ok_with_empty_drafts(self, client):
        r = client.get("/api/v1/proforma/pipeline/BATCH-NONE",
                       headers=_auth_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["batch_id"] == "BATCH-NONE"
        assert body["client_count"] == 0
        assert body["drafts"] == []
        assert body["pipeline_stage"] == "none"
        assert body["needs_attention"] is False
        assert body["has_posted"] is False
        assert body["all_posted"] is False

    def test_by_state_empty(self, client):
        r = client.get("/api/v1/proforma/pipeline/BATCH-NONE",
                       headers=_auth_headers())
        assert r.json()["by_state"] == {}

    def test_queue_stats_empty(self, client):
        r = client.get("/api/v1/proforma/pipeline/BATCH-NONE",
                       headers=_auth_headers())
        assert r.json()["queue_stats"] == {}


class TestPipelineSingleDraft:
    """Single draft in various states."""

    def test_draft_state_count(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B2", client_name="ACME", state=None)
        r = client.get("/api/v1/proforma/pipeline/B2",
                       headers=_auth_headers())
        body = r.json()
        assert body["client_count"] == 1
        assert body["by_state"].get("draft", 0) == 1
        assert body["pipeline_stage"] == "drafting"
        assert body["has_draft"] is True

    def test_approved_state(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B3", client_name="ACME", state="approved")
        r = client.get("/api/v1/proforma/pipeline/B3",
                       headers=_auth_headers())
        body = r.json()
        assert body["by_state"].get("approved", 0) == 1
        assert body["pipeline_stage"] == "approved"
        assert body["has_approved"] is True
        assert body["needs_attention"] is False

    def test_posted_state(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B4", client_name="ACME", state="posted")
        r = client.get("/api/v1/proforma/pipeline/B4",
                       headers=_auth_headers())
        body = r.json()
        assert body["by_state"].get("posted", 0) == 1
        assert body["has_posted"] is True
        assert body["all_posted"] is True
        assert body["pipeline_stage"] == "all_posted"

    def test_post_failed_needs_attention(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B5", client_name="ACME",
                    state="post_failed")
        r = client.get("/api/v1/proforma/pipeline/B5",
                       headers=_auth_headers())
        body = r.json()
        assert body["by_state"].get("post_failed", 0) == 1
        assert body["needs_attention"] is True
        assert body["pipeline_stage"] == "post_failed"

    def test_posting_state_needs_attention(self, client, db_path, monkeypatch):
        """A draft stuck in 'posting' state must raise needs_attention.

        'posting' represents an in-flight wFirma write.  If it never
        transitions to 'posted' or 'post_failed' the batch is stuck and
        the operator needs to investigate.  The endpoint must surface this
        via needs_attention=True so the attention bucket on the dashboard
        lights up even before a post_failed is recorded.
        """
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B5b", client_name="ACME",
                    state="posting")
        r = client.get("/api/v1/proforma/pipeline/B5b",
                       headers=_auth_headers())
        body = r.json()
        assert body["by_state"].get("posting", 0) == 1
        assert body["needs_attention"] is True, (
            "A draft in 'posting' state must set needs_attention=True — "
            "it represents a stuck in-flight wFirma write"
        )

    def test_error_hint_in_draft_entry(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B6", client_name="ACME",
                    state="post_failed")
        r = client.get("/api/v1/proforma/pipeline/B6",
                       headers=_auth_headers())
        drafts = r.json()["drafts"]
        assert len(drafts) == 1
        # error_hint should contain the seeded error text
        assert "wFirma connection timeout" in (drafts[0].get("error_hint") or "")

    def test_posting_metadata_present(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B7", client_name="ACME",
                    state="posted")
        r = client.get("/api/v1/proforma/pipeline/B7",
                       headers=_auth_headers())
        d = r.json()["drafts"][0]
        # posted_by + posted_at should be present after mark_post_succeeded
        assert d.get("posted_by") == "test"
        assert d.get("posted_at") is not None


class TestPipelineMultipleDrafts:
    """Multiple clients in the same batch with different states."""

    def test_partial_posted(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B8", client_name="ACME",  state="posted")
        _seed_draft(db_path, batch_id="B8", client_name="GLOBAL", state="approved")
        r = client.get("/api/v1/proforma/pipeline/B8",
                       headers=_auth_headers())
        body = r.json()
        assert body["client_count"] == 2
        assert body["has_posted"] is True
        assert body["all_posted"] is False
        assert body["pipeline_stage"] == "partial_posted"

    def test_all_posted(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B9", client_name="ACME",  state="posted")
        _seed_draft(db_path, batch_id="B9", client_name="GLOBAL", state="posted")
        r = client.get("/api/v1/proforma/pipeline/B9",
                       headers=_auth_headers())
        body = r.json()
        assert body["all_posted"] is True
        assert body["pipeline_stage"] == "all_posted"

    def test_post_failed_takes_priority_over_posted(self, client, db_path,
                                                    monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B10", client_name="ACME",  state="posted")
        _seed_draft(db_path, batch_id="B10", client_name="GLOBAL", state="post_failed")
        r = client.get("/api/v1/proforma/pipeline/B10",
                       headers=_auth_headers())
        body = r.json()
        assert body["needs_attention"] is True
        # post_failed takes top-priority in pipeline_stage
        assert body["pipeline_stage"] == "post_failed"

    def test_by_state_counts_correct(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B11", client_name="A", state=None)       # draft
        _seed_draft(db_path, batch_id="B11", client_name="B", state="approved")
        _seed_draft(db_path, batch_id="B11", client_name="C", state="posted")
        _seed_draft(db_path, batch_id="B11", client_name="D", state="cancelled")
        r = client.get("/api/v1/proforma/pipeline/B11",
                       headers=_auth_headers())
        by_state = r.json()["by_state"]
        assert by_state.get("draft", 0)     == 1
        assert by_state.get("approved", 0)  == 1
        assert by_state.get("posted", 0)    == 1
        assert by_state.get("cancelled", 0) == 1


class TestPipelineReservationCrossJoin:
    """Reservation draft status cross-joined when wfirma_db is initialised."""

    def test_reservation_null_when_no_res_draft(self, client, db_path, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes_proforma._proforma_db_path", lambda: db_path
        )
        _seed_draft(db_path, batch_id="B12", client_name="ACME")
        r = client.get("/api/v1/proforma/pipeline/B12",
                       headers=_auth_headers())
        d = r.json()["drafts"][0]
        # No reservation draft seeded — all fields should be None
        assert d["reservation_status"]    is None
        assert d["wfirma_reservation_id"] is None
        assert d["reservation_ready"]     is False


class TestPipelineAuth:
    """Auth guard is enforced when an API key is configured."""

    def test_requires_api_key_when_configured(self, tmp_path, monkeypatch):
        """When settings.api_key is set, missing key → 401."""
        monkeypatch.setattr(settings, "api_key", "secret-key-for-test")
        monkeypatch.setattr(settings, "storage_root", tmp_path)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/proforma/pipeline/BATCH-X")
            assert r.status_code == 401

    def test_correct_key_succeeds(self, tmp_path, monkeypatch):
        """Correct key → 200 (even for a batch with no drafts)."""
        monkeypatch.setattr(settings, "api_key", "secret-key-for-test")
        monkeypatch.setattr(settings, "storage_root", tmp_path)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/proforma/pipeline/BATCH-X",
                      headers={"X-API-KEY": "secret-key-for-test"})
            assert r.status_code == 200
