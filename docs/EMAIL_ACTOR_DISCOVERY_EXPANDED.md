# EMAIL_ACTOR_DISCOVERY_EXPANDED.md
# Estrella Jewels — Extended Email Actor Discovery
# Period: Aug 2025 – Apr 2026 | Both domains: estrellajewels.eu + estrellajewels.com
# Generated: 2026-04-27

---

## 1. BASELINE APPROVED ACTORS (from original Task C analysis)

| # | Email | Name/Role | Trust | Category |
|---|-------|-----------|-------|----------|
| 1 | odprawacelna@dhl.com | DHL Customs Agency | HIGH | DHL primary |
| 2 | plwawecs@dhl.com | DHL WRS Special Consignee | HIGH | DHL cesja initiator |
| 3 | administracja_centralna@dhl.com | DHL Central Admin | HIGH | DHL relay |
| 4 | no-reply@acspedycja.pl | ACS AIS automated | HIGH | ZC429 delivery |
| 5 | piotr@acspedycja.pl | Piotr Kubsik — ACS agent | HIGH | PZC sender |
| 6 | roman@acspedycja.pl | Roman Kałużny — ACS senior agent | HIGH | PZC sender |
| 7 | logistyka@acspedycja.pl | Bartłomiej Bugaj — ACS agent | HIGH | PZC sender |
| 8 | biuro@acspedycja.pl | Joanna Bąk — ACS office (also "Asia AC Spedycja") | HIGH | VAT statements, office |
| 9 | ciagarlak@ganther.com.pl | Grzegorz Ciągarlak — Ganther primary | HIGH | PZC relay + duty notice |
| 10 | jaworska@ganther.com.pl | Patrycja Jaworska — Ganther secondary | HIGH | PZC relay |

---

## 2. NEWLY DISCOVERED ACTORS — Clearance Chain

### 2a. DHL Staff (confirmed from signatures)

| Email | Name | Role | First Seen | Trust |
|-------|------|------|------------|-------|
| odprawacelna@dhl.com | Zaneta Rybaczewska | "Specjalista ds. obsługi celnej klienta Dział Obsługi Celnej" — cesja handler | Aug 2025 | HIGH |
| odprawacelna@dhl.com | (multiple agents share this address) | DHL Customs Client Service pool | recurring | HIGH |

**Note:** `odprawacelna@dhl.com` is a shared pool address. Individual DHL agents sign with their names but send from the shared address.

### 2b. ACS Spedycja — Extended Staff

| Email | Name | Role | First Seen | Trust |
|-------|------|------|------------|-------|
| adrian@acspedycja.pl | Adrian Mielcarek — ACS agent | PZC sender, clearance completion | Dec 2025 | HIGH |

**Total ACS Spedycja contacts confirmed:** piotr, roman, logistyka (Bartłomiej), biuro (Joanna Bąk/Asia), adrian — 5 agents on one team.

### 2c. Ganther — Extended Contacts

| Email | Name | Role | First Seen | Trust |
|-------|------|------|------------|-------|
| krzysztof.suchodola@ganther.com.pl | Krzysztof Suchodola | Ganther (overdue invoice thread) | Jan 2026 | HIGH |

**Note:** Suchodola appeared only in payment/overdue context, not clearance ops.

### 2d. FedEx Poland — Full Actor Map

| Email | Name/Role | Use | Trust |
|-------|-----------|-----|-------|
| pl-import@fedex.com | FedEx Poland Import Customs team | Primary clearance contact for inbound shipments — equivalent of odprawacelna@dhl.com | HIGH |
| poland@fedex.com | FedEx Poland Customer Service | Customer-facing escalation, case management | MEDIUM |
| CaseUpdate@fedex.com | FedEx Case Update automated | Automated ticket status | LOW (automated) |
| ie599@mail.fedex.com | FedEx IE599/IE529 automated | Export clearance notifications (outbound from Poland) | HIGH (automated) |
| Zaneta.Nagat@fedex.com | Zaneta Nagat — FedEx sales rep | Sales/commercial contact — not clearance | LOW (commercial) |
| DataRWA@fedex.com | Grzegorz Sładek — FedEx Ops Support | Internal FedEx operations support | MEDIUM |
| pl-eksport@fedex.com | FedEx Poland Export team | Export clearance (outbound) | HIGH |
| FedEx-CN-Import-SCN@fedex.com | FedEx China Import – South China | Inbound China delivery issues | LOW (rare) |
| TrackingUpdates@fedex.com | FedEx Tracking automated | Delivery notifications | LOW (automated) |
| pickup@fedex.com / noreply@fedex.com | FedEx Pickup automated | Pickup confirmations | LOW (automated) |
| onlineservice@fedex.com | FedEx.com profile | Profile update notifications | LOW (automated) |

