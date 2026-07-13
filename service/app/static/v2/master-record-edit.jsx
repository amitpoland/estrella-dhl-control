// master-record-edit.jsx — Wave 7: generic capability-driven CRUD form modal.
//
// Exposed: MasterRecordEditModal({ domain, capability, columns, record, onClose, onSaved })
// Domains: hs, fx, vat, carriers, incoterms, units
// record=null → create mode; record=<object> → edit mode
// create_kind 'put'  → key field editable in create, READ-ONLY in edit (PUT upsert by code)
// create_kind 'post' → no key field rendered; create calls createX wrapper, edit calls saveX by id
// Credential fields (api_key/secret/password/token) are never rendered — backend rejects them.

// ── Field definitions per domain ────────────────────────────────────────────
// label: display label; key: data key; type: 'text'|'number'|'checkbox'
// isKey: true → this is the URL-level key (code/id); required: true → validate non-empty
const DOMAIN_FIELDS = {
  hs: [
    { key: 'hs_code',        label: 'HS Code *',            type: 'text',     isKey: true, required: true },
    { key: 'description_pl', label: 'Description (PL)',     type: 'text' },
    { key: 'description_en', label: 'Description (EN)',     type: 'text' },
    { key: 'duty_rate_pct',  label: 'Duty Rate %',          type: 'number' },
    { key: 'vat_rate_pct',   label: 'VAT Rate %',           type: 'number' },
    { key: 'active',         label: 'Active',               type: 'checkbox' },
  ],
  units: [
    { key: 'code',           label: 'Code *',               type: 'text',     isKey: true, required: true },
    { key: 'name_pl',        label: 'Name (PL)',            type: 'text' },
    { key: 'name_en',        label: 'Name (EN)',            type: 'text' },
    { key: 'unit_type',      label: 'Unit Type',            type: 'text' },
    { key: 'active',         label: 'Active',               type: 'checkbox' },
  ],
  incoterms: [
    { key: 'code',                label: 'Code *',                 type: 'text',     isKey: true, required: true },
    { key: 'name',                label: 'Name',                   type: 'text' },
    { key: 'risk_transfer_point', label: 'Risk Transfer Point',    type: 'text' },
    { key: 'freight_included',    label: 'Freight Included',       type: 'checkbox' },
    { key: 'insurance_included',  label: 'Insurance Included',     type: 'checkbox' },
    { key: 'customs_included',    label: 'Customs Included',       type: 'checkbox' },
    { key: 'active',              label: 'Active',                 type: 'checkbox' },
  ],
  carriers: [
    // NOTE: credential fields (api_key/secret/password/token) are intentionally excluded
    // — the backend rejects them and they must never be rendered here.
    { key: 'carrier_code',       label: 'Carrier Code *',          type: 'text',     isKey: true, required: true },
    { key: 'name',               label: 'Name',                    type: 'text' },
    { key: 'parser_type',        label: 'Parser Type',             type: 'text' },
    { key: 'api_type',           label: 'API Type',                type: 'text' },
    { key: 'inbox_email',        label: 'Inbox Email',             type: 'text' },
    { key: 'supported_services', label: 'Supported Services',      type: 'text' },
    { key: 'notes',              label: 'Notes',                   type: 'text' },
    { key: 'active',             label: 'Active',                  type: 'checkbox' },
  ],
  vat: [
    // create_kind = 'post'; vat_id is auto-assigned — NOT an input field
    { key: 'rate_code',    label: 'Rate Code *',         type: 'text',   required: true },
    { key: 'rate_pct',     label: 'Rate % *',            type: 'number', required: true },
    { key: 'country',      label: 'Country (ISO-2)',     type: 'text' },
    { key: 'product_type', label: 'Product Type',        type: 'text' },
    { key: 'active',       label: 'Active',              type: 'checkbox' },
  ],
  fx: [
    // create_kind = 'post'; fx_id is auto-assigned — NOT an input field
    { key: 'from_currency', label: 'From Currency *',        type: 'text',   required: true },
    { key: 'to_currency',   label: 'To Currency *',          type: 'text',   required: true },
    { key: 'rate',          label: 'Rate *',                 type: 'number', required: true },
    { key: 'rate_date',     label: 'Rate Date (YYYY-MM-DD)', type: 'text' },
    { key: 'source',        label: 'Source',                 type: 'text' },
    { key: 'active',        label: 'Active',                 type: 'checkbox' },
  ],
};

const DOMAIN_LABEL = {
  hs: 'HS Code',
  units: 'Unit',
  incoterms: 'Incoterm',
  carriers: 'Carrier Config',
  vat: 'VAT Rate',
  fx: 'FX Rate',
};

