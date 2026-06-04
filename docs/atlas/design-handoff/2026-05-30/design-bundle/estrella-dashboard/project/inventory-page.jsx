// ── Inventory Module — Two-Stage Architecture
// Stage 1 (Temporary): Temp Purchase · Temp Warehouse · Temp Sale
// Stage 2 (Physical):  Final Stock · Sample Out · Sample Return · Goods Return from Client · Return to Producer
// Plus: Identity / Mapping panel
//
// Truth model:
//   wfirma_good_id, wfirma_product_code  →  read-only external accounting refs
//   product_family_code, design_id       →  internal commercial identity
//   batch_id, bag_id                     →  physical batching
//   stock_unit_id                        →  inventory truth
//   trace_barcode = family-design-batch-bag

const INV_TABS = [
  { id: 'overview',     label: 'Overview',                 stage: '' },
  { id: 'tempPurchase', label: 'Temp Purchase',            stage: 'Stage 1' },
  { id: 'tempWarehouse',label: 'Temp Warehouse',           stage: 'Stage 1' },
  { id: 'tempSale',     label: 'Temp Sale',                stage: 'Stage 1' },
  { id: 'consignment',  label: 'Consignment',              stage: 'Stage 2' },
  { id: 'finalStock',   label: 'Final Stock',              stage: 'Stage 2' },
  { id: 'sampleOut',    label: 'Sample Out',               stage: 'Stage 2' },
  { id: 'sampleReturn', label: 'Sample Return',            stage: 'Stage 2' },
  { id: 'clientReturn', label: 'Goods Return from Client', stage: 'Stage 2' },
  { id: 'producerReturn',label: 'Return to Producer',      stage: 'Stage 2' },
  { id: 'mapping',      label: 'Identity / Mapping',       stage: '' },
];

// ── Shared inventory primitives ────────────────────────────────────────
function InvStatTile({ label, value, hint, tone }) {
  const toneColor = tone === 'red'   ? 'var(--badge-red-text)'
                  : tone === 'amber' ? 'var(--badge-amber-text)'
                  : tone === 'green' ? 'var(--badge-green-text)'
                  : 'var(--text)';
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 10, padding: '14px 16px', boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6, lineHeight: 1.25 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: toneColor, lineHeight: 1.25 }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

function StagePill({ stage }) {
  if (!stage) return null;
  const isOne = stage === 'Stage 1';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
      padding: '2px 6px', borderRadius: 3,
      background: isOne ? 'var(--badge-amber-bg)' : 'var(--badge-blue-bg)',
      color:      isOne ? 'var(--badge-amber-text)' : 'var(--badge-blue-text)',
      border: `1px solid ${isOne ? 'var(--badge-amber-border)' : 'var(--badge-blue-border)'}`,
    }}>{stage}</span>
  );
}

function InvBadge({ label, tone = 'neutral' }) {
  const t = {
    neutral: { bg: 'var(--badge-neutral-bg)', tx: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' },
    blue:    { bg: 'var(--badge-blue-bg)',    tx: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)' },
    amber:   { bg: 'var(--badge-amber-bg)',   tx: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)' },
    green:   { bg: 'var(--badge-green-bg)',   tx: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)' },
    red:     { bg: 'var(--badge-red-bg)',     tx: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)' },
    orange:  { bg: 'var(--badge-orange-bg)',  tx: 'var(--badge-orange-text)',  bd: 'var(--badge-orange-border)' },
    purple:  { bg: 'var(--badge-purple-bg)',  tx: 'var(--badge-purple-text)',  bd: 'var(--badge-purple-border)' },
  }[tone] || { bg: 'var(--badge-neutral-bg)', tx: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: t.bg, color: t.tx, border: `1px solid ${t.bd}`,
      borderRadius: 4, padding: '2px 8px',
      fontSize: 11, fontWeight: 600, letterSpacing: '0.03em', whiteSpace: 'nowrap',
    }}>{label}</span>
  );
}

function ReadOnlyField({ value }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontFamily: 'monospace', fontSize: 11.5, color: 'var(--text-2)',
      background: 'var(--bg-subtle)', border: '1px dashed var(--border)',
      borderRadius: 4, padding: '2px 6px',
    }}>
      <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: 'var(--text-3)' }}>wF</span>
      {value}
    </span>
  );
}

