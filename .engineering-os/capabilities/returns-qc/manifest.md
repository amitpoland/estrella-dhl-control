# Capability Manifest — returns-qc

**Status:** COMPLETE / SEALED (origin/main @ 880c1ba4 via #848/#849, deployed + production-verified 2026-07-07)
**Authority owner:** **INVENTORY** (returns_qc_disposition store + single-writer transition)

> This is the reference example of a capability taken through the full OS lifecycle:
> inspection → authority build → operability amendment → 7-agent gate → prod verification → seal.

---

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | Inventory → Sample Return + Client Return registers (`inventory-page.jsx` — QCDispositionModal, QcCells) |
| **API** | `routes_inventory_returns.py` — `POST /api/v1/inventory/pieces/{id}/qc-disposition`, `GET .../qc-dispositions` |
| **Service** | `inventory_qc_writer.py` (`apply_qc_disposition`), `warehouse_db.py` (record/find/list helpers) |
| **DB** | `warehouse.db` — `returns_qc_disposition` table (additive, IF NOT EXISTS) + `returns_events` |
| **Transport** | `pz-api.js` — `qcDisposition`, `getQcDispositions` |

## QC decision → transition map

| Decision | Transition | Requires |
|---|---|---|
| restock | RETURNED_FROM_CLIENT → WAREHOUSE_STOCK | — |
| repair | RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER | `producer_name` (evidence contract) |
| write_off | → WRITTEN_OFF (terminal) | explicit "terminal & irreversible" confirm checkbox |

Idempotent (AWB/piece + type + window); idempotency pre-check runs **before** the state gate.
Operator identity is **session-derived**, never free-text. Role-gated by
`require_api_key_privileged`.

## Blockers vs advisories (Lesson N)

- Write-off's value-scrap accounting consequence is a **downstream/advisory** link to
  accounting/wFirma (a SEPARATE authority) — it must **NOT** auto-post.
- QC is not fiscal; it drives inventory state only.

## Deferred (NOT built — future packages, not blockers)

reversal, delete, edit, bulk/multi-select QC, finer role model,
`GET /returns/{id}/documents`, `PATCH dispatch_reference`.

## Related
Skills: `ej-dashboard-fullstack-governance`, design pair.
Agents: `inventory-state-machine`, `security-write-action-reviewer`, `frontend-flow-reviewer`.
See also: `project-returns-qc-disposition` (auto-memory, sealed).
