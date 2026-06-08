"""
test_dhl_proactive_dispatch.py — P2 Slice A test bundle.

Covers the proactive DHL customs dispatch feature end-to-end:

  * proposal creation endpoint (POST /api/v1/dhl/proactive-dispatch/{batch_id})
  * authentication hardening on the action-proposals router
  * proactive-only G9 guards at queue time
  * authoritative recipient/CC re-resolution from settings at queue time
  * type-discriminated failure handling around queue_email
  * concurrent proposal creation dedup + concurrent queue exactly-once
  * customs-value-freeze on every audit/timeline write
  * Slice A negative-scope guards (no clearance_status mutation, no PZ/wFirma,
    no carrier_arrived_at_poland_at, no tracking_events read required)
  * non-proactive proposal regression — existing types retain bubbling

Locked invariants exercised:
  D1 — env-driven recipient
  D2 — env-driven CC
  D3 — no new clearance_status value
  D4 — Polish-first AWB-first subject
  D5 — new builder file
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

# ── Path / env setup ─────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# NOTE: do NOT do `os.environ.setdefault("API_KEY", ...)` at module-import
# time. pytest collects this file before app.core.config.settings is
# instantiated; a module-level env mutation here pollutes os.environ for the
# entire pytest session, and pydantic then reads it as the singleton baseline
# — leaking `settings.api_key="test-key"` into every subsequent test in the
# session (e.g. ZC429 dashboard tests then start failing with 401). The
# `dhl_env` fixture below already monkeypatches `settings.api_key` per-test.


# ── Autouse fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point storage_root at tmp_path; reset proposal locks between tests.

    Also scopes the API_KEY env var to per-test (via monkeypatch.setenv)
    rather than relying on a module-level os.environ mutation that would
    pollute settings.api_key across the whole pytest session.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setenv("API_KEY", "test-key")
    from app.api import routes_action_proposals
    from app.services import action_email_builder
    for mod in (routes_action_proposals, action_email_builder):
        monkeypatch.setattr(mod, "_OUTPUTS", tmp_path / "outputs")
    # Reset per-batch locks so tests do not share state
    from app.utils import proposal_lock
    proposal_lock._reset_locks_for_tests()


@pytest.fixture
def dhl_env(monkeypatch):
    """Default DHL customs env: dev mode with explicit recipient + CC."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "environment",     "dev",            raising=False)
    monkeypatch.setattr(settings, "dhl_customs_email", "customs@dhl.example", raising=False)
    monkeypatch.setattr(settings, "dhl_customs_cc",    "ops@estrellajewels.eu", raising=False)
    monkeypatch.setattr(settings, "api_key",          "test-key",       raising=False)
    # SMTP off by default; tests that exercise the new autosend path
    # explicitly patch _smtp_configured to True.
    monkeypatch.setattr(settings, "smtp_user",        "",               raising=False)
    monkeypatch.setattr(settings, "smtp_password",    "",               raising=False)
    return settings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _render_minimal_valid_polish_desc(path: Path, *, awb: str) -> None:
    """Render a minimal Polish customs description PDF that satisfies the
    format validator. Used by all _make_batch invocations so the new
    approve/queue gate (services.polish_desc_validator) can read real text.
    Synthetic refs are AWB-derived so legacy tests (audit lacks
    invoice_names) still produce a structurally complete PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet()
    n = styles["Normal"]
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    doc.build([
        Paragraph(f"AWB / Nr listu: {awb}", n),
        Paragraph(f"FAKTURA / INVOICE: EJL/26-27/{awb[-3:] if len(awb) >= 3 else '001'}", n),
        Paragraph("14-karatowe złoto próby 585", n),
        Paragraph("Razem CIF faktury / Invoice CIF total: USD 100.00", n),
        Paragraph("PODSUMOWANIE / CONSOLIDATED CUSTOMS SUMMARY", n),
        Paragraph("Razem ilość / Total quantity: 1 PCS · 0 PRS", n),
        Paragraph("Razem FOB / Total FOB: USD 100.00", n),
        Paragraph("Fracht / Freight: USD 0.00", n),
        Paragraph("Ubezpieczenie / Insurance: USD 0.00", n),
        Paragraph("RAZEM CIF / TOTAL CIF (customs value): USD 100.00", n),
    ])


def _make_batch(
    root: Path,
    *,
    batch_id: str | None = None,
    awb:      str = "1234567890",
    customs_package_generated: bool = True,
    polish_desc: bool = True,
    invoices:    int = 1,
    awb_pdf:     bool = True,
    extra:       Dict[str, Any] | None = None,
) -> Tuple[str, Path, Path]:
    bid = batch_id or f"BATCH_{uuid.uuid4().hex[:8]}"
    batch_dir = root / "outputs" / bid
    (batch_dir / "source" / "invoices").mkdir(parents=True, exist_ok=True)
    (batch_dir / "source" / "awb").mkdir(parents=True, exist_ok=True)

    # Polish description PDF lives at storage_root/polish_descriptions/.
    # Render a real PDF (not a stub byte string) so the polish-desc format
    # validator can extract text and find the required structural markers.
    if polish_desc:
        (root / "polish_descriptions").mkdir(parents=True, exist_ok=True)
        _render_minimal_valid_polish_desc(
            root / "polish_descriptions" / f"POLISH_DESC_{bid}.pdf",
            awb=awb,
        )

    # Invoices
    for i in range(invoices):
        (batch_dir / "source" / "invoices" / f"invoice_{i+1}.pdf").write_bytes(b"%PDF-1.4 inv")

    # AWB PDF
    if awb_pdf:
        (batch_dir / "source" / "awb" / "awb.pdf").write_bytes(b"%PDF-1.4 awb")

    audit: Dict[str, Any] = {
        "batch_id":   bid,
        "awb":        awb,
        "dhl_awb":    awb,
        "carrier":    "DHL",
        "tracking_no": awb,
        "status":     "processing",
        "clearance_decision": {
            "total_value_usd": 800.0,
            "threshold_usd":   2500.0,
            "clearance_path":  "dhl_self_clearance",
            "require_dsk":     False,
        },
        "inputs": {
            "invoices": [f"invoice_{i+1}.pdf" for i in range(invoices)],
            "awb":      "awb.pdf" if awb_pdf else "",
        },
        "timeline":             [],
        "action_proposals":     [],
        "polish_desc_filename": f"POLISH_DESC_{bid}.pdf" if polish_desc else "",
    }
    if customs_package_generated:
        audit["customs_package_generated_at"] = "2026-05-07T10:00:00Z"
    if extra:
        audit.update(extra)

    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    return bid, batch_dir, ap


def _read_audit(ap: Path) -> Dict[str, Any]:
    return json.loads(ap.read_text(encoding="utf-8"))


def _post_proactive(client, bid: str, operator_id: str = "alice"):
    return client.post(
        f"/api/v1/dhl/proactive-dispatch/{bid}",
        json={"operator_id": operator_id},
        headers={"X-API-Key": "test-key"},
    )


def _approve(client, proposal_id: str, approved_by: str = "bob"):
    return client.post(
        f"/api/v1/action-proposals/{proposal_id}/approve",
        json={"approved_by": approved_by},
        headers={"X-API-Key": "test-key"},
    )


def _queue(client, proposal_id: str):
    return client.post(
        f"/api/v1/action-proposals/{proposal_id}/queue",
        headers={"X-API-Key": "test-key"},
    )


@pytest.fixture
def client(dhl_env):
    """FastAPI TestClient with API key auth configured."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


