"""Engine-level tests for the SAMPLE_OUT lifecycle state.

Covers:
- STATES includes SAMPLE_OUT
- PROFORMA_ELIGIBLE_STATES does NOT include SAMPLE_OUT (critical
  invariant per SAMPLE_OUT_DESIGN.md §6.2)
- LEGAL_TRANSITIONS:
  - WAREHOUSE_STOCK → SAMPLE_OUT (legal with evidence)
  - SAMPLE_OUT → WAREHOUSE_STOCK (legal, no evidence gate)
  - SAMPLE_OUT → CLOSED, SALES_TRANSIT, CLIENT_DISPATCHED,
    PURCHASE_TRANSIT, DIRECT_DISPATCH_READY, SAMPLE_OUT (all forbidden)
- Evidence gate fires on:
  - missing operator
  - missing recipient_client_name
  - bad sample_reason (not in enum)
  - missing expected_return_date
  - past expected_return_date
  - malformed expected_return_date
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

from app.services import inventory_state_engine as ise
from app.services import warehouse_db as wdb


@pytest.fixture
def warehouse_db_with_engine(tmp_path):
    """Initialise a temp warehouse.db with all schemas (including
    sample_out_events from the draft migration applied inline)."""
    db_path = tmp_path / "warehouse.db"
    wdb.init_warehouse_db(db_path)
    # Apply the sample_out_events migration inline (test-only).
    import sqlite3 as _sql
    with _sql.connect(str(db_path)) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sample_out_events (
                id                     TEXT PRIMARY KEY,
                scan_code              TEXT NOT NULL,
                direction              TEXT NOT NULL,
                operator               TEXT NOT NULL DEFAULT '',
                recipient_client_name  TEXT NOT NULL DEFAULT '',
                recipient_client_id    TEXT NOT NULL DEFAULT '',
                sample_reason          TEXT NOT NULL DEFAULT '',
                expected_return_date   TEXT NOT NULL DEFAULT '',
                notes                  TEXT NOT NULL DEFAULT '',
                idempotency_key        TEXT NOT NULL DEFAULT '',
                linked_state_event_id  TEXT NOT NULL DEFAULT '',
                linked_origin_event_id TEXT NOT NULL DEFAULT '',
                occurred_at            TEXT NOT NULL,
                created_at             TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sample_out_idempotency
                ON sample_out_events (scan_code, idempotency_key)
                WHERE idempotency_key != '';
            CREATE INDEX IF NOT EXISTS idx_sample_out_recipient_open
                ON sample_out_events (recipient_client_name, direction, expected_return_date);
            CREATE INDEX IF NOT EXISTS idx_sample_out_scan_time
                ON sample_out_events (scan_code, occurred_at);
        """)
    # Force a re-check of the precheck cache so this test's fresh DB
    # is seen as having the schema.
    wdb._sample_out_schema_verified = False
    wdb._idempotency_schema_verified = False
    yield db_path


