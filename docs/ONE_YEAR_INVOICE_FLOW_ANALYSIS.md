# ONE_YEAR_INVOICE_FLOW_ANALYSIS.md
# Estrella Jewels — Invoice Flow Analysis (1-Year)
# Period: Jun 2024 – Apr 2026 | Inbound DHL + FedEx
# Generated: 2026-04-27

---

## Executive Summary

This document analyzes the invoice processing flow for inbound Estrella Jewels shipments over
12+ months. Key findings: Invoice batches range from 1 to 6 invoices per AWB; invoice numbering
follows the EJL/<FY>/<seq> format; filename date vs PDF body date mismatches are consistent
and resolved by PZ engine; verification gaps (exporter field, qty-by-type) are structural
and not errors. The GJL India inter-company accounting loop is the primary downstream consumer
of processed invoice data.

---

## 1. Invoice Characteristics

### Numbering Format

Estrella Jewels invoices from the India LLP follow this numbering scheme:

```
EJL/<fiscal-year>/<sequence>
Examples:
  EJL/25-26/039   ← Fiscal year 2025-2026, invoice 039
  EJL/26-27/039   ← Fiscal year 2026-2027, invoice 039
  EJL/25-26/951   ← Higher sequence numbers appear for non-standard clearances
```

Fiscal year runs Apr–Mar (India standard). The PZ processor extracts these refs and
cross-references against the ZC429/SAD.

### Invoice Grouping Per Shipment

Multiple invoices per AWB is standard. From confirmed PZ batches:

| AWB / Batch | Invoice Count | Invoice Refs | Notes |
|------------|--------------|-------------|-------|
| f490637817… (Apr 2026) | 6 | EJL/26-27/039–044 | Standard multi-invoice batch |
| AWB 2136263684 (Dec 2025) | 3 | EJL/25-26/951–953 | Non-standard clearance type |
| Most standard AWBs | 2–4 | EJL/<FY>/<seq> | Typical range |

### Invoice Filename Format

Observed pattern: `<seq> Invoice EJL-<FY>-<seq>-<date>.pdf`

Example: `039 Invoice EJL-26-27-039-10-04-26.pdf`

**Known issue:** Filename date encoding `26-27-03` sometimes differs from PDF body date
`10-04-2026`. This is consistent across all invoices in a batch and the PZ engine correctly
uses the PDF body date. This is documented in `corrections_log` as a non-blocking note.

---

## 2. Invoice Verification Flow

### What the PZ Engine Checks

1. **Invoice refs match ZC429:** Cross-reference EJL/<FY>/<seq> numbers
2. **CIF total match:** Sum of invoice CIF values vs ZC429 declared CIF value (in USD)
3. **Importer match:** Invoice importer name vs SAD importer name (normalized string comparison)
4. **Exporter match:** Invoice exporter vs SAD exporter — often a VERIFY-GAP (structural)
5. **VAT number match:** Invoice VAT vs SAD VAT — sometimes VERIFY-GAP if not on invoice
6. **Qty by type:** Piece counts by category — often VERIFY-GAP (SAD format limitation)

### Verification State Reference

| State | Meaning | Action |
|-------|---------|--------|
| `True` | Verified match | No action needed |
| `False` | Confirmed mismatch | Amendment flag required |
| `None` | Could not verify from document format | `[VERIFY-GAP]` note only |

### Common VERIFY-GAPsConditions (structural — not errors)

- **`qty_match_by_type = null`:** SAD goods description format insufficient for category breakdown
- **`exporter_match = null`:** SAD exporter field not parsed from ZC429 format
- **`vat_match = null`:** VAT number not visible on invoice or SAD

These are documented in `corrections_log` with `[VERIFY-GAP]` prefix and are visible to humans.
They do NOT produce amendment flags.

---

## 3. Invoice CIF and Exchange Rate

### CIF Components

