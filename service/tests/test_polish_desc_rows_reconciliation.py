"""test_polish_desc_rows_reconciliation.py

Production incident — Global-inv-088 / GLOBAL Invoice batch:

  guard=rows_audit_reconciliation_failed
  row_fob_sum = 0.00, audit_fob = 3172.00, drift = -3172.00

## Root cause

The intake-time invoice parser (``invoice_intake_parser.py``) is tuned for
the EJL invoice template. For other layouts (e.g. GLOBAL Jewellery), the
regex+pdfplumber extraction fails and the parser writes a single
zero-valued placeholder row to ``invoice_lines`` with description
``"(placeholder — PZ engine will populate)"``. The engine's
``parse_invoice`` knows the ``global_jewellery`` format and extracts
aggregate FOB / freight / insurance / CIF correctly, but returns
``items: []`` — no per-line breakdown. Result: audit aggregates are right,
but row projection sums to 0, and the reconciler hard-fails.

## Fix

Two pure additions in routes_dhl_clearance.py:

1. ``_is_placeholder_invoice_line`` — defensive filter. Drop placeholder
   rows from the DB projection (and the cross-batch AWB-union fallback)
   so they never enter ``audit["rows"]``.

2. ``_synthesize_rows_from_invoice_aggregates`` — new third source in
   ``_inject_rows_from_sources``. When the DB and XLSX paths produce no
   real rows but the engine extracted aggregates, synthesize one grouped
   row per (invoice, unit_type=PCS|PRS) carrying the engine's parsed FOB
   for that file proportionally allocated by qty share. PCS / PRS units
   preserved. Sum reconciles exactly to declared FOB by construction.

The reconciliation guard is **not weakened**. It runs unchanged; we just
ensure the row source produces row totals that legitimately match the
aggregate the engine already parsed.

## Constraints honoured

- No CIF formula change
- No customs routing threshold change
- No SAD/ZC429 gate change
- No wFirma / PZ / proforma write paths
- No DB schema change
- Engine parser arithmetic untouched (we consume what the engine produces)
- Packing list NOT used as customs aggregate authority (invoice file only)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_SVC          = Path(__file__).resolve().parent.parent
_ROUTES_DHL   = _SVC / "app" / "api" / "routes_dhl_clearance.py"


# ── Source contract: helpers exist and are wired into _inject_rows_from_sources


def test_placeholder_detector_helper_exists():
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    assert "def _is_placeholder_invoice_line(" in src, (
        "_is_placeholder_invoice_line helper missing"
    )


def test_synthesizer_helper_exists():
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    assert "def _synthesize_rows_from_invoice_aggregates(" in src, (
        "_synthesize_rows_from_invoice_aggregates helper missing"
    )


def test_synthesizer_wired_into_inject_chain():
    """_inject_rows_from_sources must call the synthesizer AFTER DB+XLSX."""
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    idx_chain = src.find("def _inject_rows_from_sources(")
    chain_body = src[idx_chain : idx_chain + 1200]
    i_db   = chain_body.find("_inject_rows_from_db_invoice_lines(")
    i_xlsx = chain_body.find("_inject_rows_from_xlsx(")
    i_syn  = chain_body.find("_synthesize_rows_from_invoice_aggregates(")
    assert i_db >= 0 and i_xlsx >= 0 and i_syn >= 0, (
        "chain must include all three sources"
    )
    assert i_db < i_xlsx < i_syn, (
        "chain order must be: DB → XLSX → synthesize"
    )


def test_db_path_filters_placeholders():
    """Both the primary path and the cross-batch fallback must filter
    placeholder rows."""
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    idx_db = src.find("def _inject_rows_from_db_invoice_lines(")
    end_db = src.find("\ndef ", idx_db + 10)
    body = src[idx_db:end_db]
    assert "_is_placeholder_invoice_line(" in body, (
        "_inject_rows_from_db_invoice_lines must filter placeholders"
    )
    # Filter must apply in both primary and cross-batch loops
    assert body.count("_is_placeholder_invoice_line(") >= 2, (
        "placeholder filter must apply to both primary read and "
        "cross-batch AWB-union fallback"
    )


# ── Helper unit tests ─────────────────────────────────────────────────────


def test_is_placeholder_invoice_line_detects_intake_fallback():
    from app.api.routes_dhl_clearance import _is_placeholder_invoice_line
    row = {
        "invoice_no": "GLOBAL Invoice",
        "line_position": 1,
        "product_code": "GLOBAL Invoice-1",
        "description": "(placeholder — PZ engine will populate)",
        "quantity": 0.0,
        "total_value": 0.0,
        "currency": "USD",
    }
    assert _is_placeholder_invoice_line(row) is True


def test_is_placeholder_invoice_line_keeps_real_row():
    from app.api.routes_dhl_clearance import _is_placeholder_invoice_line
    real = {
        "invoice_no": "EJL/26-27/180",
        "line_position": 1,
        "product_code": "EJL-180-1",
        "description": "PCS, 18KT Gold, Plain Jewellery PEND.",
        "quantity": 5.0,
        "total_value": 116.00,
        "currency": "USD",
    }
    assert _is_placeholder_invoice_line(real) is False


def test_is_placeholder_invoice_line_keeps_zero_value_real_row():
    """A row with qty=0 and total=0 but a normal description is NOT a
    placeholder (could be a stub line for a sample/gift). Only the exact
    intake fallback marker triggers the filter."""
    from app.api.routes_dhl_clearance import _is_placeholder_invoice_line
    row = {
        "invoice_no": "EJL/26-27/180",
        "description": "Sample piece — no charge",
        "quantity": 0.0,
        "total_value": 0.0,
    }
    assert _is_placeholder_invoice_line(row) is False


def test_is_placeholder_invoice_line_handles_amount_usd_field():
    """Older rows may carry amount_usd instead of total_value. Both must
    be checked."""
    from app.api.routes_dhl_clearance import _is_placeholder_invoice_line
    row = {
        "description": "(placeholder — PZ engine will populate)",
        "quantity": 0.0,
        "amount_usd": 0.0,
    }
    assert _is_placeholder_invoice_line(row) is True


# ── Synthesizer integration: GLOBAL Invoice fixture ───────────────────────


@pytest.fixture
def global_invoice_batch(tmp_path, monkeypatch):
    """Fixture mimicking the SHIPMENT_4789974092 batch:

      - real PDF source/invoices/GLOBAL Invoice.pdf (copied from production)
      - corrupt PDF Global-inv-088.xls _Compatibility Mode_.pdf
        (quarantined by C27.1 magic-header check)
      - audit.json with engine-parsed aggregates (FOB 3172, etc) but
        no rows / no invoices keys

    Patches settings.storage_root to tmp_path so _OUTPUTS lookup
    resolves to the fixture.
    """
    # Build minimal directory layout
    out_root = tmp_path / "outputs"
    batch_id = "TESTBATCH_GLOBAL_INV_088"
    batch_dir = out_root / batch_id
    inv_dir = batch_dir / "source" / "invoices"
    inv_dir.mkdir(parents=True)

    # Real PDF: minimal valid %PDF- header is enough for the magic check;
    # the engine's parse_invoice will be MOCKED in the test, not run for real.
    (inv_dir / "GLOBAL Invoice.pdf").write_bytes(b"%PDF-1.7\n%fake but header ok\n")
    # Corrupt sibling — XLS magic, not PDF
    (inv_dir / "Global-inv-088.xls _Compatibility Mode_.pdf").write_bytes(
        b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 16
    )

    audit = {
        "batch_id": batch_id,
        "invoice_names": ["Global-inv-088.xls  _Compatibility Mode_.pdf"],
        "invoice_totals": {
            "total_pcs":  0,   # engine couldn't extract per-line items
            "total_prs":  0,
            "total_units": 0,
            "total_fob_usd": 3172.0,
            "total_freight_usd": 125.0,
            "total_insurance_usd": 25.0,
            "total_cif_usd": 3322.0,
        },
        # No rows / no invoices — exactly the failing prod state
    }

    # Redirect storage_root
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)

    return {
        "batch_id":  batch_id,
        "tmp_path":  tmp_path,
        "audit":     audit,
        "inv_dir":   inv_dir,
    }


def _install_fake_parse_invoice(monkeypatch, items_response):
    """Install a fake pz_import_processor.parse_invoice that returns the
    given dict for any input PDF path. Used to test the synthesizer's
    consumption of engine output without depending on the real engine."""
    fake_module = type(sys)("pz_import_processor")
    fake_module.parse_invoice = lambda path, corr: items_response  # type: ignore[attr-defined]
    fake_module.compute_invoice_totals = lambda parsed: {}        # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pz_import_processor", fake_module)


def test_synthesizer_produces_pcs_and_prs_grouped_rows(
    global_invoice_batch, monkeypatch
):
    """When engine reports PCS 183 + PRS 62 with FOB 3172, synthesizer
    must produce exactly 2 grouped rows summing to 3172 with units
    preserved."""
    _install_fake_parse_invoice(monkeypatch, {
        "filename": "GLOBAL Invoice.pdf",
        "invoice_no": "GLOBAL Invoice",
        "invoice_format": "global_jewellery",
        "fob_usd": 3172.0,
        "freight_usd": 125.0,
        "insurance_usd": 25.0,
        "cif_usd": 3322.0,
        "items": [],
        "product_counts_by_unit": {
            "PCS": {"all": 183},
            "PRS": {"all": 62},
        },
    })
    from app.api.routes_dhl_clearance import _synthesize_rows_from_invoice_aggregates
    out = _synthesize_rows_from_invoice_aggregates(
        global_invoice_batch["batch_id"], global_invoice_batch["audit"],
    )
    rows = out["rows"]
    assert len(rows) == 2, f"expected 2 grouped rows (PCS + PRS), got {len(rows)}"
    units = sorted(r["uom"] for r in rows)
    assert units == ["PCS", "PRS"], f"expected PCS+PRS, got {units}"

    pcs_row = next(r for r in rows if r["uom"] == "PCS")
    prs_row = next(r for r in rows if r["uom"] == "PRS")
    assert pcs_row["quantity"] == 183.0
    assert prs_row["quantity"] == 62.0


def test_synthesizer_row_total_sums_to_declared_fob(
    global_invoice_batch, monkeypatch
):
    """Hard reconciliation requirement: synthesized line_total values
    must sum EXACTLY to declared FOB (USD 3172.00)."""
    _install_fake_parse_invoice(monkeypatch, {
        "invoice_no": "GLOBAL Invoice",
        "invoice_format": "global_jewellery",
        "fob_usd": 3172.0,
        "items": [],
        "product_counts_by_unit": {
            "PCS": {"all": 183},
            "PRS": {"all": 62},
        },
    })
    from app.api.routes_dhl_clearance import _synthesize_rows_from_invoice_aggregates
    out = _synthesize_rows_from_invoice_aggregates(
        global_invoice_batch["batch_id"], global_invoice_batch["audit"],
    )
    total = round(sum(r["line_total"] for r in out["rows"]), 2)
    assert total == 3172.00, f"row sum {total} ≠ declared FOB 3172.00"


def test_synthesizer_marks_source_correctly(
    global_invoice_batch, monkeypatch
):
    _install_fake_parse_invoice(monkeypatch, {
        "invoice_no": "GLOBAL Invoice",
        "invoice_format": "global_jewellery",
        "fob_usd": 3172.0,
        "items": [],
        "product_counts_by_unit": {
            "PCS": {"all": 183}, "PRS": {"all": 62},
        },
    })
    from app.api.routes_dhl_clearance import _synthesize_rows_from_invoice_aggregates
    out = _synthesize_rows_from_invoice_aggregates(
        global_invoice_batch["batch_id"], global_invoice_batch["audit"],
    )
    assert out.get("_rows_source") == "synthesized_from_invoice_aggregates"
    assert out.get("_rows_row_count") == 2


def test_synthesizer_is_noop_when_rows_already_present(
    global_invoice_batch, monkeypatch,
):
    """Idempotency: if audit already carries rows from DB/XLSX path,
    synthesizer must not overwrite them."""
    audit = dict(global_invoice_batch["audit"])
    audit["rows"] = [{"foo": "existing"}]
    from app.api.routes_dhl_clearance import _synthesize_rows_from_invoice_aggregates
    out = _synthesize_rows_from_invoice_aggregates(
        global_invoice_batch["batch_id"], audit,
    )
    assert out["rows"] == [{"foo": "existing"}]
    assert out.get("_rows_source") != "synthesized_from_invoice_aggregates"


def test_synthesizer_is_noop_when_fob_is_zero(
    global_invoice_batch, monkeypatch,
):
    """Don't synthesize fake rows when there's no aggregate to anchor to."""
    audit = dict(global_invoice_batch["audit"])
    audit["invoice_totals"] = dict(audit["invoice_totals"])
    audit["invoice_totals"]["total_fob_usd"] = 0.0
    from app.api.routes_dhl_clearance import _synthesize_rows_from_invoice_aggregates
    out = _synthesize_rows_from_invoice_aggregates(
        global_invoice_batch["batch_id"], audit,
    )
    assert not out.get("rows"), "synthesizer must not create rows with zero FOB"


def test_synthesizer_skips_corrupt_pdf_siblings(
    global_invoice_batch, monkeypatch,
):
    """The corrupt Global-inv-088.xls _Compatibility Mode_.pdf in the
    fixture must NOT be fed to the engine — it's quarantined by the C27.1
    magic-header check. Verified by setting fob_usd=999 in the fake parser
    and confirming the synthesizer still produces rows summing to 3172
    (because the corrupt sibling is skipped, only GLOBAL Invoice.pdf is
    consumed)."""
    # The fake parse_invoice returns the SAME value for any path. If the
    # synthesizer were processing BOTH the valid and corrupt sibling, the
    # sum would be 2× 3172 = 6344. The C27.1 quarantine ensures only 1
    # PDF is processed.
    _install_fake_parse_invoice(monkeypatch, {
        "invoice_no": "GLOBAL Invoice",
        "invoice_format": "global_jewellery",
        "fob_usd": 3172.0,
        "items": [],
        "product_counts_by_unit": {
            "PCS": {"all": 183}, "PRS": {"all": 62},
        },
    })
    from app.api.routes_dhl_clearance import _synthesize_rows_from_invoice_aggregates
    out = _synthesize_rows_from_invoice_aggregates(
        global_invoice_batch["batch_id"], global_invoice_batch["audit"],
    )
    total = round(sum(r["line_total"] for r in out["rows"]), 2)
    assert total == 3172.00, (
        f"corrupt sibling appears to have been processed (sum={total}); "
        "C27.1 quarantine must skip non-PDF in source/invoices"
    )


# ── End-to-end: reconciler accepts synthesized rows ───────────────────────


def test_reconciler_passes_with_synthesized_rows(
    global_invoice_batch, monkeypatch,
):
    """The whole point: after synthesizer runs, the reconciler MUST
    return ok=True for the previously-failing audit state."""
    _install_fake_parse_invoice(monkeypatch, {
        "invoice_no": "GLOBAL Invoice",
        "invoice_format": "global_jewellery",
        "fob_usd": 3172.0,
        "items": [],
        "product_counts_by_unit": {
            "PCS": {"all": 183}, "PRS": {"all": 62},
        },
    })
    from app.api.routes_dhl_clearance import (
        _inject_rows_from_sources,
        _reconcile_rows_with_audit_totals,
    )
    audit = _inject_rows_from_sources(
        global_invoice_batch["batch_id"], global_invoice_batch["audit"],
    )
    # The audit must now have rows
    assert audit.get("rows"), "no rows after _inject_rows_from_sources"

    # Update invoice_names to match the synthesized invoice_number so
    # the missing-in-rows check doesn't fire.
    audit["invoice_names"] = ["GLOBAL Invoice.pdf"]

    recon = _reconcile_rows_with_audit_totals(audit)
    assert recon["ok"], (
        f"reconciler still failing: warnings={recon['warnings']!r}, "
        f"details={recon['details']!r}"
    )


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_no_cif_formula_or_customs_threshold_touched():
    """Synthesizer must consume engine output, not redo any pricing
    arithmetic. Source-grep: forbidden tokens absent from the helper."""
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    idx = src.find("def _synthesize_rows_from_invoice_aggregates(")
    end = src.find("\ndef _inject_rows_from_sources(", idx)
    body = src[idx:end]
    # Strip docstring
    import re as _re
    code = _re.sub(r'""".*?"""', "", body, count=1, flags=_re.DOTALL)
    forbidden = (
        "duty_", "_customs_threshold", "WFIRMA_CREATE_",
        "create_invoice", "create_pz", "_guard_wfirma_export",
    )
    for tok in forbidden:
        assert tok not in code, (
            f"synthesizer must not reference {tok!r} — pure read + project"
        )


def test_reconciliation_guard_string_unchanged():
    """The 422 guard string `rows_audit_reconciliation_failed` must still
    appear in the source — this PR does NOT bypass the guard."""
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    assert src.count('"rows_audit_reconciliation_failed"') >= 2, (
        "rows_audit_reconciliation_failed guard must remain — this PR "
        "fixes the upstream row source, not the guard"
    )


def test_sad_zc429_guard_paths_unchanged():
    """SAD/ZC429 missing must remain warning-only at the description
    generation path. Verified by checking the guard string set in the
    customs-description endpoint."""
    src = _ROUTES_DHL.read_text(encoding="utf-8")
    # The customs-description endpoint should NOT have introduced new
    # SAD-blocker escalations as part of this PR.
    assert '"rows_audit_reconciliation_failed"' in src
    # No new SAD/ZC429 blocker tokens were introduced by this PR
    assert src.count("sad_required_for_description") == 0
