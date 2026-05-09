# Wireframe Brief — Estrella PZ Operational Dashboard

**Date:** 2026-05-03
**Audience:** Claude Design (or any designer producing low-fidelity wireframes)
**Output expected:** Wireframes for 9 screens (WF-01 → WF-09)
**Format:** Low-fidelity is fine. Figma share-link, PNGs, or Sketch — annotated with default / loading / empty / error states.

This brief is **not a redesign mandate**. The dashboard already exists and works. The goal is to lay down a coherent target for screens that today are either backend-only or visually inconsistent — without disturbing what is already operational.

---

## 1. Project context

**Estrella** is an import operations company. The dashboard runs the post-shipment workflow:

```
Intake → Documents → Customs Clearance → PZ Calculation → Warehouse → Sales → wFirma Accounting
```

The system handles every air shipment from supplier → DHL/agency customs clearance → warehouse stocking → sales fulfilment → wFirma reservation → ledger entry. Calculations (landed cost, duty, freight allocation, VAT) happen in a Python engine that is **not in scope** for redesign.

The dashboard's job is to:

1. Show operators the state of every shipment at every stage
2. Surface what is blocking the next step
3. Let operators trigger the next step (send DHL reply, run PZ, create reservation)

The dashboard does **not** sell anything. It is internal-only, used by 3-5 staff.

---

## 2. Audience and non-goals

### Who uses it

- 1 owner / decision maker
- 2-3 ops staff (handle daily shipments, customs replies, warehouse scans)
- Occasional accountant view (wFirma reservation export, audit reports)

### Non-goals

- **Not a SaaS product.** No marketing pages, no public landing, no signup funnel.
- **Not a customer-facing UI.** No external clients log in.
- **Not a visual rebrand.** Existing colors, typography, and branding stay.
- **Not a framework migration.** Dashboard runs as React-in-script inside one large `dashboard.html`. No build step. Wireframes must be implementable in this environment.

---

## 3. Design rules (these are non-negotiable)

1. **Reuse existing classes and visual patterns.** Every existing screen uses `<Card>`, `<Btn>` variants, `<Badge>`, `<Modal>`, and tokenised CSS variables. New screens must reuse these — not introduce a parallel visual system.
2. **Status colors are consistent across the entire app.** Green = ready / clean / success. Amber = warning / partial / blocked-but-fixable. Red = missing / error / failed. Blue = pending / in-progress / informational. Neutral grey = no-data / not-applicable.
3. **Hierarchy on every screen:** summary card(s) at top → gate / status banner → grouped detail cards → compact tables.
4. **Empty, loading, and error states are required.** Never show a blank screen when data is missing. Loading states use the same spinner / skeleton pattern as today.
5. **One primary action per screen.** Secondary actions are outline / ghost. Disabled buttons must show a reason on hover or in inline helper text.
6. **Table-first.** Most operator data is best shown as compact tables. 11 px text, 6×8 px padding, sticky headers.
7. **Avoid heavy visual noise.** No gradients on data rows. Color is information, not decoration.
8. **Mobile-safe.** The dashboard is desktop-first but tables wrap with `flex-wrap` and pages scroll. Existing layout already handles this — do not break it.

---

## 4. Design tokens already in use

These come from `app/static/dashboard.html` and are inherited by every component. Do not introduce new tokens.

### Colors (CSS variables)

| Token | Usage |
|---|---|
| `--card` | Card background |
| `--bg`, `--bg-2`, `--bg-3`, `--bg-subtle` | Page and surface backgrounds |
| `--border`, `--border-subtle` | Borders and table dividers |
| `--text`, `--text-2`, `--text-3` | Primary / secondary / tertiary text |
| `--accent`, `--accent-light`, `--accent-text`, `--accent-subtle`, `--accent-border` | Brand gold |
| `--badge-green-bg/text/border` | Success / ready |
| `--badge-amber-bg/text/border` | Warning / partial |
| `--badge-red-bg/text/border` | Error / missing |
| `--badge-blue-bg/text/border` | Pending / informational |
| `--badge-purple-bg/text/border` | Special / FedEx |
| `--badge-neutral-bg/text/border` | No-data / not-applicable |
| `--shadow`, `--shadow-heavy` | Card and modal elevation |
| `--row-hover`, `--sidebar-bg`, `--sidebar-text` | Layout chrome |

### Typography

- Body: `Plus Jakarta Sans` (400 / 500 / 600 / 700)
- Headings: `DM Serif Display` (used sparingly — only major numerics on Reports page)
- Monospace: `ui-monospace, monospace` (for IDs, hashes, codes, AWBs)
- Sizes in use: 10 (caption), 11 (body small), 12 (body), 13 (section header), 14 (page title)

