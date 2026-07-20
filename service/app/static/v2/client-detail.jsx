// client-detail.jsx — Client Detail edit modal for Customer Master authority.
//
// ── V1 UI PARITY (operator directive, 2026-07-20) ────────────────────────
// V1 is the VISUAL AUTHORITY for this modal. The reference implementation is
// ClientKycModal in service/app/static/dashboard.html (FROZEN V1 page — read
// only, never edited from here). This file reproduces that screen: the same
// 6 tabs in the same order, the same section headings, the same field order,
// the same labels/placeholders, the same header (title + tab-map subtitle +
// wFirma id + ✕ icon close), the same tab strip, and the same Cancel / Save
// footer. Zero redesign — a V1 operator must not notice the swap.
//
// What stays V2 (the "new engine under the same dashboard"):
//   • async load  — PzApi.getCustomerMaster(clientKey)
//   • partial PUT — PzApi.saveCustomerMaster(clientKey, changedFieldsOnly);
//     the backend _parse_body hydrates omitted fields from the stored record,
//     so V1's full-payload null-coercion lists are neither needed nor safe here.
//
// Save is immediate, exactly like V1 — no confirmation step (operator ruling
// 2026-07-20: a Customer Master edit is not an irreversible financial
// operation; confirm dialogs are reserved for actions that genuinely are).
//
// PARITY DEVIATIONS — deliberate, each preserving capability V1 lacks a home
// for. Removing either would be Lesson-M capability suppression:
//   1. Freight + Insurance defaults live in the Invoices tab. V1 round-trips
//      these fields but renders no UI for them. The backend deep-link
//      _cm_freight_edit_url (routes_proforma.py) sends operators here
//      *specifically* for the freight amount fields, so they must stay visible.
//   2. ship_to_contractor_id / wFirma Receiver (Shipping) and the read-only
//      record metadata (collapsed <details> on Company / Basic) are V2
//      capabilities with no V1 tab. Preserved in the nearest matching V1
//      section rather than deleted.
//
// bank_account is deliberately ABSENT — see the note in the Billing address
// section. It stays out until a canonical customer-banking authority is
// identified and wired (operator ruling 2026-07-20).
//
// Authority: Customer Master is PRIMARY for client identity, email, address.
//   bill_to_* = invoice / billing authority
//   ship_to_* = DHL delivery / shipping authority
//   Shape B (ship_to_contractor_id) = wFirma receiver, NOT DHL delivery
//
// No DHL logic. No proforma logic. No email send logic.
// UI only — authority stays backend-side.

// V1 tab set, order and labels — dashboard.html ClientKycModal KYC_TABS.
const _CD_TABS = [
  { id: 'basic',    label: 'Company / Basic' },
  { id: 'shipping', label: 'Shipping' },
  { id: 'carriers', label: 'Carriers' },
  { id: 'kyc',      label: 'KYC / Compliance' },
  { id: 'kuke',     label: 'KUKE & Credit' },
  { id: 'invoices', label: 'Invoices' },
];

// ── V1 style constants (verbatim from ClientKycModal) ───────────────────
const _cdInputStyle = {
  padding: '5px 8px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 4,
  fontFamily: 'inherit', background: 'var(--bg-subtle)', color: 'var(--text)', width: '100%',
};
const _cdLabelStyle     = { display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11 };
const _cdLabelTextStyle = { fontSize: 10, color: 'var(--text-3)', fontWeight: 600 };
const _cdSectionHeadStyle = {
  fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase',
  letterSpacing: '0.08em', marginBottom: 10, marginTop: 16,
  paddingBottom: 4, borderBottom: '1px solid var(--border-subtle)',
};
const _cdSubHeadStyle = {
  fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
  textTransform: 'uppercase', letterSpacing: '0.08em', flex: 1,
};
const _cdRowBtnStyle = {
  fontSize: 10, padding: '2px 7px', cursor: 'pointer',
  background: 'none', border: '1px solid var(--border)', borderRadius: 3,
  color: 'var(--text-2)',
};
const _cdAddBtnStyle = {
  padding: '3px 10px', fontSize: 10, cursor: 'pointer',
  background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4,
};
const _cdErrorBoxStyle = {
  padding: '6px 10px', background: 'var(--badge-red-bg)',
  border: '1px solid var(--badge-red-border)', borderRadius: 4,
  fontSize: 10, color: 'var(--badge-red-text)', marginBottom: 8,
};
const _cdDefaultPillStyle = {
  fontSize: 9, padding: '1px 5px',
  background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)',
  border: '1px solid var(--badge-green-border)', borderRadius: 8,
  fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
};

// Business label for the stored payment_type value. Display only — the stored
// values (shipper / receiver / third_party) are never rewritten.
const _CD_BILLING_ROLE_LABELS = {
  shipper: 'Sender',
  receiver: 'Receiver',
  third_party: 'Third party',
};
function _cdBillingRoleLabel(paymentType) {
  if (!paymentType) return '';
  return _CD_BILLING_ROLE_LABELS[paymentType] || paymentType;
}

const _cdInactivePillStyle = {
  fontSize: 9, padding: '1px 5px',
  background: 'var(--bg-subtle)', color: 'var(--text-3)',
  border: '1px solid var(--border)', borderRadius: 8,
  fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
};

