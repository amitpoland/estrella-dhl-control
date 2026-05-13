# ADR-011: Adopt persistent multi-agent engineering cell

Status: Accepted
Date:   2026-05-10
Phase:  governance — supersedes ad-hoc per-session orchestration

## Context

The DL-A through DL-F3.5 campaigns shipped 17 phase commits across
roughly seven months of session work. Each campaign succeeded but
exposed a recurring failure pattern *between* campaigns:

- Every new session re-derived ownership ("which role owns the
  webhook handler?") from `git log` and source files.
- Every new session re-discovered open debt ("there's no carrier
  UI yet") that earlier sessions had already observed.
- Every new session re-explained the rollout posture ("flags are
  default-off; live AWB never persisted") to the same Coordinator.
- Strategic and execution work mixed in long sessions, producing
  drift the rollback doctrine had to clean up.

The root cause is **session-bound state**: `engineering/charter.md`
defines the cosmology of roles, but no artifact carries
*operational state* across sessions. The system can describe what
roles exist but cannot describe what they currently own or what
mode they should be operating in.

## Decision

Adopt a three-file operating system layered on top of the
existing charter and ADR system:

1. **`.claude/org/roles.md`** — routing table. Each role gets a
   path-glob allowlist, a denylist, trigger conditions, and review
   obligations. This makes the charter's role names *operational*
   (who edits what; who reviews what; who never touches what).

2. **`.claude/org/program_board.md`** — persistent workstream
   state. Every active workstream (DHL workflow, dashboard,
   customs/PZ, wFirma, DSK forward, cowork action runner,
   newsletter, etc.) gets a row with State / Owner / Tests /
   Telemetry / UI / Debt / Live-risk-gate columns. Updated at
   every phase commit. New sessions read this row by row.

3. **`.claude/org/execution_modes.md`** — three-mode contract:
   PRE-IMPLEMENTATION, IMPLEMENTATION, RELEASE. Each mode declares
   its goal, allowed actions, forbidden actions, required outputs,
   and exit condition. The Coordinator declares mode at session
   start. **No mode = no work.**

These three files together replace ad-hoc session orchestration
with persistent program-level state.

## Boundaries (what this ADR does NOT do)

This ADR explicitly **does not** introduce:

- Background agent orchestration ("agents chatting forever").
- Recursive self-expansion (agents spawning agents without
  Coordinator approval).
- Auto-merging or auto-commit by reviewers.
- Multiple concurrent in-flight implementation lanes (the
  Coordinator may *spawn* parallel reviewers, but only one
  Implementation Engineer edits at a time per phase).
- A new model tier or new role beyond what `charter.md` already
  names.

The system stays at the abstraction level the operator approved.
Future ADRs may extend it; this one freezes the current scope.

## Authority

- The Coordinator is the only role that may transition modes.
- The no-self-approval rule (`charter.md`) holds: a reviewer
  signs off on findings, not on their own implementation.
- A row on `program_board.md` enters `release` only on Coordinator
  decision; flips to `live-shadow` or `live-prod` require
  Production Readiness Reviewer + Operator Safety Reviewer
  sign-off (per the charter authority matrix, unchanged).

## Consequences

Positive:
- New sessions orient by reading `program_board.md` instead of
  by replaying `git log`.
- Mode declarations make drift visible (a session that started in
  IMPLEMENTATION but produced no commit is a clear signal).
- Reviewer triggers are deterministic (no role activates because
  someone "felt like it"; activation flows from path globs).
- Governance debt is named in one place.

Negative:
- Three new files to keep updated. The mitigation is to make
  updates part of the phase-commit ritual, so the state cannot
  drift more than one commit behind reality.
- Risk of bureaucracy. Mitigated by the dry-run protocol in
  `execution_modes.md`: the first PRE-IMPLEMENTATION run produces
  an artifact the operator evaluates *before* the system
  hardens. If it feels heavy, simplify before institutionalising.

## Verification

This ADR is verified by:

1. The three files exist at `.claude/org/`.
2. `engineering/charter.md` carries a footer pointing at `org/`.
3. The first PRE-IMPLEMENTATION dry-run is filed at
   `.claude/org/dry_runs/2026-05-10-pre-implementation.md` and
   the operator evaluates it before the next IMPLEMENTATION
   session opens.

## Related

- `ADR-001` — carrier abstraction (sets the technical scope this
  governs).
- `ADR-010` — default-OFF feature flags (the discipline this
  operating system enforces persistently).
- `engineering/charter.md` — role cosmology.
- `engineering/session-discipline.md` — superseded in part:
  "strategic vs execution" survives, but the new three-mode
  contract is the canonical definition.
