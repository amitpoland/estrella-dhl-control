// dhl-daily-summary.jsx — DHL Daily Operations Report (read-only).
//
// Calls GET /api/v1/dhl/daily-summary.
// Shows Lane A health, active shipment dashboard, DHL waiting queue,
// Lane B candidates preview, exceptions, and executive summary.
//
// Never triggers scans. Never sends email. Never modifies audit files.
// window.DhlDailySummary exported.

(function () {
  'use strict';

  function _fmt(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString('pl-PL', {
        timeZone: 'Europe/Warsaw', hour12: false,
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
      });
    } catch (_) { return (iso || '').slice(0, 16).replace('T', ' '); }
  }

  function _dur(s) {
    if (s == null) return '—';
    if (s < 60) return Math.round(s) + 's';
    return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
  }

  function _v(v, unit) {
    if (v == null) return '—';
    return String(v) + (unit ? ' ' + unit : '');
  }

  function Badge({ children, ok }) {
    var col = ok ? 'var(--badge-green-text)' : 'var(--badge-red-text)';
    var bg  = ok ? 'var(--badge-green-bg)'  : 'var(--badge-red-bg)';
    return (
      <span style={{
        background: bg, color: col, border: '1px solid ' + (ok ? 'var(--badge-green-border)' : 'var(--badge-red-border)'),
        fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
        textTransform: 'uppercase',
      }}>{children}</span>
    );
  }

  function Section({ title, children, count }) {
    return (
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
                      borderBottom: '1px solid var(--border)', paddingBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', textTransform: 'uppercase',
                         letterSpacing: '0.06em' }}>{title}</span>
          {count != null && (
            <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--text-3)',
                           background: 'var(--bg-subtle)', padding: '1px 6px', borderRadius: 3 }}>
              {count}
            </span>
          )}
        </div>
        {children}
      </div>
    );
  }

  function Row({ label, value, mono, highlight }) {
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0',
                    fontSize: 11.5, borderBottom: '1px solid var(--border-subtle)' }}>
        <span style={{ color: 'var(--text-3)' }}>{label}</span>
        <span style={{
          fontFamily: mono ? 'monospace' : 'inherit', fontWeight: highlight ? 700 : 400,
          color: highlight ? 'var(--badge-red-text)' : 'var(--text)',
        }}>{value}</span>
      </div>
    );
  }

  function ShipmentTable({ rows, emptyMsg }) {
    if (!rows || rows.length === 0) {
      return <div style={{ fontSize: 11, color: 'var(--text-3)', fontStyle: 'italic', padding: '8px 0' }}>{emptyMsg}</div>;
    }
    return (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['AWB','Supplier','Path','Status','DHL','DSK','Days'].map(function(h) {
                return <th key={h} style={{ padding: '4px 8px', textAlign: 'left',
                  color: 'var(--text-3)', fontWeight: 600, fontSize: 10,
                  textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>;
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map(function(r) {
              return (
                <tr key={r.batch_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}
                    onMouseEnter={function(e){e.currentTarget.style.background='var(--bg-subtle)'}}
                    onMouseLeave={function(e){e.currentTarget.style.background='transparent'}}>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--accent)' }}>{r.awb}</td>
                  <td style={{ padding: '4px 8px', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.supplier}</td>
                  <td style={{ padding: '4px 8px', fontSize: 10, color: 'var(--text-3)' }}>{r.clearance_path === 'agency_clearance' ? 'Agency' : r.clearance_path === 'carrier_self_clearance' ? 'Self' : r.clearance_path}</td>
                  <td style={{ padding: '4px 8px', fontSize: 10, color: 'var(--text-2)', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.status}</td>
                  <td style={{ padding: '4px 8px' }}><Badge ok={r.dhl_received}>{r.dhl_received ? 'YES' : 'NO'}</Badge></td>
                  <td style={{ padding: '4px 8px' }}><Badge ok={r.dsk_sent}>{r.dsk_sent ? 'SENT' : 'NO'}</Badge></td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.days_open != null ? r.days_open + 'd' : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  function DhlDailySummary() {
    var _s0 = React.useState(null);  var data = _s0[0], setData = _s0[1];
    var _s1 = React.useState(true);  var loading = _s1[0], setLoading = _s1[1];
    var _s2 = React.useState(null);  var err = _s2[0], setErr = _s2[1];

    function load() {
      setLoading(true); setErr(null);
      window.EstrellaShared.apiFetch('/api/v1/dhl/daily-summary')
        .then(function(d) { setData(d); setLoading(false); })
        .catch(function(e) { setErr(e.message || String(e)); setLoading(false); });
    }

    React.useEffect(function() { load(); }, []);

    return (
      <div style={{ padding: 24, maxWidth: 900, fontFamily: 'sans-serif' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
            DHL Operations Report
          </h2>
          <span style={{ flex: 1 }}></span>
          {data && <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Generated {_fmt(data.generated_at)}</span>}
          <button data-testid="dhl-summary-refresh" onClick={load} disabled={loading}
            style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: 4,
                     padding: '4px 10px', cursor: 'pointer', fontSize: 11, color: 'var(--text-2)' }}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>

        {err && <div style={{ color: 'var(--badge-red-text)', marginBottom: 16, fontSize: 12 }}>Error: {err}</div>}
        {!data && !loading && !err && <div style={{ color: 'var(--text-3)' }}>No data available.</div>}

        {data && (
          <div>
            {/* Executive Summary */}
            <Section title="Executive Summary">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
                {[
                  ['Active shipments', data.summary.active_shipments],
                  ['Waiting for DHL', data.summary.waiting_for_dhl],
                  ['Replies sent today', data.summary.replies_sent_today],
                  ['Scanner runs (24h)', data.summary.scanner_runs_24h],
                  ['Scanner failures', data.summary.scanner_failures_24h, data.summary.scanner_failures_24h > 0],
                  ['Lane B eligible', data.summary.lane_b_eligible],
                ].map(function(item) {
                  return (
                    <div key={item[0]} style={{ background: 'var(--bg-subtle)', borderRadius: 6,
                      padding: '10px 14px', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase',
                                    letterSpacing: '0.05em', marginBottom: 4 }}>{item[0]}</div>
                      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'monospace',
                                    color: item[2] ? 'var(--badge-red-text)' : 'var(--text)' }}>{item[1]}</div>
                    </div>
                  );
                })}
              </div>
            </Section>

            {/* Lane A Health */}
            <Section title="Lane A Health">
              <div style={{ columns: 2, gap: 24 }}>
                <Row label="Last run at"         value={_fmt(data.lane_a_health.last_run_at)} />
                <Row label="Last status"          value={data.lane_a_health.last_run_status}
                     highlight={data.lane_a_health.last_run_status === 'failed'} />
                <Row label="Last duration"        value={_dur(data.lane_a_health.last_run_duration_s)} />
                <Row label="Runs (24h)"           value={_v(data.lane_a_health.runs_24h)} mono />
                <Row label="Failures (24h)"       value={_v(data.lane_a_health.failed_runs_24h)}
                     highlight={data.lane_a_health.failed_runs_24h > 0} mono />
                <Row label="Avg duration"         value={_dur(data.lane_a_health.avg_duration_s)} />
                <Row label="Avg batches checked"  value={_v(data.lane_a_health.avg_batches_checked)} mono />
                <Row label="Avg matches found"    value={_v(data.lane_a_health.avg_matches_found)} mono />
              </div>
            </Section>

            {/* DHL Waiting Queue */}
            <Section title="DHL Waiting Queue — DSK sent, no reply yet"
                     count={data.dhl_waiting_queue.length}>
              {data.dhl_waiting_queue.length === 0
                ? <div style={{ fontSize: 11, color: 'var(--badge-green-text)', padding: '6px 0' }}>
                    ✓ No shipments waiting for DHL reply.
                  </div>
                : <ShipmentTable rows={data.dhl_waiting_queue} emptyMsg="—" />
              }
            </Section>

            {/* Lane B Candidates */}
            <Section title="Lane B Candidates (preview — read-only)"
                     count={data.lane_b_candidates.length}>
              {data.lane_b_candidates.length === 0
                ? <div style={{ fontSize: 11, color: 'var(--text-3)', fontStyle: 'italic', padding: '6px 0' }}>
                    No follow-up candidates.
                  </div>
                : data.lane_b_candidates.map(function(c) {
                  return (
                    <div key={c.batch_id} style={{
                      padding: '8px 12px', marginBottom: 6, borderRadius: 6,
                      background: c.eligible ? 'var(--badge-amber-bg)' : 'var(--bg-subtle)',
                      border: '1px solid ' + (c.eligible ? 'var(--badge-amber-border)' : 'var(--border)'),
                      fontSize: 11,
                    }}>
                      <span style={{ fontFamily: 'monospace', fontWeight: 700, color: 'var(--accent)' }}>{c.awb}</span>
                      <span style={{ margin: '0 8px', color: 'var(--text-3)' }}>·</span>
                      <span>{c.supplier}</span>
                      <span style={{ margin: '0 8px', color: 'var(--text-3)' }}>·</span>
                      <span style={{ color: 'var(--text-2)' }}>
                        Waiting {c.hours_waiting != null ? c.hours_waiting + 'h' : '—'}
                      </span>
                      <span style={{ margin: '0 8px', color: 'var(--text-3)' }}>·</span>
                      <Badge ok={c.eligible}>{c.eligible ? 'ELIGIBLE' : 'NOT YET'}</Badge>
                      <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--text-3)' }}>
                        Lane B: {c.lane_b_status}
                      </span>
                    </div>
                  );
                })
              }
            </Section>

            {/* Active Shipments */}
            <Section title="Active Shipment Dashboard" count={data.active_shipments.length}>
              <ShipmentTable rows={data.active_shipments} emptyMsg="No active shipments." />
            </Section>

            {/* Exceptions */}
            {data.exceptions.length > 0 && (
              <Section title="Exceptions" count={data.exceptions.length}>
                {data.exceptions.map(function(e, i) {
                  return (
                    <div key={i} style={{ padding: '6px 10px', marginBottom: 4, borderRadius: 4,
                      background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
                      fontSize: 11, color: 'var(--badge-red-text)' }}>
                      <strong>{e.type}</strong>
                      {e.awb && <span style={{ fontFamily: 'monospace', marginLeft: 8 }}>{e.awb}</span>}
                      {e.reason && <span style={{ marginLeft: 8, color: 'var(--text-2)' }}>{e.reason}</span>}
                    </div>
                  );
                })}
              </Section>
            )}
          </div>
        )}
      </div>
    );
  }

  window.DhlDailySummary = DhlDailySummary;
})();