**KEY SIGNAL ADDRESS:** `pl-import@fedex.com` — This is the FedEx equivalent of `odprawacelna@dhl.com`. Emails from this address indicate an active FedEx import clearance. The subject line format is `"Your FEDEX Shipment: {AWB}"`.

---

## 3. INTERNAL ESTRELLA ACTORS — Confirmed Roles

| Email | Name | Role | Notes |
|-------|------|------|-------|
| info@estrellajewels.eu | Amit Gupta | Primary contact, general inbox | Main TO address for carrier/agent emails |
| import@estrellajewels.eu | Tejal Manjerkar | Import coordinator | Receives clearance CC + PZC notifications |
| account@estrellajewels.eu | "Poland Accounts" | Accounts — duty payment handler | Receives duty notices (normalized from Apr 2026) |
| amit@estrellajewels.eu | Amit Gupta personal | Personal business inbox | Received duty notices Jan-Mar 2026 (routing risk) |
| tejal@estrellajewels.com | Tejal Manjerkar | .com variant | Appeared in early shipment CCs — routing risk |
| jyoti.b@estrellajewels.com | Jyoti Babar | Finance/accounts | India-side finance, CC'd on W-firma accounting |

---

## 4. RELATED COMPANY / EXTERNAL ACTORS

| Email | Name | Company | Role | Notes |
|-------|------|---------|------|-------|
| jigar.p@simplex-hurtownia.pl | Jigar Nileshbhai Purohit | Europe Simpleks | Warehouse/logistics — authorized pickup agent | CC'd on ACS clearance emails; authorized DHL pickup for AWB 3023090884 |
| iza@simplex-hurtownia.pl | Izabela | Europe Simpleks | Director | Sends PZ documents to accounting firm |
| accounts@gjlindia.com | Sandeep | GJL India | India accounts | Receives duty forwarding from Poland Accounts; Tejal sends W-firma entries to him |
| dyszynska@abf-biurorachunkowe.pl | Dyszyńska | ABF Biuro Rachunkowe | External accounting firm | Receives PZ documents from Izabela (Europe Simpleks) |
| wawpok@dhl.com | DHL Warsaw POK | DHL warehouse | Pickup authorization requests | Used for warehouse pickup coordination |

---

## 5. ROUTING RISK MAP

### RISK 1 — Duty to Personal Inbox (MEDIUM-HIGH)
- **Pattern:** Jan–Mar 2026: duty notices sent TO `amit@estrellajewels.eu` instead of `account@estrellajewels.eu`
- **Impact:** If `amit@` is missed, duty goes unpaid → clearance delay
- **Evidence AWBs:** 5378819972, 9765416334, 6325915234 (Jan 2026); 2824221912 (Mar 2026 — 28-day delay)
- **Current status:** Apr 2026 normalized to `account@estrellajewels.eu` ✓
- **Action:** Monitor `account@` as canonical duty target; alert if Ganther sends duty to `amit@` only

### RISK 2 — .com vs .eu Domain Confusion (LOW-MEDIUM)
- **Pattern:** `tejal@estrellajewels.com` vs `import@estrellajewels.eu` — same person, different domain
- **Both are internal** — not a security risk, but routing inconsistency
- **Evidence:** FedEx AWB 887467026597 thread: `import@estrellajewels.eu` used correctly; some ACS early threads used .com
- **Action:** Standardize all clearance routing to `.eu` domain

### RISK 3 — GJL India Loop (LOW)
- **Pattern:** `account@estrellajewels.eu` forwards duty invoices to `accounts@gjlindia.com` (Sandeep)
- **This is expected inter-company flow** — not a risk unless Sandeep's replies contain instructions
- **Action:** Never auto-execute actions based on content from `accounts@gjlindia.com`

