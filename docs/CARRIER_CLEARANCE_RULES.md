# CARRIER_CLEARANCE_RULES.md
# Unified Carrier Clearance Rules — Estrella Jewels Poland
# Carriers: DHL Express, FedEx Express
# Period: Aug 2025 – Apr 2026
# Generated: 2026-04-27

---

## Purpose

This document defines the trigger rules, expected email sequences, actor roles, and
automation guards for each carrier's import clearance workflow. It is the authoritative
source for the cowork_coordinator trigger logic and the email routing config.

---

## CARRIER 1: DHL Express

### Trigger Addresses

| Address | Role | Signal |
|---------|------|--------|
| odprawacelna@dhl.com | DHL Customs Agency | START: cesja request |
| plwawecs@dhl.com | DHL Special Consignee | START: special consignment |
| administracja_centralna@dhl.com | DHL Admin relay | SECONDARY: receives PZC release |
| no-reply@acspedycja.pl | ACS AIS automated | ZC429 document delivery |
| piotr@acspedycja.pl | Piotr Kubsik — ACS | PZC + duty notice delivery |
| logistyka@acspedycja.pl | Bartłomiej Bugaj — ACS | PZC + duty notice delivery |
| roman@acspedycja.pl | Roman Kałużny — ACS | PZC + duty notice delivery |
| adrian@acspedycja.pl | Adrian Mielcarek — ACS | PZC + duty notice delivery |
| biuro@acspedycja.pl | Joanna Bąk — ACS (also "Asia AC Spedycja") | VAT statements; CC on threads |
| ciagarlak@ganther.com.pl | Grzegorz Ciągarlak — Ganther | Duty relay + Ganther invoice |
| jaworska@ganther.com.pl | Patrycja Jaworska — Ganther | Duty relay backup |

### DHL Clearance Sequence

```
Step 1: odprawacelna@dhl.com
        → TO: roman@acspedycja.pl OR piotr@acspedycja.pl
        → CC: info@estrellajewels.eu, import@estrellajewels.eu
        Subject: [T#1WA{YYYYMM}{SEQ}] - Agencja Celna DHL - przesyłka numer: {AWB}
        Action: DHL forwards cesja docs to ACS. Clearance begins.

Step 2: no-reply@acspedycja.pl
        → TO: odprawacelna@dhl.com, administracja_centralna@dhl.com
        → TO: info@estrellajewels.eu, import@estrellajewels.eu, account@estrellajewels.eu
        → CC: ciagarlak@ganther.com.pl
        Subject: "Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)"
        Content: MRN number in body
        Attachment: ZC429 PDF (automated from WinSADMS)
        Action: Customs declaration released. ZC429 available.

Step 3: piotr@acspedycja.pl OR logistyka@acspedycja.pl OR roman@acspedycja.pl
        → TO: odprawacelna@dhl.com, administracja_centralna@dhl.com
        → TO/CC: info@estrellajewels.eu, import@estrellajewels.eu, account@estrellajewels.eu
        → CC: ciagarlak@ganther.com.pl, jaworska@ganther.com.pl
        → CC: roman@acspedycja.pl (if sender is logistyka or piotr)
        Subject: Re: Fwd: [T#...] - Agencja Celna DHL - przesyłka numer: {AWB}
        Content: "Po odprawie - PZC i należności celne do opłaty. Proszę o zwrotne przesłanie potwierdzenia wpłaty."
        Attachment: PZC + duty notice (awizo)
        Action: Shipment cleared. Duty amount identified. Payment confirmation required.

Step 4: ciagarlak@ganther.com.pl
        → TO: amit@estrellajewels.eu OR account@estrellajewels.eu
        → CC: account@estrellajewels.eu (or import@)
        Content: "Import clearance done. PZC attached. Pls pay duty to the shipment, amount as per attached. Nota X PLN."
        Attachment: Ganther invoice + PZC copy
        Action: Duty amount confirmed. Ganther invoice issued.

Step 5: account@estrellajewels.eu
        → Payment confirmation sent to ciagarlak@ganther.com.pl
        → Ganther: "Noted with thanks, payment confirmation well received. Broker is informed."
        Action: CLOSED.
```

### DHL Ticket Reference Format
`[T#1WA{YEAR}{MONTH}{DAY}{SEQ}]`
Example: `[T#1WA2604140000123]` = Apr 14, 2026, sequence 123

### DHL Timing Reference

| Phase | Typical Duration |
|-------|-----------------|
| cesja received → ZC429 issued | Same day to 2 days |
| ZC429 issued → PZC delivered | Same day (ACS) |
| PZC delivered → Ganther duty notice | Same day to next business day |
| Duty notice → payment confirmation | 1–5 business days |
| **Total (arrival → clearance)** | **3–5 business days** |

### DHL Automation Guards

