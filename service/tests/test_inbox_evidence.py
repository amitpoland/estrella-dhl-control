"""
test_inbox_evidence.py — Contract tests for GET /api/v1/inbox/evidence/{item_id}.

Sprint 03.3 Scope C / PR-E3a: per-item evidence detail for the V2 Inbox
evidence panel.

The evidence endpoint is a pure read with per-source field allowlists. These
tests pin the full marker contract and — critically — the no-leak posture: the
projections must NEVER surface email bodies, draft to/cc/body, message
body_text/attachments, proforma JSON blobs, or any financial figure.

Coverage:
  1.  Auth required (no API key → 401/403 in prod mode).
  2.  Unknown prefix → 404 unknown_item_type.
  3.  Proposal (pending) → 200, subject-only; draft to/body NOT leaked.
  4.  Proposal resolved → 200 {ok:false, gone:true}.
  5.  Proposal missing → 404 not_found.
  6.  DHL evidence (real stored file) → 200; body_text/attachments NOT leaked.
  7.  DHL missing evidence → 404 not_found.
  8.  Proforma draft → 200, identity/lifecycle fields only; no JSON blobs.
  9.  Proforma draft missing → 404 not_found.
  10. Proforma draft non-numeric id → 404 not_found.
  11. Email evidence as admin → 200, subject/to/status; body NOT leaked.
  12. Email evidence as non-admin (no session) → 403 forbidden (no oracle).
  13. Email evidence as non-admin (operator session) → 403 forbidden.
  14. Cache-Control: no-store on 200 / 404 / 403 responses.
  15. Source read raises → 200 {ok:false, degraded:true} (generic error only).
  16. Zero-side-effect: no scan module import (static guard, evidence-scoped).
  17. DHL summary allowlist: rogue summary field / matched_identifiers stripped.
  18. no-store also on gone:true and degraded:true (200) responses.
  19. Every non-pending proposal status → gone; draft content never leaks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


# ── helpers ──────────────────────────────────────────────────────────────────

def _api_key_header() -> Dict[str, str]:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _seed_proposal(tmp_path: Path, batch_id: str, proposal: Dict[str, Any]) -> None:
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "action_proposals": [proposal]}
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")


def _seed_dhl_awb(tmp_path: Path, awb: str, *, summary: Dict[str, bool],
                  message: Dict[str, Any], batch_ids: list) -> None:
    by_awb = tmp_path / "email_evidence" / "by_awb"
    by_awb.mkdir(parents=True, exist_ok=True)
    doc = {
        "awb":             awb,
        "batch_ids":       batch_ids,
        "threads":         [{"messages": [message]}],
        "summary":         summary,
        "last_message_at": "2026-06-10T10:00:00",
        "last_scan_at":    "2026-06-10T10:05:00",
    }
    (by_awb / f"{awb}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def client(tmp_path) -> TestClient:
    with patch.object(settings, "storage_root", tmp_path):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── Test 1: auth required ─────────────────────────────────────────────────────

def test_evidence_requires_auth_in_prod(tmp_path):
    """No API key in prod mode → 401/403 before any resolver runs."""
    with (
        patch.object(settings, "api_key", "prod-secret-key"),
        patch.object(settings, "auth_secret_key", "test-secret-key-not-placeholder"),
        patch.object(settings, "environment", "prod"),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/v1/inbox/evidence/proposal-anything")  # no auth header
    assert r.status_code in (401, 403)


# ── Test 2: unknown prefix ────────────────────────────────────────────────────

def test_unknown_prefix_returns_404_unknown_item_type(client):
    r = client.get("/api/v1/inbox/evidence/banana-123", headers=_api_key_header())
    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "unknown_item_type"


# ── Test 3: proposal (pending) — subject only, no body/to leak ────────────────

def test_proposal_evidence_subject_only_no_body_leak(client, tmp_path):
    """A pending proposal returns the draft subject only — to/cc/body never leak."""
    secret_body = "CONFIDENTIAL-BODY-DO-NOT-LEAK"
    secret_to   = "secret-recipient@dhl.example"
    proposal = {
        "proposal_id": "pid-subj",
        "type":        "dhl_reply",
        "batch_id":    "BATCH-EV",
        "status":      "pending_review",
        "reason":      "DHL asked for docs",
        "created_at":  "2026-06-10T09:00:00Z",
        "draft": {
            "subject":     "Re: Customs documents for AWB 123",
            "to":          secret_to,
            "cc":          "boss@example.com",
            "body":        secret_body,
            "attachments": [{"name": "invoice.pdf"}],
        },
    }
    _seed_proposal(tmp_path, "BATCH-EV", proposal)

    r = client.get("/api/v1/inbox/evidence/proposal-pid-subj", headers=_api_key_header())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    ev = body["evidence"]
    assert ev["draft_subject"] == "Re: Customs documents for AWB 123"
    assert ev["proposal_type"] == "dhl_reply"
    assert ev["status"] == "pending_review"
    assert ev["can_approve"] is True
    assert ev["linked_batch_id"] == "BATCH-EV"

    # No-leak: the whole serialized response must not carry body / recipients /
    # attachment filenames.
    raw = r.text
    assert secret_body not in raw
    assert secret_to not in raw
    assert "invoice.pdf" not in raw
    assert "boss@example.com" not in raw
    # Projection must not even carry the keys.
    assert "to" not in ev
    assert "body" not in ev
    assert "attachments" not in ev


# ── Test 4: proposal resolved → gone ──────────────────────────────────────────

def test_resolved_proposal_returns_gone(client, tmp_path):
    proposal = {
        "proposal_id": "pid-gone",
        "type":        "dhl_reply",
        "batch_id":    "BATCH-GONE",
        "status":      "approved",      # no longer pending_review
        "reason":      "already handled",
        "created_at":  "2026-06-10T09:00:00Z",
        "draft":       {"subject": "x"},
    }
    _seed_proposal(tmp_path, "BATCH-GONE", proposal)

    r = client.get("/api/v1/inbox/evidence/proposal-pid-gone", headers=_api_key_header())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["gone"] is True


# ── Test 5: proposal missing → not_found ──────────────────────────────────────

def test_missing_proposal_returns_not_found(client):
    r = client.get("/api/v1/inbox/evidence/proposal-nope", headers=_api_key_header())
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# ── Test 6: DHL evidence (real stored file) — no body_text/attachment leak ─────

def test_dhl_evidence_no_body_leak(client, tmp_path):
    """DHL evidence reads the stored by_awb file; lineage strips body/attachments."""
    secret = "DHL-MESSAGE-BODY-SECRET"
    _seed_dhl_awb(
        tmp_path, "4789974092",
        summary={
            "dhl_request_received": True,
            "our_dhl_reply_sent":   False,
            "our_dhl_reply_queued": False,
        },
        message={
            "direction":   "incoming",
            "event_type":  "dhl_request",
            "subject":     "Need customs docs",
            "sender":      "dhl@dhl.example",
            "timestamp":   "2026-06-10T10:00:00",
            "body_text":   secret,
            "attachments": [{"name": "request.pdf"}],
        },
        batch_ids=["GJ-2026-001"],
    )

    r = client.get("/api/v1/inbox/evidence/dhl-4789974092", headers=_api_key_header())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    ev = body["evidence"]
    assert ev["awb"] == "4789974092"
    assert ev["batch_ids"] == ["GJ-2026-001"]
    assert ev["summary"]["dhl_request_received"] is True
    assert ev["next_action"]["priority"] == "urgent"

    lineage = ev["thread_lineage"]
    assert len(lineage) == 1
    msg = lineage[0]
    assert msg["direction"] == "incoming"
    assert msg["event_type"] == "dhl_request"
    assert msg["subject"] == "Need customs docs"
    assert msg["sender"] == "dhl@dhl.example"
    # Body / attachments must be stripped — key absent AND value absent.
    assert "body_text" not in msg
    assert "attachments" not in msg
    assert secret not in r.text
    assert "request.pdf" not in r.text


# ── Test 7: DHL missing evidence → not_found ─────────────────────────────────

def test_missing_dhl_evidence_returns_not_found(client):
    """An AWB with no stored evidence file resolves to not_found (empty scaffold)."""
    r = client.get("/api/v1/inbox/evidence/dhl-NO-SUCH-AWB", headers=_api_key_header())
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# ── Test 8: proforma draft → identity/lifecycle only, no JSON blobs ───────────

def test_proforma_draft_evidence_projection(client, tmp_path):
    from app.services import proforma_invoice_link_db as pildb

    db_path = tmp_path / "proforma_links.db"
    draft, created = pildb.upsert_pending_draft(
        db_path,
        batch_id="BATCH-PF",
        client_name="UAB Tomas Gold",
        currency="EUR",
        exchange_rate=4.30,
        source_lines_json=json.dumps([{"sku": "SECRET-SKU", "price": 99999}]),
    )
    assert created is True
    assert draft.id is not None

    r = client.get(
        f"/api/v1/inbox/evidence/proforma-draft-{draft.id}",
        headers=_api_key_header(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    ev = body["evidence"]
    assert ev["draft_id"] == draft.id
    assert ev["client_name"] == "UAB Tomas Gold"
    assert ev["batch_id"] == "BATCH-PF"
    assert ev["currency"] == "EUR"

    # No-leak: line JSON / sku / price must never appear in the projection.
    raw = r.text
    assert "SECRET-SKU" not in raw
    assert "99999" not in raw
    assert "source_lines_json" not in ev
    assert "editable_lines_json" not in ev
    assert "buyer_override_json" not in ev
    assert "ship_to_override_json" not in ev
    assert "payment_terms_json" not in ev
    assert "exchange_rate" not in ev
    # The projection is an explicit allowlist — pin its exact key set so a future
    # field added to ProformaDraft cannot silently flow through.
    assert set(ev.keys()) == {
        "draft_id", "draft_state", "client_name", "batch_id", "currency",
        "fullnumber", "created_at", "updated_at", "post_failed_at",
    }


# ── Test 9: proforma draft missing → not_found ────────────────────────────────

def test_missing_proforma_draft_returns_not_found(client):
    r = client.get("/api/v1/inbox/evidence/proforma-draft-999999", headers=_api_key_header())
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# ── Test 10: proforma draft non-numeric id → not_found ───────────────────────

def test_non_numeric_proforma_draft_id_returns_not_found(client):
    r = client.get("/api/v1/inbox/evidence/proforma-draft-abc", headers=_api_key_header())
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# ── Test 11: email evidence as admin — subject/to/status, no body leak ────────

def test_email_evidence_admin_no_body_leak(tmp_path):
    admin_user = {"id": "u1", "role": "admin", "is_active": True, "is_approved": True}
    secret_html = "<p>SECRET-EMAIL-HTML</p>"
    email_item = {
        "id":        "001",
        "status":    "pending",
        "subject":   "Customs forward",
        "to":        "agency@test.pl",
        "batch_id":  "BATCH-EM",
        "queued_at": "2026-06-10T09:00:00Z",
        "body_html": secret_html,
        "body_text": "SECRET-EMAIL-TEXT",
    }

    with (
        patch("app.auth.dependencies.get_current_user_optional", return_value=admin_user),
        patch("app.services.email_service.get_all_emails", return_value=[email_item]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get(
                "/api/v1/inbox/evidence/email-001",
                headers=_api_key_header(),
                cookies={"pz_session": "fake-admin-token"},
            )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    ev = body["evidence"]
    assert ev["subject"] == "Customs forward"
    assert ev["to"] == "agency@test.pl"
    assert ev["status"] == "pending"
    assert "body_html" not in ev
    assert "body_text" not in ev
    assert "SECRET-EMAIL-HTML" not in r.text
    assert "SECRET-EMAIL-TEXT" not in r.text


# ── Test 12: email evidence as non-admin (no session) → 403, no oracle ────────

def test_email_evidence_non_admin_no_session_forbidden(tmp_path):
    """Non-admin (no session) → 403 BEFORE lookup. The email exists, yet the
    response is 403 (not 404) so it cannot be used as an existence oracle."""
    email_item = {"id": "002", "status": "pending", "subject": "x", "to": "y@z"}
    with (
        patch("app.services.email_service.get_all_emails", return_value=[email_item]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get("/api/v1/inbox/evidence/email-002", headers=_api_key_header())

    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


# ── Test 13: email evidence as non-admin (operator session) → 403 ────────────

def test_email_evidence_operator_session_forbidden(tmp_path):
    operator = {"id": "u2", "role": "operator", "is_active": True, "is_approved": True}
    with (
        patch("app.auth.dependencies.get_current_user_optional", return_value=operator),
        patch("app.services.email_service.get_all_emails", return_value=[]),
        patch.object(settings, "storage_root", tmp_path),
    ):
        tmp_path.joinpath("outputs").mkdir(exist_ok=True)
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.get(
                "/api/v1/inbox/evidence/email-anything",
                headers=_api_key_header(),
                cookies={"pz_session": "fake-operator-token"},
            )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


# ── Test 14: Cache-Control no-store on 200 / 404 / 403 ───────────────────────

def test_cache_control_no_store_on_all_responses(client, tmp_path):
    # 404 (unknown prefix)
    r404 = client.get("/api/v1/inbox/evidence/banana-1", headers=_api_key_header())
    assert "no-store" in r404.headers.get("cache-control", "")

    # 403 (email non-admin, no session)
    r403 = client.get("/api/v1/inbox/evidence/email-x", headers=_api_key_header())
    assert r403.status_code == 403
    assert "no-store" in r403.headers.get("cache-control", "")

    # 200 (pending proposal)
    _seed_proposal(tmp_path, "BATCH-CC", {
        "proposal_id": "pid-cc", "type": "dhl_reply", "batch_id": "BATCH-CC",
        "status": "pending_review", "reason": "r", "created_at": "2026-06-10T09:00:00Z",
        "draft": {"subject": "s"},
    })
    r200 = client.get("/api/v1/inbox/evidence/proposal-pid-cc", headers=_api_key_header())
    assert r200.status_code == 200
    assert "no-store" in r200.headers.get("cache-control", "")


# ── Test 15: source read raises → degraded ───────────────────────────────────

def test_source_error_degrades_gracefully(client, tmp_path):
    """If the underlying evidence read raises, the endpoint returns 200 with a
    degraded marker — it never 500s the panel."""
    with patch(
        "app.services.email_evidence_store.get_by_awb",
        side_effect=RuntimeError("disk gone"),
    ):
        r = client.get("/api/v1/inbox/evidence/dhl-12345", headers=_api_key_header())

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    # Generic category only — the raw exception string must never reach the
    # response (it could carry source content).
    assert body["error"] == "evidence_read_error"
    assert "disk gone" not in r.text


# ── Test 16: zero-side-effect — no scan module import (evidence-scoped) ───────

def test_evidence_path_imports_no_scan_module():
    """The evidence endpoint lives in routes_inbox; that module must not import
    the Zoho/Gmail scan triggers — proving the evidence path cannot fire a scan.
    """
    import ast
    import importlib.util

    spec = importlib.util.find_spec("app.api.routes_inbox")
    assert spec is not None
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))

    forbidden = {
        "dhl_email_monitor",          # owns scan_for_dhl_customs_emails
        "email_evidence_ingestor",    # calls the scan trigger
        "routes_dhl_clearance",
        "email_intelligence_store",
        "scan_for_dhl_customs_emails",  # direct symbol import guard
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            names = " ".join(a.name for a in getattr(node, "names", []))
            for fm in forbidden:
                assert fm not in module and fm not in names, (
                    f"routes_inbox.py must not import {fm} — evidence path must "
                    "never reach a live scan"
                )


# ── Test 17: DHL summary allowlist — rogue field stripped ────────────────────

def test_dhl_summary_allowlists_known_flags_only(client, tmp_path):
    """A rogue (non-flag) key written into the stored summary blob must never
    flow through the projection — only the 9 known boolean flags are exposed."""
    rogue = "ROGUE-SUMMARY-PII-LEAK"
    _seed_dhl_awb(
        tmp_path, "5550001111",
        summary={
            "dhl_request_received": True,
            "operator_note":        rogue,        # rogue non-flag field
            "sender_email":         "leak@x.example",
        },
        message={
            "direction":  "incoming",
            "event_type": "dhl_request",
            "subject":    "docs",
            "sender":     "dhl@dhl.example",
            "timestamp":  "2026-06-10T10:00:00",
            # Derived intelligence that must not surface in lineage:
            "matched_identifiers": {"invoice": "INV-SECRET-9"},
        },
        batch_ids=["B1"],
    )

    r = client.get("/api/v1/inbox/evidence/dhl-5550001111", headers=_api_key_header())
    assert r.status_code == 200
    ev = r.json()["evidence"]

    # Summary carries exactly the 9 known flags — nothing else.
    assert set(ev["summary"].keys()) == {
        "dhl_request_received", "our_dhl_reply_sent", "our_dhl_reply_queued",
        "dhl_documents_received", "agency_forward_sent", "agency_forward_queued",
        "agency_sad_received", "dhl_invoice_received", "agency_invoice_received",
    }
    assert ev["summary"]["dhl_request_received"] is True
    assert "operator_note" not in ev["summary"]
    assert "sender_email" not in ev["summary"]
    assert rogue not in r.text
    assert "leak@x.example" not in r.text

    # Lineage exposes the 5 allowlisted fields only — matched_identifiers absent.
    msg = ev["thread_lineage"][0]
    assert "matched_identifiers" not in msg
    assert "INV-SECRET-9" not in r.text


# ── Test 18: no-store on gone:true and degraded:true (200) responses ─────────

def test_cache_control_no_store_on_gone_and_degraded(client, tmp_path):
    # gone:true (resolved proposal) is a 200 — must still be no-store.
    _seed_proposal(tmp_path, "BATCH-G", {
        "proposal_id": "pid-g", "type": "dhl_reply", "batch_id": "BATCH-G",
        "status": "approved", "reason": "r", "created_at": "2026-06-10T09:00:00Z",
        "draft": {"subject": "s"},
    })
    rg = client.get("/api/v1/inbox/evidence/proposal-pid-g", headers=_api_key_header())
    assert rg.status_code == 200 and rg.json()["gone"] is True
    assert "no-store" in rg.headers.get("cache-control", "")

    # degraded:true (source raised) is a 200 — must still be no-store.
    with patch(
        "app.services.email_evidence_store.get_by_awb",
        side_effect=RuntimeError("boom"),
    ):
        rd = client.get("/api/v1/inbox/evidence/dhl-999", headers=_api_key_header())
    assert rd.status_code == 200 and rd.json()["degraded"] is True
    assert "no-store" in rd.headers.get("cache-control", "")


# ── Test 19: every non-pending proposal status resolves to gone ──────────────

@pytest.mark.parametrize("status", ["approved", "rejected", "queued", "sent"])
def test_non_pending_proposal_status_is_gone(client, tmp_path, status):
    """Only pending_review proposals expose draft content; every other status
    (including future terminal states) must report gone, never leak the draft."""
    secret = f"DRAFT-SUBJECT-{status}-SECRET"
    _seed_proposal(tmp_path, f"BATCH-{status}", {
        "proposal_id": f"pid-{status}", "type": "dhl_reply",
        "batch_id": f"BATCH-{status}", "status": status, "reason": "r",
        "created_at": "2026-06-10T09:00:00Z",
        "draft": {"subject": secret, "body": "should-not-leak"},
    })
    r = client.get(
        f"/api/v1/inbox/evidence/proposal-pid-{status}", headers=_api_key_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["gone"] is True
    # A non-pending proposal must not leak any draft content.
    assert secret not in r.text
    assert "should-not-leak" not in r.text
