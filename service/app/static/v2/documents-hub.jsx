// ─────────────────────────────────────────────────────────────────────────────
// Documents Hub — read-only observer surface (Sprint 35)
//
// Authority: GET /api/v1/dashboard/batches
//   Returns the deduplicated batch list with per-batch pz_status, sad_status,
//   tracking_no, doc_no, and timestamp. No writes, no regeneration, no mutation.
//
// Operator flow:
//   1. Hub lists all known batches with their document status summary.
//   2. "View Documents" opens documents-v2.html?batch_id=X (standalone viewer).
//      That page uses GET /api/v1/dashboard/batches/{id} and serves real file links.
//
// This page is READ-ONLY.  It never calls a POST, PUT, PATCH, or DELETE endpoint.
// Proforma/PZ lifecycle management (create, approve, post-to-wFirma) is deferred
// to a write-capable sprint that adds those endpoints.
// ─────────────────────────────────────────────────────────────────────────────

const { apiFetch } = window.EstrellaShared;

// ── Status helpers ────────────────────────────────────────────────────────────

const PZ_TONE = {
  'Generated': 'green',
  'Exported':  'green',
  'Ready':     'blue',
  'Pending':   'amber',
  'Blocked':   'red',
};

const SAD_TONE = {
  'present':  'green',
  'uploaded': 'green',
  'partial':  'amber',
  'missing':  'red',
};

function statusChip(label, toneMap) {
  const key   = Object.keys(toneMap).find(k => (label || '').includes(k)) || '';
  const tone  = toneMap[key] || 'neutral';
  const COLORS = {
    green:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    blue:    { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)'  },
    amber:   { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    red:     { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)'   },
    neutral: { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
  };
  const c = COLORS[tone];
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      fontSize: 11, fontWeight: 600, letterSpacing: '0.02em',
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
    }}>
      {label || '—'}
    </span>
  );
}

function fmtDate(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' });
  } catch (_) { return ts.slice(0, 10); }
}

// ── Documents Hub page ────────────────────────────────────────────────────────

function DocumentsHubPage() {
  const [batches, setBatches]   = React.useState(null);
  const [loading, setLoading]   = React.useState(true);
  const [error,   setError]     = React.useState(null);

  const load = React.useCallback(() => {
    setLoading(true);
    setError(null);
    apiFetch('/api/v1/dashboard/batches')
      .then(rows => { setBatches(rows); setLoading(false); })
      .catch(e  => { setError((e && e.message) || String(e)); setLoading(false); });
  }, []);

  React.useEffect(() => { load(); }, [load]);

  return (
    <div
      data-testid="documents-hub-root"
      style={{ flex: 1, overflow: 'auto', padding: '16px 32px 32px', display: 'flex', flexDirection: 'column', gap: 16 }}
    >
      {/* Header bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 4 }}>
            Documents — read-only authority observer
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-2)' }}>
            Document status per shipment · SAD · PZ · Generated outputs · Source uploads
          </div>
        </div>
        <button
          data-testid="documents-hub-reload"
          onClick={load}
          disabled={loading}
          style={{
            padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)',
            background: 'var(--card)', color: 'var(--text)', fontSize: 12,
            fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? '⟳ Loading…' : '↻ Reload'}
        </button>
      </div>

      {/* Summary strip */}
      {batches && (
        <div
          data-testid="documents-hub-summary"
          style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}
        >
          {[
            { label: 'Total batches',  value: batches.length },
            { label: 'PZ generated',   value: batches.filter(b => (b.pz_status || '').includes('Generated') || (b.pz_status || '').includes('Exported')).length },
            { label: 'SAD present',    value: batches.filter(b => (b.sad_status || '').toLowerCase() !== 'missing').length },
          ].map(({ label, value }) => (
            <div key={label} style={{
              padding: '10px 18px', background: 'var(--card)', border: '1px solid var(--border)',
              borderRadius: 8, boxShadow: '0 1px 2px var(--shadow)',
            }}>
              <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div style={{
          padding: '14px 18px', background: 'var(--badge-red-bg)',
          border: '1px solid var(--badge-red-border)', borderRadius: 8,
          color: 'var(--badge-red-text)', fontSize: 12.5, fontWeight: 600,
        }}>
          Failed to load batches: {error}
        </div>
      )}

      {/* Batch table */}
      {!error && batches && batches.length === 0 && (
        <div style={{
          padding: 40, textAlign: 'center', color: 'var(--text-3)',
          border: '1px dashed var(--border)', borderRadius: 10, fontSize: 13,
        }}>
          No batches found. Process a shipment to see documents here.
        </div>
      )}

      {!error && batches && batches.length > 0 && (
        <div
          data-testid="documents-hub-batch-table"
          style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 2px var(--shadow)' }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['Tracking / Batch', 'Date', 'SAD', 'PZ', ''].map(h => (
                  <th key={h} style={{
                    padding: '10px 14px', textAlign: 'left', fontWeight: 700,
                    color: 'var(--text-3)', fontSize: 10.5, textTransform: 'uppercase',
                    letterSpacing: '0.08em', borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {batches.map(b => (
                <tr
                  key={b.batch_id}
                  data-testid={`documents-hub-row-${b.batch_id}`}
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '11px 14px' }}>
                    <div style={{ fontFamily: 'monospace', fontWeight: 700, color: 'var(--text)', fontSize: 12 }}>
                      {b.tracking_no || b.doc_no || b.batch_id}
                    </div>
                    {b.doc_no && b.tracking_no && (
                      <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{b.doc_no}</div>
                    )}
                  </td>
                  <td style={{ padding: '11px 14px', color: 'var(--text-2)', fontFamily: 'monospace', fontSize: 11.5 }}>
                    {fmtDate(b.timestamp)}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    {statusChip(b.sad_status, SAD_TONE)}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    {statusChip(b.pz_status, PZ_TONE)}
                  </td>
                  <td style={{ padding: '11px 14px', textAlign: 'right' }}>
                    <a
                      data-testid={`documents-hub-view-${b.batch_id}`}
                      href={`../documents-v2.html?batch_id=${encodeURIComponent(b.batch_id)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        padding: '5px 12px', borderRadius: 5,
                        border: '1px solid var(--border)', background: 'var(--bg-subtle)',
                        color: 'var(--text)', fontSize: 11.5, fontWeight: 600,
                        textDecoration: 'none',
                      }}
                    >
                      View Documents
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

window.DocumentsHubPage = DocumentsHubPage;
