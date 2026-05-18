---
name: pz-shipment
description: >
  Full PZ shipment processing protocol for Estrella Jewels. Covers the required
  4-step workflow (validate → process → generate → post), financial calculation
  rules (freight/duty allocation), three-state verification semantics, all Cliq
  posting formats, and WorkDrive automation flow. Invoke whenever processing a
  live shipment, generating a PZ batch, or posting results to #PZ.
triggers:
  - "run a shipment"
  - "process invoices"
  - "process batch"
  - "generate PZ"
  - "post to PZ"
  - "make verify"
  - "WorkDrive upload"
  - "Cliq posting format"
---

# PZ Shipment Processing Protocol

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
