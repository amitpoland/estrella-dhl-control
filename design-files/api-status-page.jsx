// ─────────────────────────────────────────────────────────────────────────────
// API Status — consolidated single page replacing scattered API health
// surfaces across Diagnostics / Carriers / Admin / module footers.
//
// Sections:
//   1. KPI strip
//   2. Integration cards grid (carriers, wFirma, customs, internal, webhooks)
//   3. Endpoint registry — every API call in the system, searchable
//   4. Recent errors panel
//   5. Incidents log
//
// Backend hooks (all stubbed):
//   GET /api/v1/admin/api-status            — aggregated health
//   GET /api/v1/admin/api-status/endpoints  — endpoint registry
//   GET /api/v1/admin/api-status/errors     — recent errors
//   GET /api/v1/admin/api-status/incidents  — incident log
//   POST /api/v1/admin/api-status/{id}/test — synthetic probe
// ─────────────────────────────────────────────────────────────────────────────

const API_INTEGRATIONS = [
  // ── Carriers ───────────────────────────────────────────────────
  { id: 'dhl-express', name: 'DHL Express',    group: 'Carriers',     state: 'healthy',     endpoints: 14, successPct: 99.7, latencyMs: 312, calls24h: 4218, lastError: null,                                                lastCall: '2026-05-11 09:42:14' },
  { id: 'fedex',       name: 'FedEx',           group: 'Carriers',     state: 'healthy',     endpoints: 11, successPct: 99.2, latencyMs: 411, calls24h: 712,  lastError: null,                                                lastCall: '2026-05-11 09:38:02' },
  { id: 'ups',         name: 'UPS',             group: 'Carriers',     state: 'pending',     endpoints: 9,  successPct: 0,    latencyMs: null,calls24h: 0,    lastError: 'OAuth not completed',                              lastCall: '—' },
  { id: 'gls',         name: 'GLS',             group: 'Carriers',     state: 'disconnected',endpoints: 7,  successPct: 0,    latencyMs: null,calls24h: 0,    lastError: 'Carrier disconnected by operator',                  lastCall: '2026-04-22 14:01:00' },
  { id: 'inpost',      name: 'InPost',          group: 'Carriers',     state: 'configured',  endpoints: 5,  successPct: 100,  latencyMs: 184, calls24h: 12,   lastError: null,                                                lastCall: '2026-05-09 11:24:00' },
  { id: 'dpd',         name: 'DPD',             group: 'Carriers',     state: 'error',       endpoints: 6,  successPct: 0,    latencyMs: null,calls24h: 0,    lastError: 'AUTH_401 — token rejected',                         lastCall: '2026-05-10 22:17:44' },

  // ── Accounting / Tax ───────────────────────────────────────────
  { id: 'wfirma',      name: 'wFirma',          group: 'Accounting',   state: 'healthy',     endpoints: 23, successPct: 99.8, latencyMs: 280, calls24h: 1820, lastError: null,                                                lastCall: '2026-05-11 09:41:00' },
  { id: 'fx',          name: 'FX Rates',        group: 'Accounting',   state: 'healthy',     endpoints: 3,  successPct: 100,  latencyMs: 92,  calls24h: 24,   lastError: null,                                                lastCall: '2026-05-11 06:00:00' },

  // ── Customs / Government ────────────────────────────────────────
  { id: 'sad',         name: 'SAD (PUESC)',     group: 'Customs',      state: 'healthy',     endpoints: 8,  successPct: 98.4, latencyMs: 1812,calls24h: 64,   lastError: 'Timeout on /sad/declarations/lookup (last 18h ago)',lastCall: '2026-05-11 08:14:22' },
  { id: 'zc429',       name: 'ZC429 (Customs)', group: 'Customs',      state: 'degraded',    endpoints: 5,  successPct: 87.1, latencyMs: 2240,calls24h: 31,   lastError: 'Intermittent 502 from PUESC (3 in last hr)',         lastCall: '2026-05-11 09:11:08' },

  // ── Internal services ──────────────────────────────────────────
  { id: 'cowork',      name: 'Cowork Engine',   group: 'Internal',     state: 'healthy',     endpoints: 17, successPct: 99.9, latencyMs: 142, calls24h: 8412, lastError: null,                                                lastCall: '2026-05-11 09:42:54' },
  { id: 'aibridge',    name: 'AI Bridge',       group: 'Internal',     state: 'healthy',     endpoints: 12, successPct: 99.4, latencyMs: 1842,calls24h: 412,  lastError: null,                                                lastCall: '2026-05-11 09:40:11' },
  { id: 'storage',     name: 'Storage',         group: 'Internal',     state: 'healthy',     endpoints: 9,  successPct: 100,  latencyMs: 38,  calls24h: 32844,lastError: null,                                                lastCall: '2026-05-11 09:43:01' },
  { id: 'ocr',         name: 'OCR / Parser',    group: 'Internal',     state: 'healthy',     endpoints: 6,  successPct: 96.2, latencyMs: 3210,calls24h: 184,  lastError: 'Low-confidence parse on 2 invoices (queued)',        lastCall: '2026-05-11 09:39:48' },
  { id: 'smtp',        name: 'SMTP / Mailer',   group: 'Internal',     state: 'healthy',     endpoints: 4,  successPct: 99.9, latencyMs: 412, calls24h: 287,  lastError: null,                                                lastCall: '2026-05-11 09:42:00' },
  { id: 'imap',        name: 'IMAP (Inbound)',  group: 'Internal',     state: 'healthy',     endpoints: 3,  successPct: 100,  latencyMs: 218, calls24h: 412,  lastError: null,                                                lastCall: '2026-05-11 09:42:30' },

  // ── Webhooks ───────────────────────────────────────────────────
  { id: 'webhooks',    name: 'Webhook Ingest',  group: 'Webhooks',     state: 'healthy',     endpoints: 28, successPct: 99.6, latencyMs: 88,  calls24h: 4124, lastError: null,                                                lastCall: '2026-05-11 09:42:58' },
];

