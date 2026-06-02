// ─────────────────────────────────────────────────────────────────────────────
// AccountingHub — consolidated accounting workspace.
//
// All document types and ledgers mapped from wFirma:
//   Proforma · Invoice · WZ · PZ · RW · PW · MM · Credit Note · Debit Note
//   Client Balance · Client Ledger · Supplier Ledger · wFirma Sync
//
// Visual hub: left rail = doc type / ledger picker, main area = filtered grid.
// Backend (stubbed):
//   GET  /api/v1/accounting/{type}?from=&to=&party=
//   GET  /api/v1/ledger/clients
//   GET  /api/v1/ledger/suppliers
//   POST /api/v1/wfirma/sync/{type}
// ─────────────────────────────────────────────────────────────────────────────

const ACC_SECTIONS = [
  { id: 'overview',    label: 'Overview',          icon: '◈', group: 'top' },

  { id: 'pi',          label: 'Proforma',          icon: '✎', group: 'sales',    code: 'PI',   color: 'var(--badge-blue-text)' },
  { id: 'inv',         label: 'Invoice',           icon: '⊞', group: 'sales',    code: 'INV',  color: 'var(--badge-green-text)' },
  { id: 'cn',          label: 'Credit Note',       icon: '↩', group: 'sales',    code: 'CN',   color: 'var(--badge-amber-text)' },

  { id: 'wz',          label: 'WZ — Outbound',     icon: '↗', group: 'warehouse',code: 'WZ',   color: 'var(--badge-purple-text)' },
  { id: 'pz',          label: 'PZ — Inbound',      icon: '↘', group: 'warehouse',code: 'PZ',   color: 'var(--accent)' },
  { id: 'pw',          label: 'PW — Internal in',  icon: '⊕', group: 'warehouse',code: 'PW',   color: 'var(--badge-blue-text)' },
  { id: 'rw',          label: 'RW — Internal out', icon: '⊖', group: 'warehouse',code: 'RW',   color: 'var(--badge-red-text)' },
  { id: 'mm',          label: 'MM — Transfer',     icon: '⇄', group: 'warehouse',code: 'MM',   color: 'var(--badge-neutral-text)' },

  { id: 'balance',     label: 'Client Balance',    icon: '⊜', group: 'ledger' },
  { id: 'clientLedger',label: 'Client Ledger',     icon: '☷', group: 'ledger' },
  { id: 'supplierLedger',label: 'Supplier Ledger', icon: '☷', group: 'ledger' },

  { id: 'wfirma',      label: 'wFirma Sync',       icon: '↻', group: 'system' },
];

