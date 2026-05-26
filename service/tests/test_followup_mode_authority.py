"""
test_followup_mode_authority.py — Single-authority follow-up mode contract.

Locks the operator directive (2026-05-26):
  - Exactly ONE engine: dhl_followup_guard.validate_followup_send_preconditions
  - Exactly ONE global emergency switch: DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP
  - Exactly ONE shipment-level decision: audit.followup.mode ∈ {manual, automatic}
  - Default mode: manual
  - Monitor + Inbox preview read the SAME guard — no duplicate gating

Required tests (10 scenarios from the operator brief):
  1. Manual mode blocks monitor send
  2. Automatic mode allows monitor send
  3. Global flag OFF blocks all auto-send
  4. Global flag ON respects shipment mode
  5. Inbox mode toggle persists correctly
  6. Duplicate send impossible (idempotency key reuse blocked)
  7. DHL response disables automation (active-shipment / evidence)
  8. Agency response disables automation
  9. Terminal shipment disables automation
 10. Preview uses same engine as monitor (single guard authority)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.services.dhl_followup_guard import (
    validate_followup_send_preconditions,
    record_idempotency_key_into_audit,
)
from app.services.dhl_followup_mode import (
    get_mode, set_mode, is_automatic, is_mode_explicit, DEFAULT_MODE,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _fresh_iso(offset_min: int = -5) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_min)).isoformat()


def _base_audit(batch_id: str = "B_MODE", awb: str = "4789974092") -> dict:
    """Audit dict where every NON-mode-or-flag gate passes by default."""
    return {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "clearance_status": "import_documents_requested",
        "clearance_decision": {"clearance_path": "agency_clearance",
                                "agency_email":   "piotr@acspedycja.pl"},
        "tracking":    {"status": "in_transit"},
        "tracking_events": [{"normalized_stage": "ARRIVED_DESTINATION_COUNTRY"}],
        "customs_workflow_eligible": True,
        "customs_docs":    {"received": False},
        "dhl_email":       {"received": False},
        "agency_preclearance": {},
        "email_ingestion": {"last_scan_at": _fresh_iso(-5)},
        "dhl_followup": {
            "active":            True,
            "trigger_reason":    "customs_trigger",
            "trigger_time":      _fresh_iso(-300),
            "first_followup_at": _fresh_iso(-10),
            "next_followup_at":  _fresh_iso(-1),
            "followup_count":    1,
            "last_followup_at":  None,
            "stopped_at":        None,
            "stop_reason":       None,
            "sent_idempotency_keys": [],
        },
        "followup": {"mode": "automatic"},
    }


def _pkg(awb: str = "4789974092") -> dict:
    return {
        "to":        "odprawacelna@dhl.com",
        "to_list":   ["odprawacelna@dhl.com"],
        "cc":        "import@estrellajewels.eu",
        "cc_list":   ["import@estrellajewels.eu"],
        "subject":   f"URGENT follow-up #2 – DSK – AWB {awb}",
        "body_text": f"Please send DSK / customs docs for AWB {awb}.",
        "body_html": f"<p>Please send DSK for AWB {awb}.</p>",
        "attachments": [],
    }


# ── 1. Manual mode blocks monitor send ──────────────────────────────────────

def test_manual_mode_blocks_monitor_send():
    audit = _base_audit()
    audit["followup"] = {"mode": "manual"}
    res = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res.ok is False
    assert res.reason == "manual_mode"


# ── 2. Automatic mode allows monitor send ───────────────────────────────────

def test_automatic_mode_allows_monitor_send():
    audit = _base_audit()           # default fixture: mode=automatic
    res = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res.ok is True, res.reason
    assert res.idempotency_key
    assert res.primary_to == "odprawacelna@dhl.com"


# ── 3. Global flag OFF blocks all auto-send (kill-all) ──────────────────────

def test_global_flag_off_blocks_even_when_mode_automatic():
    audit = _base_audit()           # mode=automatic
    res = validate_followup_send_preconditions(audit, _pkg(), flag_override=False)
    assert res.ok is False
    assert res.reason == "auto_send_dhl_followup_flag_off"


# ── 4. Global flag ON respects shipment mode (mode is the per-shipment opt-in) ─

def test_global_flag_on_respects_per_shipment_mode():
    pkg = _pkg()
    # mode=manual + flag ON  → still blocked (manual mode wins)
    a_manual = _base_audit()
    a_manual["followup"] = {"mode": "manual"}
    r1 = validate_followup_send_preconditions(a_manual, pkg, flag_override=True)
    assert r1.ok is False and r1.reason == "manual_mode"

    # mode=automatic + flag ON → permitted
    a_auto = _base_audit()
    r2 = validate_followup_send_preconditions(a_auto, pkg, flag_override=True)
    assert r2.ok is True


# ── 5. Inbox mode toggle persists correctly ─────────────────────────────────

def test_inbox_mode_toggle_persists(tmp_path):
    audit = _base_audit()
    audit["followup"] = {"mode": "manual"}
    p = tmp_path / "outputs" / "B_MODE" / "audit.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(audit), encoding="utf-8")

    # Operator enables auto via the inbox
    result = set_mode(p, audit, "automatic", operator="amit@inbox")
    assert result["changed"] is True
    assert result["previous"] == "manual"

    # Re-read from disk: persistence verified
    disk = json.loads(p.read_text(encoding="utf-8"))
    assert disk["followup"]["mode"] == "automatic"
    # Timeline event written (audit-trail requirement)
    events = [e.get("event") for e in disk.get("timeline", [])]
    assert "dhl_followup_mode_changed" in events

    # Operator disables — idempotent down + back up
    result2 = set_mode(p, audit, "manual", operator="amit@inbox")
    assert result2["changed"] is True
    disk2 = json.loads(p.read_text(encoding="utf-8"))
    assert disk2["followup"]["mode"] == "manual"

    # Setting same mode again is a no-op
    result3 = set_mode(p, audit, "manual", operator="amit@inbox")
    assert result3["changed"] is False


def test_invalid_mode_raises():
    audit = _base_audit()
    with pytest.raises(ValueError):
        set_mode(Path("/tmp/x.json"), audit, "auto", operator="x")
    with pytest.raises(ValueError):
        set_mode(Path("/tmp/x.json"), audit, "off", operator="x")


def test_default_mode_is_manual_when_unset():
    a = _base_audit()
    a.pop("followup", None)
    assert get_mode(a) == "manual"
    assert is_automatic(a) is False
    assert DEFAULT_MODE == "manual"


# ── is_mode_explicit — distinguish operator-set from default-fallback ────────

def test_is_mode_explicit_true_when_authority_set_to_manual():
    a = _base_audit()
    a["followup"] = {"mode": "manual"}
    assert is_mode_explicit(a) is True


def test_is_mode_explicit_true_when_authority_set_to_automatic():
    a = _base_audit()  # fixture default sets mode="automatic"
    assert is_mode_explicit(a) is True


def test_is_mode_explicit_false_when_followup_block_missing():
    a = _base_audit()
    a.pop("followup", None)
    assert is_mode_explicit(a) is False
    # And get_mode still returns the safe default
    assert get_mode(a) == "manual"


def test_is_mode_explicit_false_when_mode_field_missing():
    a = _base_audit()
    a["followup"] = {}  # block present, but mode field absent
    assert is_mode_explicit(a) is False


def test_is_mode_explicit_false_when_mode_invalid():
    a = _base_audit()
    a["followup"] = {"mode": "garbage"}
    assert is_mode_explicit(a) is False
    # get_mode falls back to default
    assert get_mode(a) == "manual"


# ── 6. Duplicate send impossible (idempotency key reuse blocked) ────────────

def test_duplicate_idempotency_key_blocked():
    audit = _base_audit()
    # Pre-record the key that would be generated for this slot
    next_at = audit["dhl_followup"]["next_followup_at"]
    audit["dhl_followup"]["sent_idempotency_keys"] = [
        f"{audit['batch_id']}|dhl_followup|{next_at}",
    ]
    res = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res.ok is False
    assert res.reason == "duplicate_idempotency_key"


def test_record_idempotency_helper_prevents_replay():
    audit = _base_audit()
    res1 = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res1.ok and res1.idempotency_key
    # Caller records the key after a successful send
    record_idempotency_key_into_audit(audit, res1.idempotency_key)
    # Same audit, same slot → blocked on replay
    res2 = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res2.ok is False
    assert res2.reason == "duplicate_idempotency_key"


# ── 7. DHL response disables automation ─────────────────────────────────────

def test_dhl_response_disables_automation():
    """When DHL replies, the upstream monitor stop-branch deactivates the
    SLA (stop_followup with STOP_DHL_EMAIL_RECEIVED). Once dhl_followup.
    active is False, is_due() returns False so the guard is never reached
    for an auto-send. This test pins that contract end-to-end:
    dhl_email.received → stop_followup → state.active=False → no send."""
    from app.services.dhl_followup_sla import (
        stop_followup, STOP_DHL_EMAIL_RECEIVED, is_due,
    )
    audit = _base_audit()
    audit["dhl_email"] = {"received": True, "ticket": "T-DHL"}
    # Simulate the monitor's upstream stop branch
    stop_followup(audit, STOP_DHL_EMAIL_RECEIVED)
    assert audit["dhl_followup"]["active"] is False
    assert audit["dhl_followup"]["stop_reason"] == STOP_DHL_EMAIL_RECEIVED
    # is_due is the gate that even precedes the guard call
    assert is_due(audit["dhl_followup"]) is False


# ── 8. Agency response disables automation ──────────────────────────────────

def test_agency_response_disables_automation():
    audit = _base_audit()
    audit["clearance_status"] = "agency_email_sent"
    audit["agency_preclearance"] = {"sent_at": _fresh_iso(-30)}
    res = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res.ok is False
    assert res.reason != "manual_mode"
    assert "not_active" in res.reason or "agency" in res.reason


# ── 9. Terminal shipment disables automation ────────────────────────────────

def test_terminal_shipment_disables_automation():
    audit = _base_audit()
    audit["tracking"] = {"status": "delivered"}
    audit["clearance_status"] = "delivered"
    res = validate_followup_send_preconditions(audit, _pkg(), flag_override=True)
    assert res.ok is False
    assert "not_active" in res.reason


# ── 10. Preview uses the SAME engine as monitor (single guard authority) ────

def test_preview_endpoint_uses_canonical_guard():
    """The /auto/preview endpoint must call dhl_followup_guard — proving
    Inbox preview and monitor sweep share one decision authority."""
    import inspect
    from app.api import routes_dhl_followup as r
    src = inspect.getsource(r.auto_preview_endpoint)
    assert "validate_followup_send_preconditions" in src, \
        "Preview endpoint MUST call the canonical guard"
    # The deleted PR #372 engine must NOT be imported
    assert "dhl_followup_auto_sender" not in src
    assert "try_auto_send" not in src
    assert "evaluate_gates" not in src


def test_only_one_followup_engine_module_remains():
    """The PR #372 dhl_followup_auto_sender module must be gone.
    Single-authority means a single engine on disk."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    engine_file = repo_root / "app" / "services" / "dhl_followup_auto_sender.py"
    assert not engine_file.exists(), \
        f"Redundant engine still on disk: {engine_file}"


