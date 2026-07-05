# Wave-3 CP3 — Operator Live-Review Map

**Server:** http://localhost:60991/v2/index.html (Preview-managed; hash-routed SPA — `#/<slug>`).
> **NOTE (2026-07-04):** port 8135 is held by a kernel zombie socket (dead PID
> 27036, left by a CP3 harness run — cannot be force-cleared from user space,
> self-reaps or clears on reboot). The IDENTICAL live UI is served Preview-
> managed at the URL above (autoPort picked 54494). Launch config `pz-review`
> added to `.claude/launch.json` for stable managed restarts.
**Composites for reference:** this folder, `pair-01`…`pair-38` (wireframe LEFT · live RIGHT).
**How to read:** each row = the exact place to click + the ONE behavior to confirm.
Every cited handler is in the live code at the line given (as of `df1ab135`/CP3 HEAD).

---

## 1. Documents Hub — `#/documents`

| Check | Where | Confirm | Handler |
|---|---|---|---|
| Upload navigates (not the old dead event) | header "↑ Upload Document" | click → URL becomes `/v2/documents`-family target, NOT a silent no-op | real SPA nav (the dangling `inv:upload` CustomEvent was REMOVED, W3-page6b) |
| 3-lane kanban shape | page body | Draft / Approved / Posted columns for PI (+ PZ) | `PiLane` documents-hub.jsx:354; lanes rendered per state |
| Zero dead buttons | each card | every button either acts or is disabled-with-reason | Approve `onApprove=doApprove` :327; Post `onPost=doPostToWfirma` :329 (→ flag-gated routes_proforma:8095); Delete/Unapprove wired; DC-12/13-PZ/14 disabled w/ title (Wave-4) |

## 2. Inventory — `#/inventory` (10-tab strip)

| Check | Where | Confirm | Handler |
|---|---|---|---|
| All tabs open | tab strip | each of the 10 tabs renders (empty states honest — dev storage is empty) | `INV_TABS` + tab render switch |
| Temp Warehouse vs Final Stock DISJOINT | those two tabs | a piece appears in exactly ONE — assigned→Final, unassigned→Temp | shared predicate `isAssigned(item)` inventory-page.jsx:2977 (R-Q4: `current_location` non-empty) |
| Export downloads | header "↓ Export" on a tab with rows | click → CSV file downloads of the active tab's rendered rows | `reportExport` bridge (tabs feed header, e.g. :978-991); disabled+titled when the tab has no rows |
| Upload navigates | header "↑ Upload Document" | click → documents hub | `navigateToDocuments()` inventory-page.jsx:4875 (pushState + popstate) |

## 3. Accounting — `#/accounting` (6 live tabs + 5 gated)

| Check | Where | Confirm | Handler |
|---|---|---|---|
| 6 tabs present | left rail | Purchase Ledger · Sales/Proforma · Client Ledger · wFirma Sync · Master Data · Audit Trail | `acc-rail-*` buttons, accounting-hub.jsx:118 |
| No duplicate authority | Client Ledger / Master Data / wFirma Sync | Client Ledger EMBEDS the existing LedgersPage; Master Data + wFirma Sync NAVIGATE out (no re-implementation) | LedgersPage embed; `onNav('master')` :625, `onNav('wfirma_setup')` :535 |
| No fake widget | every tab | live data or honest empty/error; gated WZ/PZ/PW/RW/MM visibly disabled (W4) | KPIs derived from live reads; `tab-gated-*` :796 |

## 4. Shipment Detail — `#/detail`

| Check | Where | Confirm | Handler |
|---|---|---|---|
| DHL is entry-point-only (R-Q1) | DHL/Customs sub-tab | shows a read-only status summary + "Open DHL Console" link; NO duplicated DHL action UI | SD-4: DhlReadinessCard + nav to `/v2/dhl?batch_id=…` |

## 5. Dashboard — `#/dashboard`

| Check | Where | Confirm | Handler |
|---|---|---|---|
| Live health, no fabricated widget | top status strip | states come from a real health call (unavailable renders honestly red on 401) — NOT the old 6 hardcoded rows | `OperationalStatusStrip` → `apiFetch('/api/v1/health')` wireframe-update.jsx:87 |

## 6. Proforma — `#/proforma` → open a draft → Detail

| Check | Where | Confirm | Handler |
|---|---|---|---|
| service-products actually wired | Proforma Detail → Overview | ServiceProductRegistryPanel loads/saves via the real endpoint (previously never called) | `ServiceProductRegistryPanel` proforma-detail.jsx:3044 → GET/PUT `/proforma/service-products` |

---

## Notes for the operator's eye

- **Empty states are truthful.** Dev storage is empty, so data tables show honest empty renders — that IS the state, not a defect.
- **Gated controls are honest, not dead.** Disabled buttons carry a `title` naming the missing backend / Wave-4 route (Lesson M).
- **Open CP3 finding:** 4 wireframe-only accounting sub-views (`only-wireframe-accounting_tab_invoice / credit_note / client_balance / supplier_ledger`) — classified as census Tab-C sub-views + document-types (census §6 = 6 accounting tabs). Confirm the classification, or rule "re-open accounting."
- **Queued after your feedback:** the Visual Bug Sweep (alignment/spacing/overflow/mobile/scroll/clipping/icons/typography/responsive) runs as its own polish slice under this same gate — EJ tokens only, no wireframe redesign.
