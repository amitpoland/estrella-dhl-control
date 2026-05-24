# Campaign: PZ Correction Lifecycle Authority
## Single-session bootstrap -- Phases 1 + 2
## Status: PHASE 1 COMPLETE + PR A APPLIED (Phase 2 pending operator approval)
## Last updated: 2026-05-24 (PR A — sentinel fix, suppress route, doc corrections)
## Depends on: global_pz_correction.py (read-only), global_pz_push.py (write adapter)
## Blocked by: nothing -- CANCEL_AND_RECREATE is DEFERRED (see OQ1 below)

### PHASE 1 COMPLETION RECORD (2026-05-24)

Architect review corrected two design gaps before implementation:

**Gap A -- Route authority**: The campaign document originally proposed creating
`routes_pz_correction.py` with router prefix `/api/v1/upload`.  This was WRONG.
`routes_pz.py` (prefix `/api/v1`) already owns all 3 correction routes.  The
correct action is to EXTEND `routes_pz.py` with 4 new lifecycle endpoints.  No
`routes_pz_correction.py` was created.  No `main.py` change required.

**Gap B -- Ordering constraint**: The original design called `push_correction_to_wfirma()`
directly.  This would always fail at Gate 5 (missing `correction_execution_record.json`).
`stage_option()` MUST call `execute_correction_option()` first (local write, no wFirma),
which writes `correction_execution_record.json`.  Only then does `execute()` call
`push_correction_to_wfirma()`.

**Files created/modified (Phase 1):**
- `service/app/services/pz_correction_state.py` -- NEW (state enum, transition table, record)
- `service/app/services/pz_correction_lifecycle.py` -- NEW (PZCorrectionLifecycle class)
- `service/app/core/config.py` -- MODIFIED (added `pz_correction_lifecycle_enabled`)
- `service/app/api/routes_pz.py` -- MODIFIED (4 new lifecycle endpoints added)
- `service/tests/test_pz_correction_state.py` -- NEW (25 tests, all pass)
- `service/tests/test_pz_correction_lifecycle.py` -- NEW (26 tests, all pass)
- `service/tests/test_pz_correction_routes.py` -- NEW (21 tests, all pass)

**NOT created**: `routes_pz_correction.py`, changes to `main.py` (not needed)

**DEPLOYED**: 2026-05-24 — 7-agent governance gate (all CLEAR, Lead Coordinator: READY-TO-DEPLOY).
Robocopy synced 20 files to C:\PZ\app. PZService restarted. Smoke tests:
- Local health: 200 ✓
- Public health: 200 ✓
- GET /correction-state: 503 ✓ (flag off)
- pz_correction_lifecycle_enabled=False confirmed in deployed config ✓
- No startup errors in pz_stderr.log ✓

**PZ regression**: 160/160 ✓ | **Carrier suite**: 381/381 ✓

**PR A (activation blocker fixes) — 2026-05-24:**
- Sentinel mismatch corrected: tests import `_CONFIRM_SENTINEL`, docstrings updated
- suppress_terminal route added: POST `/pz/lineage/{batch_id}/correction-suppress`
- Documentation sentinel value corrected in both phase1 memory files
- 9 new tests added (suppress route + wrong-sentinel gate test via real push service)
- Total lifecycle tests: 81 (was 72)
- PR B (atomicity hardening + parallel push deprecation) still required before flag activation

---

## 0. GOVERNANCE CLOSURE NOTE -- OQ1 (read before writing a single line of code)

**OQ1 -- wFirma PZ delete API existence + inventory reversal: DEFERRED / MANUAL-ONLY**

Three-layer consensus (external docs unconfirmed + three independent codebase statements +
pinned governance regression test) establishes that `warehouse_document_p_z/delete/{id}`
does NOT exist in the known wFirma API surface. The governance test
`test_no_pz_document_mutation_path_in_wfirma_client` in
`service/tests/test_wfirma_pz_notes_workflow_rule.py` is currently PASSING and will
FAIL IMMEDIATELY if any `delete_warehouse_pz`, `cancel_warehouse_pz`, or
`"warehouse_document_p_z", "delete"` callsite is added to `wfirma_client.py`.

**This campaign contains zero CANCEL_AND_RECREATE implementation.** Sprint 3 of the
original plan is DEFERRED and lives in the Future Research Track (section 7 below).

**Do not open the OQ1 discussion again in this session.** The decision is recorded in
`PROJECT_STATE.md` DECISIONS section. The trigger to reopen is written wFirma support
confirmation from `pomoc@wfirma.pl`. Until that arrives, the current production workflow
is the correct and complete fallback:

  1. Operator deletes PZ document manually in wFirma UI
  2. Operator calls `POST /shipment/{batch_id}/wfirma/pz/clear-mapping`
     (X-Operator header required; local-audit-only, never calls wFirma)
  3. Operator re-runs the guarded PZ create path

This workflow is proven, documented, and sufficient. **Move on.**

---

## 1. CAMPAIGN SCOPE

### In scope (this session only)
- `service/app/services/pz_correction_state.py` -- NEW file [DONE Phase 1]
- `service/app/services/pz_correction_lifecycle.py` -- NEW file [DONE Phase 1]
- `service/app/api/routes_pz.py` -- EXTEND (4 new endpoints) [DONE Phase 1]
  NOTE: NOT `routes_pz_correction.py` -- see Phase 1 completion record above
- `service/app/core/config.py` -- MODIFY (add 1 flag) [DONE Phase 1]
- `service/tests/test_pz_correction_state.py` -- NEW file [DONE Phase 1]
- `service/tests/test_pz_correction_lifecycle.py` -- NEW file [DONE Phase 1]
- `service/tests/test_pz_correction_routes.py` -- NEW file [DONE Phase 1]

REMOVED from scope (architect review):
- `service/app/api/routes_pz_correction.py` -- NOT created (routes_pz.py owns authority)
- `service/app/main.py` -- NOT modified (routes_pz.py is already registered)

### Explicitly out of scope
- `wfirma_client.py` -- must not be touched (governance test would fail)
- `global_pz_push.py` -- adapter wraps it; do not modify
- `global_pz_correction.py` -- read-only; do not modify
- Any CANCEL_AND_RECREATE implementation -- DEFERRED (see section 7)
- Any wFirma delete/cancel/edit warehouse document call -- FORBIDDEN
- All Phase 8 files, V1/V2 frontend files, DHL files -- untouched

### Feature flag
All new lifecycle endpoints are gated behind `pz_correction_lifecycle_enabled: bool = False`.
The flag is `False` by default. No endpoint returns 200 unless the flag is `True` in `.env`.
This means deploying this code changes NOTHING in production until an operator explicitly
enables the flag.

---

## 2. PRE-FLIGHT

Before writing a single file, run:

```powershell
cd "C:\Users\Super Fashion\PZ APP"
make verify
```

Record the test count. All tests must pass. If any fail, stop and report -- do not proceed
with implementation until the baseline is clean.

Also verify:
```bash
python -c "from app.services.global_pz_push import push_correction_to_wfirma, _batch_dir; print('OK')"
python -c "from app.services.global_pz_correction import build_correction_proposal, CorrectionProposal; print('OK')"
```

---

## 3. PHASE 1 -- UNIVERSAL LIFECYCLE AUTHORITY

### 3A. pz_correction_state.py (NEW)

Write `service/app/services/pz_correction_state.py` with the following complete content:

