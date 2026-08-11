# RBAC Slice 1 — duplicate-authority disposition (pre-edit audit)

**Date:** 2026-08-11  
**Tree:** `C:\PZ-wt\rbac-s1` @ branch `feat/rbac-slice-1` (base `ce73770f`)  
**Reconciled against:** Slice 0 payload ancestor `e06b8687` / main merge `ce73770f`

## Classification

| Site | Disposition | Notes |
|---|---|---|
| Backend `auth/permissions.py` catalogue + `ROLE_LANDING` | **KEEP** | Sole authority |
| `/auth/me` + login user payload | **CONSUME** | Extended with `allowed_pages` (derived binder, not a second catalogue) |
| `login.html` hard `/dashboard` | **CONSUME** | Uses `default_surface` + `default_page` |
| `main.py` `/`, `/dashboard`, `/login`, `/signup`, non-admin `/admin/users` | **CONSUME** | `landing_url_for_user` |
| `admin-users.html` non-admin bounce | **CONSUME** | Landing from `/auth/me` |
| V2 `NAV_TREE` structure | **KEEP** | Structure only |
| V2 Sidebar / SubTabStrip visibility | **CONSUME** | Filter via `allowed_pages` from `/auth/me` |
| V2 `index.html` routing / `handleNav` / popstate | **CONSUME** | Direct URL deny → `default_page` |
| V1 `dashboard.html` NAV_TREE | **KEEP** | V1 frozen; landing prefers V2 |
| Master `ROLE_MATRIX` / Acting-as | **KEEP** (Slice 1) / **RETIRE-LATER** | Not required to remove for Slice 1 |
| `pz-design-v2.js` stale NAV | **RETIRE-LATER** | Not a Slice 1 consumer |
| `pages-v2.jsx` `role === 'admin'` DHL UI | **KEEP** | Local action visibility; not landing |
| AdminUsers role allow-lists | **KEEP** | Synced with `ROLES` |
| Tier-0 fiscal `require_*` API auth | **KEEP** / **DO NOT TOUCH** | Out of Slice 1 |

## Explicit non-goals (this slice)

- No frontend permission catalogue / role→permission matrix / landing map
- No Tier-0 fiscal / wFirma / PZ finalize / inventory / DHL execution / calc changes
- No Master `ROLE_MATRIX` removal
