# service/tests/test_wdt_series_authority.py
"""
Tests for WDT invoice series authority.
These tests MUST FAIL before the fix is applied (Task 6).
Run: cd service && pytest tests/test_wdt_series_authority.py -v
"""
import pytest
from unittest.mock import MagicMock


OMARA_WDT_SERIES_ID = "15827921"   # WDT series in wFirma
OMARA_FV_SERIES_ID  = "15827088"   # Generic FV series — must NOT be used for WDT


def _make_customer_master(invoice_series_id=OMARA_FV_SERIES_ID):
    cm = MagicMock()
    cm.preferred_invoice_series_id = invoice_series_id
    cm.vat_mode = 228
    cm.country = "CZ"
    cm.vat_eu_valid = True
    return cm


def test_wdt_context_must_not_use_fv_series():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_customer_master(invoice_series_id=OMARA_FV_SERIES_ID)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="wdt",
                                                     wdt_series_id=OMARA_WDT_SERIES_ID)
    assert result != OMARA_FV_SERIES_ID, (
        f"WDT context must not return FV series {OMARA_FV_SERIES_ID}, got {result!r}"
    )


def test_wdt_context_returns_wdt_series():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_customer_master(invoice_series_id=OMARA_FV_SERIES_ID)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="wdt",
                                                     wdt_series_id=OMARA_WDT_SERIES_ID)
    assert result == OMARA_WDT_SERIES_ID, (
        f"WDT context must return WDT series {OMARA_WDT_SERIES_ID}, got {result!r}"
    )


def test_domestic_context_uses_customer_preferred():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_customer_master(invoice_series_id=OMARA_FV_SERIES_ID)
    result = pick_invoice_series_id_for_vat_context(cm, vat_context="domestic",
                                                     wdt_series_id=OMARA_WDT_SERIES_ID)
    assert result == OMARA_FV_SERIES_ID


def test_wdt_context_missing_wdt_series_id_raises():
    from app.services.customer_master import pick_invoice_series_id_for_vat_context
    cm = _make_customer_master(invoice_series_id=OMARA_FV_SERIES_ID)
    with pytest.raises(ValueError, match="WDT series"):
        pick_invoice_series_id_for_vat_context(cm, vat_context="wdt",
                                                wdt_series_id=None)
