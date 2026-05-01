# ONE_YEAR_ATTACHMENT_INTELLIGENCE.md
# Estrella Jewels — Email Attachment Intelligence (1-Year)
# Period: Jun 2024 – Apr 2026 | All Carriers + Agents
# Generated: 2026-04-27

---

## Executive Summary

This document catalogs all significant email attachment types observed in Estrella's customs
clearance operations. 7 distinct document types are identified. The most operationally critical
are: ZC429 (customs clearance proof), Ganther duty invoices (trigger payment), and ACS VAT
statements (monthly accounting). The WinSADMS automated ZC429 attachment from `no-reply@acspedycja.pl`
is the highest-value automation target — it contains the MRN that links a shipment to its
customs declaration.

---

## 1. Document Type Catalog

### Type 1: ZC429 / SAD (Polish Customs Document)

**Source:** `no-reply@acspedycja.pl` (automated)
**Filename pattern:** `ZC429_<MRN>_1_PL.pdf`
**Example:** `ZC429_26PL44302D005LJ4R0_1_PL.pdf`

**Contents:**
- MRN (Merchandise Release Number) — unique customs identifier
- Importer details (name, VAT, address)
- Goods description and quantity
- Declared CIF value (USD)
- Duty amount A00 (PLN) — only reliable duty source
- VAT B00 (PLN) — reference only, not in landed cost
- Customs exchange rate
- ACS agent declaration

**Automation value:** CRITICAL
- MRN extraction → links AWB to customs declaration
- CIF USD value → cross-reference with invoice CIF
- A00 duty → must match Ganther duty notice amount

**Current usage:** PZ processor reads ZC429 as primary input. Not currently auto-extracted
from email — user manually uploads to dashboard.

**Proposed automation:** Detect `no-reply@acspedycja.pl` → download attachment → auto-upload
to PZ processor batch → log `sad_uploaded` timeline event.

---

### Type 2: DHL Cesja Document

**Source:** `odprawacelna@dhl.com` (forwarded to ACS)
**Filename pattern:** Variable — typically `cesja_AWB<number>.pdf` or similar
**Recipient:** `roman@acspedycja.pl` or other ACS agent (NOT Estrella)

**Contents:**
- DHL internal authorization for customs representation
- AWB reference
- Importer identification
- Legal authorization text (Polish)

**Automation value:** LOW for Estrella directly (attachment goes to ACS, not Estrella)
- Detection: DHL cesja Fwd email → log `dhl_cesja_forwarded` timeline event
- Estrella does not need to process this attachment

---

### Type 3: FedEx Cesja Form

**Source:** `pl-import@fedex.com` (sent to Estrella for completion)
**Filename pattern:** Variable — FedEx standard form PDF

**Contents:**
- Importer identification fields (to be filled)
- AWB reference
- Authorization language for Ganther to act as customs rep
- Signature/stamp fields

**Automation value:** HIGH
- Detection: FedEx cesja form received → trigger 24h countdown for submission
- After submission: FedEx sends auto-ack PDF → log `cesja_submitted`

**Required action:** Estrella must sign, scan, and return this to `pl-import@fedex.com`.
This is a manual human step — automation can only detect and alert.

---

### Type 4: Ganther Duty Invoice (FV / Faktura VAT)

**Source:** `ganther.com.pl` (primary) or `krzysztof.suchodola@ganther.com.pl` (escalation)
**Filename pattern:** Variable — typically `FV<number>.pdf` or `faktura_<date>.pdf`

**Contents:**
- Ganther brokerage service fee (PLN)
- Invoice number (e.g., 92/10)
- AWB reference (sometimes embedded)
- Bank account for payment
- Due date

**Automation value:** HIGH
- Extract invoice number → link to AWB
- Extract PLN amount → log `ganther_invoice_received` in timeline
- Track payment status → alert if unpaid after 14 days

**Currently:** Not systematically tracked. The Jan 2026 overdue incident (2,962.30 PLN) is
evidence that Ganther invoices are not monitored.

---

### Type 5: ACS VAT Statement ("Zestawienie do VAT")

**Source:** `biuro@acspedycja.pl` (Joanna Bąk)
**Filename pattern:** Variable — typically includes month reference
**Frequency:** Monthly

**Contents:**
- Summary of ACS services for the month
- Per-shipment breakdown of clearance services
- VAT invoice totals
- Bank account for payment

**Automation value:** MEDIUM
- Route to `account@estrellajewels.eu` accounting workflow
- Do NOT trigger clearance events from this attachment
- Could extract per-shipment ACS service fees if needed for cost analysis

---

### Type 6: Ganther PZC (Potwierdzenie Zgłoszenia Celnego)

