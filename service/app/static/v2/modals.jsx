// New Shipment Form Modal — V2 canonical.
//
// Wave 2 (EJ Dashboard Stabilization Sprint 1): the mock modal (hardcoded
// CLIENT_LIST / SUPPLIER_LIST, filename-only state, setTimeout fake save) is
// replaced by the proven B1 intake authority:
//   POST /api/v1/shipment/intake  (routes_intake.py — the ONLY shipment
//   creation path; drives packing/PZ/SAD/DHL/wFirma/proforma downstream).
// This React modal is another CLIENT of that authority — no business logic is
// reproduced in the browser. Contractor identity comes from real master data
// (Customer Master + Supplier Master). File payload + metadata blocks mirror
// the proven dashboard.html (V1) client so the backend contract is identical.
//
// Idempotency: a per-modal idempotency_key is sent on every attempt; a retry
// after failure reuses it, so the backend returns the ORIGINAL batch instead
// of creating a duplicate. No PZ number is assigned at intake (status=draft).

// Per-slot extension policy MIRRORS the backend allow-list in routes_intake.py
// (_ALLOWED_INVOICE_EXT / _PACKING_EXT / _SERVICE_EXT / _CARNET_EXT /
// _OTHER_EXT) — used as both the <input accept> and the client-side preflight.
const DOC_TYPES = [
  { id: 'purchase_invoice',       label: 'Purchase Invoice',       icon: '📄', hint: 'Commercial invoice from supplier (purchase price)',                multi: true,  needsClient: false, needsSupplier: true,  accept: '.pdf',                          allowedExts: ['.pdf'] },
  { id: 'sales_proforma',         label: 'Sales Proforma Invoice', icon: '📑', hint: 'Proforma issued to client — sales price · pre-acceptance',         multi: true,  needsClient: true,  needsSupplier: false, accept: '.pdf',                          allowedExts: ['.pdf'] },
  { id: 'sales_invoice',          label: 'Sales Invoice (Final)',  icon: '🧾', hint: 'Final commercial invoice issued to client',                         multi: true,  needsClient: true,  needsSupplier: false, accept: '.pdf',                          allowedExts: ['.pdf'] },
  { id: 'purchase_packing_list',  label: 'Purchase Packing List',  icon: '📋', hint: 'Items + purchase prices — flows to customs (CIF / SAD)',           multi: true,  needsClient: false, needsSupplier: true,  accept: '.pdf,.xlsx,.xls',               allowedExts: ['.pdf', '.xlsx', '.xls'] },
  { id: 'sales_packing_list',     label: 'Sales Packing List',     icon: '📋', hint: 'Same items + sales prices — flows to warehouse stock valuation',   multi: true,  needsClient: true,  needsSupplier: false, accept: '.pdf,.xlsx,.xls',               allowedExts: ['.pdf', '.xlsx', '.xls'] },
  { id: 'awb',                    label: 'AWB / Tracking PDF',     icon: '📎', hint: 'Air-waybill / tracking document',                                   multi: false, needsClient: false, needsSupplier: false, accept: '.pdf',                          allowedExts: ['.pdf'] },
  { id: 'service_invoice',        label: 'Service Invoice',        icon: '💼', hint: 'Shipping, insurance, customs-agent or handling invoice',           multi: true,  needsClient: false, needsSupplier: true,  accept: '.pdf,.xlsx,.xls',               allowedExts: ['.pdf', '.xlsx', '.xls'] },
  { id: 'carnet',                 label: 'ATA Carnet / Temp Doc',  icon: '🛂', hint: 'Temporary import / export document',                                multi: false, needsClient: false, needsSupplier: false, accept: '.pdf',                          allowedExts: ['.pdf'] },
  { id: 'other',                  label: 'Other Document',         icon: '📁', hint: 'Any supporting document',                                            multi: true,  needsClient: false, needsSupplier: false, accept: '.pdf,.xlsx,.xls,.jpg,.jpeg,.png', allowedExts: ['.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png'] },
];

