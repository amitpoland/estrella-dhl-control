// ─────────────────────────────────────────────────────────────────────────────
// Inbox — unified action queue replacing 5 separate pages:
//   Action Center · Email Queue · Operator Queue · Action Proposals · Reservations
//
// Everything that needs operator attention shows up here, ordered by priority.
// Click an item → primary action; long-press → all options.
//
// Backend hooks (stubbed):
//   GET  /api/v1/inbox?priority=&type=
//   POST /api/v1/inbox/{id}/approve
//   POST /api/v1/inbox/{id}/reject
//   POST /api/v1/inbox/{id}/snooze
// ─────────────────────────────────────────────────────────────────────────────

const INBOX_ITEMS = [
  // ── Urgent ──────────────────────────────────────────────
  { id: 'inbox-1001', type: 'customs',     priority: 'urgent', title: 'SAD verification required',                                    detail: 'SHIP-2026-0420 · Audemars Piguet · CHF 88,400',                  age: '2h ago',  actor: 'Customs Agent', primary: 'Verify', linkedTo: 'SHIP-2026-0420' },
  { id: 'inbox-1002', type: 'email',       priority: 'urgent', title: 'DHL email — clearance hold notice',                            detail: 'Subject: AWB 1234567803 — additional documentation required',    age: '4h ago',  actor: 'DHL inbox',     primary: 'Open',   linkedTo: 'SHIP-2026-0419' },
  { id: 'inbox-1003', type: 'proposal',    priority: 'urgent', title: 'Generate PI — Crown Jewelers (USD 24,100)',                    detail: 'AI proposes draft Proforma from order ORD-885',                  age: '15min ago',actor: 'AI Bridge',    primary: 'Approve', linkedTo: 'ORD-885'        },

  // ── High ────────────────────────────────────────────────
  { id: 'inbox-1004', type: 'reservation', priority: 'high', title: 'Reservation gate — Maison Royale',                              detail: 'Warehouse audit ✓ · Sales linkage pending · wFirma preview ready',age: '1h ago',  actor: 'Reservation cell', primary: 'Confirm', linkedTo: 'PI-2026/0143'   },
  { id: 'inbox-1005', type: 'email',       priority: 'high',   title: 'New customer email — Atelier Lumière',                          detail: 'Subject: Quote request for collection 2026/SS',                  age: '1h ago',  actor: 'sales@estrella.pl', primary: 'Parse', linkedTo: null              },
  { id: 'inbox-1006', type: 'proposal',    priority: 'high',   title: 'Match email attachment to SHIP-2026-0419',                       detail: 'AI proposes linking inbound PDF (commercial invoice) — confidence 94%',age: '2h ago',actor: 'AI Bridge',     primary: 'Approve', linkedTo: 'SHIP-2026-0419' },
  { id: 'inbox-1007', type: 'approval',    priority: 'high',   title: 'Post PI-2026/0142 → wFirma',                                    detail: 'Aurum Watches GmbH · EUR 18,420 · YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA',age: '3h ago',actor: 'Operator queue',primary: 'Approve', linkedTo: 'PI-2026/0142'   },

  // ── Normal ──────────────────────────────────────────────
  { id: 'inbox-1008', type: 'email',       priority: 'normal', title: 'Carrier confirmation — InPost',                                 detail: 'Subject: Shipment booking confirmed · INP-552448',               age: '5h ago',  actor: 'noreply@inpost.pl', primary: 'Open',  linkedTo: 'SHIP-2026-0417' },
  { id: 'inbox-1009', type: 'proposal',    priority: 'normal', title: 'Update HS code mapping — bracelets',                            detail: 'Parser learned new HS code 7113.11.00 from SAD declaration',     age: '6h ago',  actor: 'Parser',         primary: 'Approve', linkedTo: null              },
  { id: 'inbox-1010', type: 'customs',     priority: 'normal', title: 'ZC429-26-04482 acknowledged',                                   detail: 'Customs notice accepted by PUESC for SAD-PL-26-118472',          age: '1d ago',  actor: 'PUESC webhook',  primary: 'Open',   linkedTo: 'SAD-PL-26-118472'},
  { id: 'inbox-1011', type: 'reservation', priority: 'normal', title: 'Reservation confirmed — Hôtel Belle Étoile',                    detail: 'All 3 gates clean · proceed with INV generation',                 age: '1d ago',  actor: 'System',         primary: 'Open',   linkedTo: 'ORD-884'         },
  { id: 'inbox-1012', type: 'approval',    priority: 'normal', title: 'Move 4 items from Temp → Final Stock',                          detail: 'B-2026-014 · audit checksum ok',                                  age: '1d ago',  actor: 'Warehouse',     primary: 'Approve', linkedTo: 'B-2026-014'      },

  // ── Info ────────────────────────────────────────────────
  { id: 'inbox-1013', type: 'email',       priority: 'info',   title: 'System digest — overnight automation summary',                  detail: '12 emails parsed · 4 PIs drafted · 2 SADs uploaded · 0 errors',  age: '8h ago',  actor: 'Automation',     primary: 'Open',   linkedTo: null              },
  { id: 'inbox-1014', type: 'email',       priority: 'info',   title: 'Newsletter — Lufthansa Cargo updates',                          detail: 'Quarterly carrier notification',                                  age: '12h ago', actor: 'noreply@lcag.com', primary: 'Open',  linkedTo: null              },
];

