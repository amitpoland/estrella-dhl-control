# Evidence note — Draft #73 `EJL/26-27/453-1/-2/-3` blocker: data-resolved, not code-changed

**Date:** 2026-07-30
**Scope:** Read-only diagnosis (no code change, no fiscal write, no production mutation).
**Draft:** Pro Forma Draft #73 (Diamond Point B.V., USD), invoice lot `EJL/26-27/453`.
**Trigger:** Readiness panel showed "⛔ Not ready — 1 blocking reason": *3 product(s) not
matched in wfirma_products (missing wfirma_product_id): EJL/26-27/453-1, -2, -3*, plus the
"Resolve mapping → wFirma is temporarily unavailable (gateway error)" message per code.

## Verdict

The panel was **accurate when it rendered** but is **now stale**. The single blocker has
cleared at the **data layer** (the three lots are registered in wFirma and synced into the
mirror). No proforma/readiness code was changed to resolve it. The "gateway error" was a
**wFirma circuit-breaker stuck-OPEN** defect whose fix is already deployed.

## Check 1 — mapping table (production `reservation_queue.db` → `wfirma_product_mirror`)

Read-only query (`file:...?mode=ro`) of `C:\PZ\storage\reservation_queue.db`:

| product_code | wfirma_id | deleted_flag | last_sync (UTC) |
|---|---|---|---|
| `EJL/26-27/453-1` | `51495203` | 0 | 2026-07-30T17:54:49Z |
| `EJL/26-27/453-2` | `51495331` | 0 | 2026-07-30T17:55:08Z |
| `EJL/26-27/453-3` | `51495267` | 0 | 2026-07-30T17:54:55Z |
| `EJL/26-27/453-4` | `51495651` | 0 | (present) |

Mirror total = 179 rows, all with non-empty `wfirma_id`. The readiness gate
(`routes_proforma.py` §3, lines ~7394–7415) resolves each billed `product_code` via
`_c1f_mirror_good_id()` → `reservation_db.get_mirror_product()`; all three now return a
confirmed id, so the "not matched in wfirma_products" block no longer fires.

## Check 2 — 502 "gateway error" root cause + fix status

Root cause was **not** a prolonged wFirma outage. It was the **wFirma circuit breaker wedged
OPEN**: admission read the raw `.state` property, which never calls `_maybe_transition()`, so
the 90s OPEN→HALF_OPEN recovery could never fire — every wFirma call short-circuited to a
gateway error until a manual service restart.

Confirmed fixed and live in deployed `C:\PZ\app\core\circuit_breaker.py` (prod
`version.txt = 922228499746e694c7e261171ac6bc055aa79932`):

- admission now flows through `call()` (line 106) → `_maybe_transition()` (line 125);
- the `.state` property carries an explicit "Do NOT use it as an admission gate … reintroduces
  the stuck-OPEN defect" warning (line ~190);
- wFirma/ERP breaker `recovery_timeout = 90` (line ~336).

Shipped in PRs #1040/#1041 (wFirma breaker, prod `c7903686`) and preserved through the later
Cliq breaker fix #1042 (prod `92222849`). Deploy verified previously (`Test-PZDeployClose`
10/10). Once the breaker could self-recover, the "Resolve mapping" calls reached wFirma and
the three lots were created + synced (the 17:54–17:55Z timestamps above).

## Net

- Blocker: cleared (data-level; all 3 codes mapped).
- Gateway 502: root cause fixed and live; breaker auto-recovers in ~90s instead of wedging
  until restart.
- Remaining panel items (`PURCHASE_TRANSIT` stock, `vies_unverified`) are advisories and
  correctly do not gate (Lesson N).

**Operator action:** reload Draft #73 / re-check readiness — the one blocking reason should be
gone, leaving only advisories; Approve / Post / Convert unlock. Fiscal actions remain
operator-gated and were not performed by this diagnosis.

## Related

- `project-wfirma-breaker-stuck-open-bug` (root cause of this `EJL/26-27/453` gateway error)
- `project-cliq-breaker-recovery-pr1042` (same `.state` anti-pattern, Cliq side; prod `92222849`)
- `project-draft73-charge-unwrap-gateway-pr1036` (the clean gateway-error *message* + retry affordance)
