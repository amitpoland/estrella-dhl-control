# DUPLICATE_AUTHORITY_REPORT.md — Estrella PZ Platform

**Campaign:** EJ PLATFORM CONSOLIDATION DISCOVERY
**Inspected:** `origin/main @ fb70e15` (read-only; via `git show`/`diff`/`grep`)
**Date:** 2026-06-18
**Companion docs:** [AUTHORITY_MAP.md](./AUTHORITY_MAP.md) · [V1_V2_CAPABILITY_MATRIX.md](./V1_V2_CAPABILITY_MATRIX.md) · [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md)

> "Live" = reachable via the deployed `static/` mount + an in-app navigation/route link. "Orphaned" = on disk and technically served by the `/dashboard/{path}` wildcard, but no navigation points to it. Risk types: **DC** = data-consistency, **M** = maintenance, **D** = deployment.

---

## Risk register (summary — full detail below)

| ID | Cluster | Risk | Why |
|---|---|---|---|
| **R-1** | `pz-api.js` v1 (263 ln) vs v2 (566 ln) | **HIGH** (DC) | Two LIVE transport layers, divergent method sets; Track-1 proforma pages lack `getDraftReadiness`/`resolveDraftAmbiguity` |
| **R-2** | Proforma detail: `proforma-detail-v2.html` (T1) vs `proforma-detail.jsx` (T2) | **HIGH** (DC) | Same draft, two LIVE write surfaces; T1 bypasses the frontend readiness pre-check |
| **R-3** | `dashboard.html` vs `v2/dashboard-page.jsx` | **HIGH** (DC/M) | Two LIVE pipeline renderers; new capability in one invisible via the other |
| **R-4** | `shipment-detail.html` vs `v2/shipment-detail-page.jsx` | **HIGH** (DC) | Two LIVE shipment renderers; Pro-Forma tab + write affordances differ |
| **R-5** | `routes_wfirma._compute_effective_pz_status` vs `operational_authority.derive_pz_status` | **HIGH** (DC) | **Backend** authority divergence — wFirma guard has extra "Path B"; can disagree with dashboard readiness |
| **R-6** | `EstrellaShared.apiFetch` ×3 implementations | **MED** (M) | `dashboard-shared.js` / `v2/index.html` shim / `pz-design-v2.js` — contract drift risk; latter two untested |
| **R-7** | `dashboard-shared.js` root vs `v2/` copy | **MED** (M) | **Bit-identical today**; v2 copy ORPHANED (ADR-028 says shell must not load it) → silent-drift trap |
| **R-8** | `pz-state.js` v1 (151) vs v2 (138) | **MED** (M) | `useProformaDraftEvents` hook in v1 only; two patterns for same fetch |
| **R-9** | Atlas shell parallel nav (`static/atlas/`) | **MED** (M) | Complete separate nav tree of stubs, disconnected from V1 and T2 |
| **R-10** | `shipment-detail-page.v1.jsx`/`.v2.jsx`, `shipping-ops.jsx` | **LOW** (M) | Orphaned MOCK/wireframe variants; confuse navigation |
| **R-11** | `atlas/proforma-v2.html` (73 ln), `atlas/documents-v2.html` (89 ln) | **LOW** | Reachable stub placeholders, no real data |

---

## Cluster 1 — Shared JS layers

| Artifact | V1 / Track-1 | Track-2 (`v2/`) | Identical? | Live status | Risk |
|---|---|---|---|---|---|
| `dashboard-shared.js` | `static/dashboard-shared.js` (536 ln) — **LIVE** (loaded by `dashboard.html`, `shipment-detail.html`, `proforma-v2.html:96`) | `static/v2/dashboard-shared.js` (536 ln) — **ORPHANED** (v2 shell must not load it per ADR-028; not in `index.html`) | **IDENTICAL (0-line diff)** | one live, one dead copy | **R-7 MED/M** — silent drift trap |
| `pz-api.js` | `static/pz-api.js` (263 ln) — LIVE (`proforma-v2.html:97`, `shipment-detail.html`) | `static/v2/pz-api.js` (566 ln) — LIVE (`index.html:51`) | **DIVERGENT FORK** (v2 superset +303 ln) | both LIVE | **R-1 HIGH/DC** |
| `pz-state.js` | `static/pz-state.js` (151 ln) — LIVE | `static/v2/pz-state.js` (138 ln) — LIVE | DIVERGENT (v1 adds `useProformaDraftEvents`) | both LIVE | **R-8 MED/M** |

