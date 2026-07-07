# Capability Manifest — warehouse

**Status:** ACTIVE (Inventory Intelligence Phase 1 read-only reconciliation deployed; frontend
consolidation in progress)
**Authority owner:** **INVENTORY** — `inventory_state_engine.transition()` (single state writer)

> Inventory is the sole stock authority. It reads product_code from packing, never from wFirma.
> All state changes go through the single-writer `transition()`.

---

## State machine (inventory_state_engine.py)

```
PURCHASE_TRANSIT → WAREHOUSE_STOCK → { SALES_TRANSIT, SAMPLE_OUT, RETURNED_FROM_CLIENT,
                                       RETURNED_TO_PRODUCER, DIRECT_DISPATCH_READY → CLIENT_DISPATCHED }
                                     → CLOSED
                   WAREHOUSE_STOCK / RETURNED_FROM_CLIENT → WRITTEN_OFF (terminal)
```

Single writer: `transition()`. Canonical state set pinned by `test_inventory_batch_state` +
`test_inventory_state_engine`.

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | `/v2` Inventory — `service/app/static/v2/inventory-page.jsx` (canonical 5k-line hub, has writes) |
| **API** | `routes_inventory*.py`, `routes_inventory_returns.py` |
| **Service** | `inventory_state_engine.py`, `warehouse_receipt` service, reconciliation engine (Phase 1) |
| **DB** | `warehouse.db` (`inventory_state`, events tables) |

## Frontend authority note (from inspection)

- Canonical = `v2/inventory-page.jsx`. Legacy `inventory-v2.html` (read-only) is routed to only
  by `pz-design-v2.js:103`; a 3rd surface is `dashboard.html` inline view. Smallest consolidation
  = repoint that one route + freeze legacy (no new page — Lesson M/F).

## Blockers vs advisories (Lesson N / authority separation)

- **WAREHOUSE authority = operator quantity confirmation** (advisory; quantity-risk only).
- **Must NOT hard-block** on per-piece barcode scan unless the shipment is `serial_controlled`.
- Scan / warehouse-confirmation are **advisory** to fiscal actions elsewhere.

## Governance guardrails

- No second stock authority; no upward writes to Product Master (consume-only).
- Read-only reconciliation stays read-only; corrections are a separate approved package.

## Related
Skills: `ej-dashboard-fullstack-governance`, design pair (page work).
Agents: `inventory-state-machine`, `warehouse-ops`, `backend-safety-reviewer`, `frontend-authority-inspector`.
See also: `project-inventory-intelligence`, `project-inventory-frontend-consolidation` (auto-memory).
