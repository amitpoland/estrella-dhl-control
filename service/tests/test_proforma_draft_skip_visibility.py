"""
test_proforma_draft_skip_visibility.py — PR 1 (Draft-birth visibility)
======================================================================

Tests for the silent-drop visibility layer added to
``proforma_draft_sync.sync_draft_from_packing_upload``.

Behaviour contract (PR 1 — observation only):
  * For every ``sales_document_id`` whose lines all carry empty
    ``client_name`` (and therefore contribute ZERO entries to ``by_client``),
    emit exactly ONE timeline event on ``audit.json``:
      - ``proforma_draft_creation_pending_resolution`` when at least one
        identity signal (VAT or heading candidate) was observed in the
        source XLSX preamble.
      - ``proforma_draft_creation_skipped`` when no identity signals were
        found.
  * The draft-count invariant is preserved: pre-PR draft count for any
    given input == post-PR draft count.  The visibility layer never
    creates, mutates, or skips a draft.
  * Helper ``preamble_signals.extract_*`` is best-effort: missing file,
    no openpyxl, no signal — all return ``None`` and the visibility
    branch falls through to the SKIPPED event.

Regression target: SHIPMENT_7123231135_2026-06_f255bbb5 (7 packing
uploads → 5 drafts).  The 2 missing drafts (EJL/26-27/258, /260) were
silently dropped with no audit signal.  PR 1 makes that class auditable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services import proforma_invoice_link_db as pildb
from app.services.proforma_draft_sync import sync_draft_from_packing_upload


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


def _line(
    *,
    sales_document_id: str,
    client_name: str = "",
    total_value: float = 100.0,
    currency: str = "EUR",
    product_code: str = "PC-001",
) -> Dict[str, Any]:
    """Minimal sales_packing_lines-shaped row carrying a sales_document_id."""
    return {
        "sales_document_id": sales_document_id,
        "client_name":       client_name,
        "client_ref":        "",
        "product_code":      product_code,
        "design_no":         "D001",
        "bag_id":            "B1",
        "quantity":          1.0,
        "unit_price":        total_value,
        "currency":          currency,
        "total_value":       total_value,
        "price_source":      "packing_xlsx_value",
        "remarks":           "",
    }


def _patch_sales_lines(lines: List[Dict[str, Any]]):
    return patch(
        "app.services.proforma_draft_sync.ddb.get_sales_packing_lines",
        return_value=lines,
    )


def _patch_lookup(mapping: Dict[str, str]):
    """Patch the documents.db sales_documents lookup with an in-memory map.

    ``mapping`` is {sales_document_id: source_file_path}.
    """
    def fake_lookup(batch_id: str, sd_id: str):
        return (mapping.get(sd_id, ""), "")
    return patch(
        "app.services.proforma_draft_sync._lookup_sales_doc_source_path",
        side_effect=fake_lookup,
    )


def _patch_signals(per_path_signals: Dict[str, Dict[str, Any]]):
    """Patch preamble_signals.extract_all_signals with a path → signals map.

    Any path not in the map returns ``{"vat": None, "heading_candidate": None}``.
    """
    def fake_extract(xlsx_path):
        return per_path_signals.get(
            str(xlsx_path), {"vat": None, "heading_candidate": None}
        )
    return patch(
        "app.services.proforma_draft_sync._ps.extract_all_signals",
        side_effect=fake_extract,
    )


def _events(audit_path: Path) -> List[Dict[str, Any]]:
    return json.loads(audit_path.read_text(encoding="utf-8")).get("timeline", [])


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEmptyClientNameEmitsSkipEvent:
    """All-empty-client_name sales_document → exactly one skip event."""

    def test_empty_client_name_with_vat_signal_emits_pending(
        self, db_path, audit_path
    ):
        lines = [_line(sales_document_id="SD-VAT", client_name="")]
        with _patch_sales_lines(lines), \
             _patch_lookup({"SD-VAT": "/fake/ejl-260.xlsx"}), \
             _patch_signals({
                 "/fake/ejl-260.xlsx": {
                     "vat": "SK107095376", "heading_candidate": None,
                 }
             }):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS1", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        events = [e for e in _events(audit_path)
                  if e["event"] == "proforma_draft_creation_pending_resolution"]
        assert len(events) == 1, (
            "VAT signal present → expected one PENDING_RESOLUTION event"
        )
        detail = events[0]["detail"]
        assert detail["sales_doc_id"] == "SD-VAT"
        assert detail["resolver_signals_seen"]["vat"] == "SK107095376"
        assert detail["next_action"] == "vat_resolver_will_auto_bind_post_pr2"
        assert result["pending_resolution"] == 1
        assert result["skipped_no_signal"] == 0

    def test_empty_client_name_no_signal_emits_skipped(
        self, db_path, audit_path
    ):
        lines = [_line(sales_document_id="SD-NONE", client_name="")]
        with _patch_sales_lines(lines), \
             _patch_lookup({"SD-NONE": "/fake/blank.xlsx"}), \
             _patch_signals({
                 "/fake/blank.xlsx": {
                     "vat": None, "heading_candidate": None,
                 }
             }):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS2", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        events = [e for e in _events(audit_path)
                  if e["event"] == "proforma_draft_creation_skipped"]
        assert len(events) == 1, (
            "No signals → expected one SKIPPED event"
        )
        detail = events[0]["detail"]
        assert detail["sales_doc_id"] == "SD-NONE"
        assert detail["resolver_signals_seen"] == {
            "vat": None, "heading_candidate": None,
        }
        assert detail["next_action"] == "operator_bind_client_name_manually"
        assert result["pending_resolution"] == 0
        assert result["skipped_no_signal"] == 1

    def test_non_empty_client_name_emits_no_skip_event(
        self, db_path, audit_path
    ):
        lines = [_line(sales_document_id="SD-OK", client_name="ACME")]
        with _patch_sales_lines(lines), \
             _patch_lookup({"SD-OK": "/fake/ok.xlsx"}), \
             _patch_signals({}):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS3", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        skip_events = [
            e for e in _events(audit_path)
            if e["event"] in (
                "proforma_draft_creation_pending_resolution",
                "proforma_draft_creation_skipped",
            )
        ]
        assert skip_events == [], (
            "client_name present → no skip event must be emitted"
        )
        assert result["pending_resolution"] == 0
        assert result["skipped_no_signal"] == 0
        assert result["created"] == 1


class TestSkipEventCountMatchesDroppedDocs:
    """One event per dropped sales_document, regardless of line count."""

    def test_two_distinct_empty_docs_emit_two_events(
        self, db_path, audit_path
    ):
        lines = [
            _line(sales_document_id="SD-A", client_name=""),
            _line(sales_document_id="SD-A", client_name=""),
            _line(sales_document_id="SD-A", client_name=""),
            _line(sales_document_id="SD-B", client_name=""),
            _line(sales_document_id="SD-B", client_name=""),
        ]
        with _patch_sales_lines(lines), \
             _patch_lookup({
                 "SD-A": "/fake/ejl-258.xlsx",
                 "SD-B": "/fake/ejl-260.xlsx",
             }), \
             _patch_signals({
                 "/fake/ejl-258.xlsx": {"vat": None, "heading_candidate": None},
                 "/fake/ejl-260.xlsx": {
                     "vat": "SK107095376", "heading_candidate": None,
                 },
             }):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS4", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        events = [
            e for e in _events(audit_path)
            if e["event"] in (
                "proforma_draft_creation_pending_resolution",
                "proforma_draft_creation_skipped",
            )
        ]
        assert len(events) == 2, (
            "Two dropped sales_documents → expected two skip events "
            "(one per doc, NOT one per line)"
        )
        emitted_ids = {e["detail"]["sales_doc_id"] for e in events}
        assert emitted_ids == {"SD-A", "SD-B"}
        assert result["pending_resolution"] == 1   # SD-B
        assert result["skipped_no_signal"] == 1    # SD-A

    def test_mixed_dropped_and_kept_docs_only_emit_for_dropped(
        self, db_path, audit_path
    ):
        lines = [
            _line(sales_document_id="SD-EMPTY", client_name=""),
            _line(sales_document_id="SD-OK", client_name="ACME"),
        ]
        with _patch_sales_lines(lines), \
             _patch_lookup({
                 "SD-EMPTY": "/fake/empty.xlsx",
                 "SD-OK":    "/fake/ok.xlsx",
             }), \
             _patch_signals({}):
            sync_draft_from_packing_upload(
                batch_id="BVIS5", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        events = [
            e for e in _events(audit_path)
            if e["event"] in (
                "proforma_draft_creation_pending_resolution",
                "proforma_draft_creation_skipped",
            )
        ]
        assert len(events) == 1
        assert events[0]["detail"]["sales_doc_id"] == "SD-EMPTY"


class TestSkipEventPreservesDraftCountInvariant:
    """Behaviour invariant: visibility layer never changes draft count."""

    def test_drafts_created_for_kept_clients_only(self, db_path, audit_path):
        """One sales_doc dropped, one kept → exactly one draft created."""
        lines = [
            _line(sales_document_id="SD-DROP", client_name=""),
            _line(sales_document_id="SD-KEEP", client_name="ACME"),
        ]
        with _patch_sales_lines(lines), \
             _patch_lookup({"SD-DROP": "/fake/x.xlsx",
                            "SD-KEEP": "/fake/y.xlsx"}), \
             _patch_signals({}):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS6", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        # Visibility emits exactly one skip event (for SD-DROP)
        skip_events = [
            e for e in _events(audit_path)
            if e["event"] in (
                "proforma_draft_creation_pending_resolution",
                "proforma_draft_creation_skipped",
            )
        ]
        assert len(skip_events) == 1
        # And exactly one draft was created (for ACME, from SD-KEEP)
        assert result["created"] == 1
        assert result["synced"] == 0
        assert result["blocked"] == 0
        drafts = pildb.list_drafts_for_batch(db_path, "BVIS6")
        assert len(drafts) == 1
        assert drafts[0].client_name == "ACME"

    def test_all_empty_zero_drafts_still_emits_events(
        self, db_path, audit_path
    ):
        lines = [
            _line(sales_document_id="SD-1", client_name=""),
            _line(sales_document_id="SD-2", client_name=""),
        ]
        with _patch_sales_lines(lines), \
             _patch_lookup({"SD-1": "/fake/a.xlsx",
                            "SD-2": "/fake/b.xlsx"}), \
             _patch_signals({}):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS7", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        # Zero drafts (pre-PR behaviour preserved)
        assert result["created"] == 0
        assert result["synced"] == 0
        assert result["blocked"] == 0
        assert pildb.list_drafts_for_batch(db_path, "BVIS7") == []
        # Two skip events written (post-PR visibility)
        events = [
            e for e in _events(audit_path)
            if e["event"] == "proforma_draft_creation_skipped"
        ]
        assert len(events) == 2

    def test_lookup_failure_falls_back_to_skipped_with_no_signals(
        self, db_path, audit_path
    ):
        """Source file lookup miss → SKIPPED with empty signals (not crash)."""
        lines = [_line(sales_document_id="SD-MISSING", client_name="")]
        with _patch_sales_lines(lines), \
             _patch_lookup({}), \
             _patch_signals({}):
            result = sync_draft_from_packing_upload(
                batch_id="BVIS8", operator="packing_upload",
                db_path=db_path, audit_path=audit_path,
            )

        events = [
            e for e in _events(audit_path)
            if e["event"] == "proforma_draft_creation_skipped"
        ]
        assert len(events) == 1
        detail = events[0]["detail"]
        assert detail["source_file_path"] == ""
        assert detail["resolver_signals_seen"] == {
            "vat": None, "heading_candidate": None,
        }
        assert result["skipped_no_signal"] == 1
