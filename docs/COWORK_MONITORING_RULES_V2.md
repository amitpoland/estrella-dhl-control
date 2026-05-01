# Cowork Monitoring Rules — v2
## Real-World Validated Automation Design
### Replaces: COWORK_MONITORING_RULES.md (v1)
### Source: 11 shipments, Jan–Apr 2026 + system analysis

---

## Changes from v1

| Item | v1 | v2 |
|------|----|----|
| DSK source | `administracja_centralna@dhl.com` | **`odprawacelna@dhl.com`** (FIXED — critical bug) |
| Cesja trigger | Based on arrival notification | **Based on cesja email** (more reliable) |
| Clearance signal | ACS PZC email | **AIS ZC429 OR ACS PZC** (whichever comes first) |
| Payment timeout | Not specified | **72h warn, 7-day critical** |
| System layer | Assumed active | **Not deployed — email-only for now** |
| Tracking integration | Assumed available | **API pending — email-derived only** |
| Ganther relay timing | Immediate after PZC | **5–6h typical lag** |

---

## Part A: Real vs System Design Comparison

### REAL FLOW (verified from email evidence)

```
1. DHL arrival (unknown — tracking API pending)
2. DHL → Cesja email to roman@acspedycja.pl CC info@estrellajewels.eu
   [From: odprawacelna@dhl.com]
3. ACS processes declaration (2–28h)
4a. AIS → ZC429 notification to all parties [no-reply@acspedycja.pl] ← CLEARANCE SIGNAL
4b. ACS → PZC + duty notice to DHL + Estrella + Ganther [piotr@acspedycja.pl or logistyka@]
5. Ganther → PZC release to DHL (acts on AIS, not waiting for ACS email) [ciagarlak@ganther.com.pl]
6. Ganther → Duty notice to account@estrellajewels.eu "pay duty X PLN" [same day]
7. Estrella pays duty (bank transfer, 1 min – 28 days)
8. Ganther → "dzieki, płaci się" to thread [same day as payment]
9. Ganther → Service invoice to account@ [5–10 days later]
```

### CURRENT SYSTEM DESIGN (from cowork_coordinator.py + routes)

```
1. Admin uploads invoices + ZC429 to dashboard
2. PZ processor runs
3. Polish description generated
4. IF CIF > $2500: Build agency email package
5. IF CIF ≤ $2500: DHL description reply path
6. Email queued for admin review
```

### Comparison

| Step | Real Flow | System Design | Status |
|------|-----------|--------------|--------|
| AWB input | From email subject | From dashboard upload | MISSING — no auto-extraction |
| Cesja detection | Email monitoring | `mark_email_received` endpoint | MISSING in prod (not called) |
| ZC429 arrival | Email auto-ingestion | Manual upload | MISSING — ZC429 arrives by email |
| Clearance signal | AIS ZC429 email | Not modeled | MISSING |
| PZC received | ACS email → Ganther | Not tracked | MISSING |
| Duty payment | Ganther email, then Estrella pays | Not modeled | MISSING |
| Duty amount (PLN) | Extracted from email | Not stored | MISSING |
| Payment ack | Ganther "płaci się" | Not tracked | MISSING |
| Service invoice | Ganther email | Not tracked | MISSING |
| DHL API tracking | Pending | Pending | MATCH |
| PZ generation | Dashboard | Dashboard | MATCH |
| Agency email | Agency package builder | Agency package builder | MATCH |
| DHL reply (DSK) | Via cowork | Via routes_dhl_clearance | PARTIAL (addresses wrong) |

---

## Part B: Final Clearance Flow (Real-World Validated)

This is the authoritative workflow for implementing the full automation.

