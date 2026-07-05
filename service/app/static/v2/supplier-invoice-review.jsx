// supplier-invoice-review.jsx — Supplier Invoice OCR review page (V2 SPA).
//
// Upload a foreign supplier invoice (PDF/PNG/JPG) → Claude vision extraction
// draft → operator reviews in a two-pane layout (source preview left,
// editable fields right, needs_review fields amber-highlighted) → Confirm
// freezes the operator-corrected values. NO wFirma write: a confirmed draft
// is the operator's reference for booking the expense manually.
//
// Layer rules: transport via window.PzApi only; shared atoms (Btn, Card,
// FormField, Input) from components.jsx. NO spread-rest anywhere in this file
// (DECISIONS "V2-wide spread-rest collision sweep").

const SIR_STATUS_STYLE = {
  pending_review: { bg: 'var(--badge-amber-bg)', text: 'var(--badge-amber-text)', border: 'var(--badge-amber-border)', label: 'Pending review' },
  confirmed:      { bg: 'var(--badge-green-bg)', text: 'var(--badge-green-text)', border: 'var(--badge-green-border)', label: 'Confirmed' },
  rejected:       { bg: 'var(--badge-red-bg)',   text: 'var(--badge-red-text)',   border: 'var(--badge-red-border)',   label: 'Rejected' },
};

function SirStatusPill({ status }) {
  const s = SIR_STATUS_STYLE[status] || SIR_STATUS_STYLE.pending_review;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap',
    }}>{s.label}</span>
  );
}

// Amber wrapper for fields the extraction flagged as uncertain
// (ProformaPartyCard `warn` convention).
function SirReviewHighlight({ fieldName, needsReview, children }) {
  const flagged = Array.isArray(needsReview) && needsReview.includes(fieldName);
  if (!flagged) return children;
  return (
    <div data-testid={`needs-review-${fieldName.replace(/_/g, '-')}`} style={{
      border: '1px solid var(--badge-amber-border)',
      background: 'var(--badge-amber-bg)',
      borderRadius: 6, padding: '6px 8px', marginBottom: 16,
    }}>
      {children}
      <div style={{ fontSize: 10, color: 'var(--badge-amber-text)', marginTop: 2 }}>
        ⚠ Extraction not confident — verify against the document
      </div>
    </div>
  );
}

// Field keys follow the SHARED vision_extractor schema (supplier, invoice_no,
// hsn, unit_price_usd, total_usd, …) — single extraction authority; never
// rename a concept the shipment flow already names. UI labels stay
// human-readable independently of the keys.
const SIR_EMPTY_LINE = { description: '', hsn: '', quantity: '', unit: '', unit_price_usd: '', total_usd: '' };
const SIR_EMPTY_TAX  = { tax_type: '', rate: '', amount: '' };

function sirToEditFields(src) {
  const f = src || {};
  return {
    supplier:         f.supplier || '',
    supplier_address: f.supplier_address || '',
    supplier_gstin:   f.supplier_gstin || '',
    invoice_no:       f.invoice_no || '',
    invoice_date:     f.invoice_date || '',
    currency:         f.currency || '',
    subtotal:         f.subtotal != null ? String(f.subtotal) : '',
    // total_amount: machine-extracted grand total (invoice currency, as
    // printed — operator ruling 2026-07-03); operator can override on review.
    total_amount:     f.total_amount != null ? String(f.total_amount) : '',
    line_items: (Array.isArray(f.line_items) ? f.line_items : []).map(it => ({
      description:    it.description || '',
      hsn:            it.hsn || '',
      quantity:       it.quantity != null ? String(it.quantity) : '',
      unit:           it.unit || '',
      unit_price_usd: it.unit_price_usd != null ? String(it.unit_price_usd) : '',
      total_usd:      it.total_usd != null ? String(it.total_usd) : '',
    })),
    tax_details: (Array.isArray(f.tax_details) ? f.tax_details : []).map(tx => ({
      tax_type: tx.tax_type || '',
      rate:     tx.rate != null ? String(tx.rate) : '',
      amount:   tx.amount != null ? String(tx.amount) : '',
    })),
  };
}

function sirNum(v) {
  const s = String(v == null ? '' : v).trim();
  if (!s) return null;
  const n = Number(s.replace(/,/g, ''));
  return Number.isFinite(n) ? n : s; // keep the operator's literal text if not numeric
}

