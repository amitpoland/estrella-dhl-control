"""
test_dhl_followup_auto_sender.py — 7-gate contract for autonomous
DHL follow-up sending.

One test per gate failure mode + one happy-path + AI fallback + idempotency.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.services import dhl_followup_auto_sender as svc


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_latch():
    svc._LATCH_HELD.clear()
    yield
    svc._LATCH_HELD.clear()


@pytest.fixture
def _enable_flag(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_auto_followup_enabled", True, raising=False)
    monkeypatch.setattr(settings, "dhl_auto_followup_max_ingest_age_minutes", 30, raising=False)
    monkeypatch.setattr(settings, "dhl_auto_followup_use_ai_draft", False, raising=False)
    return settings


@pytest.fixture
def _audit_dir(tmp_path):
    d = tmp_path / "outputs" / "BATCH123"
    d.mkdir(parents=True)
    return d


def _make_audit(audit_dir: Path, **overrides) -> tuple[Path, dict]:
    """Return (audit_path, audit_dict) for an active, gates-ready batch.

    Overrides patch individual fields to test gate failures.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    fresh_scan = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    # SLA due: next_followup_at in the past
    next_due = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    audit = {
        "batch_id":         "BATCH123",
        "awb":              "4789974092",
        "tracking_no":      "4789974092",
        "clearance_status": "awaiting_dhl_customs_email",
        "tracking":         {"status": "in_transit"},
        "dhl_email":        {},  # no DHL email yet
        "agency_preclearance": {},
        "customs_docs":     {},
        "dhl_followup": {
            "active":           True,
            "trigger_time":     now_iso,
            "trigger_reason":   "poland_customs_stage_detected",
            "first_followup_at": next_due,
            "next_followup_at": next_due,
            "followup_count":   0,
            "last_followup_at": None,
            "stopped_at":       None,
            "stop_reason":      None,
        },
        "email_ingestion":  {"last_scan_at": fresh_scan},
        "clearance_decision": {"total_value_usd": 1234.56},
    }
    audit.update(overrides)
    audit_path = audit_dir / "audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return audit_path, audit


# ── Gate 0: master flag ──────────────────────────────────────────────────────

def test_gate_flag_disabled_blocks(_audit_dir, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_auto_followup_enabled", False, raising=False)
    audit_path, audit = _make_audit(_audit_dir)
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "flag_enabled"


# ── Gate 1: active shipment ──────────────────────────────────────────────────

def test_gate_terminal_shipment_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir,
        clearance_status="agency_email_sent",
        tracking={"status": "delivered"},
        agency_reply_package={"send_verified": True},
    )
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "active_shipment"


# ── Gate 2: SLA elapsed ──────────────────────────────────────────────────────

def test_gate_sla_not_yet_due_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir)
    # Move next_followup_at into the future
    audit["dhl_followup"]["next_followup_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=2)
    ).isoformat()
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "sla_elapsed"


# ── Gate 3: fresh email ingest ───────────────────────────────────────────────

def test_gate_stale_ingest_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir,
        email_ingestion={"last_scan_at":
            (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()},
    )
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "fresh_email_ingest"


def test_gate_missing_ingest_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir, email_ingestion={})
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "fresh_email_ingest"


# ── Gate 4: no DHL/agency email evidence ─────────────────────────────────────

def test_gate_dhl_email_already_received_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir,
        dhl_email={"received": True, "ticket": "T123"},
    )
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "no_dhl_or_agency_email"


def test_gate_agency_preclearance_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir,
        agency_preclearance={"sent_at": "2026-05-20T10:00:00Z"},
    )
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "no_dhl_or_agency_email"


# ── Gate 5: safe recipient ───────────────────────────────────────────────────

def test_gate_unsafe_recipient_blocks(_audit_dir, _enable_flag, monkeypatch):
    # Patch DHL_TO at the svc module's import site to an unsafe address
    monkeypatch.setattr(svc, "_SAFE_TO_ADDRESSES", frozenset(), raising=False)
    monkeypatch.setattr(svc, "_SAFE_TO_DOMAINS", frozenset(), raising=False)
    audit_path, audit = _make_audit(_audit_dir)
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "safe_recipient"


# ── Gate 6: package buildable (AWB) ──────────────────────────────────────────

def test_gate_missing_awb_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir, awb="", tracking_no="")
    audit.pop("batch_meta", None)
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "package_buildable"


# ── Gate 7: idempotency ──────────────────────────────────────────────────────

def test_gate_idempotency_inflight_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir)
    svc._LATCH_HELD.add(svc._idempotency_key("BATCH123", 1))
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "idempotency_clear"


