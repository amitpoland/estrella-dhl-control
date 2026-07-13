// design-detail.jsx — Design Detail create / edit modal.
//
// Authority: Design Master (GET /api/v1/designs/{code}, POST/PATCH /api/v1/designs).
// Create mode (designCode === null | undefined): empty form; calls PzApi.saveDesign(code, body).
// Edit mode (designCode = string): loads via PzApi.getDesign(designCode); saves partial diff
//   (changed fields only) via PzApi.saveDesign(code, diff) after confirm dialog.
//
// design_code is the immutable business key — READ-ONLY in edit mode.
// Mirrors the structure of supplier-detail.jsx.

const _DD_TABS = [
  { id: 'identity',   label: 'Identity' },
  { id: 'attributes', label: 'Attributes' },
  { id: 'notes',      label: 'Notes' },
];

// ── Field wrapper ─────────────────────────────────────────────────────────────
function _DdField({ label, children, span, hint }) {
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
const _ddInputStyle = {
  width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box',
  border: '1px solid var(--border)', borderRadius: 6,
  background: 'var(--card)', color: 'var(--text)',
};
const _ddReadonlyStyle = Object.assign({}, _ddInputStyle, {
  background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed',
});

// ── Confirm-before-save dialog (local; _SdConfirmDialog is not exported globally)
function _DdConfirmDialog({ changes, onConfirm, onCancel }) {
  var entries = Object.entries(changes);
  return (
    <div data-testid="dd-confirm-dialog" style={{
      position: 'fixed', inset: 0, zIndex: 1100,
      background: 'var(--overlay, rgba(0,0,0,0.5))',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }} onClick={onCancel}>
      <div onClick={function(e){ e.stopPropagation(); }} style={{
        background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
        maxWidth: 480, width: '100%', maxHeight: '60vh', overflow: 'auto',
        boxShadow: '0 12px 40px var(--shadow-heavy, rgba(0,0,0,0.35))', padding: 20,
        color: 'var(--text)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>Confirm design changes</div>
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
          <Btn variant="outline" small onClick={onCancel} data-testid="dd-confirm-cancel">Cancel</Btn>
          <Btn variant="gold" small onClick={onConfirm} data-testid="dd-confirm-save">Save to Design Master</Btn>
        </div>
      </div>
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────
function DesignDetailModal({ designCode, onClose, onSaved }) {
  var isCreate = designCode === null || designCode === undefined;
  var [tab, setTab]                 = React.useState('identity');
  var [loading, setLoading]         = React.useState(!isCreate);
  var [saving, setSaving]           = React.useState(false);
  var [loadErr, setLoadErr]         = React.useState(null);
  var [saveErr, setSaveErr]         = React.useState(null);
  var [fieldErr, setFieldErr]       = React.useState({});
  var [showConfirm, setShowConfirm] = React.useState(false);
  var [original, setOriginal]       = React.useState(null);
  var [form, setForm]               = React.useState({
    design_code:   '',
    display_name:  '',
    design_family: '',
    collection:    '',
    metal:         '',
    stone_summary: '',
    hs_code:       '',
    unit:          '',
    notes:         '',
  });

  // ── Load on open (edit mode) ──────────────────────────────────────────────
  React.useEffect(function() {
    if (isCreate) return;
    setLoading(true); setLoadErr(null);
    PzApi.getDesign(designCode).then(function(res) {
      if (res.ok) {
        var d = res.data || {};
        setOriginal(d);
        setForm({
          design_code:   d.design_code   != null ? String(d.design_code)   : '',
          display_name:  d.display_name  != null ? String(d.display_name)  : '',
          design_family: d.design_family != null ? String(d.design_family) : '',
          collection:    d.collection    != null ? String(d.collection)    : '',
          metal:         d.metal         != null ? String(d.metal)         : '',
          stone_summary: d.stone_summary != null ? String(d.stone_summary) : '',
          hs_code:       d.hs_code       != null ? String(d.hs_code)       : '',
          unit:          d.unit          != null ? String(d.unit)          : '',
          notes:         d.notes         != null ? String(d.notes)         : '',
        });
      } else {
        setLoadErr(res.error || 'Failed to load design');
      }
      setLoading(false);
    }).catch(function(err) { setLoadErr(String(err)); setLoading(false); });
  }, [designCode]);

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

  // ── Compute changed fields (edit mode — partial diff) ─────────────────────
  function computeChanges() {
    if (!original) return {};
    var SKIP = { id:1, created_at:1, updated_at:1, deleted_at:1, design_code:1 };
    var ch = {};
    Object.keys(form).forEach(function(key) {
      if (SKIP[key]) return;
      var ov = (original[key] === null || original[key] === undefined || original[key] === '') ? '' : String(original[key]);
      var nv = val(key);
      if (ov !== nv) ch[key] = nv === '' ? null : nv;
    });
    return ch;
  }
  var changedFields = isCreate ? {} : computeChanges();
  var hasChanges    = isCreate ? true : Object.keys(changedFields).length > 0;

  // ── Validation ────────────────────────────────────────────────────────────
  function validate() {
    var errs = {};
    if (isCreate && !val('design_code').trim()) errs.design_code = 'Required';
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
    setSaving(true); setSaveErr(null);
    var p;
    if (isCreate) {
      var code = val('design_code').trim();
      var body = {};
      Object.keys(form).forEach(function(k) {
        if (k === 'design_code') return; // passed as URL key
        var v = val(k);
        if (v.trim() !== '') body[k] = v;
      });
      p = PzApi.saveDesign(code, body);
    } else {
      p = PzApi.saveDesign(designCode, changedFields);
    }
    p.then(function(res) {
      setSaving(false); setShowConfirm(false);
      if (res.ok) {
        if (onSaved) onSaved();
        onClose();
      } else {
        var detail = (res.data && res.data.detail) ? String(res.data.detail) : '';
        if (res.status === 409 || detail.toLowerCase().indexOf('duplicate') !== -1 || detail.toLowerCase().indexOf('already') !== -1) {
          setSaveErr('Design code already exists — use a different code or edit the existing design.');
        } else {
          setSaveErr(res.error || detail || (isCreate ? 'Create failed' : 'Save failed'));
        }
      }
    }).catch(function(err) { setSaving(false); setShowConfirm(false); setSaveErr(String(err)); });
  }

  // ── Input renderer ────────────────────────────────────────────────────────
  function inp(field, opts) {
    var options     = opts || {};
    var placeholder = options.placeholder;
    var type        = options.type || 'text';
    var readonly    = options.readonly;
    var testid      = options.testid || ('dd-' + field);
    if (readonly) {
      return (
        <input data-testid={testid} type={type}
          style={_ddReadonlyStyle} value={val(field)} readOnly
          title="Business key — read-only after creation" />
      );
    }
    var borderColor = fieldErr[field] ? 'var(--badge-red-border)' : 'var(--border)';
    var style = Object.assign({}, _ddInputStyle, { borderColor: borderColor });
    return (
      <div>
        <input data-testid={testid} type={type}
          style={style}
          value={val(field)} placeholder={placeholder || ''}
          onChange={function(e) { setField(field, e.target.value); }} />
        {fieldErr[field] && (
          <div style={{ fontSize: 10, color: 'var(--badge-red-text)', marginTop: 2 }}>{fieldErr[field]}</div>
        )}
      </div>
    );
  }

  var changedCount = Object.keys(changedFields).length;

  return (
    <div data-testid="design-detail-modal" style={{
      position: 'fixed', inset: 0, background: 'var(--overlay, rgba(0,0,0,0.45))', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--bg)', borderRadius: 12, width: '100%', maxWidth: 720,
        maxHeight: '92vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        border: '1px solid var(--border)', boxShadow: '0 12px 48px var(--shadow-heavy, rgba(0,0,0,0.25))',
        color: 'var(--text)',
      }} onClick={function(e){ e.stopPropagation(); }}>

        {/* ── Header ── */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {isCreate ? 'New Design' : (original ? (original.display_name || original.design_code || 'Design') : 'Design')}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
              {isCreate ? 'Create new design record (Design Master authority)' : ('Edit design — ' + designCode)}
            </div>
          </div>
          <Btn small variant="ghost" onClick={onClose} data-testid="dd-close">{'✕'} Close</Btn>
        </div>

        {/* ── Tab strip ── */}
        <div style={{ display: 'flex', gap: 0, padding: '0 24px', borderBottom: '1px solid var(--border)' }}>
          {_DD_TABS.map(function(t) {
            return (
              <Btn key={t.id} data-testid={'dd-tab-' + t.id}
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
            <div data-testid="dd-loading" style={{ textAlign: 'center', padding: 48, color: 'var(--text-3)' }}>
              Loading design data...
            </div>
          )}

          {loadErr && (
            <div data-testid="dd-load-error" style={{
              padding: 16, background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
              borderRadius: 6, color: 'var(--badge-red-text)', fontSize: 12,
            }}>{loadErr}</div>
          )}

          {saveErr && (
            <div data-testid="dd-save-error" style={{
              padding: 12, marginBottom: 12, background: 'var(--badge-red-bg)',
              border: '1px solid var(--badge-red-border)', borderRadius: 6,
              fontSize: 12, color: 'var(--badge-red-text)',
            }}>Save failed: {saveErr}</div>
          )}

          {/* Identity tab */}
          {!loading && !loadErr && tab === 'identity' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_DdField label="Design code *"
                hint={isCreate ? 'Business key — cannot be changed after creation' : 'Business key — read-only after creation'}>
                {inp('design_code', { placeholder: 'e.g. RG-10025', readonly: !isCreate, testid: 'dd-design-code' })}
              </_DdField>
              <_DdField label="Display name">
                {inp('display_name', { placeholder: 'Human-readable design name' })}
              </_DdField>
              <_DdField label="Design family">
                {inp('design_family', { placeholder: 'e.g. Floral, Classic, Modern' })}
              </_DdField>
              <_DdField label="Collection">
                {inp('collection', { placeholder: 'e.g. Spring 2025' })}
              </_DdField>
            </div>
          )}

          {/* Attributes tab */}
          {!loading && !loadErr && tab === 'attributes' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <_DdField label="Metal">
                {inp('metal', { placeholder: 'e.g. 925 Silver, 14K Gold' })}
              </_DdField>
              <_DdField label="Stone summary">
                {inp('stone_summary', { placeholder: 'e.g. CZ, Ruby, Emerald' })}
              </_DdField>
              <_DdField label="HS code (advisory)" hint="Advisory only — definitive HS code is managed in the HS Codes tab">
                {inp('hs_code', { placeholder: 'e.g. 7113.19', testid: 'dd-hs-code' })}
              </_DdField>
              <_DdField label="Unit">
                {inp('unit', { placeholder: 'e.g. pcs, set' })}
              </_DdField>
            </div>
          )}

          {/* Notes tab */}
          {!loading && !loadErr && tab === 'notes' && (
            <_DdField label="Notes" span={2}>
              <textarea data-testid="dd-notes" rows={6}
                style={Object.assign({}, _ddInputStyle, { resize: 'vertical' })}
                value={val('notes')} onChange={function(e){ setField('notes', e.target.value); }}
                placeholder="Internal notes about this design" />
            </_DdField>
          )}

          {/* Record info collapsible (edit mode) */}
          {!loading && !loadErr && !isCreate && original && (
            <details style={{ marginTop: 20 }} data-testid="dd-record-info">
              <summary style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer', userSelect: 'none', padding: '4px 0' }}>
                Record info (read-only)
              </summary>
              <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: '6px 12px', marginTop: 8 }}>
                {[
                  ['ID',             original.id         || '--'],
                  ['Created',        original.created_at  || '--'],
                  ['Updated',        original.updated_at  || '--'],
                ].map(function(pair) {
                  return (
                    <React.Fragment key={pair[0]}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)' }}>{pair[0]}</div>
                      <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text)' }}>{pair[1]}</div>
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
              ? 'Fill required field (*) then click Create'
              : hasChanges
                ? changedCount + ' field' + (changedCount === 1 ? '' : 's') + ' changed'
                : 'No changes'}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="outline" onClick={onClose} data-testid="dd-cancel">Cancel</Btn>
            <Btn variant="gold" onClick={handleSaveClick}
              disabled={(!isCreate && !hasChanges) || saving || loading}
              data-testid="dd-save">
              {saving ? 'Saving...' : isCreate ? 'Create Design' : 'Save to Design Master'}
            </Btn>
          </div>
        </div>
      </div>

      {showConfirm && !isCreate && (
        <_DdConfirmDialog
          changes={changedFields}
          onConfirm={doSave}
          onCancel={function(){ setShowConfirm(false); }}
        />
      )}
    </div>
  );
}

Object.assign(window, { DesignDetailModal });
