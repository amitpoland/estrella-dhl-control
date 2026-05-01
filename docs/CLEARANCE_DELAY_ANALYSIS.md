# Clearance Delay Analysis
## Quantified Delays by Stage — Jan 27 – Apr 27, 2026
### Source: Email timestamps, 11 shipments

---

## Delay Classification

| Grade | Threshold | Meaning |
|-------|-----------|---------|
| ✅ OK | < 2h | Within normal automated response |
| ⚠️ WARN | 2h – 6h | Watch — may need attention |
| 🔴 DELAY | 6h – 24h | Actionable — follow-up needed |
| 🔴🔴 CRITICAL | > 24h | Blocking — escalation required |

---

## Stage 1: Cesja → ACS Clearance

The time from DHL sending cesja to ACS Spedycja until customs clearance is complete.
This is the **core SLA** — it measures how fast ACS processes the declaration.

| AWB | Cesja | Clearance Signal | Duration | Grade |
|-----|-------|-----------------|----------|-------|
| 8580992114 | 2026-02-13 05:36 | 2026-02-13 08:06 | **2h 30m** | ⚠️ WARN |
| 3109419880 | 2026-02-25 02:09 | 2026-02-25 04:17 | **2h 08m** | ⚠️ WARN |
| 1214569005 | 2026-03-03 03:24 | 2026-03-03 09:36 (AIS) | **6h 12m** | 🔴 DELAY |
| 2824221912 | 2026-03-12 03:55 | 2026-03-12 09:36 (AIS) | **5h 41m** | ⚠️ WARN |
| 3369800350 | 2026-03-17 04:46 | 2026-03-18 03:38 | **22h 52m** | 🔴 DELAY |
| 8523214840 | 2026-04-01 06:45 | 2026-04-02 06:13 | **23h 28m** | 🔴 DELAY |
| 3283625844 | 2026-04-14 03:57 | 2026-04-15 08:24 | **28h 26m** | 🔴🔴 CRITICAL |

**Summary:**
- Best case: 2h 08m (AWB 3109419880, Feb)
- Worst case: 28h 26m (AWB 3283625844, Apr)
- Median: ~6h
- **5 of 7 measured clearances took >6h** (DELAY or worse)
- Trend: Getting slower through the quarter (Feb avg 2h 19m → Apr avg 25h 27m)

**Root cause candidates:**
- ACS Spedycja processes overnight (Polish working hours ~08:00–16:00 CET)
- Cesja often arrives early morning (02:00–07:00 UTC = 03:00–08:00 CET) — before office opens
- Larger/more complex shipments may require more customs documentation review
- April shipments may have coincided with higher seasonal volume or holiday periods

---

## Stage 2: ACS PZC → Ganther Relay to DHL

The time from ACS sending PZC to DHL until Ganther sends their own separate PZC release
instruction to DHL.

**Critical finding:** In 2 of 4 measured cases, Ganther sent the PZC release to DHL
**BEFORE** ACS sent the formal PZC email. This means Ganther monitors the AIS ZC429
notification directly and acts on it immediately, without waiting for ACS's email.

| AWB | ACS PZC (email) | Ganther PZC to DHL | Duration | Grade | Note |
|-----|----------------|-------------------|----------|-------|------|
| 5378819972 | 2026-01-27 06:52 | 2026-01-27 07:46 | **0h 54m** | ✅ OK | — |
| 8580992114 | 2026-02-13 08:06 | 2026-02-13 13:47 | **5h 41m** | ⚠️ WARN | — |
| 3109419880 | 2026-02-25 04:17 | 2026-02-25 09:54 | **5h 37m** | ⚠️ WARN | — |
| 1214569005 | 2026-03-04 01:37 | 2026-03-03 15:33 | **-10h 4m** | — | Ganther acted on AIS (6h after AIS) |
| 2824221912 | 2026-03-13 07:09 | 2026-03-12 15:13 | **-15h 56m** | — | Ganther acted on AIS (5h 37m after AIS) |
| 6876258325 | 2026-04-07 05:22 | 2026-04-07 11:06 | **5h 44m** | ⚠️ WARN | — |

**Key insight:** The real relay lag from clearance to DHL release is:
- From AIS ZC429 to Ganther PZC to DHL: **5h 37m – 6h 11m** (for AWBs with AIS data)
- From ACS PZC email to Ganther PZC to DHL: **0h 54m – 5h 44m** (for AWBs without AIS)

**Pattern:** Ganther does NOT relay immediately upon receiving ACS email. There is a
consistent 5–6h gap. This may be intentional (Ganther checks payment status, confirms
with DHL, prepares their own release email) or operational (Ganther processes in batches).

---

## Stage 3: Ganther Duty Request → Estrella Payment Acknowledgment

The time from Ganther sending the duty payment request to account@estrellajewels.eu until
Ganther confirms payment received ("dzieki, płaci się").

