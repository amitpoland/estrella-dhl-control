# ONE_YEAR_SAD_ZC429_FLOW_ANALYSIS.md
# Estrella Jewels — SAD / ZC429 Flow Analysis
# Period: Jun 2024 – Apr 2026 | Carrier: DHL
# Generated: 2026-04-27

---

## Executive Summary

This document analyzes the SAD (Single Administrative Document) and ZC429 customs clearance
document flow for Estrella Jewels inbound DHL shipments. Key finding: ACS Spedycja sends
automated ZC429 AIS notifications from `no-reply@acspedycja.pl` with full MRN numbers.
9 MRN→AWB mappings have been confirmed. The VAT deferment lapse in Dec 2025 caused the only
confirmed SAD-related hold in the analysis period.

---

## 1. Document Flow Overview

### DHL SAD / ZC429 Chain

```
DHL arrives at Polish customs warehouse
    ↓
ACS Spedycja agent logs into WinSADMS
    ↓
ACS files SAD declaration with Polish customs (Urząd Celny)
    ↓
Customs accepts SAD → MRN assigned
    ↓
WinSADMS auto-sends ZC429 AIS notification:
    FROM: no-reply@acspedycja.pl
    TO: import@estrellajewels.eu
    CC: (varies)
    Subject: contains MRN
    Attachment: ZC429_<MRN>_1_PL.pdf
    ↓
Estrella downloads ZC429 PDF
    ↓
ZC429 provided to Ganther for PZC calculation
    ↓
PZC (Potwierdzenie Zgłoszenia Celnego) issued
    ↓
Goods released after duty payment
```

---

## 2. ZC429 / MRN Registry (9 confirmed mappings)

| AWB | MRN | Date | Source |
|-----|-----|------|--------|
| 4560229026 | DSK: 25PL44302D004MARU8 | ~Jun 2024 | Oldest DSK reference |
| 2264932003 | 25PL44302D00C46MR7 | Nov 2025 | AIS email confirmed |
| 5264550174 | 25PL44302D00CKTER2 | Nov 2025 | AIS email confirmed |
| 2064232951 | 25PL44302D00D755R5 | Nov 2025 | AIS email confirmed |
| 6561633783 | 25PL44302D00BPS8R4 | Nov/Dec 2025 | AIS email confirmed |
| 6883058851 | 25PL44302D00DW19R7 | Dec 2025 | AIS email confirmed |
| 2136263684 | 25PL44302D00E7LNR2 | Dec 2025 | AIS email confirmed |
| 1214569005 | 26PL44302D004TVCR0 | Mar 2026 | AIS email confirmed |
| 2824221912 | 26PL44302D005LJ4R0 | Mar 2026 | AIS email confirmed |
| (PZ batch) | 26PL44302D008N8OR0 | Apr 2026 | PZ system (EJL/26-27/039-044) |

### MRN Pattern Analysis

All confirmed MRNs follow Polish customs format:

```
26PL44302D005LJ4R0
└─┬─┘└──┬──┘└──┬─┘└┘
  │     │      │   └── Check digit
  │     │      └─────── Shipment identifier
  │     └────────────── Customs office code (44302D = Kraków Airport?)
  └──────────────────── Year + Country (26PL = 2026, Poland)
```

The customs office code `44302D` appears consistently — this is the processing office
for all Estrella DHL clearances, strongly suggesting all shipments clear through the same
customs jurisdiction.

---

## 3. AIS Automated Notification System

### Sender: `no-reply@acspedycja.pl`

This address sends automated notifications from WinSADMS (Polish customs software).

**Confirmed ZC429 email properties:**
- Subject format: contains MRN number
- Attachment: `ZC429_<MRN>_1_PL.pdf`
- TO: `import@estrellajewels.eu` (Tejal)
- Content: automated — no human authored text
- Timing: typically same day or next day after SAD accepted by customs

**CRITICAL gap identified in Task E:** `no-reply@acspedycja.pl` was NOT in the original
`TRUSTED_CLEARANCE_SENDERS` configuration. This means the ZC429 notification was arriving
but not being detected by cowork automation.

**Status:** Added to trusted senders in `CARRIER_CLEARANCE_RULES.md` (Task E output).

---

## 4. ZC429 Format in PZ System

The PZ processor uses ZC429 PDF for:
- MRN extraction (`zc429_mrn`)
- CIF total validation against invoices
- Duty amount A00 extraction
- Importer name verification
- Customs rate (different from NBP accounting rate)

