# B-MD1 — Users/Roles Writes — Implementation Plan

> Implementation companion to `tasks/master-data-users-roles-approval-package.md`.
> Maps every B-MD1 button to its exact endpoint, payload, DB column, UI
> location, risk, and test. No new schema. No new backend route. Only UI
> wiring + contract tests.
> **Campaign:** `MDOC-2026-05` / batch `B-MD1`. **Date:** 2026-05-16.

---

## 1 — Multi-agent classification

| Agent | Verdict |
|---|---|
| Architecture | `AdminUsersPage` is a NEW top-level page component, separate from `MasterDataPage`. New nav child `admin_users` under existing `g_setup` group. Admin-gated render at top-level page switch. **Both existing MasterDataPage security contracts stay intact.** |
| Backend/API | All 5 admin write endpoints already exist in `service/app/api/routes_auth.py` (lines 363–429), protected by `Depends(require_admin)`. `SetRoleRequest` (line 101) validates role against the literal `ROLES` allow-list. **No backend changes.** |
| DB/schema | Auth store is `<storage_root>/users.db`. Free-text `role` column. **No migration. No schema change.** |
| Frontend/UI | Component at the bottom of `dashboard.html` near `AdminPage`. Page-switch entry under existing `{page === 'admin'}` block. New `'admin_users'` nav child entry. |
| Security/write-safety | Self-lockout guard (hide actions on `row.id === user.id` for reject/deactivate/role). Confirm dialog on every write. Admin-only render gate. Existing backend admin check on every route is the authoritative gate. |
| QA/regression | 9 new source-grep contracts in `test_dashboard_admin_users_design.py`. 5 new route tests in `test_auth_admin_user_routes.py` covering require_admin + 403 + 404. Existing MasterDataPage contracts re-run unchanged. |
| Release/deploy | Single file changed in `service/app/`: `dashboard.html`. Standard robocopy + PZService restart. No backend deploy artifact. Rollback: `git revert -m 1 <merge-sha>` + redeploy. |
| Browser/API smoke | 10 UI smoke checks + 2 backend curl checks defined in §3 of approval package; mirrored in §7 below. |

**Classification confirmed:** B-MD1 is **safe to implement in this run** as a UI-only batch over already-deployed admin write endpoints.

---

## 2 — Existing API surface (no change)

| Verb | Path | Payload | DB column updated | Response |
|---|---|---|---|---|
| GET | `/auth/users` | n/a | (read) | `[{id, email, full_name, role, is_approved, is_active, approval_status, created_at, last_login}, ...]` |
| GET | `/auth/me` | n/a | (read) | `{id, email, full_name, role, ...}` (used to detect admin + self-row) |
| POST | `/auth/users/{id}/approve` | (none) | `is_approved`, `approval_status` | `{ok, message}` + queues approval email |
| POST | `/auth/users/{id}/reject` | (none) | `is_approved=false`, `approval_status="rejected"` | `{ok, message}` + queues rejection email. Backend rejects self-reject with 400. |
| POST | `/auth/users/{id}/role` | `{role: <one of admin/accounts/logistics/auditor/viewer>}` | `role` | `{ok, message}` |
| POST | `/auth/users/{id}/activate` | (none) | `is_active=true` | `{ok}` |
| POST | `/auth/users/{id}/deactivate` | (none) | `is_active=false` | `{ok}`. Backend rejects self-deactivate with 400. |

ROLE allow-list (from `service/app/auth/service.py::ROLES`):
`admin`, `accounts`, `logistics`, `auditor`, `viewer`.

---

## 3 — Button matrix

