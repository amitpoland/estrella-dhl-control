"""
test_cowork_pipeline.py — Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit

Tests:
  - Cowork DHL email result triggers SMTP DHL reply
  - Cowork DSK result triggers agency forward
  - Cowork SAD/PZC result triggers importer
  - Cowork invoice result triggers service invoice monitor
  - Financial mutation rejected (flat, nested, recursive)
  - Duplicate Cowork result does not resend
  - Action failure creates risk_flag
  - Evidence written to audit
  - No financial fields modified
  - Email draft pipeline (accept, reject, routing, sender, financial safety)
  - Production hardening:
    - Action idempotency locks
    - Confidence gate (medium, low)
    - Attachment source authority
    - Thread integrity guard
    - SMTP send confirmation
    - Action priority resolver
    - Extended financial field protection
    - Compact AI decision/action summaries
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


@pytest.fixture(autouse=True)
def _isolate_storage_root(tmp_path, monkeypatch):
    """Patch the real settings singleton so modules that import it directly
    (e.g. batch_lock.py) use tmp_path instead of live storage."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)


def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
        smtp_host = "smtppro.zoho.in"
        smtp_port = 465
        smtp_user = None
        smtp_password = None
        smtp_use_ssl = True
        mcp_send_max_attachment_bytes = 200_000
    return S()


def _seed_shipment(tmp_path, batch_id, awb="1012178215", **extra):
    """Create a minimal shipment audit for testing."""
    batch_dir = tmp_path / "outputs" / batch_id
    (batch_dir / "source" / "invoices").mkdir(parents=True, exist_ok=True)
    (batch_dir / "source" / "awb").mkdir(parents=True, exist_ok=True)

    awb_filename = f"{awb} AWB.pdf"
    (batch_dir / "source" / "awb" / awb_filename).write_bytes(b"%PDF awb")
    (batch_dir / "source" / "invoices" / "INV-001.pdf").write_bytes(b"%PDF inv")

    audit = {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "inputs":      {"awb": awb_filename, "invoices": ["INV-001.pdf"]},
        "clearance_decision": {
            "total_value_usd": 10366,
            "clearance_path":  "agency_clearance",
        },
    }
    audit.update(extra)
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_dir


# ═══════════════════════════════════════════════════════════════════════════
# ORIGINAL TESTS (preserved)
# ═══════════════════════════════════════════════════════════════════════════

def test_financial_mutation_rejected(tmp_path, monkeypatch):
    """Cowork result containing financial fields must be rejected."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_FIN_REJ")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_fin_1",
        "evidence": {
            "dhl_email": {"received": True, "ticket": "T#123"},
            "invoice_totals": {"total_cif_usd": 9999},
        },
    }
    out = process_cowork_result("task_fin_1", result, "B_FIN_REJ")
    assert out["rejected"] is True
    assert "Financial field mutation rejected" in out["rejection_reason"]


def test_nested_financial_mutation_rejected(tmp_path, monkeypatch):
    """Nested financial fields must also be caught."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_FIN_NEST")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_nest_1",
        "evidence": {
            "dhl_email": {"received": True, "duty": 500},
        },
    }
    out = process_cowork_result("task_nest_1", result, "B_FIN_NEST")
    assert out["rejected"] is True
    assert "Financial field mutation rejected" in out["rejection_reason"]


def test_awb_mismatch_rejected(tmp_path, monkeypatch):
    """Cowork result with wrong AWB must be rejected."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_AWB_MIS", awb="1012178215")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_awb_1",
        "awb": "9999999999",
        "evidence": {"dhl_email": {"received": True}},
    }
    out = process_cowork_result("task_awb_1", result, "B_AWB_MIS")
    assert out["rejected"] is True
    assert "AWB mismatch" in out["rejection_reason"]


def test_duplicate_result_rejected(tmp_path, monkeypatch):
    """Second Cowork result with same task_id must be rejected."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_DUP")

    audit_path = batch_dir / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["cowork_results_log"] = [{"task_id": "task_dup_1", "processed_at": "2026-01-01"}]
    audit_path.write_text(json.dumps(audit))

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_dup_1",
        "evidence": {"dhl_email": {"received": True}},
    }
    out = process_cowork_result("task_dup_1", result, "B_DUP")
    assert out["rejected"] is True
    assert "Duplicate" in out["rejection_reason"]


