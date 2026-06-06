// ---------------------------------------------------------------------------
// CarriersPage -- Authority-honest Carrier Config + DHL Operations page.
//
// Sprint 39: Complete redesign from mock multi-carrier management console to
// real authority-backed page. All data from live backend APIs:
//
//   GET  /api/v1/carriers-config/       -- carrier config registry (CRUD)
//   GET  /api/v1/carrier/status         -- carrier_api_status + carrier_plt_status
//   GET  /api/v1/master/audit/?entity=carriers_config  -- config audit trail
//
// Tabs:
//   1. Config Registry  -- live rows from carriers-config table
//   2. DHL Operations   -- real gate status + route-backed operational facts
//   3. Integration Gaps -- missing APIs rendered as disabled backend-pending items
//   4. Config Audit     -- real audit trail filtered to carriers_config entity
//
// Authority owners:
//   - Carrier config:  /api/v1/carriers-config/ (master_data.sqlite)
//   - Carrier gates:   /api/v1/carrier/status (settings)
//   - DHL operations:  DHL clearance/tracking/webhook/followup/readiness routes
//   - Config audit:    /api/v1/master/audit/ filtered to carriers_config
//
// NO fake connection states. NO fake account numbers. NO fake quotas.
// NO fake ping times. NO fake session tracking. NO fake webhook registry.
// Planned actions visible but disabled with exact backend-pending reasons.
// ---------------------------------------------------------------------------

const CARRIER_TABS = [
  { id: 'config',      label: 'Config Registry' },
  { id: 'dhl_ops',     label: 'DHL Operations' },
  { id: 'gaps',        label: 'Integration Gaps' },
  { id: 'audit',       label: 'Config Audit' },
];