### Spacing scale

- 4 / 6 / 8 / 12 / 14 / 16 / 18 / 20 / 24 px
- Page padding: `24px 32px 40px`
- Card padding: `14px 18px` (compact) or `20px 24px` (relaxed)

### Border radius

- Pills: 4 px
- Cards: 8 px (small) or 10 px (large)
- Modals: 10 px

---

## 5. Component primitives (reuse only — do not redesign)

| Primitive | Where defined | Variants |
|---|---|---|
| `<Card>` | `dashboard.html` line ~283 | `style` override; `onClick` for clickable cards |
| `<Btn>` | line ~293 | `default` (filled dark), `gold` (accent), `outline`, `ghost`, `danger`, `success`. `small` flag for compact size. |
| `<Badge>` (status) | renders pill from `STATUS_MAP` | small flag |
| `<Modal>` | line ~316 | `wide` flag |
| Compact table | inline in panels (Changes 2/3/4) | `thStyle` + `tdStyle` constants reused |

When in doubt, copy from `Warehouse`, `Sales`, or `wFirma` tabs in `BatchDetailPage` — those are the canonical examples of the design system after Phase 1.

---

## 6. Status badge dictionary (single source of truth)

Use exactly these labels and colors. Do not invent variants.

| Domain | Value | Color | Label |
|---|---|---|---|
| Stock status | `dispatched` | green | "Dispatched" |
| Stock status | `received` | blue | "Received" |
| Stock status | `missing` | red | "Missing" |
| Warehouse hint | `clean` | green | "Clean" |
| Warehouse hint | `partial` | amber | "Partial" |
| Warehouse hint | `empty` | red | "Empty" |
| Warehouse hint | `n/a` | neutral | "—" |
| Sales hint | `present` | green | "Linked" |
| Sales hint | `none` | neutral | "—" |
| wFirma hint | `preview_built` | blue | "Preview" |
| wFirma hint | `none` | neutral | "—" |
| Customer / Product mapping | `true` | green | "Matched" |
| Customer / Product mapping | `false` | amber | "No mapping" |
| Ready flag (row / doc) | `true` | green | "Ready" |
| Ready flag | `false` | amber | "Not ready" |
| Parser / extraction status | `complete` / `ok` / `success` | green | the value, capitalised |
| Parser / extraction status | `pending` / `processing` | amber | the value |
| Parser / extraction status | `failed` / `error` | red | the value |
| Capability flag | `true` | green | "✓ <flag name>" |
| Capability flag | `false` | red | "✗ <flag name>" |
| Capability flag | partial / warn | amber | "⚠ <flag name>" |
| Manual review needed | `true` | red | "Review" |

---

## 7. Wireframes to design

Numbered WF-01 to WF-09. Same numbering as `system_inventory_and_ui_plan.md` Section 5 — keep this for cross-reference.

### WF-01 — New Shipment Intake

**Purpose** — Create a new shipment from scratch
**Primary action** — Enter AWB number → upload Section A files → upload Section B files → upload Section C files → confirm intake
**Sections shown**
- Section A: Shipment / AWB (tracking number is the shipment key)
- Section B: Purchase Documents (invoices, packing list)
- Section C: Sales / Client Documents (sales invoice, packing slip)

**Data per section** — file upload zone, list of uploaded files with type detection, remove button per file, validation messages
**Endpoints used** — `POST /api/v1/shipment`, `POST /api/v1/upload/{batch_id}/upload`
**States to design** — empty (no files), files uploading, files uploaded, validation error, server error
**Edge cases** — duplicate AWB (warn before overwrite), missing required section (block confirm)
**Mobile** — sections stack vertically, file zone full-width
**Priority** — HIGH (current intake is buried in dashboard)

---

### WF-02 — Batch Dashboard (Shipments List)

**Purpose** — Overview of all active shipments, with at-a-glance status
**Primary action** — Click a row → open Batch detail
**Columns (already implemented after Phase 1)**
- AWB / Tracking · Carrier · DHL Status · SAD Status · MRN · PZ Status · Warehouse · Sales · wFirma · Net · Gross · Duty A00 · Overall · Actions
**Filtering & sorting** — Click any column header to sort; status filter pills above table; carrier filter; search by AWB / MRN / doc no.
**States to design** — empty, loading, error, filtered-empty
**Mobile** — table horizontal scrolls; sticky AWB and Actions columns
**Priority** — HIGH (most-used screen — refine, do not redesign from scratch)

