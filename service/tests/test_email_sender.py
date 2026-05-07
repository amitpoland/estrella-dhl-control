"""
test_email_sender.py — Real SMTP delivery for queued emails.

Verifies:
  - SMTP missing → status stays pending, error="smtp_not_configured"
  - Idempotency: re-send returns existing state without re-transmitting
  - Successful send marks status=sent, stores provider_message_id, and
    updates audit.{agency,dhl}_reply_package with send_verified=true
  - Missing attachments returns clear error, NOT a sent state
  - SMTP auth failure returns clear error, NOT a sent state
  - No financial fields modified
"""
from __future__ import annotations

import json
import smtplib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


def _settings(tmp_path: Path, **overrides):
    class S:
        storage_root  = tmp_path
        smtp_host     = "smtppro.zoho.in"
        smtp_port     = 465
        smtp_user     = None
        smtp_password = None
        smtp_use_ssl  = True
        mcp_send_max_attachment_bytes = 200_000
    for k, v in overrides.items():
        setattr(S, k, v)
    return S()


def _seed_queue(tmp_path: Path, queue_id: str = "Q1", batch_id: str = "B1",
                attachment_files: int = 0, status: str = "pending"):
    """Seed email_queue.json + a batch audit with optional attachment files."""
    # Build batch dir
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    attach_paths = []
    for i in range(attachment_files):
        p = batch_dir / f"att_{i}.pdf"
        p.write_bytes(b"%PDF-1.4 fake content for test")
        attach_paths.append({"label": f"att_{i}", "path": str(p), "filename": p.name})

    audit = {
        "batch_id":            batch_id,
        "agency_reply_package": {
            "to":          "biuro@acspedycja.pl",
            "cc":          "roman@acspedycja.pl, info@estrellajewels.eu",
            "subject":     "TEST customs",
            "body_pl":     "Polski",
            "body_en":     "English",
            "attachments": attach_paths,
            "email_id":    queue_id,
            "status":      "queued",
        },
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    queue = [{
        "id":        queue_id,
        "batch_id":  batch_id,
        "to":        "biuro@acspedycja.pl, biuro@acspedycja.pl",   # dup to test dedupe
        "cc":        "roman@acspedycja.pl, info@estrellajewels.eu",
        "subject":   "TEST customs",
        "body_text": "plain body",
        "body_html": "<p>html body</p>",
        "status":    status,
    }]
    (tmp_path / "email_queue.json").write_text(json.dumps(queue), encoding="utf-8")
    return queue_id, batch_id


# ── SMTP not configured → stays pending ──────────────────────────────────────

def test_no_smtp_returns_smtp_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings", _settings(tmp_path))
    qid, _ = _seed_queue(tmp_path)
    from app.services.email_sender import send_queued_email
    r = send_queued_email(qid)
    assert r["ok"] is False
    assert r["error"] == "SMTP_NOT_CONFIGURED"
    assert r["status"] == "pending"
    # Email Evidence V2: MCP send is disabled — only manual_package is offered
    # alongside SMTP-fix as fallback.
    assert "manual_package" in r["available_methods"]
    assert "zoho_mcp" not in r["available_methods"]
    # Queue still pending
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"


# ── Idempotency: already-sent returns existing state ─────────────────────────

def test_already_sent_returns_existing_state(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings",
                       _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, _ = _seed_queue(tmp_path, status="sent")
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    queue[0]["sent_at"] = "2026-04-29T01:00:00Z"
    queue[0]["provider_message_id"] = "<existing@id>"
    (tmp_path / "email_queue.json").write_text(json.dumps(queue))

    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL") as smtp:
        r = send_queued_email(qid)
    smtp.assert_not_called()
    assert r["ok"] is True
    assert r["already_sent"] is True
    assert r["provider_message_id"] == "<existing@id>"


# ── Successful send marks sent + updates audit ───────────────────────────────

def test_successful_send_marks_sent_and_updates_audit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings",
                       _settings(tmp_path, smtp_user="info@estrellajewels.eu",
                                 smtp_password="app-pass"))
    qid, batch_id = _seed_queue(tmp_path, attachment_files=2)

    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__  = MagicMock(return_value=False)
    fake_smtp.send_message = MagicMock()
    fake_smtp.login = MagicMock()

    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL", return_value=fake_smtp):
        r = send_queued_email(qid)

    assert r["ok"] is True
    assert r["status"] == "sent"
    assert r["provider_message_id"]
    assert r["attachments_count"] == 2
    # Recipients deduped (TO had two copies of same address)
    assert r["recipients"]["to"] == ["biuro@acspedycja.pl"]
    # CC drops anything already in TO
    assert "biuro@acspedycja.pl" not in r["recipients"]["cc"]

    # Queue marked sent
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "sent"
    assert queue[0]["provider_message_id"]
    assert queue[0]["sent_via"] == "smtp_zoho"

    # Audit updated
    audit = json.loads((tmp_path / "outputs" / batch_id / "audit.json").read_text())
    arp = audit["agency_reply_package"]
    assert arp["status"] == "sent"
    assert arp["send_verified"] is True
    assert arp["provider_message_id"]
    assert arp["sent_via"] == "smtp_zoho"


# ── Missing attachment file → clear error, not sent ──────────────────────────

def test_missing_attachment_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings",
                       _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, batch_id = _seed_queue(tmp_path, attachment_files=1)
    # Delete the file
    audit = json.loads((tmp_path / "outputs" / batch_id / "audit.json").read_text())
    Path(audit["agency_reply_package"]["attachments"][0]["path"]).unlink()

    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL") as smtp:
        r = send_queued_email(qid)
    smtp.assert_not_called()
    assert r["ok"] is False
    assert r["error"] == "attachments_missing"
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"


# ── SMTP auth failure → clear error, not sent ────────────────────────────────

def test_smtp_auth_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings",
                       _settings(tmp_path, smtp_user="x", smtp_password="bad"))
    qid, _ = _seed_queue(tmp_path, attachment_files=0)

    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__  = MagicMock(return_value=False)
    fake_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad auth")

    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL", return_value=fake_smtp):
        r = send_queued_email(qid)
    assert r["ok"] is False
    assert r["error"] == "smtp_auth_failed"
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"


