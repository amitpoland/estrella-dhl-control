"""
test_dashboard_closure_eval_card.py — Source-grep tests for the
Closure Evaluation card in the Overview tab.

The card calls GET /api/v1/closure/{batch_id}/check — a read-only
adapter that calls evaluate_closure() only, never apply_closure().
It DOES NOT close the shipment, write status=completed, or modify the audit.

Pattern: read dashboard.html as text + route source for backend assertions.
No JSX execution.
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)
ROUTES_LIFECYCLE = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/api/routes_lifecycle.py"
)
SHIPMENT_CLOSURE = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/services/shipment_closure.py"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Backend endpoint safety ───────────────────────────────────────────────────

def test_check_endpoint_exists_in_routes():
    """/closure/{batch_id}/check endpoint must be defined in routes_lifecycle."""
    content = ROUTES_LIFECYCLE.read_text(encoding="utf-8")
    assert "/closure/{batch_id}/check" in content, (
        "check_closure_endpoint not found in routes_lifecycle.py"
    )


def test_check_endpoint_uses_get_method():
    """The /check endpoint must be a GET (not POST) to signal read-only intent."""
    content = ROUTES_LIFECYCLE.read_text(encoding="utf-8")
    idx = content.find("/closure/{batch_id}/check")
    assert idx != -1
    # Look backward a few lines for the decorator
    snippet = content[max(0, idx - 200):idx + 50]
    assert "@router.get" in snippet, (
        "check_closure_endpoint must use @router.get, not @router.post"
    )


def test_check_endpoint_calls_evaluate_not_apply():
    """check_closure_endpoint must call evaluate_closure(), NOT apply_closure or closure_for_batch."""
    content = ROUTES_LIFECYCLE.read_text(encoding="utf-8")
    idx = content.find("check_closure_endpoint")
    assert idx != -1
    snippet = content[idx:idx + 600]
    assert "evaluate_closure" in snippet, (
        "check_closure_endpoint must call evaluate_closure()"
    )
    assert "apply_closure" not in snippet, (
        "check_closure_endpoint must NOT call apply_closure()"
    )
    assert "closure_for_batch" not in snippet, (
        "check_closure_endpoint must NOT call closure_for_batch()"
    )


def test_evaluate_closure_is_pure():
    """evaluate_closure() in the service must not call write_json_atomic."""
    content = SHIPMENT_CLOSURE.read_text(encoding="utf-8")
    # Find the evaluate_closure function body (ends before apply_closure)
    idx_start = content.find("def evaluate_closure(")
    idx_end   = content.find("def apply_closure(")
    assert idx_start != -1 and idx_end > idx_start
    body = content[idx_start:idx_end]
    assert "write_json_atomic" not in body, (
        "evaluate_closure() must not write to audit — it is a pure check"
    )


# ── Card presence in Overview tab ────────────────────────────────────────────

def test_closure_eval_card_testid():
    """data-testid='closure-eval-card' must be present in dashboard."""
    src = _src()
    assert (
        'data-testid="closure-eval-card"' in src
        or "data-testid='closure-eval-card'" in src
    ), "closure-eval-card testid not found"


def test_closure_eval_card_in_overview_tab():
    """Closure Evaluation card must be inside the Overview tab block."""
    src = _src()
    overview_start = src.find("activeTab === 'Overview'")
    assert overview_start != -1, "Overview tab block not found"
    # The card must appear after the first Overview check
    remaining = src[overview_start:]
    assert "closure-eval-card" in remaining, (
        "closure-eval-card not found inside Overview tab"
    )


def test_closure_eval_card_after_missing_functions_matrix():
    """Closure Evaluation card must appear after MissingFunctionsMatrix."""
    src = _src()
    matrix_idx = src.find("MissingFunctionsMatrix")
    card_idx   = src.find("closure-eval-card")
    assert matrix_idx != -1 and card_idx != -1
    assert card_idx > matrix_idx, (
        "closure-eval-card must appear after MissingFunctionsMatrix"
    )


# ── Endpoint path wiring ──────────────────────────────────────────────────────

def test_closure_check_endpoint_in_dashboard():
    """Dashboard must call /api/v1/closure/.../check (not /evaluate)."""
    src = _src()
    idx = src.find("closure-eval-card")
    snippet = src[idx:idx + 6000]
    assert "/closure/" in snippet, "closure endpoint path not found in card"
    assert "/check" in snippet, "/check not found in closure eval card"


def test_closure_card_does_not_call_evaluate_endpoint():
    """Dashboard must NOT call /closure/.../evaluate (that endpoint writes)."""
    src = _src()
    idx = src.find("closure-eval-card")
    snippet = src[idx:idx + 6000]
    assert "/evaluate" not in snippet, (
        "Dashboard calls /evaluate which writes audit — must use /check instead"
    )


# ── Required UI elements ──────────────────────────────────────────────────────

def test_closure_eval_button_present():
    """data-testid='closure-eval-btn' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-btn"' in src
        or "data-testid='closure-eval-btn'" in src
    )


