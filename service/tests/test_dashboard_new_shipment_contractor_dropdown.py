"""V1 New Shipment is retired — V2 is the sole intake party authority.

This file used to pin the V1 (dashboard.html) New Shipment modal: its
shipment-level Client/Supplier dropdowns, its per-slot overrides and its own
POST /api/v1/shipment/intake payload builder.

That was the duplicate authority. V2 (v2/modals.jsx) now makes each document
slot the only source of its own party identity, and keeping a second payload
builder in V1 would have meant two divergent truths for the same document —
so the V1 modal was removed and its entry point routes to the canonical V2
surface. These tests pin that closure; the V2 behaviour itself is pinned by
test_v2_new_shipment_party_authority.py.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
_DASH = _STATIC / "dashboard.html"
_MODALS = _STATIC / "v2" / "modals.jsx"


def _src() -> str:
    return _DASH.read_text(encoding="utf-8")


# ── The duplicate authority is gone from V1 ──────────────────────────────

def test_v1_no_longer_defines_a_new_shipment_modal():
    src = _src()
    assert "function NewShipmentModal" not in src
    assert "function NewShipmentDocumentSlot" not in src
    assert "showNewShipment" not in src


def test_v1_no_longer_builds_an_intake_payload():
    """Only ONE frontend may assemble the /shipment/intake multipart body."""
    src = _src()
    assert "fetch('/api/v1/shipment/intake'" not in src
    assert "shipmentClientCid" not in src
    assert "shipmentSupplierCid" not in src
    assert 'data-testid="new-shipment-client-select"' not in src
    assert 'data-testid="new-shipment-supplier-select"' not in src


def test_v1_entry_routes_to_the_canonical_v2_surface():
    """The V1 header button still works — it lands the operator on V2."""
    src = _src()
    assert "onNewShipment={() => { window.location.href = '/v2/dashboard'; }}" in src


def test_v2_is_the_single_intake_authority():
    modals = _MODALS.read_text(encoding="utf-8")
    assert modals.count("PzApi.intakeShipment") == 1


# ── What V1 keeps ────────────────────────────────────────────────────────

def test_doc_type_policy_survives_for_add_document():
    """AddDocumentModal (post-draft single-file upload) reuses _NS_DOC_TYPES."""
    src = _src()
    assert "const _NS_DOC_TYPES = [" in src
    assert "function AddDocumentModal(" in src
    assert "_NS_DOC_TYPES.filter(t => t.id !== 'sad')" in src
    # The retired modal's wired-type set had no other reader.
    assert "_NS_WIRED_TYPES" not in src


def test_master_data_endpoints_still_used_by_v1():
    """Retiring the modal must not cut V1 off from real master data."""
    src = _src()
    assert "/api/v1/customer-master/" in src
    assert "/api/v1/suppliers/" in src
