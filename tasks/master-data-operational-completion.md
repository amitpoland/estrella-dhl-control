# Master Data Operational Completion — Inspection + Parity Matrix

> **Status:** inspection-only. No code change. Defines the campaign goal
> and parity matrix; sequences safe batches; identifies hard stops.
> **Campaign id:** `MDOC-2026-05` (Master Data Operational Completion).
> **Date:** 2026-05-16.

This document inspects every Master Data surface and assigns each
entity/button a verdict (keep / merge / remove / implement / disable) so
that future sessions can execute safe batches without re-deriving the
analysis. Predecessor campaigns:
- `MDC-2026-05` — Master Data Completion (closed; 14 batches)
- `OIA-2026-05` — Operational Integrity + Automation (closed)
- `OSO-2026-05` — Operational Stabilization + Observation (closed)
- `P6F-2026-05` — Phase 6F (paused at steady-state)

The four predecessor campaigns shipped most of the master-data surface.
This campaign closes the operational gap: Users/Roles writes, Designs
master, KYC tabs polish, wFirma sync visibility, and the per-entity
button audit.

---

## 1 — Files inspected (read-only)

| File | Size | Routes | Purpose |
|---|---|---|---|
| `service/app/api/routes_master_data.py` | 610 | 28 (HS/Units/PL/Incoterms/VAT/FX/Carriers GET+PUT+DELETE+POST) | B5–B9 entities |
| `service/app/api/routes_customer_master.py` | 310 | 3 (GET list, GET one, PUT upsert) | Customer Master (B0) |
| `service/app/api/routes_client_addresses.py` | 131 | 4 (GET, POST, PUT, DELETE) | Shipping addresses (B2 helper) |
| `service/app/api/routes_client_carrier_accounts.py` | 143 | 4 (GET, POST, PUT, DELETE) | Per-client carrier accounts (B2 helper) |
| `service/app/api/routes_suppliers.py` | 189 | 5 (GET×2, POST, PUT, DELETE) | Suppliers (B4) |
| `service/app/api/routes_auth.py` | 429 | 13 (login, signup, /me, forgot/reset, users list, users approve/reject/role/activate/deactivate, reset-code) | Auth + Users + Roles |
| `service/app/services/master_data_db.py` | (large) | n/a | HS/Units/PL/Incoterms/VAT/FX/Carriers DAO |
| `service/app/services/customer_master_db.py` | (large) | n/a | Customer master DAO |
| `service/app/services/client_addresses_db.py` | (small) | n/a | Shipping addresses DAO |
| `service/app/services/client_carrier_accounts_db.py` | (small) | n/a | Client carrier accounts DAO |
| `service/app/services/suppliers_db.py` | (medium) | n/a | Suppliers DAO |
| `service/app/static/dashboard.html` | ~23,000 lines | n/a | `MasterDataPage` at L3317; `ClientKycModal` at L2341 |
| `service/tests/test_dashboard_master_design.py` | 769 | n/a | The security-contract source-grep suite |

Auth user store: `<storage_root>/users.db` (see `routes_auth.py::router = APIRouter(prefix="/auth", ...)` + `auth_db_path` in `core/config.py`).
Master data store: `<storage_root>/master_data.sqlite`.
Customer master store: `<storage_root>/customer_master.sqlite`.
Suppliers store: `<storage_root>/suppliers.sqlite`.
Audit retention: docs persist via the existing audit framework.

---

## 2 — Parity matrix

Columns: **UI** = panel exists in MasterDataPage / KYC modal. **API** = backend route exists. **DB** = persistent store wired. **Verdict** = next-action class. **Batch** = batch id (MDOC-* assigned here; references prior campaigns where applicable).

### 2.1 — Customer-side entities

