"""
test_scan_inbox_sets_dhl_received.py
=====================================
Regression: when GET /api/v1/dhl/scan-inbox finds an odprawacelna@dhl.com
T# customs email matched to a known AWB, the route must write
audit.dhl_email.received = True so the B2 DSK-reply path in
active_shipment_monitor fires on the next sweep.

Root cause fixed here (PR #454):
  routes_dhl_clearance.py scan_dhl_inbox handler — after logging
  EV_DHL_INBOX_SCANNED, the handler now checks each matched email for a
  DHL customs sender + T# ticket and writes dhl_email.received directly
  to the audit. Without this write, the monitor's _apply_derived_events
  exits early (derived_events is empty) and the B2 auto-reply never fires.

Hardened (PR #455 — GAP-1 fix):
  The write is now gated by _is_active() so terminal/delivered batches
  whose AWB appears in a late DHL email are not re-flagged. A delivered
  shipment must never restart B2 automation.

AWB 8400636576 (real incident 2026-06-05):
  odprawacelna@dhl.com sent T#1WA2606050000553; inbox scanned 3×; but
  dhl_email.received was never set; DSK was NOT sent to DHL automatically.

GAP-2 (deferred, documented):
  The native email classifier maps odprawacelna@dhl.com → "dhl_arrival"
  → timeline event "carrier_arrived". This feeds sla_engine.py SLA
  anchors (arrival_to_sad, fedex_arrival_to_cesja) and
  routes_intelligence.py next-step guidance. Do NOT change this mapping.
  The AI Bridge path uses "dhl_customs_request" → "dhl_customs_email_received"
  for the derived-events cache route. The two event names serve different
  subsystems and must remain separate.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── Source-grep checks (route-level; no server needed) ───────────────────────

_ROUTE = (
    Path(__file__).parent.parent
    / "app" / "api" / "routes_dhl_clearance.py"
)


def test_scan_handler_checks_dhl_customs_senders():
    """Handler must define the set of DHL customs senders to detect."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "_DHL_CUSTOMS_SENDERS" in src, (
        "scan_dhl_inbox must define _DHL_CUSTOMS_SENDERS to identify "
        "odprawacelna@dhl.com T# emails"
    )


def test_scan_handler_includes_odprawacelna():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "odprawacelna@dhl.com" in src, (
        "scan_dhl_inbox must explicitly include odprawacelna@dhl.com "
        "in its DHL customs sender check"
    )


def test_scan_handler_writes_dhl_email_received():
    """Handler must write dhl_email.received after finding a customs email."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    # The write must appear after the DHL customs sender check
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    received_write_idx = src.index('"received":     True', sender_idx)
    assert received_write_idx > sender_idx, (
        "dhl_email.received = True must be written after _DHL_CUSTOMS_SENDERS check"
    )


def test_scan_handler_calls_write_json_atomic_in_customs_path():
    """write_json_atomic must be called inside the customs-email block."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    # write_json_atomic should appear after the DHL customs sender check
    # Accepts either the aliased form (_wja_scan) or the direct name
    alias_idx  = src.find("_wja_scan(_ap, _cur_audit)", sender_idx)
    direct_idx = src.find("write_json_atomic(_ap, _cur_audit)", sender_idx)
    atomic_idx = max(alias_idx, direct_idx)
    assert atomic_idx > sender_idx, (
        "write_json_atomic (or its alias _wja_scan) must be called with the "
        "updated audit inside the _DHL_CUSTOMS_SENDERS match block"
    )


def test_scan_handler_idempotent_guard():
    """Handler must NOT re-write if received is already set."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    # The check for existing received must precede the write
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    guard_idx  = src.index(".get(\"received\")", sender_idx)
    alias_idx  = src.find("_wja_scan(_ap, _cur_audit)", sender_idx)
    direct_idx = src.find("write_json_atomic(_ap, _cur_audit)", sender_idx)
    write_idx  = max(alias_idx, direct_idx)
    assert write_idx > 0, "Atomic write call must exist in customs block"
    assert guard_idx < write_idx, (
        "Idempotency guard (.get('received')) must appear before the atomic write"
    )


def test_scan_handler_logs_dhl_email_received_event():
    """Handler must emit EV_DHL_EMAIL_RECEIVED timeline event when writing."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    ev_idx = src.index("EV_DHL_EMAIL_RECEIVED", sender_idx)
    assert ev_idx > sender_idx, (
        "EV_DHL_EMAIL_RECEIVED event must be logged inside the "
        "_DHL_CUSTOMS_SENDERS match block"
    )


