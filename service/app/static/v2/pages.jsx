// All sidebar module pages

// ── Shared filtered shipment table used by multiple pages
function FilteredShipmentsTable({ filterFn, onViewShipment, emptyMsg }) {
  const rows = MOCK_SHIPMENTS.filter(filterFn || (() => true));
  if (!rows.length) return (
    <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-3)' }}>
      <div style={{ fontSize: 36, marginBottom: 10, opacity: 0.3 }}>⬡</div>
      <div style={{ fontSize: 13, fontWeight: 600 }}>{emptyMsg || 'No shipments'}</div>
    </div>
  );
  return (
    <Card style={{ overflow: 'hidden', marginTop: 16 }}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['AWB / Tracking', 'Carrier', 'Overall Status', 'Net Value', 'Gross Value', 'Duty A00', 'Actions'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <td style={{ padding: '10px 12px' }}>
                  <button onClick={() => onViewShipment(row)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--badge-blue-text)', fontSize: 12, fontWeight: 600, fontFamily: 'monospace', textDecoration: 'underline', textDecorationStyle: 'dotted' }}>{row.awb}</button>
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{ display: 'inline-block', padding: '1px 6px', background: row.carrier === 'DHL' ? 'var(--badge-blue-bg)' : row.carrier === 'FedEx' ? 'var(--badge-purple-bg)' : 'var(--badge-neutral-bg)', borderRadius: 4, fontSize: 10, fontWeight: 700, color: row.carrier === 'DHL' ? 'var(--badge-blue-text)' : row.carrier === 'FedEx' ? 'var(--badge-purple-text)' : 'var(--badge-neutral-text)' }}>{row.carrier}</span>
                </td>
                <td style={{ padding: '10px 12px' }}><Badge status={row.overall} small /></td>
                <td style={{ padding: '10px 12px', color: 'var(--text)', fontWeight: 500, textAlign: 'right' }}>{row.net}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text)', fontWeight: 500, textAlign: 'right' }}>{row.gross}</td>
                <td style={{ padding: '10px 12px', color: 'var(--accent)', fontWeight: 700, textAlign: 'right' }}>{row.duty}</td>
                <td style={{ padding: '10px 12px' }}><Btn small variant="outline" onClick={() => onViewShipment(row)}>View</Btn></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── DHL Clearance Page
function DhlClearancePage({ onViewShipment }) {
  const [scanning, setScanning] = React.useState(false);
  const [scanned, setScanned] = React.useState(false);

  const dhlShipments = MOCK_SHIPMENTS.filter(s => s.carrier === 'DHL');
  const awaitingReply = dhlShipments.filter(s => s.dhlStatus === 'Awaiting DHL Email' || s.dhlStatus === 'DHL Email Received');
  const replySent = dhlShipments.filter(s => s.dhlStatus === 'Reply Sent');
  const completed = dhlShipments.filter(s => s.dhlStatus === 'Pre-check Completed');

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Status summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Total DHL Shipments', value: dhlShipments.length, color: 'var(--text)' },
          { label: 'Awaiting Reply', value: awaitingReply.length, color: 'var(--badge-amber-text)' },
          { label: 'Reply Sent', value: replySent.length, color: 'var(--badge-blue-text)' },
          { label: 'Clearance Complete', value: completed.length, color: 'var(--badge-green-text)' },
        ].map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 6 }}>{c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: c.color, fontFamily: '"DM Serif Display", serif' }}>{c.value}</div>
          </Card>
        ))}
      </div>

      {/* Global actions */}
      <Card style={{ padding: '16px 20px', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>DHL Inbox</div>
        <Btn variant="outline" onClick={() => { setScanning(true); setTimeout(() => { setScanning(false); setScanned(true); }, 1500); }}>
          {scanning ? '⟳ Scanning…' : '⌕ Scan DHL Inbox'}
        </Btn>
        {scanned && <span style={{ fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ Inbox scanned — 2 emails matched</span>}
      </Card>

      {/* Pending reply */}
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Awaiting DHL Email / Reply Required</div>
      <FilteredShipmentsTable filterFn={s => s.dhlStatus === 'Awaiting DHL Email' || s.dhlStatus === 'DHL Email Received'} onViewShipment={onViewShipment} emptyMsg="No shipments awaiting DHL" />

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8, marginTop: 24 }}>All DHL Shipments</div>
      <FilteredShipmentsTable filterFn={s => s.carrier === 'DHL'} onViewShipment={onViewShipment} emptyMsg="No DHL shipments" />
    </div>
  );
}

