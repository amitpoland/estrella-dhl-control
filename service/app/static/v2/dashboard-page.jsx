// Shipments Hub (V2 shell `page === 'shipments'`) — read-only batch list.
//
// Sprint 32: replaced the inline MOCK_SHIPMENTS + static SUMMARY_CARDS with a
// live, read-only projection of completed batches. Same observer pattern as
// Sprint 30 (Inventory) and Sprint 31 (DHL Hub): existing authority → dumb
// renderer → no mutation.
//
// Authority owner (backend, unchanged): routes_dashboard.py `list_batches()`
// → `_batch_summary(audit.json)`. This page renders batch truth; it never
// starts, reprocesses, regenerates, rechecks, archives, deletes, overrides, or
// resends anything. Those authorities live in V1 + the engine and are out of
// scope. See .claude/campaigns/atlas-v2/sprint-32-shipments-hub.md.
//
// The ONLY endpoint this page may consume:
//   GET /api/v1/dashboard/batches   — completed batches, newest first, deduped
//
// Removed (P3) by this sprint: the `⋯` action menu (Edit Draft / Reprocess /
// Archive / Delete), `← Prev` / `Next →` pagination, and the internal drill into
// the mock-shaped ShipmentDetailPage. AWB renders as an external carrier-tracking
// link (live `tracking_url`) only.

const SHIPMENTS_ENDPOINT = '/api/v1/dashboard/batches';

// Overall-status buckets used by the filter bar (derived from live `status`).
const OVERALL_FILTERS = ['all', 'success', 'partial', 'blocked'];

function _fmt(v) {
  // The backend already formats most values; render raw, fall back to em-dash.
  if (v === null || v === undefined || v === '') return '—';
  return v;
}

function _money(v) {
  // Monetary columns (net/gross/duty) arrive as raw engine numbers. Render to
  // exactly two decimals via the shared V2 formatter (window.fmtMoney2 from
  // components.jsx). Locale pl-PL is the established V2 money convention —
  // matches dashboard-kanban.jsx and shipment-detail-page.jsx so the same PLN
  // value reads identically across list, kanban, and detail. Fallback to _fmt
  // only if the shared layer is unavailable.
  return window.fmtMoney2 ? window.fmtMoney2(v, { locale: 'pl-PL' }) : _fmt(v);
}

