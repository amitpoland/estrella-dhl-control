# ONE_YEAR_SYSTEM_GAP_REPORT.md
# Estrella Jewels — System Gap Report (1-Year)
# Period: Jun 2024 – Apr 2026 | All Systems
# Generated: 2026-04-27

---

## Executive Summary

This document catalogs confirmed gaps between what the cowork automation system currently
does and what the full 12-month evidence base reveals it should do. 19 gaps are identified
across 5 categories: detection, timeline, actor registry, compliance, and architecture.
All gaps are read-only findings — no production changes proposed without explicit approval.

---

## Category 1: Detection Gaps

### GAP-D01: DHL Arrival Not Auto-Detected

**Gap:** The system has no mechanism to detect when a DHL shipment arrives (email from
`odprawacelna@dhl.com`). The T1 trigger (DSK_MISSING) requires `arrived_warehouse=True`
but this is never set automatically.

**Evidence:** 35+ DHL arrival emails confirmed over 12 months. All manual.

**Impact:** T1 trigger cannot fire in production — it requires `arrived_warehouse=True`
which is never set from email.

**Required fix:** Parse `odprawacelna@dhl.com` email → extract AWB → set `arrived_warehouse=True`

---

### GAP-D02: FedEx Arrival Not Auto-Detected

**Gap:** The system has no mechanism to detect FedEx arrivals from `pl-import@fedex.com`.
T3 (DSK_MISSING FedEx) trigger is defined but never fires because arrival is not detected.

**Evidence:** AWB 887467026597 required manual awareness of FedEx arrival.

**Impact:** T3 trigger never fires — FedEx cesja delay goes undetected.

---

### GAP-D03: ZC429 AIS Notification Not Processed

**Gap:** `no-reply@acspedycja.pl` sends automated ZC429 notifications but this sender
was NOT in the original TRUSTED_CLEARANCE_SENDERS config. Even after adding (Task E),
no code extracts MRN from the ZC429 filename.

**Evidence:** 8 confirmed ZC429 AIS emails found with MRN numbers in filenames.

**Impact:** MRN→AWB linkage is manual. PZ processor cannot auto-trigger on ZC429 receipt.

---

### GAP-D04: "Płaci się" Payment Signal Not Detected

**Gap:** Ganther's payment confirmation phrases ("płaci się", "placi sie", etc.) are not
detected by any automated system. `duty_paid_signal_at` is never set from email.

**Evidence:** 15+ confirmed payment confirmations over 12 months across known phrase variants.

**Impact:** T2 (DUTY_PAYMENT_PENDING) cannot close automatically when payment is confirmed.

---

### GAP-D05: VAT Deferment Issue Not Detected

**Gap:** No keyword detection exists for VAT deferment lapse warnings from Ganther.
The Dec 2025 incident (AWB 6883058851) had no system alert.

**Evidence:** Confirmed Ganther message: "Estrella has no permission for VAT Deferment."

**Impact:** Next VAT deferment lapse causes clearance hold with no warning.

---

### GAP-D06: Ganther Invoice Not Detected

**Gap:** Ganther's per-shipment brokerage invoices (FV / Faktura VAT) are not detected
or linked to AWBs in the audit system. `ganther_invoice_received` timeline event never fires.

**Evidence:** Confirmed 2,962.30 PLN accumulated unpaid over Nov–Dec 2025 without alert.

**Impact:** Ganther invoice accumulation goes undetected until overdue demand arrives.

---

### GAP-D07: FCA Incoterms Not Detected

**Gap:** FCA incoterms in FedEx shipments require a transport invoice from the shipper.
This is not detected. Ganther must manually identify and request the transport invoice.

**Evidence:** AWB 887467026597 — FCA terms added 1 day to clearance.

**Impact:** Minor delay per FCA shipment; 1–2 extra days.

---

## Category 2: Timeline Gaps

### GAP-T01: `carrier_arrived` Event Missing

**Gap:** No `carrier_arrived` timeline event exists. The clearance SLA starts at carrier
arrival but the system has no way to record when arrival occurred.

**Impact:** Cannot compute clearance duration per shipment. SLA monitoring impossible.

---

### GAP-T02: `dsk_received` Event Not Populated

**Gap:** The `dsk_received` event is defined but never populated from email. DHL DSK
issuance (from ACS) and FedEx DSK issuance (from pl-import) are not detected.

**Impact:** T1 trigger (DSK_MISSING) cannot close when DSK received. May fire indefinitely.

---

### GAP-T03: `pzc_received` Event Not Populated

**Gap:** When Ganther sends PZC to Estrella, no timeline event is logged. PZC receipt
is the customs clearance confirmation — a critical milestone.

**Impact:** Cannot confirm clearance completion from timeline.

---

### GAP-T04: `cesja_submitted` Event Missing

**Gap:** No `cesja_submitted` event exists for FedEx cesja submission. After Estrella
submits the cesja form, there is no record of this in the audit system.

**Impact:** Cannot track FedEx cesja submission compliance. T3 cannot confirm closure.

---

### GAP-T05: `cargo_released` Event Missing

**Gap:** When cargo is released after duty payment, no event is logged. Delivery
confirmation from DHL/FedEx is not captured.

**Impact:** Cannot determine end-to-end clearance duration.

---

## Category 3: Actor Registry Gaps

### GAP-A01: Michał Cieślak Not in Trusted Config

