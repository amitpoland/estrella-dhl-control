// Pro Forma Detail (Screen B) — wFirma-style detail with 5 tabs + action toolbar
// Per ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md

const PROFORMA_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'lines', label: 'Lines' },
  { id: 'customer_mapping', label: 'Customer Mapping' },
  { id: 'reservation', label: 'Reservation' },
  { id: 'history', label: 'History' },
];

function ProformaDetailPage({ draft, onBack, onConvert }) {
  const [activeTab, setActiveTab] = React.useState('overview');
  const [showConvertModal, setShowConvertModal] = React.useState(false);

  // WIRED: fetch full draft detail from backend (GET /api/v1/proforma/draft/{id})
  const draftHook = window.PzState.useDraft(draft && draft.id);
  const liveDraft = (draftHook.data && draftHook.data.draft) ? draftHook.data.draft : draft;

  // WIRED: fetch VAT context from disclose-post (GET /api/v1/proforma/draft/{id}/disclose-post)
  const [disclosure, setDisclosure] = React.useState(null);
  React.useEffect(() => {
    if (!draft || !draft.id) return;
    window.EstrellaShared.apiFetch(`/api/v1/proforma/draft/${draft.id}/disclose-post`)
      .then(d => setDisclosure(d))
      .catch(() => setDisclosure(null));
  }, [draft && draft.id]);

  // WIRED: fetch readiness from preview (POST /api/v1/proforma/preview/{batch_id}/{client_name})
  const batchId = draft && (draft.batch_id || '');
  const clientName = draft && (draft.client_name || '');
  const previewHook = window.PzState.useProformaPreview(batchId, clientName);
  const preview = previewHook.data || null;

  const vatResolution = disclosure && disclosure.vat_resolution;

  const detail = {
    ...liveDraft,
    customer: {
      name: liveDraft.client_name || draft.client_name || '—',
      vatEu: '—',
      address: '—',
      country: '—',
      wfirmaId: null,
      wfirmaName: null,
    },
    exporter: {
      name: 'Estrella Jewels Sp. z o.o.',
      vatEu: 'PL5252532437',
      address: 'ul. Przykładowa 10, 00-001 Warszawa',
      country: 'Poland',
    },
    fx: {
      rate: 4.2650,
      source: 'NBP',
      date: '2026-05-10',
      table: 'A 089/2026',
    },
    lines: [
      { seq: 1, sku: 'RNG-AU750-001', desc: '18K Gold Ring with Diamond', qty: 2, unitEur: 1840.00, netEur: 3680.00, hsCode: '71131910', origin: 'IN', purity: '18K 750', wfirmaProductId: 'WF-PROD-8821' },
      { seq: 2, sku: 'NKL-AU585-008', desc: '14K Gold Necklace', qty: 3, unitEur: 980.50, netEur: 2941.50, hsCode: '71131910', origin: 'IN', purity: '14K 585', wfirmaProductId: 'WF-PROD-8822' },
      { seq: 3, sku: 'BRC-PT950-012', desc: 'Platinum Bracelet', qty: 1, unitEur: 4200.00, netEur: 4200.00, hsCode: '71131100', origin: 'CH', purity: 'PT 950', wfirmaProductId: 'WF-PROD-8823' },
    ],
    paymentTerms: 'Bank transfer · 14 days',
    incoterm: 'DDP Warsaw',
  };

  // Use live draft_state if available, fall back to mock status
  const draftState = liveDraft.draft_state || liveDraft.status || draft.status || '';
  const canConvert = draftState === 'posted' || draftState === 'ready';
  const isBlocked = draftState === 'post_failed' || draftState === 'convert_blocked';

  // Readiness from live preview
  const blockingReasons = (preview && preview.blocking_reasons) || [];
  const exportBlockers = (preview && preview.export_blockers) || [];

  return (
    <div data-screen-label={`Proforma ${draft.number}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg)' }}>
      
      {/* Action toolbar */}
      <div style={{
        padding: '16px 32px', background: 'var(--card)', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0, flexWrap: 'wrap',
      }}>
        <button onClick={onBack} style={{
          background: 'none', border: '1px solid var(--border)', cursor: 'pointer',
          padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
          color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: 6,
        }}>← Back to list</button>

        <div style={{ width: 1, height: 28, background: 'var(--border)' }} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 2 }}>
            Pro Forma Draft
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'monospace', color: 'var(--text)' }}>
            {draft.number}
          </div>
        </div>

        <ProformaStatusChip status={draft.status} />

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="outline" small>↓ Download PDF</Btn>
          <Btn variant="outline" small>✎ Edit Draft</Btn>
          {isBlocked && (
            <Btn variant="outline" small disabled style={{ opacity: 0.5, cursor: 'not-allowed' }}>
              ⚠ Convert Blocked
            </Btn>
          )}
          {canConvert && (
            <Btn variant="gold" small onClick={() => setShowConvertModal(true)}>
              ⚠ Convert to Invoice
            </Btn>
          )}
        </div>
      </div>

      {/* Party cards strip */}
      <div style={{ padding: '20px 32px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
          <PartyCard title="Exporter" party={detail.exporter} />
          <PartyCard title="Customer" party={detail.customer} highlight={isBlocked} />
          <div style={{
            background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
            padding: 14, boxShadow: '0 1px 2px var(--shadow)',
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
              FX & Payment
            </div>
            <InfoRow label="EUR/PLN Rate" value={detail.fx.rate.toFixed(4)} />
            <InfoRow label="NBP Table" value={detail.fx.table} />
            <InfoRow label="Rate Date" value={detail.fx.date} />
            <InfoRow label="Payment Terms" value={detail.paymentTerms} />
            <InfoRow label="Incoterm" value={detail.incoterm} />
          </div>
        </div>
      </div>

      {/* Tab strip */}
      <div style={{
        display: 'flex', gap: 4, padding: '0 32px', background: 'var(--card)',
        borderBottom: '1px solid var(--border)', flexShrink: 0,
      }}>
        {PROFORMA_TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: '12px 16px', background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${activeTab === t.id ? 'var(--accent)' : 'transparent'}`,
            color: activeTab === t.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 13, fontWeight: activeTab === t.id ? 700 : 500,
            transition: 'all 0.12s', marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '24px 32px' }}>
        {activeTab === 'overview' && (
          <>
            {/* LIVE: readiness blocking reasons */}
            {blockingReasons.length > 0 && (
              <div style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6 }}>
                <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 4 }}>Blocking reasons</div>
                {blockingReasons.map((r, i) => <div key={i} style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>{r}</div>)}
              </div>
            )}
            {exportBlockers.length > 0 && (
              <div style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6 }}>
                <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-amber-text)', marginBottom: 4 }}>Export blockers</div>
                {exportBlockers.map((r, i) => <div key={i} style={{ fontSize: 12, color: 'var(--badge-amber-text)' }}>{r}</div>)}
              </div>
            )}
            {/* LIVE: VAT resolution (from disclose-post, ADR-027 D4) */}
            {vatResolution && (
              <div style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--badge-neutral-bg)', border: '1px solid var(--border)', borderRadius: 6 }} data-testid="vat-resolution-detail">
                <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>VAT Treatment</div>
                <div style={{ fontSize: 12, color: 'var(--text)' }}>
                  Context: <code>{vatResolution.vat_context || '?'}</code>
                  {' '}&middot; Code: <code>{vatResolution.vat_code || '?'}</code>
                  {' '}&middot; Source: <code>{vatResolution.decision_source || '?'}</code>
                </div>
                {!vatResolution.draft_has_vat_freeze && (
                  <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginTop: 4 }}>VAT context not yet frozen (will be set on first post attempt)</div>
                )}
              </div>
            )}
            <OverviewTab detail={detail} />
          </>
        )}
        {activeTab === 'lines' && <LinesTab lines={detail.lines} />}
        {activeTab === 'customer_mapping' && <CustomerMappingTab customer={detail.customer} isBlocked={isBlocked} />}
        {activeTab === 'reservation' && <ReservationTab draft={draft} />}
        {activeTab === 'history' && <HistoryTab draft={draft} />}
      </div>

      {showConvertModal && (
        <ConvertToInvoiceModal
          draft={draft}
          detail={detail}
          onClose={() => setShowConvertModal(false)}
          onConfirm={() => {
            setShowConvertModal(false);
            onConvert && onConvert(draft);
          }}
        />
      )}
    </div>
  );
}

