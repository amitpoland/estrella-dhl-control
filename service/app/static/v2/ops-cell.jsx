// ── Operations Cell — surfaces backend modules that currently have no UI.
// Built on top of system_inventory_and_ui_plan.md (Section 4 — UI Gap Analysis).
//
// Modules covered:
//   1. WarehouseScannerPage       — POST /api/v1/warehouse/scan, mobile-first
//   2. ReservationCellPage        — Warehouse Audit + Sales Linkage + wFirma Preview gate
//   3. WfirmaMappingPage          — GET/PUT /api/v1/wfirma/customers, /products, capabilities
//   4. DiagnosticsPage            — system health, storage, locks, CLI tool runners
//   5. LabelPrintPage             — GET /api/v1/packing/{id}/barcode + ZPL print queue
//   6. DocumentExtractionPage     — per-batch extracted_fields registry
//
// All actionable writes are wireframe-disabled with status chips indicating API state.

// ──────────────────────────────────────────────────────────────────────
// SHARED ATOMS — status chip, mini sparkline, gate banner
// ──────────────────────────────────────────────────────────────────────

function StatusChip({ kind, children }) {
  const PALETTE = {
    ready:    { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)',  dot: '#1AA960' },
    pending:  { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)',  dot: '#C09020' },
    blocked:  { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)',    dot: '#B82820' },
    info:     { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)',   dot: '#2868C8' },
    neutral:  { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)',dot: '#7E8AA0' },
    api:      { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)',   dot: '#2868C8' },
    cli:      { bg: 'var(--badge-purple-bg)',  fg: 'var(--badge-purple-text)',  bd: 'var(--badge-purple-border)', dot: '#7848B8' },
  };
  const c = PALETTE[kind] || PALETTE.neutral;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      borderRadius: 4, padding: '2px 7px', fontSize: 10, fontWeight: 600,
      letterSpacing: '0.02em', whiteSpace: 'nowrap',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: c.dot }} />
      {children}
    </span>
  );
}

function GateBanner({ kind, title, children }) {
  const PALETTE = {
    open:    { bg: 'var(--badge-green-bg)',  fg: 'var(--badge-green-text)',  bd: 'var(--badge-green-border)',  icon: '✓' },
    closed:  { bg: 'var(--badge-red-bg)',    fg: 'var(--badge-red-text)',    bd: 'var(--badge-red-border)',    icon: '✕' },
    partial: { bg: 'var(--badge-amber-bg)',  fg: 'var(--badge-amber-text)',  bd: 'var(--badge-amber-border)',  icon: '!' },
  };
  const c = PALETTE[kind] || PALETTE.partial;
  return (
    <div style={{
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      borderRadius: 8, padding: '12px 16px', display: 'flex', gap: 14, alignItems: 'flex-start',
    }}>
      <div style={{
        width: 26, height: 26, borderRadius: '50%', background: c.fg, color: c.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 13, fontWeight: 700, flexShrink: 0,
      }}>{c.icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 11, lineHeight: 1.5, opacity: 0.92 }}>{children}</div>
      </div>
    </div>
  );
}

function MetricTile({ label, value, sub, tone, mono }) {
  const TONE = {
    green: 'var(--badge-green-text)',
    amber: 'var(--badge-amber-text)',
    red:   'var(--badge-red-text)',
    blue:  'var(--badge-blue-text)',
    text:  'var(--text)',
  };
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
      padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{
        fontFamily: mono ? 'ui-monospace, monospace' : 'inherit',
        fontSize: 22, fontWeight: 700, color: TONE[tone] || TONE.text, lineHeight: 1.1,
      }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{sub}</div>}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// 1. WAREHOUSE SCANNER — mobile-first scan/move/dispatch
// ──────────────────────────────────────────────────────────────────────

