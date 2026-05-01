# Automation Trigger Rules
## Real-World Validated — Derived from 11 Shipments, Jan–Apr 2026

---

## Architecture

The automation layer sits between email inbox and the system. It watches incoming email,
classifies events, updates system state, and fires notifications. It does NOT initiate
outbound emails automatically — it drafts and queues for human review.

```
Zoho Mail Inbox (info / import / account)
        ↓
   Email Classifier (RULE ENGINE — this document)
        ↓
   Batch State Machine (audit.json)
        ↓
   Cliq Notifications (#PZ channel)
        ↓
   Human Action (pay duty, approve email, etc.)
```

---

## TRIGGER 1: New Shipment — DHL Cesja Received

**Priority:** HIGH
**Signal reliability:** VERY HIGH (confirmed in 8/11 shipments)
**Recommendation:** Use as PRIMARY clearance start trigger (more reliable than DHL notification)

```python
TRIGGER_1 = {
    "name": "DHL_CESJA_RECEIVED",
    "conditions": {
        "sender": "odprawacelna@dhl.com",
        "subject_pattern": r"Fwd:.*T#1WA\d+.*przesy[łl]ka numer",
        "body_keywords": ["cesja", "dokumenty do cesji"],
        "has_attachment": True,
    },
    "extract": {
        "awb": r"przesy[łl]ka numer[:\s]+(\d{10,12})",
        "ticket": r"T#1WA\d+",
        "cesja_doc": "first_attachment",
    },
    "actions": [
        "create_batch_if_not_exists(awb, ticket)",
        "set(audit.dsk_received = True)",
        "set(audit.dsk_source = 'odprawacelna@dhl.com')",
        "set(audit.dsk_received_at = email_timestamp)",
        "save_attachment_to(outputs/{batch_id}/source/cesja/)",
        "set(audit.clearance_status = 'cesja_received')",
        "start_timer('cesja_to_clearance', 24h)",
        "post_cliq('#PZ', '📨 Cesja received — AWB {awb}. ACS Spedycja now handling clearance. Expected: ~6–24h.')",
    ],
}
```

---

## TRIGGER 2: AIS Customs Clearance Approved

**Priority:** CRITICAL
**Signal reliability:** VERY HIGH (automated from Polish customs AIS system)
**Timing:** Fires immediately when customs grants clearance

```python
TRIGGER_2 = {
    "name": "AIS_ZC429_CLEARANCE",
    "conditions": {
        "sender": "no-reply@acspedycja.pl",
        "subject_exact": "Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)",
        "has_attachment": True,
    },
    "extract": {
        "mrn": r"MRN[:\s]+([A-Z0-9]+)",
        "awb": "from_thread_context",  # match via T#1WA in prior thread
        "zc429_doc": "first_attachment",
    },
    "actions": [
        "cancel_timer('cesja_to_clearance')",
        "save_attachment_to(outputs/{batch_id}/source/{awb}_ZC429.pdf)",
        "set(audit.zc429_received = True)",
        "set(audit.zc429_received_at = email_timestamp)",
        "set(audit.mrn = mrn)",
        "set(audit.zc429_source = 'email_auto')",
        "set(audit.clearance_status = 'cleared')",
        "start_timer('pzc_relay_to_dhl', 8h)",
        "post_cliq('#PZ', '✅ CUSTOMS CLEARED — AWB {awb} / MRN {mrn}. ZC429 saved. Ganther should release to DHL shortly.')",
    ],
}
```

---

## TRIGGER 3: ACS PZC + Duty Notice (Formal)

**Priority:** HIGH
**Signal reliability:** HIGH (confirmed in 9/11 shipments)

```python
TRIGGER_3 = {
    "name": "ACS_PZC_RECEIVED",
    "conditions": {
        "sender_pattern": r"(piotr|logistyka|biuro)@acspedycja\.pl",
        "subject_pattern": r"Re:.*Fwd:.*Fwd:.*Agencja Celna DHL",
        "body_keywords_any": ["PZC", "należności celne", "potwierdzenia wpłaty", "awizo"],
        "has_attachment": True,
    },
    "extract": {
        "awb": r"przesy[łl]ka numer[:\s]+(\d{10,12})",
        "ticket": r"T#1WA\d+",
        "pzc_doc": "attachment",
    },
    "actions": [
        "save_attachment_to(outputs/{batch_id}/source/pzc/)",
        "set(audit.pzc_received = True)",
        "set(audit.pzc_received_at = email_timestamp)",
        "set(audit.clearance_status = 'pzc_received')",
        "start_timer('duty_payment', 72h)",
        "post_cliq('#PZ', '📄 ACS PZC received for AWB {awb}. Awaiting Ganther duty notification.')",
    ],
    "notes": "In some shipments (1214569005, 2824221912), Ganther relays to DHL BEFORE this email arrives. Do not block on ACS PZC — it is informational."
}
```

