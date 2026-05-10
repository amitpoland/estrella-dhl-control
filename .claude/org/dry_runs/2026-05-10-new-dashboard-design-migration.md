# New Estrella Dashboard Design — Migration Analysis

**Mode:** PRE-IMPLEMENTATION
**Scope:** evaluate the new design bundle from
`api.anthropic.com/v1/design/h/SsXdZzIKxDttoOyA8YSnYA` against
the current production dashboard. Doc-only — no code, no
backend, no test edits.
**Baseline:** `c2a704e` (W-2.3 first write-surface phase closed)
**Coordinator pass:** in-context (Opus); reviewer roles
(UI/UX Planner, Backend Architect, Route/API Mapper, Operator
Safety, Security, QA Lead, Gap Hunter) executed as
Coordinator-simulated parallel reads.

---

## 1. Design file summary

The handoff bundle decompresses to 45 files under
`estrella-dashboard/`:

| Category | Count | Notable files |
|---|---|---|
| Top-level docs | 2 | `README.md`, `chats/chat1.md` (2466 lines — the iteration history) |
| Main HTML prototypes | 3 | `Estrella Dashboard.html` (530 lines, primary), `Estrella Dashboard Standalone.html` (215 lines), `Estrella Document Suite.html` (192 lines) |
| JSX component files | 16 | `components.jsx`, `pages.jsx` (1050 lines), `pages-v2.jsx` (1166 lines), `master-page.jsx`, `inventory-page.jsx` (1225 lines), `ledgers-page.jsx`, `modals.jsx`, `dashboard-page.jsx`, `shipment-detail-page.jsx` (3 versions), `shipping-ops.jsx` (669 lines), `client-kyc-and-consignment.jsx`, `wireframe-update.jsx`, `tweaks-panel.jsx` |
| `estrella-docs/` subfolder | 9 | `tokens.css`, `tweaks-panel.jsx`, `design-canvas.jsx`, doc components (cmr / proforma / statement / xlsx / email-mobile), 2 logos |
| Uploads | 8 | Real Estrella data samples — Faktura WDT 48_2026.pdf, Pro forma PROF 95_2026.pdf, packing-list xlsx files, prior dashboard prototypes (`dashboard_prototype.html`, `estrella_dashboard_full.html`), screenshots |

Total JSX line count: ≈ 11 775 lines. The bundle uses React 18
+ Babel-standalone served from unpkg — pure prototype, no
build pipeline.

## 2. README findings (verbatim quotes)

The README directs the coding agent explicitly:

- *"Read `estrella-dashboard/project/Estrella Dashboard.html` in full. The user had this file open when they triggered the handoff, so it's almost certainly the primary design they want built."*
- *"The design medium is HTML/CSS/JS — these are prototypes, not production code. Your job is to recreate them pixel-perfectly in whatever technology makes sense for the target codebase."*
- *"If anything is ambiguous, ask the user to confirm before you start implementing."*

**Operator-facing assistant quote from chat1.md** (after building all sidebar pages):

> *"All sidebar modules are now fully wired … The design medium is HTML/CSS/JS — these are prototypes, not production code."*

**Implication:** the bundle is a *target* shape, not a *plan*. The coding agent (us) must decide which parts to bring across, in what order, and at what risk level. The README says "ask before implementing if ambiguous" — and *Polish DHL Express only* is exactly that ambiguity.

## 3. Existing dashboard workflow inventory

`service/app/static/dashboard.html` (15 133 lines) is a single-file React SPA built on a **batch-centric** paradigm:

| Surface | Shape | Test pinning |
|---|---|---|
| **Top-level routes** | Inline page state: `BatchListPage`, `BatchDetailPage`, plus standalone read-only pages already shipped (Action Proposals cross-batch, Broker Followups, Customer Statements, Proforma Drafts) | source-grep tests for each |
| **BatchDetailPage tabs** | `DETAIL_TABS = ['Overview','Documents','DHL / Customs','Warehouse','Sales','PZ / wFirma','Timeline','Intelligence','Proposals','DHL Express']` (10 tabs) | per-tab assertion files |
| **Recently-shipped surfaces** | W-2.1: `carrier-actions-tab` + shipment overview; W-2.2: shipment timeline + label evidence; W-2.3: proposals + confirmation drawer (3 simple actions) | 157 carrier-UI tests across `test_dashboard_carrier_overview.py`, `test_dashboard_carrier_timeline.py`, `test_dashboard_carrier_proposals.py` |
| **Test suite size** | 36 dashboard test files | 1032 passing tests at HEAD `c2a704e` |
| **Backend routes consumed** | 245 routes across 44 `routes_*.py` files | dashboard route audit (`test_dashboard_repair::test_route_audit_zero_stale`) — green |
| **Operator-visible label discipline** | "DHL Express" wording locked-in (W-2.1a) — generic "Carrier Shipments" forbidden by tests | 8 W-2.1a parametrised tests |

**The existing dashboard's first navigation is the batch.** A user opens a batch, then sees 10 tabs of context for that batch. The design from the bundle inverts this.

## 4. New design module inventory

`Estrella Dashboard.html` registers **22 top-level pages** via `components.jsx` `NAV_ITEMS`:

| ID | Label | Page reference | Wireframe state |
|---|---|---|---|
| dashboard | Dashboard | `dashboard-page.jsx` | functional |
| actions | Action Center | `pages-v2.jsx` | partial |
| shipments | Shipments | `dashboard-page.jsx` (shipment table) | functional |
| **shipping** | Shipping Ops | `shipping-ops.jsx` | **wireframe — multi-carrier (DHL Express + FedEx + UPS)** |
| dhl | DHL / Customs | `pages.jsx` | functional |
| accounting | Accounting | `pages.jsx` (PZ + Sales + wFirma + Master + Audit merged) | functional |
| inventory | Inventory | `inventory-page.jsx` (1225 lines, 2-stage) | partial |
| identity | Identity / Mapping | `pages-v2.jsx` | wireframe |
| move_stock | Move Stock | `pages-v2.jsx` | wireframe |
| sample_out | Sample Out | `pages-v2.jsx` | wireframe |
| sample_return | Sample Return | `pages-v2.jsx` | wireframe |
| goods_return | Goods Return | `pages-v2.jsx` | wireframe |
| return_prod | Return to Producer | `pages-v2.jsx` | wireframe |
| proposals | Action Proposals | `pages.jsx` | functional |
| intelligence | Intelligence (was Learning / Parser) | `pages.jsx` | functional |
| automation | Automation Center (AI Bridge) | `pages.jsx` | functional |
| email_queue | Email Queue | `pages.jsx` | wireframe |
| reports | Reports | `pages.jsx` | wireframe |
| master | Master Data | `master-page.jsx` (455 lines) | partial |
| coverage | Coverage Matrix | `pages.jsx` | doc-only |
| admin | Admin / Settings | `pages.jsx` | partial |

**Paradigm shift:** sidebar-first (22 items) instead of batch-first (10 tabs). A shipment is reached via the *Shipments* table or *Shipping Ops*, not by drilling into a batch.

## 5. Coverage map — design vs. existing

For every existing dashboard surface, classify whether the new design covers it:

| Existing surface | New design coverage | Migration class |
|---|---|---|
| Batch list (cross-batch) | `dashboard` page + `shipments` page | **covered** (shipment-centric pivot) |
| Batch detail Overview tab | `dashboard-page.jsx` summary cards | **covered** at the dashboard level, not at batch-detail level |
| Documents tab | `Estrella Document Suite.html` + estrella-docs JSX | **covered** but as a separate viewer, not a batch-tab |
| DHL / Customs tab | `dhl` page (functional) | **covered** |
| Warehouse tab | `inventory` page | **partial** (different model — 2-stage inventory page is broader scope) |
| Sales tab | `accounting` page | **partial** |
| PZ / wFirma tab | `accounting` page (PZ + wFirma merged) | **partial** |
| Timeline tab | `shipment-detail-page.jsx` timeline section | **partial** |
| Intelligence tab | `intelligence` page | **covered** |
| Proposals tab | `proposals` page (cross-batch) | **covered** |
| **DHL Express tab (W-2.1+a / W-2.2 / W-2.3)** | `shipping` page | **UNSAFE** — see §8 |
| Customer Statements (read-only) | not present | **missing** |
| Proforma Drafts (read-only) | not present | **missing** |
| Broker Followups (read-only) | not present | **missing** |
| Cross-batch Action Proposals page | `proposals` page | **covered** |
| Closure-confirm card | not present | **missing** (carries the operator-facing closure approval flow) |
| Agency docs received card | partial in `dhl` page | **partial** |
| DHL docs received card | partial in `dhl` page | **partial** |
| wFirma reservation preview | not directly present | **missing** |
| Customer statement drawer | not directly present | **missing** |

