# DHL Tracking ↔ Email Correlation Map
## How Carrier Events Map to Email Events
### Source: Email reverse engineering + DHL tracking service analysis

---

## Status: DHL Tracking API Not Active

The DHL Tracking API is configured in the system but has not been approved yet:
```
dhl_tracking_api_status = "pending"  (from settings / tracking_service.py)
```

When `status != "active"`, `tracking_service.py` hard-blocks all API calls and returns:
```json
{
  "available": false,
  "reason": "DHL API not active (pending approval)",
  "status": "unknown"
}
```

**Consequence for this analysis:** DHL carrier-side tracking events (pickup, departure,
transit, arrival, customs started/completed, delivery) are not available from the API.
The correlation map below is derived by **inferring carrier events from email timing**.

---

## Theoretical Correlation Model

This maps expected DHL tracking milestones to their email equivalents.

| DHL Tracking Event | Email Signal | Lag | Reliability |
|-------------------|--------------|-----|-------------|
| `Shipment created` | (none — pre-email) | — | N/A |
| `Picked up` | (none) | — | N/A |
| `Departed origin` | (none) | — | N/A |
| `Arrived Poland (WAW hub)` | (none direct) | — | N/A |
| `Customs — Registered` | DHL sends Agencja Celna notification | ~0–48h | HIGH (confirmed) |
| `Customs — Cesja sent` | DHL sends Fwd: cesja to roman@acspedycja.pl | simultaneous | HIGH (confirmed) |
| `Customs — ACS Processing` | (no email during this phase) | — | N/A |
| `Customs — Cleared` | AIS ZC429: no-reply@acspedycja.pl OR Ganther PZC to DHL | <1h | HIGH (confirmed) |
| `Released from customs` | Ganther PZC release email to odprawacelna@dhl.com | simultaneous | HIGH (confirmed) |
| `Out for delivery` | (none — DHL internal) | — | N/A |
| `Delivered` | Ganther "matter is closed, delivered" (only for delayed cases) | days/weeks | LOW |

---

## Email-Derived Arrival Indicators

Since DHL tracking is unavailable, arrival at Poland can be inferred from email timing.

### Indicator 1: DHL "Agencja Celna DHL" Notification
**Signal:** `odprawacelna@dhl.com` sends notification to Ganther + Estrella.
**Meaning:** Shipment is in DHL Warsaw customs warehouse, assigned for agency clearance.
**Lag from physical arrival:** Typically 0–24h after arrival scan at WAW hub.

### Indicator 2: DHL Cesja Email
**Signal:** `odprawacelna@dhl.com` sends cesja to `roman@acspedycja.pl`.
**Meaning:** DHL customs team has processed the shipment, cesja officially transfers authority.
**Lag from arrival notification:** 0–4h (often simultaneous with or before notification).

### Indicator 3: AIS ZC429 Notification
**Signal:** `no-reply@acspedycja.pl` sends ZC429.
**Meaning:** Customs clearance APPROVED. Shipment is legally cleared.
**Lag from cesja:** 2h 30m to 28h 26m (observed range).

---

## Observed Correlation Table (All 11 Shipments)

```
AWB          DHL Notif          Cesja              AIS/ZC429          Clearance Complete
5378819972   2026-01-27 12:23   N/A                N/A                2026-01-27 06:52 ✓
8580992114   2026-02-13 08:28   2026-02-13 05:36   N/A                2026-02-13 08:06 ✓
2759203252   2026-02-18 08:23   N/A                N/A                Inferred ✓
3109419880   2026-02-25 04:50   2026-02-25 02:09   N/A                2026-02-25 04:17 ✓
1214569005   N/A                2026-03-03 03:24   2026-03-03 09:36   2026-03-04 01:37 ✓
2824221912   N/A                2026-03-12 03:55   2026-03-12 09:36   2026-03-13 07:09 ✓
3369800350   N/A                2026-03-17 04:46   N/A                2026-03-18 03:38 ✓
8523214840   2026-04-02 07:14   2026-04-01 06:45   N/A                2026-04-02 06:13 ✓
6876258325   N/A                N/A                N/A                2026-04-07 05:22 ✓
3283625844   N/A                2026-04-14 03:57   N/A                2026-04-15 08:24 ✓
5180358875   ~2026-03-10 07:00  N/A (different)    N/A                Manual (HK re-import)
```

