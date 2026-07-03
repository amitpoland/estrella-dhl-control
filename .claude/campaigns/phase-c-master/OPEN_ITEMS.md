# Phase-C Inventory Master — Open Items Ledger (OPEN_ITEMS.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

OI = an item requiring operator input (wFirma account facts, business decisions) that
gates campaign slices. Constitution §19: never guess a wFirma capability. States:
**OPEN** / **ANSWERED** (with citation) / **INVALIDATED** (assumption behind it collapsed).
Numbering follows the integration audit's consolidated OPERATOR-INPUT list
(`reports/inspection/2026-07-03T-integration-architecture-audit.md` §Consolidated), which
extends the §E checklist (`2026-07-03T-wfirma-section-e-operator-checklist.md`).

---

## Category A — Blocks the consignment build (highest priority)

**OI-1 — MM via API** (audit #1; OQ-WFIRMA-MM-ANSWER)
Question: does wFirma expose przesunięcie międzymagazynowe (inter-warehouse transfer)
via API, and under what module/endpoint?
State: **OPEN** (business model ANSWERED 2026-07-03: MM = internal transfer, not WZ;
API vehicle still unconfirmed — MM absent from client registry, python-wfirma type list,
and all four wFirma docs)
Gates: W3-A5 (C-4b — fallback exists: operator-UI MM + Atlas reconcile), W4-A3 (C-7a)
Fallback if NO: consignment MM manual in wFirma UI + Atlas reconcile; or RW+PW pair
(needs accounting sign-off). C-7a becomes documentation-only.

**OI-2 — Consignment warehouse** (audit #2)
Question: does a second (Consignment) warehouse exist in wFirma, or must it be created?
Is all stock in one warehouse today? (`list_warehouses()` already enumerates.)
State: **OPEN** · Gates: C-4b (Wave 3)

**OI-3 — WZ add via API vs invoice-auto-WZ** (audit #3)
Question: one sandbox probe — does an invoice against a warehouse auto-emit the WZ, or is
a standalone `warehouse_document_w_z/add` needed? (2023 forum claims auto-only; production
disproved the same claim for PZ — docs stale, probe required.)
State: **OPEN** · Gates: C-6a (Wave 3), C-8c (Wave 4)

**OI-4 — get_stock enablement** (audit #4)
Question: goods/get grant for count/reserved read (double-stock-out verification)?
Stub at wfirma_client.py:1161 (NotImplementedError).
State: **OPEN** · Gates: C-9a (Wave 4)

**OI-5 — Sandbox / test company** (audit #5)
Question: is there a sandbox for MM/WZ write trials before prod?
State: **OPEN** · Gates: C-4b/C-6a probe safety (Wave 3)

**OI-6 — PZ delete/reversal** (audit #6)
Question: does `warehouse_document_p_z/delete/{id}` exist? (Repo has no delete path + a
CI test that fails if one is added.)
State: **OPEN** · Gates: none in Waves 1–4 (correction-lifecycle adjacent)

## Category B — Account config the sync depends on

**OI-7 — WFIRMA_WEBHOOK_KEY** set in NSSM prod env? (empty → invoice webhooks silently
503-rejected.) State: **OPEN** · Gates: W4-A1

**OI-8 — WFIRMA_CREATE_PZ_ALLOWED** current prod value? (false → PZ creates error before
wFirma.) State: **OPEN** — note: memory records a standing all-ON wFirma flag posture;
verify against prod env at Wave-4 boundary, do not assume. Gates: none directly (PZ live-proven)

**OI-9 — Invoice webhooks** — which Faktury.* events registered; URL →
POST /api/v1/webhooks/wfirma on prod? State: **OPEN** · Gates: W4-A1

**OI-10 — Goods webhooks (Towary.*)** registered? (No handler exists — would dead-letter.)
State: **OPEN** · Gates: W4-A1 (C-8a)

**OI-11 — Contractor webhooks (Kontrahenci.*)** registered? (Only indirect sync today.)
State: **OPEN** · Gates: W4-A1 (C-8b)

**OI-12 — Warehouse (Magazyn) module** active? (Determines goods count/reserved
population + PZ add availability.) State: **OPEN** · Gates: Wave 4 checks

## Category C — Mirror-consolidation design inputs

**OI-13 — contractor_id stability** in ALL wFirma responses (contractors, webhook
payloads, invoice contractor blocks)? Required to key the canonical customer mirror by
contractor_id instead of client_name.
State: **OPEN** · Gates: W1-A3 (C-2a keying — Wave 1). Note: memory records this as
wFirma-email item #2; if unanswered when C-2a starts, C-2a proceeds with contractor_id
keying + a defensive uniqueness check, per Phase-0 evidence pass.

**OI-14 — /magazines endpoint** in the API plan, or warehouse_id = config constant?
Decides whether wfirma_warehouse_mirror (net-new) is needed.
State: **OPEN** · Gates: C-4b (Wave 3)

**OI-15 — Contractor API fields** — does /contractors return default_currency +
per-contractor series IDs, or are series account-level? Decides which customer_master
columns auto-fill vs stay operator-only.
State: **OPEN** · Gates: C-2b detail (Wave 1, non-blocking — COALESCE fill-when-empty
semantics already protect operator fields)

## Category D — Design Number custom field (Constitution §4/§5; advisor item #3)

**OI-16 — Design Number custom field** — (a) created in wFirma? (b) API name?
(c) does the goods API return custom fields?
State: **OPEN** · Gates: Design-Number custom-field sync (NEW scope, explicitly gated
beyond C-1d per advisor reconciliation; wFirma email item #3, after MM (#1) and
contractor_id (#2)). Constitution §19 applies.

## Category E — Operator business decisions

**OI-17 — Consignment allocation model** (OI-CONSIGNMENT-MODEL)
Question: is consignment tracked as an inventory STATE (custody sub-state) or as a
WAREHOUSE/LOCATION dimension?
State: **OPEN** — operator decision · Gates: W3-A3 (C-4a, Wave 3)
Context: wireframe inspection §C3 "model decision for the operator"; ledger columns
Cons.ID/Client/Design/Qty/Value/Issued/Due Back/Days Out/Proforma.

**OI-18 — C-1e ruling** (routes_wfirma reads+writes migration)
Question: PROJECT_STATE marks C-1e "ADDED RESIDUAL (DEVIATION, needs ruling)" — confirm
scope before the slice starts.
State: **ANSWERED** (operator verdict 2026-07-03, Ruling 1 = Option (a)): C-1e proceeds
as its own slice, C-1w1/C-1w2 pattern — mirror-first transitional dual-write ×3,
Master/passthrough reads ×5, pin 2 → 1. Sequence: C-1e → Mirror Completeness Proof
(grep evidence) → C-1f (output-equivalence) → C-1d audit. Citation: DECISIONS.md
"OPERATOR VERDICT: six rulings" entry.