def test_only_one_global_flag_governs_followup():
    """Exactly one env flag should govern auto-send: dhl_orch_auto_send_dhl_followup.
    The PR #372 dhl_auto_followup_* flags must be removed from settings."""
    from app.core.config import settings
    # Canonical flag exists
    assert hasattr(settings, "dhl_orch_auto_send_dhl_followup")
    # Redundant flags from PR #372 are gone
    for ghost in (
        "dhl_auto_followup_enabled",
        "dhl_auto_followup_max_ingest_age_minutes",
        "dhl_auto_followup_use_ai_draft",
    ):
        assert not hasattr(settings, ghost), \
            f"Redundant flag still present: {ghost}"


# ── Endpoint contract ────────────────────────────────────────────────────────

def test_mode_endpoints_registered():
    from app.api import routes_dhl_followup as r
    by_path = {}
    for route in r.router.routes:
        by_path.setdefault(route.path, set()).update(
            getattr(route, "methods", set()) or set()
        )
    assert "GET" in by_path.get("/api/v1/dhl-followup/{batch_id}/mode", set())
    assert "POST" in by_path.get("/api/v1/dhl-followup/{batch_id}/mode", set())
    # The deleted POST /auto/run is gone
    assert "/api/v1/dhl-followup/{batch_id}/auto/run" not in by_path


def test_preview_endpoint_still_available_as_read_only_get():
    from app.api import routes_dhl_followup as r
    by_path = {}
    for route in r.router.routes:
        by_path.setdefault(route.path, set()).update(
            getattr(route, "methods", set()) or set()
        )
    methods = by_path.get("/api/v1/dhl-followup/{batch_id}/auto/preview", set())
    assert "GET" in methods
    # NOT POST — preview is read-only
    assert "POST" not in methods
