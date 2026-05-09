# Session Discipline

Long Claude Code sessions degrade in predictable ways:
context poisoning, drift across goals, accumulated assumptions,
self-justification loops. This doc names the discipline that
keeps a session sharp and bounded.

## Two session types

| Type | Purpose | Model | Length | Output |
|---|---|---|---|---|
| **Strategic session** | Architecture, rollout planning, risk inspection, redesign, production decisions, multi-agent inspection | Opus 4.7 (coordinator) + Opus / Sonnet specialists in parallel | One sitting; tight scope | A phased roadmap, an ADR, a go/no-go decision |
| **Execution session** | Single small commit: tests, route work, schema migration, bug fix, doc update | Sonnet 4.6 | One sitting; one commit | A diff that lands cleanly with carrier suite + `make verify` green |

**Never mix the two.** A session that started as "implement Phase
1" and pivots into "redesign the locking strategy" must STOP,
land any in-flight commit, and re-open the redesign as a fresh
strategic session. Mixing strategic and execution work is the
single biggest cause of drift.

## Per-session rules

### Strategic sessions

- Begin with a `/context` block stating: scope, baseline commit,
  agents to spawn, deliverable shape.
- Spawn agents in parallel. Read-only by default.
- Coordinator synthesises. Implementation Engineer is **not**
  spawned during a strategic session.
- End with a written deliverable (phased plan, ADR, decision).
  No code committed unless that deliverable is itself a doc
  (e.g., this Org Bootstrap session).
- Do NOT extend a strategic session into "and now let's
  implement Phase 1." Open a fresh execution session.

### Execution sessions

- Begin with the exact `/context` block produced by the most
  recent strategic session.
- Engineer implements ONE commit only.
- All gates run at HEAD before commit.
- Reviewers (QA, Security, Release) re-engage briefly on the
  resulting diff.
- Coordinator approves Phase N+1 fire from a fresh session — not
  from the just-completed execution session.

### Length cap

A session that runs longer than ~3 hours of compute time should
be paused and resumed cleanly. Symptoms of context poisoning:
- Agent re-reads files it has already loaded earlier.
- Agent contradicts a decision recorded earlier in the session.
- Agent self-justifies why a known-bad pattern is "fine here."

When any symptom appears: stop, capture state in writing, end the
session.

## Session handoff format

When ending a session that has more work to do, the final message
must include:

1. **Repo state**: branch + commit hash + working-tree status.
2. **What landed**: list of files changed + tests added.
3. **What's next**: the exact `/context` block for the next
   session.
4. **Open questions**: anything the next session must resolve
   before code lands.

This handoff is what makes long-running campaigns survive.

## Cross-reference: what this doc does NOT cover

- The agent organisation: see `charter.md`.
- Per-phase gates: see `promotion-gates.md`.
- What to do when a phase fails: see `rollback-doctrine.md`.
- Cutover-time gate: see `production-readiness-checklist.md`.
- Decision history: see `../adr/`.
