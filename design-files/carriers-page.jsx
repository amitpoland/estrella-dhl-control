// ─────────────────────────────────────────────────────────────────────────────
// CarriersPage — multi-carrier login & API integration registry
//
// Backend hooks (all wireframe; nothing live):
//   GET  /api/v1/carriers                    — list connected accounts
//   POST /api/v1/carriers/{id}/test          — ping carrier sandbox / prod
//   POST /api/v1/carriers/{id}/credentials   — rotate/edit credentials
//   POST /api/v1/carriers/{id}/disconnect    — revoke session, clear tokens
//   POST /api/v1/carriers/{id}/oauth/start   — begin OAuth flow (FedEx, UPS)
//   GET  /api/v1/carriers/{id}/webhooks      — webhook receiver health
//   GET  /api/v1/carriers/{id}/services      — supported services / rate plans
//   GET  /api/v1/carriers/audit              — credential audit log
//
// All write buttons stay disabled with an API chip + tooltip naming the
// endpoint. No live credentials are shipped — placeholders only.
// ─────────────────────────────────────────────────────────────────────────────

const CARRIER_TABS = [
  { id: 'accounts',    label: 'Carrier Accounts' },
  { id: 'add',         label: 'Add Carrier' },
  { id: 'integration', label: 'API Integration' },
  { id: 'webhooks',    label: 'Webhooks' },
  { id: 'sessions',    label: 'Active Sessions' },
  { id: 'audit',       label: 'Audit Log' },
];

const CARRIERS = [
  {
    id: 'dhl-express', name: 'DHL Express', code: 'DHL', logo: 'D',
    env: 'production', state: 'connected', auth: 'API Key + Site ID',
    account: '954********', sandboxAccount: '980********',
    services: ['Express Worldwide', 'Express 9:00', 'Express 12:00', 'Economy Select'],
    lastPing: '2026-05-11 09:42:14', pingMs: 312, region: 'EU · APAC · AMR',
    quotaUsed: 1247, quotaLimit: 5000,
    docs: ['Commercial Invoice', 'Waybill', 'CN23'],
  },
  {
    id: 'fedex', name: 'FedEx', code: 'FDX', logo: 'F',
    env: 'sandbox', state: 'connected', auth: 'OAuth2 Client Credentials',
    account: '740********', sandboxAccount: '510********',
    services: ['International Priority', 'International Economy', 'International First'],
    lastPing: '2026-05-11 09:38:02', pingMs: 411, region: 'Global',
    quotaUsed: 38, quotaLimit: 2500,
    docs: ['Commercial Invoice', 'Air Waybill'],
  },
  {
    id: 'ups', name: 'UPS', code: 'UPS', logo: 'U',
    env: 'sandbox', state: 'pending_oauth', auth: 'OAuth2 Authorization Code',
    account: '—', sandboxAccount: '7T****',
    services: ['Worldwide Express', 'Worldwide Saver', 'Worldwide Expedited'],
    lastPing: '—', pingMs: null, region: 'Global',
    quotaUsed: 0, quotaLimit: 1000,
    docs: ['Commercial Invoice'],
  },
  {
    id: 'gls', name: 'GLS', code: 'GLS', logo: 'G',
    env: 'production', state: 'disconnected', auth: 'API Key',
    account: '—', sandboxAccount: '—',
    services: ['Business Parcel', 'Express'],
    lastPing: '2026-04-22 14:01:00', pingMs: null, region: 'EU',
    quotaUsed: 0, quotaLimit: 3000,
    docs: ['Commercial Invoice'],
  },
  {
    id: 'inpost', name: 'InPost', code: 'INP', logo: 'i',
    env: 'sandbox', state: 'configured', auth: 'Bearer Token',
    account: '—', sandboxAccount: 'shop_*****',
    services: ['Paczkomat 24/7', 'Kurier'],
    lastPing: '2026-05-09 11:24:00', pingMs: 184, region: 'PL · CZ · DE',
    quotaUsed: 12, quotaLimit: 2000,
    docs: ['Label'],
  },
  {
    id: 'dpd', name: 'DPD', code: 'DPD', logo: 'd',
    env: 'production', state: 'error', auth: 'Username + Password',
    account: 'estr_pl', sandboxAccount: '—',
    services: ['Classic', 'Pickup'],
    lastPing: '2026-05-10 22:17:44', pingMs: null, region: 'EU',
    quotaUsed: 0, quotaLimit: 0,
    docs: ['Label'],
    errorMsg: 'AUTH_401 — token rejected; needs rotation',
  },
];

