// ── Ledgers / Statements module ────────────────────────────────────────
// READ-ONLY. Source of truth: wFirma. No manual edits, no payment posting,
// no invoice correction. Shows statements, balances, aging, and links only.
// ───────────────────────────────────────────────────────────────────────

const LDG_FMT = {
  pln: (n) => 'PLN ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  eur: (n) => 'EUR ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  // Generic money: backend amounts arrive as strings ("1234.00") with an
  // explicit currency — never assume PLN.
  money: (v, ccy) => {
    const n = Number(v);
    if (v === null || v === undefined || v === '' || Number.isNaN(n)) return '—';
    return `${(ccy || '').trim() || ''} ${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
  },
};

// Period authority: LedgersPage owns ONE normalized filter object and every
// window comes from window.resolvePeriod (components.jsx). There is no local
// fallback formula here any more — a second formula is exactly what made the
// period selector look cosmetic (PR-005: single authority ownership).
// statement.json / statement.pdf REQUIRE explicit from/to (routes_ledgers.py
// 400s on ''), so the filter object always carries resolved dates.
const LDG_TODAY = () => new Date().toISOString().slice(0, 10);

// Compact paging — every roster/table on this page uses the same page size.
const LDG_LIST_LIMIT = 20;
const SUP_LIST_LIMIT = 20;
const MA_TABLE_LIMIT = 10;

// AP financial-row identity = (contractor_id, currency). Backend payables grain
// is already one row per pair; the Supplier Ledger roster must select/page by
// the same composite key so EUR+USD for one contractor never collapse.
const supplierFinancialRowId = (contractorId, currency) =>
  `${contractorId || ''}|${String(currency || '').trim().toUpperCase()}`;
const parseSupplierFinancialRowId = (rowId) => {
  const s = String(rowId || '');
  const i = s.lastIndexOf('|');
  if (i <= 0) return { contractor_id: s, currency: '' };
  return { contractor_id: s.slice(0, i), currency: s.slice(i + 1).toUpperCase() };
};

// AP / MA aging buckets in report order — same keys the backend emits
// (financial_aging.AGING_BUCKETS_WITH_UNAVAILABLE).
const SUP_AGING_BUCKETS = [
  ['not_due', 'not due'], ['b_1_30', '1–30'], ['b_31_60', '31–60'],
  ['b_61_90', '61–90'], ['b_91_180', '91–180'], ['b_181_365', '181–365'],
  ['b_365_plus', '365+'], ['due_date_unavailable', 'due n/a'],
];

// currency_summaries[].aging → the shape LdgAgingStrip renders. The analytics
// layer owns the sum, so this strip and the Management Analysis PDF print the
// same figures — neither of them adds anything up.
const agingStripBuckets = (aging) =>
  SUP_AGING_BUCKETS.map(([k, label]) => ({
    label,
    value: (aging && aging[k]) || '0.00',
    tone: k === 'not_due' || k === 'due_date_unavailable' ? '' : 'red',
  }));

// Shared monthly window helper (same formula as AccountingRegisterFilter).
function ldgMonthlyPeriod(year, month) {
  if (typeof window !== 'undefined' && typeof window.arfMonthlyPeriod === 'function') {
    return window.arfMonthlyPeriod(year, month);
  }
  const y = Number(year); const m = Number(month);
  const pad = (n) => String(n).padStart(2, '0');
  const last = new Date(y, m, 0).getDate();
  return { from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(last)}` };
}

function ldgDefaultActivityPeriod() {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  return { year: y, month: m, periodMode: 'monthly', ...ldgMonthlyPeriod(y, m) };
}

/** Render ledger warning dicts as human text — never String(obj) → [object Object]. */
function formatLedgerWarning(w) {
  if (w == null || w === '') return null;
  if (typeof w === 'string' || typeof w === 'number' || typeof w === 'boolean') {
    const s = String(w);
    return s === '[object Object]' ? null : s;
  }
  if (typeof w !== 'object') return String(w);
  const event = w.event || w.code || '';
  const msg = w.message || w.detail || '';
  const parts = [];
  if (event) parts.push(String(event).replace(/_/g, ' '));
  if (msg && msg !== event) parts.push(String(msg));
  if (w.wfirma_doc_id) parts.push(`doc ${w.wfirma_doc_id}`);
  if (w.linked_invoice) parts.push(`invoice ${w.linked_invoice}`);
  if (w.invoice_id) parts.push(`invoice ${w.invoice_id}`);
  if (w.source) parts.push(`source ${w.source}`);
  if (!parts.length) return 'Data-quality exception (see server logs)';
  return parts.join(' · ');
}

function dedupeLedgerWarnings(warnings) {
  const seen = new Set();
  const out = [];
  (warnings || []).forEach((w) => {
    const text = formatLedgerWarning(w);
    if (!text || text === '[object Object]') return;
    if (seen.has(text)) return;
    seen.add(text);
    out.push(text);
  });
  return out;
}

function formatAccUpstreamError(err) {
  const s = String(err == null ? '' : err);
  if (!s) return 'wFirma temporarily unavailable. Retry shortly.';
  if (/<!DOCTYPE|<html[\s>]|cloudflare/i.test(s)) {
    return 'wFirma temporarily unavailable. Wait a moment, then retry.';
  }
  if (s === '[object Object]') return 'wFirma read failed. Retry shortly.';
  return s.length > 180 ? `${s.slice(0, 177)}…` : s;
}

// ── Source / read-only badges ──────────────────────────────────────────
// mode: 'wfirma' = live/lazy wFirma read; 'local' = reporting projection
function LdgSourceBadge({ mode }) {
  const local = mode === 'local';
  return (
    <span data-testid={local ? 'ldg-source-local' : 'ldg-source-wfirma'} style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 4, fontSize: 9.5, fontWeight: 700,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      background: local ? 'var(--badge-green-bg)' : 'var(--badge-blue-bg)',
      color: local ? 'var(--badge-green-text)' : 'var(--badge-blue-text)',
      border: `1px solid ${local ? 'var(--badge-green-border)' : 'var(--badge-blue-border)'}`,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: local ? 'var(--badge-green-text)' : 'var(--badge-blue-text)' }} />
      {local ? 'Source · local' : 'Source · wFirma'}
    </span>
  );
}
function LdgReadOnlyBadge() {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 4, fontSize: 9.5, fontWeight: 700,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      background: 'var(--bg-subtle)', color: 'var(--text-3)',
      border: '1px solid var(--border)',
    }}>
      🔒 Read-only
    </span>
  );
}

