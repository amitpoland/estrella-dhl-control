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

// Statement window: statement.json / statement.pdf REQUIRE explicit from/to
// (routes_ledgers.py validates and 400s on ''). Use the same default the
// /ledgers/clients roster applies server-side — Jan 1 of the current year
// through today (UTC) — so the statement matches the roster figures.
const LDG_WINDOW = () => {
  const now = new Date();
  return { from: `${now.getUTCFullYear()}-01-01`, to: now.toISOString().slice(0, 10) };
};

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

// ── Header (sub-tabs + global wFirma sync state) ───────────────────────
function LedgersPage() {
  const [tab, setTab] = React.useState('clients');
  const [selectedRow, setSelectedRow] = React.useState(null);
  // HONEST load model (replaces the old fabricated static sync-age chip):
  // ledger figures are LIVE on-demand wFirma reads via GET /api/v1/ledgers/*.
  // The chip reports the LAST ACTUAL fetch outcome, lifted from
  // ClientLedgerView; Refresh re-runs the real fetch (refreshKey).
  const [loadInfo, setLoadInfo] = React.useState({ status: 'loading', at: null, count: null, error: null });
  const [refreshKey, setRefreshKey] = React.useState(0);
  const _t = (d) => d ? d.toLocaleTimeString('en-GB') : '';

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

      {/* Top-level tab strip — counts are REAL (clients: from the live list;
          suppliers: no backend ledger route exists yet → no fake count) */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0, marginBottom: 18, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'clients',   label: 'Client Ledger',   count: loadInfo.count },
          { id: 'suppliers', label: 'Supplier Ledger', count: null },
        ].map(t => {
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => { setTab(t.id); setSelectedRow(null); }} style={{
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

      {tab === 'clients'
        ? <ClientLedgerView onSelectRow={setSelectedRow} selectedRow={selectedRow}
            refreshKey={refreshKey}
            onLoadInfo={(info) => setLoadInfo(info)} />
        : <SupplierLedgerView />}

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
function ClientLedgerView({ onSelectRow, selectedRow, refreshKey, onLoadInfo }) {
  const [clients, setClients] = React.useState(null);      // null = loading
  const [listErr, setListErr] = React.useState(null);
  const [active, setActive]   = React.useState('');
  const [stmt, setStmt]       = React.useState({ status: 'idle', data: null, err: null });

  // Live client-balance list. Re-runs on ↻ Refresh (refreshKey).
  React.useEffect(() => {
    let gone = false;
    setClients(null); setListErr(null);
    // Shared roster read: routes through the PzApi transport authority so this
    // page and Accounting Overview reuse ONE live /ledgers/clients?limit=100 read
    // per navigation (short TTL, in-flight coalesced). Manual ↻ Refresh
    // (refreshKey > 0) forces a real new backend read, bypassing the cache.
    window.PzApi.listClientBalancesShared({ limit: 100 }, { force: refreshKey > 0 })
      .then(r => {
        if (gone) return;
        const rows = (r && r.rows) || [];
        setClients(rows);
        onLoadInfo && onLoadInfo({ status: 'ok', at: new Date(), count: rows.length, error: null });
        if (rows.length && !rows.some(x => x.contractor_id === active)) {
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
  }, [refreshKey]);

  const c = (clients || []).find(x => x.contractor_id === active) || null;

  // Live per-client statement (entries + totals + aging). On-demand per
  // selection — same authority the statement PDF uses.
  React.useEffect(() => {
    if (!active) { setStmt({ status: 'idle', data: null, err: null }); return; }
    let gone = false;
    setStmt({ status: 'loading', data: null, err: null });
    const w = LDG_WINDOW();
    window.EstrellaShared.apiFetch(`/api/v1/ledgers/clients/${encodeURIComponent(active)}/statement.json?from=${w.from}&to=${w.to}`)
      .then(r => { if (!gone) setStmt({ status: 'ok', data: r, err: null }); })
      .catch(e => { if (!gone) setStmt({ status: 'error', data: null, err: (e && e.message) || 'statement read failed' }); });
    return () => { gone = true; };
  }, [active, refreshKey]);

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
      {/* Left: client filter list (live rows; '—' when the wFirma read for a
          row failed — balance_available:false is an honest backend state) */}
      <div>
        <LdgFilterPanel
          title="Clients"
          searchPlaceholder="Search clients…"
          extraFilters={[]}
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
        {/* limit=100 is the route maximum; equal counts mean the roster MAY be
            truncated — say so instead of silently hiding clients. */}
        {clients.length >= 100 && (
          <div data-testid="ldg-clients-truncated" style={{ marginTop: 8, fontSize: 10.5, color: 'var(--badge-amber-text)' }}>
            Showing the first 100 clients — the list may be truncated (backend pagination pending).
          </div>
        )}
      </div>

      {/* Right: header card + statement table */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {c && <ClientHeaderCard client={c} stmt={stmt} />}
        {c && <ClientStatementTable client={c} stmt={stmt} onRowClick={onSelectRow} selectedId={selectedRow && selectedRow.id} />}
      </div>
    </div>
  );
}

function ClientHeaderCard({ client: c, stmt }) {
  // LDG-1: every KPI reads the /ledgers/clients row (live wFirma) or renders
  // an honest missing state. Credit-limit / KUKE utilisation bars and
  // inventory-exposure tiles from the old mock are NOT rendered as numbers —
  // no ledger authority serves them yet (see backend-pending note below).
  const unavailable = c.balance_available === false;
  const stmtGen = stmt && stmt.status === 'ok' && stmt.data ? (stmt.data.generated_at || '') : '';
  const w = LDG_WINDOW();
  const pdfHref = `/api/v1/ledgers/clients/${encodeURIComponent(c.contractor_id)}/statement.pdf?from=${w.from}&to=${w.to}`;
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
function ClientStatementTable({ client, stmt, onRowClick, selectedId }) {
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
  const w = LDG_WINDOW();
  const pdfHref = `/api/v1/ledgers/clients/${encodeURIComponent(client.contractor_id)}/statement.pdf?from=${w.from}&to=${w.to}`;

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

// ── SUPPLIER LEDGER ── honest backend-pending state (LDG-1) ───────────────
// No supplier-side ledger route exists (routes_ledgers.py serves clients
// only). The previous view rendered four synthetic suppliers with synthetic
// statements — fake data on an accounting surface. Per the five-state UI
// truth model (Lesson M) the tab STAYS visible and states its real status;
// building the purchase-side ledger is a separate backend campaign.
function SupplierLedgerView() {
  return (
    <div data-testid="ldg-suppliers-pending" style={{ padding: 36, textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 8, background: 'var(--bg-subtle)' }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>Supplier Ledger — backend pending</div>
      <div style={{ fontSize: 12, color: 'var(--text-2)', maxWidth: 560, margin: '0 auto', lineHeight: 1.6 }}>
        There is no supplier-side ledger read authority yet — purchase invoices and payments
        live in wFirma. This tab will activate when a supplier statement route exists
        (mirror of <span style={{ fontFamily: 'monospace' }}>GET /api/v1/ledgers/clients</span>).
        No figures are shown because none would be real.
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
        {extraFilters.map(f => (
          <label key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, padding: '3px 0', color: 'var(--text-2)', cursor: 'pointer' }}>
            <input type="checkbox" /> {f.label}
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
