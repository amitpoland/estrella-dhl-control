# 05 — Capability Registry

**Business capabilities first, not pages.** Every package is scoped to exactly one capability.
A capability owns an authority, a canonical page, an API surface, a DB, and a service. Before
implementation, the Executive Coordinator loads that capability's manifest
(`capabilities/<name>/manifest.md`) and proves the chain (`00 §1.7`).

> This registry is an **index**. Detailed authority/page/API/DB/service state lives in each
> manifest, and the live authoritative map lives in `.claude/memory/PROJECT_STATE.md` and the
> Application Authority Registry. Where they disagree, PROJECT_STATE + the code win; a manifest
> that drifts is a stale-registry issue to fix (see `10`).

---

## The seven capabilities

| Capability | Authority owner | Canonical surface (V2) | Primary DB(s) | Manifest |
|---|---|---|---|---|
| **master-data** | Product Master + Customer Master (consume-only) | Master Data → Products / Clients | `reservation_queue.db` (product_master), customer master, `wfirma_product_mirror` | `capabilities/master-data/manifest.md` |
| **warehouse** | `inventory_state_engine` (single-writer `transition()`) | `/v2` Inventory (`inventory-page.jsx`) | `warehouse.db`, `inventory_state` | `capabilities/warehouse/manifest.md` |
| **returns-qc** | INVENTORY (returns_qc_disposition store) | Inventory → Returns registers | `warehouse.db` (`returns_qc_disposition`, `returns_events`) | `capabilities/returns-qc/manifest.md` |
| **manufacturing** | producer / MM movement + sample/consignment workflow | Inventory (Sample / Consignment / Producer-return views) | `warehouse.db` (sample_out_events, MM state) | `capabilities/manufacturing/manifest.md` |
| **commercial** | PROFORMA + IMPORT_PZ + SALES (separate authorities, Lesson N) | Proforma / Sales / PZ pages | proforma DB, `documents.db`, sales linkage | `capabilities/commercial/manifest.md` |
| **integrations** | Mirror/sync layer to external systems | (backend + status panels) | mirror tables, webhook state | `capabilities/integrations/manifest.md` |
| **platform** | app shell, auth, config/flags, deploy, observability | V2 router / shell, admin | config, auth/session, deployment_record | `capabilities/platform/manifest.md` |

---

## Capability contract (what every manifest must name)

1. **Authority owner** — the one module/master that owns this business process.
2. **Existing page** — the single canonical URL + JSX file (no new page; Lesson M/F).
3. **Existing API** — the `routes_*.py` surface (registered in `main.py`).
4. **Existing DB** — the SQLite file(s) owned by a `*_db.py` module.
5. **Existing service(s)** — where the business logic lives.
6. **Blockers vs advisories** — which signals may hard-block Approve/Post/Convert/Reservation
   (true fiscal/tax/duplication risk) vs which are advisory-only (Lesson N).
7. **Status** — one of `COMPLETE` · `ACTIVE` · `PARTIAL` · `PLANNED`.

If any of items 1–5 cannot be named for a proposed change, **STOP** and confirm with the
operator (Master-First rule; `00 §1.7`).

---

## Rules

- **No cross-authority guard without a named business rule + a pinning test** (Lesson N /
  authority separation). PRODUCT / PROFORMA / IMPORT_PZ / WAREHOUSE / SALES each own their gates.
- **A capability is not "complete" until the Business Operability gate passes** (`07`).
- **Extending a capability never creates a second one.** New scope extends the existing
  authority page/service/DB (Existing Pages Rule / Existing Backend Rule).
