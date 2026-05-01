# wFirma Reporting Dashboard — Plan

**Date:** 2026-04-27  
**Status:** Planning phase — no API calls made  
**Prerequisites:** wFirma read-only API keys (contractors/find, invoices/find, expenses/find, payments/find)

---

## Overview

The Estrella Reporting Dashboard aggregates data from:
- Estrella PZ processor (audit.json, calculated duty, shipping costs)
- wFirma read API (invoices, expenses, payments, contractors)
- Local batch records (AWB, carrier costs, insurance, duty A00)

**Goal:** Single-screen visibility into import economics, accounting sync status, and cash position.

---

## Dashboard Cards — Full Specification

### Card 1: Courier Cost Paid vs. Charged to Customer

**Data sources:**
- Paid: audit.json `totals.freight_usd × nbp_rate` (from each batch)
- Charged to customer: wFirma `invoices/find` where invoice description contains AWB

**Display:**
```
Courier Cost Paid vs. Charged
Month:  April 2026
Paid:       PLN 4,280
Charged:    PLN 3,900
Delta:     -PLN  380   ⚠ Under-recovered
```

**Alert:** Red if charged < paid by more than 5%  
**Drill-down:** Per-batch table showing AWB, paid, charged, delta

**API call:**
```json
POST /invoices/find  {conditions: [{field: "date", ge: "2026-04-01"}]}
```

---

### Card 2: Insurance Cost Paid vs. Charged

**Data sources:**
- Paid: audit.json `totals.insurance_usd × nbp_rate`
- Charged: manual entry or invoice line item tagged "insurance"

**Display:**
```
Insurance
Month:    April 2026
Paid:     PLN 620
Charged:  PLN 620
Status:   ✓ Balanced
```

---

### Card 3: Import Duty A00 by Month

**Data sources:**
- audit.json `customs_declaration.duty_a00_pln` per batch
- Cross-check against wFirma expenses (if duty recorded as cost)

**Display:**
```
Import Duty A00
Jan 2026:  PLN 3,412
Feb 2026:  PLN 4,891
Mar 2026:  PLN 2,108
Apr 2026:  PLN 1,181  (month in progress)
YTD Total: PLN 11,592
```

**Chart:** Bar chart, monthly, current month highlighted in gold

---

### Card 4: Shipment Profitability

**Data sources:**
- Revenue: wFirma `invoices/find` (sales invoices) matched to AWB
- Cost: audit.json `total_gross` (PZ gross value = cost of goods)
- Duty: audit.json `duty_a00_pln`
- Freight: audit.json `totals.freight_pln`

**Display:**
```
Shipment Profitability
AWB 3283625844:
  Revenue:    PLN 72,400
  COGS:       PLN 59,998
  Gross Margin: PLN 12,402  (17.1%)
  Duty:       PLN  1,181
  Freight:    PLN  4,280
  Net:        PLN  6,941  (9.6%)
```

**Alert:** Red if net margin < 5%

---

### Card 5: Supplier Outstanding

**Data sources:**
- wFirma `expenses/find` where payment status = unpaid
- OR wFirma `payments/find` filtered by contractor = supplier

**Display:**
```
Supplier Outstanding
Estrella Jewels LLP.:
  3 invoices unpaid
  Total:  USD 18,240  (≈ PLN 67,610)
  Oldest: 45 days overdue  ⚠
```

**Alert:** Red if any invoice > 30 days overdue  
**Drill-down:** Per-invoice list with due dates

**API call:**
```json
POST /expenses/find  {conditions: [{field: "paymentdate", operator: "lt", value: "today"}]}
```

---

### Card 6: Customer Outstanding

**Data sources:**
- wFirma `invoices/find` where payment_state = "not_paid" or "partial"

**Display:**
```
Customer Outstanding
3 invoices unpaid
Total:    PLN 24,800
Oldest:   12 days
Status:   ✓ Within terms
```

**Alert:** Amber if > 14 days, Red if > 30 days

**API call:**
```json
POST /invoices/find  {conditions: [{field: "payment_state", operator: "ne", value: "paid"}]}
```

---

### Card 7: Inventory / PZ Value

**Data sources:**
- Local: sum of all audit.json `totals.net` for batches with `status: success/partial`
- wFirma (future): `warehousedocuments/find` type=PZ (once API verified)

**Display:**
```
Inventory Value (PZ basis)
Total batches:    24
Total PZ value:   PLN 486,320 netto
Last PZ:          2026-04-27 (PZ 12/3/2026)
wFirma sync:      ⚠ Not synced via API yet
```

**Note:** Until Phase 3 is live, this card reads from local audit.json only.

---

### Card 8: Monthly Gross/Net Shipment Value

**Data sources:**
- Local audit.json files: `totals.net`, `totals.gross` per batch, grouped by month

**Display:**
```
Monthly Shipment Value
Month         Netto PLN    Brutto PLN   Batches
Jan 2026      124,420      153,037        8
Feb 2026      198,344      243,963       12
Mar 2026       87,210      107,268        5
Apr 2026       48,778       59,998        3  (in progress)
```

**Chart:** Stacked bar, net vs. VAT portion

---

### Card 9: wFirma Sync Status

**Data sources:**
- Local: `audit.json["wfirma_export"]` per batch
- wFirma API: `invoices/find` last 30 days (for invoice sync verification)

**Display:**
```
wFirma Sync Status
Mode:               Clipboard (Phase 1)
Last exported:      2026-04-27 14:32  (AWB 3283625844)
Batches exported:   18 / 24

Sync gaps:
  6 batches not yet exported to wFirma
  [View list]

API Mode:           Not enabled
Phase 3 status:     Pending endpoint verification
```

