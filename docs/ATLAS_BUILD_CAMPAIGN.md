# ATLAS_BUILD_CAMPAIGN.md — Phases 2–12, end-to-end build plan

**Status:** Draft for operator lock
**Date:** 2026-06-01
**Controlling spec:** `docs/ATLAS_WORKFLOW_MAP.md` (the spine, PR #417). Every phase executes against the spine and its WF1–WF4 / §1A / §1B model.
**Phase 1 (process authority)** is done — this campaign is Phases 2–12.

---

## Campaign invariants (apply to EVERY phase, no exceptions)

1. **All wFirma write flags stay OFF for the entire campaign** — `WFIRMA_CREATE_PRODUCT_ALLOWED`, `WFIRMA_CREATE_PZ_ALLOWED`, `WFIRMA_CREATE_PROFORMA_ALLOWED`, `WFIRMA_CREATE_INVOICE_ALLOWED`, and `live_enabled`. No live wFirma or email writes; dev uses the mock client. **Flag enablement happens only at Phase 12, one-by-one, by the operator — never by the agent.**
2. **Soft applies to workflow gates only.** Irreversible writes stay flag-hard. (This is the line that makes "no hard blocks" safe.)
3. **Investigation before implementation.** Every phase starts read-only (INSPECTOR), produces a short plan, then implements. Never fire an implementation before discovery is complete.
4. **Evidence-producing gates.** Never claim "passes / renders / clean" without attached proof — test output, diff, or rendered compare.
5. **PR per phase (or per coherent slice). GATE-2: ≤3 open PRs at once.** At the cap, STOP until merges free a slot.
6. **Migrations are additive + atomic writer/reader.** Existing data preserved and reconciled; no destructive ops.
7. **V1-frozen files never edited:** `dashboard.html`, `shipment-detail.html`. New pages build on `pz-design-v2`.
8. **No merge, no deploy, no C:\PZ mutation inside the campaign.** Those are operator actions outside the run.
9. **Single session only.** No second Claude Code session on the tree while the campaign runs.

---

## Risk tiers

| Tier | Meaning |
|---|---|
| **LOW** | Docs, additive read-only surfaces |
| **MED** | Behaviour change behind a flag; new read paths |
| **HIGH** | Schema migration; wFirma write paths (even flag-off); UI wiring; anything touching guards, money, or customs values |

---

## Dependency-ordered sequence

```
2 → 10(operator backfill) → 4 → 3 → 5 → 8 → 7 → 6 → 9 → 11 → 12
```

---

## Phase 2 — Soften the three hard-stops · **MED** · *unblocks the 25 + enables end-to-end testing*

**Objective:** convert HS-1 (DHL email + SAD/MRN), HS-2 (product-sync before proforma post), HS-3 (PZ-before-proforma) from HTTP-422/400 hard blocks into **advisory + inbox** signals, behind an advisory-mode flag. Keep the 4 write flags hard.

**Touches (confirm in INSPECTOR):** `guards.py` (`guard_pz_requires_sad`, `guard_dhl_requires_email`); `routes_proforma.py` (`_check_proforma_export_prerequisites`, `missing_products`); `routes_dhl_clearance.py`.

**Evidence:** tests showing each gate now warns + emits an inbox advisory instead of raising; 381 carrier baseline still green; demo that a batch with no SAD can proceed through description → PZ generation with no wFirma write.

**PR:** 1. Stop-and-report.

---

## Phase 10 — Master-data backfill · **OPERATOR task, not agent code**

**Objective:** populate `company_profile` (consignee) FIRST, then verify supplier / client / HS / product authority rows. Lock the conflict rule (master wins; parsed doc → proposal). `company_profile` being empty is today's blocker for consignee identity (PR #416).

**Agent's only job:** provide a backfill checklist + a read-only before/after row count. The data entry itself is operator work via the Masters UI.

**Evidence:** read-only counts before vs after.

---

## Phase 4 — Product master authority, composite key · **HIGH** · *foundation for 5/6/8*

**Objective:** make `product_master` the enforced authority. Composite identity = `supplier_id + supplier_product_code + normalized_design_attributes`. Every parsed line resolves to exactly one row; 417G kept (separate rows per supplier); same supplier+code ambiguous → inbox disambiguation proposal. Close GAP 17 — logical/SQL links from `inventory_state` + `editable_lines_json` lines to `product_master`. Preserve supplier-specific parsing rules.

**Touches:** `product_master` (reservation_queue.db), `design_product_mapping`, line storage in `document_db`, `build_product_code`, an additive migration.

**Evidence:** migration additive; reader/writer parity test; 57 existing rows preserved + reconciled; resolution test incl. a 417G cross-supplier case.

**PR:** 1 (schema + resolver). **HIGH → explicit operator go required before starting.**

---

## Phase 3 — detect→inbox→approve via the AI Reverification Layer · **HIGH** · *the big new subsystem*

**Objective:** on parse, the AI reverification layer (map §1A) re-checks parsed data against the source doc + masters + paired lines and emits the §7 inbox proposal types. Read-only / proposal-only — never writes masters or wFirma, never auto-approves.

**Touches:** new reverification service; `action_proposals` infra extended to accept parse-sourced proposals; inbox read path.

**Evidence:** proposals created from a real parsed batch (mock wFirma); operator approve/hold/override tested; zero master/wFirma writes from the layer.

**PR:** likely 2 (proposal infra; AI checks). **HIGH.**

---

## Phase 5 — Dual-valuation resolver · **MED**

**Objective:** one backend resolver — purchase value → customs/SAD/PZ cost basis; sales value → warehouse/sales value. UI shows both (map §6).

**Evidence:** resolver unit tests on a real batch; both values surfaced in the UI.

**PR:** 1.

---

## Phase 8 — Sales↔purchase line matching → proposal · **MED**

**Objective:** match sales lines to purchase by `product_code`; a mismatch creates an inbox proposal with the exact reason (approve / correct / split) instead of silently blocking the proforma.

**Evidence:** mismatch case → proposal with reason; no silent block.

**PR:** 1.

---

## Phase 7 — DHL→inventory lifecycle · **MED**

**Objective:** DHL in-transit → WF4.1 IN_TRANSIT auto; DHL delivered → "confirm received" inbox proposal → operator confirms person/date/location → WF4.3 RECEIVED; scan → final/dispatch. "Received" is soft (not a posting precondition).

**Touches:** DHL webhook/monitor → `inventory_state_engine.transition`; inbox proposal.

**Evidence:** delivered event raises proposal; confirm transitions state; no auto-transition without operator confirm.

**PR:** 1.

---

## Phase 6 — wFirma product registration at intake · **HIGH** · *wFirma write path*

**Objective:** after parse + approval, a "register product to wFirma" proposal appears in the inbox; operator approves; product pushed ONLY if `WFIRMA_CREATE_PRODUCT_ALLOWED` is on (stays off during the build; mock in dev). Makes PZ instant later.

**Evidence:** proposal → approve → mock create called; flag-off path blocks the write; no live write.

**PR:** 1. **HIGH.**

---

## Phase 9 — Proforma/invoice closure + payload-disclosure modal · **HIGH** · *wFirma writes*

**Objective:** draft always creatable; post requires customer mapped + products resolved + advisory warnings reviewed + flag on; convert→invoice requires a payload-disclosure modal (shows exactly what will be written to wFirma) + explicit operator confirm. Behind `CREATE_PROFORMA` / `CREATE_INVOICE` flags (off during build).

**Evidence:** post/convert gated; payload-disclosure shows the exact wFirma payload; mock-only.

**PR:** 1. **HIGH.**

---

## Phase 11 — UI wiring (redesign → backend) · **HIGH, large**

**Objective:** wire the redesigned dashboard to the backend per WF ownership:

| Surface | Owns |
|---|---|
| Dashboard | Visual-only (no business logic) |
| Shipment Detail | WF1 |
| Proforma | WF2 |
| Reservation | WF3 |
| Inventory | WF4 |
| Inbox | Approve / hold / override |

Replace prototype `notify()`/`simulate` stubs with real endpoints; every state-changing button references exactly one WF id (map §2). Build on `pz-design-v2`; never edit the two frozen files.

**Note:** large — sub-split into per-screen PRs (Shipment Detail, Inbox, Proforma, Inventory, Masters).

**Evidence:** per screen — buttons hit real endpoints; rendered compare; zero frozen-file diff.

**PR:** multiple (one per screen). **HIGH.**

---

## Phase 12 — Verification + staged enablement

**Objective:** run one full SAFE shipment path with NO live writes (mock); run one gated write path in test/staging ONLY; produce the §9 truth table:

```
transition | button | endpoint | gate | inbox proposal | output document | status
```

**THEN — operator, not agent** — enable the production write flags one-by-one, watching the attachment guard and the truth table after each.

**Evidence:** the completed truth table; the safe-path run log.

**PR:** the truth table is a docs PR. **Flag enablement is NOT a PR — it is a gated operator action, one-by-one, outside the campaign run.**

---

## Hard stop conditions

The runner **waits for explicit operator authorization** at:

| Condition | When |
|---|---|
| Any **HIGH**-risk phase (4, 3, 6, 9, 11) | Before starting |
| **GATE-2 cap** (3 open PRs) | Until merges free a slot |
| Any **failed evidence gate** or discovered blocker | Immediately |
| **Phase 12 flag enablement** | Each flag, one-by-one |

**The runner NEVER flips a flag or `live_enabled`, NEVER merges, NEVER touches `C:\PZ`, and NEVER does a live wFirma/email write — in any phase.**