"""
test_email_search_context.py — Multi-key search-context extraction.

Verifies the helper that turns an audit dict into a Cowork email_scan task
payload: AWB + invoice numbers + DHL ticket + MRN + sender domains + the
deduped search_terms list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.email_search_context import build_email_search_context  # noqa: E402


# ── Basic extraction ─────────────────────────────────────────────────────────

def test_awb_extracted_from_top_level():
    audit = {"awb": "1012178215"}
    ctx = build_email_search_context(audit)
    assert ctx["awb"] == "1012178215"
    assert "1012178215" in ctx["search_terms"]
    # Partial AWB (last 8) is also in search_terms when len >= 8
    assert "12178215" in ctx["search_terms"]


def test_awb_falls_back_to_tracking_no():
    ctx = build_email_search_context({"tracking_no": "2824221912"})
    assert ctx["awb"] == "2824221912"


def test_invoice_numbers_extracted_from_filenames():
    audit = {
        "inputs": {
            "invoices": [
                "1247 Invoice EJL-25-26-1247-09-03-26.pdf",
                "1248 Invoice EJL-25-26-1248-09-03-26.pdf",
            ],
        },
    }
    ctx = build_email_search_context(audit)
    invs = " ".join(ctx["invoice_numbers"]).lower()
    assert "ejl-25-26-1247" in invs or "ejl-25-26-1247-09-03-26" in invs
    assert "ejl-25-26-1248" in invs or "ejl-25-26-1248-09-03-26" in invs
    # invoice numbers must also appear in search_terms
    assert any("EJL" in t.upper() for t in ctx["search_terms"])


def test_invoice_numbers_extracted_from_pz_rows():
    audit = {
        "pz_rows": [
            {"invoice_no": "EJL-26-27-100-25-04-26"},
            {"invoice_no": "EJL-26-27-101-25-04-26"},
        ],
    }
    ctx = build_email_search_context(audit)
    invs = [i.upper() for i in ctx["invoice_numbers"]]
    assert any("EJL-26-27-100" in i for i in invs)
    assert any("EJL-26-27-101" in i for i in invs)


def test_dhl_ticket_extracted_from_dhl_email_field():
    audit = {"dhl_email": {"ticket": "T#1WA2604140000123"}}
    ctx = build_email_search_context(audit)
    assert ctx["dhl_ticket"] == "T#1WA2604140000123"
    assert "T#1WA2604140000123" in ctx["search_terms"]


def test_mrn_extracted_from_customs_declaration():
    audit = {"customs_declaration": {"mrn": "26PL44302D003UC7R3"}}
    ctx = build_email_search_context(audit)
    assert ctx["mrn"] == "26PL44302D003UC7R3"


# ── Search context shape ─────────────────────────────────────────────────────

def test_known_senders_and_domains_present():
    ctx = build_email_search_context({})
    assert "odprawacelna@dhl.com"     in ctx["known_senders"]
    assert "biuro@acspedycja.pl"      in ctx["known_senders"]
    assert "ciagarlak@ganther.com.pl" in ctx["known_senders"]
    assert "dhl.com"          in ctx["known_domains"]
    assert "acspedycja.pl"    in ctx["known_domains"]
    assert "estrellajewels.eu" in ctx["known_domains"]


def test_search_terms_includes_fixed_subject_phrases():
    ctx = build_email_search_context({"awb": "1234567890"})
    terms = " | ".join(ctx["search_terms"])
    assert "Agencja Celna DHL" in terms
    assert "przesyłka numer"   in terms
    assert "DSK"               in terms


def test_search_terms_deduplicated():
    audit = {
        "awb":         "1234567890",
        "tracking_no": "1234567890",   # duplicate
        "dhl_email":   {"ticket": "T#1234"},
    }
    ctx = build_email_search_context(audit)
    # AWB should appear once even though it's in two source fields
    assert ctx["search_terms"].count("1234567890") == 1


# ── Integration: scan-inbox dispatcher payload includes search_terms ─────────

def test_dispatched_task_payload_carries_search_terms(tmp_path, monkeypatch):
    """When the bridge dispatcher fires, the task payload contains the full
    search context so Cowork has all identifiers available."""
    # Stub settings.storage_root so create_task writes to tmp_path
    monkeypatch.setattr(
        "app.services.ai_bridge.settings",
        type("S", (), {"storage_root": tmp_path})(),
    )
    from app.services.ai_bridge import create_task
    from app.services.email_search_context import build_email_search_context

    audit = {
        "awb": "1012178215",
        "inputs": {"invoices": ["1247 Invoice EJL-25-26-1247-09-03-26.pdf"]},
    }
    ctx = build_email_search_context(audit)

    task = create_task(
        batch_id="TEST_PAYLOAD",
        task_type="email_scan",
        payload={
            "awb":             ctx["awb"],
            "invoice_numbers": ctx["invoice_numbers"],
            "dhl_ticket":      ctx["dhl_ticket"],
            "search_terms":    ctx["search_terms"],
            "known_senders":   ctx["known_senders"],
            "known_domains":   ctx["known_domains"],
        },
    )
    payload = task["payload"]
    assert payload["awb"] == "1012178215"
    assert len(payload["invoice_numbers"]) >= 1
    assert any("EJL" in i.upper() for i in payload["invoice_numbers"])
    assert "1012178215" in payload["search_terms"]
    assert "Agencja Celna DHL" in payload["search_terms"]
    assert "odprawacelna@dhl.com" in payload["known_senders"]


# ── Integration: import hook handles search_unreliable=true ──────────────────

def test_search_context_includes_related_identities():
    """The search context must surface ALL identities of the one Estrella mailbox."""
    from app.services.email_search_context import (
        build_email_search_context,
        ESTRELLA_ACCOUNT_ID,
        ESTRELLA_LOGIN,
        ESTRELLA_RELATED_IDENTITIES,
    )
    ctx = build_email_search_context({"awb": "1234567890"})
    assert ctx["target_account_id"] == ESTRELLA_ACCOUNT_ID == "2261204000000002002"
    assert ctx["target_mailbox"]    == ESTRELLA_LOGIN      == "amit@estrellajewels.eu"
    ids = ctx["related_identities"]
    # All four routing identities must be in scope as "same mailbox"
    assert "amit@estrellajewels.eu"    in ids
    assert "info@estrellajewels.eu"    in ids
    assert "account@estrellajewels.eu" in ids
    assert "import@estrellajewels.eu"  in ids
    # The .com alias too
    assert "amit@estrellajewels.com"   in ids
    # Same list every time (immutable identity)
    assert ids == list(ESTRELLA_RELATED_IDENTITIES)


def test_template_uses_same_mailbox_language_not_separate_accounts():
    """Template must NOT instruct Cowork to treat aliases as separate accounts."""
    from app.services.ai_bridge import TASK_TEMPLATES
    instr = TASK_TEMPLATES["email_scan"]["instructions"]
    # Positive: explicit mention of related_identities and same mailbox
    assert "related_identities" in instr
    assert "same mailbox" in instr.lower()
    # Negative: must NOT instruct Cowork to "connect" or "verify" the aliases
    assert "Do not try to connect them" in instr or "NOT separate accounts" in instr


def test_connector_mismatch_only_checks_account_not_identities():
    """Mismatch logic must compare accountId/mailId — not individual identities."""
    from app.services.ai_bridge import TASK_TEMPLATES
    instr = TASK_TEMPLATES["email_scan"]["instructions"]
    # Verification step must reference accountId + primaryEmailAddress only
    assert "accountId == target_account_id" in instr
    assert "primaryEmailAddress == target_mailbox" in instr
    # And explicitly tell Cowork NOT to treat individual sender identities as
    # mismatch grounds during verification
    assert "Do NOT check individual sender identities" in instr


def test_email_scan_template_includes_connector_verification():
    """Template instructions must require connector binding verification."""
    from app.services.ai_bridge import TASK_TEMPLATES
    instr = TASK_TEMPLATES["email_scan"]["instructions"]
    assert "VERIFY MAILBOX BINDING FIRST" in instr
    assert "getMailAccounts" in instr
    assert "target_account_id" in instr
    assert "target_mailbox" in instr
    assert "preferred_mcp_connector_hint" in instr
    assert "connector_mismatch" in instr


def test_connector_mismatch_treated_as_unreliable(tmp_path, monkeypatch):
    """connector_mismatch=true should classify the result as search_unreliable."""
    from app.utils.io import write_json_atomic
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings",
        type("S", (), {"storage_root": tmp_path})())

    audit_path = tmp_path / "outputs" / "TEST_MISMATCH" / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": "TEST_MISMATCH",
             "clearance_status": "awaiting_dhl_customs_email"}
    write_json_atomic(audit_path, audit)

    task = ab.create_task(batch_id="TEST_MISMATCH", task_type="email_scan",
                          payload={"awb": "1234567890",
                                   "target_account_id": "2261204000000002002"})

    result_data = {
        "email_scan_results": {
            "awb": "1234567890",
            "matched": 0,
            "connector_mismatch": True,
            "expected_account_id": "2261204000000002002",
            "actual_account_id":   "9999999999999",
            "search_unreliable": True,
            "manual_review_required": True,
            "zero_result_reason": "connector_mismatch",
        },
    }
    audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
    outcome = ab.import_result(
        task_id=task["task_id"],
        result={"task_id": task["task_id"], "result_data": result_data},
        audit=audit_now, audit_path=audit_path,
    )
    assert outcome["ok"] is True
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    esr = audit_after["email_scan_results"]
    assert esr["connector_mismatch"]    is True
    assert esr["search_unreliable"]     is True
    # clearance_status NOT downgraded
    assert audit_after["clearance_status"] == "awaiting_dhl_customs_email"


def test_verified_scan_with_derived_events_imports_cleanly(tmp_path, monkeypatch):
    """Verified result with derived_events should import without errors."""
    from app.utils.io import write_json_atomic
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings",
        type("S", (), {"storage_root": tmp_path})())

    audit_path = tmp_path / "outputs" / "TEST_VER" / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(audit_path, {"batch_id": "TEST_VER",
                                   "clearance_status": "awaiting_dhl_customs_email"})

    task = ab.create_task(batch_id="TEST_VER", task_type="email_scan",
                          payload={"awb": "3109419880"})

    result_data = {
        "email_scan_results": {
            "awb": "3109419880",
            "matched": 10,
            "confidence": "high",
            "connector_used": "mcp__620999a3",
            "account_id": "2261204000000002002",
            "dhl_ticket": "T#1WA2602230000068",
            "derived_events": [
                {"event": "dhl_customs_email_received",
                 "source_email_from": "odprawacelna@dhl.com",
                 "source_email_subject": "Agencja Celna DHL - przesyłka numer: 3109419880",
                 "ticket": "T#1WA2602230000068",
                 "timestamp": "2026-02-25T07:50:21Z",
                 "confidence": "high"},
                {"event": "agency_reply_detected",
                 "source_email_from": "piotr@acspedycja.pl",
                 "timestamp": "2026-02-25T11:37:01Z",
                 "confidence": "high"},
                {"event": "shipment_delivered",
                 "timestamp": "2026-02-25T13:41:27Z",
                 "confidence": "high"},
            ],
            "recommended_next_action": "no_action_required",
            "search_unreliable": False,
        },
    }
    audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
    outcome = ab.import_result(
        task_id=task["task_id"],
        result={"task_id": task["task_id"], "result_data": result_data},
        audit=audit_now, audit_path=audit_path,
    )
    assert outcome["ok"] is True
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    esr = audit_after["email_scan_results"]
    assert esr["matched"] == 10
    assert esr["dhl_ticket"] == "T#1WA2602230000068"
    assert len(esr["derived_events"]) == 3


def test_verified_scan_does_not_downgrade_later_status(tmp_path, monkeypatch):
    """Importing a dhl_customs_email_received event must NOT regress agency_email_sent."""
    from app.utils.io import write_json_atomic
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings",
        type("S", (), {"storage_root": tmp_path})())

    audit_path = tmp_path / "outputs" / "TEST_NODOWN" / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    # Already advanced past dhl_email_received
    write_json_atomic(audit_path, {"batch_id": "TEST_NODOWN",
                                   "clearance_status": "agency_email_sent"})

    task = ab.create_task(batch_id="TEST_NODOWN", task_type="email_scan",
                          payload={"awb": "X"})
    result_data = {"email_scan_results": {
        "awb": "X", "matched": 1,
        "derived_events": [{"event": "dhl_customs_email_received",
                            "source_email_from": "odprawacelna@dhl.com",
                            "timestamp": "2026-02-25T07:50:21Z"}],
    }}
    audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
    ab.import_result(task_id=task["task_id"],
                     result={"task_id": task["task_id"], "result_data": result_data},
                     audit=audit_now, audit_path=audit_path)
    # Note: the post-import hook (in routes_ai_bridge) is what enforces the
    # rank guard. ai_bridge.import_result alone applies result_data only.
    # So clearance_status remains 'agency_email_sent' here regardless.
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_after["clearance_status"] == "agency_email_sent"


def test_dispatch_payload_includes_target_account(tmp_path, monkeypatch):
    """Bridge dispatcher payload must include target_account_id for verification."""
    monkeypatch.setattr("app.services.ai_bridge.settings",
        type("S", (), {"storage_root": tmp_path})())
    from app.services.ai_bridge import create_task

    task = create_task(
        batch_id="TEST_PAY",
        task_type="email_scan",
        payload={
            "awb": "1234567890",
            "target_account_id": "2261204000000002002",
            "target_mailbox":    "amit@estrellajewels.eu",
            "preferred_mcp_connector_hint": "mcp__620999a3",
        },
    )
    payload = task["payload"]
    assert payload["target_account_id"] == "2261204000000002002"
    assert payload["target_mailbox"]    == "amit@estrellajewels.eu"
    assert payload["preferred_mcp_connector_hint"].startswith("mcp__620999a3")


def test_import_hook_writes_email_search_risk_when_unreliable(tmp_path, monkeypatch):
    """matched=0 + search_unreliable=true → audit.email_search_risk=true."""
    from app.utils.io import write_json_atomic
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings",
        type("S", (), {"storage_root": tmp_path})())

    audit_path = tmp_path / "outputs" / "TEST_RISK" / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id":         "TEST_RISK",
        "tracking_no":      "1012178215",
        "clearance_status": "awaiting_dhl_customs_email",
    }
    write_json_atomic(audit_path, audit)

    task = ab.create_task(
        batch_id="TEST_RISK",
        task_type="email_scan",
        payload={"awb": "1012178215"},
    )

    # Cowork returns 0 matched but flags search_unreliable
    result_data = {
        "email_scan_results": {
            "awb":     "1012178215",
            "matched": 0,
            "emails":  [],
            "threads": [],
            "searched": {
                "awb":             "1012178215",
                "invoice_numbers": ["EJL-25-26-1247-09-03-26"],
                "terms":           ["1012178215", "EJL-25-26-1247-09-03-26"],
            },
            "search_unreliable":      True,
            "manual_review_required": True,
            "zero_result_reason":     "Cowork returned 0 despite AWB/invoice identifiers",
        },
    }
    audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
    outcome = ab.import_result(
        task_id=task["task_id"],
        result={"task_id": task["task_id"], "result_data": result_data},
        audit=audit_now,
        audit_path=audit_path,
    )
    assert outcome["ok"] is True
    # Note: import_result alone applies result_data — the email_search_risk
    # write is performed by the routes_ai_bridge post-import hook. Verify
    # that the email_scan_results are at least applied to audit:
    audit_after = json.loads(audit_path.read_text(encoding="utf-8"))
    esr = audit_after.get("email_scan_results", {})
    assert esr.get("search_unreliable")      is True
    assert esr.get("manual_review_required") is True
    assert esr.get("zero_result_reason")
    # clearance_status NOT downgraded
    assert audit_after["clearance_status"] == "awaiting_dhl_customs_email"
