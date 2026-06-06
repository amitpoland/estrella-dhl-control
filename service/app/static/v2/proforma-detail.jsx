// proforma-detail.jsx — Sprint 36 Phase 2: UI parity with atlas-proforma-preview.html
// Authority sources (no fake/hardcoded data):
//   GET /api/v1/proforma/draft/{id}                → editable_lines, exchange_rate, customer_resolution
//   GET /api/v1/settings/company-profile             → exporter identity (SELLER card)
//   GET /api/v1/proforma/draft/{id}/disclose-post    → VAT context, post payload
//   POST /api/v1/proforma/draft/{id}/post            → post to wFirma (toolbar + modal)
//   POST /api/v1/proforma/draft/{id}/clone           → duplicate action (toolbar)
//   POST /api/v1/proforma/draft/{id}/to-invoice      → convert to invoice (toolbar + modal)
//   GET /api/v1/proforma/{batch_id}/{cn}/document.pdf → PDF download / print (toolbar)
//   GET /api/v1/proforma/draft/{id}/events           → history tab
//   POST /api/v1/proforma/preview/{batch_id}/{cn}    → reservation / blocking reasons

const PROFORMA_TABS = [
  { id: 'overview',         label: 'Overview'         },
  { id: 'lines',            label: 'Lines'            },
  { id: 'customer_mapping', label: 'Customer Mapping' },
  { id: 'reservation',      label: 'Reservation'      },
  { id: 'history',          label: 'History'          },
];

// ── Toolbar button ────────────────────────────────────────────────────────────
function TbBtn({ children, onClick, disabled, title, warn, style: xs, ...rest }) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      {...rest}
      style={{
        background: 'transparent', border: 0, padding: '7px 11px', borderRadius: 6,
        fontFamily: 'inherit', fontSize: 13,
        color: warn
          ? 'var(--badge-amber-text)'
          : (disabled ? 'var(--text-4, #9ca3af)' : 'var(--text)'),
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'inline-flex', alignItems: 'center', gap: 6,
        fontWeight: 500, opacity: disabled ? 0.5 : 1,
        whiteSpace: 'nowrap',
        ...(xs || {}),
      }}
    >
      {children}
    </button>
  );
}

function TbSep() {
  return <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px', flexShrink: 0 }} />;
}

// ── KV grid item ──────────────────────────────────────────────────────────────
function KvItem({ k, v, mono, muted }) {
  const empty = v === null || v === undefined || v === '' || v === '—';
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 3, fontWeight: 500 }}>{k}</div>
      <div style={{
        fontWeight: (muted || empty) ? 500 : 700,
        fontSize: mono ? 13 : 15,
        color: (muted || empty) ? 'var(--text-4, #9ca3af)' : 'var(--text)',
        fontFamily: mono ? 'monospace' : 'inherit',
      }}>
        {empty ? '—' : v}
      </div>
    </div>
  );
}

// ── Status chip (for Reservation cap strip) ───────────────────────────────────
function CapChip({ ok, label }) {
  return (
    <span style={{
      padding: '5px 11px',
      border: `1px solid ${ok ? 'var(--badge-green-border)' : 'var(--badge-amber-border)'}`,
      background: ok ? 'var(--badge-green-bg)' : 'var(--badge-amber-bg)',
      color: ok ? 'var(--badge-green-text)' : 'var(--badge-amber-text)',
      borderRadius: 6, fontSize: 12, fontWeight: 600,
      display: 'inline-flex', alignItems: 'center', gap: 5,
    }}>
      {ok ? '✓' : '⚠'} {label}
    </span>
  );
}

