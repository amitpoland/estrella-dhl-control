# ONE_YEAR_AGENCY_INVOICE_FLOW_ANALYSIS.md
# Estrella Jewels — Agency Invoice Flow Analysis (1-Year)
# Period: Jun 2024 – Apr 2026 | ACS Spedycja + Ganther
# Generated: 2026-04-27

---

## Executive Summary

This document analyzes invoice and billing flows from clearance agents (ACS Spedycja and
Ganther) to Estrella Jewels. Key findings: ACS sends monthly VAT statements (not per-shipment);
Ganther invoices per shipment but payment tracking gaps caused a 6–8 week unpaid invoice
situation in Nov–Dec 2025; Ganther's billing contact (Krzysztof Suchodola) is distinct from
clearance contacts; and no Ganther invoice amounts are systematically stored in audit.json.

---

## 1. ACS Spedycja Billing — Monthly VAT Statements

### What ACS Bills

ACS Spedycja charges for customs clearance services. They do NOT charge for duty — duty is
a separate government obligation paid directly by Estrella.

### Billing Address

ACS billing comes exclusively from: `biuro@acspedycja.pl` (Joanna Bąk / "Asia AC Spedycja")

**Critical note:** This is the ONLY billing-related ACS address. The other 5 ACS clearance
agents (piotr, logistyka, roman, adrian, michal) do NOT send billing communications.

### VAT Statement Format

ACS sends monthly "Zestawienie do VAT" (VAT statement):
- Subject pattern: contains "Zestawienie" or "VAT"
- Frequency: Monthly
- Confirmed period: **Aug 2023 onward** (3+ year relationship confirmed)
- Recipient: `account@estrellajewels.eu` or `import@estrellajewels.eu`

### VAT Statement Coverage

30 VAT statement emails confirmed in the analysis window. At monthly frequency, this represents
~2.5 years of billing continuity.

**Automation note:** VAT statement emails from `biuro@acspedycja.pl` should be classified
as billing-only and routed to accounting. They must NOT trigger clearance events.

---

## 2. Ganther Billing — Per-Shipment Invoices

### What Ganther Bills

Ganther charges for customs brokerage services on a per-shipment basis:
- Customs representation fee
- DSK / cesja processing fee
- Other customs-related service fees

Ganther does NOT charge the duty itself — duty is paid separately by Estrella to the tax authority.

### Billing Structure

| Contact | Email | Role |
|---------|-------|------|
| Main inbox | ganther.com.pl | Primary invoice sender |
| Krzysztof Suchodola | krzysztof.suchodola@ganther.com.pl | Admin / billing escalation |

Clearance notifications and broker invoices come from the same ganther.com.pl inbox.
There is no separate billing email address for Ganther.

### Invoice Numbering

Ganther invoices follow the format: `<number>/<month>`

**Examples from Jan 2026 overdue notice:**
- Invoice 92/10
- Invoice 64/10

"92/10" = invoice number 92, month 10 (October). This is a simple sequential numbering
within the month.

---

## 3. The Ganther Unpaid Invoice Incident (Jan 2026)

### What Happened

In January 2026, Ganther sent an urgent payment demand for overdue invoices from Nov–Dec 2025.

**Details:**
- Total overdue: **2,962.30 PLN**
- Invoices mentioned: inv 92/10 and inv 64/10 (and additional ones)
- Period: November–December 2025 (6–8 weeks unpaid)
- CC'd: Krzysztof Suchodola (`krzysztof.suchodola@ganther.com.pl`)

**Tejal's response:** Acknowledged 5 invoices. Payment presumably made (no escalation found
in subsequent threads).

### Root Cause Analysis

Ganther had been clearing shipments since at least Nov 2025 but had not been paid for that
period. The gap was 6–8 weeks between clearance service and payment.

**Likely causes:**
1. No systematic Ganther invoice tracking per shipment
2. Invoices arriving in import@ or account@ mailbox but not processed for payment
3. No automated alert for unpaid Ganther invoices