// An idempotency token for one intake attempt. Regenerated whenever the
// payload (AWB / carrier / documents) changes, so a corrected retry is a NEW
// logical shipment while an unchanged retry reuses the key and dedupes.
function _newIdemKey() {
  try {
    if (window.crypto && window.crypto.randomUUID) return 'ns-' + window.crypto.randomUUID();
    if (window.crypto && window.crypto.getRandomValues) {
      const b = new Uint8Array(16); window.crypto.getRandomValues(b);
      return 'ns-' + Array.from(b).map(x => x.toString(16).padStart(2, '0')).join('');
    }
  } catch (e) { /* fall through */ }
  return 'ns-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10);
}

function NewShipmentModal({ onClose, onCreated }) {
  // step: 1=form, 2=uploading, 3=success
  const [step, setStep]     = React.useState(1);
  const [error, setError]   = React.useState('');
  const [warnings, setWarnings] = React.useState([]);

  // Shipment-level fields
  const [awbNo, setAwbNo]     = React.useState('');
  const [carrier, setCarrier] = React.useState('DHL');
  const [note, setNote]       = React.useState('');

  // Shipment-level party IDs (master-data backed; '' until selected)
  const [shipmentClientCid, setShipmentClientCid]     = React.useState('');
  const [shipmentSupplierCid, setShipmentSupplierCid] = React.useState('');

  // Duplicate-AWB advisory (Lesson N: advisory, never a hard block)
  const [dupAdvisory, setDupAdvisory] = React.useState(null); // null | array of matches
  const dupConfirmedRef = React.useRef(false);

  // DHL pre-check result (read-only readiness, run after a successful intake)
  const [precheckResult, setPrecheckResult] = React.useState(null);
  const [createdBatchId, setCreatedBatchId] = React.useState('');
  // True when the backend returned an existing batch (idempotent retry) rather
  // than creating a new one — surfaced so the operator is never misled.
  const [replayNotice, setReplayNotice] = React.useState(false);

  // Idempotency key for the CURRENT payload. Regenerated whenever the AWB,
  // carrier, or documents change so a corrected retry creates a fresh shipment
  // while an unchanged retry reuses the key and dedupes (no duplicate batch).
  const idemKeyRef = React.useRef(_newIdemKey());

  // Document slots (4 defaults)
  const _emptySlot = (typeId) => ({
    uid: 'd' + Math.random().toString(36).slice(2, 10),
    typeId, files: [], clientOverride: '', supplierOverride: '',
  });
  const [documents, setDocuments] = React.useState([
    _emptySlot('purchase_invoice'),
    _emptySlot('purchase_packing_list'),
    _emptySlot('sales_packing_list'),
    _emptySlot('awb'),
  ]);
  const addDocument    = (typeId) => setDocuments(prev => [...prev, _emptySlot(typeId)]);
  const removeDocument = (uid)    => setDocuments(prev => prev.filter(d => d.uid !== uid));
  const updateDoc      = (uid, patch) => setDocuments(prev => prev.map(d => d.uid === uid ? { ...d, ...patch } : d));

  // Payload changed → this is a new logical shipment attempt: fresh idempotency
  // key, and clear the duplicate-AWB confirmation latch (so a second changed
  // duplicate is re-checked, not waved through).
  React.useEffect(() => {
    idemKeyRef.current = _newIdemKey();
    dupConfirmedRef.current = false;
  }, [awbNo, carrier, documents]);

  // ── Master-data dropdown sources (real backend; no hardcodes) ─────────
  const [clientList,   setClientList]   = React.useState([]);
  const [supplierList, setSupplierList] = React.useState([]);
  const [masterLoadError, setMasterLoadError] = React.useState('');

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const [cRes, sRes] = await Promise.all([
        window.PzApi.listCustomerMaster({ limit: 500 }),
        window.PzApi.listSuppliers({ limit: 500 }),
      ]);
      if (cancelled) return;
      if (cRes && cRes.ok) {
        const d = cRes.data;
        const arr = Array.isArray(d) ? d : (d && d.customers) || [];
        setClientList(arr.map(c => ({
          contractor_id: c.bill_to_contractor_id || c.id || '',
          name:          c.bill_to_name || c.name || '',
          country:       c.country || '',
          vat_id:        c.nip || c.vat_eu_number || '',
        })).filter(x => x.contractor_id && x.name));
      } else if (cRes && cRes.error) {
        setMasterLoadError(cRes.error);
      }
      if (sRes && sRes.ok) {
        const d = sRes.data;
        const arr = Array.isArray(d) ? d : (d && d.suppliers) || [];
        setSupplierList(arr.map(s => ({
          contractor_id: s.id != null ? String(s.id) : (s.supplier_code || ''),
          name:          s.name || '',
          country:       s.country || '',
          vat_id:        s.vat_id || '',
        })).filter(x => x.contractor_id && x.name));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const hasMasterClients   = clientList.length > 0;
  const hasMasterSuppliers = supplierList.length > 0;

  const totalFiles    = documents.reduce((sum, d) => sum + d.files.length, 0);
  const hasAnyInvoice = documents.some(d => d.typeId === 'purchase_invoice' && d.files.length > 0);
  const saveDisabled  = !awbNo.trim() || !hasAnyInvoice;

  // ── Duplicate-AWB advisory lookup (frontend, read-only) ───────────────
  const _findDuplicates = async (awb) => {
    try {
      const res = await window.PzApi.listBatches();
      if (!res || !res.ok || !Array.isArray(res.data)) {
        // Advisory is best-effort (Lesson N: never a hard block). If the batch
        // list can't be read, proceed — but log so the skipped check is visible.
        console.warn('[new-shipment] duplicate-AWB check skipped:', res && res.error);
        return [];
      }
      const norm = awb.replace(/\s+/g, '').toLowerCase();
      return res.data.filter(r => String(r.tracking_no || '').replace(/\s+/g, '').toLowerCase() === norm);
    } catch (e) {
      console.warn('[new-shipment] duplicate-AWB check failed:', e && e.message);
      return [];
    }
  };

  // ── Submit: flatten slots into the /shipment/intake payload ───────────
  const handleSubmit = async (runPrecheck) => {
    if (!awbNo.trim())  { setError('AWB / Tracking number is required.'); return; }
    if (!hasAnyInvoice) { setError('At least one Purchase Invoice file is required.'); return; }

    // Advisory duplicate-AWB check (not a hard block). Second click confirms.
    if (!dupConfirmedRef.current) {
      const dupes = await _findDuplicates(awbNo.trim());
      if (dupes.length > 0) { setDupAdvisory(dupes); setError(''); return; }
    }

    setStep(2); setError(''); setWarnings([]); setPrecheckResult(null);
    try {
      const fd = new FormData();
      fd.append('tracking_no', awbNo.trim());
      fd.append('carrier', carrier);
      fd.append('idempotency_key', idemKeyRef.current);

      const purchaseSlots     = documents.filter(d => d.typeId === 'purchase_invoice');
      const purchasePackSlots = documents.filter(d => d.typeId === 'purchase_packing_list');
      const salesDocSlots     = documents.filter(d => d.typeId === 'sales_invoice' || d.typeId === 'sales_proforma');
      const salesPackSlots    = documents.filter(d => d.typeId === 'sales_packing_list');
      const awbSlot           = documents.find(d => d.typeId === 'awb');

      if (awbSlot && awbSlot.files.length > 0) fd.append('awb', awbSlot.files[0]);

      // purchase_blocks: pair purchase packing slot i with purchase invoice slot i.
      const purchaseMeta = [];
      let invIdx = 0, packIdx = 0;
      purchaseSlots.forEach((slot, sIdx) => {
        slot.files.forEach(f => fd.append('invoices', f));
        const pairedPack = purchasePackSlots[sIdx];
        purchaseMeta.push({
          invoice_index:          invIdx,
          packing_index:          (pairedPack && pairedPack.files.length > 0) ? packIdx : -1,
          supplier_name:          '',
          supplier_contractor_id: (slot.supplierOverride || shipmentSupplierCid || '').trim(),
        });
        if (pairedPack && pairedPack.files.length > 0) {
          pairedPack.files.forEach(f => fd.append('packing_lists', f));
          packIdx += pairedPack.files.length;
        }
        invIdx += slot.files.length;
      });
      // Extra purchase packing slots beyond the invoice slots — keep the files.
      for (let i = purchaseSlots.length; i < purchasePackSlots.length; i++) {
        purchasePackSlots[i].files.forEach(f => fd.append('packing_lists', f));
      }

      // sales_blocks: pair sales packing slot i with sales doc slot i.
      const salesMeta = [];
      let sDocIdx = 0, sPackIdx = 0;
      salesDocSlots.forEach((slot, sIdx) => {
        slot.files.forEach(f => fd.append('sales_documents', f));
        const pairedPack = salesPackSlots[sIdx];
        salesMeta.push({
          document_index:       sDocIdx,
          packing_index:        (pairedPack && pairedPack.files.length > 0) ? sPackIdx : -1,
          client_name:          '',
          client_ref:           '',
          client_contractor_id: (slot.clientOverride || shipmentClientCid || '').trim(),
        });
        if (pairedPack && pairedPack.files.length > 0) {
          pairedPack.files.forEach(f => fd.append('sales_packing_lists', f));
          sPackIdx += pairedPack.files.length;
        }
        sDocIdx += slot.files.length;
      });
      // Sales packing slots without a paired sales doc — keep client_contractor_id.
      for (let i = salesDocSlots.length; i < salesPackSlots.length; i++) {
        const extraPack = salesPackSlots[i];
        if (extraPack.files.length > 0) {
          extraPack.files.forEach(f => fd.append('sales_packing_lists', f));
          salesMeta.push({
            document_index:       -1,
            packing_index:        sPackIdx,
            client_name:          '',
            client_ref:           '',
            client_contractor_id: (extraPack.clientOverride || shipmentClientCid || '').trim(),
          });
          sPackIdx += extraPack.files.length;
        }
      }

      // Local-only Atlas types (service_invoice / carnet / other).
      const serviceMeta = [], carnetMeta = [], otherMeta = [];
      documents.filter(d => d.typeId === 'service_invoice').forEach(slot => {
        slot.files.forEach(f => { fd.append('service_invoices', f); serviceMeta.push({ supplier_contractor_id: (slot.supplierOverride || shipmentSupplierCid || '').trim(), client_contractor_id: '' }); });
      });
      documents.filter(d => d.typeId === 'carnet').forEach(slot => {
        slot.files.forEach(f => { fd.append('carnet_docs', f); carnetMeta.push({ supplier_contractor_id: (slot.supplierOverride || shipmentSupplierCid || '').trim(), client_contractor_id: (slot.clientOverride || shipmentClientCid || '').trim() }); });
      });
      documents.filter(d => d.typeId === 'other').forEach(slot => {
        slot.files.forEach(f => { fd.append('other_docs', f); otherMeta.push({ supplier_contractor_id: (slot.supplierOverride || shipmentSupplierCid || '').trim(), client_contractor_id: (slot.clientOverride || shipmentClientCid || '').trim() }); });
      });

      fd.append('metadata', JSON.stringify({
        purchase_blocks: purchaseMeta,
        sales_blocks:    salesMeta,
        service_blocks:  serviceMeta,
        carnet_blocks:   carnetMeta,
        other_blocks:    otherMeta,
        note:            note.trim(),
      }));

      const res = await window.PzApi.intakeShipment(fd);
      if (!res.ok) {
        setStep(1);
        setError(res.error || 'Intake failed. Check the server and retry — a retry will not create a duplicate.');
        return;
      }
      const data = res.data || {};
      const batchId = data.batch_id || '';
      setCreatedBatchId(batchId);
      setReplayNotice(data.idempotent_replay === true);
      setWarnings(Array.isArray(data.warnings) ? data.warnings : []);

      // Optional read-only DHL pre-check (no mutation).
      if (runPrecheck && batchId) {
        const pc = await window.PzApi.getDhlReadiness(batchId);
        setPrecheckResult(pc && pc.ok ? pc.data : { error: (pc && pc.error) || 'pre-check unavailable' });
      }

      // Show the summary and let the OPERATOR open the detail — no auto-close
      // timer (which could fire after a manual dismiss and hide the pre-check).
      setStep(3);
    } catch (e) {
      setStep(1);
      setError((e && e.message) || 'Intake failed. Check the server.');
    }
  };

  const confirmDupAndSubmit = (runPrecheck) => {
    dupConfirmedRef.current = true;
    setDupAdvisory(null);
    handleSubmit(runPrecheck);
  };

  return (
    <Modal title="New Shipment" onClose={onClose} wide>
      {step === 1 && (
        <>
          {error && (
            <div data-testid="new-shipment-error" style={{ marginBottom: 14, padding: '10px 14px', borderRadius: 6, background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', fontSize: 12, color: 'var(--badge-red-text)' }}>{error}</div>
          )}
          {masterLoadError && (
            <div data-testid="new-shipment-master-error" style={{ marginBottom: 14, padding: '10px 14px', borderRadius: 6, background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', fontSize: 12, color: 'var(--badge-amber-text)' }}>
              Master data could not load ({masterLoadError}). You can still create the shipment; contractor identity will be blank until the masters are reachable.
            </div>
          )}
          {dupAdvisory && (
            <div data-testid="new-shipment-dup-advisory" style={{ marginBottom: 14, padding: '10px 14px', borderRadius: 6, background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', fontSize: 12, color: 'var(--badge-amber-text)' }}>
              <strong>Advisory — AWB already used.</strong> {dupAdvisory.length} existing shipment{dupAdvisory.length === 1 ? '' : 's'} carry this tracking number
              ({dupAdvisory.slice(0, 3).map(d => d.batch_id).join(', ')}{dupAdvisory.length > 3 ? '…' : ''}). This is not blocked — confirm to create another.
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <Btn variant="outline" small onClick={() => setDupAdvisory(null)} data-testid="new-shipment-dup-cancel">Cancel</Btn>
                <Btn variant="gold" small onClick={() => confirmDupAndSubmit(false)} data-testid="new-shipment-dup-confirm">Create anyway</Btn>
              </div>
            </div>
          )}

          {/* Row 1: AWB + Carrier */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <FormField label="AWB / Tracking Number" hint="Required">
              <Input value={awbNo} onChange={e => setAwbNo(e.target.value)} placeholder="e.g. 1234567890" data-testid="new-shipment-awb" />
            </FormField>
            <FormField label="Carrier">
              <Select value={carrier} onChange={e => setCarrier(e.target.value)} data-testid="new-shipment-carrier">
                <option>DHL</option>
                <option>FedEx</option>
                <option>Other</option>
              </Select>
            </FormField>
          </div>

          {/* Row 2: Shipment-level Client + Supplier */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 8 }}>
            <FormField label="Client (Sales)" hint={hasMasterClients ? 'Buyer / importer — default for sales documents' : 'Master data empty'}>
              <Select value={shipmentClientCid} onChange={e => setShipmentClientCid(e.target.value)} data-testid="new-shipment-client-select">
                <option value="">— select client —</option>
                {clientList.map(c => <option key={c.contractor_id} value={c.contractor_id}>{c.name}{c.country ? ` (${c.country})` : ''}</option>)}
              </Select>
            </FormField>
            <FormField label="Supplier (Purchase)" hint={hasMasterSuppliers ? 'Exporter — default for purchase documents' : 'Master data empty'}>
              <Select value={shipmentSupplierCid} onChange={e => setShipmentSupplierCid(e.target.value)} data-testid="new-shipment-supplier-select">
                <option value="">— select supplier —</option>
                {supplierList.map(s => <option key={s.contractor_id} value={s.contractor_id}>{s.name}{s.country ? ` (${s.country})` : ''}</option>)}
              </Select>
            </FormField>
          </div>

          {/* Documents section */}
          <div style={{ marginTop: 8, marginBottom: 8, paddingTop: 16, borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Documents</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{documents.length} slot{documents.length === 1 ? '' : 's'} · {totalFiles} file{totalFiles === 1 ? '' : 's'} attached</div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {documents.map(doc => (
              <DocumentSlot key={doc.uid} doc={doc} onUpdate={(patch) => updateDoc(doc.uid, patch)} onRemove={() => removeDocument(doc.uid)} clientList={clientList} supplierList={supplierList} defaultClientCid={shipmentClientCid} defaultSupplierCid={shipmentSupplierCid} />
            ))}
          </div>

          {/* Add-more row */}
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600 }}>+ Add another:</span>
            {DOC_TYPES.map(t => (
              <button key={t.id} data-testid={`new-shipment-add-${t.id}`} onClick={() => addDocument(t.id)} style={{ padding: '5px 10px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 11, fontWeight: 600, color: 'var(--text-2)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <span style={{ fontSize: 13 }}>{t.icon}</span>{t.label}
              </button>
            ))}
          </div>

          <div style={{ marginTop: 14, padding: '10px 12px', borderRadius: 6, background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)', fontSize: 11, color: 'var(--badge-blue-text)', lineHeight: 1.5 }}>
            ℹ <strong>Purchase ↔ Sales packing lists</strong> may share identical items and quantities — only prices differ. They are kept as <strong>separate document identities</strong>: purchase values flow to customs (CIF / SAD); sales values flow to warehouse stock valuation. Each slot can override its own client / supplier.
          </div>

          <FormField label="Optional Note">
            <textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Any notes about this shipment…" rows={2} data-testid="new-shipment-note" style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)', background: 'var(--bg-subtle)', outline: 'none', resize: 'vertical', boxSizing: 'border-box', fontFamily: 'inherit' }} />
          </FormField>

          <div style={{ marginTop: 4, padding: '12px 14px', borderRadius: 6, background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', fontSize: 11, color: 'var(--badge-amber-text)' }}>
            ℹ PZ number is assigned at the end of the workflow — not at intake. SAD is not required at this stage.
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <Btn variant="outline" onClick={onClose} data-testid="new-shipment-cancel">Cancel</Btn>
            <Btn variant="outline" onClick={() => handleSubmit(false)} disabled={saveDisabled} title={saveDisabled ? 'AWB + at least one Purchase Invoice required' : 'Create the real shipment draft'} data-testid="new-shipment-save">Save Draft</Btn>
            <Btn variant="gold" onClick={() => handleSubmit(true)} disabled={saveDisabled} title={saveDisabled ? 'AWB + at least one Purchase Invoice required' : 'Create the draft, then run a read-only DHL readiness pre-check'} data-testid="new-shipment-save-precheck">Save &amp; Run DHL Pre-check</Btn>
          </div>
        </>
      )}

      {step === 2 && (
        <div style={{ padding: '40px 0', textAlign: 'center' }} data-testid="new-shipment-uploading">
          <div style={{ fontSize: 36, marginBottom: 12, animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Creating shipment…</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>Uploading files to the intake authority</div>
          <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {step === 3 && (
        <div style={{ padding: '32px 8px', textAlign: 'center' }} data-testid="new-shipment-success">
          <div style={{ fontSize: 36, marginBottom: 12 }}>✅</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--badge-green-text)' }}>{replayNotice ? 'Existing draft returned' : 'Shipment draft created'}</div>
          {createdBatchId && <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4, fontFamily: 'monospace' }}>{createdBatchId}</div>}
          {replayNotice && (
            <div data-testid="new-shipment-replay" style={{ marginTop: 14, textAlign: 'left', padding: '10px 12px', borderRadius: 6, background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', fontSize: 11, color: 'var(--badge-amber-text)' }}>
              This idempotency key already created a shipment — the <strong>existing</strong> draft above is being opened (no duplicate was created). If you intended a new shipment, change the AWB or files and try again.
            </div>
          )}
          {warnings.length > 0 && (
            <div data-testid="new-shipment-warnings" style={{ marginTop: 14, textAlign: 'left', padding: '10px 12px', borderRadius: 6, background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', fontSize: 11, color: 'var(--badge-amber-text)' }}>
              <strong>Created with {warnings.length} advisory warning{warnings.length === 1 ? '' : 's'}:</strong>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{warnings.map((w, i) => <li key={i}>{typeof w === 'string' ? w : JSON.stringify(w)}</li>)}</ul>
            </div>
          )}
          {precheckResult && (
            <div data-testid="new-shipment-precheck" style={{ marginTop: 14, textAlign: 'left', padding: '10px 12px', borderRadius: 6, background: 'var(--bg-subtle)', border: '1px solid var(--border)', fontSize: 11, color: 'var(--text-2)' }}>
              <strong>DHL pre-check:</strong>{' '}
              {precheckResult.error
                ? <span style={{ color: 'var(--badge-red-text)' }}>{precheckResult.error}</span>
                : <span>{precheckResult.dhl_status || 'checked'}{precheckResult.next_required_action ? ` — next: ${precheckResult.next_required_action}` : ''}{Array.isArray(precheckResult.missing_documents) && precheckResult.missing_documents.length ? ` · missing: ${precheckResult.missing_documents.join(', ')}` : ''}</span>}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
            <Btn variant="outline" onClick={onClose} data-testid="new-shipment-success-close">Close</Btn>
            <Btn variant="gold" onClick={() => onCreated({ awb: awbNo, carrier, batchId: createdBatchId })} disabled={!createdBatchId} data-testid="new-shipment-open-detail">Open Shipment Detail →</Btn>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Single document slot row ──────────────────────────────────────────────
function DocumentSlot({ doc, onUpdate, onRemove, clientList, supplierList, defaultClientCid, defaultSupplierCid }) {
  const type = DOC_TYPES.find(t => t.id === doc.typeId) || DOC_TYPES[DOC_TYPES.length - 1];
  const [showOverride, setShowOverride] = React.useState(false);
  const [slotError, setSlotError] = React.useState('');
  const fileInputRef = React.useRef(null);

  const handleFiles = e => {
    const incoming = Array.from(e.target.files || []);
    // Preflight against the slot's allow-list BEFORE state (mirror backend).
    const allowed = (type.allowedExts || ['.pdf']).map(s => s.toLowerCase());
    const accepted = [], rejected = [];
    incoming.forEach(f => {
      const dot = f.name.lastIndexOf('.');
      const ext = (dot >= 0 ? f.name.slice(dot) : '').toLowerCase();
      if (allowed.indexOf(ext) >= 0) accepted.push(f); else rejected.push(f.name);
    });
    setSlotError(rejected.length ? `Rejected ${rejected.length} file(s) of unsupported type. Allowed: ${allowed.join(', ')}` : '');
    if (accepted.length > 0) onUpdate({ files: type.multi ? [...doc.files, ...accepted] : accepted.slice(0, 1) });
    if (fileInputRef.current) fileInputRef.current.value = '';
  };
  const removeFile = (idx) => onUpdate({ files: doc.files.filter((_, i) => i !== idx) });

  return (
    <div data-testid={`new-shipment-slot-${doc.uid}`} data-doctype={type.id} style={{ border: '1px solid var(--border)', borderRadius: 6, background: 'var(--card)', overflow: 'hidden' }}>
      {/* Slot header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
        <span style={{ fontSize: 16 }}>{type.icon}</span>
        <Select value={doc.typeId} onChange={e => onUpdate({ typeId: e.target.value })} style={{ width: 220, padding: '4px 8px', fontSize: 12 }}>
          {DOC_TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
        </Select>
        <span style={{ fontSize: 11, color: 'var(--text-3)', flex: 1 }}>{type.hint}</span>
        {(type.needsClient || type.needsSupplier) && (
          <button data-testid={`new-shipment-slot-override-toggle-${doc.uid}`} onClick={() => setShowOverride(s => !s)} style={{ padding: '3px 8px', background: showOverride ? 'var(--accent)' : 'transparent', border: '1px solid ' + (showOverride ? 'var(--accent)' : 'var(--border)'), borderRadius: 4, fontSize: 10, fontWeight: 600, color: showOverride ? '#fff' : 'var(--text-3)', cursor: 'pointer' }}>
            {type.needsClient ? 'Client' : 'Supplier'} {showOverride ? '✓' : '↓'}
          </button>
        )}
        <button data-testid={`new-shipment-slot-remove-${doc.uid}`} onClick={onRemove} style={{ width: 24, height: 24, borderRadius: 4, background: 'transparent', border: '1px solid var(--border)', cursor: 'pointer', color: 'var(--text-3)', fontSize: 14, lineHeight: 1 }} title="Remove this document slot">×</button>
      </div>

      {/* Per-document override */}
      {showOverride && (type.needsClient || type.needsSupplier) && (
        <div style={{ padding: '10px 12px', display: 'grid', gridTemplateColumns: type.needsClient && type.needsSupplier ? '1fr 1fr' : '1fr', gap: 10, background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border-subtle)' }}>
          {type.needsClient && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Client for this document</div>
              <Select data-testid={`new-shipment-slot-client-override-${doc.uid}`} value={doc.clientOverride || ''} onChange={e => onUpdate({ clientOverride: e.target.value })}>
                <option value="">— inherit shipment-level —</option>
                {clientList.map(c => <option key={c.contractor_id} value={c.contractor_id}>{c.name}{c.country ? ` (${c.country})` : ''}</option>)}
              </Select>
            </div>
          )}
          {type.needsSupplier && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Supplier for this document</div>
              <Select data-testid={`new-shipment-slot-supplier-override-${doc.uid}`} value={doc.supplierOverride || ''} onChange={e => onUpdate({ supplierOverride: e.target.value })}>
                <option value="">— inherit shipment-level —</option>
                {supplierList.map(s => <option key={s.contractor_id} value={s.contractor_id}>{s.name}{s.country ? ` (${s.country})` : ''}</option>)}
              </Select>
            </div>
          )}
        </div>
      )}

      {slotError && (
        <div data-testid={`new-shipment-slot-error-${doc.uid}`} style={{ padding: '6px 12px', fontSize: 11, color: 'var(--badge-red-text)', background: 'var(--badge-red-bg)', borderBottom: '1px solid var(--border-subtle)' }}>{slotError}</div>
      )}

      {/* Drop area */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', cursor: 'pointer', background: doc.files.length ? 'transparent' : 'var(--bg-subtle)', borderTop: doc.files.length ? '1px dashed var(--border)' : 'none' }}>
        <input ref={fileInputRef} type="file" accept={type.accept} multiple={type.multi} onChange={handleFiles} style={{ display: 'none' }} data-testid={`new-shipment-slot-input-${doc.uid}`} data-doctype={type.id} />
        <span style={{ fontSize: 18, color: 'var(--text-3)' }}>+</span>
        <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
          {doc.files.length === 0 ? `Click to upload ${type.label.toLowerCase()}${type.multi ? ' (multiple allowed)' : ''}` : type.multi ? 'Click to add more files' : 'Click to replace file'}
        </span>
      </label>

      {/* Files list (real File objects) */}
      {doc.files.length > 0 && (
        <div style={{ padding: '6px 12px 10px' }}>
          {doc.files.map((f, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 4, background: 'var(--bg-subtle)', marginTop: 4 }}>
              <span style={{ fontSize: 12 }}>📄</span>
              <span style={{ flex: 1, fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}>{f.name}</span>
              <span style={{ fontSize: 10, color: 'var(--text-3)' }}>{f.size != null ? (f.size / 1024).toFixed(0) + ' KB' : ''}</span>
              <button data-testid={`new-shipment-file-remove-${doc.uid}-${i}`} onClick={() => removeFile(i)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-3)', fontSize: 14 }}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── API Wiring Checklist Modal — reflects the REAL endpoints this UI calls.
const API_ITEMS = [
  { action: 'Create shipment (intake)', endpoint: 'POST /api/v1/shipment/intake',        exists: true, auth: true, status: 'Live' },
  { action: 'Client search',            endpoint: 'GET /api/v1/customer-master',          exists: true, auth: true, status: 'Live' },
  { action: 'Supplier search',          endpoint: 'GET /api/v1/suppliers',                exists: true, auth: true, status: 'Live' },
  { action: 'Duplicate-AWB advisory',   endpoint: 'GET /api/v1/dashboard/batches',        exists: true, auth: true, status: 'Live' },
  { action: 'DHL pre-check (readiness)', endpoint: 'GET /api/v1/dhl/readiness/:batch',     exists: true, auth: true, status: 'Live' },
];

function ApiChecklistModal({ onClose }) {
  return (
    <Modal title="API Wiring Checklist" onClose={onClose} wide>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ background: 'var(--bg-subtle)' }}>
            {['Action', 'Endpoint', 'Exists', 'Auth', 'Status'].map(h => (
              <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {API_ITEMS.map(r => (
            <tr key={r.action} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <td style={{ padding: '10px 12px', fontWeight: 600, color: 'var(--text)' }}>{r.action}</td>
              <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)' }}>{r.endpoint}</td>
              <td style={{ padding: '10px 12px', color: r.exists ? 'var(--badge-green-text)' : 'var(--badge-red-text)' }}>{r.exists ? '✓' : '✗'}</td>
              <td style={{ padding: '10px 12px', color: r.auth ? 'var(--badge-green-text)' : 'var(--badge-red-text)' }}>{r.auth ? '✓' : '✗'}</td>
              <td style={{ padding: '10px 12px', color: 'var(--badge-green-text)', fontWeight: 600 }}>{r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}

Object.assign(window, { NewShipmentModal, ApiChecklistModal, DOC_TYPES });
