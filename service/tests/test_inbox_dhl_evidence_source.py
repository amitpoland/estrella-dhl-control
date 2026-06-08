"""
test_inbox_dhl_evidence_source.py — Contract tests for DHL evidence store → inbox wiring.

Sprint 1: Inbox Authority Completion — Fix Source C.

Proves:
  T1. Actionable AWB (dhl_request_received, reply not sent) appears in list_actionable_awbs()
  T2. Fully-resolved AWB does NOT appear in list_actionable_awbs()
  T3. Priority ladder: urgent > high > normal (derived from summary flags)
  T4. Malformed JSON in by_awb/ is skipped safely
  T5. Missing by_awb/ directory returns []
  T6. GET /api/v1/inbox returns type="customs" items from evidence store (end-to-end)
  T7. No scan trigger: routes_inbox imports neither dhl_email_monitor nor routes_dhl_clearance
  T8. email_intelligence_store.list_recent is NOT called from inbox path
  T9. Envelope shape: every DHL inbox item has required fields
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.email_evidence_store import (
    _derive_next_action,
    list_actionable_awbs,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_awb_file(by_awb_dir: Path, awb: str, summary: Dict[str, bool],
                   batch_ids: list = None, messages: int = 3,
                   last_message_at: str = "2026-06-05T10:00:00") -> None:
    """Write a minimal AWB evidence file."""
    threads = [{"messages": [{"event_type": "dhl_request"}] * messages}]
    doc = {
        "awb": awb,
        "batch_ids": batch_ids or [],
        "threads": threads,
        "summary": summary,
        "last_message_at": last_message_at,
        "last_scan_at": last_message_at,
    }
    by_awb_dir.mkdir(parents=True, exist_ok=True)
    (by_awb_dir / f"{awb}.json").write_text(json.dumps(doc), encoding="utf-8")


def _api_key_header() -> Dict[str, str]:
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── T1: Actionable AWB appears ────────────────────────────────────────────────

def test_actionable_dhl_request_appears(tmp_path):
    """AWB with dhl_request_received=True, reply not sent → appears as actionable."""
    by_awb = tmp_path / "email_evidence" / "by_awb"
    _make_awb_file(by_awb, "4789974092", {
        "dhl_request_received": True,
        "our_dhl_reply_sent": False,
        "our_dhl_reply_queued": False,
        "dhl_documents_received": False,
        "agency_forward_sent": False,
        "agency_forward_queued": False,
        "agency_sad_received": False,
        "dhl_invoice_received": False,
        "agency_invoice_received": False,
    }, batch_ids=["GJ-2026-001"])

    with patch.object(settings, "storage_root", tmp_path):
        results = list_actionable_awbs(limit=30)

    assert len(results) == 1
    r = results[0]
    assert r["awb"] == "4789974092"
    assert r["priority"] == "urgent"
    assert "reply needed" in r["next_action"]
    assert r["batch_ids"] == ["GJ-2026-001"]
    assert r["message_count"] == 3


# ── T2: Resolved AWB does NOT appear ─────────────────────────────────────────

def test_resolved_awb_not_surfaced(tmp_path):
    """AWB with all actions resolved (reply sent, docs forwarded) → not in results."""
    by_awb = tmp_path / "email_evidence" / "by_awb"
    _make_awb_file(by_awb, "RESOLVED-001", {
        "dhl_request_received": True,
        "our_dhl_reply_sent": True,
        "our_dhl_reply_queued": False,
        "dhl_documents_received": True,
        "agency_forward_sent": True,
        "agency_forward_queued": False,
        "agency_sad_received": False,
        "dhl_invoice_received": False,
        "agency_invoice_received": False,
    })

    with patch.object(settings, "storage_root", tmp_path):
        results = list_actionable_awbs(limit=30)

    assert len(results) == 0, "Fully resolved AWB must not appear in actionable list"


# ── T3: Priority ladder ──────────────────────────────────────────────────────

class TestPriorityLadder:
    """_derive_next_action returns correct priority for each flag combination."""

    def test_urgent_dhl_request_no_reply(self):
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": False,
            "our_dhl_reply_queued": False,
        })
        assert action is not None
        assert action["priority"] == "urgent"

    def test_high_documents_not_forwarded(self):
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": True,
            "dhl_documents_received": True,
            "agency_forward_sent": False,
            "agency_forward_queued": False,
        })
        assert action is not None
        assert action["priority"] == "high"
        assert "forward to agency" in action["title"]

    def test_high_sad_received(self):
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": True,
            "dhl_documents_received": True,
            "agency_forward_sent": True,
            "agency_sad_received": True,
        })
        assert action is not None
        assert action["priority"] == "high"
        assert "SAD" in action["title"]

    def test_normal_dhl_invoice(self):
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": True,
            "dhl_documents_received": True,
            "agency_forward_sent": True,
            "agency_sad_received": False,
            "dhl_invoice_received": True,
        })
        assert action is not None
        assert action["priority"] == "normal"
        assert "DHL invoice" in action["title"]

    def test_normal_agency_invoice(self):
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": True,
            "dhl_documents_received": True,
            "agency_forward_sent": True,
            "agency_sad_received": False,
            "dhl_invoice_received": False,
            "agency_invoice_received": True,
        })
        assert action is not None
        assert action["priority"] == "normal"
        assert "Agency invoice" in action["title"]

    def test_none_when_empty_summary(self):
        assert _derive_next_action({}) is None
        assert _derive_next_action(None) is None

    def test_none_when_all_resolved(self):
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": True,
            "our_dhl_reply_queued": False,
            "dhl_documents_received": True,
            "agency_forward_sent": True,
            "agency_forward_queued": False,
            "agency_sad_received": False,
            "dhl_invoice_received": False,
            "agency_invoice_received": False,
        })
        assert action is None

    def test_queued_reply_counts_as_handled(self):
        """our_dhl_reply_queued=True → not urgent (reply is pending send)."""
        action = _derive_next_action({
            "dhl_request_received": True,
            "our_dhl_reply_sent": False,
            "our_dhl_reply_queued": True,
        })
        # Not urgent anymore — reply is queued
        assert action is None or action["priority"] != "urgent"


# ── T4: Malformed JSON skipped safely ─────────────────────────────────────────

def test_malformed_json_skipped(tmp_path):
    """Malformed JSON in by_awb/ is silently skipped; other AWBs still returned."""
    by_awb = tmp_path / "email_evidence" / "by_awb"
    by_awb.mkdir(parents=True, exist_ok=True)
    # Bad file
    (by_awb / "BAD-AWB.json").write_text("not valid json {{{", encoding="utf-8")
    # Good file
    _make_awb_file(by_awb, "GOOD-AWB", {
        "dhl_request_received": True,
        "our_dhl_reply_sent": False,
        "our_dhl_reply_queued": False,
    })

    with patch.object(settings, "storage_root", tmp_path):
        results = list_actionable_awbs(limit=30)

    assert len(results) == 1
    assert results[0]["awb"] == "GOOD-AWB"


# ── T5: Missing by_awb/ directory returns [] ──────────────────────────────────

def test_missing_by_awb_dir_returns_empty(tmp_path):
    """If storage/email_evidence/by_awb/ doesn't exist, return empty list."""
    # Don't create the directory at all
    with patch.object(settings, "storage_root", tmp_path):
        results = list_actionable_awbs(limit=30)

    assert results == []


