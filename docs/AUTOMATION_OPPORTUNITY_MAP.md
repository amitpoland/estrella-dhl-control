# AUTOMATION_OPPORTUNITY_MAP.md
# Estrella Jewels — Customs Clearance Automation Opportunity Map
# Generated from 12-Month Email Intelligence Analysis
# Generated: 2026-04-27

---

## Overview

This document maps every confirmed automation opportunity identified from the 12-month
email analysis. Opportunities are scored by: **Impact** (business value), **Effort** (implementation
complexity), and **Risk** (automation risk level). "Suggest-only" means the system proposes
an action but never executes it without human approval.

**Automation philosophy (from user):**
> Cowork should first become an intelligence analyst.
> Then it becomes a monitor. Only later it becomes an action assistant.

All items in Phase 1 (Monitor) produce suggestions or alerts. No action execution.
Phase 2+ items are flagged as requiring explicit future approval.

---

## Phase 1 — Intelligence & Monitoring (Suggest-Only, No Code Execution)

### OP-01: ZC429 MRN Extraction from AIS Email

**Trigger:** Email received from `no-reply@acspedycja.pl` with ZC429 attachment

**What it does:** Extract MRN from filename → log `sad_uploaded` event with MRN in detail
→ cross-reference with known AWBs → update `audit["zc429_mrn"]`

**Impact:** HIGH — currently all ZC429 PDFs are manually uploaded to PZ processor
**Effort:** LOW — filename regex is straightforward
**Risk:** LOW — read-only, no action taken

**Implementation:**
```python
# Detect AIS notification:
if sender == "no-reply@acspedycja.pl" and has_attachment("ZC429_"):
    mrn = re.match(r'ZC429_([A-Z0-9]+)_\d+_PL\.pdf', attachment.name).group(1)
    timeline.log_event(audit, "sad_uploaded", detail={"mrn": mrn, "source": "ais_auto"})
    audit["zc429_mrn"] = mrn
```

**Status:** Not implemented. Add to Phase 1 roadmap.

---

### OP-02: DHL Warehouse Arrival Detection

**Trigger:** Email received from `odprawacelna@dhl.com`

**What it does:** Parse AWB from subject/body → log `carrier_arrived` event →
set `audit["tracking"]["arrived_warehouse"] = True` → start DSK missing countdown

**Impact:** HIGH — enables T1 (DSK_MISSING) to fire reliably
**Effort:** LOW — sender-based detection, AWB regex extraction
**Risk:** LOW — read-only

**AWB extraction:**
```python
# DHL AWBs are 10-digit numbers in email subject/body
awb = re.search(r'\b(\d{10})\b', email_text).group(1)
```

**Status:** Not implemented. Critical for T1 trigger to work in production.

---

### OP-03: FedEx Cesja Submission Alert (T3)

**Trigger:** Email received from `pl-import@fedex.com` (arrival notification)

**What it does:** Log `fedex_arrived` event → set 24h countdown → if no cesja auto-ack
received within 24h, fire T3 suggestion: "Submit cesja form to pl-import@fedex.com for AWB <number>"

**Impact:** HIGH — prevents FedEx cesja delay (confirmed near-miss AWB 887467026597)
**Effort:** MEDIUM — requires FedEx email parsing + 24h countdown state
**Risk:** LOW — suggest-only, no form submission automated

**Status:** T3 trigger defined in COWORK_MONITORING_RULES_V3.md but email detection not implemented.

---

### OP-04: Duty Routing Gap Detection (T9)

**Trigger:** Ganther sends duty notice to `amit@` without `account@` in TO

**What it does:** Parse Ganther email recipients → if duty amount present (PLN) and
`account@estrellajewels.eu` is NOT in TO → fire T9: DUTY_ROUTING_GAP suggestion

**Impact:** HIGH — prevents recurrence of 28-day delay (AWB 2824221912)
**Effort:** LOW — email header parsing
**Risk:** LOW — suggest-only

**Detection pattern:**
```python
if (sender_domain == "ganther.com.pl" and
    has_pln_amount(email_body) and
    "account@estrellajewels.eu" not in email.to):
    fire_trigger("DUTY_ROUTING_GAP", awb=..., detail={"to": email.to})
```

