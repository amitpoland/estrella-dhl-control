# AWB 9198333502 — Proforma Draft Repair Runbook

**Batch:** `SHIPMENT_9198333502_2026-05_87257361`  
**Status:** BLOCKED — do not execute until deploy sequence is complete  
**Created:** 2026-05-26  
**Last reviewed:** 2026-05-26

---

## ⛔ EXECUTION GATE

**Do not run any repair step until ALL of the following are complete:**

1. Technical lead signs Section 1 below
2. Code commit (intake-contract fix) is on `main`
3. 7-agent deploy gate passes (no exceptions per CLAUDE.md)
4. Production deploy is confirmed on `https://pz.estrellajewels.eu`
5. Only then: run Steps I–V in order
6. QA verifies V1–V5 closure conditions

---

## Section 1 — Technical Lead Sign-off

> *Technical lead must sign here before execution is permitted.*

**Signed by:** _________________________  
**Date:** _________________________  
**Commit SHA deployed:** _________________________

---

## Section 1.1 — Root Cause (precise)

**Two-failure statement:**

> empty `client_name` was the **immediate draft-generation failure**.  
> missing `client_contractor_id` was the **authority failure**.  
> Both came from the same intake-contract gap.

**Full root cause:**

The upload sent/handled contractor identity and display identity inconsistently.
The frontend supplied `contractor_id` but sent a blank `client_name`.
The backend relied on `client_name` for draft generation and did not reliably
persist `contractor_id` as upload authority.

Result: no `proforma_draft` rows, no upload-selected contractor authority.

**What this is NOT:**

- Not a missing upload (files were uploaded correctly)
- Not a parser failure (sales lines were created)
- Not a wFirma write failure (no wFirma call was attempted)
- Not an export gate issue (export was correctly blocked — no SAD yet)

---

## Section 2 — Authority Verification (run before any repair)

### Authority hierarchy for this workflow

| Field | Role | Authoritative? |
|-------|------|---------------|
| `sales_packing_lines` columns | Product, quantity, price, design | Not customer authority |
| `sales_documents.client_name` | Display / reference value — can be wrong, stale, or derived | **Not** customer authority |
| `shipment_documents.client_contractor_id` | Operator-selected customer, validated against `customer_master` | **Yes — this is the authority field** |

**Do not use `sales_documents.client_name`, packing-list customer text, or XLSX naming
conventions to determine customer assignment. Only `shipment_documents.client_contractor_id`
→ `customer_master.bill_to_contractor_id` → `customer_master.bill_to_name` is authoritative.**

Only if `client_contractor_id` is empty should a repair plan be generated.

---

### Check 1 — Read contractor authority from shipment_documents

```powershell
$db = "C:\PZ\storage\documents.db"
$B  = "SHIPMENT_9198333502_2026-05_87257361"

$sql1 = @"
SELECT
    id,
    file_name,
    client_contractor_id
FROM shipment_documents
WHERE batch_id = '$B'
  AND document_type = 'sales_packing_list';
"@

& "C:\PZ\service\python.exe" -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
for row in conn.execute(sys.argv[2]):
    print(dict(row))
" $db $sql1
```

**Decision:**
- Both rows have `client_contractor_id` filled → proceed; use those IDs in Check 2.
- Either row has `client_contractor_id` empty → V1 repair is required (see Emergency Backfill).

---

### Check 2 — Resolve contractor names from customer_master

Using the `client_contractor_id` values returned in Check 1:

```powershell
$cm = "C:\PZ\storage\customer_master.sqlite"

$sql2 = @"
SELECT
    bill_to_contractor_id,
    bill_to_name
FROM customer_master
WHERE bill_to_contractor_id IN (
    <contractor_ids_from_check_1>
);
"@

& "C:\PZ\service\python.exe" -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
for row in conn.execute(sys.argv[2]):
    print(dict(row))
" $cm $sql2
```

This establishes the **authoritative name** for each document. If `bill_to_name` does not
match what operator expects, that is a `customer_master` discrepancy — not a `sales_documents`
repair problem.

---

### Check 3 — Confirm sales_documents exist (draft generation pre-condition)

```powershell
$sql3 = @"
SELECT
    id,
    document_id,
    client_name
FROM sales_documents
WHERE batch_id = '$B';
"@

& "C:\PZ\service\python.exe" -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
for row in conn.execute(sys.argv[2]):
    print(dict(row))
" $db $sql3
```

Compare Check 3 `client_name` against Check 2 authority names.

**Implementation note:** `sales_documents.client_name` serves a dual role in the
`derive_customer_authority_for_draft` function (`customer_resolution_authority.py`):
- It is a **routing key** — the function uses it in a SQL `WHERE client_name = ?` join
  to locate the correct `sales_documents` row before reading
  `shipment_documents.client_contractor_id`.
- It is **not** the contractor authority — the authority is `client_contractor_id`.

This produces two distinct failure modes, both of which must be understood:

| Check 3 result | Failure mode | Blocks authority path? | Action |
|---|---|---|---|
| `client_name` is non-empty and matches `customer_master` name | Clean | No | Proceed |
| `client_name` is non-empty but differs from `customer_master` name | Display-layer mismatch (advisory only) | **No** — routing still works because the value is non-empty; contractor_id is the authority | Note discrepancy; do not block |
| `client_name` is empty | Routing failure | **Yes** — function cannot find the `sales_documents` row | Repair client_name first (same intake-contract gap as missing contractor_id — see Section 1.1) |

---

**Decision gate:**
- Check 1 IDs filled + Check 2 names resolve + Check 3 client_name non-empty → proceed to Section 3.
- Check 1 IDs empty → run Emergency Backfill (Section 4) first, then re-run Checks 1–3.
- Check 3 client_name empty → routing failure; restore client_name before generating drafts.
- Check 2 names unexpected (non-empty mismatch) → note discrepancy; do not block; investigate `customer_master` separately.

---

## Section 3 — Repair Steps

### Pre-Step I — Safety Check: Verify No Existing Drafts

Before generating new drafts, confirm no drafts already exist for this batch.
Drafts with wrong client names must be identified and cancelled before generating new ones.

```powershell
$BASE = "https://pz.estrellajewels.eu"
$B    = "SHIPMENT_9198333502_2026-05_87257361"
$TOKEN = "<paste operator token here>"
$h = @{ "Authorization" = "Bearer $TOKEN"; "Content-Type" = "application/json" }

$draftsJson = Invoke-WebRequest -UseBasicParsing -Headers $h `
  "$BASE/api/v1/proforma/drafts/$([uri]::EscapeDataString($B))" `
  | Select-Object -ExpandProperty Content

Write-Host $draftsJson
```

**Decision rule:**

| Result | Action |
|--------|--------|
| `"count": 0` | Proceed to Step I |
| `"count": N` and Section 2 Check 1 confirms `client_contractor_id` filled on both rows | Proceed directly to V1–V5 verification — drafts already present |
| `"count": N` but Section 2 Check 1 shows `client_contractor_id` empty on any row | **CANCEL. Do not proceed.** Run Emergency Backfill (Section 4) first, then restart runbook. |

---

### Step I — Trigger Proforma Draft Generation

Call the proforma pipeline endpoint to generate drafts for both clients:

```powershell
$pipelineResponse = Invoke-WebRequest -UseBasicParsing -Method POST -Headers $h `
  "$BASE/api/v1/proforma/pipeline/$([uri]::EscapeDataString($B))" `
  -Body '{"dry_run": false}' `
  | Select-Object -ExpandProperty Content

Write-Host $pipelineResponse
```

**Expected response (after deploy with intake-contract fix):**
```json
{
  "status": "ok",
  "client_count": 2,
  "drafts_created": 2,
  "export_blocked": true,
  "export_blockers": ["SAD/ZC429 not yet received", "PZ not yet generated"]
}
```

**If `client_count = 0`:** pipeline is not reading the client names. Check
`routes_proforma.py` pipeline query — the `query_sales_to_wfirma` call may
filter on `client_name`. Abort and investigate.

**If `drafts_created = 0` with `client_count = 2`:** draft write failed silently.
Check stderr logs: `Get-Content "C:\PZ\logs\pzservice.log" -Tail 50`.

---

### Step II — Verify client_contractor_id Populated on Packing Lines

The closure condition V1 requires `client_contractor_id` to be filled on both
`shipment_documents` (sales packing list) rows. This is a repeat of Section 2 Check 1,
run post-deploy to confirm the authority field was not cleared.

Re-run Check 1 from Section 2. Cross-reference the returned `client_contractor_id`
values against `customer_master` via Check 2.

**Pass condition:** both rows have `client_contractor_id` filled and both IDs
resolve in `customer_master.bill_to_contractor_id`.

**Fail condition:** either row has `client_contractor_id` empty after deploy →
the intake-contract fix did not backfill these rows. Apply Emergency Backfill
(Section 4) then re-verify.

Do not assert specific contractor IDs here. The authority answer comes from
Check 1 + Check 2. Whatever those return is the source of truth for V1.

---

### Step III — Preview Both Drafts via API

```powershell
# Get draft IDs from the drafts list
$drafts = $draftsJson | ConvertFrom-Json

