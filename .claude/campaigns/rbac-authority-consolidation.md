# RBAC Authority Consolidation — Frozen Implementation Charter

**Status:** FROZEN (operator-ratified 2026-08-11)  
**Campaign name:** RBAC Authority Consolidation  
**Pinned source:** `C:\PZ-main` / `origin/main` @ `7150996b75eb12174df3ee79f896bd5510d2eec5`  
**Change class (when implemented):** auth / authorization runtime + V1/V2 consumers + tests  
**Authority owner:** backend authorization layer  
**UI consumers:** V1 renderer and V2 renderer (no independent frontend authority)

> This document is the **implementation charter**. It freezes architecture and the first `/plan` deliverable set. It does **not** authorize coding until an explicit implementation slice is opened against this charter.

---

## 1. Mission

Create **one canonical user-access system** for V1 and V2:

- Each user has: **role**, **permissions** (derived from role, overridable only via audited admin path), **default_surface**, **default_page**.
- Navigation, direct URL access, and backend API authorization all derive from the **same backend-owned permission catalogue**.
- Manually changing a URL must never widen access.
- Frontend never calculates or invents authority; it only **consumes** `/auth/me` (or equivalent) payloads.

---

## 2. Four freeze corrections (operator-ratified)

These corrections are **binding**. They do not widen scope; they prevent accidental privilege escalation.

### C1 — `Full` is human shorthand only

Matrix cells may say `Full` for readability. The **implementation catalogue must never store or check `Full`**.

Every `Full` expands to the explicit verb set for that module, e.g. Documents:

```
documents.view
documents.create
documents.edit
documents.upload
documents.download
documents.execute
documents.approve
documents.delete
documents.admin
```

### C2 — Logistics ≠ fiscal finalization

Logistics may receive **operational preparation** access. Financial finalization is a **separate permission set**.

PZ split:

| Permission | Meaning |
|---|---|
| `pz.view` | View PZ / import readiness surfaces |
| `pz.prepare` | Operational preparation (non-final) |
| `pz.create_draft` | Create draft PZ artifacts |
| `pz.finalize` | Finalize PZ for booking |
| `pz.export_wfirma` | Push / export PZ to wFirma |

Proforma split:

| Permission | Meaning |
|---|---|
| `proforma.view` | View proforma |
| `proforma.prepare` | Operational preparation |
| `proforma.create` | Create proforma draft |
| `proforma.edit` | Edit existing draft |
| `proforma.approve` | Approval / readiness finalize |
| `proforma.convert` | Convert to invoice / fiscal conversion |

**Default grant:** Logistics → prepare / create_draft (and view) only.  
**Default deny:** `pz.finalize`, `pz.export_wfirma`, `proforma.approve`, `proforma.convert` → Accounts / Admin (and explicit grants only).

### C3 — CRM role is frozen; customer/document-oriented

Add `crm` to the operator role namespace (legacy ladder side, not `master_*`).

**Initial CRM grants (allowed):**

- `dashboard.view`
- `inbox.view`, `inbox.act_crm`
- `shipments.view`
- `documents.view`, `documents.download`
- `proforma.view`
- `reports.crm`
- `master.clients.view`
- `master.clients.edit` — **only if explicitly desired** (default **OFF** in migration map)

**Default CRM denies:**

- `pz.*`, `wfirma.*`, `inventory.execute`, `dhl.execute`, `accounting.*`, `users.*`, `system.*`
- `documents.upload` — **not automatic**; grant only if business proves CRM uploads customer docs

### C4 — `default_surface` and `default_page` are separate fields

```
default_surface = v1 | v2
default_page    = dashboard | inbox | shipments | accounting | documents | dhl | …
```

Examples:

| Role | default_surface | default_page |
|---|---|---|
| logistics | v2 | shipments |
| accounts | v2 | accounting |
| crm | v2 | inbox |
| admin | v2 | dashboard |

---

## 3. Frozen authority model

