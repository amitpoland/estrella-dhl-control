# BE-2b — receipt-path promotions produce Stock Promotion Notes: build + test record

- **Date:** 2026-07-03 · backend only, zero UI · no deploy · commits
  authorized by the BE-2b build instruction (STEP 5)

## STEP 0 — site verification at HEAD (per the build instruction)

The PURCHASE_TRANSIT→WAREHOUSE_STOCK writer set outside run_stock_promotion:
1. **`dhl_delivery_bridge.execute_goods_received`** — the ONE production
   receipt path. The prior scoping's "DHL bridge" and "direct
   physical-receipt confirm" are the SAME function (the delivered→confirm
   proposal's executor). Per-piece via packing lines post-conversion; batch,
   operator, goods-received evidence, and trigger all in scope. CONVERTED.
2. **DIVERGENCE — STOPPED, not edited** (per the instruction's STOP clause):
   `routes_packing.py:3237 dev_seed_inventory_state`
   (`POST /inventory-state/seed-batch`, dev_router, hard-gated
   `settings.environment != "dev"` → 404) promotes PT→WS through a VARIABLE
   target (`to_state=next_state`, chain planner :3303-3310) — invisible to
   literal greps and to the original boundary pin. Dev-only legacy-batch
   backfill/repair with dry_run semantics; conversion is non-trivial
   (dry_run has no shared-function equivalent) and whether legacy backfills
   should mint Notes is a business question. HELD for operator ruling:
   (a) exempt-as-repair-tool with recorded boundary, or (b) convert with
   trigger="legacy_backfill". Until ruled, a NEW PIN
   (`test_dev_seed_backfill_variable_promotion_stays_dev_gated`) fires if
   the dev gate is removed.

Trigger naming: kept `"warehouse_receive"` (the instruction's
"receipt_confirmed"/"dhl_delivered" were examples) — continuity with the
trigger this path has always written to inventory_state_events; the origin
is named distinctly vs pz_created/pz_generated, and
source="dhl_delivery_bridge" disambiguates further.

The operator-ratified GOVERNANCE rule (authority-first, business principle,
Phase A/B/C roadmap incl. the Phase-B Move-Location-folding note requiring
its own approval) is recorded verbatim in PROJECT_STATE DECISIONS
"GOVERNANCE: authority-first rule".
- **Operator GO (verbatim):** "BE-2b. Reason: it closes the business rule
  first: Every stock movement must produce a document. UI parity should come
  after, so the page can show complete backend truth, not a partial document
  trail."
- **Declared:** PROJECT_STATE DECISIONS "BE-2b" (before any edit), alongside
  the two side answers: wFirma MM = business model settled (MM Main→
  Consignment, never WZ; API capability STILL open — §E checklist item), and
  the backup task re-confirmed pending (blocks risky cleanup).

## What changed

1. **`dhl_delivery_bridge.execute_goods_received`** — the LAST
   `PURCHASE_TRANSIT → WAREHOUSE_STOCK` writer outside the shared authority
   (repo-wide grep: only the bridge and stock_promotion.py wrote that edge;
   sample/producer RETURNS to stock are a different edge). Its direct
   SELECT + per-row `ise.transition` loop is replaced by ONE
   `run_stock_promotion(batch_id, trigger="warehouse_receive",
   source="dhl_delivery_bridge", operator, note=goods_received-evidence)`
   call. The receipt path thereby gains the idempotent skip, audit mirrors,
   and the Stock Promotion Note. Return contract: `transitioned` = promoted
   count (unchanged semantics), `errors` list (aggregated string — disclosed
   delta, shape pinned), plus additive `note_no` and `skipped`.
2. **`stock_promotion.py`** — `note_failed: True` on Note-write failure
   (programmatic signal; state truth stands) + docstring documents the INT
   counters.
3. **Boundary comments in-code** at both returns writers'
   WAREHOUSE_STOCK transitions (`inventory_returns_writer.py`,
   `inventory_sample_writer.py`): returns to stock are NOT promotions — no
   Note by design; a new transition there must justify itself against the
   BE-2b boundary.
4. **`tests/test_stock_promotion_be2b.py`** (10 tests): receipt→Note with
   full evidence round-trip (trigger/source/operator/reason/before-after);
   both orderings yield exactly ONE Note; replay distinguishable from empty
   batch (skipped signal); partial-failure shape pinned; Note-failure
   surfaces in errors[]; ValueError + missing-warehouse.db contracts
   unchanged; source pins (no direct engine call in the bridge; the
   WAREHOUSE_STOCK writer set is exactly {stock_promotion, sample_writer,
   returns_writer} with the latter two excluded by design).

## Disclosures

- The Inbox dispatcher for the delivered→confirm proposal is NOT wired in
  production (pre-existing; grep shows no app-side caller of
  execute_goods_received) — BE-2b makes the path Note-complete for when it
  wires; the wiring slice must handle the replay signal and the additive
  note_no key deliberately.
- The bridge now depends on packing_db initialisation (service startup does
  this; the shared function derives pieces from packing lines).

## Adversarial verify (2-lens workflow wf_82058fae-16d)

Lens-2 (Note doctrine/boundary): refuted=false. Lens-1
(behavior-equivalence): refuted=true — traced entirely to the disclosed
error-format delta (no production parser); its piece-set-divergence attack
found nothing. Four hardenings applied pre-commit (note_failed signal,
skipped/replay distinction, partial-failure pin, boundary comments) — all
described in the DECISIONS VERIFY PASS paragraph. Residuals accepted:
errors-as-int at the stock_promotion level (documented), note_no additive.

## Gates (at record time)

```
BE-2b 11/11 (incl. the STEP-0 dev-gate pin) · BE-2 Note suite 10/10
(note_failed pin added) · BE-1 12/12 · pre-existing promotion pins 9/9 ·
bridge suites (phase7 + remediation_b4) green · sample/returns writer
suites green — combined run: 96 passed
PYTHONUTF8=1 python test_pz_regression.py — 160/160 golden PASS
```

## Phase A status

Backend movement authority COMPLETE for all PRODUCTION paths — every
production PT→WS promotion flows through run_stock_promotion and yields
exactly one Note. One dev-only site (dev_seed_inventory_state, 404 in prod,
gate pinned) is held for the operator's legacy-backfill ruling; it does not
block the Phase-A freeze for production behavior.
