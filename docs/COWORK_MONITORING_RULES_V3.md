# COWORK_MONITORING_RULES_V3.md
# Cowork Coordinator — Monitoring & Trigger Rules v3
# Carriers: DHL + FedEx | Period evidence: Aug 2025 – Apr 2026
# Generated: 2026-04-27

---

## Overview

This document defines the trigger conditions, confidence levels, and recommended actions
for the `detect_triggers()` function in `cowork_coordinator.py`.

Version 3 adds:
- FedEx-specific trigger variants
- Refined DSK_MISSING timing per carrier
- Duty routing gap detection
- Expanded clearance delay patterns

**Operating mode:** All triggers are SUGGEST-ONLY. The cowork coordinator reads audit.json
and returns structured suggestions. It never sends emails, never modifies files, never fires
queue_email. Execution requires human approval.

---

## Trigger Catalogue

### T1 — AWB_MISSING

**Condition:**
```python
not audit.get("awb") and "awb_missing" in (audit.get("warnings") or [])
```

**Confidence:** HIGH
**Action:** Block all automation. Request AWB from import@estrellajewels.eu.
**Carrier:** Any / Unknown

**Suggested action output:**
```json
{
  "trigger": "AWB_MISSING",
  "reason": "No AWB found in audit. Tracking and automation blocked.",
  "confidence": "high",
  "action": "Request tracking number from import@estrellajewels.eu",
  "batch_id": "...",
  "awb": null
}
```

---

### T2 — DSK_MISSING (DHL variant)

**Condition:**
```python
carrier == "DHL" AND
clearance_decision.get("require_dsk") == True AND
clearance_decision.get("clearance_path") == "broker_dsk" AND
tracking.get("arrived_warehouse") == True AND
dsk_filename is None AND
hours_since(clearance_updated_at) > 48
```

**Confidence:** HIGH
**Action:** Check if cesja email arrived from odprawacelna@dhl.com. If yes and ACS has not confirmed ZC429, escalate to roman@acspedycja.pl.
**Carrier:** DHL

**Timing:** Fire after 48 hours without DSK confirmation (DHL baseline clearance 3–5 days, 48h threshold gives sufficient buffer).

---

### T3 — DSK_MISSING (FedEx variant)

**Condition:**
```python
carrier == "FedEx" AND
clearance_decision.get("require_dsk") == True AND
dsk_filename is None AND
hours_since(clearance_updated_at) > 72  # FedEx baseline is longer
```

**Confidence:** HIGH
**Action:** Check if cesja form was submitted to pl-import@fedex.com. If not, alert import@estrellajewels.eu to submit form. If submitted but no DSK back from FedEx, check with Ganther.
**Carrier:** FedEx

**Timing:** Fire after 72 hours (FedEx cesja → DSK takes 1–4 days; 72h = Day 3 threshold).

---

### T4 — DUTY_PAYMENT_PENDING

**Condition:**
```python
(audit.get("duty_notice_received_at") is not None) AND
(audit.get("duty_paid_signal_at") is None) AND
(audit.get("duty_amount_pln") or 0) > 0 AND
business_days_since(duty_notice_received_at) > 3
```

**Confidence:** HIGH
**Action:** Remind account@estrellajewels.eu to pay duty. Include amount and reference.
**Carrier:** Any

**Payment target (normalized from Apr 2026):**
- TO: account@estrellajewels.eu
- CC: amit@estrellajewels.eu

**Timing:** Fire after 3 business days without payment confirmation.

---

### T5 — SAD_DELAY (DHL only)

**Condition:**
```python
carrier == "DHL" AND
audit.get("customs_declaration") is not None AND
agency_reply_package.get("status") == "queued" AND
hours_since(clearance_updated_at) > 24 AND
# No ZC429 event in timeline
not any(ev["event"] == "zc429_received" for ev in timeline)
```

