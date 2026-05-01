# CLEARANCE_AUTOMATION_MASTER_BLUEPRINT.md
# Estrella Jewels — Customs Clearance Automation Master Blueprint
# Synthesized from 12-Month Intelligence Analysis
# Generated: 2026-04-27

---

## Philosophy

> "Cowork should first become an intelligence analyst.
> Then it becomes a monitor. Only later it becomes an action assistant."

This blueprint is structured in 3 phases aligned with that philosophy.

**What this blueprint does NOT authorize:**
- Any production code changes
- Any email sending or drafting
- Any configuration activation
- Any live system modification

All implementation items require explicit admin approval before execution.

---

## System State as of Apr 2026

### What Works (Production)
- ✅ PZ processor (invoice + ZC429 → PZC PDF + XLSX)
- ✅ 6 validation checks pass (production readiness confirmed)
- ✅ detect_triggers() with T1–T11 defined
- ✅ suggest_only mode active
- ✅ timeline.log_event() append-only
- ✅ Backfill script for legacy batches
- ✅ Zoho Cliq delivery via Estrella Cliq connector
- ✅ WorkDrive sync + share link generation
- ✅ AWB presence check in all batches

### What's Missing (Confirmed from 12-Month Analysis)
- ❌ Email-based carrier arrival detection
- ❌ ZC429 MRN extraction from AIS notifications
- ❌ FedEx cesja submission monitoring
- ❌ Duty routing gap detection in live email
- ❌ "Płaci się" payment signal detection
- ❌ VAT deferment gap detection
- ❌ Ganther invoice tracking
- ❌ SLA timer per shipment
- ❌ VAT deferment renewal tracking

---

## Phase 1: Intelligence Analyst (Now → 3 months)

**Goal:** System reads inbound emails and builds awareness of clearance state.
Outputs: timeline events, audit field updates, and intelligence reports.
No suggestions or actions. Read-only.

### P1-01: Email Ingestion Layer (Foundation)

Build the core email reader that connects Zoho Mail to the cowork system.

**Architecture:**
```
Zoho Mail (import@, account@) → Email Poller → Event Classifier → Audit Updater
```

**Email Poller:**
- Poll `import@estrellajewels.eu` every 15 minutes
- Poll `account@estrellajewels.eu` every 15 minutes
- Check sender against TRUSTED_CLEARANCE_SENDERS
- Route to appropriate handler

**Event Classifier:**
```python
SENDER_HANDLERS = {
    "odprawacelna@dhl.com":     handle_dhl_arrival,
    "no-reply@acspedycja.pl":   handle_ais_notification,
    "pl-import@fedex.com":      handle_fedex_event,
    "ganther.com.pl":           handle_ganther_email,
    "piotr@acspedycja.pl":      handle_acs_clearance,
    "logistyka@acspedycja.pl":  handle_acs_clearance,
    "roman@acspedycja.pl":      handle_acs_clearance,
    "adrian@acspedycja.pl":     handle_acs_clearance,
    "michal@acspedycja.pl":     handle_acs_clearance,
    "biuro@acspedycja.pl":      handle_acs_billing,  # NOT clearance
}
```

**Approval needed:** Email polling from `import@` and `account@` mailboxes.

---

### P1-02: DHL Arrival Detection

**Handler:** `handle_dhl_arrival(email)`

```python
def handle_dhl_arrival(email):
    # Extract AWB (10-digit number)
    awb = re.search(r'\b(\d{10})\b', email.subject + email.body)
    if not awb:
        return

    # Extract DHL ticket
    ticket = re.search(r'\[T#1WA\d+\]', email.subject)

    # Find or create audit batch for this AWB
    batch = find_batch_by_awb(awb.group(1))
    if batch:
        timeline.log_event(batch, "carrier_arrived", {
            "carrier": "DHL",
            "awb": awb.group(1),
            "dhl_ticket": ticket.group(0) if ticket else None,
            "email_subject": email.subject[:100],
        })
        batch["tracking"]["arrived_warehouse"] = True
        save_audit(batch)
```

**Enables:** T1 (DSK_MISSING) to fire correctly.

---

### P1-03: ZC429 AIS Notification Processing

