// Shipment Detail Page — workflow strip + tabbed structure
// Tabs: Overview · DHL / Customs · PZ / Accounting · Documents · Timeline

const SHIPMENT_TABS = [
  { id: 'overview',  label: 'Overview' },
  { id: 'dhl',       label: 'DHL / Customs' },
  { id: 'pz',        label: 'PZ / Accounting' },
  { id: 'documents', label: 'Documents' },
  { id: 'timeline',  label: 'Timeline' },
];

// 7-stage workflow strip (matches operational pipeline)
const WORKFLOW_STAGES = [
  { id: 'intake',    num: '01', label: 'Intake' },
  { id: 'precheck',  num: '02', label: 'DHL Pre-check' },
  { id: 'reply',     num: '03', label: 'DHL Reply' },
  { id: 'sad',       num: '04', label: 'SAD / ZC429' },
  { id: 'verified',  num: '05', label: 'Verified' },
  { id: 'pz',        num: '06', label: 'PZ Generated' },
  { id: 'wfirma',    num: '07', label: 'wFirma Booked' },
];

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

  // Compute workflow stage states
  const stageState = (id) => {
    if (id === 'intake')   return 'done';
    if (id === 'precheck') return 'done';
    if (id === 'reply')    return replySent ? 'done' : (dhlEmailReceived ? 'active' : 'active');
    if (id === 'sad')      return sadUploaded ? 'done' : (replySent ? 'active' : 'pending');
    if (id === 'verified') return sadUploaded ? 'done' : 'pending';
    if (id === 'pz')       return pzGenerated ? 'done' : (sadUploaded ? 'active' : 'pending');
    if (id === 'wfirma')   return pzExported ? 'done' : (pzGenerated ? 'active' : 'pending');
    return 'pending';
  };

  // Compute the single "next action" for the operator
  const nextAction = (() => {
    if (!dhlEmailReceived) return { label: 'Scan DHL inbox for clearance email', tab: 'dhl', cta: 'Go to DHL / Customs' };
    if (!replySent)        return { label: 'Send reply package to DHL', tab: 'dhl', cta: 'Go to DHL / Customs' };
    if (!sadUploaded)      return { label: 'Upload SAD / ZC429 from customs agent', tab: 'dhl', cta: 'Go to DHL / Customs' };
    if (!pzGenerated)      return { label: 'Generate PZ document', tab: 'pz', cta: 'Go to PZ / Accounting' };
    if (!pzExported)       return { label: 'Export PZ to wFirma', tab: 'pz', cta: 'Go to PZ / Accounting' };
    return null;
  })();

  return (
    <div data-screen-label="Shipment Detail" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>

      {/* Notification toast */}
      {notification && (
        <div style={{
          position: 'fixed', top: 70, right: 24, zIndex: 999,
          background: notification.type === 'success' ? 'var(--badge-green-text)' : notification.type === 'info' ? 'var(--badge-blue-text)' : 'var(--badge-red-text)',
          color: '#fff', padding: '10px 18px', borderRadius: 8,
          fontSize: 12, fontWeight: 600, boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        }}>{notification.msg}</div>
      )}

      {/* Sub-header: AWB + stage badge + back */}
      <div style={{
        padding: '14px 32px', background: '#fff',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0,
      }}>
        <button onClick={onBack} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 4,
          color: 'var(--text-2)', fontSize: 12, padding: '4px 8px', borderRadius: 4,
        }}>← Back to shipments</button>
        <div style={{ width: 1, height: 20, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600 }}>AWB</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{shipment.awb}</div>
        </div>
        <div style={{ width: 1, height: 28, background: 'var(--border)' }} />
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600 }}>Importer</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{shipment.client || 'Estrella Jewels Sp. z o.o.'}</div>
        </div>
        <div style={{ flex: 1 }} />
        <Badge status={shipment.overall} />
      </div>

      {/* Workflow Strip */}
      <div style={{ padding: '16px 32px 0', background: '#fff' }}>
        <div style={{
          display: 'flex',
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          overflow: 'hidden',
        }}>
          {WORKFLOW_STAGES.map((stage, i) => {
            const state = stageState(stage.id);
            const isLast = i === WORKFLOW_STAGES.length - 1;
            const colors = {
              done:    { bg: 'rgba(46, 125, 50, 0.06)', num: 'var(--badge-green-text)', label: 'var(--badge-green-text)', icon: '✓' },
              active:  { bg: 'rgba(212, 168, 83, 0.10)', num: GOLD, label: 'var(--text)', icon: '●' },
              pending: { bg: 'transparent', num: 'var(--text-3)', label: 'var(--text-3)', icon: '○' },
            }[state];
            return (
              <div key={stage.id} style={{
                flex: 1,
                padding: '10px 12px',
                background: colors.bg,
                borderRight: isLast ? 'none' : '1px solid var(--border)',
                position: 'relative',
                fontWeight: state === 'active' ? 700 : 500,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 10, fontFamily: 'monospace', color: colors.num, fontWeight: 700 }}>{stage.num}</span>
                  <span style={{ fontSize: 11, color: colors.num }}>{colors.icon}</span>
                </div>
                <div style={{ fontSize: 11, color: colors.label, lineHeight: 1.3 }}>{stage.label}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Tab nav */}
      <div style={{
        display: 'flex', gap: 0, padding: '0 32px',
        background: '#fff', borderBottom: '1px solid var(--border)',
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        {SHIPMENT_TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: '14px 18px',
            background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${activeTab === t.id ? GOLD : 'transparent'}`,
            color: activeTab === t.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 12, fontWeight: activeTab === t.id ? 600 : 500,
            transition: 'all 0.12s',
          }}>{t.label}</button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ padding: '20px 32px', display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* Next-action gold callout (visible on every tab if there is one) */}
        {nextAction && (
          <div style={{
            background: 'linear-gradient(135deg, rgba(212, 168, 83, 0.10), rgba(212, 168, 83, 0.04))',
            border: '1px solid rgba(212, 168, 83, 0.35)',
            borderRadius: 8,
            padding: '14px 18px',
            display: 'flex', alignItems: 'center', gap: 14,
          }}>
            <div style={{
              width: 32, height: 32, borderRadius: 16,
              background: GOLD, color: 'var(--text)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, fontWeight: 800, flexShrink: 0,
            }}>▶</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: GOLD, letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 2 }}>Next operator action</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{nextAction.label}</div>
            </div>
            {activeTab !== nextAction.tab && (
              <Btn variant="gold" small onClick={() => setActiveTab(nextAction.tab)}>{nextAction.cta} →</Btn>
            )}
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} pzExported={pzExported} replySent={replySent} dhlEmailReceived={dhlEmailReceived} setActiveTab={setActiveTab} />
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

// ── OVERVIEW TAB — at-a-glance summary

function OverviewTab({ shipment, sadUploaded, pzGenerated, pzExported, replySent, dhlEmailReceived, setActiveTab }) {
  const stats = [
    { label: 'Pieces',         value: shipment.pieces || '—' },
    { label: 'Total CIF',      value: 'EUR 1,280.00' },
    { label: 'Net Value',      value: shipment.net },
    { label: 'Duty A00',       value: shipment.duty },
  ];

  return (
    <>
      {/* Quick stats row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {stats.map(s => (
          <div key={s.label} style={{
            padding: '14px 16px',
            background: 'var(--card)',
            border: '1px solid var(--border)',
            borderRadius: 6,
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-display)' }}>{s.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Shipment info */}
        <Card>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)' }}>Shipment</div>
            <button onClick={() => setActiveTab('dhl')} style={{ background: 'none', border: 'none', color: 'var(--text-2)', fontSize: 11, cursor: 'pointer' }}>View →</button>
          </div>
          <div style={{ padding: '4px 18px 12px' }}>
            <InfoRow label="AWB / Tracking" value={shipment.awb} mono />
            <InfoRow label="Carrier" value={shipment.carrier} />
            <InfoRow label="Tracking" value="In Transit" />
            <InfoRow label="Invoices" value="3 invoices uploaded" />
            <InfoRow label="AWB PDF" value="Uploaded ✓" />
          </div>
        </Card>

        {/* DHL clearance summary */}
        <Card>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)' }}>DHL Clearance</div>
            <button onClick={() => setActiveTab('dhl')} style={{ background: 'none', border: 'none', color: 'var(--text-2)', fontSize: 11, cursor: 'pointer' }}>View →</button>
          </div>
          <div style={{ padding: '4px 18px 12px' }}>
            <InfoRow label="Total Invoice CIF" value="EUR 1,280.00" />
            <InfoRow label="DSK Recommendation" value="Standard DSK" />
            <InfoRow label="DHL Email" value={dhlEmailReceived ? 'Received ✓' : 'Awaiting'} />
            <InfoRow label="Reply Status" value={replySent ? 'Sent ✓' : 'Not sent'} />
          </div>
        </Card>

        {/* Customs (SAD) */}
        <Card>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)' }}>Customs / SAD</div>
            <button onClick={() => setActiveTab('dhl')} style={{ background: 'none', border: 'none', color: 'var(--text-2)', fontSize: 11, cursor: 'pointer' }}>View →</button>
          </div>
          <div style={{ padding: '4px 18px 12px' }}>
            <InfoRow label="SAD / ZC429" value={sadUploaded ? 'Uploaded ✓' : 'Not uploaded'} />
            <InfoRow label="MRN" value={shipment.mrn} mono />
            <InfoRow label="Clearance Date" value={sadUploaded ? '27 Apr 2024' : '—'} />
            <InfoRow label="Customs Agent" value={sadUploaded ? 'Agencja Celna' : '—'} />
          </div>
        </Card>

        {/* PZ / accounting */}
        <Card>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)' }}>PZ / Accounting</div>
            <button onClick={() => setActiveTab('pz')} style={{ background: 'none', border: 'none', color: 'var(--text-2)', fontSize: 11, cursor: 'pointer' }}>View →</button>
          </div>
          <div style={{ padding: '4px 18px 12px' }}>
            <InfoRow label="PZ Status" value={pzGenerated ? 'Generated ✓' : (sadUploaded ? 'Ready' : 'Locked')} />
            <InfoRow label="PZ Number" value={pzGenerated ? 'PZ/2024/001234' : '—'} mono />
            <InfoRow label="Net Value" value={shipment.net} />
            <InfoRow label="wFirma" value={pzExported ? 'Exported ✓' : 'Not exported'} />
          </div>
        </Card>
      </div>
    </>
  );
}

// ── DHL / CUSTOMS TAB — combined: DHL clearance + SAD upload + verification

function DhlTab({ shipment, sadUploaded, setSadUploaded, dhlEmailReceived, setDhlEmailReceived, replySent, setReplySent, scanning, setScanning, notify, simulateAction }) {
  return (
    <>
      {/* DHL Clearance card */}
      <Card>
        <SectionHeader icon="✈" title="DHL Clearance" subtitle="Pre-check, email correspondence, and reply package" status={replySent ? 'Reply Sent' : (dhlEmailReceived ? 'DHL Email Received' : 'Awaiting Email')} />
        <div style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Customs Values</div>
            <InfoRow label="Total Invoice CIF" value="EUR 1,280.00" />
            <InfoRow label="FOB Value" value="EUR 1,150.00" />
            <InfoRow label="Freight" value="EUR 95.00" />
            <InfoRow label="Insurance" value="EUR 35.00" />
            <InfoRow label="DHL Threshold" value="EUR 150 — Reply Required" />
            <InfoRow label="DSK Recommendation" value="Standard DSK" />
          </div>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Reply Package Status</div>
            <InfoRow label="DHL Email" value={dhlEmailReceived ? 'Received ✓' : 'Awaiting'} />
            <InfoRow label="Polish Description" value={dhlEmailReceived ? 'Generated ✓' : '—'} />
            <InfoRow label="DSK PDF" value={dhlEmailReceived ? 'Generated ✓' : '—'} />
            <InfoRow label="Reply Package" value={replySent ? 'Sent ✓' : (dhlEmailReceived ? 'Built ✓' : '—')} />
            <InfoRow label="Reply Sent" value={replySent ? '27 Apr 2024 14:32' : 'Not sent'} />
          </div>
        </div>
        <div style={{ padding: '0 20px 16px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
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
      </Card>

      {/* SAD / Customs Documents card */}
      <Card>
        <SectionHeader icon="⊟" title="SAD / ZC429 — Customs Document" subtitle="Upload, parse, and verify the customs declaration" status={sadUploaded ? 'SAD Uploaded' : 'SAD Pending'} />
        <div style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Document References</div>
            <InfoRow label="SAD / ZC429 Status" value={sadUploaded ? 'Uploaded ✓' : 'Not uploaded'} />
            <InfoRow label="MRN" value={shipment.mrn} mono />
            <InfoRow label="LRN" value={sadUploaded ? 'LRN-20240427-001' : '—'} mono />
            <InfoRow label="Clearance Date" value={sadUploaded ? '27 Apr 2024' : '—'} />
            <InfoRow label="Customs Agent" value={sadUploaded ? 'Agencja Celna Sp. z o.o.' : '—'} />
          </div>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Values & Rates</div>
            <InfoRow label="SAD Exchange Rate" value={sadUploaded ? 'EUR/PLN 4.2650' : '—'} />
            <InfoRow label="NBP Accounting Rate" value={sadUploaded ? 'EUR/PLN 4.2510' : '—'} />
            <InfoRow label="A00 Duty" value={sadUploaded ? 'PLN 282.00' : '—'} />
            <InfoRow label="B00 VAT" value={sadUploaded ? 'PLN 1,254.60' : '—'} />
            <InfoRow label="Art.33a / Import" value={sadUploaded ? 'Standard Import' : '—'} />
          </div>
        </div>

        {sadUploaded && (
          <div style={{ margin: '0 20px 16px', padding: 14, background: 'var(--bg-subtle)', borderRadius: 6, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>Verification Checks</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              {[
                { label: 'Invoice reference check', ok: true },
                { label: 'CIF / customs value check', ok: true },
                { label: 'Importer / exporter check', ok: true },
                { label: 'Quantity check', ok: shipment.sadStatus !== 'Verification Needed' },
              ].map(c => (
                <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                  <span style={{ color: c.ok ? 'var(--badge-green-text)' : 'var(--badge-red-text)', fontSize: 13 }}>{c.ok ? '✓' : '⚠'}</span>
                  <span style={{ color: c.ok ? 'var(--text)' : 'var(--badge-red-text)' }}>{c.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ padding: '0 20px 16px', display: 'flex', gap: 8, alignItems: 'center' }}>
          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '7px 14px', borderRadius: 6, border: '1px solid var(--badge-neutral-border)',
            cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--text)',
            background: 'transparent',
          }}>
            <input type="file" style={{ display: 'none' }} onChange={() => { setSadUploaded(true); notify('SAD / ZC429 uploaded and parsed.'); }} />
            ⊞ Upload SAD / ZC429
          </label>
          {sadUploaded && <span style={{ fontSize: 11, color: 'var(--badge-green-text)' }}>✓ SAD uploaded — customs values parsed</span>}
        </div>
      </Card>
    </>
  );
}

// ── PZ / ACCOUNTING TAB

function PzTab({ shipment, sadUploaded, pzGenerated, setPzGenerated, pzExported, setPzExported, pzNumber, setPzNumber, confirmingPz, setConfirmingPz, notify }) {
  return (
    <Card>
      <SectionHeader icon="⊞" title="PZ Document & wFirma Booking" subtitle="Goods receipt document, audit files, and wFirma export" status={pzExported ? 'Exported' : (pzGenerated ? 'Generated' : (sadUploaded ? 'Ready for PZ' : 'Locked'))} />

      {!sadUploaded ? (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 32, marginBottom: 10 }}>🔒</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>PZ Locked</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Upload SAD / ZC429 from the DHL / Customs tab to unlock PZ generation.</div>
        </div>
      ) : (
        <div style={{ padding: 20 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 16 }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>PZ Details</div>
              <InfoRow label="PZ Status" value={pzGenerated ? 'Generated ✓' : 'Ready for PZ'} />
              <InfoRow label="PZ Number" value={pzNumber || '—'} mono />
              <InfoRow label="Net Value" value={shipment.net} />
              <InfoRow label="Gross Value" value={shipment.gross} />
              <InfoRow label="Duty A00" value={shipment.duty} />
            </div>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>wFirma</div>
              <InfoRow label="wFirma Status" value={pzExported ? 'Exported ✓' : 'Not exported'} />
              <InfoRow label="Export Date" value={pzExported ? '27 Apr 2024' : '—'} />
              <InfoRow label="External Doc ID" value={pzExported ? 'WF-2024-04-PZ-1234' : '—'} mono />
            </div>
          </div>

          {confirmingPz && (
            <div style={{ marginBottom: 16, padding: 14, background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>Enter PZ Number</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Input value={pzNumber} onChange={e => setPzNumber(e.target.value)} placeholder="e.g. PZ/2024/001234" style={{ flex: 1 }} />
                <Btn variant="gold" onClick={() => { setConfirmingPz(false); notify('PZ number confirmed and saved.'); }}>Confirm</Btn>
                <Btn variant="outline" onClick={() => setConfirmingPz(false)}>Cancel</Btn>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: pzGenerated ? 12 : 0 }}>
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
            <div style={{ display: 'flex', gap: 8, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
              <Btn variant="outline" onClick={() => notify('wFirma format copied to clipboard.')}>⊞ Copy wFirma Format</Btn>
              <Btn variant="default" disabled={pzExported} onClick={() => { setPzExported(true); notify('Exported to wFirma successfully.'); }}>
                {pzExported ? '✓ Exported to wFirma' : '↗ Export to wFirma'}
              </Btn>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ── DOCUMENTS TAB

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
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '12px 16px', borderRadius: 6,
      border: '1px solid var(--border)', background: 'var(--card)',
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 6,
        background: available ? 'var(--badge-blue-bg)' : 'var(--badge-neutral-bg)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 16,
      }}>
        {doc.name.endsWith('.pdf') ? '📄' : doc.name.endsWith('.xlsx') ? '📊' : doc.name.endsWith('.json') ? '{}' : '📦'}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: available ? 'var(--text)' : 'var(--text-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</div>
        <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 1 }}>{doc.type}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {available
          ? <span style={{ fontSize: 10, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ {doc.status === 'uploaded' ? 'Uploaded' : 'Generated'}</span>
          : <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Not generated</span>
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
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>Uploaded Shipment Documents</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[...UPLOADED_DOCS, sadDoc, dhlDoc].map((d, i) => (
            <DocCard key={i} doc={d} sadUploaded={sadUploaded} pzGenerated={pzGenerated} onNotify={onNotify} />
          ))}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>Generated Output Documents</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {GENERATED_DOCS.map((d, i) => (
            <DocCard key={i} doc={d} sadUploaded={sadUploaded} pzGenerated={pzGenerated} onNotify={onNotify} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── TIMELINE TAB

const TIMELINE_EVENTS = [
  { label: 'Shipment created', done: true, date: '10 Apr 2024, 09:12' },
  { label: 'Invoice uploaded', done: true, date: '10 Apr 2024, 09:15' },
  { label: 'AWB uploaded', done: true, date: '10 Apr 2024, 09:17' },
  { label: 'DHL pre-check completed', done: true, date: '10 Apr 2024, 09:20' },
  { label: 'DHL email received', done: null, date: null, key: 'dhlEmail' },
  { label: 'Polish description generated', done: null, date: null, key: 'dhlEmail' },
  { label: 'DSK generated', done: null, date: null, key: 'dhlEmail' },
  { label: 'Reply package prepared', done: null, date: null, key: 'dhlEmail' },
  { label: 'Reply sent to DHL', done: null, date: null, key: 'reply' },
  { label: 'SAD / ZC429 uploaded', done: null, date: null, key: 'sad' },
  { label: 'Customs values parsed', done: null, date: null, key: 'sad' },
  { label: 'Verification checks passed', done: null, date: null, key: 'sad' },
  { label: 'PZ unlocked', done: null, date: null, key: 'pzUnlock' },
  { label: 'PZ generated', done: null, date: null, key: 'pz' },
  { label: 'PZ number confirmed', done: null, date: null, key: 'pz' },
  { label: 'Exported to wFirma', done: null, date: null, key: 'wfirma' },
];

function TimelineTab({ shipment, sadUploaded, pzGenerated, replySent, dhlEmailReceived, pzExported }) {
  const events = TIMELINE_EVENTS.map(e => {
    let done = e.done;
    if (e.key === 'dhlEmail' && (dhlEmailReceived || replySent)) done = true;
    if (e.key === 'reply' && replySent) done = true;
    if (e.key === 'sad' && sadUploaded) done = true;
    if (e.key === 'pzUnlock' && sadUploaded) done = true;
    if (e.key === 'pz' && pzGenerated) done = true;
    if (e.key === 'wfirma' && pzExported) done = true;
    return { ...e, done };
  });

  return (
    <Card style={{ padding: 28 }}>
      <div style={{ position: 'relative', paddingLeft: 32 }}>
        <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: 'var(--border)' }} />
        {events.map((e, i) => (
          <div key={i} style={{ position: 'relative', marginBottom: 18, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
            <div style={{
              position: 'absolute', left: -32,
              width: 16, height: 16, borderRadius: '50%',
              background: e.done ? GOLD : 'var(--card)',
              border: `2px solid ${e.done ? GOLD : 'var(--badge-neutral-border)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              zIndex: 1, top: 1,
            }}>
              {e.done && <span style={{ fontSize: 7, color: 'var(--text)', fontWeight: 800 }}>✓</span>}
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: e.done ? 600 : 400, color: e.done ? 'var(--text)' : 'var(--text-3)' }}>{e.label}</div>
              {e.done && e.date && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>{e.date}</div>}
              {e.done && !e.date && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>Completed</div>}
              {!e.done && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>Pending</div>}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

Object.assign(window, { ShipmentDetailPage });