# ── T6: End-to-end: GET /api/v1/inbox returns customs items ───────────────────

def test_inbox_returns_customs_items_from_evidence_store(tmp_path):
    """GET /api/v1/inbox surfaces DHL evidence as type='customs' items."""
    by_awb = tmp_path / "email_evidence" / "by_awb"
    _make_awb_file(by_awb, "4789974092", {
        "dhl_request_received": True,
        "our_dhl_reply_sent": False,
        "our_dhl_reply_queued": False,
        "dhl_documents_received": False,
        "agency_forward_sent": False,
        "agency_forward_queued": False,
        "agency_sad_received": False,
        "dhl_invoice_received": False,
        "agency_invoice_received": False,
    }, batch_ids=["GJ-2026-001"], last_message_at="2026-06-05T10:00:00")

    with (
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True

    customs_items = [i for i in body["items"] if i["type"] == "customs"]
    assert len(customs_items) >= 1, "Expected at least one customs item from evidence store"
    item = customs_items[0]
    assert item["id"] == "dhl-4789974092"
    assert item["priority"] == "urgent"
    assert item["linked_batch_id"] == "GJ-2026-001"
    assert item["actionable"] is True
    assert "reply needed" in item["title"]

    # Source reported healthy
    assert body["sources"]["dhl_cache"]["ok"] is True
    assert body["sources"]["dhl_cache"]["count"] >= 1


# ── T7: No scan trigger — static import guard ────────────────────────────────

def test_no_scan_trigger_in_inbox():
    """routes_inbox.py must not import dhl_email_monitor or routes_dhl_clearance."""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("app.api.routes_inbox")
    assert spec is not None
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_modules = {"dhl_email_monitor", "routes_dhl_clearance"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            names = [a.name for a in getattr(node, "names", [])]
            for fm in forbidden_modules:
                assert fm not in module and fm not in " ".join(names), (
                    f"routes_inbox.py must not import {fm} — "
                    "would create scan trigger path from GET /api/v1/inbox"
                )


# ── T8: email_intelligence_store.list_recent not called ───────────────────────

def test_intelligence_store_not_called_from_inbox(tmp_path):
    """Inbox path must NOT call email_intelligence_store.list_recent anymore."""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("app.api.routes_inbox")
    assert spec is not None
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Check no import of email_intelligence_store anywhere in the module
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "email_intelligence_store" in module:
                pytest.fail(
                    "routes_inbox.py must not import email_intelligence_store — "
                    "Source C now reads from email_evidence_store"
                )


# ── T9: Envelope shape — required fields present ─────────────────────────────

def test_inbox_item_envelope_shape(tmp_path):
    """Every DHL customs inbox item has the required envelope fields."""
    by_awb = tmp_path / "email_evidence" / "by_awb"
    _make_awb_file(by_awb, "SHAPE-001", {
        "dhl_request_received": True,
        "our_dhl_reply_sent": False,
        "our_dhl_reply_queued": False,
    }, batch_ids=["B-SHAPE"], messages=2)

    with (
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    customs_items = [i for i in r.json()["items"] if i["type"] == "customs"]
    assert len(customs_items) >= 1

    required_fields = {
        "id", "type", "priority", "title", "detail",
        "age", "actor", "primary_action", "linked_batch_id",
        "actionable", "endpoint",
    }
    for item in customs_items:
        missing = required_fields - set(item.keys())
        assert not missing, f"Missing fields in DHL inbox item: {missing}"
        assert item["type"] == "customs"
        assert item["actionable"] is True
        assert item["primary_action"] == "Review"
        assert item["actor"] == "DHL evidence"
