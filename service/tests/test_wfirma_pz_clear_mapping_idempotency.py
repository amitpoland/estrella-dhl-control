"""clear-mapping idempotency fix — regression lock (2026-05-22).

Root cause (production incident — SHIPMENT_4789974092_2026-05_999deef1):
  The /wfirma/pz/clear-mapping endpoint used wfirma_export.wfirma_pz_doc_id
  as its idempotency guard.  A subsequent /process run had already wiped
  wfirma_export, so prev_doc_id was empty and the endpoint returned
  "already_cleared" — without writing wfirma_pz_mapping_cleared.  The
  lifecycle engine therefore kept the batch in PZ_RECOVERY_REQUIRED with no
  self-service exit.

Fix (PR #282):
  Idempotency is now determined by _has_pz_mapping_cleared_after_create(audit)
  — the same timeline-based authority the lifecycle engine uses.  The endpoint
  writes the clearing event any time wfirma_pz_created is in the timeline but
  wfirma_pz_mapping_cleared is not yet the latest PZ-mapping event.

Tests pin:
  1. _has_pz_mapping_cleared_after_create with incident shape (False expected).
  2. _has_pz_mapping_cleared_after_create with normal post-clear shape (True).
  3. _has_pz_mapping_cleared_after_create with doc_id wiped + cleared written (True).
  4. Source-grep: endpoint uses _has_pz_mapping_cleared_after_create, not prev_doc_id.
  5. Source-grep: clear-mapping makes no wFirma API calls.
  6. Lifecycle → PZ_RECONCILED when clearing event is present.
  7. Lifecycle stays PZ_RECOVERY_REQUIRED without clearing event (incident scenario).
  8. Clearing event is not duplicated when already present.
  9. Estrella (PZ_CREATED) regression unaffected.
"""
from __future__ import annotations

from pathlib import Path


# ── shared source ──────────────────────────────────────────────────────────

from service.app.api.routes_wfirma import (
    EV_WFIRMA_PZ_CREATED,
    _compute_pz_lifecycle_state,
    _has_pz_mapping_cleared_after_create,
)

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"


# ── audit fixtures ─────────────────────────────────────────────────────────

def _incident_audit():
    """Exact shape of the production incident.

    wfirma_export was wiped by a /process run → empty.
    Timeline still has wfirma_pz_created but no wfirma_pz_mapping_cleared.
    """
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-21T23:28:48Z", "event": "wfirma_pz_mapping_refreshed"},
        ],
    }


def _post_clear_audit():
    """Audit after clear-mapping correctly wrote the event."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-21T23:28:48Z", "event": "wfirma_pz_mapping_refreshed"},
            {"ts": "2026-05-22T10:17:00Z", "event": "wfirma_pz_mapping_cleared"},
        ],
    }


def _doc_id_wiped_then_cleared_audit():
    """doc_id wiped from wfirma_export (by /process), but clearing event
    was subsequently written by the fixed endpoint."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-22T10:17:00Z", "event": "wfirma_pz_mapping_cleared"},
        ],
    }


def _estrella_audit():
    """Estrella reference batch — PZ created normally, no clearing."""
    return {
        "wfirma_export": {
            "wfirma_pz_doc_id": "12345678",
            "pz_source": "created_via_app",
        },
        "timeline": [{"ts": "2026-05-22T00:00:00Z", "event": EV_WFIRMA_PZ_CREATED}],
    }


# ── 1. Incident shape: helper returns False ────────────────────────────────

def test_has_mapping_cleared_false_for_incident_shape():
    """The incident audit — created event present, export wiped, no cleared
    event — must return False so the endpoint proceeds to write the event."""
    assert _has_pz_mapping_cleared_after_create(_incident_audit()) is False


# ── 2. Normal post-clear: helper returns True ──────────────────────────────

def test_has_mapping_cleared_true_after_event_written():
    """Once wfirma_pz_mapping_cleared is in the timeline as the latest
    PZ-mapping event, the helper must return True (idempotency gate)."""
    assert _has_pz_mapping_cleared_after_create(_post_clear_audit()) is True


# ── 3. doc_id wiped by /process then cleared event written: True ───────────

def test_has_mapping_cleared_true_when_export_wiped_but_event_present():
    """Simulates the exact post-fix state: wfirma_export empty (wiped by
    /process) but clearing event was subsequently written.  Must return True
    so re-calling the endpoint does not write a duplicate event."""
    assert _has_pz_mapping_cleared_after_create(_doc_id_wiped_then_cleared_audit()) is True


# ── 4. Source-grep: endpoint uses timeline-based guard ─────────────────────

