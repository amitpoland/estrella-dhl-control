// New page components for the restructured sidebar.
// DhlCustomsPage (merged) · AccountingPage · EmailQueuePage · AiBridgePage · ActionProposalsPage
// Plus a new ReportsPage that REPLACES the old one (financial / sales / purchase / shipping).

// ── Shared small UI helpers
function Tabs({ tabs, active, onChange, style }) {
  return (
    <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)', marginBottom: 16, overflowX: 'auto', flexShrink: 0, ...style }}>
      {tabs.map(t => (
        <button key={t.id} onClick={() => onChange(t.id)} style={{
          padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer',
          fontSize: 12, fontWeight: 600, color: active === t.id ? 'var(--text)' : 'var(--text-3)',
          borderBottom: active === t.id ? '2px solid var(--accent)' : '2px solid transparent',
          whiteSpace: 'nowrap', letterSpacing: '0.02em',
          marginBottom: -1,
        }}>
          {t.label}
          {t.count != null && (
            <span style={{ marginLeft: 6, padding: '1px 6px', background: active === t.id ? 'var(--accent)' : 'var(--bg-subtle)', color: active === t.id ? '#fff' : 'var(--text-3)', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

function StatTile({ label, value, sub, accent, onClick }) {
  return (
    <Card onClick={onClick} style={{ padding: '14px 16px', cursor: onClick ? 'pointer' : 'default' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', fontFamily: '"DM Serif Display", serif', lineHeight: 1.25, wordBreak: 'break-word' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6, lineHeight: 1.4 }}>{sub}</div>}
    </Card>
  );
}

function Pill({ children, tone = 'neutral', small }) {
  const tones = {
    neutral: { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-text)' },
    blue:    { bg: 'var(--badge-blue-bg)',    fg: 'var(--badge-blue-text)' },
    green:   { bg: 'var(--badge-green-bg)',   fg: 'var(--badge-green-text)' },
    amber:   { bg: 'var(--badge-amber-bg)',   fg: 'var(--badge-amber-text)' },
    red:     { bg: 'var(--badge-red-bg)',     fg: 'var(--badge-red-text)' },
    purple:  { bg: 'var(--badge-purple-bg)',  fg: 'var(--badge-purple-text)' },
    gold:    { bg: 'rgba(212,168,83,0.12)',   fg: 'var(--accent)' },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span style={{
      display: 'inline-block', padding: small ? '1px 6px' : '2px 8px',
      background: t.bg, color: t.fg, borderRadius: 4,
      fontSize: small ? 9 : 10, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
      whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// DHL / Customs (merged page) — clearance pipeline + DHL emails + SAD docs
// ════════════════════════════════════════════════════════════════════════════
function DhlCustomsPage({ onViewShipment }) {
  const [tab, setTab] = React.useState('clearance');
  const [openEmail, setOpenEmail] = React.useState(null);

  const emails = [
    { id: 'em-1', awb: 'DHL-7733991122', subject: 'RE: Customs clearance — pre-check required', from: 'clearance@dhl.com.pl', received: '2 min ago', dir: 'in', status: 'new', summary: 'CIF value EUR 1,840 below threshold. Standard procedure recommended.', flags: ['CIF<EUR 6,000', 'GOLD JEWELLERY'] },
    { id: 'em-2', awb: 'DHL-8825441199', subject: 'Reply: Documents attached for clearance', from: 'estrella@example.com', received: '14 min ago', dir: 'out', status: 'sent', summary: 'Polish description + DSK + invoice + AWB attached. 4 files, 2.3 MB.', flags: ['BUNDLE READY'] },
    { id: 'em-3', awb: 'DHL-9988776655', subject: 'Customs: SAD ZC429/2024/000847 issued', from: 'clearance@dhl.com.pl', received: '1 h ago', dir: 'in', status: 'parsed', summary: 'SAD attached. Duty A00 PLN 380. Verified against pre-check.', flags: ['SAD ATTACHED', 'A00 PLN 380'] },
    { id: 'em-4', awb: 'DHL-2244668800', subject: 'RE: Clearance request', from: 'clearance@dhl.com.pl', received: '3 h ago', dir: 'in', status: 'error', summary: 'Parser could not extract MRN. Manual review required.', flags: ['PARSE FAILED'] },
    { id: 'em-5', awb: 'DHL-5566778899', subject: 'Reply queued: Polish description + DSK', from: 'estrella@example.com', received: 'pending', dir: 'out', status: 'queued', summary: 'Awaiting operator approval. AI-generated DSK recommendation: PROBLEMATIC.', flags: ['NEEDS APPROVAL', 'DSK: PROBLEMATIC'] },
  ];

  const sadDocs = [
    { id: 'sad-1', mrn: 'ZC429/2024/000847', awb: 'DHL-9988776655', issued: '27 Apr 2024', a00: 'PLN 380', vat: 'PLN 1,420', status: 'Verified' },
    { id: 'sad-2', mrn: 'ZC429/2024/000845', awb: 'DHL-7733991122', issued: '26 Apr 2024', a00: 'PLN 0', vat: 'PLN 0', status: 'Pending parser' },
    { id: 'sad-3', mrn: 'ZC429/2024/000844', awb: 'DHL-8825441199', issued: '26 Apr 2024', a00: 'PLN 215', vat: 'PLN 962', status: 'Verified' },
    { id: 'sad-4', mrn: '—', awb: 'DHL-2244668800', issued: '—', a00: '—', vat: '—', status: 'Awaiting upload' },
  ];

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Stat row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Inbox new" value="3" sub="DHL replies awaiting parse" />
        <StatTile label="Reply queue" value="2" sub="Drafts pending operator approval" accent="var(--accent)" />
        <StatTile label="SAD pending" value="1" sub="Awaiting customs agent upload" />
        <StatTile label="Cleared today" value="5" sub="Verified · 100% match" accent="var(--badge-green-text)" />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'clearance', label: 'Clearance Pipeline' },
          { id: 'inbox',     label: 'DHL Email Queue', count: emails.filter(e => e.status === 'new' || e.status === 'queued').length },
          { id: 'sad',       label: 'SAD / ZC429 Documents', count: sadDocs.length },
          { id: 'shipments', label: 'All DHL Shipments' },
        ]}
      />

      {tab === 'clearance' && <DhlClearancePipeline onViewShipment={onViewShipment} />}
      {tab === 'inbox'     && <DhlEmailInbox emails={emails} onOpen={setOpenEmail} />}
      {tab === 'sad'       && <SadDocsTable docs={sadDocs} onView={onViewShipment} />}
      {tab === 'shipments' && <FilteredShipmentsTable filterFn={r => r.carrier === 'DHL'} onViewShipment={onViewShipment} />}

      {openEmail && <EmailDetailModal email={openEmail} onClose={() => setOpenEmail(null)} />}
    </div>
  );
}

function DhlClearancePipeline({ onViewShipment }) {
  // Reuse the existing DhlClearancePage's layout but trimmed.
  const [scanning, setScanning] = React.useState(false);
  const stages = [
    { num: 1, label: 'Inbox scan', count: 3, tone: 'blue' },
    { num: 2, label: 'Pre-check', count: 2, tone: 'amber' },
    { num: 3, label: 'Reply build', count: 2, tone: 'gold' },
    { num: 4, label: 'Awaiting SAD', count: 1, tone: 'purple' },
    { num: 5, label: 'SAD verified', count: 5, tone: 'green' },
  ];
  return (
    <div>
      <Card style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Pipeline overview</div>
            <div style={{ fontSize: 18, fontWeight: 600, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginTop: 2 }}>Today · 13 active items across 5 stages</div>
          </div>
          <Btn variant="gold" small onClick={() => setScanning(true)}>{scanning ? 'Scanning…' : '↻ Scan DHL Inbox'}</Btn>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
          {stages.map(s => (
            <div key={s.num} style={{ padding: '12px 14px', background: 'var(--bg-subtle)', borderRadius: 6, border: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--card)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: 'var(--text-2)' }}>{s.num}</div>
                <Pill tone={s.tone} small>{s.count} items</Pill>
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{s.label}</div>
            </div>
          ))}
        </div>
      </Card>
      <FilteredShipmentsTable filterFn={r => r.carrier === 'DHL' && r.overall !== 'Done'} onViewShipment={onViewShipment} />
    </div>
  );
}

function DhlEmailInbox({ emails, onOpen }) {
  const [filter, setFilter] = React.useState('all');
  const filters = [
    { id: 'all', label: 'All', count: emails.length },
    { id: 'in', label: 'Inbound', count: emails.filter(e => e.dir === 'in').length },
    { id: 'out', label: 'Outbound', count: emails.filter(e => e.dir === 'out').length },
    { id: 'queued', label: 'Pending Send', count: emails.filter(e => e.status === 'queued').length },
    { id: 'error', label: 'Errors', count: emails.filter(e => e.status === 'error').length },
  ];
  const visible = emails.filter(e => filter === 'all' ? true : filter === 'in' || filter === 'out' ? e.dir === filter : e.status === filter);

  return (
    <Card style={{ overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 6, borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
        {filters.map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)} style={{
            padding: '4px 10px', background: filter === f.id ? 'var(--card)' : 'transparent',
            border: '1px solid ' + (filter === f.id ? 'var(--border)' : 'transparent'),
            borderRadius: 4, fontSize: 11, fontWeight: 600,
            color: filter === f.id ? 'var(--text)' : 'var(--text-3)', cursor: 'pointer',
          }}>{f.label} <span style={{ opacity: 0.6, marginLeft: 4 }}>{f.count}</span></button>
        ))}
      </div>
      <div>
        {visible.map(e => (
          <div key={e.id} onClick={() => onOpen(e)} style={{
            padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer',
            display: 'flex', alignItems: 'flex-start', gap: 12,
          }} onMouseEnter={ev => ev.currentTarget.style.background = 'var(--row-hover)'}
             onMouseLeave={ev => ev.currentTarget.style.background = 'transparent'}>
            <div style={{ width: 24, height: 24, borderRadius: '50%', background: e.dir === 'in' ? 'var(--badge-blue-bg)' : 'var(--bg-subtle)', color: e.dir === 'in' ? 'var(--badge-blue-text)' : 'var(--text-3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0, marginTop: 2 }}>{e.dir === 'in' ? '↓' : '↑'}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--badge-blue-text)', fontWeight: 600 }}>{e.awb}</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>·</span>
                <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{e.from}</span>
                {e.status === 'new'    && <Pill tone="blue"   small>NEW</Pill>}
                {e.status === 'queued' && <Pill tone="gold"   small>PENDING SEND</Pill>}
                {e.status === 'sent'   && <Pill tone="green"  small>SENT</Pill>}
                {e.status === 'parsed' && <Pill tone="purple" small>PARSED</Pill>}
                {e.status === 'error'  && <Pill tone="red"    small>ERROR</Pill>}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{e.subject}</div>
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>{e.summary}</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {e.flags.map(f => <Pill key={f} tone="neutral" small>{f}</Pill>)}
              </div>
            </div>
            <div style={{ flexShrink: 0, fontSize: 11, color: 'var(--text-3)' }}>{e.received}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function EmailDetailModal({ email, onClose }) {
  return (
    <Modal title={`Email · ${email.awb}`} onClose={onClose} wide>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 20 }}>
        <div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Subject</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{email.subject}</div>
          </div>
          <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 11 }}>
            <div><span style={{ color: 'var(--text-3)' }}>From:</span> <span style={{ color: 'var(--text)' }}>{email.from}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Received:</span> <span style={{ color: 'var(--text)' }}>{email.received}</span></div>
          </div>
          <div style={{ padding: 14, background: 'var(--bg-subtle)', borderRadius: 6, border: '1px solid var(--border)', fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 12 }}>
            <div style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
{`Hello,

${email.summary}

Please find attached:
  • Polish description (auto-generated)
  • DSK recommendation
  • Commercial invoice
  • AWB / Tracking sheet

Best regards,
Estrella Jewels Customs Bridge`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {email.status === 'queued' && <Btn variant="gold" small>📤 Send Now</Btn>}
            {email.status === 'error'  && <Btn variant="gold" small>↻ Retry Parse</Btn>}
            <Btn variant="outline" small>View Shipment</Btn>
            <Btn variant="outline" small>Edit Reply</Btn>
            <Btn variant="outline" small>↓ Download .eml</Btn>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>AI Bridge result</div>
          <Card style={{ padding: 12, marginBottom: 12 }}>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 4 }}>Classification</div>
            <Pill tone={email.flags.some(f => f.includes('PROBLEMATIC')) ? 'amber' : 'green'} small>
              {email.flags.find(f => f.includes('DSK')) || 'STANDARD'}
            </Pill>
          </Card>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Detected flags</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {email.flags.map(f => <Pill key={f} tone="neutral" small>{f}</Pill>)}
          </div>
        </div>
      </div>
    </Modal>
  );
}

function SadDocsTable({ docs, onView }) {
  return (
    <Card style={{ overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ background: 'var(--bg-subtle)' }}>
            {['MRN', 'AWB', 'Issued', 'A00 (Duty)', 'VAT', 'Status', ''].map(h => (
              <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {docs.map(d => (
            <tr key={d.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text)', fontWeight: 600 }}>{d.mrn}</td>
              <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--badge-blue-text)' }}>{d.awb}</td>
              <td style={{ padding: '10px 12px', color: 'var(--text-2)' }}>{d.issued}</td>
              <td style={{ padding: '10px 12px', color: 'var(--accent)', fontWeight: 700, textAlign: 'right' }}>{d.a00}</td>
              <td style={{ padding: '10px 12px', color: 'var(--text)', textAlign: 'right' }}>{d.vat}</td>
              <td style={{ padding: '10px 12px' }}>
                <Pill tone={d.status === 'Verified' ? 'green' : d.status === 'Pending parser' ? 'amber' : 'neutral'} small>{d.status}</Pill>
              </td>
              <td style={{ padding: '10px 12px' }}><Btn small variant="outline">View</Btn></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Accounting (merger of PZ + Sales + wFirma + Master Data + Audit)
// ════════════════════════════════════════════════════════════════════════════
function AccountingPage({ onViewShipment }) {
  const [tab, setTab] = React.useState('purchase');
  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Purchase ledger" value="142" sub="PZ documents this month" />
        <StatTile label="Sales / proforma" value="38" sub="Active · 6 awaiting export" accent="var(--accent)" />
        <StatTile label="wFirma sync" value="OK" sub="Last sync 4 min ago · 0 errors" accent="var(--badge-green-text)" />
        <StatTile label="Audit events" value="1,284" sub="Last 30 days" />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'purchase',  label: 'Purchase Ledger (PZ)' },
          { id: 'sales',     label: 'Sales / Proforma' },
          { id: 'ledgers',   label: 'Ledgers / Statements' },
          { id: 'wfirma',    label: 'wFirma Sync' },
          { id: 'master',    label: 'Master Data' },
          { id: 'audit',     label: 'Audit Trail' },
        ]}
      />

      {tab === 'purchase' && <PzAccountingPage onViewShipment={onViewShipment} />}
      {tab === 'sales'    && <SalesProformaPage onGoToWfirma={() => setTab('wfirma')} />}
      {tab === 'ledgers'  && (window.LedgersPage ? <window.LedgersPage /> : null)}
      {tab === 'wfirma'   && <WfirmaExportPage onViewShipment={onViewShipment} />}
      {tab === 'master'   && <MasterDataView />}
      {tab === 'audit'    && <AuditTrailView />}
    </div>
  );
}

function MasterDataView() {
  const [section, setSection] = React.useState('clients');
  const sections = [
    { id: 'clients',   label: 'Clients / Importers', count: 12 },
    { id: 'suppliers', label: 'Suppliers / Exporters', count: 47 },
    { id: 'hs',        label: 'HS Codes / Tariff', count: 184 },
    { id: 'fx',        label: 'Currency / FX Rates' },
    { id: 'vat',       label: 'VAT Rates' },
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16 }}>
      <Card style={{ padding: 6 }}>
        {sections.map(s => (
          <button key={s.id} onClick={() => setSection(s.id)} style={{
            width: '100%', padding: '10px 12px', textAlign: 'left',
            background: section === s.id ? 'var(--bg-subtle)' : 'transparent',
            border: 'none', borderRadius: 4, cursor: 'pointer',
            fontSize: 12, fontWeight: section === s.id ? 600 : 500,
            color: section === s.id ? 'var(--text)' : 'var(--text-2)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            {s.label}
            {s.count != null && <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{s.count}</span>}
          </button>
        ))}
      </Card>
      <Card style={{ padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{sections.find(s => s.id === section).label}</div>
          <Btn small variant="outline">+ Add</Btn>
        </div>
        {section === 'clients' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Name', 'Country', 'NIP / VAT ID', 'Default Currency', 'Last activity', ''].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[
                ['Estrella Jewels Sp. z o.o.', 'PL', 'PL5252312345', 'PLN', '2 min ago'],
                ['Atelier Bonacchi SRL', 'IT', 'IT04520119872', 'EUR', '3 days ago'],
                ['Geneva Imports SA', 'CH', 'CHE-115.823.554', 'CHF', '1 week ago'],
              ].map(r => (
                <tr key={r[0]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400 }}>{c}</td>)}
                  <td><Btn small variant="outline">Edit</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section === 'suppliers' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Supplier', 'Country', 'Default Carrier', 'HS Codes', 'Active'].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[
                ['Bonacchi Atelier', 'IT', 'DHL', '7113.19, 7117.19', '✓'],
                ['Maison de Vicenza', 'IT', 'FedEx', '7113.11, 7113.19', '✓'],
                ['Antwerp Stones', 'BE', 'DHL', '7102.39, 7103.91', '✓'],
                ['Geneva Goldworks', 'CH', 'DHL', '7113.19', '✓'],
              ].map(r => (
                <tr key={r[0]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400 }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section === 'hs' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['HS Code', 'Description', 'Duty %', 'VAT %', 'Locked'].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[
                ['7113.19.00', 'Articles of jewellery, precious metal (excl. silver)', '2.5%', '23%', '🔒'],
                ['7113.11.00', 'Articles of jewellery of silver', '2.5%', '23%', '🔒'],
                ['7102.39.00', 'Diamonds, non-industrial, worked', '0%', '23%', '🔒'],
                ['7103.91.00', 'Rubies, sapphires, emeralds — worked', '0%', '23%', '🔒'],
                ['7117.19.00', 'Imitation jewellery, base metal', '4%', '23%', '🔒'],
              ].map(r => (
                <tr key={r[0]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, fontFamily: i === 0 ? 'monospace' : 'inherit', color: i === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: i === 0 ? 600 : 400 }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section === 'fx' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
              {[['EUR', '4.3128', '+0.012'], ['USD', '4.0214', '-0.008'], ['CHF', '4.4502', '+0.021'], ['GBP', '5.0388', '+0.005']].map(r => (
                <div key={r[0]} style={{ padding: 12, background: 'var(--bg-subtle)', borderRadius: 6, border: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em' }}>{r[0]} → PLN</div>
                  <div style={{ fontSize: 20, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)' }}>{r[1]}</div>
                  <div style={{ fontSize: 10, color: r[2].startsWith('+') ? 'var(--badge-green-text)' : 'var(--badge-red-text)' }}>{r[2]} vs yesterday</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>NBP table A · 27 April 2024 · Last sync 11 min ago. SAD historical rates kept per shipment.</div>
          </div>
        )}
        {section === 'vat' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Rate', 'Code', 'Applies to', 'Locked'].map(h => <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
            <tbody>
              {[['23%', 'VAT-23', 'Standard rate (jewellery, accessories)', '🔒'], ['8%', 'VAT-8', 'Reduced rate', '🔒'], ['0%', 'VAT-0', 'Exports, intra-EU supplies', '🔒'], ['NP', 'VAT-NP', 'Not subject to VAT', '🔒']].map(r => (
                <tr key={r[1]} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  {r.map((c, i) => <td key={i} style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-2)' }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function AuditTrailView() {
  const events = [
    { ts: '14:42:11', user: 'system', action: 'AI Bridge classified DHL email', target: 'em-872 · DHL-7733991122', tone: 'blue' },
    { ts: '14:38:02', user: 'anna.k',  action: 'Approved reply package', target: 'DHL-8825441199', tone: 'green' },
    { ts: '14:21:55', user: 'anna.k',  action: 'Edited HS code', target: '7113.19 → 7117.19 · DHL-2244668800', tone: 'amber' },
    { ts: '14:08:03', user: 'system', action: 'Generated PZ document', target: 'PZ/2024/000891 · DHL-9988776655', tone: 'purple' },
    { ts: '13:54:17', user: 'tomek.w', action: 'Uploaded SAD', target: 'ZC429/2024/000847 · DHL-9988776655', tone: 'green' },
    { ts: '13:32:00', user: 'system', action: 'wFirma export succeeded', target: 'PZ/2024/000890 → wFirma id #38221', tone: 'green' },
    { ts: '12:11:48', user: 'system', action: 'Action proposal queued', target: 'AP-014 · Reclassify supplier "Bonacchi"', tone: 'gold' },
    { ts: '11:02:33', user: 'anna.k',  action: 'Closed temporary import', target: 'ATA-2024-0118 · Vicenza Show', tone: 'green' },
  ];
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Input placeholder="Search action / target…" />
        <Select><option>All users</option><option>anna.k</option><option>tomek.w</option><option>system</option></Select>
        <Select><option>All actions</option><option>Approvals</option><option>Edits</option><option>Exports</option></Select>
        <Btn variant="outline" small>↓ Export</Btn>
      </div>
      <Card style={{ overflow: 'hidden' }}>
        {events.map((e, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '90px 110px 1fr 1.5fr', gap: 12, padding: '10px 16px', borderBottom: i < events.length - 1 ? '1px solid var(--border-subtle)' : 'none', alignItems: 'center', fontSize: 12 }}>
            <div style={{ fontFamily: 'monospace', color: 'var(--text-3)' }}>{e.ts}</div>
            <div style={{ color: 'var(--text)', fontWeight: 600 }}>{e.user}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Pill tone={e.tone} small>{e.action}</Pill>
            </div>
            <div style={{ color: 'var(--text-2)', fontFamily: 'monospace', fontSize: 11 }}>{e.target}</div>
          </div>
        ))}
      </Card>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Email Queue (system-wide email queue, beyond just DHL)
// ════════════════════════════════════════════════════════════════════════════
function EmailQueuePage({ onViewShipment }) {
  const [filter, setFilter] = React.useState('all');
  const queue = [
    { id: 'eq-1', dir: 'in',  source: 'DHL',     subject: 'RE: Customs clearance — pre-check', awb: 'DHL-7733991122', received: '2 min ago',  status: 'parsed', size: '12 KB' },
    { id: 'eq-2', dir: 'out', source: 'DHL',     subject: 'Reply: Documents attached', awb: 'DHL-8825441199', received: '14 min ago', status: 'sent', size: '2.3 MB' },
    { id: 'eq-3', dir: 'out', source: 'DHL',     subject: 'Reply queued: DSK + invoice', awb: 'DHL-5566778899', received: 'pending',    status: 'queued', size: '1.1 MB' },
    { id: 'eq-4', dir: 'in',  source: 'DHL',     subject: 'Customs: SAD ZC429 issued',   awb: 'DHL-9988776655', received: '1 h ago',    status: 'parsed', size: '480 KB' },
    { id: 'eq-5', dir: 'in',  source: 'DHL',     subject: 'RE: Clearance request',       awb: 'DHL-2244668800', received: '3 h ago',    status: 'error',  size: '8 KB',  error: 'MRN extraction failed' },
    { id: 'eq-6', dir: 'out', source: 'wFirma',  subject: 'Export PZ/2024/000891',       awb: 'DHL-9988776655', received: '4 h ago',    status: 'sent',   size: '14 KB' },
    { id: 'eq-7', dir: 'out', source: 'system',  subject: 'Daily summary — 27 Apr 2024', awb: '—',              received: 'Yesterday',  status: 'sent',   size: '32 KB' },
    { id: 'eq-8', dir: 'out', source: 'wFirma',  subject: 'Export PZ/2024/000885',       awb: 'DHL-1199227733', received: '5 h ago',    status: 'error',  size: '14 KB', error: 'wFirma API timeout (gateway)' },
  ];

  const filters = [
    { id: 'all',     label: 'All',          count: queue.length },
    { id: 'in',      label: 'Inbound',      count: queue.filter(q => q.dir === 'in').length },
    { id: 'out',     label: 'Outbound',     count: queue.filter(q => q.dir === 'out').length },
    { id: 'queued',  label: 'Pending Send', count: queue.filter(q => q.status === 'queued').length },
    { id: 'error',   label: 'Errors',       count: queue.filter(q => q.status === 'error').length },
    { id: 'wfirma',  label: 'wFirma',       count: queue.filter(q => q.source === 'wFirma').length },
    { id: 'dhl',     label: 'DHL',          count: queue.filter(q => q.source === 'DHL').length },
  ];

  const visible = queue.filter(q => {
    if (filter === 'all') return true;
    if (filter === 'in' || filter === 'out') return q.dir === filter;
    if (filter === 'wfirma') return q.source === 'wFirma';
    if (filter === 'dhl') return q.source === 'DHL';
    return q.status === filter;
  });

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Total today" value={queue.length} sub="In + out" />
        <StatTile label="Pending send" value={queue.filter(q => q.status === 'queued').length} sub="Awaiting approval" accent="var(--accent)" />
        <StatTile label="Errors" value={queue.filter(q => q.status === 'error').length} sub="Need operator review" accent="var(--badge-red-text)" />
        <StatTile label="Avg parse time" value="3.2s" sub="DHL inbound · last 24h" accent="var(--badge-green-text)" />
      </div>

      <Card style={{ overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 6, borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', flexWrap: 'wrap' }}>
          {filters.map(f => (
            <button key={f.id} onClick={() => setFilter(f.id)} style={{
              padding: '4px 10px', background: filter === f.id ? 'var(--card)' : 'transparent',
              border: '1px solid ' + (filter === f.id ? 'var(--border)' : 'transparent'),
              borderRadius: 4, fontSize: 11, fontWeight: 600,
              color: filter === f.id ? 'var(--text)' : 'var(--text-3)', cursor: 'pointer',
            }}>{f.label} <span style={{ opacity: 0.6, marginLeft: 4 }}>{f.count}</span></button>
          ))}
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['', 'Source', 'Subject / Linked AWB', 'Received', 'Size', 'Status', 'Actions'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map(q => (
              <tr key={q.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{ display: 'inline-flex', width: 22, height: 22, borderRadius: '50%', background: q.dir === 'in' ? 'var(--badge-blue-bg)' : 'var(--bg-subtle)', color: q.dir === 'in' ? 'var(--badge-blue-text)' : 'var(--text-3)', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{q.dir === 'in' ? '↓' : '↑'}</span>
                </td>
                <td style={{ padding: '10px 12px' }}><Pill tone={q.source === 'DHL' ? 'blue' : q.source === 'wFirma' ? 'purple' : 'neutral'} small>{q.source}</Pill></td>
                <td style={{ padding: '10px 12px' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{q.subject}</div>
                  {q.awb !== '—' && <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--badge-blue-text)', marginTop: 2 }}>{q.awb}</div>}
                  {q.error && <div style={{ fontSize: 11, color: 'var(--badge-red-text)', marginTop: 4 }}>⚠ {q.error}</div>}
                </td>
                <td style={{ padding: '10px 12px', color: 'var(--text-3)', fontSize: 11, whiteSpace: 'nowrap' }}>{q.received}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text-3)', fontSize: 11, fontFamily: 'monospace' }}>{q.size}</td>
                <td style={{ padding: '10px 12px' }}>
                  {q.status === 'parsed' && <Pill tone="green"  small>PARSED</Pill>}
                  {q.status === 'sent'   && <Pill tone="green"  small>SENT</Pill>}
                  {q.status === 'queued' && <Pill tone="gold"   small>QUEUED</Pill>}
                  {q.status === 'error'  && <Pill tone="red"    small>ERROR</Pill>}
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {q.status === 'queued' && <Btn small variant="gold">Send</Btn>}
                    {q.status === 'error'  && <Btn small variant="gold">Retry</Btn>}
                    <Btn small variant="outline">View</Btn>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// AI Bridge — task queue, results, errors, capabilities, prompt templates
// ════════════════════════════════════════════════════════════════════════════
function AiBridgePage() {
  const [tab, setTab] = React.useState('tasks');

  const tasks = [
    { id: 'T-8842', kind: 'classify_email',     input: 'em-872 · DHL-7733991122', model: 'haiku-4-5',   started: '14:42:09', dur: '1.4s', status: 'success', confidence: 0.94 },
    { id: 'T-8841', kind: 'generate_dsk',       input: 'DHL-2244668800',          model: 'sonnet-4-5',  started: '14:38:21', dur: '3.7s', status: 'success', confidence: 0.88 },
    { id: 'T-8840', kind: 'translate_pl',       input: 'inv-2294 · 12 lines',     model: 'haiku-4-5',   started: '14:36:05', dur: '2.1s', status: 'success', confidence: 0.97 },
    { id: 'T-8839', kind: 'parse_sad',          input: 'sad-pdf-447.pdf',         model: 'sonnet-4-5',  started: '14:21:33', dur: '5.8s', status: 'success', confidence: 0.91 },
    { id: 'T-8838', kind: 'classify_email',     input: 'em-869 · DHL-2244668800', model: 'haiku-4-5',   started: '14:08:14', dur: '0.9s', status: 'error',   error: 'MRN regex match failed; needs human review' },
    { id: 'T-8837', kind: 'reconcile_pz',       input: 'PZ/2024/000891',          model: 'sonnet-4-5',  started: '13:55:02', dur: '4.2s', status: 'success', confidence: 0.96 },
    { id: 'T-8836', kind: 'propose_action',     input: 'batch:DHL-april',         model: 'sonnet-4-5',  started: '13:30:00', dur: '11.4s', status: 'success', confidence: 0.82 },
    { id: 'T-8835', kind: 'classify_invoice',   input: 'inv-2293.pdf',            model: 'haiku-4-5',   started: '12:44:28', dur: '1.7s', status: 'pending', confidence: null },
  ];

  const capabilities = [
    { id: 'classify_email',   label: 'Classify DHL email',         desc: 'Detects pre-check / reply / SAD / error categories from inbox messages', model: 'haiku-4-5', enabled: true },
    { id: 'generate_dsk',     label: 'Generate DSK recommendation', desc: 'Decides STANDARD vs PROBLEMATIC based on CIF / origin / category', model: 'sonnet-4-5', enabled: true },
    { id: 'translate_pl',     label: 'Translate to Polish',         desc: 'Converts invoice descriptions to Polish customs descriptions', model: 'haiku-4-5', enabled: true },
    { id: 'parse_sad',        label: 'Parse SAD / ZC429',           desc: 'Extracts MRN, A00 duty, VAT, line items from PDF', model: 'sonnet-4-5', enabled: true },
    { id: 'reconcile_pz',     label: 'Reconcile PZ',                desc: 'Matches PZ values to invoice + SAD; flags discrepancies', model: 'sonnet-4-5', enabled: true },
    { id: 'classify_invoice', label: 'Classify invoice items',      desc: 'Maps each line to HS code based on description + supplier history', model: 'haiku-4-5', enabled: true },
    { id: 'propose_action',   label: 'Cross-batch action proposals', desc: 'Path-A: proposes operator actions across batches', model: 'sonnet-4-5', enabled: true },
    { id: 'verify_carnet',    label: 'Verify ATA Carnet',           desc: 'Checks carnet completeness for temp import / export', model: 'sonnet-4-5', enabled: false },
  ];

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Tasks today" value="284" sub="✓ 271 success · ✗ 8 errors · ⏱ 5 pending" />
        <StatTile label="Avg latency" value="2.4s" sub="Last 24h · p95 6.8s" accent="var(--badge-green-text)" />
        <StatTile label="Token spend" value="$4.82" sub="Today · capped at $20/day" accent="var(--accent)" />
        <StatTile label="Capabilities" value={capabilities.filter(c => c.enabled).length + '/' + capabilities.length} sub="Active capabilities" />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'tasks',         label: 'Task Queue', count: tasks.filter(t => t.status === 'pending').length },
          { id: 'results',       label: 'Recent Results' },
          { id: 'errors',        label: 'Errors', count: tasks.filter(t => t.status === 'error').length },
          { id: 'capabilities',  label: 'Capabilities' },
          { id: 'templates',     label: 'Prompt Templates' },
        ]}
      />

      {(tab === 'tasks' || tab === 'results' || tab === 'errors') && (
        <Card style={{ overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['Task ID', 'Capability', 'Input', 'Model', 'Started', 'Duration', 'Confidence', 'Status', ''].map(h => (
                  <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tasks.filter(t => tab === 'tasks' ? true : tab === 'results' ? t.status === 'success' : t.status === 'error').map(t => (
                <tr key={t.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{t.id}</td>
                  <td style={{ padding: '10px 12px' }}><Pill tone="purple" small>{t.kind}</Pill></td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)' }}>{t.input}</td>
                  <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--text-3)' }}>{t.model}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-3)' }}>{t.started}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-3)' }}>{t.dur}</td>
                  <td style={{ padding: '10px 12px', fontSize: 11, color: t.confidence == null ? 'var(--text-3)' : t.confidence > 0.9 ? 'var(--badge-green-text)' : 'var(--accent)', fontWeight: 600 }}>{t.confidence == null ? '—' : (t.confidence * 100).toFixed(0) + '%'}</td>
                  <td style={{ padding: '10px 12px' }}>
                    {t.status === 'success' && <Pill tone="green" small>✓ SUCCESS</Pill>}
                    {t.status === 'error'   && <Pill tone="red"   small>✗ ERROR</Pill>}
                    {t.status === 'pending' && <Pill tone="amber" small>⏱ PENDING</Pill>}
                    {t.error && <div style={{ fontSize: 10, color: 'var(--badge-red-text)', marginTop: 4 }}>{t.error}</div>}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {t.status === 'error' && <Btn small variant="gold">Retry</Btn>}
                      <Btn small variant="outline">Inspect</Btn>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'capabilities' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
          {capabilities.map(c => (
            <Card key={c.id} style={{ padding: 16 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{c.label}</div>
                    <Pill tone={c.enabled ? 'green' : 'neutral'} small>{c.enabled ? 'ENABLED' : 'DISABLED'}</Pill>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 8, lineHeight: 1.5 }}>{c.desc}</div>
                  <div style={{ display: 'flex', gap: 8, fontSize: 10, color: 'var(--text-3)' }}>
                    <span><span style={{ fontWeight: 700 }}>capability:</span> <span style={{ fontFamily: 'monospace', color: 'var(--text-2)' }}>{c.id}</span></span>
                    <span>·</span>
                    <span><span style={{ fontWeight: 700 }}>model:</span> {c.model}</span>
                  </div>
                </div>
                <Btn small variant="outline">Edit</Btn>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'templates' && (
        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 12 }}>
          <Card style={{ padding: 6 }}>
            {['classify_email.v3', 'generate_dsk.v2', 'translate_pl.v4', 'parse_sad.v2', 'reconcile_pz.v1', 'propose_action.v1'].map((id, i) => (
              <button key={id} style={{
                width: '100%', padding: '10px 12px', textAlign: 'left',
                background: i === 0 ? 'var(--bg-subtle)' : 'transparent',
                border: 'none', borderRadius: 4, cursor: 'pointer',
                fontSize: 11, fontFamily: 'monospace', color: i === 0 ? 'var(--text)' : 'var(--text-2)',
                fontWeight: i === 0 ? 600 : 500,
                display: 'flex', justifyContent: 'space-between',
              }}>
                {id}
                {i === 0 && <Pill tone="gold" small>Active</Pill>}
              </button>
            ))}
          </Card>
          <Card style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', fontFamily: 'monospace' }}>classify_email.v3</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Last edited 3 days ago by anna.k · 94% avg confidence over 1,284 calls</div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <Btn small variant="outline">Diff vs v2</Btn>
                <Btn small variant="outline">Test</Btn>
                <Btn small variant="gold">Save & Activate</Btn>
              </div>
            </div>
            <div style={{ background: '#1a1a1a', color: '#e8e8e8', padding: 16, borderRadius: 6, fontFamily: 'monospace', fontSize: 11, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
{`SYSTEM: You are a Polish customs operations assistant.
Classify the inbound DHL email into one of:
  - PRE_CHECK_REQUEST   (DHL asks Estrella for pre-clearance docs)
  - SAD_ATTACHED        (DHL forwards an issued SAD/ZC429)
  - QUERY               (DHL asks a clarifying question)
  - ERROR               (parser failure or unrecognised format)

INPUT:
  - email body (raw text)
  - email subject
  - any attachments metadata

OUTPUT (strict JSON):
{
  "category": "PRE_CHECK_REQUEST | SAD_ATTACHED | QUERY | ERROR",
  "awb": "string | null",
  "confidence": "0.0-1.0",
  "flags": ["string", ...],
  "next_action": "string"
}

RULES:
  · If CIF < EUR 6,000 and origin in [IT, CH, FR], add flag "CIF<EUR 6,000"
  · For gold/silver jewellery, always include HS hint flag
  · Return ERROR only if subject + body do not contain an AWB`}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Action Proposals — cross-batch AI suggestions awaiting operator approval
// ════════════════════════════════════════════════════════════════════════════
function ActionProposalsPage() {
  const proposals = [
    {
      id: 'AP-014', priority: 'high', impact: 'PLN 12,400 / month',
      title: 'Reclassify supplier "Bonacchi Atelier" default carrier from DHL to FedEx',
      reason: 'Last 18 shipments via FedEx cleared 2.3 days faster on average; DHL pre-check failures up 22% this month.',
      affected: 18, affectedKind: 'shipments', proposedAt: '2 h ago', evidence: ['18 shipments analysed', 'Avg DHL clearance: 4.1d', 'Avg FedEx clearance: 1.8d'],
    },
    {
      id: 'AP-013', priority: 'high', impact: 'Risk reduction',
      title: 'Add "PROBLEMATIC" DSK flag to all gold jewellery > EUR 8,000 from Switzerland',
      reason: 'Swiss origin + high CIF triggers manual customs review in 67% of cases. Pre-flagging reduces clearance time.',
      affected: 7, affectedKind: 'pending shipments', proposedAt: '4 h ago', evidence: ['Last 90 days: 21/31 manually reviewed', 'Avg delay when manual: +3.2d'],
    },
    {
      id: 'AP-012', priority: 'medium', impact: 'PLN 880 saved',
      title: 'Update HS code 7117.19.00 → 7113.19.00 for "Bonacchi rose-gold"',
      reason: 'AI classifier confidence 0.91 on reclassification. Duty drops 4% → 2.5% for these line items.',
      affected: 14, affectedKind: 'line items in PZ/2024/000891', proposedAt: '6 h ago', evidence: ['SAD ZC429/2024/000847 line 3', 'Bonacchi catalog 2024 confirms'],
    },
    {
      id: 'AP-011', priority: 'medium', impact: 'Process',
      title: 'Auto-approve DHL replies when DSK = STANDARD and CIF < EUR 1,500',
      reason: 'Last 60 days: 0 errors out of 142 such replies. Manual approval averages 14 min delay per shipment.',
      affected: 142, affectedKind: 'historical shipments', proposedAt: '1 day ago', evidence: ['142/142 succeeded', 'Avg manual delay: 14m'],
    },
    {
      id: 'AP-010', priority: 'low', impact: 'Cleanup',
      title: 'Archive 38 closed temp-import carnets older than 6 months',
      reason: 'All marked Re-exported, all closure documents present. Free up the active list for operators.',
      affected: 38, affectedKind: 'ATA carnets', proposedAt: '2 days ago', evidence: ['38/38 have closure docs', 'Last activity > 180d'],
    },
  ];

  const [tab, setTab] = React.useState('pending');

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ padding: 14, background: 'rgba(212,168,83,0.08)', border: '1px solid rgba(212,168,83,0.3)', borderRadius: 6, marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'var(--accent)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, flexShrink: 0 }}>◉</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 2 }}>Path-A · Cross-batch action proposals</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5 }}>The AI Bridge analyses the full ledger and proposes actions that improve clearance speed, reduce duty, or reduce risk. Every proposal is operator-approved before it takes effect. Approvals become rules; rejections train the model.</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Pending review" value={proposals.length} sub="High: 2 · Med: 2 · Low: 1" accent="var(--accent)" />
        <StatTile label="Approved (30d)" value="23" sub="14 became active rules" accent="var(--badge-green-text)" />
        <StatTile label="Rejected (30d)" value="7" sub="Used for model training" />
        <StatTile label="Estimated savings" value="PLN 18,420" sub="From applied proposals · 30d" accent="var(--badge-green-text)" />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'pending',  label: 'Pending Review', count: proposals.length },
          { id: 'approved', label: 'Approved' },
          { id: 'rejected', label: 'Rejected' },
          { id: 'rules',    label: 'Active Rules' },
        ]}
      />

      {tab === 'pending' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {proposals.map(p => (
            <Card key={p.id} style={{ padding: 18 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                <div style={{ flexShrink: 0 }}>
                  <Pill tone={p.priority === 'high' ? 'red' : p.priority === 'medium' ? 'amber' : 'neutral'} small>{p.priority.toUpperCase()}</Pill>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-3)', fontWeight: 600 }}>{p.id}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>·</span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Proposed {p.proposedAt}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>·</span>
                    <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>Impact: {p.impact}</span>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', fontFamily: '"DM Serif Display", serif', marginBottom: 6 }}>{p.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.55, marginBottom: 10 }}>{p.reason}</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                    <Pill tone="blue" small>Affects {p.affected} {p.affectedKind}</Pill>
                    {p.evidence.map(e => <Pill key={e} tone="neutral" small>{e}</Pill>)}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Btn variant="gold" small>✓ Approve & Apply</Btn>
                    <Btn variant="outline" small>Approve as Rule</Btn>
                    <Btn variant="outline" small>Edit</Btn>
                    <Btn variant="outline" small>✗ Reject</Btn>
                    <Btn variant="outline" small>Snooze 7d</Btn>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab !== 'pending' && (
        <Card style={{ padding: 48, textAlign: 'center', color: 'var(--text-3)' }}>
          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.4 }}>◉</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{tab === 'approved' ? '23 approved proposals · 14 active rules' : tab === 'rejected' ? '7 rejected proposals · used for training' : '14 active rules from approved proposals'}</div>
          <div style={{ fontSize: 11, marginTop: 4 }}>Connect API to load full history.</div>
        </Card>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Reports — financial, sales, purchase, shipping (date-filtered)
// ════════════════════════════════════════════════════════════════════════════
function ReportsPage() {
  const [period, setPeriod] = React.useState('mtd');
  const [tab, setTab] = React.useState('financial');

  const periods = [
    { id: 'today', label: 'Today' },
    { id: 'wtd',   label: 'Week to date' },
    { id: 'mtd',   label: 'Month to date' },
    { id: 'qtd',   label: 'Quarter to date' },
    { id: 'ytd',   label: 'Year to date' },
    { id: 'last30', label: 'Last 30 days' },
    { id: 'custom', label: 'Custom…' },
  ];

  return (
    <div style={{ padding: '20px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Date range bar */}
      <Card style={{ padding: 14, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Period</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {periods.map(p => (
            <button key={p.id} onClick={() => setPeriod(p.id)} style={{
              padding: '6px 12px', background: period === p.id ? 'var(--text)' : 'transparent',
              border: '1px solid ' + (period === p.id ? 'var(--text)' : 'var(--border)'),
              borderRadius: 4, fontSize: 11, fontWeight: 600,
              color: period === p.id ? 'var(--card)' : 'var(--text-2)', cursor: 'pointer',
            }}>{p.label}</button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>1 Apr → 27 Apr 2024 · 27 days</div>
        <Btn small variant="outline">↓ Export PDF</Btn>
        <Btn small variant="outline">↓ Export CSV</Btn>
        <Btn small variant="outline">📅 Schedule</Btn>
      </Card>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'financial',  label: 'Financial' },
          { id: 'sales',      label: 'Sales' },
          { id: 'purchase',   label: 'Purchase' },
          { id: 'shipping',   label: 'Shipping' },
          { id: 'duty',       label: 'Duty & VAT' },
        ]}
      />

      {tab === 'financial' && <ReportsFinancial />}
      {tab === 'sales'     && <ReportsSales />}
      {tab === 'purchase'  && <ReportsPurchase />}
      {tab === 'shipping'  && <ReportsShipping />}
      {tab === 'duty'      && <ReportsDuty />}
    </div>
  );
}

function MiniBarChart({ data, accent, height = 80 }) {
  const max = Math.max(...data.map(d => d.v));
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height, padding: '4px 0' }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <div style={{ width: '100%', height: `${(d.v / max) * (height - 20)}px`, background: accent || 'var(--accent)', borderRadius: 2, opacity: 0.8 }} />
          <div style={{ fontSize: 9, color: 'var(--text-3)', fontWeight: 600 }}>{d.label}</div>
        </div>
      ))}
    </div>
  );
}

function ReportsFinancial() {
  const days = ['1', '5', '10', '15', '20', '25', '27'].map((d, i) => ({ label: d, v: [42000, 58000, 72000, 89000, 124000, 156000, 184500][i] }));
  const margin = ['1', '5', '10', '15', '20', '25', '27'].map((d, i) => ({ label: d, v: [18, 22, 19, 24, 27, 25, 28][i] }));
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Revenue" value="PLN 184,500" sub="+18% vs last month" accent="var(--badge-green-text)" />
        <StatTile label="Cost of goods" value="PLN 132,800" sub="incl. duty & VAT non-recoverable" />
        <StatTile label="Gross margin" value="28.0%" sub="+3.2 pp vs last month" accent="var(--badge-green-text)" />
        <StatTile label="Outstanding A/R" value="PLN 42,180" sub="6 invoices · oldest 14 days" accent="var(--accent)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 12, marginBottom: 16 }} className="grid-2col">
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Cumulative revenue</div>
          <div style={{ fontSize: 22, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 14 }}>PLN 184,500</div>
          <MiniBarChart data={days} accent="var(--accent)" height={120} />
        </Card>
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Daily margin %</div>
          <div style={{ fontSize: 22, fontWeight: 700, fontFamily: '"DM Serif Display", serif', color: 'var(--text)', marginBottom: 14 }}>28.0%</div>
          <MiniBarChart data={margin} accent="var(--badge-green-text)" height={120} />
        </Card>
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>P&L summary</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <tbody>
            {[
              ['Revenue (proforma accepted)',     'PLN 184,500', false],
              ['  Goods sold',                     'PLN 178,200', true],
              ['  Service fees',                   'PLN 6,300',   true],
              ['Cost of goods (PZ booked)',        'PLN 124,800', false],
              ['  Net invoice value',              'PLN 109,400', true],
              ['  Duty A00',                       'PLN 7,200',   true],
              ['  Shipping & insurance',           'PLN 4,800',   true],
              ['  Service invoices',               'PLN 3,400',   true],
              ['Gross profit',                     'PLN 51,700',  false, 'green'],
              ['Operating expenses',               'PLN 18,200',  false],
              ['EBITDA',                           'PLN 33,500',  false, 'gold'],
            ].map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '8px 12px', fontSize: 12, color: r[2] ? 'var(--text-2)' : 'var(--text)', fontWeight: r[2] ? 400 : 600, paddingLeft: r[2] ? 28 : 12 }}>{r[0]}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: r[2] ? 400 : 700, color: r[3] === 'green' ? 'var(--badge-green-text)' : r[3] === 'gold' ? 'var(--accent)' : 'var(--text)' }}>{r[1]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ReportsSales() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Proformas issued" value="38" sub="MTD · +12 vs last month" />
        <StatTile label="Accepted" value="29" sub="76% acceptance rate" accent="var(--badge-green-text)" />
        <StatTile label="Avg deal size" value="PLN 6,360" sub="vs PLN 5,820 last month" accent="var(--accent)" />
        <StatTile label="Days to close" value="3.2" sub="median · -0.8d MoM" accent="var(--badge-green-text)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }} className="grid-2col">
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Top clients (MTD)</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <tbody>
              {[
                ['Estrella Boutique Warsaw', 'PLN 64,200', 9],
                ['Geneva Imports SA',         'PLN 38,900', 4],
                ['Estrella Boutique Krakow',  'PLN 28,600', 6],
                ['Atelier Bonacchi SRL',      'PLN 22,400', 3],
                ['Paris Atelier Direct',      'PLN 14,800', 2],
              ].map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{r[0]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r[1]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontSize: 11, color: 'var(--text-3)', width: 60 }}>{r[2]} prof.</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>By product category</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <tbody>
              {[
                ['Gold jewellery',   'PLN 98,400', '53%'],
                ['Silver jewellery', 'PLN 38,200', '21%'],
                ['Diamond pieces',   'PLN 28,400', '15%'],
                ['Coloured stones',  'PLN 14,200', '8%'],
                ['Imitation / accessories', 'PLN 5,300', '3%'],
              ].map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 0', fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{r[0]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r[1]}</td>
                  <td style={{ padding: '8px 0', textAlign: 'right', fontSize: 11, color: 'var(--accent)', width: 60, fontWeight: 700 }}>{r[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function ReportsPurchase() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="PZ documents" value="142" sub="MTD · all booked to wFirma" />
        <StatTile label="Total purchase value" value="PLN 124,800" sub="Net of duty & shipping" />
        <StatTile label="Duty paid (A00)" value="PLN 7,200" sub="Avg 5.8% on dutiable goods" accent="var(--accent)" />
        <StatTile label="VAT recoverable" value="PLN 28,704" sub="23% · settled in declaration" accent="var(--badge-green-text)" />
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Top suppliers (MTD)</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['Supplier', 'Country', 'Shipments', 'Net value', 'Duty', 'Avg clearance'].map(h => <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
          <tbody>
            {[
              ['Bonacchi Atelier',  'IT', '24', 'PLN 48,200', 'PLN 1,205', '1.8d'],
              ['Maison de Vicenza', 'IT', '18', 'PLN 32,400', 'PLN 810',   '2.1d'],
              ['Geneva Goldworks',  'CH', '12', 'PLN 28,800', 'PLN 720',   '4.2d'],
              ['Antwerp Stones',    'BE', '8',  'PLN 9,600',  'PLN 0',     '1.4d'],
              ['Paris Diamonds',    'FR', '6',  'PLN 5,800',  'PLN 0',     '1.6d'],
            ].map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                {r.map((c, j) => <td key={j} style={{ padding: '10px 12px', fontSize: 12, color: j === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: j === 0 ? 600 : 400, fontFamily: j >= 3 && j <= 4 ? 'monospace' : 'inherit', textAlign: j >= 3 ? 'right' : 'left' }}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ReportsShipping() {
  const carriers = [['DHL', 84, 60], ['FedEx', 32, 25], ['UPS', 18, 13], ['Other', 8, 6]];
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Shipments" value="142" sub="MTD · 138 cleared" />
        <StatTile label="On-time clearance" value="92%" sub="Target 90% · met" accent="var(--badge-green-text)" />
        <StatTile label="Avg clearance time" value="2.1d" sub="vs target ≤ 3d" accent="var(--badge-green-text)" />
        <StatTile label="Held / blocked" value="2" sub="Manual review queue" accent="var(--accent)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }} className="grid-2col">
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 14 }}>By carrier</div>
          {carriers.map(c => (
            <div key={c[0]} style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{c[0]}</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{c[1]} shipments · {c[2]}%</span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-subtle)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${c[2]}%`, height: '100%', background: 'var(--accent)' }} />
              </div>
            </div>
          ))}
        </Card>
        <Card style={{ padding: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Tracking export</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6, marginBottom: 12 }}>
            Export per-shipment tracking history (status, location, dwell time at each leg) for all carriers in the selected period. Includes failed-clearance reason codes.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="gold" small>↓ Export tracking CSV</Btn>
            <Btn variant="outline" small>↓ Export PDF</Btn>
          </div>
          <div style={{ marginTop: 16, padding: 12, background: 'var(--bg-subtle)', borderRadius: 4, fontSize: 11, color: 'var(--text-3)' }}>
            Last export: yesterday 17:42 · 142 rows · sent to ops@estrella-jewels.pl
          </div>
        </Card>
      </div>
    </div>
  );
}

function ReportsDuty() {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }} className="grid-stats">
        <StatTile label="Duty paid" value="PLN 7,200" sub="A00 · MTD" accent="var(--accent)" />
        <StatTile label="VAT (import)" value="PLN 28,704" sub="23% · recoverable" accent="var(--badge-green-text)" />
        <StatTile label="Avg duty rate" value="2.6%" sub="weighted · all dutiable" />
        <StatTile label="Tariff codes used" value="9" sub="HS 6-digit distinct" />
      </div>

      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 12 }}>Duty by HS code (MTD)</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ background: 'var(--bg-subtle)' }}>{['HS code', 'Description', 'Shipments', 'Net value', 'Duty rate', 'Duty paid'].map(h => <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
          <tbody>
            {[
              ['7113.19.00', 'Articles of jewellery, precious metal',          '68', 'PLN 64,200', '2.5%', 'PLN 1,605'],
              ['7113.11.00', 'Articles of jewellery, silver',                  '34', 'PLN 28,400', '2.5%', 'PLN 710'],
              ['7117.19.00', 'Imitation jewellery, base metal',                '12', 'PLN 4,800',  '4.0%', 'PLN 192'],
              ['7102.39.00', 'Diamonds, non-industrial, worked',               '8',  'PLN 14,200', '0.0%', 'PLN 0'],
              ['7103.91.00', 'Rubies, sapphires, emeralds — worked',           '6',  'PLN 8,400',  '0.0%', 'PLN 0'],
            ].map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                {r.map((c, j) => <td key={j} style={{ padding: '10px 12px', fontSize: 12, fontFamily: j === 0 ? 'monospace' : 'inherit', color: j === 0 ? 'var(--text)' : 'var(--text-2)', fontWeight: j === 0 ? 600 : 400, textAlign: j >= 2 ? 'right' : 'left' }}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

Object.assign(window, {
  DhlCustomsPage,
  AccountingPage,
  EmailQueuePage,
  AiBridgePage,
  ActionProposalsPage,
  ReportsPage,        // overrides the old one
  // small helpers also exported in case other files want them
  Tabs, StatTile, Pill,
});
