# FEDEX_CLEARANCE_WORKFLOW_MAP.md
# FedEx Import Clearance Workflow — Estrella Jewels Poland
# Evidence base: AWB 887467026597 (Jan–Feb 2026), AWB 882994160903 (Aug 2025)
# Generated: 2026-04-27

---

## Overview

FedEx import clearance into Poland uses the same Ganther broker and DSK/cesja mechanism as DHL,
but the handshake sequence differs. The key distinction: FedEx requires explicit "cession of rights"
(cesja praw) via a formal form submitted to `pl-import@fedex.com` before Ganther can act.

---

## Stage-by-Stage Flow

### Stage 1 — FedEx Arrival Notification
**Trigger:** Shipment arrives at FedEx Poland warehouse (Zdrojowa 9, Wypędy, Raszyn).
**Actor:** `pl-import@fedex.com` (FedEx Poland Import Customs)
**Sends to:** `info@estrellajewels.eu` + `import@estrellajewels.eu`
**Subject format:** `"Your FEDEX Shipment: {AWB}"`
**Content:** Customs clearance required. Documents needed. Send to pl-import@fedex.com.
**Also sends:** `"Odprawa celna – brak faktury od Nadawcy"` if invoice missing.

**Email evidence:**
```
From: pl-import@fedex.com
Subject: Your FEDEX Shipment: 887467026597
"Twoja przesyłka FedEx podlega odprawie celnej oraz opłatom celno-podatkowym.
 Uzupełnij brakujące informacje i prześlij dokumenty niezbędne do sprawnego przebiegu
 odprawy celnej na adres pl-import@fedex.com"
```

---

### Stage 2 — Cesja / DSK Request
**Trigger:** FedEx sends cesja form to Estrella.
**Actor:** `pl-import@fedex.com` (Kamil Romanowski signed)
**Sends to:** `amit@estrellajewels.eu` + `roman@acspedycja.pl` + `ciagarlak@ganther.com.pl`
**Content:** Cesja application form attached. Required before broker can act.

**Email evidence:**
```
From: pl-import@fedex.com (Romanowski Kamil)
"Witam. W celu dokonania cesji wymagany jest załączony wniosek."
```

Simultaneously or shortly after, Ganther asks Estrella:
```
From: ciagarlak@ganther.com.pl
"Good day Mr Gupta. Have you asked Fedex for Cession of rights? We need DSK?"
```

---

### Stage 3 — Cesja / DSK Delivery
**Actor:** Estrella (Amit/import@) submits completed cesja form to `pl-import@fedex.com`.
**DSK document sent:** via email to `pl-import@fedex.com`.

FedEx acknowledges receipt:
```
From: pl-import@fedex.com
Subject: Automatyczna odpowiedź
"Dziękujemy za przesłane dokumenty dotyczące bieżącej odprawy celnej."
```

**DSK delivery to Ganther:**
```
From: pl-import@fedex.com
Subject: ODP: [EXTERNAL] RE: Your FEDEX Shipment: 887467026597
"Dzień dobry, DSK w załączeniu"
To: ciagarlak@ganther.com.pl, import@estrellajewels.eu
CC: info@estrellajewels.eu
```

---

### Stage 4 — CIF / Transport Invoice Resolution (if FCA terms)
**Trigger:** If invoice shows FCA (Free Carrier) terms, Ganther cannot declare CIF without transport cost.
**Actor:** Ganther (Ciągarlak)
**Asks:** Estrella for transport invoice

**Email evidence:**
```
From: ciagarlak@ganther.com.pl
"Good day Mr Gupta. Terms of Delivery on commercial invoice is FCA Hong Kong.
 Do you have transport invoice to the shipment? Or do you know transport amount?"
```

**Resolution:** Estrella provides transport invoices. For AWB 887467026597, there were 2 invoices
(original sea freight + revised air freight charges). Ganther adds both to CIF value.

```
From: ciagarlak@ganther.com.pl
"Good day Mr Gupta. Noted with thanks, it is clear now. We are making import clearance
 adding transport cost (2 invoices) to value of goods."
```

---

### Stage 5 — Clearance in Progress
**Actor:** Ganther
**Asks FedEx** (when DSK delayed):
```
From: ciagarlak@ganther.com.pl
To: import@estrellajewels.eu, pl-import@fedex.com
"Good day Dear FedEx – when DSK will be available to the shipment to make import clearance?"
```

**Status confirmed received:**
```
From: ciagarlak@ganther.com.pl
"Dziekuje, przesyłka w odprawie"
```

---

### Stage 6 — Import Clearance Complete — PZC to FedEx
**Actor:** Ganther (Ciągarlak)
**Sends to:** `pl-import@fedex.com` TO + `import@estrellajewels.eu` TO
**CC:** `info@estrellajewels.eu`
**Attachment:** PZC (Potwierdzenie Zgłoszenia Celnego)
**Content (Polish):** "Przesyłka odprawiona celnie, PZC załączone. Proszę zwolnić towar i dostarczyć do firmy Estrella."
**Content (English):** "Import Customs Clearance done, PZC is attached. FedEx informed to release shipment and deliver to Estrella."