function PartyCard({ title, party, highlight }) {
  return (
    <div style={{
      background: 'var(--card)',
      border: `1px solid ${highlight ? 'var(--badge-red-border)' : 'var(--border)'}`,
      borderRadius: 8,
      padding: 14,
      boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>{party.name}</div>
      <div style={{ fontSize: 11, color: 'var(--text-2)', lineHeight: 1.4 }}>
        {party.address}<br/>
        {party.country}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 6, fontFamily: 'monospace' }}>
        VAT EU: {party.vatEu}
      </div>
      {party.wfirmaId && (
        <div style={{ marginTop: 6, padding: '4px 8px', background: 'var(--badge-green-bg)', border: `1px solid var(--badge-green-border)`, borderRadius: 4, fontSize: 10, color: 'var(--badge-green-text)', fontWeight: 600 }}>
          ✓ Mapped to wFirma: {party.wfirmaName}
        </div>
      )}
      {!party.wfirmaId && highlight && (
        <div style={{ marginTop: 6, padding: '4px 8px', background: 'var(--badge-red-bg)', border: `1px solid var(--badge-red-border)`, borderRadius: 4, fontSize: 10, color: 'var(--badge-red-text)', fontWeight: 600 }}>
          ⚠ No wFirma mapping
        </div>
      )}
    </div>
  );
}