function InvTable({ columns, rows, empty }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
        {empty || 'No records yet'}
      </div>
    );
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 800 }}>
        <thead>
          <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
            {columns.map(c => (
              <th key={c.key || c.label} style={{
                padding: '10px 12px', textAlign: c.align || 'left',
                fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
                letterSpacing: '0.10em', textTransform: 'uppercase', whiteSpace: 'nowrap',
              }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              {columns.map(c => (
                <td key={c.key || c.label} style={{
                  padding: '11px 12px', textAlign: c.align || 'left',
                  fontFamily: c.mono ? 'monospace' : undefined,
                  fontWeight: c.bold ? 600 : undefined,
                  color: c.muted ? 'var(--text-2)' : 'var(--text)',
                  whiteSpace: c.wrap ? 'normal' : 'nowrap',
                }}>{c.render ? c.render(r) : r[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Stage 1 : TEMP PURCHASE ────────────────────────────────────────────
function TempPurchaseTab({ openViewer }) {
  const lines = [
    { plSr: 1, ctg: 'PND', clientPo: 'PROF 70/2026', designNo: 'EJ-PND-0142-A', karat: '18KT', color: 'W', quality: 'VS-GH', diaWt: '0.75', colWt: '—', qty: 2, size: '—', value: 'EUR 480.00', total: 'EUR 960.00', supplier: 'Estrella Jewels LLP', awb: 'DHL-1234567890', expected: '04 Apr 2026', status: 'Awaiting goods' },
    { plSr: 2, ctg: 'PND', clientPo: 'PROF 70/2026', designNo: 'EJ-PND-0142-B', karat: '18KT', color: 'W', quality: 'VS-GH', diaWt: '0.82', colWt: '—', qty: 3, size: '—', value: 'EUR 510.00', total: 'EUR 1,530.00', supplier: 'Estrella Jewels LLP', awb: 'DHL-1234567890', expected: '04 Apr 2026', status: 'Awaiting goods' },
    { plSr: 3, ctg: 'Loose Metal', clientPo: '—', designNo: 'LM-18W-04', karat: '18KT', color: 'W', quality: '—', diaWt: '—', colWt: '12.40', qty: 1, size: '—', value: 'EUR 612.00', total: 'EUR 612.00', supplier: 'Estrella Jewels LLP', awb: 'DHL-1234567890', expected: '04 Apr 2026', status: 'Partially arrived' },
    { plSr: 4, ctg: 'RNG', clientPo: 'PROF 71/2026', designNo: 'EJ-RNG-0089-C', karat: '14KT', color: 'Y', quality: 'SI-FG', diaWt: '0.40', colWt: '—', qty: 4, size: '54-58', value: 'EUR 295.00', total: 'EUR 1,180.00', supplier: 'Estrella Jewels LLP', awb: 'DHL-1234567884', expected: '06 Apr 2026', status: 'Closed-out' },
  ];

  const stats = [
    { label: 'Open packing lists', value: '6' },
    { label: 'Awaiting goods (lines)',value: '14', tone: 'amber' },
    { label: 'Partially arrived',  value: '2', tone: 'amber' },
    { label: 'Closed-out',         value: '8', tone: 'green' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {stats.map(s => <InvStatTile key={s.label} {...s} />)}
      </div>
      <div style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 12, color: 'var(--text-2)' }}>
        <strong style={{ color: 'var(--text)' }}>Stage 1 — Document layer.</strong> These lines come from supplier invoices &amp; packing lists. Goods are <em>expected</em> but not physically confirmed. No final stock is created here.
      </div>

      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Open packing-list lines</span>
            <InvBadge label="from invoices &amp; packing lists" tone="neutral" />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn small variant="outline">Filter</Btn>
            <Btn small variant="outline">↓ Export CSV</Btn>
            <Btn small>+ Upload Packing List</Btn>
          </div>
        </div>
        <InvTable
          columns={[
            { key: 'plSr',      label: 'Pk Sr', mono: true, align: 'right' },
            { key: 'ctg',       label: 'Ctg' },
            { key: 'clientPo',  label: 'Client PO', mono: true },
            { key: 'designNo',  label: 'Design No', mono: true, bold: true },
            { key: 'karat',     label: 'Karat' },
            { key: 'color',     label: 'Color' },
            { key: 'quality',   label: 'Quality' },
            { key: 'diaWt',     label: 'Dia Wt', align: 'right', mono: true },
            { key: 'colWt',     label: 'Col Wt', align: 'right', mono: true },
            { key: 'qty',       label: 'Qty',    align: 'right', bold: true },
            { key: 'size',      label: 'Size' },
            { key: 'total',     label: 'Total', align: 'right', mono: true, bold: true },
            { key: 'awb',       label: 'AWB', mono: true, muted: true },
            { key: 'status',    label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Awaiting goods' ? 'amber' : r.status === 'Partially arrived' ? 'orange' : 'green'} /> },
            { key: 'actions',   label: '',
              render: r => (
                <div style={{ display: 'flex', gap: 6 }}>
                  <Btn small variant="ghost" onClick={() => openViewer && openViewer({
                    id: 'PL-' + r.designNo, title: 'Packing List · ' + r.clientPo, type: 'Packing List', awb: r.awb,
                  })}>View doc</Btn>
                  <Btn small variant="outline">Receive</Btn>
                </div>
              ) },
          ]}
          rows={lines}
        />
      </Card>
    </div>
  );
}

// ── Stage 1 : TEMP WAREHOUSE ───────────────────────────────────────────
function TempWarehouseTab() {
  const items = [
    { plSr: 1, designNo: 'EJ-PND-0142-A', expectedQty: 2, receivedQty: 2, delta: 0,  bag: '—', awb: 'DHL-1234567890', recvDate: '07 Apr 2026', status: 'Pending match' },
    { plSr: 2, designNo: 'EJ-PND-0142-B', expectedQty: 3, receivedQty: 3, delta: 0,  bag: '—', awb: 'DHL-1234567890', recvDate: '07 Apr 2026', status: 'Pending match' },
    { plSr: 3, designNo: 'LM-18W-04',     expectedQty: 1, receivedQty: 0, delta: -1, bag: '—', awb: 'DHL-1234567890', recvDate: '—',          status: 'Discrepancy' },
    { plSr: 5, designNo: 'EJ-NCK-0211-A', expectedQty: 4, receivedQty: 5, delta: +1, bag: 'BAG-2604-A', awb: 'DHL-1234567884', recvDate: '06 Apr 2026', status: 'Discrepancy' },
    { plSr: 6, designNo: 'EJ-RNG-0098',   expectedQty: 2, receivedQty: 2, delta: 0,  bag: 'BAG-2604-B', awb: 'DHL-1234567884', recvDate: '06 Apr 2026', status: 'Counted, awaiting bag' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="Awaiting count"    value="9"  tone="amber" />
        <InvStatTile label="Counted"           value="14" />
        <InvStatTile label="Discrepancies"     value="3"  tone="red" />
        <InvStatTile label="Ready for matching"value="11" tone="green" />
      </div>
      <div style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 12, color: 'var(--text-2)' }}>
        <strong style={{ color: 'var(--text)' }}>Stage 1 — Physical arrival.</strong> Goods have arrived but are not fully matched, counted or bagged. Discrepancies allowed and tracked. <strong>No FINAL_STOCK is created until matching is complete.</strong>
      </div>

      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Pending physical match</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn small variant="outline">Scan barcode</Btn>
            <Btn small>Begin matching</Btn>
          </div>
        </div>
        <InvTable
          columns={[
            { key: 'plSr',        label: 'Pk Sr', mono: true, align: 'right' },
            { key: 'designNo',    label: 'Design No', mono: true, bold: true },
            { key: 'expectedQty', label: 'Expected', align: 'right' },
            { key: 'receivedQty', label: 'Received', align: 'right', bold: true },
            { key: 'delta',       label: 'Δ', align: 'right',
              render: r => <span style={{ color: r.delta === 0 ? 'var(--text-2)' : r.delta > 0 ? 'var(--badge-amber-text)' : 'var(--badge-red-text)', fontWeight: 700, fontFamily: 'monospace' }}>{r.delta > 0 ? '+' + r.delta : r.delta}</span> },
            { key: 'bag',         label: 'Bag ID', mono: true },
            { key: 'awb',         label: 'AWB', mono: true, muted: true },
            { key: 'recvDate',    label: 'Received' },
            { key: 'status',      label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Discrepancy' ? 'red' : r.status === 'Pending match' ? 'amber' : 'blue'} /> },
            { key: 'actions',     label: '',
              render: r => (
                <div style={{ display: 'flex', gap: 6 }}>
                  <Btn small variant="ghost">Count</Btn>
                  <Btn small variant="outline">Assign bag</Btn>
                </div>
              ) },
          ]}
          rows={items}
        />
      </Card>
    </div>
  );
}

// ── Stage 1 : TEMP SALE ────────────────────────────────────────────────
function TempSaleTab() {
  const reservations = [
    { proforma: 'PROF 70/2026',  client: 'Juliany EOOD',     designNo: 'EJ-PND-0142-A', qty: 2, value: 'EUR 960.00',   linkedTo: 'TempWarehouse · BAG-2604-A', status: 'Reserved' },
    { proforma: 'PROF 70/2026',  client: 'Juliany EOOD',     designNo: 'EJ-PND-0142-B', qty: 3, value: 'EUR 1,530.00', linkedTo: 'TempWarehouse · BAG-2604-A', status: 'Reserved' },
    { proforma: 'PROF 71/2026',  client: 'Verhoeven',        designNo: 'EJ-RNG-0098',   qty: 2, value: 'EUR 590.00',   linkedTo: 'TempWarehouse · BAG-2604-B', status: 'Awaiting goods' },
    { proforma: 'PROF 72/2026',  client: '38-10 Juliany EOOD',designNo: 'EJ-NCK-0211-A', qty: 4, value: 'EUR 1,180.00', linkedTo: 'TempPurchase · DHL-1234567884', status: 'Pre-reserved' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="Open reservations" value="11" />
        <InvStatTile label="Awaiting goods"    value="4"  tone="amber" />
        <InvStatTile label="Reserved"          value="6" />
        <InvStatTile label="Sales-invoice gate" value="LOCKED" tone="amber" hint="Until FINAL_STOCK confirms" />
      </div>
      <div style={{ background: 'var(--badge-orange-bg)', border: '1px solid var(--badge-orange-border)', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 12, color: 'var(--text)' }}>
        <strong>Sales-invoice gate is enforced.</strong> No commercial sale invoice can be issued from a TEMP_SALE row. The invoice is unlocked only when its linked stock has reached <strong>FINAL_STOCK</strong> after physical verification.
      </div>

      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Sales reservations awaiting closure</span>
        </div>
        <InvTable
          columns={[
            { key: 'proforma', label: 'Proforma', mono: true, bold: true },
            { key: 'client',   label: 'Client' },
            { key: 'designNo', label: 'Design No', mono: true },
            { key: 'qty',      label: 'Qty', align: 'right', bold: true },
            { key: 'value',    label: 'Value', align: 'right', mono: true },
            { key: 'linkedTo', label: 'Linked to', muted: true },
            { key: 'status',   label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Reserved' ? 'blue' : r.status === 'Awaiting goods' ? 'amber' : 'orange'} /> },
            { key: 'actions',  label: '',
              render: () => (
                <div style={{ display: 'flex', gap: 6 }}>
                  <Btn small variant="ghost">View proforma</Btn>
                  <Btn small variant="outline" disabled>Issue invoice</Btn>
                </div>
              ) },
          ]}
          rows={reservations}
        />
      </Card>
    </div>
  );
}

// ── Stage 2 : FINAL STOCK ──────────────────────────────────────────────
function FinalStockTab() {
  const stock = [
    { stockUnitId: 'SU-2604-00012', family: 'PND-CLASSIC', design: 'EJ-PND-0142-A', batch: 'B-2604-04',  bag: 'BAG-2604-A',  qty: 2, location: 'Główny / Shelf-A4', valuePln: 'PLN 4,128.00', traceBarcode: 'PND-CLASSIC·EJ-PND-0142-A·B-2604-04·BAG-2604-A', wfGoodId: '78461', wfCode: 'PND-CL-0142', verifiedOn: '07 Apr 2026' },
    { stockUnitId: 'SU-2604-00013', family: 'PND-CLASSIC', design: 'EJ-PND-0142-B', batch: 'B-2604-04',  bag: 'BAG-2604-A',  qty: 3, location: 'Główny / Shelf-A4', valuePln: 'PLN 6,572.00', traceBarcode: 'PND-CLASSIC·EJ-PND-0142-B·B-2604-04·BAG-2604-A', wfGoodId: '78462', wfCode: 'PND-CL-0142B', verifiedOn: '07 Apr 2026' },
    { stockUnitId: 'SU-2604-00018', family: 'RNG-CLASSIC', design: 'EJ-RNG-0098',   batch: 'B-2604-04',  bag: 'BAG-2604-B',  qty: 2, location: 'Główny / Shelf-B2', valuePln: 'PLN 2,535.00', traceBarcode: 'RNG-CLASSIC·EJ-RNG-0098·B-2604-04·BAG-2604-B',   wfGoodId: '71204', wfCode: 'RNG-CL-0098', verifiedOn: '07 Apr 2026' },
    { stockUnitId: 'SU-2603-00097', family: 'NCK-PEARL',   design: 'EJ-NCK-0211-A', batch: 'B-2603-22',  bag: 'BAG-2603-D',  qty: 6, location: 'Główny / Shelf-C1', valuePln: 'PLN 5,068.00', traceBarcode: 'NCK-PEARL·EJ-NCK-0211-A·B-2603-22·BAG-2603-D',  wfGoodId: '64391', wfCode: 'NCK-PRL-0211',verifiedOn: '22 Mar 2026' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="Stock units"    value="412" />
        <InvStatTile label="Pieces on hand" value="1,847" />
        <InvStatTile label="Reserved"       value="148" />
        <InvStatTile label="Available"      value="1,699" tone="green" />
        <InvStatTile label="Stock value"    value="PLN 2.41M" />
      </div>
      <div style={{ background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 12, color: 'var(--text)' }}>
        <strong>Stage 2 — Inventory truth.</strong> Each row is a physically-verified <code style={{ fontFamily: 'monospace', background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>stock_unit_id</code>. wFirma fields are <em>read-only references</em> until controlled execution is approved separately.
      </div>

      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Verified stock units</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input placeholder="Filter family / design / batch / bag…" style={{
              padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--card)', color: 'var(--text)', minWidth: 280,
            }} />
            <Btn small variant="outline">Cycle count</Btn>
            <Btn small variant="outline">↓ Export</Btn>
          </div>
        </div>
        <InvTable
          columns={[
            { key: 'stockUnitId',  label: 'Stock Unit ID', mono: true, bold: true },
            { key: 'family',       label: 'Family', mono: true },
            { key: 'design',       label: 'Design ID', mono: true },
            { key: 'batch',        label: 'Batch', mono: true },
            { key: 'bag',          label: 'Bag', mono: true },
            { key: 'qty',          label: 'Qty', align: 'right', bold: true },
            { key: 'location',     label: 'Location', muted: true },
            { key: 'valuePln',     label: 'Value', align: 'right', mono: true },
            { key: 'wfCode',       label: 'wFirma ref',
              render: r => <ReadOnlyField value={r.wfCode} /> },
            { key: 'actions',      label: '',
              render: () => (
                <div style={{ display: 'flex', gap: 6 }}>
                  <Btn small variant="ghost">Trace</Btn>
                  <Btn small variant="outline">Move</Btn>
                </div>
              ) },
          ]}
          rows={stock}
        />
      </Card>
    </div>
  );
}

// ── Stage 2 : SAMPLE OUT ───────────────────────────────────────────────
function SampleOutTab() {
  const samples = [
    { sampleId: 'SMP-2604-001', stockUnitId: 'SU-2604-00012', design: 'EJ-PND-0142-A', qty: 1, issuedTo: 'Anna K. (Sales)',   issuedFor: 'Client visit · Sofia',  issued: '04 Apr 2026', returnBy: '11 Apr 2026', daysLeft: 4,  status: 'Out' },
    { sampleId: 'SMP-2604-002', stockUnitId: 'SU-2604-00018', design: 'EJ-RNG-0098',   qty: 1, issuedTo: 'Marek W. (Sales)',  issuedFor: 'Antwerp viewing',        issued: '02 Apr 2026', returnBy: '09 Apr 2026', daysLeft: 2,  status: 'Closing soon' },
    { sampleId: 'SMP-2603-097', stockUnitId: 'SU-2603-00097', design: 'EJ-NCK-0211-A', qty: 1, issuedTo: 'Juliany EOOD',     issuedFor: 'On approval',            issued: '20 Mar 2026', returnBy: '03 Apr 2026', daysLeft: -4, status: 'Overdue' },
    { sampleId: 'SMP-2603-082', stockUnitId: 'SU-2603-00081', design: 'EJ-EAR-0357',   qty: 1, issuedTo: 'Verhoeven',         issuedFor: 'On approval',            issued: '18 Mar 2026', returnBy: '01 Apr 2026', daysLeft: 0,  status: 'Returned',  returned: '31 Mar 2026' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="Active out"     value="14" />
        <InvStatTile label="Closing soon"   value="3"  tone="amber" hint="≤ 3 days" />
        <InvStatTile label="Overdue"        value="1"  tone="red" />
        <InvStatTile label="Returned (mo.)" value="22" tone="green" />
      </div>
      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Verified stock issued temporarily</span>
          <Btn small>+ Issue Sample</Btn>
        </div>
        <InvTable
          columns={[
            { key: 'sampleId',    label: 'Sample ID', mono: true, bold: true },
            { key: 'stockUnitId', label: 'Source SU', mono: true, muted: true },
            { key: 'design',      label: 'Design', mono: true },
            { key: 'qty',         label: 'Qty', align: 'right' },
            { key: 'issuedTo',    label: 'Issued to' },
            { key: 'issuedFor',   label: 'Purpose', muted: true },
            { key: 'issued',      label: 'Issued' },
            { key: 'returnBy',    label: 'Return by' },
            { key: 'daysLeft',    label: 'Days left', align: 'right',
              render: r => <span style={{ fontWeight: 700, color: r.daysLeft < 0 ? 'var(--badge-red-text)' : r.daysLeft <= 3 ? 'var(--badge-amber-text)' : 'var(--text)' }}>{r.daysLeft}</span> },
            { key: 'status',      label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Out' ? 'blue' : r.status === 'Closing soon' ? 'amber' : r.status === 'Overdue' ? 'red' : 'green'} /> },
            { key: 'actions',     label: '',
              render: r => (
                <div style={{ display: 'flex', gap: 6 }}>
                  {r.status !== 'Returned' && <Btn small variant="outline">Mark returned</Btn>}
                  <Btn small variant="ghost">Trace</Btn>
                </div>
              ) },
          ]}
          rows={samples}
        />
      </Card>
    </div>
  );
}

// ── Stage 2 : SAMPLE RETURN ────────────────────────────────────────────
function SampleReturnTab() {
  const returns = [
    { rtnId: 'SR-2604-001', sampleId: 'SMP-2603-082', design: 'EJ-EAR-0357',   qty: 1, returnedFrom: 'Verhoeven',           received: '31 Mar 2026', condition: 'Mint',   inspectedBy: 'Anna K.',  decision: 'Restock',     status: 'Restocked' },
    { rtnId: 'SR-2604-002', sampleId: 'SMP-2603-085', design: 'EJ-PND-0140',   qty: 1, returnedFrom: 'Anna K. (Sales)',     received: '30 Mar 2026', condition: 'Light scratches', inspectedBy: 'Marek W.', decision: 'Restock after polish', status: 'In repair' },
    { rtnId: 'SR-2604-003', sampleId: 'SMP-2603-090', design: 'EJ-RNG-0099',   qty: 1, returnedFrom: 'Juliany EOOD',         received: '02 Apr 2026', condition: 'Damaged stone', inspectedBy: '—',         decision: '—',           status: 'Awaiting inspection' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="Awaiting inspection" value="3" tone="amber" />
        <InvStatTile label="In repair"           value="2" />
        <InvStatTile label="Restocked (mo.)"     value="18" tone="green" />
        <InvStatTile label="Written off (mo.)"   value="1" tone="red" />
      </div>
      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Samples coming back from sales / clients</span>
        </div>
        <InvTable
          columns={[
            { key: 'rtnId',        label: 'Return ID', mono: true, bold: true },
            { key: 'sampleId',     label: 'Sample', mono: true, muted: true },
            { key: 'design',       label: 'Design', mono: true },
            { key: 'qty',          label: 'Qty', align: 'right' },
            { key: 'returnedFrom', label: 'Returned from' },
            { key: 'received',     label: 'Received' },
            { key: 'condition',    label: 'Condition' },
            { key: 'inspectedBy',  label: 'Inspector', muted: true },
            { key: 'decision',     label: 'Decision' },
            { key: 'status',       label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Awaiting inspection' ? 'amber' : r.status === 'In repair' ? 'blue' : r.status === 'Restocked' ? 'green' : 'neutral'} /> },
            { key: 'actions',      label: '',
              render: r => (
                <div style={{ display: 'flex', gap: 6 }}>
                  {r.status === 'Awaiting inspection' && <Btn small>Inspect</Btn>}
                  <Btn small variant="ghost">View</Btn>
                </div>
              ) },
          ]}
          rows={returns}
        />
      </Card>
    </div>
  );
}

// ── Stage 2 : GOODS RETURN FROM CLIENT (RMA) ───────────────────────────
function ClientReturnTab() {
  const rmas = [
    { rmaId: 'RMA-2604-001', invoice: 'INV 2026/0148', client: 'Juliany EOOD', design: 'EJ-PND-0142-A', qty: 1, value: 'EUR 480.00', reason: 'Size exchange',     received: '04 Apr 2026', condition: 'Mint',         decision: 'Restock',       status: 'Restocked' },
    { rmaId: 'RMA-2604-002', invoice: 'INV 2026/0151', client: 'Verhoeven',     design: 'EJ-RNG-0099',   qty: 1, value: 'EUR 295.00', reason: 'Damaged in transit',received: '05 Apr 2026', condition: 'Stone loose', decision: '—',            status: 'Awaiting inspection' },
    { rmaId: 'RMA-2604-003', invoice: 'INV 2026/0144', client: '38-10 Juliany', design: 'EJ-NCK-0211-A', qty: 2, value: 'EUR 1,180.00',reason: 'Wrong item shipped',received: '06 Apr 2026', condition: 'Mint',         decision: 'Restock',       status: 'Inspected' },
    { rmaId: 'RMA-2604-004', invoice: 'INV 2026/0140', client: 'Bijou & Co',    design: 'EJ-EAR-0357',   qty: 1, value: 'EUR 320.00', reason: 'Quality dispute',   received: '02 Apr 2026', condition: 'Discoloured', decision: 'Return to producer', status: 'Routed to RTP' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="Open RMAs"           value="7" />
        <InvStatTile label="Awaiting inspection" value="2" tone="amber" />
        <InvStatTile label="Routed to producer"  value="1" tone="orange" />
        <InvStatTile label="Restocked (mo.)"     value="11" tone="green" />
      </div>
      <div style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 12, color: 'var(--text-2)' }}>
        Post-sale returns (RMA). After inspection, route to <strong>Restock</strong>, <strong>Repair</strong>, <strong>Write-off</strong>, or <strong>Return to Producer</strong>. Credit-note generation stays in Sales / wFirma — not here.
      </div>

      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Open RMAs</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn small variant="outline">+ Open RMA</Btn>
          </div>
        </div>
        <InvTable
          columns={[
            { key: 'rmaId',    label: 'RMA ID', mono: true, bold: true },
            { key: 'invoice',  label: 'Invoice', mono: true, muted: true },
            { key: 'client',   label: 'Client' },
            { key: 'design',   label: 'Design', mono: true },
            { key: 'qty',      label: 'Qty', align: 'right' },
            { key: 'value',    label: 'Value', align: 'right', mono: true },
            { key: 'reason',   label: 'Reason' },
            { key: 'received', label: 'Received' },
            { key: 'decision', label: 'Decision' },
            { key: 'status',   label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Awaiting inspection' ? 'amber' : r.status === 'Restocked' ? 'green' : r.status === 'Routed to RTP' ? 'orange' : 'blue'} /> },
            { key: 'actions',  label: '',
              render: r => (
                <div style={{ display: 'flex', gap: 6 }}>
                  {r.status === 'Awaiting inspection' && <Btn small>Inspect</Btn>}
                  <Btn small variant="ghost">View</Btn>
                </div>
              ) },
          ]}
          rows={rmas}
        />
      </Card>
    </div>
  );
}

// ── Stage 2 : RETURN TO PRODUCER ───────────────────────────────────────
function ProducerReturnTab() {
  const rtps = [
    { rtpId: 'RTP-2604-001', source: 'RMA-2604-004', design: 'EJ-EAR-0357', qty: 1, supplier: 'Estrella Jewels LLP', reason: 'Quality dispute',  prepared: '06 Apr 2026', awbOut: '—',              status: 'Awaiting AWB' },
    { rtpId: 'RTP-2604-002', source: 'TempWH · LM-18W-04', design: 'LM-18W-04', qty: 1, supplier: 'Estrella Jewels LLP', reason: 'Short-shipped',    prepared: '07 Apr 2026', awbOut: 'DHL-OUT-991224', status: 'Shipped' },
    { rtpId: 'RTP-2603-018', source: 'SR-2603-022', design: 'EJ-RNG-0089',  qty: 1, supplier: 'Estrella Jewels LLP', reason: 'Sample worn out',  prepared: '24 Mar 2026', awbOut: 'DHL-OUT-991108', status: 'Confirmed by producer' },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <InvStatTile label="In preparation" value="2" />
        <InvStatTile label="Awaiting AWB"   value="1" tone="amber" />
        <InvStatTile label="In transit"     value="3" />
        <InvStatTile label="Confirmed (mo.)" value="9" tone="green" />
      </div>
      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Returns prepared for supplier shipment</span>
        </div>
        <InvTable
          columns={[
            { key: 'rtpId',    label: 'RTP ID', mono: true, bold: true },
            { key: 'source',   label: 'Source', mono: true, muted: true },
            { key: 'design',   label: 'Design', mono: true },
            { key: 'qty',      label: 'Qty', align: 'right' },
            { key: 'supplier', label: 'Supplier' },
            { key: 'reason',   label: 'Reason' },
            { key: 'prepared', label: 'Prepared' },
            { key: 'awbOut',   label: 'AWB out', mono: true },
            { key: 'status',   label: 'Status',
              render: r => <InvBadge label={r.status}
                tone={r.status === 'Awaiting AWB' ? 'amber' : r.status === 'Shipped' ? 'blue' : r.status === 'Confirmed by producer' ? 'green' : 'neutral'} /> },
            { key: 'actions',  label: '',
              render: r => (
                <div style={{ display: 'flex', gap: 6 }}>
                  {r.status === 'Awaiting AWB' && <Btn small>Add AWB</Btn>}
                  <Btn small variant="ghost">View docs</Btn>
                </div>
              ) },
          ]}
          rows={rtps}
        />
      </Card>
    </div>
  );
}

// ── IDENTITY / MAPPING ─────────────────────────────────────────────────
function MappingTab() {
  const fields = [
    { key: 'wfirma_good_id',      group: 'External (read-only)', label: 'wFirma Good ID',       desc: 'Read-only external accounting product ID',     ex: '78461',          editable: false },
    { key: 'wfirma_product_code', group: 'External (read-only)', label: 'wFirma Product Code',  desc: 'Read-only external wFirma product code',         ex: 'PND-CL-0142',    editable: false },
    { key: 'product_family_code', group: 'Internal commercial',  label: 'Product Family Code', desc: 'Internal commercial product family',             ex: 'PND-CLASSIC',    editable: true },
    { key: 'design_id',           group: 'Internal commercial',  label: 'Design ID',           desc: 'Actual jewelry design / model',                  ex: 'EJ-PND-0142-A',  editable: true },
    { key: 'batch_id',            group: 'Physical',             label: 'Batch ID',            desc: 'Import / purchase / production batch',           ex: 'B-2604-04',      editable: true },
    { key: 'bag_id',              group: 'Physical',             label: 'Bag ID',              desc: 'Physical bag / packet',                          ex: 'BAG-2604-A',     editable: true },
    { key: 'stock_unit_id',       group: 'Truth',                label: 'Stock Unit ID',       desc: 'System-generated physical stock identity',        ex: 'SU-2604-00012',  editable: false, truth: true },
    { key: 'trace_barcode',       group: 'Truth',                label: 'Trace Barcode',       desc: 'family + design + batch + bag (scan value)',     ex: 'PND-CLASSIC·EJ-PND-0142-A·B-2604-04·BAG-2604-A', editable: false, truth: true },
  ];

  return (
    <div>
      <div style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, padding: '14px 18px', marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Identity model</div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.55 }}>
          wFirma is <strong>not</strong> the inventory truth. The truth is <code style={{ fontFamily: 'monospace', background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>stock_unit_id</code>, scanned via <code style={{ fontFamily: 'monospace', background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>trace_barcode</code>. wFirma fields appear here as read-only references to keep accounting in sync without letting external mismatches corrupt physical inventory.
        </div>
      </div>

      <Card>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>The 8 identity fields</span>
        </div>
        <InvTable
          columns={[
            { key: 'group',      label: 'Group',
              render: r => <span style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: r.truth ? 'var(--badge-green-text)' : r.editable ? 'var(--text-2)' : 'var(--text-3)',
              }}>{r.group}</span> },
            { key: 'key',        label: 'Field key', mono: true, bold: true },
            { key: 'label',      label: 'Label' },
            { key: 'desc',       label: 'Description', muted: true, wrap: true },
            { key: 'ex',         label: 'Example', mono: true, muted: true },
            { key: 'access',     label: 'Access',
              render: r => r.editable
                ? <InvBadge label="Editable"  tone="blue" />
                : r.truth
                  ? <InvBadge label="System-generated" tone="green" />
                  : <InvBadge label="Read-only (wFirma)" tone="neutral" /> },
          ]}
          rows={fields}
        />
      </Card>

      <div style={{ marginTop: 24, fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 10, padding: '0 4px' }}>Movement model</div>
      <Card>
        <div style={{ padding: '14px 18px', fontSize: 12, color: 'var(--text-2)', lineHeight: 1.7 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Stage 1 — Temporary</div>
              <div>1. Supplier invoice / packing list → <strong>TEMP_PURCHASE</strong></div>
              <div>2. DHL / SAD / PZ reference attached</div>
              <div>3. Goods physically arrive → <strong>TEMP_WAREHOUSE</strong></div>
              <div>4. Sales reservation → <strong>TEMP_SALE</strong> (gated)</div>
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Stage 2 — Physical</div>
              <div>5. Physical count + bag assignment + match</div>
              <div>6. <strong>FINAL_STOCK</strong> created (verified)</div>
              <div>7. Movement: Sale · <strong>SAMPLE_TEMP</strong> · Client return · <strong>RETURN_TO_PRODUCER</strong></div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ── INVENTORY OVERVIEW ─────────────────────────────────────────────────
function InventoryOverviewTab({ setTab }) {
  const fire = (evt) => window.dispatchEvent(new CustomEvent(evt));
  return (
    <div>
      {/* Quick actions */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
        <div onClick={() => fire('inv:upload')} style={{
          padding: '16px 18px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--card)',
          cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 14,
        }}>
          <div style={{ width: 38, height: 38, borderRadius: 8, background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700 }}>↑</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Upload Document</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Packing list · Invoice · Transfer · Return — auto-routes by type</div>
          </div>
          <span style={{ fontSize: 16, color: 'var(--text-3)' }}>›</span>
        </div>
        <div onClick={() => fire('inv:move')} style={{
          padding: '16px 18px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--card)',
          cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 14,
        }}>
          <div style={{ width: 38, height: 38, borderRadius: 8, background: 'var(--badge-blue-bg)', color: 'var(--badge-blue-text)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700 }}>⇄</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Move Stock</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Warehouse → Warehouse, Main → Sample / Consignment / Return</div>
          </div>
          <span style={{ fontSize: 16, color: 'var(--text-3)' }}>›</span>
        </div>
        <div onClick={() => setTab('mapping')} style={{
          padding: '16px 18px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--card)',
          cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 14,
        }}>
          <div style={{ width: 38, height: 38, borderRadius: 8, background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700 }}>≡</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Identity / Mapping</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Family · Design · Batch · Bag · Trace barcode</div>
          </div>
          <span style={{ fontSize: 16, color: 'var(--text-3)' }}>›</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        <InvStatTile label="Stock units (final)" value="412"        tone="green" />
        <InvStatTile label="Pieces on hand"      value="1,847" />
        <InvStatTile label="Stock value"         value="PLN 2.41M" />
        <InvStatTile label="Reorder alerts"      value="6"          tone="amber" hint="below reorder point" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16 }}>
        <Card>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-amber-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 4 }}>Stage 1 — Temporary</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Document &amp; arrival layer</div>
            </div>
          </div>
          <div style={{ padding: '6px 0' }}>
            {[
              { id: 'tempPurchase',  label: 'Temp Purchase',   right: '6 open · 14 lines' },
              { id: 'tempWarehouse', label: 'Temp Warehouse',  right: '9 awaiting count · 3 discrepancies' },
              { id: 'tempSale',      label: 'Temp Sale',       right: '11 reserved · invoice gate locked' },
            ].map(r => (
              <div key={r.id} onClick={() => setTab(r.id)} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '12px 18px', cursor: 'pointer',
                borderBottom: '1px solid var(--border-subtle)',
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{r.label}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{r.right}</span>
                  <span style={{ fontSize: 14, color: 'var(--text-3)' }}>›</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-blue-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 4 }}>Stage 2 — Physical</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Verified stock &amp; movements</div>
          </div>
          <div style={{ padding: '6px 0' }}>
            {[
              { id: 'finalStock',     label: 'Final Stock',                right: '412 SU · 1,847 pcs' },
              { id: 'sampleOut',      label: 'Sample Out',                 right: '14 active · 1 overdue' },
              { id: 'sampleReturn',   label: 'Sample Return',              right: '3 awaiting inspection' },
              { id: 'clientReturn',   label: 'Goods Return from Client',   right: '7 open · 2 awaiting inspection' },
              { id: 'producerReturn', label: 'Return to Producer',         right: '6 open' },
            ].map(r => (
              <div key={r.id} onClick={() => setTab(r.id)} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '12px 18px', cursor: 'pointer',
                borderBottom: '1px solid var(--border-subtle)',
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{r.label}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{r.right}</span>
                  <span style={{ fontSize: 14, color: 'var(--text-3)' }}>›</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Recent inventory movements</span>
          <Btn small variant="outline">View full ledger</Btn>
        </div>
        <InvTable
          columns={[
            { key: 'time',     label: 'When', muted: true },
            { key: 'kind',     label: 'Movement',
              render: r => <InvBadge label={r.kind} tone={r.tone} /> },
            { key: 'su',       label: 'Stock Unit / Line', mono: true },
            { key: 'design',   label: 'Design', mono: true },
            { key: 'qty',      label: 'Qty', align: 'right', bold: true },
            { key: 'who',      label: 'By', muted: true },
            { key: 'ref',      label: 'Ref', mono: true, muted: true },
          ]}
          rows={[
            { time: '14:42 today',  kind: 'IN — Temp WH',   tone: 'amber', su: 'PL-3 / EJ-PND-0142-A', design: 'EJ-PND-0142-A', qty: 2, who: 'DHL receipt', ref: 'AWB-1234567890' },
            { time: '11:18 today',  kind: 'MATCH → Final',  tone: 'green', su: 'SU-2604-00018',         design: 'EJ-RNG-0098',   qty: 2, who: 'Anna K.',     ref: 'BAG-2604-B' },
            { time: '10:05 today',  kind: 'OUT — Sample',   tone: 'blue',  su: 'SU-2604-00012',         design: 'EJ-PND-0142-A', qty: 1, who: 'Marek W.',    ref: 'SMP-2604-002' },
            { time: 'Yesterday',    kind: 'IN — RMA',       tone: 'orange',su: 'SU-2603-00097',         design: 'EJ-NCK-0211-A', qty: 2, who: '38-10 Juliany',ref: 'RMA-2604-003' },
            { time: '2 days ago',   kind: 'OUT — RTP',      tone: 'red',   su: 'SU-LM-18W-04',          design: 'LM-18W-04',     qty: 1, who: 'Marek W.',    ref: 'RTP-2604-002' },
          ]}
        />
      </Card>
    </div>
  );
}

// ── MAIN INVENTORY PAGE ────────────────────────────────────────────────
function InventoryPage({ openViewer }) {
  const [tab, setTab] = React.useState('overview');
  const [showMove, setShowMove] = React.useState(false);
  const [showUpload, setShowUpload] = React.useState(false);

  React.useEffect(() => {
    const onMove = () => setShowMove(true);
    const onUpload = () => setShowUpload(true);
    const onJump = (e) => { if (e?.detail?.tab) setTab(e.detail.tab); };
    window.addEventListener('inv:move', onMove);
    window.addEventListener('inv:upload', onUpload);
    window.addEventListener('inv:jump', onJump);
    return () => {
      window.removeEventListener('inv:move', onMove);
      window.removeEventListener('inv:upload', onUpload);
      window.removeEventListener('inv:jump', onJump);
    };
  }, []);

  const tabsByStage = {
    '': INV_TABS.filter(t => !t.stage),
    'Stage 1': INV_TABS.filter(t => t.stage === 'Stage 1'),
    'Stage 2': INV_TABS.filter(t => t.stage === 'Stage 2'),
  };

  return (
    <div style={{ padding: '20px 32px 32px', overflowY: 'auto', flex: 1 }}>
      {/* Tab strip — grouped by stage */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0, marginBottom: 20, borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        {INV_TABS.map((t, i) => {
          const isActive = tab === t.id;
          const prev = INV_TABS[i - 1];
          const showStageBreak = prev && prev.stage !== t.stage;
          return (
            <React.Fragment key={t.id}>
              {showStageBreak && <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 6px 8px' }} />}
              <button onClick={() => setTab(t.id)} style={{
                padding: '10px 14px', background: 'none', border: 'none', cursor: 'pointer',
                borderBottom: `2px solid ${isActive ? 'var(--accent)' : 'transparent'}`,
                color: isActive ? 'var(--text)' : 'var(--text-2)',
                fontSize: 12.5, fontWeight: isActive ? 700 : 500, marginBottom: -1,
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                {t.label}
                {t.stage && (
                  <span style={{
                    fontSize: 8.5, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                    padding: '1px 5px', borderRadius: 3,
                    background: t.stage === 'Stage 1' ? 'var(--badge-amber-bg)' : 'var(--badge-blue-bg)',
                    color:      t.stage === 'Stage 1' ? 'var(--badge-amber-text)' : 'var(--badge-blue-text)',
                    border: `1px solid ${t.stage === 'Stage 1' ? 'var(--badge-amber-border)' : 'var(--badge-blue-border)'}`,
                  }}>{t.stage === 'Stage 1' ? 'S1' : 'S2'}</span>
                )}
              </button>
            </React.Fragment>
          );
        })}
      </div>

      {tab === 'overview'        && <InventoryOverviewTab setTab={setTab} />}
      {tab === 'tempPurchase'    && <TempPurchaseTab openViewer={openViewer} />}
      {tab === 'tempWarehouse'   && <TempWarehouseTab />}
      {tab === 'tempSale'        && <TempSaleTab />}
      {tab === 'consignment'     && <ConsignmentTab />}
      {tab === 'finalStock'      && <FinalStockTab />}
      {tab === 'sampleOut'       && <SampleOutTab />}
      {tab === 'sampleReturn'    && <SampleReturnTab />}
      {tab === 'clientReturn'    && <ClientReturnTab />}
      {tab === 'producerReturn'  && <ProducerReturnTab />}
      {tab === 'mapping'         && <MappingTab />}

      {showMove && <MoveStockModal onClose={() => setShowMove(false)} />}
      {showUpload && <UploadDocumentModal onClose={() => setShowUpload(false)} onRoute={(t) => { setTab(t); setShowUpload(false); }} />}
    </div>
  );
}

// ── DOCUMENT VIEWER (full-page route) ──────────────────────────────────
function DocumentViewerPage({ doc, onBack }) {
  const [page, setPageNum] = React.useState(1);
  const [zoom, setZoom] = React.useState(100);
  const totalPages = doc?.totalPages || 2;

  const meta = [
    { label: 'Document type',  value: doc?.type || 'Packing List' },
    { label: 'Document #',     value: doc?.id || 'PL-EJL-26-27-013' },
    { label: 'Title',          value: doc?.title || 'Packing list of shipment 5pcs · 04 Apr 2026' },
    { label: 'Linked AWB',     value: doc?.awb || 'DHL-1234567890' },
    { label: 'Linked shipment',value: doc?.shipment || 'SHP-2026-0142' },
    { label: 'Uploaded',       value: doc?.uploaded || '04 Apr 2026 · 09:14' },
    { label: 'Uploaded by',    value: doc?.uploadedBy || 'Anna K.' },
    { label: 'Size',           value: doc?.size || '184 KB' },
    { label: 'Format',         value: doc?.format || 'XLSX' },
    { label: 'Hash',           value: doc?.hash || 'sha256:a4f9…b182' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: 'var(--bg)' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 24px', borderBottom: '1px solid var(--border)',
        background: 'var(--card)', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Btn small variant="ghost" onClick={onBack}>← Back</Btn>
          <div style={{ width: 1, height: 22, background: 'var(--border)' }} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{doc?.title || 'Packing list of shipment'}</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'monospace' }}>{doc?.id || 'PL-EJL-26-27-013'} · {doc?.format || 'XLSX'}</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Btn small variant="ghost" onClick={() => setPageNum(Math.max(1, page - 1))} disabled={page === 1}>‹</Btn>
          <span style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 48, textAlign: 'center', fontFamily: 'monospace' }}>{page} / {totalPages}</span>
          <Btn small variant="ghost" onClick={() => setPageNum(Math.min(totalPages, page + 1))} disabled={page === totalPages}>›</Btn>
          <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px' }} />
          <Btn small variant="ghost" onClick={() => setZoom(Math.max(50, zoom - 10))}>−</Btn>
          <span style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 44, textAlign: 'center', fontFamily: 'monospace' }}>{zoom}%</span>
          <Btn small variant="ghost" onClick={() => setZoom(Math.min(200, zoom + 10))}>+</Btn>
          <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px' }} />
          <Btn small variant="outline">Open in new tab</Btn>
          <Btn small variant="outline">↓ Download</Btn>
          <Btn small>↓ Download all (.zip)</Btn>
        </div>
      </div>

      {/* Body — viewer + side panel */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 1, overflow: 'auto', padding: 24, background: 'var(--bg-subtle)', display: 'flex', justifyContent: 'center', alignItems: 'flex-start' }}>
          <div style={{
            width: 800 * (zoom / 100), minHeight: 1000 * (zoom / 100),
            background: 'white', boxShadow: '0 4px 20px var(--shadow)',
            padding: '40px 48px', color: '#222',
            fontFamily: 'sans-serif', fontSize: 11 * (zoom / 100),
          }}>
            {/* Mock packing list rendering */}
            <div style={{ background: '#131C2E', color: 'white', padding: '14px 20px', textAlign: 'center', fontWeight: 700, letterSpacing: '0.05em', marginBottom: 16, fontSize: 14 * (zoom / 100) }}>
              SHIPMENT PACKING LIST
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 9 * (zoom / 100), fontWeight: 700, color: '#666', textTransform: 'uppercase', marginBottom: 4 }}>Bill to:</div>
                <div style={{ fontWeight: 700 }}>Juliany EOOD</div>
                <div>G.S. Rakovski №70</div>
                <div>1000 Sofia, Bulgaria</div>
                <div>VAT UE: BG121281167</div>
              </div>
              <div>
                <div style={{ fontSize: 9 * (zoom / 100), fontWeight: 700, color: '#666', textTransform: 'uppercase', marginBottom: 4 }}>Ship to:</div>
                <div style={{ fontWeight: 700 }}>Juliany EOOD</div>
                <div>ul. Georgi Benkovski 14-16</div>
                <div>1000 Sofia, Bulgaria</div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid #ddd' }}>
              <div><strong>Invoice #:</strong> EJL/26-27/013 · PROF 70/2026</div>
              <div><strong>Dated:</strong> 07.04.2026</div>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 9.5 * (zoom / 100) }}>
              <thead>
                <tr style={{ background: '#f3f1ea' }}>
                  {['Pk Sr','Ctg','Client PO','Design No','Karat','Color','Quality','Dia Wt','Col Wt','Qty','Size','Value','Total'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', border: '1px solid #ccc', textAlign: 'left', fontSize: 9 * (zoom / 100) }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ['1','PND','PROF 70/2026','EJ-PND-0142-A','18KT','W','VS-GH','0.75','—','2','—','480.00','960.00'],
                  ['2','PND','PROF 70/2026','EJ-PND-0142-B','18KT','W','VS-GH','0.82','—','3','—','510.00','1,530.00'],
                  ['3','Loose Metal','—','LM-18W-04','18KT','W','—','—','12.40','1','—','612.00','612.00'],
                ].map((row, i) => (
                  <tr key={i}>
                    {row.map((c, j) => (
                      <td key={j} style={{ padding: '5px 8px', border: '1px solid #ddd' }}>{c}</td>
                    ))}
                  </tr>
                ))}
                <tr style={{ background: '#f3f1ea', fontWeight: 700 }}>
                  <td colSpan="9" style={{ padding: '6px 8px', border: '1px solid #ccc', textAlign: 'right' }}>Grand Total</td>
                  <td style={{ padding: '6px 8px', border: '1px solid #ccc' }}>6</td>
                  <td colSpan="2" style={{ padding: '6px 8px', border: '1px solid #ccc' }}></td>
                  <td style={{ padding: '6px 8px', border: '1px solid #ccc' }}>3,102.00</td>
                </tr>
              </tbody>
            </table>
            <div style={{ marginTop: 16, fontSize: 10 * (zoom / 100), color: '#666' }}>No frt charges.</div>
          </div>
        </div>

        {/* Side panel */}
        <div style={{
          width: 320, flexShrink: 0, borderLeft: '1px solid var(--border)',
          background: 'var(--card)', overflowY: 'auto', padding: 20,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 12 }}>Document metadata</div>
          {meta.map(m => (
            <div key={m.label} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 2 }}>{m.label}</div>
              <div style={{ fontSize: 12.5, color: 'var(--text)', fontFamily: m.label === 'Hash' || m.label.includes('#') ? 'monospace' : undefined, wordBreak: 'break-all' }}>{m.value}</div>
            </div>
          ))}

          <div style={{ height: 1, background: 'var(--border)', margin: '20px 0' }} />
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Linked entities</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>→ Shipment SHP-2026-0142</a>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>→ AWB DHL-1234567890</a>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>→ TempPurchase (3 lines)</a>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>→ Proforma PROF 70/2026</a>
          </div>

          <div style={{ height: 1, background: 'var(--border)', margin: '20px 0' }} />
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Other documents in this shipment</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {['Commercial Invoice EJL/26-27/013', 'AWB Print', 'SAD ZC429', 'PZ Receipt'].map(name => (
              <div key={name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', background: 'var(--bg-subtle)', borderRadius: 6, fontSize: 12 }}>
                <span style={{ color: 'var(--text-2)' }}>{name}</span>
                <Btn small variant="ghost">View</Btn>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── MOVE STOCK MODAL ───────────────────────────────────────────────────
function MoveStockModal({ onClose }) {
  const [moveType, setMoveType] = React.useState('wh-wh'); // wh-wh | stage
  const [from, setFrom] = React.useState('main');
  const [to, setTo] = React.useState('branch');
  const [stage, setStage] = React.useState('sample');
  const [su, setSu] = React.useState('SU-2604-00012');
  const [qty, setQty] = React.useState(1);
  const [reason, setReason] = React.useState('');

  const fld = {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
    background: 'var(--card)', outline: 'none',
  };
  const lbl = { display: 'block', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', marginBottom: 5, letterSpacing: '0.06em', textTransform: 'uppercase' };

  const physicalWarehouses = [
    { id: 'main',   label: 'Główny — main warehouse (Warsaw)' },
    { id: 'branch', label: 'Branch — Sofia office' },
    { id: 'safe',   label: 'Safe vault — high-value' },
    { id: 'trade',  label: 'Trade fair — Vicenza booth' },
  ];
  const stageDestinations = [
    { id: 'sample',      label: 'Sample Out — issued to salesperson / client' },
    { id: 'consignment', label: 'Consignment — to client on consignment terms' },
    { id: 'producer',    label: 'Return to Producer — RTP' },
    { id: 'tempSale',    label: 'Temp Sale — reserve against proforma' },
  ];

  return (
    <window.Modal title="Move Stock" onClose={onClose} wide>
      {/* Type toggle */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 18, padding: 4, background: 'var(--bg-subtle)', borderRadius: 8, border: '1px solid var(--border)' }}>
        {[
          { id: 'wh-wh', title: 'Warehouse → Warehouse', desc: 'Physical location transfer' },
          { id: 'stage', title: 'Stage transition',      desc: 'Main → Sample / Consignment / RTP' },
        ].map(opt => (
          <button key={opt.id} onClick={() => setMoveType(opt.id)} style={{
            padding: '12px 14px', textAlign: 'left', borderRadius: 6, cursor: 'pointer',
            background: moveType === opt.id ? 'var(--card)' : 'transparent',
            border: moveType === opt.id ? '1px solid var(--accent)' : '1px solid transparent',
            boxShadow: moveType === opt.id ? '0 1px 2px var(--shadow)' : 'none',
          }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text)' }}>{opt.title}</div>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{opt.desc}</div>
          </button>
        ))}
      </div>

      {/* Stock unit + qty */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12, marginBottom: 14 }}>
        <div>
          <label style={lbl}>Stock unit</label>
          <input value={su} onChange={e => setSu(e.target.value)} style={{ ...fld, fontFamily: 'monospace' }} placeholder="SU-…" />
          <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 4 }}>EJ-PND-0142-A · 18KT W · BAG-2604-A · 2 pcs available</div>
        </div>
        <div>
          <label style={lbl}>Quantity</label>
          <input type="number" value={qty} onChange={e => setQty(e.target.value)} style={fld} min="1" />
        </div>
      </div>

      {/* From / To */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <div>
          <label style={lbl}>From</label>
          <select value={from} onChange={e => setFrom(e.target.value)} style={fld}>
            {physicalWarehouses.map(w => <option key={w.id} value={w.id}>{w.label}</option>)}
          </select>
        </div>
        <div>
          <label style={lbl}>{moveType === 'wh-wh' ? 'To warehouse' : 'To stage'}</label>
          {moveType === 'wh-wh' ? (
            <select value={to} onChange={e => setTo(e.target.value)} style={fld}>
              {physicalWarehouses.filter(w => w.id !== from).map(w => <option key={w.id} value={w.id}>{w.label}</option>)}
            </select>
          ) : (
            <select value={stage} onChange={e => setStage(e.target.value)} style={fld}>
              {stageDestinations.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* Stage-specific fields */}
      {moveType === 'stage' && (stage === 'sample' || stage === 'consignment') && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <div>
            <label style={lbl}>{stage === 'sample' ? 'Issued to' : 'Consignee'}</label>
            <input style={fld} placeholder={stage === 'sample' ? 'Anna K. (Sales)' : 'Juliany EOOD'} />
          </div>
          <div>
            <label style={lbl}>Return by</label>
            <input type="date" style={fld} />
          </div>
        </div>
      )}

      {/* Reason / notes */}
      <div style={{ marginBottom: 18 }}>
        <label style={lbl}>Reason / notes</label>
        <textarea value={reason} onChange={e => setReason(e.target.value)} rows="2" style={{ ...fld, resize: 'vertical', fontFamily: 'inherit' }} placeholder="Optional — visible in audit log" />
      </div>

      {/* Audit preview */}
      <div style={{ padding: '12px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, marginBottom: 18 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>Audit ledger entry (preview)</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'monospace' }}>
          {moveType === 'wh-wh' ? 'TRANSFER' : 'STAGE-MOVE'} · {su} · qty {qty} · {from} → {moveType === 'wh-wh' ? to : stage} · by anna.k · {new Date().toISOString().slice(0, 19).replace('T', ' ')}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <window.Btn variant="outline" onClick={onClose}>Cancel</window.Btn>
        <window.Btn variant="gold" onClick={() => { window.dispatchEvent(new CustomEvent('inv:jump', { detail: { tab: moveType === 'stage' && stage === 'sample' ? 'sampleOut' : moveType === 'stage' && stage === 'consignment' ? 'consignment' : moveType === 'stage' && stage === 'producer' ? 'producerReturn' : moveType === 'stage' && stage === 'tempSale' ? 'tempSale' : 'finalStock' } })); onClose(); }}>Confirm move</window.Btn>
      </div>
    </window.Modal>
  );
}

// ── UPLOAD DOCUMENT MODAL ──────────────────────────────────────────────
function UploadDocumentModal({ onClose, onRoute }) {
  const [docType, setDocType] = React.useState('packingList');

  const docTypes = [
    { id: 'packingList',   label: 'Packing List',         desc: 'Supplier shipment lines',          route: 'tempPurchase',  badge: 'S1' },
    { id: 'purchaseInv',   label: 'Purchase Invoice',     desc: 'Supplier commercial invoice',      route: 'tempPurchase',  badge: 'S1' },
    { id: 'arrivalNote',   label: 'Arrival / Receipt',    desc: 'Goods arrived at warehouse',       route: 'tempWarehouse', badge: 'S1' },
    { id: 'transferNote',  label: 'Internal Transfer',    desc: 'Warehouse → warehouse',            route: 'finalStock',    badge: 'S2' },
    { id: 'sampleIssue',   label: 'Sample Issue Form',    desc: 'Goods issued out as samples',      route: 'sampleOut',     badge: 'S2' },
    { id: 'sampleReturn',  label: 'Sample Return Slip',   desc: 'Sample returned, awaiting QC',     route: 'sampleReturn',  badge: 'S2' },
    { id: 'rmaForm',       label: 'Client RMA Form',      desc: 'Goods return from client',         route: 'clientReturn',  badge: 'S2' },
    { id: 'rtpForm',       label: 'Return to Producer',   desc: 'RTP outbound to supplier',         route: 'producerReturn',badge: 'S2' },
    { id: 'consignment',   label: 'Consignment Note',     desc: 'Stock held on consignment',        route: 'consignment',   badge: 'S2' },
    { id: 'other',         label: 'Other Document',       desc: 'Will be filed for manual review',  route: 'overview',      badge: '—' },
  ];

  const selected = docTypes.find(d => d.id === docType);

  return (
    <window.Modal title="Upload Document" onClose={onClose} wide>
      <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 14 }}>
        Drop a file and choose its type — the system will route it to the matching inventory tab and pre-fill what it can extract.
      </div>

      {/* Drop zone */}
      <div style={{
        border: '2px dashed var(--border)', borderRadius: 10, padding: '32px 18px',
        textAlign: 'center', background: 'var(--bg-subtle)', marginBottom: 18,
      }}>
        <div style={{ fontSize: 28, color: 'var(--text-3)', marginBottom: 6 }}>↑</div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Drag a file here, or click to browse</div>
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>PDF · XLSX · DOCX · PNG / JPG · max 25 MB</div>
      </div>

      {/* Doc type picker */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-2)', marginBottom: 8, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Document type</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          {docTypes.map(d => {
            const active = docType === d.id;
            return (
              <button key={d.id} onClick={() => setDocType(d.id)} style={{
                padding: '10px 12px', textAlign: 'left', borderRadius: 6, cursor: 'pointer',
                background: active ? 'var(--card)' : 'transparent',
                border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{d.label}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{d.desc}</div>
                </div>
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
                  background: d.badge === 'S1' ? 'var(--badge-amber-bg)' : d.badge === 'S2' ? 'var(--badge-blue-bg)' : 'var(--badge-neutral-bg)',
                  color:      d.badge === 'S1' ? 'var(--badge-amber-text)' : d.badge === 'S2' ? 'var(--badge-blue-text)' : 'var(--badge-neutral-text)',
                  border:    `1px solid ${d.badge === 'S1' ? 'var(--badge-amber-border)' : d.badge === 'S2' ? 'var(--badge-blue-border)' : 'var(--badge-neutral-border)'}`,
                  flexShrink: 0,
                }}>{d.badge}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Route preview */}
      <div style={{ padding: '12px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, marginBottom: 18 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>Will be routed to</div>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
          Inventory › {selected?.label} → <span style={{ color: 'var(--accent)' }}>{selected?.route === 'tempPurchase' ? 'Temp Purchase' : selected?.route === 'tempWarehouse' ? 'Temp Warehouse' : selected?.route === 'sampleOut' ? 'Sample Out' : selected?.route === 'sampleReturn' ? 'Sample Return' : selected?.route === 'clientReturn' ? 'Goods Return from Client' : selected?.route === 'producerReturn' ? 'Return to Producer' : selected?.route === 'consignment' ? 'Consignment' : selected?.route === 'finalStock' ? 'Final Stock' : 'Overview'}</span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <window.Btn variant="outline" onClick={onClose}>Cancel</window.Btn>
        <window.Btn variant="gold" onClick={() => onRoute(selected?.route || 'overview')}>Upload &amp; route</window.Btn>
      </div>
    </window.Modal>
  );
}

Object.assign(window, { InventoryPage, DocumentViewerPage });
