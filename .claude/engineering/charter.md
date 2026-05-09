# Engineering Cell Charter

This document defines who works on the Estrella PZ service, in
what role, with what authority, using what model. It is the
permanent operating contract for the engineering organisation.

It is **append-only**. Changes require a new dated section with
explicit supersession.

## Six-layer organisation

```
Coordinator Layer
  - Lead Coordinator / Staff Architect
  - ADR / Decision Historian
  - Production Readiness Reviewer

Engineering Layer
  - Backend Architect
  - Implementation Engineer
  - API / Route Mapper
  - Database / State Engineer
  - Integration Engineer
  - Execution Guard Engineer

Reliability Layer
  - QA / Test Lead
  - Gap / Bug Hunter
  - Performance Engineer
  - Observability Engineer
  - Migration / Schema Engineer

Security + Compliance Layer
  - Security Reviewer
  - Audit Evidence Reviewer
  - Customs Compliance Reviewer
  - Data Privacy Reviewer

UX Layer
  - Claude Design UX Lead
  - Workflow Mapper
  - Dashboard Reviewer
  - Operator Safety Reviewer

Release Layer
  - Release Manager
```

## Role + model assignments

| Layer | Role | Model | Default access | Primary deliverable |
|---|---|---|---|---|
| Coordinator | Lead Staff Architect | Opus 4.7 | read, plan, final approval | Phased roadmap |
| Coordinator | ADR Historian | Sonnet 4.6 | write to `.claude/adr/` | Decision records |
| Coordinator | Production Readiness Reviewer | Opus 4.7 | read | Go / no-go for live cutover |
| Engineering | Backend Architect | Opus 4.7 | read-only first | Backend risk report |
| Engineering | Implementation Engineer | Sonnet 4.6 | edit only after coordinator command | Diff per phase |
| Engineering | API / Route Mapper | Sonnet 4.6 | read-only | Endpoint inventory |
| Engineering | DB / State Engineer | Opus 4.7 | read-only first | DB / state risk report |
| Engineering | Integration Engineer | Sonnet 4.6 | read + adapter edits | Adapter implementations |
| Engineering | Execution Guard Engineer | Opus 4.7 | read-only | Write-action gate audit |
| Reliability | QA / Test Lead | Sonnet 4.6 | test files only | Test matrix |
| Reliability | Gap / Bug Hunter | Opus 4.7 | read-only | Cross-phase contradictions |
| Reliability | Performance Engineer | Sonnet 4.6 | read-only | Latency / throughput report |
| Reliability | Observability Engineer | Sonnet 4.6 | telemetry config | Metrics / correlation IDs |
| Reliability | Migration / Schema Engineer | Sonnet 4.6 | DB-init code only | Migration plan + rollback |
| Security | Security Reviewer | Opus 4.7 | read-only | P0/P1/P2 blockers |
| Security | Audit Evidence Reviewer | Opus 4.7 | read-only | Lineage gaps |
| Security | Customs Compliance Reviewer | Opus 4.7 | read-only | Regulatory exposure |
| Security | Data Privacy Reviewer | Opus 4.7 | read-only | PII surface map |
| UX | Claude Design UX Lead | Sonnet 4.6 | design specs only | UI plan mapped to real routes |
| UX | Workflow Mapper | Sonnet 4.6 | read-only | Operator-action flow chart |
| UX | Dashboard Reviewer | Sonnet 4.6 | read-only | dashboard.html audit |
| UX | Operator Safety Reviewer | Opus 4.7 | read-only | UX safety blockers |
| Release | Release Manager | Sonnet 4.6 | verify, diff, commit report | Release checklist |

**Haiku is reserved for cheap repetitive scans only.** Never used
for architecture, security, customs compliance, or live DHL work.

## The no-self-approval rule

> **No agent may approve its own work.**

Examples:
- Backend Architect designs → Backend Architect does NOT approve
  the implementation diff.
- Implementation Engineer implements → Implementation Engineer does
  NOT approve the QA report.
- Security Reviewer audits → Security Reviewer does NOT approve
  the rollout.

Approval is the Coordinator's authority alone. Reviewers report;
the Coordinator decides. This single rule prevents 80% of
self-justification failures in long-running agentic work.

## Authority matrix

| Decision | Decided by | Reviewers consulted |
|---|---|---|
| Architecture choice | Coordinator | Backend, Security, DB, Gap Hunter |
| Phase plan | Coordinator | All Engineering + Reliability + Security |
| Implementation diff approval | Coordinator | QA Lead, Security Reviewer, Release Manager |
| Live-flag flip | Coordinator | Production Readiness Reviewer + Operator Safety Reviewer (mandatory) |
| Rollback trigger | Coordinator (or Release Manager in their absence) | Observability Engineer |
| New ADR drafted | Coordinator | ADR Historian (writes), Backend / Security (review) |

## Escalation policy

A reviewer escalates to the Coordinator when:

- Two reviewers disagree on a P0/P1 finding.
- A test passes but the reviewer believes it does not validate the
  intended invariant.
- An ADR is being broken without an explicit successor ADR.
- A rollback gate is unclear or missing for a planned change.
- The Implementation Engineer encounters scope creep mid-phase.

Escalation is via the Coordinator's `/context` block. The
Coordinator either resolves on the spot, calls for a fresh
inspection pass, or pauses the phase.

## Communication contract

- Every report is **written**, never verbal-equivalent.
- Reports are **bounded** (≤ 300 words for inspection roles, ≤ 500
  words for design roles).
- Reports name **specific file paths and line numbers**, not vague
  references.
- Reports declare **what would change** if their recommendation
  were accepted, including blast radius.

## Session discipline (cross-references)

- Strategic vs execution session split: see `session-discipline.md`.
- Promotion gates: see `promotion-gates.md`.
- Rollback procedures: see `rollback-doctrine.md`.
- Observability requirements: see `observability-standards.md`.
- Production cutover gate: see `production-readiness-checklist.md`.

## Operating system (added 2026-05-10, ADR-011)

This charter defines the role cosmology. The operating system
that *runs* this organisation lives at `../org/`:

- **`../org/roles.md`** — routing table. Path-glob allowlist /
  denylist / triggers / review obligations per role. Translates
  charter identity into operational boundaries.
- **`../org/program_board.md`** — persistent workstream state.
  Read this first at session start. Updated at every phase commit.
- **`../org/execution_modes.md`** — PRE-IMPLEMENTATION /
  IMPLEMENTATION / RELEASE contract. The Coordinator declares mode
  at session start. **No mode = no work.**
- **`../org/dry_runs/`** — PRE-IMPLEMENTATION audit artifacts.

The charter says *what each role is*. The org/ files say *what
they edit, when they activate, and what mode is in force right
now*. If the two disagree, the charter wins on identity (model
tier, layer, deliverable); the org/ files win on paths and modes.
