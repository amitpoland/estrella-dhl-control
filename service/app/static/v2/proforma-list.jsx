// Pro Forma List (Screen A) -- WIRED to live backend via PzState.useProformaDrafts
// Per ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md
//
// WIRING: GET /api/v1/proforma/drafts/{batch_id} (per-batch only --
// no global cross-batch list endpoint exists). batch_id from URL ?batch_id=.
// ASSUMPTION: navigated with ?batch_id= in URL. Empty state if absent.
// ASSUMPTION: backend draft shape: { id, batch_id, client_name, draft_state,
//   wfirma_proforma_fullnumber, currency, created_at, updated_at,
//   editable_lines_json (JSON string of lines), ... }

const STATUS_CHIP = {
  draft:              { label: 'Draft',          bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  editing:            { label: 'Editing',        bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  approved:           { label: 'Approved',       bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  posting:            { label: 'Posting...',     bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  posted:             { label: 'Posted',         bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  post_failed:        { label: 'Post Failed',    bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  adopted_from_audit: { label: 'Adopted',        bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  cancelled:          { label: 'Cancelled',      bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
};

function ProformaStatusChip({ status }) {
  const s = STATUS_CHIP[status] || { label: status || 'Unknown', bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 4,
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      fontSize: 10.5, fontWeight: 600, letterSpacing: '0.02em',
    }}>
      {s.label}
    </span>
  );
}

function ProformaListPage({ onDrill }) {
  // Read batch_id from URL (same pattern as proforma-v2.html)
  const batchId = (new URLSearchParams(window.location.search)).get('batch_id') || '';

  // Fetch real drafts from backend -- LIVE
  const draftsHook = window.PzState.useProformaDrafts(batchId);
  const drafts = (draftsHook.data && draftsHook.data.drafts) ? draftsHook.data.drafts : [];

  if (!batchId) {
    return (
      <div style={{ flex: 1, overflow: 'auto', padding: '20px 32px', background: 'var(--bg)' }}>
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)' }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>No batch selected</div>
          <div style={{ fontSize: 13 }}>Navigate here with ?batch_id=&lt;id&gt; to view proforma drafts for a shipment batch.</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '20px 32px', background: 'var(--bg)' }} data-testid="proforma-list-page">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', margin: 0 }}>Pro Forma Drafts</h2>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 3 }}>
            Batch: <code style={{ fontSize: 11 }}>{batchId}</code>
            {' '}&mdash; Click any draft to open detail &middot; {drafts.length} draft(s)
          </div>
        </div>
      </div>

      {/* Loading / error / empty */}
      {draftsHook.loading && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}>
          <span className="spinner" /> Loading drafts...
        </div>
      )}
      {draftsHook.error && !draftsHook.loading && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--badge-red-text)' }}>
          Failed to load drafts: {draftsHook.error}
          <br /><button onClick={draftsHook.reload} style={{ marginTop: 12, cursor: 'pointer' }}>Retry</button>
        </div>
      )}
      {!draftsHook.loading && !draftsHook.error && drafts.length === 0 && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}>
          No proforma drafts found for this batch.
        </div>
      )}

      {/* Drafts table -- real data */}
      {!draftsHook.loading && drafts.length > 0 && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['Draft ID', 'Client', 'State', 'Currency', 'Lines', 'Created'].map(h => (
                  <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drafts.map((d, i) => {
                // Parse lines count from editable_lines_json if present
                let lineCount = '—';
                try { lineCount = JSON.parse(d.editable_lines_json || '[]').length; } catch (_) {}
                return (
                  <tr
                    key={d.id}
                    onClick={() => onDrill(d)}
                    data-testid={`draft-row-${d.id}`}
                    style={{ borderBottom: i < drafts.length - 1 ? '1px solid var(--border-subtle)' : 'none', cursor: 'pointer' }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <td style={{ padding: '14px 16px', fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
                      #{d.id}
                      {d.wfirma_proforma_fullnumber && (
                        <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'sans-serif' }}>{d.wfirma_proforma_fullnumber}</div>
                      )}
                    </td>
                    <td style={{ padding: '14px 16px', fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{d.client_name || '—'}</td>
                    <td style={{ padding: '14px 16px' }}><ProformaStatusChip status={d.draft_state || d.status} /></td>
                    <td style={{ padding: '14px 16px'
