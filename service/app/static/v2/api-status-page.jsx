// ─────────────────────────────────────────────────────────────────────────────
// API Status — Integration Health Board (Sprint 41: authority-honest)
//
// Replaces 100% MOCK multi-carrier API gateway dashboard with live
// subsystem health derived from 12 real backend endpoints.
//
// Authority sources (all read-only, zero new backend routes):
//   GET /api/v1/debug/health-full            — 12-dim Guardian diagnostic
//   GET /api/v1/debug/pending                — bot pipeline + recent errors
//   GET /api/v1/debug/storage/health         — storage health snapshot
//   GET /api/v1/pz/health                    — PZ engine status
//   GET /api/v1/dhl/auto-scan-status         — DHL inbox scanner
//   GET /api/v1/dhl/daily-summary            — DHL ops report
//   GET /api/v1/dhl/followup-automation/status — follow-up SLA card
//   GET /api/v1/carrier/status               — carrier gate flags
//   GET /api/v1/carriers-config/             — carrier config registry
//   GET /api/v1/wfirma/capabilities          — wFirma capability map
//   GET /api/v1/admin/email-queue            — email queue (admin)
//   GET /api/v1/intelligence/status          — intelligence engine
//
// Sprint 41: DELETE all 4 fake arrays (API_INTEGRATIONS, API_ENDPOINT_REGISTRY,
// RECENT_ERRORS, INCIDENTS). DELETE fake carriers (FedEx/UPS/GLS/InPost/DPD).
// DELETE fake latency/call-count/incident metrics.
// ─────────────────────────────────────────────────────────────────────────────

// ── Shared components (exported by carriers-page.jsx, loaded first) ─────────
const CarrierKpi = window.CarrierKpi;

// ── Subsystem definitions ───────────────────────────────────────────────────
// Each entry maps to one real backend endpoint.
const SUBSYSTEMS = [
  { id: 'pz-engine',     name: 'PZ Engine',           group: 'Core',       fetch: () => PzApi.getPzHealth() },
  { id: 'health-full',   name: 'System Health',       group: 'Core',       fetch: () => PzApi.getHealthFull() },
  { id: 'storage',       name: 'Storage',             group: 'Core',       fetch: () => PzApi.getStorageHealth() },
  { id: 'dhl-scanner',   name: 'DHL Inbox Scanner',   group: 'DHL',        fetch: () => PzApi.getDhlAutoScanStatus() },
  { id: 'dhl-ops',       name: 'DHL Operations',      group: 'DHL',        fetch: () => PzApi.getDhlDailySummary() },
  { id: 'dhl-followup',  name: 'DHL Follow-up SLA',   group: 'DHL',        fetch: () => PzApi.getDhlFollowupStatus() },
  { id: 'carrier-gate',  name: 'Carrier Gate',        group: 'Carrier',    fetch: () => PzApi.getCarrierStatus() },
  { id: 'carrier-config',name: 'Carrier Config',      group: 'Carrier',    fetch: () => PzApi.listCarriersConfig() },
  { id: 'wfirma',        name: 'wFirma',              group: 'Accounting', fetch: () => PzApi.getWfirmaCapabilities() },
  { id: 'email-queue',   name: 'Email Queue',         group: 'Comms',      fetch: () => PzApi.getEmailQueue() },
  { id: 'intelligence',  name: 'Intelligence Engine', group: 'AI',         fetch: () => PzApi.getIntelligenceStatus() },
  { id: 'bot-pipeline',  name: 'Bot Pipeline',        group: 'Comms',      fetch: () => PzApi.getDebugPending() },
];

