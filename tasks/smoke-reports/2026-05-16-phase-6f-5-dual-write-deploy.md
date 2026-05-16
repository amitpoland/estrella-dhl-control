# 6F.5 — Dual-Write Scaffolding Deploy Smoke Report

**Date:** 2026-05-16  
**Merge SHA:** `0f67d342e74c93145a96ef34aeb3b01fc4431606` (PR #121)  
**Deployed runtime files (3):**
- `service/app/core/config.py` → `C:\PZ\app\core\config.py` (22,759 bytes)
- `service/app/services/finance_dual_write.py` → `C:\PZ\app\services\finance_dual_write.py` (15,639 bytes, NEW)
- `service/app/api/routes_proforma.py` → `C:\PZ\app\api\routes_proforma.py` (172,462 bytes)

**PZService status after deploy:** RUNNING  
**Activation status:** **NOT ACTIVATED** (both flags default False)

---

## 1. Pre-deploy gate

8-agent inline review verdict: **READY-TO-MERGE-AND-DEPLOY**
- ARCHITECTURE / ACCOUNTING / BACKEND_API / DB_IDEMPOTENCY / QA / SECURITY / RELEASE / SMOKE_PLAN: all CLEAR.

Pre-deploy tests (gate sweep):
- finance_dual_write suites + dual_write_source_grep: **46/46**
- finance_postings_contracts + finance_panel_contracts + master_data_hard_rules + runner_v2_hard_rules: **88/88**
- **PZ regression: 160/160**
- `campaign_status doctor`: no issues

Aggregate: 294 tests green.

## 2. Deploy actions

| Step | Command | Result |
|---|---|---|
| Sync runtime | `robocopy "...\service\app" "C:\PZ\app" /E /XO ...` | Exit 3 — 3 files copied, 0 failed |
| Restart | `sc.exe stop PZService; sc.exe start PZService` | STATE: RUNNING |

## 3. Health checks

| Check | Expected | Actual |
|---|---|---|
| Local health | HTTP 200 | HTTP 200 ✅ |
| Public health (`https://pz.estrellajewels.eu/api/v1/health`) | HTTP 200 | HTTP 200 ✅ |
| stderr tail | uvicorn startup, no tracebacks | clean ✅ |

## 4. **HARD GATE — Flags-OFF production verification**

Three sources inspected for `FINANCE_DUAL_WRITE_*` configuration. Pydantic Settings falls back to `Field(default=False)` when no source provides a value.

| Source | Result |
|---|---|
| Operator session `Get-ChildItem env:FINANCE_DUAL_WRITE_*` | **(no entries)** — DEFAULT-OFF verified |
| `C:\PZ\.env` `Select-String FINANCE_DUAL_WRITE` | **(no entries)** — DEFAULT-OFF verified |
| NSSM `AppEnvironmentExtra` for PZService | **(empty)** — no per-service env overrides |
| Deployed `C:\PZ\app\core\config.py` field defaults | `Field(default=False, env="FINANCE_DUAL_WRITE_ENABLED")` + `Field(default=False, env="FINANCE_DUAL_WRITE_SHADOW")` — both False ✅ |

**Verdict: DEFAULT-OFF VERIFIED at all three sources + the deployed config file.**

## 5. Safe smoke (no live posting)

| Check | Expected | Actual |
|---|---|---|
| Hook + flag references in deployed routes_proforma.py | ≥ 2 hits | **4** ✅ |
| `finance_dual_write.py` deployed | exists | 15,639 bytes ✅ |
| Hook AFTER `mark_post_succeeded` (byte offsets) | True | hook@160442 > mark@158368 ✅ |
| `GET /api/v1/finance/postings/9999999/breakdown` | HTTP 404 | HTTP 404 `{"detail":"Posting not found: id=9999999"}` ✅ |
| `C:\PZ\storage\finance_postings.sqlite` size unchanged | 81,920 bytes | 81,920 bytes ✅ |
| `grep -c finance_dual_write` in `pz_stderr.log` | 0 | **0** ✅ |

No live proforma posting performed (operator-driven smoke deferred). The breakdown endpoint already exists from 6F.3 and remains stable.

## 6. Verdict

**6F.5 scaffolding deploy: PASS. Activation: NOT PERFORMED. Activation: NOT APPROVED.**

The dual-write code is now in production at `C:\PZ\app\services\finance_dual_write.py` and the hook is wired in `routes_proforma.py`, but both feature flags are False at every inspected source. Production behaviour is bit-identical to pre-deploy.

A separate operator decision is required to activate. See approval package §2 ("Enabling sequence" — 4-step gated rollout) and decision memo §5 ("binding conditions").

## 7. Rollback (if needed)

```bash
git revert -m 1 0f67d342e74c93145a96ef34aeb3b01fc4431606 --no-edit
git push
# Then merge the revert PR, robocopy, restart PZService.
```

This reverts to the state before PR #121 (no dual-write helper, no hook in routes_proforma.py, 6F.4 panel still live, 6F.3 breakdown endpoint still live).