const AVAILABLE_NEW = [
  { code: 'TNT', name: 'TNT', auth: 'API Key', region: 'Global' },
  { code: 'AMZ', name: 'Amazon Shipping', auth: 'OAuth2', region: 'EU · US' },
  { code: 'POC', name: 'Poczta Polska', auth: 'SOAP Auth', region: 'PL' },
  { code: 'ARM', name: 'Aramex', auth: 'API Key', region: 'MENA · APAC' },
  { code: 'PSL', name: 'PostNL', auth: 'API Key', region: 'NL · BE · DE' },
  { code: 'CHN', name: 'China Post', auth: 'OAuth2', region: 'CN' },
];

const API_ENDPOINTS = [
  { method: 'POST', path: '/api/v1/carriers/dhl/shipments',       auth: 'API Key + Site ID', rateLimit: '60 / min', status: 'connected' },
  { method: 'GET',  path: '/api/v1/carriers/dhl/tracking/{awb}',  auth: 'API Key',           rateLimit: '300 / min', status: 'connected' },
  { method: 'POST', path: '/api/v1/carriers/dhl/labels',          auth: 'API Key',           rateLimit: '30 / min', status: 'connected' },
  { method: 'POST', path: '/api/v1/carriers/fedex/oauth/token',   auth: 'Client Credentials',rateLimit: '—',         status: 'connected' },
  { method: 'POST', path: '/api/v1/carriers/fedex/ship',          auth: 'Bearer',            rateLimit: '60 / min', status: 'connected' },
  { method: 'POST', path: '/api/v1/carriers/fedex/track',         auth: 'Bearer',            rateLimit: '120 / min', status: 'connected' },
  { method: 'POST', path: '/api/v1/carriers/ups/oauth/authorize', auth: 'OAuth2 Code',       rateLimit: '—',         status: 'pending' },
  { method: 'POST', path: '/api/v1/carriers/inpost/shipments',    auth: 'Bearer',            rateLimit: '20 / min', status: 'configured' },
  { method: 'POST', path: '/api/v1/carriers/gls/parcels',         auth: 'API Key',           rateLimit: '40 / min', status: 'disconnected' },
  { method: 'POST', path: '/api/v1/carriers/dpd/auth',            auth: 'Username + PW',     rateLimit: '—',         status: 'error' },
  { method: 'POST', path: '/api/v1/carriers/{id}/test',           auth: '—',                  rateLimit: '—',         status: 'meta' },
  { method: 'POST', path: '/api/v1/carriers/{id}/disconnect',     auth: '—',                  rateLimit: '—',         status: 'meta' },
];

const WEBHOOKS = [
  { carrier: 'DHL Express', event: 'shipment.created',     url: '/webhooks/carriers/dhl/created',  state: 'active',   last24h: 142 },
  { carrier: 'DHL Express', event: 'tracking.update',      url: '/webhooks/carriers/dhl/tracking', state: 'active',   last24h: 3018 },
  { carrier: 'DHL Express', event: 'delivery.confirmed',   url: '/webhooks/carriers/dhl/delivered',state: 'active',   last24h: 89 },
  { carrier: 'FedEx',       event: 'shipment.confirmed',   url: '/webhooks/carriers/fedex/ship',   state: 'active',   last24h: 27 },
  { carrier: 'FedEx',       event: 'tracking.update',      url: '/webhooks/carriers/fedex/track',  state: 'active',   last24h: 612 },
  { carrier: 'UPS',         event: 'oauth.callback',       url: '/webhooks/carriers/ups/oauth',    state: 'pending',  last24h: 0 },
  { carrier: 'InPost',      event: 'parcel.locker_dropped',url: '/webhooks/carriers/inpost/drop',  state: 'configured', last24h: 0 },
  { carrier: 'DPD',         event: 'tracking.update',      url: '/webhooks/carriers/dpd/track',    state: 'error',    last24h: 0 },
];

