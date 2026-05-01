# DHL / Agency Email Pattern Map
## Signal Detection Rules for Automated Monitoring
### Source: Reverse engineering of 11 shipments, Jan–Apr 2026

---

## Overview

Each email type in the clearance workflow has a distinct and detectable pattern.
This map provides exact matching rules (sender, subject, body keywords, attachments)
for each email type, enabling automated classification and action triggering.

---

## Email Type Catalog

### TYPE 1: DHL_ARRIVAL_NOTIFICATION

**What it is:** DHL informs Estrella that a shipment has arrived and is pending customs.

**Sender patterns:**
- `odprawacelna@dhl.com`
- `plwawecs@dhl.com` (WAW DHL customs office, used for special cases)

**Subject patterns:**
```
[T#1WAxxxxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
Agencja Celna DHL – prosimy o odpowiedź do przesyłki o numerze: XXXXXXXXXXX
```

**Body keywords:** `Agencja Celna DHL`, `przesyłka numer`, `T#1WA`

**AWB extraction:** From subject — digits after "przesyłka numer: "
**Ticket extraction:** From subject — `T#1WA` followed by digits

**Attachments:** Sometimes; often just notification text

**Action:** Triggers Step 2 (Estrella should send broker appointment letter if not already sent)

**Distinguishing feature:** Subject contains `T#1WA` ticket number. Always from DHL address.

---

### TYPE 2: ESTRELLA_BROKER_APPOINTMENT

**What it is:** Estrella formally appoints Ganther as customs broker to DHL.
Sent from `import@estrellajewels.eu`.

**Sender:** `import@estrellajewels.eu`

**Subject pattern:**
```
Re:T#1WAxxxxxxxxxx - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
```

**Body keywords:** `custom clearance broker`, `Grzegorz Ciagarlak`, `Ganther`, `appointed`

**Key body phrase (detected):**
"I am writing to inform you that we have appointed our custom clearance broker"

**Attachments:** Customs documents (invoice, proforma) — `has:attachment`

**To:** `odprawacelna@dhl.com`, `roman@acspedycja.pl`
**CC:** `import@estrellajewels.eu`, `ciagarlak@ganther.com.pl`

---

### TYPE 3: DHL_CESJA_FORWARD

**What it is:** DHL transfers customs authority (cesja) to ACS Spedycja.
Sent from `odprawacelna@dhl.com` directly to `roman@acspedycja.pl`.
Estrella is CC'd on `info@estrellajewels.eu`.

**Sender:** `odprawacelna@dhl.com`

**Subject pattern:**
```
Fwd: [T#1WAxxxxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
```

**Body keywords (Polish):** `cesja`, `dokumenty do cesji`, `PZC`, `administracja_centralna@dhl.com`

**Key body phrase:**
"W załączniku przesyłam dokumenty do cesji. Po dokonanej odprawie proszę o przesłanie PZC"

**To:** `roman@acspedycja.pl`
**CC:** `info@estrellajewels.eu`
**Attachments:** Cesja document + DHL original notification (always has attachment)

**Distinguishing feature:** Subject starts with `Fwd:` (not `Re:`). Sender is DHL. Recipient is ACS.

---

### TYPE 4: AIS_ZC429_CLEARANCE_NOTIFICATION

**What it is:** Automated notification from Polish customs system (AIS/WinSADMS) confirming
that customs clearance has been granted. Contains the ZC429 document.

**Sender:** `no-reply@acspedycja.pl`

**Subject (exact):**
```
Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)
```

**Body pattern:**
"Powiadomienie o dokonanej odprawie importowej (nr MRN: xxPLxxxxxxxxx) wysłano programem WinSADMS XX.XX"

**MRN extraction:** Regex `\(nr MRN: ([A-Z0-9]+)\)`

**To:** `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`, `import@estrellajewels.eu`,
         `info@estrellajewels.eu`, `account@estrellajewels.eu`, `ciagarlak@ganther.com.pl`
**CC:** `piotr@acspedycja.pl`
**Attachment:** ZC429 PDF (~17KB)

**Distinguishing feature:** Sender is `no-reply@acspedycja.pl`, subject is exact and static.
This is the **most reliable automated clearance signal**.

---

### TYPE 5: ACS_PZC_AND_DUTY_NOTICE

**What it is:** ACS Spedycja sends the PZC (customs release document) and duty notice
to DHL and all parties. This is the operational completion signal.

