"""
test_broker_reply_analyzer.py — broker reply classifier coverage.

Strict scope: read-only classifier. No file/queue/audit mutations are tested
because the route does none. The route returns a deterministic structured
response derived purely from the input text.

Coverage
--------
  Classification:
    1.  Case A — "please find attached invoice" with EJL ID
    2.  Case A — "we attach" + invoice variant
    3.  Case B — "amend SAD"
    4.  Case B — "corrected SAD" / "new MRN"
    5.  Case C — "multiple invoices" + USD 17,049
    6.  Case C — "partial shipment"
    7.  Case D — "please confirm" with no other signals
    8.  Case D — "please provide"
    9.  Case E — "values are correct"
   10.  Case E — "no discrepancy"
   11.  Empty text → case=None, low confidence
   12.  Unrelated chatter → case=None, low confidence
  Priority:
   13.  Amendment beats multi-invoice (B over C)
   14.  Attachment beats request (A over D)
  Extraction:
   15.  Invoice ID extraction — single
   16.  Invoice ID extraction — multiple
   17.  USD extraction — comma-separated
   18.  USD extraction — "USD 17,049" form
   19.  USD extraction — bare amount
  Determinism / no-side-effect:
   20.  Same text → same result (twice)
  HTTP route:
   21.  Route returns 200 + JSON shape
   22.  Endpoint accepts empty body text gracefully
   23.  Endpoint requires the 'text' field
  Confidence:
   24.  Case A with invoice_ids → high
   25.  Single signal → medium
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import require_api_key
from app.api.routes_dashboard import _classify_broker_reply, router


# ── Test client ───────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Classification — pure function tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_case_a_attached_invoice():
    r = _classify_broker_reply(
        "Dear Sir, please find attached invoice EJL/25-26/1043 as requested."
    )
    assert r["case"] == "A"
    assert r["signals"]["has_invoice_attachment_hint"] is True
    assert "EJL/25-26/1043" in r["extracted"]["invoice_ids"]


def test_case_a_we_attach_variant():
    r = _classify_broker_reply("We attach invoice EJL/25-26/1043 herewith.")
    assert r["case"] == "A"


def test_case_b_amend_sad():
    r = _classify_broker_reply(
        "We will amend SAD due to incorrect invoice references."
    )
    assert r["case"] == "B"
    assert r["signals"]["mentions_amendment"] is True


def test_case_b_corrected_sad_new_mrn():
    r = _classify_broker_reply(
        "A corrected SAD will be issued under a new MRN shortly."
    )
    assert r["case"] == "B"
    assert r["signals"]["mentions_amendment"] is True


def test_case_c_multiple_invoices_with_amount():
    r = _classify_broker_reply(
        "The shipment is made up of multiple invoices totalling USD 17,049."
    )
    assert r["case"] == "C"
    assert r["signals"]["mentions_multiple_invoices"] is True
    assert "17,049" in r["extracted"]["usd_amounts"]


def test_case_c_partial_shipment():
    r = _classify_broker_reply("This was a partial shipment of the original lot.")
    assert r["case"] == "C"


def test_case_d_please_confirm():
    r = _classify_broker_reply(
        "Please confirm the AWB number so we can investigate further."
    )
    assert r["case"] == "D"
    assert r["signals"]["requests_info"] is True


def test_case_d_please_provide():
    r = _classify_broker_reply(
        "Could you provide the original purchase order for cross-reference?"
    )
    assert r["case"] == "D"


def test_case_e_values_are_correct():
    r = _classify_broker_reply(
        "We have reviewed the SAD; values are correct as declared."
    )
    assert r["case"] == "E"
    assert r["signals"]["rejects_discrepancy"] is True


def test_case_e_no_discrepancy():
    r = _classify_broker_reply(
        "Our records show no discrepancy with the figures shown on the SAD."
    )
    assert r["case"] == "E"


def test_empty_text_returns_no_case():
    r = _classify_broker_reply("")
    assert r["case"] is None
    assert r["confidence"] == "low"
    assert r["extracted"]["invoice_ids"] == []
    assert r["extracted"]["usd_amounts"] == []


def test_unrelated_text_returns_no_case():
    r = _classify_broker_reply(
        "Hello — happy birthday and best wishes. Talk soon."
    )
    assert r["case"] is None
    assert r["confidence"] == "low"


# ── Priority ordering ─────────────────────────────────────────────────────────

def test_priority_amendment_beats_multi():
    """Case B (amendment) takes precedence over Case C (multiple invoices)."""
    r = _classify_broker_reply(
        "Multiple invoices were used. We will amend SAD with new MRN."
    )
    assert r["case"] == "B"


def test_priority_attachment_beats_request():
    """Case A (attached) takes precedence over Case D (please confirm)."""
    r = _classify_broker_reply(
        "Please confirm receipt of the attached invoice EJL/25-26/1043."
    )
    assert r["case"] == "A"


# ── Extraction ────────────────────────────────────────────────────────────────

def test_invoice_id_single():
    r = _classify_broker_reply("Invoice EJL/25-26/1043 is enclosed.")
    assert r["extracted"]["invoice_ids"] == ["EJL/25-26/1043"]


def test_invoice_id_multiple_dedupes_and_sorts():
    r = _classify_broker_reply(
        "Invoices EJL/25-26/1043, EJL/25-26/1044 and EJL/25-26/1043 are attached."
    )
    ids = r["extracted"]["invoice_ids"]
    assert ids == sorted(set(ids))
    assert "EJL/25-26/1043" in ids
    assert "EJL/25-26/1044" in ids


def test_usd_amount_comma_separated():
    r = _classify_broker_reply("Total amount is $11,237.00 across the line items.")
    assert "11,237.00" in r["extracted"]["usd_amounts"]


def test_usd_amount_usd_prefix():
    r = _classify_broker_reply("The CIF value of USD 17,049 is correct.")
    assert "17,049" in r["extracted"]["usd_amounts"]


def test_usd_amount_bare_thousands():
    """Bare 5,812 (no $ prefix) still extracts as USD candidate."""
    r = _classify_broker_reply("Discrepancy of 5,812 noted.")
    # '5,812' has comma → matched by second alternative
    assert any("5,812" in a for a in r["extracted"]["usd_amounts"])


# ── Determinism ───────────────────────────────────────────────────────────────

def test_classifier_is_deterministic():
    text = "We attach invoice EJL/25-26/1043 totalling USD 11,237."
    a = _classify_broker_reply(text)
    b = _classify_broker_reply(text)
    assert a == b


# ── Confidence heuristic ──────────────────────────────────────────────────────

def test_case_a_with_invoice_id_is_high_confidence():
    r = _classify_broker_reply("Please find attached invoice EJL/25-26/1043.")
    assert r["case"] == "A"
    assert r["confidence"] == "high"


def test_single_signal_is_medium_confidence():
    r = _classify_broker_reply("Please confirm the AWB.")
    assert r["case"] == "D"
    assert r["confidence"] == "medium"


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP route
# ═══════════════════════════════════════════════════════════════════════════════

def test_route_returns_json_shape(client: TestClient):
    r = client.post(
        "/dashboard/broker-reply/analyze",
        json={"text": "Please find attached invoice EJL/25-26/1043."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["case"] == "A"
    assert "confidence" in body
    assert "signals" in body and isinstance(body["signals"], dict)
    assert "extracted" in body and isinstance(body["extracted"], dict)
    assert "recommended_action" in body and isinstance(body["recommended_action"], str)


def test_route_handles_empty_text(client: TestClient):
    r = client.post("/dashboard/broker-reply/analyze", json={"text": ""})
    assert r.status_code == 200
    assert r.json()["case"] is None


def test_route_requires_text_field(client: TestClient):
    r = client.post("/dashboard/broker-reply/analyze", json={})
    assert r.status_code == 422   # FastAPI/Pydantic validation


def test_route_idempotent_no_side_effects(client: TestClient, tmp_path, monkeypatch):
    """Two identical calls must produce identical responses."""
    payload = {"text": "We will amend SAD with a new MRN."}
    r1 = client.post("/dashboard/broker-reply/analyze", json=payload)
    r2 = client.post("/dashboard/broker-reply/analyze", json=payload)
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["case"] == "B"


# ═══════════════════════════════════════════════════════════════════════════════
# UI panel — source-grep tests for BrokerReplyAnalyzerPanel
# ═══════════════════════════════════════════════════════════════════════════════

import re as _re_ui
from pathlib import Path as _Path_ui

_DASHBOARD = _Path_ui(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src_ui() -> str:
    return _DASHBOARD.read_text(encoding="utf-8")


def test_ui_panel_function_exists():
    assert _re_ui.search(r"function\s+BrokerReplyAnalyzerPanel\s*\(", _src_ui()), \
        "BrokerReplyAnalyzerPanel function not defined"


def test_ui_panel_root_has_testid():
    assert 'data-testid="broker-reply-analyzer-panel"' in _src_ui()


def test_ui_panel_rendered_in_overview_tab():
    src = _src_ui()
    panel_idx = src.find("<BrokerReplyAnalyzerPanel")
    assert panel_idx != -1, "<BrokerReplyAnalyzerPanel /> render site not found"
    overview_idx = src.rfind("activeTab === 'Overview'", 0, panel_idx)
    docs_idx     = src.find("{/* ── DOCUMENTS TAB ── */}", panel_idx)
    assert overview_idx != -1
    assert docs_idx != -1


def test_ui_panel_uses_analyze_endpoint():
    src = _src_ui()
    assert "apiFetch('/dashboard/broker-reply/analyze'" in src, \
        "UI must call apiFetch('/dashboard/broker-reply/analyze')"


def test_ui_panel_post_method():
    src = _src_ui()
    # find the actual apiFetch call site, not the comment header
    idx = src.find("apiFetch('/dashboard/broker-reply/analyze'")
    assert idx != -1
    snippet = src[idx:idx + 400]
    assert "method:" in snippet and "'POST'" in snippet


def test_ui_panel_has_textarea():
    src = _src_ui()
    assert 'data-testid="broker-reply-input"' in src
    # textarea element with that testid
    assert _re_ui.search(r"<textarea[^>]*data-testid=\"broker-reply-input\"", src, _re_ui.DOTALL), \
        "Input must be a <textarea>"


def test_ui_analyze_button_disabled_when_empty():
    src = _src_ui()
    idx = src.find('data-testid="broker-reply-analyze-btn"')
    assert idx != -1
    snippet = src[max(0, idx - 400):idx + 200]
    assert "disabled={busy || !text.trim()}" in snippet, \
        "Analyze button must be disabled when text is empty or busy"


def test_ui_clear_button_resets_state():
    src = _src_ui()
    # clear() helper resets text, result, error
    assert _re_ui.search(
        r"const\s+clear\s*=\s*\(\)\s*=>\s*\{\s*setText\(''\)\s*;\s*setResult\(null\)\s*;\s*setError\(''\)",
        src,
    ), "Clear handler must reset text, result, and error state"


def test_ui_no_audit_or_send_calls():
    """Panel must not POST to /send, override, audit, or batch routes."""
    src = _src_ui()
    start = src.find("function BrokerReplyAnalyzerPanel")
    end   = src.find("function MissingFunctionsMatrix", start)
    body  = src[start:end]
    # The only POST endpoint in the panel must be the analyze route
    posts = _re_ui.findall(r"apiFetch\([^)]+", body)
    forbidden_substrings = (
        "/send",
        "/operator-override",
        "/process",
        "/regenerate",
        "/closure",
        "/files/",
        "/batches/",
    )
    for call in posts:
        for forbid in forbidden_substrings:
            assert forbid not in call, (
                f"BrokerReplyAnalyzerPanel must not call {forbid} — saw: {call}"
            )


def test_ui_renders_recommendation_block():
    src = _src_ui()
    assert 'data-testid="broker-reply-result-recommendation"' in src
    assert 'data-testid="broker-reply-result-safety-note"' in src
    assert "does not run PZ" in src or "no email is sent" in src.lower()


def test_ui_no_auto_analyze_on_mount():
    """Mount-time effect must not call analyze automatically."""
    src = _src_ui()
    start = src.find("function BrokerReplyAnalyzerPanel")
    end   = src.find("function MissingFunctionsMatrix", start)
    body  = src[start:end]
    # Either no useEffect at all, or any useEffect must not call analyze
    if "React.useEffect" in body:
        ue_idx = body.find("React.useEffect")
        block  = body[ue_idx:ue_idx + 200]
        assert "analyze" not in block, "useEffect must not auto-call analyze on mount"
