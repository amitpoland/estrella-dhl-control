"""
test_dhl_awb1196338404.py — Regression tests for AWB 1196338404 incident.

Covers:
  1. AWB extraction from exact subject (no-bracket T# format)
  2. DHL customs email detection from odprawacelna@dhl.com
  3. Polish subject/body handling with "przesyłka numer:"
  4. Scan by AWB 1196338404 via mock → email returned
  5. Email found even if attachments missing/inaccessible
  6. Product-description guard passes when dhl_email.received=True
  7. Product-description guard raises when no email received
  8. email_classifier extracts correct ticket from un-bracketed subject

Bugs fixed:
  - email_classifier._DHL_TICKET_RE required brackets [T#...], blocking
    ticket extraction from DHL's native notification format.
  - config.zoho_mail_api_base defaulted to mail.zoho.eu instead of
    zmail.zoho.in, causing all Zoho API calls to return 401 silently.
  - dhl_email_monitor._do_search swallowed 401 errors with log.debug,
    preventing the route from detecting auth failure and falling back to bridge.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# CLI root contains dhl_email_monitor.py (not inside the service package)
_CLI = Path(__file__).parent.parent.parent
if str(_CLI) not in sys.path:
    sys.path.insert(0, str(_CLI))

from dhl_email_monitor import (  # noqa: E402
    _extract_awb,
    _extract_awbs_from_text,
    _extract_ticket,
    match_email_to_shipment,
    scan_for_dhl_customs_emails,
    _fetch_messages,
    _build_search_key,
)

_AWB    = "1196338404"
_TICKET = "T#1WA2605130000195"
_SUBJECT_REAL = "T#1WA2605130000195 - Agencja Celna DHL - przesyłka numer: 1196338404"
_SENDER_DHL   = "odprawacelna@dhl.com"
_TOKEN  = "test-token"
_BASE   = "https://zmail.zoho.in/api"
_ACCT   = "2261204000000002002"


# ── 1. AWB extraction from exact production subject ────────────────────────────

def test_awb_extracted_from_real_subject():
    """AWB 1196338404 is embedded in the exact DHL notification subject."""
    awbs = _extract_awbs_from_text(_SUBJECT_REAL)
    assert _AWB in awbs, f"Expected {_AWB!r} in extracted AWBs, got {awbs}"


def test_awb_extracted_via_przesylka_numer_pattern():
    """The 'przesyłka numer:' prefix is recognised and the AWB captured."""
    text = "przesyłka numer: 1196338404"
    awbs = _extract_awbs_from_text(text)
    assert "1196338404" in awbs


# ── 2. DHL customs email detection from odprawacelna@dhl.com ──────────────────

def test_dhl_arrival_email_matched_awb_targeted():
    """Real AWB-targeted match: odprawacelna@dhl.com, un-bracketed T# subject."""
    email = {
        "subject":     _SUBJECT_REAL,
        "from":        _SENDER_DHL,
        "body":        "",
        "attachments": [],
    }
    result = match_email_to_shipment(email, target_awb=_AWB)
    assert result["matched"] is True
    assert result["awb"] == _AWB
    assert result["sender_role"] == "dhl"
    assert "subject" in result["matched_fields"]


def test_dhl_ticket_extracted_without_brackets():
    """
    T#... token is extracted even without surrounding brackets.

    This is the DHL native notification format. Reply-thread format adds
    brackets. Both must work.
    """
    ticket = _extract_ticket(_SUBJECT_REAL)
    assert ticket == _TICKET, f"Expected {_TICKET!r}, got {ticket!r}"


def test_dhl_ticket_extracted_with_brackets():
    """Bracketed format (reply threads) is also accepted."""
    subject_bracketed = f"[{_TICKET}] - Agencja Celna DHL - przesyłka numer: {_AWB}"
    ticket = _extract_ticket(subject_bracketed)
    assert ticket == _TICKET