**Sender patterns:**
- `piotr@acspedycja.pl` (Piotr Kubsik — primary)
- `logistyka@acspedycja.pl` (Bartłomiej Bugaj — also used)

**Subject pattern:**
```
Re: Fwd: Fwd: [T#1WAxxxxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
Re: Fwd: Fwd: [T#1WAxxxxxxxxxx] Re:- Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
```

**Body (Polish):**
"Po odprawie - w załączniku przesyłam PZC i należności celne do opłaty. Proszę o zwrotne przesłanie potwierdzenia wpłaty."
OR
"Dzień dobry, towar po odprawie. W załączniku przesyłam PZC oraz awizo na powstałe należności."

**Body keywords:** `PZC`, `należności celne`, `potwierdzenia wpłaty`, `odprawie`

**To:** `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`, Estrella (info/import/account), `ciagarlak@ganther.com.pl`
**CC:** `biuro@acspedycja.pl`, `roman@acspedycja.pl`
**Attachments:** PZC document + "awizo należności" (duty bill) — always `has:attachment`

**Distinguishing feature:** Subject has double `Fwd: Fwd:`. Sender is ACS (`@acspedycja.pl`).

---

### TYPE 6: GANTHER_DUTY_PAYMENT_REQUEST

**What it is:** Ganther summarises the duty amount and instructs Estrella's accounts (Tejal) to pay.
This is the **primary action trigger for Estrella's accounts team**.

**Sender:** `ciagarlak@ganther.com.pl`

**Subject pattern:**
```
FW: Fwd: Fwd: [T#1WAxxxxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
FW: Fwd: Fwd: [T#1WAxxxxxxxxxx] Re:- Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
```

**Body (English, concise):**
"Good day, Cust Clearance is done, DHL informed to release shipment, pls pay duty as per attached nota. Amount of XXXX PLN"
OR
"Hi Tejal pls pay duty to the shipment XXXXXXXXXX as per attached nota, XXXX PLN"
OR
"Dear Tejal Pls kindly pay duty to the shipment XXXXXXXXXX as per attached nota. Amount XXXX PLN."

**Duty amount extraction:** Regex `(\d+[\s,.]?\d*)\s*PLN`

**To:** `account@estrellajewels.eu`
**CC:** `amit@estrellajewels.eu`
**Attachments:** Nota (duty tax invoice) — always `has:attachment`

**Distinguishing feature:** Subject has `FW:` (capital, Outlook-style). Recipient is `account@estrellajewels.eu`.
Body always contains duty amount in PLN.

---

### TYPE 7: GANTHER_PZC_RELEASE_TO_DHL

**What it is:** Ganther sends PZC document directly to DHL to formally request shipment release.
This is Ganther's authorization for DHL to hand over the goods.

**Sender:** `ciagarlak@ganther.com.pl`

**Subject pattern:**
```
FW: Fwd: Fwd: [T#1WAxxxxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
RE: T#1WAxxxxxxxxxx - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
FW: FW: [T#1WAxxxxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXXX
```

**Body (Polish):**
"Przesyłka AWB XXXXXXXXXX odprawiona celnie, PZC załączone. Proszę pilnie zwolnić towar, Pan Gupta (w kopii) samodzielnie odbierze przesyłkę z magazynu DHL"
OR
"Przesyłka o numerze AWB XXXXXXXXXX just odprawiona celnie PZC zalaczone. Proszę pilnie zwolnić towar"

**Body keywords:** `odprawiona celnie`, `PZC`, `zwolnić towar`, `Gupta`, `magazynu DHL`

**To:** `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`
**CC:** `account@estrellajewels.eu`, `import@estrellajewels.eu`, `amit@estrellajewels.eu`
**Attachments:** PZC document — always `has:attachment`
**Priority:** Often set to `important` (priority 2)

**Distinguishing feature:** To field contains **only** DHL addresses (no ACS). Body mentions Gupta collecting.

---

### TYPE 8: GANTHER_PAYMENT_ACKNOWLEDGMENT

**What it is:** Ganther confirms to ACS/DHL thread that Estrella has paid the duty.

**Sender:** `ciagarlak@ganther.com.pl`

