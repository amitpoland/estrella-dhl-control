"""
test_inbox_contract.py — Contract tests for GET /api/v1/inbox aggregator.

Sprint 2B.1: inbox aggregator (routes_inbox.py).
Design: docs/inbox/sprint-2b-design.md (72d3f4d).

Coverage:
  1. Aggregator returns merged, priority-sorted items from sources A + C.
  2. Admin caller receives source B (email queue) items.
  3. Non-admin caller receives ZERO source B items (privilege-escalation gate).
  4. GET fires no Zoho scan — scan_for_dhl_customs_emails never called.
  5. One source raises → 200 with per-source error marker; other sources intact.
  6. ?limit filter respected.
  7. ?priority filter respected.
  8. ?type filter respected.
  9. Route registered and requires auth in prod mode.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


# ── helpers ──────────────────────────────────────────────────────────────────

def _api_key_header() -> Dict[str, str]:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _make_proposal(
    proposal_id: str,
    ptype: str = "dhl_proactive_dispatch",
    batch_id: str = "BATCH-001",
    status: str = "pending_review",
) -> Dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "type":        ptype,
        "batch_id":    batch_id,
        "status":      status,
        "reason":      f"Test reason for {proposal_id}",
        "created_at":  "2026-06-03T10:00:00Z",
    }


def _make_email_queue_item(eid: str, batch_id: str = "BATCH-001") -> Dict[str, Any]:
    return {
        "id":         eid,
        "status":     "pending",
        "subject":    f"Test email {eid}",
        "to":         "agency@test.pl",
        "batch_id":   batch_id,
        "queued_at":  "2026-06-03T09:00:00Z",
    }


def _make_dhl_cache_record(awb: str) -> Dict[str, Any]:
    return {
        "awb":                    awb,
        "matched":                2,
        "last_scanned_at":        "2026-06-03T08:00:00Z",
        "recommended_next_action":"Verify AWB against SAD",
        "linked_batches":         ["BATCH-001"],
    }


@pytest.fixture()
def client(tmp_path) -> TestClient:
    with patch.object(settings, "storage_root", tmp_path):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_batch_with_proposals(
    tmp_path: Path,
    batch_id: str,
    proposals: list[Dict[str, Any]],
) -> None:
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "action_proposals": proposals}
    (batch_dir / "audit.json").write_text(
        json.dumps(audit), encoding="utf-8"
    )


# ── Test 1: merged + priority-sorted items ───────────────────────────────────

def test_aggregator_returns_merged_priority_sorted_items(client, tmp_path):
    """Inbox merges A + C and sorts urgent before high before normal."""
    # Source A: two proposals with different priorities
    urgent_prop  = _make_proposal("pid-urgent",  ptype="dhl_proactive_dispatch")
    normal_prop  = _make_proposal("pid-normal",  ptype="agency_package")
    _seed_batch_with_proposals(tmp_path, "BATCH-A", [urgent_prop, normal_prop])

    # Source C: one DHL cache item
    dhl_record = _make_dhl_cache_record("AWB-9999")

    with (
        patch("app.services.email_intelligence_store.list_recent", return_value=[dhl_record]),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        r = client.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    items = body["items"]

    ids = [i["id"] for i in items]
    assert "proposal-pid-urgent" in ids
    assert "proposal-pid-normal" in ids
    assert "dhl-AWB-9999" in ids

    # urgent (priority 0) must come before normal (priority 2)
    urgent_idx = ids.index("proposal-pid-urgent")
    normal_idx = ids.index("proposal-pid-normal")
    assert urgent_idx < normal_idx, "urgent proposal must sort before normal"

    # sources reported
    assert body["sources"]["proposals"]["ok"] is True
    assert body["sources"]["dhl_cache"]["ok"]  is True


# ── Test 2: admin sees email queue items ──────────────────────────────────────

def test_admin_caller_receives_email_queue_items(tmp_path):
    """Admin caller (role='admin') gets email queue items in the inbox.

    pz_session cookie must be present; get_current_user_optional is then called
    to derive the role. Without the cookie, the admin check short-circuits to False.
    """
    admin_user = {"id": "u1", "role": "admin", "is_active": True, "is_approved": True}
    email_item = _make_email_queue_item("email-001")

    with (
        patch("app.auth.dependencies.get_current_user_optional", return_value=admin_user),
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[email_item]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            # Pass a fake pz_session cookie so the admin check runs (value doesn't
            # matter — get_current_user_optional is mocked to return admin_user).
            r = c.get(
                "/api/v1/inbox",
                headers=_api_key_header(),
                cookies={"pz_session": "fake-admin-token"},
            )

    assert r.status_code == 200
    body = r.json()
    email_ids = [i["id"] for i in body["items"] if i["type"] == "email"]
    assert "email-email-001" in email_ids, "admin must receive email queue items"
    assert body["sources"]["email_queue"]["ok"] is True
    assert body["sources"]["email_queue"]["count"] >= 1


# ── Test 3: non-admin receives ZERO email queue items (privilege gate) ────────

def test_non_admin_receives_zero_email_queue_items(tmp_path):
    """Non-admin caller must receive ZERO email queue items — privilege-escalation gate."""
    non_admin_user = {"id": "u2", "role": "operator", "is_active": True, "is_approved": True}
    email_item = _make_email_queue_item("email-002")

    with (
        patch("app.auth.dependencies.get_current_user_optional", return_value=non_admin_user),
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[email_item]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    email_items = [i for i in body["items"] if i["type"] == "email"]
    assert len(email_items) == 0, "non-admin must receive ZERO email queue items"
    # source marker shows not_admin, not an error
    eq_source = body["sources"]["email_queue"]
    assert eq_source["ok"] is True
    assert eq_source["count"] == 0
    assert eq_source.get("note") == "not_admin"


# ── Test 4: GET fires no Zoho scan ────────────────────────────────────────────

def test_get_fires_no_zoho_scan(client, tmp_path):
    """GET /api/v1/inbox must never call scan_for_dhl_customs_emails."""
    scan_mock = MagicMock()

    with (
        patch(
            "app.services.email_intelligence_store.list_recent",
            return_value=[],
        ),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
        # Assert the scan function is never called via this import path
        patch("dhl_email_monitor.scan_for_dhl_customs_emails", scan_mock, create=True),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        r = client.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    scan_mock.assert_not_called()


# ── Test 5: one source dead → 200 with per-source error marker ────────────────

def test_one_source_dead_returns_200_with_error_marker(tmp_path):
    """If proposals source raises, inbox returns 200 with proposals.ok=false; others intact."""
    dhl_record = _make_dhl_cache_record("AWB-DEAD-TEST")

    with (
        patch(
            "app.api.routes_inbox._collect_pending_proposals",
            side_effect=RuntimeError("disk error"),
        ),
        patch("app.services.email_intelligence_store.list_recent", return_value=[dhl_record]),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True

    # proposals source failed
    assert body["sources"]["proposals"]["ok"] is False
    assert "disk error" in body["sources"]["proposals"]["error"]

    # DHL cache source intact
    assert body["sources"]["dhl_cache"]["ok"] is True
    assert any(i["id"] == "dhl-AWB-DEAD-TEST" for i in body["items"])


# ── Test 6: limit filter ──────────────────────────────────────────────────────

def test_limit_filter(tmp_path):
    """?limit=2 returns at most 2 items."""
    proposals = [
        _make_proposal(f"pid-{i}", ptype="dhl_proactive_dispatch") for i in range(5)
    ]
    _seed_batch_with_proposals(tmp_path, "BATCH-LIMIT", proposals)

    with (
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox?limit=2", headers=_api_key_header())

    assert r.status_code == 200
    assert len(r.json()["items"]) <= 2


# ── Test 7: priority filter ───────────────────────────────────────────────────

def test_priority_filter(tmp_path):
    """?priority=urgent returns only urgent items."""
    urgent = _make_proposal("pid-urg", ptype="dhl_proactive_dispatch")
    normal = _make_proposal("pid-nor", ptype="agency_package")
    _seed_batch_with_proposals(tmp_path, "BATCH-PRI", [urgent, normal])

    with (
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox?priority=urgent", headers=_api_key_header())

    body = r.json()
    assert all(i["priority"] == "urgent" for i in body["items"])
    assert any(i["id"] == "proposal-pid-urg" for i in body["items"])
    assert all(i["id"] != "proposal-pid-nor" for i in body["items"])


# ── Test 8: type filter ───────────────────────────────────────────────────────

def test_type_filter(tmp_path):
    """?type=proposal returns only proposal items (no customs items)."""
    proposal = _make_proposal("pid-type-test")
    _seed_batch_with_proposals(tmp_path, "BATCH-TYPE", [proposal])
    dhl_record = _make_dhl_cache_record("AWB-TYPE-TEST")

    with (
        patch("app.services.email_intelligence_store.list_recent", return_value=[dhl_record]),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox?type=proposal", headers=_api_key_header())

    items = r.json()["items"]
    assert all(i["type"] == "proposal" for i in items)
    assert all(i["type"] != "customs"  for i in items)


# ── Test 9: auth required in prod mode ───────────────────────────────────────

def test_requires_auth_in_prod(tmp_path):
    """GET /api/v1/inbox requires auth in prod mode (api_key set)."""
    with (
        patch.object(settings, "api_key", "prod-secret-key"),
        patch.object(settings, "environment", "prod"),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/v1/inbox")   # no auth header

    assert r.status_code in (401, 403)
