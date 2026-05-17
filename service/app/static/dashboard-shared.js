// dashboard-shared.js — Phase 1 shared frontend utilities.
//
// Loaded by dashboard.html via:
//   <script type="text/babel" data-presets="env,react"
//           src="/dashboard/dashboard-shared.js"></script>
// MUST be placed BEFORE the main Babel block — destructuring downstream
// depends on window.EstrellaShared being set by the time it runs.
//
// Surfaces 8 utilities on window.EstrellaShared:
//   apiFetch, fmtPLN,
//   Badge, Card, Btn, Sel, Toast, SessionBanner
//
// Hard rules for this module:
//   - no backend URLs
//   - no app-specific config (NAV_TREE, ROUTE_REDIRECTS, etc.)
//   - no Sidebar / no App / no BatchDetailPage
//   - bodies copied byte-for-byte from dashboard.html so Phase 1
//     introduces zero behaviour drift.
//
// Note on STATUS_MAP: Badge depends on a STATUS_MAP lookup table. The
// shared module carries its OWN copy (frozen below) so this file has no
// implicit file-scope dependency on dashboard.html. dashboard.html
// keeps its own STATUS_MAP for callers outside Badge (e.g. inline pill
// rendering elsewhere). The two copies must be kept in sync; this is
// the only intentional duplication introduced by Phase 1.

