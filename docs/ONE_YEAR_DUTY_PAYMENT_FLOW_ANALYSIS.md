# ONE_YEAR_DUTY_PAYMENT_FLOW_ANALYSIS.md
# Estrella Jewels — Duty Payment Flow Analysis
# Period: Oct 2025 – Apr 2026 (duty-confirmed window) | Carrier: DHL + FedEx
# Generated: 2026-04-27

---

## Executive Summary

This document analyzes the complete duty payment flow for inbound DHL shipments over the
observable period. Duty amounts are confirmed from Ganther invoice emails. The analysis covers
21 AWBs with known duty amounts, totaling 31,667 PLN. One confirmed routing failure caused a
28-day clearance delay (AWB 2824221912, Mar 2026). Routing has since normalized by Apr 2026.

---

## 1. Duty Payment Chain

### Standard Flow (DHL)

```
DHL arrival
    ↓
ACS Spedycja files SAD / ZC429
    ↓
ZC429 issued → Ganther receives PZC
    ↓
Ganther sends duty notice to Estrella
    ↓
Estrella pays duty (account@estrellajewels.eu → bank transfer)
    ↓
Ganther confirms payment ("płaci się") → notifies ACS
    ↓
ACS releases cargo → delivery arranged
```

### Duty Notice Routing (observed evolution)

The routing of Ganther's duty notice email evolved significantly over the analysis period:

| Period | TO address | CC address | Risk |
|--------|-----------|-----------|------|
| Jan 2026 | amit@estrellajewels.eu | account@estrellajewels.eu | MEDIUM — correct person in CC |
| Feb 2026 | import@estrellajewels.eu (Tejal) | amit@estrellajewels.eu | HIGH — accounts not notified |
| Mar 2026 | amit@estrellajewels.eu | *(none)* | **CRITICAL — caused 28-day delay** |
| Apr 2026 | account@estrellajewels.eu | amit@estrellajewels.eu | ✅ CORRECT — normalized |

---

## 2. Complete Duty Dataset (21 confirmed AWBs)

### Oct 2025 — 3 AWBs, 2,978 PLN total

| AWB | Duty (PLN) | Notes |
|-----|-----------|-------|
| 5778558973 | 579 | Standard flow |
| 9765961984 | 553 | Standard flow |
| 2831021244 | 1,846 | Standard flow |

### Nov 2025 — 3 AWBs, 5,897 PLN total

| AWB | Duty (PLN) | Notes |
|-----|-----------|-------|
| 2264932003 | 2,551 | Standard flow |
| 5264550174 | 1,440 | Standard flow |
| 2064232951 | 1,906 | accounts@gjlindia.com CC'd |

### Dec 2025 — 2 AWBs with confirmed duty, 5,185 PLN total

| AWB | Duty (PLN) | Notes |
|-----|-----------|-------|
| 6883058851 | 973 | VAT deferment hold — delayed clearance |
| 2136263684 | 4,212 | Highest single-shipment duty of the year |

*Note: AWBs 8321832024, 6561633783, 4315324860 — duty amounts not extracted from available threads.*

### Jan 2026 — 5 AWBs, 8,499 PLN total

| AWB | Duty (PLN) | Routing | Notes |
|-----|-----------|---------|-------|
| 6458714065 | 879 | Unknown | Standard flow |
| 9765416334 | 1,528 | TO: amit@, CC: account@ | Routing gap — correct via CC |
| 6325915234 | 2,336 | TO: amit@, CC: account@ | Routing gap — correct via CC |
| 5378819972 | 1,622 | Unknown | Amit self-pickup from DHL warehouse |
| 8722845401 | 2,134 | Unknown | Standard flow |

*Jan 2026 was the heaviest duty month: 5 shipments, 8,499 PLN.*

### Feb 2026 — 2 AWBs with confirmed duty, 943 PLN total

| AWB | Duty (PLN) | Routing | Notes |
|-----|-----------|---------|-------|
| 2759203252 | 476 | Unknown | Standard flow |
| 8580992114 | 467 | TO: import@ (Tejal) | Domain confusion — accounts missed |

### Mar 2026 — 3 AWBs, 4,345 PLN total

| AWB | Duty (PLN) | Routing | Notes |
|-----|-----------|---------|-------|
| 1214569005 | 2,050 | Unknown | Standard flow |
| 2824221912 | 1,261 | TO: amit@ ONLY | **28-day delay — accounts never notified** |
| 3369800350 | 1,034 | Unknown | Standard flow |

### Apr 2026 — 3 AWBs, 3,820 PLN total

