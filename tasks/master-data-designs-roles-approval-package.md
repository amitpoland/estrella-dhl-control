# B-MD2 — Designs + Roles Master — Approval Package

> **Status:** docs-only, awaiting operator sign-off. NO code change.
> NO implementation begins until §16 is signed.
> **Predecessor:** B-MD1 (Admin · Users) merged, deployed, smoked.
> Both `Designs` and `Roles` are still rendered as `PendingPanel` in
> `MasterDataPage`. This package proposes how to graduate them to
> live, with explicit operator-gated boundaries for each.
> **Campaign:** `MDOC-2026-05` / batch `B-MD2`. **Date:** 2026-05-16.

This document is the docs-only design contract that gates the B-MD2
implementation PR. Implementation begins ONLY after §16 is signed.

---

## 1 — Current state matrix

### 1.1 — Designs

| Surface | Today | Evidence |
|---|---|---|
| UI | `PendingPanel` only (`live: false`) at `MasterDataPage` `activeEntity === 'designs'` | `dashboard.html` L3761, L4503–4507 |
| API | None — no `routes_designs.py` exists | file inventory |
| DB | None — no `designs` table; no design DAO | `service/app/services/master_data_db.py` line 28–137 lists only HsCode/Unit/ProductLocal/CarrierConfig/Incoterm/FxRate/VatConfig |
| Consumers | `product_identity_engine.py` computes identity from raw `karat`/`metal_color`/`description_pl` inputs (does NOT read a designs table today). `design_product_bridge.py` is a packing-side helper that maps packed design codes → product codes (NOT a master). `routes_master_data.py::ProductLocal` has a `design_code_link` column that is just a free-text string today. |  |
| Hidden anchors | `master-pending-designs` testid stays alive while panel shows as pending | `dashboard.html` L5784 |

### 1.2 — Roles

| Surface | Today | Evidence |
|---|---|---|
| UI (display) | `PendingPanel` only (`live: false`) at `MasterDataPage` `activeEntity === 'roles'`; AdminUsersPage role dropdown (B-MD1) | `dashboard.html` L3778, L5769–5773; AdminUsersPage live |
| API | `POST /auth/users/{id}/role` exists; **no `/auth/roles` collection route** | `routes_auth.py` L403–409 |
| DB | Free-text `users.role` column. **No `roles` table. No permission matrix.** | `users.db` schema |
| Allow-list | `ROLES = ("admin", "accounts", "logistics", "auditor", "viewer")` | `service/app/auth/service.py` L18 |
| Enforcement | **`require_admin` is the ONLY role gate in production today.** Maps to `role == "admin"`. The other 4 roles (`accounts`, `logistics`, `auditor`, `viewer`) exist as legal string values but have ZERO enforcement points across the API surface. | `grep -rn "require_admin\|require_role" service/app/api/` |
| Hidden anchors | `master-pending-roles` testid | `dashboard.html` L5784 |

---

## 2 — Existing UI / buttons

| Surface | Buttons |
|---|---|
| MasterDataPage `designs` entity | None (pending panel) |
| MasterDataPage `roles` entity | None (pending panel) |
| AdminUsersPage (B-MD1, live) | Set role ▾ (admin / accounts / logistics / auditor / viewer) — already wired |

No write buttons exist for Designs or Roles entity panels.

---

## 3 — Existing APIs

| Verb | Path | Status | Used by |
|---|---|---|---|
| GET | `/api/v1/hs-codes/` etc. | live (B5) | MasterDataPage |
| POST | `/auth/users/{id}/role` | live (B-MD1) | AdminUsersPage |
| (none) | `/api/v1/designs/*` | **not built** | n/a |
| (none) | `/auth/roles/*` | **not built** | n/a |
| (none) | permission-matrix endpoints | **not built** | n/a |

---

## 4 — Existing DB / models

- `master_data.sqlite` has tables: `hs_codes`, `units`, `product_local`, `carriers_config`, `incoterms`, `fx_rates`, `vat_config`. **No `designs` table.**
- `users.db` (auth) has the `users` row schema with a free-text `role` column. **No `roles` table. No `role_permissions` table.**

---

## 5 — Missing backend

### 5.1 — Designs

To go live, designs needs:

