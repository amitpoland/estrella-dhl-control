# Shipment Lifecycle Timeline
## 3-Layer Unified Timeline — All 11 Shipments
### Jan 27 – Apr 27, 2026 | Source: Email + System audit

---

## Data Sources per Layer

| Layer | Source | Status |
|-------|--------|--------|
| `[TRACKING]` | DHL Tracking API | ⛔ API pending — not active. Tracking events not available. |
| `[EMAIL]` | Zoho Mail (info/import/account@estrellajewels.eu) | ✅ Full data — 11 shipments, all key events |
| `[SYSTEM]` | audit.json files (15 batches in storage) | ⚠️ Partial — No AWB links, no clearance events. PZ docs generated only. |

**Note on SYSTEM layer:** The 15 audit batches in storage contain no AWB numbers, no timeline events, and no clearance workflow events (clearance_status, dsk_received, etc.). All have doc_no "PZ 26-27/039-044" or empty. The system PZ processor has been used for document generation, but the clearance workflow (cowork_coordinator, DHL reply, agency email) has not been deployed in production. System events therefore cannot be correlated to email shipments.

---

## Notation

```
[TRACKING]  = DHL carrier event (not available — API pending)
[EMAIL]     = Email event observed in Zoho Mail
[SYSTEM]    = System event from audit.json timeline
[INFERRED]  = Derived from context (order of events, thread structure)
⚑           = Trigger point — action required
⏱ GAP       = Time gap between events
```

---

## Shipment 1 — AWB 5378819972
**DHL Ticket:** T#1WA2601260000069 | **Date:** Jan 27, 2026 | **Duty:** 1622 PLN

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     ACS PZC + Duty to DHL            2026-01-27 06:52 UTC  (piotr@acspedycja.pl)
            ⏱ GAP: 0h 54m ✅ OK
[EMAIL]     Ganther PZC release to DHL       2026-01-27 07:46 UTC  (ciagarlak@ganther.com.pl)
            ⏱ GAP: 0h 02m ✅ OK
[EMAIL]     ⚑ Ganther → Duty notice Estrella 2026-01-27 07:48 UTC  "Import clearance done, duty 1622 PLN"
            ⏱ GAP: ~27h (inferred payment)
[EMAIL]     Ganther Service Invoice           2026-01-28 11:10 UTC
[SYSTEM]    No system events recorded
```

**Notes:** Fastest clearance observed. No cesja email found (standing authorization likely pre-exists for this agent combination). PZC, PZC-to-DHL, and duty request sent within 56 minutes.

---

## Shipment 2 — AWB 8580992114
**DHL Ticket:** T#1WA2602100000562 | **Date:** Feb 10–13, 2026 | **Duty:** unknown

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL → Cesja to ACS               2026-02-13 05:36 UTC  (odprawacelna@dhl.com → roman@acspedycja.pl)
            ⏱ GAP: 2h 30m ⚠️ WARN (ACS clearance faster than usual)
[EMAIL]     ACS clearance complete (PZC)     2026-02-13 08:06 UTC  (logistyka@acspedycja.pl)
            ⏱ GAP: 0h 10m ✅ OK
[EMAIL]     Ganther PZC release to DHL       2026-02-13 08:16 UTC
[EMAIL]     DHL Notification to Ganther      2026-02-13 08:28 UTC  (AFTER clearance — notification arrived late)
[SYSTEM]    No system events recorded
```

**Notes:** DHL notification arrived AFTER clearance was already complete — cesja was sent first, then standard notification. This means DHL's internal system sent cesja and notification separately. ACS cleared in 2.5h (unusually fast). Handler: Bartłomiej Bugaj (logistyka@acspedycja.pl) instead of Piotr Kubsik.

---

## Shipment 3 — AWB 2759203252
**DHL Ticket:** T#1WA2602160000033 | **Date:** Feb 16–18, 2026 | **Duty:** unknown

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL Notification to Estrella     2026-02-18 08:23 UTC  (odprawacelna@dhl.com)
[EMAIL]     Ganther PZC release to DHL       2026-02-18 10:56 UTC  (ciagarlak@ganther.com.pl)
[SYSTEM]    No system events recorded
```

**Notes:** Partial data — no cesja or ACS PZC email found in inbox. Clearance was completed (Ganther PZC email exists), but ACS PZC arrival not captured in monitored mailboxes. The ACS PZC may have been sent directly to DHL without Estrella in copy for this shipment.

---

## Shipment 4 — AWB 3109419880
**DHL Ticket:** T#1WA2602230000068 | **Date:** Feb 23–25, 2026 | **Duty:** unknown

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL → Cesja to ACS               2026-02-25 02:09 UTC  (odprawacelna@dhl.com → roman@acspedycja.pl)
            ⏱ GAP: 2h 08m ⚠️ WARN
[EMAIL]     ACS clearance complete (PZC)     2026-02-25 04:17 UTC  (piotr@acspedycja.pl)
            ⏱ GAP: 5h 37m ⚠️ WARN
[EMAIL]     Ganther PZC release to DHL       2026-02-25 09:54 UTC
[EMAIL]     DHL Notification (generic)       2026-02-25 10:50 UTC  (arrived AFTER release)
[SYSTEM]    No system events recorded
```

