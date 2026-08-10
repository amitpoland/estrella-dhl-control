# RBAC Slice 0 — Duplicate-authority audit + implementation record

**Date:** 2026-08-11  
**Pin / branch:** `feat/rbac-slice-0` from `origin/main` @ `7150996b`  
**Worktree:** `C:\PZ-wt\rbac-s0`  
**Verdict:** **GO** (implemented)

---

## Existing authority map

| Concern | Existing owner | Consumers | Keep / extend / retire | Duplicate? |
|---|---|---|---|---|
| Role catalogue | `auth/service.py::ROLES` | routes_auth validators, capabilities, Admin Users dropdowns | **CANONICAL — EXTEND** (+`crm`) | Stale 5-role dropdowns were drift (fixed) |
| Role → permissions | *(none pre-Slice 0)* | — | **CANONICAL NEW** `auth/permissions.py::ROLE_PERMISSIONS` | No prior catalogue |
| Fake FE role matrix | `master-page.jsx::ROLE_MATRIX` (`admin/manager/operator/viewer`) | Master Acting-as simulator only | **LEGACY** — do not use as authority; retire later | YES (fake) |
| Write-capable roles | `security.py::_WRITE_CAPABLE_ROLES` | `require_api_key_privileged` | **KEEP** (API layer; not human catalogue) | Derived parallel — ranked under ROLES |
| Master role gate | `role_gate.py` + `master_role_enforcement` | Master write routes | **KEEP** isolated; flag still False | Namespace subset of ROLES |
| `/auth/me` | `routes_auth.me` → `_safe_user` | V1/V2 pages | **CANONICAL — EXTEND** (+permissions, landing) | NO |
| User admin UI | `AdminUsersPage` + `/admin/users` | Admin operators | **CANONICAL keep**; no new page | Standalone HTML = LEGACY twin surface |
| Master Users tab | `master-page.jsx` read-only | V2 Master | **CONSUMER / LEGACY** (writes still disabled) | Not a second admin |
| Master Roles tab | capabilities / STATIC_ROLES_NAMES | V2 Master | **CONSUMER** of ROLES | OK |
| NAV_TREE V1/V2 | dashboard.html / v2/components.jsx | Sidebars | **KEEP** (shell only) | V2 missing admin_users nav = gap later |
| Landing | hard `/dashboard` in login.html | Login | **EXTEND later (Slice 1)**; Slice 0 stores fields + `/auth/me` | NO second map |
| API-key | `require_api_key*` | Routes | **KEEP** — machine auth ≠ human auth | No second key catalogue |

### Canonical survivors
1. `ROLES` + `ROLE_PERMISSIONS` + `ROLE_LANDING` (backend auth package)  
2. `/auth/me` via `_safe_user` → `build_authority_fields`  
3. AdminUsersPage / `/admin/users` for user admin presentation  
4. Master page for Master Data presentation (consumes roles list; fake ROLE_MATRIX LEGACY)

### Retirement plan (later slices — not deleted in Slice 0)
| Item | Plan |
|---|---|
| `ROLE_MATRIX` Acting-as | Retire / replace with session `/auth/me` permissions |
| Standalone `admin-users.html` | Converge to AdminUsersPage or keep as LEGACY redirect |
| Dead `_ROLE_RANK` | Retire or wire intentionally |
| Hard-coded login `/dashboard` | Slice 1 consumer of `default_surface`/`default_page` |

### Master-page reuse
- No new Master / Users / RBAC page created  
- `STATIC_ROLES_NAMES` extended with `crm` to mirror `ROLES`  
- Users write still disabled on Master (points at admin endpoints)

---

## Slice 0 delivered

| Item | Location |
|---|---|
| Permission catalogue | `service/app/auth/permissions.py` |
| Nine-role map | `ROLE_PERMISSIONS` + `ROLES` (+`crm`) |
| Landing authority | `default_surface` / `default_page` columns + `ROLE_LANDING` |
| `/auth/me` | `_safe_user` adds `permissions`, `default_surface`, `default_page` |
| Safe migration | `init_db` column add + `_backfill_landing_defaults`; `create_user` / `set_user_role` set landing |
| Consumer sync | `ADMIN_USERS_ROLES`, signup/admin-users selects, STATIC_ROLES_NAMES |

### Explicitly NOT done (correct)
- No Tier-0 route tightening  
- No `require_permission` helper  
- No API-key permission catalogue  
- No new admin/RBAC page  
- Login still hard-redirects to `/dashboard` (Slice 1)

---

## Tests
`tests/test_rbac_slice0_authority.py` + updated role allow-list pins — **37 passed** with related auth design tests.

---

## Security
- Logistics has **zero** `FISCAL_FINALIZE_PERMISSIONS` in catalogue map  
- CRM narrow; master_* isolated  
- Unknown role → empty permissions  
- Fiscal route gates **unchanged** (still GAP until Slice 2) — documented  

---

## GO/HOLD
**GO** — single canonical role catalogue identified; Slice 0 implemented without a third abstraction.
