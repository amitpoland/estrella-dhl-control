# MIGRATION_ROADMAP.md — Estrella PZ Platform

**Campaign:** EJ PLATFORM CONSOLIDATION DISCOVERY
**Inspected:** `origin/main @ fb70e15` (read-only)
**Date:** 2026-06-18
**Companion docs:** [AUTHORITY_MAP.md](./AUTHORITY_MAP.md) · [V1_V2_CAPABILITY_MATRIX.md](./V1_V2_CAPABILITY_MATRIX.md) · [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md)

> Decisions are grounded in code + campaign docs at HEAD. Each cites support. Ambiguity → **GAP:** + a verification step, not a guess. Decision verbs: **KEEP V1 / KEEP V2 / MERGE / REBUILD / RETIRE.**

---

## 0. Headline decision: **V2-FIRST** (already decided and largely executed)

This is not a fresh recommendation — it is the trajectory the repo has already committed to and substantially delivered:

1. **V1 is frozen.** `CLAUDE.md` Lesson F + `docs/v2-architecture-plan.md §0` + `.claude/campaigns/atlas-v2.md §1`: `dashboard.html` (20,332 ln) and `shipment-detail.html` (16,214 ln) accept **critical fixes only**. Adding to V1 is prohibited.
2. **The V2 shell is functionally complete for reads.** `WIRED_PAGES = 17/17 (100%)` (`PROJECT_STATE.md`; `v2/mock-badge.jsx:48-52`) — the MOCK-elimination campaign (Atlas-V2 sprint program) finished; banner retired.
3. **The backend is the stable layer** — `docs/v2-architecture-plan.md §0`: "do not rewrite." Migration is a frontend exercise; the API serves all surfaces unchanged.
4. **ADR-029 (Accepted)** resolves the one architectural exception (Proforma Workspace orchestration shell), so V2 can coordinate multi-domain workflows without re-implementing domain logic.

**Rejected alternatives:** *V1-FIRST* — prohibited by Lesson F. *HYBRID* — that is today's transient state (4 surfaces), doubling maintenance; it is the problem, not the target. *FULL CONSOLIDATION into one shell now* — valid future state but blocked by ADR-028 (Track-1/Track-2 isolation) until the Track-1 shared layers are retired/ported; out of near-term scope.

**What V2-FIRST means operationally:** new capability lands in the `/v2/` shell or a Track-1 V2 page — never in `dashboard.html`/`shipment-detail.html`; V1 files are archived (not deleted) only after V2 equivalents are operator-verified; the three remaining MOCK shell pages are the immediate backlog; the **duplicate V2 surfaces (Track-1 vs Track-2, forked JS libs) must be unified** — the consolidation is as much *within* V2 as away from V1.

---

## 1. Module-by-module verdicts

