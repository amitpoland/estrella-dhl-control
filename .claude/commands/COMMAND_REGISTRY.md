# COMMAND_REGISTRY.md — Atlas V2 Slash Commands

**Source of truth for slash commands version-controlled in `.claude/commands/`.**
Updated 2026-07-17. 15 project commands.

> **Capability legend:**
> - **READ-ONLY** — inspects/reports; edits nothing.
> - **REVIEW-ONLY** — structured review; edits nothing.
> - **WRITE-CAPABLE** — may edit files / issue live operations (requires care + gates).
> - **DEPLOY-CAPABLE** — triggers a production deployment path (highest risk).

---

## Quick matrix

| Command | Capability | Purpose (1-line) | Operator approval |
|---|---|---|---|
| `/feature` | WRITE-CAPABLE | Canonical DISCOVERY→PLAN→IMPLEMENT→VERIFY→CLOSE entry point for all feature work | required before merge |
| `/inspect-route` | READ-ONLY | Inspect an endpoint's payload/validation/UI-safety | not required (read-only) |
| `/pz-audit-roadmap` | READ-ONLY | Full read-only codebase audit → decision-ready roadmap | not required (read-only) |
| `/cowork-integration` | READ-ONLY (reference) | Cowork architecture + draft-validation reference | not required |
| `/engineering-lessons` | READ-ONLY (reference) | Full engineering-lessons narratives | not required |
| `/review-execution` | REVIEW-ONLY | Execution-safety review (engine use, idempotency, audit log, readiness) | not required |
| `/patch` | WRITE-CAPABLE | Smallest safe code patch for a task | required before merge/deploy |
| `/pz-shipment` | WRITE-CAPABLE | Run a live PZ shipment batch (process_batch + Cliq post) | required — live batch + Cliq |
| `/deploy` | DEPLOY-CAPABLE | Full production deploy via the mandatory 7-agent gate | required — production mutation |
| `/pz-loop` | WRITE-CAPABLE (loop) | Engineering OS bounded iterative loop (`00 §13`); refuses to start without OBJECTIVE / STOP_CONDITIONS / ITERATION_CAP / VERIFY_CMD | required for any mutating iteration + before merge |
| `/authority-census` | READ-ONLY | Audit authority ownership across modules (HTML/JSX/routes) | not required (read-only) |
| `/context-lite` | READ-ONLY | Lightweight context load for a simple/single-domain task | not required (read-only) |
| `/context-pr` | READ-ONLY | PR-scoped context load | not required (read-only) |
| `/context-task` | READ-ONLY | Task-scoped (multi-domain) context load | not required (read-only) |
| `/implement-slice` | WRITE-CAPABLE | Execute one named campaign slice under the implement-guard | required before merge |

> **Backfill note (2026-07-17):** `/authority-census`, `/context-lite`, `/context-pr`,
> `/context-task`, and `/implement-slice` were added to `.claude/commands/` after the
> 2026-06-20 registry update and are recorded here as quick-matrix rows to restore the
> source-of-truth count (9 → 15). Full per-command detail sections for these five are a
> **SCHEDULED** backlog item, not written in this change.

---

## Per-command detail

### `/feature` — WRITE-CAPABLE ⚠️
- **Purpose:** Canonical entry point for all new feature work. Executes the mandatory five-phase protocol (DISCOVERY → PLAN → IMPLEMENT → VERIFY → CLOSE) defined in `.claude/TASK_EXECUTION_PROTOCOL.md`.
- **Mandatory subagents:** `gap-detection` (DISCOVERY), `reviewer-challenge` (PLAN, mandatory), `final-consistency-review` (VERIFY), `flow-context-keeper` (CLOSE). Substitution requires GATE 5 disclosure.
- **Safe usage:** Every new feature, regardless of size. Pass the task as `$ARGUMENTS` (one line or paragraph).
- **Forbidden usage:** Skipping `reviewer-challenge`; skipping GATE 1 checklist; opening a PR before GATE 1 is satisfied; editing files not on the plan list.
- **Capability:** WRITE-CAPABLE (edits files during IMPLEMENT, opens PRs, commits). **Operator approval required before merge.**
- **Invocation examples:** `/feature Add proforma snapshot columns` · `/feature Wire DHL lane-readiness to V2` · `/feature Add email idempotency guard`

### `/inspect-route` — READ-ONLY
- **Purpose:** Inspect an endpoint — identify payload/validation, check if safe for UI.
- **Safe usage:** Pre-implementation discovery; verifying an endpoint before wiring a UI to it (e.g. confirming the 4 DHL endpoints before Sprint 31).
- **Forbidden usage:** Editing files (the command explicitly forbids edits).
- **Capability:** READ-ONLY.

### `/pz-audit-roadmap` — READ-ONLY
- **Purpose:** Scan the full PZ codebase and produce a decision-ready audit roadmap. Modifies nothing.
- **Safe usage:** Sprint planning, authority audits (e.g. the Sprint 31 authority audit).
- **Forbidden usage:** Any file modification; treating its roadmap as an authorization to deploy.
- **Capability:** READ-ONLY.

