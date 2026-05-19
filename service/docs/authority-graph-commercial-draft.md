# Commercial Draft Authority Graph
# Campaign 4 — Single Source of Truth Refactor
# Status: REFERENCE — append-only. Supersede with a new dated entry.
# Authored: 2026-05-19

---

## Purpose

This document is the canonical map of every system that touches commercial/customer
data in the proforma draft flow. It exists so no future developer accidentally
creates a fourth authority layer, silently bypasses an existing one, or ships
a diverged test tool.

---

## Authority Layers

### Layer A — Identity / Mapping (`wfirma_customers` table in `wfirma_db.py`)

**Purpose**: client_name → wFirma contractor ID mapping; invoice receiver routing

| Field | Is canonical for | Updated via |
|-------|-----------------|-------------|
| `wfirma_customer_id` | wFirma bill-to entity | register / sync |
| `client_name` | PZ-internal customer name | same |
| `vat_id`, `country`, `match_status` | EU VAT identity | auto-sync from wFirma |
| `ship_to_mode` | wFirma XML `<contractor_receiver>` shape | PATCH `/api/v1/wfirma/customers/{name}/ship-to` |
| `ship_to_wfirma_customer_id` | wFirma receiver entity ID in proforma XML | same PATCH |

**Production proforma routes read ship_to exclusively from this table.**

### Layer B — Commercial defaults (`CustomerMaster` DB in `customer_master_db.py`)

**Purpose**: per-customer commercial configuration; defaults hydrated into proforma drafts

| Field group | Canonical for | Used in |
|-------------|--------------|---------|
| `freight_fixed_amount_eur/usd` | freight suggestion | `suggest-freight` endpoint |
| `freight_service_id`, `freight_label_*` | freight wFirma product ID | same |
| `freight_last_amount` + `freight_mode` | **LEGACY backward-compat only** | `pick_freight()` fallback |
| `insurance_fixed_amount_eur/usd`, `insurance_rate`, `insurance_min_*` | insurance suggestion | `suggest-insurance` endpoint |
| `insurance_service_id`, `insurance_label_*` | insurance wFirma product ID | same |
| `preferred_proforma_series_id` | proforma series | `_build_proforma_request()` |
| `preferred_invoice_series_id` | invoice series | invoice conversion path |
| `preferred_payment_method` | payment method XML field | `_build_proforma_request()` |
| `default_currency`, `default_language_id` | draft defaults | draft creation |
| `bill_to_name`, `bill_to_street`, etc. | human-readable buyer address | `onApplyCustomerDefaults` (UI) |
| `ship_to_name`, `ship_to_street`, etc. | human-readable ship-to address | `onApplyCustomerDefaults` (UI) |
| **`ship_to_contractor_id`** | ⚠️ wFirma receiver ID (DUPLICATE — see below) | legacy test tool only |
| **`ship_to_use_alternate`** | alternate address form show/hide in dashboard.html | dashboard UI only |

**Important**: `CustomerMaster.ship_to_name/street/city/zip/etc` are the human-readable
physical address fields, used by the "Apply customer defaults" UX button to populate the
draft's buyer/ship-to blocks. They are NOT the same as `wfirma_customers.ship_to_mode` —
these serve genuinely different purposes (physical address vs wFirma entity routing).

### Layer C — Batch-level service charges (`proforma_service_charges_db`)

**Purpose**: operator-entered freight/insurance for one specific shipment batch

| Keyed by | `(batch_id, client_name, charge_type)` |
|----------|---------------------------------------|
| UPSERT semantics | `replace_all()` |
| Displayed in | `_build_preview()` → preview.service_charges |
| Separate from | CustomerMaster default amounts |

These are the ACTUAL line-item charges on the proforma. CustomerMaster amounts are
suggestions; `proforma_service_charges_db` holds what the operator committed per batch.

### Layer D — Advisory inference (`customer_commercial_profile.py`)

**Purpose**: wFirma invoice history analysis → confidence scoring

- Never written to any DB by production routes
- Has `ship_to_mode`, freight, insurance inferences from invoice history
- Purely advisory: shown in UI as hints, never drives proforma generation

### Layer E — TOOL-ONLY legacy freight cascade (`freight_resolver.py` + `customer_freight_history` DB)

**Purpose**: 4-step cascading freight resolver (DB → wFirma invoices → proformas → unresolved)

⚠️ **NO PRODUCTION ROUTE IMPORTS THIS MODULE.** Only `app/tools/send_wfirma_proforma_live_test.py` uses it.

