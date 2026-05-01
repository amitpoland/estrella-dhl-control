# ONE_YEAR_TRACKING_FLOW_ANALYSIS.md
# Estrella Jewels — Shipment Tracking Flow Analysis (1-Year)
# Period: Jun 2024 – Apr 2026 | DHL + FedEx
# Generated: 2026-04-27

---

## Executive Summary

This document analyzes how inbound shipment tracking data flows from carriers to Estrella
and into the cowork automation system. Key findings: DHL tracking uses a ticket-based system
`[T#1WA{date}{seq}]` for internal routing; FedEx tracking is managed via `pl-import@fedex.com`
milestones; the system currently relies on email-inferred tracking rather than direct API calls;
and warehouse arrival detection is critical for the DSK missing trigger (T1).

---

## 1. DHL Tracking Architecture

### Email-Based Tracking (Primary)

DHL tracking for Estrella arrives exclusively via email from `odprawacelna@dhl.com`.
No confirmed use of DHL MyDHL+ API or webhook in the current workflow.

**Email contains:**
- AWB number
- Shipment weight and declared value
- Arrival date
- Customs status
- Cesja forwarding status

**DHL Ticket System:**

Every DHL clearance email has an internal ticket reference:

```
Format: [T#1WA{YYYYMMDD}{SEQ}]
Example: [T#1WA20260315001]
```

This ticket number:
- Appears in email subjects for threading
- Allows DHL to track internal handling
- Is NOT an AWB or MRN — it's DHL's internal case ID
- Useful for reconstructing email threads per shipment

### DHL Tracking Milestones (observed from email content)

| Milestone | Email trigger | From |
|-----------|--------------|------|
| Arrival at customs warehouse | Initial notification | odprawacelna@dhl.com |
| Cesja forwarded to ACS | Cesja Fwd email | odprawacelna@dhl.com |
| SAD accepted | ZC429 AIS notification | no-reply@acspedycja.pl |
| PZC issued | PZC + duty notice | Any ACS agent |
| Duty notice | Invoice email | ganther.com.pl |
| Duty paid | "płaci się" | ganther.com.pl → ACS |
| Cargo released / pickup scheduled | Delivery email | ganther.com.pl or DHL |

### Warehouse Arrival Detection (for T1 trigger)

The T1 (DSK_MISSING) trigger requires `arrived_warehouse=True` in `audit["tracking"]`.

**How to detect warehouse arrival from email:**
- DHL notification from `odprawacelna@dhl.com` → `arrived_warehouse = True`
- ZC429 AIS notification from `no-reply@acspedycja.pl` → confirms customs filing started

Currently the PZ system does not automatically extract this from email.
Implementation note: parse DHL arrival email → set `audit["tracking"]["arrived_warehouse"] = True`
→ start DSK missing countdown.

---

## 2. FedEx Tracking Architecture

### Email-Based Tracking (Primary)

FedEx tracking for inbound shipments arrives via `pl-import@fedex.com`.

**FedEx AWB 887467026597 — full milestone evidence:**

| Day | Event | Email Source |
|-----|-------|-------------|
| 0 | FedEx notification received | pl-import@fedex.com |
| 0 | Cesja form sent to Amit/Roman/Ganther | pl-import@fedex.com |
| 3 | Ganther follow-up on cesja | ganther.com.pl |
| 4 | Cesja submitted by Estrella | import@estrellajewels.eu → pl-import@fedex.com |
| 4 | FedEx auto-acknowledges cesja | pl-import@fedex.com auto-reply |
| 5 | DSK issued by FedEx to Ganther | pl-import@fedex.com → ganther.com.pl |
| 5 | Ganther: "przesyłka w odprawie" | ganther.com.pl → import@ |
| 6 | PZC sent + clearance notification | ganther.com.pl → amit@ |
| 9 | Warehouse address provided by FedEx | pl-import@fedex.com |
| 9 | Delivery arranged | Ganther + FedEx |

### FedEx Tracking Key Phrases (Polish)

| Phrase | Translation | Stage |
|--------|------------|-------|
| przesyłka w odprawie | shipment in clearance | SAD filed — waiting for customs |
| DSK do Ganther | DSK issued to Ganther | Clearance authorized |
| adres magazynu | warehouse address | Ready for pickup |