**Status:** T9 defined in COWORK_MONITORING_RULES_V3.md. Email detection not implemented.

---

### OP-05: Duty Amount Extraction

**Trigger:** Ganther sends duty invoice email (PLN amount in body)

**What it does:** Extract PLN duty amount → store in `audit["duty_amount_pln"]` →
log `duty_notice_received` event with amount in detail

**Impact:** MEDIUM — enables duty tracking, Ganther invoice reconciliation
**Effort:** LOW — regex for PLN amount in Ganther email

**PLN amount regex:**
```python
duty_pln = re.search(r'(\d[\d\s,]+)\s*PLN', email_body)
# Clean: duty_pln.group(1).replace(' ', '').replace(',', '.')
```

**Status:** `duty_amount_pln` field exists in audit schema. Not populated from email.

---

### OP-06: Ganther Invoice Tracking

**Trigger:** Ganther sends FV (Faktura VAT) invoice email or attachment

**What it does:** Extract invoice number + PLN amount + AWB reference →
log `ganther_invoice_received` event → if 2nd notice for same AWB → fire GANTHER_OVERDUE alert

**Impact:** MEDIUM — prevents overdue accumulation (2,962.30 PLN incident Jan 2026)
**Effort:** MEDIUM — invoice detection requires pattern matching
**Risk:** LOW

**Status:** `ganther_invoice_received` event defined in timeline.py. Not populated.

---

### OP-07: "Płaci się" Payment Confirmation Detection

**Trigger:** Ganther sends email containing "płaci się" / "placi sie" / "Zapłata odebrana"

**What it does:** Log `duty_paid_signal_at` → set `duty_paid = True` → stop T2 clock

**Impact:** MEDIUM — closes duty payment loop; confirms cargo release is authorized
**Effort:** LOW — keyword match on confirmed phrase variants
**Risk:** LOW

**Confirmed phrase variants:**
```python
PAYMENT_CONFIRMED_PHRASES = [
    "płaci się",
    "placi sie",
    "dzieki, płaci się",
    "dzięki płaci się",
    "Zapłata odebrana",
    "płatność odebrana",
]
```

**Status:** `duty_paid_signal_at` field exists. Not populated from email.

---

### OP-08: VAT Deferment Gap Detection

**Trigger:** Ganther email contains VAT deferment keywords

**What it does:** Fire VAT_DEFERMENT_GAP alert → immediate notification to
`account@estrellajewels.eu` + `amit@estrellajewels.eu`

**Impact:** HIGH — VAT deferment lapse causes hard clearance block (Dec 2025 confirmed)
**Effort:** LOW — keyword match
**Risk:** LOW

**Detection keywords:**
```python
VAT_DEFERMENT_KEYWORDS = [
    "VAT Deferment",
    "odroczenie VAT",
    "brak pozwolenia",
    "pozwolenie wygasło",
    "no permission for VAT",
    "VAT zostanie zapłacony przed",
]
```

**Status:** NOT DEFINED in current monitoring rules. New trigger required.

---

### OP-09: FCA Complication Flag

**Trigger:** Ganther email mentions "FCA" (Free Carrier incoterms)

**What it does:** Set `fca_complication = True` in audit → log event →
suggest to `import@estrellajewels.eu`: "FedEx shipment AWB <number> uses FCA incoterms.
Ganther will need transport invoice — request from shipper now."

**Impact:** LOW–MEDIUM — saves 1–2 day delay on FCA FedEx shipments
**Effort:** LOW — keyword match
**Risk:** LOW

**Status:** NOT DEFINED. New trigger required.

---

### OP-10: Clearance SLA Monitoring

**Trigger:** `carrier_arrived` event logged → SLA countdown starts

**What it does:** After carrier arrival:
- If DHL: alert at Day 4 if no `duty_notice_received` event logged
- If FedEx: alert at Day 7 if no `cargo_released` event logged

**Impact:** HIGH — catches all slow clearances proactively before storage fees begin
**Effort:** MEDIUM — requires carrier arrival detection (OP-02/OP-03) first
**Risk:** LOW

