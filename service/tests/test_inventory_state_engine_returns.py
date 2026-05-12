"""State engine tests for Phase B.2 Returns lifecycle.

Covers:
  - RETURNED_FROM_CLIENT + RETURNED_TO_PRODUCER are in STATES
  - LEGAL_TRANSITIONS contains every transition resolved in
    RETURNS_LIFECYCLE_DESIGN.md
  - Forbidden-by-absence: CLOSED stays terminal; returns states
    cannot become SAMPLE_OUT / SALES_TRANSIT / CLIENT_DISPATCHED /
    DIRECT_DISPATCH_READY / PURCHASE_TRANSIT; RETURNED_TO_PRODUCER
    cannot become CLOSED (design §3 + §4)
  - Evidence gates: RETURNED_FROM_CLIENT requires
    operator + return_reason in enum + origin_context + received_at
    not in future
  - Evidence gates: RETURNED_TO_PRODUCER requires
    operator + producer_name + (reason or dispatch_reference) +
    optional expected_resolution_date in future when given
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_state_engine as ise  # noqa: E402
from app.services import warehouse_db as wdb            # noqa: E402


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "wh.db"
    wdb.init_warehouse_db(db_path)
    # Reset state-engine schema cache between tests
    yield db_path
    wdb._db_path = None


# ── States + enums ────────────────────────────────────────────────────────

def test_states_include_both_returns_states():
    assert "RETURNED_FROM_CLIENT" in ise.STATES
    assert "RETURNED_TO_PRODUCER" in ise.STATES


def test_returned_from_client_reasons_includes_wrong_item_shipped():
    """Decided 2026-05-12 — include from day one."""
    assert "wrong_item_shipped" in ise.RETURNED_FROM_CLIENT_REASONS
    for r in ("warranty_claim", "customer_refused",
              "post_sample_review_reject", "dimension_issue",
              "quality_complaint", "other"):
        assert r in ise.RETURNED_FROM_CLIENT_REASONS


def test_returned_to_producer_reasons_set():
    for r in ("defect", "dimension_out_of_spec", "quality_reject",
              "post_inspection_reject", "recall", "other"):
        assert r in ise.RETURNED_TO_PRODUCER_REASONS


# ── Legal transitions (design §3) ─────────────────────────────────────────

def test_warehouse_stock_can_go_to_either_returns_state():
    legal = ise.LEGAL_TRANSITIONS[ise.WAREHOUSE_STOCK]
    assert ise.RETURNED_FROM_CLIENT in legal
    assert ise.RETURNED_TO_PRODUCER in legal


def test_sample_out_can_go_to_returned_from_client():
    legal = ise.LEGAL_TRANSITIONS[ise.SAMPLE_OUT]
    assert ise.RETURNED_FROM_CLIENT in legal


def test_returned_from_client_legal_successors():
    legal = ise.LEGAL_TRANSITIONS[ise.RETURNED_FROM_CLIENT]
    assert ise.WAREHOUSE_STOCK in legal
    assert ise.RETURNED_TO_PRODUCER in legal


def test_returned_to_producer_legal_successors():
    legal = ise.LEGAL_TRANSITIONS[ise.RETURNED_TO_PRODUCER]
    assert ise.WAREHOUSE_STOCK in legal
    assert ise.RETURNED_FROM_CLIENT in legal


# ── Forbidden-by-absence (design §4) ──────────────────────────────────────

def test_closed_stays_terminal():
    """No successor from CLOSED — including no shortcut from
    RETURNED_TO_PRODUCER → CLOSED."""
    assert ise.LEGAL_TRANSITIONS[ise.CLOSED] == frozenset()


def test_returned_to_producer_cannot_close_directly():
    """Operator-decided 2026-05-12: producer replacements use a new
    scan_code, not a CLOSED transition out of RETURNED_TO_PRODUCER."""
    legal = ise.LEGAL_TRANSITIONS[ise.RETURNED_TO_PRODUCER]
    assert ise.CLOSED not in legal


def test_returned_from_client_cannot_close_directly():
    legal = ise.LEGAL_TRANSITIONS[ise.RETURNED_FROM_CLIENT]
    assert ise.CLOSED not in legal


def test_returns_states_cannot_become_outbound_states():
    for src in (ise.RETURNED_FROM_CLIENT, ise.RETURNED_TO_PRODUCER):
        legal = ise.LEGAL_TRANSITIONS[src]
        for forbidden in (
            ise.SAMPLE_OUT, ise.SALES_TRANSIT,
            ise.CLIENT_DISPATCHED, ise.DIRECT_DISPATCH_READY,
            ise.PURCHASE_TRANSIT,
        ):
            assert forbidden not in legal, (
                f"{src} must not be able to become {forbidden}"
            )


def test_returned_to_producer_cannot_loop_to_itself():
    assert ise.RETURNED_TO_PRODUCER not in \
        ise.LEGAL_TRANSITIONS[ise.RETURNED_TO_PRODUCER]


def test_returned_from_client_cannot_loop_to_itself():
    assert ise.RETURNED_FROM_CLIENT not in \
        ise.LEGAL_TRANSITIONS[ise.RETURNED_FROM_CLIENT]


# ── Default triggers ──────────────────────────────────────────────────────

def test_default_triggers_present_for_returns():
    expected = {
        (ise.WAREHOUSE_STOCK,      ise.RETURNED_FROM_CLIENT):
            "returned_from_client_received",
        (ise.SAMPLE_OUT,           ise.RETURNED_FROM_CLIENT):
            "returned_from_client_received",
        (ise.WAREHOUSE_STOCK,      ise.RETURNED_TO_PRODUCER):
            "returned_to_producer_shipped",
        (ise.RETURNED_FROM_CLIENT, ise.WAREHOUSE_STOCK):
            "returned_restocked",
        (ise.RETURNED_FROM_CLIENT, ise.RETURNED_TO_PRODUCER):
            "returned_escalated_to_producer",
        (ise.RETURNED_TO_PRODUCER, ise.WAREHOUSE_STOCK):
            "returned_from_producer_restocked",
        (ise.RETURNED_TO_PRODUCER, ise.RETURNED_FROM_CLIENT):
            "returned_from_producer_to_rma",
    }
    for pair, expected_trigger in expected.items():
        assert ise.DEFAULT_TRIGGER[pair] == expected_trigger


# ── Evidence gates (design §5) ────────────────────────────────────────────

def _ymd_future(days=14):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _ymd_past(days=1):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _seed_warehouse_stock(db, scan_code: str):
    ise.transition(scan_code=scan_code, to_state=ise.PURCHASE_TRANSIT,
                    operator="op")
    ise.transition(scan_code=scan_code, to_state=ise.WAREHOUSE_STOCK,
                    operator="op")


def test_returned_from_client_evidence_required(db):
    _seed_warehouse_stock(db, "RFC-1")
    with pytest.raises(ValueError) as exc:
        ise.transition(scan_code="RFC-1",
                        to_state=ise.RETURNED_FROM_CLIENT)
    msg = str(exc.value)
    assert "operator" in msg
    assert "return_reason" in msg
    assert "origin_context" in msg
    assert "received_at" in msg


def test_returned_from_client_rejects_bad_reason(db):
    _seed_warehouse_stock(db, "RFC-2")
    with pytest.raises(ValueError) as exc:
        ise.transition(
            scan_code="RFC-2", to_state=ise.RETURNED_FROM_CLIENT,
            operator="op", return_reason="not_a_real_reason",
            origin_context="rma#1", received_at=_ymd_past(),
        )
    assert "return_reason" in str(exc.value)


def test_returned_from_client_rejects_future_received_at(db):
    _seed_warehouse_stock(db, "RFC-3")
    with pytest.raises(ValueError) as exc:
        ise.transition(
            scan_code="RFC-3", to_state=ise.RETURNED_FROM_CLIENT,
            operator="op", return_reason="warranty_claim",
            origin_context="rma#1", received_at=_ymd_future(),
        )
    assert "received_at not in the future" in str(exc.value)


def test_returned_from_client_accepts_full_evidence(db):
    _seed_warehouse_stock(db, "RFC-4")
    row = ise.transition(
        scan_code="RFC-4", to_state=ise.RETURNED_FROM_CLIENT,
        operator="op", return_reason="wrong_item_shipped",
        origin_context="rma#42", received_at=_ymd_past(),
        source_holder_name="Estrella Boutique",
    )
    assert row["state"] == ise.RETURNED_FROM_CLIENT


def test_returned_to_producer_requires_operator_and_producer(db):
    _seed_warehouse_stock(db, "RTP-1")
    with pytest.raises(ValueError) as exc:
        ise.transition(
            scan_code="RTP-1", to_state=ise.RETURNED_TO_PRODUCER,
        )
    msg = str(exc.value)
    assert "operator" in msg
    assert "producer_name" in msg


def test_returned_to_producer_requires_reason_or_dispatch_ref(db):
    _seed_warehouse_stock(db, "RTP-2")
    with pytest.raises(ValueError) as exc:
        ise.transition(
            scan_code="RTP-2", to_state=ise.RETURNED_TO_PRODUCER,
            operator="op", producer_name="ProdCo",
        )
    assert "return_reason or dispatch_reference" in str(exc.value)


def test_returned_to_producer_accepts_dispatch_reference_alone(db):
    _seed_warehouse_stock(db, "RTP-3")
    row = ise.transition(
        scan_code="RTP-3", to_state=ise.RETURNED_TO_PRODUCER,
        operator="op", producer_name="ProdCo",
        dispatch_reference="WB-12345",
    )
    assert row["state"] == ise.RETURNED_TO_PRODUCER


def test_returned_to_producer_accepts_reason_alone(db):
    _seed_warehouse_stock(db, "RTP-4")
    row = ise.transition(
        scan_code="RTP-4", to_state=ise.RETURNED_TO_PRODUCER,
        operator="op", producer_name="ProdCo",
        return_reason="defect",
    )
    assert row["state"] == ise.RETURNED_TO_PRODUCER


def test_returned_to_producer_rejects_bad_reason_when_given(db):
    _seed_warehouse_stock(db, "RTP-5")
    with pytest.raises(ValueError) as exc:
        ise.transition(
            scan_code="RTP-5", to_state=ise.RETURNED_TO_PRODUCER,
            operator="op", producer_name="ProdCo",
            return_reason="not_in_enum",
        )
    assert "return_reason" in str(exc.value)


def test_returned_to_producer_rejects_past_expected_resolution(db):
    _seed_warehouse_stock(db, "RTP-6")
    with pytest.raises(ValueError) as exc:
        ise.transition(
            scan_code="RTP-6", to_state=ise.RETURNED_TO_PRODUCER,
            operator="op", producer_name="ProdCo",
            return_reason="defect",
            expected_resolution_date=_ymd_past(),
        )
    assert "expected_resolution_date in the future" in str(exc.value)


# ── End-to-end transition legality (engine enforcement) ───────────────────

def test_illegal_transition_warehouse_to_closed_still_blocked(db):
    """Regression — pre-existing engine invariant unchanged by Phase B.2."""
    _seed_warehouse_stock(db, "ILL-1")
    with pytest.raises(ValueError) as exc:
        ise.transition(scan_code="ILL-1", to_state=ise.CLOSED,
                        operator="op")
    assert "Illegal transition" in str(exc.value)


def test_illegal_transition_rtp_to_closed_blocked(db):
    """Phase B.2 explicit: RETURNED_TO_PRODUCER → CLOSED is forbidden."""
    _seed_warehouse_stock(db, "RTP-CLOSED-1")
    ise.transition(
        scan_code="RTP-CLOSED-1", to_state=ise.RETURNED_TO_PRODUCER,
        operator="op", producer_name="ProdCo", return_reason="defect",
    )
    with pytest.raises(ValueError) as exc:
        ise.transition(scan_code="RTP-CLOSED-1", to_state=ise.CLOSED,
                        operator="op")
    assert "Illegal transition" in str(exc.value)


def test_round_trip_warehouse_rfc_warehouse(db):
    _seed_warehouse_stock(db, "RT-1")
    ise.transition(
        scan_code="RT-1", to_state=ise.RETURNED_FROM_CLIENT,
        operator="op", return_reason="warranty_claim",
        origin_context="rma#9", received_at=_ymd_past(),
    )
    ise.transition(
        scan_code="RT-1", to_state=ise.WAREHOUSE_STOCK, operator="op",
    )
    assert ise.get_state("RT-1")["state"] == ise.WAREHOUSE_STOCK


def test_escalation_rfc_to_rtp(db):
    _seed_warehouse_stock(db, "ESC-1")
    ise.transition(
        scan_code="ESC-1", to_state=ise.RETURNED_FROM_CLIENT,
        operator="op", return_reason="quality_complaint",
        origin_context="rma#11", received_at=_ymd_past(),
    )
    ise.transition(
        scan_code="ESC-1", to_state=ise.RETURNED_TO_PRODUCER,
        operator="op", producer_name="ProdCo", return_reason="quality_reject",
    )
    assert ise.get_state("ESC-1")["state"] == ise.RETURNED_TO_PRODUCER