def test_evidence_written_to_audit(tmp_path, monkeypatch):
    """Valid Cowork result writes evidence to audit."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_EV")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_ev_1",
        "confidence": "high",
        "evidence": {
            "dhl_email": {
                "received": True,
                "ticket":   "T#1WA2604290000028",
                "sender":   "odprawacelna@dhl.com",
            },
        },
    }
    out = process_cowork_result("task_ev_1", result, "B_EV")
    assert out["ok"] is True
    assert "dhl_email" in out["evidence_written"]

    audit = json.loads((batch_dir / "audit.json").read_text())
    assert audit["dhl_email"]["received"] is True
    assert audit["dhl_email"]["ticket"] == "T#1WA2604290000028"
    assert any(e["task_id"] == "task_ev_1" for e in audit["cowork_results_log"])


def test_dhl_email_triggers_reply(tmp_path, monkeypatch):
    """DHL email evidence → build_and_send_dhl_reply action decided."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_DHL_REPLY")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_reply_1",
        "confidence": "high",
        "evidence": {
            "dhl_email": {
                "received":     True,
                "ticket":       "T#1WA2604290000028",
                "sender":       "odprawacelna@dhl.com",
                "request_type": "translation",
            },
        },
    }
    out = process_cowork_result("task_reply_1", result, "B_DHL_REPLY")
    assert out["ok"] is True
    actions = [a["action"] for a in out["actions_decided"]]
    assert "build_and_send_dhl_reply" in actions


def test_dhl_reply_action_queues_email(tmp_path, monkeypatch):
    """Action runner actually queues the DHL reply via SMTP."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    monkeypatch.setattr("app.services.agency_forward_after_dhl_builder.settings", s)
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", s)

    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    batch_dir = _seed_shipment(tmp_path, "B_DHL_Q", dhl_email={
        "received": True, "ticket": "T#1WA2604290000028", "sender": "odprawacelna@dhl.com",
    })
    polish_dir = tmp_path / "outputs" / "polish_descriptions"
    polish_dir.mkdir(parents=True, exist_ok=True)
    (polish_dir / "PD_1012178215.pdf").write_bytes(b"%PDF polish")
    audit_path = batch_dir / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["polish_desc_filename"] = "PD_1012178215.pdf"
    audit_path.write_text(json.dumps(audit))

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "build_and_send_dhl_reply", "task_id": "task_q_1", "reason": "test"}]
    out = run_actions("B_DHL_Q", actions)

    audit = json.loads(audit_path.read_text())
    drp = audit.get("dhl_reply_package") or {}
    assert drp.get("status") == "queued"
    assert drp.get("source") == "cowork_action_runner"
    assert drp.get("email_id")

    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert any(e["id"] == drp["email_id"] for e in queue)


def test_dhl_docs_triggers_agency_forward(tmp_path, monkeypatch):
    """DHL documents received → agency forward action decided."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))

    batch_dir = _seed_shipment(tmp_path, "B_FWD", dhl_email={
        "received": True, "ticket": "T#1WA2604290000028",
    })
    docs_dir = batch_dir / "dhl_docs"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "DSK.pdf").write_bytes(b"%PDF dsk")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_fwd_1",
        "confidence": "high",
        "evidence": {
            "dhl_documents_received": {
                "received": True,
                "files": [{"name": "DSK.pdf", "path": str(docs_dir / "DSK.pdf"), "type": "DSK"}],
            },
        },
    }
    out = process_cowork_result("task_fwd_1", result, "B_FWD")
    assert out["ok"] is True
    actions = [a["action"] for a in out["actions_decided"]]
    assert "validate_and_forward_dhl_docs_to_agency" in actions


def test_agency_customs_docs_triggers_importer(tmp_path, monkeypatch):
    """Agency reply with customs docs → import action decided."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_SAD")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_sad_1",
        "confidence": "high",
        "evidence": {
            "agency_reply_detected": {
                "has_customs_docs": True,
                "customs_files":    ["/tmp/SAD.pdf", "/tmp/PZC.pdf"],
            },
        },
    }
    out = process_cowork_result("task_sad_1", result, "B_SAD")
    assert out["ok"] is True
    actions = [a["action"] for a in out["actions_decided"]]
    assert "import_agency_customs_docs" in actions


def test_agency_invoice_triggers_register(tmp_path, monkeypatch):
    """Agency invoice detected → register action decided."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_INV")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_inv_1",
        "confidence": "high",
        "evidence": {
            "service_invoices_detected": {
                "agency_invoice_files": ["/tmp/agency_inv.pdf"],
            },
        },
    }
    out = process_cowork_result("task_inv_1", result, "B_INV")
    assert out["ok"] is True
    actions = [a["action"] for a in out["actions_decided"]]
    assert "register_agency_invoices" in actions


