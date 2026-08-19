"""
AWB modal prefill contract pins (2026-07-06).

Bugs fixed: the prefill read `detail.total_eur` (a key that does not exist on
the composed detail object) so Declared Value was always blank, and Customer
Reference read `draft.doc_no` / `liveDraft.proforma_number` instead of the
canonical `wfirma_proforma_fullnumber` every other panel uses.

These pins hold the corrected sources:
  - Customer Reference  = canonical proforma number (never the batch id)
  - Shipment Reference  = internal batch id (unchanged)
  - Declared Value      = the Overview "Amount due" authority (billed lines
                          total) + the CommercialChargeAuthority same-currency
                          service-charge subtotal
  - Currency            = draft currency
  - Manual override + honest empty hint preserved
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
SRC = JSX.read_text(encoding="utf-8")


def _prefill_block() -> str:
    """The AwbGenerateModal render block including the prefill computation."""
    start = SRC.index("showAwbModal && batchId")
    end = SRC.index("onSuccess={() => { setShowAwbModal(false); loadCarrierShipment(); }}")
    return SRC[start:end]


# ── Customer / Shipment references ────────────────────────────────────────────


def test_customer_reference_uses_canonical_proforma_number():
    block = _prefill_block()
    assert "customer_reference: _awbProformaNo" in block
    # canonical field feeds _awbProformaNo, fullnumber first
    assert "liveDraft.wfirma_proforma_fullnumber" in block


def test_customer_reference_never_uses_batch_id():
    block = _prefill_block()
    ref_line = next(l for l in block.splitlines() if "customer_reference:" in l)
    assert "batchId" not in ref_line
    assert "batch_id" not in ref_line


def test_shipment_reference_still_uses_internal_batch_id():
    block = _prefill_block()
    assert "shipment_reference: batchId || ''" in block


# ── Declared value + currency ─────────────────────────────────────────────────


def test_declared_value_uses_lines_total_authority():
    """Same reduce the Overview 'Amount due' uses — no new calc authority."""
    block = _prefill_block()
    assert "_awbLinesTotal = lines.reduce" in block
    assert "Number(l.netEur)" in block


def test_declared_value_includes_same_currency_service_charges():
    """Charges come from the ONE CommercialChargeAuthority subtotal (PR #923).

    Same-currency-only is enforced inside resolve_commercial_charges()
    (currency_rule: same_currency_only) — the UI must NOT re-sum the raw
    service_charges list.
    """
    block = _prefill_block()
    assert "_awbChargesTotal" in block
    # exact authority read — one source, no fallback re-sum
    assert "Number((liveDraft.commercial_charges || {}).service_charge_subtotal) || 0" in block
    # the old UI re-sum over the raw charge list is gone from the prefill
    assert "liveDraft.service_charges" not in block


def test_declared_value_prefill_derived_not_hardcoded():
    block = _prefill_block()
    assert "declared_value:     _awbDeclared > 0 ? _awbDeclared.toFixed(2) : ''" in block
    # the broken source is gone from the prefill
    assert "detail.total_eur" not in block


def test_currency_prefills_from_draft_currency():
    block = _prefill_block()
    assert "currency:           draftCurrency || 'EUR'" in block


def test_overview_amount_due_authority_unchanged():
    """The page total authority itself is untouched by this fix."""
    assert "const totalEur = lines.reduce((s, l) => s + l.netEur, 0);" in SRC


# ── Override + honest empty state ─────────────────────────────────────────────


def test_declared_value_field_remains_operator_editable():
    m = re.search(r'id="awb-declared_value"[^>]*', SRC)
    assert m and "disabled" not in m.group(0)
    assert "onChange={e => set('declared_value', e.target.value)}" in SRC


def test_missing_total_shows_honest_hint():
    assert 'data-testid="awb-declared-missing-hint"' in SRC
    assert "Declared value not found from proforma total" in SRC
    # hint renders only when the field is empty
    assert "!form.declared_value && (" in SRC


def test_awb_description_prefill_not_hardcoded_jewellery():
    block = _prefill_block()
    assert "_awbShipmentDescriptionFromLines" not in block
    assert "description:        'Jewellery'" not in block
    assert "getCarrierShipmentDescription" in SRC


def test_awb_contact_name_not_hardcoded_empty_only():
    """Contact Full Name may come from ship_to.person — not forced to ''."""
    block = _prefill_block()
    assert "sto.person" in block
    assert "name:               ''," not in block


def test_awb_modal_uses_description_override_dirty_flag():
    """Automatic canonical display must not be posted as body.description."""
    assert "description_override" in SRC
    assert "descriptionDirty" in SRC
    assert "_awbShipmentDescriptionFromLines" not in SRC
    assert "STUD: 'Stud Earrings'" not in SRC


# ── Packed gross weight (2026-08-19) ──────────────────────────────────────────
# Bug: the operator recorded the packed gross weight once in the proforma
# Weights panel (proforma_drafts.manual_gross_weight, already an endpoint + UI),
# and then had to retype it into the AWB modal because the booking modal read no
# weight authority at all. These pins hold the prefill AND the one contract that
# makes it safe: a display-only calculated gross must never become a booked
# shipment weight.


def test_weight_prefills_from_page_weight_authority():
    block = _prefill_block()
    assert "weight_kg:" in block
    assert "_ew.gross" in block


def test_calculated_gross_never_prefills_a_booking():
    """`calculated_net_plus_tare` is display-only by the _transport contract."""
    block = _prefill_block()
    assert "calculated_net_plus_tare" in block
    weight = block[block.index("weight_kg:"):block.index("weight_source:")]
    assert "!==" in weight and "calculated_net_plus_tare" in weight


def test_modal_weight_field_initialises_from_prefill():
    assert "weight_kg:     prefill.weight_kg || ''" in SRC


def test_weight_source_hint_is_honest_when_no_weight_recorded():
    """No recorded weight → name the operator workflow, never invent a number."""
    hint = SRC[SRC.index('data-testid="awb-weight-source-hint"'):]
    hint = hint[:hint.index("</div>")]
    assert "Weights panel" in hint
    assert not re.search(r"\b\d+(\.\d+)?\s*kg\b", hint)
