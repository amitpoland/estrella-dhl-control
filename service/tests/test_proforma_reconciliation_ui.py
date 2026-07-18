"""test_proforma_reconciliation_ui.py — Campaign-2 A2 Step 3 (frontend, source-grep).

The V2 stack is Babel JSX with no bundler / JS test runner, so — as with the
other V2 pins in this repo — these are Python source assertions over the JSX +
pz-api.js. They pin the reconciliation PRESENTATION panel: it renders the backend
view-model, holds no comparison/recomputation, hides technical metadata, and
wires View/Print to existing document authorities.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
_JSX = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
_API = (_V2 / "pz-api.js").read_text(encoding="utf-8")


def _panel() -> str:
    a = _JSX.index("function ReconciliationPanel({ draft })")
    b = _JSX.index("function ProformaDetailPage(", a)
    return _JSX[a:b]


# ── transport (Lesson F: pz-api.js only) ─────────────────────────────────────

def test_pzapi_reconciliation_transport_is_get_only():
    assert "getDraftReconciliation:" in _API
    assert "/reconciliation`)" in _API
    # transport only — no comparison/inference in the wrapper
    assert "compare_invoice_plan" not in _API
    # EJ source preview URL builder present (reuses existing preview authority)
    assert "draftPreviewHtmlUrl:" in _API and "/preview.html`" in _API


# ── single fetch, keyed on draft load ────────────────────────────────────────

def test_panel_mounted_once():
    assert _JSX.count("<ReconciliationPanel ") == 1


def test_fetch_called_once_per_draft_load():
    p = _panel()
    assert p.count("window.PzApi.getDraftReconciliation(") == 1
    assert "}, [draftId]);" in p          # effect keyed on the draft id


# ── deterministic states ─────────────────────────────────────────────────────

def test_all_states_rendered():
    p = _panel()
    for tid in (
        "pf-recon-loading",              # loading
        "pf-recon-unavailable",          # feature disabled (503)
        "pf-recon-remote-unavailable",   # linked invoice unavailable (502)
        "pf-recon-nolocalauthority",     # no_local_authority
        "pf-recon-match",                # exact match
        "pf-recon-mismatch",             # mismatch
    ):
        assert f'data-testid="{tid}"' in p, f"missing state testid {tid}"
    # classified gap rows use a STABLE field-qualified testid (never index-based)
    assert 'data-testid={`pf-recon-gap-${g.field}`}' in p


def test_status_mapping_is_direct_not_inferred():
    """Panel branches on backend fields (res.status / d.status / d.clean),
    never recomputing them."""
    p = _panel()
    assert "=== 503" in p and "=== 502" in p and "=== 404" in p
    assert "d.status === 'no_local_authority'" in p
    assert "d.clean" in p


# ── shows required fields ────────────────────────────────────────────────────

def test_shows_status_summary_gaps_version_comparedat():
    p = _panel()
    assert 'data-testid="pf-recon-summary"' in p          # gap summary
    assert "d.gap_summary" in p
    assert 'data-testid={`pf-recon-gap-severity-${g.field}`}' in p   # classified: severity
    assert 'data-testid={`pf-recon-gap-policy-${g.field}`}' in p     # classified: policy
    assert "g.field" in p and "g.message" in p            # classified gap fields
    assert 'data-testid="pf-recon-version"' in p and "comparison_version" in p
    assert 'data-testid="pf-recon-comparedat"' in p and "compared_at" in p


# ── document actions reuse existing authorities ──────────────────────────────

def test_document_actions_labelled_ej_and_wfirma():
    p = _panel()
    assert "EJ source document" in p
    assert "Linked wFirma invoice" in p
    for tid in ("pf-recon-doc-ej-view", "pf-recon-doc-ej-print",
                "pf-recon-doc-wfirma-view", "pf-recon-doc-wfirma-print"):
        assert f'data-testid="{tid}"' in p
    # EJ = existing local preview authority; wFirma = existing invoice pdf authority
    assert "draftPreviewHtmlUrl(draftId)" in p
    assert "draftInvoicePdfUrl(draftId)" in p
    # shared Btn component (not raw <button>), per the frontend design standard
    assert "<Btn" in p


def test_wfirma_actions_disabled_without_linked_invoice():
    """The linked-wFirma View/Print actions must be disabled (with a reason) when
    no invoice is linked, so the operator is never sent to a 404. EJ source stays
    available. Linked-ness is derived from the backend status, not inferred."""
    p = _panel()
    assert "hasLinkedInvoice" in p and "'reconciled'" in p
    assert "disabled={!hasLinkedInvoice}" in p
    assert 'data-testid="pf-recon-wfirma-disabled-reason"' in p


# ── no technical metadata surfaced ───────────────────────────────────────────

def test_no_hashes_or_internal_ids_displayed():
    p = _panel()
    for tok in ("local_source_hash", "remote_snapshot_hash", "remote_document_id"):
        assert tok not in p, f"panel must not surface technical field {tok}"


# ── no frontend reconciliation calculation ───────────────────────────────────

def test_no_frontend_reconciliation_calculation():
    p = _panel()
    assert "compare_invoice_plan" not in p
    assert ".reduce(" not in p          # no client-side gap aggregation
    # it renders backend-provided summary/gaps, not a recomputed one
    assert "d.gaps" in p and "d.gap_summary" in p