**Confidence:** MEDIUM
**Action:** Check ACS inbox for ZC429. Email may have gone to filtered folder.
**Carrier:** DHL

**Note:** SAD_DELAY means the clearance declaration was submitted to customs but ZC429 (release confirmation) has not arrived. This is an ACS/AIS system check.

---

### T6 — CLEARANCE_OVERDUE

**Condition:**
```python
business_days_since(clearance_started_at) > threshold AND
not any(ev["event"] == "pzc_received" for ev in timeline)
```

**Thresholds by carrier:**
- DHL: > 7 business days
- FedEx: > 10 business days
- Unknown carrier: > 7 business days

**Confidence:** HIGH
**Action:** Escalate to ciagarlak@ganther.com.pl. Request status.
**Carrier:** Any

---

### T7 — CLEARANCE_SLOW (Warning only)

**Condition:**
```python
business_days_since(clearance_started_at) > slow_threshold AND
not any(ev["event"] == "pzc_received" for ev in timeline)
```

**Thresholds by carrier:**
- DHL: > 4 business days (warning before OVERDUE)
- FedEx: > 6 business days

**Confidence:** MEDIUM
**Action:** No escalation. Log for monitoring. If still slow in 2 days, escalate.
**Carrier:** Any

---

### T8 — GANTHER_RELAY_OVERDUE

**Condition:**
```python
any(ev["event"] == "pzc_received" for ev in timeline) AND
not any(ev["event"] == "duty_note_received" for ev in timeline) AND
business_days_since(pzc_received_at) > 2
```

**Confidence:** HIGH
**Action:** Contact ciagarlak@ganther.com.pl. PZC was issued but Ganther has not sent duty notice or invoice.
**Carrier:** Any

---

### T9 — DUTY_ROUTING_GAP (NEW in v3)

**Condition:**
```python
(audit.get("duty_notice_received_at") is not None) AND
# Ganther sent duty to amit@ without account@ in TO field
# Detectable from timeline event detail
timeline_event_detail("duty_note_received").get("to_address") contains "amit@" AND
NOT timeline_event_detail("duty_note_received").get("to_address") contains "account@"
```

**Confidence:** MEDIUM
**Action:** Flag routing gap. account@estrellajewels.eu may not have received duty notice.
Forward duty notice to account@estrellajewels.eu manually.
**Carrier:** Any

**Context:** Jan-Mar 2026 duty routing was inconsistent. Apr 2026 normalized.
AWB 2824221912 (Mar 2026) had a 28-day clearance delay attributed partly to duty routing gap.

---

### T10 — FEDEX_DUTY_RECIPIENT_MISMATCH (NEW in v3)

**Condition:**
```python
carrier == "FedEx" AND
# Timeline contains billing dispute or "recipient pays" flag
any(ev.get("detail", {}).get("fedex_billing_mode") == "recipient_pays" for ev in timeline)
```

**Confidence:** HIGH
**Action:** Alert Amit. Contact poland@fedex.com to request billing correction.
FedEx charged recipient (Estrella customer) instead of importer.
**Carrier:** FedEx only

---

### T11 — TIMELINE_EMPTY

**Condition:**
```python
not (audit.get("timeline") or [])
```

**Confidence:** HIGH
**Action:** Run backfill script. If batch predates timeline logging, reconstruct from audit fields.
**Carrier:** Any

---

## Trigger Firing Priority

```
CRITICAL (fire immediately):
  T1 — AWB_MISSING
  T11 — TIMELINE_EMPTY

HIGH (fire after threshold breach):
  T2 — DSK_MISSING (DHL)
  T3 — DSK_MISSING (FedEx)
  T4 — DUTY_PAYMENT_PENDING
  T6 — CLEARANCE_OVERDUE
  T8 — GANTHER_RELAY_OVERDUE
  T10 — FEDEX_DUTY_RECIPIENT_MISMATCH

MEDIUM (fire with warning, no escalation):
  T5 — SAD_DELAY
  T7 — CLEARANCE_SLOW
  T9 — DUTY_ROUTING_GAP
```

