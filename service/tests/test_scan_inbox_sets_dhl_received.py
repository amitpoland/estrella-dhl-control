"""
test_scan_inbox_sets_dhl_received.py
=====================================
Regression: when GET /api/v1/dhl/scan-inbox finds an odprawacelna@dhl.com
T# customs email matched to a known AWB, the route must write
audit.dhl_email.received = True so the B2 DSK-reply path in
active_shipment_monitor fires on the next sweep.

Root cause fixed here:
  routes_dhl_clearance.py scan_dhl_inbox handler — after logging
  EV_DHL_INBOX_SCANNED, the handler now checks each matched email for a
  DHL customs sender + T# ticket and writes dhl_email.received directly
  to the audit. Without this write, the monitor's _apply_derived_events
  exits early (derived_events is empty) and the B2 auto-reply never fires.

AWB 8400636576 (real incident 2026-06-05):
  odprawacelna@dhl.com sent T#1WA2606050000553; inbox scanned 3×; but
  dhl_email.received was never set; DSK was NOT sent to DHL automatically.
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
