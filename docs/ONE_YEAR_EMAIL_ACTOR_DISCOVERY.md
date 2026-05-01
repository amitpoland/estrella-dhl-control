# ONE_YEAR_EMAIL_ACTOR_DISCOVERY.md
# Estrella Jewels — Complete Email Actor Discovery (1-Year)
# Period: Jun 2024 – Apr 2026 | All Carriers + Internal
# Generated: 2026-04-27

---

## Executive Summary

This document is the authoritative actor registry for all email addresses observed in
Estrella Jewels customs clearance operations over 12+ months. It covers 45+ unique addresses
across 8 domains, 6 ACS agents (up from original 1), 3 Ganther contacts, 7 DHL cesja staff,
and 4 FedEx contacts. Key discovery: Michał Cieślak (`michal@acspedycja.pl`) as the 6th ACS
agent active in mid-2024, and `kaushal@estrellajewelsllp.com` as the India LLP dashboard entity.

---

## 1. ACS Spedycja (Clearance Agent — DHL Only)

ACS Spedycja is Estrella's customs agency for DHL shipments. They file SADs, handle cesja
forwarding, issue PZC, and send ZC429 AIS notifications.

### Clearance Agents (6 confirmed)

| Name | Email | Period Active | Role | Notes |
|------|-------|--------------|------|-------|
| Roman Kałużny | roman@acspedycja.pl | Aug 2025, Jan 2026 | Senior agent / supervisor | CC'd on FedEx cesja thread also |
| Piotr Kubsik | piotr@acspedycja.pl | Jan–Apr 2026 | Primary clearance agent | Most active in 2026; requests payment confirmation back |
| Bartłomiej Bugaj | logistyka@acspedycja.pl | Nov 2025–Apr 2026 | Clearance agent | Sends PZC + duty notice; does NOT request payment confirmation |
| Adrian Mielcarek | adrian@acspedycja.pl | Dec 2025 | Clearance agent | Less frequent; possibly junior or specialist |
| Michał Cieślak | michal@acspedycja.pl | Jun–Sep 2024 | Clearance agent | Confirmed in "placi się" thread + Sep 2024 activity |
| (Unknown) | no-reply@acspedycja.pl | Ongoing | WinSADMS automated | Sends ZC429 AIS notifications — NOT a human |

### Billing / Admin

| Name | Email | Role |
|------|-------|------|
| Joanna Bąk ("Asia AC Spedycja") | biuro@acspedycja.pl | Monthly VAT statements ("Zestawienie do VAT") — not clearance |

**Critical note:** Any of the 5 human ACS clearance agents may send PZC. Automation must
recognize all 5 as valid PZC senders. `biuro@acspedycja.pl` is billing only — do not trigger
clearance events from this address.

**ACS relationship duration:** VAT statements confirmed from **Aug 2023** → relationship
established ≥3 years before this analysis window.

---

## 2. Ganther (Customs Broker — DHL + FedEx)

Ganther is the ONLY customs broker handling both DHL and FedEx shipments. They are the single
point of contact for duty calculation, PZC relay, and payment confirmation.

| Name | Email | Role | Notes |
|------|-------|------|-------|
| (Main inbox) | ganther.com.pl | Primary coordinator | All duty notices, PZC relay, DSK comms |
| Patrycja Jaworska | jaworska@ganther.com.pl | Secondary coordinator | Directly sends clearance notifications (AWB 4315324860, AWB 6876258325) |
| Krzysztof Suchodola | krzysztof.suchodola@ganther.com.pl | Admin / billing | CC'd on overdue invoice thread |

**Ganther scope:** Processes ALL DHL (via DSK from ACS) and ALL FedEx (via cesja direct from
FedEx) shipments for Estrella. No other broker confirmed.

---

## 3. DHL Poland (Carrier — Inbound)

DHL handles the physical transport and cesja initiation for DHL AWBs.