const API_ENDPOINT_REGISTRY = [
  // (group, method, path, integration, auth, rateLimit, calls24h, p95ms, status, lastError)
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/dhl/shipments',         i: 'DHL Express', a: 'API Key + Site ID',        rl: '60/min',  c: 412, l: 318,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'GET',  p: '/api/v1/carriers/dhl/tracking/{awb}',    i: 'DHL Express', a: 'API Key',                  rl: '300/min', c: 3018,l: 142,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/dhl/labels',            i: 'DHL Express', a: 'API Key',                  rl: '30/min',  c: 412, l: 380,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/fedex/oauth/token',     i: 'FedEx',       a: 'Client Credentials',       rl: '—',       c: 8,   l: 411,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/fedex/ship',            i: 'FedEx',       a: 'Bearer',                   rl: '60/min',  c: 27,  l: 514,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/fedex/track',           i: 'FedEx',       a: 'Bearer',                   rl: '120/min', c: 612, l: 218,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/ups/oauth/authorize',   i: 'UPS',         a: 'OAuth2 Code',              rl: '—',       c: 0,   l: null, s: 'pending',  e: 'awaiting operator callback' },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/inpost/shipments',      i: 'InPost',      a: 'Bearer',                   rl: '20/min',  c: 12,  l: 184,  s: 'healthy',  e: null },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/gls/parcels',           i: 'GLS',         a: 'API Key',                  rl: '40/min',  c: 0,   l: null, s: 'disconnected', e: 'carrier disconnected' },
  { g: 'Carriers',  m: 'POST', p: '/api/v1/carriers/dpd/auth',              i: 'DPD',         a: 'Username + PW',            rl: '—',       c: 0,   l: null, s: 'error',    e: 'AUTH_401 — token rejected' },
  { g: 'Accounting',m: 'POST', p: '/api/v1/wfirma/invoices/add',            i: 'wFirma',      a: 'AccessKey',                rl: '120/min', c: 142, l: 280,  s: 'healthy',  e: null },
  { g: 'Accounting',m: 'GET',  p: '/api/v1/wfirma/invoices/{id}',           i: 'wFirma',      a: 'AccessKey',                rl: '300/min', c: 412, l: 188,  s: 'healthy',  e: null },
  { g: 'Accounting',m: 'POST', p: '/api/v1/wfirma/contractors/add',         i: 'wFirma',      a: 'AccessKey',                rl: '60/min',  c: 21,  l: 312,  s: 'healthy',  e: null },
  { g: 'Accounting',m: 'POST', p: '/api/v1/wfirma/goods/add',               i: 'wFirma',      a: 'AccessKey',                rl: '120/min', c: 84,  l: 314,  s: 'healthy',  e: null },
  { g: 'Accounting',m: 'POST', p: '/api/v1/proforma/draft/{id}/post',       i: 'wFirma',      a: 'Server token',             rl: '20/min',  c: 12,  l: 642,  s: 'healthy',  e: null },
  { g: 'Customs',   m: 'POST', p: '/api/v1/customs/sad/declarations/add',   i: 'SAD (PUESC)', a: 'mTLS + Cert',              rl: '20/min',  c: 18,  l: 1812, s: 'healthy',  e: null },
  { g: 'Customs',   m: 'GET',  p: '/api/v1/customs/sad/declarations/{mrn}', i: 'SAD (PUESC)', a: 'mTLS',                     rl: '60/min',  c: 46,  l: 1280, s: 'healthy',  e: null },
  { g: 'Customs',   m: 'POST', p: '/api/v1/customs/zc429/notice',           i: 'ZC429',       a: 'mTLS',                     rl: '20/min',  c: 31,  l: 2240, s: 'degraded', e: 'Intermittent 502 from PUESC' },
  { g: 'Internal',  m: 'POST', p: '/api/v1/cowork/tasks',                   i: 'Cowork',      a: 'JWT',                      rl: '600/min', c: 412, l: 142,  s: 'healthy',  e: null },
  { g: 'Internal',  m: 'GET',  p: '/api/v1/cowork/tasks/{id}',              i: 'Cowork',      a: 'JWT',                      rl: '1200/min',c: 8000,l: 78,   s: 'healthy',  e: null },
  { g: 'Internal',  m: 'POST', p: '/api/v1/ai-bridge/complete',             i: 'AI Bridge',   a: 'JWT',                      rl: '60/min',  c: 412, l: 1842, s: 'healthy',  e: null },
  { g: 'Internal',  m: 'POST', p: '/api/v1/ocr/parse',                      i: 'OCR',         a: 'JWT',                      rl: '120/min', c: 184, l: 3210, s: 'healthy',  e: null },
  { g: 'Internal',  m: 'POST', p: '/api/v1/documents/{type}',               i: 'Storage',     a: 'JWT',                      rl: '300/min', c: 822, l: 42,   s: 'healthy',  e: null },
  { g: 'Internal',  m: 'PATCH',p: '/api/v1/documents/{id}',                 i: 'Storage',     a: 'JWT',                      rl: '300/min', c: 412, l: 38,   s: 'healthy',  e: null },
  { g: 'Internal',  m: 'DELETE',p:'/api/v1/documents/{id}',                 i: 'Storage',     a: 'JWT',                      rl: '60/min',  c: 18,  l: 41,   s: 'healthy',  e: null },
  { g: 'Internal',  m: 'GET',  p: '/api/v1/documents/{id}/download',        i: 'Storage',     a: 'JWT',                      rl: '600/min', c: 2418,l: 28,   s: 'healthy',  e: null },
  { g: 'Webhooks',  m: 'POST', p: '/webhooks/carriers/dhl/tracking',        i: 'Webhook',     a: 'HMAC',                     rl: '∞',       c: 3018,l: 88,   s: 'healthy',  e: null },
  { g: 'Webhooks',  m: 'POST', p: '/webhooks/carriers/fedex/track',         i: 'Webhook',     a: 'HMAC',                     rl: '∞',       c: 612, l: 92,   s: 'healthy',  e: null },
  { g: 'Webhooks',  m: 'POST', p: '/webhooks/customs/sad/status',           i: 'Webhook',     a: 'HMAC',                     rl: '∞',       c: 31,  l: 102,  s: 'healthy',  e: null },
  { g: 'Webhooks',  m: 'POST', p: '/webhooks/wfirma/invoice/issued',        i: 'Webhook',     a: 'HMAC',                     rl: '∞',       c: 142, l: 71,   s: 'healthy',  e: null },
];