| AWB | Duty (PLN) | Routing | Notes |
|-----|-----------|---------|-------|
| 8523214840 | 1,181 | account@ normalized | ✅ Correct routing |
| 6876258325 | 1,414 | account@ normalized | ✅ Correct routing |
| 3283625844 | 1,225 | account@ normalized | ✅ Correct routing |

---

## 3. Monthly Duty Trend

```
Oct 2025:  2,978 PLN  ██
Nov 2025:  5,897 PLN  ████
Dec 2025:  5,185 PLN  ████
Jan 2026:  8,499 PLN  ██████  ← PEAK MONTH
Feb 2026:    943 PLN  █
Mar 2026:  4,345 PLN  ███
Apr 2026:  3,820 PLN  ███
─────────────────────────────
TOTAL:    31,667 PLN  (21 confirmed AWBs)
Avg/ship:  1,508 PLN
```

Jan 2026 peak is explained by 5 shipments landing in same period (post-holiday stock replenishment).

---

## 4. Confirmed Delay Incident — AWB 2824221912

**What happened:** Ganther sent duty notice for AWB 2824221912 (Mar 2026, duty 1,261 PLN)
exclusively to `amit@estrellajewels.eu`. The `account@estrellajewels.eu` mailbox was not
notified. Duty payment was not made for 28 days. Typical clearance duration is 3–5 days.

**Root cause:** Ganther's contact list for Estrella was not standardized. During Feb 2026,
duty notices had gone to `import@` (Tejal), which was also wrong. By Mar 2026, Ganther
reverted to Amit's personal address without CC-ing accounts.

**Financial impact:** 28-day warehouse hold. DHL storage fees may apply (not confirmed from
available threads). Disruption to stock replenishment cycle.

**Resolution:** By Apr 2026, Ganther had corrected routing to `account@` as primary,
`amit@` as CC. This appears to have been corrected following direct feedback.

---

## 5. Payment Confirmation Mechanism

Ganther uses a verbal confirmation pattern when duty is paid:

**Variants observed (all from ganther.com.pl):**
- "płaci się" — standard
- "placi sie" — unaccented variant
- "dzieki, płaci się" — thanking + confirmation
- "Zapłata odebrana" — "Payment received"
- Direct: confirmation of payment received + release notification

ACS Spedycja receives this confirmation and proceeds with cargo release.

---

## 6. Inter-Company Accounting Loop

Duty invoices from `account@estrellajewels.eu` are forwarded to `accounts@gjlindia.com`
(Sandeep at GJL India). Tejal sends W-firma entries to Sandeep with CC to Jyoti and
`info@estrellajewels.eu`.

**Purpose:** Shared accounting/ownership structure between Estrella Jewels Poland and GJL India.

**Automation rule:** Do NOT trigger on content from `accounts@gjlindia.com`. This is a
pure inter-company accounting loop. Sandeep's replies are not clearance instructions.

---

## 7. FedEx Duty (Partial)

FedEx duty flow differs from DHL:

1. FedEx sends duty notice alongside cesja request to `pl-import@fedex.com`
2. Ganther handles duty payment coordination after DSK issued
3. AWB 882994160903 (Aug 2025): FedEx incorrectly billed the shipment recipient (Estrella's
   customer) for duties — required manual correction via `poland@fedex.com`

FedEx duty amounts not available in analyzed threads.

---

## 8. Risk Assessment

| Risk | Severity | Status |
|------|----------|--------|
| Duty notice to personal inbox (amit@) without account@ | HIGH | Self-corrected Apr 2026 |
| Duty notice to import@ (Tejal) without account@ | MEDIUM | Was transient — Feb 2026 |
| FedEx recipient billing error | MEDIUM | Required manual fix |
| No duty amount tracking in audit.json for most AWBs | LOW | Field exists, not populated |

---

## 9. Automation Recommendations

1. **Duty routing guard:** If Ganther sends duty notice to `amit@` or `import@` without `account@`
   in TO or CC → fire T9 (DUTY_ROUTING_GAP) trigger immediately.

2. **Duty amount extraction:** Parse PLN amount from Ganther duty emails → store in
   `audit["duty_amount_pln"]` → use for Ganther invoice reconciliation.

3. **Payment confirmation tracker:** Detect "płaci się" / "placi sie" / "Zapłata odebrana" from
   ganther.com.pl → log `duty_paid_signal_at` in timeline.

4. **28-day SLA alert:** If duty notice received and `duty_paid_signal_at` not set within
   5 days → escalate via T2 (DUTY_PAYMENT_PENDING).

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
