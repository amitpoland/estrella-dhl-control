# Phase-C Wave 4 (Synchronization) — Unblock Package

**Date:** 2026-07-04 · **Type:** research/inspection only — NO implementation, NO Wave-4 start, Waves 1–3 not reopened.
**Sources audited:** `MASTER_MANIFEST.md` §2 Wave 4 · `OPEN_ITEMS.md` (OI-1..OI-17) · `PROJECT_STATE.md` (Wave-2 COMPLETE) · `.claude/skills/ej-dashboard-master/ACTIVE_CAMPAIGNS.md` (synced) · existing wFirma code (`wfirma_client.py`, `routes_webhooks_wfirma.py`, `wfirma_enrichment_processor.py`). No wFirma API behavior invented; undocumented capability = WFIRMA-GATED.

## OI table (Wave-4-gating)

| OI | Question | Why it blocks Wave 4 | Affected slice | Evidence in repo | Evidence needed (operator / wFirma docs) | Recommended ruling | Safe fallback if unanswered |
|---|---|---|---|---|---|---|---|
| OI-1 | Does wFirma expose inter-warehouse transfer (MM / przesunięcie) via API? | MM is the vehicle for MAIN→CONSIGNMENT + return legs | C-4b, C-7a | **Absent** — no `warehouse_document_m_m` / `przesun*` in `wfirma_client.py` type registry (PZ/WZ present, MM not); OPEN_ITEMS: "absent from client registry, python-wfirma type list, all four wFirma docs" | wFirma docs confirmation MM endpoint exists (currently undocumented) | **WFIRMA-GATED** — treat as NO absent proof | Operator-UI MM in wFirma + Atlas reconcile; C-7a becomes documentation-only |
| OI-2 | Does a Consignment warehouse exist, or must it be created? | C-4b needs a target warehouse id | C-4b | `list_warehouses()` exists (`wfirma_client.py:536`) — enumerates live | Run `list_warehouses()` on prod, or operator states | **OPERATOR-GATED** — enumerate, don't assume | Create Consignment warehouse in wFirma UI first |
| OI-3 | Invoice auto-emits WZ, or standalone `warehouse_document_w_z/add` needed? | C-6a closes SALES_TRANSIT via WZ | C-6a, C-8c | WZ in type list (`:39`); **no add path** (only PZ has add/fetch/find). PZ-precedent: 2023 forum "auto-only" was disproved for PZ → docs stale | One sandbox probe (needs OI-5) | **WFIRMA-GATED** until probe | Assume standalone-add needed; gate write behind probe |
| OI-4 | `goods/get` grant for count/reserved (double-stock-out read)? | C-9a verification read | C-9a | Stub `get_stock()` raises `NotImplementedError` (`wfirma_client.py:1161`) | wFirma account grant / capability | **WFIRMA-GATED** | Skip get_stock read; rely on Atlas inventory_state (no wFirma cross-check) |
| OI-5 | Sandbox / test company for MM/WZ write trials? | Probe safety for OI-1/OI-3 | C-4b, C-6a | — | Operator account fact | **OPERATOR-GATED** | No live write trials; documentation-only until sandbox |
| OI-7 | `WFIRMA_WEBHOOK_KEY` set in NSSM prod env? | Empty → invoice webhooks silently 503 | C-8a/b/c (W4-A1) | Handler checks key (`routes_webhooks_wfirma.py:10,47`) | Read prod NSSM env (operator/read-only) | **OPERATOR-GATED** — verify prod env | Poll-based sync (existing Phase-3B) |
| OI-9 | Which `Faktury.*` events registered; URL → prod webhook? | Confirms invoice sync live | C-6a linkage | Handler exists — `Faktury.Dodanie` processed (`wfirma_enrichment_processor.py:30`) | Operator confirms wFirma webhook config | **OPERATOR-GATED** | Keep invoice poll |
| OI-10 | `Towary.*` (goods) webhooks registered? | No handler → dead-letter | C-8a | **No goods handler** in repo | Operator confirms registration | **BLOCKED BY OI** (+ handler is new build) | Keep goods poll; do not register until handler ships |
| OI-11 | `Kontrahenci.*` (contractor) webhooks registered? | No handler → dead-letter | C-8b | **No contractor handler**; indirect sync only | Operator confirms registration | **OPERATOR-GATED** (fallback is explicit) | Keep Phase-3B contractor poll |
| OI-17 | Consignment = inventory STATE or WAREHOUSE/LOCATION dimension? | Data model for the whole consignment leg | C-4b, C-5a | Wireframe §C3 "model decision for the operator"; ledger cols defined | Operator design decision | **OPERATOR-GATED** — operator decision, no wFirma dependency | None — hard prerequisite for C-4b/C-5a |

