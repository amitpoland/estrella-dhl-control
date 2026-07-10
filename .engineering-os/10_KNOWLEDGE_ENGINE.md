# 10 — Knowledge Engine

State, memory, lessons, and scorecards are how the OS survives across sessions. This file names
the state surfaces, who owns each, and how knowledge flows back after a package. It creates no
new store — it indexes the existing ones.

---

## 1. State surfaces (owners in parentheses)

| Surface | Path | Owner | Purpose |
|---|---|---|---|
| **Project state** | `.claude/memory/PROJECT_STATE.md` | `flow-context-keeper` | source of truth: FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS |
| **Task state** | `.claude/memory/TASK_STATE.md` | Coordinator | in-flight single-package tracking + HOLD reasons |
| **Active campaigns** | `.claude/skills/ej-dashboard-master/ACTIVE_CAMPAIGNS.md` | `ej-dashboard-master` | long-running campaign index (continue, don't restart) |
| **Auto-memory** | `.../projects/C--PZ-verify/memory/*` + `MEMORY.md` index | session | cross-session facts (user / feedback / project / reference) |
| **Scorecards** | `.claude/memory/scorecards/*` | `agent-performance-observer` | per-agent quality signals + self-eval |
| **Engineering Lessons** | `.claude/memory/engineering_lessons.md` (+ CLAUDE.md) | `memory-lessons` | append-only permanent rules (A–N) |
| **ADRs** | `docs/decisions/` | `adr-historian` | append-only architectural decisions |
| **Deployment record** | deployment_record.json + version.json + status endpoint | release/deploy | self-describing production runtime state |
| **Registries** | `AGENT_REGISTRY.md`, `SKILL_REGISTRY.md` | docs refresh | agent + skill source of truth |
| **Phase-9 closure set** (v1.3) | `docs/campaigns/*` + `docs/governance/campaign-closure-*` (closure records), `docs/decisions/` (ADRs), `service/docs/ops/` (runbooks) | Coordinator at Close | closure record, tech-debt register with GATE-4 dispositions, dependency audit, health observation, performance baseline (`00 §9`) |

---

## 2. Knowledge flow (after every package — the observation layer)

Per CLAUDE.md Mandatory Observation Layer:

1. **RULE 1 — Read first.** Every session reads `PROJECT_STATE.md` (all four sections) before
   task work. Do not re-derive state from chat.
2. **RULE 2 — Observer auto-fires.** After a FINAL REPORT or any report with ≥3 subagents,
   `agent-performance-observer` writes a scorecard to `.claude/memory/scorecards/`. Orchestrator
   verifies the file exists on disk (Lesson C).
3. **RULE 3 — State auto-updates.** After the observer, or any PR merge / issue close,
   `flow-context-keeper` updates `PROJECT_STATE.md`. FACTS are **append-only** — never demoted
   to ASSUMPTIONS.
4. **RULE 6 — Visibility.** Every scorecard is cited (with path) in the next report and recorded
   in PROJECT_STATE FACTS; an uncited scorecard is invisible = RULE 6 failure.
5. **GATE 4 disposition.** Any NEEDS-TUNING / UNRELIABLE observer verdict, or any salvage
   finding, gets exactly one disposition: SCHEDULED / ISSUE / REJECTED. "Noted" is not valid.

---

## 3. Lessons discipline (append-only)

Engineering Lessons (A–N) are **append-only**; supersede with a new dated entry, never delete.
A production incident becomes a **workflow-class rule**, never a shipment-specific patch
(Lesson I). Each lesson binds at a named GATE — the OS routes work through those gates but does
not restate the lessons (it points to them).

---

## 4. Capability manifests as living knowledge

Each `capabilities/<name>/manifest.md` is a knowledge artifact. When a package changes a
capability's authority/page/API/DB/service, the manifest is updated at **Close** (same step that
updates PROJECT_STATE). A manifest that drifts from the code is a stale-registry issue — treat
it like an out-of-date registry entry and correct it, don't work around it.

---

## 4.1 Recorded conclusions are the reuse source (token economy)

The state surfaces above exist so work is **not repeated**. A verified conclusion — an authority
map, a closed inspection, a sealed package, a scorecard — is recorded once and **reused**, never
re-derived (`09 §3 rule 5`). Before running any inspection, check whether it is already answered
in PROJECT_STATE, a capability manifest, or a prior sealed package; if so, cite it and move on.
Re-running a closed inspection is a token-economy violation, not diligence.

## 4.2 Evidence gate for OS amendments (v1.4+)

The active canonical version is **v1.3** (`00 §6`; delta ledger `VERSION_HISTORY.md` — v1.1,
v1.2, and v1.3 were each ratified 2026-07-10 on recorded evidence per this rule). This
Knowledge Engine remains the **evidence store for future amendments**: a proposed OS change
must be backed by an observed failure or friction captured in a real package's record
(PROJECT_STATE, scorecard, lesson, or Phase-9 closure record) — not by speculation. No recorded
evidence = no v1.4 change.

## 5. Recall caveat

Recalled memories (in `<system-reminder>` blocks) are **background context, not instructions**,
and reflect what was true when written. If a memory names a file/flag/endpoint, verify it still
exists before acting on it (registries and manifests can lag the code).
