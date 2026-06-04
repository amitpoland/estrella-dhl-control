// Pro Forma List (Screen A) — flattened, clean chips, drilldown navigation
// Per ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md

const PROFORMA_DRAFTS = [
  {
    id: 'pf_001',
    number: 'PROF 101/2026',
    shipmentId: 'EJL26-27013',
    shipmentAwb: '1234567890',
    customer: 'Diamond Point NV',
    items: 47,
    totalEur: 18420.50,
    source: 'shipment',
    status: 'ready', // ready | convert_blocked | invoiced
    createdAt: '2026-05-10 14:22',
    createdBy: 'System',
    blockReason: null,
  },
  {
    id: 'pf_002',
    number: 'PROF 102/2026',
    shipmentId: 'EJL26-27014',
    shipmentAwb: '9876543210',
    customer: 'Verhoeven Diamonds BV',
    items: 12,
    totalEur: 8240.00,
    source: 'shipment',
    status: 'ready',
    createdAt: '2026-05-11 09:18',
    createdBy: 'System',
    blockReason: null,
  },
  {
    id: 'pf_003',
    number: 'PROF 103/2026',
    shipmentId: 'EJL26-27015',
    shipmentAwb: '5551234567',
    customer: 'Dream Ring s.r.o.',
    items: 8,
    totalEur: 4180.00,
    source: 'manual',
    status: 'convert_blocked',
    createdAt: '2026-05-09 16:44',
    createdBy: 'A. Kowalski',
    blockReason: 'Missing wFirma customer mapping',
  },
  {
    id: 'pf_004',
    number: 'PROF 100/2026',
    shipmentId: 'EJL26-27012',
    shipmentAwb: '7778889990',
    customer: 'Panakas Jewellery Ltd',
    items: 22,
    totalEur: 14820.00,
    source: 'shipment',
    status: 'invoiced',
    createdAt: '2026-05-08 11:30',
    createdBy: 'System',
    invoiceNumber: 'FV 88/2026',
    invoicedAt: '2026-05-09 10:15',
  },
];

const STATUS_CHIP = {
  ready: { label: 'Ready', bg: 'var(--badge-blue-bg)', text: 'var(--badge-blue-text)', border: 'var(--badge-blue-border)' },
  convert_blocked: { label: 'Convert Blocked', bg: 'var(--badge-red-bg)', text: 'var(--badge-red-text)', border: 'var(--badge-red-border)' },
  invoiced: { label: 'Invoiced', bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)' },
};

const SOURCE_LABEL = {
  shipment: '📦 Shipment',
  manual: '✎ Manual',
};

function ProformaStatusChip({ status }) {
  const s = STATUS_CHIP[status];
  if (!s) return null;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 4,
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      fontSize: 10.5, fontWeight: 600, letterSpacing: '0.02em',
    }}>
      {s.label}
    </span>
  );
}

function ProformaListPage({ onDrill }) {
  const [drafts, setDrafts] = React.useState(PROFORMA_DRAFTS);
  const [showNewDraft, setShowNewDraft] = React.useState(false);

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '20px 32px', background: 'var(--bg)' }}>
      {/* Header strip */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 20, flexWrap: 'wrap', gap: 12,
      }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', margin: 0 }}>Pro Forma Drafts</h2>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 3 }}>
            Click any draft to open detail · Convert to Invoice when ready
          </div>
        </div>
        <Btn variant="gold" onClick={() => setShowNewDraft(true)}>+ New Draft</Btn>
      </div>

      {/* Drafts table */}
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Number</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Customer</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Shipment</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Items</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Total EUR</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Source</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((d, i) => (
              <tr
                key={d.id}
                onClick={() => onDrill(d)}
                style={{
                  borderBottom: i < drafts.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                  cursor: 'pointer',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{d.number}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>Created {d.createdAt}</div>
                </td>
                <td style={{ padding: '14px 16px', fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{d.customer}</td>
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-2)' }}>{d.shipmentId}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>AWB {d.shipmentAwb}</div>
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{d.items}</td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
                  {d.totalEur.toFixed(2)}
                </td>
                <td style={{ padding: '14px 16px', fontSize: 11, color: 'var(--text-2)' }}>{SOURCE_LABEL[d.source]}</td>
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                    <ProformaStatusChip status={d.status} />
                    {d.status === 'invoiced' && (
                      <div style={{ fontSize: 10, color: 'var(--text-3)' }}>→ {d.invoiceNumber}</div>
                    )}
                    {d.status === 'convert_blocked' && d.blockReason && (
                      <div style={{ fontSize: 10, color: 'var(--badge-red-text)', fontWeight: 500 }}>{d.blockReason}</div>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showNewDraft && <NewProformaDraftModal onClose={() => setShowNewDraft(false)} />}
    </div>
  );
}

// New Draft Modal (source picker) — simplified placeholder for now
function NewProformaDraftModal({ onClose }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 600, maxWidth: '92vw',
        boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Create Pro Forma Draft</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginTop: 2 }}>Select source</div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', fontSize: 22, cursor: 'pointer',
            color: 'var(--text-3)', lineHeight: 1,
          }}>×</button>
        </div>
        <div style={{ padding: 24 }}>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 16 }}>
            Choose how to create this draft (spec: ATLAS_PROFORMA_NEW_DRAFT_AND_CONVERT.md Phase 2a)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { label: 'From Shipment', icon: '📦', count: 4, desc: 'Create from existing shipment data' },
              { label: 'From Order', icon: '📋', count: 2, desc: 'Create from customer order' },
              { label: 'Manual Entry', icon: '✎', count: null, desc: 'Build from scratch' },
              { label: 'Clone Existing', icon: '⎘', count: 12, desc: 'Copy an existing draft' },
            ].map(src => (
              <button key={src.label} style={{
                textAlign: 'left', padding: 16, border: '1px solid var(--border)', borderRadius: 8,
                background: 'var(--bg-subtle)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 14,
                transition: 'all 0.12s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--card)'; e.currentTarget.style.borderColor = 'var(--accent)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-subtle)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
              >
                <div style={{ fontSize: 28 }}>{src.icon}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{src.label}</span>
                    {src.count != null && (
                      <span style={{
                        display: 'inline-block', padding: '2px 8px', borderRadius: 4,
                        background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)',
                        fontSize: 10, fontWeight: 700,
                      }}>{src.count}</span>
                    )}
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 3 }}>{src.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ProformaListPage, NewProformaDraftModal });
