---
name: audit-trace-reporter
description: Read-only inspection of timeline events and audit file state for a specific batch. Checks for missing events, out-of-order timestamps, orphaned lock files, and reports a structured trace.
triggers:
  - trace batch timeline
  - inspect audit trail
  - check timeline events
  - debug batch state
  - audit file report
tools:
  - Read
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(ls:*)
  - Bash(jq:*)
concurrency_safe: true
---

# Audit Trace Reporter

Read-only inspection skill that examines the timeline and audit state for a specific shipment batch.

## Purpose

Answer the question: "What happened to batch X?" by reading the audit JSON and timeline events, checking for integrity issues, and producing a structured trace report.

## When to Use

- A shipment is stuck and you need to understand the sequence of events.
- Verifying timeline integrity after a code change.
- Checking whether a specific event (e.g., `ai_bridge_task_created`, `dhl_customs_email_received`) was logged for a batch.
- Debugging missing, duplicate, or out-of-order timeline entries.
- Checking for orphaned `.lock_*` files in `ai_bridge/`.

## When NOT to Use

- Creating AI Bridge tasks or importing results — use the AI Bridge skills.
- Modifying audit files or timeline code — this skill is read-only.
- Running tests — use `regression-test-guard`.
- Inspecting project structure — use `system-controller`.
- Reviewing customs/PZ guard coverage — use `customs-pz-safety-checker`.

## Workflow

1. **Locate batch** — find the audit file for the requested batch_id in `app/storage/outputs/`. If not found, report "Batch not found" and stop.
2. **Read audit** — load the audit JSON and extract key state fields: `status`, `clearance_status`, `tracking`, `dhl_email`, `inputs`, `ai_bridge_tasks`.
3. **Read timeline** — extract the `timeline` array from the audit file. List all events with timestamps.
4. **Check ordering** — verify timestamps are monotonically increasing. Flag any out-of-order entries.
5. **Check completeness** — for each AI Bridge task referenced in the audit, verify that both `ai_bridge_task_created` and `ai_bridge_result_received` events exist (or that the task is still pending).
6. **Check lock files** — look for orphaned `.lock_*` files in `ai_bridge/` that match this batch's task IDs.
7. **Check processed/errors** — verify that completed tasks appear in `ai_bridge/processed/` and rejected tasks appear in `ai_bridge/errors/`.
8. **Report** — return a structured trace report.

## Safety Rules

- This skill is strictly read-only. It never creates, edits, or deletes any file.
- It never modifies audit files, timeline entries, or lock files.
- It never writes to `storage/`, `ai_bridge/`, or any application directory.
- It does not read or log credentials, tokens, or secrets.
- If it finds orphaned lock files, it reports them — it does not delete them.

## Output Format

```
## Audit Trace Report — {batch_id}
- **Batch status:** (current status)
- **Clearance status:** (current clearance_status)
- **Timeline events:** (count, with chronological list)
- **Ordering issues:** (details, or "None — chronological")
- **Missing events:** (list, or "None")
- **Orphaned lock files:** (list, or "None")
- **AI Bridge tasks:** (count pending / processed / errored)
- **Verdict:** CLEAN / ISSUES FOUND
```