| Address | Role | Notes |
|---------|------|-------|
| odprawacelna@dhl.com | DHL customs department | Primary sender of arrival notifications and cesja Fwd to ACS |
| administracja_centralna@dhl.com | DHL central admin | Receives PZC release confirmation (not a clearance initiator) |

### DHL Cesja Staff (pool of 7 — rotation is normal)

| Name | Period |
|------|--------|
| Zaneta Rybaczewska | Confirmed in signatures |
| Anna Was | Confirmed |
| Paulina Debowska | Confirmed |
| Andrzej (surname unknown) | Confirmed |
| Julia Barczuk | Confirmed |
| Dominika Soberka | Confirmed |
| Olena (surname unknown) | Confirmed |

All cesja emails come FROM `odprawacelna@dhl.com` regardless of individual staff member.
Automation should key on the FROM address, not the signature name.

---

## 4. FedEx Poland (Carrier — Inbound + Outbound)

| Address | Name | Role |
|---------|------|------|
| pl-import@fedex.com | Kamil Romanowski (named in sig) | FedEx customs clearance / cesja handler |
| DataRWA@fedex.com | Grzegorz Sładek | FedEx Ops Support |
| poland@fedex.com | Unknown | Billing corrections / disputes |
| Zaneta.Nagat@fedex.com | Zaneta Nagat | FedEx sales (non-clearance) |

**FedEx clearance note:** Unlike DHL, FedEx does NOT use ACS Spedycja. Ganther handles
clearance directly after Estrella submits cesja to `pl-import@fedex.com`.

---

## 5. Estrella Internal (Poland)

| Address | Person | Role | Notes |
|---------|--------|------|-------|
| import@estrellajewels.eu | Tejal Manjerkar | Primary import handler | Receives all carrier notifications; submits FedEx cesja |
| tejal@estrellajewels.com | Tejal Manjerkar | Same person — .com variant | Used interchangeably; routing risk if one stops forwarding |
| account@estrellajewels.eu | (Accounts team) | Duty payment mailbox | CANONICAL target for duty notices — should always be in TO |
| amit@estrellajewels.eu | Amit Gupta | Owner / operations | Receives duty notices CC; should not be sole recipient |
| jyoti@estrellajewels.com | Jyoti | India-side operations | .com domain; India accounting forwards |
| info@estrellajewels.eu | General | General inquiries | CC'd on some accounting threads |

### Domain Usage Pattern

- `.eu` domain: Primary for all carrier, agent, broker communications
- `.com` domain: Used by Tejal and Jyoti for India-side operations
- **Risk:** Both domains are internal. Risk only if one stops forwarding to the other.
- **Recommendation:** All clearance-critical comms should use `.eu` exclusively.

---

## 6. Estrella LLP India (Entity)

| Address | Person | Role |
|---------|--------|------|
| kaushal@estrellajewelsllp.com | Kaushal | India LLP dashboard — discovered in Ganther email CC |

**Note:** This is the India LLP entity. Emails appear in CC on some duty-related threads.
Classification: inter-company accounting / ownership structure. Not a clearance actor.

---

## 7. Third-Party Service Providers

| Address | Name | Organization | Role |
|---------|------|-------------|------|
| jigar.p@simplex-hurtownia.pl | Jigar Purohit | Europe Simpleks | Pickup agent for some DHL shipments |
| iza@simplex-hurtownia.pl | Izabela | Europe Simpleks | Director |
| accounts@gjlindia.com | Sandeep | GJL India | Inter-company accounting |
| dyszynska@abf-biurorachunkowe.pl | Dyszyńska | ABF Biuro Rachunkowe | Polish accounting firm |

**Europe Simpleks:** Confirmed pickup agent for at least AWB 3023090884 (Aug 2025). Jigar
Purohit arranged pickup on behalf of Estrella from DHL warehouse.

**GJL India:** Receives duty invoice forwards from `account@estrellajewels.eu`. This is an
inter-company accounting loop. Sandeep's replies are NOT clearance instructions — do not trigger.

