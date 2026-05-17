"""Source-grep tests for the Atlas-aligned New Shipment modal.

Confirms:
- modal exposes master-data dropdown state (clientList/supplierList)
- dropdowns load from real master-data endpoints (no hardcoded party data)
- dropdown testids present (supplier-select, client-select) + free-text
  fallback testids retained for empty-master-data state
- intake metadata carries client_contractor_id / supplier_contractor_id
- four default slots present, in Atlas order
- add-another chips present for all DOC_TYPES
- Save Draft posts to the real intake endpoint; no SHP-NEW; no DHL pre-check
- packing list card untouched
"""
from __future__ import annotations

from pathlib import Path

_DASH = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html")


def _src() -> str:
    return _DASH.read_text(encoding="utf-8")


# ── Master-data wiring ────────────────────────────────────────────────────

def test_modal_loads_client_master_endpoint():
    assert "/api/v1/customer-master/" in _src()


def test_modal_loads_supplier_master_endpoint():
    assert "/api/v1/suppliers/" in _src()


def test_modal_carries_contractor_id_state():
    src = _src()
    assert "clientList" in src
    assert "supplierList" in src
    assert "shipmentClientCid" in src
    assert "shipmentSupplierCid" in src


def test_shipment_level_dropdown_testids_present():
    src = _src()
    assert 'data-testid="new-shipment-client-select"'   in src
    assert 'data-testid="new-shipment-supplier-select"' in src
    # Free-text fallback testids retained for empty-master-data state.
    assert 'data-testid="new-shipment-client-fallback"'   in src
    assert 'data-testid="new-shipment-supplier-fallback"' in src


def test_intake_metadata_includes_contractor_ids():
    src = _src()
    assert "supplier_contractor_id:" in src, \
        "purchase block must send supplier_contractor_id in metadata"
    assert "client_contractor_id:" in src, \
        "sales block must send client_contractor_id in metadata"


# ── Atlas alignment ───────────────────────────────────────────────────────

def test_atlas_four_default_slots():
    """Modal must initialise with the four Atlas default slots in order:
    purchase_invoice, purchase_packing, sales_packing, awb."""
    src = _src()
    block_start = src.index("function NewShipmentModal")
    block_end   = src.index("function NewShipmentDocumentSlot", block_start)
    body = src[block_start:block_end]
    # Find the documents-initializer
    for needed in ("_emptySlot('purchase_invoice')",
                   "_emptySlot('purchase_packing')",
                   "_emptySlot('sales_packing')",
                   "_emptySlot('awb')"):
        assert needed in body, f"missing default slot init: {needed}"


def test_atlas_doc_types_complete():
    """All 9 Atlas DOC_TYPES must be enumerated for the add-another chip row."""
    src = _src()
    for tid in ("purchase_invoice", "sales_proforma", "sales_invoice",
                "purchase_packing", "sales_packing", "awb",
                "service_invoice", "carnet", "other"):
        assert f"id: '{tid}'" in src, f"DOC_TYPE missing: {tid}"


def test_add_another_chip_testid_template_present():
    """Each DOC_TYPE renders an add-another chip with a templated testid
    of form `new-shipment-add-${t.id}`. Source-grep confirms the template
    and the DOC_TYPES enumeration (covered by test_atlas_doc_types_complete)."""
    src = _src()
    assert "`new-shipment-add-${t.id}`" in src, \
        "add-another chip testid template must use t.id"
    # Parent container testid:
    assert 'data-testid="new-shipment-add-another"' in src


def test_slot_row_testid_pattern_present():
    src = _src()
    assert "`new-shipment-slot-${type.id}`" in src or \
           "new-shipment-slot-${type.id}" in src, \
        "slot row template testid required"


def test_per_document_override_present():
    """Each slot can toggle a per-document client/supplier override."""
    src = _src()
    assert "supplierOverride" in src
    assert "clientOverride" in src
    # Override toggle testid template:
    assert "new-shipment-slot-override-toggle-" in src
    # Inherit option present in overrides:
    assert "inherit shipment-level" in src


def test_documents_section_header_present():
    src = _src()
    assert 'data-testid="new-shipment-documents-section"' in src
    assert 'data-testid="new-shipment-slot-counter"' in src