// ── Status derivation per subsystem ─────────────────────────────────────────
// Each function receives the raw API response and returns { state, detail }.
// state: 'healthy' | 'degraded' | 'error' | 'offline' | 'unknown'
function _deriveStatus(id, data) {
  if (!data) return { state: 'unknown', detail: 'No data' };
  try {
    switch (id) {
      case 'pz-engine': {
        const s = (data.status || '').toLowerCase();
        return {
          state: s === 'ok' ? 'healthy' : s === 'degraded' ? 'degraded' : 'error',
          detail: `Engine: ${data.engine || '?'} · Env: ${data.environment || '?'}`,
        };
      }
      case 'health-full': {
        const steps = Object.entries(data).filter(([k]) => /^\d+_/.test(k));
        const ok = steps.filter(([,v]) => v && v.status === 'ok').length;
        const warn = steps.filter(([,v]) => v && v.status === 'warn').length;
        const fail = steps.filter(([,v]) => v && v.status === 'fail').length;
        const state = fail > 0 ? 'error' : warn > 0 ? 'degraded' : 'healthy';
        return { state, detail: `${ok} ok · ${warn} warn · ${fail} fail of ${steps.length} checks` };
      }
      case 'storage': {
        const ok = data.ok !== false;
        return {
          state: ok ? 'healthy' : 'degraded',
          detail: ok ? 'Storage healthy' : (data.warnings || []).join('; ') || 'Issues detected',
        };
      }
      case 'dhl-scanner': {
        const s = (data.status || 'never_run').toLowerCase();
        if (s === 'success') return { state: 'healthy', detail: `Checked ${data.batches_checked || 0} batches · ${data.received_set || 0} matched` };
        if (s === 'running') return { state: 'healthy', detail: 'Scan in progress…' };
        if (s === 'never_run') return { state: 'offline', detail: 'Scanner has never run' };
        return { state: 'error', detail: data.last_error || `Status: ${s}` };
      }
      case 'dhl-ops': {
        const sm = data.summary || {};
        return {
          state: (sm.scanner_failures_24h || 0) > 2 ? 'degraded' : 'healthy',
          detail: `${sm.active_shipments || 0} active · ${sm.waiting_for_dhl || 0} waiting · ${sm.replies_sent_today || 0} replies today`,
        };
      }
      case 'dhl-followup': {
        const raw = data.traffic_light || data.summary_status || 'unknown';
        const s = typeof raw === 'string' ? raw.toLowerCase() : 'unknown';
        const state = s === 'green' ? 'healthy' : s === 'yellow' || s === 'amber' ? 'degraded' : s === 'red' ? 'error' : 'healthy';
        const active = data.active_count ?? data.active ?? '?';
        const eligible = data.eligible_count ?? data.eligible ?? '?';
        return { state, detail: `Active: ${active} · Eligible: ${eligible}` };
      }
      case 'carrier-gate': {
        const api = data.carrier_api_status || 'unknown';
        const plt = data.carrier_plt_status || 'unknown';
        const both = (api + ' ' + plt).toLowerCase();
        const state = both.includes('error') || both.includes('fail') ? 'error'
          : both.includes('disabled') || both.includes('off') ? 'offline' : 'healthy';
        return { state, detail: `API: ${api} · PLT: ${plt}` };
      }
      case 'carrier-config': {
        const count = data.count ?? (data.carriers || []).length;
        const active = (data.carriers || []).filter(c => c.is_active !== false && !c.deleted_at).length;
        return { state: count > 0 ? 'healthy' : 'offline', detail: `${active} active of ${count} configured` };
      }
      case 'wfirma': {
        const caps = data;
        const enabled = Object.values(caps).filter(v => v === true).length;
        const total = Object.keys(caps).length;
        return {
          state: enabled > 0 ? 'healthy' : 'offline',
          detail: `${enabled} of ${total} capabilities enabled`,
        };
      }
      case 'email-queue': {
        const pc = data.pending_count ?? 0;
        return {
          state: pc > 10 ? 'degraded' : pc > 0 ? 'healthy' : 'healthy',
          detail: `${pc} pending · ${(data.emails || []).length} total`,
        };
      }
      case 'intelligence': {
        const docs = data.research_docs || {};
        const cfg = data.config || {};
        return {
          state: cfg.exists ? 'healthy' : 'degraded',
          detail: `Config: ${cfg.exists ? 'loaded' : 'missing'} · Docs: ${docs.found || 0}/${docs.total || 0}`,
        };
      }
      case 'bot-pipeline': {
        const c = data.counts || {};
        const errs = c.errors || 0;
        return {
          state: errs > 5 ? 'degraded' : 'healthy',
          detail: `Sessions: ${c.active_sessions || 0} · Events: ${c.bot_events_seen || 0} · Errors: ${errs}`,
        };
      }
      default:
        return { state: 'unknown', detail: JSON.stringify(data).slice(0, 80) };
    }
  } catch (e) {
    return { state: 'error', detail: String(e) };
  }
}