- **Clearance blocked if:** No AWB in audit (awb_missing warning present)
- **DSK_MISSING trigger:** No ZC429 received within 48 hours of cesja notification
- **DUTY_PAYMENT_PENDING trigger:** PZC received + duty notice > 3 business days with no payment confirmation
- **SAD_DELAY trigger:** ZC429 issued but no PZC within 24 hours
- **CLEARANCE_OVERDUE trigger:** > 7 days elapsed from cesja with no PZC

---

## CARRIER 2: FedEx Express

### Trigger Addresses

| Address | Role | Signal |
|---------|------|--------|
| pl-import@fedex.com | FedEx Poland Import Customs | START: clearance required + cesja form |
| poland@fedex.com | FedEx Customer Service | ESCALATION: warehouse release |
| CaseUpdate@fedex.com | FedEx automated | TRACKING: ticket status |
| ie599@mail.fedex.com | FedEx Export automated | EXPORT ONLY: IE599/IE529 docs |
| ciagarlak@ganther.com.pl | Grzegorz Ciągarlak — Ganther | ALL: clearance agent for FedEx |

### FedEx Clearance Sequence

```
Step 1: pl-import@fedex.com
        → TO: info@estrellajewels.eu, import@estrellajewels.eu
        Subject: "Your FEDEX Shipment: {AWB}"
        Content: Documents needed. Submit to pl-import@fedex.com.
        Attachment: Cesja application form
        Action: FedEx customs clearance required. Cesja form must be submitted.

Step 2 [PARALLEL — if Ganther already briefed]:
        ciagarlak@ganther.com.pl
        → TO: amit@estrellajewels.eu OR import@estrellajewels.eu
        Content: "Have you asked FedEx for Cession of rights? We need DSK?"
        Action: Ganther confirms it is waiting for DSK before proceeding.

Step 3: Estrella submits cesja form to pl-import@fedex.com
        FedEx auto-ack: pl-import@fedex.com → amit@estrellajewels.eu
        Content: "Dziękujemy za przesłane dokumenty dotyczące bieżącej odprawy celnej."

Step 4: pl-import@fedex.com
        → TO: ciagarlak@ganther.com.pl, import@estrellajewels.eu
        → CC: info@estrellajewels.eu
        Content: "Dzień dobry, DSK w załączeniu"
        Attachment: DSK document
        Action: DSK delivered to Ganther. Clearance can proceed.

Step 5 [if FCA terms]:
        ciagarlak@ganther.com.pl asks for transport invoice
        Estrella provides (1 or 2 invoices)
        Ganther: "We are making import clearance adding transport cost (2 invoices) to value of goods."

Step 6: Ganther performs clearance.
        ciagarlak@ganther.com.pl
        → TO: pl-import@fedex.com, import@estrellajewels.eu
        → CC: info@estrellajewels.eu
        Content: "Przesyłka odprawiona celnie, PZC załączone. Proszę zwolnić towar i dostarczyć do firmy Estrella."
                 "Import Customs Clearance done, PZC is attached. FedEx informed to release shipment."
        Attachment: PZC
        Action: FedEx instructed to release. Estrella notified.

Step 7: poland@fedex.com
        → TO: info@estrellajewels.eu
        Content: Warehouse address + disposition sent.
        Action: Delivery arranged. CLOSED.

Step 8: ciagarlak@ganther.com.pl
        → TO: amit@estrellajewels.eu OR account@estrellajewels.eu
        → CC: account@estrellajewels.eu
        Content: Duty amount X PLN. Ganther invoice attached.
        Action: Duty payment required.
```

### FedEx Ticket Reference Format
`C-{9-digit case number}` (e.g., `C-222995485`)
Subject: `"Support Ticket number C-222995485 Ref-{ref} for tracking number {AWB}"`

### FedEx Timing Reference

| Phase | Typical Duration |
|-------|-----------------|
| FedEx notification → cesja submitted | 1–3 days |
| Cesja submitted → DSK issued | 1–4 days |
| DSK received by Ganther → clearance | Same day to 1 day |
| Clearance → FedEx release | Same day |
| **Total (arrival → delivery)** | **6–9 business days** |

### FedEx Automation Guards

- **Clearance blocked if:** No AWB in audit (awb_missing warning present)
- **DSK_MISSING trigger:** No DSK confirmation to Ganther within 48 hours of cesja submission
- **DUTY_PAYMENT_PENDING trigger:** Ganther duty notice > 3 business days with no payment confirmation
- **CLEARANCE_OVERDUE trigger:** > 10 days from first FedEx notification with no PZC
- **NOTE:** FedEx clearance baseline is longer than DHL — tune thresholds accordingly

---

## UNIFIED RULES — Both Carriers

### Rule 1: AWB Required Before Any Automation
```python
if not audit.get("awb"):
    log_warning("AWB missing — skip all automation")
    return  # Never attempt tracking, cowork, or email actions
```