| Button | Existing API | Payload | DB/model | UI location | Risk | Decision | Test |
|---|---|---|---|---|---|---|---|
| **Approve user** | `POST /auth/users/{id}/approve` | none | `users.is_approved/approval_status` | Per-row, visible when `approval_status === "pending"` | LOW (backend handles all gating) | **implement** | `test_approve_button_present`, `test_approve_calls_correct_endpoint`, `test_approve_has_confirm` |
| **Reject user** | `POST /auth/users/{id}/reject` | none | `users.is_approved/approval_status` | Per-row, visible when `approval_status === "pending"`; hidden on self-row | MEDIUM (sends email; backend 400 on self) | **implement** | `test_reject_button_present`, `test_reject_calls_correct_endpoint`, `test_reject_has_confirm`, `test_reject_hidden_on_self_row` |
| **Set role** | `POST /auth/users/{id}/role` | `{role: <ROLES allow-list>}` | `users.role` | Per-row dropdown, hidden on self-row | MEDIUM (privilege change) | **implement** | `test_role_select_pinned_values`, `test_role_calls_correct_endpoint`, `test_role_has_confirm`, `test_role_hidden_on_self_row` |
| **Activate user** | `POST /auth/users/{id}/activate` | none | `users.is_active=true` | Per-row, visible when `is_active === false` | LOW | **implement** | `test_activate_button_present`, `test_activate_calls_correct_endpoint` |
| **Deactivate user** | `POST /auth/users/{id}/deactivate` | none | `users.is_active=false` | Per-row, visible when `is_active === true && approval_status === "approved"`; hidden on self-row | MEDIUM | **implement** | `test_deactivate_button_present`, `test_deactivate_calls_correct_endpoint`, `test_deactivate_has_confirm`, `test_deactivate_hidden_on_self_row` |
| **Refresh users** | `GET /auth/users` | n/a | (read) | Header button | LOW | **implement** | `test_refresh_calls_only_users_get` |
| **Search/filter (client-side)** | n/a | n/a | n/a | Header text input | LOW | **implement** | `test_search_is_client_side` |
| **Invite / Create user** | NOT in scope | n/a | n/a | Disabled chip with "Backend pending / out of scope. Use /auth/signup" | LOW | **disabled, labelled** | `test_no_create_user_write_path` |

---

## 4 — Component shape

```
AdminUsersPage  (rendered at page === 'admin_users')
├── Admin gate: render Access Denied banner if user.role !== 'admin'
├── Header
│   ├── Title: "Admin · Users"
│   ├── Search input (client-side filter on email + full_name + role)
│   ├── Refresh button (GET /auth/users)
│   └── Disabled "Invite user" chip with explanation
├── Counters: Total / Pending / Approved / Inactive
├── Table
│   ├── Cols: Full name · Email · Role · Status · Created · Last login · Actions
│   └── Per-row Actions cell:
│       • If row.id === currentUserId: "—" (self-lockout guard)
│       • If approval_status === "pending": [Approve] [Reject]
│       • Else if approval_status === "approved" && is_active:
│            [Set role ▾]  [Deactivate]
│       • Else if is_active === false: [Activate]
└── Per-action confirm dialog (native window.confirm with explicit message)
```

---

## 5 — Nav wiring

In `NAV_TREE.g_setup.children` (line ~99 of `dashboard.html`), insert
`{ id: 'admin_users', label: 'Admin · Users' }` between `admin` and
`master`. Top-level page switch adds:
`{page === 'admin_users' && <AdminUsersPage user={user} onNav={handleNav} onToast={notify} />}`.

Visibility of the nav entry follows the standard admin-detection used
elsewhere (`user.role === 'admin'`). Operators without admin role see
the page render an Access Denied banner if they navigate by URL.

---

## 6 — Source-grep contract tests

`service/tests/test_dashboard_admin_users_design.py` (NEW, ≥ 12 tests):

