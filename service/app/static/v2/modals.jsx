// New Shipment Form Modal

const CLIENT_LIST = [
  { id: 'EJ-PL',   name: 'Estrella Jewels Sp. z o.o. (PL)',  type: 'Importer' },
  { id: 'GS-UK',   name: 'Goldsmith & Co. (UK)',              type: 'Buyer' },
  { id: 'MA-FR',   name: 'Maison Aurélie (FR)',               type: 'Buyer' },
  { id: 'EBW-PL',  name: 'Estrella Boutique Warsaw',          type: 'Buyer' },
  { id: 'DT-AE',   name: 'Diamond Trade DMCC (AE)',           type: 'Buyer' },
  { id: 'BL-BE',   name: 'Bijoux Lumière (BE)',               type: 'Buyer' },
];

const SUPPLIER_LIST = [
  { id: 'BON-IT',  name: 'Bonacchi Atelier (IT)',     country: 'IT' },
  { id: 'VIC-IT',  name: 'Maison de Vicenza (IT)',    country: 'IT' },
  { id: 'ANT-BE',  name: 'Antwerp Stones (BE)',       country: 'BE' },
  { id: 'GEN-CH',  name: 'Geneva Goldworks (CH)',     country: 'CH' },
  { id: 'PAR-FR',  name: 'Paris Diamonds (FR)',       country: 'FR' },
];

// ── Multi-document uploader: any number of named slots that the operator can add
const DOC_TYPES = [
  { id: 'purchase_invoice',  label: 'Purchase Invoice',         icon: '📄', hint: 'Commercial invoice from supplier (purchase price)',                multi: true,  needsClient: false, needsSupplier: true  },
  { id: 'sales_proforma',    label: 'Sales Proforma Invoice',   icon: '📑', hint: 'Proforma issued to client — sales price · pre-acceptance',         multi: true,  needsClient: true,  needsSupplier: false },
  { id: 'sales_invoice',     label: 'Sales Invoice (Final)',    icon: '🧾', hint: 'Final commercial invoice issued to client',                         multi: true,  needsClient: true,  needsSupplier: false },
  { id: 'purchase_packing',  label: 'Purchase Packing List',    icon: '📋', hint: 'Items + purchase prices — flows to customs (CIF / SAD)',           multi: true,  needsClient: false, needsSupplier: true  },
  { id: 'sales_packing',     label: 'Sales Packing List',       icon: '📋', hint: 'Same items + sales prices — flows to warehouse stock valuation',   multi: true,  needsClient: true,  needsSupplier: false },
  { id: 'awb',               label: 'AWB / Tracking PDF',       icon: '📎', hint: 'Air-waybill / tracking document',                                   multi: false, needsClient: false, needsSupplier: false },
  { id: 'service_invoice',   label: 'Service Invoice',          icon: '💼', hint: 'Shipping, insurance, customs-agent or handling invoice',           multi: true,  needsClient: false, needsSupplier: true  },
  { id: 'carnet',            label: 'ATA Carnet / Temp Doc',    icon: '🛂', hint: 'Temporary import / export document',                                multi: false, needsClient: false, needsSupplier: false },
  { id: 'other',             label: 'Other Document',           icon: '📁', hint: 'Any supporting document',                                            multi: true,  needsClient: false, needsSupplier: false },
];