# ── 3. Polish subject/body handling ───────────────────────────────────────────

def test_przesylka_numer_detection():
    """'przesyłka numer:' keyword triggers subject match in the monitor."""
    from dhl_email_monitor import _subject_matches
    assert _subject_matches(_SUBJECT_REAL) is True


def test_przesylka_numer_with_body_keywords():
    """Body containing translation request keywords is detected."""
    from dhl_email_monitor import _body_matches
    body = "Uprzejmie prosimy o Tłumaczenie zawartości przesyłki."
    assert _body_matches(body) is True


# ── 4. Scan by AWB returns the email via mocked Zoho REST ─────────────────────

def _make_zoho_message(awb: str, ticket: str) -> dict:
    return {
        "messageId":    "99887766554433221",
        "threadId":     "11223344556677889",
        "subject":      f"{ticket} - Agencja Celna DHL - przesyłka numer: {awb}",
        "fromAddress":  _SENDER_DHL,
        "receivedTime": "1747130412000",
        "hasAttachment": "0",
    }


def _ok_resp(data: list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": data}
    resp.raise_for_status.return_value = None
    return resp


def test_scan_finds_email_for_awb_1196338404(monkeypatch):
    """
    When Zoho returns the real email for AWB 1196338404, the scan correctly
    matches and returns it.
    """
    msg = _make_zoho_message(_AWB, _TICKET)

    # Mock requests.get to return the message on any search call
    with patch("requests.get", return_value=_ok_resp([msg])) as mock_get:
        result = scan_for_dhl_customs_emails(
            zoho_account_id=_ACCT,
            zoho_api_token=_TOKEN,
            target_awb=_AWB,
            api_base=_BASE,
        )

    assert result["matched"] >= 1, (
        f"Expected >= 1 match, got {result['matched']}. "
        f"scan_method={result.get('scan_method')}"
    )
    matched_email = result["emails"][0]
    assert matched_email["awb"] == _AWB
    assert matched_email["dhl_ticket"] == _TICKET
    assert matched_email["sender_role"] == "dhl"


# ── 5. Email found even if attachments missing/inaccessible ───────────────────

def test_scan_matches_without_attachments(monkeypatch):
    """
    AWB match succeeds on subject alone; no attachments required.
    This is the production scenario where DHL sends notification without docs.
    """
    msg = _make_zoho_message(_AWB, _TICKET)
    msg["hasAttachment"] = "0"  # no attachments

    with patch("requests.get", return_value=_ok_resp([msg])):
        result = scan_for_dhl_customs_emails(
            zoho_account_id=_ACCT,
            zoho_api_token=_TOKEN,
            target_awb=_AWB,
            api_base=_BASE,
        )

    assert result["matched"] >= 1
    assert result["emails"][0]["awb"] == _AWB


# ── 6. Product-description guard passes when DHL email received ───────────────

def test_guard_passes_when_dhl_email_received():
    """
    guard_dhl_requires_email must NOT raise when audit.dhl_email.received=True.
    """
    import importlib, sys as _sys
    # Import via service package
    _svc = Path(__file__).parent.parent / "app"
    if str(_svc.parent) not in _sys.path:
        _sys.path.insert(0, str(_svc.parent))

    from app.core.guards import guard_dhl_requires_email

    audit_ok = {
        "clearance_status": "awaiting_dhl_customs_email",
        "dhl_email": {"received": True},
    }
    # Must not raise
    guard_dhl_requires_email(audit_ok)


def test_guard_passes_when_clearance_status_email_received():
    """Guard passes on clearance_status='dhl_email_received'."""
    from app.core.guards import guard_dhl_requires_email
    from fastapi import HTTPException

    audit = {"clearance_status": "dhl_email_received"}
    guard_dhl_requires_email(audit)  # must not raise


def test_guard_passes_when_dhl_ticket_in_audit():
    """Guard passes when dhl_ticket is stored in audit (from classifier fix)."""
    from app.core.guards import guard_dhl_requires_email

    audit = {"dhl_ticket": "T#1WA2605130000195"}
    guard_dhl_requires_email(audit)  # must not raise


# ── 7. Product-description guard raises when no email received ────────────────

def test_guard_raises_when_no_dhl_email():
    """
    guard_dhl_requires_email must raise HTTPException(422) when:
    - clearance_status is not in the allowed set
    - dhl_ticket is absent
    - dhl_email.received is not True
    """
    from app.core.guards import guard_dhl_requires_email
    from fastapi import HTTPException

    audit_empty = {}
    with pytest.raises(HTTPException) as exc_info:
        guard_dhl_requires_email(audit_empty)
    assert exc_info.value.status_code == 422
    assert "DHL_NO_EMAIL" in str(exc_info.value.detail)


# ── 8. email_classifier extracts ticket from un-bracketed subject ─────────────

def test_email_classifier_ticket_no_brackets():
    """
    email_classifier.classify_email must extract dhl_ticket even when the
    subject contains no brackets around the T# token.

    This was the production bug: _DHL_TICKET_RE required [T#...] but DHL's
    original notification format is T#... without brackets.
    """
    _svc_app = Path(__file__).parent.parent / "app"
    if str(_svc_app.parent) not in sys.path:
        sys.path.insert(0, str(_svc_app.parent))

    from app.services.email_classifier import classify_email

    result = classify_email(
        sender=_SENDER_DHL,
        subject=_SUBJECT_REAL,
        body="",
    )
    assert result["type"] in ("dhl_arrival", "dhl_cesja_fwd"), (
        f"Unexpected type: {result['type']}"
    )
    assert result["dhl_ticket"] == _TICKET, (
        f"Expected {_TICKET!r}, got {result['dhl_ticket']!r}. "
        "Likely _DHL_TICKET_RE still requires brackets."
    )
    assert result["awb"] == _AWB


def test_email_classifier_ticket_with_brackets():
    """
    email_classifier.classify_email also handles the bracketed reply-thread format.
    """
    from app.services.email_classifier import classify_email

    subject_bracketed = f"[{_TICKET}] - Agencja Celna DHL - przesyłka numer: {_AWB}"
    result = classify_email(
        sender=_SENDER_DHL,
        subject=subject_bracketed,
        body="",
    )
    assert result["dhl_ticket"] == _TICKET


def test_email_classifier_awb_without_ticket():
    """AWB is still extracted even when no ticket token is present in subject."""
    from app.services.email_classifier import classify_email

    subject_no_ticket = f"Agencja Celna DHL - przesyłka numer: {_AWB}"
    result = classify_email(
        sender=_SENDER_DHL,
        subject=subject_no_ticket,
        body="",
    )
    assert result["awb"] == _AWB
    assert result["dhl_ticket"] is None   # correct — no ticket in this subject


# ── 401 auth-failure signal propagation ───────────────────────────────────────

def test_fetch_messages_auth_error_on_401():
    """
    When Zoho returns 401, _fetch_messages must return scan_method='auth_error'
    so the route can fall back to AI Bridge instead of silently returning 0 matches.
    """
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.text = '{"code":"INVALID_OAUTHTOKEN"}'
    resp_401.raise_for_status.side_effect = Exception("401 Client Error")

    with patch("requests.get", return_value=resp_401):
        messages, scanned, query_used, scan_method = _fetch_messages(
            account_id=_ACCT,
            folder_id="2261204000000002014",
            limit=50,
            token=_TOKEN,
            target_awb=_AWB,
            api_base="https://mail.zoho.eu/api",   # wrong region — triggers 401
        )

    assert scan_method == "auth_error", (
        f"Expected 'auth_error', got {scan_method!r}. "
        "401 responses must be propagated so the route can fall back to bridge."
    )
    assert messages == []