| Entity | UI | API | DB | Missing | Risk | Verdict | Batch |
|---|---|---|---|---|---|---|---|
| **Clients (wFirma customers)** | List panel + Open profile button | `GET /api/v1/wfirma/customers` | wFirma authoritative (read-only mirror) | None — display is complete; "Open profile" opens KYC modal | LOW | **keep** | (live) |
| **Customer Master** | Inline edit (PUT) inside ClientKycModal | `routes_customer_master.py` (3 routes: GET list, GET one, PUT upsert) | `customer_master.sqlite` | None | LOW | **keep** | (live; B0/B2 fixed 422 bug) |
| **Shipping Addresses** | KYC modal "Addresses" tab | `routes_client_addresses.py` (4 routes) | `customer_master.sqlite::shipping_addresses` | None | LOW | **keep** | (live) |
| **Client Carrier Accounts** | KYC modal "Carriers" tab | `routes_client_carrier_accounts.py` (4 routes) | `customer_master.sqlite::client_carrier_accounts` | None | LOW | **keep** | (live) |
| **KYC** | KYC modal KYC tab (kyc_status, kyc_approved_on, kyc_expiry) | Same as Customer Master (PUT upsert) | `customer_master.sqlite` | None — fields land via Customer Master PUT | LOW | **keep** | (live) |
| **KUKE / Credit** | KYC modal Credit tab (kuke_limit, kuke_approved, credit_limit) | Same as Customer Master (PUT upsert) | `customer_master.sqlite` | None — `Decimal(0)` falsy fix (L-004) shipped in B0 | LOW | **keep** | (live) |
| **Invoice Settings** | KYC modal Invoices tab (vat_id, default_vat_code, default_incoterm, …) | Same as Customer Master (PUT upsert) | `customer_master.sqlite` | None | LOW | **keep** | (live) |

### 2.2 — User identity entities

| Entity | UI | API | DB | Missing | Risk | Verdict | Batch |
|---|---|---|---|---|---|---|---|
| **Users (read)** | `MasterDataPage::users` panel — table-only display | `GET /auth/users`, `GET /auth/users/{id}/active-reset-code` | `users.db` | None | LOW | **keep** | (live) |
| **Users (admin writes)** | **NONE** — buttons absent from MasterDataPage | `POST /auth/users/{id}/{approve,reject,role,activate,deactivate}` exist | `users.db` | UI buttons for the 5 write actions | **HIGH** — destructive identity actions | **implement, gated** | **B-MD1 approval first** |
| **Roles** | `PendingPanel` only (`live: false`) | None (no roles route) | No `roles` table; permissions live as boolean columns on users | Roles DAO + route + UI | **HIGH** — schema change + authz contract | **implement, gated** | **B-MD2 (Designs/Roles approval first)** |

### 2.3 — Product-side entities

| Entity | UI | API | DB | Missing | Risk | Verdict | Batch |
|---|---|---|---|---|---|---|---|
| **Products (wFirma)** | Read-only table | `GET /api/v1/wfirma/products` | wFirma authoritative | None | LOW | **keep** | (live) |
| **Product Local Augmentation** | List + PUT/DELETE in MasterDataPage (B5) | `routes_master_data.py` `/api/v1/product-local/*` (GET/PUT/DELETE) | `master_data.sqlite::product_local` | None | LOW | **keep** | (live) |
| **Designs** | `PendingPanel` only (`live: false`) | None | None (planned in MDC-2026-05/B6) | Full schema + DAO + 4 routes + panel + tests | **HIGH** — schema sign-off needed; product_identity_engine read-only consumer guarantee | **implement, gated** | **B-MD2 (Designs/Roles approval first)** |
| **HS Codes** | List + PUT/DELETE (B5) | `routes_master_data.py` `/api/v1/hs-codes/*` | `master_data.sqlite::hs_codes` | None | LOW | **keep** | (live) |
| **Units** | List + PUT/DELETE (B5) | `routes_master_data.py` `/api/v1/units/*` | `master_data.sqlite::units` | None | LOW | **keep** | (live) |
| **Incoterms** | List + PUT/DELETE (B7) | `routes_master_data.py` `/api/v1/incoterms/*` | `master_data.sqlite::incoterms` | None | LOW | **keep** | (live) |

### 2.4 — Finance & carrier entities

| Entity | UI | API | DB | Missing | Risk | Verdict | Batch |
|---|---|---|---|---|---|---|---|
| **VAT Config** | List + POST/PUT/DELETE (B7) | `routes_master_data.py` `/api/v1/vat-config/*` | `master_data.sqlite::vat_config` | None (read-only on invoicing per MDC-070 contract) | LOW | **keep** | (live) |
| **FX Rates** | List + POST/PUT/DELETE (B8) | `routes_master_data.py` `/api/v1/fx-rates/*` | `master_data.sqlite::fx_rates` | None — **MDC-071 PERMANENTLY FORBIDDEN** (FX never overrides PZ landed-cost) | LOW (with permanent rule) | **keep** | (live) |
| **Global Carrier Config** | List + PUT/DELETE (B9) | `routes_master_data.py` `/api/v1/carriers-config/*` | `master_data.sqlite::carriers_config` | None | LOW | **keep** | (live) |
| **Suppliers** | List + POST/PUT/DELETE (B4) | `routes_suppliers.py` (5 routes) | `suppliers.sqlite` | None | LOW | **keep** | (live) |

