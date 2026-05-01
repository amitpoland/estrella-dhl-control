# Email Actor Discovery
## All Email Addresses Found Across 11 Clearance Shipments
### Source: From/To/CC/Reply-To headers + body signatures + forwarded headers
### Coverage: Jan 27 – Apr 27, 2026 | AWBs: 5378819972, 8580992114, 2759203252, 3109419880, 1214569005, 2824221912, 5180358875, 3369800350, 8523214840, 6876258325, 3283625844

---

## Section 1: Pre-Approved Addresses (Baseline — Known Before This Audit)

These were in the system config before this analysis:

| Address | Role | Domain | Config Key |
|---------|------|--------|-----------|
| `odprawacelna@dhl.com` | DHL customs operations shared mailbox — sends cesja | dhl.com | `DHL_DSK_SOURCE` (corrected in v2) |
| `administracja_centralna@dhl.com` | DHL admin — RECEIVES PZC release instructions | dhl.com | `DHL_DSK_RECIPIENT` |
| `piotr@acspedycja.pl` | Piotr Kubsik, ACS Spedycja agent | acspedycja.pl | `AGENCY_SENDERS` |
| `biuro@acspedycja.pl` | ACS Spedycja office | acspedycja.pl | `AGENCY_SENDERS` |
| `roman@acspedycja.pl` | Roman Kałużny, ACS Spedycja agent | acspedycja.pl | `AGENCY_SENDERS` |
| `ciagarlak@ganther.com.pl` | Grzegorz Ciągarlak, Ganther coordinator | ganther.com.pl | `FORWARDER_SENDERS` |
| `info@estrellajewels.eu` | Estrella general inbox (CC on clearance) | estrellajewels.eu | `INTERNAL_MAILBOXES` |
| `import@estrellajewels.eu` | Estrella import/operations inbox (Tejal) | estrellajewels.eu | `INTERNAL_MAILBOXES` |
| `account@estrellajewels.eu` | Estrella accounts inbox (duty payments) | estrellajewels.eu | `INTERNAL_MAILBOXES` |

---

## Section 2: Newly Discovered Addresses — Full Classification

### 2A. ACS Spedycja (Agency)

| # | Address | Person | Discovery Source | Trust Level | Evidence |
|---|---------|--------|-----------------|-------------|----------|
| A1 | `logistyka@acspedycja.pl` | Bartłomiej Bugaj, ACS logistics | From field — sent PZC for AWB 8580992114 (Feb 13) and AWB 8523214840 (Apr 2) | `candidate_agency` — HIGH CONFIDENCE | Full PZC emails sent with attachments; identified as backup handler when Piotr is unavailable |
| A2 | `no-reply@acspedycja.pl` | ACS AIS automation (WinSADMS system) | From field — sent ZC429 notification for AWB 1214569005 and AWB 2824221912 | `candidate_agency` — CONFIRMED AUTOMATED | Subject exact: "Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)"; never sends human messages; automation only |

### 2B. DHL (Carrier)

| # | Address | Person / Role | Discovery Source | Trust Level | Evidence |
|---|---------|--------------|-----------------|-------------|----------|
| B1 | `plwawecs@dhl.com` | DHL WAW Customs Office (special cases) | To/From field — AWB 5180358875 (HK returnee), atypical case | `candidate_dhl` — MEDIUM CONFIDENCE | Different team from odprawacelna; handles exceptional cases (temporary export returns, trade fair goods) |
| B2 | `kontakt.int@dhl.com` | DHL International contact | To field — AWB 5180358875 thread | `unknown` — LOW CONFIDENCE | Appears once in HK returnee thread only; unclear if operational or complaint channel |
| B3 | `wawpok@dhl.com` | DHL WAW POK (warehouse?) | To field — AWB 5180358875, proforma query | `unknown` — LOW CONFIDENCE | Appears once; may be DHL WAW warehouse/pickup operations; not seen in standard clearance flow |
| B4 | `Iwona.Sosnowska-Zdunowska@dhl.com` | Iwona Sosnowska-Zdunowska, DHL supervisor — head of customs team | Body signature — appears in ALL cesja emails as feedback link | `candidate_dhl` — MEDIUM CONFIDENCE | Signature text: "Zachęcam do podzielenia się opinią na temat obsługi celnej — Iwona Sosnowska-Zdunowska"; not a sender; escalation contact for DHL service issues |
| B5 | `windykacja.DHLexpress@dhl.com` | DHL Express collections / dunning | From field — billing dunning emails | `approved_billing` — CONFIRMED | Known billing sender; already in `BILLING_SENDERS` list per v2 rules |
| B6 | `Justyna.CZYNSZ@dhl.com` | Justyna Czynsz, DHL billing specialist | From field — billing/dunning emails | `approved_billing` — CONFIRMED | Named billing individual; already in `BILLING_SENDERS` list per v2 rules |
| B7 | `pl.dhlexp.iod@dhl.com` | DHL Poland Data Protection Officer (IOD = Inspektor Ochrony Danych) | Body legal footer — appears in ALL DHL emails | `ignore` — REGULATORY ONLY | Standard GDPR footer; DPO contact; never operational; not relevant to clearance workflow |

