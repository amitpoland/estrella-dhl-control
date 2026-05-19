# Deploy Delta Manifest — PR #228
# Campaign 9: Commercial Completion (Warsaw date + payment method)
# Merged: 2026-05-19T19:36:54Z — SHA 24382c3cdd8201a59b98f69ea045a465aade9332
# Profile: windows_prod_v2 (see .claude/deploy/windows_prod_v2.json)

## Pre-deploy

```
{python} -m pip install "tzdata>=2024.1"
nssm stop PZService
```
Replace `{python}` with value from `windows_prod_v2.json`.

## New directory (create if absent)

```
mkdir "C:\PZ\app\core"
```

## Files to copy (7 total)

| # | Source dir | File | Destination dir | Note |
|---|------------|------|-----------------|------|
| 1 | `service\app\core` | `timezone_utils.py` | `C:\PZ\app\core` | NEW FILE |
| 2 | `service\app\services` | `wfirma_client.py` | `C:\PZ\app\services` | update |
| 3 | `service\app\services` | `customer_master_db.py` | `C:\PZ\app\services` | update |
| 4 | `service\app\api` | `routes_customer_master.py` | `C:\PZ\app\api` | update |
| 5 | `service\app\api` | `routes_proforma.py` | `C:\PZ\app\api` | update |
| 6 | `service\app\static` | `dashboard.html` | `C:\PZ\app\static` | update |
| 7 | `service` | `requirements.txt` | `C:\PZ` | update |

Robocopy pattern from profile: `robocopy "{src_dir}" "{dst_dir}" {filename} /COPY:DAT`

## Post-deploy

```
nssm start PZService
curl http://localhost:47213/health
curl http://localhost:47213/api/v1/health
```

## Smoke checks

- Dashboard loads, payment method dropdown shows: Transfer / Cash / Card / Compensation (no "other")
- Create proforma → verify `<date>` in wFirma matches today's Warsaw date (not UTC)
- Customer master PUT with payment method value saves and round-trips

## Lesson D reminder

Windows is at `7392be1` (V1/V2/V3 local commits). Before running `git pull --ff-only origin main`:
- Push V1/V2/V3 as a reconciliation PR first
- See INC-003 in `incident_registry.md`

## Gate results (pre-merge)

| Agent | Verdict |
|-------|---------|
| deploy_git_diff_reviewer | CLEAR |
| deploy_persistence_storage_reviewer | CLEAR |
| deploy_backend_impact_reviewer | CLEAR |
| deploy_security_reviewer | CLEAR |
| deploy_qa_reviewer | PASS (381/366 carrier ✓, 26/26 new tests ✓) |
| deploy_release_manager | GO |
| deploy_lead_coordinator | GO |
| pre-existing test failures | INC: test_pz_canonical_mapping ×2 — GitHub issue #229 SCHEDULED |