**Notes:** Same pattern as AWB 8580992114 — DHL notification sent after clearance was already complete.

---

## Shipment 5 — AWB 1214569005
**DHL Ticket:** T#1WA2603020000138 | **Date:** Mar 2–4, 2026 | **Duty:** unknown

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL → Cesja to ACS               2026-03-03 03:24 UTC  (odprawacelna@dhl.com → roman@acspedycja.pl)
            ⏱ GAP: 6h 12m 🔴 DELAY (ACS took >6h to clear)
[EMAIL]     ⚑ AIS ZC429 notification         2026-03-03 09:36 UTC  (no-reply@acspedycja.pl) MRN: 26PL44302D004TVCR0
            ⏱ GAP: 5h 57m ⚠️ WARN (Ganther waited ~6h after AIS before relaying to DHL)
[EMAIL]     Ganther PZC release to DHL       2026-03-03 15:33 UTC  [Ganther acted on AIS, not waiting for ACS PZC]
            ⏱ GAP: 10h 04m after Ganther relay — ACS sent formal PZC next day
[EMAIL]     ACS formal PZC email             2026-03-04 01:37 UTC  (piotr@acspedycja.pl — backup/documentation only)
[SYSTEM]    No system events recorded
```

**Notes:** Key insight — Ganther sent PZC release to DHL based on AIS ZC429 notification, NOT waiting for ACS's formal PZC email. The ACS PZC arrived ~10h after Ganther had already released the shipment. This means Ganther monitors the AIS system directly.

---

## Shipment 6 — AWB 2824221912 ⚠️ CRITICAL CASE — 28-Day Payment Delay
**DHL Ticket:** T#1WA2603100000499 | **Date:** Mar 10 – Apr 9, 2026 | **Duty:** 1261 PLN

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL → Cesja to ACS               2026-03-12 03:55 UTC  (odprawacelna@dhl.com)
            ⏱ GAP: 5h 41m ⚠️ WARN
[EMAIL]     ⚑ AIS ZC429 notification         2026-03-12 09:36 UTC  (no-reply@acspedycja.pl) MRN: 26PL44302D005LJ4R0
            ⏱ GAP: 5h 37m ⚠️ WARN
[EMAIL]     Ganther PZC release to DHL       2026-03-12 15:13 UTC  [on AIS notification, not ACS PZC]
            ⏱ GAP: 15h 55m after Ganther release — ACS sent formal PZC next day
[EMAIL]     ACS formal PZC + duty notice     2026-03-13 07:09 UTC  (piotr@acspedycja.pl)
            ⏱ GAP: 3h 17m
[EMAIL]     ⚑ Ganther → Duty + Invoice       2026-03-13 10:26 UTC  "docs attached, pls pay duty 1261 PLN"
                                              ← DUTY NOTICE UNACTIONED FOR 28 DAYS →
[EMAIL]     ⚑ Amit URGENT email to Ganther   2026-04-09 16:17 UTC  "URGENT CUSTOMS CLEARANCE"
            ⏱ GAP: 0h 58m
[EMAIL]     Ganther closure reply             2026-04-09 17:15 UTC  "matter is closed, delivered to consignee"
[SYSTEM]    No system events recorded
```

**Root cause:** Duty notice went to `amit@estrellajewels.eu` (not `account@estrellajewels.eu` in this case). No escalation mechanism. Shipment was apparently released and delivered BEFORE duty was paid — Ganther confirmed "delivered to consignee" on Apr 9. Duty was paid sometime between Mar 13 and delivery.

---

## Shipment 7 — AWB 3369800350
**DHL Ticket:** T#1WA2603160000052 | **Date:** Mar 16–18, 2026 | **Duty:** unknown

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL → Cesja to ACS               2026-03-17 04:46 UTC  (odprawacelna@dhl.com)
            ⏱ GAP: 22h 51m 🔴 DELAY
[EMAIL]     ACS clearance complete (PZC)     2026-03-18 03:38 UTC  (piotr@acspedycja.pl)
            ⏱ GAP: 1h 21m ✅ OK
[EMAIL]     Ganther payment ack              2026-03-18 04:59 UTC  "dzieki, płaci się"
[SYSTEM]    No system events recorded
```

**Notes:** 23h clearance time — possibly a more complex declaration or ACS was busy. Payment confirmed same day as PZC.

---

## Shipment 8 — AWB 8523214840
**DHL Ticket:** T#1WA2604010000228 | **Date:** Apr 1–2, 2026 | **Duty:** 1181 PLN

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     DHL → Cesja to ACS               2026-04-01 06:45 UTC  (Paulina Debowska, odprawacelna@dhl.com)
            ⏱ GAP: 23h 28m 🔴 DELAY
[EMAIL]     ACS clearance complete (PZC)     2026-04-02 06:13 UTC  (logistyka@acspedycja.pl — Bartłomiej Bugaj)
            ⏱ GAP: 1h 01m ✅ OK
[EMAIL]     DHL Notification                 2026-04-02 07:14 UTC  (generic notification, arrived after clearance)
            ⏱ GAP: 6h 12m ⚠️ WARN
[EMAIL]     ⚑ Ganther → Duty request         2026-04-02 13:26 UTC  "pay duty 1181 PLN"
[SYSTEM]    No system events recorded
```