// -- Known DHL operational routes (backend-verified, not mock) ---------------
const DHL_ROUTES = [
  { category: 'Shipment',    method: 'POST', path: '/api/v1/carrier/{batch_id}/shipment',          gated: true,  gate: 'carrier_api_status', desc: 'Create carrier shipment via CarrierCoordinator' },
  { category: 'Shipment',    method: 'GET',  path: '/api/v1/carrier/{batch_id}/shipment',          gated: false, gate: null,                 desc: 'Get recorded shipment for batch' },
  { category: 'Label',       method: 'POST', path: '/api/v1/carrier/{batch_id}/label-package',     gated: false, gate: null,                 desc: 'Generate outbound customs/shipping doc package' },
  { category: 'Tracking',    method: 'GET',  path: '/api/v1/tracking/{tracking_no}',               gated: true,  gate: 'dhl_tracking_api_status', desc: 'Live tracking status (auto-detects DHL by 10-digit AWB)' },
  { category: 'Tracking',    method: 'POST', path: '/api/v1/tracking/{tracking_no}/refresh',       gated: true,  gate: 'dhl_tracking_api_status', desc: 'Force-refresh tracking status from carrier API' },
  { category: 'Tracking DB', method: 'GET',  path: '/api/v1/tracking/events/{batch_id}',           gated: false, gate: null,                 desc: 'DB-backed tracking events for batch' },
  { category: 'Webhook',     method: 'POST', path: '/api/v1/carrier/webhook/dhl',                  gated: false, gate: null,                 desc: 'DHL Express webhook receiver (HMAC-SHA256 verified)' },
  { category: 'Clearance',   method: 'GET',  path: '/api/v1/dhl/scan-inbox',                       gated: false, gate: null,                 desc: 'Scan Zoho Mail for DHL customs emails' },
  { category: 'Clearance',   method: 'POST', path: '/api/v1/dhl/match-and-handle',                 gated: false, gate: null,                 desc: 'Match AWB to batch + run clearance handler' },
  { category: 'Clearance',   method: 'GET',  path: '/api/v1/dhl/clearance-status/{batch_id}',      gated: false, gate: null,                 desc: 'Clearance status for batch' },
  { category: 'Clearance',   method: 'POST', path: '/api/v1/dhl/generate-description/{batch_id}',  gated: false, gate: null,                 desc: 'Generate Polish customs description' },
  { category: 'Clearance',   method: 'POST', path: '/api/v1/dhl/generate-customs-package/{batch_id}', gated: false, gate: null,              desc: 'Full customs description package' },
  { category: 'Clearance',   method: 'POST', path: '/api/v1/dhl/approve/{batch_id}',               gated: false, gate: null,                 desc: 'Approve customs description' },
  { category: 'Clearance',   method: 'GET',  path: '/api/v1/dhl/sad-ready/{batch_id}',             gated: false, gate: null,                 desc: 'SAD-ready JSON data for filing' },
  { category: 'Documents',   method: 'POST', path: '/api/v1/dhl-documents/{batch_id}/upload',      gated: false, gate: null,                 desc: 'Upload customs documents (multipart)' },
  { category: 'Documents',   method: 'POST', path: '/api/v1/dhl-documents/{batch_id}/received',    gated: false, gate: null,                 desc: 'Register DHL-received customs docs into audit' },
  { category: 'Readiness',   method: 'GET',  path: '/api/v1/dhl/readiness/{batch_id}',             gated: false, gate: null,                 desc: '7-stage pipeline readiness (read-only reconstruction)' },
  { category: 'Follow-up',   method: 'GET',  path: '/api/v1/dhl-followup/{batch_id}/mode',         gated: false, gate: null,                 desc: 'Read current follow-up mode + telemetry' },
  { category: 'Follow-up',   method: 'POST', path: '/api/v1/dhl-followup/{batch_id}/mode',         gated: false, gate: null,                 desc: 'Set follow-up mode (manual/automatic)' },
  { category: 'Follow-up',   method: 'POST', path: '/api/v1/dhl-followup/{batch_id}/send-now',     gated: false, gate: null,                 desc: 'Fire follow-up email now (operator-explicit)' },
  { category: 'Follow-up',   method: 'POST', path: '/api/v1/dhl-followup/{batch_id}/stop',         gated: false, gate: null,                 desc: 'Stop SLA follow-up' },
  { category: 'Follow-up',   method: 'GET',  path: '/api/v1/dhl/followup-automation/status',       gated: false, gate: null,                 desc: 'Automation status card payload' },
  { category: 'Follow-up',   method: 'GET',  path: '/api/v1/dhl/followup-automation/shipments',    gated: false, gate: null,                 desc: 'Drill-down shipment rows' },
  { category: 'Shadow',      method: 'GET',  path: '/api/v1/carrier/shadow/log',                   gated: false, gate: null,                 desc: 'Shadow mode log entries' },
  { category: 'Status',      method: 'GET',  path: '/api/v1/carrier/status',                       gated: false, gate: null,                 desc: 'Global carrier_api_status + carrier_plt_status' },
];

// -- Integration gaps (from Sprint 39 audit) ---------------------------------
const INTEGRATION_GAPS = [
  { id: 'GAP-C01', api: 'GET /api/v1/carriers',              label: 'Unified carrier list with connection state', severity: 'critical', note: 'carriers-config provides config metadata; connection state tracking does not exist' },
  { id: 'GAP-C02', api: 'POST /api/v1/carriers/{id}/test',   label: 'Test connection / health-check',              severity: 'medium',   note: 'No per-carrier ping/health endpoint' },
  { id: 'GAP-C03', api: 'POST /api/v1/carriers/{id}/credentials', label: 'Credential rotation / editing',          severity: 'high',     note: 'Credentials in .env only; no UI management API' },
  { id: 'GAP-C04', api: 'POST /api/v1/carriers/{id}/disconnect',  label: 'Disconnect / revoke carrier session',    severity: 'high',     note: 'No connection-state machine exists' },
  { id: 'GAP-C05', api: 'POST /api/v1/carriers/{id}/oauth/start', label: 'OAuth flow initiation',                  severity: 'high',     note: 'No OAuth infrastructure (FedEx, UPS)' },
  { id: 'GAP-C06', api: 'GET /api/v1/carriers/{id}/webhooks',     label: 'Webhook registry (list/manage)',         severity: 'medium',   note: 'DHL webhook receiver exists; no registry endpoint to list/manage' },
  { id: 'GAP-C07', api: 'GET /api/v1/carriers/{id}/sessions',     label: 'Session / token tracking',              severity: 'medium',   note: 'No session tracking backend' },
  { id: 'GAP-C08', api: 'POST /api/v1/carriers/{id}/env',         label: 'Per-carrier env management (prod/sandbox)', severity: 'high',  note: 'carrier_api_status is global, not per-carrier' },
  { id: 'GAP-C09', api: 'GET /api/v1/carriers/{id}/quota',        label: 'Quota / rate-limit tracking',            severity: 'low',      note: 'No quota instrumentation' },
  { id: 'GAP-C10', api: 'POST /api/v1/carriers/onboard',          label: 'Carrier onboarding workflow',            severity: 'high',     note: 'OAuth callback, key entry, integration setup does not exist' },
];

