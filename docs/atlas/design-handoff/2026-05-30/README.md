# Atlas Design Handoff — Preserved Artifacts (2026-05-30)

## Context and provenance

These files were salvaged on 2026-06-04 from a **quarantined broken working tree**
(`C:\Users\Super Fashion\PZ APP`) before that tree was cleaned.

The source tree had become unusable during a customs-engine fix session on 2026-06-04:
a failed `git rebase origin/main` left its index in a conflicted state with orphaned
remote changes staged (UU: `routes_proforma.py`, `inbox-page.jsx`, `proforma-list.jsx`).
The tree was quarantined — no deployments or merges may originate from it.

All files here were **untracked** in the broken tree (not in any commit, not on any PR
at the time of salvage) and therefore would have been permanently lost by a `git clean -fd`.

Authority note: **these are design inputs and audit records, not production authority.**
No file in this directory automatically changes system behaviour. Each file must be
evaluated and its decisions implemented deliberately in a future sprint.

---

## File inventory

### Design specifications (inputs for upcoming Atlas/proforma work)

| File | Size | Summary |
|------|------|---------|
| `ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md` | 15 KB | Full specification for wFirma-style proforma drilldown redesign. Navigation model, three-card layout (Sprzedawca / Nabywca / Odbiorca), action toolbar, tab strip, component breakdown. Foundation doc for the next proforma sprint. |
| `ATLAS_PROFORMA_NEW_DRAFT_AND_CONVERT.md` | 22 KB | Two-phase task spec: Phase 1 investigation report (backend routes, DB schema, frontend wiring for proforma draft lifecycle + wFirma convert-to-invoice), Phase 2 build plan. Contains file:line citations for current backend state. |

**Duplication note**: both of the above also exist inside
`design-bundle/estrella-dashboard/project/uploads/` (byte-identical copies, 15497 and
22175 bytes respectively). The root copies here are the canonical version for quick
access; the uploads copies are part of the design bundle's native structure.

### Workflow and architecture audit records

| File | Size | Summary |
|------|------|---------|
| `ATLAS_WORKFLOW_VERIFICATION_REPORT.md` | 18 KB | End-to-end verification of all WF1–WF4 transitions (26 transitions: 17 VERIFIED, 6 PARTIAL, 1 WRONG AUTHORITY, 1 MISSING). Critical authority document for all future Atlas workflow development. T3.4 WRONG AUTHORITY (duplicate blocking-reason logic) and the IB.3 MISSING (bulk inbox actions) are actionable bugs. |
| `REALITY_AUDIT.md` | 3 KB | P1–P26 problem list — anchor document for the three-part frontend reality audit. Defines 19 audit pages, verdict vocabulary (LIVE/WIRE/BUILD/HIDE/DELETE/FAKE), calibration notes. Source tree: Mac. |
| `REALITY_AUDIT_FINAL.md` | 9 KB | Consolidated final audit report: Phase A (data-quality, P10–P23 verdicts with source evidence) + Phase B (BUILD/architectural, P8/P12/P13/P17/P25). 8 problems REFUTED, many CONFIRMED. Phase C (gated remediation) awaiting authorization. |
| `REALITY_AUDIT_PART2.md` | 20 KB | Part 2 authenticated render verification on live production instance. Confirms render reality for dashboard.html and documents-v2.html. Cross-page source sweep. 15-page coverage matrix. |

### Governance record

| File | Size | Summary |
|------|------|---------|
| `SCRATCH-TREE-RETIRED.md` | 2 KB | Written by a prior session on 2026-06-04. Explicitly marks `C:\Users\Super Fashion\PZ APP` as a retired scratch clone, documents the canonical path convention (`C:\PZ-verify` = canonical, `C:\PZ` = production, broken tree = retired), and explains why commands from that tree produced false signals. Provenance record for the quarantine decision. |

### Prototype HTML

| File | Size | Summary |
|------|------|---------|
| `shipment-detail-v3.html` | 37 KB | V3 rebuild of the shipment detail page using Atlas design bundle tokens (DM Serif Display + Plus Jakarta Sans, CSS custom properties). Self-contained — does **not** load `dashboard-shared.js` or reuse old shared components. Candidate for the Atlas Step 7 reskin (customer-master-v2 + pz-design-v2.js integration). |

