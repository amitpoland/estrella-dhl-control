"""
test_path_a_auto_queue.py — Phase 2.3 Path A auto-queue at Departed origin.

Pins the twelve security guarantees from the pre-implementation security
review. The auto-queue is the first auto-send pattern in the codebase;
guarantees protect against double-fires, wrong recipients, value/path
inconsistency, mid-flight feature-flag flips, and customs-value mutation.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Fixtures ───────────────────────────────────────────────────────────────

def _settings_obj(tmp_path: Path, *, flag: bool = True):
    class S:
        storage_root = tmp_path
        enable_path_a_auto_queue = flag
        environment = "dev"
        dhl_customs_email = "odprawacelna@dhl.com"
        dhl_customs_cc = ("info@estrellajewels.eu, "
                          "import@estrellajewels.eu, "
                          "account@estrellajewels.eu")
    return S()


def _seed(tmp_path: Path, *, batch_id: str = "B_P23",
          awb: str = "1012178215",
          path: str = "dhl_self_clearance",
          cif: float = 1500.0,
          with_polish: bool = True,
          polish_size: int = 1024,
          with_invoice: bool = True,
          with_awb_pdf: bool = True,
          tracking_codes: list[str] | None = None,
          extras: dict | None = None) -> tuple[Path, dict]:
    batch_dir = tmp_path / "outputs" / batch_id
    inv_dir   = batch_dir / "source" / "invoices"
    awb_dir   = batch_dir / "source" / "awb"
    polish_dir = tmp_path / "polish_descriptions"
    for d in (inv_dir, awb_dir, polish_dir):
        d.mkdir(parents=True, exist_ok=True)

    polish_fn = "POLISH_DESC.pdf"
    if with_polish:
        body = (b"%PDF " + b"x" * polish_size) if polish_size > 0 else b""
        (polish_dir / polish_fn).write_bytes(body)
    if with_invoice:
        (inv_dir / "INV.pdf").write_bytes(b"%PDF inv")
    awb_fn = f"{awb} AWB.pdf"
    if with_awb_pdf:
        (awb_dir / awb_fn).write_bytes(b"%PDF awb")

    track_codes = tracking_codes if tracking_codes is not None else ["DEPARTED_ORIGIN_HUB"]
    audit = {
        "batch_id":     batch_id,
        "awb":          awb,
        "tracking_no":  awb,
        "doc_no":       "PZ_TEST",
        "polish_desc_filename": polish_fn if with_polish else "",
        "inputs":       {"awb": awb_fn if with_awb_pdf else ""},
        "clearance_decision": {"clearance_path": path, "total_value_usd": cif},
        "invoice_totals":     {"total_cif_usd": cif},
        "verification":       {"invoice_cif_total_usd": cif},
        "tracking_events":    [{"normalized_stage": code} for code in track_codes],
    }
    if extras:
        audit.update(extras)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit), encoding="utf-8")
    return ap, audit


def _patch_settings(monkeypatch, tmp_path, *, flag: bool = True):
    from app.services import active_shipment_monitor as asm
    from app.services import dhl_proactive_dispatch_builder as bld
    from app.core.config import settings as real_settings
    s = _settings_obj(tmp_path, flag=flag)
    # Patch every module-level `settings` binding the auto-queue path touches.
    monkeypatch.setattr(asm, "settings", s)
    monkeypatch.setattr(bld, "settings", s)
    monkeypatch.setattr(real_settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(real_settings, "enable_path_a_auto_queue", flag, raising=False)
    monkeypatch.setattr(real_settings, "dhl_customs_email", s.dhl_customs_email, raising=False)
    monkeypatch.setattr(real_settings, "dhl_customs_cc", s.dhl_customs_cc, raising=False)
    return s


def _stub_queue_email(succeed: bool = True, exc: Exception | None = None):
    if exc is not None:
        return patch("app.services.email_service.queue_email", side_effect=exc)
    if succeed:
        return patch("app.services.email_service.queue_email",
                     return_value="email-id-OK")
    return patch("app.services.email_service.queue_email", side_effect=RuntimeError("smtp_down"))


# ── Happy path ─────────────────────────────────────────────────────────────

def test_happy_path_fires_and_writes_all_decision_fields(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True):
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert result["queued"] is True, f"result={result}"
    assert result["triggered"] is True
    assert result["outcome"] == "fired"
    audit = json.loads(ap.read_text())
    assert audit["auto_queue_started_at"]
    assert audit["auto_queue_completed_at"]
    assert audit["auto_queue_decision_outcome"] == "fired"
    assert audit["auto_queue_flag_at_decision"] is True
    assert audit["auto_queue_resolved_to"] == "odprawacelna@dhl.com"
    assert "info@estrellajewels.eu" in audit["auto_queue_resolved_cc"]
    assert audit["auto_queue_actor"] == "system:path_a_auto_queue"
    assert audit["proactive_dispatch_sent_at"]
    assert audit["proactive_dispatch_email_id"] == "email-id-OK"


# ── GUARANTEE-7: feature flag off → skipped ────────────────────────────────

def test_flag_off_skips_no_queue_no_proposal(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=False)
    ap, _ = _seed(tmp_path)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert result["outcome"] == "skipped:flag_off"
    assert result["queued"] is False
    q.assert_not_called()
    audit = json.loads(ap.read_text())
    assert audit["auto_queue_decision_outcome"] == "skipped:flag_off"
    assert audit["auto_queue_flag_at_decision"] is False
    assert "auto_queue_started_at" not in audit
    assert "action_proposals" not in audit


# ── Legacy alias: carrier_self_clearance → treated as Path A ──────────────

def test_legacy_carrier_self_clearance_alias_recognized_as_path_a(tmp_path, monkeypatch):
    """Regression: audits created before the spec rename still carry
    clearance_decision.clearance_path = 'carrier_self_clearance' (the old
    value) and have no top-level audit['clearance_path']. The observer must
    normalize through clearance_path_alias and treat them as Path A.

    Audit shape: top-level clearance_path absent, clearance_decision uses
    the legacy value. Feature flag ON so the happy path runs.
    Expected: auto-queue fires (not skipped:not_path_a)."""
    _patch_settings(monkeypatch, tmp_path, flag=True)
    # Seed with the legacy alias — _seed normally passes "dhl_self_clearance".
    ap, _ = _seed(tmp_path, path="carrier_self_clearance", batch_id="B_LEGACY_ALIAS")
    # Remove top-level clearance_path if _seed ever writes it (currently it
    # does not — this assert documents the expected audit shape).
    a = json.loads(ap.read_text())
    assert a.get("clearance_path") is None, (
        "test fixture unexpectedly has top-level clearance_path set")
    assert a["clearance_decision"]["clearance_path"] == "carrier_self_clearance"
    ap.write_text(json.dumps(a), encoding="utf-8")

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert result["outcome"] != "skipped:not_path_a", (
        f"Legacy alias 'carrier_self_clearance' was not recognized as Path A; "
        f"got outcome={result['outcome']!r}")
    assert q.call_count == 1, "Expected exactly one queue_email call for legacy alias shape"


def test_legacy_carrier_self_clearance_alias_flag_off_records_decision(tmp_path, monkeypatch):
    """Regression guard for flag-off path with legacy alias.
    Observer must record 'skipped:flag_off', not 'skipped:not_path_a'."""
    _patch_settings(monkeypatch, tmp_path, flag=False)
    ap, _ = _seed(tmp_path, path="carrier_self_clearance", batch_id="B_LEGACY_FLAGOFF")
    a = json.loads(ap.read_text())
    assert a["clearance_decision"]["clearance_path"] == "carrier_self_clearance"

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert result["outcome"] == "skipped:flag_off", (
        f"Legacy alias should produce skipped:flag_off, got {result['outcome']!r}")
    q.assert_not_called()
    audit = json.loads(ap.read_text())
    assert audit.get("auto_queue_decision_outcome") == "skipped:flag_off"


# ── Path B → skipped ───────────────────────────────────────────────────────

def test_path_b_skipped_no_queue(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path, path="agency_clearance", cif=5000.0)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "skipped:not_path_a"
    q.assert_not_called()


# ── No Departed-origin event → skipped ─────────────────────────────────────

def test_no_departed_origin_skipped(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path, tracking_codes=["LABEL_CREATED", "PICKED_UP"])
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "skipped:no_departed_origin_event"
    q.assert_not_called()


# ── GUARANTEE-11: first-occurrence dedup; second pass → skipped ────────────

def test_second_pass_after_success_is_idempotent(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        first = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
        second = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert first["outcome"] == "fired"
    assert second["outcome"] == "skipped:already_fired"
    assert q.call_count == 1


# ── GUARANTEE-1 / GUARANTEE-4: parallel calls → exactly one queue ──────────

def test_parallel_calls_queue_exactly_once(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path, batch_id="B_PARA")
    from app.services import active_shipment_monitor as asm

    results = []
    with _stub_queue_email(succeed=True) as q:
        def runner():
            results.append(asm._ensure_path_a_auto_queue(
                ap, json.loads(ap.read_text())))
        threads = [threading.Thread(target=runner) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

    fired = [r for r in results if r["outcome"] == "fired"]
    skipped = [r for r in results if r["outcome"] == "skipped:already_fired"]
    assert len(fired) == 1
    assert len(skipped) == 3
    assert q.call_count == 1


# ── GUARANTEE-5 Check 5: value/path inconsistency ──────────────────────────

def test_value_path_inconsistency_blocks_with_alert(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    # path says A but value > threshold — corrupted classification
    ap, _ = _seed(tmp_path, path="dhl_self_clearance", cif=5000.0)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "validation_failed:value_path_inconsistency"
    q.assert_not_called()
    audit = json.loads(ap.read_text())
    proposals = audit.get("action_proposals") or []
    assert len(proposals) == 1
    assert proposals[0]["validation_failure_reason"] == \
        "validation_failed:value_path_inconsistency"
    assert proposals[0]["created_by"] == "system:path_a_auto_queue"


# ── GUARANTEE-5 individual checks ──────────────────────────────────────────

@pytest.mark.parametrize("seed_kwargs,expected", [
    ({"path": "routing_pending"},                        "skipped:not_path_a"),
    ({"awb": "BAD"},                                     "validation_failed:awb_format"),
    ({"cif": 0.5},                                       "validation_failed:invoice_value_below_floor"),
    ({"with_polish": False},                             "validation_failed:polish_desc_missing"),
    ({"polish_size": 0},                                 "validation_failed:polish_desc_missing"),
    ({"with_invoice": False},                            "validation_failed:invoice_files_missing"),
    ({"with_awb_pdf": False},                            "validation_failed:awb_pdf_missing"),
])
def test_validation_gate_failure_reasons(tmp_path, monkeypatch, seed_kwargs, expected):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path, **seed_kwargs)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == expected
    q.assert_not_called()


# ── GUARANTEE-12: already-shipped checks ───────────────────────────────────

@pytest.mark.parametrize("extras", [
    {"dhl_email": {"received": True}},
    {"dhl_documents_received": {"received": True, "files": []}},
])
def test_already_shipped_email_or_docs_blocks(tmp_path, monkeypatch, extras):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path, extras=extras)
    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "validation_failed:already_shipped"
    q.assert_not_called()


@pytest.mark.parametrize("track_code", [
    "ARRIVED_DESTINATION_COUNTRY", "CUSTOMS_PENDING", "CLEARED", "DELIVERED",
])
def test_already_shipped_tracking_codes_block(tmp_path, monkeypatch, track_code):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path, tracking_codes=["DEPARTED_ORIGIN_HUB", track_code])
    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "validation_failed:already_shipped"
    q.assert_not_called()


# ── GUARANTEE-6: recipient allowlist ───────────────────────────────────────

def test_recipient_not_allowlisted_blocks(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    # Override DHL_TO to a non-allowlisted address
    from app.config import email_routing as er
    monkeypatch.setattr(er, "DHL_TO", ["customs@dhl-test.example"])
    from app.core.config import settings as real_settings
    monkeypatch.setattr(real_settings, "dhl_customs_email", "", raising=False)

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "validation_failed:recipient_not_allowlisted"
    q.assert_not_called()


# ── GUARANTEE-6: empty recipient blocks ────────────────────────────────────

def test_empty_recipient_blocks(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    from app.config import email_routing as er
    monkeypatch.setattr(er, "DHL_TO", [])
    from app.core.config import settings as real_settings
    monkeypatch.setattr(real_settings, "dhl_customs_email", "", raising=False)

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "validation_failed:recipient_not_allowlisted"
    q.assert_not_called()


# ── GUARANTEE-8: builder missing → fallback proposal ───────────────────────

def test_builder_missing_creates_fallback_no_queue(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    from app.services import active_shipment_monitor as asm

    fake_pkg = {
        "to": "odprawacelna@dhl.com",
        "cc": "info@estrellajewels.eu",
        "subject": "AWB X",
        "body_text": "...",
        "body_html": "...",
        "attachments": [],
        "missing": ["polish description: not on disk"],
    }
    with patch("app.services.dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch",
               return_value=fake_pkg), _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert result["outcome"].startswith("builder_missing:")
    q.assert_not_called()
    audit = json.loads(ap.read_text())
    proposals = audit.get("action_proposals") or []
    assert len(proposals) == 1
    assert proposals[0]["validation_failure_reason"].startswith("builder_missing:")


# ── queue_email failure → auto_queue_failed status, no auto-retry ──────────

def test_queue_failure_marks_status_no_auto_retry(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(exc=RuntimeError("smtp_disconnect")):
        first = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert first["outcome"].startswith("queue_failed:")
    audit = json.loads(ap.read_text())
    assert audit["auto_queue_failed_at"]
    assert audit["proactive_dispatch_failed_at"]
    proposals = audit.get("action_proposals") or []
    assert proposals[-1]["status"] == "auto_queue_failed"

    # Re-run: must NOT re-queue (auto_queue_started_at marker present)
    with _stub_queue_email(succeed=True) as q2:
        second = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert second["outcome"] == "skipped:already_fired"
    q2.assert_not_called()


# ── GUARANTEE-10: customs-value-freeze ─────────────────────────────────────

def test_customs_value_freeze(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, audit_before = _seed(tmp_path)
    from app.services import active_shipment_monitor as asm

    snapshot = {
        "verification":       json.loads(json.dumps(audit_before["verification"])),
        "invoice_totals":     json.loads(json.dumps(audit_before["invoice_totals"])),
        "clearance_decision": json.loads(json.dumps(audit_before["clearance_decision"])),
    }

    with _stub_queue_email(succeed=True):
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "fired"

    audit_after = json.loads(ap.read_text())
    assert audit_after["verification"]       == snapshot["verification"]
    assert audit_after["invoice_totals"]     == snapshot["invoice_totals"]
    assert audit_after["clearance_decision"] == snapshot["clearance_decision"]


# ── GUARANTEE-2: G9 self-approval exemption ────────────────────────────────

def test_g9_exemption_for_auto_actor():
    """Auto-actor sentinel passes G9; non-sentinel equality still blocks."""
    from app.api.routes_action_proposals import _is_auto_actor, AUTO_ACTOR_SENTINELS
    assert "system:path_a_auto_queue" in AUTO_ACTOR_SENTINELS
    assert _is_auto_actor("system:path_a_auto_queue") is True
    assert _is_auto_actor("alice") is False
    assert _is_auto_actor("system:other") is False
    assert _is_auto_actor("") is False


def test_g9_blocks_manual_self_approval(tmp_path, monkeypatch):
    """Phase 2.3 must NOT relax G9 for human actors."""
    from fastapi import HTTPException
    from app.api.routes_action_proposals import _assert_can_queue
    proposal = {
        "type": "dhl_proactive_dispatch",
        "status": "approved",
        "draft": {"to": "x@y", "subject": "s",
                  "body_text": "b", "attachments": []},
        "created_by": "alice",
        "approved_by": "alice",
    }
    audit = {
        "batch_id": "B", "awb": "1234567890",
        "polish_desc_filename": "x.pdf",
        "clearance_decision": {"clearance_path": "dhl_self_clearance",
                               "total_value_usd": 1500.0},
    }
    with pytest.raises(HTTPException) as ei:
        _assert_can_queue(proposal, audit)
    assert ei.value.detail.get("code") == "self_approval_blocked"


# ──────────────────────────────────────────────────────────────────────────
# Phase 2.3.1 — corrective tests for SECURITY post-implementation findings
# ──────────────────────────────────────────────────────────────────────────


# ── ITEM-B: G9 strip-bypass + Unicode/case parametrized regression ─────────

@pytest.mark.parametrize("actor", [
    " system:path_a_auto_queue ",      # leading + trailing whitespace
    "system:path_a_auto_queue ",       # trailing whitespace
    " system:path_a_auto_queue",       # leading whitespace
    "SYSTEM:PATH_A_AUTO_QUEUE",        # uppercase — frozenset is byte-equal
    "system:path_a_auto_queue​",  # zero-width space appended
    "ѕystem:path_a_auto_queue",        # Cyrillic 'ѕ' instead of Latin 's'
])
def test_g9_blocks_padded_or_lookalike_self_approval(actor):
    """G9 must NOT exempt whitespace-padded, case-variant, zero-width,
    or Cyrillic-lookalike sentinel values. Only byte-equal-to-sentinel
    auto-actor passes the exemption."""
    from fastapi import HTTPException
    from app.api.routes_action_proposals import _assert_can_queue
    proposal = {
        "type":         "dhl_proactive_dispatch",
        "status":       "approved",
        "draft":        {"to": "x@y", "subject": "s",
                         "body_text": "b", "attachments": []},
        "created_by":   actor,
        "approved_by":  actor,
    }
    audit = {
        "batch_id": "B", "awb": "1234567890",
        "polish_desc_filename": "x.pdf",
        "clearance_decision": {"clearance_path": "dhl_self_clearance",
                               "total_value_usd": 1500.0},
    }
    with pytest.raises(HTTPException) as ei:
        _assert_can_queue(proposal, audit)
    assert ei.value.detail.get("code") == "self_approval_blocked"


def test_g9_exempts_exact_sentinel_only():
    """The byte-equal sentinel passes; everything else (including
    whitespace-padded variants) is rejected."""
    from app.api.routes_action_proposals import _is_auto_actor
    assert _is_auto_actor("system:path_a_auto_queue") is True
    assert _is_auto_actor(" system:path_a_auto_queue") is False
    assert _is_auto_actor("system:path_a_auto_queue ") is False
    assert _is_auto_actor("SYSTEM:PATH_A_AUTO_QUEUE") is False


# ── ITEM-D: operator-spoofing via proactive-dispatch endpoint ──────────────

def test_proactive_endpoint_rejects_auto_actor_operator_id(tmp_path):
    """Operator submitting operator_id matching the auto-actor sentinel
    must be rejected with 422 + auto_actor_sentinel_reserved code."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings

    client = TestClient(app)
    # Use any batch id; the validation fires before batch resolution if
    # operator_id matches the sentinel (placement after missing-id check
    # but before batch lookup).
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    r = client.post(
        "/api/v1/dhl/proactive-dispatch/SOME_BATCH",
        json={"operator_id": "system:path_a_auto_queue"},
        headers=headers,
    )
    assert r.status_code == 422
    detail = r.json().get("detail", {})
    assert detail.get("code") == "auto_actor_sentinel_reserved"