// ── Sample data — every shown number is illustrative only ─────────────
const ACC_DOCS = {
  pi: [
    { num: 'PI-2026/0143', date: '2026-04-22', party: 'Maison Royale SARL',  net: 8000.00,  tax: 1840.00, gross: 9840.50,  cur: 'EUR', state: 'draft',     wf: 'pending'  },
    { num: 'PI-2026/0142', date: '2026-04-21', party: 'Aurum Watches GmbH',  net: 14975.61, tax: 3444.39, gross: 18420.00, cur: 'EUR', state: 'sent',      wf: 'synced'   },
    { num: 'PI-2026/0141', date: '2026-04-20', party: 'Crown Jewelers Ltd',  net: 19593.50, tax: 4506.50, gross: 24100.00, cur: 'USD', state: 'sent',      wf: 'synced'   },
    { num: 'PI-2026/0140', date: '2026-04-19', party: 'Hôtel Belle Étoile',  net: 3430.89,  tax: 789.11,  gross: 4220.00,  cur: 'EUR', state: 'accepted',  wf: 'synced'   },
  ],
  inv: [
    { num: 'INV-2026/0089', date: '2026-04-22', party: 'Crown Jewelers Ltd', net: 19593.50, tax: 4506.50, gross: 24100.00, cur: 'USD', state: 'paid',      wf: 'synced'   },
    { num: 'INV-2026/0088', date: '2026-04-20', party: 'Aurum Watches GmbH', net: 14975.61, tax: 3444.39, gross: 18420.00, cur: 'EUR', state: 'open',      wf: 'synced'   },
    { num: 'INV-2026/0087', date: '2026-04-18', party: 'Bijoux Sélection',   net: 1495.93,  tax: 344.07,  gross: 1840.00,  cur: 'EUR', state: 'overdue',   wf: 'synced'   },
    { num: 'INV-2026/0086', date: '2026-04-15', party: 'Hôtel Belle Étoile', net: 3430.89,  tax: 789.11,  gross: 4220.00,  cur: 'EUR', state: 'paid',      wf: 'synced'   },
  ],
  cn: [
    { num: 'CN-2026/0012', date: '2026-04-18', party: 'Bijoux Sélection',    net: -240.00,  tax: -55.20,  gross: -295.20,  cur: 'EUR', state: 'issued',    wf: 'pending'  },
  ],
  wz: [
    { num: 'WZ-2026/0142', date: '2026-04-22', party: 'Aurum Watches GmbH', items: 4,  ref: 'INV-2026/0088', state: 'released', wf: 'synced'  },
    { num: 'WZ-2026/0141', date: '2026-04-21', party: 'Crown Jewelers Ltd', items: 6,  ref: 'INV-2026/0089', state: 'released', wf: 'synced'  },
    { num: 'WZ-2026/0140', date: '2026-04-19', party: 'Hôtel Belle Étoile', items: 2,  ref: 'PI-2026/0140',  state: 'draft',    wf: 'pending' },
  ],
  pz: [
    { num: 'PZ-2026-014', date: '2026-04-23', party: 'Manufaktura Złota',  items: 4,  ref: 'B-2026-014', state: 'received',  wf: 'synced'  },
    { num: 'PZ-2026-013', date: '2026-04-19', party: 'Patek Philippe SA',  items: 7,  ref: 'B-2026-013', state: 'received',  wf: 'synced'  },
    { num: 'PZ-2026-012', date: '2026-04-17', party: 'Audemars Piguet',    items: 12, ref: 'B-2026-012', state: 'received',  wf: 'synced'  },
  ],
  pw: [
    { num: 'PW-2026-008', date: '2026-04-22', party: 'Internal — Showroom', items: 1, ref: 'Sample return', state: 'posted',  wf: 'synced'  },
  ],
  rw: [
    { num: 'RW-2026-021', date: '2026-04-20', party: 'Internal — Marketing', items: 2, ref: 'Sample out',   state: 'posted',  wf: 'synced'  },
    { num: 'RW-2026-020', date: '2026-04-18', party: 'Internal — Workshop',  items: 1, ref: 'Reworking',    state: 'posted',  wf: 'synced'  },
  ],
  mm: [
    { num: 'MM-2026-004', date: '2026-04-19', party: 'Temp → Final',        items: 7, ref: 'B-2026-013',   state: 'posted',  wf: 'synced'  },
  ],
};

const CLIENT_BALANCE = [
  { client: 'Crown Jewelers Ltd',  open: 18200.00, overdue:     0, last30: 42300.00, ytd: 184500.00, cur: 'USD', state: 'healthy' },
  { client: 'Aurum Watches GmbH',  open: 18420.00, overdue:     0, last30: 22640.00, ytd:  98750.00, cur: 'EUR', state: 'healthy' },
  { client: 'Bijoux Sélection',    open:  1840.00, overdue:  1840, last30:  1840.00, ytd:  18420.00, cur: 'EUR', state: 'overdue' },
  { client: 'Hôtel Belle Étoile',  open:     0,    overdue:     0, last30:  8440.00, ytd:  56720.00, cur: 'EUR', state: 'healthy' },
  { client: 'Maison Royale SARL',  open:  9840.50, overdue:     0, last30:  9840.50, ytd:  18420.50, cur: 'EUR', state: 'pending' },
];