- `service/app/services/designs_db.py` — new DAO: `Design` dataclass, `init_db`, `validate_design`, `upsert_design`, `get_design`, `list_designs`, `delete_design`. Storage in `master_data.sqlite::designs` (additive).
- `service/app/api/routes_designs.py` — 4 read/write endpoints (`GET /api/v1/designs/`, `GET /api/v1/designs/{code}`, `PUT /api/v1/designs/{code}` for upsert, `DELETE /api/v1/designs/{code}`), each `dependencies=[_auth]`.
- Router registration in `main.py`.

### 5.2 — Roles

Two options (decision in §16):

**Option A — keep current free-text `role` column.** Continue using the literal `ROLES` allow-list in `auth/service.py`. The Roles panel becomes a READ-ONLY explainer page (not a write surface). No new backend.

**Option B — add a `roles` table + permission matrix.** New DAO, new routes (`GET /auth/roles`, `PUT /auth/roles/{role_code}` upserting permission flags). Requires `auth_db.py` schema migration. **B-MD2 recommends Option A.** Option B is deferred to a separate write-bearing batch with its own approval.

---

## 6 — Missing frontend

| Entity | Missing |
|---|---|
| Designs | Whole panel inside `MasterDataPage` `activeEntity === 'designs'` — list + add + edit + delete. Source-grep tests. |
| Roles | Either (Option A) a small read-only panel explaining the 5 roles + which one is enforced (admin via `require_admin`) + AdminUsersPage as the role-editing surface, OR (Option B, deferred) a full CRUD UI with permission matrix editor. |

---

## 7 — Proposed schema (additive only)

### 7.1 — Designs table — `master_data.sqlite::designs`

```sql
CREATE TABLE IF NOT EXISTS designs (
    design_code      TEXT PRIMARY KEY,           -- canonical short code (e.g. "EJ-PD-001")
    design_family    TEXT NOT NULL,              -- e.g. "Pendant", "Ring"
    item_type        TEXT NOT NULL,              -- mirrors product_identity_engine vocab
    karat            TEXT,                       -- e.g. "14K", "18K", "925"
    material         TEXT,                       -- e.g. "Gold", "Silver", "Platinum"
    stone_type       TEXT,                       -- nullable; e.g. "Diamond"
    stone_weight_ct  TEXT,                       -- string-decimal; nullable
    color            TEXT,                       -- e.g. "Yellow", "White"
    name_pl          TEXT,                       -- bilingual name (Polish)
    name_en          TEXT,                       -- bilingual name (English)
    hs_code          TEXT,                       -- FK-by-value to hs_codes.hs_code
    unit             TEXT,                       -- FK-by-value to units.code
    active           INTEGER NOT NULL DEFAULT 1, -- bool
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
```

No foreign-key constraints enforced at SQL level (consistent with existing master-data table style). FK-by-value soft-references documented at the application layer.

### 7.2 — Roles (Option A — recommended)

**No schema change.** Continue using the 5-value `ROLES` allow-list. Document the enforcement matrix in a new operator-facing page:

| Role | Login allowed | Admin write actions | Master Data writes | Master Data reads |
|---|---|---|---|---|
| admin | yes | yes (require_admin) | yes (existing API auth) | yes |
| accounts | yes | no | yes (existing API auth) | yes |
| logistics | yes | no | yes (existing API auth) | yes |
| auditor | yes | no | yes (existing API auth) | yes |
| viewer | yes | no | yes (existing API auth) | yes |

**Important:** until a permission-enforcement engine ships, only the `admin` gate is differentially enforced. The other 4 roles all have identical API privileges. This is honest reality; the panel must say so.

### 7.3 — Roles (Option B — deferred, not in B-MD2)

If approved later as a SEPARATE batch:

```sql
CREATE TABLE IF NOT EXISTS roles (
    role_code        TEXT PRIMARY KEY,
    role_name        TEXT NOT NULL,
    description      TEXT,
    can_admin_users  INTEGER NOT NULL DEFAULT 0,
    can_master_write INTEGER NOT NULL DEFAULT 0,
    can_post_wfirma  INTEGER NOT NULL DEFAULT 0,
    can_close_settl  INTEGER NOT NULL DEFAULT 0,
    can_view         INTEGER NOT NULL DEFAULT 1,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
```

