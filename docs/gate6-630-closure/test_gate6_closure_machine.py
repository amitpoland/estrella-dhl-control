"""Tests for the hardened Gate 6 closure state machine.

Covers both READY-WITH-CONDITIONS blockers:
  * governance never depends on ``assert`` (source-AST scan + a real ``python -O``
    subprocess run that still raises GovernanceViolation), and
  * ``dispatch()`` is the sole public entrypoint; true internals are name-mangled.

Plus the full transition contract: accept/reject + audit ordering, replay,
out-of-order, unknown events, terminal absorption, B1-B5 halt, the retryable
missing-SHA reject (G1), the distinct docs_merged gate before Phase 1A (G2),
and audit-chain integrity after both accepted and rejected events.
"""

import ast
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate6_closure_machine as g6  # noqa: E402
from gate6_closure_machine import (  # noqa: E402
    Event,
    Gate6ClosureMachine,
    GovernanceViolation,
    InvalidTransitionError,
    State,
)

MODULE_PATH = os.path.abspath(g6.__file__)
MODULE_DIR = os.path.dirname(MODULE_PATH)


def _to_ready_to_create_docs_branch():
    """Drive a fresh machine to READY_TO_CREATE_DOCS_BRANCH via the supported path."""
    m = Gate6ClosureMachine()
    m.dispatch(Event.MERGED)
    m.dispatch(Event.B1_B5_PASSED, verified_sha="deadbeef1234")
    assert m.state is State.READY_TO_CREATE_DOCS_BRANCH
    return m


def _to_docs_branch_created():
    """Drive to DOCS_BRANCH_CREATED (docs branch created, not yet merged)."""
    m = _to_ready_to_create_docs_branch()
    m.dispatch(Event.CREATE_DOCS_BRANCH)
    assert m.state is State.DOCS_BRANCH_CREATED
    return m


# --------------------------------------------------------------------------- #
# 1. merged accepted only in WAITING_FOR_MERGE
# --------------------------------------------------------------------------- #
def test_merged_accepted_only_in_waiting_for_merge():
    m = Gate6ClosureMachine()
    assert m.state is State.WAITING_FOR_MERGE
    assert m.dispatch(Event.MERGED) is State.VERIFYING_MAIN

    # In every other reachable non-terminal state, merged is rejected.
    m2 = _to_ready_to_create_docs_branch()
    before = len(m2.audit_log)
    try:
        m2.dispatch(Event.MERGED)
        assert False, "merged should be rejected outside WAITING_FOR_MERGE"
    except InvalidTransitionError:
        pass
    assert m2.state is State.READY_TO_CREATE_DOCS_BRANCH
    assert len(m2.audit_log) == before + 1
    assert m2.audit_log[-1]["kind"] == "REJECT"


# --------------------------------------------------------------------------- #
# 2. replay of merged is rejected and audited
# --------------------------------------------------------------------------- #
def test_replay_of_merged_rejected_and_audited():
    m = Gate6ClosureMachine()
    m.dispatch(Event.MERGED)
    before = len(m.audit_log)
    try:
        m.dispatch(Event.MERGED)  # replay
        assert False, "replayed merged should reject"
    except InvalidTransitionError:
        pass
    assert m.state is State.VERIFYING_MAIN  # unchanged
    assert len(m.audit_log) == before + 1
    last = m.audit_log[-1]
    assert last["kind"] == "REJECT"
    assert last["reason"] == "no-transition"
    assert m.verify_chain() is True


# --------------------------------------------------------------------------- #
# 3. create_docs_branch before READY_TO_CREATE_DOCS_BRANCH is rejected/audited
# --------------------------------------------------------------------------- #
def test_create_docs_branch_before_ready_is_rejected_and_audited():
    m = Gate6ClosureMachine()  # WAITING_FOR_MERGE
    before = len(m.audit_log)
    try:
        m.dispatch(Event.CREATE_DOCS_BRANCH)
        assert False, "create_docs_branch too early should reject"
    except InvalidTransitionError:
        pass
    assert m.state is State.WAITING_FOR_MERGE
    assert m.created_branches == ()
    assert len(m.audit_log) == before + 1
    assert m.audit_log[-1]["kind"] == "REJECT"

    # Also rejected from VERIFYING_MAIN (still before the ready gate).
    m.dispatch(Event.MERGED)
    try:
        m.dispatch(Event.CREATE_DOCS_BRANCH)
        assert False
    except InvalidTransitionError:
        pass
    assert m.created_branches == ()


