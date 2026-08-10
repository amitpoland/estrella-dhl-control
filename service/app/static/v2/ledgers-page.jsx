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
const LDG_LIST_LIMIT = 10;
const SUP_LIST_LIMIT = 10;
const MA_TABLE_LIMIT = 10;

// AP aging buckets in report order — same keys the backend emits, so this
// strip and the Supplier Statement PDF read one authority.
const SUP_AGING_BUCKETS = [
  ['not_due', 'not due'], ['b_1_30', '1–30'], ['b_31_90', '31–90'],
  ['b_91_180', '91–180'], ['b_180_plus', '180+'], ['due_date_unavailable', 'due n/a'],
];

const LDG_PRESETS = [
  { id: 'this_month', label: 'This Month' },
  { id: 'prev_month', label: 'Previous Month' },
  { id: 'quarter', label: 'Quarter' },
  { id: 'ytd', label: 'YTD' },
  { id: 'custom', label: 'Custom' },
];

// ── Source / read-only badges ──────────────────────────────────────────
function LdgSourceBadge() {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 4, fontSize: 9.5, fontWeight: 700,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      background: 'var(--badge-blue-bg)', color: 'var(--badge-blue-text)',
      border: '1px solid var(--badge-blue-border)',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--badge-blue-text)' }} />
      Source · wFirma
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