```
PHASE 1: TRIGGER
─────────────────
Email: DHL cesja arrives → odprawacelna@dhl.com → roman@acspedycja.pl, CC info@estrellajewels.eu
  • Create batch (AWB, ticket, date)
  • Save cesja attachment
  • Start clearance clock (24h SLA)
  • Notify #PZ

PHASE 2: CLEARANCE MONITORING
──────────────────────────────
  [Wait for AIS ZC429 or ACS PZC — whichever first]
  
  Email: AIS ZC429 from no-reply@acspedycja.pl [2–28h after cesja]
  • Save ZC429 PDF → auto-attach to batch
  • Mark "customs cleared"
  • Cancel clearance clock
  • Start PZC relay clock (8h)
  
  Email: ACS PZC from piotr@acspedycja.pl / logistyka@acspedycja.pl [may arrive 1–16h after AIS]
  • Save PZC + duty awizo attachment
  • Start duty payment clock (72h)

PHASE 3: DHL RELEASE
──────────────────────
  Email: Ganther PZC release to odprawacelna@dhl.com [5–6h after AIS, typically]
  • Mark "shipment released"
  • Cancel PZC relay clock
  • Notify #PZ: Amit can collect

PHASE 4: DUTY PAYMENT
──────────────────────
  Email: Ganther duty notice to account@estrellajewels.eu [same day as clearance]
  • Extract duty amount (PLN)
  • Save nota attachment
  • Post HIGH PRIORITY to #PZ with amount
  • Start 72h → 7-day escalation timers
  
  [Accounts team pays via bank transfer]
  
  Email: Ganther "dzieki, płaci się" in thread
  • Cancel all payment timers
  • Mark "duty paid"

PHASE 5: CLOSURE
──────────────────
  Email: Ganther service invoice to account@estrellajewels.eu [5–10 days]
  • Save invoice attachment
  • Mark "ganther invoice received"
  • Batch status: clearance complete
  
  [Amit picks up from DHL warehouse]
  
  [PZ processing: generate PZ document using ZC429 + invoices]
```

---

## Part C: Exact Trigger Points

| # | Trigger | Watched Mailbox | Expected Timing | SLA |
|---|---------|----------------|-----------------|-----|
| T1 | Cesja email from DHL | info@estrellajewels.eu | Anytime | — |
| T2 | AIS ZC429 notification | info@estrellajewels.eu | 2–28h after T1 | 24h |
| T3 | ACS PZC + duty | info@estrellajewels.eu | ~24h after T1 | 28h |
| T4 | Ganther PZC to DHL | info@estrellajewels.eu | 5–6h after T2 | 8h |
| T5 | Ganther duty notice | account@estrellajewels.eu | ~same day as T3 | — |
| T6 | Ganther payment ack | info@estrellajewels.eu | 1h – 7 days after T5 | 72h |
| T7 | Ganther service invoice | account@estrellajewels.eu | 5–10 days after T6 | 14 days |

---

## Part D: Required System Automations

### D1. Email Monitor Service
**New component:** Background polling service that monitors mailboxes and fires triggers.
- Poll every 15 min (business hours), 30 min (off-hours)
- Connects to: Zoho Mail MCP (connector `mcp__620999a3-8e04-40ac-88f9-184d3824e310`)
- Deduplicates via messageId cache
- For each new email: run through rule engine (TRIGGERS 1–7)

### D2. ZC429 Auto-Attachment
**Enhancement to existing system:** When AIS ZC429 arrives by email, auto-save to batch folder and auto-associate with batch (currently requires manual upload).
- Sender: `no-reply@acspedycja.pl`
- File: first attachment (PDF, ~17KB)
- Target: `outputs/{batch_id}/source/{awb}_ZC429.pdf`
- Action: set `audit.zc429_source = "email_auto"`

### D3. Duty Amount Tracking
**New field in audit.json:**
```json
{
  "duty_amount_pln": 1225,
  "duty_notice_received_at": "2026-04-15T10:07:00Z",
  "duty_paid_signal_at": "2026-04-15T17:29:00Z"
}
```

### D4. Payment Escalation Timer
**New service:** TimerManager that fires Cliq notifications when payment SLA is breached.
- 72h: warning to #PZ
- 7 days: critical alert + email to Amit

### D5. Batch AWB Linking
**Enhancement:** When batch is created from email, link AWB to batch_id so all subsequent
emails for that AWB auto-route to the same batch.
- Store: `batch_index.json` → `{awb: batch_id, ticket: batch_id}`
- Used for: all trigger matching

