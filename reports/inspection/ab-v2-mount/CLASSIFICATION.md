# A/B V2 shell-mount classification

Probe: `ab_v2_mount_probe.py`  
Out: `C:\PZ-wt\rbac-s1\reports\inspection\ab-v2-mount`  
Mount timeout: 60000 ms

**Harness note:** Direct `python ab_v2_mount_probe.py` hung (uvicorn child `stdout=PIPE` deadlock). Both labels were completed via a reports-only stdio wrapper that redirects only the `ab_mount_*` boot child to DEVNULL. No `service/app/` edits.

## A (clean baseline)

| Field | Value |
|---|---|
| service_root | `C:\PZ-wt\rbac-s1-base-probe\service` |
| SHA | `ce73770fca538d8cf503eecabef02cd401296349` |
| dirty_porcelain_lines | 0 |
| has_authority_consumer_file | false |
| **ok_mount** | **true** |
| classification_hint | MOUNT_OK |

### mount_snapshot (key fields)

| Field | Value |
|---|---|
| hasReact | true |
| hasReactDOM | true |
| hasBabel | true |
| hasSidebar | true |
| hasAuthorityConsumer | false |
| rootChildren | 1 |
| hasShellTestId | false |

### Errors / assets

- pageerrors: `[]`
- failed_v2_assets: `[]`

## B (Slice 1 worktree)

| Field | Value |
|---|---|
| service_root | `C:\PZ-wt\rbac-s1\service` |
| SHA | `ce73770fca538d8cf503eecabef02cd401296349` (dirty tree; 20 porcelain lines) |
| dirty_porcelain_lines | 20 |
| has_authority_consumer_file | true |
| **ok_mount** | **true** |
| classification_hint | MOUNT_OK |

### mount_snapshot (key fields)

| Field | Value |
|---|---|
| hasReact | true |
| hasReactDOM | true |
| hasBabel | true |
| hasSidebar | true |
| hasAuthorityConsumer | true |
| rootChildren | 1 |
| hasShellTestId | true |

### Errors / assets

- pageerrors: `[]`
- failed_v2_assets: `[]`

## VERDICT

**SLICE1_OK_OR_IMPROVED**

Both A and B mount (`ok_mount: true`, `rootChildren: 1`, no pageerrors / failed V2 assets). B additionally exposes `AuthorityConsumer` and `data-testid=v2-shell-root`, and lands post-login on `/v2/shipments` directly (A still bounced through `dashboard.html` then navigated to V2). Prior 60s mount timeout was **harness** (uvicorn PIPE deadlock), not Slice 1 regression.

## Post-classification acceptance (B only)

Script: `browser_accept_slice1_b.py` → `acceptance-b/report.json`

| # | Scenario | Result |
|---|---|---|
| 1 | Logistics → `/v2/shipments` | PASS |
| 2 | CRM nav hides Accounting/Inventory | PASS |
| 3 | CRM direct `/v2/accounting` → inbox | PASS |
| 4 | CRM refresh persistence | PASS |
| 5 | Malformed `/auth/me` fail-closed → `/login` | PASS |

Scenario 5 initially failed because bare `/login` while `pz_session` remained bounced authenticated users back to landing (loop). Minimal product fix: `AuthorityConsumer.failClosedToLogin()` POSTs `/auth/logout` then navigates to `/login`. Focused Slice 0+1 tests: **37 passed**. No Tier-0 / catalogue / ROLE_MATRIX changes.
