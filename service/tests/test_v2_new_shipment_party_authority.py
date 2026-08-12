"""Source-grep pins for the V2 New Shipment modal's party authority.

The defect this locks out: the modal used to carry BOTH a shipment-level
Client/Supplier pair AND a per-document selection, with the payload written as
``slot.override || shipmentLevel``. Two editable truths for one document
identity — ambiguous for customs (purchase / CIF) and warehouse valuation
(sales) alike.

After consolidation the ONLY party authority is the document slot itself:

    document -> doc type -> required party -> master selection -> metadata block

Backend contract is untouched: POST /api/v1/shipment/intake stays the single
creation path and still reads ``supplier_contractor_id`` /
``client_contractor_id`` out of the same metadata blocks.

V1 (service/app/static/dashboard.html) keeps the old shipment-level UI and is
pinned by test_dashboard_new_shipment_contractor_dropdown.py — that surface is
frozen and consolidating it is a separate campaign.
"""
from __future__ import annotations

from pathlib import Path

_MODALS = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "modals.jsx"


def _src() -> str:
    return _MODALS.read_text(encoding="utf-8")


# ── Duplicate authority is gone ───────────────────────────────────────────

def test_no_shipment_level_party_state():
    src = _src()
    assert "shipmentClientCid" not in src
    assert "shipmentSupplierCid" not in src


def test_no_shipment_level_party_selects():
    src = _src()
    assert 'data-testid="new-shipment-client-select"' not in src
    assert 'data-testid="new-shipment-supplier-select"' not in src


def test_no_inherit_shipment_level_option():
    assert "inherit shipment-level" not in _src()


def test_no_default_party_props_passed_to_slots():
    src = _src()
    assert "defaultClientCid" not in src
    assert "defaultSupplierCid" not in src


def test_no_shipment_level_fallback_in_payload():
    """Every contractor id in the payload comes from the slot alone."""
    src = _src()
    assert "|| shipmentSupplierCid" not in src
    assert "|| shipmentClientCid" not in src
    for field in ("supplier_contractor_id:", "client_contractor_id:"):
        for line in [ln for ln in src.splitlines() if field in ln]:
            assert "shipment" not in line, f"shipment-level fallback survives: {line.strip()}"


# ── The slot is the authority, and it is always visible ───────────────────

def test_slot_party_selectors_present_and_master_backed():
    src = _src()
    assert "new-shipment-slot-client-override-" in src
    assert "new-shipment-slot-supplier-override-" in src
    # Options come from the master lists loaded off the real endpoints.
    assert "clientList.map(c => <option key={c.contractor_id} value={c.contractor_id}>" in src
    assert "supplierList.map(s => <option key={s.contractor_id} value={s.contractor_id}>" in src
    assert "PzApi.listCustomerMaster" in src
    assert "PzApi.listSuppliers" in src


def test_slot_party_selector_is_not_hidden_behind_a_toggle():
    """A required field cannot live behind a collapsed override toggle."""
    src = _src()
    assert "showOverride" not in src
    assert "{(type.needsClient || type.needsSupplier) && (" in src


# ── Required-party validation, before any upload starts ───────────────────

def test_populated_slot_requiring_a_party_blocks_submit():
    src = _src()
    assert "requires Supplier." in src
    assert "requires Client." in src
    # Only populated slots are challenged — empty optional slots stay optional.
    assert "if (d.files.length === 0) return;" in src


def test_party_validation_runs_before_the_upload():
    src = _src()
    assert src.index("partyErrors.length") < src.index("new FormData()")


# ── Contract with the intake authority is unchanged ───────────────────────

def test_single_creation_path():
    src = _src()
    assert "PzApi.intakeShipment(fd)" in src
    assert src.count("PzApi.intakeShipment") == 1
    assert "idempotency_key" in src


def test_all_nine_doc_types_reach_their_multipart_field():
    src = _src()
    for tid in ("purchase_invoice", "sales_proforma", "sales_invoice",
                "purchase_packing_list", "sales_packing_list", "awb",
                "service_invoice", "carnet", "other"):
        assert f"id: '{tid}'," in src, f"DOC_TYPE missing: {tid}"
    for field in ("'invoices'", "'packing_lists'", "'sales_documents'",
                  "'sales_packing_lists'", "'awb'", "'service_invoices'",
                  "'carnet_docs'", "'other_docs'"):
        assert f"fd.append({field}," in src, f"multipart field not appended: {field}"
    for block in ("purchase_blocks:", "sales_blocks:", "service_blocks:",
                  "carnet_blocks:", "other_blocks:"):
        assert block in src


def test_awb_requires_no_party():
    src = _src()
    awb_line = next(ln for ln in src.splitlines() if "id: 'awb'," in ln)
    assert "needsClient: false" in awb_line
    assert "needsSupplier: false" in awb_line


def test_packing_file_count_range_match_preserved():
    """Multi-file packing slots must keep inheriting their own block identity."""
    assert _src().count("packing_file_count") >= 4


# ── Carrier / pre-check semantics ─────────────────────────────────────────

def test_dhl_precheck_offered_only_for_dhl():
    src = _src()
    assert "{carrier === 'DHL' && (" in src
    assert src.index("{carrier === 'DHL' && (") < src.index("new-shipment-save-precheck")


def test_precheck_is_read_only_and_intake_never_writes_to_carriers():
    src = _src()
    assert "getDhlReadiness" in src
    for forbidden in ("createShipment", "createDhlShipment", "wfirma", "sendEmail", "schedulePickup"):
        assert forbidden not in src, f"external write from the intake modal: {forbidden}"