// ── Period bar — the single period control for every ledger surface ────
// Rendered once, by LedgersPage. Switching to Custom PREFILLS both inputs with
// the currently resolved window, so the half-filled state that used to fall
// silently back to a preset the operator never chose cannot occur; an inverted
// range reports inline and the last valid window is held.
function LdgPeriodBar({ filters, custom, periodErr, onMode, onCustom, inert, inertNote }) {
  const dateStyle = {
    marginLeft: 6, padding: '4px 7px', fontSize: 11,
    border: '1px solid var(--border)', borderRadius: 4,
    background: inert ? 'var(--bg-subtle)' : 'var(--bg)', color: 'var(--text)',
  };
  return (
    <div data-testid="ldg-period-bar" style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8,
      padding: '10px 14px', marginBottom: 14, borderRadius: 6,
      border: '1px solid var(--border)', background: 'var(--card)',
    }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Period</span>
      {LDG_PRESETS.map(p => {
        const active = filters.mode === p.id;
        return (
          <button key={p.id} type="button" data-testid={`ldg-preset-${p.id}`}
            disabled={inert} onClick={() => onMode(p.id)}
            style={{
              padding: '4px 10px', fontSize: 11, borderRadius: 4, cursor: inert ? 'not-allowed' : 'pointer',
              border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
              background: active ? 'var(--bg-subtle)' : 'var(--card)',
              color: active ? 'var(--text)' : 'var(--text-2)',
              fontWeight: active ? 700 : 500, opacity: inert ? 0.5 : 1,
            }}>{p.label}</button>
        );
      })}
      {filters.mode === 'custom' && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-3)' }}>
          <label>From
            <input type="date" data-testid="ldg-from" value={custom.from} disabled={inert}
              onChange={(e) => onCustom({ ...custom, from: e.target.value })} style={dateStyle} />
          </label>
          <label>To
            <input type="date" data-testid="ldg-to" value={custom.to} disabled={inert}
              onChange={(e) => onCustom({ ...custom, to: e.target.value })} style={dateStyle} />
          </label>
        </span>
      )}
      <span data-testid="ldg-period-window" style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-2)', marginLeft: 'auto' }}>
        {filters.from} → {filters.to}
      </span>
      {periodErr && (
        <div data-testid="ldg-period-error" style={{ flexBasis: '100%', fontSize: 11, color: 'var(--badge-red-text)' }}>
          {periodErr} — showing {filters.from} → {filters.to}.
        </div>
      )}
      {inert && inertNote && (
        <div data-testid="ldg-period-inert" style={{ flexBasis: '100%', fontSize: 11, color: 'var(--text-3)' }}>
          {inertNote}
        </div>
      )}
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
  // One normalized filter object for every ledger surface on this page. No
  // child holds its own period state and nothing computes a second default.
  // Management Analysis opens on the full outstanding portfolio as of today —
  // a balance-sheet-style exposure, not "documents issued this month" — so its
  // scope defaults to all_outstanding and the period bar goes inert for it.
  const today = LDG_TODAY();
  const [filters, setFilters] = React.useState(() => {
    const p = window.resolvePeriod('this_month', null, today);
    return {
      mode: 'this_month', from: p.from, to: p.to, as_of: today,
      scope: 'all_outstanding', currency: '',
      ar_status: 'outstanding', ap_status: 'outstanding',
    };
  });
  const [custom, setCustom] = React.useState({ from: '', to: '' });
  const [periodErr, setPeriodErr] = React.useState('');
  const patch = (p) => setFilters(f => ({ ...f, ...p }));

  const onMode = (mode) => {
    setPeriodErr('');
    if (mode === 'custom') {
      // Prefill both inputs from the window currently on screen.
      setCustom({ from: filters.from, to: filters.to });
      patch({ mode: 'custom' });
      return;
    }
    const p = window.resolvePeriod(mode, null, today);
    patch({ mode, from: p.from, to: p.to });
  };

  const onCustom = (next) => {
    setCustom(next);
    const p = window.resolvePeriod('custom', next, today);
    if (!p) {
      setPeriodErr(next.from && next.to ? 'From date must be on or before To date' : 'Both dates are required');
      return;
    }
    setPeriodErr('');
    patch({ mode: 'custom', from: p.from, to: p.to });
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

  const openSupplierLedger = (contractorId) => {
    setFocusSupplierId(contractorId || '');
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
          <LdgSourceBadge />
          <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
            All balances and movements are pulled from wFirma. No values can be edited here. Posting payments and corrections must be done in wFirma directly.
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {loadInfo.status === 'loading' && (
            <span data-testid="ldg-load-status" style={{ fontSize: 11, color: 'var(--text-3)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--text-3)' }} />
              Loading from wFirma…
            </span>
          )}
          {loadInfo.status === 'ok' && (
            <span data-testid="ldg-load-status" title="Figures are live wFirma reads made at this time — not a background sync" style={{ fontSize: 11, color: 'var(--badge-green-text)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-green-text)' }} />
              Live wFirma read · loaded {_t(loadInfo.at)}
            </span>
          )}
          {loadInfo.status === 'error' && (
            <span data-testid="ldg-load-status" style={{ fontSize: 11, color: 'var(--badge-red-text)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-red-text)' }} />
              wFirma read failed{loadInfo.at ? ` · ${_t(loadInfo.at)}` : ''}
            </span>
          )}
          <window.Btn small variant="outline" data-testid="ldg-refresh"
            onClick={() => { setLoadInfo(p => ({ ...p, status: 'loading' })); setSelectedRow(null); setRefreshKey(k => k + 1); }}>
            ↻ Refresh from wFirma
          </window.Btn>
        </div>
      </div>

      <LdgPeriodBar
        filters={filters} custom={custom} periodErr={periodErr}
        onMode={onMode} onCustom={onCustom}
        inert={tab === 'analysis' && filters.scope === 'all_outstanding'}
        inertNote="Management Analysis is showing the full outstanding portfolio as of today. Switch Scope to Custom Period to apply these dates." />

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
  const [clients, setClients] = React.useState(null);      // null = loading
  const [listErr, setListErr] = React.useState(null);
  const [active, setActive]   = React.useState('');
  const [stmt, setStmt]       = React.useState({ status: 'idle', data: null, err: null });
  const [currencyFilter, setCurrencyFilter] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('');
  const [listPage, setListPage] = React.useState(1);
  const [listHasMore, setListHasMore] = React.useState(false);
  const period = { from: filters.from, to: filters.to };

  React.useEffect(() => {
    if (focusContractorId) setActive(focusContractorId);
  }, [focusContractorId]);

  React.useEffect(() => { setListPage(1); }, [period.from, period.to, currencyFilter, statusFilter]);

  // Live client-balance list. Re-runs on ↻ Refresh (refreshKey).
  React.useEffect(() => {
    let gone = false;
    setClients(null); setListErr(null);
    const params = {
      limit: LDG_LIST_LIMIT,
      start: (listPage - 1) * LDG_LIST_LIMIT,
      from: period.from,
      to: period.to,
    };
    if (currencyFilter) params.currency = currencyFilter;
    if (statusFilter) params.status = statusFilter;
    // Cache entry is keyed by the resolved query string, so a period change is
    // already a distinct entry — force is only for the manual ↻ Refresh.
    window.PzApi.listClientBalancesShared(params, { force: refreshKey > 0 })
      .then(r => {
        if (gone) return;
        const rows = (r && r.rows) || [];
        setClients(rows);
        setListHasMore(rows.length >= LDG_LIST_LIMIT);
        onLoadInfo && onLoadInfo({ status: 'ok', at: new Date(), count: rows.length, error: null });
        const prefer = focusContractorId && rows.some(x => x.contractor_id === focusContractorId)
          ? focusContractorId : null;
        if (prefer) setActive(prefer);
        else if (rows.length && !rows.some(x => x.contractor_id === active)) {
          setActive(rows[0].contractor_id);
        }
      })
      .catch(e => {
        if (gone) return;
        setClients([]);
        setListErr((e && e.message) || 'wFirma read failed');
        onLoadInfo && onLoadInfo({ status: 'error', at: new Date(), count: null, error: (e && e.message) || '' });
      });
    return () => { gone = true; };
  }, [refreshKey, period.from, period.to, currencyFilter, statusFilter, listPage]);

  const c = (clients || []).find(x => x.contractor_id === active) || null;

  // Live per-client statement (entries + totals + aging). On-demand per
  // selection — same authority the statement PDF uses.
  React.useEffect(() => {
    if (!active) { setStmt({ status: 'idle', data: null, err: null }); return; }
    let gone = false;
    setStmt({ status: 'loading', data: null, err: null });
    const w = period;
    window.EstrellaShared.apiFetch(`/api/v1/ledgers/clients/${encodeURIComponent(active)}/statement.json?from=${w.from}&to=${w.to}`)
      .then(r => { if (!gone) setStmt({ status: 'ok', data: r, err: null }); })
      .catch(e => { if (!gone) setStmt({ status: 'error', data: null, err: (e && e.message) || 'statement read failed' }); });
    return () => { gone = true; };
  }, [active, refreshKey, period.from, period.to]);

  if (clients === null) {
    return <div data-testid="ldg-clients-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>Loading client balances from wFirma…</div>;
  }
  if (listErr && clients.length === 0) {
    return (
      <div data-testid="ldg-clients-error" style={{ padding: 30, textAlign: 'center', border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 4 }}>Could not load client balances</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)' }}>{listErr} · use ↻ Refresh to retry</div>
      </div>
    );
  }
  if (clients.length === 0) {
    return <div data-testid="ldg-clients-empty" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>No customers in Customer Master yet.</div>;
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
      <div>
        <LdgFilterPanel
          title="Clients"
          searchPlaceholder="Search clients…"
          extraFilters={[
            {
              id: 'currency',
              label: 'Currency',
              value: currencyFilter,
              onChange: setCurrencyFilter,
              options: ['', 'PLN', 'EUR', 'USD', 'GBP'],
            },
            {
              id: 'status',
              label: 'Status',
              value: statusFilter,
              onChange: setStatusFilter,
              options: ['', 'outstanding', 'clear', 'unknown'],
            },
          ]}
          items={clients.map(x => ({
            id: x.contractor_id, label: x.name || x.contractor_id,
            sub: [x.country, x.vat_id].filter(Boolean).join(' · '),
            value: x.balance_available === false ? '—'
                 : x.currency === 'multi' ? 'multi-ccy'
                 : LDG_FMT.money(x.open, x.currency),
            alert: (Number(x.overdue_invoice_age) || 0) > 0,
          }))}
          activeId={active}
          onSelect={setActive}
        />
        <div data-testid="ldg-clients-pager" style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
          <button type="button" data-testid="ldg-clients-prev" disabled={listPage <= 1}
            onClick={() => setListPage(p => Math.max(1, p - 1))}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: listPage <= 1 ? 'not-allowed' : 'pointer', opacity: listPage <= 1 ? 0.45 : 1 }}>Previous</button>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Page {listPage} · {LDG_LIST_LIMIT}/page</span>
          <button type="button" data-testid="ldg-clients-next" disabled={!listHasMore}
            onClick={() => setListPage(p => p + 1)}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: !listHasMore ? 'not-allowed' : 'pointer', opacity: !listHasMore ? 0.45 : 1 }}>Next</button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {c && <ClientHeaderCard client={c} stmt={stmt} period={period} />}
        {c && <ClientStatementTable client={c} stmt={stmt} period={period} onRowClick={onSelectRow} selectedId={selectedRow && selectedRow.id} />}
      </div>
    </div>
  );
}

