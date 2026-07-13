// supplier-detail.jsx — Supplier Detail edit / create modal.
//
// Authority: Supplier Master.
// Edit mode (supplierId = number/string): loads via PzApi.getSupplier(supplierId);
//   saves ONLY changed fields via PzApi.saveSupplier(id, diff) with confirm dialog.
// Create mode (supplierId = null/undefined): empty form; calls PzApi.createSupplier(body).
//
// supplier_code is the immutable business key — READ-ONLY in edit mode.
// wfirma_id is always READ-ONLY (set by wFirma sync only).
// Mirrors the structure of client-detail.jsx.

const _SD_TABS = [
  { id: 'identity', label: 'Identity' },
  { id: 'tax',      label: 'Tax' },
  { id: 'address',  label: 'Address' },
  { id: 'contact',  label: 'Contact' },
  { id: 'wfirma',   label: 'wFirma' },
  { id: 'notes',    label: 'Notes' },
];

// ── Field wrapper ─────────────────────────────────────────────────────────────
function _SdField({ label, children, span, hint }) {
  return (
    <div style={{ gridColumn: span ? 'span ' + span : 'span 1' }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-2)', display: 'block', marginBottom: 4 }}>
        {label}
      </label>
      {children}
      {hint && <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

// ── Shared input styles ───────────────────────────────────────────────────────
const _sdInputStyle = {
  width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box',
  border: '1px solid var(--border)', borderRadius: 6,
  background: 'var(--card)', color: 'var(--text)',
};
const _sdReadonlyStyle = Object.assign({}, _sdInputStyle, {
  background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed',
});

// ── Confirm-before-save dialog ────────────────────────────────────────────────
function _SdConfirmDialog({ changes, onConfirm, onCancel }) {
  var entries = Object.entries(changes);
  return (
    <div data-testid="sd-confirm-dialog" style={{
      position: 'fixed', inset: 0, zIndex: 1100,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }} onClick={onCancel}>
      <div onClick={function(e){ e.stopPropagation(); }} style={{
        background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
        maxWidth: 480, width: '100%', maxHeight: '60vh', overflow: 'auto',
        boxShadow: '0 12px 40px rgba(0,0,0,0.35)', padding: 20,
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 12 }}>Confirm changes</div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
          {entries.length} field{entries.length === 1 ? '' : 's'} will be updated:
        </div>
        <div style={{ maxHeight: 200, overflowY: 'auto', marginBottom: 16 }}>
          {entries.map(function(kv){
            var k = kv[0]; var v = kv[1];
            return (
              <div key={k} style={{
                display: 'grid', gridTemplateColumns: '160px 1fr', gap: 8,
                padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11,
              }}>
                <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>
                  {k.replace(/_/g, ' ').replace(/\b\w/g, function(c){ return c.toUpperCase(); })}
                </span>
                <span style={{ fontFamily: 'monospace', color: 'var(--text)', wordBreak: 'break-word' }}>
                  {v === null || v === '' ? '(cleared)' : String(v)}
                </span>
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Btn variant="outline" small onClick={onCancel} data-testid="sd-confirm-cancel">Cancel</Btn>
          <Btn variant="gold" small onClick={onConfirm} data-testid="sd-confirm-save">Save Changes</Btn>
        </div>
      </div>
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────
function SupplierDetailModal({ supplierId, onClose, onSaved }) {
  var isCreate = supplierId === null || supplierId === undefined;
  var [tab, setTab]                   = React.useState('identity');
  var [loading, setLoading]           = React.useState(!isCreate);
  var [saving, setSaving]             = React.useState(false);
  var [loadErr, setLoadErr]           = React.useState(null);
  var [saveErr, setSaveErr]           = React.useState(null);
  var [fieldErr, setFieldErr]         = React.useState({});
  var [showConfirm, setShowConfirm]   = React.useState(false);
  var [original, setOriginal]         = React.useState(null);
  var [form, setForm]                 = React.useState({
    supplier_code: '', name: '', country: '',
    vat_id: '', eori: '',
    street: '', city: '', postal_code: '', address: '',
    contact_email: '', contact_phone: '', contact_mobile: '', bank_account: '',
    wfirma_id: '', notes: '',
  });

  // ── Load on open (edit mode) ──────────────────────────────────────────────
  React.useEffect(function() {
    if (isCreate) return;
    setLoading(true);
    setLoadErr(null);
    PzApi.getSupplier(supplierId).then(function(res) {
      if (res.ok) {
        var d = res.data || {};
        setOriginal(d);
        setForm({
          supplier_code:  d.supplier_code  != null ? String(d.supplier_code)  : '',
          name:           d.name           != null ? String(d.name)           : '',
          country:        d.country        != null ? String(d.country)        : '',
          vat_id:         d.vat_id         != null ? String(d.vat_id)         : '',
          eori:           d.eori           != null ? String(d.eori)           : '',
          street:         d.street         != null ? String(d.street)         : '',
          city:           d.city           != null ? String(d.city)           : '',
          postal_code:    d.postal_code    != null ? String(d.postal_code)    : '',
          address:        d.address        != null ? String(d.address)        : '',
          contact_email:  d.contact_email  != null ? String(d.contact_email)  : '',
          contact_phone:  d.contact_phone  != null ? String(d.contact_phone)  : '',
          contact_mobile: d.contact_mobile != null ? String(d.contact_mobile) : '',
          bank_account:   d.bank_account   != null ? String(d.bank_account)   : '',
          wfirma_id:      d.wfirma_id      != null ? String(d.wfirma_id)      : '',
          notes:          d.notes          != null ? String(d.notes)          : '',
        });
      } else {
        setLoadErr(res.error || 'Failed to load supplier');
      }
      setLoading(false);
    }).catch(function(err) { setLoadErr(String(err)); setLoading(false); });
  }, [supplierId]);

  // ── Field helpers ─────────────────────────────────────────────────────────
  function setField(field, value) {
    setForm(function(prev) { var n = Object.assign({}, prev); n[field] = value; return n; });
    setSaveErr(null);
    setFieldErr(function(prev) { var n = Object.assign({}, prev); n[field] = null; return n; });
  }
  function val(field) {
    var v = form[field];
    return (v === null || v === undefined) ? '' : String(v);
  }

  // ── Compute changed fields (edit mode) ────────────────────────────────────
  function computeChanges() {
    if (!original) return {};
    var SKIP = { id:1, created_at:1, updated_at:1, last_wfirma_sync_at:1,
                 deleted_at:1, wfirma_id:1, wfirma_sync_source:1 };
    var ch = {};
    Object.keys(form).forEach(function(key) {
      if (SKIP[key]) return;
      var ov = (original[key] === null || original[key] === undefined || original[key] === '') ? '' : String(original[key]);
      var nv = val(key);
      if (ov !== nv) ch[key] = nv;
    });
    return ch;
  }
  var changedFields = isCreate ? {} : computeChanges();
  var hasChanges    = isCreate ? true : Object.keys(changedFields).length > 0;

  // ── Validation ────────────────────────────────────────────────────────────
  function validate() {
    var errs = {};
    if (!val('supplier_code').trim()) errs.supplier_code = 'Required';
    if (!val('name').trim())          errs.name          = 'Required';
    var c = val('country').trim();
    if (!c)              errs.country = 'Required';
    else if (c.length !== 2) errs.country = '2-letter ISO code required (e.g. CN, DE)';
    setFieldErr(errs);
    return Object.keys(errs).length === 0;
  }

  // ── Save flow ─────────────────────────────────────────────────────────────
  function handleSaveClick() {
    if (!validate()) return;
    if (!isCreate && !hasChanges) return;
    if (isCreate) { doSave(); return; }
    setShowConfirm(true);
  }

  function doSave() {
    setSaving(true);
    setSaveErr(null);
    var p;
    if (isCreate) {
      var body = {};
      Object.keys(form).forEach(function(k) {
        if (k === 'wfirma_id') return;
        var v = form[k];
        if (typeof v === 'string' && v.trim() !== '') {
          body[k] = k === 'country' ? v.trim().toUpperCase() : v.trim();
        }
      });
      p = PzApi.createSupplier(body);
    } else {
      var diff = Object.assign({}, changedFields);
      if (diff.country) diff.country = diff.country.toUpperCase();
      p = PzApi.saveSupplier(supplierId, diff);
    }
    p.then(function(res) {
      setSaving(false);
      setShowConfirm(false);
      if (res.ok) {
        if (onSaved) onSaved();
        onClose();
      } else {
        var detail = (res.data && res.data.detail) ? String(res.data.detail) : '';
        if (res.status === 409 || detail.indexOf('DUPLICATE_CODE') === 0) {
          setSaveErr('Duplicate supplier code — a supplier with this code already exists.');
        } else {
          setSaveErr(res.error || detail || (isCreate ? 'Create failed' : 'Save failed'));
        }
      }
    }).catch(function(err) { setSaving(false); setShowConfirm(false); setSaveErr(String(err)); });
  }

  // ── Timestamp formatter ───────────────────────────────────────────────────
  function fmtTs(s) {
    if (!s) return '--';
    try {
      var d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleString('en-GB', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
    } catch(e) { return s; }
  }

  // ── Input renderer ────────────────────────────────────────────────────────
  function inp(field, opts) {
    var options   = opts || {};
    var placeholder = options.placeholder;
    var type        = options.type || 'text';
    var readonly    = options.readonly;
    var testid      = options.testid || ('sd-' + field);
    if (readonly) {
      return (
        <input data-testid={testid} type={type}
          style={_sdReadonlyStyle} value={val(field)} readOnly
          title="Read-only — system-managed field" />
      );
    }
    var borderColor = fieldErr[field] ? 'var(--badge-red-border, rgba(220,38,38,0.7))' : 'var(--border)';
    var style = Object.assign({}, _sdInputStyle, { borderColor: borderColor });
    return (
      <div>
        <input data-testid={testid} type={type}
          style={style}
          value={val(field)} placeholder={placeholder || ''}
          onChange={function(e) { setField(field, e.target.value); }} />
        {fieldErr[field] && (
          <div style={{ fontSize: 10, color: 'var(--badge-red-text, rgba(220,38,38,0.9))', marginTop: 2 }}>{fieldErr[field]}</div>
        )}
      </div>
    );
  }

  var changedCount = Object.keys(changedFields).length;

  return (
    <div data-testid="supplier-detail-modal" style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--bg)', borderRadius: 12, width: '100%', maxWidth: 820,
        maxHeight: '92vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        border: '1px solid var(--border)', boxShadow: '0 12px 48px rgba(0,0,0,0.25)',
        color: 'var(--text)',
      }} onClick={function(e){ e.stopPropagation(); }}>

        {/* ── Header ── */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {isCreate ? 'New Supplier' : (original ? original.name : 'Supplier')}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
              {isCreate ? 'Create new supplier record' : 'Edit supplier record'}
            </div>
          </div>
          <Btn small variant="ghost" onClick={onClose} data-testid="sd-close">{'✕'} Close</Btn>
        </div>

        {/* ── Tab strip ── */}
        <div style={{ display: 'flex', gap: 0, padding: '0 24px', borderBottom: '1px solid var(--border)' }}>
          {_SD_TABS.map(function(t) {
            return (
              <Btn key={t.id} data-testid={'sd-tab-' + t.id}
                onClick={function(){ setTab(t.id); }}
                variant={tab === t.id ? 'outline' : 'ghost'}
                style={{
                  padding: '12px 14px', background: 'none', borderRadius: 0, marginBottom: -1,
                  borderBottom: '2px solid ' + (tab === t.id ? 'var(--accent)' : 'transparent'),
                  fontWeight: tab === t.id ? 700 : 500, fontSize: 12.5,
                }}>{t.label}</Btn>
            );
          })}
        </div>

        {/* ── Body ── */}
        <div style={{ overflowY: 'auto', flex: 1, padding: 24 }}>

          {loading && (
            <div data-testid="sd-loading" style={{ textAlign:'center', padding: 48, color:'var(--text-3)' }}>
              Loading supplier data...
            </div>
          )}

          {loadErr && (
            <div data-testid="sd-load-error" style={{ padding:16, background:'var(--badge-red-bg, rgba(220,38,38,0.08))', border:'1px solid var(--badge-red-border, rgba(220,38,38,0.2))', borderRadius:6, color:'var(--badge-red-text, rgba(220,38,38,0.9))', fontSize:12 }}>
              {loadErr}
            </div>
          )}

          {saveErr && (
            <div data-testid="sd-save-error" style={{ padding:12, marginBottom:12, background:'var(--badge-red-bg, rgba(220,38,38,0.08))', border:'1px solid var(--badge-red-border, rgba(220,38,38,0.2))', borderRadius:6, fontSize:12, color:'var(--badge-red-text, rgba(220,38,38,0.9))' }}>
              Save failed: {saveErr}
            </div>
          )}

          {/* Identity tab */}
          {!loading && !loadErr && tab === 'identity' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_SdField label="Supplier code *" hint={isCreate ? 'Business key — cannot be changed after creation' : 'Business key — read-only after creation'}>
                {inp('supplier_code', { placeholder: 'e.g. SUP-001', readonly: !isCreate })}
              </_SdField>
              <_SdField label="Name *">
                {inp('name', { placeholder: 'Supplier legal name' })}
              </_SdField>
              <_SdField label="Country * (ISO-2)" hint="Two-letter ISO country code">
                {inp('country', { placeholder: 'CN', testid: 'sd-country' })}
              </_SdField>
            </div>
          )}

          {/* Tax tab */}
          {!loading && !loadErr && tab === 'tax' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_SdField label="VAT ID">
                {inp('vat_id', { placeholder: 'VAT / NIP number' })}
              </_SdField>
              <_SdField label="EORI">
                {inp('eori', { placeholder: 'EORI number' })}
              </_SdField>
            </div>
          )}

          {/* Address tab */}
          {!loading && !loadErr && tab === 'address' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_SdField label="Street" span={2}>
                {inp('street', { placeholder: 'Street and number' })}
              </_SdField>
              <_SdField label="City">
                {inp('city', { placeholder: 'City' })}
              </_SdField>
              <_SdField label="Postal code">
                {inp('postal_code', { placeholder: 'Postal / ZIP code' })}
              </_SdField>
              <_SdField label="Address (legacy free-form)" span={2} hint="Legacy field — prefer Street / City / Postal for new records">
                <textarea data-testid="sd-address" rows={3}
                  style={Object.assign({}, _sdInputStyle, { resize: 'vertical' })}
                  value={val('address')} onChange={function(e){ setField('address', e.target.value); }}
                  placeholder="Legacy free-form address" />
              </_SdField>
            </div>
          )}

          {/* Contact tab */}
          {!loading && !loadErr && tab === 'contact' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_SdField label="Contact email" span={2}>
                {inp('contact_email', { placeholder: 'contact@supplier.com', type: 'email' })}
              </_SdField>
              <_SdField label="Phone">
                {inp('contact_phone', { placeholder: '+86 ...' })}
              </_SdField>
              <_SdField label="Mobile">
                {inp('contact_mobile', { placeholder: '+86 ...' })}
              </_SdField>
              <_SdField label="Bank account" span={2}>
                {inp('bank_account', { placeholder: 'IBAN or account number' })}
              </_SdField>
            </div>
          )}

          {/* wFirma tab */}
          {!loading && !loadErr && tab === 'wfirma' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_SdField label="wFirma ID" hint="Set by wFirma sync — read-only">
                {inp('wfirma_id', { placeholder: '—', readonly: true })}
              </_SdField>
              {!isCreate && original && (
                <_SdField label="Last wFirma sync">
                  <input style={_sdReadonlyStyle} readOnly value={fmtTs(original.last_wfirma_sync_at)} data-testid="sd-last-sync" />
                </_SdField>
              )}
            </div>
          )}

          {/* Notes tab */}
          {!loading && !loadErr && tab === 'notes' && (
            <_SdField label="Notes">
              <textarea data-testid="sd-notes" rows={6}
                style={Object.assign({}, _sdInputStyle, { resize: 'vertical' })}
                value={val('notes')} onChange={function(e){ setField('notes', e.target.value); }}
                placeholder="Internal notes" />
            </_SdField>
          )}

          {/* Record info collapsible (edit mode) */}
          {!loading && !loadErr && !isCreate && original && (
            <details style={{ marginTop: 20 }} data-testid="sd-record-info">
              <summary style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer', userSelect: 'none', padding: '4px 0' }}>
                Record info (read-only)
              </summary>
              <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: '6px 12px', marginTop: 8 }}>
                {[
                  ['ID',             original.id || '--'],
                  ['Created',        fmtTs(original.created_at)],
                  ['Updated',        fmtTs(original.updated_at)],
                  ['Last wFirma sync', fmtTs(original.last_wfirma_sync_at)],
                ].map(function(pair) {
                  return (
                    <React.Fragment key={pair[0]}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)' }}>{pair[0]}</div>
                      <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text)' }}>{pair[1] || '--'}</div>
                    </React.Fragment>
                  );
                })}
              </div>
            </details>
          )}
        </div>

        {/* ── Footer ── */}
        <div style={{
          padding: '14px 24px', borderTop: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
            {isCreate
              ? 'Fill required fields (*) then click Create'
              : hasChanges
                ? changedCount + ' field' + (changedCount === 1 ? '' : 's') + ' changed'
                : 'No changes'}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="outline" onClick={onClose} data-testid="sd-cancel">Cancel</Btn>
            <Btn variant="gold" onClick={handleSaveClick}
              disabled={(!isCreate && !hasChanges) || saving || loading}
              data-testid="sd-save">
              {saving ? 'Saving...' : isCreate ? 'Create Supplier' : 'Save to Supplier Master'}
            </Btn>
          </div>
        </div>
      </div>

      {showConfirm && !isCreate && (
        <_SdConfirmDialog
          changes={changedFields}
          onConfirm={doSave}
          onCancel={function(){ setShowConfirm(false); }}
        />
      )}
    </div>
  );
}

Object.assign(window, { SupplierDetailModal });
