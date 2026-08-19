"""
test_shipping_ops_live_authority.py
===================================
Campaign A — Shipping Ops is a live consumer of existing carrier /
DHL Logistics authorities. Structural pins fail if the wireframe mock
authority returns.
"""
from __future__ import annotations

import re
from pathlib import Path

_V2 = Path(__file__).parent.parent / "app" / "static" / "v2"
_OPS = _V2 / "shipping-ops.jsx"
_API = _V2 / "pz-api.js"
_INDEX = _V2 / "index.html"


def _src() -> str:
    return _OPS.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip full-line // comments."""
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def test_no_hardcoded_shipments_array():
    code = _code_only(_src())
    assert not re.search(r"\bconst\s+SHIPMENTS\s*=\s*\[", code), (
        "Hardcoded SHIPMENTS array must be removed from shipping-ops.jsx"
    )


def test_no_fake_company_names():
    code = _code_only(_src())
    for fake in ("Aurum Trading", "Levi Joaillerie", "Maison Élise", "Maison Elise"):
        assert fake not in code, f"Fake client {fake!r} still present"


def test_no_fake_awb_or_sample_ids():
    code = _code_only(_src())
    for fake in ("1Z 994", "7799 1184 22", "SHP-2412-", "PRN-004", "RTN-001", "RMA-004"):
        assert fake not in code, f"Fake sample id/AWB {fake!r} still present"


def test_no_static_dhl_not_connected_claim():
    src = _src()
    assert "DHL Express API · not connected" not in src
    assert "DHL Express API" not in src or "not connected" not in src
    # Must not hardcode the false connectivity chip as operational copy
    assert re.search(r"getCarrierStatus", _code_only(src)), (
        "DHL capability must come from getCarrierStatus"
    )


def test_no_api_v1_shipping_namespace():
    src = _src()
    assert "/api/v1/shipping/" not in src, (
        "Forbidden /api/v1/shipping/ must not appear in Shipping Ops"
    )
    api = _API.read_text(encoding="utf-8")
    assert "${BASE}/shipping/" not in api
    assert "/carrier/" in api


def test_uses_canonical_carrier_and_logistics_wrappers():
    code = _code_only(_src())
    for name in (
        "getDhlLogisticsProjection",
        "getCarrierStatus",
        "listCarrierServices",
        "listBoxTypes",
        "getCarrierShipment",
        "getDhlLogisticsShipment",
        "getReturnDraft",
    ):
        assert name in code, f"Expected live authority wrapper {name} in Shipping Ops"


def test_fedex_stays_unavailable():
    src = _src()
    assert "FedEx · unavailable" in src
    assert "not implemented" in src.lower() or "Unavailable" in src


def test_live_return_create_remains_blocked():
    src = _src()
    code = _code_only(src)
    assert "ship-ops-return-hold-banner" in src
    assert "DHL capability pending" in src or "capability pending" in src.lower()
    assert "createReturnShipment(" not in code
    assert "return/create" in src.lower() or "Live Create Return" in src


def test_no_local_delivered_parser():
    code = _code_only(_src())
    assert "function parseDelivered" not in code
    assert "parseDelivered" not in code
    # KPI comes from projection.kpis, not a second engine
    assert "kpis.delivered_today" in code or "delivered_today" in code


def test_booking_navigates_not_copies_payload():
    src = _src()
    code = _code_only(src)
    assert "Proforma" in src
    assert "createCarrierShipment(" not in code
    assert "ship-ops-goto-proforma" in src or "ship-ops-new-shipment" in src


def test_shell_wires_nav_callbacks_and_live_subtitle():
    index = _INDEX.read_text(encoding="utf-8")
    block_start = index.index("page === 'shipping_ops'")
    block = index[block_start : block_start + 550]
    assert "ShippingOpsPage onViewShipment={handleViewShipment}" in block
    assert "onNav={handleNav}" in block
    assert "wireframe only" not in block.lower()
    assert "future scope" not in block.lower()


def test_shipping_ops_in_wired_pages():
    badge = (_V2 / "mock-badge.jsx").read_text(encoding="utf-8")
    m = re.search(r"const WIRED_PAGES\s*=\s*\[([^\]]+)\]", badge)
    assert m and "'shipping_ops'" in m.group(1), (
        "shipping_ops must be in WIRED_PAGES after Campaign A live authority"
    )


def test_pz_api_has_carrier_document_url_helper_only():
    api = _API.read_text(encoding="utf-8")
    assert "carrierDocumentUrls:" in api
    assert "/label/" in api
    assert "/waybill-doc/" in api
    assert "/receipt/" in api
    assert "/epod/" in api
    # Helper must not invent a parallel shipping namespace
    helper = api[api.index("carrierDocumentUrls:") : api.index("carrierDocumentUrls:") + 600]
    assert "/shipping/" not in helper


def test_queue_surfaces_carrier_tracking_freshness():
    """Location / ETA / last-sync come from the projection row, not from the UI."""
    code = _code_only(_src())
    for field in (
        "r.current_location",
        "r.expected_delivery_warsaw",
        "r.tracking_last_checked_at",
        "r.tracking_stale",
    ):
        assert field in code, f"Shipping Ops queue must render {field} from the projection row"


def test_projection_rows_carry_tracking_freshness_both_directions():
    """Outbound rows must expose the same staleness keys inbound already does.

    Without them the queue's Last Sync column would silently read blank for every
    outbound shipment, which looks like 'never checked' rather than 'not projected'.
    """
    proj = (
        Path(__file__).parent.parent / "app" / "services" / "dhl_logistics_projector.py"
    ).read_text(encoding="utf-8")
    for key in ('"tracking_stale":', '"tracking_last_checked_at":'):
        assert proj.count(key) >= 4, (
            f"{key} must be emitted by both the inbound and the outbound row builder"
        )
