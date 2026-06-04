// ──────────────────────────────────────────────────────────────────────────
// wireframe-update.jsx
// Status-aware additions for the Estrella Atlas wireframe:
//   • FeatureStatus chip (Active / Partial / Backend pending / Future)
//   • OperationalStatusStrip (top banner)
//   • CoverageMatrix page (full feature × status × API placeholder table)
//   • ActionCenter page  (operator queue — replaces scattered approval pop-ups)
//   • AutomationCenterPage (replaces the AI Bridge page; same data)
//   • Stub pages: Identity/Mapping, MoveStock, SampleOut, SampleReturn,
//                  GoodsReturn, ReturnToProducer
//
// All pages are wireframes — no real fetches, no mutations.
// Reads use "Source · wFirma" badges. Writes use "Approval required".
// ──────────────────────────────────────────────────────────────────────────

// ── 1. Feature status chip ────────────────────────────────────────────────
function FeatureStatus({ level = 'active', label }) {
  const map = {
    active:  { dot:'#22A06B', bg:'var(--badge-green-bg)',   text:'var(--badge-green-text)',   border:'var(--badge-green-border)',   default:'Active' },
    partial: { dot:'#D4A853', bg:'var(--badge-amber-bg)',   text:'var(--badge-amber-text)',   border:'var(--badge-amber-border)',   default:'Partial' },
    backend: { dot:'#9CA8B8', bg:'var(--badge-neutral-bg)', text:'var(--badge-neutral-text)', border:'var(--badge-neutral-border)', default:'Backend pending' },
    future:  { dot:'#7E63C9', bg:'var(--badge-purple-bg)',  text:'var(--badge-purple-text)',  border:'var(--badge-purple-border)',  default:'Future' },
    readonly:{ dot:'#1A4A90', bg:'var(--badge-blue-bg)',    text:'var(--badge-blue-text)',    border:'var(--badge-blue-border)',    default:'Source · wFirma' },
    approval:{ dot:'#902018', bg:'var(--badge-red-bg)',     text:'var(--badge-red-text)',     border:'var(--badge-red-border)',     default:'Approval required' },
  };
  const s = map[level] || map.active;
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:5,
      background:s.bg, color:s.text, border:`1px solid ${s.border}`,
      padding:'2px 8px', borderRadius:10, fontSize:10, fontWeight:600,
      letterSpacing:'0.02em', lineHeight:1.4, whiteSpace:'nowrap',
    }}>
      <span style={{ width:6, height:6, borderRadius:'50%', background:s.dot }}/>
      {label || s.default}
    </span>
  );
}

// Disabled control with tooltip — used for backend-pending / future controls
function PendingBtn({ label, level = 'backend', onClick }) {
  const isPending = level === 'backend' || level === 'future';
  return (
    <button
      onClick={isPending ? undefined : onClick}
      disabled={isPending}
      title={
        level === 'backend' ? 'Backend endpoint not yet implemented' :
        level === 'future'  ? 'Planned — not yet scoped' :
        level === 'approval'? 'Operator approval required before execute' : ''
      }
      style={{
        padding:'6px 12px', borderRadius:6, fontSize:12, fontWeight:600,
        border:'1px solid var(--border)',
        background: isPending ? 'var(--bg-subtle)' : 'var(--card)',
        color: isPending ? 'var(--text-3)' : 'var(--text)',
        cursor: isPending ? 'not-allowed' : 'pointer',
        display:'inline-flex', alignItems:'center', gap:6,
        opacity: isPending ? 0.7 : 1,
      }}>
      {label}
      <FeatureStatus level={level}/>
    </button>
  );
}

