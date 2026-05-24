"""Unit tests for pz_correction_state.py.

Tests the state enum, transition table, serialisation round-trip,
and the is_transition_allowed helper.
"""
from __future__ import annotations

import pytest

from app.services.pz_correction_state import (
    VALID_TRANSITIONS,
    CorrectionLifecycleRecord,
    CorrectionLifecycleState,
    CorrectionLifecycleTransitionError,
    _utc_now,
    is_transition_allowed,
)


class TestValidTransitions:
    def test_all_states_have_transition_entries(self):
        """Every CorrectionLifecycleState must appear in VALID_TRANSITIONS."""
        for state in CorrectionLifecycleState:
            assert state in VALID_TRANSITIONS, (
                f"State {state!r} is missing from VALID_TRANSITIONS"
            )

    def test_terminal_suppressed_has_no_outgoing(self):
        assert len(VALID_TRANSITIONS[CorrectionLifecycleState.TERMINAL_SUPPRESSED]) == 0

    def test_proposed_can_reach_operator_reviewed(self):
        assert is_transition_allowed(
            CorrectionLifecycleState.PROPOSED,
            CorrectionLifecycleState.OPERATOR_REVIEWED,
        )

    def test_proposed_cannot_jump_to_staged(self):
        assert not is_transition_allowed(
            CorrectionLifecycleState.PROPOSED,
            CorrectionLifecycleState.STAGED,
        )

    def test_proposed_cannot_jump_to_executing(self):
        assert not is_transition_allowed(
            CorrectionLifecycleState.PROPOSED,
            CorrectionLifecycleState.EXECUTING,
        )

    def test_operator_reviewed_can_reach_staged(self):
        assert is_transition_allowed(
            CorrectionLifecycleState.OPERATOR_REVIEWED,
            CorrectionLifecycleState.STAGED,
        )

    def test_operator_reviewed_cannot_reach_executing_directly(self):
        assert not is_transition_allowed(
            CorrectionLifecycleState.OPERATOR_REVIEWED,
            CorrectionLifecycleState.EXECUTING,
        )

    def test_staged_can_reset_to_operator_reviewed(self):
        assert is_transition_allowed(
            CorrectionLifecycleState.STAGED,
            CorrectionLifecycleState.OPERATOR_REVIEWED,
        )

    def test_staged_can_reach_executing(self):
        assert is_transition_allowed(
            CorrectionLifecycleState.STAGED,
            CorrectionLifecycleState.EXECUTING,
        )

    def test_staged_cannot_reach_completed_directly(self):
        assert not is_transition_allowed(
            CorrectionLifecycleState.STAGED,
            CorrectionLifecycleState.COMPLETED,
        )

    def test_executing_can_complete(self):
        assert is_transition_allowed(
            CorrectionLifecycleState.EXECUTING,
            CorrectionLifecycleState.COMPLETED,
        )

    def test_executing_can_fail(self):
        assert is_transition_allowed(
            CorrectionLifecycleState.EXECUTING,
            CorrectionLifecycleState.FAILED,
        )

    def test_failed_can_re_stage(self):
        """FAILED -> STAGED allows re-staging after a failed push attempt."""
        assert is_transition_allowed(
            CorrectionLifecycleState.FAILED,
            CorrectionLifecycleState.STAGED,
        )

    def test_failed_cannot_reach_completed(self):
        assert not is_transition_allowed(
            CorrectionLifecycleState.FAILED,
            CorrectionLifecycleState.COMPLETED,
        )

    def test_completed_cannot_reach_staged(self):
        assert not is_transition_allowed(
            CorrectionLifecycleState.COMPLETED,
            CorrectionLifecycleState.STAGED,
        )

    def test_any_non_terminal_can_suppress(self):
        """Every non-terminal state must be able to reach TERMINAL_SUPPRESSED."""
        for state in CorrectionLifecycleState:
            if state != CorrectionLifecycleState.TERMINAL_SUPPRESSED:
                assert is_transition_allowed(
                    state,
                    CorrectionLifecycleState.TERMINAL_SUPPRESSED,
                ), f"{state!r} cannot reach TERMINAL_SUPPRESSED"

    def test_terminal_cannot_transition_to_anything(self):
        for state in CorrectionLifecycleState:
            assert not is_transition_allowed(
                CorrectionLifecycleState.TERMINAL_SUPPRESSED,
                state,
            ), f"TERMINAL_SUPPRESSED should not transition to {state!r}"


class TestCorrectionLifecycleRecordSerialisation:
    def test_round_trip_full(self):
        record = CorrectionLifecycleRecord(
            batch_id="batch-001",
            state=CorrectionLifecycleState.STAGED,
            staged_option_id="ALIGN_TO_AUTHORITY",
            operator_note="Looks correct",
            review_ts="2026-05-24T10:00:00+00:00",
            stage_ts="2026-05-24T10:05:00+00:00",
            execute_ts=None,
            complete_ts=None,
        )
        d = record.to_dict()
        restored = CorrectionLifecycleRecord.from_dict(d)

        assert restored.batch_id         == "batch-001"
        assert restored.state            == CorrectionLifecycleState.STAGED
        assert restored.staged_option_id == "ALIGN_TO_AUTHORITY"
        assert restored.operator_note    == "Looks correct"
        assert restored.review_ts        == "2026-05-24T10:00:00+00:00"
        assert restored.stage_ts         == "2026-05-24T10:05:00+00:00"
        assert restored.execute_ts       is None
        assert restored.schema_version   == 1

    def test_round_trip_minimal(self):
        record = CorrectionLifecycleRecord(
            batch_id="b1",
            state=CorrectionLifecycleState.PROPOSED,
        )
        d = record.to_dict()
        restored = CorrectionLifecycleRecord.from_dict(d)

        assert restored.batch_id         == "b1"
        assert restored.state            == CorrectionLifecycleState.PROPOSED
        assert restored.staged_option_id is None
        assert restored.operator_note    is None

    def test_from_dict_handles_missing_optional_fields(self):
        minimal = {"batch_id": "b1", "state": "OPERATOR_REVIEWED"}
        record = CorrectionLifecycleRecord.from_dict(minimal)
        assert record.state         == CorrectionLifecycleState.OPERATOR_REVIEWED
        assert record.review_ts     is None
        assert record.schema_version == 1

    def test_state_is_string_in_dict(self):
        record = CorrectionLifecycleRecord(
            batch_id="b1",
            state=CorrectionLifecycleState.COMPLETED,
        )
        d = record.to_dict()
        assert d["state"] == "COMPLETED"
        assert isinstance(d["state"], str)

    def test_all_states_round_trip(self):
        for state in CorrectionLifecycleState:
            record = CorrectionLifecycleRecord(batch_id="b", state=state)
            restored = CorrectionLifecycleRecord.from_dict(record.to_dict())
            assert restored.state == state

    def test_suppression_reason_persisted(self):
        record = CorrectionLifecycleRecord(
            batch_id="b1",
            state=CorrectionLifecycleState.TERMINAL_SUPPRESSED,
            suppression_reason="Operator abandoned correction",
        )
        restored = CorrectionLifecycleRecord.from_dict(record.to_dict())
        assert restored.suppression_reason == "Operator abandoned correction"


class TestUtcNow:
    def test_returns_string(self):
        ts = _utc_now()
        assert isinstance(ts, str)

    def test_contains_utc_offset(self):
        ts = _utc_now()
        # ISO-8601 with UTC: ends with +00:00 or Z
        assert "+00:00" in ts or ts.endswith("Z")
