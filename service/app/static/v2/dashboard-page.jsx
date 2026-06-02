// Dashboard Page — summary cards + shipment table

const MOCK_SHIPMENTS = [
  { id: 'SHP-001', awb: 'DHL-1234567890', carrier: 'DHL', dhlStatus: 'DHL Email Received', dhlRec: 'Reply Required', sadStatus: 'SAD Uploaded', mrn: 'PL12345678901234A', pzStatus: 'Ready for PZ', net: 'PLN 4,820', gross: 'PLN 5,640', duty: 'PLN 282', overall: 'Ready for PZ' },
  { id: 'SHP-002', awb: 'DHL-9876543210', carrier: 'DHL', dhlStatus: 'Awaiting DHL Email', dhlRec: 'Pending', sadStatus: 'SAD Pending', mrn: '—', pzStatus: 'Locked', net: 'PLN 3,100', gross: 'PLN 3,720', duty: '—', overall: 'Awaiting DHL' },
  { id: 'SHP-003', awb: 'FDX-0011223344', carrier: 'FedEx', dhlStatus: 'Pre-check Completed', dhlRec: 'No Reply Needed', sadStatus: 'Customs Verified', mrn: 'PL98765432101234B', pzStatus: 'Generated', net: 'PLN 7,250', gross: 'PLN 8,700', duty: 'PLN 435', overall: 'Ready for Booking' },
  { id: 'SHP-004', awb: 'DHL-5544332211', carrier: 'DHL', dhlStatus: 'Reply Sent', dhlRec: 'Completed', sadStatus: 'Verification Needed', mrn: 'PL11223344556677C', pzStatus: 'Locked', net: 'PLN 2,400', gross: 'PLN 2,880', duty: '—', overall: 'Action Required' },
  { id: 'SHP-005', awb: 'DHL-6677889900', carrier: 'DHL', dhlStatus: 'Pre-check Pending', dhlRec: '—', sadStatus: 'SAD Pending', mrn: '—', pzStatus: 'Locked', net: '—', gross: '—', duty: '—', overall: 'In Preparation' },
  { id: 'SHP-006', awb: 'OTH-1122334455', carrier: 'Other', dhlStatus: 'Pre-check Completed', dhlRec: 'No Reply Needed', sadStatus: 'Customs Parsed', mrn: 'PL22334455667788D', pzStatus: 'Ready for PZ', net: 'PLN 9,100', gross: 'PLN 10,920', duty: 'PLN 546', overall: 'Ready for PZ' },
  { id: 'SHP-007', awb: 'FDX-9988776655', carrier: 'FedEx', dhlStatus: 'Pre-check Completed', dhlRec: 'No Reply Needed', sadStatus: 'Customs Verified', mrn: 'PL33445566778899E', pzStatus: 'Exported', net: 'PLN 6,330', gross: 'PLN 7,596', duty: 'PLN 380', overall: 'Exported' },
];

const SUMMARY_CARDS = [
  { label: 'Total Shipments', value: 7, icon: '⬡', colorVar: 'var(--text)' },
  { label: 'Awaiting DHL', value: 1, icon: '✈', colorVar: 'var(--badge-amber-text)' },
  { label: 'Awaiting SAD', value: 2, icon: '⊟', colorVar: 'var(--badge-orange-text)' },
  { label: 'Ready for PZ', value: 2, icon: '◈', colorVar: 'var(--badge-green-text)' },
  { label: 'Verification Needed', value: 1, icon: '⚠', colorVar: 'var(--badge-red-text)' },
  { label: 'Ready for Booking', value: 1, icon: '✓', colorVar: 'var(--badge-purple-text)' },
  { label: 'Total Duty A00', value: 'PLN 1,643', icon: '₤', colorVar: 'var(--accent)', wide: true },
  { label: 'Total Gross Value', value: 'PLN 45,456', icon: '◈', colorVar: 'var(--badge-blue-text)', wide: true },
];

