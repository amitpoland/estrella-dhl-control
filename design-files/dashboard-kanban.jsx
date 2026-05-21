// ─────────────────────────────────────────────────────────────────────────────
// DashboardKanban — workflow-first dashboard replacing the metrics page.
// Visual pipeline board: every active shipment as a card in the lane matching
// its current stage. One-glance situational awareness.
//
// Plus 4 quick-start CTAs for the most common operator workflows.
// ─────────────────────────────────────────────────────────────────────────────

const LANES = [
  { id: 'new',      label: 'New / Drafting',     hint: 'no PI yet',                     color: 'var(--badge-neutral-text)', bg: 'var(--badge-neutral-bg)',  border: 'var(--badge-neutral-border)' },
  { id: 'docs',     label: 'Awaiting Documents', hint: 'PI · INV · PZ pending',         color: 'var(--badge-amber-text)',   bg: 'var(--badge-amber-bg)',    border: 'var(--badge-amber-border)' },
  { id: 'customs',  label: 'Customs Clearance',  hint: 'SAD · ZC429 in progress',       color: 'var(--badge-red-text)',     bg: 'var(--badge-red-bg)',      border: 'var(--badge-red-border)' },
  { id: 'ready',    label: 'Ready to Ship',      hint: 'cleared · awaiting label',      color: 'var(--badge-purple-text)',  bg: 'var(--badge-purple-bg)',   border: 'var(--badge-purple-border)' },
  { id: 'transit',  label: 'In Transit',         hint: 'with carrier',                  color: 'var(--badge-blue-text)',    bg: 'var(--badge-blue-bg)',     border: 'var(--badge-blue-border)' },
  { id: 'done',     label: 'Delivered',          hint: 'closed · last 7 days',          color: 'var(--badge-green-text)',   bg: 'var(--badge-green-bg)',    border: 'var(--badge-green-border)' },
];