---

## Shipment 9 — AWB 6876258325
**DHL Ticket:** T#1WA2604070000057 | **Date:** Apr 7–13, 2026 | **Duty:** 1414 PLN

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     ACS clearance complete (PZC)     2026-04-07 05:22 UTC  (piotr@acspedycja.pl)
            ⏱ GAP: 5h 44m ⚠️ WARN
[EMAIL]     Ganther PZC release to DHL       2026-04-07 11:06 UTC
            ⏱ GAP: 0h 02m ✅ OK
[EMAIL]     ⚑ Ganther → Duty request         2026-04-07 11:08 UTC  "pay duty 1414 PLN"
            ⏱ GAP: 0h 06m ✅ OK
[EMAIL]     Ganther payment ack              2026-04-07 11:15 UTC  "dzieki, placi sie"
            ⏱ GAP: 6 days
[EMAIL]     Ganther service invoice          2026-04-13 14:47 UTC
[SYSTEM]    No system events recorded
```

**Notes:** Best payment performance — payment acknowledged 6 minutes after duty notice. Very compressed timeline at clearance stage.

---

## Shipment 10 — AWB 3283625844
**DHL Ticket:** T#1WA2604140000123 | **Date:** Apr 13–27, 2026 | **Duty:** 1225 PLN

```
[TRACKING]  Shipment arrived Poland          ── NOT AVAILABLE (API pending)
[EMAIL]     ⚑ Estrella → Broker appointment  2026-04-13 11:47 UTC  (import@estrellajewels.eu → DHL + roman@acspedycja.pl)
            ⏱ GAP: 16h 10m (Estrella sent broker letter, DHL responded next day)
[EMAIL]     DHL → Cesja to ACS               2026-04-14 03:57 UTC  (Anna Was*, odprawacelna@dhl.com)
            ⏱ GAP: 28h 26m 🔴🔴 CRITICAL (longest cesja→clearance gap)
[EMAIL]     ACS clearance complete (PZC)     2026-04-15 08:24 UTC  (piotr@acspedycja.pl)
            ⏱ GAP: 1h 43m ✅ OK
[EMAIL]     ⚑ Ganther → Duty request         2026-04-15 10:07 UTC  "clearance done, pay duty 1225 PLN"
            ⏱ GAP: 7h 21m 🔴 DELAY
[EMAIL]     Ganther payment ack              2026-04-15 17:29 UTC  "dzieki, płaci się"
            ⏱ GAP: 6 days
[EMAIL]     Ganther service invoice          2026-04-21 15:05 UTC
[SYSTEM]    No system events recorded
```

---

## Shipment 11 — AWB 5180358875 (HK Trade Fair Returnee — Atypical)
**DHL Ticket:** T#1WA2603080000002 | **Date:** Mar 8–16, 2026 | **Duty:** special (temporary export return)

```
[EMAIL]     DHL ZC429 notification           2026-03-10 ~07:00 UTC  (different DHL address: plwawecs@dhl.com)
[EMAIL]     Estrella → DHL explanation       2026-03-12 ~07:52 UTC  "goods temporarily exported from Poland to HK International Jewellery Show"
[EMAIL]     DHL queries about documents      Multiple rounds
[EMAIL]     Amit → DHL proforma             2026-03-12 ~07:56 UTC
[SYSTEM]    No system events recorded
```

**Notes:** NOT a standard import. This shipment was re-imported goods from trade fair. Different DHL team handled it (plwawecs@dhl.com). No cesja → ACS path. Multiple document rounds. This flow is outside the standard clearance automation.

---

## System Layer Findings

After reviewing all 15 audit.json batches:

```
Total batches:         15
With AWB number:        0  (none linked to email shipments)
With timeline events:   0  (no clearance workflow executed)
With clearance_status:  0
With clearance_decision: 0
Doc "PZ 26-27/039-044":  6 batches (same document, multiple runs)
Empty/test batches:      9
```

**Conclusion:** The clearance workflow system has not been used in production for any of the 11 shipments identified in email. The PZ processor has been run (generating documents) but independently of the email-triggered clearance pipeline. The system has no real-world clearance event data from this period.

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Shipments analyzed | 11 |
| Duty amounts known | 6 (1181–1622 PLN) |
| Avg duty amount | ~1351 PLN |
| DHL API tracking | Not available |
| System audit events | 0 (not deployed) |
| Critical payment delay | 1 (AWB 2824221912, 28 days) |
| Atypical cases | 1 (AWB 5180358875, HK returnee) |
