// Shipment Detail Page — 3 pipeline sections + Documents tab + Timeline

const TABS = ['Pipeline', 'Documents', 'Timeline'];

function ShipmentDetailPage({ shipment, onBack }) {
  const [activeTab, setActiveTab] = React.useState('Pipeline');
  const [sadUploaded, setSadUploaded] = React.useState(shipment.sadStatus !== 'SAD Pending');
  const [pzGenerated, setPzGenerated] = React.useState(shipment.pzStatus === 'Generated' || shipment.pzStatus === 'Exported');
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

  return (
    <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>

      {/* Notification toast */}
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
        padding: '14px 32px', background: '#fff',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0,
      }}>
        <button onClick={onBack} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 4,
          color: 'var(--text-2)', fontSize: 12,
        }}>← Back</button>
        <div style={{ width: 1, height: 20, background: 'var(--border)' }} />
        <div>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Shipment / </span>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', fontFamily: 'monospace' }}>{shipment.awb}</span>
        </div>
        <Badge status={shipment.overall} />
        <div style={{ flex: 1 }} />
        {TABS.map(t => (
          <button key={t} onClick={() => setActiveTab(t)} style={{
            padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: activeTab === t ? 'var(--text)' : 'transparent',
            color: activeTab === t ? '#fff' : 'var(--text-2)',
            fontSize: 12, fontWeight: activeTab === t ? 600 : 400,
          }}>{t}</button>
        ))}
      </div>

      <div style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 16 }}>

        {activeTab === 'Pipeline' && (
          <>
            {/* Section 1: Shipment & DHL Clearance */}
            <Card>
              <SectionHeader icon="✈" title="Section 1 — Shipment & DHL Clearance" subtitle="Track DHL pre-check, email correspondence, and reply package" status={shipment.dhlStatus} />
              <div style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Shipment Info</div>
                  <InfoRow label="AWB / Tracking" value={shipment.awb} mono />
                  <InfoRow label="Carrier" value={shipment.carrier} />
                  <InfoRow label="Tracking Status" value="In Transit" />
                  <InfoRow label="Invoice Count" value="3 invoices" />
                  <InfoRow label="AWB PDF" value="Uploaded ✓" />
                </div>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>DHL Clearance</div>
                  <InfoRow label="Total Invoice CIF" value="EUR 1,280.00" />
                  <InfoRow label="FOB Value" value="EUR 1,150.00" />
                  <InfoRow label="Freight" value="EUR 95.00" />
                  <InfoRow label="Insurance" value="EUR 35.00" />
                  <InfoRow label="DHL Threshold" value="EUR 150 — Reply Required" />
                  <InfoRow label="DSK Recommendation" value="Standard DSK" />
                  <InfoRow label="DHL Email Status" value={dhlEmailReceived ? 'Received ✓' : 'Awaiting'} />
                </div>
              </div>
              <div style={{ padding: '0 20px 16px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Btn variant="outline" onClick={() => { setScanning(true); setTimeout(() => { setScanning(false); setDhlEmailReceived(true); notify('DHL inbox scanned — 1 email matched.'); }, 1500); }}>
                  {scanning ? '⟳ Scanning…' : '⌕ Scan DHL Inbox'}
                </Btn>
                <Btn variant="outline" onClick={() => { setDhlEmailReceived(true); notify('DHL email marked received.'); }}>✓ Mark DHL Email Received</Btn>
                <Btn variant="outline" onClick={() => simulateAction('Generate Polish Description')}>⊞ Generate Polish Customs Desc.</Btn>
                <Btn variant="outline" onClick={() => simulateAction('Generate DSK')}>⊟ Generate DSK</Btn>
                <Btn variant="outline" onClick={() => simulateAction('Build DHL Reply Package')}>⊡ Build DHL Reply Package</Btn>
                <Btn variant={replySent ? 'ghost' : 'gold'} disabled={!dhlEmailReceived || replySent} onClick={() => { setReplySent(true); notify('Reply sent to DHL.'); }}>
                  {replySent ? '✓ Reply Sent' : '↗ Send Reply to DHL'}
                </Btn>
              </div>
            </Card>

            {/* Section 2: Customs Documents */}
            <Card>
              <SectionHeader icon="⊟" title="Section 2 — Customs Documents" subtitle="SAD / ZC429 upload, customs values, MRN verification" status={sadUploaded ? 'SAD Uploaded' : 'SAD Pending'} />
              <div style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Document References</div>
                  <InfoRow label="SAD / ZC429 Status" value={sadUploaded ? 'Uploaded ✓' : 'Not uploaded'} />
                  <InfoRow label="MRN" value={shipment.mrn} mono />
                  <InfoRow label="LRN" value={sadUploaded ? 'LRN-20240427-001' : '—'} mono />
                  <InfoRow label="Clearance Date" value={sadUploaded ? '27 Apr 2024' : '—'} />
                  <InfoRow label="Customs Agent" value={sadUploaded ? 'Agencja Celna Sp. z o.o.' : '—'} />
                </div>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Values & Checks</div>
                  <InfoRow label="SAD Exchange Rate" value={sadUploaded ? 'EUR/PLN 4.2650' : '—'} />
                  <InfoRow label="NBP Accounting Rate" value={sadUploaded ? 'EUR/PLN 4.2510' : '—'} />
                  <InfoRow label="A00 Duty" value={sadUploaded ? 'PLN 282.00' : '—'} />
                  <InfoRow label="B00 VAT" value={sadUploaded ? 'PLN 1,254.60' : '—'} />
                  <InfoRow label="Art.33a / Import" value={sadUploaded ? 'Standard Import' : '—'} />
                </div>
              </div>

              {/* Verification checks */}
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

            {/* Section 3: PZ / Accounting */}
            <Card>
              <SectionHeader icon="⊞" title="Section 3 — PZ / Accounting" subtitle="Goods receipt document, wFirma export, and audit files" status={sadUploaded ? (pzGenerated ? 'Generated' : 'Ready for PZ') : 'Locked'} />

              {!sadUploaded ? (
                <div style={{ padding: 28, textAlign: 'center' }}>
                  <div style={{ fontSize: 32, marginBottom: 10 }}>🔒</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>PZ Locked</div>
                  <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Reason: SAD / ZC429 required before PZ generation</div>
                </div>
              ) : (
                <div style={{ padding: 20 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 16 }}>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>PZ Details</div>
                      <InfoRow label="PZ Status" value={pzGenerated ? 'Generated' : 'Ready for PZ'} />
                      <InfoRow label="PZ Number" value={pzNumber || '—'} mono />
                      <InfoRow label="Net Value" value={shipment.net} />
                      <InfoRow label="Gross Value" value={shipment.gross} />
                      <InfoRow label="Duty A00" value={shipment.duty} />
                    </div>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>wFirma</div>
                      <InfoRow label="wFirma Status" value={shipment.pzStatus === 'Exported' ? 'Exported ✓' : 'Not exported'} />
                      <InfoRow label="Export Date" value={shipment.pzStatus === 'Exported' ? '27 Apr 2024' : '—'} />
                    </div>
                  </div>

                  {/* Confirm PZ number */}
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

                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <Btn variant="gold" onClick={() => { setPzGenerated(true); notify('PZ generated successfully.'); }}>
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
                    <div style={{ display: 'flex', gap: 8, marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
                      <Btn variant="outline" onClick={() => notify('wFirma format copied to clipboard.')}>⊞ Copy wFirma Format</Btn>
                      <Btn variant="default" onClick={() => notify('Exported to wFirma successfully.')}>↗ Export to wFirma</Btn>
                    </div>
                  )}
                </div>
              )}
            </Card>
          </>
        )}

        {activeTab === 'Documents' && (
          <DocumentsTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} onNotify={notify} />
        )}

        {activeTab === 'Timeline' && (
          <TimelineTab shipment={shipment} sadUploaded={sadUploaded} pzGenerated={pzGenerated} replySent={replySent} />
        )}
      </div>
    </div>
  );
}