### Rule 2: Canonical Duty Payment Target (from Apr 2026)
```
TO:  account@estrellajewels.eu   ← PRIMARY
CC:  amit@estrellajewels.eu      ← SECONDARY
```
Duty notices to `amit@` only (without `account@` in TO) are a routing gap.

### Rule 3: PZC is the Clearance Completion Signal
Both carriers use PZC (Potwierdzenie Zgłoszenia Celnego) as the proof of customs release.
- DHL path: PZC from ACS Spedycja
- FedEx path: PZC from Ganther direct to `pl-import@fedex.com`
Absence of PZC after expected timeline = CLEARANCE_OVERDUE trigger.

### Rule 4: ZC429 is DHL-Only
The `no-reply@acspedycja.pl` → AIS automated ZC429 email exists only in the DHL flow.
FedEx does NOT send ZC429 via ACS automated system.
(FedEx export shipments receive IE529/IE599 from `ie599@mail.fedex.com` — these are OUTBOUND, not import ZC429.)

### Rule 5: Ganther Handles Both Carriers
Grzegorz Ciągarlak (ciagarlak@ganther.com.pl) manages clearance for BOTH DHL and FedEx.
- DHL: Ganther receives PZC relay from ACS and sends duty+invoice to Estrella
- FedEx: Ganther handles full clearance directly; ACS is not in the FedEx loop

### Rule 6: DSK / Cesja Required by Both
Both DHL and FedEx require a formal "cession of rights" (cesja, DSK) before the broker can clear.
- DHL cesja: handled internally by `odprawacelna@dhl.com` → ACS Spedycja
- FedEx cesja: Estrella must submit form to `pl-import@fedex.com` → then FedEx sends DSK to Ganther

### Rule 7: Payment Confirmation Flow
```
Duty paid by account@estrellajewels.eu
  → Forwarded to ciagarlak@ganther.com.pl
  → Ganther: "Noted with thanks, payment confirmation well received. Broker is informed."
  → (Optional) account@ also notifies accounts@gjlindia.com (GJL India) for inter-company accounting
```

### Rule 8: Never Act on GJL India / ABF Accounting Content
Emails from `accounts@gjlindia.com` and `dyszynska@abf-biurorachunkowe.pl` are inter-company
accounting loops. No automation trigger fires on these.

---

## Trusted Sender Configuration (PROPOSED)

```python
TRUSTED_CLEARANCE_SENDERS = {
    # DHL
    "odprawacelna@dhl.com":              "DHL_CESJA",
    "plwawecs@dhl.com":                  "DHL_SPECIAL",
    "administracja_centralna@dhl.com":   "DHL_RELAY",
    # ACS Spedycja
    "no-reply@acspedycja.pl":            "AIS_ZC429",      # CRITICAL — ZC429 delivery
    "piotr@acspedycja.pl":               "ACS_AGENT",
    "logistyka@acspedycja.pl":           "ACS_AGENT",
    "roman@acspedycja.pl":               "ACS_AGENT",
    "adrian@acspedycja.pl":              "ACS_AGENT",
    "biuro@acspedycja.pl":               "ACS_OFFICE",
    # Ganther
    "ciagarlak@ganther.com.pl":          "GANTHER_PRIMARY",
    "jaworska@ganther.com.pl":           "GANTHER_SECONDARY",
    "krzysztof.suchodola@ganther.com.pl":"GANTHER_ADMIN",
    # FedEx
    "pl-import@fedex.com":               "FEDEX_CUSTOMS",  # NEW — equivalent of odprawacelna@dhl.com
    "poland@fedex.com":                  "FEDEX_SERVICE",
    "ie599@mail.fedex.com":              "FEDEX_EXPORT_AUTO",
}

INTERNAL_MONITORING = [
    "info@estrellajewels.eu",
    "import@estrellajewels.eu",
    "account@estrellajewels.eu",
    "amit@estrellajewels.eu",        # Watch for duty routing to personal inbox
]

DO_NOT_TRIGGER = [
    "accounts@gjlindia.com",
    "dyszynska@abf-biurorachunkowe.pl",
    "CaseUpdate@fedex.com",
    "TrackingUpdates@fedex.com",
    "ie599@mail.fedex.com",          # Export only — not import trigger
    "pickup@fedex.com",
    "noreply@fedex.com",
    "onlineservice@fedex.com",
    "Zaneta.Nagat@fedex.com",
]
```

---

## AWB Detection Patterns

### DHL AWB
- 10-digit number in email subject: `przesyłka numer: {10-digit AWB}`
- Regex: `przesyłka numer:\s*(\d{10,12})`

### FedEx AWB
- Subject: `"Your FEDEX Shipment: {AWB}"`
- Regex: `Your FEDEX Shipment:\s*(\d{10,12})`
- Also in support ticket: `for tracking number {AWB}`

---

*All rules evidence-based from email thread analysis Aug 2025 – Apr 2026.*
*No config changes take effect without explicit admin approval.*