def test_gate_idempotency_already_sent_in_timeline_blocks(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir)
    # Pre-seed audit.timeline with a sent event for seq=1
    audit["timeline"] = [
        {"event": "dhl_followup_auto_sent",
         "detail": {"followup_seq": 1}}
    ]
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "blocked"
    assert v["first_failed"] == "idempotency_clear"


# ── Happy path: all 7 gates pass, evaluate_gates returns ready ──────────────

def test_all_gates_pass_returns_ready(_audit_dir, _enable_flag):
    audit_path, audit = _make_audit(_audit_dir)
    v = svc.evaluate_gates(audit_path, audit)
    assert v["decision"] == "ready", v
    assert v["first_failed"] is None
    # Every gate present
    names = [g["name"] for g in v["gates"]]
    for required in ("flag_enabled", "active_shipment", "sla_elapsed",
                     "fresh_email_ingest", "no_dhl_or_agency_email",
                     "safe_recipient", "package_buildable", "idempotency_clear"):
        assert required in names


# ── try_auto_send happy path: drafts + sends + writes audit + timeline ───────

def test_try_auto_send_happy_path(_audit_dir, _enable_flag, monkeypatch):
    audit_path, audit = _make_audit(_audit_dir)
    sent = {}

    def fake_queue_email(**kw):
        sent.update(kw)
        return "queue-id-77"

    monkeypatch.setattr("app.services.email_service.queue_email", fake_queue_email)

    result = svc.try_auto_send(audit_path, audit, operator="test")
    assert result["decision"] == "sent", result
    assert result["queue_id"] == "queue-id-77"
    assert result["idempotency_key"].startswith("dhl_followup_auto::BATCH123::seq1")
    assert result["draft_source"] in ("deterministic", "deterministic_disabled", "deterministic_fallback")
    # queue_email called with DHL recipient + non-empty body
    assert sent["to"]
    assert "AWB 4789974092" in sent["subject"]
    assert sent["batch_id"] == "BATCH123"
    # Timeline event written inside audit.json
    audit_after = json.loads(audit_path.read_text())
    sent_events = [e for e in audit_after.get("timeline", [])
                   if e.get("event") == "dhl_followup_auto_sent"]
    assert len(sent_events) == 1
    assert sent_events[0]["detail"]["followup_seq"] == 1
    assert sent_events[0]["detail"]["queue_id"] == "queue-id-77"
    # followup_count incremented
    assert audit_after["dhl_followup"]["followup_count"] == 1
    assert audit_after["dhl_followup"]["last_followup_at"]


# ── Suppression writes a timeline event so it is audit-visible ───────────────

def test_suppressed_send_writes_timeline_event(_audit_dir, _enable_flag, monkeypatch):
    audit_path, audit = _make_audit(_audit_dir,
        dhl_email={"received": True, "ticket": "T999"},
    )
    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: pytest.fail("queue_email must NOT be called on suppression"),
    )
    result = svc.try_auto_send(audit_path, audit, operator="test")
    assert result["decision"] == "suppressed"
    assert result["reason"] == "no_dhl_or_agency_email"
    audit_after = json.loads(audit_path.read_text())
    sup_events = [e for e in audit_after.get("timeline", [])
                  if e.get("event") == "dhl_followup_auto_suppressed"]
    assert len(sup_events) == 1
    assert sup_events[0]["detail"]["first_failed"] == "no_dhl_or_agency_email"


# ── force_sla skips ONLY the SLA gate, never the others ──────────────────────

def test_force_sla_skips_only_sla(_audit_dir, _enable_flag, monkeypatch):
    audit_path, audit = _make_audit(_audit_dir)
    # SLA not yet due
    audit["dhl_followup"]["next_followup_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=2)
    ).isoformat()
    # But also dhl_email already received → should STILL block on evidence gate
    audit["dhl_email"] = {"received": True, "ticket": "T1"}
    audit_path.write_text(json.dumps(audit), encoding="utf-8")

    monkeypatch.setattr(
        "app.services.email_service.queue_email",
        lambda **kw: pytest.fail("queue_email must NOT be called"),
    )
    result = svc.try_auto_send(audit_path, audit, operator="test", force_sla=True)
    assert result["decision"] == "suppressed"
    # force_sla did not bypass the evidence gate
    assert result["reason"] == "no_dhl_or_agency_email"


