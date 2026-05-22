"""Confirm Existing PZ (pz_adopt) guard fixes — regression lock (2026-05-22).

Root causes:
  1. Guard 0 (WFIRMA_CREATE_PZ_ALLOWED) blocked pz_adopt even though adoption
     makes zero wFirma write calls. Recovery must not require the creation flag.
  2. _assert_pz_not_locked blocked adoption in PZ_RECOVERY_REQUIRED state:
     empty export + wfirma_pz_created in timeline -> PZ_ALREADY_CREATED 409.
  3. No /wfirma/pz_confirm route alias despite "Confirm Existing PZ" being the
     UI term and confirm_existing_pz being the lifecycle primary_action value.

Fixes (PR #285):
  1. Removed Guard 0 from pz_adopt. Added comment explaining separation of
     concerns: create flag governs wFirma writes; adoption is a local audit
     re-link only (wFirma is read-only from adopt's perspective).
  2. Added recovery fast-exit in _assert_pz_not_locked for action="pz_adopt":
     when both export fields are empty, adoption is allowed regardless of
     terminal timeline events.
  3. Added @router.post("/wfirma/pz_confirm") alias on the same handler.
  4. pz_adopt success responses now include wfirma_pz_view_url.

Lesson I classification:
  Type: Operator confusion + conflicting statuses (lifecycle says "confirm", guard says "blocked")
  Authority owner: pz_lifecycle.primary_action drives the UI; pz_adopt is the handler
  Workflow class: any batch in PZ_RECOVERY_REQUIRED — all suppliers, all batches
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from service.app.api.routes_wfirma import (
    EV_WFIRMA_PZ_ADOPTED,
    EV_WFIRMA_PZ_CREATED,
    _assert_pz_not_locked,
    _compute_pz_lifecycle_state,
)

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"


# ── audit fixtures ─────────────────────────────────────────────────────────

def _audit_recovery():
    """PZ_RECOVERY_REQUIRED: created event, export wiped, no clearing event."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-21T23:28:48Z", "event": "wfirma_pz_mapping_refreshed"},
        ],
    }


def _audit_reconciled():
    """PZ_RECONCILED: created then cleared."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-22T10:17:00Z", "event": "wfirma_pz_mapping_cleared"},
        ],
    }


def _audit_created_live():
    """Normally created PZ with live doc_id — adoption must still be blocked."""
    return {
        "wfirma_export": {
            "wfirma_pz_doc_id": "185704611",
            "pz_source":        "created_via_app",
        },
        "timeline": [{"ts": "2026-05-21Z", "event": EV_WFIRMA_PZ_CREATED}],
    }


def _audit_adopted_live():
    """Already-adopted PZ with live doc_id — re-adoption blocked."""
    return {
        "wfirma_export": {
            "wfirma_pz_doc_id": "185759075",
            "pz_source":        "adopted_existing",
        },
        "timeline": [{"ts": "2026-05-21Z", "event": EV_WFIRMA_PZ_ADOPTED}],
    }


# ── 1. PZ_RECOVERY_REQUIRED: pz_adopt allowed (recovery fast-exit) ────────

def test_assert_pz_not_locked_allows_adopt_in_recovery_state():
    """PZ_RECOVERY_REQUIRED: export empty, created in timeline, no clearing.
    pz_adopt must be allowed so the operator can re-link the existing PZ."""
    # Should NOT raise
    _assert_pz_not_locked(_audit_recovery(), "BATCH_TEST", "pz_adopt")


# ── 2. PZ_RECOVERY_REQUIRED: pz_create still blocked ─────────────────────

def test_assert_pz_not_locked_blocks_create_in_recovery_state():
    """pz_create in PZ_RECOVERY_REQUIRED must still be blocked — the recovery
    path uses adopt, not create."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_recovery(), "BATCH_TEST", "pz_create")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PZ_ALREADY_CREATED"


# ── 3. PZ_RECONCILED: pz_adopt also allowed (reconciled bypass covers it) ─

def test_assert_pz_not_locked_allows_adopt_in_reconciled_state():
    """PZ_RECONCILED: export empty, clearing event present.
    pz_adopt must be allowed (re-create-after-delete workflow)."""
    _assert_pz_not_locked(_audit_reconciled(), "BATCH_TEST", "pz_adopt")