// ── Customs Documents Page
function CustomsDocumentsPage({ onViewShipment }) {
  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'SAD Pending', value: MOCK_SHIPMENTS.filter(s => s.sadStatus === 'SAD Pending').length, color: 'var(--badge-amber-text)' },
          { label: 'SAD Uploaded', value: MOCK_SHIPMENTS.filter(s => s.sadStatus === 'SAD Uploaded').length, color: 'var(--badge-blue-text)' },
          { label: 'Customs Verified', value: MOCK_SHIPMENTS.filter(s => s.sadStatus === 'Customs Verified').length, color: 'var(--badge-green-text)' },
          { label: 'Verification Needed', value: MOCK_SHIPMENTS.filter(s => s.sadStatus === 'Verification Needed').length, color: 'var(--badge-red-text)' },
        ].map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 6 }}>{c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: c.color, fontFamily: '"DM Serif Display", serif' }}>{c.value}</div>
          </Card>
        ))}
      </div>

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Verification Needed</div>
      <FilteredShipmentsTable filterFn={s => s.sadStatus === 'Verification Needed'} onViewShipment={onViewShipment} emptyMsg="No shipments needing verification" />

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8, marginTop: 24 }}>SAD Pending Upload</div>
      <FilteredShipmentsTable filterFn={s => s.sadStatus === 'SAD Pending'} onViewShipment={onViewShipment} emptyMsg="No SAD pending" />

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8, marginTop: 24 }}>Customs Parsed / Verified</div>
      <FilteredShipmentsTable filterFn={s => s.sadStatus === 'Customs Parsed' || s.sadStatus === 'Customs Verified'} onViewShipment={onViewShipment} emptyMsg="None yet" />
    </div>
  );
}

// ── PZ / Accounting Page
function PzAccountingPage({ onViewShipment }) {
  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Locked (No SAD)', value: MOCK_SHIPMENTS.filter(s => s.pzStatus === 'Locked').length, color: 'var(--text-3)' },
          { label: 'Ready for PZ', value: MOCK_SHIPMENTS.filter(s => s.pzStatus === 'Ready for PZ').length, color: 'var(--badge-green-text)' },
          { label: 'PZ Generated', value: MOCK_SHIPMENTS.filter(s => s.pzStatus === 'Generated').length, color: 'var(--badge-blue-text)' },
          { label: 'Exported to wFirma', value: MOCK_SHIPMENTS.filter(s => s.pzStatus === 'Exported').length, color: 'var(--accent)' },
        ].map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 6 }}>{c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: c.color, fontFamily: '"DM Serif Display", serif' }}>{c.value}</div>
          </Card>
        ))}
      </div>

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Ready for PZ — Action Required</div>
      <FilteredShipmentsTable filterFn={s => s.pzStatus === 'Ready for PZ'} onViewShipment={onViewShipment} emptyMsg="No shipments ready for PZ" />

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8, marginTop: 24 }}>PZ Generated — Awaiting Booking</div>
      <FilteredShipmentsTable filterFn={s => s.pzStatus === 'Generated' || s.pzStatus === 'Ready for Booking'} onViewShipment={onViewShipment} emptyMsg="None yet" />

      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8, marginTop: 24 }}>Exported to wFirma</div>
      <FilteredShipmentsTable filterFn={s => s.pzStatus === 'Exported'} onViewShipment={onViewShipment} emptyMsg="None exported yet" />
    </div>
  );
}

