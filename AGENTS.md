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

**Architecture:** Python service processes and generates files → TrueSync auto-uploads to WorkDrive → Codex MCP finds files + creates share links → posts to Cliq.

Python never calls WorkDrive API. Codex MCP handles all WorkDrive and Cliq steps.

### TrueSync folder structure (required)

Files must land in a batch-scoped folder so search never returns the wrong file:

```
Zoho WorkDrive TrueSync/PZ/2026/BATCH_<batch_id>/
    PZ_<doc>.pdf
    PZ_<doc>_calc.xlsx
```

The service writes files here automatically when `WORKDRIVE_SYNC_ROOT` is set in `.env`.

### After /api/v1/pz/process responds — Codex MCP steps

**If response `status` is `"blocked"`:** do not proceed to WorkDrive. Post to Cliq only:
```
⚠️ PZ BLOCKED — verification mismatch
Document: <doc_no>
Reason: <errors[0]>
No files posted.
```

**If response `status` is `"success"` or `"partial"`:**

1. Extract: `batch_id`, `files.pdf_url` basename (PDF filename), `files.xlsx_url` basename (XLSX filename)
2. Wait 3 seconds for TrueSync
3. Resolve the batch folder (search once):
   ```
   searchTeamFoldersFiles(search_text="BATCH_<batch_id>")
   → capture batch_folder_id
   ```
4. For each file (PDF, then XLSX) — retry up to 5 attempts:
   ```
   attempt 1..5:
       searchTeamFoldersFiles(search_text=<exact filename>)
       for each result:
           if item.name == filename AND item.parent_id == batch_folder_id → FOUND
       if FOUND → break
       else:
           log: [RETRY] <filename> attempt <n> → MISS
           wait 2 seconds
   if not FOUND after 5 attempts:
       log: [RETRY] <filename> attempt 5 → SYNC FAILED
       STOP — post failure alert to Cliq, do not send broken links
   ```
5. For each found file:
   ```
   createExternalShareLink(resource_id=<resource_id>, link_type="download")
   ```
6. Post to Cliq via **Estrella Cliq**:

   On success:
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

   On partial (VERIFY-GAP only):
   ```
   PZ processed (partial)
   Document: <doc_no>
   Netto: <x> PLN
   Brutto: <x> PLN
   Duty A00: <x> PLN
   Gaps:
   - <gap 1>
   Files:
   PDF: <workdrive_share_link>
   XLSX: <workdrive_share_link>
   ```

### Retry log (persist to audit)

Maintain a list during the MCP phase:
```
retry_log = []
retry_log.append({"file": filename, "attempt": n, "status": "found" | "miss" | "sync_failed"})
```

After both files are resolved (or failed), append `retry_log` to `audit.json`:
```
read audit.json → parse → add "workdrive_retries": retry_log → write back
```

This makes WorkDrive sync failures reconstructible after the fact.

### Rules

- Never search globally — always match exact filename AND `parent_id == batch_folder_id`
- Log every retry: `[RETRY] <filename> attempt <n> → FOUND/MISS/SYNC FAILED` (and persist)
- Always retry before failing — TrueSync lag is normal
- Never send local file paths or localhost URLs in the Cliq message
- If share link creation fails: report it explicitly, do not send a broken link

---

## Operating rules

1. `process_batch()` is the only calculation path
2. Never recompute in the Cliq layer
3. Always run `make verify` before a live batch
4. If `golden_constants.py` is updated for a new golden batch: tests must fail first, workbook must be validated, tests must go green after update
5. Use the connector named exactly: **Estrella Cliq**
6. WorkDrive: always use batch-scoped folders and retry-based detection — never search globally

---

## When asked to run a shipment

Do this in order:
1. confirm inputs are present
2. run verification gate (`make verify`)
3. call `/api/v1/pz/process` (without `post_to_cliq`)
4. wait for TrueSync → retry search → create WorkDrive share links
5. post concise result + WorkDrive links via Estrella Cliq
6. surface mismatches or verification gaps honestly

---

## Short instruction version

```
Use the Codex connector named "Estrella Cliq" only for messaging and file return.
Keep all calculations in the Python engine via process_batch().
For every shipment: run make verify, process invoices + ZC429, generate both PDF and XLSX,
and post a concise summary plus both files back to Cliq.
Treat A00 as the only duty source, allocate freight and duty proportionally by value,
preserve three-state verification (True / False / None+[VERIFY-GAP]),
and fail honestly if any requested deliverable is not produced.
```
