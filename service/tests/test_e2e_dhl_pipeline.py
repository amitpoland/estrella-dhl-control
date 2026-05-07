"""
test_e2e_dhl_pipeline.py — Full customs-trigger → SLA-start → SAD-stop pipeline.

Covers the complete state-machine sequence in one accumulated audit:
  1. Seed batch: AWB + CUSTOMS_PENDING normalized event + customs tracking event
  2. Sweep 1:  customs trigger detected → stage gate passes → SLA armed
  3. Make SLA due → Sweep 2: follow-up dispatch exercised (email queue mocked)
  4. SAD uploaded: customs_docs.received = True
  5. Sweep 3: SLA stopped (stop_reason = "customs_docs_received")
  6. Milestone skip at all three surfaces:
       execute_action("dhl_send_reply")       → skipped / customs_docs_received
       run_actions("build_and_send_dhl_reply") → skipped / milestone_skip
       POST /send-now                          → 409 / customs_docs_received
  7. Protected financial fields unchanged throughout.

No production logic changes; no real network calls.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_POLAND_TZ = ZoneInfo("Europe/Warsaw")

# ── Network stubs ─────────────────────────────────────────────────────────────

_INGEST_STUB = {
    "ok": True,
    "started_at": "2026-01-01T00:00:00Z",
    "active_batches": 0,
    "shipments": [],
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Block all real Zoho / SMTP network calls in every test in this file."""
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda **kw: _INGEST_STUB,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _normalized_event(stage: str, hours_ago: float = 1.0) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "normalized_stage": stage,
        "event_time":       ts,
        "raw_description":  stage.lower().replace("_", " "),
        "source":           "dhl_api",
    }


def _raw_event(location: str, description: str, hours_ago: float = 1.0) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"timestamp": ts, "location": location, "status": "", "description": description}