const RECENT_ERRORS = [
  { ts: '2026-05-11 09:11:08', integration: 'ZC429',     endpoint: '/customs/zc429/notice',  code: '502', message: 'Bad Gateway — PUESC upstream',                actor: 'system', occurrences: 3 },
  { ts: '2026-05-11 06:14:22', integration: 'SAD (PUESC)', endpoint: '/sad/declarations/lookup', code: 'TIMEOUT', message: 'Request exceeded 30s',                  actor: 'system', occurrences: 1 },
  { ts: '2026-05-10 22:17:44', integration: 'DPD',       endpoint: '/dpd/auth',              code: '401', message: 'token rejected — credentials expired',         actor: 'system', occurrences: 14 },
  { ts: '2026-05-10 18:02:11', integration: 'OCR',       endpoint: '/ocr/parse',             code: 'LOW_CONF', message: 'Confidence 0.42 — queued for manual review', actor: 'system', occurrences: 2 },
  { ts: '2026-05-09 14:08:00', integration: 'GLS',       endpoint: '/gls/parcels',           code: 'DISCONN', message: 'Carrier disconnected by operator',         actor: 'admin@estrella.pl', occurrences: 1 },
];

const INCIDENTS = [
  { id: 'INC-2026-014', opened: '2026-05-10 22:17', closed: null,                  severity: 'P2', integration: 'DPD',       title: 'DPD authentication failure',           status: 'open' },
  { id: 'INC-2026-013', opened: '2026-05-11 09:00', closed: null,                  severity: 'P3', integration: 'ZC429',     title: 'PUESC intermittent 502s',              status: 'investigating' },
  { id: 'INC-2026-012', opened: '2026-05-09 12:30', closed: '2026-05-09 13:48',    severity: 'P3', integration: 'wFirma',    title: 'Slow response on /invoices/add (>2s)', status: 'resolved' },
  { id: 'INC-2026-011', opened: '2026-05-08 04:11', closed: '2026-05-08 04:42',    severity: 'P2', integration: 'AI Bridge', title: 'Cowork queue backup',                  status: 'resolved' },
];