**Email evidence:**
```
From: ciagarlak@ganther.com.pl
To: pl-import@fedex.com, import@estrellajewels.eu
CC: info@estrellajewels.eu
Subject: RE: [EXTERNAL] RE: Your FEDEX Shipment: 887467026597
"Dzień dobry. Przesyłka odprawiona celnie, PZC załączone.
 Proszę zwolnić towar i dostarczyć do firmy Estrella."
```

---

### Stage 7 — FedEx Releases Shipment
**Actor:** `poland@fedex.com` (FedEx customer service)
**Sends to:** `info@estrellajewels.eu`
**Content:** Delivery address + warehouse contact ("I will send disposition to the warehouse")

---

### Stage 8 — Ganther Duty + Invoice to Estrella
**Actor:** Ganther (Ciągarlak)
**Sends to:** `amit@estrellajewels.eu` (or `account@estrellajewels.eu`)
**CC:** `account@estrellajewels.eu`
**Content:** Clearance done. Duty amount X PLN. Ganther invoice attached.

---

## Timing Reference (AWB 887467026597)

| Event | Date | Days elapsed |
|-------|------|-------------|
| FedEx first notification (`Your FEDEX Shipment: 887467026597`) | ~Jan 23, 2026 | Day 0 |
| Cesja form sent by FedEx to Amit/Roman/Ganther | ~Jan 23, 2026 | Day 0 |
| Ganther asks "Have you asked FedEx for Cession?" | Jan 26, 2026 | Day 3 |
| FedEx auto-ack of cesja docs | Jan 27, 2026 | Day 4 |
| DSK delivered to Ganther | Jan 28, 2026 | Day 5 |
| Ganther: "przesyłka w odprawie" (in clearance) | Jan 28, 2026 | Day 5 |
| Ganther sends PZC to FedEx + requests release | Jan 29, 2026 | Day 6 |
| Ganther notifies Amit: clearance done | Jan 29, 2026 | Day 6 |
| FedEx warehouse address provided | Feb 1, 2026 | Day 9 |
| Support ticket updates (automated) | Jan 25–27, 2026 | ongoing |

**Total FedEx clearance time (from notification to release): ~6–9 days**
*(DHL clearance is typically 3–5 days — FedEx is slower due to cesja form requirements)*

---

## DSK Delay Pattern

For AWB 887467026597, the DSK wait was approximately 3-4 days.
Ganther's standard message during wait:
```
"Dear Mr Gupta. Noted with thanks, it is enough at this stage.
 If anything will be needed yet, I let you know.
 We are waiting for DSK to Clear the shipment."
```

**Automation implication:** A `DSK_MISSING` trigger should fire after 24 hours without DSK confirmation
for FedEx shipments (same as DHL), but the threshold may need to be 48 hours given the longer baseline.

---

## FedEx-Specific Email Addresses for Monitoring

| Address | Purpose | Monitor for |
|---------|---------|-------------|
| `pl-import@fedex.com` | FedEx customs clearance | Inbound: new clearance request |
| `poland@fedex.com` | FedEx customer service | Escalations, warehouse releases |
| `CaseUpdate@fedex.com` | Automated case updates | Subject contains AWB — ticket tracking |
| `ie599@mail.fedex.com` | Export IE599/IE529 | Outbound export completion |
| `pl-eksport@fedex.com` | FedEx export team | Export clearance |

---

## Key Differences: FedEx vs DHL

| Aspect | DHL | FedEx |
|--------|-----|-------|
| Customs agency trigger address | odprawacelna@dhl.com | pl-import@fedex.com |
| Subject format | `[T#1WA{ref}] - Agencja Celna DHL - przesyłka numer: {AWB}` | `Your FEDEX Shipment: {AWB}` |
| Cesja mechanism | DHL cesja form → ACS Spedycja | FedEx cesja form → Ganther directly |
| Who handles clearance | ACS Spedycja (primary) + Ganther (relay/duty) | Ganther (directly) |
| CIF terms handling | ACS verifies; Ganther notifies duty | Ganther asks for transport invoice if FCA |
| PZC delivery | ACS → DHL CC Ganther CC Estrella | Ganther → FedEx CC import@estrellajewels.eu |
| Typical clearance time | 3–5 days | 6–9 days |
| Support ticket system | DHL Ticket# in subject | FedEx Case# (C-XXXXXXXXX) |

---

## Billing Risk — FedEx Duty-to-Recipient

AWB 882994160903 (Aug 2025): FedEx charged the recipient (not sender) for customs + duties because
the shipment was created with "recipient pays" setting.

```
From: poland@fedex.com
"Good Morning. Referring to the telephone conversation, I would like to inform you that
 when creating the shipment 882994160903, you selected that the recipient would pay for
 customs duties and taxes, therefore Fedex charged the recipient for the cost."
```

**Implication:** Always verify shipment creation settings. Inbound shipments from India should
have importer (Estrella Poland) as duty payer.

---

*Evidence fully confirmed from email thread analysis. No synthetic data.*
