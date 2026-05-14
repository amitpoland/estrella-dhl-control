"""
test_pr2c2_unit_price.py — PR 2C.2: unit_price_eur passthrough + zero-price guards.

Coverage:
  1. test_link_as_sales_carries_eur_price
     — unit_price_eur=145.00, quantity=2 → unit_price==145.0, total_value==290.0,
       currency=="EUR", price_source=="packing_xlsx_value"
  2. test_link_as_sales_zero_price_source_label
     — unit_price_eur=0 → price_source=="packing_promote", unit_price==0.0
  3. test_link_as_sales_missing_unit_price_eur_defaults_to_zero
     — no unit_price_eur key at all → no exception, unit_price==0.0, total_value==0.0
  4. test_auto_create_draft_carries_unit_price_through
     — sales_lines with unit_price=145.0 flow into editable_lines_json unchanged
  5. test_zero_price_blocks_proforma_post_preview
     — draft with unit_price=0 lines → _post_validation_error path triggers
  6. test_needs_pricing_refresh_true_when_zero_prices
     — _draft_to_full: all lines at unit_price=0 → needs_pricing_refresh==True
  7. test_needs_pricing_refresh_false_when_prices_populated
     — _draft_to_full: all lines at unit_price>0 → needs_pricing_refresh==False
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api.routes_packing import _build_matched_sales_lines


# ── helpers ────────────────────────────────────────────────────────────────────

def _packing_line(
    product_code: str = "EJL-RNG-417G",
    design_no:    str = "D001",
    quantity:     float = 1.0,
    unit_price_eur: Any = None,
    currency:     str = "EUR",
    requires_manual_review: bool = False,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "product_code":          product_code,
        "design_no":             design_no,
        "bag_id":                "BAG-1",
        "invoice_no":            "INV-001",
        "quantity":              quantity,
        "remarks":               "",
        "currency":              currency,
        "requires_manual_review": requires_manual_review,
    }
    if unit_price_eur is not None:
        row["unit_price_eur"] = unit_price_eur
    return row


# ── 1. EUR price carried through ──────────────────────────────────────────────

def test_link_as_sales_carries_eur_price():
    lines = [_packing_line(unit_price_eur=145.00, quantity=2.0, currency="EUR")]
    sales_lines, skipped = _build_matched_sales_lines(lines, client="SUOKKO")

    assert skipped == 0
    assert len(sales_lines) == 1
    sl = sales_lines[0]
    assert sl["unit_price"] == 145.00,   f"expected 145.00, got {sl['unit_price']}"
    assert sl["total_value"] == 290.00,  f"expected 290.00, got {sl['total_value']}"
    assert sl["currency"] == "EUR",      f"expected EUR, got {sl['currency']}"
    assert sl["price_source"] == "packing_xlsx_value", (
        f"expected packing_xlsx_value, got {sl['price_source']}"
    )


# ── 2. Zero price → packing_promote label ─────────────────────────────────────

def test_link_as_sales_zero_price_source_label():
    lines = [_packing_line(unit_price_eur=0, quantity=3.0)]
    sales_lines, skipped = _build_matched_sales_lines(lines, client="SUOKKO")

    assert len(sales_lines) == 1
    sl = sales_lines[0]
    assert sl["unit_price"] == 0.0,             f"expected 0.0, got {sl['unit_price']}"
    assert sl["price_source"] == "packing_promote", (
        f"expected packing_promote, got {sl['price_source']}"
    )


# ── 3. Missing unit_price_eur key → defaults to zero ─────────────────────────

def test_link_as_sales_missing_unit_price_eur_defaults_to_zero():
    lines = [_packing_line()]  # no unit_price_eur key at all
    sales_lines, skipped = _build_matched_sales_lines(lines, client="SUOKKO")

    assert len(sales_lines) == 1
    sl = sales_lines[0]
    assert sl["unit_price"] == 0.0,  f"expected 0.0, got {sl['unit_price']}"
    assert sl["total_value"] == 0.0, f"expected 0.0, got {sl['total_value']}"


# ── 4. auto_create_draft carries unit_price through ────────────────────────────

def test_auto_create_draft_carries_unit_price_through():
    from app.services.proforma_invoice_link_db import auto_create_draft_from_sales_packing

    sales_input = [
        {
            "product_code": "EJL-RNG-417G",
            "design_no":    "D001",
            "quantity":     2.0,
            "unit_price":   145.0,
            "currency":     "EUR",
            "price_source": "packing_xlsx_value",
            "client_ref":   "INV-001",
        }
    ]

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        draft, was_created = auto_create_draft_from_sales_packing(
            db_path,
            batch_id    = "BATCH-TEST-001",
            client_name = "SUOKKO",
            currency    = "EUR",
            lines       = sales_input,
            operator    = "test",
        )
        assert was_created is True
        editable = json.loads(draft.editable_lines_json or "[]")
        assert len(editable) == 1, f"expected 1 editable line, got {len(editable)}"
        ln = editable[0]
        assert ln["unit_price"] == 145.0, (
            f"expected unit_price==145.0 in draft, got {ln['unit_price']}"
        )
        assert ln["currency"] == "EUR", f"expected EUR, got {ln['currency']}"
    finally:
        try:
            db_path.unlink()
        except Exception:
            pass


# ── 5. Zero-price blocks post preview ─────────────────────────────────────────
#
# We test the pre-flight guard inside post_proforma_draft_to_wfirma by calling
# the function with a mock draft that has zero-price lines, and asserting that
# the function returns a 400-blocked response before reaching start_post or
# any wFirma call.

def test_zero_price_blocks_proforma_post_preview():
    import importlib
    from app.api import routes_proforma

    zero_lines = json.dumps([
        {"product_code": "EJL-RNG-417G", "qty": 1.0, "unit_price": 0.0, "currency": "EUR"},
    ])

    mock_draft = MagicMock()
    mock_draft.editable_lines_json = zero_lines
    mock_draft.wfirma_proforma_id  = ""
    mock_draft.client_name         = "SUOKKO"
    mock_draft.batch_id            = "BATCH-001"

    # Patch all I/O; we only care about the zero-price guard path.
    with patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=mock_draft), \
         patch.object(routes_proforma, "_proforma_db_path", return_value=Path("/tmp/mock.db")), \
         patch.object(routes_proforma.settings, "wfirma_create_proforma_allowed", True):

        response = routes_proforma.post_proforma_draft_to_wfirma(
            draft_id   = 1,
            body       = {
                "expected_updated_at": "2026-01-01T00:00:00Z",
                "confirm_token":       "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA",
            },
            x_operator = "test-operator",
        )

    data = json.loads(response.body)
    assert data["ok"] is False,            f"expected ok=False, got {data.get('ok')}"
    assert data["status"] == "blocked",    f"expected blocked, got {data.get('status')}"
    reasons = " ".join(data.get("blocking_reasons", []))
    assert "unit_price" in reasons or "price" in reasons, (
        f"blocking_reasons should mention price, got: {data.get('blocking_reasons')}"
    )


# ── 6. needs_pricing_refresh=True when any line has zero price ────────────────

def _make_mock_draft(editable_lines: List[Dict[str, Any]]) -> MagicMock:
    d = MagicMock()
    d.editable_lines_json  = json.dumps(editable_lines, ensure_ascii=False)
    d.source_lines_json    = "[]"
    d.service_charges_json = "[]"
    d.buyer_override_json  = "{}"
    d.ship_to_override_json = "{}"
    d.payment_terms_json   = "{}"
    d.remarks              = ""
    d.notes                = ""
    d.exchange_rate        = None
    d.status               = "draft"
    # Fields consumed by _draft_to_summary
    d.id                   = 1
    d.batch_id             = "BATCH-001"
    d.client_name          = "SUOKKO"
    d.currency             = "EUR"
    d.draft_state          = "draft"
    d.draft_version        = 1
    d.wfirma_proforma_id   = ""
    d.wfirma_proforma_fullnumber = ""
    d.created_at           = "2026-01-01T00:00:00Z"
    d.updated_at           = "2026-01-01T00:00:00Z"
    d.last_packing_sync_at = None
    d.packing_sync_warning = None
    return d


def test_needs_pricing_refresh_true_when_zero_prices():
    from app.api.routes_proforma import _draft_to_full

    mock_draft = _make_mock_draft([
        {"product_code": "EJL-RNG-417G", "qty": 1.0, "unit_price": 0.0,  "currency": "EUR"},
        {"product_code": "EJL-PND-ROSE", "qty": 2.0, "unit_price": 0.0,  "currency": "EUR"},
    ])

    result = _draft_to_full(mock_draft)
    assert result["needs_pricing_refresh"] is True, (
        f"expected needs_pricing_refresh=True, got {result.get('needs_pricing_refresh')}"
    )


# ── 7. needs_pricing_refresh=False when all prices populated ──────────────────

def test_needs_pricing_refresh_false_when_prices_populated():
    from app.api.routes_proforma import _draft_to_full

    mock_draft = _make_mock_draft([
        {"product_code": "EJL-RNG-417G", "qty": 1.0, "unit_price": 145.0, "currency": "EUR"},
        {"product_code": "EJL-PND-ROSE", "qty": 2.0, "unit_price": 89.50, "currency": "EUR"},
    ])

    result = _draft_to_full(mock_draft)
    assert result["needs_pricing_refresh"] is False, (
        f"expected needs_pricing_refresh=False, got {result.get('needs_pricing_refresh')}"
    )