// -- Severity badge rendering ------------------------------------------------
const severityChip = (sev) => {
  const m = {
    critical: { label: 'Critical', bg: 'var(--badge-red-bg)',    text: 'var(--badge-red-text)',    border: 'var(--badge-red-border)' },
    high:     { label: 'High',     bg: 'var(--badge-yellow-bg)', text: 'var(--badge-yellow-text)', border: 'var(--badge-yellow-border)' },
    medium:   { label: 'Medium',   bg: 'var(--badge-blue-bg)',   text: 'var(--badge-blue-text)',   border: 'var(--badge-blue-border)' },
    low:      { label: 'Low',      bg: 'var(--badge-neutral-bg)',text: 'var(--badge-neutral-text)',border: 'var(--badge-neutral-border)' },
  };
  const v = m[sev] || m.medium;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: v.bg, color: v.text, border: '1px solid ' + v.border,
      borderRadius: 4, padding: '2px 7px', fontSize: 10, fontWeight: 600,
      letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{v.label}</span>
  );
};

// State chip (reused from carrier status)
const stateChip = (s) => {
  const m = {
    pending:  { label: 'Pending', bg: 'var(--badge-yellow-bg)', text: 'var(--badge-yellow-text)', border: 'var(--badge-yellow-border)' },
    shadow:   { label: 'Shadow',  bg: 'var(--badge-blue-bg)',   text: 'var(--badge-blue-text)',   border: 'var(--badge-blue-border)' },
    live:     { label: 'Live',    bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    active:   { label: 'Active',  bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    inactive: { label: 'Inactive',bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    exists:   { label: 'Exists',  bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    missing:  { label: 'Missing', bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    gated:    { label: 'Gated',   bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
    error:    { label: 'Error',   bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  };
  const v = m[s] || { label: s || '?', bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: v.bg, color: v.text, border: '1px solid ' + v.border,
      borderRadius: 4, padding: '2px 7px', fontSize: 10, fontWeight: 600,
      letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{v.label}</span>
  );
};

// ============================================================================
// CarriersPage — main component
// ============================================================================

function CarriersPage() {
  const [tab, setTab] = React.useState('config');
  const [carriers, setCarriers] = React.useState(null);
  const [carrierStatus, setCarrierStatus] = React.useState(null);
  const [loadErr, setLoadErr] = React.useState(null);

  // Load carrier config + gate status on mount
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cfgRes, statusRes] = await Promise.all([
          PzApi.listCarriersConfig(),
          PzApi.getCarrierStatus(),
        ]);
        if (cancelled) return;
        setCarriers(cfgRes.carriers || []);
        setCarrierStatus(statusRes);
      } catch (e) {
        if (!cancelled) setLoadErr(e.error || e.message || 'Failed to load carrier data');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // KPI strip — computed from live data
  const activeCount = carriers ? carriers.filter(c => c.active !== false).length : 0;
  const totalCount  = carriers ? carriers.length : 0;
  const apiStatus   = carrierStatus ? carrierStatus.carrier_api_status : '...';
  const pltStatus   = carrierStatus ? carrierStatus.carrier_plt_status : '...';

  return (
    <div data-testid="carriers-page" style={{ flex: 1, overflowY: 'auto', padding: '20px 32px 40px' }}>
      {/* KPI strip — all from real backend data */}
      <div data-testid="carriers-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <CarrierKpi label="Registered Configs" value={carriers ? String(totalCount) : '...'} accent="var(--text)" />
        <CarrierKpi label="Active Configs"     value={carriers ? String(activeCount) + ' of ' + totalCount : '...'} accent="var(--badge-green-text)" />
        <CarrierKpi label="Carrier API Gate"   value={apiStatus} accent={apiStatus === 'live' ? 'var(--badge-green-text)' : apiStatus === 'shadow' ? 'var(--badge-blue-text)' : 'var(--badge-yellow-text)'} />
        <CarrierKpi label="PLT Gate"           value={pltStatus} accent={pltStatus === 'live' ? 'var(--badge-green-text)' : pltStatus === 'shadow' ? 'var(--badge-blue-text)' : 'var(--badge-yellow-text)'} />
      </div>

      {/* Error state */}
      {loadErr && (
        <div data-testid="carriers-load-error" style={{
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', padding: '12px 16px', borderRadius: 6,
          fontSize: 12, marginBottom: 16,
        }}>Failed to load carrier data: {loadErr}</div>
      )}

      {/* Tab strip */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {CARRIER_TABS.map(t => (
          <button key={t.id} data-testid={'carrier-tab-' + t.id} onClick={() => setTab(t.id)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '8px 14px 10px', fontSize: 12,
            fontWeight: tab === t.id ? 700 : 500,
            color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
            borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1, letterSpacing: '0.01em',
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'config'  && <ConfigRegistryTab carriers={carriers} />}
      {tab === 'dhl_ops' && <DhlOperationsTab carrierStatus={carrierStatus} />}
      {tab === 'gaps'    && <IntegrationGapsTab />}
      {tab === 'audit'   && <ConfigAuditTab />}
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


// ============================================================================
// Tab 1: Config Registry — live rows from GET /api/v1/carriers-config/
// ============================================================================

function ConfigRegistryTab({ carriers }) {
  if (!carriers) {
    return <div data-testid="config-loading" style={{ padding: 20, color: 'var(--text-2)', fontSize: 12 }}>Loading carrier configs...</div>;
  }
  if (carriers.length === 0) {
    return (
      <div data-testid="config-empty" style={{ padding: 20, color: 'var(--text-2)', fontSize: 12 }}>
        No carrier configurations found. Add a carrier config via
        <code style={{ marginLeft: 4 }}>PUT /api/v1/carriers-config/{'<carrier_code>'}</code>
      </div>
    );
  }

  return (
    <div data-testid="config-registry-tab" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Info banner */}
      <div style={{
        background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
      }}>
        <b style={{ color: 'var(--text)' }}>Carrier Config Registry</b> &mdash; local configuration metadata from
        <code style={{ marginLeft: 4 }}>/api/v1/carriers-config/</code>.
        This table stores parser routing, inbox references, and API type.
        It does <b>not</b> store credentials (those are in <code>.env</code>) or connection state.
        <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
          <ApiBtn title="Backend pending: POST /api/v1/carriers/{id}/test — no health-check endpoint exists">Test Connection</ApiBtn>
          <ApiBtn title="Backend pending: POST /api/v1/carriers/{id}/credentials — credentials managed via .env">Edit Credentials</ApiBtn>
          <ApiBtn title="Backend pending: POST /api/v1/carriers/{id}/disconnect — no connection-state machine exists">Disconnect</ApiBtn>
          <ApiBtn title="Backend pending: POST /api/v1/carriers/{id}/oauth/start — no OAuth infrastructure">Complete OAuth</ApiBtn>
          <ApiBtn title="Backend pending: credential rotation API does not exist">Rotate Token</ApiBtn>
          <ApiBtn title="Backend pending: POST /api/v1/carriers/onboard — carrier onboarding workflow does not exist">Add Carrier Integration</ApiBtn>
        </div>
      </div>

      {/* Config table */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
        <Tbl
          cols={['Code', 'Name', 'Parser', 'Inbox Email', 'API Type', 'Services', 'Active']}
          widths={['100px', '160px', '130px', '1fr', '100px', '1fr', '80px']}
          rows={carriers.map(c => [
            <span data-testid={'config-code-' + c.carrier_code} style={{ fontSize: 12, fontWeight: 700, fontFamily: 'monospace', color: 'var(--text)' }}>{c.carrier_code}</span>,
            <span style={{ fontSize: 12, color: 'var(--text)' }}>{c.name || '—'}</span>,
            <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.parser_type || '—'}</span>,
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{c.inbox_email || '—'}</span>,
            <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.api_type || '—'}</span>,
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{c.supported_services || '—'}</span>,
            c.active !== false ? stateChip('active') : stateChip('inactive'),
          ])}
        />
      </div>

      {/* Carrier config CRUD note */}
      <div style={{
        background: 'var(--bg-subtle)', border: '1px solid var(--border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
      }}>
        <b style={{ color: 'var(--text)' }}>CRUD authority:</b> Full CRUD via
        <code style={{ margin: '0 4px' }}>PUT /api/v1/carriers-config/{'{carrier_code}'}</code> (upsert),
        <code style={{ margin: '0 4px' }}>DELETE /{'{carrier_code}'}</code> (soft/hard delete),
        <code style={{ margin: '0 4px' }}>POST /{'{carrier_code}'}/restore</code>.
        Write operations are gated on <code>master_editor</code> role.
        UI write buttons are disabled pending Sprint 40+ (carrier config write forms).
      </div>
    </div>
  );
}


// ============================================================================
// Tab 2: DHL Operations — real gate status + route-backed operational facts
// ============================================================================

function DhlOperationsTab({ carrierStatus }) {
  const apiGate = carrierStatus ? carrierStatus.carrier_api_status : null;
  const pltGate = carrierStatus ? carrierStatus.carrier_plt_status : null;

  return (
    <div data-testid="dhl-ops-tab" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Gate status card */}
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 8, padding: 16, boxShadow: '0 1px 3px var(--shadow)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 10 }}>
          Carrier Gate Status
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 12 }}>
          Source: <code>GET /api/v1/carrier/status</code> &mdash; live from settings
        </div>
        <div data-testid="gate-status-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <GateCard
            label="Carrier API Gate"
            field="carrier_api_status"
            value={apiGate}
            desc="Controls POST /api/v1/carrier/{batch_id}/shipment. Returns 503 when 'pending'."
          />
          <GateCard
            label="PLT Gate"
            field="carrier_plt_status"
            value={pltGate}
            desc="Paperless Trade gate. Independent of carrier_api_status."
          />
          <GateCard
            label="DHL Tracking API"
            field="dhl_tracking_api_status"
            value={null}
            desc="Controls GET /api/v1/tracking/{tracking_no}. Not exposed by /carrier/status endpoint."
            note="Route exists; status not exposed via REST. Check .env DHL_TRACKING_API_STATUS."
          />
        </div>
      </div>

      {/* DHL capabilities summary */}
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 8, padding: 16, boxShadow: '0 1px 3px var(--shadow)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 4 }}>
          DHL Express Operational Routes
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 12 }}>
          {DHL_ROUTES.length} backend routes across {[...new Set(DHL_ROUTES.map(r => r.category))].length} categories.
          All routes verified in backend source code &mdash; no live health endpoint exists per-route.
        </div>
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          <Tbl
            cols={['Category', 'Method', 'Route', 'Gate', 'Description']}
            widths={['100px', '60px', '1fr', '100px', '1fr']}
            rows={DHL_ROUTES.map(r => [
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>{r.category}</span>,
              <span style={{
                display: 'inline-block', padding: '1px 7px', borderRadius: 3,
                fontSize: 9.5, fontWeight: 700, fontFamily: 'monospace',
                background: r.method === 'GET' ? 'var(--badge-blue-bg)' : 'var(--accent-subtle)',
                color: r.method === 'GET' ? 'var(--badge-blue-text)' : 'var(--accent)',
                border: r.method === 'GET' ? '1px solid var(--badge-blue-border)' : '1px solid var(--accent-border)',
              }}>{r.method}</span>,
              <span style={{ fontFamily: 'monospace', fontSize: 10.5, color: 'var(--text)' }}>{r.path}</span>,
              r.gated ? stateChip('gated') : stateChip('exists'),
              <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{r.desc}</span>,
            ])}
          />
        </div>
      </div>

      {/* Other carriers note */}
      <div style={{
        background: 'var(--bg-subtle)', border: '1px solid var(--border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
      }}>
        <b style={{ color: 'var(--text)' }}>FedEx / UPS / GLS / InPost / DPD:</b> Config-only (registered in carriers-config table).
        No live integrations, no dedicated routes, no webhook receivers, no tracking auto-detection (except FedEx partial via digit-length heuristic).
        Backend authority for these carriers is limited to the carriers-config CRUD endpoints.
      </div>
    </div>
  );
}

function GateCard({ label, field, value, desc, note }) {
  return (
    <div data-testid={'gate-' + field} style={{
      background: 'var(--bg-subtle)', border: '1px solid var(--border)',
      borderRadius: 6, padding: 12,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>{label}</div>
      <div style={{ marginBottom: 6 }}>
        {value ? stateChip(value) : (
          <span style={{ fontSize: 10, color: 'var(--text-3)', fontStyle: 'italic' }}>not exposed</span>
        )}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', lineHeight: 1.4 }}>{desc}</div>
      {note && (
        <div style={{ fontSize: 10, color: 'var(--badge-yellow-text)', marginTop: 4, fontStyle: 'italic' }}>{note}</div>
      )}
    </div>
  );
}


// ============================================================================
// Tab 3: Integration Gaps — missing APIs with disabled backend-pending buttons
// ============================================================================

function IntegrationGapsTab() {
  return (
    <div data-testid="gaps-tab" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Info banner */}
      <div style={{
        background: 'var(--badge-yellow-bg)', border: '1px solid var(--badge-yellow-border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--badge-yellow-text)',
      }}>
        <b>Integration Gaps</b> &mdash; APIs required for full carrier management that do not yet exist in the backend.
        Each gap was identified in the Sprint 39 preflight audit. Buttons are visible but disabled with exact backend-pending reasons.
      </div>

      {/* Gaps table */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
        <Tbl
          cols={['Gap ID', 'Missing API', 'Description', 'Severity', 'Action']}
          widths={['80px', '1fr', '1fr', '80px', '160px']}
          rows={INTEGRATION_GAPS.map(g => [
            <span data-testid={'gap-' + g.id} style={{ fontSize: 11, fontWeight: 700, fontFamily: 'monospace', color: 'var(--text)' }}>{g.id}</span>,
            <span style={{ fontSize: 10.5, fontFamily: 'monospace', color: 'var(--text)' }}>{g.api}</span>,
            <div>
              <div style={{ fontSize: 11, color: 'var(--text)', fontWeight: 600 }}>{g.label}</div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{g.note}</div>
            </div>,
            severityChip(g.severity),
            <ApiBtn title={'Backend pending: ' + g.api + ' — ' + g.note}>{g.label.split(' ')[0]}</ApiBtn>,
          ])}
        />
      </div>

      {/* Gap summary */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12,
      }}>
        <CarrierKpi label="Critical Gaps" value={String(INTEGRATION_GAPS.filter(g => g.severity === 'critical').length)} accent="var(--badge-red-text)" />
        <CarrierKpi label="High Gaps"     value={String(INTEGRATION_GAPS.filter(g => g.severity === 'high').length)}     accent="var(--badge-yellow-text)" />
        <CarrierKpi label="Medium Gaps"    value={String(INTEGRATION_GAPS.filter(g => g.severity === 'medium').length)}   accent="var(--badge-blue-text)" />
        <CarrierKpi label="Low Gaps"       value={String(INTEGRATION_GAPS.filter(g => g.severity === 'low').length)}      accent="var(--text-3)" />
      </div>
    </div>
  );
}


// ============================================================================
// Tab 4: Config Audit — real audit trail from /api/v1/master/audit/
// ============================================================================

function ConfigAuditTab() {
  const [rows, setRows] = React.useState(null);
  const [err, setErr]   = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await PzApi.listMasterAudit({ entity: 'carriers_config', limit: 50 });
        if (!cancelled) setRows(data.rows || []);
      } catch (e) {
        if (!cancelled) setErr(e.error || e.message || 'Audit fetch failed');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div data-testid="audit-tab" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Info banner */}
      <div style={{
        background: 'var(--accent-subtle)', border: '1px solid var(--accent-border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
      }}>
        <b style={{ color: 'var(--text)' }}>Config Audit Trail</b> &mdash; real audit rows from
        <code style={{ marginLeft: 4 }}>GET /api/v1/master/audit/?entity=carriers_config</code>.
        Every carriers-config create, update, delete, and restore operation is logged.
      </div>

      {/* Error state */}
      {err && (
        <div data-testid="audit-error" style={{
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', padding: '12px 16px', borderRadius: 6, fontSize: 12,
        }}>Audit load failed: {err}</div>
      )}

      {/* Loading */}
      {!rows && !err && (
        <div style={{ padding: 20, color: 'var(--text-2)', fontSize: 12 }}>Loading audit trail...</div>
      )}

      {/* Empty */}
      {rows && rows.length === 0 && (
        <div data-testid="audit-empty" style={{
          padding: 20, color: 'var(--text-2)', fontSize: 12,
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
        }}>
          No carriers_config audit entries found. Entries appear after carrier config create/update/delete operations.
        </div>
      )}

      {/* Audit rows */}
      {rows && rows.length > 0 && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <Tbl
            cols={['Timestamp', 'Operation', 'Carrier Code', 'Actor', 'Detail']}
            widths={['160px', '100px', '130px', '170px', '1fr']}
            rows={rows.map(a => [
              <span style={{ fontSize: 11, color: 'var(--text-2)', fontFamily: 'monospace' }}>{a.created_at || a.ts || '—'}</span>,
              <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'monospace', color: 'var(--text)' }}>{a.op || a.operation || '—'}</span>,
              <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'monospace', color: 'var(--text)' }}>{a.pk || a.primary_key || '—'}</span>,
              <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{a.actor || '—'}</span>,
              <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{
                a.diff ? (typeof a.diff === 'string' ? a.diff : JSON.stringify(a.diff)) :
                a.reason || '—'
              }</span>,
            ])}
          />
        </div>
      )}

      {/* Webhook + session management disabled note */}
      <div style={{
        background: 'var(--bg-subtle)', border: '1px solid var(--border)',
        padding: 12, borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
      }}>
        <b style={{ color: 'var(--text)' }}>Planned surfaces (backend pending):</b>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <ApiBtn title="Backend pending: GET /api/v1/carriers/{id}/webhooks — webhook registry endpoint does not exist">Webhook Registry</ApiBtn>
          <ApiBtn title="Backend pending: GET /api/v1/carriers/{id}/sessions — session tracking backend does not exist">Session Management</ApiBtn>
          <ApiBtn title="Backend pending: credential rotation audit — no credential lifecycle tracking">Credential Audit</ApiBtn>
        </div>
      </div>
    </div>
  );
}


// ============================================================================
// Shared helpers
// ============================================================================

function ApiBtn({ children, variant, small, title }) {
  const variants = {
    gold:    { bg: 'var(--accent)',         color: 'var(--accent-text)',         border: 'var(--accent)' },
    danger:  { bg: 'var(--badge-red-bg)',   color: 'var(--badge-red-text)',      border: 'var(--badge-red-border)' },
    outline: { bg: 'transparent',          color: 'var(--text)',                border: 'var(--border)' },
    ghost:   { bg: 'transparent',          color: 'var(--text-2)',              border: 'transparent' },
    default: { bg: 'var(--bg-subtle)',     color: 'var(--text)',                border: 'var(--border)' },
  };
  const v = variants[variant] || variants.default;
  return (
    <button disabled title={title || ''} data-testid="carrier-btn-disabled" style={{
      background: v.bg, color: v.color, border: '1px solid ' + v.border,
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
