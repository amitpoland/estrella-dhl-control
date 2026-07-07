# Capability Manifest — manufacturing

**Status:** PARTIAL / PLANNED (producer-return path exists; MM movement + sample/consignment
workflow states partially built — confirm live state against PROJECT_STATE before any package)
**Authority owner:** **INVENTORY** for stock state + workflow; **wFirma** for warehouse documents (MM)

> "Manufacturing" here = the producer / movement side of inventory: repair-to-producer,
> sample-out, consignment, and MM (inter-warehouse) movements. Physical warehouse documents
> (PZ/WZ/MM/RW/PW) stay in wFirma; the app mirrors them and stores workflow state.

---

## Workflow authority (Phase-C Constitution §9/§10)

```
Sample:      Main Warehouse → MM → Sample Warehouse → Customer → Return → MM → Main Warehouse
Consignment: Main Warehouse → MM → Consignment Warehouse → Customer
             (monthly: report sold → select → Invoice → WZ from Consignment ONLY — no double-WZ)
```

Every movement produces a document (wFirma). Inventory stores workflow state; wFirma stores the
warehouse document.

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | Inventory — Sample / Consignment / Producer-return views (`inventory-page.jsx`) |
| **API** | `routes_inventory_returns.py` (return-to-producer / return-from-producer), MM/movement routes |
| **Service** | `inventory_state_engine.py`, sample/consignment services, warehouse_receipt |
| **DB** | `warehouse.db` — `sample_out_events`, returns/producer events, MM state |

## Authority separation (Lesson N)

- **WAREHOUSE** owns quantity confirmation; **SALES** owns dispatch/allocation. A movement
  guard must not block across authority boundaries without a named business rule + a pinning test.
- MM warehouse-document writes to wFirma are **NOT API-writable** (wFirma limitation — warehouse
  documents PZ/WZ/RW/PW/MM cannot be created via API; see `wfirma-api-integration`). Confirm the
  real integration boundary before proposing any wFirma MM write.

## STOP conditions

- MM integration + webhook sync are late in the locked Implementation Order (steps 9–10).
- If a package needs a wFirma MM capability, **research first** (`wfirma-api-integration`,
  §19 Research Rule) — never guess a wFirma capability.

## Related
Skills: `ej-dashboard-fullstack-governance`, `wfirma-api-integration` (reference).
Agents: `inventory-state-machine`, `warehouse-ops`, `pz-purchase-accounting`, `integration-boundary`.
> This manifest is the least-settled of the seven — treat any manufacturing package as **Deep Path**.