---

## 3. Tracking in the PZ System — Current State

### Audit Fields

```python
audit["tracking"] = {
    "arrived_warehouse": bool | None,   # DHL arrival confirmed
    "dsk_received": bool | None,        # DSK/cesja issued to Ganther
    "pzc_issued": bool | None,          # PZC issued by customs
    "duty_paid": bool | None,           # Duty payment confirmed
    "released": bool | None,            # Cargo released
}
```

### Fallback Function: `_dhl_pending_fallback()`

When DHL API is not available, the tracking service returns:

```python
{
    "available": False,
    "source": "email_inferred",  # or "api_pending"
    "status": "pending",
    "tracking_url": "https://www.dhl.com/pl-en/home/tracking.html?tracking-id=<AWB>"
}
```

This was validated in production readiness check 6 (all 6 checks passed).

**Design principle:** No external API dependency for tracking fallback. Email-inferred tracking
is the production mode until DHL API integration is implemented.

---

## 4. Self-Pickup Events

One confirmed case of Amit (owner) doing self-pickup from DHL warehouse:

**AWB 5378819972 (Jan 2026):** Duty 1,622 PLN. Amit collected the shipment personally
from the DHL warehouse rather than arranging standard delivery.

**Automation note:** Self-pickup does not change the clearance flow — duty must still be paid
and PZC obtained. The delivery stage simply becomes owner-pickup rather than courier delivery.

---

## 5. Europe Simpleks Pickup Events

Confirmed for AWB 3023090884 (Aug 2025):

Jigar Purohit (`jigar.p@simplex-hurtownia.pl`) arranged pickup from DHL warehouse on behalf
of Estrella. Duty invoice was forwarded to `accounts@gjlindia.com` (GJL India) for that shipment.

This suggests Europe Simpleks may act as Estrella's Poland-side logistics partner for certain
shipments (pickup, local transport). This is not standard — most shipments are DHL-delivered.

---

## 6. Clearance Speed Reference

### DHL (Evidence-Based)

| Category | Duration | Observed Cases |
|----------|----------|---------------|
| Standard | 3–5 days | Majority of 35+ AWBs |
| Delayed (single issue) | 6–14 days | AWB 6883058851 (VAT deferment) |
| Severely delayed | >14 days | AWB 2824221912 (28 days — duty routing gap) |

### FedEx (Evidence-Based)

| Category | Duration | Notes |
|----------|----------|-------|
| Standard | 6–9 days | AWB 887467026597 baseline |
| With FCA complication | 7–11 days | Additional transport invoice required |

---

## 7. Tracking Data Quality Gaps

| Gap | Impact | Notes |
|-----|--------|-------|
| Warehouse arrival date rarely explicit in current audit | HIGH — T1 trigger depends on it | Need email parsing to extract |
| DSK issue date not logged | MEDIUM — T1 can't compute DSK wait time | Need to parse ACS PZC email date |
| PZC issue date not logged | LOW | Could be extracted from ACS email |
| Cargo release date not logged | LOW | Could be extracted from Ganther email |
| DHL ticket number not stored | LOW | Useful for thread reconstruction |

---

## 8. Automation Recommendations

1. **Warehouse arrival logging:** Parse `odprawacelna@dhl.com` email → set `arrived_warehouse=True`
   → log `dhl_arrived` timeline event with AWB and ticket number.

2. **DSK detection:** Parse ACS PZC email → set `dsk_received=True` → log `dsk_received`
   timeline event → stop T1 clock.

3. **Duty paid detection:** Parse "płaci się" from `ganther.com.pl` → set `duty_paid=True`
   → log `duty_paid_signal_at` → stop T2 clock.

4. **FedEx cesja submission:** Detect `pl-import@fedex.com` arrival → prompt `import@`
   within 24h → log `cesja_submitted` when FedEx auto-ack received.

5. **Clearance duration tracking:** Store `clearance_start` (DHL arrival) and `clearance_end`
   (cargo released) → compute clearance days → flag if > 5 days DHL or > 9 days FedEx.

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
