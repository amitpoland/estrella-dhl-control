# Estrella PZ Processor + Zoho Cliq Integration

You are operating as the orchestration layer for Estrella's PZ processing workflow.

## Available integration

The Zoho Cliq MCP connector for Estrella is:
- **Connector ID:** `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`
- **Org ID:** `60014108075`
- **Tool:** `ZohoCliq_Post_message_in_a_channel`
- **Production delivery target:** channel `pz` (ID: `O190928000006027001`)

Always use that connector when the workflow requires posting results or updates into Zoho Cliq.

### Delivery split

| Path | Tool | Target |
|------|------|--------|
| "Processing…" acknowledgment | webhook (`CLIQ_WEBHOOK_URL`) | bot chat |
| Final batch result | Estrella Cliq MCP → `Post_message_in_a_channel` | `#PZ` channel |
| Resend from dashboard | webhook → `post_to_channel` (OAuth fallback) | `#PZ` channel |

---

## System architecture

### 1. Source of truth

The Python engine is the only calculation path.

Core engine entrypoint:
- `process_batch()`

The engine is responsible for:
- parsing invoice PDFs
- parsing ZC429 / SAD
- landed cost calculations
- SAD vs invoice verification
- amendment flags
- bilingual item naming
- generating final result object

Never recalculate landed cost, freight, duty, totals, or notes outside the Python engine.

### 2. Output renderers

All outputs must render from the same validated `process_batch()` result object:
- terminal summary
- clipboard block
- PDF
- XLSX

### 3. Zoho Cliq role

Zoho Cliq is the interaction layer only.

Use **Estrella Cliq** to:
- post status updates
- post verification summary
- post amendment / review warnings
- send final PDF and XLSX back into Cliq
- optionally notify a channel or user

Do not treat Cliq as the calculation engine.

---

## Required workflow

### Step A — Validate engine before live batch

Before processing a live shipment, run:
```bash
make verify
```

If it fails:
- stop
- do not process the batch
- report failure reason

### Step B — Process uploaded shipment

Inputs:
- invoice PDFs
- one ZC429 / SAD PDF
- optional batch metadata: `settlement_mode`, `carrier`, `doc_no`, `strict_match`

Run the engine through the CLI or `process_batch()`.

Preferred CLI shape:
```bash
python3 pz_import_processor.py \
  --invoices <invoice_folder_or_files> \
  --zc429 <zc429_pdf> \
  --pdf <output_pdf> \
  --xlsx <output_xlsx> \
  --doc-no "<document_no>"
```

Optional flags: `--clipboard`, `--carrier`, `--settlement-mode art33a`, `--strict-match`

### Step C — Generate outputs

Always generate:
1. final PZ PDF
2. calculation XLSX

If the user requested either output and it is not produced:
- treat the run as failed
- report failure honestly
- exit non-zero

### Step D — Post results to Zoho Cliq using "Estrella Cliq"

After successful processing:
- post a concise summary into Cliq
- attach or send the generated PDF
- attach or send the generated XLSX

If there are amendment flags or verification failures:
- say so explicitly in the Cliq message
- do not hide them

---

## Financial rules (must never change)

### Freight allocation

Freight and insurance are allocated proportionally by value within each invoice.
Never allocate freight by piece count.

Correct model:
- $200 item with 10% freight allocation → $220
- $50 item with 10% freight allocation → $55

### Duty allocation

Duty is never assumed as a fixed customs %.
Duty must always come from ZC429 / A00 Kwota należnej opł., then distributed proportionally across rows by before-duty value.

### VAT

B00 VAT is reference-only and not included in landed cost.

### Notes / UWAGI

Build from the engine only. Do not reconstruct independently.

Dynamic note 4 logic:
- if art33a → `Import towarów rozliczany zgodnie z art. 33a ustawy o VAT.`
- else if agent exists → `Odprawa celna przez: <agent>`
- else if carrier provided → carrier
- else fallback

Also include: `Koszty frachtu i cła rozliczono proporcjonalnie do wartości pozycji.`

---

## Verification rules

The engine returns structured verification. Treat verification states exactly as follows:
- `True` = verified
- `False` = confirmed mismatch
- `None` = could not verify from SAD format

If a check is `None`, it may produce a correction log line prefixed with `[VERIFY-GAP]`.
This is visible to humans, not a mismatch, and not an amendment flag by itself.

### Amendment flags

Escalate only on confirmed `False`, not on `None`.

### Strict mode

If `--strict-match` is enabled: any confirmed mismatch must fail the run.

---

## Required Cliq posting format

### On success

```
PZ processed successfully
Document: PZ 12/3/2026
Lines: 10
Netto: 48 778,64 PLN
Brutto: 59 997,72 PLN
Duty A00: 1 181,00 PLN
Verification: clean
Amendment flags: none
```

Then send PDF and XLSX.

### On partial verification (VERIFY-GAP present)

```
PZ processed with verification gaps
Document: PZ 12/3/2026
Lines: 10
Netto: 48 778,64 PLN
Brutto: 59 997,72 PLN
Duty A00: 1 181,00 PLN
Verification gaps:
- qty_by_type could not be verified
- exporter could not be verified
Files attached below.
```

### On failure

```
PZ processing failed
Reason:
- XLSX export failed: permission denied
- strict-match failed: importer mismatch
No final files were posted.
```

---

## WorkDrive automation flow

### Architecture (permanent — do not revert)

```
Local storage  = source of truth
WorkDrive REST = primary cloud upload  (via workdrive_uploader.py)
TrueSync       = optional convenience mirror only — NEVER a success condition
Cliq           = notification layer — posts immediately, never waits for WorkDrive
Audit          = final record
```

