# Runbook — V2 Proforma Detail (wireframe rebuild, campaign PFW)

Scope: operating, verifying, and rolling back the proforma detail page shipped
by PRs #870/#872/#874/#875 (production `b1caafd4`, 2026-07-10).

## Deployment (app channel only — no engine files in this campaign)

1. On the deploy tree: `git fetch && git checkout <target SHA>` — **verify the
   tree is actually on the target SHA before syncing** (Slice-4 incident: the
   first robocopy copied feature-branch bytes; caught by hash-match).
2. `robocopy service\app C:\PZ\app /MIR <standard flags> /XD storage` —
   the `/XD storage` exclusion is mandatory (deploy hygiene).
3. Clear pycache recursively:
   `Get-ChildItem -Path C:\PZ -Recurse -Filter __pycache__ | Remove-Item -Recurse -Force`
4. Restart `PZService` — **then confirm it is RUNNING** (Slice-3 incident: the
   service was left stopped for ~1h post-deploy).
5. Hash-match the deployed page (LF-normalized SHA-256 of
   `C:\PZ\app\static\v2\proforma-detail.jsx` vs the repo file at the target SHA).

## Smoke tests (2 minutes, browser)

Open `/v2/proforma_detail?batch_id=<batch>&draft=<id>` on a real draft:

- All 8 tabs render (Overview · Items · Source & Extraction · Logistics ·
  Documents · Audit Trail · Customer Mapping · Reservation).
- Toolbar shows the eyebrow ("PRO FORMA DRAFT" + number + status chip) and the
  full action row; Post/Convert/Print disabled reasons are honest for the
  draft's state.
- Items tab: variant columns (Kt/Col/Quality/Dia Wt/Col Wt/Size/Client PO)
  show data for post-2026-07-10 drafts, `—` for older ones (expected — see
  Common failures).
- ⚡ AWB Generate opens the DHL form (do NOT submit unless booking is intended).
- Console: zero errors.

## Monitoring

- `C:\PZ\logs\pz_stderr.log` — grep `proforma|carrier|awb`; the page itself is
  render-only, so page regressions surface as Babel/console errors in the
  browser, not stderr.
- `GET /api/v1/health` → 401 = alive+auth-gated; `/docs` → 200.
- First-observation-period monitors are owned by the POST-RELEASE
  STABILIZATION-1 session (draft lifecycle, webhook delivery, PM sync,
  carrier, stderr).

## Common failures & recovery

| Symptom | Cause | Recovery |
|---|---|---|
| Whole V2 app blank / `ProformaDetailPage is not defined` | Babel parse error anywhere in proforma-detail.jsx (one syntax error kills the entire file's script) | Check browser console for the Babel SyntaxError line; fix or roll back. Never leave a JSX comment between `return (` and the root element. |
| Variant columns all `—` on an old draft | Fields are stored at birth/reset only | Expected. Operator refresh path: "Reset draft from sales packing" (destructive to line edits) or next intake. |
| KUKE panel all `—` + "Customer Master unavailable" | Draft has no `client_contractor_id`, no CM row, or CM fetch failed | Fix customer mapping (Customer Mapping tab → Customer Master). Panel is advisory; nothing is blocked. |
| Stale page after deploy | `.jsx` served with cache | `serve_v2_static` sends no-store for .jsx (Lesson G); hard-refresh; verify hash-match step 5. |
| NBP table `—` | No `fx_rates` row for (rate date, currency) | Operator-managed reference store — add the observation in master data; display-only. |

## Rollback

Campaign commits stack on one file — **revert in reverse order only**:

```
git revert b1caafd4   # Slice 4 (KUKE panel)
git revert 52ee8ad2   # Slice 3 (render layer)
git revert 7ca509e8   # Slice 2 (primitives)
git revert 709f8592   # Slice 1 (backend fields — leaves inert JSON keys, no data loss)
```

then redeploy per the steps above. Partial rollback to pre-campaign UI with
Slice-1 data retained = revert #875+#874+#872 only. All slices are
render/additive layers; no schema migrations were made, so reverts never orphan
writes.

## Escalation

Operator (amitpoland). Fiscal writes (post/convert/AWB) remain flag- and
token-gated regardless of page state; a page defect cannot autonomously post
to wFirma or book carriers.
