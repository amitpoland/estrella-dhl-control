# Accounting Authority Comparison — decision artifact (factual only)

**Date:** 2026-07-05 · **Purpose:** Accounting is the one remaining page with an authority conflict (per the continuous-port rule). Factual differences only — no recommendation, no implementation, no rebuild.

**Composite image:** `reports/wave3/cp3/accounting-authority-comparison.png` (two panels, same 1440 viewport, full-page).

## The two versions

| # | Version | Source rendered | Component |
|---|---|---|---|
| 1 | **Pinned wireframe** | `docs/design/estrella-dashboard-wireframe.html` (f7dd5e38), Accounting screen | wireframe Accounting **Overview** |
| 2 | **Current live at HEAD** | `http://…/v2/accounting` | **AccountingHub** (`accounting-hub.jsx`) |

**Correction to the porting brief:** the earlier note described the wireframe Accounting as "6 KPI tiles + KSeF panel + KPO tracker." The actual pinned wireframe shows **4 KPI tiles + document-count panels + a document-map diagram** — there is **no KSeF panel and no KPO tracker** in f7dd5e38. (Same class of gap as the Dashboard "two-column cockpit" that was not in the wireframe — stated here as fact, not preference.)

## Factual differences

| Aspect | 1 — Pinned wireframe (Overview) | 2 — Current live (AccountingHub) |
|---|---|---|
| **Default landing** | **Overview** summary screen | **Purchase Ledger** tab (data table) |
| **Left rail** | **Document-type** nav, grouped: Sales Documents (Proforma · Invoice · Credit Note) · Warehouse Documents (WZ · PZ · PW · RW · MM) · Ledgers (Client Balance · Client Ledger · Supplier Ledger) · System (wFirma Sync) | **Workflow-tab** nav: *Wave 3 — Live* (Purchase Ledger · Sales/Proforma · Client Ledger · wFirma Sync · Master Data · Audit Trail) + *Wave 4 — Doc Register* (WZ · PZ · PW · RW · MM, gated) |
| **KPI treatment** | **4 tiles**: Sales Receivable (€33.1K) · Sales Overdue (€1.84K) · Supplier Payable (€18.4K) · Last wFirma Sync (2h ago) | **4 tiles**: Total Batches (273) · In Progress (273) · Completed (0) · Synced to wFirma |
| **Panels** | "Sales documents · April 2026" (Proforma 12 · Invoices 28 · Credit notes 1 · WZ 18) + "Warehouse documents · April 2026" (PZ 9 · PW 1 · RW 2 · MM 4) + **"Document map"** flow diagram (PI→INV→WZ→PZ→CN) | Single **data table** (Doc No · Date · AWB/Batch · Lines · Net PLN · Gross PLN · Status · wFirma) per active tab |
| **KSeF / KPO** | **Neither present** in the wireframe | Neither present |
| **Buttons/actions** | API Checklist · Sync wFirma · Export (header); left-rail document-type navigation | API Checklist · Sync wFirma · Export (header); tab navigation; per-row View; filter-by-batch |
| **Data source** | MOCK (mapped-from-wFirma copy, hardcoded counts/values) | LIVE — Purchase Ledger from `GET /api/v1/dashboard/batches`; Sales from proforma authority; Client Ledger via wFirma; Audit via `/master/audit` |

## Conflict summary (no recommendation)

- The current build **does realize** parts of the wireframe (header actions, a KPI row, a wFirma-mapped rail with the same WZ/PZ/PW/RW/MM document types), but **lands on a ledger table** rather than the wireframe's **Overview** (KPI + document-count summary panels + document-map diagram), and its rail is organized by **workflow phase** rather than **document type**.
- The wireframe contains **no KSeF panel and no KPO tracker** — those are not a porting target from f7dd5e38.

Options for the operator's ruling on Accounting (same A/B/C frame):
- **A** = pinned wireframe governs → add the Overview landing (4 KPI + doc-count panels + document-map) and document-type rail.
- **C** = current AccountingHub accepted as authority-of-record (workflow-tab + Purchase-Ledger-first, live data).
- **Hybrid** = keep the live tabs, add the wireframe's Overview as the landing tab.

HOLD on Accounting only. Every other page is resolved (Dashboard/Documents Hub/Proforma/Shipment Detail accepted canonical); the campaign is not blocked on this page.