```python
"""
PZ Correction Lifecycle State Models
======================================
Immutable data models for the PZ correction lifecycle state machine.

Lifecycle states:

    PROPOSED            Correction proposal has been generated and is available.
                        No operator action has been taken yet.

    OPERATOR_REVIEWED   Operator has loaded and inspected the correction proposal.
                        No option has been staged yet.

    STAGED              Operator has selected a correction option and it is ready
                        for execution. The staged option is recorded in the state
                        record. Execution has not been attempted.

    EXECUTING           A push to wFirma is in progress. Set atomically before the
                        first API call. Prevents concurrent executions.

    COMPLETED           Push succeeded. wFirma PZ document has been updated. The
                        resulting wfirma_document_id is stored in push_result_ref.

    FAILED              Push failed. The operator may re-stage (possibly choosing a
                        different option) and retry execution.

    TERMINAL_SUPPRESSED The batch reached a terminal lifecycle state (closed,
                        delivered, archived, cancelled) before or during correction.
                        No further correction actions are permitted.

Valid transitions
-----------------
    PROPOSED           -> OPERATOR_REVIEWED   (proposal endpoint called)
    OPERATOR_REVIEWED  -> STAGED              (POST /stage with selected option)
    OPERATOR_REVIEWED  -> TERMINAL_SUPPRESSED (batch goes terminal before staging)
    STAGED             -> OPERATOR_REVIEWED   (operator resets / changes selection)
    STAGED             -> EXECUTING           (POST /execute called)
    STAGED             -> TERMINAL_SUPPRESSED (batch goes terminal before execute)
    EXECUTING          -> COMPLETED           (push returned ok=True)
    EXECUTING          -> FAILED              (push returned ok=False)
    FAILED             -> STAGED              (operator re-stages after failure)
    FAILED             -> TERMINAL_SUPPRESSED (batch goes terminal after failed push)
    * any state        -> TERMINAL_SUPPRESSED (guard fires at any point)

CANCEL_AND_RECREATE: DEFERRED
------------------------------
CANCEL_AND_RECREATE is NOT a SelectedOption in this module. It will remain absent
until OQ1 is resolved by written wFirma support confirmation. See PROJECT_STATE.md
DECISIONS section "wFirma PZ Cancel/Delete Capability Audit -- DEFERRED/MANUAL-ONLY".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class CorrectionLifecycleState(str, Enum):
    """Lifecycle state of one batch's correction workflow."""
    PROPOSED            = "proposed"
    OPERATOR_REVIEWED   = "operator_reviewed"
    STAGED              = "staged"
    EXECUTING           = "executing"
    COMPLETED           = "completed"
    FAILED              = "failed"
    TERMINAL_SUPPRESSED = "terminal_suppressed"


class CorrectionLifecycleEvent(str, Enum):
    """Events that drive state transitions."""
    PROPOSAL_VIEWED    = "proposal_viewed"
    OPTION_STAGED      = "option_staged"
    STAGE_RESET        = "stage_reset"
    EXECUTE_REQUESTED  = "execute_requested"
    PUSH_SUCCEEDED     = "push_succeeded"
    PUSH_FAILED        = "push_failed"
    BATCH_TERMINAL     = "batch_terminal"


class SelectedOption(str, Enum):
    """
    Correction option that an operator has staged for execution.

    CANCEL_AND_RECREATE is intentionally absent -- DEFERRED pending OQ1.
    Only ALIGN_TO_AUTHORITY and SPLIT_TO_STYLE_LEVEL result in wFirma writes.
    KEEP_CURRENT is a valid terminal state that records an explicit no-action
    decision without any wFirma write.
    """
    ALIGN_TO_AUTHORITY   = "ALIGN_TO_AUTHORITY"
    SPLIT_TO_STYLE_LEVEL = "SPLIT_TO_STYLE_LEVEL"
    KEEP_CURRENT         = "KEEP_CURRENT"

    @property
    def requires_wfirma_write(self) -> bool:
        """Return True when execution will call wFirma API."""
        return self in (
            SelectedOption.ALIGN_TO_AUTHORITY,
            SelectedOption.SPLIT_TO_STYLE_LEVEL,
        )

    @property
    def is_no_action(self) -> bool:
        """Return True when execution is a local-only audit record."""
        return self == SelectedOption.KEEP_CURRENT


# ---------------------------------------------------------------------------
# Transition table
# (current_state, event) -> next_state
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: Dict[
    tuple[CorrectionLifecycleState, CorrectionLifecycleEvent],
    CorrectionLifecycleState,
] = {
    (CorrectionLifecycleState.PROPOSED,          CorrectionLifecycleEvent.PROPOSAL_VIEWED):   CorrectionLifecycleState.OPERATOR_REVIEWED,
    (CorrectionLifecycleState.OPERATOR_REVIEWED, CorrectionLifecycleEvent.OPTION_STAGED):     CorrectionLifecycleState.STAGED,
    (CorrectionLifecycleState.OPERATOR_REVIEWED, CorrectionLifecycleEvent.BATCH_TERMINAL):    CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    (CorrectionLifecycleState.STAGED,            CorrectionLifecycleEvent.STAGE_RESET):       CorrectionLifecycleState.OPERATOR_REVIEWED,
    (CorrectionLifecycleState.STAGED,            CorrectionLifecycleEvent.EXECUTE_REQUESTED): CorrectionLifecycleState.EXECUTING,
    (CorrectionLifecycleState.STAGED,            CorrectionLifecycleEvent.BATCH_TERMINAL):    CorrectionLifecycleState.TERMINAL_SUPPRESSED,
    (CorrectionLifecycleState.EXECUTING,         CorrectionLifecycleEvent.PUSH_SUCCEEDED):    CorrectionLifecycleState.COMPLETED,
    (CorrectionLifecycleState.EXECUTING,         CorrectionLifecycleEvent.PUSH_FAILED):       CorrectionLifecycleState.FAILED,
    (CorrectionLifecycleState.FAILED,            CorrectionLifecycleEvent.OPTION_STAGED):     CorrectionLifecycleState.STAGED,
    (CorrectionLifecycleState.FAILED,            CorrectionLifecycleEvent.BATCH_TERMINAL):    CorrectionLifecycleState.TERMINAL_SUPPRESSED,
}

# Any state can receive BATCH_TERMINAL (the entries above cover the states where
# BATCH_TERMINAL is meaningful before execution; guard code adds the rest).
_TERMINAL_OVERRIDE_STATES: frozenset[CorrectionLifecycleState] = frozenset({
    CorrectionLifecycleState.PROPOSED,
    CorrectionLifecycleState.OPERATOR_REVIEWED,
    CorrectionLifecycleState.STAGED,
    CorrectionLifecycleState.FAILED,
})

# States from which no further action is possible.
TERMINAL_STATES: frozenset[CorrectionLifecycleState] = frozenset({
    CorrectionLifecycleState.COMPLETED,
    CorrectionLifecycleState.TERMINAL_SUPPRESSED,
})


@dataclass
class LifecycleTransition:
    """Immutable record of one state transition."""
    from_state: str
    to_state:   str
    event:      str
    actor:      str
    timestamp:  str
    metadata:   Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_state": self.from_state,
            "to_state":   self.to_state,
            "event":      self.event,
            "actor":      self.actor,
            "timestamp":  self.timestamp,
            "metadata":   self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LifecycleTransition":
        return cls(
            from_state=d["from_state"],
            to_state=d["to_state"],
            event=d["event"],
            actor=d["actor"],
            timestamp=d["timestamp"],
            metadata=d.get("metadata", {}),
        )


@dataclass
class SupplierContext:
    """
    Supplier context enrichment attached to a correction state response.

    This is informational only -- it helps operators understand which supplier
    authority is driving the correction options. It does not affect state
    transitions or push logic.
    """
    supplier_name:    str
    supplier_type:    str    # "DIRECT" | "CONSOLIDATED" | "TRANSIT" | "UNKNOWN"
    authority_source: str    # "invoice" | "customs_manifest" | "warehouse" | "unknown"
    is_global_supplier: bool
    context_note:     str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supplier_name":    self.supplier_name,
            "supplier_type":    self.supplier_type,
            "authority_source": self.authority_source,
            "is_global_supplier": self.is_global_supplier,
            "context_note":     self.context_note,
        }

    @classmethod
    def unknown(cls) -> "SupplierContext":
        """Return a safe default when supplier context cannot be determined."""
        return cls(
            supplier_name="unknown",
            supplier_type="UNKNOWN",
            authority_source="unknown",
            is_global_supplier=False,
            context_note="Supplier context could not be resolved from batch audit.",
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SupplierContext":
        return cls(
            supplier_name=d.get("supplier_name", "unknown"),
            supplier_type=d.get("supplier_type", "UNKNOWN"),
            authority_source=d.get("authority_source", "unknown"),
            is_global_supplier=d.get("is_global_supplier", False),
            context_note=d.get("context_note", ""),
        )


@dataclass
class PushResultRef:
    """Lightweight reference to the outcome of a push execution."""
    ok:                 bool
    status:             str
    wfirma_document_id: str = ""
    error:              Optional[str] = None
    audit_event_id:     str = ""
    pushed_at:          str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok":                 self.ok,
            "status":             self.status,
            "wfirma_document_id": self.wfirma_document_id,
            "error":              self.error,
            "audit_event_id":     self.audit_event_id,
            "pushed_at":          self.pushed_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PushResultRef":
        return cls(
            ok=d.get("ok", False),
            status=d.get("status", "unknown"),
            wfirma_document_id=d.get("wfirma_document_id", ""),
            error=d.get("error"),
            audit_event_id=d.get("audit_event_id", ""),
            pushed_at=d.get("pushed_at", ""),
        )


@dataclass
class CorrectionStateRecord:
    """
    Complete lifecycle state record for one batch's correction workflow.

    Persisted as `pz_correction_lifecycle.json` in the batch directory.
    Written atomically via write_json_atomic. Never overwritten in-place
    (transitions append to history list, then the whole record is re-persisted).
    """
    batch_id:             str
    current_state:        CorrectionLifecycleState
    selected_option:      Optional[SelectedOption]
    supplier_context:     Optional[SupplierContext]
    push_result_ref:      Optional[PushResultRef]
    transitions:          List[LifecycleTransition]
    created_at:           str
    updated_at:           str
    idempotency_key:      str = ""    # set when option is staged; checked on execute
    operator_reason:      str = ""    # recorded at staging time
    execution_record_id:  str = ""    # correlation id set at EXECUTING transition

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":            self.batch_id,
            "current_state":       self.current_state.value,
            "selected_option":     self.selected_option.value if self.selected_option else None,
            "supplier_context":    self.supplier_context.to_dict() if self.supplier_context else None,
            "push_result_ref":     self.push_result_ref.to_dict() if self.push_result_ref else None,
            "transitions":         [t.to_dict() for t in self.transitions],
            "created_at":          self.created_at,
            "updated_at":          self.updated_at,
            "idempotency_key":     self.idempotency_key,
            "operator_reason":     self.operator_reason,
            "execution_record_id": self.execution_record_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CorrectionStateRecord":
        return cls(
            batch_id=d["batch_id"],
            current_state=CorrectionLifecycleState(d["current_state"]),
            selected_option=(
                SelectedOption(d["selected_option"])
                if d.get("selected_option")
                else None
            ),
            supplier_context=(
                SupplierContext.from_dict(d["supplier_context"])
                if d.get("supplier_context")
                else None
            ),
            push_result_ref=(
                PushResultRef.from_dict(d["push_result_ref"])
                if d.get("push_result_ref")
                else None
            ),
            transitions=[
                LifecycleTransition.from_dict(t) for t in d.get("transitions", [])
            ],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            idempotency_key=d.get("idempotency_key", ""),
            operator_reason=d.get("operator_reason", ""),
            execution_record_id=d.get("execution_record_id", ""),
        )

    @classmethod
    def new(cls, batch_id: str) -> "CorrectionStateRecord":
        """Create a fresh PROPOSED record for a batch."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            batch_id=batch_id,
            current_state=CorrectionLifecycleState.PROPOSED,
            selected_option=None,
            supplier_context=None,
            push_result_ref=None,
            transitions=[],
            created_at=now,
            updated_at=now,
        )
```

### 3B. pz_correction_lifecycle.py (NEW)

Write `service/app/services/pz_correction_lifecycle.py` with the following complete content:

```python
"""
PZ Correction Lifecycle Manager
=================================
State machine for governing the PZ correction workflow.

This module wraps the existing global_pz_push.push_correction_to_wfirma() function
with a lifecycle layer that tracks state, enforces idempotency, prevents concurrent
executions, and records a full transition history in the batch directory.

Architecture
------------
                   CorrectionProposal (read-only, from global_pz_correction)
                           |
                           v
              PZCorrectionLifecycle.stage_option()   <- operator selects an option
                           |
                           v
              PZCorrectionLifecycle.execute()         <- operator triggers execution
                           |
                           v
                push_correction_to_wfirma()           <- existing governed write path
                           |
                           v
                   CorrectionStateRecord saved to {batch_dir}/pz_correction_lifecycle.json

Idempotency
-----------
- Every call to stage_option() generates a fresh idempotency_key (UUID4).
- execute() passes this key to push_correction_to_wfirma(), which enforces
  its own at-most-once guarantee.
- If the state is already EXECUTING when execute() is called (concurrent call
  or crash recovery), the call is rejected with a 409-equivalent error.
- If the state is COMPLETED, the call is rejected with the existing push result.

CANCEL_AND_RECREATE
-------------------
Not implemented. DEFERRED pending OQ1. See PROJECT_STATE.md.

No `delete_warehouse_pz` call exists anywhere in this module.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core.logging import get_logger
from ..utils.io import write_json_atomic
from .global_pz_push import _batch_dir, push_correction_to_wfirma
from .pz_correction_state import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    _TERMINAL_OVERRIDE_STATES,
    CorrectionLifecycleEvent,
    CorrectionLifecycleState,
    CorrectionStateRecord,
    LifecycleTransition,
    PushResultRef,
    SelectedOption,
    SupplierContext,
)

_log = get_logger(__name__)

_LIFECYCLE_FILENAME = "pz_correction_lifecycle.json"


class LifecycleError(Exception):
    """Raised when a lifecycle operation is not permitted in the current state."""

    def __init__(self, message: str, current_state: str, http_status: int = 409):
        super().__init__(message)
        self.current_state = current_state
        self.http_status = http_status


class PZCorrectionLifecycle:
    """
    Manages the correction lifecycle state for a single batch.

    Usage
    -----
        lifecycle = PZCorrectionLifecycle(batch_id, storage_root)
        record = lifecycle.get_or_init_state()

        # Operator stages an option
        record = lifecycle.stage_option(
            SelectedOption.ALIGN_TO_AUTHORITY,
            actor="operator",
            operator_reason="Product codes need INV format",
        )

        # Operator executes
        record = lifecycle.execute(
            actor="operator",
            contractor_id="12345",
            warehouse_id="67890",
        )

    All methods are safe to call multiple times (idempotent reads; writes
    are guarded by state machine transitions).
    """

    def __init__(self, batch_id: str, storage_root: Path) -> None:
        self.batch_id = batch_id
        self.storage_root = storage_root
        self._batch_path: Optional[Path] = _batch_dir(batch_id, storage_root)

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def get_state(self) -> Optional[CorrectionStateRecord]:
        """
        Return the current lifecycle state record, or None if no correction
        has been initiated for this batch.
        """
        return self._load()

    def get_or_init_state(
        self,
        supplier_context: Optional[SupplierContext] = None,
    ) -> CorrectionStateRecord:
        """
        Return the current state record, creating a fresh PROPOSED record if
        none exists yet. Idempotent -- repeated calls do not change state.

        If a supplier_context is provided and the record has no supplier context
        yet, it is attached on first init only.
        """
        record = self._load()
        if record is not None:
            return record

        record = CorrectionStateRecord.new(self.batch_id)
        if supplier_context is not None:
            record.supplier_context = supplier_context
        self._save(record)
        return record

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def mark_reviewed(self, actor: str) -> CorrectionStateRecord:
        """
        Transition from PROPOSED to OPERATOR_REVIEWED.

        Called automatically by the GET /correction/proposal endpoint when an
        operator fetches the correction proposal. Idempotent if already in
        OPERATOR_REVIEWED (returns current record unchanged).
        """
        record = self._require_state()

        if record.current_state == CorrectionLifecycleState.OPERATOR_REVIEWED:
            return record  # already reviewed -- idempotent

        return self._transition(
            record, CorrectionLifecycleEvent.PROPOSAL_VIEWED, actor
        )

    def stage_option(
        self,
        option: SelectedOption,
        actor: str,
        operator_reason: str = "",
    ) -> CorrectionStateRecord:
        """
        Stage a correction option for execution.

        Valid from: OPERATOR_REVIEWED, FAILED
        Generates a fresh idempotency_key for this execution attempt.

        Parameters
        ----------
        option:
            The correction option to stage. Must not be CANCEL_AND_RECREATE
            (which does not exist in SelectedOption -- DEFERRED).
        actor:
            Operator identifier (from X-Operator header).
        operator_reason:
            Human-readable reason for choosing this option (required for
            options that trigger a wFirma write; optional for KEEP_CURRENT).
        """
        record = self._require_state()

        if record.current_state in TERMINAL_STATES:
            raise LifecycleError(
                f"Cannot stage option: batch {self.batch_id} correction is in "
                f"terminal state {record.current_state.value}.",
                current_state=record.current_state.value,
                http_status=409,
            )

        allowed_from = {
            CorrectionLifecycleState.OPERATOR_REVIEWED,
            CorrectionLifecycleState.FAILED,
        }
        if record.current_state not in allowed_from:
            raise LifecycleError(
                f"Cannot stage option from state {record.current_state.value}. "
                f"Expected one of: {', '.join(s.value for s in allowed_from)}.",
                current_state=record.current_state.value,
                http_status=409,
            )

        if option.requires_wfirma_write and not operator_reason.strip():
            raise LifecycleError(
                f"operator_reason is required when staging {option.value} "
                f"(a wFirma write will be performed on execute).",
                current_state=record.current_state.value,
                http_status=422,
            )

        if not settings.wfirma_correction_push_allowed and option.requires_wfirma_write:
            raise LifecycleError(
                "wfirma_correction_push_allowed is False in settings. "
                "Enable the flag before staging a write-path correction option.",
                current_state=record.current_state.value,
                http_status=403,
            )

        record.selected_option  = option
        record.operator_reason  = operator_reason.strip()
        record.idempotency_key  = str(uuid.uuid4())
        record.execution_record_id = ""  # cleared on re-stage

        event = (
            CorrectionLifecycleEvent.OPTION_STAGED
            if record.current_state == CorrectionLifecycleState.OPERATOR_REVIEWED
            else CorrectionLifecycleEvent.OPTION_STAGED  # FAILED -> STAGED also uses OPTION_STAGED
        )

        return self._transition(
            record,
            event,
            actor,
            metadata={
                "selected_option":  option.value,
                "operator_reason":  record.operator_reason,
                "idempotency_key":  record.idempotency_key,
            },
        )

    def reset_stage(self, actor: str) -> CorrectionStateRecord:
        """
        Reset from STAGED back to OPERATOR_REVIEWED without executing.
        Clears the staged option, reason, and idempotency key.
        """
        record = self._require_state()

        if record.current_state != CorrectionLifecycleState.STAGED:
            raise LifecycleError(
                f"Cannot reset stage from state {record.current_state.value}. "
                "Only STAGED records may be reset.",
                current_state=record.current_state.value,
                http_status=409,
            )

        record.selected_option    = None
        record.operator_reason    = ""
        record.idempotency_key    = ""
        record.execution_record_id = ""

        return self._transition(record, CorrectionLifecycleEvent.STAGE_RESET, actor)

    def execute(
        self,
        actor: str,
        contractor_id: str,
        warehouse_id: str,
        product_map: Optional[Dict[str, str]] = None,
    ) -> CorrectionStateRecord:
        """
        Execute the staged correction by calling push_correction_to_wfirma.

        Valid from: STAGED only.
        Transitions to EXECUTING before any API call, then to COMPLETED or FAILED.

        For KEEP_CURRENT: records a local audit event and transitions to COMPLETED
        without any wFirma call.

        Parameters
        ----------
        actor:
            Operator identifier.
        contractor_id:
            wFirma contractor ID to use for the PZ document.
        warehouse_id:
            wFirma warehouse ID to use for the PZ document.
        product_map:
            Optional override map {product_code -> wfirma_product_id}.
            If None, push_correction_to_wfirma will build it from the DB.
        """
        record = self._require_state()

        if record.current_state in TERMINAL_STATES:
            raise LifecycleError(
                f"Correction for {self.batch_id} is already {record.current_state.value}. "
                "No further execution is possible.",
                current_state=record.current_state.value,
                http_status=409,
            )

        if record.current_state == CorrectionLifecycleState.EXECUTING:
            raise LifecycleError(
                f"Correction for {self.batch_id} is already EXECUTING. "
                "Wait for the current execution to complete before retrying.",
                current_state=record.current_state.value,
                http_status=409,
            )

        if record.current_state != CorrectionLifecycleState.STAGED:
            raise LifecycleError(
                f"Cannot execute from state {record.current_state.value}. "
                "Stage an option first.",
                current_state=record.current_state.value,
                http_status=409,
            )

        if not record.selected_option:
            raise LifecycleError(
                "No option is staged. Call stage_option() before execute().",
                current_state=record.current_state.value,
                http_status=409,
            )

        # --- KEEP_CURRENT: local audit only, no wFirma call ---
        if record.selected_option.is_no_action:
            execution_id = str(uuid.uuid4())
            record.execution_record_id = execution_id
            record = self._transition(
                record,
                CorrectionLifecycleEvent.EXECUTE_REQUESTED,
                actor,
                metadata={"execution_record_id": execution_id},
            )
            push_ref = PushResultRef(
                ok=True,
                status="keep_current_acknowledged",
                wfirma_document_id="",
                audit_event_id=execution_id,
                pushed_at=datetime.now(timezone.utc).isoformat(),
            )
            record.push_result_ref = push_ref
            return self._transition(
                record,
                CorrectionLifecycleEvent.PUSH_SUCCEEDED,
                actor,
                metadata={"status": "keep_current_acknowledged"},
            )

        # --- ALIGN_TO_AUTHORITY / SPLIT_TO_STYLE_LEVEL: wFirma write ---
        execution_id = str(uuid.uuid4())
        record.execution_record_id = execution_id

        # Transition to EXECUTING atomically before the API call.
        record = self._transition(
            record,
            CorrectionLifecycleEvent.EXECUTE_REQUESTED,
            actor,
            metadata={"execution_record_id": execution_id},
        )

        _log.info(
            "pz_correction_lifecycle.execute: batch=%s option=%s execution_id=%s",
            self.batch_id,
            record.selected_option.value,
            execution_id,
        )

        try:
            push_result = push_correction_to_wfirma(
                batch_id=self.batch_id,
                execution_record_id=execution_id,
                operator_reason=record.operator_reason,
                idempotency_key=record.idempotency_key,
                confirm_understanding="EXECUTE_CORRECTION",
                storage_root=self.storage_root,
                contractor_id=contractor_id,
                warehouse_id=warehouse_id,
                product_map=product_map,
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("pz_correction_lifecycle.execute: push raised unexpectedly")
            push_ref = PushResultRef(
                ok=False,
                status="failed",
                error=str(exc),
                audit_event_id=execution_id,
                pushed_at=datetime.now(timezone.utc).isoformat(),
            )
            record.push_result_ref = push_ref
            return self._transition(
                record,
                CorrectionLifecycleEvent.PUSH_FAILED,
                actor,
                metadata={"error": str(exc)},
            )

        push_ref = PushResultRef(
            ok=push_result.ok,
            status=push_result.status,
            wfirma_document_id=push_result.wfirma_document_id,
            error=push_result.error,
            audit_event_id=push_result.audit_event_id,
            pushed_at=datetime.now(timezone.utc).isoformat(),
        )
        record.push_result_ref = push_ref

        if push_result.ok:
            return self._transition(
                record,
                CorrectionLifecycleEvent.PUSH_SUCCEEDED,
                actor,
                metadata={
                    "wfirma_document_id": push_result.wfirma_document_id,
                    "status":             push_result.status,
                },
            )
        else:
            return self._transition(
                record,
                CorrectionLifecycleEvent.PUSH_FAILED,
                actor,
                metadata={
                    "error":  push_result.error,
                    "status": push_result.status,
                },
            )

    def suppress_terminal(self, actor: str, reason: str = "") -> CorrectionStateRecord:
        """
        Transition to TERMINAL_SUPPRESSED because the batch has closed.

        Valid from: any non-terminal state. Idempotent if already TERMINAL_SUPPRESSED.
        """
        record = self._require_state()

        if record.current_state == CorrectionLifecycleState.TERMINAL_SUPPRESSED:
            return record

        if record.current_state in TERMINAL_STATES:
            return record  # already COMPLETED -- do not suppress a successful completion

        if record.current_state not in _TERMINAL_OVERRIDE_STATES:
            _log.warning(
                "pz_correction_lifecycle.suppress_terminal: unexpected state %s for %s",
                record.current_state.value,
                self.batch_id,
            )

        return self._transition(
            record,
            CorrectionLifecycleEvent.BATCH_TERMINAL,
            actor,
            metadata={"reason": reason},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state_path(self) -> Optional[Path]:
        """Return path to lifecycle JSON file, or None if batch dir not found."""
        if self._batch_path is None:
            # Re-probe in case the directory was created since __init__.
            self._batch_path = _batch_dir(self.batch_id, self.storage_root)
        if self._batch_path is None:
            return None
        return self._batch_path / _LIFECYCLE_FILENAME

    def _load(self) -> Optional[CorrectionStateRecord]:
        """Load the state record from disk, or return None if it does not exist."""
        path = self._get_state_path()
        if path is None or not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return CorrectionStateRecord.from_dict(data)
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "pz_correction_lifecycle._load: failed to load %s: %s", path, exc
            )
            raise LifecycleError(
                f"Could not load lifecycle state for {self.batch_id}: {exc}",
                current_state="unknown",
                http_status=500,
            ) from exc

    def _save(self, record: CorrectionStateRecord) -> None:
        """Persist the state record atomically."""
        path = self._get_state_path()
        if path is None:
            raise LifecycleError(
                f"Cannot save lifecycle state: batch directory not found for {self.batch_id}.",
                current_state=record.current_state.value,
                http_status=500,
            )
        record.updated_at = datetime.now(timezone.utc).isoformat()
        write_json_atomic(path, record.to_dict())

    def _require_state(self) -> CorrectionStateRecord:
        """Load the state record, raising 404-equivalent if not found."""
        record = self._load()
        if record is None:
            raise LifecycleError(
                f"No correction lifecycle state found for {self.batch_id}. "
                "Call GET /correction/proposal first to initialise.",
                current_state="not_found",
                http_status=404,
            )
        return record

    def _transition(
        self,
        record: CorrectionStateRecord,
        event: CorrectionLifecycleEvent,
        actor: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CorrectionStateRecord:
        """
        Apply a state transition, append to history, and persist.

        Raises LifecycleError if the (current_state, event) pair is not in
        VALID_TRANSITIONS and is not a BATCH_TERMINAL override.
        """
        current = record.current_state
        key = (current, event)

        next_state = VALID_TRANSITIONS.get(key)
        if next_state is None:
            # BATCH_TERMINAL is allowed from any non-terminal non-completed state.
            if event == CorrectionLifecycleEvent.BATCH_TERMINAL:
                next_state = CorrectionLifecycleState.TERMINAL_SUPPRESSED
            else:
                raise LifecycleError(
                    f"Transition ({current.value}, {event.value}) is not allowed. "
                    f"Current state: {current.value}.",
                    current_state=current.value,
                    http_status=409,
                )

        transition = LifecycleTransition(
            from_state=current.value,
            to_state=next_state.value,
            event=event.value,
            actor=actor,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )

        record.current_state = next_state
        record.transitions.append(transition)
        self._save(record)

        _log.info(
            "pz_correction_lifecycle: batch=%s %s -> %s (event=%s actor=%s)",
            self.batch_id,
            current.value,
            next_state.value,
            event.value,
            actor,
        )

        return record
```