function OverviewTab({ detail }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SectionLabel>Summary</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
        <StatTile label="Line Items" value={detail.lines.length} />
        <StatTile label="Total Items" value={detail.items} />
        <StatTile label="Total EUR" value={`€${detail.totalEur.toFixed(2)}`} accent="var(--accent)" />
        <StatTile label="Total PLN" value={`zł ${(detail.totalEur * detail.fx.rate).toFixed(2)}`} />
      </div>

      <SectionLabel style={{ marginTop: 8 }}>Shipment reference</SectionLabel>
      <PanelCard>
        <div style={{ padding: '16px 20px' }}>
          <InfoRow label="Shipment ID" value={detail.shipmentId} mono />
          <InfoRow label="AWB / Tracking" value={detail.shipmentAwb} mono />
          <InfoRow label="Source" value={SOURCE_LABEL[detail.source]} />
          <InfoRow label="Created" value={detail.createdAt} />
          <InfoRow label="Created by" value={detail.createdBy} />
        </div>
      </PanelCard>
    </div>
  );
}

function LinesTab({ lines }) {
  return (
    <div>
      <SectionLabel>Line items ({lines.length})</SectionLabel>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>#</th>
              <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>SKU</th>
              <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Description</th>
              <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>HS Code</th>
              <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Origin</th>
              <th style={{ padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Qty</th>
              <th style={{ padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Unit EUR</th>
              <th style={{ padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Net EUR</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, i) => (
              <tr key={line.seq} style={{ borderBottom: i < lines.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                <td style={{ padding: '12px 14px', fontSize: 11, color: 'var(--text-3)' }}>{line.seq}</td>
                <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontSize: 11, fontWeight: 600, color: 'var(--text-2)' }}>{line.sku}</td>
                <td style={{ padding: '12px 14px' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{line.desc}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{line.purity}</div>
                </td>
                <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)' }}>{line.hsCode}</td>
                <td style={{ padding: '12px 14px', fontSize: 11, color: 'var(--text-2)' }}>{line.origin}</td>
                <td style={{ padding: '12px 14px', textAlign: 'right', fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{line.qty}</td>
                <td style={{ padding: '12px 14px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, color: 'var(--text)' }}>{line.unitEur.toFixed(2)}</td>
                <td style={{ padding: '12px 14px', textAlign: 'right', fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{line.netEur.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ borderTop: '2px solid var(--border)', background: 'var(--bg-subtle)' }}>
              <td colSpan="7" style={{ padding: '12px 14px', textAlign: 'right', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>Total</td>
              <td style={{ padding: '12px 14px', textAlign: 'right', fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: 'var(--accent)' }}>
                {lines.reduce((sum, l) => sum + l.netEur, 0).toFixed(2)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function CustomerMappingTab({ customer, isBlocked }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SectionLabel>wFirma customer mapping</SectionLabel>
      {isBlocked ? (
        <div style={{
          padding: 24, background: 'var(--badge-red-bg)', border: `2px solid var(--badge-red-border)`,
          borderRadius: 10, textAlign: 'center',
        }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>⚠</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 6 }}>
            No wFirma customer mapping
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 16, lineHeight: 1.5 }}>
            This customer must be mapped to a wFirma customer record before converting to invoice.
          </div>
          <Btn variant="gold" small>Open wFirma Mapping Setup</Btn>
        </div>
      ) : (
        <PanelCard>
          <div style={{ padding: '16px 20px' }}>
            <div style={{ padding: '12px 14px', background: 'var(--badge-green-bg)', border: `1px solid var(--badge-green-border)`, borderRadius: 8, marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-green-text)', marginBottom: 6 }}>✓ Customer mapped to wFirma</div>
              <div style={{ fontSize: 12, color: 'var(--text)' }}>
                <strong>{customer.name}</strong> → <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{customer.wfirmaName}</span>
              </div>
            </div>
            <InfoRow label="Atlas Customer" value={customer.name} />
            <InfoRow label="wFirma ID" value={customer.wfirmaId} mono />
            <InfoRow label="wFirma Name" value={customer.wfirmaName} />
            <InfoRow label="VAT EU" value={customer.vatEu} mono />
          </div>
        </PanelCard>
      )}
    </div>
  );
}

function ReservationTab({ draft }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SectionLabel>Reservation status</SectionLabel>
      <PanelCard>
        <div style={{ padding: 24, textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 8 }}>
            Reservation gate status for this draft
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
            Not implemented in this wireframe
          </div>
        </div>
      </PanelCard>
    </div>
  );
}

function HistoryTab({ draft }) {
  const events = [
    { ts: draft.createdAt, user: draft.createdBy, action: 'Draft created', status: 'created' },
    { ts: '2026-05-10 14:25', user: 'System', action: 'Customer mapping verified', status: 'verified' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SectionLabel>Activity history</SectionLabel>
      <PanelCard>
        <div style={{ padding: '20px 24px' }}>
          <div style={{ position: 'relative', paddingLeft: 32 }}>
            <div style={{ position: 'absolute', left: 10, top: 8, bottom: 8, width: 2, background: 'var(--border)' }} />
            {events.map((e, i) => (
              <div key={i} style={{ position: 'relative', marginBottom: i < events.length - 1 ? 20 : 0, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                <div style={{
                  position: 'absolute', left: -32, width: 22, height: 22, borderRadius: 11,
                  background: 'var(--badge-green-bg)', border: `2px solid var(--badge-green-border)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1,
                }}>
                  <span style={{ fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 700 }}>✓</span>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{e.action}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                    {e.ts} · {e.user}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </PanelCard>
    </div>
  );
}

// Convert to Invoice Modal — full payload disclosure + idempotency key
function ConvertToInvoiceModal({ draft, detail, onClose, onConfirm }) {
  const [idempotencyKey, setIdempotencyKey] = React.useState(`INV-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`);
  const [confirmed, setConfirmed] = React.useState(false);

  const payload = {
    endpoint: 'POST /api/v1/proforma/{id}/convert-to-invoice',
    proformaId: draft.id,
    proformaNumber: draft.number,
    customer: detail.customer.wfirmaId,
    customerName: detail.customer.wfirmaName,
    totalEur: detail.totalEur,
    fxRate: detail.fx.rate,
    totalPln: (detail.totalEur * detail.fx.rate).toFixed(2),
    lineCount: detail.lines.length,
    idempotencyKey,
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 680, maxWidth: '92vw',
        maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{
          padding: '18px 24px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--badge-red-text)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              ⚠ Irreversible Action
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', marginTop: 2 }}>
              Convert Pro Forma to Invoice
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', fontSize: 24, cursor: 'pointer',
            color: 'var(--text-3)', lineHeight: 1,
          }}>×</button>
        </div>

        <div style={{ padding: 24 }}>
          {/* Warning block */}
          <div style={{
            padding: '14px 16px', background: 'var(--badge-red-bg)', border: `2px solid var(--badge-red-border)`,
            borderRadius: 8, marginBottom: 20,
          }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 6 }}>
              ⚠ This action is irreversible
            </div>
            <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>
              Converting this Pro Forma to an Invoice will immediately post it to wFirma and cannot be undone.
              The invoice will be assigned a permanent number and recorded in the accounting ledger.
            </div>
          </div>

          {/* Payload disclosure */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>
              Request payload
            </div>
            <div style={{
              background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8,
              padding: '14px 16px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)',
              maxHeight: 240, overflowY: 'auto',
            }}>
              <div style={{ color: 'var(--badge-blue-text)', fontWeight: 600, marginBottom: 8 }}>
                {payload.endpoint}
              </div>
              {Object.entries(payload).filter(([k]) => k !== 'endpoint').map(([k, v]) => (
                <div key={k} style={{ marginBottom: 4 }}>
                  <span style={{ color: 'var(--text-3)' }}>{k}:</span> <span style={{ fontWeight: 600 }}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Idempotency key */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
              Idempotency key (pre-reserved)
            </div>
            <div style={{
              padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)',
              borderRadius: 6, fontFamily: 'monospace', fontSize: 12, color: 'var(--text)',
            }}>
              {idempotencyKey}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 4 }}>
              This key ensures the operation runs exactly once, even if the network fails mid-request.
            </div>
          </div>

          {/* Confirmation checkbox */}
          <label style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px',
            background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8,
            cursor: 'pointer', marginBottom: 20,
          }}>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={e => setConfirmed(e.target.checked)}
              style={{ width: 18, height: 18, cursor: 'pointer' }}
            />
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
              I understand this action is irreversible and will immediately post to wFirma
            </span>
          </label>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Btn variant="outline" onClick={onClose}>Cancel</Btn>
            <Btn
              variant="default"
              disabled={!confirmed}
              onClick={onConfirm}
              style={{
                background: confirmed ? 'var(--badge-red-text)' : 'var(--badge-neutral-bg)',
                color: confirmed ? '#fff' : 'var(--text-3)',
                cursor: confirmed ? 'pointer' : 'not-allowed',
                opacity: confirmed ? 1 : 0.5,
              }}
            >
              ⚠ Convert to Invoice
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ProformaDetailPage, ConvertToInvoiceModal });