| Test | Pins |
|---|---|
| `test_admin_users_page_function_present` | `function AdminUsersPage(` declaration |
| `test_admin_users_page_renders_at_route` | `<AdminUsersPage` rendered when `page === 'admin_users'` |
| `test_admin_users_nav_entry_present` | `'admin_users'` entry in `NAV_TREE.g_setup.children` |
| `test_admin_users_admin_gate_present` | `user.role === 'admin'` (or equivalent admin check) inside AdminUsersPage |
| `test_admin_users_calls_only_allowed_endpoints` | Every `apiFetch` inside the AdminUsersPage block targets ONLY `/auth/users` or `/auth/users/{id}/...` |
| `test_admin_users_uses_post_for_writes` | All 5 write actions use `method: 'POST'`; no PATCH/DELETE |
| `test_admin_users_role_dropdown_pinned_values` | Role options match the backend `ROLES` allow-list exactly (`admin`, `accounts`, `logistics`, `auditor`, `viewer`) |
| `test_admin_users_no_create_or_delete_user_buttons` | Strings `>Create user<`, `>Delete user<`, `>Remove user<` not present (Invite button if any must be disabled+labelled) |
| `test_admin_users_has_self_lockout_guard` | `row.id === user.id` self-guard near actions |
| `test_admin_users_has_confirm_for_writes` | `window.confirm` (or equivalent) invoked before each write |
| `test_admin_users_refresh_is_safe_get` | Refresh action calls `/auth/users` GET only |
| `test_master_data_page_still_clean` | The 2 existing MasterDataPage contracts still pass (regression cross-check) |

`service/tests/test_auth_admin_user_routes.py` (NEW, ≥ 5 tests):

| Test | Pins |
|---|---|
| `test_all_admin_writes_have_require_admin` | Each of the 5 write routes declares `Depends(require_admin)` |
| `test_set_role_validates_role_value` | `SetRoleRequest` rejects roles outside the allow-list |
| `test_role_allowlist_pinned` | `ROLES` tuple has exactly 5 values |
| `test_reject_self_route_protection` | The reject route rejects self (returns 400 if `target_id == user.id`) — source-grep on the route |
| `test_deactivate_self_route_protection` | Deactivate route rejects self — source-grep on the route |

---

## 7 — Browser/API smoke plan

Pre-flight (no auth):

```bash
curl -sI http://127.0.0.1:47213/api/v1/health
# Expected: 200
```

With admin session:

1. Open `Setup → Admin · Users`. Page renders with a table.
2. Search "test". Table filters client-side; no network call.
3. Click Refresh. Single GET to `/auth/users` fires.
4. On a pending row, click Approve. Confirm dialog appears. Click Yes. `POST /auth/users/{id}/approve` returns 200. Row badge flips to ● Approved.
5. On another pending row, click Reject. Confirm dialog mentions email queue. Click Yes. `POST /auth/users/{id}/reject` returns 200.
6. On an approved active row (not self), click Set role → select `auditor`. Confirm dialog. Click Yes. `POST /auth/users/{id}/role` body `{role: "auditor"}` returns 200.
7. On the same row, click Deactivate. Confirm dialog. Click Yes. Row shows `· inactive`. `POST /auth/users/{id}/deactivate` returns 200.
8. On the now-inactive row, click Activate. `POST /auth/users/{id}/activate` returns 200.
9. On the current admin's own row, the Actions column shows `—` (self-lockout).
10. Console clean throughout.

Without admin session:

11. `GET /admin_users` (or navigate) renders an Access Denied banner (no leak of user data).
12. Direct curl: `curl -X POST http://127.0.0.1:47213/auth/users/<id>/approve -H "Cookie: <non-admin-session>"` returns 403.

---

## 8 — Rollback

| Path | Cost | Reversibility |
|---|---|---|
| **A — UI revert** | Full deploy cycle | Full. `git revert -m 1 <merge-sha> --no-edit`; robocopy `dashboard.html`; restart PZService. |
| **B — Admin lockdown** | Manual (operator changes own role away from admin) | All admin write endpoints become unreachable without an admin session. |
| **C — Direct backend disable** | Code edit | Add `raise HTTPException(503, "B-MD1 temporarily disabled")` to each route. Behind a flag if desired. Reserved for incident response. |

---

## 9 — Hard rules in effect

- No writes added inside `MasterDataPage` — both existing security contracts (`test_only_allowed_writes_in_master`, `test_no_dangerous_destructive_buttons_in_master`) stay green.
- No new auth route. No auth schema change.
- No new roles table (deferred to B-MD2).
- No invite / signup flow added.
- No automatic state change — every write is an explicit operator click + confirm.
- No finance / wFirma / PZ / DHL / customs / FX coupling.
- No `.env` change.
- No production DB edit.
