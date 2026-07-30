# PR #1042 Cliq breaker recovery — campaign closure — 2026-07-30

**Verdict: CLOSED — Completed.** The fix is merged, deployed, live-verified, and every
GATE-4 follow-up is dispositioned. No blocker remains.

**Authority:** Session/campaign discipline (inspect→implement→test→deploy→verify→close) +
GATE-1 (reviewer verdicts / green regression / forbidden-files) + GATE-2 (≤3 open PRs) +
GATE-4 (every follow-up finding gets exactly one disposition) + Deploy-source discipline +
Council-authorized merge gate (#950).

**Scope:** one production file, `service/app/services/cliq_service.py`. The circuit-breaker
core (`service/app/core/circuit_breaker.py`) was **not** modified — deployed byte-identical to
main, leaving #1042 independently revertable and isolated from #1041. No financial / customs /
inventory / fiscal write path was changed. The only production mutation was the governed
whole-tree `/MIR` deploy; the only external writes this session were four GitHub issues.

---

## 1. Defect (what was closed)

`post_to_channel` / `_refresh_access_token` gated admission on the breaker's **raw `.state`** and
returned *before* `breaker.call()` ran. OPEN→HALF_OPEN recovery only happens inside `call()`
(`_maybe_transition`), so the `zoho_cliq` breaker never evaluated `recovery_timeout` → it stayed
OPEN until a PZService restart, silencing **every** PZ batch-completion notification. Identical
anti-pattern to the wFirma breaker fixed in #1041. Admission now flows through
`await asyncio.to_thread(breaker.call, …)` with a sync `httpx.Client`; the 90s timer is now
*reachable* — not retuned (`zoho_cliq` config unchanged: 5 / 60s / 15s / 3). A HIGH security
finding (OAuth creds via `params=` → leak into `httpx.HTTPStatusError.str()` → logs) was fixed by
moving creds to the `data=` form body, with a regression test driving a real `httpx.MockTransport`.

---

## 2. Lifecycle evidence

| Phase | Evidence | Result |
|---|---|---|
| Implement | 2 commits + reviewer fixes; test-only head `6d6d272a` adds the 2 missing wrapper-branch tests | reviewed head `6d6d272afc2814f807f60b100ca712e650c4ad3e` |
| Test | wrapper+cliq 28/28 both orderings; core breaker 30/30; smoke 63 pass / 1 skip; 58 targeted green | GATE-1 all reviewers PASS/SHIP, zero BLOCK/HIGH |
| Gate | 7-agent pre-deploy gate over `923e437e..6d6d272a` | deploy-lead-coordinator **READY-TO-DEPLOY** |
| Merge | `gh pr merge --merge` (operator-run; agent path hook-denied by #950, no signer) | **MERGED** `92222849…` at 2026-07-30T20:00:50Z; tree == reviewed `6d6d272a` |
| Deploy | governed whole-tree `/MIR` from C:\PZ-main; deploy jti `b77e4759…` consumed | prod `version.txt` = `922228499746e694c7e261171ac6bc055aa79932` |
| Verify | PZService Running (pid 20172 owns :47213); one `Started server process` (no restart loop); health 200 authenticated / **401 unauthenticated** (auth not weakened); manifest 0 discrepancies | **LIVE VERIFIED** |

**Content parity:** deployed `cliq_service.py`, normalized via `git hash-object --path=`, matches
canonical blob `7f54d532…` at `92222849` exactly; `circuit_breaker.py` matches main
(`d698392f…`). Deployed-file markers: 0 raw `.state` admission gates, 2 `to_thread(breaker.call)`
admissions, `CircuitBreakerProbeInProgress` handlers present, creds in `data=` body, 0 `params=`
creds. Logs across the deploy window: 0 breaker/HALF_OPEN lines, 0 tracebacks, 0 ERROR, 0 HTTP
5xx, 0 credential matches, **0 Cliq messages emitted** (no test notification sent — no approved
test channel; recovery confirmed from tests + logs only).

**Rollback:** unit `922228499746e694c7e261171ac6bc055aa79932-20260730-220450` intact; rollback jti
`f60b7cd0…` deliberately **UNCONSUMED** (valid to 2026-07-31T20:04Z). Not needed — no rollback
performed. Deploy closure detail: `reports/deploy/2026-07-30-92222849-cliq-breaker-deploy-closure.md`.

---

## 3. GATE-4 dispositions (all closed to a single disposition)

| Item | Disposition | Issue |
|---|---|---|
| 4 unbreakered raw-httpx Cliq paths (`post_message`/`post_file`/`_authed_get`/`download_cliq_file`) + bare `routes_pz.py:149/184/233` calls | ISSUE | [#1046](https://github.com/amitpoland/estrella-dhl-control/issues/1046) |
| `_wfirma_error_envelope` raw-exception disclosure (response body + logs) | ISSUE (was SCHEDULED) | [#1044](https://github.com/amitpoland/estrella-dhl-control/issues/1044) |
| `routes_wfirma_capabilities` wFirma-write POSTs on `require_api_key` not `require_admin` (instance of #504) | ISSUE (was SCHEDULED) | [#1047](https://github.com/amitpoland/estrella-dhl-control/issues/1047) |
| `build_pz_batch.py` / `build_wfirma_pz_csv.py` drive-root output default at deployed location | ISSUE | [#1045](https://github.com/amitpoland/estrella-dhl-control/issues/1045) |
| DHL `dhl_client` `.state` audit | **RESOLVED-NEGATIVE, no issue** | no `dhl_client.py`; 3 benign `.state` matches repo-wide; `carrier/adapters/live.py` has 0 breaker refs |

All four issues confirmed **OPEN** at closure. They are independent future work, **not** campaign
blockers — the deployed fix is complete and correct on its own.

---

## 4. Structural outcome

Both raw-`.state` breaker twins are now gone (wFirma in `c7903686`, Cliq in `92222849`).
**Restart is no longer the remedy for breaker recovery on either integration** — the class of
stuck-OPEN incident that this and #1041 addressed is closed at the source. GATE-2 respected
throughout (≤3 open PRs). Worktree follow-up discharged separately
(`reports/campaigns/2026-07-30-worktree-governance-cleanup.md`).

**Nothing carries forward from this campaign except the four independent GATE-4 issues above.**
