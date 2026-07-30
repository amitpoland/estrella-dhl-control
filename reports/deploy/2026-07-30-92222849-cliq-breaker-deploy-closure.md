# Post-deployment closure — Cliq circuit-breaker recovery (PR #1042)

**Deployed SHA:** `922228499746e694c7e261171ac6bc055aa79932` (merge commit)
**Reviewed head:** `6d6d272afc2814f807f60b100ca712e650c4ad3e` — ancestor of the deployed SHA
**Previous production SHA:** `c7903686a13d1579b749c993e11b7f00a6afcdd5`
**Backup / rollback unit:** `922228499746e694c7e261171ac6bc055aa79932-20260730-220450`
**Merge + deploy performed by:** operator, via `gh pr merge --merge` and `Deploy-PZ.ps1` (governed path).
**Verification performed by:** agent session, read-only. **No production write, no wFirma write, no Cliq
message, no fiscal / inventory / customs / accounting / mapping / invoice mutation was performed.**

---

## 1. Content identity — what actually shipped

The merge was a merge-commit over a fast-forwardable branch, so the merge commit's tree is **identical**
to the reviewed head's tree. The deployed bytes are exactly what passed the verification gate.

| Check | Value | Result |
|---|---|---|
| tree(`92222849`) | `e358d6c2f9e7ebe009a639caef47ec82a59bb15a` | **identical** |
| tree(`6d6d272a`) | `e358d6c2f9e7ebe009a639caef47ec82a59bb15a` | **identical** |
| `merge-base --is-ancestor 6d6d272a 92222849` | exit 0 | PASS |
| `C:\PZ\version.txt` | `922228499746e694c7e261171ac6bc055aa79932` | matches |
| `origin/main` | `922228499746e694c7e261171ac6bc055aa79932` | matches |

**Blast radius (content, not copy count — Lesson P):** exactly **one** production file.

| File | Source blob @ 92222849 | Deployed blob | Result |
|---|---|---|---|
| `app/services/cliq_service.py` | `7f54d532e14f0b82de40b8aeb0df92fec08b1f6d` | `7f54d532e14f0b82de40b8aeb0df92fec08b1f6d` | **byte-identical** |
| `app/core/circuit_breaker.py` (off-limits) | `d698392f6e13d72bbe45bec4cdc590daf332e77d` | `d698392f6e13d72bbe45bec4cdc590daf332e77d` | **untouched** |

The other two files in the PR are `service/tests/*` — non-production, not deployed. The off-limits
`circuit_breaker.py` is unchanged from main, so PR #1042 remains independently revertable.

## 2. Governed closure (operator-run) + service state

`Test-PZDeployClose.ps1 -ExpectedSHA 92222849…` — **10/10 gates PASS**, run without `-Verbose` and
outside `Start-Transcript` per the credential-hygiene rule. Manifest parity 0 discrepancies; engine
parity PASS; protected runtime paths intact.

Independent agent re-verification:

| Check | Result |
|---|---|
| PZService | **Running**; python pid **20172** owns the listener on 127.0.0.1:47213 |
| Restart loop | **None** — exactly **one** `Started server process [20172]`; `pz_stderr.log` holds only the four normal uvicorn startup lines |
| Health (local, authenticated) | **HTTP 200** — `{"status":"ok","engine":"ok","environment":"prod"}` |
| Health (public, authenticated) | **HTTP 200** — `https://pz.estrellajewels.eu/api/v1/health` |
| Health auth not weakened | unauthenticated local **and** public → **HTTP 401**. Correct fail-closed behaviour |
| Backup unit | present — `unit.json` `{"scope":"Both","app_backed_up":true,"engine_backed_up":true,"bootstrap":false,"complete":true}` |
| Health watchdog | single `FAIL [1/2]` at **22:04:48** (the deploy's own service-stop window) → `HOLD` (**no watchdog restart issued**) → `RECOVERED HTTP 200` at 22:05:46 → continuous `OK HTTP 200` through 22:10:46 |

## 3. Authorization hygiene

| Artifact | jti | Consumed | Expires |
|---|---|---|---|
| deploy / Both | `b77e4759-da9c-4d95-a0f5-28a12e2d93ca` | **True** — `consumed/b77e4759….used` @ 22:04:39 | 2026-07-30T21:04:24Z (elapsed) |
| rollback / Both | `f60b7cd0-16b9-4404-90ac-f0fc863fdb04` | **False — deliberately available** | 2026-07-31T20:04:24Z |

Consumption was determined by testing for the `consumed/<jti>.used` marker and reading the artifact's
`jti`/`action`/`scope` fields only — **`evaluate()` was NOT run against the rollback artifact**, because
it consumes the jti on success. No signature or key material was read or printed.

## 4. Log review (post-deploy window)

| Signal | Finding |
|---|---|
| Repeated `CircuitBreakerError` | **0** — zero `circuit` / `breaker` / `CircuitBreaker*` matches |
| HALF_OPEN probe storm | **0** — no HALF_OPEN transitions at all |
| Unhandled exceptions | **0 tracebacks, 0 `ERROR` lines** |
| HTTP 5xx | **0** |
| Credential leakage | **0 matches** across `X-API-Key`, `api_key=`, `access_key`, `secret_key`, `client_secret`, `refresh_token`, `oauthtoken`, `Authorization:`, `password`, `WFIRMA_ACCESS/SECRET` |
| Cliq messages | **0** Cliq / `post_to_channel` / Zoho lines — **no Cliq message was emitted, authorized or otherwise.** No test notification was sent to `#pz` or any other channel. |

## 5. Recovery-path correctness (no failure injection, no live Cliq send)

Deliberately tripping the production Cliq breaker or sending a test notification is out of scope, so
correctness is established from the **deployed** file plus the merged test suite:

- `C:\PZ\app\services\cliq_service.py`: **0** raw `.state` gates; **0** direct `_on_success`/`_on_failure`
  calls (the single textual match is inside the explanatory comment at line 310); **2** admission sites,
  both `await asyncio.to_thread(breaker.call, …)` — `_do_refresh` (:255) and `_do_post` (:326); **3**
  `CircuitBreakerProbeInProgress` handlers. `CircuitBreaker.call()` is now the sole admission authority,
  so `_maybe_transition()` — and with it the recovery deadline — is reachable on every call.
- OAuth credentials travel in the form-encoded **body** (`data=`, :244), not the query string, so a
  `raise_for_status()` `HTTPStatusError` cannot embed secrets in its `str()` and leak them into the
  `log.error("…%s", exc)` fallback. Confirmed by the zero credential matches above.
- `C:\PZ\app\core\circuit_breaker.py`: `class CircuitBreakerProbeInProgress(CircuitBreakerError)` present
  at :74 (3 occurrences). `zoho_cliq` config **unchanged** — `failure_threshold=5`, `recovery_timeout=60`,
  `call_timeout=15`, `retry_attempts=3`. The timer was made *reachable*, not retuned.
- **ImportError risk retired empirically**: `cliq_service` is imported at boot by five registered route
  modules (`routes_batch`, `routes_bot`, `routes_dashboard`, `routes_debug`, `routes_pz`), and the service
  reached `Application startup complete` with zero tracebacks — the import chain resolved cleanly.
- Return contracts preserved: `post_to_channel` still returns `bool`; both breaker exceptions log a
  warning and return `False`; `_refresh_access_token` returns the cached token on breaker rejection. The
  401 → refresh → retry-once loop is intact at the async level.

## 6. Verdict

**Post-deployment verification PASSED. Rollback not required** — the rollback unit
`922228499746e694c7e261171ac6bc055aa79932-20260730-220450` and its unconsumed authorization
(`f60b7cd0…`, valid to 2026-07-31T20:04Z) remain intact and available.

The Cliq circuit-breaker stuck-OPEN defect is fixed **in production**. Both raw-`.state` split-admission
anti-patterns (wFirma in `c7903686`, Cliq in `92222849`) are now eliminated; a Cliq outage can no longer
silence PZ batch-completion notifications until a service restart. **Restart is no longer the remedy for
breaker recovery on either integration.**

## 7. Carried, not fixed here

1. `_wfirma_error_envelope` (`routes_wfirma_capabilities.py` ~371) still returns the raw
   `f"{type(exc).__name__}: {exc}"` to the browser — **SCHEDULED**, backend-only, separate slice.
2. Five raw `httpx.AsyncClient` Cliq paths remain unbreakered (pre-existing; unchanged by this PR), and
   `routes_pz.py:149/184` call `post_to_channel` / `deliver_batch_result` bare — **GATE-4, unscheduled**.
3. `dhl_client` has not been audited for the same `.state` anti-pattern — **GATE-4, open**.
4. Merged local branch `fix/cliq-breaker-recovery` is still checked out in worktree
   `C:\PZ-verify\.claude\worktrees\nice-chaum-b2853b`; deletion deferred pending an ownership +
   clean-state check (operator instruction, GATE-3 discipline).
