// components.js — Application constants, data helpers, and layout components.
//
// Layer: sits BETWEEN dashboard-shared.js (visual atoms) and page-level
//         files (dashboard-kanban.js, carriers-page.js, etc.)
//
// Load order (MUST be respected):
//   1. dashboard-shared.js   → window.EstrellaShared
//   2. components.js         → window.EstrellaDash, window.NAV_TREE (compat alias)
//   3. <page>.js             → destructures from window.EstrellaDash
//
// Layer rules:
//   ALLOWED:  navigation constants, status/domain helpers, layout components
//   FORBIDDEN: backend URLs, direct fetch calls, business-rule computation,
//              write-gate decisions, wFirma/DHL API logic
//
// Note on SectionHeader naming:
//   dashboard-shared.js exports a V2 SectionHeader({ label, action }).
//   This file exports a V1 SectionHeader({ icon, title, subtitle, status }).
//   They are different components. Callers importing from EstrellaDash get
//   the V1 variant; callers importing from EstrellaShared get the V2 atom.

(function () {
  'use strict';

  // ── Shared atoms from dashboard-shared.js ─────────────────────────────
  const {
    apiFetch, fmtPLN,
    Badge, Card, Btn, Sel, Toast, SessionBanner,
    EstrellaMark, SubTabStrip, Sidebar,
  } = window.EstrellaShared;

  // ══════════════════════════════════════════════════════════
  // NAVIGATION CONSTANTS
  // ══════════════════════════════════════════════════════════

  const NAV_TREE = [
    { id: 'dashboard',  label: 'Dashboard',  icon: '▦' },
    { id: 'inbox',      label: 'Inbox',      icon: '✉' },
    { id: 'shipments',  label: 'Shipments',  icon: '⬡' },
    { id: 'documents',  label: 'Documents',  icon: '📄' },
    { id: 'accounting', label: 'Accounting', icon: '⊞' },
    { id: 'inventory',  label: 'Inventory',  icon: '◫' },
    { id: 'reports',    label: 'Reports',    icon: '≡' },
    { id: 'g_setup', label: 'Setup', icon: '⚙', defaultId: 'admin', children: [
      { id: 'admin',             label: 'Settings' },
      { id: 'admin_users',       label: 'Admin · Users' },
      { id: 'master',            label: 'Master Data' },
      { id: 'carriers',          label: 'Carriers' },
      { id: 'wfirma_setup',      label: 'wFirma' },
      { id: 'api_status',        label: 'API Status' },
      { id: 'diagnostics',       label: 'Diagnostics' },
      { id: 'automation',        label: 'Automation' },
      { id: 'intelligence_grp',  label: 'Parser / Learning' },
      { id: 'coverage',          label: 'Coverage Matrix' },
      { id: 'warehouse_scanner', label: 'Warehouse Scanner', href: '/dashboard/warehouse.html' },
    ]},
  ];

  // Flat index for quick lookup: id → item (including children)
  const NAV_INDEX = {};
  (function buildIndex(tree) {
    tree.forEach(n => { NAV_INDEX[n.id] = n; if (n.children) buildIndex(n.children); });
  })(NAV_TREE);

  // Legacy/alternate ids that map to a canonical id
  const ROUTE_REDIRECTS = {
    'pz_accounting': 'accounting',
    'pz':            'accounting',
    'dhl_clearance': 'dhl',
    'customs_documents': 'documents',
    'customs':       'documents',
    'wfirma':        'wfirma_setup',
    'ai_bridge':     'automation',
    'learning':      'intelligence_grp',
  };

  // Which group (if any) owns a given leaf id
  function navGroupOf(id) {
    for (const n of NAV_TREE) {
      if (n.children && n.children.some(c => c.id === id)) return n;
    }
    return null;
  }

  // ══════════════════════════════════════════════════════════
  // STATUS MAP — domain-facing lookup used by callers that render
  // pills outside of the Badge component.
  // (Badge in dashboard-shared.js carries its own frozen private copy;
  //  the two copies must stay in sync.)
  // ══════════════════════════════════════════════════════════

  const STATUS_MAP = {
    'Draft':                  { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'In Transit':             { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Pre-check Pending':      { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Pre-check Completed':    { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Awaiting DHL Email':     { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
    'DHL Email Received':     { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Reply Sent':             { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Reply Queued':           { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'SAD Pending':            { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'SAD Uploaded':           { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Customs Parsed':         { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Verification Needed':    { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    'Customs Verified':       { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Locked':                 { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'Ready for PZ':           { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Generated':              { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Ready for Booking':      { bg: 'var(--badge-purple-bg)',  text: 'var(--badge-purple-text)',  border: 'var(--badge-purple-border)' },
    'Exported':               { bg: 'var(--badge-accent-bg)',  text: 'var(--badge-accent-text)',  border: 'var(--badge-accent-border)' },
    'Awaiting DHL':           { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Awaiting SAD':           { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
    'Action Required':        { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    'In Preparation':         { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'Completed':              { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Pending':                { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Live':                   { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Awaiting Clearance':     { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Processing':             { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Reply Package Prepared': { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  };

  // ══════════════════════════════════════════════════════════
  // STATUS / DATA HELPERS
  // ══════════════════════════════════════════════════════════

  function mapOverall(status) {
    const m = {
      success: 'Ready for Booking', partial: 'Ready for Booking',
      blocked: 'Action Required', failed: 'Action Required',
      awaiting_dhl_email: 'Awaiting DHL', awaiting_sad: 'Awaiting SAD',
      awaiting_clearance: 'Awaiting Clearance',
      in_preparation: 'In Preparation', draft: 'Draft',
      ready: 'Ready for PZ', processing: 'In Preparation',
      collecting: 'In Preparation',
    };
    return m[status] || (status ? status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Pending');
  }

  function mapDhlStatus(s) {
    if (!s) return '—';
    const m = {
      awaiting_dhl_email:     'Awaiting DHL Email',
      dhl_email_received:     'DHL Email Received',
      reply_sent:             'Reply Sent',
      reply_queued:           'Reply Queued',
      pre_check_completed:    'Pre-check Completed',
      pre_check_pending:      'Pre-check Pending',
      reply_package_prepared: 'Reply Package Prepared',
    };
    return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function mapSadStatus(s) {
    if (!s) return 'SAD Pending';
    const m = {
      // frontend legacy values
      sad_pending:         'SAD Pending',
      sad_uploaded:        'SAD Uploaded',
      customs_parsed:      'Customs Parsed',
      customs_verified:    'Customs Verified',
      verification_needed: 'Verification Needed',
      // backend _derive_sad_status() values
      missing:             'SAD Pending',
      uploaded:            'SAD Uploaded',
      uploaded_parsed:     'Customs Parsed',
    };
    return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function mapPzStatus(s) {
    if (!s) return 'Locked';
    const m = { locked: 'Locked', ready: 'Ready for PZ', generated: 'Generated', exported: 'Exported' };
    return m[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  // Normalise a raw batch API response to the shape expected by dashboard
  // and kanban views.
  function transformBatch(b) {
    return {
      id:        b.batch_id,
      batch_id:  b.batch_id,
      awb:       b.tracking_no || b.doc_no || b.batch_id,
      carrier:   b.carrier || '—',
      dhlStatus: mapDhlStatus(b.dhl_status),
      dhlRec:    b.dhl_status === 'reply_sent'            ? 'Completed'
               : b.dhl_status === 'reply_queued'          ? 'Queued'
               : b.dhl_status === 'pre_check_completed'   ? 'No Reply Needed'
               : b.dhl_status === 'dhl_email_received'    ? 'Reply Required' : '—',
      sadStatus: mapSadStatus(b.sad_status),
      mrn:       b.mrn || '—',
      pzStatus:  mapPzStatus(b.pz_status),
      net:       fmtPLN(b.net),
      gross:     fmtPLN(b.gross),
      duty:      fmtPLN(b.duty),
      overall:   mapOverall(b.status),
      action_reason: b.action_reason || '',
      doc_no:    b.doc_no || '',
      timestamp: b.timestamp || '',
      has_sad:   b.has_sad,
      warehouseHint: b.warehouse_status_hint || 'n/a',
      salesHint:     b.sales_status_hint || 'n/a',
      wfirmaHint:    b.wfirma_status_hint || 'n/a',
      _raw:      b,
    };
  }

  // Operator identity resolver for write actions that need attribution.
  // Prompts once per browser session, then caches in localStorage.
  // Returns "" if the user cancels — callers may still proceed;
  // backend falls back to "operator" via _operator_from_header.
  function _resolveOperator() {
    try {
      const cached = (window.localStorage.getItem('pz_operator_name') || '').trim();
      if (cached) return cached;
    } catch (_) { /* localStorage may be disabled */ }
    let name = '';
    try {
      name = (window.prompt('Operator name (recorded in audit timeline):', 'admin') || '').trim();
    } catch (_) { name = ''; }
    if (name) {
      try { window.localStorage.setItem('pz_operator_name', name); } catch (_) {}
    }
    return name;
  }

  // ══════════════════════════════════════════════════════════
  // LAYOUT COMPONENTS
  // ══════════════════════════════════════════════════════════

  // Generic modal shell — backdrop click dismisses.
  function Modal({ title, onClose, children, wide }) {
    return (
      <div style={{
        position: 'fixed', inset: 0, background: 'var(--overlay)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: 24,
      }} onClick={e => e.target === e.currentTarget && onClose()}>
        <div style={{
          background: 'var(--card)', borderRadius: 10,
          width: wide ? 680 : 480, maxWidth: '100%',
          maxHeight: '90vh', overflow: 'auto',
          boxShadow: '0 20px 60px var(--shadow-heavy)',
          border: '1px solid var(--border)',
        }}>
          <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, fontFamily: '"DM Serif Display",serif', color: 'var(--text)' }}>{title}</h2>
            <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-3)' }}>×</button>
          </div>
          <div style={{ padding: 24 }}>{children}</div>
        </div>
      </div>
    );
  }

  // Labelled form field wrapper with optional hint text.
  function FormField({ label, children, hint }) {
    return (
      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: 'var(--text-2)', marginBottom: 5, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{label}</label>
        {children}
        {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 3 }}>{hint}</div>}
      </div>
    );
  }

  // Styled text input — use inside FormField.
  function Inp({ value, onChange, placeholder, type = 'text', style: s, ...rest }) {
    return (
      <input value={value} onChange={onChange} placeholder={placeholder} type={type} {...rest} style={{
        width: '100%', padding: '8px 10px', borderRadius: 6,
        border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
        background: 'var(--bg-subtle)', outline: 'none',
        boxSizing: 'border-box', fontFamily: 'inherit', ...s,
      }} />
    );
  }

  // Panel section header — icon square + title/subtitle + optional Badge.
  // NOTE: distinct from the V2 SectionHeader in dashboard-shared.js
  //       which takes { label, action } props.
  function SectionHeader({ icon, title, subtitle, status }) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
        <div style={{ width: 32, height: 32, borderRadius: 6, background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, color: 'var(--accent)' }}>{icon}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
          {subtitle && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 1 }}>{subtitle}</div>}
        </div>
        {status && <Badge status={status} />}
      </div>
    );
  }

  // Horizontally laid-out label/value row — for details panels.
  function InfoRow({ label, value, mono }) {
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
        <span style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 500 }}>{label}</span>
        <span style={{ fontSize: 11, color: 'var(--text)', fontWeight: 600, fontFamily: mono ? 'monospace' : 'inherit', textAlign: 'right', maxWidth: '60%', wordBreak: 'break-all' }}>{value ?? '—'}</span>
      </div>
    );
  }

  // Application top bar — search palette, dark-mode toggle, user avatar, logout.
  function TopBar({ onNewShipment, onToggleDark, isDark, user, onLogout }) {
    const [searchOpen, setSearchOpen] = React.useState(false);
    const [search, setSearch]         = React.useState('');
    const initials = user ? user.full_name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() : 'U';

    React.useEffect(() => {
      const handler = (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setSearchOpen(o => !o); }
        if (e.key === 'Escape') setSearchOpen(false);
      };
      window.addEventListener('keydown', handler);
      return () => window.removeEventListener('keydown', handler);
    }, []);

    return (
      <>
      {searchOpen && (
        <div onClick={() => setSearchOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 8000, background: 'var(--overlay)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: 120 }}>
          <div onClick={e => e.stopPropagation()} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12, boxShadow: '0 16px 48px var(--shadow-heavy)', width: '100%', maxWidth: 560, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ color: 'var(--text-3)', fontSize: 16 }}>⌕</span>
              <input autoFocus value={search} onChange={e => setSearch(e.target.value)} placeholder="Search AWB, MRN, batch ID…"
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 14, color: 'var(--text)', background: 'transparent', fontFamily: 'inherit' }} />
              <kbd style={{ fontSize: 10, color: 'var(--text-3)', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px' }}>Esc</kbd>
            </div>
            <div style={{ padding: '8px 16px 12px', fontSize: 11, color: 'var(--text-3)' }}>Type to search shipments, AWBs, MRNs…</div>
          </div>
        </div>
      )}
      <header style={{ height: 56, background: 'var(--card)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', padding: '0 24px', gap: 12, flexShrink: 0 }}>
        <button onClick={() => setSearchOpen(true)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', color: 'var(--text-3)', fontSize: 12, fontFamily: 'inherit', flex: 1, maxWidth: 280, textAlign: 'left' }}>
          <span style={{ fontSize: 14 }}>⌕</span>
          <span style={{ flex: 1, color: 'var(--text-3)' }}>Search…</span>
          <kbd style={{ fontSize: 10, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 5px', color: 'var(--text-3)' }}>⌘K</kbd>
        </button>
        <div style={{ flex: 1 }} />
        <button onClick={onToggleDark} title={isDark ? 'Light mode' : 'Dark mode'} style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 10px', cursor: 'pointer', fontSize: 14, color: 'var(--text-2)', fontFamily: 'inherit' }}>
          {isDark ? '☀' : '🌿'}
        </button>
        <button onClick={onNewShipment} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--accent)', color: 'var(--accent-text)', border: 'none', borderRadius: 6, padding: '7px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New Shipment
        </button>
        {user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 34, height: 34, borderRadius: '50%', background: 'linear-gradient(135deg,var(--accent),var(--accent-light))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'var(--accent-text)', boxShadow: '0 1px 3px rgba(0,0,0,.1)', border: '2px solid var(--accent-border)', letterSpacing: '0.02em' }}>{initials}</div>
            <div style={{ lineHeight: 1.3 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', letterSpacing: '-0.01em' }}>{user.full_name}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent)', background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)', padding: '1px 6px', borderRadius: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{user.role}</span>
                {user.is_approved && <span style={{ fontSize: 9, color: 'var(--badge-green-text)', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', padding: '1px 5px', borderRadius: 10, fontWeight: 600 }}>✓</span>}
              </div>
            </div>
            <div style={{ width: 1, height: 24, background: 'var(--border)', margin: '0 2px' }} />
            <button onClick={onLogout}
              style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', fontSize: 11, fontWeight: 500, color: 'var(--text-2)', padding: '5px 12px', fontFamily: 'inherit', transition: 'all .15s' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--badge-red-bg)'; e.currentTarget.style.color = 'var(--badge-red-text)'; e.currentTarget.style.borderColor = 'var(--badge-red-border)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-subtle)'; e.currentTarget.style.color = 'var(--text-2)'; e.currentTarget.style.borderColor = 'var(--border)'; }}>
              Logout
            </button>
          </div>
        )}
      </header>
      </>
    );
  }

  // Horizontal rule with an uppercase label — separates groups of content.
  function SectionLabel({ children, style }) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, ...style }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.12em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{children}</span>
        <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
      </div>
    );
  }

  // Card with optional header row (title, subtitle, status badge) and
  // an optional left accent bar (pass a CSS color string as `accent`).
  function PanelCard({ title, subtitle, status, children, accent }) {
    return (
      <div style={{
        background: 'var(--card)', borderRadius: 10,
        boxShadow: '0 1px 2px var(--shadow)', overflow: 'hidden',
        border: '1px solid var(--border)',
        borderLeft: accent ? `3px solid ${accent}` : '1px solid var(--border)',
      }}>
        {(title || status) && (
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, background: 'var(--bg-subtle)' }}>
            <div>
              {title && <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>}
              {subtitle && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{subtitle}</div>}
            </div>
            {status && <Badge status={status} />}
          </div>
        )}
        <div>{children}</div>
      </div>
    );
  }

  // Single-metric KPI tile — large number + label + optional sub-line.
  function StatTile({ label, value, sub, accent }) {
    return (
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '16px 20px', boxShadow: '0 1px 2px var(--shadow)' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>{label}</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', fontFamily: '"DM Serif Display",serif', letterSpacing: '-0.01em', lineHeight: 1 }}>{value ?? '—'}</div>
        {sub && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4 }}>{sub}</div>}
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════
  // EXPORTS
  // ══════════════════════════════════════════════════════════

  // V1 compat alias — dashboard.html reads NAV_TREE directly from scope,
  // but standalone pages that load this file via <script> need the global.
  window.NAV_TREE = NAV_TREE;

  window.EstrellaDash = Object.freeze({
    // Navigation
    NAV_TREE,
    NAV_INDEX,
    ROUTE_REDIRECTS,
    navGroupOf,
    // Domain data
    STATUS_MAP,
    mapOverall,
    mapDhlStatus,
    mapSadStatus,
    mapPzStatus,
    transformBatch,
    _resolveOperator,
    // Layout components
    Modal,
    FormField,
    Inp,
    SectionHeader,
    InfoRow,
    TopBar,
    SectionLabel,
    PanelCard,
    StatTile,
  });
})();