def test_force_sla_sends_when_only_sla_was_blocking(_audit_dir, _enable_flag, monkeypatch):
    audit_path, audit = _make_audit(_audit_dir)
    audit["dhl_followup"]["next_followup_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=2)
    ).isoformat()
    audit_path.write_text(json.dumps(audit), encoding="utf-8")

    monkeypatch.setattr(
        "app.services.email_service.queue_email", lambda **kw: "qid-force",
    )
    result = svc.try_auto_send(audit_path, audit, operator="test", force_sla=True)
    assert result["decision"] == "sent"


# ── AI unavailable / returns None → deterministic fallback ───────────────────

def test_ai_unavailable_falls_back_to_deterministic(_audit_dir, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_auto_followup_use_ai_draft", True, raising=False)
    monkeypatch.setattr(settings, "dhl_auto_followup_enabled", True, raising=False)

    monkeypatch.setattr("app.services.ai_gateway.call", lambda **kw: None)

    audit_path, audit = _make_audit(_audit_dir)
    pkg = svc.draft_followup(audit, "BATCH123", use_ai=True)
    assert pkg["draft_source"] == "deterministic_fallback"
    assert "AWB 4789974092" in pkg["body_text"]


def test_ai_strips_anchor_falls_back_to_deterministic(_audit_dir, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_auto_followup_use_ai_draft", True, raising=False)
    monkeypatch.setattr(settings, "dhl_auto_followup_enabled", True, raising=False)

    # AI returns a body MISSING the AWB anchor → must fall back
    monkeypatch.setattr(
        "app.services.ai_gateway.call",
        lambda **kw: "Polished but the AWB number is missing.",
    )
    audit_path, audit = _make_audit(_audit_dir)
    pkg = svc.draft_followup(audit, "BATCH123", use_ai=True)
    assert pkg["draft_source"] == "deterministic_fallback"
    assert "AWB 4789974092" in pkg["body_text"]


def test_ai_preserves_anchors_uses_ai_draft(_audit_dir, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_auto_followup_use_ai_draft", True, raising=False)
    monkeypatch.setattr(settings, "dhl_auto_followup_enabled", True, raising=False)

    polished = (
        "Dear DHL Poland team,\n\n"
        "Polished follow-up for AWB 4789974092 — value 1,234.56 USD still pending. "
        "Please send DSK/customs documents immediately.\n"
    )
    monkeypatch.setattr("app.services.ai_gateway.call", lambda **kw: polished)
    audit_path, audit = _make_audit(_audit_dir)
    pkg = svc.draft_followup(audit, "BATCH123", use_ai=True)
    assert pkg["draft_source"] == "ai"
    assert "AWB 4789974092" in pkg["body_text"]
    assert "1,234.56" in pkg["body_text"]


# ── Phase-3 non-goals (regression guards) ────────────────────────────────────

def test_agency_auto_send_not_imported_here():
    """This module must NEVER reference the agency reply builders."""
    src = Path(svc.__file__).read_text(encoding="utf-8")
    forbidden = (
        "agency_email_builder",
        "agency_forward_after_dhl_builder",
        "send_agency",
        "AGENCY_TO",
    )
    for tok in forbidden:
        assert tok not in src, f"Forbidden reference to {tok!r}"


def test_no_wfirma_or_pz_writes():
    src = Path(svc.__file__).read_text(encoding="utf-8")
    for tok in ("wfirma_client", "pz_create", "create_invoice", "create_proforma",
                "create_pz", "inventory_state_engine"):
        assert tok not in src, f"Forbidden regulatory write reference: {tok!r}"


def test_no_dhl_substantive_reply_send():
    src = Path(svc.__file__).read_text(encoding="utf-8")
    # The auto-sender is for FOLLOW-UPs (chase), never substantive customs replies
    for tok in ("dhl_reply_builder", "build_dhl_reply"):
        assert tok not in src, f"Auto-sender must not send substantive DHL replies: {tok!r}"


# ── Endpoint contract: preview + run wired and reuse the engine ──────────────

def test_endpoints_added_to_followup_router():
    from app.api import routes_dhl_followup as r
    paths = {route.path for route in r.router.routes}
    assert "/api/v1/dhl-followup/{batch_id}/auto/preview" in paths
    assert "/api/v1/dhl-followup/{batch_id}/auto/run" in paths


def test_endpoint_preview_is_get_and_run_is_post():
    from app.api import routes_dhl_followup as r
    by_path = {}
    for route in r.router.routes:
        by_path.setdefault(route.path, set()).update(getattr(route, "methods", set()) or set())
    assert "GET" in by_path["/api/v1/dhl-followup/{batch_id}/auto/preview"]
    assert "POST" in by_path["/api/v1/dhl-followup/{batch_id}/auto/run"]
