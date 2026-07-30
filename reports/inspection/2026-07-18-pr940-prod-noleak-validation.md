# PR #940 — Production carrier-row no-leak validation (task_b76ee829)

**Date:** 2026-07-18 · **Deployed SHA validated:** `4676057280e99e7c6774164b8c3a5bf9ecce1933`
**Result: ✅ PASS — no cross-client AWB/service/dimension leak on any production draft.**

> ⚠️ **LOCAL / SANITIZE BEFORE ANY PUBLIC PUSH.** Contains production batch IDs and DHL AWB
> numbers. Client names are anonymized (C01…); the name↔code map is NOT stored in the repo
> (kept only in the local validation run). Per `feedback-sanitize-pii-before-public-push`.

## Method (zero production writes — proven)
Production DBs were opened `mode=ro` and copied via the SQLite **backup API** into a temp dir; the
additive `client_ref` migration (`shipment_db.init_db`) and every resolver call ran **only against the
temp copies**. The resolver functions are the **real deployed code** imported from `C:\PZ-main\service`
(byte-identical to `C:\PZ\app` at `4676057`): `get_shipment_for_draft`, `get_shipment_by_batch_id`,
`get_legacy_shipment`, `list_drafts_for_batch`.

**Non-mutation proof:** after the run, `C:\PZ\storage\carrier\carrier_shipments.db` still has **no
`client_ref` column**, **23 rows**, mtime `Wed Jul 15 06:01:49 2026` (pre-session). Production was
read-only throughout. No AWB created, no `POST /shipment`, no DHL/wFirma call, no service restart.

## Config resolved
`ENVIRONMENT=prod`, `STORAGE_ROOT=C:/PZ/storage`, **no `CARRIER_STORAGE_ROOT`** →
active carrier DB = `C:\PZ\storage\carrier\carrier_shipments.db` (the single carrier_shipments.db on
disk — no stale second file; the `_carrier_shipment_db_path` "previously-invisible rows" concern is
resolved: one correctly-resolved file). GET route `routes_carrier_actions.py:457` =
`init_db → get_shipment_for_draft(..., allow_single_client_fallback=_batch_not_multi_client(batch))`.

## Per-batch result (4 real multi-client batches with carrier rows + 1 control)

| Batch | Clients | Carrier rows | Fallback gate | Every-draft resolution | OLD batch-latest path **would** have leaked |
|---|---|---|---|---|---|
| `SHIPMENT_1003835895_2026-07_523c9281` | 6 | 3 | DENY (multi) | all → honest-missing (None) | AWB `7924336254` → all 6 |
| `SHIPMENT_6769309142_2026-06_b2016b29` | 10 | 9 | DENY (multi) | all → honest-missing (None) | AWB `4839461152` (do_not_use) → all 10 |
| `SHIPMENT_8341809162_2026-07_3d940f75` | 3 | 2 | DENY (multi) | all → honest-missing (None) | AWB `3281094692` → all 3 |
| `SHIPMENT_9158478722_2026-06_924c4e59` | 10 | 7 (all shadow/pending) | DENY (multi) | all → honest-missing (None) | no live AWB present (no leak either way; resolver correct) |
| `SHIPMENT_9807058483_2026-06_c600949a` (control) | 1 | 2 | ALLOW (single) | honest-missing (None) | fallback needs EXACTLY 1 row; 2 present → conservatively None |

## Acceptance criteria
1. **Real production multi-client batch verified** — ✅ 4 batches (3–10 clients each).
2. **Each draft resolves only its own carrier shipment** — ✅ every draft resolves its own row or
   honest-missing; **zero** drafts resolve another client's row.
3. **No legacy fallback leaks another client's AWB/service/dimensions** — ✅ multi-client → fallback
   denied → honest-missing; the OLD batch-latest path is shown to have leaked (fix changed behavior).
4. **Legacy-rebook confirmation behaves correctly** — ✅ `get_legacy_shipment` returns a row for every
   batch → the modal confirmation gate fires on rebook; combined with the review-env proof at this exact
   SHA where confirm → **Cancel** = zero `POST /shipment` + carrier DB byte-identical + no DHL egress
   (production runs byte-identical code, so the gate behavior is identical).
5. **Evidence recorded** — this file (batch IDs, client counts, AWB IDs; drafts by client).
6. **Result: PASS.**

## Honest scope note (important for UAT)
All existing production carrier rows **predate `client_ref`** (legacy/NULL — the column ships with #940
and is added on the first post-deploy carrier route call). So the fix currently manifests as
**honest-missing** for multi-client drafts, not "each draft shows its own AWB": drafts in
already-booked multi-client batches that PREVIOUSLY displayed a (leaked, wrong) AWB will now correctly
display **no AWB** until a client-scoped booking exists. The positive resolution ("draft shows its own
client-scoped AWB") applies to **new** post-deploy bookings (which carry `client_ref`) and is covered by
the route/unit tests + review-env browser verification — it is not present in today's production data.
The critical **safety** property (no cross-client leak) is fully proven on real production data above.
