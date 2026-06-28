# service/tests/test_wdt_series_authority.py
"""
Invoice series authority tests — Customer Master is the ONLY source.

Each context (WDT / domestic / export) reads from its own CM field.
Missing CM field blocks conversion before reaching wFirma.

Run: cd service && pytest tests/test_wdt_series_authority.py -v
"""
import pytest
from unittest.mock import MagicMock


OMARA_FV_SERIES     = "15827088"   # domestic / FV series
OMARA_WDT_SERIES    = "15827921"   # EU WDT series (Faktury WDT)
OMARA_EXPORT_SERIES = "15900001"   # non-EU export series (example)


def _make_cm(
    *,
    invoice_series=None,
    wdt_series=None,
    export_series=None,
    name="Test Customer",
):
    cm = MagicMock()
    cm.bill_to_name = name
    cm.bill_to_contractor_id = "99999999"
    cm.preferred_invoice_series_id = invoice_series
    cm.preferred_wdt_invoice_series_id = wdt_series
    cm.preferred_export_invoice_series_id = export_series
    return cm


# ── WDT context ──────────────────────────────────────────────────────────────

def test_wdt_context_reads_from_cm_wdt_field():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=OMARA_FV_SERIES, wdt_series=OMARA_WDT_SERIES)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="wdt")
    assert result == OMARA_WDT_SERIES


def test_wdt_context_must_not_return_fv_series():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=OMARA_FV_SERIES, wdt_series=OMARA_WDT_SERIES)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="wdt")
    assert result != OMARA_FV_SERIES, (
        f"WDT context must NOT return FV series {OMARA_FV_SERIES!r}, got {result!r}"
    )


def test_wdt_context_missing_cm_wdt_series_blocks():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=OMARA_FV_SERIES, wdt_series=None)
    with pytest.raises(ValueError, match="WDT invoice series not configured"):
        pick_invoice_series_id_for_vat_context(cm, vat_context="wdt")


# ── Domestic / FV context ────────────────────────────────────────────────────

def test_domestic_context_reads_from_cm_invoice_field():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=OMARA_FV_SERIES, wdt_series=OMARA_WDT_SERIES)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="domestic")
    assert result == OMARA_FV_SERIES


def test_domestic_context_missing_cm_series_blocks():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=None, wdt_series=OMARA_WDT_SERIES)
    with pytest.raises(ValueError, match="Domestic invoice series not configured"):
        pick_invoice_series_id_for_vat_context(cm, vat_context="domestic")


# ── Export context ───────────────────────────────────────────────────────────

def test_export_context_reads_from_cm_export_field():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=OMARA_FV_SERIES, export_series=OMARA_EXPORT_SERIES)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="export")
    assert result == OMARA_EXPORT_SERIES


def test_export_context_missing_cm_series_blocks():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=OMARA_FV_SERIES, export_series=None)
    with pytest.raises(ValueError, match="Export invoice series not configured"):
        pick_invoice_series_id_for_vat_context(cm, vat_context="export")


# ── Isolation: each context reads only its own field ─────────────────────────

def test_wdt_context_ignores_domestic_and_export_fields():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(
        invoice_series=OMARA_FV_SERIES,
        wdt_series=OMARA_WDT_SERIES,
        export_series=OMARA_EXPORT_SERIES,
    )
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="wdt")
    assert result == OMARA_WDT_SERIES
    assert result != OMARA_FV_SERIES
    assert result != OMARA_EXPORT_SERIES


def test_export_context_ignores_domestic_and_wdt_fields():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(
        invoice_series=OMARA_FV_SERIES,
        wdt_series=OMARA_WDT_SERIES,
        export_series=OMARA_EXPORT_SERIES,
    )
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="export")
    assert result == OMARA_EXPORT_SERIES
    assert result != OMARA_FV_SERIES
    assert result != OMARA_WDT_SERIES


def test_domestic_missing_does_not_fall_back_to_wdt():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_cm(invoice_series=None, wdt_series=OMARA_WDT_SERIES)
    with pytest.raises(ValueError):
        pick_invoice_series_id_for_vat_context(cm, vat_context="domestic")
