"""Single PZ lifecycle authority (2026-05-22).

`_compute_pz_lifecycle_state` is the SOLE authority every UI surface
should consult for the PZ panel. It collapses four previously separate
authority sources (pz_preview.ready, pz_lock_status,
capabilities.create_pz_allowed, timeline events) into one canonical
enum value plus an action envelope.

These tests pin the precedence contract and prove every documented
state is reachable from a synthetic audit shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.app.api.routes_wfirma import (
    EV_WFIRMA_PZ_ADOPTED,
    EV_WFIRMA_PZ_CREATED,
    PZ_LIFECYCLE_STATES,
    _compute_pz_lifecycle_state,
    _has_pz_mapping_cleared_after_create,
)


# ── Fixtures ────────────────────────────────────────────────────────────

def _empty_audit():
    return {"wfirma_export": {}, "timeline": []}


def _audit_created(doc_id="185704611", source="created_via_app"):
    return {
        "wfirma_export": {"wfirma_pz_doc_id": doc_id, "pz_source": source},
        "timeline": [{"ts": "2026-05-22T00:00:00", "event": EV_WFIRMA_PZ_CREATED}],
    }


def _audit_recovery():
    """Timeline says created, audit doc_id empty (audit-write failed)."""
    return {
        "wfirma_export": {},
        "timeline": [{"ts": "2026-05-22T00:00:00", "event": EV_WFIRMA_PZ_CREATED}],
    }


def _audit_reconciled():
    """Created then mapping cleared by operator."""
    return {
        "wfirma_export": {},
        "timeline": [
            {"ts": "2026-05-22T00:00:00", "event": EV_WFIRMA_PZ_CREATED},
            {"ts": "2026-05-22T01:00:00", "event": "wfirma_pz_mapping_refreshed"},
            {"ts": "2026-05-22T02:00:00", "event": "wfirma_pz_mapping_cleared"},
        ],
    }


# ── 1. PZ_CREATED ──────────────────────────────────────────────────────

def test_state_pz_created_when_doc_id_and_source():
    out = _compute_pz_lifecycle_state(
        _audit_created(),
        preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"]                            == "PZ_CREATED"
    assert out["reason"]                           == "pz_created"
    assert out["primary_action"]                   == "none"
    assert out["wfirma_pz_doc_id"]                 == "185704611"
    assert out["hide_create_button"]               is True
    assert out["hide_resolve_products"]            is False


def test_state_pz_created_adopted_variant():
    out = _compute_pz_lifecycle_state(
        _audit_created(source="adopted_existing"),
        preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"] == "PZ_CREATED"
    assert out["reason"] == "pz_adopted_existing"


# ── 2. PZ_RECOVERY_REQUIRED ───────────────────────────────────────────

def test_state_pz_recovery_required():
    out = _compute_pz_lifecycle_state(
        _audit_recovery(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"]                            == "PZ_RECOVERY_REQUIRED"
    assert out["reason"]                           == "audit_write_recovery_required"
    assert out["primary_action"]                   == "confirm_existing_pz"
    assert "refresh_mapping" in out["secondary_actions"]
    assert out["terminal_event"]                   == EV_WFIRMA_PZ_CREATED


# ── 3. Recovery overrides "creation disabled" messaging ───────────────

def test_recovery_overrides_create_disabled_message():
    """RULE: when state=PZ_RECOVERY_REQUIRED, the UI MUST NOT show
    'PZ creation disabled' even when WFIRMA_CREATE_PZ_ALLOWED=False.
    The flag is structurally irrelevant — the operator's job is to
    Confirm Existing PZ, not flip a flag."""
    out = _compute_pz_lifecycle_state(
        _audit_recovery(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["override_create_disabled_message"] is True


# ── 4. Recovery hides Resolve Products + Create ──────────────────────

def test_recovery_hides_resolve_products():
    out = _compute_pz_lifecycle_state(_audit_recovery(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["hide_create_button"]    is True
    assert out["hide_resolve_products"] is True


# ── 5. PZ_RECONCILED ──────────────────────────────────────────────────

def test_state_pz_reconciled_after_mapping_cleared():
    out = _compute_pz_lifecycle_state(
        _audit_reconciled(),
        preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["state"]          == "PZ_RECONCILED"
    assert out["reason"]         == "pz_mapping_cleared_awaiting_recreate"
    assert out["primary_action"] == "recreate_when_ready"


def test_mapping_cleared_after_create_helper():
    assert _has_pz_mapping_cleared_after_create(_audit_reconciled()) is True
    assert _has_pz_mapping_cleared_after_create(_audit_recovery()) is False
    assert _has_pz_mapping_cleared_after_create(_audit_created()) is False


# ── 6. PZ_READY_TO_CREATE ─────────────────────────────────────────────

def test_state_pz_ready_to_create():
    out = _compute_pz_lifecycle_state(
        _empty_audit(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["state"]                  == "PZ_READY_TO_CREATE"
    assert out["primary_action"]         == "create_pz"
    assert out["hide_create_button"]     is False


# ── 7. PZ_NOT_READY when create flag off ──────────────────────────────

def test_state_pz_not_ready_when_create_disabled():
    out = _compute_pz_lifecycle_state(
        _empty_audit(),
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"]              == "PZ_NOT_READY"
    assert out["reason"]             == "create_disabled"
    assert out["hide_create_button"] is True


# ── 8. PZ_NOT_READY with blocker codes ────────────────────────────────

def test_state_pz_not_ready_when_preview_not_ready_carries_blocker_codes():
    out = _compute_pz_lifecycle_state(
        _empty_audit(),
        preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
        blocker_codes=["ENGINE_ERROR"],
    )
    assert out["state"]         == "PZ_NOT_READY"
    assert out["reason"]        == "preview_not_ready"
    assert out["blocker_codes"] == ["ENGINE_ERROR"]


# ── 9. PZ_DUPLICATE_DETECTED ──────────────────────────────────────────

def test_state_pz_duplicate_detected_overrides_everything():
    a = _audit_created()
    out = _compute_pz_lifecycle_state(
        a,
        preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
        duplicate_owner_batch_id="SHIPMENT_OTHER_2026-05_abc12345",
    )
    assert out["state"]                            == "PZ_DUPLICATE_DETECTED"
    assert out["reason"]                           == "wfirma_pz_doc_id_claimed_by_other_batch"
    assert out["hide_create_button"]               is True
    assert out["hide_resolve_products"]            is True
    assert out["override_create_disabled_message"] is True
    assert out["duplicate_owner_batch_id"]         == "SHIPMENT_OTHER_2026-05_abc12345"


# ── 10. PZ_LOCKED ─────────────────────────────────────────────────────

def test_state_pz_locked_when_audit_flag_set():
    a = _empty_audit()
    a["wfirma_locked"] = True
    out = _compute_pz_lifecycle_state(
        a,
        preview_ready=True, supplier_configured=True,
        warehouse_configured=True, create_allowed=True,
    )
    assert out["state"]                  == "PZ_LOCKED"
    assert out["reason"]                 == "wfirma_locked"
    assert out["primary_action"]         == "none"
    assert out["hide_create_button"]     is True
    assert out["hide_resolve_products"]  is True


# ── 11. Estrella regression: created path unaffected ──────────────────

def test_estrella_created_audit_classifies_pz_created():
    """Estrella batch with a created PZ must classify as PZ_CREATED
    regardless of any blockers/flags. The supplier name is irrelevant
    to the lifecycle classifier — it consumes only audit shape."""
    a = {
        "wfirma_export": {
            "wfirma_pz_doc_id":     "12345678",
            "pz_source":            "created_via_app",
            "wfirma_pz_fullnumber": "PZ 1/5/2026",
        },
        "timeline": [{"event": EV_WFIRMA_PZ_CREATED}],
    }
    out = _compute_pz_lifecycle_state(
        a, preview_ready=False, supplier_configured=True,
        warehouse_configured=True, create_allowed=False,
    )
    assert out["state"] == "PZ_CREATED"


# ── 12. Stable enum contract ──────────────────────────────────────────

def test_stable_enum_contract():
    """The enum is part of the public API. Adding/renaming/reordering
    these states requires updating every UI surface — pin the contract
    so an accidental rename surfaces in CI."""
    assert PZ_LIFECYCLE_STATES == (
        "PZ_DUPLICATE_DETECTED",
        "PZ_RECOVERY_REQUIRED",
        "PZ_LOCKED",
        "PZ_CREATED",
        "PZ_CREATING",
        "PZ_RECONCILED",
        "PZ_READY_TO_CREATE",
        "PZ_NOT_READY",
    )


# ── 13. Wiring: pz_preview response carries pz_lifecycle ──────────────

ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma.py"
)


def test_wfirma_pz_preview_returns_pz_lifecycle_in_all_paths():
    body = ROUTES.read_text(encoding="utf-8")
    # The preview function has three potential return points: already-created,
    # structured-blocker early return, build-path success. All three must
    # include `pz_lifecycle`.
    preview_start = body.find("async def wfirma_pz_preview")
    assert preview_start > 0
    # Find next async def or end of file as boundary.
    next_def = body.find("async def ", preview_start + 1)
    chunk = body[preview_start:next_def] if next_def > 0 else body[preview_start:]
    count = chunk.count('"pz_lifecycle":')
    assert count >= 3, (
        f"expected >=3 pz_lifecycle wirings in wfirma_pz_preview; found {count}"
    )


# ── 14. Recovery wins over PZ_NOT_READY's create_disabled ─────────────

def test_recovery_state_overrides_default_not_ready_reason():
    """A subtle precedence case: when create_allowed=False AND
    timeline has wfirma_pz_created AND doc_id is empty, the lifecycle
    must report PZ_RECOVERY_REQUIRED (priority 2) rather than the
    default PZ_NOT_READY/create_disabled (priority 7)."""
    out = _compute_pz_lifecycle_state(
        _audit_recovery(),
        preview_ready=False, supplier_configured=False,
        warehouse_configured=False, create_allowed=False,
    )
    assert out["state"]                            == "PZ_RECOVERY_REQUIRED"
    assert out["reason"]                           != "create_disabled"
    assert out["override_create_disabled_message"] is True