## 6. Existing functions that must not break

These are operator-critical surfaces that have already shipped, are tested, and have audit trails. Any migration that loses them is a regression:

1. **PZ generation flow** (`/api/v1/execute/pz_generate` etc.) — the entire reason this product exists.
2. **Closure confirm flow** — the closure-confirm guard (W-7 / B1.b restored its contract).
3. **W-7 dashboard test debt repaired** — 875 → 1032 dashboard tests; this is the *trust layer*.
4. **DHL Express read-only overview + timeline + label evidence** (W-2.1, W-2.1a, W-2.2) — operator-visible "DHL Express" wording locked in.
5. **DHL Express proposal panel + confirmation drawer for 3 simple actions** (W-2.3) — first carrier write surface; behind actor validation + irreversible cancel warning.
6. **Cross-batch read-only pages** — Action Proposals, Broker Followups, Customer Statements, Proforma Drafts.
7. **DHL / Customs flow** — agency docs upload, DHL docs upload, scan inbox, build & send reply.
8. **wFirma proforma → WDT conversion** — already-live workflow (memory: PROF 94/2026 → WDT 84/2026 sequence).
9. **Customs/PZ engine** — `make verify` 160/160 must remain intact.
10. **Lane-serialization, ADR append-only, governance OS** (`.claude/**`) — frozen per the stabilization-window posture.

Any phase that touches dashboard.html must end with these gates green:
- `make verify` 160/160
- carrier+DHL backend suite 1205/1205
- dashboard suite **at least** 1032/1032 (count must not decrease)

## 7. Endpoint compatibility map

The new design references endpoints; the existing backend exposes them. Coverage check on a sample of high-value flows:

| New design page | Endpoint(s) it implies | Backend status |
|---|---|---|
| `dashboard` | `/dashboard/batches?all=1` | exists (existing dashboard uses it) |
| `shipments` | `/dashboard/batches?all=1` | exists |
| `dhl` | `/api/v1/dhl-readiness/{batch_id}`, `/api/v1/dhl-documents/{batch_id}/upload`, `/api/v1/agency-documents/{batch_id}/upload`, scan-inbox routes | all exist (already wired) |
| `accounting` | `/api/v1/wfirma/*`, `/api/v1/proforma/*`, `/api/v1/sales/*`, PZ engine routes | all exist |
| `inventory` | `/api/v1/warehouse/*`, `/api/v1/inventory/*` | exist (some surfaces partial) |
| `proposals` | `/api/v1/action-proposals/*`, `/api/v1/carrier/proposals/*` | both exist |
| `intelligence` | `/api/v1/intelligence/*`, `/api/v1/learning/*` | exist |
| `automation` | `/api/v1/agents/*`, `/api/v1/ai-bridge/*` | exist |
| **`shipping` (Shipping Ops)** | **none — the design explicitly marks every action chip as "Backend pending" / "API required" / "Carrier approval required"** | **does not exist** — would require multi-carrier backend that violates scope |
| `email_queue` | various email queue routes | partial |
| `reports` | `/api/v1/reports/*`, `/api/v1/analytics/*` | partial — wireframe-grade |
| `master` | `/api/v1/wfirma/products/*`, `/api/v1/master/*` | partial |
| `coverage` | none — pure documentation | n/a |
| `admin` | `/api/v1/admin/*`, `/api/v1/system/*` | partial |

**Single most-incompatible page: `shipping`.** The shipping-ops page renders disabled buttons with chips like "Carrier approval required" — the design itself acknowledges no backend exists and FedEx/UPS would require non-existent multi-carrier infrastructure.

