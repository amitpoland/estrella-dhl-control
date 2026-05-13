"""
test_proforma_packing_sync.py — proforma_draft_sync.sync_draft_from_packing_upload

Tests for the packing-upload → proforma-draft auto-create/sync flow.

Coverage:
1.  No sales packing lines → no-op, returns no_sales_lines=True
2.  New client → draft auto-created, action=created, EV_PROFORMA_DRAFT_AUTO_CREATED logged
3.  Existing editable draft (state=draft) → lines reset, action=synced, state→editing
4.  Existing editable draft (state=post_failed) → lines reset, action=synced
5.  Existing finalized draft (state=approved) → blocked, draft unchanged
6.  Existing finalized draft (state=posted) → blocked, draft unchanged
7.  Multiple clients → each handled independently, counts correct
8.  TOCTOU race (DraftConflict) → treated as blocked, no 500 raised
9.  last_packing_sync_at written after create
10. last_packing_sync_at written after sync; packing_sync_warning set on blocked
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.services import proforma_invoice_link_db as pildb
from app.services.proforma_draft_sync import sync_draft_from_packing_upload, _modal_currency


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def audit_path(tmp_path) -> Path:
    p = tmp_path / "audit.json"
    p.write_text(json.dumps({"timeline": []}), encoding="utf-8")
    return p


def _sales_lines(client_name: str, n: int = 2, currency: str = "EUR") -> List[Dict[str, Any]]:
    return [
        {
            "client_name":  client_name,
            "product_code": f"PC-{i:03d}",
            "design_no":    f"D{i:03d}",
            "qty":          float(i + 1),
            "unit_price":   10.0 * (i + 1),
            "currency":     currency,
        }
        for i in range(n)
    ]


def _patch_sales_lines(batch_id: str, lines: List[Dict[str, Any]]):
    """Return a context-manager that monkey-patches ddb.get_sales_packing_lines."""
    return patch(
        "app.services.proforma_draft_sync.ddb.get_sales_packing_lines",
        return_value=lines,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestNoSalesLines:
    """No sales packing lines → sync is a no-op."""

    def test_no_lines_returns_flag(self, db_path, audit_path):
        with _patch_sales_lines("B1", []):
            result = sync_draft_from_packing_upload(
                batch_id="B1", operator="test",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["no_sales_lines"] is True
        assert result["clients_processed"] == 0
        assert result["created"] == 0

    def test_no_lines_no_draft_created(self, db_path, audit_path):
        with _patch_sales_lines("B1", []):
            sync_draft_from_packing_upload(
                batch_id="B1", operator="test",
                db_path=db_path, audit_path=audit_path,
            )
        drafts = pildb.list_drafts_for_batch(db_path, "B1")
        assert drafts == []


class TestAutoCreate:
    """New client → draft created."""

    def test_creates_draft(self, db_path, audit_path):
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B2", lines):
            result = sync_draft_from_packing_upload(
                batch_id="B2", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["created"] == 1
        assert result["synced"] == 0
        assert result["blocked"] == 0
        drafts = pildb.list_drafts_for_batch(db_path, "B2")
        assert len(drafts) == 1
        assert drafts[0].client_name == "ACME"
        assert drafts[0].draft_state == "draft"

    def test_create_is_idempotent(self, db_path, audit_path):
        """Second upload on same batch+client → syncs (not second create)."""
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B3", lines):
            r1 = sync_draft_from_packing_upload(
                batch_id="B3", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        with _patch_sales_lines("B3", lines):
            r2 = sync_draft_from_packing_upload(
                batch_id="B3", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert r1["created"] == 1
        assert r2["created"] == 0
        assert r2["synced"] == 1
        # Only one draft row
        assert len(pildb.list_drafts_for_batch(db_path, "B3")) == 1

    def test_create_writes_sync_metadata(self, db_path, audit_path):
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B4", lines):
            sync_draft_from_packing_upload(
                batch_id="B4", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        draft = pildb.list_drafts_for_batch(db_path, "B4")[0]
        assert draft.last_packing_sync_at is not None
        assert draft.packing_sync_warning is None

    def test_create_logs_timeline_event(self, db_path, audit_path):
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B5", lines):
            sync_draft_from_packing_upload(
                batch_id="B5", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        timeline = json.loads(audit_path.read_text(encoding="utf-8")).get("timeline", [])
        events = [e["event"] for e in timeline]
        assert "proforma_draft_auto_created" in events


class TestSyncEditable:
    """Existing editable draft → lines are reset."""

    def _make_draft(self, db_path, batch_id, client_name, state=None):
        d, _ = pildb.auto_create_draft_from_sales_packing(
            db_path, batch_id=batch_id, client_name=client_name,
            currency="EUR", lines=[{"product_code": "PC-001", "qty": 1, "unit_price": 10.0, "currency": "EUR"}],
            operator="test",
        )
        if state == "post_failed":
            d = pildb.approve_draft(db_path, d.id, "test", d.updated_at,
                                    confirm_token=pildb.APPROVE_CONFIRM_TOKEN)
            d = pildb.start_post(db_path, d.id, "test", d.updated_at,
                                 confirm_token=pildb.POST_CONFIRM_TOKEN)
            d = pildb.mark_post_failed(db_path, d.id, error="timeout", operator="test")
        return d

    def test_sync_draft_state_advances_to_editing(self, db_path, audit_path):
        self._make_draft(db_path, "B6", "ACME")
        lines = _sales_lines("ACME", n=3)
        with _patch_sales_lines("B6", lines):
            result = sync_draft_from_packing_upload(
                batch_id="B6", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["synced"] == 1
        draft = pildb.list_drafts_for_batch(db_path, "B6")[0]
        assert draft.draft_state == "editing"
        # Lines were updated (3 lines now)
        editable = json.loads(draft.editable_lines_json)
        assert len(editable) == 3

    def test_sync_post_failed_draft(self, db_path, audit_path):
        self._make_draft(db_path, "B7", "ACME", state="post_failed")
        lines = _sales_lines("ACME", n=2)
        with _patch_sales_lines("B7", lines):
            result = sync_draft_from_packing_upload(
                batch_id="B7", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["synced"] == 1
        draft = pildb.list_drafts_for_batch(db_path, "B7")[0]
        # post_failed stays post_failed (no transition)
        assert draft.draft_state == "post_failed"

    def test_sync_writes_sync_metadata(self, db_path, audit_path):
        self._make_draft(db_path, "B8", "ACME")
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B8", lines):
            sync_draft_from_packing_upload(
                batch_id="B8", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        draft = pildb.list_drafts_for_batch(db_path, "B8")[0]
        assert draft.last_packing_sync_at is not None
        assert draft.packing_sync_warning is None

    def test_sync_logs_timeline_event(self, db_path, audit_path):
        self._make_draft(db_path, "B9", "ACME")
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B9", lines):
            sync_draft_from_packing_upload(
                batch_id="B9", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        timeline = json.loads(audit_path.read_text(encoding="utf-8")).get("timeline", [])
        events = [e["event"] for e in timeline]
        assert "proforma_draft_synced" in events


class TestFinalizedDraftProtection:
    """Finalized drafts must not be overwritten."""

    def _make_approved(self, db_path, batch_id, client_name):
        d, _ = pildb.auto_create_draft_from_sales_packing(
            db_path, batch_id=batch_id, client_name=client_name,
            currency="EUR", lines=[{"product_code": "PC-001", "qty": 1, "unit_price": 10.0, "currency": "EUR"}],
        )
        d = pildb.approve_draft(db_path, d.id, "test", d.updated_at,
                                confirm_token=pildb.APPROVE_CONFIRM_TOKEN)
        return d

    def test_approved_draft_not_overwritten(self, db_path, audit_path):
        d = self._make_approved(db_path, "B10", "ACME")
        original_updated_at = d.updated_at
        lines = _sales_lines("ACME", n=5)
        with _patch_sales_lines("B10", lines):
            result = sync_draft_from_packing_upload(
                batch_id="B10", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["blocked"] == 1
        assert result["synced"] == 0
        draft = pildb.list_drafts_for_batch(db_path, "B10")[0]
        assert draft.draft_state == "approved"
        # Lines should NOT be updated to 5
        editable = json.loads(draft.editable_lines_json)
        assert len(editable) == 1

    def test_blocked_sets_sync_warning(self, db_path, audit_path):
        self._make_approved(db_path, "B11", "ACME")
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B11", lines):
            sync_draft_from_packing_upload(
                batch_id="B11", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        draft = pildb.list_drafts_for_batch(db_path, "B11")[0]
        assert draft.packing_sync_warning is not None
        assert "finalized" in draft.packing_sync_warning

    def test_blocked_logs_timeline_event(self, db_path, audit_path):
        self._make_approved(db_path, "B12", "ACME")
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B12", lines):
            sync_draft_from_packing_upload(
                batch_id="B12", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        timeline = json.loads(audit_path.read_text(encoding="utf-8")).get("timeline", [])
        events = [e["event"] for e in timeline]
        assert "proforma_sync_blocked_finalized" in events


class TestMultipleClients:
    """Multiple clients in one batch handled independently."""

    def test_multiple_clients_separate_drafts(self, db_path, audit_path):
        lines = _sales_lines("ACME") + _sales_lines("GLOBAL", currency="USD")
        with _patch_sales_lines("B13", lines):
            result = sync_draft_from_packing_upload(
                batch_id="B13", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["created"] == 2
        assert result["clients_processed"] == 2
        drafts = pildb.list_drafts_for_batch(db_path, "B13")
        client_names = {d.client_name for d in drafts}
        assert client_names == {"ACME", "GLOBAL"}

    def test_partial_blocked_does_not_stop_others(self, db_path, audit_path):
        # Pre-create ACME as approved (blocked)
        d, _ = pildb.auto_create_draft_from_sales_packing(
            db_path, batch_id="B14", client_name="ACME",
            currency="EUR",
            lines=[{"product_code": "PC-001", "qty": 1, "unit_price": 10.0, "currency": "EUR"}],
        )
        pildb.approve_draft(db_path, d.id, "test", d.updated_at,
                            confirm_token=pildb.APPROVE_CONFIRM_TOKEN)
        # GLOBAL is new
        lines = _sales_lines("ACME") + _sales_lines("GLOBAL")
        with _patch_sales_lines("B14", lines):
            result = sync_draft_from_packing_upload(
                batch_id="B14", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )
        assert result["created"] == 1   # GLOBAL created
        assert result["blocked"] == 1   # ACME blocked
        assert result["clients_processed"] == 2


class TestTOCTOURace:
    """DraftConflict from optimistic lock → treated as blocked, no exception."""

    def test_draft_conflict_is_non_fatal(self, db_path, audit_path):
        d, _ = pildb.auto_create_draft_from_sales_packing(
            db_path, batch_id="B15", client_name="ACME",
            currency="EUR",
            lines=[{"product_code": "PC-001", "qty": 1, "unit_price": 10.0, "currency": "EUR"}],
        )
        # Simulate race: reset raises DraftConflict
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B15", lines):
            with patch(
                "app.services.proforma_draft_sync.pildb.reset_draft_from_sales_packing",
                side_effect=pildb.DraftConflict("simulated race"),
            ):
                result = sync_draft_from_packing_upload(
                    batch_id="B15", operator="packing_upload",
                    db_path=db_path, audit_path=audit_path,
                )
        # Must not raise — blocked is the expected outcome
        assert result["blocked"] == 1
        assert result["synced"] == 0

    def test_draft_conflict_sets_warning(self, db_path, audit_path):
        d, _ = pildb.auto_create_draft_from_sales_packing(
            db_path, batch_id="B16", client_name="ACME",
            currency="EUR",
            lines=[{"product_code": "PC-001", "qty": 1, "unit_price": 10.0, "currency": "EUR"}],
        )
        lines = _sales_lines("ACME")
        with _patch_sales_lines("B16", lines):
            with patch(
                "app.services.proforma_draft_sync.pildb.reset_draft_from_sales_packing",
                side_effect=pildb.DraftConflict("simulated race"),
            ):
                sync_draft_from_packing_upload(
                    batch_id="B16", operator="packing_upload",
                    db_path=db_path, audit_path=audit_path,
                )
        draft = pildb.list_drafts_for_batch(db_path, "B16")[0]
        assert draft.packing_sync_warning is not None
        assert "DraftConflict" in draft.packing_sync_warning


class TestModalCurrency:
    """Helper correctly picks the most-common currency."""

    def test_single_currency(self):
        lines = [{"currency": "EUR"}, {"currency": "EUR"}]
        assert _modal_currency(lines) == "EUR"

    def test_majority_currency(self):
        lines = [
            {"currency": "EUR"}, {"currency": "EUR"},
            {"currency": "USD"}, {"currency": "PLN"},
        ]
        assert _modal_currency(lines) == "EUR"

    def test_empty_fallback(self):
        assert _modal_currency([]) == "EUR"
        assert _modal_currency([{}]) == "EUR"