**R-1 detail (divergent transport).** `v2/pz-api.js` exclusively adds: `_isProposalActionUrl` security guard (`:42-49`), `searchProformaDrafts` (`:105-115`), `deleteDraft`/`sendProformaEmail`/`cloneDraft`/`draftToInvoice`/`getDraftEvents`/`getDraftReadiness`/`resolveDraftAmbiguity` (`:180-272`), `approveProposal`/`rejectProposal` w/ URL validation (`:307-347`), wFirma + 13 master-data read endpoints (`:349-395`), system-health endpoints. The v1 copy has none of these. Stale comment `v2/pz-api.js:10` ("MUST load AFTER dashboard-shared.js") is wrong under ADR-028. **Consequence:** `proforma-v2.html` (Track-1) runs a functionally inferior transport with no readiness/ambiguity safety methods.

**ADR-028 mandate** (`.claude/adr/ADR-028-v2-shell-no-dashboard-shared.md`): the `/v2/` shell MUST NOT load `dashboard-shared.js`; `apiFetch` comes from the inline shim (`v2/index.html:18-46`). The orphaned `v2/dashboard-shared.js` was never flagged for deletion — **GAP:** clean-up not tracked.

---

## Cluster 2 — Shipment-detail surfaces (5)

| File | Lines | Live? | Data | Reached via |
|---|---|---|---|---|
| `static/shipment-detail.html` | 16,214 | **LIVE** (primary V1) | live | `dashboard.html:20007` |
| `static/shipment-detail-v3.html` | 526 | reachable (orphaned-ish) | live | `inbox-v2.html:90`, `pz-design-v2.js:98` only |
| `static/v2/shipment-detail-page.jsx` | 871 | **LIVE** (T2) | live (writes PENDING) | `v2/index.html:255,583` |
| `static/v2/shipment-detail-page.v1.jsx` | 383 | **ORPHANED** | **MOCK** (`simulateAction`, hardcoded `PZ/2024/001234`) | nothing |
| `static/v2/shipment-detail-page.v2.jsx` | 627 | **ORPHANED** | unwired | nothing |

**R-4 (HIGH/DC):** `shipment-detail.html` and `shipment-detail-page.jsx` are both LIVE for the same batch, pulling `GET /api/v1/dashboard/batches/{id}` but rendering different logic — V1 is the full write surface; T2 adds a Pro-Forma tab V1 lacks (`shipment-detail-page.jsx:1-8`). Operators on different paths see different affordances. **R-10 (LOW):** the two `.v1/.v2.jsx` orphans are dead MOCK code.

---

## Cluster 3 — Dashboard surfaces (5)

| File | Live? | Reached via |
|---|---|---|
| `static/dashboard.html` | **LIVE** (primary V1) | `/dashboard` → `main.py:525,686` |
| `static/dashboard-v2.html` (613 ln) | reachable, **no primary nav** | — |
| `static/atlas/dashboard-v2.html` | reachable | `atlas-shared.js:141` (Atlas nav) |
| `static/v2/dashboard-page.jsx` | **LIVE** (T2) | `v2/index.html:254` |
| `static/v2/dashboard-kanban.jsx` | LIVE-loaded | `v2/index.html:271` (GAP: confirm rendered route) |

**R-3 (HIGH):** `dashboard.html` vs `v2/dashboard-page.jsx` both LIVE — divergent batch pipeline views; lane derivation differs (`OP_PREDICATES` vs `deriveLane`). **R-9 (MED):** `atlas/` has its own nav tree (`atlas-shared.js:141-150`) — a third parallel navigation system.

---

## Cluster 4 — Proforma surfaces

| File | Lines | Live? | Transport |
|---|---|---|---|
| `static/proforma-v2.html` | 830 | **LIVE** (T1 workspace) | **v1** `pz-api.js` |
| `static/proforma-detail-v2.html` | 1,073 | **LIVE** | v1 (via `pz-design-v2.js`) |
| `static/atlas/proforma-v2.html` | 73 | reachable | STUB |
| `static/v2/proforma-list.jsx` | 136 | **LIVE** (T2) | **v2** `pz-api.js` |
| `static/v2/proforma-detail.jsx` | 3,008 | **LIVE** (T2) | v2 |
| `static/v2/proforma-search.jsx` | 408 | **LIVE** (T2) | v2 (`searchProformaDrafts`) |
| `static/v2/estrella-doc-proforma.jsx` | 630 | LIVE (print component) | — |

