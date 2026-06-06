// Pro Forma Detail (Screen B) — Sprint 36 Phase 1 authority recovery
// Authority sources (no fake/hardcoded data):
//   GET /api/v1/proforma/draft/{id}              → editable_lines, exchange_rate
//   GET /api/v1/settings/company-profile          → exporter identity
//   GET /api/v1/proforma/draft/{id}/disclose-post → VAT context
//   POST /api/v1/proforma/draft/{id}/to-invoice   → convert action (real API)
//   GET /api/v1/proforma/{batch_id}/{cn}/document.pdf → PDF download
//   GET /api/v1/proforma/draft/{id}/events        → history tab

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

  // WIRED: fetch company profile for exporter block (GET /api/v1/settings/company-profile)
  const [companyProfile, setCompanyProfile] = React.useState(null);
  React.useEffect(() => {
    window.EstrellaShared.apiFetch('/api/v1/settings/company-profile')
      .then(r => setCompanyProfile((r && r.profile) || null))
      .catch(() => setCompanyProfile(null));
  }, []);

  const vatResolution = disclosure && disclosure.vat_resolution;

  // ── Authority-wired detail construction ──────────────────────────────────────
  // Product lines from backend editable_lines (GET /api/v1/proforma/draft/{id})
  const lines = (liveDraft.editable_lines || []).map((ln, i) => ({
    seq:      i + 1,
    lineId:   ln.line_id || '',
    sku:      ln.product_code || '—',
    desc:     ln.design_no || ln.product_code || '—',
    qty:      parseFloat(ln.qty || 0),
    unitEur:  parseFloat(ln.unit_price || 0),
    netEur:   parseFloat(ln.unit_price || 0) * parseFloat(ln.qty || 0),
    hsCode:   ln.hs_code || '—',
    origin:   ln.origin || '—',
    purity:   ln.purity || '',
    currency: ln.currency || 'EUR',
  }));

  // FX rate from backend draft (no browser-side PLN conversion)
  const fxRate = liveDraft.exchange_rate ? parseFloat(liveDraft.exchange_rate) : null;

  // Payment terms from JSON blob
  const rawPt = liveDraft.payment_terms;
  const paymentTermsDisplay = rawPt
    ? (typeof rawPt === 'object'
        ? (Object.entries(rawPt).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—')
        : String(rawPt))
    : '—';

  // Exporter from company profile (GET /api/v1/settings/company-profile)
  const exporter = companyProfile
    ? {
        name:    companyProfile.legal_name || '—',
        vatEu:   companyProfile.vat_eu || '—',
        address: [companyProfile.street, companyProfile.postal_city].filter(Boolean).join(', ') || '—',
        country: companyProfile.country || '—',
      }
    : { name: '—', vatEu: '—', address: '—', country: '—' };

  // Customer from live draft resolution
  const cr = liveDraft.customer_resolution || {};
  const customer = {
    name:       liveDraft.client_name || draft.client_name || '—',
    vatEu:      cr.vat_eu || '—',
    address:    '—',
    country:    '—',
    wfirmaId:   cr.wfirma_customer_id || null,
    wfirmaName: cr.resolved_wfirma_customer_name || null,
  };

  const detail = {
    ...liveDraft,
    customer,
    exporter,
    fx: {
      rate:   fxRate,
      source: liveDraft.exchange_rate_source || 'NBP',
      date:   liveDraft.exchange_rate_date || '—',
      table:  liveDraft.nbp_table || '—',
    },
    lines,
    paymentTerms: paymentTermsDisplay,
    incoterm:     liveDraft.incoterm || '—',
  };
  // ─────────────────────────────────────────────────────────────────────────────

  const draftState = liveDraft.draft_state || liveDraft.status || draft.status || '';
  const canConvert = draftState === 'posted' || draftState === 'ready';
  const isBlocked  = draftState === 'post_failed' || draftState === 'convert_blocked';

  const blockingReasons = (preview && preview.blocking_reasons) || [];
  const exportBlockers  = (preview && preview.export_blockers)  || [];

  const handleDownloadPdf = () => {
    const bid = liveDraft.batch_id || draft.batch_id || '';
    const cn  = liveDraft.client_name || draft.client_name || '';
    if (!bid || !cn) return;
    window.open(`/api/v1/proforma/${encodeURIComponent(bid)}/${encodeURIComponent(cn)}/document.pdf`, '_blank');
  };

  const proformaLabel = liveDraft.wfirma_proforma_fullnumber || draft.wfirma_proforma_fullnumber || `Draft #${draft.id}`;

  return (
    <div data-testid="proforma-detail-root" data-screen-label={`Proforma ${proformaLabel}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg)' }}>

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
            {proformaLabel}
          </div>
        </div>

        <ProformaStatusChip status={draftState} />

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="outline" small onClick={handleDownloadPdf} data-testid="proforma-detail-download-pdf">↓ Download PDF</Btn>
          {isBlocked && (
            <Btn variant="outline" small disabled style={{ opacity: 0.5, cursor: 'not-allowed' }}>
              ⚠ Convert Blocked
            </Btn>
          )}
          {canConvert && (
            <Btn variant="gold" small onClick={() => setShowConvertModal(true)} data-testid="proforma-detail-convert-btn">
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
            <InfoRow label="EUR/PLN Rate" value={fxRate ? fxRate.toFixed(4) : '—'} />
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
            <OverviewTab detail={detail} lines={lines} fxRate={fxRate} />
          </>
        )}
        {activeTab === 'lines' && <LinesTab lines={detail.lines} />}
        {activeTab === 'customer_mapping' && <CustomerMappingTab customer={detail.customer} isBlocked={isBlocked} />}
        {activeTab === 'reservation' && <ReservationTab draft={draft} />}
        {activeTab === 'history' && <HistoryTab draft={draft} draftId={draft && draft.id} />}
      </div>

      {showConvertModal && (
        <ConvertToInvoiceModal
          draft={draft}
          detail={detail}
          onClose={() => setShowConvertModal(false)}
          onSuccess={() => {
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

function OverviewTab({ detail, lines, fxRate }) {
  const totalEur = lines.reduce((s, l) => s + l.netEur, 0);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SectionLabel>Summary</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
        <StatTile label="Line Items" value={lines.length} />
        <StatTile label="Currency" value={detail.currency || 'EUR'} />
        <StatTile label="Total EUR" value={`€${totalEur.toFixed(2)}`} accent="var(--accent)" />
        <StatTile label="FX Rate EUR/PLN" value={fxRate ? fxRate.toFixed(4) : '—'} />
      </div>

      <SectionLabel style={{ marginTop: 8 }}>Shipment reference</SectionLabel>
      <PanelCard>
        <div style={{ padding: '16px 20px' }}>
          <InfoRow label="Batch ID" value={detail.batch_id} mono />
          <InfoRow label="Client" value={detail.client_name} />
          <InfoRow label="Draft state" value={detail.draft_state} />
          <InfoRow label="Created" value={detail.created_at} />
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
            {lines.length === 0 && (
              <tr>
                <td colSpan="8" style={{ padding: '24px 14px', textAlign: 'center', fontSize: 12, color: 'var(--text-3)' }}>
                  No line items — draft not yet built from packing upload.
                </td>
              </tr>
            )}
            {lines.map((line, i) => (
              <tr key={line.lineId || line.seq} style={{ borderBottom: i < lines.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                <td style={{ padding: '12px 14px', fontSize: 11, color: 'var(--text-3)' }}>{line.seq}</td>
                <td style={{ padding: '12px 14px', fontFamily: 'monospace', fontSize: 11, fontWeight: 600, color: 'var(--text-2)' }}>{line.sku}</td>
                <td style={{ padding: '12px 14px' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{line.desc}</div>
                  {line.purity && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{line.purity}</div>}
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
              <td style={{ padding: '12px 14px', textAlign: 'right', fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: 'var(--accent)' }} data-testid="proforma-lines-total">
                {lines.length > 0 ? lines.reduce((s, l) => s + l.netEur, 0).toFixed(2) : '—'}
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
            Use the Customer Mapping page to establish the link.
          </div>
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
            Not yet wired — deferred post Sprint 36
          </div>
        </div>
      </PanelCard>
    </div>
  );
}

function HistoryTab({ draft, draftId }) {
  // WIRED: GET /api/v1/proforma/draft/{id}/events
  const [events, setEvents] = React.useState(null);
  React.useEffect(() => {
    if (!draftId) return;
    window.PzApi.getDraftEvents(draftId)
      .then(r => setEvents((r && r.events) ? r.events : []))
      .catch(() => setEvents([]));
  }, [draftId]);

  const displayEvents = (events !== null && events.length > 0) ? events : (
    events === null
      ? [{ ts: '…', user: '', action: 'Loading history…', status: 'loading' }]
      : [{ ts: draft.created_at || '—', user: draft.created_by || '—', action: 'Draft created', status: 'created' }]
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SectionLabel>Activity history</SectionLabel>
      <PanelCard>
        <div style={{ padding: '20px 24px' }}>
          <div style={{ position: 'relative', paddingLeft: 32 }}>
            <div style={{ position: 'absolute', left: 10, top: 8, bottom: 8, width: 2, background: 'var(--border)' }} />
            {displayEvents.map((e, i) => (
              <div key={i} style={{ position: 'relative', marginBottom: i < displayEvents.length - 1 ? 20 : 0, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                <div style={{
                  position: 'absolute', left: -32, width: 22, height: 22, borderRadius: 11,
                  background: 'var(--badge-green-bg)', border: `2px solid var(--badge-green-border)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1,
                }}>
                  <span style={{ fontSize: 11, color: 'var(--badge-green-text)', fontWeight: 700 }}>✓</span>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{e.action || e.event_type || e.description || '—'}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                    {e.ts || e.created_at || e.occurred_at || '—'} · {e.user || e.operator || '—'}
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

// Convert to Invoice Modal — wired to POST /api/v1/proforma/draft/{id}/to-invoice
function ConvertToInvoiceModal({ draft, detail, onClose, onSuccess }) {
  const [confirmed, setConfirmed] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [apiError, setApiError] = React.useState(null);

  const handleConvert = () => {
    if (!confirmed || loading) return;
    setLoading(true);
    setApiError(null);
    window.PzApi.draftToInvoice(draft.id, {
      confirm: 'YES_CREATE_FINAL_INVOICE_FROM_PROFORMA',
    })
      .then(() => { onSuccess && onSuccess(); })
      .catch(e => {
        setApiError((e && e.message) ? e.message : 'Conversion failed — check backend logs.');
        setLoading(false);
      });
  };

  const payload = {
    endpoint:         'POST /api/v1/proforma/draft/{id}/to-invoice',
    draftId:          draft.id,
    proformaNumber:   detail.wfirma_proforma_fullnumber || '—',
    wfirmaProformaId: detail.wfirma_proforma_id || '—',
    customer:         detail.customer.wfirmaId || '—',
    customerName:     detail.customer.wfirmaName || '—',
    lineCount:        detail.lines.length,
    currency:         detail.currency || 'EUR',
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

          {apiError && (
            <div style={{
              marginBottom: 16, padding: '10px 14px',
              background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
              borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600,
            }} data-testid="convert-modal-error">
              ⚠ {apiError}
            </div>
          )}

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
              data-testid="convert-modal-confirm-checkbox"
            />
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
              I understand this action is irreversible and will immediately post to wFirma
            </span>
          </label>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Btn variant="outline" onClick={onClose} disabled={loading}>Cancel</Btn>
            <Btn
              variant="default"
              disabled={!confirmed || loading}
              onClick={handleConvert}
              data-testid="convert-modal-submit"
              style={{
                background: (confirmed && !loading) ? 'var(--badge-red-text)' : 'var(--badge-neutral-bg)',
                color: (confirmed && !loading) ? '#fff' : 'var(--text-3)',
                cursor: (confirmed && !loading) ? 'pointer' : 'not-allowed',
                opacity: (confirmed && !loading) ? 1 : 0.5,
              }}
            >
              {loading ? '⏳ Converting…' : '⚠ Convert to Invoice'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ProformaDetailPage, ConvertToInvoiceModal });
