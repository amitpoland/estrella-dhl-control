"""
test_dhl_email_match.py — Tests for the permissive DHL/agency/Ganther/internal
email matcher used by /api/v1/dhl/scan-inbox.

The matcher must catch real shipment correspondence regardless of whether the
mail came directly from DHL or was forwarded by Ganther / Estrella internal.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# customs_description_engine.py and dhl_email_monitor.py live at CLI root
_CLI = Path(__file__).parent.parent.parent
if str(_CLI) not in sys.path:
    sys.path.insert(0, str(_CLI))

from dhl_email_monitor import (  # noqa: E402
    match_email_to_shipment,
    scan_for_dhl_customs_emails,
    _classify_sender,
    _classify_attachment,
    _extract_awbs_from_text,
)


_AWB = "2824221912"


# ── Sender classification ────────────────────────────────────────────────────

def test_sender_classification_dhl():
    assert _classify_sender("odprawacelna@dhl.com")          == "dhl"
    assert _classify_sender("administracja_centralna@dhl.com") == "dhl"
    assert _classify_sender("Some Person <plwawecs@dhl.com>") == "dhl"

def test_sender_classification_agency():
    assert _classify_sender("piotr@acspedycja.pl")  == "agency"
    assert _classify_sender("biuro@acspedycja.pl")  == "agency"
    assert _classify_sender("logistyka@acspedycja.pl") == "agency"

def test_sender_classification_ganther():
    assert _classify_sender("ciagarlak@ganther.com.pl") == "ganther"

def test_sender_classification_internal():
    assert _classify_sender("Tejal <import@estrellajewels.eu>") == "internal"
    assert _classify_sender("amit@estrellajewels.com")          == "internal"

def test_sender_classification_fedex():
    assert _classify_sender("pl-import@fedex.com") == "fedex"

def test_sender_classification_unknown():
    assert _classify_sender("random@example.com") == "unknown"


# ── AWB extraction ───────────────────────────────────────────────────────────

def test_awb_extract_polish_phrase():
    assert _AWB in _extract_awbs_from_text(f"przesyłka numer: {_AWB}")

def test_awb_extract_awb_label():
    assert _AWB in _extract_awbs_from_text(f"AWB: {_AWB}")

def test_awb_extract_bare_10_digits():
    assert _AWB in _extract_awbs_from_text(f"see attached doc for {_AWB} please")

def test_awb_extract_skips_short_numbers():
    assert _extract_awbs_from_text("invoice 123 totals 5000") == []


# ── Matcher: AWB-targeted ────────────────────────────────────────────────────

def test_match_awb_in_subject():
    email = {
        "subject":     f"[T#1WA2604140000123] - Agencja Celna DHL - przesyłka numer: {_AWB}",
        "from":        "odprawacelna@dhl.com",
        "body":        "",
        "attachments": [],
    }
    r = match_email_to_shipment(email, target_awb=_AWB)
    assert r["matched"] is True
    assert "subject" in r["matched_fields"]
    assert r["awb"] == _AWB
    assert r["sender_role"] == "dhl"
    assert r["ticket"] == "T#1WA2604140000123"

def test_match_awb_in_body_only():
    email = {
        "subject":     "Re: customs question",
        "from":        "biuro@acspedycja.pl",
        "body":        f"Witam, dla przesyłki {_AWB} prosimy o uzupełnienie dokumentów.",
        "attachments": [],
    }
    r = match_email_to_shipment(email, target_awb=_AWB)
    assert r["matched"] is True
    assert "body" in r["matched_fields"]
    assert r["sender_role"] == "agency"

def test_match_awb_in_forwarded_body():
    forwarded = (
        "---------- Forwarded message ---------\n"
        "From: odprawacelna@dhl.com\n"
        f"Subject: Agencja Celna DHL - przesyłka numer: {_AWB}\n"
        "\n"
        f"Treść: AWB {_AWB} wymaga opisu zawartości."
    )
    email = {
        "subject":     "Fwd: DHL clearance request",
        "from":        "import@estrellajewels.eu",   # internal forwarder
        "body":        forwarded,
        "attachments": [],
    }
    r = match_email_to_shipment(email, target_awb=_AWB)
    assert r["matched"] is True
    assert "body" in r["matched_fields"]
    assert r["sender_role"] == "internal"
    assert r["detected_type"] in ("internal_forward", "translation", "broker_notification")

def test_match_awb_in_attachment_filename():
    email = {
        "subject":     "Documents",
        "from":        "ciagarlak@ganther.com.pl",
        "body":        "Please find docs attached.",
        "attachments": [{"filename": f"DSK_{_AWB}.pdf"}, {"filename": "invoice.pdf"}],
    }
    r = match_email_to_shipment(email, target_awb=_AWB)
    assert r["matched"] is True
    assert "attachment" in r["matched_fields"]
    assert r["awb"] == _AWB
    types = {a["type"] for a in r["attachments"]}
    assert "dsk"     in types
    assert "invoice" in types

def test_match_random_email_does_not_match():
    email = {
        "subject":     "Newsletter — Q2 update",
        "from":        "marketing@example.com",
        "body":        "Read about our latest products...",
        "attachments": [],
    }
    r = match_email_to_shipment(email, target_awb=_AWB)
    assert r["matched"] is False


# ── Matcher: broad mode (no specific AWB) ────────────────────────────────────

def test_broad_mode_finds_any_awb():
    email = {
        "subject":     f"przesyłka numer: 1234567890",
        "from":        "odprawacelna@dhl.com",
        "body":        "Tłumaczenie zawartości przesyłki wymagane.",
        "attachments": [],
    }
    r = match_email_to_shipment(email)
    assert r["matched"] is True
    assert r["awb"] == "1234567890"

def test_broad_mode_trusted_sender_with_keyword():
    email = {
        "subject":     "Pytanie do Państwa",
        "from":        "piotr@acspedycja.pl",
        "body":        "Dzień dobry, dotyczy odprawy celnej z dnia wczorajszego.",
        "attachments": [],
    }
    # No AWB but trusted sender + customs keyword → match
    r = match_email_to_shipment(email)
    assert r["matched"] is True


# ── Scan endpoint behaviour ──────────────────────────────────────────────────

def test_scan_no_token_returns_no_credentials(monkeypatch):
    monkeypatch.delenv("ZOHO_MAIL_API_TOKEN", raising=False)
    result = scan_for_dhl_customs_emails(zoho_api_token=None, target_awb=_AWB)
    assert isinstance(result, dict)
    assert result["scan_method"] == "no_credentials"
    assert result["matched"] == 0
    assert result["search_mode"] == "awb_targeted"
    assert result["awb_used"] == _AWB

def test_email_scan_mode_setting_default():
    """Default mode must be 'auto' so existing deployments behave unchanged."""
    from app.core.config import Settings
    s = Settings()
    assert s.email_scan_mode in ("auto", "bridge_only", "api_only")
    # Default unless overridden in env
    import os
    if "EMAIL_SCAN_MODE" not in os.environ:
        assert s.email_scan_mode == "auto"


def test_email_scan_template_registered():
    """Bridge should know about email_scan task type with email_scan_results allowed."""
    from app.services.ai_bridge import TASK_TEMPLATES, _ALLOWED_WRITES
    assert "email_scan" in TASK_TEMPLATES
    template = TASK_TEMPLATES["email_scan"]
    assert "awb" in template["instructions"].lower()
    assert "email_scan_results" in template["result_schema"]
    assert "email_scan_results" in _ALLOWED_WRITES["email_scan"]


def test_email_scan_result_validates_with_allowed_keys(tmp_path, monkeypatch):
    """Importing an email_scan result must be accepted when it writes only email_scan_results."""
    monkeypatch.setattr(
        "app.services.ai_bridge.settings",
        type("S", (), {"storage_root": tmp_path})(),
    )
    from app.services.ai_bridge import create_task, import_result
    from app.utils.io import write_json_atomic

    audit_path = tmp_path / "outputs" / "TEST_BATCH" / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": "TEST_BATCH", "tracking_no": _AWB}
    write_json_atomic(audit_path, audit)

    task = create_task(
        batch_id="TEST_BATCH",
        task_type="email_scan",
        payload={"awb": _AWB, "batch_id": "TEST_BATCH"},
    )
    assert task["task_type"] == "email_scan"

    outcome = import_result(
        task_id=task["task_id"],
        result={
            "task_id": task["task_id"],
            "result_data": {
                "email_scan_results": {
                    "awb":        _AWB,
                    "scanned_at": "2026-04-28T10:00:00Z",
                    "matched":    1,
                    "emails": [
                        {
                            "subject":     f"DHL clearance — przesyłka numer: {_AWB}",
                            "from":        "odprawacelna@dhl.com",
                            "detected_type": "translation",
                            "awb":         _AWB,
                            "matched_fields": ["subject", "body"],
                        }
                    ],
                },
            },
        },
        audit=audit,
        audit_path=audit_path,
    )
    assert outcome["ok"] is True
    assert "email_scan_results" in outcome["applied_keys"]


def test_email_scan_rejects_forbidden_field(tmp_path, monkeypatch):
    """Bridge must reject a result that tries to write a forbidden financial field."""
    monkeypatch.setattr(
        "app.services.ai_bridge.settings",
        type("S", (), {"storage_root": tmp_path})(),
    )
    from app.services.ai_bridge import create_task, import_result
    from app.utils.io import write_json_atomic

    audit_path = tmp_path / "outputs" / "T2" / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": "T2"}
    write_json_atomic(audit_path, audit)

    task = create_task(batch_id="T2", task_type="email_scan",
                      payload={"awb": _AWB})
    with pytest.raises(ValueError, match="disallowed"):
        import_result(
            task_id=task["task_id"],
            result={
                "task_id": task["task_id"],
                "result_data": {
                    "email_scan_results": {"awb": _AWB, "matched": 0, "emails": []},
                    "cif": 9999.99,   # forbidden financial field
                },
            },
            audit=audit,
            audit_path=audit_path,
        )


def test_scan_awb_targeted_uses_search_endpoint():
    """When AWB is given, we must hit the search endpoint, not the folder list."""
    fake_msg = {
        "messageId":     "999",
        "threadId":      "777",
        "subject":       f"DHL Agencja Celna - przesyłka numer: {_AWB}",
        "fromAddress":   "odprawacelna@dhl.com",
        "receivedTime":  "1714298400000",
    }
    list_resp = MagicMock()
    list_resp.json.return_value = {"data": [fake_msg]}
    list_resp.raise_for_status = MagicMock()

    body_resp = MagicMock()
    body_resp.json.return_value = {"data": {"content": f"Tłumaczenie zawartości {_AWB}"}}
    body_resp.raise_for_status = MagicMock()

    captured_urls = []
    def _fake_get(url, headers=None, params=None, timeout=None):
        captured_urls.append((url, params or {}))
        # First call = search; subsequent = body fetch
        return list_resp if "/messages/search" in url or "/messages?" in url or "/folders/" in url else body_resp
    fake_req = MagicMock()
    fake_req.get = _fake_get
    with patch.dict(sys.modules, {"requests": fake_req}):
        result = scan_for_dhl_customs_emails(
            zoho_api_token="fake-token",
            target_awb=_AWB,
            limit=10,
        )
    assert result["search_mode"] == "awb_targeted"
    assert result["scan_method"] == "rest_api_search"
    # Verify the URL hit was the search endpoint (not folders/.../messages)
    assert any("/messages/search" in u for u, _ in captured_urls)
    # Verify the searchKey contained the AWB
    search_calls = [p for u, p in captured_urls if "/messages/search" in u]
    assert search_calls, "search endpoint never hit"
    assert _AWB in str(search_calls[0])
    assert result["matched"] >= 1
    assert result["emails"][0]["awb"] == _AWB
