---
name: cowork-integration
description: >
  Cowork intelligence integration spec for the PZ App. Covers the
  Cowork→PZ→SMTP→Audit pipeline architecture, cowork_result_processor.py
  flow, cowork_action_runner.py execution contract, email drafting types
  and validation rules, and the hard list of actions Cowork must NEVER
  take. Invoke when building or reviewing any Cowork result handler,
  action runner, or email drafting flow.
triggers:
  - "cowork result"
  - "cowork_result_processor"
  - "cowork_action_runner"
  - "process_cowork_result"
  - "run_post_result"
  - "cowork email draft"
  - "cowork integration"
---

# Action Execution After Cowork Result

## Architecture

```
Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit
```

| Component | Role |
|-----------|------|
| Claude Coworker | Intelligence and evidence collection |
| PZ App | Decision engine and execution controller |
| SMTP | Actual sender |
| Audit | Proof record |

## Correct flow

```
Scheduler runs every 10 minutes
→ PZ App creates Cowork task
→ Cowork reads Zoho and maps emails/documents
→ Cowork posts structured result to PZ App
→ PZ App validates result
→ PZ App decides next action
→ PZ App sends via SMTP
→ PZ App logs audit/timeline
```

Coworker should NOT directly send emails. It returns exact structured data only.

## Implementation

**`service/app/services/cowork_result_processor.py`**

Function: `process_cowork_result(task_id, result, batch_id)`

Flow:
1. Load related shipment audit
2. Validate result:
   - AWB match
   - Invoice overlap
   - DHL ticket match if present
   - Attachment classification confidence
   - Reject any financial field mutation
3. Write safe evidence to audit
4. Decide next action from existing state machine:
   - DHL email found → build/send DHL reply via SMTP
   - DHL document set found → validate/store/forward to agency via SMTP
   - Agency SAD/PZC found → import customs docs and trigger PZ
   - Agency invoice found → store as service invoice
   - DHL invoice found → store as service invoice
   - Missing response → schedule follow-up SLA

**`service/app/services/cowork_action_runner.py`**

Function: `run_post_result(task_id, result, batch_id)`

Executes only through existing PZ App services:
- `email_service.py` (SMTP queue)
- `dhl_reply_builder.py`
- `agency_forward_after_dhl_builder.py`
- `sad_importer.py`
- `service_invoice_monitor.py`
- `shipment_closure.py`

Logs every action:
- `cowork_action_executed`
- `cowork_action_failed`
- `cowork_result_processed`
- `cowork_result_rejected`

## Cowork email drafting

Cowork may generate professional email body text for:
- DHL DSK request (`dhl_dsk_request`)
- DHL follow-up (`dhl_followup`)
- Agency document forward (`agency_document_forward`)
- Agency follow-up (`agency_followup`)
- Missing document request (`missing_document_request`)
- Service invoice follow-up (`service_invoice_followup`)

Cowork returns drafts as structured JSON field alongside evidence:
```json
{
  "recommended_action": "send_email",
  "email_draft": {
    "type": "dhl_followup",
    "subject": "Follow-up: AWB 1012178215",
    "body": "Dear DHL Customs Team, ...",
    "language": "en",
    "tone": "professional",
    "reason": "No DHL document response after initial reply"
  },
  "evidence": { ... },
  "risk_flags": []
}
```

**Draft validation (cowork_result_processor.py):**
- Type must be in `ALLOWED_DRAFT_TYPES`
- Must NOT contain forbidden fields: `to`, `cc`, `bcc`, `from`, `attachments`, `files`
- AWB in draft must match audit AWB
- Must have `subject` and `body`
- Invalid drafts are dropped (not blocking — evidence still written)

**Draft execution (cowork_action_runner.py):**
- PZ App injects correct recipients from `email_routing.py` based on draft type
- PZ App appends standard Estrella Jewels signature
- PZ App decides attachments from audit state (never from Cowork)
- PZ App sends via `email_service.queue_email` only
- Sender always `import@estrellajewels.eu`
- Draft record stored in `audit.cowork_email_drafts[]`

## Cowork must NEVER directly

- Modify CIF / duty / invoice totals
- Send emails
- Close shipments
- Delete or move emails
- Choose email recipients (PZ App controls routing)
- Attach files to emails (PZ App controls attachments)
- Override sender identity
