# EXTENDED_EMAIL_ANALYSIS_REPORT.md
# Estrella Jewels — Extended Shipment Email Analysis
# Period: Aug 2025 – Apr 2026 | Carriers: DHL + FedEx | Both .eu and .com domains
# Generated: 2026-04-27

---

## Executive Summary

This report covers analysis of ~200+ shipment-related emails across both Estrella Jewels
domains (`estrellajewels.eu`, `estrellajewels.com`) from Aug 2025 through Apr 2026.

**Key outcomes:**
- 19 DHL inbound AWBs fully mapped (vs 11 in original Task C)
- 3 FedEx inbound AWBs discovered; full clearance flow reverse-engineered
- 35 unique email actors catalogued across carriers, agents, and internal mailboxes
- 4 routing risks identified; 1 confirmed to have caused a 28-day clearance delay
- FedEx confirmed to use same Ganther broker + DSK mechanism as DHL
- 6 output documents produced for automation improvement

---

## 1. Scope Achieved

### Email searches completed

| Search | Results | Data quality |
|--------|---------|-------------|
| `sender:fedex.com` | 30 emails | HIGH — full FedEx thread history |
| `sender:acspedycja.pl` | 30 emails | HIGH — complete ACS agent map |
| `entire:887467026597` | 10 emails | HIGH — full FedEx clearance thread |
| `entire:DSK::sender:ganther.com.pl` | 20 emails | HIGH — Ganther DSK interactions |
| `entire:6325915234:or:9765416334:or:6458714065` | 0 results | ZERO — keyword search limitation |
| `entire:3023090884` | 10 emails | HIGH — Aug 2025 shipment thread |
| `sender:jyoti` (prior session) | 50 emails | HIGH — internal actor map |
| `sender:ganther.com.pl` (prior session) | 50 emails | HIGH — duty history + FedEx link |

**Note on zero-result searches:** Direct AWB keyword searches (`entire:6325915234`) returned
zero results due to Zoho search limitations with numeric-only search terms combined with date
filters. However, these AWBs were confirmed through ACS sender searches and Ganther threads.

### Domain coverage

- `estrellajewels.eu` — PRIMARY. All carrier, agent, and broker emails route here.
- `estrellajewels.com` — SECONDARY. Tejal and Jyoti use .com addresses for India-side ops.
  Both are internal — no security risk. Routing inconsistency exists (clearance should use .eu).

---

## 2. Carrier Flow Findings

### DHL (confirmed: Aug 2025 – Apr 2026)

DHL clearance is a 3-actor chain: **DHL → ACS Spedycja → Ganther → Estrella**.

The flow is stable and well-documented. ACS handles full customs declaration; Ganther
relays PZC and issues duty notice. The sequence is consistent across all 19 AWBs examined.

**Improvements identified:**
- `no-reply@acspedycja.pl` was not in original trusted sender config (CRITICAL gap — ZC429 arrives here)
- `logistyka@acspedycja.pl` (Bartłomiej Bugaj) and `adrian@acspedycja.pl` (Adrian Mielcarek)
  are additional ACS agents not in original config
- `administracja_centralna@dhl.com` role clarified: receives PZC release, not a clearance initiator

### FedEx (confirmed: Jan–Feb 2026, Aug 2025)

FedEx clearance is a 2-actor chain: **FedEx → Ganther → Estrella**.
ACS Spedycja is NOT in the FedEx loop. Ganther handles the full clearance directly.

**Critical finding:** FedEx requires a formal cesja form submitted to `pl-import@fedex.com`
before Ganther can act. This is distinct from DHL where ACS handles cesja internally.

**FedEx-specific risks:**
1. Cesja form submission is manual — if import@ misses the FedEx email, DSK is delayed
2. If invoice shows FCA terms, Ganther needs transport invoice — adds 1-2 days
3. FedEx baseline clearance is 6–9 days vs DHL's 3–5 days

**AWB 887467026597 timeline (fully reconstructed):**
```
Day 0:  FedEx notification arrives (pl-import@fedex.com)
Day 0:  Cesja form sent to Amit/Roman/Ganther by FedEx
Day 3:  Ganther asks "Have you asked FedEx for Cession?"
Day 4:  Cesja docs submitted; FedEx auto-ack
Day 5:  DSK issued by FedEx to Ganther
Day 5:  Ganther: "przesyłka w odprawie" (in clearance)
Day 6:  Ganther sends PZC to FedEx + clearance notification to Amit
Day 9:  FedEx provides warehouse address; delivery arranged
```