**R-2 (HIGH/DC) — two live proforma write workflows.** Track-1 (`proforma-detail-v2.html`, v1 transport) exposes approve/post/clone but its transport **lacks `getDraftReadiness`**, so it shows no frontend readiness pre-check/blocker reason; Track-2 (`proforma-detail.jsx`, v2 transport) calls `GET /draft/{id}/readiness?intent=…` before enabling actions. Backend ultimately enforces the gate, but T1 is a Lesson-F "frontend reflects truth, does not produce it" violation. `docs/proforma-workspace-consolidation-plan.md §0.2` confirms this is a known tension and designates Track-1 `proforma-v2.html` as the intended workspace — **plan not yet executed.**

---

## Cluster 5 — Documents surfaces

| File | Live? | Relationship |
|---|---|---|
| `static/documents-v2.html` (480 ln) | LIVE (per-batch view) | linked from `documents-hub.jsx` |
| `static/atlas/documents-v2.html` (89 ln) | reachable STUB | Atlas nav |
| `static/v2/documents-hub.jsx` (226 ln) | **LIVE** (hub, read) | `v2/index.html:269` |

**LOW** — hub + per-batch view are complementary (different hierarchy levels), not conflicting. No cross-batch `GET /api/v1/documents` endpoint exists (Sprint 04 gap).

---

## Conflicting-authority subsection (LIVE surfaces that could derive/write the same truth differently)

**CA-1 — Proforma draft lifecycle, two live write paths (CRITICAL).** `proforma-detail-v2.html` (T1, no readiness pre-check) vs `proforma-detail.jsx` (T2, readiness-gated). Evidence: `proforma-v2.html:352`; `v2/index.html:720`; `v2/pz-api.js:242-258` (`getDraftReadiness`) absent in `pz-api.js`.

**CA-2 — `EstrellaShared.apiFetch` ×3 (MED).** (1) `dashboard-shared.js:26-75`; (2) `v2/index.html:18-46` inline shim (ADR-028, tested); (3) `pz-design-v2.js:26-56` (conditional, loaded by `shipment-detail-v3.html`, `proforma-detail-v2.html`, `wfirma-inbox-v2.html`, `customer-master-v2.html`) — **no test coverage referenced.** If 401/204/error-shape behavior drifts, Track-1.5 pages behave differently silently.

**CA-3 — `routes_wfirma._compute_effective_pz_status` vs `operational_authority.derive_pz_status` (HIGH, BACKEND).** This is the **only backend** conflicting authority. `routes_wfirma.py:146` adds "Path B" (missing-MRN tolerated if `pz_output.pdf` present) not in the canonical `operational_authority.py:115`. Used at `routes_wfirma.py:289,325,341,1594,1648,1774`. The wFirma PZ-create guard can therefore admit a PZ the dashboard readiness would classify differently. History: `operational_authority.py:4-9` ("three places → consolidated two") — this is the surviving third.

**CA-4 — Shipment-detail dual renderer (covered as R-4).**

---

## Cross-reference to existing in-repo findings
- `docs/proforma-workspace-consolidation-plan.md §0.2` — confirms CA-1 (Track-1 vs Track-2 proforma) is a known, planned-but-unexecuted consolidation; Track-1 designated workspace.
- `MOCK_PAGE_AUTHORITY_AUDIT.md` (2026-06-06) — flagged `master-page.jsx`, `carriers-page.jsx`, `wfirma_setup` as full-MOCK. **GAP/reconcile:** predates the WIRED_PAGES-17/17 completion; verify current state before treating as live duplicates.

## Information gaps
- **GAP-A:** `dashboard-kanban.jsx` loaded but render-route unconfirmed.
- **GAP-B:** MOCK-audit vs WIRED_PAGES timing conflict (above) — one of the two is stale; reconcile against current `static/v2/*.jsx`.
- **GAP-C:** `pz-design-v2.js` apiFetch shim has no referenced test (CA-2).
