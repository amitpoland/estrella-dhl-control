# Cowork Email Monitoring Rules
## Clearance Workflow Detection for cowork_coordinator.py
### Source: Email reverse engineering, Jan–Apr 2026

---

## Purpose

These rules define how `cowork_coordinator.py` (and any future automated email monitor)
should classify incoming emails and decide what actions to take.
Rules are derived from observed real-world email patterns across 11 shipments.

---

## Monitored Mailboxes

| Mailbox | Role | Priority |
|---------|------|----------|
| `info@estrellajewels.eu` | Receives DHL notifications (CC), cesja (CC), AIS notifications | HIGH |
| `import@estrellajewels.eu` | Sends broker letters; receives DHL queries | HIGH |
| `account@estrellajewels.eu` | Receives Ganther duty notices (TO) | HIGH |

All three must be monitored. `account@estrellajewels.eu` is the most actionable
(duty payment instructions land here).

---

## Rule Set

### RULE 1: New Shipment Arrival

**Trigger condition:**
```
sender IN ["odprawacelna@dhl.com", "plwawecs@dhl.com"]
AND subject MATCHES /Agencja Celna DHL.*przesyłka numer/
AND subject MATCHES /T#1WA\d+/
```

**Actions:**
1. Extract AWB: `re.search(r'przesyłka numer[:\s]+(\d{10,12})', subject)`
2. Extract DHL ticket: `re.search(r'T#1WA\d+', subject)`
3. Create new batch record with `status = "dhl_notification_received"`
4. Set `audit["tracking_no"] = awb`
5. Set `audit["dhl_ticket"] = ticket`
6. Post to Cliq `#PZ`: "New DHL shipment notification: AWB {awb} — broker appointment may be needed"

**Do NOT auto-send broker appointment** — verify no standing authorization first.

---

### RULE 2: Cesja Received (DSK)

**Trigger condition:**
```
sender == "odprawacelna@dhl.com"
AND subject MATCHES /Fwd:.*T#1WA\d+/
AND (body CONTAINS "cesja" OR body CONTAINS "dokumenty do cesji")
AND has_attachment == True
```

**Actions:**
1. Extract AWB from subject
2. Set `audit["dsk_received"] = True`
3. Set `audit["dsk_source"] = "odprawacelna@dhl.com"`
4. Set `audit["dsk_received_at"] = email_timestamp`
5. Download attachment (cesja document) and save to `outputs/{batch_id}/source/cesja/`
6. Advance `clearance_status` to `"cesja_received"`
7. Post to Cliq: "Cesja received for AWB {awb} → ACS Spedycja now handling clearance"

**Note:** Cesja is always from `odprawacelna@dhl.com`, not `administracja_centralna@dhl.com`.

---

### RULE 3: AIS Clearance Granted (ZC429 Arrival)

**Trigger condition:**
```
sender == "no-reply@acspedycja.pl"
AND subject == "Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)"
AND has_attachment == True
```