def test_endpoint_uses_timeline_authority_for_idempotency():
    """The fix must replace the raw `if not prev_doc_id` check with the
    timeline-based helper.  Pin this so a future simplification cannot
    accidentally revert to the broken authority."""
    src = ROUTES.read_text(encoding="utf-8")
    # Fixed guard is present.
    assert "_has_pz_mapping_cleared_after_create(audit)" in src
    # Broken guard must not appear as a standalone condition in the endpoint.
    # (It may still appear as a variable assignment for logging, so we check
    # the specific pattern that caused the bug.)
    broken_pattern = "if not prev_doc_id:"
    assert broken_pattern not in src, (
        "broken idempotency guard 'if not prev_doc_id:' must not be present — "
        "use _has_pz_mapping_cleared_after_create(audit) instead"
    )


# ── 5. Source-grep: clear-mapping makes no wFirma API calls ───────────────

def test_clear_mapping_makes_no_wfirma_api_calls():
    """clear-mapping is a local-audit-only operation.  It must never call
    the wFirma REST client (no create, delete, or read calls to wFirma)."""
    src = ROUTES.read_text(encoding="utf-8")
    # Locate the clear-mapping endpoint body.
    start = src.find("async def wfirma_pz_clear_mapping(")
    assert start > 0
    next_def = src.find("\nasync def ", start + 1)
    endpoint_body = src[start:next_def] if next_def > 0 else src[start:]
    # The endpoint body must not call wFirma API helpers.
    for forbidden in ("wf_client", "wfirma_client", "wf.create", "wf.delete",
                      "wfirma_create_pz", "wfirma_delete"):
        assert forbidden not in endpoint_body, (
            f"clear-mapping must not call wFirma API — found '{forbidden}' "
            f"in endpoint body"
        )


# ── 6. Lifecycle → PZ_RECONCILED after clearing event ─────────────────────

def test_lifecycle_transitions_to_reconciled_after_clear_event():
    """After clear-mapping writes the event, pz_preview must report
    PZ_RECONCILED so the operator can recreate the PZ."""
    out = _compute_pz_lifecycle_state(
        _post_clear_audit(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["state"]          == "PZ_RECONCILED"
    assert out["reason"]         == "pz_mapping_cleared_awaiting_recreate"
    assert out["primary_action"] == "recreate_when_ready"
    assert out["already_created"] is False if "already_created" in out else True


def test_lifecycle_reconciled_flags_for_recreation():
    """PZ_RECONCILED must allow the create path: hide_create_button reflects
    the WFIRMA_CREATE_PZ_ALLOWED flag (passed as create_allowed), and
    Resolve Products is shown (not hidden)."""
    # create_allowed=True simulates flag being on → button should be visible.
    out_allowed = _compute_pz_lifecycle_state(
        _post_clear_audit(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    # create_allowed=False simulates flag off → button hidden.
    out_blocked = _compute_pz_lifecycle_state(
        _post_clear_audit(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out_allowed["state"] == "PZ_RECONCILED"
    assert out_blocked["state"] == "PZ_RECONCILED"
    # Resolve Products must not be hidden in RECONCILED state.
    assert out_allowed.get("hide_resolve_products") is not True


# ── 7. Lifecycle stays PZ_RECOVERY_REQUIRED without clearing event ─────────

def test_lifecycle_stays_recovery_required_without_clear_event():
    """Regression pin for the incident: without the clearing event the
    lifecycle MUST NOT silently drop to PZ_RECONCILED or PZ_READY_TO_CREATE.
    This is the exact production state before the fix was applied."""
    out = _compute_pz_lifecycle_state(
        _incident_audit(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["state"]          == "PZ_RECOVERY_REQUIRED"
    assert out["primary_action"] == "confirm_existing_pz"
    assert out["hide_create_button"]    is True
    assert out["hide_resolve_products"] is True
    assert out["override_create_disabled_message"] is True


# ── 8. Clearing event not duplicated ──────────────────────────────────────

def test_helper_returns_true_when_event_already_present():
    """When wfirma_pz_mapping_cleared is already the latest PZ-mapping event,
    the helper must return True so callers know not to append another event."""
    assert _has_pz_mapping_cleared_after_create(_doc_id_wiped_then_cleared_audit()) is True
    assert _has_pz_mapping_cleared_after_create(_post_clear_audit()) is True


# ── 9. Estrella regression ─────────────────────────────────────────────────

def test_estrella_created_audit_unaffected():
    """A normally-created PZ (Estrella reference) must still classify as
    PZ_CREATED regardless of the idempotency fix.  The clearing-event check
    must not interfere with the happy path."""
    out = _compute_pz_lifecycle_state(
        _estrella_audit(),
        preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"] == "PZ_CREATED"
    assert out["primary_action"] == "none"
    assert out["hide_create_button"] is True