def test_closure_eval_button_label():
    """Button must say 'Evaluate Closure Readiness'."""
    assert "Evaluate Closure Readiness" in _src()


def test_closure_eval_description_text():
    """Card must state it does not close the shipment."""
    src = _src()
    assert "does not close" in src or "Evaluation only" in src, (
        "Card must clearly state evaluation-only nature"
    )


def test_closure_eval_safe_note_testid():
    """data-testid='closure-eval-safe-note' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-safe-note"' in src
        or "data-testid='closure-eval-safe-note'" in src
    )


def test_closure_eval_checklist_testid():
    """data-testid='closure-eval-checklist' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-checklist"' in src
        or "data-testid='closure-eval-checklist'" in src
    )


def test_closure_eval_blocking_reasons_testid():
    """data-testid='closure-eval-blocking-reasons' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-blocking-reasons"' in src
        or "data-testid='closure-eval-blocking-reasons'" in src
    )


def test_closure_eval_error_testid():
    """data-testid='closure-eval-error' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-error"' in src
        or "data-testid='closure-eval-error'" in src
    )


def test_closure_eval_status_badge_testid():
    """data-testid='closure-eval-status-badge' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-status-badge"' in src
        or "data-testid='closure-eval-status-badge'" in src
    )


# ── Refresh after evaluation ──────────────────────────────────────────────────

def test_refresh_batch_readiness_after_eval():
    """Card must call loadBatchReadiness() after evaluation."""
    src = _src()
    idx = src.find("closure-eval-card")
    snippet = src[idx:idx + 6000]
    assert "loadBatchReadiness" in snippet, (
        "loadBatchReadiness() not called after closure evaluation"
    )


# ── Safety: no write actions added ───────────────────────────────────────────

def test_no_delete_in_closure_card():
    """Closure card must not contain any delete/archive/close calls."""
    src = _src()
    idx = src.find("closure-eval-card")
    snippet = src[idx:idx + 6000]
    for forbidden in ("DELETE", "/archive", "/close", "status=completed", "apply_closure"):
        assert forbidden not in snippet, (
            f"Forbidden write action '{forbidden}' found in closure eval card"
        )


def test_no_unrelated_post_in_closure_card():
    """Closure card must not POST to unrelated endpoints."""
    src = _src()
    idx = src.find("closure-eval-card")
    snippet = src[idx:idx + 6000]
    for forbidden in ("/api/v1/email", "/api/v1/dhl", "/api/v1/pz", "/api/v1/agency"):
        assert forbidden not in snippet, (
            f"Unexpected endpoint '{forbidden}' found in closure eval card"
        )


# ── Confirm Closure button ────────────────────────────────────────────────────

def test_confirm_button_testid_present():
    """data-testid='closure-confirm-btn' must exist in dashboard source."""
    src = _src()
    assert (
        'data-testid="closure-confirm-btn"' in src
        or "data-testid='closure-confirm-btn'" in src
    ), "closure-confirm-btn testid not found"


def test_confirm_button_calls_execute_not_deprecated_endpoint():
    """Button must POST to /api/v1/execute/closure_confirm, never to the deprecated /closure route."""
    src = _src()
    card_idx = src.find("closure-confirm-btn")
    assert card_idx != -1
    snippet = src[card_idx:card_idx + 2000]
    assert "/api/v1/execute/closure_confirm" in snippet, (
        "closure-confirm-btn must call /api/v1/execute/closure_confirm"
    )
    # Must never call the old evaluate/apply endpoints directly
    for bad in ("/api/v1/closure/", "apply_closure", "/evaluate"):
        assert bad not in snippet, (
            f"closure-confirm-btn must not call '{bad}' — use execute endpoint only"
        )


def test_confirm_button_gated_by_ready_flag():
    """Button must be disabled when closureCheck.ready is false or missing."""
    src = _src()
    card_idx = src.find("closure-confirm-btn")
    assert card_idx != -1
    snippet = src[card_idx:card_idx + 800]
    # The disabled prop must reference closureCheck.ready
    assert "closureCheck" in snippet and "ready" in snippet, (
        "closure-confirm-btn disabled prop must check closureCheck.ready"
    )


def test_confirm_button_hidden_when_already_completed():
    """Button must also be gated by !closureCheck.already_completed."""
    src = _src()
    card_idx = src.find("closure-confirm-btn")
    assert card_idx != -1
    snippet = src[card_idx:card_idx + 800]
    assert "already_completed" in snippet, (
        "closure-confirm-btn must check already_completed — button must be disabled when shipment is done"
    )


def test_confirm_button_sends_approved_by_in_payload():
    """Button must include approved_by in the payload sent to the execute endpoint."""
    src = _src()
    card_idx = src.find("closure-confirm-btn")
    assert card_idx != -1
    snippet = src[card_idx:card_idx + 2000]
    assert "approved_by" in snippet, (
        "closure-confirm-btn must pass approved_by in payload"
    )


def test_confirm_section_testid_present():
    """data-testid='closure-confirm-section' must wrap the confirm button."""
    src = _src()
    assert (
        'data-testid="closure-confirm-section"' in src
        or "data-testid='closure-confirm-section'" in src
    ), "closure-confirm-section testid not found"


def test_confirm_result_testid_present():
    """data-testid='closure-confirm-result' must be present for result display."""
    src = _src()
    assert (
        'data-testid="closure-confirm-result"' in src
        or "data-testid='closure-confirm-result'" in src
    ), "closure-confirm-result testid not found"


def test_confirm_not_ready_reason_testid_present():
    """data-testid='closure-confirm-not-ready-reason' must be present."""
    src = _src()
    assert (
        'data-testid="closure-confirm-not-ready-reason"' in src
        or "data-testid='closure-confirm-not-ready-reason'" in src
    ), "closure-confirm-not-ready-reason testid not found"


def test_confirm_refreshes_after_success():
    """After a successful confirm, the card must refresh load() and loadBatchReadiness()."""
    src = _src()
    card_idx = src.find("closure-confirm-section")
    assert card_idx != -1
    # Use a 4 000-char window — the Promise.all refresh calls sit ~3 300 chars in
    snippet = src[card_idx:card_idx + 4000]
    assert "loadBatchReadiness" in snippet, (
        "closure confirm must call loadBatchReadiness() on success"
    )
    assert "load()" in snippet or "load(" in snippet, (
        "closure confirm must call load() to refresh the audit card on success"
    )


# ── Structural integrity ──────────────────────────────────────────────────────

def test_brace_balance():
    """Curly braces in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("{")
    closes = jsx.count("}")
    assert opens == closes, f"Unbalanced braces: {{ {opens}  }} {closes}"


def test_paren_balance():
    """Parentheses in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("(")
    closes = jsx.count(")")
    assert opens == closes, f"Unbalanced parens: ( {opens}  ) {closes}"
