# FEDEX_ONE_YEAR_WORKFLOW_ANALYSIS.md
# Estrella Jewels — FedEx One-Year Workflow Analysis
# Period: Aug 2025 – Apr 2026 (FedEx-active period)
# Generated: 2026-04-27

---

## Executive Summary

FedEx began appearing in Estrella's inbound shipment record from Aug 2025. Three inbound
AWBs confirmed, plus three outbound export AWBs. The FedEx clearance chain is fundamentally
different from DHL: it is a 2-actor chain (FedEx→Ganther) rather than 3-actor (DHL→ACS→Ganther),
and critically, the cesja/DSK process is importer-initiated rather than ACS-handled. The Aug 2025
FedEx AWBs reveal a billing error (recipient charged for duties). The Jan 2026 FedEx AWB is
fully documented and took 9 days from arrival to delivery.

---

## 1. FedEx Actor Map

| Actor | Email | Role |
|-------|-------|------|
| FedEx Poland Import | pl-import@fedex.com | Customs clearance, cesja handler |
| Kamil Romanowski | Named in pl-import signature | Cesja handler |
| FedEx Poland Billing | poland@fedex.com | Billing corrections |
| FedEx Ops Support | DataRWA@fedex.com | Ops support (Grzegorz Sładek) |
| FedEx Sales | Zaneta.Nagat@fedex.com | Sales — not clearance |
| Ganther (broker) | ganther.com.pl | Handles ALL FedEx clearance |
| ACS Spedycja (Roman) | roman@acspedycja.pl | CC'd on cesja thread — not clearance actor |

**Key finding:** ACS Spedycja is NOT in the FedEx clearance loop. Ganther handles the full
FedEx clearance directly. Roman Kałużny (ACS) appearing as CC on the cesja thread is
informational only — not a clearance step.

---

## 2. FedEx vs DHL Comparison

| Attribute | DHL | FedEx |
|-----------|-----|-------|
| Clearance chain | DHL → ACS → Ganther → Estrella | FedEx → Ganther → Estrella |
| Cesja initiator | DHL (automatic, sent to ACS) | **Estrella (manual, to pl-import@fedex.com)** |
| Clearance time | 3–5 days standard | 6–9 days standard |
| DSK issuer | ACS Spedycja | FedEx Poland (pl-import) |
| ZC429 / AIS notification | no-reply@acspedycja.pl | Not applicable (no ACS involvement) |
| Main bottleneck | Duty routing gap | Cesja submission delay |
| Broker | Ganther | Ganther (same broker) |

---

## 3. FedEx Inbound AWB Registry (3 Confirmed)

### AWB 887467026597 — Jan–Feb 2026 (FULLY DOCUMENTED)

**Full timeline:**

| Day | Event | Detail |
|-----|-------|--------|
| 0 | FedEx notification | From pl-import@fedex.com |
| 0 | Cesja form sent | FedEx → Amit / Roman / Ganther |
| 3 | Ganther follow-up | "Have you asked FedEx for Cession of rights?" |
| 4 | Cesja submitted | import@estrellajewels.eu → pl-import@fedex.com |
| 4 | FedEx auto-ack | pl-import@fedex.com auto-reply |
| 5 | DSK issued | FedEx → Ganther |
| 5 | Ganther in clearance | "przesyłka w odprawie" |
| 6 | PZC + clearance notice | Ganther → Amit |
| 9 | Warehouse address | FedEx → Ganther |
| 9 | Delivery arranged | — |

**Total: 9 days from arrival to delivery**

**DSK gap:** 3-day gap between cesja form sent (Day 0) and cesja submission (Day 4).
Ganther had to follow up. Without the follow-up, this could have extended further.

**FCA complication:** Invoice used FCA (Free Carrier) incoterms. This required Ganther to
request the transport invoice to compute correct CIF value. Added approximately 1 day.

### AWB 882994160903 — Aug 2025 (Billing Dispute)

