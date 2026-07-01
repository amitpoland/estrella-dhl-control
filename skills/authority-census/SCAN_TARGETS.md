# Authority Census — Scan Targets

Base SHA: **aa414d90** (origin/main).
Counts are as of the 2026-06-30 census; re-verify on each run.

---

## Frontend Scan Targets

### V2 SPA (primary authority)

| Path | File count (baseline) | Notes |
|---|---|---|
| `service/app/static/v2/*.jsx` | 33 JSX | Components; each should map to exactly one URL slug |
| `service/app/static/v2/*.js` | ~5 JS | `pz-api.js`, `pz-design-v2.js`, `pages-v2.js`, etc. |
| `service/app/static/v2/index.html` | 1 | SPA shell — contains `WIRED_PAGES`, `NAV_TREE`, `ROUTE_REDIRECTS` |

### V1 HTML pages (legacy or still-active shells)

| Path | File count (baseline) | Notes |
|---|---|---|
| `service/app/static/*.html` | 31 HTML | Mix of legacy, still-active shells, admin pages |

### Atlas orphan cluster

| Path | File count (baseline) | Notes |
|---|---|---|
| `atlas/*.html` | Variable | Not in main nav — likely orphan cluster |
| `atlas/atlas-shared.js` | 1 | Atlas nav config; check for dead links |

### Key navigation config files

Read all of these during Step 5 (Nav Map):
- `service/app/static/v2/index.html` — `WIRED_PAGES`, `NAV_TREE`, `ROUTE_REDIRECTS`
- `service/app/static/pz-design-v2.js` — legacy nav (if present)
- `atlas/atlas-shared.js` — Atlas nav (if present)

---

## Backend Scan Targets

### Route files

| Path | File count (baseline) | Notes |
|---|---|---|
| `service/app/api/routes_*.py` | 78 active, 1 dead | `routes_reservations.py` was not imported as of 2026-06-30 |

### Router registration (source of truth)

- `service/app/main.py` — **definitive** list of what is actually mounted.
  Scan for all `include_router(` calls. If a route file is not listed here,
  its endpoints are completely unreachable regardless of what the file declares.

### Service layer (for dead-code cross-check)

- `service/app/services/` — services that start at startup but whose routes
  may be dead. Cross-reference `startup()` / `lifespan()` in `main.py`.

---

## Output Paths

All report files write to:
```
C:\PZ-verify\reports\authority-census\<UTC-stamp>\
```

UTC stamp format: `yyyy-MM-ddTHHmmssZ` (colons removed for Windows path safety).

Do NOT write to any other directory.