const apiStateChip = (s) => {
  const m = {
    healthy:      { label: 'Healthy',      bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    degraded:     { label: 'Degraded',     bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
    error:        { label: 'Error',        bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    pending:      { label: 'Pending',      bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
    disconnected: { label: 'Disconnected', bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    configured:   { label: 'Configured',   bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    investigating:{ label: 'Investigating',bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
    open:         { label: 'Open',         bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    resolved:     { label: 'Resolved',     bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  };
  const v = m[s] || m.healthy;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: v.bg, color: v.text, border: `1px solid ${v.border}`,
      borderRadius: 4, padding: '2px 7px', fontSize: 10, fontWeight: 600,
      letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{v.label}</span>
  );
};

// Pulled from carriers-page.jsx window exports (loaded first)
const CarrierKpi = window.CarrierKpi;
const ApiBtn     = window.ApiBtn;
const Tbl        = window.Tbl;

function ApiStatusPage() {
  const [tab, setTab]   = React.useState('overview');
  const [query, setQuery] = React.useState('');
  const [grpFilter, setGrpFilter] = React.useState('All');

  const filtered = API_ENDPOINT_REGISTRY.filter(e =>
    (grpFilter === 'All' || e.g === grpFilter) &&
    (query === '' || (e.p + ' ' + e.i).toLowerCase().includes(query.toLowerCase()))
  );

  const healthyCount = API_INTEGRATIONS.filter(i => i.state === 'healthy').length;
  const totalCalls = API_INTEGRATIONS.reduce((s, i) => s + i.calls24h, 0);
  const openIncidents = INCIDENTS.filter(i => i.status !== 'resolved').length;

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 32px 40px' }}>
      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <CarrierKpi label="Healthy / Total"  value={`${healthyCount} of ${API_INTEGRATIONS.length}`} accent="var(--badge-green-text)" />
        <CarrierKpi label="Calls (24 h)"      value={totalCalls.toLocaleString()}                     accent="var(--text)" />
        <CarrierKpi label="P95 latency"       value="318 ms"                                           accent="var(--accent)" />
        <CarrierKpi label="Open incidents"    value={openIncidents > 0 ? `${openIncidents} active`    : 'None'} accent={openIncidents ? 'var(--badge-red-text)' : 'var(--badge-green-text)'} />
      </div>

      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'overview',  label: 'Integrations' },
          { id: 'endpoints', label: 'Endpoint Registry' },
          { id: 'errors',    label: 'Recent Errors' },
          { id: 'incidents', label: 'Incidents' },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '8px 14px 10px', fontSize: 12,
            fontWeight: tab === t.id ? 700 : 500,
            color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
            borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1, letterSpacing: '0.01em',
          }}>{t.label}</button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'overview'  && <ApiStatusOverviewTab />}
      {tab === 'endpoints' && <ApiStatusEndpointsTab query={query} setQuery={setQuery} grpFilter={grpFilter} setGrpFilter={setGrpFilter} rows={filtered} />}
      {tab === 'errors'    && <ApiStatusErrorsTab />}
      {tab === 'incidents' && <ApiStatusIncidentsTab />}
    </div>
  );
}

function ApiStatusOverviewTab() {
  const byGroup = API_INTEGRATIONS.reduce((acc, i) => {
    (acc[i.group] = acc[i.group] || []).push(i);
    return acc;
  }, {});
  const order = ['Carriers','Accounting','Customs','Internal','Webhooks'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {order.map(g => (
        <div key={g}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8,
          }}>{g}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
            {(byGroup[g] || []).map(it => <ApiIntegrationCard key={it.id} it={it} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function ApiIntegrationCard({ it }) {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, padding: 14, boxShadow: '0 1px 3px var(--shadow)',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{it.name}</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{it.endpoints} endpoints</div>
        </div>
        {apiStateChip(it.state)}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 10, rowGap: 4, fontSize: 11 }}>
        <span style={{ color: 'var(--text-3)' }}>Success</span>
        <span style={{ color: it.successPct > 95 ? 'var(--badge-green-text)' : it.successPct > 80 ? 'var(--badge-yellow-text)' : 'var(--badge-red-text)', fontFamily: 'monospace', fontWeight: 600 }}>{it.successPct}%</span>
        <span style={{ color: 'var(--text-3)' }}>P95 latency</span>
        <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>{it.latencyMs ? `${it.latencyMs} ms` : '—'}</span>
        <span style={{ color: 'var(--text-3)' }}>Calls 24h</span>
        <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>{it.calls24h.toLocaleString()}</span>
        <span style={{ color: 'var(--text-3)' }}>Last call</span>
        <span style={{ color: 'var(--text-2)', fontFamily: 'monospace', fontSize: 10.5 }}>{it.lastCall}</span>
      </div>
      {it.lastError && (
        <div style={{
          marginTop: 10, padding: '6px 10px', borderRadius: 4,
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', fontSize: 10.5, fontFamily: 'monospace',
        }}>{it.lastError}</div>
      )}
      <div style={{ display: 'flex', gap: 4, marginTop: 10 }}>
        <ApiBtn small title={`POST /api/v1/admin/api-status/${it.id}/test`}>⚡ Probe</ApiBtn>
        <ApiBtn small variant="ghost" title={`GET /api/v1/admin/api-status/${it.id}/logs`}>Logs</ApiBtn>
      </div>
    </div>
  );
}

function ApiStatusEndpointsTab({ query, setQuery, grpFilter, setGrpFilter, rows }) {
  const groups = ['All','Carriers','Accounting','Customs','Internal','Webhooks'];
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', display: 'flex', gap: 8, alignItems: 'center', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search path or integration…"
          style={{ flex: 1, maxWidth: 360, padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 4, fontSize: 12, background: 'var(--card)', color: 'var(--text)', outline: 'none' }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {groups.map(g => (
            <button key={g} onClick={() => setGrpFilter(g)} style={{
              padding: '5px 10px', fontSize: 10.5, borderRadius: 4, cursor: 'pointer',
              background: grpFilter === g ? 'var(--text)' : 'var(--card)',
              color:      grpFilter === g ? 'var(--card)' : 'var(--text-2)',
              border: '1px solid ' + (grpFilter === g ? 'var(--text)' : 'var(--border)'),
              fontWeight: grpFilter === g ? 700 : 500,
            }}>{g}</button>
          ))}
        </div>
        <span style={{ marginLeft: 'auto', fontSize: 10.5, color: 'var(--text-3)' }}>{rows.length} of {API_ENDPOINT_REGISTRY.length}</span>
      </div>
      <Tbl
        cols={['Method','Endpoint','Integration','Auth','Rate','Calls 24h','P95','State']}
        widths={['72px','1fr','130px','170px','90px','90px','70px','110px']}
        rows={rows.map(e => [
          <span style={{
            display: 'inline-block', padding: '1px 7px', borderRadius: 3,
            fontSize: 9.5, fontWeight: 700, fontFamily: 'monospace',
            background: e.m === 'GET' ? 'var(--badge-blue-bg)' : e.m === 'DELETE' ? 'var(--badge-red-bg)' : 'var(--accent-subtle)',
            color:      e.m === 'GET' ? 'var(--badge-blue-text)' : e.m === 'DELETE' ? 'var(--badge-red-text)' : 'var(--accent)',
            border: '1px solid ' + (e.m === 'GET' ? 'var(--badge-blue-border)' : e.m === 'DELETE' ? 'var(--badge-red-border)' : 'var(--accent-border)'),
          }}>{e.m}</span>,
          <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text)' }}>{e.p}</span>,
          <span style={{ fontSize: 11, color: 'var(--text)' }}>{e.i}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{e.a}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{e.rl}</span>,
          <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}>{e.c.toLocaleString()}</span>,
          <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}>{e.l ? `${e.l} ms` : '—'}</span>,
          apiStateChip(e.s),
        ])}
      />
    </div>
  );
}

function ApiStatusErrorsTab() {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <Tbl
        cols={['Timestamp','Integration','Endpoint','Code','Message','Actor','Count']}
        widths={['140px','130px','230px','90px','1fr','170px','70px']}
        rows={RECENT_ERRORS.map(r => [
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{r.ts}</span>,
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>{r.integration}</span>,
          <span style={{ fontSize: 10.5, color: 'var(--text-2)', fontFamily: 'monospace' }}>{r.endpoint}</span>,
          <span style={{ fontSize: 10.5, color: 'var(--badge-red-text)', fontFamily: 'monospace', fontWeight: 700 }}>{r.code}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{r.message}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{r.actor}</span>,
          <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'monospace', fontWeight: 600 }}>{r.occurrences}</span>,
        ])}
      />
    </div>
  );
}

