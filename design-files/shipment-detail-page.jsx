// Shipment Detail Page — light-theme redesign with clean tabbed structure
// Tabs: Overview · DHL / Customs · PZ / Accounting · Documents · Timeline

const SHIPMENT_TABS = [
  { id: 'overview',  label: 'Overview' },
  { id: 'proforma',  label: 'Pro Forma' },
  { id: 'dhl',       label: 'DHL / Customs' },
  { id: 'pz',        label: 'PZ / Accounting' },
  { id: 'documents', label: 'Documents' },
  { id: 'timeline',  label: 'Timeline' },
];

// 7-stage workflow (sequential)
const WORKFLOW_STAGES = [
  { id: 'intake',    num: 1, label: 'Intake' },
  { id: 'precheck',  num: 2, label: 'Pre-check' },
  { id: 'reply',     num: 3, label: 'DHL Reply' },
  { id: 'sad',       num: 4, label: 'SAD / ZC429' },
  { id: 'verified',  num: 5, label: 'Verified' },
  { id: 'pz',        num: 6, label: 'PZ Generated' },
  { id: 'wfirma',    num: 7, label: 'wFirma Booked' },
];

// Reusable section heading: "OVERLINE ─────────────"
function SectionLabel({ children, style }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, ...style }}>
      <span style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
        letterSpacing: '0.12em', textTransform: 'uppercase',
      }}>{children}</span>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  );
}