For production freight suggestions: use `pick_freight(cm, draft_currency)` from
`app.services.customer_master`. CustomerMaster fields `freight_fixed_amount_eur/usd`
are the canonical production path.

### Layer F — Physical shipping addresses (`client_addresses_db.py` / `routes_client_addresses.py`)

**Purpose**: multiple named shipping addresses per contractor (label, street, is_default)

Separate concern. Not connected to proforma XML receiver routing (Layer A).
Not used in `onApplyCustomerDefaults` (Layer B address fields are used there).

---

## Known Authority Conflicts

### Conflict 1 — Ship-to receiver ID stored in two tables (MEDIUM SEVERITY)

| Location | Field | Used by |
|----------|-------|---------|
| `wfirma_customers.ship_to_wfirma_customer_id` | wFirma receiver entity ID | **Production routes** |
| `CustomerMaster.ship_to_contractor_id` | same semantic value | **Test tool only** |

These can diverge silently. `_build_preview()` emits a `ship_to_cm_conflict` warning
(non-blocking) when both are non-empty and disagree. The production route is always correct;
if they disagree, update `wfirma_customers` via the PATCH `/ship-to` endpoint.

**Resolution rule**: `wfirma_customers.ship_to_wfirma_customer_id` is the production truth.
`CustomerMaster.ship_to_contractor_id` is a cache/legacy field. To update ship-to:
use `PATCH /api/v1/wfirma/customers/{name}/ship-to`, NOT the customer master PUT.

### Conflict 2 — Test tool uses CustomerMaster for ship_to, production uses wfirma_customers

`send_wfirma_proforma_live_test.py` at line 816 calls `cm_ship_to_shape(cm_record)` which
reads `CustomerMaster.ship_to_contractor_id`. Production routes read `wfirma_customers.ship_to_mode`.

If `CustomerMaster.ship_to_contractor_id` and `wfirma_customers.ship_to_wfirma_customer_id`
are in sync, both paths give the same result. Conflict 1 fix keeps them in sync.

---

## Hydration Flow for Proforma Drafts

```
_build_preview(batch_id, client_name)
  │
  ├─ packing_lines DB               → product lines, quantities
  ├─ wfirma_customers table         → ship_to_mode, ship_to_wfirma_customer_id
  ├─ CustomerMaster DB              → series_id, payment_method, default_currency
  ├─ proforma_service_charges_db    → freight/insurance service charges
  └─ inventory_state                → stock position
       ↓
  preview response (shown to operator before create)
       ↓
  operator reviews, adjusts service charges if needed
       ↓
  POST /proforma/create (legacy) or POST /draft/{id}/post (new flow)
       ↓
  _build_proforma_request() / _build_proforma_request_from_draft()
    ├─ wfirma_customers             → ship_to_mode + receiver_id (for XML)
    ├─ CustomerMaster               → series_id, payment_method
    └─ persisted draft lines        → product, pricing (new flow only)
```

---

## What Does NOT Belong Here

The following systems interact with customer data but are NOT part of the commercial
draft authority graph:

- `wfirma_client.py` — live API calls; read-only lookups, never the storage authority
- `customer_master_db.py` KYC/compliance fields — separate risk management domain
- `routes_client_addresses.py` — physical address book; separate from proforma generation
- `reservation_queue.wfirma_customer_mapping` — parallel registry for reservation flow
- Cowork / intelligence layer — advisory suggestions, never writes to any authority source

---

## Rules for Future Development

1. **Freight defaults** → always read from `CustomerMaster.freight_fixed_amount_eur/usd`.
   Never add new callers to `freight_resolver.resolve_freight()` in production routes.

2. **Insurance defaults** → always read from `CustomerMaster.insurance_*` via
   `compute_insurance_suggestion()`. Never derive from wFirma invoice history in routes.

3. **Ship-to receiver entity** → read from `wfirma_customers.ship_to_wfirma_customer_id`
   in all proforma routes. Update via PATCH `/api/v1/wfirma/customers/{name}/ship-to`.
   Do NOT create a third storage location.

4. **Human-readable ship-to address** → read from `CustomerMaster.ship_to_*` address
   fields in `onApplyCustomerDefaults`. These are physical address fields, not entity IDs.

5. **Series IDs** → `CustomerMaster.preferred_proforma_series_id` / `preferred_invoice_series_id`.
   Single authority. Do not add fallbacks to wfirma_customers.

6. **Payment method** → `CustomerMaster.preferred_payment_method`. Single authority.

7. Adding a new commercial default field → add to `CustomerMaster` dataclass ONLY.
   Do not add to `wfirma_customers` table.
