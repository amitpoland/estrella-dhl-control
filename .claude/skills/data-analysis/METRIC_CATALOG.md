# METRIC_CATALOG.md — Estrella PZ Platform

**Authority:** `pz_calculator.py` + `pz_import_processor.py::process_batch()`
**Updated:** 2026-06-23
**Rule:** All metrics below are computed by `process_batch()`. Never recompute independently.

---

## Per-Line Metrics (one row per invoice line)

### FOB USD
- **Definition:** Invoice face value — supplier's price for goods at port of export
- **Formula:** Direct from supplier invoice PDF
- **Source field:** `invoice_lines.total_value` (documents.db) / `row["fob_usd"]` in process_batch output
- **Authority:** Supplier invoice document
- **Limitations:** FOB varies per exporter; CIF conversion adds freight + insurance

### DHL Line Share (PLN)
- **Definition:** This invoice line's proportional share of total DHL freight cost in PLN
- **Formula:** `(fob_usd / total_fob_usd_across_batch) × dhl_total_pln`
- **Source field:** `row["dhl_share_pln"]`
- **Authority:** `pz_calculator.py` line 237
- **Limitations:** Allocation is value-proportional (not piece-count-proportional)

### DHL Line Share (USD)
- **Definition:** DHL line share converted to USD
- **Formula:** `dhl_line_pln / usd_pln`
- **Source field:** `row["dhl_share_usd"]`
- **Authority:** `pz_calculator.py` line 238

### Insurance USD
- **Definition:** Marine/air insurance cost allocated to this invoice line
- **Formula:** `fob_usd × 0.005` (0.5% of FOB)
- **Source field:** `row["insurance_usd"]`
- **Authority:** `pz_calculator.py` line 241; constant `INSURANCE_PCT = 0.005`
- **Limitations:** Fixed percentage; actual insurance policy may differ

### Freight USD
- **Definition:** Air freight cost allocated to this invoice line
- **Formula:** `dhl_line_usd × 0.50` (50% of DHL USD share)
- **Source field:** `row["freight_usd"]`
- **Authority:** `pz_calculator.py` line 242; constant `DHL_SHARE = 0.50`
- **Limitations:** 50/50 split is a business rule, not a carrier rate

### CIF USD
- **Definition:** Cost + Insurance + Freight (customs valuation basis)
- **Formula:** `fob_usd + insurance_usd + freight_usd`
- **Source field:** `row["cif_usd"]`
- **Authority:** `pz_calculator.py` line 243
- **Cross-check:** Must reconcile with ZC429 declared CIF value (tolerance: ±$1.00 USD)

### Duty USD
- **Definition:** Import duty on this line's CIF value
- **Formula:** `cif_usd × duty_rate` (where `duty_rate` comes from ZC429 A00 / total CIF)
- **Source field:** `row["duty_usd"]`
- **Authority:** `pz_calculator.py` line 246; but effective duty rate from ZC429
- **CRITICAL:** `DUTY_RATE = 0.12` in constants is a FALLBACK for golden tests only. Real duty is the A00 amount from ZC429 divided proportionally by CIF. Never use 12% as a fixed rate for real batches.

### Landed USD
- **Definition:** Total import cost per line before currency conversion
- **Formula:** `cif_usd + duty_usd`
- **Source field:** `row["landed_usd"]`
- **Authority:** `pz_calculator.py` line 249

### Landed PLN (Line Netto PLN)
- **Definition:** Landed cost converted to Polish zloty — the accounting value for the PZ
- **Formula:** `landed_usd × usd_pln`
- **Source field:** `row["landed_pln"]` = `row["line_netto_pln"]`
- **Authority:** `pz_calculator.py` line 250
- **NBP Rate:** Applied at batch time; stored in audit file as `usd_pln`

### VAT PLN
- **Definition:** Polish VAT on the landed value (reference only for PZ)
- **Formula:** `landed_pln × 0.23`
- **Source field:** `row["vat_pln"]`
- **Authority:** `pz_calculator.py` line 253; constant `VAT_RATE = 0.23`
- **Note:** VAT (B00) is reference-only on the PZ. It is NOT included in the landed cost posted to wFirma.

### Brutto PLN (Line Brutto PLN)
- **Definition:** Landed cost including VAT — the "with-VAT" total
- **Formula:** `landed_pln + vat_pln`
- **Source field:** `row["brutto_pln"]` = `row["line_brutto_pln"]`
- **Authority:** `pz_calculator.py` line 254

### Landed Per Piece (PLN)
- **Definition:** Average landed cost per unit for this invoice line
- **Formula:** `landed_pln / qty`
- **Source field:** `row["landed_per_pc_pln"]`
- **Authority:** `pz_calculator.py` line 257

### Brutto Per Piece (PLN)
- **Definition:** Average brutto cost per unit for this invoice line
- **Formula:** `brutto_pln / qty`
- **Source field:** `row["brutto_per_pc_pln"]`
- **Authority:** `pz_calculator.py` line 258

---

## Batch-Level Aggregates (process_batch return)

### Razem Netto PLN (Total Net)
- **Definition:** Sum of all landed PLN values across the entire PZ batch
- **Formula:** `Σ row["landed_pln"] for all rows`
- **Source field:** `process_batch()["total_net"]`; stored in `pz_documents.total_net_pln`
- **Authority:** `pz_import_processor.py` line 3491
- **Golden reference:** `49668.46` PLN for batch 039–044