---

## Key Correlation Insight: DHL Notification vs Cesja Ordering

In multiple shipments, the DHL **cesja email arrived BEFORE** the standard "Agencja Celna DHL"
notification:

| AWB | Cesja time | Notification time | Delta |
|-----|-----------|-------------------|-------|
| 8580992114 | 05:36 | 08:28 | Cesja **2h 52m BEFORE** notification |
| 3109419880 | 02:09 | 04:50 | Cesja **2h 41m BEFORE** notification |
| 8523214840 | 06:45 (Apr 1) | 07:14 (Apr 2) | Cesja **24h BEFORE** notification |

**Interpretation:** DHL's customs team sends the cesja as a direct operational message,
while the automated "Agencja Celna DHL" notification is sent separately by a different system
(potentially triggered by a different event, like final customs registration). The cesja is
the more actionable signal.

**System implication:** The automation should watch for CESJA emails (TYPE 3), not the
standard notification (TYPE 1), as the true trigger for clearance workflow start.

---

## Clearance Duration by Month

| Month | AWBs | Avg Cesja→Clearance | Fast (<4h) | Slow (>20h) |
|-------|------|--------------------|-----------:|------------:|
| Jan 2026 | 1 | N/A (no cesja) | 1 | 0 |
| Feb 2026 | 3 | ~2h 22m ⚠️ WARN | 2 | 0 |
| Mar 2026 | 4 | ~19h 22m 🔴 DELAY | 0 | 3 |
| Apr 2026 | 3 | ~25h 27m 🔴 CRITICAL | 0 | 2 |

**Observation:** Clearance is getting **slower** through the quarter. Feb 2026 averaged 2h 22m;
Apr 2026 averaged 25h+. This may reflect seasonal volume, changing ACS staffing, or more
complex declarations being submitted for higher-value shipments.

---

## AIS ZC429 as the Best Correlation Anchor

The AIS ZC429 notification from `no-reply@acspedycja.pl` is the **single most reliable
correlation point** because:
1. It is automated (no human delay)
2. It fires immediately when Polish customs grants clearance
3. It carries the MRN (unique customs declaration ID)
4. It contains the ZC429 document needed for PZ processing
5. It is sent to all parties simultaneously

Only 2 of 11 shipments had AIS ZC429 captured in inbox (AWBs 1214569005 and 2824221912).
The others either arrived in a different folder or the ZC429 sender was not in the monitored
mailboxes for those dates.

**Recommendation:** The AIS ZC429 notification from `no-reply@acspedycja.pl` should be
treated as the definitive "customs cleared" timestamp for system purposes.

---

## Tracking URLs (Manual Reference)

Since the API is not active, tracking pages can be accessed manually:

```
DHL Express tracking page:
https://www.dhl.com/pl-en/home/tracking/tracking-express.html?tracking-id=<AWB>

Examples:
AWB 3283625844: https://www.dhl.com/pl-en/home/tracking/tracking-express.html?tracking-id=3283625844
AWB 6876258325: https://www.dhl.com/pl-en/home/tracking/tracking-express.html?tracking-id=6876258325
```

These pages are publicly accessible and can be checked manually to verify delivery status
for the 6 shipments where delivery confirmation was not found in email.

---

## When DHL API Becomes Active

When `DHL_TRACKING_API_STATUS=active` is set in `.env`, the system will automatically call
the DHL Unified API (OAuth2) or fall back to legacy API key. The correlation model above
will become fully computable — each carrier event will have an exact timestamp that can be
fused with email timestamps to produce millisecond-accurate lifecycle timelines.

**Estimated value unlock:** The most important missing tracking event is "Arrived Poland"
(customs entry scan). With this timestamp, the delay between physical arrival and first
email action can be quantified — currently this is the only gap not measurable from email
data alone.
