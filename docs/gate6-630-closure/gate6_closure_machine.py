"""Gate 6 closure state machine — #630 → Phase 1A governance lifecycle.

This is a GOVERNANCE MODELING ARTIFACT, not production code. It lives under
``docs/`` (excluded from the production robocopy: `service/app/**` is the only
deployed tree). It encodes — and makes mechanically testable — the post-merge
branch-lifecycle rule:

    WAITING_FOR_MERGE
        --merged-->              VERIFYING_MAIN
    VERIFYING_MAIN
        --b1_b5_passed-->        READY_TO_CREATE_DOCS_BRANCH  (records verified_sha)
        --b1_b5_failed-->        HALT_ESCALATE                (terminal; no branch/artifact)
    READY_TO_CREATE_DOCS_BRANCH
        --create_docs_branch-->  DOCS_BRANCH_CREATED          (creates docs branch)
    DOCS_BRANCH_CREATED
        --docs_merged-->         DOCS_MERGED                  (records docs merge)
    DOCS_MERGED
        --phase1a_authorized-->  PHASE_1A_OPEN                (opens Phase 1A)

The distinct ``docs_merged`` gate is load-bearing (G2): Phase 1A cannot open
until the docs/governance branch has actually merged. Creating the docs branch
is NOT the same event as the docs branch merging — Phase 1A keys off the merge,
not the branch creation.

Hardening contract (this module is the hardened revision; both READY-WITH-
CONDITIONS blockers from the prior review are closed):

  BLOCKER 1 — governance checks must not depend on ``assert``.
    ``python -O`` strips ``assert`` statements. Every governance-relevant
    precondition (branch authority, B1-B5 completion, verified SHA presence,
    docs-merge completion, immutability of terminal states) is enforced with
    explicit ``if/raise`` fail-closed checks. There is NO ``assert`` anywhere
    in this module.

  BLOCKER 2 — internal methods must not be a back door around ``dispatch()``.
    ``dispatch()`` is the SOLE supported public entrypoint that may mutate the
    machine. Every true internal is name-mangled (``__run``, ``__apply_event``,
    ``__create_docs_branch``, ``__record_docs_merged``, ``__open_phase_1a``,
    ``__audit``) so it is not reachable as a plain attribute. The double-
    underscore form is a structural deterrent (callers would have to spell
    ``_Gate6ClosureMachine__apply_event``, which is explicitly documented as
    unsupported), not a hard security boundary.

Invariants enforced (see tests):
  * ``OPERATOR_TRANSITIONS`` is the sole operator routing table.
  * Audit is written BEFORE every accepted state mutation.
  * Audit is written BEFORE every rejected raise.
  * Unknown, replay, and out-of-order events reject with ``InvalidTransitionError``.
  * Terminal states (``PHASE_1A_OPEN``, ``HALT_ESCALATE``) are absorbing.
  * B1-B5 failure halts before any docs branch or artifact is created.
  * A missing verified SHA is a RETRYABLE reject in ``VERIFYING_MAIN`` (state
    unchanged), NOT a terminal halt. Only an actual B1-B5 failure halts. (G1)
  * Phase 1A cannot open until the docs branch is created AND docs merge is on
    record. (G2)
  * The machine never writes ``FEATURE_BRANCH`` and never merges to ``main``
    (it has no code path that does either; ``merged`` and ``docs_merged`` are
    inbound *notifications* that an operator-performed merge happened, not
    actions the machine takes).
"""

from __future__ import annotations

import enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


# --- Defaults sourced from the active modernization lane -----------------------
# Feature PR #630 branch (frozen on merge) and the dedicated post-merge docs branch.
DEFAULT_FEATURE_BRANCH = "feat/pr1a-conflict-foundation-remediation"
DEFAULT_DOCS_BRANCH = "docs/gate6-630-closure"