// ── State chip (reused from carriers-page.jsx pattern) ──────────────────────
const STATE_STYLES = {
  healthy:  { label: 'Healthy',  bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  degraded: { label: 'Degraded', bg: 'var(--badge-yellow-bg)',  text: 'var(--badge-yellow-text)',  border: 'var(--badge-yellow-border)' },
  error:    { label: 'Error',    bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  offline:  { label: 'Offline',  bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  unknown:  { label: '…',       bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  loading:  { label: 'Loading',  bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  fetch_error:{ label: 'Fetch Error', bg: 'var(--badge-red-bg)', text: 'var(--badge-red-text)',   border: 'var(--badge-red-border)' },
};
function StateChip({ state }) {
  const v = STATE_STYLES[state] || STATE_STYLES.unknown;
  return (
    <span data-testid={`state-chip-${state}`} style={{
      display: 'inline-flex', alignItems: 'center',
      background: v.bg, color: v.text, border: `1px solid ${v.border}`,
      borderRadius: 4, padding: '2px 7px', fontSize: 10, fontWeight: 600,
      letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{v.label}</span>
  );
}

// ── Subsystem card ──────────────────────────────────────────────────────────
function SubsystemCard({ sub, result }) {
  const { state, detail } = result.status === 'loading'
    ? { state: 'loading', detail: 'Fetching…' }
    : result.status === 'error'
      ? { state: 'fetch_error', detail: result.error || 'Failed to load' }
      : _deriveStatus(sub.id, result.data);

  return (
    <div data-testid={`subsystem-card-${sub.id}`} style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, padding: 14, boxShadow: '0 1px 3px var(--shadow)',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{sub.name}</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>{sub.group}</div>
        </div>
        <StateChip state={state} />
      </div>
      <div style={{
        fontSize: 11, color: 'var(--text-2)', lineHeight: 1.5,
        fontFamily: state === 'loading' ? 'inherit' : 'monospace',
        opacity: state === 'loading' ? 0.6 : 1,
      }}>{detail}</div>
    </div>
  );
}

// ── Health-full detail expansion ────────────────────────────────────────────
function HealthFullDetail({ data }) {
  if (!data) return null;
  const steps = Object.entries(data)
    .filter(([k]) => /^\d+_/.test(k))
    .sort(([a], [b]) => a.localeCompare(b));
  if (!steps.length) return null;

  return (
    <div data-testid="health-full-detail" style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, overflow: 'hidden',
    }}>
      <div style={{
        padding: '10px 16px', fontSize: 11, fontWeight: 700,
        color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em',
        borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)',
      }}>Guardian Diagnostic — 12 Dimensions</div>
      <div style={{ padding: 4 }}>
        {steps.map(([key, val]) => {
          const label = key.replace(/^\d+_/, '').replace(/_/g, ' ');
          const st = (val && val.status) || 'unknown';
          const det = (val && val.detail) || '';
          const color = st === 'ok' ? 'var(--badge-green-text)' : st === 'warn' ? 'var(--badge-yellow-text)' : 'var(--badge-red-text)';
          return (
            <div key={key} style={{
              display: 'grid', gridTemplateColumns: '28px 160px 1fr',
              alignItems: 'center', padding: '5px 12px', fontSize: 11,
              borderBottom: '1px solid var(--border-subtle)',
            }}>
              <span style={{ color, fontWeight: 700, fontSize: 10 }}>{st === 'ok' ? '✓' : st === 'warn' ? '⚠' : '✗'}</span>
              <span style={{ color: 'var(--text)', fontWeight: 600, textTransform: 'capitalize' }}>{label}</span>
              <span style={{ color: 'var(--text-2)', fontFamily: 'monospace', fontSize: 10.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{det}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Recent errors table ─────────────────────────────────────────────────────
function RecentErrorsPanel({ errors }) {
  if (!errors || !errors.length) {
    return (
      <div data-testid="recent-errors-empty" style={{
        padding: 32, textAlign: 'center', color: 'var(--text-3)', fontSize: 12,
      }}>No recent errors in the bot pipeline ring buffer.</div>
    );
  }
  return (
    <div data-testid="recent-errors-panel" style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, overflow: 'hidden',
    }}>
      <div style={{
        padding: '10px 16px', fontSize: 11, fontWeight: 700,
        color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em',
        borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)',
      }}>Recent Errors (bot pipeline, last 20)</div>
      <div style={{ maxHeight: 320, overflowY: 'auto' }}>
        {errors.map((err, i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '150px 1fr',
            padding: '6px 16px', fontSize: 11, borderBottom: '1px solid var(--border-subtle)',
          }}>
            <span style={{ color: 'var(--text-3)', fontFamily: 'monospace', fontSize: 10.5 }}>
              {err.ts || err.timestamp || '—'}
            </span>
            <span style={{ color: 'var(--badge-red-text)', fontFamily: 'monospace', fontSize: 10.5 }}>
              {err.msg || err.error_message || err.event || JSON.stringify(err).slice(0, 120)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Bot activity panel ──────────────────────────────────────────────────────
function BotActivityPanel({ data }) {
  if (!data) return null;
  const events = data.last_bot_events || [];
  const stages = data.last_stage_events || [];
  const posts = data.last_pz_posts || [];
  const counts = data.counts || {};

  return (
    <div data-testid="bot-activity-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <_MiniKpi label="Active Sessions" value={counts.active_sessions || 0} />
        <_MiniKpi label="Pending Chats" value={counts.pending_chats || 0} />
        <_MiniKpi label="Events Seen" value={counts.bot_events_seen || 0} />
        <_MiniKpi label="PZ Posts" value={counts.pz_posts || 0} />
      </div>
      {stages.length > 0 && (
        <details style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8 }}>
          <summary style={{ padding: '8px 16px', fontSize: 11, fontWeight: 600, color: 'var(--text-2)', cursor: 'pointer' }}>
            Last {stages.length} pipeline stage events
          </summary>
          <div style={{ maxHeight: 200, overflowY: 'auto', padding: '0 4px 4px' }}>
            {stages.slice().reverse().map((ev, i) => (
              <div key={i} style={{
                padding: '4px 12px', fontSize: 10.5, fontFamily: 'monospace',
                color: 'var(--text-2)', borderBottom: '1px solid var(--border-subtle)',
              }}>
                <span style={{ color: 'var(--text-3)' }}>{ev.ts || ev.timestamp || ''}</span>{' '}
                {ev.event || ev.stage || JSON.stringify(ev).slice(0, 80)}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function _MiniKpi({ label, value }) {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6,
      padding: '8px 12px', textAlign: 'center',
    }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{value}</div>
      <div style={{ fontSize: 9.5, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 2 }}>{label}</div>
    </div>
  );
}

// ── DHL Operations summary ──────────────────────────────────────────────────
function DhlOpsSummary({ data }) {
  if (!data) return null;
  const sm = data.summary || {};
  const la = data.lane_a_health || {};

  return (
    <div data-testid="dhl-ops-summary" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <_MiniKpi label="Active Shipments" value={sm.active_shipments || 0} />
        <_MiniKpi label="Waiting for DHL" value={sm.waiting_for_dhl || 0} />
        <_MiniKpi label="Replies Today" value={sm.replies_sent_today || 0} />
        <_MiniKpi label="Scanner Runs 24h" value={sm.scanner_runs_24h || 0} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        <_MiniKpi label="Scanner Failures" value={sm.scanner_failures_24h || 0} />
        <_MiniKpi label="Lane B Eligible" value={sm.lane_b_eligible || 0} />
        <_MiniKpi label="Excluded" value={sm.excluded_batches || 0} />
      </div>
      {la.last_run_at && (
        <div style={{
          padding: '8px 14px', background: 'var(--card)', border: '1px solid var(--border)',
          borderRadius: 6, fontSize: 11, color: 'var(--text-2)',
        }}>
          <strong style={{ color: 'var(--text)' }}>Lane A last run:</strong>{' '}
          {la.last_run_status} at {la.last_run_at}{' '}
          {la.last_run_duration_s != null && `(${la.last_run_duration_s}s)`}
          {la.avg_batches_checked != null && ` · avg ${la.avg_batches_checked} batches/run`}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main page component
// ═══════════════════════════════════════════════════════════════════════════════
function ApiStatusPage() {
  const [results, setResults] = React.useState(() => {
    const init = {};
    SUBSYSTEMS.forEach(s => { init[s.id] = { status: 'loading', data: null, error: null }; });
    return init;
  });
  const [tab, setTab] = React.useState('overview');

  // Fetch all subsystems independently — each fires its own .then/.catch
  React.useEffect(() => {
    SUBSYSTEMS.forEach(sub => {
      sub.fetch()
        .then(data => {
          setResults(prev => ({ ...prev, [sub.id]: { status: 'ok', data, error: null } }));
        })
        .catch(err => {
          setResults(prev => ({ ...prev, [sub.id]: { status: 'error', data: null, error: String(err) } }));
        });
    });
  }, []);

  // ── KPI derivation from live results ────────────────────────────────────
  const systemsOnline = SUBSYSTEMS.filter(s => {
    const r = results[s.id];
    if (r.status !== 'ok') return false;
    const d = _deriveStatus(s.id, r.data);
    return d.state === 'healthy';
  }).length;

  const emailsPending = (() => {
    const r = results['email-queue'];
    if (r.status !== 'ok' || !r.data) return '—';
    return r.data.pending_count ?? 0;
  })();

  const scannerStatus = (() => {
    const r = results['dhl-scanner'];
    if (r.status !== 'ok' || !r.data) return '—';
    const s = (r.data.status || 'never_run');
    return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');
  })();

  const followupQueue = (() => {
    const r = results['dhl-followup'];
    if (r.status !== 'ok' || !r.data) return '—';
    return r.data.eligible_count ?? r.data.eligible ?? r.data.active_count ?? '—';
  })();

  const botErrors = (() => {
    const r = results['bot-pipeline'];
    if (r.status !== 'ok' || !r.data) return '—';
    return (r.data.counts || {}).errors || 0;
  })();

  const activeCarriers = (() => {
    const r = results['carrier-config'];
    if (r.status !== 'ok' || !r.data) return '—';
    return (r.data.carriers || []).filter(c => c.is_active !== false && !c.deleted_at).length;
  })();

  const isLoading = SUBSYSTEMS.some(s => results[s.id].status === 'loading');

  // ── Group order for overview ────────────────────────────────────────────
  const GROUP_ORDER = ['Core', 'DHL', 'Carrier', 'Accounting', 'Comms', 'AI'];

  return (
    <div data-testid="api-status-page" style={{ flex: 1, overflowY: 'auto', padding: '20px 32px 40px' }}>
      {/* KPI strip */}
      <div data-testid="api-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 16 }}>
        <CarrierKpi label="Systems Online" value={isLoading ? '…' : `${systemsOnline} / ${SUBSYSTEMS.length}`} accent={systemsOnline === SUBSYSTEMS.length ? 'var(--badge-green-text)' : 'var(--badge-yellow-text)'} />
        <CarrierKpi label="Emails Pending" value={emailsPending} accent={emailsPending > 5 ? 'var(--badge-red-text)' : 'var(--text)'} />
        <CarrierKpi label="DHL Scanner" value={scannerStatus} accent="var(--text)" />
        <CarrierKpi label="Follow-up Queue" value={followupQueue} accent="var(--text)" />
        <CarrierKpi label="Bot Errors" value={botErrors} accent={botErrors > 0 ? 'var(--badge-red-text)' : 'var(--badge-green-text)'} />
        <CarrierKpi label="Active Carriers" value={activeCarriers} accent="var(--text)" />
      </div>

      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'overview',   label: 'Integration Health' },
          { id: 'guardian',   label: 'Guardian Diagnostic' },
          { id: 'dhl-ops',    label: 'DHL Operations' },
          { id: 'errors',     label: 'Recent Errors' },
          { id: 'bot',        label: 'Bot Activity' },
        ].map(t => (
          <button key={t.id} data-testid={`tab-${t.id}`} onClick={() => setTab(t.id)} style={{
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
      {tab === 'overview' && (
        <div data-testid="tab-content-overview" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {GROUP_ORDER.map(g => {
            const subs = SUBSYSTEMS.filter(s => s.group === g);
            if (!subs.length) return null;
            return (
              <div key={g}>
                <div style={{
                  fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
                  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8,
                }}>{g}</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
                  {subs.map(sub => <SubsystemCard key={sub.id} sub={sub} result={results[sub.id]} />)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tab === 'guardian' && (
        <div data-testid="tab-content-guardian">
          {results['health-full'].status === 'loading'
            ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>Loading Guardian diagnostic…</div>
            : results['health-full'].status === 'error'
              ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--badge-red-text)' }}>Failed to load: {results['health-full'].error}</div>
              : <HealthFullDetail data={results['health-full'].data} />
          }
        </div>
      )}

      {tab === 'dhl-ops' && (
        <div data-testid="tab-content-dhl-ops">
          {results['dhl-ops'].status === 'loading'
            ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>Loading DHL operations…</div>
            : results['dhl-ops'].status === 'error'
              ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--badge-red-text)' }}>Failed to load: {results['dhl-ops'].error}</div>
              : <DhlOpsSummary data={results['dhl-ops'].data} />
          }
        </div>
      )}

      {tab === 'errors' && (
        <div data-testid="tab-content-errors">
          {results['bot-pipeline'].status === 'loading'
            ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>Loading recent errors…</div>
            : results['bot-pipeline'].status === 'error'
              ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--badge-red-text)' }}>Failed to load: {results['bot-pipeline'].error}</div>
              : <RecentErrorsPanel errors={(results['bot-pipeline'].data || {}).last_errors || []} />
          }
        </div>
      )}

      {tab === 'bot' && (
        <div data-testid="tab-content-bot">
          {results['bot-pipeline'].status === 'loading'
            ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>Loading bot activity…</div>
            : results['bot-pipeline'].status === 'error'
              ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--badge-red-text)' }}>Failed to load: {results['bot-pipeline'].error}</div>
              : <BotActivityPanel data={results['bot-pipeline'].data} />
          }
        </div>
      )}
    </div>
  );
}

window.ApiStatusPage = ApiStatusPage;
