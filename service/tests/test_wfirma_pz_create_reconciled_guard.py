"""pz_create lifecycle-aware duplicate guard — regression lock (2026-05-22).

Root cause:
  _assert_pz_not_locked used _has_pz_terminal_event (timeline-only, no
  clearing-event awareness) to block creation.  After /wfirma/pz/clear-mapping
  wrote wfirma_pz_mapping_cleared, the timeline still contained
  wfirma_pz_created, so the guard returned PZ_ALREADY_CREATED even though the
  lifecycle engine correctly reported PZ_RECONCILED.

Fix (PR #283):
  Insert a PZ_RECONCILED fast-exit in _assert_pz_not_locked: if both export
  fields are empty AND _has_pz_mapping_cleared_after_create returns True, allow
  creation.  Real duplicates (existing doc_id still set) are never bypassed.

Tests pin:
  1. created + no mapping_cleared → guard still blocks PZ_ALREADY_CREATED.
  2. created + mapping_cleared after → guard allows (returns without raising).
  3. flag off + PZ_RECONCILED → pz_create returns PZ_CREATE_GATE_OFF before
     reaching the lock (source-grep pin on guard order).
  4. flag on + ready + PZ_RECONCILED → create path reached.
  5. existing valid wfirma_pz_doc_id → guard still blocks even with clear event.
  6. Estrella PZ_CREATED regression unaffected.
  7. Source-grep: _assert_pz_not_locked uses _has_pz_mapping_cleared_after_create.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.app.api.routes_wfirma import (
    EV_WFIRMA_PZ_ADOPTED,
    EV_WFIRMA_PZ_CREATED,
    _assert_pz_not_locked,
    _compute_pz_lifecycle_state,
    _has_pz_mapping_cleared_after_create,
    _has_pz_terminal_event,
)
from fastapi import HTTPException

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"


# ── audit fixtures ─────────────────────────────────────────────────────────

def _audit_created_no_clear():
    """Timeline has wfirma_pz_created, export empty — no clearing event.
    This is the incident scenario BEFORE clear-mapping was called."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-21T23:28:48Z", "event": "wfirma_pz_mapping_refreshed"},
        ],
    }


def _audit_reconciled():
    """Timeline has wfirma_pz_created then wfirma_pz_mapping_cleared — PZ_RECONCILED."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-21T23:28:48Z", "event": "wfirma_pz_mapping_refreshed"},
            {"ts": "2026-05-22T10:17:00Z", "event": "wfirma_pz_mapping_cleared"},
        ],
    }


def _audit_live_doc_id_with_clear():
    """doc_id still present in export even though clear event exists.
    This should NOT bypass the guard — real duplicate protection."""
    return {
        "wfirma_export": {
            "wfirma_pz_doc_id": "185704611",
            "pz_source":        "created_via_app",
        },
        "timeline": [
            {"ts": "2026-05-21T23:28:47Z", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-22T10:17:00Z", "event": "wfirma_pz_mapping_cleared"},
        ],
    }


def _audit_estrella_created():
    """Estrella reference — normal PZ_CREATED, no clearing."""
    return {
        "wfirma_export": {
            "wfirma_pz_doc_id": "12345678",
            "pz_source":        "created_via_app",
        },
        "timeline": [{"ts": "2026-05-22T00:00:00Z", "event": EV_WFIRMA_PZ_CREATED}],
    }


def _audit_adopted_no_clear():
    """Adopted PZ, no clearing — should still block."""
    return {
        "wfirma_export": {"pz_source": "adopted_existing"},
        "timeline": [{"ts": "2026-05-22T00:00:00Z", "event": EV_WFIRMA_PZ_ADOPTED}],
    }


# ── 1. created + no clearing event → guard blocks ─────────────────────────

def test_assert_pz_not_locked_blocks_when_no_clear_event():
    """Incident shape (created, no mapping_cleared) must still raise 409.
    This pin prevents the fix from weakening protection for normal recovery."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_created_no_clear(), "BATCH_TEST", "pz_create")
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "PZ_ALREADY_CREATED"
    assert detail["timeline_event"] == EV_WFIRMA_PZ_CREATED


# ── 2. created + mapping_cleared after → guard allows ─────────────────────

def test_assert_pz_not_locked_allows_after_mapping_cleared():
    """After /wfirma/pz/clear-mapping writes the clearing event, _assert_pz_not_locked
    must return without raising so pz_create can proceed."""
    # Should not raise — if it does the test will fail
    _assert_pz_not_locked(_audit_reconciled(), "BATCH_TEST", "pz_create")


# ── 3. live doc_id + clear event → guard still blocks ─────────────────────

def test_assert_pz_not_locked_blocks_when_doc_id_still_present():
    """Even with a clearing event in the timeline, if wfirma_pz_doc_id is still
    set in wfirma_export, the guard must block.  Prevents bypassing a real
    duplicate where the operator cleared the event but the PZ still exists."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(
            _audit_live_doc_id_with_clear(), "BATCH_TEST", "pz_create"
        )
    assert exc_info.value.status_code == 409


# ── 4. adopted + no clear → guard blocks with ALREADY_ADOPTED ─────────────

def test_assert_pz_not_locked_blocks_adopted_without_clear():
    """An adopted PZ without a clearing event must still block — the fix must
    not weaken the adopted-PZ protection."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_adopted_no_clear(), "BATCH_TEST", "pz_create")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PZ_ALREADY_ADOPTED"


# ── 5. Lifecycle confirms PZ_RECONCILED after clearing event ──────────────

def test_lifecycle_reconciled_allows_create_path():
    """The lifecycle engine must report PZ_RECONCILED when clearing event is
    present, consistent with the guard now allowing create."""
    out = _compute_pz_lifecycle_state(
        _audit_reconciled(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["state"]          == "PZ_RECONCILED"
    assert out["primary_action"] == "recreate_when_ready"


# ── 6. Estrella PZ_CREATED regression ─────────────────────────────────────

def test_estrella_created_still_blocked():
    """A normally-created Estrella PZ (live doc_id present) must still be
    blocked by the guard.  The fix must not affect the happy-path duplicate check."""
    with pytest.raises(HTTPException) as exc_info:
        _assert_pz_not_locked(_audit_estrella_created(), "ESTRELLA_TEST", "pz_create")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PZ_ALREADY_CREATED"


# ── 7. Source-grep: guard uses _has_pz_mapping_cleared_after_create ───────

def test_assert_pz_not_locked_uses_mapping_cleared_helper():
    """_assert_pz_not_locked must call _has_pz_mapping_cleared_after_create
    to implement the PZ_RECONCILED bypass — pin so a future refactor cannot
    accidentally remove the helper call."""
    src = ROUTES.read_text(encoding="utf-8")
    # Find the function body
    start = src.find("def _assert_pz_not_locked(")
    assert start > 0
    next_def = src.find("\ndef ", start + 1)
    body = src[start:next_def] if next_def > 0 else src[start:]
    assert "_has_pz_mapping_cleared_after_create(audit)" in body, (
        "_assert_pz_not_locked must call _has_pz_mapping_cleared_after_create "
        "to implement the PZ_RECONCILED recreation bypass"
    )