# ── 1. Proposal creation happy path ─────────────────────────────────────────

class TestProposalCreation:

    def test_creates_proposal_with_requested_at_timestamp(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["is_new"] is True
        assert body["status"] == "pending_review"

        a = _read_audit(ap)
        assert a["proactive_dispatch_requested_at"]
        assert a["proactive_dispatch_proposal_id"] == body["proposal_id"]
        prop = a["action_proposals"][0]
        assert prop["type"] == "dhl_proactive_dispatch"
        assert prop["created_by"] == "alice"
        assert prop["status"] == "pending_review"

    def test_emits_requested_event(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        _post_proactive(client, bid, "alice")
        a = _read_audit(ap)
        events = [e["event"] for e in a["timeline"]]
        assert "dhl_proactive_dispatch_requested" in events

    def test_idempotent_duplicate_post(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        r2 = _post_proactive(client, bid, "alice")
        assert r1.json()["proposal_id"] == r2.json()["proposal_id"]
        assert r2.json()["is_new"] is False
        a = _read_audit(ap)
        proactive_props = [p for p in a["action_proposals"]
                           if p["type"] == "dhl_proactive_dispatch"]
        assert len(proactive_props) == 1


# ── 2. G-PC precondition guards ─────────────────────────────────────────────

class TestPreconditionGuards:

    def test_blocks_when_carrier_not_dhl(self, tmp_path, client):
        bid, _, _ = _make_batch(tmp_path, extra={"carrier": "FedEx"})
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "carrier_not_dhl"

    def test_blocks_when_clearance_path_is_agency(self, tmp_path, client):
        bid, _, _ = _make_batch(tmp_path, extra={
            "clearance_decision": {"clearance_path": "agency_clearance"},
        })
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "agency_path_active"

    def test_blocks_when_customs_package_not_generated(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path, customs_package_generated=False)
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "customs_package_not_generated"

    def test_blocks_when_already_dispatched(self, tmp_path, client):
        bid, _, ap = _make_batch(
            tmp_path,
            extra={"proactive_dispatch_sent_at": "2026-05-06T12:00:00Z"},
        )
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "already_dispatched"

    def test_blocks_when_dsk_present(self, tmp_path, client):
        bid, _, _ = _make_batch(tmp_path, extra={"dsk_filename": "DSK_xyz.pdf"})
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "dsk_already_created"

    def test_blocks_when_agency_reply_package_active(self, tmp_path, client):
        bid, _, _ = _make_batch(tmp_path, extra={
            "agency_reply_package": {"status": "queued"},
        })
        r = _post_proactive(client, bid, "alice")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "agency_path_active"

    def test_blocks_when_batch_not_found(self, tmp_path, client):
        r = _post_proactive(client, "nonexistent_batch", "alice")
        assert r.status_code == 404


# ── 3. Authentication ───────────────────────────────────────────────────────

class TestAuthentication:

    def test_proactive_endpoint_requires_api_key(self, tmp_path, client):
        bid, _, _ = _make_batch(tmp_path)
        r = client.post(
            f"/api/v1/dhl/proactive-dispatch/{bid}",
            json={"operator_id": "alice"},
        )
        assert r.status_code == 401

    def test_action_proposals_list_requires_api_key(self, tmp_path, client):
        bid, _, _ = _make_batch(tmp_path)
        r = client.get(f"/api/v1/action-proposals/{bid}")
        assert r.status_code == 401

    def test_action_proposals_approve_requires_api_key(self, tmp_path, client):
        r = client.post(
            "/api/v1/action-proposals/some-id/approve",
            json={"approved_by": "bob"},
        )
        assert r.status_code == 401

    def test_action_proposals_reject_requires_api_key(self, tmp_path, client):
        r = client.post(
            "/api/v1/action-proposals/some-id/reject",
            json={"rejected_by": "bob", "reason": "test"},
        )
        assert r.status_code == 401

    def test_action_proposals_queue_requires_api_key(self, tmp_path, client):
        r = client.post("/api/v1/action-proposals/some-id/queue")
        assert r.status_code == 401

    def test_action_proposals_refresh_requires_api_key(self, tmp_path, client):
        r = client.post("/api/v1/action-proposals/some-batch/refresh")
        assert r.status_code == 401


# ── 4. Self-approval block + queue G9 re-checks ────────────────────────────

class TestQueueGuards:

    def test_self_approval_blocked(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        # Approve as the SAME operator who created it. H-W3 (#502): the approver
        # identity is derived SERVER-SIDE, so stub the derivation to "alice"
        # (= created_by) so the self-approval guard (created_by == approved_by) fires.
        from app.api import routes_action_proposals as _rap
        with patch.object(_rap, "_approver_from_session", return_value="alice"):
            _approve(client, proposal_id, "alice")

        with patch("app.services.email_service.queue_email", return_value="email-123"):
            r = _queue(client, proposal_id)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "self_approval_blocked"

    def test_queue_rechecks_clearance_path(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Mutate audit between approve and queue: flip path to agency
        a = _read_audit(ap)
        a["clearance_decision"]["clearance_path"] = "agency_clearance"
        ap.write_text(json.dumps(a), encoding="utf-8")

        with patch("app.services.email_service.queue_email", return_value="email-123"):
            r = _queue(client, proposal_id)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "agency_path_active"

    def test_queue_rechecks_dsk_absence(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Inject DSK between approve and queue
        a = _read_audit(ap)
        a["dsk_filename"] = "DSK_xyz.pdf"
        ap.write_text(json.dumps(a), encoding="utf-8")

        with patch("app.services.email_service.queue_email", return_value="email-123"):
            r = _queue(client, proposal_id)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "dsk_already_created"

    def test_queue_rechecks_no_concurrent_send(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        a = _read_audit(ap)
        a["proactive_dispatch_sent_at"] = "2026-05-07T11:00:00Z"
        ap.write_text(json.dumps(a), encoding="utf-8")

        with patch("app.services.email_service.queue_email", return_value="email-123"):
            r = _queue(client, proposal_id)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "already_dispatched"

    def test_queue_attachment_recheck(self, tmp_path, client):
        bid, batch_dir, _ = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Delete an invoice file between approve and queue
        for f in (batch_dir / "source" / "invoices").iterdir():
            f.unlink()

        with patch("app.services.email_service.queue_email", return_value="email-123"):
            r = _queue(client, proposal_id)
        assert r.status_code == 422
        # G4 surfaces a structured detail string mentioning the file
        assert "not found" in (r.json()["detail"]) or "attachment" in str(r.json())


# ── 5. Recipient / CC re-resolution at queue time ──────────────────────────

class TestRecipientResolution:

    def test_uses_env_recipient_at_queue_time(self, tmp_path, client, monkeypatch):
        from app.core.config import settings
        from app.config import email_routing as er
        bid, _, _ = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Phase 1.3.5: empty DHL_TO so the env-var fallback path fires.
        monkeypatch.setattr(er, "DHL_TO", [])
        # Mutate env BETWEEN approve and queue
        monkeypatch.setattr(settings, "dhl_customs_email", "new-customs@dhl.example", raising=False)

        captured: Dict[str, Any] = {}

        def fake_queue(**kwargs):
            captured.update(kwargs)
            return "email-id-1"

        with patch("app.services.email_service.queue_email", side_effect=fake_queue):
            r = _queue(client, proposal_id)
        assert r.status_code == 200, r.text
        assert captured["to"] == "new-customs@dhl.example"

    def test_uses_env_cc_at_queue_time(self, tmp_path, client, monkeypatch):
        from app.core.config import settings
        from app.config import email_routing as er
        bid, _, _ = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Phase 1.3.5: empty INTERNAL_CC so the env-var CC fallback fires.
        monkeypatch.setattr(er, "INTERNAL_CC", [])
        monkeypatch.setattr(settings, "dhl_customs_cc", "new-cc@estrellajewels.eu", raising=False)

        captured: Dict[str, Any] = {}

        def fake_queue(**kwargs):
            captured.update(kwargs)
            return "email-id-1"

        with patch("app.services.email_service.queue_email", side_effect=fake_queue):
            r = _queue(client, proposal_id)
        assert r.status_code == 200, r.text
        assert captured["cc"] == "new-cc@estrellajewels.eu"

    def test_dev_mode_localhost_fallback(self, tmp_path, client, monkeypatch):
        from app.core.config import settings
        from app.config import email_routing as er
        bid, _, _ = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Phase 1.3.5: empty DHL_TO so resolve_dhl_to() returns empty and
        # the dev-null fallback path kicks in.
        monkeypatch.setattr(er, "DHL_TO", [])
        monkeypatch.setattr(settings, "dhl_customs_email", "", raising=False)
        monkeypatch.setattr(settings, "environment", "dev", raising=False)

        captured: Dict[str, Any] = {}

        def fake_queue(**kwargs):
            captured.update(kwargs)
            return "email-id-1"

        with patch("app.services.email_service.queue_email", side_effect=fake_queue):
            r = _queue(client, proposal_id)
        assert r.status_code == 200, r.text
        assert captured["to"] == "dev-null@localhost"

    @pytest.mark.parametrize("env_value", ["prod", "production", "staging"])
    def test_prod_environment_fails_loud_when_email_missing(
        self, tmp_path, client, monkeypatch, env_value,
    ):
        from app.core.config import settings
        from app.config import email_routing as er
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # Phase 1.3.5: empty DHL_TO so resolve_dhl_to() returns empty and
        # the prod-class fail-loud path kicks in.
        monkeypatch.setattr(er, "DHL_TO", [])
        monkeypatch.setattr(settings, "dhl_customs_email", "", raising=False)
        monkeypatch.setattr(settings, "environment", env_value, raising=False)

        called = {"count": 0}

        def fake_queue(**kwargs):
            called["count"] += 1
            return "email-id-1"

        with patch("app.services.email_service.queue_email", side_effect=fake_queue):
            r = _queue(client, proposal_id)
        assert r.status_code == 500
        assert "config_missing" in str(r.json())
        assert called["count"] == 0
        # No audit field written
        a = _read_audit(ap)
        assert "proactive_dispatch_sent_at" not in a

    def test_request_body_cannot_override_recipient(self, tmp_path, client):
        # The pydantic model has extra="forbid"; sending a `to` field must
        # be rejected at request validation, never reach the audit.
        bid, _, ap = _make_batch(tmp_path)
        r = client.post(
            f"/api/v1/dhl/proactive-dispatch/{bid}",
            json={"operator_id": "alice", "to": "attacker@evil.com"},
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 422  # pydantic rejection


# ── 6. Builder shape & content ─────────────────────────────────────────────

class TestBuilder:

    def test_subject_fallback_when_no_dhl_ticket(self, tmp_path, dhl_env):
        """No ticket recorded → standalone fallback subject."""
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert pkg["subject"] == f"AWB {a['awb']} — Dokumenty celne / Customs documents"
        assert not pkg["subject"].lower().startswith("re:")

    def test_subject_uses_thread_when_dhl_ticket_present(self, tmp_path, dhl_env):
        """audit.dhl_ticket present → join existing DHL thread."""
        bid, _, _ = _make_batch(tmp_path, extra={"dhl_ticket": "T#1WA0001234"})
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert pkg["subject"] == (
            f"Re:T#1WA0001234 - Agencja Celna DHL - przesyłka numer: {a['awb']}"
        )

    def test_subject_uses_thread_when_dhl_email_ticket_present(self, tmp_path, dhl_env):
        """audit.dhl_email.ticket fallback location is also honored."""
        bid, _, _ = _make_batch(
            tmp_path, extra={"dhl_email": {"ticket": "T#1WA000"}},
        )
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert "T#1WA000" in pkg["subject"]
        assert pkg["subject"].startswith("Re:T#1WA000")

    def test_builder_does_not_read_monetary_fields(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path, extra={
            "clearance_decision": {
                "clearance_path":  "dhl_self_clearance",
                "total_value_usd": 1234.56,   # would be inserted into reply body
            },
            "customs_declaration": {"cif": 999.99, "duty_a00_pln": 88.0},
            "invoice_totals":      {"total_cif_usd": 1234.56},
        })
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        body = pkg["body_text"] + pkg["body_html"]
        for forbidden in ("1234.56", "USD", "999.99", "88.0", "CIF",
                          "cif", "duty", "VAT"):
            assert forbidden not in body, (
                f"Builder body leaks {forbidden!r}; full body:\n{body}"
            )

    def test_builder_resolves_attachments(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path, invoices=2)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert pkg["missing"] == []
        labels = {att["label"] for att in pkg["attachments"]}
        assert "Polish Customs Description" in labels
        assert "AWB Document" in labels
        assert sum(1 for l in labels if l.startswith("Invoice:")) == 2

    def test_builder_reports_missing_polish_description(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path, polish_desc=False)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert any("polish description" in m.lower() for m in pkg["missing"])

    def test_builder_first_contact_no_thread_headers(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        # No reply-thread headers in the returned dict
        for forbidden_key in ("in_reply_to", "reply_to", "references", "thread_id"):
            assert forbidden_key not in pkg


# ── 7. action_email_builder registration ───────────────────────────────────

class TestActionEmailBuilderRegistration:

    def test_registry_includes_proactive_type(self):
        from app.services.action_email_builder import build_email_draft
        # Should not raise — proves the type is registered
        audit_stub = {
            "batch_id": "BATCH_TEST",
            "awb":      "AWB1",
            "inputs":   {"awb": "", "invoices": []},
        }
        draft = build_email_draft("dhl_proactive_dispatch", audit_stub)
        assert draft is not None
        assert draft.get("subject", "").startswith("AWB AWB1")

    def test_unknown_type_still_raises(self):
        from app.services.action_email_builder import build_email_draft
        with pytest.raises(ValueError):
            build_email_draft("not_a_real_type", {})


# ── 8. Attachment-missing 503 at create time ───────────────────────────────

def test_attachment_missing_at_create_returns_503(tmp_path, client):
    # Create batch WITHOUT polish description PDF — builder.missing
    # will be non-empty and the create endpoint must abort.
    bid, _, ap = _make_batch(tmp_path, polish_desc=False)
    r = _post_proactive(client, bid, "alice")
    assert r.status_code == 503
    assert "attachment" in str(r.json()).lower()
    a = _read_audit(ap)
    # Audit must be unchanged
    assert a["action_proposals"] == []
    assert "proactive_dispatch_requested_at" not in a


# ── 9. Queue happy path + first-contact send semantics ─────────────────────

class TestQueueHappyPath:

    def test_first_contact_no_reply_mime_headers(self, tmp_path, client):
        """queue_email must NOT receive reply_to/in_reply_to/references/
        thread_id MIME header kwargs. Subject text may still use 'Re:' when
        the audit carries a DHL ticket — that is a thread-aware human
        subject, not an SMTP reply header."""
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        captured: Dict[str, Any] = {}

        def fake_queue(**kwargs):
            captured.update(kwargs)
            return "email-id-1"

        with patch("app.services.email_service.queue_email", side_effect=fake_queue):
            r = _queue(client, proposal_id)
        assert r.status_code == 200, r.text
        for forbidden_key in ("reply_to", "in_reply_to", "references", "thread_id"):
            assert forbidden_key not in captured

    def test_audit_writes_no_financial_keys(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            _queue(client, proposal_id)

        a = _read_audit(ap)
        forbidden = {"unit_price", "total_value", "cif", "duty", "vat",
                     "amount", "tax", "currency", "duty_a00_pln",
                     "total_value_usd", "total_cif_usd"}
        proactive_keys = {k for k in a.keys() if k.startswith("proactive_dispatch_")}
        assert proactive_keys, "expected proactive_dispatch_* fields after queue"
        for k in proactive_keys:
            assert not (set(str(a[k]).split()) & forbidden)
            assert k not in forbidden

    def test_timeline_detail_no_financial_keys(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            _queue(client, proposal_id)

        a = _read_audit(ap)
        forbidden = {"unit_price", "total_value", "cif", "duty", "vat",
                     "amount", "tax", "currency", "duty_a00_pln",
                     "total_value_usd", "total_cif_usd"}
        for ev in a["timeline"]:
            detail = ev.get("detail") or {}
            assert not (forbidden & set(detail.keys())), (
                f"event {ev['event']!r} leaks financial key: {detail}"
            )

    def test_emits_sent_event(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            _queue(client, proposal_id)
        a = _read_audit(ap)
        events = [e["event"] for e in a["timeline"]]
        assert "dhl_proactive_dispatch_sent" in events
        assert "email_queued" in events


# ── 10. Failure-path discriminated handling ────────────────────────────────

class TestFailureHandling:

    def test_failed_emits_failed_event_and_preserves_approved_status(
        self, tmp_path, client,
    ):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        def boom(**kwargs):
            raise RuntimeError("smtp connection refused")

        with patch("app.services.email_service.queue_email", side_effect=boom):
            r = _queue(client, proposal_id)
        assert r.status_code == 500
        assert "queue_failed" in str(r.json())

        a = _read_audit(ap)
        assert a["proactive_dispatch_failed_at"]
        assert a["proactive_dispatch_failure_reason"]
        assert len(a["proactive_dispatch_failure_reason"]) <= 200
        events = [e["event"] for e in a["timeline"]]
        assert "dhl_proactive_dispatch_failed" in events
        # Proposal status remains approved
        prop = a["action_proposals"][0]
        assert prop["status"] == "approved"

    def test_non_proactive_failure_bubbles_unchanged(self, tmp_path, client):
        # Build an audit with a dhl_followup proposal manually so we can
        # verify exception bubbles per existing behavior, not via the
        # proactive failure side-effects.
        bid, _, ap = _make_batch(tmp_path)
        a = _read_audit(ap)
        proposal_id = str(uuid.uuid4())
        a["action_proposals"] = [{
            "proposal_id":  proposal_id,
            "type":         "dhl_followup",
            "batch_id":     bid,
            "status":       "approved",
            "approved_by":  "bob",
            "approved_at":  "2026-05-07T10:00:00Z",
            "reason":       "test",
            "confidence":   "high",
            "draft": {
                "to":          "odprawacelna@dhl.com",
                "cc":          "",
                "subject":     "Test",
                "body_text":   "...",
                "body_html":   "<pre>...</pre>",
                "attachments": [],
            },
            "created_at":  "2026-05-07T09:59:00Z",
            "created_by":  "alice",
            "rejected_by": None,
            "rejected_at": None,
            "reject_reason": None,
            "email_id":    None,
            "queued_at":   None,
        }]
        ap.write_text(json.dumps(a), encoding="utf-8")

        def boom(**kwargs):
            raise RuntimeError("smtp connection refused")

        with patch("app.services.email_service.queue_email", side_effect=boom):
            r = _queue(client, proposal_id)
        # Existing behavior — unwrapped exception surfaces as 500
        assert r.status_code == 500

        a2 = _read_audit(ap)
        # No proactive fields written for non-proactive type
        assert "proactive_dispatch_failed_at" not in a2
        assert "proactive_dispatch_failure_reason" not in a2
        # No proactive failed event in timeline
        events = [e["event"] for e in a2.get("timeline", [])]
        assert "dhl_proactive_dispatch_failed" not in events


# ── 11. Negative-scope guards (Slice A invariants) ─────────────────────────

class TestNegativeScopeGuards:

    def test_no_clearance_status_mutation(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path, extra={
            "clearance_status": "awaiting_dhl_customs_email",
        })
        before = _read_audit(ap)["clearance_status"]

        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            _queue(client, proposal_id)

        after = _read_audit(ap).get("clearance_status")
        assert after == before, "clearance_status MUST NOT be mutated by Slice A"

    def test_no_pz_or_wfirma_mutation(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        before = set(_read_audit(ap).keys())

        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            _queue(client, proposal_id)

        after = set(_read_audit(ap).keys())
        new_keys = after - before
        for forbidden_prefix in ("pz_", "wfirma_"):
            leaked = [k for k in new_keys if k.startswith(forbidden_prefix)]
            assert not leaked, f"Slice A leaked {forbidden_prefix}* fields: {leaked}"

    def test_no_carrier_arrived_at_poland_at_write(self, tmp_path, client):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            _queue(client, proposal_id)
        a = _read_audit(ap)
        assert "carrier_arrived_at_poland_at" not in a

    def test_no_tracking_events_required(self, tmp_path, client):
        # Audit has NO tracking_events key. Full lifecycle must succeed.
        bid, _, ap = _make_batch(tmp_path)
        a = _read_audit(ap)
        a.pop("tracking_events", None)
        ap.write_text(json.dumps(a), encoding="utf-8")

        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")
        with patch("app.services.email_service.queue_email", return_value="email-id-1"):
            r = _queue(client, proposal_id)
        assert r.status_code == 200, r.text


# ── 12. Concurrency tests ──────────────────────────────────────────────────

class TestConcurrency:

    def test_concurrent_proposal_creation_dedupes_to_one(
        self, tmp_path, client,
    ):
        bid, _, ap = _make_batch(tmp_path)

        responses: List[Any] = []
        errors: List[Exception] = []

        def worker():
            try:
                r = _post_proactive(client, bid, "alice")
                responses.append(r.json())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        proposal_ids = {r.get("proposal_id") for r in responses}
        assert len(proposal_ids) == 1, (
            f"Expected exactly one proposal_id across 8 threads, got "
            f"{proposal_ids}"
        )
        a = _read_audit(ap)
        proactive = [p for p in a["action_proposals"]
                     if p["type"] == "dhl_proactive_dispatch"]
        assert len(proactive) == 1

    def test_concurrent_queue_calls_send_exactly_one_email(
        self, tmp_path, client,
    ):
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        # queue_email mock — counts calls.
        call_count = {"n": 0}
        call_lock = threading.Lock()

        def fake_queue(**kwargs):
            with call_lock:
                call_count["n"] += 1
            return f"email-id-{call_count['n']}"

        statuses: List[int] = []
        statuses_lock = threading.Lock()

        def worker():
            with patch("app.services.email_service.queue_email",
                       side_effect=fake_queue):
                r = _queue(client, proposal_id)
                with statuses_lock:
                    statuses.append(r.status_code)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Exactly ONE queue_email invocation across all threads
        assert call_count["n"] == 1, (
            f"Expected queue_email called exactly once; got {call_count['n']}"
        )
        # Post-SMTP-autosend-fix contract:
        #   thread 1: status=approved → queue_email + (SMTP off in dhl_env)
        #             → 200 (queued)
        #   threads 2-4: status=queued + email_id → proactive_retry path
        #             → skip queue_email, SMTP off → 200 (queued)
        # Concurrent retries no longer fail with 409; they observe the prior
        # queue entry and short-circuit. queue_email-once invariant still holds.
        assert all(s == 200 for s in statuses), (
            f"All concurrent /queue calls expected 200 with SMTP off; got {statuses}"
        )

    def test_real_proposal_write_lock_primitive_used(self):
        """The lock helper must return a real threading.Lock."""
        from app.utils.proposal_lock import proposal_write_lock
        lock = proposal_write_lock("BATCH_LOCK_TYPE_PROBE")
        # Returns the SAME lock for the same batch_id
        lock2 = proposal_write_lock("BATCH_LOCK_TYPE_PROBE")
        assert lock is lock2
        # Different batch_id → different lock
        lock_other = proposal_write_lock("BATCH_OTHER")
        assert lock is not lock_other
        # Real threading.Lock — exercise acquire/release semantics
        assert lock.acquire(blocking=False)
        try:
            assert not lock.acquire(blocking=False)  # already held, can't re-acquire
        finally:
            lock.release()

    def test_per_batch_lock_independence(self, tmp_path, client):
        """A long-held lock on BATCH_A must not block POSTs for BATCH_B."""
        from app.utils.proposal_lock import proposal_write_lock
        bid_a, _, _ = _make_batch(tmp_path, batch_id="BATCH_A")
        bid_b, _, _ = _make_batch(tmp_path, batch_id="BATCH_B")

        lock_a = proposal_write_lock(bid_a)
        lock_a.acquire()
        try:
            # POST to BATCH_B must succeed even though BATCH_A is locked.
            r = _post_proactive(client, bid_b, "alice")
            assert r.status_code == 200, r.text
        finally:
            lock_a.release()


# ── 13. _OPERATOR_INITIATED_TYPES exclusion in refresh_proposals ───────────

def test_refresh_does_not_auto_resolve_proactive(tmp_path, client):
    """Proactive proposals are operator-initiated; no trigger source can
    auto-resolve them."""
    bid, _, ap = _make_batch(tmp_path)
    r1 = _post_proactive(client, bid, "alice")
    proposal_id = r1.json()["proposal_id"]

    # Manually invoke refresh_proposals with no active triggers
    from app.api.routes_action_proposals import refresh_proposals
    a = _read_audit(ap)
    refresh_proposals(ap, a, bid)
    ap.write_text(json.dumps(a), encoding="utf-8")

    a2 = _read_audit(ap)
    prop = next(p for p in a2["action_proposals"]
                if p["proposal_id"] == proposal_id)
    assert prop["status"] == "pending_review", (
        "proactive proposals must NOT be auto-resolved by refresh_proposals"
    )


# Phase 1.3 helper-resolution tests moved to test_email_routing.py
# (the helpers were promoted from this module to email_routing in Phase 1.3.5).


# ──────────────────────────────────────────────────────────────────────────
# 12. SMTP autosend on /queue (real-send fix)
# Pins the post-fix contract: /queue performs queue_email + send_queued_email
# in the same request when SMTP is configured.
# ──────────────────────────────────────────────────────────────────────────

class TestQueueAutoSendsSmtp:

    def test_queue_calls_send_queued_email_immediately(self, tmp_path, client):
        """When SMTP is configured, /queue triggers send_queued_email and
        returns delivered=True with provider_message_id + sent_at."""
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        send_calls = []

        def fake_send(queue_id, method="smtp", **kw):
            send_calls.append({"queue_id": queue_id, "method": method})
            return {
                "ok":                  True,
                "queue_id":            queue_id,
                "status":              "sent",
                "provider_message_id": "<smtp-msg-id-001@zoho>",
                "sent_at":             "2026-05-07T20:50:00+00:00",
            }

        with patch("app.services.email_service.queue_email", return_value="qid-001"), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=fake_send):
            r = _queue(client, proposal_id)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"]    == "sent"
        assert body["delivered"] is True
        assert body["email_id"]  == "qid-001"
        assert body["provider_message_id"] == "<smtp-msg-id-001@zoho>"
        assert body["sent_at"]   == "2026-05-07T20:50:00+00:00"

        # send_queued_email called exactly once with the queue id
        assert len(send_calls) == 1
        assert send_calls[0]["queue_id"] == "qid-001"
        assert send_calls[0]["method"]   == "smtp"

        # Audit reflects delivery
        a = _read_audit(ap)
        assert a["proactive_dispatch_delivered_at"]        == "2026-05-07T20:50:00+00:00"
        assert a["proactive_dispatch_provider_message_id"] == "<smtp-msg-id-001@zoho>"
        # Proposal flipped to sent
        prop = a["action_proposals"][0]
        assert prop["status"]              == "sent"
        assert prop["sent_at"]             == "2026-05-07T20:50:00+00:00"
        assert prop["provider_message_id"] == "<smtp-msg-id-001@zoho>"
        # Delivery timeline event present
        events = [e["event"] for e in a["timeline"]]
        assert "dhl_proactive_dispatch_delivered" in events

    def test_smtp_failure_records_failure_markers_and_returns_502(
        self, tmp_path, client,
    ):
        """SMTP failure: response is 502, audit captures failure markers,
        proposal stays at status='queued' (retryable)."""
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        def fail_send(queue_id, method="smtp", **kw):
            return {
                "ok":           False,
                "queue_id":     queue_id,
                "status":       "pending",
                "error":        "smtp_auth_failed",
                "error_detail": "535 authentication failed",
            }

        with patch("app.services.email_service.queue_email", return_value="qid-002"), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=fail_send):
            r = _queue(client, proposal_id)

        assert r.status_code == 502, r.text
        body = r.json()["detail"]
        assert body["error"]       == "smtp_send_failed"
        assert body["reason"]      == "smtp_auth_failed"
        assert body["retryable"]   is True
        assert body["email_id"]    == "qid-002"

        a = _read_audit(ap)
        assert a["proactive_dispatch_failed_at"]
        assert a["proactive_dispatch_failure_reason"] == "smtp_auth_failed"
        assert a["proactive_dispatch_send_error"]["reason"]       == "smtp_auth_failed"
        assert a["proactive_dispatch_send_error"]["error_detail"] == "535 authentication failed"

        # Proposal must be retryable: status remains 'queued' with email_id
        prop = a["action_proposals"][0]
        assert prop["status"]   == "queued"
        assert prop["email_id"] == "qid-002"

        events = [e["event"] for e in a["timeline"]]
        assert "dhl_proactive_dispatch_send_failed" in events

    def test_retry_after_smtp_failure_does_not_duplicate_queue_record(
        self, tmp_path, client,
    ):
        """After SMTP failure, calling /queue again must NOT call queue_email
        a second time. It only retries send_queued_email."""
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        queue_calls: List[Dict[str, Any]] = []
        def fake_queue(**kwargs):
            queue_calls.append(kwargs)
            return f"qid-{len(queue_calls):03d}"

        # First attempt: queue ok, send fails
        def fail_send(queue_id, method="smtp", **kw):
            return {"ok": False, "queue_id": queue_id, "status": "pending",
                    "error": "smtp_send_failed", "error_detail": "connection refused"}

        with patch("app.services.email_service.queue_email", side_effect=fake_queue), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=fail_send):
            r = _queue(client, proposal_id)
            assert r.status_code == 502

        # Second attempt: send succeeds; queue_email must NOT be called again
        def ok_send(queue_id, method="smtp", **kw):
            return {"ok": True, "queue_id": queue_id, "status": "sent",
                    "provider_message_id": "<msg-2@zoho>",
                    "sent_at": "2026-05-07T21:00:00+00:00"}

        with patch("app.services.email_service.queue_email", side_effect=fake_queue), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=ok_send):
            r2 = _queue(client, proposal_id)

        assert r2.status_code == 200, r2.text
        assert r2.json()["status"]    == "sent"
        assert r2.json()["delivered"] is True
        # Critical: queue_email was called exactly once across both attempts
        assert len(queue_calls) == 1, (
            f"queue_email called {len(queue_calls)} times — retry duplicated queue record"
        )

    def test_already_sent_proposal_short_circuits_idempotently(
        self, tmp_path, client,
    ):
        """Re-calling /queue on a proposal already marked sent returns the
        prior delivery state without calling queue_email or SMTP."""
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        def ok_send(queue_id, method="smtp", **kw):
            return {"ok": True, "queue_id": queue_id, "status": "sent",
                    "provider_message_id": "<msg-3@zoho>",
                    "sent_at": "2026-05-07T21:10:00+00:00"}

        with patch("app.services.email_service.queue_email", return_value="qid-A"), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=ok_send):
            r1q = _queue(client, proposal_id)
            assert r1q.json()["status"] == "sent"

        # Second call must short-circuit. queue_email and send_queued_email
        # MUST NOT be invoked.
        q_called = {"n": 0}
        s_called = {"n": 0}
        def trip_q(**kw):  q_called["n"] += 1; return "should-not-be-called"
        def trip_s(*a, **kw): s_called["n"] += 1; return {"ok": True, "status": "sent"}

        with patch("app.services.email_service.queue_email", side_effect=trip_q), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=trip_s):
            r2 = _queue(client, proposal_id)

        assert r2.status_code == 200
        body = r2.json()
        assert body["status"]       == "sent"
        assert body["already_sent"] is True
        assert body["delivered"]    is True
        assert body["provider_message_id"] == "<msg-3@zoho>"
        assert q_called["n"] == 0
        assert s_called["n"] == 0

    def test_smtp_not_configured_keeps_legacy_queued_response(
        self, tmp_path, client,
    ):
        """When SMTP is not configured (dev), the endpoint preserves the
        legacy 'queued' response — does NOT call send, does NOT 502."""
        bid, _, ap = _make_batch(tmp_path)
        r1 = _post_proactive(client, bid, "alice")
        proposal_id = r1.json()["proposal_id"]
        _approve(client, proposal_id, "bob")

        s_called = {"n": 0}
        def trip_s(*a, **kw): s_called["n"] += 1; return {"ok": True, "status": "sent"}

        with patch("app.services.email_service.queue_email", return_value="qid-D"), \
             patch("app.services.email_sender._smtp_configured", return_value=False), \
             patch("app.services.email_sender.send_queued_email", side_effect=trip_s):
            r = _queue(client, proposal_id)

        assert r.status_code == 200
        assert r.json()["status"] == "queued"
        assert "delivered" not in r.json() or r.json().get("delivered") in (None, False)
        assert s_called["n"] == 0

    def test_non_proactive_queue_does_not_call_send(self, tmp_path, client):
        """Non-proactive proposal types must keep their existing behavior:
        /queue returns 'queued' and does NOT call send_queued_email."""
        bid, _, ap = _make_batch(tmp_path)
        a = _read_audit(ap)
        proposal_id = str(uuid.uuid4())
        a["action_proposals"] = [{
            "proposal_id":  proposal_id,
            "type":         "dhl_followup",
            "batch_id":     bid,
            "status":       "approved",
            "approved_by":  "bob",
            "approved_at":  "2026-05-07T10:00:00Z",
            "reason":       "test",
            "confidence":   "high",
            "draft": {
                "to":          "odprawacelna@dhl.com",
                "cc":          "",
                "subject":     "Test followup",
                "body_text":   "...",
                "body_html":   "<pre>...</pre>",
                "attachments": [],
            },
            "created_at":  "2026-05-07T09:59:00Z",
            "created_by":  "alice",
            "rejected_by": None, "rejected_at": None, "reject_reason": None,
            "email_id":    None, "queued_at":   None,
        }]
        ap.write_text(json.dumps(a), encoding="utf-8")

        s_called = {"n": 0}
        def trip_s(*a_, **kw): s_called["n"] += 1; return {"ok": True, "status": "sent"}

        with patch("app.services.email_service.queue_email", return_value="qid-NF"), \
             patch("app.services.email_sender._smtp_configured", return_value=True), \
             patch("app.services.email_sender.send_queued_email", side_effect=trip_s):
            r = _queue(client, proposal_id)

        assert r.status_code == 200, r.text
        assert r.json()["status"] == "queued"
        # send_queued_email is NOT called for non-proactive types from /queue
        assert s_called["n"] == 0


# ──────────────────────────────────────────────────────────────────────────
# 13. Body formatting & correction mode
# ──────────────────────────────────────────────────────────────────────────

class TestBodyFormatting:

    def test_body_polish_first_then_english(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        body = pkg["body_text"]
        pl_idx = body.find("Szanowni Państwo")
        en_idx = body.find("Dear DHL Customs Team")
        assert pl_idx >= 0 and en_idx >= 0, body
        assert pl_idx < en_idx, "Polish must precede English"

    def test_body_uses_numbered_attachment_list(self, tmp_path, dhl_env):
        """Numbered list, not leading-space bullets that wrap badly on phones."""
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        body = pkg["body_text"]
        for line in ("1. Faktury handlowe", "2. List przewozowy AWB",
                     "3. Opis towarów w języku polskim"):
            assert line in body, f"missing: {line}\n---\n{body}"
        for line in ("1. Commercial invoices", "2. AWB document",
                     "3. Polish goods description"):
            assert line in body, f"missing: {line}\n---\n{body}"
        # Old indented-bullet style must be gone
        assert "  - Faktura(y) handlowa(e)" not in body
        assert "  - Commercial invoice(s)" not in body

    def test_body_has_no_wide_table_markup(self, tmp_path, dhl_env):
        """HTML must not embed <table>/<tr>/<td> — those break on mobile.
        plain <pre> wrapper is mobile-safe."""
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        html = pkg["body_html"].lower()
        for tag in ("<table", "<tr", "<td", "<th", "width=", "colspan"):
            assert tag not in html, f"forbidden HTML markup '{tag}' in body_html"

    def test_body_no_total_attachments_count_line(self, tmp_path, dhl_env):
        """Old 'Total attachments: N' line is gone — count is implicit
        from the actual MIME parts."""
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert "Total attachments:" not in pkg["body_text"]
        assert "Total attachments:" not in pkg["body_html"]

    def test_correction_mode_inserts_correction_paragraph(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid, correction=True)
        body = pkg["body_text"]
        assert "korektą" in body.lower(), body
        assert "correction of an earlier message" in body, body

    def test_normal_mode_omits_correction_paragraph(self, tmp_path, dhl_env):
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)   # correction defaults to False
        body = pkg["body_text"]
        assert "korekt" not in body.lower(), body
        assert "correction" not in body.lower(), body

    def test_body_text_and_html_match_in_meaning(self, tmp_path, dhl_env):
        """The HTML must be a faithful rendering of body_text — same words,
        same order — so recipients on plain-text and HTML clients see the
        same message."""
        bid, _, _ = _make_batch(tmp_path)
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        # body_text is embedded verbatim inside the <pre> wrapper
        assert pkg["body_text"] in pkg["body_html"]


class TestSubjectThreading:

    def test_dhl_ticket_takes_precedence_over_dhl_email_ticket(
        self, tmp_path, dhl_env,
    ):
        """When both audit.dhl_ticket and audit.dhl_email.ticket are set,
        the top-level field wins."""
        bid, _, _ = _make_batch(tmp_path, extra={
            "dhl_ticket": "T#TOPLEVEL",
            "dhl_email":  {"ticket": "T#NESTED"},
        })
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert "T#TOPLEVEL" in pkg["subject"]
        assert "T#NESTED" not in pkg["subject"]

    def test_empty_ticket_strings_treated_as_absent(self, tmp_path, dhl_env):
        """An empty string for a ticket field must NOT trigger the 'Re:'
        thread-mode subject."""
        bid, _, _ = _make_batch(tmp_path, extra={
            "dhl_ticket": "",
            "dhl_email":  {"ticket": ""},
        })
        from app.services.dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
        a = _read_audit(tmp_path / "outputs" / bid / "audit.json")
        pkg = build_dhl_proactive_dispatch(a, bid)
        assert pkg["subject"] == f"AWB {a['awb']} — Dokumenty celne / Customs documents"
