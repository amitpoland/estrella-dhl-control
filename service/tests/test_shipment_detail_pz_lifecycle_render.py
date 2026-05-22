"""Shipment-detail PZ panel rewired to pz_lifecycle.state (2026-05-22).

PR #280 added the backend `pz_lifecycle` authority. This test suite
pins the frontend rewiring (PR #281) — every PZ panel rendering
decision in `shipment-detail.html` MUST read from `pz_lifecycle.state`
as the single source. Legacy `pz_lock_status` remains as secondary
detail only, suppressed when the lifecycle is in an alarming state.

These are source-grep tests on the static HTML. Each test fails if a
future change reintroduces multi-authority rendering or removes a
lifecycle-aware branch.
"""
from __future__ import annotations

from pathlib import Path


HTML = (
    Path(__file__).resolve().parent.parent
    / "app" / "static" / "shipment-detail.html"
)


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


# ── 1. Primary authority: pz_lifecycle.state ─────────────────────────

def test_lifecycle_banner_reads_pz_lifecycle_state():
    body = _src()
    assert "pzPreview?.pz_lifecycle" in body
    assert "pzPreview.pz_lifecycle" in body
    assert "_lf.state" in body


# ── 2. Banner testid hook ────────────────────────────────────────────

def test_lifecycle_banner_has_testid():
    body = _src()
    assert 'data-testid="pz-lifecycle-banner"' in body
    assert "data-state={_lf.state}" in body


# ── 3. PZ_RECOVERY_REQUIRED branch + copy ────────────────────────────

def test_recovery_required_branch_present():
    body = _src()
    assert "'PZ_RECOVERY_REQUIRED'" in body
    assert "PZ recovery required" in body
    assert "PZ was created in wFirma, but local audit mapping is missing" in body
    assert "Confirm the existing PZ to recover" in body


# ── 4. PZ_DUPLICATE_DETECTED branch ──────────────────────────────────

def test_duplicate_detected_branch_present():
    body = _src()
    assert "'PZ_DUPLICATE_DETECTED'" in body
    assert "Duplicate wFirma PZ doc id detected" in body
    assert "duplicate_owner_batch_id" in body


# ── 5. PZ_LOCKED branch ──────────────────────────────────────────────

def test_locked_branch_present():
    body = _src()
    assert "'PZ_LOCKED'" in body
    assert "PZ locked" in body
    assert "accounting period close or operator hold" in body


# ── 6. PZ_RECONCILED branch ──────────────────────────────────────────

def test_reconciled_branch_present():
    body = _src()
    assert "'PZ_RECONCILED'" in body
    assert "PZ mapping cleared — recreate when ready" in body


# ── 7. Legacy pz_lock_status banner guarded against alarming states ──

def test_legacy_lock_status_banner_suppressed_when_lifecycle_alarming():
    """The legacy pz_lock_status banner must NOT render when pz_lifecycle
    is in one of the alarming states (RECOVERY_REQUIRED, DUPLICATE_
    DETECTED, LOCKED, RECONCILED). The lifecycle banner is the primary
    source for those; rendering both would re-introduce the
    contradictory-banner defect.
    """
    body = _src()
    # The legacy banner now has a guard that checks pz_lifecycle.state.
    assert "pzPreview?.pz_lock_status && !(" in body
    # All four alarming states are listed in the guard.
    legacy_start = body.find("pzPreview?.pz_lock_status && !(")
    assert legacy_start > 0
    chunk = body[legacy_start:legacy_start + 800]
    for state in ("PZ_RECOVERY_REQUIRED", "PZ_DUPLICATE_DETECTED",
                  "PZ_LOCKED", "PZ_RECONCILED"):
        assert state in chunk, f"alarming state {state!r} missing from legacy-banner guard"


# ── 8. Resolve Products button respects hide_resolve_products ────────

def test_resolve_products_button_respects_hide_flag():
    body = _src()
    # The Resolve Products button is wrapped in a hide_resolve_products
    # guard. Without the lifecycle field (older backend), the button
    # renders normally — graceful degradation.
    assert 'data-testid="btn-pz-resolve"' in body
    assert "pzPreview.pz_lifecycle.hide_resolve_products" in body


# ── 9. Create wFirma PZ button respects hide_create_button ───────────

def test_create_pz_button_respects_hide_flag():
    body = _src()
    assert 'data-testid="btn-pz-create"' in body
    assert "pzPreview.pz_lifecycle.hide_create_button" in body


# ── 10. ExecutePZGate suppresses "creation is disabled" when lifecycle says so ─

def test_execute_pz_gate_suppresses_create_disabled_message():
    body = _src()
    # The lifecycle override flag is read and gates the disabled chip.
    assert "override_create_disabled_message" in body
    assert "_lfSuppressCreateDisabled" in body
    # And the flag is consulted in the disabled-message branch.
    assert "if (!flagOn && !_lfSuppressCreateDisabled)" in body


# ── 11. Regression — "creation is disabled" still emitted when no override ─

def test_create_disabled_message_still_emitted_when_no_lifecycle_override():
    """When pz_lifecycle does NOT set override_create_disabled_message
    (e.g. state=PZ_NOT_READY with reason=create_disabled), the
    operator MUST still see the "PZ creation is disabled (admin
    setting)" chip — the override is opt-in. Regression pin.
    """
    body = _src()
    # The chip string is preserved verbatim.
    assert "PZ creation is disabled (admin setting)" in body


# ── 12. Confirm Existing PZ button gets primary emphasis on recovery ─

def test_confirm_existing_pz_button_promoted_to_primary_on_recovery():
    body = _src()
    # Button variant changes from "outline" (secondary) to "gold"
    # (primary) when lifecycle's primary_action is confirm_existing_pz.
    assert "'confirm_existing_pz'" in body
    assert 'data-primary={String(pzPreview?.pz_lifecycle?.primary_action === \'confirm_existing_pz\')}' in body


# ── 13. ExecutePZGate consolidates alarming states into one reason ───

def test_execute_pz_gate_consolidates_alarming_states():
    """When lifecycle is in an alarming state, the operator should see
    ONE clear directive in ExecutePZGate — not multiple contradictory
    reason chips. PR #281 routes alarming states through a dedicated
    `_lfRecoveryState` branch that emits exactly one targeted message.
    """
    body = _src()
    assert "_lfRecoveryState" in body
    assert "use Confirm Existing PZ in the wFirma Warehouse card above" in body
    assert "Duplicate wFirma PZ doc id — resolve cross-batch conflict before creating" in body


# ── 14. Graceful degradation — no lifecycle in response ──────────────

def test_renders_without_pz_lifecycle_for_older_backends():
    """When the backend doesn't yet return pz_lifecycle (older deploy),
    the panel falls back to the legacy pz_lock_status rendering. PR
    #281 entry-points use optional chaining (`pzPreview?.pz_lifecycle`)
    or a presence-check (`pzPreview?.pz_lifecycle && (...)`) so a
    missing field is null-safe.
    """
    body = _src()
    # Entry-points use optional chaining at module boundaries.
    assert body.count("pzPreview?.pz_lifecycle") >= 4, (
        "expected optional-chaining entry-points at multiple call sites"
    )
    # The dedicated banner block opens with a presence-check.
    assert "pzPreview?.pz_lifecycle && (() =>" in body