def _future(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _seed_piece(scan_code: str, batch_id: str = "B1") -> None:
    """Seed a piece into WAREHOUSE_STOCK via the engine (two transitions:
    None → PURCHASE_TRANSIT → WAREHOUSE_STOCK)."""
    ise.transition(
        scan_code=scan_code, to_state=ise.PURCHASE_TRANSIT,
        product_code="P1", design_no="D1", batch_id=batch_id,
        operator="seed",
    )
    ise.transition(
        scan_code=scan_code, to_state=ise.WAREHOUSE_STOCK,
        operator="seed",
    )


# ── Constants ────────────────────────────────────────────────────────────

def test_sample_out_in_states():
    assert "SAMPLE_OUT" in ise.STATES
    assert ise.SAMPLE_OUT == "SAMPLE_OUT"


def test_sample_out_not_in_proforma_eligible():
    """CRITICAL: SAMPLE_OUT must NEVER satisfy proforma readiness.
    A piece physically out at a client cannot back a proforma until
    it returns to WAREHOUSE_STOCK. Adding SAMPLE_OUT to
    PROFORMA_ELIGIBLE_STATES is a release-blocker bug."""
    assert ise.SAMPLE_OUT not in ise.PROFORMA_ELIGIBLE_STATES


def test_legal_transitions_out_and_return():
    assert ise.SAMPLE_OUT in ise.LEGAL_TRANSITIONS[ise.WAREHOUSE_STOCK]
    assert ise.WAREHOUSE_STOCK in ise.LEGAL_TRANSITIONS[ise.SAMPLE_OUT]


@pytest.mark.parametrize("forbidden", [
    "CLOSED", "SALES_TRANSIT", "CLIENT_DISPATCHED",
    "PURCHASE_TRANSIT", "DIRECT_DISPATCH_READY", "SAMPLE_OUT",
])
def test_forbidden_transitions_from_sample_out(forbidden):
    """Every transition out of SAMPLE_OUT except WAREHOUSE_STOCK is forbidden.
    Engine enforces by absence from LEGAL_TRANSITIONS."""
    legal = ise.LEGAL_TRANSITIONS[ise.SAMPLE_OUT]
    assert forbidden not in legal


def test_default_triggers_present():
    assert ise.DEFAULT_TRIGGER[(ise.WAREHOUSE_STOCK, ise.SAMPLE_OUT)] == "sample_out_marked"
    assert ise.DEFAULT_TRIGGER[(ise.SAMPLE_OUT, ise.WAREHOUSE_STOCK)] == "sample_returned"


# ── Evidence gate ────────────────────────────────────────────────────────

def test_transition_to_sample_out_happy_path(warehouse_db_with_engine):
    _seed_piece("S001")
    row = ise.transition(
        scan_code="S001", to_state=ise.SAMPLE_OUT,
        operator="alice",
        recipient_client_name="ACME Corp",
        expected_return_date=_future(7),
        sample_reason="customer_review",
    )
    assert row["state"] == ise.SAMPLE_OUT


def test_transition_to_sample_out_missing_operator(warehouse_db_with_engine):
    _seed_piece("S002")
    with pytest.raises(ValueError, match="operator"):
        ise.transition(
            scan_code="S002", to_state=ise.SAMPLE_OUT,
            recipient_client_name="ACME Corp",
            expected_return_date=_future(7),
            sample_reason="customer_review",
        )


def test_transition_to_sample_out_missing_recipient(warehouse_db_with_engine):
    _seed_piece("S003")
    with pytest.raises(ValueError, match="recipient_client_name"):
        ise.transition(
            scan_code="S003", to_state=ise.SAMPLE_OUT,
            operator="alice",
            expected_return_date=_future(7),
            sample_reason="customer_review",
        )


def test_transition_to_sample_out_bad_reason(warehouse_db_with_engine):
    _seed_piece("S004")
    with pytest.raises(ValueError, match="sample_reason"):
        ise.transition(
            scan_code="S004", to_state=ise.SAMPLE_OUT,
            operator="alice",
            recipient_client_name="ACME Corp",
            expected_return_date=_future(7),
            sample_reason="not_a_real_reason",
        )


def test_transition_to_sample_out_missing_return_date(warehouse_db_with_engine):
    _seed_piece("S005")
    with pytest.raises(ValueError, match="expected_return_date"):
        ise.transition(
            scan_code="S005", to_state=ise.SAMPLE_OUT,
            operator="alice",
            recipient_client_name="ACME Corp",
            sample_reason="customer_review",
        )


def test_transition_to_sample_out_past_return_date(warehouse_db_with_engine):
    _seed_piece("S006")
    with pytest.raises(ValueError, match="future"):
        ise.transition(
            scan_code="S006", to_state=ise.SAMPLE_OUT,
            operator="alice",
            recipient_client_name="ACME Corp",
            expected_return_date=_past(1),
            sample_reason="customer_review",
        )


def test_transition_to_sample_out_malformed_return_date(warehouse_db_with_engine):
    _seed_piece("S007")
    with pytest.raises(ValueError, match="ISO 8601"):
        ise.transition(
            scan_code="S007", to_state=ise.SAMPLE_OUT,
            operator="alice",
            recipient_client_name="ACME Corp",
            expected_return_date="not-a-date",
            sample_reason="customer_review",
        )


def test_transition_sample_return_no_evidence_required(warehouse_db_with_engine):
    """Returning a sample needs only scan_code + operator (the legality
    check + state-row presence). No evidence gate."""
    _seed_piece("S008")
    ise.transition(
        scan_code="S008", to_state=ise.SAMPLE_OUT,
        operator="alice",
        recipient_client_name="ACME Corp",
        expected_return_date=_future(7),
        sample_reason="customer_review",
    )
    row = ise.transition(
        scan_code="S008", to_state=ise.WAREHOUSE_STOCK,
        operator="alice",
    )
    assert row["state"] == ise.WAREHOUSE_STOCK


@pytest.mark.parametrize("bad_to", ["CLOSED", "SALES_TRANSIT", "CLIENT_DISPATCHED"])
def test_transition_from_sample_out_to_forbidden_raises(warehouse_db_with_engine, bad_to):
    _seed_piece("S009")
    ise.transition(
        scan_code="S009", to_state=ise.SAMPLE_OUT,
        operator="alice",
        recipient_client_name="ACME Corp",
        expected_return_date=_future(7),
        sample_reason="customer_review",
    )
    with pytest.raises(ValueError, match="Illegal transition"):
        ise.transition(
            scan_code="S009", to_state=bad_to,
            operator="alice",
        )


def test_transition_round_trip_history(warehouse_db_with_engine):
    """OUT → RETURN creates two state events with the right triggers."""
    _seed_piece("S010")
    ise.transition(
        scan_code="S010", to_state=ise.SAMPLE_OUT,
        operator="alice",
        recipient_client_name="ACME Corp",
        expected_return_date=_future(7),
        sample_reason="customer_review",
    )
    ise.transition(
        scan_code="S010", to_state=ise.WAREHOUSE_STOCK,
        operator="alice",
    )
    history = ise.get_history("S010")
    triggers = [h["trigger"] for h in history]
    # seed: pz_generated + warehouse_receive
    # sample-out: sample_out_marked
    # sample-return: sample_returned
    assert "sample_out_marked" in triggers
    assert "sample_returned" in triggers