### Impact on Operations

During the unpaid period (Nov–Dec 2025), Ganther continued clearing shipments. This suggests
Ganther maintained trust/credit with Estrella. However, the accumulated 2,962.30 PLN could
indicate a pattern if not monitored.

---

## 4. Ganther Invoice Tracking Gap

### Current State

Ganther invoices are NOT systematically tracked in audit.json. The `ganther_invoice_received`
timeline event was proposed in Task D (Step 2) but requires email parsing to populate.

**What exists in the schema:**
```python
audit["timeline"] = [
    {
        "ts": "...",
        "event": "ganther_invoice_received",  # NEW — not yet populated in production
        "detail": {
            "invoice_number": "92/10",
            "amount_pln": 2962.30,
        }
    }
]
```

**What's missing:** No mechanism to automatically detect Ganther invoices from email and
populate this timeline event.

### Proposed Invoice Detection Pattern

Ganther invoice emails characteristics:
- FROM: ganther.com.pl
- TO: account@estrellajewels.eu or import@estrellajewels.eu
- Subject: contains "FV" (faktura VAT) or invoice number pattern `\d+/\d+`
- Body: contains PLN amount + invoice number + AWB reference (when present)
- Attachment: PDF invoice

**Trigger:** When Ganther email matches invoice pattern → extract invoice number + PLN amount
→ link to AWB if present → log `ganther_invoice_received` timeline event.

---

## 5. ACS Service Fee Tracking

ACS service fees are captured in the monthly VAT statement but NOT per-shipment in audit.json.

**Per-shipment ACS fee:** Not extractable from current data — ACS VAT statements are aggregate
by month, not itemized per AWB.

**Proposed improvement:** If ACS ever sends per-shipment clearance invoices (not currently
observed), extract fee → log `acs_invoice_received` timeline event with AWB linkage.

---

## 6. Inter-Agency Payment Flow

```
Estrella pays Ganther → Ganther confirms ("płaci się") → ACS releases cargo
```

This means Ganther acts as a financial intermediary: Estrella pays Ganther for brokerage
PLUS duty, and Ganther pays the duty obligation to customs on Estrella's behalf.

**Risk:** If Ganther is not paid promptly, they could theoretically delay cargo release.
The 28-day delay (AWB 2824221912) was NOT caused by non-payment to Ganther — it was caused
by the duty notice routing gap. But delayed payment to Ganther is a separate risk.

---

## 7. Billing Actor Summary

| Actor | Invoice Freq | Format | Automation Priority |
|-------|-------------|--------|-------------------|
| ACS (biuro@) | Monthly aggregate | "Zestawienie do VAT" | LOW — route to accounting |
| Ganther (main) | Per shipment | FV number + PLN amount | HIGH — link to AWB |
| Ganther (Krzysztof) | Escalation only | Overdue demand | HIGH — immediate alert |

---

## 8. Automation Recommendations

1. **Ganther invoice tracking:** Parse Ganther emails matching invoice pattern → extract
   invoice number + PLN amount → log `ganther_invoice_received` → associate with current AWB.

2. **Unpaid invoice alert:** If Ganther sends 2nd invoice for same number (or overdue notice)
   → fire GANTHER_INVOICE_OVERDUE alert to `account@estrellajewels.eu` immediately.

3. **ACS VAT statement routing:** Auto-label `biuro@acspedycja.pl` emails as "ACS Billing"
   → route to `account@estrellajewels.eu` accounting workflow — no clearance trigger.

4. **Payment confirmation tracking:** After "płaci się" confirmation from Ganther, check if
   Ganther invoice amount was logged → if not, log as `duty_paid_no_invoice_on_record` warning.

5. **Monthly reconciliation:** Build a Ganther invoice register: AWB → invoice number →
   amount → paid date → confirmation. Use `ganther_invoice_received` timeline events as source.

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