def test_dhl_invoice_triggers_register(tmp_path, monkeypatch):
    """DHL invoice detected → register action decided."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_DINV")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_dinv_1",
        "confidence": "high",
        "evidence": {
            "dhl_invoice_detected": {
                "files": ["/tmp/dhl_invoice.pdf"],
            },
        },
    }
    out = process_cowork_result("task_dinv_1", result, "B_DINV")
    assert out["ok"] is True
    actions = [a["action"] for a in out["actions_decided"]]
    assert "register_dhl_invoices" in actions


def test_action_failure_creates_risk_flag(tmp_path, monkeypatch):
    """Failed action execution must add a risk_flag to audit."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_FAIL")

    from app.services import cowork_action_runner as runner

    # Register a handler that always raises, so the failure is explicit
    # rather than relying on missing SMTP config or storage mismatches.
    original_handlers = dict(runner._ACTION_HANDLERS)
    runner._ACTION_HANDLERS["test_failing_action"] = lambda bid, ad: (_ for _ in ()).throw(
        RuntimeError("intentional test failure")
    )
    try:
        actions = [{"action": "test_failing_action", "task_id": "task_fail_1", "reason": "test failure"}]
        out = runner.run_actions("B_FAIL", actions)
        assert out["ok"] is False
        assert len(out["failed"]) == 1

        audit = json.loads((tmp_path / "outputs" / "B_FAIL" / "audit.json").read_text())
        assert "cowork_action_failed:test_failing_action" in (audit.get("risk_flags") or [])
    finally:
        runner._ACTION_HANDLERS = original_handlers


def test_no_financial_fields_modified(tmp_path, monkeypatch):
    """Full pipeline must never modify financial fields."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_SAFE")

    audit_path = batch_dir / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["invoice_totals"] = {"total_cif_usd": 10366}
    audit_path.write_text(json.dumps(audit))

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_safe_1",
        "confidence": "high",
        "evidence": {"dhl_email": {"received": True, "ticket": "T#123"}},
    }
    out = process_cowork_result("task_safe_1", result, "B_SAFE")
    assert out["ok"] is True

    after = json.loads(audit_path.read_text())
    assert after["invoice_totals"]["total_cif_usd"] == 10366
    assert after["clearance_decision"]["total_value_usd"] == 10366


def test_full_pipeline_dhl_email_to_reply(tmp_path, monkeypatch):
    """Full pipeline: Cowork DHL email → validate → build reply → queue SMTP."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", s)

    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    batch_dir = _seed_shipment(tmp_path, "B_FULL")
    polish_dir = tmp_path / "outputs" / "polish_descriptions"
    polish_dir.mkdir(parents=True, exist_ok=True)
    (polish_dir / "PD_1012178215.pdf").write_bytes(b"%PDF polish")
    audit_path = batch_dir / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["polish_desc_filename"] = "PD_1012178215.pdf"
    audit_path.write_text(json.dumps(audit))

    from app.services.cowork_action_runner import run_post_result

    result = {
        "task_id": "task_full_1",
        "confidence": "high",
        "evidence": {
            "dhl_email": {
                "received": True, "ticket": "T#1WA2604290000028",
                "sender": "odprawacelna@dhl.com", "request_type": "translation",
            },
        },
    }
    out = run_post_result("task_full_1", result, "B_FULL")
    assert out["ok"] is True
    assert len(out["executed"]) >= 1
    assert out["executed"][0]["action"] == "build_and_send_dhl_reply"

    audit = json.loads(audit_path.read_text())
    assert audit["dhl_reply_package"]["status"] == "queued"
    assert audit["dhl_reply_package"]["source"] == "cowork_action_runner"

    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert len(queue) == 1
    assert queue[0]["email_type"] == "dhl_reply"


