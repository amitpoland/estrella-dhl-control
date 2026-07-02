"""
test_phase_b_fold_parity.py — Phase B FOLD parity gate
(PROJECT_STATE DECISIONS "Phase B FOLD", 2026-07-03).

The Move Location capability is folded into the Inventory authority as a Move
Stock modal (Lesson M relocation). Parity rules (operator, verbatim):
no raw internal-ID paste inputs; selection from lists; behavior carried from
the page; pending-badge the missing feeds; retire the page only after parity.

This gate PINS the modal and — critically — the NO-PASTE rule as a
drop-can't-return grep (a future PR re-adding a paste input fails here).
"""
from __future__ import annotations

import re
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"


def _read(name: str) -> str:
    return (_V2 / name).read_text(encoding="utf-8", errors="replace")


def _modal_block() -> str:
    src = _read("inventory-page.jsx")
    # Start at the MS_ERROR_HINTS constants (they + msClassifyError belong to
    # the modal) and end at the InventoryPage shell.
    k = src.index("const MS_ERROR_HINTS")
    end = src.index("function InventoryPage(", k)
    return src[k:end]


# ── no-paste rule (the crux) ─────────────────────────────────────────────────

def test_modal_has_no_paste_id_input():
    """The wireframe's stock_unit PASTE box is FORBIDDEN. The modal's only
    inputs are <select> (source/dest), checkbox (pieces), textarea (note).
    A raw <input> asking for a batch/piece/SU id must never appear."""
    block = _modal_block()
    # The only <input in the modal must be type="checkbox".
    inputs = re.findall(r"<input\b[^>]*>", block)
    for tag in inputs:
        assert 'type="checkbox"' in tag, (
            f"non-checkbox <input> in the Move Stock modal (paste-box "
            f"regression — operator rule 'no raw internal-ID paste'): {tag}"
        )
    # Selection is from lists: source + destination are <select>.
    assert 'data-testid="ms-source"' in block and "<select" in block
    assert 'data-testid="ms-destination"' in block


def test_no_batch_or_piece_paste_placeholders_survived_the_port():
    """The retiring page's batch/piece text boxes must NOT reappear in the
    Inventory hub's write flow."""
    block = _modal_block()
    for forbidden in ("Batch id (e.g.", "ms-batch-input", 'placeholder="Batch',
                      "input-batch-id"):
        assert forbidden not in block, f"page paste-box survived the port: {forbidden!r}"


# ── modal structure + behavior carried over ─────────────────────────────────

def test_modal_testids_present():
    block = _modal_block()
    for tid in ("move-stock-modal", "ms-source", "ms-destination", "ms-note",
                "ms-table", "ms-row-checkbox", "ms-results", "ms-result-row",
                "ms-submit", "ms-cancel", "ms-empty", "ms-banner",
                "ms-type-wh-wh", "ms-type-stage", "ms-pending-unlocated"):
        assert tid in block, f"modal testid missing: {tid}"


def test_five_error_states_carried_over():
    block = _modal_block()
    for code in ("INVALID_INPUT", "PIECE_NOT_FOUND", "WRONG_STATE",
                 "DB_UNAVAILABLE", "MIGRATION_PENDING"):
        assert code in block, f"error state {code} not carried over from the page"


def test_sequential_per_piece_and_synthetic_disable_carried():
    block = _modal_block()
    assert "for (const code of selectedCodes)" in block, "sequential per-piece loop missing"
    assert "await window.PzApi.movePieceLocation" in block, "per-piece move missing"
    assert "crypto.randomUUID()" in block, "per-piece idempotency key missing"
    assert "synthetic" in block and "disabled={synthetic}" in block, "synthetic-disable missing"
    assert "Batch = sequential single-piece moves (backend is per-piece)" in block


def test_stage_transition_is_pending_badged_not_wired():
    block = _modal_block()
    # The 'stage' toggle option must carry pending: true (disabled, badged).
    k = block.index("testid: 'ms-type-stage'")
    seg = block[k:k + 120]
    assert "pending: true" in seg, "Stage transition toggle must be pending: true"
    assert "BACKEND-PENDING" in block and "PHASE C" in block
    # canMove must gate on wh-wh only (stage can't execute a move)
    assert "moveType === 'wh-wh'" in block


def test_unlocated_context_pending_badged():
    block = _modal_block()
    assert 'data-testid="ms-pending-unlocated"' in block
    assert "Backend-pending — Phase C" in block


# ── transports (no-paste feeds) ─────────────────────────────────────────────

def test_pz_api_has_the_two_nonpaste_feeds():
    api = _read("pz-api.js")
    assert "getWarehouseLocations:" in api
    assert "getLocationInventory:" in api
    assert "/warehouse/locations`" in api or "/warehouse/locations`)" in api
    # location_code is slash-safe (encoded per segment), never whole-id
    k = api.index("getLocationInventory:")
    assert ".split('/').map(encodeURIComponent).join('/')" in api[k:k + 300]


def test_modal_uses_only_pzapi_transports():
    block = _modal_block()
    assert "fetch(" not in block, "modal must go through PzApi, not raw fetch"
    for m in ("getWarehouseLocations", "getLocationInventory", "movePieceLocation"):
        assert f"window.PzApi.{m}" in block, f"modal must call PzApi.{m}"


# ── the action button that opens it (folded into the hub, no new page) ──────

def test_inventory_hub_hosts_the_move_stock_action():
    src = _read("inventory-page.jsx")
    assert 'data-testid="btn-open-move-stock"' in src, "hub must host the Move Stock action"
    assert "<MoveStockModal onClose=" in src, "hub must mount the modal"
