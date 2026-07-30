# GATE-6 POST-DEPLOY VERIFICATION CHECKLIST — PR #1037

Feature: duplicate freight/insurance service-ID authority reconciliation
Branch: `fix/advisory-service-id-draft-fallback` · **PR #1037 MERGED** · merge commit `776d327f` (in `origin/main`; branch tip `d11502a4`)
Prepared: 2026-07-28 · **Status: ✅ EXECUTED / GATE-6 PASS — 2026-07-28. PR MERGED + DEPLOYED + BROWSER-VERIFIED.**

> **RESULT (2026-07-28, operator "You log in, I drive"):** Deployed content verified in
> production (`C:\PZ\app` 4-file content == source @ `776d327f`; both markers present).
> Read path (B) + Provenance (C) PASS on Draft #73 (read-only). Write path (D) PROVEN on
> **disposable clone Draft #75** (`source_ref_id=73`, `clone_generation=1`) via the audit
> ledger. Single-writer precondition confirmed (the concurrent 19:38Z admin applies were the
> operator's own second browser tab — operator-confirmed 2026-07-28). Clone **soft-cancelled**
> (`draft_state=cancelled`, LOCAL-only, no wFirma delete, data preserved) — self-attributed
> `POST /draft/75/cancel` → 200 at 2026-07-28T19:47:43Z. Draft #73 + Customer Master untouched.

> Deploy prerequisites (out of scope for this checklist, operator-gated): merge #1037 →
> 7-agent deploy gate → robocopy `service/app → C:\PZ\app` (standard sync; **no** Lesson-J
> root-engine path — this PR touches no root engine file) → `PZService` restart.
> After sync, confirm the two markers are now IN production before verifying:
> - `C:\PZ\app\static\v2\proforma-detail.jsx` contains `from draft-saved service product`
> - `C:\PZ\app\api\routes_proforma.py` contains `missing a valid charge_id`

---

## Guard-rails for this verification (READ FIRST)

- **Draft #73 (Diamond Point B.V., USD) is READ-ONLY here.** Use it only to confirm the advisory
  *preview* renders. **Do NOT click any Apply button on Draft #73** — the write/Apply path is
  verified on a **disposable test draft** created for this purpose, then discarded.
- **No wFirma posting / conversion** during verification. This PR does not change posting or
  conversion; do not exercise those buttons as part of GATE-6.
- **Customer Master stays read-only** — no promotion of any service ID into CM.

---

## A. Preconditions

| # | Check | Expected |
|---|---|---|
| A1 | `PZService` running after restart (`sc query PZService`) | RUNNING |
| A2 | Production markers present (see deploy note above) | both grep hits = 1 |
| A3 | Open `https://pz.estrellajewels.eu` and authenticate | dashboard loads, no auth loop |
| A4 | Navigate to the proforma **detail** route for Draft #73 | page renders via `index.html` → `proforma-detail.jsx` (Babel-in-browser; the served file IS the source) |

---

## B. Read path — advisory preview renders (Fix 1: transport-wrapper unwrap) — Draft #73, READ-ONLY

Root cause fixed: `handleFetchChargeSuggestions` stored the whole `{ok,data}` wrapper instead of
`r.data`, so the panel read `undefined` and showed a spurious "Not available".

| # | Action | Expected |
|---|---|---|
| B1 | In **Service Charges** (`[data-testid="service-charges-panel"]`), click **"↓ Preview freight/insurance from Customer Master"** (`[data-testid="btn-suggest-charges"]`) | suggestion panel `[data-testid="charge-suggestion-panel"]` appears |
| B2 | Read the panel header | `Advisory preview (Customer Master, USD) — read-only:` — **real currency `USD`, not `—`** (this is the exact bug that was reported) |
| B3 | Freight row `[data-testid="suggestion-row-freight"]` | shows a **real Customer Master amount** OR a specific `[data-testid="suggestion-blocked-freight"]` reason with an **Edit Customer Master** link `[data-testid="freight-authority-edit-freight"]` + **↻ Retry** `[data-testid="freight-authority-retry-freight"]` — **never a bare "Not available" with no reason** |
| B4 | Insurance row `[data-testid="suggestion-row-insurance"]` | real amount or a specific blocked reason (same rule as B3) |
| B5 | **Network:** `GET /api/v1/proforma/draft/73/suggest-service-charges` | **200**, body `{ok:true, draft_currency:"USD", freight:{...}, insurance:{...}}` |
| B6 | **Console** | no new red errors |
| B7 | **Confirm no write happened** (preview is read-only): re-query the draft; service_charges unchanged; no `draft_service_charge_added/updated` audit event fired by the preview | draft byte-identical; audit log unchanged |

> USD note: `pick_freight` reads `freight_fixed_amount_usd`. If Customer Master holds only an
> EUR value for Diamond Point B.V., B3 will now show a **real reason** ("no USD amount
> configured") instead of a false "Not available" — that is **correct** behavior and is a
> separate Customer-Master data question, not a regression.

---

## C. Provenance note — the fallback identity is visibly attributed

| # | Action | Expected |
|---|---|---|
| C1 | On a draft/type where identity resolved via the saved-draft fallback, read the source badge `[data-testid="charge-svc-source-freight"]` (or `-insurance`) | text `↳ from draft-saved service product (svc N)` with the saved service id, tooltip explaining CM has no service ID for this type |
| C2 | On a type resolved from Customer Master (CM has the id) | **no** draft-saved provenance badge (source is CM, not fallback) |

---

## D. Write / Apply path — fallback updates in place (amount from CM, saved id preserved) — DISPOSABLE TEST DRAFT ONLY

**Do NOT use Draft #73.** Create a throwaway proforma draft for a customer where CM has an
amount but **no** freight `service_id`, and the draft already carries a freight charge with a
valid saved wFirma `service_id` (the fallback precondition). Discard the draft after.

| # | Action | Expected |
|---|---|---|
| # | Action | Expected | **Result — clone Draft #75 (Diamond Point B.V., USD)** |
|---|---|---|---|
| D1 | Preview (`btn-suggest-charges`) → freight row shows amount from CM + provenance badge (fallback) | resolved via `saved_draft_fallback` | ✅ freight `28.00` svc `13002743`, insurance `362.39` svc `13102217`, both `service_id_source="saved_draft_fallback"` |
| D2 | Click **Calculate from CM / Apply Freight** | button completes | ✅ applied (via `handleCalculateFromCM` → same apply endpoint) |
| D3 | **Network:** `POST .../apply-service-charges` → `applied[0].service_id_source=="saved_draft_fallback"`, amount == CM amount | 200 | ⚠️ PROVEN VIA AUDIT — the successful 200s (events 1353/1354) came from the operator's 2nd browser tab, not this pane; route code + audit confirm `source=saved_draft_fallback`, amount from CM |
| D4 | Persisted charge: amount = CM, `wfirma_service_id` = saved id unchanged, exactly one charge/type | in-place update | ✅ freight `0→28` svc `13002743` preserved; insurance `0→362.39` svc `13102217` preserved; `resolution=calculated`; one charge/type |
| D5 | Customer Master unchanged — fallback id never written back | CM freight service_id absent | ✅ post-apply `suggest` still returns `saved_draft_fallback` → CM never written |
| D6 | **Audit:** `draft_service_charge_updated` event present | normal update audit | ✅ event `id 1353` @19:38:05Z (freight 0→28), `id 1354` @19:38:07Z (insurance 0→362.39), operator="admin" |
| D7 | Re-apply with **stale** `expected_updated_at` → **409** | no silent overwrite | ✅ 409: `updated_at='…19:38:07Z' does not match expected '…19:33:18Z' — refresh and retry` |
| D8 | `apply:["freight"]` only → insurance untouched | only-selected touched | ✅ two separate single-type events (freight-only, then insurance-only) — per-type isolation held |
| D9 | CM-resolved + already-present type → re-apply → **skipped** (idempotent) | existing charge not clobbered | ⚪ N/A on this customer (both types are fallback, neither CM-resolved) — pinned by `test_apply_service_charges_idempotent_skip` (green) |

---

## E. Malformed-data fail-safe (charge_id = 0 guard) — backend, test-substituted

Not safely reproducible by normal browser clicks (requires a corrupt persisted row). It is pinned
by `test_apply_fallback_malformed_charge_id_fails_safe` (green). Optional live confirmation on a
**disposable** draft only: strip the `charge_id` from the freight charge's
`service_charges_json`, then Apply freight.

| # | Action | Expected |
|---|---|---|
| E1 | Apply freight against the charge_id-less row | **200**; `applied == []`; `skipped` contains freight with reason "missing a valid charge_id" |
| E2 | The malformed row | **unchanged** — `update_draft_service_charge` was **never** called with `charge_id=0`; no `draft_service_charge_updated` event |

---

## F. Gateway-502 message (Fix 2: friendly product-resolver error)

| # | Action | Expected |
|---|---|---|
| F1 | With wFirma reachable, run a real product search in **Resolve product mapping** | normal found / not-found / create paths work (unaffected) |
| F2 | Force the error branch (devtools-block the search response, or search while wFirma is down) | row shows **"wFirma is temporarily unavailable (gateway error). Wait a moment, then click Resolve mapping to retry."** — **not** a wall of raw HTML |
| F3 | Click **Resolve mapping** again | retry fires (button reappears on error → second click retries) |

---

## G. GATE-6 completeness sign-off

- [x] Read path (B) — preview shows real CM currency (`USD`) + freight `28.00` / insurance `362.39`; `/suggest` 200; console clean; **no write from preview**.
- [x] Provenance (C) — fallback source badge (`↳ from draft-saved service product (svc N)`) shown for both fallback-resolved types.
- [x] Write path (D) — fallback updates in place, amount from CM, saved id preserved, CM unwritten, single charge/type, `draft_service_charge_updated` audit events, **409 on stale concurrency**, only-selected-type touched. CM-resolved idempotent skip N/A on this customer → test-covered. **(disposable clone #75; Draft #73 untouched.)** PROVEN via audit ledger — the successful applies were the operator's own 2nd browser tab (single-writer confirmed), not a separate session.
- [x] Fail-safe (E) — malformed charge_id skips safely (`test_apply_fallback_malformed_charge_id_fails_safe`, green; live confirm not run — corrupt-row not reproduced on the clone).
- [ ] 502 message (F) — **NOT run** (optional; product-resolver friendly-error path). Deferred; Fix 2 is test/plan-covered, low blast radius.
- [x] Console: no new red errors on read/write paths. Network: 409 confirmed on the concurrency path; happy-path applies 200.
- [x] Posting / conversion NOT exercised and NOT changed. wFirma untouched. Clone soft-cancelled (not purged).

**Execution path proven end-to-end (the GATE-6 bar):**
Apply button click → `POST .../apply-service-charges` (200) → draft charge updated in place in
`proforma_links.db` (amount from CM, saved id preserved) → `draft_service_charge_updated` audit
event → UI reflects the single updated charge. Read path: preview button →
`GET .../suggest-service-charges` (200) → advisory panel renders real CM values / real reason,
with the draft-saved provenance badge when identity came from the fallback.

**Record on completion:** date, operator, production SHA, and any B3/B4 USD data-reason observed
for Draft #73 (Customer-Master follow-up, not a bug).

**COMPLETION RECORD:**
- **Date:** 2026-07-28
- **Operator:** admin (session "You log in, I drive" — operator authenticated; Claude drove the browser)
- **Production SHA (content-verified):** `776d327f` — `C:\PZ\app` 4-file content == source @ 776d327f (per `reports/deploy/2026-07-28-pr1037-provenance-investigation.md`); PR #1037 branch head `d11502a4`.
- **B3/B4 USD note:** Draft #73 shows real freight `28.00` / insurance `362.39` in USD — **no** false "Not available", **no** USD-data-gap reason surfaced (CM holds usable amounts for Diamond Point B.V.). No Customer-Master follow-up needed for this customer.
- **Verification draft:** clone Draft #75 (`source_ref_id=73`), soft-cancelled after test (`draft_state=cancelled`, LOCAL-only, data preserved, no wFirma delete/purge).
- **Single-writer:** confirmed — the 19:38Z admin-attributed applies were the operator's own second browser tab (operator-confirmed), not an unattributed writer.
- **GATE-6 verdict:** ✅ PASS (D9 CM-resolved idempotent skip and E live-confirm test-substituted; F 502-message optional, deferred).
