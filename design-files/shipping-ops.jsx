// ──────────────────────────────────────────────────────────────────────────
// shipping-ops.jsx
// Future-planned module: Carrier Shipment & Label Operations
// All carrier integrations are wireframe placeholders — no real fetches,
// no rate quotes, no AWB generation. Status chips: Planned · Backend pending ·
// API required · Carrier approval required.
// ──────────────────────────────────────────────────────────────────────────

// ── Status chip aliases for shipping-specific levels ──────────────────────
function ShipStatus({ kind = 'planned', label }) {
  const map = {
    planned:        { dot:'#7E63C9', bg:'var(--badge-purple-bg)', text:'var(--badge-purple-text)', border:'var(--badge-purple-border)', default:'Planned' },
    backend:        { dot:'#9CA8B8', bg:'var(--badge-neutral-bg)',text:'var(--badge-neutral-text)',border:'var(--badge-neutral-border)',default:'Backend pending' },
    api:            { dot:'#1A4A90', bg:'var(--badge-blue-bg)',   text:'var(--badge-blue-text)',   border:'var(--badge-blue-border)',   default:'API required' },
    carrier:        { dot:'#902018', bg:'var(--badge-red-bg)',    text:'var(--badge-red-text)',    border:'var(--badge-red-border)',    default:'Carrier approval required' },
    temporary:      { dot:'#D4A853', bg:'var(--badge-amber-bg)',  text:'var(--badge-amber-text)',  border:'var(--badge-amber-border)',  default:'Temporary' },
  };
  const s = map[kind] || map.planned;
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:5,
      background:s.bg, color:s.text, border:`1px solid ${s.border}`,
      padding:'2px 8px', borderRadius:10, fontSize:10, fontWeight:600,
      letterSpacing:'0.02em', whiteSpace:'nowrap',
    }}>
      <span style={{ width:6, height:6, borderRadius:'50%', background:s.dot }}/>
      {label || s.default}
    </span>
  );
}

function DisBtn({ children, kind='backend', primary=false }) {
  return (
    <button disabled title="Backend / carrier integration not yet implemented" style={{
      padding:'6px 12px', fontSize:11, fontWeight:600, borderRadius:6,
      border: primary ? '1px solid var(--accent-border)' : '1px solid var(--border)',
      background: primary ? 'var(--accent-subtle)' : 'var(--bg-subtle)',
      color: 'var(--text-3)', cursor:'not-allowed',
      display:'inline-flex', alignItems:'center', gap:6, opacity:0.85,
    }}>
      {children}
      <ShipStatus kind={kind}/>
    </button>
  );
}

// ── Shipping ops main page ────────────────────────────────────────────────
const SHIPMENTS = [
  { id:'SHP-2412-441', awb:'— pending —',  carrier:'DHL Express', client:'Aurum Trading',   docs:['PI 2025/0418','PZ 2412-441'], pkgs:3, weight:'4.85 kg', state:'Temp · pre-execute',     stage:0 },
  { id:'SHP-2412-440', awb:'1Z 994 …7714', carrier:'FedEx IP',    client:'Levi Joaillerie', docs:['INV 2025/0405'],              pkgs:1, weight:'0.32 kg', state:'In transit · exception',  stage:3 },
  { id:'SHP-2412-439', awb:'7799 1184 22', carrier:'DHL Express', client:'Maison Élise',    docs:['INV 2025/0399','PZ 2412-301'],pkgs:2, weight:'1.24 kg', state:'Delivered',               stage:5 },
  { id:'SHP-2412-438', awb:'— failed —',   carrier:'DHL Express', client:'Aurum Trading',   docs:['PI 2025/0410'],               pkgs:5, weight:'8.10 kg', state:'Carrier rejected',        stage:1 },
];

function ShipmentTimelineMini({ stage }) {
  const stages = ['Created','Labels','In transit','Customs','Out for delivery','Delivered'];
  return (
    <div style={{ display:'flex', gap:4, alignItems:'center' }}>
      {stages.map((s, i) => (
        <React.Fragment key={s}>
          <div title={s} style={{
            width:8, height:8, borderRadius:'50%',
            background: i < stage ? '#22A06B' : i === stage ? 'var(--accent)' : 'var(--border)',
          }}/>
          {i < stages.length-1 && <div style={{ width:14, height:1, background: i < stage ? '#22A06B' : 'var(--border)' }}/>}
        </React.Fragment>
      ))}
    </div>
  );
}