### 2.5 — Integration visibility

| Entity | UI | API | DB | Missing | Risk | Verdict | Batch |
|---|---|---|---|---|---|---|---|
| **wFirma Sync Visibility chip** | `wfirmaHint` column + per-batch chip (B10) | Read from `batches.wfirma_status_hint` | n/a | None | LOW | **keep** | (live) |
| **Finance posting breakdown panel** | `DiagnosticsPage` read-only panel (6F.4) | `GET /api/v1/finance/postings/{id}/breakdown` (6F.3) | `finance_postings.sqlite` (empty at closure) | None | LOW | **keep** | (live; P6F-2026-05) |

---

## 3 — Button-level classification

Each user-facing button reachable from `MasterDataPage` or `ClientKycModal`:

| Button | Where | Wires to | State | Verdict |
|---|---|---|---|---|
| **Add (Suppliers)** | Suppliers panel | `POST /api/v1/suppliers` | live | keep |
| **Edit (Suppliers)** | Suppliers row | `PUT /api/v1/suppliers/{id}` | live | keep |
| **Delete (Suppliers)** | Suppliers row `×` | `DELETE /api/v1/suppliers/{id}` | live | keep |
| **Save (Customer Master)** | KYC modal | `PUT /api/v1/customer-master/{id}` | live | keep |
| **Save (KYC tab)** | KYC modal | Same PUT | live | keep |
| **Save (Invoices tab)** | KYC modal | Same PUT | live | keep |
| **Add/Edit/Delete (Shipping Addresses)** | KYC modal Addresses tab | 4 routes | live | keep |
| **Add/Edit/Delete (Client Carrier Accounts)** | KYC modal Carriers tab | 4 routes | live | keep |
| **PUT/DELETE (HS/Units/PL/Incoterms/VAT/FX/Carriers)** | Each B5/B7/B8/B9 panel | `routes_master_data.py` | live | keep |
| **Approve user** | NOT IN UI | `POST /auth/users/{id}/approve` exists in backend | **MISSING** | **B-MD1 implement, gated** |
| **Reject user** | NOT IN UI | `POST /auth/users/{id}/reject` exists | **MISSING** | **B-MD1 implement, gated** |
| **Set Role** | NOT IN UI | `POST /auth/users/{id}/role` exists | **MISSING** | **B-MD1 implement, gated** |
| **Activate / Deactivate user** | NOT IN UI | `POST /auth/users/{id}/{activate,deactivate}` | **MISSING** | **B-MD1 implement, gated** |
| **Roles add/edit/delete** | NOT IN UI | Nothing — no routes | **MISSING (full stack)** | **B-MD2 implement, gated** |
| **Designs add/edit/delete** | NOT IN UI | Nothing — no routes | **MISSING (full stack)** | **B-MD2 implement, gated** |
| **Refresh (Re-check)** | MasterDataPage header | `loadUsers(); loadCustomers(); loadProducts(); …` (GETs only) | live | keep |
| **Open Profile** | Clients row | Opens `ClientKycModal` (no write on click) | live | keep |
| **Import CSV (any entity)** | NOT IN UI | Nothing | **N/A — not currently planned** | **disable / mark out-of-scope** |
| **Sync (wFirma manual)** | NOT IN UI | Existing wFirma read endpoints used implicitly | **N/A — not exposed as button** | **disable / mark out-of-scope** |

### 3.1 — Disabled / pending buttons inventory

| Pending surface | Where | Reason | Action |
|---|---|---|---|
| `PendingPanel` for Designs | `MasterDataPage` `activeEntity === 'designs'` | B6 schema sign-off needed | **B-MD2 approval, then implementation** |
| `PendingPanel` for Roles | `MasterDataPage` `activeEntity === 'roles'` | B-MD2 schema needed | **B-MD2 approval, then implementation** |
| Hidden anchors `master-pending-designs`, `master-pending-roles` | L5780-L5787 | Test compatibility; testids stay alive while panels show as pending | Keep until both go live |

---

## 4 — Security contract that gates B-MD1

`service/tests/test_dashboard_master_design.py` enforces two contracts that
block adding Users/Roles writes inside `MasterDataPage`:

| Contract | Function | Effect |
|---|---|---|
| Allowed write paths | `test_only_allowed_writes_in_master` (line 199–242) | POST/PUT/DELETE inside the MasterDataPage block must target one of: `/api/v1/suppliers`, `/api/v1/hs-codes`, `/api/v1/units`, `/api/v1/product-local`, `/api/v1/incoterms`, `/api/v1/vat-config`, `/api/v1/fx-rates`, `/api/v1/carriers-config`. `/auth/users/*` is **NOT** allowed. |
| No destructive identity buttons | `test_no_dangerous_destructive_buttons_in_master` (line 245–254) | Strings `>Approve<`, `>Reject<`, `>Deactivate<`, `>Suspend<`, `>Delete user<`, `>Delete client<` must not appear anywhere in `MasterDataPage`. |

To wire Users/Roles writes, the operator must choose one of:

- **(a) Relax both contracts** to include `/auth/users/*` and the destructive button labels. Security-sensitive; requires explicit operator approval.
- **(b) Move user admin to a separate `AdminUsersPage` outside `MasterDataPage`**. Cleaner boundary; both contracts stay intact; the new page lives at its own URL with its own write-safety review.

The Users/Roles approval package (`tasks/master-data-users-roles-approval-package.md`) recommends option **(b)**.

---

## 5 — Sequenced batch plan

| Batch | Title | Class | Approval gate | Implementation gate |
|---|---|---|---|---|
| **B-MD0** | This matrix doc | docs-only | n/a | n/a (this PR) |
| **B-MD1-approval** | Users/Roles writes — approval package | docs-only | (operator sign-off) | — |
| **B-MD1** | Users/Roles writes implementation (separate `AdminUsersPage`) | code | requires B-MD1-approval signed | mandatory operator sign-off + 8-agent review |
| **B-MD2-approval** | Designs master — schema + routes approval package | docs-only | (operator sign-off) | — |
| **B-MD2** | Designs master implementation | code | requires B-MD2-approval signed | mandatory schema review + product_identity_engine read-only-consumer guarantee |
| **B-MD3** | UI-only cleanup — disabled-state polish + testid hygiene | code | none (read-only-ish) | standard deploy |
| **B-MD4** | Browser smoke completion across all 13 live master-data entities | manual | none | standard smoke report |

This campaign **ends** when B-MD3 and B-MD4 ship. B-MD1 and B-MD2 are
operator-gated; deferring either is a defensible outcome.

---

## 6 — Hard stops for this campaign

The campaign STOPS if any batch needs:

- User role / security contract relaxation **without** explicit operator approval
- wFirma write
- Accounting / finance activation (P6F.5 flag flip; B-MD3 stays read-only)
- PZ / customs / DHL calculation change
- FX override into PZ landed-cost (MDC-071 — PERMANENT)
- Destructive schema operation (any DROP TABLE)
- Production DB edit
- `.env` change
- Irreversible external action

NOT hard stops (these are normal campaign output):

- Docs-only approval package
- Additive local SQLite table behind a feature flag
- Read-only endpoint
- Source-grep tests
- UI-only disabled-state cleanup
- Browser smoke

---

## 7 — Final risk register (for this matrix doc only)

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| MD1 | A future PR adds `/auth/users/*` POST inside `MasterDataPage` without first signing the B-MD1 approval | HIGH | `test_only_allowed_writes_in_master` + `test_no_dangerous_destructive_buttons_in_master` both already enforce; B-MD1 must update them together with the implementation |
| MD2 | A future PR adds a Designs CRUD without product_identity_engine read-only-consumer guarantee | HIGH | B-MD2 approval package must include the source-grep contract proving `product_identity_engine` never writes to the new Designs DB |
| MD3 | A future PR adds Roles writes via `/auth/users/{id}/role` without authz model approval | MEDIUM | B-MD1 approval explicitly covers the role-set endpoint as a separate decision |
| MD4 | MasterDataPage becomes a sprawling write surface that operators can no longer reason about | MEDIUM | Pin entity count + sidebar layout via existing source-grep tests; new entities require explicit panel addition |
| MD5 | KYC tabs accumulate write fields that bypass the Customer Master PUT | LOW | All current KYC writes go through the single `PUT /api/v1/customer-master/{id}`; B-MD3 polish does not add new write endpoints |

---

## 8 — Recommended next batch

**B-MD1 approval package.** It is docs-only, zero-risk, and unblocks the
last destructive write surface that the prior campaign (MDC-2026-05/B3)
left explicitly gated.

If the operator defers B-MD1 indefinitely, the defensible alternative is
**B-MD2 approval package** (Designs master). It is also docs-only and
operator-decision-only. Both packages can be authored independently.

Implementing either is forbidden until the matching package is signed.