def _seed_batch(tmp_path: Path, batch_id: str, awb: str = "9876543210") -> Path:
    batch_dir = tmp_path / "outputs" / batch_id
    inv_dir   = batch_dir / "source" / "invoices"
    awb_dir   = batch_dir / "source" / "awb"
    for d in (inv_dir, awb_dir):
        d.mkdir(parents=True, exist_ok=True)
    (inv_dir / "INV.pdf").write_bytes(b"%PDF inv")
    awb_pdf = awb_dir / f"{awb} AWB.pdf"
    awb_pdf.write_bytes(b"%PDF awb")

    audit = {
        "batch_id":           batch_id,
        "awb":                awb,
        "tracking_no":        awb,
        "inputs":             {"awb": awb_pdf.name},
        "clearance_status":   "awaiting_dhl_customs_email",
        "clearance_decision": {
            "total_value_usd":  8500.00,
            "clearance_path":   "agency_clearance",
        },
        "invoice_totals":     {"total_cif_usd": 8500.00},
        # normalized events — enables stage-rank gate (Rule 2)
        "tracking_events": [
            _normalized_event("IN_TRANSIT", hours_ago=6),
            _normalized_event("ARRIVED_DESTINATION_COUNTRY", hours_ago=3),
            _normalized_event("CUSTOMS_PENDING", hours_ago=1),
        ],
        # raw events — enables trigger detection
        "tracking": {
            "events": [
                _raw_event("WARSAW - PL", "Customs clearance status updated", hours_ago=1),
            ],
        },
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_dir


# ── The test ──────────────────────────────────────────────────────────────────

def test_full_pipeline_customs_trigger_through_sad_stop(tmp_path, monkeypatch):
    """
    Full DHL customs pipeline state-machine in one accumulated audit.

    Sequence:
      Sweep 1  → customs trigger detected, stage gate passes, SLA armed
      Sweep 2  → SLA is due, follow-up queued (email mocked), counter advances
      SAD      → customs_docs.received set
      Sweep 3  → SLA stopped (customs_docs_received)
      Checks   → execute_action / run_actions / send-now all blocked
      Checks   → financial fields unchanged throughout
    """
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab

    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))

    AWB      = "9876543210"
    BATCH_ID = "E2E_DHL_PIPE"

    batch_dir  = _seed_batch(tmp_path, BATCH_ID, awb=AWB)
    audit_path = batch_dir / "audit.json"

    # ── Sweep 1: trigger detected, gate passes, SLA armed ────────────────────
    out1 = m.scan_active_shipments()
    a1   = next(a for a in out1["actions"] if a["batch_id"] == BATCH_ID)

    assert a1.get("triggers"), "Sweep 1: expected at least one trigger"
    assert any(
        t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED"
        for t in a1["triggers"]
    ), "Sweep 1: DHL_CUSTOMS_EMAIL_CHECK_REQUIRED trigger not emitted"

    audit1 = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit1["dhl_followup"]["active"] is True,       "Sweep 1: SLA did not start"
    assert audit1["dhl_followup"]["followup_count"] == 0,  "Sweep 1: unexpected count"
    assert audit1["dhl_followup"]["first_followup_at"],    "Sweep 1: first_followup_at missing"

    # Financial fields must be unchanged after sweep 1
    assert audit1["invoice_totals"]["total_cif_usd"] == 8500.00
    assert audit1["clearance_decision"]["total_value_usd"] == 8500.00

    # ── Sweep 2: make SLA due, mock email queue + send ────────────────────────
    audit1["dhl_followup"]["next_followup_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()
    audit_path.write_text(json.dumps(audit1), encoding="utf-8")

    fake_email_pkg = {
        "to":           "odprawacelna@dhl.com",
        "subject":      "Follow-up: AWB 9876543210",
        "body_html":    "<p>follow-up</p>",
        "body_text":    "follow-up",
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_followup",
        "attachments":  [],
    }
    fake_send_outcome = {
        "ok":                  True,
        "status":              "sent",
        "provider_message_id": "smtp-msg-e2e-001",
    }

    with (
        patch("app.services.dhl_followup_email_builder.build_dhl_followup_email",
              return_value=fake_email_pkg),
        patch("app.services.email_service.queue_email",
              return_value="email-id-e2e-001"),
        patch("app.services.email_sender._smtp_configured", return_value=True),
        patch("app.services.email_sender.send_queued_email",
              return_value=fake_send_outcome),
    ):
        out2 = m.scan_active_shipments()

    a2 = next(a for a in out2["actions"] if a["batch_id"] == BATCH_ID)
    assert a2.get("dhl_followup", {}).get("sent") is True, \
        "Sweep 2: follow-up was not dispatched"

    audit2 = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit2["dhl_followup"]["active"] is True,      "Sweep 2: SLA should still be active"
    assert audit2["dhl_followup"]["followup_count"] == 1, "Sweep 2: followup_count not incremented"
    assert audit2["dhl_followup"]["last_followup_at"],    "Sweep 2: last_followup_at missing"

    # Financial fields still unchanged
    assert audit2["invoice_totals"]["total_cif_usd"] == 8500.00
    assert audit2["clearance_decision"]["total_value_usd"] == 8500.00

    # ── SAD upload: customs docs received ────────────────────────────────────
    audit2["customs_docs"] = {
        "received":    True,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    audit_path.write_text(json.dumps(audit2), encoding="utf-8")

    # ── Sweep 3: SLA stopped on customs_docs_received ────────────────────────
    out3 = m.scan_active_shipments()
    a3   = next(a for a in out3["actions"] if a["batch_id"] == BATCH_ID)
    assert a3.get("dhl_followup", {}).get("stopped") is True, \
        "Sweep 3: SLA not stopped after SAD upload"

    audit3 = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit3["dhl_followup"]["active"] is False,                       "Sweep 3: SLA still active"
    assert audit3["dhl_followup"]["stop_reason"] == "customs_docs_received", "Sweep 3: wrong stop_reason"
    assert audit3["dhl_followup"]["stopped_at"],                            "Sweep 3: stopped_at missing"

    # Financial fields still unchanged
    assert audit3["invoice_totals"]["total_cif_usd"] == 8500.00
    assert audit3["clearance_decision"]["total_value_usd"] == 8500.00

    # Patch settings.storage_root for the remainder of the test via monkeypatch
    # so it stays in effect through teardown (unlike patch.object context managers
    # which restore the live path before the conftest guard runs).
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    # ── Milestone skip: execution_engine.execute_action ──────────────────────
    from app.services.execution_engine import execute_action

    _batch_ready  = {"overall": {"ready_for_closure": True,
                                 "blocked_domains": [], "next_step": None}}
    _dhl_ready    = {"dhl_status": "dhl_contacted"}
    _wfirma_ready = {"ready_to_create": True}

    with (
        patch("app.services.batch_readiness.get_batch_readiness",        return_value=_batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness",            return_value=_dhl_ready),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=_wfirma_ready),
    ):
        exec_result = execute_action("dhl_send_reply", BATCH_ID)

    assert exec_result["ok"]     is True,                     "execute_action: expected ok=True on skip"
    assert exec_result["status"] == "skipped",                "execute_action: expected status=skipped"
    assert exec_result["reason"] == "customs_docs_received",  "execute_action: wrong skip reason"
    assert exec_result.get("stage") == "milestone_skip",      "execute_action: stage not milestone_skip"

    # ── Milestone skip: cowork_action_runner.run_actions ─────────────────────
    from app.services.cowork_action_runner import run_actions

    runner_result = run_actions(
        BATCH_ID,
        [{"action": "build_and_send_dhl_reply", "task_id": "e2e-task-001",
          "reason": "e2e test"}],
    )

    assert runner_result["ok"] is True, "run_actions: expected ok=True"
    assert len(runner_result["failed"]) == 0, "run_actions: unexpected failures"
    skip_reasons = [s.get("reason", "") for s in runner_result["skipped"]]
    assert any("milestone_skip" in r for r in skip_reasons), \
        f"run_actions: expected milestone_skip in {skip_reasons}"
    assert any("customs_docs_received" in r for r in skip_reasons), \
        f"run_actions: expected customs_docs_received in {skip_reasons}"

    # ── Milestone skip: POST /api/v1/dhl-followup/{batch_id}/send-now → 409 ──
    # Re-arm dhl_followup.active so the endpoint's "not active" guard does not
    # fire first — we want the customs_docs guard to be the one that fires.
    audit3["dhl_followup"]["active"] = True
    audit_path.write_text(json.dumps(audit3), encoding="utf-8")

    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post(
        f"/api/v1/dhl-followup/{BATCH_ID}/send-now",
        json={"approved_by": "test_operator"},
    )

    assert r.status_code == 409, \
        f"send-now: expected 409, got {r.status_code} — body: {r.text}"
    body = r.json()
    assert (body.get("detail") or {}).get("guard") == "customs_docs_received", \
        f"send-now: expected guard=customs_docs_received in detail, got: {body}"

    # ── Final financial invariant ─────────────────────────────────────────────
    audit_final = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_final["invoice_totals"]["total_cif_usd"] == 8500.00,       "Final: invoice_totals mutated"
    assert audit_final["clearance_decision"]["total_value_usd"] == 8500.00, "Final: clearance_decision mutated"