function ClientHeaderCard({ client: c, stmt, period }) {
  // LDG-1: every KPI reads the /ledgers/clients row (live wFirma) or renders
  // an honest missing state. Credit-limit / KUKE utilisation bars and
  // inventory-exposure tiles from the old mock are NOT rendered as numbers —
  // no ledger authority serves them yet (see backend-pending note below).
  const unavailable = c.balance_available === false;
  const stmtGen = stmt && stmt.status === 'ok' && stmt.data ? (stmt.data.generated_at || '') : '';
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
            /* Multi-currency contractor: top-line figures are per-currency
               dicts, not one number — the statement below shows each currency
               honestly instead of a fabricated cross-currency sum. */
            <LdgStatTile label="Open (outstanding)" value="multi-currency"
              sub={`per currency: ${Object.entries(c.open_by_currency || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'see statement'}`} />
          ) : (
            <LdgStatTile label="Open (outstanding)" value={LDG_FMT.money(c.open, c.currency)}
              sub="live wFirma statement" />
          )}
          {/* aged = aging.total − aging.current (routes_ledgers.py), i.e. any
              unpaid amount past its INVOICE date — includes 1–30-day invoices
              that may be well within payment terms. Due-date aging is Backend
              Pending, so the label must not claim "overdue" or "30+ days". */}
          <LdgStatTile label="Aged (invoice age)" value={c.currency === 'multi' ? 'see statement' : LDG_FMT.money(c.overdue_invoice_age, c.currency)}
            sub={(Number(c.overdue_invoice_age) || 0) > 0 ? 'unpaid past invoice date — see statement aging' : 'invoice-age basis'}
            tone={(Number(c.overdue_invoice_age) || 0) > 0 ? 'amber' : 'green'} />
          <LdgStatTile label="Invoiced (period)" value={c.currency === 'multi' ? 'see statement' : LDG_FMT.money(c.ytd_invoiced, c.currency)} sub="statement window" />
          {/* last_30d is served as null by routes_ledgers.py (Backend Pending) —
              say so rather than rendering a dash that implies a live zero. */}
          <LdgStatTile label="Last 30 days" value="—" sub="backend pending" />
        </div>
      )}

      {/* Honest capability note (Lesson M five-state: the old mock PROMISED
          credit-limit / KUKE utilisation and inventory exposure here) */}
      <div data-testid="ldg-credit-kuke-pending" style={{ padding: '8px 16px', borderTop: '1px solid var(--border-subtle)', fontSize: 10.5, color: 'var(--text-3)' }}>
        Credit-limit / KUKE utilisation and inventory exposure: <strong>backend pending</strong> — no ledger
        authority serves these yet (Customer Master holds KUKE terms; exposure needs the inventory valuation feed).
        {stmtGen && <span style={{ marginLeft: 10 }}>Statement generated {stmtGen}.</span>}
      </div>
    </window.Card>
  );
}

