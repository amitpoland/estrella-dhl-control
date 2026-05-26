# Sprint 21 — Client KYC + Consignment V2

**Campaign:** Atlas-V2  
**Sprint:** 21 of 23  
**Branch:** `atlas-v2/sprint-21-client-kyc-consignment-v2`  
**Dependency:** Sprints 05 (customer-master) + 09 (inventory) merged  
**New file:** `service/app/static/client-kyc-consignment-v2.html`  
**URL:** `/dashboard/client-kyc-consignment-v2.html`  
**Design source:** `design-files/client-kyc-and-consignment.jsx`

---

## Authority Boundary

```
OWNS:  Rich client KYC capture (multiple addresses, KUKE rating, credit limit,
       carrier preferences, document history), consignment goods tracking
       (pieces out on consignment, return-by date, value at risk)
NEVER: Override customer-master-v2's authority on the canonical customer record —
       this page ADDs KYC fields to the existing record; it does not own customer
       identity. Inventory state remains owned by inventory-v2 / inventory-state-machine.
```

This page extends customer-master-v2 with KYC depth, and inventory-v2 with consignment
visibility. The canonical authorities remain unchanged.

---

## APIs

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/v1/customers/{id}/kyc` | KYC bundle (addresses, KUKE, credit, carrier prefs) | NEW |
| `PUT /api/v1/customers/{id}/kyc` | Update KYC (gated, audit-trailed) | NEW write |
| `GET /api/v1/customers/{id}/document-history` | Doc history per client | NEW read-only |
| `GET /api/v1/inventory/consignment` | Pieces out on consignment | NEW read-only |
| `POST /api/v1/inventory/consignment/{piece_id}/return` | Mark returned | NEW write — goes through inventory-state-machine |

**Lesson I binding:** consignment state is part of inventory lifecycle. Returns
MUST flow through `inventory-state-machine` agent's authority — never direct DB writes.

---

## Page Structure

- PageHeader (h1: "Client KYC & Consignment", subtitle: "Customer profile + consignment goods")
- Tab strip: KYC | Document History | Consignment Out
- KYC tab: form fields (addresses[], KUKE rating, credit limit, carriers[], notes)
- Document History tab: CompactTable of all docs (proforma, invoice, PZ, statements) with DocActions (View/Download)
- Consignment Out tab: CompactTable of pieces (SKU, client, sent date, return-by, value, status) + "Mark returned" Btn per row
- SessionBanner on errors

---

## Mandatory Agents

Same 15. Adds:
- `client-contractor-mapping` verdict on KYC schema (no duplication of customer-master authority)
- `inventory-state-machine` verdict on return flow
- `compliance` verdict on KYC field set (KUKE, credit limit, KYC retention rules)
- `security-write-action-reviewer` verdict on KYC PUT + consignment return POST

---

## Acceptance Criteria

1. Page loads, no console errors
2. KYC tab: addresses can be added/edited, save persists, audit trail recorded
3. Document History tab: shows all docs with View/Download
4. Consignment tab: "Mark returned" flows through inventory-state-machine (verified by checking state log)
5. KYC writes audit-trailed (audit endpoint returns recent edit)
6. SessionBanner on auth/network errors
7. `data-testid` on all interactive surfaces
8. Rollback: remove file

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 21 — Client KYC + Consignment V2
Branch: atlas-v2/sprint-21-client-kyc-consignment-v2 (Sprints 05 + 09 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/client-kyc-and-consignment.jsx

TASK: Create client-kyc-consignment-v2.html — KYC depth + consignment visibility.

AUTHORITY:
OWNS: KYC field capture, consignment-out display, return-flow trigger
NEVER: override customer-master-v2 canonical customer record;
       direct inventory writes (must flow through inventory-state-machine);
       bypass compliance KYC retention rules

LESSON I BINDING:
- Consignment returns MUST flow through inventory-state-machine (not direct DB)
- Authority owner test: customer-master-v2 owns identity; this page adds KYC

KEY AGENTS:
- client-contractor-mapping (no duplication of customer-master authority)
- inventory-state-machine (return flow legality)
- compliance (KYC retention rules)
- security-write-action-reviewer (audit-trailed writes)

BACKEND: KYC GET/PUT + document-history GET + consignment GET + return POST.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