const SESSIONS = [
  { carrier: 'DHL Express', user: 'admin@estrella.pl',   token: 'k_dhl_2026****a9c2', issued: '2026-05-11 08:00', expires: '2026-05-11 16:00', ip: '10.0.4.21', state: 'active' },
  { carrier: 'FedEx',       user: 'system',              token: 'fx_oauth_****d1f0',  issued: '2026-05-11 06:22', expires: '2026-05-11 22:22', ip: 'service',   state: 'active' },
  { carrier: 'FedEx',       user: 'admin@estrella.pl',   token: 'fx_user_****81bb',   issued: '2026-05-11 09:14', expires: '2026-05-11 17:14', ip: '10.0.4.21', state: 'active' },
  { carrier: 'InPost',      user: 'ops@estrella.pl',     token: 'inp_****0c14',       issued: '2026-05-10 14:08', expires: '2026-05-17 14:08', ip: '10.0.4.42', state: 'active' },
  { carrier: 'UPS',         user: 'admin@estrella.pl',   token: '—',                  issued: '—',                expires: '—',                ip: '—',         state: 'pending' },
];

const AUDIT = [
  { ts: '2026-05-11 09:42', carrier: 'DHL Express', actor: 'admin@estrella.pl', event: 'credentials.test',    detail: 'Test ping → 200 OK · 312 ms' },
  { ts: '2026-05-11 09:14', carrier: 'FedEx',       actor: 'admin@estrella.pl', event: 'oauth.refresh',       detail: 'Bearer rotated, expires 17:14' },
  { ts: '2026-05-11 06:22', carrier: 'FedEx',       actor: 'system',            event: 'oauth.refresh.auto',  detail: 'Background refresh; success' },
  { ts: '2026-05-10 22:17', carrier: 'DPD',         actor: 'system',            event: 'auth.error',          detail: 'AUTH_401 — token rejected · alert raised' },
  { ts: '2026-05-10 14:08', carrier: 'InPost',      actor: 'ops@estrella.pl',   event: 'credentials.added',   detail: 'Bearer Token added (sandbox)' },
  { ts: '2026-05-09 17:30', carrier: 'GLS',         actor: 'admin@estrella.pl', event: 'carrier.disconnect',  detail: 'Manual disconnect — tokens revoked' },
  { ts: '2026-05-08 11:02', carrier: 'UPS',         actor: 'admin@estrella.pl', event: 'oauth.start',         detail: 'OAuth flow initiated → awaiting callback' },
  { ts: '2026-05-08 10:55', carrier: 'UPS',         actor: 'admin@estrella.pl', event: 'carrier.added',       detail: 'Created sandbox account record' },
];