**Body (Polish):**
"dzieki, płaci się" (Thanks, it's being paid / payment in progress)
OR
"Dziekuje Panie Piotrze płaci się"
OR
"Panie Piotrze dzieki, placi sie"

**Body keywords:** `płaci się`, `dzieki`

**No attachment** (payment acknowledgment only)

**Distinguishing feature:** Very short body. Polish. Same thread as clearance. No attachment.

---

### TYPE 9: GANTHER_SERVICE_INVOICE

**What it is:** Ganther sends their own service fee invoice to Estrella after clearance.

**Sender:** `ciagarlak@ganther.com.pl`

**Body (English):**
"Good day, Our invoice is attached, Brgds Greg"
OR
"Dear Tejal, Inv to the shipment is attached, Brgds Greg"

**To:** `account@estrellajewels.eu`
**CC:** `amit@estrellajewels.eu`
**Attachments:** PDF invoice — `has:attachment`

**Timing:** Typically 5–10 days after clearance

---

### TYPE 10: DHL_BILLING_DUNNING (Unrelated to Clearance)

**What it is:** DHL Express billing department chasing overdue service invoices.
Completely separate from customs clearance process.

**Sender:** `windykacja.DHLexpress@dhl.com`, `Justyna.CZYNSZ@dhl.com`

**Subject patterns:**
```
DHL - 07 - WEZWANIE DO ZAPŁATY - XXXXXXXXXX
DHL - 07 - PONOWNE WEZWANIE - XXXXXXXXXX
DHL Express – planowana blokada konta XXXXXXXXXX
```

**Action:** Send to DHL billing folder. Do NOT treat as customs event.
**Body keywords:** `wezwanie do zapłaty`, `blokada konta`, `zaległych faktur`

---

## Detection Matrix

| Email Type | Primary Sender | Subject Contains | Body Contains | Has Attachment | Priority |
|------------|---------------|-----------------|---------------|---------------|---------|
| DHL_ARRIVAL | `odprawacelna@dhl.com` | `T#1WA`, `Agencja Celna DHL` | `przesyłka numer` | Sometimes | Normal |
| ESTRELLA_BROKER | `import@estrellajewels.eu` | `Re:T#1WA` | `appointed`, `Ganther` | Yes | Normal |
| DHL_CESJA | `odprawacelna@dhl.com` | `Fwd: [T#1WA` | `cesja`, `PZC` | Yes | Normal |
| AIS_ZC429 | `no-reply@acspedycja.pl` | `Powiadomienie AIS` | `MRN`, `WinSADMS` | Yes (ZC429) | Normal |
| ACS_PZC | `*@acspedycja.pl` | `Re: Fwd: Fwd:` | `PZC`, `należności` | Yes | Normal |
| GANTHER_DUTY | `ciagarlak@ganther.com.pl` | `FW: Fwd: Fwd:` | `pay duty`, `PLN`, `nota` | Yes | Normal/Important |
| GANTHER_PZC | `ciagarlak@ganther.com.pl` | `FW:`/`RE: T#` | `odprawiona celnie`, `Gupta` | Yes | Important |
| GANTHER_PAYMENT_ACK | `ciagarlak@ganther.com.pl` | `RE: Fwd: Fwd:` | `płaci się` | No | Normal |
| GANTHER_INVOICE | `ciagarlak@ganther.com.pl` | `RE: Fwd:` | `invoice`, `attached` | Yes | Normal |
| DHL_BILLING | `windykacja@dhl`/`Justyna.CZYNSZ` | `WEZWANIE`/`blokada` | `zaległych faktur` | Sometimes | Normal |

---

## AWB Extraction Rules

From email subjects — two patterns:
```
Pattern A: "przesyłka numer: (\d{10,12})"
Pattern B: "numer: (\d{10,12})"
```

From email bodies:
```
Pattern C: "AWB[:\s]+(\d{10,12})"
Pattern D: "AWB (\d{2}\s\d{4}\s\d{4})"  (FedEx format with spaces)
```

---

## Duty Amount Extraction

From GANTHER_DUTY emails body:
```
Pattern: "(\d{3,5})\s*PLN"
         "Amount of (\d{3,5}) PLN"
         "Amount (\d{3,5}) PLN"
         "(\d{3,5}) PLN"
```

Observed range: 467–2050 PLN (Jan–Apr 2026)

---

## Thread ID Tracing

All emails about the same shipment share a DHL ticket reference: `T#1WAxxxxxxxxxx`.
This appears in subject lines throughout the thread and can be used to link all emails
in a shipment's lifecycle together regardless of the email direction or sender.

```
Thread key = T#1WAxxxxxxxxxx  (extracted from subject)
AWB = digits after "przesyłka numer: "
```