function NewShipmentModal({ onClose, onCreated }) {
  const [awb, setAwb] = React.useState('');
  const [carrier, setCarrier] = React.useState('DHL');
  const [client, setClient] = React.useState(CLIENT_LIST[0].id);
  const [supplier, setSupplier] = React.useState(SUPPLIER_LIST[0].id);
  const [note, setNote] = React.useState('');
  const [step, setStep] = React.useState(1);

  // documents: array of { uid, typeId, files: [name], clientOverride?, supplierOverride? }
  const [documents, setDocuments] = React.useState([
    { uid: 'd1', typeId: 'purchase_invoice', files: [] },
    { uid: 'd2', typeId: 'purchase_packing', files: [] },
    { uid: 'd3', typeId: 'sales_packing',    files: [] },
    { uid: 'd4', typeId: 'awb',              files: [] },
  ]);

  const addDocument = (typeId = 'other') => {
    setDocuments(prev => [...prev, { uid: 'd' + Date.now() + Math.random().toString(36).slice(2, 5), typeId, files: [] }]);
  };
  const removeDocument = (uid) => setDocuments(prev => prev.filter(d => d.uid !== uid));
  const updateDoc = (uid, patch) => setDocuments(prev => prev.map(d => d.uid === uid ? { ...d, ...patch } : d));

  const handleSave = (runPrecheck) => {
    if (!awb.trim()) return;
    setStep(2);
    setTimeout(() => {
      setStep(3);
      setTimeout(() => { onCreated({ awb, carrier, runPrecheck }); }, 800);
    }, 1400);
  };

  const totalFiles = documents.reduce((sum, d) => sum + d.files.length, 0);

  return (
    <Modal title="New Shipment" onClose={onClose} wide>
      {step === 1 && (
        <>
          {/* ── Header fields */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <FormField label="AWB / Tracking Number" hint="Required">
              <Input value={awb} onChange={e => setAwb(e.target.value)} placeholder="e.g. DHL-1234567890" />
            </FormField>
            <FormField label="Carrier">
              <Select value={carrier} onChange={e => setCarrier(e.target.value)}>
                <option>DHL</option>
                <option>FedEx</option>
                <option>UPS</option>
                <option>Other</option>
              </Select>
            </FormField>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <FormField label="Client (Sales)" hint="Buyer / importer — used for sales documents">
              <Select value={client} onChange={e => setClient(e.target.value)}>
                {CLIENT_LIST.map(c => <option key={c.id} value={c.id}>{c.name} — {c.type}</option>)}
                <option value="__new">+ Add new client to master…</option>
              </Select>
            </FormField>
            <FormField label="Supplier (Purchase)" hint="Exporter — used for purchase invoice / packing list">
              <Select value={supplier} onChange={e => setSupplier(e.target.value)}>
                {SUPPLIER_LIST.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                <option value="__new">+ Add new supplier to master…</option>
              </Select>
            </FormField>
          </div>

          {/* ── Documents section */}
          <div style={{
            marginTop: 8, marginBottom: 8, paddingTop: 16, borderTop: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Documents</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                {documents.length} slot{documents.length === 1 ? '' : 's'} · {totalFiles} file{totalFiles === 1 ? '' : 's'} attached
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {documents.map(doc => (
              <DocumentSlot
                key={doc.uid}
                doc={doc}
                onUpdate={(patch) => updateDoc(doc.uid, patch)}
                onRemove={() => removeDocument(doc.uid)}
                clientList={CLIENT_LIST}
                supplierList={SUPPLIER_LIST}
                defaultClient={client}
                defaultSupplier={supplier}
              />
            ))}
          </div>

          {/* Add-more dropdown row */}
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600 }}>+ Add another:</span>
            {DOC_TYPES.map(t => (
              <button key={t.id} onClick={() => addDocument(t.id)} style={{
                padding: '5px 10px', background: 'var(--bg-subtle)',
                border: '1px solid var(--border)', borderRadius: 4,
                fontSize: 11, fontWeight: 600, color: 'var(--text-2)', cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 4,
              }} onMouseEnter={e => { e.currentTarget.style.background = 'var(--card)'; e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--text)'; }}
                 onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-subtle)'; e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-2)'; }}>
                <span style={{ fontSize: 13 }}>{t.icon}</span>{t.label}
              </button>
            ))}
          </div>

          <div style={{
            marginTop: 14, padding: '10px 12px', borderRadius: 6,
            background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)',
            fontSize: 11, color: 'var(--badge-blue-text)', lineHeight: 1.5,
          }}>
            ℹ <strong>Purchase ↔ Sales packing lists</strong> share identical line items and quantities — only prices differ. Sales prices flow to warehouse stock valuation; purchase prices flow to customs (CIF / SAD). Each document slot can override its own client / supplier if it differs from the shipment-level defaults above.
          </div>

          <FormField label="Optional Note">
            <textarea
              value={note} onChange={e => setNote(e.target.value)}
              placeholder="Any notes about this shipment…"
              rows={2}
              style={{
                width: '100%', padding: '8px 10px', borderRadius: 6,
                border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)',
                background: 'var(--bg-subtle)', outline: 'none', resize: 'vertical',
                boxSizing: 'border-box', fontFamily: 'inherit',
              }}
            />
          </FormField>

          <div style={{
            marginTop: 4, padding: '12px 14px', borderRadius: 6,
            background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
            fontSize: 11, color: '#8A5A00',
          }}>
            ℹ PZ number will be assigned at the end of the workflow. SAD is not required at this stage.
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <Btn variant="outline" onClick={onClose}>Cancel</Btn>
            <Btn variant="outline" onClick={() => handleSave(false)} disabled={!awb.trim()}>Save Draft</Btn>
            <Btn variant="gold" onClick={() => handleSave(true)} disabled={!awb.trim()}>Save &amp; Run DHL Pre-check</Btn>
          </div>
        </>
      )}

      {step === 2 && (
        <div style={{ padding: '40px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 36, marginBottom: 12, animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Creating shipment…</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>Uploading files and running pre-check</div>
          <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {step === 3 && (
        <div style={{ padding: '40px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>✅</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--badge-green-text)' }}>Shipment created!</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>Redirecting to shipment detail…</div>
        </div>
      )}
    </Modal>
  );
}

// ── Single document slot row
function DocumentSlot({ doc, onUpdate, onRemove, clientList, supplierList, defaultClient, defaultSupplier }) {
  const type = DOC_TYPES.find(t => t.id === doc.typeId) || DOC_TYPES[DOC_TYPES.length - 1];
  const [showOverride, setShowOverride] = React.useState(false);

  const handleFiles = e => {
    const names = Array.from(e.target.files).map(f => f.name);
    onUpdate({ files: type.multi ? [...doc.files, ...names] : names.slice(0, 1) });
  };
  const removeFile = (idx) => onUpdate({ files: doc.files.filter((_, i) => i !== idx) });

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 6,
      background: 'var(--card)', overflow: 'hidden',
    }}>
      {/* Slot header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
        <span style={{ fontSize: 16 }}>{type.icon}</span>
        <Select value={doc.typeId} onChange={e => onUpdate({ typeId: e.target.value })} style={{ width: 220, padding: '4px 8px', fontSize: 12 }}>
          {DOC_TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
        </Select>
        <span style={{ fontSize: 11, color: 'var(--text-3)', flex: 1 }}>{type.hint}</span>
        {(type.needsClient || type.needsSupplier) && (
          <button onClick={() => setShowOverride(s => !s)} style={{
            padding: '3px 8px', background: showOverride ? 'var(--accent)' : 'transparent',
            border: '1px solid ' + (showOverride ? 'var(--accent)' : 'var(--border)'),
            borderRadius: 4, fontSize: 10, fontWeight: 600,
            color: showOverride ? '#fff' : 'var(--text-3)', cursor: 'pointer',
          }}>
            {type.needsClient ? 'Client' : 'Supplier'} {showOverride ? '✓' : '↓'}
          </button>
        )}
        <button onClick={onRemove} style={{
          width: 24, height: 24, borderRadius: 4, background: 'transparent',
          border: '1px solid var(--border)', cursor: 'pointer',
          color: 'var(--text-3)', fontSize: 14, lineHeight: 1,
        }} title="Remove this document slot">×</button>
      </div>

      {/* Optional override row */}
      {showOverride && (type.needsClient || type.needsSupplier) && (
        <div style={{ padding: '10px 12px', display: 'grid', gridTemplateColumns: type.needsClient && type.needsSupplier ? '1fr 1fr' : '1fr', gap: 10, background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border-subtle)' }}>
          {type.needsClient && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Client for this document</div>
              <Select value={doc.clientOverride || defaultClient} onChange={e => onUpdate({ clientOverride: e.target.value })}>
                {clientList.map(c => <option key={c.id} value={c.id}>{c.name} — {c.type}</option>)}
                <option value="__new">+ Add new client to master…</option>
              </Select>
            </div>
          )}
          {type.needsSupplier && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Supplier for this document</div>
              <Select value={doc.supplierOverride || defaultSupplier} onChange={e => onUpdate({ supplierOverride: e.target.value })}>
                {supplierList.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                <option value="__new">+ Add new supplier to master…</option>
              </Select>
            </div>
          )}
        </div>
      )}

      {/* Drop area */}
      <label style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '14px 16px', cursor: 'pointer',
        background: doc.files.length ? 'transparent' : 'var(--bg-subtle)',
        borderTop: doc.files.length ? '1px dashed var(--border)' : 'none',
      }}>
        <input type="file" accept=".pdf,.jpg,.png" multiple={type.multi} onChange={handleFiles} style={{ display: 'none' }} />
        <span style={{ fontSize: 18, color: 'var(--text-3)' }}>+</span>
        <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
          {doc.files.length === 0
            ? `Click to upload ${type.label.toLowerCase()}${type.multi ? ' (multiple allowed)' : ''}`
            : type.multi ? 'Click to add more files' : 'Click to replace file'}
        </span>
      </label>

      {/* Files list */}
      {doc.files.length > 0 && (
        <div style={{ padding: '6px 12px 10px' }}>
          {doc.files.map((f, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '6px 8px', borderRadius: 4,
              background: 'var(--bg-subtle)', marginTop: 4,
            }}>
              <span style={{ fontSize: 12 }}>📄</span>
              <span style={{ flex: 1, fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}>{f}</span>
              <button onClick={() => removeFile(i)} style={{
                background: 'transparent', border: 'none', cursor: 'pointer',
                color: 'var(--text-3)', fontSize: 14,
              }}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── API Wiring Checklist Modal
const API_ITEMS = [
  { action: 'Create shipment', endpoint: 'POST /api/v1/upload/shipment', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Upload invoice', endpoint: 'POST /api/v1/upload/shipment', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Upload AWB', endpoint: 'POST /api/v1/upload/shipment', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Run DHL pre-check', endpoint: 'POST /api/v1/dhl/match-and-handle', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Scan DHL inbox', endpoint: 'GET /api/v1/dhl/scan-inbox', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Generate PZ document', endpoint: 'POST /api/v1/pz/generate', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Export to wFirma', endpoint: 'POST /api/v1/wfirma/export', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'List shipments', endpoint: 'GET /api/v1/shipments', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'Get shipment detail', endpoint: 'GET /api/v1/shipments/:id', exists: true, auth: true, status: 'Live', fix: '' },
  { action: 'AI Bridge: classify', endpoint: 'POST /api/v1/ai/classify', exists: true, auth: true, status: 'Live', fix: '' },
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

Object.assign(window, { NewShipmentModal, ApiChecklistModal, CLIENT_LIST, SUPPLIER_LIST });