---

## TRIGGER 4: Ganther PZC Release to DHL

**Priority:** MEDIUM
**Signal reliability:** HIGH

```python
TRIGGER_4 = {
    "name": "GANTHER_PZC_RELEASE",
    "conditions": {
        "sender": "ciagarlak@ganther.com.pl",
        "recipients_include": "odprawacelna@dhl.com",
        "body_keywords_all": ["odprawiona celnie", "PZC"],
        "has_attachment": True,
    },
    "extract": {
        "awb": r"AWB[:\s]+(\d{10,12})",
        "ticket": r"T#1WA\d+",
    },
    "actions": [
        "cancel_timer('pzc_relay_to_dhl')",
        "set(audit.ganther_pzc_to_dhl_at = email_timestamp)",
        "set(audit.clearance_status = 'shipment_released')",
        "post_cliq('#PZ', '🚚 Shipment released by Ganther — AWB {awb}. Amit can collect from DHL warehouse.')",
    ],
}
```

---

## TRIGGER 5: Ganther Duty Payment Request ← MOST CRITICAL TRIGGER

**Priority:** CRITICAL — accounts team must act
**Signal reliability:** VERY HIGH (confirmed in 6/11 shipments with duty amounts)
**Recipient:** `account@estrellajewels.eu` (always — this is the action trigger)

```python
TRIGGER_5 = {
    "name": "GANTHER_DUTY_REQUEST",
    "conditions": {
        "sender": "ciagarlak@ganther.com.pl",
        "recipients_include": "account@estrellajewels.eu",
        "body_keywords_any": ["pay duty", "nota", "należności celne"],
        "body_pattern": r"\d{3,5}\s*PLN",
        "has_attachment": True,
    },
    "extract": {
        "awb": r"AWB[:\s]+(\d{10,12})|przesy[łl]ka[:\s]+(\d{10,12})",
        "ticket": r"T#1WA\d+",
        "duty_pln": r"(\d{3,5})\s*PLN",
        "nota_doc": "attachment",
    },
    "actions": [
        "save_attachment_to(outputs/{batch_id}/source/nota/)",
        "set(audit.duty_amount_pln = duty_pln)",
        "set(audit.duty_notice_received_at = email_timestamp)",
        "set(audit.clearance_status = 'duty_notice_received')",
        "start_timer('payment_escalation_1', 72h)",
        "start_timer('payment_escalation_2', 168h)",  # 7 days
        "post_cliq('#PZ', PRIORITY='HIGH', message='''\n⚠️ DUTY PAYMENT REQUIRED\nAWB: {awb}\nAmount: {duty_pln} PLN\nNota: saved\nPay to: per nota (bank transfer)\nDeadline: {timestamp + 3 business days}\n@account — please action\n''')",
        "notify_amit_if_amount_over_1000pln(duty_pln)",
    ],
    "escalations": {
        "72h_no_ack": {
            "action": "post_cliq('#PZ', '🔴 OVERDUE DUTY — AWB {awb}, {duty_pln} PLN unpaid for 3 days. @amit please check.')",
        },
        "168h_no_ack": {
            "action": "post_cliq('#PZ', '🚨 CRITICAL — AWB {awb}, {duty_pln} PLN unpaid for 7 DAYS. Immediate action required.')",
        },
    },
}
```

---

## TRIGGER 6: Payment Confirmed by Ganther

**Priority:** HIGH (closes the payment loop)
**Signal reliability:** HIGH

```python
TRIGGER_6 = {
    "name": "GANTHER_PAYMENT_ACK",
    "conditions": {
        "sender": "ciagarlak@ganther.com.pl",
        "body_keywords_any": ["płaci się", "placi sie", "dzieki"],
        "has_attachment": False,
        "prior_state": "duty_notice_received",  # only meaningful if duty was pending
    },
    "extract": {
        "awb": "from_thread_subject",
    },
    "actions": [
        "cancel_timer('payment_escalation_1')",
        "cancel_timer('payment_escalation_2')",
        "set(audit.duty_paid_signal_at = email_timestamp)",
        "set(audit.clearance_status = 'duty_paid')",
        "post_cliq('#PZ', '✅ Duty payment confirmed by Ganther for AWB {awb}')",
    ],
}
```

---

## TRIGGER 7: Ganther Service Invoice

**Priority:** LOW (informational, for accounts)