def test_proactive_endpoint_rejects_padded_auto_actor_operator_id(tmp_path):
    """ITEM-C uses .strip() before the sentinel check — padded variants
    are also rejected."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings

    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    r = client.post(
        "/api/v1/dhl/proactive-dispatch/SOME_BATCH",
        json={"operator_id": " system:path_a_auto_queue "},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json().get("detail", {}).get("code") == "auto_actor_sentinel_reserved"


def test_approve_endpoint_rejects_auto_actor_approved_by(tmp_path):
    """Same guard on approve_proposal: approved_by cannot be a sentinel."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings

    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    r = client.post(
        "/api/v1/action-proposals/some-id/approve",
        json={"approved_by": "system:path_a_auto_queue"},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json().get("detail", {}).get("code") == "auto_actor_sentinel_reserved"


# ── ITEM-F: validation-failure preserves operator's created_by ─────────────

def test_validation_fail_preserves_operator_created_by(tmp_path, monkeypatch):
    """When a Path A audit has an existing operator-created proposal and
    the auto-queue gate fails, the existing created_by must NOT be
    overwritten with _AUTO_ACTOR. Decision-trail audit fields still
    written."""
    _patch_settings(monkeypatch, tmp_path, flag=True)
    # Seed without polish_desc to force validation failure (Check 6).
    ap, _ = _seed(tmp_path, with_polish=False)
    audit = json.loads(ap.read_text())
    audit.setdefault("action_proposals", []).append({
        "proposal_id":  "operator-pp-1",
        "type":         "dhl_proactive_dispatch",
        "batch_id":     audit["batch_id"],
        "status":       "pending_review",
        "reason":       "operator_initiated",
        "confidence":   "high",
        "draft":        {},
        "created_at":   "2026-05-01T00:00:00+00:00",
        "approved_by":  None,
        "created_by":   "alice@example.com",
    })
    ap.write_text(json.dumps(audit))

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True):
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))

    assert result["outcome"].startswith("validation_failed:")
    persisted = json.loads(ap.read_text())
    proposals = persisted.get("action_proposals") or []
    operator_props = [p for p in proposals if p["proposal_id"] == "operator-pp-1"]
    assert len(operator_props) == 1
    assert operator_props[0]["created_by"] == "alice@example.com"
    # Validation_failure_reason is overwritten on the dedup-returned proposal
    # (this is intentional — latest gate result wins for this informational field).
    assert operator_props[0]["validation_failure_reason"].startswith("validation_failed:")
    # Decision trail still written
    assert persisted.get("auto_queue_decision_outcome", "").startswith("validation_failed:")


