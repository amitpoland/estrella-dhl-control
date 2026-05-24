"""Unit tests for pz_correction_lifecycle.py.

Tests the PZCorrectionLifecycle class with mocked execute_correction_option
and push_correction_to_wfirma so that no real wFirma calls or filesystem
outside tmp_path are made.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.pz_correction_state import (
    CorrectionLifecycleState,
    CorrectionLifecycleTransitionError,
)
from app.services.pz_correction_lifecycle import PZCorrectionLifecycle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BATCH_ID = "test-batch"
PATCH_EXEC = "app.services.pz_correction_lifecycle.execute_correction_option"
PATCH_PUSH = "app.services.pz_correction_lifecycle.push_correction_to_wfirma"


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    """Create a fake outputs/{BATCH_ID} directory under tmp_path."""
    bdir = tmp_path / "outputs" / BATCH_ID
    bdir.mkdir(parents=True)
    return tmp_path


def make_lc(storage_root: Path) -> PZCorrectionLifecycle:
    return PZCorrectionLifecycle(BATCH_ID, storage_root)


def make_exec_ok() -> MagicMock:
    m = MagicMock()
    m.ok    = True
    m.error = None
    return m


def make_exec_fail(error: str = "pz_rows not found") -> MagicMock:
    m = MagicMock()
    m.ok    = False
    m.error = error
    return m


def make_push_ok() -> MagicMock:
    m = MagicMock()
    m.ok     = True
    m.status = "pushed"
    m.error  = None
    return m


def make_push_fail(error: str = "wFirma 500") -> MagicMock:
    m = MagicMock()
    m.ok     = False
    m.status = "failed"
    m.error  = error
    return m


def state_file(storage_root: Path) -> Path:
    return storage_root / "outputs" / BATCH_ID / "pz_correction_lifecycle.json"


# ---------------------------------------------------------------------------
# get_or_init_state
# ---------------------------------------------------------------------------

class TestGetOrInitState:
    def test_creates_proposed_record_on_first_call(self, storage_root):
        lc     = make_lc(storage_root)
        record = lc.get_or_init_state()
        assert record.state    == CorrectionLifecycleState.PROPOSED
        assert record.batch_id == BATCH_ID

    def test_idempotent_on_subsequent_calls(self, storage_root):
        lc = make_lc(storage_root)
        r1 = lc.get_or_init_state()
        r2 = lc.get_or_init_state()
        assert r1.state == r2.state == CorrectionLifecycleState.PROPOSED

    def test_persists_to_disk(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        sf = state_file(storage_root)
        assert sf.exists()
        data = json.loads(sf.read_text(encoding="utf-8"))
        assert data["state"] == "PROPOSED"

    def test_raises_if_batch_dir_missing(self, tmp_path):
        lc = PZCorrectionLifecycle("nonexistent-batch", tmp_path)
        with pytest.raises(ValueError, match="not found"):
            lc.get_or_init_state()


# ---------------------------------------------------------------------------
# mark_reviewed
# ---------------------------------------------------------------------------

class TestMarkReviewed:
    def test_proposed_advances_to_operator_reviewed(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        record = lc.mark_reviewed("LGTM")

        assert record.state         == CorrectionLifecycleState.OPERATOR_REVIEWED
        assert record.operator_note == "LGTM"
        assert record.review_ts     is not None

    def test_persists_to_disk(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("noted")

        data = json.loads(state_file(storage_root).read_text(encoding="utf-8"))
        assert data["state"]         == "OPERATOR_REVIEWED"
        assert data["operator_note"] == "noted"

    def test_cannot_review_from_operator_reviewed(self, storage_root):
        """OPERATOR_REVIEWED -> OPERATOR_REVIEWED is not a valid transition."""
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("first review")
        with pytest.raises(CorrectionLifecycleTransitionError):
            lc.mark_reviewed("second review")


# ---------------------------------------------------------------------------
# stage_option
# ---------------------------------------------------------------------------

class TestStageOption:
    def test_operator_reviewed_advances_to_staged(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")

        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            record = lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])

        assert record.state            == CorrectionLifecycleState.STAGED
        assert record.staged_option_id == "ALIGN_TO_AUTHORITY"
        assert record.stage_ts         is not None

    def test_persists_staged_to_disk(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")

        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            lc.stage_option("SPLIT_TO_STYLE_LEVEL", "reason", [])

        data = json.loads(state_file(storage_root).read_text(encoding="utf-8"))
        assert data["state"]            == "STAGED"
        assert data["staged_option_id"] == "SPLIT_TO_STYLE_LEVEL"

    def test_state_stays_at_operator_reviewed_when_execute_fails(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")

        with patch(PATCH_EXEC, return_value=make_exec_fail("bad rows")):
            with pytest.raises(CorrectionLifecycleTransitionError, match="bad rows"):
                lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])

        data = json.loads(state_file(storage_root).read_text(encoding="utf-8"))
        assert data["state"] == "OPERATOR_REVIEWED"

    def test_cancel_and_recreate_is_blocked(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")

        with pytest.raises(CorrectionLifecycleTransitionError, match="CANCEL_AND_RECREATE"):
            lc.stage_option("CANCEL_AND_RECREATE", "reason", [])

    def test_cannot_stage_from_proposed_directly(self, storage_root):
        """PROPOSED -> STAGED is not a valid transition (must review first)."""
        lc = make_lc(storage_root)
        lc.get_or_init_state()

        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            with pytest.raises(CorrectionLifecycleTransitionError):
                lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])

    def test_re_stage_from_failed_is_allowed(self, storage_root):
        """FAILED -> STAGED is permitted (operator re-staging after push failure)."""
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")

        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])

        # Force to FAILED state by directly writing the state file
        sf = state_file(storage_root)
        data = json.loads(sf.read_text(encoding="utf-8"))
        data["state"] = "FAILED"
        sf.write_text(json.dumps(data), encoding="utf-8")

        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            record = lc.stage_option("SPLIT_TO_STYLE_LEVEL", "re-staging", [])

        assert record.state == CorrectionLifecycleState.STAGED


# ---------------------------------------------------------------------------
# reset_stage
# ---------------------------------------------------------------------------

class TestResetStage:
    def test_staged_reverts_to_operator_reviewed(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")

        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])

        record = lc.reset_stage()
        assert record.state            == CorrectionLifecycleState.OPERATOR_REVIEWED
        assert record.staged_option_id is None
        assert record.stage_ts         is None

    def test_cannot_reset_from_proposed(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        with pytest.raises(CorrectionLifecycleTransitionError):
            lc.reset_stage()

    def test_cannot_reset_from_operator_reviewed(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")
        with pytest.raises(CorrectionLifecycleTransitionError):
            lc.reset_stage()


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    def _stage(self, lc: PZCorrectionLifecycle) -> None:
        lc.get_or_init_state()
        lc.mark_reviewed("ok")
        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])

    def test_staged_advances_to_completed_on_push_success(self, storage_root):
        lc = make_lc(storage_root)
        self._stage(lc)

        with patch(PATCH_PUSH, return_value=make_push_ok()):
            record = lc.execute("commit", "key-1", "I UNDERSTAND THE IMPLICATIONS",
                                  None, "c1", "w1")

        assert record.state        == CorrectionLifecycleState.COMPLETED
        assert record.result_summary == "pushed"
        assert record.complete_ts  is not None

    def test_staged_advances_to_failed_on_push_failure(self, storage_root):
        lc = make_lc(storage_root)
        self._stage(lc)

        with patch(PATCH_PUSH, return_value=make_push_fail("wFirma 502")):
            record = lc.execute("commit", "key-1", "I UNDERSTAND THE IMPLICATIONS",
                                  None, "c1", "w1")

        assert record.state == CorrectionLifecycleState.FAILED
        assert "wFirma 502" in (record.result_summary or "")

    def test_executing_state_written_before_push(self, storage_root):
        """Verifies EXECUTING is written to disk before push_correction_to_wfirma is called."""
        lc = make_lc(storage_root)
        self._stage(lc)

        seen_states: list = []

        def _push(**kwargs):
            data = json.loads(state_file(storage_root).read_text(encoding="utf-8"))
            seen_states.append(data["state"])
            return make_push_ok()

        with patch(PATCH_PUSH, side_effect=_push):
            lc.execute("commit", "key-1", "I UNDERSTAND THE IMPLICATIONS",
                       None, "c1", "w1")

        assert "EXECUTING" in seen_states

    def test_failed_on_push_exception(self, storage_root):
        lc = make_lc(storage_root)
        self._stage(lc)

        with patch(PATCH_PUSH, side_effect=RuntimeError("network timeout")):
            with pytest.raises(RuntimeError, match="network timeout"):
                lc.execute("commit", "key-1", "I UNDERSTAND THE IMPLICATIONS",
                            None, "c1", "w1")

        data = json.loads(state_file(storage_root).read_text(encoding="utf-8"))
        assert data["state"] == "FAILED"
        assert "network timeout" in data.get("result_summary", "")

    def test_cannot_execute_from_proposed(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        with pytest.raises(CorrectionLifecycleTransitionError):
            lc.execute("r", "k", "I UNDERSTAND THE IMPLICATIONS", None, "c", "w")

    def test_cannot_execute_from_operator_reviewed(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")
        with pytest.raises(CorrectionLifecycleTransitionError):
            lc.execute("r", "k", "I UNDERSTAND THE IMPLICATIONS", None, "c", "w")


# ---------------------------------------------------------------------------
# suppress_terminal
# ---------------------------------------------------------------------------

class TestSuppressTerminal:
    def test_proposed_can_suppress(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        record = lc.suppress_terminal("abandoned")
        assert record.state              == CorrectionLifecycleState.TERMINAL_SUPPRESSED
        assert record.suppression_reason == "abandoned"
        assert record.complete_ts        is not None

    def test_operator_reviewed_can_suppress(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")
        record = lc.suppress_terminal("no longer needed")
        assert record.state == CorrectionLifecycleState.TERMINAL_SUPPRESSED

    def test_staged_can_suppress(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.mark_reviewed("ok")
        with patch(PATCH_EXEC, return_value=make_exec_ok()):
            lc.stage_option("ALIGN_TO_AUTHORITY", "reason", [])
        record = lc.suppress_terminal("cancelled by operator")
        assert record.state == CorrectionLifecycleState.TERMINAL_SUPPRESSED

    def test_terminal_suppressed_cannot_suppress_again(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.suppress_terminal("first")
        with pytest.raises(CorrectionLifecycleTransitionError):
            lc.suppress_terminal("second")

    def test_persists_to_disk(self, storage_root):
        lc = make_lc(storage_root)
        lc.get_or_init_state()
        lc.suppress_terminal("audit closure")
        data = json.loads(state_file(storage_root).read_text(encoding="utf-8"))
        assert data["state"]              == "TERMINAL_SUPPRESSED"
        assert data["suppression_reason"] == "audit closure"