```
User
 ├── role
 ├── default_surface
 ├── default_page
 │
 ▼
Role → Permission Catalogue
 │
 ▼
Module.Action
 │
 ├── Gate 1 — Navigation (hide unauthorized items)
 ├── Gate 2 — Direct URL (403 / redirect to allowed landing)
 └── Gate 3 — Backend API (403 even via Postman/DevTools)
```

Example `/auth/me` authority payload (shape frozen; exact field names may use snake_case in API):

```json
{
  "role": "logistics",
  "default_surface": "v2",
  "default_page": "shipments",
  "permissions": [
    "shipments.view",
    "shipments.create",
    "dhl.view",
    "dhl.execute",
    "awb.create",
    "documents.view",
    "documents.upload",
    "documents.download",
    "pz.view",
    "pz.prepare",
    "proforma.view",
    "proforma.prepare"
  ]
}
```

V1 and V2 both consume this payload. Neither invents a second matrix.

---

## 4. Ratified role direction

| Role | Primary authority |
|---|---|
| `admin` | System administration + explicitly granted business operations |
| `accounts` | Accounting, fiscal documents, PZ finalization, wFirma financial ops |
| `logistics` | Shipments, DHL, AWB, documents, operational PZ/proforma **preparation** |
| `crm` | Customers, CRM inbox, customer documents/downloads, proforma visibility |
| `auditor` | Read-only cross-domain audit |
| `viewer` | Minimal read-only operational visibility |
| `master_admin` | Master-data administration **only** |
| `master_editor` | Master-data editing **only** |
| `master_viewer` | Master-data read **only** |

**Namespace rule (frozen):** Do **not** merge `master_*` into legacy roles in this campaign. Permission **authority** consolidates; role **namespaces** stay isolated until a separate operator decision.

Post-freeze canonical roles (9):

```
admin, accounts, logistics, crm, auditor, viewer,
master_admin, master_editor, master_viewer
```

---

## 5. Governance rules (frozen)

1. **No permission widening** during migration vs current effective authority, unless explicitly approved.
2. Existing users retain **at most** current effective authority after migration defaults.
3. PZ finalization, wFirma writes, accounting postings, inventory mutations are **individually classified** (see §8).
4. **API-key authentication is not user authorization.** Keys may remain automation break-glass; they must not silently mean “any session role may write.”
5. `admin` does **not** automatically mean every fiscal action where business approval semantics differ — still permission-checked (admin may be granted the full set explicitly).
6. Hidden menu is **not** a security control.
7. Every direct URL must resolve permission **before** rendering sensitive page content.
8. Every sensitive backend write must enforce permission **independently**.
9. `master_*` isolation preserved until dedicated migration decision.
10. Permission / role / landing changes are **auditable** (who changed what, when).

---

## 6. Scope boundaries

### In scope (implementation, later slices)

- Auth schema / service / dependencies
- Auth API (`/auth/me`, user admin)
- V1 and V2 permission consumers (login landing, nav, URL gate)
- Route-by-route permission migration for classified endpoints
- Tests (deny-path first)
- Safe migration defaults script
- Admin Users UI: role, default_surface, default_page, permission chart

### Off-limits during initial RBAC migration

- Business calculations / `process_batch()`
- PZ accounting logic / landed-cost semantics
- wFirma payload semantics
- Customs workflow semantics
- Inventory quantity logic

### Protected-domain gate

Before implementing permission bindings for Financial / Customs / Inventory writes: mandatory `/security-review` on that slice. Blanket `require_api_key` → permission replacement is **forbidden**.

---

## 7. Deliverable A — Canonical Permission Catalogue

Format: `module.action`. Actions vocabulary:

`view` · `create` · `edit` · `upload` · `download` · `execute` · `approve` · `delete` · `admin`  
plus **domain-specific** fiscal/ops verbs where C2 requires them (`prepare`, `create_draft`, `finalize`, `export_wfirma`, `convert`, `act_crm`, …).

### 7.1 Shell / system