This is **explicitly out of scope for B-MD2** because:
1. Building the table without enforcement code creates a false sense of security.
2. Enforcement requires touching every write route to add `require_role(...)`.
3. Operator should see the design fully scoped before the implementation begins.

---

## 8 — Proposed API routes (B-MD2 scope)

| Verb | Path | Purpose | Auth | Body |
|---|---|---|---|---|
| GET | `/api/v1/designs/` | List designs | `_auth` (existing API key) | n/a |
| GET | `/api/v1/designs/{design_code}` | Get one | `_auth` | n/a |
| PUT | `/api/v1/designs/{design_code}` | Upsert | `_auth` | `Design` JSON |
| DELETE | `/api/v1/designs/{design_code}` | Delete | `_auth` | n/a |

Roles endpoints in B-MD2: **none new**. Existing `POST /auth/users/{id}/role` continues to be the only role-writer (via AdminUsersPage).

---

## 9 — Proposed UI placement

### 9.1 — Designs

Inside `MasterDataPage` (sidebar entity already exists). Pattern mirrors B5 entities (HS / Units / ProductLocal):

- Replace the `PendingPanel` block at L4502 with a real list + edit panel.
- Reuse `b5Save` / `b5Delete` generic helpers (basePath = `/api/v1/designs`).
- Toggle `live: true` for the `designs` sidebar entry (L3761).
- Remove `'designs'` from the hidden `master-pending-grid` (L5784).

### 9.2 — Roles

Inside `MasterDataPage` (sidebar entity already exists). Pattern: **read-only explainer panel** describing the 5 roles + the enforcement matrix from §7.2. NO writes from this panel. Role edits stay in AdminUsersPage.

- Replace `PendingPanel` at L5769 with a read-only table showing the 5 roles.
- Keep `live: false` semantically (no count) OR introduce a new `live: 'read_only'` flag — operator decision (§16).
- A clear "Role assignments are managed in Admin · Users" link to AdminUsersPage.

---

## 10 — Button map

### 10.1 — Designs

| Button | Endpoint | Payload | DB | UI location | Risk | Decision | Test |
|---|---|---|---|---|---|---|---|
| Add design | `PUT /api/v1/designs/{code}` | full `Design` body | `designs.*` | `MasterDataPage::designs` top form | LOW | implement | `test_designs_add_calls_correct_endpoint` |
| Edit design | `PUT /api/v1/designs/{code}` | partial-or-full body | same | per-row | LOW | implement | `test_designs_edit_calls_correct_endpoint` |
| Delete design | `DELETE /api/v1/designs/{code}` | none | same | per-row `×` | LOW | implement | `test_designs_delete_calls_correct_endpoint` |
| Activate/Deactivate toggle | `PUT /api/v1/designs/{code}` body `{active: bool}` | same | same | per-row toggle | LOW | implement | `test_designs_toggle_active` |
| Refresh | `GET /api/v1/designs/` | n/a | (read) | panel header | LOW | implement | `test_designs_refresh_is_safe_get` |

### 10.2 — Roles (read-only)

| Button | Action | Decision |
|---|---|---|
| (no buttons) | n/a | **explainer panel only** |
| "Manage role assignments →" link | navigates to `admin_users` page | implement (`onNav('admin_users')`) |

---

## 11 — Test plan

### 11.1 — Designs (`service/tests/test_dashboard_designs_panel.py`, NEW)

- `test_designs_panel_renders_at_route`
- `test_designs_panel_calls_only_designs_endpoints`
- `test_designs_panel_uses_b5_helpers` (write helpers, no inline POST)
- `test_designs_panel_has_add_edit_delete_buttons`
- `test_designs_sidebar_marked_live`
- `test_designs_removed_from_pending_grid`

### 11.2 — Designs backend (`service/tests/test_designs_db.py`, NEW)

- `test_init_db_idempotent`
- `test_upsert_design_round_trip`
- `test_validate_design_required_fields` (design_code, design_family, item_type)
- `test_list_designs_active_filter`
- `test_delete_design_returns_404_when_missing`
- `test_design_decimal_safety_on_stone_weight_ct` (Decimal-via-string)

### 11.3 — Designs route (`service/tests/test_routes_designs.py`, NEW)

- `test_designs_list_endpoint`
- `test_designs_upsert_endpoint`
- `test_designs_get_endpoint`
- `test_designs_delete_endpoint`
- `test_designs_require_auth`

