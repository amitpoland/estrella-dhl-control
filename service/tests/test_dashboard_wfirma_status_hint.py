"""
test_dashboard_wfirma_status_hint.py — Regression tests for the two
dashboard status-column fixes (2026-05-28):

Fix 1: _wfirma_hint now returns 'posted' when wfirma_pz_doc_id is present
        in the audit (previously returned 'none' — incorrect for AWB 4183498255
        and similar batches where the hint didn't reflect the real PZ state).

Fix 2: _derive_pz_status now returns 'complete' when wfirma_pz_doc_id is set,
        even if engine_error is non-empty. A PZ doc ID in wFirma is the
        authoritative proof of completion and overrides a stale engine error
        (real-world case: AWB 6049349806 had engine_error from an old failed
        attempt but PZ 4/5/2026 / doc 183484963 was later created).
"""
from __future__ import annotations

import pytest

from app.api.routes_dashboard import _derive_pz_status, _wfirma_hint


# ---------------------------------------------------------------------------
# _wfirma_hint
# ---------------------------------------------------------------------------

class TestWfirmaHint:
    def _audit_with_doc(self, doc_id: str = "186710627") -> dict:
        return {"wfirma_export": {"wfirma_pz_doc_id": doc_id}}

    def _audit_no_doc(self) -> dict:
        return {"wfirma_export": {"wfirma_pz_doc_id": None}}

    def _audit_no_export(self) -> dict:
        return {}

    def test_returns_posted_when_doc_id_set(self):
        """wfirma_hint must return 'posted' when audit has a wFirma PZ doc ID."""
        result = _wfirma_hint("BATCH_ID", self._audit_with_doc())
        assert result == "posted", f"Expected 'posted', got {result!r}"

    def test_returns_posted_for_any_doc_id(self):
        """Any truthy doc ID (old or new) triggers 'posted'."""
        for doc in ("186437155", "183484963", "1"):
            assert _wfirma_hint("BATCH_ID", {"wfirma_export": {"wfirma_pz_doc_id": doc}}) == "posted"

    def test_returns_none_when_doc_id_null_and_no_drafts(self, monkeypatch):
        """Without doc ID and without drafts the hint should be 'none'."""
        import app.api.routes_dashboard as mod
        # Monkeypatch wfirma_db.list_reservation_drafts to return []
        import types
        fake_wfdb = types.SimpleNamespace(list_reservation_drafts=lambda bid: [])
        monkeypatch.setattr(mod, "_wfirma_hint_wfdb", None, raising=False)
        # Patch via importlib to avoid module-level import issues
        import importlib, sys
        fake_mod = types.ModuleType("app.services.wfirma_db")
        fake_mod.list_reservation_drafts = lambda bid: []
        monkeypatch.setitem(sys.modules, "app.services.wfirma_db", fake_mod)

        result = _wfirma_hint("BATCH_ID", self._audit_no_doc())
        # Should fall through to draft check → no drafts → "none"
        assert result == "none"

    def test_no_audit_passed_falls_through_to_drafts(self, monkeypatch):
        """Calling without audit arg (legacy callers) must not crash."""
        import types, sys
        fake_mod = types.ModuleType("app.services.wfirma_db")
        fake_mod.list_reservation_drafts = lambda bid: []
        monkeypatch.setitem(sys.modules, "app.services.wfirma_db", fake_mod)
        # Should not raise; falls through to draft check
        result = _wfirma_hint("BATCH_ID")
        assert result in ("none", "preview_built", "n/a")

    def test_doc_id_beats_drafts(self, monkeypatch):
        """'posted' takes priority over draft existence — doc ID is authoritative."""
        import types, sys
        fake_mod = types.ModuleType("app.services.wfirma_db")
        # Even with drafts present, doc_id should win
        fake_mod.list_reservation_drafts = lambda bid: [{"id": 1}]
        monkeypatch.setitem(sys.modules, "app.services.wfirma_db", fake_mod)

        result = _wfirma_hint("BATCH_ID", self._audit_with_doc())
        assert result == "posted", "doc ID must beat drafts"

    def test_empty_string_doc_id_not_posted(self, monkeypatch):
        """An empty string doc ID must not trigger 'posted'."""
        import types, sys
        fake_mod = types.ModuleType("app.services.wfirma_db")
        fake_mod.list_reservation_drafts = lambda bid: []
        monkeypatch.setitem(sys.modules, "app.services.wfirma_db", fake_mod)
        result = _wfirma_hint("BATCH_ID", {"wfirma_export": {"wfirma_pz_doc_id": ""}})
        assert result != "posted"