### 2C. Ganther (Customs Forwarder)

| # | Address | Person | Discovery Source | Trust Level | Evidence |
|---|---------|--------|-----------------|-------------|----------|
| C1 | `jaworska@ganther.com.pl` | Jaworska (first name unknown), Ganther secondary contact | CC field — appears as CC in Ganther correspondence | `candidate_forwarder` — MEDIUM CONFIDENCE | Always CC, never From; Ganther backup contact; no solo emails observed |

### 2D. Estrella Internal

| # | Address | Person | Discovery Source | Trust Level | Evidence |
|---|---------|--------|-----------------|-------------|----------|
| D1 | `amit@estrellajewels.eu` | Amit Gupta, Estrella owner | From/CC field — appears in escalation emails, broker appointment (AWB 3283625844), urgent follow-up (AWB 2824221912) | `approved_existing` — INTERNAL | Confirmed internal actor; AWB 2824221912 shows duty notice incorrectly routed here — monitoring should normalize to `account@estrellajewels.eu` |
| D2 | `tejal@estrellajewels.com` | Tejal (accounts) — .com domain variant | To field — Ganther duty notices addressed here in some shipments | `candidate_internal` — CONFIRMED REAL | Ganther used `.com` domain variant (`estrellajewels.com`) for Tejal; search confirmed 0 outbound from this address; `.eu` domain is canonical; **ROUTING RISK**: duty notices may go unmonitored if sent only to `.com` variant |
| D3 | `privacy@estrellajewels.com` | Estrella privacy/data contact | Body footer — appears in Estrella-sent emails | `ignore` — COMPLIANCE ONLY | Legal/GDPR footer contact; not operational for clearance |
| D4 | `it@estrellajewels.com` | Estrella IT | Body footer — appears in Estrella-sent emails | `ignore` — INTERNAL INFRASTRUCTURE | IT support contact in email footer; not relevant to clearance monitoring |

### 2E. External Third Parties

| # | Address | Person / Company | Discovery Source | Trust Level | Evidence |
|---|---------|-----------------|-----------------|-------------|----------|
| E1 | `jigar.p@simplex-hurtownia.pl` | Jigar P., Europe Simpleks / simplex-hurtownia.pl | CC field — AWB 1214569005 thread | `candidate_internal` — MEDIUM CONFIDENCE | simplex-hurtownia.pl is a related Estrella entity; Jigar was CC'd on an ACS customs notification; likely warehouse or related business affiliate |
| E2 | `portalklienta@kuke.com.pl` | KUKE portal (Korporacja Ubezpieczeń Kredytów Eksportowych) — Polish export credit insurer | From field — insurance notifications | `ignore` — UNRELATED | KUKE is trade credit insurance; no role in customs clearance; auto-notifications only |

---

## Section 3: DHL Staff Identified (Not Email Addresses — Signature Only)

These individuals sign emails sent FROM `odprawacelna@dhl.com`. Their personal DHL email addresses were NOT exposed in any email.