function ShippingOpsPage() {
  const [tab, setTab] = React.useState('queue');
  const tabs = [
    ['queue',    'Shipment Queue'],
    ['create',   'Create Shipment'],
    ['packages', 'Package Builder'],
    ['labels',   'Label Preview & Print'],
    ['timeline', 'Shipment + Tracking Timeline'],
    ['handoff',  'Warehouse → Carrier Handoff'],
    ['returns',  'Return Shipments'],
    ['audit',    'Audit Log'],
    ['integrations','Integration Map'],
  ];

  return (
    <div style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
      {/* Sub-tab strip */}
      <div style={{
        display:'flex', gap:2, padding:'0 32px', borderBottom:'1px solid var(--border)',
        background:'var(--bg-subtle)', flexShrink:0, overflowX:'auto',
      }}>
        {tabs.map(([id, label]) => (
          <button key={id} onClick={()=>setTab(id)} style={{
            padding:'9px 14px', background:'transparent', border:'none',
            borderBottom: tab===id ? '2px solid var(--accent)' : '2px solid transparent',
            color: tab===id ? 'var(--text)' : 'var(--text-2)',
            fontSize:12, fontWeight: tab===id ? 700 : 500, cursor:'pointer', whiteSpace:'nowrap',
          }}>{label}</button>
        ))}
      </div>

      <div style={{ flex:1, overflowY:'auto', padding:'18px 32px 32px' }}>
        {tab==='queue'        && <SOQueue/>}
        {tab==='create'       && <SOCreate/>}
        {tab==='packages'     && <SOPackages/>}
        {tab==='labels'       && <SOLabels/>}
        {tab==='timeline'     && <SOTimeline/>}
        {tab==='handoff'      && <SOHandoff/>}
        {tab==='returns'      && <SOReturns/>}
        {tab==='audit'        && <SOAudit/>}
        {tab==='integrations' && <SOIntegrations/>}
      </div>
    </div>
  );
}

