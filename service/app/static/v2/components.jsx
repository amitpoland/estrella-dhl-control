// ── Shared components with thyme palette + CSS variable theming

const GOLD = 'var(--accent)';
const DARK_BG = 'var(--sidebar-bg)';
const SIDEBAR_W = 220;

// Hierarchical nav — simplified flow (7 sections, workflow-first IA).
// Old multi-page modules are folded into tabbed pages; deep-links to legacy
// route slugs still work via tab redirects in the host HTML.
const NAV_TREE = [
  { id: 'dashboard', label: 'Dashboard', icon: '▦' },
  { id: 'inbox',     label: 'Inbox',     icon: '✉', badge: 'NEW' },
  { id: 'shipments', label: 'Shipments', icon: '⬡' },
  // Sprint 31: DHL Hub added as a top-level observer surface so the live
  // read-only DHL renderer is discoverable in the V2 shell. Without this entry,
  // P2 ("operator can observe truth") cannot be satisfied — the page exists
  // but is not reachable. Observer only; Lane A/B remain the sole authority.
  { id: 'dhl',       label: 'DHL',       icon: '✈' },
  { id: 'proforma',  label: 'Pro Forma', icon: '📋' },
  { id: 'documents', label: 'Documents', icon: '📄' },
  { id: 'accounting', label: 'Accounting', icon: '⊞', badge: 'NEW' },
  // Phase B FOLD (2026-07-03, PROJECT_STATE DECISIONS "Phase B FOLD"): the
  // g_inventory NAV group (Stock Hub + Move Location) is COLLAPSED back to a
  // single flat Inventory entry — Move Location was folded into the Inventory
  // page as the Move Stock modal (Lesson M relocation), so there is no second
  // inventory sibling to group. The wireframe's Inventory is one nav entry
  // with tabs/actions inside.
  { id: 'inventory', label: 'Inventory', icon: '◫' },
  { id: 'reports',   label: 'Reports',   icon: '≡' },

  { id: 'g_setup', label: 'Setup', icon: '⚙', defaultId: 'admin', children: [
    { id: 'admin',        label: 'Settings' },
    { id: 'master',       label: 'Master Data' },
    { id: 'carriers',     label: 'Carriers' },
    { id: 'wfirma_setup', label: 'wFirma' },
    { id: 'api_status',   label: 'API Status' },
    { id: 'diagnostics',  label: 'Diagnostics' },
    { id: 'automation',   label: 'Automation' },
    { id: 'intelligence', label: 'Intelligence Hub' },
    { id: 'coverage',     label: 'Coverage Map' },
  ]},
];

// Flat lookup: page id → { group, item } so the SubTabStrip can find
// siblings of the active page without re-walking the tree at every render.
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

// Status badge colors — kept semantic, work in both modes
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
  'Customs Verified':     { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Live':                 { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  'Pending':              { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
};

function Badge({ status, small }) {
  const s = STATUS_MAP[status] || STATUS_MAP['Draft'];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      borderRadius: 4, padding: small ? '1px 6px' : '2px 8px',
      fontSize: small ? 10 : 11, fontWeight: 600, letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{status}</span>
  );
}

