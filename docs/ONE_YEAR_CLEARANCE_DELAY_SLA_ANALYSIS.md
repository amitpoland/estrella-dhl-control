# ONE_YEAR_CLEARANCE_DELAY_SLA_ANALYSIS.md
# Estrella Jewels — Clearance Delay & SLA Analysis (1-Year)
# Period: Jun 2024 – Apr 2026 | DHL + FedEx
# Generated: 2026-04-27

---

## Executive Summary

This document analyzes customs clearance delays observed over 12+ months. Two confirmed delay
events are documented: (1) AWB 6883058851 (Dec 2025) delayed by VAT deferment lapse, and
(2) AWB 2824221912 (Mar 2026) delayed 28 days by duty routing gap. Standard DHL clearance
runs 3–5 days; FedEx 6–9 days. Duty routing gap is now resolved (Apr 2026). Three structural
risk factors remain: FedEx manual cesja, VAT deferment renewal monitoring, and no systematic
SLA tracking in the audit system.

---

## 1. SLA Benchmarks (Evidence-Based)

### DHL Inbound — Standard Clearance

| Stage | Typical Duration | Evidence |
|-------|-----------------|---------|
| Day 0: DHL notification | — | arrival email |
| Day 0–1: ACS files SAD | 0–1 days | ZC429 AIS notification timing |
| Day 1–2: ZC429 issued / PZC sent | 1–2 days | ACS PZC email timing |
| Day 2–3: Duty notice from Ganther | 1–2 days | Ganther email timing |
| Day 3–4: Estrella pays duty | 1 day | "płaci się" timing |
| Day 4–5: Cargo released | 1 day | Delivery arrangement email |
| **Total: 3–5 days** | | Confirmed across 30+ AWBs |

### FedEx Inbound — Standard Clearance

| Stage | Typical Duration | Evidence |
|-------|-----------------|---------|
| Day 0: FedEx notification + cesja form | — | pl-import@fedex.com email |
| Day 0–4: Estrella submits cesja | 0–4 days | **Human step — highly variable** |
| Day 4: FedEx auto-ack | immediate | Auto-reply |
| Day 5: DSK issued to Ganther | next day | ganther.com.pl email |
| Day 5–6: SAD filed + PZC | 1 day | Ganther clearance email |
| Day 6–9: Duty + release + delivery | 3 days | AWB 887467026597 timeline |
| **Total: 6–9 days** | | Based on AWB 887467026597 |

---

## 2. Confirmed Delay Events

### Delay Event 1: AWB 6883058851 — Dec 2025

**Delay type:** Administrative hold — VAT deferment lapse
**Standard duration:** 3–5 days
**Actual duration:** Extended (exact days not reconstructed from available thread)
**Duty:** 973 PLN

**Root cause:** Estrella's VAT deferment permission (odroczenie VAT) had lapsed recently
before Dec 2025. Ganther caught this during SAD filing and notified Estrella:
> "Estrella has no permission for VAT Deferment, it was ended recently."

**Impact:** Clearance held until VAT deferment status resolved. This is a hard customs block —
goods cannot be cleared without valid VAT deferment authorization.

**Resolution:** Not documented in available threads — assumed resolved without further delay.

**Recurrence risk:** HIGH — VAT deferment is a time-limited permission requiring periodic
renewal. No alert system currently exists for renewal tracking.

### Delay Event 2: AWB 2824221912 — Mar 2026

**Delay type:** Duty routing failure — payment not made
**Standard duration:** 3–5 days
**Actual duration:** 28 days
**Duty:** 1,261 PLN

**Root cause:** Ganther sent duty notice exclusively to `amit@estrellajewels.eu`. The
`account@estrellajewels.eu` mailbox was not notified. Duty payment was never triggered.
Cargo sat in DHL warehouse for 28 days before the situation was discovered and resolved.

**Financial impact:**
- DHL storage fees likely accrued (standard DHL free storage: 5 days; fee applicable days 6–28)
- Stock replenishment delayed ~25 days
- 1,261 PLN duty paid late (no penalty confirmed but late payment risk exists)

**Resolution:** Duty eventually paid. By Apr 2026 Ganther normalized routing to `account@`.

**Recurrence risk:** LOW — routing has normalized. Monitor to confirm stability.

### Delay Risk Event: FedEx AWB 887467026597 — Jan 2026

**Delay type:** Cesja submission gap (near-miss)
**Standard FedEx duration:** 6–9 days
**Actual duration:** 9 days (at the upper edge of standard)
**DSK delay component:** 3 days (cesja submitted Day 4 vs ideal Day 1)

**Root cause:** Cesja form not submitted promptly by `import@estrellajewels.eu`.
Ganther followed up on Day 3: "Have you asked FedEx for Cession?"

**Impact:** 3-day delay in DSK issuance. Ganther followed up — if Ganther had not,
delay could have extended to 10–15+ days.

**Recurrence risk:** MEDIUM — FedEx is now confirmed. Every future FedEx shipment requires
manual cesja submission. Probability of missing it without automation is significant.

---

## 3. Delay Pattern Analysis

### Delay by Root Cause