# ── 4. Live doc_id still blocks adopt ─────────────────────────────────────

def test_assert_pz_not_locked_blocks_adopt_when_doc_id_present():
    """When a live doc_id is present in the export, adoption must still
    be blocked — this is a real duplicate, not a recovery case."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_created_live(), "BATCH_TEST", "pz_adopt")
    assert exc_info.value.status_code == 409


# ── 5. Adopted-live doc_id still blocks adopt ─────────────────────────────

def test_assert_pz_not_locked_blocks_re_adopt_when_different_doc_id_present():
    """Already-adopted PZ with live doc_id → cannot overwrite with a different
    doc_id through adopt."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_adopted_live(), "BATCH_TEST", "pz_adopt")
    assert exc_info.value.status_code == 409


# ── 6. Lifecycle confirms PZ_RECOVERY_REQUIRED for recovery audit ─────────

def test_lifecycle_recovery_required_for_recovery_audit():
    out = _compute_pz_lifecycle_state(
        _audit_recovery(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"]          == "PZ_RECOVERY_REQUIRED"
    assert out["primary_action"] == "confirm_existing_pz"


# ── 7. pz_confirm alias present in routes ─────────────────────────────────

def test_pz_confirm_route_alias_present():
    src = ROUTES.read_text(encoding="utf-8")
    assert '"/shipment/{batch_id}/wfirma/pz_confirm"' in src, (
        "pz_confirm route alias must be registered in routes_wfirma.py"
    )
    # Must be on the same handler as pz_adopt
    confirm_idx = src.find('"/shipment/{batch_id}/wfirma/pz_confirm"')
    adopt_idx   = src.find('"/shipment/{batch_id}/wfirma/pz_adopt"')
    assert confirm_idx > 0 and adopt_idx > 0
    # Both decorators should be within 10 lines of each other
    confirm_line = src[:confirm_idx].count('\n')
    adopt_line   = src[:adopt_idx].count('\n')
    assert abs(confirm_line - adopt_line) <= 10, (
        "pz_confirm and pz_adopt decorators must be on the same handler"
    )


# ── 8. Guard 0 removed from pz_adopt ─────────────────────────────────────

def test_guard_0_removed_from_pz_adopt():
    """WFIRMA_CREATE_PZ_ALLOWED must NOT gate pz_adopt.
    Source-grep: the old guard message must not be present in the adopt handler."""
    src = ROUTES.read_text(encoding="utf-8")
    adopt_start = src.find("async def wfirma_pz_adopt(")
    assert adopt_start > 0
    next_def = src.find("\nasync def ", adopt_start + 1)
    body = src[adopt_start:next_def] if next_def > 0 else src[adopt_start:]
    assert "WFIRMA_CREATE_PZ_ALLOWED is not enabled" not in body, (
        "Guard 0 (WFIRMA_CREATE_PZ_ALLOWED) must not be in pz_adopt — "
        "adoption makes no wFirma writes, so the creation flag does not apply"
    )


# ── 9. wfirma_pz_view_url in adopt success response ──────────────────────

def test_adopt_success_response_includes_view_url():
    src = ROUTES.read_text(encoding="utf-8")
    adopt_start = src.find("async def wfirma_pz_adopt(")
    assert adopt_start > 0
    next_def = src.find("\nasync def ", adopt_start + 1)
    body = src[adopt_start:next_def] if next_def > 0 else src[adopt_start:]
    view_url_count = body.count('"wfirma_pz_view_url"')
    assert view_url_count >= 2, (
        f"pz_adopt must return wfirma_pz_view_url in both already_adopted "
        f"and adopted responses; found {view_url_count} occurrences"
    )


# ── 10. Estrella regression: created PZ still blocks adopt ────────────────

def test_estrella_created_pz_still_blocks_adopt():
    """A normally-created Estrella PZ (live doc_id) must still block adoption.
    The recovery fast-exit must not weaken protection for live doc_ids."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_created_live(), "ESTRELLA", "pz_adopt")
    assert exc_info.value.status_code == 409
