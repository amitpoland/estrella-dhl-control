"""
test_awb_customs_value.py — regression coverage for DHL waybill "Custom Val"
extraction (awb_parser._extract_customs_value).

Root-cause incident: AWB 2315714531 (Global Jewellery India → Estrella Jewels,
inv_122.pdf / DHL122_Global.pdf). The waybill rendered the customs value with a
LEADING currency code ("Custom Val: USD 732.00"). The previous regex required
the numeric value to appear immediately after the label, so it only matched the
currency-SUFFIX form. Every prefix/glued/thousands-separator/label-variant
rendering produced customs_value=None, which downstream coerced to 0.00 and
blocked clearance routing ("Routing Pending — CIF not calculated yet").

These tests pin the contract that the value parses regardless of currency
placement, and that an unreadable value returns None (a VERIFY-GAP signal),
never a silent 0.00.
"""
from __future__ import annotations

import pytest

from app.services.awb_parser import _extract_customs_value


# ── The actual incident: currency PREFIX (was returning None → 0.00) ──────────

def test_custom_val_currency_prefix_with_space():
    # DHL122_Global.pdf rendering for AWB 2315714531
    value, ccy, source = _extract_customs_value("Custom Val: USD 732.00")
    assert value == pytest.approx(732.00)
    assert ccy == "USD"
    assert source == "custom_val_label"


def test_custom_val_currency_prefix_glued():
    value, ccy, source = _extract_customs_value("Custom Val:USD732.00")
    assert value == pytest.approx(732.00)
    assert ccy == "USD"


# ── Existing currency-SUFFIX form must keep working ───────────────────────────

def test_custom_val_currency_suffix():
    value, ccy, _ = _extract_customs_value("Custom Val: 732.00 USD")
    assert value == pytest.approx(732.00)
    assert ccy == "USD"


def test_custom_val_suffix_thousands_separator():
    # the pre-existing real-PDF smoke value (AWB 2824221912 → 14169.0)
    value, ccy, _ = _extract_customs_value("Custom Val: 14,169.00 USD")
    assert value == pytest.approx(14169.0)
    assert ccy == "USD"


# ── Label / format variants ───────────────────────────────────────────────────

def test_customs_value_label_variant_prefix():
    value, ccy, _ = _extract_customs_value("Customs Value: EUR 1,250.50")
    assert value == pytest.approx(1250.50)
    assert ccy == "EUR"


def test_customs_value_parenthetical_label():
    value, _, _ = _extract_customs_value(
        "Customs Value (for customs purposes only): USD 732.00"
    )
    assert value == pytest.approx(732.00)


def test_custom_val_no_currency():
    value, ccy, source = _extract_customs_value("Custom Val: 732.00")
    assert value == pytest.approx(732.00)
    assert ccy == ""           # caller falls back to document-level USD/EUR scan
    assert source == "custom_val_label"


def test_custom_val_value_in_full_waybill_block():
    text = (
        "DHL EXPRESS WAYBILL 2315714531\n"
        "Shipper : GLOBAL JEWELLERY INDIA PVT LTD\n"
        "Receiver : ESTRELLA JEWELS SP. Z O.O.\n"
        "Contents : SL925 SILVER JEWELLERY STUDDED WITH CZ\n"
        "Pieces : 1   Weight : 1.0 kg\n"
        "Custom Val: USD 732.00\n"
        "Origin: BOM  Destination: WAW\n"
    )
    value, ccy, source = _extract_customs_value(text)
    assert value == pytest.approx(732.00)
    assert ccy == "USD"
    assert source == "custom_val_label"


# ── VERIFY-GAP: unreadable / absent value returns None, never 0.00 ────────────

def test_label_present_but_no_value_returns_none():
    value, _, source = _extract_customs_value("Custom Val:\nShipper: ACME")
    assert value is None          # NOT 0.0
    assert source == "label_no_value"


def test_no_label_returns_none():
    value, _, source = _extract_customs_value("Some unrelated waybill text")
    assert value is None
    assert source == "no_label"