### Razem Brutto PLN (Total Gross)
- **Definition:** Sum of all brutto PLN values across the entire PZ batch
- **Formula:** `Σ row["brutto_pln"] for all rows`
- **Source field:** `process_batch()["total_gross"]`; stored in `pz_documents.total_gross_pln`
- **Authority:** `pz_import_processor.py` line 3492
- **Golden reference:** `61092.21` PLN for batch 039–044

### Duty A00 PLN
- **Definition:** Total import duty paid, as declared on the ZC429 A00 field
- **Formula:** Direct from ZC429 PDF, field A00 — no calculation
- **Source field:** `process_batch()["duty_pln"]`; stored in `pz_documents.duty_a00_pln` and `customs_declarations.duty_pln`
- **Authority:** ZC429 / SAD document — NEVER derive from invoice values
- **Golden reference:** `1225.00` PLN for batch 039–044

### Total CIF USD
- **Definition:** Sum of CIF USD across all invoice lines in the batch
- **Source field:** `process_batch()["totals"]["total_cif_usd"]`
- **Cross-check:** Must match ZC429 declared CIF value within ±$1.00 USD (`CIF_RECONCILIATION_TOLERANCE_USD = 1.0`)

### Effective Duty Rate %
- **Definition:** Implied duty rate from the batch (duty_pln / total_cif_usd × usd_pln × 100)
- **Source field:** `process_batch()["totals"]["duty_rate_pct"]`
- **Validity range:** 0–20% (`DUTY_RATE_MAX_PCT = 20.0`); anything outside this range aborts processing

### NBP Exchange Rate
- **Definition:** USD/PLN rate used for all currency conversions in this batch
- **Source:** NBP Table A (fetched live) or `--rate` CLI parameter
- **Source field:** `process_batch()["nbp"]["usd_rate"]`
- **Golden reference:** `3.6506` for batch 039–044 (NBP Table A 2026-04-09)

---

## Sales / Proforma Metrics

### Proforma Service Charge (Freight)
- **Definition:** Freight charge billed to a specific customer on their proforma
- **Source:** Operator-entered via `proforma_service_charges_db.py`
- **Source table:** `proforma_service_charges` → `charge_type='freight'`
- **Authority:** Operator; NOT derived from DHL cost
- **Limitation:** These are sales-side charges to the customer; unrelated to import CIF freight

### Proforma Service Charge (Insurance)
- **Definition:** Insurance charge billed to a specific customer on their proforma
- **Source:** Operator-entered via `proforma_service_charges_db.py`
- **Source table:** `proforma_service_charges` → `charge_type='insurance'`
- **Limitation:** Sales-side charge; rate may differ from 0.5% CIF insurance rate

---

## Financial Posting Metrics (finance_postings.sqlite)

**IMPORTANT:** All amounts in this database are stored as INTEGER (minor units / cents). Never sum as float.

### Charge Amount
- **Definition:** A single charge line associated with a batch and client
- **Types:** `net_goods`, `freight`, `insurance`, `duty`, `vat`, `other`
- **Source field:** `charges.amount_minor` (integer cents)
- **Convert to PLN:** `amount_minor / 100`

### Posting Total
- **Definition:** Total issued amount for a payment posting
- **Source field:** `postings.issued_total_minor` (integer cents)

### Payment Applied
- **Definition:** Amount of a payment applied to a specific charge
- **Source field:** `payment_allocations.applied_minor` (integer cents)

### FX Delta
- **Definition:** Currency conversion rounding delta when applying a payment
- **Source field:** `payment_allocations.fx_delta_minor` (integer cents)

---

## Verification Metrics (process_batch() → "verification" dict)

These are the cross-check results between invoice data and customs declaration:

| Metric | Values | Meaning |
|---|---|---|
| `invoice_refs_match` | `True` / `False` / `None` | Do ZC429 invoice refs match uploaded invoices? |
| `cif_match` | `True` / `False` / `None` | Does sum-of-invoice CIF match ZC429 declared CIF within ±$1? |
| `importer_match` | `True` / `False` / `None` | Does ZC429 consignee match Estrella's NIP `5252812119`? |
| `exporter_match` | `True` / `False` / `None` | Does ZC429 exporter match known supplier? |
| `qty_match_by_type` | dict by HSN type | Do piece counts match per item type? |
| `duty_rate_ok` | `True` / `False` | Is effective duty rate within 0–20%? |
| `blocked_phrases_clean` | `True` / `False` | Are there no blocked phrases in corrections log? |
| `nbp_rate_used` | float | The NBP rate used for this batch |

**Semantics:**
- `True` = verified ✓
- `False` = confirmed mismatch → amendment flag required
- `None` = could not verify → emit `[VERIFY-GAP]` prefix; NOT a mismatch

---

## Known Limitations

1. **DUTY_RATE = 0.12 is a golden-test constant only.** Real batches use ZC429 A00 proportionally.
2. **DHL_SHARE = 0.50 is a business rule.** DHL invoice may have different freight/insurance breakdown.
3. **INSURANCE_PCT = 0.005 is approximate.** Actual marine insurance policy may use a different rate.
4. **NBP rate is a daily spot rate.** It does not reflect intraday fluctuations.
5. **CIF reconciliation tolerance is $1.00 USD.** Rounding differences above this trigger a VERIFY-GAP.
6. **Proforma service charges are operator-entered** and are not validated against actual DHL costs.
7. **Finance posting amounts are in integer cents.** Summing the `amount_minor` column gives cents; divide by 100 for PLN.
8. **`customer_invoice_snapshot.db` is a cache** — reflects wFirma state at last sync, not real-time.
