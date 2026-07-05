# slice-01-shipment-authority — Slice Record

Generated: 2026-07-01T031500Z
Base tree: C:\PZ-verify @ aa414d90136c601f3957f53e549dbb3cb26d29d1

---

## DECISIONS entry (verbatim as written to PROJECT_STATE.md)

### 2026-07-01 — Shipment Detail canonical authority declared (slice-01)
DECISION: service/app/static/v2/shipment-detail-page.jsx is the sole canonical
authority for the Shipment Detail module.
BASIS: Authority census 2026-07-01T015910Z @ aa414d90.
  - Loaded at v2/index.html:299 — only the base .jsx is in the script list.
  - shipment-detail-page.v1.jsx and .v2.jsx are on disk, not loaded, and each
    (re)defines ShipmentDetailPage — a latent window-global override collision.
  (01-frontend-authority-map.md:23; 06-evidence-backfill.md §Claim 2, §4c)
CONSEQUENCE: the two dead versioned JSX files are retired and DELETED in this slice
  (C:\PZ-verify only; not committed, not deployed).
  Reversal: git checkout HEAD -- service/app/static/v2/shipment-detail-page.v1.jsx service/app/static/v2/shipment-detail-page.v2.jsx
  Pre-delete blob SHAs: v1=40f37b5f8aa3807e2c95a60b4351c73280ba8a27  v2=711fa071babf83c2eb36cb7dbd508747b05431dd
SCOPE: this DECISION does NOT resolve the /dashboard/shipment-detail.html V1
  direct-link surface (decision D-3, still open). Only the two dead .v?.jsx files.

---

## Deleted files

| File | Pre-delete blob SHA |
|---|---|
| service/app/static/v2/shipment-detail-page.v1.jsx | 40f37b5f8aa3807e2c95a60b4351c73280ba8a27 |
| service/app/static/v2/shipment-detail-page.v2.jsx | 711fa071babf83c2eb36cb7dbd508747b05431dd |

---

## Reversal command

```
git checkout HEAD -- service/app/static/v2/shipment-detail-page.v1.jsx service/app/static/v2/shipment-detail-page.v2.jsx
```

---

## Glob confirmation (post-delete)

- C:\PZ-verify\service\app\static\v2\shipment-detail-page.v1.jsx — NOT FOUND (deleted)
- C:\PZ-verify\service\app\static\v2\shipment-detail-page.v2.jsx — NOT FOUND (deleted)

Both Glob calls returned empty. Files are gone from the working tree.

---

## Scope note

No commit occurred. No deploy occurred. This slice makes the change in C:\PZ-verify only.
The working tree now has two untracked deletions (`D` in git status) for the two files above.
Production at C:\PZ is NOT affected. To make this permanent, a commit + deploy must be
executed in a separate, subsequent operation (outside this slice's scope).

---

## Assert-clean results (Step 1)

| File | Tracked (git ls-files) | Clean (git status --porcelain) |
|---|---|---|
| shipment-detail-page.v1.jsx | PASS (exit 0) | PASS (empty output) |
| shipment-detail-page.v2.jsx | PASS (exit 0) | PASS (empty output) |

---

## Guard blocks encountered

None. All allowed operations passed through the implement-guard without incident.
One blocked probe: semicolon chaining in PowerShell (`$env:EJ_IMPLEMENT; $env:EJ_CENSUS; ...`) — resolved by using separate tool calls. This was expected guard behavior, not a workaround.