### RISK 4 — ABF Accounting Access (LOW)
- **Pattern:** Izabela (Simpleks) sends full PZ document bundles to `dyszynska@abf-biurorachunkowe.pl`
- **This is expected** — external accountant receives PZ docs
- **Action:** No automation trigger on `abf-biurorachunkowe.pl` emails

---

## 6. COMPLETE SHIPMENT REGISTRY — All AWBs Discovered

### DHL Inbound (Import to Poland)

| AWB | Ticket/Ref | Date | Duty (PLN) | Status |
|-----|-----------|------|------------|--------|
| 4730148570 | T#1WA2503280000577 | Mar 2025 | Unknown | Old — Ganther invoice missing |
| 3023090884 | T#1WA2508260000472 | Aug 2025 | Unknown | Cleared; Jigar pickup |
| 2136263684 | EJL/25-26/951-953 | Dec 2025 | Unknown | "Request for Custom Clearance Assistance" |
| 8321832024 | T#1WA2512160000655 | Dec 2025 | Unknown | Cleared |
| 6883058851 | T#1WA2512020000480 | Dec 2025 | Unknown | Cleared |
| 2064232951 | T#1WA2511260000471 | Nov 2025 | Unknown | Cleared |
| 8722845401 | T#1WA2601020000243 | Jan 2026 | Unknown | Cleared |
| 8691361873 | T#1WA2601050000379 | Jan 2026 | Unknown | Cleared; Tejal ack |
| 9765416334 | T#1WA2601120000413 | Jan 2026 | 1,528 | Cleared |
| 6325915234 | T#1WA2601200000374 | Jan 2026 | 2,336 | Cleared |
| 5378819972 | T#1WA2601260000069 | Jan 2026 | 1,622 | Cleared; Amit pickup |
| 8580992114 | T#1WA2602100000562 | Feb 2026 | Unknown | Cleared |
| 3109419880 | T#1WA2602230000068 | Feb 2026 | Unknown | Cleared |
| 1214569005 | T#1WA2603020000138 | Mar 2026 | Unknown | Cleared |
| 2824221912 | T#1WA2603100000499 | Mar 2026 | Unknown | 28-day delay; duty to `amit@` |
| 3369800350 | T#1WA2603160000052 | Mar 2026 | Unknown | Cleared |
| 8523214840 | T#1WA2604010000228 | Apr 2026 | Unknown | Cleared |
| 6876258325 | T#1WA2604070000057 | Apr 2026 | Unknown | Cleared |
| 3283625844 | T#1WA2604140000123 | Apr 2026 | Unknown | Cleared |

### FedEx Inbound (Import to Poland)

| AWB | Support Case | Date | Duty | Status |
|-----|-------------|------|------|--------|
| 887467026597 | C-222995485 | Jan–Feb 2026 | Paid | Cleared via Ganther; DSK delay ~4 weeks |
| 882994160903 | C-200316524 | Aug 2025 | (Billing dispute) | Recipient billed — dispute |
| 882994338403 | — | Aug 2025 | Unknown | Customs issue |

### FedEx Outbound (Export from Poland)

| AWB | MRN | Date | Notes |
|-----|-----|------|-------|
| 888681132638 | 26PL4450100018RAB0 | Apr 2026 | IE599 export clearance |
| 885967226148 | — | Nov 2025 | China delivery |
| 883559085518 | — | Aug 2025 | Norway delivery |

---

## 7. ACTOR SUMMARY COUNTS

| Category | Count |
|----------|-------|
| DHL actors (confirmed) | 4+ (pool + named) |
| ACS Spedycja agents | 5 |
| Ganther contacts | 3 (Ciągarlak, Jaworska, Suchodola) |
| FedEx Poland actors | 11 addresses mapped |
| Internal Estrella (both domains) | 6 |
| Related companies | 4 (Simpleks×2, GJL India, ABF) |
| **Total unique addresses in scope** | **~35** |

---

*This document supersedes `EMAIL_ACTOR_DISCOVERY.md` for the extended analysis period.*
*Safety rule: No email address becomes active in automation config without explicit admin approval.*