| Permission | Meaning |
|---|---|
| `dashboard.view` | Open dashboard |
| `inbox.view` | Open inbox |
| `inbox.act` | General inbox operational actions |
| `inbox.act_crm` | CRM-scoped inbox actions only |
| `system.settings.view` | Open system settings / admin shell page |
| `system.settings.admin` | Change system settings |
| `system.diagnostics.view` | Diagnostics |
| `system.api_status.view` | API status |
| `system.automation.view` | Automation / action center view |
| `system.automation.execute` | Run automation actions |
| `users.view` | List users |
| `users.admin` | Approve / reject / role / activate / deactivate |
| `reports.view` | Generic reports |
| `reports.financial` | Financial reports |
| `reports.logistics` | Logistics reports |
| `reports.crm` | CRM reports |
| `intelligence.view` | Intelligence hub |
| `coverage.view` | Coverage map |
| `shipping_ops.view` | Shipping ops |

### 7.2 Shipments / DHL / AWB

| Permission | Meaning |
|---|---|
| `shipments.view` | Shipments list/detail |
| `shipments.create` | Create / intake shipment |
| `shipments.edit` | Edit shipment metadata |
| `dhl.view` | DHL tower / clearance view |
| `dhl.execute` | Approve / send / operational DHL actions |
| `dhl.resolve` | Resolve / reopen (admin-class ops) |
| `awb.create` | Carrier AWB / shipment booking |
| `awb.label` | Label package generation |
| `awb.docs_fetch` | Waybill / ePOD fetch |

### 7.3 Documents

| Permission | Meaning |
|---|---|
| `documents.view` | Documents hub / list |
| `documents.create` | Create document records |
| `documents.edit` | Edit document metadata |
| `documents.upload` | Upload files |
| `documents.download` | Download / export |
| `documents.execute` | Package / regenerate operational actions |
| `documents.approve` | Document approval actions |
| `documents.delete` | Delete / replace documents |
| `documents.admin` | Document admin configuration |

### 7.4 Proforma (C2 split)

| Permission | Meaning |
|---|---|
| `proforma.view` | View list/detail |
| `proforma.prepare` | Operational prep (non-fiscal) |
| `proforma.create` | Create draft |
| `proforma.edit` | Edit draft |
| `proforma.approve` | Approve / finalize readiness |
| `proforma.convert` | Convert to invoice / fiscal conversion |
| `proforma.delete` | Delete/cancel draft (if exposed) |

### 7.5 PZ / import (C2 split)

| Permission | Meaning |
|---|---|
| `pz.view` | View PZ / import surfaces |
| `pz.prepare` | Operational preparation |
| `pz.create_draft` | Create draft PZ |
| `pz.finalize` | Finalize PZ |
| `pz.export_wfirma` | Push/export to wFirma |
| `pz.process` | Run PZ process engine path (non-calc change; auth only) |

### 7.6 Accounting / wFirma financial

| Permission | Meaning |
|---|---|
| `accounting.view` | Accounting hub / ledgers / statements (read) |
| `accounting.execute` | Non-posting accounting ops (refresh, export UI) |
| `accounting.post` | Fiscal postings (if any local) |
| `wfirma.view` | wFirma setup / mapping view |
| `wfirma.goods.write` | Create/adopt goods |
| `wfirma.customers.write` | Customer auto-create / sync apply |
| `wfirma.reservation.create` | Create wFirma reservation |
| `supplier_invoices.view` | Supplier invoice review |
| `supplier_invoices.upload` | Upload supplier invoices |
| `supplier_invoices.edit` | Edit / resolve supplier invoice rows |

### 7.7 Inventory / warehouse

| Permission | Meaning |
|---|---|
| `inventory.view` | Inventory screens |
| `inventory.execute` | Location move, sample, returns, dispatch marks |
| `inventory.correct` | Privileged corrections / reversals |
| `warehouse.scan` | Warehouse scan writes |
| `warehouse.receipt.confirm` | Receipt confirm |