const PIPELINE_SHIPMENTS = [
  // new
  { id: 'SHIP-2026-0425', client: 'Maison Royale SARL',  age: '2h',  lane: 'new',     direction: 'out', carrier: '—',         awb: '—',                docs: 0, value: 9840.50,  currency: 'EUR', flag: null,                        priority: 'normal' },
  { id: 'SHIP-2026-0426', client: 'Atelier Lumière',     age: '1h',  lane: 'new',     direction: 'out', carrier: '—',         awb: '—',                docs: 0, value: 0,        currency: 'EUR', flag: null,                        priority: 'normal' },
  // docs
  { id: 'SHIP-2026-0424', client: 'Crown Jewelers Ltd',  age: '6h',  lane: 'docs',    direction: 'out', carrier: 'FedEx',     awb: '—',                docs: 2, value: 24100.00, currency: 'USD', flag: 'awaiting INV',              priority: 'high'   },
  { id: 'SHIP-2026-0423', client: 'Patek Philippe SA',   age: '1d',  lane: 'docs',    direction: 'in',  carrier: 'DHL',       awb: '—',                docs: 1, value: 142000.0, currency: 'CHF', flag: 'awaiting PZ',               priority: 'high'   },
  { id: 'SHIP-2026-0422', client: 'Hôtel Belle Étoile',  age: '4h',  lane: 'docs',    direction: 'out', carrier: 'DHL',       awb: '—',                docs: 1, value: 4220.00,  currency: 'EUR', flag: null,                        priority: 'normal' },
  // customs
  { id: 'SHIP-2026-0420', client: 'Audemars Piguet',     age: '2d',  lane: 'customs', direction: 'in',  carrier: 'DHL',       awb: '1234567802',       docs: 3, value: 88400.00, currency: 'CHF', flag: 'SAD pending',               priority: 'urgent' },
  { id: 'SHIP-2026-0419', client: 'Crown Jewelers Ltd',  age: '1d',  lane: 'customs', direction: 'in',  carrier: 'DHL',       awb: '1234567803',       docs: 3, value: 18200.00, currency: 'USD', flag: 'verification needed',       priority: 'urgent' },
  // ready
  { id: 'SHIP-2026-0421', client: 'Aurum Watches GmbH',  age: '3h',  lane: 'ready',   direction: 'out', carrier: 'DHL',       awb: '1234567890',       docs: 4, value: 18420.00, currency: 'EUR', flag: null,                        priority: 'normal' },
  { id: 'SHIP-2026-0417', client: 'Bijoux Sélection',    age: '5h',  lane: 'ready',   direction: 'out', carrier: 'InPost',    awb: 'INP-552448',       docs: 3, value: 1840.00,  currency: 'EUR', flag: null,                        priority: 'normal' },
  // transit
  { id: 'SHIP-2026-0418', client: 'Crown Jewelers Ltd',  age: '1d',  lane: 'transit', direction: 'out', carrier: 'FedEx',     awb: '998877665',        docs: 4, value: 24100.00, currency: 'USD', flag: null,                        priority: 'normal' },
  { id: 'SHIP-2026-0415', client: 'Manufaktura Złota',   age: '2d',  lane: 'transit', direction: 'in',  carrier: 'DHL',       awb: '8442211003',       docs: 4, value: 18420.00, currency: 'EUR', flag: null,                        priority: 'normal' },
  { id: 'SHIP-2026-0414', client: 'Aurum Watches GmbH',  age: '2d',  lane: 'transit', direction: 'out', carrier: 'DHL',       awb: '1234567812',       docs: 4, value: 8200.00,  currency: 'EUR', flag: null,                        priority: 'normal' },
  // done
  { id: 'SHIP-2026-0410', client: 'Patek Philippe SA',   age: '3d',  lane: 'done',    direction: 'in',  carrier: 'DHL',       awb: '1234567830',       docs: 5, value: 142000.0, currency: 'CHF', flag: null,                        priority: 'normal' },
  { id: 'SHIP-2026-0408', client: 'Hôtel Belle Étoile',  age: '4d',  lane: 'done',    direction: 'out', carrier: 'DHL',       awb: '1234567831',       docs: 4, value: 4220.00,  currency: 'EUR', flag: null,                        priority: 'normal' },
  { id: 'SHIP-2026-0407', client: 'Maison Royale SARL',  age: '5d',  lane: 'done',    direction: 'out', carrier: 'InPost',    awb: 'INP-552399',       docs: 3, value: 880.00,   currency: 'EUR', flag: null,                        priority: 'normal' },
];

const QUICK_FLOWS = [
  { id: 'inbound',  icon: '📥', label: 'Receive shipment',           hint: 'Inbound · PZ · SAD',       color: 'var(--badge-blue-text)',  bg: 'var(--badge-blue-bg)',  border: 'var(--badge-blue-border)' },
  { id: 'outbound', icon: '📤', label: 'Create outbound shipment',   hint: 'Order → INV → Label',      color: 'var(--accent)',           bg: 'var(--accent-subtle)',  border: 'var(--accent-border)' },
  { id: 'email',    icon: '✉',  label: 'Process new email',           hint: 'Parse · Match · Action',   color: 'var(--badge-purple-text)',bg: 'var(--badge-purple-bg)',border: 'var(--badge-purple-border)' },
  { id: 'order',    icon: '🛒', label: 'Customer order',              hint: 'Order → Invoice → Ship',   color: 'var(--badge-green-text)', bg: 'var(--badge-green-bg)', border: 'var(--badge-green-border)' },
];