def test_scan_handler_stores_ticket_in_dhl_ticket_field():
    """T# ticket must be written to audit.dhl_ticket for reference."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    ticket_write = src.find('"dhl_ticket"', sender_idx)
    assert ticket_write > sender_idx, (
        "audit.dhl_ticket must be populated from the T# ticket inside "
        "the _DHL_CUSTOMS_SENDERS match block"
    )


# ── GAP-1 guard tests (PR #455) ──────────────────────────────────────────────

def test_scan_handler_imports_is_active_guard():
    """GAP-1: scan handler must import _is_active from active_shipment_monitor."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    # The import must appear inside the _DHL_CUSTOMS_SENDERS block
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    # Accept either the aliased name or the direct import
    alias_import = src.find("_scan_batch_is_active", sender_idx)
    direct_import = src.find("_is_active as _scan_batch_is_active", sender_idx)
    found_idx = max(alias_import, direct_import)
    assert found_idx > sender_idx, (
        "scan_dhl_inbox must import/use _is_active (as _scan_batch_is_active) "
        "inside the _DHL_CUSTOMS_SENDERS block to guard against inactive batches"
    )


def test_scan_handler_is_active_check_precedes_received_write():
    """GAP-1: _is_active check must come BEFORE the dhl_email.received write."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    active_check_idx = src.index("_scan_batch_is_active", sender_idx)
    received_write_idx = src.index('"received":     True', sender_idx)
    assert active_check_idx < received_write_idx, (
        "_scan_batch_is_active (GAP-1 guard) must appear before "
        "'received': True write — active batches must be confirmed eligible "
        "before the flag is set"
    )


def test_scan_handler_skip_path_for_inactive_batch():
    """GAP-1: a log.info skip path must exist for inactive batches."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    # The skip path must log that the batch is terminal/inactive
    skip_log_idx = src.find("skipping dhl_email.received", sender_idx)
    assert skip_log_idx > sender_idx, (
        "scan_dhl_inbox must log a skip message when _scan_batch_is_active "
        "returns False — silent skips make incidents hard to diagnose"
    )
    # Verify the skip comes BEFORE the write (not after)
    received_write_idx = src.index('"received":     True', sender_idx)
    assert skip_log_idx < received_write_idx, (
        "Skip log for inactive batch must precede the 'received': True write"
    )


def test_scan_handler_active_check_before_idempotency_guard():
    """GAP-1: _is_active check must precede the idempotency (.get('received')) guard.
    Order: active-check → idempotency → write. Both guard the write.
    """
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    active_idx = src.index("_scan_batch_is_active", sender_idx)
    # .get("received") for idempotency check (first occurrence after sender check)
    idem_idx = src.index('.get("received")', sender_idx)
    assert active_idx < idem_idx, (
        "_scan_batch_is_active (GAP-1 outer guard) must come before the "
        "idempotency .get('received') inner guard"
    )


def test_gap2_deferral_documented_in_route():
    """GAP-2 (deferred): the route must carry a comment explaining that
    carrier_arrived and dhl_customs_email_received serve different subsystems
    and must NOT be merged.
    """
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    sender_idx = src.index("_DHL_CUSTOMS_SENDERS")
    # The comment must explain the duality
    gap2_note_idx = src.find("GAP-2", sender_idx)
    assert gap2_note_idx > sender_idx, (
        "GAP-2 deferral must be documented with a 'GAP-2' comment inside the "
        "_DHL_CUSTOMS_SENDERS block so future developers understand why "
        "carrier_arrived and dhl_customs_email_received are separate"
    )
    # Also confirm carrier_arrived is still preserved (not replaced)
    carrier_arrived_idx = src.find("carrier_arrived", sender_idx)
    assert carrier_arrived_idx > sender_idx, (
        "carrier_arrived event name must still appear near the GAP-2 comment "
        "to confirm the mapping was intentionally preserved"
    )


# ── Functional test: real audit write with mocked scan result ────────────────