# ── No financial fields modified ─────────────────────────────────────────────

def test_send_does_not_touch_financial_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings",
                       _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, batch_id = _seed_queue(tmp_path, attachment_files=1)
    audit = json.loads((tmp_path / "outputs" / batch_id / "audit.json").read_text())
    audit["invoice_totals"]    = {"total_cif_usd": 10000.00}
    audit["clearance_decision"] = {"total_value_usd": 10000.00}
    (tmp_path / "outputs" / batch_id / "audit.json").write_text(json.dumps(audit))

    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__  = MagicMock(return_value=False)
    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL", return_value=fake_smtp):
        send_queued_email(qid)
    after = json.loads((tmp_path / "outputs" / batch_id / "audit.json").read_text())
    assert after["invoice_totals"]["total_cif_usd"]      == 10000.00
    assert after["clearance_decision"]["total_value_usd"] == 10000.00


# ── Fallback ladder: manual_package ──────────────────────────────────────────

def test_manual_package_returns_assembled_package_no_send(tmp_path, monkeypatch):
    """method=manual_package returns the package, status stays pending."""
    monkeypatch.setattr("app.services.email_sender.settings", _settings(tmp_path))
    qid, _ = _seed_queue(tmp_path, attachment_files=2)
    from app.services.email_sender import send_queued_email
    r = send_queued_email(qid, method="manual_package")
    assert r["ok"] is True
    assert r["method"] == "manual_package"
    assert r["status"] == "pending"
    assert r["package"]["to"] == ["biuro@acspedycja.pl"]   # deduped
    assert "biuro@acspedycja.pl" not in r["package"]["cc"]  # dropped from CC
    assert len(r["package"]["attachments"]) == 2
    # Queue NOT marked sent
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"


# ── Fallback ladder: mcp ─────────────────────────────────────────────────────

# ── Email Evidence V2: MCP send is disabled at the gate ─────────────────────
# All zoho_mcp call shapes now return {ok:false, error:'mcp_send_disabled'}.
# The legacy approval/confirm/cap/handoff branches are unreachable. The tests
# below pin the disabled contract; the legacy branches' code is preserved
# behind the gate (do not delete) for future re-enable.

def _assert_mcp_disabled(r):
    assert r["ok"] is False
    assert r["error"] == "mcp_send_disabled"
    assert "smtp" in r["available_methods"]
    assert "manual_package" in r["available_methods"]
    assert "zoho_mcp" not in r["available_methods"]