**Known format gap:** ZC429 SAD exporter identity cannot always be parsed from goods
description format → produces `[VERIFY-GAP] SAD exporter identity could not be verified`
in corrections_log. This is structural (ZC429 doesn't always include supplier field).

---

## 5. VAT Deferment Gap — Dec 2025 (Confirmed SAD Impact)

### What happened

On AWB 6883058851 (Dec 2025), Ganther's clearance notification contained:

> "Estrella has no permission for VAT Deferment, it was ended recently."

**Impact:** Clearance held until VAT deferment status resolved. Duty 973 PLN.

**Background:** Polish importers can apply for VAT deferment permission (allowing VAT payment
after clearance rather than before). Estrella's deferment permission lapsed in Dec 2025.
Ganther caught this during the SAD filing stage.

**Resolution:** Not documented in available threads — assumed resolved by Jan 2026 when
clearance resumed normally.

### System gap

No automation currently exists to:
1. Detect VAT deferment warning in Ganther email
2. Alert `account@estrellajewels.eu` of impending VAT status issue
3. Track VAT deferment renewal dates

**Proposed trigger:** T-NEW (VAT_DEFERMENT_GAP): If Ganther email contains keywords
"VAT Deferment" / "VAT Odroczenie" / "brak pozwolenia" → alert immediately.

---

## 6. PZC (Potwierdzenie Zgłoszenia Celnego) Flow

PZC is the formal customs acceptance document issued after SAD is accepted.

**DHL flow:**
1. ACS receives SAD acceptance from customs
2. ACS sends PZC to Estrella (`import@estrellajewels.eu`)
3. Ganther simultaneously sends clearance notification
4. Estrella downloads PZC for accounting records

**FedEx flow:**
1. Ganther files SAD directly (no ACS intermediary)
2. FedEx issues DSK to Ganther after cesja completed
3. Ganther obtains PZC and sends clearance notification to Estrella

---

## 7. ACS Agent Assignment to SAD Tasks

Different ACS agents handle SAD filing at different times:

| Agent | Email | Period Active | Role |
|-------|-------|--------------|------|
| Michał Cieślak | michal@acspedycja.pl | Jun–Sep 2024 | SAD filing |
| Roman Kałużny | roman@acspedycja.pl | Aug 2025, Jan 2026 | Senior / supervision |
| Adrian Mielcarek | adrian@acspedycja.pl | Dec 2025 | SAD filing |
| Bartłomiej Bugaj | logistyka@acspedycja.pl | Nov 2025–Apr 2026 | SAD filing |
| Piotr Kubsik | piotr@acspedycja.pl | Jan–Apr 2026 | Primary SAD agent |

No single agent handles all SADs — automation must accept PZC/ZC429 from any of these 5 agents.

---

## 8. SAD Quality Observations

### Format variations

- **Normal:** Full goods description, CIF declared, importer/exporter fields complete
- **Partial:** Goods description format insufficient for qty-by-type verification → `[VERIFY-GAP]`
- **Exception:** EJL/25-26/951-953 (AWB 2136263684) — "Request for Custom Clearance Assistance"
  suggests a non-standard clearance situation; highest duty year (4,212 PLN)

### Rate discrepancy (by design)

ZC429 uses customs declaration exchange rate.
PZ processor uses NBP table exchange rate (accounting standard).
These rates legitimately differ — documented in `rate_note` field in audit.json.

---

## 9. Gaps in ZC429 Coverage

| Gap | Reason | Impact |
|-----|--------|--------|
| AWBs before Nov 2025 — MRN unknown | AIS notification history not fully preserved | LOW — old shipments |
| AWBs 6325915234, 9765416334 — MRN unknown | Numeric Zoho search limitation | LOW — AWBs confirmed via ACS sender |
| AWB 4560229026 — only DSK preserved, not full MRN | Old record format | LOW |
| FedEx AWBs — no ZC429 format (different document) | FedEx uses internal DSK via pl-import | N/A |

---

## 10. Automation Recommendations

1. **ZC429 detection:** Detect `no-reply@acspedycja.pl` → extract MRN from subject or
   attachment filename → store in `audit["zc429_mrn"]` → log `sad_uploaded` timeline event.

2. **MRN→AWB link:** When AWB known + MRN received, cross-reference to link ZC429 to batch.

3. **VAT deferment monitor:** Detect "VAT Deferment" / "odroczenie" in Ganther email body
   → fire VAT_DEFERMENT_GAP alert to `account@estrellajewels.eu`.

4. **SAD rate gap note:** Always preserve `rate_note` in audit — NBP vs customs rate diff is
   expected and must not trigger verification failure.

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
