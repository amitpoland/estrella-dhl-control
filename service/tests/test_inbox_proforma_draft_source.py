"""
test_inbox_proforma_draft_source.py — Contract tests for proforma draft → inbox wiring.

Sprint 2: Inbox Authority Completion — Add Source D (Proforma Drafts).

Proves:
  T1. Attention-state drafts (draft, editing, approved, post_failed, posting) appear
  T2. Terminal-state drafts (posted, cancelled, superseded) do NOT appear
  T3. Priority: post_failed/posting = high; approved/draft/editing = normal
  T4. Type is "proforma_draft", never "approval" or "proposal"
  T5. linked_batch_id is present on every item
  T6. No approve/post/cancel/convert calls from inbox
  T7. Empty DB returns []
  T8. End-to-end: GET /api/v1/inbox includes type="proforma_draft" items
  T9. Envelope shape: all required inbox fields present
  T10. Actor is "Proforma"
  T11. Source D graceful degradation (DB error → still 200)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.proforma_invoice_link_db import (
    DRAFT_LIFECYCLE_STATES,
    list_attention_drafts,
    init_db,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _insert_draft(db_path: Path, *,
                  draft_id: int = 1,
                  batch_id: str = "BATCH-001",
                  client_name: str = "TestClient GmbH",
                  draft_state: str = "draft",
                  currency: str = "EUR",
                  fullnumber: str = "",
                  updated_at: str = "2026-06-08T10:00:00Z",
                  created_at: str = "2026-06-07T08:00:00Z") -> None:
    """Insert a minimal proforma_drafts row directly."""
    init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """INSERT INTO proforma_drafts
               (id, batch_id, client_name, status, currency, source_lines_json,
                created_at, updated_at, draft_state, wfirma_proforma_fullnumber)
               VALUES (?, ?, ?, 'draft', ?, '[]', ?, ?, ?, ?)""",
            (draft_id, batch_id, client_name, currency,
             created_at, updated_at, draft_state, fullnumber),
        )
        conn.commit()


def _api_key_header() -> Dict[str, str]:
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── T1: Attention-state drafts appear ────────────────────────────────────────

class TestAttentionStatesAppear:
    """Each attention state produces a result in list_attention_drafts."""

    @pytest.mark.parametrize("state", ["draft", "editing", "approved", "post_failed", "posting"])
    def test_attention_state_appears(self, tmp_path, state):
        db = tmp_path / "proforma_links.db"
        _insert_draft(db, draft_id=1, draft_state=state)
        results = list_attention_drafts(db, limit=50)
        assert len(results) == 1
        assert results[0]["draft_state"] == state
        assert results[0]["batch_id"] == "BATCH-001"
        assert results[0]["client_name"] == "TestClient GmbH"


# ── T2: Terminal-state drafts do NOT appear ──────────────────────────────────

class TestTerminalStatesExcluded:
    """posted, cancelled, superseded must never appear in attention list."""

    @pytest.mark.parametrize("state", ["posted", "cancelled", "superseded"])
    def test_terminal_state_excluded(self, tmp_path, state):
        db = tmp_path / "proforma_links.db"
        _insert_draft(db, draft_id=1, draft_state=state)
        results = list_attention_drafts(db, limit=50)
        assert len(results) == 0, f"State '{state}' must not appear in attention list"


# ── T3: Priority mapping ────────────────────────────────────────────────────

class TestPriorityMapping:
    """post_failed/posting = high; approved/draft/editing = normal."""

    def test_post_failed_is_high(self, tmp_path):
        db = tmp_path / "proforma_links.db"
        _insert_draft(db, draft_id=1, draft_state="post_failed")
        with patch.object(settings, "storage_root", tmp_path):
            from app.api.routes_inbox import _collect_proforma_draft_items
            items = _collect_proforma_draft_items()
        assert len(items) == 1
        assert items[0]["priority"] == "high"

    def test_posting_is_high(self, tmp_path):
        db = tmp_path / "proforma_links.db"
        _insert_draft(db, draft_id=1, draft_state="posting")
        with patch.object(settings, "storage_root", tmp_path):
            from app.api.routes_inbox import _collect_proforma_draft_items
            items = _collect_proforma_draft_items()
        assert len(items) == 1
        assert items[0]["priority"] == "high"

    def test_approved_is_normal(self, tmp_path):
        db = tmp_path / "proforma_links.db"
        _insert_draft(db, draft_id=1, draft_state="approved")
        with patch.object(settings, "storage_root", tmp_path):
            from app.api.routes_inbox import _collect_proforma_draft_items
            items = _collect_proforma_draft_items()
        assert len(items) == 1
        assert items[0]["priority"] == "normal"

    def test_draft_is_normal(self, tmp_path):
        db = tmp_path / "proforma_links.db"
        _insert_draft(db, draft_id=1, draft_state="draft")
        with patch.object(settings, "storage_root", tmp_path):
            from app.api.routes_inbox import _collect_proforma_draft_items
            items = _collect_proforma_draft_items()
        assert len(items) == 1
        assert items[0]["priority"] == "normal"


# ── T4: Type is proforma_draft, never approval ──────────────────────────────

def test_type_is_proforma_draft_not_approval(tmp_path):
    """Type must be 'proforma_draft', not 'approval' or 'proposal'."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, draft_state="approved")
    with patch.object(settings, "storage_root", tmp_path):
        from app.api.routes_inbox import _collect_proforma_draft_items
        items = _collect_proforma_draft_items()
    assert len(items) == 1
    assert items[0]["type"] == "proforma_draft"
    assert items[0]["type"] != "approval"
    assert items[0]["type"] != "proposal"


