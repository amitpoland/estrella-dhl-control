"""Proforma Logistics tab - outbound vs inbound authority split.

Pins that the customer Logistics / Carrier and Transport surface:
  * drives outbound live tracking from carrierShipment.tracking_ref (AWB)
    via the canonical GET/POST /api/v1/tracking/{tracking_no} (PzApi)
  * does NOT mount import batch timeline / clearance as the outbound timeline
  * keeps import clearance (DSK/SAD/agency/inbound AWB) in a separately labeled panel
  * keeps CMR AWB on _transport.outbound_awb (never import batch_id)
  * uses the shared EJOutboundTrackingCard presentation (one card authority)

No second DHL tracker may be introduced.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parents[1]
_JSX = (_ROOT / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
_SHARED = (_ROOT / "app" / "static" / "v2" / "estrella-outbound-tracking.jsx").read_text(encoding="utf-8")
_API = (_ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
_INDEX = (_ROOT / "app" / "static" / "v2" / "index.html").read_text(encoding="utf-8")
_SHIP = (_ROOT / "app" / "static" / "v2" / "shipment-detail-page.jsx").read_text(encoding="utf-8")


def test_outbound_tracking_component_exists():
    assert "function OutboundShipmentTracking(" in _JSX
    assert "EJOutboundTrackingCard" in _JSX
    assert "window.EJOutboundTrackingCard" in _SHARED
    assert 'testIdRoot="pf-logistics-outbound"' in _JSX
    assert 'data-testid={testIdRoot}' in _SHARED or "data-testid={testIdRoot}" in _SHARED


def test_shared_card_loaded_once_and_reused_on_shipment_detail():
    assert "estrella-outbound-tracking.jsx" in _INDEX
    assert "EJOutboundTrackingCard" in _SHIP
    assert "function DhlTrackingCard(" in _SHIP


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
    assert "PzApi.getDhlTracking" in _SHARED
    assert "PzApi.refreshDhlTracking" in _SHARED
    assert "/tracking/${encodeURIComponent(trackingNo)}" in _API
    assert "getDhlTracking:" in _API
    assert "refreshDhlTracking:" in _API
    # Shared card must not call import clearance authorities.
    assert "/tracking/shipment/" not in _SHARED
    assert "clearance-status" not in _SHARED


def test_outbound_mount_keys_on_carrier_tracking_ref():
    assert re.search(
        r"<OutboundShipmentTracking[\s\S]*?awb=\{\(carrierShipment\s*&&\s*carrierShipment\.tracking_ref\)",
        _JSX,
    ), "Outbound tracking must key on carrierShipment.tracking_ref"
    assert "draftId={draft && draft.id}" in _JSX
    outbound_fn = _JSX.split("function OutboundShipmentTracking(", 1)[1].split(
        "function ImportClearanceLogisticsPanel(", 1
    )[0]
    assert "/tracking/shipment/" not in outbound_fn
    assert "clearance-status" not in outbound_fn


def test_inbound_panel_keeps_batch_timeline_and_clearance():
    inbound_fn = _JSX.split("function ImportClearanceLogisticsPanel(", 1)[1].split(
        "// ── Documents registry", 1
    )[0]
    # Hub comment may have moved; tolerate Documents aggregator header.
    if "/tracking/shipment/" not in inbound_fn:
        inbound_fn = _JSX.split("function ImportClearanceLogisticsPanel(", 1)[1][:8000]
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
    assert "createDhlTracker" not in _SHARED
    assert "/api/v1/shipping/dhl/tracking/" not in _SHARED


def test_shared_card_keeps_api_path_out_of_primary_hierarchy():
    """Primary copy must not lead with GET /api/...; diagnostic is secondary."""
    assert "Customer shipment · not import clearance" in _SHARED
    assert "<details" in _SHARED
    assert "GET /api/v1/tracking/" in _SHARED
    assert "ej-outbound-lifecycle" in _SHARED or "outbound-lifecycle" in _SHARED