| Person | Title | Observed in AWBs |
|--------|-------|-----------------|
| **Anna Wasacz** | Specjalista ds. obsługi celnej klienta, Dział Obsługi Celnej Klienta | 3283625844 (Apr 14) |
| **Paulina Debowska** | Specjalista ds. obsługi celnej klienta, Dział Obsługi Celnej Klienta | 8523214840 (Apr 1) |
| **Andrzej Strzelec** | Starszy specjalista ds. obsługi celnej klienta (Senior) | 2824221912 (Mar 12) |

All three work through the shared `odprawacelna@dhl.com` mailbox. Their personal addresses are not operationally relevant — replies go to the shared mailbox.

---

## Section 4: ACS Staff Identified (Via Email Senders)

| Person | Address | Title (inferred) | Role |
|--------|---------|-----------------|------|
| **Piotr Kubsik** | `piotr@acspedycja.pl` | Primary agent | Sends PZC + duty notices; main ACS contact |
| **Bartłomiej Bugaj** | `logistyka@acspedycja.pl` | Logistics (backup) | Sends PZC when Piotr is unavailable |
| **Roman Kałużny** | `roman@acspedycja.pl` | Receives cesja from DHL | Primary cesja recipient at ACS |

---

## Section 5: Complete Actor Count Summary

| Category | New Addresses Found | Already Known | Total Actors |
|----------|--------------------:|-------------:|-------------:|
| DHL (carrier) | 5 new (B1–B5) + 2 billing (B5–B6 known) | 2 | 7 |
| ACS Spedycja | 2 new (A1–A2) | 3 | 5 |
| Ganther | 1 new (C1) | 1 | 2 |
| Estrella internal | 1 new functional (D2) + 2 ignore (D3–D4) | 3 + D1 | 7 |
| External 3rd party | 2 (E1–E2) | 0 | 2 |
| **Total** | **13 new discovered** | **9 pre-known** | **22** |

---

## Section 6: Address Routing Risk Map

### RISK: Duty notices reaching wrong mailbox

| Shipment | Duty Notice Sent To | Should Go To | Risk |
|----------|--------------------|-----------|----|
| AWB 2824221912 | `amit@estrellajewels.eu` | `account@estrellajewels.eu` | 28-day payment delay — root cause confirmed |
| Some shipments | `tejal@estrellajewels.com` (`.com` domain) | `account@estrellajewels.eu` | If `.com` mailbox not monitored = SILENT MISS |

### RISK: ACS backup sender not in approved list

`logistyka@acspedycja.pl` (Bartłomiej Bugaj) sends real PZC emails with attachments. Not in current approved sender list. If email monitoring is deployed, his emails will be missed or classified as unknown.

### RISK: ZC429 automation sender not in approved list

`no-reply@acspedycja.pl` is the AIS ZC429 automation sender — the highest-value signal in the entire clearance pipeline. Not in approved sender list for the deployed system.

---

## Appendix: All Discovered Addresses (Flat List)

```
# ACS Spedycja
logistyka@acspedycja.pl          → Bartłomiej Bugaj (backup agent)
no-reply@acspedycja.pl           → ACS AIS automation (ZC429)

# DHL
plwawecs@dhl.com                 → DHL WAW special customs (atypical cases)
kontakt.int@dhl.com              → DHL International (once only, HK case)
wawpok@dhl.com                   → DHL WAW POK/warehouse (once only, HK case)
Iwona.Sosnowska-Zdunowska@dhl.com → DHL supervisor (signature only, no operational role)
windykacja.DHLexpress@dhl.com    → DHL billing dunning (already known)
Justyna.CZYNSZ@dhl.com          → DHL billing (already known)
pl.dhlexp.iod@dhl.com           → DHL Data Protection Officer (legal footer, ignore)

# Ganther
jaworska@ganther.com.pl          → Ganther secondary (CC only)

# Estrella
amit@estrellajewels.eu           → Amit Gupta (internal, owner)
tejal@estrellajewels.com         → Tejal accounts (.com variant — ROUTING RISK)
privacy@estrellajewels.com       → Privacy footer (ignore)
it@estrellajewels.com           → IT footer (ignore)

# External
jigar.p@simplex-hurtownia.pl    → Jigar P., related entity
portalklienta@kuke.com.pl       → KUKE insurance portal (ignore)
```
