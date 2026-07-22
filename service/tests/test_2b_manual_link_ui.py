"""test_2b_manual_link_ui.py — Campaign-2 · Phase 2B (frontend, source-grep).

The V2 stack is Babel JSX with no bundler / JS test runner, so — as with the
other V2 pins — these are Python source assertions over the ManualLinkPanel JSX +
pz-api.js. They pin: canonical PZ API transport only; NO internal id / hash
rendered as business data; confirmation requires an explicit operator action;
disabled / refused states show business-readable reasons; a successful confirm
reloads the canonical draft rather than inventing local state.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
_JSX = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
_API = (_V2 / "pz-api.js").read_text(encoding="utf-8")


def _panel() -> str:
    a = _JSX.index("function ManualLinkPanel(")
    b = _JSX.index("function ProformaDetailPage(", a)
    return _JSX[a:b]


# ── transport (Lesson F: pz-api.js only, transport-only) ─────────────────────

def test_pzapi_has_manual_link_transport():
    assert "resolveWfirmaDocument:" in _API
    assert "confirmWfirmaLink:" in _API
    assert "/resolve-wfirma-document`" in _API
    assert "/confirm-wfirma-link`" in _API


def test_pzapi_read_vs_write_verbs():
    # resolve is a read-like POST (no X-Operator); confirm is a mutation POST.
    assert "resolveWfirmaDocument: (draftId, body) =>\n      _post(" in _API
    assert "confirmWfirmaLink: (draftId, body) =>\n      _postM(" in _API


def test_pzapi_no_comparison_or_hash_construction():
    # the backend owns comparison + the opaque preview_hash; the wrapper builds
    # none (it only echoes expected_preview_hash back on the confirm round-trip).
    for banned in ("compare_invoice_plan", "sha256", "createHash", "hashlib"):
        assert banned not in _API


# ── panel uses the canonical transport only (no direct fetch) ────────────────

def test_panel_uses_pzapi_only():
    p = _panel()
    assert "window.PzApi.resolveWfirmaDocument(" in p
    assert "window.PzApi.confirmWfirmaLink(" in p
    assert "fetch(" not in p          # no second transport path
    assert "XMLHttpRequest" not in p


def test_panel_mounted_once():
    assert _JSX.count("<ManualLinkPanel ") == 1


# ── no internal id / hash rendered as business data ──────────────────────────

def test_panel_renders_no_internal_ids():
    p = _panel()
    for banned in ("series_id", "company_account_id", "contractor_id",
                   "contractor_receiver_id", "good_id", "remote_document_id"):
        assert banned not in p


def test_panel_does_not_render_preview_hash():
    p = _panel()
    # the hash is a round-trip token echoed in the confirm body ONLY; it is never
    # rendered to the DOM (no ">{...hash}" text node, no hash in a title/tooltip).
    assert "expected_preview_hash: st.hash" in p     # round-tripped in the body
    assert ">{st.hash}" not in p and "{st.hash}<" not in p
    assert "title={st.hash" not in p


# ── confirmation requires an explicit operator action ────────────────────────

def test_confirm_requires_explicit_action():
    p = _panel()
    assert 'data-testid="pf-link-confirm"' in p
    assert "onClick={onConfirm}" in p
    # the confirm button is disabled until a valid preview hash exists (no
    # auto-confirm, no confirm without a fresh preview)
    assert "disabled={confirming || !st.hash}" in p
    # preview is a distinct explicit step
    assert 'data-testid="pf-link-preview"' in p and "onClick={onPreview}" in p


# ── disabled / refused states show business-readable reasons ─────────────────

def test_refused_states_show_business_reasons():
    p = _panel()
    assert 'data-testid="pf-link-error"' in p
    assert "{st.error}" in p                          # surfaces the server reason
    # irreversibility disclosure before the write
    assert "cannot be undone" in p


# ── success reloads the CANONICAL draft (never invents local state) ──────────

def test_success_reloads_canonical_draft():
    p = _panel()
    assert "draftHook.reload()" in p
    # success is gated on the server's own ok+status, not a locally-fabricated one
    assert "res.ok && res.data && res.data.ok" in p


# ── panel is scoped to eligible drafts only ──────────────────────────────────

def test_panel_gated_on_posted_proforma():
    p = _panel()
    assert "draft.wfirma_proforma_id" in p
    assert "if (!hasProforma) return null;" in p
