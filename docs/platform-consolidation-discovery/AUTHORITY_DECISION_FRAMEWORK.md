# AUTHORITY_DECISION_FRAMEWORK.md — Binding Governance Layer

**Campaign:** EJ PLATFORM CONSOLIDATION DISCOVERY → DECISION
**Inspected:** `origin/main @ fb70e15` (read-only; evidence carried from the discovery pass)
**Date:** 2026-06-18
**Status:** DRAFT — requires leadership sign-off (§4) before any wave begins.
**Consolidates:** [AUTHORITY_MAP.md](./AUTHORITY_MAP.md) (= WORKFLOW_AUTHORITY_MATRIX), [V1_V2_CAPABILITY_MATRIX.md](./V1_V2_CAPABILITY_MATRIX.md) (= UI_SURFACE_DECISION_MATRIX inputs), [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md) (= DUPLICATE_AUTHORITY_REGISTER + BACKEND_AUTHORITY_CONFLICT_REPORT), [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md) (= CONSOLIDATION_WAVE_PLAN). This document is the single binding view; the four above are its evidence base.

> Every subsequent migration work item MUST cite a decision ID (D-n) or conflict ID (R-n / CA-n) from this framework.

---

## 1. Executive Summary

**State of authority today.** The platform is **one shared FastAPI backend** under **four frontend surfaces**: a frozen V1 monolith, a Track-1 standalone V2-HTML set, the Track-2 `/v2/` JSX shell (WIRED_PAGES 17/17 — the real working V2 app), and an `static/atlas/*.html` stub shell. Backend authority is mostly clean and singular; the dominant problem is **frontend fragmentation** (the same workflow rendered by up to 4–6 surfaces over forked copies of the same JS libraries) plus **one true backend authority divergence** (PZ status). Direction is already set and executed: **V2-FIRST**.

**The gaps.** (a) The PZ-status calculation has two backend owners that can disagree (`operational_authority.derive_pz_status` vs `routes_wfirma._compute_effective_pz_status`). (b) The proforma write workflow exists on two *live* surfaces, one of which lacks the readiness gate. (c) Shared libraries (`pz-api.js`, `pz-state.js`, `dashboard-shared.js`) are forked/duplicated. (d) Several backends have **no UI in any surface** (inventory returns/sample, reservation queue) and several UIs have **no backend** (cross-batch documents/PZ list, CMR/packing PDF). (e) The term "Atlas" is overloaded.

**The 3–5 critical decisions leadership must make:**
- **D-1 — Canonical PZ-status owner** (resolve R-5/CA-3): make `operational_authority.derive_pz_status` the sole authority; promote or reject the wFirma "Path B" rule explicitly.
- **D-2 — Atlas role**: confirm the Track-2 `/v2/` JSX shell is the future shell; the `static/atlas/*.html` stub shell is RETIRE/absorb; ADR-029 orchestration-shell is a *bounded per-workspace* exception, not a universal mandate.
- **D-3 — Canonical state/transport layer**: pick one source for `pz-api.js`/`pz-state.js`/`dashboard-shared.js` and retire the forks.
- **D-4 — Canonical proforma write surface** (resolve R-2/CA-1): one live write surface, readiness-gated.
- **D-5 — Wave order + parallelism**: accept the sequencing in §8.

**Business risk of delay.** Every week the PZ divergence (D-1) stays open, the wFirma PZ-create guard can admit a goods-receipt the dashboard would block — a real accounting-integrity exposure on a write path. Every week the dual proforma surface (D-4) stays open, operators on Track-1 can post drafts without the readiness pre-check. Fragmentation also taxes every change: a fix must be applied to up to 4 surfaces or silently diverge.

---

## 2. Authority Map (consolidated)

### 2.1 Backend authority by domain (canonical owner)
| Domain | Canonical backend authority | Persistence | Conflict? |
|---|---|---|---|
| Shipment lifecycle / status | `operational_authority.derive_status` | per-batch `audit.json` + `timeline.jsonl` | — |
| **PZ status** | **`operational_authority.derive_pz_status`** (`operational_authority.py:115`) | `documents.db`/`wfirma.db` | **YES → R-5/CA-3 (D-1)** |
| PZ engine (landed cost) | `process_batch()` via `export_service` | `audit.json`/`pz_rows.json` | — (frozen valuation) |
| Proforma drafts/lifecycle | `proforma_draft_governance` + `routes_proforma` | `proforma_links.db` | — backend; **frontend dual surface (R-2)** |
| wFirma writes (PZ/invoice) | `wfirma_client` (flag-gated) | `wfirma.db` (system of record) | — (intentional gate, KEEP V1 model) |
| DHL/customs | `dhl_clearance_coordinator` + `clearance_decision` | `audit.json` | — |
| CIF resolution | `cif_resolver` tri-state (ADR-030) | derived | — |
| Inventory state | `inventory_state_engine` (never bypass) | `warehouse.db` | — |
| Customer/Supplier master | `customer_master_db` / `suppliers_db` (ADR-023/024) | master DBs | — (GAP: paths) |
| Documents | per-batch via `routes_dashboard`/`routes_upload` | `documents.db` | cross-batch list endpoint **absent** |
| Readiness | `routes_batch_readiness` / `routes_dhl_readiness` / `routes_proforma` readiness | reads | — (frontend must not recompute) |
| AI execution | `ai_gateway` (sole, ADR-020) | `ai_call_ledger.db` | — |

