# Capability Manifest — platform

**Status:** ACTIVE (V2 = frontend authority; deploy verification gate + status API live)
**Authority owner:** the **application shell** — auth, config/flags, routing, deploy, observability

> Platform is the cross-cutting substrate every other capability runs on. Changes here are
> almost always Deep Path because they affect all capabilities at once.

---

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | V2 shell + router (`index.html` WIRED_PAGES/NAV_TREE/ROUTE_REDIRECTS, `pz-design-v2.js`), admin surfaces |
| **API** | auth/session routes, `routes_admin.py`, deploy-status + health endpoints — all registered in `main.py` |
| **Service** | `core/config.py` (feature flags), `core/audit`, `core/guards`, circuit breaker, security; `auth/` (JWT + session) |
| **DB / state** | config (env-var driven, no `.env`), auth/session store, deployment_record.json + version.json |

## Frontend authority (Constitution)

- **V2 is the current frontend authority.** One canonical URL + one JSX file + one API wrapper
  path + one backend authority per module. No new standalone HTML page (login/auth/static shell
  excepted); no parallel React app; no `*New`/`*V2` duplicate.
- Shared primitives: `dashboard-shared.js` (visual atoms, zero domain knowledge),
  `static/v2/components.jsx`, `pz-api.js` (transport only).

## Config / flags

- Runtime flags in `core/config.py`: `audit_hardening_enabled`,
  `compliance_intelligence_resolver_enabled`, `series_bootstrap_enabled`,
  `advisory_gates_enabled`, `WFIRMA_CREATE_*` (default off). Environment-variable driven.
- Standing production posture: wFirma create flags gated; X-API-Key auth on privileged routes.

## Deploy + observability (see `08`, `10`)

- Production: `C:\PZ`, `PZService` (NSSM, port 47213), public `https://pz.estrellajewels.eu`.
- Self-describing production model: deployment_record.json + version.json + status endpoint
  answer "what SHA is live, when did it deploy, is it healthy."
- Deploy verification gate + deploy status API/dashboard are live (session 2026-06-27 wins).

## Governance guardrails

- Every new route file **must** be registered in `main.py` (no hidden/auto routers).
- Download endpoints set `Cache-Control: no-store …` (Lesson G).
- No auth-guard removal without Security council + deploy-security-reviewer sign-off (terminal
  blocker).
- Platform changes never bypass the 7-agent deploy gate.

## Related
Skills: `ej-dashboard-fullstack-governance`, design pair (shell/router UI), `ej-dashboard-webapp-testing`.
Agents: `security-permissions`, `deployment-windows-ops`, `backend-route-inspector`, `navigation-inspector`, all `deploy-*`.
