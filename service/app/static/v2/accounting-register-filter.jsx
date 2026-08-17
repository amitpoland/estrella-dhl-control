// ─────────────────────────────────────────────────────────────────────────────
// AccountingRegisterFilter — shared Year/Month/From/To/Search/Currency/Status
// bar for Accounting Hub document registers (Insurance Export pattern authority).
// Zero client-side monetary math. Period Apply commits custom ranges only.
// ─────────────────────────────────────────────────────────────────────────────

const ARF_MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function arfPad2(n) {
  return n < 10 ? `0${n}` : `${n}`;
}

function arfIsoDate(d) {
  return `${d.getFullYear()}-${arfPad2(d.getMonth() + 1)}-${arfPad2(d.getDate())}`;
}

function arfMonthlyPeriod(year, month) {
  if (!month) {
    return { from: `${year}-01-01`, to: `${year}-12-31` };
  }
  const today = new Date();
  const isCurrent = year === today.getFullYear() && month === today.getMonth() + 1;
  const lastDay = new Date(year, month, 0).getDate();
  return {
    from: `${year}-${arfPad2(month)}-01`,
    to: isCurrent ? arfIsoDate(today) : `${year}-${arfPad2(month)}-${arfPad2(lastDay)}`,
  };
}

function arfDefaultYear() {
  return new Date().getFullYear();
}

function arfYearOptions(now) {
  const y = (now || new Date()).getFullYear();
  const out = [];
  for (let i = y + 1; i >= y - 5; i--) out.push(i);
  return out;
}

/**
 * Shared register filter bar.
 * props:
 *   testIdPrefix, pageSize (default 20), showSearch, showCurrency, showStatus,
 *   statusOptions, currencyOptions, onChange({ period, search, currency, status, page }),
 *   page, hasMore, loading, onPage(prev|next)
 */