| # | Module | Verdict | Rationale (cited) |
|---|---|---|---|
| 1 | Shipments | **KEEP V2** | T2 `dashboard-page.jsx` wired (Sprint 32); V1 frozen. `shipment-detail-v3.html` disposition unknown (**GAP/OQ-2**). |
| 2 | Dashboard | **KEEP V2** | T2 wired; V1 frozen; Sprint-13 aggregator superseded by shell. 3 MOCK pages remain (`PROJECT_STATE.md`). |
| 3 | Inventory (read) | **KEEP V2** | Sprint 30 wired live; write engine stays backend-gated (`inventory_state_engine.py`). **But** returns/sample writes have NO UI in any gen ([matrix §3]) → **REBUILD-as-new** those surfaces (greenfield, no V1 to keep). |
| 4 | Proforma | **KEEP V2** + finish ADR-029 workspace | Most mature domain; `proforma-v2.html` LIVE; ADR-029 PR-1 merged+deployed, PR-2 scoped. **MERGE the two live proforma write surfaces** (R-2/CA-1) onto the designated Track-1 workspace. |
| 5 | DHL / Customs | **KEEP V2** (frontend) | T2 page wired (Sprint 31); backend stable. **GAP:** verify V2 DHL surface reflects ADR-030 tri-state CIF; DHL *write* actions still V1-only. |
| 6 | wFirma | **KEEP V2** (frontend) + **KEEP V1** (write/gating layer) | Sprint 37 wired frontend; the flag-gated write layer (`routes_wfirma.py`, ADR-025) is permanent architecture, not a migration target. **Also fix R-5/CA-3:** retire `_compute_effective_pz_status`, route the wFirma guard through `operational_authority.derive_pz_status`. |
| 7 | PZ | **MERGE** | T2 `pz` wired but correction lifecycle unresolved — Sprint 07 vs `pz-correction-v2-uxmod` collision (**OQ-1**). Consolidate display into `/v2/pz`, wire `routes_pz.py` correction chain, retire `atlas/pz-v2.html` stub. |
| 8 | Documents | **KEEP V2** | Hub wired; needs backend `GET /api/v1/documents` (Sprint 04 gap) + backend CMR/packing PDF generators (currently print-only). |
| 9 | Master data / customer master | **KEEP V2** | `customer-master-v2.html` + `master-data-v2.html` live (T1 designated owner); T2 `master` wired (Sprint 38). **OQ-3:** are the two T1 pages distinct domains or competing? |
| 10 | Ledgers / Accounting | **MERGE** | T2 `accounting-hub.jsx` is MOCK; `accounting-hub-v2.html` (T1) + `atlas/ledgers-v2.html` exist; all endpoints already exist (`routes_ledgers.py`, `routes_finance_postings.py`). Wire shell to existing routes; retire standalone. |
| 11 | Inbox | **KEEP V2** | T2 `inbox-page.jsx` wired (Sprint E3b, deployed); retire `inbox-v2.html` stub. |
| 12 | Global search | **KEEP V2** | T2 wired; `routes_search.py` exists. **GAP:** `global-search.jsx:6` header still says "stubbed" vs `atlas/search-v2.html` live — reconcile. |
| 13 | Carriers | **KEEP V2** | Sprint 39 wired (Integration-Gaps tab); backend stable; live DHL label = Phase D (ADR-026). |
| 14 | `dashboard-shared.js` | **MERGE → single source** | Identical root/v2 copies (R-7); v2 copy orphaned per ADR-028. **RETIRE** the orphaned `v2/dashboard-shared.js`. |
| 15 | `pz-api.js` | **MERGE** | Divergent fork (R-1); v2 is a superset. Converge Track-1 onto the v2 superset (or a shared module) so proforma-v2 gains readiness/ambiguity methods. |
| 16 | `pz-state.js` / `pz-components.js` | **MERGE** | R-8 divergence (`useProformaDraftEvents`); unify hook set. |
| 17 | Atlas shell (`static/atlas/*.html`) | **RETIRE** (or absorb) | Parallel stub nav tree (R-9), disconnected; superseded by the T2 `/v2/` shell. Confirm no unique live capability before removing. |
| 18 | V1 `dashboard.html`, `shipment-detail.html` | **RETIRE (Wave 5)** | Frozen; archive to git history after V2 write-parity verified. Lowest priority — harmless while frozen. |
| 19 | `batch.html`, `warehouse.html`, `admin-users.html` | **RETIRE (Wave 5)** | After their V2 equivalents (Sprints 08/10/11) are live. |
| 20 | Orphaned `shipment-detail-page.v1/v2.jsx`, `shipping-ops.jsx` | **RETIRE now** | Dead MOCK/wireframe (R-10); zero blast radius; removing reduces navigation confusion. |

---

## 2. Migration waves (sequenced)

**Wave 0 — Governance / gap closure (no new feature code).** Resolve the open questions that block sequencing:
- OQ-1 PZ-correction campaign collision · OQ-2 `shipment-detail-v3.html` disposition · OQ-3 master-data vs customer-master overlap · OQ-4 `reports` shell page source · OQ-5 formalize ADR-028 status (currently "Proposed").
- Retire dead files (item 20) and the orphaned `v2/dashboard-shared.js` (item 14).
- **Unblocks:** Waves 1–4.

**Wave 1 — Finish the `/v2/` shell (3 MOCK pages).** Wire `accounting`/`reports`/`admin` shell routes to existing backend routes (`routes_ledgers`, `routes_finance_postings`, `routes_analytics`, `routes_admin*`). **GAP:** no sprint file for `reports` (OQ-4). **Unblocks:** trustworthy shell-wide navigation → Wave 5.

