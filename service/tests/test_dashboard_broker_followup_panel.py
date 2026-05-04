"""
test_dashboard_broker_followup_panel.py — source-grep tests for the
BrokerFollowupPanel UI in dashboard.html (Overview tab).

Pattern matches the existing closure/agency-docs panel tests: read the
HTML+JSX as text and assert the structural and behavioural contract.

Coverage
--------
  1. BrokerFollowupPanel function exists
  2. Panel rendered in Overview tab via <BrokerFollowupPanel batchId={batchId} />
  3. Loads via GET /dashboard/broker-followups
  4. POST uses /dashboard/broker-followups/${batchId}/send
  5. POST body includes 'to'
  6. POST body includes 'cc'
  7. from_address only included when provided (conditional spread)
  8. To input is required and uses type=email
  9. Send disabled when 'to' empty (isValidTo)
 10. Email regex validates format
 11. Confirmation modal/dialog required before POST
 12. Confirmation modal contains warning about not modifying customs/PZ
 13. Sent draft disables Send button
 14. Error branch surfaces error message in the panel
 15. Success path refreshes drafts (loadDrafts call after POST)
 16. No hardcoded broker email / domain
 17. No auto-send on load — POST only fires from sendDraft
 18. Refresh button calls loadDrafts
 19. data-testid="broker-followup-panel" attached to root Card
 20. References POST send endpoint contract from routes_dashboard
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)
ROUTES_DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/api/routes_dashboard.py"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Component existence ───────────────────────────────────────────────────────

def test_broker_followup_panel_function_exists():
    assert re.search(r"function\s+BrokerFollowupPanel\s*\(", _src()), \
        "BrokerFollowupPanel function not defined"


def test_panel_rendered_in_overview_tab():
    """The panel must be mounted inside the activeTab === 'Overview' tab block."""
    src = _src()
    # Use the JSX render site, not the comment in the function header
    panel_idx = src.find("<BrokerFollowupPanel batchId={batchId}")
    assert panel_idx != -1, "<BrokerFollowupPanel batchId={batchId} /> render site not found"
    # Find the nearest preceding Overview tab guard and the next Documents tab guard
    overview_idx = src.rfind("activeTab === 'Overview'", 0, panel_idx)
    docs_idx     = src.find("{/* ── DOCUMENTS TAB ── */}", panel_idx)
    assert overview_idx != -1, "panel must come after an `activeTab === 'Overview'` guard"
    assert docs_idx != -1, "panel must come before the Documents tab marker"


def test_panel_passes_batch_id_prop():
    assert re.search(r"<BrokerFollowupPanel\s+batchId=\{batchId\}", _src()), \
        "<BrokerFollowupPanel /> must receive batchId prop"


def test_panel_root_has_testid():
    assert 'data-testid="broker-followup-panel"' in _src(), \
        "Root Card must carry data-testid=\"broker-followup-panel\""


# ── GET wiring ────────────────────────────────────────────────────────────────

def test_loads_via_get_broker_followups():
    """Component must call GET /dashboard/broker-followups (via apiFetch)."""
    src = _src()
    # apiFetch defaults to GET when no method/options provided
    assert "apiFetch('/dashboard/broker-followups')" in src, \
        "Must call apiFetch('/dashboard/broker-followups') for the load path"


def test_refresh_button_calls_loadDrafts():
    src = _src()
    idx = src.find('data-testid="broker-followup-refresh-btn"')
    assert idx != -1
    # Look at the surrounding JSX tag: onClick attribute may be before or after data-testid
    snippet = src[max(0, idx - 400):idx + 200]
    assert "onClick={loadDrafts}" in snippet, \
        "Refresh button must invoke loadDrafts via onClick"


# ── POST wiring ───────────────────────────────────────────────────────────────

def test_post_uses_correct_endpoint():
    src = _src()
    assert re.search(
        r"`/dashboard/broker-followups/\$\{encodeURIComponent\(batchId\)\}/send`",
        src,
    ), "POST must target /dashboard/broker-followups/${encodeURIComponent(batchId)}/send"


def test_post_method_is_post():
    src = _src()
    # Locate the send block and ensure method: 'POST' is present nearby
    idx = src.find("/broker-followups/${encodeURIComponent(batchId)}/send")
    assert idx != -1
    snippet = src[idx:idx + 600]
    assert "method:" in snippet and "'POST'" in snippet, \
        "Send must use method: 'POST'"


def test_post_body_includes_to():
    src = _src()
    # Body shape: { to: form.to.trim(), cc: ... }
    assert re.search(r"body\s*=\s*\{\s*to:\s*form\.to\.trim\(\)", src), \
        "POST body must include 'to' from form input"


def test_post_body_includes_cc():
    src = _src()
    assert re.search(r"cc:\s*\(form\.cc\s*\|\|\s*''\)\.trim\(\)", src), \
        "POST body must include 'cc' from form input"


def test_from_address_only_when_provided():
    """from_address must be conditional — only added when truthy."""
    src = _src()
    # Must have an `if (form.from_address ...)` guard before assigning to body
    assert re.search(
        r"if\s*\(\s*form\.from_address\s*&&\s*form\.from_address\.trim\(\)\s*\)\s*\{\s*body\.from_address\s*=",
        src,
    ), "from_address must only be added to body when operator provided one"


# ── Validation ────────────────────────────────────────────────────────────────

def test_email_regex_present():
    src = _src()
    assert re.search(r"EMAIL_RE\s*=\s*/\^\[\^\\s@\]\+@\[\^\\s@\]\+\\\.\[\^\\s@\]\+\$/", src), \
        "Email validation regex must be present"


def test_isValidTo_helper_used():
    src = _src()
    assert "isValidTo" in src, "isValidTo helper must exist"
    # And must reject empty/invalid: && EMAIL_RE.test(toVal.trim())
    assert "EMAIL_RE.test" in src, "Validator must call EMAIL_RE.test"


def test_to_input_required_attribute():
    src = _src()
    # The To input has required and type='email'
    idx = src.find('data-testid="broker-followup-to"')
    assert idx != -1
    snippet = src[idx:idx + 400]
    assert "required" in snippet, "To input must be marked required"
    assert 'type="email"' in snippet, "To input must be type=email"


def test_send_disabled_when_to_empty_or_invalid():
    src = _src()
    # sendDisabled depends on toValid (which depends on isValidTo)
    assert "const sendDisabled = sent || !toValid" in src, \
        "sendDisabled gate must include !toValid"


def test_send_button_disabled_attr_bound():
    src = _src()
    idx = src.find('data-testid="broker-followup-send-btn"')
    assert idx != -1
    snippet = src[idx:idx + 400]
    assert "disabled={sendDisabled}" in snippet, \
        "Send button must bind disabled to sendDisabled"


# ── Confirmation modal ────────────────────────────────────────────────────────

def test_confirm_modal_required_before_post():
    """Send button must open confirmFor; sendDraft is only invoked from inside the modal."""
    src = _src()
    # Send button click sets confirmFor (does NOT call sendDraft directly)
    idx = src.find('data-testid="broker-followup-send-btn"')
    assert idx != -1
    snippet = src[idx:idx + 600]
    assert "setConfirmFor(draft)" in snippet, \
        "Send button click must open confirmation modal via setConfirmFor"
    # And sendDraft is wired to the modal's confirm button only
    confirm_idx = src.find('data-testid="broker-followup-confirm-send"')
    assert confirm_idx != -1
    # onClick={() => sendDraft(confirmFor)} is in the same Btn JSX block as the testid
    confirm_snippet = src[max(0, confirm_idx - 400):confirm_idx + 200]
    assert "sendDraft(confirmFor)" in confirm_snippet, \
        "sendDraft must be called from the confirmation modal's confirm button"


def test_confirm_modal_has_warning():
    src = _src()
    assert "broker-followup-confirm-warning" in src, \
        "Confirmation modal must surface the no-mutation warning"
    assert "will not modify customs/PZ values" in src, \
        "Warning text must state customs/PZ values are not modified"


def test_confirm_modal_has_cancel():
    src = _src()
    assert "broker-followup-confirm-cancel" in src, \
        "Confirmation modal must offer a Cancel control"


# ── Sent / error branches ─────────────────────────────────────────────────────

def test_sent_draft_disables_send_button():
    src = _src()
    # sent = draft.status === 'sent' || draft.status === 'queued'
    assert re.search(
        r"const\s+sent\s*=\s*draft\.status\s*===\s*'sent'\s*\|\|\s*draft\.status\s*===\s*'queued'",
        src,
    ), "Sent flag must be derived from draft.status === 'sent' || 'queued'"
    # sendDisabled must short-circuit on sent
    assert "sent || !toValid" in src, \
        "sendDisabled must set true when draft already sent"


def test_error_branch_renders_error():
    src = _src()
    assert "broker-followup-error" in src, \
        "Per-draft error must render with data-testid"
    # Error is set in catch block, NOT marked as sent
    assert re.search(
        r"catch\s*\(ex\)\s*\{\s*setErrors\(prev\s*=>\s*\(\{[^}]*\[draft\.draft_id\]:",
        src, re.DOTALL,
    ), "Error path must populate per-draft errors map"


def test_error_does_not_mark_sent():
    """Send catch block must NOT call loadDrafts that downgrades to sent."""
    src = _src()
    # Specifically: in catch, no draft.status assignment to 'sent'
    sd_idx = src.find("const sendDraft = async")
    assert sd_idx != -1
    sd_block = src[sd_idx:sd_idx + 1500]
    catch_idx = sd_block.find("catch")
    assert catch_idx != -1
    catch_block = sd_block[catch_idx:]
    assert "status = 'sent'" not in catch_block, \
        "Error path must not flip draft.status to 'sent' client-side"


def test_success_refreshes_drafts():
    """sendDraft must call loadDrafts() in the try-block after POST success."""
    src = _src()
    sd_idx = src.find("const sendDraft = async")
    assert sd_idx != -1
    sd_block = src[sd_idx:sd_idx + 1500]
    # Inside try-block, after apiFetch POST, loadDrafts is awaited
    assert "await loadDrafts()" in sd_block, \
        "Success path must call await loadDrafts() to refresh state"


# ── Safety: no hardcoded recipient, no auto-send ─────────────────────────────

def test_no_hardcoded_broker_email():
    """Component must not contain a hardcoded broker recipient address."""
    # Restrict scan to the BrokerFollowupPanel function body.
    src = _src()
    start = src.find("function BrokerFollowupPanel")
    assert start != -1
    end = src.find("function MissingFunctionsMatrix", start)
    assert end != -1
    body = src[start:end]
    # Allow placeholder text inside attributes; reject any literal email used as a default value.
    # Look for default-value patterns like: to: 'someone@x.y' or value="x@y.z"
    forbidden = re.findall(r"(value|defaultValue|to)\s*[:=]\s*['\"][^'\"]*@[^'\"]+['\"]", body)
    # Permit placeholder= which is just hint text, not a default value
    forbidden = [f for f in forbidden if 'placeholder' not in f]
    assert not forbidden, f"Hardcoded broker recipient detected: {forbidden}"


def test_no_auto_send_on_load():
    """useEffect must call loadDrafts only — never sendDraft on mount."""
    src = _src()
    start = src.find("function BrokerFollowupPanel")
    end = src.find("function MissingFunctionsMatrix", start)
    body = src[start:end]
    use_effect_idx = body.find("React.useEffect")
    assert use_effect_idx != -1
    # Inspect the first effect block
    effect_block = body[use_effect_idx:use_effect_idx + 200]
    assert "loadDrafts" in effect_block, "Mount effect must call loadDrafts"
    assert "sendDraft" not in effect_block, "Mount effect must NOT auto-call sendDraft"


def test_no_post_outside_sendDraft():
    """The only 'POST' literal in the panel must be inside sendDraft (operator-driven)."""
    src = _src()
    start = src.find("function BrokerFollowupPanel")
    end = src.find("function MissingFunctionsMatrix", start)
    body = src[start:end]

    # Count occurrences of the POST literal in the panel body
    occurrences = [m.start() for m in re.finditer(r"['\"]POST['\"]", body)]
    assert len(occurrences) == 1, (
        f"Expected exactly one 'POST' literal in BrokerFollowupPanel, "
        f"found {len(occurrences)} at {occurrences}"
    )

    # Confirm that single POST sits inside the sendDraft function definition
    sd_idx     = body.find("const sendDraft = async")
    sd_end_idx = body.find("React.useEffect", sd_idx)   # next major statement after sendDraft
    if sd_end_idx == -1:
        sd_end_idx = body.find("return (", sd_idx)
    assert sd_idx != -1 and sd_end_idx > sd_idx
    assert sd_idx < occurrences[0] < sd_end_idx, \
        "POST literal must reside inside sendDraft's function body"


# ── Backend route contract (sanity) ───────────────────────────────────────────

def test_route_contract_send_endpoint_exists():
    """Confirm the backend route the UI POSTs to is defined."""
    backend = ROUTES_DASHBOARD.read_text(encoding="utf-8")
    assert "/broker-followups/{batch_id}/send" in backend, \
        "POST send endpoint must be defined in routes_dashboard.py"


def test_route_contract_get_endpoint_exists():
    backend = ROUTES_DASHBOARD.read_text(encoding="utf-8")
    assert '"/broker-followups"' in backend or "'/broker-followups'" in backend, \
        "GET broker-followups endpoint must be defined in routes_dashboard.py"