# ── T5: linked_batch_id is present ──────────────────────────────────────────

def test_linked_batch_id_present(tmp_path):
    """Every proforma draft inbox item must have linked_batch_id."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, batch_id="GJ-2026-005", draft_state="draft")
    with patch.object(settings, "storage_root", tmp_path):
        from app.api.routes_inbox import _collect_proforma_draft_items
        items = _collect_proforma_draft_items()
    assert len(items) == 1
    assert items[0]["linked_batch_id"] == "GJ-2026-005"


# ── T6: No approve/post/cancel/convert calls ────────────────────────────────

def test_no_write_imports_in_inbox():
    """routes_inbox must not import proforma write functions."""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("app.api.routes_inbox")
    assert spec is not None
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Forbidden import targets: any proforma write route module
    forbidden_names = {
        "approve_draft", "reopen_draft", "cancel_draft",
        "post_proforma_draft_to_wfirma", "create_pending_link",
        "mark_issued", "mark_failed",
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            for fn in forbidden_names:
                assert fn not in names, (
                    f"routes_inbox.py must not import {fn} — "
                    "inbox is read-only, proforma writes stay in routes_proforma.py"
                )


# ── T7: Empty DB returns [] ─────────────────────────────────────────────────

def test_empty_db_returns_empty(tmp_path):
    """list_attention_drafts on empty/nonexistent DB returns []."""
    db = tmp_path / "proforma_links.db"
    # DB doesn't exist yet
    results = list_attention_drafts(db, limit=50)
    assert results == []


def test_db_with_only_terminal_returns_empty(tmp_path):
    """DB with only posted drafts returns []."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, draft_state="posted")
    _insert_draft(db, draft_id=2, draft_state="cancelled", client_name="Other", batch_id="B2")
    results = list_attention_drafts(db, limit=50)
    assert results == []


# ── T8: End-to-end: GET /api/v1/inbox includes proforma_draft items ────────