## 8. DHL Express-only constraint check

The operator's policy (recorded across W-2.1a + W-2.2 + W-2.3 commits): **Polish DHL Express / MyDHL API only. No FedEx, no UPS, no multi-carrier UI.**

The new design contains the following violations:

| File | Violations | Severity |
|---|---|---|
| `shipping-ops.jsx` | 9 occurrences (FedEx IP, FedEx Priority, UPS Express, etc.); the *entire page* is a multi-carrier wireframe | **P0 — entire page is out of scope** |
| `Estrella Dashboard.html` (page subtitle) | "Carrier shipment & label operations — DHL Express · FedEx · multi-package · print queue · returns. Wireframe only" | P0 — copy implies multi-carrier |
| `pages-v2.jsx` | 5 occurrences | P1 |
| `master-page.jsx` | 5 occurrences (master-data lists with FedEx accounts) | P1 |
| `dashboard-page.jsx` | 4 occurrences (sample shipment-table rows show FedEx as carrier in dummy data) | **P1 — would surface in operator view as fake FedEx shipments** |
| `client-kyc-and-consignment.jsx` | 3 occurrences (FedEx account number field on the KYC form) | P1 — implies multi-carrier client onboarding |
| `modals.jsx` | 2 occurrences | P2 — likely sample data in modals |
| `wireframe-update.jsx` | 2 occurrences | P2 |
| `Estrella Document Suite.html` | 1 occurrence (`options=["DHL","FedEx","UPS"]`) | P1 — multi-carrier select option |
| `pages.jsx` + main HTML | 1 each | P2 |

**Findings:** the *entire `shipping` page* and *all sample data carrying FedEx/UPS rows* must be filtered out before any of this design can land. That eliminates the majority of `shipping-ops.jsx` (669 lines) and substantial chunks of `dashboard-page.jsx`, `master-page.jsx`, `client-kyc-and-consignment.jsx`.

The existing W-2 carrier UI (DHL Express tab) is **not** mirrored in the new design — the new design's only carrier-facing surface is the multi-carrier `shipping` page, which we cannot adopt. This means **migrating the new design *replaces* the carrier subsystem with nothing** unless we explicitly keep the W-2 tab alive.

## 9. UI migration risk table

| Risk | Severity | Why |
|---|---|---|
| **Multi-carrier scope leak** | **P0** | New design assumes DHL+FedEx+UPS. Most affected page (`shipping`) is wireframe-only and out of scope. |
| **Loss of W-2.1+a / W-2.2 / W-2.3 surfaces** | **P0** | New design's `shipping` page does not mirror our DHL Express tab. Replacing dashboard.html wholesale would drop a tested write surface (proposal drawer, irreversible cancel warning). |
| **Test trust layer regression** | **P0** | 1032 dashboard tests pin specific testids, copy, endpoint references. Wholesale replacement = mass test invalidation. The W-7 stabilization win would be undone. |
| **Navigation paradigm shift (batch-tabs → sidebar)** | **P1** | Operator muscle memory rebuilt. PZ flows currently live under `BatchDetailPage > PZ / wFirma`; in new design they live under top-level `accounting`. |
| **Closure-confirm flow loss** | **P1** | New design has no closure-confirm card. The W-7 / B1.b execution-guard contract (closure_confirm body must include `payload: {}`, `approved_by`, `loadBatchReadiness` refresh) does not have a place in the new design. |
| **Sample-data leakage to operator view** | **P1** | If sample arrays in `dashboard-page.jsx` ship as-is, operators see fake FedEx shipments. Sample data must be replaced with real fetches BEFORE the page renders. |
| **Wireframe pages with "API required" chips** | **P1** | The design carries placeholder chips ("Backend pending", "Carrier approval required"). If operators see these, they may attempt to act and discover dead buttons. |
| **wFirma + proforma + master data merged into single "Accounting" page** | **P2** | Existing dashboard.html separates these concerns. Merging may simplify or may bury features. Needs UX review against current operator flow. |
| **Stabilization-window posture** | **P2** | The cell is in stabilization. Migrating an entire dashboard now contradicts the explicit "no implementation campaign without operational evidence" rule. |
| **Build pipeline change** | **P3** | New design uses Babel-standalone served from unpkg (acceptable for current dashboard.html shape). Some imports may need restructuring. |