**What happened:** FedEx shipped a return or special shipment where the billing mode was
set to "recipient pays" for customs and duties. The recipient (Estrella's customer) was
unexpectedly charged for duties.

**Resolution:** Required manual correction via `poland@fedex.com`. Billing corrected.

**Root cause:** When creating FedEx outbound shipments in shipment setup, the "duty/tax
billing" setting was left at "recipient" rather than "sender."

**Proposed guard:** Always verify FedEx duty billing mode = "sender pays" before confirming
shipment creation.

### AWB 882994338403 — Aug 2025 (Partial Thread)

Details partial — customs issue confirmed but specifics not available in searched threads.
Likely parallel to AWB 882994160903 (same month, similar AWB prefix pattern).

---

## 4. FedEx Outbound AWBs (Export from Poland) — 3 Confirmed

| AWB | MRN | Destination | Notes |
|-----|-----|-------------|-------|
| 888681132638 | 26PL4450100018RAB0 | Unknown | IE599 / IE529 export clearance confirmed |
| 885967226148 | — | China (Guangzhou) | Customer delivery |
| 883559085518 | — | Norway | Customer delivery |

**Export note:** AWB 888681132638 has an MRN, indicating Polish customs export declaration
was filed (IE529 = export arrival at customs; IE599 = export released). This is a formal
export, not a simple EU parcel.

---

## 5. FedEx Cesja Mechanism — Detail

### The Cesja Form

FedEx Poland provides a standard cesja (cession of rights) form that must be signed by the
importer (Estrella) and submitted to `pl-import@fedex.com`.

**Content of cesja form:**
- Importer identification (Estrella company details)
- AWB number
- Signature and stamp of authorized Estrella representative
- Authorization for Ganther to act as customs representative

**Submission process:**
1. FedEx sends cesja form to Estrella (and CC Ganther) on Day 0
2. Estrella signs and scans form
3. Estrella emails signed form to `pl-import@fedex.com`
4. FedEx sends auto-acknowledgment
5. FedEx issues DSK to Ganther (typically next business day)

**Why this is different from DHL:** DHL sends the cesja directly to ACS (the agent) who
processes it on Estrella's behalf. FedEx requires the IMPORTER to submit it directly.

### Risk

If `import@estrellajewels.eu` (Tejal) misses the FedEx notification email, the cesja is
not submitted, DSK is not issued, and clearance is blocked until Ganther follows up.

For AWB 887467026597, Ganther followed up on Day 3. This is the best-case scenario — Ganther
was watching the status. If Ganther had not followed up, the delay could have been much longer.

---

## 6. FedEx Clearance Timing vs DHL

```
DHL Standard Timeline:
Day 0:  DHL arrival notification → ACS receives cesja Fwd
Day 1:  ACS files SAD → ZC429 issued (MRN assigned)
Day 2:  ACS sends PZC + duty notice to Estrella
Day 3:  Estrella pays duty → "płaci się" to ACS
Day 4:  Cargo released → delivery arranged
Day 5:  Delivery

FedEx Standard Timeline:
Day 0:  FedEx notification → cesja form sent
Day 0-3: WAIT for Estrella to submit cesja ← HUMAN STEP
Day 4:  Cesja submitted → FedEx auto-ack
Day 5:  DSK issued → Ganther begins clearance
Day 5:  "przesyłka w odprawie" (in clearance)
Day 6:  PZC issued + clearance notification
Day 9:  Warehouse address → delivery arranged
```

The FedEx baseline (6–9 days) vs DHL baseline (3–5 days): the primary driver of the longer
FedEx timeline is the manual cesja submission requirement (adds 3–5 days vs ACS-automated DHL).

---

## 7. FedEx Invoice Incoterms Impact

**FCA (Free Carrier) terms:**
- Ganther needs transport invoice to compute CIF correctly
- Common when Indian shipper uses FCA rather than CIF/DAP/DDP

**CIF/DAP/DDP terms:**
- Standard — no additional documents needed
- Ganther can compute CIF directly from invoice

**Detection:** Parse Ganther email for "FCA" → flag as FCA_COMPLICATION → prompt import@
for transport invoice immediately rather than waiting for Ganther's request.

---

## 8. Automation Recommendations for FedEx

1. **Cesja submission alert (T3):** Detect `pl-import@fedex.com` email →
   if no cesja submission confirmation within 24h → alert `import@estrellajewels.eu`:
   "FedEx shipment AWB <number> requires cesja submission to pl-import@fedex.com."

2. **Cesja timeline logging:** Log `cesja_submitted` event when FedEx auto-ack received.
   Log `dsk_received` when Ganther says "przesyłka w odprawie."

3. **FCA flag:** Detect "FCA" in Ganther email → log `fca_complication = True` →
   alert import@ for transport invoice before Ganther asks.

4. **FedEx billing guard:** When creating FedEx shipments, always confirm duty billing =
   "sender pays" before submission (cannot automate — manual checklist).

5. **FedEx vs DHL SLA:** FedEx SLA = 9 days; DHL SLA = 5 days. Apply different thresholds
   when computing clearance delay alerts. Use `audit["carrier"]` to select threshold.

6. **DO NOT TRIGGER on:** `DataRWA@fedex.com` (ops), `Zaneta.Nagat@fedex.com` (sales),
   `poland@fedex.com` (billing corrections — manual process). Only `pl-import@fedex.com`
   triggers clearance events.

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