class State(enum.Enum):
    WAITING_FOR_MERGE = "WAITING_FOR_MERGE"
    VERIFYING_MAIN = "VERIFYING_MAIN"
    READY_TO_CREATE_DOCS_BRANCH = "READY_TO_CREATE_DOCS_BRANCH"
    DOCS_BRANCH_CREATED = "DOCS_BRANCH_CREATED"
    DOCS_MERGED = "DOCS_MERGED"
    PHASE_1A_OPEN = "PHASE_1A_OPEN"
    HALT_ESCALATE = "HALT_ESCALATE"


class Event(enum.Enum):
    MERGED = "merged"
    B1_B5_PASSED = "b1_b5_passed"
    B1_B5_FAILED = "b1_b5_failed"
    CREATE_DOCS_BRANCH = "create_docs_branch"
    DOCS_MERGED = "docs_merged"
    PHASE1A_AUTHORIZED = "phase1a_authorized"


TERMINAL_STATES = frozenset({State.PHASE_1A_OPEN, State.HALT_ESCALATE})

# Sole operator routing table. (current_state, event) -> next_state.
# Nothing else decides legal operator transitions; guards/actions only add
# fail-closed preconditions and side effects, they never invent a transition.
OPERATOR_TRANSITIONS: Dict[Tuple[State, Event], State] = {
    (State.WAITING_FOR_MERGE, Event.MERGED): State.VERIFYING_MAIN,
    (State.VERIFYING_MAIN, Event.B1_B5_PASSED): State.READY_TO_CREATE_DOCS_BRANCH,
    (State.VERIFYING_MAIN, Event.B1_B5_FAILED): State.HALT_ESCALATE,
    (State.READY_TO_CREATE_DOCS_BRANCH, Event.CREATE_DOCS_BRANCH): State.DOCS_BRANCH_CREATED,
    (State.DOCS_BRANCH_CREATED, Event.DOCS_MERGED): State.DOCS_MERGED,
    (State.DOCS_MERGED, Event.PHASE1A_AUTHORIZED): State.PHASE_1A_OPEN,
}


class Gate6Error(Exception):
    """Base class for Gate 6 closure errors."""


class InvalidTransitionError(Gate6Error):
    """Raised when an event is unknown, a replay, or out of order."""


class GovernanceViolation(Gate6Error):
    """Raised when a fail-closed governance precondition is not satisfied.

    Distinct from InvalidTransitionError: the transition itself is legal in the
    routing table, but a governance guard (branch authority, B1-B5 completion,
    verified SHA, docs-merge completion) refused it.

    Per G1, a GovernanceViolation does NOT advance state — the operator may
    correct the precondition and re-dispatch. It is a retryable reject, not a
    terminal halt. (Terminal halt is reserved for an actual B1-B5 failure.)
    """


def _coerce_event(event: Any) -> Optional[Event]:
    """Map an inbound value to a known Event, or None if unrecognized."""
    if isinstance(event, Event):
        return event
    if isinstance(event, str):
        try:
            return Event(event)
        except ValueError:
            return None
    return None