// ── Estrella brandmark — modern minimal SVG (rhombus + center stone)
function EstrellaMark({ size = 30 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" style={{ display: 'block', flexShrink: 0 }}>
      {/* Outer rhombus — thin gold outline (jewel setting) */}
      <path d="M20 3 L37 20 L20 37 L3 20 Z"
            fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round"/>
      {/* Inner stone — solid gold rhombus */}
      <path d="M20 13 L27 20 L20 27 L13 20 Z" fill="var(--accent)"/>
      {/* Highlight line — single facet */}
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

function Sidebar({ active, onNav, collapsed, onToggle }) {
  // A group is "open" when one of its children is the active page.
  // User can also manually expand by clicking the group header.
  const activeGroup = NAV_INDEX[active]?.group?.id;
  const [openGroups, setOpenGroups] = React.useState(() => {
    const init = {};
    if (activeGroup) init[activeGroup] = true;
    return init;
  });
  React.useEffect(() => {
    if (activeGroup) setOpenGroups(g => ({ ...g, [activeGroup]: true }));
  }, [activeGroup]);

  const rowStyle = (isActive, isChild) => ({
    width: '100%', display: 'flex', alignItems: 'center',
    gap: 10, padding: collapsed ? '9px 14px' : (isChild ? '7px 16px 7px 44px' : '9px 16px'),
    background: isActive ? 'var(--sidebar-active)' : 'transparent',
    border: 'none', cursor: 'pointer', textAlign: 'left',
    borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
    transition: 'background 0.15s',
  });

  return (
    <aside style={{
      width: collapsed ? 52 : SIDEBAR_W, minWidth: collapsed ? 52 : SIDEBAR_W,
      background: 'var(--sidebar-bg)', display: 'flex', flexDirection: 'column',
      transition: 'width 0.2s, min-width 0.2s', overflow: 'hidden', zIndex: 10,
      borderRight: '1px solid var(--sidebar-border)',
    }}>
      {/* Logo — inline SVG brandmark */}
      <div style={{
        padding: collapsed ? '20px 8px' : '20px 18px',
        borderBottom: '1px solid var(--sidebar-border)',
        display: 'flex', alignItems: 'center', gap: 12, minHeight: 72,
        justifyContent: collapsed ? 'center' : 'flex-start',
      }}>
        <EstrellaMark size={collapsed ? 26 : 32}/>
        <EstrellaWordmark collapsed={collapsed}/>
      </div>

      {/* Nav — grouped */}
      <nav style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
        {NAV_TREE.map(node => {
          // Leaf row
          if (!node.children) {
            const isActive = active === node.id;
            return (
              <button key={node.id} onClick={() => onNav(node.id)}
                style={rowStyle(isActive, false)}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}>
                <span style={{ color: isActive ? 'var(--accent)' : 'var(--sidebar-icon)', fontSize: 14, minWidth: 18, textAlign: 'center' }}>{node.icon}</span>
                {!collapsed && <span style={{ color: isActive ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)', fontSize: 12, fontWeight: isActive ? 600 : 400, letterSpacing: '0.01em' }}>{node.label}</span>}
              </button>
            );
          }
          // Group row + children
          const open       = !!openGroups[node.id];
          const groupHot   = node.children.some(c => c.id === active);
          const childActiveCount = node.children.filter(c => c.id === active).length;
          return (
            <div key={node.id}>
              <button onClick={() => {
                  if (collapsed) {
                    // Collapsed sidebar: clicking a group jumps to its default child
                    onNav(node.defaultId || node.children[0].id);
                  } else {
                    setOpenGroups(g => ({ ...g, [node.id]: !g[node.id] }));
                  }
                }}
                style={rowStyle(false, false)}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}>
                <span style={{
                  color: groupHot ? 'var(--accent)' : 'var(--sidebar-icon)',
                  fontSize: 14, minWidth: 18, textAlign: 'center',
                }}>{node.icon}</span>
                {!collapsed && (
                  <>
                    <span style={{
                      color: groupHot ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)',
                      fontSize: 12, fontWeight: groupHot ? 600 : 500, letterSpacing: '0.01em', flex: 1,
                    }}>{node.label}</span>
                    <span style={{
                      fontSize: 10, color: 'var(--sidebar-text-muted)',
                      transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
                      transition: 'transform 0.15s', marginRight: 2,
                    }}>›</span>
                  </>
                )}
              </button>

              {/* Children — only when expanded and sidebar not collapsed */}
              {!collapsed && open && node.children.map(child => {
                const ca = active === child.id;
                return (
                  <button key={child.id} onClick={() => onNav(child.id)}
                    style={rowStyle(ca, true)}
                    onMouseEnter={e => { if (!ca) e.currentTarget.style.background = 'var(--sidebar-hover)'; }}
                    onMouseLeave={e => { if (!ca) e.currentTarget.style.background = 'transparent'; }}>
                    <span style={{
                      color: ca ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)',
                      fontSize: 11.5, fontWeight: ca ? 600 : 400, flex: 1,
                    }}>{child.label}</span>
                    {child.badge && (
                      <span style={{
                        fontSize: 8.5, fontWeight: 700, letterSpacing: '0.06em',
                        background: 'var(--accent)', color: 'var(--accent-text)',
                        padding: '1px 5px', borderRadius: 3, marginRight: 4,
                      }}>{child.badge}</span>
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
      }}>{collapsed ? '›' : '‹'}</button>
    </aside>
  );
}

// SubTabStrip — horizontal sibling-nav shown below the page header
// when the active page is a child of a NAV_TREE group.
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
          <button key={s.id} onClick={() => onNav(s.id)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '10px 14px 11px', fontSize: 12,
            fontWeight: isActive ? 700 : 500,
            color: isActive ? 'var(--text)' : 'var(--text-2)',
            borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1, letterSpacing: '0.01em', whiteSpace: 'nowrap',
            display: 'inline-flex', alignItems: 'center', gap: 6,
          }}>
            {s.label}
            {s.badge && (
              <span style={{
                fontSize: 8.5, fontWeight: 700, letterSpacing: '0.06em',
                background: 'var(--accent)', color: 'var(--accent-text)',
                padding: '1px 5px', borderRadius: 3,
              }}>{s.badge}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function TopBar({ onNewShipment, onToggleDark, isDark, onOpenSearch }) {
  return (
    <header style={{
      height: 56, background: 'var(--card)',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: '0 24px', gap: 16, flexShrink: 0,
    }}>
      <button onClick={onOpenSearch} style={{
        flex: 1, maxWidth: 360, display: 'flex', alignItems: 'center', gap: 10,
        background: 'var(--bg-subtle)', border: '1px solid var(--border)',
        borderRadius: 6, padding: '7px 12px', cursor: 'pointer',
        color: 'var(--text-3)', fontSize: 12, fontFamily: 'inherit',
      }}>
        <span style={{ fontSize: 13 }}>⌕</span>
        <span style={{ flex: 1, textAlign: 'left' }}>Search AWB, PI, INV, client…</span>
        <span style={{
          fontFamily: 'monospace', fontSize: 9.5, padding: '1px 5px',
          background: 'var(--card)', border: '1px solid var(--border)',
          borderRadius: 3, fontWeight: 600,
        }}>⌘K</span>
      </button>
      <div style={{ flex: 1 }} />

      {/* Dark mode toggle */}
      <button onClick={onToggleDark} title={isDark ? 'Switch to Light' : 'Switch to Dark'} style={{
        background: 'var(--bg-subtle)', border: '1px solid var(--border)',
        borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
        fontSize: 14, color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: 4,
      }}>
        {isDark ? '☀' : '🌿'}
      </button>

      <button onClick={onNewShipment} style={{
        display: 'flex', alignItems: 'center', gap: 6,
        background: 'var(--accent)', color: 'var(--accent-text)',
        border: 'none', borderRadius: 6,
        padding: '7px 14px', fontSize: 12, fontWeight: 700,
        cursor: 'pointer', letterSpacing: '0.02em',
      }}>
        <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New Shipment
      </button>

      <button style={{ background: 'none', border: 'none', cursor: 'pointer', position: 'relative', padding: 4 }}>
        <span style={{ fontSize: 18, color: 'var(--text-2)' }}>🔔</span>
        <span style={{ position: 'absolute', top: 2, right: 2, width: 8, height: 8, borderRadius: '50%', background: '#C0321A', border: '1.5px solid var(--card)' }}></span>
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
        <div style={{
          width: 30, height: 30, borderRadius: '50%',
          background: 'linear-gradient(135deg, var(--accent), var(--accent-light))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 12, fontWeight: 700, color: 'var(--accent-text)',
        }}>A</div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>Admin</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)' }}>Super User</div>
        </div>
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>▾</span>
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

// No spread-rest (PROJECT_STATE DECISIONS "V2-wide spread-rest collision
// sweep"): Babel-standalone hoists `_excluded` to global scope and a
// later-loaded file overwrites it. Explicit 'data-testid' destructuring is
// census-complete (Card only ever receives data-testid) and collision-safe.
function Card({ children, style, onClick, 'data-testid': testid }) {
  return (
    <div onClick={onClick} data-testid={testid} style={{
      background: 'var(--card)', borderRadius: 8,
      border: '1px solid var(--border)',
      boxShadow: '0 1px 3px var(--shadow)',
      ...style,
    }}>{children}</div>
  );
}

// Forwards data-testid / title / aria-label to the <button> — same contract
// as the Btn in v2/dashboard-shared.js (without which a data-testid on a Btn
// usage silently vanishes). Explicit destructuring, NOT spread-rest: the
// _excluded global-hoist collision (DECISIONS "V2-wide spread-rest collision
// sweep") forbids `...rest` in V2 JSX; the census confirms these three attrs
// are the complete forwarded set.
function Btn({ children, onClick, variant = 'default', small, disabled, style: extraStyle, 'data-testid': testid, title, 'aria-label': ariaLabel }) {
  const variants = {
    default: { background: 'var(--text)', color: 'var(--card)', border: '1px solid var(--text)' },
    // `primary` = alias for gold/accent (C20A parity with the Btn in v2/dashboard-shared.js).
    // Unknown variants fall back to `default` navy, which silently un-styled primary CTAs.
    primary: { background: 'var(--accent)', color: 'var(--accent-text)', border: '1px solid var(--accent)' },
    gold:    { background: 'var(--accent)', color: 'var(--accent-text)', border: '1px solid var(--accent)' },
    outline: { background: 'transparent', color: 'var(--text)', border: '1px solid var(--border)' },
    ghost:   { background: 'transparent', color: 'var(--text-2)', border: '1px solid transparent' },
    danger:  { background: 'var(--badge-red-bg)', color: 'var(--badge-red-text)', border: '1px solid var(--badge-red-border)' },
    success: { background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)', border: '1px solid var(--badge-green-border)' },
  };
  const v = variants[variant] || variants.default;
  return (
    <button onClick={onClick} disabled={disabled} data-testid={testid} title={title} aria-label={ariaLabel} style={{
      ...v, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
      padding: small ? '4px 10px' : '7px 14px',
      fontSize: small ? 11 : 12, fontWeight: 600,
      opacity: disabled ? 0.45 : 1,
      display: 'inline-flex', alignItems: 'center', gap: 4,
      whiteSpace: 'nowrap', transition: 'opacity 0.15s',
      ...extraStyle,
    }}>{children}</button>
  );
}

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
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{title}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-3)' }}>×</button>
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

// Explicit 'data-testid' destructuring, NOT spread-rest (DECISIONS "V2-wide
// spread-rest collision sweep"). Census: Input only receives data-testid.
function Input({ value, onChange, placeholder, type = 'text', style: s, 'data-testid': testid }) {
  return (
    <input value={value} onChange={onChange} placeholder={placeholder} type={type} data-testid={testid} style={{
      width: '100%', padding: '8px 10px', borderRadius: 6,
      border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
      background: 'var(--bg-subtle)', outline: 'none', boxSizing: 'border-box', ...s,
    }} />
  );
}

function Select({ value, onChange, children, style: s }) {
  return (
    <select value={value} onChange={onChange} style={{
      width: '100%', padding: '8px 10px', borderRadius: 6,
      border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
      background: 'var(--bg-subtle)', outline: 'none', boxSizing: 'border-box', ...s,
    }}>{children}</select>
  );
}

function SectionHeader({ icon, title, subtitle, status }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '14px 20px', borderBottom: '1px solid var(--border)',
      background: 'var(--bg-subtle)',
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 6,
        background: 'var(--accent-subtle)',
        border: '1px solid var(--accent-border)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 14, color: 'var(--accent)',
      }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 1 }}>{subtitle}</div>}
      </div>
      {status && <Badge status={status} />}
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

Object.assign(window, {
  Badge, Sidebar, TopBar, PageHeader, Card, Btn, Modal,
  FormField, Input, Select, SectionHeader, InfoRow,
  STATUS_MAP, GOLD, DARK_BG, NAV_TREE, NAV_INDEX, SubTabStrip,
});