// ── wFirma Export Page
function WfirmaExportPage({ onViewShipment }) {
  const [exported, setExported] = React.useState([
    { id: 'SHP-007', awb: 'FDX-9988776655', date: '27 Apr 2024', pz: 'PZ/2024/000891', net: 'PLN 6,330', gross: 'PLN 7,596', duty: 'PLN 380', status: 'Exported' },
  ]);
  const ready = MOCK_SHIPMENTS.filter(s => s.pzStatus === 'Generated');

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Ready to Export', value: ready.length, color: 'var(--badge-green-text)' },
          { label: 'Exported This Month', value: exported.length, color: 'var(--accent)' },
          { label: 'Total Duty Exported', value: 'PLN 380', color: 'var(--badge-blue-text)' },
        ].map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 6 }}>{c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: c.color, fontFamily: '"DM Serif Display", serif' }}>{c.value}</div>
          </Card>
        ))}
      </div>

      {/* Ready queue */}
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Ready for wFirma Export</div>
      <Card style={{ overflow: 'hidden' }}>
        {ready.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>No shipments ready for export</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['AWB', 'Net Value', 'Gross Value', 'Duty A00', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ready.map(row => (
                <tr key={row.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--badge-blue-text)' }}>{row.awb}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>{row.net}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>{row.gross}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--accent)', fontWeight: 700 }}>{row.duty}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Btn small variant="outline" onClick={() => onViewShipment(row)}>View</Btn>
                      <Btn small variant="gold" onClick={() => alert('Exported to wFirma!')}>↗ Export</Btn>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Export log */}
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8, marginTop: 24 }}>Export Log</div>
      <Card style={{ overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              {['AWB', 'Export Date', 'PZ Number', 'Net', 'Gross', 'Duty', 'Status'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {exported.map((row, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontWeight: 600 }}>{row.awb}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text-2)' }}>{row.date}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11 }}>{row.pz}</td>
                <td style={{ padding: '10px 12px', textAlign: 'right' }}>{row.net}</td>
                <td style={{ padding: '10px 12px', textAlign: 'right' }}>{row.gross}</td>
                <td style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--accent)', fontWeight: 700 }}>{row.duty}</td>
                <td style={{ padding: '10px 12px' }}><Badge status="Exported" small /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ── Learning / Parser Page
function LearningParserPage() {
  const [parserInput, setParserInput] = React.useState('');
  const [parserResult, setParserResult] = React.useState(null);
  const [parsing, setParsing] = React.useState(false);

  const runParser = () => {
    if (!parserInput.trim()) return;
    setParsing(true);
    setParserResult(null);
    setTimeout(() => {
      setParsing(false);
      setParserResult({
        mrn: 'PL' + Math.floor(Math.random() * 99999999999999).toString().padStart(14, '0') + 'X',
        lrn: 'LRN-' + new Date().getFullYear() + '-' + Math.floor(Math.random() * 9999).toString().padStart(4, '0'),
        clearanceDate: '27 Apr 2024',
        agent: 'Agencja Celna Sp. z o.o.',
        exchangeRate: '4.2650',
        nbpRate: '4.2510',
        a00Duty: (Math.random() * 500 + 100).toFixed(2),
        b00Vat: (Math.random() * 1500 + 500).toFixed(2),
        importType: 'Standard Import',
        status: 'Parsed successfully',
      });
    }, 1600);
  };

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* SAD Parser */}
        <Card>
          <SectionHeader icon="⊟" title="SAD / ZC429 Parser" subtitle="Test the customs document parser" />
          <div style={{ padding: 20 }}>
            <FormField label="Paste SAD text or upload PDF" hint="Parser extracts MRN, LRN, exchange rates, duty values">
              <textarea
                value={parserInput}
                onChange={e => setParserInput(e.target.value)}
                placeholder="Paste SAD / ZC429 document text here for testing…"
                rows={8}
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 6,
                  border: '1px solid var(--border)', fontSize: 11, color: 'var(--text)',
                  background: 'var(--bg-subtle)', outline: 'none', resize: 'vertical',
                  fontFamily: 'monospace', boxSizing: 'border-box',
                }}
              />
            </FormField>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn variant="gold" onClick={runParser} disabled={!parserInput.trim()}>
                {parsing ? '⟳ Parsing…' : '▶ Run Parser'}
              </Btn>
              <Btn variant="outline" onClick={() => { setParserInput(''); setParserResult(null); }}>Clear</Btn>
            </div>

            {parserResult && (
              <div style={{ marginTop: 16, padding: 14, background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 6 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-green-text)', marginBottom: 10 }}>✓ {parserResult.status}</div>
                {Object.entries(parserResult).filter(([k]) => k !== 'status').map(([k, v]) => (
                  <InfoRow key={k} label={k.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase())} value={v} mono={['mrn','lrn','exchangeRate','nbpRate'].includes(k)} />
                ))}
              </div>
            )}
          </div>
        </Card>

        {/* Invoice Parser */}
        <Card>
          <SectionHeader icon="📄" title="Invoice Parser" subtitle="Test invoice PDF extraction" />
          <div style={{ padding: 20 }}>
            <FormField label="Upload invoice PDF for test parsing">
              <label style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '32px 16px', borderRadius: 6,
                border: '2px dashed var(--badge-neutral-border)', cursor: 'pointer',
                background: 'var(--bg-subtle)', justifyContent: 'center', flexDirection: 'column',
              }}>
                <input type="file" accept=".pdf" style={{ display: 'none' }} onChange={() => alert('Invoice parser: file uploaded. Results would appear here.')} />
                <span style={{ fontSize: 28, opacity: 0.4 }}>📄</span>
                <span style={{ fontSize: 12, color: 'var(--text-2)' }}>Click to upload invoice PDF</span>
              </label>
            </FormField>
            <div style={{ marginTop: 12, padding: 12, background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-amber-text)' }}>
              ℹ Invoice parser logic is fixed — values are extracted as-is. No rounding or formula changes.
            </div>
          </div>
        </Card>

        {/* Parser rules */}
        <Card style={{ gridColumn: 'span 2' }}>
          <SectionHeader icon="⊞" title="Parser Rules &amp; Locked Formulas" subtitle="These rules are fixed and cannot be changed from this UI" />
          <div style={{ padding: 20 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
              {[
                { rule: 'PZ Calculation', desc: 'Fixed. Uses SAD net value × carrier exchange rate.', locked: true },
                { rule: 'Duty Formula (A00)', desc: 'Fixed. Customs tariff × CIF value.', locked: true },
                { rule: 'VAT Formula (B00)', desc: 'Fixed. (CIF + A00) × VAT rate (23%).', locked: true },
                { rule: 'SAD Parser Logic', desc: 'Regex + positional extraction. Read-only.', locked: true },
                { rule: 'Invoice Parser', desc: 'PDF text extraction. Field mapping locked.', locked: true },
                { rule: 'DHL Auto-send', desc: 'Disabled. Admin must approve all DHL replies.', locked: true },
              ].map((r, i) => (
                <div key={i} style={{ padding: 12, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text)' }}>{r.rule}</span>
                    <span style={{ fontSize: 10, color: 'var(--badge-red-text)', fontWeight: 700 }}>🔒 Locked</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-2)' }}>{r.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

// ── Admin / Settings Page
function AdminSettingsPage() {
  const [apiUrl, setApiUrl] = React.useState('https://api.estrella-pz.pl/api/v1');
  const [dhlEmail, setDhlEmail] = React.useState('clearance@dhl.com.pl');
  const [wfirmaKey, setWfirmaKey] = React.useState('wf_••••••••••••••••');
  const [saved, setSaved] = React.useState(false);

  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* API Config */}
        <Card>
          <SectionHeader icon="⚙" title="API Configuration" />
          <div style={{ padding: 20 }}>
            <FormField label="Backend API Base URL">
              <Input value={apiUrl} onChange={e => setApiUrl(e.target.value)} />
            </FormField>
            <FormField label="DHL Clearance Email Address">
              <Input value={dhlEmail} onChange={e => setDhlEmail(e.target.value)} />
            </FormField>
            <FormField label="wFirma API Key">
              <Input value={wfirmaKey} onChange={e => setWfirmaKey(e.target.value)} type="password" />
            </FormField>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Btn variant="gold" onClick={save}>Save Settings</Btn>
              {saved && <span style={{ fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ Saved</span>}
            </div>
          </div>
        </Card>

        {/* User management */}
        <Card>
          <SectionHeader icon="◎" title="Users &amp; Roles" />
          <div style={{ padding: 20 }}>
            {[
              { name: 'Admin', email: 'admin@estrella.pl', role: 'Super User', active: true },
              { name: 'Karolina', email: 'k.nowak@estrella.pl', role: 'Accountant', active: true },
              { name: 'Marek', email: 'm.kowalski@estrella.pl', role: 'Logistics', active: false },
            ].map((u, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{
                  width: 32, height: 32, borderRadius: '50%',
                  background: u.active ? `linear-gradient(135deg, ${GOLD}, #E8C870)` : 'var(--border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 12, fontWeight: 700, color: u.active ? 'var(--text)' : 'var(--text-3)',
                }}>{u.name[0]}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{u.name}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-2)' }}>{u.email} · {u.role}</div>
                </div>
                <span style={{ fontSize: 10, color: u.active ? 'var(--badge-green-text)' : 'var(--text-3)', fontWeight: 600 }}>{u.active ? '● Active' : '○ Inactive'}</span>
              </div>
            ))}
            <div style={{ marginTop: 12 }}>
              <Btn variant="outline" small>+ Invite User</Btn>
            </div>
          </div>
        </Card>

        {/* System info */}
        <Card style={{ gridColumn: 'span 2' }}>
          <SectionHeader icon="▦" title="System Status" />
          <div style={{ padding: 20, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            {[
              { label: 'API Status', value: '● Online', color: 'var(--badge-green-text)' },
              { label: 'DHL Inbox Connector', value: '● Connected', color: 'var(--badge-green-text)' },
              { label: 'wFirma Integration', value: '● Active', color: 'var(--badge-green-text)' },
              { label: 'Last Sync', value: '27 Apr 2024, 14:32', color: 'var(--text)' },
            ].map((s, i) => (
              <div key={i} style={{ padding: 12, borderRadius: 6, background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 4 }}>{s.label}</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: s.color }}>{s.value}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ── Warehouse / Stock Page
function WarehousePage({ onViewShipment }) {
  const [tab, setTab] = React.useState('stock');

  const stockItems = [
    { sku: 'EJ-RING-0142', name: 'Diamond Solitaire Ring 0.5ct',  category: 'Rings',     onHand: 24, reserved: 4,  available: 20, pz: 'PZ/2024/001234', batch: 'B-2024-04-01', value: 'PLN 38,400' },
    { sku: 'EJ-NECK-0089', name: 'Gold Pendant Chain 18k',         category: 'Necklaces', onHand: 12, reserved: 2,  available: 10, pz: 'PZ/2024/001234', batch: 'B-2024-04-01', value: 'PLN 14,640' },
    { sku: 'EJ-BRAC-0211', name: 'Tennis Bracelet Sapphire',       category: 'Bracelets', onHand: 6,  reserved: 6,  available: 0,  pz: 'PZ/2024/001230', batch: 'B-2024-04-02', value: 'PLN 21,300' },
    { sku: 'EJ-EARR-0357', name: 'Pearl Drop Earrings',            category: 'Earrings',  onHand: 38, reserved: 0,  available: 38, pz: 'PZ/2024/001228', batch: 'B-2024-03-22', value: 'PLN 11,400' },
    { sku: 'EJ-RING-0098', name: 'Engagement Ring 1.0ct Platinum', category: 'Rings',     onHand: 3,  reserved: 1,  available: 2,  pz: 'PZ/2024/001225', batch: 'B-2024-03-15', value: 'PLN 24,750' },
  ];

  const receipts = [
    { pz: 'PZ/2024/001234', date: '27 Apr 2024', awb: 'DHL-1234567890', pieces: 47, value: 'PLN 53,040', status: 'Received' },
    { pz: 'PZ/2024/001230', date: '24 Apr 2024', awb: 'DHL-1234567884', pieces: 32, value: 'PLN 28,200', status: 'Received' },
    { pz: 'PZ/2024/001228', date: '22 Apr 2024', awb: 'FDX-9988776655', pieces: 76, value: 'PLN 18,400', status: 'Received' },
    { pz: 'PZ/2024/001225', date: '15 Apr 2024', awb: 'DHL-1234567851', pieces: 8,  value: 'PLN 49,500', status: 'Received' },
  ];

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
        {[
          { label: 'Total SKUs',       value: '1,284' },
          { label: 'Units on hand',    value: '4,712' },
          { label: 'Stock value',      value: 'PLN 2.41M' },
          { label: 'Pending receipts', value: '3' },
        ].map(s => (
          <div key={s.label} style={{
            background: 'var(--card)', border: '1px solid var(--border)',
            borderRadius: 10, padding: '16px 18px', boxShadow: '0 1px 2px var(--shadow)',
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>{s.label}</div>
            <div style={{ fontSize: 22, fontWeight: 600, color: 'var(--text)' }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {[
          { id: 'stock',     label: 'Stock Levels' },
          { id: 'receipts',  label: 'Goods Receipts' },
          { id: 'batches',   label: 'Batches / Traceability' },
          { id: 'tempImp',   label: 'Temp Import' },
          { id: 'tempExp',   label: 'Temp Export' },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${tab === t.id ? 'var(--accent)' : 'transparent'}`,
            color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 13, fontWeight: tab === t.id ? 700 : 500, marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'stock' && (
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['SKU', 'Item', 'Category', 'On hand', 'Reserved', 'Available', 'Source PZ', 'Batch', 'Stock value', ''].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stockItems.map(it => (
                <tr key={it.sku} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{it.sku}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 500 }}>{it.name}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{it.category}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{it.onHand}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{it.reserved}</td>
                  <td style={{ padding: '12px 14px', color: it.available === 0 ? 'var(--badge-red-text)' : 'var(--badge-green-text)', fontWeight: 600 }}>{it.available}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'monospace', color: 'var(--text-2)' }}>{it.pz}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'monospace', color: 'var(--text-2)' }}>{it.batch}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{it.value}</td>
                  <td style={{ padding: '12px 14px' }}><Btn small variant="outline">View</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'receipts' && (
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['PZ Number', 'Receipt date', 'AWB', 'Pieces', 'Value', 'Status', ''].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {receipts.map(r => (
                <tr key={r.pz} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{r.pz}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{r.date}</td>
                  <td style={{ padding: '12px 14px', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.awb}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{r.pieces}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{r.value}</td>
                  <td style={{ padding: '12px 14px' }}><Badge status="Received" /></td>
                  <td style={{ padding: '12px 14px' }}><Btn small variant="outline" onClick={() => onViewShipment && onViewShipment({ awb: r.awb })}>Open shipment</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'batches' && (
        <Card>
          <div style={{ padding: 20 }}>
            <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>
              Each goods receipt creates an immutable batch tied to its source PZ document.
              Click any batch ID below to trace its origin (AWB → SAD → PZ) and current stock distribution.
            </div>
            <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
              {receipts.map(r => (
                <div key={r.pz} style={{
                  border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px',
                  background: 'var(--bg-subtle)',
                }}>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>Batch · {r.date.replace(/\s/g, '-')}</div>
                  <div style={{ fontSize: 13, fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>B-2024-{r.pz.slice(-4)}</div>
                  <InfoRow label="Source PZ" value={r.pz} mono />
                  <InfoRow label="AWB"        value={r.awb} mono />
                  <InfoRow label="Pieces"     value={r.pieces} />
                  <InfoRow label="Value"      value={r.value} />
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
      {tab === 'tempImp' && (
        <Card>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Temporary Import</div>
              <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>Goods admitted under temporary import procedure (ATA Carnet, IM5, exhibitions, repairs). Must be re-exported by deadline.</div>
            </div>
            <Btn variant="gold" small>+ New Temp Import</Btn>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['Ref', 'Carnet / MRN', 'Description', 'Pieces', 'Value', 'Entry date', 'Re-export deadline', 'Days left', 'Status', ''].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { ref: 'TI-2024-0012', mrn: 'ATA-PL-2024-0089', desc: 'Trade show samples — Vicenza Oro',     pieces: 24, value: 'EUR 18,400', entry: '12 Apr 2024', deadline: '12 Jul 2024', daysLeft: 66, status: 'Active' },
                { ref: 'TI-2024-0011', mrn: 'IM5-2024-001245',  desc: 'Repair return — Patek Philippe watch', pieces: 1,  value: 'EUR 42,000', entry: '03 Apr 2024', deadline: '03 Jun 2024', daysLeft: 27, status: 'Active' },
                { ref: 'TI-2024-0010', mrn: 'ATA-PL-2024-0072', desc: 'Exhibition pieces — Munich Time',      pieces: 8,  value: 'EUR 124,500', entry: '18 Mar 2024', deadline: '18 May 2024', daysLeft: 11, status: 'Closing soon' },
                { ref: 'TI-2024-0009', mrn: 'IM5-2024-001112',  desc: 'Stone setting samples',                pieces: 36, value: 'EUR 7,200',  entry: '02 Mar 2024', deadline: '02 May 2024', daysLeft: -5, status: 'Overdue' },
                { ref: 'TI-2024-0008', mrn: 'ATA-PL-2024-0061', desc: 'Inhorgenta show samples',              pieces: 18, value: 'EUR 22,800', entry: '08 Feb 2024', deadline: '08 Apr 2024', daysLeft: null, status: 'Re-exported' },
              ].map(r => {
                const overdue = r.daysLeft !== null && r.daysLeft < 0;
                const closing = r.daysLeft !== null && r.daysLeft >= 0 && r.daysLeft <= 14;
                return (
                  <tr key={r.ref} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{r.ref}</td>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.mrn}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)' }}>{r.desc}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{r.pieces}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{r.value}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{r.entry}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{r.deadline}</td>
                    <td style={{ padding: '12px 14px', color: overdue ? 'var(--badge-red-text)' : closing ? 'var(--badge-amber-text)' : 'var(--text-2)', fontWeight: 600 }}>
                      {r.daysLeft === null ? '—' : (r.daysLeft < 0 ? `${Math.abs(r.daysLeft)} overdue` : `${r.daysLeft} days`)}
                    </td>
                    <td style={{ padding: '12px 14px' }}><Badge status={r.status === 'Active' ? 'In Transit' : r.status === 'Closing soon' ? 'Pre-check Pending' : r.status === 'Overdue' ? 'Verification Needed' : 'Pre-check Completed'} /></td>
                    <td style={{ padding: '12px 14px' }}><Btn small variant="outline">Re-export</Btn></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'tempExp' && (
        <Card>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Temporary Export</div>
              <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>Goods sent abroad temporarily (EX2, ATA outbound) — exhibitions, repair, certification. Must be re-imported by deadline.</div>
            </div>
            <Btn variant="gold" small>+ New Temp Export</Btn>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['Ref', 'Carnet / MRN', 'Destination', 'Description', 'Pieces', 'Value', 'Export date', 'Return deadline', 'Days left', 'Status', ''].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { ref: 'TE-2024-0021', mrn: 'EX2-PL-2024-0312', dest: 'Vicenza, IT',     desc: 'Showcase pieces — Vicenza Oro', pieces: 36, value: 'EUR 84,200',  exp: '08 Apr 2024', deadline: '08 Jul 2024', daysLeft: 62, status: 'Active' },
                { ref: 'TE-2024-0020', mrn: 'ATA-PL-2024-0091', dest: 'Geneva, CH',     desc: 'GIA certification — diamonds',  pieces: 12, value: 'EUR 156,000', exp: '21 Mar 2024', deadline: '21 May 2024', daysLeft: 14, status: 'Closing soon' },
                { ref: 'TE-2024-0019', mrn: 'EX2-PL-2024-0298', dest: 'Antwerp, BE',    desc: 'Stone re-cutting',              pieces: 6,  value: 'EUR 28,400',  exp: '14 Mar 2024', deadline: '14 May 2024', daysLeft: 7,  status: 'Closing soon' },
                { ref: 'TE-2024-0018', mrn: 'EX2-PL-2024-0271', dest: 'Las Vegas, US',  desc: 'JCK trade show samples',        pieces: 24, value: 'EUR 64,800',  exp: '01 Mar 2024', deadline: '15 Apr 2024', daysLeft: -22, status: 'Overdue' },
                { ref: 'TE-2024-0017', mrn: 'ATA-PL-2024-0058', dest: 'Basel, CH',      desc: 'Baselworld samples',            pieces: 18, value: 'EUR 41,200',  exp: '12 Feb 2024', deadline: '12 Apr 2024', daysLeft: null, status: 'Returned' },
              ].map(r => {
                const overdue = r.daysLeft !== null && r.daysLeft < 0;
                const closing = r.daysLeft !== null && r.daysLeft >= 0 && r.daysLeft <= 14;
                return (
                  <tr key={r.ref} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{r.ref}</td>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.mrn}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{r.dest}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)' }}>{r.desc}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{r.pieces}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{r.value}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{r.exp}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{r.deadline}</td>
                    <td style={{ padding: '12px 14px', color: overdue ? 'var(--badge-red-text)' : closing ? 'var(--badge-amber-text)' : 'var(--text-2)', fontWeight: 600 }}>
                      {r.daysLeft === null ? '—' : (r.daysLeft < 0 ? `${Math.abs(r.daysLeft)} overdue` : `${r.daysLeft} days`)}
                    </td>
                    <td style={{ padding: '12px 14px' }}><Badge status={r.status === 'Active' ? 'In Transit' : r.status === 'Closing soon' ? 'Pre-check Pending' : r.status === 'Overdue' ? 'Verification Needed' : 'Pre-check Completed'} /></td>
                    <td style={{ padding: '12px 14px' }}><Btn small variant="outline">Re-import</Btn></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// ── Sales / Proforma Page
function SalesProformaPage({ onGoToWfirma }) {
  const [tab, setTab] = React.useState('list');
  const [showNew, setShowNew] = React.useState(false);

  const proformas = [
    { id: 'PF-2024-0042', client: 'Goldsmith & Co. (UK)',     date: '28 Apr 2024', valid: '28 May 2024', items: 12, net: 'EUR 18,400', vat: 'EUR 4,232', gross: 'EUR 22,632', currency: 'EUR', status: 'Sent',      wfirma: 'Exported',     extDoc: 'WF-2024-04-PF-0042' },
    { id: 'PF-2024-0041', client: 'Maison Aurélie (FR)',      date: '27 Apr 2024', valid: '27 May 2024', items: 6,  net: 'EUR 9,200',  vat: 'EUR 2,116', gross: 'EUR 11,316', currency: 'EUR', status: 'Accepted',  wfirma: 'Pending',      extDoc: '—' },
    { id: 'PF-2024-0040', client: 'Estrella Boutique Warsaw', date: '25 Apr 2024', valid: '25 May 2024', items: 24, net: 'PLN 84,200', vat: 'PLN 19,366', gross: 'PLN 103,566', currency: 'PLN', status: 'Draft',     wfirma: 'Not exported', extDoc: '—' },
    { id: 'PF-2024-0039', client: 'Diamond Trade DMCC (AE)',  date: '23 Apr 2024', valid: '07 May 2024', items: 8,  net: 'USD 42,500', vat: 'USD 0',     gross: 'USD 42,500', currency: 'USD', status: 'Sent',      wfirma: 'Pending',      extDoc: '—' },
    { id: 'PF-2024-0038', client: 'Bijoux Lumière (BE)',      date: '21 Apr 2024', valid: '21 May 2024', items: 18, net: 'EUR 12,800', vat: 'EUR 2,944', gross: 'EUR 15,744', currency: 'EUR', status: 'Expired',   wfirma: '—',            extDoc: '—' },
    { id: 'PF-2024-0037', client: 'Goldsmith & Co. (UK)',     date: '18 Apr 2024', valid: '18 May 2024', items: 14, net: 'EUR 22,100', vat: 'EUR 5,083', gross: 'EUR 27,183', currency: 'EUR', status: 'Converted', wfirma: 'Exported',     extDoc: 'WF-2024-04-PF-0037' },
  ];

  const statusFor = (s) => s === 'Sent' ? 'In Transit' : s === 'Accepted' ? 'Pre-check Completed' : s === 'Draft' ? 'Draft' : s === 'Expired' ? 'Verification Needed' : s === 'Converted' ? 'Pre-check Completed' : 'Draft';
  const wfirmaBadge = (w) => w === 'Exported' ? 'Pre-check Completed' : w === 'Pending' ? 'Pre-check Pending' : w === 'Not exported' ? 'Draft' : 'Draft';

  const totals = {
    drafts:    proformas.filter(p => p.status === 'Draft').length,
    sent:      proformas.filter(p => p.status === 'Sent' || p.status === 'Accepted').length,
    converted: proformas.filter(p => p.status === 'Converted').length,
    pendingWf: proformas.filter(p => p.wfirma === 'Pending').length,
  };

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Stat tiles */}
      <div className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
        {[
          { label: 'Drafts',           value: totals.drafts,    accent: 'var(--text-2)' },
          { label: 'Sent / Accepted',  value: totals.sent,      accent: 'var(--badge-blue-text)' },
          { label: 'Converted',        value: totals.converted, accent: 'var(--badge-green-text)' },
          { label: 'Awaiting wFirma',  value: totals.pendingWf, accent: 'var(--badge-amber-text)' },
        ].map(s => (
          <div key={s.label} style={{
            background: 'var(--card)', border: '1px solid var(--border)',
            borderRadius: 10, padding: '16px 18px', boxShadow: '0 1px 2px var(--shadow)',
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>{s.label}</div>
            <div style={{ fontSize: 22, fontWeight: 600, color: s.accent }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[
            { id: 'list',     label: 'All Proformas' },
            { id: 'pipeline', label: 'Pipeline' },
            { id: 'wfirma',   label: 'wFirma Sync' },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer',
              borderBottom: `2px solid ${tab === t.id ? 'var(--accent)' : 'transparent'}`,
              color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
              fontSize: 13, fontWeight: tab === t.id ? 700 : 500, marginBottom: -1,
            }}>{t.label}</button>
          ))}
        </div>
        <div style={{ paddingBottom: 8 }}>
          <Btn variant="gold" small onClick={() => setShowNew(true)}>+ New Proforma</Btn>
        </div>
      </div>

      {tab === 'list' && (
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {['Proforma', 'Client', 'Date', 'Valid until', 'Items', 'Net', 'VAT', 'Gross', 'Status', 'wFirma', ''].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {proformas.map(p => (
                <tr key={p.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{p.id}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 500 }}>{p.client}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.date}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.valid}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 600 }}>{p.items}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.net}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.vat}</td>
                  <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 700 }}>{p.gross}</td>
                  <td style={{ padding: '12px 14px' }}><Badge status={statusFor(p.status)} /></td>
                  <td style={{ padding: '12px 14px' }}>
                    {p.wfirma === 'Exported'
                      ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 600 }}>✓ Exported</span>
                      : p.wfirma === 'Pending'
                        ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--badge-amber-text)', fontWeight: 600 }}>⏱ Pending</span>
                        : <span style={{ fontSize: 11, color: 'var(--text-3)' }}>—</span>
                    }
                  </td>
                  <td style={{ padding: '12px 14px', display: 'flex', gap: 6 }}>
                    <Btn small variant="outline">View</Btn>
                    {p.wfirma === 'Pending' && <Btn small variant="gold" onClick={onGoToWfirma}>↗ Export</Btn>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'pipeline' && (
        <div className="responsive-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
          {[
            { label: 'Draft',     items: proformas.filter(p => p.status === 'Draft'),     color: 'var(--text-2)' },
            { label: 'Sent',      items: proformas.filter(p => p.status === 'Sent'),      color: 'var(--badge-blue-text)' },
            { label: 'Accepted',  items: proformas.filter(p => p.status === 'Accepted' || p.status === 'Converted'), color: 'var(--badge-green-text)' },
            { label: 'Expired',   items: proformas.filter(p => p.status === 'Expired'),   color: 'var(--badge-red-text)' },
          ].map(col => (
            <div key={col.label} style={{
              background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
              boxShadow: '0 1px 2px var(--shadow)', overflow: 'hidden',
            }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: col.color, letterSpacing: '0.10em', textTransform: 'uppercase' }}>{col.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600 }}>{col.items.length}</div>
              </div>
              <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 8, minHeight: 200 }}>
                {col.items.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-3)', textAlign: 'center', padding: 20 }}>No items</div>}
                {col.items.map(p => (
                  <div key={p.id} style={{
                    border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px',
                    background: 'var(--bg-subtle)', cursor: 'pointer',
                  }}>
                    <div style={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{p.id}</div>
                    <div style={{ fontSize: 12, color: 'var(--text)', fontWeight: 500, marginBottom: 6 }}>{p.client}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{p.date}</span>
                      <span style={{ fontWeight: 700, color: 'var(--text)' }}>{p.gross}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'wfirma' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Pending wFirma export</div>
                <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>Accepted proformas not yet pushed to wFirma. Map fields and queue export.</div>
              </div>
              <Btn variant="gold" small onClick={onGoToWfirma}>Export all → wFirma</Btn>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                  {['Proforma', 'Client', 'Currency', 'Net', 'Gross', 'Field mapping', 'Queue position', ''].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {proformas.filter(p => p.wfirma === 'Pending').map((p, i) => (
                  <tr key={p.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{p.id}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)' }}>{p.client}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.currency}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.net}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 700 }}>{p.gross}</td>
                    <td style={{ padding: '12px 14px' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 600 }}>
                        ✓ Mapped (12/12)
                      </span>
                    </td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)', fontFamily: 'monospace' }}>#{i + 1}</td>
                    <td style={{ padding: '12px 14px' }}>
                      <Btn small variant="gold" onClick={onGoToWfirma}>↗ Export now</Btn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Recently exported</div>
              <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>Confirmed in wFirma with external document IDs.</div>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                  {['Proforma', 'Client', 'Gross', 'External Doc ID', 'Exported on', ''].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {proformas.filter(p => p.wfirma === 'Exported').map(p => (
                  <tr key={p.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{p.id}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)' }}>{p.client}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text)', fontWeight: 700 }}>{p.gross}</td>
                    <td style={{ padding: '12px 14px', fontFamily: 'monospace', color: 'var(--badge-green-text)', fontWeight: 600 }}>{p.extDoc}</td>
                    <td style={{ padding: '12px 14px', color: 'var(--text-2)' }}>{p.date}</td>
                    <td style={{ padding: '12px 14px' }}><Btn small variant="outline">View in wFirma →</Btn></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {showNew && (
        <Modal title="New Proforma" onClose={() => setShowNew(false)} actions={
          <>
            <Btn variant="outline" onClick={() => setShowNew(false)}>Cancel</Btn>
            <Btn variant="gold" onClick={() => setShowNew(false)}>Save as Draft</Btn>
          </>
        }>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <FormField label="Client">
              <Select>
                <option>Goldsmith &amp; Co. (UK)</option>
                <option>Maison Aurélie (FR)</option>
                <option>Estrella Boutique Warsaw</option>
                <option>Diamond Trade DMCC (AE)</option>
                <option>+ Add new client…</option>
              </Select>
            </FormField>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <FormField label="Currency">
                <Select><option>EUR</option><option>PLN</option><option>USD</option></Select>
              </FormField>
              <FormField label="Valid for">
                <Select><option>30 days</option><option>14 days</option><option>60 days</option></Select>
              </FormField>
            </div>
            <FormField label="Items source">
              <Select>
                <option>Pick from warehouse stock</option>
                <option>Manual line items</option>
                <option>Copy from previous proforma…</option>
              </Select>
            </FormField>
            <FormField label="Auto-export to wFirma when accepted">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
                <input type="checkbox" defaultChecked id="autoexp" style={{ accentColor: 'var(--accent)' }} />
                <label htmlFor="autoexp" style={{ fontSize: 12, color: 'var(--text-2)' }}>Push to wFirma immediately on status change to "Accepted"</label>
              </div>
            </FormField>
          </div>
        </Modal>
      )}
    </div>
  );
}

Object.assign(window, {
  DhlClearancePage,
  CustomsDocumentsPage,
  PzAccountingPage,
  WarehousePage,
  SalesProformaPage,
  WfirmaExportPage,
  LearningParserPage,
  AdminSettingsPage,
  FilteredShipmentsTable,
});
