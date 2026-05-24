"""
pz_correction_lifecycle.py -- Lifecycle manager for PZ correction workflow.

Owns the state-machine transitions, disk persistence, and delegation to
execute_correction_option() and push_correction_to_wfirma().

Critical ordering invariant
----------------------------
stage_option() MUST call execute_correction_option() (local write, no wFirma)
BEFORE transitioning to STAGED.  This writes correction_execution_record.json,
which push_correction_to_wfirma() requires at Gate 5.  The state is only
written as STAGED if execute_correction_option() succeeds.

execute() calls push_correction_to_wfirma() (wFirma write).  State transitions
to EXECUTING before the push call, then to COMPLETED or FAILED depending on
the result.

CANCEL_AND_RECREATE is blocked explicitly -- see OQ1 in PROJECT_STATE.md.

No code here makes wFirma calls directly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.io import write_json_atomic
from .global_pz_execution import execute_correction_option
from .global_pz_push import push_correction_to_wfirma
from .pz_correction_state import (
    CorrectionLifecycleRecord,
    CorrectionLifecycleState,
    CorrectionLifecycleTransitionError,
    _utc_now,
    is_transition_allowed,
)


_STATE_FILE = "pz_correction_lifecycle.json"


# ---------------------------------------------------------------------------
# Storage helper
# ---------------------------------------------------------------------------

def _batch_dir(batch_id: str, storage_root: Path) -> Optional[Path]:
    """Locate batch directory. Mirrors global_pz_execution._batch_dir."""
    for sub in ("outputs", "working"):
        candidate = storage_root / sub / batch_id
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Lifecycle manager
# ---------------------------------------------------------------------------

class PZCorrectionLifecycle:
    """Manages the PZ correction lifecycle state machine for a single batch.

    All state is persisted to {batch_dir}/pz_correction_lifecycle.json via
    write_json_atomic.  get_or_init_state() is safe to call any number of
    times; it creates the record only once.

    Happy-path usage::

        lc = PZCorrectionLifecycle(batch_id, settings.storage_root)
        state = lc.get_or_init_state()                         # PROPOSED
        state = lc.mark_reviewed("Proposal looks correct")    # OPERATOR_REVIEWED
        state = lc.stage_option("ALIGN_TO_AUTHORITY",          # STAGED
                                 "Aligning to invoice",
                                 proposed_lines)
        state = lc.execute(                                    # COMPLETED
                    operator_reason="Correcting PZ",
                    idempotency_key="batch-align-20260524",
                    # confirm_understanding must match _CONFIRM_SENTINEL
                    # defined in global_pz_push.py (Gate 1 of push service).
                    confirm_understanding=(
                        "I confirm this will create a new wFirma PZ document "
                        "and cannot be undone without manual wFirma intervention"
                    ),
                    product_map=None,
                    contractor_id=settings.wfirma_supplier_contractor_id,
                    warehouse_id=settings.wfirma_warehouse_id,
                )
    """

    def __init__(self, batch_id: str, storage_root: Path) -> None:
        self.batch_id     = batch_id
        self.storage_root = storage_root

    # ── Private helpers ────────────────────────────────────────────────────────

    def _locate_batch_dir(self) -> Path:
        bdir = _batch_dir(self.batch_id, self.storage_root)
        if bdir is None:
            raise ValueError(
                f"Batch directory not found for batch_id={self.batch_id!r}. "
                "Checked outputs/ and working/ subdirectories."
            )
        return bdir

    def _state_path(self) -> Path:
        return self._locate_batch_dir() / _STATE_FILE

    def _read_state(self) -> Optional[CorrectionLifecycleRecord]:
        p = self._state_path()
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return CorrectionLifecycleRecord.from_dict(data)
        except Exception:
            return None

    def _write_state(self, record: CorrectionLifecycleRecord) -> None:
        write_json_atomic(self._state_path(), record.to_dict())

    def _assert_transition(
        self,
        record:   CorrectionLifecycleRecord,
        to_state: CorrectionLifecycleState,
    ) -> None:
        if not is_transition_allowed(record.state, to_state):
            raise CorrectionLifecycleTransitionError(
                f"Transition {record.state.value} -> {to_state.value} is not "
                f"permitted. Current state: {record.state.value}. "
                f"Valid next states: "
                f"{[s.value for s in VALID_TRANSITIONS.get(record.state, frozenset())]}"
            )

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_or_init_state(self) -> CorrectionLifecycleRecord:
        """Return the current lifecycle record, creating it as PROPOSED if absent."""
        record = self._read_state()
        if record is not None:
            return record
        record = CorrectionLifecycleRecord(
            batch_id=self.batch_id,
            state=CorrectionLifecycleState.PROPOSED,
        )
        self._write_state(record)
        return record

    def mark_reviewed(self, operator_note: str) -> CorrectionLifecycleRecord:
        """Transition PROPOSED -> OPERATOR_REVIEWED.

        Records the operator's review note and timestamp.
        """
        record = self.get_or_init_state()
        self._assert_transition(record, CorrectionLifecycleState.OPERATOR_REVIEWED)
        record.state         = CorrectionLifecycleState.OPERATOR_REVIEWED
        record.operator_note = operator_note
        record.review_ts     = _utc_now()
        self._write_state(record)
        return record

    def stage_option(
        self,
        option_id:       str,
        operator_reason: str,
        proposed_lines:  List[Any],
    ) -> CorrectionLifecycleRecord:
        """Transition OPERATOR_REVIEWED -> STAGED (or FAILED -> STAGED on re-stage).

        CRITICAL ORDERING RULE: calls execute_correction_option() BEFORE writing
        STAGED to disk.  execute_correction_option() writes
        correction_execution_record.json (local only, no wFirma).  Gate 5 of
        push_correction_to_wfirma() requires that file to exist.

        If execute_correction_option() fails, the state remains at
        OPERATOR_REVIEWED (or FAILED) -- never written as STAGED.

        CANCEL_AND_RECREATE is explicitly blocked -- see OQ1 in PROJECT_STATE.md.
        """
        record = self.get_or_init_state()
        self._assert_transition(record, CorrectionLifecycleState.STAGED)

        # CANCEL_AND_RECREATE guard -- wFirma delete capability not confirmed (OQ1)
        if option_id == "CANCEL_AND_RECREATE":
            raise CorrectionLifecycleTransitionError(
                "CANCEL_AND_RECREATE is not implemented. "
                "This option requires wFirma delete capability (OQ1 in PROJECT_STATE.md). "
                "Status: DEFERRED/MANUAL-ONLY. Contact wFirma support at pomoc@wfirma.pl."
            )

        # KEEP_CURRENT / NO_ACTION guard -- no wFirma push needed for these options.
        # Staging them would write a correction_execution_record.json that then triggers
        # a wFirma PZ create in commit -- which is the opposite of what the operator wants.
        # Direct the operator to correction-suppress to close the workflow cleanly.
        if option_id == "KEEP_CURRENT":
            raise CorrectionLifecycleTransitionError(
                "KEEP_CURRENT: the existing PZ structure is accepted as-is — "
                "no wFirma push is needed. To close this correction workflow, "
                "call POST /api/v1/pz/lineage/{batch_id}/correction-suppress."
            )
        if option_id == "NO_ACTION":
            raise CorrectionLifecycleTransitionError(
                "NO_ACTION: acknowledged, no PZ document pending — "
                "no wFirma push is needed. To close this correction workflow, "
                "call POST /api/v1/pz/lineage/{batch_id}/correction-suppress."
            )

        exec_result = execute_correction_option(
            batch_id=self.batch_id,
            option_id=option_id,
            operator_reason=operator_reason,
            proposed_lines=proposed_lines,
            storage_root=self.storage_root,
        )

        if not exec_result.ok:
            raise CorrectionLifecycleTransitionError(
                f"execute_correction_option failed, state not advanced to STAGED. "
                f"Error: {exec_result.error}"
            )

        record.state            = CorrectionLifecycleState.STAGED
        record.staged_option_id = option_id
        record.stage_ts         = _utc_now()
        self._write_state(record)
        return record

    def reset_stage(self) -> CorrectionLifecycleRecord:
        """Transition STAGED -> OPERATOR_REVIEWED.

        Allows the operator to change their selected option before committing.
        Does NOT delete correction_execution_record.json -- the next stage_option()
        call will overwrite it via execute_correction_option() idempotency.

        Only callable from STAGED -- calling from any other state raises
        CorrectionLifecycleTransitionError.  This guard is explicit because
        PROPOSED -> OPERATOR_REVIEWED is also a valid entry in the transition
        table (used by mark_reviewed), and we do not want reset_stage to
        silently succeed from PROPOSED.
        """
        record = self.get_or_init_state()
        if record.state != CorrectionLifecycleState.STAGED:
            raise CorrectionLifecycleTransitionError(
                f"reset_stage requires state STAGED, "
                f"but current state is {record.state.value}."
            )
        record.state            = CorrectionLifecycleState.OPERATOR_REVIEWED
        record.staged_option_id = None
        record.stage_ts         = None
        self._write_state(record)
        return record

    def execute(
        self,
        operator_reason:       str,
        idempotency_key:       str,
        confirm_understanding: str,
        product_map:           Optional[Dict[str, str]],
        contractor_id:         str,
        warehouse_id:          str,
    ) -> CorrectionLifecycleRecord:
        """Transition STAGED -> EXECUTING -> COMPLETED | FAILED.

        Delegates to push_correction_to_wfirma().  correction_execution_record.json
        must already exist on disk (written by stage_option / execute_correction_option).
        Gate 5 of push_correction_to_wfirma() will block if it does not.

        State sequence:
          1. Assert STAGED -> EXECUTING is valid.
          2. Write EXECUTING to disk (before the wFirma call).
          3. Call push_correction_to_wfirma().
          4. Write COMPLETED or FAILED to disk.
        """
        record = self.get_or_init_state()
        self._assert_transition(record, CorrectionLifecycleState.EXECUTING)

        # Write EXECUTING before the push call
        record.state      = CorrectionLifecycleState.EXECUTING
        record.execute_ts = _utc_now()
        self._write_state(record)

        try:
            push_result = push_correction_to_wfirma(
                batch_id=self.batch_id,
                execution_record_id=self.batch_id,
                operator_reason=operator_reason,
                idempotency_key=idempotency_key,
                confirm_understanding=confirm_understanding,
                storage_root=self.storage_root,
                contractor_id=contractor_id,
                warehouse_id=warehouse_id,
                product_map=product_map,
            )
        except Exception as exc:
            record.state          = CorrectionLifecycleState.FAILED
            record.result_summary = f"push raised exception: {exc}"
            record.complete_ts    = _utc_now()
            self._write_state(record)
            raise

        if push_result.ok or push_result.status in ("pushed", "already_pushed"):
            record.state = CorrectionLifecycleState.COMPLETED
        else:
            record.state = CorrectionLifecycleState.FAILED

        record.result_summary = push_result.error or push_result.status
        record.complete_ts    = _utc_now()
        self._write_state(record)
        return record

    def suppress_terminal(self, reason: str) -> CorrectionLifecycleRecord:
        """Transition ANY -> TERMINAL_SUPPRESSED.

        Used by operators to close out a correction workflow without pushing
        to wFirma (e.g. the correction was abandoned, or applied manually).
        """
        record = self.get_or_init_state()
        self._assert_transition(record, CorrectionLifecycleState.TERMINAL_SUPPRESSED)
        record.state              = CorrectionLifecycleState.TERMINAL_SUPPRESSED
        record.suppression_reason = reason
        record.complete_ts        = _utc_now()
        self._write_state(record)
        return record


# Re-export for transition table access in tests
from .pz_correction_state import VALID_TRANSITIONS  # noqa: E402, F401