---

## Carrier Detection

The cowork coordinator should detect carrier from audit fields in this priority order:

```python
def _detect_carrier(audit: dict) -> str:
    """Detect carrier from audit fields."""
    # Explicit field
    if audit.get("carrier"):
        return audit["carrier"].upper()

    # AWB length heuristic
    awb = audit.get("awb", "")
    if awb:
        if len(awb) == 10:  # DHL AWBs are typically 10 digits
            return "DHL"
        if len(awb) == 12:  # FedEx AWBs are typically 12 digits
            return "FEDEX"

    # Timeline event detection
    timeline = audit.get("timeline") or []
    for ev in timeline:
        detail = ev.get("detail") or {}
        source = str(ev.get("trigger_source", "")).lower()
        if "fedex" in source or "pl-import@fedex" in str(detail):
            return "FEDEX"
        if "dhl" in source or "odprawacelna@dhl" in str(detail):
            return "DHL"

    return "UNKNOWN"
```

---

## DSK Detection in Timeline

A DSK/cesja event is considered "received" when:

```python
# DHL path: ZC429 received = cesja was processed
dsk_received = any(
    ev["event"] in ("zc429_received", "cesja_received", "dsk_received")
    for ev in timeline
)

# FedEx path: ganther_pzc_sent implies DSK was processed
# (Ganther only sends PZC after receiving DSK)
fedex_dsk_inferred = any(
    ev["event"] == "ganther_pzc_sent"
    for ev in timeline
)
```

---

## Suggest-Only Mode Contract

The `detect_triggers()` function:

✅ MAY:
- Read audit dict
- Read timeline events
- Compute time deltas
- Return structured suggestion list

❌ MUST NOT:
- Call queue_email()
- Call write_json_atomic()
- Append to timeline
- Make HTTP requests
- Read filesystem (only receives pre-loaded audit dict)

```python
def detect_triggers(audit: dict, batch_id: str = "") -> list[dict]:
    """
    Pure function. Reads audit, returns trigger suggestions.
    No side effects. Called from run_cowork_cycle(suggest_only=True).
    """
    suggestions = []
    # ... trigger checks ...
    return suggestions
```

---

## Cowork Cycle Output Format

```json
{
  "mode": "suggest_only",
  "run_at": "2026-04-27T10:00:00+00:00",
  "batches_checked": 15,
  "suggestions": [
    {
      "trigger": "DUTY_PAYMENT_PENDING",
      "reason": "Duty notice received 5 business days ago, no payment confirmation",
      "confidence": "high",
      "action": "Remind account@estrellajewels.eu to pay duty of 1225 PLN",
      "batch_id": "f490637817b14d2cb72319ebf614ed4d",
      "awb": null
    }
  ],
  "errors": []
}
```

---

## Changes from v2

| Change | Reason |
|--------|--------|
| Added T3 DSK_MISSING (FedEx variant) | FedEx confirmed to use same DSK/cesja mechanism |
| Added T9 DUTY_ROUTING_GAP | Jan–Mar 2026 routing inconsistency caused 28-day delay |
| Added T10 FEDEX_DUTY_RECIPIENT_MISMATCH | AWB 882994160903 billing dispute found in email analysis |
| FedEx carrier detection added | AWB 887467026597 confirmed FedEx clearance via Ganther |
| DSK threshold: DHL 48h, FedEx 72h | FedEx baseline clearance is longer (6–9 days vs 3–5 days) |
| CLEARANCE_OVERDUE: FedEx threshold 10d | Calibrated from AWB 887467026597 evidence |

---

*This document supersedes COWORK_MONITORING_RULES_V2.md.*
*All trigger thresholds are evidence-based from email analysis. Adjust after 3+ months of live data.*