function DashboardPage({ onViewShipment }) {
  const [filter, setFilter] = React.useState('all');
  const [sortCol, setSortCol] = React.useState(null);
  const [sortDir, setSortDir] = React.useState('asc');
  const [actionMenu, setActionMenu] = React.useState(null);

  const overallFilters = ['all', 'Ready for PZ', 'Awaiting DHL', 'Awaiting SAD', 'Action Required', 'Ready for Booking', 'Exported'];
  const filtered = filter === 'all' ? MOCK_SHIPMENTS : MOCK_SHIPMENTS.filter(s => s.overall === filter);

  const handleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const TH = ({ col, children }) => (
    <th onClick={() => handleSort(col)} style={{
      padding: '10px 12px', textAlign: 'left', fontSize: 10,
      fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em',
      textTransform: 'uppercase', cursor: 'pointer', whiteSpace: 'nowrap',
      borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)',
      userSelect: 'none',
    }}>
      {children} {sortCol === col ? (sortDir === 'asc' ? '↑' : '↓') : ''}
    </th>
  );

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', flex: 1 }}>

      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 28 }}>
        {SUMMARY_CARDS.map((c, i) => (
          <Card key={i} style={{ padding: '16px 18px', cursor: 'pointer' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 500, marginBottom: 6 }}>{c.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: c.colorVar, fontFamily: '"DM Serif Display", serif' }}>{c.value}</div>
              </div>
              <div style={{
                width: 30, height: 30, borderRadius: 6,
                background: 'var(--accent-subtle)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 14, color: c.colorVar,
              }}>{c.icon}</div>
            </div>
          </Card>
        ))}
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: '#8A8278', marginRight: 4 }}>Filter:</span>
        {overallFilters.map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            padding: '4px 10px', borderRadius: 20,
            border: filter === f ? `1px solid ${GOLD}` : '1px solid #E4DDD2',
            background: filter === f ? GOLD + '22' : 'transparent',
            color: filter === f ? '#18160F' : '#6A6258',
            fontSize: 11, fontWeight: filter === f ? 600 : 400, cursor: 'pointer',
          }}>{f === 'all' ? 'All' : f}</button>
        ))}
      </div>

      {/* Table */}
      <Card style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                <TH col="awb">AWB / Tracking</TH>
                <TH col="carrier">Carrier</TH>
                <TH col="dhlStatus">DHL Status</TH>
                <TH col="dhlRec">DHL Rec.</TH>
                <TH col="sadStatus">SAD Status</TH>
                <TH col="mrn">MRN</TH>
                <TH col="pzStatus">PZ Status</TH>
                <TH col="net">Net Value</TH>
                <TH col="gross">Gross Value</TH>
                <TH col="duty">Duty A00</TH>
                <TH col="overall">Overall</TH>
                <th style={{ padding: '10px 12px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)', background: '#FAFAF8' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, i) => (
                <tr key={row.id}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  style={{ borderBottom: '1px solid var(--border-subtle)', transition: 'background 0.1s' }}
                >
                  <td style={{ padding: '10px 12px' }}>
                    <button onClick={() => onViewShipment(row)} style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      color: '#1A5FA8', fontSize: 12, fontWeight: 600,
                      fontFamily: 'monospace', textDecoration: 'underline',
                      textDecorationStyle: 'dotted',
                    }}>{row.awb}</button>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#18160F' }}>
                    <span style={{
                      display: 'inline-block', padding: '1px 6px',
                      background: row.carrier === 'DHL' ? '#EBF3FB' : row.carrier === 'FedEx' ? '#F0EBFB' : '#F0EFEB',
                      borderRadius: 4, fontSize: 10, fontWeight: 700,
                      color: row.carrier === 'DHL' ? '#1A5FA8' : row.carrier === 'FedEx' ? '#5A1AA8' : '#5A5550',
                    }}>{row.carrier}</span>
                  </td>
                  <td style={{ padding: '10px 12px' }}><Badge status={row.dhlStatus} small /></td>
                  <td style={{ padding: '10px 12px', color: '#6A6258', fontSize: 11 }}>{row.dhlRec}</td>
                  <td style={{ padding: '10px 12px' }}><Badge status={row.sadStatus} small /></td>
                  <td style={{ padding: '10px 12px', color: '#18160F', fontSize: 11, fontFamily: 'monospace' }}>{row.mrn}</td>
                  <td style={{ padding: '10px 12px' }}><Badge status={row.pzStatus} small /></td>
                  <td style={{ padding: '10px 12px', color: '#18160F', fontWeight: 500, textAlign: 'right' }}>{row.net}</td>
                  <td style={{ padding: '10px 12px', color: '#18160F', fontWeight: 500, textAlign: 'right' }}>{row.gross}</td>
                  <td style={{ padding: '10px 12px', color: GOLD, fontWeight: 700, textAlign: 'right' }}>{row.duty}</td>
                  <td style={{ padding: '10px 12px' }}><Badge status={row.overall} small /></td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <Btn small variant="outline" onClick={() => onViewShipment(row)}>View</Btn>
                      <div style={{ position: 'relative' }}>
                        <Btn small variant="ghost" onClick={() => setActionMenu(actionMenu === row.id ? null : row.id)}>⋯</Btn>
                        {actionMenu === row.id && (
                          <div style={{
                            position: 'absolute', right: 0, top: '100%', zIndex: 100,
                            background: 'var(--card)', border: '1px solid var(--border)',
                            borderRadius: 6, boxShadow: '0 4px 16px var(--shadow-heavy)',
                            minWidth: 130, overflow: 'hidden',
                          }}>
                            {['Edit Draft', 'Reprocess', 'Archive', 'Delete'].map(a => (
                              <button key={a} onClick={() => setActionMenu(null)} style={{
                                display: 'block', width: '100%', padding: '8px 14px',
                                textAlign: 'left', background: 'none', border: 'none',
                                fontSize: 12, cursor: 'pointer', color: a === 'Delete' ? 'var(--badge-red-text)' : 'var(--text)',
                              }}
                                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-subtle)'}
                                onMouseLeave={e => e.currentTarget.style.background = 'none'}
                              >{a}</button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Showing {filtered.length} of {MOCK_SHIPMENTS.length} shipments</span>
          <div style={{ display: 'flex', gap: 4 }}>
            <Btn small variant="outline">← Prev</Btn>
            <Btn small variant="outline">Next →</Btn>
          </div>
        </div>
      </Card>
    </div>
  );
}

Object.assign(window, { DashboardPage, MOCK_SHIPMENTS });