// State chip colours (extends global chip vocab for carriers)
const carrierStateChip = (s) => {
  const m = {
    connected:    { label: 'Connected',     bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    sandbox:      { label: 'Sandbox',       bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
    pending_oauth:{ label: 'OAuth Pending', bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
    configured:   { label: 'Configured',    bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    disconnected: { label: 'Disconnected',  bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    error:        { label: 'Error',         bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    pending:      { label: 'Pending',       bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
    active:       { label: 'Active',        bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    meta:         { label: 'Meta',          bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  };
  const v = m[s] || m.configured;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: v.bg, color: v.text, border: `1px solid ${v.border}`,
      borderRadius: 4, padding: '2px 7px', fontSize: 10, fontWeight: 600,
      letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{v.label}</span>
  );
};

function CarriersPage() {
  const [tab, setTab] = React.useState('accounts');
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 32px 40px' }}>
      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <CarrierKpi label="Connected"     value="4 of 6"     accent="var(--badge-green-text)" />
        <CarrierKpi label="Sandbox / Prod" value="3 / 1"      accent="var(--badge-blue-text)"  />
        <CarrierKpi label="Webhooks 24h"   value="3,888"      accent="var(--text)"             />
        <CarrierKpi label="Open Alerts"    value="1 · DPD AUTH_401" accent="var(--badge-red-text)" />
      </div>

      {/* Inline tab strip for module-internal sections */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {CARRIER_TABS.map(t => (
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

      {tab === 'accounts'    && <CarrierAccountsTab />}
      {tab === 'add'         && <AddCarrierTab />}
      {tab === 'integration' && <ApiIntegrationTab />}
      {tab === 'webhooks'    && <WebhooksTab />}
      {tab === 'sessions'    && <SessionsTab />}
      {tab === 'audit'       && <AuditTab />}
    </div>
  );
}

function CarrierKpi({ label, value, accent }) {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, padding: '12px 16px',
      boxShadow: '0 1px 3px var(--shadow)',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: accent, marginTop: 4, fontFamily: '"DM Serif Display", serif' }}>{value}</div>
    </div>
  );
}

// ─── Carrier Accounts ───────────────────────────────────────────────────────

function CarrierAccountsTab() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 14 }}>
      {CARRIERS.map(c => <CarrierCard key={c.id} carrier={c} />)}
      <AddCarrierCard />
    </div>
  );
}

function CarrierCard({ carrier }) {
  const c = carrier;
  const pct = c.quotaLimit ? Math.min(100, Math.round((c.quotaUsed / c.quotaLimit) * 100)) : 0;
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, padding: 16, boxShadow: '0 1px 3px var(--shadow)',
      display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          width: 38, height: 38, borderRadius: 6,
          background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 16, fontWeight: 700, color: 'var(--accent)',
          fontFamily: '"DM Serif Display", serif',
        }}>{c.logo}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{c.name}</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{c.code} · {c.region}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
          {carrierStateChip(c.state)}
          {carrierStateChip(c.env === 'production' ? 'connected' : 'sandbox')}
        </div>
      </div>

      {c.state === 'error' && (
        <div style={{
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', padding: '6px 10px', borderRadius: 4,
          fontSize: 11, fontFamily: 'monospace',
        }}>{c.errorMsg}</div>
      )}

      {/* Body */}
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 10, rowGap: 4, fontSize: 11 }}>
        <span style={{ color: 'var(--text-3)' }}>Auth</span>
        <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>{c.auth}</span>
        <span style={{ color: 'var(--text-3)' }}>Prod acct</span>
        <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>{c.account}</span>
        <span style={{ color: 'var(--text-3)' }}>Sandbox</span>
        <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>{c.sandboxAccount}</span>
        <span style={{ color: 'var(--text-3)' }}>Last ping</span>
        <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>
          {c.lastPing}{c.pingMs ? <span style={{ color: 'var(--text-3)' }}> · {c.pingMs} ms</span> : null}
        </span>
      </div>

      {/* Services */}
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Services</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {c.services.map(s => (
            <span key={s} style={{
              background: 'var(--bg-subtle)', border: '1px solid var(--border)',
              color: 'var(--text-2)', fontSize: 10, padding: '2px 7px', borderRadius: 3,
            }}>{s}</span>
          ))}
        </div>
      </div>

      {/* Quota bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-3)', marginBottom: 3 }}>
          <span>Monthly quota</span>
          <span>{c.quotaUsed.toLocaleString()} / {c.quotaLimit.toLocaleString()}</span>
        </div>
        <div style={{ height: 5, background: 'var(--bg-subtle)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{
            width: `${pct}%`, height: '100%',
            background: pct > 80 ? 'var(--badge-red-text)' : pct > 50 ? 'var(--accent)' : 'var(--badge-green-text)',
          }} />
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
        <ApiBtn title="POST /api/v1/carriers/{id}/test">⚡ Test Connection</ApiBtn>
        <ApiBtn title="POST /api/v1/carriers/{id}/credentials">✎ Edit Credentials</ApiBtn>
        {c.state === 'pending_oauth' && <ApiBtn variant="gold" title="POST /api/v1/carriers/{id}/oauth/start">↗ Complete OAuth</ApiBtn>}
        {c.state === 'connected' && <ApiBtn variant="danger" title="POST /api/v1/carriers/{id}/disconnect">⊘ Disconnect</ApiBtn>}
        {c.state === 'disconnected' && <ApiBtn variant="gold" title="POST /api/v1/carriers/{id}/connect">↗ Re-connect</ApiBtn>}
        {c.state === 'error' && <ApiBtn variant="gold" title="POST /api/v1/carriers/{id}/credentials">↻ Rotate Token</ApiBtn>}
      </div>
    </div>
  );
}

function AddCarrierCard() {
  return (
    <div style={{
      background: 'var(--bg-subtle)', border: '1px dashed var(--border)',
      borderRadius: 8, padding: 16,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', minHeight: 280, gap: 8,
    }}>
      <div style={{ fontSize: 24, color: 'var(--text-3)' }}>+</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>Add Carrier</div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', textAlign: 'center', maxWidth: 260 }}>
        Connect a new carrier — supports API key, OAuth2, and bearer-token auth.
      </div>
      <ApiBtn variant="gold" title="POST /api/v1/carriers — opens new-carrier modal">+ Connect Carrier</ApiBtn>
    </div>
  );
}

// ─── Add Carrier tab — explicit form ───────────────────────────────────────

function AddCarrierTab() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 16 }}>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 8, padding: 20, boxShadow: '0 1px 3px var(--shadow)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 6 }}>
          Connect a Carrier
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 16 }}>
          Configure carrier credentials and environment. The system validates the connection
          before storing tokens. All credentials are encrypted at rest.
        </div>

        <FormSection title="Carrier">
          <FieldGrid>
            <Field label="Carrier" type="select" options={['DHL Express','FedEx','UPS','GLS','InPost','DPD','TNT','PostNL','Aramex','Poczta Polska','Amazon Shipping','China Post','Other…']} />
            <Field label="Display name" placeholder="e.g. DHL EU — Estrella Main" />
            <Field label="Environment" type="select" options={['Sandbox','Production']} />
            <Field label="Region scope" type="select" options={['EU only','Global','EU + APAC','EU + AMR','Custom…']} />
          </FieldGrid>
        </FormSection>

        <FormSection title="Authentication">
          <FieldGrid>
            <Field label="Auth method" type="select" options={['API Key','OAuth2 Client Credentials','OAuth2 Authorization Code','Bearer Token','Username + Password','SOAP Auth']} />
            <Field label="Site / Account ID" placeholder="954XXXXXXX" />
            <Field label="API Key / Client ID" placeholder="••••••••••••••••" mono />
            <Field label="API Secret / Client Secret" placeholder="••••••••••••••••" mono />
            <Field label="OAuth Callback URL" value="https://app.estrella.pl/webhooks/oauth/callback" mono readOnly />
            <Field label="Webhook Secret" placeholder="auto-generate on save" mono readOnly />
          </FieldGrid>
        </FormSection>

        <FormSection title="Services & defaults">
          <FieldGrid>
            <Field label="Default service" placeholder="e.g. Express Worldwide" />
            <Field label="Default incoterm" type="select" options={['DAP','DDP','DDU','FCA','EXW']} />
            <Field label="Pickup mode" type="select" options={['Drop-off','Scheduled pickup','Daily pickup']} />
            <Field label="Insurance default" type="select" options={['Off','Auto when value > €1,000','Always']} />
          </FieldGrid>
        </FormSection>

        <div style={{ display: 'flex', gap: 8, marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border-subtle)' }}>
          <ApiBtn title="POST /api/v1/carriers/test (unsaved)">⚡ Test Connection</ApiBtn>
          <ApiBtn variant="gold" title="POST /api/v1/carriers — saves + initiates OAuth if needed">✓ Save & Connect</ApiBtn>
          <ApiBtn variant="outline" title="Resets form">✕ Cancel</ApiBtn>
        </div>
      </div>

      {/* Side rail: integration checklist */}
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 8, padding: 16, boxShadow: '0 1px 3px var(--shadow)',
        height: 'fit-content',
      }}>
        <div style={{ fontSize: 12, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 4 }}>
          Integration Checklist
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 12 }}>
          Required for go-live with this carrier
        </div>
        {[
          ['Carrier account number / Site ID', 'pending'],
          ['API credentials (key / secret)',   'pending'],
          ['OAuth2 callback whitelisted',      'pending'],
          ['Sandbox connection test passed',   'pending'],
          ['Webhook endpoints registered',     'pending'],
          ['Production credentials',           'blocked'],
          ['Approval from carrier rep',        'blocked'],
          ['Insurance contract on file',       'optional'],
          ['Tariff agreement uploaded',        'optional'],
        ].map(([t, s], i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '6px 0', borderBottom: '1px dashed var(--border-subtle)', fontSize: 11,
          }}>
            <span style={{ width: 14 }}>{s === 'optional' ? '○' : '◌'}</span>
            <span style={{ flex: 1, color: 'var(--text)' }}>{t}</span>
            {carrierStateChip(s === 'pending' ? 'pending' : s === 'blocked' ? 'error' : 'meta')}
          </div>
        ))}
        <div style={{ marginTop: 12, padding: 10, background: 'var(--accent-subtle)', borderRadius: 4, fontSize: 10, color: 'var(--text-2)', border: '1px solid var(--accent-border)' }}>
          <b>Note:</b> Production credentials require carrier-side approval and a signed tariff
          agreement on file. Use sandbox to validate the integration end-to-end first.
        </div>
      </div>
    </div>
  );
}

