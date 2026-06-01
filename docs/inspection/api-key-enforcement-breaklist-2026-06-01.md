# API-Key Enforcement Break-List

**Inspection branch:** `feat/inspection-api-key-breaklist`
**Base SHA:** `e0987811375afce29cc9ed1e1875ecb1c9d9d29a` (origin/main)
**Inspected:** 2026-06-02
**Status:** PHASE 0 READ-ONLY — no flag flipped, no code changed, no PR opened

### Amendment 2026-06-02

**Hazard overturned:** An earlier note carried from the WF4 outbound-dispatch
follow-up read: _"ships together or not at all — the shipment-v2.html blob fetch
breaks when api_key is set."_

**This is false.** `shipment-v2.html:360` sends `credentials: 'include'`
(blob reason is why it bypasses `apiFetch`, not why it bypasses auth).
`require_api_key` checks `pz_session` cookie after X-API-Key; a logged-in browser
user passes via the cookie path. The blob fetch is safe.

**Correct hazard, correctly located:** The coupled break is
`scripts/run_active_shipment_monitor.py:34` — the **10-minute production cron** —
which carries no auth at all. See §3b, break-list item #1.

---

## 1. Auth-Enforcement Map

### 1a. Mechanism

| Item | Detail |
|---|---|
| **Header name** | `X-API-Key` (`APIKeyHeader`, case-insensitive at FastAPI layer) |
| **Dependency** | `require_api_key` — `service/app/core/security.py:14` |
| **Setting** | `settings.api_key` — `service/app/core/config.py:14` — `api_key: str = ""` |
| **Cookie fallback** | `pz_session` cookie checked AFTER X-API-Key; valid session user passes |
| **Rejection code** | `HTTP 401 Unauthorized` — `"Authentication required"` |

### 1b. No-op proof (current state)

```python
# security.py:18
if not settings.api_key:
    return  # auth disabled in dev (preserves current prod posture)
```

```python
# config.py:14
api_key: str = ""  # empty = auth disabled (dev only)
```

