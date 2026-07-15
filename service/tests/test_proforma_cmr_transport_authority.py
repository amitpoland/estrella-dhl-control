"""test_proforma_cmr_transport_authority.py — PR-5.

Structural contracts for the Transport Document Authority (ADR
docs/decisions/ADR-proforma-cmr-transport-authority.md):

  * ONE resolver (`_transport`) turns Draft + carrierShipment into a single
    transport-document projection; the CMR, Packing List and Logistics panel
    consume it — React never assembles transport identity from multiple responses.
  * The CMR number is a STABLE document identifier (export shipment reference),
    INDEPENDENT of the AWB — a re-book changes the AWB, not the document identity.
  * outbound AWB / carrier / service come from carrierShipment (not the batch id).
  * one effectiveWeight object with fixed precedence (manual → carrier → packing →
    missing) shared by CMR + Packing List + Logistics; honest Missing + reason.
  * exactly ONE weight-override writer; weight_override_source provenance column.

Required tests 1, 2, 3, 4, 6, 13, 14, 15 + the mandated pre-merge adjustments.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parents[1]
_JSX = (_ROOT / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
_API = (_ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
_CMR = (_ROOT / "app" / "static" / "v2" / "estrella-doc-cmr.jsx").read_text(encoding="utf-8")
_PILDB = (_ROOT / "app" / "services" / "proforma_invoice_link_db.py").read_text(encoding="utf-8")
_ROUTES = (_ROOT / "app" / "api" / "routes_proforma.py").read_text(encoding="utf-8")


# ── one resolver (TransportDocumentAuthority) ─────────────────────────────────

def test_single_transport_resolver():
    assert re.search(r"const _transport\s*=\s*\(\(\)\s*=>", _JSX), "one _transport resolver must exist"
    assert "const _ew = _transport.effectiveWeight" in _JSX
    # The resolver reads the fetched carrier shipment, not scattered responses.
    assert re.search(r"const ship\s*=\s*\(carrierShipment", _JSX)


# ── 1: CMR uses the outbound AWB, not the import batch id ─────────────────────

def test_cmr_awb_is_outbound_not_batch_id():
    assert re.search(r"awb:\s*_transport\.outbound_awb", _JSX)
    assert not re.search(r"awb:\s*liveDraft\.batch_id", _JSX)


# ── 2: CMR number is STABLE and INDEPENDENT of the AWB ────────────────────────

def test_cmr_number_stable_independent_of_awb():
    # number derives from the export shipment reference, not the AWB/tracking_ref
    assert re.search(r"cmr_number:\s*export_shipment_id\s*\?", _JSX)
    assert re.search(r"CMR-EJ-\$\{export_shipment_id\}", _JSX)
    assert re.search(r"cmr_no:\s*_transport\.cmr_number", _JSX)
    # the CMR number must NOT be built from the AWB / tracking_ref
    assert not re.search(r"CMR-EJ-\$\{[^}]*tracking_ref", _JSX), (
        "CMR number must be independent of the AWB (tracking_ref)"
    )
    assert "`CMR-EJ-${batchId}`" not in _JSX


# ── 3: carrier + service from the resolver (canonical booking) ────────────────

def test_carrier_and_service_from_resolver():
    assert re.search(r"name:\s*_transport\.carrier", _JSX)
    assert re.search(r"service:\s*_transport\.service", _JSX)
    assert "'EXPRESS WORLDWIDE'" not in _JSX


# ── 4: honest missing state (carrier + reason) ────────────────────────────────

def test_missing_outbound_renders_honest_state_with_reason():
    assert re.search(r"carrier:\s*_transport\.linked\s*\?", _JSX)
    assert "carrier_missing_reason" in _JSX
    assert "No outbound shipment linked" in _JSX
    assert "EJCMRNoCarrier" in _CMR


# ── 6: gross weight uses the effective projection (carrier precedence) ─────────

def test_gross_weight_uses_effective_projection():
    assert re.search(r"weight_kg:\s*_ew\.gross", _JSX)
    # precedence includes carrier booking for gross
    assert "source: 'carrier'" in _JSX and "bookGross" in _JSX


# ── weight source precedence documented; never inferred/averaged/divided ──────

def test_weight_precedence_documented():
    assert re.search(r"manual\s*.\s*carrier booking\s*.\s*packing extraction\s*.\s*missing", _JSX)
    # net precedence has no carrier source (only manual → packing → missing)
    assert re.search(r"manual\s*.\s*packing extraction\s*.\s*missing", _JSX)


# ── 13: no live DHL from a document render or the weight endpoints ────────────

def test_no_live_dhl_in_render_or_weight_endpoints():
    assert "getCarrierShipment" in _JSX
    assert re.search(r"const _transport\s*=", _JSX)
    assert "setWeightOverride" in _JSX and "clearWeightOverride" in _JSX
    _wblock = _PILDB.split("def set_draft_weight_override")[1].split("def update_draft_line")[0]
    assert "adapters.live" not in _wblock
    assert "book" not in _wblock.lower()


# ── 14: CMR + Packing List share the SAME effective-weight object ─────────────

def test_cmr_and_packing_share_effective_weight():
    for token in ("effective_net_kg:", "effective_gross_kg:"):
        assert _JSX.count(token) >= 2
    # both derive from the single _ew (= _transport.effectiveWeight)
    assert re.search(r"effective_net_kg:\s*_ew\.net", _JSX)
    assert re.search(r"effective_gross_kg:\s*_ew\.gross", _JSX)
    # the Logistics tiles consume the same effective weight
    assert re.search(r"pf-logistics-tile-gross.*_ew\.gross|_ew\.gross[^\n]*pf-logistics-tile-gross", _JSX, re.DOTALL) \
        or "_ew.gross != null" in _JSX


# ── 15: exactly one weight writer; API wrappers + UI controls present ─────────

def test_single_weight_writer_and_ui():
    assert _PILDB.count("def set_draft_weight_override") == 1
    assert _PILDB.count("def clear_draft_weight_override") == 1
    assert "setWeightOverride" in _API and "clearWeightOverride" in _API
    for tid in ("pf-weight-edit", "pf-weight-save", "pf-weight-cancel", "pf-weight-clear",
                "pf-weight-net", "pf-weight-gross"):
        assert f'data-testid="{tid}"' in _JSX


# ── weight_override_source provenance column persisted ────────────────────────

def test_weight_override_source_column():
    assert '"weight_override_source"' in _PILDB or "weight_override_source" in _PILDB
    assert 'new_weight_override_source = "manual"' in _PILDB
    assert 'new_weight_override_source = "cleared"' in _PILDB
    assert '"weight_override_source"' in _ROUTES


# ── source badges present (Extracted / Carrier / Manual / Missing) ────────────

def test_weight_source_badges_present():
    for label in ("Manual override", "Extracted from packing", "Carrier booking", "Missing"):
        assert label in _JSX