Adjacent (not Wave-4-blocking, noted): OI-2/OI-14 warehouse mirror (`list_warehouses()` covers read); OI-12 Magazyn module active (affects counts); OI-6 PZ delete (correction-lifecycle, not Wave 4). OI-18 ANSWERED.

## Wave 4 slice classification

| Slice | Class | Gate |
|---|---|---|
| C-4b Consignment issue MAIN→CONSIGNMENT | **BLOCKED BY OI** | OI-17 (model) + OI-2 (warehouse) + OI-1/OI-5 (MM write); fallback = operator-UI MM makes it OPERATOR-GATED once OI-17/OI-2 answered |
| C-4d Return Consignment→Main | **BLOCKED BY OI** | downstream of C-4b |
| C-5a Invoice-from-consignment | **BLOCKED BY OI** | OI-17 + OI-2 |
| C-6a WZ verification / SALES_TRANSIT close | **BLOCKED BY OI** | OI-3 (needs OI-5 probe) |
| C-7a MM integration via API | **NOT IMPLEMENTABLE FROM CURRENT EVIDENCE** | OI-1 MM API undocumented → documentation-only fallback until proven |
| C-8a Goods webhook handler (Towary.*) | **BLOCKED BY OI** | OI-10 registration + new handler build |
| C-8b Contractor webhook handler (Kontrahenci.*) | **OPERATOR-GATED** | OI-11 — explicit fallback "keep Phase-3B poll" |
| C-8c WZ webhook / standalone add | **BLOCKED BY OI** | OI-3 |
| C-9a get_stock enablement | **NOT IMPLEMENTABLE FROM CURRENT EVIDENCE** | OI-4 grant (WFIRMA-GATED) |

**READY: none.** No Wave-4 slice is implementable from current evidence.

## 1. Minimal operator questions to unblock Wave 4

1. **OI-17** — Consignment = inventory STATE or WAREHOUSE dimension? (pure business decision; no wFirma dep; unblocks C-4b/C-5a data model)
2. **OI-2** — Does a Consignment warehouse exist in wFirma? (or authorize me to enumerate via `list_warehouses()` against prod)
3. **OI-1** — Is there a wFirma MM (inter-warehouse) API endpoint? If unknown, ratify the **fallback** (operator-UI MM + Atlas reconcile) as permanent.
4. **OI-5** — Is there a wFirma sandbox for MM/WZ write probes? (gates OI-3 resolution)
5. **OI-7 + OI-9/10/11** — On prod: is `WFIRMA_WEBHOOK_KEY` set, and which `Faktury.*/Towary.*/Kontrahenci.*` events are registered? (or authorize read-only prod-env + wFirma webhook-config inspection)
6. **OI-4** — Is the `goods/get` grant available for stock read? If not, ratify skipping the double-stock-out cross-check.

## 2. Recommended execution order (after answers)

1. **Deploy Wave 3 to production first** (see §3).
2. OI-17 + OI-2 answered → **C-4b** (consignment model + warehouse target; MM via fallback if OI-1 negative) → **C-4d** → **C-5a**.
3. OI-5 sandbox → probe OI-3 → **C-6a** → **C-8c**.
4. OI-1 ruling → **C-7a** (API if proven, else documentation-only permanent).
5. OI-7/9 confirmed → **C-8b** (keep-poll unless registered) → OI-10 → build + **C-8a**.
6. OI-4 grant → **C-9a** (else skip, documented).

## 3. Should Wave 3 deploy before Wave 4? — **YES**

Wave-4 assumption **W4-A3** requires "Waves 2–3 deployed so the sync legs have surfaces to land on." Wave 3 is COMPLETE on `deploy/latest`, unshipped. Deploying it first (operator-gated 7-agent gate, CP4/CP5) is lower blast radius (UI-only), lands the consignment/inventory surfaces C-4b/C-5a/C-9a will wire into, and satisfies W4-A3 — so Wave 3 production deploy should precede any Wave-4 slice.