function DashboardKanban({ onNav, onOpenNewShipment, onOpenSearch }) {
  const counts = LANES.reduce((acc, l) => {
    acc[l.id] = PIPELINE_SHIPMENTS.filter(s => s.lane === l.id).length;
    return acc;
  }, {});
  const inboundCount  = PIPELINE_SHIPMENTS.filter(s => s.direction === 'in' && s.lane !== 'done').length;
  const outboundCount = PIPELINE_SHIPMENTS.filter(s => s.direction === 'out' && s.lane !== 'done').length;
  const urgentCount   = PIPELINE_SHIPMENTS.filter(s => s.priority === 'urgent').length;
  const totalValue    = PIPELINE_SHIPMENTS.filter(s => s.lane !== 'done').reduce((sum, s) => sum + (s.value || 0), 0);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 32px 40px' }}>
      {/* Quick-start CTA strip */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Start a workflow</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
          {QUICK_FLOWS.map(f => (
            <button key={f.id}
              onClick={() => {
                if (f.id === 'outbound') onOpenNewShipment && onOpenNewShipment();
                else if (f.id === 'email') onNav && onNav('inbox');
                else if (f.id === 'inbound') onNav && onNav('shipments');
                else if (f.id === 'order') onNav && onNav('documents');
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
                background: f.bg, border: `1px solid ${f.border}`,
                borderRadius: 8, cursor: 'pointer', textAlign: 'left',
                transition: 'transform 0.15s, box-shadow 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = '0 4px 12px var(--shadow)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}>
              <span style={{ fontSize: 22 }}>{f.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{f.hint}</div>
              </div>
              <span style={{ fontSize: 14, color: f.color }}>→</span>
            </button>
          ))}
        </div>
      </div>

      {/* Compact KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 18 }}>
        <CompactKpi label="Active shipments"   value={PIPELINE_SHIPMENTS.filter(s => s.lane !== 'done').length} hint="in pipeline" />
        <CompactKpi label="Urgent"              value={urgentCount}      hint="customs / docs blocked" accent="var(--badge-red-text)" />
        <CompactKpi label="Inbound"             value={inboundCount}     hint="being received" />
        <CompactKpi label="Outbound"            value={outboundCount}    hint="being shipped" />
        <CompactKpi label="Total value"         value={`€${(totalValue/1000).toFixed(0)}K`} hint="pipeline · mixed FX" accent="var(--accent)" />
      </div>

      {/* Pipeline header */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>Pipeline</h2>
          <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-3)' }}>Drag cards between lanes — wireframe · click a card to open shipment detail</p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button onClick={onOpenSearch} style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'var(--bg-subtle)', border: '1px solid var(--border)',
            color: 'var(--text-2)', borderRadius: 6, padding: '5px 10px',
            fontSize: 11, fontWeight: 600, cursor: 'pointer',
          }}>⌕ Search <span style={{ fontFamily: 'monospace', padding: '0px 5px', background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 3, fontSize: 9.5 }}>⌘K</span></button>
          <button style={{
            background: 'transparent', border: '1px solid var(--border)',
            color: 'var(--text-2)', borderRadius: 6, padding: '5px 10px',
            fontSize: 11, fontWeight: 600, cursor: 'pointer',
          }}>⊟ List view</button>
        </div>
      </div>

      {/* Kanban board */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(6, minmax(220px, 1fr))', gap: 12,
        overflowX: 'auto', paddingBottom: 4,
      }}>
        {LANES.map(lane => (
          <KanbanLane key={lane.id} lane={lane} count={counts[lane.id]}
            cards={PIPELINE_SHIPMENTS.filter(s => s.lane === lane.id)}
            onCardClick={() => onNav && onNav('shipments')} />
        ))}
      </div>

      {/* Bottom helper */}
      <div style={{ marginTop: 18, padding: 12, background: 'var(--bg-subtle)', border: '1px dashed var(--border)', borderRadius: 6, fontSize: 11.5, color: 'var(--text-2)', lineHeight: 1.55 }}>
        <strong style={{ color: 'var(--text)' }}>How this works:</strong> shipments move left-to-right as they progress. Urgent items (red flag, ⚠ icon) need your attention now — usually customs holds or missing docs. Use the quick-start cards above to begin a new workflow.
      </div>
    </div>
  );
}