### `/cowork-integration` — READ-ONLY (reference)
- **Purpose:** Cowork architecture, flow, draft-type reference, and the Cowork result/validation rules.
- **Safe usage:** Understanding the Cowork → PZ Validation → PZ Automation → SMTP → Audit chain before touching any cowork-adjacent code.
- **Forbidden usage:** Not an actor — does not run cowork. Cowork must never send emails / choose recipients / attach files / mutate finance (per CLAUDE.md §9).
- **Capability:** READ-ONLY reference.

### `/engineering-lessons` — READ-ONLY (reference)
- **Purpose:** Full origin narratives, detection signals, and worked examples for Engineering Lessons A–K.
- **Safe usage:** Before any incident-driven fix; to apply Lesson I's 6-step framework.
- **Forbidden usage:** Reference only — no actions.
- **Capability:** READ-ONLY reference.

### `/review-execution` — REVIEW-ONLY
- **Purpose:** Review execution safety — confirm `execution_engine` used, no direct unsafe POST from UI, idempotency exists, `execution_log` written, readiness guards present.
- **Safe usage:** After any change touching the execution path; pairs with `security-write-action-reviewer`.
- **Forbidden usage:** Does not edit; does not run the engine.
- **Capability:** REVIEW-ONLY.

### `/patch` — WRITE-CAPABLE ⚠️
- **Purpose:** Make the smallest safe patch for a task (inspect first, edit only required files, no unrelated refactor).
- **Safe usage:** Small, scoped fixes after inspection. Pair with the implementation-review group afterward.
- **Forbidden usage:** Large refactors; touching forbidden domains (customs/accounting/inventory/wFirma/Lane A-B) without the safety review + deploy gate; merging or deploying on its own.
- **Capability:** WRITE-CAPABLE. **Operator approval required before any resulting change merges or deploys.**

### `/pz-shipment` — WRITE-CAPABLE ⚠️
- **Purpose:** Run a live PZ shipment batch — `make verify` → `process_batch()` → PDF+XLSX → Cliq post (and optional WorkDrive share links).
- **Safe usage:** Processing a real shipment when inputs are present and `make verify` passes. `process_batch()` is the only calculation path.
- **Forbidden usage:** Recomputing landed cost/freight/duty/notes outside the engine; posting local paths/localhost to Cliq; processing if `make verify` fails. Live external side effects (Cliq) — not for dry runs.
- **Capability:** WRITE-CAPABLE (live batch + Cliq post). **Operator approval required.**

### `/deploy` — DEPLOY-CAPABLE ⚠️⚠️
- **Purpose:** Trigger the full production deployment procedure (`service/docs/production_deployment_rule.md`). **Never skip any step. Never skip the 7-agent gate.**
- **Safe usage:** Production deploy AFTER: PR merged to main, the 7-agent gate returns READY-TO-DEPLOY, and the operator has authorized. Static-only deploys still run the full gate.
- **Forbidden usage:** Any deploy without the 7-agent gate; deploying a dirty tree; deploying engine/root files without the separate sync (Lesson J); bypassing a security block.
- **Capability:** DEPLOY-CAPABLE — highest risk. **Operator approval + full gate mandatory.**

### `/pz-loop` — WRITE-CAPABLE (loop) ⚠️
- **Purpose:** Run the Engineering OS **bounded iterative loop** for a stated task — the
  iterative counterpart to `/feature`'s linear protocol, for work that converges through
  repeated apply→verify cycles. All loop mechanics are governed by
  `.engineering-os/00_ENGINEERING_CONSTITUTION.md §13`; the command file is only the entry point.
- **Required inputs (refuses to start without all four):** `OBJECTIVE`, `STOP_CONDITIONS` (an
  aspirational phrase is not a stop condition), `ITERATION_CAP` (default 5, still must be stated),
  `VERIFY_CMD` (a real executable command). Also refuses if `TASK_STATE.md` shows a different task
  `IN_PROGRESS`, if canonical authority/ownership is unclear, or if the first action begins beyond
  an operator gate.
- **Safe usage:** Convergent diagnostic or implementation work with an objective verifier and an
  explicit cap. Each iteration applies the smallest change (`00 §12`) and classifies results under
  the Evidence Contract (`00 §11`).
- **Forbidden usage:** Starting without the four inputs; running past `ITERATION_CAP`; restarting
  solved work; crossing any operator gate (merge, deploy, production mutation, fiscal/wFirma
  write) inside an iteration. Do **not** create a `/loop` project command — `/pz-loop` is the only
  loop command (`/loop` is a reserved platform-level skill name; do not shadow it with a
  `loop.md` project command regardless).
- **Capability:** WRITE-CAPABLE for mutating iterations (READ-ONLY iterations run freely). GATE 1
  applies at loop exit before any PR opens; **operator approval required before any iteration that
  mutates production.**

---

## Safety rule (binding)

A slash command's capability tier is binding. READ-ONLY / REVIEW-ONLY commands may run
freely. WRITE-CAPABLE and DEPLOY-CAPABLE commands require explicit operator approval and,
for production, the full 7-agent deploy gate. No command — including `/deploy` — may bypass
a `deploy-security-reviewer` block.