### 3C. Config addition

Add exactly one line to the wFirma flag block in `service/app/core/config.py` after the line
`wfirma_correction_push_allowed: bool = Field(default=False)`:

```python
    pz_correction_lifecycle_enabled: bool = Field(
        default=False,
        description=(
            "Gates all /pz/correction/lifecycle endpoints. "
            "Set True in .env to enable the correction lifecycle API. "
            "Has no effect on existing /pz_create or /pz/clear-mapping paths."
        ),
    )
```

### 3D. Phase 1 Tests

Write `service/tests/test_pz_correction_state.py`:

```python
"""
Tests for pz_correction_state.py -- state model and transition table.
"""
from __future__ import annotations

import pytest
from app.services.pz_correction_state import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    CorrectionLifecycleEvent,
    CorrectionLifecycleState,
    CorrectionStateRecord,
    LifecycleTransition,
    PushResultRef,
    SelectedOption,
    SupplierContext,
)


# ---------------------------------------------------------------------------
# SelectedOption
# ---------------------------------------------------------------------------

class TestSelectedOption:
    def test_align_requires_wfirma_write(self):
        assert SelectedOption.ALIGN_TO_AUTHORITY.requires_wfirma_write is True

    def test_split_requires_wfirma_write(self):
        assert SelectedOption.SPLIT_TO_STYLE_LEVEL.requires_wfirma_write is True

    def test_keep_current_no_write(self):
        assert SelectedOption.KEEP_CURRENT.requires_wfirma_write is False

    def test_keep_current_is_no_action(self):
        assert SelectedOption.KEEP_CURRENT.is_no_action is True

    def test_align_not_no_action(self):
        assert SelectedOption.ALIGN_TO_AUTHORITY.is_no_action is False

    def test_cancel_and_recreate_not_present(self):
        """CANCEL_AND_RECREATE must not exist -- it is DEFERRED per OQ1."""
        option_values = {o.value for o in SelectedOption}
        assert "CANCEL_AND_RECREATE" not in option_values, (
            "CANCEL_AND_RECREATE must remain DEFERRED until OQ1 is resolved. "
            "See PROJECT_STATE.md DECISIONS section."
        )


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS completeness
# ---------------------------------------------------------------------------

class TestTransitionTable:
    def test_proposed_to_reviewed(self):
        key = (CorrectionLifecycleState.PROPOSED, CorrectionLifecycleEvent.PROPOSAL_VIEWED)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.OPERATOR_REVIEWED

    def test_reviewed_to_staged(self):
        key = (CorrectionLifecycleState.OPERATOR_REVIEWED, CorrectionLifecycleEvent.OPTION_STAGED)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.STAGED

    def test_staged_to_executing(self):
        key = (CorrectionLifecycleState.STAGED, CorrectionLifecycleEvent.EXECUTE_REQUESTED)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.EXECUTING

    def test_executing_to_completed(self):
        key = (CorrectionLifecycleState.EXECUTING, CorrectionLifecycleEvent.PUSH_SUCCEEDED)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.COMPLETED

    def test_executing_to_failed(self):
        key = (CorrectionLifecycleState.EXECUTING, CorrectionLifecycleEvent.PUSH_FAILED)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.FAILED

    def test_failed_to_staged(self):
        key = (CorrectionLifecycleState.FAILED, CorrectionLifecycleEvent.OPTION_STAGED)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.STAGED

    def test_staged_reset_to_reviewed(self):
        key = (CorrectionLifecycleState.STAGED, CorrectionLifecycleEvent.STAGE_RESET)
        assert VALID_TRANSITIONS[key] == CorrectionLifecycleState.OPERATOR_REVIEWED

    def test_terminal_states_immutable(self):
        for terminal in TERMINAL_STATES:
            for event in CorrectionLifecycleEvent:
                key = (terminal, event)
                # No valid forward transition from a terminal state (except BATCH_TERMINAL
                # which the lifecycle handles via override, not via VALID_TRANSITIONS).
                assert key not in VALID_TRANSITIONS, (
                    f"Terminal state {terminal.value} must not have forward transitions "
                    f"in VALID_TRANSITIONS. Found: {key}"
                )

    def test_no_cancel_and_recreate_transition(self):
        """Guard: no CANCEL_AND_RECREATE event or state appears in the table."""
        for (state, event), next_state in VALID_TRANSITIONS.items():
            assert "cancel" not in state.value.lower()
            assert "cancel" not in event.value.lower()
            assert "cancel" not in next_state.value.lower()


# ---------------------------------------------------------------------------
# CorrectionStateRecord serialization round-trip
# ---------------------------------------------------------------------------

class TestStateRecordSerialization:
    def test_new_record_roundtrip(self):
        record = CorrectionStateRecord.new("BATCH_001")
        assert record.current_state == CorrectionLifecycleState.PROPOSED
        assert record.selected_option is None
        assert record.transitions == []

        d = record.to_dict()
        restored = CorrectionStateRecord.from_dict(d)
        assert restored.batch_id == "BATCH_001"
        assert restored.current_state == CorrectionLifecycleState.PROPOSED
        assert restored.selected_option is None

    def test_record_with_option_roundtrip(self):
        record = CorrectionStateRecord.new("BATCH_002")
        record.selected_option = SelectedOption.ALIGN_TO_AUTHORITY
        record.idempotency_key = "test-key-123"
        record.operator_reason = "Align product codes"

        d = record.to_dict()
        restored = CorrectionStateRecord.from_dict(d)
        assert restored.selected_option == SelectedOption.ALIGN_TO_AUTHORITY
        assert restored.idempotency_key == "test-key-123"
        assert restored.operator_reason == "Align product codes"

    def test_record_with_transition_roundtrip(self):
        record = CorrectionStateRecord.new("BATCH_003")
        record.transitions.append(LifecycleTransition(
            from_state="proposed",
            to_state="operator_reviewed",
            event="proposal_viewed",
            actor="test-operator",
            timestamp="2026-05-24T12:00:00+00:00",
            metadata={"note": "test"},
        ))

        d = record.to_dict()
        restored = CorrectionStateRecord.from_dict(d)
        assert len(restored.transitions) == 1
        t = restored.transitions[0]
        assert t.from_state == "proposed"
        assert t.actor == "test-operator"
        assert t.metadata == {"note": "test"}

    def test_record_with_push_result_roundtrip(self):
        record = CorrectionStateRecord.new("BATCH_004")
        record.push_result_ref = PushResultRef(
            ok=True,
            status="pushed",
            wfirma_document_id="doc-999",
            audit_event_id="evt-abc",
            pushed_at="2026-05-24T12:01:00+00:00",
        )

        d = record.to_dict()
        restored = CorrectionStateRecord.from_dict(d)
        assert restored.push_result_ref is not None
        assert restored.push_result_ref.ok is True
        assert restored.push_result_ref.wfirma_document_id == "doc-999"

    def test_supplier_context_roundtrip(self):
        ctx = SupplierContext(
            supplier_name="Test Supplier",
            supplier_type="DIRECT",
            authority_source="invoice",
            is_global_supplier=True,
            context_note="From invoice line authority",
        )
        d = ctx.to_dict()
        restored = SupplierContext.from_dict(d)
        assert restored.supplier_name == "Test Supplier"
        assert restored.supplier_type == "DIRECT"
        assert restored.is_global_supplier is True

    def test_supplier_context_unknown_factory(self):
        ctx = SupplierContext.unknown()
        assert ctx.supplier_name == "unknown"
        assert ctx.supplier_type == "UNKNOWN"
        assert ctx.is_global_supplier is False
```

