"""Package C1 — Piece detail timeline enrichment + authority pins.

Tests that corrections and reversals appear in the unified timeline
returned by get_piece_detail(), with correct kind, sort order, and
summary text. Also pins the read-only authority of inventory_piece_view
(no writes) and verifies graceful degradation when a reader fails.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_piece_view as ipv  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────

def _state_row(scan_code="S1", state="WAREHOUSE_STOCK"):
    return {
        "id": "state-1", "scan_code": scan_code, "current_state": state,
        "product_code": "P1", "design_no": "D1", "batch_id": "B1",
        "created_at": "2026-05-01T09:00:00Z",
        "updated_at": "2026-05-12T10:00:00Z",
    }


def _correction_row(eid, created_at, ctype="identity",
                     old_pc="P1", new_pc="P2",
                     old_dn="D1", new_dn="D2",
                     old_bid="B1", new_bid="B1",
                     reason="typo", status="applied"):
    return {
        "id": eid, "scan_code": "S1", "correction_type": ctype,
        "old_product_code": old_pc, "new_product_code": new_pc,
        "old_design_no": old_dn, "new_design_no": new_dn,
        "old_batch_id": old_bid, "new_batch_id": new_bid,
        "reason": reason, "operator": "op", "status": status,
        "idempotency_key": "k-" + eid, "created_at": created_at,
    }


def _reversal_row(eid, created_at, from_state="SALES_TRANSIT",
                   to_state="WAREHOUSE_STOCK", reason="wrong dispatch",
                   reversal_type="transit"):
    return {
        "id": eid, "scan_code": "S1",
        "from_state": from_state, "to_state": to_state,
        "reversal_type": reversal_type, "reason": reason,
        "operator": "op", "original_event_id": "ev-orig",
        "notes": "", "created_at": created_at,
        "idempotency_key": "k-" + eid,
    }


def _archive_proposal_row(eid, created_at, status="proposed"):
    return _correction_row(
        eid, created_at, ctype="archive_proposal",
        old_pc="P1", new_pc="P1", old_dn="D1", new_dn="D1",
        old_bid="B1", new_bid="B1",
        reason="over-scan duplicate", status=status,
    )


def _lifecycle_event(eid, occurred_at, frm, to, trigger="warehouse_receive"):
    return {
        "id": eid, "scan_code": "S1",
        "from_state": frm, "to_state": to, "trigger": trigger,
        "occurred_at": occurred_at, "operator": "op", "note": "",
    }


def _all_empty(**overrides):
    defaults = dict(
        get_state=_state_row(),
        get_current_location=None,
        get_history=[], get_movement_history=[],
        get_sample_out_history=[], get_returns_history=[],
        get_corrections=[], get_reversals=[],
    )
    defaults.update(overrides)
    return defaults


def _patch_all(kw):
    import contextlib
    return contextlib.ExitStack()


@pytest.fixture
def _patch_readers():
    """Context-manager factory: patch all 8 readers from a dict."""
    from contextlib import ExitStack
    import unittest.mock as um

    def _go(**kw):
        d = _all_empty(**kw)
        stack = ExitStack()
        stack.enter_context(um.patch.object(
            ipv.inventory_state_engine, "get_state", return_value=d["get_state"]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_current_location", return_value=d["get_current_location"]))
        stack.enter_context(um.patch.object(
            ipv.inventory_state_engine, "get_history", return_value=d["get_history"]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_movement_history", return_value=d["get_movement_history"]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_sample_out_history", return_value=d["get_sample_out_history"]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_returns_history", return_value=d["get_returns_history"]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_corrections", return_value=d["get_corrections"]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_reversals", return_value=d["get_reversals"]))
        return stack

    return _go


# ── Timeline enrichment: corrections ─────────────────────────────────────

class TestCorrectionTimeline:

    def test_identity_correction_appears_in_timeline(self, _patch_readers):
        corr = [_correction_row("C1", "2026-05-13T10:00:00Z")]
        with _patch_readers(get_corrections=corr):
            d = ipv.get_piece_detail("S1")
        kinds = [e["kind"] for e in d["timeline"]]
        assert "correction" in kinds

    def test_correction_summary_shows_changed_fields(self, _patch_readers):
        corr = [_correction_row("C1", "2026-05-13T10:00:00Z",
                                 old_pc="OLD", new_pc="NEW",
                                 old_dn="D1", new_dn="D1")]
        with _patch_readers(get_corrections=corr):
            d = ipv.get_piece_detail("S1")
        c_evt = [e for e in d["timeline"] if e["kind"] == "correction"][0]
        assert "product_code: OLD -> NEW" in c_evt["summary"]
        assert "design_no" not in c_evt["summary"]

    def test_archive_proposal_summary(self, _patch_readers):
        corr = [_archive_proposal_row("A1", "2026-05-14T10:00:00Z")]
        with _patch_readers(get_corrections=corr):
            d = ipv.get_piece_detail("S1")
        c_evt = [e for e in d["timeline"] if e["kind"] == "correction"][0]
        assert "archive proposal" in c_evt["summary"]
        assert "proposed" in c_evt["summary"]

    def test_correction_detail_has_old_new_fields(self, _patch_readers):
        corr = [_correction_row("C1", "2026-05-13T10:00:00Z")]
        with _patch_readers(get_corrections=corr):
            d = ipv.get_piece_detail("S1")
        c_evt = [e for e in d["timeline"] if e["kind"] == "correction"][0]
        detail = c_evt["detail"]
        assert "old_product_code" in detail
        assert "new_product_code" in detail
        assert "correction_type" in detail

    def test_correction_uses_created_at_as_occurred_at(self, _patch_readers):
        ts = "2026-05-13T10:30:00Z"
        corr = [_correction_row("C1", ts)]
        with _patch_readers(get_corrections=corr):
            d = ipv.get_piece_detail("S1")
        c_evt = [e for e in d["timeline"] if e["kind"] == "correction"][0]
        assert c_evt["occurred_at"] == ts


# ── Timeline enrichment: reversals ───────────────────────────────────────

class TestReversalTimeline:

    def test_reversal_appears_in_timeline(self, _patch_readers):
        rev = [_reversal_row("R1", "2026-05-14T11:00:00Z")]
        with _patch_readers(get_reversals=rev):
            d = ipv.get_piece_detail("S1")
        kinds = [e["kind"] for e in d["timeline"]]
        assert "reversal" in kinds

    def test_reversal_summary_includes_states_and_reason(self, _patch_readers):
        rev = [_reversal_row("R1", "2026-05-14T11:00:00Z",
                              from_state="SALES_TRANSIT",
                              to_state="WAREHOUSE_STOCK",
                              reason="wrong dispatch")]
        with _patch_readers(get_reversals=rev):
            d = ipv.get_piece_detail("S1")
        r_evt = [e for e in d["timeline"] if e["kind"] == "reversal"][0]
        assert "SALES_TRANSIT" in r_evt["summary"]
        assert "WAREHOUSE_STOCK" in r_evt["summary"]
        assert "wrong dispatch" in r_evt["summary"]

    def test_reversal_detail_has_expected_fields(self, _patch_readers):
        rev = [_reversal_row("R1", "2026-05-14T11:00:00Z")]
        with _patch_readers(get_reversals=rev):
            d = ipv.get_piece_detail("S1")
        r_evt = [e for e in d["timeline"] if e["kind"] == "reversal"][0]
        detail = r_evt["detail"]
        for k in ("from_state", "to_state", "reversal_type", "reason",
                   "original_event_id"):
            assert k in detail, f"Missing detail key {k!r}"


# ── Sort order with corrections + reversals ──────────────────────────────

class TestTimelineSortOrder:

    def test_six_kinds_sorted_chronologically(self, _patch_readers):
        lc = [_lifecycle_event("L1", "2026-05-01T09:00:00Z", "", "PURCHASE_TRANSIT", "pz_generated")]
        corr = [_correction_row("C1", "2026-05-15T10:00:00Z")]
        rev = [_reversal_row("R1", "2026-05-20T10:00:00Z")]
        with _patch_readers(get_history=lc, get_corrections=corr, get_reversals=rev):
            d = ipv.get_piece_detail("S1")
        kinds = [e["kind"] for e in d["timeline"]]
        assert kinds == ["lifecycle", "correction", "reversal"]

    def test_same_timestamp_sorted_by_kind_priority(self, _patch_readers):
        ts = "2026-05-15T10:00:00Z"
        lc = [_lifecycle_event("L1", ts, "PURCHASE_TRANSIT", "WAREHOUSE_STOCK")]
        corr = [_correction_row("C1", ts)]
        rev = [_reversal_row("R1", ts)]
        with _patch_readers(get_history=lc, get_corrections=corr, get_reversals=rev):
            d = ipv.get_piece_detail("S1")
        kinds = [e["kind"] for e in d["timeline"]]
        assert kinds == ["lifecycle", "correction", "reversal"]


# ── Graceful degradation ─────────────────────────────────────────────────

class TestDegradation:

    def test_corrections_reader_failure_degrades_gracefully(self, _patch_readers):
        from contextlib import ExitStack
        import unittest.mock as um
        stack = ExitStack()
        stack.enter_context(um.patch.object(
            ipv.inventory_state_engine, "get_state", return_value=_state_row()))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_current_location", return_value=None))
        stack.enter_context(um.patch.object(
            ipv.inventory_state_engine, "get_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_movement_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_sample_out_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_returns_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_corrections",
            side_effect=RuntimeError("db locked")))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_reversals", return_value=[]))
        with stack:
            d = ipv.get_piece_detail("S1")
        assert d["degraded"] is True
        assert any("inventory_corrections" in lim for lim in d["limitations"])
        assert d["found"] is True

    def test_reversals_reader_failure_degrades_gracefully(self, _patch_readers):
        from contextlib import ExitStack
        import unittest.mock as um
        stack = ExitStack()
        stack.enter_context(um.patch.object(
            ipv.inventory_state_engine, "get_state", return_value=_state_row()))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_current_location", return_value=None))
        stack.enter_context(um.patch.object(
            ipv.inventory_state_engine, "get_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_movement_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_sample_out_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_returns_history", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_corrections", return_value=[]))
        stack.enter_context(um.patch.object(
            ipv.warehouse_db, "get_reversals",
            side_effect=RuntimeError("table missing")))
        with stack:
            d = ipv.get_piece_detail("S1")
        assert d["degraded"] is True
        assert any("inventory_reversals" in lim for lim in d["limitations"])
        assert d["found"] is True


# ── Authority pins ───────────────────────────────────────────────────────

class TestAuthorityPins:

    def test_piece_view_has_no_write_verbs(self):
        """inventory_piece_view must be read-only — no INSERT/UPDATE/DELETE."""
        src = inspect.getsource(ipv)
        for verb in ("INSERT", "UPDATE", "DELETE", "CREATE TABLE",
                      "ALTER TABLE", "DROP TABLE"):
            assert verb not in src, \
                f"inventory_piece_view.py contains write verb {verb!r}"

    def test_kind_priority_covers_all_six_kinds(self):
        expected = {"lifecycle", "movement", "sample", "returns",
                    "correction", "reversal"}
        assert set(ipv._KIND_PRIORITY.keys()) == expected

    def test_correction_entries_maps_created_at(self):
        row = _correction_row("C1", "2026-06-01T10:00:00Z")
        entries = ipv._correction_entries([row])
        assert len(entries) == 1
        assert entries[0]["occurred_at"] == "2026-06-01T10:00:00Z"
        assert entries[0]["kind"] == "correction"

    def test_reversal_entries_maps_created_at(self):
        row = _reversal_row("R1", "2026-06-02T10:00:00Z")
        entries = ipv._reversal_entries([row])
        assert len(entries) == 1
        assert entries[0]["occurred_at"] == "2026-06-02T10:00:00Z"
        assert entries[0]["kind"] == "reversal"

    def test_correction_summary_no_change_returns_generic(self):
        row = _correction_row("C1", "2026-06-01T10:00:00Z",
                               old_pc="P1", new_pc="P1",
                               old_dn="D1", new_dn="D1",
                               old_bid="B1", new_bid="B1",
                               ctype="identity")
        assert ipv._correction_summary(row) == "identity correction"

    def test_reversal_summary_without_from_state(self):
        row = _reversal_row("R1", "2026-06-01T10:00:00Z",
                             from_state="", to_state="WAREHOUSE_STOCK",
                             reason="")
        summary = ipv._reversal_summary(row)
        assert "-> WAREHOUSE_STOCK" in summary
        assert "reversal" in summary.lower()