---

## Part E: SLA Timing Rules

| SLA | Threshold | Action on breach |
|-----|-----------|-----------------|
| Cesja → clearance | 24h | Alert to #PZ + Ganther follow-up draft |
| AIS → Ganther relay | 8h | Alert to #PZ |
| Duty notice → payment | 72h | Alert #PZ + email to Amit |
| Duty notice → payment | 7 days | Critical alert + escalation |
| Clearance → PZ generated | 48h | Reminder to operator |
| Clearance → Ganther invoice | 14 days | Follow-up draft to Ganther |

---

## Part F: Failure Recovery Actions

### Failure: No clearance signal after 24h
```
1. Check if ACS received cesja (confirm forwarding email)
2. Draft: "Hi Greg, can you check status of AWB {awb}? No clearance signal after 24h."
3. Send to: ciagarlak@ganther.com.pl
4. Wait 4h for response
5. If no response: escalate to Amit
```

### Failure: Duty overdue 7+ days
```
1. Check account@estrellajewels.eu for any payment confirmation emails
2. Check if "dzieki, płaci się" email was missed (search Zoho)
3. If payment genuinely not made: notify Amit + Tejal with full duty details
4. Draft escalation email to Ganther for status clarification
```

### Failure: ZC429 not received
```
1. Check if AIS notification went to different folder (spam, archive)
2. If not found: contact Ganther to send ZC429 manually
3. Manual upload path in dashboard remains as fallback
```

### Failure: PZC not received but Ganther released shipment
```
1. This is normal (Ganther acts on AIS, not waiting for ACS PZC)
2. Wait 16h for ACS formal PZC email (backup documentation)
3. If not arrived after 24h: request from piotr@acspedycja.pl
```

---

## Part G: Cowork Coordinator Responsibilities

| Responsibility | Current State | Required Action |
|---------------|--------------|-----------------|
| Monitor cesja emails | ❌ Not implemented | Add email polling |
| Auto-save ZC429 | ❌ Not implemented | Add trigger T2 |
| Track duty amounts | ❌ Not implemented | Add audit field |
| Escalate unpaid duty | ❌ Not implemented | Add timer T5 |
| Link AWB to batch | ❌ Not implemented | Add batch_index |
| DHL follow-up drafts | ⚠️ Partial (manual) | Auto-draft on timeout |
| Agency email drafting | ✅ Implemented | Works correctly |
| DHL description reply | ✅ Implemented | Works correctly |
| Cliq notifications | ✅ Implemented | Works correctly |

---

## Sender Whitelist (Updated)

```python
# v2 — corrected DHL_DSK_SOURCE
TRUSTED_CLEARANCE_SENDERS = {
    "odprawacelna@dhl.com":      "DHL_CESJA",          # sends cesja
    "plwawecs@dhl.com":          "DHL_SPECIAL",         # DHL WAW customs (special cases)
    "no-reply@acspedycja.pl":    "AIS_ZC429",           # ACS automated ZC429
    "piotr@acspedycja.pl":       "ACS_AGENT",           # Piotr Kubsik
    "logistyka@acspedycja.pl":   "ACS_AGENT",           # Bartłomiej Bugaj
    "biuro@acspedycja.pl":       "ACS_OFFICE",
    "roman@acspedycja.pl":       "ACS_AGENT",           # Roman Kałużny
    "ciagarlak@ganther.com.pl":  "GANTHER_COORDINATOR", # Grzegorz Ciągarlak
    "jaworska@ganther.com.pl":   "GANTHER_SECONDARY",
}

# CORRECTED from v1 — administracja_centralna only RECEIVES, never sends
DHL_DSK_SOURCE = ["odprawacelna@dhl.com"]
# administracja_centralna@dhl.com = RECIPIENT only (receives PZC release instructions)

BILLING_SENDERS = [
    "windykacja.DHLexpress@dhl.com",
    "Justyna.CZYNSZ@dhl.com",
]
```