// ── Aging strip ────────────────────────────────────────────────────────
function LdgAgingStrip({ buckets }) {
  return (
    <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 14, borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
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

// ── Compact ERP statement table — LIVE (statement.json entries) ────────
// LDG-1: renders entries_per_currency / totals_per_currency /
// aging_per_currency from GET /ledgers/clients/{id}/statement.json. The old
// synthetic rows and the fabricated aging strip are gone; every state
// (loading / error / empty) is honest.
function ClientStatementTable({ client, stmt, onRowClick, selectedId, period }) {
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

  const TYPE_LABEL = { invoice: 'Invoice', correction: 'Correction', payment: 'Payment', proforma: 'Proforma' };
  const agingBuckets = (a) => {
    if (!a) return [];
    const order = ['current', 'd1_30', '1_30', 'd31_60', '31_60', 'd61_90', '61_90', 'd90_plus', '90_plus', 'over_90'];
    const label = (k) => ({ current: 'Current', d1_30: '1–30', '1_30': '1–30', d31_60: '31–60', '31_60': '31–60',
                            d61_90: '61–90', '61_90': '61–90', d90_plus: '90+', '90_plus': '90+', over_90: '90+' }[k] || k);
    const tone = (k) => (/90|61/.test(k) ? 'red' : /30|60/.test(k) ? 'amber' : null);
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
          <LdgSourceBadge />
          <LdgReadOnlyBadge />
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
          No invoices or payments on record for this customer in the period.
        </div>
      )}

      {currencies.map(ccy => {
        const entries = entriesBy[ccy] || [];
        const totals = totalsBy[ccy] || {};
        return (
          <div key={ccy} data-testid={`ldg-stmt-ccy-${ccy}`}>
            <LdgAgingStrip buckets={[
              { label: ccy, value: '' },
              ...agingBuckets(agingBy[ccy]).map(b => ({ ...b, value: LDG_FMT.money(b.value, '') })),
            ]} />
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                    {['Date', 'Doc no.', 'Type', 'Debit', 'Credit', 'Running balance', 'Source'].map((h, i) => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: i >= 3 && i <= 5 ? 'right' : 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {entries.map((r, i) => {
                    const rowId = `${ccy}-${r.wfirma_doc_id || i}`;
                    const isSelected = selectedId === rowId;
                    return (
                      <tr key={rowId}
                        onClick={() => onRowClick && onRowClick({ ...r, id: rowId })}
                        style={{ borderBottom: '1px solid var(--border-subtle)', cursor: onRowClick ? 'pointer' : 'default', background: isSelected ? 'var(--bg-subtle)' : 'transparent' }}>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{r.date || '—'}</td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.doc_number || (r.type === 'payment' ? (r.linked_invoice ? `→ ${r.linked_invoice}` : '(unmatched)') : '—')}</td>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2)' }}>{TYPE_LABEL[r.type] || r.type}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: Number(r.debit) > 0 ? 'var(--text)' : 'var(--text-3)' }}>{Number(r.debit) > 0 ? LDG_FMT.money(r.debit, ccy) : '—'}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: Number(r.credit) > 0 ? 'var(--badge-green-text)' : 'var(--text-3)' }}>{Number(r.credit) > 0 ? LDG_FMT.money(r.credit, ccy) : '—'}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text)' }}>{LDG_FMT.money(r.running_balance, ccy)}</td>
                        <td style={{ padding: '8px 12px', fontSize: 10, color: 'var(--text-3)' }}>wFirma</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', fontSize: 11.5, background: 'var(--bg-subtle)' }}>
              <span style={{ color: 'var(--text-3)' }}>{entries.length} entr{entries.length === 1 ? 'y' : 'ies'} · {ccy} · all sourced from wFirma</span>
              <span style={{ color: 'var(--text)', fontWeight: 700, fontFamily: 'monospace' }} data-testid={`ldg-stmt-outstanding-${ccy}`}>
                Outstanding: {LDG_FMT.money(totals.outstanding, ccy)}
              </span>
            </div>
          </div>
        );
      })}

      {(d.warnings || []).length > 0 && (
        <div data-testid="ldg-stmt-warnings" style={{ padding: '8px 16px', fontSize: 10.5, color: 'var(--badge-amber-text)', borderTop: '1px solid var(--border-subtle)' }}>
          {(d.warnings || []).map((w, i) => <div key={i}>⚠ {String(w)}</div>)}
        </div>
      )}
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
  const [data, setData] = React.useState(null);
  const [apData, setApData] = React.useState(null);
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
    const apParams = scopeParams();
    if (currency) apParams.currency = currency;
    if (apStatus) apParams.status = apStatus;
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
        const nAr = (body && body.customers && body.customers.length) || 0;
        const nAp = (apRes && (apRes.data || apRes).suppliers && (apRes.data || apRes).suppliers.length) || 0;
        onLoadInfo && onLoadInfo({ status: 'ok', at: new Date(), count: nAr + nAp, error: null });
      })
      .catch((e) => {
        if (gone) return;
        setData(null);
        setApData(null);
        setLoading(false);
        const msg = (e && e.message) || 'portfolio read failed';
        setErr(msg);
        onLoadInfo && onLoadInfo({ status: 'error', at: new Date(), count: null, error: msg });
      });
    return () => { gone = true; };
  }, [scope, period.from, period.to, asOf, currency, status, apStatus, refreshKey, localRefresh]);

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
    return <div data-testid="ldg-ma-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>Loading receivables portfolio from wFirma…</div>;
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

  return (
    <div data-testid="ldg-ma-root">
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>Management Analysis</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>
          Receivables and Payables from wFirma — shared remaining math, no FX merge, read-only.
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
        <window.Btn small data-testid="ldg-ma-refresh" onClick={() => setLocalRefresh((n) => n + 1)}>Refresh</window.Btn>
        {/* Read-only projection of exactly these filters — the PDF route calls
            the same builders as the JSON above, so it cannot show a different
            number than the screen. */}
        <a href={window.PzApi.managementAnalysisPdfUrl(pdfParams)} target="_blank" rel="noopener"
           data-testid="ldg-ma-pdf"
           style={{ fontSize: 11, fontWeight: 600, padding: '5px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none', background: 'transparent' }}>
          ↓ Management PDF
        </a>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12, fontSize: 11, color: 'var(--text-3)' }}>
        <span data-testid="ldg-ma-asof-label">Data as of {data.generated_at || '—'}</span>
        <span>·</span>
        <span data-testid="ldg-ma-health">
          Source {health.ok === false ? '⚠️ incomplete (cap/stall)' : 'healthy'}
          {qs.duration_ms != null ? ` · ${qs.duration_ms} ms` : ''}
          {qs.invoice_api_calls != null ? ` · inv calls ${qs.invoice_api_calls}` : ''}
          {qs.payment_api_calls != null ? ` · pay calls ${qs.payment_api_calls}` : ''}
          {qs.per_customer_wfirma_calls === 0 ? ' · no N+1' : ''}
        </span>
        <span>·</span>
        <span data-testid="ldg-ma-due-coverage">
          Due-date coverage {cov.open_coverage_pct == null ? '—' : `${cov.open_coverage_pct}%`}
          {cov.open_with_paymentdate != null ? ` (${cov.open_with_paymentdate}/${(cov.open_with_paymentdate || 0) + (cov.open_missing_paymentdate || 0)} open)` : ''}
        </span>
      </div>

      {summaries.map((s) => (
        <div key={s.currency} data-testid={`ldg-ma-ccy-${s.currency}`} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text)' }}>{s.currency} portfolio</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 10 }}>
            <LdgStatTile label="Receivable" value={LDG_FMT.money(s.total_receivable, s.currency)} />
            <LdgStatTile label="Overdue" value={LDG_FMT.money(s.overdue, s.currency)} tone="red" alert={Number(s.overdue) > 0} />
            <LdgStatTile label="Not Due" value={LDG_FMT.money(s.not_due, s.currency)} />
            <LdgStatTile label="Customer Credits" value={LDG_FMT.money(s.customer_credits, s.currency)} tone="green" />
            <LdgStatTile label="Customers Outstanding" value={String(s.customers_outstanding)} sub={`${s.customers_overdue} overdue`} />
            <LdgStatTile label="Net position" value={LDG_FMT.money(s.net_position, s.currency)}
              sub={s.reconciliation_ok ? 'aging reconciles' : '⚠️ aging mismatch'} />
          </div>
        </div>
      ))}

      <window.Card style={{ padding: 0, overflow: 'auto' }}>
        <table data-testid="ldg-ma-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5, minWidth: 960 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left' }}>
              {['Customer', 'Ccy', 'Credit', 'Not Due', '1–30', '31–90', '91–180', '>180', 'Outstanding', 'Oldest Due', 'Last Payment', ''].map((h) => (
                <th key={h} style={{ padding: '8px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: 'var(--text-3)', fontWeight: 600, textAlign: h === 'Customer' || h === '' ? 'left' : 'right' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={12} style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>No customers match filters.</td></tr>
            )}
            {rows.map((r) => (
              <tr key={`${r.contractor_id}-${r.currency}`} data-testid={`ldg-ma-row-${r.contractor_id}-${r.currency}`}
                style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '7px 8px', fontWeight: 600 }}>{r.customer_name}</td>
                <td style={{ padding: '7px 8px', textAlign: 'right' }}>{r.currency}</td>
                {moneyCell(r.credit_balance, r.currency)}
                {moneyCell(r.not_due, r.currency)}
                {moneyCell(r.b_1_30, r.currency)}
                {moneyCell(r.b_31_90, r.currency)}
                {moneyCell(r.b_91_180, r.currency)}
                {moneyCell(r.b_180_plus, r.currency)}
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

      {Object.keys(dq).length > 0 && (
        <details data-testid="ldg-ma-dq" style={{ marginTop: 14 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>AR data quality</summary>
          <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 11.5, color: 'var(--text-3)' }}>
            {Object.entries(dq).map(([k, v]) => (
              <li key={k}>{k}: {v}</li>
            ))}
          </ul>
        </details>
      )}

      {/* ── PAYABLES / CREDITOR AGING ── */}
      <div data-testid="ldg-ma-payables" style={{ marginTop: 28, paddingTop: 20, borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Payables</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12 }}>
          Supplier payables and creditor aging from wFirma expenses and linked payments.
          Credits / advances stay outside overdue buckets. Currencies stay separate.
        </div>
        {apErr && !apData && (
          <div data-testid="ldg-ma-ap-error" style={{ padding: 16, border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8, marginBottom: 12, fontSize: 12 }}>
            {apErr}
          </div>
        )}
        {apData && (() => {
          const apSummaries = apData.currency_summaries || [];
          const apCov = apData.due_date_coverage || {};
          const apQs = apData.query_stats || {};
          const apDq = apData.data_quality || {};
          const apHealth = apData.source_health || {};
          const apQLower = (apQ || '').trim().toLowerCase();
          const apRowsAll = (apData.suppliers || []).filter((r) => {
            if (!apQLower) return true;
            return String(r.supplier_name || '').toLowerCase().includes(apQLower);
          });
          const apTotalPages = Math.max(1, Math.ceil(apRowsAll.length / MA_TABLE_LIMIT) || 1);
          const apPageSafe = Math.min(apTablePage, apTotalPages);
          const apRows = apRowsAll.slice((apPageSafe - 1) * MA_TABLE_LIMIT, apPageSafe * MA_TABLE_LIMIT);
          return (
            <div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12, fontSize: 11, color: 'var(--text-3)' }}>
                <span data-testid="ldg-ma-ap-health">
                  AP source {apHealth.ok === false ? '⚠️ incomplete' : 'healthy'}
                  {apQs.expense_api_calls != null ? ` · exp calls ${apQs.expense_api_calls}` : ''}
                  {apQs.payment_api_calls != null ? ` · pay calls ${apQs.payment_api_calls}` : ''}
                  {apQs.per_supplier_wfirma_calls === 0 ? ' · no N+1' : ''}
                </span>
                <span>·</span>
                <span data-testid="ldg-ma-ap-due-coverage">
                  Due-date coverage {apCov.open_coverage_pct == null ? '—' : `${apCov.open_coverage_pct}%`}
                </span>
              </div>
              {apSummaries.map((s) => (
                <div key={s.currency} data-testid={`ldg-ma-ap-ccy-${s.currency}`} style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text)' }}>{s.currency} payables</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 10 }}>
                    <LdgStatTile label="Supplier Payable" value={LDG_FMT.money(s.gross_payable, s.currency)} />
                    <LdgStatTile label="Overdue Payable" value={LDG_FMT.money(s.overdue, s.currency)} tone="red" alert={Number(s.overdue) > 0} />
                    <LdgStatTile label="Not Due" value={LDG_FMT.money(s.not_due, s.currency)} />
                    <LdgStatTile label="Supplier Credits" value={LDG_FMT.money(s.supplier_credits, s.currency)} tone="green" />
                    <LdgStatTile label="Suppliers Outstanding" value={String(s.suppliers_outstanding)} sub={`${s.suppliers_overdue} overdue`} />
                    <LdgStatTile label="Net Payable" value={LDG_FMT.money(s.net_payable, s.currency)}
                      sub={s.reconciliation_ok ? 'aging reconciles' : '⚠️ aging mismatch'} />
                  </div>
                </div>
              ))}
              <window.Card style={{ padding: 0, overflow: 'auto' }}>
                <table data-testid="ldg-ma-ap-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5, minWidth: 960 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-subtle)', textAlign: 'left' }}>
                      {['Supplier', 'Ccy', 'Credit', 'Not Due', '1–30', '31–90', '91–180', '>180', 'Net Payable', 'Oldest Due', 'Last Payment', ''].map((h) => (
                        <th key={h} style={{ padding: '8px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: 'var(--text-3)', fontWeight: 600, textAlign: h === 'Supplier' || h === '' ? 'left' : 'right' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {apRows.length === 0 && (
                      <tr><td colSpan={12} style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>No suppliers match filters.</td></tr>
                    )}
                    {apRows.map((r) => (
                      <tr key={`${r.contractor_id}-${r.currency}`} data-testid={`ldg-ma-ap-row-${r.contractor_id}-${r.currency}`}
                        style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '7px 8px', fontWeight: 600 }}>{r.supplier_name}</td>
                        <td style={{ padding: '7px 8px', textAlign: 'right' }}>{r.currency}</td>
                        {moneyCell(r.credit_balance, r.currency)}
                        {moneyCell(r.not_due, r.currency)}
                        {moneyCell(r.b_1_30, r.currency)}
                        {moneyCell(r.b_31_90, r.currency)}
                        {moneyCell(r.b_91_180, r.currency)}
                        {moneyCell(r.b_180_plus, r.currency)}
                        {moneyCell(r.net_payable, r.currency)}
                        <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.oldest_due_date || '—'}</td>
                        <td style={{ padding: '7px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{r.last_payment_date || '—'}</td>
                        <td style={{ padding: '7px 8px' }}>
                          <window.Btn small variant="outline" data-testid={`ldg-ma-ap-open-${r.contractor_id}`}
                            onClick={() => onOpenSupplierLedger && onOpenSupplierLedger(r.contractor_id)}>
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
              {Object.keys(apDq).length > 0 && (
                <details data-testid="ldg-ma-ap-dq" style={{ marginTop: 14 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>AP data quality</summary>
                  <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 11.5, color: 'var(--text-3)' }}>
                    {Object.entries(apDq).map(([k, v]) => (
                      <li key={k}>{k}: {v}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
}

// ── SUPPLIER LEDGER — shared AP facts (statement.json) ─────────────────────
function SupplierLedgerView({ refreshKey, onLoadInfo, filters, focusSupplierId }) {
  const period = { from: filters.from, to: filters.to };
  const [suppliers, setSuppliers] = React.useState(null);
  const [listErr, setListErr] = React.useState(null);
  const [activeId, setActiveId] = React.useState(focusSupplierId || '');
  const [stmt, setStmt] = React.useState(null);
  const [stmtErr, setStmtErr] = React.useState(null);
  const [stmtLoading, setStmtLoading] = React.useState(false);
  const [supListPage, setSupListPage] = React.useState(1);

  React.useEffect(() => {
    if (focusSupplierId) setActiveId(focusSupplierId);
  }, [focusSupplierId]);

  // Changing the period changes the roster, so page 2 of the old roster is
  // meaningless. The client and MA tables already did this; the supplier
  // pager did not, and kept a stale page number across period changes.
  React.useEffect(() => { setSupListPage(1); }, [period.from, period.to]);

  React.useEffect(() => {
    let gone = false;
    setSuppliers(null); setListErr(null);
    onLoadInfo && onLoadInfo({ status: 'loading', at: null, count: null, error: null });
    const payParams = {
      from: period.from, to: period.to, as_of: period.to, status: 'outstanding',
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
        if (!activeId && rows.length) setActiveId(rows[0].contractor_id);
      })
      .catch((e) => {
        if (gone) return;
        setListErr((e && e.message) || 'payables read failed');
        onLoadInfo && onLoadInfo({ status: 'error', at: new Date(), count: null, error: (e && e.message) || '' });
      });
    return () => { gone = true; };
  }, [period.from, period.to, refreshKey]);

  React.useEffect(() => {
    if (!activeId) { setStmt(null); return; }
    let gone = false;
    setStmtLoading(true); setStmtErr(null); setStmt(null);
    window.PzApi.getSupplierStatement(
      activeId, period.from, period.to, period.to,
      refreshKey > 0 ? { refresh: true } : undefined,
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
  }, [activeId, period.from, period.to, refreshKey]);

  if (listErr && !suppliers) {
    return (
      <div data-testid="ldg-suppliers-error" style={{ padding: 30, textAlign: 'center', border: '1px solid var(--badge-red-border)', background: 'var(--badge-red-bg)', borderRadius: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--badge-red-text)' }}>Could not load Supplier Ledger</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)' }}>{listErr}</div>
      </div>
    );
  }
  if (!suppliers) {
    return <div data-testid="ldg-suppliers-loading" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12.5 }}>Loading supplier payables from wFirma…</div>;
  }
  if (suppliers.length === 0) {
    return <div data-testid="ldg-suppliers-empty" style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>No outstanding suppliers in this period.</div>;
  }

  const active = suppliers.find((s) => s.contractor_id === activeId) || suppliers[0];
  const supTotalPages = Math.max(1, Math.ceil(suppliers.length / SUP_LIST_LIMIT) || 1);
  const supPageSafe = Math.min(supListPage, supTotalPages);
  const filterItems = suppliers
    .slice((supPageSafe - 1) * SUP_LIST_LIMIT, supPageSafe * SUP_LIST_LIMIT)
    .map((s) => ({
      id: s.contractor_id,
      label: s.supplier_name || s.contractor_id,
      sub: `${s.currency} · net ${s.net_payable}`,
    }));

  return (
    <div data-testid="ldg-suppliers-root" style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
      <div>
        <LdgFilterPanel
          title="Suppliers"
          searchPlaceholder="Search supplier…"
          items={filterItems}
          activeId={active.contractor_id}
          onSelect={setActiveId}
        />
        <div data-testid="ldg-suppliers-pager" style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
          <button type="button" data-testid="ldg-suppliers-prev" disabled={supPageSafe <= 1} onClick={() => setSupListPage(p => Math.max(1, p - 1))}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: supPageSafe <= 1 ? 'not-allowed' : 'pointer', opacity: supPageSafe <= 1 ? 0.45 : 1 }}>Previous</button>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Page {supPageSafe}/{supTotalPages}</span>
          <button type="button" data-testid="ldg-suppliers-next" disabled={supPageSafe >= supTotalPages} onClick={() => setSupListPage(p => p + 1)}
            style={{ padding: '4px 10px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--card)', cursor: supPageSafe >= supTotalPages ? 'not-allowed' : 'pointer', opacity: supPageSafe >= supTotalPages ? 0.45 : 1 }}>Next</button>
        </div>
      </div>
      <div>
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700 }} data-testid="ldg-supplier-name">{active.supplier_name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
              Period {period.from} → {period.to} · {active.currency} · open expenses {active.open_expense_count}
            </div>
          </div>
          {/* Same AP authority as the statement below — the PDF route calls the
              same builder, so it cannot print a different total. */}
          <a href={window.PzApi.supplierStatementPdfUrl(active.contractor_id, {
                from: period.from, to: period.to, as_of: period.to,
              })}
             target="_blank" rel="noopener" data-testid="ldg-supplier-statement-pdf"
             style={{ fontSize: 11, fontWeight: 600, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', textDecoration: 'none', flexShrink: 0 }}>
            ↓ Statement PDF
          </a>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 14 }}>
          <LdgStatTile label="Gross Payable" value={LDG_FMT.money(active.gross_payable, active.currency)} />
          <LdgStatTile label="Credits" value={LDG_FMT.money(active.credit_balance, active.currency)} tone="green" />
          <LdgStatTile label="Net Payable" value={LDG_FMT.money(active.net_payable, active.currency)} />
          <LdgStatTile label="Overdue" value={LDG_FMT.money(active.overdue, active.currency)} tone="red" alert={Number(active.overdue) > 0} />
        </div>
        {stmtLoading && <div data-testid="ldg-supplier-stmt-loading" style={{ padding: 20, color: 'var(--text-3)', fontSize: 12 }}>Loading statement…</div>}
        {stmtErr && <div data-testid="ldg-supplier-stmt-error" style={{ padding: 16, border: '1px solid var(--badge-red-border)', borderRadius: 8, color: 'var(--badge-red-text)', fontSize: 12 }}>{stmtErr}</div>}
        {stmt && (stmt.currencies || []).map((ccy) => {
          const rows = (stmt.entries_per_currency && stmt.entries_per_currency[ccy]) || [];
          const tot = (stmt.totals_per_currency && stmt.totals_per_currency[ccy]) || {};
          const ag = (stmt.aging_per_currency && stmt.aging_per_currency[ccy]) || null;
          return (
            <window.Card key={ccy} style={{ padding: 0, marginBottom: 14, overflow: 'auto' }} data-testid={`ldg-supplier-stmt-${ccy}`}>
              <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700 }}>
                {ccy} · outstanding {tot.outstanding} · net {tot.net_payable}
              </div>
              {/* Aging comes from the statement DTO itself — the PDF prints
                  these exact figures rather than reading a second endpoint. */}
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
                  {rows.map((e, i) => (
                    <tr key={`${e.wfirma_doc_id}-${i}`} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{e.date || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{e.doc_number || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{e.type}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{e.debit}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{e.credit}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'monospace' }}>{e.running_balance}</td>
                      <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{e.due_date || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{e.status || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </window.Card>
          );
        })}
      </div>
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
          <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>Search above · period presets at the top of this page</div>
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
            <button key={it.id} onClick={() => onSelect(it.id)} style={{
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
              <LdgSourceBadge />
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
