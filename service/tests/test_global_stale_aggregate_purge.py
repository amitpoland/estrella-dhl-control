"""test_global_stale_aggregate_purge.py

Pins the stale-aggregate audit cache purge that closes the Global
Jewellery clearance loop.

Production state observed for SHIPMENT_4789974092_2026-05_999deef1
BEFORE this fix:

    audit["rows"] = [
       {"product_code":"GLOBAL Invoice-AGG-PCS","description":"PCS, grouped invoice aggregate from global_jewellery (GLOBAL Invoice.pdf)",...},
       {"product_code":"GLOBAL Invoice-AGG-PRS","description":"PRS, grouped invoice aggregate from global_jewellery (GLOBAL Invoice.pdf)",...},
    ]
    audit["_rows_source"] = "synthesized_from_invoice_aggregates"

These 2 rows pre-date PR #259's packing-first authority. The
idempotency-on-rows guard in _inject_rows_from_packing_lines was
preventing the rebuild from packing_lines, so Polish Description
generation kept emitting UNKNOWN / metal szlachetny / grouped
invoice aggregate even after PR #258 populated 245 packing_lines.

Fix:
  - _audit_rows_are_stale_aggregate() detects the 3 stale-row markers
  - _purge_stale_audit_rows() evicts rows + source metadata in-place
  - _inject_rows_from_packing_lines() invokes purge for Global supplier
    BEFORE the idempotency check
  - /generate-description?force=true exposes the same purge to the
    operator for manual cache clearing on any batch

The reconciliation guard is unchanged. Estrella EJL chain is unchanged
(non-Global suppliers bypass the purge entirely).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


_ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_dhl_clearance.py"
)


# ── Helper functions exist ────────────────────────────────────────────────


def test_stale_aggregate_detector_exists():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "def _audit_rows_are_stale_aggregate(" in src


def test_purge_helper_exists():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "def _purge_stale_audit_rows(" in src


def test_stale_aggregate_markers_complete():
    """Three markers must be detected: _rows_source, product_code suffix,
    and 'grouped invoice aggregate' description fragment."""
    src = _ROUTES.read_text(encoding="utf-8")
    for marker in ('"synthesized_from_invoice_aggregates"',
                   '"grouped invoice aggregate"',
                   '"-AGG-PCS"',
                   '"-AGG-PRS"'):
        assert marker in src, f"marker {marker!r} missing from _STALE_AGGREGATE_MARKERS"


# ── _audit_rows_are_stale_aggregate behaviour ────────────────────────────


def test_detector_fires_on_rows_source_marker():
    from app.api.routes_dhl_clearance import _audit_rows_are_stale_aggregate
    audit = {
        "_rows_source": "synthesized_from_invoice_aggregates",
        "rows": [{"product_code": "anything", "description": "anything"}],
    }
    assert _audit_rows_are_stale_aggregate(audit) is True


def test_detector_fires_on_product_code_suffix():
    """The production audit had product_code='GLOBAL Invoice-AGG-PCS' /
    '...AGG-PRS' from the synthesizer."""
    from app.api.routes_dhl_clearance import _audit_rows_are_stale_aggregate
    audit = {
        "rows": [
            {"product_code": "GLOBAL Invoice-AGG-PCS",
             "description": "PCS, …", "quantity": 183.0, "line_total": 2369.29},
            {"product_code": "GLOBAL Invoice-AGG-PRS",
             "description": "PRS, …", "quantity": 62.0,  "line_total":  802.71},
        ],
    }
    assert _audit_rows_are_stale_aggregate(audit) is True


def test_detector_fires_on_description_marker():
    """Description literal 'grouped invoice aggregate' is the C27.2
    synthesizer fingerprint."""
    from app.api.routes_dhl_clearance import _audit_rows_are_stale_aggregate
    audit = {"rows": [{"product_code": "X", "description":
                       "PCS, grouped invoice aggregate from global_jewellery (X.pdf)"}]}
    assert _audit_rows_are_stale_aggregate(audit) is True


def test_detector_returns_false_for_real_packing_rows():
    """Rows from packing_lines (PR #259 step 0) must NOT be detected as
    stale — they're the real customs row source."""
    from app.api.routes_dhl_clearance import _audit_rows_are_stale_aggregate
    audit = {
        "_rows_source": "packing_lines",
        "rows": [
            {"product_code": "088/2026-2027-1",
             "description": "09KT Gold Plain Jewellery BRACELET",
             "polish_customs_description": "Bransoletka ze złota próby 375",
             "item_type": "BRACELET", "quantity": 1.0, "line_total": 232.0},
        ],
    }
    assert _audit_rows_are_stale_aggregate(audit) is False


def test_detector_returns_false_for_empty_audit():
    from app.api.routes_dhl_clearance import _audit_rows_are_stale_aggregate
    assert _audit_rows_are_stale_aggregate({}) is False
    assert _audit_rows_are_stale_aggregate({"rows": []}) is False


# ── _purge_stale_audit_rows behaviour ────────────────────────────────────


def test_purge_clears_rows_and_source_markers():
    from app.api.routes_dhl_clearance import _purge_stale_audit_rows
    audit = {
        "batch_id": "X",
        "rows": [{"product_code": "X-AGG-PCS"}],
        "_rows_source": "synthesized_from_invoice_aggregates",
        "_rows_row_count": 2,
        "_global_packing_present_but_empty": True,
        "invoice_totals": {"total_fob_usd": 3172.0},  # untouched
    }
    _purge_stale_audit_rows(audit)
    assert "rows" not in audit
    assert "_rows_source" not in audit
    assert "_rows_row_count" not in audit
    assert "_global_packing_present_but_empty" not in audit
    # Financial truth is preserved
    assert audit["invoice_totals"]["total_fob_usd"] == 3172.0
    assert audit["batch_id"] == "X"


def test_purge_is_idempotent_on_empty_audit():
    """Calling purge on an audit that has no row-cache must not raise
    or corrupt other fields."""
    from app.api.routes_dhl_clearance import _purge_stale_audit_rows
    audit = {"batch_id": "X", "invoice_totals": {"total_fob_usd": 100.0}}
    _purge_stale_audit_rows(audit)
    assert audit == {"batch_id": "X",
                     "invoice_totals": {"total_fob_usd": 100.0}}


# ── Integration: purge runs inside _inject_rows_from_packing_lines ───────


def test_packing_injection_purges_stale_aggregate_for_global(monkeypatch):
    """A Global batch with stale 2-row aggregate cache must have those
    rows purged so the chain can rebuild from packing_lines.

    Strategy: patch _detect_global_supplier_for_batch to return True so
    we exercise the Global branch deterministically (the on-disk PDF
    detector requires real pdfplumber-parseable files)."""
    import app.api.routes_dhl_clearance as _mod
    monkeypatch.setattr(_mod, "_detect_global_supplier_for_batch",
                        lambda batch_id: True)
    # Also short-circuit packing_db so no real DB is touched
    monkeypatch.setattr(
        "app.services.packing_db.get_packing_lines_for_batch",
        lambda batch_id: [],
        raising=False,
    )

    audit = {
        "batch_id": "TESTBATCH_STALE_GLOBAL",
        "_rows_source": "synthesized_from_invoice_aggregates",
        "rows": [
            {"product_code": "GLOBAL Invoice-AGG-PCS",
             "description": "PCS, grouped invoice aggregate"},
            {"product_code": "GLOBAL Invoice-AGG-PRS",
             "description": "PRS, grouped invoice aggregate"},
        ],
        "_rows_row_count": 2,
    }

    out = _mod._inject_rows_from_packing_lines(
        "TESTBATCH_STALE_GLOBAL", audit,
    )
    # Stale rows must be gone
    assert not out.get("rows"), (
        f"stale rows survived: {out.get('rows')}"
    )
    assert out.get("_rows_source") != "synthesized_from_invoice_aggregates"


def test_packing_injection_does_not_purge_for_non_global(monkeypatch):
    """Estrella EJL audit cache MUST be preserved — purge only applies
    to Global supplier."""
    import app.api.routes_dhl_clearance as _mod
    monkeypatch.setattr(_mod, "_detect_global_supplier_for_batch",
                        lambda batch_id: False)

    estrella_rows = [
        {"product_code": "EJL/26-27/180-1",
         "description": "PCS, 18KT Gold, Plain Jewellery PEND.",
         "quantity": 5.0, "line_total": 116.0},
    ]
    audit = {
        "batch_id": "TESTBATCH_ESTRELLA",
        "_rows_source": "db_invoice_lines",
        "rows": list(estrella_rows),
    }
    out = _mod._inject_rows_from_packing_lines("TESTBATCH_ESTRELLA", audit)
    # Estrella cache preserved untouched
    assert out["rows"] == estrella_rows
    assert out["_rows_source"] == "db_invoice_lines"


# ── /generate-description?force=true endpoint contract ────────────────────


def test_generate_description_endpoint_accepts_force_param():
    """The route signature must expose `force: bool = False` so the UI
    can force-regenerate by clearing the row cache before rebuild."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    assert idx >= 0
    sig = src[idx : idx + 600]
    assert "force: bool = False" in sig, (
        "force parameter missing from generate_description signature"
    )


def test_generate_description_force_calls_purge():
    """The force=True branch must call _purge_stale_audit_rows so the
    chain rebuilds from source."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    body = src[idx : idx + 3000]
    assert "if force:" in body
    assert "_purge_stale_audit_rows" in body, (
        "force=True branch must call _purge_stale_audit_rows"
    )


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_purge_does_not_touch_fiscal_or_invoice_totals_fields():
    """The purge helper must NOT remove invoice_totals, dhl_precheck,
    verification, clearance_decision, or any fiscal field. Only the
    row-cache + source markers."""
    from app.api.routes_dhl_clearance import _purge_stale_audit_rows
    audit = {
        "rows": [{"x": 1}],
        "_rows_source": "synthesized_from_invoice_aggregates",
        "invoice_totals": {"total_fob_usd": 3172.0, "total_cif_usd": 3322.0},
        "verification": {"invoice_cif_total_usd": 3322.0},
        "dhl_precheck": {"completed_at": "X"},
        "clearance_decision": {"clearance_path": "X"},
        "polish_desc_filename": "POLISH_DESC_X.pdf",
    }
    _purge_stale_audit_rows(audit)
    assert audit["invoice_totals"]["total_fob_usd"] == 3172.0
    assert audit["invoice_totals"]["total_cif_usd"] == 3322.0
    assert audit["verification"]["invoice_cif_total_usd"] == 3322.0
    assert audit["dhl_precheck"]["completed_at"] == "X"
    assert audit["clearance_decision"]["clearance_path"] == "X"
    assert audit["polish_desc_filename"] == "POLISH_DESC_X.pdf"