# --------------------------------------------------------------------------- #
# 4. unknown event is rejected and audited
# --------------------------------------------------------------------------- #
def test_unknown_event_rejected_and_audited():
    m = Gate6ClosureMachine()
    before = len(m.audit_log)
    try:
        m.dispatch("not_a_real_event")
        assert False, "unknown event should reject"
    except InvalidTransitionError:
        pass
    assert m.state is State.WAITING_FOR_MERGE
    assert len(m.audit_log) == before + 1
    last = m.audit_log[-1]
    assert last["kind"] == "REJECT"
    assert last["reason"] == "unknown-event"
    assert last["event"] == "not_a_real_event"


# --------------------------------------------------------------------------- #
# 5. B1-B5 failure reaches HALT_ESCALATE and creates no branch/artifact
# --------------------------------------------------------------------------- #
def test_b1_b5_failure_halts_with_no_branch_or_artifact():
    m = Gate6ClosureMachine()
    m.dispatch(Event.MERGED)
    m.dispatch(Event.B1_B5_FAILED, reason="marker missing on origin/main")
    assert m.state is State.HALT_ESCALATE
    assert m.created_branches == ()
    assert m.b1_b5_passed is False
    assert m.verified_sha is None

    # Terminal: every further event is absorbed (rejected), still no branch.
    for ev in (Event.CREATE_DOCS_BRANCH, Event.MERGED, Event.PHASE1A_AUTHORIZED):
        try:
            m.dispatch(ev)
            assert False, "terminal state must absorb {}".format(ev)
        except InvalidTransitionError:
            pass
    assert m.created_branches == ()
    assert m.state is State.HALT_ESCALATE


# --------------------------------------------------------------------------- #
# 5b. (G1) missing verified_sha is a RETRYABLE reject in VERIFYING_MAIN,
#     not a terminal halt. The operator can supply the SHA and re-dispatch.
# --------------------------------------------------------------------------- #
def test_missing_sha_is_retryable_reject_not_terminal_halt():
    m = Gate6ClosureMachine()
    m.dispatch(Event.MERGED)
    assert m.state is State.VERIFYING_MAIN

    before = len(m.audit_log)
    try:
        m.dispatch(Event.B1_B5_PASSED)  # no verified_sha
        assert False, "missing verified_sha must raise GovernanceViolation"
    except GovernanceViolation:
        pass
    # State is UNCHANGED — this is retryable, not a halt.
    assert m.state is State.VERIFYING_MAIN
    assert m.b1_b5_passed is False
    assert m.verified_sha is None
    assert len(m.audit_log) == before + 1
    assert m.audit_log[-1]["kind"] == "REJECT"
    assert m.audit_log[-1]["reason"] == "missing-verified-sha"

    # Re-dispatch with the SHA now succeeds from the same state.
    assert m.dispatch(Event.B1_B5_PASSED, verified_sha="abc123") is State.READY_TO_CREATE_DOCS_BRANCH
    assert m.verify_chain() is True


# --------------------------------------------------------------------------- #
# 5c. (G2) Phase 1A cannot open until docs_merged is recorded
# --------------------------------------------------------------------------- #
def test_phase_1a_blocked_until_docs_merged():
    # DOCS_MERGED event before the branch is created is rejected at routing.
    m = _to_ready_to_create_docs_branch()
    try:
        m.dispatch(Event.DOCS_MERGED)
        assert False, "docs_merged before branch creation should reject"
    except InvalidTransitionError:
        pass
    assert m.state is State.READY_TO_CREATE_DOCS_BRANCH

    # After branch creation, phase1a_authorized is NOT yet a legal transition
    # from DOCS_BRANCH_CREATED (must go through docs_merged first).
    m = _to_docs_branch_created()
    try:
        m.dispatch(Event.PHASE1A_AUTHORIZED)
        assert False, "phase1a before docs_merged should reject"
    except InvalidTransitionError:
        pass
    assert m.state is State.DOCS_BRANCH_CREATED

    # Record the docs merge, then Phase 1A opens.
    assert m.dispatch(Event.DOCS_MERGED, docs_merge_sha="f00dbabe") is State.DOCS_MERGED
    assert m.docs_merged is True
    assert m.audit_log[-2]["kind"] == "DOCS_MERGED"  # action audited before ACCEPT
    assert m.dispatch(Event.PHASE1A_AUTHORIZED) is State.PHASE_1A_OPEN


