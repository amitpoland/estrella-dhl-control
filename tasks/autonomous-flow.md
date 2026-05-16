# Future Autonomous Campaign Flow

> Forward-looking document. Describes how the runner v2 supports a
> supervised-autonomous workflow for Claude Code campaigns.
> Status: design intent · 2026-05-16.

---

## 1 — What "autonomous" means here

The runner is **supervised-autonomous**, not unattended-autonomous:

| Decision | Autonomous? | Why |
|---|---|---|
| Read state, pick next batch | YES | Pure read |
| Track batch transitions | YES | File-based; auditable |
| Detect stuck batches | YES | Read-only inspection |
| Render dashboard | YES | Pure read |
| Generate rollback command | YES | Deterministic from state |
| Update state file | YES (atomic write) | Single writer, single file |
| Open PR | YES (Claude session does this) | Operator reviews before merge |
| Run tests locally | YES | No production touch |
| Merge PR | **NO** | Operator gates this |
| Deploy to production | **NO** | Operator runs robocopy + restart |
| Mutate `.env` | **NO** | Forbidden |
| Mutate accounting/PZ engine | **NO** | Forbidden |

The line is **always**: read freely, write to state freely, but every
externally-visible mutation (PR merge, deploy, production data) requires an
operator action.

---

## 2 — End-to-end flow for one batch

```
┌──────────────────────────────────────────────────────────────────────────┐
│ OPERATOR    →  CLAUDE SESSION                  →  RUNNER STATE FILE     │
└──────────────────────────────────────────────────────────────────────────┘

[1] "Start B<N>"
                  ─→ next <C>
                       ─→ reads state
                       ─→ returns next ready batch
                       ─→ recommends action

[2]               ─→ git checkout main; git checkout -b feat/...
                  ─→ implement + add tests + run locally
                  ─→ git push; gh pr create
                  ─→ update <C> B<N> --status pr_open --pr <n>
                       ─→ writes state

[3] "Merge it"
                  ─→ operator runs `gh pr merge`
                  ─→ update <C> B<N> --status merged --sha <merge_sha>
                       ─→ writes state

[4] "Deploy"
                  ─→ operator runs robocopy + restart
                  ─→ deploy <C> B<N> --sha <new_head> --previous-main-sha
                                     --robocopy-exit-codes ... --restart-seconds
                       ─→ writes state with full audit metadata

[5]               ─→ run_smoke.py
                  ─→ smoke <C> B<N> --report <path>
                       ─→ writes state (status → smoked)

[6] "Verify"
                  ─→ verify <C> B<N>
                       ─→ reads gates
                       ─→ returns ok=true (or missing gates)
```

The Claude session can run steps 1, 2 (excluding push), 5 fully
autonomously. Steps 3 (merge), 4 (deploy), and the `git push` in step 2
require explicit operator approval. The state file records every
transition; the runner's `dashboard` and `doctor` surface anomalies.

---

## 3 — Failure modes and recovery

### Failure: tests fail locally before PR

- Don't push.
- Don't update state to `pr_open`.
- If batch is `active`, optionally `block --reason "tests failed: <summary>"`.
- After fix: `unblock` and continue.

### Failure: PR review rejects

- Update state: `update <C> B<N> --status active` (back to in-progress).
- Or: `pause <C> B<N> --reason "rework after review"`.

### Failure: merge succeeds but deploy fails

- The `deploy` subcommand was never called (deploy did not finish).
- Batch is stuck in `merged`.
- Doctor will flag it after 24h.
- Recover: re-run deploy; OR rollback the merge if the bug is severe.

### Failure: deploy succeeds but smoke fails

- Don't call `smoke`. Batch stays in `deployed`.
- Doctor flags after 24h.
- Recover: investigate failure; if production is impacted, run rollback.
- Rollback command is auto-generated from state.

### Failure: stack-into-stack misroute

- `doctor` flags it via `branch_stack.warning`.
- Recover: open a forward-merge PR from the stack tip → main.
- See L-018 / L-029 / L-035 in `tasks/lessons.md`.

### Failure: state file corrupted

- Every save uses atomic `.tmp` + `replace`.
- If corrupted, restore from git: `git checkout tasks/campaign-state.json`.
- The file is single-writer; concurrent writes are not supported.

---

## 4 — Multi-campaign coordination

Multiple active campaigns can be tracked simultaneously. The runner
treats them independently:

- `list` — shows all campaigns.
- `dashboard` — shows next batches per active campaign, plus all blockers
  and stuck batches across all campaigns.
- `next <C>` — campaign-scoped.
- `doctor` — global scan.

If an operator runs two Claude sessions on different campaigns
simultaneously: **single-writer assumption applies**. Do not have two
sessions writing state concurrently. Sequential is safe.

---

## 5 — Phase 6F under autonomous flow

The Phase 6F implementation campaign (when operator approves §10.1-§10.3
of the architecture doc) will follow this flow:

```
6F.1 → schema (new SQLite, additive)         AUTO_SAFE
6F.1.5 → contract tests pin no-mutation      AUTO_SAFE (new)
6F.3 → read-only /breakdown endpoint         AUTO_SAFE
6F.2 → backfill from legacy table            AUTO_SAFE (read-only of legacy)
6F.4 → UI panel                              AUTO_SAFE
6F.5 → /post dual-write, flag OFF            NEEDS_SECURITY_REVIEW
6F.6 → settlement close + FX delta           NEEDS_SECURITY_REVIEW
6F.7 → legacy cleanup                        NEEDS_SCHEMA_APPROVAL
```

The runner tracks each as a separate batch. The `NEEDS_*` classifications
translate to explicit `pause` events when the operator reaches that batch.
Doctor will flag if the operator forgets to pause a `NEEDS_*` batch.

---

## 6 — Boundaries that will NOT be crossed

The following will never be implemented in the runner — they are
permanently out of scope:

| Capability | Why excluded |
|---|---|
| Daemon / scheduler thread | File-based orchestration only (architecture target) |
| Auto-merge bot | Operator must approve every merge |
| Auto-deploy | Operator must approve every deploy |
| Direct DB writes | Runner does not touch production SQLite/etc. |
| `.env` mutation | Hard rule |
| HTTP server | Runner is a CLI, not a service |
| Async execution | Single-threaded, no asyncio loops |
| Concurrent state writes | Single-writer assumption |
| External integrations (Slack, email, GitHub webhooks) | Runner is offline-only |

Any future ask to add one of these requires either:
1. A new orchestrator layer above the runner (the runner stays unchanged), or
2. Explicit operator approval to relax the corresponding contract test.

---

## 7 — Roadmap for the next year

| Quarter | Capability | Status |
|---|---|---|
| 2026 Q2 | Campaign runner v2 (this commit) | DELIVERED |
| 2026 Q2 | Phase 6F architecture approval | OPERATOR-GATED |
| 2026 Q3 | Phase 6F batches 6F.1-6F.4 (additive) | PLANNED |
| 2026 Q3 | B3 / B6 security + schema review | OPERATOR-GATED |
| 2026 Q4 | Phase 6F batches 6F.5-6F.7 (with flags) | PLANNED |
| 2027 Q1 | FX override (MDC-071) revisit | FORBIDDEN_NOW; revisit only via separate landed-cost campaign |

---

## 8 — Closure

The runner v2 is a **floor**, not a ceiling. It makes campaign work
deterministic, auditable, and rollback-safe — but it does not replace
operator judgment at merge, deploy, and approval gates. The runner exists
to ensure no batch falls through the cracks; the operator exists to ensure
every batch that lands is the right one.