function AccountingRegisterFilter(props) {
  const p = props || {};
  const tid = p.testIdPrefix || 'acc-reg';
  const pageSize = p.pageSize != null ? p.pageSize : 20;
  const now = new Date();

  const [periodMode, setPeriodMode] = React.useState('monthly');
  const [year, setYear] = React.useState(arfDefaultYear());
  const [month, setMonth] = React.useState(now.getMonth() + 1);
  const [customFrom, setCustomFrom] = React.useState('');
  const [customTo, setCustomTo] = React.useState('');
  const [periodError, setPeriodError] = React.useState(null);
  const [period, setPeriod] = React.useState(arfMonthlyPeriod(now.getFullYear(), now.getMonth() + 1));
  const [search, setSearch] = React.useState('');
  const [currency, setCurrency] = React.useState('');
  const [status, setStatus] = React.useState('');
  const [page, setPage] = React.useState(1);

  const emit = React.useCallback((next) => {
    if (typeof p.onChange === 'function') {
      p.onChange({
        period: next.period || period,
        search: next.search != null ? next.search : search,
        currency: next.currency != null ? next.currency : currency,
        status: next.status != null ? next.status : status,
        page: next.page != null ? next.page : page,
        pageSize,
        year: next.year != null ? next.year : year,
      });
    }
  }, [p.onChange, period, search, currency, status, page, pageSize, year]);

  React.useEffect(() => {
    emit({ period, search, currency, status, page, year });
  }, [period, search, currency, status, page, year]);

  const applyMonthly = (y, m) => {
    setYear(y); setMonth(m); setPeriodError(null);
    const np = arfMonthlyPeriod(y, m);
    setPeriod(np); setPage(1);
  };

  const changeMode = (mode) => {
    setPeriodMode(mode); setPeriodError(null);
    if (mode === 'custom') {
      setCustomFrom(period.from);
      setCustomTo(period.to);
    } else {
      const np = arfMonthlyPeriod(year, month);
      setPeriod(np); setPage(1);
    }
  };

  const stepMonth = (dir) => {
    if (!month) { applyMonthly(year + dir, 0); return; }
    let m = month + dir; let y = year;
    if (m < 1) { m = 12; y = y - 1; }
    if (m > 12) { m = 1; y = y + 1; }
    applyMonthly(y, m);
  };

  const goToday = () => {
    const d = new Date();
    setPeriodMode('monthly');
    applyMonthly(d.getFullYear(), d.getMonth() + 1);
  };

  const applyCustom = () => {
    if (!customFrom || !customTo) {
      setPeriodError('Enter both a start and an end date.');
      return;
    }
    if (customFrom > customTo) {
      setPeriodError('Date from must not be after date to.');
      return;
    }
    setPeriodError(null);
    setPeriod({ from: customFrom, to: customTo });
    setPage(1);
  };

  const inputStyle = {
    background: 'var(--surface, var(--card))', border: '1px solid var(--border)',
    color: 'var(--text)', borderRadius: 4, padding: '4px 8px', fontSize: 11,
  };
  const btnOutline = {
    background: 'transparent', border: '1px solid var(--border)',
    color: 'var(--text-2)', borderRadius: 4, padding: '5px 10px',
    fontSize: 11, fontWeight: 600, cursor: 'pointer',
  };
  const btnDis = { ...btnOutline, opacity: 0.45, cursor: 'not-allowed' };

  const statusOpts = p.statusOptions || ['', 'Outstanding', 'Paid', 'draft', 'approved', 'posted'];
  const currencyOpts = p.currencyOptions || ['', 'PLN', 'EUR', 'USD', 'GBP'];

  return (
    <div data-testid={`${tid}-filter-root`} style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8,
      padding: '10px 12px', marginBottom: 12, borderRadius: 8,
      background: 'var(--surface-2, var(--bg-subtle))', border: '1px solid var(--border)',
    }}>
      <span style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Period</span>
      <select data-testid={`${tid}-period-mode`} value={periodMode} onChange={(e) => changeMode(e.target.value)} style={inputStyle}>
        <option value="monthly">Monthly</option>
        <option value="custom">Custom range</option>
        <option value="year">Year only</option>
      </select>

      {periodMode === 'monthly' && (
        <React.Fragment>
          <select data-testid={`${tid}-year`} value={year} onChange={(e) => applyMonthly(Number(e.target.value), month)} style={inputStyle}>
            {arfYearOptions(now).map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <select data-testid={`${tid}-month`} value={month} onChange={(e) => applyMonthly(year, Number(e.target.value))} style={inputStyle}>
            <option value={0}>All year</option>
            {ARF_MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
          <button type="button" data-testid={`${tid}-prev`} onClick={() => stepMonth(-1)} style={btnOutline}>‹ Prev</button>
          <button type="button" data-testid={`${tid}-today`} onClick={goToday} style={btnOutline}>Today</button>
          <button type="button" data-testid={`${tid}-next`} onClick={() => stepMonth(1)} style={btnOutline}>Next ›</button>
        </React.Fragment>
      )}

      {periodMode === 'year' && (
        <select data-testid={`${tid}-year-only`} value={year} onChange={(e) => {
          const y = Number(e.target.value);
          setYear(y); setPeriod({ from: `${y}-01-01`, to: `${y}-12-31` }); setPage(1);
        }} style={inputStyle}>
          {arfYearOptions(now).map((y) => <option key={y} value={y}>{y}</option>)}
          <option value="all">All Years</option>
        </select>
      )}

      {periodMode === 'custom' && (
        <React.Fragment>
          <label style={{ fontSize: 10.5, color: 'var(--text-3)' }}>From
            <input data-testid={`${tid}-from`} type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} style={{ ...inputStyle, marginLeft: 4 }} />
          </label>
          <label style={{ fontSize: 10.5, color: 'var(--text-3)' }}>To
            <input data-testid={`${tid}-to`} type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} style={{ ...inputStyle, marginLeft: 4 }} />
          </label>
          <button type="button" data-testid={`${tid}-apply`} onClick={applyCustom} style={{ ...btnOutline, background: 'var(--accent)', color: 'var(--accent-text)', borderColor: 'var(--accent)' }}>Apply</button>
        </React.Fragment>
      )}

      <span data-testid={`${tid}-period-label`} style={{ fontSize: 10.5, color: 'var(--text-3)', marginLeft: 4 }}>
        {period.from} → {period.to}
      </span>

      {p.showSearch && (
        <input data-testid={`${tid}-search`} type="search" placeholder="Search…" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          style={{ ...inputStyle, minWidth: 120, marginLeft: 8 }} />
      )}

      {p.showCurrency && (
        <select data-testid={`${tid}-currency`} value={currency} onChange={(e) => { setCurrency(e.target.value); setPage(1); }} style={inputStyle}>
          {currencyOpts.map((c) => <option key={c || 'all'} value={c}>{c || 'All currencies'}</option>)}
        </select>
      )}

      {p.showStatus && (
        <select data-testid={`${tid}-status`} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} style={inputStyle}>
          {statusOpts.map((s) => <option key={s || 'all'} value={s}>{s || 'All statuses'}</option>)}
        </select>
      )}

      <div style={{ flex: 1 }} />

      <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{pageSize}/page</span>
      <button type="button" data-testid={`${tid}-page-prev`} disabled={p.loading || page <= 1}
        onClick={() => setPage((pg) => Math.max(1, pg - 1))}
        style={p.loading || page <= 1 ? btnDis : btnOutline}>Previous</button>
      <span data-testid={`${tid}-page-label`} style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 64, textAlign: 'center' }}>Page {page}</span>
      <button type="button" data-testid={`${tid}-page-next`} disabled={p.loading || !p.hasMore}
        onClick={() => setPage((pg) => pg + 1)}
        style={p.loading || !p.hasMore ? btnDis : btnOutline}>Next</button>

      {periodError ? (
        <div data-testid={`${tid}-period-error`} style={{ flexBasis: '100%', fontSize: 10.5, color: 'var(--badge-red-text)' }}>{periodError}</div>
      ) : null}
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.AccountingRegisterFilter = AccountingRegisterFilter;
  window.arfMonthlyPeriod = arfMonthlyPeriod;
}