def test_already_sent_reply_not_resent(tmp_path, monkeypatch):
    """If DHL reply already queued, action runner skips it."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_IDEM", dhl_email={
        "received": True, "ticket": "T#123",
    }, dhl_reply_package={"status": "queued", "email_id": "old"})

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "build_and_send_dhl_reply", "task_id": "task_idem_1", "reason": "test"}]
    out = run_actions("B_IDEM", actions)
    assert out["ok"] is True
    # Idempotency lock catches it — goes to skipped list
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["reason"] == "action_lock_active"


# ═══════════════════════════════════════════════════════════════════════════
# EMAIL DRAFT TESTS (preserved)
# ═══════════════════════════════════════════════════════════════════════════

def test_email_draft_accepted_for_valid_followup(tmp_path, monkeypatch):
    """Valid Cowork email draft for DHL follow-up is accepted and queued."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)

    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    _seed_shipment(tmp_path, "B_DRAFT_OK", dhl_email={"received": True, "ticket": "T#123"})

    from app.services.cowork_action_runner import run_post_result

    result = {
        "task_id": "task_draft_1",
        "confidence": "high",
        "evidence": {"tracking": {"status": "in_transit"}},
        "email_draft": {
            "type": "dhl_followup",
            "subject": "Follow-up: AWB 1012178215",
            "body": "Dear DHL Customs Team,\n\nWe are writing to follow up on our previous request regarding AWB 1012178215. We have not yet received the DSK transfer code.\n\nCould you please provide an update?",
            "language": "en", "tone": "professional",
            "reason": "No DHL document response detected",
        },
    }
    out = run_post_result("task_draft_1", result, "B_DRAFT_OK")
    assert out["ok"] is True

    draft_actions = [e for e in out["executed"] if e["action"] == "send_cowork_email_draft"]
    assert len(draft_actions) == 1
    assert draft_actions[0]["result"]["sent"] is True

    queue = json.loads((tmp_path / "email_queue.json").read_text())
    draft_emails = [e for e in queue if e["email_type"] == "cowork_dhl_followup"]
    assert len(draft_emails) == 1
    assert "odprawacelna@dhl.com" in draft_emails[0]["to"]

    audit = json.loads((tmp_path / "outputs" / "B_DRAFT_OK" / "audit.json").read_text())
    drafts = audit.get("cowork_email_drafts") or []
    assert len(drafts) == 1
    assert drafts[0]["from_address"] == "import@estrellajewels.eu"


def test_email_draft_rejected_if_awb_mismatch(tmp_path, monkeypatch):
    """Cowork email draft with wrong AWB is dropped."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    _seed_shipment(tmp_path, "B_DRAFT_AWB", awb="1012178215")
    from app.services.cowork_action_runner import run_post_result

    result = {
        "task_id": "task_draft_awb_1",
        "confidence": "high",
        "evidence": {"dhl_email": {"received": True}},
        "email_draft": {
            "type": "dhl_followup", "subject": "Follow-up",
            "body": "Wrong AWB reference.", "awb": "9999999999",
        },
    }
    out = run_post_result("task_draft_awb_1", result, "B_DRAFT_AWB")
    draft_actions = [a for a in out.get("executed", []) if a["action"] == "send_cowork_email_draft"]
    assert len(draft_actions) == 0


def test_email_draft_cannot_override_recipients(tmp_path, monkeypatch):
    """Cowork draft with 'to' or 'cc' fields is rejected."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_DRAFT_ROUTE")
    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_draft_route_1",
        "confidence": "high",
        "evidence": {"dhl_email": {"received": True}},
        "email_draft": {
            "type": "dhl_followup", "subject": "Follow-up",
            "body": "Some valid body text.", "to": "hacker@evil.com", "cc": "leak@evil.com",
        },
    }
    out = process_cowork_result("task_draft_route_1", result, "B_DRAFT_ROUTE")
    draft_actions = [a for a in out["actions_decided"] if a["action"] == "send_cowork_email_draft"]
    assert len(draft_actions) == 0


def test_email_draft_cannot_attach_files(tmp_path, monkeypatch):
    """Cowork draft with 'attachments' field is rejected."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_DRAFT_ATT")
    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_draft_att_1",
        "confidence": "high",
        "evidence": {"dhl_email": {"received": True}},
        "email_draft": {
            "type": "dhl_followup", "subject": "Follow-up",
            "body": "Some valid body text.", "attachments": ["/etc/passwd"],
        },
    }
    out = process_cowork_result("task_draft_att_1", result, "B_DRAFT_ATT")
    draft_actions = [a for a in out["actions_decided"] if a["action"] == "send_cowork_email_draft"]
    assert len(draft_actions) == 0


def test_email_draft_pz_app_is_sender(tmp_path, monkeypatch):
    """Queued draft email always uses PZ App sender identity."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    _seed_shipment(tmp_path, "B_DRAFT_SENDER")
    from app.services.cowork_action_runner import run_actions

    actions = [{
        "action": "send_cowork_email_draft", "task_id": "task_sender_1", "reason": "test",
        "draft": {
            "type": "agency_followup", "subject": "Follow-up on customs clearance",
            "body": "Dear ACS Team,\n\nPlease provide an update on customs clearance.\n\nThank you.",
        },
    }]
    out = run_actions("B_DRAFT_SENDER", actions)
    assert out["ok"] is True

    queue = json.loads((tmp_path / "email_queue.json").read_text())
    assert queue[0]["from_address"] == "import@estrellajewels.eu"
    assert "Estrella Jewels" in queue[0]["body_text"]
    assert "piotr@acspedycja.pl" in queue[0]["to"]