### Agent performance scorecard

| File | Size | Summary |
|------|------|---------|
| `scorecard-2026-05-30-pr-board-clear-and-step5.md` | 6 KB | Agent performance scorecard for the 2026-05-30 PR board clear + Step 5 design shell campaign. Per-agent scores (NEEDS-TUNING: integration-boundary, deployment-windows-ops). Required by CLAUDE.md RULE 6 to be visible and cited. |

### Design bundle (Claude Design handoff)

| Directory | Files | Size | Summary |
|-----------|-------|------|---------|
| `design-bundle/` | 61 files | ~7.5 MB | Full Claude Design handoff bundle exported from claude.ai/design. Contains JSX component files, HTML prototypes, design tokens, and uploaded assets. See sub-inventory below. |

**Design bundle sub-inventory:**

```
design-bundle/estrella-dashboard/
  README.md                                     Instructions for implementing from the bundle
  project/
    Estrella Dashboard.html                     Primary design prototype (34 KB)
    Estrella Dashboard Standalone.html          Self-contained version (1.6 MB)
    Estrella Document Suite.html                Document suite prototype (10 KB)
    Estrella Document Suite Standalone.html     Self-contained (1.7 MB)
    Estrella Dashboard-print.html               Print layout (35 KB)
    pages.jsx                  67 KB            Page components (v1)
    pages-v2.jsx               75 KB            Page components (v2)
    ops-cell.jsx               54 KB            Ops cell component
    inventory-page.jsx         77 KB            Inventory page
    ledgers-page.jsx           47 KB            Ledgers page
    shipment-detail-page.jsx   43 KB            Shipment detail (current)
    shipment-detail-page.v1.jsx 23 KB           Shipment detail (v1)
    shipment-detail-page.v2.jsx 35 KB           Shipment detail (v2)
    proforma-detail.jsx        24 KB            Proforma detail component
    proforma-list.jsx          11 KB            Proforma list component
    accounting-hub.jsx         33 KB            Accounting hub
    documents-hub.jsx          29 KB            Documents hub
    inbox-page.jsx             17 KB            Inbox page
    carriers-page.jsx          35 KB            Carriers page
    client-kyc-and-consignment.jsx 31 KB        Client KYC + consignment
    global-search.jsx          12 KB            Global search
    master-page.jsx            29 KB            Master page
    dashboard-page.jsx         12 KB            Dashboard page
    dashboard-kanban.jsx       17 KB            Kanban dashboard
    shipping-ops.jsx           40 KB            Shipping ops
    api-status-page.jsx        27 KB            API status page
    modals.jsx                 20 KB            Modal components
    components.jsx             23 KB            Shared components
    tweaks-panel.jsx           18 KB            Tweaks panel
    wireframe-update.jsx       31 KB            Wireframe updates
    estrella-docs/             subtree          Document renderers (CMR, proforma, statement, email, xlsx)
    uploads/                   subtree          Source docs + screenshots + ATLAS_PROFORMA copies
```

---

## What to do with these files

These files are **design inputs and audit records**. The correct flow:

1. **ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md** — Read before starting the proforma drilldown sprint. It is the task spec.
2. **ATLAS_PROFORMA_NEW_DRAFT_AND_CONVERT.md** — Phase 1 investigation report is inside. Read before writing any proforma draft/convert code.
3. **ATLAS_WORKFLOW_VERIFICATION_REPORT.md** — Consult before any WF1–WF4 work. The T3.4 blocking-reason authority finding is an open bug.
4. **REALITY_AUDIT_FINAL.md** — The Phase C remediation list. Requires operator authorization before acting on any BUILD item.
5. **shipment-detail-v3.html** — Candidate for Atlas Step 7 reskin; needs operator approval to promote to `service/app/static/`.
6. **design-bundle/** — Input for implementing the next Atlas sprint. Read `design-bundle/estrella-dashboard/README.md` first.
7. **scorecard** — Must be cited in PROJECT_STATE.md FACTS per CLAUDE.md RULE 6.

None of these files modify production behaviour automatically. All implementation
decisions require explicit operator instruction.
