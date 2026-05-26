// atlas-shared.js — Atlas V2 shared visual primitives.
//
// Hard rules (binding):
//   - Visual primitives only. NO domain knowledge.
//   - NO backend URLs. NO direct fetch. NO business logic.
//   - Consumers pass data in via props; this module renders it.
//   - Surfaces `window.AtlasShared`. Loaded by every page under
//     /dashboard/atlas/<page>-v2.html.
//
// Authority: this module DOES NOT REPLACE or modify dashboard-shared.js.
// dashboard-shared.js (V1 + V2 atoms, no domain) stays the canonical visual
// atom library for the project. atlas-shared.js adds Atlas-specific layouts
// (PageHeader, KPI, Lane, Card, Empty/Loading/Error blocks) that match the
// Estrella Atlas design system.
//
// Stack constraint reminder: Babel standalone + UMD React 18.
// No bundler, no TypeScript, no Tailwind. CSS custom properties only.

(function () {
  'use strict';

  // ── Inject Atlas V2 CSS tokens + global styles once ─────────────────
  function injectStyles() {
    if (document.getElementById('atlas-v2-styles')) return;
    const css = `
      *, *::before, *::after { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; }
      body {
        font-family: 'Plus Jakarta Sans', -apple-system, system-ui, sans-serif;
        background: var(--bg); color: var(--text);
        min-height: 100vh; font-size: 13px;
      }
      #root { display: flex; flex-direction: column; min-height: 100vh; }
      ::-webkit-scrollbar { width: 5px; height: 5px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

      :root {
        --bg: #F4F1EA; --bg-subtle: #FAF8F2; --card: #FFFFFF;
        --row-hover: #F6F2EA; --border: #E5DECF; --border-subtle: #EFE9DA;
        --text: #1B2538; --text-2: #4E5A72; --text-3: #8B97AE;
        --shadow: rgba(27,37,56,0.06); --shadow-heavy: rgba(27,37,56,0.16);
        --accent: #B89968; --accent-light: #D4B884; --accent-text: #1B2538;
        --accent-subtle: #F8EFD8; --accent-border: #CFB178;
        --badge-neutral-bg: #EEF0F4; --badge-neutral-text: #4A5A70; --badge-neutral-border: #CED4E0;
        --badge-blue-bg: #E8EFF8;   --badge-blue-text: #1A4A90;   --badge-blue-border: #AABEE0;
        --badge-amber-bg: #FBF5E0;  --badge-amber-text: #805A00;  --badge-amber-border: #DEC870;
        --badge-orange-bg: #FBF0E4; --badge-orange-text: #804000; --badge-orange-border: #DEB870;
        --badge-green-bg: #E8F5EE;  --badge-green-text: #186838;  --badge-green-border: #96CCA8;
        --badge-red-bg: #FBE8E6;    --badge-red-text: #902018;    --badge-red-border: #E0A8A0;
        --badge-purple-bg: #EEE8F8; --badge-purple-text: #481898; --badge-purple-border: #BEA4E8;
        --badge-accent-bg: #131C2E; --badge-accent-text: #B89968; --badge-accent-border: #B89968;
        --sidebar-bg: #131C2E; --sidebar-border: #25334C;
      }

      @media (prefers-color-scheme: dark) {
        :root {
          --bg: #111928; --bg-subtle: #172030; --card: #1C2638;
          --row-hover: #223040; --border: #2C3C54; --border-subtle: #243050;
          --text: #EEE8DC; --text-2: #8A9AB6; --text-3: #566478;
          --shadow: rgba(0,0,0,0.3); --shadow-heavy: rgba(0,0,0,0.5);
          --accent: #D4AA5C; --accent-light: #ECC870; --accent-text: #111928;
          --accent-subtle: #1E2808; --accent-border: #5A4A18;
          --badge-neutral-bg: #1C2838; --badge-neutral-text: #8A9AB6; --badge-neutral-border: #2C3C54;
          --badge-blue-bg: #0E1E38;   --badge-blue-text: #80AAEE;   --badge-blue-border: #1E3A64;
          --badge-amber-bg: #20180A;  --badge-amber-text: #E8C040;  --badge-amber-border: #584010;
          --badge-orange-bg: #201008; --badge-orange-text: #E89860; --badge-orange-border: #582010;
          --badge-green-bg: #0E2018;  --badge-green-text: #68CC88;  --badge-green-border: #1A4830;
          --badge-red-bg: #200E10;    --badge-red-text: #EE8880;    --badge-red-border: #581018;
          --badge-purple-bg: #160E28; --badge-purple-text: #AA88EE; --badge-purple-border: #341860;
        }
      }

      .atlas-header { padding: 22px 32px 14px; border-bottom: 1px solid var(--border-subtle); background: var(--card); }
      .atlas-h1 { margin: 0; font-size: 22px; font-weight: 700; font-family: 'DM Serif Display', serif; color: var(--text); letter-spacing: 0.005em; }
      .atlas-sub { margin: 4px 0 0; font-size: 11.5px; color: var(--text-3); }
      .atlas-header-row { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
      .atlas-actions { display: flex; gap: 8px; flex-wrap: wrap; }
      .atlas-content { padding: 20px 32px 40px; flex: 1; }
      .atlas-tier-banner { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; padding: 8px 12px; background: var(--badge-amber-bg); border: 1px solid var(--badge-amber-border); color: var(--badge-amber-text); border-radius: 6px; font-size: 11.5px; }

      .atlas-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 6px; font-size: 11.5px; font-weight: 600; font-family: inherit; cursor: pointer; transition: background 0.15s, opacity 0.15s; line-height: 1.3; }
      .atlas-btn-primary { background: var(--accent); color: var(--accent-text); border: 1px solid var(--accent-border); }
      .atlas-btn-primary:hover:not(:disabled) { background: var(--accent-light); }
      .atlas-btn-outline { background: transparent; color: var(--text-2); border: 1px solid var(--border); }
      .atlas-btn-outline:hover:not(:disabled) { background: var(--bg-subtle); }
      .atlas-btn-ghost { background: transparent; color: var(--text-2); border: 1px solid transparent; }
      .atlas-btn-ghost:hover:not(:disabled) { background: var(--bg-subtle); }
      .atlas-btn:disabled { cursor: not-allowed; opacity: 0.55; }
      .atlas-btn.small { padding: 5px 10px; font-size: 11px; }

      .atlas-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
      .atlas-empty { padding: 40px; text-align: center; color: var(--text-3); background: var(--card); border: 1px dashed var(--border); border-radius: 8px; font-size: 12px; }
      .atlas-error { padding: 10px 14px; background: var(--badge-red-bg); border: 1px solid var(--badge-red-border); border-radius: 6px; color: var(--badge-red-text); font-size: 12px; margin-bottom: 14px; }
      .atlas-loading { padding: 40px; text-align: center; color: var(--text-3); font-size: 12px; }

      .atlas-spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: atlas-spin 0.7s linear infinite; vertical-align: middle; }
      @keyframes atlas-spin { to { transform: rotate(360deg); } }
      @keyframes atlas-fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

      .atlas-section-title { font-size: 10.5px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
      .atlas-h2 { margin: 0; font-size: 16px; font-weight: 700; color: var(--text); }

      .atlas-table { width: 100%; border-collapse: collapse; font-size: 12px; }
      .atlas-table th { text-align: left; padding: 8px 12px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px; background: var(--bg-subtle); border-bottom: 1px solid var(--border); }
      .atlas-table td { padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); color: var(--text); }
      .atlas-table tr:hover td { background: var(--row-hover); }

      .atlas-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 4px; font-size: 10.5px; font-weight: 600; letter-spacing: 0.02em; white-space: nowrap; border: 1px solid; }

      .atlas-kpi { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; }
      .atlas-kpi-label { font-size: 9.5px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.08em; }
      .atlas-kpi-value { font-size: 22px; font-weight: 700; margin-top: 4px; font-family: 'DM Serif Display', serif; color: var(--text); }
      .atlas-kpi-hint { font-size: 10px; color: var(--text-3); margin-top: 2px; }

      .atlas-nav-strip { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 32px; background: var(--bg-subtle); border-bottom: 1px solid var(--border-subtle); }
      .atlas-nav-link { padding: 4px 10px; border-radius: 4px; font-size: 11px; color: var(--text-2); text-decoration: none; border: 1px solid transparent; }
      .atlas-nav-link:hover { background: var(--card); border-color: var(--border); }
      .atlas-nav-link.current { background: var(--card); border-color: var(--border); color: var(--text); font-weight: 600; }

      @media (max-width: 1100px) {
        .atlas-grid-4 { grid-template-columns: repeat(2, 1fr) !important; }
        .atlas-kpi-strip { grid-template-columns: repeat(3, 1fr) !important; }
      }
      @media (max-width: 700px) {
        .atlas-header { padding: 16px 16px 12px; }
        .atlas-content { padding: 14px 16px 30px; }
        .atlas-grid-4 { grid-template-columns: 1fr !important; }
        .atlas-kpi-strip { grid-template-columns: repeat(2, 1fr) !important; }
        .atlas-nav-strip { padding: 8px 16px; overflow-x: auto; flex-wrap: nowrap; }
      }
    `;
    const tag = document.createElement('style');
    tag.id = 'atlas-v2-styles';
    tag.textContent = css;
    document.head.appendChild(tag);
  }

  // ── Cross-page nav strip (Phase One Atlas pages) ───────────────────
  const ATLAS_PAGES = [
    { id: 'dashboard',   label: 'Dashboard',   href: '/dashboard/atlas/dashboard-v2.html' },
    { id: 'inbox',       label: 'Inbox',       href: '/dashboard/atlas/inbox-v2.html' },
    { id: 'shipments',   label: 'Shipments',   href: '/dashboard/atlas/shipments-v2.html' },
    { id: 'documents',   label: 'Documents',   href: '/dashboard/atlas/documents-v2.html' },
    { id: 'pz',          label: 'PZ',          href: '/dashboard/atlas/pz-v2.html' },
    { id: 'proforma',    label: 'Proforma',    href: '/dashboard/atlas/proforma-v2.html' },
    { id: 'accounting',  label: 'Accounting',  href: '/dashboard/atlas/accounting-v2.html' },
    { id: 'ledgers',     label: 'Ledgers',     href: '/dashboard/atlas/ledgers-v2.html' },
    { id: 'search',      label: 'Search',      href: '/dashboard/atlas/search-v2.html' },
    { id: 'api_status',  label: 'API Status',  href: '/dashboard/atlas/api-status-v2.html' },
  ];

  function NavStrip({ current }) {
    return (
      <nav className="atlas-nav-strip" data-testid="atlas-nav-strip" aria-label="Atlas V2 navigation">
        {ATLAS_PAGES.map(p => (
          <a key={p.id} href={p.href}
             data-testid={`atlas-nav-${p.id}`}
             className={`atlas-nav-link${current === p.id ? ' current' : ''}`}>
            {p.label}
          </a>
        ))}
        <span style={{ flex: 1 }} />
        <a href="/dashboard/dashboard.html"
           data-testid="atlas-nav-v1"
           className="atlas-nav-link"
           title="Open the existing V1 dashboard (full operator UI)">
          ← V1 Dashboard
        </a>
      </nav>
    );
  }

  // ── PageHeader ─────────────────────────────────────────────────────
  function PageHeader({ title, subtitle, actions, testid }) {
    return (
      <header className="atlas-header" data-testid={testid || 'atlas-page-header'}>
        <div className="atlas-header-row">
          <div style={{ minWidth: 0 }}>
            <h1 className="atlas-h1" data-testid="atlas-page-title">{title}</h1>
            {subtitle && <p className="atlas-sub" data-testid="atlas-page-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="atlas-actions" data-testid="atlas-page-actions">{actions}</div>}
        </div>
      </header>
    );
  }

  // ── Button (with disabled + tooltip support) ───────────────────────
  function Btn({ variant = 'outline', small, disabled, onClick, title, children, testid, type = 'button' }) {
    const cls = `atlas-btn atlas-btn-${variant}${small ? ' small' : ''}`;
    return (
      <button type={type} className={cls} disabled={disabled}
        onClick={onClick} title={title}
        data-testid={testid}>
        {children}
      </button>
    );
  }

  // ── Shell tier banner — used by stub pages to flag "preview only" ──
  function TierBanner({ children, testid }) {
    return (
      <div className="atlas-tier-banner" data-testid={testid || 'atlas-tier-banner'}>
        <span style={{ fontSize: 16 }}>⚠</span>
        <div>{children}</div>
      </div>
    );
  }

  // ── Badge (8 variants matching design palette) ─────────────────────
  function Badge({ tone = 'neutral', children, testid }) {
    const map = {
      neutral: { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
      blue:    { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
      amber:   { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
      orange:  { bg: 'var(--badge-orange-bg)',  fg: 'var(--badge-orange-text)',  bd: 'var(--badge-orange-border)' },
      green:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
      red:     { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
      purple:  { bg: 'var(--badge-purple-bg)',  fg: 'var(--badge-purple-text)',  bd: 'var(--badge-purple-border)' },
      accent:  { bg: 'var(--badge-accent-bg)',  fg: 'var(--badge-accent-text)',  bd: 'var(--badge-accent-border)' },
    };
    const s = map[tone] || map.neutral;
    return (
      <span className="atlas-badge" data-testid={testid}
        style={{ background: s.bg, color: s.fg, borderColor: s.bd }}>
        {children}
      </span>
    );
  }

  // ── KPI tile ───────────────────────────────────────────────────────
  function Kpi({ label, value, hint, accent, testid }) {
    return (
      <div className="atlas-kpi" data-testid={testid}>
        <div className="atlas-kpi-label">{label}</div>
        <div className="atlas-kpi-value" style={accent ? { color: accent } : null}>{value}</div>
        {hint && <div className="atlas-kpi-hint">{hint}</div>}
      </div>
    );
  }

  // ── Empty / Loading / Error blocks ─────────────────────────────────
  function Empty({ children, testid }) {
    return <div className="atlas-empty" data-testid={testid || 'atlas-empty'}>{children}</div>;
  }
  function Loading({ children, testid }) {
    return (
      <div className="atlas-loading" data-testid={testid || 'atlas-loading'}>
        <span className="atlas-spinner"></span>
        <div style={{ marginTop: 8 }}>{children || 'Loading…'}</div>
      </div>
    );
  }
  function ErrorBanner({ children, testid }) {
    return <div className="atlas-error" data-testid={testid || 'atlas-error'}>{children}</div>;
  }

  // ── Compact section header ─────────────────────────────────────────
  function SectionTitle({ children, testid }) {
    return <div className="atlas-section-title" data-testid={testid}>{children}</div>;
  }

  // ── Format helpers (visual only — no business calculation) ─────────
  function ageStr(ts) {
    if (!ts) return '—';
    const t = new Date(ts);
    if (isNaN(t.getTime())) return '—';
    const diffMs = Date.now() - t.getTime();
    const h = Math.floor(diffMs / (3600 * 1000));
    if (h < 1) return 'now';
    if (h < 24) return `${h}h`;
    const d = Math.floor(h / 24);
    return `${d}d`;
  }

  function shortId(batch_id, tracking_no) {
    if (tracking_no) return tracking_no;
    if (!batch_id) return '—';
    const parts = batch_id.split('_');
    return parts[parts.length - 1] || batch_id;
  }

  function valueK(amount) {
    if (amount == null) return null;
    const n = Number(amount);
    if (isNaN(n) || n === 0) return null;
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return n.toFixed(0);
  }

  function fmtMoney(amount, currency) {
    if (amount == null || isNaN(Number(amount))) return '—';
    const n = Number(amount);
    return `${currency || ''} ${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
  }

  // ── Inject styles automatically once on first import ───────────────
  if (typeof document !== 'undefined' && !document.getElementById('atlas-v2-styles')) {
    injectStyles();
  }

  // ── Export ─────────────────────────────────────────────────────────
  window.AtlasShared = Object.freeze({
    // Layout
    PageHeader, NavStrip, TierBanner, SectionTitle,
    // Atoms
    Btn, Badge, Kpi, Empty, Loading, ErrorBanner,
    // Helpers
    ageStr, shortId, valueK, fmtMoney,
    injectStyles,
    // Constants
    ATLAS_PAGES,
  });
})();