function sirToConfirmedFields(ef) {
  return {
    supplier:         ef.supplier.trim() || null,
    supplier_address: ef.supplier_address.trim() || null,
    supplier_gstin:   ef.supplier_gstin.trim() || null,
    invoice_no:       ef.invoice_no.trim() || null,
    invoice_date:     ef.invoice_date.trim() || null,
    currency:         ef.currency.trim().toUpperCase() || null,
    subtotal:         sirNum(ef.subtotal),
    total_amount:     sirNum(ef.total_amount),
    line_items: ef.line_items
      .filter(it => it.description.trim())
      .map(it => ({
        description:    it.description.trim(),
        hsn:            it.hsn.trim() || null,
        quantity:       sirNum(it.quantity),
        unit:           it.unit.trim() || null,
        unit_price_usd: sirNum(it.unit_price_usd),
        total_usd:      sirNum(it.total_usd),
      })),
    tax_details: ef.tax_details
      .filter(tx => tx.tax_type.trim())
      .map(tx => ({
        tax_type: tx.tax_type.trim(),
        rate:     sirNum(tx.rate),
        amount:   sirNum(tx.amount),
      })),
  };
}

// ── Detail view — two-pane review ────────────────────────────────────────────

function SirDetailView({ draftId, onBack, onChanged }) {
  const [draft, setDraft]           = React.useState(null);
  const [loadError, setLoadError]   = React.useState(null);
  const [editFields, setEditFields] = React.useState(null);
  const [busy, setBusy]             = React.useState(false);
  const [actionError, setActionError] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoadError(null);
    const r = await window.PzApi.getSupplierInvoiceDraft(draftId);
    if (!r.ok) { setLoadError(r.error); return; }
    const d = r.data.draft;
    setDraft(d);
    // Confirmed drafts show the operator's frozen values; pending drafts
    // pre-fill from the validated machine extraction. raw_extraction is the
    // full provenance dict — its .fields is the last-resort source.
    setEditFields(sirToEditFields(
      d.confirmed_fields || d.machine_original || (d.raw_extraction && d.raw_extraction.fields)
    ));
  }, [draftId]);

  React.useEffect(() => { load(); }, [load]);

  if (loadError) {
    return (
      <Card style={{ margin: 24, padding: 20 }} data-testid="supplier-invoice-detail-error">
        <div style={{ color: 'var(--badge-red-text)', fontSize: 12 }}>{loadError}</div>
        <div style={{ marginTop: 10 }}><Btn variant="outline" small onClick={onBack}>← Back to list</Btn></div>
      </Card>
    );
  }
  if (!draft || !editFields) {
    return <div style={{ padding: 32, fontSize: 12, color: 'var(--text-2)' }} data-testid="supplier-invoice-detail-loading">Loading draft…</div>;
  }

  const needsReview = draft.needs_review || [];
  const readOnly    = draft.status !== 'pending_review';
  const isPdf       = /\.pdf$/i.test(draft.source_filename || '');
  const sourceUrl   = `/api/v1/supplier-invoice-ocr/drafts/${draft.id}/source-file`;

  const setF = (name, value) => setEditFields(prev => ({ ...prev, [name]: value }));
  const setLine = (i, name, value) => setEditFields(prev => ({
    ...prev,
    line_items: prev.line_items.map((it, idx) => idx === i ? { ...it, [name]: value } : it),
  }));
  const setTax = (i, name, value) => setEditFields(prev => ({
    ...prev,
    tax_details: prev.tax_details.map((tx, idx) => idx === i ? { ...tx, [name]: value } : tx),
  }));

  const doConfirm = async () => {
    setBusy(true); setActionError(null);
    const r = await window.PzApi.confirmSupplierInvoiceDraft(draft.id, sirToConfirmedFields(editFields));
    setBusy(false);
    if (!r.ok) { setActionError(r.error); return; }
    await load();
    if (onChanged) onChanged();
  };
  const doReject = async () => {
    setBusy(true); setActionError(null);
    const r = await window.PzApi.rejectSupplierInvoiceDraft(draft.id);
    setBusy(false);
    if (!r.ok) { setActionError(r.error); return; }
    await load();
    if (onChanged) onChanged();
  };

  const textField = (name, label, hint) => (
    <SirReviewHighlight fieldName={name} needsReview={needsReview}>
      <FormField label={label} hint={hint}>
        <Input value={editFields[name]}
               onChange={e => setF(name, e.target.value)}
               data-testid={`field-${name.replace(/_/g, '-')}`}
               style={readOnly ? { opacity: 0.7, pointerEvents: 'none' } : {}} />
      </FormField>
    </SirReviewHighlight>
  );

  const cellInput = (value, onChange, testid) => (
    <input value={value} onChange={onChange} data-testid={testid} readOnly={readOnly} style={{
      width: '100%', padding: '4px 6px', borderRadius: 4, boxSizing: 'border-box',
      border: '1px solid var(--border)', fontSize: 11, color: 'var(--text)',
      background: readOnly ? 'var(--bg)' : 'var(--bg-subtle)', outline: 'none',
    }} />
  );

  const th = { textAlign: 'left', fontSize: 10, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.04em', padding: '4px 6px' };

  return (
    <div data-testid="supplier-invoice-detail-view" style={{ padding: '16px 32px 32px', display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0 }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Btn variant="outline" small onClick={onBack} data-testid="supplier-invoice-back-btn">← Drafts</Btn>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>#{draft.id} · {draft.source_filename}</span>
        <SirStatusPill status={draft.status} />
        {draft.extraction_method && (
          <span style={{ fontSize: 10, color: 'var(--text-3)' }}>
            extraction: {draft.extraction_method}
            {draft.extraction_confidence != null ? ` · confidence ${Math.round(draft.extraction_confidence * 100)}%` : ''}
          </span>
        )}
        <div style={{ flex: 1 }} />
        {!readOnly && (
          <Btn variant="danger" small disabled={busy} onClick={doReject} data-testid="reject-btn">Reject draft</Btn>
        )}
        {!readOnly && (
          <Btn variant="gold" small disabled={busy} onClick={doConfirm} data-testid="confirm-btn">
            ✓ Confirm reviewed values
          </Btn>
        )}
      </div>

      {draft.status === 'confirmed' && (
        <div style={{ fontSize: 11, color: 'var(--badge-green-text)', background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)', borderRadius: 6, padding: '6px 10px' }}>
          Confirmed by {draft.confirmed_by} at {draft.confirmed_at}. Book the wFirma expense manually using these values — this app does not write expenses.
        </div>
      )}
      {actionError && (
        <div data-testid="supplier-invoice-action-error" style={{ fontSize: 11, color: 'var(--badge-red-text)', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, padding: '6px 10px' }}>
          {actionError}
        </div>
      )}
      {needsReview.length > 0 && draft.status === 'pending_review' && (
        <div data-testid="needs-review-banner" style={{ fontSize: 11, color: 'var(--badge-amber-text)', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, padding: '6px 10px' }}>
          ⚠ Extraction flagged for review: {needsReview.join(', ')}
        </div>
      )}

      {/* Two-pane: source preview | editable fields */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, flex: 1, minHeight: 0 }}>
        <Card style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 480 }} data-testid="supplier-invoice-source-pane">
          {isPdf ? (
            <iframe title="Invoice source" src={sourceUrl} data-testid="supplier-invoice-source-preview"
                    style={{ border: 'none', width: '100%', flex: 1, minHeight: 480 }} />
          ) : (
            <div style={{ overflow: 'auto', flex: 1, padding: 8 }}>
              <img alt="Invoice source" src={sourceUrl} data-testid="supplier-invoice-source-preview"
                   style={{ maxWidth: '100%', display: 'block' }} />
            </div>
          )}
        </Card>

        <Card style={{ overflow: 'auto', padding: 16 }} data-testid="supplier-invoice-fields-pane">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            {textField('supplier', 'Supplier')}
            {textField('supplier_gstin', 'Supplier GSTIN')}
          </div>
          {textField('supplier_address', 'Supplier address')}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', columnGap: 12 }}>
            {textField('invoice_no', 'Invoice No.')}
            {textField('invoice_date', 'Invoice date (YYYY-MM-DD)')}
            {textField('currency', 'Currency')}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            {textField('subtotal', 'Subtotal (invoice currency)')}
            {textField('total_amount', 'Total amount',
                       'Grand total in the invoice currency, as printed — verify against the document')}
          </div>

          {/* Line items */}
          <SirReviewHighlight fieldName="line_items" needsReview={needsReview}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.04em', margin: '8px 0 5px' }}>Line items</div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="line-items-table">
              <thead><tr>
                <th style={th}>Description</th><th style={th}>HSN</th><th style={th}>Qty</th>
                <th style={th}>Unit</th><th style={th}>Unit price</th><th style={th}>Line total</th>
                {!readOnly && <th style={th} />}
              </tr></thead>
              <tbody>
                {editFields.line_items.map((it, i) => (
                  <tr key={i}>
                    <td style={{ padding: 2, width: '32%' }}>{cellInput(it.description, e => setLine(i, 'description', e.target.value), `line-item-${i}-description`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(it.hsn, e => setLine(i, 'hsn', e.target.value), `line-item-${i}-hsn`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(it.quantity, e => setLine(i, 'quantity', e.target.value), `line-item-${i}-quantity`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(it.unit, e => setLine(i, 'unit', e.target.value), `line-item-${i}-unit`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(it.unit_price_usd, e => setLine(i, 'unit_price_usd', e.target.value), `line-item-${i}-unit-price-usd`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(it.total_usd, e => setLine(i, 'total_usd', e.target.value), `line-item-${i}-total-usd`)}</td>
                    {!readOnly && (
                      <td style={{ padding: 2 }}>
                        <Btn variant="ghost" small data-testid={`line-item-${i}-remove`}
                             onClick={() => setEditFields(prev => ({ ...prev, line_items: prev.line_items.filter((_, idx) => idx !== i) }))}>✕</Btn>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {!readOnly && (
              <div style={{ marginTop: 6 }}>
                <Btn variant="outline" small data-testid="line-item-add"
                     onClick={() => setEditFields(prev => ({ ...prev, line_items: prev.line_items.concat([{ ...SIR_EMPTY_LINE }]) }))}>+ Add line</Btn>
              </div>
            )}
          </SirReviewHighlight>

          {/* Tax details */}
          <SirReviewHighlight fieldName="tax_details" needsReview={needsReview}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.04em', margin: '14px 0 5px' }}>Tax details</div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="tax-details-table">
              <thead><tr>
                <th style={th}>Tax type</th><th style={th}>Rate %</th><th style={th}>Amount</th>
                {!readOnly && <th style={th} />}
              </tr></thead>
              <tbody>
                {editFields.tax_details.map((tx, i) => (
                  <tr key={i}>
                    <td style={{ padding: 2 }}>{cellInput(tx.tax_type, e => setTax(i, 'tax_type', e.target.value), `tax-detail-${i}-tax-type`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(tx.rate, e => setTax(i, 'rate', e.target.value), `tax-detail-${i}-rate`)}</td>
                    <td style={{ padding: 2 }}>{cellInput(tx.amount, e => setTax(i, 'amount', e.target.value), `tax-detail-${i}-amount`)}</td>
                    {!readOnly && (
                      <td style={{ padding: 2 }}>
                        <Btn variant="ghost" small data-testid={`tax-detail-${i}-remove`}
                             onClick={() => setEditFields(prev => ({ ...prev, tax_details: prev.tax_details.filter((_, idx) => idx !== i) }))}>✕</Btn>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {!readOnly && (
              <div style={{ marginTop: 6 }}>
                <Btn variant="outline" small data-testid="tax-detail-add"
                     onClick={() => setEditFields(prev => ({ ...prev, tax_details: prev.tax_details.concat([{ ...SIR_EMPTY_TAX }]) }))}>+ Add tax row</Btn>
              </div>
            )}
          </SirReviewHighlight>
        </Card>
      </div>
    </div>
  );
}

// ── List view — drafts table + upload panel ──────────────────────────────────

function SupplierInvoiceReviewPage() {
  const [view, setView]                 = React.useState('list');   // 'list' | 'detail'
  const [selectedId, setSelectedId]     = React.useState(null);
  const [drafts, setDrafts]             = React.useState([]);
  const [loading, setLoading]           = React.useState(true);
  const [listError, setListError]       = React.useState(null);
  const [statusFilter, setStatusFilter] = React.useState('');
  const [uploading, setUploading]       = React.useState(false);
  const [uploadError, setUploadError]   = React.useState(null);
  const fileRef = React.useRef(null);

  const loadList = React.useCallback(async () => {
    setLoading(true); setListError(null);
    const params = { limit: '100' };
    if (statusFilter) params.status = statusFilter;
    const r = await window.PzApi.listSupplierInvoiceDrafts(params);
    setLoading(false);
    if (!r.ok) { setListError(r.error); return; }
    setDrafts(r.data.drafts || []);
  }, [statusFilter]);

  React.useEffect(() => { if (view === 'list') loadList(); }, [view, loadList]);

  const doUpload = async () => {
    const input = fileRef.current;
    const file = input && input.files && input.files[0];
    if (!file) { setUploadError('Choose a PDF/PNG/JPG file first.'); return; }
    setUploading(true); setUploadError(null);
    const r = await window.PzApi.uploadSupplierInvoice(file);
    setUploading(false);
    if (input) input.value = '';
    if (!r.ok) {
      // 422/503 still persist the draft — refresh so the operator can see it.
      setUploadError(r.error);
      loadList();
      return;
    }
    const draftId = r.data && r.data.draft_id;
    if (draftId) { setSelectedId(draftId); setView('detail'); }
    else loadList();
  };

  if (view === 'detail' && selectedId != null) {
    return <SirDetailView draftId={selectedId} onBack={() => setView('list')} onChanged={loadList} />;
  }

  return (
    <div style={{ padding: '16px 32px 32px', display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0 }}>
      {/* Upload panel */}
      <Card style={{ padding: 14 }} data-testid="supplier-invoice-upload-panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <input ref={fileRef} type="file" accept=".pdf,.png,.jpg,.jpeg"
                 data-testid="supplier-invoice-upload-input"
                 style={{ fontSize: 12, color: 'var(--text-2)' }} />
          <Btn variant="gold" small disabled={uploading} onClick={doUpload} data-testid="supplier-invoice-upload-btn">
            {uploading ? 'Extracting…' : '⬆ Upload + Extract'}
          </Btn>
          <span style={{ fontSize: 10, color: 'var(--text-3)' }}>
            Foreign supplier invoice (PDF/PNG/JPG) → AI extraction draft. Nothing is booked — confirmed drafts are your reference for manual wFirma entry.
          </span>
        </div>
        {uploadError && (
          <div data-testid="supplier-invoice-upload-error" style={{ marginTop: 8, fontSize: 11, color: 'var(--badge-red-text)', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, padding: '6px 10px' }}>
            {uploadError}
          </div>
        )}
      </Card>

      {/* Drafts table */}
      <Card style={{ overflow: 'auto', flex: 1 }} data-testid="supplier-invoice-draft-list">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Extraction drafts</span>
          <div style={{ width: 170 }}>
            <Select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="pending_review">Pending review</option>
              <option value="confirmed">Confirmed</option>
              <option value="rejected">Rejected</option>
            </Select>
          </div>
          <div style={{ flex: 1 }} />
          <Btn variant="outline" small onClick={loadList} data-testid="supplier-invoice-reload">↻ Reload</Btn>
        </div>
        {listError && (
          <div style={{ padding: 14, fontSize: 11, color: 'var(--badge-red-text)' }} data-testid="supplier-invoice-list-error">{listError}</div>
        )}
        {loading && !listError && (
          <div style={{ padding: 14, fontSize: 12, color: 'var(--text-2)' }}>Loading…</div>
        )}
        {!loading && !listError && drafts.length === 0 && (
          <div style={{ padding: 14, fontSize: 12, color: 'var(--text-3)' }} data-testid="supplier-invoice-list-empty">
            No drafts yet — upload a supplier invoice above.
          </div>
        )}
        {!loading && !listError && drafts.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['#', 'File', 'Supplier', 'Invoice no.', 'Date', 'Total', 'Status', 'Uploaded', ''].map((h, i) => (
                  <th key={i} style={{ textAlign: 'left', fontSize: 10, fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.04em', padding: '6px 10px' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drafts.map(d => (
                <tr key={d.id} data-testid={`supplier-invoice-row-${d.id}`} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '6px 10px', color: 'var(--text-3)' }}>{d.id}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text)' }}>{d.source_filename}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text)' }}>{d.supplier_name || '—'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text)' }}>{d.invoice_number || '—'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{d.invoice_date || '—'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                    {d.total_amount != null ? `${d.total_amount} ${d.currency || ''}`.trim() : '—'}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    <SirStatusPill status={d.status} />
                    {Array.isArray(d.needs_review) && d.needs_review.length > 0 && d.status === 'pending_review' && (
                      <span title={d.needs_review.join(', ')} style={{ marginLeft: 6, fontSize: 10, color: 'var(--badge-amber-text)' }}>
                        ⚠ {d.needs_review.length}
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', color: 'var(--text-3)', fontSize: 10 }}>{(d.created_at || '').slice(0, 16).replace('T', ' ')}</td>
                  <td style={{ padding: '6px 10px' }}>
                    <Btn variant="outline" small data-testid={`supplier-invoice-review-${d.id}`}
                         onClick={() => { setSelectedId(d.id); setView('detail'); }}>Review</Btn>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

window.SupplierInvoiceReviewPage = SupplierInvoiceReviewPage;