// ── 2. Operational Status Strip ───────────────────────────────────────────
function OperationalStatusStrip() {
  const items = [
    { name:'wFirma',        status:'ok',   meta:'last sync 4 min ago'   , level:'active' },
    { name:'DHL Inbox',     status:'ok',   meta:'2 unread, polled 30s ago', level:'active' },
    { name:'Email Queue',   status:'warn', meta:'3 awaiting approval'   , level:'partial' },
    { name:'Cliq Webhook',  status:'ok',   meta:'last event 1 min ago'  , level:'active' },
    { name:'Cowork Bridge', status:'idle', meta:'no active tasks'       , level:'partial' },
    { name:'WorkDrive',     status:'ok',   meta:'token valid · 14h left', level:'active' },
  ];
  const dotColor = s => s==='ok' ? '#22A06B' : s==='warn' ? '#D4A853' : s==='down' ? '#C0321A' : '#8A9AB0';

  return (
    <div style={{
      display:'flex', alignItems:'center', gap:18, flexWrap:'wrap',
      padding:'7px 24px', background:'var(--bg-subtle)',
      borderBottom:'1px solid var(--border)', fontSize:11,
      color:'var(--text-2)',
    }}>
      <span style={{ fontWeight:700, color:'var(--text)', letterSpacing:'0.04em' }}>System</span>
      {items.map(i => (
        <span key={i.name} style={{ display:'inline-flex', alignItems:'center', gap:6 }}>
          <span style={{ width:7, height:7, borderRadius:'50%', background:dotColor(i.status) }}/>
          <span style={{ fontWeight:600, color:'var(--text)' }}>{i.name}</span>
          <span style={{ color:'var(--text-3)' }}>· {i.meta}</span>
        </span>
      ))}
      <span style={{ flex:1 }}/>
      <a href="#" style={{ color:'var(--accent-text)', textDecoration:'underline', fontWeight:600 }}>System health →</a>
    </div>
  );
}