// Card with optional header
function PanelCard({ title, subtitle, status, children, accent }) {
  return (
    <div style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      boxShadow: '0 1px 2px var(--shadow)',
      overflow: 'hidden',
      borderLeft: accent ? `3px solid ${accent}` : `1px solid var(--border)`,
    }}>
      {(title || status) && (
        <div style={{
          padding: '14px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, background: 'var(--bg-subtle)',
        }}>
          <div>
            {title && <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', letterSpacing: '0.01em' }}>{title}</div>}
            {subtitle && <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{subtitle}</div>}
          </div>
          {status && <Badge status={status} />}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
}

function ShipmentDetailPage({ shipment, onBack }) {
  const [activeTab, setActiveTab] = React.useState('overview');
  const [sadUploaded, setSadUploaded] = React.useState(shipment.sadStatus !== 'SAD Pending');
  const [pzGenerated, setPzGenerated] = React.useState(shipment.pzStatus === 'Generated' || shipment.pzStatus === 'Exported');
  const [pzExported, setPzExported] = React.useState(shipment.pzStatus === 'Exported');
  const [pzNumber, setPzNumber] = React.useState(pzGenerated ? 'PZ/2024/001234' : '');
  const [confirmingPz, setConfirmingPz] = React.useState(false);
  const [dhlEmailReceived, setDhlEmailReceived] = React.useState(shipment.dhlStatus === 'DHL Email Received' || shipment.dhlStatus === 'Reply Sent');
  const [replySent, setReplySent] = React.useState(shipment.dhlStatus === 'Reply Sent');
  const [scanning, setScanning] = React.useState(false);
  const [notification, setNotification] = React.useState(null);

  const notify = (msg, type = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 3000);
  };

  const simulateAction = (label, cb) => {
    notify(`Running: ${label}…`, 'info');
    setTimeout(() => { cb && cb(); notify(`${label} completed.`, 'success'); }, 1200);
  };

  const stageState = (id) => {
    if (id === 'intake')   return 'done';
    if (id === 'precheck') return 'done';
    if (id === 'reply')    return replySent ? 'done' : 'active';
    if (id === 'sad')      return sadUploaded ? 'done' : (replySent ? 'active' : 'pending');
    if (id === 'verified') return sadUploaded ? 'done' : 'pending';
    if (id === 'pz')       return pzGenerated ? 'done' : (sadUploaded ? 'active' : 'pending');
    if (id === 'wfirma')   return pzExported ? 'done' : (pzGenerated ? 'active' : 'pending');
    return 'pending';
  };

  const nextAction = (() => {
    if (!dhlEmailReceived) return { label: 'Scan DHL inbox for clearance email',     tab: 'dhl', cta: 'Open DHL / Customs' };
    if (!replySent)        return { label: 'Send reply package to DHL',              tab: 'dhl', cta: 'Open DHL / Customs' };
    if (!sadUploaded)      return { label: 'Upload SAD / ZC429 from customs agent',  tab: 'dhl', cta: 'Open DHL / Customs' };
    if (!pzGenerated)      return { label: 'Generate PZ document',                   tab: 'pz',  cta: 'Open PZ / Accounting' };
    if (!pzExported)       return { label: 'Export PZ to wFirma',                    tab: 'pz',  cta: 'Open PZ / Accounting' };
    return null;
  })();

  const stageColors = {
    done:    { num: '#FFFFFF', numBg: '#22A06B', numBorder: '#22A06B', label: '#186838', bg: 'rgba(34, 160, 107, 0.06)' },
    active:  { num: '#131C2E', numBg: '#D4B884', numBorder: '#B89968', label: '#7A5A20', bg: 'rgba(184, 153, 104, 0.10)' },
    pending: { num: '#9CA8B8', numBg: '#FFFFFF', numBorder: '#D8DAE2', label: '#8A9AB0', bg: 'transparent' },
  };

  return (
    <div data-screen-label="Shipment Detail" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>

      {notification && (
        <div style={{
          position: 'fixed', top: 70, right: 24, zIndex: 999,
          background: notification.type === 'success' ? 'var(--badge-green-text)' : notification.type === 'info' ? 'var(--badge-blue-text)' : 'var(--badge-red-text)',
          color: '#fff', padding: '10px 18px', borderRadius: 8,
          fontSize: 12, fontWeight: 600, boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
          animation: 'fadeIn 0.2s',
        }}>{notification.msg}</div>
      )}

      {/* Sub-header */}
      <div style={{
        padding: '16px 32px', background: 'var(--card)',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 20, flexShrink: 0,
      }}>
        <button onClick={onBack} style={{
          background: 'none', border: '1px solid var(--border)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
          color: 'var(--text-2)', fontSize: 12, padding: '6px 12px', borderRadius: 6,
          fontWeight: 500,
        }}>← Back</button>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>AWB / Tracking</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{shipment.awb}</div>
        </div>
        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Importer</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{shipment.client || 'Estrella Jewels Sp. z o.o.'}</div>
        </div>
        <div style={{ width: 1, height: 32, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 2 }}>Pieces</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{shipment.pieces || 47}</div>
        </div>
        <div style={{ flex: 1 }} />
        <Badge status={shipment.overall} />
      </div>

      {/* Workflow Strip */}
      <div style={{ padding: '20px 32px 0', background: 'var(--card)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 0, position: 'relative' }}>
          {WORKFLOW_STAGES.map((stage, i) => {
            const state = stageState(stage.id);
            const c = stageColors[state];
            const isLast = i === WORKFLOW_STAGES.length - 1;
            const nextState = !isLast ? stageState(WORKFLOW_STAGES[i + 1].id) : null;
            const connectorDone = state === 'done' && (nextState === 'done' || nextState === 'active');

            return (
              <React.Fragment key={stage.id}>
                <div style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center',
                  gap: 6, flexShrink: 0, padding: '0 4px', minWidth: 64,
                }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 16,
                    background: c.numBg, border: `2px solid ${c.numBorder}`,
                    color: c.num, fontSize: 13, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: state === 'active' ? '0 0 0 4px rgba(212, 168, 83, 0.18)' : 'none',
                    transition: 'all 0.15s',
                  }}>
                    {state === 'done' ? '✓' : stage.num}
                  </div>
                  <div style={{
                    fontSize: 10, fontWeight: state === 'active' ? 700 : 600,
                    color: c.label, textAlign: 'center', lineHeight: 1.2,
                    letterSpacing: '0.02em',
                  }}>{stage.label}</div>
                </div>
                {!isLast && (
                  <div style={{
                    flex: 1, height: 2, marginTop: -16,
                    background: connectorDone ? '#22A06B' : 'var(--border)',
                    transition: 'background 0.15s',
                  }} />
                )}
              </React.Fragment>
            );
          })}
        </div>
        <div style={{ height: 16 }} />
      </div>

      {/* Tab nav */}
      <div style={{
        display: 'flex', gap: 4, padding: '0 32px',
        background: 'var(--card)', borderBottom: '1px solid var(--border)',
      }}>
        {SHIPMENT_TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: '12px 16px',
            background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${activeTab === t.id ? 'var(--accent)' : 'transparent'}`,
            color: activeTab === t.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 13, fontWeight: activeTab === t.id ? 700 : 500,
            transition: 'all 0.12s', marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}>

        {/* Next-action callout */}
        {nextAction && activeTab === 'overview' && (
          <div style={{
            background: 'linear-gradient(135deg, #FBF5E4, #F8EDD0)',
            border: '1px solid var(--accent-border)',
            borderRadius: 10,
            padding: '16px 20px',
            display: 'flex', alignItems: 'center', gap: 16,
            boxShadow: '0 1px 3px rgba(201, 164, 86, 0.12)',
          }}>
            <div style={{
              width: 40, height: 40, borderRadius: 20,
              background: 'var(--accent)', color: 'var(--text)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16, fontWeight: 800, flexShrink: 0,
            }}>▶</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#7A5400', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 3 }}>Next operator action</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{nextAction.label}</div>
            </div>
            {activeTab !== nextAction.tab && (
              <button onClick={() => setActiveTab(nextAction.tab)} style={{
                padding: '8px 16px', background: 'var(--text)', color: 'var(--card)',
                border: 'none', borderRadius: 6, cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
              }}>{nextAction.cta} →</button>
            )}
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} pzExported={pzExported} replySent={replySent} dhlEmailReceived={dhlEmailReceived} setActiveTab={setActiveTab} />
        )}
        {activeTab === 'proforma' && (
          <ProformaTabInShipment shipment={shipment} />
        )}
        {activeTab === 'dhl' && (
          <DhlTab
            shipment={shipment} sadUploaded={sadUploaded} setSadUploaded={setSadUploaded}
            dhlEmailReceived={dhlEmailReceived} setDhlEmailReceived={setDhlEmailReceived}
            replySent={replySent} setReplySent={setReplySent}
            scanning={scanning} setScanning={setScanning}
            notify={notify} simulateAction={simulateAction}
          />
        )}
        {activeTab === 'pz' && (
          <PzTab
            shipment={shipment} sadUploaded={sadUploaded}
            pzGenerated={pzGenerated} setPzGenerated={setPzGenerated}
            pzExported={pzExported} setPzExported={setPzExported}
            pzNumber={pzNumber} setPzNumber={setPzNumber}
            confirmingPz={confirmingPz} setConfirmingPz={setConfirmingPz}
            notify={notify}
          />
        )}
        {activeTab === 'documents' && (
          <DocumentsTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} onNotify={notify} />
        )}
        {activeTab === 'timeline' && (
          <TimelineTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} replySent={replySent} dhlEmailReceived={dhlEmailReceived} pzExported={pzExported} />
        )}
      </div>
    </div>
  );
}

// ── Stat tile (light, refined)
function StatTile({ label, value, accent }) {
  return (
    <div style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: '16px 18px',
      boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: accent || 'var(--text)', letterSpacing: '0.01em' }}>{value}</div>
    </div>
  );
}

// ── Two-column info row inside a card
function InfoBlock({ rows }) {
  return (
    <div style={{ padding: '6px 20px 14px' }}>
      {rows.map((r, i) => (
        <InfoRow key={i} label={r.label} value={r.value} mono={r.mono} />
      ))}
    </div>
  );
}

// ── OVERVIEW

function OverviewTab({ shipment, sadUploaded, pzGenerated, pzExported, replySent, dhlEmailReceived, setActiveTab }) {
  return (
    <>
      <SectionLabel>Key figures</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
        <StatTile label="Pieces"        value={shipment.pieces || 47} />
        <StatTile label="Total CIF"     value="EUR 1,280" />
        <StatTile label="Net (PLN)"     value={shipment.net} />
        <StatTile label="Duty A00"      value={shipment.duty} />
      </div>

      <SectionLabel style={{ marginTop: 8 }}>Workflow areas</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Shipment */}
        <PanelCard title="Shipment" subtitle="Tracking, invoices, AWB" status="DHL In Transit">
          <InfoBlock rows={[
            { label: 'AWB / Tracking', value: shipment.awb, mono: true },
            { label: 'Carrier',        value: shipment.carrier },
            { label: 'Tracking',       value: 'In Transit' },
            { label: 'Invoices',       value: '3 uploaded' },
            { label: 'AWB PDF',        value: 'Uploaded ✓' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* DHL clearance */}
        <PanelCard title="DHL Clearance" subtitle="Email correspondence + reply" status={replySent ? 'Reply Sent' : (dhlEmailReceived ? 'DHL Email Received' : 'Awaiting DHL Email')}>
          <InfoBlock rows={[
            { label: 'Total Invoice CIF', value: 'EUR 1,280.00' },
            { label: 'DSK Recommendation', value: 'Standard DSK' },
            { label: 'DHL Email',         value: dhlEmailReceived ? 'Received ✓' : 'Awaiting' },
            { label: 'Reply Status',      value: replySent ? 'Sent ✓' : 'Not sent' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* Customs */}
        <PanelCard title="Customs / SAD" subtitle="ZC429 declaration & verification" status={sadUploaded ? 'SAD Uploaded' : 'SAD Pending'}>
          <InfoBlock rows={[
            { label: 'SAD / ZC429',    value: sadUploaded ? 'Uploaded ✓' : 'Not uploaded' },
            { label: 'MRN',            value: shipment.mrn, mono: true },
            { label: 'Clearance Date', value: sadUploaded ? '27 Apr 2024' : '—' },
            { label: 'Customs Agent',  value: sadUploaded ? 'Agencja Celna' : '—' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('dhl')} style={navLinkStyle()}>Open DHL / Customs →</button>
          </div>
        </PanelCard>

        {/* PZ / accounting */}
        <PanelCard title="PZ / Accounting" subtitle="Goods receipt & wFirma export" status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : (sadUploaded ? 'Ready for PZ' : 'Locked'))}>
          <InfoBlock rows={[
            { label: 'PZ Status',  value: pzGenerated ? 'Generated ✓' : (sadUploaded ? 'Ready' : 'Locked') },
            { label: 'PZ Number',  value: pzGenerated ? 'PZ/2024/001234' : '—', mono: true },
            { label: 'Net Value',  value: shipment.net },
            { label: 'wFirma',     value: pzExported ? 'Exported ✓' : 'Not exported' },
          ]} />
          <div style={{ padding: '0 20px 16px' }}>
            <button onClick={() => setActiveTab('pz')} style={navLinkStyle()}>Open PZ / Accounting →</button>
          </div>
        </PanelCard>
      </div>
    </>
  );
}

function navLinkStyle() {
  return {
    background: 'none', border: 'none', cursor: 'pointer',
    color: 'var(--text)', fontSize: 12, fontWeight: 600,
    padding: '6px 0', display: 'inline-flex', alignItems: 'center', gap: 4,
    textDecoration: 'underline', textUnderlineOffset: 4, textDecorationColor: 'var(--accent)',
    textDecorationThickness: 2,
  };
}

// ── DHL / CUSTOMS

function DhlTab({ shipment, sadUploaded, setSadUploaded, dhlEmailReceived, setDhlEmailReceived, replySent, setReplySent, scanning, setScanning, notify, simulateAction }) {
  return (
    <>
      <SectionLabel>Step 1 · DHL clearance email & reply</SectionLabel>
      <PanelCard
        title="DHL Clearance"
        subtitle="Pre-check, email correspondence, and reply package"
        status={replySent ? 'Reply Sent' : (dhlEmailReceived ? 'DHL Email Received' : 'Awaiting Email')}
        accent={replySent ? '#22A06B' : 'var(--accent)'}
      >
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Customs values</div>
            <InfoRow label="Total Invoice CIF"     value="EUR 1,280.00" />
            <InfoRow label="FOB Value"             value="EUR 1,150.00" />
            <InfoRow label="Freight"               value="EUR 95.00" />
            <InfoRow label="Insurance"             value="EUR 35.00" />
            <InfoRow label="DHL Threshold"         value="EUR 150 — Reply Required" />
            <InfoRow label="DSK Recommendation"    value="Standard DSK" />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Reply package status</div>
            <InfoRow label="DHL Email"           value={dhlEmailReceived ? 'Received ✓' : 'Awaiting'} />
            <InfoRow label="Polish Description"  value={dhlEmailReceived ? 'Generated ✓' : '—'} />
            <InfoRow label="DSK PDF"             value={dhlEmailReceived ? 'Generated ✓' : '—'} />
            <InfoRow label="Reply Package"       value={replySent ? 'Sent ✓' : (dhlEmailReceived ? 'Built ✓' : '—')} />
            <InfoRow label="Reply Sent"          value={replySent ? '27 Apr 2024 · 14:32' : 'Not sent'} />
          </div>
        </div>
        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="outline" onClick={() => { setScanning(true); setTimeout(() => { setScanning(false); setDhlEmailReceived(true); notify('DHL inbox scanned — 1 email matched.'); }, 1500); }}>
            {scanning ? '⟳ Scanning…' : '⌕ Scan DHL Inbox'}
          </Btn>
          <Btn variant="outline" onClick={() => { setDhlEmailReceived(true); notify('DHL email marked received.'); }}>✓ Mark Email Received</Btn>
          <Btn variant="outline" onClick={() => simulateAction('Generate Polish Description')}>⊞ Generate Polish Desc.</Btn>
          <Btn variant="outline" onClick={() => simulateAction('Generate DSK')}>⊟ Generate DSK</Btn>
          <Btn variant="outline" onClick={() => simulateAction('Build DHL Reply Package')}>⊡ Build Reply Package</Btn>
          <Btn variant={replySent ? 'ghost' : 'gold'} disabled={!dhlEmailReceived || replySent} onClick={() => { setReplySent(true); notify('Reply sent to DHL.'); }}>
            {replySent ? '✓ Reply Sent' : '↗ Send Reply to DHL'}
          </Btn>
        </div>
      </PanelCard>

      <SectionLabel style={{ marginTop: 8 }}>Step 2 · SAD / ZC429 customs document</SectionLabel>
      <PanelCard
        title="SAD / ZC429"
        subtitle="Upload, parse, and verify the customs declaration"
        status={sadUploaded ? 'SAD Uploaded' : 'SAD Pending'}
        accent={sadUploaded ? '#22A06B' : (replySent ? 'var(--accent)' : null)}
      >
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Document references</div>
            <InfoRow label="SAD / ZC429 Status" value={sadUploaded ? 'Uploaded ✓' : 'Not uploaded'} />
            <InfoRow label="MRN"                value={shipment.mrn} mono />
            <InfoRow label="LRN"                value={sadUploaded ? 'LRN-20240427-001' : '—'} mono />
            <InfoRow label="Clearance Date"     value={sadUploaded ? '27 Apr 2024' : '—'} />
            <InfoRow label="Customs Agent"      value={sadUploaded ? 'Agencja Celna Sp. z o.o.' : '—'} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Values & rates</div>
            <InfoRow label="SAD Exchange Rate"   value={sadUploaded ? 'EUR/PLN 4.2650' : '—'} />
            <InfoRow label="NBP Accounting Rate" value={sadUploaded ? 'EUR/PLN 4.2510' : '—'} />
            <InfoRow label="A00 Duty"            value={sadUploaded ? 'PLN 282.00' : '—'} />
            <InfoRow label="B00 VAT"             value={sadUploaded ? 'PLN 1,254.60' : '—'} />
            <InfoRow label="Art.33a / Import"    value={sadUploaded ? 'Standard Import' : '—'} />
          </div>
        </div>

        {sadUploaded && (
          <div style={{ margin: '0 20px 16px', padding: '14px 16px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-green-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Verification checks</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {[
                { label: 'Invoice reference check',     ok: true },
                { label: 'CIF / customs value check',   ok: true },
                { label: 'Importer / exporter check',   ok: true },
                { label: 'Quantity check',              ok: shipment.sadStatus !== 'Verification Needed' },
              ].map(c => (
                <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{
                    width: 18, height: 18, borderRadius: 9,
                    background: c.ok ? 'var(--badge-green-text)' : 'var(--badge-red-text)',
                    color: '#fff', fontSize: 11, fontWeight: 700,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}>{c.ok ? '✓' : '!'}</span>
                  <span style={{ color: c.ok ? 'var(--text)' : 'var(--badge-red-text)', fontWeight: 500 }}>{c.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border)',
            cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--text)',
            background: 'var(--card)',
          }}>
            <input type="file" style={{ display: 'none' }} onChange={() => { setSadUploaded(true); notify('SAD / ZC429 uploaded and parsed.'); }} />
            ⊞ Upload SAD / ZC429
          </label>
          {sadUploaded && <span style={{ fontSize: 12, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ SAD uploaded — customs values parsed</span>}
        </div>
      </PanelCard>
    </>
  );
}

// ── PZ / ACCOUNTING

function PzTab({ shipment, sadUploaded, pzGenerated, setPzGenerated, pzExported, setPzExported, pzNumber, setPzNumber, confirmingPz, setConfirmingPz, notify }) {
  if (!sadUploaded) {
    return (
      <PanelCard title="PZ Document & wFirma Booking" subtitle="Goods receipt, audit files, and accounting export" status="Locked">
        <div style={{ padding: 48, textAlign: 'center' }}>
          <div style={{
            width: 56, height: 56, borderRadius: 28,
            background: 'var(--badge-neutral-bg)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 14px', fontSize: 22,
          }}>🔒</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>PZ Locked</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', maxWidth: 420, margin: '0 auto', lineHeight: 1.5 }}>
            Upload SAD / ZC429 from the <strong>DHL / Customs</strong> tab to unlock PZ generation.
          </div>
        </div>
      </PanelCard>
    );
  }

  return (
    <>
      <SectionLabel>Step 3 · PZ document &amp; wFirma booking</SectionLabel>
      <PanelCard
        title="PZ Document"
        subtitle="Generate goods receipt, download audit files, export to wFirma"
        status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : 'Ready for PZ')}
        accent={pzExported ? '#22A06B' : (pzGenerated ? '#22A06B' : 'var(--accent)')}
      >
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>PZ details</div>
            <InfoRow label="PZ Status"   value={pzGenerated ? 'Generated ✓' : 'Ready for PZ'} />
            <InfoRow label="PZ Number"   value={pzNumber || '—'} mono />
            <InfoRow label="Net Value"   value={shipment.net} />
            <InfoRow label="Gross Value" value={shipment.gross} />
            <InfoRow label="Duty A00"    value={shipment.duty} />
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>wFirma export</div>
            <InfoRow label="wFirma Status"   value={pzExported ? 'Exported ✓' : 'Not exported'} />
            <InfoRow label="Export Date"     value={pzExported ? '27 Apr 2024' : '—'} />
            <InfoRow label="External Doc ID" value={pzExported ? 'WF-2024-04-PZ-1234' : '—'} mono />
          </div>
        </div>

        {confirmingPz && (
          <div style={{ margin: '0 20px 16px', padding: '14px 16px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10, color: 'var(--text)' }}>Enter PZ number</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Input value={pzNumber} onChange={e => setPzNumber(e.target.value)} placeholder="e.g. PZ/2024/001234" style={{ flex: 1 }} />
              <Btn variant="gold" onClick={() => { setConfirmingPz(false); notify('PZ number confirmed and saved.'); }}>Confirm</Btn>
              <Btn variant="outline" onClick={() => setConfirmingPz(false)}>Cancel</Btn>
            </div>
          </div>
        )}

        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="gold" onClick={() => { setPzGenerated(true); setPzNumber('PZ/2024/001234'); notify('PZ generated successfully.'); }}>
            {pzGenerated ? '↺ Regenerate PZ' : '▶ Run PZ'}
          </Btn>
          {pzGenerated && (
            <>
              <Btn variant="outline" onClick={() => setConfirmingPz(true)}>✎ Confirm PZ Number</Btn>
              <Btn variant="outline" onClick={() => notify('Downloading PZ PDF…')}>↓ PZ PDF</Btn>
              <Btn variant="outline" onClick={() => notify('Downloading Calculation XLSX…')}>↓ Calc XLSX</Btn>
              <Btn variant="outline" onClick={() => notify('Downloading Audit EN PDF…')}>↓ Audit EN</Btn>
              <Btn variant="outline" onClick={() => notify('Downloading Audit PL PDF…')}>↓ Audit PL</Btn>
              <Btn variant="outline" onClick={() => notify('Downloading Audit Memo…')}>↓ Memo</Btn>
              <Btn variant="outline" onClick={() => notify('Downloading Correction Report…')}>↓ Correction</Btn>
            </>
          )}
        </div>
        {pzGenerated && (
          <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: 10 }}>
            <Btn variant="outline" onClick={() => notify('wFirma format copied to clipboard.')}>⊞ Copy wFirma Format</Btn>
            <Btn variant="default" disabled={pzExported} onClick={() => { setPzExported(true); notify('Exported to wFirma successfully.'); }}>
              {pzExported ? '✓ Exported to wFirma' : '↗ Export to wFirma'}
            </Btn>
          </div>
        )}
      </PanelCard>
    </>
  );
}

// ── DOCUMENTS

const UPLOADED_DOCS = [
  { name: 'Invoice_Estrella_Apr2024.pdf', type: 'Invoice PDF', status: 'uploaded' },
  { name: 'Invoice_Estrella_Apr2024_2.pdf', type: 'Invoice PDF', status: 'uploaded' },
  { name: 'Invoice_Estrella_Apr2024_3.pdf', type: 'Invoice PDF', status: 'uploaded' },
  { name: 'AWB_DHL_1234567890.pdf', type: 'AWB / Tracking PDF', status: 'uploaded' },
];

const GENERATED_DOCS = [
  { name: 'Polish_Customs_Description.pdf', type: 'Polish Customs Desc.', status: 'generated' },
  { name: 'SAD_ready.json', type: 'SAD-ready JSON', status: 'generated' },
  { name: 'DSK_Estrella_Apr2024.pdf', type: 'DSK PDF', status: 'generated' },
  { name: 'DHL_Reply_Package.zip', type: 'DHL Reply Package', status: 'generated' },
  { name: 'PZ_Estrella_Apr2024.pdf', type: 'PZ PDF', status: null },
  { name: 'Calculation_Apr2024.xlsx', type: 'Calculation XLSX', status: null },
  { name: 'Audit_EN_Apr2024.pdf', type: 'Audit EN PDF', status: null },
  { name: 'Audit_PL_Apr2024.pdf', type: 'Audit PL PDF', status: null },
  { name: 'Audit_Memo_Apr2024.pdf', type: 'Audit Memo PDF', status: null },
  { name: 'Correction_Report_Apr2024.pdf', type: 'Correction Report', status: null },
];

function DocCard({ doc, sadUploaded, pzGenerated, onNotify }) {
  const isPzRelated = doc.name.includes('PZ') || doc.name.includes('Calc') || doc.name.includes('Audit') || doc.name.includes('Correction');
  const available = doc.status === 'uploaded' || (doc.status === 'generated' && (!isPzRelated || pzGenerated)) || (isPzRelated && pzGenerated);
  const ext = doc.name.split('.').pop().toLowerCase();
  const iconBg = available ? (ext === 'pdf' ? 'var(--badge-red-bg)' : ext === 'xlsx' ? 'var(--badge-green-bg)' : ext === 'json' ? 'var(--badge-blue-bg)' : 'var(--badge-amber-bg)') : 'var(--badge-neutral-bg)';
  const iconColor = available ? (ext === 'pdf' ? 'var(--badge-red-text)' : ext === 'xlsx' ? 'var(--badge-green-text)' : ext === 'json' ? 'var(--badge-blue-text)' : 'var(--badge-amber-text)') : 'var(--text-3)';

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '14px 16px', borderRadius: 8,
      border: '1px solid var(--border)', background: 'var(--card)',
      boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 8,
        background: iconBg, color: iconColor,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 800, letterSpacing: '0.05em',
      }}>{ext.toUpperCase()}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: available ? 'var(--text)' : 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>{doc.type}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {available
          ? <span style={{ fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ {doc.status === 'uploaded' ? 'Uploaded' : 'Generated'}</span>
          : <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Not generated</span>
        }
        <Btn small variant={available ? 'outline' : 'ghost'} disabled={!available} onClick={() => onNotify(`Downloading ${doc.name}…`)}>↓</Btn>
      </div>
    </div>
  );
}

function DocumentsTab({ shipment, sadUploaded, pzGenerated, onNotify }) {
  const sadDoc = { name: 'SAD_ZC429.pdf', type: 'SAD / ZC429 PDF', status: sadUploaded ? 'uploaded' : null };
  const dhlDoc = { name: 'DHL_Email_Attachment.pdf', type: 'DHL Email Attachment', status: 'uploaded' };
  return (
    <div className="docs-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div>
        <SectionLabel>Uploaded shipment documents</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[...UPLOADED_DOCS, sadDoc, dhlDoc].map((d, i) => (
            <DocCard key={i} doc={d} sadUploaded={sadUploaded} pzGenerated={pzGenerated} onNotify={onNotify} />
          ))}
        </div>
      </div>
      <div>
        <SectionLabel>Generated output documents</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {GENERATED_DOCS.map((d, i) => (
            <DocCard key={i} doc={d} sadUploaded={sadUploaded} pzGenerated={pzGenerated} onNotify={onNotify} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── TIMELINE

const TIMELINE_EVENTS = [
  { label: 'Shipment created',                done: true, date: '10 Apr 2024 · 09:12' },
  { label: 'Invoice uploaded',                done: true, date: '10 Apr 2024 · 09:15' },
  { label: 'AWB uploaded',                    done: true, date: '10 Apr 2024 · 09:17' },
  { label: 'DHL pre-check completed',         done: true, date: '10 Apr 2024 · 09:20' },
  { label: 'DHL email received',              done: null, date: null, key: 'dhlEmail' },
  { label: 'Polish description generated',    done: null, date: null, key: 'dhlEmail' },
  { label: 'DSK generated',                   done: null, date: null, key: 'dhlEmail' },
  { label: 'Reply package prepared',          done: null, date: null, key: 'dhlEmail' },
  { label: 'Reply sent to DHL',               done: null, date: null, key: 'reply' },
  { label: 'SAD / ZC429 uploaded',            done: null, date: null, key: 'sad' },
  { label: 'Customs values parsed',           done: null, date: null, key: 'sad' },
  { label: 'Verification checks passed',      done: null, date: null, key: 'sad' },
  { label: 'PZ unlocked',                     done: null, date: null, key: 'pzUnlock' },
  { label: 'PZ generated',                    done: null, date: null, key: 'pz' },
  { label: 'PZ number confirmed',             done: null, date: null, key: 'pz' },
  { label: 'Exported to wFirma',              done: null, date: null, key: 'wfirma' },
];

function TimelineTab({ shipment, sadUploaded, pzGenerated, replySent, dhlEmailReceived, pzExported }) {
  const events = TIMELINE_EVENTS.map(e => {
    let done = e.done;
    if (e.key === 'dhlEmail' && (dhlEmailReceived || replySent)) done = true;
    if (e.key === 'reply'    && replySent) done = true;
    if (e.key === 'sad'      && sadUploaded) done = true;
    if (e.key === 'pzUnlock' && sadUploaded) done = true;
    if (e.key === 'pz'       && pzGenerated) done = true;
    if (e.key === 'wfirma'   && pzExported) done = true;
    return { ...e, done };
  });

  return (
    <PanelCard title="Activity timeline" subtitle="Chronological audit log of every event for this shipment">
      <div style={{ padding: '24px 28px' }}>
        <div style={{ position: 'relative', paddingLeft: 28 }}>
          <div style={{ position: 'absolute', left: 9, top: 6, bottom: 6, width: 2, background: 'var(--border)' }} />
          {events.map((e, i) => (
            <div key={i} style={{ position: 'relative', marginBottom: 18, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
              <div style={{
                position: 'absolute', left: -28,
                width: 20, height: 20, borderRadius: 10,
                background: e.done ? '#22A06B' : 'var(--card)',
                border: `2px solid ${e.done ? '#22A06B' : 'var(--border)'}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 1, top: 0,
              }}>
                {e.done && <span style={{ fontSize: 10, color: '#fff', fontWeight: 800 }}>✓</span>}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: e.done ? 600 : 500, color: e.done ? 'var(--text)' : 'var(--text-3)' }}>{e.label}</div>
                {e.done && e.date && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2, fontFamily: 'monospace' }}>{e.date}</div>}
                {e.done && !e.date && <div style={{ fontSize: 11, color: 'var(--badge-green-text)', marginTop: 2, fontWeight: 600 }}>Completed</div>}
                {!e.done && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Pending</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </PanelCard>
  );
}