// ── Route save/create to the correct PzApi wrapper ──────────────────────────
async function _domainSave(domain, isCreate, record, form) {
  const num = (v) => (v === '' || v == null) ? null : Number(v);
  const str = (v) => (v == null || String(v).trim() === '') ? null : String(v).trim();

  if (domain === 'hs') {
    // create_kind='put': saveHsCode upserts by code for both create and edit
    return await PzApi.saveHsCode(form.hs_code.trim(), {
      description_pl: str(form.description_pl),
      description_en: str(form.description_en),
      duty_rate_pct:  num(form.duty_rate_pct),
      vat_rate_pct:   num(form.vat_rate_pct),
      active:         !!form.active,
    });
  }

  if (domain === 'units') {
    return await PzApi.saveUnit(form.code.trim(), {
      name_pl:   str(form.name_pl),
      name_en:   str(form.name_en),
      unit_type: str(form.unit_type),
      active:    !!form.active,
    });
  }

  if (domain === 'incoterms') {
    return await PzApi.saveIncoterm(form.code.trim(), {
      name:                str(form.name),
      risk_transfer_point: str(form.risk_transfer_point),
      freight_included:    !!form.freight_included,
      insurance_included:  !!form.insurance_included,
      customs_included:    !!form.customs_included,
      active:              !!form.active,
    });
  }

  if (domain === 'carriers') {
    return await PzApi.saveCarrierConfig(form.carrier_code.trim(), {
      name:               str(form.name),
      parser_type:        str(form.parser_type),
      api_type:           str(form.api_type),
      inbox_email:        str(form.inbox_email),
      supported_services: str(form.supported_services),
      notes:              str(form.notes),
      active:             !!form.active,
    });
  }

  if (domain === 'vat') {
    if (isCreate) {
      return await PzApi.createVatConfig({
        rate_code:    str(form.rate_code),
        rate_pct:     num(form.rate_pct),
        country:      str(form.country),
        product_type: str(form.product_type),
        active:       !!form.active,
      });
    } else {
      const vatId = record.vat_id || record.id;
      return await PzApi.saveVatConfig(vatId, {
        rate_code:    str(form.rate_code),
        rate_pct:     num(form.rate_pct),
        country:      str(form.country),
        product_type: str(form.product_type),
        active:       !!form.active,
      });
    }
  }

  if (domain === 'fx') {
    if (isCreate) {
      return await PzApi.createFxRate({
        from_currency: str(form.from_currency),
        to_currency:   str(form.to_currency),
        rate:          num(form.rate),
        rate_date:     str(form.rate_date),
        source:        str(form.source),
        active:        !!form.active,
      });
    } else {
      const fxId = record.fx_id || record.id;
      return await PzApi.saveFxRate(fxId, {
        from_currency: str(form.from_currency),
        to_currency:   str(form.to_currency),
        rate:          num(form.rate),
        rate_date:     str(form.rate_date),
        source:        str(form.source),
        active:        !!form.active,
      });
    }
  }

  return { ok: false, error: 'Unknown domain: ' + domain };
}

