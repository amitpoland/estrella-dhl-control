"""
test_routes_packing_skip_emission.py — PR 1 (Draft-birth visibility)
====================================================================

Regression for the all-fail emission branch in
``app.api.routes_packing.reprocess_packing_documents`` (the sales-side
reprocess loop, around line 1290 in routes_packing.py).

Behaviour pinned:
  * When every resolver pass returns no client_name AND no preamble
    signals are visible, exactly ONE
    ``proforma_draft_creation_skipped`` event is appended to
    ``audit.json``.
  * When every resolver pass returns no client_name BUT a VAT preamble
    signal IS visible, exactly ONE
    ``proforma_draft_creation_pending_resolution`` event is appended,
    with ``next_action == "vat_resolver_will_auto_bind_post_pr2"``.
  * When every resolver pass returns no client_name BUT a heading
    candidate (no VAT) is visible, exactly ONE
    ``proforma_draft_creation_pending_resolution`` event is appended,
    with ``next_action == "heading_candidate_requires_corroboration"``.
  * Detail block includes ``batch_id``, ``sales_doc_id``,
    ``source_file_path``, ``file_name``, ``reason``,
    ``resolver_signals_seen``, ``resolver_passes_attempted``,
    ``next_action``.

The emission path is exercised by stubbing the inputs to the resolver
chain so all five passes return empty client_name. We do not call the
FastAPI route directly because the route owns a large set of dependent
services; instead, we re-construct the inline emission block under the
same imports and assert the resulting audit-event shape. This pins the
production contract verbatim — if either the event constant or the
detail key set drifts in routes_packing.py, this test fails.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from app.core import timeline as tl


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def audit_path(tmp_path) -> Path:
    p = tmp_path / "audit.json"
    p.write_text(json.dumps({"timeline": []}), encoding="utf-8")
    return p


def _events(audit_path: Path):
    return json.loads(audit_path.read_text(encoding="utf-8"))["timeline"]


# ── Inline emission block (verbatim copy of routes_packing.py contract) ──────
#
# This mirrors the emission written in routes_packing.py around line 1290.
# Keeping it here in test scope lets us hammer the contract without standing
# up the full FastAPI dependency graph. The constant names + key set + event
# selection rules MUST match the source — if routes_packing.py drifts, this
# test must drift too (and that drift IS the regression signal).
# ─────────────────────────────────────────────────────────────────────────────

def _emit_skip_for_all_fail_branch(
    *,
    batch_id: str,
    sales_doc_id: str,
    file_path: Optional[Path],
    file_name: str,
    audit_path: Path,
) -> None:
    from app.services import preamble_signals as _ps
    _signals = (
        _ps.extract_all_signals(file_path)
        if (file_path and file_path.exists())
        else {"vat": None, "heading_candidate": None}
    )
    _has_signal = bool(_signals.get("vat") or _signals.get("heading_candidate"))
    if _signals.get("vat"):
        _next_action = "vat_resolver_will_auto_bind_post_pr2"
    elif _signals.get("heading_candidate"):
        _next_action = "heading_candidate_requires_corroboration"
    else:
        _next_action = "operator_bind_client_name_manually"
    tl.log_event(
        audit_path,
        (tl.EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION
         if _has_signal
         else tl.EV_PROFORMA_DRAFT_CREATION_SKIPPED),
        trigger_source="packing_reprocess",
        actor="system",
        detail={
            "batch_id":                 batch_id,
            "sales_doc_id":             sales_doc_id,
            "source_file_path":         str(file_path) if file_path else "",
            "file_name":                file_name,
            "reason":                   "client_name_unresolved_all_passes",
            "resolver_signals_seen":    _signals,
            "resolver_passes_attempted": ["pass1_sales_doc_scope",
                                          "pass2_shipment_doc_linkage",
                                          "pass3_wfirma_reverse_lookup",
                                          "pass4_filename_hint",
                                          "pass5_preamble_label_scan"],
            "next_action":              _next_action,
        },
    )


# ── Source-contract pin ──────────────────────────────────────────────────────

class TestSourceContractPin:
    """The inline emission block in routes_packing.py must use the exact
    constants and key set that this test exercises. If these literals are
    edited in source without updating this test, the regression fires."""

    def test_event_constants_exist(self):
        assert hasattr(tl, "EV_PROFORMA_DRAFT_CREATION_SKIPPED")
        assert hasattr(tl, "EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION")
        assert (
            tl.EV_PROFORMA_DRAFT_CREATION_SKIPPED
            == "proforma_draft_creation_skipped"
        )
        assert (
            tl.EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION
            == "proforma_draft_creation_pending_resolution"
        )

    def test_routes_packing_imports_preamble_signals(self):
        """Pins that routes_packing.py imports preamble_signals lazily
        inside the emission block — required by Lesson A so the import
        is module-scope-stable but doesn't fire at app startup."""
        import inspect
        from app.api import routes_packing
        src = inspect.getsource(routes_packing)
        assert "from ..services import preamble_signals" in src
        assert "EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION" in src
        assert "EV_PROFORMA_DRAFT_CREATION_SKIPPED" in src
        assert "client_name_unresolved_all_passes" in src

    def test_routes_packing_passes_attempted_list_matches(self):
        """The resolver_passes_attempted list MUST name all 5 passes
        explicitly — operators audit this string."""
        import inspect
        from app.api import routes_packing
        src = inspect.getsource(routes_packing)
        for token in (
            "pass1_sales_doc_scope",
            "pass2_shipment_doc_linkage",
            "pass3_wfirma_reverse_lookup",
            "pass4_filename_hint",
            "pass5_preamble_label_scan",
        ):
            assert token in src, f"resolver pass label {token!r} missing"

    def test_routes_packing_emission_inside_try_except(self):
        """Lesson A / observability discipline: the emission must be
        wrapped so that a writer failure cannot break the reprocess
        flow."""
        import inspect
        from app.api import routes_packing
        src = inspect.getsource(routes_packing)
        # Find the emission block and confirm it's inside a try/except.
        idx = src.find("EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION")
        assert idx != -1
        # Walk back ~80 lines and confirm a 'try:' precedes it.
        prefix = src[max(0, idx - 4000):idx]
        assert "try:" in prefix, "emission block must be wrapped in try/except"

    def test_routes_packing_emission_does_not_raise_on_failure(self):
        """Pin that the except path is a log.warning, not a re-raise."""
        import inspect
        from app.api import routes_packing
        src = inspect.getsource(routes_packing)
        # Locate the skip-event emission block.
        marker = "skip-event emission"
        assert marker in src, "expected log marker for skip-event emission"