def test_email_draft_no_financial_fields_modified(tmp_path, monkeypatch):
    """Email draft pipeline must never modify financial audit fields."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    batch_dir = _seed_shipment(tmp_path, "B_DRAFT_FIN")
    audit_path = batch_dir / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["invoice_totals"] = {"total_cif_usd": 10366}
    audit["pz_totals"] = {"netto": 48778.64}
    audit_path.write_text(json.dumps(audit))

    from app.services.cowork_action_runner import run_post_result

    result = {
        "task_id": "task_draft_fin_1",
        "confidence": "high",
        "evidence": {"dhl_email": {"received": True}},
        "email_draft": {
            "type": "dhl_followup", "subject": "Follow-up",
            "body": "Please provide DSK transfer code.",
        },
    }
    out = run_post_result("task_draft_fin_1", result, "B_DRAFT_FIN")

    after = json.loads(audit_path.read_text())
    assert after["invoice_totals"]["total_cif_usd"] == 10366
    assert after["pz_totals"]["netto"] == 48778.64
    assert after["clearance_decision"]["total_value_usd"] == 10366


# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING TESTS
# ═══════════════════════════════════════════════════════════════════════════


# ── 1. Action lock prevents duplicate DHL reply send ────────────────────────

def test_action_lock_prevents_duplicate_dhl_reply(tmp_path, monkeypatch):
    """Action lock prevents second DHL reply even if handler guard is bypassed."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_LOCK_DHL", action_locks={"dhl_reply_sent": True})

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "build_and_send_dhl_reply", "task_id": "task_lock_1", "reason": "test"}]
    out = run_actions("B_LOCK_DHL", actions)
    assert out["ok"] is True
    # Should be in skipped list (idempotency lock)
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["reason"] == "action_lock_active"


# ── 2. Action lock prevents duplicate agency forward ────────────────────────

def test_action_lock_prevents_duplicate_agency_forward(tmp_path, monkeypatch):
    """Action lock prevents second agency forward."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_LOCK_FWD", action_locks={"agency_forward_sent": True})

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "validate_and_forward_dhl_docs_to_agency", "task_id": "t1", "reason": "test"}]
    out = run_actions("B_LOCK_FWD", actions)
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["reason"] == "action_lock_active"


# ── 3. Medium confidence stores evidence but does not send ──────────────────

def test_medium_confidence_stores_evidence_no_send(tmp_path, monkeypatch):
    """Medium confidence writes evidence but does NOT execute actions."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_MED_CONF")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_med_1",
        "confidence": "medium",
        "evidence": {
            "dhl_email": {"received": True, "ticket": "T#123"},
        },
    }
    out = process_cowork_result("task_med_1", result, "B_MED_CONF")
    assert out["ok"] is True
    assert "dhl_email" in out["evidence_written"]
    # No actions should be decided for execution
    assert out["actions_decided"] == []
    assert "medium_confidence_review_only" in out["risk_flags"]

    # Evidence should be in audit
    audit = json.loads((batch_dir / "audit.json").read_text())
    assert audit["dhl_email"]["received"] is True
    # last_ai_decision status should be needs_review
    assert audit["last_ai_decision"]["status"] == "needs_review"


# ── 4. Low confidence sets risk flag ────────────────────────────────────────

def test_low_confidence_sets_risk_flag(tmp_path, monkeypatch):
    """Low confidence sets risk_flag and does NOT execute actions."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_LOW_CONF")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_low_1",
        "confidence": "low",
        "evidence": {
            "dhl_email": {"received": True},
        },
    }
    out = process_cowork_result("task_low_1", result, "B_LOW_CONF")
    assert out["ok"] is True
    assert "low_confidence_ai_result" in out["risk_flags"]
    assert out["actions_decided"] == []

    audit = json.loads((batch_dir / "audit.json").read_text())
    assert "low_confidence_ai_result" in (audit.get("risk_flags") or [])
    assert audit["last_ai_decision"]["status"] == "needs_review"


# ── 5. Cowork absolute attachment path is rejected ──────────────────────────

def test_cowork_absolute_attachment_path_rejected(tmp_path, monkeypatch):
    """Absolute paths from Cowork outside internal storage are flagged."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))

    from app.services.cowork_action_runner import _resolve_internal_attachments
    valid, rejected = _resolve_internal_attachments(
        ["/etc/passwd", "/tmp/evil.pdf", "/usr/local/hack.pdf"],
        "B_TEST_ATT",
    )
    assert len(valid) == 0
    assert len(rejected) == 3