def test_inbox_returns_proforma_draft_items(tmp_path):
    """GET /api/v1/inbox surfaces proforma drafts as type='proforma_draft'."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, batch_id="GJ-2026-PROFORMA",
                  draft_state="post_failed", client_name="DiamondGroup GmbH")

    with (
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch("app.services.email_evidence_store.list_actionable_awbs", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True

    pf_items = [i for i in body["items"] if i["type"] == "proforma_draft"]
    assert len(pf_items) >= 1, "Expected at least one proforma_draft item"
    item = pf_items[0]
    assert item["id"] == "proforma-draft-1"
    assert item["priority"] == "high"
    assert item["linked_batch_id"] == "GJ-2026-PROFORMA"
    assert item["actionable"] is True
    assert "post failed" in item["title"].lower()

    # Source D reported healthy
    assert body["sources"]["proforma_drafts"]["ok"] is True
    assert body["sources"]["proforma_drafts"]["count"] >= 1


# ── T9: Envelope shape ──────────────────────────────────────────────────────

def test_proforma_draft_envelope_shape(tmp_path):
    """Every proforma_draft inbox item has all required envelope fields."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, draft_state="editing",
                  batch_id="SHAPE-B", client_name="ShapeCo")

    with patch.object(settings, "storage_root", tmp_path):
        from app.api.routes_inbox import _collect_proforma_draft_items
        items = _collect_proforma_draft_items()

    assert len(items) >= 1
    required_fields = {
        "id", "type", "priority", "title", "detail",
        "age", "actor", "primary_action", "linked_batch_id",
        "actionable", "endpoint",
    }
    for item in items:
        missing = required_fields - set(item.keys())
        assert not missing, f"Missing fields in proforma_draft item: {missing}"
        assert item["type"] == "proforma_draft"
        assert item["actionable"] is True
        assert item["primary_action"] == "Review"


# ── T10: Actor is "Proforma" ────────────────────────────────────────────────

def test_actor_is_proforma(tmp_path):
    """Actor must be 'Proforma', not 'AI Bridge' or 'Proforma system'."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, draft_state="approved")
    with patch.object(settings, "storage_root", tmp_path):
        from app.api.routes_inbox import _collect_proforma_draft_items
        items = _collect_proforma_draft_items()
    assert len(items) == 1
    assert items[0]["actor"] == "Proforma"


# ── T11: Graceful degradation — DB error still returns 200 ──────────────────

def test_source_d_graceful_degradation(tmp_path):
    """If proforma DB read fails, inbox still returns 200 with error marker."""
    with (
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch("app.services.email_evidence_store.list_actionable_awbs", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
        patch(
            "app.api.routes_inbox._collect_proforma_draft_items",
            side_effect=RuntimeError("DB locked"),
        ),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["sources"]["proforma_drafts"]["ok"] is False
    assert "DB locked" in body["sources"]["proforma_drafts"]["error"]


# ── T12: Multiple attention states sorted by updated_at DESC ────────────────

def test_multiple_drafts_sorted_by_recency(tmp_path):
    """Multiple drafts across states, most recently updated first."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, draft_state="draft",
                  updated_at="2026-06-01T10:00:00Z", batch_id="B1",
                  client_name="C1")
    _insert_draft(db, draft_id=2, draft_state="post_failed",
                  updated_at="2026-06-08T10:00:00Z", batch_id="B2",
                  client_name="C2")
    _insert_draft(db, draft_id=3, draft_state="approved",
                  updated_at="2026-06-05T10:00:00Z", batch_id="B3",
                  client_name="C3")

    results = list_attention_drafts(db, limit=50)
    assert len(results) == 3
    # Most recent updated_at first
    assert results[0]["id"] == 2  # June 8
    assert results[1]["id"] == 3  # June 5
    assert results[2]["id"] == 1  # June 1


# ── T13: Detail includes batch_id and client_name ───────────────────────────

def test_detail_contains_batch_and_client(tmp_path):
    """Detail string includes batch_id and client_name."""
    db = tmp_path / "proforma_links.db"
    _insert_draft(db, draft_id=1, draft_state="draft",
                  batch_id="GJ-2026-042", client_name="DiamondGroup GmbH")
    with patch.object(settings, "storage_root", tmp_path):
        from app.api.routes_inbox import _collect_proforma_draft_items
        items = _collect_proforma_draft_items()
    assert len(items) == 1
    assert "GJ-2026-042" in items[0]["detail"]
    assert "DiamondGroup GmbH" in items[0]["detail"]