**Handler:** `handle_ais_notification(email)`

```python
def handle_ais_notification(email):
    for attachment in email.attachments:
        m = re.match(r'ZC429_([A-Z0-9]+)_\d+_PL\.pdf', attachment.name)
        if m:
            mrn = m.group(1)
            # Find batch by AWB (may need to search recent batches)
            timeline.log_event(batch, "sad_uploaded", {
                "mrn": mrn,
                "source": "ais_auto",
                "file": attachment.name,
            })
            batch["zc429_mrn"] = mrn
            save_audit(batch)
```

**Enables:** Automatic MRN→AWB linkage without manual upload.

---

### P1-04: Ganther Email Classifier

**Handler:** `handle_ganther_email(email)`

```python
def handle_ganther_email(email):
    text = email.body.lower()

    # Payment confirmation
    for phrase in PAYMENT_CONFIRMED_PHRASES:
        if phrase.lower() in text:
            log_event("duty_paid_signal_at", ...)
            return

    # Duty notice (has PLN amount)
    pln_match = re.search(r'(\d[\d\s,.]+)\s*PLN', email.body)
    if pln_match:
        amount = parse_pln(pln_match.group(1))
        log_event("duty_notice_received", {"amount_pln": amount})
        batch["duty_amount_pln"] = amount
        batch["duty_notice_received_at"] = email.date
        return

    # VAT deferment warning
    for kw in VAT_DEFERMENT_KEYWORDS:
        if kw.lower() in text:
            log_event("vat_deferment_warning", {"keyword": kw})
            # FIRE VAT_DEFERMENT_GAP alert
            return

    # PZC / clearance notification
    if "pzc" in text or "odprawy" in text or "odprawie" in text:
        log_event("pzc_received", {...})
        return

    # FCA complication
    if "fca" in text and "transport" in text:
        batch["fca_complication"] = True
        log_event("fca_complication_detected", {...})
        return
```

---

### P1-05: FedEx Arrival and Cesja Detection

**Handler:** `handle_fedex_event(email)`

```python
def handle_fedex_event(email):
    text = email.body.lower()

    # Cesja auto-acknowledgment
    if "cesja" in text and "potwierdzenie" in text:
        log_event("cesja_submitted", {"source": "fedex_auto_ack"})
        return

    # DSK issued
    if "dsk" in text and "ganther" in text:
        log_event("dsk_received", {"carrier": "FedEx"})
        return

    # Arrival notification (has AWB)
    awb = re.search(r'\b(\d{12})\b', email.subject + email.body)
    if awb:
        log_event("carrier_arrived", {"carrier": "FedEx", "awb": awb.group(1)})
        # Start 24h cesja countdown
        batch["fedex_arrival_at"] = email.date
        return
```

**Enables:** T3 (FedEx DSK_MISSING) to fire based on cesja countdown.

---

### P1-06: Intelligence Reports (Phase 1 Output)

At end of Phase 1, the system can produce:

1. **Active shipment dashboard:** All AWBs in flight with current clearance state
2. **Duty payment register:** All duty amounts + payment status
3. **Clearance duration log:** Per-AWB days from arrival to release
4. **Actor activity log:** Which ACS agent / Ganther contact handled each shipment

---

## Phase 2: Monitor (Months 3–6)

**Goal:** System produces suggestions and alerts based on observed email state.
Outputs: Cliq suggestions via detect_triggers(). No actions taken.

### P2-01: Enable T1 (DSK_MISSING) in Production

**Prerequisite:** P1-02 (DHL arrival detection) complete.

T1 already defined. Enable with confirmed `arrived_warehouse` source:
```python
# In detect_triggers():
if batch["tracking"].get("arrived_warehouse") and not batch.get("dsk_filename"):
    # Fire T1 — suggest follow-up with ACS
```

---

### P2-02: Enable T2 (DUTY_PAYMENT_PENDING) in Production

**Prerequisite:** P1-04 (Ganther email classifier) complete.

T2 already defined. Enable with confirmed `duty_notice_received_at` source:
```python
if batch.get("duty_notice_received_at") and not batch.get("duty_paid_signal_at"):
    # Fire T2 after configurable hours
```

---

### P2-03: Enable T3 (FedEx DSK_MISSING) in Production