**Status:** NOT DEFINED. Depends on OP-02 (DHL arrival) and OP-03 (FedEx arrival).

---

### OP-11: ACS VAT Statement Auto-Routing

**Trigger:** Email from `biuro@acspedycja.pl` with subject containing "Zestawienie"

**What it does:** Auto-label email → route to `account@estrellajewels.eu` accounting workflow
→ log `acs_vat_statement_received` → do NOT trigger clearance events

**Impact:** LOW — reduces manual sorting
**Effort:** LOW — rule-based routing
**Risk:** NONE

**Status:** NOT DEFINED. Optional quality-of-life improvement.

---

### OP-12: DHL Ticket Number Extraction

**Trigger:** Any `odprawacelna@dhl.com` email

**What it does:** Extract `[T#1WA{date}{seq}]` ticket reference → store in audit →
use for email thread reconstruction

**Impact:** LOW — enables better audit trail reconstruction
**Effort:** LOW — regex

```python
ticket = re.search(r'\[T#1WA\d+\]', email_subject)
```

**Status:** NOT DEFINED. Nice-to-have.

---

## Phase 2 — Action Assistance (Requires Explicit Approval)

These opportunities involve Claude taking actions (not just alerting). Each requires explicit
one-time or per-action approval.

### OP-A1: ZC429 Auto-Upload to PZ Processor

**What:** Receive ZC429 from AIS email → auto-upload to PZ processor batch for the AWB

**Approval needed:** Confirmed AWB→batch linkage before upload
**Risk:** MEDIUM — wrong AWB could corrupt a batch

### OP-A2: Duty Payment Confirmation Reply to Ganther

**What:** When duty paid (confirmed by `account@`), send confirmation email to ganther.com.pl

**Approval needed:** User must approve each payment confirmation message
**Risk:** LOW but email composition requires approval

### OP-A3: FedEx Cesja Form Submission

**What:** Pre-fill cesja form from known importer data → send to `pl-import@fedex.com`

**Approval needed:** User must review and approve each cesja submission
**Risk:** MEDIUM — legal document, must be human-reviewed before submission

### OP-A4: Ganther Invoice Payment Tracking

**What:** When Ganther invoice received → add to payment queue → alert on due date

**Approval needed:** Payment itself requires human action — alert only is Phase 1
**Risk:** LOW for alert; PROHIBITED for payment execution

---

## Summary Scorecard

| Opportunity | Impact | Effort | Status | Priority |
|------------|--------|--------|--------|----------|
| OP-01: ZC429 MRN extraction | HIGH | LOW | Not implemented | P1 |
| OP-02: DHL warehouse arrival | HIGH | LOW | Not implemented | P1 |
| OP-03: FedEx cesja alert (T3) | HIGH | MEDIUM | Partially defined | P1 |
| OP-04: Duty routing gap (T9) | HIGH | LOW | Partially defined | P1 |
| OP-05: Duty amount extraction | MEDIUM | LOW | Schema exists | P2 |
| OP-06: Ganther invoice tracking | MEDIUM | MEDIUM | Event defined | P2 |
| OP-07: "Płaci się" detection | MEDIUM | LOW | Schema exists | P2 |
| OP-08: VAT deferment gap | HIGH | LOW | Not defined | P1 |
| OP-09: FCA flag | LOW | LOW | Not defined | P3 |
| OP-10: Clearance SLA monitor | HIGH | MEDIUM | Not defined (needs OP-02/03) | P2 |
| OP-11: ACS statement routing | LOW | LOW | Not defined | P3 |
| OP-12: DHL ticket extraction | LOW | LOW | Not defined | P3 |

**P1 items (6):** OP-01, OP-02, OP-03, OP-04, OP-08 — all high-impact, low-effort or partially defined
**P2 items (4):** OP-05, OP-06, OP-07, OP-10 — medium impact, builds on P1
**P3 items (3):** OP-09, OP-11, OP-12 — quality of life improvements

---

*This map is evidence-based from 12 months of email thread examination.*
*No production changes proposed here — requires explicit admin approval before implementation.*