### 7.8 Master data (namespace-preserving)

| Permission | Meaning |
|---|---|
| `master.view` | Master data shell |
| `master.edit` | Master edit (maps to master_editor capability) |
| `master.admin` | Master admin / hard-delete class |
| `master.clients.view` | Customer master view (CRM-relevant) |
| `master.clients.edit` | Customer master edit (explicit grant) |
| `carriers.view` | Carriers page |
| `carriers.edit` | Carrier configuration |

> Catalogue may gain verbs during security-review of a specific endpoint **only by appending** to this file (append-only). Renaming/removing a frozen permission requires operator amendment.

---

## 8. Deliverable B — Existing-Role → Permissions Migration Map

**Rule:** deny-by-default. Only listed permissions are granted. Migration must not exceed today’s effective authority for fiscal writes (C2).

### 8.1 Landing defaults

| Role | default_surface | default_page |
|---|---|---|
| admin | v2 | dashboard |
| accounts | v2 | accounting |
| logistics | v2 | shipments |
| crm | v2 | inbox |
| auditor | v2 | dashboard |
| viewer | v2 | dashboard |
| master_admin | v2 | master |
| master_editor | v2 | master |
| master_viewer | v2 | master |

Existing users without stored landing → assign from role table above.  
`default_surface=v1` only when operator explicitly sets it (no auto-force of all users to V2 in migration).

### 8.2 Permission bundles

Legend: `✓` = default grant · `—` = default deny · `(opt)` = off by default, explicit opt-in only

#### Legacy / CRM operator roles

| Permission | admin | accounts | logistics | crm | auditor | viewer |
|---|---|---|---|---|---|---|
| dashboard.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| inbox.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| inbox.act | ✓ | ✓ | ✓ | — | — | — |
| inbox.act_crm | ✓ | — | — | ✓ | — | — |
| shipments.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| shipments.create | ✓ | — | ✓ | — | — | — |
| shipments.edit | ✓ | — | ✓ | — | — | — |
| dhl.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| dhl.execute | ✓ | — | ✓ | — | — | — |
| dhl.resolve | ✓ | — | — | — | — | — |
| awb.create | ✓ | — | ✓ | — | — | — |
| awb.label | ✓ | — | ✓ | — | — | — |
| awb.docs_fetch | ✓ | — | ✓ | — | — | — |
| documents.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| documents.upload | ✓ | — | ✓ | (opt) | — | — |
| documents.download | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| documents.execute | ✓ | — | ✓ | — | — | — |
| documents.delete | ✓ | — | — | — | — | — |
| documents.admin | ✓ | — | — | — | — | — |
| proforma.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| proforma.prepare | ✓ | ✓ | ✓ | — | — | — |
| proforma.create | ✓ | ✓ | ✓* | — | — | — |
| proforma.edit | ✓ | ✓ | ✓* | — | — | — |
| proforma.approve | ✓ | ✓ | — | — | — | — |
| proforma.convert | ✓ | ✓ | — | — | — | — |
| pz.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| pz.prepare | ✓ | ✓ | ✓ | — | — | — |
| pz.create_draft | ✓ | ✓ | ✓ | — | — | — |
| pz.finalize | ✓ | ✓ | — | — | — | — |
| pz.export_wfirma | ✓ | ✓ | — | — | — | — |
| pz.process | ✓ | ✓ | ✓** | — | — | — |
| accounting.view | ✓ | ✓ | ✓*** | — | ✓ | — |
| accounting.execute | ✓ | ✓ | — | — | — | — |
| accounting.post | ✓ | ✓ | — | — | — | — |
| wfirma.view | ✓ | ✓ | ✓ | — | ✓ | — |
| wfirma.goods.write | ✓ | ✓ | — | — | — | — |
| wfirma.customers.write | ✓ | ✓ | — | — | — | — |
| wfirma.reservation.create | ✓ | ✓ | — | — | — | — |
| supplier_invoices.view | ✓ | ✓ | ✓ | — | ✓ | — |
| supplier_invoices.upload | ✓ | ✓ | ✓ | — | — | — |
| inventory.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| inventory.execute | ✓ | — | ✓ | — | — | — |
| inventory.correct | ✓ | — | — | — | — | — |
| warehouse.scan | ✓ | — | ✓ | — | — | — |
| warehouse.receipt.confirm | ✓ | — | ✓ | — | — | — |
| reports.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| reports.financial | ✓ | ✓ | — | — | ✓ | — |
| reports.logistics | ✓ | — | ✓ | — | ✓ | — |
| reports.crm | ✓ | — | — | ✓ | ✓ | — |
| master.view | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| master.clients.view | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| master.clients.edit | ✓ | ✓ | — | (opt) | — | — |
| master.edit | ✓ | — | — | — | — | — |
| master.admin | ✓ | — | — | — | — | — |
| carriers.view | ✓ | ✓ | ✓ | — | ✓ | — |
| carriers.edit | ✓ | — | ✓ | — | — | — |
| system.settings.view | ✓ | — | — | — | — | — |
| system.settings.admin | ✓ | — | — | — | — | — |
| system.diagnostics.view | ✓ | — | — | — | ✓ | — |
| system.api_status.view | ✓ | — | ✓ | — | ✓ | — |
| system.automation.view | ✓ | ✓ | ✓ | — | ✓ | — |
| system.automation.execute | ✓ | — | ✓ | — | — | — |
| users.view | ✓ | — | — | — | — | — |
| users.admin | ✓ | — | — | — | — | — |
| intelligence.view | ✓ | ✓ | ✓ | — | ✓ | — |
| coverage.view | ✓ | — | ✓ | — | ✓ | — |
| shipping_ops.view | ✓ | — | ✓ | — | ✓ | — |

