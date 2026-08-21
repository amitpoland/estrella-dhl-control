"""A posted proforma shows charge facts, not the registry rows behind them.

The Service Charges panel rendered `svc:<wfirma_service_id>` on every charge
line regardless of draft state. That id names the wFirma registry row the charge
maps to -- configuration metadata. Nothing an operator reads on a POSTED
document depends on it, and the panel that manages those mappings is already
hidden once the document is posted, so the annotation outlived its own context.

It is gated, never deleted (Lesson M): the value stays on the draft, in the API,
in the audit trail, and on screen while the draft is still editable -- which is
where the operator actually chooses the mapping.

These tests pin BOTH halves: the id disappears from the posted surface, and the
business facts it sat next to all survive.
"""
from __future__ import annotations

import pathlib

_V2 = pathlib.Path(__file__).parent.parent / "app" / "static" / "v2"
_DETAIL = _V2 / "proforma-detail.jsx"


def _src() -> str:
    return _DETAIL.read_text(encoding="utf-8", errors="replace")


def _charge_row_block() -> str:
    """The per-charge render inside ServiceChargesPanel."""
    src = _src()
    start = src.index("function ServiceChargesPanel(")
    end = src.index("function ", start + 10)
    return src[start:end]


# ── the id is gated off the posted surface ───────────────────────────────────


def test_the_service_registry_id_is_gated_on_canedit():
    block = _charge_row_block()
    assert "canEdit && c.wfirma_service_id" in block, (
        "the wFirma service-product id must render only while the draft is "
        "editable -- a posted document is not a configuration surface"
    )


def test_the_service_registry_id_is_not_rendered_unconditionally():
    block = _charge_row_block()
    assert "{c.wfirma_service_id && (" not in block, (
        "an ungated {c.wfirma_service_id && ...} puts registry metadata back on "
        "the posted business UI"
    )


def test_the_id_is_preserved_not_deleted():
    """Gating must not become removal: the value and its testid still exist."""
    block = _charge_row_block()
    assert "svc:{c.wfirma_service_id}" in block, (
        "the annotation must still exist for the editable context"
    )
    assert "charge-svc-id-" in block, "its testid must survive for the edit surface"


# ── the business facts beside it must survive ────────────────────────────────


def test_charge_amount_and_labels_survive():
    block = _charge_row_block()
    assert "fmtAmt" in block, "charge amounts must still render"
    assert "RES_LABELS[c.resolution]" in block, "resolution labels must survive"


def test_insurance_rate_survives():
    block = _charge_row_block()
    assert "charge-rate-pct-" in block, "the stored insurance rate must stay visible"
    assert "rate:{c.formula_basis.rate_pct}%" in block


def test_insurance_premium_formula_survives():
    block = _charge_row_block()
    assert "charge-premium-" in block, (
        "the basis x rate = premium provenance must stay visible"
    )


def test_the_service_product_registry_panel_stays_canedit_gated():
    """The boundary this change aligns with — do not regress it."""
    src = _src()
    assert "{canEdit && <ServiceProductRegistryPanel />}" in src, (
        "the global registry panel must remain hidden on posted documents"
    )


def test_adr_027_vat_resolution_contract_is_untouched():
    """Guard against collateral damage in the same file."""
    src = _src()
    assert 'data-testid="vat-resolution-detail"' in src


def test_payment_status_scope_language_is_untouched():
    src = _src()
    assert "a proforma has no payment record of its own until it is converted" in src