Write `service/tests/test_pz_correction_lifecycle.py`:

```python
"""
Tests for pz_correction_lifecycle.py -- state machine operations.

All tests use a tmp_path fixture so no real batch directory is required.
The write path (push_correction_to_wfirma) is mocked in all execute() tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.services.pz_correction_lifecycle import (
    LifecycleError,
    PZCorrectionLifecycle,
)
from app.services.pz_correction_state import (
    CorrectionLifecycleState,
    CorrectionStateRecord,
    SelectedOption,
    SupplierContext,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def batch_id() -> str:
    return "SHIPMENT_TEST_2026-05_abc12345"


@pytest.fixture
def storage_root(tmp_path: Path, batch_id: str) -> Path:
    """Create a minimal batch directory structure under tmp_path."""
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def lifecycle(batch_id: str, storage_root: Path) -> PZCorrectionLifecycle:
    return PZCorrectionLifecycle(batch_id, storage_root)


@pytest.fixture
def mock_push_ok() -> MagicMock:
    result = MagicMock()
    result.ok = True
    result.status = "pushed"
    result.wfirma_document_id = "wf-doc-555"
    result.error = None
    result.audit_event_id = "evt-test-ok"
    return result


@pytest.fixture
def mock_push_fail() -> MagicMock:
    result = MagicMock()
    result.ok = False
    result.status = "failed"
    result.wfirma_document_id = ""
    result.error = "wFirma returned non-OK status"
    result.audit_event_id = "evt-test-fail"
    return result


# ---------------------------------------------------------------------------
# get_or_init_state
# ---------------------------------------------------------------------------

class TestGetOrInitState:
    def test_creates_proposed_on_first_call(self, lifecycle: PZCorrectionLifecycle):
        record = lifecycle.get_or_init_state()
        assert record.current_state == CorrectionLifecycleState.PROPOSED
        assert record.selected_option is None
        assert record.transitions == []

    def test_idempotent_on_second_call(self, lifecycle: PZCorrectionLifecycle):
        r1 = lifecycle.get_or_init_state()
        r2 = lifecycle.get_or_init_state()
        assert r1.created_at == r2.created_at
        assert r2.current_state == CorrectionLifecycleState.PROPOSED

    def test_persists_to_disk(self, lifecycle: PZCorrectionLifecycle, batch_id: str, storage_root: Path):
        lifecycle.get_or_init_state()
        path = storage_root / "outputs" / batch_id / "pz_correction_lifecycle.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["batch_id"] == batch_id
        assert data["current_state"] == "proposed"

    def test_attaches_supplier_context_on_init(self, lifecycle: PZCorrectionLifecycle):
        ctx = SupplierContext(
            supplier_name="Mumbai Gems",
            supplier_type="DIRECT",
            authority_source="invoice",
            is_global_supplier=True,
        )
        record = lifecycle.get_or_init_state(supplier_context=ctx)
        assert record.supplier_context is not None
        assert record.supplier_context.supplier_name == "Mumbai Gems"

    def test_does_not_overwrite_existing_supplier_context(self, lifecycle: PZCorrectionLifecycle):
        ctx1 = SupplierContext("S1", "DIRECT", "invoice", True)
        lifecycle.get_or_init_state(supplier_context=ctx1)
        ctx2 = SupplierContext("S2", "TRANSIT", "customs_manifest", False)
        record = lifecycle.get_or_init_state(supplier_context=ctx2)
        # Existing record should not be overwritten
        assert record.supplier_context.supplier_name == "S1"


# ---------------------------------------------------------------------------
# mark_reviewed
# ---------------------------------------------------------------------------

class TestMarkReviewed:
    def test_proposed_to_reviewed(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        record = lifecycle.mark_reviewed("operator")
        assert record.current_state == CorrectionLifecycleState.OPERATOR_REVIEWED
        assert len(record.transitions) == 1
        assert record.transitions[0].event == "proposal_viewed"

    def test_idempotent_if_already_reviewed(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        r1 = lifecycle.mark_reviewed("operator")
        r2 = lifecycle.mark_reviewed("operator")
        # Should not append a second transition
        assert len(r2.transitions) == 1
        assert r2.current_state == CorrectionLifecycleState.OPERATOR_REVIEWED


# ---------------------------------------------------------------------------
# stage_option
# ---------------------------------------------------------------------------

class TestStageOption:
    @pytest.fixture(autouse=True)
    def _setup_reviewed(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        lifecycle.mark_reviewed("operator")

    def test_stage_align_to_authority(self, lifecycle: PZCorrectionLifecycle):
        with patch("app.services.pz_correction_lifecycle.settings") as mock_settings:
            mock_settings.wfirma_correction_push_allowed = True
            record = lifecycle.stage_option(
                SelectedOption.ALIGN_TO_AUTHORITY,
                actor="operator",
                operator_reason="Product codes need INV format",
            )
        assert record.current_state == CorrectionLifecycleState.STAGED
        assert record.selected_option == SelectedOption.ALIGN_TO_AUTHORITY
        assert record.idempotency_key != ""
        assert record.operator_reason == "Product codes need INV format"

    def test_stage_keep_current_no_reason_required(self, lifecycle: PZCorrectionLifecycle):
        record = lifecycle.stage_option(
            SelectedOption.KEEP_CURRENT,
            actor="operator",
        )
        assert record.current_state == CorrectionLifecycleState.STAGED
        assert record.selected_option == SelectedOption.KEEP_CURRENT

    def test_stage_write_option_requires_reason(self, lifecycle: PZCorrectionLifecycle):
        with patch("app.services.pz_correction_lifecycle.settings") as mock_settings:
            mock_settings.wfirma_correction_push_allowed = True
            with pytest.raises(LifecycleError) as exc_info:
                lifecycle.stage_option(
                    SelectedOption.ALIGN_TO_AUTHORITY,
                    actor="operator",
                    operator_reason="",
                )
        assert exc_info.value.http_status == 422

    def test_stage_blocked_if_flag_disabled(self, lifecycle: PZCorrectionLifecycle):
        with patch("app.services.pz_correction_lifecycle.settings") as mock_settings:
            mock_settings.wfirma_correction_push_allowed = False
            with pytest.raises(LifecycleError) as exc_info:
                lifecycle.stage_option(
                    SelectedOption.ALIGN_TO_AUTHORITY,
                    actor="operator",
                    operator_reason="reason",
                )
        assert exc_info.value.http_status == 403

    def test_re_stage_after_failure(self, lifecycle: PZCorrectionLifecycle, mock_push_fail: MagicMock):
        with patch("app.services.pz_correction_lifecycle.settings") as mock_settings:
            mock_settings.wfirma_correction_push_allowed = True
            lifecycle.stage_option(
                SelectedOption.ALIGN_TO_AUTHORITY, "op", "reason"
            )
        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma",
            return_value=mock_push_fail,
        ):
            lifecycle.execute("op", "contractor-1", "wh-1")

        # Re-stage from FAILED
        with patch("app.services.pz_correction_lifecycle.settings") as mock_settings:
            mock_settings.wfirma_correction_push_allowed = True
            record = lifecycle.stage_option(
                SelectedOption.SPLIT_TO_STYLE_LEVEL, "op", "split instead"
            )
        assert record.current_state == CorrectionLifecycleState.STAGED
        assert record.selected_option == SelectedOption.SPLIT_TO_STYLE_LEVEL


# ---------------------------------------------------------------------------
# reset_stage
# ---------------------------------------------------------------------------

class TestResetStage:
    def test_reset_staged_to_reviewed(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        lifecycle.mark_reviewed("op")
        lifecycle.stage_option(SelectedOption.KEEP_CURRENT, "op")
        record = lifecycle.reset_stage("op")
        assert record.current_state == CorrectionLifecycleState.OPERATOR_REVIEWED
        assert record.selected_option is None
        assert record.idempotency_key == ""

    def test_reset_from_non_staged_raises(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        lifecycle.mark_reviewed("op")
        with pytest.raises(LifecycleError) as exc_info:
            lifecycle.reset_stage("op")
        assert exc_info.value.http_status == 409


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    def _stage(self, lifecycle: PZCorrectionLifecycle, option: SelectedOption = SelectedOption.KEEP_CURRENT):
        lifecycle.get_or_init_state()
        lifecycle.mark_reviewed("op")
        if option.requires_wfirma_write:
            with patch("app.services.pz_correction_lifecycle.settings") as mock_settings:
                mock_settings.wfirma_correction_push_allowed = True
                lifecycle.stage_option(option, "op", "reason for write")
        else:
            lifecycle.stage_option(option, "op")

    def test_keep_current_completes_without_push(self, lifecycle: PZCorrectionLifecycle):
        self._stage(lifecycle, SelectedOption.KEEP_CURRENT)
        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma"
        ) as mock_push:
            record = lifecycle.execute("op", "c-1", "wh-1")
        mock_push.assert_not_called()
        assert record.current_state == CorrectionLifecycleState.COMPLETED
        assert record.push_result_ref is not None
        assert record.push_result_ref.status == "keep_current_acknowledged"

    def test_align_calls_push_and_completes(
        self, lifecycle: PZCorrectionLifecycle, mock_push_ok: MagicMock
    ):
        self._stage(lifecycle, SelectedOption.ALIGN_TO_AUTHORITY)
        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma",
            return_value=mock_push_ok,
        ):
            record = lifecycle.execute("op", "c-1", "wh-1")
        assert record.current_state == CorrectionLifecycleState.COMPLETED
        assert record.push_result_ref.ok is True
        assert record.push_result_ref.wfirma_document_id == "wf-doc-555"

    def test_push_failure_transitions_to_failed(
        self, lifecycle: PZCorrectionLifecycle, mock_push_fail: MagicMock
    ):
        self._stage(lifecycle, SelectedOption.ALIGN_TO_AUTHORITY)
        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma",
            return_value=mock_push_fail,
        ):
            record = lifecycle.execute("op", "c-1", "wh-1")
        assert record.current_state == CorrectionLifecycleState.FAILED
        assert record.push_result_ref.ok is False
        assert "wFirma returned non-OK status" in record.push_result_ref.error

    def test_execute_on_completed_raises(self, lifecycle: PZCorrectionLifecycle):
        self._stage(lifecycle, SelectedOption.KEEP_CURRENT)
        lifecycle.execute("op", "c-1", "wh-1")
        with pytest.raises(LifecycleError) as exc_info:
            lifecycle.execute("op", "c-1", "wh-1")
        assert exc_info.value.http_status == 409

    def test_execute_without_staging_raises(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        lifecycle.mark_reviewed("op")
        with pytest.raises(LifecycleError) as exc_info:
            lifecycle.execute("op", "c-1", "wh-1")
        assert exc_info.value.http_status == 409

    def test_transition_history_is_complete(
        self, lifecycle: PZCorrectionLifecycle, mock_push_ok: MagicMock
    ):
        self._stage(lifecycle, SelectedOption.ALIGN_TO_AUTHORITY)
        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma",
            return_value=mock_push_ok,
        ):
            record = lifecycle.execute("op", "c-1", "wh-1")
        events = [t.event for t in record.transitions]
        # proposed -> reviewed -> staged -> executing -> completed
        assert "proposal_viewed" in events
        assert "option_staged" in events
        assert "execute_requested" in events
        assert "push_succeeded" in events

    def test_push_exception_transitions_to_failed(self, lifecycle: PZCorrectionLifecycle):
        self._stage(lifecycle, SelectedOption.ALIGN_TO_AUTHORITY)
        with patch(
            "app.services.pz_correction_lifecycle.push_correction_to_wfirma",
            side_effect=RuntimeError("unexpected push error"),
        ):
            record = lifecycle.execute("op", "c-1", "wh-1")
        assert record.current_state == CorrectionLifecycleState.FAILED
        assert "unexpected push error" in record.push_result_ref.error


# ---------------------------------------------------------------------------
# suppress_terminal
# ---------------------------------------------------------------------------

class TestSuppressTerminal:
    def test_any_state_can_be_suppressed(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        record = lifecycle.suppress_terminal("system", reason="Batch closed by operator")
        assert record.current_state == CorrectionLifecycleState.TERMINAL_SUPPRESSED

    def test_idempotent_if_already_suppressed(self, lifecycle: PZCorrectionLifecycle):
        lifecycle.get_or_init_state()
        lifecycle.suppress_terminal("system")
        r2 = lifecycle.suppress_terminal("system")
        assert r2.current_state == CorrectionLifecycleState.TERMINAL_SUPPRESSED


# ---------------------------------------------------------------------------
# Batch directory not found
# ---------------------------------------------------------------------------

class TestBatchDirNotFound:
    def test_get_state_returns_none_if_no_dir(self, batch_id: str, tmp_path: Path):
        lifecycle = PZCorrectionLifecycle(batch_id, tmp_path / "nonexistent")
        assert lifecycle.get_state() is None

    def test_get_or_init_raises_if_no_dir(self, batch_id: str, tmp_path: Path):
        lifecycle = PZCorrectionLifecycle(batch_id, tmp_path / "nonexistent")
        with pytest.raises(LifecycleError) as exc_info:
            lifecycle.get_or_init_state()
        assert exc_info.value.http_status == 500
```

