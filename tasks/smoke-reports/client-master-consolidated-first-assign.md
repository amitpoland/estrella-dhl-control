# Smoke report — Consolidated Client Master first Save/Assign

**Date:** 2026-05-16
**Production SHA:** `9c81367` (PR #150 — Consolidate Client Master UI into one surface)
**Service:** PZService RUNNING
**Local + public health:** 200 / 200

This report is a **template**. Server-side validation (Phase 0) was completed
by the agent. **Phase 1 (browser), Phase 2 (client assign), and Phase 3
(supplier assign) require explicit operator action** — the brief says
*"operator approves it as safe"* per row pick, which the agent cannot do
autonomously.

---

## Phase 0 — Server-side pre-validation (PASS)

| Check | Result |
|---|---|
| Service status | RUNNING |
| Local `/api/v1/health` | 200 |
| Public `/api/v1/health` | 200 |
| Legacy `id: 'clients'` sidebar entry in dashboard.html | **0** (expected 0) |
| `'Client Master'` nav label | **1** |
| `cm-view-mode-chips` testid | **1** |
| Default view-mode `useState('master')` | **1** |
| Default `activeEntity` `useState('customer_master')` | **1** |
| Target selector options (`client_master`, `supplier_master`, `ignore`, `needs_operator_review`) | **1 each** |
| `'Fetch clients from wFirma'` button label | **2** (button + Review-pane CTA reference — correct) |
| Any-case `customer master` string in deployed dashboard | **0** |
| Backend routes registered | all 6 present (`/customer-master/`, `/customer-master/sync-from-wfirma/{preview,apply}`, `/suppliers/`, `/suppliers/sync-from-wfirma/{preview,apply}`) |
| Pre-assign baseline · Client Master rows | **9** |
| Pre-assign baseline · Supplier rows | **1** |
| Live preview total proposals | **221** |
| Live preview verdicts | `client_master=155, supplier_master=5, ignore=14, needs_operator_review=47` |
| Non-canonical verdicts | **0** (resolver model closed) |
| stderr | clean (uvicorn startup only) |
| `wfirma-write / finance_dual_write / create_contractor` log scan | **0 matches** |

---

## Phase 1 — Browser validation (OPERATOR)

Open `https://pz.estrellajewels.eu/dashboard/dashboard.html` (or the local URL),
log in as admin, navigate to **Master Data**, and tick each item:

| # | Check | Result (✓ / ✗ / note) |
|---|---|---|
| 1 | Master Data sidebar shows exactly one **Client Master** entry | |
| 2 | No separate **Clients** entry | |
| 3 | Opening Master Data lands on Client Master | |
| 4 | Default view-mode is **Master** | |
| 5 | Master view shows client master table + freight/insurance + Open full profile | |
| 6 | Identity chip → wFirma identity projection table renders | |
| 7 | Review chip → review pane (CTA when no review loaded) | |
| 8 | Click **Fetch clients from wFirma** → ~221 proposals load | |
| 9 | Target selector options visible: Client Master / Supplier Master / Ignore / Needs review | |
| 10 | KYC modal opens from Master view (**Open full profile** button) | |
| 11 | KYC modal opens from Identity view (**Edit** button on a row) | |
| 12 | Browser console: no red errors | |
| 13 | Browser network tab: no 4xx/5xx on happy path | |

**Verdict (operator):** ____ PASS / FAIL

Screenshots / notes:
- [ ] sidebar.png
- [ ] cm-master-view.png
- [ ] cm-identity-view.png
- [ ] cm-review-view.png
- [ ] kyc-modal-from-master.png
- [ ] kyc-modal-from-identity.png

---

## Phase 2 — Controlled local Client assign (OPERATOR)

**Only if Phase 1 verdict = PASS.** Pick exactly **one** safe row:
- `suggested_target` = `client_master`
- valid `name`, valid `country`
- not a duplicate of an existing local row
- not internal/tax/airline/hotel/vendor
- operator explicitly approves it as safe

Selected row:
- `wfirma_id`: ____
- `name`: ____
- `country`: ____
- `vat_id`: ____
- `suggested_target`: client_master

Action: change Assign-to to **Client Master** (or leave at default), click **Save / Assign**.

### Pre-assign DB snapshot
```powershell
$keyLine = (Get-Content "C:\PZ\.env" | Select-String -Pattern "^AUTH_SECRET_KEY=" | Select-Object -First 1).Line
$apiKey  = $keyLine -replace "^AUTH_SECRET_KEY=",""
$h = @{ "X-API-Key" = $apiKey }
$pre = Invoke-RestMethod "http://127.0.0.1:47213/api/v1/customer-master/?limit=500" -Headers $h
$pre.customers | Where-Object { $_.bill_to_contractor_id -eq "<WFID>" } |
  ConvertTo-Json -Depth 4
```
- Pre-row exists? ____
- Pre `bill_to_email`: ____
- Pre `freight_service_id`: ____
- Pre `insurance_rate`: ____
- Pre `kyc_status`: ____
- Pre `last_wfirma_sync_at`: ____

### Click Save / Assign

### Post-assign verification
```powershell
$post = Invoke-RestMethod "http://127.0.0.1:47213/api/v1/customer-master/?limit=500" -Headers $h
$post.count                                # expect pre+1 (or unchanged if update)
$row = $post.customers | Where-Object { $_.bill_to_contractor_id -eq "<WFID>" }
$row | Select-Object bill_to_contractor_id, bill_to_name, country, nip,
                       bill_to_email, bill_to_phone, bill_to_mobile, bank_account,
                       freight_service_id, freight_fixed_amount_eur,
                       insurance_rate, kyc_status, kuke_limit,
                       default_currency, preferred_proforma_series_id,
                       last_wfirma_sync_at, wfirma_sync_source
```

| Check | Pre | Post | Pass? |
|---|---|---|---|
| Client Master row count | 9 | ___ | |
| `bill_to_name` | ___ | (matches wFirma) | |
| `country` | ___ | (matches wFirma) | |
| `bill_to_contractor_id` (wFirma ID) | ___ | (= picked wfid) | |
| `freight_service_id` | ___ | **unchanged** | |
| `freight_fixed_amount_eur` | ___ | **unchanged** | |
| `insurance_rate` | ___ | **unchanged** | |
| `kyc_status` | ___ | **unchanged** | |
| `kuke_limit` | ___ | **unchanged** | |
| `default_currency` | ___ | (filled if was empty) | |
| `bill_to_email` | ___ | (filled if was empty AND wFirma had one) | |
| `last_wfirma_sync_at` | ___ | ISO timestamp set | |
| `wfirma_sync_source` | ___ | `review_assign` | |

### Side-effect checks
```powershell
Get-Content C:\PZ\logs\pz_stderr.log -Tail 10
(Get-Content C:\PZ\logs\pz_stderr.log | Select-String -Pattern 'wfirma.*write|finance_dual_write|create_contractor').Count
```
- stderr clean? ____
- wFirma-write log entries: ____ (expect 0)
- finance_dual_write log entries: ____ (expect 0)

**Verdict (operator):** ____ PASS / FAIL

---

## Phase 3 — Controlled local Supplier assign (OPERATOR)

**Only if Phase 2 verdict = PASS.** Pick exactly **one** safe row:
- `suggested_target` = `supplier_master`
- valid `name`, valid `wfirma_id`
- operator explicitly approves it as supplier

Selected row:
- `wfirma_id`: ____
- `name`: ____
- `country`: ____
- `suggested_target`: supplier_master

Action: change Assign-to to **Supplier Master** on this row, click **Save / Assign**.

### Pre-assign DB snapshot
```powershell
$pre = Invoke-RestMethod "http://127.0.0.1:47213/api/v1/suppliers/?limit=500" -Headers $h
$pre.suppliers | Where-Object { $_.wfirma_id -eq "<WFID>" } | ConvertTo-Json -Depth 4
```

### Post-assign verification
```powershell
$post = Invoke-RestMethod "http://127.0.0.1:47213/api/v1/suppliers/?limit=500" -Headers $h
$post.count                              # expect pre+1
$row = $post.suppliers | Where-Object { $_.wfirma_id -eq "<WFID>" }
$row | Select-Object id, supplier_code, name, country, vat_id,
                       address, contact_email, contact_phone,
                       wfirma_id, active, created_at, updated_at
```

| Check | Pre | Post | Pass? |
|---|---|---|---|
| Supplier row count | 1 | ___ (expect 2) | |
| `wfirma_id` | — | (= picked wfid) | |
| `name` | — | (matches wFirma) | |
| `country` | — | (matches wFirma) | |
| `supplier_code` | — | `WF-<wfid>-<NAME>` | |
| `eori` | — | NULL (operator fills later) | |
| `notes` | — | NULL | |
| `address` | — | opportunistically filled from wFirma if present | |
| `contact_email` | — | filled if wFirma surfaced one | |
| `active` | — | 1 | |

### Side-effect checks
```powershell
Get-Content C:\PZ\logs\pz_stderr.log -Tail 10
(Get-Content C:\PZ\logs\pz_stderr.log | Select-String -Pattern 'wfirma.*write|finance_dual_write|create_contractor').Count
```

**Verdict (operator):** ____ PASS / FAIL

---

## Phase 4 — Final regression + tracking

| Gate | Result |
|---|---|
| `python test_pz_regression.py` (post-assigns) | (operator runs after Phase 3) |
| `python service/scripts/campaign_status.py doctor` | (operator runs after Phase 3) |
| `tasks/campaign-state.json` updated with B0 consolidation closure | (operator) |

---

## Final verdict template

```
Browser validation : PASS / FAIL
Client assign      : PASS / FAIL / SKIPPED
Supplier assign    : PASS / FAIL / SKIPPED
DB changes         : <pre→post counts, fields verified>
Console            : <clean / errors listed>
Network            : <clean / 4xx-5xx listed>
Logs               : <stderr clean? wfirma-write count? finance count?>
Tests              : PZ regression <x/160>  doctor <clean / issues>
Final verdict      : READY-FOR-NEXT-BATCH / NEEDS-FIX / ROLLBACK
```

---

## What the agent did vs. what the operator must do

| Phase | Agent | Operator |
|---|---|---|
| 0 Server-side validation | ✓ done | n/a |
| 1 Browser validation | ✗ (no browser) | required (13 visual checks) |
| 2 Pick + assign one safe client | ✗ (cannot judge "safe") | required (single row, explicit approval, DB diff) |
| 3 Pick + assign one safe supplier | ✗ (cannot judge "safe") | required (single row, explicit approval, DB diff) |
| 4 Run regression + doctor | will run post-Phase-3 on request | confirm |

The DB-verification PowerShell snippets are written to be copy-pasted by the operator after each click. Pre/post counts and field-level diffs let the operator confirm preservation of freight/insurance/KYC and verify the new write is identity-only.