| AWB | Duty Request | Payment Ack | Duration | Grade |
|-----|-------------|------------|----------|-------|
| 6876258325 | 2026-04-07 11:08 | 2026-04-07 11:15 | **0h 06m** | ✅ OK |
| 3283625844 | 2026-04-15 10:07 | 2026-04-15 17:29 | **7h 22m** | 🔴 DELAY |
| 3369800350 | (no duty email found) | 2026-03-18 04:59 | — | — |
| **2824221912** | **2026-03-13 10:26** | **2026-04-09 17:15** | **🔴🔴 27 DAYS** | **CRITICAL** |

**Critical case — AWB 2824221912:**
The duty notice was sent Mar 13 to `amit@estrellajewels.eu` instead of `account@estrellajewels.eu`.
No response for 28 days. Amit sent an "URGENT CUSTOMS CLEARANCE" email on Apr 9.
Ganther replied that the shipment was already "delivered to consignee" — meaning DHL
released the shipment before duty was formally paid/confirmed.

**Observation for AWB 6876258325:** 6-minute payment ack is not realistic as a wire transfer.
Ganther confirmed "dzieki, placi sie" almost immediately — this may mean Tejal (accounts)
sent payment confirmation via phone/WhatsApp and Ganther acknowledged by email. The bank
transfer would have settled later.

---

## Stage 4: Broker Appointment Latency (where applicable)

For AWB 3283625844 (the only shipment with clear Estrella broker appointment email):

| Event | Time |
|-------|------|
| Estrella sends broker appointment to DHL | 2026-04-13 11:47 UTC |
| DHL sends cesja to ACS | 2026-04-14 03:57 UTC |
| Gap: broker letter → cesja | **16h 10m** ⚠️ WARN |

This gap represents DHL's internal processing time for the broker appointment. DHL processes
it overnight (typical Polish business hours pattern).

---

## Aggregate Delay Heatmap

```
Stage                          Jan  Feb  Mar  Apr  Trend
─────────────────────────────────────────────────────────
Cesja → Clearance               N/A  WARN WARN CRIT  ↗ WORSENING
ACS PZC → Ganther relay         OK   WARN WARN WARN  → STABLE
Duty Request → Payment Ack      N/A  N/A  CRIT OK    — INCONSISTENT
Overall Cycle Time              Fast Fast Slow Slow  ↗ WORSENING
```

---

## The 28-Day Case: Full Post-Mortem

**Shipment:** AWB 2824221912 (T#1WA2603100000499)
**Impact:** 28-day payment delay for 1261 PLN duty

**Timeline of failure:**
```
Mar 12 03:55  DHL sends cesja → ACS begins work
Mar 12 09:36  AIS confirms clearance (ZC429 received)
Mar 12 15:13  Ganther sends PZC to DHL → shipment released
Mar 13 10:26  Ganther sends duty notice TO: amit@estrellajewels.eu CC: account@estrellajewels.eu
              ↑ THIS IS THE FAILURE POINT
              The email went to Amit's personal inbox, not the accounts inbox (Tejal).
              Amit was presumably traveling or not actively monitoring this thread.
              No follow-up reminder was sent.
              No system alert existed.

[28 DAYS PASS]

Apr 09 16:17  Amit emails Ganther: "URGENT CUSTOMS CLEARANCE"
Apr 09 17:15  Ganther: "matter is closed, delivered to consignee"
```

**What prevented detection:**
1. Duty notice went to `amit@estrellajewels.eu` instead of `account@estrellajewels.eu`
2. No automated follow-up after 72h without payment
3. No system visibility into pending duty payments
4. Shipment was released before payment (DHL released on PZC, duty is separate)

**Financial exposure:** Estrella received the goods without confirmed duty payment. Duty
was eventually paid (Ganther confirmed closure), but the exact payment date is unknown.
This creates an audit gap where duty could theoretically go unpaid.

---

## SLA Benchmarks (Derived from Observed Data)

| Stage | Best Case | Typical | Maximum Observed | Recommended SLA |
|-------|----------|---------|-----------------|-----------------|
| DHL Notification → first email | <1h | 0–2h | 24h | 4h |
| Cesja → ACS clearance | 2h 08m | 6–24h | 28h 26m | 24h |
| ACS PZC → Ganther relay | 0h 54m | 1–6h | 6h | 8h |
| Ganther duty notice → Estrella pays | 6 min | 1–8h | 28 days | 3 business days |
| Ganther sends invoice | 1 day | 5–10 days | ~14 days | 14 days |

---

## Actionable Thresholds for Automation

Based on observed data, these thresholds should trigger escalation:

```python
THRESHOLDS = {
    # If no clearance signal 24h after cesja → DHL follow-up to ACS
    "cesja_to_clearance_warn_h": 6,
    "cesja_to_clearance_alert_h": 24,

    # If no Ganther relay 8h after AIS/PZC → check with Ganther
    "pzc_to_ganther_relay_h": 8,

    # If no payment ack 72h after duty notice → escalate to Amit
    "duty_to_payment_warn_h": 72,

    # If no payment ack 7 days after duty notice → URGENT flag
    "duty_to_payment_critical_h": 168,
}
```