// ── MasterRecordEditModal ────────────────────────────────────────────────────
// Generic create/edit form for capability-driven CRUD domains.
// Props:
//   domain      — 'hs' | 'fx' | 'vat' | 'carriers' | 'incoterms' | 'units'
//   capability  — the domain descriptor from capabilities[domain] (may be null/undefined)
//   columns     — ENTITY_COLUMNS[domain] (unused here; fields come from DOMAIN_FIELDS)
//   record      — existing record object (edit) or null (create)
//   onClose     — called when modal is closed without save
//   onSaved     — called after successful save; parent calls handleReload()
function MasterRecordEditModal({ domain, capability, columns, record, onClose, onSaved }) {
  const isCreate = !record;
  const fields = DOMAIN_FIELDS[domain] || [];
  const domainLabel = DOMAIN_LABEL[domain] || domain;
  const createKind = (capability && capability.create_kind) || 'put';

  // Build initial form state from record or empty for create
  function initForm() {
    const f = {};
    fields.forEach(function(fd) {
      if (fd.type === 'checkbox') {
        f[fd.key] = record ? (record[fd.key] !== false) : true;
      } else if (fd.type === 'number') {
        f[fd.key] = (record && record[fd.key] != null) ? String(record[fd.key]) : '';
      } else {
        f[fd.key] = (record && record[fd.key] != null) ? String(record[fd.key]) : '';
      }
    });
    return f;
  }

  const [form, setForm] = React.useState(initForm);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [fieldErrors, setFieldErrors] = React.useState({});

  function set(k, v) {
    setForm(function(prev) { return Object.assign({}, prev, { [k]: v }); });
    setFieldErrors(function(prev) { return Object.assign({}, prev, { [k]: null }); });
    setError(null);
  }

  function validate() {
    const errs = {};
    fields.forEach(function(fd) {
      if (fd.required && fd.type !== 'checkbox') {
        const v = form[fd.key];
        if (!v || !String(v).trim()) {
          errs[fd.key] = 'Required';
        }
      }
    });
    return errs;
  }

  async function save() {
    if (saving) return;
    const errs = validate();
    if (Object.keys(errs).length) {
      setFieldErrors(errs);
      setError('Please fill in all required fields.');
      return;
    }
    setSaving(true);
    setError(null);
    let res;
    try {
      res = await _domainSave(domain, isCreate, record, form);
    } catch (ex) {
      setSaving(false);
      setError(String(ex));
      return;
    }
    setSaving(false);
    if (res && res.ok) {
      if (onSaved) onSaved();
      onClose();
    } else {
      setError(
        (res && res.error) ||
        (res && res.data && res.data.detail) ||
        'Save failed.'
      );
    }
  }

  // A field with isKey=true and createKind='put' is read-only in edit mode.
  function isKeyReadOnly(fd) {
    return fd.isKey && !isCreate && createKind === 'put';
  }

  const inputBase = {
    width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box',
    border: '1px solid var(--border)', borderRadius: 6,
    background: 'var(--card)', color: 'var(--text)',
  };
  const inputReadOnly = Object.assign({}, inputBase, {
    background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed',
  });
  const inputError = (hasErr) => hasErr
    ? Object.assign({}, inputBase, { borderColor: 'var(--badge-red-border, rgba(220,38,38,0.7))' })
    : inputBase;

  return (
    <div
      data-testid={'master-record-edit-modal-' + domain}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1200,
        background: 'var(--overlay, rgba(0,0,0,0.45))',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}>
      <div
        onClick={function(e) { e.stopPropagation(); }}
        style={{
          background: 'var(--card)', borderRadius: 10,
          width: 500, maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto',
          padding: 20, boxShadow: '0 20px 60px var(--shadow-heavy, rgba(0,0,0,0.3))',
          color: 'var(--text)',
        }}>
        {/* Header */}
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4, color: 'var(--text)' }}>
          {isCreate ? 'New ' + domainLabel : 'Edit ' + domainLabel}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 16 }}>
          {isCreate
            ? 'Create a new ' + domainLabel + ' record.'
            : 'Edit ' + domainLabel + ' record.'
          }
        </div>

        {/* Fields */}
        {fields.map(function(fd) {
          const hasErr = !!fieldErrors[fd.key];
          const readOnly = isKeyReadOnly(fd);

          if (fd.type === 'checkbox') {
            return (
              <label
                key={fd.key}
                data-testid={'mre-field-' + fd.key}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  fontSize: 12, color: 'var(--text-2)', marginBottom: 12, cursor: 'pointer',
                }}>
                <input
                  type="checkbox"
                  data-testid={'mre-input-' + fd.key}
                  checked={!!form[fd.key]}
                  onChange={function(e) { set(fd.key, e.target.checked); }}
                />
                {fd.label}
              </label>
            );
          }

          return (
            <div key={fd.key} style={{ marginBottom: 12 }} data-testid={'mre-field-' + fd.key}>
              <label style={{
                display: 'block', fontSize: 11, fontWeight: 600,
                color: 'var(--text-2)', marginBottom: 4,
              }}>
                {fd.label}
              </label>
              <input
                data-testid={'mre-input-' + fd.key}
                type={fd.type === 'number' ? 'number' : 'text'}
                value={form[fd.key]}
                readOnly={readOnly}
                disabled={readOnly}
                step={fd.type === 'number' ? 'any' : undefined}
                onChange={readOnly ? undefined : function(e) { set(fd.key, e.target.value); }}
                style={readOnly ? inputReadOnly : inputError(hasErr)}
              />
              {hasErr && (
                <div style={{ fontSize: 10, color: 'var(--badge-red-text, rgba(220,38,38,0.9))', marginTop: 2 }}>
                  {fieldErrors[fd.key]}
                </div>
              )}
              {readOnly && (
                <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
                  Key field — read-only after creation.
                </div>
              )}
            </div>
          );
        })}

        {/* Error */}
        {error && (
          <div
            data-testid="mre-error"
            style={{
              marginBottom: 12, padding: '8px 10px', fontSize: 12, borderRadius: 6,
              background: 'var(--badge-red-bg, rgba(220,38,38,0.08))',
              color: 'var(--badge-red-text, rgba(220,38,38,0.9))',
              border: '1px solid var(--badge-red-border, rgba(220,38,38,0.2))',
            }}>
            {error}
          </div>
        )}

        {/* Footer buttons */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn variant="outline" small onClick={onClose} data-testid="mre-cancel">Cancel</Btn>
          <Btn
            variant="gold"
            small
            onClick={save}
            disabled={saving}
            data-testid={'mre-save-' + domain}>
            {saving ? 'Saving…' : (isCreate ? 'Create ' + domainLabel : 'Save to ' + domainLabel)}
          </Btn>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { MasterRecordEditModal });
