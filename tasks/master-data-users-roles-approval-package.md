# Master Data — Users / Roles Writes — Approval Package

> **Status:** docs-only, awaiting operator sign-off. NO code change.
> NO implementation begins until §9 is signed.
> **Predecessor:** `MDC-2026-05/B3` left the Users/Roles writes blocked
> behind a security contract. This package proposes the unblocking design.
> **Date:** 2026-05-16. **Campaign:** `MDOC-2026-05` / batch `B-MD1`.

This package defines exactly how Users/Roles writes will be wired,
which security contracts move and which stay, and the sign-off that
implementation requires.

---

## 1 — Existing auth / user APIs

`service/app/api/routes_auth.py` (429 lines, 13 routes) — already deployed:

| Verb | Path | Purpose | Auth requirement (existing) |
|---|---|---|---|
| POST | `/auth/login` | Session login | unauth |
| POST | `/auth/logout` | Session logout | session |
| POST | `/auth/signup` | First-user is admin + auto-approved; rest await approval | unauth |
| GET | `/auth/me` | Current session info | session |
| POST | `/auth/forgot-password` | Email reset code | unauth |
| POST | `/auth/reset-password` | Apply reset code | unauth (validates code) |
| GET | `/auth/users` | List users (admin) | `require_admin` |
| GET | `/auth/users/{id}/active-reset-code` | Inspect pending reset (admin) | `require_admin` |
| **POST** | `/auth/users/{id}/approve` | **Admin write** — mark approved | `require_admin` |
| **POST** | `/auth/users/{id}/reject` | **Admin write** — reject + email | `require_admin` |
| **POST** | `/auth/users/{id}/role` | **Admin write** — set role | `require_admin` |
| **POST** | `/auth/users/{id}/deactivate` | **Admin write** — disable account | `require_admin` |
| **POST** | `/auth/users/{id}/activate` | **Admin write** — re-enable account | `require_admin` |

All 5 bolded write endpoints are **already implemented and protected by
`require_admin`**. The only missing surface is the UI that calls them.
There is **no new backend work** in B-MD1 — only frontend wiring +
contract-test movement.

---

## 2 — Existing role model

Today's role model is implicit:

- `users.db` schema columns referenced by `routes_auth.py`: `id`, `email`, `full_name`, `role` (free-text), `is_approved`, `is_active`, `approval_status`, `created_at`, `last_login`.
- The `role` column is a free-text string. No dedicated `roles` table exists.
- Admin gate is `require_admin` (likely `role == "admin"` check). The system has at least the literal values `"admin"` and `"user"` in production.

**B-MD1 does NOT propose a new roles table.** The existing `role` column
is sufficient for the 5 write endpoints. A separate `roles` master-data
entity (with custom role definitions, permission sets, `can_approve` /
`can_post_wfirma` / `can_manage_master`) is scope of B-MD2, NOT B-MD1.

B-MD2 (Designs/Roles approval package, to be authored separately) covers
the proper `roles` table + permission matrix.

---

## 3 — Allowed write actions (B-MD1 scope)

| Write | UI button | Endpoint | Confirmation required | Audit |
|---|---|---|---|---|
| Approve a user | "Approve" per-row button | `POST /auth/users/{id}/approve` | Operator confirm dialog | Existing audit on the route |
| Reject a user | "Reject" per-row button | `POST /auth/users/{id}/reject` | Operator confirm dialog + reason text | Existing audit; rejection email sent |
| Set role | "Set role" per-row dropdown (values: `admin`, `user`) | `POST /auth/users/{id}/role` body `{role: "admin"\|"user"}` | Operator confirm dialog | Existing audit |
| Activate | "Activate" per-row button (only when `is_active === false`) | `POST /auth/users/{id}/activate` | Operator confirm dialog | Existing audit |
| Deactivate | "Deactivate" per-row button (only when `is_active === true`) | `POST /auth/users/{id}/deactivate` | Operator confirm dialog | Existing audit |

Each button:

- Renders **only for the current admin session** (read `is_admin` from `/auth/me`; default-deny otherwise).
- Calls `apiFetch(...)` with `method: 'POST'` and the route as written above.
- On success: refreshes the users list via the existing `loadUsers()` helper.
- On failure: surfaces the backend error via `onToast(...)`.

---

## 4 — Forbidden actions (B-MD1)

Operator may NOT do any of the following in B-MD1; each is gated by a
separate approval:

| Forbidden in B-MD1 | Reason | Where it goes |
|---|---|---|
| Create a new user via UI | UX surface for password handling is risky | Stays at `/auth/signup` (unauth flow); admin can email the link |
| Delete a user | No backend `DELETE /auth/users/{id}` exists; deactivate is the soft-delete | Out of scope |
| Set role to any value other than `admin` / `user` | B-MD1 uses the existing free-text column; adding custom roles needs schema work | B-MD2 |
| Edit user email or full_name | No backend endpoint; touches identity | Separate batch with separate approval |
| Reset a user's password from admin UI | Reset flow already exists at `/auth/forgot-password`; admin re-sends | Out of scope |
| Change an admin's own role from the same admin's session | Self-lockout risk | UI gate: hide "Set role" on `currentUserId === u.id` |
| Approve / reject in bulk (multi-select) | One-at-a-time is auditable; bulk is risky | Out of scope |
| Show full reset code to admin via UI | Token leakage risk | Backend exposes the route but UI shows only "Reset pending: yes/no" |
| Inline role edits without confirm dialog | Misclick risk | Confirm dialog mandatory |

---

## 5 — Required UI buttons + placement

**Recommended placement: a NEW page `AdminUsersPage`**, NOT a write
section added to `MasterDataPage`. Two reasons:

1. The two existing security contracts inside `MasterDataPage` stay intact.
2. Admin users panel needs visibility separate from master-data sidebar (it's an identity surface, not a master-data entity).

Layout (one component file or one section in dashboard.html, behind a new top-nav entry):

```
AdminUsersPage
├── Header: "Admin · Users"
├── Refresh button (calls loadUsers; same as today)
├── Table:
│   ├── Columns: Full name · Email · Role · Status · Created · Last login · [Actions]
│   └── Per-row Actions cell:
│       • If approval_status === "pending":  [Approve]  [Reject]
│       • If approval_status === "approved" and is_active:  [Set role ▾]  [Deactivate]
│       • If is_active === false:  [Activate]
│       • Hide all actions when row.id === currentUserId (self-lockout guard)
├── Per-row confirm dialogs for all 5 actions (operator types "CONFIRM" or clicks Yes/No)
└── Result toasts
```

Top-nav entry: a new `Admin` tab visible only when `currentUser.role === "admin"`. The existing `MasterDataPage` keeps its current sidebar (users panel stays read-only there); the new page is the write surface.

---

## 6 — Source-grep contract tests required

Two new contract tests in `service/tests/test_dashboard_admin_users_design.py` (NEW file). Plus surgical updates to two existing tests.

### 6.1 — New tests (`test_dashboard_admin_users_design.py`)

| Test | Pins |
|---|---|
| `test_admin_users_page_exists` | `function AdminUsersPage(` appears in `dashboard.html`; rendered behind admin nav gate |
| `test_admin_users_calls_only_allowed_endpoints` | Every `apiFetch(...)` inside the `AdminUsersPage` block targets ONLY `/auth/users` or `/auth/users/{id}/{approve\|reject\|role\|activate\|deactivate}` |
| `test_admin_users_uses_post_for_writes` | Each of the 5 write actions uses `method: 'POST'`; no PATCH; no DELETE |
| `test_admin_users_no_create_or_delete_user_buttons` | Strings `>Create user<`, `>Delete user<`, `>Remove user<` MUST NOT appear |
| `test_admin_users_has_self_lockout_guard` | `row.id === currentUserId` or equivalent self-guard is present near the action cell |
| `test_admin_users_has_confirm_for_each_action` | Each action is wrapped in a confirm-dialog handler (search for `window.confirm` or `<ConfirmDialog` pattern) |
| `test_admin_users_role_dropdown_pinned_values` | `role` dropdown allow-list is exactly `{admin, user}` |
| `test_admin_users_admin_gate_present` | Page render is gated on `currentUser.role === "admin"` or equivalent admin check |

### 6.2 — Existing contract tests — surgical updates

| Test | Update |
|---|---|
| `test_only_allowed_writes_in_master` (`test_dashboard_master_design.py` line 199) | **NO CHANGE.** `/auth/users/*` writes still forbidden inside `MasterDataPage` — they live in the new `AdminUsersPage`. |
| `test_no_dangerous_destructive_buttons_in_master` (line 245) | **NO CHANGE.** Destructive identity strings still forbidden inside `MasterDataPage`. The new page is the legal location. |

This preserves both security contracts on the existing surface and
moves the new writes to a clearly-bounded admin surface.

### 6.3 — Backend contract test

| Test | Pins |
|---|---|
| `test_auth_users_routes_require_admin` (`service/tests/test_auth_admin_user_routes.py`, NEW or extend existing) | All 5 admin write routes use `Depends(require_admin)`; non-admin caller returns 403 |

---

## 7 — Rollback plan

Three paths, mirroring the established pattern:

### Path A — UI hide (immediate)

A future PR can gate the entire `AdminUsersPage` behind a feature flag
`ADMIN_USERS_UI_ENABLED` (default True after activation; can be flipped
False if any incident requires hiding the surface). 30-second restart.

This is **optional**. Without the flag, hiding requires a code revert
(Path B).

### Path B — Code revert

```bash
git revert -m 1 <merge-sha> --no-edit
git push
# Merge revert PR + robocopy + restart.
```

Full deploy cycle. Reverts to the state before B-MD1 (Users read-only in `MasterDataPage`; no `AdminUsersPage`).

### Path C — Backend-only kill

```python
# In routes_auth.py — convert each write route to return 403 immediately.
# Behind a flag if desired. This decouples backend lockdown from UI presence.
```

Use Path C only if Path A/B insufficient (e.g. UI cached on operator
machines). Each write route's `Depends(require_admin)` already provides
the natural lockdown — strip the admin's role and Path C is automatic.

---

## 8 — Smoke plan

After deploy:

| Check | Expected |
|---|---|
| `GET /api/v1/health` | 200 |
| Public health | 200 |
| Open `AdminUsersPage` as admin | Render with table; no console errors |
| Approve a test pending user | `POST /auth/users/{id}/approve` → 200; user row shows ● Approved on refresh |
| Reject another test pending user | `POST /auth/users/{id}/reject` → 200; rejection email visible in operator inbox |
| Set role to `user` on a test admin | `POST /auth/users/{id}/role` → 200; role badge updates |
| Deactivate a test user | `POST /auth/users/{id}/deactivate` → 200; status shows `· inactive`; user's next login fails with "Account has been deactivated." |
| Activate the same user | `POST /auth/users/{id}/activate` → 200; login restored |
| Open `AdminUsersPage` as non-admin | Render denied (gate hides the page); direct `POST` to write routes returns 403 |
| Self-lockout guard | Actions hidden on the current admin's own row |
| All confirm dialogs | Click "Cancel" → no network request fired |

Backend smoke (curl with admin session cookie):

```bash
# Approve
curl -X POST http://127.0.0.1:47213/auth/users/<test-id>/approve -H "Cookie: <session>" -i
# Expected: 200

# Non-admin smoke
curl -X POST http://127.0.0.1:47213/auth/users/<test-id>/approve -H "Cookie: <non-admin-session>" -i
# Expected: 403
```

PZ regression: 160/160 must remain unchanged. The change is UI + admin auth surface; the calculation path is untouched.

---

## 9 — Approval block (operator to sign)

```
B-MD1 Users/Roles Writes — Operator Approval

Read this entire document:                                  ___ (yes / no)
Approves §3 allowed write actions:                          ___ (yes / no)
Approves §4 forbidden actions:                              ___ (yes / no)
Approves §5 placement (new AdminUsersPage, NOT MasterDataPage): ___ (yes / no)
Approves §6 contract tests:                                 ___ (yes / no)
Approves NOT relaxing the two existing MasterDataPage security contracts: ___ (yes / no)
Approves §7 rollback plan (A primary, B secondary, C tertiary): ___ (yes / no)

Approved by:    __________________________
Date/time:      __________________________
Notes:
```

Until §9 is signed, `B-MD1` remains `blocked`. The 5 backend write
endpoints continue to exist; the UI continues to expose only the
read-only Users panel inside `MasterDataPage`.

---

## 10 — Exact next command if approved

```bash
# 1. Create implementation branch.
cd "C:/Users/Super Fashion/PZ APP"
git checkout main && git pull --ff-only origin main
git checkout -b feat/b-md1-admin-users-writes

# 2. Allowed files (no others without re-approval):
#    - service/app/static/dashboard.html
#         + new AdminUsersPage component
#         + new top-nav entry "Admin" (admin-gated)
#         + per-row action cell + confirm dialogs
#    - service/tests/test_dashboard_admin_users_design.py (NEW; 8 tests)
#    - service/tests/test_auth_admin_user_routes.py (NEW or extend; 1 test)
#    - tasks/campaign-state.json (B-MD1 active -> pr_open)

# 3. Run gates BEFORE pushing.
cd service
python -m pytest tests/test_dashboard_admin_users_design.py tests/test_auth_admin_user_routes.py -v
python -m pytest tests/test_dashboard_master_design.py -q  # MUST stay green; existing contracts unchanged
cd ..
PYTHONIOENCODING=utf-8 python test_pz_regression.py  # must be 160/160
python service/scripts/campaign_status.py doctor

# 4. After all green: open PR, run 7-agent deploy gate.
# 5. Post-deploy: smoke per §8.
```

Lessons L-037 (deployed != activated) and L-040 (inspection-only batches
close decisions without writing code) both apply: this package is the
docs-only precursor; implementation is a SEPARATE PR after sign-off.
