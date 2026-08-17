"""Unit tests for accounting_awb_projection (Logistics consume-only)."""
from __future__ import annotations

from app.services.accounting_awb_projection import (
    project_awbs_from_shipment_rows,
    resolve_wz_invoice_id,
)


def test_project_multiple_awbs():
    rows = [
        {"provider": "DHL", "tracking_ref": "111", "mode": "live", "state": "complete",
         "idempotency_key": "k1", "batch_id": "b1"},
        {"provider": "UPS", "tracking_ref": "222", "mode": "external", "state": "complete",
         "idempotency_key": "k2", "batch_id": "b1"},
        {"provider": "FEDEX", "tracking_ref": "333", "mode": "external", "state": "retired",
         "idempotency_key": "k3", "batch_id": "b1"},
        {"provider": "DHL", "tracking_ref": "", "mode": "live", "state": "pending"},
    ]
    out = project_awbs_from_shipment_rows(rows)
    assert len(out) == 3
    assert out[0]["source"] == "API"
    assert out[1]["source"] == "MANUAL_EXTERNAL"
    assert out[2]["source"] == "RETIRED"
    assert "Track" in out[0]["actions"]
    assert "Waybill" not in out[1]["actions"]


def test_resolve_wz_direct_join():
    assert resolve_wz_invoice_id({"document": {"invoice_id": "498723555"}}) == "498723555"
    assert resolve_wz_invoice_id({"invoice_id": "0", "nested_invoice_ids": ["498723555"]}) == "498723555"
    assert resolve_wz_invoice_id({"invoice_id": "0"}) is None
