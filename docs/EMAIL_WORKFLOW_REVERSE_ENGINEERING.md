# Email Workflow Reverse Engineering
## DHL / Customs Agency Clearance — Estrella Jewels Poland
### Source: Zoho Mail analysis, Jan 27 – Apr 27, 2026

---

## 1. Executive Summary

Every high-value DHL shipment to Estrella follows a 9-step email choreography involving
four parties: **DHL**, **Estrella**, **Ganther** (freight forwarder / coordinator), and
**ACS Spedycja** (licensed customs agent).  Ganther acts as the operational hub — they
receive ACS's clearance output and translate it into actionable duty-payment instructions
for Estrella's accounts team.  Estrella never communicates directly with ACS Spedycja.

---

## 2. Parties Identified

| Role | Entity | Key Contacts | Email Addresses |
|------|--------|-------------|-----------------|
| Carrier / Customs initiator | DHL Poland | Anna Was*, Paulina Debowska (cesja); windykacja (billing) | `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`, `plwawecs@dhl.com`, `wawpok@dhl.com` |
| Importer / Payer | Estrella Jewels | Amit Gupta, import team, accounts (Tejal) | `import@estrellajewels.eu`, `account@estrellajewels.eu`, `info@estrellajewels.eu`, `amit@estrellajewels.eu` |
| Freight Forwarder / Coordinator | Ganther Sp. z o.o. | Grzegorz Ciągarlak, Jaworska | `ciagarlak@ganther.com.pl`, `jaworska@ganther.com.pl` |
| Licensed Customs Agent | ACS Spedycja | Piotr Kubsik, Bartłomiej Bugaj, Joanna Bąk, Roman Kałużny | `piotr@acspedycja.pl`, `logistyka@acspedycja.pl`, `biuro@acspedycja.pl`, `roman@acspedycja.pl`, `no-reply@acspedycja.pl` |

---

## 3. Shipments Covered (Jan 27 – Apr 27, 2026)

| # | AWB | DHL Ticket | Approximate Date | Duty (PLN) | Notes |
|---|-----|-----------|-----------------|-----------|-------|
| 1 | 5378819972 | T#1WA2601260000069 | Jan 27, 2026 | ~467 | Earliest in window |
| 2 | 8580992114 | T#1WA2602100000562 | Feb 10, 2026 | — | Bugaj handled |
| 3 | 2759203252 | T#1WA2602160000033 | Feb 16, 2026 | — | — |
| 4 | 3109419880 | T#1WA2602230000068 | Feb 23, 2026 | — | — |
| 5 | 1214569005 | T#1WA2603020000138 | Mar 2, 2026 | — | — |
| 6 | **2824221912** | T#1WA2603100000499 | Mar 10, 2026 | — | **28-day payment delay** |
| 7 | **5180358875** | T#1WA2603080000002 | Mar 8, 2026 | — | **HK trade fair returnee — atypical** |
| 8 | 3369800350 | T#1WA2603160000052 | Mar 16, 2026 | — | — |
| 9 | 8523214840 | T#1WA2604010000228 | Apr 1, 2026 | 1181 | — |
| 10 | 6876258325 | T#1WA2604070000057 | Apr 7, 2026 | 1414 | — |
| 11 | **3283625844** | T#1WA2604140000123 | Apr 14, 2026 | **1225** | Most complete thread |

---

## 4. Standard Clearance Workflow (9 Steps)

### Step 1 — DHL Arrival Notification
**Trigger:** DHL receives shipment at Warsaw customs warehouse.
**What happens:** DHL internally creates ticket `T#1WAxxx`. Sends "Agencja Celna DHL" email.
**Who receives:** `info@estrellajewels.eu` (CC only at this stage).
**Timing:** Within 24–48h of shipment arrival.

### Step 2 — Estrella Replies to DHL (Broker Appointment Letter)
**Trigger:** `import@estrellajewels.eu` receives or anticipates DHL notification.
**What happens:** Sends formal broker appointment letter to DHL.
**Body (translated):** "Dear DHL Poland team, I am writing to inform you that we have appointed our custom clearance broker, Mr. Grzegorz Ciagarlak from Ganther Sp. z o.o., to handle the custom clearance process…"
**To:** `odprawacelna@dhl.com`, `roman@acspedycja.pl`
**CC:** `import@estrellajewels.eu`, `ciagarlak@ganther.com.pl`
**Attachment:** Required customs documents (invoice, proforma, etc.)
**Note:** Sometimes Estrella sends this proactively; sometimes DHL queries for documents first (AWB 5180358875).