function ApiStatusIncidentsTab() {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <Tbl
        cols={['ID','Opened','Closed','Sev','Integration','Title','Status','Action']}
        widths={['130px','130px','130px','50px','130px','1fr','120px','110px']}
        rows={INCIDENTS.map(i => [
          <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'monospace', fontWeight: 600 }}>{i.id}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{i.opened}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{i.closed || '—'}</span>,
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
            color: i.severity === 'P1' ? 'var(--badge-red-text)' : i.severity === 'P2' ? 'var(--badge-yellow-text)' : 'var(--badge-blue-text)',
            background: i.severity === 'P1' ? 'var(--badge-red-bg)' : i.severity === 'P2' ? 'var(--badge-yellow-bg)' : 'var(--badge-blue-bg)',
            border: '1px solid ' + (i.severity === 'P1' ? 'var(--badge-red-border)' : i.severity === 'P2' ? 'var(--badge-yellow-border)' : 'var(--badge-blue-border)'),
          }}>{i.severity}</span>,
          <span style={{ fontSize: 11, color: 'var(--text)', fontWeight: 600 }}>{i.integration}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{i.title}</span>,
          apiStateChip(i.status),
          <ApiBtn small variant="ghost" title={`GET /api/v1/admin/api-status/incidents/${i.id}`}>Open</ApiBtn>,
        ])}
      />
    </div>
  );
}

window.ApiStatusPage = ApiStatusPage;