# ── ITEM-H: regex parametrized rejection / acceptance regression ───────────

@pytest.mark.parametrize("addr,expected", [
    ("odprawacelna@dhl.com",            True),   # canonical
    ("ODPRAWACELNA@DHL.COM",            True),   # uppercase via IGNORECASE
    ("odprawacelna@dhl.com.fake",       False),  # lookalike domain
    ("odprawacelna@dhi.com",            False),  # typo (dhl literal)
    ("odprawacelna@dhl-test.com",       False),  # subdomain trick
    ("odprawacelna@dhl.coni",           False),  # TLD typo
    ("odprawacelna@dhl@evil.com",       False),  # embedded @ in local-part
    ("odprawacelna@dhl.com@evil.com",   False),  # chained domains
    (" odprawacelna@dhl.com",           False),  # leading whitespace
    ("odprawacelna@dhl.com ",           False),  # trailing whitespace
    ("",                                False),  # empty
    ("odprawаcelna@dhl.com",            False),  # Cyrillic 'а'
])
def test_dhl_to_allowlist_regex(addr, expected):
    from app.services.active_shipment_monitor import _DHL_TO_ALLOWLIST_RE
    assert bool(_DHL_TO_ALLOWLIST_RE.match(addr)) is expected


def test_multi_recipient_with_one_invalid_blocks(tmp_path, monkeypatch):
    """Validation gate's per-address loop must reject when ANY resolved
    recipient fails the allowlist."""
    _patch_settings(monkeypatch, tmp_path, flag=True)
    ap, _ = _seed(tmp_path)
    from app.config import email_routing as er
    monkeypatch.setattr(er, "DHL_TO", ["odprawacelna@dhl.com",
                                       "attacker@evil.com"])
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_path_a_auto_queue(ap, json.loads(ap.read_text()))
    assert result["outcome"] == "validation_failed:recipient_not_allowlisted"
    q.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# Phase 2.3 in-process probe — Safety Path-2 (no network, flag on)