### Step 3 — DHL Sends Cesja to ACS
**Trigger:** DHL customs team processes broker appointment.
**What happens:** DHL specialist (Anna Was* / Paulina Debowska) sends cesja (customs authority transfer) documents.
**Body (translated):** "W załączniku przesyłam dokumenty do cesji. Po dokonanej odprawie proszę o przesłanie PZC celem wydania przesyłki do doręczenia. Do wiadomości proszę o załączenie adresu: administracja_centralna@dhl.com"
("I am attaching cesja documents. After clearance, please send the PZC to release the shipment. Please include administracja_centralna@dhl.com in all communications.")
**To:** `roman@acspedycja.pl` (ACS Spedycja)
**CC:** `info@estrellajewels.eu`
**Attachment:** Cesja document + original DHL notification
**Subject pattern:** `Fwd: [T#1WAxxxxxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXX`

### Step 4 — ACS Performs Customs Clearance
**What happens:** ACS Spedycja lodges the customs declaration with Polish customs (AIS system).
**Duration:** Typically 1–5 business days after receiving cesja.
**No email during this step** (internal ACS work).

### Step 5 — AIS/ZC429 Automated Notification
**Trigger:** Polish customs system (AIS) approves the declaration.
**Sender:** `no-reply@acspedycja.pl` (automated from WinSADMS software)
**Subject:** `Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)`
**Body:** "Powiadomienie o dokonanej odprawie importowej (nr MRN: xxPLxxxxx) wysłano programem WinSADMS XX.XX"
**To:** `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`, `import@estrellajewels.eu`, `info@estrellajewels.eu`, `account@estrellajewels.eu`, `ciagarlak@ganther.com.pl`
**CC:** `piotr@acspedycja.pl`
**Attachment:** ZC429 document (PDF, ~17KB)
**Note:** This is the SAD/ZC429 file that feeds the PZ processor.

### Step 6 — ACS Sends PZC + Duty Notice to DHL
**Trigger:** Immediately after AIS clearance (same day).
**What happens:** ACS sends the PZC (release document) directly to DHL and all parties.
**Sender:** `piotr@acspedycja.pl` or `logistyka@acspedycja.pl`
**Body (translated):** "After clearance — I am attaching the PZC and customs duties for payment. Please send back confirmation of payment."
**To:** `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`, Estrella (info/import/account), `ciagarlak@ganther.com.pl`
**CC:** `biuro@acspedycja.pl`, `roman@acspedycja.pl`
**Attachment:** PZC document + duty "awizo" (duty bill)
**Subject pattern:** `Re: Fwd: Fwd: [T#xxxx] - Agencja Celna DHL - przesyłka numer: XXXXXXXXXX`

### Step 7 — Ganther Forwards Duty Amount to Estrella Accounts
**Trigger:** Ganther receives PZC email from ACS (Step 6).
**What happens:** Ganther sends a concise duty payment instruction to `account@estrellajewels.eu`.
**Sender:** `ciagarlak@ganther.com.pl`
**Body pattern (English):** "Good day, Cust Clearance is done, DHL informed to release shipment, pls pay duty as per attached nota. Amount of XXXX PLN"
**To:** `account@estrellajewels.eu`
**CC:** `amit@estrellajewels.eu`
**Attachment:** Nota (duty tax document/invoice from ACS)
**Note:** This is the operational trigger for Estrella's accounts team (Tejal) to make payment.

### Step 8 — Ganther Sends PZC to DHL (Release Instruction)
**Trigger:** Either after duty payment confirmed, or concurrently with Step 7.
**What happens:** Ganther sends separate email to DHL to release the shipment.
**Sender:** `ciagarlak@ganther.com.pl`
**Body pattern (Polish):** "Przesyłka AWB XXXXXXXXXX odprawiona celnie, PZC załączone. Proszę pilnie zwolnić towar, Pan Gupta (w kopii) samodzielnie odbierze przesyłkę z magazynu DHL"
("Shipment AWB XXXXXXXXXX cleared customs, PZC attached. Please urgently release the goods. Mr. Gupta (CC'd) will collect the shipment from DHL warehouse himself.")
**To:** `odprawacelna@dhl.com`, `administracja_centralna@dhl.com`
**CC:** `account@estrellajewels.eu`, `import@estrellajewels.eu`, `amit@estrellajewels.eu`
**Attachment:** PZC document
**Note:** Amit always picks up personally from DHL warehouse. This is stated explicitly in every PZC email.