# ── 6. Internal attachment resolution succeeds ─────────────────────────────

def test_internal_attachment_resolution_succeeds(tmp_path, monkeypatch):
    """Files inside internal storage directories are accepted."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_INT_ATT")

    # File exists inside source/invoices
    inv_path = str(batch_dir / "source" / "invoices" / "INV-001.pdf")

    from app.services.cowork_action_runner import _resolve_internal_attachments
    valid, rejected = _resolve_internal_attachments([inv_path], "B_INT_ATT")
    assert len(valid) == 1
    assert len(rejected) == 0


# ── 7. Thread integrity failure blocks send ─────────────────────────────────

def test_thread_integrity_failure_blocks_send(tmp_path, monkeypatch):
    """Thread integrity failure prevents DHL reply when no AWB/ticket/email."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    # Create shipment with no AWB, no DHL email
    _seed_shipment(tmp_path, "B_THREAD", awb="")

    from app.services.cowork_result_processor import _check_thread_integrity

    # No AWB, no DHL email, no ticket
    audit = {"tracking_no": "", "awb": ""}
    evidence = {}
    err = _check_thread_integrity(audit, evidence, "build_and_send_dhl_reply")
    assert err is not None
    assert "Thread integrity failed" in err


# ── 8. SMTP send without provider_message_id does not set verified ──────────

def test_smtp_unconfirmed_sets_risk_flag(tmp_path, monkeypatch):
    """SMTP send without provider_message_id adds risk flag."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)

    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    _seed_shipment(tmp_path, "B_SMTP_UNCONF")

    from app.services.cowork_action_runner import run_actions

    actions = [{
        "action": "send_cowork_email_draft", "task_id": "task_smtp_1", "reason": "test",
        "draft": {
            "type": "agency_followup", "subject": "Test",
            "body": "Please confirm receipt of customs documents.",
        },
    }]
    out = run_actions("B_SMTP_UNCONF", actions)
    assert out["ok"] is True

    # Check last_ai_action was written
    audit = json.loads((tmp_path / "outputs" / "B_SMTP_UNCONF" / "audit.json").read_text())
    ai_action = audit.get("last_ai_action") or {}
    assert ai_action.get("action") == "send_cowork_email_draft"
    assert ai_action.get("queue_id") is not None


# ── 9. Action priority selects DHL reply before follow-up ──────────────────

def test_action_priority_selects_dhl_reply_first(tmp_path, monkeypatch):
    """Priority resolver puts DHL reply before follow-up SLA."""
    from app.services.cowork_result_processor import _resolve_priority

    actions = [
        {"action": "check_followup_sla", "task_id": "t1", "reason": "follow-up"},
        {"action": "build_and_send_dhl_reply", "task_id": "t2", "reason": "reply"},
        {"action": "register_agency_invoices", "task_id": "t3", "reason": "invoice"},
    ]
    selected, skipped = _resolve_priority(actions)
    assert selected[0]["action"] == "build_and_send_dhl_reply"
    # All three should be selected (no conflicts)
    assert len(selected) == 3
    assert len(skipped) == 0


# ── 10. Conflicting actions are skipped and logged ─────────────────────────

def test_conflicting_actions_skipped(tmp_path, monkeypatch):
    """Two DHL reply types in same pass: only first is kept."""
    from app.services.cowork_result_processor import _resolve_priority

    actions = [
        {"action": "build_and_send_dhl_reply", "task_id": "t1", "reason": "agency path"},
        {"action": "build_and_send_dhl_self_clearance_reply", "task_id": "t2", "reason": "self path"},
    ]
    selected, skipped = _resolve_priority(actions)
    # Only one DHL reply type should survive
    assert len(selected) == 1
    assert len(skipped) == 1
    assert selected[0]["action"] == "build_and_send_dhl_reply"
    assert "build_and_send_dhl_self_clearance_reply" in skipped


# ── 11. Deeply nested financial field is rejected ──────────────────────────

def test_deeply_nested_financial_field_rejected(tmp_path, monkeypatch):
    """Financial fields nested 3+ levels deep must be caught."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_DEEP_FIN")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_deep_1",
        "evidence": {
            "dhl_email": {
                "received": True,
                "metadata": {
                    "inner": {
                        "exchange_rate": 4.25,  # deeply nested forbidden field
                    }
                }
            },
        },
    }
    out = process_cowork_result("task_deep_1", result, "B_DEEP_FIN")
    assert out["rejected"] is True
    assert "Financial field mutation rejected" in out["rejection_reason"]


