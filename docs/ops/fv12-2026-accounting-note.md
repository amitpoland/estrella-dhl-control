# Operator Note — Invoice FV 12/2026 (wFirma ID 484110947)

**Date:** 2026-06-28  
**Author:** system investigation  
**Status:** PENDING ACCOUNTING DECISION

---

## What happened

Invoice FV 12/2026 was created in wFirma on 2026-06-28 at 15:52 Warsaw time for OMARA s.r.o (Slovakia, EU VAT SK2121868914).

At the time of conversion, `preferred_wdt_invoice_series_id` was not yet configured for the OMARA customer master. The conversion route received an empty series from the customer master lookup and wFirma applied the contractor's default series (FV domestic, series_id=15827082) instead of the WDT series (series_id=15827921).

---

## What is correct vs wrong

| Dimension | Status | Detail |
|---|---|---|
| VAT rate | CORRECT | vat_code=228 (WDT 0%) — correct for EU intra-community supply to Slovakia |
| Customer | CORRECT | OMARA s.r.o, SK, EU VAT SK2121868914 |
| Invoice series | WRONG | 15827082 (FV domestic) used instead of 15827921 (WDT series) |
| Document number | WRONG | FV 12/2026 instead of WDT x/2026 |
| KSeF registration | DONE | Reference: 5252812119-20260628-7087D4000001-6F |
| KSeF date | 2026-06-28 15:52:03 | Already submitted to tax authority |

---

## What cannot be changed automatically

- The invoice is registered with KSeF. The document number FV 12/2026 cannot be renumbered retroactively by the portal.
- No automated correction, cancellation, or reissuance has been performed.
- No further wFirma write calls have been made regarding this invoice.

---

## What accounting must decide

One of the following actions may be required — this is a business and accounting decision, not a code decision:

1. **No action** — if the accounting team determines that a WDT at 0% VAT in the FV series is acceptable for JPK_V7M purposes (the tax position is correct, only the series prefix is non-standard).

2. **Correction note (nota korygująca)** — a formal correction of the invoice series/number prefix issued by OMARA as the buyer, or by Estrella as the seller.

3. **JPK annotation** — a manual annotation in the JPK_V7M submission identifying this FV entry as a WDT transaction, if not already automatically tagged by wFirma's WDT VAT code.

4. **Cancellation and reissuance** — cancel FV 12/2026 in wFirma (generates a correction), reissue in the WDT series. Only if the accounting team determines this is required and KSeF allows it.

---

## Portal fix deployed

PR #786 (`fix/reconciliation-phase-a-persistence`) fixes the root cause:
- `preferred_wdt_invoice_series_id` is now returned by the Customer Master GET endpoint.
- `conversion_persistence.persist_invoice_to_draft()` now persists `sale_date`.

Future conversions for OMARA and other EU customers with `preferred_wdt_invoice_series_id` configured will correctly use the WDT series.

---

## Do not

- Do not create another invoice for this transaction.
- Do not call any wFirma write endpoint from the portal for FV 12/2026.
- Do not automate any KSeF or JPK correction.
- Do not attempt to renumber FV 12/2026 via the portal.
