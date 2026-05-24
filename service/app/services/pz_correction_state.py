"""
pz_correction_state.py -- Lifecycle state model for PZ correction workflow.

State machine
-------------
    PROPOSED            -> OPERATOR_REVIEWED  (via mark_reviewed)
    OPERATOR_REVIEWED   -> STAGED             (via stage_option, after
                                               execute_correction_option succeeds)
    STAGED              -> OPERATOR_REVIEWED  (via reset_stage)
    STAGED              -> EXECUTING          (via execute -- start of wFirma push)
    EXECUTING           -> COMPLETED          (via execute -- wFirma push succeeded)
    EXECUTING           -> FAILED             (via execute -- wFirma push failed)
    FAILED              -> STAGED             (via stage_option -- re-stage after failure)
    ANY                 -> TERMINAL_SUPPRESSED (via suppress_terminal)

Stored as: {batch_dir}/pz_correction_lifecycle.json
Schema version: 1
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class CorrectionLifecycleState(str, Enum):
    PROPOSED            = "PROPOSED"
    OPERATOR_REVIEWED   = "OPERATOR_REVIEWED"
    STAGED              = "STAGED"
    EXECUTING           = "EXECUTING"
    COMPLETED           = "COMPLETED"
    FAILED              = "FAILED"
    TERMINAL_SUPPRESSED = "TERMINAL_SUPPRESSED"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: Dict[CorrectionLifecycleState, frozenset] = {
    CorrectionLifecycleState.PROPOSED: frozenset({
        CorrectionLifecycleState.OPERATOR_REVIEWED,
        CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    }),
    CorrectionLifecycleState.OPERATOR_REVIEWED: frozenset({
        CorrectionLifecycleState.STAGED,
        CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    }),
    CorrectionLifecycleState.STAGED: frozenset({
        CorrectionLifecycleState.OPERATOR_REVIEWED,   # reset_stage
        CorrectionLifecycleState.EXECUTING,
        CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    }),
    CorrectionLifecycleState.EXECUTING: frozenset({
        CorrectionLifecycleState.COMPLETED,
        CorrectionLifecycleState.FAILED,
        CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    }),
    CorrectionLifecycleState.COMPLETED: frozenset({
        CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    }),
    CorrectionLifecycleState.FAILED: frozenset({
        CorrectionLifecycleState.STAGED,              # re-stage after failure
        CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    }),
    CorrectionLifecycleState.TERMINAL_SUPPRESSED: frozenset(),  # terminal
}


# ---------------------------------------------------------------------------
# State record
# ---------------------------------------------------------------------------

@dataclass
class CorrectionLifecycleRecord:
    """Serialisable lifecycle state record. Written to pz_correction_lifecycle.json."""
    batch_id:           str
    state:              CorrectionLifecycleState
    staged_option_id:   Optional[str] = None
    operator_note:      Optional[str] = None
    review_ts:          Optional[str] = None   # ISO-8601 UTC
    stage_ts:           Optional[str] = None   # ISO-8601 UTC
    execute_ts:         Optional[str] = None   # ISO-8601 UTC
    complete_ts:        Optional[str] = None   # ISO-8601 UTC
    result_summary:     Optional[str] = None
    suppression_reason: Optional[str] = None
    schema_version:     int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":           self.batch_id,
            "state":              self.state.value,
            "staged_option_id":   self.staged_option_id,
            "operator_note":      self.operator_note,
            "review_ts":          self.review_ts,
            "stage_ts":           self.stage_ts,
            "execute_ts":         self.execute_ts,
            "complete_ts":        self.complete_ts,
            "result_summary":     self.result_summary,
            "suppression_reason": self.suppression_reason,
            "schema_version":     self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorrectionLifecycleRecord":
        return cls(
            batch_id=data["batch_id"],
            state=CorrectionLifecycleState(data["state"]),
            staged_option_id=data.get("staged_option_id"),
            operator_note=data.get("operator_note"),
            review_ts=data.get("review_ts"),
            stage_ts=data.get("stage_ts"),
            execute_ts=data.get("execute_ts"),
            complete_ts=data.get("complete_ts"),
            result_summary=data.get("result_summary"),
            suppression_reason=data.get("suppression_reason"),
            schema_version=data.get("schema_version", 1),
        )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class CorrectionLifecycleTransitionError(Exception):
    """Raised when a requested state transition is not permitted."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_transition_allowed(
    from_state: CorrectionLifecycleState,
    to_state:   CorrectionLifecycleState,
) -> bool:
    """Return True if from_state -> to_state is a valid transition."""
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())


def _utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