function LdgStatusPill({ status }) {
  const map = {
    'Open':       { bg: 'var(--badge-amber-bg)',   tx: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    'Overdue':    { bg: 'var(--badge-red-bg)',     tx: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
    'Paid':       { bg: 'var(--badge-green-bg)',   tx: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    'Partial':    { bg: 'var(--badge-amber-bg)',   tx: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    'Reconciled': { bg: 'var(--badge-green-bg)',   tx: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    'Pending':    { bg: 'var(--badge-neutral-bg)', tx: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
    // Live /ledgers/clients row states (routes_ledgers.py: outstanding | clear)
    'Outstanding': { bg: 'var(--badge-amber-bg)', tx: 'var(--badge-amber-text)', bd: 'var(--badge-amber-border)' },
    'Clear':       { bg: 'var(--badge-green-bg)', tx: 'var(--badge-green-text)', bd: 'var(--badge-green-border)' },
  };
  const t = map[status] || map['Pending'];
  return (
    <span style={{
      display: 'inline-block', padding: '2px 7px', borderRadius: 3,
      fontSize: 10, fontWeight: 600,
      background: t.bg, color: t.tx, border: `1px solid ${t.bd}`,
    }}>{status}</span>
  );
}

// ── Stat tile ──────────────────────────────────────────────────────────
function LdgStatTile({ label, value, sub, tone, alert }) {
  return (
    <div style={{
      padding: '14px 16px', background: 'var(--card)',
      border: `1px solid ${alert ? 'var(--badge-red-border)' : 'var(--border)'}`,
      borderRadius: 8,
    }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>{label}</div>
      <div style={{
        fontSize: 20, fontWeight: 700, lineHeight: 1.2,
        color: tone === 'red' ? 'var(--badge-red-text)' : tone === 'amber' ? 'var(--badge-amber-text)' : tone === 'green' ? 'var(--badge-green-text)' : 'var(--text)',
        fontFamily: 'monospace',
      }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Period bar — Year / Month / From / To (Accounting register convention)
// POSITION as-of is separate from ACTIVITY From→To. Client Balance roster stays
// all_outstanding as of `as_of`; statement/activity views use From/To.
function LdgPeriodBar({ filters, custom, periodErr, onPeriodMode, onYear, onMonth, onCustom, onAsOf, inert, inertNote }) {
  const inputStyle = {
    marginLeft: 4, padding: '4px 7px', fontSize: 11,
    border: '1px solid var(--border)', borderRadius: 4,
    background: inert ? 'var(--bg-subtle)' : 'var(--bg)', color: 'var(--text)',
  };
  const yNow = new Date().getFullYear();
  const years = Array.from({ length: 11 }, (_, i) => yNow - i);
  const months = [
    [1, 'Jan'], [2, 'Feb'], [3, 'Mar'], [4, 'Apr'], [5, 'May'], [6, 'Jun'],
    [7, 'Jul'], [8, 'Aug'], [9, 'Sep'], [10, 'Oct'], [11, 'Nov'], [12, 'Dec'],
  ];
  const periodMode = filters.periodMode || 'monthly';
  return (
    <div data-testid="ldg-period-bar" style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8,
      padding: '10px 14px', marginBottom: 14, borderRadius: 6,
      border: '1px solid var(--border)', background: 'var(--card)',
    }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Activity</span>
      <select data-testid="ldg-period-mode" disabled={inert} value={periodMode}
        onChange={(e) => onPeriodMode(e.target.value)} style={inputStyle}>
        <option value="monthly">Month</option>
        <option value="custom">Custom range</option>
      </select>
      {periodMode === 'monthly' && (
        <React.Fragment>
          <label style={{ fontSize: 10.5, color: 'var(--text-3)' }}>Year
            <select data-testid="ldg-year" disabled={inert} value={filters.year} onChange={(e) => onYear(Number(e.target.value))} style={inputStyle}>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 10.5, color: 'var(--text-3)' }}>Month
            <select data-testid="ldg-month" disabled={inert} value={filters.month} onChange={(e) => onMonth(Number(e.target.value))} style={inputStyle}>
              {months.map(([n, lab]) => <option key={n} value={n}>{lab}</option>)}
            </select>
          </label>
        </React.Fragment>
      )}
      {periodMode === 'custom' && (
        <React.Fragment>
          <label style={{ fontSize: 10.5, color: 'var(--text-3)' }}>From
            <input type="date" data-testid="ldg-from" value={custom.from} disabled={inert}
              onChange={(e) => onCustom({ ...custom, from: e.target.value })} style={inputStyle} />
          </label>
          <label style={{ fontSize: 10.5, color: 'var(--text-3)' }}>To
            <input type="date" data-testid="ldg-to" value={custom.to} disabled={inert}
              onChange={(e) => onCustom({ ...custom, to: e.target.value })} style={inputStyle} />
          </label>
        </React.Fragment>
      )}
      <span data-testid="ldg-period-window" style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-2)' }}>
        {filters.from} → {filters.to}
      </span>
      <span style={{ width: 1, height: 18, background: 'var(--border)', margin: '0 4px' }} />
      <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Position as-of</span>
      <input type="date" data-testid="ldg-as-of" value={filters.as_of || ''}
        onChange={(e) => onAsOf(e.target.value)}
        style={{ ...inputStyle, background: 'var(--bg)', opacity: 1 }} />
      {periodErr && (
        <div data-testid="ldg-period-error" style={{ flexBasis: '100%', fontSize: 11, color: 'var(--badge-red-text)' }}>
          {periodErr} — showing activity {filters.from} → {filters.to}.
        </div>
      )}
      {inert && inertNote && (
        <div data-testid="ldg-period-inert" style={{ flexBasis: '100%', fontSize: 11, color: 'var(--text-3)' }}>
          {inertNote}
        </div>
      )}
      <div data-testid="ldg-period-semantics" style={{ flexBasis: '100%', fontSize: 10.5, color: 'var(--text-3)' }}>
        Client Balance Open / Overdue = full outstanding position as of the as-of date (due-date aging; not limited to the activity window).
        Statement lines = activity in From→To only.
      </div>
    </div>
  );
}

// ── Header (period bar + sub-tabs + global wFirma sync state) ──────────
function LedgersPage(props) {
  const initialTab = (props && props.initialTab) || 'clients';
  const [tab, setTab] = React.useState(
    initialTab === 'suppliers' || initialTab === 'analysis' || initialTab === 'clients'
      ? initialTab
      : 'clients'
  );
  const [selectedRow, setSelectedRow] = React.useState(null);
  const [focusContractorId, setFocusContractorId] = React.useState('');
  const [focusSupplierId, setFocusSupplierId] = React.useState('');

  // ── THE period authority ──────────────────────────────────────────────
  // Activity From/To (Year/Month or custom) drives statement windows.
  // Position as-of drives Client Balance Open (scope=all_outstanding).
  // Management Analysis opens on the full outstanding portfolio as of today.
  const today = LDG_TODAY();
  const [filters, setFilters] = React.useState(() => {
    const act = ldgDefaultActivityPeriod();
    return {
      periodMode: act.periodMode, year: act.year, month: act.month,
      from: act.from, to: act.to, as_of: today,
      scope: 'all_outstanding', currency: '',
      ar_status: 'outstanding', ap_status: 'outstanding',
    };
  });
  const [custom, setCustom] = React.useState({ from: '', to: '' });
  const [periodErr, setPeriodErr] = React.useState('');
  const patch = (p) => setFilters(f => ({ ...f, ...p }));

  const onPeriodMode = (periodMode) => {
    setPeriodErr('');
    if (periodMode === 'custom') {
      setCustom({ from: filters.from, to: filters.to });
      patch({ periodMode: 'custom' });
      return;
    }
    const p = ldgMonthlyPeriod(filters.year, filters.month);
    patch({ periodMode: 'monthly', from: p.from, to: p.to });
  };

  const onYear = (year) => {
    setPeriodErr('');
    const p = ldgMonthlyPeriod(year, filters.month);
    patch({ year, from: p.from, to: p.to, periodMode: 'monthly' });
  };

  const onMonth = (month) => {
    setPeriodErr('');
    const p = ldgMonthlyPeriod(filters.year, month);
    patch({ month, from: p.from, to: p.to, periodMode: 'monthly' });
  };

  const onCustom = (next) => {
    setCustom(next);
    const p = window.resolvePeriod('custom', next, today);
    if (!p) {
      setPeriodErr(next.from && next.to ? 'From date must be on or before To date' : 'Both dates are required');
      return;
    }
    setPeriodErr('');
    patch({ periodMode: 'custom', from: p.from, to: p.to });
  };

  const onAsOf = (as_of) => {
    if (!as_of) return;
    patch({ as_of });
  };

  // HONEST load model (replaces the old fabricated static sync-age chip):
  // ledger figures are LIVE on-demand wFirma reads via GET /api/v1/ledgers/*.
  // The chip reports the LAST ACTUAL fetch outcome, lifted from
  // ClientLedgerView; Refresh re-runs the real fetch (refreshKey).
  const [loadInfo, setLoadInfo] = React.useState({ status: 'loading', at: null, count: null, error: null });
  const [refreshKey, setRefreshKey] = React.useState(0);
  const _t = (d) => d ? d.toLocaleTimeString('en-GB') : '';
  React.useEffect(() => {
    if (initialTab === 'suppliers' || initialTab === 'analysis' || initialTab === 'clients') {
      setTab(initialTab);
    }
  }, [initialTab]);

  const openClientLedger = (contractorId) => {
    setFocusContractorId(contractorId || '');
    setTab('clients');
    setSelectedRow(null);
  };

  const openSupplierLedger = (contractorId, currency) => {
    setFocusSupplierId(supplierFinancialRowId(contractorId, currency));
    setTab('suppliers');
    setSelectedRow(null);
  };

  return (
    <div>
      {/* Read-only banner */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderRadius: 6, marginBottom: 16,
        background: 'var(--bg-subtle)', border: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <LdgReadOnlyBadge />
          <LdgSourceBadge mode={tab === 'analysis' ? 'local' : 'wfirma'} />
          <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
            {tab === 'analysis'
              ? 'Management Analysis reads the local financial reporting projection (SOURCE-LOCAL). Statement drawers remain live wFirma reads.'
              : 'Client / Supplier balances and statements are live wFirma reads. No values can be edited here. Posting payments and corrections must be done in wFirma.'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {loadInfo.status === 'loading' && (
            <span data-testid="ldg-load-status" style={{ fontSize: 11, color: 'var(--text-3)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--text-3)' }} />
              {tab === 'analysis' ? 'Loading local projection…' : 'Loading from wFirma…'}
            </span>
          )}
          {loadInfo.status === 'ok' && (
            <span data-testid="ldg-load-status" title={tab === 'analysis' ? 'Local projection read' : 'Figures are live wFirma reads made at this time'} style={{ fontSize: 11, color: 'var(--badge-green-text)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-green-text)' }} />
              {tab === 'analysis' ? `Local projection · loaded ${_t(loadInfo.at)}` : `Live wFirma read · loaded ${_t(loadInfo.at)}`}
            </span>
          )}
          {loadInfo.status === 'error' && (
            <span data-testid="ldg-load-status" style={{ fontSize: 11, color: 'var(--badge-red-text)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-red-text)' }} />
              {tab === 'analysis' ? 'Local projection read failed' : 'wFirma read failed'}{loadInfo.at ? ` · ${_t(loadInfo.at)}` : ''}
            </span>
          )}
          <window.Btn small variant="outline" data-testid="ldg-refresh"
            onClick={() => { setLoadInfo(p => ({ ...p, status: 'loading' })); setSelectedRow(null); setRefreshKey(k => k + 1); }}>
            {tab === 'analysis' ? '↻ Refresh projection' : '↻ Refresh from wFirma'}
          </window.Btn>
        </div>
      </div>

      <LdgPeriodBar
        filters={filters} custom={custom} periodErr={periodErr}
        onPeriodMode={onPeriodMode} onYear={onYear} onMonth={onMonth}
        onCustom={onCustom} onAsOf={onAsOf}
        inert={tab === 'analysis' && filters.scope === 'all_outstanding'}
        inertNote="Management Analysis is showing the full outstanding portfolio as of the Position as-of date. Switch Scope to Custom Period to apply the activity From/To window." />

      {/* Top-level tab strip — clients / analysis / suppliers share LedgersPage.
          Supplier counts come from live AP reads (no synthetic placeholder). */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0, marginBottom: 18, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'clients',   label: 'Client Ledger',   count: tab === 'clients' ? loadInfo.count : null },
          { id: 'analysis',  label: 'Management Analysis', count: tab === 'analysis' ? loadInfo.count : null },
          { id: 'suppliers', label: 'Supplier Ledger', count: tab === 'suppliers' ? loadInfo.count : null },
        ].map(t => {
          const active = tab === t.id;
          return (
            <button key={t.id} data-testid={`ldg-tab-${t.id}`} onClick={() => { setTab(t.id); setSelectedRow(null); }} style={{
              padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer',
              borderBottom: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
              color: active ? 'var(--text)' : 'var(--text-2)',
              fontSize: 13, fontWeight: active ? 700 : 500, marginBottom: -1,
              display: 'inline-flex', alignItems: 'center', gap: 8,
            }}>
              {t.label}
              {t.count != null && (
                <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', padding: '1px 6px', background: 'var(--bg-subtle)', borderRadius: 3, border: '1px solid var(--border)' }}>{t.count}</span>
              )}
            </button>
          );
        })}

        {/* Right-aligned API checklist link */}
        <div style={{ marginLeft: 'auto', paddingBottom: 6 }}>
          <button onClick={() => window.dispatchEvent(new CustomEvent('ldg:openApiChecklist'))} style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 11, color: 'var(--text-3)', textDecoration: 'underline',
          }}>
            Future endpoints →
          </button>
        </div>
      </div>

      {tab === 'clients' && (
        <ClientLedgerView onSelectRow={setSelectedRow} selectedRow={selectedRow}
          refreshKey={refreshKey} filters={filters}
          focusContractorId={focusContractorId}
          onLoadInfo={(info) => setLoadInfo(info)} />
      )}
      {tab === 'analysis' && (
        <ManagementAnalysisView
          refreshKey={refreshKey} filters={filters} onFilters={patch}
          onOpenLedger={openClientLedger}
          onOpenSupplierLedger={openSupplierLedger}
          onLoadInfo={(info) => setLoadInfo(info)} />
      )}
      {tab === 'suppliers' && (
        <SupplierLedgerView
          refreshKey={refreshKey} filters={filters}
          focusSupplierId={focusSupplierId}
          onLoadInfo={(info) => setLoadInfo(info)} />
      )}

      {selectedRow && (
        <StatementDetailDrawer
          row={selectedRow}
          onClose={() => setSelectedRow(null)}
        />
      )}
    </div>
  );
}

// ── CLIENT LEDGER — LIVE (GET /api/v1/ledgers/clients + statement.json) ──
// LDG-1: the previous view rendered four synthetic clients and a synthetic
// statement. Every figure below now comes from the canonical ledger read
// authority (routes_ledgers.py → live wFirma reads). No value is fabricated:
// a failed read renders its own honest state, never a placeholder number.
function ClientLedgerView({ onSelectRow, selectedRow, refreshKey, onLoadInfo, filters, focusContractorId }) {
  const [clients, setClients] = React.useState(null);
  const [listErr, setListErr] = React.useState(null);
  const [detailId, setDetailId] = React.useState('');
  const [detailTab, setDetailTab] = React.useState('statement');
  const [stmt, setStmt] = React.useState({ status: 'idle', data: null, err: null });
  const [searchQ, setSearchQ] = React.useState('');
  const [currencyFilter, setCurrencyFilter] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('');
  const [listPage, setListPage] = React.useState(1);
  const [listHasMore, setListHasMore] = React.useState(false);
  const period = { from: filters.from, to: filters.to, scope: filters.scope || 'all_outstanding', as_of: filters.as_of || filters.to };

  React.useEffect(() => {
    if (focusContractorId) { setDetailId(focusContractorId); setDetailTab('statement'); }
  }, [focusContractorId]);

  React.useEffect(() => { setListPage(1); }, [period.from, period.to, period.scope, currencyFilter, statusFilter, searchQ]);

  React.useEffect(() => {
    let gone = false;
    setClients(null); setListErr(null);
    const params = {
      limit: LDG_LIST_LIMIT,
      start: (listPage - 1) * LDG_LIST_LIMIT,
      scope: period.scope || 'all_outstanding',
      to: period.as_of || period.to,
    };
    if (period.scope === 'activity') {
      params.from = period.from;
      params.to = period.to;
    }
    if (currencyFilter) params.currency = currencyFilter;
    if (statusFilter) params.status = statusFilter;
    if (searchQ.trim()) params.q = searchQ.trim();
    window.PzApi.listClientBalancesShared(params, { force: refreshKey > 0 })
      .then((r) => {
        if (gone) return;
        const rows = (r && r.rows) || [];
        setClients(rows);
        setListHasMore(rows.length >= LDG_LIST_LIMIT);
        onLoadInfo && onLoadInfo({ status: 'ok', at: new Date(), count: rows.length, error: null });
      })
      .catch((e) => {
        if (gone) return;
        setClients([]);
        setListErr((e && e.message) || 'wFirma read failed');
        onLoadInfo && onLoadInfo({ status: 'error', at: new Date(), count: null, error: (e && e.message) || '' });
      });
    return () => { gone = true; };
  }, [refreshKey, period.from, period.to, period.scope, period.as_of, currencyFilter, statusFilter, searchQ, listPage]);

  const detailClient = (clients || []).find((x) => x.contractor_id === detailId) || null;

  // Lazy statement — only when detail panel open (not for every visible roster row).
  React.useEffect(() => {
    if (!detailId) { setStmt({ status: 'idle', data: null, err: null }); return; }
    if (detailTab === 'info') { setStmt({ status: 'idle', data: null, err: null }); return; }
    let gone = false;
    setStmt({ status: 'loading', data: null, err: null });
    const w = period;
    window.EstrellaShared.apiFetch(`/api/v1/ledgers/clients/${encodeURIComponent(detailId)}/statement.json?from=${w.from}&to=${w.to}`)
      .then((r) => { if (!gone) setStmt({ status: 'ok', data: r, err: null }); })
      .catch((e) => { if (!gone) setStmt({ status: 'error', data: null, err: (e && e.message) || 'statement read failed' }); });
    return () => { gone = true; };
  }, [detailId, detailTab, refreshKey, period.from, period.to]);

  if (clients === null) {
    return <div data-testid="ldg-clients-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>Loading client balances (local projection)…</div>;
  }
  if (listErr && clients.length === 0) {
    return (
      <div data-testid="ldg-clients-error" style={{ padding: 30, textAlign: 'center', border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 4 }}>Could not load client balances</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)' }}>{listErr} · use ↻ Refresh to retry</div>
      </div>
    );
  }

  const moneyCell = (v, ccy, avail) => {
    if (!avail) return <td style={{ padding: '8px 10px', textAlign: 'right', color: 'var(--text-3)' }}>—</td>;
    return <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace' }}>{LDG_FMT.money(v, ccy)}</td>;
  };

  return (
    <div data-testid="ldg-clients-root">
      <div data-testid="ldg-clients-toolbar" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <input data-testid="ldg-filter-search" type="search" placeholder="Search clients…" value={searchQ}
          onChange={(e) => setSearchQ(e.target.value)}
          style={{ padding: '6px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', minWidth: 180 }} />
        <select data-testid="ldg-clients-currency" value={currencyFilter} onChange={(e) => setCurrencyFilter(e.target.value)}
          style={{ padding: '6px 8px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)' }}>
          {['', 'PLN', 'EUR', 'USD', 'GBP'].map((c) => <option key={c || 'all'} value={c}>{c || 'All currencies'}</option>)}
        </select>
        <select data-testid="ldg-clients-status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          style={{ padding: '6px 8px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)' }}>
          {['', 'outstanding', 'clear', 'unknown'].map((s) => <option key={s || 'all'} value={s}>{s || 'All statuses'}</option>)}
        </select>
        <span style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 'auto' }}>Sorted: overdue → largest → outstanding → clear · {LDG_LIST_LIMIT}/page</span>
      </div>

      <window.Card style={{ padding: 0, overflow: 'auto', marginBottom: detailId ? 14 : 0 }}>
        <table data-testid="ldg-clients-balance-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left' }}>
              {['Client', 'Open (as-of)', 'Overdue (due-date)', 'Invoiced (period)', 'Cur', 'State', ''].map((h) => (
                <th key={h || 'act'} style={{ padding: '10px 12px', fontSize: 10, color: 'var(--text-3)', fontWeight: 700, textAlign: ['Open (as-of)', 'Overdue (due-date)', 'Invoiced (period)'].includes(h) ? 'right' : 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {clients.length === 0 && (
              <tr><td colSpan={7} data-testid="ldg-clients-empty" style={{ padding: 28, textAlign: 'center', color: 'var(--text-3)' }}>No clients match filters.</td></tr>
            )}
            {clients.map((x) => (
              <tr key={x.contractor_id} data-testid="acc-balance-row" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '8px 10px', fontWeight: 600 }}>{x.name || x.contractor_id}</td>
                {moneyCell(x.open, x.currency, x.balance_available !== false)}
                {moneyCell(x.overdue_due_date != null ? x.overdue_due_date : x.overdue_invoice_age, x.currency, x.balance_available !== false && (x.overdue_due_date != null || x.overdue_invoice_age != null))}
                {moneyCell(x.ytd_invoiced, x.currency, x.balance_available !== false && x.ytd_invoiced != null)}
                <td style={{ padding: '8px 10px' }}>{x.currency || '—'}</td>
                <td style={{ padding: '8px 10px' }}>{x.balance_available ? <LdgStatusPill status={x.state === 'outstanding' ? 'Outstanding' : x.state === 'clear' ? 'Clear' : x.state} /> : 'unknown'}</td>
                <td style={{ padding: '8px 10px' }}>
                  <window.Btn small variant="outline" data-testid={`ldg-client-open-${x.contractor_id}`}
                    onClick={() => { setDetailId(x.contractor_id); setDetailTab('statement'); }}>
                    Open
                  </window.Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div data-testid="ldg-clients-pager" style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end', padding: '10px 12px', borderTop: '1px solid var(--border-subtle)' }}>
          <button type="button" data-testid="ldg-clients-prev" disabled={listPage <= 1} onClick={() => setListPage((p) => Math.max(1, p - 1))}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: listPage <= 1 ? 'not-allowed' : 'pointer', opacity: listPage <= 1 ? 0.45 : 1 }}>Previous</button>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Page {listPage} · {LDG_LIST_LIMIT}/page</span>
          <button type="button" data-testid="ldg-clients-next" disabled={!listHasMore} onClick={() => setListPage((p) => p + 1)}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: !listHasMore ? 'not-allowed' : 'pointer', opacity: !listHasMore ? 0.45 : 1 }}>Next</button>
        </div>
      </window.Card>

      {detailClient && (
        <ClientDetailPanel
          client={detailClient}
          stmt={stmt}
          period={period}
          tab={detailTab}
          onTab={setDetailTab}
          onClose={() => setDetailId('')}
          onRowClick={onSelectRow}
          selectedId={selectedRow && selectedRow.id}
        />
      )}
    </div>
  );
}

function ClientDetailPanel({ client, stmt, period, tab, onTab, onClose, onRowClick, selectedId }) {
  const unmatchedCount = React.useMemo(() => {
    if (!stmt || stmt.status !== 'ok' || !stmt.data) return 0;
    const u = stmt.data.unmatched_payments_per_currency || {};
    return Object.values(u).reduce((n, arr) => n + ((arr && arr.length) || 0), 0);
  }, [stmt]);
  const tabs = [
    { id: 'statement', label: 'Statement' },
    { id: 'invoices', label: 'Invoices' },
    { id: 'payments', label: 'Payments' },
    { id: 'unapplied', label: unmatchedCount ? `Unapplied (${unmatchedCount})` : 'Unapplied' },
    { id: 'aging', label: 'Aging' },
    { id: 'info', label: 'Client Info' },
  ];
  return (
    <div data-testid="ldg-client-detail" style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--card)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>{client.name || client.contractor_id}</div>
        <div style={{ flex: 1 }} />
        <button type="button" data-testid="ldg-client-detail-close" onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)', fontSize: 18 }}>×</button>
      </div>
      <div data-testid="ldg-client-tabs" style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', overflowX: 'auto' }}>
        {tabs.map((t) => (
          <button key={t.id} type="button" data-testid={`ldg-client-tab-${t.id}`} onClick={() => onTab(t.id)}
            style={{
              padding: '8px 14px', background: 'none', border: 'none', cursor: 'pointer', fontSize: 11.5, fontWeight: tab === t.id ? 700 : 500,
              borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent', color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
            }}>{t.label}</button>
        ))}
      </div>
      <div style={{ padding: '12px 14px' }}>
        <div style={{ marginBottom: 12 }}>
          <ClientHeaderCard client={client} stmt={stmt} period={period} />
        </div>
        <div data-testid="ldg-position-vs-activity-note" style={{ marginBottom: 12, padding: '8px 12px', fontSize: 11, color: 'var(--text-3)', background: 'var(--bg-subtle)', borderRadius: 6, border: '1px solid var(--border)' }}>
          Activity period ({period.from} → {period.to}) filters the movements listed below.
          Position tiles above remain as-of {period.as_of || period.to} and do not change with the activity window
          unless you change Position as-of.
        </div>
        {tab === 'info' && (
          <div data-testid="ldg-client-info">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, fontSize: 11.5 }}>
              <div><span style={{ color: 'var(--text-3)' }}>Contractor</span><div style={{ fontFamily: 'monospace' }}>{client.contractor_id}</div></div>
              <div><span style={{ color: 'var(--text-3)' }}>Country</span><div>{client.country || '—'}</div></div>
              <div><span style={{ color: 'var(--text-3)' }}>VAT / Tax ID</span><div style={{ fontFamily: 'monospace' }}>{client.vat_id || '—'}</div></div>
              <div><span style={{ color: 'var(--text-3)' }}>Default currency</span><div>{client.currency || '—'}</div></div>
            </div>
          </div>
        )}
        {tab === 'aging' && (
          stmt.status === 'ok' && stmt.data ? (
            (stmt.data.currencies || []).map((ccy) => (
              <LdgAgingStrip key={ccy} testid={`ldg-client-aging-${ccy}`} buckets={agingStripBuckets((stmt.data.aging_per_currency || {})[ccy])} />
            ))
          ) : stmt.status === 'loading' ? (
            <div data-testid="ldg-stmt-loading" style={{ padding: 20, color: 'var(--text-3)' }}>Loading aging…</div>
          ) : (
            <div style={{ color: 'var(--text-3)', fontSize: 12 }}>Aging unavailable — open Statement tab or refresh.</div>
          )
        )}
        {tab === 'unapplied' && (
          <UnappliedPaymentsPanel stmt={stmt} />
        )}
        {(tab === 'statement' || tab === 'invoices' || tab === 'payments') && (
          <ClientStatementTable
            client={client}
            stmt={stmt}
            period={period}
            onRowClick={onRowClick}
            selectedId={selectedId}
            entryFilter={tab === 'invoices' ? 'invoice' : tab === 'payments' ? 'payment' : null}
          />
        )}
      </div>
    </div>
  );
}

