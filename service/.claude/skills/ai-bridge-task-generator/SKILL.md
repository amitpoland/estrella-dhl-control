---
name: ai-bridge-task-generator
description: Generate safe AI Bridge task files, task templates, and external AI task instructions. Use when creating task payloads for external AI tools, drafting new task type templates, or preparing task instructions that comply with forbidden-field and allowed-writes rules.
triggers:
  - create AI bridge task
  - generate task template
  - draft task instructions
  - new task type for AI bridge
  - prepare task payload
tools:
  - Read
  - Bash(find:*)
  - Bash(ls:*)
  - Bash(grep:*)
  - Bash(jq:*)
---

# AI Bridge Task Generator

Generate safe, validated task files and templates for the AI Bridge system. Tasks are consumed by external AI tools (Claude Cowork, ChatGPT, etc.) that assist with shipment processing without direct access to financial data or production systems.

## Purpose

Create task definitions that external AI tools can read from `ai_bridge/tasks/` and act on. Every generated task must comply with the forbidden-field and allowed-writes constraints enforced by `ai_bridge.py`.

## When to Use

- Creating a new task file for an existing task type (tracking_lookup, document_summary, risk_assessment, supplier_research, email_draft, general_research, email_scan).
- Drafting a new task type template with instructions, result schema, and allowed write keys.
- Reviewing whether a proposed task payload is safe before submission.
- Generating task instructions that an external AI tool will follow.

## When NOT to Use

- Importing or applying results from external AI tools (use `ai-bridge-result-validator`).
- Modifying customs, financial, or accounting data directly.
- Sending emails, triggering external workflows, or executing actions.
- Editing existing application code or API routes.
- Any task that requires Write or Edit tools against `app/` or `tests/`.

## Inputs

- **task_type** (required): one of the registered types in `TASK_TEMPLATES`.
- **batch_id** (required): the shipment batch this task relates to.
- **payload** (optional): context fields for the external AI (AWB, tracking URL, research question, etc.).
- **note** (optional): human-readable note for the operator.

## Outputs

- A JSON task file matching the schema in `ai_bridge.py:create_task()`.
- Or a task type template definition with `description`, `instructions`, `result_schema`, and `allowed_writes`.

## Workflow

1. **Read current templates** — inspect `TASK_TEMPLATES` and `_ALLOWED_WRITES` in `app/services/ai_bridge.py` to understand existing task types and constraints.
2. **Validate task type** — confirm the requested type exists. If proposing a new type, draft the template.
3. **Locate batch** — look up the requested `batch_id` in `app/storage/outputs/`. If the batch audit file does not exist, **stop immediately** and return: `"Batch not found. Task not generated."` Do not proceed to step 4.
4. **Extract payload from matched batch only** — read AWB, carrier, tracking_url, and other context fields from the audit file that matches the requested `batch_id`. Never use data from a different batch.
5. **Check payload safety** — verify the payload contains no forbidden fields and no credentials, tokens, or secrets.
6. **Generate task JSON** — produce the task file content with all required fields: `task_id`, `task_type`, `batch_id`, `status`, `created_at`, `description`, `instructions`, `result_schema`, `payload`, `note`, `result_file`.
7. **Validate result schema** — if defining a new task type, verify the `result_schema` does not request forbidden fields and the `allowed_writes` list does not overlap with `FORBIDDEN_FIELDS`.
8. **Present for review** — show the generated task to the user before any file is written.

## Source-of-Truth Rule

- Every field in the task payload (batch_id, AWB, carrier, tracking_url, status) must come from the audit file of the **requested batch_id** and no other source.
- Never substitute, infer, or borrow data from a different batch, shipment, or audit file.
- If the requested batch_id does not exist on disk, stop and return: **"Batch not found. Task not generated."**
- Do not generate a task with placeholder or fallback values from unrelated batches.
- Always state explicitly whether the payload data came from the requested batch's audit file.

## Protected Fields

The following fields must NEVER appear in any task payload, result schema, or allowed-writes list:

- `pz_totals`
- `cif`
- `customs_values`
- `customs_declaration`
- `duty`
- `vat`
- `invoice_totals`
- `clearance_decision`
- `sad_data`
- `sad_items`
- `sad_verification`
- `invoice_lines`
- `landed_cost`

## Safety Rules

- This skill is read-only for inspection. It generates task content for user review but does not write files without explicit user confirmation.
- Never include credentials, API keys, tokens, or secrets in task payloads or instructions.
- Never generate instructions that tell the external AI to modify financial fields, customs values, duty, VAT, or any protected field.
- Never generate instructions that tell the external AI to send emails, trigger webhooks, or execute external workflows.
- Never generate instructions that bypass the forbidden-field or allowed-writes validation in `ai_bridge.py`.
- If proposing a new task type, its `allowed_writes` must not overlap with `FORBIDDEN_FIELDS`.
- Task instructions must always direct the external AI to write results to `ai_bridge/results/<task_id>.json` — never directly to audit files.

## Output Format

```json
{
  "task_id":       "<uuid>",
  "task_type":     "<type>",
  "batch_id":      "<batch>",
  "status":        "pending",
  "created_at":    "<ISO8601>",
  "description":   "<what the external AI should do>",
  "instructions":  "<step-by-step instructions>",
  "result_schema": { "<key>": "<type and description>" },
  "payload":       { "<context fields>" },
  "note":          "<optional operator note>",
  "result_file":   "ai_bridge/results/<task_id>.json"
}
```
