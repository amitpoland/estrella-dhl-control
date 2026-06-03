"""
test_inbox_contract.py — Contract tests for GET /api/v1/inbox aggregator.

Sprint 2B.1: inbox aggregator (routes_inbox.py).
Design: docs/inbox/sprint-2b-design.md (72d3f4d).

Coverage:
  1. Aggregator returns merged, priority-sorted items from sources A + C.
  2. Admin caller receives source B (email queue) items.
  3a. Non-admin with NO session → ZERO email-queue items (if pz_session guard).
  3b. Non-admin WITH session → ZERO email-queue items (role gate exercises the mock).
  4. GET reads DHL state from cache only: static import-graph proof + dynamic _load_master proof.
  5. One source raises → 200 with per-source error marker; other sources intact.
  6. ?limit filter respected.
  7. ?priority filter respected.
  8. ?type filter respected.
  9. Route registered and requires auth in prod mode.
 10. Only pending_review proposals surface; approved/rejected/queued are excluded (drift guard).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

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


# ── Test 3a: no-session path — gate short-circuits before role check ──────────

def test_non_admin_no_session_receives_zero_email_queue_items(tmp_path):
    """No pz_session cookie → if pz_session: guard short-circuits → is_admin stays False.

    Case A: caller has an API key but no session cookie at all.
    The get_current_user_optional mock is intentionally dead here — proving the
    no-session path does NOT even reach the role check.
    """
    email_item = _make_email_queue_item("email-002a")

    with (
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[email_item]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            # No pz_session cookie — the if pz_session: guard in routes_inbox.py
            # short-circuits, is_admin stays False, email queue never queried.
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    email_items = [i for i in body["items"] if i["type"] == "email"]
    assert len(email_items) == 0, "no-session caller must not receive email queue items"
    eq_source = body["sources"]["email_queue"]
    assert eq_source["ok"] is True
    assert eq_source["count"] == 0
    assert eq_source.get("note") == "not_admin"


# ── Test 3b: non-admin WITH session — role check runs, gate holds ─────────────

def test_non_admin_with_session_receives_zero_email_queue_items(tmp_path):
    """pz_session present + role='operator' → get_current_user_optional executes →
    role != 'admin' → is_admin=False → email queue excluded.

    Case B: the mock IS exercised (cookie present → if pz_session: branch entered).
    This proves the role gate holds even when the session lookup succeeds.
    A regression that removed the role=='admin' check would be caught here.
    """
    non_admin_user = {"id": "u2", "role": "operator", "is_active": True, "is_approved": True}
    email_item = _make_email_queue_item("email-002b")

    with (
        patch("app.auth.dependencies.get_current_user_optional", return_value=non_admin_user),
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[email_item]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            # pz_session cookie present → if pz_session: branch is entered →
            # get_current_user_optional mock executes → returns non-admin user →
            # is_admin = bool(user and "operator" == "admin") = False
            r = c.get(
                "/api/v1/inbox",
                headers=_api_key_header(),
                cookies={"pz_session": "fake-operator-token"},
            )

    assert r.status_code == 200
    body = r.json()
    email_items = [i for i in body["items"] if i["type"] == "email"]
    assert len(email_items) == 0, "non-admin with session must not receive email queue items"
    eq_source = body["sources"]["email_queue"]
    assert eq_source["ok"] is True
    assert eq_source["count"] == 0
    assert eq_source.get("note") == "not_admin"


# ── Test 4: GET reads DHL state from cache — no scan triggered ───────────────

def test_get_reads_dhl_from_cache_not_scan(tmp_path):
    """GET /api/v1/inbox must read DHL state from email_intelligence_store cache only.

    Two-pronged proof:

    1. STATIC: routes_inbox.py source contains no reference to
       scan_for_dhl_customs_emails.  A module-level reference (import or inline call)
       would create a code path to the Zoho scan from the GET handler.  Its absence
       is the architectural guarantee.

    2. DYNAMIC: mock email_intelligence_store._load_master (the underlying cache read
       that list_recent() calls) with a canned record carrying recommended_next_action.
       The inbox must surface the DHL item from that record — proving the data comes
       from the cache read path, not a live scan.
    """
    import importlib.util
    from pathlib import Path as _Path

    # ── Static proof: dhl_email_monitor not imported in routes_inbox ─────────
    # Use AST-based import scan rather than a raw string search: the module
    # docstring deliberately mentions scan_for_dhl_customs_emails as a
    # constraint ("NEVER calls ..."), so a substring check would false-positive.
    # An actual import statement is the only way the scan could be reached.
    import ast as _ast
    spec = importlib.util.find_spec("app.api.routes_inbox")
    assert spec is not None, "routes_inbox module not found"
    inbox_source = _Path(spec.origin).read_text(encoding="utf-8")
    tree = _ast.parse(inbox_source)
    scan_imports = [
        node for node in _ast.walk(tree)
        if isinstance(node, (_ast.Import, _ast.ImportFrom))
        and (
            any(
                (alias.name or "").startswith("dhl_email_monitor")
                for alias in getattr(node, "names", [])
            )
            or (getattr(node, "module", "") or "").startswith("dhl_email_monitor")
            or (getattr(node, "module", "") or "") == "routes_dhl_clearance"
        )
    ]
    assert not scan_imports, (
        "routes_inbox.py must not import from dhl_email_monitor or routes_dhl_clearance — "
        "either would create a code path to the Zoho scan trigger from GET /api/v1/inbox"
    )

    # ── Dynamic proof: DHL item surfaces from _load_master cache, not a scan ──
    # Mock at _load_master (one level below list_recent) to prove the full data
    # flow: GET /inbox → _collect_dhl_cache_items → list_recent → _load_master.
    canned_master = {
        "rec-cache-proof": {
            "awb":                    "AWB-CACHE-PROOF",
            "matched":                1,
            "last_scanned_at":        "2026-06-03T07:00:00Z",
            "recommended_next_action": "Review matching documents",
            "linked_batches":         ["BATCH-PROOF"],
        }
    }

    with (
        patch(
            "app.services.email_intelligence_store._load_master",
            return_value=canned_master,
        ),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    dhl_ids = [i["id"] for i in body["items"] if i["type"] == "customs"]
    assert "dhl-AWB-CACHE-PROOF" in dhl_ids, (
        "DHL item must appear in inbox sourced from _load_master cache — "
        "proves the GET path reads from cache, not a live Zoho scan"
    )
    assert body["sources"]["dhl_cache"]["ok"] is True


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


# ── Test 10: only pending_review proposals surface — drift guard ──────────────

def test_only_pending_review_proposals_surface(tmp_path):
    """Inbox must surface ONLY pending_review proposals; approved/rejected/queued excluded.

    Drift guard for the proposal scan duplicated from routes_action_proposals._resolve_proposal
    (routes_action_proposals.py:1342).  If the status model evolves (e.g. 'pending_review'
    renamed, or a new actionable status added), this test will fail visibly rather than
    silently under-showing pending work in the inbox.

    Seeds one proposal per status and asserts the exact inclusion/exclusion boundary.
    """
    pending  = _make_proposal("p-pending",  status="pending_review")
    approved = _make_proposal("p-approved", status="approved")
    rejected = _make_proposal("p-rejected", status="rejected")
    queued   = _make_proposal("p-queued",   status="queued")
    sent     = _make_proposal("p-sent",     status="sent")

    _seed_batch_with_proposals(
        tmp_path, "BATCH-STATUS-DRIFT",
        [pending, approved, rejected, queued, sent],
    )

    with (
        patch("app.services.email_intelligence_store.list_recent", return_value=[]),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    items = r.json()["items"]
    proposal_ids = {i["id"] for i in items if i["type"] == "proposal"}

    # ── Inclusion: only pending_review appears ────────────────────────────────
    assert "proposal-p-pending" in proposal_ids, (
        "pending_review proposal must appear in inbox"
    )

    # ── Exclusion: all terminal/in-progress statuses absent ──────────────────
    assert "proposal-p-approved" not in proposal_ids, (
        "approved proposals must NOT appear (already actioned; queued via separate step)"
    )
    assert "proposal-p-rejected" not in proposal_ids, (
        "rejected proposals must NOT appear (terminal state)"
    )
    assert "proposal-p-queued" not in proposal_ids, (
        "queued proposals must NOT appear (already in email queue, surfaced via source B)"
    )
    assert "proposal-p-sent" not in proposal_ids, (
        "sent proposals must NOT appear (terminal state)"
    )
