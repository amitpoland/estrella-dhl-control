# Dashboard Authority Comparison — decision artifact (factual only)

**Date:** 2026-07-05 · **Purpose:** three-way Dashboard render for the operator's authority-of-record ruling. Factual differences only — no recommendation, no implementation, no rebuild.

**Composite image:** `reports/wave3/cp3/dashboard-authority-comparison.png` (three panels, same 1440-wide viewport, full-page).

## The three versions

| # | Version | Source rendered | Component |
|---|---|---|---|
| 1 | **Pinned authority** | `docs/design/estrella-dashboard-wireframe.html` (sha256 `f7dd5e38…`), default `/dashboard` screen | its bundled **DashboardKanban** |
| 2 | **Repo component design** | `service/app/static/v2/dashboard-page.jsx` (live-mounted at `/shipments`; identical component in the design bundle) | **DashboardPage** |
| 3 | **Current live at HEAD** | `http://…/v2/dashboard` | **DashboardKanban** (`service/app/static/v2/dashboard-kanban.jsx`) |

Note: version 1 (pinned wireframe) and version 3 (live) are the **same component family** (DashboardKanban); version 2 (DashboardPage) is a **different component**. dashboard-page.jsx exists in the live repo but is mounted at `/shipments`, not `/dashboard`.

## Factual differences

| Aspect | 1 — Pinned wireframe (DashboardKanban) | 2 — dashboard-page.jsx (DashboardPage) | 3 — Live HEAD (DashboardKanban) |
|---|---|---|---|
| **Layout structure** | Vertical stack: CTA strip → KPI strip → kanban board | Vertical stack: summary-card grid → filter row → shipment **table** | Vertical stack: CTA strip → KPI strip → kanban board → "How this works" footer; live `OperationalStatusStrip` above (via TopBar) |
| **Columns** | Kanban: **6 lanes** — New/Drafting · Awaiting Documents · Customs Clearance · Ready to Ship · In Transit · Delivered/Done (generic shipping) | Table: **~10 columns** — AWB · carrier · DHL status · SAD status · MRN · PZ status · net · gross · duty · overall (+ row action menu) | Kanban: **6 lanes** — New/Drafting · Awaiting Documents · Customs Clearance · **Ready for PZ · PZ Generated · Exported** (PZ workflow) |
| **Panels** | "Start a workflow" (4 CTA cards); KPI strip; Pipeline board | Summary-cards grid (`repeat(6,1fr)`, incl. 2 wide value cards); overall-status filter chips; sortable table | "Start a workflow" (4 CTA cards); KPI strip; Pipeline board; "How this works" panel; live health strip |
| **KPI treatment** | **5 tiles**: Active shipments · Urgent · Inbound · Outbound · Total value (€K) | **6 summary cards** (centered stats, as rendered live): Total Shipments · Success · Partial · Blocked · SAD Present · PZ Confirmed. (design-bundle variant: Total Shipments · Awaiting DHL · Awaiting SAD · Ready for PZ · Verification Needed · Ready for Booking · Total Duty A00 · Total Gross — same treatment, different labels) | **5 tiles**: Active · Urgent · Awaiting DHL · Awaiting SAD · Ready for booking |
| **Activity / feed treatment** | 6-lane **kanban**; cards carry client name · age · IN/OUT · carrier · awb · docs (n/4) · value+currency · flag · priority | **No kanban/feed** — a single sortable/filterable **table** (one row per shipment) | 6-lane **kanban**; cards carry short batch id · age · carrier · inv count · net value · urgent/high flag (leaner than v1: no client name, no per-card doc-count/currency) |
| **Buttons / actions** | 4 quick-flow CTAs (Receive shipment · Create outbound shipment · Scan email · Customer order); "Drag cards between lanes"; card → detail | Overall filter chips (all · Ready for PZ · Awaiting DHL · …); column sort; per-row action menu; row → detail | 4 quick-flow CTAs (Receive shipment · New shipment · Scan DHL inbox · Generate PZ); Search (⌘K); List view; card → detail |
| **Data source assumptions** | **MOCK** — hardcoded `PIPELINE_SHIPMENTS` (luxury client names) | **LIVE as rendered** — the live `/shipments` mount reads real batches (273 rows shown). The design-bundle `dashboard-page.jsx` counterpart uses hardcoded `MOCK_SHIPMENTS` (same layout, mock data) | **LIVE** — `GET /api/v1/dashboard/batches` (`PzApi.listBatches`); empty lanes render "—" |

## Deltas at a glance

- **1 vs 3** (same kanban family): different KPI set (Inbound/Outbound/Total-value vs Awaiting-DHL/SAD/Ready-for-booking); different lane labels (generic shipping vs PZ workflow: Ready-for-PZ/PZ-Generated/Exported); richer cards in 1 (client/docs/currency/priority) vs leaner in 3 (batch-id/carrier/inv/net); 3 adds a live health strip, "How this works", Search + List-view; data mock (1) vs live (3).
- **2 vs 1/3**: fundamentally different layout — summary-cards + sortable table (no kanban/feed) vs CTA + KPI + kanban; 6 centered summary cards vs 5 KPI tiles; filter chips + column sort + row action menu vs quick-flow CTAs + drag-lanes. Data: version 1 mock; versions 2 (as rendered) and 3 live.

## Authority-of-record options (operator to choose — no recommendation given)

- **A** = pinned HTML governs (version 1).
- **B** = JSX component design governs where it conflicts (version 2, dashboard-page.jsx).
- **C** = current implementation accepted as authority for Dashboard (version 3).

HOLD for the operator's ruling. The chosen authority will then be applied consistently to the remaining unfinished pages only.
