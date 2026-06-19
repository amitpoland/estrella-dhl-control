# Gate 6 closure — #630 → Phase 1A state machine

Governance artifact (NOT production code; lives under `docs/`, excluded from the
`service/app/**` production robocopy). It encodes and mechanically tests the
post-merge branch-lifecycle rule for closing PR #630 and authorizing Phase 1A.

## Lifecycle modeled

```
WAITING_FOR_MERGE           --merged-->              VERIFYING_MAIN
VERIFYING_MAIN              --b1_b5_passed-->        READY_TO_CREATE_DOCS_BRANCH  (records verified_sha)
VERIFYING_MAIN              --b1_b5_failed-->        HALT_ESCALATE                (terminal; no branch/artifact)
READY_TO_CREATE_DOCS_BRANCH --create_docs_branch-->  DOCS_BRANCH_CREATED          (creates docs branch)
DOCS_BRANCH_CREATED         --docs_merged-->         DOCS_MERGED                  (records docs merge)
DOCS_MERGED                 --phase1a_authorized-->  PHASE_1A_OPEN                (terminal; opens Phase 1A)
```

Events: `merged`, `b1_b5_passed`, `b1_b5_failed`, `create_docs_branch`,
`docs_merged`, `phase1a_authorized`.

`OPERATOR_TRANSITIONS` is the sole operator routing table. Terminal states
(`PHASE_1A_OPEN`, `HALT_ESCALATE`) are absorbing. Unknown, replay, and
out-of-order events reject with `InvalidTransitionError`. The machine never
writes the feature branch and never merges to `main` — `merged` and
`docs_merged` are inbound *notifications* of operator-performed merges, not
actions the machine takes.

**Two distinct merge gates (G2).** Creating the docs branch
(`create_docs_branch`) is not the same as merging it (`docs_merged`). Phase 1A
keys off the *docs merge*, not the branch creation: `phase1a_authorized` is
rejected in `DOCS_BRANCH_CREATED` and only legal once the machine is in
`DOCS_MERGED`. This guards the #626 class — a docs/closure branch that is
created but never actually reaches `main` cannot unlock the next phase.

**Missing SHA is retryable, not terminal (G1).** A `b1_b5_passed` without a
`verified_sha` raises `GovernanceViolation` but leaves the machine in
`VERIFYING_MAIN` — the operator supplies the SHA and re-dispatches. Likewise a
missing merge simply leaves the machine in `WAITING_FOR_MERGE` indefinitely.
The *only* terminal halt is an actual `b1_b5_failed`, which routes to
`HALT_ESCALATE` before any branch or artifact is created.

## Supported entrypoint contract (BLOCKER 2)

**`dispatch(event, **payload)` is the ONLY supported public entrypoint that may
mutate the machine.** Read-only accessors (`state`, `audit_log`,
`created_branches`, `verified_sha`, `b1_b5_passed`, `verify_chain`,
`merged_to_main`) are the rest of the surface.

True internals are name-mangled (`__run`, `__apply_event`, `__create_docs_branch`,
`__record_docs_merged`, `__open_phase_1a`, `__audit`). They are not reachable as plain attributes; the
mangled forms (`_Gate6ClosureMachine__apply_event`, …) exist but calling them is
**explicitly unsupported and out of contract**. Name-mangling is a structural
deterrent, not a hard security boundary — there is no in-process way to make a
private method uncallable in Python, so the contract is documented here and
enforced by `test_internals_are_name_mangled_and_dispatch_is_sole_entrypoint`,
which pins the public surface to exactly `{dispatch, verify_chain}`.

## Fail-closed governance (BLOCKER 1)

No `assert` guards any governance decision (asserts vanish under `python -O`).
Every precondition is an explicit `if/raise` (`GovernanceViolation`). Enforced in
`__create_docs_branch` and friends:

- `DOCS_BRANCH != FEATURE_BRANCH` (branch authority)
- `B1-B5 passed` before any docs branch is created
- `verified_sha` exists before any docs branch is created
- `docs_merged` recorded only after the docs branch was created off this machine
- Phase 1A cannot open unless the docs branch was created, the docs merge is on record, and verification is on record

`test_module_has_no_assert_statements` (AST scan) + `test_governance_guards_raise
_under_optimized_mode` (real `python -O` subprocess) prove the guards survive
optimization.

## Audit

Append-only SHA-256 hash chain. An audit entry is written **before** every
accepted state mutation and **before** every rejected raise. `verify_chain()`
recomputes and validates the chain; it stays valid after both accepted and
rejected events and detects tampering.

## Running

```
python -m pytest docs/gate6-630-closure/test_gate6_closure_machine.py
python -O -m pytest docs/gate6-630-closure/test_gate6_closure_machine.py
```