// Pro Forma tab inside shipment detail — shows drafts for this shipment
function ProformaTabInShipment({ shipment }) {
  // Sample drafts linked to this shipment
  const drafts = [
    { id: 'pf_s1', number: 'PROF 95/2026', customer: 'Diamond Point NV', items: 47, totalEur: 18420.50, status: 'ready', createdAt: '2026-05-10 14:22' },
  ];

  return (
    <>
      <SectionLabel>Pro Forma drafts for this shipment</SectionLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {drafts.length === 0 ? (
          <PanelCard>
            <div style={{ padding: 32, textAlign: 'center' }}>
              <div style={{ fontSize: 13, color: 'var(--text-3)' }}>No pro forma drafts for this shipment</div>
              <Btn variant="gold" small style={{ marginTop: 14 }}>+ Create Pro Forma Draft</Btn>
            </div>
          </PanelCard>
        ) : (
          drafts.map(d => (
            <PanelCard key={d.id}>
              <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 16 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{d.number}</span>
                    <Badge status={d.status === 'ready' ? 'Ready' : d.status} />
                  </div>
                  <InfoRow label="Customer" value={d.customer} />
                  <InfoRow label="Items" value={d.items} />
                  <InfoRow label="Total EUR" value={`€${d.totalEur.toFixed(2)}`} />
                  <InfoRow label="Created" value={d.createdAt} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Btn variant="outline" small onClick={() => alert('Open Pro Forma detail (would navigate to /proforma/' + d.id + ')')}>Open Detail →</Btn>
                  <Btn variant="outline" small>↓ Download PDF</Btn>
                </div>
              </div>
            </PanelCard>
          ))
        )}
      </div>
      <div style={{ marginTop: 12, padding: '12px 16px', background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)', borderRadius: 8, fontSize: 11.5, color: 'var(--text)', lineHeight: 1.5 }}>
        <strong>Note:</strong> Pro Forma drafts are automatically created from shipment data. To manage all drafts across shipments, navigate to <strong>Documents → Pro Forma</strong> from the sidebar.
      </div>
    </>
  );
}

Object.assign(window, { ShipmentDetailPage });