### 2.2 Frontend authority by domain (canonical renderer — target)
| Domain | Canonical renderer (target) | Today's competing surfaces (to MERGE/RETIRE) |
|---|---|---|
| Proforma | Track-1 `proforma-v2.html` workspace (per `proforma-workspace-consolidation-plan.md`) **OR** Track-2 `proforma-detail.jsx` — **D-4 must pick one** | the other live surface + V1 inline + `atlas/proforma-v2.html` stub |
| Shipment detail | Track-2 `shipment-detail-page.jsx` (after write-parity) | V1 `shipment-detail.html` (frozen), `shipment-detail-v3.html` (OQ-2), 2 orphaned `.v1/.v2.jsx` |
| Dashboard | Track-2 `dashboard-page.jsx` | V1 `dashboard.html`, `dashboard-v2.html`, `atlas/dashboard-v2.html` |
| Master/Customer | Track-1 `customer-master-v2.html` + `master-data-v2.html` (designated owners) | V1 inline, Track-2 read-only `master-page.jsx` |
| All others | Track-2 `/v2/` shell pages | V1 inline + Atlas stubs |

**Canonical resolution of every known conflict is in §6 (Conflict-to-Impact Register).**

---

## 3. Atlas Platform Decision Brief (answers the leadership question)

**Question:** Is Atlas the future shell for all workflows, or only a workspace for specific domains?

**Finding (evidence-based):** "Atlas" is **two different things** and the term must be disambiguated:
- **`static/atlas/*.html` + `atlas-shared.js`** — a parallel **stub** shell with its own nav tree (R-9); mostly read-only placeholders (e.g., `atlas/proforma-v2.html` = 73 lines). This is **NOT** the future shell.
- **The Track-2 `/v2/` JSX shell** (`v2/index.html` + `v2/*.jsx`, WIRED_PAGES 17/17, governed by ADR-028) — this **is** the real, working V2 application and the future shell.
- **ADR-029 "orchestration shell"** is a **bounded, per-workspace exception** (Proforma first) allowing one V2 surface to coordinate multiple domains *without re-implementing their logic* — it is **not** a mandate that one shell owns every domain's business logic.

**Recommended decision (D-2):**
> The **future shell = the Track-2 `/v2/` JSX shell.** The `static/atlas/*.html` stub shell is **RETIRE/absorb** (Wave 5). The orchestration-shell pattern is applied **per workspace** where a domain genuinely needs cross-domain coordination (Proforma now; others only on explicit ADR), never as a blanket "Atlas owns all workflows."

**Implications of each choice:**
| Choice | Implication |
|---|---|
| **`/v2/` shell is the universal future shell (recommended)** | One operator app; per-page domain isolation (Lesson F); orchestration only by ADR exception. Lowest coupling, matches WIRED 17/17 reality. |
| "Atlas stub shell becomes the universal shell" | Throws away the WIRED 17/17 investment; rebuilds wired pages as stubs. **Rejected.** |
| "One orchestration shell owns all domains" | Re-creates the V1 monolith coupling that the migration exists to escape (Lesson F §3-4). **Rejected.** |

**GAP/OQ:** the campaign docs sometimes call the Track-2 shell "Atlas-V2," colliding with the `static/atlas/` name. Leadership should ratify a single term to avoid this brief being misread.

---

## 4. Classification Criteria + UI Surface Decision Matrix

### 4.1 Defensible criteria (makes the matrix reproducible/auditable)
Score each surface on five factors; the dominant factor drives the verdict.
| Factor | Definition | Pulls toward |
|---|---|---|
| **Strategic direction** | V2 strategic · V1 frozen (Lesson F) · `atlas/` stub deprecated | V1→RETIRE; V2→KEEP |
| **Risk profile** | criticality to a live workflow + operator reach | critical+live→careful MERGE not RETIRE |
| **Tech-debt cost** | rebuild cost vs. keep cost | high keep-cost (16k-line monolith)→RETIRE; low→KEEP |
| **Dependency complexity** | how many surfaces import/route to it | high (shared libs)→MERGE to one source |
| **Recency** | last substantive change; actively evolving vs. dormant | dormant orphan→RETIRE |