// ── 3. Coverage Matrix page ───────────────────────────────────────────────
const COVERAGE_ROWS = [
  // [module, feature, status, api, notes]
  ['Shipments',  'PZ batch import (process_batch)',          'active',  'POST /api/v1/pz/process',                    'Single source of truth'],
  ['Shipments',  'PZ XLSX/PDF dual export',                  'active',  'GET /api/v1/pz/{id}/export?fmt=xlsx|pdf',    ''],
  ['Shipments',  'Set PZ status (operator)',                 'active',  'POST /api/v1/pz/{id}/set-status',            'Approval required'],
  ['DHL/Customs','Inbox monitor (DHL emails)',               'active',  'GET /api/v1/dhl/inbox',                      ''],
  ['DHL/Customs','Reply queue + send',                       'partial', 'POST /api/v1/dhl/reply/{id}',                'Send gated by feature flag'],
  ['DHL/Customs','Proactive dispatch (DSK package)',         'active',  'POST /api/v1/dhl/dispatch',                  ''],
  ['DHL/Customs','SAD/ZC429 parse',                          'active',  'POST /api/v1/customs/parse',                 ''],
  ['DHL/Customs','FedEx clearance flow',                     'future',  'POST /api/v1/fedex/clearance',               'Planned — mirrors DHL'],
  ['Accounting', 'Purchase ledger / PZ list',                'active',  'GET /api/v1/accounting/pz',                  ''],
  ['Accounting', 'Sales · Proforma create',                  'partial', 'POST /api/v1/sales/proforma',                'Write gated · approval req.'],
  ['Accounting', 'Sales · Invoice convert',                  'partial', 'POST /api/v1/sales/proforma/{id}/convert',   'Write gated · approval req.'],
  ['Accounting', 'Proforma view / download',                 'active',  'GET /api/v1/sales/proforma/{id}.pdf',        ''],
  ['Accounting', 'Invoice view / download',                  'active',  'GET /api/v1/sales/invoice/{id}.pdf',         ''],
  ['Ledgers',    'Client ledger · balances',                 'active',  'GET /api/v1/ledgers/clients',                'Source · wFirma'],
  ['Ledgers',    'Client statement · entries',               'active',  'GET /api/v1/ledgers/clients/{id}/statement', 'Source · wFirma'],
  ['Ledgers',    'Client aging buckets',                     'active',  'GET /api/v1/ledgers/clients/{id}/aging',     'Source · wFirma'],
  ['Ledgers',    'Supplier ledger · balances',               'active',  'GET /api/v1/ledgers/suppliers',              'Source · wFirma'],
  ['Ledgers',    'Supplier statement · entries',             'active',  'GET /api/v1/ledgers/suppliers/{id}/statement','Source · wFirma'],
  ['Ledgers',    'PI ↔ PZ link',                             'partial', 'GET /api/v1/ledgers/documents/{id}/links',   'Operational links'],
  ['Ledgers',    'Read-only document stream',                'active',  'GET /api/v1/ledgers/documents/{id}.pdf',     'Source · wFirma'],
  ['Inventory',  'Stage 1 · Temp Purchase',                  'active',  'GET /api/v1/inventory/temp/purchase',        ''],
  ['Inventory',  'Stage 1 · Temp Warehouse',                 'partial', 'GET /api/v1/inventory/temp/warehouse',       'Goods received, not yet final'],
  ['Inventory',  'Stage 1 · Temp Sale',                      'partial', 'GET /api/v1/inventory/temp/sale',            'Reserved against proforma'],
  ['Inventory',  'Stage 2 · Final Stock',                    'active',  'GET /api/v1/inventory/final',                ''],
  ['Inventory',  'Move Stock (Temp → Final)',                'backend', 'POST /api/v1/inventory/move',                'Approval required'],
  ['Inventory',  'Identity / Mapping (SKU ↔ design)',        'backend', 'POST /api/v1/inventory/identity',            'Two-way mapping required'],
  ['Inventory',  'Consignment register',                     'active',  'GET /api/v1/inventory/consignment',          ''],
  ['Inventory',  'Sample Out',                               'partial', 'POST /api/v1/inventory/samples/out',         'Approval required'],
  ['Inventory',  'Sample Return',                            'backend', 'POST /api/v1/inventory/samples/return',      'Approval required'],
  ['Inventory',  'Goods Return from Client',                 'backend', 'POST /api/v1/inventory/returns/from-client', 'Approval required'],
  ['Inventory',  'Return to Producer',                       'future',  'POST /api/v1/inventory/returns/to-producer', 'Planned — supplier RMA'],
  ['Clients',    'Client KYC',                               'partial', 'GET/PUT /api/v1/clients/{id}/kyc',           ''],
  ['Clients',    'DHL / FedEx account fields',               'partial', 'PUT /api/v1/clients/{id}/carrier-accounts',  ''],
  ['Clients',    'KUKE insurance limit',                     'backend', 'GET /api/v1/clients/{id}/kuke',              'Source · KUKE feed (planned)'],
  ['Clients',    'Credit limit',                             'partial', 'PUT /api/v1/clients/{id}/credit-limit',      'Approval required'],
  ['Documents',  'Upload Document (any module)',             'partial', 'POST /api/v1/documents/upload',              ''],
  ['Operator',   'Action Center · operator queue',           'partial', 'GET /api/v1/actions',                        'Pending: bulk approve'],
  ['Operator',   'Approve action',                           'partial', 'POST /api/v1/actions/{id}/approve',          'Approval required'],
  ['Operator',   'Execute action (after approve)',           'partial', 'POST /api/v1/actions/{id}/execute',          ''],
  ['Automation', 'Automation Center · task queue (Cowork)',  'active',  'GET /api/v1/cowork/tasks',                   'Was AI Bridge'],
  ['Automation', 'Capability registry',                      'active',  'GET /api/v1/cowork/capabilities',            ''],
  ['Automation', 'Prompt templates',                         'partial', 'GET/PUT /api/v1/cowork/templates',           ''],
  ['Reports',    'Financial reports',                        'partial', 'GET /api/v1/reports/financial',              ''],
  ['Reports',    'Sales reports',                            'partial', 'GET /api/v1/reports/sales',                  ''],
  ['Reports',    'Purchase reports',                         'partial', 'GET /api/v1/reports/purchase',               ''],
];

