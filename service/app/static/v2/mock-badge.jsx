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
const WIRED_PAGES = ['proforma', 'inbox', 'inventory', 'dhl', 'shipments', 'automation', 'intelligence', 'documents', 'proforma_detail', 'wfirma_setup', 'master'];

function MockBanner({ page }) {
  if (WIRED_PAGES.includes(page)) return null;
  return (
    <div
      data-testid="mock-banner"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 900,
        background: '#7c3aed',
        color: '#fff',
        padding: '10px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: '0.02em',
        borderBottom: '2px solid #6d28d9',
      }}
    >
      <span style={{
        background: '#fff',
        color: '#7c3aed',
        borderRadius: 4,
        padding: '1px 8px',
        fontSize: 10.5,
        fontWeight: 800,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
      }}>MOCK</span>
      This page is not yet wired to the live backend — data shown is design-time placeholder only.
    </div>
  );
}

window.MockBanner = MockBanner;
window.WIRED_PAGES = WIRED_PAGES;