\* Logistics `proforma.create` / `proforma.edit` = **draft/preparation only**; must not imply approve/convert.  
\*\* `pz.process` for logistics = engine run for preparation outputs only; **must not** imply `pz.export_wfirma`. Implementation must bind the route to the correct verb after security-review.  
\*\*\* Logistics `accounting.view` = **limited view** only (no financial write). If the accounting hub cannot hide write controls without permissions, deny page-level access until UI respects permissions.

#### Master-data namespace (isolated)

| Permission | master_admin | master_editor | master_viewer |
|---|---|---|---|
| master.view | ✓ | ✓ | ✓ |
| master.edit | ✓ | ✓ | — |
| master.admin | ✓ | — | — |
| master.clients.view | ✓ | ✓ | ✓ |
| master.clients.edit | ✓ | ✓ | — |
| All other catalogue permissions | — | — | — |
| default_page | master | master | master |

Master roles do **not** receive legacy shipments/DHL/accounting grants by migration.

### 8.3 Expanding `Full` (C1)

When Admin matrix cell was `Full` for a module, migrate Admin to **all verbs listed for that module** in §7 — never a literal `Full` token.

---

## 9. Deliverable C — Deny-by-default API Mapping

**Principle:** unclassified sensitive write → **deny** for session users until mapped. Automation `X-API-Key` remains a separate break-glass channel and must be explicitly documented per route; it is **not** a substitute for user permission.

Columns:

- **Current gate** = what exists at pin `7150996b`
- **Required permission** = session-user check to add
- **Risk** = financial / customs / inventory / admin
- **Migration note** = no widening

### 9.1 Priority Tier-0 (must map before any “permission complete” claim)