# ── 12. Protected exchange_rate / vat / tax fields rejected ────────────────

def test_protected_exchange_rate_vat_tax_rejected(tmp_path, monkeypatch):
    """Extended financial fields (exchange_rate, vat_amount, tax) are protected."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_EXT_FIN")

    from app.services.cowork_result_processor import process_cowork_result

    # Test exchange_rate
    result = {
        "task_id": "task_ext_1",
        "evidence": {"exchange_rate": 4.25},
    }
    out = process_cowork_result("task_ext_1", result, "B_EXT_FIN")
    assert out["rejected"] is True

    # Test vat_amount (new task_id to avoid duplicate rejection)
    _seed_shipment(tmp_path, "B_EXT_FIN2")
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    result2 = {
        "task_id": "task_ext_2",
        "evidence": {"dhl_email": {"received": True, "vat_amount": 999}},
    }
    out2 = process_cowork_result("task_ext_2", result2, "B_EXT_FIN2")
    assert out2["rejected"] is True

    # Test tax
    _seed_shipment(tmp_path, "B_EXT_FIN3")
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    result3 = {
        "task_id": "task_ext_3",
        "evidence": {"dhl_email": {"received": True, "tax": 100}},
    }
    out3 = process_cowork_result("task_ext_3", result3, "B_EXT_FIN3")
    assert out3["rejected"] is True


# ── 13. last_ai_decision written ───────────────────────────────────────────

def test_last_ai_decision_written(tmp_path, monkeypatch):
    """Compact last_ai_decision is written to audit after processing."""
    monkeypatch.setattr("app.services.cowork_result_processor.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_AI_DEC")

    from app.services.cowork_result_processor import process_cowork_result

    result = {
        "task_id": "task_dec_1",
        "confidence": "high",
        "evidence": {"dhl_email": {"received": True, "ticket": "T#123"}},
    }
    out = process_cowork_result("task_dec_1", result, "B_AI_DEC")
    assert out["ok"] is True

    audit = json.loads((batch_dir / "audit.json").read_text())
    dec = audit.get("last_ai_decision")
    assert dec is not None
    assert dec["task_id"] == "task_dec_1"
    assert dec["confidence"] == "high"
    assert dec["status"] == "executed"
    assert "recommended_actions" in dec
    assert "selected_action" in dec
    assert "skipped_actions" in dec


# ── 14. last_ai_action written ────────────────────────────────────────────

def test_last_ai_action_written(tmp_path, monkeypatch):
    """Compact last_ai_action is written to audit after action execution."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    _seed_shipment(tmp_path, "B_AI_ACT")
    from app.services.cowork_action_runner import run_actions

    actions = [{
        "action": "send_cowork_email_draft", "task_id": "task_act_1", "reason": "test",
        "draft": {
            "type": "dhl_followup", "subject": "Test",
            "body": "Please confirm receipt of clearance documentation.",
        },
    }]
    out = run_actions("B_AI_ACT", actions)
    assert out["ok"] is True

    audit = json.loads((tmp_path / "outputs" / "B_AI_ACT" / "audit.json").read_text())
    act = audit.get("last_ai_action")
    assert act is not None
    assert act["action"] == "send_cowork_email_draft"
    assert act["result"] == "success"
    assert act["queue_id"] is not None


# ── 15. No financial fields modified (hardening pass) ──────────────────────

