// client-detail.jsx — Client Detail edit modal for Customer Master authority.
//
// Step 3 of Customer Master Address Authority migration.
// Authority: Customer Master is PRIMARY for client identity, email, address.
//   bill_to_* = invoice / billing authority
//   ship_to_* = DHL delivery / shipping authority
//   Shape B (ship_to_contractor_id) = wFirma receiver, NOT DHL delivery
//
// Loads full record via PzApi.getCustomerMaster(clientKey).
// Saves changed fields via PzApi.saveCustomerMaster(clientKey, body).
// Backend _parse_body hydrates omitted fields from stored record (partial PUT).
//
// No DHL logic. No proforma logic. No email send logic.
// UI only — authority stays backend-side.

const _CD_TABS = [
  { id: 'identity',   label: 'Identity' },
  { id: 'billing',    label: 'Billing Address' },
  { id: 'shipping',   label: 'Shipping Address' },
  { id: 'commercial', label: 'Commercial Defaults' },
  { id: 'sync',       label: 'Sync & Authority' },
];

// ── Reusable field component ────────────────────────────────────────────
function _CdField({ label, children, span, hint, testid }) {
  return (
    <div style={{ gridColumn: span ? 'span ' + span : 'span 1' }}>
      <label data-testid={testid ? testid + '-label' : undefined}
        style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>
        {label}
      </label>
      {children}
      {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

// ── Authority badge ─────────────────────────────────────────────────────
function _AuthBadge({ text }) {
  return (
    <span data-testid="authority-badge" style={{
      fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em',
      padding: '2px 8px', borderRadius: 3,
      background: 'rgba(212,168,83,0.12)', color: 'var(--accent, #d4a853)',
      border: '1px solid rgba(212,168,83,0.25)',
    }}>{text}</span>
  );
}

// ── Input style (shared) ────────────────────────────────────────────────
const _cdInputStyle = {
  width: '100%', padding: '8px 10px', fontSize: 13,
  border: '1px solid var(--border)', borderRadius: 6,
  background: 'var(--card)', color: 'var(--text)',
};

const _cdReadonlyStyle = {
  ..._cdInputStyle,
  background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed',
};

// ── Confirm dialog ──────────────────────────────────────────────────────
function _CdConfirmDialog({ changes, onConfirm, onCancel }) {
  const entries = Object.entries(changes);
  return (
    <div data-testid="cd-confirm-dialog" style={{
      position: 'fixed', inset: 0, zIndex: 1100,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }} onClick={onCancel}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
        maxWidth: 480, width: '100%', maxHeight: '60vh', overflow: 'auto',
        boxShadow: '0 12px 40px rgba(0,0,0,0.35)', padding: 20,
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 12 }}>
          Confirm changes
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
          {entries.length} field{entries.length === 1 ? '' : 's'} will be updated:
        </div>
        <div style={{ maxHeight: 200, overflowY: 'auto', marginBottom: 16 }}>
          {entries.map(([k, v]) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '160px 1fr', gap: 8,
              padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
              fontSize: 11,
            }}>
              <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>
                {k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
              </span>
              <span style={{ fontFamily: 'monospace', color: 'var(--text)', wordBreak: 'break-word' }}>
                {v === null || v === '' ? '(cleared)' : String(v)}
              </span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onCancel} data-testid="cd-confirm-cancel">Cancel</Btn>
          <Btn variant="gold" small onClick={onConfirm} data-testid="cd-confirm-save">Save Changes</Btn>
        </div>
      </div>
    </div>
  );
}

// ── Main modal ──────────────────────────────────────────────────────────
function ClientDetailModal({ clientKey, onClose, onSaved }) {
  const [tab, setTab] = React.useState('identity');
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [saveError, setSaveError] = React.useState(null);
  const [validationErrors, setValidationErrors] = React.useState([]);
  const [showConfirm, setShowConfirm] = React.useState(false);

  // Original record from GET (frozen reference for diff)
  const [original, setOriginal] = React.useState(null);
  // Working copy (editable)
  const [form, setForm] = React.useState({});

  // ── Load customer on mount ──────────────────────────────────────────
  React.useEffect(() => {
    if (!clientKey) return;
    setLoading(true);
    setError(null);
    PzApi.getCustomerMaster(clientKey).then(res => {
      if (res.ok) {
        setOriginal(res.data);
        setForm({ ...res.data });
      } else {
        setError(res.error || 'Failed to load customer');
      }
      setLoading(false);
    }).catch(err => {
      setError(String(err));
      setLoading(false);
    });
  }, [clientKey]);

  if (!clientKey) return null;

  // ── Field setter ────────────────────────────────────────────────────
  const set = (field, value) => {
    setForm(prev => ({ ...prev, [field]: value }));
    setSaveError(null);
    setValidationErrors([]);
  };

  const val = (field) => {
    const v = form[field];
    if (v === null || v === undefined) return '';
    return String(v);
  };

  const boolVal = (field) => !!form[field];

  const toggleBool = (field) => set(field, !form[field]);

  // ── Compute changed fields ──────────────────────────────────────────
  const computeChanges = () => {
    if (!original) return {};
    const changes = {};
    for (const key of Object.keys(form)) {
      if (key === 'id' || key === 'created_at' || key === 'updated_at' ||
          key === 'last_wfirma_sync_at' || key === 'wfirma_sync_source' ||
          key === 'deleted_at') continue;
      const ov = original[key];
      const nv = form[key];
      // Normalize: treat null, undefined, '' as equivalent for comparison
      const ovNorm = (ov === null || ov === undefined || ov === '') ? '' : String(ov);
      const nvNorm = (nv === null || nv === undefined || nv === '') ? '' : String(nv);
      if (ovNorm !== nvNorm) {
        // Send empty string for cleared fields (backend coerces to None)
        changes[key] = nv === '' ? '' : nv;
      }
    }
    return changes;
  };

  const changedFields = computeChanges();
  const hasChanges = Object.keys(changedFields).length > 0;

  // ── Save handler ────────────────────────────────────────────────────
  const handleSaveClick = () => {
    if (!hasChanges) return;
    setShowConfirm(true);
  };

  const handleConfirmSave = () => {
    setShowConfirm(false);
    setSaving(true);
    setSaveError(null);
    setValidationErrors([]);

    PzApi.saveCustomerMaster(clientKey, changedFields).then(res => {
      if (res.ok) {
        Toast.success('Client updated successfully');
        if (onSaved) onSaved();
        onClose();
      } else {
        // Check for validation errors
        if (res.data && res.data.detail && res.data.detail.validation_errors) {
          setValidationErrors(res.data.detail.validation_errors);
        } else {
          setSaveError(res.error || res.data?.detail || 'Save failed');
        }
      }
      setSaving(false);
    }).catch(err => {
      setSaveError(String(err));
      setSaving(false);
    });
  };

  // ── Format timestamp ────────────────────────────────────────────────
  const fmtTs = (isoStr) => {
    if (!isoStr) return '--';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (_) { return isoStr; }
  };

  // ── Render input helper ─────────────────────────────────────────────
  const inp = (field, opts) => {
    const { placeholder, type, readonly, testid } = opts || {};
    if (readonly) {
      return <input data-testid={testid || 'cd-' + field} type={type || 'text'}
        style={_cdReadonlyStyle} value={val(field)} readOnly title="Read-only — system-managed field" />;
    }
    return <input data-testid={testid || 'cd-' + field} type={type || 'text'}
      style={_cdInputStyle} value={val(field)} placeholder={placeholder || ''}
      onChange={e => set(field, e.target.value)} />;
  };

  const sel = (field, options, opts) => {
    const { testid } = opts || {};
    return (
      <select data-testid={testid || 'cd-' + field} style={_cdInputStyle}
        value={val(field)} onChange={e => set(field, e.target.value)}>
        <option value="">--</option>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  };

  // ── Shipping toggle state ───────────────────────────────────────────
  const shipToEnabled = boolVal('ship_to_use_alternate');

  return (
    <div data-testid="client-detail-modal" style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--bg)', borderRadius: 12, width: '100%', maxWidth: 920,
        maxHeight: '92vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        border: '1px solid var(--border)', boxShadow: '0 12px 48px rgba(0,0,0,0.25)',
        color: 'var(--text)',
      }} onClick={e => e.stopPropagation()}>

        {/* ── Header ──────────────────────────────────────────────── */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {original ? original.bill_to_name : 'Client'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
              Edit client record
              {original && original.bill_to_contractor_id && (
                <span style={{ marginLeft: 8, fontFamily: 'monospace', fontSize: 10 }}>
                  wFirma ID: {original.bill_to_contractor_id}
                </span>
              )}
            </div>
          </div>
          <Btn small variant="ghost" onClick={onClose} data-testid="cd-close">X Close</Btn>
        </div>

        {/* ── Tab strip ───────────────────────────────────────────── */}
        <div style={{
          display: 'flex', gap: 0, padding: '0 24px',
          borderBottom: '1px solid var(--border)',
        }}>
          {_CD_TABS.map(t => (
            <button key={t.id} data-testid={'cd-tab-' + t.id}
              onClick={() => setTab(t.id)} style={{
                padding: '12px 14px', background: 'none', border: 'none', cursor: 'pointer',
                borderBottom: '2px solid ' + (tab === t.id ? 'var(--accent)' : 'transparent'),
                color: tab === t.id ? 'var(--text)' : 'var(--text-2)',
                fontSize: 12.5, fontWeight: tab === t.id ? 700 : 500, marginBottom: -1,
              }}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Body ────────────────────────────────────────────────── */}
        <div style={{ overflowY: 'auto', flex: 1, padding: 24 }}>

          {/* Loading */}
          {loading && (
            <div data-testid="cd-loading" style={{ textAlign: 'center', padding: 48, color: 'var(--text-3)' }}>
              Loading customer data...
            </div>
          )}

          {/* Error */}
          {error && (
            <div data-testid="cd-error" style={{
              padding: 16, background: 'rgba(220,38,38,0.08)',
              border: '1px solid rgba(220,38,38,0.2)', borderRadius: 6,
              color: 'var(--badge-red-text, #991b1b)', fontSize: 12,
            }}>
              {error}
            </div>
          )}

          {/* Validation errors */}
          {validationErrors.length > 0 && (
            <div data-testid="cd-validation-errors" style={{
              padding: 12, marginBottom: 12,
              background: 'rgba(220,38,38,0.08)',
              border: '1px solid rgba(220,38,38,0.2)', borderRadius: 6,
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 4 }}>
                Validation failed
              </div>
              {validationErrors.map((err, i) => (
                <div key={i} style={{ fontSize: 11, color: 'var(--badge-red-text)', marginBottom: 2 }}>
                  {err}
                </div>
              ))}
            </div>
          )}

          {/* Save error */}
          {saveError && (
            <div data-testid="cd-save-error" style={{
              padding: 12, marginBottom: 12,
              background: 'rgba(220,38,38,0.08)',
              border: '1px solid rgba(220,38,38,0.2)', borderRadius: 6,
              fontSize: 12, color: 'var(--badge-red-text)',
            }}>
              Save failed: {saveError}
            </div>
          )}

          {/* ── Identity tab ──────────────────────────────────────── */}
          {!loading && !error && tab === 'identity' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_CdField label="Company name *" span={2}>
                {inp('bill_to_name', { placeholder: 'Company legal name' })}
              </_CdField>
              <_CdField label="Country *">
                {inp('country', { placeholder: 'PL' })}
              </_CdField>
              <_CdField label="Default currency">
                {sel('default_currency', ['EUR', 'PLN', 'USD', 'CHF', 'GBP', 'CZK', 'HUF', 'BGN'])}
              </_CdField>
              <_CdField label="NIP / VAT ID">
                {inp('nip', { placeholder: 'PL5252312345' })}
              </_CdField>
              <_CdField label="EU VAT number">
                {inp('vat_eu_number', { placeholder: 'PL5252312345' })}
              </_CdField>
              <_CdField label="EORI">
                {inp('eori', { placeholder: 'PL525231234500000' })}
              </_CdField>
              <_CdField label="REGON">
                {inp('regon')}
              </_CdField>
              <_CdField label="Short code">
                {inp('short_code', { placeholder: 'JLY' })}
              </_CdField>
              <_CdField label="Client type">
                {sel('client_type', ['Importer', 'Buyer', 'Distributor', 'Retailer', 'Wholesale'])}
              </_CdField>
              <_CdField label="Industry">
                {sel('industry', ['Jewelry retail', 'Jewelry wholesale', 'Distributor', 'Watch retail', 'Other'])}
              </_CdField>
              <_CdField label="Active">
                <label data-testid="cd-active-toggle" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                  <input type="checkbox" data-testid="cd-active" checked={boolVal('active')}
                    onChange={() => toggleBool('active')} />
                  <span style={{ fontSize: 12 }}>{boolVal('active') ? 'Active' : 'Inactive'}</span>
                </label>
              </_CdField>
              <_CdField label="Internal notes" span={2}>
                <textarea data-testid="cd-notes" rows={3}
                  style={{ ..._cdInputStyle, resize: 'vertical' }}
                  value={val('notes')} onChange={e => set('notes', e.target.value)}
                  placeholder="Internal notes (not visible to client)" />
              </_CdField>
            </div>
          )}

          {/* ── Billing Address tab ───────────────────────────────── */}
          {!loading && !error && tab === 'billing' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <_AuthBadge text="Authority: Invoice / Billing" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <_CdField label="Email" span={2} hint="Primary email for proforma and invoice delivery">
                  {inp('bill_to_email', { placeholder: 'billing@company.com', type: 'email' })}
                </_CdField>
                <_CdField label="Phone">
                  {inp('bill_to_phone', { placeholder: '+48 22 123 4567' })}
                </_CdField>
                <_CdField label="Mobile">
                  {inp('bill_to_mobile', { placeholder: '+48 600 123 456' })}
                </_CdField>
                <_CdField label="Street" span={2}>
                  {inp('bill_to_street', { placeholder: 'Street and number' })}
                </_CdField>
                <_CdField label="City">
                  {inp('bill_to_city', { placeholder: 'City' })}
                </_CdField>
                <_CdField label="Postal code">
                  {inp('bill_to_postal_code', { placeholder: '00-000' })}
                </_CdField>
                <_CdField label="Bank account" span={2}>
                  {inp('bank_account', { placeholder: 'IBAN or account number' })}
                </_CdField>
              </div>
            </div>
          )}

          {/* ── Shipping Address tab ──────────────────────────────── */}
          {!loading && !error && tab === 'shipping' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <_AuthBadge text="Authority: DHL Delivery" />
              </div>

              {/* Toggle */}
              <div data-testid="cd-shipto-toggle-section" style={{
                padding: 14, marginBottom: 16,
                background: 'var(--bg-subtle)', border: '1px solid var(--border)',
                borderRadius: 8,
              }}>
                <label data-testid="cd-shipto-toggle-label" style={{
                  display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
                }}>
                  <input type="checkbox" data-testid="cd-ship_to_use_alternate"
                    checked={shipToEnabled}
                    onChange={() => toggleBool('ship_to_use_alternate')} />
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>
                      {shipToEnabled ? 'Different delivery address' : 'Delivery address: Same as billing'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                      {shipToEnabled
                        ? 'DHL will deliver to the alternate address below'
                        : 'DHL will use the billing address for delivery'}
                    </div>
                  </div>
                </label>
              </div>

              {/* Ship-to fields (visible when toggled on) */}
              {shipToEnabled && (
                <div data-testid="cd-shipto-fields" style={{
                  border: '1px solid var(--border)', borderRadius: 8,
                  padding: 16, marginBottom: 16,
                }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
                    textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12,
                  }}>Alternate delivery address</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                    <_CdField label="Company / recipient name">
                      {inp('ship_to_name', { placeholder: 'Warehouse name or company' })}
                    </_CdField>
                    <_CdField label="Contact person">
                      {inp('ship_to_person', { placeholder: 'Name for courier' })}
                    </_CdField>
                    <_CdField label="Street" span={2}>
                      {inp('ship_to_street', { placeholder: 'Street and number' })}
                    </_CdField>
                    <_CdField label="City">
                      {inp('ship_to_city', { placeholder: 'City' })}
                    </_CdField>
                    <_CdField label="Postal code">
                      {inp('ship_to_zip', { placeholder: '00-000' })}
                    </_CdField>
                    <_CdField label="Country">
                      {inp('ship_to_country', { placeholder: 'PL' })}
                    </_CdField>
                    <_CdField label="Phone">
                      {inp('ship_to_phone', { placeholder: '+48 ...' })}
                    </_CdField>
                    <_CdField label="Email" span={2} hint="Delivery notification email (fallback if no billing email)">
                      {inp('ship_to_email', { placeholder: 'warehouse@company.com', type: 'email' })}
                    </_CdField>
                  </div>
                </div>
              )}

              {/* Shape B: wFirma receiver (always visible, independent of toggle) */}
              <div data-testid="cd-shapeb-section" style={{
                border: '1px solid var(--border)', borderRadius: 8,
                padding: 16, background: 'var(--bg-subtle)',
              }}>
                <div style={{
                  fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
                  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8,
                }}>wFirma Receiver</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>
                  Separate wFirma contractor used as invoice receiver. Does NOT affect DHL delivery address.
                </div>
                <_CdField label="wFirma Receiver contractor ID">
                  {inp('ship_to_contractor_id', { placeholder: 'wFirma contractor ID (optional)' })}
                </_CdField>
              </div>
            </div>
          )}

          {/* ── Commercial Defaults tab ───────────────────────────── */}
          {!loading && !error && tab === 'commercial' && (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <_CdField label="Payment method">
                  {sel('preferred_payment_method', ['transfer', 'cash', 'card', 'compensation'])}
                </_CdField>
                <_CdField label="Payment terms (days)">
                  {inp('payment_terms_days', { type: 'number', placeholder: '30' })}
                </_CdField>
                <_CdField label="VAT mode">
                  {inp('vat_mode', { type: 'number', placeholder: '0' })}
                </_CdField>
                <_CdField label="Proforma series ID">
                  {inp('preferred_proforma_series_id', { placeholder: 'wFirma series ID' })}
                </_CdField>
                <_CdField label="Invoice series ID">
                  {inp('preferred_invoice_series_id', { placeholder: 'wFirma series ID' })}
                </_CdField>
                <_CdField label="Language ID">
                  {inp('default_language_id', { placeholder: 'wFirma language ID' })}
                </_CdField>
              </div>

              {/* Freight section */}
              <div style={{
                marginTop: 20, border: '1px solid var(--border)', borderRadius: 8, padding: 16,
              }}>
                <div style={{
                  fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 12,
                }}>Freight defaults</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14 }}>
                  <_CdField label="Mode">
                    {sel('freight_mode', ['no_data', 'fixed', 'variable', 'manual'])}
                  </_CdField>
                  <_CdField label="Fixed amount (EUR)">
                    {inp('freight_fixed_amount_eur', { type: 'number', placeholder: '0.00' })}
                  </_CdField>
                  <_CdField label="Fixed amount (USD)">
                    {inp('freight_fixed_amount_usd', { type: 'number', placeholder: '0.00' })}
                  </_CdField>
                  <_CdField label="Currency">
                    {sel('freight_currency', ['EUR', 'PLN', 'USD'])}
                  </_CdField>
                  <_CdField label="Label (PL)">
                    {inp('freight_label_pl', { placeholder: 'Fracht' })}
                  </_CdField>
                  <_CdField label="Label (EN)">
                    {inp('freight_label_en', { placeholder: 'Freight' })}
                  </_CdField>
                </div>
              </div>

              {/* Insurance section */}
              <div style={{
                marginTop: 16, border: '1px solid var(--border)', borderRadius: 8, padding: 16,
              }}>
                <div style={{
                  fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 12,
                }}>Insurance defaults</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14 }}>
                  <_CdField label="Enabled">
                    <label data-testid="cd-insurance-enabled-toggle" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                      <input type="checkbox" data-testid="cd-insurance_enabled"
                        checked={boolVal('insurance_enabled')}
                        onChange={() => toggleBool('insurance_enabled')} />
                      <span style={{ fontSize: 12 }}>{boolVal('insurance_enabled') ? 'Yes' : 'No'}</span>
                    </label>
                  </_CdField>
                  <_CdField label="Mode">
                    {sel('insurance_mode', ['no_data', 'fixed', 'formula', 'manual'])}
                  </_CdField>
                  <_CdField label="Rate (%)">
                    {inp('insurance_rate', { type: 'number', placeholder: '0.50' })}
                  </_CdField>
                  <_CdField label="Fixed (EUR)">
                    {inp('insurance_fixed_amount_eur', { type: 'number', placeholder: '0.00' })}
                  </_CdField>
                  <_CdField label="Fixed (USD)">
                    {inp('insurance_fixed_amount_usd', { type: 'number', placeholder: '0.00' })}
                  </_CdField>
                  <_CdField label="Min (EUR)">
                    {inp('insurance_min_eur', { type: 'number', placeholder: '0.00' })}
                  </_CdField>
                  <_CdField label="Label (PL)">
                    {inp('insurance_label_pl', { placeholder: 'Ubezpieczenie' })}
                  </_CdField>
                  <_CdField label="Label (EN)">
                    {inp('insurance_label_en', { placeholder: 'Insurance' })}
                  </_CdField>
                  <_CdField label="Min (USD)">
                    {inp('insurance_min_usd', { type: 'number', placeholder: '0.00' })}
                  </_CdField>
                </div>
              </div>
            </div>
          )}

          {/* ── Sync & Authority tab ──────────────────────────────── */}
          {!loading && !error && tab === 'sync' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <_AuthBadge text="System metadata (read-only)" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: '10px 16px' }}>
                {[
                  ['wFirma Contractor ID', val('bill_to_contractor_id'), 'cd-ro-contractor-id'],
                  ['Last wFirma sync', fmtTs(form.last_wfirma_sync_at), 'cd-ro-last-sync'],
                  ['Sync source', val('wfirma_sync_source') || '--', 'cd-ro-sync-source'],
                  ['Created', fmtTs(form.created_at), 'cd-ro-created'],
                  ['Updated', fmtTs(form.updated_at), 'cd-ro-updated'],
                  ['DB ID', val('id') || '--', 'cd-ro-id'],
                ].map(([label, value, testid]) => (
                  <React.Fragment key={testid}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', padding: '6px 0' }}>
                      {label}
                    </div>
                    <div data-testid={testid} style={{
                      fontSize: 12, fontFamily: 'monospace', color: 'var(--text)',
                      padding: '6px 0', borderBottom: '1px solid var(--border-subtle)',
                      wordBreak: 'break-word',
                    }}>
                      {value}
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────────── */}
        <div style={{
          padding: '14px 24px', borderTop: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
            {hasChanges
              ? Object.keys(changedFields).length + ' field' + (Object.keys(changedFields).length === 1 ? '' : 's') + ' changed'
              : 'No changes'}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="outline" onClick={onClose} data-testid="cd-cancel">Cancel</Btn>
            <Btn variant="gold" onClick={handleSaveClick}
              disabled={!hasChanges || saving || loading}
              data-testid="cd-save">
              {saving ? 'Saving...' : 'Save Changes'}
            </Btn>
          </div>
        </div>
      </div>

      {/* Confirm overlay */}
      {showConfirm && (
        <_CdConfirmDialog
          changes={changedFields}
          onConfirm={handleConfirmSave}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}

Object.assign(window, { ClientDetailModal });
