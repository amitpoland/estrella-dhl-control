# PR #940 — GATE-6 Browser Verification: COMPLETE → READY_FOR_REVIEW

**Date:** 2026-07-17 · **Session:** M1-gate owner (transport-m1) · **OS:** EJ Engineering OS v1.4
**Supersedes:** `2026-07-17-pr940-gate6-hold.md` — the three "environment blockers" in that HOLD
were surmounted (see §Blocker resolution). **#940 stays DRAFT** (merge operator-gated).

## Outcome: READY_FOR_REVIEW (with one disclosed environment-limited sub-check)

Valid GATE-6 browser verification WAS completed in this environment via an isolated, non-prod local
review instance that **demonstrably serves commit 13d442e9** with representative carrier/shipment
data built through the real create-path. 5 of 6 scenarios fully browser-verified; scenario 4
(CMR positive country label) code + unit-test verified with honest-null observed in-browser.

## Preconditions (PASS)
OS v1.4; registry owner = this session, expected_head=last_verified_head=13d442e9, lock null; C:\PZ-pr7
HEAD 13d442e9, clean, no rebase/merge in progress; PR #940 OPEN/DRAFT/MERGEABLE @13d442e9. Session-
collision reconciled: operator partitioned transport-m1 to this session; the sole-coordinator did not
touch C:\PZ-pr7/lock and closed out its #938/#939/#932 work.

## Blocker resolution (vs the prior HOLD's 3 "absent prerequisites")
- **B1 no server serves 13d442e9** → SURMOUNTED. Bash-launched `uvicorn --app-dir service` from
  cwd `C:\PZ-pr7` (not preview_start, which uses the session tree C:\PZ-verify). Fingerprint:
  startup log `Engine dir: C:\PZ-pr7`; HTTP `/v2/*` asset sha256 == working-tree sha (4/4 MATCH);
  served proforma-detail.jsx carries `invoice_ref: invoiceProjection.invoiceNumber || null`.
- **B2 no non-prod auth** → SURMOUNTED. `ENVIRONMENT=dev` + empty `API_KEY` = auth disabled
  (security.py:18-24, only 503s when environment==prod). No prod secret used.
- **B3 no safe representative data** → SURMOUNTED. Real create-path
  `auto_create_draft_from_sales_packing()` + real `insert_shipment`/`update_state` (shadow/simulated)
  + `compute_idempotency_key`. Isolated `STORAGE_ROOT` (scratchpad). Two-client batch + a legacy
  batch. NOT hand-forged SQL.
- **Live-DHL safety** → `carrier_live_allowlist=""` makes the live adapter raise on every batch
  (live.py:218) — zero live DHL calls; DHL/wFirma creds unset; `WFIRMA_CREATE_*=false`.

## Scenario results
| # | Scenario | Verdict | Evidence |
|---|---|---|---|
| 1 | Draft-specific shipment isolation | PASS | ALPHA AWB 1112223330/CMR-D10E6710D1 vs BRAVO 9998887770/CMR-52D9AD4E1D — distinct (rendered innerText + API) |
| 2 | No cross-client leak | PASS | BRAVO view = own AWB, ALPHA's 1112223330 ABSENT (both directions, incl. CMR body); unknown CLIENT_CHARLIE → 404 honest-missing |
| 3 | Legacy AWB rebook confirm/cancel | PASS (probe) + covered | Modal-open fires client-scoped `GET .../legacy-probe → 200` (legacy_exists:true/has_client_row:false; ALPHA→has_client_row:true suppression). Cancel created NO booking (no POST /shipment; DB stays 3 rows). Submit-confirmation pinned by test_awb_legacy_rebook_confirm.py (31) + security-review |
| 4 | CMR full-country rendering | CODE-VERIFIED + honest-null observed | `_cmrCountryName`/`_CMR_COUNTRY_NAMES` (IN→India) + goods_origin_country builder are data-driven w/ honest-null (2026-07-16 Condition-1 fix). Browser showed honest-null omission (Product-Master/packing origin authority not seeded; packing/lines 401'd). Per-line ISO = chip task_35c61ad8. Positive render pinned by CMR origin unit tests |
| 5 | Packing human invoice number + honest-null | PASS | ALPHA renders `FV 5/2026`; BRAVO (no invoice) renders NO FV = honest-null |
| 6 | Canonical routes + clean console | PASS | All carrier calls client-scoped GETs; only non-carrier POST = read-only /proforma/preview; NO POST /carrier/.../shipment; console = only in-browser-Babel perf warnings |

## No-unintended-write proof
Zero `POST /carrier/{batch}/shipment`; carrier DB unchanged (3 rows); instance STORAGE_ROOT =
isolated scratchpad; prod `C:\PZ\storage\carrier\carrier_shipments.db` mtime = 2026-07-15 (untouched);
prod PZService (:47213) still Running independently. No wFirma write (creds unset → series
refresh source=error).

## Tests at exact 13d442e9 (all #940-relevant green; failures pre-existing/env)
Root golden 160/160; transport/document 86; #939 reconcile/terminal/invoice-link 213 pass/1 skip;
carrier 926 pass / 17 pre-existing-env (proven vs main baseline 9417a32f — none in #940 diff; 4
DHL-creds reds + isolation-class); PZ+weight+authority 75 pass / 1 pre-existing #613 CSV-CRLF red.
Carrier 584 baseline NOT breached; baseline unchanged (operator constraint honored).

## Review gates
/code-review (medium): APPROVE — no blockers; 3 non-blocking suggestions (chips task_35c61ad8,
task_ab702256, + cross-route private import). /security-review: NO HIGH/CRITICAL, NO BLOCK — SQL
parameterized, no auth downgrade, 3-layer cross-client defense-in-depth, no traversal/creds/live-write.

## Disposition
- **#940 stays DRAFT / merge operator-gated.** No merge, no deploy, no live write, no baseline change,
  no registry lock transfer, C:\PZ-pr7 untouched (verification used a separate isolated instance).
- Recommended pre-merge follow-up (operator's call): a positive CMR-country ("India") browser render
  once the Product-Master origin authority is seeded — logic is already code + unit verified.
- Post-merge tail unchanged: carrier baseline 584→596; PZ-pr7 → C:\PZ-active.