def test_mcp_send_returns_disabled_without_approval(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings", _settings(tmp_path))
    qid, _ = _seed_queue(tmp_path, attachment_files=1)
    from app.services.email_sender import send_queued_email
    _assert_mcp_disabled(send_queued_email(qid, method="zoho_mcp", confirm_mcp_send=True))


def test_mcp_send_returns_disabled_without_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings", _settings(tmp_path))
    qid, _ = _seed_queue(tmp_path, attachment_files=1)
    from app.services.email_sender import send_queued_email
    _assert_mcp_disabled(send_queued_email(qid, method="zoho_mcp", approved_by="admin"))


def test_mcp_back_compat_alias_mcp_also_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings", _settings(tmp_path))
    qid, _ = _seed_queue(tmp_path, attachment_files=1)
    from app.services.email_sender import send_queued_email
    r = send_queued_email(qid, method="mcp", approved_by="admin", confirm_mcp_send=True)
    _assert_mcp_disabled(r)


def test_mcp_send_no_thread_disabled(tmp_path, monkeypatch):
    s = _settings(tmp_path); s.mcp_send_max_attachment_bytes = 100_000
    monkeypatch.setattr("app.services.email_sender.settings", s)
    qid, _ = _seed_queue(tmp_path, attachment_files=1)
    from app.services.email_sender import send_queued_email
    _assert_mcp_disabled(send_queued_email(qid, method="zoho_mcp", approved_by="admin", confirm_mcp_send=True))


def test_mcp_send_with_thread_disabled(tmp_path, monkeypatch):
    s = _settings(tmp_path); s.mcp_send_max_attachment_bytes = 100_000
    monkeypatch.setattr("app.services.email_sender.settings", s)
    qid, _ = _seed_queue(tmp_path, attachment_files=0)
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    queue[0]["reply_to_message_id"] = "msg-12345"
    (tmp_path / "email_queue.json").write_text(json.dumps(queue))
    from app.services.email_sender import send_queued_email
    _assert_mcp_disabled(send_queued_email(qid, method="zoho_mcp", approved_by="admin", confirm_mcp_send=True))


def test_mcp_send_large_attachments_still_disabled(tmp_path, monkeypatch):
    s = _settings(tmp_path); s.mcp_send_max_attachment_bytes = 40
    monkeypatch.setattr("app.services.email_sender.settings", s)
    qid, _ = _seed_queue(tmp_path, attachment_files=2)
    from app.services.email_sender import send_queued_email
    _assert_mcp_disabled(send_queued_email(qid, method="zoho_mcp", confirm_mcp_send=True, approved_by="admin"))


def test_mcp_send_within_cap_still_disabled(tmp_path, monkeypatch):
    s = _settings(tmp_path); s.mcp_send_max_attachment_bytes = 10_000
    monkeypatch.setattr("app.services.email_sender.settings", s)
    qid, _ = _seed_queue(tmp_path, attachment_files=1)
    from app.services.email_sender import send_queued_email
    r = send_queued_email(qid, method="zoho_mcp", confirm_mcp_send=True, approved_by="admin")
    _assert_mcp_disabled(r)
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"


def test_unknown_method_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.email_sender.settings", _settings(tmp_path))
    qid, _ = _seed_queue(tmp_path)
    from app.services.email_sender import send_queued_email
    r = send_queued_email(qid, method="carrier_pigeon")
    assert r["ok"] is False
    assert r["error"] == "unknown_method"


# ── PZ-decoupling guard tests ────────────────────────────────────────────────

def test_polish_desc_route_does_not_require_pz():
    """Read the route source: Polish description handler must NOT call any PZ guard."""
    src = open("/Users/amitgupta/Downloads/CLI/service/app/api/routes_dhl_clearance.py",
               "r", encoding="utf-8").read()
    idx = src.find('@router.post("/generate-description/')
    assert idx > 0
    section = src[idx:idx + 5000]
    assert "guard_pz_requires_sad" not in section
    assert "pz_status" not in section


def test_dsk_route_does_not_require_pz():
    """DSK generation route must NOT call any PZ guard."""
    src = open("/Users/amitgupta/Downloads/CLI/service/app/api/routes_dsk.py",
               "r", encoding="utf-8").read()
    assert "guard_pz_requires_sad" not in src
    assert "pz_status" not in src


# ──────────────────────────────────────────────────────────────────────────
# Proposal-driven attachments (proactive_dispatch silent-send fix)
# ──────────────────────────────────────────────────────────────────────────

def _seed_queue_with_proposal_attachments(
    tmp_path: Path,
    queue_id: str = "Q_PROP",
    batch_id: str = "B_PROP",
    attachment_files: int = 2,
):
    """Seed a queue + audit where the attachments live in
    audit.action_proposals[*].draft.attachments (the proactive_dispatch
    layout), not in agency_reply_package / dhl_reply_package."""
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    attach_paths = []
    for i in range(attachment_files):
        p = batch_dir / f"prop_att_{i}.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        attach_paths.append({"label": f"prop_att_{i}", "path": str(p), "filename": p.name})

    audit = {
        "batch_id": batch_id,
        "action_proposals": [{
            "proposal_id": "p-1",
            "type":        "dhl_proactive_dispatch",
            "status":      "queued",
            "email_id":    queue_id,
            "draft": {
                "to":          "odprawacelna@dhl.example",
                "cc":          "",
                "subject":     "AWB X — Customs",
                "body_text":   "...",
                "body_html":   "<pre>...</pre>",
                "attachments": attach_paths,
            },
        }],
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    queue = [{
        "id":        queue_id,
        "batch_id":  batch_id,
        "to":        "odprawacelna@dhl.example",
        "cc":        "",
        "subject":   "AWB X — Customs",
        "body_text": "plain body",
        "body_html": "<p>html body</p>",
        "status":    "pending",
    }]
    (tmp_path / "email_queue.json").write_text(json.dumps(queue), encoding="utf-8")
    return queue_id, batch_id, attach_paths


def test_proactive_proposal_attachments_resolved_and_sent(tmp_path, monkeypatch):
    """Proactive-dispatch attachments must be picked up from the
    proposal.draft.attachments path and attached to the MIME."""
    monkeypatch.setattr("app.services.email_sender.settings",
                        _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, _, atts = _seed_queue_with_proposal_attachments(
        tmp_path, attachment_files=2,
    )

    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        r = send_queued_email(qid, method="smtp")

    assert r["ok"] is True, r
    assert r["status"] == "sent"
    assert r["attachments_count"] == 2
    smtp.send_message.assert_called_once()


def test_proactive_with_attachment_list_cannot_send_body_only(tmp_path, monkeypatch):
    """Silent-send guard: if the proposal declares attachments but the
    resolver returns zero (e.g. attachments key in an unscanned location),
    the send must be refused with attachments_unresolved, NOT marked sent."""
    monkeypatch.setattr("app.services.email_sender.settings",
                        _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, _, _ = _seed_queue_with_proposal_attachments(
        tmp_path, attachment_files=2,
    )

    # Patch the resolver to return empty (simulating a future bug where
    # the location moves) while _expected_attachment_count still sees the
    # 2 declared attachments.
    from app.services import email_sender as es
    with patch.object(es, "_attachments_for_queue", return_value=([], [])), \
         patch("smtplib.SMTP_SSL") as smtp_cls:
        r = es.send_queued_email(qid, method="smtp")
        smtp_cls.assert_not_called()

    assert r["ok"] is False
    assert r["error"] == "attachments_unresolved"
    assert "refusing to send body-only" in r["error_detail"]
    # Queue must NOT be marked sent
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"
    # Error marker persisted on queue entry
    assert queue[0]["error"] == "attachments_unresolved"


def test_missing_attachment_marks_queue_error_and_does_not_send(tmp_path, monkeypatch):
    """When _attachments_for_queue reports a missing file, the send is
    refused AND the queue entry's error field is updated so a retry sees
    the prior failure."""
    monkeypatch.setattr("app.services.email_sender.settings",
                        _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, _, atts = _seed_queue_with_proposal_attachments(
        tmp_path, attachment_files=1,
    )
    # Delete the file so it's missing at send time
    Path(atts[0]["path"]).unlink()

    from app.services.email_sender import send_queued_email
    with patch("smtplib.SMTP_SSL") as smtp_cls:
        r = send_queued_email(qid, method="smtp")
        smtp_cls.assert_not_called()

    assert r["ok"] is False
    assert r["error"] == "attachments_missing"
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["status"] == "pending"
    assert queue[0]["error"]  == "attachments_missing"


def test_expected_attachment_count_reads_proposal_draft(tmp_path, monkeypatch):
    """_expected_attachment_count must count attachments from
    action_proposals[*].draft.attachments when proposal.email_id matches."""
    monkeypatch.setattr("app.services.email_sender.settings",
                        _settings(tmp_path, smtp_user="x", smtp_password="y"))
    qid, _, _ = _seed_queue_with_proposal_attachments(
        tmp_path, attachment_files=6,
    )
    from app.services.email_sender import _expected_attachment_count
    # Simulate the queue entry as the resolver sees it
    entry = json.loads((tmp_path / "email_queue.json").read_text())[0]
    assert _expected_attachment_count(entry) == 6