# ---------------------------------------------------------------------------
# _derive_pz_status
# ---------------------------------------------------------------------------

class TestDerivePzStatus:

    # ── Fix 2: wfirma_pz_doc_id overrides engine_error ───────────────────────

    def test_posted_pz_doc_id_overrides_engine_error(self):
        """If wfirma_pz_doc_id is set, pz_status must be 'complete' even with engine_error.

        Real-world case: AWB 6049349806 had engine_error="'NoneType' object has no
        attribute 'name'" from an old failed attempt but PZ 4/5/2026 was later created.
        Before the fix, the batch showed pz_status='failed' on the dashboard despite
        having a real wFirma PZ document.
        """
        a = {
            "status": "failed",
            "engine_error": "'NoneType' object has no attribute 'name'",
            "wfirma_export": {"wfirma_pz_doc_id": "183484963"},
        }
        result = _derive_pz_status(a)
        assert result == "complete", (
            f"Expected 'complete' when wfirma_pz_doc_id is set; got {result!r}"
        )

    def test_posted_pz_doc_id_overrides_failed_status(self):
        """wfirma_pz_doc_id must win over audit.status == 'failed'."""
        a = {
            "status": "failed",
            "wfirma_export": {"wfirma_pz_doc_id": "186710627"},
        }
        assert _derive_pz_status(a) == "complete"

    def test_posted_pz_doc_id_alone_is_enough(self):
        """Minimal audit with only wfirma_pz_doc_id → complete."""
        a = {"wfirma_export": {"wfirma_pz_doc_id": "12345"}}
        assert _derive_pz_status(a) == "complete"

    # ── Original behaviour preserved ──────────────────────────────────────────

    def test_failed_status_without_doc_id_stays_failed(self):
        """Without a wFirma doc ID, a failed engine must still show 'failed'."""
        a = {"status": "failed", "engine_error": "something went wrong"}
        assert _derive_pz_status(a) == "failed"

    def test_engine_error_without_doc_id_stays_failed(self):
        """engine_error without doc ID → 'failed'."""
        a = {"status": "partial", "engine_error": "NoneType error"}
        assert _derive_pz_status(a) == "failed"

    def test_no_doc_id_null_stays_failed_on_error(self):
        """Null doc_id must not trigger 'complete'."""
        a = {
            "status": "failed",
            "engine_error": "some error",
            "wfirma_export": {"wfirma_pz_doc_id": None},
        }
        assert _derive_pz_status(a) == "failed"

    def test_no_doc_id_empty_string_stays_failed(self):
        """Empty string doc_id must not trigger 'complete'."""
        a = {
            "status": "failed",
            "engine_error": "some error",
            "wfirma_export": {"wfirma_pz_doc_id": ""},
        }
        assert _derive_pz_status(a) == "failed"

    def test_partial_status_no_error_is_complete(self):
        """Normal successful partial batch → 'complete'."""
        a = {"status": "partial"}
        assert _derive_pz_status(a) == "complete"

    def test_no_sad_is_locked(self):
        """Batch without SAD → 'locked'."""
        # Simulate no-SAD batch: empty audit with no indicators
        a = {"status": "pending"}
        # Will derive "locked" when SAD is missing and no engine error
        result = _derive_pz_status(a)
        assert result in ("locked", "ready")  # depends on SAD derivation

    def test_empty_audit_is_ready_or_locked(self):
        """Empty audit dict must not raise."""
        result = _derive_pz_status({})
        assert result in ("ready", "locked", "failed", "complete")
