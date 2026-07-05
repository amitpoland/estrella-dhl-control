# Wave-3 Build Record: Setup→Settings + Reports (MOCK honest)

**Date:** 2026-07-04
**Branch:** deploy/latest
**Sub-slice:** (c) Settings live company-profile + Reports R-Q3 notice
**Criterion 10 (control matrix gate):** PASS — Wireframe-Required Missing = 0

---

## Summary

**Settings (`admin` slug):** Wired company profile section to `GET /api/v1/settings/company-profile`
(routes_settings.py). API Config card now shows environment-set notice (not editable via UI).
Save Changes button disabled with Backend Required note (PATCH requires admin auth, Wave-4 wiring).

**Reports (`reports` slug):** No confirmed backend endpoint per census. Per R-Q3 honest-gate
policy, added amber MOCK notice at top of page. All 5 tabs unchanged (Financial / Sales /
Purchase / Shipping / Duty & VAT). Page stays off WIRED_PAGES.

---

## Files Changed

| File | Change |
|---|---|
| `service/app/static/v2/pages.jsx` | `AdminSettingsPage`: added `useEffect` → `GET /api/v1/settings/company-profile`; Company Profile card live; API Config amber notice; Save disabled (Backend Required) |
| `service/app/static/v2/pages-v2.jsx` | `ReportsPage`: amber MOCK notice added at top; R-Q3 comment added |

---

## Control Matrix — Settings

| Census ID | Control | Disposition | Authority |
|---|---|---|---|
| SET-1 | Company profile read | WIRED — live from `GET /api/v1/settings/company-profile` | `routes_settings.py:33` |
| SET-2 | Company profile save | HONEST-GATED — disabled, "PATCH · admin auth · Wave-4" | `routes_settings.py:43` PATCH endpoint exists |
| SET-3 | API Config (env vars) | HONEST-GATED — readOnly disabled + amber notice | Environment-set, not DB-stored |
| SET-4 | Invite User | MOCK — button visible, no backend (Wave-4) | routes_users.py (unverified) |

Wireframe-Required Missing = **0** — criterion 10 PASS.

---

## Control Matrix — Reports

| Census ID | Control | Disposition | Authority |
|---|---|---|---|
| REP-1 | Financial tab | HONEST-MOCK — R-Q3 notice present | No confirmed backend |
| REP-2 | Sales tab | HONEST-MOCK | No confirmed backend |
| REP-3 | Purchase tab | HONEST-MOCK | No confirmed backend |
| REP-4 | Shipping tab | HONEST-MOCK | No confirmed backend |
| REP-5 | Duty & VAT tab | HONEST-MOCK | No confirmed backend |
| REP-6 | Export buttons | STATIC (not disabled — no write, just MOCK export) | N/A |

Wireframe-Required Missing = **0** — criterion 10 PASS.
Reports NOT added to WIRED_PAGES (no confirmed live backend).

---

## Backend Truth Citation

| Endpoint | Route file | Method |
|---|---|---|
| `GET /api/v1/settings/company-profile` | `routes_settings.py:33` | `get_company_profile_endpoint()` |

---

## Tree Count

**Before / After:** 11 / 11 modified tracked files