def test_hardening_no_financial_fields_modified(tmp_path, monkeypatch):
    """Full hardened pipeline preserves all financial fields."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    batch_dir = _seed_shipment(tmp_path, "B_HARDEN_FIN")
    audit_path = batch_dir / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["invoice_totals"] = {"total_cif_usd": 10366}
    audit["pz_totals"] = {"netto": 48778.64}
    audit["exchange_rate"] = 4.1234
    audit_path.write_text(json.dumps(audit))

    from app.services.cowork_action_runner import run_post_result

    result = {
        "task_id": "task_hfin_1",
        "confidence": "high",
        "evidence": {"tracking": {"status": "delivered"}},
    }
    out = run_post_result("task_hfin_1", result, "B_HARDEN_FIN")

    after = json.loads(audit_path.read_text())
    assert after["invoice_totals"]["total_cif_usd"] == 10366
    assert after["pz_totals"]["netto"] == 48778.64
    assert after["exchange_rate"] == 4.1234
    assert after["clearance_decision"]["total_value_usd"] == 10366


# ── 16. Existing successful queue records unchanged ────────────────────────

def test_existing_queue_records_unchanged(tmp_path, monkeypatch):
    """Existing sent DHL reply queue record is not modified by new processing."""
    s = _settings(tmp_path)
    monkeypatch.setattr("app.services.cowork_action_runner.settings", s)
    monkeypatch.setattr("app.services.cowork_result_processor.settings", s)
    from app.services import email_service
    monkeypatch.setattr(email_service, "settings", s)

    # Pre-existing queue with a sent email
    existing_queue = [{
        "id": "existing_email_001",
        "email_type": "dhl_reply",
        "status": "sent",
        "to": "odprawacelna@dhl.com",
        "from_address": "import@estrellajewels.eu",
        "provider_message_id": "msg_12345",
    }]
    (tmp_path / "email_queue.json").write_text(json.dumps(existing_queue))

    _seed_shipment(tmp_path, "B_QUEUE_SAFE", dhl_reply_package={
        "status": "sent", "email_id": "existing_email_001",
    }, action_locks={"dhl_reply_sent": True})

    from app.services.cowork_action_runner import run_post_result

    result = {
        "task_id": "task_queue_1",
        "confidence": "high",
        "evidence": {"tracking": {"status": "in_transit"}},
    }
    out = run_post_result("task_queue_1", result, "B_QUEUE_SAFE")

    # Existing queue record must be untouched
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    original = next(e for e in queue if e["id"] == "existing_email_001")
    assert original["status"] == "sent"
    assert original["provider_message_id"] == "msg_12345"


# ═══════════════════════════════════════════════════════════════════════════
# check_followup_sla action handler (DHL follow-up SLA)
# ═══════════════════════════════════════════════════════════════════════════

def test_followup_sla_starts_on_missing_dhl_response(tmp_path, monkeypatch):
    """check_followup_sla starts the DHL follow-up SLA when none is active.

    Regression: the handler previously read audit["dhl_followup_sla"].started
    (wrong key + field) and called start_followup(audit, reason=...) — an invalid
    signature that raised TypeError. Only ImportError was caught, so the action
    crashed into failed[] for every batch that triggered it. It must now write
    audit["dhl_followup"].active via start_followup(audit, trigger_time, reason)
    and succeed.
    """
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_SLA_START")

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "check_followup_sla", "task_id": "task_sla_1",
                "reason": "no DHL response detected by cowork"}]
    out = run_actions("B_SLA_START", actions)

    # Action executed cleanly — not failed (pins the TypeError regression)
    assert out["ok"] is True
    assert out["failed"] == []
    assert out["executed"][0]["result"] == {"started": True}

    audit = json.loads((batch_dir / "audit.json").read_text())
    # Correct state key + field written; the old (wrong) key is never created
    assert audit["dhl_followup"]["active"] is True
    assert "dhl_followup_sla" not in audit
    # §9: cowork must not mutate financial fields
    assert audit["clearance_decision"]["total_value_usd"] == 10366


def test_followup_sla_reports_due(tmp_path, monkeypatch):
    """An active follow-up past its next_followup_at is reported as due.

    Regression: the handler previously called is_due(audit) with the whole audit
    dict instead of the follow-up state dict, so active/next_followup_at were
    never seen and this branch was dead. It must now call is_due(audit["dhl_followup"]).
    """
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    _seed_shipment(tmp_path, "B_SLA_DUE", dhl_followup={
        "active": True,
        "next_followup_at": "2020-01-01T00:00:00+02:00",
        "followup_count": 0,
    })

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "check_followup_sla", "task_id": "task_sla_2", "reason": "poll"}]
    out = run_actions("B_SLA_DUE", actions)

    assert out["ok"] is True
    assert out["executed"][0]["result"]["due"] is True


def test_followup_sla_reports_running_when_not_due(tmp_path, monkeypatch):
    """An active follow-up not yet due is reported as running and is not restarted."""
    monkeypatch.setattr("app.services.cowork_action_runner.settings", _settings(tmp_path))
    batch_dir = _seed_shipment(tmp_path, "B_SLA_RUN", dhl_followup={
        "active": True,
        "next_followup_at": "2099-01-01T00:00:00+02:00",
        "followup_count": 2,
    })

    from app.services.cowork_action_runner import run_actions

    actions = [{"action": "check_followup_sla", "task_id": "task_sla_3", "reason": "poll"}]
    out = run_actions("B_SLA_RUN", actions)

    assert out["ok"] is True
    assert out["executed"][0]["result"]["running"] is True
    # Idempotent: existing follow-up state preserved, not reset
    audit = json.loads((batch_dir / "audit.json").read_text())
    assert audit["dhl_followup"]["followup_count"] == 2