---

## 4. PHASE 2 -- UNIVERSAL ROUTE SURFACE

### 4A. routes_pz_correction.py (NEW)

Write `service/app/api/routes_pz_correction.py` with the following complete content:

```python
"""
PZ Correction Lifecycle Routes
================================
FastAPI router exposing the PZ correction lifecycle state machine.

All endpoints are gated behind settings.pz_correction_lifecycle_enabled.
When the flag is False (default), all endpoints return 503 with a governance
note. No wFirma call is possible through these endpoints when the flag is off.

Route surface
-------------
    GET  /shipment/{batch_id}/wfirma/pz/correction/proposal
         Fetch the correction proposal enriched with supplier context.
         Transitions state from PROPOSED -> OPERATOR_REVIEWED on first call.

    GET  /shipment/{batch_id}/wfirma/pz/correction/state
         Read the current lifecycle state without transitioning it.

    POST /shipment/{batch_id}/wfirma/pz/correction/stage
         Stage a selected correction option for execution.
         Body: { "option": "ALIGN_TO_AUTHORITY"|"SPLIT_TO_STYLE_LEVEL"|"KEEP_CURRENT",
                 "operator_reason": "..." }

    DELETE /shipment/{batch_id}/wfirma/pz/correction/stage
         Reset a STAGED record back to OPERATOR_REVIEWED without executing.

    POST /shipment/{batch_id}/wfirma/pz/correction/execute
         Execute the currently staged correction.
         Body: { "contractor_id": "...", "warehouse_id": "...",
                 "product_map": {...} }   # product_map is optional

Auth
----
All endpoints require X-API-Key (via require_api_key dependency).
Write endpoints (stage, execute) additionally require X-Operator header.

Supplier context
----------------
The GET /proposal endpoint attempts to derive supplier context from the batch
audit and attaches it to the lifecycle state record on first init. Future calls
return the stored context. If context cannot be derived, SupplierContext.unknown()
is used as a safe fallback.

CANCEL_AND_RECREATE
-------------------
No route for CANCEL_AND_RECREATE exists. DEFERRED pending OQ1.
See PROJECT_STATE.md DECISIONS section.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services.batch_service import get_output_dir
from ..services.global_pz_correction import build_correction_proposal
from ..services.pz_correction_lifecycle import LifecycleError, PZCorrectionLifecycle
from ..services.pz_correction_state import SelectedOption, SupplierContext

_log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/upload", tags=["pz_correction_lifecycle"])

_auth = Depends(require_api_key)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class StageRequest(BaseModel):
    option: str
    operator_reason: str = ""


class ExecuteRequest(BaseModel):
    contractor_id: str
    warehouse_id: str
    product_map: Optional[Dict[str, str]] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_lifecycle_enabled() -> None:
    """Raise 503 if the feature flag is off."""
    if not settings.pz_correction_lifecycle_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "error":   "feature_disabled",
                "message": (
                    "PZ correction lifecycle is not enabled. "
                    "Set PZ_CORRECTION_LIFECYCLE_ENABLED=true in .env to activate."
                ),
                "flag":    "pz_correction_lifecycle_enabled",
            },
        )


def _operator_from_header(x_operator: Optional[str]) -> str:
    """Extract operator id from header, defaulting to 'operator'."""
    return (x_operator or "").strip() or "operator"


def _make_lifecycle(batch_id: str) -> PZCorrectionLifecycle:
    """Construct a lifecycle instance using the configured storage root."""
    storage_root = Path(get_output_dir())
    return PZCorrectionLifecycle(batch_id, storage_root)


def _handle_lifecycle_error(exc: LifecycleError) -> JSONResponse:
    """Convert a LifecycleError to a JSONResponse with the correct status code."""
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error":         "lifecycle_error",
            "message":       str(exc),
            "current_state": exc.current_state,
        },
    )


def _derive_supplier_context(batch_id: str) -> SupplierContext:
    """
    Attempt to derive supplier context from the batch audit.

    This is a best-effort read-only operation. If the audit cannot be read
    or the supplier fields are absent, SupplierContext.unknown() is returned.
    No exception is raised -- the supplier context is informational only.
    """
    try:
        storage_root = Path(get_output_dir())
        from ..services.global_pz_push import _batch_dir  # noqa: PLC0415

        batch_path = _batch_dir(batch_id, storage_root)
        if batch_path is None:
            return SupplierContext.unknown()

        audit_path = batch_path / "audit.json"
        if not audit_path.exists():
            return SupplierContext.unknown()

        import json  # noqa: PLC0415
        audit = json.loads(audit_path.read_text(encoding="utf-8"))

        supplier_name = (
            audit.get("supplier_name")
            or audit.get("supplier")
            or "unknown"
        )
        is_global = bool(audit.get("is_global_supplier", False))
        clearance_path = audit.get("clearance_path", "")
        supplier_type = (
            "CONSOLIDATED" if "consolidated" in clearance_path.lower()
            else "TRANSIT"  if "transit"      in clearance_path.lower()
            else "DIRECT"   if supplier_name != "unknown"
            else "UNKNOWN"
        )

        return SupplierContext(
            supplier_name=supplier_name,
            supplier_type=supplier_type,
            authority_source="invoice",
            is_global_supplier=is_global,
            context_note=f"Derived from batch audit. clearance_path={clearance_path!r}",
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("_derive_supplier_context: could not derive for %s: %s", batch_id, exc)
        return SupplierContext.unknown()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/shipment/{batch_id}/wfirma/pz/correction/proposal", dependencies=[_auth])
async def get_correction_proposal(
    batch_id: str,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Fetch the correction proposal for this batch, enriched with supplier context
    and the current lifecycle state.

    On first call, this endpoint:
    1. Derives supplier context from the batch audit.
    2. Initialises the lifecycle state as PROPOSED (if not already initialised).
    3. Transitions PROPOSED -> OPERATOR_REVIEWED and records the operator.

    On subsequent calls, returns the current lifecycle state without transitioning.

    The correction proposal itself is generated fresh from the authoritative data
    on every call (it is not cached in the lifecycle record). The lifecycle state
    is cached in pz_correction_lifecycle.json.

    Response
    --------
    {
        "batch_id": "...",
        "lifecycle": { ... CorrectionStateRecord.to_dict() },
        "proposal":  { ... CorrectionProposal },
        "supplier_context": { ... },
        "llm_used": false
    }
    """
    _require_lifecycle_enabled()
    actor = _operator_from_header(x_operator)

    lifecycle = _make_lifecycle(batch_id)
    supplier_ctx = _derive_supplier_context(batch_id)

    try:
        record = lifecycle.get_or_init_state(supplier_context=supplier_ctx)
        from ..services.pz_correction_state import CorrectionLifecycleState  # noqa: PLC0415
        if record.current_state == CorrectionLifecycleState.PROPOSED:
            record = lifecycle.mark_reviewed(actor)
    except LifecycleError as exc:
        return _handle_lifecycle_error(exc)

    # Build the correction proposal (read-only, no DB writes).
    # The proposal is built from existing lineage/authority data -- this call
    # matches the existing global_pz_correction.build_correction_proposal() pattern.
    # The implementing session should adapt the call signature to match the
    # actual build_correction_proposal() parameters for this batch.
    proposal_dict: Dict[str, Any] = {}
    try:
        from ..services.global_pz_push import _batch_dir  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415, F811
        import json  # noqa: PLC0415, F811

        storage_root = Path(get_output_dir())
        batch_path = _batch_dir(batch_id, storage_root)
        if batch_path:
            pz_rows_path = batch_path / "pz_rows.json"
            pz_rows = json.loads(pz_rows_path.read_text()) if pz_rows_path.exists() else []

            # Build proposal -- adapt call signature as needed after reading
            # build_correction_proposal() in global_pz_correction.py.
            # The lineage_result, invoice_no, and authority_rows come from the
            # existing batch data sources used by the shipment detail page.
            proposal_dict = {"note": "Proposal generation requires lineage_result -- see impl note"}
    except Exception as exc:  # noqa: BLE001
        _log.warning("get_correction_proposal: proposal build failed for %s: %s", batch_id, exc)
        proposal_dict = {"error": str(exc)}

    return JSONResponse(
        status_code=200,
        content={
            "batch_id":        batch_id,
            "lifecycle":       record.to_dict(),
            "proposal":        proposal_dict,
            "supplier_context": (
                record.supplier_context.to_dict()
                if record.supplier_context
                else SupplierContext.unknown().to_dict()
            ),
            "llm_used": False,
        },
    )


@router.get("/shipment/{batch_id}/wfirma/pz/correction/state", dependencies=[_auth])
async def get_correction_state(batch_id: str) -> JSONResponse:
    """
    Read the current lifecycle state for this batch.

    Returns the full CorrectionStateRecord dict. Returns 404 if no correction
    lifecycle has been initialised (call GET /proposal first).

    This endpoint does NOT transition any state. It is safe to poll.

    Response
    --------
    {
        "batch_id": "...",
        "state": { ... CorrectionStateRecord.to_dict() },
        "llm_used": false
    }
    """
    _require_lifecycle_enabled()
    lifecycle = _make_lifecycle(batch_id)

    try:
        record = lifecycle.get_state()
    except LifecycleError as exc:
        return _handle_lifecycle_error(exc)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error":   "not_found",
                "message": (
                    f"No correction lifecycle state found for {batch_id}. "
                    "Call GET /correction/proposal first."
                ),
            },
        )

    return JSONResponse(
        status_code=200,
        content={"batch_id": batch_id, "state": record.to_dict(), "llm_used": False},
    )


@router.post("/shipment/{batch_id}/wfirma/pz/correction/stage", dependencies=[_auth])
async def stage_correction_option(
    batch_id: str,
    body: StageRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Stage a correction option for execution.

    The option must be one of: ALIGN_TO_AUTHORITY, SPLIT_TO_STYLE_LEVEL, KEEP_CURRENT.
    CANCEL_AND_RECREATE is not accepted -- DEFERRED pending OQ1.

    operator_reason is required when staging ALIGN_TO_AUTHORITY or SPLIT_TO_STYLE_LEVEL.

    Lifecycle state must be OPERATOR_REVIEWED or FAILED before staging.

    Response
    --------
    {
        "batch_id": "...",
        "state": { ... CorrectionStateRecord.to_dict() },
        "llm_used": false
    }
    """
    _require_lifecycle_enabled()
    actor = _operator_from_header(x_operator)

    # Validate option.
    if body.option == "CANCEL_AND_RECREATE":
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "option_deferred",
                "message": (
                    "CANCEL_AND_RECREATE is DEFERRED pending OQ1 resolution. "
                    "See PROJECT_STATE.md DECISIONS section 'wFirma PZ Cancel/Delete "
                    "Capability Audit'. Current production workflow: delete PZ manually "
                    "in wFirma UI, then call /pz/clear-mapping, then re-run /pz_create."
                ),
            },
        )

    try:
        option = SelectedOption(body.option)
    except ValueError:
        valid = ", ".join(o.value for o in SelectedOption)
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "invalid_option",
                "message": f"Invalid option {body.option!r}. Valid options: {valid}",
            },
        )

    lifecycle = _make_lifecycle(batch_id)

    try:
        record = lifecycle.stage_option(
            option,
            actor=actor,
            operator_reason=body.operator_reason,
        )
    except LifecycleError as exc:
        return _handle_lifecycle_error(exc)

    return JSONResponse(
        status_code=200,
        content={"batch_id": batch_id, "state": record.to_dict(), "llm_used": False},
    )


@router.delete("/shipment/{batch_id}/wfirma/pz/correction/stage", dependencies=[_auth])
async def reset_correction_stage(
    batch_id: str,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Reset a STAGED record back to OPERATOR_REVIEWED.

    Clears the staged option, operator_reason, and idempotency_key.
    The operator must re-stage before executing.

    Only valid from STAGED state.
    """
    _require_lifecycle_enabled()
    actor = _operator_from_header(x_operator)
    lifecycle = _make_lifecycle(batch_id)

    try:
        record = lifecycle.reset_stage(actor)
    except LifecycleError as exc:
        return _handle_lifecycle_error(exc)

    return JSONResponse(
        status_code=200,
        content={"batch_id": batch_id, "state": record.to_dict(), "llm_used": False},
    )


@router.post("/shipment/{batch_id}/wfirma/pz/correction/execute", dependencies=[_auth])
async def execute_correction(
    batch_id: str,
    body: ExecuteRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """
    Execute the staged correction by calling push_correction_to_wfirma.

    This endpoint is the only path from a staged correction to a live wFirma write.
    It wraps push_correction_to_wfirma() through the lifecycle adapter, which:
    - Checks the lifecycle is in STAGED state
    - Transitions to EXECUTING atomically before any API call
    - Passes the idempotency_key generated at stage_option() time
    - Transitions to COMPLETED or FAILED based on the push result
    - Persists the full transition history

    For KEEP_CURRENT: no wFirma call is made; state transitions to COMPLETED with
    status 'keep_current_acknowledged'.

    CANCEL_AND_RECREATE: not supported. See /stage for the error message.

    Response
    --------
    {
        "batch_id": "...",
        "state": { ... CorrectionStateRecord.to_dict() },
        "push_result": { ok, status, wfirma_document_id, error },
        "llm_used": false
    }
    """
    _require_lifecycle_enabled()
    actor = _operator_from_header(x_operator)
    lifecycle = _make_lifecycle(batch_id)

    try:
        record = lifecycle.execute(
            actor=actor,
            contractor_id=body.contractor_id,
            warehouse_id=body.warehouse_id,
            product_map=body.product_map,
        )
    except LifecycleError as exc:
        return _handle_lifecycle_error(exc)

    return JSONResponse(
        status_code=200,
        content={
            "batch_id":    batch_id,
            "state":       record.to_dict(),
            "push_result": record.push_result_ref.to_dict() if record.push_result_ref else None,
            "llm_used":    False,
        },
    )
```

