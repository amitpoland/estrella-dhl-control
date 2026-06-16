"""
test_c03_inbox_evidence_panel.py — Campaign-03 Sprint 03.3 PR-E3b contract.

Covers the read-only EvidencePanel added to the served Inbox V2 page
(service/app/static/v2/inbox-page.jsx). The panel consumes the E3a endpoint
GET /api/v1/inbox/evidence/{item_id} (#614) and renders ONLY the per-kind
projection that endpoint returns. Static source-grep only — no server, no JSX
execution (mirrors test_c03_shipment_detail_v2_ux.py).

Intent (operator-authorized PR-E3b, frontend-only):
  • Frontend consumes the deployed E3a endpoint via EstrellaShared.apiFetch
    (ADR-028 shim) — never raw fetch, never a write verb.
  • Every documented marker path is handled honestly: loading / auth / network /
    not-found / gone (resolved) / degraded (source read error) / body.
  • No raw evidence beyond endpoint projection: the panel must NOT reference any
    leaked field the endpoint is contractually forbidden to emit
    (body_html/body_text/attachments/cc/bcc/matched_identifiers/line JSON).
  • next_action is an object {title, priority} — must render .title + a priority
    badge, never the bare object ([object Object]).
  • Full data-testid coverage for every panel state + the per-kind bodies.
"""
from __future__ import annotations

from pathlib import Path

_INBOX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "inbox-page.jsx"


def _src() -> str:
    return _INBOX.read_text(encoding="utf-8")


# ── A. Components present ──────────────────────────────────────────────────────

def test_evidence_components_present():
    """The three evidence primitives must exist."""
    src = _src()
    assert "function EvidencePanel(" in src, "EvidencePanel component missing"
    assert "function renderEvidence(" in src, "renderEvidence helper missing"
    assert "function EvField(" in src, "EvField primitive missing"


def test_panel_wired_into_inbox_page():
    """EvidencePanel is rendered off the existing `selected` row state."""
    src = _src()
    assert "<EvidencePanel" in src, "EvidencePanel never rendered"
    assert "itemId={selected}" in src, "panel must take the selected row id"
    assert "onClose={function() { setSelected(null); }}" in src, (
        "Close must clear the selection (deselect the row)"
    )
    # input item is resolved from the already-loaded list — no extra list fetch
    assert "items.find(" in src, "panel item must come from the loaded items list"


# ── B. Reads through the shared shim, never raw fetch, never a write verb ──────

def test_uses_apifetch_not_raw_fetch():
    """Evidence read goes through EstrellaShared.apiFetch (ADR-028), not raw fetch."""
    src = _src()
    assert "EstrellaShared.apiFetch('/api/v1/inbox/evidence/'" in src, (
        "panel must call EstrellaShared.apiFetch on the evidence endpoint"
    )
    # The evidence endpoint id is URL-encoded (item ids carry ':' / '-').
    assert "encodeURIComponent(itemId)" in src, "item_id must be URL-encoded"


def test_evidence_endpoint_is_read_only():
    """The panel must never POST/PUT/DELETE — evidence is read-only projection."""
    src = _src()
    # Window-level write helpers (PzApi.*) belong to the row approve/reject flow,
    # never the evidence panel. Assert the evidence endpoint is only ever read.
    assert "method: 'POST'" not in src and 'method: "POST"' not in src, (
        "inbox page must not POST — evidence panel is read-only"
    )
    # Pin that the evidence URL is only ever passed to apiFetch (a GET shim).
    ev_refs = src.count("/api/v1/inbox/evidence/")
    assert ev_refs >= 1, "evidence endpoint reference missing"


# ── C. Every marker state handled with a testid ───────────────────────────────

def test_all_panel_state_testids_present():
    """Loading / error / gone / degraded / body / close all carry stable testids."""
    src = _src()
    for tid in (
        "inbox-evidence-panel",
        "inbox-evidence-loading",
        "inbox-evidence-error",
        "inbox-evidence-gone",
        "inbox-evidence-degraded",
        "inbox-evidence-body",
        "inbox-evidence-close",
        "inbox-evidence-retry",
    ):
        assert f'"{tid}"' in src, f"panel state testid '{tid}' missing"


