// ── Ledgers / Statements module ────────────────────────────────────────
// READ-ONLY. Source of truth: wFirma. No manual edits, no payment posting,
// no invoice correction. Shows statements, balances, aging, and links only.
// ───────────────────────────────────────────────────────────────────────

const LDG_FMT = {
  pln: (n) => 'PLN ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  eur: (n) => 'EUR ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
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
function LedgersPage({ initialTab } = {}) {
  const [tab, setTab] = React.useState(initialTab === 'suppliers' ? 'suppliers' : 'clients');
  const [wfirmaState, setWfirmaState] = React.useState('connected'); // connected | disconnected | empty
  const [selectedRow, setSelectedRow] = React.useState(null);

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
          {wfirmaState === 'connected' && (
            <span style={{ fontSize: 11, color: 'var(--badge-green-text)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-green-text)' }} />
              Synced 4 min ago
            </span>
          )}
          {wfirmaState === 'disconnected' && (
            <span style={{ fontSize: 11, color: 'var(--badge-red-text)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--badge-red-text)' }} />
              wFirma disconnected
            </span>
          )}
          <window.Btn small variant="outline">↻ Refresh from wFirma</window.Btn>
        </div>
      </div>

      {/* Top-level tab strip */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0, marginBottom: 18, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'clients',   label: 'Client Ledger',   count: 12 },
          { id: 'suppliers', label: 'Supplier Ledger', count: 47 },
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
              <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', padding: '1px 6px', background: 'var(--bg-subtle)', borderRadius: 3, border: '1px solid var(--border)' }}>{t.count}</span>
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

      {wfirmaState === 'disconnected' ? (
        <LdgErrorState onRetry={() => setWfirmaState('connected')} />
      ) : (
        tab === 'clients'
          ? <ClientLedgerView onSelectRow={setSelectedRow} selectedRow={selectedRow} />
          : <SupplierLedgerView onSelectRow={setSelectedRow} selectedRow={selectedRow} />
      )}

      {selectedRow && (
        <StatementDetailDrawer
          row={selectedRow}
          kind={tab}
          onClose={() => setSelectedRow(null)}
        />
      )}
    </div>
  );
}

// ── CLIENT LEDGER ──────────────────────────────────────────────────────
function ClientLedgerView({ onSelectRow, selectedRow }) {
  const [active, setActive] = React.useState('JU01');

  const clients = [
    { id: 'JU01', name: 'Juliany EOOD',          country: 'BG', vat: 'BG123456789',  wfirma: 'WF-CT-1042', credit: 50000, kuke: 30000, balance: 18450.20, overdue:  4200.00, openInv: 6, openProf: 2, consign: 12400, sample: 3200, lastInv: '04 Apr 2026', lastPay: '28 Mar 2026' },
    { id: 'VH01', name: 'Verhoeven Antwerp',     country: 'BE', vat: 'BE0823.456.789',wfirma: 'WF-CT-1108', credit: 80000, kuke: 60000, balance:  6200.00, overdue:     0.00, openInv: 2, openProf: 1, consign:     0, sample: 1800, lastInv: '02 Apr 2026', lastPay: '31 Mar 2026' },
    { id: 'GE02', name: 'Geneva GIA Office',     country: 'CH', vat: 'CHE-115.823.554',wfirma:'WF-CT-1156', credit: 30000, kuke: 20000, balance:    420.00, overdue:     0.00, openInv: 1, openProf: 0, consign:     0, sample:    0, lastInv: '20 Mar 2026', lastPay: '12 Mar 2026' },
    { id: 'AB03', name: 'Atelier Bonacchi SRL',  country: 'IT', vat: 'IT04520119872', wfirma: 'WF-CT-1207', credit: 25000, kuke: 15000, balance: 27800.50, overdue:  9100.00, openInv: 4, openProf: 0, consign:     0, sample:    0, lastInv: '12 Mar 2026', lastPay: '02 Mar 2026', breach: true },
  ];

  const c = clients.find(x => x.id === active) || clients[0];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
      {/* Left: client filter list */}
      <div>
        <LdgFilterPanel
          title="Clients"
          searchPlaceholder="Search clients…"
          extraFilters={[
            { id: 'overdueOnly',     label: 'Overdue only' },
            { id: 'breachOnly',      label: 'Credit-limit breach' },
            { id: 'hasConsignment',  label: 'Has consignment value' },
          ]}
          items={clients.map(x => ({
            id: x.id, label: x.name, sub: x.country + ' · ' + x.wfirma,
            value: LDG_FMT.pln(x.balance),
            alert: x.overdue > 0 || x.breach,
          }))}
          activeId={active}
          onSelect={setActive}
        />
      </div>

      {/* Right: header card + statement table */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <ClientHeaderCard client={c} />
        <ClientStatementTable client={c} onRowClick={onSelectRow} selectedId={selectedRow?.id} />
      </div>
    </div>
  );
}