def test_optional_note_field_present():
    src = _src()
    assert 'data-testid="new-shipment-note"' in src


def test_footer_actions_cancel_and_save_draft():
    src = _src()
    assert 'data-testid="new-shipment-cancel"' in src
    assert 'data-testid="new-shipment-save-draft"' in src


def test_no_dhl_precheck_button_in_save_action():
    """Atlas reference includes a 'Save & Run DHL Pre-check' button. Per the
    operator's brief that explicitly forbids external workflow trigger from
    Save Draft, the pre-check button MUST NOT be wired in this modal."""
    src = _src()
    start = src.index("function NewShipmentModal")
    end   = src.index("function NewShipmentDocumentSlot", start)
    body  = src[start:end]
    assert "DHL Pre-check" not in body, \
        "DHL pre-check button forbidden in Save Draft action"
    assert "runPrecheck" not in body, \
        "Save Draft must not carry a runPrecheck flag"


def test_blue_info_banner_about_packing_lists_present():
    """Atlas blue banner explaining purchase ↔ sales packing relationship."""
    src = _src()
    assert "Purchase ↔ Sales packing lists" in src or \
           "Purchase ↔ Sales packing lists" in src


def test_amber_banner_about_pz_and_sad_present():
    src = _src()
    assert "PZ number will be assigned at the end of the workflow" in src
    assert "SAD is not required at this stage" in src


# ── Real backend wiring preserved ─────────────────────────────────────────

def test_save_draft_still_posts_to_real_intake_endpoint():
    src = _src()
    assert "/api/v1/shipment/intake" in src
    assert "SHP-NEW" not in src
    assert "SHP_NEW" not in src


# ── Local-only doc types (service_invoice / carnet / other) wired ─────────

def test_local_only_doc_types_appended_to_form_data():
    """Service / carnet / other files are now uploaded under their own
    form fields (service_invoices, carnet_docs, other_docs)."""
    src = _src()
    assert "fd.append('service_invoices'" in src
    assert "fd.append('carnet_docs'" in src
    assert "fd.append('other_docs'" in src


def test_local_only_metadata_blocks_present():
    src = _src()
    assert "service_blocks" in src
    assert "carnet_blocks"  in src
    assert "other_blocks"   in src


def test_pending_wiring_badge_no_longer_renders():
    """All 9 DOC_TYPES are now wired. The PENDING WIRING badge JSX is
    gated by `!wired` which can never be true any more."""
    src = _src()
    # The wired set must include all three previously-pending types.
    block_start = src.index("const _NS_WIRED_TYPES")
    block_end   = src.index("]", block_start) + 1
    wired_block = src[block_start:block_end]
    for tid in ("service_invoice", "carnet", "other"):
        assert f"'{tid}'" in wired_block, f"{tid} must be in _NS_WIRED_TYPES"


def test_no_hardcoded_atlas_mock_party_lists():
    """The Atlas reference modals.jsx ships with hardcoded CLIENT_LIST /
    SUPPLIER_LIST arrays (Bonacchi Atelier, Estrella Jewels Sp. z o.o.,
    Goldsmith & Co., Maison Aurélie, …). Per the operator brief, no such
    hardcoded party values may be embedded inside the modal."""
    src = _src()
    start = src.index("function NewShipmentModal")
    end   = src.index("function DashboardKanban", start)
    body  = src[start:end]
    for bad in (
        "Bonacchi Atelier",
        "Estrella Jewels Sp. z o.o.",
        "Goldsmith & Co.",
        "Maison Aur",                # Maison Aurélie (encoding-safe)
        "Diamond Trade DMCC",
        "Bijoux Lumi",
        "Geneva Goldworks",
        "Paris Diamonds",
        "Antwerp Stones",
        "Maison de Vicenza",
    ):
        assert bad not in body, f"hardcoded Atlas mock party value present: {bad}"


# ── Guard: packing pipeline UI untouched ──────────────────────────────────

def test_existing_packing_list_card_still_present():
    src = _src()
    assert 'data-testid="packing-list-card"' in src
    assert "loadPackingInfo" in src