@pytest.fixture
def _batch_dir(tmp_path, monkeypatch):
    """Create a minimal batch output dir with audit.json; point storage root there."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    batch_id = "SHIPMENT_TEST_" + uuid.uuid4().hex[:8]
    bd = tmp_path / "outputs" / batch_id
    bd.mkdir(parents=True)
    audit = {
        "batch_id":   batch_id,
        "awb":        "8400636576",
        "status":     "draft",
        "clearance_decision": {
            "clearance_path":   "agency_clearance",
            "total_value_usd":  12427.0,
            "require_dsk":      True,
        },
        "dsk_filename": "DSK_8400636576_02-06-2026.pdf",
        "dsk_path":     str(tmp_path / "dsk_outputs" / "DSK_8400636576_02-06-2026.pdf"),
    }
    (bd / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return bd, batch_id


def test_scan_writes_received_flag_when_odprawacelna_email_matched(
    _batch_dir, monkeypatch
):
    """Functional: after scan finds T# email from odprawacelna@dhl.com,
    audit.dhl_email.received must be True on disk."""
    bd, batch_id = _batch_dir

    # Patch the Zoho scan so it returns a matched odprawacelna email for our AWB.
    _fake_scan_result = {
        "scanned": 3,
        "matched": 1,
        "awb":     "8400636576",
        "scan_method": "zoho_api",
        "search_mode": "awb_targeted",
        "query_used":  "test",
        "emails": [
            {
                "from":       "odprawacelna@dhl.com",
                "subject":    "T#1WA2606050000553 - AWB 8400636576 celna",
                "dhl_ticket": "T#1WA2606050000553",
                "awb":        "8400636576",
                "received_at": "2026-06-05T08:00:00Z",
                "detected_type": "dhl_arrival",
                "matched_fields": ["subject"],
            }
        ],
        "scanned_at": "2026-06-05T08:01:00Z",
    }

    # Patch at the point where scan_dhl_inbox assembles its result dict.
    # We patch the Zoho mail search so the native scan path returns our fake result.
    import app.api.routes_dhl_clearance as _r
    monkeypatch.setattr(
        _r, "_scan_zoho_inbox_for_awb",
        lambda *a, **kw: _fake_scan_result,
        raising=False,
    )
    # Also patch the lower-level scan function used by the route
    from unittest.mock import AsyncMock, patch as _patch
    with _patch.object(
        _r, "_run_native_inbox_scan",
        return_value=_fake_scan_result,
        create=True,
    ):
        pass  # Just confirming the patch attribute; real patch below via client

    # Use the app's TestClient with a patched scan result injected via the
    # result-assembly section. The simplest approach: patch the entire
    # scan pipeline to return our fake_result, then call the endpoint.
    from app.core.config import settings as _s
    from unittest.mock import patch as _p, AsyncMock as _AM

    os_env = {"API_KEY": "test-key"}
    import os
    for k, v in os_env.items():
        monkeypatch.setenv(k, v)

    # Reload settings to pick up the patched API_KEY
    monkeypatch.setattr(_s, "api_key", "test-key")

    # Patch the full scan-inbox endpoint at the result-assembly level.
    # We target the _run_inbox_scan helper that returns the unified result dict.
    with _p("app.api.routes_dhl_clearance._run_inbox_scan",
             return_value=_fake_scan_result,
             create=True):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/dhl/scan-inbox",
            params={"batch_id": batch_id, "awb": "8400636576"},
            headers={"X-API-Key": "test-key"},
        )

    # Either 200 (scan ran) or a non-500 (route didn't crash); what we care
    # about is the audit write, not the HTTP status (scan may 200 even when
    # credentials are absent — it returns a structured result).
    audit_path = bd / "audit.json"
    assert audit_path.exists(), "audit.json must exist after scan"
    written = json.loads(audit_path.read_text(encoding="utf-8"))
    dhl_email = written.get("dhl_email") or {}
    assert dhl_email.get("received") is True, (
        f"audit.dhl_email.received must be True after scan matched "
        f"odprawacelna@dhl.com T# email. Got: {dhl_email}"
    )
    assert dhl_email.get("ticket") == "T#1WA2606050000553", (
        f"audit.dhl_email.ticket must be the T# from the email. "
        f"Got: {dhl_email.get('ticket')!r}"
    )