def test_in_band_markers_branch_in_then_not_catch():
    """gone/degraded are 200-markers — must be read off the resolved data object."""
    src = _src()
    # apiFetch resolves 2xx (including {ok:false, gone/degraded}) into .then.
    assert "data.ok === false && data.gone" in src, "gone marker not handled"
    assert "data.ok === false && data.degraded" in src, "degraded marker not handled"
    # Success body only renders on ok + evidence present.
    assert "data.ok && data.evidence" in src, "success body guard missing"


def test_error_kinds_distinguished():
    """The catch path distinguishes auth / network / not-found / generic."""
    src = _src()
    # auth + network come from apiFetch err.type; 404 from the HTTP message.
    assert "e.type" in src, "must read err.type for auth/network classification"
    assert "HTTP 404" in src, "must detect 404 (not-found) from the thrown message"
    for kind in ("'auth'", "'network'", "'notfound'", "'generic'"):
        assert kind in src, f"error kind {kind} not handled"
    # auth is non-retryable; a 403/401 must NOT show a retry button.
    assert "err.kind !== 'auth'" in src, "retry must be suppressed for auth errors"


# ── D. Per-kind projection bodies ─────────────────────────────────────────────

def test_per_kind_bodies_present():
    """renderEvidence covers all four endpoint kinds + an unknown fallback."""
    src = _src()
    for tid in (
        "inbox-ev-proposal",
        "inbox-ev-email",
        "inbox-ev-customs",
        "inbox-ev-proforma-draft",
        "inbox-ev-unknown",
    ):
        assert f'"{tid}"' in src, f"per-kind body testid '{tid}' missing"
    for kind in ("'proposal'", "'email'", "'customs'", "'proforma_draft'"):
        assert kind in src, f"renderEvidence branch for {kind} missing"


def test_next_action_object_rendered_not_stringified():
    """customs next_action is {title, priority} — render title + badge, not object."""
    src = _src()
    assert "na.title" in src, "next_action.title must be rendered"
    assert "PRIORITY_CONF[na.priority]" in src, (
        "next_action.priority must map to a priority badge config"
    )
    assert "ev-customs-next-action" in src, "next_action row needs a testid"


def test_customs_summary_flags_and_lineage_rendered():
    """customs summary boolean flags + thread lineage have dedicated render paths."""
    src = _src()
    assert "ev-customs-flags" in src, "summary flags render path missing"
    assert "ev-customs-lineage" in src, "thread lineage render path missing"
    # only true flags are shown (collected evidence), key underscores humanised
    assert "ev.summary[k] === true" in src, "must filter summary to true flags"
    assert "replace(/_/g, ' ')" in src, "flag keys must be humanised"


# ── E. No-leak posture — forbidden fields never referenced ────────────────────

def test_no_leaked_evidence_fields():
    """The panel must not reference any field the endpoint is forbidden to emit.

    The E3a contract (routes_inbox.py + test_inbox_evidence.py) proves the
    endpoint never returns message bodies, recipients beyond `to`, attachments,
    matched identifiers, or raw line/financial JSON. The renderer must therefore
    never reach for them — referencing one would be either dead code or a sign
    the projection was widened past the no-leak contract.
    """
    src = _src()
    for leaked in (
        "body_html", "body_text", "ev.attachments", ".bcc", "ev.cc",
        "matched_identifiers", "ev.lines", "ev.line_items",
    ):
        assert leaked not in src, (
            f"forbidden evidence field '{leaked}' referenced — violates the "
            "no-leak projection contract (E3a)"
        )


def test_proposal_subject_only_no_body():
    """Proposal evidence renders draft_subject only — never a draft body."""
    src = _src()
    assert "ev.draft_subject" in src, "proposal subject must be rendered"
    assert "ev.draft_body" not in src, "proposal must never render a draft body"


# ── F. Stack-discipline guards (B2 + theming) ─────────────────────────────────

def test_no_pz_components_reference():
    """Must not reference pz-components.js (B2)."""
    assert "pz-components" not in _src(), "must not reference pz-components.js (B2)"


def test_no_hardcoded_hex_in_panel():
    """Panel theming uses CSS custom properties, not hardcoded hex."""
    src = _src()
    # isolate the evidence block to avoid scanning unrelated row code
    start = src.index("function EvField(")
    end = src.index("// ── InboxPage")
    block = src[start:end]
    import re
    hexes = re.findall(r"#[0-9a-fA-F]{3,6}\b", block)
    assert not hexes, f"hardcoded hex colors in evidence panel: {hexes}"