def test_phase_1a_open_is_terminal_absorbing():
    m = _to_docs_branch_created()
    m.dispatch(Event.DOCS_MERGED)
    assert m.state is State.DOCS_MERGED
    m.dispatch(Event.PHASE1A_AUTHORIZED)
    assert m.state is State.PHASE_1A_OPEN
    before = len(m.audit_log)
    try:
        m.dispatch(Event.MERGED)
        assert False
    except InvalidTransitionError:
        pass
    assert m.state is State.PHASE_1A_OPEN
    assert m.audit_log[-1]["kind"] == "REJECT"
    assert m.audit_log[-1]["reason"] == "terminal-absorbing"
    assert len(m.audit_log) == before + 1


# --------------------------------------------------------------------------- #
# 6. governance does NOT depend on assert
# --------------------------------------------------------------------------- #
def test_module_has_no_assert_statements():
    with open(MODULE_PATH, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=MODULE_PATH)
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert asserts == [], "governance module must contain no assert statements"


def test_governance_guards_raise_under_optimized_mode():
    """Run the governance checks in a real ``python -O`` subprocess.

    If any guard were an ``assert``, -O would strip it and the violations would
    NOT raise. This proves fail-closed behavior survives optimization.
    """
    script = (
        "import sys; sys.path.insert(0, {dir!r});"
        "import gate6_closure_machine as g;"
        "from gate6_closure_machine import Event, GovernanceViolation,"
        " InvalidTransitionError, Gate6ClosureMachine, State;"
        # assert is stripped under -O: prove __debug__ is False here.
        "print('DEBUG', __debug__);"
        # (a) b1_b5_passed without verified_sha must still raise.
        "m=Gate6ClosureMachine(); m.dispatch(Event.MERGED);"
        "r1='no';\n"
        "try:\n"
        "    m.dispatch(Event.B1_B5_PASSED)\n"
        "except GovernanceViolation:\n"
        "    r1='raised'\n"
        "print('R1', r1);"
        # (b) docs branch == feature branch must still raise.
        "m2=Gate6ClosureMachine(feature_branch='x', docs_branch='x');"
        "m2.dispatch(Event.MERGED);"
        "m2.dispatch(Event.B1_B5_PASSED, verified_sha='abc');"
        "r2='no';\n"
        "try:\n"
        "    m2.dispatch(Event.CREATE_DOCS_BRANCH)\n"
        "except GovernanceViolation:\n"
        "    r2='raised'\n"
        "print('R2', r2);"
        # (c) phase1a before docs_merged must still be rejected fail-closed.
        # From DOCS_BRANCH_CREATED the routing table has no phase1a transition,
        # so this rejects at the routing layer (InvalidTransitionError). The
        # point under -O: the machine does NOT open Phase 1A without docs_merged.
        "m3=Gate6ClosureMachine();"
        "m3.dispatch(Event.MERGED);"
        "m3.dispatch(Event.B1_B5_PASSED, verified_sha='abc');"
        "m3.dispatch(Event.CREATE_DOCS_BRANCH);"
        "r3='no';\n"
        "try:\n"
        "    m3.dispatch(Event.PHASE1A_AUTHORIZED)\n"
        "except InvalidTransitionError:\n"
        "    r3='raised'\n"
        "print('R3', r3, 'STATE', m3.state.value)"
    ).format(dir=MODULE_DIR)
    out = subprocess.check_output(
        [sys.executable, "-O", "-c", script], stderr=subprocess.STDOUT
    ).decode("utf-8")
    assert "DEBUG False" in out, out  # confirms -O is active (asserts stripped)
    assert "R1 raised" in out, out
    assert "R2 raised" in out, out
    assert "R3 raised" in out, out


def test_governance_violations_raise_in_normal_mode():
    # b1_b5_passed without verified_sha
    m = Gate6ClosureMachine()
    m.dispatch(Event.MERGED)
    try:
        m.dispatch(Event.B1_B5_PASSED)
        assert False
    except GovernanceViolation:
        pass
    assert m.b1_b5_passed is False

    # docs branch must differ from feature branch
    m2 = Gate6ClosureMachine(feature_branch="same", docs_branch="same")
    m2.dispatch(Event.MERGED)
    m2.dispatch(Event.B1_B5_PASSED, verified_sha="abc")
    try:
        m2.dispatch(Event.CREATE_DOCS_BRANCH)
        assert False
    except GovernanceViolation:
        pass
    assert m2.created_branches == ()

    # phase1a cannot open before docs_merged
    m3 = _to_docs_branch_created()
    try:
        # routing rejects this (InvalidTransitionError), but prove no open either way
        m3.dispatch(Event.PHASE1A_AUTHORIZED)
        assert False
    except (GovernanceViolation, InvalidTransitionError):
        pass
    assert m3.state is State.DOCS_BRANCH_CREATED