| Area | Representative routes (module) | Current gate | Required permission(s) | Risk |
|---|---|---|---|---|
| User admin | `/auth/users*` | `require_admin` | `users.admin` | admin |
| System admin | `/api/v1/admin/*`, backup | `require_admin` | `system.settings.admin` / `users.admin` as applicable | admin |
| AWB create | `POST /api/v1/carrier/{batch}/shipment` | api_key + `admin\|logistics` | `awb.create` | customs |
| Label package | `POST …/label-package` | api_key + `admin\|logistics` | `awb.label` | customs |
| DHL approve/send/package | `routes_dhl_clearance` mutations | api_key + `admin\|logistics` | `dhl.execute` | customs |
| DHL resolve/reopen | `routes_dhl_logistics` | `require_admin` | `dhl.resolve` | customs |
| Proforma post/create/to-invoice | `routes_proforma` privileged writes | `require_api_key_privileged` | `proforma.approve` / `proforma.convert` / `proforma.create` (per action) | financial |
| PZ process | `POST /api/v1/pz/process` | `require_api_key` only | `pz.process` (+ finalize/export if route does those) | financial |
| PZ create/adopt/confirm | `routes_wfirma` pz_* | `require_api_key` only | `pz.finalize` and/or `pz.export_wfirma` (classify each) | financial |
| wFirma goods create/adopt | `routes_wfirma_capabilities` | `require_api_key` only | `wfirma.goods.write` | financial |
| wFirma customer write/sync apply | same | api_key / admin mix | `wfirma.customers.write` | financial |
| Reservation create | `routes_wfirma_reservation` | `require_api_key` only | `wfirma.reservation.create` | financial |
| Inventory location/sample/returns | inventory write routers | mostly `require_api_key` | `inventory.execute` | inventory |
| Inventory corrections | returns corrections | `require_api_key_privileged` | `inventory.correct` | inventory |
| Warehouse scan/receipt | warehouse routes | privileged | `warehouse.scan` / `warehouse.receipt.confirm` | inventory |
| Document delete/replace | upload master gates | `require_role_or_apikey(MASTER_*)` (flag OFF→api_key) | `documents.delete` + keep master isolation when flag ON | admin/docs |
| Packing writes | `routes_packing` | `get_current_user` (any role) | tighten to `documents.upload` / module-specific | docs |

### 9.2 Deny-by-default policy for migration coding

1. New permission dependency helper: e.g. `require_permission("pz.export_wfirma")` (name illustrative).
2. For each Tier-0 route: add permission check **in the same PR as tests** that prove:
   - logistics session → 403 on finalize/export/approve/convert
   - accounts session → allow where mapped
   - viewer/crm → 403 on writes
   - URL/nav deny covered in FE tests separately
3. Do **not** replace `require_api_key` with “any authenticated user with vague module.view”.
4. `master_role_enforcement` remains a separate decision; do not silently enable it as part of UI nav work.

### 9.3 Explicit non-goals for first API slice

- Reclassifying every read endpoint in one PR
- Collapsing API-key automation into user roles
- Enabling fiscal writes for logistics “because the old matrix said Full/Create”

---

## 10. Three gates (implementation contract)

| Gate | Owner | Behavior |
|---|---|---|
| 1 Navigation | V1/V2 consumers of `/auth/me` | Hide items lacking `*.view` (or module entry permission) |
| 2 Direct URL | V1/V2 shell | Unauthorized page → access denied or redirect to `default_surface`+`default_page` |
| 3 Backend API | Auth dependencies | 403 if permission missing; FE hide is irrelevant |

Login: remove hard-coded `/dashboard`; use backend-provided landing from role/user profile.

V2 App: load `/auth/me` at startup; stop hard-coding TopBar identity.

---

## 11. Implementation sequence (post-charter)

1. Revalidate pin / security-review Tier-0 writes (classify each action verb).  
2. Implement catalogue + role map in backend (no FE yet).  
3. Extend user record: `default_surface`, `default_page`; add `crm` to `ROLES`.  
4. Safe migration defaults (no widening).  
5. `/auth/me` returns role + permissions + landing.  
6. Login landing consumer.  
7. V2: load me → filter NAV → gate `handleNav` + deep-link.  
8. V1: same catalogue consumers.  
9. Route-by-route Tier-0 permission gates + deny tests.  
10. Admin Users UI: role, surface, page, permission chart (read from catalogue).  
11. Browser + API tampering tests.  
12. Rollback path: restore prior role-membership behavior without business-data mutation.