function FormSection({ title, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{
        fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10,
      }}>{title}</div>
      {children}
    </div>
  );
}
function FieldGrid({ children }) {
  return <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>{children}</div>;
}
function Field({ label, placeholder, value, type = 'text', options = [], mono, readOnly }) {
  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    padding: '7px 10px', border: '1px solid var(--border)',
    borderRadius: 4, fontSize: 12, color: 'var(--text)',
    background: readOnly ? 'var(--bg-subtle)' : 'var(--card)',
    fontFamily: mono ? 'monospace' : 'inherit',
    outline: 'none',
  };
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 4, fontWeight: 600, letterSpacing: '0.02em' }}>{label}</div>
      {type === 'select' ? (
        <select defaultValue={value} style={inputStyle}>
          {options.map(o => <option key={o}>{o}</option>)}
        </select>
      ) : (
        <input defaultValue={value} placeholder={placeholder} readOnly={readOnly} style={inputStyle} />
      )}
    </div>
  );
}

// ─── API Integration tab ───────────────────────────────────────────────────

function ApiIntegrationTab() {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)',
    }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>
          Backend API Surface
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>
          Endpoint registry — every carrier integration call. All paths are wireframe stubs;
          state column reflects readiness of the underlying carrier account.
        </div>
      </div>
      <Tbl
        cols={['Method','Endpoint','Auth','Rate limit','State']}
        widths={['80px','1fr','220px','120px','120px']}
        rows={API_ENDPOINTS.map(e => [
          <span style={{
            display: 'inline-block', padding: '1px 7px', borderRadius: 3,
            fontSize: 9.5, fontWeight: 700, fontFamily: 'monospace',
            background: e.method === 'GET' ? 'var(--badge-blue-bg)' : 'var(--accent-subtle)',
            color: e.method === 'GET' ? 'var(--badge-blue-text)' : 'var(--accent)',
            border: e.method === 'GET' ? '1px solid var(--badge-blue-border)' : '1px solid var(--accent-border)',
          }}>{e.method}</span>,
          <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text)' }}>{e.path}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{e.auth}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{e.rateLimit}</span>,
          carrierStateChip(e.status),
        ])}
      />
    </div>
  );
}