| Cause | AWBs Affected | Frequency | Max Delay | Risk Level |
|-------|--------------|-----------|-----------|-----------|
| Duty routing gap | 2824221912 | 1 (confirmed severe) | 28 days | HIGH → self-corrected |
| VAT deferment lapse | 6883058851 | 1 (confirmed) | Unknown | HIGH → monitor renewal |
| FedEx cesja delay | 887467026597 | 1 (near-miss) | 3 extra days | MEDIUM → automation opportunity |
| Domain confusion (routing) | 8580992114 | 1 (minor) | Minor | LOW |

### Delay Distribution (rough estimate)

From 35+ DHL AWBs observed:
- **~33 AWBs:** Standard 3–5 day clearance (no evidence of delay)
- **1 AWB:** VAT deferment hold (Dec 2025) — duration uncertain
- **1 AWB:** 28-day delay (Mar 2026) — confirmed

**Delay rate:** ~2/35 = ~6% of confirmed DHL shipments experienced notable delays.

---

## 4. SLA Monitoring Gap

**Current state:** No SLA tracking exists in the audit system. There is no mechanism to:
1. Record `clearance_start` (DHL arrival date)
2. Record `clearance_end` (cargo released date)
3. Compute clearance duration per shipment
4. Alert if duration exceeds 5 days (DHL) or 9 days (FedEx)

**Trigger T2 (DUTY_PAYMENT_PENDING)** exists in cowork_coordinator.py and fires when
duty notice is received but payment not confirmed. This is a partial SLA mechanism but
doesn't cover the full clearance window.

---

## 5. Missing SLA Events in Timeline

For complete SLA tracking, these timeline events are needed:

| Event | Trigger | Current Status |
|-------|---------|---------------|
| `carrier_arrived` | DHL/FedEx notification email received | NOT IMPLEMENTED |
| `sad_filed` | ZC429 AIS notification from ACS | NOT IMPLEMENTED |
| `dsk_received` | ACS issues DSK to Ganther (DHL) or FedEx issues DSK (FedEx) | NOT IMPLEMENTED |
| `pzc_received` | Ganther sends PZC to Estrella | NOT IMPLEMENTED |
| `duty_notice_received` | Ganther sends duty invoice | PARTIALLY (duty_notice_received_at exists) |
| `cesja_submitted` | Estrella submits cesja to FedEx | NOT IMPLEMENTED |
| `duty_paid` | "płaci się" from Ganther | PARTIALLY (duty_paid_signal_at exists) |
| `cargo_released` | Delivery confirmation | NOT IMPLEMENTED |

The existing timeline has: `batch_created`, `invoice_uploaded`, `sad_uploaded`, `pz_generated`.
These are PZ system events, not clearance milestones.

---

## 6. VAT Deferment — Renewal Risk

### What it is

Polish VAT odroczenie (deferment) is a permission granted by customs to defer VAT payment
on imports. Without it, VAT must be paid before goods are released.

### Current status

The Dec 2025 lapse confirms this permission had expired. It was presumably renewed afterward
(clearances resumed normally in Jan 2026).

### Risk

There is no alert system for VAT deferment renewal deadlines. The next expiry could cause
another clearance hold — potentially on a high-value shipment.

### Proposed detection

Ganther email keywords that indicate VAT deferment issue:
- "VAT Deferment" / "odroczenie VAT"
- "brak pozwolenia" (no permission)
- "pozwolenie wygasło" (permission expired)
- "VAT zostanie zapłacony przed zwolnieniem" (VAT to be paid before release)

Trigger: VAT_DEFERMENT_GAP → immediate alert to `account@estrellajewels.eu` and `amit@`.

---

## 7. DHL Storage Fee Risk

DHL standard free storage at customs warehouse: typically 5 business days.
After 5 days: storage fees apply (rate unknown — varies by shipment weight/value).

**AWB 2824221912 impact:** 28-day hold. Storage fee exposure for days 6–28 = 22 billable days.
Exact fee not available in email threads. Likely hundreds of PLN in additional costs.

**Proposed guard:** If DHL arrival detected and duty not paid within 4 days →
alert `account@estrellajewels.eu` urgently: "Storage fees begin tomorrow."

---

## 8. Recommendations

### Immediate (no code change)

1. Track VAT deferment renewal date in accounting calendar. Set reminder 30 days before expiry.
2. Confirm `account@estrellajewels.eu` is canonical duty target — monitor Ganther routing
   through Apr/May 2026 to confirm normalization holds.

### Short-term (code changes, require approval)

3. Implement carrier arrival detection: `odprawacelna@dhl.com` → log `carrier_arrived` event.
4. Implement FedEx cesja alert (T3): 24h window from `pl-import@fedex.com` email.
5. Implement VAT deferment keyword detection → T-NEW: VAT_DEFERMENT_GAP.
6. Add `clearance_start` and `clearance_end` to audit fields for SLA computation.

### Medium-term

7. Full clearance SLA dashboard: per-AWB duration tracking → flag outliers (>5 days DHL,
   >9 days FedEx) → monthly SLA report.
8. DHL storage fee alert: if clearance duration > 4 days → warn before storage fees begin.

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