```python
TRIGGER_7 = {
    "name": "GANTHER_SERVICE_INVOICE",
    "conditions": {
        "sender": "ciagarlak@ganther.com.pl",
        "recipients_include": "account@estrellajewels.eu",
        "body_keywords_any": ["invoice", "invoic"],
        "has_attachment": True,
        "prior_state_any": ["duty_paid", "shipment_released"],
    },
    "extract": {"awb": "from_thread_subject"},
    "actions": [
        "save_attachment_to(outputs/{batch_id}/source/ganther_invoice/)",
        "set(audit.ganther_invoice_received_at = email_timestamp)",
        "set(audit.clearance_status = 'ganther_invoice_received')",
        "post_cliq('#PZ', '🧾 Ganther invoice received for AWB {awb}. Forward to accounts.')",
    ],
}
```

---

## TIMEOUT TRIGGERS (Escalation Rules)

### Timeout T1: No clearance after cesja

```python
IF TRIGGER_1_FIRED (cesja received)
   AND no TRIGGER_2 or TRIGGER_3 within 24 hours:
   → post_cliq('#PZ', '⚠️ No clearance signal 24h after cesja for AWB {awb}. Check with Ganther/ACS.')
   → draft_email_to(ciagarlak@ganther.com.pl, subject="Status check AWB {awb}")
```

### Timeout T2: No Ganther relay after clearance

```python
IF TRIGGER_2 or TRIGGER_3 FIRED (customs cleared)
   AND no TRIGGER_4 within 8 hours:
   → post_cliq('#PZ', '⚠️ No Ganther release 8h after clearance for AWB {awb}. Check with Ganther.')
```

### Timeout T3: No duty payment acknowledgment (HIGHEST PRIORITY)

```python
IF TRIGGER_5_FIRED (duty notice received)
   AND no TRIGGER_6 within 72 hours:
   → post_cliq('#PZ', '🔴 Duty payment overdue 72h — AWB {awb}, {duty_pln} PLN')
   → notify_email(amit@estrellajewels.eu)

IF TRIGGER_5_FIRED
   AND no TRIGGER_6 within 168 hours (7 days):
   → post_cliq('#PZ', '🚨 CRITICAL: Duty overdue 7 days — AWB {awb}')
   → escalate to Amit with URGENT flag
```

### Timeout T4: No ACS clearance after 24h (new trigger)

```python
IF TRIGGER_1_FIRED (cesja received)
   AND no ACS_PZC or AIS_ZC429 within 24 hours:
   → post_cliq('#PZ', '🔴 ACS clearance overdue (>24h) — AWB {awb}. Typically done within 24h.')
```

---

## DO-NOT-AUTOMATE Rules

These must NEVER be auto-executed — human review required:

| Action | Reason |
|--------|--------|
| Send broker appointment email to DHL | Legal authorization document |
| Reply to DHL customs queries | Customs declarations are legally binding |
| Pay duty (any action toward payment) | Financial transaction |
| Accept any DHL terms or agreements | Legal |
| Forward shipment documents to third parties | Privacy/compliance |
| Create/modify DHL clearance instructions | Legal |

These may be drafted and placed in a review queue, but never auto-sent.

---

## Signal Priority Matrix

Rank by urgency (highest to lowest):

| Priority | Trigger | Action Window |
|----------|---------|---------------|
| 🚨 P0 | Duty notice + no payment 7d | Immediate — escalate Amit |
| 🔴 P1 | Duty notice received | 72h — accounts team pays |
| 🔴 P1 | No clearance 24h after cesja | 4h — follow up Ganther |
| ⚠️ P2 | AIS ZC429 received | Same day — save ZC429, notify |
| ⚠️ P2 | Cesja received | Same day — start clearance clock |
| 📄 P3 | ACS PZC received | Next action — save, inform |
| 📄 P3 | Ganther PZC to DHL | Informational — update status |
| ✅ P4 | Ganther payment ack | Close payment loop |
| 🧾 P4 | Ganther service invoice | Route to accounts |

---

## Implementation Note

The trigger engine should be implemented as a polling loop on the Zoho Mail API:
- Poll `info@estrellajewels.eu`, `import@estrellajewels.eu`, `account@estrellajewels.eu`
- Check for new emails every 15 minutes during Polish business hours (07:00–18:00 CET)
- Check every 30 minutes outside business hours
- Use `fromDate` filter with last-checked timestamp to avoid reprocessing
- Do NOT use `fromtime` filter (unreliable per Zoho Cliq troubleshooting notes)
- Use `limit=50` per mailbox per poll
- Deduplication: track processed messageIds in a local set
