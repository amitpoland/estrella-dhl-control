# Production reconciliation — retired `proforma-react` bundle

**Date:** 2026-08-01
**Campaign:** retire duplicate Proforma V2 frontend authority (`cleanup/retire-proforma-react`)
**Scope of this note:** production residue only. This campaign made **no production change**
and authorizes **no manual production command**.

---

## 1. What the repository change did

Deleted from the repository:

| Path | Kind | Files |
|---|---|---|
| `service/frontend/proforma-v2/` | Vite/React source of a duplicate Proforma V2 app | 16 tracked |
| `service/app/static/v2/proforma-react/` | its committed build output | 3 tracked |

Canonical Proforma V2 frontend — `service/app/static/v2/proforma-detail.jsx`, loaded by
`service/app/static/v2/index.html:326` — is **unmodified** by this campaign.

## 2. Why the endpoint existed at all

`service/app/main.py:673-704` mounts a catch-all: `@app.get("/v2/{path:path}")` serving any file
under `service/app/static/v2/`. Nothing had to link the bundle for it to be live — committing the
build directory was sufficient to publish it. `GET /v2/proforma-react/index.html` therefore served
the duplicate app to any authenticated operator who knew or guessed the URL. Deleting the directory
from the repository is what removes the endpoint; there is no route to unregister.

The route keeps its session/API-key gate for non-dev environments (`main.py:676-683`), so the
obsolete app was authenticated — but authenticated is not unreachable.

## 3. What must be true after deployment

1. **The obsolete endpoint must disappear.** After the release that carries this commit reaches
   production, `GET /v2/proforma-react/index.html` and `GET /v2/proforma-react/assets/*` must
   return **404**. Any 200 means the production directory still holds the files.
2. **`C:\PZ\app\static\v2\proforma-react\` must be checked explicitly.** Removal from
   `C:\PZ-main` does not remove it from `C:\PZ`. The runtime directory has to be inventoried by
   name — a green deploy log is not evidence of its absence.
3. **Stale accumulated bundles must not remain reachable.** Production holds *more* bundles than
   the repository ever did. Destination-only inventory
   `reports/authority-census/2026-07-01T015910Z/prod-extras-dest-to-source.log:372-382` records
   **11 files** under `C:\PZ\app\static\v2\proforma-react\` — `index.html`, **8**
   `assets/index-*.js`, and 2 `assets/index-*.css`:

   ```
   index-159CL44L.js  index-BtOUQ513.js  index-CGYvGRbx.js  index-CpcixrHE.js
   index-CWCzKKCA.js  index-CzL6IjSW.js  index-DdedaF4E.js  index-DGtR0NbZ.js
   index-B4s_xe_B.css  index-jaQaH3iP.css  index.html
   ```

   Only `index-CGYvGRbx.js` / `index-jaQaH3iP.css` / `index.html` were ever tracked in the
   repository. The other 8 are accumulated output of earlier deploys — each one an independently
   reachable URL under the `/v2/{path:path}` handler. Reconciliation must clear the **directory**,
   not the three filenames this commit deleted.

## 4. How the cleanup may happen — and how it may not

Removal of destination-only files is governed by `.claude/deploy/windows_prod_v2.json`
(SOLE configuration authority; `Deploy-PZ.ps1` is the SOLE execution authority, enforced by
`service/tests/test_deploy_authority.py`).

- `/MIR` is a **gated flag**, not a free one. Contract, `gated_flags./MIR`: *"PERMITTED ONLY after
  the destination-only inventory has classified every extraneous path, AND with
  protected_dirs/protected_files excluded. /MIR is REQUIRED for exact convergence and is the only
  mechanism that removes files a newer release introduced."*
- So: cleanup occurs **only** through that approved gated convergence process — full
  destination-only inventory first, every extraneous path classified, `protected_dirs`
  (`storage`, `logs`, `cloudflared`, `__pycache__`, `.pytest_cache`) and `protected_files`
  (`.env`, `*.pyc`, `*.pyo`, `*.zip`) excluded, run by `Deploy-PZ.ps1`.
- **No manual deletion is authorized by this campaign.** No `Remove-Item`, no ad-hoc
  `robocopy /MIR`, no hand-editing of `C:\PZ`. This note does not schedule, trigger, or approve a
  deploy; it records the requirement for whoever runs the next gated convergence.

## 5. Verification, both sides of the run

**Pre-cleanup inventory** (read-only, part of the standard destination-only inventory step):
enumerate `C:\PZ\app\static\v2\proforma-react\` recursively and record every filename and size, so
the set removed is known before anything is removed.

**Post-cleanup verification:**
- `C:\PZ\app\static\v2\proforma-react\` no longer exists;
- `GET /v2/proforma-react/index.html` → 404 and
  `GET /v2/proforma-react/assets/index-CGYvGRbx.js` → 404 (authenticated probe — the route is
  gated by design; an anonymous 401 is not a 404 and does not prove removal);
- `GET /v2/` still serves the canonical shell and `GET /v2/proforma-detail.jsx` still returns 200.

The last check is the one that matters most: convergence must remove the retired app **without**
touching the canonical one.

## 6. Rollback

Restoring the artifact is justified **only** if the canonical app is found to depend on it.
Evidence says it does not:

- `service/app/static/v2/index.html` contains no reference to `proforma-react`;
- no first-party source file references the retired tree (repo-wide guard,
  `service/tests/test_atlas_v2_sprint1.py::test_no_first_party_source_references_retired_frontend`);
- the two implementations were independent — the Vite tree was never a generator for
  `proforma-detail.jsx` and had no parity relationship with it.

If a dependency is nonetheless discovered, restore by reverting the deletion commit and
redeploying through the normal gated path — not by hand-copying files into `C:\PZ`.

---

**Safety:** no production file was read for mutation, no production command was run, no production
database or issued document was touched by this campaign.