// ── Documents Tab

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
  const available = doc.status === 'uploaded' || doc.status === 'generated' && (pzGenerated || !doc.name.includes('PZ') && !doc.name.includes('Calc') && !doc.name.includes('Audit') && !doc.name.includes('Correction'));
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

// ── Timeline Tab

const TIMELINE_EVENTS = [
  { label: 'Shipment created', done: true, date: '10 Apr 2024, 09:12' },
  { label: 'Invoice uploaded', done: true, date: '10 Apr 2024, 09:15' },
  { label: 'AWB uploaded', done: true, date: '10 Apr 2024, 09:17' },
  { label: 'DHL pre-check completed', done: true, date: '10 Apr 2024, 09:20' },
  { label: 'DHL email received', done: null, date: null, key: 'dhlEmail' },
  { label: 'Polish description generated', done: null, date: null },
  { label: 'DSK generated', done: null, date: null },
  { label: 'Reply package prepared', done: null, date: null },
  { label: 'Reply sent to DHL', done: null, date: null, key: 'reply' },
  { label: 'SAD uploaded', done: null, date: null, key: 'sad' },
  { label: 'Customs parsed', done: null, date: null },
  { label: 'PZ unlocked', done: null, date: null, key: 'pzUnlock' },
  { label: 'PZ generated', done: null, date: null, key: 'pz' },
  { label: 'PZ number confirmed', done: null, date: null },
  { label: 'Exported to wFirma', done: null, date: null },
];

function TimelineTab({ shipment, sadUploaded, pzGenerated, replySent }) {
  const events = TIMELINE_EVENTS.map(e => {
    let done = e.done;
    if (e.key === 'dhlEmail' && (shipment.dhlStatus === 'DHL Email Received' || replySent)) done = true;
    if (e.key === 'reply' && replySent) done = true;
    if (e.key === 'sad' && sadUploaded) { done = true; }
    if (e.key === 'pzUnlock' && sadUploaded) done = true;
    if (e.key === 'pz' && pzGenerated) done = true;
    return { ...e, done };
  });

  return (
    <Card style={{ padding: 28 }}>
      <div style={{ position: 'relative', paddingLeft: 32 }}>
        <div style={{ position: 'absolute', left: 7, top: 0, bottom: 0, width: 2, background: 'var(--border)' }} />
        {events.map((e, i) => (
          <div key={i} style={{ position: 'relative', marginBottom: 20, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
            <div style={{
              position: 'absolute', left: -32,
              width: 16, height: 16, borderRadius: '50%',
              background: e.done ? GOLD : 'var(--card)',
              border: `2px solid ${e.done ? GOLD : 'var(--badge-neutral-border)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              zIndex: 1, top: 1,
            }}>
              {e.done && <span style={{ fontSize: 7, color: 'var(--text)' }}>✓</span>}
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