const CLIENT_LEDGER = [
  { date: '2026-04-22', client: 'Aurum Watches GmbH', ref: 'INV-2026/0088', desc: 'Sales invoice',           debit: 18420.00, credit:     0, balance: 18420.00 },
  { date: '2026-04-21', client: 'Aurum Watches GmbH', ref: 'PI-2026/0142',  desc: 'Proforma issued',         debit:    0,     credit:     0, balance:     0    },
  { date: '2026-04-15', client: 'Hôtel Belle Étoile', ref: 'INV-2026/0086', desc: 'Sales invoice',           debit:  4220.00, credit:     0, balance:  4220.00 },
  { date: '2026-04-16', client: 'Hôtel Belle Étoile', ref: 'PAY-114',       desc: 'Payment received',        debit:    0,     credit:  4220.00, balance:    0    },
  { date: '2026-04-18', client: 'Bijoux Sélection',   ref: 'INV-2026/0087', desc: 'Sales invoice',           debit:  1840.00, credit:    0,    balance:  1840.00 },
  { date: '2026-04-22', client: 'Crown Jewelers Ltd', ref: 'INV-2026/0089', desc: 'Sales invoice',           debit: 24100.00, credit:    0,    balance: 24100.00 },
  { date: '2026-04-23', client: 'Crown Jewelers Ltd', ref: 'PAY-118',       desc: 'Payment received',        debit:    0,     credit: 24100.00, balance:    0    },
];

const SUPPLIER_LEDGER = [
  { date: '2026-04-23', supplier: 'Manufaktura Złota',  ref: 'PZ-2026-014',  desc: 'Goods received',         debit:    0,     credit: 18420.00, balance: 18420.00 },
  { date: '2026-04-19', supplier: 'Patek Philippe SA',  ref: 'PZ-2026-013',  desc: 'Goods received',         debit:    0,     credit: 142000.0, balance: 142000.0 },
  { date: '2026-04-20', supplier: 'Patek Philippe SA',  ref: 'PAY-OUT-099',  desc: 'Wire transfer',          debit: 142000.0, credit:    0,    balance:    0    },
  { date: '2026-04-17', supplier: 'Audemars Piguet',    ref: 'PZ-2026-012',  desc: 'Goods received',         debit:    0,     credit:  88400.0, balance:  88400.0 },
];