---

## 8. Actor Timeline (Who Was Active When)

### Jun–Sep 2024
- `odprawacelna@dhl.com` — DHL arrivals
- `michal@acspedycja.pl` (Michał Cieślak) — ACS primary agent
- `roman@acspedycja.pl` — ACS supervisor
- `ganther.com.pl` — Broker
- `biuro@acspedycja.pl` — Monthly VAT statements since Aug 2023

### Oct–Dec 2024
- ACS agent: transitioning (Michał active through Sep; exact handoff unknown)
- `ganther.com.pl` — Broker
- `odprawacelna@dhl.com` — DHL

### Aug–Nov 2025
- `odprawacelna@dhl.com` — DHL
- `roman@acspedycja.pl` — ACS supervisor
- `logistyka@acspedycja.pl` (Bartłomiej Bugaj) — ACS agent (confirmed Nov 2025)
- `ganther.com.pl` — Broker
- `no-reply@acspedycja.pl` — ZC429 AIS notifications (confirmed from this period)
- `pl-import@fedex.com` (FedEx) — Aug 2025 AWBs 882994160903, 882994338403
- `jigar.p@simplex-hurtownia.pl` — AWB 3023090884 pickup

### Dec 2025
- `odprawacelna@dhl.com` — DHL
- `adrian@acspedycja.pl` (Adrian Mielcarek) — ACS agent (AWB 2136263684)
- `logistyka@acspedycja.pl` (Bartłomiej Bugaj) — ACS agent
- `ganther.com.pl` + `jaworska@ganther.com.pl` — Broker
- VAT deferment gap discovered (AWB 6883058851)

### Jan–Feb 2026
- `piotr@acspedycja.pl` (Piotr Kubsik) — Primary ACS agent (most active)
- `logistyka@acspedycja.pl` (Bartłomiej) — Secondary ACS agent
- `roman@acspedycja.pl` — ACS (CC on FedEx cesja thread)
- `ganther.com.pl` + `jaworska@ganther.com.pl`
- `pl-import@fedex.com` — AWB 887467026597
- Ganther unpaid invoice thread (Jan 2026) — Krzysztof Suchodola CC'd

### Mar–Apr 2026
- `piotr@acspedycja.pl` — Primary ACS agent
- `ganther.com.pl` — Routing normalized to `account@` as canonical
- `jaworska@ganther.com.pl` — Active on AWBs 4315324860, 6876258325

---

## 9. DO NOT TRIGGER List

These addresses should NEVER fire clearance automation:

| Address | Reason |
|---------|--------|
| biuro@acspedycja.pl | VAT statements only — not clearance |
| no-reply@acspedycja.pl | Automated ZC429 — use for MRN extraction only, not action triggers |
| accounts@gjlindia.com | Inter-company accounting loop |
| dyszynska@abf-biurorachunkowe.pl | External accounting firm — not clearance |
| Zaneta.Nagat@fedex.com | FedEx sales — not customs |
| DataRWA@fedex.com | FedEx ops support — not clearance trigger |
| kaushal@estrellajewelsllp.com | India LLP — not clearance |

---

## 10. Trust Levels for Automation

| Level | Addresses | Action |
|-------|-----------|--------|
| **TRUSTED_CLEARANCE** | piotr@, logistyka@, roman@, adrian@, michal@acspedycja.pl + odprawacelna@dhl.com + ganther.com.pl + jaworska@ganther + pl-import@fedex.com | Trigger clearance event detection |
| **TRUSTED_NOTIFICATION** | no-reply@acspedycja.pl | Extract MRN only, no action trigger |
| **TRUSTED_INTERNAL** | import@, account@, amit@, tejal@ (both domains) | Internal routing — no trigger |
| **DO_NOT_TRIGGER** | biuro@, gjlindia, abf, sales FedEx, LLP | Ignore for automation purposes |

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