// ─── Webhooks tab ──────────────────────────────────────────────────────────

function WebhooksTab() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{
        background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <span style={{ fontSize: 16, color: 'var(--accent)' }}>⚯</span>
        <div style={{ flex: 1 }}>
          <b style={{ color: 'var(--text)' }}>Receiver base URL</b>{' '}
          <span style={{ fontFamily: 'monospace' }}>https://app.estrella.pl/webhooks/carriers/&#123;carrier&#125;/&#123;event&#125;</span>
        </div>
        <ApiBtn small title="POST /api/v1/webhooks/secret/rotate">↻ Rotate Secret</ApiBtn>
      </div>

      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <Tbl
          cols={['Carrier','Event','URL','State','24h count','Action']}
          widths={['140px','190px','1fr','110px','100px','170px']}
          rows={WEBHOOKS.map(w => [
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{w.carrier}</span>,
            <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{w.event}</span>,
            <span style={{ fontSize: 10.5, color: 'var(--text-2)', fontFamily: 'monospace' }}>{w.url}</span>,
            carrierStateChip(w.state),
            <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}>{w.last24h.toLocaleString()}</span>,
            <div style={{ display: 'flex', gap: 4 }}>
              <ApiBtn small title={`POST ${w.url}/test`}>⚡ Test</ApiBtn>
              <ApiBtn small variant="ghost" title={`GET ${w.url}/log`}>Log</ApiBtn>
            </div>,
          ])}
        />
      </div>
    </div>
  );
}