Each invoice CIF includes:
- **Cost** (invoice declared value)
- **Insurance** (if separately specified)
- **Freight** (allocated by value, not piece count — critical rule)

### Exchange Rate Handling

| Rate | Source | Usage |
|------|--------|-------|
| NBP table rate | Bank of Poland daily table (e.g., table 068/A/NBP/2026) | PZ accounting (Polish GAAP) |
| Customs declaration rate | ZC429 `sad_customs_rate` | Customs assessment |

These rates legitimately differ. The `rate_note` field in audit.json documents this.
The PZ engine uses the NBP rate for all PLN calculations; customs uses its own rate.

**Example from audit.json (batch f490637817):**
```json
"nbp_rate_usd": 3.6506,
"sad_customs_rate": 3.693,
"rate_note": "NBP accounting rate may differ from customs declaration rate"
```

---

## 4. Freight Allocation Rule

**Mandatory rule (from CLAUDE.md):**

> Freight and insurance are allocated proportionally by value within each invoice.
> Never allocate freight by piece count.

### Correct Model

```
Item A: $200 USD value → 20% of CIF freight
Item B: $50 USD value  → 5% of CIF freight
Item C: $150 USD value → 15% of CIF freight
(Total $400 = 100%)
```

This rule applies to all invoices in a batch. The PZ engine enforces this.

---

## 5. Invoice Processing — Known Invoice Refs by Period

### Dec 2025

- **AWB 2136263684:** EJL/25-26/951–953 — "Request for Custom Clearance Assistance"
  This non-standard ref (951–953 are very high sequence numbers) suggests a special or
  amended clearance. Duty: 4,212 PLN (highest single-shipment duty of the year).

### Apr 2026

- **PZ batch f490637817b14d2cb72319ebf614ed4d:** EJL/26-27/039–044
  6 invoices, CIF total $13,270 USD, duty 1,225 PLN, verification: clean (CIF match verified)

---

## 6. Downstream Invoice Flow — GJL India Accounting Loop

After PZ is processed and duty paid:

1. `account@estrellajewels.eu` holds duty invoice from Ganther
2. Tejal sends W-firma (Polish accounting software) entries to `accounts@gjlindia.com` (Sandeep)
3. CC: Jyoti (`jyoti@estrellajewels.com`), `info@estrellajewels.eu`
4. Sandeep receives entries for inter-company reconciliation with GJL India

**Purpose:** Shared ownership/accounting structure between Estrella Jewels Poland and GJL India.

**Automation rule:** This is a pure accounting loop. Do not trigger clearance events from
`accounts@gjlindia.com` or W-firma notifications.

---

## 7. Invoice Importer Name Normalization

The PZ engine compares:
- Invoice: `"Estrella Jewels Sp. z o.o., Sp. k.(cid:13) Estrella Jewels Sp. z o.o., Sp. k.(cid:13)"`
  (PDF extraction artifact — `(cid:13)` = carriage return)
- SAD: `"ESTRELLA JEWELS SP. Z O.O. SP. KOM."`

These are the same legal entity — different abbreviation conventions (Sp. k. vs Sp. Kom.).
The PZ engine handles this normalization. `importer_match = True` is correct even with this
surface difference.

---

## 8. Invoice Gaps and Automation Opportunities

| Gap | Impact | Proposed Fix |
|-----|--------|-------------|
| Invoice filename date ≠ PDF body date | Low — handled by engine | Log as correction, not error |
| Invoice exporter often unverifiable | Low — structural | Maintain VERIFY-GAP, don't flag |
| No invoice → AWB linkage in pre-automation batches | Medium — can't auto-match | Use AWB in batch_id or audit field |
| W-firma posting not tracked in timeline | Low | Add `accounting_entry_posted` event if observable |
| Invoice currency (USD) → PLN conversion tracked but not stored per invoice | Low | Add per-invoice PLN equivalent to audit |

---

*Analysis complete. All findings are evidence-based from email thread examination and PZ processor output.*
*No production data was modified.*
