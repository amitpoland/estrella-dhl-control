"""
test_invoice_projection_convergence.py — one invoice-link authority per UI projection.

Incident (operator, 2026-07-17): a single draft rendered four mutually
contradictory projections at the same time —

    "Invoice Created — wFirma invoice WDT 144/2026 · 2026-07-14"   (invoice exists)
    "⚠ Convert to Invoice"                                          (amber, reads actionable)
    lifecycle step "Invoiced" NOT complete
    header "Ready / Next: Review draft"

Root cause — NOT a backend defect. The canonical lifecycle vocabulary is
proforma_invoice_link_db.DRAFT_LIFECYCLE_STATES, whose terminal member is
'converted'. The V2 page never learned that:

  * ProformaStatusHeader keyed terminal state on `draft_state === 'posted' ||
    draft_state === 'invoiced'` — 'converted' absent, so a converted draft fell
    through every branch to pill "Ready" / nextAction "Review draft".
  * WorkflowRail had an off-by-one: an invoice set rank = 3, but `done = i < rank`
    means stage index 3 ("Invoiced") needs rank >= 4. The terminal stage was
    structurally unreachable — it had never rendered a checkmark for anyone.
  * PF_STATUS_CHIP had no 'converted' key at all (chip silently vanished) and
    carried an invented 'issued' key.
  * 'ready' and 'invoiced' appear in the V2 conditionals but exist NOWHERE in
    DRAFT_LIFECYCLE_STATES — dead branches masquerading as logic.

The repair routes every invoice-dependent projection through ONE derived
authority, `deriveInvoiceProjection(liveDraft)`, so the contradictory state is
structurally unrepresentable rather than merely absent today.

Assertions are source-text (no browser, no server), following the established
repo pattern of test_convert_modal_truth.py / test_proforma_readiness_single_authority.py.

Every pin in this file FAILS at 90e79267 and passes after the correction.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
JSX = _V2 / "proforma-detail.jsx"
SRC = JSX.read_text(encoding="utf-8")
INDEX_HTML = (_V2 / "index.html").read_text(encoding="utf-8")


def _block(fn_signature: str, src: str = "") -> str:
    """Slice a top-level function body: from its signature to the next
    top-level `function ` declaration (or the window export at EOF)."""
    haystack = src or SRC
    start = haystack.index(fn_signature)
    nxt = haystack.find("\nfunction ", start + len(fn_signature))
    end = haystack.index("Object.assign(window,", start) if nxt == -1 else nxt
    return haystack[start:end]


# ── Pin 1: the single authority exists and is reachable ──────────────────────

def test_derive_invoice_projection_exists():
    """The ONE derivation every invoice projection must route through."""
    assert "function deriveInvoiceProjection(" in SRC, (
        "deriveInvoiceProjection() is the single invoice-link authority for this "
        "page — without it each projection re-derives its own truth and they drift."
    )


def test_derive_invoice_projection_is_window_exported():
    """Exported so the projection can be exercised outside the page."""
    export = SRC[SRC.index("Object.assign(window,"):]
    assert "deriveInvoiceProjection" in export, (
        "deriveInvoiceProjection must be window-exported alongside ProformaDetailPage."
    )


def test_derive_invoice_projection_reads_the_draft_mirror_fields():
    """The mirror of proforma_invoice_links written by persist_invoice_to_draft()."""
    block = _block("function deriveInvoiceProjection(")
    for field in ("wfirma_invoice_id", "wfirma_invoice_number",
                  "converted_at", "draft_state"):
        assert field in block, (
            f"deriveInvoiceProjection must read {field!r} — it is the draft-side "
            "mirror of the canonical proforma_invoice_links row."
        )
    assert "'converted'" in block, (
        "deriveInvoiceProjection must recognise the terminal lifecycle state "
        "'converted' (DRAFT_LIFECYCLE_STATES) — this is the whole defect."
    )


# ── Pin 2: convergence — no projection re-derives its own truth ──────────────

def test_page_derives_the_projection_exactly_once():
    """One useMemo in ProformaDetailPage; every consumer takes it as a prop."""
    assert SRC.count("deriveInvoiceProjection(liveDraft)") == 1, (
        "The projection must be derived ONCE in ProformaDetailPage and threaded "
        "down. A second derivation site is a second authority."
    )


def test_workflow_rail_consumes_the_projection_not_raw_fields():
    """CONVERGENCE PIN — the rail must not re-derive 'invoiced' locally."""
    signature = SRC[SRC.index("function WorkflowRail("):]
    signature = signature[:signature.index(")")]
    assert "invoiced" in signature, (
        "WorkflowRail must take the derived `invoiced` signal as a prop — "
        f"got signature: {signature!r}"
    )
    assert "wfirmaInvoiceId" not in signature, (
        "WorkflowRail must NOT take the raw wfirma_invoice_id — it is a second "
        "authority. Consume the derived projection instead."
    )


def test_status_header_consumes_the_projection_not_draft_state():
    """CONVERGENCE PIN — the header read ONLY draft_state; that was the split."""
    block = _block("function ProformaStatusHeader(")
    assert "invoiceProjection" in block, (
        "ProformaStatusHeader must consume invoiceProjection. Keying terminal "
        "state on draft_state alone is exactly what produced "
        "'Ready / Next: Review draft' on a converted draft."
    )


def test_toolbar_gate_consumes_the_projection():
    """CONVERGENCE PIN — alreadyConverted must come from the one authority."""
    assert "invoiceProjection.invoiced" in SRC, (
        "The convert gate must derive from invoiceProjection.invoiced."
    )
    assert "!!(liveDraft.wfirma_invoice_id) || draftState === 'converted'" not in SRC, (
        "The old inline re-derivation of alreadyConverted must be gone — it is a "
        "parallel authority to deriveInvoiceProjection."
    )


# ── Pin 3: the rail off-by-one — 'Invoiced ✓' must be reachable ──────────────

def test_workflow_rail_terminal_stage_is_reachable():
    """
    stages = ['Review','Approved','Posted','Invoiced'] -> 'Invoiced' is index 3.
    done = i < rank, so rank must reach 4 for index 3 to render its checkmark.
    Capping rank at 3 made the terminal stage structurally unreachable.
    """
    block = _block("function WorkflowRail(")
    assert "converted: 4" in block, (
        "RANK.converted must be 4 — with `done = i < rank`, a rank of 3 can never "
        "mark stage index 3 ('Invoiced') as done."
    )
    assert "rank = 4" in block, (
        "An existing invoice must promote rank to 4 so 'Invoiced' renders as done."
    )
    assert "rank = 3" not in block, (
        "The rank-3 ceiling is the off-by-one that hid 'Invoiced ✓' from every user."
    )


# ── Pin 4: header shows the terminal truth, ahead of alreadyPosted ───────────

def test_status_header_has_invoiced_pill_and_open_invoice_next_action():
    block = _block("function ProformaStatusHeader(")
    assert "'Invoiced'" in block, (
        "The header pill must be able to say 'Invoiced' — a converted draft "
        "reported the readiness pill 'Ready' instead."
    )
    assert "Open invoice in wFirma" in block, (
        "nextAction on an invoiced draft must be the follow-up action, not the "
        "fallthrough 'Review draft'."
    )


def test_status_header_checks_the_invoice_before_already_posted():
    """Precedence matters: alreadyPosted is false for 'converted'."""
    block = _block("function ProformaStatusHeader(")
    assert block.index("invoiceProjection") < block.index("alreadyPosted"), (
        "invoiceProjection must be consulted BEFORE alreadyPosted in the pill "
        "chain, otherwise a converted draft falls through to the readiness pill."
    )


# ── Pin 5: invented lifecycle states are gone ────────────────────────────────

def test_pf_status_chip_knows_the_terminal_state():
    chip = SRC[SRC.index("const PF_STATUS_CHIP = {"):SRC.index("function PfProformaStatusChip(")]
    assert "converted:" in chip, (
        "PF_STATUS_CHIP had no 'converted' key, so PfProformaStatusChip returned "
        "null and the lifecycle chip silently disappeared on converted drafts."
    )


def test_invented_lifecycle_states_removed():
    """'ready' and 'invoiced' are not in DRAFT_LIFECYCLE_STATES."""
    assert "draftState === 'ready'" not in SRC, (
        "'ready' is not a real draft_state — dead branch."
    )
    assert "draftState === 'invoiced'" not in SRC, (
        "'invoiced' is not a real draft_state — the alreadyPosted check that used "
        "it could never fire, which is why the header never saw a terminal draft."
    )


def test_lifecycle_vocabulary_matches_the_backend():
    """The V2 chip map must not invent states the page can never observe.

    `draftState` is `draft_state || legacy status`, so the observable vocabulary
    is DRAFT_LIFECYCLE_STATES plus the legacy `status` aliases that fallback can
    still surface. 'issued' is such an alias (proforma_invoice_link_db backfills
    status='issued' → draft_state='posted'), so it is legitimate — and dropping
    it would re-create the vanishing-chip bug for any row the backfill missed.
    Anything outside both sets is dead code pretending to be logic.
    """
    from app.services.proforma_invoice_link_db import DRAFT_LIFECYCLE_STATES
    LEGACY_STATUS_ALIASES = {"issued"}
    observable = set(DRAFT_LIFECYCLE_STATES) | LEGACY_STATUS_ALIASES
    chip = SRC[SRC.index("const PF_STATUS_CHIP = {"):SRC.index("function PfProformaStatusChip(")]
    for line in chip.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if not key.isidentifier() or key in ("label", "bg", "text", "border"):
            continue
        assert key in observable, (
            f"PF_STATUS_CHIP key {key!r} is neither a DRAFT_LIFECYCLE_STATE "
            f"{DRAFT_LIFECYCLE_STATES} nor a known legacy status alias "
            f"{LEGACY_STATUS_ALIASES} — the page is inventing a lifecycle state."
        )


# ── Pin 6: post-conversion re-fetch (optimistic UI is insufficient) ──────────

def test_convert_success_reloads_the_draft():
    """Criterion 2: conversion success must re-fetch the canonical state."""
    start = SRC.index("<ConvertToInvoiceModal")
    block = SRC[start:SRC.index("/>", start)]
    assert "draftHook.reload()" in block, (
        "Convert onSuccess must call draftHook.reload() — optimistic UI alone "
        "leaves the page showing pre-conversion truth."
    )


def test_no_phantom_refresh_calls_remain():
    """pz-state.js `_useApiCall` returns { ...state, reload } — there is no
    `refresh`. Every `draftHook.refresh && draftHook.refresh()` is a silent no-op."""
    state_src = (_V2 / "pz-state.js").read_text(encoding="utf-8")
    assert "refresh:" not in state_src, (
        "pz-state.js grew a `refresh` — this pin assumes `reload` is the only API."
    )
    assert "draftHook.refresh" not in SRC, (
        "draftHook.refresh does not exist (pz-state.js exposes `reload`), so the "
        "guarded call silently no-ops and the draft is never re-fetched."
    )


def test_convert_success_path_is_not_a_stub():
    """The real conversion path popped an alert and navigated away."""
    assert "(stub)" not in INDEX_HTML, (
        "index.html onConvert still fires alert('… Invoice created (stub)') and "
        "navigates off the page on a REAL conversion — the operator never sees "
        "the converged state."
    )


# ── Pin 7: follow-up action + Lesson M (no capability suppression) ───────────

def test_view_invoice_action_present():
    assert 'data-testid="tb-view-invoice"' in SRC, (
        "An invoiced draft's primary follow-up action must be View/Open wFirma Invoice."
    )


def test_convert_button_still_rendered_lesson_m():
    """Lesson M: a converted proforma's convert capability is 'unavailable',
    not suppressed. It stays rendered with an honest disabled reason."""
    assert 'data-testid="tb-convert"' in SRC, (
        "tb-convert must remain rendered — hiding it is capability suppression "
        "requiring a formal cancellation record in PROJECT_STATE.md DECISIONS."
    )
    assert "Already converted — invoice" in SRC, (
        "The disabled reason must name what already happened."
    )


# ── Pin 8: split-brain gate must not hide a stale projection ─────────────────

def test_split_brain_gate_keys_on_full_health():
    """
    The backend classifies 'stale_draft_projection' when an issued link's draft
    mirror disagrees — INCLUDING the case where wfirma_invoice_id matches but
    draft_state is still 'posted'. Bailing on a truthy wfirma_invoice_id alone
    suppressed the recovery panel for exactly that case.

    The health test must mirror the backend's: id present AND state 'converted'.
    """
    health = SRC[SRC.index("const _projectionHealthy"):]
    health = health[:health.index(";")]
    assert "wfirma_invoice_id" in health and "'converted'" in health, (
        "The split-brain skip condition must require BOTH a linked invoice id "
        f"AND draft_state === 'converted'. Got: {health!r}"
    )

    gate = SRC[SRC.index("const loadSplitBrain"):]
    gate = gate[:gate.index("React.useEffect")]
    assert "_projectionHealthy" in gate, (
        "loadSplitBrain must skip on the full-health test, not on a bare "
        "wfirma_invoice_id — that hid the stale_draft_projection the backend "
        "is specifically built to detect."
    )
    assert "|| liveDraft.wfirma_invoice_id ||" not in gate, (
        "The old bare-id bail-out must be gone."
    )