---

## 3. Actor Discoveries

### New actors confirmed (not in original Task C analysis)

| Actor | Email | Significance |
|-------|-------|-------------|
| Adrian Mielcarek | adrian@acspedycja.pl | 3rd ACS clearance agent |
| Bartłomiej Bugaj | logistyka@acspedycja.pl | 2nd ACS clearance agent |
| Patrycja Jaworska | jaworska@ganther.com.pl | Ganther secondary coordinator |
| Krzysztof Suchodola | krzysztof.suchodola@ganther.com.pl | Ganther admin/billing |
| FedEx Poland Import | pl-import@fedex.com | FedEx customs clearance trigger |
| Kamil Romanowski | pl-import@fedex.com | FedEx cesja handler (named in signature) |
| Zaneta Rybaczewska | odprawacelna@dhl.com | DHL customs specialist (named in signature) |
| Jigar Purohit | jigar.p@simplex-hurtownia.pl | Europe Simpleks — pickup agent |
| Izabela | iza@simplex-hurtownia.pl | Europe Simpleks Director |
| Sandeep | accounts@gjlindia.com | GJL India accounts |
| Dyszyńska | dyszynska@abf-biurorachunkowe.pl | ABF accounting firm |
| Grzegorz Sładek | DataRWA@fedex.com | FedEx Ops Support |
| Zaneta Nagat | Zaneta.Nagat@fedex.com | FedEx sales (non-clearance) |

### Actor role clarifications

- **Joanna Bąk** (`biuro@acspedycja.pl`) also appears as "Asia AC Spedycja" in display name — same person/address
- **Tejal Manjerkar** uses both `import@estrellajewels.eu` and `tejal@estrellajewels.com` — same person
- **Ganther** is the ONLY broker handling both DHL and FedEx — single point of clearance for all carriers

---

## 4. Routing Risks Found

### Risk 1: Duty to Personal Inbox — CONFIRMED DELAY CAUSED

**Finding:** From Jan–Mar 2026, Ganther sent duty notices TO `amit@estrellajewels.eu`
rather than TO `account@estrellajewels.eu`.

**Impact confirmed:** AWB 2824221912 (Mar 2026) — duty notice went to `amit@` only.
Clearance took 28 days vs typical 5 days. The delay is directly attributable to the
duty notice not reaching `account@estrellajewels.eu`.

**Evolution observed:**
```
Jan 2026:  duty TO amit@           CC account@   ← routing gap
Feb 2026:  duty TO import@(Tejal)  CC amit@      ← confusion
Mar 2026:  duty TO amit@           only          ← 28-day delay
Apr 2026:  duty TO account@        CC amit@      ← CORRECT (normalized)
```

**Status:** Self-corrected by Apr 2026. Monitor to ensure this holds.

### Risk 2: Domain Inconsistency (.com vs .eu)

**Finding:** Both `tejal@estrellajewels.com` and `import@estrellajewels.eu` are used interchangeably.
Some early ACS emails (Nov–Dec 2025) used .com variants; later threads normalized to .eu.

**Impact:** Low. Both are internal. Risk is only if one mailbox stops forwarding to the other.

### Risk 3: FedEx Cesja Manual Submission Gap

**Finding:** FedEx requires Estrella to manually submit a cesja form to `pl-import@fedex.com`.
Unlike DHL where ACS handles cesja internally, FedEx puts the responsibility on the importer.

**Impact:** If `import@estrellajewels.eu` (Tejal) misses the FedEx notification, the entire
clearance is blocked until she submits the form. For AWB 887467026597, the process worked
but required Ganther to follow up ("Have you asked FedEx for Cession of rights?").

**Proposed automation:** Detect `pl-import@fedex.com` email → confirm cesja submitted within
24 hours → if not, alert `import@estrellajewels.eu`.

### Risk 4: FedEx Billing Mode (Recipient Pays)

