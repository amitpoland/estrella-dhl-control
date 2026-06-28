// App.jsx — Atlas visual shell + ProformaDetailPage route.
// Phase D-2: visual shell only. No navigation functionality, no route switch.
// Sidebar is decorative; topbar provides dark-mode toggle only.

import React, { useState, useEffect } from 'react'
import ProformaDetailPage from './ProformaDetail.jsx'
import './styles/tokens.css'

// ── Decorative sidebar (visual only — no nav callbacks wired) ─────────────────
const NAV_ITEMS = [
  { icon: '▣',  label: 'Dashboard' },
  { icon: '✉',  label: 'Inbox' },
  { icon: '✈',  label: 'Shipments' },
  { icon: '🧾', label: 'Pro Forma', active: true },
  { icon: '📦', label: 'Inventory' },
  { icon: '⚙',  label: 'Settings' },
]

function AtlasSidebar({ collapsed, onToggle }) {
  const w = collapsed ? 52 : 200
  return (
    <div style={{
      width: w, flexShrink: 0, height: '100vh',
      background: 'var(--sidebar-bg)',
      borderRight: '1px solid var(--sidebar-border)',
      display: 'flex', flexDirection: 'column',
      transition: 'width 0.2s ease',
      overflow: 'hidden',
      position: 'relative', zIndex: 10,
    }}>
      {/* Logo */}
      <div style={{
        height: 52, padding: '0 14px',
        borderBottom: '1px solid var(--sidebar-border)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
      }}>
        <span style={{ fontSize: 20, color: 'var(--sidebar-icon)', flexShrink: 0, lineHeight: 1 }}>✦</span>
        {!collapsed && (
          <span style={{
            fontSize: 14, fontWeight: 700,
            color: 'var(--sidebar-text)',
            fontFamily: '"DM Serif Display", serif',
            whiteSpace: 'nowrap', letterSpacing: '0.01em',
          }}>
            Estrella
          </span>
        )}
      </div>

      {/* Nav items */}
      <div style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
        {NAV_ITEMS.map(({ icon, label, active }) => (
          <div
            key={label}
            title={collapsed ? label : undefined}
            style={{
              display: 'flex', alignItems: 'center',
              gap: 10, padding: '9px 14px',
              background: active ? 'var(--sidebar-active)' : 'transparent',
              borderLeft: active
                ? '3px solid var(--sidebar-icon)'
                : '3px solid transparent',
              cursor: 'default', whiteSpace: 'nowrap',
              userSelect: 'none',
            }}
          >
            <span style={{
              fontSize: 15, flexShrink: 0,
              color: active ? 'var(--sidebar-icon)' : 'var(--sidebar-text-muted)',
            }}>{icon}</span>
            {!collapsed && (
              <span style={{
                fontSize: 12.5,
                fontWeight: active ? 700 : 500,
                color: active ? 'var(--sidebar-text)' : 'var(--sidebar-text-muted)',
              }}>{label}</span>
            )}
          </div>
        ))}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        style={{
          margin: 8, padding: '7px 0', borderRadius: 6,
          background: 'transparent', border: '1px solid var(--sidebar-border)',
          color: 'var(--sidebar-text-muted)', cursor: 'pointer',
          fontSize: 12, display: 'flex', alignItems: 'center',
          justifyContent: 'center', flexShrink: 0,
        }}
      >
        {collapsed ? '→' : '←'}
      </button>
    </div>
  )
}

// ── Minimal topbar (visual only — dark-mode toggle active) ────────────────────
function AtlasTopBar({ isDark, onToggleDark }) {
  return (
    <div style={{
      height: 48, flexShrink: 0,
      background: 'var(--card)',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: '0 24px', gap: 8,
      boxShadow: '0 1px 3px var(--shadow)',
    }}>
      {/* Breadcrumb */}
      <span style={{ fontSize: 11.5, color: 'var(--text-3)', fontWeight: 500 }}>Pro Forma</span>
      <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>/</span>
      <span style={{ fontSize: 11.5, color: 'var(--text)', fontWeight: 600 }}>Draft Detail</span>

      <div style={{ flex: 1 }} />

      {/* Dark-mode toggle */}
      <button
        onClick={onToggleDark}
        title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        style={{
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 6, padding: '5px 12px', cursor: 'pointer',
          color: 'var(--text-2)', fontSize: 11.5, fontWeight: 600,
          display: 'inline-flex', alignItems: 'center', gap: 5,
        }}
      >
        {isDark ? '☀ Light' : '◑ Dark'}
      </button>
    </div>
  )
}

// ── URL param parsing ─────────────────────────────────────────────────────────
function parseParams() {
  const p = new URLSearchParams(window.location.search)
  return {
    batchId:    p.get('batch_id')    || '',
    clientName: p.get('client_name') || '',
    draftId:    p.get('draft_id') || p.get('draft') || null,
  }
}

// ── App root ──────────────────────────────────────────────────────────────────
export default function App() {
  const [params] = useState(parseParams)
  const [draft,   setDraft]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [isDark,  setIsDark]  = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Apply theme to <html> so CSS vars cascade correctly
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light')
  }, [isDark])

  useEffect(() => {
    if (params.draftId) {
      fetch(`/api/v1/proforma/draft/${params.draftId}`, { credentials: 'include' })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
        .then(data => { setDraft(data.draft || data); setLoading(false) })
        .catch(e => { setError(e.message); setLoading(false) })
    } else if (params.batchId && params.clientName) {
      fetch(`/api/v1/proforma/drafts/${encodeURIComponent(params.batchId)}`, { credentials: 'include' })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
        .then(data => {
          const drafts = (data.drafts || []).filter(d => d.client_name === params.clientName)
          setDraft(drafts[0] || null)
          setLoading(false)
        })
        .catch(e => { setError(e.message); setLoading(false) })
    } else {
      setLoading(false)
    }
  }, [params.draftId, params.batchId, params.clientName])

  // Loading / error / empty states render within the shell so the sidebar is
  // always visible — consistent with the standalone Atlas layout.
  const mainContent = loading ? (
    <div style={{ padding: 40, color: 'var(--text-2)', fontSize: 13 }}>Loading draft…</div>
  ) : error ? (
    <div style={{ padding: 40, color: 'var(--badge-red-text)', fontSize: 13 }}>Error: {error}</div>
  ) : !draft ? (
    <div style={{ padding: 40, color: 'var(--text-2)', fontSize: 13 }}>
      No draft found. Provide <code>?draft=&lt;id&gt;</code> or{' '}
      <code>?batch_id=&amp;client_name=</code> in the URL.
    </div>
  ) : (
    <ProformaDetailPage
      draft={draft}
      batchId={params.batchId || draft.batch_id || ''}
      clientName={params.clientName || draft.client_name || ''}
      onBack={() => window.history.back()}
      onConvert={() => { window.location.reload() }}
    />
  )

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Decorative Atlas sidebar — visual only, no navigation */}
      <AtlasSidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(v => !v)}
      />

      {/* Main content column */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        <AtlasTopBar isDark={isDark} onToggleDark={() => setIsDark(v => !v)} />

        {/* Scrollable content area — ProformaDetailPage owns its own scroll */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {mainContent}
        </div>
      </div>
    </div>
  )
}