function AccountingHub({ onNav }) {
  const [section, setSection] = React.useState('overview');
  const activeConf = ACC_SECTIONS.find(s => s.id === section);

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      {/* Left rail — section picker */}
      <div style={{
        width: 220, flexShrink: 0, background: 'var(--bg-subtle)',
        borderRight: '1px solid var(--border)', padding: '12px 0',
        overflowY: 'auto',
      }}>
        <AccRailGroup label="" sections={ACC_SECTIONS.filter(s => s.group === 'top')} active={section} onClick={setSection} />
        <AccRailGroup label="Sales documents"   sections={ACC_SECTIONS.filter(s => s.group === 'sales')}     active={section} onClick={setSection} />
        <AccRailGroup label="Warehouse documents" sections={ACC_SECTIONS.filter(s => s.group === 'warehouse')} active={section} onClick={setSection} />
        <AccRailGroup label="Ledgers"           sections={ACC_SECTIONS.filter(s => s.group === 'ledger')}    active={section} onClick={setSection} />
        <AccRailGroup label="System"            sections={ACC_SECTIONS.filter(s => s.group === 'system')}    active={section} onClick={setSection} />

        <div style={{ margin: '16px 14px', padding: 10, background: 'var(--card)', border: '1px solid var(--accent-border)', borderRadius: 6 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Source</div>
          <div style={{ fontSize: 10.5, color: 'var(--text-2)', lineHeight: 1.4 }}>All documents and balances are mapped <strong>from wFirma</strong> · last sync 2h ago</div>
        </div>
      </div>

      {/* Main area */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {section === 'overview'      && <AccOverview onJump={setSection} />}
        {ACC_DOCS[section]           && <AccDocGrid conf={activeConf} rows={ACC_DOCS[section]} />}
        {section === 'balance'       && <AccBalance rows={CLIENT_BALANCE} />}
        {section === 'clientLedger'  && <AccLedger rows={CLIENT_LEDGER} partyKey="client"   title="Client Ledger" />}
        {section === 'supplierLedger'&& <AccLedger rows={SUPPLIER_LEDGER} partyKey="supplier" title="Supplier Ledger" />}
        {section === 'wfirma'        && <AccWfirmaSync />}
      </div>
    </div>
  );
}

function AccRailGroup({ label, sections, active, onClick }) {
  if (!sections.length) return null;
  return (
    <div style={{ marginBottom: 14 }}>
      {label && <div style={{ padding: '4px 16px 6px', fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>}
      {sections.map(s => {
        const a = active === s.id;
        return (
          <button key={s.id} onClick={() => onClick(s.id)} style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 10,
            padding: '7px 16px', background: a ? 'var(--card)' : 'transparent',
            border: 'none', cursor: 'pointer', textAlign: 'left',
            borderLeft: a ? '3px solid var(--accent)' : '3px solid transparent',
          }}>
            <span style={{ width: 14, fontSize: 12, color: a ? 'var(--accent)' : 'var(--text-3)' }}>{s.icon}</span>
            <span style={{ flex: 1, fontSize: 11.5, color: a ? 'var(--text)' : 'var(--text-2)', fontWeight: a ? 600 : 400 }}>{s.label}</span>
            {s.code && <span style={{
              fontSize: 8.5, padding: '0px 4px', borderRadius: 2,
              background: 'var(--bg-subtle)', color: s.color,
              border: '1px solid var(--border)', fontWeight: 700, fontFamily: 'monospace',
            }}>{s.code}</span>}
          </button>
        );
      })}
    </div>
  );
}

function AccOverview({ onJump }) {
  const totals = {
    salesOpen: 33100.50, salesOverdue: 1840.00,
    purchaseOpen: 18420.00, purchaseOverdue: 0,
    piCount: 12, invCount: 28, wzCount: 18, pzCount: 9,
  };
  return (
    <div style={{ padding: '20px 28px 40px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        <AccKpi label="Sales receivable"   value="€33.1K" hint="2 invoices open" accent="var(--badge-blue-text)" />
        <AccKpi label="Sales overdue"      value="€1.84K" hint="1 invoice · Bijoux" accent="var(--badge-red-text)" />
        <AccKpi label="Supplier payable"   value="€18.4K" hint="1 PZ open" accent="var(--badge-amber-text)" />
        <AccKpi label="Last wFirma sync"   value="2h ago" hint="last full sync" accent="var(--accent)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 18 }}>
        <AccSummaryCard title="Sales documents · April 2026" rows={[
          { label: 'Proforma issued',  value: 12, action: () => onJump('pi'),  code: 'PI' },
          { label: 'Invoices issued',  value: 28, action: () => onJump('inv'), code: 'INV' },
          { label: 'Credit notes',     value:  1, action: () => onJump('cn'),  code: 'CN' },
          { label: 'WZ releases',      value: 18, action: () => onJump('wz'),  code: 'WZ' },
        ]}/>
        <AccSummaryCard title="Warehouse documents · April 2026" rows={[
          { label: 'PZ (external receipt)', value: 9, action: () => onJump('pz'), code: 'PZ' },
          { label: 'PW (internal receipt)', value: 1, action: () => onJump('pw'), code: 'PW' },
          { label: 'RW (internal release)', value: 2, action: () => onJump('rw'), code: 'RW' },
          { label: 'MM (transfer)',         value: 4, action: () => onJump('mm'), code: 'MM' },
        ]}/>
      </div>

      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Document map</span>
          <span style={{ fontSize: 10, color: 'var(--text-3)' }}>How sales & warehouse documents connect</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, fontSize: 10.5 }}>
          {[
            { c: 'PI',  l: 'Proforma',         h: 'Quote to client'              },
            { c: 'INV', l: 'Sales Invoice',    h: 'Issued on shipment'           },
            { c: 'WZ',  l: 'Outbound release', h: 'Linked to INV — stock leaves' },
            { c: 'PZ',  l: 'Inbound receipt',  h: 'Stock arrives from supplier'  },
            { c: 'CN',  l: 'Credit Note',      h: 'Correction / refund'          },
          ].map((n, i) => (
            <div key={n.c} style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace', marginBottom: 2 }}>{n.c}</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>{n.l}</div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{n.h}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AccKpi({ label, value, hint, accent }) {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 6, padding: '12px 14px' }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', marginTop: 4, fontFamily: '"DM Serif Display", serif' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>
    </div>
  );
}

function AccSummaryCard({ title, rows }) {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>{title}</div>
      {rows.map(r => (
        <button key={r.label} onClick={r.action} style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 0', background: 'transparent', border: 'none',
          borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', textAlign: 'left',
        }}>
          <span style={{ fontSize: 9, fontFamily: 'monospace', padding: '1px 5px', borderRadius: 2, background: 'var(--accent-subtle)', color: 'var(--accent)', fontWeight: 700, minWidth: 28, textAlign: 'center' }}>{r.code}</span>
          <span style={{ flex: 1, fontSize: 11.5, color: 'var(--text-2)' }}>{r.label}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{r.value}</span>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>›</span>
        </button>
      ))}
    </div>
  );
}

function AccDocGrid({ conf, rows }) {
  const isWarehouse = ['wz','pz','pw','rw','mm'].includes(conf.id);
  return (
    <div style={{ padding: '20px 28px 40px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>{conf.label}</span>
        <span style={{ fontSize: 9, fontFamily: 'monospace', padding: '2px 6px', borderRadius: 2, background: 'var(--accent-subtle)', color: 'var(--accent)', fontWeight: 700, letterSpacing: '0.04em' }}>{conf.code}</span>
        <span style={{ flex: 1 }}></span>
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Source: wFirma</span>
        <button style={accBtnOutline}>↻ Sync</button>
        <button style={accBtnOutline}>↓ Export</button>
        <button style={accBtnGold}>+ New {conf.code}</button>
      </div>

      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: isWarehouse ? '140px 100px 1fr 90px 140px 110px 100px 80px' : '140px 100px 1fr 110px 110px 110px 70px 100px 100px 80px', padding: '10px 14px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          <div>Number</div>
          <div>Date</div>
          <div>{conf.code === 'PZ' ? 'Supplier' : 'Party'}</div>
          {!isWarehouse && <>
            <div style={{ textAlign: 'right' }}>Net</div>
            <div style={{ textAlign: 'right' }}>Tax</div>
            <div style={{ textAlign: 'right' }}>Gross</div>
            <div>Cur</div>
          </>}
          {isWarehouse && <>
            <div style={{ textAlign: 'right' }}>Items</div>
            <div>Linked</div>
          </>}
          <div>State</div>
          <div>wFirma</div>
          <div></div>
        </div>
        {rows.map(r => (
          <div key={r.num} style={{ display: 'grid', gridTemplateColumns: isWarehouse ? '140px 100px 1fr 90px 140px 110px 100px 80px' : '140px 100px 1fr 110px 110px 110px 70px 100px 100px 80px', padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11.5, color: 'var(--text-2)', alignItems: 'center' }}>
            <div style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{r.num}</div>
            <div style={{ fontFamily: 'monospace' }}>{r.date}</div>
            <div style={{ color: 'var(--text)' }}>{r.party}</div>
            {!isWarehouse && <>
              <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{r.net.toFixed(2)}</div>
              <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{r.tax.toFixed(2)}</div>
              <div style={{ textAlign: 'right', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{r.gross.toFixed(2)}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10 }}>{r.cur}</div>
            </>}
            {isWarehouse && <>
              <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{r.items}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--accent)' }}>{r.ref}</div>
            </>}
            <div><StateChip state={r.state} /></div>
            <div><WfChip state={r.wf} /></div>
            <div style={{ display: 'flex', gap: 4 }}>
              <button style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 3, padding: '2px 6px', fontSize: 10, cursor: 'pointer' }}>View</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AccBalance({ rows }) {
  return (
    <div style={{ padding: '20px 28px 40px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>Client Balance</span>
        <span style={{ flex: 1 }}></span>
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Source: wFirma · ledger snapshot</span>
        <button style={accBtnOutline}>↻ Refresh</button>
        <button style={accBtnOutline}>↓ Export</button>
      </div>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 120px 120px 120px 130px 70px 100px', padding: '10px 14px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          <div>Client</div>
          <div style={{ textAlign: 'right' }}>Open</div>
          <div style={{ textAlign: 'right' }}>Overdue</div>
          <div style={{ textAlign: 'right' }}>Last 30d</div>
          <div style={{ textAlign: 'right' }}>YTD</div>
          <div>Cur</div>
          <div>State</div>
        </div>
        {rows.map(r => (
          <div key={r.client} style={{ display: 'grid', gridTemplateColumns: '1.4fr 120px 120px 120px 130px 70px 100px', padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11.5, alignItems: 'center' }}>
            <div style={{ fontWeight: 600, color: 'var(--text)' }}>{r.client}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: r.open > 0 ? 'var(--text)' : 'var(--text-3)' }}>{r.open.toFixed(2)}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: r.overdue > 0 ? 'var(--badge-red-text)' : 'var(--text-3)', fontWeight: r.overdue > 0 ? 700 : 400 }}>{r.overdue.toFixed(2)}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.last30.toFixed(2)}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.ytd.toFixed(2)}</div>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-3)' }}>{r.cur}</div>
            <div><StateChip state={r.state} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AccLedger({ rows, partyKey, title }) {
  return (
    <div style={{ padding: '20px 28px 40px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>{title}</span>
        <span style={{ flex: 1 }}></span>
        <select style={{ padding: '5px 10px', borderRadius: 4, border: '1px solid var(--border)', fontSize: 11, background: 'var(--card)' }}>
          <option>All {partyKey}s</option>
        </select>
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Source: wFirma</span>
        <button style={accBtnOutline}>↓ Export</button>
      </div>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '110px 1.3fr 140px 1fr 120px 120px 130px', padding: '10px 14px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          <div>Date</div>
          <div>{partyKey === 'client' ? 'Client' : 'Supplier'}</div>
          <div>Reference</div>
          <div>Description</div>
          <div style={{ textAlign: 'right' }}>Debit</div>
          <div style={{ textAlign: 'right' }}>Credit</div>
          <div style={{ textAlign: 'right' }}>Balance</div>
        </div>
        {rows.map((r, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '110px 1.3fr 140px 1fr 120px 120px 130px', padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11.5, alignItems: 'center' }}>
            <div style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.date}</div>
            <div style={{ fontWeight: 600, color: 'var(--text)' }}>{r[partyKey]}</div>
            <div style={{ fontFamily: 'monospace', fontSize: 10.5, color: 'var(--accent)' }}>{r.ref}</div>
            <div style={{ color: 'var(--text-2)' }}>{r.desc}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: r.debit > 0 ? 'var(--text)' : 'var(--text-3)' }}>{r.debit > 0 ? r.debit.toFixed(2) : '—'}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: r.credit > 0 ? 'var(--badge-green-text)' : 'var(--text-3)' }}>{r.credit > 0 ? r.credit.toFixed(2) : '—'}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{r.balance.toFixed(2)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AccWfirmaSync() {
  const mappings = [
    { type: 'Proforma',    code: 'PI',  wf: 'invoices/proforma',       state: 'synced',  count: 12, last: '2h ago' },
    { type: 'Invoice',     code: 'INV', wf: 'invoices/normal',         state: 'synced',  count: 28, last: '2h ago' },
    { type: 'Credit Note', code: 'CN',  wf: 'invoices/correction',     state: 'synced',  count:  1, last: '2h ago' },
    { type: 'WZ',          code: 'WZ',  wf: 'warehouse/wz',            state: 'synced',  count: 18, last: '2h ago' },
    { type: 'PZ',          code: 'PZ',  wf: 'warehouse/pz',            state: 'synced',  count:  9, last: '2h ago' },
    { type: 'PW',          code: 'PW',  wf: 'warehouse/pw',            state: 'synced',  count:  1, last: '2h ago' },
    { type: 'RW',          code: 'RW',  wf: 'warehouse/rw',            state: 'synced',  count:  2, last: '2h ago' },
    { type: 'MM',          code: 'MM',  wf: 'warehouse/mm',            state: 'pending', count:  4, last: '6h ago' },
    { type: 'Client ledger',   code: '—', wf: 'contractors/ledger',    state: 'synced',  count: '—',last: '2h ago' },
    { type: 'Supplier ledger', code: '—', wf: 'contractors/ledger',    state: 'synced',  count: '—',last: '2h ago' },
  ];
  return (
    <div style={{ padding: '20px 28px 40px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"DM Serif Display", serif' }}>wFirma Sync</span>
        <span style={{ flex: 1 }}></span>
        <button style={accBtnGold}>↻ Sync all now</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 18 }}>
        <AccKpi label="Synced types"     value="9 / 10" hint="1 pending"                       accent="var(--badge-green-text)" />
        <AccKpi label="Last full sync"   value="2h ago" hint="auto every 6h · manual any time" accent="var(--accent)" />
        <AccKpi label="Failed events"    value="0"      hint="last 24h"                        accent="var(--text)" />
      </div>

      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 80px 1.5fr 80px 100px 120px 110px', padding: '10px 14px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          <div>Local type</div>
          <div>Code</div>
          <div>wFirma endpoint</div>
          <div style={{ textAlign: 'right' }}>Count</div>
          <div>State</div>
          <div>Last sync</div>
          <div></div>
        </div>
        {mappings.map(m => (
          <div key={m.type} style={{ display: 'grid', gridTemplateColumns: '1.3fr 80px 1.5fr 80px 100px 120px 110px', padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11.5, alignItems: 'center' }}>
            <div style={{ fontWeight: 600, color: 'var(--text)' }}>{m.type}</div>
            <div><span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2, background: 'var(--accent-subtle)', color: 'var(--accent)', border: '1px solid var(--accent-border)', fontWeight: 700, fontFamily: 'monospace' }}>{m.code}</span></div>
            <div style={{ fontFamily: 'monospace', fontSize: 10.5, color: 'var(--text-2)' }}>{m.wf}</div>
            <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{m.count}</div>
            <div><StateChip state={m.state} /></div>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{m.last}</div>
            <div><button style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 3, padding: '3px 8px', fontSize: 10, cursor: 'pointer' }}>Re-sync</button></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StateChip({ state }) {
  const conf = {
    draft:     { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
    sent:      { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
    accepted:  { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    open:      { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    paid:      { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    overdue:   { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
    issued:    { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    released:  { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    received:  { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    posted:    { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
    healthy:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    pending:   { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    synced:    { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
  };
  const c = conf[state] || conf.draft;
  return <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: c.bg, color: c.fg, border: `1px solid ${c.bd}`, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{state}</span>;
}

function WfChip({ state }) {
  const c = state === 'synced'
    ? { bg: 'var(--badge-green-bg)', fg: 'var(--badge-green-text)', bd: 'var(--badge-green-border)' }
    : { bg: 'var(--badge-amber-bg)', fg: 'var(--badge-amber-text)', bd: 'var(--badge-amber-border)' };
  return <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: c.bg, color: c.fg, border: `1px solid ${c.bd}`, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>wF · {state}</span>;
}

const accBtnOutline = { background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 4, padding: '5px 10px', fontSize: 11, fontWeight: 600, cursor: 'pointer' };
const accBtnGold    = { background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-text)', borderRadius: 4, padding: '5px 12px', fontSize: 11, fontWeight: 700, cursor: 'pointer' };

window.AccountingHub = AccountingHub;