// ── Tab 1: Queue ──────────────────────────────────────────────────────────
function SOQueue() {
  return (
    <>
      <div style={{ display:'flex', gap:12, marginBottom:14 }}>
        {[
          ['Open',          '4'],
          ['Pending pickup','2'],
          ['In transit',    '7'],
          ['Exceptions',    '1'],
          ['Delivered (7d)','18'],
        ].map(([k,v])=> (
          <div key={k} style={{ flex:1, padding:'10px 14px', background:'var(--card)', border:'1px solid var(--border)', borderRadius:8 }}>
            <div style={{ fontFamily:'"DM Serif Display", serif', fontSize:24, color:'var(--text)' }}>{v}</div>
            <div style={{ fontSize:10, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em' }}>{k}</div>
          </div>
        ))}
      </div>

      <div style={{ display:'flex', gap:8, marginBottom:10 }}>
        <DisBtn primary kind="api">+ New shipment</DisBtn>
        <DisBtn kind="api">Bulk dispatch</DisBtn>
        <DisBtn kind="carrier">Pickup request</DisBtn>
        <DisBtn kind="api">Generate manifest</DisBtn>
        <span style={{ flex:1 }}/>
        <ShipStatus kind="api" label="DHL Express API · not connected"/>
        <ShipStatus kind="api" label="FedEx API · not connected"/>
      </div>

      <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
          <thead>
            <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
              {['Shipment','AWB','Carrier','Client / Consignee','Linked docs','Pkgs','Weight','Lifecycle','State',''].map(h=>
                <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {SHIPMENTS.map(s => (
              <tr key={s.id} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text-2)' }}>{s.id}</td>
                <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text)' }}>{s.awb}</td>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{s.carrier}</td>
                <td style={{ padding:'8px 10px', color:'var(--text)' }}>{s.client}</td>
                <td style={{ padding:'8px 10px' }}>
                  {s.docs.map(d => (
                    <span key={d} style={{ display:'inline-block', marginRight:4, padding:'1px 6px', background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:4, fontSize:10, color:'var(--text)' }}>{d}</span>
                  ))}
                </td>
                <td style={{ padding:'8px 10px', color:'var(--text)' }}>{s.pkgs}</td>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{s.weight}</td>
                <td style={{ padding:'8px 10px' }}><ShipmentTimelineMini stage={s.stage}/></td>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{s.state}</td>
                <td style={{ padding:'8px 10px', textAlign:'right' }}>
                  <DisBtn kind="api">Open</DisBtn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding:'10px 12px', background:'var(--bg-subtle)', fontSize:11, color:'var(--text-3)', borderTop:'1px solid var(--border-subtle)' }}>
          Wireframe data — no carrier integration. AWBs, weights, and states are illustrative only.
        </div>
      </div>
    </>
  );
}

// ── Tab 2: Create Shipment ────────────────────────────────────────────────
function SOCreate() {
  const F = ({ label, value, hint, mono=false }) => (
    <div style={{ marginBottom:10 }}>
      <div style={{ fontSize:10, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:3 }}>{label}</div>
      <div style={{ fontSize:12, color:'var(--text)', fontFamily: mono ? 'ui-monospace, monospace' : 'inherit' }}>{value}</div>
      {hint && <div style={{ fontSize:10, color:'var(--text-3)', marginTop:2 }}>{hint}</div>}
    </div>
  );

  return (
    <div style={{ display:'flex', gap:18 }}>
      {/* Form */}
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
          <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>New shipment · operational form</h3>
          <ShipStatus kind="backend"/>
          <ShipStatus kind="api"/>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
          {/* Sender / receiver */}
          <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
            <div style={{ fontWeight:700, fontSize:12, color:'var(--text)', marginBottom:8 }}>Shipper</div>
            <F label="Account" value="Estrella Jewels Sp. z o.o."/>
            <F label="Address" value="ul. Krucza 12, 00-001 Warszawa, PL"/>
            <F label="Carrier account" value="DHL · 950-1234567" mono/>
          </div>
          <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
            <div style={{ fontWeight:700, fontSize:12, color:'var(--text)', marginBottom:8 }}>Consignee</div>
            <F label="Client" value="Aurum Trading Ltd. · pulled from Master"/>
            <F label="Address" value="34 Hatton Garden, London EC1N, UK"/>
            <F label="Carrier accounts" value="DHL: 410-998877 · FedEx: 612-001-449" mono/>
          </div>
          {/* Service */}
          <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
            <div style={{ fontWeight:700, fontSize:12, color:'var(--text)', marginBottom:8 }}>Service</div>
            <F label="Carrier" value="DHL Express  ·  FedEx IP  ·  FedEx IE"/>
            <F label="Service level" value="Worldwide Express · Economy Select" hint="Live rate query · API required"/>
            <F label="Incoterm" value="DAP · DDP · CIP"/>
            <F label="Insurance" value="Declared value · KUKE-linked" hint="Pulled from client KYC"/>
          </div>
          {/* Customs */}
          <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
            <div style={{ fontWeight:700, fontSize:12, color:'var(--text)', marginBottom:8 }}>Customs</div>
            <F label="Reason for export" value="Sale · Sample · Repair · Return"/>
            <F label="Commercial invoice" value="INV 2025/0418  ·  attach" hint="Auto-link from sales module"/>
            <F label="CN23 / EAD / EUR.1" value="Generate from PZ data" hint="Backend pending"/>
            <F label="HS codes" value="711319 · 711719 · pulled from line items"/>
          </div>
        </div>

        <div style={{ marginTop:14, display:'flex', gap:8 }}>
          <DisBtn kind="temporary">Save as Temporary</DisBtn>
          <DisBtn kind="api">Validate with carrier</DisBtn>
          <DisBtn kind="api" primary>Generate AWB &amp; Labels</DisBtn>
          <DisBtn kind="carrier">Cancel shipment</DisBtn>
        </div>
      </div>

      {/* Right rail — linked docs + status */}
      <aside style={{ width:280, flexShrink:0, display:'flex', flexDirection:'column', gap:10 }}>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Linked documents</div>
          {['PI 2025/0418','INV 2025/0418','PZ 2412-441','Order O-9933'].map(d => (
            <div key={d} style={{ display:'flex', justifyContent:'space-between', padding:'6px 0', borderBottom:'1px solid var(--border-subtle)', fontSize:11 }}>
              <span style={{ color:'var(--text)', fontFamily:'ui-monospace, monospace' }}>{d}</span>
              <a href="#" style={{ color:'var(--accent-text)', fontSize:10, fontWeight:600 }}>view</a>
            </div>
          ))}
        </div>
        <div style={{ background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Carrier integration</div>
          <ul style={{ margin:0, paddingLeft:16, fontSize:11, color:'var(--text-2)', lineHeight:1.7 }}>
            <li>DHL Express API · <strong>not connected</strong></li>
            <li>FedEx Ship API · <strong>not connected</strong></li>
            <li>Label render service · pending</li>
            <li>Pickup scheduling · pending</li>
          </ul>
        </div>
      </aside>
    </div>
  );
}

// ── Tab 3: Package Builder (Multi-package grid) ──────────────────────────
function SOPackages() {
  const pkgs = [
    { idx:1, type:'Box S',  l:25, w:18, h:8,  weight:0.85, items:'4 × ring boxes',           barcode:'EJP-441-01' },
    { idx:2, type:'Box M',  l:35, w:25, h:12, weight:1.60, items:'2 × pendant trays',        barcode:'EJP-441-02' },
    { idx:3, type:'Soft',   l:20, w:14, h:5,  weight:0.40, items:'documents · invoice copy', barcode:'EJP-441-03' },
  ];
  const total = pkgs.reduce((a,p)=>a+p.weight, 0).toFixed(2);

  return (
    <>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Multi-package grid</h3>
        <ShipStatus kind="backend"/>
        <span style={{ flex:1 }}/>
        <DisBtn kind="api">+ Add package</DisBtn>
        <DisBtn kind="api">Group selected</DisBtn>
        <DisBtn kind="api">Scan barcode</DisBtn>
      </div>

      <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden', marginBottom:14 }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
          <thead>
            <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
              {['#','Type','L (cm)','W (cm)','H (cm)','Weight (kg)','Items','Barcode','Label',''].map(h=>
                <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {pkgs.map(p=> (
              <tr key={p.idx} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{p.idx}</td>
                <td style={{ padding:'8px 10px', color:'var(--text)' }}>{p.type}</td>
                <td style={{ padding:'8px 10px' }}>{p.l}</td>
                <td style={{ padding:'8px 10px' }}>{p.w}</td>
                <td style={{ padding:'8px 10px' }}>{p.h}</td>
                <td style={{ padding:'8px 10px', fontWeight:600, color:'var(--text)' }}>{p.weight}</td>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{p.items}</td>
                <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text)' }}>{p.barcode}</td>
                <td style={{ padding:'8px 10px' }}><ShipStatus kind="api" label="Pending"/></td>
                <td style={{ padding:'8px 10px', textAlign:'right' }}>
                  <DisBtn kind="api">Edit</DisBtn>
                </td>
              </tr>
            ))}
            <tr style={{ background:'var(--bg-subtle)' }}>
              <td colSpan={5} style={{ padding:'8px 10px', textAlign:'right', color:'var(--text-2)', fontWeight:600 }}>Total weight</td>
              <td style={{ padding:'8px 10px', fontWeight:700, color:'var(--text)' }}>{total} kg</td>
              <td colSpan={4}/>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Package grouping</div>
          <p style={{ fontSize:11, color:'var(--text-2)', lineHeight:1.7, margin:0 }}>
            Group multi-piece consignments under one master AWB. Children pieces share customs and tracking events; each piece prints its own label with sequence (1/3, 2/3…).
          </p>
        </div>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Scanner integration</div>
          <p style={{ fontSize:11, color:'var(--text-2)', lineHeight:1.7, margin:0 }}>
            Hand scanner / phone camera reads EJP barcodes to auto-fill weight + dimensions from a connected scale. <ShipStatus kind="planned"/>
          </p>
        </div>
      </div>
    </>
  );
}

// ── Tab 4: Label Preview & Print Queue ────────────────────────────────────
function SOLabels() {
  const queue = [
    { id:'PRN-0042', shipment:'SHP-2412-441', pieces:'1/3',  doc:'AWB label',     paper:'A6 thermal · 4×6"', state:'queued',     level:'api' },
    { id:'PRN-0041', shipment:'SHP-2412-441', pieces:'2/3',  doc:'AWB label',     paper:'A6 thermal · 4×6"', state:'queued',     level:'api' },
    { id:'PRN-0040', shipment:'SHP-2412-441', pieces:'3/3',  doc:'AWB label',     paper:'A6 thermal · 4×6"', state:'queued',     level:'api' },
    { id:'PRN-0039', shipment:'SHP-2412-441', pieces:'—',    doc:'Commercial inv.',paper:'A4',                state:'queued',     level:'api' },
    { id:'PRN-0038', shipment:'SHP-2412-441', pieces:'—',    doc:'CN23',           paper:'A4',                state:'queued',     level:'backend' },
    { id:'PRN-0037', shipment:'SHP-2412-440', pieces:'1/1',  doc:'AWB label',     paper:'A6 thermal · 4×6"', state:'printed',    level:'api' },
    { id:'PRN-0036', shipment:'SHP-2412-440', pieces:'—',    doc:'Manifest',       paper:'A4',                state:'printed',    level:'api' },
  ];
  return (
    <div style={{ display:'flex', gap:18 }}>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
          <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Print queue</h3>
          <ShipStatus kind="api" label="Label PDF render · pending"/>
          <span style={{ flex:1 }}/>
          <DisBtn kind="api" primary>Print all</DisBtn>
          <DisBtn kind="api">Reprint selected</DisBtn>
          <DisBtn kind="api">Export PDF</DisBtn>
        </div>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
            <thead>
              <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
                {['Job','Shipment','Piece','Document','Paper','State',''].map(h=>
                  <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {queue.map(j => (
                <tr key={j.id} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                  <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text-2)' }}>{j.id}</td>
                  <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text)' }}>{j.shipment}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{j.pieces}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text)' }}>{j.doc}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{j.paper}</td>
                  <td style={{ padding:'8px 10px' }}><ShipStatus kind={j.level} label={j.state==='printed'?'Printed':'Queued'}/></td>
                  <td style={{ padding:'8px 10px', textAlign:'right' }}>
                    <DisBtn kind="api">Preview</DisBtn>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Label preview window */}
      <aside style={{ width:340, flexShrink:0 }}>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:10 }}>
            <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Label preview</div>
            <ShipStatus kind="api"/>
          </div>
          {/* Wireframe label */}
          <div style={{
            aspectRatio:'4/6', background:'#fff', border:'1.5px dashed var(--accent-border)',
            borderRadius:6, padding:10, fontSize:9, fontFamily:'ui-monospace, monospace',
            color:'var(--text)', display:'flex', flexDirection:'column', gap:6,
          }}>
            <div style={{ display:'flex', justifyContent:'space-between' }}><b>DHL EXPRESS</b><span>1/3</span></div>
            <div style={{ height:1, background:'var(--text)' }}/>
            <div>FROM: Estrella Jewels Sp. z o.o.</div>
            <div>ul. Krucza 12, 00-001 Warszawa, PL</div>
            <div style={{ height:1, background:'var(--border)' }}/>
            <div>TO: Aurum Trading Ltd.</div>
            <div>34 Hatton Garden, London EC1N, UK</div>
            <div style={{ height:1, background:'var(--border)' }}/>
            <div style={{ background:'#000', height:38, borderRadius:2, display:'flex', alignItems:'center', justifyContent:'center', color:'#fff', fontSize:10 }}>‖█▌▌█‖▌█‖▌█  AWB pending</div>
            <div style={{ display:'flex', justifyContent:'space-between' }}>
              <div>WP-EXPRESS</div>
              <div>0.85 kg</div>
            </div>
            <div style={{ display:'flex', justifyContent:'center', alignItems:'center', flex:1, color:'var(--text-3)', fontStyle:'italic' }}>— wireframe —</div>
          </div>
        </div>
      </aside>
    </div>
  );
}

// ── Tab 5: Shipment + Tracking unified timeline ───────────────────────────
function SOTimeline() {
  const events = [
    { ts:'12 May · 14:42', stage:'Shipment created',                   kind:'op',     by:'operator · MK',  status:'done' },
    { ts:'12 May · 14:44', stage:'Packages built · 3 pieces',           kind:'op',     by:'operator · MK',  status:'done' },
    { ts:'12 May · 14:46', stage:'Labels generated · DHL Express',      kind:'carrier',by:'API',            status:'pending', level:'api' },
    { ts:'12 May · 15:10', stage:'Pickup requested',                    kind:'carrier',by:'API',            status:'pending', level:'carrier' },
    { ts:'12 May · 17:30', stage:'Picked up by courier',                kind:'carrier',by:'DHL',            status:'pending', level:'api' },
    { ts:'13 May · 02:14', stage:'Departed origin facility · WAW',      kind:'tracking',by:'DHL feed',      status:'pending', level:'api' },
    { ts:'13 May · 06:48', stage:'Customs export · cleared',            kind:'tracking',by:'DHL feed',      status:'pending', level:'api' },
    { ts:'13 May · 09:30', stage:'Arrived destination facility · LHR',  kind:'tracking',by:'DHL feed',      status:'pending', level:'api' },
    { ts:'13 May · 11:00', stage:'Customs import · clearance',          kind:'tracking',by:'DHL feed',      status:'pending', level:'api' },
    { ts:'13 May · 14:20', stage:'Out for delivery',                    kind:'tracking',by:'DHL feed',      status:'pending', level:'api' },
    { ts:'13 May · 16:45', stage:'Delivered · signed B. Patel',         kind:'tracking',by:'DHL feed',      status:'pending', level:'api' },
  ];
  const dot = e => e.status==='done' ? '#22A06B' : 'var(--border)';
  return (
    <>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Shipment + tracking · unified timeline</h3>
        <ShipStatus kind="api" label="Tracking event ingestion · pending"/>
      </div>
      <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:'14px 18px' }}>
        {events.map((e, i) => (
          <div key={i} style={{ display:'flex', alignItems:'flex-start', gap:14, padding:'8px 0', borderBottom: i<events.length-1 ? '1px solid var(--border-subtle)' : 'none' }}>
            <div style={{ width:80, fontSize:11, color:'var(--text-3)', fontFamily:'ui-monospace, monospace', flexShrink:0 }}>{e.ts}</div>
            <div style={{ width:8, height:8, borderRadius:'50%', background:dot(e), marginTop:4, flexShrink:0 }}/>
            <div style={{ flex:1 }}>
              <div style={{ fontSize:12, color:'var(--text)', fontWeight:600 }}>{e.stage}</div>
              <div style={{ fontSize:10, color:'var(--text-3)', marginTop:1 }}>{e.kind} · {e.by}</div>
            </div>
            {e.level && <ShipStatus kind={e.level}/>}
          </div>
        ))}
      </div>
    </>
  );
}

// ── Tab 6: Warehouse → Carrier handoff ────────────────────────────────────
function SOHandoff() {
  return (
    <>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Warehouse → Carrier handoff</h3>
        <ShipStatus kind="backend"/>
      </div>
      <p style={{ fontSize:12, color:'var(--text-2)', marginBottom:14, maxWidth:780, lineHeight:1.7 }}>
        Operational flow for the moment goods leave Final Stock and are tendered to the courier. Each step records
        the operator, scan timestamp, and signature. Direct dispatch from a DHL warehouse skips steps 1–2.
      </p>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:10, marginBottom:14 }}>
        {[
          ['1 · Pick',         'Pick list scanned · qty confirmed',      'op'],
          ['2 · Pack',         'Items packed · weight + dim recorded',   'op'],
          ['3 · Label',        'Labels printed · pieces matched',         'api'],
          ['4 · Tender',       'Courier scan · Out For Carriage',         'carrier'],
          ['5 · Manifest',     'EOD manifest closed · day signed off',    'api'],
        ].map(([t, d, k]) => (
          <div key={t} style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:12 }}>
            <div style={{ fontWeight:700, fontSize:12, color:'var(--text)', marginBottom:6 }}>{t}</div>
            <div style={{ fontSize:11, color:'var(--text-2)', marginBottom:10, lineHeight:1.5 }}>{d}</div>
            <ShipStatus kind={k==='op'?'backend':k==='api'?'api':'carrier'}/>
          </div>
        ))}
      </div>
      <div style={{ background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:8, padding:14 }}>
        <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Direct dispatch from DHL warehouse</div>
        <p style={{ fontSize:11, color:'var(--text-2)', margin:0, lineHeight:1.7 }}>
          When goods are already on DHL premises (e.g. cross-dock from import clearance), the handoff form switches
          to a one-step "tender at facility" with a facility code selector. Manifest still closes EOD.
        </p>
      </div>
    </>
  );
}