### 4B. main.py addition

At the end of the import block in `service/app/main.py`, add exactly:

```python
from .api.routes_pz_correction import router as pz_correction_router
```

And in the router registration block (after the other `app.include_router()` calls):

```python
app.include_router(pz_correction_router)
```

### 4C. Phase 2 Tests

Write `service/tests/test_pz_correction_routes.py`:

```python
"""
Integration tests for routes_pz_correction.py.

Uses FastAPI TestClient. The pz_correction_lifecycle module is mocked so
these tests verify routing, auth, flag gating, and response shape without
requiring a real batch directory or wFirma connection.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pz_correction_state import (
    CorrectionLifecycleState,
    CorrectionStateRecord,
    SelectedOption,
    SupplierContext,
)

_API_KEY = "test-key"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", _API_KEY)
    return TestClient(app, raise_server_exceptions=False)


def _headers(operator: str = "test-op") -> dict:
    return {"X-API-Key": _API_KEY, "X-Operator": operator}


def _make_record(state: CorrectionLifecycleState = CorrectionLifecycleState.PROPOSED) -> CorrectionStateRecord:
    record = CorrectionStateRecord.new("BATCH_001")
    record.current_state = state
    return record


BASE = "/api/v1/upload/shipment/BATCH_001/wfirma/pz/correction"


# ---------------------------------------------------------------------------
# Feature flag gating
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def test_all_endpoints_return_503_when_flag_off(self, client):
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = False
            for method, path in [
                ("get",    f"{BASE}/proposal"),
                ("get",    f"{BASE}/state"),
                ("post",   f"{BASE}/stage"),
                ("delete", f"{BASE}/stage"),
                ("post",   f"{BASE}/execute"),
            ]:
                resp = getattr(client, method)(path, headers=_headers())
                assert resp.status_code == 503, f"Expected 503 for {method} {path}"
                assert "feature_disabled" in resp.json()["detail"]["error"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_missing_api_key_returns_401(self, client):
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            resp = client.get(f"{BASE}/state", headers={"X-Operator": "op"})
        assert resp.status_code in (401, 403)

    def test_wrong_api_key_returns_401(self, client):
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            resp = client.get(
                f"{BASE}/state",
                headers={"X-API-Key": "wrong", "X-Operator": "op"},
            )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /state
# ---------------------------------------------------------------------------

class TestGetState:
    def test_returns_404_when_no_state(self, client):
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            with patch("app.api.routes_pz_correction._make_lifecycle") as mock_lc:
                mock_instance = MagicMock()
                mock_instance.get_state.return_value = None
                mock_lc.return_value = mock_instance

                resp = client.get(f"{BASE}/state", headers=_headers())
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "not_found"

    def test_returns_state_record(self, client):
        record = _make_record(CorrectionLifecycleState.OPERATOR_REVIEWED)
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            with patch("app.api.routes_pz_correction._make_lifecycle") as mock_lc:
                mock_instance = MagicMock()
                mock_instance.get_state.return_value = record
                mock_lc.return_value = mock_instance

                resp = client.get(f"{BASE}/state", headers=_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] == "BATCH_001"
        assert data["state"]["current_state"] == "operator_reviewed"
        assert data["llm_used"] is False


# ---------------------------------------------------------------------------
# POST /stage
# ---------------------------------------------------------------------------

class TestStageOption:
    def test_cancel_and_recreate_returns_400(self, client):
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            resp = client.post(
                f"{BASE}/stage",
                headers=_headers(),
                json={"option": "CANCEL_AND_RECREATE", "operator_reason": "test"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "option_deferred"

    def test_invalid_option_returns_422(self, client):
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            resp = client.post(
                f"{BASE}/stage",
                headers=_headers(),
                json={"option": "NONEXISTENT", "operator_reason": "test"},
            )
        assert resp.status_code == 422

    def test_stage_keep_current_returns_200(self, client):
        record = _make_record(CorrectionLifecycleState.STAGED)
        record.selected_option = SelectedOption.KEEP_CURRENT
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            with patch("app.api.routes_pz_correction._make_lifecycle") as mock_lc:
                mock_instance = MagicMock()
                mock_instance.stage_option.return_value = record
                mock_lc.return_value = mock_instance

                resp = client.post(
                    f"{BASE}/stage",
                    headers=_headers(),
                    json={"option": "KEEP_CURRENT"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"]["current_state"] == "staged"
        assert data["llm_used"] is False


# ---------------------------------------------------------------------------
# POST /execute
# ---------------------------------------------------------------------------

class TestExecuteCorrection:
    def test_execute_completed_returns_200(self, client):
        record = _make_record(CorrectionLifecycleState.COMPLETED)
        from app.services.pz_correction_state import PushResultRef
        record.push_result_ref = PushResultRef(
            ok=True, status="pushed", wfirma_document_id="wf-999",
            audit_event_id="evt-1", pushed_at="2026-05-24T12:00:00+00:00"
        )
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            with patch("app.api.routes_pz_correction._make_lifecycle") as mock_lc:
                mock_instance = MagicMock()
                mock_instance.execute.return_value = record
                mock_lc.return_value = mock_instance

                resp = client.post(
                    f"{BASE}/execute",
                    headers=_headers(),
                    json={"contractor_id": "c-1", "warehouse_id": "wh-1"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"]["current_state"] == "completed"
        assert data["push_result"]["ok"] is True
        assert data["push_result"]["wfirma_document_id"] == "wf-999"
        assert data["llm_used"] is False


# ---------------------------------------------------------------------------
# No CANCEL_AND_RECREATE route exists
# ---------------------------------------------------------------------------

class TestNoCancelAndRecreate:
    def test_no_execute_cancel_route_exists(self):
        """Guard: no route path contains 'cancel' anywhere in the correction router."""
        from app.api.routes_pz_correction import router
        for route in router.routes:
            assert "cancel" not in str(route.path).lower(), (
                f"Found 'cancel' in route path {route.path!r}. "
                "CANCEL_AND_RECREATE is DEFERRED. Remove any cancel route."
            )

    def test_cancel_and_recreate_stage_returns_400_not_405(self, client):
        """The /stage endpoint handles CANCEL_AND_RECREATE with a 400 governance message,
        not a 404/405. This verifies the user gets a clear DEFERRED explanation."""
        with patch("app.api.routes_pz_correction.settings") as mock_settings:
            mock_settings.pz_correction_lifecycle_enabled = True
            resp = client.post(
                f"{BASE}/stage",
                headers=_headers(),
                json={"option": "CANCEL_AND_RECREATE"},
            )
        assert resp.status_code == 400
        body = resp.json()
        assert "DEFERRED" in body["detail"]["message"]
        assert "OQ1" in body["detail"]["message"]
```