### Step 9 — Ganther Confirms Payment + Issues Service Invoice
**Trigger:** Estrella's accounts team (Tejal) pays the duty and notifies Ganther.
**What happens (two sub-steps):**
- 9a: Ganther confirms payment: "dzieki, płaci się" (Thanks, it's being paid)
- 9b: Ganther sends their own service invoice to `account@estrellajewels.eu`
**9b subject:** Uses same thread subject as clearance
**9b body:** "Good day, Our invoice is attached, Brgds Greg"

---

## 5. Complete Thread Example — AWB 3283625844 (April 2026)

Timeline reconstructed from email timestamps:

```
Apr 13, 2026 ~11:47 UTC  [STEP 2]  import@estrellajewels.eu → odprawacelna@dhl.com, roman@acspedycja.pl
                                    "Broker appointment letter — Ganther/Ciagarlak"
                                    + attachments (invoice, docs)

Apr 14, 2026 ~13:18 UTC  [STEP 3]  odprawacelna@dhl.com → roman@acspedycja.pl, CC: info@estrellajewels.eu
                                    "Cesja documents for T#1WA2604140000123 / AWB 3283625844"

Apr 15, 2026 ~10:24 UTC  [STEP 5]  no-reply@acspedycja.pl → DHL+Estrella+Ganther, CC: piotr
                                    "AIS ZC429 clearance notification (automated)"

Apr 15, 2026 ~10:27 UTC  [STEP 6]  piotr@acspedycja.pl → DHL+Estrella+Ganther, CC: biuro+roman
                                    "PZC i należności celne do opłaty" + attachment

Apr 15, 2026 ~10:49 UTC  [STEP 7]  ciagarlak@ganther.com.pl → account@estrellajewels.eu, CC: amit
                                    "Clearance done, pay duty 1225 PLN, nota attached"

Apr 15, 2026 ~10:50 UTC  [STEP 8]  ciagarlak@ganther.com.pl → odprawacelna@dhl.com+administracja_centralna
                                    "PZC attached, release shipment, Gupta collects"

Apr 19, 2026 ~11:12 UTC  [STEP 9a] ciagarlak@ganther.com.pl → piotr+DHL+Estrella
                                    "dzieki, płaci się" (payment acknowledged)

Apr 24, 2026 ~11:37 UTC  [STEP 9b] ciagarlak@ganther.com.pl → account@estrellajewels.eu, CC: amit
                                    "Our invoice attached"

Apr 27, 2026              [CLOSE]   info@estrellajewels.eu → ciagarlak@ganther.com.pl (forwarded)
                                    Thread closed
```

**Total elapsed time: ~14 days** (from broker appointment to invoice)
**ACS clearance turnaround: ~24 hours** (cesja Apr 14 → PZC Apr 15)
**Estrella duty payment delay: ~4 days** (duty notice Apr 15 → Ganther confirms Apr 19)

---

## 6. Atypical Case — AWB 5180358875 (HK Trade Fair Returnee)

This shipment was previously **temporarily exported from Poland** to Hong Kong International Jewellery Show and returned. Handling differed:

1. DHL sent ZC429 communication first (no standard cesja flow)
2. Estrella sent detailed explanation: "towary zostały wcześniej czasowo wyeksportowane z Polski na targi" (goods were previously temporarily exported from Poland to trade fair)
3. Multiple DHL queries about commodity description
4. Sent to `plwawecs@dhl.com` (Agencja Celna DHL WAW) + `kontakt.int@dhl.com`
5. DHL requested "performa w tym samym formacie" (proforma in same format) — Amit sent this from `amit@estrellajewels.eu`

**Key difference:** No standard cesja → ACS path. DHL handled clearance internally, with Estrella directly providing documents.

---

## 7. Special Role: Automated AIS Notification

`no-reply@acspedycja.pl` sends an automated notification from WinSADMS (Polish customs software) the moment customs clearance is approved. This email:
- Contains the **MRN number** (e.g., `26PL44302D005LJ4R0`)
- Has the **ZC429/SAD document** attached (~17KB PDF)
- Goes to all parties simultaneously
- Subject always: `Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)`

This is the **most important signal** for the PZ processor — it means the ZC429 file is immediately available as an email attachment.

---

## 8. Key Observations for System Design

1. **Estrella always passive**: Estrella receives but rarely initiates mid-clearance. Only inputs: broker appointment letter (Step 2) and duty payment.

2. **Ganther = Translation Layer**: DHL ↔ ACS Spedycja communicate in Polish/technical customs. Ganther translates ACS output into actionable English duty notices for Estrella.

3. **No payment confirmation trail**: After Estrella's accounts team (Tejal) pays the duty, no payment confirmation email was found in inbox. Confirmation likely sent from `account@estrellajewels.eu` or verbally to Ganther.

4. **Same-day clearance common**: AIS notification and PZC often arrive within minutes of each other. ACS performs clearance rapidly once cesja is received.

5. **Two parallel DHL release paths**: ACS sends PZC to DHL directly (Step 6), AND Ganther sends a separate PZC release email to DHL (Step 8). Both include `administracja_centralna@dhl.com`.

6. **DHL billing is separate**: DHL Express sends service invoices to `info@estrellajewels.eu` via `windykacja.DHLexpress@dhl.com`. This is unrelated to the customs clearance flow. Outstanding: DBP2216003 (66.42 PLN, overdue as of Apr 2026).