// ── Main modal ──────────────────────────────────────────────────────────
function ClientDetailModal({ clientKey, onClose, onSaved }) {
  const [tab, setTab] = React.useState('basic');
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [saveError, setSaveError] = React.useState(null);
  const [validationErrors, setValidationErrors] = React.useState([]);

  // Original record from GET (frozen reference for diff)
  const [original, setOriginal] = React.useState(null);
  // Working copy (editable)
  const [form, setForm] = React.useState({});

  // Sub-resources — shipping addresses + carrier accounts (V1 parity)
  const [shippingAddrs, setShippingAddrs] = React.useState([]);
  const [addrLoading, setAddrLoading]     = React.useState(false);
  const [addrError, setAddrError]         = React.useState(null);
  const [addrForm, setAddrForm]           = React.useState(null); // null=hidden, {}=add, {id,...}=edit
  const [addrSaving, setAddrSaving]       = React.useState(false);

  const [carrierAccts, setCarrierAccts]   = React.useState([]);
  const [carrierLoading, setCarrierLoading] = React.useState(false);
  const [carrierError, setCarrierError]     = React.useState(null);
  const [carrierForm, setCarrierForm]       = React.useState(null);
  const [carrierSaving, setCarrierSaving]   = React.useState(false);

  // Operator dictionaries — human labels for VAT modes, languages, series.
  const [dicts, setDicts] = React.useState({
    vat_modes: [], currencies: [], languages: [],
    invoice_series: [], proforma_series: [],
    source_state: {}, fetched_at: null,
  });
  const [dictRefreshing, setDictRefreshing] = React.useState(false);

  const _applyDicts = (d) => setDicts({
    vat_modes:       d.vat_modes       || [],
    currencies:      d.currencies      || [],
    languages:       d.languages       || [],
    invoice_series:  d.invoice_series  || [],
    proforma_series: d.proforma_series || [],
    source_state:    d.source_state    || {},
    fetched_at:      d.fetched_at      || null,
  });

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

  // ── Load dictionaries once ──────────────────────────────────────────
  React.useEffect(() => {
    PzApi.getCustomerDictionaries()
      .then(res => { if (res.ok && res.data) _applyDicts(res.data); })
      .catch(() => { /* keep empty defaults — operator can still hand-edit IDs */ });
  }, []);

  const contractorId = (original && original.bill_to_contractor_id) || clientKey;

  // ── Load sub-resources ──────────────────────────────────────────────
  const refreshAddrs = React.useCallback(() => {
    if (!contractorId) return;
    PzApi.listShippingAddresses(contractorId)
      .then(res => { if (res.ok) setShippingAddrs((res.data && res.data.addresses) || []); })
      .catch(() => {});
  }, [contractorId]);

  const refreshCarriers = React.useCallback(() => {
    if (!contractorId) return;
    PzApi.listCarrierAccounts(contractorId)
      .then(res => { if (res.ok) setCarrierAccts((res.data && res.data.accounts) || []); })
      .catch(() => {});
  }, [contractorId]);

  React.useEffect(() => {
    if (!contractorId) return;
    setAddrLoading(true);
    PzApi.listShippingAddresses(contractorId)
      .then(res => {
        if (res.ok) { setShippingAddrs((res.data && res.data.addresses) || []); setAddrError(null); }
        else setAddrError(res.error || 'Failed to load addresses');
      })
      .catch(e => setAddrError(String(e)))
      .finally(() => setAddrLoading(false));

    setCarrierLoading(true);
    PzApi.listCarrierAccounts(contractorId)
      .then(res => {
        if (res.ok) { setCarrierAccts((res.data && res.data.accounts) || []); setCarrierError(null); }
        else setCarrierError(res.error || 'Failed to load carrier accounts');
      })
      .catch(e => setCarrierError(String(e)))
      .finally(() => setCarrierLoading(false));
  }, [contractorId]);

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

  // ── Compute changed fields (partial PUT — V2 backend contract) ──────
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
  const canSave = !!contractorId;

  // ── Save handler ────────────────────────────────────────────────────
  // V1 behaviour: Save writes immediately. Operator ruling 2026-07-20 —
  // a Customer Master edit is not an irreversible financial operation;
  // validation, dirty-state and save-error handling are sufficient. Confirm
  // dialogs are reserved for genuinely irreversible / financial actions.
  const handleSave = () => {
    if (!hasChanges || !canSave) return;
    setSaving(true);
    setSaveError(null);
    setValidationErrors([]);

    PzApi.saveCustomerMaster(clientKey, changedFields).then(res => {
      if (res.ok) {
        if (onSaved) onSaved();
        onClose();
      } else {
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

  // ── Shipping address handlers ───────────────────────────────────────
  const handleAddrSave = () => {
    if (!addrForm || !contractorId) return;
    setAddrSaving(true);
    const p = addrForm.id
      ? PzApi.updateShippingAddress(contractorId, addrForm.id, addrForm)
      : PzApi.createShippingAddress(contractorId, addrForm);
    p.then(res => {
      if (res.ok) { setAddrForm(null); setAddrError(null); refreshAddrs(); }
      else setAddrError(res.error || 'Save failed');
    }).catch(e => setAddrError(String(e)))
      .finally(() => setAddrSaving(false));
  };

  const handleAddrDelete = (addrId) => {
    if (!contractorId) return;
    PzApi.deleteShippingAddress(contractorId, addrId).then(res => {
      if (res.ok) refreshAddrs();
      else setAddrError(res.error || 'Delete failed');
    }).catch(e => setAddrError(String(e)));
  };

  // ── Carrier account handlers ────────────────────────────────────────
  const handleCarrierSave = () => {
    if (!carrierForm || !contractorId) return;
    setCarrierSaving(true);
    const p = carrierForm.id
      ? PzApi.updateCarrierAccount(contractorId, carrierForm.id, carrierForm)
      : PzApi.createCarrierAccount(contractorId, carrierForm);
    p.then(res => {
      if (res.ok) { setCarrierForm(null); setCarrierError(null); refreshCarriers(); }
      else setCarrierError(res.error || 'Save failed');
    }).catch(e => setCarrierError(String(e)))
      .finally(() => setCarrierSaving(false));
  };

  const handleCarrierDelete = (acctId) => {
    if (!contractorId) return;
    PzApi.deleteCarrierAccount(contractorId, acctId).then(res => {
      if (res.ok) refreshCarriers();
      else setCarrierError(res.error || 'Delete failed');
    }).catch(e => setCarrierError(String(e)));
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

  // ── Render helpers (V1 label/input markup) ──────────────────────────
  const inp = (field, opts) => {
    const { placeholder, type, maxLength, testid } = opts || {};
    return <input data-testid={testid || 'cd-' + field} type={type || 'text'}
      style={_cdInputStyle} value={val(field)} placeholder={placeholder || ''}
      maxLength={maxLength}
      onChange={e => set(field, e.target.value)} />;
  };

  const sel = (field, options, opts) => {
    const { testid, blank } = opts || {};
    return (
      <select data-testid={testid || 'cd-' + field} style={_cdInputStyle}
        value={val(field)} onChange={e => set(field, e.target.value)}>
        {blank !== false && <option value="">{blank || '—'}</option>}
        {options.map(o => (typeof o === 'string'
          ? <option key={o} value={o}>{o}</option>
          : <option key={o.value} value={o.value}>{o.label}</option>))}
      </select>
    );
  };

  const fld = (label, node, opts) => {
    const { span, hint } = opts || {};
    return (
      <label style={span ? { ..._cdLabelStyle, gridColumn: '1 / -1' } : _cdLabelStyle}>
        <span style={_cdLabelTextStyle}>
          {label}
          {hint && <span style={{ fontSize: 9, color: 'var(--text-3)' }}> {hint}</span>}
        </span>
        {node}
      </label>
    );
  };

  const req = <span style={{ color: 'var(--badge-red-text)' }}>*</span>;

  const shipAlt = boolVal('ship_to_use_alternate');

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1200, background: 'var(--overlay)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
         onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div data-testid="client-detail-modal"
           style={{ background: 'var(--card)', borderRadius: 12, width: '100%', maxWidth: 760,
                    maxHeight: '90vh', display: 'flex', flexDirection: 'column',
                    boxShadow: '0 20px 60px var(--shadow-heavy)' }}>

        {/* ── Header (V1) ─────────────────────────────────────────── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px',
                      borderBottom: '1px solid var(--border)' }}>
          <div style={{ flex: 1 }}>
            <div data-testid="client-detail-modal-title"
              style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.01em' }}>
              {form.bill_to_name || (original && original.bill_to_name) || 'Client'}
            </div>
            <div data-testid="client-detail-modal-subtitle"
              style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 3, letterSpacing: '0.02em' }}>
              Company &middot; Shipping &middot; Carriers &middot; KYC &middot; Credit &middot; Invoices
              {contractorId && (
                <span style={{ marginLeft: 10, fontFamily: 'monospace', opacity: 0.8 }}>
                  · wFirma {contractorId}
                </span>
              )}
            </div>
          </div>
          {!contractorId && (
            <span style={{ fontSize: 10, color: 'var(--badge-amber-text)',
              background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
              borderRadius: 10, padding: '2px 8px', fontWeight: 700 }}>No contractor ID — read only</span>
          )}
          <button data-testid="cd-close" onClick={onClose}
            aria-label="Close"
            style={{ background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-3)', fontSize: 18, lineHeight: 1, padding: 4 }}>✕</button>
        </div>

        {/* ── Tab strip (V1) ──────────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 2, padding: '0 20px',
                      borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)',
                      flexWrap: 'wrap' }}>
          {_CD_TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              data-testid={'cd-tab-' + t.id}
              style={{ padding: '10px 14px', fontSize: 11,
                fontWeight: tab === t.id ? 700 : 500,
                color: tab === t.id ? 'var(--accent)' : 'var(--text-2)',
                background: 'none', border: 'none',
                borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
                cursor: 'pointer', fontFamily: 'inherit', marginBottom: -1, whiteSpace: 'nowrap' }}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Body ────────────────────────────────────────────────── */}
        <div style={{ overflowY: 'auto', flex: 1, padding: '14px 20px' }}>

          {loading && (
            <div data-testid="cd-loading" style={{ textAlign: 'center', padding: 48, color: 'var(--text-3)' }}>
              Loading customer data...
            </div>
          )}

          {error && (
            <div data-testid="cd-error" style={{
              padding: 16, background: 'var(--badge-red-bg)',
              border: '1px solid var(--badge-red-border)', borderRadius: 6,
              color: 'var(--badge-red-text)', fontSize: 12,
            }}>
              {error}
            </div>
          )}

          {validationErrors.length > 0 && (
            <div data-testid="cd-validation-errors" style={{
              padding: 12, marginBottom: 12,
              background: 'var(--badge-red-bg)',
              border: '1px solid var(--badge-red-border)', borderRadius: 6,
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

          {/* ── Company / Basic tab ───────────────────────────────── */}
          {!loading && !error && tab === 'basic' && (
            <div data-testid="cd-panel-basic">
              <div style={{ ..._cdSectionHeadStyle, marginTop: 0 }}>Company / Identity</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {fld(<>Company name {req}</>, inp('bill_to_name', { testid: 'cd-bill_to_name' }))}
                {fld(<>Country (ISO alpha-2) {req}</>,
                  inp('country', { placeholder: 'e.g. IN', maxLength: 2 }))}
                {fld('Short code',
                  inp('short_code', { placeholder: 'Short operator code (any country)' }))}
                {fld('Client type', sel('client_type', [
                  { value: 'company',    label: 'Company' },
                  { value: 'individual', label: 'Individual' },
                  { value: 'government', label: 'Government' },
                  { value: 'other',      label: 'Other' },
                ]))}
                {fld('Industry', inp('industry', { placeholder: 'Industry sector' }))}
                {fld('Default currency', sel('default_currency',
                  ['EUR','USD','GBP','PLN','CHF','SEK','JPY','CAD','AUD','INR'], { blank: false }))}
              </div>

              <div style={_cdSectionHeadStyle}>Billing address</div>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 10 }}>
                {fld('Street', inp('bill_to_street', { placeholder: 'Street / no. / suite' }))}
                {fld('Postal code', inp('bill_to_postal_code', { placeholder: 'Any country format' }))}
                {fld('City', inp('bill_to_city'))}
              </div>
              {/* NOTE — no Bank account field here, deliberately.
                  V1 (ClientKycModal) has none, and the pre-parity V2 field was
                  non-functional: upsert_customer()'s payload dict in
                  customer_master_db.py omits bank_account, so the PUT route
                  accepts the value, returns 200, bumps updated_at and silently
                  drops it (verified in-browser 2026-07-20 — the column, the
                  dataclass, the route allowlist and the GET all support it;
                  only the write payload is missing it). Rendering an input that
                  discards what the operator types is fake readiness. Restore
                  this field only together with the backend fix. */}

              <div style={_cdSectionHeadStyle}>Contact</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                {fld('Email',  inp('bill_to_email',  { type: 'email' }))}
                {fld('Phone',  inp('bill_to_phone',  { type: 'tel' }))}
                {fld('Mobile', inp('bill_to_mobile', { type: 'tel' }))}
              </div>

              <div style={_cdSectionHeadStyle}>VAT / Tax numbers</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {fld('Tax / VAT ID (local)',
                  inp('nip', { placeholder: 'Local tax / VAT identifier' }))}
                {fld('VAT EU number',
                  inp('vat_eu_number', { placeholder: 'e.g. DE123456789' }))}
                {fld('EORI number',
                  inp('eori', { placeholder: 'e.g. GB123456789000' }), { hint: '(optional)' })}
                {fld('REGON',
                  inp('regon', { placeholder: '9-digit REGON if PL' }), { hint: '(PL only · optional)' })}
              </div>

              <div style={_cdSectionHeadStyle}>Notes</div>
              <textarea data-testid="cd-notes"
                value={val('notes')} onChange={e => set('notes', e.target.value)}
                style={{ ..._cdInputStyle, height: 70, resize: 'vertical', fontFamily: 'inherit' }}
                placeholder="Internal notes…" />

              {/* V2 capability with no V1 tab — read-only record metadata. */}
              <details data-testid="cd-record-meta" style={{ marginTop: 14 }}>
                <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--text-3)' }}>
                  Advanced · Record metadata (read-only)
                </summary>
                <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: '6px 12px', marginTop: 8 }}>
                  {[
                    ['wFirma Contractor ID', val('bill_to_contractor_id'), 'cd-ro-contractor-id'],
                    ['Last wFirma sync', fmtTs(form.last_wfirma_sync_at), 'cd-ro-last-sync'],
                    ['Sync source', val('wfirma_sync_source') || '--', 'cd-ro-sync-source'],
                    ['Created', fmtTs(form.created_at), 'cd-ro-created'],
                    ['Updated', fmtTs(form.updated_at), 'cd-ro-updated'],
                    ['DB ID', val('id') || '--', 'cd-ro-id'],
                  ].map(([label, value, testid]) => (
                    <React.Fragment key={testid}>
                      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', padding: '4px 0' }}>
                        {label}
                      </div>
                      <div data-testid={testid} style={{
                        fontSize: 11, fontFamily: 'monospace', color: 'var(--text)',
                        padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
                        wordBreak: 'break-word',
                      }}>
                        {value}
                      </div>
                    </React.Fragment>
                  ))}
                </div>
              </details>
            </div>
          )}

          {/* ── Shipping tab ──────────────────────────────────────── */}
          {!loading && !error && tab === 'shipping' && (
            <div data-testid="cd-panel-shipping">
              <div style={{ ..._cdSectionHeadStyle, marginTop: 0 }}>Bill-to address (from Client Master)</div>
              <div data-testid="cd-shipping-bill-to-summary"
                style={{ padding: '12px 14px', background: 'var(--bg-subtle)',
                  border: '1px solid var(--border-subtle)', borderRadius: 6,
                  fontSize: 11, color: 'var(--text-2)', display: 'grid',
                  gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                <div><strong style={{ color: 'var(--text)' }}>{val('bill_to_name') || '—'}</strong></div>
                <div style={{ textAlign: 'right', fontFamily: 'monospace' }}>{contractorId || '—'}</div>
                <div style={{ gridColumn: '1 / -1' }}>{val('bill_to_street') || <em style={{ color: 'var(--text-3)' }}>street not set</em>}</div>
                <div>{[val('bill_to_postal_code'), val('bill_to_city')].filter(Boolean).join(' ') || <em style={{ color: 'var(--text-3)' }}>postal / city not set</em>}</div>
                <div style={{ textAlign: 'right' }}>{val('country') || '—'}</div>
                <div>{val('bill_to_email') || <em style={{ color: 'var(--text-3)' }}>email not set</em>}</div>
                <div style={{ textAlign: 'right' }}>{val('bill_to_phone') || <em style={{ color: 'var(--text-3)' }}>phone not set</em>}</div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, marginBottom: 10 }}>
                <div style={{ ..._cdSectionHeadStyle, marginTop: 0, marginBottom: 0, flex: 1 }}>
                  Ship-to address
                </div>
                <button data-testid="cd-shipping-copy-billing" type="button"
                  onClick={() => {
                    setForm(f => ({
                      ...f,
                      ship_to_use_alternate: true,
                      ship_to_name:    f.ship_to_name    || f.bill_to_name        || '',
                      ship_to_country: f.ship_to_country || f.country             || '',
                      ship_to_street:  f.ship_to_street  || f.bill_to_street      || '',
                      ship_to_city:    f.ship_to_city    || f.bill_to_city        || '',
                      ship_to_zip:     f.ship_to_zip     || f.bill_to_postal_code || '',
                      ship_to_email:   f.ship_to_email   || f.bill_to_email       || '',
                      ship_to_phone:   f.ship_to_phone   || f.bill_to_phone       || '',
                    }));
                    setSaveError(null);
                  }}
                  title="Pre-fill ship-to fields from the billing identity (works for any country)"
                  style={{ padding: '4px 10px', fontSize: 11, background: 'var(--bg-subtle)',
                    color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6,
                    cursor: 'pointer', fontFamily: 'inherit' }}>
                  Copy billing address
                </button>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                  <input data-testid="cd-ship_to_use_alternate" type="checkbox"
                    checked={shipAlt}
                    onChange={() => toggleBool('ship_to_use_alternate')} />
                  Use alternate ship-to address
                </label>
              </div>

              {!shipAlt && (
                <div data-testid="cd-shipping-inheritance-hint"
                  style={{ padding: '8px 12px', background: 'var(--bg-subtle)',
                    border: '1px dashed var(--border)', borderRadius: 6,
                    fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>
                  Ship-to inherits the billing address shown above (name,
                  street, city, postal code, country, email, phone). Toggle
                  <em> Use alternate ship-to address</em> on the right to
                  override.
                </div>
              )}

              <div data-testid="cd-shipto-fields"
                style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10,
                         opacity: shipAlt ? 1 : 0.5 }}>
                {fld('Company name',
                  <input data-testid="cd-ship_to_name" type="text" style={_cdInputStyle}
                    value={val('ship_to_name')} disabled={!shipAlt}
                    onChange={e => set('ship_to_name', e.target.value)} />)}
                {fld('Contact person',
                  <input data-testid="cd-ship_to_person" type="text" style={_cdInputStyle}
                    value={val('ship_to_person')} disabled={!shipAlt}
                    onChange={e => set('ship_to_person', e.target.value)} />)}
                {fld('Street address',
                  <input data-testid="cd-ship_to_street" type="text" style={_cdInputStyle}
                    value={val('ship_to_street')} disabled={!shipAlt}
                    onChange={e => set('ship_to_street', e.target.value)} />, { span: true })}
                {fld('City',
                  <input data-testid="cd-ship_to_city" type="text" style={_cdInputStyle}
                    value={val('ship_to_city')} disabled={!shipAlt}
                    onChange={e => set('ship_to_city', e.target.value)} />)}
                {fld('ZIP / Postal code',
                  <input data-testid="cd-ship_to_zip" type="text" style={_cdInputStyle}
                    value={val('ship_to_zip')} disabled={!shipAlt}
                    onChange={e => set('ship_to_zip', e.target.value)} />)}
                {fld('Country (ISO alpha-2)',
                  <input data-testid="cd-ship_to_country" type="text" style={_cdInputStyle}
                    value={val('ship_to_country')} disabled={!shipAlt} maxLength={2}
                    onChange={e => set('ship_to_country', e.target.value)} />)}
                {fld('Phone',
                  <input data-testid="cd-ship_to_phone" type="text" style={_cdInputStyle}
                    value={val('ship_to_phone')} disabled={!shipAlt}
                    onChange={e => set('ship_to_phone', e.target.value)} />)}
                {fld('Email',
                  <input data-testid="cd-ship_to_email" type="email" style={_cdInputStyle}
                    value={val('ship_to_email')} disabled={!shipAlt}
                    onChange={e => set('ship_to_email', e.target.value)} />)}
              </div>

              {/* Saved delivery addresses (V1) */}
              <div style={{ marginTop: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={_cdSubHeadStyle}>Saved delivery addresses</div>
                  <button data-testid="cd-shipping-add-btn"
                    onClick={() => setAddrForm({ label: '', name: '', person: '', street: '',
                      city: '', zip: '', country: '', phone: '', email: '', is_default: false })}
                    disabled={!!addrForm}
                    style={_cdAddBtnStyle}>
                    + Add address
                  </button>
                </div>
                {addrError && <div style={_cdErrorBoxStyle}>{addrError}</div>}
                {addrLoading && (
                  <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '6px 0' }}>Loading addresses…</div>
                )}
                <div data-testid="cd-shipping-addr-list">
                  {shippingAddrs.map(addr => (
                    <div key={addr.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                      padding: '7px 10px', background: 'var(--bg-subtle)',
                      border: '1px solid var(--border-subtle)', borderRadius: 5, marginBottom: 5 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
                          {addr.label}
                          {addr.is_default && <span style={_cdDefaultPillStyle}>default</span>}
                        </div>
                        <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 2 }}>
                          {[addr.name, addr.street, addr.city, addr.zip, addr.country].filter(Boolean).join(', ')}
                        </div>
                      </div>
                      <button data-testid={'cd-shipping-addr-' + addr.id + '-edit'}
                        onClick={() => setAddrForm({ ...addr })} style={_cdRowBtnStyle}>
                        Edit
                      </button>
                      <button data-testid={'cd-shipping-addr-' + addr.id + '-delete'}
                        onClick={() => handleAddrDelete(addr.id)} style={_cdRowBtnStyle}>
                        ×
                      </button>
                    </div>
                  ))}
                  {!addrLoading && shippingAddrs.length === 0 && (
                    <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '8px 0' }}>
                      No saved delivery addresses yet.
                    </div>
                  )}
                </div>
                {addrForm !== null && (
                  <div style={{ marginTop: 12, padding: '12px', background: 'var(--card)',
                    border: '1px solid var(--border)', borderRadius: 6 }}>
                    <div style={{ ..._cdSubHeadStyle, flex: 'none', marginBottom: 8 }}>
                      {addrForm.id ? 'Edit address' : 'New address'}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                      <label style={{ ..._cdLabelStyle, gridColumn: '1 / -1' }}>
                        <span style={_cdLabelTextStyle}>Label *</span>
                        <input data-testid="cd-shipping-addr-form-label" type="text"
                          value={addrForm.label || ''}
                          onChange={e => setAddrForm(f => ({ ...f, label: e.target.value }))}
                          style={_cdInputStyle} placeholder="e.g. Main warehouse" />
                      </label>
                      <label style={_cdLabelStyle}>
                        <span style={_cdLabelTextStyle}>Company name</span>
                        <input type="text" value={addrForm.name || ''}
                          onChange={e => setAddrForm(f => ({ ...f, name: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={_cdLabelStyle}>
                        <span style={_cdLabelTextStyle}>Contact person</span>
                        <input type="text" value={addrForm.person || ''}
                          onChange={e => setAddrForm(f => ({ ...f, person: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={{ ..._cdLabelStyle, gridColumn: '1 / -1' }}>
                        <span style={_cdLabelTextStyle}>Street</span>
                        <input type="text" value={addrForm.street || ''}
                          onChange={e => setAddrForm(f => ({ ...f, street: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={_cdLabelStyle}>
                        <span style={_cdLabelTextStyle}>City</span>
                        <input type="text" value={addrForm.city || ''}
                          onChange={e => setAddrForm(f => ({ ...f, city: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={_cdLabelStyle}>
                        <span style={_cdLabelTextStyle}>ZIP</span>
                        <input type="text" value={addrForm.zip || ''}
                          onChange={e => setAddrForm(f => ({ ...f, zip: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={_cdLabelStyle}>
                        <span style={_cdLabelTextStyle}>Country (ISO alpha-2)</span>
                        <input type="text" value={addrForm.country || ''}
                          onChange={e => setAddrForm(f => ({ ...f, country: e.target.value.toUpperCase() }))}
                          maxLength={2} style={_cdInputStyle} placeholder="DE" />
                      </label>
                      <label style={_cdLabelStyle}>
                        <span style={_cdLabelTextStyle}>Phone</span>
                        <input type="text" value={addrForm.phone || ''}
                          onChange={e => setAddrForm(f => ({ ...f, phone: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={{ ..._cdLabelStyle, gridColumn: '1 / -1' }}>
                        <span style={_cdLabelTextStyle}>Email</span>
                        <input type="email" value={addrForm.email || ''}
                          onChange={e => setAddrForm(f => ({ ...f, email: e.target.value }))}
                          style={_cdInputStyle} />
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, gridColumn: '1 / -1' }}>
                        <input type="checkbox" checked={!!addrForm.is_default}
                          onChange={e => setAddrForm(f => ({ ...f, is_default: e.target.checked }))} />
                        Set as default delivery address
                      </label>
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <button data-testid="cd-shipping-addr-form-save"
                        onClick={handleAddrSave} disabled={addrSaving}
                        style={{ padding: '4px 14px', fontSize: 11, cursor: 'pointer',
                          background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4 }}>
                        {addrSaving ? 'Saving…' : 'Save'}
                      </button>
                      <button onClick={() => { setAddrForm(null); setAddrError(null); }}
                        style={{ padding: '4px 14px', fontSize: 11, cursor: 'pointer',
                          background: 'none', border: '1px solid var(--border)', borderRadius: 4,
                          color: 'var(--text-2)' }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Shape B — wFirma receiver. V2 capability, no V1 tab. */}
              <div data-testid="cd-shapeb-section" style={{
                marginTop: 16, border: '1px solid var(--border)', borderRadius: 6,
                padding: 12, background: 'var(--bg-subtle)',
              }}>
                <div style={{ ..._cdSubHeadStyle, flex: 'none', marginBottom: 6 }}>wFirma Receiver</div>
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 8 }}>
                  Separate wFirma contractor used as invoice receiver. Does NOT affect DHL delivery address.
                </div>
                {fld('wFirma Receiver contractor ID',
                  inp('ship_to_contractor_id', { placeholder: 'wFirma contractor ID (optional)' }))}
              </div>
            </div>
          )}

          {/* ── Carriers tab ──────────────────────────────────────── */}
          {!loading && !error && tab === 'carriers' && (
            <div data-testid="cd-panel-carriers">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <div style={_cdSubHeadStyle}>DHL Express accounts</div>
                <button data-testid="cd-carriers-add-btn"
                  onClick={() => setCarrierForm({ carrier: 'dhl', account_number: '',
                    account_name: '', payment_type: '', service_level: '', is_default: false })}
                  disabled={!!carrierForm}
                  style={_cdAddBtnStyle}>
                  + Add account
                </button>
              </div>
              {carrierError && <div style={_cdErrorBoxStyle}>{carrierError}</div>}
              {carrierLoading && (
                <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '6px 0' }}>Loading carrier accounts…</div>
              )}
              <div data-testid="cd-carriers-list">
                {carrierAccts.map(acct => (
                  <div key={acct.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                    padding: '7px 10px', background: 'var(--bg-subtle)',
                    border: '1px solid var(--border-subtle)', borderRadius: 5, marginBottom: 5 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ textTransform: 'uppercase' }}>{acct.carrier}</span>
                        <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-2)' }}>
                          {acct.account_number}
                        </span>
                        {acct.is_default && (
                          <span style={_cdDefaultPillStyle}
                            data-testid={'cd-carriers-acct-' + acct.id + '-default'}>
                            default shipping
                          </span>
                        )}
                        {/* Active is READ-ONLY here on purpose. update_account()
                            writes carrier / account_number / account_name /
                            payment_type / service_level / is_default only — the
                            `active` column is owned by the delete (soft-delete)
                            and restore endpoints. An editable Active control
                            would silently discard the operator's click. */}
                        {acct.active === false && (
                          <span style={_cdInactivePillStyle}
                            data-testid={'cd-carriers-acct-' + acct.id + '-inactive'}>
                            inactive
                          </span>
                        )}
                      </div>
                      {(acct.account_name || acct.payment_type) && (
                        <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 2 }}
                          data-testid={'cd-carriers-acct-' + acct.id + '-meta'}>
                          {[acct.account_name, _cdBillingRoleLabel(acct.payment_type)]
                            .filter(Boolean).join(' · ')}
                        </div>
                      )}
                    </div>
                    <button data-testid={'cd-carriers-acct-' + acct.id + '-edit'}
                      onClick={() => setCarrierForm({ ...acct })} style={_cdRowBtnStyle}>
                      Edit
                    </button>
                    <button data-testid={'cd-carriers-acct-' + acct.id + '-delete'}
                      onClick={() => handleCarrierDelete(acct.id)} style={_cdRowBtnStyle}>
                      ×
                    </button>
                  </div>
                ))}
                {!carrierLoading && carrierAccts.length === 0 && (
                  <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '8px 0' }}>
                    No carrier accounts configured yet.
                  </div>
                )}
              </div>
              {carrierForm !== null && (
                <div style={{ marginTop: 12, padding: '12px', background: 'var(--card)',
                  border: '1px solid var(--border)', borderRadius: 6 }}>
                  <div style={{ ..._cdSubHeadStyle, flex: 'none', marginBottom: 8 }}>
                    {carrierForm.id ? 'Edit carrier account' : 'New carrier account'}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <label style={_cdLabelStyle}>
                      <span style={_cdLabelTextStyle}>Carrier *</span>
                      <select data-testid="cd-carriers-form-carrier"
                        value={carrierForm.carrier || 'dhl'}
                        onChange={e => setCarrierForm(f => ({ ...f, carrier: e.target.value }))}
                        style={{ ..._cdInputStyle, padding: '4px 8px' }}>
                        <option value="dhl">DHL</option>
                        <option value="fedex">FedEx</option>
                        <option value="ups">UPS</option>
                        <option value="other">Other</option>
                      </select>
                    </label>
                    <label style={_cdLabelStyle}>
                      <span style={_cdLabelTextStyle}>Account number *</span>
                      <input data-testid="cd-carriers-form-account-number" type="text"
                        value={carrierForm.account_number || ''}
                        onChange={e => setCarrierForm(f => ({ ...f, account_number: e.target.value }))}
                        style={_cdInputStyle} />
                    </label>
                    <label style={_cdLabelStyle}>
                      <span style={_cdLabelTextStyle}>Account name</span>
                      <input type="text" value={carrierForm.account_name || ''}
                        onChange={e => setCarrierForm(f => ({ ...f, account_name: e.target.value }))}
                        style={_cdInputStyle} />
                    </label>
                    <label style={_cdLabelStyle}>
                      <span style={_cdLabelTextStyle}>Billing role</span>
                      {/* Business labels only — the STORED payment_type values
                          (shipper / receiver / third_party) are unchanged.
                          Billing role is the account's billing function; it is a
                          separate concept from "Default shipping account"
                          (is_default) and neither infers the other. */}
                      <select data-testid="cd-carriers-form-billing-role"
                        value={carrierForm.payment_type || ''}
                        onChange={e => setCarrierForm(f => ({ ...f, payment_type: e.target.value }))}
                        style={{ ..._cdInputStyle, padding: '4px 8px' }}>
                        <option value="">— none —</option>
                        <option value="shipper">Sender</option>
                        <option value="receiver">Receiver</option>
                        <option value="third_party">Third party</option>
                      </select>
                    </label>
                    <label style={{ ..._cdLabelStyle, gridColumn: '1 / -1' }}>
                      <span style={_cdLabelTextStyle}>Service level</span>
                      <input type="text" value={carrierForm.service_level || ''}
                        onChange={e => setCarrierForm(f => ({ ...f, service_level: e.target.value }))}
                        style={_cdInputStyle} placeholder="e.g. EXPRESS_WORLDWIDE" />
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, gridColumn: '1 / -1' }}>
                      <input type="checkbox" checked={!!carrierForm.is_default}
                        onChange={e => setCarrierForm(f => ({ ...f, is_default: e.target.checked }))} />
                      Default shipping account
                    </label>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                    <button data-testid="cd-carriers-form-save"
                      onClick={handleCarrierSave} disabled={carrierSaving}
                      style={{ padding: '4px 14px', fontSize: 11, cursor: 'pointer',
                        background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4 }}>
                      {carrierSaving ? 'Saving…' : 'Save'}
                    </button>
                    <button onClick={() => { setCarrierForm(null); setCarrierError(null); }}
                      style={{ padding: '4px 14px', fontSize: 11, cursor: 'pointer',
                        background: 'none', border: '1px solid var(--border)', borderRadius: 4,
                        color: 'var(--text-2)' }}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── KYC / Compliance tab ──────────────────────────────── */}
          {!loading && !error && tab === 'kyc' && (
            <div data-testid="cd-panel-kyc">
              <div style={{ ..._cdSectionHeadStyle, marginTop: 0 }}>KYC Status</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {fld('KYC Status', sel('kyc_status', ['approved','pending','review','rejected']))}
                {fld('Approved on', inp('kyc_approved_on', { type: 'date' }))}
                {fld('Expiry date', inp('kyc_expiry', { type: 'date' }))}
                {fld('Beneficial owner', inp('beneficial_owner'))}
                {fld('Owner ID type', sel('owner_id_type', ['passport','id_card','drivers_license']))}
                {fld('Owner ID number', inp('owner_id_number'))}
                {fld('AML risk rating', sel('aml_risk_rating', ['low','medium','high']))}
                {fld('PEP check result',
                  sel('pep_check_result', ['clear','flagged','pending'],
                      { testid: 'cd-pep-check-result' }), { span: true })}
                {fld('Compliance notes',
                  <textarea data-testid="cd-compliance-notes"
                    value={val('compliance_notes')}
                    onChange={e => set('compliance_notes', e.target.value)}
                    style={{ ..._cdInputStyle, height: 60, resize: 'vertical' }} />, { span: true })}
              </div>
            </div>
          )}

          {/* ── KUKE & Credit tab ─────────────────────────────────── */}
          {!loading && !error && tab === 'kuke' && (
            <div data-testid="cd-panel-kuke">
              <div style={{ ..._cdSectionHeadStyle, marginTop: 0 }}>KUKE Insurance</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label style={{ ..._cdLabelStyle, gridColumn: '1 / -1',
                  flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                  <input data-testid="cd-kuke_approved" type="checkbox"
                    checked={boolVal('kuke_approved')}
                    onChange={() => toggleBool('kuke_approved')} />
                  <span style={{ fontSize: 12, fontWeight: 600 }}>KUKE insurance approved</span>
                </label>
                {fld('KUKE limit', inp('kuke_limit', { placeholder: 'e.g. 50000.00' }))}
                {fld('Currency', sel('kuke_currency', ['EUR','USD','PLN','GBP'], { blank: false }))}
                {fld('Expiry date', inp('kuke_expiry_date', { type: 'date' }))}
                {fld('Policy number', inp('kuke_policy_number', { placeholder: 'e.g. POL-2024-001' }))}
                {fld('Self-retention %', inp('kuke_self_retention_pct', { placeholder: 'e.g. 10' }))}
              </div>

              <div style={_cdSectionHeadStyle}>Credit</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {fld('Credit limit', inp('credit_limit', { placeholder: 'e.g. 100000.00' }))}
                {fld('Currency', sel('credit_currency', ['EUR','USD','PLN','GBP'], { blank: false }))}
                {fld('Payment terms (days)',
                  inp('payment_terms_days', { type: 'number', placeholder: 'e.g. 30',
                                              testid: 'cd-kuke-payment-terms' }))}
                {fld('Risk status', sel('risk_status', ['low','medium','high','blocked']))}
              </div>
            </div>
          )}

          {/* ── Invoices tab ──────────────────────────────────────── */}
          {!loading && !error && tab === 'invoices' && (
            <div data-testid="cd-panel-invoices">
              <div style={{ ..._cdSectionHeadStyle, marginTop: 0 }}>Document defaults</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label style={_cdLabelStyle}>
                  <span style={_cdLabelTextStyle}>VAT mode</span>
                  <select data-testid="cd-vat_mode"
                    value={val('vat_mode')}
                    onChange={e => set('vat_mode', e.target.value)}
                    style={_cdInputStyle}>
                    <option value="">—</option>
                    {(dicts.vat_modes.length > 0
                       ? dicts.vat_modes
                       : [{ id: 222, label: 'Standard (222)' },
                          { id: 228, label: 'Reverse charge (228)' },
                          { id: 229, label: 'Export 0% (229)' }]
                    ).map(m => (
                      <option key={m.id} value={String(m.id)}>{m.label}</option>
                    ))}
                  </select>
                </label>
                <label style={_cdLabelStyle}>
                  <span style={_cdLabelTextStyle}>Default language</span>
                  <select data-testid="cd-default_language_id"
                    value={val('default_language_id')}
                    onChange={e => set('default_language_id', e.target.value)}
                    style={_cdInputStyle}>
                    {dicts.languages.length > 0
                      ? dicts.languages.map(L => (
                          <option key={L.id || '_blank'} value={L.id}>{L.label}</option>
                        ))
                      : <option value="">— Default</option>}
                  </select>
                </label>
              </div>

              <div data-testid="cd-invoices-dict-refresh-row"
                style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14 }}>
                <button data-testid="cd-invoices-dict-refresh" type="button"
                  disabled={dictRefreshing}
                  onClick={() => {
                    setDictRefreshing(true);
                    PzApi.refreshCustomerDictionaries()
                      .then(res => { if (res.ok && res.data) _applyDicts(res.data); })
                      .catch(() => {})
                      .finally(() => setDictRefreshing(false));
                  }}
                  style={{ padding: '5px 12px', fontSize: 11, fontWeight: 600,
                    background: 'var(--bg-subtle)', color: 'var(--text)',
                    border: '1px solid var(--border)', borderRadius: 6,
                    cursor: dictRefreshing ? 'not-allowed' : 'pointer',
                    opacity: dictRefreshing ? 0.5 : 1, fontFamily: 'inherit' }}>
                  {dictRefreshing ? 'Refreshing…' : 'Refresh wFirma dictionaries'}
                </button>
                {dicts.source_state && (
                  <span data-testid="cd-invoices-dict-source-state"
                    style={{ fontSize: 10, color: 'var(--text-3)' }}>
                    invoice: <strong style={{ color: 'var(--text-2)' }}>{dicts.source_state.invoice_series || 'baseline'}</strong>
                    {' · '}proforma: <strong style={{ color: 'var(--text-2)' }}>{dicts.source_state.proforma_series || 'baseline'}</strong>
                    {dicts.fetched_at && <span> · fetched {dicts.fetched_at}</span>}
                  </span>
                )}
              </div>

              <details data-testid="cd-invoices-advanced" style={{ marginTop: 8 }}>
                <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--text-3)' }}>
                  Advanced · wFirma series IDs
                </summary>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8 }}>
                  <label style={_cdLabelStyle}>
                    <span style={_cdLabelTextStyle}>Preferred proforma series</span>
                    {dicts.proforma_series && dicts.proforma_series.length > 1 ? (
                      <select data-testid="cd-preferred_proforma_series_id"
                        value={val('preferred_proforma_series_id')}
                        onChange={e => set('preferred_proforma_series_id', e.target.value)}
                        style={_cdInputStyle}>
                        {dicts.proforma_series.map(s => (
                          <option key={s.id || '_blank'} value={s.id}>{s.label}</option>
                        ))}
                        {/* Unresolved-id fallback: keep the saved value visible when the
                            live catalog has not been refreshed in this process. */}
                        {val('preferred_proforma_series_id') &&
                         !dicts.proforma_series.some(s => String(s.id) === val('preferred_proforma_series_id')) && (
                          <option data-testid="cd-proforma-series-unresolved"
                            value={val('preferred_proforma_series_id')}>
                            Unknown wFirma series (#{val('preferred_proforma_series_id')})
                          </option>
                        )}
                      </select>
                    ) : (
                      <input data-testid="cd-preferred_proforma_series_id" type="text"
                        value={val('preferred_proforma_series_id')}
                        onChange={e => set('preferred_proforma_series_id', e.target.value)}
                        placeholder="wFirma series id (raw)"
                        title="Dictionary catalog not yet refreshed — enter raw wFirma id"
                        style={_cdInputStyle} />
                    )}
                  </label>
                  <label style={_cdLabelStyle}>
                    <span style={_cdLabelTextStyle}>Preferred invoice series</span>
                    {dicts.invoice_series && dicts.invoice_series.length > 1 ? (
                      <select data-testid="cd-preferred_invoice_series_id"
                        value={val('preferred_invoice_series_id')}
                        onChange={e => set('preferred_invoice_series_id', e.target.value)}
                        style={_cdInputStyle}>
                        {dicts.invoice_series.map(s => (
                          <option key={s.id || '_blank'} value={s.id}>{s.label}</option>
                        ))}
                        {val('preferred_invoice_series_id') &&
                         !dicts.invoice_series.some(s => String(s.id) === val('preferred_invoice_series_id')) && (
                          <option data-testid="cd-invoice-series-unresolved"
                            value={val('preferred_invoice_series_id')}>
                            Unknown wFirma series (#{val('preferred_invoice_series_id')})
                          </option>
                        )}
                      </select>
                    ) : (
                      <input data-testid="cd-preferred_invoice_series_id" type="text"
                        value={val('preferred_invoice_series_id')}
                        onChange={e => set('preferred_invoice_series_id', e.target.value)}
                        placeholder="wFirma series id (raw)"
                        title="Dictionary catalog not yet refreshed — enter raw wFirma id"
                        style={_cdInputStyle} />
                    )}
                  </label>
                </div>
              </details>

              <div style={_cdSectionHeadStyle}>Payment defaults</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {fld('Payment terms (days)',
                  inp('payment_terms_days', { type: 'number', placeholder: 'e.g. 30',
                                              testid: 'cd-payment_terms_days' }))}
                {fld('Preferred payment method',
                  <select data-testid="cd-preferred_payment_method"
                    value={val('preferred_payment_method')}
                    onChange={e => set('preferred_payment_method', e.target.value)}
                    style={_cdInputStyle}>
                    <option value=''>wFirma default</option>
                    <option value='transfer'>Transfer (przelew)</option>
                    <option value='cash'>Cash (gotówka)</option>
                    <option value='card'>Card (karta)</option>
                    <option value='compensation'>Compensation (kompensata)</option>
                  </select>)}
                {fld('Default currency',
                  sel('default_currency', ['EUR','USD','GBP','PLN','CHF','SEK'],
                      { blank: false, testid: 'cd-invoices-currency' }))}
              </div>

              {/* Freight defaults — V2 capability, no V1 tab. The backend
                  freight-authority deep-link targets these exact fields. */}
              <div style={_cdSectionHeadStyle}>Freight defaults</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                {fld('Mode', sel('freight_mode', ['no_data','fixed','variable','manual']))}
                {fld('Fixed amount (EUR)',
                  inp('freight_fixed_amount_eur', { type: 'number', placeholder: '0.00' }))}
                {fld('Fixed amount (USD)',
                  inp('freight_fixed_amount_usd', { type: 'number', placeholder: '0.00' }))}
                {fld('Currency', sel('freight_currency', ['EUR','PLN','USD']))}
                {fld('Label (PL)', inp('freight_label_pl', { placeholder: 'Fracht' }))}
                {fld('Label (EN)', inp('freight_label_en', { placeholder: 'Freight' }))}
                {fld('Freight service ID', inp('freight_service_id'))}
              </div>

              {/* Insurance defaults — V2 capability, no V1 tab. */}
              <div style={_cdSectionHeadStyle}>Insurance defaults</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                <label style={_cdLabelStyle}>
                  <span style={_cdLabelTextStyle}>Enabled</span>
                  <label data-testid="cd-insurance-enabled-toggle"
                    style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', paddingTop: 4 }}>
                    <input type="checkbox" data-testid="cd-insurance_enabled"
                      checked={boolVal('insurance_enabled')}
                      onChange={() => toggleBool('insurance_enabled')} />
                    <span style={{ fontSize: 11 }}>{boolVal('insurance_enabled') ? 'Yes' : 'No'}</span>
                  </label>
                </label>
                {fld('Mode', sel('insurance_mode', ['no_data','fixed','formula','manual']))}
                {fld('Rate (%)', inp('insurance_rate', { type: 'number', placeholder: '0.50' }))}
                {fld('Fixed (EUR)', inp('insurance_fixed_amount_eur', { type: 'number', placeholder: '0.00' }))}
                {fld('Fixed (USD)', inp('insurance_fixed_amount_usd', { type: 'number', placeholder: '0.00' }))}
                {fld('Min (EUR)', inp('insurance_min_eur', { type: 'number', placeholder: '0.00' }))}
                {fld('Min (USD)', inp('insurance_min_usd', { type: 'number', placeholder: '0.00' }))}
                {fld('Label (PL)', inp('insurance_label_pl', { placeholder: 'Ubezpieczenie' }))}
                {fld('Label (EN)', inp('insurance_label_en', { placeholder: 'Insurance' }))}
                {fld('Insurance service ID', inp('insurance_service_id'))}
              </div>

              <div style={{ marginTop: 14, padding: '8px 10px', background: 'var(--bg-subtle)',
                            border: '1px solid var(--border-subtle)', borderRadius: 4,
                            fontSize: 10, color: 'var(--text-3)' }}>
                Invoice &amp; proforma history per client is sourced from wFirma — read-only on this page.
              </div>
            </div>
          )}
        </div>

        {/* ── Footer (V1) ─────────────────────────────────────────── */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)',
                      display: 'flex', alignItems: 'center', gap: 10,
                      background: 'var(--bg-subtle)' }}>
          {saveError && (
            <div data-testid="cd-save-error"
                 style={{ flex: 1, padding: '5px 10px', background: 'var(--badge-red-bg)',
                   border: '1px solid var(--badge-red-border)', borderRadius: 4,
                   fontSize: 11, color: 'var(--badge-red-text)' }}>{saveError}</div>
          )}
          {!saveError && (
            <div data-testid="cd-change-count" style={{ flex: 1, fontSize: 11, color: 'var(--text-3)' }}>
              {hasChanges
                ? Object.keys(changedFields).length + ' field' + (Object.keys(changedFields).length === 1 ? '' : 's') + ' changed'
                : 'No changes'}
            </div>
          )}
          <button data-testid="cd-cancel" onClick={onClose}
            style={{ padding: '7px 16px', fontSize: 12, background: 'var(--card)',
              color: 'var(--text-2)', border: '1px solid var(--border)',
              borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit' }}>Cancel</button>
          <button data-testid="cd-save" onClick={handleSave}
            disabled={saving || loading || !canSave || !hasChanges}
            style={{ padding: '7px 20px', fontSize: 12, fontWeight: 700,
              background: (canSave && hasChanges) ? 'var(--accent)' : 'var(--bg-subtle)',
              color: (canSave && hasChanges) ? '#fff' : 'var(--text-3)',
              border: (canSave && hasChanges) ? 'none' : '1px solid var(--border)',
              borderRadius: 6,
              cursor: (saving || !canSave || !hasChanges) ? 'not-allowed' : 'pointer',
              fontFamily: 'inherit', opacity: saving ? 0.6 : 1 }}>
            {saving ? 'Saving…' : canSave ? 'Save' : 'No contractor ID'}
          </button>
        </div>
      </div>

    </div>
  );
}

Object.assign(window, { ClientDetailModal });
