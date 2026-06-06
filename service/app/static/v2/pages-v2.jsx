// New page components for the restructured sidebar.
// DhlCustomsPage (merged) · AccountingPage · EmailQueuePage · AiBridgePage · ActionProposalsPage
// Plus a new ReportsPage that REPLACES the old one (financial / sales / purchase / shipping).

// ── Shared small UI helpers
function Tabs({ tabs, active, onChange, style }) {
  return (
    <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)', marginBottom: 16, overflowX: 'auto', flexShrink: 0, ...style }}>
      {tabs.map(t => (
        <button key={t.id} onClick={() => onChange(t.id)} style={{
          padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer',
          fontSize: 12, fontWeight: 600, color: active === t.id ? 'var(--text)' : 'var(--text-3)',
          borderBottom: active === t.id ? '2px solid var(--accent)' : '2px solid transparent',
          whiteSpace: 'nowrap', letterSpacing: '0.02em',
          marginBottom: -1,
        }}>
          {t.label}
          {t.count != null && (
            <span style={{ marginLeft: 6, padding: '1px 6px', background: active === t.id ? 'var(--accent)' : 'var(--bg-subtle)', color: active === t.id ? '#fff' : 'var(--text-3)', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

function StatTile({ label, value, sub, accent, onClick }) {
  return (
    <Card onClick={onClick} style={{ padding: '14px 16px', cursor: onClick ? 'pointer' : 'default' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', fontFamily: '"DM Serif Display", serif', lineHeight: 1.25, wordBreak: 'break-word' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6, lineHeight: 1.4 }}>{sub}</div>}
    </Card>
  );
}

function Pill({ children, tone = 'neutral', small }) {
  const tones = {
    neutral: { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)' },
    blue:    { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)' },
    green:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)' },
    amber:   { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)' },
    red:     { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)' },
    purple:  { bg: 'var(--badge-purple-bg)',  fg: 'var(--badge-purple-text)' },
    gold:    { bg: 'rgba(212,168,83,0.12)',   fg: 'var(--accent)' },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span style={{
      display: 'inline-block', padding: small ? '1px 6px' : '2px 8px',
      background: t.bg, color: t.fg, borderRadius: 4,
      fontSize: small ? 9 : 10, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
      whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// DHL Hub — read-only observer (Sprint 31)
// ────────────────────────────────────────────────────────────────────────────
// Wires the V2 shell `page === 'dhl'` route to live DHL authority. This is a
// VISIBILITY-ONLY surface — Lane A / Lane B / Task Scheduler remain the sole
// automation actors. The Hub renders truth produced by the backend; it never
// mutates server state in any way.
//
// Allowed endpoints (exactly 4 — and nothing else):
//   GET /api/v1/dhl/followup-automation/status     — automation status projection
//   GET /api/v1/dhl/followup-automation/shipments  — DHL shipment rows (projector)
//   GET /api/v1/dhl/auto-scan-status               — Lane A inbox-scanner health (DhlScanStatus)
//   GET /api/v1/dhl/daily-summary                  — daily DHL operations (DhlDailySummary)
//
// Note: the brief originally summarised the first two without the router
// prefix segment "followup-automation". The actual registered prefix in
// routes_dhl_followup_status.py is the followup-automation subpath, so the
// canonical paths include that segment. Authority owner unchanged
// (dhl_followup_status_projector); only the URL shape was corrected.
//
// Composes the existing live cards:
//   window.DhlScanStatus    (service/app/static/v2/dhl-scan-status.jsx)
//   window.DhlDailySummary  (service/app/static/v2/dhl-daily-summary.jsx)
//
// Retired (P3) by this sprint: DhlClearancePipeline, DhlEmailInbox,
// EmailDetailModal, SadDocsTable, and the inline mock arrays.
// Those components held write-implying affordances that this observer must
// never expose; see the brief at .claude/campaigns/atlas-v2/sprint-31-dhl-hub.md
// §4 for the exhaustive forbidden list.
// ════════════════════════════════════════════════════════════════════════════

function DhlCustomsPage({ onViewShipment }) {
  // Live data from the 4 allowed GET endpoints.
  const [statusData,    setStatusData]    = React.useState(null);
  const [statusLoading, setStatusLoading] = React.useState(true);
  const [statusError,   setStatusError]   = React.useState(null);

  const [shipData,    setShipData]    = React.useState(null);
  const [shipLoading, setShipLoading] = React.useState(true);
  const [shipError,   setShipError]   = React.useState(null);

  // Re-render key forces the embedded DhlScanStatus + DhlDailySummary cards to
  // re-mount on a passive Reload (they auto-fetch on mount). Zero server side-effect.
  const [reloadKey, setReloadKey] = React.useState(0);

  const loadStatus = React.useCallback(() => {
    setStatusLoading(true); setStatusError(null);
    window.EstrellaShared.apiFetch('/api/v1/dhl/followup-automation/status')
      .then(d => { setStatusData(d); setStatusLoading(false); })
      .catch(e => { setStatusError((e && e.message) || String(e)); setStatusLoading(false); });
  }, []);

  const loadShipments = React.useCallback(() => {
    setShipLoading(true); setShipError(null);
    window.EstrellaShared.apiFetch('/api/v1/dhl/followup-automation/shipments')
      .then(d => { setShipData(d); setShipLoading(false); })
      .catch(e => { setShipError((e && e.message) || String(e)); setShipLoading(false); });
  }, []);

  React.useEffect(() => { loadStatus();    }, [loadStatus]);
  React.useEffect(() => { loadShipments(); }, [loadShipments]);

  // Passive client-side reload: re-issues the same 4 GETs. No POST, no server
  // side-effect. Brief §3 permits this only with a non-mutating label.
  const reloadAll = React.useCallback(() => {
    loadStatus();
    loadShipments();
    setReloadKey(k => k + 1);
  }, [loadStatus, loadShipments]);

  // Normalise the projector shipment rows. We render whatever fields the
  // projector emits without inventing semantics; if shape changes, the
  // operator sees the raw projector output rather than stale assumptions.
  const ships = (shipData && (shipData.shipments || shipData.rows || shipData.items)) || [];

  return (
    <div data-testid="dhl-hub-root" style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Reload-all bar (passive client-side; zero server side-effect) */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button
          data-testid="dhl-hub-reload"
          onClick={reloadAll}
          disabled={statusLoading || shipLoading}
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 4,
            padding: '4px 10px', fontSize: 11, color: 'var(--text-2)',
            cursor: (statusLoading || shipLoading) ? 'default' : 'pointer',
          }}
        >↻ Reload</button>
      </div>

      {/* Row 1: Lane A scanner health + daily operations report (existing live cards) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 380px) 1fr', gap: 16, marginBottom: 20 }}>
        <div data-testid="dhl-hub-scan-card">
          {window.DhlScanStatus
            ? React.createElement(window.DhlScanStatus, { key: 'scan-' + reloadKey })
            : <div style={{ padding: 12, fontSize: 11, color: 'var(--text-3)' }}>Scanner card unavailable.</div>}
        </div>
        <div data-testid="dhl-hub-summary-card">
          {window.DhlDailySummary
            ? React.createElement(window.DhlDailySummary, { key: 'sum-' + reloadKey })
            : <div style={{ padding: 12, fontSize: 11, color: 'var(--text-3)' }}>Daily summary card unavailable.</div>}
        </div>
      </div>

      {/* Panel: DHL automation status (/dhl/status) */}
      <DhlPanel
        title="DHL automation status"
        subtitle="Live projection from dhl_followup_status_projector — Lane A / Lane B authority"
        testid="dhl-hub-status-panel"
      >
        {statusLoading && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading…</div>}
        {statusError   && <div style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>{statusError}</div>}
        {statusData && (
          <DhlJsonReadout data={statusData} testid="dhl-hub-status-readout" />
        )}
        <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-3)' }}>
          Read-only. No write calls are made from this panel.
        </div>
      </DhlPanel>

      {/* Panel: DHL shipment rows (/dhl/shipments) */}
      <DhlPanel
        title="DHL shipment queue"
        subtitle="Projector rows — read-only visibility into the active DHL workflow"
        testid="dhl-hub-shipments-panel"
      >
        {shipLoading && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading…</div>}
        {shipError   && <div style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>{shipError}</div>}
        {shipData && (
          <DhlShipmentsTable rows={ships} onViewShipment={onViewShipment} testid="dhl-hub-shipments-table" />
        )}
        <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-3)' }}>
          Read-only. No write calls are made from this panel.
        </div>
      </DhlPanel>

      {/* Authority statement */}
      <div style={{
        marginTop: 8, padding: '12px 16px', background: 'var(--bg-subtle)',
        border: '1px solid var(--border)', borderRadius: 8,
        fontSize: 11, color: 'var(--text-3)', lineHeight: 1.5,
      }}>
        <strong style={{ color: 'var(--text-2)' }}>Observer only.</strong>{' '}
        Lane A · Lane B · Task Scheduler remain the sole DHL automation authority.
        This surface is read-only — no write actions, no workflow triggers, no automation controls.{' '}
        <strong style={{ color: 'var(--text-2)' }}>Endpoints:</strong>{' '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/dhl/followup-automation/status</code> ·{' '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/dhl/followup-automation/shipments</code> ·{' '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/dhl/auto-scan-status</code> ·{' '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/dhl/daily-summary</code>.
      </div>
    </div>
  );
}

// ── DHL Hub primitives (private to DhlCustomsPage) ──────────────────────────

function DhlPanel({ title, subtitle, testid, children }) {
  return (
    <div data-testid={testid} style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 10, overflow: 'hidden',
      boxShadow: '0 1px 3px var(--shadow)', marginBottom: 20,
    }}>
      <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{subtitle}</div>}
      </div>
      <div style={{ padding: '16px 20px' }}>{children}</div>
    </div>
  );
}

// Read-only JSON readout — pretty-print whatever the projector emits without
// inventing semantics. Sprint 30 used a similar pattern for unfamiliar payloads.
function DhlJsonReadout({ data, testid }) {
  return (
    <pre data-testid={testid} style={{
      margin: 0, padding: '12px 14px', background: 'var(--bg-subtle)',
      border: '1px solid var(--border)', borderRadius: 6,
      fontSize: 11, color: 'var(--text)',
      overflowX: 'auto', maxHeight: 360, overflowY: 'auto',
      whiteSpace: 'pre-wrap', wordBreak: 'break-all',
      fontFamily: 'monospace', lineHeight: 1.5,
    }}>{JSON.stringify(data, null, 2)}</pre>
  );
}

// Defensive renderer: accepts an array of projector rows, picks a stable
// column set from common fields, and renders read-only. No row actions.
function DhlShipmentsTable({ rows, onViewShipment, testid }) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No DHL shipments in the projector output.</div>;
  }
  // Pick a column set from the first row's actual keys (caps at 8 for layout).
  const pick = ['batch_id', 'awb', 'carrier', 'status', 'state', 'waiting_for', 'updated_at', 'next_action'];
  const present = pick.filter(k => Object.prototype.hasOwnProperty.call(rows[0], k));
  const cols = present.length > 0 ? present : Object.keys(rows[0]).slice(0, 8);

  return (
    <div style={{ overflowX: 'auto', maxHeight: 360, overflowY: 'auto' }} data-testid={testid}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
            {cols.map(h => (
              <th key={h} style={{
                padding: '6px 10px', textAlign: 'left',
                fontWeight: 700, color: 'var(--text-3)',
                letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: 10,
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 200).map((r, i) => (
            <tr key={r.batch_id || r.id || i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              {cols.map(c => {
                const v = r[c];
                const display = v == null ? '—' :
                  typeof v === 'object' ? JSON.stringify(v) :
                  String(v);
                return (
                  <td key={c} style={{
                    padding: '5px 10px',
                    fontFamily: c === 'batch_id' || c === 'awb' ? 'monospace' : undefined,
                    color: 'var(--text-2)',
                    maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{display}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 200 && (
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6 }}>
          Showing first 200 of {rows.length}.
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Accounting (merger of PZ + Sales + wFirma + Master Data + Audit)
// ════════════════════════════════════════════════════════════════════════════
function AccountingPage({ onViewShipment }) {
  const [tab, setTab] = React.useState('purchase');
  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Purchase ledger" value="142" sub="PZ documents this month" />
        <StatTile label="Sales / proforma" value="38" sub="Active · 6 awaiting export" accent="var(--accent)" />
        <StatTile label="wFirma sync" value="OK" sub="Last sync 4 min ago · 0 errors" accent="var(--badge-green-text)" />
        <StatTile label="Audit events" value="1,284" sub="Last 30 days" />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'purchase',  label: 'Purchase Ledger (PZ)' },
          { id: 'sales',     label: 'Sales / Proforma' },
          { id: 'ledgers',   label: 'Ledgers / Statements' },
          { id: 'wfirma',    label: 'wFirma Sync' },
          { id: 'master',    label: 'Master Data' },
          { id: 'audit',     label: 'Audit Trail' },
        ]}
      />

      {tab === 'purchase' && <PzAccountingPage onViewShipment={onViewShipment} />}
      {tab === 'sales'    && <SalesProformaPage onGoToWfirma={() => setTab('wfirma')} />}
      {tab === 'ledgers'  && (window.LedgersPage ? <window.LedgersPage /> : null)}
      {tab === 'wfirma'   && <WfirmaExportPage onViewShipment={onViewShipment} />}
      {tab === 'master'   && <MasterDataView />}
      {tab === 'audit'    && <AuditTrailView />}
    </div>
  );
}

function MasterDataView() {
  const [section, setSection] = React.useState('clients');
  const sections = [
    { id: 'clients',   label: 'Clients / Importers', count: 12 },
    { id: 'suppliers', label: 'Suppliers / Exporters', count: 47 },
    { id: 'hs',        label: 'HS Codes / Tariff', count: 184 },
    { id: 'fx',        label: 'Currency / FX Rates' },
    { id: 'vat',       label: 'VAT Rates' },
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16 }}>
      <Card style={{ padding: 6 }}>
        {sections.map(s => (
          <button key={s.id} onClick={() => setSection(s.id)} style={{
            width: '100%', padding: '10px 12px', textAlign: 'left',
            background: section === s.id ? 'var(--bg-subtle)' : 'transparent',
            border: 'none', borderRadius: 4, cursor: 'pointer',
            fontSize: 12, fontWeight: section === s.id ? 600 : 500,
            color: section === s.id ? 'var(--text)' : 'var(--text-2)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            {s.label}
            {s.count != null && <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{s.count}</span>}
          </button>
        ))}
      </Card>
      <Card style={{ padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{sections.find(s => s.id === section).label}</div>
          <Btn small variant="outline">+ Add</Btn>
        </div>
        {section === 'clients' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Name', 'Country', 'NIP / VAT ID', 'Default Currency', 'Last activity', ''].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[
                ['Estrella Jewels Sp. z o.o.', 'PL', 'PL5252312345', 'PLN', '2 min ago'],
                ['Atelier Bonacchi SRL', 'IT', 'IT04520119872', 'EUR', '3 days ago'],
                ['Geneva Imports SA', 'CH', 'CHE-115.823.554', 'CHF', '1 week ago'],
              ].map(r => (
                <tr key={r[0]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400 }}>{c}</td>)}
                  <td><Btn small variant="outline">Edit</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section === 'suppliers' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Supplier', 'Country', 'Default Carrier', 'HS Codes', 'Active'].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[
                ['Bonacchi Atelier', 'IT', 'DHL', '7113.19, 7117.19', '✓'],
                ['Maison de Vicenza', 'IT', 'FedEx', '7113.11, 7113.19', '✓'],
                ['Antwerp Stones', 'BE', 'DHL', '7102.39, 7103.91', '✓'],
                ['Geneva Goldworks', 'CH', 'DHL', '7113.19', '✓'],
              ].map(r => (
                <tr key={r[0]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400 }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section === 'hs' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['HS Code', 'Description', 'Duty %', 'VAT %', 'Locked'].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[
                ['7113.19.00', 'Articles of jewellery, precious metal (excl. silver)', '2.5%', '23%', '🔒'],
                ['7113.11.00', 'Articles of jewellery of silver', '2.5%', '23%', '🔒'],
                ['7102.39.00', 'Diamonds, non-industrial, worked', '0%', '23%', '🔒'],
                ['7103.91.00', 'Rubies, sapphires, emeralds — worked', '0%', '23%', '🔒'],
                ['7117.19.00', 'Imitation jewellery, base metal', '4%', '23%', '🔒'],
              ].map(r => (
                <tr key={r[0]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, fontFamily: i === 0 ? 'monospace' : 'inherit', color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400 }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section === 'fx' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
              {[['EUR', '4.3128', '+0.012'], ['USD', '4.0214', '-0.008'], ['CHF', '4.4502', '+0.021'], ['GBP', '5.0388', '+0.005']].map(r => (
                <div key={r[0]} style={{ padding: 12, background: 'var(--bg-subtle)', borderRadius: 6, border: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em' }}>{r[0]} → PLN</div>
                  <div style={{ fontSize: 20, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{r[1]}</div>
                  <div style={{ fontSize: 10, color: r[2].startsWith('+') ? 'var(--badge-green-text)' : 'var(--badge-red-text)' }}>{r[2]} vs yesterday</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>NBP table A · 27 April 2024 · Last sync 11 min ago. SAD historical rates kept per shipment.</div>
          </div>
        )}
        {section === 'vat' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Rate', 'Code', 'Applies to', 'Locked'].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[['23%', 'VAT-23', 'Standard rate (jewellery, accessories)', '🔒'], ['8%', 'VAT-8', 'Reduced rate', '🔒'], ['0%', 'VAT-0', 'Exports, intra-EU supplies', '🔒'], ['NP', 'VAT-NP', 'Not subject to VAT', '🔒']].map(r => (
                <tr key={r[1]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-2)' }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function AuditTrailView() {
  const events = [
    { ts: '14:42:11', user: 'system', action: 'AI Bridge classified DHL email', target: 'em-872 · DHL-7733991122', tone: 'blue' },
    { ts: '14:38:02', user: 'anna.k',  action: 'Approved reply package', target: 'DHL-8825441199', tone: 'green' },
    { ts: '14:21:55', user: 'anna.k',  action: 'Edited HS code', target: '7113.19 → 7117.19 · DHL-2244668800', tone: 'amber' },
    { ts: '14:08:03', user: 'system', action: 'Generated PZ document', target: 'PZ/2024/000891 · DHL-9988776655', tone: 'purple' },
    { ts: '13:54:17', user: 'tomek.w', action: 'Uploaded SAD', target: 'ZC429/2024/000847 · DHL-9988776655', tone: 'green' },
    { ts: '13:32:00', user: 'system', action: 'wFirma export succeeded', target: 'PZ/2024/000890 → wFirma id #38221', tone: 'green' },
    { ts: '12:11:48', user: 'system', action: 'Action proposal queued', target: 'AP-014 · Reclassify supplier "Bonacchi"', tone: 'gold' },
    { ts: '11:02:33', user: 'anna.k',  action: 'Closed temporary import', target: 'ATA-2024-0118 · Vicenza Show', tone: 'green' },
  ];
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Input placeholder="Search action / target…" />
        <Select><option>All users</option><option>anna.k</option><option>tomek.w</option><option>system</option></Select>
        <Select><option>All actions</option><option>Approvals</option><option>Edits</option><option>Exports</option></Select>
        <Btn variant="outline" small>↓ Export</Btn>
      </div>
      <Card style={{ overflow: 'hidden' }}>
        {events.map((e, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '90px 110px 1fr 1.5fr', gap: 12, padding: '10px 16px', borderBottom: i < events.length - 1 ? '1px solid var(--border-subtle)' : 'none', alignItems: 'center', fontSize: 12 }}>
            <div style={{ fontFamily: 'monospace', color: 'var(--text-3)' }}>{e.ts}</div>
            <div style={{ color: 'var(--text)', fontWeight: 600 }}>{e.user}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Pill tone={e.tone} small>{e.action}</Pill>
            </div>
            <div style={{ color: 'var(--text-2)', fontFamily: 'monospace', fontSize: 11 }}>{e.target}</div>
          </div>
        ))}
      </Card>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Email Queue (system-wide email queue, beyond just DHL)
// ════════════════════════════════════════════════════════════════════════════
function EmailQueuePage({ onViewShipment }) {
  const [filter, setFilter] = React.useState('all');
  const queue = [
    { id: 'eq-1', dir: 'in',  source: 'DHL',     subject: 'RE: Customs clearance — pre-check', awb: 'DHL-7733991122', received: '2 min ago',  status: 'parsed', size: '12 KB' },
    { id: 'eq-2', dir: 'out', source: 'DHL',     subject: 'Reply: Documents attached', awb: 'DHL-8825441199', received: '14 min ago', status: 'sent', size: '2.3 MB' },
    { id: 'eq-3', dir: 'out', source: 'DHL',     subject: 'Reply queued: DSK + invoice', awb: 'DHL-5566778899', received: 'pending',    status: 'queued', size: '1.1 MB' },
    { id: 'eq-4', dir: 'in',  source: 'DHL',     subject: 'Customs: SAD ZC429 issued',   awb: 'DHL-9988776655', received: '1 h ago',    status: 'parsed', size: '480 KB' },
    { id: 'eq-5', dir: 'in',  source: 'DHL',     subject: 'RE: Clearance request',       awb: 'DHL-2244668800', received: '3 h ago',    status: 'error',  size: '8 KB',  error: 'MRN extraction failed' },
    { id: 'eq-6', dir: 'out', source: 'wFirma',  subject: 'Export PZ/2024/000891',       awb: 'DHL-9988776655', received: '4 h ago',    status: 'sent',   size: '14 KB' },
    { id: 'eq-7', dir: 'out', source: 'system',  subject: 'Daily summary — 27 Apr 2024', awb: '—',              received: 'Yesterday',  status: 'sent',   size: '32 KB' },
    { id: 'eq-8', dir: 'out', source: 'wFirma',  subject: 'Export PZ/2024/000885',       awb: 'DHL-1199227733', received: '5 h ago',    status: 'error',  size: '14 KB', error: 'wFirma API timeout (gateway)' },
  ];

  const filters = [
    { id: 'all',     label: 'All',          count: queue.length },
    { id: 'in',      label: 'Inbound',      count: queue.filter(q => q.dir === 'in').length },
    { id: 'out',     label: 'Outbound',     count: queue.filter(q => q.dir === 'out').length },
    { id: 'queued',  label: 'Pending Send', count: queue.filter(q => q.status === 'queued').length },
    { id: 'error',   label: 'Errors',       count: queue.filter(q => q.status === 'error').length },
    { id: 'wfirma',  label: 'wFirma',       count: queue.filter(q => q.source === 'wFirma').length },
    { id: 'dhl',     label: 'DHL',          count: queue.filter(q => q.source === 'DHL').length },
  ];

  const visible = queue.filter(q => {
    if (filter === 'all') return true;
    if (filter === 'in' || filter === 'out') return q.dir === filter;
    if (filter === 'wfirma') return q.source === 'wFirma';
    if (filter === 'dhl') return q.source === 'DHL';
    return q.status === filter;
  });

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Total today" value={queue.length} sub="In + out" />
        <StatTile label="Pending send" value={queue.filter(q => q.status === 'queued').length} sub="Awaiting approval" accent="var(--accent)" />
        <StatTile label="Errors" value={queue.filter(q => q.status === 'error').length} sub="Need operator review" accent="var(--badge-red-text)" />
        <StatTile label="Avg parse time" value="3.2s" sub="DHL inbound · last 24h" accent="var(--badge-green-text)" />
      </div>

      <Card style={{ overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 6, borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', flexWrap: 'wrap' }}>
          {filters.map(f => (
            <button key={f.id} onClick={() => setFilter(f.id)} style={{
              padding: '4px 10px', background: filter === f.id ? 'var(--card)' : 'transparent',
              border: '1px solid ' + (filter === f.id ? 'var(--border)' : 'transparent'),
              borderRadius: 4, fontSize: 11, fontWeight: 600,
              color: filter === f.id ? 'var(--text)' : 'var(--text-3)', cursor: 'pointer',
            }}>{f.label} <span style={{ opacity: 0.6, marginLeft: 4 }}>{f.count}</span></button>
          ))}
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['', 'Source', 'Subject / Linked AWB', 'Received', 'Size', 'Status', 'Actions'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map(q => (
              <tr key={q.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{ display: 'inline-flex', width: 22, height: 22, borderRadius: '50%', background: q.dir === 'in' ? 'var(--badge-blue-bg)' : 'var(--bg-subtle)', color: q.dir === 'in' ? 'var(--badge-blue-text)' : 'var(--text-3)', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{q.dir === 'in' ? '↓' : '↑'}</span>
                </td>
                <td style={{ padding: '10px 12px' }}><Pill tone={q.source === 'DHL' ? 'blue' : q.source === 'wFirma' ? 'purple' : 'neutral'} small>{q.source}</Pill></td>
                <td style={{ padding: '10px 12px' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{q.subject}</div>
                  {q.awb !== '—' && <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--badge-blue-text)', marginTop: 2 }}>{q.awb}</div>}
                  {q.error && <div style={{ fontSize: 11, color: 'var(--badge-red-text)', marginTop: 4 }}>⚠ {q.error}</div>}
                </td>
                <td style={{ padding: '10px 12px', color: 'var(--text-3)', fontSize: 11, whiteSpace: 'nowrap' }}>{q.received}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text-3)', fontSize: 11, fontFamily: 'monospace' }}>{q.size}</td>
                <td style={{ padding: '10px 12px' }}>
                  {q.status === 'parsed' && <Pill tone="green"  small>PARSED</Pill>}
                  {q.status === 'sent'   && <Pill tone="green"  small>SENT</Pill>}
                  {q.status === 'queued' && <Pill tone="gold"   small>QUEUED</Pill>}
                  {q.status === 'error'  && <Pill tone="red"    small>ERROR</Pill>}
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {q.status === 'queued' && <Btn small variant="gold">Send</Btn>}
                    {q.status === 'error'  && <Btn small variant="gold">Retry</Btn>}
                    <Btn small variant="outline">View</Btn>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Automation Hub — read-only observer over AI Bridge authority (Sprint 33)
// Authority: routes_ai_bridge.py  (GET endpoints only)
// Allowed:  GET /api/v1/ai-bridge/tasks  GET /api/v1/ai-bridge/errors
//           GET /api/v1/ai-bridge/templates
// Forbidden: POST /api/v1/ai-bridge/tasks/{batch_id}
//            POST /api/v1/ai-bridge/results/{task_id}
// Retired:  hardcoded tasks[] array, capabilities[] array, Retry/Edit/Save &
//           Activate/Test/Diff buttons, static stat tiles, Capabilities tab.
// ════════════════════════════════════════════════════════════════════════════
function AiBridgePage() {
  const [tab, setTab] = React.useState('tasks');

  const [pendingData,    setPendingData]    = React.useState(null);
  const [pendingLoading, setPendingLoading] = React.useState(true);
  const [pendingError,   setPendingError]   = React.useState(null);

  const [processedData,    setProcessedData]    = React.useState(null);
  const [processedLoading, setProcessedLoading] = React.useState(true);
  const [processedError,   setProcessedError]   = React.useState(null);

  const [errorsData,     setErrorsData]     = React.useState(null);
  const [errorsLoading,  setErrorsLoading]  = React.useState(true);
  const [errorsFetchErr, setErrorsFetchErr] = React.useState(null);

  const [templatesData,    setTemplatesData]    = React.useState(null);
  const [templatesLoading, setTemplatesLoading] = React.useState(true);
  const [templatesError,   setTemplatesError]   = React.useState(null);

  const loadPending = React.useCallback(() => {
    setPendingLoading(true); setPendingError(null);
    window.EstrellaShared.apiFetch('/api/v1/ai-bridge/tasks?status=pending')
      .then(d => { setPendingData(d); setPendingLoading(false); })
      .catch(e => { setPendingError((e && e.message) || String(e)); setPendingLoading(false); });
  }, []);

  const loadProcessed = React.useCallback(() => {
    setProcessedLoading(true); setProcessedError(null);
    window.EstrellaShared.apiFetch('/api/v1/ai-bridge/tasks?status=processed')
      .then(d => { setProcessedData(d); setProcessedLoading(false); })
      .catch(e => { setProcessedError((e && e.message) || String(e)); setProcessedLoading(false); });
  }, []);

  const loadErrors = React.useCallback(() => {
    setErrorsLoading(true); setErrorsFetchErr(null);
    window.EstrellaShared.apiFetch('/api/v1/ai-bridge/errors')
      .then(d => { setErrorsData(d); setErrorsLoading(false); })
      .catch(e => { setErrorsFetchErr((e && e.message) || String(e)); setErrorsLoading(false); });
  }, []);

  const loadTemplates = React.useCallback(() => {
    setTemplatesLoading(true); setTemplatesError(null);
    window.EstrellaShared.apiFetch('/api/v1/ai-bridge/templates')
      .then(d => { setTemplatesData(d); setTemplatesLoading(false); })
      .catch(e => { setTemplatesError((e && e.message) || String(e)); setTemplatesLoading(false); });
  }, []);

  React.useEffect(() => {
    loadPending(); loadProcessed(); loadErrors(); loadTemplates();
  }, [loadPending, loadProcessed, loadErrors, loadTemplates]);

  const reloadAll = React.useCallback(() => {
    loadPending(); loadProcessed(); loadErrors(); loadTemplates();
  }, [loadPending, loadProcessed, loadErrors, loadTemplates]);

  const pendingList   = (pendingData   && Array.isArray(pendingData.tasks))   ? pendingData.tasks   : [];
  const processedList = (processedData && Array.isArray(processedData.tasks)) ? processedData.tasks : [];
  const errorList     = (errorsData    && Array.isArray(errorsData.errors))   ? errorsData.errors   : [];
  const templateMap   = (templatesData && templatesData.templates)             ? templatesData.templates : {};

  const anyLoading = pendingLoading || processedLoading || errorsLoading || templatesLoading;

  return (
    <div data-testid="automation-hub-root" style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button
          data-testid="automation-hub-reload"
          onClick={reloadAll}
          disabled={anyLoading}
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 4,
            padding: '4px 10px', fontSize: 11, color: 'var(--text-2)',
            cursor: anyLoading ? 'default' : 'pointer',
          }}
        >↻ Reload</button>
      </div>

      <div data-testid="automation-hub-summary" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile
          label="Pending tasks"
          value={pendingLoading ? '…' : pendingData != null ? String(pendingData.count) : '—'}
          sub="Awaiting AI processing"
        />
        <StatTile
          label="Processed"
          value={processedLoading ? '…' : processedData != null ? String(processedData.count) : '—'}
          sub="Completed task results"
          accent="var(--badge-green-text)"
        />
        <StatTile
          label="Errors"
          value={errorsLoading ? '…' : errorsData != null ? String(errorsData.count) : '—'}
          sub="Rejected results"
          accent={errorsData && errorsData.count > 0 ? 'var(--badge-red-text)' : undefined}
        />
        <StatTile
          label="Task types"
          value={templatesLoading ? '…' : templatesData != null ? String(templatesData.count) : '—'}
          sub="Registered templates"
        />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'tasks',     label: 'Task Queue',     count: pendingData   ? pendingData.count   : null },
          { id: 'results',   label: 'Recent Results', count: processedData ? processedData.count : null },
          { id: 'errors',    label: 'Errors',         count: errorsData    ? errorsData.count    : null },
          { id: 'templates', label: 'Templates',      count: templatesData ? templatesData.count : null },
        ]}
      />

      {tab === 'tasks' && (
        <AiBridgeTaskTable
          rows={pendingList}
          loading={pendingLoading}
          error={pendingError}
          testid="automation-hub-tasks-table"
        />
      )}

      {tab === 'results' && (
        <AiBridgeTaskTable
          rows={processedList}
          loading={processedLoading}
          error={processedError}
          testid="automation-hub-results-table"
        />
      )}

      {tab === 'errors' && (
        <AiBridgeErrorTable
          rows={errorList}
          loading={errorsLoading}
          error={errorsFetchErr}
          testid="automation-hub-errors-table"
        />
      )}

      {tab === 'templates' && (
        <AiBridgeTemplatesView
          templates={templateMap}
          loading={templatesLoading}
          error={templatesError}
          testid="automation-hub-templates"
        />
      )}

      <div style={{
        marginTop: 8, padding: '12px 16px', background: 'var(--bg-subtle)',
        border: '1px solid var(--border)', borderRadius: 8,
        fontSize: 11, color: 'var(--text-3)', lineHeight: 1.5,
      }}>
        <strong style={{ color: 'var(--text-2)' }}>Observer only.</strong>{' '}
        Task execution, result submission, and capability configuration remain the sole authority of the AI Bridge engine.
        This surface is read-only — no task queuing, no result submission, no template editing.
        {' '}Endpoints:{' '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/ai-bridge/tasks</code>
        {' · '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/ai-bridge/errors</code>
        {' · '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>/api/v1/ai-bridge/templates</code>
      </div>
    </div>
  );
}

function AiBridgeTaskTable({ rows, loading, error, testid }) {
  if (loading) return <div style={{ fontSize: 12, color: 'var(--text-3)', padding: 12 }}>Loading…</div>;
  if (error)   return <div style={{ fontSize: 12, color: 'var(--badge-red-text)', padding: 12 }}>{error}</div>;
  if (!Array.isArray(rows) || rows.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text-3)', padding: 12 }}>No tasks in this queue.</div>;
  }
  const PREF = ['task_id', 'task_type', 'batch_id', 'status', 'created_at', 'note'];
  const present = PREF.filter(k => Object.prototype.hasOwnProperty.call(rows[0], k));
  const cols = present.length > 0 ? present : Object.keys(rows[0]).slice(0, 6);
  return (
    <div data-testid={testid} style={{ overflowX: 'auto', marginBottom: 12 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, background: 'var(--card)', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border)' }}>
        <thead>
          <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
            {cols.map(h => (
              <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: 10 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 200).map((r, i) => (
            <tr key={r.task_id || r.id || i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              {cols.map(c => {
                const v = r[c];
                const disp = v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);
                return (
                  <td key={c} style={{ padding: '6px 12px', fontFamily: (c === 'task_id' || c === 'batch_id') ? 'monospace' : undefined, color: 'var(--text-2)', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{disp}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 200 && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>Showing first 200 of {rows.length}.</div>}
    </div>
  );
}

function AiBridgeErrorTable({ rows, loading, error, testid }) {
  if (loading) return <div style={{ fontSize: 12, color: 'var(--text-3)', padding: 12 }}>Loading…</div>;
  if (error)   return <div style={{ fontSize: 12, color: 'var(--badge-red-text)', padding: 12 }}>{error}</div>;
  if (!Array.isArray(rows) || rows.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text-3)', padding: 12 }}>No error records.</div>;
  }
  const PREF = ['task_id', 'task_type', 'batch_id', 'reason', 'rejected_at', 'source'];
  const present = PREF.filter(k => Object.prototype.hasOwnProperty.call(rows[0], k));
  const cols = present.length > 0 ? present : Object.keys(rows[0]).slice(0, 6);
  return (
    <div data-testid={testid} style={{ overflowX: 'auto', marginBottom: 12 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, background: 'var(--card)', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--badge-red-border)' }}>
        <thead>
          <tr style={{ background: 'var(--badge-red-bg)', borderBottom: '1px solid var(--badge-red-border)' }}>
            {cols.map(h => (
              <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 700, color: 'var(--badge-red-text)', letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: 10 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((r, i) => (
            <tr key={r.task_id || r.id || i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              {cols.map(c => {
                const v = r[c];
                const disp = v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);
                return (
                  <td key={c} style={{ padding: '6px 12px', fontFamily: (c === 'task_id' || c === 'batch_id') ? 'monospace' : undefined, color: 'var(--text-2)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{disp}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AiBridgeTemplatesView({ templates, loading, error, testid }) {
  if (loading) return <div style={{ fontSize: 12, color: 'var(--text-3)', padding: 12 }}>Loading…</div>;
  if (error)   return <div style={{ fontSize: 12, color: 'var(--badge-red-text)', padding: 12 }}>{error}</div>;
  const keys = Object.keys(templates || {});
  if (keys.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text-3)', padding: 12 }}>No templates registered.</div>;
  }
  return (
    <div data-testid={testid} style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 12 }}>
      {keys.map(key => {
        const t = templates[key];
        return (
          <div key={key} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', boxShadow: '0 1px 3px var(--shadow)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{key}</span>
              <Pill tone="blue" small>TEMPLATE</Pill>
            </div>
            {t && t.description && (
              <div style={{ fontSize: 11, color: 'var(--text-2)', lineHeight: 1.5, marginBottom: 8 }}>{t.description}</div>
            )}
            {t && t.result_schema && (
              <details style={{ fontSize: 10 }}>
                <summary style={{ cursor: 'pointer', color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>Result schema</summary>
                <pre style={{ margin: '6px 0 0', padding: '8px 10px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 10, color: 'var(--text)', fontFamily: 'monospace', overflowX: 'auto', maxHeight: 160, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{JSON.stringify(t.result_schema, null, 2)}</pre>
              </details>
            )}
            <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-3)' }}>Read-only. No template editing.</div>
          </div>
        );
      })}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Action Proposals — cross-batch AI suggestions awaiting operator approval
// ════════════════════════════════════════════════════════════════════════════
function ActionProposalsPage() {
  const proposals = [
    {
      id: 'AP-014', priority: 'high', impact: 'PLN 12,400 / month',
      title: 'Reclassify supplier "Bonacchi Atelier" default carrier from DHL to FedEx',
      reason: 'Last 18 shipments via FedEx cleared 2.3 days faster on average; DHL pre-check failures up 22% this month.',
      affected: 18, affectedKind: 'shipments', proposedAt: '2 h ago', evidence: ['18 shipments analysed', 'Avg DHL clearance: 4.1d', 'Avg FedEx clearance: 1.8d'],
    },
    {
      id: 'AP-013', priority: 'high', impact: 'Risk reduction',
      title: 'Add "PROBLEMATIC" DSK flag to all gold jewellery > EUR 8,000 from Switzerland',
      reason: 'Swiss origin + high CIF triggers manual customs review in 67% of cases. Pre-flagging reduces clearance time.',
      affected: 7, affectedKind: 'pending shipments', proposedAt: '4 h ago', evidence: ['Last 90 days: 21/31 manually reviewed', 'Avg delay when manual: +3.2d'],
    },
    {
      id: 'AP-012', priority: 'medium', impact: 'PLN 880 saved',
      title: 'Update HS code 7117.19.00 → 7113.19.00 for "Bonacchi rose-gold"',
      reason: 'AI classifier confidence 0.91 on reclassification. Duty drops 4% → 2.5% for these line items.',
      affected: 14, affectedKind: 'line items in PZ/2024/000891', proposedAt: '6 h ago', evidence: ['SAD ZC429/2024/000847 line 3', 'Bonacchi catalog 2024 confirms'],
    },
    {
      id: 'AP-011', priority: 'medium', impact: 'Process',
      title: 'Auto-approve DHL replies when DSK = STANDARD and CIF < EUR 1,500',
      reason: 'Last 60 days: 0 errors out of 142 such replies. Manual approval averages 14 min delay per shipment.',
      affected: 142, affectedKind: 'historical shipments', proposedAt: '1 day ago', evidence: ['142/142 succeeded', 'Avg manual delay: 14m'],
    },
    {
      id: 'AP-010', priority: 'low', impact: 'Cleanup',
      title: 'Archive 38 closed temp-import carnets older than 6 months',
      reason: 'All marked Re-exported, all closure documents present. Free up the active list for operators.',
      affected: 38, affectedKind: 'ATA carnets', proposedAt: '2 days ago', evidence: ['38/38 have closure docs', 'Last activity > 180d'],
    },
  ];

  const [tab, setTab] = React.useState('pending');

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ padding: 14, background: 'rgba(212,168,83,0.08)', border: '1px solid rgba(212,168,83,0.3)', borderRadius: 6, marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'var(--accent)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, flexShrink: 0 }}>◉</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 2 }}>Path-A · Cross-batch action proposals</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5 }}>The AI Bridge analyses the full ledger and proposes actions that improve clearance speed, reduce duty, or reduce risk. Every proposal is operator-approved before it takes effect. Approvals become rules; rejections train the model.</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Pending review" value={proposals.length} sub="High: 2 · Med: 2 · Low: 1" accent="var(--accent)" />
        <StatTile label="Approved (30d)" value="23" sub="14 became active rules" accent="var(--badge-green-text)" />
        <StatTile label="Rejected (30d)" value="7" sub="Used for model training" />
        <StatTile label="Estimated savings" value="PLN 18,420" sub="From applied proposals · 30d" accent="var(--badge-green-text)" />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'pending',  label: 'Pending Review', count: proposals.length },
          { id: 'approved', label: 'Approved' },
          { id: 'rejected', label: 'Rejected' },
          { id: 'rules',    label: 'Active Rules' },
        ]}
      />

      {tab === 'pending' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {proposals.map(p => (
            <Card key={p.id} style={{ padding: 18 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                <div style={{ flexShrink: 0 }}>
                  <Pill tone={p.priority === 'high' ? 'red' : p.priority === 'medium' ? 'amber' : 'neutral'} small>{p.priority.toUpperCase()}</Pill>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-3)', fontWeight: 600 }}>{p.id}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>·</span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Proposed {p.proposedAt}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>·</span>
                    <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>Impact: {p.impact}</span>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', fontFamily: '"DM Serif Display", serif', marginBottom: 6 }}>{p.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.55, marginBottom: 10 }}>{p.reason}</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                    <Pill tone="blue" small>Affects {p.affected} {p.affectedKind}</Pill>
                    {p.evidence.map(e => <Pill key={e} tone="neutral" small>{e}</Pill>)}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Btn variant="gold" small>✓ Approve & Apply</Btn>
                    <Btn variant="outline" small>Approve as Rule</Btn>
                    <Btn variant="outline" small>Edit</Btn>
                    <Btn variant="outline" small>✗ Reject</Btn>
                    <Btn variant="outline" small>Snooze 7d</Btn>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab !== 'pending' && (
        <Card style={{ padding: 48, textAlign: 'center', color: 'var(--text-3)' }}>
          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.4 }}>◉</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{tab === 'approved' ? '23 approved proposals · 14 active rules' : tab === 'rejected' ? '7 rejected proposals · used for training' : '14 active rules from approved proposals'}</div>
          <div style={{ fontSize: 11, marginTop: 4 }}>Connect API to load full history.</div>
        </Card>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Reports — financial, sales, purchase, shipping (date-filtered)
// ════════════════════════════════════════════════════════════════════════════
function ReportsPage() {
  const [period, setPeriod] = React.useState('mtd');
  const [tab, setTab] = React.useState('financial');

  const periods = [
    { id: 'today', label: 'Today' },
    { id: 'wtd',   label: 'Week to date' },
    { id: 'mtd',   label: 'Month to date' },
    { id: 'qtd',   label: 'Quarter to date' },
    { id: 'ytd',   label: 'Year to date' },
    { id: 'last30', label: 'Last 30 days' },
    { id: 'custom', label: 'Custom…' },
  ];

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Date range bar */}
      <Card style={{ padding: 14, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Period</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {periods.map(p => (
            <button key={p.id} onClick={() => setPeriod(p.id)} style={{
              padding: '6px 12px', background: period === p.id ? 'var(--text)' : 'transparent',
              border: '1px solid ' + (period === p.id ? 'var(--text)' : 'var(--border)'),
              borderRadius: 4, fontSize: 11, fontWeight: 600,
              color: period === p.id ? 'var(--card)' : 'var(--text-2)', cursor: 'pointer',
            }}>{p.label}</button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>1 Apr → 27 Apr 2024 · 27 days</div>
        <Btn small variant="outline">↓ Export PDF</Btn>
        <Btn small variant="outline">↓ Export CSV</Btn>
        <Btn small variant="outline">📅 Schedule</Btn>
      </Card>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'financial',  label: 'Financial' },
          { id: 'sales',      label: 'Sales' },
          { id: 'purchase',   label: 'Purchase' },
          { id: 'shipping',   label: 'Shipping' },
          { id: 'duty',       label: 'Duty & VAT' },
        ]}
      />

      {tab === 'financial' && <ReportsFinancial />}
      {tab === 'sales'     && <ReportsSales />}
      {tab === 'purchase'  && <ReportsPurchase />}
      {tab === 'shipping'  && <ReportsShipping />}
      {tab === 'duty'      && <ReportsDuty />}
    </div>
  );
}

function MiniBarChart({ data, accent, height = 80 }) {
  const max = Math.max(...data.map(d => d.v));
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height, padding: '4px 0' }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <div style={{ width: '100%', height: `${(d.v / max) * (height - 20)}px`, background: accent || 'var(--accent)', borderRadius: 2, opacity: 0.8 }} />
          <div style={{ fontSize: 9, color: 'var(--text-3)', fontWeight: 600 }}>{d.label}</div>
        </div>
      ))}
    </div>
  );
}

function ReportsFinancial() {
  const days = ['1', '5', '10', '15', '20', '25', '27'].map((d, i) => ({ label: d, v: [42000, 58000, 72000, 89000, 124000, 156000, 184500][i] }));
  const margin = ['1', '5', '10', '15', '20', '25', '27'].map((d, i) => ({ label: d, v: [18, 22, 19, 24, 27, 25, 28][i] }));
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Revenue" value="PLN 184,500" sub="+18% vs last month" accent="var(--badge-green-text)" />
        <StatTile label="Cost of goods" value="PLN 132,800" sub="incl. duty & VAT non-recoverable" />
        <StatTile label="Gross margin" value="28.0%" sub="+3.2 pp vs last month" accent="var(--badge-green-text)" />
        <StatTile label="Outstanding A/R" value="PLN 42,180" sub="6 invoices · oldest 14 days" accent="var(--accent)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 12, marginBottom: 16 }} className="grid-2col">
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Cumulative revenue</div>
          <div style={{ fontSize: 22, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 14 }}>PLN 184,500</div>
          <MiniBarChart data={days} accent="var(--accent)" height={120} />
        </Card>
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Daily margin %</div>
          <div style={{ fontSize: 22, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 14 }}>28.0%</div>
          <MiniBarChart data={margin} accent="var(--badge-green-text)" height={120} />
        </Card>
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>P&L summary</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <tbody>
            {[
              ['Revenue (proforma accepted)',     'PLN 184,500', false],
              ['  Goods sold',                     'PLN 178,200', true],
              ['  Service fees',                   'PLN 6,300',   true],
              ['Cost of goods (PZ booked)',        'PLN 124,800', false],
              ['  Net invoice value',              'PLN 109,400', true],
              ['  Duty A00',                       'PLN 7,200',   true],
              ['  Shipping & insurance',           'PLN 4,800',   true],
              ['  Service invoices',               'PLN 3,400',   true],
              ['Gross profit',                     'PLN 51,700',  false, 'green'],
              ['Operating expenses',               'PLN 18,200',  false],
              ['EBITDA',                           'PLN 33,500',  false, 'gold'],
            ].map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '8px 12px', fontSize: 12, color: r[2] ? 'var(--text-2)' : 'var(--text)', fontWeight: r[2] ? 400 : 600, paddingLeft: r[2] ? 28 : 12 }}>{r[0]}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: r[2] ? 400 : 700, color: r[3] === 'green' ? 'var(--badge-green-text)' : r[3] === 'gold' ? 'var(--accent)' : 'var(--text)' }}>{r[1]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ReportsSales() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Proformas issued" value="38" sub="MTD · +12 vs last month" />
        <StatTile label="Accepted" value="29" sub="76% acceptance rate" accent="var(--badge-green-text)" />
        <StatTile label="Avg deal size" value="PLN 6,360" sub="vs PLN 5,820 last month" accent="var(--accent)" />
        <StatTile label="Days to close" value="3.2" sub="median · -0.8d MoM" accent="var(--badge-green-text)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }} className="grid-2col">
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Top clients (MTD)</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <tbody>
              {[
                ['Estrella Boutique Warsaw', 'PLN 64,200', 9],
                ['Geneva Imports SA',         'PLN 38,900', 4],
                ['Estrella Boutique Krakow',  'PLN 28,600', 6],
                ['Atelier Bonacchi SRL',      'PLN 22,400', 3],
                ['Paris Atelier Direct',      'PLN 14,800', 2],
              ].map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{r[0]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r[1]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontSize: 11, color: 'var(--text-3)', width: 60 }}>{r[2]} prof.</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>By product category</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <tbody>
              {[
                ['Gold jewellery',   'PLN 98,400', '53%'],
                ['Silver jewellery', 'PLN 38,200', '21%'],
                ['Diamond pieces',   'PLN 28,400', '15%'],
                ['Coloured stones',  'PLN 14,200', '8%'],
                ['Imitation / accessories', 'PLN 5,300', '3%'],
              ].map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{r[0]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r[1]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontSize: 11, color: 'var(--accent)', width: 60, fontWeight: 700 }}>{r[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function ReportsPurchase() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="PZ documents" value="142" sub="MTD · all booked to wFirma" />
        <StatTile label="Total purchase value" value="PLN 124,800" sub="Net of duty & shipping" />
        <StatTile label="Duty paid (A00)" value="PLN 7,200" sub="Avg 5.8% on dutiable goods" accent="var(--accent)" />
        <StatTile label="VAT recoverable" value="PLN 28,704" sub="23% · settled in declaration" accent="var(--badge-green-text)" />
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Top suppliers (MTD)</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Supplier', 'Country', 'Shipments', 'Net value', 'Duty', 'Avg clearance'].map(h => <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
          <tbody>
            {[
              ['Bonacchi Atelier',  'IT', '24', 'PLN 48,200', 'PLN 1,205', '1.8d'],
              ['Maison de Vicenza', 'IT', '18', 'PLN 32,400', 'PLN 810',   '2.1d'],
              ['Geneva Goldworks',  'CH', '12', 'PLN 28,800', 'PLN 720',   '4.2d'],
              ['Antwerp Stones',    'BE', '8',  'PLN 9,600',  'PLN 0',     '1.4d'],
              ['Paris Diamonds',    'FR', '6',  'PLN 5,800',  'PLN 0',     '1.6d'],
            ].map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                {r.map((c, j) => <td key={j} style={{ padding: '10px 12px', fontSize: 12, color: j === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: j === 0 ? 600 : 400, fontFamily: j >= 3 && j <= 4 ? 'monospace' : 'inherit', textAlign: j >= 3 ? 'right' : 'left' }}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ReportsShipping() {
  const carriers = [['DHL', 84, 60], ['FedEx', 32, 25], ['UPS', 18, 13], ['Other', 8, 6]];
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Shipments" value="142" sub="MTD · 138 cleared" />
        <StatTile label="On-time clearance" value="92%" sub="Target 90% · met" accent="var(--badge-green-text)" />
        <StatTile label="Avg clearance time" value="2.1d" sub="vs target ≤ 3d" accent="var(--badge-green-text)" />
        <StatTile label="Held / blocked" value="2" sub="Manual review queue" accent="var(--accent)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }} className="grid-2col">
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 14 }}>By carrier</div>
          {carriers.map(c => (
            <div key={c[0]} style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{c[0]}</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{c[1]} shipments · {c[2]}%</span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-subtle)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${c[2]}%`, height: '100%', background: 'var(--accent)' }} />
              </div>
            </div>
          ))}
        </Card>
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Tracking export</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 12 }}>
            Export per-shipment tracking history (status, location, dwell time at each leg) for all carriers in the selected period. Includes failed-clearance reason codes.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="gold" small>↓ Export tracking CSV</Btn>
            <Btn variant="outline" small>↓ Export PDF</Btn>
          </div>
          <div style={{ marginTop: 16, padding: 12, background: 'var(--bg-subtle)', borderRadius: 4, fontSize: 11, color: 'var(--text-3)' }}>
            Last export: yesterday 17:42 · 142 rows · sent to ops@estrella-jewels.pl
          </div>
        </Card>
      </div>
    </div>
  );
}

function ReportsDuty() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Duty paid" value="PLN 7,200" sub="A00 · MTD" accent="var(--accent)" />
        <StatTile label="VAT (import)" value="PLN 28,704" sub="23% · recoverable" accent="var(--badge-green-text)" />
        <StatTile label="Avg duty rate" value="2.6%" sub="weighted · all dutiable" />
        <StatTile label="Tariff codes used" value="9" sub="HS 6-digit distinct" />
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Duty by HS code (MTD)</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['HS code', 'Description', 'Shipments', 'Net value', 'Duty rate', 'Duty paid'].map(h => <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
          <tbody>
            {[
              ['7113.19.00', 'Articles of jewellery, precious metal',          '68', 'PLN 64,200', '2.5%', 'PLN 1,605'],
              ['7113.11.00', 'Articles of jewellery, silver',                  '34', 'PLN 28,400', '2.5%', 'PLN 710'],
              ['7117.19.00', 'Imitation jewellery, base metal',                '12', 'PLN 4,800',  '4.0%', 'PLN 192'],
              ['7102.39.00', 'Diamonds, non-industrial, worked',               '8',  'PLN 14,200', '0.0%', 'PLN 0'],
              ['7103.91.00', 'Rubies, sapphires, emeralds — worked',           '6',  'PLN 8,400',  '0.0%', 'PLN 0'],
            ].map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                {r.map((c, j) => <td key={j} style={{ padding: '10px 12px', fontSize: 12, fontFamily: j === 0 ? 'monospace' : 'inherit', color: j === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: j === 0 ? 600 : 400, textAlign: j >= 2 ? 'right' : 'left' }}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

Object.assign(window, {
  DhlCustomsPage,
  AccountingPage,
  EmailQueuePage,
  AiBridgePage,
  ActionProposalsPage,
  ReportsPage,        // overrides the old one
  // small helpers also exported in case other files want them
  Tabs, StatTile, Pill,
});