---

## 5. IMPLEMENTATION NOTES FOR THE EXECUTING SESSION

Before writing any file, the executing session must:

1. **Read `service/app/services/batch_service.py`** to find the exact function name and
   return type for `get_output_dir()`. If it returns a `Path`, use it directly.
   If it returns a `str`, wrap with `Path(get_output_dir())`.

2. **Read `service/app/services/global_pz_correction.py` fully** to understand the complete
   `build_correction_proposal()` signature. The routes_pz_correction.py placeholder in
   `get_correction_proposal()` must be replaced with a real call that passes the correct
   arguments (lineage_result, authority_rows, pz_rows, invoice_no).

3. **Read `service/app/core/security.py`** to verify the exact name of the API key
   dependency (`require_api_key`). If it differs, update the import in routes_pz_correction.py.

4. **Run `make verify` before writing the first file** and record the test count as
   the baseline. Run again after all files are written. The delta must be positive (new
   tests added, not tests broken).

5. **The `write_json_atomic` import** is from `..utils.io`. Confirm this path exists before
   writing pz_correction_lifecycle.py. If the function lives elsewhere, update the import.

6. **Supplier context note**: `_derive_supplier_context()` reads `audit.json` from the
   batch directory. The actual field names in the audit file (`supplier_name`,
   `is_global_supplier`, etc.) should be verified against a real audit file before the
   route goes live. The function is already guarded with a broad except that returns
   `SupplierContext.unknown()` on any error, so a wrong field name will not break the
   endpoint -- it will just return unknown context.

---

## 6. ACCEPTANCE CRITERIA

The session is COMPLETE when all of the following are true:

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | `make verify` passes with MORE tests than baseline | Run `make verify` |
| 2 | `pz_correction_state.py` imports cleanly | `python -c "from app.services.pz_correction_state import CorrectionStateRecord; print('OK')"` |
| 3 | `pz_correction_lifecycle.py` imports cleanly | `python -c "from app.services.pz_correction_lifecycle import PZCorrectionLifecycle; print('OK')"` |
| 4 | `routes_pz_correction.py` imports cleanly | `python -c "from app.api.routes_pz_correction import router; print('OK')"` |
| 5 | CANCEL_AND_RECREATE is absent from SelectedOption | `test_cancel_and_recreate_not_present` passes |
| 6 | No cancel route exists in router | `test_no_execute_cancel_route_exists` passes |
| 7 | All endpoints return 503 when flag is off | `test_all_endpoints_return_503_when_flag_off` passes |
| 8 | Transition history is persisted to disk | `test_transition_history_is_complete` passes |
| 9 | `test_wfirma_pz_notes_workflow_rule.py` still passes | Confirms no governance leak |
| 10 | No wFirma write path exists outside `push_correction_to_wfirma()` | Source-grep: `grep -n "warehouse_document_p_z.*delete\|delete_warehouse_pz" service/app/ -r` returns nothing |

---

## 7. FUTURE RESEARCH TRACK -- DEFERRED (do not implement in this session)

### Sprint 3: CANCEL_AND_RECREATE (BLOCKED on OQ1)

**Status**: DEFERRED / MANUAL-ONLY

**What is blocked**: Implementation of a `cancel_warehouse_pz()` wrapper in
`wfirma_client.py` and a CANCEL_AND_RECREATE execution path in the lifecycle.

**Reopening trigger**: Written confirmation from wFirma support (`pomoc@wfirma.pl`)
that `warehouse_document_p_z/delete/{id}` exists with:
- Confirmed return status on success
- Confirmed inventory reversal behavior (stock decremented)
- Documented error codes for linked-document rejection

**Four prerequisites (all must be met before any implementation PR opens)**:
1. wFirma support confirms `warehouse_document_p_z/delete/{id}` exists
2. wFirma support confirms inventory reversal semantics
3. Operator explicitly instructs: "Implement automated PZ delete with inventory reversal"
4. 7-agent deploy gate reviewed with write-gate, idempotency, audit-trail, rollback

**When it reopens**: The lifecycle in this campaign can be extended to add
`SelectedOption.CANCEL_AND_RECREATE`, a new `suppress_cancel_deferred()` check in
`stage_option()`, a new transition `STAGED -> CANCELLING -> COMPLETED/FAILED`, and
a `cancel_warehouse_pz()` call wrapped with the same idempotency pattern as
`push_correction_to_wfirma()`. None of that work is speculative -- it follows the exact
patterns laid down in Phases 1 and 2. It simply requires the external verification first.

**Current production workflow (proven, sufficient)**:
1. Operator deletes PZ document in wFirma UI
2. Operator calls `POST /shipment/{batch_id}/wfirma/pz/clear-mapping` (X-Operator header)
3. Operator re-runs the guarded PZ create path via `/wfirma/pz_create`

---

## 8. DEPLOY NOTES

This campaign requires a standard deploy (all files in `service/app/**`):

```powershell
# After PR is merged to main:
git pull --ff-only origin main

robocopy "C:\Users\Super Fashion\PZ APP\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache `
  /XF "*.pyc" "*.pyo" "*.zip"

# Restart required (new Python modules)
sc.exe stop PZService
# ... wait for STOPPED
sc.exe start PZService

# Verify flag is OFF (default -- all new endpoints return 503)
Invoke-WebRequest "http://127.0.0.1:47213/api/v1/upload/shipment/SMOKE-TEST/wfirma/pz/correction/state" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
# Expected: 503 {"error":"feature_disabled",...}
```

The feature flag `PZ_CORRECTION_LIFECYCLE_ENABLED=true` must be added to `C:\PZ\.env`
**manually by the operator** before any lifecycle endpoint becomes active. This is an
intentional operator gate -- deploying this code changes nothing in production.

A deploy manifest (`windows_deploy_<SHA>.ps1`) must be generated by the deploy_release_manager
agent as part of the normal 7-agent deploy gate. This campaign document is NOT the deploy
manifest.

---

*End of campaign document.*
*Generated: 2026-05-24*
*Campaign status: READY FOR IMPLEMENTATION*
*Author: Estrella PZ Processor governance layer*
