"""
test_dashboard_proforma_draft_panel.py — Phase 6 dashboard wiring.

Source-grep coverage for the new local editable Proforma Draft panel
in service/app/static/dashboard.html. We don't run the SPA in tests;
instead we pin the wiring contract by string-searching the HTML for
the expected endpoints, tokens, and gating logic.

Each test pins one rule from the Phase 6 task spec.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DASHBOARD = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


@pytest.fixture(scope="module")
def html() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── 1. List endpoint is read ────────────────────────────────────────────────

def test_list_drafts_endpoint_is_called(html):
    # The panel reads GET /api/v1/proforma/drafts/{batchId}
    assert "/api/v1/proforma/drafts/" in html, \
        "ProformaDraftPanel must read GET /api/v1/proforma/drafts/{batch_id}"


def test_list_endpoint_is_only_called_via_get(html):
    # The list endpoint must NOT be invoked with method:'POST' / 'PATCH' / 'DELETE'.
    # If ANY call to /drafts/{batchId} appears alongside a write method on the
    # same line block, fail.
    bad = re.search(
        r"/api/v1/proforma/drafts/[^/'\"]+(?:'\s*\+\s*[^,]+)?[^}]{0,200}method:\s*['\"](?:POST|PATCH|DELETE)",
        html,
    )
    assert bad is None, (
        "GET /api/v1/proforma/drafts/{batch_id} must not be called with a write "
        "method"
    )


# ── 2. Single-draft + events endpoints ──────────────────────────────────────

def test_single_draft_endpoint_referenced(html):
    assert "/api/v1/proforma/draft/${" in html or "`/api/v1/proforma/draft/${" in html
    # Specifically the read pattern (no '/lines/' or '/service-charges/' or
    # '/approve' on the same template-literal segment).
    assert re.search(r"`/api/v1/proforma/draft/\$\{(?:openId|draftId)\}`", html), (
        "GET /api/v1/proforma/draft/{id} must be called with a clean template "
        "literal — no trailing path"
    )


def test_events_endpoint_referenced(html):
    assert re.search(r"`/api/v1/proforma/draft/\$\{(?:openId|draftId)\}/events`", html)


# ── 3. Edit calls send X-Operator + expected_updated_at ─────────────────────

def test_write_call_helper_sends_x_operator(html):
    # The wrapper helper that all mutations go through must inject X-Operator.
    assert "'X-Operator': op" in html or "'X-Operator': _op" in html, (
        "Mutation calls must include the X-Operator header"
    )


def test_every_mutation_sends_expected_updated_at(html):
    # Every mutation we know about must reference expected_updated_at in the
    # body or query. We check by counting: each mutation handler should
    # appear within ~10 lines of an expected_updated_at reference.
    write_endpoints = [
        "PATCH",         # PATCH /draft/{id}
        "approve",       # POST /draft/{id}/approve
        "re-open",       # POST /draft/{id}/re-open
        "cancel",        # POST /draft/{id}/cancel
        "reset-from-sales-packing",
        "lines/${lineId}",      # PATCH /draft/{id}/lines/{line_id}
        "service-charges",
        "/post`",        # POST /draft/{id}/post
    ]
    for needle in write_endpoints:
        assert needle in html, f"missing expected mutation reference: {needle!r}"
    # And expected_updated_at must appear at least once for every distinct
    # mutation site.
    occurrences = html.count("expected_updated_at")
    assert occurrences >= 8, (
        f"expected_updated_at appears {occurrences} times — every mutation "
        "must include it (PATCH/lines, PATCH/draft, charges add/remove, "
        "approve, reopen, cancel, reset, post)"
    )


# ── 4-5. Confirm tokens for approve / reopen ───────────────────────────────

def test_approve_token_is_required_and_exact(html):
    assert "YES_APPROVE_LOCAL_PROFORMA_DRAFT" in html
    # Must be checked literally, not just embedded in a URL.
    assert re.search(
        r"token\s*!==\s*PROFORMA_DRAFT_TOKENS\.approve",
        html,
    ), "Approve flow must compare typed token against the exact constant"


def test_reopen_token_is_required_and_exact(html):
    assert "YES_REOPEN_LOCAL_PROFORMA_DRAFT" in html
    assert re.search(
        r"token\s*!==\s*PROFORMA_DRAFT_TOKENS\.reopen",
        html,
    ), "Re-open flow must compare typed token against the exact constant"


# ── 6. Post button visibility — only for approved state ─────────────────────

def test_post_button_only_visible_for_approved_state(html):
    # The post button must be wrapped in a state==='approved' guard.
    # Find the btn-draft-post test id and walk back; the conditional must
    # appear within the surrounding fragment.
    idx = html.find("data-testid=\"btn-draft-post\"")
    assert idx > 0, "btn-draft-post must exist"
    window = html[max(0, idx - 600):idx]
    assert "draft_state === 'approved'" in window or \
           'draft_state === "approved"' in window, (
        "Post button must be gated on draft_state === 'approved'"
    )


def test_post_handler_guards_state(html):
    # The onPostToWfirma handler itself must also early-return on non-approved.
    assert re.search(
        r"openDraft\.draft_state\s*!==\s*['\"]approved['\"]",
        html,
    ), "onPostToWfirma must guard against non-approved drafts"


# ── 7. Post route only fires from manual handler ────────────────────────────

def test_post_endpoint_called_only_from_manual_handler(html):
    # The endpoint string must appear exactly once and only inside the
    # onPostToWfirma helper. No useEffect / auto-trigger.
    post_calls = re.findall(
        r"`/api/v1/proforma/draft/\$\{[^}]+\}/post`",
        html,
    )
    assert len(post_calls) == 1, (
        f"POST /draft/{{id}}/post must be referenced exactly once "
        f"(found {len(post_calls)}). Multiple references suggest auto-fire."
    )
    # And the call must be inside _writeCall('Post to wFirma', ...)
    idx = html.index(post_calls[0])
    window = html[max(0, idx - 400):idx]
    assert "_writeCall('Post to wFirma'" in window or \
           '_writeCall("Post to wFirma"' in window


def test_post_requires_window_confirm_and_token(html):
    # Find onPostToWfirma block.
    m = re.search(r"onPostToWfirma\s*=\s*\(\)\s*=>\s*\{", html)
    assert m, "onPostToWfirma not found"
    end = html.index("};", m.end())
    block = html[m.start():end]
    assert "window.confirm" in block, "post must call window.confirm"
    assert "POSTS A REAL PROFORMA TO wFirma" in block, (
        "post warning must mention live wFirma write"
    )
    assert "PROFORMA_DRAFT_TOKENS.post" in block, (
        "post handler must check the typed post token against the constant"
    )


def test_post_token_string_is_present(html):
    assert "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA" in html


# ── 8. Legacy /proforma/create is NOT called from this panel ───────────────

def test_legacy_create_endpoint_not_referenced_in_dashboard(html):
    # The legacy POST /api/v1/proforma/create/{batch}/{client} route must
    # not appear in the dashboard. If a future change re-introduces it we
    # need an explicit decision.
    assert re.search(
        r"/api/v1/proforma/create/",
        html,
    ) is None, "Dashboard must not call legacy /api/v1/proforma/create — "\
                "use the local draft post endpoint instead"


# ── 9. Posted drafts surface wFirma id + fullnumber ─────────────────────────

def test_posted_banner_renders_wfirma_id(html):
    assert 'data-testid="draft-posted-banner"' in html
    assert 'data-testid="draft-posted-wfirma-id"' in html
    assert 'data-testid="draft-posted-fullnumber"' in html


def test_posted_banner_links_to_view_proforma(html):
    assert 'data-testid="draft-view-proforma-link"' in html
    # The link target must be the existing Proforma document fetcher
    assert "/api/v1/proforma/${encodeURIComponent(openDraft.batch_id)}/" in html


# ── 10. Cancel button hidden for posted / posting drafts ────────────────────

def test_cancel_button_hidden_when_posted(html):
    # The cancel button is wrapped in `!isPosted && !isCancelled && ...`
    idx = html.find('data-testid="btn-draft-cancel"')
    assert idx > 0
    window = html[max(0, idx - 400):idx]
    assert "!isPosted" in window
    assert "!isCancelled" in window


def test_cancel_button_hidden_when_posting(html):
    """Cancel must be suppressed while a wFirma write is in-flight.

    A draft in 'posting' state has an active external write in progress.
    Showing the cancel button during this window creates a race condition
    where the cancel request can land after the wFirma document has already
    been created, leaving the system in an inconsistent state.

    The fix: add ``!isPosting`` to the cancel button guard.
    """
    idx = html.find('data-testid="btn-draft-cancel"')
    assert idx > 0, "btn-draft-cancel must exist in the DOM"
    window = html[max(0, idx - 400):idx]
    assert "!isPosting" in window, (
        "Cancel draft button must be gated on !isPosting to prevent "
        "race condition against an in-flight wFirma write. "
        "Add '&& !isPosting' to the cancel button condition."
    )


# ── 11. Reset warns lines will be replaced ─────────────────────────────────

def test_reset_warns_about_line_replacement(html):
    m = re.search(r"const onReset\s*=", html)
    assert m
    end = html.index("};", m.end())
    block = html[m.start():end]
    assert "WILL BE REPLACED" in block.upper() or "REPLACED" in block.upper()


def test_reset_all_warns_about_full_wipe(html):
    m = re.search(r"const onResetAll\s*=", html)
    assert m
    end = html.index("};", m.end())
    block = html[m.start():end]
    assert "RESET ALL" in block.upper()
    assert "wipe" in block.lower() or "WIPE" in block.upper()


# ── 12. State chips for every lifecycle state ──────────────────────────────

@pytest.mark.parametrize("state", [
    "draft", "editing", "approved", "posting", "posted",
    "post_failed", "cancelled", "superseded",
])
def test_state_chip_handles_each_lifecycle_state(html, state):
    # _draftStateChipColors must have an entry for every lifecycle state.
    assert re.search(rf"\b{state}:\s*\{{", html), (
        f"_draftStateChipColors must define colours for state {state!r}"
    )


# ── 13. Edit gating: only editable states allow PATCH ──────────────────────

def test_editable_states_const_pinned(html):
    # The editable-states constant must be exactly the three Phase 3 states.
    assert re.search(
        r"PROFORMA_DRAFT_EDITABLE_STATES\s*=\s*\[\s*'draft'\s*,\s*'editing'\s*,\s*'post_failed'\s*\]",
        html,
    ), "PROFORMA_DRAFT_EDITABLE_STATES must be ['draft','editing','post_failed']"


def test_line_save_button_only_when_editable(html):
    # btn-line-save-... should only render under `editable && dirty`.
    idx = html.find('data-testid={`btn-line-save-')
    assert idx > 0
    window = html[max(0, idx - 400):idx]
    assert "editable" in window and "dirty" in window


# ── 14. Events drawer ──────────────────────────────────────────────────────

def test_events_drawer_reads_events_endpoint(html):
    assert 'data-testid="draft-events-drawer"' in html
    assert 'data-testid="btn-draft-events"' in html
    # Must call /events endpoint
    assert re.search(r"/api/v1/proforma/draft/\$\{[^}]+\}/events", html)


# ── 15. Operator resolved before every mutation ────────────────────────────

def test_write_call_aborts_when_operator_missing(html):
    # _writeCall must call _resolveOperator() and bail on empty.
    m = re.search(r"const\s+_writeCall\s*=", html)
    assert m, "_writeCall helper not found"
    # Within ~50 lines after declaration, must call _resolveOperator and
    # check for empty.
    block = html[m.start():m.start() + 2000]
    assert "_resolveOperator()" in block
    assert "operator missing" in block or "operator name required" in block


# ── 16. Panel rendered inside BatchDetailPage ──────────────────────────────

def test_panel_rendered_in_batch_detail(html):
    assert "<ProformaDraftPanel batchId={batchId}" in html, (
        "ProformaDraftPanel must be mounted in BatchDetailPage"
    )


def test_panel_mount_does_not_auto_post(html):
    # The mount line itself must not be near a /post call. Walk forward
    # 200 chars from the mount and confirm no post URL appears.
    idx = html.find("<ProformaDraftPanel batchId={batchId}")
    assert idx > 0
    window = html[idx:idx + 200]
    assert "/post" not in window