### 4.2 Applied matrix (worked reasoning; full list in MIGRATION_ROADMAP §1)
| Surface | Verdict | Dominant criteria → reasoning |
|---|---|---|
| V1 `dashboard.html` / `shipment-detail.html` | **RETIRE (Wave 5)** | Strategic (frozen) + tech-debt (20k/16k lines) — archive after V2 write-parity |
| Track-1 `proforma-v2.html` + `proforma-detail-v2.html` | **MERGE** | Risk (critical+live) + dependency — converge with Track-2 onto one live surface (D-4) |
| Track-2 `proforma-detail.jsx` | **MERGE/KEEP** | Strategic + has readiness gate — likely the survivor |
| Track-2 `/v2/*.jsx` wired pages | **KEEP** | Strategic + recency (WIRED 17/17) |
| `static/atlas/*.html` stub shell | **RETIRE** | Strategic (stub) + recency (dormant) + dependency (parallel nav) |
| `pz-api.js` / `pz-state.js` / `dashboard-shared.js` (forks) | **MERGE → one source** | Dependency (every page) — R-1/R-7/R-8 |
| orphaned `shipment-detail-page.v1/v2.jsx`, `shipping-ops.jsx` | **RETIRE now** | Recency (dead MOCK) — zero blast radius |
| Inventory returns/sample UI, reservation-queue UI | **REBUILD (greenfield)** | No V1 to keep; backend exists, UI absent |

---

## 5. Decision Validation Checklist (leadership sign-off — traceable)

Each item: mark **ACCEPT** / **REJECT**, add rationale if rejected. No wave begins until D-1…D-5 are ACCEPT.

```
D-1  Canonical PZ-status owner = operational_authority.derive_pz_status;
     routes_wfirma._compute_effective_pz_status RETIRED; "Path B" (pz_output.pdf
     as MRN substitute) explicitly promoted-into-canonical OR rejected.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____

D-2  Future shell = Track-2 /v2/ JSX shell; static/atlas/*.html = RETIRE/absorb;
     ADR-029 orchestration = bounded per-workspace exception, not universal.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____

D-3  Canonical shared-library source chosen (one pz-api.js / pz-state.js /
     dashboard-shared.js); forks RETIRED.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____

D-4  Canonical proforma write surface chosen (one live, readiness-gated);
     the other demoted to read-only or retired.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____

D-5  Wave order + parallelism per §8 accepted.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____

D-6  Open questions OQ-1..OQ-6 (MIGRATION_ROADMAP §3) assigned an owner + due date.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____

D-7  Escalation protocol (§7) adopted; conflict decision-maker named.
     [ ] ACCEPT   [ ] REJECT — rationale: ____________________   Signed: ______  Date: ____
```

---

## 6. Conflict-to-Impact Register

> **User counts: operator to supply** — I do not have telemetry; blast radius is described by which workflows/surfaces touch each conflict. This is the GAP flagged in discovery.

| ID | Conflict | Workflows affected | Blast radius | If option A wins | If option B wins | Priority |
|---|---|---|---|---|---|---|
| **R-5 / CA-3** | PZ-status: `derive_pz_status` vs `_compute_effective_pz_status` (Path B) | PZ create, dashboard readiness, wFirma posting | **Write path** — wrong allow/deny on goods-receipt = accounting integrity | A=`derive_pz_status` canonical: must encode Path B as explicit branch or some PZs newly blocked | B=wFirma fork stays: dashboard keeps disagreeing | **P0** (write integrity) |
| **R-2 / CA-1** | Dual live proforma write surface (T1 ungated vs T2 gated) | Proforma approve/post/convert | Operators on T1 post without readiness pre-check | Keep T2 (gated): T1 users must switch surface | Keep T1: re-add gate to v1 transport (R-1 dependency) | **P0** |
| **R-1** | `pz-api.js` fork (263 vs 566) | All proforma/shared pages | T1 lacks readiness/ambiguity/search methods | Converge on v2 superset: T1 gains methods | Maintain both: permanent drift | **P1** (blocks R-2 fix) |
| **R-3** | `dashboard.html` vs `dashboard-page.jsx` | Cross-batch pipeline view | Divergent lane logic; new caps invisible per surface | Keep T2: retire V1 view after parity | Keep both: double maintenance | **P2** |
| **R-4** | `shipment-detail.html` vs `shipment-detail-page.jsx` | Full shipment lifecycle | T2 lacks live write actions (DHL/PZ/wFirma) | Keep T2: must reach write-parity first | Keep V1: migration stalls | **P1** |
| **R-7** | `dashboard-shared.js` identical orphaned v2 copy | All V2 pages (latent) | Silent drift trap | Delete orphan (ADR-028) | Leave: future drift | **P3** (cheap) |
| **R-8** | `pz-state.js` fork (`useProformaDraftEvents`) | Proforma events | Two fetch patterns | Unify hook | Leave: drift | **P2** |
| **CA-2** | `apiFetch` ×3 implementations | All pages (error/401/204 contract) | Silent behavior drift on Track-1.5 pages | Single shim + tests | Leave: untested forks | **P2** |
| Coverage gaps | returns/sample/reservation UI absent; cross-batch docs/PZ list, CMR/packing PDF backends absent | inventory, documents, PZ | Capability simply unavailable (not wrong) | Build (REBUILD) | — | **P2–P3** |