---

## 12. Safety gates

Mandatory `/security-review` before binding:

- Accounting / PZ finalization / proforma conversion / wFirma create-export  
- Inventory mutations  
- DHL execute / AWB create  

**No fiscal/business write behavior may be newly enabled** solely because a nav item became visible.

---

## 13. Acceptance criteria (campaign-level)

- [ ] Single permission catalogue is backend authority  
- [ ] `/auth/me` returns role + permissions + default_surface + default_page  
- [ ] Login does not hard-code `/dashboard`  
- [ ] V2 loads current user; nav and `/v2/<page>` are permission-gated  
- [ ] Non-admin cannot render Admin/Users surfaces via URL tampering  
- [ ] Logistics cannot call finalize/export/approve/convert APIs (403)  
- [ ] CRM cannot call `pz.*` / `wfirma.*` / `inventory.execute` / `dhl.execute` / `accounting.*` / `users.*`  
- [ ] master_* still isolated  
- [ ] Deny-path tests exist before rely-on-allow tests  
- [ ] Rollback restores prior role gates without data loss  

---

## 14. Amendment rule

This charter is **frozen**. Changes require an explicit operator amendment block appended below (date + what changed + why). Do not silently edit ratified tables.

### Amendments

#### AMD-2026-08-11-A — Tier-0 security review completed (read-only)

- Evidence: `reports/inspection/2026-08-11-rbac-tier0-security-review.md`
- Pin confirmed: `7150996b`
- Finding: Logistics **can** currently reach fiscal finalization (`pz_create`, correction-push/commit, proforma approve/post/to-invoice) — C2 is a **tightening** migration
- Finding: `master_role_enforcement=False` → master_* isolation **not live**
- Finding: Users/System admin + DHL/AWB execute paths largely **SAFE**; PZ/proforma/wFirma/inventory largely **GAP**
- Next: open implementation Slice 0 only after operator acknowledgment; Slice 2 requires deny-path logistics tests

#### AMD-2026-08-11-B — Slice 0 + Slice 1 merged; Gate 3 defined as Slice 2

- Slice 0: PR #1184 → merge `ce73770f` (catalogue + `/auth/me`)
- Slice 1: PR #1188 → merge `42f8a1f9` (feature tip `9f8c7538`; V2 Gate 1+2 consumer)
- Post-merge baseline @ `42f8a1f9`: **CLEAR** — `reports/inspection/2026-08-11-rbac-slice1-postmerge-baseline.md` (focused 57 passed; Tier-0 still unbound)
- Production deploy Slice 0/1: **HOLD**
- Slice 2 definition (backend Gate 3 / `require_permission`): `reports/inspection/2026-08-11-rbac-slice2-definition.md` — **coding WAIT** until explicit **OPEN SLICE 2**
- Do not mix Tier-0 enforcement PRs with production sync

#### AMD-2026-08-12-C — OPEN SLICE 2 (operator word)

- Continuity pin: `0dc647afa8608f49f52783b652e5e5074cd09a25` (R-1 closed; main = prod)
- Open record: `reports/inspection/2026-08-12-rbac-slice2-open.md`
- Sub-slice at open: **2a already on tip** (`require_permission` + `reports.financial`); **2b** users/system admin catalogue stack in this coding wave; **2c/2d/2e deferred** pending mandatory `/security-review`
- Production deploy of Slice 2: **HOLD** (unchanged)

---

## 15. Related evidence

- Read-only audit canvas: Cursor canvas `rbac-authority-audit.canvas.tsx`  
- Frozen charter canvas: `rbac-authority-charter-frozen.canvas.tsx`  
- Tier-0 security review: `reports/inspection/2026-08-11-rbac-tier0-security-review.md`  
- Prior audit agents against `7150996b`: auth model, V2 shell, V1 gates, API inventory  
- Atlas V2 Auth campaign history (login once targeted inbox-v2; current main diverged to `/dashboard`)