**Per-batch status:**
- ✅ `clipboard_exported` — clipboard was copied
- ⚠️ `pending` — PZ generated but not yet exported
- 🔴 `failed` — export attempt failed

---

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Estrella Reporting Dashboard          April 2026  [Export] │
├──────────────────┬──────────────────┬─────────────────────-─┤
│  Duty A00 YTD    │  Shipment Value  │  Profitability         │
│  PLN 11,592      │  Apr: 48,778     │  Avg margin: 9.6%      │
├──────────────────┼──────────────────┼───────────────────────┤
│  Courier         │  Insurance       │  wFirma Sync           │
│  Δ -PLN 380 ⚠   │  ✓ Balanced      │  18/24 exported        │
├──────────────────┼──────────────────┼───────────────────────┤
│  Supplier OS     │  Customer OS     │  Inventory PZ          │
│  USD 18,240 ⚠   │  PLN 24,800 ✓   │  PLN 486,320           │
└──────────────────┴──────────────────┴───────────────────────┘

[Monthly Trend Chart — 12 months netto/brutto]
```

---

## Three Export Modes (current + planned)

### Mode 1 — Clipboard Export (LIVE)
- Button in PZ/Accounting section of each shipment
- Generates tab-separated rows for wFirma PZ form paste
- Endpoint: `POST /api/v1/upload/shipment/{batch_id}/wfirma/clipboard`
- No API key required from wFirma

### Mode 2 — Chrome AutoFill (READY)
- User opens wFirma PZ page manually
- Loads PZ_READY.json in Chrome console
- Script fills all fields, never clicks Save
- Files: `chrome_wfirma_autofill/autofill_pz.js`

### Mode 3 — Direct API (PLANNED)
- Blocked until `warehousedocuments/add` is endpoint-verified
- Will require: wFirma API keys (accessKey + secretKey + appKey)
- Will create PZ documents automatically after shipment processing
- Will store returned document ID in audit.json for audit trail
- See: `docs/WFIRMA_PZ_API_FEASIBILITY.md` for verification checklist

---

## Implementation Phases

### Phase A — Local Analytics (no wFirma API needed) — NOW
Read from local `outputs/*/audit.json` files only.

| Card | Data source | Status |
|------|-------------|--------|
| Duty A00 by month | audit.json batches | Buildable now |
| Monthly shipment value | audit.json batches | Buildable now |
| Inventory / PZ value | audit.json batches | Buildable now |
| wFirma sync status | audit.json wfirma_export | Buildable now |

### Phase B — wFirma Read API — After keys obtained
Add wFirma read-only API calls.

| Card | wFirma endpoint | Prerequisites |
|------|----------------|---------------|
| Supplier outstanding | expenses/find | accessKey + secretKey + appKey |
| Customer outstanding | invoices/find | Same |
| Courier cost charged | invoices/find | Same |

### Phase C — Full Sync (warehousedocuments/add verified)
| Card | wFirma endpoint | Prerequisites |
|------|----------------|---------------|
| Inventory (live) | warehousedocuments/find | Phase 3 API verified |
| wFirma Sync Status (API) | warehousedocuments/find | Phase 3 API verified |

---

## wFirma Reporting API Read Operations (safe, no write risk)

These can be used for dashboard data TODAY once keys are obtained:

```python
# Monthly invoices (sales revenue)
POST /invoices/find
{
  "api": {
    "invoices": {
      "parameters": {
        "conditions": {
          "condition": [
            {"field": "date", "operator": "ge", "value": "2026-04-01"},
            {"field": "date", "operator": "le", "value": "2026-04-30"}
          ]
        },
        "fields": ["id", "number", "date", "total", "payment_state", "contractor.name"],
        "page": {"start": 0, "limit": 100}
      }
    }
  }
}

# Unpaid customer invoices
POST /invoices/find
{conditions: [{field: "payment_state", operator: "ne", value: "paid"}]}

# Supplier expenses (costs)
POST /expenses/find
{conditions: [{field: "date", operator: "ge", value: "2026-04-01"}]}
```

---

## Environment Variables Required (for Phase B+)

Add to `.env` when ready:
```
# wFirma API — Read (reporting only)
WFIRMA_ACCESS_KEY=
WFIRMA_SECRET_KEY=
WFIRMA_APP_KEY=
WFIRMA_COMPANY_ID=
WFIRMA_API_BASE_URL=https://api2.wfirma.pl

# Phase 3 write (disabled until verified)
WFIRMA_API_WRITE_ENABLED=false
```

---

## Security Rules (non-negotiable)

1. API keys stored in `.env` only — never in audit.json or Cliq messages
2. `WFIRMA_API_WRITE_ENABLED` defaults to `false` — must be explicitly set to `true`
3. All API calls logged with timestamp, endpoint, and response code in audit trail
4. Rate limiting: max 1 request/second to wFirma API
5. Duplicate prevention: check `audit.json["wfirma_export"]["api_doc_id"]` before creating new PZ
6. Rollback plan: store every created document ID — can be deleted if wrong
7. Never expose wFirma API keys in browser (all calls go through Python service)

---

## Next Immediate Action

1. Email wFirma support to confirm `warehousedocuments/add` availability on current plan
2. Build Phase A local analytics dashboard (no external API needed)
3. Once Phase A works, add wFirma read keys for Phase B
4. When `warehousedocuments/add` is confirmed → Phase 3