foreach ($draft in $drafts.drafts) {
    $previewResponse = Invoke-WebRequest -UseBasicParsing -Headers $h `
      "$BASE/api/v1/proforma/preview/$($draft.id)" `
      | Select-Object -ExpandProperty Content
    Write-Host "--- Draft $($draft.id) ---"
    Write-Host $previewResponse
}
```

**Expected for each draft:**
- `"authority_mode": "upload_selected_client"`
- `"can_preview": true`
- `"draft_ready": true`
- `"export_blocked": true` (SAD/ZC429 not yet present — correct)
- `"status": "pending_local"`

---

## Section 4 — Closure Conditions (V1–V5)

All five must pass before this runbook is closed.

| # | Condition | Check |
|---|-----------|-------|
| V1 | `client_contractor_id` filled on both `shipment_documents` (sales packing list) rows | Step II SQL above |
| V2 | `drafts.count = 2` for batch `SHIPMENT_9198333502_2026-05_87257361` | Pre-Step I check |
| V3 | Pipeline endpoint returns `client_count = 2` | Step I response |
| V4 | Authority groups = 2, `unassigned = []` | Step I response or `GET /api/v1/proforma/pipeline/{B}` |
| V5 | Preview for both drafts returns `authority_mode = upload_selected_client` | Step III response |
| + | No new stderr tracebacks in `pzservice.log` during repair | `Get-Content "C:\PZ\logs\pzservice.log" -Tail 100` |

**Closure signoff:**

| # | Pass | Notes |
|---|------|-------|
| V1 | ☐ | |
| V2 | ☐ | |
| V3 | ☐ | |
| V4 | ☐ | |
| V5 | ☐ | |
| Logs clean | ☐ | |

**QA signed by:** _________________________  
**Date closed:** _________________________

---

## Section 4a — Emergency Backfill (only if V1 fails after deploy)

Trigger: Check 1 returns empty `client_contractor_id` on one or both rows.

**Step 1 — Determine correct contractor IDs from operator**

Do not derive contractor IDs from filenames, packing-list text, or `sales_documents.client_name`.
Ask the operator: *"Which contractor should be assigned to each sales packing list document?"*
Get the contractor IDs from `customer_master`:

```powershell
# List all contractors the operator may intend
& "C:\PZ\service\python.exe" -c "
import sqlite3
conn = sqlite3.connect('C:/PZ/storage/customer_master.sqlite')
conn.row_factory = sqlite3.Row
for row in conn.execute('SELECT bill_to_contractor_id, bill_to_name FROM customer_master ORDER BY bill_to_name'):
    print(dict(row))
"
```

**Step 2 — Operator confirms mapping**

Operator must explicitly state:
- Document row A (`file_name = <value from Check 1>`) → contractor_id = `<X>`
- Document row B (`file_name = <value from Check 1>`) → contractor_id = `<Y>`

**Step 3 — Write only after operator confirmation**

```powershell
# Template — fill in <DOC_ID_A>, <CID_A>, <DOC_ID_B>, <CID_B> from operator confirmation
$updateSql = @"
UPDATE shipment_documents
SET client_contractor_id = CASE
    WHEN id = '<DOC_ID_A>' THEN '<CID_A>'
    WHEN id = '<DOC_ID_B>' THEN '<CID_B>'
    ELSE client_contractor_id
END
WHERE batch_id = 'SHIPMENT_9198333502_2026-05_87257361'
  AND document_type = 'sales_packing_list'
  AND COALESCE(client_contractor_id, '') = '';
"@
```

> **Never use filename pattern matching (`LIKE '%EJL%187%'`) as a contractor mapping signal.**
> Filenames are not authority. Match only on `id` (UUID) after operator confirmation.

---

## Section 5 — Proforma Authority Verification Protocol (reusable)

The stable authority chain for this workflow:

```
customer_master
    ↑
shipment_documents.client_contractor_id   ← authority
    ↑
sales_documents.document_id
    ↑
sales_document_id passed to preview / create
```

**Non-authority fields — do not use for contractor decisions:**
- `sales_documents.client_name`
- packing list text
- XLSX filename
- operator memory

### Canonical 5-step verification order

Run these in order. Do not skip ahead to step 5 to check UI rendering.

| Step | Check | Pass condition |
|------|-------|---------------|
| 1 | `shipment_documents.client_contractor_id` exists | Both rows populated |
| 2 | `customer_master` resolves the contractor ID | `bill_to_name` returned for both IDs |
| 3 | `proforma_drafts` exist | `count ≥ 1` per expected client |
| 4 | Preview resolves through sales_document_id | `authority_mode = upload_selected_client` |
| 5 | UI renders | No blank page, correct client shown |

### Interpretation table

| Result | Action |
|--------|--------|
| `client_contractor_id` populated and resolves in `customer_master` | No contractor repair required |
| `client_contractor_id` empty | Repair plan required (Section 4) |
| `sales_documents.client_name` differs from `customer_master` name | Investigate separately — does not prove authority failure |
| Filename or XLSX text differs from expected | Ignore for authority decisions |

Only after steps 1–4 pass should any investigation look at `sales_documents.client_name`,
filenames, or packing-list labels. Those are presentation and data-quality concerns, not
customer authority.

---

## Section 6 — What This Runbook Does NOT Cover

- wFirma write (PZ posting) — blocked by export gate; do not attempt
- SAD/ZC429 import — separate flow triggered when DHL customs clears
- Duty calculation — not touched here
- Fiscal export — blocked until SAD received; correct
- Product creation — separate Issue #378 tracks the SAD-gate bug

---

## Related

- **Issue #378:** `_guard_wfirma_export` incorrectly placed in `wfirma_products_resolve()` and `wfirma_products_sync_names()` — product master should not require SAD/ZC429
- **PR #377:** Proforma gate decoupling (`draft_ready` vs `ready`)
- **PR #376:** DHL automation inbox navigation bridge (Lesson F)
- **Lesson F:** V1-FREEZE — `shipment-detail.html` critical fixes only
- **Lesson I:** Incidents must become workflow-class rules, not shipment patches
