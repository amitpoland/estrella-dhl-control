# Post-deployment closure — wFirma circuit-breaker recovery (PR #1041 + #1040)

**Deployed SHA:** `c7903686a13d1579b749c993e11b7f00a6afcdd5`
**Rollback unit:** `c7903686a13d1579b749c993e11b7f00a6afcdd5-20260730-194654`
**Deploy performed by:** operator, via `Deploy-PZ.ps1` (governed path). Not performed by the agent session.
**Verification performed by:** agent session, read-only. **No production write, no wFirma write, no fiscal /
inventory / customs / accounting mutation was performed during verification.**

---

## 1. Governed closure validator

`Test-PZDeployClose.ps1 -ExpectedSHA c7903686…` — run from `C:\PZ-main`, deliberately **without** `-Verbose`
and outside any `Start-Transcript` (credential-hygiene rule, `windows_prod_v2.json`). **All 10 conditions
passed, exit 0**:

| # | Condition | Result |
|---|---|---|
| 1 | `version_file` is BOM-free | PASS (clean) |
| 2 | `version_file` matches ExpectedSHA | PASS (`c7903686…` == expected) |
| 3 | `source_root` HEAD == ExpectedSHA | PASS |
| 4 | production matches artifact manifest | PASS — **0 discrepancies** |
| 5 | engine files match source | PASS |
| 6 | protected runtime paths intact | PASS (none missing) |
| 7 | PZService Running | PASS |
| 8 | health `http://127.0.0.1:47213/api/v1/health` | PASS — HTTP 200 |
| 9 | health `https://pz.estrellajewels.eu/api/v1/health` | PASS — HTTP 200 |
| 10 | rollback unit available | PASS — `c7903686…-20260730-194654` |

Supporting evidence: `unit.json` → `{"scope":"Both","app_backed_up":true,"engine_backed_up":true,
"bootstrap":false,"complete":true}`; release artifact + manifest present under `C:\PZ-releases`; no stale
`.deploy.lock`.

## 2. Service, identity, and authorization

- **PZService Running**, python **pid 6644**, port 47213 listening on that pid.
- **No restart loop** — exactly **one** `Started server process [6644]` in the current `pz_stderr.log`;
  `pz_stderr.log` contains only the four normal uvicorn startup lines and nothing else.