(function () {
  'use strict';

  // ── HTTP helper ─────────────────────────────────────────────────────
  async function apiFetch(url, opts = {}) {
    let res;
    try {
      res = await fetch(url, { credentials: 'include', ...opts });
    } catch (netErr) {
      // Network-level failure (service down, no connection)
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

  // ── Currency formatter ─────────────────────────────────────────────
  function fmtPLN(n) {
    if (n == null || n === '') return '—';
    const num = Number(n);
    if (isNaN(num)) return '—';
    return 'PLN ' + num.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // ── Status pill lookup (private copy; see header note) ─────────────
  const STATUS_MAP = Object.freeze({
    'Draft':                 { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'In Transit':            { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Pre-check Pending':     { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Pre-check Completed':   { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Awaiting DHL Email':    { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
    'DHL Email Received':    { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Reply Sent':            { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Reply Queued':          { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'SAD Pending':           { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'SAD Uploaded':          { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Customs Parsed':        { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Verification Needed':   { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    'Customs Verified':      { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Locked':                { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'Ready for PZ':          { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Generated':             { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Ready for Booking':     { bg: 'var(--badge-purple-bg)',  text: 'var(--badge-purple-text)',  border: 'var(--badge-purple-border)' },
    'Exported':              { bg: 'var(--badge-accent-bg)',  text: 'var(--badge-accent-text)',  border: 'var(--badge-accent-border)' },
    'Awaiting DHL':          { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Awaiting SAD':          { bg: 'var(--badge-orange-bg)',  text: 'var(--badge-orange-text)',  border: 'var(--badge-orange-border)' },
    'Action Required':       { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    'In Preparation':        { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    'Completed':             { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Pending':               { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    'Live':                  { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    'Awaiting Clearance':    { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Processing':            { bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    'Reply Package Prepared':{ bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  });

  // ── Base components ────────────────────────────────────────────────
  function Badge({ status, small, title }) {
    const s = STATUS_MAP[status] || { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
    return (
      <span title={title || undefined} style={{
        display: 'inline-flex', alignItems: 'center',
        background: s.bg, color: s.text, border: `1px solid ${s.border}`,
        borderRadius: 4, padding: small ? '1px 6px' : '2px 8px',
        fontSize: small ? 10 : 11, fontWeight: 600, letterSpacing: '0.03em', whiteSpace: 'nowrap',
        cursor: title ? 'help' : undefined,
      }}>{status || 'Unknown'}</span>
    );
  }

  function Card({ children, style, onClick }) {
    return (
      <div onClick={onClick} style={{
        background: 'var(--card)', borderRadius: 8,
        border: '1px solid var(--border)',
        boxShadow: '0 1px 3px var(--shadow)', ...style,
      }}>{children}</div>
    );
  }

  function Btn({ children, onClick, variant = 'default', small, disabled, style: xs }) {
    const variants = {
      default: { background: 'var(--text)', color: 'var(--card)', border: '1px solid var(--text)' },
      gold:    { background: 'var(--accent)', color: 'var(--accent-text)', border: '1px solid var(--accent)' },
      outline: { background: 'transparent', color: 'var(--text)', border: '1px solid var(--border)' },
      ghost:   { background: 'transparent', color: 'var(--text-2)', border: '1px solid transparent' },
      danger:  { background: 'var(--badge-red-bg)', color: 'var(--badge-red-text)', border: '1px solid var(--badge-red-border)' },
      success: { background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)', border: '1px solid var(--badge-green-border)' },
    };
    const v = variants[variant] || variants.default;
    return (
      <button onClick={onClick} disabled={disabled} style={{
        ...v, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
        padding: small ? '4px 10px' : '7px 14px',
        fontSize: small ? 11 : 12, fontWeight: 600,
        opacity: disabled ? 0.45 : 1,
        display: 'inline-flex', alignItems: 'center', gap: 4,
        whiteSpace: 'nowrap', transition: 'opacity 0.15s',
        fontFamily: 'inherit', ...xs,
      }}>{children}</button>
    );
  }

  function Sel({ value, onChange, children, ...rest }) {
    // Forward arbitrary props (e.g., data-testid) so callers can target
    // the rendered <select> from the browser DOM. Additive; existing
    // callers unaffected.
    return (
      <select value={value} onChange={onChange} {...rest} style={{
        width: '100%', padding: '8px 10px', borderRadius: 6,
        border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
        background: 'var(--bg-subtle)', outline: 'none',
        boxSizing: 'border-box', fontFamily: 'inherit',
      }}>{children}</select>
    );
  }

  function Toast({ msg, type }) {
    const colors = { success: 'var(--badge-green-text)', info: 'var(--badge-blue-text)', error: 'var(--badge-red-text)', warn: 'var(--badge-amber-text)' };
    return (
      <div style={{
        position: 'fixed', top: 70, right: 24, zIndex: 9999,
        background: colors[type] || colors.info,
        color: '#fff', padding: '10px 18px', borderRadius: 8,
        fontSize: 12, fontWeight: 600, boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        animation: 'fadeIn 0.2s', maxWidth: 380, wordBreak: 'break-word',
      }}>{msg}</div>
    );
  }

  function SessionBanner({ type, onDismiss }) {
    // type: 'auth' | 'network'
    const isAuth = type === 'auth';
    return (
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
        background: isAuth ? '#7A2000' : '#4A3A00',
        color: '#FFF', padding: '10px 20px',
        display: 'flex', alignItems: 'center', gap: 12,
        fontSize: 13, fontWeight: 500, boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        animation: 'fadeIn 0.2s ease',
      }}>
        <span style={{ fontSize: 16 }}>{isAuth ? '🔒' : '⚠️'}</span>
        <span style={{ flex: 1 }}>
          {isAuth
            ? 'Session expired or access denied.'
            : 'Service unreachable — the backend may be down.'}
          {' '}
          {isAuth
            ? <a href="/login" style={{ color: '#FFD080', textDecoration: 'underline' }}>Sign in again</a>
            : <span style={{ color: '#FFD080', cursor: 'pointer', textDecoration: 'underline' }}
                onClick={() => window.location.reload()}>Retry</span>}
        </span>
        {onDismiss && (
          <button onClick={onDismiss} style={{
            background: 'none', border: 'none', color: '#FFF', cursor: 'pointer',
            fontSize: 16, padding: '0 4px', lineHeight: 1,
          }}>✕</button>
        )}
      </div>
    );
  }

  // ── Phase 1B — sidebar shell primitives ─────────────────────────────
  // EstrellaMark, SubTabStrip, and Sidebar live here so a future
  // shipment-detail.html can render an identical nav chrome. Sidebar
  // is prop-driven (navTree) — it does NOT close over NAV_TREE /
  // NAV_INDEX / ROUTE_REDIRECTS / navGroupOf (those remain
  // dashboard-specific app config in dashboard.html).

  const _DEFAULT_SIDEBAR_W = 220;

  // Private helper — mirrors dashboard.html's navGroupOf but operates
  // on whatever navTree the caller passes. Keeps Sidebar self-contained
  // inside the shared IIFE.
  function _findActiveGroup(navTree, active) {
    if (!Array.isArray(navTree)) return null;
    for (const n of navTree) {
      if (n.children && n.children.some(c => c.id === active)) return n;
    }
    return null;
  }

  function EstrellaMark({ size = 32 }) {
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" style={{ flexShrink: 0 }}>
        <path d="M20 3 L37 20 L20 37 L3 20 Z" fill="none" stroke="var(--accent)" strokeWidth="1.6"/>
        <path d="M20 13 L27 20 L20 27 L13 20 Z" fill="var(--accent)"/>
        <path d="M16.5 16.5 L23.5 16.5" stroke="var(--sidebar-bg)" strokeWidth="0.8" opacity="0.5"/>
      </svg>
    );
  }

  function SubTabStrip({ group, active, onNav }) {
    if (!group || !group.children) return null;
    return (
      <div style={{ display: 'flex', gap: 2, padding: '0 32px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', flexShrink: 0, overflowX: 'auto' }}>
        {group.children.map(child => {
          const isActive = active === child.id;
          return (
            <button key={child.id} onClick={() => child.href ? (window.location.href = child.href) : onNav(child.id)} style={{
              padding: '8px 14px', border: 'none', cursor: 'pointer',
              background: 'transparent', fontFamily: 'inherit', fontSize: 12, fontWeight: isActive ? 600 : 400,
              color: isActive ? 'var(--accent)' : 'var(--text-2)',
              borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'color 0.15s', whiteSpace: 'nowrap',
            }}>{child.label}</button>
          );
        })}
      </div>
    );
  }

  function Sidebar({ active, onNav, collapsed, onToggle, navTree, width }) {
    // Defensive defaults so a caller that forgets navTree degrades to
    // an empty sidebar instead of throwing.
    const tree = Array.isArray(navTree) ? navTree : [];
    const W = typeof width === 'number' ? width : _DEFAULT_SIDEBAR_W;

    const [openGroups, setOpenGroups] = React.useState(() => {
      const init = {};
      tree.forEach(n => { if (n.children) { init[n.id] = n.children.some(c => c.id === active); } });
      return init;
    });

    const toggleGroup = (id) => setOpenGroups(g => ({ ...g, [id]: !g[id] }));

    const activeGroup = _findActiveGroup(tree, active);

    return (
      <aside style={{
        width: collapsed ? 52 : W, minWidth: collapsed ? 52 : W,
        background: 'var(--sidebar-bg)', display: 'flex', flexDirection: 'column',
        transition: 'width 0.2s,min-width 0.2s', overflow: 'hidden', zIndex: 10,
        borderRight: '1px solid var(--sidebar-border)',
      }}>
        <div style={{ padding: '16px 14px', borderBottom: '1px solid var(--sidebar-border)', display: 'flex', alignItems: 'center', gap: 10, minHeight: 60 }}>
          <EstrellaMark size={collapsed ? 28 : 30} />
          {!collapsed && (
            <div style={{ overflow: 'hidden' }}>
              <div style={{ color: 'var(--sidebar-text)', fontSize: 13, fontWeight: 700, letterSpacing: '0.04em', fontFamily: '"DM Serif Display",serif', lineHeight: 1.2 }}>Estrella</div>
              <div style={{ color: 'var(--accent)', fontSize: 9, letterSpacing: '0.12em', marginTop: 1, opacity: 0.85 }}>ATLAS</div>
            </div>
          )}
        </div>
        <nav style={{ flex: 1, padding: '6px 0', overflowY: 'auto' }}>
          {tree.map(item => {
            const isLeafActive = active === item.id;
            const isGroupActive = !!(item.children && item.children.some(c => c.id === active));
            const isOpen = openGroups[item.id];

            if (item.children) {
              return (
                <React.Fragment key={item.id}>
                  <button onClick={() => { toggleGroup(item.id); if (!isOpen && !isGroupActive) onNav(item.defaultId || item.children[0].id); }}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center',
                      gap: 10, padding: collapsed ? '9px 14px' : '9px 16px',
                      background: isGroupActive ? 'var(--sidebar-active)' : 'transparent',
                      border: 'none', cursor: 'pointer', textAlign: 'left',
                      borderLeft: isGroupActive ? '2px solid var(--accent)' : '2px solid transparent',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => { if (!isGroupActive) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                    onMouseLeave={e => { if (!isGroupActive) e.currentTarget.style.background = isGroupActive ? 'var(--sidebar-active)' : 'transparent'; }}
                  >
                    <span style={{ color: isGroupActive ? 'var(--accent)' : 'var(--sidebar-icon)', fontSize: 14, minWidth: 18, textAlign: 'center' }}>{item.icon}</span>
                    {!collapsed && <>
                      <span style={{ flex: 1, color: isGroupActive ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 12, fontWeight: isGroupActive ? 600 : 400 }}>{item.label}</span>
                      <span style={{ color: 'var(--sidebar-text-muted)', fontSize: 10 }}>{isOpen ? '▾' : '▸'}</span>
                    </>}
                  </button>
                  {!collapsed && isOpen && item.children.map(child => {
                    const isChildActive = active === child.id;
                    return (
                      <button key={child.id} onClick={() => child.href ? (window.location.href = child.href) : onNav(child.id)} style={{
                        width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                        padding: '7px 16px 7px 42px',
                        background: isChildActive ? 'var(--sidebar-active)' : 'transparent',
                        border: 'none', cursor: 'pointer', textAlign: 'left',
                        borderLeft: isChildActive ? '2px solid var(--accent)' : '2px solid transparent',
                        transition: 'background 0.15s',
                      }}
                        onMouseEnter={e => { if (!isChildActive) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                        onMouseLeave={e => { if (!isChildActive) e.currentTarget.style.background = 'transparent'; }}
                      >
                        <span style={{ color: isChildActive ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 11, fontWeight: isChildActive ? 600 : 400 }}>{child.label}</span>
                      </button>
                    );
                  })}
                </React.Fragment>
              );
            }

            return (
              <button key={item.id} onClick={() => onNav(item.id)} style={{
                width: '100%', display: 'flex', alignItems: 'center',
                gap: 10, padding: collapsed ? '9px 14px' : '9px 16px',
                background: isLeafActive ? 'var(--sidebar-active)' : 'transparent',
                border: 'none', cursor: 'pointer', textAlign: 'left',
                borderLeft: isLeafActive ? '2px solid var(--accent)' : '2px solid transparent',
                transition: 'background 0.15s',
              }}
                onMouseEnter={e => { if (!isLeafActive) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                onMouseLeave={e => { if (!isLeafActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ color: isLeafActive ? 'var(--accent)' : 'var(--sidebar-icon)', fontSize: 14, minWidth: 18, textAlign: 'center' }}>{item.icon}</span>
                {!collapsed && <span style={{ color: isLeafActive ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 12, fontWeight: isLeafActive ? 600 : 400 }}>{item.label}</span>}
              </button>
            );
          })}
        </nav>
        <button onClick={onToggle} style={{ padding: '12px 16px', background: 'transparent', border: 'none', borderTop: '1px solid var(--sidebar-border)', cursor: 'pointer', color: 'var(--sidebar-icon)', fontSize: 12, display: 'flex', justifyContent: collapsed ? 'center' : 'flex-end' }}>
          {collapsed ? '›' : '‹'}
        </button>
      </aside>
    );
  }

  // ── Export ─────────────────────────────────────────────────────────
  window.EstrellaShared = Object.freeze({
    apiFetch, fmtPLN,
    Badge, Card, Btn, Sel, Toast, SessionBanner,
    EstrellaMark, SubTabStrip, Sidebar,
  });
})();
