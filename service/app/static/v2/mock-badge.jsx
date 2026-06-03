// mock-badge.jsx -- MOCK badge for un-wired pages (Phase 3, Sprint 1)
// Rendered by the shell wrapper for any page NOT in WIRED_PAGES.
// Must be prominent and unmissable -- no mock data may appear without it.

// Sprint 2B.2: 'inbox' added — read-only display wired to GET /api/v1/inbox.
const WIRED_PAGES = ['proforma', 'proforma_detail', 'inbox'];

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