class Gate6ClosureMachine:
    """Deterministic, audit-chained state machine for the Gate 6 closure flow.

    Public API (the supported surface):
      * ``dispatch(event, **payload)`` — the ONLY entrypoint that mutates state.
      * ``state`` — read-only current state.
      * ``audit_log`` — read-only copy of the audit chain.
      * ``created_branches`` — read-only copy of branches the machine created.
      * ``verified_sha`` / ``b1_b5_passed`` / ``docs_merged`` — read-only facts.
      * ``verify_chain()`` — recompute and validate the audit hash chain.
      * ``merged_to_main`` — always False; the machine never merges to main.

    Everything else is name-mangled and unsupported. Reaching past ``dispatch()``
    (e.g. ``machine._Gate6ClosureMachine__apply_event(...)``) is explicitly
    out of contract.
    """

    def __init__(
        self,
        feature_branch: str = DEFAULT_FEATURE_BRANCH,
        docs_branch: str = DEFAULT_DOCS_BRANCH,
        initial_state: State = State.WAITING_FOR_MERGE,
    ) -> None:
        self.__feature_branch = feature_branch
        self.__docs_branch = docs_branch
        self.__state = initial_state
        self.__verified_sha: Optional[str] = None
        self.__b1_b5_passed = False
        self.__docs_merged = False
        self.__created_branches: List[str] = []
        self.__audit_log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Public, read-only accessors
    # ------------------------------------------------------------------ #
    @property
    def state(self) -> State:
        return self.__state

    @property
    def feature_branch(self) -> str:
        return self.__feature_branch

    @property
    def docs_branch(self) -> str:
        return self.__docs_branch

    @property
    def verified_sha(self) -> Optional[str]:
        return self.__verified_sha

    @property
    def b1_b5_passed(self) -> bool:
        return self.__b1_b5_passed

    @property
    def docs_merged(self) -> bool:
        return self.__docs_merged

    @property
    def created_branches(self) -> Tuple[str, ...]:
        return tuple(self.__created_branches)

    @property
    def merged_to_main(self) -> bool:
        # The machine never performs a merge to main. Always False, immutable.
        return False

    @property
    def audit_log(self) -> Tuple[Dict[str, Any], ...]:
        # Deep-ish copy so callers cannot tamper with the chain.
        return tuple(dict(entry) for entry in self.__audit_log)

    # ------------------------------------------------------------------ #
    # Sole public entrypoint
    # ------------------------------------------------------------------ #
    def dispatch(self, event: Any, **payload: Any) -> State:
        """The only supported way to advance the machine.

        Returns the resulting state on an accepted transition. Raises
        ``InvalidTransitionError`` (unknown / replay / out-of-order / terminal)
        or ``GovernanceViolation`` (fail-closed precondition) on rejection.
        Every accepted mutation and every rejected raise is audited first.
        """
        return self.__run(event, payload)

    # ------------------------------------------------------------------ #
    # Internals — name-mangled, unsupported as call targets
    # ------------------------------------------------------------------ #
    def __run(self, event: Any, payload: Dict[str, Any]) -> State:
        coerced = _coerce_event(event)
        return self.__apply_event(coerced, event, payload)

    def __apply_event(
        self, event: Optional[Event], raw_event: Any, payload: Dict[str, Any]
    ) -> State:
        state = self.__state

        # 1. Unknown event -> audit reject, raise.
        if event is None:
            self.__audit("REJECT", raw_event, reason="unknown-event", from_state=state)
            raise InvalidTransitionError(
                "unknown event {!r} in state {}".format(raw_event, state.value)
            )

        # 2. Terminal states are absorbing -> audit reject, raise.
        if state in TERMINAL_STATES:
            self.__audit("REJECT", event, reason="terminal-absorbing", from_state=state)
            raise InvalidTransitionError(
                "state {} is terminal; event {} rejected".format(
                    state.value, event.value
                )
            )

        # 3. No legal transition (replay or out-of-order) -> audit reject, raise.
        key = (state, event)
        if key not in OPERATOR_TRANSITIONS:
            self.__audit(
                "REJECT", event, reason="no-transition", from_state=state
            )
            raise InvalidTransitionError(
                "no transition for event {} in state {}".format(
                    event.value, state.value
                )
            )

        target = OPERATOR_TRANSITIONS[key]

        # 4. Fail-closed governance side effects. These run BEFORE the accept
        #    audit and BEFORE any state mutation. On violation they audit a
        #    REJECT and raise, leaving state untouched (no ACCEPT recorded).
        #    Per G1 a GovernanceViolation here is retryable: state is unchanged,
        #    so the operator can fix the precondition and re-dispatch the same
        #    event in the same state.
        if event is Event.B1_B5_PASSED:
            self.__record_b1_b5_pass(payload)
        elif event is Event.B1_B5_FAILED:
            self.__record_b1_b5_fail(payload)
        elif event is Event.CREATE_DOCS_BRANCH:
            self.__create_docs_branch(payload)
        elif event is Event.DOCS_MERGED:
            self.__record_docs_merged(payload)
        elif event is Event.PHASE1A_AUTHORIZED:
            self.__open_phase_1a(payload)

        # 5. Audit the accepted transition BEFORE mutating state.
        self.__audit(
            "ACCEPT", event, from_state=state, to_state=target,
            detail={"verified_sha": self.__verified_sha},
        )

        # 6. Mutate state last.
        self.__state = target
        return self.__state

    # --- governance actions (fail-closed; explicit if/raise, no assert) --- #
    def __record_b1_b5_pass(self, payload: Dict[str, Any]) -> None:
        verified_sha = payload.get("verified_sha")
        # FAIL-CLOSED, RETRYABLE (G1): B1-B5 cannot be marked passed without a
        # verified SHA. This raises but leaves state in VERIFYING_MAIN so the
        # operator can supply the SHA and re-dispatch. It is NOT a terminal halt.
        if not verified_sha or not isinstance(verified_sha, str):
            self.__audit(
                "REJECT", Event.B1_B5_PASSED,
                reason="missing-verified-sha", from_state=self.__state,
            )
            raise GovernanceViolation(
                "b1_b5_passed requires a non-empty verified_sha"
            )
        self.__verified_sha = verified_sha
        self.__b1_b5_passed = True
        self.__audit(
            "VERIFY", Event.B1_B5_PASSED, from_state=self.__state,
            detail={"verified_sha": verified_sha, "b1_b5_passed": True},
        )

    def __record_b1_b5_fail(self, payload: Dict[str, Any]) -> None:
        # Halt path: explicitly mark B1-B5 NOT passed so no later docs-branch
        # action can ever succeed off this machine. No branch/artifact created.
        # This is the ONLY terminal halt route (G1).
        self.__b1_b5_passed = False
        self.__audit(
            "HALT", Event.B1_B5_FAILED, from_state=self.__state,
            reason=str(payload.get("reason", "b1_b5_failed")),
            detail={"b1_b5_passed": False},
        )

    def __create_docs_branch(self, payload: Dict[str, Any]) -> None:
        """Create the post-merge docs/governance branch — fail-closed.

        No ``assert`` may guard branch authority, verified SHA, or B1-B5
        completion. Every precondition is an explicit if/raise.
        """
        # GUARD 1 — branch authority: docs branch must NOT be the feature branch.
        if self.__docs_branch == self.__feature_branch:
            self.__audit(
                "REJECT", Event.CREATE_DOCS_BRANCH,
                reason="docs-branch-equals-feature-branch",
                from_state=self.__state,
            )
            raise GovernanceViolation(
                "docs branch {!r} must differ from feature branch {!r}".format(
                    self.__docs_branch, self.__feature_branch
                )
            )

        # GUARD 2 — B1-B5 must have passed before any docs branch is created.
        if not self.__b1_b5_passed:
            self.__audit(
                "REJECT", Event.CREATE_DOCS_BRANCH,
                reason="b1-b5-not-passed", from_state=self.__state,
            )
            raise GovernanceViolation(
                "cannot create docs branch before B1-B5 passed"
            )

        # GUARD 3 — a verified post-merge SHA must exist.
        if not self.__verified_sha:
            self.__audit(
                "REJECT", Event.CREATE_DOCS_BRANCH,
                reason="missing-verified-sha", from_state=self.__state,
            )
            raise GovernanceViolation(
                "cannot create docs branch without a verified_sha"
            )

        # GUARD 4 — never write the feature branch (defense in depth).
        if self.__docs_branch == self.__feature_branch:
            # Unreachable given GUARD 1, kept as an explicit immutability check.
            self.__audit(
                "REJECT", Event.CREATE_DOCS_BRANCH,
                reason="feature-branch-write-blocked", from_state=self.__state,
            )
            raise GovernanceViolation("refusing to write feature branch")

        self.__created_branches.append(self.__docs_branch)
        self.__audit(
            "BRANCH_CREATED", Event.CREATE_DOCS_BRANCH, from_state=self.__state,
            detail={
                "docs_branch": self.__docs_branch,
                "from_sha": self.__verified_sha,
            },
        )

    def __record_docs_merged(self, payload: Dict[str, Any]) -> None:
        """Record that the docs/governance branch has merged — fail-closed (G2).

        Creating the docs branch is not the same as merging it. Phase 1A keys
        off this merge record, so this is a distinct gate. The docs branch must
        have been created off this machine before its merge can be recorded.
        """
        # GUARD — the docs branch must have actually been created here first.
        if self.__docs_branch not in self.__created_branches:
            self.__audit(
                "REJECT", Event.DOCS_MERGED,
                reason="docs-branch-not-created", from_state=self.__state,
            )
            raise GovernanceViolation(
                "cannot record docs merge before the docs branch is created"
            )

        self.__docs_merged = True
        docs_merge_sha = payload.get("docs_merge_sha")
        self.__audit(
            "DOCS_MERGED", Event.DOCS_MERGED, from_state=self.__state,
            detail={
                "docs_branch": self.__docs_branch,
                "docs_merge_sha": docs_merge_sha if isinstance(docs_merge_sha, str) else None,
                "docs_merged": True,
            },
        )

    def __open_phase_1a(self, payload: Dict[str, Any]) -> None:
        # FAIL-CLOSED (G2): Phase 1A cannot open unless the docs branch was
        # created off this machine, B1-B5 verification is on record, AND the
        # docs merge has been confirmed. Docs-merge is the load-bearing new gate.
        if self.__docs_branch not in self.__created_branches:
            self.__audit(
                "REJECT", Event.PHASE1A_AUTHORIZED,
                reason="docs-branch-not-created", from_state=self.__state,
            )
            raise GovernanceViolation(
                "cannot open Phase 1A before the docs branch is created"
            )
        if not self.__docs_merged:
            self.__audit(
                "REJECT", Event.PHASE1A_AUTHORIZED,
                reason="docs-not-merged", from_state=self.__state,
            )
            raise GovernanceViolation(
                "cannot open Phase 1A before the docs branch is merged"
            )
        if not self.__b1_b5_passed or not self.__verified_sha:
            self.__audit(
                "REJECT", Event.PHASE1A_AUTHORIZED,
                reason="verification-not-on-record", from_state=self.__state,
            )
            raise GovernanceViolation(
                "cannot open Phase 1A without B1-B5 + verified_sha on record"
            )
        self.__audit(
            "PHASE_1A_OPEN", Event.PHASE1A_AUTHORIZED, from_state=self.__state,
            detail={"verified_sha": self.__verified_sha},
        )

    # --- audit hash chain ------------------------------------------------- #
    def __audit(
        self,
        kind: str,
        event: Any,
        from_state: Optional[State] = None,
        to_state: Optional[State] = None,
        reason: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        if isinstance(event, Event):
            event_repr = event.value
        else:
            event_repr = str(event)
        prev_hash = self.__audit_log[-1]["entry_hash"] if self.__audit_log else ""
        body = {
            "seq": len(self.__audit_log),
            "kind": kind,
            "event": event_repr,
            "from_state": from_state.value if from_state else None,
            "to_state": to_state.value if to_state else None,
            "reason": reason,
            "detail": detail or {},
            "prev_hash": prev_hash,
        }
        body["entry_hash"] = self.__hash_entry(body)
        self.__audit_log.append(body)

    @staticmethod
    def __hash_entry(body: Dict[str, Any]) -> str:
        payload = {k: v for k, v in body.items() if k != "entry_hash"}
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def verify_chain(self) -> bool:
        """Recompute the audit hash chain and confirm it is intact."""
        prev_hash = ""
        for entry in self.__audit_log:
            if entry.get("prev_hash") != prev_hash:
                return False
            recomputed = self.__hash_entry(entry)
            if recomputed != entry.get("entry_hash"):
                return False
            prev_hash = entry["entry_hash"]
        return True