// ─── Active Sessions tab ──────────────────────────────────────────────────

function SessionsTab() {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <Tbl
        cols={['Carrier','User','Token','Issued','Expires','IP','State','Action']}
        widths={['130px','170px','170px','140px','140px','100px','100px','120px']}
        rows={SESSIONS.map(s => [
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{s.carrier}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{s.user}</span>,
          <span style={{ fontSize: 10.5, color: 'var(--text)', fontFamily: 'monospace' }}>{s.token}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{s.issued}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{s.expires}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{s.ip}</span>,
          carrierStateChip(s.state),
          <ApiBtn small variant="danger" title="POST /api/v1/carriers/sessions/{id}/revoke">⊘ Revoke</ApiBtn>,
        ])}
      />
    </div>
  );
}

// ─── Audit Log tab ────────────────────────────────────────────────────────

function AuditTab() {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <Tbl
        cols={['Timestamp','Carrier','Actor','Event','Detail']}
        widths={['140px','130px','170px','170px','1fr']}
        rows={AUDIT.map(a => [
          <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{a.ts}</span>,
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>{a.carrier}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{a.actor}</span>,
          <span style={{ fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}>{a.event}</span>,
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{a.detail}</span>,
        ])}
      />
    </div>
  );
}

// ─── Internal helpers ─────────────────────────────────────────────────────

function ApiBtn({ children, variant, small, title }) {
  const variants = {
    gold:    { bg: 'var(--accent)', color: 'var(--accent-text)', border: 'var(--accent)' },
    danger:  { bg: 'var(--badge-red-bg)',   color: 'var(--badge-red-text)',   border: 'var(--badge-red-border)' },
    outline: { bg: 'transparent', color: 'var(--text)', border: 'var(--border)' },
    ghost:   { bg: 'transparent', color: 'var(--text-2)', border: 'transparent' },
    default: { bg: 'var(--bg-subtle)', color: 'var(--text)', border: 'var(--border)' },
  };
  const v = variants[variant] || variants.default;
  return (
    <button disabled title={title || ''} style={{
      background: v.bg, color: v.color, border: `1px solid ${v.border}`,
      borderRadius: 4, padding: small ? '3px 8px' : '5px 10px',
      fontSize: small ? 10 : 11, fontWeight: 600,
      cursor: 'not-allowed', opacity: 0.78,
      display: 'inline-flex', alignItems: 'center', gap: 4,
      whiteSpace: 'nowrap',
    }}>{children}</button>
  );
}

function Tbl({ cols, widths, rows }) {
  const grid = widths.join(' ');
  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: grid,
        padding: '10px 16px', background: 'var(--bg-subtle)',
        borderBottom: '1px solid var(--border)',
        fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)',
        textTransform: 'uppercase', letterSpacing: '0.06em',
        gap: 12,
      }}>
        {cols.map(c => <div key={c}>{c}</div>)}
      </div>
      {rows.map((r, i) => (
        <div key={i} style={{
          display: 'grid', gridTemplateColumns: grid,
          padding: '10px 16px',
          borderBottom: i < rows.length - 1 ? '1px solid var(--border-subtle)' : 'none',
          gap: 12, alignItems: 'center',
        }}>
          {r.map((cell, j) => <div key={j} style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{cell}</div>)}
        </div>
      ))}
    </div>
  );
}

// Shared helpers (consumed by api-status-page.jsx and others)
Object.assign(window, { CarriersPage, CarrierKpi, ApiBtn, Tbl });
