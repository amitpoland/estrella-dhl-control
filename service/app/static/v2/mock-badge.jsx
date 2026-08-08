// mock-badge.jsx -- MOCK badge for un-wired pages (Phase 3, Sprint 1)
// Rendered by the shell wrapper for any page NOT in WIRED_PAGES.
// Must be prominent and unmissable -- no mock data may appear without it.

// Sprint 2B.2: 'inbox' added — read-only display wired to GET /api/v1/inbox.
// Sprint 30:   'inventory' added — live hub from inventory-v2.html (Sprint 29).
// Sprint 31:   'dhl' added — read-only observer over DHL projector + scan/summary cards.
// Sprint 32:   'shipments' added — DashboardPage wired read-only to GET /api/v1/dashboard/batches.
// Sprint 33:   'automation' added — AiBridgePage wired read-only to ai-bridge authority.
// Sprint 34:   'intelligence' added — IntelligencePage wired read-only to intelligence + invoice-learning authority.
// Sprint 35:   'documents' added — DocumentsHubPage wired read-only to GET /api/v1/dashboard/batches.
// Sprint 36 Phase 0 (2026-06-06): 'proforma_detail' REMOVED — authority violation containment.
// Sprint 36 Phase 1 (2026-06-06): 'proforma_detail' RE-ADDED — authority recovery complete.
//   All fake data removed: exporter from GET /api/v1/settings/company-profile,
//   lines from editable_lines, FX from exchange_rate, PDF download wired,
//   ConvertToInvoiceModal calls draftToInvoice, no browser-side FX calculations.
// Sprint 36 Phase 2 (2026-06-06): Full UI parity with atlas-proforma-preview.html.
//   Full 8-button toolbar (Edit/Delete/Duplicate/PostToWFirma/Convert/Print/Send/Generate).
//   SELLER/BUYER/RECIPIENT party cards. ReservationTab wired to blocking_reasons.
//   OverviewTab KV grid (16 fields). PostToWFirmaModal added.
//   pz-api.js: postDraftToWfirma now accepts body param for confirm_token.
// Sprint 37 (2026-06-06): 'wfirma_setup' added — WfirmaMappingPage wired to
//   GET /wfirma/capabilities, GET /wfirma/customers, GET /wfirma/products.
//   All hardcoded mock data removed; live API rendering only.
// Sprint 38 (2026-06-07): 'master' added — MasterPage wired to live GET endpoints
//   for all 12 entity tabs (10 full CRUD, Users read-only, Roles static).
//   All hardcoded SEED data removed; writes disabled with explicit reasons.
// Sprint 39 (2026-06-07): 'carriers' added — CarriersPage redesigned from mock
//   multi-carrier management console to authority-honest Config Registry + DHL
//   Operations page. All hardcoded CARRIERS/WEBHOOKS/SESSIONS/AUDIT/AVAILABLE_NEW
//   removed. Live data from GET /api/v1/carriers-config/ and GET /api/v1/carrier/status.
//   Audit tab wired to GET /api/v1/master/audit/?entity=carriers_config.
// Sprint 40 (2026-06-07): 'dashboard' added — DashboardKanban wired to live
//   GET /api/v1/dashboard/batches. All 15 fake PIPELINE_SHIPMENTS removed. 6 PZ
//   workflow lanes from V1 production (new→docs→customs→ready→booked→done).
//   KPIs derived from live batch data. Status mappers ported from V1.
// Sprint 41 (2026-06-07): 'api_status' added — ApiStatusPage wired to 12
//   live subsystem endpoints (health-full, pending, storage/health, pz/health,
//   dhl/auto-scan-status, dhl/daily-summary, dhl/followup-automation/status,
//   carrier/status, carriers-config, wfirma/capabilities, admin/email-queue,
//   intelligence/status). All 4 fake arrays removed (API_INTEGRATIONS,
//   API_ENDPOINT_REGISTRY, RECENT_ERRORS, INCIDENTS). No fake carriers.
// Sprint 42: 'diagnostics' added — DiagnosticsPage wired to 5 live GET endpoints
//   (health-full, storage/health, storage/locks, system/version, debug/pending).
//   All hardcoded fake data removed. CLI tools visible but disabled.
// Sprint 43: 'coverage' added — CoverageMapPage wired to GET /openapi.json.
//   All 46 hardcoded COVERAGE_ROWS removed. Live OpenAPI spec is the authority.
//   WIRED_PAGES = 16/16 — ALL V2 pages are now authority-honest. MOCK banner retired.
// M6-cleanup: 'proforma_search' added — ProformaSearchPage wired to
//   GET /api/v1/proforma/search via PzApi.searchProformaDrafts. Read-only,
//   no mock data. False positive MOCK banner resolved. WIRED_PAGES = 17/17.
// detail-wiring: 'detail' added — ShipmentDetailPage (the shipment drill-down reached
//   via page==='detail') wired read-only to GET /api/v1/dashboard/batches/{batch_id}
//   (full-audit authority). All hardcoded values removed — CIF (real USD), clearance
//   date, customs agent, LRN, SAD/NBP rates, A00/B00, PZ number + wFirma doc id, line
//   count, invoice count, and the activity timeline now render from the audit; missing
//   fields show '—'. Write actions remain visible+disabled (Lesson M) on their domain
//   pages. WIRED_PAGES = 18/18.
// B×7-1 (2026-07-02): 'move_location' added — first inventory-family promotion.
// Phase B FOLD (2026-07-03): 'move_location' REMOVED — the standalone page is
//   retired and its capability folded into the Inventory page as the Move
//   Stock modal (Lesson M relocation; PROJECT_STATE DECISIONS "Phase B FOLD").
//   Net page count DECREASED by one. WIRED_PAGES = 18/18.
// supplier-invoice-ocr (2026-07-02): 'supplier_invoice_review' added — new
//   Supplier Invoice OCR review page, wired live to
//   /api/v1/supplier-invoice-ocr (upload / drafts / confirm / reject).
//   No mock data. WIRED_PAGES = 19/19.
// Wave-3 Accounting Hub (2026-07-04): 'accounting' added — AccountingHub wired
//   live to 6 tabs: Purchase Ledger (listBatches), Sales/Proforma
//   (searchProformaDrafts), Client Ledger (LedgersPage embed), wFirma Sync
//   (getWfirmaContractorScanStatus + navigate to wfirma_setup), Master Data
//   (navigate to master), Audit Trail (listMasterAudit). Wave-4 doc-register
//   tabs (WZ/PZ/PW/RW/MM) kept visible but gated per R-Q3 (BACKEND-REQUIRED).
//   All mock arrays removed. WIRED_PAGES = 20/20.
const WIRED_PAGES = ['proforma', 'proforma_search', 'inbox', 'inventory', 'dhl', 'shipments', 'automation', 'intelligence', 'documents', 'proforma_detail', 'wfirma_setup', 'master', 'carriers', 'dashboard', 'api_status', 'diagnostics', 'coverage', 'detail', 'supplier_invoice_review', 'accounting'];

function MockBanner({ page }) {
  if (WIRED_PAGES.includes(page)) return null;
  return (
    <div
      data-testid="mock-banner"
      className="mock-banner"
      style={{
        // Stay below mobile nav drawer (z-index 1100) — sticky only within page scroll
        position: 'sticky',
        top: 0,
        zIndex: 30,
        background: 'var(--badge-purple-bg)',
        color: 'var(--badge-purple-text)',
        padding: '10px 16px',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: '0.02em',
        borderBottom: '1px solid var(--badge-purple-border)',
        flexShrink: 0,
        flexWrap: 'wrap',
        lineHeight: 1.45,
      }}
    >
      <span style={{
        background: 'var(--card)',
        color: 'var(--badge-purple-text)',
        borderRadius: 4,
        padding: '2px 8px',
        fontSize: 10.5,
        fontWeight: 800,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        flexShrink: 0,
        border: '1px solid var(--badge-purple-border)',
      }}>MOCK</span>
      <span style={{ flex: '1 1 180px', minWidth: 0 }}>
        This page is not yet wired to the live backend — data shown is design-time placeholder only.
      </span>
    </div>
  );
}

window.MockBanner = MockBanner;
window.WIRED_PAGES = WIRED_PAGES;
