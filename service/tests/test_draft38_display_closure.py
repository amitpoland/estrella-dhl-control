"""
test_draft38_display_closure.py — Draft #38 workflow-closure display fixes.

Four display/read-only defects on the V2 proforma detail page, fixed without
weakening any backend gate and without any wFirma write:

  1. Reservation tab BATCH LEAK — the reservation-preview top-level
     blocking_reasons is BATCH-scoped (e.g. "84 packing line(s) not yet
     scanned" counts the whole batch's packing). It was merged into the draft's
     reservation display, so a Draft (11 billed lines) appeared to carry an
     84-line blocker. Fix: backend exposes a read-only, NON-gating
     `batch_blocking_reasons` field; the tab renders batch-scope vs draft-scope
     in two clearly-labelled sections.
  2. Currency label — USD draft was shown as EUR in the Lines tab + proforma
     preview. Fix: a single draftCurrency authority drives the Lines tab headers
     and the print layout (no hardcoded EUR).
  3. Freight + insurance — absent from the proforma preview. Fix: surfaced with
     an explicit value OR a "— not set" missing state.
  4. Generate menu — vague disabled reason. Fix: exact gap reference (M4).

Static source-grep only. V2-only; backend change is the read-only field only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_V2     = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "proforma-detail.jsx"
_DOC    = _V2 / "estrella-doc-proforma.jsx"
_RESV   = Path(__file__).resolve().parents[1] / "app" / "services" / "wfirma_reservation.py"


@pytest.fixture(scope="module")
def detail():
    return _DETAIL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc():
    return _DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def resv():
    return _RESV.read_text(encoding="utf-8")


# ── Issue 1 — reservation batch-vs-draft scope separation ─────────────────────

def test_backend_exposes_batch_blocking_reasons(resv):
    # the field is returned (both the normal and the empty-response paths)
    assert '"batch_blocking_reasons": batch_blocking_reasons' in resv
    assert resv.count('"batch_blocking_reasons":') >= 2
    # captured from the warehouse/config blockers BEFORE the per-document
    # client roll-ups are folded into blocking_reasons
    cap    = resv.index("batch_blocking_reasons = list(blocking_reasons)")
    rollup = resv.index('f"{d[\'client_name\']!r}: "')
    assert cap < rollup, "batch_blocking_reasons must be captured before per-doc roll-ups"
    # content isolation: the per-doc roll-up appends to blocking_reasons, never to
    # batch_blocking_reasons — and the capture is a copy (list(...)), so a client
    # roll-up can never leak into the batch-scoped list even on a future refactor.
    assert "batch_blocking_reasons.append(" not in resv, (
        "nothing may append to batch_blocking_reasons — it is a frozen snapshot"
    )
    assert "list(blocking_reasons)" in resv, "batch snapshot must be a copy, not an alias"


def test_backend_batch_field_is_not_gating(resv):
    # the read-only field must not enter the ready_to_create gate
    i = resv.index("ready_to_create = (")
    block = resv[i:i + 200]
    assert "batch_blocking_reasons" not in block, (
        "batch_blocking_reasons is display-only — must NOT affect the create gate"
    )


def test_frontend_splits_batch_and_draft_scope(detail):
    # two scoped lists, sourced from the right authority
    assert "reservationBatchReasons" in detail and "reservationDraftReasons" in detail
    assert "reservationPreview.batch_blocking_reasons" in detail
    assert "reservationDoc && reservationDoc.blocking_reasons" in detail
    # the old leaky combined list is gone
    assert "const reservationReasons = [" not in detail


def test_frontend_labels_each_scope_distinctly(detail):
    assert 'data-testid="reservation-batch-blockers"' in detail
    assert 'data-testid="reservation-draft-blockers"' in detail
    # the batch section is explicitly labelled batch-scope, not draft-scope
    assert "affects all clients in this batch" in detail
    # the create gate is unchanged (canonical reservation readiness)
    assert "reservationPreview.ready_to_create && reservationDoc && reservationDoc.ready" in detail


# ── Issue 2 — currency label (USD not EUR) ────────────────────────────────────

def test_draft_currency_authority(detail):
    assert "const draftCurrency = liveDraft.currency" in detail
    # per-line fallback inherits the draft currency, not a hardcoded EUR
    assert "ln.currency || draftCurrency" in detail
    assert "ln.currency || 'EUR'" not in detail


def test_lines_tab_headers_use_draft_currency(detail):
    # headers are dynamic; the hardcoded EUR header array is gone.
    # Wireframe rebuild Slice 3: headers moved from `UNIT ${cur}`/`NET ${cur}`
    # to the wireframe's `Value ${sym}`/`Total ${sym}` where sym is DERIVED
    # from the draft currency (EUR→€, USD→$, else the code itself). The
    # guarded invariant — amount headers follow the draft currency, never a
    # hardcoded EUR — is unchanged.
    assert "`Value ${sym.trim()}`" in detail and "`Total ${sym.trim()}`" in detail
    assert "const sym = cur === 'USD'" in detail   # sym derives from draft cur
    assert "'UNIT EUR', 'NET EUR'" not in detail
    assert "'Value EUR'" not in detail and "'Total EUR'" not in detail
    # the tab is actually passed the currency (PFW-S5: the call site is now
    # multi-line — anchor on the props, not the exact single-line string)
    import re as _re
    assert _re.search(r"ProformaLinesTab[\s\S]{0,400}?currency=\{draftCurrency\}", detail), \
        "ProformaLinesTab must receive currency={draftCurrency}"


def test_preview_doc_carries_currency(detail):
    assert "currency: draftCurrency," in detail


def test_doc_layout_parameterises_currency(doc):
    # every variant derives currency from data, not a literal
    assert doc.count("const cur = d.currency") >= 3
    # no hardcoded currency column headers remain
    for bad in ("Unit · EUR", "Net · EUR", "Unit EUR", "Net EUR"):
        assert bad not in doc, f"doc layout must not hardcode currency header {bad!r}"
    # FX label uses the draft currency
    assert "1 EUR = " not in doc
    assert "1 ${cur} = " in doc


# ── Issue 3 — freight + insurance shown (value or explicit missing) ───────────

def test_preview_doc_carries_charges(detail):
    assert "previewCharges" in detail
    assert "charge_type" in detail
    # explicit present flag so a missing charge is a state, not a hidden zero
    assert "present:" in detail


def test_doc_layout_renders_charges_with_missing_state(doc):
    # each variant renders the charges (freight/insurance)
    assert doc.count("data-ej-charge=") >= 3
    # missing charge renders an explicit "not set", never silently absent
    assert "— not set" in doc


# ── Issue 4 — Generate menu exact disabled reason ─────────────────────────────

def test_generate_menu_has_exact_gap_reference(detail):
    i = detail.index('data-testid="tb-generate"')
    blk = detail[i - 600:i]
    assert "generate-documents" in blk, "must name the exact missing endpoint"
    assert "M4" in blk, "must reference the backend gap id"
    assert "BACKEND_GAP_REGISTER" in blk, "must point at the gap register"
    # the vague reason is gone
    assert "Document generation not yet available from this view" not in detail
