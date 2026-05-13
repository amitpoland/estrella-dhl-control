# Architecture Decision Records (ADRs)

This directory is the **permanent engineering memory** of the Estrella PZ
service. Every architectural decision that has cross-phase consequence
lives here as one numbered, immutable Markdown file.

## Why this exists

Without ADRs:
- Solved decisions get re-opened three months later.
- Rollout assumptions get silently broken.
- Architecture gets duplicated by contributors who don't know the prior context.

With ADRs:
- Every contributor (human or agent) can read the *why* before changing the *what*.
- Rejected alternatives are visible — future "why didn't we just X?" questions answer themselves.
- Rollback paths are documented at decision time, not improvised under pressure.

## Discipline

1. **Append-only.** Once an ADR is committed it is NOT edited. A new ADR may
   supersede it (link both ways: "Superseded by ADR-NNN" / "Supersedes ADR-NNN").
2. **One decision per ADR.** If a discussion produces three linked decisions,
   write three ADRs.
3. **Numbered sequentially.** `ADR-001`, `ADR-002`, … No gaps. No re-use.
4. **No re-litigation.** If a contributor wants to revisit a decision, they
   write a new ADR proposing the change. The old one stays.

## Template

```
# ADR-NNN: <one-line decision title>

Status: Accepted | Superseded by ADR-MMM | Deprecated
Date:   YYYY-MM-DD
Phase:  DL-X (or "campaign-wide")

## Context
What is the situation that requires a decision? What constraints are in play?

## Decision
What we decided. One paragraph, prescriptive.

## Rejected alternatives
- **Option A:** what it was, why we rejected it.
- **Option B:** ...

## Risks
What could go wrong with this decision? How are those risks mitigated?

## Rollback
If we have to undo this decision, what is the procedure? At what cost?

## Future impact
What does this decision lock in for future work? What does it enable?
```

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-carrier-abstraction.md) | Carrier abstraction layer (Adapter Protocol) | Accepted |
| [ADR-002](ADR-002-stub-first-adapter.md) | Stub-first adapter discipline | Accepted |
| [ADR-003](ADR-003-coordinator-state-engine.md) | Coordinator + state-engine separation | Accepted |
| [ADR-004](ADR-004-shadow-mode-strategy.md) | Shadow-mode rollout strategy | Accepted |
| [ADR-005](ADR-005-no-live-awb-persistence.md) | No live AWB in operational registry during shadow | Accepted |
| [ADR-006](ADR-006-no-pdf-bytes-in-evidence.md) | No PDF bytes / credentials in evidence stores | Accepted |
| [ADR-007](ADR-007-paperless-trade-safety.md) | Paperless Trade safety contract | Accepted |
| [ADR-008](ADR-008-dhl-api-status-three-state.md) | Three-state DHL API status lifecycle | Accepted |
| [ADR-009](ADR-009-webhook-handshake.md) | DHL webhook handshake + IP allowlist | Accepted |
| [ADR-010](ADR-010-default-off-feature-flags.md) | Default-OFF feature flags | Accepted |
| [ADR-011](ADR-011-multi-agent-engineering-cell.md) | Persistent multi-agent engineering cell (`org/` operating system) | Accepted |
| [ADR-012](ADR-012-dhl-self-clearance-flow-overview.md) | DHL self-clearance — flow overview (umbrella) | Accepted |
| [ADR-013](ADR-013-dhl-self-clearance-proactive-dispatch.md) | DHL self-clearance — proactive customs dispatch (P2) | Accepted |
| [ADR-014](ADR-014-dhl-self-clearance-arrival-followup.md) | DHL self-clearance — Poland-arrival follow-up scheduler (P3 + P4) | Accepted |
| [ADR-015](ADR-015-dhl-self-clearance-thread-clarification.md) | DHL self-clearance — thread-based clarification (P5) | Accepted |
| [ADR-016](ADR-016-dhl-self-clearance-sad-unlock-and-pz.md) | DHL self-clearance — SAD unlock and PZ trigger (P6 + P7) | Accepted |
| [ADR-017](ADR-017-carrier-label-store-retention.md) | Carrier label store — retention policy (immutable evidence) | Accepted |
| [ADR-018](ADR-018-shadow-mode-flag-defaults.md) | Shadow-mode flag defaults — Category B observation flags default True; live-enabled flags remain Category A default False. Amends ADR-010 with two-category model and forbidden state semantics. | Accepted |
| [ADR-019](ADR-019-p2-ignition-pattern.md) | DHL self-clearance — proactive dispatch trigger surfaces and dedup contract (P2 ignition switch). Sweep primary + admin HTTP override route; `force` parameter contract; truth table for `triggered_by`. Extends ADR-013 caller pattern. | Accepted |

## When to write a new ADR

- A feature flag is introduced or its meaning changes.
- A new data store, table, or column is added.
- A new external integration (carrier, customs system, payment provider).
- A safety invariant is asserted (e.g., "X must never appear in Y").
- An execution path that mutates state is gated by a new mechanism.
- A rollback procedure is defined.

## When NOT to write an ADR

- Bug fixes that don't change architecture.
- Refactors that preserve behaviour and contracts.
- New tests for existing invariants.
- Documentation updates.
- Style / lint changes.