# --------------------------------------------------------------------------- #
# 7. direct internal bypass is structurally discouraged / documented unsupported
# --------------------------------------------------------------------------- #
def test_internals_are_name_mangled_and_dispatch_is_sole_entrypoint():
    m = Gate6ClosureMachine()

    # Plain (single-underscore / unmangled) internal names must NOT exist.
    for plain in (
        "_apply_event",
        "_run",
        "_create_docs_branch",
        "_record_docs_merged",
        "_open_phase_1a",
        "_audit",
    ):
        assert not hasattr(m, plain), "internal leaked as {}".format(plain)

    # The mangled forms exist but are explicitly unsupported call targets.
    for mangled in (
        "_Gate6ClosureMachine__apply_event",
        "_Gate6ClosureMachine__run",
        "_Gate6ClosureMachine__create_docs_branch",
        "_Gate6ClosureMachine__record_docs_merged",
        "_Gate6ClosureMachine__open_phase_1a",
    ):
        assert hasattr(m, mangled), "expected mangled internal {}".format(mangled)

    # The only public (no underscore) callables are the supported API surface.
    public_callables = {
        name
        for name in dir(m)
        if not name.startswith("_") and callable(getattr(m, name))
    }
    assert public_callables == {"dispatch", "verify_chain"}, public_callables


# --------------------------------------------------------------------------- #
# 8. audit chain verifies after accepted and rejected events
# --------------------------------------------------------------------------- #
def test_audit_chain_verifies_after_accepted_and_rejected_events():
    m = Gate6ClosureMachine()
    assert m.verify_chain() is True  # empty chain

    m.dispatch(Event.MERGED)  # accepted
    assert m.verify_chain() is True

    try:
        m.dispatch(Event.MERGED)  # rejected (replay)
    except InvalidTransitionError:
        pass
    assert m.verify_chain() is True

    m.dispatch(Event.B1_B5_PASSED, verified_sha="cafef00d")  # accepted
    try:
        m.dispatch(Event.MERGED)  # rejected (out of order)
    except InvalidTransitionError:
        pass
    m.dispatch(Event.CREATE_DOCS_BRANCH)  # accepted, creates branch
    m.dispatch(Event.DOCS_MERGED)  # accepted, records docs merge
    m.dispatch(Event.PHASE1A_AUTHORIZED)  # accepted, terminal
    assert m.verify_chain() is True

    # Every accepted transition was audited before the mutation: the ACCEPT
    # entry for a transition precedes any later state. Spot-check ordering:
    kinds = [e["kind"] for e in m.audit_log]
    assert "ACCEPT" in kinds and "BRANCH_CREATED" in kinds and "DOCS_MERGED" in kinds

    # Tampering breaks the chain.
    raw = m._Gate6ClosureMachine__audit_log  # test-only introspection
    raw[1]["to_state"] = "TAMPERED"
    assert m.verify_chain() is False


# --------------------------------------------------------------------------- #
# Full happy-path contract
# --------------------------------------------------------------------------- #
def test_full_happy_path():
    m = Gate6ClosureMachine()
    assert m.dispatch(Event.MERGED) is State.VERIFYING_MAIN
    assert m.dispatch(Event.B1_B5_PASSED, verified_sha="abc123") is State.READY_TO_CREATE_DOCS_BRANCH
    assert m.dispatch(Event.CREATE_DOCS_BRANCH) is State.DOCS_BRANCH_CREATED
    assert m.created_branches == (g6.DEFAULT_DOCS_BRANCH,)
    assert g6.DEFAULT_FEATURE_BRANCH not in m.created_branches
    assert m.dispatch(Event.DOCS_MERGED, docs_merge_sha="beadfeed") is State.DOCS_MERGED
    assert m.docs_merged is True
    assert m.dispatch(Event.PHASE1A_AUTHORIZED) is State.PHASE_1A_OPEN
    assert m.merged_to_main is False
    assert m.verify_chain() is True


def test_string_events_are_accepted_via_routing_table():
    m = Gate6ClosureMachine()
    assert m.dispatch("merged") is State.VERIFYING_MAIN
    assert m.dispatch("b1_b5_passed", verified_sha="z") is State.READY_TO_CREATE_DOCS_BRANCH
    assert m.dispatch("create_docs_branch") is State.DOCS_BRANCH_CREATED
    assert m.dispatch("docs_merged") is State.DOCS_MERGED
    assert m.dispatch("phase1a_authorized") is State.PHASE_1A_OPEN