**Prerequisite:** P1-05 (FedEx arrival detection) complete.

T3 already defined. Enable with confirmed FedEx arrival detection:
```python
if batch.get("fedex_arrival_at") and not batch.get("cesja_submitted"):
    if hours_since(batch["fedex_arrival_at"]) > 24:
        # Fire T3 — suggest cesja submission
```

---

### P2-04: Enable T9 (DUTY_ROUTING_GAP) in Production

**Prerequisite:** P1-04 (Ganther email classifier) with routing check.

T9 already defined. Add routing check to Ganther handler:
```python
if has_pln_amount(email) and "account@estrellajewels.eu" not in email.to:
    fire_trigger("DUTY_ROUTING_GAP", detail={"routing": email.to})
```

---

### P2-05: New Trigger — VAT_DEFERMENT_GAP

```python
def detect_vat_deferment_gap(email_body: str) -> bool:
    for kw in VAT_DEFERMENT_KEYWORDS:
        if kw.lower() in email_body.lower():
            return True
    return False
```

Cliq suggestion format:
```
⚠️ VAT DEFERMENT ISSUE DETECTED
AWB: <number>
Ganther flagged: "no permission for VAT Deferment"
Action required: Contact account@estrellajewels.eu to verify VAT deferment status.
Renewal may be needed — contact Polish customs authority.
```

---

### P2-06: Clearance SLA Monitor

```python
def check_clearance_sla(batch: dict) -> list[dict]:
    suggestions = []
    carrier = batch.get("carrier", "DHL")
    arrived_at = batch.get("clearance_start")
    if not arrived_at:
        return suggestions

    days_elapsed = (now() - parse_datetime(arrived_at)).days
    sla_threshold = 5 if carrier == "DHL" else 9

    if days_elapsed > sla_threshold and not batch.get("cargo_released"):
        suggestions.append({
            "trigger": "CLEARANCE_SLA_BREACH",
            "message": f"Clearance for AWB {batch.get('awb')} has exceeded {sla_threshold}-day SLA.",
            "days_elapsed": days_elapsed,
        })
    return suggestions
```

---

## Phase 3: Action Assistant (Months 6+)

**Goal:** System executes specific, pre-approved, reversible actions.
Each action category requires its own approval.

### P3-01: ZC429 Auto-Upload to PZ Processor

**Action:** When ZC429 AIS notification received for a known AWB → auto-upload attachment
to PZ processor batch.

**Approval gate:** AWB must be confirmed in audit. Batch must be in draft state.
User sees: "ZC429 ready to upload for AWB 1234567890 — confirm?"

---

### P3-02: Duty Payment Reminder to Accounts

**Action:** When T2 fires → send formatted message to `account@estrellajewels.eu`:
"Duty payment required for AWB <number>: <amount> PLN. Ganther invoice attached."

**Approval gate:** Message content reviewed before send. Amount confirmed from audit.

---

### P3-03: FedEx Cesja Submission Reminder

**Action:** When T3 fires → send reminder to `import@estrellajewels.eu`:
"Please submit cesja form to pl-import@fedex.com for FedEx AWB <number>."

**Note:** Claude does NOT submit the form — only sends reminder to Tejal.

---

### P3-04: Ganther Invoice Register

**Action:** Maintain a live Ganther invoice register. Log each invoice when received.
Alert if unpaid after 14 days.

**Output:** Monthly reconciliation report: AWB → invoice → amount → paid/unpaid.

---

## Clearance Trigger State Machine

### DHL Shipment — Full State Diagram

```
[AWAITING_ARRIVAL]
    → carrier_arrived event received
[AWAITING_DSK]       ← T1 fires if >24h here
    → dsk_received event OR ACS PZC email
[AWAITING_PZC]
    → pzc_received event OR Ganther clearance email
[AWAITING_DUTY]      ← T2 fires if >24h here
    → duty_paid_signal_at set from "płaci się"
[AWAITING_RELEASE]
    → cargo_released event
[COMPLETE]
```

### FedEx Shipment — Full State Diagram

