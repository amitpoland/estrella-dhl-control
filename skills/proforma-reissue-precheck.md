# proforma-reissue-precheck

Read-only precheck before authorising cancel+reissue remediation of an
existing wFirma proforma whose persisted state is incomplete or has
the wrong VAT regime. Designed for the PROF 92/2026 case (Juliany
EOOD, BG, 12-line submission persisted as 1 line, vat_code 222 PL 23%
where WDT 0% should apply) but reusable for any future proforma whose
fields drifted from the source-of-truth payload.

## When to run

- Before any `/sync?write=true`, before any `WFIRMA_CREATE_PROFORMA_ALLOWED=true`
  retry, and before any invoices/delete authorisation.
- After a verify-after-create gate has surfaced a partial/wrong-VAT
  proforma in wFirma.
- Before final-invoice conversion of a proforma that may have been
  created on an outdated payload shape.

## What this skill does

1. Read PROF state — calls `wfirma_client.fetch_invoice_xml(id)`
   (read-only) and parses:
     - `<type>`               (must be `proforma` for cancel+reissue)
     - `<state>` / `<paymentstate>` / `<fiscalised>` flags
     - count of `<invoicecontent>` children
     - `<contractor><id>` (must equal local mapping)
     - vat_code id on each line
2. Verify customer master parity — looks up
   `wfirma_customers` by client_name and confirms:
     - row present
     - `wfirma_customer_id` non-empty
     - `country` non-blank
     - `vat_id` non-blank for EU non-PL customers (else WDT cannot
       be selected; the route's live-search fallback is a soft fix
       but not durable)
3. Simulate the reissue plan — runs
   `decide_proforma_vat_context(country, vat_id)` and
   `resolve_vat_code_id_for_context(decision.vat_code)` against the
   resolved customer state and reports the would-be `vat_code_id`
   plus the would-be line count from the current preview.
4. Cancel-feasibility check — confirms `<type>=proforma` (not
   `normal`). A converted final invoice cannot be cancelled by the
   proforma path; that requires invoice cancel + correction note,
   which is not in scope.
5. Safety report — confirms no writes occurred and that all live
   write flags remain false.

## What this skill never does

- Never calls `invoices/add`, `invoices/edit`, `invoices/delete`,
  `goods/edit`, `contractors/add`, or any other wFirma write endpoint.
- Never writes to local DB tables (`wfirma_customers`,
  `wfirma_products`, `proforma_drafts`, `proforma_invoice_links`).
- Never flips an env flag.
- Never proposes a value change beyond the documented target
  (WDT 0% on Juliany BG / 12-line target). Customs-value-freeze
  applies — totals, freight, duty, and qty come from the existing
  preview only.

## Output schema (fixed)

```
Endpoint:     <wFirma endpoints touched, all read-only>
Payload:      <country, vat_id, decided context+vat_code, resolved
              vat_code_id, would-be line count, would-be currency>
Validation:   <decision result, mappings complete Y/N, PROF
              cancellable Y/N, type=proforma confirmed, fiscalised N>
Safety:       <writes=0; flags WFIRMA_CREATE_PROFORMA_ALLOWED=false,
              WFIRMA_EDIT_INVOICE_ALLOWED=false,
              WFIRMA_SYNC_CUSTOMERS_ALLOWED=false confirmed;
              customs-value-freeze respected>
Required fix: <one sentence GREEN-or-RED verdict>
```

## Stop conditions (RED)

Any one of these must produce a RED verdict and stop:

- `<type>` ≠ `proforma` (already converted; cancel path closed)
- `<fiscalised>` truthy (rare on proformas, but kill-switch)
- contractor mapping not found locally OR remote contractor id
  differs from local mapping (data integrity issue — must reconcile
  before any cancel+reissue)
- `decide_proforma_vat_context` returns `blocked` (operator must
  fill country/vat_id manually, not auto-derived)
- `resolve_vat_code_id_for_context` raises (wFirma vat_code
  registry doesn't carry the expected `code` value)
- preview line count not equal to the target reissue line count
  (drift between source data and intended payload — operator must
  reconcile)
- any of the three write flags is currently true (operator left a
  gate open — close before precheck completes)