## 10. Safe migration phases (proposed)

If the operator approves migration despite the above risks, the **only safe path** is incremental, behind feature gates, with sample-data replacement upstream of any operator-facing render. The proposed phasing:

### Phase UI-1 — visual shell only (highest-safety, smallest)

| Field | Value |
|---|---|
| **Touches** | `service/app/static/dashboard.html` only — adopts `tokens.css` colour tokens and font import; no markup change |
| **Endpoints used** | none (CSS-only) |
| **Tests added** | source-grep that `--accent` / `--bg` / `--text` token map is present; existing dashboard tests must remain green |
| **Risk** | low — visual tokens only |
| **Rollback** | revert single commit |
| **Stop condition** | dashboard suite remains 1032+; visual tokens applied |
| **Out of scope** | any layout change; any sidebar; any new page |

### Phase UI-2 — read-only panels (port specific cards)

| Field | Value |
|---|---|
| **Touches** | `service/app/static/dashboard.html`; new component-style sections for cards already present in design (e.g., `PageHeader`, `Btn`, status badges) |
| **Endpoints used** | only existing endpoints already in dashboard.html |
| **Tests added** | per-component testid pinning |
| **Risk** | low — read-only |
| **Rollback** | revert |
| **Stop condition** | per-card source-grep tests green; existing tests unaffected |
| **Out of scope** | sidebar navigation; multi-carrier; any new page |

### Phase UI-3 — DHL Express panels (preserve W-2 surfaces)

| Field | Value |
|---|---|
| **Touches** | `service/app/static/dashboard.html` only |
| **Endpoints used** | the DHL Express endpoints already wired in W-2.1+a / W-2.2 / W-2.3 (no new ones) |
| **Tests added** | preserve all 157 W-2 tests; add visual-token-conformance tests |
| **Risk** | medium — touches our most-recent ship |
| **Rollback** | revert |
| **Stop condition** | all 157 W-2 tests green; visual update applied |
| **Out of scope** | adopting the new design's `shipping` page (multi-carrier) — **explicitly forbidden** |

### Phase UI-4 — write actions (high-risk; only after W-2 fully closed)

| Field | Value |
|---|---|
| **Touches** | `service/app/static/dashboard.html` only |
| **Endpoints used** | existing write surfaces only — no new endpoints |
| **Tests added** | confirmation-drawer parity for any new write surface |
| **Risk** | high — first non-W-2 write surface adopted from the new design |
| **Rollback** | revert |
| **Stop condition** | new tests green; existing 1032 dashboard tests + 1205 carrier+DHL + 160 verify all green |
| **Out of scope** | live-prod cutover (independent — DL-Hx territory); any flag flip |
| **Required first** | sandbox-shadow operational evidence per stabilization-window posture |

### Phase UI-5 — cleanup

| Field | Value |
|---|---|
| **Touches** | `service/app/static/dashboard.html`; `service/tests/test_dashboard_*.py` (test refactor only) |
| **Endpoints used** | none (cleanup) |
| **Tests added** | none (consolidate existing) |
| **Risk** | low |
| **Rollback** | revert |
| **Stop condition** | net file size reduction; tests still green |
| **Out of scope** | adding any new behaviour |

### Phases that should NOT exist

- **No phase for the `shipping` page.** Multi-carrier; out of scope.
- **No phase for FedEx/UPS sample data.** Drop entirely.
- **No phase for client KYC FedEx account fields.** Drop.
- **No phase for `Master Data` FedEx-account entries.** Drop.

## 11. Tests required per phase

