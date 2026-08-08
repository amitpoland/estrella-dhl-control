"""Proforma Logistics tab - outbound vs inbound authority split.

Pins that the customer Logistics / Carrier and Transport surface:
  * drives outbound live tracking from carrierShipment.tracking_ref (AWB)
    via the canonical GET/POST /api/v1/tracking/{tracking_no} (PzApi)
  * does NOT mount import batch timeline / clearance as the outbound timeline
  * keeps import clearance (DSK/SAD/agency/inbound AWB) in a separately labeled panel
  * keeps CMR AWB on _transport.outbound_awb (never import batch_id)

No second DHL tracker may be introduced.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parents[1]
_JSX = (_ROOT / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
_API = (_ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")


def test_outbound_tracking_component_exists():
    assert "function OutboundShipmentTracking(" in _JSX
    assert 'data-testid="pf-logistics-outbound-tracking"' in _JSX
    assert 'data-testid="pf-logistics-outbound-timeline"' in _JSX


def test_inbound_clearance_is_separate_labeled_panel():
    assert "function ImportClearanceLogisticsPanel(" in _JSX
    assert 'data-testid="pf-logistics-inbound-clearance"' in _JSX
    assert "Import clearance (inbound)" in _JSX
    assert "Shipment timeline &amp; clearance" not in _JSX
    assert "Shipment timeline & clearance" not in _JSX


def test_legacy_mixed_LogisticsTracking_removed():
    assert "function LogisticsTracking(" not in _JSX
    assert 'data-testid="pf-logistics-tracking"' not in _JSX
    assert re.search(
        r"<LogisticsTracking\s+batchId=\{liveDraft\.batch_id",
        _JSX,
    ) is None


def test_outbound_uses_canonical_tracking_api_not_batch_timeline():
    assert "PzApi.getDhlTracking" in _JSX
    assert "PzApi.refreshDhlTracking" in _JSX
    assert "/tracking/${encodeURIComponent(trackingNo)}" in _API
    assert "getDhlTracking:" in _API
    assert "refreshDhlTracking:" in _API


def test_outbound_mount_keys_on_carrier_tracking_ref():
    assert re.search(
        r"<OutboundShipmentTracking[\s\S]*?awb=\{\(carrierShipment\s*&&\s*carrierShipment\.tracking_ref\)",
        _JSX,
    ), "Outbound tracking must key on carrierShipment.tracking_ref"
    outbound_fn = _JSX.split("function OutboundShipmentTracking(", 1)[1].split(
        "function ImportClearanceLogisticsPanel(", 1
    )[0]
    assert "/tracking/shipment/" not in outbound_fn
    assert "clearance-status" not in outbound_fn


def test_inbound_panel_keeps_batch_timeline_and_clearance():
    inbound_fn = _JSX.split("function ImportClearanceLogisticsPanel(", 1)[1].split(
        "// ── Documents registry", 1
    )[0]
    assert "/tracking/shipment/" in inbound_fn
    assert "clearance-status" in inbound_fn
    assert "Inbound AWB" in inbound_fn


def test_cmr_still_uses_outbound_awb_not_batch_id():
    assert re.search(r"awb:\s*_transport\.outbound_awb", _JSX)
    assert not re.search(r"awb:\s*liveDraft\.batch_id", _JSX)
    assert re.search(
        r"outbound_awb:\s*ship\s*\?\s*\(ship\.tracking_ref\s*\|\|\s*null\)\s*:\s*null",
        _JSX,
    )


def test_no_second_dhl_tracker_service_invented():
    assert "createDhlTracker" not in _JSX
    assert "new TrackingService" not in _JSX
    outbound_fn = _JSX.split("function OutboundShipmentTracking(", 1)[1].split(
        "function ImportClearanceLogisticsPanel(", 1
    )[0]
    assert "/api/v1/shipping/dhl/tracking/" not in outbound_fn