**Source:** `ganther.com.pl` or ACS agents
**Filename pattern:** Variable — typically `PZC_<MRN>.pdf` or `potwierdzenie_<date>.pdf`

**Contents:**
- Official Polish customs clearance confirmation
- MRN reference
- Goods cleared confirmation
- ACS agent details
- Date/time stamp

**Automation value:** HIGH
- Detection: PZC received → set `pzc_issued = True` → log `pzc_received` timeline event
- This document confirms clearance is complete and cargo can be released after duty payment

---

### Type 7: W-firma Accounting Entries

**Source:** `tejal@estrellajewels.com` or `import@estrellajewels.eu`
**Destination:** `accounts@gjlindia.com` (Sandeep)
**Format:** PDF or XLS — W-firma (Polish accounting software) export

**Contents:**
- Accounting journal entries for duty and invoice values
- PLN amounts with exchange rate references
- GJL India inter-company tracking codes

**Automation value:** NONE for clearance
- This is pure inter-company accounting
- Do NOT trigger clearance events from W-firma attachments

---

## 2. Attachment Routing Matrix

| Attachment | From | To | Automation Action |
|-----------|------|----|--------------------|
| ZC429 PDF | no-reply@acspedycja.pl | import@estrellajewels.eu | Extract MRN → log sad_uploaded |
| DHL cesja | odprawacelna@dhl.com | ACS agents | Log dhl_cesja_forwarded |
| FedEx cesja form | pl-import@fedex.com | import@estrellajewels.eu | Start 24h cesja submission countdown |
| FedEx cesja auto-ack | pl-import@fedex.com | import@estrellajewels.eu | Log cesja_submitted |
| Ganther FV invoice | ganther.com.pl | account@estrellajewels.eu | Extract invoice no + PLN → log ganther_invoice_received |
| ACS VAT statement | biuro@acspedycja.pl | account@estrellajewels.eu | Route to accounting — no clearance trigger |
| Ganther PZC | ganther.com.pl | import@estrellajewels.eu | Log pzc_received → set pzc_issued=True |
| W-firma entries | import@, tejal@ | accounts@gjlindia.com | No action — inter-company accounting |

---

## 3. Attachment Naming Conventions

### ZC429 Filename → MRN Extraction

```python
import re

def extract_mrn_from_filename(filename: str) -> str | None:
    """Extract MRN from ZC429 attachment filename."""
    # Pattern: ZC429_<MRN>_1_PL.pdf
    m = re.match(r'ZC429_([A-Z0-9]+)_\d+_PL\.pdf', filename, re.IGNORECASE)
    return m.group(1) if m else None

# Example:
# ZC429_26PL44302D005LJ4R0_1_PL.pdf → "26PL44302D005LJ4R0"
```

### AWB from DHL Arrival Email

AWB appears in the email subject and body of `odprawacelna@dhl.com` emails.
DHL ticket reference format: `[T#1WA{YYYYMMDD}{SEQ}]` — this is NOT the AWB.

```python
import re

def extract_awb_from_dhl_email(text: str) -> str | None:
    """Extract DHL AWB from email body or subject."""
    # DHL AWBs are 10-digit numbers
    m = re.search(r'\b(\d{10})\b', text)
    return m.group(1) if m else None
```

---

## 4. Attachment Volume Estimate

Over the 12-month analysis period, estimated attachment volume:

| Type | Frequency | Estimated Count |
|------|-----------|----------------|
| ZC429 PDFs | ~1 per DHL shipment | 25–35 |
| DHL cesja Fwds | ~1 per DHL shipment | 25–35 |
| FedEx cesja forms | ~1 per FedEx shipment | 3 |
| Ganther FV invoices | ~1 per shipment | 30–40 |
| ACS VAT statements | Monthly | 12–14 |
| Ganther PZC | ~1 per DHL shipment | 25–35 |
| W-firma entries | Monthly or per shipment | 15–25 |

Total estimated attachments processed manually: **135–186 over 12 months.**

Automation potential: ZC429 detection + MRN extraction alone would save ~30–35 manual uploads
per year.

---

## 5. Automation Priority by Attachment Type

| Priority | Attachment | Reason |
|----------|-----------|--------|
| 1 | ZC429 PDF (MRN extraction) | Links AWB to customs declaration; enables PZ processor auto-trigger |
| 2 | Ganther FV invoice | Enables duty payment tracking; prevents overdue accumulation |
| 3 | FedEx cesja auto-ack | Confirms manual step completed; stops T3 alert |
| 4 | Ganther PZC | Confirms clearance; enables cargo release tracking |
| 5 | ACS VAT statement routing | Reduces manual accounting work |

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