function CoverageMatrix() {
  const [filter, setFilter] = React.useState('all');
  const [q, setQ] = React.useState('');
  const filtered = COVERAGE_ROWS.filter(r =>
    (filter==='all' || r[2]===filter) &&
    (!q || (r[0]+r[1]+r[3]).toLowerCase().includes(q.toLowerCase()))
  );
  const counts = {
    active:  COVERAGE_ROWS.filter(r=>r[2]==='active').length,
    partial: COVERAGE_ROWS.filter(r=>r[2]==='partial').length,
    backend: COVERAGE_ROWS.filter(r=>r[2]==='backend').length,
    future:  COVERAGE_ROWS.filter(r=>r[2]==='future').length,
  };

  const tile = (level, label, count) => (
    <button onClick={()=>setFilter(filter===level?'all':level)} style={{
      flex:1, minWidth:140, padding:'12px 14px', borderRadius:8,
      border: filter===level ? '1.5px solid var(--accent)' : '1px solid var(--border)',
      background: filter===level ? 'var(--accent-subtle)' : 'var(--card)',
      cursor:'pointer', textAlign:'left',
    }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4 }}>
        <FeatureStatus level={level}/>
      </div>
      <div style={{ fontFamily:'"DM Serif Display", serif', fontSize:26, color:'var(--text)' }}>{count}</div>
      <div style={{ fontSize:11, color:'var(--text-3)' }}>{label}</div>
    </button>
  );

  return (
    <div style={{ padding:'18px 32px 32px', overflowY:'auto', flex:1 }}>
      <div style={{ display:'flex', gap:12, marginBottom:14, flexWrap:'wrap' }}>
        {tile('active',  'Wired & shipping',       counts.active)}
        {tile('partial', 'UI live · backend gaps', counts.partial)}
        {tile('backend', 'Backend pending',        counts.backend)}
        {tile('future',  'Planned · not scoped',   counts.future)}
      </div>

      <div style={{ display:'flex', gap:8, marginBottom:10, alignItems:'center' }}>
        <input value={q} onChange={e=>setQ(e.target.value)}
               placeholder="Filter by module, feature, or API path…"
               style={{ flex:1, maxWidth:420, padding:'7px 10px', border:'1px solid var(--border)', borderRadius:6, fontSize:12, color:'var(--text)', background:'var(--card)' }}/>
        {filter!=='all' && <button onClick={()=>setFilter('all')} style={{ padding:'6px 10px', fontSize:11, border:'1px solid var(--border)', background:'var(--card)', borderRadius:6, cursor:'pointer' }}>Clear filter</button>}
        <span style={{ flex:1 }}/>
        <span style={{ fontSize:11, color:'var(--text-3)' }}>Showing {filtered.length} of {COVERAGE_ROWS.length}</span>
      </div>

      <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
          <thead>
            <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
              <th style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase', width:130 }}>Module</th>
              <th style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase' }}>Feature</th>
              <th style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase', width:130 }}>Status</th>
              <th style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase' }}>API placeholder</th>
              <th style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase', width:200 }}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                <td style={{ padding:'8px 12px', color:'var(--text-2)', fontWeight:600 }}>{r[0]}</td>
                <td style={{ padding:'8px 12px', color:'var(--text)' }}>{r[1]}</td>
                <td style={{ padding:'8px 12px' }}><FeatureStatus level={r[2]}/></td>
                <td style={{ padding:'8px 12px', fontFamily:'ui-monospace, "SF Mono", Menlo, monospace', fontSize:11, color:'var(--text-2)' }}>{r[3]}</td>
                <td style={{ padding:'8px 12px', color:'var(--text-3)', fontSize:11 }}>{r[4]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop:18, padding:14, background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:8, fontSize:11, color:'var(--text-2)', lineHeight:1.6 }}>
        <strong style={{ color:'var(--text)' }}>Wireframe rules in effect:</strong>{' '}
        Future / Backend-pending controls are rendered disabled with a tooltip · Read-only data shows <em>Source · wFirma</em> · Write actions show <em>Approval required</em> until executed · No real fetches or mutations are performed in this wireframe.
      </div>
    </div>
  );
}