// ── Tab 7: Return Shipments ───────────────────────────────────────────────
function SOReturns() {
  const rows = [
    ['RTN-0019','RMA-0044','Aurum Trading',     'INV 2025/0412','DHL Express','— pending —','Awaiting label',  'carrier'],
    ['RTN-0018','RMA-0043','Levi Joaillerie',   'INV 2025/0405','FedEx IE',   '7799 1184 30','In transit',     'api'],
    ['RTN-0017','RMA-0042','Maison Élise',      'INV 2025/0399','DHL Express','7799 1184 18','Delivered',       'api'],
  ];
  return (
    <>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Return shipments</h3>
        <ShipStatus kind="backend"/>
        <span style={{ flex:1 }}/>
        <DisBtn kind="api">+ Generate return label</DisBtn>
      </div>
      <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
          <thead>
            <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
              {['Return','RMA','From','Original Inv.','Carrier','AWB','State','Status'].map(h=>
                <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i) => (
              <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                {r.slice(0,7).map((c,j)=> <td key={j} style={{ padding:'8px 10px', color: j===0||j===1 ? 'var(--text)' : 'var(--text-2)', fontFamily: j===0||j===1||j===5 ? 'ui-monospace, monospace' : 'inherit', fontSize: j===0||j===1||j===5 ? 11 : 12 }}>{c}</td>)}
                <td style={{ padding:'8px 10px' }}><ShipStatus kind={r[7]}/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── Tab 8: Audit log ──────────────────────────────────────────────────────
function SOAudit() {
  const rows = [
    ['12 May · 17:30','SHP-2412-441','operator · MK','shipment.create',          'temp draft',        'api'],
    ['12 May · 17:32','SHP-2412-441','operator · MK','packages.add',             '3 pieces · 4.85 kg','backend'],
    ['12 May · 17:33','SHP-2412-441','API',           'awb.generate',             'failed · no creds', 'api'],
    ['12 May · 14:20','SHP-2412-440','operator · AS', 'shipment.cancel',          'cancelled by operator','carrier'],
    ['11 May · 09:15','SHP-2412-439','API',           'tracking.event',           'delivered · signed B.Patel','api'],
  ];
  return (
    <>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Shipment audit log</h3>
        <ShipStatus kind="backend"/>
      </div>
      <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
          <thead>
            <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
              {['Timestamp','Shipment','Actor','Event','Detail','Source'].map(h=>
                <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i)=> (
              <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text-3)' }}>{r[0]}</td>
                <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text)' }}>{r[1]}</td>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{r[2]}</td>
                <td style={{ padding:'8px 10px', color:'var(--text)', fontFamily:'ui-monospace, monospace', fontSize:11 }}>{r[3]}</td>
                <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{r[4]}</td>
                <td style={{ padding:'8px 10px' }}><ShipStatus kind={r[5]}/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── Tab 9: Carrier integration map (API dependency map) ──────────────────
function SOIntegrations() {
  const groups = [
    {
      group:'DHL Express',
      level:'api',
      apis:[
        ['POST /api/v1/shipping/dhl/quote',           'Live rate quote'],
        ['POST /api/v1/shipping/dhl/shipment',        'Create shipment + AWB'],
        ['POST /api/v1/shipping/dhl/label',           'Render label PDF'],
        ['POST /api/v1/shipping/dhl/pickup',          'Schedule pickup'],
        ['POST /api/v1/shipping/dhl/manifest',        'Close manifest'],
        ['POST /api/v1/shipping/dhl/cancel',          'Cancel shipment'],
        ['GET  /api/v1/shipping/dhl/tracking/{awb}',  'Tracking events'],
        ['POST /api/v1/shipping/dhl/return',          'Return label'],
      ]
    },
    {
      group:'FedEx (IP / IE)',
      level:'api',
      apis:[
        ['POST /api/v1/shipping/fedex/rate',          'Live rate quote'],
        ['POST /api/v1/shipping/fedex/ship',          'Create shipment + AWB'],
        ['POST /api/v1/shipping/fedex/label',         'Render label PDF'],
        ['POST /api/v1/shipping/fedex/pickup',        'Schedule pickup'],
        ['POST /api/v1/shipping/fedex/cancel',        'Cancel shipment'],
        ['GET  /api/v1/shipping/fedex/tracking/{awb}','Tracking events'],
      ]
    },
    {
      group:'Internal · execution engine',
      level:'backend',
      apis:[
        ['POST /api/v1/shipping/shipments',           'Create operational shipment record'],
        ['POST /api/v1/shipping/shipments/{id}/packages',  'Add package(s)'],
        ['POST /api/v1/shipping/shipments/{id}/execute',   'Execute · approval req.'],
        ['POST /api/v1/shipping/shipments/{id}/cancel',    'Cancel · approval req.'],
        ['POST /api/v1/shipping/shipments/{id}/temp',      'Save as Temporary'],
        ['POST /api/v1/shipping/shipments/{id}/handoff',   'Warehouse → carrier handoff'],
        ['POST /api/v1/shipping/print/queue',              'Add print job'],
        ['POST /api/v1/shipping/print/{id}/done',          'Mark printed'],
        ['POST /api/v1/shipping/customs/cn23',             'Generate CN23 from PZ'],
        ['POST /api/v1/shipping/customs/commercial-invoice','Generate from sales'],
      ]
    },
    {
      group:'Tracking event ingestion',
      level:'api',
      apis:[
        ['POST /api/v1/shipping/webhooks/dhl',        'DHL pushes events'],
        ['POST /api/v1/shipping/webhooks/fedex',      'FedEx pushes events'],
        ['POST /api/v1/shipping/sync/email-trigger',  'Email-trigger fallback for missing pushes'],
      ]
    },
  ];
  return (
    <>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Integration map · API placeholders</h3>
        <ShipStatus kind="planned"/>
      </div>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
        {groups.map(g => (
          <div key={g.group} style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
              <div style={{ fontSize:12, fontWeight:700, color:'var(--text)' }}>{g.group}</div>
              <ShipStatus kind={g.level}/>
            </div>
            <ul style={{ margin:0, paddingLeft:0, listStyle:'none', fontSize:11, color:'var(--text-2)' }}>
              {g.apis.map(([p, d]) => (
                <li key={p} style={{ display:'flex', justifyContent:'space-between', gap:10, padding:'4px 0', borderBottom:'1px solid var(--border-subtle)' }}>
                  <code style={{ fontFamily:'ui-monospace, monospace', fontSize:10.5, color:'var(--text)' }}>{p}</code>
                  <span style={{ color:'var(--text-3)', fontSize:10.5, textAlign:'right' }}>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div style={{ marginTop:14, padding:14, background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:8, fontSize:11, color:'var(--text-2)', lineHeight:1.7 }}>
        <strong style={{ color:'var(--text)' }}>Wireframe rules:</strong> No carrier integrations are live. AWBs, rates, and labels in this module are illustrative only.
        Status chips: <ShipStatus kind="planned"/> <ShipStatus kind="backend"/> <ShipStatus kind="api"/> <ShipStatus kind="carrier"/> <ShipStatus kind="temporary"/> ·
        Read-only feeds will show <em>Source · DHL feed</em> / <em>Source · FedEx feed</em> when wired.
      </div>
    </>
  );
}

Object.assign(window, { ShippingOpsPage, ShipStatus });