**Gap:** `michal@acspedycja.pl` (6th ACS agent) was not in the original trusted senders
config. Active in Jun–Sep 2024. Now added in CARRIER_CLEARANCE_RULES.md (Task E) but
not yet in production config.

**Impact:** LOW — Michał inactive since Sep 2024. But if Michał returns, PZC emails
would not be recognized.

---

### GAP-A02: DHL Ticket Reference Not Stored

**Gap:** DHL internal ticket references `[T#1WA{date}{seq}]` are not extracted or stored.
These are valuable for reconstructing email threads per shipment.

**Impact:** LOW — audit reconstruction capability limited.

---

### GAP-A03: `kaushal@estrellajewelsllp.com` Not Classified

**Gap:** The India LLP entity email address appears in Ganther CC threads but is not
formally classified in any config. It should be in the DO_NOT_TRIGGER list.

**Impact:** LOW — risk of incorrect trigger if this address is misclassified.

---

## Category 4: Compliance Gaps

### GAP-C01: VAT Deferment Renewal Not Tracked

**Gap:** Estrella's VAT deferment permission (odroczenie VAT) has no renewal tracking.
The Dec 2025 lapse was caught by Ganther — not by any internal system.

**Evidence:** Confirmed lapse causing clearance hold on AWB 6883058851.

**Impact:** HIGH — next lapse could cause same hold without warning.

**Required fix:** Add VAT deferment expiry date to a tracked field (calendar entry, audit
configuration field, or compliance note). Set 30-day renewal reminder.

---

### GAP-C02: Ganther Invoice Reconciliation Not Implemented

**Gap:** There is no systematic reconciliation of Ganther invoices against cleared shipments.
The 2,962.30 PLN unpaid balance accumulated over 6–8 weeks without detection.

**Impact:** MEDIUM — financial exposure risk if pattern continues.

---

### GAP-C03: FedEx Billing Mode Not Verified

**Gap:** No process exists to verify FedEx duty billing mode = "sender pays" before
shipment creation. AWB 882994160903 (Aug 2025) had incorrect "recipient pays" setting.

**Impact:** MEDIUM — customers billed incorrectly; manual correction required.

---

## Category 5: Architecture Gaps

### GAP-AR01: Email-Based Tracking vs API Tracking

**Gap:** The system relies on email-inferred tracking. No DHL or FedEx API integration
exists. The `_dhl_pending_fallback()` function returns `email_inferred` source, not live
tracking data.

**Impact:** MEDIUM — tracking data is coarse (arrival/clearance email timing) vs
fine-grained (package scan history). For current use case, email inference is sufficient.

**Recommendation:** Email inference is adequate for Phase 1 monitoring. DHL API integration
is Phase 3+ work.

---

### GAP-AR02: AWB→Batch Linkage Not Automatic

**Gap:** When a new DHL arrival email is received, the system cannot automatically link
the AWB to an existing audit batch. Manual batch creation is required.

**Impact:** HIGH — limits automation in end-to-end flow. All AWB linkage is currently manual.

---

### GAP-AR03: Multi-Shipment Month Handling

**Gap:** In Jan 2026, 5+ DHL shipments arrived in the same period. The system processes
batches independently but there is no view of "how many shipments are in clearance simultaneously."

**Impact:** LOW — each batch is independent; simultaneous handling is not a problem.
But monitoring complexity grows linearly with active shipments.

---

## Gap Priority Summary

| Category | Gap ID | Severity | Quick Fix | Notes |
|----------|--------|----------|-----------|-------|
| Detection | D01 | HIGH | YES | Parse odprawacelna@dhl.com |
| Detection | D02 | HIGH | YES | Parse pl-import@fedex.com |
| Detection | D03 | HIGH | YES | Parse no-reply@acspedycja.pl filename |
| Detection | D04 | MEDIUM | YES | Keyword match on "płaci się" |
| Detection | D05 | HIGH | YES | Keyword match on "VAT Deferment" |
| Detection | D06 | MEDIUM | MEDIUM | FV invoice pattern match |
| Detection | D07 | LOW | YES | FCA keyword match |
| Timeline | T01 | HIGH | YES | Log on carrier email receipt |
| Timeline | T02 | MEDIUM | YES | Log on ACS PZC email receipt |
| Timeline | T03 | LOW | YES | Log on Ganther PZC email |
| Timeline | T04 | MEDIUM | YES | Log on FedEx cesja auto-ack |
| Timeline | T05 | LOW | MEDIUM | Log on delivery confirmation email |
| Actor | A01 | LOW | YES | Add michal@ to production config |
| Actor | A02 | LOW | YES | DHL ticket extraction regex |
| Actor | A03 | LOW | YES | Add kaushal@ to DO_NOT_TRIGGER |
| Compliance | C01 | HIGH | NO | Manual calendar entry required |
| Compliance | C02 | MEDIUM | MEDIUM | Invoice reconciliation register |
| Compliance | C03 | MEDIUM | NO | Manual pre-shipment checklist |
| Architecture | AR01 | MEDIUM | NO | Phase 3+ work |
| Architecture | AR02 | HIGH | MEDIUM | Email→batch AWB matching |
| Architecture | AR03 | LOW | NO | Cosmetic / dashboard feature |

---

*All gaps identified from read-only analysis of 12 months of email data.*
*No production changes proposed here — require explicit admin approval before implementation.*