**Actions:**
1. Extract MRN: `re.search(r'MRN[:\s]+([A-Z0-9]+)', body)`
2. Extract AWB from thread context (linked via T#1WA ticket or prior subject matching)
3. Download attached ZC429 PDF → save to `outputs/{batch_id}/source/`
4. Set `audit["zc429_received"] = True`
5. Set `audit["zc429_received_at"] = email_timestamp`
6. Set `audit["mrn"] = mrn`
7. Set `audit["zc429_source"] = "email_auto"`
8. Advance `clearance_status` to `"cleared"`
9. Post to Cliq: "✅ Customs cleared — AWB {awb} / MRN {mrn} — ZC429 saved"

**Priority:** HIGH. This is the most reliable clearance signal.
ZC429 arrives within minutes of customs approval. Auto-download is safe.

---

### RULE 4: ACS PZC + Duty Notice Received

**Trigger condition:**
```
sender IN ["piotr@acspedycja.pl", "logistyka@acspedycja.pl"]
AND subject MATCHES /Re: Fwd: Fwd:.*Agencja Celna DHL/
AND (body CONTAINS "PZC" OR body CONTAINS "należności celne")
AND has_attachment == True
```

**Actions:**
1. Extract AWB from subject
2. Download attachments (PZC + duty awizo) → save to `outputs/{batch_id}/source/pzc/`
3. Set `audit["pzc_received"] = True`
4. Set `audit["pzc_received_at"] = email_timestamp`
5. Advance `clearance_status` to `"pzc_received"`
6. Start duty payment timer: `audit["duty_payment_deadline"] = now + 72h`
7. Post to Cliq: "📄 PZC received for AWB {awb} — awaiting Ganther duty amount"

---

### RULE 5: Ganther Duty Payment Request (HIGHEST PRIORITY)

**Trigger condition:**
```
sender == "ciagarlak@ganther.com.pl"
AND recipient CONTAINS "account@estrellajewels.eu"
AND (body CONTAINS "pay duty" OR body CONTAINS "nota" OR body MATCHES /\d{3,5}\s*PLN/)
AND has_attachment == True
```

**Actions:**
1. Extract AWB from subject or body
2. Extract duty amount: `re.search(r'(\d{3,5})\s*PLN', body)` → first match
3. Set `audit["duty_amount_pln"] = amount`
4. Set `audit["duty_notice_received_at"] = email_timestamp`
5. Download nota attachment → save to `outputs/{batch_id}/source/nota/`
6. Advance `clearance_status` to `"duty_notice_received"`
7. Post to Cliq `#PZ` with HIGH PRIORITY:
   ```
   ⚠️ DUTY PAYMENT REQUIRED
   AWB: {awb}
   Amount: {amount} PLN
   Nota: attached
   Pay to: [as per nota]
   Deadline: {now + 3 business days}
   ```
8. Notify `amit@estrellajewels.eu` if duty > 1000 PLN

**Escalation if no payment confirmation within 72h:**
```
POST to Cliq: "🔴 OVERDUE DUTY — AWB {awb} — {amount} PLN unpaid for 3 days"
Notify: amit@estrellajewels.eu
```

---

### RULE 6: Ganther PZC Release to DHL

**Trigger condition:**
```
sender == "ciagarlak@ganther.com.pl"
AND recipient CONTAINS "odprawacelna@dhl.com"
AND (body CONTAINS "odprawiona celnie" OR body CONTAINS "PZC")
AND (body CONTAINS "Gupta" OR body CONTAINS "zwolnić towar")
AND has_attachment == True
```

**Actions:**
1. Extract AWB from body: `re.search(r'AWB\s+(\d+)', body)`
2. Set `audit["ganther_pzc_to_dhl_at"] = email_timestamp`
3. Advance `clearance_status` to `"shipment_released"`
4. Post to Cliq: "🚚 Shipment released — AWB {awb} — Amit can collect from DHL"

---

### RULE 7: Duty Payment Confirmed

**Trigger condition:**
```
sender == "ciagarlak@ganther.com.pl"
AND subject MATCHES /RE: Fwd:.*Agencja Celna DHL/
AND (body CONTAINS "płaci się" OR body CONTAINS "placi sie" OR body CONTAINS "dzieki")
AND has_attachment == False
```

**Actions:**
1. Extract AWB from subject
2. Set `audit["duty_paid_signal_at"] = email_timestamp`
3. Advance `clearance_status` to `"duty_paid"`
4. Clear any pending duty escalation timer
5. Post to Cliq: "✅ Duty payment confirmed by Ganther for AWB {awb}"

---

### RULE 8: Ganther Service Invoice

**Trigger condition:**
```
sender == "ciagarlak@ganther.com.pl"
AND recipient CONTAINS "account@estrellajewels.eu"
AND (body CONTAINS "invoice" OR body CONTAINS "Our invoic")
AND has_attachment == True
AND (clearance_status FOR awb IN ["duty_paid", "shipment_released"])
```

**Actions:**
1. Extract AWB from subject
2. Download invoice attachment → save to `outputs/{batch_id}/source/ganther_invoice/`
3. Set `audit["ganther_invoice_received_at"] = email_timestamp`
4. Advance `clearance_status` to `"ganther_invoice_received"`
5. Post to Cliq: "🧾 Ganther service invoice received for AWB {awb}"

---

### RULE 9: DHL Billing (Ignore / Classify Only)

**Trigger condition:**
```
sender IN ["windykacja.DHLexpress@dhl.com", "Justyna.CZYNSZ@dhl.com"]
OR subject MATCHES /WEZWANIE DO ZAPŁATY|planowana blokada konta/
```

**Actions:**
1. Classify as `DHL_BILLING` — NOT a clearance event
2. Apply label `DHL_BILLING` in Zoho Mail
3. Post to `#account` channel (NOT `#PZ`): "DHL billing notice received — review invoice"
4. Do NOT create a batch record

---

## State Machine

The cowork coordinator should maintain `clearance_status` as a state machine:

```
UNKNOWN
  → dhl_notification_received     (RULE 1)
  → cesja_received                 (RULE 2)
  → cleared                        (RULE 3 — ZC429 received)
  → pzc_received                   (RULE 4)
  → duty_notice_received           (RULE 5)
  → shipment_released              (RULE 6)
  → duty_paid                      (RULE 7)
  → ganther_invoice_received       (RULE 8)
  → [CLOSED]                       (manual confirmation or auto after invoice)
```

State transitions must only advance, never regress.
Multiple states can overlap (e.g., `pzc_received` and `duty_notice_received` often arrive within minutes).

---

## AWB-to-Batch Matching

When an email arrives, match to an existing batch using:
1. AWB number (from subject extraction)
2. DHL ticket reference `T#1WA...` (cross-reference from prior emails)
3. If no match: create a new pending batch record

Matching priority:
```
1. Exact AWB match in audit["tracking_no"]
2. DHL ticket match in audit["dhl_ticket"]  
3. Thread ID match (if email is a reply in existing thread)
4. No match → create new pending batch
```

---

## Escalation Rules

| Condition | Escalation Target | Channel |
|-----------|------------------|---------|
| No broker letter sent within 24h of DHL notification | `import@estrellajewels.eu` | `#PZ` |
| No AIS notification within 5 days of cesja | `ciagarlak@ganther.com.pl` | `#PZ` |
| Duty notice received but no "płaci się" within 72h | `amit@estrellajewels.eu` | `#PZ` + email |
| Duty notice received but no "płaci się" within 7 days | `amit@estrellajewels.eu` | Email (HIGH PRIORITY) |
| No Ganther invoice within 14 days of clearance | Ganther follow-up email | `#PZ` |

---

## Email Fields Reference

When reading emails via Zoho Mail API:
```python
# Extract from email search result
awb = re.search(r'przesy[łl]ka numer[:\s]+(\d{10,12})', subject)
ticket = re.search(r'T#1WA\d+', subject)
duty_pln = re.search(r'(\d{3,5})\s*PLN', body)
mrn = re.search(r'MRN[:\s]+([A-Z0-9]+)', body)

# Key email field mappings (Zoho Mail API)
sender = email["fromAddress"]
subject = email["subject"]
has_attachment = email["hasAttachment"] == "1"
timestamp_ms = int(email["sentDateInGMT"])
folder_id = email["folderId"]
message_id = email["messageId"]
```

---

## Do-Not-Automate List

These actions must always require human approval before execution:

| Action | Reason |
|--------|--------|
| Send broker appointment letter to DHL | Sensitive legal authorization |
| Send cesja reply on behalf of Estrella | Legal document — must be reviewed |
| Pay duty (any amount) | Financial transaction |
| Reply to DHL customs queries (documents, commodity description) | Customs declarations are legally binding |
| Send any email to `administracja_centralna@dhl.com` | High-impact DHL ops address |

These may be *drafted* and queued for review, but never auto-sent.

---

## Sender Whitelist for Auto-Classification

Only classify and act on emails from these senders automatically:

```python
TRUSTED_CLEARANCE_SENDERS = [
    "odprawacelna@dhl.com",           # DHL customs
    "plwawecs@dhl.com",                # DHL WAW customs office
    "no-reply@acspedycja.pl",          # ACS automated ZC429 notifications
    "piotr@acspedycja.pl",             # ACS agent (Piotr Kubsik)
    "logistyka@acspedycja.pl",         # ACS agent (Bartłomiej Bugaj)
    "biuro@acspedycja.pl",             # ACS office
    "roman@acspedycja.pl",             # ACS agent (Roman Kałużny)
    "ciagarlak@ganther.com.pl",        # Ganther coordinator (Grzegorz Ciągarlak)
    "jaworska@ganther.com.pl",         # Ganther (secondary)
]

# Billing — classify but do not trigger clearance actions
BILLING_SENDERS = [
    "windykacja.DHLexpress@dhl.com",
    "Justyna.CZYNSZ@dhl.com",
]

# DHL queries about shipments (manual handling required)
DHL_QUERY_SENDERS = [
    "wawpok@dhl.com",
    "kontakt.int@dhl.com",
]
```

---

## Notes on Timing

Based on observed shipments:

| Step | Typical Duration |
|------|-----------------|
| DHL notification → cesja | 24–48 hours |
| Cesja → AIS ZC429 | 1–5 business days |
| AIS ZC429 → ACS PZC email | Minutes (same email batch) |
| ACS PZC → Ganther duty notice | 15–30 minutes |
| Ganther duty notice → Estrella pays | 1–4 days (normal); up to 28 days (abnormal) |
| Payment → Ganther confirms | Same day |
| Clearance → Ganther service invoice | 5–10 days |

Total typical cycle: **7–14 days** from DHL notification to shipment pickup.
Worst case observed: **42+ days** (AWB 2824221912 — 28d payment delay + delays before).