```
[AWAITING_ARRIVAL]
    → carrier_arrived event (from pl-import@fedex.com)
[AWAITING_CESJA]     ← T3 fires if >24h here
    → cesja_submitted event (FedEx auto-ack)
[AWAITING_DSK]
    → dsk_received event (FedEx issues DSK to Ganther)
[AWAITING_PZC]
    → pzc_received event
[AWAITING_DUTY]      ← T2 fires if >24h here
    → duty_paid_signal_at
[AWAITING_RELEASE]
    → cargo_released event
[COMPLETE]
```

---

## Implementation Checklist (For Future Approval)

### Phase 1 Prerequisites
- [ ] Admin approval for email polling from import@ and account@
- [ ] Zoho Mail API token with read access to import@ + account@
- [ ] Email poller deployed as background service
- [ ] DHL arrival handler (P1-02) implemented and tested
- [ ] ZC429 AIS handler (P1-03) implemented and tested
- [ ] Ganther email classifier (P1-04) implemented and tested
- [ ] FedEx arrival handler (P1-05) implemented and tested

### Phase 2 Prerequisites
- [ ] All Phase 1 items complete
- [ ] T1 validated with real DHL arrival data
- [ ] T2 validated with real Ganther duty email data
- [ ] T3 validated with real FedEx arrival data
- [ ] T9 validated with real Ganther routing data
- [ ] VAT_DEFERMENT_GAP trigger implemented and tested
- [ ] Clearance SLA monitor implemented and tested

### Phase 3 Prerequisites
- [ ] All Phase 2 items complete + 3 months stability observation
- [ ] Explicit admin approval for each action category (P3-01 through P3-04)
- [ ] Error handling and rollback for all action steps
- [ ] Human confirmation gate implemented for all actions

---

## Approved Configuration Additions (From Task E — Pending Admin Sign-off)

These config additions were proposed in Task E and are ready for approval:

### TRUSTED_CLEARANCE_SENDERS (additions)
```python
TRUSTED_CLEARANCE_SENDERS = [
    # DHL
    "odprawacelna@dhl.com",
    "administracja_centralna@dhl.com",
    # ACS Spedycja — all 6 agents
    "piotr@acspedycja.pl",
    "logistyka@acspedycja.pl",
    "roman@acspedycja.pl",
    "adrian@acspedycja.pl",
    "michal@acspedycja.pl",     # ← NEW (Task E + confirmed Jun 2024)
    "no-reply@acspedycja.pl",   # ← NEW (ZC429 AIS — extract only, no action trigger)
    # Ganther
    "ganther.com.pl",
    "jaworska@ganther.com.pl",
    "krzysztof.suchodola@ganther.com.pl",
    # FedEx
    "pl-import@fedex.com",      # ← NEW (Task E)
]

DO_NOT_TRIGGER = [
    "biuro@acspedycja.pl",
    "accounts@gjlindia.com",
    "dyszynska@abf-biurorachunkowe.pl",
    "Zaneta.Nagat@fedex.com",
    "DataRWA@fedex.com",
    "poland@fedex.com",
    "kaushal@estrellajewelsllp.com",  # ← NEW (12-month discovery)
]
```

**Approval gate:** These additions require admin review and sign-off before activation.
See `EMAIL_ROUTING_UPDATE_PROPOSAL_EXPANDED.md` Section 7 for full approval gate.

---

## Evidence Base

This blueprint is derived from:
- **35+ DHL AWBs** analyzed over 12 months (Jun 2024–Apr 2026)
- **3 FedEx inbound AWBs** analyzed (Aug 2025–Feb 2026)
- **8 parallel email searches** totaling 230+ emails examined
- **6 ACS agents** identified (up from 1 in original config)
- **3 Ganther contacts** identified
- **7 DHL cesja staff** identified
- **4 FedEx contacts** identified
- **2 confirmed clearance delays** root-caused (VAT deferment + routing gap)
- **1 confirmed near-miss** analyzed (FedEx cesja delay)
- **21 duty amounts** extracted and catalogued (31,667 PLN total)
- **9 MRN→AWB mappings** confirmed from AIS notifications

All findings are read-only. No production data was modified.

---

*Blueprint complete. All implementation items require explicit admin approval.*
*This document is the synthesis output of Task F — 1-Year Customs Intelligence Analysis.*