function WarehouseScannerPage() {
  const [scanCode, setScanCode] = React.useState('');
  const [action, setAction] = React.useState('RECV');
  const [location, setLocation] = React.useState('WH-A-12');
  const [feed, setFeed] = React.useState([
    { ts: '14:02:18', code: 'EJP-26-27-015-006', act: 'RECV', loc: 'WH-A-12', batch: 'EJP-26-27-015', ok: true,  note: 'Inbound from DHL Express' },
    { ts: '14:01:55', code: 'EJP-26-27-015-005', act: 'RECV', loc: 'WH-A-12', batch: 'EJP-26-27-015', ok: true,  note: 'Inbound from DHL Express' },
    { ts: '14:01:33', code: 'EJP-26-27-015-004', act: 'RECV', loc: 'WH-A-12', batch: 'EJP-26-27-015', ok: true,  note: 'Inbound from DHL Express' },
    { ts: '13:48:02', code: 'EJP-26-26-091-002', act: 'DISP', loc: 'WH-B-04', batch: 'EJP-26-26-091', ok: false, note: 'Already dispatched 2 days ago' },
    { ts: '13:45:11', code: 'EJP-26-27-014-003', act: 'MOVE', loc: 'WH-A-12 → WH-B-08', batch: 'EJP-26-27-014', ok: true, note: 'Manual move' },
  ]);

  const ACTIONS = [
    { id: 'RECV', label: 'Receive', hint: 'Inbound from carrier' },
    { id: 'MOVE', label: 'Move',    hint: 'Internal relocation' },
    { id: 'DISP', label: 'Dispatch',hint: 'Outbound to client' },
    { id: 'RTRN', label: 'Return',  hint: 'Customer return / RMA' },
  ];

  const inputRef = React.useRef(null);
  React.useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = () => {
    if (!scanCode.trim()) return;
    const entry = {
      ts: new Date().toTimeString().slice(0, 8),
      code: scanCode.trim(),
      act: action,
      loc: location,
      batch: 'EJP-26-27-015',
      ok: true,
      note: ACTIONS.find(a => a.id === action)?.hint || '',
    };
    setFeed(f => [entry, ...f].slice(0, 30));
    setScanCode('');
    inputRef.current?.focus();
  };

  const recvCount  = feed.filter(f => f.act === 'RECV' && f.ok).length;
  const dispCount  = feed.filter(f => f.act === 'DISP' && f.ok).length;
  const moveCount  = feed.filter(f => f.act === 'MOVE' && f.ok).length;
  const errorCount = feed.filter(f => !f.ok).length;

  return (
    <div style={{ padding: '0 32px 40px', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* KPI strip */}
      <div className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <MetricTile label="Received today" value={recvCount}  sub="Inbound scans"     tone="green" />
        <MetricTile label="Dispatched"     value={dispCount}  sub="Outbound scans"    tone="blue" />
        <MetricTile label="Internal moves" value={moveCount}  sub="Within warehouse"  tone="text" />
        <MetricTile label="Errors / blocks" value={errorCount} sub="Need attention"   tone={errorCount ? 'red' : 'text'} />
      </div>

      {/* Scan composer + Recent feed — 2-col on desktop, stack on phone */}
      <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 16 }}>

        {/* Composer */}
        <Card style={{ padding: 18 }}>
          <SectionHeader icon="⊡" title="Scan / Move / Dispatch" subtitle="Scanner input — large hit area, mobile-safe" />

          <div style={{ marginTop: 14 }}>
            <FormField label="Scan code" hint="Auto-focused. Hit Enter to submit.">
              <input
                ref={inputRef}
                value={scanCode}
                onChange={e => setScanCode(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submit()}
                placeholder="EJP-26-27-015-001"
                style={{
                  width: '100%', padding: '14px 16px', fontSize: 18,
                  fontFamily: 'ui-monospace, monospace', fontWeight: 600,
                  background: 'var(--bg-subtle)', border: '2px solid var(--accent)',
                  borderRadius: 8, color: 'var(--text)', outline: 'none', letterSpacing: '0.02em',
                }}
              />
            </FormField>

            <FormField label="Action">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                {ACTIONS.map(a => (
                  <button key={a.id} onClick={() => setAction(a.id)} style={{
                    padding: '12px 10px', borderRadius: 6, cursor: 'pointer',
                    border: action === a.id ? '2px solid var(--accent)' : '1px solid var(--border)',
                    background: action === a.id ? 'var(--accent-subtle)' : 'var(--card)',
                    color: 'var(--text)', textAlign: 'left',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>{a.label}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{a.hint}</div>
                  </button>
                ))}
              </div>
            </FormField>

            <FormField label="Location">
              <Select value={location} onChange={e => setLocation(e.target.value)}>
                <option>WH-A-12</option><option>WH-A-13</option><option>WH-B-04</option>
                <option>WH-B-08</option><option>WH-SAMPLES</option><option>WH-RETURNS</option>
              </Select>
            </FormField>

            <Btn variant="gold" onClick={submit} style={{ width: '100%', padding: '14px 16px', fontSize: 14, fontWeight: 700 }}>
              Submit Scan
            </Btn>

            <div style={{ marginTop: 10, padding: '8px 10px', background: 'var(--bg-subtle)', borderRadius: 6,
              display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, color: 'var(--text-3)' }}>
              <StatusChip kind="api">API</StatusChip>
              <code style={{ fontFamily: 'ui-monospace, monospace' }}>POST /api/v1/warehouse/scan</code>
            </div>
          </div>
        </Card>

        {/* Live feed */}
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Recent activity</div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Last {feed.length} scans · auto-scrolls</div>
            </div>
            <StatusChip kind="info">Live</StatusChip>
          </div>

          <div style={{ maxHeight: 460, overflowY: 'auto' }}>
            {feed.map((f, i) => (
              <div key={i} style={{
                padding: '10px 18px', borderBottom: '1px solid var(--border-subtle)',
                display: 'grid', gridTemplateColumns: '60px 1fr auto', gap: 12, alignItems: 'center',
                background: f.ok ? 'var(--card)' : 'var(--badge-red-bg)',
              }}>
                <div style={{ fontSize: 10, fontFamily: 'ui-monospace, monospace', color: 'var(--text-3)' }}>{f.ts}</div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <code style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{f.code}</code>
                    <StatusChip kind={f.act === 'DISP' ? 'info' : f.act === 'MOVE' ? 'neutral' : 'ready'}>{f.act}</StatusChip>
                    <span style={{ fontSize: 10, color: 'var(--text-3)' }}>· {f.loc}</span>
                  </div>
                  <div style={{ fontSize: 10, color: f.ok ? 'var(--text-3)' : 'var(--badge-red-text)', marginTop: 2 }}>{f.note}</div>
                </div>
                <StatusChip kind={f.ok ? 'ready' : 'blocked'}>{f.ok ? 'OK' : 'Rejected'}</StatusChip>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Quick location overview */}
      <Card style={{ padding: 18 }}>
        <SectionHeader icon="⊞" title="Location occupancy" subtitle="Snapshot of current_location table" />
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8 }}>
          {[
            { loc: 'WH-A-12', count: 14, cap: 20 },
            { loc: 'WH-A-13', count: 9,  cap: 20 },
            { loc: 'WH-B-04', count: 18, cap: 20 },
            { loc: 'WH-B-08', count: 3,  cap: 20 },
            { loc: 'WH-SAMPLES', count: 22, cap: 30 },
            { loc: 'WH-RETURNS', count: 5,  cap: 15 },
          ].map(l => {
            const pct = (l.count / l.cap) * 100;
            const tone = pct > 85 ? 'red' : pct > 60 ? 'amber' : 'green';
            return (
              <div key={l.loc} style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
                <div style={{ fontSize: 11, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{l.loc}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginTop: 4 }}>{l.count}<span style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 400 }}> / {l.cap}</span></div>
                <div style={{ height: 4, background: 'var(--border-subtle)', borderRadius: 2, marginTop: 6, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: pct + '%', background: tone === 'red' ? '#B82820' : tone === 'amber' ? '#C09020' : '#1AA960' }} />
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// 2. RESERVATION CELL — unified warehouse audit + sales linkage + wfirma preview gate
// ──────────────────────────────────────────────────────────────────────

function ReservationCellPage() {
  const [batch, setBatch] = React.useState('EJP-26-27-015');
  const [stage, setStage] = React.useState('audit');  // audit | linkage | preview

  const auditClean = false;
  const linkageClean = true;
  const previewReady = false;
  const wfirmaConfigGreen = false;

  const STAGES = [
    { id: 'audit',   label: 'Warehouse Audit', sub: 'Gap detection',   icon: '⊞', state: auditClean   ? 'ready' : 'blocked', endpoint: 'GET /api/v1/warehouse/{id}/audit-summary/{batch_id}' },
    { id: 'linkage', label: 'Sales Linkage',   sub: 'Sales → Packing', icon: '⊕', state: linkageClean ? 'ready' : 'pending', endpoint: 'GET /api/v1/sales/linkage/{batch_id}' },
    { id: 'preview', label: 'wFirma Preview',  sub: 'Reservation draft',icon: '⊛',state: previewReady ? 'ready' : 'blocked', endpoint: 'GET /api/v1/wfirma/reservation-preview/{batch_id}' },
  ];

  const gateOpen = auditClean && linkageClean && previewReady && wfirmaConfigGreen;

  return (
    <div style={{ padding: '0 32px 40px', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Top toolbar — batch selector + gate */}
      <Card style={{ padding: 16, display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '0 0 auto' }}>
          <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Active batch</div>
          <Select value={batch} onChange={e => setBatch(e.target.value)} style={{ marginTop: 4, fontFamily: 'ui-monospace, monospace', fontSize: 13, fontWeight: 700 }}>
            <option>EJP-26-27-015</option><option>EJP-26-27-014</option><option>EJP-26-27-013</option>
          </Select>
        </div>
        <div style={{ flex: 1, minWidth: 240, padding: '10px 14px', background: 'var(--bg-subtle)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Reservation gate</div>
          <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 10 }}>
            <StatusChip kind={gateOpen ? 'ready' : 'blocked'}>{gateOpen ? 'OPEN — ready to create' : 'BLOCKED'}</StatusChip>
            {!gateOpen && <span style={{ fontSize: 10, color: 'var(--text-2)' }}>3 prerequisites must pass</span>}
          </div>
        </div>
        <Btn variant="gold" disabled={!gateOpen}>Create Reservation in wFirma</Btn>
      </Card>

      {/* Stage stepper */}
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          {STAGES.map((s, i) => (
            <button key={s.id} onClick={() => setStage(s.id)} style={{
              flex: 1, padding: '14px 18px', border: 'none', textAlign: 'left',
              background: stage === s.id ? 'var(--accent-subtle)' : 'var(--card)',
              borderBottom: stage === s.id ? '2px solid var(--accent)' : '2px solid transparent',
              borderRight: i < STAGES.length - 1 ? '1px solid var(--border-subtle)' : 'none',
              cursor: 'pointer', display: 'flex', gap: 12, alignItems: 'center',
            }}>
              <div style={{
                width: 32, height: 32, borderRadius: 6, fontSize: 16,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: stage === s.id ? 'var(--accent)' : 'var(--bg-subtle)',
                color: stage === s.id ? 'var(--accent-text)' : 'var(--accent)',
              }}>{s.icon}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 9, color: 'var(--text-3)', fontWeight: 600 }}>{`STAGE ${i + 1}`}</span>
                  <StatusChip kind={s.state}>{s.state === 'ready' ? 'CLEAN' : s.state === 'pending' ? 'PARTIAL' : 'ISSUES'}</StatusChip>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginTop: 2 }}>{s.label}</div>
                <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{s.sub}</div>
              </div>
            </button>
          ))}
        </div>

        <div style={{ padding: 20 }}>
          {stage === 'audit'   && <AuditPanel batch={batch} />}
          {stage === 'linkage' && <LinkagePanel batch={batch} />}
          {stage === 'preview' && <PreviewPanel batch={batch} configGreen={wfirmaConfigGreen} />}
        </div>
      </Card>
    </div>
  );
}

function AuditPanel({ batch }) {
  const missing = [
    { code: 'EJP-26-27-015-007', design: 'CSTR07599', expected: 'WH-A-12', lastSeen: 'never',           note: 'Never scanned on receipt' },
    { code: 'EJP-26-27-015-009', design: 'CSTR07601', expected: 'WH-A-12', lastSeen: '2026-04-29 11:02', note: 'Receipt scan timed out' },
  ];
  const stuck = [
    { code: 'EJP-26-26-091-014', design: 'CSTR07410', loc: 'WH-A-12', sinceDays: 47, note: 'No movement >45d' },
  ];
  const invalid = [
    { code: 'EJP-26-27-015-002', from: 'DISP', to: 'DISP', when: '2026-05-09 13:48', note: 'Duplicate dispatch attempt' },
  ];
  const orphans = [
    { code: 'EJP-26-27-015-099', loc: 'WH-A-12', when: '2026-05-04 08:11', note: 'Scan code not in packing list' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <GateBanner kind="closed" title="Warehouse audit: 4 issues blocking reservation">
        Resolve missing scans (2), stuck inventory (1), invalid flows (1), and orphan scans (1) before continuing.
      </GateBanner>

      <div className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <MetricTile label="Expected" value="9"  sub="From packing"   tone="text" />
        <MetricTile label="Received" value="7"  sub="78% complete"   tone="amber" />
        <MetricTile label="Missing"  value="2"  sub="Critical gap"   tone="red" />
        <MetricTile label="Orphans"  value="1"  sub="Unknown codes"  tone="amber" />
      </div>

      <AuditTable title="Missing scans"   rows={missing} cols={['Code','Design','Expected loc','Last seen','Note']} />
      <AuditTable title="Stuck inventory" rows={stuck}   cols={['Code','Design','Location','Days idle','Note']} />
      <AuditTable title="Invalid flows"   rows={invalid} cols={['Code','From','To','When','Note']} />
      <AuditTable title="Orphan scans"    rows={orphans} cols={['Code','Location','When','Note']} />

      <div style={{ display: 'flex', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
        <Btn variant="outline" small>Refresh audit</Btn>
        <Btn variant="outline" small>Export CSV</Btn>
        <Btn variant="outline" small>Open Scanner</Btn>
        <StatusChip kind="api">GET /api/v1/warehouse/{`{wh_id}`}/audit-summary/{`{batch_id}`}</StatusChip>
      </div>
    </div>
  );
}

function AuditTable({ title, rows, cols }) {
  if (rows.length === 0) {
    return (
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{title}</div>
        <div style={{ padding: 16, border: '1px dashed var(--border)', borderRadius: 6, textAlign: 'center', fontSize: 11, color: 'var(--text-3)' }}>None — clean</div>
      </div>
    );
  }
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{title} <span style={{ color: 'var(--badge-red-text)' }}>({rows.length})</span></div>
      <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {cols.map(c => <th key={c} style={{ textAlign: 'left', padding: '8px 12px', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border)' }}>{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: i ? '1px solid var(--border-subtle)' : 'none' }}>
                {Object.values(r).map((v, j) => (
                  <td key={j} style={{ padding: '8px 12px', color: 'var(--text)', fontFamily: j === 0 ? 'ui-monospace, monospace' : 'inherit' }}>{String(v)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LinkagePanel({ batch }) {
  const clients = [
    {
      name: 'Bijoux Maison Paris', short: 'BMP', sales_doc: 'INV-2026-0411', lines: [
        { sku: 'CSTR07596', design: 'Solitaire 1.0ct', qty: 2, pack_match: true,  stock_ok: true,  note: '' },
        { sku: 'CSTR07597', design: 'Halo bracelet',   qty: 1, pack_match: true,  stock_ok: true,  note: '' },
        { sku: 'CSTR07599', design: 'Pavé pendant',    qty: 1, pack_match: true,  stock_ok: false, note: 'Awaiting warehouse receipt' },
      ],
    },
    {
      name: 'Goldhaus Berlin', short: 'GHB', sales_doc: 'INV-2026-0412', lines: [
        { sku: 'CSTR07598', design: 'Chain 18k',       qty: 3, pack_match: true,  stock_ok: true,  note: '' },
      ],
    },
    {
      name: 'Atelier Lyon', short: 'ATL', sales_doc: 'INV-2026-0413', lines: [
        { sku: 'CSTR07601', design: 'Stud earrings',   qty: 4, pack_match: false, stock_ok: false, note: 'SKU not in packing list — check identity mapping' },
      ],
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <GateBanner kind="partial" title="Sales linkage: 3 clients, 1 unresolved">
        4 of 5 sales lines resolved cleanly. 1 line failed packing match — needs identity mapping or override.
      </GateBanner>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {clients.map(c => {
          const unresolved = c.lines.filter(l => !l.pack_match || !l.stock_ok).length;
          return (
            <div key={c.short} style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ width: 30, height: 30, borderRadius: 6, background: 'var(--accent)', color: 'var(--accent-text)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{c.short}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{c.name}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)' }}>Sales doc <code style={{ fontFamily: 'ui-monospace, monospace' }}>{c.sales_doc}</code> · {c.lines.length} line{c.lines.length !== 1 ? 's' : ''}</div>
                </div>
                <StatusChip kind={unresolved ? 'pending' : 'ready'}>{unresolved ? `${unresolved} unresolved` : 'CLEAN'}</StatusChip>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ background: 'var(--card)' }}>
                    {['SKU','Design','Qty','Packing match','Stock','Note'].map(h => <th key={h} style={{ textAlign: 'left', padding: '8px 16px', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border-subtle)' }}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {c.lines.map((l, i) => (
                    <tr key={i} style={{ borderTop: i ? '1px solid var(--border-subtle)' : 'none' }}>
                      <td style={{ padding: '8px 16px', fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{l.sku}</td>
                      <td style={{ padding: '8px 16px', color: 'var(--text)' }}>{l.design}</td>
                      <td style={{ padding: '8px 16px', color: 'var(--text)' }}>{l.qty}</td>
                      <td style={{ padding: '8px 16px' }}><StatusChip kind={l.pack_match ? 'ready' : 'blocked'}>{l.pack_match ? 'Matched' : 'No match'}</StatusChip></td>
                      <td style={{ padding: '8px 16px' }}><StatusChip kind={l.stock_ok ? 'ready' : 'pending'}>{l.stock_ok ? 'In stock' : 'Awaiting'}</StatusChip></td>
                      <td style={{ padding: '8px 16px', color: 'var(--text-3)', fontSize: 10 }}>{l.note || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Btn variant="outline" small>Refresh linkage</Btn>
        <Btn variant="outline" small>Open Identity / Mapping</Btn>
        <StatusChip kind="api">GET /api/v1/sales/linkage/{`{batch_id}`}</StatusChip>
      </div>
    </div>
  );
}

function PreviewPanel({ batch, configGreen }) {
  const drafts = [
    {
      client: 'Bijoux Maison Paris', wfirmaId: 'WF-CUST-104', match: true,
      lines: [
        { code: 'EJL/26-27/015-1', wfirmaGood: 'WF-PROD-9921', name: 'Solitaire 1.0ct',  qty: 2, price: 4250.00, stock: 3 },
        { code: 'EJL/26-27/015-2', wfirmaGood: 'WF-PROD-9922', name: 'Halo bracelet',    qty: 1, price: 1820.00, stock: 1 },
        { code: 'EJL/26-27/015-3', wfirmaGood: null,           name: 'Pavé pendant',     qty: 1, price: 990.00,  stock: 0 },
      ],
    },
    {
      client: 'Goldhaus Berlin', wfirmaId: 'WF-CUST-108', match: true,
      lines: [
        { code: 'EJL/26-27/015-4', wfirmaGood: 'WF-PROD-9931', name: 'Chain 18k',        qty: 3, price: 670.00,  stock: 12 },
      ],
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      <GateBanner kind={configGreen ? 'partial' : 'closed'} title={configGreen ? 'Preview ready — gate held by upstream issues' : 'wFirma config not green — preview only'}>
        {configGreen
          ? 'Configuration passes all 10 checks. Reservation create remains disabled until warehouse audit + sales linkage are clean.'
          : 'check_wfirma_config has not passed all 10 checks. Run diagnostic from System Diagnostics page before creating reservations.'}
      </GateBanner>

      <div className="responsive-grid-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        <StatusChipRow label="WFIRMA_APP_KEY"        ok={true}  />
        <StatusChipRow label="WFIRMA_API_LOGIN"      ok={true}  />
        <StatusChipRow label="WFIRMA_API_PASSWORD"   ok={true}  />
        <StatusChipRow label="WFIRMA_COMPANY_ID"     ok={true}  />
        <StatusChipRow label="WFIRMA_WAREHOUSE_ID"   ok={false} />
        <StatusChipRow label="reservation.write scope" ok={false}/>
      </div>

      {drafts.map(d => {
        const oneMissing = d.lines.some(l => !l.wfirmaGood);
        return (
          <div key={d.client} style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>{d.client}</div>
                <div style={{ fontSize: 10, color: 'var(--text-3)' }}>wFirma customer <code style={{ fontFamily: 'ui-monospace, monospace' }}>{d.wfirmaId}</code></div>
              </div>
              <StatusChip kind={oneMissing ? 'pending' : 'ready'}>{oneMissing ? 'Product mapping needed' : 'Ready'}</StatusChip>
              <code style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'ui-monospace, monospace' }}>warehouse_document_r</code>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>
                  {['Product code','wFirma good_id','Name','Qty','Unit price (PLN)','Stock'].map(h => <th key={h} style={{ textAlign: 'left', padding: '8px 16px', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border-subtle)' }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {d.lines.map((l, i) => (
                  <tr key={i} style={{ borderTop: i ? '1px solid var(--border-subtle)' : 'none' }}>
                    <td style={{ padding: '8px 16px', fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{l.code}</td>
                    <td style={{ padding: '8px 16px' }}>{l.wfirmaGood ? <code style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{l.wfirmaGood}</code> : <StatusChip kind="blocked">No mapping</StatusChip>}</td>
                    <td style={{ padding: '8px 16px', color: 'var(--text)' }}>{l.name}</td>
                    <td style={{ padding: '8px 16px', color: 'var(--text)' }}>{l.qty}</td>
                    <td style={{ padding: '8px 16px', color: 'var(--text)', textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>{l.price.toFixed(2)}</td>
                    <td style={{ padding: '8px 16px' }}><StatusChip kind={l.stock >= l.qty ? 'ready' : 'blocked'}>{l.stock}</StatusChip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Btn variant="outline" small>Refresh preview</Btn>
        <Btn variant="outline" small>Open wFirma Mapping</Btn>
        <Btn variant="outline" small>Export JSON</Btn>
        <StatusChip kind="api">GET /api/v1/wfirma/reservation-preview/{`{batch_id}`}</StatusChip>
        <StatusChip kind="blocked">POST /reservations/create — NOT BUILT</StatusChip>
      </div>
    </div>
  );
}

function StatusChipRow({ label, ok }) {
  return (
    <div style={{
      padding: '8px 12px', background: 'var(--bg-subtle)', borderRadius: 6,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
    }}>
      <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 10.5, color: 'var(--text)' }}>{label}</code>
      <StatusChip kind={ok ? 'ready' : 'blocked'}>{ok ? '✓' : '✗'}</StatusChip>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// 3. WFIRMA MAPPING — customers + products
// ──────────────────────────────────────────────────────────────────────

function WfirmaMappingPage() {
  const [tab, setTab] = React.useState('customers');

  const customers = [
    { name: 'Bijoux Maison Paris', wfirmaId: 'WF-CUST-104', vat: 'FR12345678901', country: 'FR', match: true,  lastSync: '2026-05-08 09:12' },
    { name: 'Goldhaus Berlin',     wfirmaId: 'WF-CUST-108', vat: 'DE987654321',   country: 'DE', match: true,  lastSync: '2026-05-08 09:12' },
    { name: 'Atelier Lyon',        wfirmaId: null,          vat: 'FR55667788990', country: 'FR', match: false, lastSync: '—' },
    { name: 'Joaillerie Geneva',   wfirmaId: 'WF-CUST-112', vat: 'CHE112233445',  country: 'CH', match: true,  lastSync: '2026-05-08 09:12' },
  ];

  const products = [
    { code: 'EJL/26-27/015-1', wfirmaGood: 'WF-PROD-9921', name: 'Solitaire 1.0ct',  unit: 'piece', vat: '23%', stock: 3,  sync: 'ok'      },
    { code: 'EJL/26-27/015-2', wfirmaGood: 'WF-PROD-9922', name: 'Halo bracelet',    unit: 'piece', vat: '23%', stock: 1,  sync: 'ok'      },
    { code: 'EJL/26-27/015-3', wfirmaGood: null,           name: 'Pavé pendant',     unit: 'piece', vat: '23%', stock: 0,  sync: 'missing' },
    { code: 'EJL/26-27/015-4', wfirmaGood: 'WF-PROD-9931', name: 'Chain 18k',        unit: 'piece', vat: '23%', stock: 12, sync: 'ok'      },
    { code: 'EJL/26-27/015-5', wfirmaGood: 'WF-PROD-9932', name: 'Stud earrings',    unit: 'piece', vat: '23%', stock: 4,  sync: 'stale'   },
  ];

  return (
    <div style={{ padding: '0 32px 40px', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Capability strip */}
      <Card style={{ padding: 16 }}>
        <SectionHeader icon="◉" title="Capability strip" subtitle="GET /api/v1/wfirma/capabilities" />
        <div className="responsive-grid-3" style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          <CapPill label="customers.read"     ok={true}  />
          <CapPill label="customers.write"    ok={true}  />
          <CapPill label="goods.read"         ok={true}  />
          <CapPill label="goods.write"        ok={false} />
          <CapPill label="warehouse.read"     ok={true}  />
          <CapPill label="reservation.write"  ok={false} warn />
        </div>
        <div style={{ marginTop: 12, padding: '8px 12px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-amber-text)' }}>
          <strong>Blocking reasons:</strong> WFIRMA_WAREHOUSE_ID missing · reservation.write scope not granted on credentials
        </div>
      </Card>

      {/* Tabs */}
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          {[
            { id: 'customers', label: 'Customers',  count: customers.length, unresolved: customers.filter(c => !c.match).length },
            { id: 'products',  label: 'Products',   count: products.length,  unresolved: products.filter(p => !p.wfirmaGood || p.sync === 'stale').length },
          ].map((t, i) => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: '12px 20px', border: 'none', cursor: 'pointer',
              background: tab === t.id ? 'var(--card)' : 'var(--bg-subtle)',
              borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
              borderRight: i === 0 ? '1px solid var(--border-subtle)' : 'none',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{t.label}</span>
              <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{t.count}</span>
              {t.unresolved > 0 && <StatusChip kind="pending">{t.unresolved} pending</StatusChip>}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <div style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <input placeholder="Filter…" style={{ padding: '6px 10px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--card)', color: 'var(--text)' }} />
            <Btn variant="outline" small>Run diagnostic</Btn>
          </div>
        </div>

        {tab === 'customers' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['Client name','wFirma ID','VAT ID','Country','Match status','Last sync',''].map(h => <th key={h} style={{ textAlign: 'left', padding: '10px 16px', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {customers.map((c, i) => (
                <tr key={i} style={{ borderTop: i ? '1px solid var(--border-subtle)' : 'none' }}>
                  <td style={{ padding: '10px 16px', color: 'var(--text)', fontWeight: 600 }}>{c.name}</td>
                  <td style={{ padding: '10px 16px' }}>{c.wfirmaId ? <code style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{c.wfirmaId}</code> : <span style={{ color: 'var(--text-3)' }}>—</span>}</td>
                  <td style={{ padding: '10px 16px', fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{c.vat}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--text)' }}>{c.country}</td>
                  <td style={{ padding: '10px 16px' }}><StatusChip kind={c.match ? 'ready' : 'pending'}>{c.match ? 'Matched' : 'No mapping'}</StatusChip></td>
                  <td style={{ padding: '10px 16px', color: 'var(--text-3)', fontFamily: 'ui-monospace, monospace', fontSize: 10 }}>{c.lastSync}</td>
                  <td style={{ padding: '10px 16px', textAlign: 'right' }}><Btn variant="ghost" small>{c.match ? 'Edit' : 'Map'}</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'products' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['Product code','wFirma good_id','Polish name','Unit','VAT','Stock','Sync',''].map(h => <th key={h} style={{ textAlign: 'left', padding: '10px 16px', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {products.map((p, i) => (
                <tr key={i} style={{ borderTop: i ? '1px solid var(--border-subtle)' : 'none' }}>
                  <td style={{ padding: '10px 16px', fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{p.code}</td>
                  <td style={{ padding: '10px 16px' }}>{p.wfirmaGood ? <code style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text)' }}>{p.wfirmaGood}</code> : <StatusChip kind="blocked">Missing</StatusChip>}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--text)' }}>{p.name}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--text)' }}>{p.unit}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--text)' }}>{p.vat}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--text)' }}>{p.stock}</td>
                  <td style={{ padding: '10px 16px' }}>
                    <StatusChip kind={p.sync === 'ok' ? 'ready' : p.sync === 'stale' ? 'pending' : 'blocked'}>
                      {p.sync === 'ok' ? 'Synced' : p.sync === 'stale' ? 'Stale' : 'Missing'}
                    </StatusChip>
                  </td>
                  <td style={{ padding: '10px 16px', textAlign: 'right' }}><Btn variant="ghost" small>{p.wfirmaGood ? 'Edit' : 'Map'}</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* API footer */}
      <Card style={{ padding: 14 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Wired endpoints</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          <StatusChip kind="api">GET /api/v1/wfirma/capabilities</StatusChip>
          <StatusChip kind="api">GET /api/v1/wfirma/customers</StatusChip>
          <StatusChip kind="api">PUT /api/v1/wfirma/customers/{`{name}`}</StatusChip>
          <StatusChip kind="api">GET /api/v1/wfirma/products</StatusChip>
          <StatusChip kind="api">PUT /api/v1/wfirma/products/{`{code}`}</StatusChip>
        </div>
      </Card>
    </div>
  );
}

function CapPill({ label, ok, warn }) {
  return (
    <div style={{
      padding: '8px 12px', background: 'var(--bg-subtle)', borderRadius: 6,
      border: `1px solid ${ok ? 'var(--badge-green-border)' : warn ? 'var(--badge-amber-border)' : 'var(--badge-red-border)'}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
    }}>
      <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text)' }}>{label}</code>
      <span style={{ fontSize: 13, fontWeight: 700, color: ok ? 'var(--badge-green-text)' : warn ? 'var(--badge-amber-text)' : 'var(--badge-red-text)' }}>{ok ? '✓' : warn ? '⚠' : '✗'}</span>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// 4. DIAGNOSTICS — system health, storage, locks, CLI runners
// ──────────────────────────────────────────────────────────────────────

function DiagnosticsPage() {
  const [running, setRunning] = React.useState(null);

  const healthChecks = [
    { name: 'database.packing',         ok: true,  ms: 12  },
    { name: 'database.documents',       ok: true,  ms: 9   },
    { name: 'database.warehouse',       ok: true,  ms: 14  },
    { name: 'database.wfirma',          ok: true,  ms: 11  },
    { name: 'database.tracking',        ok: true,  ms: 8   },
    { name: 'storage.locks_table',      ok: true,  ms: 6   },
    { name: 'smtp.outbound',            ok: true,  ms: 142 },
    { name: 'imap.dhl_inbox',           ok: true,  ms: 280 },
    { name: 'workdrive.api',            ok: false, ms: 1820, err: 'OAuth token expired' },
    { name: 'cliq.webhook',             ok: true,  ms: 95  },
    { name: 'wfirma.api',               ok: false, ms: null, err: 'WFIRMA_WAREHOUSE_ID not set' },
    { name: 'cowork.coordinator',       ok: true,  ms: 18  },
  ];

  const cliTools = [
    { id: 'check_dhl',  name: 'check_dhl_config',          desc: 'Validate DHL Express IMAP + SMTP + classifier rules',
      cmd: 'python3 -m app.tools.check_dhl_config', lastRun: '2026-05-08 14:02', state: 'ok'   },
    { id: 'check_wf',   name: 'check_wfirma_config',       desc: '10-check diagnostic for wFirma reservation gate',
      cmd: 'python3 -m app.tools.check_wfirma_config', lastRun: '2026-05-09 09:11', state: 'fail' },
    { id: 'regen',      name: 'regenerate_stale_batches',  desc: 'Re-run audit / outputs for batches >7d stale',
      cmd: 'python3 -m app.tools.regenerate_stale_batches', lastRun: '2026-05-02 18:33', state: 'idle' },
    { id: 'monitor',    name: 'run_active_shipment_monitor',desc: 'Sweep active shipments for tracking + email updates',
      cmd: 'python3 -m service.scripts.run_active_shipment_monitor', lastRun: '2026-05-10 06:00', state: 'scheduled' },
  ];

  const runTool = (id) => {
    setRunning(id);
    setTimeout(() => setRunning(null), 2200);
  };

  const okCount = healthChecks.filter(h => h.ok).length;
  const failCount = healthChecks.length - okCount;

  return (
    <div style={{ padding: '0 32px 40px', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* KPI strip */}
      <div className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <MetricTile label="Health checks"   value={`${okCount}/${healthChecks.length}`} sub={`${failCount} failing`} tone={failCount ? 'red' : 'green'} />
        <MetricTile label="Storage used"    value="2.4 GB" sub="of 100 GB"          tone="text" />
        <MetricTile label="Active locks"    value="3"      sub="2 batch / 1 user"   tone="text" />
        <MetricTile label="Version"         value="v2.14.3" sub="deployed 2026-05-09 11:30" tone="text" mono />
      </div>

      {/* Health checks grid */}
      <Card style={{ padding: 18 }}>
        <SectionHeader icon="❤" title="Health checks" subtitle="GET /api/v1/system/health-full · run every 60s" />
        <div className="responsive-grid-3" style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {healthChecks.map((c, i) => (
            <div key={i} style={{
              padding: '10px 12px', borderRadius: 6,
              border: `1px solid ${c.ok ? 'var(--border)' : 'var(--badge-red-border)'}`,
              background: c.ok ? 'var(--card)' : 'var(--badge-red-bg)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, fontWeight: 600, color: c.ok ? 'var(--text)' : 'var(--badge-red-text)' }}>{c.name}</code>
                <StatusChip kind={c.ok ? 'ready' : 'blocked'}>{c.ok ? `${c.ms}ms` : 'FAIL'}</StatusChip>
              </div>
              {!c.ok && c.err && <div style={{ marginTop: 6, fontSize: 10, color: 'var(--badge-red-text)' }}>{c.err}</div>}
            </div>
          ))}
        </div>
      </Card>

      {/* Storage panel + Locks panel side by side */}
      <div className="responsive-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card style={{ padding: 18 }}>
          <SectionHeader icon="⊟" title="Storage health" subtitle="GET /api/v1/system/storage/health" />
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <BarRow label="Real shipments"   used="1.8 GB" pct={72} />
            <BarRow label="Test fixtures"    used="0.3 GB" pct={12} />
            <BarRow label="Quarantine"       used="0.2 GB" pct={8}  tone="amber" />
            <BarRow label="Outputs / PZ"     used="0.1 GB" pct={4} />
            <BarRow label="Locks DB"         used="2 MB"   pct={1} />
          </div>
        </Card>

        <Card style={{ padding: 18 }}>
          <SectionHeader icon="🔒" title="Active locks" subtitle="GET /api/v1/system/storage/locks" />
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11 }}>
            {[
              { id: 'lock-201', kind: 'batch.pz_export', subj: 'EJP-26-27-015', age: '2m 14s', actor: 'amit@estrella' },
              { id: 'lock-202', kind: 'batch.wfirma_preview', subj: 'EJP-26-27-015', age: '1m 02s', actor: 'system' },
              { id: 'lock-203', kind: 'user.session', subj: 'amit@estrella', age: '42m', actor: 'auth' },
            ].map(l => (
              <div key={l.id} style={{ padding: '8px 10px', background: 'var(--bg-subtle)', borderRadius: 6, display: 'grid', gridTemplateColumns: '1fr auto', gap: 8 }}>
                <div>
                  <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--text)' }}>{l.kind}</code>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}><code>{l.subj}</code> · {l.actor} · {l.age}</div>
                </div>
                <Btn variant="ghost" small disabled>Release</Btn>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* CLI tool runners */}
      <Card style={{ padding: 18 }}>
        <SectionHeader icon="$" title="CLI diagnostic tools" subtitle="Surfaced from app/tools/* · output streamed to operator log" />
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {cliTools.map(t => (
            <div key={t.id} style={{
              padding: '12px 14px', border: '1px solid var(--border)', borderRadius: 6,
              display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'center',
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{t.name}</code>
                  <StatusChip kind={t.state === 'ok' ? 'ready' : t.state === 'fail' ? 'blocked' : t.state === 'scheduled' ? 'info' : 'neutral'}>
                    {t.state === 'ok' ? 'Last run: OK' : t.state === 'fail' ? 'Last run: FAIL' : t.state === 'scheduled' ? 'Cron' : 'Idle'}
                  </StatusChip>
                  <StatusChip kind="cli">CLI</StatusChip>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-2)' }}>{t.desc}</div>
                <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 10, color: 'var(--text-3)', display: 'block', marginTop: 4 }}>{t.cmd} · last run {t.lastRun}</code>
              </div>
              <Btn variant="outline" small onClick={() => runTool(t.id)} disabled={running === t.id}>
                {running === t.id ? 'Running…' : 'Run'}
              </Btn>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function BarRow({ label, used, pct, tone }) {
  const c = tone === 'amber' ? '#C09020' : tone === 'red' ? '#B82820' : 'var(--accent)';
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>
        <span>{label}</span>
        <code style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--text-3)' }}>{used}</code>
      </div>
      <div style={{ height: 6, background: 'var(--bg-subtle)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: pct + '%', background: c }} />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Export all to window
// ──────────────────────────────────────────────────────────────────────
Object.assign(window, {
  WarehouseScannerPage,
  ReservationCellPage,
  WfirmaMappingPage,
  DiagnosticsPage,
  OpsStatusChip: StatusChip,
});