// ── 4. Action Center page ─────────────────────────────────────────────────
function ActionCenterPage() {
  const queue = [
    { id:'A-2487', kind:'Proforma · approve & issue',         client:'Aurum Trading',   amount:'EUR 4,820', risk:'low',    age:'12 min', level:'partial' },
    { id:'A-2486', kind:'PZ · adopt into wFirma',             ref:'AWB 2412-441',       amount:'PLN 18,400', risk:'low',   age:'34 min', level:'active' },
    { id:'A-2485', kind:'Sample Out · release from stock',    client:'Levi Joaillerie', amount:'EUR 1,260', risk:'medium', age:'1h 04m', level:'partial' },
    { id:'A-2484', kind:'Credit limit · raise to EUR 25k',    client:'Maison Élise',    amount:'',          risk:'high',   age:'2h 11m', level:'partial' },
    { id:'A-2483', kind:'Goods Return · receive from client', client:'Aurum Trading',   amount:'EUR 920',   risk:'medium', age:'3h 28m', level:'backend' },
    { id:'A-2482', kind:'Return to Producer · open RMA',      ref:'PI 2025/418',        amount:'EUR 2,100', risk:'low',    age:'5h 02m', level:'future' },
  ];
  const riskColor = r => r==='high' ? 'var(--badge-red-text)' : r==='medium' ? 'var(--badge-amber-text)' : 'var(--badge-green-text)';

  return (
    <div style={{ padding:'18px 32px 32px', overflowY:'auto', flex:1, display:'flex', gap:18 }}>
      {/* main queue */}
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
          <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>Pending operator actions</h3>
          <FeatureStatus level="approval" label="Approval required"/>
          <span style={{ flex:1 }}/>
          <PendingBtn label="Bulk approve" level="backend"/>
        </div>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
            <thead>
              <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
                {['ID','Action','Reference','Amount','Risk','Age','Status',''].map(h => (
                  <th key={h} style={{ textAlign:'left', padding:'8px 10px', fontWeight:700, color:'var(--text-2)', fontSize:11, letterSpacing:'0.04em', textTransform:'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {queue.map(a => (
                <tr key={a.id} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                  <td style={{ padding:'8px 10px', fontFamily:'ui-monospace, monospace', fontSize:11, color:'var(--text-2)' }}>{a.id}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text)' }}>{a.kind}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text-2)' }}>{a.client || a.ref}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text)', fontWeight:600 }}>{a.amount || '—'}</td>
                  <td style={{ padding:'8px 10px', color:riskColor(a.risk), fontWeight:600, textTransform:'capitalize' }}>{a.risk}</td>
                  <td style={{ padding:'8px 10px', color:'var(--text-3)' }}>{a.age}</td>
                  <td style={{ padding:'8px 10px' }}><FeatureStatus level={a.level}/></td>
                  <td style={{ padding:'8px 10px', textAlign:'right' }}>
                    <button disabled={a.level!=='partial' && a.level!=='active'} style={{
                      padding:'5px 10px', fontSize:11, fontWeight:600,
                      border:'1px solid var(--accent-border)',
                      background: (a.level==='partial'||a.level==='active') ? 'var(--accent)' : 'var(--bg-subtle)',
                      color:(a.level==='partial'||a.level==='active') ? 'var(--accent-text)' : 'var(--text-3)',
                      borderRadius:6, cursor:(a.level==='partial'||a.level==='active') ? 'pointer' : 'not-allowed',
                    }}>Review</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* right action rail */}
      <aside style={{ width:280, flexShrink:0, display:'flex', flexDirection:'column', gap:12 }}>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Today</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8 }}>
            {[['Approved','24'],['Auto-executed','11'],['Rejected','3'],['SLA breaches','1']].map(([k,v])=> (
              <div key={k} style={{ padding:8, background:'var(--bg-subtle)', borderRadius:6 }}>
                <div style={{ fontFamily:'"DM Serif Display", serif', fontSize:22, color:'var(--text)' }}>{v}</div>
                <div style={{ fontSize:10, color:'var(--text-3)' }}>{k}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, padding:14 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>Approval policy</div>
          <ul style={{ margin:0, paddingLeft:16, fontSize:11, color:'var(--text-2)', lineHeight:1.7 }}>
            <li>Writes to wFirma → operator approve</li>
            <li>Credit-limit changes → 2-eyes</li>
            <li>Returns / RMA → ops + finance</li>
            <li>Auto-execute: PZ adopt &lt; PLN 50k</li>
          </ul>
        </div>
      </aside>
    </div>
  );
}

// ── 5. Stub pages — light wireframes for not-yet-built screens ────────────
function StubPage({ title, description, status='backend', endpoints=[], columns=[], rows=[] }) {
  return (
    <div style={{ padding:'18px 32px 32px', overflowY:'auto', flex:1 }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:6 }}>
        <h3 style={{ margin:0, fontSize:14, color:'var(--text)' }}>{title}</h3>
        <FeatureStatus level={status}/>
      </div>
      <p style={{ margin:'0 0 14px', fontSize:12, color:'var(--text-2)', maxWidth:780, lineHeight:1.6 }}>{description}</p>

      {columns.length > 0 && (
        <div style={{ background:'var(--card)', border:'1px solid var(--border)', borderRadius:8, overflow:'hidden', marginBottom:18 }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
            <thead>
              <tr style={{ background:'var(--bg-subtle)', borderBottom:'1px solid var(--border)' }}>
                {columns.map(c => <th key={c} style={{ textAlign:'left', padding:'8px 12px', fontWeight:700, color:'var(--text-2)', fontSize:11, textTransform:'uppercase', letterSpacing:'0.04em' }}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)', opacity:0.85 }}>
                  {r.map((cell, j) => <td key={j} style={{ padding:'8px 12px', color: j===0 ? 'var(--text)' : 'var(--text-2)' }}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding:'10px 12px', background:'var(--bg-subtle)', fontSize:11, color:'var(--text-3)', borderTop:'1px solid var(--border-subtle)' }}>
            Wireframe data — backend not yet wired.
          </div>
        </div>
      )}

      {endpoints.length>0 && (
        <div style={{ padding:14, background:'var(--accent-subtle)', border:'1px solid var(--accent-border)', borderRadius:8 }}>
          <div style={{ fontSize:11, color:'var(--text-3)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:6 }}>Recommended API placeholders</div>
          <ul style={{ margin:0, paddingLeft:16, fontSize:11, color:'var(--text-2)', lineHeight:1.8, fontFamily:'ui-monospace, monospace' }}>
            {endpoints.map(e => <li key={e}>{e}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function IdentityMappingPage() {
  return <StubPage
    title="Identity / Mapping"
    description="Two-way mapping between supplier SKUs, internal design IDs, and customer SKUs. Required before goods can move from Temp Warehouse → Final Stock."
    status="backend"
    columns={['Supplier SKU','Internal Design ID','Customer SKU','Confidence','Last Updated']}
    rows={[
      ['SUP-441-AB',  'EJ-D-00412', 'AUR-441',     'High · 0.94', '2 days ago'],
      ['SUP-441-AC',  'EJ-D-00413', '— unmapped —','—',           '—'],
      ['SUP-552-XX',  'EJ-D-00420', 'LEV-552-X',   'Medium · 0.71','4 days ago'],
    ]}
    endpoints={[
      'GET  /api/v1/inventory/identity?status=unmapped',
      'POST /api/v1/inventory/identity   (bulk upsert)',
      'POST /api/v1/inventory/identity/{id}/confirm',
      'GET  /api/v1/inventory/identity/{id}/audit',
    ]}/>;
}

function MoveStockPage() {
  return <StubPage
    title="Move Stock"
    description="Move identified items from Temp Warehouse → Final Stock once Identity / Mapping is confirmed and customs is verified. Approval required."
    status="backend"
    columns={['Lot','Item','From','To','Qty','Status']}
    rows={[
      ['LOT-2412-441-A','EJ-D-00412','Temp Warehouse','Final Stock', '12', 'Pending mapping'],
      ['LOT-2412-441-B','EJ-D-00413','Temp Warehouse','Final Stock', '8',  'Mapping required'],
      ['LOT-2412-552',  'EJ-D-00420','Temp Warehouse','Final Stock', '20', 'Ready · awaiting approval'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/move           (single lot)',
      'POST /api/v1/inventory/move/bulk',
      'GET  /api/v1/inventory/move/preview?lot=…',
      'POST /api/v1/inventory/move/{id}/approve',
    ]}/>;
}

function SampleOutPage() {
  return <StubPage
    title="Sample Out"
    description="Release samples from Final Stock to a client for evaluation. Tracked separately from sales — does not deduct sellable stock until conversion."
    status="partial"
    columns={['Sample ID','Client','Item','Out Date','Expected Return','Status']}
    rows={[
      ['SMP-0124', 'Aurum Trading',     'EJ-D-00412', '12 May 2026', '26 May 2026', 'Out · in eval'],
      ['SMP-0123', 'Levi Joaillerie',   'EJ-D-00413', '08 May 2026', '22 May 2026', 'Out · overdue'],
      ['SMP-0122', 'Maison Élise',      'EJ-D-00420', '02 May 2026', '16 May 2026', 'Returned'],
    ]}
    endpoints={[
      'GET  /api/v1/inventory/samples',
      'POST /api/v1/inventory/samples/out',
      'POST /api/v1/inventory/samples/{id}/extend',
    ]}/>;
}

function SampleReturnPage() {
  return <StubPage
    title="Sample Return"
    description="Receive samples back into Final Stock or convert to a sale. Triggers QC re-check and a stock movement journal entry."
    status="backend"
    columns={['Sample ID','Client','Item','Returned','Outcome','QC']}
    rows={[
      ['SMP-0119', 'Aurum Trading',   'EJ-D-00405', '11 May 2026', 'Back to stock', 'Pass'],
      ['SMP-0118', 'Levi Joaillerie', 'EJ-D-00407', '09 May 2026', 'Convert to sale','Pass'],
      ['SMP-0117', 'Maison Élise',    'EJ-D-00408', '07 May 2026', 'Damaged · write-off','Fail'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/samples/return',
      'POST /api/v1/inventory/samples/{id}/convert-to-sale',
      'POST /api/v1/inventory/samples/{id}/writeoff',
    ]}/>;
}

function GoodsReturnPage() {
  return <StubPage
    title="Goods Return from Client"
    description="Receive returned goods from a client (post-sale RMA). Generates a credit note in wFirma and re-enters items to Final Stock after QC."
    status="backend"
    columns={['RMA','Client','Original Inv.','Items','Reason','Status']}
    rows={[
      ['RMA-0044','Aurum Trading',   'INV 2025/0412','3', 'Wrong size',     'In transit'],
      ['RMA-0043','Levi Joaillerie', 'INV 2025/0405','1', 'Quality issue',  'QC pending'],
      ['RMA-0042','Maison Élise',    'INV 2025/0399','2', 'Customer return','Credit issued'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/returns/from-client',
      'POST /api/v1/inventory/returns/{id}/qc',
      'POST /api/v1/inventory/returns/{id}/credit-note   (writes wFirma · approval req.)',
    ]}/>;
}

function ReturnToProducerPage() {
  return <StubPage
    title="Return to Producer"
    description="Send goods back to the original supplier (defective lots, wrong items, end-of-line). Mirrors PZ flow in reverse — generates a debit note request."
    status="future"
    columns={['Producer RMA','Supplier','Original PI','Items','Reason','Status']}
    rows={[
      ['PRMA-0012','Mehta Gems · MUM',     'PI 2025/418','5','Off-spec',  'Draft'],
      ['PRMA-0011','Levant Diamonds · TLV','PI 2025/410','2','Wrong cut',  'Awaiting approval'],
      ['PRMA-0010','Mehta Gems · MUM',     'PI 2025/402','3','Damaged',    'Sent'],
    ]}
    endpoints={[
      'POST /api/v1/inventory/returns/to-producer',
      'POST /api/v1/inventory/returns/{id}/dispatch',
      'POST /api/v1/inventory/returns/{id}/debit-note   (writes wFirma · approval req.)',
    ]}/>;
}

// ── Export to window so the host HTML can mount these ─────────────────────
Object.assign(window, {
  FeatureStatus, PendingBtn, OperationalStatusStrip,
  CoverageMatrix, ActionCenterPage,
  IdentityMappingPage, MoveStockPage,
  SampleOutPage, SampleReturnPage,
  GoodsReturnPage, ReturnToProducerPage,
});