function _safeHttpUrl(u) {
  // Only allow http(s) tracking links — never render a javascript:/data:/vbscript:
  // href even if the backend field were ever poisoned (defence in depth).
  return (typeof u === 'string' && /^https?:\/\//i.test(u)) ? u : null;
}

function DashboardPage({ onViewShipment }) {

  const [rows,    setRows]    = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error,   setError]   = React.useState(null);
  const [filter,  setFilter]  = React.useState('all');
  const [sortCol, setSortCol] = React.useState(null);
  const [sortDir, setSortDir] = React.useState('asc');

  const load = React.useCallback(() => {
    setLoading(true); setError(null);
    window.EstrellaShared.apiFetch(SHIPMENTS_ENDPOINT)
      .then(d => {
        // Backend returns a bare list; tolerate {batches:[...]} / {rows:[...]} too.
        const list = Array.isArray(d) ? d : ((d && (d.batches || d.rows || d.items)) || []);
        setRows(list); setLoading(false);
      })
      .catch(e => { setError((e && e.message) || String(e)); setLoading(false); });
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const all = rows || [];

  // ── Summary tiles derived from live rows (no static values) ─────────────────
  const summary = React.useMemo(() => {
    const count = pred => all.filter(pred).length;
    return [
      { label: 'Total Shipments',     value: all.length,                                     icon: '⬡', colorVar: 'var(--text)' },
      { label: 'Success',             value: count(s => s.status === 'success'),             icon: '✓', colorVar: 'var(--badge-green-text)' },
      { label: 'Partial',             value: count(s => s.status === 'partial'),             icon: '◑', colorVar: 'var(--badge-amber-text)' },
      { label: 'Blocked',             value: count(s => s.status === 'blocked'),             icon: '⚠', colorVar: 'var(--badge-red-text)' },
      { label: 'SAD Present',         value: count(s => s.has_sad),                          icon: '⊟', colorVar: 'var(--badge-blue-text)' },
      { label: 'PZ Confirmed',        value: count(s => s.pz_confirmed),                     icon: '◈', colorVar: 'var(--badge-purple-text)' },
    ];
  }, [all]);

  const filtered = filter === 'all' ? all : all.filter(s => s.status === filter);

  const sorted = React.useMemo(() => {
    if (!sortCol) return filtered;
    const copy = filtered.slice();
    copy.sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol];
      if (av === bv) return 0;
      if (av === null || av === undefined || av === '') return 1;
      if (bv === null || bv === undefined || bv === '') return -1;
      const r = String(av).localeCompare(String(bv), undefined, { numeric: true });
      return sortDir === 'asc' ? r : -r;
    });
    return copy;
  }, [filtered, sortCol, sortDir]);

  const handleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const TH = ({ col, children }) => (
    <th onClick={() => handleSort(col)} style={{
      padding: '10px 12px', textAlign: 'left', fontSize: 10,
      fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em',
      textTransform: 'uppercase', cursor: 'pointer', whiteSpace: 'nowrap',
      borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)',
      userSelect: 'none',
    }}>
      {children} {sortCol === col ? (sortDir === 'asc' ? '↑' : '↓') : ''}
    </th>
  );

  return (
    <div data-testid="shipments-hub-root" style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>

      {/* Reload bar (passive client-side GET re-issue; zero server side-effect) */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button
          data-testid="shipments-hub-reload"
          onClick={load}
          disabled={loading}
          style={{
            background: 'transparent', border: '1px solid var(--border)', borderRadius: 4,
            padding: '4px 10px', fontSize: 11, color: 'var(--text-2)',
            cursor: loading ? 'default' : 'pointer',
          }}
        >↻ Reload</button>
      </div>

      {/* Summary tiles (derived from live rows) */}
      <div data-testid="shipments-hub-summary" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 28 }}>
        {summary.map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 500, marginBottom: 6 }}>{c.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: c.colorVar, fontFamily: '"DM Serif Display", serif' }}>{loading ? '—' : c.value}</div>
              </div>
              <div style={{
                width: 30, height: 30, borderRadius: 6,
                background: 'var(--accent-subtle)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 14, color: c.colorVar,
              }}>{c.icon}</div>
            </div>
          </Card>
        ))}
      </div>

      {/* Filter bar (client-side over live data) */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: '#8A8278', marginRight: 4 }}>Filter:</span>
        {OVERALL_FILTERS.map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            padding: '4px 10px', borderRadius: 20,
            border: filter === f ? `1px solid ${GOLD}` : '1px solid #E4DDD2',
            background: filter === f ? GOLD + '22' : 'transparent',
            color: filter === f ? '#18160F' : '#6A6258',
            fontSize: 11, fontWeight: filter === f ? 600 : 400, cursor: 'pointer',
            textTransform: f === 'all' ? 'none' : 'capitalize',
          }}>{f === 'all' ? 'All' : f}</button>
        ))}
      </div>

      {/* Loading / error / empty states */}
      {loading && <div data-testid="shipments-hub-loading" style={{ fontSize: 12, color: 'var(--text-3)', padding: '12px 4px' }}>Loading batches…</div>}
      {error   && <div data-testid="shipments-hub-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', padding: '12px 4px' }}>Failed to load batches: {error}</div>}
      {!loading && !error && all.length === 0 && (
        <div data-testid="shipments-hub-empty" style={{ fontSize: 12, color: 'var(--text-3)', padding: '12px 4px' }}>No completed batches yet.</div>
      )}

      {/* Table */}
      {!loading && !error && all.length > 0 && (
        <Card style={{ overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="shipments-hub-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  <TH col="tracking_no">AWB / Tracking</TH>
                  <TH col="carrier">Carrier</TH>
                  <TH col="dhl_status">DHL / Clearance</TH>
                  <TH col="action_reason">Rec.</TH>
                  <TH col="sad_status">SAD Status</TH>
                  <TH col="mrn">MRN</TH>
                  <TH col="pz_status">PZ Status</TH>
                  <TH col="net">Net Value</TH>
                  <TH col="gross">Gross Value</TH>
                  <TH col="duty">Duty A00</TH>
                  <TH col="status">Overall</TH>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row, i) => {
                  const label = row.tracking_no || row.batch_id || '—';
                  const trackUrl = _safeHttpUrl(row.tracking_url);
                  return (
                    <tr key={row.batch_id || i}
                      onClick={() => onViewShipment && onViewShipment(row)}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      style={{ borderBottom: '1px solid var(--border-subtle)', transition: 'background 0.1s', cursor: onViewShipment ? 'pointer' : 'default' }}
                    >
                      <td style={{ padding: '10px 12px' }}>
                        {trackUrl ? (
                          <a href={trackUrl} target="_blank" rel="noopener noreferrer"
                            title={row.tracking_label || 'Open carrier tracking'}
                            style={{
                              color: '#1A5FA8', fontSize: 12, fontWeight: 600,
                              fontFamily: 'monospace', textDecoration: 'underline',
                              textDecorationStyle: 'dotted',
                            }}>{label} ↗</a>
                        ) : (
                          <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'monospace', color: 'var(--text)' }}>{label}</span>
                        )}
                      </td>
                      <td style={{ padding: '10px 12px', color: '#18160F' }}>
                        <span style={{
                          display: 'inline-block', padding: '1px 6px',
                          background: row.carrier === 'DHL' ? '#EBF3FB' : row.carrier === 'FedEx' ? '#F0EBFB' : '#F0EFEB',
                          borderRadius: 4, fontSize: 10, fontWeight: 700,
                          color: row.carrier === 'DHL' ? '#1A5FA8' : row.carrier === 'FedEx' ? '#5A1AA8' : '#5A5550',
                        }}>{_fmt(row.carrier)}</span>
                      </td>
                      <td style={{ padding: '10px 12px' }}>{row.dhl_status ? <Badge status={row.dhl_status} small /> : <span style={{ color: 'var(--text-3)' }}>—</span>}</td>
                      <td style={{ padding: '10px 12px', color: '#6A6258', fontSize: 11 }}>{_fmt(row.action_reason)}</td>
                      <td style={{ padding: '10px 12px' }}>{row.sad_status ? <Badge status={row.sad_status} small /> : <span style={{ color: 'var(--text-3)' }}>—</span>}</td>
                      <td style={{ padding: '10px 12px', color: '#18160F', fontSize: 11, fontFamily: 'monospace' }}>{_fmt(row.mrn)}</td>
                      <td style={{ padding: '10px 12px' }}>{row.pz_status ? <Badge status={row.pz_status} small /> : <span style={{ color: 'var(--text-3)' }}>—</span>}</td>
                      <td style={{ padding: '10px 12px', color: '#18160F', fontWeight: 500, textAlign: 'right' }}>{_money(row.net)}</td>
                      <td style={{ padding: '10px 12px', color: '#18160F', fontWeight: 500, textAlign: 'right' }}>{_money(row.gross)}</td>
                      <td style={{ padding: '10px 12px', color: GOLD, fontWeight: 700, textAlign: 'right' }}>{_money(row.duty)}</td>
                      <td style={{ padding: '10px 12px' }}>{row.status ? <Badge status={row.status} small /> : <span style={{ color: 'var(--text-3)' }}>—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Showing {sorted.length} of {all.length} batches</span>
          </div>
        </Card>
      )}

      {/* Authority statement */}
      <div style={{
        marginTop: 16, padding: '12px 16px', background: 'var(--bg-subtle)',
        border: '1px solid var(--border)', borderRadius: 8,
        fontSize: 11, color: 'var(--text-3)', lineHeight: 1.5,
      }}>
        <strong style={{ color: 'var(--text-2)' }}>Observer only.</strong>{' '}
        This surface is read-only — it renders completed-batch truth and exposes no
        action controls of any kind. Batch processing authority remains the engine
        and the V1 dashboard.{' '}
        <strong style={{ color: 'var(--text-2)' }}>Endpoint:</strong>{' '}
        <code style={{ fontFamily: 'monospace', background: 'var(--card)', padding: '1px 5px', borderRadius: 3 }}>{SHIPMENTS_ENDPOINT}</code>.
      </div>
    </div>
  );
}

Object.assign(window, { DashboardPage });
