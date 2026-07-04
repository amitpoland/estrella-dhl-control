// ──────────────────────────────────────────────────────────────────────────
// wireframe-update.jsx
// Status-aware additions for the Estrella Atlas wireframe:
//   • FeatureStatus chip (Active / Partial / Backend pending / Future)
//   • OperationalStatusStrip (top banner)
//   • CoverageMapPage (Sprint 43: authority-honest, reads /openapi.json)
//   • ActionCenter page  (operator queue — replaces scattered approval pop-ups)
//   • AutomationCenterPage (replaces the AI Bridge page; same data)
//   • Stub pages: Identity/Mapping, MoveStock, SampleOut, SampleReturn,
//                  GoodsReturn, ReturnToProducer
//
// All pages are wireframes — no real fetches, no mutations.
// Reads use "Source · wFirma" badges. Writes use "Approval required".
// ──────────────────────────────────────────────────────────────────────────

// ── 1. Feature status chip ────────────────────────────────────────────────
function FeatureStatus({ level = 'active', label }) {
  const map = {
    active:  { dot:'#22A06B', bg:'var(--badge-green-bg)',   text:'var(--badge-green-text)',   border:'var(--badge-green-border)',   default:'Active' },
    partial: { dot:'#D4A853', bg:'var(--badge-amber-bg)',   text:'var(--badge-amber-text)',   border:'var(--badge-amber-border)',   default:'Partial' },
    backend: { dot:'#9CA8B8', bg:'var(--badge-neutral-bg)', text:'var(--badge-neutral-text)', border:'var(--badge-neutral-border)', default:'Backend pending' },
    future:  { dot:'#7E63C9', bg:'var(--badge-purple-bg)',  text:'var(--badge-purple-text)',  border:'var(--badge-purple-border)',  default:'Future' },
    readonly:{ dot:'#1A4A90', bg:'var(--badge-blue-bg)',    text:'var(--badge-blue-text)',    border:'var(--badge-blue-border)',    default:'Source · wFirma' },
    approval:{ dot:'#902018', bg:'var(--badge-red-bg)',     text:'var(--badge-red-text)',     border:'var(--badge-red-border)',     default:'Approval required' },
  };
  const s = map[level] || map.active;
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:5,
      background:s.bg, color:s.text, border:`1px solid ${s.border}`,
      padding:'2px 8px', borderRadius:10, fontSize:10, fontWeight:600,
      letterSpacing:'0.02em', lineHeight:1.4, whiteSpace:'nowrap',
    }}>
      <span style={{ width:6, height:6, borderRadius:'50%', background:s.dot }}/>
      {label || s.default}
    </span>
  );
}

// Disabled control with tooltip — used for backend-pending / future controls
function PendingBtn({ label, level = 'backend', onClick }) {
  const isPending = level === 'backend' || level === 'future';
  return (
    <button
      onClick={isPending ? undefined : onClick}
      disabled={isPending}
      title={
        level === 'backend' ? 'Backend endpoint not yet implemented' :
        level === 'future'  ? 'Planned — not yet scoped' :
        level === 'approval'? 'Operator approval required before execute' : ''
      }
      style={{
        padding:'6px 12px', borderRadius:6, fontSize:12, fontWeight:600,
        border:'1px solid var(--border)',
        background: isPending ? 'var(--bg-subtle)' : 'var(--card)',
        color: isPending ? 'var(--text-3)' : 'var(--text)',
        cursor: isPending ? 'not-allowed' : 'pointer',
        display:'inline-flex', alignItems:'center', gap:6,
        opacity: isPending ? 0.7 : 1,
      }}>
      {label}
      <FeatureStatus level={level}/>
    </button>
  );
}

