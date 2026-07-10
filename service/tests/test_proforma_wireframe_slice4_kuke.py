"""test_proforma_wireframe_slice4_kuke.py — Proforma wireframe rebuild Slice 4.

Pins for the VAT & Insurance (KUKE) Overview panel: display-only wiring of the
Slice-1 vat_code/vat_context draft keys plus Customer Master KUKE fields via
the EXISTING PzApi.getCustomerMaster call (one fetch per draft). The panel is
purely informational (Lesson N): a missing contractor id, missing master row,
or failed fetch renders '—' and never blocks or gates anything. Premium is a
display-only estimate (goods total × insurance_rate), never persisted.
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = (Path(__file__).resolve().parent.parent
       / "app" / "static" / "v2" / "proforma-detail.jsx")


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def _panel(src: str) -> str:
    start = src.index("function VatInsurancePanel(")
    m = re.search(r"\nfunction [A-Za-z_]", src[start + 10:])
    return src[start:start + 10 + (m.start() if m else len(src) - start)]


def test_panel_exists_with_wireframe_structure():
    src = _src()
    assert "function VatInsurancePanel(" in src
    assert 'data-testid="pf-vat-insurance"' in src
    assert "VAT &amp; Insurance (KUKE)" in src
    assert 'data-testid="pf-kuke-premium"' in src


def test_panel_rendered_in_overview_with_slice1_keys():
    """The render call passes the Slice-1 additive draft keys + contractor id."""
    src = _src()
    call = src[src.index("<VatInsurancePanel"):]
    call = call[:call.index("/>")]
    for prop in ("contractorId={detail.client_contractor_id}",
                 "vatCode={detail.vat_code}",
                 "vatContext={detail.vat_context}",
                 "totalEur={totalEur}",
                 "currency={currency}"):
        assert prop in call, f"render call missing {prop}"


def test_fetch_uses_existing_customer_master_api():
    """One fetch via the EXISTING PzApi.getCustomerMaster — the same wrapper
    the AWB modal uses. No new endpoint, no new wrapper."""
    panel = _panel(_src())
    assert "window.PzApi.getCustomerMaster(contractorId)" in panel
    # no direct apiFetch to a new endpoint inside the panel
    assert "apiFetch" not in panel


def test_fetch_failure_and_missing_id_fall_back_safely():
    panel = _panel(_src())
    assert "setMasterFetch('missing-id')" in panel      # no contractor id
    assert "setMasterFetch('failed')" in panel          # non-ok response
    assert ".catch(() => setMasterFetch('failed'))" in panel  # network failure
    assert 'data-testid="pf-kuke-fetch-failed"' in panel      # fail-visible note
    # every KUKE field carries the '—' fallback
    for token in ("m.kuke_policy_number || '—'",
                  "const kukeApproved = m.kuke_approved === true ? 'Yes' : "
                  "m.kuke_approved === false ? 'No' : '—'"):
        assert token in panel, f"missing '—' fallback: {token}"


def test_missing_master_row_renders_dashes():
    """Fields read from an EMPTY object when not loaded — masterFetch gates the
    projection, so failed/missing states can never show stale values."""
    panel = _panel(_src())
    assert "masterFetch === 'loaded' ? (master || {}) : {}" in panel


def test_vat_label_mapping():
    src = _src()
    labels = src[src.index("const PF_VAT_LABELS"):]
    labels = labels[:labels.index("};") + 2]
    assert "WDT:  '0% WDT — intra-EU supply'" in labels
    assert "EXP:  '0% Export'" in labels
    assert "'23': '23% domestic'" in labels
    # unknown codes fall back to the raw code; absent code renders '—'
    panel = _panel(src)
    assert "PF_VAT_LABELS[String(vatCode)] || String(vatCode)" in panel
    assert "vatCode ? " in panel and ": '—'" in panel


def test_premium_is_display_only():
    panel = _panel(_src())
    assert "Premium (display-only)" in panel
    assert "(totalEur * rate).toFixed(2)" in panel
    assert "(est.)" in panel
    # the panel performs NO writes: no PATCH/POST/save call of any kind
    for forbidden in ("patchDraft", "saveCustomerMaster", "applyServiceCharges",
                      "method: 'POST'", "method: 'PATCH'"):
        assert forbidden not in panel, f"display-only panel must not call {forbidden}"


def test_panel_never_feeds_readiness_or_gates():
    """Lesson N: the panel is informational. VatInsurancePanel appears exactly
    twice (definition + Overview render) and its state never reaches the gate
    variables."""
    src = _src()
    assert len(re.findall(r"\bVatInsurancePanel\b", src)) == 2
    gates = src[src.index("const canPost"):src.index("const canPost") + 2500]
    assert "masterFetch" not in gates and "VatInsurance" not in gates