function ClientHeaderCard({ client: c }) {
  const utilPct = Math.min(100, Math.round((c.balance / c.credit) * 100));
  const breach = c.balance > c.credit;
  return (
    <window.Card>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{c.name}</div>
            <span style={{ fontSize: 10, color: 'var(--text-3)', padding: '2px 6px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 3 }}>{c.country}</span>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--text-3)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>VAT / Tax ID: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.vat}</span></span>
            <span>wFirma contractor: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.wfirma}</span></span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <window.Btn small variant="outline">View statement</window.Btn>
          <window.Btn small variant="outline">↓ PDF</window.Btn>
          <window.Btn small variant="outline">↓ XLSX</window.Btn>
          <window.Btn small variant="outline">View invoices</window.Btn>
          <window.Btn small variant="outline">View proformas</window.Btn>
          <window.Btn small variant="outline">Inventory exposure</window.Btn>
        </div>
      </div>

      {/* KPI grid */}
      <div style={{ padding: 16, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <LdgStatTile label="Current balance" value={LDG_FMT.pln(c.balance)} sub={`Credit limit ${LDG_FMT.pln(c.credit)}`} tone={breach ? 'red' : null} alert={breach} />
        <LdgStatTile label="Overdue balance" value={LDG_FMT.pln(c.overdue)} sub={c.overdue > 0 ? 'Action required' : 'No overdue'} tone={c.overdue > 0 ? 'red' : 'green'} alert={c.overdue > 0} />
        <LdgStatTile label="Open invoices"   value={c.openInv}                sub={`${c.openProf} open proforma${c.openProf === 1 ? '' : 's'}`} />
        <LdgStatTile label="Inventory exposure" value={LDG_FMT.pln(c.consign + c.sample)} sub={`Consign ${LDG_FMT.pln(c.consign)} · Sample ${LDG_FMT.pln(c.sample)}`} />
      </div>

      {/* Credit utilization + KUKE */}
      <div style={{ padding: '12px 16px 16px', borderTop: '1px solid var(--border-subtle)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text-3)', marginBottom: 5, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            <span>Credit utilization</span>
            <span style={{ color: breach ? 'var(--badge-red-text)' : 'var(--text-2)' }}>{utilPct}% {breach && '· OVER LIMIT'}</span>
          </div>
          <div style={{ height: 7, background: 'var(--bg-subtle)', borderRadius: 4, border: '1px solid var(--border)', overflow: 'hidden' }}>
            <div style={{ width: `${utilPct}%`, height: '100%', background: breach ? 'var(--badge-red-text)' : utilPct > 80 ? 'var(--badge-amber-text)' : 'var(--badge-green-text)' }} />
          </div>
        </div>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text-3)', marginBottom: 5, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            <span>KUKE insured limit</span>
            <span style={{ color: 'var(--text-2)' }}>{LDG_FMT.pln(c.kuke)}</span>
          </div>
          <div style={{ height: 7, background: 'var(--bg-subtle)', borderRadius: 4, border: '1px solid var(--border)', overflow: 'hidden' }}>
            <div style={{ width: `${Math.min(100, (c.balance / c.kuke) * 100)}%`, height: '100%', background: 'var(--badge-blue-text)' }} />
          </div>
        </div>
      </div>

      {/* Footer dates */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: 24, fontSize: 11, color: 'var(--text-3)' }}>
        <span>Last invoice: <span style={{ color: 'var(--text-2)' }}>{c.lastInv}</span></span>
        <span>Last payment: <span style={{ color: 'var(--text-2)' }}>{c.lastPay}</span></span>
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

// ── Compact ERP statement table ────────────────────────────────────────
function ClientStatementTable({ client, onRowClick, selectedId }) {
  // Synthetic statement rows
  const rows = [
    { id: 'INV-2026-148',   date: '04 Apr 2026', doc: 'INV 2026/0148', type: 'Invoice', due: '04 May 2026', debit: 4800.00, credit:    0,    balance: 18450.20, status: 'Open',     source: 'wFirma' },
    { id: 'PAY-2604-08',    date: '01 Apr 2026', doc: 'PAY-2604-08',   type: 'Payment', due: '—',           debit:    0,    credit: 6200.00, balance: 13650.20, status: 'Reconciled', source: 'wFirma' },
    { id: 'PROF-070',       date: '28 Mar 2026', doc: 'PROF 70/2026',  type: 'Proforma',due: '—',           debit:    0,    credit:    0,    balance: 19850.20, status: 'Pending',   source: 'wFirma' },
    { id: 'INV-2026-138',   date: '20 Mar 2026', doc: 'INV 2026/0138', type: 'Invoice', due: '19 Apr 2026', debit: 4200.00, credit:    0,    balance: 19850.20, status: 'Overdue',   source: 'wFirma' },
    { id: 'CN-2026-012',    date: '15 Mar 2026', doc: 'CN 2026/0012',  type: 'Credit note', due: '—',       debit:    0,    credit:  640.00, balance: 15650.20, status: 'Reconciled', source: 'wFirma' },
    { id: 'INV-2026-128',   date: '08 Mar 2026', doc: 'INV 2026/0128', type: 'Invoice', due: '07 Apr 2026', debit: 3290.50, credit:    0,    balance: 16290.20, status: 'Partial',   source: 'wFirma' },
    { id: 'OPENING',        date: '01 Mar 2026', doc: 'Opening',       type: 'Opening', due: '—',           debit: 13000.00,credit:    0,    balance: 13000.00, status: 'Reconciled', source: 'wFirma' },
  ];

  const cols = [
    { id: 'date',  label: 'Date',     w: 100 },
    { id: 'doc',   label: 'Doc no.',  w: 130, mono: true },
    { id: 'type',  label: 'Type',     w: 100 },
    { id: 'due',   label: 'Due',      w: 100 },
    { id: 'debit', label: 'Debit',    w: 110, align: 'right', mono: true },
    { id: 'credit',label: 'Credit',   w: 110, align: 'right', mono: true },
    { id: 'balance',label:'Balance',  w: 120, align: 'right', mono: true, bold: true },
    { id: 'status',label: 'Status',   w: 95 },
    { id: 'source',label: 'Source',   w: 80 },
    { id: 'actions',label: '',        w: 110, align: 'right' },
  ];

  return (
    <window.Card>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Statement</span>
          <LdgSourceBadge />
          <LdgReadOnlyBadge />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <select style={{ fontSize: 11, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--card)', color: 'var(--text-2)' }}>
            <option>This month</option><option>YTD</option><option>Last 12 months</option><option>Custom range…</option>
          </select>
          <window.Btn small variant="outline">↓ PDF</window.Btn>
          <window.Btn small variant="outline">↓ XLSX</window.Btn>
        </div>
      </div>

      <LdgAgingStrip buckets={[
        { label: 'Current', value: LDG_FMT.pln(8950.20) },
        { label: '1–30',    value: LDG_FMT.pln(5300.00), tone: 'amber' },
        { label: '31–60',   value: LDG_FMT.pln(2100.00), tone: 'amber' },
        { label: '61–90',   value: LDG_FMT.pln(1500.00), tone: 'red' },
        { label: '90+',     value: LDG_FMT.pln(600.00),  tone: 'red' },
        { label: 'Total',   value: LDG_FMT.pln(client.balance) },
      ]} />

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              {cols.map(c => (
                <th key={c.id} style={{
                  padding: '8px 12px', textAlign: c.align || 'left', fontSize: 10,
                  fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em',
                  textTransform: 'uppercase', whiteSpace: 'nowrap', width: c.w,
                }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const isSelected = selectedId === r.id;
              const overdue = r.status === 'Overdue';
              return (
                <tr key={r.id}
                  onClick={() => onRowClick(r)}
                  style={{
                    borderBottom: '1px solid var(--border-subtle)',
                    cursor: 'pointer',
                    background: isSelected ? 'var(--bg-subtle)' : overdue ? 'rgba(229, 73, 73, 0.04)' : 'transparent',
                  }}>
                  <td style={{ padding: '8px 12px', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{r.date}</td>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.doc}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-2)' }}>{r.type}</td>
                  <td style={{ padding: '8px 12px', color: overdue ? 'var(--badge-red-text)' : 'var(--text-2)', whiteSpace: 'nowrap', fontWeight: overdue ? 600 : 400 }}>{r.due}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: r.debit > 0 ? 'var(--text)' : 'var(--text-3)' }}>{r.debit > 0 ? LDG_FMT.pln(r.debit) : '—'}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: r.credit > 0 ? 'var(--badge-green-text)' : 'var(--text-3)' }}>{r.credit > 0 ? LDG_FMT.pln(r.credit) : '—'}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text)' }}>{LDG_FMT.pln(r.balance)}</td>
                  <td style={{ padding: '8px 12px' }}><LdgStatusPill status={r.status} /></td>
                  <td style={{ padding: '8px 12px', fontSize: 10, color: 'var(--text-3)' }}>{r.source}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                    <span style={{ display: 'inline-flex', gap: 4 }}>
                      <button style={ldgIconBtn} title="View">👁</button>
                      <button style={ldgIconBtn} title="Download">↓</button>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer summary */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', fontSize: 11.5, background: 'var(--bg-subtle)' }}>
        <span style={{ color: 'var(--text-3)' }}>{rows.length} entries · all sourced from wFirma</span>
        <span style={{ color: 'var(--text)', fontWeight: 700, fontFamily: 'monospace' }}>Closing balance: {LDG_FMT.pln(client.balance)}</span>
      </div>
    </window.Card>
  );
}

// ── SUPPLIER LEDGER ────────────────────────────────────────────────────
function SupplierLedgerView({ onSelectRow, selectedRow }) {
  const [active, setActive] = React.useState('EJ01');

  const suppliers = [
    { id: 'EJ01', name: 'Estrella Jewels LLP',     country: 'IN', vat: 'AAACE1234F', wfirma: 'WF-VN-2014', balance: 32500.00, openPI: 4, paidPI: 28, pendingSvc: 1, pzLinked: 14, lastBuy: '04 Apr 2026', lastPay: '02 Apr 2026', cur: 'EUR' },
    { id: 'IF02', name: 'India Fine Jewels Pvt',   country: 'IN', vat: 'AAACI4567K', wfirma: 'WF-VN-2031', balance:  8400.00, openPI: 1, paidPI: 12, pendingSvc: 0, pzLinked:  9, lastBuy: '20 Mar 2026', lastPay: '15 Mar 2026', cur: 'EUR' },
    { id: 'BG03', name: 'Bangkok Gem Co Ltd',      country: 'TH', vat: '0105537000XYZ',wfirma:'WF-VN-2058',balance:     0.00, openPI: 0, paidPI:  6, pendingSvc: 0, pzLinked:  4, lastBuy: '12 Feb 2026', lastPay: '20 Feb 2026', cur: 'USD' },
    { id: 'DH01', name: 'DHL Express (PL)',        country: 'PL', vat: 'PL5252041377',wfirma: 'WF-VN-2003', balance:  1240.00, openPI: 2, paidPI: 84, pendingSvc: 3, pzLinked:  0, lastBuy: '06 Apr 2026', lastPay: '01 Apr 2026', cur: 'PLN' },
  ];

  const s = suppliers.find(x => x.id === active) || suppliers[0];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
      <LdgFilterPanel
        title="Suppliers"
        searchPlaceholder="Search suppliers…"
        extraFilters={[
          { id: 'openPiOnly',     label: 'Open purchase invoices' },
          { id: 'pendingSvcOnly', label: 'Pending service invoices' },
          { id: 'noPzMatch',      label: 'PI without matching PZ' },
        ]}
        items={suppliers.map(x => ({
          id: x.id, label: x.name, sub: x.country + ' · ' + x.wfirma,
          value: x.cur === 'PLN' ? LDG_FMT.pln(x.balance) : 'EUR ' + x.balance.toLocaleString('en-US', { minimumFractionDigits: 2 }),
          alert: x.openPI > 0,
        }))}
        activeId={active}
        onSelect={setActive}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <SupplierHeaderCard supplier={s} />
        <SupplierStatementTable supplier={s} onRowClick={onSelectRow} selectedId={selectedRow?.id} />
      </div>
    </div>
  );
}

function SupplierHeaderCard({ supplier: s }) {
  const cur = s.cur === 'PLN' ? LDG_FMT.pln : (n) => s.cur + ' ' + n.toLocaleString('en-US', { minimumFractionDigits: 2 });
  return (
    <window.Card>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{s.name}</div>
            <span style={{ fontSize: 10, color: 'var(--text-3)', padding: '2px 6px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 3 }}>{s.country}</span>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--text-3)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>VAT / Tax ID: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{s.vat}</span></span>
            <span>wFirma contractor: <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{s.wfirma}</span></span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <window.Btn small variant="outline">View statement</window.Btn>
          <window.Btn small variant="outline">↓ PDF</window.Btn>
          <window.Btn small variant="outline">↓ XLSX</window.Btn>
          <window.Btn small variant="outline">View linked PZ</window.Btn>
          <window.Btn small variant="outline">View invoices</window.Btn>
        </div>
      </div>

      <div style={{ padding: 16, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <LdgStatTile label="Current balance"      value={cur(s.balance)}             sub={`Currency: ${s.cur}`} />
        <LdgStatTile label="Open purchase inv."   value={s.openPI}                    sub={`${s.paidPI} paid (lifetime)`} alert={s.openPI > 0} tone={s.openPI > 0 ? 'amber' : null} />
        <LdgStatTile label="Pending service inv." value={s.pendingSvc}                sub="Cost lines awaiting invoice" />
        <LdgStatTile label="PZ-linked purchases"  value={s.pzLinked}                  sub="Goods receipts matched" />
      </div>

      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: 24, fontSize: 11, color: 'var(--text-3)' }}>
        <span>Last purchase: <span style={{ color: 'var(--text-2)' }}>{s.lastBuy}</span></span>
        <span>Last payment: <span style={{ color: 'var(--text-2)' }}>{s.lastPay}</span></span>
      </div>
    </window.Card>
  );
}

function SupplierStatementTable({ supplier, onRowClick, selectedId }) {
  const cur = supplier.cur === 'PLN' ? LDG_FMT.pln : (n) => supplier.cur + ' ' + n.toLocaleString('en-US', { minimumFractionDigits: 2 });

  const rows = [
    { id: 'PI-EJ-148', date: '04 Apr 2026', doc: 'PI-EJ-2026/148', type: 'Purchase invoice', due: '04 Jul 2026', debit:    0,    credit: 14200.00, balance: 32500.00, status: 'Open',       source: 'wFirma', linkPz: 'PZ-2604-013' },
    { id: 'PAY-2604-04',date:'02 Apr 2026', doc: 'PAY-2604-04',    type: 'Payment',          due: '—',           debit: 8000.00, credit:    0,    balance: 18300.00, status: 'Reconciled', source: 'wFirma' },
    { id: 'SVC-DHL-09',date:'01 Apr 2026',  doc: 'SVC-DHL-09',     type: 'Service invoice',  due: '15 Apr 2026', debit:    0,    credit:    420.00, balance: 26300.00, status: 'Open',       source: 'wFirma' },
    { id: 'PI-EJ-141', date: '20 Mar 2026', doc: 'PI-EJ-2026/141', type: 'Purchase invoice', due: '20 Jun 2026', debit:    0,    credit:  6300.00, balance: 25880.00, status: 'Open',       source: 'wFirma', linkPz: 'PZ-2603-009' },
    { id: 'PAY-2603-12',date:'15 Mar 2026', doc: 'PAY-2603-12',    type: 'Payment',          due: '—',           debit: 5000.00, credit:    0,    balance: 19580.00, status: 'Reconciled', source: 'wFirma' },
    { id: 'OPENING-S', date: '01 Mar 2026', doc: 'Opening',        type: 'Opening',          due: '—',           debit: 14580.00,credit:    0,    balance: 14580.00, status: 'Reconciled', source: 'wFirma' },
  ];

  const cols = [
    { id: 'date',   label: 'Date',    w: 100 },
    { id: 'doc',    label: 'Doc no.', w: 150, mono: true },
    { id: 'type',   label: 'Type',    w: 130 },
    { id: 'due',    label: 'Due',     w: 100 },
    { id: 'debit',  label: 'Debit',   w: 110, align: 'right' },
    { id: 'credit', label: 'Credit',  w: 110, align: 'right' },
    { id: 'balance',label: 'Balance', w: 120, align: 'right' },
    { id: 'status', label: 'Status',  w: 95 },
    { id: 'pz',     label: 'PZ link', w: 110 },
    { id: 'source', label: 'Source',  w: 80 },
    { id: 'actions',label: '',        w: 110, align: 'right' },
  ];

  return (
    <window.Card>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Supplier statement</span>
          <LdgSourceBadge />
          <LdgReadOnlyBadge />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <select style={{ fontSize: 11, padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--card)', color: 'var(--text-2)' }}>
            <option>This month</option><option>YTD</option><option>Last 12 months</option><option>Custom range…</option>
          </select>
          <window.Btn small variant="outline">↓ PDF</window.Btn>
          <window.Btn small variant="outline">↓ XLSX</window.Btn>
        </div>
      </div>

      <LdgAgingStrip buckets={[
        { label: 'Current', value: cur(18000) },
        { label: '1–30',    value: cur(8200), tone: 'amber' },
        { label: '31–60',   value: cur(4300), tone: 'amber' },
        { label: '61–90',   value: cur(2000), tone: 'red' },
        { label: '90+',     value: cur(0) },
        { label: 'Total',   value: cur(supplier.balance) },
      ]} />

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              {cols.map(c => (
                <th key={c.id} style={{
                  padding: '8px 12px', textAlign: c.align || 'left', fontSize: 10,
                  fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em',
                  textTransform: 'uppercase', whiteSpace: 'nowrap', width: c.w,
                }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const isSelected = selectedId === r.id;
              const overdue = r.status === 'Overdue';
              return (
                <tr key={r.id}
                  onClick={() => onRowClick(r)}
                  style={{
                    borderBottom: '1px solid var(--border-subtle)',
                    cursor: 'pointer',
                    background: isSelected ? 'var(--bg-subtle)' : overdue ? 'rgba(229, 73, 73, 0.04)' : 'transparent',
                  }}>
                  <td style={{ padding: '8px 12px', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{r.date}</td>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.doc}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-2)' }}>{r.type}</td>
                  <td style={{ padding: '8px 12px', color: overdue ? 'var(--badge-red-text)' : 'var(--text-2)', whiteSpace: 'nowrap' }}>{r.due}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: r.debit > 0 ? 'var(--text)' : 'var(--text-3)' }}>{r.debit > 0 ? cur(r.debit) : '—'}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', color: r.credit > 0 ? 'var(--text)' : 'var(--text-3)' }}>{r.credit > 0 ? cur(r.credit) : '—'}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text)' }}>{cur(r.balance)}</td>
                  <td style={{ padding: '8px 12px' }}><LdgStatusPill status={r.status} /></td>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 10.5 }}>
                    {r.linkPz
                      ? <a href="#" style={{ color: 'var(--accent)' }} onClick={e => e.preventDefault()}>{r.linkPz}</a>
                      : <span style={{ color: 'var(--text-3)' }}>—</span>}
                  </td>
                  <td style={{ padding: '8px 12px', fontSize: 10, color: 'var(--text-3)' }}>{r.source}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                    <span style={{ display: 'inline-flex', gap: 4 }}>
                      <button style={ldgIconBtn} title="View">👁</button>
                      <button style={ldgIconBtn} title="Download">↓</button>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', fontSize: 11.5, background: 'var(--bg-subtle)' }}>
        <span style={{ color: 'var(--text-3)' }}>{rows.length} entries · all sourced from wFirma</span>
        <span style={{ color: 'var(--text)', fontWeight: 700, fontFamily: 'monospace' }}>Closing balance: {cur(supplier.balance)}</span>
      </div>
    </window.Card>
  );
}

// ── Filter panel (left) ────────────────────────────────────────────────
function LdgFilterPanel({ title, searchPlaceholder, items, activeId, onSelect, extraFilters }) {
  return (
    <window.Card style={{ padding: 0, position: 'sticky', top: 0 }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>{title}</div>
        <input placeholder={searchPlaceholder} style={{
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
        {items.map(it => {
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

// ── Statement detail drawer (right-side) ───────────────────────────────
function StatementDetailDrawer({ row, kind, onClose }) {
  const isInvoice = row.type === 'Invoice' || row.type === 'Purchase invoice';
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 900, display: 'flex', justifyContent: 'flex-end',
      background: 'rgba(0,0,0,0.18)',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        width: 520, height: '100%', background: 'var(--card)',
        borderLeft: '1px solid var(--border)', boxShadow: '-12px 0 32px rgba(0,0,0,0.06)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{row.doc}</span>
              <LdgStatusPill status={row.status} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <LdgSourceBadge />
              <LdgReadOnlyBadge />
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-3)' }}>×</button>
        </div>

        {/* Meta grid */}
        <div style={{ padding: 18, borderBottom: '1px solid var(--border-subtle)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {[
            ['Type',          row.type],
            ['Date',          row.date],
            ['Due date',      row.due],
            ['Debit',         row.debit > 0 ? LDG_FMT.pln(row.debit) : '—'],
            ['Credit',        row.credit > 0 ? LDG_FMT.pln(row.credit) : '—'],
            ['Balance after', LDG_FMT.pln(row.balance)],
            ['Source',        row.source],
            ['wFirma doc id', 'WF-DOC-' + row.id],
          ].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 3 }}>{k}</div>
              <div style={{ fontSize: 12, color: 'var(--text)', fontFamily: k === 'wFirma doc id' || k === 'Balance after' || k === 'Debit' || k === 'Credit' ? 'monospace' : 'inherit' }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Document preview placeholder */}
        <div style={{ padding: 18, borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Document preview</div>
          <div style={{
            border: '1px dashed var(--border)', borderRadius: 6,
            padding: '40px 18px', textAlign: 'center',
            background: 'var(--bg-subtle)',
          }}>
            <div style={{ fontSize: 32, color: 'var(--text-3)', marginBottom: 4 }}>📄</div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', fontWeight: 600 }}>{row.doc}.pdf</div>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 4 }}>Pulled from wFirma · 184 KB · 2 pages</div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginTop: 12 }}>
              <window.Btn small variant="outline">Open viewer</window.Btn>
              <window.Btn small variant="outline">↓ PDF</window.Btn>
            </div>
          </div>
        </div>

        {/* Linked operational movements */}
        <div style={{ padding: 18, flex: 1, overflowY: 'auto' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Linked operational movements</div>
          <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginBottom: 10, fontStyle: 'italic' }}>
            Operational links — separate from the accounting balance above
          </div>
          {[
            isInvoice && { kind: 'Shipment',         id: 'SHP-2026-0142',  detail: 'AWB DHL-1234567890 · cleared 04 Apr' },
            isInvoice && { kind: 'PZ goods receipt', id: 'PZ-2604-013',    detail: '14 lines · PLN 18,420 cost basis' },
            kind === 'clients' && isInvoice && { kind: 'Sample exposure', id: 'SMP-2604-002', detail: '1 pc held by client · EUR 1,800' },
            kind === 'clients' && isInvoice && { kind: 'Consignment',     id: 'CSG-2603-007', detail: '3 pcs on consignment · EUR 12,400' },
            { kind: 'Audit event', id: 'AUD-2604-2148', detail: 'Synced from wFirma · 04 Apr 14:42 · by anna.k' },
          ].filter(Boolean).map(l => (
            <div key={l.id} style={{
              padding: '10px 12px', borderRadius: 6,
              border: '1px solid var(--border)', marginBottom: 8,
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10,
            }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{l.kind}</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', fontFamily: 'monospace', marginTop: 2 }}>{l.id}</div>
                <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{l.detail}</div>
              </div>
              <window.Btn small variant="outline">Open →</window.Btn>
            </div>
          ))}
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

// ── Error / empty states ───────────────────────────────────────────────
function LdgErrorState({ onRetry }) {
  return (
    <div style={{
      padding: '60px 24px', textAlign: 'center',
      background: 'var(--card)', border: '1px solid var(--badge-red-border)',
      borderRadius: 8,
    }}>
      <div style={{ fontSize: 36, color: 'var(--badge-red-text)', marginBottom: 8 }}>⚠</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>wFirma is disconnected</div>
      <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 14, maxWidth: 480, margin: '0 auto 14px' }}>
        Ledger data is read-only and depends on wFirma. Without a live connection no balances or statements can be displayed. Reconnect in <strong>Admin → Integrations</strong> or retry below.
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
        <window.Btn variant="outline" small>Open Admin → Integrations</window.Btn>
        <window.Btn variant="gold" small onClick={onRetry}>Retry connection</window.Btn>
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
