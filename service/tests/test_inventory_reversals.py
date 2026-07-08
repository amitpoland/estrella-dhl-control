"""test_inventory_reversals.py — Inventory Reversal authority (Package B).

Pins the forward-correction reversal authority:
    SALES_TRANSIT / CLIENT_DISPATCHED → WAREHOUSE_STOCK
via the single state writer inventory_state_engine.transition().

Terminal states (CLOSED, WRITTEN_OFF) have NO successors and are NOT reversible.

Reversals are recorded append-only in inventory_reversals, are idempotent,
role-gated, session-operatored, never write Product Master, never delete
history, and never touch accounting / wFirma / customs.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_reversal_writer as rev
from app.services import inventory_state_engine as ise
from app.services import warehouse_db as wdb


def _seed_receive_event(scan: str) -> None:
    """Insert a minimal RECEIVE movement event so DDR evidence gate passes."""
    con = sqlite3.connect(str(wdb._db_path))
    con.execute(
        "INSERT OR IGNORE INTO inventory_movement_events "
        "(id, scan_code, action, from_location, to_location, batch_id, "
        " operator, event_time, note, created_at) "
        "VALUES (?, ?, 'RECEIVE', '', 'WH-01', 'B-1', "
        " 'seed', datetime('now'), 'test seed', datetime('now'))",
        (f"evt-{scan}", scan),
    )
    con.commit()
    con.close()


def _drive_to_state(scan: str, target: str, *, pc: str = "PC-1",
                     dn: str = "DN-1", batch: str = "B-1") -> None:
    """Drive a fresh piece through the legal path to `target`."""
    if target == "CLIENT_DISPATCHED":
        ise.transition(scan_code=scan, to_state=ise.PURCHASE_TRANSIT,
                       operator="seed", product_code=pc, design_no=dn, batch_id=batch)
        _seed_receive_event(scan)
        ise.transition(scan_code=scan, to_state=ise.DIRECT_DISPATCH_READY,
                       operator="seed", customer_allocation="ALLOC-1",
                       customs_cleared=True)
        ise.transition(scan_code=scan, to_state=ise.CLIENT_DISPATCHED, operator="seed",
                       recipient_client_name="Test Client")
        return
    ise.transition(scan_code=scan, to_state=ise.PURCHASE_TRANSIT,
                   operator="seed", product_code=pc, design_no=dn, batch_id=batch)
    ise.transition(scan_code=scan, to_state=ise.WAREHOUSE_STOCK, operator="seed")
    if target == "WAREHOUSE_STOCK":
        return
    if target == "CLOSED":
        ise.transition(scan_code=scan, to_state=ise.SALES_TRANSIT, operator="seed")
        ise.transition(scan_code=scan, to_state=ise.CLOSED, operator="seed")
    elif target == "WRITTEN_OFF":
        ise.transition(scan_code=scan, to_state=ise.RETURNED_FROM_CLIENT, operator="seed",
                       return_reason="quality_complaint", origin_context="test",
                       received_at="2026-01-01T00:00:00+00:00")
        ise.transition(scan_code=scan, to_state=ise.WRITTEN_OFF, operator="seed")
    elif target == "SALES_TRANSIT":
        ise.transition(scan_code=scan, to_state=ise.SALES_TRANSIT, operator="seed")


@pytest.fixture()
def db(tmp_path):
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    return tmp_path / "warehouse.db"


# ── 1-2. happy path: each reversible transit state → WAREHOUSE_STOCK ──────────

def test_reverse_sales_transit_to_stock(db):
    _drive_to_state("SC-ST", "SALES_TRANSIT")
    r = rev.reverse_to_stock(
        scan_code="SC-ST", operator="carol", reason="wrong_invoice_link",
        idempotency_key="k3", expected_from="SALES_TRANSIT",
    )
    assert r["status"] == "reversed"
    assert r["from_state"] == "SALES_TRANSIT"
    state = ise.get_state("SC-ST")
    assert state["state"] == "WAREHOUSE_STOCK"
    rows = wdb.get_reversals("SC-ST")
    assert rows[0]["reversal_type"] == "transit"


def test_reverse_dispatched_to_stock(db):
    _drive_to_state("SC-D", "CLIENT_DISPATCHED")
    r = rev.reverse_to_stock(
        scan_code="SC-D", operator="dave", reason="cancelled_dispatch",
        idempotency_key="k4", expected_from="CLIENT_DISPATCHED",
    )
    assert r["status"] == "reversed"
    assert r["from_state"] == "CLIENT_DISPATCHED"
    state = ise.get_state("SC-D")
    assert state["state"] == "WAREHOUSE_STOCK"
    rows = wdb.get_reversals("SC-D")
    assert rows[0]["reversal_type"] == "transit"


# ── 3. idempotency: replay returns same result ─────────────────────────────────

def test_idempotency_replay(db):
    _drive_to_state("SC-IDEM", "SALES_TRANSIT")
    r1 = rev.reverse_to_stock(
        scan_code="SC-IDEM", operator="alice", reason="operator_error",
        idempotency_key="k-same", expected_from="SALES_TRANSIT",
    )
    assert r1["status"] == "reversed"
    r2 = rev.reverse_to_stock(
        scan_code="SC-IDEM", operator="alice", reason="operator_error",
        idempotency_key="k-same", expected_from="SALES_TRANSIT",
    )
    assert r2["status"] == "replayed"
    assert r2["reversal_id"] == r1["reversal_id"]
    assert len(wdb.get_reversals("SC-IDEM")) == 1


# ── 4. wrong_state: expected_from doesn't match current ───────────────────────

def test_wrong_state_mismatch(db):
    _drive_to_state("SC-WS", "SALES_TRANSIT")
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="SC-WS", operator="alice", reason="operator_error",
            idempotency_key="k6", expected_from="CLIENT_DISPATCHED",
        )
    assert exc.value.code == "WRONG_STATE"
    assert ise.get_state("SC-WS")["state"] == "SALES_TRANSIT"


# ── 5. non-reversible state → INVALID_INPUT ───────────────────────────────────

def test_non_reversible_state_rejected(db):
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="SC-NR", operator="alice", reason="operator_error",
            idempotency_key="k7", expected_from="WAREHOUSE_STOCK",
        )
    assert exc.value.code == "INVALID_INPUT"


# ── 6. bad reason → INVALID_INPUT ─────────────────────────────────────────────

def test_bad_reason_transit(db):
    _drive_to_state("SC-BRT", "SALES_TRANSIT")
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="SC-BRT", operator="alice", reason="customer_dispute",
            idempotency_key="k9", expected_from="SALES_TRANSIT",
        )
    assert exc.value.code == "INVALID_INPUT"


# ── 7. piece not found → PIECE_NOT_FOUND ──────────────────────────────────────

def test_piece_not_found(db):
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="GHOST", operator="alice", reason="operator_error",
            idempotency_key="k10", expected_from="SALES_TRANSIT",
        )
    assert exc.value.code == "PIECE_NOT_FOUND"


# ── 8. missing required fields → INVALID_INPUT ────────────────────────────────

def test_missing_scan_code(db):
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="", operator="alice", reason="operator_error",
            idempotency_key="k11", expected_from="SALES_TRANSIT",
        )
    assert exc.value.code == "INVALID_INPUT"


def test_missing_operator(db):
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="SC-X", operator="", reason="operator_error",
            idempotency_key="k12", expected_from="SALES_TRANSIT",
        )
    assert exc.value.code == "INVALID_INPUT"


# ── 9. audit trail integrity ──────────────────────────────────────────────────

def test_audit_fields_recorded(db):
    _drive_to_state("SC-AUD", "SALES_TRANSIT")
    rev.reverse_to_stock(
        scan_code="SC-AUD", operator="ops-lead", reason="operator_error",
        idempotency_key="k-aud", expected_from="SALES_TRANSIT",
        original_event_id="EVT-123",
        notes="Late-found data entry error",
    )
    rows = wdb.get_reversals("SC-AUD")
    assert len(rows) == 1
    r = rows[0]
    assert r["from_state"] == "SALES_TRANSIT"
    assert r["to_state"] == "WAREHOUSE_STOCK"
    assert r["reversal_type"] == "transit"
    assert r["reason"] == "operator_error"
    assert r["operator"] == "ops-lead"
    assert r["original_event_id"] == "EVT-123"
    assert r["notes"] == "Late-found data entry error"
    assert r["idempotency_key"] == "k-aud"


# ── 10. reversed piece can transition again ────────────────────────────────────

def test_reversed_piece_can_move_again(db):
    _drive_to_state("SC-CYCLE", "SALES_TRANSIT")
    rev.reverse_to_stock(
        scan_code="SC-CYCLE", operator="alice", reason="operator_error",
        idempotency_key="k-cycle", expected_from="SALES_TRANSIT",
    )
    assert ise.get_state("SC-CYCLE")["state"] == "WAREHOUSE_STOCK"
    ise.transition(scan_code="SC-CYCLE", to_state=ise.SALES_TRANSIT, operator="bob")
    assert ise.get_state("SC-CYCLE")["state"] == "SALES_TRANSIT"


# ── 11-12. TERMINAL PINNING: CLOSED and WRITTEN_OFF have NO successors ────────

def test_closed_has_no_successors(db):
    assert ise.LEGAL_TRANSITIONS[ise.CLOSED] == frozenset(), \
        "CLOSED must be terminal — no legal transitions out"


def test_written_off_has_no_successors(db):
    assert ise.LEGAL_TRANSITIONS[ise.WRITTEN_OFF] == frozenset(), \
        "WRITTEN_OFF must be terminal — no legal transitions out"


# ── 13-14. CLOSED / WRITTEN_OFF are not reversible ────────────────────────────

def test_closed_not_reversible(db):
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="SC-CLOSED", operator="alice", reason="operator_error",
            idempotency_key="k-closed", expected_from="CLOSED",
        )
    assert exc.value.code == "INVALID_INPUT"
    assert "CLOSED" in exc.value.message


def test_written_off_not_reversible(db):
    with pytest.raises(rev.ReversalError) as exc:
        rev.reverse_to_stock(
            scan_code="SC-WO", operator="alice", reason="operator_error",
            idempotency_key="k-wo", expected_from="WRITTEN_OFF",
        )
    assert exc.value.code == "INVALID_INPUT"
    assert "WRITTEN_OFF" in exc.value.message


# ── 15. state engine rejects transition out of terminal states ─────────────────

def test_state_engine_rejects_closed_transition(db):
    _drive_to_state("SC-TERM-C", "CLOSED")
    with pytest.raises(ValueError):
        ise.transition(scan_code="SC-TERM-C", to_state=ise.WAREHOUSE_STOCK,
                       operator="attacker")
    assert ise.get_state("SC-TERM-C")["state"] == "CLOSED"


def test_state_engine_rejects_written_off_transition(db):
    _drive_to_state("SC-TERM-W", "WRITTEN_OFF")
    with pytest.raises(ValueError):
        ise.transition(scan_code="SC-TERM-W", to_state=ise.WAREHOUSE_STOCK,
                       operator="attacker")
    assert ise.get_state("SC-TERM-W")["state"] == "WRITTEN_OFF"
