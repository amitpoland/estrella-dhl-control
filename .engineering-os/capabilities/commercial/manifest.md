# Capability Manifest — commercial

**Status:** ACTIVE (sales persistence unified Pkg1 deployed; proforma detail parity + PDF work in flight)
**Authority owners (SEPARATE — do not conflate):** **PROFORMA**, **IMPORT_PZ**, **SALES**

> Lesson N (authority separation): Import, product master, proforma, warehouse receipt, barcode
> traceability, and sales linkage are separate authorities. Each owns its own gates. A guard that
> blocks across a boundary without a named business rule + test is incomplete.

---

## The three commercial authorities

| Authority | Source of truth | May hard-block on | Must NOT block on |
|---|---|---|---|
| **PROFORMA** | customer + product master + pricing | customer unmatched/ambiguous, missing price, design ambiguity, over-bill, WDT EU-VAT, margin-mask | inventory / stock / PZ / scan (advisory only) |
| **IMPORT_PZ** | import invoice/packing + customs evidence + mapped products + confirmed qty | unmapped products, no SAD/customs evidence, duplicate PZ, price conflict, `WFIRMA_CREATE_PZ_ALLOWED` | sales packing list, customer allocation, per-piece scan |
| **SALES** | sales packing / allocation / reservation | final dispatch / sales posting; reservation gate: customer matched + product mapped + stock dispatched per billed line | product creation, proforma, import qty confirmation, import PZ |

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | Proforma / Sales / PZ pages (V2) |
| **API** | `routes_proforma.py`, `routes_pz*.py`, sales linkage + `wfirma_reservation` routes |
| **Service** | `sales-proforma` logic, `pz-purchase-accounting`, `persist_sales_from_packing` (single canonical write path), `process_batch()` for all landed-cost/duty/VAT |
| **DB** | proforma DB, `documents.db`, sales linkage/reservation DBs |

## Hard financial rules (must never change)

- **`process_batch()` is the ONLY calculation path** — never recompute landed cost, freight,
  duty, totals, or notes in a route/service/Cliq layer.
- Freight/insurance proportional by value; duty from ZC429/A00 only; B00 VAT reference-only;
  notes/UWAGI from the engine only.
- Description authority: `description_pl` = legal Polish, `description_en` = legal English;
  posted proformas are read-only snapshots (repair only unposted drafts).

## Advisory routing (already in code)

`routes_proforma.py` routes "sales design not mapped to wFirma product_code" to
`line_mismatch_advisories` (advisory), NOT `blocking_reasons`, when `advisory_gates_enabled` —
Lesson N makes that the permanent default for advisory-class signals.

## Related
Skills: `ej-dashboard-fullstack-governance`, `wfirma-api-integration`.
Agents: `sales-proforma`, `pz-purchase-accounting`, `finance-accounting-logic`, `readiness-closure`, `security-write-action-reviewer`.
> Every commercial package touches protected + fiscal domains → **Deep Path, stop-and-ask, deploy gate mandatory.**
