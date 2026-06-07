// proforma-search.jsx — M6 Prior Proforma Search (Screen C)
// WIRED to GET /api/v1/proforma/search via PzApi.searchProformaDrafts.
//
// Authority: proforma_drafts table ONLY. Read-only. No wFirma, no invoice
// ledger, no email, no mutation. Does NOT implement amount-range search.
//
// Sprint: M6 Prior Proforma Search (PR 3/3 — V2 UI)

function ProformaSearchPage({ onNav, onDrillBatch }) {
  const [filters, setFilters] = React.useState({
    client_name: '',
    batch_id: '',
    wfirma_proforma_id: '',
    wfirma_proforma_fullnumber: '',
    draft_state: '',
    currency: '',
    date_from: '',
    date_to: '',
  });
  const [page, setPage] = React.useState(1);
  const [pageSize] = React.useState(25);
  const [results, setResults] = React.useState(null);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [searched, setSearched] = React.useState(false);

  const doSearch = async (pg) => {
    setLoading(true);
    setError(null);
    const targetPage = pg || page;
    // Build non-empty filters only
    const active = {};
    Object.entries(filters).forEach(([k, v]) => {
      if (v && v.trim()) active[k] = v.trim();
    });
    active.page = String(targetPage);
    active.page_size = String(pageSize);

    const res = await window.PzApi.searchProformaDrafts(active);
    setLoading(false);
    if (!res.ok) {
      setError(res.error || 'Search failed');
      return;
    }
    setResults(res.data.results || []);
    setTotal(res.data.total || 0);
    setPage(res.data.page || targetPage);
    setSearched(true);
  };

  const handleSearch = (e) => {
    if (e) e.preventDefault();
    setPage(1);
    doSearch(1);
  };

  const handlePageChange = (newPage) => {
    setPage(newPage);
    doSearch(newPage);
  };

  const handleClear = () => {
    setFilters({
      client_name: '', batch_id: '', wfirma_proforma_id: '',
      wfirma_proforma_fullnumber: '', draft_state: '', currency: '',
      date_from: '', date_to: '',
    });
    setResults(null);
    setTotal(0);
    setSearched(false);
    setError(null);
    setPage(1);
  };

  const handleRowClick = (row) => {
    if (row.batch_id && onDrillBatch) {
      onDrillBatch(row.batch_id);
    }
  };

  const updateFilter = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const inputStyle = {
    width: '100%', padding: '8px 10px', fontSize: 13,
    border: '1px solid var(--border)', borderRadius: 6,
    background: 'var(--card)', color: 'var(--text)',
    fontFamily: 'inherit', outline: 'none',
  };
  const labelStyle = {
    fontSize: 11, fontWeight: 600, color: 'var(--text-2)',
    marginBottom: 4, display: 'block', letterSpacing: '0.03em',
  };

  const DRAFT_STATES = ['', 'draft', 'editing', 'approved', 'posting', 'posted', 'post_failed', 'adopted_from_audit', 'cancelled'];
  const CURRENCIES = ['', 'EUR', 'USD', 'PLN', 'GBP', 'INR'];

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '20px 32px', background: 'var(--bg)' }}
         data-testid="proforma-search-page">

      {/* Authority notice */}
      <div style={{
        padding: '10px 16px', marginBottom: 16, borderRadius: 8,
        background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)',
        fontSize: 12, color: 'var(--badge-blue-text)', lineHeight: 1.5,
      }} data-testid="proforma-search-authority-notice">
        Read-only search across local proforma drafts. Does not query wFirma and does not mutate accounting records.
      </div>

      {/* Search form */}
      <form onSubmit={handleSearch} data-testid="proforma-search-form">
        <div style={{
          background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
          padding: 20, marginBottom: 20, boxShadow: '0 1px 3px var(--shadow)',
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 16 }}>
            Search Filters
          </div>

          {/* Row 1: client_name, batch_id, fullnumber, proforma_id */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 14 }}>
            <div>
              <label style={labelStyle}>Client Name</label>
              <input
                data-testid="search-filter-client-name"
                style={inputStyle}
                placeholder="e.g. Global Jewellery"
                value={filters.client_name}
                onChange={e => updateFilter('client_name', e.target.value)}
              />
            </div>
            <div>
              <label style={labelStyle}>Batch ID</label>
              <input
                data-testid="search-filter-batch-id"
                style={inputStyle}
                placeholder="e.g. DHL-2026-001"
                value={filters.batch_id}
                onChange={e => updateFilter('batch_id', e.target.value)}
              />
            </div>
            <div>
              <label style={labelStyle}>Proforma Number</label>
              <input
                data-testid="search-filter-fullnumber"
                style={inputStyle}
                placeholder="e.g. FP 1/2026"
                value={filters.wfirma_proforma_fullnumber}
                onChange={e => updateFilter('wfirma_proforma_fullnumber', e.target.value)}
              />
            </div>
            <div>
              <label style={labelStyle}>wFirma ID</label>
              <input
                data-testid="search-filter-wfirma-id"
                style={inputStyle}
                placeholder="e.g. 12345"
                value={filters.wfirma_proforma_id}
                onChange={e => updateFilter('wfirma_proforma_id', e.target.value)}
              />
            </div>
          </div>

          {/* Row 2: draft_state, currency, date_from, date_to */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 18 }}>
            <div>
              <label style={labelStyle}>State</label>
              <select
                data-testid="search-filter-draft-state"
                style={{ ...inputStyle, cursor: 'pointer' }}
                value={filters.draft_state}
                onChange={e => updateFilter('draft_state', e.target.value)}
              >
                {DRAFT_STATES.map(s => (
                  <option key={s} value={s}>{s || 'All states'}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Currency</label>
              <select
                data-testid="search-filter-currency"
                style={{ ...inputStyle, cursor: 'pointer' }}
                value={filters.currency}
                onChange={e => updateFilter('currency', e.target.value)}
              >
                {CURRENCIES.map(c => (
                  <option key={c} value={c}>{c || 'All currencies'}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Created From</label>
              <input
                data-testid="search-filter-date-from"
                type="date"
                style={inputStyle}
                value={filters.date_from}
                onChange={e => updateFilter('date_from', e.target.value)}
              />
            </div>
            <div>
              <label style={labelStyle}>Created To</label>
              <input
                data-testid="search-filter-date-to"
                type="date"
                style={inputStyle}
                value={filters.date_to}
                onChange={e => updateFilter('date_to', e.target.value)}
              />
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              type="submit"
              data-testid="proforma-search-submit"
              disabled={loading}
              style={{
                padding: '9px 24px', borderRadius: 6, border: 'none',
                background: 'var(--accent)', color: 'var(--accent-text)',
                fontWeight: 700, fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer',
                fontFamily: 'inherit', opacity: loading ? 0.7 : 1,
              }}
            >
              {loading ? 'Searching...' : 'Search'}
            </button>
            <button
              type="button"
              data-testid="proforma-search-clear"
              onClick={handleClear}
              style={{
                padding: '9px 18px', borderRadius: 6,
                border: '1px solid var(--border)', background: 'var(--card)',
                color: 'var(--text-2)', fontWeight: 600, fontSize: 13,
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Clear
            </button>
          </div>
        </div>
      </form>

      {/* Loading state */}
      {loading && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}
             data-testid="proforma-search-loading">
          Searching proforma drafts...
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div style={{
          padding: 20, textAlign: 'center', borderRadius: 8,
          background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
          color: 'var(--badge-red-text)', fontSize: 13,
        }} data-testid="proforma-search-error">
          Search failed: {error}
          <br />
          <button onClick={() => doSearch(page)}
            style={{ marginTop: 10, cursor: 'pointer', fontSize: 12, padding: '6px 14px',
              borderRadius: 4, border: '1px solid var(--badge-red-border)',
              background: 'transparent', color: 'var(--badge-red-text)' }}>
            Retry
          </button>
        </div>
      )}

      {/* Empty state — searched but no results */}
      {searched && !loading && !error && results && results.length === 0 && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-2)' }}
             data-testid="proforma-search-empty">
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>No results found</div>
          <div style={{ fontSize: 13 }}>Try adjusting your search filters or clearing them to see all drafts.</div>
        </div>
      )}

      {/* Results table */}
      {!loading && !error && results && results.length > 0 && (
        <div data-testid="proforma-search-results">
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10 }}>
            {total} result{total !== 1 ? 's' : ''} found &middot; Page {page} of {totalPages}
          </div>

          <div style={{
            background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
            overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                  {['Client', 'Batch', 'State', 'Currency', 'Proforma #', 'wFirma ID', 'Created', 'Updated'].map(h => (
                    <th key={h} style={{
                      padding: '12px 14px', textAlign: 'left', fontSize: 10.5,
                      fontWeight: 700, color: 'var(--text-3)',
                      letterSpacing: '0.08em', textTransform: 'uppercase',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr
                    key={r.id || i}
                    data-testid={`proforma-search-row-${i}`}
                    onClick={() => handleRowClick(r)}
                    style={{
                      cursor: 'pointer', borderBottom: '1px solid var(--border-subtle)',
                      transition: 'background 0.1s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                    onMouseLeave={e => e.currentTarget.style.background = ''}
                  >
                    <td style={{ padding: '10px 14px', fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                      {r.client_name || '—'}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-2)', fontFamily: 'monospace' }}>
                      {r.batch_id || '—'}
                    </td>
                    <td style={{ padding: '10px 14px' }}>
                      <ProformaStatusChip status={r.draft_state} />
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
                      {r.currency || '—'}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text)' }}>
                      {r.wfirma_proforma_fullnumber || '—'}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-2)', fontFamily: 'monospace' }}>
                      {r.wfirma_proforma_id || '—'}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-2)' }}>
                      {r.created_at ? r.created_at.replace('T', ' ').slice(0, 16) : '—'}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-2)' }}>
                      {r.updated_at ? r.updated_at.replace('T', ' ').slice(0, 16) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, marginTop: 16 }}
                 data-testid="proforma-search-pagination">
              <button
                data-testid="proforma-search-prev"
                disabled={page <= 1}
                onClick={() => handlePageChange(page - 1)}
                style={{
                  padding: '6px 14px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--card)',
                  color: page <= 1 ? 'var(--text-3)' : 'var(--text)',
                  cursor: page <= 1 ? 'not-allowed' : 'pointer',
                  fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                }}
              >
                Previous
              </button>
              <span style={{ fontSize: 12, color: 'var(--text-2)', padding: '0 8px' }}>
                Page {page} of {totalPages}
              </span>
              <button
                data-testid="proforma-search-next"
                disabled={page >= totalPages}
                onClick={() => handlePageChange(page + 1)}
                style={{
                  padding: '6px 14px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--card)',
                  color: page >= totalPages ? 'var(--text-3)' : 'var(--text)',
                  cursor: page >= totalPages ? 'not-allowed' : 'pointer',
                  fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                }}
              >
                Next
              </button>
            </div>
          )}
        </div>
      )}

      {/* Initial state — not searched yet */}
      {!searched && !loading && !error && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}
             data-testid="proforma-search-initial">
          <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 6 }}>
            Enter search criteria and click Search
          </div>
          <div style={{ fontSize: 12 }}>
            Search across all local proforma drafts by client, batch, state, currency, or date range.
          </div>
        </div>
      )}
    </div>
  );
}

window.ProformaSearchPage = ProformaSearchPage;