# ──────────────────────────────────────────────────────────────────────────


def test_in_process_probe_full_happy_path_with_flag_on(tmp_path, monkeypatch):
    """Phase 2.3 in-process probe (Safety Path-2). Validates the auto-queue
    observer end-to-end with the feature flag enabled, queue_email mocked
    so NO network call occurs. Run before any real-environment flag flip.

    Asserts all twelve guarantee surfaces' observable side effects on
    audit + the queue_email call signature, plus second-pass idempotency.
    """
    # ── Setup: synthetic batch, flag on, queue_email mocked ────────────
    s = _patch_settings(monkeypatch, tmp_path, flag=True)
    assert s.enable_path_a_auto_queue is True

    ap, audit_pre = _seed(
        tmp_path,
        batch_id="probe_batch_001",
        awb="0000000001",          # synthetic, passes ^\d{10}$
        cif=1500.0,
    )
    pre_verification       = json.loads(json.dumps(audit_pre["verification"]))
    pre_invoice_totals     = json.loads(json.dumps(audit_pre["invoice_totals"]))
    pre_clearance_decision = json.loads(json.dumps(audit_pre["clearance_decision"]))

    from app.services import active_shipment_monitor as asm

    captured_kwargs: dict = {}
    def _capture_queue_email(**kwargs):
        captured_kwargs.update(kwargs)
        return "probe-email-id-123"

    with patch("app.services.email_service.queue_email",
               side_effect=_capture_queue_email) as mock_queue:
        # ── First pass — should fire ───────────────────────────────────
        result_first = asm._ensure_path_a_auto_queue(
            ap, json.loads(ap.read_text()),
        )

        audit_post = json.loads(ap.read_text())

        # ── A. Flag effective at observer entry ─────────────────────────
        assert audit_post["auto_queue_flag_at_decision"] is True

        # ── B. Decision-trail completeness ─────────────────────────────
        assert audit_post["auto_queue_decision_at"]
        assert audit_post["auto_queue_decision_outcome"] == "fired"
        assert audit_post["auto_queue_actor"] == "system:path_a_auto_queue"

        # ── C. Recipient resolution correctness ────────────────────────
        assert audit_post["auto_queue_resolved_to"] == "odprawacelna@dhl.com"
        cc_resolved = audit_post["auto_queue_resolved_cc"]
        assert "info@estrellajewels.eu"    in cc_resolved
        assert "import@estrellajewels.eu"  in cc_resolved
        assert "account@estrellajewels.eu" in cc_resolved

        # ── D. Idempotency markers set in correct order ─────────────────
        assert audit_post["auto_queue_started_at"]
        assert audit_post["auto_queue_completed_at"]
        assert audit_post["auto_queue_started_at"] <= audit_post["auto_queue_completed_at"]
        assert audit_post["proactive_dispatch_sent_at"]
        assert audit_post["proactive_dispatch_email_id"] == "probe-email-id-123"

        # ── E. queue_email mock call signature ─────────────────────────
        assert mock_queue.call_count == 1, "queue_email must be called exactly once"
        assert captured_kwargs.get("to") == "odprawacelna@dhl.com"
        assert "info@estrellajewels.eu" in captured_kwargs.get("cc", "")
        subj = captured_kwargs.get("subject") or ""
        assert "0000000001" in subj                    # AWB in subject
        assert subj                                     # non-empty
        assert captured_kwargs.get("body_text")         # non-empty
        assert captured_kwargs.get("body_html")         # non-empty

        # ── F. Customs-value-freeze proof ──────────────────────────────
        assert audit_post["verification"]       == pre_verification
        assert audit_post["invoice_totals"]     == pre_invoice_totals
        assert audit_post["clearance_decision"] == pre_clearance_decision

        # ── G. Proposal status correctness ─────────────────────────────
        proposals = audit_post.get("action_proposals") or []
        assert len(proposals) == 1
        p = proposals[-1]
        assert p["type"]        == "dhl_proactive_dispatch"
        assert p["status"]      == "queued"
        assert p["created_by"]  == "system:path_a_auto_queue"
        assert p["approved_by"] == "system:path_a_auto_queue"
        assert p["email_id"]    == "probe-email-id-123"

        # ── H. G9 exemption fired correctly ─────────────────────────────
        # The fact that result["queued"] is True and no HTTPException was
        # raised by _assert_can_queue → G9 exempted the auto-actor.
        assert result_first["queued"] is True
        assert result_first["triggered"] is True
        assert result_first["error"] is None
        assert result_first["outcome"] == "fired"

        # ── I. Idempotency on second observer call ─────────────────────
        result_second = asm._ensure_path_a_auto_queue(
            ap, json.loads(ap.read_text()),
        )
        assert result_second["outcome"] == "skipped:already_fired"
        assert result_second["queued"] is False
        assert mock_queue.call_count == 1, (
            "queue_email must NOT be called a second time"
        )

    # ── Critical safety post-condition: NO NETWORK CALL was made ───────
    # The mock intercepted every queue_email invocation. If the patch had
    # ever been bypassed (real queue_email called), call_count on the
    # mock would still be 1 here only because we asserted it inline; the
    # real send would have raised on missing SMTP config or hit the wire.
    # Both inline assertions confirm no bypass occurred.
    assert mock_queue.call_count == 1
