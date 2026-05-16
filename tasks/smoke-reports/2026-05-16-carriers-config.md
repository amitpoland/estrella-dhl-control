# Smoke report — Carriers Config (B9 post-deploy)

**Date:** 2026-05-16
**Campaign:** MDC-2026-05
**Batch(es):** B9
**Environment:** production (https://pz.estrellajewels.eu, local 127.0.0.1:47213)
**Tester:** claude-session (api-level smoke)

## Coverage

| Route                                            | Action                            | Expected | Actual | Console | Verdict |
|--------------------------------------------------|-----------------------------------|----------|--------|---------|---------|
| /api/v1/health (local)                           | GET                               | 200      | 200    | n/a     | PASS    |
| /api/v1/health (public)                          | GET                               | 200      | 200    | n/a     | PASS    |
| /api/v1/carriers-config/dhl                      | PUT minimal config                | 200      | 200    | n/a     | PASS    |
| /api/v1/carriers-config/dhl                      | PUT update name                   | 200      | 200    | n/a     | PASS    |
| /api/v1/carriers-config/                         | GET list                          | 200      | 200    | n/a     | PASS    |
| /api/v1/carriers-config/dhl                      | DELETE                            | 204      | 204    | n/a     | PASS    |
| /api/v1/carriers-config/test                     | PUT with api_key field (rejected) | 422      | 422    | n/a     | PASS    |

## Console errors

none (api-level smoke; no browser session)

## Artifacts left behind

- none — the test `dhl` record was created and deleted in the same run
- the secret-shape rejection (`api_key`) was rejected before any DB write

## Verdict

**PASS** — Full Carriers Config CRUD lifecycle green; hard-rule secret-shape guard enforced; no logs polluted.

## Screenshots

(none — api-level smoke)

## Notes for follow-up operator smoke

The browser-level steps are deferred to the operator:
1. Open https://pz.estrellajewels.eu/dashboard/dashboard.html
2. Navigate to Master Data → Carriers Config sidebar entry
3. Click + New Carrier Config → fill code `dhl`, name "DHL Express", api_type "api" → Save → row appears
4. Click Edit on the row → change name → Save → row updates
5. Click × on the row → row disappears
6. Verify console (browser devtools) shows no error

The visible disclaimer "credentials live in .env and are NEVER stored here" must remain on the panel.
