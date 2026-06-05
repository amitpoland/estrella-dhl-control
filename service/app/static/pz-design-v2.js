// pz-design-v2.js — Estrella Atlas design system (V2 baseline).
//
// Ported verbatim from estrella-dashboard/project/components.jsx (2026-05-30).
// Exposes window.PzDesign with all layout + UI components.
// Also sets window.EstrellaShared.apiFetch so pz-api.js can run without dashboard-shared.js.
//
// Load order for NEW pages (sprint-24+):
//   <script> React 18 production </script>
//   <script type="text/babel" src="/dashboard/pz-design-v2.js"></script>
//   <script type="text/babel" src="/dashboard/pz-api.js"></script>
//   <script type="text/babel" src="/dashboard/pz-state.js"></script>
//   <script type="text/babel"> /* page app */ </script>
//
// GATE 1 check: new pages MUST NOT import dashboard-shared.js.
// dashboard-shared.js is frozen for V1 + early V2 reskin.
//
// Layer rules:
//   ALLOWED:  all UI rendering, navigation, layout, design tokens, apiFetch transport
//   FORBIDDEN: business logic, API endpoint knowledge, state management, workflow decisions

(function () {
  'use strict';

  // ── apiFetch — transport (mirrors dashboard-shared.js for pz-api.js compat) ─

  async function apiFetch(url, opts = {}) {
    let res;
    try {
      res = await fetch(url, { credentials: 'include', ...opts });
    } catch (netErr) {
      const err = new Error('Service unreachable — check that the backend is running.');
      err.type = 'network';
      throw err;
    }
    if (res.status === 401 || res.status === 403) {
      const err = new Error('Session expired or access denied.');
      err.type = 'auth';
      err.status = res.status;
      throw err;
    }
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
    }
    if (res.status === 204 || res.status === 205) return null;
    const ct = res.headers.get('content-type') || '';
    return ct.includes('json') ? res.json() : res.text();
  }

  // Shim — lets pz-api.js work without dashboard-shared.js.
  // If dashboard-shared.js already ran (old pages), its apiFetch is preserved.
  if (!window.EstrellaShared) {
    window.EstrellaShared = {};
  }
  if (!window.EstrellaShared.apiFetch) {
    window.EstrellaShared.apiFetch = apiFetch;
  }

  // ── Design tokens (reference only — CSS vars are defined per-page) ──────────
  // --bg, --card, --text, --accent, --sidebar-bg, --badge-*, etc.
  // See the <style> block in any V2 page for the full token set.
  // New pages MUST include either:
  //   (a) the inline :root block from Estrella Dashboard.html, or
  //   (b) a link to a shared atlas-tokens.css (future improvement)
  // and MUST add the DM Serif Display Google Font:
  //   <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />

  // ── Navigation tree (verbatim from components.jsx) ────────────────────────

  const NAV_TREE = [
    { id: 'dashboard', label: 'Dashboard', icon: '▦' },
    { id: 'inbox',     label: 'Inbox',     icon: '✉', badge: 'NEW' },
    { id: 'shipments', label: 'Shipments', icon: '⬡' },
    { id: 'proforma',  label: 'Pro Forma', icon: '📋' },
    { id: 'documents', label: 'Documents', icon: '📄' },
    { id: 'accounting', label: 'Accounting', icon: '⊞', badge: 'NEW' },
    { id: 'inventory', label: 'Inventory', icon: '◫' },
    { id: 'reports',   label: 'Reports',   icon: '≡' },

    { id: 'g_setup', label: 'Setup', icon: '⚙', defaultId: 'admin', children: [
      { id: 'admin',        label: 'Settings' },
      { id: 'master',       label: 'Master Data' },
      { id: 'box-types',    label: 'Box Types' },    // Phase D — WF4.5 outbound packaging
      { id: 'carriers',     label: 'Carriers' },
      { id: 'wfirma_setup', label: 'wFirma' },
      { id: 'api_status',   label: 'API Status' },
      { id: 'diagnostics',  label: 'Diagnostics' },
      { id: 'automation',   label: 'Automation' },
      { id: 'intelligence', label: 'Parser / Learning' },
      { id: 'coverage',     label: 'Coverage Matrix' },
    ]},
  ];

  // Page id → route mapping for navigation
  const NAV_ROUTES = {
    'dashboard':  '/dashboard/dashboard-v2.html',
    'inbox':      '/dashboard/inbox-v2.html',
    'shipments':  '/dashboard/shipment-detail-v3.html',
    'proforma':         '/dashboard/proforma-v2.html',
    'proforma-detail':  '/dashboard/proforma-detail-v2.html',
    'documents':  '/dashboard/documents-v2.html',
    'accounting': '/dashboard/accounting-hub-v2.html',
    'inventory':  '/dashboard/inventory-v2.html',
    'reports':    '/dashboard/dashboard.html',
    'master':     '/dashboard/customer-master-v2.html',
    'box-types':  '/dashboard/master-data-v2.html',  // Phase D — WF4.5 box types catalog
    'admin':      '/dashboard/admin-users.html',
    'api_status': '/dashboard/ai-advisory-v2.html',
  };

  // Nav-route IDs whose target pages are not yet built.
  // Clicking these shows a disabled state — no 404, no navigation.
  // Remove an id from this set when its page is deployed.
  // All sidebar routes are now live. Update this Set when new planned-but-unbuilt
  // pages are added to NAV_ROUTES — add the id here to show disabled + "Soon" label.
  const STUB_ROUTES = new Set([]);

  const NAV_INDEX = (() => {
    const idx = {};
    for (const node of NAV_TREE) {
      if (node.children) {
        for (const c of node.children) idx[c.id] = { group: node, item: c };
      } else {
        idx[node.id] = { group: null, item: node };
      }
    }
    return idx;
  })();

  // ── Status map (verbatim from components.jsx) ─────────────────────────────

  const STATUS_MAP = {
    'Draft':                { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'In Transit':           { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Pre-check Pending':    { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Pre-check Completed':  { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Awaiting DHL Email':   { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
    'DHL Email Received':   { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Reply Package Prepared':{ bg: 'var(--badge-blue-bg)',   text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Reply Sent':           { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'SAD Pending':          { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'SAD Uploaded':         { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Customs Parsed':       { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Verification Needed':  { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    'Customs Verified':     { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Locked':               { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'Ready for PZ':         { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Processing':           { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Generated':            { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Ready for Booking':    { bg: 'var(--badge-purple-bg)',  text: 'var(--badge-purple-text)',  border: 'var(--badge-purple-border)' },
    'Exported':             { bg: 'var(--badge-accent-bg)',  text: 'var(--badge-accent-text)',  border: 'var(--badge-accent-border)' },
    'Awaiting DHL':         { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Awaiting SAD':         { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
    'Action Required':      { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    'In Preparation':       { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'Live':                 { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Pending':              { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  };

  // ── Components (verbatim from components.jsx; IIFE + window.PzDesign adapation) ─

  function Badge({ status, label, small }) {
    const key = status || label || 'Draft';
    const s = STATUS_MAP[key] || STATUS_MAP['Draft'];
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center',
        background: s.bg, color: s.text, border: `1px solid ${s.border}`,
        borderRadius: 4, padding: small ? '1px 6px' : '2px 8px',
        fontSize: small ? 10 : 11, fontWeight: 600, letterSpacing: '0.03em', whiteSpace: 'nowrap',
      }}>{key}</span>
    );
  }

  function EstrellaMark({ size = 30 }) {
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" style={{ display: 'block', flexShrink: 0 }}>
        <path d="M20 3 L37 20 L20 37 L3 20 Z"
              fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round"/>
        <path d="M20 13 L27 20 L20 27 L13 20 Z" fill="var(--accent)"/>
        <path d="M16.5 16.5 L23.5 16.5" stroke="var(--sidebar-bg)" strokeWidth="0.8" opacity="0.5"/>
      </svg>
    );
  }

  function EstrellaWordmark({ collapsed }) {
    if (collapsed) return null;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1, gap: 5 }}>
        <span style={{
          fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif',
          fontSize: 15, fontWeight: 600, letterSpacing: '0.22em',
          color: 'var(--sidebar-text)', textTransform: 'uppercase',
        }}>Estrella</span>
        <span style={{
          fontSize: 8.5, fontWeight: 600, letterSpacing: '0.36em',
          color: 'var(--accent)', textTransform: 'uppercase',
        }}>Atlas</span>
      </div>
    );
  }

  const SIDEBAR_W = 220;

  function Sidebar({ active, onNav, collapsed, onToggle }) {
    const activeGroup = NAV_INDEX[active]?.group?.id;
    const [openGroups, setOpenGroups] = React.useState(() => {
      const init = {};
      if (activeGroup) init[activeGroup] = true;
      return init;
    });
    React.useEffect(() => {
      if (activeGroup) setOpenGroups(g => ({ ...g, [activeGroup]: true }));
    }, [activeGroup]);

    const nav = (id) => {
      if (STUB_ROUTES.has(id)) return;
      if (onNav) {
        onNav(id);
      } else {
        const route = NAV_ROUTES[id];
        if (route) window.location.href = route;
      }
    };

    const rowStyle = (isActive, isChild) => ({
      width: '100%', display: 'flex', alignItems: 'center',
      gap: 10, padding: collapsed ? '9px 14px' : (isChild ? '7px 16px 7px 44px' : '9px 16px'),
      background: isActive ? 'var(--sidebar-active)' : 'transparent',
      border: 'none', cursor: 'pointer', textAlign: 'left',
      borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
      transition: 'background 0.15s',
    });

    return (
      <aside data-testid="sidebar" className="sidebar-desktop" style={{
        width: collapsed ? 52 : SIDEBAR_W, minWidth: collapsed ? 52 : SIDEBAR_W,
        background: 'var(--sidebar-bg)', display: 'flex', flexDirection: 'column',
        transition: 'width 0.2s, min-width 0.2s', overflow: 'hidden', zIndex: 10,
        borderRight: '1px solid var(--sidebar-border)', flexShrink: 0,
      }}>
        <div style={{
          padding: collapsed ? '20px 8px' : '20px 18px',
          borderBottom: '1px solid var(--sidebar-border)',
          display: 'flex', alignItems: 'center', gap: 12, minHeight: 72,
          justifyContent: collapsed ? 'center' : 'flex-start',
        }}>
          <EstrellaMark size={collapsed ? 26 : 32}/>
          <EstrellaWordmark collapsed={collapsed}/>
        </div>

        <nav style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
          {NAV_TREE.map(node => {
            if (!node.children) {
              const isActive = active === node.id;
              const isStub  = STUB_ROUTES.has(node.id);
              if (isStub) {
                return (
                  <button key={node.id}
                    disabled
                    title="Coming soon"
                    style={{ ...rowStyle(false, false), opacity: 0.38, cursor: 'not-allowed' }}
                    data-testid={`nav-${node.id}`}>
                    <span style={{ color: 'var(--sidebar-icon)', fontSize: 14, minWidth: 18, textAlign: 'center' }}>{node.icon}</span>
                    {!collapsed && <span style={{ color: 'var(--sidebar-text-muted)', fontSize: 12, fontWeight: 400, flex: 1 }}>{node.label}</span>}
                    {!collapsed && <span style={{ fontSize: 8, fontWeight: 600, letterSpacing: '0.04em', color: 'var(--sidebar-text-muted)', opacity: 0.7, flexShrink: 0 }}>Soon</span>}
                  </button>
                );
              }
              return (
                <button key={node.id} onClick={() => nav(node.id)}
                  style={rowStyle(isActive, false)}
                  onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                  onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                  data-testid={`nav-${node.id}`}>
                  <span style={{ color: isActive ? 'var(--accent)' : 'var(--sidebar-icon)', fontSize: 14, minWidth: 18, textAlign: 'center' }}>{node.icon}</span>
                  {!collapsed && <span style={{ color: isActive ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 12, fontWeight: isActive ? 600 : 400 }}>{node.label}</span>}
                  {!collapsed && node.badge && (
                    <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '0.06em', background: 'var(--accent)', color: 'var(--accent-text)', padding: '1px 5px', borderRadius: 3 }}>{node.badge}</span>
                  )}
                </button>
              );
            }
            const open = !!openGroups[node.id];
            const groupHot = node.children.some(c => c.id === active);
            return (
              <div key={node.id}>
                <button onClick={() => {
                    if (collapsed) { nav(node.defaultId || node.children[0].id); }
                    else { setOpenGroups(g => ({ ...g, [node.id]: !g[node.id] })); }
                  }}
                  style={rowStyle(false, false)}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  data-testid={`nav-group-${node.id}`}>
                  <span style={{ color: groupHot ? 'var(--accent)' : 'var(--sidebar-icon)', fontSize: 14, minWidth: 18, textAlign: 'center' }}>{node.icon}</span>
                  {!collapsed && (
                    <>
                      <span style={{ color: groupHot ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 12, fontWeight: groupHot ? 600 : 500, flex: 1 }}>{node.label}</span>
                      <span style={{ fontSize: 10, color: 'var(--sidebar-text-muted)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', marginRight: 2 }}>›</span>
                    </>
                  )}
                </button>
                {!collapsed && open && node.children.map(child => {
                  const ca = active === child.id;
                  return (
                    <button key={child.id} onClick={() => nav(child.id)}
                      style={rowStyle(ca, true)}
                      onMouseEnter={e => { if (!ca) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                      onMouseLeave={e => { if (!ca) e.currentTarget.style.background = 'transparent'; }}
                      data-testid={`nav-${child.id}`}>
                      <span style={{ color: ca ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 11.5, fontWeight: ca ? 600 : 400, flex: 1 }}>{child.label}</span>
                      {child.badge && (
                        <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '0.06em', background: 'var(--accent)', color: 'var(--accent-text)', padding: '1px 5px', borderRadius: 3, marginRight: 4 }}>{child.badge}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <button onClick={onToggle} style={{
          padding: '12px 16px', background: 'transparent', border: 'none',
          borderTop: '1px solid var(--sidebar-border)', cursor: 'pointer',
          color: 'var(--sidebar-icon)', fontSize: 12,
          display: 'flex', justifyContent: collapsed ? 'center' : 'flex-end',
        }} data-testid="sidebar-toggle">{collapsed ? '›' : '‹'}</button>
      </aside>
    );
  }

  function SubTabStrip({ active, onNav }) {
    const entry = NAV_INDEX[active];
    if (!entry || !entry.group) return null;
    const siblings = entry.group.children;
    return (
      <div style={{
        padding: '0 32px', borderBottom: '1px solid var(--border)',
        background: 'var(--card)', display: 'flex', gap: 4,
        flexShrink: 0, overflowX: 'auto',
      }}>
        {siblings.map(s => {
          const isActive = s.id === active;
          return (
            <button key={s.id} onClick={() => onNav ? onNav(s.id) : (window.location.href = (NAV_ROUTES[s.id] || '#'))}
              style={{
                background: 'transparent', border: 'none', cursor: 'pointer',
                padding: '10px 14px 11px', fontSize: 12,
                fontWeight: isActive ? 700 : 500,
                color: isActive ? 'var(--text)' : 'var(--text-2)',
                borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                marginBottom: -1, letterSpacing: '0.01em', whiteSpace: 'nowrap',
                display: 'inline-flex', alignItems: 'center', gap: 6,
              }} data-testid={`subtab-${s.id}`}>
              {s.label}
              {s.badge && (
                <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '0.06em', background: 'var(--accent)', color: 'var(--accent-text)', padding: '1px 5px', borderRadius: 3 }}>{s.badge}</span>
              )}
            </button>
          );
        })}
      </div>
    );
  }

  function TopBar({ onNewShipment, onToggleDark, isDark, onOpenSearch, title }) {
    return (
      <header data-testid="topbar" style={{
        height: 56, background: 'var(--card)',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center',
        padding: '0 24px', gap: 16, flexShrink: 0,
      }}>
        <button onClick={onOpenSearch || undefined} style={{
          flex: 1, maxWidth: 360, display: 'flex', alignItems: 'center', gap: 10,
          background: 'var(--bg-subtle)', border: '1px solid var(--border)',
          borderRadius: 6, padding: '7px 12px', cursor: 'pointer',
          color: 'var(--text-3)', fontSize: 12, fontFamily: 'inherit',
        }} data-testid="topbar-search">
          <span style={{ fontSize: 13 }}>⌕</span>
          <span style={{ flex: 1, textAlign: 'left' }}>Search AWB, PI, INV, client…</span>
          <span style={{ fontFamily: 'monospace', fontSize: 9.5, padding: '1px 5px', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 3, fontWeight: 600 }}>⌘K</span>
        </button>
        <div style={{ flex: 1 }} />
        <button onClick={onToggleDark || undefined} title={isDark ? 'Light mode' : 'Dark mode'} style={{
          background: 'var(--bg-subtle)', border: '1px solid var(--border)',
          borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
          fontSize: 14, color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: 4,
        }} data-testid="topbar-theme-toggle">{isDark ? '☀' : '🌿'}</button>
        {onNewShipment && (
          <button onClick={onNewShipment} style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'var(--accent)', color: 'var(--accent-text)',
            border: 'none', borderRadius: 6, padding: '7px 14px',
            fontSize: 12, fontWeight: 700, cursor: 'pointer',
          }} data-testid="topbar-new-shipment">
            <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New Shipment
          </button>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'linear-gradient(135deg, var(--accent), var(--accent-light))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: 'var(--accent-text)' }}>A</div>
        </div>
      </header>
    );
  }

  function PageHeader({ title, subtitle, actions }) {
    return (
      <div style={{ padding: '24px 32px 0', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif', letterSpacing: '-0.01em' }}>{title}</h1>
          {subtitle && <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-2)' }}>{subtitle}</p>}
        </div>
        {actions && <div style={{ display: 'flex', gap: 8 }}>{actions}</div>}
      </div>
    );
  }

  function Card({ children, style: extraStyle, onClick, 'data-testid': testId }) {
    return (
      <div onClick={onClick} data-testid={testId} style={{
        background: 'var(--card)', borderRadius: 8,
        border: '1px solid var(--border)',
        boxShadow: '0 1px 3px var(--shadow)',
        ...extraStyle,
      }}>{children}</div>
    );
  }

  function Btn({ children, onClick, variant = 'default', small, disabled, style: extraStyle, 'data-testid': testId }) {
    const variants = {
      default: { background: 'var(--text)', color: 'var(--card)', border: '1px solid var(--text)' },
      primary: { background: 'var(--accent)', color: 'var(--accent-text)', border: '1px solid var(--accent)' },
      gold:    { background: 'var(--accent)', color: 'var(--accent-text)', border: '1px solid var(--accent)' },
      outline: { background: 'transparent', color: 'var(--text)', border: '1px solid var(--border)' },
      secondary: { background: 'transparent', color: 'var(--text)', border: '1px solid var(--border)' },
      ghost:   { background: 'transparent', color: 'var(--text-2)', border: '1px solid transparent' },
      danger:  { background: 'var(--badge-red-bg)', color: 'var(--badge-red-text)', border: '1px solid var(--badge-red-border)' },
      success: { background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)', border: '1px solid var(--badge-green-border)' },
    };
    const v = variants[variant] || variants.default;
    return (
      <button onClick={onClick} disabled={disabled} data-testid={testId} style={{
        ...v, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
        padding: small ? '4px 10px' : '7px 14px',
        fontSize: small ? 11 : 12, fontWeight: 600,
        opacity: disabled ? 0.45 : 1,
        display: 'inline-flex', alignItems: 'center', gap: 4,
        whiteSpace: 'nowrap', transition: 'opacity 0.15s',
        fontFamily: 'inherit',
        ...extraStyle,
      }}>{children}</button>
    );
  }

  function Modal({ title, onClose, children, wide, 'data-testid': testId }) {
    return (
      <div data-testid={testId || 'modal'} style={{
        position: 'fixed', inset: 0, background: 'var(--overlay)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: 24,
      }} onClick={e => e.target === e.currentTarget && onClose && onClose()}>
        <div style={{
          background: 'var(--card)', borderRadius: 10,
          width: wide ? 680 : 480, maxWidth: '100%',
          maxHeight: '90vh', overflow: 'auto',
          boxShadow: '0 20px 60px var(--shadow-heavy)',
          border: '1px solid var(--border)',
        }}>
          <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{title}</h2>
            <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-3)' }} data-testid="modal-close">×</button>
          </div>
          <div style={{ padding: 24 }}>{children}</div>
        </div>
      </div>
    );
  }

  function FormField({ label, children, hint }) {
    return (
      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: 'var(--text-2)', marginBottom: 5, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{label}</label>
        {children}
        {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 3 }}>{hint}</div>}
      </div>
    );
  }

  function Input({ value, onChange, placeholder, type = 'text', style: s, 'data-testid': testId }) {
    return (
      <input value={value} onChange={onChange} placeholder={placeholder} type={type} data-testid={testId} style={{
        width: '100%', padding: '8px 10px', borderRadius: 6,
        border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
        background: 'var(--bg-subtle)', outline: 'none', boxSizing: 'border-box',
        fontFamily: 'inherit', ...s,
      }} />
    );
  }

  function Select({ value, onChange, children, style: s, 'data-testid': testId }) {
    return (
      <select value={value} onChange={onChange} data-testid={testId} style={{
        width: '100%', padding: '8px 10px', borderRadius: 6,
        border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
        background: 'var(--bg-subtle)', outline: 'none', boxSizing: 'border-box',
        fontFamily: 'inherit', ...s,
      }}>{children}</select>
    );
  }

  function SectionHeader({ icon, label, title, subtitle, status, action }) {
    const displayTitle = title || label;
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: icon ? 12 : 0,
        padding: icon ? '14px 20px' : '0 0 8px',
        borderBottom: icon ? '1px solid var(--border)' : 'none',
        background: icon ? 'var(--bg-subtle)' : 'transparent',
        marginBottom: icon ? 0 : 4,
      }}>
        {icon && (
          <div style={{
            width: 32, height: 32, borderRadius: 6,
            background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, color: 'var(--accent)',
          }}>{icon}</div>
        )}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: icon ? 13 : 11, fontWeight: 700, color: 'var(--text)' }}>{displayTitle}</div>
          {subtitle && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 1 }}>{subtitle}</div>}
        </div>
        {status && <Badge status={status} small />}
        {action && action}
      </div>
    );
  }

  function InfoRow({ label, value, mono }) {
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
        <span style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 500 }}>{label}</span>
        <span style={{ fontSize: 11, color: 'var(--text)', fontWeight: 600, fontFamily: mono ? 'monospace' : 'inherit' }}>{value ?? '—'}</span>
      </div>
    );
  }

  // ── Additional utilities not in components.jsx ─────────────────────────────

  function Toast({ msg, type = 'info' }) {
    const colors = {
      success: { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
      error:   { bg: 'var(--badge-red-bg)',   text: 'var(--badge-red-text)',   border: 'var(--badge-red-border)' },
      info:    { bg: 'var(--badge-blue-bg)',   text: 'var(--badge-blue-text)',  border: 'var(--badge-blue-border)' },
    };
    const c = colors[type] || colors.info;
    return (
      <div data-testid="toast" style={{
        position: 'fixed', top: 20, right: 20, zIndex: 9999,
        background: c.bg, color: c.text, border: `1px solid ${c.border}`,
        borderRadius: 8, padding: '10px 16px',
        boxShadow: '0 4px 16px var(--shadow-heavy)',
        fontSize: 13, fontWeight: 600, maxWidth: 340,
        animation: 'fadeIn 0.2s',
      }}>{msg}</div>
    );
  }

  function EmptyState({ state = 'empty', message, onRetry, 'data-testid': testId }) {
    const icons = { empty: '○', error: '⚠', loading: '◌' };
    return (
      <div data-testid={testId || 'empty-state'} style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-3)' }}>
        <div style={{ fontSize: 24, marginBottom: 10 }}>{icons[state] || '○'}</div>
        <div style={{ fontSize: 13, marginBottom: onRetry ? 14 : 0 }}>{message}</div>
        {onRetry && (
          <button onClick={onRetry} style={{ fontSize: 12, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 600 }}>Retry</button>
        )}
      </div>
    );
  }

  function SessionBanner({ type, onDismiss }) {
    const msgs = {
      auth: 'Session expired — please refresh and sign in again.',
      network: 'Backend unreachable — check that the service is running.',
    };
    return (
      <div style={{
        background: 'var(--badge-red-bg)', color: 'var(--badge-red-text)',
        borderBottom: '1px solid var(--badge-red-border)',
        padding: '8px 16px', fontSize: 12, fontWeight: 600,
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <span style={{ flex: 1 }}>{msgs[type] || type}</span>
        {onDismiss && <button onClick={onDismiss} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: 14 }}>×</button>}
      </div>
    );
  }

  // ── AppShell — full sidebar + topbar layout wrapper ────────────────────────
  // Usage:
  //   <AppShell activeNav="proforma" isDark={isDark} onToggleDark={setDark}>
  //     <PageHeader title="Pro Forma" />
  //     { page content }
  //   </AppShell>

  function AppShell({ children, activeNav, isDark, onToggleDark, onNewShipment }) {
    const [collapsed, setCollapsed] = React.useState(false);
    const [dark, setDark] = React.useState(isDark || false);

    const toggleDark = () => {
      const next = !dark;
      setDark(next);
      document.documentElement.setAttribute('data-theme', next ? 'dark' : '');
      if (onToggleDark) onToggleDark(next);
    };

    return (
      <div data-testid="app-shell" style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
        <Sidebar active={activeNav} collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <TopBar isDark={dark} onToggleDark={toggleDark} onNewShipment={onNewShipment} />
          {activeNav && NAV_INDEX[activeNav]?.group && (
            <SubTabStrip active={activeNav} />
          )}
          <main style={{ flex: 1, overflowY: 'auto', background: 'var(--bg)' }}>
            {children}
          </main>
        </div>
      </div>
    );
  }

  // ── Sel — styled <select> wrapper (ported from dashboard-shared.js) ──────────
  // Alias: dashboard-shared.js called this "Sel"; PzDesign also exposes it as
  // "Select" (the FormField primitive). Sel provides the standalone styled variant
  // for pages migrated off dashboard-shared.js.
  function Sel({ value, onChange, children, ...rest }) {
    return (
      <select value={value} onChange={onChange} {...rest} style={{
        width: '100%', padding: '8px 10px', borderRadius: 6,
        border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
        background: 'var(--bg-subtle)', outline: 'none',
        boxSizing: 'border-box', fontFamily: 'inherit',
        ...(rest.style || {}),
      }}>
        {children}
      </select>
    );
  }

  // ── CompactTable — standard data table (ported from dashboard-shared.js) ─────
  // cols: [{ key, label, thStyle?, tdStyle?, render? }]
  // rows: any[]  (use row._key for stable keys, or falls back to index)
  function CompactTable({ cols = [], rows = [], onRowClick, emptyLabel = 'No data', style: xs }) {
    if (!rows || rows.length === 0) {
      return (
        <div style={{ padding: '12px 0', fontSize: 11, color: 'var(--text-3)', textAlign: 'center', ...xs }}>
          {emptyLabel}
        </div>
      );
    }
    return (
      <div style={{ overflowX: 'auto', ...xs }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr>
              {cols.map(c => (
                <th key={c.key} style={{
                  padding: '5px 8px', textAlign: 'left', fontWeight: 600,
                  fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em',
                  color: 'var(--text-2)', borderBottom: '1px solid var(--border)',
                  whiteSpace: 'nowrap', background: 'var(--bg-subtle)', ...c.thStyle,
                }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={row._key || ri}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={{ cursor: onRowClick ? 'pointer' : undefined }}
                onMouseEnter={onRowClick ? e => { e.currentTarget.style.background = 'var(--row-hover)'; } : undefined}
                onMouseLeave={onRowClick ? e => { e.currentTarget.style.background = ''; } : undefined}
              >
                {cols.map(c => (
                  <td key={c.key} style={{
                    padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)',
                    ...c.tdStyle,
                  }}>
                    {c.render ? c.render(row) : (row[c.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ── Export ─────────────────────────────────────────────────────────────────

  window.PzDesign = Object.freeze({
    // Nav
    NAV_TREE, NAV_INDEX, NAV_ROUTES, STATUS_MAP,
    // Layout
    AppShell, Sidebar, SubTabStrip, TopBar, PageHeader,
    // Atoms
    EstrellaMark, EstrellaWordmark, Badge, Card, Btn,
    // Modals + forms
    Modal, FormField, Input, Select,
    // Lists + tables
    Sel, CompactTable,
    // Info
    SectionHeader, InfoRow,
    // Utilities
    Toast, EmptyState, SessionBanner,
    // Transport (also on EstrellaShared.apiFetch for pz-api.js compat)
    apiFetch,
  });

  // Announce availability
  if (typeof console !== 'undefined') {
    console.log('[pz-design-v2] loaded — window.PzDesign ready (' + Object.keys(window.PzDesign).length + ' exports)');
  }

})();