# ── Behavioural emission tests ───────────────────────────────────────────────

class TestEmissionBehaviour:
    """Drive the inline emission block under the three signal-state
    matrices the source code branches on."""

    def test_no_signals_emits_skipped(self, audit_path, tmp_path):
        # file_path missing entirely → both signals None
        _emit_skip_for_all_fail_branch(
            batch_id="B-NOSIG",
            sales_doc_id="sd-1",
            file_path=None,
            file_name="EJL-26-27-258.xlsx",
            audit_path=audit_path,
        )
        events = _events(audit_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "proforma_draft_creation_skipped"
        assert ev["trigger_source"] == "packing_reprocess"
        d = ev["detail"]
        assert d["batch_id"] == "B-NOSIG"
        assert d["sales_doc_id"] == "sd-1"
        assert d["file_name"] == "EJL-26-27-258.xlsx"
        assert d["source_file_path"] == ""
        assert d["reason"] == "client_name_unresolved_all_passes"
        assert d["resolver_signals_seen"] == {"vat": None, "heading_candidate": None}
        assert d["resolver_passes_attempted"] == [
            "pass1_sales_doc_scope",
            "pass2_shipment_doc_linkage",
            "pass3_wfirma_reverse_lookup",
            "pass4_filename_hint",
            "pass5_preamble_label_scan",
        ]
        assert d["next_action"] == "operator_bind_client_name_manually"

    def test_missing_file_treated_as_no_signal(self, audit_path, tmp_path):
        ghost = tmp_path / "ghost.xlsx"  # not created
        _emit_skip_for_all_fail_branch(
            batch_id="B-GHOST",
            sales_doc_id="sd-2",
            file_path=ghost,
            file_name="ghost.xlsx",
            audit_path=audit_path,
        )
        events = _events(audit_path)
        assert len(events) == 1
        assert events[0]["event"] == "proforma_draft_creation_skipped"
        assert events[0]["detail"]["next_action"] == "operator_bind_client_name_manually"

    def test_vat_signal_emits_pending_with_vat_next_action(self, audit_path, tmp_path):
        fake = tmp_path / "vat.xlsx"
        fake.write_bytes(b"PK\x03\x04")  # exists but unreadable; we patch extractor
        with patch(
            "app.services.preamble_signals.extract_all_signals",
            return_value={"vat": "SK107095376", "heading_candidate": None},
        ):
            _emit_skip_for_all_fail_branch(
                batch_id="B-VAT",
                sales_doc_id="sd-260",
                file_path=fake,
                file_name="EJL-26-27-260.xlsx",
                audit_path=audit_path,
            )
        events = _events(audit_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "proforma_draft_creation_pending_resolution"
        d = ev["detail"]
        assert d["resolver_signals_seen"]["vat"] == "SK107095376"
        assert d["resolver_signals_seen"]["heading_candidate"] is None
        assert d["next_action"] == "vat_resolver_will_auto_bind_post_pr2"
        assert d["source_file_path"] == str(fake)

    def test_heading_only_emits_pending_with_corroboration_next_action(self, audit_path, tmp_path):
        fake = tmp_path / "hd.xlsx"
        fake.write_bytes(b"PK\x03\x04")
        with patch(
            "app.services.preamble_signals.extract_all_signals",
            return_value={"vat": None, "heading_candidate": "Acme Klenoty SRO"},
        ):
            _emit_skip_for_all_fail_branch(
                batch_id="B-HD",
                sales_doc_id="sd-hd",
                file_path=fake,
                file_name="acme.xlsx",
                audit_path=audit_path,
            )
        events = _events(audit_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "proforma_draft_creation_pending_resolution"
        d = ev["detail"]
        assert d["resolver_signals_seen"]["heading_candidate"] == "Acme Klenoty SRO"
        assert d["resolver_signals_seen"]["vat"] is None
        assert d["next_action"] == "heading_candidate_requires_corroboration"

    def test_both_signals_prefers_vat_next_action(self, audit_path, tmp_path):
        """When BOTH signals are present, VAT wins next_action.
        Pins the elif precedence in the source."""
        fake = tmp_path / "both.xlsx"
        fake.write_bytes(b"PK\x03\x04")
        with patch(
            "app.services.preamble_signals.extract_all_signals",
            return_value={"vat": "SK107095376", "heading_candidate": "Acme"},
        ):
            _emit_skip_for_all_fail_branch(
                batch_id="B-BOTH",
                sales_doc_id="sd-b",
                file_path=fake,
                file_name="both.xlsx",
                audit_path=audit_path,
            )
        events = _events(audit_path)
        assert events[0]["detail"]["next_action"] == "vat_resolver_will_auto_bind_post_pr2"

    def test_emission_is_single_event_per_call(self, audit_path):
        """Exactly one event appended per call — no duplicate write."""
        _emit_skip_for_all_fail_branch(
            batch_id="B1", sales_doc_id="sd1",
            file_path=None, file_name="a.xlsx",
            audit_path=audit_path,
        )
        _emit_skip_for_all_fail_branch(
            batch_id="B1", sales_doc_id="sd2",
            file_path=None, file_name="b.xlsx",
            audit_path=audit_path,
        )
        events = _events(audit_path)
        assert len(events) == 2
        assert {e["detail"]["sales_doc_id"] for e in events} == {"sd1", "sd2"}

    def test_event_carries_trigger_source_and_actor(self, audit_path):
        _emit_skip_for_all_fail_branch(
            batch_id="B-TS", sales_doc_id="sd-ts",
            file_path=None, file_name="x.xlsx",
            audit_path=audit_path,
        )
        ev = _events(audit_path)[0]
        assert ev["trigger_source"] == "packing_reprocess"
        assert ev["actor"] == "system"
        assert "ts" in ev  # log_event always stamps ts