**What designers should preserve** — every column today exists for a reason. Focus on:
- Reducing visual noise (the table currently has many badge colors competing)
- Better readable density (current font is 12 px — consider 11 px with more whitespace)
- Cleaner row hover state

---

### WF-03 — Batch Detail (Shipment View)

**Purpose** — Full lifecycle view of one shipment
**Primary action** — Trigger the next step in the workflow (send DHL reply, run PZ, create reservation)
**Tabs (already implemented)**
- Pipeline · Documents · Timeline · Warehouse · Sales · wFirma · Intelligence · Proposals
**Per-tab data** — see `system_inventory_and_ui_plan.md` Section 2 for backend contracts
**States to design** — for each tab: loading, empty, error, with-data
**Mobile** — tabs scroll horizontally; content full-width
**Priority** — HIGH (operator's deepest workflow)

**Designer note** — the Documents tab is now densely packed (Source Files + Generated Outputs + Document Registry). Consider whether the registry should remain inline or move to its own sub-tab.

---

### WF-04 — Document Registry (per-batch)

**Purpose** — Browse and audit all documents registered for a shipment
**Primary action** — Click a row → expand to show extracted fields
**Data shown per row** — filename · type · parser status · extraction status · review needed · hash · created at · field count
**Expanded row shows** — list of extracted fields with field_name · normalized_value · confidence · verified_status
**Endpoints used** — `GET /api/v1/upload/shipment/{batch_id}/documents`
**States** — empty, loading, error, with-data
**Edge case** — documents with > 50 fields show first 50 and "+ N more"
**Priority** — MEDIUM (already implemented after Phase 2 Item 3 — wireframe needed only if redesign is requested)

---

### WF-05 — Warehouse Scanner Screen

**Purpose** — Scan items in / out of warehouse locations
**Primary action** — Type or paste scan code → select action (RECEIVE / MOVE / DISPATCH / RETURN) → confirm
**Inputs** — scan code (auto-focused), action dropdown, location code input, optional batch override
**Outputs** — live result panel showing scan accepted / rejected, reason on rejection
**History panel** — last 20 scans for this scan code with timestamps
**Endpoints used** — `POST /api/v1/warehouse/scan`, `GET /api/v1/warehouse/inventory/{scan_code}`, `GET /api/v1/warehouse/locations`
**States** — empty (no scan yet), scanning, scan accepted, scan rejected, network error
**Mobile** — primary use case may be phone or handheld scanner. Auto-focus scan input. Large action buttons. Numeric keypad-friendly.
**Priority** — HIGH (page exists at `/dashboard/warehouse.html` but is not mobile-optimised)

---

### WF-06 — Warehouse Audit (per-batch)

**Purpose** — Show why a batch's reservation gate is closed
**Primary action** — Resolve audit issues by going to scanner, then refresh audit
**Sections (already implemented)**
- Completion summary (total / scanned / dispatched / missing / completion %)
- Reservation gate banner (green = open, amber = blocked + reasons)
- Missing scans · Stuck inventory · Invalid flows · Orphan scans
**Endpoints** — `GET /api/v1/warehouse/audit/{batch_id}`
**States** — clean (everything green), partial (some issues), broken (critical issues), loading, error
**Priority** — MEDIUM (already implemented; wireframe only if redesign is requested)

---

### WF-07 — Sales Linkage / Reservation Preview

**Purpose** — Show how sales documents map to packing lines and what wFirma will receive
**Primary action** — Confirm reservation preview (when ready_to_create is true)
**Two-stage view** (already implemented as Sales tab + wFirma tab):
- Sales Linkage: per-client cards showing each sales line with stock status
- Reservation Preview: per-document cards showing wFirma payload preview, capability strip, gate banner, disabled "Create Reservation" button
**Endpoints** — `GET /api/v1/sales/linkage/{batch_id}`, `GET /api/v1/wfirma/reservation-preview/{batch_id}`
**Priority** — HIGH (already implemented; wireframe needed only for navigation between Sales and wFirma views)

---

### WF-08 — wFirma Setup & Mapping (NEW)

**Purpose** — Configure wFirma credentials, map customers, map products
**Primary action** — Add or edit a customer / product mapping → save
**Sections**
- Capability strip (3 pills from `GET /api/v1/wfirma/capabilities`)
- Diagnostic helper showing config readiness with `blocking_reasons`
- Customer mapping table — client name, wFirma ID, VAT ID, country, match status, edit button
- Product mapping table — product code, wFirma ID, Polish name, unit, VAT rate, sync status, edit button
**Filters** — match_status / sync_status: all / matched / pending / missing
**Add / edit UX** — modal dialog (matches existing dashboard pattern)
**Endpoints** — `GET /api/v1/wfirma/capabilities`, `GET / PUT /api/v1/wfirma/customers`, `GET / PUT /api/v1/wfirma/products`
**States** — credentials missing (blocked banner), credentials set but mappings empty, mappings populated, edit modal open, save in progress, save error
**Priority** — HIGH (gating Phase 3 wFirma live integration)

**Important constraint** — this screen does NOT call live wFirma. It only updates the local mapping DB. The actual reservation creation is gated by `python3 -m app.tools.check_wfirma_config` being green.

---

### WF-09 — Admin / System Health

**Purpose** — Operator view of system health, credentials, storage, diagnostics
**Sections (Phase 1 polish already added 3 cards at top of AdminPage)**
- Version (commit hash + deploy timestamp)
- Health (12 checks summary + expandable list)
- Storage (real / test / quarantine / locks counts + raw JSON)
- (existing) User Management link
- (existing) Email Queue stats
**Endpoints** — `GET /api/v1/system/version`, `GET /api/v1/debug/health-full`, `GET /api/v1/debug/storage/health`, `GET /api/v1/admin/email-queue`
**States** — all loading, partial loaded, all loaded, individual card error
**Priority** — MEDIUM (already implemented; wireframe only if redesign is requested)

---

## 8. Out of scope

Designer should NOT propose changes to:

- `/login`, `/signup`, `/forgot-password`, `/admin-users` — auth flows. These are minimal and stable. Don't touch.
- Internal cron / debug pages (`/api/v1/debug/*`) — not user-facing.
- The static `/dashboard/batch.html` legacy page — being replaced by in-dashboard `BatchDetailPage`. Designs should target the in-dashboard version only.
- Color palette and typography — both established and consistent. Don't propose alternatives.

---

## 9. Hand-off format expected

For each screen:

1. **One annotated wireframe** showing the default state with realistic data
2. **State variants** — at minimum: loading, empty, error. Add others if behaviour is non-trivial (e.g. WF-08 modal open).
3. **Annotations** — every non-obvious UI element annotated with: data source (endpoint), interaction (click / hover / drag), and resulting state change.
4. **Mobile note** — one sentence per screen on how it should reflow on a 375 px viewport.
5. **Priority + effort estimate** — high / medium / low, and a rough size estimate (S / M / L).

Format: Figma share-link with view permission, OR PNGs in a single zip OR a markdown doc with embedded images. Do not deliver as production assets (no Tailwind config, no React component code) — wireframes only.

---

## 10. Glossary

Terms a designer will encounter without context:

| Term | Meaning |
|---|---|
| **PZ** | Polish "Przyjęcie Zewnętrzne" — external receipt document for warehouse stocking |
| **SAD** | Single Administrative Document — EU customs declaration |
| **ZC429** | Polish customs document type, the specific PDF/XML form Estrella receives |
| **AWB** | Air Waybill — shipping tracking number from carrier (DHL, FedEx, etc.) |
| **MRN** | Movement Reference Number — customs declaration ID |
| **DSK** | Polish customs term: "Dokument SAD Korygujący" or self-clearance flag depending on context |
| **DHL Express** | Estrella's primary carrier; their email auto-classification is a major feature |
| **wFirma** | Polish online accounting platform (wfirma.pl) — Estrella's accounting system |
| **Reservation** | wFirma stock reservation document (warehouse_document_r) — created from sales packing lines |
| **Packing line** | A line in the packing list with quantity, design, weight |
| **Sales line** | A line in a sales document (invoice / packing slip) — links to a packing line via SKU / design code |
| **Design code / SKU** | Internal product identifier (e.g. `CSTR07596`) — Estrella sells jewellery, designs are unique |
| **Product code** | Invoice line reference (e.g. `EJL/26-27/015-6`) — the wFirma product symbol |
| **Cliq** | Zoho Cliq — Estrella's internal chat tool, where the bot posts results |
| **WorkDrive** | Zoho WorkDrive — file storage for generated PDFs / XLSX |
| **Cowork** | Claude Cowork — external AI integration for email scanning |
| **Audit gate** | Warehouse audit must be clean before reservation is allowed |
| **Capability flag** | Boolean from `wfirma_capabilities` indicating whether a feature is configured |

---

## Reference

- **Inventory document:** `docs/system_inventory_and_ui_plan.md`
- **Dashboard source:** `service/app/static/dashboard.html`
- **Backend routes:** `service/app/api/routes_*.py`
- **Existing wireframe specs:** Section 5 of `system_inventory_and_ui_plan.md`