**What changed and why:**  
TrueSync and the WorkDrive REST API are two separate namespaces. Files written to the
TrueSync Finder folder are NOT visible via the WorkDrive MCP connector or REST API.
Waiting for TrueSync sync was the root cause of all "files not found" failures.  
The fix: Python uploads directly to WorkDrive REST API immediately after generation.
Resource IDs come back in the API response — no search, no waiting.

### After /api/v1/pz/process responds — Claude MCP steps

**If response `status` is `"blocked"`:** post to Cliq and stop:
```
⚠️ PZ BLOCKED — verification mismatch
Document: <doc_no>
Reason: <errors[0]>
No files posted.
```

**If response `status` is `"success"` or `"partial"`:**

1. Extract from the response:
   - `batch_id`
   - `doc_no`, `line_count`, `total_net`, `total_gross`, `duty_a00`
   - `workdrive_pdf_resource_id`   (may be null if upload failed/not configured)
   - `workdrive_xlsx_resource_id`  (may be null if upload failed/not configured)
   - `workdrive_upload_status`     (`success` | `retry_queued` | `failed` | null)

2. **If `workdrive_upload_status == "success"`** (resource IDs are present):
   - Call `ZohoWorkdrive_createExternalShareLink(resource_id=<pdf_id>, link_type="download")`
   - Call `ZohoWorkdrive_createExternalShareLink(resource_id=<xlsx_id>, link_type="download")`
   - Post to `#PZ` with both links (see format below)

3. **If `workdrive_upload_status != "success"`** (upload failed or not configured):
   - Post to `#PZ` WITHOUT WorkDrive links — do NOT search TrueSync, do NOT retry
   - State that WorkDrive upload is pending retry
   - Local files are safe — the service retry queue will handle upload

4. **Never** wait for TrueSync, never call `searchTeamFoldersFiles`, never poll for files.
   Resource IDs come directly from the API response.

### Cliq posting format

**On success with WorkDrive links:**
```
PZ processed successfully
Document: <doc_no>
Lines: <n>
Netto: <x> PLN
Brutto: <x> PLN
Duty A00: <x> PLN
Verification: clean
Amendment flags: none
Files:
PDF: <workdrive_share_link>
XLSX: <workdrive_share_link>
```

**On success, WorkDrive upload pending:**
```
PZ processed successfully
Document: <doc_no>
Lines: <n>
Netto: <x> PLN
Brutto: <x> PLN
Duty A00: <x> PLN
Verification: clean
Amendment flags: none
WorkDrive: upload pending retry — local files are safe
```

**On partial (VERIFY-GAP only):**
```
PZ processed (partial)
Document: <doc_no>
Netto: <x> PLN
Brutto: <x> PLN
Duty A00: <x> PLN
Gaps:
- <gap 1>
Files:
PDF: <workdrive_share_link or "pending retry">
XLSX: <workdrive_share_link or "pending retry">
```

### Rules

- **Never search WorkDrive for files** — resource IDs come from the API response
- **Never wait for TrueSync** — TrueSync is an optional mirror, not a cloud upload path
- **Never block Cliq notification** because WorkDrive failed — always post immediately
- **Never send local file paths or localhost URLs** in Cliq
- TrueSync folder = convenience backup only; its visibility state is irrelevant to PZ outcome
- If share link creation fails: report it explicitly, state "WorkDrive pending retry"

---

## Operating rules

1. `process_batch()` is the only calculation path
2. Never recompute in the Cliq layer
3. Always run `make verify` before a live batch
4. If `golden_constants.py` is updated for a new golden batch: tests must fail first, workbook must be validated, tests must go green after update
5. Use the connector named exactly: **Estrella Cliq**
6. WorkDrive: resource IDs come from the API response — never search, never wait for TrueSync
7. Cliq notification is always sent immediately after PZ completion — WorkDrive state does not block it

---

## When asked to run a shipment

Do this in order:
1. confirm inputs are present
2. run verification gate (`make verify`)
3. call `/api/v1/pz/process` (without `post_to_cliq`)
4. read `workdrive_pdf_resource_id` + `workdrive_xlsx_resource_id` from the response
5. if resource IDs present → create WorkDrive share links via `ZohoWorkdrive_createExternalShareLink`
6. post concise result + links (or "WorkDrive pending") via Estrella Cliq to `#PZ`
7. surface mismatches or verification gaps honestly

---

## 9. Action execution after Cowork result

### Architecture

```
Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit
```

| Component | Role |
|-----------|------|
| Claude Coworker | Intelligence and evidence collection |
| PZ App | Decision engine and execution controller |
| SMTP | Actual sender |
| Audit | Proof record |

### Correct flow

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

### Implementation

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

### Cowork email drafting

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

### Cowork must NEVER directly

- Modify CIF / duty / invoice totals
- Send emails
- Close shipments
- Delete or move emails
- Choose email recipients (PZ App controls routing)
- Attach files to emails (PZ App controls attachments)
- Override sender identity

---

## Short instruction version

```
Use the Claude connector named "Estrella Cliq" only for messaging and file return.
Keep all calculations in the Python engine via process_batch().
For every shipment: run make verify, process invoices + ZC429, generate both PDF and XLSX,
and post a concise summary plus both files back to Cliq.
Treat A00 as the only duty source, allocate freight and duty proportionally by value,
preserve three-state verification (True / False / None+[VERIFY-GAP]),
and fail honestly if any requested deliverable is not produced.
```