const INBOX_TABS = [
  { id: 'all',          label: 'All',          icon: '✉', types: null },
  { id: 'emails',       label: 'Emails',       icon: '✉', types: ['email'] },
  { id: 'proposals',    label: 'Proposals',    icon: '✦', types: ['proposal'] },
  { id: 'approvals',    label: 'Approvals',    icon: '◉', types: ['approval'] },
  { id: 'reservations', label: 'Reservations', icon: '⊕', types: ['reservation'] },
  { id: 'customs',      label: 'Customs',      icon: '◐', types: ['customs'] },
];

const PRIORITY_CONF = {
  urgent: { label: 'Urgent',  icon: '⚠', color: 'var(--badge-red-text)',    bg: 'var(--badge-red-bg)',    border: 'var(--badge-red-border)' },
  high:   { label: 'High',    icon: '◐', color: 'var(--badge-amber-text)',  bg: 'var(--badge-amber-bg)',  border: 'var(--badge-amber-border)' },
  normal: { label: 'Normal',  icon: '○', color: 'var(--badge-blue-text)',   bg: 'var(--badge-blue-bg)',   border: 'var(--badge-blue-border)' },
  info:   { label: 'Info',    icon: '·', color: 'var(--badge-neutral-text)',bg: 'var(--badge-neutral-bg)',border: 'var(--badge-neutral-border)' },
};

const TYPE_CONF = {
  email:       { label: 'Email',       icon: '✉', color: 'var(--badge-purple-text)' },
  proposal:    { label: 'Proposal',    icon: '✦', color: 'var(--accent)' },
  approval:    { label: 'Approval',    icon: '◉', color: 'var(--badge-blue-text)' },
  reservation: { label: 'Reservation', icon: '⊕', color: 'var(--badge-green-text)' },
  customs:     { label: 'Customs',     icon: '◐', color: 'var(--badge-red-text)' },
};

