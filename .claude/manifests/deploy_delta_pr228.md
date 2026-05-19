# Deploy Delta Manifest — PR #228 + PR #231 + PR #232
# Campaign 9 (Warsaw date + payment method) + INC-005 fix (AWB) + Campaign 4 (SSOT)
# Base target: origin/main HEAD (after PR #232 merge)
# Windows current: 7392be1 — INC-003 RESOLVED (PR #226 merged V1/V2/V3 onto origin/main)
# Profile: windows_prod_v2 (see .claude/deploy/windows_prod_v2.json)

## Pre-deploy safety check

On Windows machine:
```
git log --oneline origin/main..HEAD
```
Expected: shows `7392be1` as the only unique commit (or confirms it's an ancestor after `git fetch`).
INC-003 RESOLVED: `7392be1` is on origin/main via PR #226. Safe to `git pull --ff-only origin main` after this deploy.

## Pre-deploy steps

```
git pull --ff-only origin main
{python} -m pip install "tzdata>=2024.1"
nssm stop PZService
```
Replace `{python}` with value from `windows_prod_v2.json`.

## New directory (create if absent)

```
mkdir "C:\PZ\app\core"
```

## Files to copy (9 total, from merged PRs #228 + #231 + #232)

| # | Source dir | File | Destination dir | PR | Note |
|---|------------|------|-----------------|-----|------|
| 1 | `service\app\core` | `timezone_utils.py` | `C:\PZ\app\core` | #228 | NEW FILE |
| 2 | `service\app\services` | `wfirma_client.py` | `C:\PZ\app\services` | #228 | update |
| 3 | `service\app\services` | `customer_master_db.py` | `C:\PZ\app\services` | #228 | update |
| 4 | `service\app\services` | `freight_resolver.py` | `C:\PZ\app\services` | #232 | comment only — safe |
| 5 | `service\app\api` | `routes_customer_master.py` | `C:\PZ\app\api` | #228 | update |
| 6 | `service\app\api` | `routes_proforma.py` | `C:\PZ\app\api` | #228+#232 | update |
| 7 | `service\app\static` | `dashboard.html` | `C:\PZ\app\static` | #228 | update |
| 8 | `service\app\static` | `shipment-detail.html` | `C:\PZ\app\static` | #231 | AWB fix |
| 9 | `service` | `requirements.txt` | `C:\PZ` | #228 | update |

New docs (no deploy needed — docs only):
- `service\docs\authority-graph-commercial-draft.md` — reference doc, no Python runtime impact
- `service\tests\test_authority_graph_commercial_draft.py` — tests, no runtime impact

Robocopy pattern from profile: `robocopy "{src_dir}" "{dst_dir}" {filename} /COPY:DAT`

## Post-deploy

```
nssm start PZService
curl http://localhost:47213/health
curl http://localhost:47213/api/v1/health
```

Runtime probes (operator-locked per PROJECT_STATE):
```
Invoke-WebRequest http://127.0.0.1:47213/api/v1/proforma/service-products
pip show tzdata
Get-Process python | Select Id,CPU,WS,StartTime
```

## Smoke checks

- Dashboard loads, payment method dropdown shows: Transfer / Cash / Card / Compensation (no "other")
- Create proforma → verify `<date>` in wFirma matches today's Warsaw date (not UTC)
- Customer master PUT with payment method value saves and round-trips
- Build DHL Reply Package button in shipment-detail.html → no 422 (AWB now included in payload)
- Preview proforma → `ship_to.cm_conflict` field present (null unless divergence exists) — non-blocking
- `GET /api/v1/customer-master/` returns 200

## INC-003 clearance (update after deploy)

INC-003 is RESOLVED — V1/V2/V3 are on origin/main via PR #226. After `git pull --ff-only origin main` succeeds on Windows, update `local-commit-deploys.jsonl` MERGED entry to note Windows pull completed.

## Gate results (pre-merge of constituent PRs)

| PR | Agent | Verdict |
|----|-------|---------|
| #228 | deploy_git_diff_reviewer | CLEAR |
| #228 | deploy_persistence_storage_reviewer | CLEAR |
| #228 | deploy_backend_impact_reviewer | CLEAR |
| #228 | deploy_security_reviewer | CLEAR |
| #228 | deploy_qa_reviewer | PASS (381/366 carrier ✓, 26/26 new tests ✓) |
| #228 | deploy_release_manager | GO |
| #228 | deploy_lead_coordinator | GO |
| #231 | All 7 agents | CLEAR (1-file change — shipment-detail.html only) |
| #232 | AG tests 10/10 | PASS — additive only (comment + non-blocking field + new doc) |
| Pre-existing failures | test_pz_canonical_mapping ×2 | SCHEDULED → issue #229 |