function CompactKpi({ label, value, hint, accent }) {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 6, padding: '10px 14px',
    }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', marginTop: 4, fontFamily: '"DM Serif Display", serif' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>
    </div>
  );
}

function KanbanLane({ lane, count, cards, onCardClick }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', minWidth: 220,
      background: 'var(--bg-subtle)', borderRadius: 8,
      border: '1px solid var(--border)',
    }}>
      {/* Lane header */}
      <div style={{
        padding: '10px 12px', borderBottom: `2px solid ${lane.border}`,
        background: lane.bg, borderRadius: '8px 8px 0 0',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 2 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: lane.color, letterSpacing: '0.02em' }}>{lane.label}</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: lane.color, fontFamily: 'monospace' }}>{count}</span>
        </div>
        <div style={{ fontSize: 9.5, color: lane.color, opacity: 0.75 }}>{lane.hint}</div>
      </div>
      {/* Cards */}
      <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 6, minHeight: 200 }}>
        {cards.length === 0 && (
          <div style={{ padding: 16, textAlign: 'center', fontSize: 10.5, color: 'var(--text-3)', fontStyle: 'italic' }}>—</div>
        )}
        {cards.map(c => <KanbanCard key={c.id} shipment={c} onClick={() => onCardClick && onCardClick(c)} />)}
      </div>
    </div>
  );
}

function KanbanCard({ shipment, onClick }) {
  const isUrgent = shipment.priority === 'urgent';
  const isHigh   = shipment.priority === 'high';
  return (
    <button onClick={onClick} style={{
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 5, padding: '8px 10px', cursor: 'pointer', textAlign: 'left',
      borderLeft: isUrgent ? '3px solid var(--badge-red-text)' : isHigh ? '3px solid var(--badge-amber-text)' : '1px solid var(--border)',
      transition: 'transform 0.12s, box-shadow 0.12s',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = '0 3px 10px var(--shadow)'; }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}>
      {/* Top row: AWB / direction / age */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          fontSize: 9, padding: '0px 4px', borderRadius: 2,
          background: shipment.direction === 'in' ? 'var(--badge-blue-bg)' : 'var(--badge-purple-bg)',
          color: shipment.direction === 'in' ? 'var(--badge-blue-text)' : 'var(--badge-purple-text)',
          border: '1px solid ' + (shipment.direction === 'in' ? 'var(--badge-blue-border)' : 'var(--badge-purple-border)'),
          fontWeight: 700, letterSpacing: '0.04em',
        }}>{shipment.direction === 'in' ? 'IN' : 'OUT'}</span>
        <span style={{ fontSize: 10.5, fontFamily: 'monospace', fontWeight: 600, color: 'var(--text)' }}>{shipment.id.split('-').slice(2).join('-')}</span>
        <span style={{ flex: 1 }}></span>
        <span style={{ fontSize: 9.5, color: 'var(--text-3)' }}>{shipment.age}</span>
      </div>
      {/* Client */}
      <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{shipment.client}</div>
      {/* Meta */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9.5, color: 'var(--text-3)' }}>
        <span style={{ fontFamily: 'monospace' }}>{shipment.carrier}</span>
        <span>·</span>
        <span>{shipment.docs}/4 docs</span>
        {shipment.value > 0 && <><span>·</span><span style={{ fontFamily: 'monospace' }}>{shipment.currency} {(shipment.value/1000).toFixed(1)}k</span></>}
      </div>
      {/* Flag */}
      {shipment.flag && (
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 2,
          fontSize: 9.5, fontWeight: 600,
          color: isUrgent ? 'var(--badge-red-text)' : 'var(--badge-amber-text)',
        }}>
          <span>{isUrgent ? '⚠' : '◐'}</span>
          <span>{shipment.flag}</span>
        </div>
      )}
    </button>
  );
}

window.DashboardKanban = DashboardKanban;