| Phase | Required new tests | Required preserved tests |
|---|---|---|
| UI-1 | `test_dashboard_brand_tokens.py` — assert tokens present, colour values match design's `--accent` / `--bg` / etc. | all 1032 dashboard tests; 1205 carrier+DHL; 160 verify |
| UI-2 | per-card pinning (`test_dashboard_<card>_v2.py`) — 1 file per ported card | all 1032 + 1205 + 160 |
| UI-3 | visual-token tests on the DHL Express tab; preserve all 157 W-2 tests | 157 W-2 + 1032 + 1205 + 160 |
| UI-4 | `test_dashboard_<surface>_writes.py` per write surface — confirmation-drawer parity, actor validation, irreversible warning, refresh hooks | all of the above + new |
| UI-5 | source-grep that no orphaned testids remain; no stale routes (`test_route_audit_zero_stale` must pass) | all of the above |

**Cross-phase invariant** (every phase): no new `/api/v1/carrier/actions/create-shipment/execute` reference (W-2.3b territory); no FedEx/UPS substrings in any operator-visible copy; no flag flip.

## 12. Final recommendation

```
═══════════════════════════════════════════════════════════════════
  RECOMMENDATION — New Estrella Dashboard design migration
  Date:     2026-05-10
  Baseline: c2a704e
═══════════════════════════════════════════════════════════════════

  Migrate?                             PARTIAL — reject unsafe parts.

  Reject (explicitly out of scope):
    - shipping-ops.jsx (entire page) — multi-carrier wireframe.
    - All FedEx / UPS sample data.
    - FedEx account fields in client-kyc-and-consignment.jsx.
    - Estrella Document Suite carrier select with FedEx/UPS options.

  Accept conditionally (subject to UI-1..UI-5 phasing above):
    - Visual tokens (tokens.css colour palette, fonts).
    - PageHeader / Btn / status-badge components (style alignment).
    - Read-only cards that map cleanly to existing endpoints
      (DHL / Customs page, accounting page, intelligence page,
      proposals page).
    - Sample dashboard / shipments table CSS, NOT sample data.

  Defer (revisit only after stabilization-window evidence):
    - Sidebar navigation paradigm shift.
    - Merging PZ + Sales + wFirma + Master + Audit into one page.
    - Inventory 2-stage redesign.
    - Email queue page.
    - Reports page.
    - Coverage Matrix.

  Hard preserve (must NOT regress through migration):
    - W-2.1 + W-2.1a + W-2.2 + W-2.3 carrier surfaces.
    - 1032 dashboard test pass count.
    - 1205 carrier+DHL test pass count.
    - 160/160 make verify.
    - DHL Express wording lock (no generic 'Carrier' regressions).
    - Closure-confirm execution-guard contract.
    - Lane-serialization rule, governance OS, append-only ADRs.

  Recommended first phase if migration opens:
    UI-1 — visual shell only.
    Single commit; CSS-only; zero markup change; rollback trivial.

  Open this campaign only if:
    1. Operator explicitly approves rejecting `shipping-ops.jsx`
       and all FedEx/UPS sample data.
    2. Operator explicitly approves PARTIAL migration (not wholesale
       replacement).
    3. Operator confirms the stabilization-window can absorb a small
       UI-1 visual-only commit, OR explicitly opens the migration
       campaign as a successor to the stabilization window.

  Otherwise:
    Cell remains at rest at c2a704e. Design bundle is recorded for
    reference. No migration scheduled.

  Signed:    Coordinator (this artifact)
  Reviewers: UI/UX Planner, Backend Architect, Route/API Mapper,
             Operator Safety, Security, QA Lead, Gap Hunter
             (all Coordinator-simulated this session)

═══════════════════════════════════════════════════════════════════
```

## Self-review notes

- **What this analysis catches:** the FedEx/UPS leak across 11 design files (which would have shipped silently into operator view if the design were accepted wholesale), the navigation paradigm shift, the missing closure-confirm flow, and the test-trust regression risk.
- **What this analysis cannot decide:** whether the operator wants the navigation paradigm shift at all. That's a judgement call that requires real operational evidence on the existing dashboard before we redesign navigation.
- **Where parallel sub-agent activation is recommended in a future implementation campaign:** UI-3 (touches W-2 surfaces — Operator Safety + QA Lead must spawn for real) and UI-4 (first new write surface — Operator Safety + Backend Architect + Security spawn for real).
- **Drift from PRE-IMPL audit norms:** none. This artifact follows the existing template (Section 0..12 numbered, signed recommendation in Section 12, self-review at the end).