### 11.4 — Roles (`service/tests/test_dashboard_roles_panel.py`, NEW)

- `test_roles_panel_renders_at_route`
- `test_roles_panel_lists_five_roles_exactly`
- `test_roles_panel_marks_admin_as_enforced_only`
- `test_roles_panel_has_no_write_buttons` (no apiFetch POST/PUT/DELETE inside the roles block)
- `test_roles_panel_links_to_admin_users_page`
- `test_roles_sidebar_remains_read_only_marked`

### 11.5 — Cross-checks (extend existing files)

- `test_dashboard_master_design.py::test_b5_entities_are_live` extended to include `designs`
- `test_dashboard_master_design.py::test_only_allowed_writes_in_master` extended allow-list to include `/api/v1/designs/`
- `test_master_data_hard_rules.py::test_product_identity_engine_does_not_read_designs_table` (NEW source-grep proving the engine remains a read-only consumer of inputs, not a reader of the new `designs` table)

---

## 12 — Source-grep contracts

### 12.1 — Designs

| Contract | Pins |
|---|---|
| Add `/api/v1/designs` to `_ALLOWED_REFERENCES` and to `allowed_writes` in `test_only_allowed_writes_in_master` | Surgical extension of existing security contract |
| `routes_designs.py` exposes only `_auth`-gated routes | No new admin-only privilege |
| `designs_db.py` does not import `wfirma_client`, `landed_cost`, `fx_*`, `proforma_*` | Isolation contract |
| `product_identity_engine.py` does not import or call `designs_db` | Read-only-consumer guarantee |
| `design_product_bridge.py` does not call `designs_db.upsert_design` | Packing helper stays read-only against the new master |

### 12.2 — Roles

| Contract | Pins |
|---|---|
| Roles panel contains zero `apiFetch(...)` calls | Read-only |
| Roles panel does not contain strings `>Save<`, `>Delete role<`, `>Add role<` | No write buttons |
| `auth/service.py::ROLES` tuple remains exactly 5 values | Allow-list stable |
| No new file under `service/app/auth/` | No auth surface mutation |
| `routes_auth.py` byte-identical to pre-B-MD2 (other than possibly imports) | No auth route added |

---

## 13 — Deploy plan

### 13.1 — Two-PR split (recommended)

1. **B-MD2a — Designs backend.** Files: `designs_db.py`, `routes_designs.py`, `main.py` register, `test_designs_db.py`, `test_routes_designs.py`. Backend-only deploy (PZService restart needed because new routes register). **No UI change.** Default UI still shows PendingPanel.
2. **B-MD2b — Designs UI.** Files: `dashboard.html`, `test_dashboard_designs_panel.py`, panel testid updates. UI deploy via robocopy + PZService restart.
3. **B-MD2c — Roles read-only explainer.** Files: `dashboard.html` (Roles panel replaced with read-only table), `test_dashboard_roles_panel.py`. UI deploy.

Each PR runs the standard 7-agent gate. Splitting reduces blast radius and makes rollback selective.

### 13.2 — Single-PR alternative

Acceptable if operator prefers, but more risk on rollback. The two-PR split keeps Designs functional even if Roles needs revert (and vice versa).

---

## 14 — Rollback plan

| Path | Cost | Reversibility |
|---|---|---|
| **A — Code revert** (per-PR) | Full deploy cycle for that PR | Full. `git revert -m 1 <merge-sha> --no-edit`. |
| **B — Hide UI panel** | UI redeploy (revert the dashboard.html change for the affected entity) | Full. Backend designs table remains; just not surfaced. |
| **C — Backend disable** | Edit `main.py` to skip `include_router(designs_router)`; PZService restart | Routes return 404. Useful if a designs route ships with a bug. |
| **D — Drop the new table** (Designs only) | Manual SQL: `DROP TABLE designs;` against `master_data.sqlite` | Destructive — only after operator approval; backup first. |

No rollback path for Roles requires SQL — Option A (the only recommended path in this batch) is purely a UI panel replacement. If the Roles panel ships wrong, Path B is sufficient.

---

## 15 — Hard stops

Implementation STOPS if any of the following becomes true:

| Stop | Reason |
|---|---|
| HS1 | Designs implementation would require `product_identity_engine` to read the new `designs` table | Engine must stay a read-only consumer of its raw inputs; coupling to a writable master creates a corruption path |
| HS2 | Designs implementation would require any FK constraint enforced at SQL level | Existing master-data tables use FK-by-value soft-references; SQL constraints would be a schema philosophy change |
| HS3 | Roles implementation as Option B (`roles` table + permission matrix) | Out of scope for B-MD2; requires its own approval + enforcement engine batch |
| HS4 | Adding `require_role` enforcement points to any existing write route | Out of scope; would silently restrict legitimate operator actions |
| HS5 | `routes_auth.py` would gain a new route | No auth surface mutation in B-MD2 |
| HS6 | Auth schema (`users.db`) migration | No auth schema change |
| HS7 | Any PZ / customs / DHL / FX / wFirma / finance / settlement coupling | Phase 6F still paused; B-MD2 must stay isolated |
| HS8 | `.env` change | Not needed for this batch |
| HS9 | Production DB edit | Standard robocopy + restart only |
| HS10 | The 6F.5 dual-write flags would be flipped | Independent batch; not touched by B-MD2 |
| HS11 | A future PR uses B-MD2 deploy as cover to relax B-MD1's MasterDataPage security contracts | Both contracts must stay green; cross-check tests pin this |

---

## 16 — Operator decision block

```
B-MD2 Designs + Roles Master — Operator Approval

Read this entire document:                                  ___ (yes / no)

Approves Designs master schema in §7.1:                     ___ (yes / no)
Approves Designs API surface in §8:                         ___ (yes / no)
Approves Designs UI placement inside MasterDataPage in §9.1: ___ (yes / no)
Approves Roles Option A (read-only explainer panel; no schema): ___ (yes / no)
       OR
       Defers Roles to a separate batch (Option B):        ___ (yes / no)

Approves §11 test plan (≥ 25 new tests across 4 files):     ___ (yes / no)
Approves §12 source-grep contracts (10 contracts):          ___ (yes / no)
Approves §13.1 two-PR split (B-MD2a backend, B-MD2b UI, B-MD2c roles): ___ (yes / no)
Approves §14 rollback plan:                                 ___ (yes / no)
Approves §15 hard stops:                                    ___ (yes / no)
Confirms product_identity_engine read-only-consumer guarantee: ___ (yes / no)

Approved by:    __________________________
Date/time:      __________________________
Notes:
```

Until §16 is signed, `B-MD2` remains `blocked`. The PendingPanel for
both entities continues to render in production. AdminUsersPage stays
the role-editing surface.

---

## 17 — Exact next command if approved

```bash
# 1. Implementer creates the B-MD2a backend branch first.
cd "C:/Users/Super Fashion/PZ APP"
git checkout main && git pull --ff-only origin main
git checkout -b feat/b-md2a-designs-backend

# Allowed files (no others without re-approval):
#  - service/app/services/designs_db.py (NEW)
#  - service/app/api/routes_designs.py (NEW)
#  - service/app/main.py (1 import + 1 include_router line)
#  - service/tests/test_designs_db.py (NEW)
#  - service/tests/test_routes_designs.py (NEW)
#  - tasks/campaign-state.json

# 2. Run gates BEFORE pushing.
cd service
python -m pytest tests/test_designs_db.py tests/test_routes_designs.py -v
python -m pytest tests/test_dashboard_master_design.py -q   # unchanged
python -m pytest tests/test_master_data_hard_rules.py tests/test_runner_v2_hard_rules.py -q
cd ..
PYTHONIOENCODING=utf-8 python test_pz_regression.py   # must be 160/160
python service/scripts/campaign_status.py doctor

# 3. After all green: open PR, run 7-agent deploy gate.
# 4. Then proceed to B-MD2b UI (separate PR) only after B-MD2a deploys + smokes.
# 5. Then B-MD2c Roles read-only panel (separate PR).
```

Lessons L-037 (deployed != activated), L-040 (inspection-only batches
close decisions without writing code), L-041 (paused campaigns need a
single closure doc), L-042 (inherit the security contract; don't relax
it), L-043 (frontend constants mirroring backend allow-lists need
pinned tests), and L-044 (destructive smoke without a safe test user
is a deferral, not a defect) all apply to B-MD2.
