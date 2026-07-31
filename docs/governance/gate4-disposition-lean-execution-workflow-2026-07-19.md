# GATE-4 Disposition — `chore/lean-execution-workflow` → REJECTED

**Date:** 2026-07-19
**Gate:** GATE 4 (salvage finding disposition) + GATE 3 (branch status designation)
**Disposition:** **REJECTED** (archive-tagged + abandoned)
**Context:** surfaced during the task-lifecycle governance campaign (PR #953, branch `docs/task-lifecycle-resume-rule`)

> This is the committed, PII-free record of the disposition. The operational
> copy lives in the local-only `.claude/memory/PROJECT_STATE.md` DECISIONS
> section (gitignored since #901 by design). This file exists so the decision
> is auditable in version control without exposing that file's contents.

---

## Subject

The unmerged branch **`chore/lean-execution-workflow`** (commit `44813371`,
"docs(workflow): add lean execution control surface + protocol (docs-only)",
dated 2026-06-14; present on both `origin` and local) introduces a **competing
governance surface**:

- `docs/EXECUTION_PROTOCOL.md` — a "7 lean rules" execution protocol that
  overlaps the canonical **`.claude/TASK_EXECUTION_PROTOCOL.md`** (the
  single-task lifecycle authority, extended by PR #953 with the
  `DISCOVERY → PLANNING → IMPLEMENTING → VALIDATING → READY_FOR_PR →
  UNDER_REVIEW → COMPLETE` lifecycle states plus the suspended
  `EXECUTION_BLOCKED` state and its Resume Rule).
- a repo-root **`PROJECT_STATE.md`** "Execution Control Surface" that overlaps
  the canonical **`.claude/memory/PROJECT_STATE.md`** (owned by
  `flow-context-keeper` per CLAUDE.md RULES 1/3/6).

The branch itself records an "Open disagreement: dual PROJECT_STATE files."

## Decision

**REJECTED.** Per the Engineering Constitution principle *"one authority per
concept,"* a second execution-protocol authority and a second PROJECT_STATE
authority must not land alongside the canonical ones.

## Reasoning (why REJECTED, not SCHEDULED or ISSUE)

1. **Not superseded-by-content by PR #953.** The branch defines *none* of the
   canonical lifecycle states or the Resume Rule, so it is a parallel,
   conflicting design — not an earlier draft of the same work that #953
   completes.
2. **No unique reconcile payload.** Its 7 rules map 1:1 onto existing
   CLAUDE.md GATES 1–6 and Lessons A / I / M — the branch's own "Relationship
   to CLAUDE.md gates" section states this. There is nothing to fold into the
   canonical protocol that is not already present or better expressed. A
   SCHEDULED reconcile would have an empty payload.
3. **Stale, obsolete state surface.** Its root `PROJECT_STATE.md` captures
   ~5-week-old operational state (a superseded production SHA, a blocked
   campaign gated on a 2026-06-20 checkpoint, and a since-resolved PR). Merging
   it would regress live execution state.
4. **Authority conflict is structural, not cosmetic.** Two execution-protocol
   surfaces and two PROJECT_STATE surfaces cannot coexist under the
   one-authority rule; keeping the branch alive perpetuates the conflict it
   itself flagged.

## Actions taken

- **GATE 3 — archive tag:** `archive/chore--lean-execution-workflow-2026-07-19`
  created, pointing at `44813371` (verified equal to the branch tip). Created
  **local-only** (no push) per the public-repo PII/tag-push discipline. Branch
  status designated **ARCHIVED**: merges nothing; may be deleted after the
  retention period. History is preserved by the tag.
- **GATE 4 — record:** disposition written to the local-only
  `.claude/memory/PROJECT_STATE.md` DECISIONS section, and mirrored here for
  version-control auditability.

## Follow-up (non-blocking)

The branch's `.github/pull_request_template.md` (a PR-closure contract) is the
one artifact that does **not** conflict with an existing authority — the repo
currently has no PR template. If a PR-closure template is wanted, it is a
**separate, independently-scoped docs task**, authored fresh against the
canonical authorities (`.claude/TASK_EXECUTION_PROTOCOL.md`, CLAUDE.md
GATES 1–6, Business Feature Completeness Standard) — **not** a resurrection of
the rejected branch's content. Tracked as a follow-up chip.

The original artifact can be read for reference (read-only) via:

```bash
git show archive/chore--lean-execution-workflow-2026-07-19:.github/pull_request_template.md
```