function UnappliedPaymentsPanel({ stmt }) {
  if (stmt.status === 'loading' || stmt.status === 'idle') {
    return <div data-testid="ldg-unapplied-loading" style={{ padding: 20, color: 'var(--text-3)', fontSize: 12 }}>Loading unapplied payments…</div>;
  }
  if (stmt.status === 'error') {
    return <div data-testid="ldg-unapplied-error" style={{ padding: 16, color: 'var(--badge-red-text)', fontSize: 12 }}>Unapplied list unavailable — {stmt.err}</div>;
  }
  const u = (stmt.data && stmt.data.unmatched_payments_per_currency) || {};
  const rows = [];
  Object.keys(u).sort().forEach((ccy) => {
    (u[ccy] || []).forEach((p) => rows.push({ ...p, currency: p.currency || ccy }));
  });
  if (!rows.length) {
    return <div data-testid="ldg-unapplied-empty" style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>No unapplied payments for this client in the loaded history.</div>;
  }
  return (
    <window.Card>
      <div data-testid="ldg-unapplied-panel" style={{ padding: '12px 16px' }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Unapplied payments ({rows.length})</div>
        <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginBottom: 10 }}>
          These payments are not matched to a fiscal invoice in the loaded history. They do not silently settle open invoices.
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['Date', 'Payment id', 'Amount', 'Cur', 'Linked invoice'].map((h) => (
                <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 10, color: 'var(--text-3)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={p.wfirma_doc_id || i} data-testid="ldg-unapplied-row" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '8px 10px' }}>{p.date || '—'}</td>
                <td style={{ padding: '8px 10px', fontFamily: 'monospace' }}>{p.wfirma_doc_id || '—'}</td>
                <td style={{ padding: '8px 10px', fontFamily: 'monospace' }}>{LDG_FMT.money(p.value, p.currency)}</td>
                <td style={{ padding: '8px 10px' }}>{p.currency || '—'}</td>
                <td style={{ padding: '8px 10px', fontFamily: 'monospace', color: 'var(--text-3)' }}>{p.linked_invoice || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </window.Card>
  );
}

function ClientHeaderCard({ client: c, stmt, period }) {
  // LDG-1: every KPI reads the /ledgers/clients row (live wFirma) or renders
  // an honest missing state. Credit-limit / KUKE utilisation bars and
  // inventory-exposure tiles from the old mock are NOT rendered as numbers —
  // no ledger authority serves them yet (see backend-pending note below).
  const unavailable = c.balance_available === false;
  const stmtGen = stmt && stmt.status === 'ok' && stmt.data ? (stmt.data.generated_at || '') : '';
  const asOf = period.as_of || period.to;
  const pdfHref = `/api/v1/ledgers/clients/${encodeURIComponent(c.contractor_id)}/statement.pdf?from=${period.from}&to=${period.to}`;
  return (
    <window.Card>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{c.name || c.contractor_id}</div>
            {c.country && <span style={{ fontSize: 10, color: 'var(--text-3)', padding: '2px 6px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 3 }}>{c.country}</span>}
            {c.state && c.state !== 'unknown' && <LdgStatusPill status={c.state === 'outstanding' ? 'Outstanding' : c.state === 'clear' ? 'Clear' : c.state} />}
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--text-3)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>VAT / Tax ID: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.vat_id || '—'}</span></span>
            <span>wFirma contractor: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.contractor_id}</span></span>
            <span data-testid="ldg-client-asof">Position as-of: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{asOf}</span></span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {/* Real authority action: the statement PDF route (existing). */}
          <a href={pdfHref} target="_blank" rel="noopener" data-testid="ldg-statement-pdf"
             style={{ fontSize: 11, fontWeight: 600, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none', background: 'transparent' }}>
            ↓ Statement PDF
          </a>
        </div>
      </div>

      {/* KPI grid — live /ledgers/clients columns only */}
      {unavailable ? (
        <div data-testid="ldg-client-unavailable" style={{ padding: 16, fontSize: 12, color: 'var(--badge-amber-text)' }}>
          Balance unavailable — {c.note || 'wFirma read failed for this contractor'}. Use ↻ Refresh to retry.
        </div>
      ) : (
        <div style={{ padding: 16, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {c.currency === 'multi' ? (
            <LdgStatTile label="Outstanding" value="multi-currency"
              sub={`as-of ${asOf} · per currency: ${Object.entries(c.open_by_currency || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'see statement'}`} />
          ) : (
            <LdgStatTile label="Outstanding" value={LDG_FMT.money(c.open, c.currency)}
              sub={`full open position as-of ${asOf}`} />
          )}
          <LdgStatTile label="Overdue (due-date)" value={c.currency === 'multi' ? 'see statement' : LDG_FMT.money(c.overdue_due_date != null ? c.overdue_due_date : c.overdue_invoice_age, c.currency)}
            sub={(Number(c.overdue_due_date != null ? c.overdue_due_date : c.overdue_invoice_age) || 0) > 0 ? 'unpaid past due date — as-of position' : 'none overdue on due-date basis'}
            tone={(Number(c.overdue_due_date != null ? c.overdue_due_date : c.overdue_invoice_age) || 0) > 0 ? 'amber' : 'green'} />
          <LdgStatTile label="Not Due" value={c.currency === 'multi' ? 'see aging' : LDG_FMT.money(
            c.not_due != null ? c.not_due : Math.max(0, (Number(c.open) || 0) - (Number(c.overdue_due_date != null ? c.overdue_due_date : c.overdue_invoice_age) || 0)),
            c.currency
          )}
            sub="Canonical due-date not-due · as-of position" />
          <LdgStatTile label="Credit Limit" value="—" sub="unavailable — not in wFirma ledger authority" />
        </div>
      )}

      <div data-testid="ldg-credit-kuke-pending" style={{ padding: '8px 16px', borderTop: '1px solid var(--border-subtle)', fontSize: 10.5, color: 'var(--text-3)' }}>
        Credit Limit / KUKE utilisation and Avg Payment Delay: unavailable — not served by the live ledger authority (shown as unavailable, not zero).
        {stmtGen && <span style={{ marginLeft: 10 }}>Statement as-of {stmtGen}.</span>}
      </div>
    </window.Card>
  );
}

// ── Aging strip ────────────────────────────────────────────────────────
function LdgAgingStrip({ buckets, testid }) {
  return (
    <div data-testid={testid} style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Aging</span>
      {buckets.map(b => (
        <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{b.label}</span>
          <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'monospace', color: b.tone === 'red' ? 'var(--badge-red-text)' : b.tone === 'amber' ? 'var(--badge-amber-text)' : 'var(--text)' }}>{b.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Management Analysis / CFO MIS helpers ─────────────────────────────
const MA_CFO_BADGE_TONES = {
  local:   { bg: 'var(--badge-blue-bg)',   tx: 'var(--badge-blue-text)',   bd: 'var(--badge-blue-border)' },
  live:    { bg: 'var(--badge-green-bg)',  tx: 'var(--badge-green-text)',  bd: 'var(--badge-green-border)' },
  fresh:   { bg: 'var(--badge-green-bg)',  tx: 'var(--badge-green-text)',  bd: 'var(--badge-green-border)' },
  stale:   { bg: 'var(--badge-amber-bg)',  tx: 'var(--badge-amber-text)',  bd: 'var(--badge-amber-border)' },
  empty:   { bg: 'var(--badge-neutral-bg)', tx: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
  unknown: { bg: 'var(--badge-neutral-bg)', tx: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
  warn:    { bg: 'var(--badge-red-bg)',    tx: 'var(--badge-red-text)',    bd: 'var(--badge-red-border)' },
  ok:      { bg: 'var(--badge-green-bg)',  tx: 'var(--badge-green-text)',  bd: 'var(--badge-green-border)' },
};

function MaCfoBadge({ label, tone }) {
  const t = MA_CFO_BADGE_TONES[tone] || MA_CFO_BADGE_TONES.unknown;
  return (
    <span data-testid={`ldg-ma-badge-${String(label || '').toLowerCase().replace(/\s+/g, '-')}`} style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 4, fontSize: 9.5, fontWeight: 700,
      letterSpacing: '0.04em', textTransform: 'uppercase',
      background: t.bg, color: t.tx, border: `1px solid ${t.bd}`,
    }}>{label}</span>
  );
}

function MaSection({ testid, title, subtitle, children }) {
  return (
    <section data-testid={testid} style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{subtitle}</div>}
      </div>
      {children}
    </section>
  );
}

function MaCompactEmpty({ testid, msg }) {
  return (
    <div data-testid={testid} style={{
      padding: '14px 16px', borderRadius: 8, border: '1px dashed var(--border)',
      background: 'var(--bg-subtle)', fontSize: 11.5, color: 'var(--text-3)',
    }}>{msg}</div>
  );
}

function MaAgingBars({ buckets, testid, currency }) {
  const nums = buckets.map((b) => Math.max(0, Number(b.value) || 0));
  const max = Math.max(...nums, 1);
  return (
    <div data-testid={testid} style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(72px, 1fr))',
      gap: 10, padding: '12px 14px',
      border: '1px solid var(--border-subtle)', borderRadius: 8, background: 'var(--card)',
    }}>
      {buckets.map((b, i) => {
        const pct = Math.round((nums[i] / max) * 100);
        const barColor = b.tone === 'red'
          ? 'var(--badge-red-text)'
          : b.tone === 'amber'
            ? 'var(--badge-amber-text)'
            : 'var(--accent)';
        return (
          <div key={b.label}>
            <div style={{ fontSize: 9.5, color: 'var(--text-3)', marginBottom: 4 }}>{b.label}</div>
            <div style={{ height: 8, background: 'var(--bg-subtle)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, minWidth: nums[i] > 0 ? 2 : 0, height: '100%', background: barColor, borderRadius: 4 }} />
            </div>
            <div style={{ fontSize: 10.5, fontFamily: 'monospace', marginTop: 4, color: 'var(--text-2)' }}>
              {LDG_FMT.money(b.value, currency)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const maFreshnessTone = (v) => {
  const k = String(v || '').toLowerCase();
  if (k === 'fresh' || k === 'live') return 'fresh';
  if (k === 'stale') return 'stale';
  if (k === 'empty') return 'empty';
  return 'unknown';
};

const maSourceTone = (v) => (String(v || '').toLowerCase() === 'live' ? 'live' : 'local');

const maReconTone = (v) => {
  const k = String(v || '').toLowerCase();
  if (k === 'projection_ok' || k === 'live_wfirma') return 'ok';
  if (k === 'stale_projection' || k === 'unverified' || k === 'unavailable') return 'warn';
  return 'unknown';
};

const maSumTreasuryByCurrency = (rows) => {
  const out = {};
  (rows || []).forEach((r) => {
    const ccy = String(r.currency || '').trim().toUpperCase();
    if (!ccy) return;
    const n = Number(r.closing_balance);
    if (Number.isNaN(n)) return;
    out[ccy] = (out[ccy] || 0) + n;
  });
  return out;
};

// ── Compact ERP statement table — LIVE (statement.json entries) ────────
// LDG-1: renders entries_per_currency / totals_per_currency /
// aging_per_currency from GET /ledgers/clients/{id}/statement.json. The old
// synthetic rows and the fabricated aging strip are gone; every state
// (loading / error / empty) is honest.
function ClientStatementTable({ client, stmt, onRowClick, selectedId, period, entryFilter }) {
  if (stmt.status === 'loading' || stmt.status === 'idle') {
    return <window.Card><div data-testid="ldg-stmt-loading" style={{ padding: 24, textAlign: 'center', fontSize: 12, color: 'var(--text-3)' }}>Loading statement from wFirma…</div></window.Card>;
  }
  if (stmt.status === 'error') {
    return (
      <window.Card>
        <div data-testid="ldg-stmt-error" style={{ padding: 20, fontSize: 12, color: 'var(--badge-red-text)' }}>
          Statement unavailable — {stmt.err}. The row figures above may still be valid; use ↻ Refresh to retry.
        </div>
      </window.Card>
    );
  }
  const d = stmt.data || {};
  const currencies = d.currencies || [];
  const entriesBy = d.entries_per_currency || {};
  const totalsBy = d.totals_per_currency || {};
  const agingBy = d.aging_per_currency || {};
  const pdfHref = `/api/v1/ledgers/clients/${encodeURIComponent(client.contractor_id)}/statement.pdf?from=${period.from}&to=${period.to}`;

  const TYPE_LABEL = {
    opening_balance: 'Opening / B/F',
    invoice: 'Invoice',
    correction: 'Credit Note',
    payment: 'Payment',
    proforma: 'Proforma',
  };
  const agingBuckets = (a) => {
    if (!a) return [];
    const order = [
      'not_due', 'current',
      'b_1_30', '1_30', 'd1_30',
      'b_31_60', '31_60', 'd31_60',
      'b_61_90', '61_90', 'd61_90',
      'b_91_180',
      'b_181_365',
      'b_365_plus', '90_plus', 'd90_plus', 'over_90',
      'due_date_unavailable',
    ];
    const label = (k) => ({
      not_due: 'Not Due', current: 'Not Due',
      b_1_30: '1–30', '1_30': '1–30', d1_30: '1–30',
      b_31_60: '31–60', '31_60': '31–60', d31_60: '31–60',
      b_61_90: '61–90', '61_90': '61–90', d61_90: '61–90',
      b_91_180: '91–180',
      b_181_365: '181–365',
      b_365_plus: '365+', '90_plus': '365+', d90_plus: '365+', over_90: '365+',
      due_date_unavailable: 'due n/a',
    }[k] || k);
    const tone = (k) => (/365|181|91|90|61/.test(k) ? 'red' : /30|60/.test(k) ? 'amber' : null);
    const seen = Object.keys(a).filter(k => k !== 'method' && k !== 'total');
    seen.sort((x, y) => order.indexOf(x) - order.indexOf(y));
    const out = seen.map(k => ({ label: label(k), value: a[k], tone: tone(k) }));
    if (a.total !== undefined) out.push({ label: 'Total', value: a.total });
    return out;
  };

  return (
    <window.Card>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Statement</span>
          <LdgSourceBadge mode="wfirma" />
          <LdgReadOnlyBadge />
          <span data-testid="ldg-stmt-scope-label" style={{ fontSize: 10.5, color: 'var(--badge-amber-text)', fontWeight: 600 }}>
            Opening → period movements → Closing
          </span>
          {d.period && (d.period.from || d.period.to) && (
            <span style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{d.period.from || '…'} → {d.period.to || '…'}</span>
          )}
        </div>
        <a href={pdfHref} target="_blank" rel="noopener" data-testid="ldg-stmt-pdf"
           style={{ fontSize: 11, fontWeight: 600, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none' }}>
          ↓ PDF
        </a>
      </div>

      {currencies.length === 0 && (
        <div data-testid="ldg-stmt-empty" style={{ padding: 24, textAlign: 'center', fontSize: 12, color: 'var(--text-3)' }}>
          No invoices or payments on record for this customer through the selected period.
        </div>
      )}

      {currencies.map(ccy => {
        let entries = entriesBy[ccy] || [];
        if (entryFilter === 'invoice') {
          entries = entries.filter((r) => r.type === 'invoice' || r.type === 'correction' || r.type === 'proforma');
        } else if (entryFilter === 'payment') {
          entries = entries.filter((r) => r.type === 'payment');
        }
        const totals = totalsBy[ccy] || {};
        const movementCount = entries.filter((r) => !r.is_opening_balance).length;
        return (
          <div key={ccy} data-testid={`ldg-stmt-ccy-${ccy}`}>
            <div data-testid={`ldg-stmt-summary-${ccy}`} style={{ padding: '10px 16px', display: 'flex', flexWrap: 'wrap', gap: 16, fontSize: 11.5, borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
              <span>Opening: <strong style={{ fontFamily: 'monospace' }}>{LDG_FMT.money(totals.opening_balance || '0.00', ccy)}</strong></span>
              <span>+ Debits: <strong style={{ fontFamily: 'monospace' }}>{LDG_FMT.money(totals.period_debits || totals.invoiced || '0.00', ccy)}</strong></span>
              <span>− Credits: <strong style={{ fontFamily: 'monospace' }}>{LDG_FMT.money(totals.period_credits || '0.00', ccy)}</strong></span>
              <span>= Closing <span style={{ color: 'var(--text-3)' }}>(as of {period.to})</span>: <strong style={{ fontFamily: 'monospace' }} data-testid={`ldg-stmt-closing-${ccy}`}>{LDG_FMT.money(totals.closing_balance || totals.outstanding || '0.00', ccy)}</strong></span>
            </div>
            <LdgAgingStrip buckets={[
              { label: ccy, value: '' },
              ...agingBuckets(agingBy[ccy]).map(b => ({ ...b, value: LDG_FMT.money(b.value, '') })),
            ]} />
            <div data-testid="ldg-aging-closing-note" style={{ padding: '6px 16px', fontSize: 10.5, color: 'var(--text-3)' }}>
              Aging shows open invoice receivables only; credit notes are excluded from aging buckets. Use Closing balance for the net period-end position.
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                    {['Date', 'Document', 'Type', 'Debit', 'Credit', 'Balance', 'Due', 'Status'].map((h, i) => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: (i >= 3 && i <= 5) ? 'right' : 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {entries.map((r, i) => {
                    const rowId = `${ccy}-${r.wfirma_doc_id || r.type || i}-${i}`;
                    const isSelected = selectedId === rowId;
                    const isBf = r.type === 'opening_balance' || r.is_opening_balance;
                    return (
                      <tr key={rowId}
                        onClick={() => !isBf && onRowClick && onRowClick({ ...r, id: rowId })}
                        style={{ borderBottom: '1px solid var(--border-subtle)', cursor: (!isBf && onRowClick) ? 'pointer' : 'default', background: isBf ? 'var(--bg-subtle)' : (isSelected ? 'var(--bg-subtle)' : 'transparent'), fontWeight: isBf ? 700 : 400 }}>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{r.date || '—'}</td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.doc_number || (r.type === 'payment' ? (r.linked_invoice ? `→ ${r.linked_invoice}` : '(unmatched)') : '—')}</td>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2)' }}>{TYPE_LABEL[r.type] || r.type}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: Number(r.debit) > 0 ? 'var(--text)' : 'var(--text-3)' }}>{Number(r.debit) > 0 ? LDG_FMT.money(r.debit, ccy) : '—'}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: Number(r.credit) > 0 ? 'var(--badge-green-text)' : 'var(--text-3)' }}>{Number(r.credit) > 0 ? LDG_FMT.money(r.credit, ccy) : '—'}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text)' }}>{LDG_FMT.money(r.running_balance, ccy)}</td>
                        <td style={{ padding: '8px 12px', color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{r.due_date || '—'}</td>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2)' }}>{r.status || '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', fontSize: 11.5, background: 'var(--bg-subtle)' }}>
              <span style={{ color: 'var(--text-3)' }}>{movementCount} movement{movementCount === 1 ? '' : 's'} · {ccy} · carried opening + period</span>
              <span style={{ color: 'var(--text)', fontWeight: 700, fontFamily: 'monospace' }} data-testid={`ldg-stmt-outstanding-${ccy}`}>
                Closing balance as of {period.to}: {LDG_FMT.money(totals.closing_balance || totals.outstanding, ccy)}
              </span>
            </div>
          </div>
        );
      })}

      {(() => {
        const warnTexts = dedupeLedgerWarnings(d.warnings);
        if (!warnTexts.length) return null;
        return (
          <div data-testid="ldg-stmt-warnings" style={{ padding: '8px 16px', fontSize: 10.5, color: 'var(--badge-amber-text)', borderTop: '1px solid var(--border-subtle)' }}>
            {warnTexts.map((text, i) => (
              <div key={i} data-testid="ldg-stmt-warning-row">⚠ {text}</div>
            ))}
          </div>
        );
      })()}
    </window.Card>
  );
}

// ── MANAGEMENT ANALYSIS — portfolio receivables + due-date aging ──────────
// Authority: GET /api/v1/ledgers/management-analysis.json (bulk invoices +
// payments). Remaining = shared ledger formula. Drill-down reuses Client Ledger.
function ManagementAnalysisView({ refreshKey, onLoadInfo, filters, onFilters, onOpenLedger, onOpenSupplierLedger }) {
  // Every period/scope/status value lives in the page-level filter object —
  // this view holds only its own free-text search boxes and paging. The old
  // local `asOf` useState snapshotted the period at mount and then silently
  // lagged it; there is nothing left here to go stale.
  const period = { from: filters.from, to: filters.to };
  const scope = filters.scope;
  const asOf = filters.as_of;
  const currency = filters.currency;
  const status = filters.ar_status;
  const apStatus = filters.ap_status;
  const [q, setQ] = React.useState('');
  const [apQ, setApQ] = React.useState('');
  const [localRefresh, setLocalRefresh] = React.useState(0);
  const liveFetchRef = React.useRef(false);
  const [data, setData] = React.useState(null);
  const [apData, setApData] = React.useState(null);
  const [treasury, setTreasury] = React.useState(null);
  const [treasuryErr, setTreasuryErr] = React.useState(null);
  const [opsStatus, setOpsStatus] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [apErr, setApErr] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [arTablePage, setArTablePage] = React.useState(1);
  const [apTablePage, setApTablePage] = React.useState(1);

  // Scope decides the window the server resolves. All Outstanding = the full
  // open portfolio back to the configured floor, as of today (balance-sheet
  // exposure). Custom Period = the dates chosen in the period bar.
  const scopeParams = () => (
    scope === 'all_outstanding'
      ? { scope: 'all_outstanding', as_of: asOf }
      : { scope: 'custom_period', from: period.from, to: period.to, as_of: asOf || period.to }
  );

  React.useEffect(() => {
    let gone = false;
    setLoading(true); setErr(null); setApErr(null);
    onLoadInfo && onLoadInfo({ status: 'loading', at: null, count: null, error: null });
    const params = scopeParams();
    if (currency) params.currency = currency;
    if (status) params.status = status;
    if (liveFetchRef.current) params.refresh = 1;
    const apParams = scopeParams();
    if (currency) apParams.currency = currency;
    if (apStatus) apParams.status = apStatus;
    if (liveFetchRef.current) apParams.refresh = 1;
    Promise.all([
      window.PzApi.getManagementAnalysis(params),
      window.PzApi.getPayablesAnalysis(apParams),
    ])
      .then(([arRes, apRes]) => {
        if (gone) return;
        if (!arRes || arRes.ok === false) {
          throw new Error((arRes && arRes.error) || 'receivables portfolio read failed');
        }
        const body = arRes.data || arRes;
        setData(body);
        if (!apRes || apRes.ok === false) {
          setApData(null);
          setApErr((apRes && apRes.error) || 'payables portfolio read failed');
        } else {
          setApData(apRes.data || apRes);
          setApErr(null);
        }
        setLoading(false);
        liveFetchRef.current = false;
        const nAr = (body && body.customers && body.customers.length) || 0;
        const nAp = (apRes && (apRes.data || apRes).suppliers && (apRes.data || apRes).suppliers.length) || 0;
        onLoadInfo && onLoadInfo({ status: 'ok', at: new Date(), count: nAr + nAp, error: null });
      })
      .catch((e) => {
        if (gone) return;
        setData(null);
        setApData(null);
        setLoading(false);
        liveFetchRef.current = false;
        const msg = (e && e.message) || 'portfolio read failed';
        setErr(msg);
        onLoadInfo && onLoadInfo({ status: 'error', at: new Date(), count: null, error: msg });
      });
    return () => { gone = true; };
  }, [scope, period.from, period.to, asOf, currency, status, apStatus, refreshKey, localRefresh]);

  React.useEffect(() => {
    let gone = false;
    setTreasury(null);
    setTreasuryErr(null);
    if (!asOf) return () => { gone = true; };
    window.EstrellaShared.apiFetch(`/api/v1/treasury/balances?as_of=${encodeURIComponent(asOf)}`)
      .then((body) => {
        if (gone) return;
        setTreasury(body || null);
      })
      .catch((e) => {
        if (gone) return;
        setTreasuryErr((e && e.message) || 'treasury read failed');
      });
    return () => { gone = true; };
  }, [asOf, refreshKey, localRefresh]);

  React.useEffect(() => {
    let gone = false;
    setOpsStatus(null);
    const load = (window.PzApi && typeof window.PzApi.getWfirmaWebhookStatus === 'function')
      ? () => window.PzApi.getWfirmaWebhookStatus()
      : () => window.EstrellaShared.apiFetch('/api/v1/webhooks/wfirma/status').then((d) => ({ ok: true, data: d }));
    load().then((res) => {
      if (gone) return;
      if (!res || res.ok === false) return;
      setOpsStatus(res.data || res);
    }).catch(() => {});
    return () => { gone = true; };
  }, [refreshKey, localRefresh]);

  const reset = () => {
    onFilters({
      scope: 'all_outstanding', currency: '',
      ar_status: 'outstanding', ap_status: 'outstanding', as_of: LDG_TODAY(),
    });
    setQ('');
    setApQ('');
    setArTablePage(1);
    setApTablePage(1);
  };

  React.useEffect(() => { setArTablePage(1); }, [q, scope, currency, status, period.from, period.to]);
  React.useEffect(() => { setApTablePage(1); }, [apQ, scope, currency, apStatus, period.from, period.to]);

  if (loading && !data) {
    return <div data-testid="ldg-ma-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>Loading CFO portfolio…</div>;
  }
  if (err && !data) {
    return (
      <div data-testid="ldg-ma-error" style={{ padding: 30, textAlign: 'center', border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 4 }}>Could not load Management Analysis</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)' }}>{err}</div>
      </div>
    );
  }

  const summaries = (data && data.currency_summaries) || [];
  // The server echoes the window it actually resolved, so the all-outstanding
  // lookback boundary is visible on screen (and in the PDF) instead of silent.
  const resolvedFrom = (data && data.period && data.period.from) || '';
  const cov = (data && data.due_date_coverage) || {};
  const qs = (data && data.query_stats) || {};
  const dq = (data && data.data_quality) || {};
  const health = (data && data.source_health) || {};
  const qLower = (q || '').trim().toLowerCase();
  const rowsAll = ((data && data.customers) || []).filter((r) => {
    if (!qLower) return true;
    return String(r.customer_name || '').toLowerCase().includes(qLower);
  });
  // Table paging only — KPI currency_summaries remain full filtered portfolio.
  const arTotalPages = Math.max(1, Math.ceil(rowsAll.length / MA_TABLE_LIMIT) || 1);
  const arPageSafe = Math.min(arTablePage, arTotalPages);
  const rows = rowsAll.slice((arPageSafe - 1) * MA_TABLE_LIMIT, arPageSafe * MA_TABLE_LIMIT);

  // One params object for the PDF, built from the same filter values the two
  // JSON reads above used. AR and AP status travel separately because the one
  // report renders both portfolios.
  const pdfParams = Object.assign(scopeParams(), {
    currency: currency || '', status: status || '', ap_status: apStatus || '',
  });

  const moneyCell = (v, ccy) => (
    <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
      {LDG_FMT.money(v, ccy)}
    </td>
  );

  const apSummaries = (apData && apData.currency_summaries) || [];
  const apCov = (apData && apData.due_date_coverage) || {};
  const apQs = (apData && apData.query_stats) || {};
  const apDq = (apData && apData.data_quality) || {};
  const apHealth = (apData && apData.source_health) || {};
  const apQLower = (apQ || '').trim().toLowerCase();
  const apRowsAll = ((apData && apData.suppliers) || []).filter((r) => {
    if (!apQLower) return true;
    return String(r.supplier_name || '').toLowerCase().includes(apQLower);
  });
  const apTotalPages = Math.max(1, Math.ceil(apRowsAll.length / MA_TABLE_LIMIT) || 1);
  const apPageSafe = Math.min(apTablePage, apTotalPages);
  const apRows = apRowsAll.slice((apPageSafe - 1) * MA_TABLE_LIMIT, apPageSafe * MA_TABLE_LIMIT);

  const arSource = data.source || qs.source || 'local';
  const arFreshness = data.freshness || 'unknown';
  const arRecon = data.reconciliation_status || 'unknown';
  const projection = data.projection || {};
  const liquidityByCcy = maSumTreasuryByCurrency(treasury && treasury.rows);
  const treasuryHasRows = Boolean(treasury && (treasury.rows || []).length > 0);
  const arNetByCcy = Object.fromEntries(summaries.map((s) => [s.currency, Number(s.net_position)]));
  const apNetByCcy = Object.fromEntries(apSummaries.map((s) => [s.currency, Number(s.net_payable)]));
  const wcCurrencies = [...new Set([...Object.keys(arNetByCcy), ...Object.keys(apNetByCcy)])].sort();

  const DQ_LABELS = {
    paymentdate_missing: 'Missing due date (AR)',
    missing_payment_date: 'Missing due date (AP)',
    unmatched_payment: 'Unmatched payment',
    orphan_expense_payment: 'Payment linked to expense outside window',
    invoice_with_empty_id: 'Invoice missing identifier',
    expense_with_empty_id: 'Expense missing identifier',
    missing_contractor_id: 'Missing contractor identity',
    unsupported_currency: 'Unsupported currency',
    duplicate_expense_id: 'Duplicate expense id',
    duplicate_payment_id_ignored: 'Duplicate payment id ignored',
    invoice_currency_missing: 'Invoice currency missing',
    malformed_amount: 'Malformed amount',
    invalid_monetary_field: 'Invalid monetary field',
    proforma_excluded_from_fiscal: 'Proforma excluded from fiscal AR',
    contractor_identity_fragment: 'Contractor identity fragmentation',
  };
  const dqLabel = (k) => DQ_LABELS[k] || String(k).replace(/_/g, ' ');
  const seenExc = {};
  const pushExc = (item) => {
    if (!item || !item.key || seenExc[item.key]) return;
    seenExc[item.key] = true;
    exceptionItems.push(item);
  };

  const exceptionItems = [];
  if (health.ok === false || health.note) {
    pushExc({ key: 'ar-source-health', text: health.note || 'AR source health incomplete (cap/stall)' });
  }
  if (apHealth.ok === false || apHealth.note) {
    pushExc({ key: 'ap-source-health', text: apHealth.note || 'AP source health incomplete' });
  }
  if (arFreshness === 'stale') {
    pushExc({ key: 'ar-stale', text: 'AR local projection is stale — use Refresh (live) for reconciliation' });
  }
  if ((apData && apData.freshness) === 'stale') {
    pushExc({ key: 'ap-stale', text: 'AP local projection is stale — use Refresh (live) for reconciliation' });
  }
  if (arRecon && arRecon !== 'projection_ok' && arRecon !== 'live_wfirma') {
    pushExc({ key: 'ar-recon', text: `AR reconciliation: ${arRecon}` });
  }
  if (apData && apData.reconciliation_status && apData.reconciliation_status !== 'projection_ok' && apData.reconciliation_status !== 'live_wfirma') {
    pushExc({ key: 'ap-recon', text: `AP reconciliation: ${apData.reconciliation_status}` });
  }
  Object.entries(dq).forEach(([k, v]) => {
    if (v == null || v === 0 || v === '0') return;
    pushExc({ key: `ar-dq-${k}`, text: `AR · ${dqLabel(k)}: ${v}` });
  });
  Object.entries(apDq).forEach(([k, v]) => {
    if (v == null || v === 0 || v === '0') return;
    pushExc({ key: `ap-dq-${k}`, text: `AP · ${dqLabel(k)}: ${v}` });
  });
  summaries.filter((s) => s.reconciliation_ok === false).forEach((s) => {
    pushExc({ key: `ar-aging-${s.currency}`, text: `${s.currency} AR aging does not reconcile to net position` });
  });
  apSummaries.filter((s) => s.reconciliation_ok === false).forEach((s) => {
    pushExc({ key: `ap-aging-${s.currency}`, text: `${s.currency} AP aging does not reconcile to net payable` });
  });
  const agingFlag = (s, key, label, prefix) => {
    const n = Number(s[key] || 0);
    if (!n) return;
    pushExc({ key: `${prefix}-aged-${key}-${s.currency}`, text: `${s.currency} ${prefix} ${label}: ${LDG_FMT.money(s[key], s.currency)}` });
  };
  summaries.forEach((s) => {
    agingFlag(s, 'b_91_180', 'aged >90', 'AR');
    agingFlag(s, 'b_181_365', 'severe >180', 'AR');
    agingFlag(s, 'b_365_plus', 'critical >365', 'AR');
  });
  apSummaries.forEach((s) => {
    agingFlag(s, 'b_91_180', 'aged >90', 'AP');
    agingFlag(s, 'b_181_365', 'severe >180', 'AP');
    agingFlag(s, 'b_365_plus', 'critical >365', 'AP');
  });
  if (treasuryErr) {
    pushExc({ key: 'treasury-read', text: `Treasury balances unavailable: ${treasuryErr}` });
  }
  if (treasury && treasury.as_of && asOf && String(treasury.as_of) < String(asOf)) {
    pushExc({ key: 'treasury-stale-close', text: `Bank/cash close as-of ${treasury.as_of} is older than MA as-of ${asOf}` });
  }
  const apSync = (opsStatus && (opsStatus.ap_reporting_sync || (opsStatus.service && opsStatus.service.ap_reporting_sync))) || null;
  if (apSync) {
    if (apSync.stale_watchdog) {
      pushExc({
        key: 'ap-sync-stale-watchdog',
        text: `AP incremental sync lag ${apSync.lag_hours != null ? apSync.lag_hours + 'h' : 'unknown'} exceeds freshness threshold — scheduler should catch up`,
      });
    }
    if (apSync.last_error || String(apSync.status || '').toLowerCase() === 'error') {
      pushExc({
        key: 'ap-sync-error',
        text: `AP incremental sync error: ${String(apSync.last_error || apSync.detail || 'unknown').slice(0, 160)}`,
      });
    }
  }
  const recon = (opsStatus && opsStatus.reconciliation) || {};
  if (Number(recon.events_without_processing || 0) > 0) {
    pushExc({
      key: 'wh009-events-without-processing',
      text: `Webhook WH-009: ${recon.events_without_processing} durable event(s) without processing row`,
    });
  }
  if (Number(recon.stale_pending || 0) > 0) {
    pushExc({
      key: 'webhook-stale-pending',
      text: `Webhook: ${recon.stale_pending} stale pending processing row(s)`,
    });
  }
  const qDead = (opsStatus && opsStatus.queue && opsStatus.queue.dead_letter) || 0;
  if (Number(qDead) > 0) {
    pushExc({ key: 'webhook-dead-letters', text: `Webhook dead letters: ${qDead}` });
  }

  return (
    <div data-testid="ldg-ma-root">
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>Management Analysis</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>
          CFO portfolio — local projection by default, currencies stay separate, read-only.
        </div>
      </div>

      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end',
        marginBottom: 14, padding: '12px 14px', border: '1px solid var(--border)',
        borderRadius: 8, background: 'var(--card)',
      }}>
        <label style={{ fontSize: 11, color: 'var(--text-3)' }}>As of
          <input data-testid="ldg-ma-asof" type="date" value={asOf} onChange={(e) => onFilters({ as_of: e.target.value })}
            style={{ display: 'block', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }} />
        </label>
        <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Scope
          <select data-testid="ldg-ma-scope" value={scope} onChange={(e) => onFilters({ scope: e.target.value })}
            style={{ display: 'block', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }}>
            <option value="all_outstanding">All Outstanding</option>
            <option value="custom_period">Custom Period</option>
          </select>
        </label>
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
          Window
          <div data-testid="ldg-ma-window" style={{ marginTop: 4, fontFamily: 'monospace', color: 'var(--text)' }}>
            {scope === 'all_outstanding'
              ? `all outstanding${resolvedFrom ? ` since ${resolvedFrom}` : ''} → as of ${asOf}`
              : `${period.from} → ${period.to}`}
          </div>
        </div>
        <label style={{ fontSize: 11, color: 'var(--text-3)' }}>Currency
          <select data-testid="ldg-ma-currency" value={currency} onChange={(e) => onFilters({ currency: e.target.value })}
            style={{ display: 'block', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }}>
            <option value="">All</option>
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
            <option value="PLN">PLN</option>
            <option value="CHF">CHF</option>
          </select>
        </label>
        <label style={{ fontSize: 11, color: 'var(--text-3)' }}>AR status
          <select data-testid="ldg-ma-status" value={status} onChange={(e) => onFilters({ ar_status: e.target.value })}
            style={{ display: 'block', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }}>
            <option value="">All</option>
            <option value="outstanding">Outstanding</option>
            <option value="overdue">Overdue</option>
            <option value="credit">Credit balances</option>
          </select>
        </label>
        <label style={{ fontSize: 11, color: 'var(--text-3)' }}>AP status
          <select data-testid="ldg-ma-ap-status" value={apStatus} onChange={(e) => onFilters({ ap_status: e.target.value })}
            style={{ display: 'block', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }}>
            <option value="">All</option>
            <option value="outstanding">Outstanding</option>
            <option value="overdue">Overdue</option>
            <option value="credit">Credits / advances</option>
          </select>
        </label>
        <label style={{ fontSize: 11, color: 'var(--text-3)', flex: '1 1 140px' }}>Customer
          <input data-testid="ldg-ma-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name…"
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }} />
        </label>
        <label style={{ fontSize: 11, color: 'var(--text-3)', flex: '1 1 140px' }}>Supplier
          <input data-testid="ldg-ma-ap-search" value={apQ} onChange={(e) => setApQ(e.target.value)} placeholder="Search name…"
            style={{ display: 'block', width: '100%', marginTop: 4, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }} />
        </label>
        <window.Btn small variant="outline" data-testid="ldg-ma-reset" onClick={reset}>Reset</window.Btn>
        <window.Btn small data-testid="ldg-ma-refresh" onClick={() => { liveFetchRef.current = true; setLocalRefresh((n) => n + 1); }}>Refresh (live)</window.Btn>
        {/* Read-only projection of exactly these filters — the PDF route calls
            the same builders as the JSON above, so it cannot show a different
            number than the screen. */}
        <a href={window.PzApi.managementAnalysisPdfUrl(pdfParams)} target="_blank" rel="noopener"
           data-testid="ldg-ma-pdf"
           style={{ fontSize: 11, fontWeight: 600, padding: '5px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none', background: 'transparent' }}>
          ↓ Management PDF
        </a>
      </div>

      <div data-testid="ldg-ma-meta-badges" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 14 }}>
        <MaCfoBadge label={`Source · ${arSource}`} tone={maSourceTone(arSource)} />
        <MaCfoBadge label={`Freshness · ${arFreshness}`} tone={maFreshnessTone(arFreshness)} />
        <MaCfoBadge label={`Reconciliation · ${arRecon}`} tone={maReconTone(arRecon)} />
        <MaCfoBadge label={`AP source · ${(apData && apData.source) || '—'}`} tone={maSourceTone((apData && apData.source) || arSource)} />
        <MaCfoBadge label={`AP freshness · ${(apData && apData.freshness) || '—'}`} tone={maFreshnessTone((apData && apData.freshness) || '')} />
        <span data-testid="ldg-ma-asof-label" style={{ fontSize: 11, color: 'var(--text-3)' }}>
          Generated {data.generated_at || '—'}
          {data.as_of ? ` · as-of ${data.as_of}` : ''}
        </span>
        {projection && (projection.ar_invoice_rows != null || projection.ap_expense_rows != null) && (
          <span data-testid="ldg-ma-projection" style={{ fontSize: 11, color: 'var(--text-3)' }}>
            · projection AR {projection.ar_invoice_rows ?? '—'} / AP {projection.ap_expense_rows ?? '—'} rows
          </span>
        )}
      </div>

      <MaSection testid="ldg-ma-liquidity" title="1 · Liquidity" subtitle="Cash and bank balances from treasury.sqlite — per currency only.">
        {treasuryHasRows ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
            {Object.entries(liquidityByCcy).sort(([a], [b]) => a.localeCompare(b)).map(([ccy, total]) => (
              <LdgStatTile key={ccy} label={`${ccy} cash & bank`} value={LDG_FMT.money(total, ccy)}
                sub={`${(treasury.rows || []).filter((r) => String(r.currency || '').toUpperCase() === ccy).length} account(s) · as of ${treasury.as_of || asOf}`} />
            ))}
          </div>
        ) : (
          <MaCompactEmpty testid="ldg-ma-liquidity-empty"
            msg={treasuryErr
              ? `Treasury balances could not be loaded (${treasuryErr}). Use Accounting → Treasury to capture balances.`
              : 'No treasury balance snapshots for this as-of date. Capture via Accounting → Treasury (manual entry or bank import).'} />
        )}
      </MaSection>

      <MaSection testid="ldg-ma-receivables" title="2 · Receivables" subtitle="Outstanding customer receivables — each currency reported separately.">
        {summaries.length === 0 ? (
          <MaCompactEmpty testid="ldg-ma-receivables-empty" msg="No receivable currency summaries for current filters." />
        ) : summaries.map((s) => (
          <div key={s.currency} data-testid={`ldg-ma-ccy-${s.currency}`} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8, color: 'var(--text-2)' }}>{s.currency}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
              <LdgStatTile label="Receivable" value={LDG_FMT.money(s.total_receivable, s.currency)}
                sub={`${arSource} · as of ${data.as_of || asOf} · ${arFreshness}`} />
              <LdgStatTile label="Not Due" value={LDG_FMT.money(s.not_due, s.currency)} />
              <LdgStatTile label="Customer Credits" value={LDG_FMT.money(s.customer_credits, s.currency)} tone="green" />
              <LdgStatTile label="Net position" value={LDG_FMT.money(s.net_position, s.currency)}
                sub={`${s.customers_outstanding} outstanding`} />
            </div>
          </div>
        ))}
      </MaSection>

      <MaSection testid="ldg-ma-overdue-ar" title="3 · Overdue Receivables" subtitle="Past-due customer balances — currency-safe.">
        {summaries.length === 0 ? (
          <MaCompactEmpty testid="ldg-ma-overdue-ar-empty" msg="No overdue receivable data for current filters." />
        ) : summaries.map((s) => (
          <div key={s.currency} data-testid={`ldg-ma-overdue-${s.currency}`} style={{ marginBottom: 10 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
              <LdgStatTile label={`${s.currency} overdue`} value={LDG_FMT.money(s.overdue, s.currency)} tone="red" alert={Number(s.overdue) > 0} />
              <LdgStatTile label="Customers overdue" value={String(s.customers_overdue)} sub={`of ${s.customers_outstanding} outstanding`} />
            </div>
          </div>
        ))}
      </MaSection>

      <MaSection testid="ldg-ma-payables" title="4 · Payables" subtitle="Supplier payables and creditor aging — credits stay outside overdue buckets.">
        {apErr && !apData && (
          <div data-testid="ldg-ma-ap-error" style={{ padding: 16, border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8, marginBottom: 12, fontSize: 12 }}>
            {apErr}
          </div>
        )}
        {!apData && !apErr && (
          <MaCompactEmpty testid="ldg-ma-payables-empty" msg="Payables portfolio not loaded." />
        )}
        {apData && apSummaries.map((s) => (
          <div key={s.currency} data-testid={`ldg-ma-ap-ccy-${s.currency}`} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8, color: 'var(--text-2)' }}>{s.currency}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
              <LdgStatTile label="Supplier Payable" value={LDG_FMT.money(s.gross_payable, s.currency)}
                sub={`${(apData && apData.source) || 'local'} · as of ${(apData && apData.as_of) || asOf} · ${(apData && apData.freshness) || '—'}`} />
              <LdgStatTile label="Overdue Payable" value={LDG_FMT.money(s.overdue, s.currency)} tone="red" alert={Number(s.overdue) > 0} />
              <LdgStatTile label="Not Due" value={LDG_FMT.money(s.not_due, s.currency)} />
              <LdgStatTile label="Supplier Credits" value={LDG_FMT.money(s.supplier_credits, s.currency)} tone="green" />
              <LdgStatTile label="Net Payable" value={LDG_FMT.money(s.net_payable, s.currency)}
                sub={`${s.suppliers_outstanding} outstanding · ${s.suppliers_overdue} overdue`} />
            </div>
          </div>
        ))}
      </MaSection>

      <MaSection testid="ldg-ma-aging" title="5 · Aging / Collections" subtitle="Due-date buckets — bar width is relative within each currency (not cross-currency).">
        {summaries.length === 0 && apSummaries.length === 0 ? (
          <MaCompactEmpty testid="ldg-ma-aging-empty" msg="No aging buckets for current filters." />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {summaries.map((s) => (
              <div key={`ar-${s.currency}`}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', marginBottom: 6 }}>{s.currency} receivables</div>
                <MaAgingBars testid={`ldg-ma-ar-aging-bars-${s.currency}`} currency={s.currency} buckets={agingStripBuckets(s.aging)} />
              </div>
            ))}
            {apSummaries.map((s) => (
              <div key={`ap-${s.currency}`}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', marginBottom: 6 }}>{s.currency} payables</div>
                <MaAgingBars testid={`ldg-ma-ap-aging-bars-${s.currency}`} currency={s.currency} buckets={agingStripBuckets(s.aging)} />
              </div>
            ))}
          </div>
        )}
      </MaSection>

      <MaSection testid="ldg-ma-treasury-trend" title="6 · Treasury trend" subtitle="Historical balance trend requires multiple as-of snapshots.">
        <MaCompactEmpty testid="ldg-ma-treasury-trend-empty"
          msg="No treasury trend series on this screen yet — only point-in-time balances as of the selected date. Trend API / Treasury tab UI pending." />
      </MaSection>

      <MaSection testid="ldg-ma-working-capital" title="7 · Working Capital" subtitle="Net receivable position minus net payables — per currency only (no FX merge).">
        {wcCurrencies.length === 0 ? (
          <MaCompactEmpty testid="ldg-ma-working-capital-empty" msg="Need both AR and AP summaries in the same currency to show working capital." />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
            {wcCurrencies.map((ccy) => {
              const arNet = arNetByCcy[ccy];
              const apNet = apNetByCcy[ccy];
              const hasAr = arNet != null && !Number.isNaN(arNet);
              const hasAp = apNet != null && !Number.isNaN(apNet);
              const wc = hasAr && hasAp ? arNet - apNet : null;
              return (
                <LdgStatTile key={ccy} label={`${ccy} working capital`}
                  value={wc != null ? LDG_FMT.money(wc, ccy) : '—'}
                  sub={hasAr && hasAp
                    ? `AR net ${LDG_FMT.money(arNet, ccy)} − AP net ${LDG_FMT.money(apNet, ccy)}`
                    : hasAr ? `AR net only (${LDG_FMT.money(arNet, ccy)})` : hasAp ? `AP net only (${LDG_FMT.money(apNet, ccy)})` : '—'} />
              );
            })}
          </div>
        )}
      </MaSection>

      <MaSection testid="ldg-ma-currency-exposure" title="8 · Currency Exposure" subtitle="Native-currency AR, AP, and Treasury only — no FX merge. Inventory valuation has no EJ Dashboard authority.">
        {(() => {
          const cash = liquidityByCcy || {};
          const ccys = [...new Set([
            ...Object.keys(arNetByCcy),
            ...Object.keys(apNetByCcy),
            ...Object.keys(cash),
          ])].sort();
          if (ccys.length === 0) {
            return (
              <MaCompactEmpty testid="ldg-ma-currency-exposure-empty"
                msg="No AR, AP, or Treasury balances for this as-of — nothing to expose by currency." />
            );
          }
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {ccys.map((ccy) => {
                const ar = arNetByCcy[ccy];
                const ap = apNetByCcy[ccy];
                const liq = cash[ccy];
                return (
                  <div key={ccy} data-testid={`ldg-ma-exposure-${ccy}`} style={{ marginBottom: 4 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8, color: 'var(--text-2)' }}>{ccy}</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
                      <LdgStatTile label="AR exposure" value={ar != null && !Number.isNaN(ar) ? LDG_FMT.money(ar, ccy) : '—'}
                        sub={`Net receivables · ${(data && data.source) || 'local'}`} />
                      <LdgStatTile label="AP exposure" value={ap != null && !Number.isNaN(ap) ? LDG_FMT.money(ap, ccy) : '—'}
                        sub={`Net payables · ${(apData && apData.source) || 'local'}`} />
                      <LdgStatTile label="Treasury exposure" value={liq != null && !Number.isNaN(liq) ? LDG_FMT.money(liq, ccy) : '—'}
                        sub={`Cash & bank · as of ${(treasury && treasury.as_of) || asOf || '—'}`} />
                      <LdgStatTile label="Inventory exposure" value="—"
                        sub="Unavailable — no inventory valuation authority in EJ Dashboard" />
                    </div>
                  </div>
                );
              })}
              <div data-testid="ldg-ma-currency-exposure-note" style={{ fontSize: 11, color: 'var(--text-3)' }}>
                Native currencies only. Do not sum PLN+EUR+USD+CHF. Inventory stays unavailable until a named valuation authority exists (not invented here).
              </div>
            </div>
          );
        })()}
      </MaSection>

      <MaSection testid="ldg-ma-exceptions" title="9 · Exceptions" subtitle="Source health, data quality, stale projection, AP sync, webhook watchdogs, and reconciliation flags.">
        {exceptionItems.length === 0 ? (
          <MaCompactEmpty testid="ldg-ma-exceptions-none" msg="No exceptions flagged for the current portfolio." />
        ) : (
          <ul data-testid="ldg-ma-exceptions-list" style={{ margin: 0, padding: '12px 16px 12px 32px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--card)', fontSize: 11.5, color: 'var(--text-2)' }}>
            {exceptionItems.map((item) => (
              <li key={item.key} data-testid={`ldg-ma-exception-${item.key}`}>{item.text}</li>
            ))}
          </ul>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          <span data-testid="ldg-ma-health">
            AR {health.ok === false ? '⚠️ incomplete' : 'healthy'}
            {qs.duration_ms != null ? ` · ${qs.duration_ms} ms` : ''}
            {qs.invoice_api_calls != null ? ` · inv ${qs.invoice_api_calls}` : ''}
            {qs.payment_api_calls != null ? ` · pay ${qs.payment_api_calls}` : ''}
          </span>
          {apData && (
            <span data-testid="ldg-ma-ap-health">
              AP {apHealth.ok === false ? '⚠️ incomplete' : 'healthy'}
              {apQs.expense_api_calls != null ? ` · exp ${apQs.expense_api_calls}` : ''}
            </span>
          )}
          <span data-testid="ldg-ma-due-coverage">
            Due-date coverage {cov.open_coverage_pct == null ? '—' : `${cov.open_coverage_pct}%`}
          </span>
          {apData && (
            <span data-testid="ldg-ma-ap-due-coverage">
              AP due coverage {apCov.open_coverage_pct == null ? '—' : `${apCov.open_coverage_pct}%`}
            </span>
          )}
        </div>
      </MaSection>

      <MaSection testid="ldg-ma-ar-table-section" title="Receivables detail" subtitle="Drill-down to Client Ledger. KPIs above = full filtered portfolio.">
      <window.Card style={{ padding: 0, overflow: 'auto' }}>
        <table data-testid="ldg-ma-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5, minWidth: 960 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left' }}>
              {['Customer', 'Ccy', 'Credit', 'Not Due', '1–30', '31–60', '61–90', '91–180', '181–365', '365+', 'Outstanding', 'Oldest Due', 'Last Payment', ''].map((h) => (
                <th key={h} style={{ padding: '8px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: 'var(--text-3)', fontWeight: 600, textAlign: h === 'Customer' || h === '' ? 'left' : 'right' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={14} style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>No customers match filters.</td></tr>
            )}
            {rows.map((r) => (
              <tr key={`${r.contractor_id}-${r.currency}`} data-testid={`ldg-ma-row-${r.contractor_id}-${r.currency}`}
                style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '7px 8px', fontWeight: 600 }}>{r.customer_name}</td>
                <td style={{ padding: '7px 8px', textAlign: 'right' }}>{r.currency}</td>
                {moneyCell(r.credit_balance, r.currency)}
                {moneyCell(r.not_due, r.currency)}
                {moneyCell(r.b_1_30, r.currency)}
                {moneyCell(r.b_31_60, r.currency)}
                {moneyCell(r.b_61_90, r.currency)}
                {moneyCell(r.b_91_180, r.currency)}
                {moneyCell(r.b_181_365, r.currency)}
                {moneyCell(r.b_365_plus, r.currency)}
                {moneyCell(r.outstanding, r.currency)}
                <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.oldest_due_date || '—'}</td>
                <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.last_payment_date || '—'}</td>
                <td style={{ padding: '7px 8px' }}>
                  <window.Btn small variant="outline" data-testid={`ldg-ma-open-${r.contractor_id}`}
                    onClick={() => onOpenLedger && onOpenLedger(r.contractor_id)}>
                    Open Ledger
                  </window.Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div data-testid="ldg-ma-ar-pager" style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end', padding: '10px 12px', borderTop: '1px solid var(--border-subtle)', fontSize: 11, color: 'var(--text-3)' }}>
          <span>KPIs = full portfolio · table {MA_TABLE_LIMIT}/page</span>
          <button type="button" data-testid="ldg-ma-ar-prev" disabled={arPageSafe <= 1} onClick={() => setArTablePage(p => Math.max(1, p - 1))}
            style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: arPageSafe <= 1 ? 'not-allowed' : 'pointer', opacity: arPageSafe <= 1 ? 0.45 : 1 }}>Previous</button>
          <span data-testid="ldg-ma-ar-page-label">Page {arPageSafe} of {arTotalPages}</span>
          <button type="button" data-testid="ldg-ma-ar-next" disabled={arPageSafe >= arTotalPages} onClick={() => setArTablePage(p => p + 1)}
            style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: arPageSafe >= arTotalPages ? 'not-allowed' : 'pointer', opacity: arPageSafe >= arTotalPages ? 0.45 : 1 }}>Next</button>
        </div>
      </window.Card>
      </MaSection>

      <MaSection testid="ldg-ma-ap-table-section" title="Payables detail" subtitle="Drill-down to Supplier Ledger.">
        {apErr && !apData && (
          <div data-testid="ldg-ma-ap-error-inline" style={{ padding: 16, border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8, marginBottom: 12, fontSize: 12 }}>
            {apErr}
          </div>
        )}
        {apData && (
          <window.Card style={{ padding: 0, overflow: 'auto' }}>
            <table data-testid="ldg-ma-ap-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5, minWidth: 960 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left' }}>
                  {['Supplier', 'Ccy', 'Credit', 'Not Due', '1–30', '31–60', '61–90', '91–180', '181–365', '365+', 'Net Payable', 'Oldest Due', 'Last Payment', ''].map((h) => (
                    <th key={h} style={{ padding: '8px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: 'var(--text-3)', fontWeight: 600, textAlign: h === 'Supplier' || h === '' ? 'left' : 'right' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {apRows.length === 0 && (
                  <tr><td colSpan={14} style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>No suppliers match filters.</td></tr>
                )}
                {apRows.map((r) => (
                  <tr key={`${r.contractor_id}-${r.currency}`} data-testid={`ldg-ma-ap-row-${r.contractor_id}-${r.currency}`}
                    style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '7px 8px', fontWeight: 600 }}>{r.supplier_name}</td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>{r.currency}</td>
                    {moneyCell(r.credit_balance, r.currency)}
                    {moneyCell(r.not_due, r.currency)}
                    {moneyCell(r.b_1_30, r.currency)}
                    {moneyCell(r.b_31_60, r.currency)}
                    {moneyCell(r.b_61_90, r.currency)}
                    {moneyCell(r.b_91_180, r.currency)}
                    {moneyCell(r.b_181_365, r.currency)}
                    {moneyCell(r.b_365_plus, r.currency)}
                    {moneyCell(r.net_payable, r.currency)}
                    <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.oldest_due_date || '—'}</td>
                    <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.last_payment_date || '—'}</td>
                    <td style={{ padding: '7px 8px' }}>
                      <window.Btn small variant="outline" data-testid={`ldg-ma-ap-open-${r.contractor_id}-${r.currency}`}
                        onClick={() => onOpenSupplierLedger && onOpenSupplierLedger(r.contractor_id, r.currency)}>
                        Open Supplier Ledger
                      </window.Btn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div data-testid="ldg-ma-ap-pager" style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end', padding: '10px 12px', borderTop: '1px solid var(--border-subtle)', fontSize: 11, color: 'var(--text-3)' }}>
              <span>AP KPIs = full portfolio · table {MA_TABLE_LIMIT}/page</span>
              <button type="button" data-testid="ldg-ma-ap-prev" disabled={apPageSafe <= 1} onClick={() => setApTablePage(p => Math.max(1, p - 1))}
                style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: apPageSafe <= 1 ? 'not-allowed' : 'pointer', opacity: apPageSafe <= 1 ? 0.45 : 1 }}>Previous</button>
              <span data-testid="ldg-ma-ap-page-label">Page {apPageSafe} of {apTotalPages}</span>
              <button type="button" data-testid="ldg-ma-ap-next" disabled={apPageSafe >= apTotalPages} onClick={() => setApTablePage(p => p + 1)}
                style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: apPageSafe >= apTotalPages ? 'not-allowed' : 'pointer', opacity: apPageSafe >= apTotalPages ? 0.45 : 1 }}>Next</button>
            </div>
          </window.Card>
        )}
      </MaSection>
    </div>
  );
}

// ── SUPPLIER LEDGER — shared AP facts (statement.json) ─────────────────────
function SupplierLedgerView({ refreshKey, onLoadInfo, filters, focusSupplierId }) {
  const period = { from: filters.from, to: filters.to };
  const asOf = filters.as_of || filters.to;
  const [suppliers, setSuppliers] = React.useState(null);
  const [listErr, setListErr] = React.useState(null);
  const [activeId, setActiveId] = React.useState(focusSupplierId || '');
  const [stmt, setStmt] = React.useState(null);
  const [stmtErr, setStmtErr] = React.useState(null);
  const [stmtLoading, setStmtLoading] = React.useState(false);
  const [supListPage, setSupListPage] = React.useState(1);

  // Changing the period changes the roster, so page 2 of the old roster is
  // meaningless. The client and MA tables already did this; the supplier
  // pager did not, and kept a stale page number across period changes.
  React.useEffect(() => { setSupListPage(1); }, [asOf]);

  React.useEffect(() => {
    let gone = false;
    setSuppliers(null); setListErr(null);
    onLoadInfo && onLoadInfo({ status: 'loading', at: null, count: null, error: null });
    const payParams = {
      scope: 'all_outstanding', as_of: asOf, status: 'outstanding',
    };
    if (refreshKey > 0) payParams.refresh = 1;
    window.PzApi.getPayablesAnalysis(payParams)
      .then((res) => {
        if (gone) return;
        if (!res || res.ok === false) throw new Error((res && res.error) || 'payables read failed');
        const body = res.data || res;
        const rows = body.suppliers || [];
        setSuppliers(rows);
        onLoadInfo && onLoadInfo({ status: 'ok', at: new Date(), count: rows.length, error: null });
        const ids = rows.map((r) => supplierFinancialRowId(r.contractor_id, r.currency));
        const prefer = focusSupplierId && ids.includes(focusSupplierId)
          ? focusSupplierId
          : (activeId && ids.includes(activeId) ? activeId : '');
        if (prefer) setActiveId(prefer);
        // Do not auto-open first supplier — lazy detail on operator click.
      })
      .catch((e) => {
        if (gone) return;
        setListErr((e && e.message) || 'payables read failed');
        onLoadInfo && onLoadInfo({ status: 'error', at: new Date(), count: null, error: (e && e.message) || '' });
      });
    return () => { gone = true; };
  }, [asOf, refreshKey]);

  React.useEffect(() => {
    if (!focusSupplierId || !suppliers || !suppliers.length) return;
    const idx = suppliers.findIndex(
      (s) => supplierFinancialRowId(s.contractor_id, s.currency) === focusSupplierId,
    );
    if (idx < 0) return;
    setActiveId(focusSupplierId);
    setSupListPage(Math.floor(idx / SUP_LIST_LIMIT) + 1);
  }, [focusSupplierId, suppliers]);

  React.useEffect(() => {
    if (!activeId) { setStmt(null); return; }
    const sel = parseSupplierFinancialRowId(activeId);
    if (!sel.contractor_id || !sel.currency) { setStmt(null); return; }
    let gone = false;
    setStmtLoading(true); setStmtErr(null); setStmt(null);
    const opts = { currency: sel.currency };
    if (refreshKey > 0) opts.refresh = true;
    window.PzApi.getSupplierStatement(
      sel.contractor_id, period.from, period.to, asOf, opts,
    )
      .then((res) => {
        if (gone) return;
        if (!res || res.ok === false) throw new Error((res && res.error) || 'statement failed');
        setStmt(res.data || res);
        setStmtLoading(false);
      })
      .catch((e) => {
        if (gone) return;
        setStmtErr((e && e.message) || 'statement failed');
        setStmtLoading(false);
      });
    return () => { gone = true; };
  }, [activeId, period.from, period.to, asOf, refreshKey]);

  if (listErr && !suppliers) {
    return (
      <div data-testid="ldg-suppliers-error" style={{ padding: 30, textAlign: 'center', border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--badge-red-text)' }}>Could not load Supplier Ledger</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)' }}>{listErr}</div>
      </div>
    );
  }
  if (!suppliers) {
    return <div data-testid="ldg-suppliers-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>Loading supplier payables…</div>;
  }
  if (suppliers.length === 0) {
    return <div data-testid="ldg-suppliers-empty" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>No outstanding suppliers in this period.</div>;
  }

  const active = suppliers.find(
    (s) => supplierFinancialRowId(s.contractor_id, s.currency) === activeId,
  ) || null;
  const activeRowId = active ? supplierFinancialRowId(active.contractor_id, active.currency) : '';
  const supTotalPages = Math.max(1, Math.ceil(suppliers.length / SUP_LIST_LIMIT) || 1);
  const supPageSafe = Math.min(supListPage, supTotalPages);
  const pageRows = suppliers.slice((supPageSafe - 1) * SUP_LIST_LIMIT, supPageSafe * SUP_LIST_LIMIT);
  // Statement/PDF are requested with the selected currency — never render a
  // sibling currency block for the same contractor from a multi-ccy payload.
  const stmtCurrencies = active && stmt && stmt.currencies
    ? ((stmt.currencies || []).filter((ccy) => ccy === active.currency))
    : [];

  return (
    <div data-testid="ldg-suppliers-root">
      <window.Card style={{ padding: 0, overflow: 'auto', marginBottom: active ? 14 : 0 }}>
        <table data-testid="ldg-suppliers-balance-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['Supplier', 'Currency', 'Net payable', 'Overdue', 'Not due', ''].map((h) => (
                <th key={h || 'act'} style={{ padding: '10px 12px', fontSize: 10, color: 'var(--text-3)', fontWeight: 700, textAlign: h && h !== 'Supplier' && h !== 'Currency' && h !== '' ? 'right' : 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((s) => {
              const rid = supplierFinancialRowId(s.contractor_id, s.currency);
              return (
                <tr key={rid} data-testid={`ldg-sup-row-${s.contractor_id}-${s.currency}`} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 10px', fontWeight: 600 }}>{s.supplier_name || s.contractor_id}</td>
                  <td style={{ padding: '8px 10px' }}>{s.currency}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace' }}>{LDG_FMT.money(s.net_payable, s.currency)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--badge-red-text)' }}>{LDG_FMT.money(s.overdue, s.currency)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace' }}>{LDG_FMT.money(s.not_due, s.currency)}</td>
                  <td style={{ padding: '8px 10px' }}>
                    <window.Btn small variant="outline" data-testid={`ldg-sup-open-${rid}`} onClick={() => setActiveId(rid)}>Open</window.Btn>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div data-testid="ldg-suppliers-pager" style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end', padding: '10px 12px', borderTop: '1px solid var(--border-subtle)' }}>
          <button type="button" data-testid="ldg-suppliers-prev" disabled={supPageSafe <= 1} onClick={() => setSupListPage((p) => Math.max(1, p - 1))}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: supPageSafe <= 1 ? 'not-allowed' : 'pointer', opacity: supPageSafe <= 1 ? 0.45 : 1 }}>Previous</button>
          <span data-testid="ldg-suppliers-page-label" style={{ fontSize: 11, color: 'var(--text-3)' }}>Page {supPageSafe}/{supTotalPages} · {SUP_LIST_LIMIT}/page</span>
          <button type="button" data-testid="ldg-suppliers-next" disabled={supPageSafe >= supTotalPages} onClick={() => setSupListPage((p) => p + 1)}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: supPageSafe >= supTotalPages ? 'not-allowed' : 'pointer', opacity: supPageSafe >= supTotalPages ? 0.45 : 1 }}>Next</button>
        </div>
      </window.Card>

      {active && (
      <div data-testid="ldg-supplier-detail">
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700 }} data-testid="ldg-supplier-name">{active.supplier_name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)' }} data-testid="ldg-supplier-meta">
              Period {period.from} → {period.to} · <span data-testid="ldg-supplier-active-currency">{active.currency}</span> · open expenses {active.open_expense_count}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <a href={window.PzApi.supplierStatementPdfUrl(active.contractor_id, {
                from: period.from, to: period.to, as_of: asOf,
                currency: active.currency,
              })}
             target="_blank" rel="noopener" data-testid="ldg-supplier-statement-pdf"
             style={{ fontSize: 11, fontWeight: 600, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none', flexShrink: 0 }}>
            ↓ Statement PDF
          </a>
          <button type="button" data-testid="ldg-supplier-close" onClick={() => setActiveId('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)', fontSize: 18 }}>×</button>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 14 }}>
          <LdgStatTile label="Opening / B/F" value={stmt ? LDG_FMT.money((stmt.totals_per_currency && stmt.totals_per_currency[active.currency] || {}).opening_balance, active.currency) : '—'}
            sub="Carried into this period" />
          <LdgStatTile label="Closing" value={stmt ? LDG_FMT.money((stmt.totals_per_currency && stmt.totals_per_currency[active.currency] || {}).closing_balance || (stmt.totals_per_currency && stmt.totals_per_currency[active.currency] || {}).net_payable, active.currency) : LDG_FMT.money(active.net_payable, active.currency)}
            sub={`As of ${period.to}`} />
          <LdgStatTile label="Net Payable" value={LDG_FMT.money(active.net_payable, active.currency)}
            sub="Open position (payables roster)" />
          <LdgStatTile label="Overdue" value={LDG_FMT.money(active.overdue, active.currency)} tone="red" alert={Number(active.overdue) > 0} />
        </div>
        {stmtLoading && <div data-testid="ldg-supplier-stmt-loading" style={{ padding: 20, color: 'var(--text-3)', fontSize: 12 }}>Loading statement…</div>}
        {stmtErr && <div data-testid="ldg-supplier-stmt-error" style={{ padding: 16, border: '1px solid var(--badge-red-border)', borderRadius: 8, color: 'var(--badge-red-text)', fontSize: 12 }}>{stmtErr}</div>}
        {stmt && stmtCurrencies.map((ccy) => {
          const rows = (stmt.entries_per_currency && stmt.entries_per_currency[ccy]) || [];
          const tot = (stmt.totals_per_currency && stmt.totals_per_currency[ccy]) || {};
          const ag = (stmt.aging_per_currency && stmt.aging_per_currency[ccy]) || null;
          return (
            <window.Card key={ccy} style={{ padding: 0, marginBottom: 14, overflow: 'auto' }} data-testid={`ldg-supplier-stmt-${ccy}`}>
              <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700 }}>
                {ccy} · opening {tot.opening_balance || '0.00'} · closing {tot.closing_balance || tot.net_payable} · net {tot.net_payable}
              </div>
              {ag && (
                <div data-testid={`ldg-supplier-aging-${ccy}`} style={{ display: 'flex', flexWrap: 'wrap', gap: 14, padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}>
                  <span style={{ color: 'var(--text-3)' }}>Aging · due date</span>
                  {SUP_AGING_BUCKETS.map(([k, label]) => (
                    <span key={k}><span style={{ color: 'var(--text-3)' }}>{label} </span><b style={{ fontFamily: 'monospace' }}>{ag[k]}</b></span>
                  ))}
                  <span><span style={{ color: 'var(--text-3)' }}>total </span><b style={{ fontFamily: 'monospace' }}>{ag.total}</b></span>
                </div>
              )}
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5, minWidth: 720 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)' }}>
                    {['Date', 'Document', 'Type', 'Debit / Expense', 'Credit / Payment', 'Running', 'Due', 'Status'].map((h) => (
                      <th key={h} style={{ padding: '7px 8px', textAlign: 'left', fontSize: 10, color: 'var(--text-3)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr><td colSpan={8} style={{ padding: 20, textAlign: 'center', color: 'var(--text-3)' }}>No movements.</td></tr>
                  )}
                  {rows.map((e, i) => {
                    const isBf = e.type === 'opening_balance' || e.is_opening_balance;
                    return (
                    <tr key={`${e.wfirma_doc_id}-${i}`} data-testid={isBf ? `ldg-supplier-bf-${ccy}` : undefined}
                      style={{ borderBottom: '1px solid var(--border-subtle)', background: isBf ? 'var(--bg-subtle)' : undefined }}>
                      <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{e.date || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{e.doc_number || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{isBf ? 'Opening / B/F' : e.type}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{e.debit}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{e.credit}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{e.running_balance}</td>
                      <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{e.due_date || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{e.status || '—'}</td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
              {tot.closing_balance != null && (
                <div data-testid={`ldg-supplier-closing-${ccy}`} style={{ padding: '8px 12px', fontSize: 11.5, fontWeight: 700, borderTop: '1px solid var(--border)' }}>
                  Closing balance as of {period.to}: {LDG_FMT.money(tot.closing_balance, ccy)}
                </div>
              )}
            </window.Card>
          );
        })}
        {stmt && (stmt.unmatched_payments_per_currency && stmt.unmatched_payments_per_currency[active.currency] || []).length > 0 && (
          <div data-testid="ldg-supplier-unapplied" style={{ marginTop: 8, padding: 12, border: '1px solid var(--badge-amber-border)', borderRadius: 8, background: 'var(--badge-amber-bg)', fontSize: 11.5 }}>
            Genuinely unapplied payments (not in running balance): {(stmt.unmatched_payments_per_currency[active.currency] || []).length}
          </div>
        )}
      </div>
      )}
    </div>
  );
}

// ── Filter panel (left) ────────────────────────────────────────────────
function LdgFilterPanel({ title, searchPlaceholder, items, activeId, onSelect, extraFilters }) {
  // LDG-1 fix (independent-review finding): the search box was a dead input —
  // it accepted keystrokes and filtered nothing. It now really filters the
  // list (name + sub line, case-insensitive) and says so when nothing matches.
  const [query, setQuery] = React.useState('');
  const q = query.trim().toLowerCase();
  const shown = q
    ? items.filter(it => `${it.label} ${it.sub || ''}`.toLowerCase().includes(q))
    : items;
  return (
    <window.Card style={{ padding: 0, position: 'sticky', top: 0 }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>{title}</div>
        <input placeholder={searchPlaceholder} data-testid="ldg-filter-search"
          value={query} onChange={(e) => setQuery(e.target.value)} style={{
          width: '100%', padding: '6px 10px', fontSize: 12,
          border: '1px solid var(--border)', borderRadius: 5,
          background: 'var(--card)', color: 'var(--text)',
        }} />
      </div>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>Filters</div>
        {(extraFilters || []).length === 0 && (
          <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>Search above · Year / Month / From / To at the top of this page</div>
        )}
        {(extraFilters || []).map(f => (
          <label key={f.id} style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11, padding: '4px 0', color: 'var(--text-2)' }}>
            <span>{f.label}</span>
            <select
              data-testid={`ldg-filter-${f.id}`}
              value={f.value || ''}
              onChange={(e) => f.onChange && f.onChange(e.target.value)}
              style={{ fontSize: 11, padding: '4px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)' }}
            >
              {(f.options || []).map(opt => (
                <option key={opt || 'all'} value={opt}>{opt || 'All'}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div style={{ maxHeight: 'calc(100vh - 360px)', overflowY: 'auto' }}>
        {q && shown.length === 0 && (
          <div data-testid="ldg-filter-no-match" style={{ padding: '14px', fontSize: 11.5, color: 'var(--text-3)', textAlign: 'center' }}>
            No clients match “{query.trim()}”.
          </div>
        )}
        {shown.map(it => {
          const active = activeId === it.id;
          return (
            <button key={it.id} data-testid={it.testid || `ldg-filter-item-${it.id}`} onClick={() => onSelect(it.id)} style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '10px 14px', cursor: 'pointer',
              background: active ? 'var(--bg-subtle)' : 'transparent',
              border: 'none',
              borderLeft: `3px solid ${active ? 'var(--accent)' : 'transparent'}`,
              borderBottom: '1px solid var(--border-subtle)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                <span style={{ fontSize: 12, fontWeight: active ? 700 : 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.label}</span>
                {it.alert && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-red-text)', flexShrink: 0 }} />}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
                <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{it.sub}</span>
                <span style={{ fontSize: 10.5, fontWeight: 700, fontFamily: 'monospace', color: 'var(--text-2)' }}>{it.value}</span>
              </div>
            </button>
          );
        })}
      </div>
    </window.Card>
  );
}

// ── Statement detail drawer (right-side) — LIVE entry fields (LDG-1) ───
// Shows exactly what the statement.json entry carries. The old drawer's
// fabricated document preview (invented file size / page count), invented linked
// movements (SHP-/PZ-/SMP- ids) and minted "WF-DOC-" ids are removed —
// cross-links to shipments/PZ are a future backend capability, stated as such.
function StatementDetailDrawer({ row, onClose }) {
  const TYPE_LABEL = { invoice: 'Invoice', correction: 'Correction', payment: 'Payment', proforma: 'Proforma' };
  const money = (v) => (v === null || v === undefined || v === '' ? '—' : LDG_FMT.money(v, row.currency || ''));
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 900, display: 'flex', justifyContent: 'flex-end',
      background: 'rgba(0,0,0,0.18)',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div data-testid="ldg-entry-drawer" style={{
        width: 520, height: '100%', background: 'var(--card)',
        borderLeft: '1px solid var(--border)', boxShadow: '-12px 0 32px rgba(0,0,0,0.06)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>
                {row.doc_number || (row.type === 'payment' ? 'Payment' : TYPE_LABEL[row.type] || row.type)}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LdgSourceBadge mode="wfirma" />
              <LdgReadOnlyBadge />
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-3)' }}>×</button>
        </div>

        {/* Meta grid — real statement.json entry fields only */}
        <div style={{ padding: 18, borderBottom: '1px solid var(--border-subtle)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {[
            ['Type',            TYPE_LABEL[row.type] || row.type],
            ['Date',            row.date || '—'],
            ['Currency',        row.currency || '—'],
            ['Debit',           Number(row.debit) > 0 ? money(row.debit) : '—'],
            ['Credit',          Number(row.credit) > 0 ? money(row.credit) : '—'],
            ['Running balance', money(row.running_balance)],
            ['Linked invoice',  row.linked_invoice || '—'],
            ['wFirma doc id',   row.wfirma_doc_id ? String(row.wfirma_doc_id) : '—'],
          ].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 3 }}>{k}</div>
              <div style={{ fontSize: 12, color: 'var(--text)', fontFamily: ['wFirma doc id', 'Running balance', 'Debit', 'Credit'].includes(k) ? 'monospace' : 'inherit' }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Cross-links: honest pending state, not fabricated ids */}
        <div style={{ padding: 18, flex: 1, overflowY: 'auto' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Linked operational movements</div>
          <div data-testid="ldg-entry-links-pending" style={{ fontSize: 11, color: 'var(--text-3)', border: '1px dashed var(--border)', borderRadius: 6, padding: '14px 12px', background: 'var(--bg-subtle)' }}>
            Backend pending — cross-linking ledger entries to shipments, PZ receipts and
            samples requires a document-link index that does not exist yet. The entry
            itself above is live wFirma data.
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 18px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-subtle)' }}>
          <span style={{ fontSize: 10.5, color: 'var(--text-3)' }}>To post payments or corrections, use wFirma directly.</span>
          <window.Btn small variant="outline" onClick={onClose}>Close</window.Btn>
        </div>
      </div>
    </div>
  );
}

const ldgIconBtn = {
  width: 22, height: 22, borderRadius: 4,
  border: '1px solid var(--border)', background: 'var(--card)',
  fontSize: 11, color: 'var(--text-2)', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

Object.assign(window, { LedgersPage });