// ── 2. Operational Status Strip ───────────────────────────────────────────
// W3 D-5 gap closure: replaced hardcoded mock with live reads from existing
// backend endpoints. Two authorities:
//   GET /api/v1/webhooks/wfirma/status  → wFirma sync scheduler heartbeat
//   GET /api/v1/health                  → engine health (pz engine, SAD parser)
// Both are auth-gated (X-API-Key via EstrellaShared.apiFetch).
// Polled once at mount; auto-refreshes every 60 seconds.
// No fake data. If an endpoint is unavailable the item shows 'unavailable'.
function OperationalStatusStrip() {
  const { useState, useEffect } = React;
  const [wfirmaStatus, setWfirmaStatus] = useState(null);
  const [healthStatus, setHealthStatus] = useState(null);
  const [ts, setTs] = useState(Date.now());

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      window.EstrellaShared.apiFetch('/api/v1/webhooks/wfirma/status')
        .then(r => { if (!cancelled) setWfirmaStatus(r && r.ok !== false ? r : null); })
        .catch(() => { if (!cancelled) setWfirmaStatus(null); });
      window.EstrellaShared.apiFetch('/api/v1/health')
        .then(r => { if (!cancelled) setHealthStatus(r && r.ok !== false ? r : null); })
        .catch(() => { if (!cancelled) setHealthStatus(null); });
      if (!cancelled) setTs(Date.now());
    };
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Derive items from live data
  const _dot = s => s === 'ok' ? '#22A06B' : s === 'warn' ? '#D4A853' : s === 'down' ? '#C0321A' : '#8A9AB0';
  const _ago = iso => {
    if (!iso) return null;
    const ms = Date.now() - new Date(iso).getTime();
    if (isNaN(ms) || ms < 0) return null;
    const m = Math.floor(ms / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
  };

  // wFirma sync item (authority: GET /api/v1/webhooks/wfirma/status)
  const wfItem = (() => {
    if (!wfirmaStatus) return { name: 'wFirma Sync', status: 'down', meta: 'unavailable' };
    const healthy = wfirmaStatus.scheduler_running === true;
    const last = _ago(wfirmaStatus.last_completed_at || wfirmaStatus.last_tick_at);
    const meta = healthy
      ? (last ? `synced ${last}` : 'running')
      : (last ? `last seen ${last}` : 'not running');
    return { name: 'wFirma Sync', status: healthy ? 'ok' : 'warn', meta };
  })();

  // PZ engine health item (authority: GET /api/v1/health)
  const engineItem = (() => {
    if (!healthStatus) return { name: 'PZ Engine', status: 'down', meta: 'unavailable' };
    const ok = healthStatus.status === 'ok' || healthStatus.healthy === true;
    return { name: 'PZ Engine', status: ok ? 'ok' : 'warn', meta: ok ? 'healthy' : 'degraded' };
  })();

  const items = [wfItem, engineItem];
  const fmtTs = new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <div data-testid="operational-status-strip" style={{
      display:'flex', alignItems:'center', gap:18, flexWrap:'wrap',
      padding:'5px 24px', background:'var(--bg-subtle)',
      borderBottom:'1px solid var(--border)', fontSize:11,
      color:'var(--text-2)',
    }}>
      <span style={{ fontWeight:700, color:'var(--text)', letterSpacing:'0.04em' }}>System</span>
      {items.map(i => (
        <span key={i.name} style={{ display:'inline-flex', alignItems:'center', gap:6 }}>
          <span style={{ width:7, height:7, borderRadius:'50%', background:_dot(i.status) }}/>
          <span style={{ fontWeight:600, color:'var(--text)' }}>{i.name}</span>
          <span style={{ color:'var(--text-3)' }}>· {i.meta}</span>
        </span>
      ))}
      <span style={{ flex:1 }}/>
      <span style={{ fontSize:9.5, color:'var(--text-3)', fontFamily:'monospace' }}>polled {fmtTs}</span>
      <a href="#" onClick={e => { e.preventDefault(); window.location.hash = '#api_status'; }}
        style={{ color:'var(--accent-text)', textDecoration:'underline', fontWeight:600 }}>System health →</a>
    </div>
  );
}

// ── 3. Coverage Map page — authority-honest (Sprint 43) ──────────────────
// Authority: GET /openapi.json (FastAPI built-in OpenAPI spec).
// All hardcoded COVERAGE_ROWS deleted. The OpenAPI spec IS the route registry.
// Deleted: 46-entry COVERAGE_ROWS array, fake status categories (active/partial/
// backend/future), fake "Wireframe rules in effect" footer, FeatureStatus tiles
// for coverage counts.

