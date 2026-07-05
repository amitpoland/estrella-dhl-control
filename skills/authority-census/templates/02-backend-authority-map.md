# Backend Authority Map

**Base SHA:** aa414d90
**Census timestamp:** {{STAMP}}
**Inspector agent:** backend-route-inspector
**Mode:** READ-ONLY — no app code was modified
**Route files found:** {{N}} ({{M}} active, {{K}} dead)
**Registered routers:** {{R}}
**Duplicate-prefix groups:** {{D}}

---

## Route File Table

| Domain | Prefix | Route File(s) | Endpoints | In main.py | Collision Risk | Notes |
|---|---|---|---|---|---|---|
| Customer Master | `/api/v1/customer-master` | `routes_customer_master.py` | N | YES | NONE | Clean |
| … | … | … | … | … | … | … |

---

## Dead Routes

| File | Endpoints | Orphaned service? | Action |
|---|---|---|---|

---

## Duplicate-Prefix Groups

| Risk | Prefix | Files | Issue |
|---|---|---|---|
| CRITICAL | `/api/v1/upload` | `routes_wfirma.py`, `routes_upload.py` | wFirma routes under upload prefix |
| … | … | … | … |

---

## Orphaned Services

| Service | File | What it does | Route file | Action |
|---|---|---|---|---|