---

## 7. Escalation Protocol (anchored to existing governance gates)

Reuse the repo's existing gate vocabulary (CLAUDE.md GATE 4 dispositions) — do **not** invent a parallel process.

```
TRIGGER  A conflict is discovered where (a) two backend services own the same calculation/state,
         (b) a frontend surface contradicts backend authority, or (c) a wave audit surfaces a
         duplicate-authority instance not in DUPLICATE_AUTHORITY_REPORT.
GATE     Block the affected wave at its current step. Do NOT proceed past the conflicting surface.
OWNER    Platform architect proposes canonical owner; OPERATOR decides (sole sign-off, per
         "prod write is operator-only" + GATE-4 disposition authority).
INPUTS   Required before decision: (1) both implementations' file:line; (2) a divergence example
         (input → differing outputs); (3) which workflows/write-paths are affected; (4) the
         proposed canonical owner + what the loser's unique logic must become (promote or drop).
SLA      P0 (write-path integrity, e.g. R-5): decide within 1 business day, wave stays blocked.
         P1: 3 business days. P2/P3: dispositioned at next wave-planning, wave may proceed if the
         conflict is outside that wave's surface set.
DISPOSITION  Exactly one of GATE-4's: SCHEDULED (named wave), ISSUE (GitHub issue + labels),
         REJECTED (operator declines, rationale logged here). "Noted" is not a disposition.
FALLBACK If escalation stalls past SLA: the wave does NOT begin (fail-closed). A P0 conflict
         blocks ALL waves that touch the same authority until resolved.
```

---

## 8. Wave Sequencing & Traceability

Every wave traces to decisions/conflicts in this framework. A wave may not start until its **blocking conflicts** are dispositioned (§7) and its decisions (§5) are ACCEPT.

| Wave | Domain | Surfaces (KEEP/MERGE/REBUILD/RETIRE) | Blocking conflicts (must resolve first) | May overlap with | Audit trail to capture |
|---|---|---|---|---|---|
| **0** | Governance/cleanup | RETIRE orphans (R-10), RETIRE orphaned `v2/dashboard-shared.js` (R-7) | OQ-1..OQ-6 assigned (D-6) | — | OQ disposition log; dead-file removal diff |
| **1** | Shared layers + PZ authority | MERGE `pz-api/state/dashboard-shared` (R-1/R-7/R-8/CA-2); **resolve R-5/CA-3** | **D-1, D-3** (P0/P1) | none (foundational) | Before/after divergence test for PZ status; lib-source decision record |
| **2** | Proforma | MERGE to one live write surface (R-2) | **D-4**, depends on Wave 1 (R-1) | — | Readiness-gate parity proof; surface-retirement record |
| **3** | Shipment + DHL | KEEP T2; build write-parity (R-4); DHL writes off V1 | R-4; ADR-030 CIF verify | Wave 4 (disjoint code) | Write-parity checklist per action |
| **4** | PZ / wFirma | MERGE PZ display+correction (OQ-1); KEEP wFirma write-gate layer | OQ-1 (correction collision) | Wave 3 | Correction-chain wiring proof |
| **5** | Inventory + Documents + Reporting | REBUILD returns/sample/reservation UI; build cross-batch docs/PZ list + CMR/packing PDF backends; wire 3 MOCK shell pages | OQ-4 (reports source) | parallelizable (greenfield) | New-endpoint contract tests |
| **6** | V1 decommission | RETIRE V1 monolith + Atlas stub shell (D-2) | all prior waves verified + operator on V2 | — | Operator-migration confirmation; archive tags |

**Parallelism rule:** waves touching **disjoint surface sets** may overlap (3∥4, components of 5). Any wave touching a **P0-conflicted authority** (PZ, R-5) is serialized behind Wave 1.

**Traceability invariant:** each migration PR cites a Wave + a decision ID (D-n) + any conflict IDs (R-n/CA-n) it resolves. A PR with no framework reference is out of governance.