// Derive a module group from an API path prefix.
function _deriveModule(path) {
  if (!path) return 'Other';
  const s = path.replace(/^\/api\/v1\//, '');
  const seg = s.split('/')[0] || 'root';
  const MAP = {
    pz: 'PZ Engine', dhl: 'DHL / Customs', customs: 'DHL / Customs',
    sales: 'Accounting', proforma: 'Accounting', ledgers: 'Ledgers',
    inventory: 'Inventory', 'customer-master': 'Clients', master: 'Master Data',
    debug: 'Debug / Ops', admin: 'Admin', batch: 'Batch', health: 'System',
    system: 'System', dashboard: 'Dashboard', cowork: 'Automation',
    intelligence: 'Intelligence', ai: 'Intelligence', search: 'Search',
    inbox: 'Inbox', tracking: 'Tracking', wfirma: 'wFirma',
    warehouse: 'Warehouse', carrier: 'Carriers', 'carriers-config': 'Carriers',
    agents: 'Agents', settings: 'Settings', upload: 'Upload',
    monitor: 'Monitor', orchestrator: 'Orchestrator',
  };
  return MAP[seg] || seg.charAt(0).toUpperCase() + seg.slice(1);
}

// Parse OpenAPI paths into a flat array of route objects.
function _parseOpenApiPaths(paths) {
  const rows = [];
  for (const [path, methods] of Object.entries(paths || {})) {
    for (const [method, info] of Object.entries(methods || {})) {
      if (method === 'parameters') continue; // path-level params, not a method
      rows.push({
        method: method.toUpperCase(),
        path: path,
        summary: (info.summary || '').replace(/\s+/g, ' ').trim(),
        tags: (info.tags || []),
        module: info.tags && info.tags[0] ? info.tags[0] : _deriveModule(path),
        deprecated: !!info.deprecated,
      });
    }
  }
  rows.sort((a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method));
  return rows;
}

// Method badge color
function _methodColor(m) {
  if (m === 'GET')    return { bg: 'var(--badge-green-bg)',  text: 'var(--badge-green-text)',  border: 'var(--badge-green-border)' };
  if (m === 'POST')   return { bg: 'var(--badge-amber-bg)',  text: 'var(--badge-amber-text)',  border: 'var(--badge-amber-border)' };
  if (m === 'PUT' || m === 'PATCH') return { bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)' };
  if (m === 'DELETE') return { bg: 'var(--badge-red-bg)',    text: 'var(--badge-red-text)',    border: 'var(--badge-red-border)' };
  return { bg: 'var(--card)', text: 'var(--text-2)', border: 'var(--border)' };
}

function _CoverageKpiStrip({ routes }) {
  const gets = routes.filter(r => r.method === 'GET').length;
  const posts = routes.filter(r => r.method === 'POST').length;
  const muts = routes.filter(r => r.method === 'PUT' || r.method === 'PATCH' || r.method === 'DELETE').length;
  const modules = new Set(routes.map(r => r.module));
  const kpi = (label, val) => (
    <div style={{ flex: 1, minWidth: 120, padding: '10px 14px', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, textAlign: 'center' }}>
      <div style={{ fontFamily: '"DM Serif Display", serif', fontSize: 24, color: 'var(--text)' }}>{val}</div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{label}</div>
    </div>
  );
  return (
    <div data-testid="coverage-kpi-strip" style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
      {kpi('Total Routes', routes.length)}
      {kpi('GET (read)', gets)}
      {kpi('POST (write)', posts)}
      {kpi('PUT/PATCH/DEL', muts)}
      {kpi('Modules', modules.size)}
    </div>
  );
}

function CoverageMapPage() {
  const { useState, useEffect } = React;
  const { Card } = window.EstrellaShared || {};
  const [spec, setSpec] = useState({ loading: true, data: null, error: null });
  const [q, setQ] = useState('');
  const [methodFilter, setMethodFilter] = useState('all');
  const [moduleFilter, setModuleFilter] = useState('all');

  useEffect(() => {
    window.PzApi.getOpenApiSpec()
      .then(res => {
        if (res.ok) {
          setSpec({ loading: false, data: res.data, error: null });
        } else {
          setSpec({ loading: false, data: null, error: res.error || 'Failed to load OpenAPI spec' });
        }
      })
      .catch(err => {
        setSpec({ loading: false, data: null, error: String(err) });
      });
  }, []);

  if (spec.loading) {
    return (
      <div data-testid="coverage-map-page" style={{ padding: '18px 32px 32px', flex: 1 }}>
        <div data-testid="coverage-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>
          Loading route registry from OpenAPI spec...
        </div>
      </div>
    );
  }

  if (spec.error) {
    return (
      <div data-testid="coverage-map-page" style={{ padding: '18px 32px 32px', flex: 1 }}>
        <div data-testid="coverage-error" style={{
          padding: 20, background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          borderRadius: 8, color: 'var(--badge-red-text)', fontSize: 13,
        }}>
          Failed to load route registry: {spec.error}
        </div>
      </div>
    );
  }

  const routes = _parseOpenApiPaths(spec.data.paths);
  const allModules = [...new Set(routes.map(r => r.module))].sort();
  const allMethods = [...new Set(routes.map(r => r.method))].sort();

  const filtered = routes.filter(r => {
    if (methodFilter !== 'all' && r.method !== methodFilter) return false;
    if (moduleFilter !== 'all' && r.module !== moduleFilter) return false;
    if (q) {
      const lq = q.toLowerCase();
      return (r.path + ' ' + r.summary + ' ' + r.module + ' ' + r.method).toLowerCase().includes(lq);
    }
    return true;
  });

  const thStyle = {
    textAlign: 'left', padding: '8px 12px', fontWeight: 700,
    color: 'var(--text-2)', fontSize: 11, letterSpacing: '0.04em', textTransform: 'uppercase',
  };

  return (
    <div data-testid="coverage-map-page" style={{ padding: '18px 32px 32px', overflowY: 'auto', flex: 1 }}>

      <_CoverageKpiStrip routes={routes} />

      <div data-testid="coverage-filters" style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input value={q} onChange={e => setQ(e.target.value)}
               placeholder="Search paths, summaries, modules..."
               data-testid="coverage-search"
               style={{ flex: 1, maxWidth: 360, padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12, color: 'var(--text)', background: 'var(--card)' }} />

        <select value={methodFilter} onChange={e => setMethodFilter(e.target.value)}
                data-testid="coverage-method-filter"
                style={{ padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12, background: 'var(--card)', color: 'var(--text)' }}>
          <option value="all">All methods</option>
          {allMethods.map(m => <option key={m} value={m}>{m}</option>)}
        </select>

        <select value={moduleFilter} onChange={e => setModuleFilter(e.target.value)}
                data-testid="coverage-module-filter"
                style={{ padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12, background: 'var(--card)', color: 'var(--text)' }}>
          <option value="all">All modules</option>
          {allModules.map(m => <option key={m} value={m}>{m}</option>)}
        </select>

        {(methodFilter !== 'all' || moduleFilter !== 'all' || q) && (
          <button onClick={() => { setMethodFilter('all'); setModuleFilter('all'); setQ(''); }}
                  style={{ padding: '6px 10px', fontSize: 11, border: '1px solid var(--border)', background: 'var(--card)', borderRadius: 6, cursor: 'pointer', color: 'var(--text-2)' }}>
            Clear filters
          </button>
        )}

        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
          Showing {filtered.length} of {routes.length} routes
        </span>
      </div>

      <div data-testid="coverage-route-table" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ ...thStyle, width: 70 }}>Method</th>
              <th style={thStyle}>Path</th>
              <th style={thStyle}>Summary</th>
              <th style={{ ...thStyle, width: 140 }}>Module</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => {
              const mc = _methodColor(r.method);
              return (
                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '6px 12px' }}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                      background: mc.bg, color: mc.text, border: '1px solid ' + mc.border, letterSpacing: '0.04em',
                    }}>{r.method}</span>
                  </td>
                  <td style={{ padding: '6px 12px', fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 11, color: r.deprecated ? 'var(--text-3)' : 'var(--text)', textDecoration: r.deprecated ? 'line-through' : 'none' }}>
                    {r.path}
                  </td>
                  <td style={{ padding: '6px 12px', color: 'var(--text-2)', fontSize: 11 }}>
                    {r.summary || '—'}
                  </td>
                  <td style={{ padding: '6px 12px', color: 'var(--text-3)', fontSize: 11, fontWeight: 600 }}>
                    {r.module}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={4} style={{ padding: 20, textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>
                  No routes match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 18, padding: 14, background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)', borderRadius: 8, fontSize: 11, color: 'var(--text-2)', lineHeight: 1.6 }}>
        <strong style={{ color: 'var(--text)' }}>Authority: /openapi.json</strong>{' '}
        — This page reads the live FastAPI OpenAPI specification. Every route shown is registered and reachable.
        Module grouping is derived from the first path segment. Route counts, methods, and summaries
        come from the running backend, not from hardcoded data.
      </div>
    </div>
  );
}