function InboxPage({ onNav }) {
  const [tab, setTab] = React.useState('all');
  const [priorityFilter, setPriorityFilter] = React.useState('all');
  const [selected, setSelected] = React.useState(null);

  const tabConf = INBOX_TABS.find(t => t.id === tab);
  const filtered = INBOX_ITEMS.filter(i => {
    if (tabConf.types && !tabConf.types.includes(i.type)) return false;
    if (priorityFilter !== 'all' && i.priority !== priorityFilter) return false;
    return true;
  });

  const counts = INBOX_TABS.reduce((acc, t) => {
    acc[t.id] = t.types ? INBOX_ITEMS.filter(i => t.types.includes(i.type)).length : INBOX_ITEMS.length;
    return acc;
  }, {});

  const priorityCounts = ['urgent','high','normal','info'].reduce((acc, p) => {
    acc[p] = INBOX_ITEMS.filter(i => i.priority === p).length;
    return acc;
  }, {});

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      {/* Left rail — tabs */}
      <div style={{
        width: 200, flexShrink: 0, background: 'var(--bg-subtle)',
        borderRight: '1px solid var(--border)',
        padding: '14px 0', overflowY: 'auto',
      }}>
        <div style={{ padding: '0 16px 8px', fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>By type</div>
        {INBOX_TABS.map(t => {
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 10,
              padding: '8px 16px', background: active ? 'var(--card)' : 'transparent',
              border: 'none', cursor: 'pointer', textAlign: 'left',
              borderLeft: active ? '3px solid var(--accent)' : '3px solid transparent',
            }}>
              <span style={{ fontSize: 13, color: active ? 'var(--accent)' : 'var(--text-3)', width: 14 }}>{t.icon}</span>
              <span style={{ flex: 1, fontSize: 12, color: active ? 'var(--text)' : 'var(--text-2)', fontWeight: active ? 600 : 400 }}>{t.label}</span>
              <span style={{
                fontSize: 10, fontFamily: 'monospace',
                color: active ? 'var(--accent)' : 'var(--text-3)',
                background: active ? 'var(--accent-subtle)' : 'transparent',
                padding: '1px 6px', borderRadius: 3, fontWeight: 600,
              }}>{counts[t.id]}</span>
            </button>
          );
        })}

        <div style={{ marginTop: 18, padding: '0 16px 8px', fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>By priority</div>
        {[
          { id: 'all',    label: 'All priorities',  count: INBOX_ITEMS.length },
          { id: 'urgent', label: 'Urgent',          count: priorityCounts.urgent, color: 'var(--badge-red-text)' },
          { id: 'high',   label: 'High',            count: priorityCounts.high,   color: 'var(--badge-amber-text)' },
          { id: 'normal', label: 'Normal',          count: priorityCounts.normal, color: 'var(--badge-blue-text)' },
          { id: 'info',   label: 'Info',            count: priorityCounts.info,   color: 'var(--badge-neutral-text)' },
        ].map(p => {
          const active = priorityFilter === p.id;
          return (
            <button key={p.id} onClick={() => setPriorityFilter(p.id)} style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 10,
              padding: '7px 16px', background: active ? 'var(--card)' : 'transparent',
              border: 'none', cursor: 'pointer', textAlign: 'left',
              borderLeft: active ? `3px solid ${p.color || 'var(--accent)'}` : '3px solid transparent',
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: p.color || 'var(--text-3)' }}></span>
              <span style={{ flex: 1, fontSize: 12, color: active ? 'var(--text)' : 'var(--text-2)', fontWeight: active ? 600 : 400 }}>{p.label}</span>
              <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--text-3)' }}>{p.count}</span>
            </button>
          );
        })}
      </div>

      {/* Main list */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12, background: 'var(--card)' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
            {tabConf.label} · {priorityFilter === 'all' ? 'all priorities' : priorityFilter}
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{filtered.length} {filtered.length === 1 ? 'item' : 'items'}</span>
          <span style={{ flex: 1 }}></span>
          <button title="Refresh — GET /api/v1/inbox" style={{
            background: 'transparent', border: '1px solid var(--border)',
            borderRadius: 4, padding: '5px 10px', cursor: 'pointer',
            color: 'var(--text-2)', fontSize: 11, fontWeight: 600,
          }}>↻ Refresh</button>
        </div>

        <div style={{ flex: 1 }}>
          {filtered.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12, fontStyle: 'italic' }}>
              ✓ Nothing here. You're all caught up.
            </div>
          )}
          {filtered.map(item => (
            <InboxRow key={item.id} item={item} selected={selected === item.id}
              onSelect={() => setSelected(item.id)}
              onNav={onNav} />
          ))}
        </div>
      </div>
    </div>
  );
}