**Finding:** AWB 882994160903 (Aug 2025) — FedEx charged the RECIPIENT (Estrella's customer)
for customs and duties because the shipment was created with "recipient pays" setting.

**Impact:** Customer billed unexpectedly. Requires manual correction via `poland@fedex.com`.

**Proposed guard:** When creating FedEx outbound shipments, always verify billing mode is
set to "sender pays" for duty/tax on inbound return shipments.

---

## 5. Shipment Registry (Complete)

### DHL Inbound — 19 AWBs confirmed

| AWB | Date | Key event | Duty |
|-----|------|-----------|------|
| 4730148570 | Mar 2025 | Oldest confirmed. Ganther invoice never sent — discovered Jan 2026 | Unknown |
| 3023090884 | Aug 2025 | Jigar pickup. duty→GJL India. Standard flow | Unknown |
| 2136263684 | Dec 2025 | "Request for Custom Clearance Assistance" (EJL/25-26/951-953) | Unknown |
| 8321832024 | Dec 2025 | Standard flow | Unknown |
| 6883058851 | Dec 2025 | Standard flow | Unknown |
| 2064232951 | Nov 2025 | accounts@gjlindia.com CC'd | Unknown |
| 8722845401 | Jan 2026 | Standard flow | Unknown |
| 8691361873 | Jan 2026 | Tejal ack'd payment; Ganther: "Glad you are satisfied" | Unknown |
| 9765416334 | Jan 2026 | Duty 1,528 PLN. Duty to amit@ (routing gap) | 1,528 PLN |
| 6325915234 | Jan 2026 | Duty 2,336 PLN. Duty to amit@ (routing gap) | 2,336 PLN |
| 5378819972 | Jan 2026 | Duty 1,622 PLN. Amit self-pickup from DHL warehouse | 1,622 PLN |
| 8580992114 | Feb 2026 | Duty to import@(Tejal) — domain confusion event | Unknown |
| 3109419880 | Feb 2026 | Standard flow | Unknown |
| 1214569005 | Mar 2026 | Standard flow | Unknown |
| 2824221912 | Mar 2026 | **28-day delay** — duty to amit@ only, account@ missed | Unknown |
| 3369800350 | Mar 2026 | Standard flow | Unknown |
| 8523214840 | Apr 2026 | Standard flow | Unknown |
| 6876258325 | Apr 2026 | Standard flow; jaworska@ganther CC'd | Unknown |
| 3283625844 | Apr 2026 | Standard flow; account@ normalized | Unknown |

### FedEx Inbound — 3 AWBs confirmed

| AWB | Date | Key event |
|-----|------|-----------|
| 887467026597 | Jan–Feb 2026 | Full clearance via Ganther. DSK delay 3–4 days. 6-9 day total |
| 882994160903 | Aug 2025 | Billing dispute — recipient charged for duties |
| 882994338403 | Aug 2025 | Customs issue (details partial) |

### FedEx Outbound (Export from Poland) — 3 AWBs

| AWB | MRN | Destination | Notes |
|-----|-----|-------------|-------|
| 888681132638 | 26PL4450100018RAB0 | Unknown | IE599/IE529 export clearance confirmed |
| 885967226148 | — | China (Guangzhou) | Customer delivery |
| 883559085518 | — | Norway | Customer delivery |

---

## 6. ACS Spedycja — Agent Specialization Observed

Analysis of sender patterns across 30+ ACS emails reveals two distinct roles:

**Piotr Kubsik** (`piotr@acspedycja.pl`):
- Sends PZC + duty notice directly
- Always includes "Proszę o zwrotne przesłanie potwierdzenia wpłaty" (request payment confirmation back)
- Most active Jan–Apr 2026

**Bartłomiej Bugaj** (`logistyka@acspedycja.pl`):
- Sends PZC + "awizo na powstałe należności" (duty notice)
- Does NOT request payment confirmation back
- Active Nov 2025 – Apr 2026 (parallel with Piotr)

**Roman Kałużny** (`roman@acspedycja.pl`):
- Appears in older shipments (Aug 2025, Nov 2025, Jan 2026)
- Also CC'd into FedEx cesja thread (AWB 887467026597)
- Appears to be senior agent / supervisor role

**Adrian Mielcarek** (`adrian@acspedycja.pl`):
- Active Dec 2025 (AWB 2136263684)
- Less frequent; possibly junior agent or specialist

**Joanna Bąk** (`biuro@acspedycja.pl` / "Asia AC Spedycja"):
- Sends "Zestawienie do VAT" (VAT statements) monthly — not clearance
- CC on some threads for billing purposes

**Implication for automation:** Any of the 4 clearance agents (piotr, logistyka, roman, adrian)
may send PZC. Automation must recognize all 4 as valid PZC senders.

---

## 7. Ganther Invoice History Gap (Financial)

**Finding:** In Jan 2026, Ganther sent a payment demand for 2,962.30 PLN for invoices from
Nov–Dec 2025 (overdue). Krzysztof Suchodola was CC'd.

This confirms Ganther had been clearing shipments since at least Nov 2025 but had not been
paid for that period. The gap was 6–8 weeks between clearance service and payment.

**Implication:** Ganther invoices should be tracked per shipment in audit.json. The
`ganther_invoice_received` timeline event (added in Task D Step 2) supports this.

---

## 8. GJL India Inter-Company Accounting Loop

**Finding:** Duty invoices from `account@estrellajewels.eu` are forwarded to
`accounts@gjlindia.com` (Sandeep at GJL India). Tejal also sends W-firma (Polish accounting
software) entries to Sandeep with CC to Jyoti and info@estrellajewels.eu.

This appears to be a shared accounting/ownership structure between Estrella Jewels Poland
and GJL India.

**Automation rule:** Never trigger on content from `accounts@gjlindia.com`. This is a
pure inter-company accounting loop. Sandeep's replies (if any) are not clearance instructions.

---

## 9. Gaps Remaining

| Gap | Why | Impact |
|----|-----|--------|
| AWB 4730148570 (Mar 2025) full thread | Date filter issue in Zoho search | LOW — old shipment |
| AWBs 6325915234, 9765416334 direct thread | Numeric search not returning body matches | LOW — already captured via ACS sender |
| FedEx AWB 882994338403 full details | Partial thread only | LOW — Aug 2025 |
| Duty amounts for Dec 2025 – Feb 2026 AWBs | Not visible in email summaries | MEDIUM — needed for Ganther invoice tracking |
| Pre-Aug 2025 shipments | Search period limited | LOW — not in scope |

---

## 10. Documents Produced

| File | Purpose | Status |
|------|---------|--------|
| `docs/EMAIL_ACTOR_DISCOVERY_EXPANDED.md` | 35-actor registry, 22 AWBs, routing risks | ✅ Complete |
| `docs/EMAIL_ROUTING_UPDATE_PROPOSAL_EXPANDED.md` | Full config proposals, approval gate | ✅ Complete |
| `docs/FEDEX_CLEARANCE_WORKFLOW_MAP.md` | 8-stage FedEx flow, timing, DHL comparison | ✅ Complete |
| `docs/CARRIER_CLEARANCE_RULES.md` | Unified DHL+FedEx rules, trusted config | ✅ Complete |
| `docs/COWORK_MONITORING_RULES_V3.md` | 11 triggers, FedEx variants, suggest-only contract | ✅ Complete |
| `docs/EXTENDED_EMAIL_ANALYSIS_REPORT.md` | This report | ✅ Complete |

---

## 11. Recommended Next Actions

### Immediate (no code change required)
1. **Admin review** of `EMAIL_ROUTING_UPDATE_PROPOSAL_EXPANDED.md` Section 7 approval gate
2. **Verify** `pl-import@fedex.com` is monitored — no automation fires on FedEx without it
3. **Confirm** `account@estrellajewels.eu` is canonical duty target for all future Ganther communications

### Short-term (code changes, require approval)
4. **Add to TRUSTED_CLEARANCE_SENDERS:** `pl-import@fedex.com`, `adrian@acspedycja.pl`
5. **Implement DO_NOT_TRIGGER list** in cowork_coordinator.py
6. **Add T3 (DSK_MISSING FedEx)** and T9 (DUTY_ROUTING_GAP) to detect_triggers()
7. **Add carrier detection logic** to cowork_coordinator.py (_detect_carrier function)

### Medium-term
8. **FedEx cesja submission tracking** — log cesja submission as timeline event `cesja_submitted`
9. **Ganther invoice tracking** — log `ganther_invoice_received` event with PLN amount
10. **Duty routing alert** — if Ganther sends duty to `amit@` without `account@` in TO, alert

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No changes to production code were made during this analysis task.*
*All config proposals require explicit admin approval before implementation.*