// Backward-compat alias — index.html still references CoverageMatrix
const CoverageMatrix = CoverageMapPage;

// ── 4. Action Center page ─────────────────────────────────────────────────
// R-Q2 (2026-07-04): Action Center is operator authority; AI Bridge = backend capability behind it.
// Data: loads recent batches via PzApi.listBatches(), then fetches proposals per batch from
// GET /api/v1/action-proposals/{batch_id}. Aggregates pending_review proposals cross-batch.
// AI Bridge is surfaced as a right-rail panel (backend capability), NOT a separate page.
function ActionCenterPage() {
  const { useState, useEffect } = React;
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);

  // Derive a human-readable age string from an ISO timestamp
  const _age = iso => {
    if (!iso) return '—';
    const ms = Date.now() - new Date(iso).getTime();
    if (isNaN(ms) || ms < 0) return '—';
    const m = Math.floor(ms / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d`;
  };

  // Map proposal confidence/risk field to a display risk level
  const _risk = p => {
    const c = (p.confidence || '').toLowerCase();
    if (c === 'high' || c === 'critical') return 'high';
    if (c === 'medium' || c === 'moderate') return 'medium';
    return 'low';
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        // Step 1: load recent batches (existing endpoint, no new routes)
        const batchRes = await window.PzApi.listBatches();
        if (!batchRes || !batchRes.ok) {
          if (!cancelled) { setError('Could not load batch list'); setLoading(false); }
          return;
        }
        const batches = Array.isArray(batchRes.data)
          ? batchRes.data
          : ((batchRes.data && batchRes.data.batches) || []);

        // Step 2: fetch proposals for up to 20 most-recent batches in parallel
        const recentBatches = batches.slice(0, 20);
        const results = await Promise.allSettled(
          recentBatches.map(b => {
            const batchId = b.batch_id || b.id || b.doc_no;
            if (!batchId) return Promise.resolve(null);
            return window.EstrellaShared.apiFetch(
              '/api/v1/action-proposals/' + encodeURIComponent(batchId)
            );
          })
        );

        // Step 3: aggregate pending_review proposals across batches
        const all = [];
        results.forEach(r => {
          if (r.status !== 'fulfilled' || !r.value) return;
          const payload = r.value;
          const list = Array.isArray(payload.proposals) ? payload.proposals
                     : Array.isArray(payload) ? payload
                     : [];
          list.forEach(p => {
            if ((p.status || '') === 'pending_review') all.push(p);
          });
        });

        if (!cancelled) { setProposals(all); setLoading(false); }
      } catch (e) {
        if (!cancelled) { setError(String(e)); setLoading(false); }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const riskColor = r => r==='high' ? 'var(--badge-red-text)' : r==='medium' ? 'var(--badge-amber-text)' : 'var(--badge-green-text)';

  const renderQueue = () => {
    if (loading) return (
      <tr><td colSpan={8} style={{ padding:'24px 10px', textAlign:'center', color:'var(--text-3)', fontSize:12 }}>Loading proposals…</td></tr>
    );
    if (error) return (
      <tr><td colSpan={8} style={{ padding:'24px 10px', textAlign:'center', color:'var(--badge-red-text)', fontSize:12 }}>Error: {error}</td></tr>
    );
    if (!proposals.length) return (
      <tr><td colSpan={8} style={{ padding:'24px 10px', textAlign:'center', color:'var(--text-3)', fontSize:12 }}>No pending proposals — queue is clear.</td></tr>
    );
    return proposals.map(p => {
      const risk = _risk(p);
      const refText = p.batch_id || p.reference || '—';
      const amountText = (p.draft && p.draft.amount) ? p.draft.amount : '—';
      return (
        <tr key={p.proposal_id || p.id} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
          <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text-2)' }}>
            {(p.proposal_id || p.id || '').slice(0, 8)}
          </td>
          <td style={{ padding:'8px 10px', color:'var(--text)' }}>
            {(p.type || p.kind || '').replace(/_/g, ' ')}
          </td>
          <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{refText}</td>
          <td style={{ padding:'8px 10px', color:'var(--text)', fontWeight:600 }}>{amountText}</td>
          <td style={{ padding:'8px 10px', color:riskColor(risk), fontWeight:600, textTransform:'capitalize' }}>{risk}</td>
          <td style={{ padding:'8px 10px', color:'var(--text-3)' }}>{_age(p.created_at)}</td>
          <td style={{ padding:'8px 10px' }}>
            <span style={{ fontSize:10, padding:'2px 7px', borderRadius:4, background:'rgba(212,168,83,0.12)', color:'var(--accent)', fontWeight:600, textTransform:'uppercase', letterSpacing:'0.04em' }}>
              pending review
            </span>
          </td>
          <td style={{ padding:'8px 10px', textAlign:'right' }}>
            <button data-testid="action-center-review-btn" style={{
              padding:'5px 10px', fontSize:11, fontWeight:600,
              border:'1px solid var(--accent-border)',
              background:'var(--accent)', color:'var(--accent-text)',
              borderRadius:6, cursor:'pointer',
            }}>Review</button>
          </td>
        </tr>
      );
    });
  };

  return (
    <div style={{ padding:'18px 32px 32px', overflowY:'auto', flex:1, display:'flex', gap:18 }}>
      {/* main queue */}
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
          <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Pending operator actions</h3>
          {!loading && !error && (
            <span style={{ fontSize:11, padding:'2px 8px', borderRadius:10, background:'rgba(212,168,83,0.15)', color:'var(--accent)', fontWeight:700 }}>
              {proposals.length}
            </span>
          )}
          <span style={{ flex:1 }}/>
          <PendingBtn label="Bulk approve" level="backend"/>
        </div>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
            <thead>
              <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
                {['ID','Action','Reference','Amount','Risk','Age','Status',''].map(h => (
                  <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {renderQueue()}
            </tbody>
          </table>
        </div>
      </div>

      {/* right action rail */}
      <aside style={{ width:280, flexShrink:0, display:'flex', flexDirection:'column', gap:12 }}>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Today</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8 }}>
            {[['Approved','—'],['Auto-executed','—'],['Rejected','—'],['SLA breaches','—']].map(([k,v])=> (
              <div key={k} style={{ padding:8, background:'var(--bg-subtle)', borderRadius:6 }}>
                <div style={{ fontFamily:'"DM Serif Display", serif', fontSize:22, color:'var(--text)' }}>{v}</div>
                <div style={{ fontSize:10, color:'var(--text-3)' }}>{k}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>Approval policy</div>
          <ul style={{ margin:0, paddingLeft:16, fontSize:11, color:'var(--text-2)', lineHeight:1.7 }}>
            <li>Writes to wFirma → operator approve</li>
            <li>Credit-limit changes → 2-eyes</li>
            <li>Returns / RMA → ops + finance</li>
            <li>Auto-execute: PZ adopt &lt; PLN 50k</li>
          </ul>
        </div>
        {/* AI Bridge panel — backend capability that feeds this queue */}
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>
            AI Bridge
            <span style={{ marginLeft:6, fontSize:10, padding:'1px 5px', borderRadius:3, background:'var(--bg-subtle)', color:'var(--text-3)', fontWeight:400, textTransform:'none' }}>backend capability</span>
          </div>
          <div style={{ fontSize:11, color:'var(--text-2)', lineHeight:1.6, marginBottom:8 }}>
            AI Bridge analyses shipments and generates the proposals in this queue. It does not take actions — it proposes them for operator approval.
          </div>
          <a href="#/automation" style={{ display:'inline-block', fontSize:11, fontWeight:600, color:'var(--accent)', textDecoration:'none' }}>
            View AI Bridge status →
          </a>
        </div>
      </aside>
    </div>
  );
}

// ── 5. Stub pages — light wireframes for not-yet-built screens ────────────
function StubPage({ title, description, status='backend', endpoints=[], columns=[], rows=[] }) {
  return (
    <div style={{ padding:'18px 32px 32px', overflowY:'auto', flex:1 }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:6 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>{title}</h3>
        <FeatureStatus level={status}/>
      </div>
      <p style={{ margin:'0 0 14px', fontSize:12, color:'var(--text-2)', maxWidth:780, lineHeight:1.6 }}>{description}</p>

      {columns.length > 0 && (
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden', marginBottom:18 }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
            <thead>
              <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
                {columns.map(c => <th key={c} style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)', opacity:0.85 }}>
                  {r.map((cell, j) => <td key={j} style={{ padding:'8px 12px', color: j===0 ? 'var(--text)' : 'var(--text-2)' }}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding:'10px 12px', background:'var(--bg-subtle)', fontSize:11, color:'var(--text-3)', borderTop:'1px solid var(--border-subtle)' }}>
            Wireframe data — backend not yet wired.
          </div>
        </div>
      )}

      {endpoints.length>0 && (
        <div style={{ padding:14, background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:8 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Recommended API placeholders</div>
          <ul style={{ margin:0, paddingLeft:16, fontSize:11, color:'var(--text-2)', lineHeight:1.8, fontFamily:'ui-monospace, monospace' }}>
            {endpoints.map(e => <li key={e}>{e}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function IdentityMappingPage() {
  return <StubPage
    title="Identity / Mapping"
    description="Two-way mapping between supplier SKUs, internal design IDs, and customer SKUs. Required before goods can move from Temp Warehouse → Final Stock."
    status="backend"
    columns={['Supplier SKU','Internal Design ID','Customer SKU','Confidence','Last Updated']}
    rows={[
      ['SUP-441-AB',  'EJ-D-00412', 'AUR-441',     'High · 0.94', '2 days ago'],
      ['SUP-441-AC',  'EJ-D-00413', '— unmapped —','—',           '—'],
      ['SUP-552-XX',  'EJ-D-00420', 'LEV-552-X',   'Medium · 0.71','4 days ago'],
    ]}
    endpoints={[
      'GET  /api/v1/inventory/identity?status=unmapped',
      'POST /api/v1/inventory/identity   (bulk upsert)',
      'POST /api/v1/inventory/identity/{id}/confirm',
      'GET  /api/v1/inventory/identity/{id}/audit',
    ]}/>;
}

// B×7-1 (2026-07-02): the MoveStockPage stub was RETIRED here — the live page
// now owns the name (move-stock-page.jsx, loaded EARLIER in index.html; keeping
// the stub caused a window-global last-write collision that silently rendered
// the mock over the live page — the same defect class slice-03 removed for
// ReportsPage). Sprint-31 playbook step P3: mock retired, functions deleted.
// The stub's advertised endpoints were FICTIONAL (superseded per PROJECT_STATE
// DECISIONS "slice B×7-1"). Each future B-slice retires its own stub the same way.

function SampleOutPage() {
  return <StubPage
    title="Sample Out"
    description="Release samples from Final Stock to a client for evaluation. Tracked separately from sales — does not deduct sellable stock until conversion."
    status="partial"
    columns={['Sample ID','Client','Item','Out Date','Expected Return','Status']}
    rows={[
      ['SMP-0124', 'Aurum Trading',     'EJ-D-00412', '12 May 2026', '26 May 2026', 'Out · in eval'],
      ['SMP-0123', 'Levi Joaillerie',   'EJ-D-00413', '08 May 2026', '22 May 2026', 'Out · overdue'],
      ['SMP-0122', 'Maison Élise',      'EJ-D-00420', '02 May 2026', '16 May 2026', 'Returned'],
    ]}
    endpoints={[
      'GET  /api/v1/inventory/samples',
      'POST /api/v1/inventory/samples/out',
      'POST /api/v1/inventory/samples/{id}/extend',
    ]}/>;
}

function SampleReturnPage() {
  return <StubPage
    title="Sample Return"
    description="Receive samples back into Final Stock or convert to a sale. Triggers QC re-check and a stock movement journal entry."
    status="backend"
    columns={['Sample ID','Client','Item','Returned','Outcome','QC']}
    rows={[
      ['SMP-0119', 'Aurum Trading',   'EJ-D-00405', '11 May 2026', 'Back to stock', 'Pass'],
      ['SMP-0118', 'Levi Joaillerie', 'EJ-D-00407', '09 May 2026', 'Convert to sale','Pass'],
      ['SMP-0117', 'Maison Élise',    'EJ-D-00408', '07 May 2026', 'Damaged · write-off','Fail'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/samples/return',
      'POST /api/v1/inventory/samples/{id}/convert-to-sale',
      'POST /api/v1/inventory/samples/{id}/writeoff',
    ]}/>;
}

function GoodsReturnPage() {
  return <StubPage
    title="Goods Return from Client"
    description="Receive returned goods from a client (post-sale RMA). Generates a credit note in wFirma and re-enters items to Final Stock after QC."
    status="backend"
    columns={['RMA','Client','Original Inv.','Items','Reason','Status']}
    rows={[
      ['RMA-0044','Aurum Trading',   'INV 2025/0412','3', 'Wrong size',     'In transit'],
      ['RMA-0043','Levi Joaillerie', 'INV 2025/0405','1', 'Quality issue',  'QC pending'],
      ['RMA-0042','Maison Élise',    'INV 2025/0399','2', 'Customer return','Credit issued'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/returns/from-client',
      'POST /api/v1/inventory/returns/{id}/qc',
      'POST /api/v1/inventory/returns/{id}/credit-note   (writes wFirma · approval req.)',
    ]}/>;
}

function ReturnToProducerPage() {
  return <StubPage
    title="Return to Producer"
    description="Send goods back to the original supplier (defective lots, wrong items, end-of-line). Mirrors PZ flow in reverse — generates a debit note request."
    status="future"
    columns={['Producer RMA','Supplier','Original PI','Items','Reason','Status']}
    rows={[
      ['PRMA-0012','Mehta Gems · MUM',     'PI 2025/418','5','Off-spec',  'Draft'],
      ['PRMA-0011','Levant Diamonds · TLV','PI 2025/410','2','Wrong cut',  'Awaiting approval'],
      ['PRMA-0010','Mehta Gems · MUM',     'PI 2025/402','3','Damaged',    'Sent'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/returns/to-producer',
      'POST /api/v1/inventory/returns/{id}/dispatch',
      'POST /api/v1/inventory/returns/{id}/debit-note   (writes wFirma · approval req.)',
    ]}/>;
}

// ── Export to window so the host HTML can mount these ─────────────────────
Object.assign(window, {
  FeatureStatus, PendingBtn, OperationalStatusStrip,
  CoverageMapPage, CoverageMatrix, ActionCenterPage,
  IdentityMappingPage,
  // MoveStockPage retired (B×7-1) — live page owns the name; see comment above.
  SampleOutPage, SampleReturnPage,
  GoodsReturnPage, ReturnToProducerPage,
});