Comment in `service/app/main.py:578` (PR #387 note) confirms:
> "api_key is empty in BOTH dev and prod (.env has no API_KEY), so the gate was …"

**Current posture:** `API_KEY` is not set in any `.env`. `require_api_key` returns immediately
for every request. Setting `API_KEY` in `.env` is the enforcement trigger.

### 1c. Routes covered by `require_api_key` (partial sample)

All `service/app/api/routes_*.py` files except the exempt set below import
`require_api_key` and declare `_auth = Depends(require_api_key)` at module scope.
Verified across **≥55 route files** (confirmed by grep: every file listed contains
`from ..core.security import require_api_key`).

### 1d. Routes explicitly EXEMPT from `require_api_key`

These routes are **unaffected** by setting `api_key`; their auth is separate:

| File | Auth mechanism | Reason |
|---|---|---|
| `routes_auth.py` | None (public) | Login / logout / signup / me — must be pre-auth accessible |
| `routes_system.py` | None (intentionally public) | Docstring: "No authentication required — safe to expose." Version endpoint. |
| `routes_carrier_webhook.py` | HMAC webhook secret (`dhl_webhook_secret`) | DHL push callbacks; different secret mechanism |
| `routes_admin.py` | `require_admin` (role-based session check) | Admin email-queue; not API-key gated |
| `routes_agency.py` | `get_current_user` (session cookie) | Agency email package |
| `routes_ai_bridge.py` | `get_current_user` (session cookie) | AI bridge tasks |
| `routes_packing.py` | `get_current_user` (session cookie) | Packing uploads |
| `routes_tracking.py` | `get_current_user` (session cookie) | Tracking data |

---

## 2. Frontend Call Layer

### 2a. `apiFetch` definition

- **File:** `service/app/static/dashboard-shared.js:31`
- **Pattern:** `async function apiFetch(url, opts = {}) { return fetch(url, { credentials: 'include', ...opts }) }`
- **Does it inject X-API-Key?** **NO.** It sends only `credentials: 'include'` (cookie auth).
- **Key source:** None. The function has no knowledge of an API key.

### 2b. `window.__apiHeaders` hook

Used in 20+ call sites across `shipment-detail.html` and `dashboard.html` as
`{ headers: window.__apiHeaders ? window.__apiHeaders() : {} }`.

**Critical finding:** `window.__apiHeaders` is **never defined or assigned anywhere** in
the entire static file tree (confirmed by exhaustive regex search across all `.html` and `.js`
files). Every call site falls back to `{}` (empty headers).

This hook is a future extension point, not a functioning injection mechanism.
File/line evidence: `dashboard.html:15280`, `dashboard.html:16121`,
`shipment-detail.html:9328`, et al. — always guarded, never set.

### 2c. Browser call authentication (all browser callers)

The `fetch()` API defaults to `credentials: 'same-origin'`, which causes the browser to
send the `pz_session` cookie automatically for all same-origin requests (no explicit
`credentials` option required). The `require_api_key` dependency checks the cookie path:

```python
# security.py:23-28
if pz_session:
    user = get_current_user_optional(pz_session=pz_session)
    if user is not None:
        return
```

**Result:** ALL browser-based fetch calls — including the `RAW_NO_CREDS` sites — authenticate
via cookie for any logged-in user. No browser call in `batch.html`, `dashboard.html`,
`shipment-detail.html`, `dhl-automation-v2.html`, `ai-advisory-v2.html`, etc. will break
under enforcement **as long as the user has a valid session.**

Unauthenticated browser requests will receive `401` and be redirected to login — this is
the expected and correct behaviour.

---

## 3. Break-List

Legend:
- **(B) BREAKS** — will receive 401 on enforcement with no code change
- **(S) SAFE** — already authenticated via cookie or key
- **(N) NOT AFFECTED** — route not under `require_api_key`

### 3a. Browser callers (all SAFE)

All 113 raw `fetch()` sites surveyed. Classification: all same-origin → cookie sent
automatically → cookie path in `require_api_key` passes. **No browser caller breaks.**

### 3b. Non-browser callers — BREAK-LIST

| # | File:line | Endpoint | Method | Caller type | Current auth | Breaks? | Fix |
|---|---|---|---|---|---|---|---|
| 1 | `service/scripts/run_active_shipment_monitor.py:34` | `/api/v1/monitor/active-shipments/run` | POST | Production cron (runs every 10 min via cron/NSSM) | None — bare `urllib.request.Request` with no headers | **YES** | Add `X-API-Key` header to request; read key from env var or config file |
| 2 | `service/scripts/run_smoke.py:15,144,162` | Any path from smoke spec | varies | Manual smoke harness | Empty header `{"X-API-KEY": ""}` — slot exists but empty | **PARTIAL** — breaks unless spec supplies real key | Smoke spec files must supply `headers: {"X-API-Key": "<key>"}` or inject from env |
| 3 | `service/app/api/routes_debug.py:173` | `/api/v1/batch/sessions` | GET | Internal self-call (httpx inside a debug endpoint) | None — bare `httpx.get("http://localhost:8000/…")` | **YES** (contained) | Pass `X-API-Key` in httpx headers; low priority — debug route only |

### 3c. Already-safe non-browser callers

| Script | Auth mechanism | Evidence |
|---|---|---|
| `activate_pz_lifecycle.py` | Sends `X-API-Key` header | `scripts/activate_pz_lifecycle.py:248` — `headers={"X-API-Key": api_key}` |
| `lifecycle_smoke_tests.py` | Sends `X-API-Key` header | `scripts/lifecycle_smoke_tests.py:126` — `headers={"X-API-Key": api_key, …}` |
| `smoke_403_deploy.py` | Sends `X-API-Key` | key-aware (confirmed by grep) |
| `prod_smoke_final.py` | Session cookie | Logs in via `/auth/login`, uses cookie jar — `scripts/prod_smoke_final.py:31-44` |
| `post_restart_smoke.py` | Session cookie | Same login + cookie pattern — `scripts/post_restart_smoke.py:26-43` |
| `email_ingestion_worker.py` | Zoho OAuth token | `services/email_ingestion_worker.py:103` — calls Zoho Mail API, not PZ API |
| DHL webhook callbacks | HMAC webhook secret | `routes_carrier_webhook.py:45-55` — separate `_require_webhook_secret()` dependency |
| All browser calls | `pz_session` cookie | See §2c |

---

## 4. Known Seed Verification

**Precondition from spec:** "confirm `shipment-v2.html → POST /api/v1/carrier/{batch_id}/label-package` is in the (B) list with its blob reason."

**Finding:** `shipment-v2.html:360-373` — this call uses `credentials: 'include'` explicitly:

```js
const res = await fetch(
  `/api/v1/carrier/${encodeURIComponent(batchId)}/label-package`,
  {
    method: 'POST',
    credentials: 'include',          // ← explicit; also sends cookie
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({…}),
  }
);
```

The comment in the source is `// Use raw fetch so we can handle binary (blob) response`.
**This call is SAFE (not in break-list)** — it carries `credentials: 'include'`, so the
`pz_session` cookie is sent and `require_api_key` passes via the cookie path.

---

## 5. Assumptions (undecided, not resolved here)

| # | Assumption | Context |
|---|---|---|
| A1 | `/auth/*`, `/system/*`, and `/carrier/webhook/*` remain **exempt** from `require_api_key` under enforcement | The enforcement PR should confirm these routes are deliberately not converted |
| A2 | `X-API-Key` is the agreed final header name (not `X-PZ-Key`, `Authorization: Bearer`, etc.) | Header is already hardcoded in `security.py:11` and multiple scripts; unless changed this is the name |
| A3 | The API key lives **server-side only** (not injected into browser pages via meta tag or build config) | `apiFetch` does not read a meta tag; `window.__apiHeaders` is never set; browser callers use cookie auth. No change needed in frontend for enforcement. |
| A4 | `get_current_user` routes (`routes_agency.py`, `routes_packing.py`, `routes_tracking.py`, `routes_ai_bridge.py`) stay **on session-cookie auth** and are NOT converted to `require_api_key` | These routes are out of scope for enforcement unless operator decides otherwise |

---

## 6. Per-item Fix Scope

| # | Item | Minimal fix | Same PR as enforcement? |
|---|---|---|---|
| 1 | `run_active_shipment_monitor.py` | Read `API_KEY` from env/config; add `headers={"X-API-Key": key}` to `urllib.request.Request` at line 34 | **Yes** — must land before or with enforcement; this script runs in prod every 10 min |
| 2 | `run_smoke.py` smoke spec default | Update default header dict and/or each smoke spec file to supply real key | **Yes** — smoke must pass after enforcement; same PR acceptable |
| 3 | `routes_debug.py:173` internal httpx call | Pass `X-API-Key: <key>` in httpx headers | **No** — debug endpoint only, low blast radius; can be a follow-up issue |

---

## 7. VERDICT

**GO** — the enforcement PR has a bounded, three-item break-list.

Two items (#1 and #2) are mandatory same-PR fixes before enforcement lands.
One item (#3) is a low-priority follow-up.

No browser caller requires any change.
No frontend injection mechanism needs to be built.
The cookie path in `require_api_key` covers all logged-in browser users transparently.

**Enforcement PR scope:**
1. Set `API_KEY` in production `.env`
2. Fix `run_active_shipment_monitor.py` to read and send key
3. Fix/update `run_smoke.py` default headers / spec convention
4. (Follow-up issue) Fix `routes_debug.py:173` internal httpx call
