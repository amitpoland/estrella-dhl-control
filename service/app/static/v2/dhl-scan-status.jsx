// dhl-scan-status.jsx — Read-only DHL inbox-scanner status card.
//
// Calls GET /api/v1/dhl/auto-scan-status (auth required).
// Shows last scan result, counts, timing, and next scheduled run.
// Never triggers a scan. Never modifies audit files. Never sends email.
//
// Mount in V2 shell alongside the inbox page or as a standalone panel.

(function () {
  'use strict';

  var STATUS_COLORS = {
    running:          { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    success:          { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    failed:           { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
    timed_out:        { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
    never_run:        { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
    status_read_error:{ bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  };

  function _fmt(isoStr) {
    if (!isoStr) return '—';
    try {
      return new Date(isoStr).toLocaleString('pl-PL', {
        timeZone: 'Europe/Warsaw', hour12: false,
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    } catch (_) { return isoStr.slice(0, 19).replace('T', ' '); }
  }

  function _dur(s) {
    if (s == null) return '—';
    if (s < 60) return s + 's';
    return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
  }

  function _val(v) {
    return v == null ? '—' : String(v);
  }

  function Row({ label, value, highlight }) {
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0',
                    borderBottom: '1px solid var(--border-subtle)', fontSize: 12 }}>
        <span style={{ color: 'var(--text-3)' }}>{label}</span>
        <span style={{ fontFamily: 'monospace', fontWeight: highlight ? 700 : 400,
                       color: highlight ? 'var(--badge-red-text)' : 'var(--text)' }}>
          {value}
        </span>
      </div>
    );
  }

  function DhlScanStatus() {
    var _s0 = React.useState(null);
    var data = _s0[0], setData = _s0[1];
    var _s1 = React.useState(true);
    var loading = _s1[0], setLoading = _s1[1];
    var _s2 = React.useState(null);
    var error = _s2[0], setError = _s2[1];

    function load() {
      setLoading(true); setError(null);
      window.EstrellaShared.apiFetch('/api/v1/dhl/auto-scan-status')
        .then(function(d) { setData(d); setLoading(false); })
        .catch(function(e) { setError(e.message || String(e)); setLoading(false); });
    }

    React.useEffect(function() { load(); }, []);

    var status = (data && data.status) || 'never_run';
    var colors = STATUS_COLORS[status] || STATUS_COLORS.never_run;
    var hasError = data && data.errors_count > 0;

    return (
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 8, padding: 16, minWidth: 280, maxWidth: 380,
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
            DHL Inbox Scanner
          </span>
          <span style={{ flex: 1 }}></span>
          {loading
            ? <span style={{ fontSize: 11, color: 'var(--text-3)' }}>…</span>
            : (
              <button
                data-testid="dhl-scan-status-refresh"
                onClick={load}
                style={{
                  background: 'transparent', border: '1px solid var(--border)',
                  borderRadius: 4, padding: '2px 8px', fontSize: 11,
                  cursor: 'pointer', color: 'var(--text-2)',
                }}
              >↻</button>
            )
          }
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
            background: colors.bg, color: colors.text, border: '1px solid ' + colors.border,
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>{status.replace(/_/g, ' ')}</span>
        </div>

        {error && (
          <div style={{ fontSize: 11, color: 'var(--badge-red-text)', marginBottom: 10 }}>
            Status fetch failed: {error}
          </div>
        )}

        {data && (
          <div>
            <Row label="Last scan started"   value={_fmt(data.started_at)} />
            <Row label="Last scan completed" value={_fmt(data.completed_at)} />
            <Row label="Duration"            value={_dur(data.duration_seconds)} />
            <Row label="Batches checked"     value={_val(data.batches_checked)} />
            <Row label="DHL emails matched"  value={_val(data.received_set)} />
            <Row label="Skipped (inactive)"  value={_val(data.skipped_inactive)} />
            <Row label="Skipped (excluded)"  value={_val(data.skipped_excluded)} />
            <Row label="B2 triggered"        value={_val(data.b2_triggered)} />
            <Row label="DSK replies sent"    value={_val(data.b2_sent)} />
            <Row label="Errors"              value={_val(data.errors_count)}
                 highlight={hasError} />
            {hasError && data.last_error && (
              <div style={{ fontSize: 10, color: 'var(--badge-red-text)',
                            marginTop: 4, wordBreak: 'break-all' }}>
                {data.last_error}
              </div>
            )}
            <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border-subtle)',
                          fontSize: 10.5, color: 'var(--text-3)', display: 'flex',
                          justifyContent: 'space-between' }}>
              <span>Next run ~</span>
              <span style={{ fontFamily: 'monospace' }}>
                {data.next_run_at ? _fmt(data.next_run_at) : '10 min after last start'}
              </span>
            </div>
          </div>
        )}
      </div>
    );
  }

  window.DhlScanStatus = DhlScanStatus;

})();