**Wave 2 — Converge the shared layers + backend authority (the duplication debt).** Unify `pz-api.js`/`pz-state.js`/`dashboard-shared.js` (items 14–16); converge the dual proforma write surface onto the Track-1 workspace per `proforma-workspace-consolidation-plan.md` (R-2); **retire `_compute_effective_pz_status`** and route the wFirma guard through `operational_authority` (R-5/CA-3). **Unblocks:** safe single-surface proforma + removes the only backend authority divergence.

**Wave 3 — Complete ADR-029 Proforma Workspace.** Open PR-2 (V1/V2/V6/V7 detectors + §5 hard gate) after a GATE-2 slot frees; add `workflow_stage` column; flip `consolidated_workflow` flag. **Depends on:** GATE-2 throttle, ADR-026 for AWB delegation.

**Wave 4 — Backend authority completions (close functional gaps).** `GET /api/v1/documents` cross-batch list (Sprint 04); PZ cross-batch list (Sprint 07); inventory **returns/sample write UIs** + reservation-queue UI (backends exist, no surface); CMR/packing PDF backend generators; resolve PZ-correction collision then wire correction chain into `/v2/pz` (Wave 3 of agent plan). **Depends on:** Wave 0 (OQ-1), GATE-2 throttle.

**Wave 5 — V1 decommission (lowest priority).** Archive `dashboard.html`/`shipment-detail.html` from static serving (retain git history) once V2 has **write parity** and operators are verified on V2 paths; retire `batch.html`/`warehouse.html`/`admin-users.html` after Sprints 08/10/11; retire the Atlas shell (item 17). **Do not rush** — frozen V1 is harmless; operator migration matters more than file cleanup.

---

## 3. Open questions (operator decision required)

| # | Question | Blocks |
|---|---|---|
| OQ-1 | `pz-correction-v2-uxmod` — closed, absorbed, or active? (`PHASE_0_AUDIT.md §C.6`) | Wave 4 PZ correction wiring |
| OQ-2 | `shipment-detail-v3.html` (526 ln) — active prototype, Sprint-03 scope, or dead? (no route reference found) | Wave 0 cleanup |
| OQ-3 | `master-data-v2.html` (1,665 ln, products) vs `customer-master-v2.html` (926 ln) — distinct domains or competing? | Master-data ownership |
| OQ-4 | `reports` shell page — data source + sprint owner? (no sprint 1–43 covers it) | Wave 1 completion |
| OQ-5 | ADR-028 status is "Proposed (pending operator approval)" — formalize to match implemented reality | Governance hygiene |
| OQ-6 | `MOCK_PAGE_AUTHORITY_AUDIT.md` (2026-06-06) flags `master-page`/`carriers-page` MOCK, but WIRED_PAGES claims 17/17 — which is current? | Accuracy of "V2 complete" claim |

---

## 4. Decision summary

| Verdict | Modules |
|---|---|
| **KEEP V2** | Shipments, Dashboard, Inventory(read), Proforma, DHL(frontend), wFirma(frontend), Documents, Master/Customer, Inbox, Search, Carriers |
| **KEEP V1** | wFirma write/gating layer only (permanent architecture) |
| **MERGE** | PZ display+correction, Ledgers/Accounting, all three shared JS layers, dual proforma write surface |
| **REBUILD** | Inventory returns/sample UIs, reservation-queue UI, CMR/packing PDF backends (greenfield — no V1 to keep) |
| **RETIRE** | Atlas shell; orphaned `*.v1/.v2.jsx` + `shipping-ops.jsx`; orphaned `v2/dashboard-shared.js`; (Wave 5) V1 `dashboard.html`/`shipment-detail.html`/`batch.html`/`warehouse.html` |

**Platform direction: V2-FIRST — confirmed by evidence, already in execution.** The remaining work is (a) finish 3 MOCK shell pages, (b) **collapse the V2 fragmentation** (Track-1/Track-2/Atlas → one surface + one shared-lib source), (c) close the backend authority divergence (R-5), (d) build the missing write UIs, then (e) decommission V1. After this campaign, every future ownership/sequencing decision anchors to these four documents.