function InboxRow({ item, selected, onSelect, onNav }) {
  const p = PRIORITY_CONF[item.priority];
  const t = TYPE_CONF[item.type];
  return (
    <div onClick={onSelect}
      style={{
        display: 'grid',
        gridTemplateColumns: '6px 24px 1fr auto auto',
        gap: 12, alignItems: 'center',
        padding: '14px 24px',
        borderBottom: '1px solid var(--border-subtle)',
        cursor: 'pointer',
        background: selected ? 'var(--accent-subtle)' : 'transparent',
        borderLeft: selected ? '3px solid var(--accent)' : '3px solid transparent',
        transition: 'background 0.12s',
      }}
      onMouseEnter={e => { if (!selected) e.currentTarget.style.background = 'var(--bg-subtle)'; }}
      onMouseLeave={e => { if (!selected) e.currentTarget.style.background = 'transparent'; }}>
      {/* Priority dot */}
      <div style={{ width: 6, height: 6, borderRadius: '50%', background: p.color }}></div>

      {/* Type icon */}
      <div style={{
        width: 24, height: 24, borderRadius: 4,
        background: p.bg, color: t.color, border: `1px solid ${p.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700,
      }}>{t.icon}</div>

      {/* Content */}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title}</span>
          <span style={{
            fontSize: 9, padding: '0px 5px', borderRadius: 2,
            background: p.bg, color: p.color, border: `1px solid ${p.border}`,
            fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>{p.label}</span>
          {item.linkedTo && (
            <span style={{
              fontSize: 9, padding: '0px 5px', borderRadius: 2, fontFamily: 'monospace',
              background: 'var(--accent-subtle)', color: 'var(--accent)',
              border: '1px solid var(--accent-border)',
            }}>{item.linkedTo}</span>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.detail}</div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
          <span>{t.label}</span>
          <span style={{ margin: '0 6px' }}>·</span>
          <span>{item.actor}</span>
          <span style={{ margin: '0 6px' }}>·</span>
          <span>{item.age}</span>
        </div>
      </div>

      {/* Quick actions */}
      <div style={{ display: 'flex', gap: 4 }}>
        <button onClick={(e) => { e.stopPropagation(); }} title={`POST /api/v1/inbox/${item.id}/snooze`}
          style={{
            background: 'transparent', border: '1px solid var(--border)',
            color: 'var(--text-2)', borderRadius: 4, padding: '4px 8px',
            fontSize: 10.5, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
          }}>⏰ Snooze</button>
        <button onClick={(e) => { e.stopPropagation(); }}
          title={`POST /api/v1/inbox/${item.id}/${item.primary.toLowerCase()}`}
          style={{
            background: item.priority === 'urgent' ? 'var(--badge-red-bg)' : item.priority === 'high' ? 'var(--accent)' : 'var(--bg-subtle)',
            color:      item.priority === 'urgent' ? 'var(--badge-red-text)' : item.priority === 'high' ? 'var(--accent-text)' : 'var(--text)',
            border: '1px solid ' + (item.priority === 'urgent' ? 'var(--badge-red-border)' : item.priority === 'high' ? 'var(--accent)' : 'var(--border)'),
            borderRadius: 4, padding: '4px 12px',
            fontSize: 11, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap',
          }}>{item.primary} →</button>
      </div>

      {/* Overflow */}
      <button onClick={(e) => { e.stopPropagation(); }} style={{
        background: 'transparent', border: 'none', cursor: 'pointer',
        color: 'var(--text-3)', fontSize: 14, padding: 4,
      }}>⋯</button>
    </div>
  );
}

window.InboxPage = InboxPage;