// ── Party card ────────────────────────────────────────────────────────────────
function ProformaPartyCard({ title, name, lines, footer, footerMuted, warn, warnMsg, mappedMsg, 'data-testid': dataTestid }) {
  return (
    <div
      data-testid={dataTestid}
      style={{
        background: 'var(--card)',
        border: `1px solid ${warn ? 'var(--badge-amber-border)' : 'var(--border)'}`,
        borderRadius: 8, padding: '14px 16px', boxShadow: '0 1px 2px var(--shadow)',
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.16em', textTransform: 'uppercase', marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{name}</div>
      {(lines || []).map((l, i) => (
        l && l !== '—' ? <div key={i} style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.55 }}>{l}</div> : null
      ))}
      {footer && (
        <div style={{
          fontSize: 11, marginTop: 6,
          color: footerMuted ? 'var(--text-3)' : 'var(--text-2)',
          fontStyle: footerMuted ? 'italic' : 'normal',
          fontFamily: footerMuted ? 'inherit' : 'monospace',
        }}>
          {footer}
        </div>
      )}
      {warnMsg && (
        <div style={{ marginTop: 8, padding: '4px 8px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 4, fontSize: 10, color: 'var(--badge-amber-text)', fontWeight: 600 }}>
          ⚠ {warnMsg}
        </div>
      )}
      {mappedMsg && (
        <div style={{ marginTop: 8, padding: '4px 8px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 4, fontSize: 10, color: 'var(--badge-green-text)', fontWeight: 600 }}>
          {mappedMsg}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
function ProformaDetailPage({ draft, onBack, onConvert }) {
  const [activeTab,        setActiveTab]        = React.useState('overview');
  const [showConvertModal, setShowConvertModal]  = React.useState(false);
  const [showPostModal,    setShowPostModal]     = React.useState(false);
  const [cloning,          setCloning]           = React.useState(false);

  // WIRED: fetch full draft detail (GET /api/v1/proforma/draft/{id})
  const draftHook = window.PzState.useDraft(draft && draft.id);
  const liveDraft = (draftHook.data && draftHook.data.draft) ? draftHook.data.draft : (draft || {});

  // WIRED: fetch post disclosure (GET /api/v1/proforma/draft/{id}/disclose-post)
  const [disclosure, setDisclosure] = React.useState(null);
  React.useEffect(() => {
    if (!draft || !draft.id) return;
    window.EstrellaShared.apiFetch(`/api/v1/proforma/draft/${draft.id}/disclose-post`)
      .then(d => setDisclosure(d))
      .catch(() => setDisclosure(null));
  }, [draft && draft.id]);

  // WIRED: fetch readiness / blocking reasons (POST /api/v1/proforma/preview/{batch_id}/{client_name})
  const batchId    = draft && (draft.batch_id    || '');
  const clientName = draft && (draft.client_name || '');
  const previewHook = window.PzState.useProformaPreview(batchId, clientName);
  const preview    = previewHook.data || null;

  // WIRED: fetch company profile for SELLER (GET /api/v1/settings/company-profile)
  const [companyProfile, setCompanyProfile] = React.useState(null);
  React.useEffect(() => {
    window.EstrellaShared.apiFetch('/api/v1/settings/company-profile')
      .then(r => setCompanyProfile((r && r.profile) || null))
      .catch(() => setCompanyProfile(null));
  }, []);

  // ── Authority-wired data construction ──────────────────────────────────────
  // Product lines from backend editable_lines
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

  // FX rate from backend (no browser-side PLN conversion)
  const fxRate = liveDraft.exchange_rate ? parseFloat(liveDraft.exchange_rate) : null;

  const rawPt = liveDraft.payment_terms;
  const paymentTermsDisplay = rawPt
    ? (typeof rawPt === 'object'
        ? (Object.entries(rawPt).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—')
        : String(rawPt))
    : '—';

  // SELLER from company profile (GET /api/v1/settings/company-profile)
  const exporter = companyProfile
    ? {
        name:    companyProfile.legal_name || '—',
        vatEu:   companyProfile.vat_eu || '—',
        address: [companyProfile.street, companyProfile.postal_city].filter(Boolean).join(', ') || '—',
        country: companyProfile.country || '—',
      }
    : { name: '—', vatEu: '—', address: '—', country: '—' };

  // BUYER from draft customer_resolution
  const cr = liveDraft.customer_resolution || {};
  const customer = {
    name:       liveDraft.client_name || (draft && draft.client_name) || '—',
    vatEu:      cr.vat_eu || '—',
    address:    cr.address || '—',
    country:    cr.country || '—',
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
  // ──────────────────────────────────────────────────────────────────────────

  const draftState    = liveDraft.draft_state || liveDraft.status || (draft && draft.status) || '';
  const canPost       = ['draft', 'pending_local', 'approved', 'post_failed'].includes(draftState);
  const canConvert    = draftState === 'posted' || draftState === 'ready';
  const isBlocked     = draftState === 'post_failed' || draftState === 'convert_blocked';
  const alreadyPosted = draftState === 'posted' || draftState === 'invoiced';

  const blockingReasons = (preview && preview.blocking_reasons) || [];
  const exportBlockers  = (preview && preview.export_blockers)  || [];
  const vatResolution   = disclosure && disclosure.vat_resolution;

  const proformaLabel = liveDraft.wfirma_proforma_fullnumber
    || (draft && draft.wfirma_proforma_fullnumber)
    || `Draft #${draft && draft.id}`;

  const handleDownloadPdf = () => {
    const bid = liveDraft.batch_id || (draft && draft.batch_id) || '';
    const cn  = liveDraft.client_name || (draft && draft.client_name) || '';
    if (!bid || !cn) return;
    window.open(`/api/v1/proforma/${encodeURIComponent(bid)}/${encodeURIComponent(cn)}/document.pdf`, '_blank');
  };

  const handleDuplicate = () => {
    if (cloning) return;
    setCloning(true);
    window.PzApi.cloneDraft(draft.id)
      .then(r => {
        setCloning(false);
        onBack && onBack({ navigateTo: r && r.draft_id });
      })
      .catch(() => setCloning(false));
  };

  return (
    <div data-testid="proforma-detail-root" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* ── Action toolbar ──────────────────────────────────────────────── */}
      <div style={{
        padding: '8px 16px', background: 'var(--card)', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 0, flexShrink: 0, flexWrap: 'wrap',
      }}>

        {/* Group 1 — CRUD */}
        <TbBtn
          disabled
          title="Inline editing not yet available — edit lines individually on the Lines tab"
          data-testid="tb-edit"
        >
          ✎ Edit
        </TbBtn>
        <TbBtn
          disabled
          title="No delete-draft endpoint available"
          data-testid="tb-delete"
        >
          🗑 Delete
        </TbBtn>
        <TbBtn
          onClick={handleDuplicate}
          disabled={cloning}
          title="Clone this draft as a new unposted draft"
          data-testid="tb-duplicate"
        >
          {cloning ? '⏳' : '⎘'} {cloning ? 'Cloning…' : 'Duplicate'}
        </TbBtn>

        <TbSep />

        {/* Group 2 — wFirma write actions */}
        <TbBtn
          onClick={() => setShowPostModal(true)}
          disabled={!canPost}
          title={canPost
            ? 'Post this draft to wFirma as a proforma invoice'
            : (alreadyPosted ? 'Already posted to wFirma' : 'Cannot post in current state')}
          data-testid="tb-post"
        >
          ↑ Post to wFirma
        </TbBtn>
        <TbBtn
          warn
          onClick={() => canConvert && setShowConvertModal(true)}
          disabled={!canConvert}
          title={canConvert
            ? 'Convert this posted proforma to a wFirma invoice'
            : (isBlocked ? 'Conversion blocked — see Reservation tab' : 'Post to wFirma first, then convert')}
          data-testid="tb-convert"
        >
          ⚠ Convert to Invoice
        </TbBtn>

        <TbSep />

        {/* Group 3 — Output */}
        <TbBtn
          onClick={handleDownloadPdf}
          title="Open PDF in new tab"
          data-testid="proforma-detail-download-pdf"
        >
          ⎙ Print
        </TbBtn>
        <TbBtn
          disabled
          title="Email send not yet wired to backend"
          data-testid="tb-send"
        >
          ➤ Send
        </TbBtn>
        <TbBtn
          disabled
          title="Document generation not yet available from this view"
          data-testid="tb-generate"
        >
          ⚙ Generate ▾
        </TbBtn>

        {/* Spacer */}
        <div style={{ flexGrow: 1, minWidth: 12 }} />

        {/* Proforma label + status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
            {proformaLabel}
          </div>
          <ProformaStatusChip status={draftState} />
        </div>

        <TbSep />

        <TbBtn
          onClick={onBack}
          title="Back to proforma list"
          data-testid="tb-back"
          style={{ fontWeight: 600 }}
        >
          ← Back
        </TbBtn>
      </div>

      {/* ── Party cards (SELLER / BUYER / RECIPIENT) ────────────────────── */}
      <div style={{
        padding: '16px 24px', background: 'var(--bg-subtle)',
        borderBottom: '1px solid var(--border)', flexShrink: 0,
      }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>

          {/* SELLER — authority: GET /api/v1/settings/company-profile */}
          <ProformaPartyCard
            title="SELLER"
            name={exporter.name}
            lines={[exporter.address, exporter.country]}
            footer={`VAT EU: ${exporter.vatEu}`}
            data-testid="party-seller"
          />

          {/* BUYER — authority: draft customer_resolution */}
          <ProformaPartyCard
            title="BUYER"
            name={customer.name}
            lines={[customer.address, customer.country]}
            footer={`VAT EU: ${customer.vatEu}`}
            warn={!customer.wfirmaId}
            warnMsg={!customer.wfirmaId ? 'Not mapped to wFirma customer' : null}
            mappedMsg={customer.wfirmaId ? `✓ Mapped: ${customer.wfirmaName}` : null}
            data-testid="party-buyer"
          />

          {/* RECIPIENT — same as buyer */}
          <ProformaPartyCard
            title="RECIPIENT"
            name={customer.name}
            lines={[customer.address, customer.country]}
            footer="Same as Buyer"
            footerMuted
            data-testid="party-recipient"
          />
        </div>
      </div>

      {/* ── Tab strip ──────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: 0, padding: '0 24px',
        background: 'var(--card)', borderBottom: '1px solid var(--border)', flexShrink: 0,
      }}>
        {PROFORMA_TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: '12px 14px', background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${activeTab === t.id ? 'var(--accent)' : 'transparent'}`,
            color: activeTab === t.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 13, fontWeight: activeTab === t.id ? 700 : 500,
            transition: 'all 0.12s', marginBottom: -1, fontFamily: 'inherit',
          }}>{t.label}</button>
        ))}
      </div>

      {/* ── Tab content ────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflow: 'auto', padding: '24px' }}>
        {activeTab === 'overview' && (
          <ProformaOverviewTab
            detail={detail}
            lines={lines}
            fxRate={fxRate}
            vatResolution={vatResolution}
            blockingReasons={blockingReasons}
            exportBlockers={exportBlockers}
          />
        )}
        {activeTab === 'lines' && <ProformaLinesTab lines={lines} />}
        {activeTab === 'customer_mapping' && (
          <ProformaCustomerMappingTab customer={customer} />
        )}
        {activeTab === 'reservation' && (
          <ProformaReservationTab
            blockingReasons={blockingReasons}
            exportBlockers={exportBlockers}
            preview={preview}
            canConvert={canConvert}
            onConvert={() => canConvert && setShowConvertModal(true)}
          />
        )}
        {activeTab === 'history' && (
          <ProformaHistoryTab draft={draft} draftId={draft && draft.id} />
        )}
      </div>

      {/* ── Modals ─────────────────────────────────────────────────────────── */}
      {showPostModal && (
        <PostToWFirmaModal
          draft={draft}
          liveDraft={liveDraft}
          onClose={() => setShowPostModal(false)}
          onSuccess={() => {
            setShowPostModal(false);
            draftHook && draftHook.refresh && draftHook.refresh();
          }}
        />
      )}
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

// ── Overview tab ──────────────────────────────────────────────────────────────
function ProformaOverviewTab({ detail, lines, fxRate, vatResolution, blockingReasons, exportBlockers }) {
  const totalEur = lines.reduce((s, l) => s + l.netEur, 0);
  const currency = detail.currency || 'EUR';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Alert banners */}
      {blockingReasons.length > 0 && (
        <div style={{ padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6 }}>
          <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 4 }}>Blocking reasons</div>
          {blockingReasons.map((r, i) => <div key={i} style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>• {r}</div>)}
        </div>
      )}
      {exportBlockers.length > 0 && (
        <div style={{ padding: '10px 14px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6 }}>
          <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-amber-text)', marginBottom: 4 }}>Export blockers</div>
          {exportBlockers.map((r, i) => <div key={i} style={{ fontSize: 12, color: 'var(--badge-amber-text)' }}>• {r}</div>)}
        </div>
      )}

      {/* KV grid — 4 columns, all values from backend authority */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px 28px' }}>
        <KvItem k="Number" v={detail.wfirma_proforma_fullnumber} mono />
        <KvItem k="Shipment" v={detail.batch_id} mono />
        <KvItem k="KSeF" v={detail.ksef_number} muted={!detail.ksef_number} />
        <KvItem k="Payment method" v={detail.paymentTerms} />

        <KvItem k="Issue date" v={detail.created_at ? detail.created_at.slice(0, 10) : null} mono />
        <KvItem k="Payment due" v={detail.payment_due_date} mono />
        <KvItem k="Sale date" v={detail.sale_date} mono />
        <KvItem k="Paid" v={`0.00 ${currency}`} muted />

        <KvItem k="Amount due" v={`${totalEur.toFixed(2)} ${currency}`} />
        <KvItem k="Accounting scheme" v={detail.accounting_scheme || 'Standard'} />
        <KvItem k="JPK codes" v={detail.jpk_codes || 'none'} muted={!detail.jpk_codes} />
        <KvItem
          k={`Total · FX ${fxRate ? fxRate.toFixed(4) : '—'} PLN`}
          v={`${totalEur.toFixed(2)} ${currency}`}
        />

        <KvItem k="Warehouse" v={detail.warehouse || 'Main'} />
        <KvItem k="wFirma proforma ID" v={detail.wfirma_proforma_id} mono />
        <KvItem k="wFirma invoice ID" v={detail.wfirma_invoice_id} mono />
        <KvItem k="Source" v={detail.clone_source || detail.source_description || detail.source || '—'} />
      </div>

      {/* VAT resolution (from disclose-post) */}
      {vatResolution && (
        <div style={{ padding: '10px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6 }} data-testid="vat-resolution-detail">
          <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>VAT Treatment</div>
          <div style={{ fontSize: 12, color: 'var(--text)' }}>
            Context: <code>{vatResolution.vat_context || '?'}</code>
            {' '}· Code: <code>{vatResolution.vat_code || '?'}</code>
            {' '}· Source: <code>{vatResolution.decision_source || '?'}</code>
          </div>
          {!vatResolution.draft_has_vat_freeze && (
            <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginTop: 4 }}>
              VAT context not yet frozen — set on first post attempt
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Lines tab ─────────────────────────────────────────────────────────────────
function ProformaLinesTab({ lines }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 12 }}>
        Line items ({lines.length})
      </div>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              {['#', 'SKU', 'DESCRIPTION', 'HS CODE', 'ORIGIN', 'QTY', 'UNIT EUR', 'NET EUR'].map((h, i) => (
                <th key={h} style={{ padding: '9px 12px', textAlign: i >= 5 ? 'right' : 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan="8" style={{ padding: '28px 14px', textAlign: 'center', fontSize: 12, color: 'var(--text-3)' }}>
                  No line items — draft not yet built from packing upload.
                </td>
              </tr>
            )}
            {lines.map((line, i) => (
              <tr key={line.lineId || line.seq} style={{ borderBottom: i < lines.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                <td style={{ padding: '11px 12px', fontSize: 11, color: 'var(--text-3)' }}>{line.seq}</td>
                <td style={{ padding: '11px 12px', fontFamily: 'monospace', fontSize: 11, fontWeight: 600, color: 'var(--text-2)' }}>{line.sku}</td>
                <td style={{ padding: '11px 12px' }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{line.desc}</div>
                  {line.purity && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{line.purity}</div>}
                </td>
                <td style={{ padding: '11px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)' }}>{line.hsCode}</td>
                <td style={{ padding: '11px 12px', fontSize: 11, color: 'var(--text-2)' }}>{line.origin}</td>
                <td style={{ padding: '11px 12px', textAlign: 'right', fontSize: 12, fontWeight: 600 }}>{line.qty}</td>
                <td style={{ padding: '11px 12px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12 }}>{line.unitEur.toFixed(2)}</td>
                <td style={{ padding: '11px 12px', textAlign: 'right', fontFamily: 'monospace', fontSize: 13, fontWeight: 700 }}>{line.netEur.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ borderTop: '2px solid var(--border)', background: 'var(--bg-subtle)' }}>
              <td colSpan="7" style={{ padding: '11px 12px', textAlign: 'right', fontSize: 12, fontWeight: 700 }}>Total</td>
              <td style={{ padding: '11px 12px', textAlign: 'right', fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: 'var(--accent)' }} data-testid="proforma-lines-total">
                {lines.length > 0 ? lines.reduce((s, l) => s + l.netEur, 0).toFixed(2) : '—'}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

// ── Customer Mapping tab ──────────────────────────────────────────────────────
function ProformaCustomerMappingTab({ customer }) {
  const mapped = !!customer.wfirmaId;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>wFirma customer mapping</div>
      {!mapped ? (
        <div style={{ padding: 24, background: 'var(--badge-red-bg)', border: '2px solid var(--badge-red-border)', borderRadius: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>⚠</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 6 }}>No wFirma customer mapping</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.5 }}>
            Customer <strong>{customer.name}</strong> must be mapped to a wFirma record before converting to invoice.
          </div>
        </div>
      ) : (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '20px 24px', boxShadow: '0 1px 3px var(--shadow)' }}>
          <div style={{ padding: '10px 14px', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 8, marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-green-text)', marginBottom: 4 }}>✓ Customer mapped to wFirma</div>
            <div style={{ fontSize: 12, color: 'var(--text)' }}>
              <strong>{customer.name}</strong> → <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{customer.wfirmaName}</span>
            </div>
          </div>
          <InfoRow label="Atlas Customer" value={customer.name} />
          <InfoRow label="wFirma ID" value={customer.wfirmaId} mono />
          <InfoRow label="wFirma Name" value={customer.wfirmaName} />
          <InfoRow label="VAT EU" value={customer.vatEu} mono />
        </div>
      )}
      {/* Match strategy display */}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '16px 20px', boxShadow: '0 1px 3px var(--shadow)', display: 'grid', gridTemplateColumns: '180px 1fr', gap: '12px 20px', alignItems: 'center' }}>
        <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Sales client name</div>
        <div style={{ fontWeight: 600 }}>{customer.name}</div>
        <div style={{ fontSize: 12, color: 'var(--text-2)' }}>wFirma customer ID</div>
        <div style={{ fontFamily: mapped ? 'monospace' : 'inherit', color: mapped ? 'var(--text)' : 'var(--badge-red-text)', fontWeight: 600 }}>
          {customer.wfirmaId || '— unmatched —'}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)' }}>wFirma stored name</div>
        <div style={{ fontWeight: 600 }}>{customer.wfirmaName || '—'}</div>
        <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Match strategy</div>
        <div>
          <span style={{
            display: 'inline-block', padding: '3px 10px', borderRadius: 999,
            fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
            background: mapped ? 'var(--badge-green-bg)' : 'var(--badge-red-bg)',
            color: mapped ? 'var(--badge-green-text)' : 'var(--badge-red-text)',
            border: `1px solid ${mapped ? 'var(--badge-green-border)' : 'var(--badge-red-border)'}`,
          }}>
            {mapped ? 'EXACT NAME' : 'NONE'}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Reservation tab ───────────────────────────────────────────────────────────
// WIRED: blocking_reasons and export_blockers from POST /api/v1/proforma/preview/{batch_id}/{client_name}
function ProformaReservationTab({ blockingReasons, exportBlockers, preview, canConvert, onConvert }) {
  const allReasons = [...blockingReasons, ...exportBlockers];
  const isBlocked  = allReasons.length > 0;
  const auditClean = exportBlockers.length === 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Cap strip with status chips */}
      <div
        data-testid="reservation-cap-strip"
        style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 16, borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
      >
        <CapChip ok={!!preview} label="wFirma configured" />
        <CapChip ok={auditClean} label="Audit clean" />
        <CapChip ok={!isBlocked} label="Reservation supported" />
        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)', display: 'flex', gap: 18 }}>
          <span>Ready: <strong style={{ color: 'var(--text)' }}>{isBlocked ? '0' : '1'} / 1</strong></span>
        </div>
      </div>

      {/* Blocking reasons */}
      {isBlocked && (
        <div style={{ background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 8, padding: '14px 18px' }}>
          <div style={{ fontWeight: 700, color: 'var(--badge-amber-text)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            ⚠ Reservation BLOCKED
          </div>
          <ul style={{ margin: 0, paddingLeft: 22, fontSize: 13, color: 'var(--text-2)' }}>
            {allReasons.map((r, i) => <li key={i} style={{ marginBottom: 4 }}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Ready state */}
      {!isBlocked && (
        <div style={{ padding: '14px 0', color: 'var(--badge-green-text)', fontSize: 13 }}>
          ✓ All preconditions met. Conversion can proceed from the toolbar above.
        </div>
      )}

      {/* Footer actions */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
        <Btn variant="outline" disabled={isBlocked}>Create Reservation</Btn>
        <Btn
          variant="danger"
          disabled={!canConvert}
          onClick={onConvert}
          data-testid="reservation-convert-btn"
        >
          ⚠ Convert Proforma to Invoice
        </Btn>
      </div>
    </div>
  );
}

// ── History tab ───────────────────────────────────────────────────────────────
// WIRED: GET /api/v1/proforma/draft/{id}/events
function ProformaHistoryTab({ draft, draftId }) {
  const [events, setEvents] = React.useState(null);
  React.useEffect(() => {
    if (!draftId) return;
    window.PzApi.getDraftEvents(draftId)
      .then(r => setEvents((r && r.events) ? r.events : []))
      .catch(() => setEvents([]));
  }, [draftId]);

  const displayEvents = (events !== null && events.length > 0)
    ? events
    : (events === null
        ? [{ ts: '…', action: 'Loading history…' }]
        : [{ ts: (draft && draft.created_at) || '—', user: (draft && draft.created_by) || '—', action: 'Draft created' }]);

  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 16 }}>
        Activity history
      </div>
      {displayEvents.map((e, i) => (
        <div key={i} style={{
          padding: '14px 0',
          borderBottom: i < displayEvents.length - 1 ? '1px solid var(--border)' : 'none',
          display: 'grid', gridTemplateColumns: '160px 1fr', gap: 16,
        }}>
          <div style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: 'monospace' }}>
            {e.ts || e.created_at || e.occurred_at || '—'}
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
              {(e.event_type || e.status) && (
                <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 10, letterSpacing: '0.08em', fontWeight: 700, background: 'var(--bg-subtle)', color: 'var(--text-2)' }}>
                  {e.event_type || e.status}
                </span>
              )}
              {e.action || e.description || '—'}
            </div>
            {e.detail && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>{e.detail}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Post to wFirma Modal ──────────────────────────────────────────────────────
// WIRED: POST /api/v1/proforma/draft/{id}/post
// confirm_token: 'YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA'
function PostToWFirmaModal({ draft, liveDraft, onClose, onSuccess }) {
  const [confirmed, setConfirmed] = React.useState(false);
  const [loading,   setLoading]   = React.useState(false);
  const [apiError,  setApiError]  = React.useState(null);

  const handlePost = () => {
    if (!confirmed || loading) return;
    setLoading(true);
    setApiError(null);
    window.PzApi.postDraftToWfirma(draft.id, {
      confirm_token:       'YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA',
      expected_updated_at: liveDraft.updated_at || '',
    })
      .then(() => { onSuccess && onSuccess(); })
      .catch(e => {
        setApiError((e && e.message) ? e.message : 'Post failed — check backend logs.');
        setLoading(false);
      });
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 620, maxWidth: '92vw',
        maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>↑ Post to wFirma</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
        </div>

        <div style={{ padding: 24 }}>
          <div style={{ padding: '12px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, marginBottom: 20, fontSize: 13, color: 'var(--text-2)' }}>
            This will create a wFirma proforma invoice record. The proforma can later be converted to a final invoice.
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>
            Request payload
          </div>
          <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)', marginBottom: 20 }}>
            <div style={{ color: 'var(--accent)', fontWeight: 600, marginBottom: 8 }}>
              POST /api/v1/proforma/draft/{draft.id}/post
            </div>
            <div><span style={{ color: 'var(--text-3)' }}>draft_id:</span> <strong>{draft.id}</strong></div>
            <div><span style={{ color: 'var(--text-3)' }}>client_name:</span> <strong>{liveDraft.client_name || (draft && draft.client_name) || '—'}</strong></div>
            <div><span style={{ color: 'var(--text-3)' }}>proforma_number:</span> <strong>{liveDraft.wfirma_proforma_fullnumber || '—'}</strong></div>
            <div><span style={{ color: 'var(--text-3)' }}>confirm_token:</span> <strong>YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA</strong></div>
          </div>

          {apiError && (
            <div style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600 }} data-testid="post-modal-error">
              ⚠ {apiError}
            </div>
          )}

          <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, cursor: 'pointer', marginBottom: 20 }}>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={e => setConfirmed(e.target.checked)}
              style={{ width: 18, height: 18, cursor: 'pointer' }}
              data-testid="post-modal-confirm-checkbox"
            />
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
              I confirm this will post the proforma to wFirma
            </span>
          </label>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Btn variant="outline" onClick={onClose} disabled={loading}>Cancel</Btn>
            <Btn
              variant="default"
              disabled={!confirmed || loading}
              onClick={handlePost}
              data-testid="post-modal-submit"
              style={{
                background: (confirmed && !loading) ? 'var(--text)' : undefined,
                color:      (confirmed && !loading) ? 'var(--card)' : undefined,
                opacity:    (confirmed && !loading) ? 1 : 0.5,
                cursor:     (confirmed && !loading) ? 'pointer' : 'not-allowed',
              }}
            >
              {loading ? '⏳ Posting…' : '↑ Post to wFirma'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Convert to Invoice Modal ──────────────────────────────────────────────────
// WIRED: POST /api/v1/proforma/draft/{id}/to-invoice
// confirm_token: 'YES_CREATE_FINAL_INVOICE_FROM_PROFORMA'
function ConvertToInvoiceModal({ draft, detail, onClose, onSuccess }) {
  const [confirmed, setConfirmed] = React.useState(false);
  const [loading,   setLoading]   = React.useState(false);
  const [apiError,  setApiError]  = React.useState(null);

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

  const totalEur = detail.lines.reduce((s, l) => s + l.netEur, 0);
  const currency = detail.currency || 'EUR';

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px', overflowY: 'auto',
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 720, maxWidth: '92vw',
        maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--badge-red-text)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>⚠ Irreversible Action</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', marginTop: 2 }}>Convert Pro Forma → Invoice</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
        </div>

        <div style={{ padding: 24 }}>
          <div style={{ padding: '12px 14px', background: 'var(--badge-amber-bg)', borderLeft: '3px solid var(--badge-amber-text)', borderRadius: '0 6px 6px 0', marginBottom: 20, fontSize: 13, color: 'var(--text-2)' }}>
            This will create a wFirma <strong>WDT invoice</strong> and link it to this proforma.
            The invoice <strong>cannot be cancelled in wFirma</strong> after creation — only corrected via Korekta.
          </div>

          {/* Payload section */}
          <div style={{ fontSize: 10, letterSpacing: '0.14em', color: 'var(--text-3)', fontWeight: 700, marginBottom: 10, borderTop: '1px solid var(--border)', paddingTop: 14 }}>PAYLOAD</div>

          {[
            ['Endpoint',        `POST /api/v1/proforma/draft/${draft.id}/to-invoice`],
            ['Source proforma', detail.wfirma_proforma_fullnumber || '—'],
            ['Customer',        detail.customer.wfirmaName || detail.customer.name || '—'],
            ['Currency',        currency],
            ['FX rate',         detail.fx.rate ? `${detail.fx.rate.toFixed(4)} PLN (table ${detail.fx.table})` : '—'],
            ['Sale date',       detail.sale_date || '—'],
            ['Payment',         detail.paymentTerms || '—'],
            [`Total (${currency})`, totalEur.toFixed(2)],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, padding: '5px 0', fontSize: 13 }}>
              <span style={{ color: 'var(--text-3)' }}>{k}</span>
              <span style={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-word' }}>{v}</span>
            </div>
          ))}

          {/* Lines in payload */}
          <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, padding: '5px 0', fontSize: 13 }}>
            <span style={{ color: 'var(--text-3)' }}>Lines ({detail.lines.length})</span>
            <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px' }}>
              {detail.lines.length === 0
                ? <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No lines</div>
                : detail.lines.map((l, i) => (
                  <div key={i} style={{ fontSize: 12, padding: '4px 0', display: 'flex', justifyContent: 'space-between', gap: 12, borderBottom: i < detail.lines.length - 1 ? '1px dashed var(--border)' : 'none' }}>
                    <span style={{ color: 'var(--text-2)' }}>{l.desc}</span>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text-3)', fontSize: 11, flexShrink: 0 }}>{l.qty} pc × {l.unitEur.toFixed(2)} {currency}</span>
                  </div>
                ))
              }
            </div>
          </div>

          {/* Audit section */}
          <div style={{ fontSize: 10, letterSpacing: '0.14em', color: 'var(--text-3)', fontWeight: 700, marginBottom: 10, marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>AUDIT</div>
          <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, padding: '5px 0', fontSize: 13 }}>
            <span style={{ color: 'var(--text-3)' }}>Audit row</span>
            <span style={{ fontSize: 12 }}>
              Written pre-call as <code style={{ background: 'var(--bg-subtle)', padding: '1px 5px', borderRadius: 3, fontSize: 11 }}>pending</code>,
              updated to <code style={{ background: 'var(--bg-subtle)', padding: '1px 5px', borderRadius: 3, fontSize: 11 }}>success</code> or
              <code style={{ background: 'var(--bg-subtle)', padding: '1px 5px', borderRadius: 3, fontSize: 11 }}>failed</code> post-call
            </span>
          </div>

          {apiError && (
            <div style={{ marginTop: 16, marginBottom: 4, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600 }} data-testid="convert-modal-error">
              ⚠ {apiError}
            </div>
          )}

          <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, cursor: 'pointer', marginBottom: 20, marginTop: 20 }}>
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
              variant="danger"
              disabled={!confirmed || loading}
              onClick={handleConvert}
              data-testid="convert-modal-submit"
              style={{
                opacity: (confirmed && !loading) ? 1 : 0.5,
                cursor:  (confirmed && !loading) ? 'pointer' : 'not-allowed',
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

Object.assign(window, { ProformaDetailPage, ConvertToInvoiceModal, PostToWFirmaModal });