- **Health watchdog**: single `FAIL [1/2]` at `19:46:48` (the deploy's own service-stop window) → `HOLD`
  (threshold not reached, **no watchdog restart issued**) → `RECOVERED HTTP 200` at `19:47:46`, then
  continuous `OK HTTP 200` every 60 s through `19:57:47`.
- **Production version exact**: `C:\PZ\version.txt` = 40 bytes, hex head `63 37 39 30 33 36 38 36`
  (ASCII `c7903686`), **no BOM**.
- **Manifest == runtime**: 0 discrepancies (validator condition 4).
- **Authorization consumed and non-reusable**: the deploy jti is recorded consumed at
  `<store>/consumed/b2929f65….used`. Re-running `deploy_authorization.py <sha> deploy Both` in this session
  returns `DENY` — the artifact cannot be replayed from here. The **rollback** artifact
  (`{sha}.rollback.json`) is present and **deliberately left unconsumed** for incident use; it was not
  evaluated, because `evaluate()` consumes the jti on success.

## 3. Read-only production checks

| Check | Result |
|---|---|
| Application shell loads | `GET /` → **HTTP 200**, 16 357 bytes (sign-in shell renders) |
| Dashboard session gate | `GET /dashboard/dashboard.html` unauth → **302 → `/login`**; `GET /v2/` unauth → **302 → `/login`**. Correct fail-closed behaviour. *(Not logged in — entering credentials is out of scope for this session, so the authenticated dashboard render is not covered here.)* |
| wFirma capabilities (authenticated) | **HTTP 200** — `api_configured: true`, `api_user_configured: true`, `warehouse_module_enabled: true`, `product_api_supported: true`, `customer_api_supported: true`, `blocking_reasons: []`, `ready_to_reserve: true` |
| Capabilities auth holds | same endpoint **without** `X-API-Key` → **HTTP 401**. Auth was not weakened. |
| Goods search (structured contract) | **HTTP 200**, envelope `{ok, found, result{wfirma_id,name,code,unit,count,reserved}}` |
| Contractor search (structured contract) | **HTTP 200**, envelope `{ok, found, result{wfirma_id,name,nip,country,…}}` — `ESTRELLA JEWELS LLP` / `38142296` |

### Resolve Mapping — the original affected case (search only)

The exact codes that produced the `EJL/26-27/453` "Resolve mapping — gateway error" now **resolve live
through the breaker**:

| Product code | Result |
|---|---|
| `EJL/26-27/453-1` | `ok:true, found:true` — `wfirma_id 51495203`, count 3.0 |
| `EJL/26-27/453-2` | `ok:true, found:true` — `wfirma_id 51495331`, count 174.0 |
| `EJL/26-27/453-3` | `ok:true, found:true` — `wfirma_id 51495267`, count 17.0 |

Search only. **No product created, no mapping saved, no adopt, no write of any kind.**
(Polish diacritics render correctly — `Wyrób jubilerski — …` — confirmed by re-decoding the raw response
as UTF-8; earlier mojibake was a PowerShell console decoding artifact in the probe, not a production defect.)

### Error-classification correctness

Live failure injection was **not** performed — intentionally tripping the production breaker or generating
repeated wFirma failures is out of scope. Correctness is therefore established from the **deployed** code
plus the merged test suite:

- `C:\PZ\app\api\routes_wfirma_capabilities.py` contains the deployed classifier with all five causes:
  `credentials_not_configured` (**retryable: false**), `unavailable_503` (true), `upstream_unreachable`
  (true), `wfirma_rejected` (**false**), `upstream_error` (true), plus `unknown`.
- `C:\PZ\app\static\v2\proforma-detail.jsx:2412` checks `d.ok === false` **before** `d.found` — so a
  structured failure can **never** render as "product not found"; it renders the cause-accurate
  `error_message`. The blanket "gateway error" text survives only for a genuine transport throw.
- `C:\PZ\app\services\wfirma_client.py` — **both** raw-`.state` fast-paths are gone; `_http_request` (:516)
  and the PDF fetch (:2973) both route admission through `breaker.call()`.
- `C:\PZ\app\core\circuit_breaker.py` — `_maybe_transition()` reachable from `call()`,
  `CircuitBreakerProbeInProgress` present, `_probe_in_flight` set under the lock and cleared in `finally`;
  wFirma `recovery_timeout = 90`.

## 4. Log review (post-deploy window, 19:47 → 19:57)

| Signal | Finding |
|---|---|
| Permanent breaker-open loop | **None** — zero `circuit` / `breaker` / `HALF_OPEN` lines since restart. The breaker has not tripped; consistent with the successful live lookups. |
| Concurrent HALF_OPEN probe storm | **None** (no HALF_OPEN transitions at all). |
| Repeated 503s | **None** — the only two `503` string matches are a contractor id (`110345038`) inside two payment-sync INFO lines. Zero HTTP 5xx responses. |
| Unhandled exceptions | **0 tracebacks, 0 `ERROR` lines.** |
| Frontend failures | No 4xx/5xx on the exercised paths; all probes 200 (or the correct 302/401 on the negative checks). |
| Credential leakage | **0 matches** for `X-API-Key`, `api_key=`, `access_key`, `secret_key`, `WFIRMA_ACCESS/SECRET/APP`, `password`, `Authorization:`. |
| Raw exception disclosure | None observed in this window (see GATE-4 note below). |

**Observations (not failures):**

1. Two `apscheduler` warnings — `_run_processing_tick … skipped: maximum number of running instances
   reached (1)` at 19:48:18 and 19:55:18. Pre-existing overlap-suppression behaviour, unrelated to this
   deploy; the job is correctly skipped rather than stacked.
2. Two startup governance WARNINGs listing TRUE wFirma write flags and AI flags — the intended startup audit
   disclosure, unchanged by this deploy.
3. At 19:56 an **operator** browser session (external IPv6 client) exercised
   `POST …/wfirma/pz_create` → 200, `pz_preview` → 200, `pz_document` → 200 and generated a 10-line PZ PDF
   for PZ `195252131`. **These were not performed by this session** (agent probes originate from
   `127.0.0.1:64311`); they are recorded here as independent evidence that the live wFirma write path is
   healthy post-deploy.

## 5. GATE-4 follow-up (carried, not fixed here)

`_wfirma_error_envelope` (`routes_wfirma_capabilities.py`, deployed at ~line 371) still returns
`"error": f"{type(exc).__name__}: {exc}"` to the browser while its own comment states the raw detail is
"not shown verbatim to the operator". The operator-facing text is the classified `error_message`, so this is
a defence-in-depth issue, not a live leak of the observed responses — but the raw field should move to logs
only. **Disposition: SCHEDULED** (separate hardening slice; do not fold into a deploy-closure change).

## 6. Verdict

**Post-deployment verification PASSED. Rollback not required — the governed rollback command and its
authorization artifact were not used, and the rollback unit
`c7903686a13d1579b749c993e11b7f00a6afcdd5-20260730-194654` remains intact and available.**

The wFirma circuit-breaker stuck-OPEN defect is now fixed **in production**: the 90 s recovery timer is
reachable, admission is consolidated in `CircuitBreaker.call()`, and the `EJL/26-27/453` Resolve Mapping
path that originally failed now returns correct structured results against live wFirma.
