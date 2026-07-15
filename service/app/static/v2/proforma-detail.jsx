// proforma-detail.jsx — Sprint 36 Phase 2: UI parity with atlas-proforma-preview.html
// Authority sources (no fake/hardcoded data):
//   GET /api/v1/proforma/draft/{id}                → editable_lines (incl. name_pl), buyer_override, exchange_rate
//   GET /api/v1/settings/company-profile             → exporter identity (SELLER card)
//   GET /api/v1/proforma/draft/{id}/disclose-post    → VAT context, post payload
//   POST /api/v1/proforma/draft/{id}/post            → post to wFirma (toolbar + modal)
//   POST /api/v1/proforma/draft/{id}/clone           → duplicate action (toolbar)
//   POST /api/v1/proforma/draft/{id}/to-invoice      → convert to invoice (toolbar + modal)
//   GET /api/v1/proforma/{batch_id}/{cn}/document.pdf → PDF download / print (toolbar)
//   GET /api/v1/proforma/draft/{id}/events           → history tab
//   POST /api/v1/proforma/preview/{batch_id}/{cn}    → reservation / blocking reasons

// HTML detail tab spec (pinned wireframe): Overview · Items · Source & Extraction ·
// Logistics · Documents · Audit Trail. Customer Mapping + Reservation are existing
// EJ Extensions (preserved per the EJ Extension rule — never removed).
const PROFORMA_TABS = [
  { id: 'overview',         label: 'Overview'            },
  { id: 'lines',            label: 'Items'               },  // HTML "Items" = editable line items
  { id: 'source',           label: 'Source & Extraction' },  // HTML tab — Backend Pending
  { id: 'logistics',        label: 'Logistics'           },  // HTML tab — Backend Pending
  { id: 'documents',        label: 'Documents'           },  // HTML tab — Backend Pending
  { id: 'history',          label: 'Audit Trail'         },  // HTML "Audit Trail" = history
  { id: 'customer_mapping', label: 'Customer Mapping'    },  // EJ Extension
  { id: 'reservation',      label: 'Reservation'         },  // EJ Extension
];

// ── Toolbar button ────────────────────────────────────────────────────────────
// The COLLIDER from the B2 render-check defect: this file loads 27th, and its
// hoisted `_excluded` (['children','onClick','disabled','title','warn','style'])
// overwrote earlier files' helpers. Explicit 'data-testid' destructuring, NOT
// spread-rest (PROJECT_STATE DECISIONS "V2-wide spread-rest collision sweep").
function TbBtn({ children, onClick, disabled, title, warn, style: xs, 'data-testid': testid }) {
  const [hov, setHov] = React.useState(false);
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      data-testid={testid}
      onMouseEnter={() => !disabled && setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: (hov && !disabled)
          ? (warn ? 'var(--badge-amber-bg)' : 'var(--row-hover)')
          : 'transparent',
        border: 0, padding: '8px 12px', borderRadius: 6,
        fontFamily: 'inherit', fontSize: 13,
        color: warn
          ? 'var(--badge-amber-text)'
          : (disabled ? 'var(--text-3)' : 'var(--text)'),
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'inline-flex', alignItems: 'center', gap: 6,
        fontWeight: warn ? 600 : 500, opacity: disabled ? 0.5 : 1,
        whiteSpace: 'nowrap', transition: 'background 0.1s',
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

// ── Wireframe primitives (Slice 2 — proforma wireframe rebuild) ──────────────
// Pf-prefixed file-local helpers ported 1:1 from the operator-approved
// wireframe (estrella-dashboard-wireframe). Pf prefix avoids symbol collision
// with shipment-detail-page.jsx's file-local SectionLabel/PanelCard/StatTile.
// Explicit destructuring only — NOT spread-rest (DECISIONS "V2-wide
// spread-rest collision sweep"). CSS custom properties only.
// CONVENTION (gate-pinned): the `accent` prop on PfPanelCard/PfStatTile takes
// a CSS custom property reference ('var(--accent)', 'var(--badge-*-text)') —
// never a hex literal. test_pf_primitives_css_vars_only enforces the block.

// Overline label with horizontal rule (wireframe SectionLabel).
function PfSectionLabel({ children, style: xs }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, ...(xs || {}) }}>
      <span style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
        letterSpacing: '0.12em', textTransform: 'uppercase',
      }}>{children}</span>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  );
}

// Card with optional header band + accent edge (wireframe PanelCard).
function PfPanelCard({ title, subtitle, status, accent, children, 'data-testid': testid }) {
  return (
    <div data-testid={testid} style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      boxShadow: '0 1px 2px var(--shadow)',
      overflow: 'hidden',
      borderLeft: accent ? `3px solid ${accent}` : '1px solid var(--border)',
    }}>
      {(title || status) && (
        <div style={{
          padding: '14px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, background: 'var(--bg-subtle)',
        }}>
          <div>
            {title && <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', letterSpacing: '0.01em' }}>{title}</div>}
            {subtitle && <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{subtitle}</div>}
          </div>
          {status}
        </div>
      )}
      {children}
    </div>
  );
}

// Stat tile (wireframe StatTile).
function PfStatTile({ label, value, accent, 'data-testid': testid }) {
  return (
    <div data-testid={testid} style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: '16px 18px',
      boxShadow: '0 1px 2px var(--shadow)',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: accent || 'var(--text)', letterSpacing: '0.01em' }}>{value}</div>
    </div>
  );
}

// Draft lifecycle chip colors (wireframe PF_STATUS_CHIP), keyed by the LIVE
// draft_state values. Lifecycle display only — readiness stays with the
// ProformaStatusHeader readiness pill (Lesson N: no gating semantics here).
const PF_STATUS_CHIP = {
  draft:           { label: 'Draft',            bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  editing:         { label: 'Editing',          bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  approved:        { label: 'Approved',         bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  posting:         { label: 'Posting…',         bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  posted:          { label: 'Posted to wFirma', bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  issued:          { label: 'Issued',           bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  post_failed:     { label: 'Post Failed',      bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  cancelled:       { label: 'Cancelled',        bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  superseded:      { label: 'Superseded',       bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
};

function PfProformaStatusChip({ draftState, 'data-testid': testid }) {
  const s = PF_STATUS_CHIP[draftState];
  if (!s) return null;
  return (
    <span data-testid={testid} style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 4,
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      fontSize: 10.5, fontWeight: 600, letterSpacing: '0.02em',
      whiteSpace: 'nowrap',
    }}>{s.label}</span>
  );
}

// Labelled edit row (wireframe FieldRow) — right-aligned control.
function PfFieldRow({ label, children, hint }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', gap: 16 }}>
      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600, minWidth: 110 }}>
        {label}
        {hint && <span style={{ display: 'block', fontWeight: 400, fontSize: 9.5, color: 'var(--text-3)', opacity: 0.8 }}>{hint}</span>}
      </span>
      <div style={{ flex: 1, maxWidth: 280, display: 'flex', justifyContent: 'flex-end' }}>{children}</div>
    </div>
  );
}

const PF_EDIT_INPUT = {
  width: '100%', padding: '6px 9px', borderRadius: 6,
  border: '1px solid var(--accent-border)', background: 'var(--card)',
  color: 'var(--text)', fontSize: 12, fontWeight: 600,
  boxSizing: 'border-box', outline: 'none',
};

function PfTextEdit({ value, onChange, type, mono, 'data-testid': testid }) {
  return (
    <input
      type={type || 'text'} value={value} data-testid={testid}
      onChange={e => onChange(e.target.value)}
      style={{ ...PF_EDIT_INPUT, fontFamily: mono ? 'monospace' : 'inherit' }}
    />
  );
}

function PfSelectEdit({ value, onChange, options, 'data-testid': testid }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} data-testid={testid} style={PF_EDIT_INPUT}>
      {(options || []).map(o => <option key={o}>{o}</option>)}
    </select>
  );
}

// Ctg display label — derived display-only from enrichment item_type (there is
// no Ctg column in any schema; same map as the CMR grouping's _cmrItemLabel,
// hoisted to module scope so the line mapping can use it).
const PF_CTG_LABELS = {
  PND: 'Pendant', PENDANT: 'Pendant', RNG: 'Ring', RING: 'Ring',
  EAR: 'Earrings', EARRING: 'Earrings', EARRINGS: 'Earrings',
  BRC: 'Bracelet', BRACELET: 'Bracelet',
  NKL: 'Necklace', NECKLACE: 'Necklace', BRO: 'Brooch', SET: 'Set',
  CHAIN: 'Chain', BANGLE: 'Bangle',
};
function PfCtgLabel(t) {
  return PF_CTG_LABELS[(t || '').toUpperCase()] || t || '';
}

// Logistics-style numeric edit row with unit suffix (wireframe EditField).
function PfEditField({ label, value, onChange, suffix, type, width }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600 }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <input
          type={type || 'text'} value={value} step="0.01"
          onChange={e => onChange(e.target.value)}
          style={{
            width: width || 120, textAlign: 'right', padding: '5px 8px',
            borderRadius: 6, border: '1px solid var(--accent-border)',
            background: 'var(--card)', color: 'var(--text)',
            fontSize: 12, fontWeight: 600, fontFamily: 'monospace',
          }}
        />
        {suffix && <span style={{ fontSize: 11, color: 'var(--text-3)', minWidth: 18 }}>{suffix}</span>}
      </div>
    </div>
  );
}

// Searchable autocomplete (wireframe Autocomplete): input + filtered dropdown
// + bold-match highlight + "No match · keep typing" empty state. Pure display
// widget — items and pick semantics come from the caller.
function PfAutocomplete({ value, placeholder, items, getLabel, getSub, onPick, onClear, width, 'data-testid': testid }) {
  const [open, setOpen] = React.useState(false);
  const [q, setQ] = React.useState('');
  const ref = React.useRef(null);

  React.useEffect(() => {
    const close = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const ql = q.trim().toLowerCase();
  const results = ql
    ? (items || []).filter(it => (getLabel(it) + ' ' + (getSub ? getSub(it) : '')).toLowerCase().includes(ql)).slice(0, 8)
    : (items || []).slice(0, 8);

  const bold = (text) => {
    if (!ql) return text;
    const i = text.toLowerCase().indexOf(ql);
    if (i < 0) return text;
    return <>{text.slice(0, i)}<b style={{ color: 'var(--accent)' }}>{text.slice(i, i + ql.length)}</b>{text.slice(i + ql.length)}</>;
  };

  return (
    <div ref={ref} data-testid={testid} style={{ position: 'relative', width: width || '100%' }}>
      {value ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', border: '1px solid var(--accent-border)', borderRadius: 6, background: 'var(--card)' }}>
          <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
          <button onClick={() => { onClear && onClear(); setQ(''); setOpen(true); }} title="Change" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: 'var(--text-3)' }}>×</button>
        </div>
      ) : (
        <input
          value={q} placeholder={placeholder}
          onChange={e => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          style={{ width: '100%', padding: '7px 10px', border: '1px solid var(--accent-border)', borderRadius: 6, background: 'var(--card)', color: 'var(--text)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }}
        />
      )}
      {open && !value && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4, background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, boxShadow: '0 8px 24px var(--shadow-heavy)', zIndex: 50, maxHeight: 280, overflowY: 'auto' }}>
          {results.length === 0 && <div style={{ padding: '12px 14px', fontSize: 11.5, color: 'var(--text-3)' }}>No match · keep typing to enter manually</div>}
          {results.map((it, i) => (
            <button
              key={i}
              onClick={() => { onPick(it); setOpen(false); setQ(''); }}
              style={{ width: '100%', textAlign: 'left', padding: '9px 12px', background: 'none', border: 'none', borderBottom: i < results.length - 1 ? '1px solid var(--border-subtle)' : 'none', cursor: 'pointer', display: 'block' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{bold(getLabel(it))}</div>
              {getSub && <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 1 }}>{getSub(it)}</div>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
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
        border: `1px solid ${warn ? 'var(--badge-red-border)' : 'var(--border)'}`,
        borderRadius: 8, padding: 14, boxShadow: '0 1px 2px var(--shadow)',
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>{name}</div>
      {(lines || []).map((l, i) => (
        l && l !== '—' ? <div key={i} style={{ fontSize: 11, color: 'var(--text-2)', lineHeight: 1.4 }}>{l}</div> : null
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

// ── Print-preview modal ────────────────────────────────────────────────────────
// READ-ONLY. Never mutates draft state. Uses real docData/cmrData from ProformaDetailPage.
// Requires: estrella-doc-tokens.css + estrella-doc-proforma.jsx + estrella-doc-cmr.jsx loaded in index.html.
function ProformaPreviewModal({ docData, variant, onVariantChange, docType, onDocTypeChange, cmrData, packingData, onClose, onEditRequest }) {
  // Portrait A4 (794px) → 0.88 fits 900px wrap.
  // Landscape A4 (1123px) → 0.87 fits 1200px wrap.
  // activeType MUST be declared before SCALE — SCALE depends on it.
  const activeType = docType || 'proforma';
  const SCALE = activeType === 'packing' ? 0.87 : 0.88;

  // Variant selection per document type
  const variantOptions = activeType === 'cmr'     ? ['classic', 'modern']
                       : activeType === 'packing'  ? ['classic']
                       : ['classic', 'modern', 'bold'];

  // Component resolution
  let DocVariant = null;
  if (activeType === 'cmr') {
    DocVariant = variant === 'modern'
      ? (window.EJCMRModern  || null)
      : (window.EJCMRClassic || null);
  } else if (activeType === 'packing') {
    DocVariant = window.EJPackingList || null;
  } else {
    DocVariant = variant === 'modern' ? (window.EJProformaModern || null)
               : variant === 'bold'   ? (window.EJProformaBold   || null)
               : (window.EJProformaClassic || null);
  }

  // Trap Escape key
  React.useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Portal: render directly on <body> so print CSS `body > *:not(.ej-preview-overlay)`
  // correctly hides the SPA container without hiding the overlay inside it.
  return ReactDOM.createPortal(
    <div
      className="ej-preview-overlay"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="proforma-preview-modal"
    >
      {/* A4 print CSS — hides modal chrome, resets scale, sets page size.
          Orientation is dynamic: landscape for Packing List, portrait for Proforma/CMR. */}
      <style>{`
        @media print {
          @page { size: A4 ${activeType === 'packing' ? 'landscape' : 'portrait'}; margin: ${activeType === 'packing' ? '0.5cm' : '0.8cm'}; }
          body > *:not(.ej-preview-overlay) { display: none !important; }
          .ej-preview-overlay {
            position: static !important; background: none !important;
            overflow: visible !important; inset: auto !important;
          }
          .ej-preview-bar { display: none !important; }
          .ej-preview-body { overflow: visible !important; height: auto !important; }
          .ej-preview-sheet { transform: none !important; transform-origin: top left !important; }
          .ej-preview-wrap { box-shadow: none !important; width: auto !important; }
        }
      `}</style>
      <div className="ej-preview-wrap" style={activeType === 'packing' ? {width: '1200px'} : {}}>
        {/* Control bar */}
        <div className="ej-preview-bar">
          <span style={{ fontWeight: 700, letterSpacing: '0.04em' }}>Print Preview</span>
          <span style={{ color: '#7C89A3', fontSize: 11 }}>
            Read-only · {activeType === 'cmr' ? (cmrData && cmrData.cmr_no) || '—' : docData.doc_no}
          </span>
          <div style={{ display: 'flex', gap: 6, marginLeft: 'auto', alignItems: 'center' }}>
            {/* Document type selector */}
            {[['proforma', 'Proforma'], ['cmr', 'CMR'], ['packing', 'Packing List']].map(([dt, label]) => (
              <button
                key={dt}
                onClick={() => {
                  onDocTypeChange(dt);
                  if ((dt === 'cmr' || dt === 'packing') && variant === 'bold') onVariantChange('classic');
                }}
                data-testid={`preview-doctype-${dt}`}
                style={{
                  padding: '4px 12px', borderRadius: 5, border: '1px solid',
                  fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  borderColor: activeType === dt ? '#C9A24B' : '#3A4A62',
                  background:  activeType === dt ? '#C9A24B30' : 'transparent',
                  color:        activeType === dt ? '#C9A24B'  : '#8A9AB6',
                }}
              >
                {label}
              </button>
            ))}
            <div style={{ width: 1, height: 20, background: '#2A3A52', margin: '0 2px' }}/>
            {/* Variant selector (per doc type) */}
            {variantOptions.map(v => (
              <button
                key={v}
                onClick={() => onVariantChange(v)}
                data-testid={`preview-variant-${v}`}
                style={{
                  padding: '4px 12px', borderRadius: 5, border: '1px solid',
                  fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  borderColor: variant === v ? '#7C89A3' : '#2A3A52',
                  background:  variant === v ? '#2A3A5240' : 'transparent',
                  color:        variant === v ? '#C8D4E8'  : '#5A6A82',
                }}
              >
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </button>
            ))}
            <div style={{ width: 1, height: 20, background: '#2A3A52', margin: '0 4px' }}/>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
              <button
                data-testid="preview-download"
                onClick={() => {
                  // Temporarily remove scale so print renders at true A4 size
                  const sheet = document.querySelector('.ej-preview-sheet');
                  const prevT = sheet ? sheet.style.transform : null;
                  const prevO = sheet ? sheet.style.transformOrigin : null;
                  if (sheet) { sheet.style.transform = 'none'; sheet.style.transformOrigin = 'top left'; }
                  window.print();
                  if (sheet) { sheet.style.transform = prevT; sheet.style.transformOrigin = prevO; }
                }}
                style={{
                  padding: '4px 12px', borderRadius: 5, border: '1px solid #2A5A3A',
                  background: '#0B3D2E20', color: '#4CAF82',
                  fontSize: 12, fontWeight: 600, cursor: 'pointer',
                }}
              >
                ⎙ Print / Save as PDF
              </button>
              <span style={{ fontSize: 9, color: '#5A6A82', lineHeight: 1.3 }}>
                Opens browser print dialog. Choose "Save as PDF" as destination.
              </span>
            </div>
            <button
              onClick={onClose}
              data-testid="preview-close"
              style={{
                padding: '4px 12px', borderRadius: 5, border: '1px solid #3A4A62',
                background: 'transparent', color: '#8A9AB6',
                fontSize: 12, fontWeight: 600, cursor: 'pointer',
              }}
            >
              ✕ Close
            </button>
          </div>
        </div>

        {/* QA warnings — preview only, hidden in print */}
        {activeType === 'proforma' && docData.warnings && docData.warnings.length > 0 && (
          <div className="ej-no-print" style={{
            margin: '8px 16px 0',
            background: '#2A1A00',
            border: '1px solid #7C4A00',
            borderRadius: 6,
            padding: '8px 12px',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}>
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#F59E0B', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 2 }}>
              QA Warnings — fix before printing
            </div>
            {docData.warnings.map((w, i) => (
              <div key={i} style={{ fontSize: 11, color: '#FCD34D', lineHeight: 1.4 }}>
                ⚠ {w.msg}
                {w.code === 'NO_FX_RATE' && onEditRequest && (
                  <button
                    data-testid="warn-fix-fx-rate"
                    onClick={() => { onClose(); onEditRequest(); }}
                    style={{ marginLeft: 8, fontSize: 10, color: '#1a1a1a', background: '#F59E0B',
                             border: 'none', borderRadius: 4, padding: '1px 7px', cursor: 'pointer',
                             fontWeight: 600, verticalAlign: 'middle' }}
                  >Set NBP rate in Overview ↗</button>
                )}
                {w.code === 'NO_ISSUE_DATE' && onEditRequest && (
                  <button
                    data-testid="warn-fix-issue-date"
                    onClick={() => { onClose(); onEditRequest(); }}
                    style={{ marginLeft: 8, fontSize: 10, color: '#1a1a1a', background: '#F59E0B',
                             border: 'none', borderRadius: 4, padding: '1px 7px', cursor: 'pointer',
                             fontWeight: 600, verticalAlign: 'middle' }}
                  >Set issue date in Overview ↗</button>
                )}
                {w.code === 'MISSING_ORIGIN' && (
                  <div data-testid="warn-origin-authority"
                       style={{ fontSize: 10, color: '#D4A600', marginTop: 3, lineHeight: 1.4 }}>
                    Origin is governed by Product Master (product_local.origin_country) — correct it there, not here.{' '}
                    <a href="/v2/master?entity=products" style={{ color: '#F59E0B' }} target="_self">Open Product Master ↗</a>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Document body */}
        <div className="ej-preview-body">
          {DocVariant ? (
            <div
              className="ej-preview-sheet"
              style={{ transform: `scale(${SCALE})`, transformOrigin: 'top center' }}
            >
              {activeType === 'cmr'
                ? <DocVariant cmrData={cmrData}/>
                : activeType === 'packing'
                ? <DocVariant packingData={packingData}/>
                : <DocVariant docData={docData}/>
              }
            </div>
          ) : (
            <div style={{ padding: 40, color: '#64748B', fontSize: 13 }}>
              Print preview requires {
                activeType === 'cmr'     ? 'estrella-doc-cmr.jsx'
                : activeType === 'packing' ? 'estrella-doc-packing.jsx'
                : 'estrella-doc-proforma.jsx'
              } to be loaded.
            </div>
          )}
        </div>
      </div>
    </div>,
  document.body);
}

// ── Cancel Draft Modal ────────────────────────────────────────────────────────
// WIRED: POST /api/v1/proforma/draft/{id}/cancel — uses PzApi.cancelDraft
function CancelDraftModal({ draft, liveDraft, onClose, onSuccess }) {
  const [reason,   setReason]   = React.useState('');
  const [loading,  setLoading]  = React.useState(false);
  const [apiError, setApiError] = React.useState(null);

  const handleCancel = () => {
    if (loading || !reason.trim()) return;
    setLoading(true);
    setApiError(null);
    window.PzApi.cancelDraft(draft.id, liveDraft.updated_at || '', reason.trim())
      .then(r => {
        if (r && r.ok) {
          onSuccess && onSuccess();
        } else {
          setApiError((r && r.error) || 'Cancel failed — check backend logs.');
          setLoading(false);
        }
      })
      .catch(e => {
        setApiError((e && e.message) ? e.message : 'Cancel failed — check backend logs.');
        setLoading(false);
      });
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
    }} onClick={onClose} data-testid="cancel-draft-modal">
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 520, maxWidth: '92vw',
        maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>🗑 Cancel Draft</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: '20px 24px' }}>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 16, lineHeight: 1.6 }}>
            This will mark draft <strong>{liveDraft.wfirma_proforma_fullnumber || `#${draft.id}`}</strong> as <code style={{ background: 'var(--bg-subtle)', padding: '1px 5px', borderRadius: 3 }}>cancelled</code>.
            The draft will remain in the system but will no longer be editable.
            This action does not delete data from wFirma.
          </div>

          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 6 }}>
            Cancellation reason (required)
          </label>
          <textarea
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="e.g. Client withdrew order, duplicate draft, incorrect data…"
            data-testid="cancel-draft-reason"
            style={{
              width: '100%', minHeight: 80, padding: '10px 12px',
              border: '1px solid var(--border)', borderRadius: 8,
              background: 'var(--bg)', color: 'var(--text)',
              fontFamily: 'inherit', fontSize: 13, resize: 'vertical',
            }}
          />

          {apiError && (
            <div style={{ marginTop: 12, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600 }} data-testid="cancel-draft-error">
              ⚠ {apiError}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Btn variant="outline" onClick={onClose} disabled={loading}>Close</Btn>
            <Btn
              variant="danger"
              disabled={!reason.trim() || loading}
              onClick={handleCancel}
              data-testid="cancel-draft-submit"
            >
              {loading ? '⏳ Cancelling…' : '🗑 Cancel Draft'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Purge Draft Modal ─────────────────────────────────────────────────────────
// WIRED: DELETE /api/v1/proforma/draft/{id} — uses PzApi.deleteDraft
// Only for cancelled local-only drafts (no wFirma ID, no PROF number).
function PurgeDraftModal({ draft, onClose, onSuccess }) {
  const [loading,  setLoading]  = React.useState(false);
  const [apiError, setApiError] = React.useState(null);

  const handlePurge = () => {
    if (loading) return;
    setLoading(true);
    setApiError(null);
    window.PzApi.deleteDraft(draft.id)
      .then(r => {
        if (r && r.ok) {
          onSuccess && onSuccess();
        } else {
          setApiError((r && r.error) || 'Delete failed — check backend logs.');
          setLoading(false);
        }
      })
      .catch(e => {
        setApiError((e && e.message) ? e.message : 'Delete failed — check backend logs.');
        setLoading(false);
      });
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
    }} onClick={onClose} data-testid="purge-draft-modal">
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 480, maxWidth: '92vw',
        boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>⛔ Delete Draft Permanently</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: '20px 24px' }}>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 16, lineHeight: 1.6 }}>
            This will <strong>permanently delete</strong> draft{' '}
            <strong>#{draft.id}</strong> and its event log from the database.
            This action cannot be undone. Only local-only cancelled drafts
            (no wFirma ID, no PROF number) may be purged.
          </div>
          {apiError && (
            <div style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600 }} data-testid="purge-draft-error">
              ⚠ {apiError}
            </div>
          )}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
            <Btn variant="outline" onClick={onClose} disabled={loading}>Cancel</Btn>
            <Btn
              variant="danger"
              disabled={loading}
              onClick={handlePurge}
              data-testid="purge-draft-submit"
            >
              {loading ? '⏳ Deleting…' : '⛔ Delete permanently'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}


// ── Send Proforma Email Modal ────────────────────────────────────────────────
// WIRED: POST /api/v1/proforma/draft/{id}/send-email — uses PzApi.sendProformaEmail
// M2 — Send proforma PDF to customer via email queue.
function SendProformaModal({ draft, liveDraft, recipientEmail, onClose, onSuccess }) {
  const [loading,    setLoading]    = React.useState(false);
  const [apiError,   setApiError]   = React.useState(null);
  const [recipientOverride, setRecipientOverride] = React.useState('');
  const [subjectOverride,   setSubjectOverride]   = React.useState('');
  const [result,     setResult]     = React.useState(null);

  const docNo = liveDraft.wfirma_proforma_fullnumber || `Draft #${draft.id}`;
  const defaultSubject = `Proforma ${docNo}`;
  const effectiveRecipient = recipientOverride.trim() || recipientEmail || '';
  const effectiveSubject   = subjectOverride.trim() || defaultSubject;

  const handleSend = () => {
    if (loading || !effectiveRecipient) return;
    setLoading(true);
    setApiError(null);
    window.PzApi.sendProformaEmail(draft.id, {
      confirm_token:      'YES_SEND_PROFORMA_EMAIL',
      recipient_override: recipientOverride.trim() || '',
      subject_override:   subjectOverride.trim() || '',
    })
      .then(r => {
        if (r && r.ok) {
          setResult(r);
          setLoading(false);
        } else {
          setApiError((r && r.detail) || (r && r.error) || 'Send failed — check backend logs.');
          setLoading(false);
        }
      })
      .catch(e => {
        const msg = (e && e.message) ? e.message : 'Send failed — check backend logs.';
        setApiError(msg);
        setLoading(false);
      });
  };

  if (result) {
    return (
      <div style={{
        position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
      }} onClick={() => { onSuccess && onSuccess(); onClose(); }} data-testid="send-proforma-modal">
        <div onClick={e => e.stopPropagation()} style={{
          background: 'var(--card)', borderRadius: 12, width: 480, maxWidth: '92vw',
          boxShadow: '0 20px 60px var(--shadow-heavy)',
        }}>
          <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--badge-green-text)' }}>✓ Email Queued</div>
            <button onClick={() => { onSuccess && onSuccess(); onClose(); }} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
          </div>
          <div style={{ padding: '20px 24px' }} data-testid="send-proforma-success">
            <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
              <p>Proforma <strong>{docNo}</strong> has been queued for delivery.</p>
              <div style={{ marginTop: 12, padding: '12px 14px', background: 'var(--bg-subtle)', borderRadius: 8, fontSize: 12 }}>
                <div><strong>Recipient:</strong> {result.recipient}</div>
                <div><strong>Subject:</strong> {result.subject}</div>
                <div><strong>Queue ID:</strong> <code>{result.queued_id}</code></div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 20 }}>
              <Btn variant="primary" onClick={() => { onSuccess && onSuccess(); onClose(); }}>Done</Btn>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
    }} onClick={onClose} data-testid="send-proforma-modal">
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 520, maxWidth: '92vw',
        maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>➤ Send Proforma Email</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: '20px 24px' }}>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 16, lineHeight: 1.6 }}>
            Send proforma <strong>{docNo}</strong> as PDF attachment to the customer.
            The email will be queued and delivered via SMTP.
          </div>

          {/* Recipient display */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 6 }}>
              Recipient {recipientEmail ? '' : '(no email on file — enter manually)'}
            </label>
            {recipientEmail ? (
              <div style={{ padding: '8px 12px', background: 'var(--bg-subtle)', borderRadius: 8, fontSize: 13, color: 'var(--text)' }} data-testid="send-proforma-default-recipient">
                {recipientEmail}
              </div>
            ) : null}
            <input
              type="email"
              value={recipientOverride}
              onChange={e => setRecipientOverride(e.target.value)}
              placeholder={recipientEmail ? 'Override recipient (optional)' : 'Enter recipient email address'}
              data-testid="send-proforma-recipient-override"
              style={{
                width: '100%', padding: '8px 12px', marginTop: 8,
                border: '1px solid var(--border)', borderRadius: 8,
                background: 'var(--bg)', color: 'var(--text)',
                fontFamily: 'inherit', fontSize: 13,
              }}
            />
          </div>

          {/* Subject */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 6 }}>
              Subject
            </label>
            <input
              type="text"
              value={subjectOverride}
              onChange={e => setSubjectOverride(e.target.value)}
              placeholder={defaultSubject}
              data-testid="send-proforma-subject"
              style={{
                width: '100%', padding: '8px 12px',
                border: '1px solid var(--border)', borderRadius: 8,
                background: 'var(--bg)', color: 'var(--text)',
                fontFamily: 'inherit', fontSize: 13,
              }}
            />
          </div>

          {/* Attachment info */}
          <div style={{ padding: '10px 14px', background: 'var(--bg-subtle)', borderRadius: 8, fontSize: 12, color: 'var(--text-2)', marginBottom: 16 }} data-testid="send-proforma-pdf-info">
            📎 Attachment: <strong>proforma-{docNo.replace(/\//g, '-').replace(/\s+/g, '_')}.pdf</strong>
          </div>

          {apiError && (
            <div style={{ marginTop: 0, marginBottom: 12, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600 }} data-testid="send-proforma-error">
              ⚠ {apiError}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Btn variant="outline" onClick={onClose} disabled={loading}>Cancel</Btn>
            <Btn
              variant="primary"
              disabled={!effectiveRecipient || loading}
              onClick={handleSend}
              data-testid="send-proforma-submit"
            >
              {loading ? '⏳ Sending…' : '➤ Send Email'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Prior Invoice History Modal ──────────────────────────────────────────────
// WIRED: GET /api/v1/ledgers/clients/{contractor_id}/invoice-ledger.json
// Read-only — no writes.
function PriorInvoiceHistoryModal({ contractorId, contractorName, onClose }) {
  const [ledger,   setLedger]   = React.useState(null);
  const [loading,  setLoading]  = React.useState(true);
  const [apiError, setApiError] = React.useState(null);

  React.useEffect(() => {
    if (!contractorId) return;
    // Default window: last 12 months
    const now  = new Date();
    const to   = now.toISOString().slice(0, 10);
    const from = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate()).toISOString().slice(0, 10);
    setLoading(true);
    setApiError(null);
    window.PzApi.getClientInvoiceLedger(contractorId, from, to)
      .then(r => {
        if (r && r.ok) {
          setLedger(r.data);
        } else {
          setApiError((r && r.error) || 'Failed to load invoice ledger');
        }
        setLoading(false);
      })
      .catch(e => {
        setApiError((e && e.message) || 'Failed to load invoice ledger');
        setLoading(false);
      });
  }, [contractorId]);

  // Flatten invoices from all currencies into one list
  const invoices = [];
  if (ledger && ledger.invoices_by_currency) {
    Object.entries(ledger.invoices_by_currency).forEach(([cur, list]) => {
      (list || []).forEach(inv => invoices.push({ ...inv, currency: cur }));
    });
  }
  // Sort by date descending
  invoices.sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
    }} onClick={onClose} data-testid="prior-invoice-modal">
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--card)', borderRadius: 12, width: 780, maxWidth: '95vw',
        maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
      }}>
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>Prior Invoice History</div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>
              wFirma contractor: {contractorName || contractorId} · Last 12 months · Read-only
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: '16px 24px' }}>
          {loading && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }} data-testid="prior-invoice-loading">
              Loading invoice history from wFirma…
            </div>
          )}
          {apiError && (
            <div style={{ padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)', fontWeight: 600 }} data-testid="prior-invoice-error">
              ⚠ {apiError}
            </div>
          )}
          {!loading && !apiError && invoices.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }} data-testid="prior-invoice-empty">
              No invoices found for this contractor in the last 12 months.
            </div>
          )}
          {!loading && !apiError && invoices.length > 0 && (
            <div style={{ overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="prior-invoice-table">
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                    {['DATE', 'NUMBER', 'TYPE', 'NET', 'GROSS', 'CUR', 'STATUS'].map(h => (
                      <th key={h} style={{ padding: '9px 12px', textAlign: h === 'NET' || h === 'GROSS' ? 'right' : 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-2)' }}>{inv.date || '—'}</td>
                      <td style={{ padding: '10px 12px', fontSize: 12, fontWeight: 600 }}>{inv.fullnumber || inv.number || '—'}</td>
                      <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--text-2)' }}>{inv.type || '—'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12 }}>{inv.netto != null ? parseFloat(inv.netto).toFixed(2) : '—'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>{inv.brutto != null ? parseFloat(inv.brutto).toFixed(2) : '—'}</td>
                      <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--text-3)' }}>{inv.currency || '—'}</td>
                      <td style={{ padding: '10px 12px', fontSize: 11 }}>
                        <span style={{
                          padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                          background: inv.status === 'paid' ? 'var(--badge-green-bg)' : 'var(--bg-subtle)',
                          color: inv.status === 'paid' ? 'var(--badge-green-text)' : 'var(--text-3)',
                          border: `1px solid ${inv.status === 'paid' ? 'var(--badge-green-border)' : 'var(--border)'}`,
                        }}>
                          {inv.status || 'issued'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: '12px 0', fontSize: 11, color: 'var(--text-3)', display: 'flex', justifyContent: 'space-between' }}>
                <span>{invoices.length} invoice{invoices.length !== 1 ? 's' : ''}</span>
                <span>Source: wFirma invoices/find · Read-only</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── AWB Generate Modal ────────────────────────────────────────────────────────
// WIRED: POST /api/v1/carrier/{batch_id}/shipment
// Requires CARRIER_API_STATUS=live + DHL credentials in environment.
// Prefill authority:
//   recipient identity/address → Customer Master (via buyer_override / ship_to_override)
//   box dimensions             → Box Master (box_types table via /api/v1/box-types/)
//   declared value / currency  → draft total / draft currency
//   EORI / VAT                 → Customer Master (bo.eori, bo.vat_id)
//   DHL service                → /api/v1/carrier/services (static catalogue)
function AwbGenerateModal({ batchId, prefill, onClose, onSuccess }) {
  const [form, setForm] = React.useState({
    // Service
    product_code:  prefill.product_code || 'P',
    // Package
    box_type_code: '',
    weight_kg:     '',
    length_cm:     '',
    width_cm:      '',
    height_cm:     '',
    // Value
    declared_value: (prefill.declared_value || '').toString(),
    currency:       prefill.currency || 'EUR',
    // Description & references
    description:         prefill.description || 'Jewellery',
    customer_reference:  prefill.customer_reference || '',
    shipment_reference:  prefill.shipment_reference || '',
    // Recipient
    name:         prefill.name || '',
    company_name: prefill.company_name || '',
    street:       prefill.street || '',
    city:         prefill.city || '',
    postal_code:  prefill.postal_code || '',
    country_code: prefill.country_code || '',
    phone:        prefill.phone || '',
    email:        prefill.email || '',
    // Customs
    receiver_vat_id: prefill.receiver_vat_id || '',
    receiver_eori:   prefill.receiver_eori || '',
    // Misc
    special_instructions: '',
  });
  const [loading,       setLoading]       = React.useState(false);
  const [apiError,      setApiError]      = React.useState(null);
  const [result,        setResult]        = React.useState(null);
  const [boxTypes,      setBoxTypes]      = React.useState([]);
  const [services,      setServices]      = React.useState([]);
  const [boxOverridden, setBoxOverridden] = React.useState(false); // true when dims differ from selected box
  const [carrierStatus, setCarrierStatus] = React.useState(null);
  const [boxTypesLoaded, setBoxTypesLoaded] = React.useState(false);
  // Customer Master save-confirmation workflow: master = this client's stored
  // record (baseline for the shipping-fields comparison); saveConfirm holds
  // the pending diff panel; savedNote shows after an approved save. Master
  // data is NEVER written silently — only via the explicit Yes button.
  const [master,        setMaster]        = React.useState(null);
  const [saveConfirm,   setSaveConfirm]   = React.useState(null);
  const [savingMaster,  setSavingMaster]  = React.useState(false);
  const [saveError,     setSaveError]     = React.useState(null);
  const [savedNote,     setSavedNote]     = React.useState(false);
  // Baseline availability — the gate FAILS VISIBLE, never open (2026-07-06
  // incident: missing client_contractor_id silently booked AWB 1129315655).
  // 'missing-id' | 'loading' | 'loaded' | 'failed'
  const [masterState,   setMasterState]   = React.useState('missing-id');

  // Load box types, service catalogue, and carrier status once on mount
  React.useEffect(() => {
    window.PzApi.listBoxTypes && window.PzApi.listBoxTypes()
      .then(r => {
        setBoxTypes(r && r.ok && r.data && Array.isArray(r.data.box_types) ? r.data.box_types : []);
        setBoxTypesLoaded(true);
      })
      .catch(() => { setBoxTypes([]); setBoxTypesLoaded(true); });
    window.PzApi.listCarrierServices && window.PzApi.listCarrierServices()
      .then(r => setServices(r && r.ok && Array.isArray(r.data) ? r.data : []))
      .catch(() => setServices([]));
    window.PzApi.getCarrierStatus && window.PzApi.getCarrierStatus()
      .then(r => setCarrierStatus(r && r.ok ? r.data : null))
      .catch(() => setCarrierStatus(null));
    // Customer Master baseline for the save-confirmation comparison.
    // Missing contractor id or a failed fetch does NOT skip the gate — it
    // arms the fail-visible baseline panel instead (never fail open).
    if (prefill.client_contractor_id && window.PzApi.getCustomerMaster) {
      setMasterState('loading');
      window.PzApi.getCustomerMaster(prefill.client_contractor_id)
        .then(r => {
          if (r && r.ok && r.data) { setMaster(r.data); setMasterState('loaded'); }
          else setMasterState('failed');
        })
        .catch(() => setMasterState('failed'));
    } else {
      setMasterState('missing-id');
    }
  }, []);

  // Modal field → Customer Master ship_to_* field. This is the complete set
  // compared before booking; saves write ONLY these ship_to_* fields —
  // bill_to_* (billing identity) is never touched from the AWB modal.
  const _SHIP_FIELD_MAP = [
    ['company_name', 'ship_to_name',    'Receiver company'],
    ['name',         'ship_to_person',  'Contact name'],
    ['street',       'ship_to_street',  'Street'],
    ['city',         'ship_to_city',    'City'],
    ['postal_code',  'ship_to_zip',     'Postal code'],
    ['country_code', 'ship_to_country', 'Country'],
    ['phone',        'ship_to_phone',   'Phone'],
    ['email',        'ship_to_email',   'Email'],
  ];
  // VAT / EORI: compared for awareness only — fiscal identity fields are
  // edited in Customer Master, never written from a shipping modal.
  const _INFO_FIELD_MAP = [
    ['receiver_vat_id', 'vat_eu_number', 'VAT (info only)'],
    ['receiver_eori',   'eori',          'EORI (info only)'],
  ];

  const _norm = (v) => (v == null ? '' : String(v)).trim();

  // Diffs between the modal shipping fields and the Customer Master baseline.
  // null = no baseline available (no contractor id / fetch failed) — booking
  // proceeds without a prompt because there is nothing to compare or save.
  const computeMasterDiffs = () => {
    if (!master) return null;
    const diffs = [];
    for (const [formKey, masterKey, label] of _SHIP_FIELD_MAP) {
      const mv = _norm(master[masterKey]);
      const fv = _norm(form[formKey]);
      if (!fv) continue;                     // blank modal value keeps master value
      const same = (formKey === 'country_code')
        ? mv.toUpperCase() === fv.toUpperCase()
        : mv === fv;
      if (!same) diffs.push({ formKey, masterKey, label, from: mv, to: fv });
    }
    const info = [];
    for (const [formKey, masterKey, label] of _INFO_FIELD_MAP) {
      const mv = _norm(master[masterKey]);
      const fv = _norm(form[formKey]);
      if (fv && mv !== fv) info.push({ formKey, masterKey, label, from: mv, to: fv });
    }
    return { diffs, info };
  };

  // Approved save: write ONLY the changed ship_to_* fields. When the master
  // had no ship-to address at all this is a brand-new shipping address —
  // also set ship_to_use_alternate so downstream flows honor it.
  const saveShippingToMaster = () => {
    const payload = {};
    for (const d of saveConfirm.diffs) payload[d.masterKey] = d.to;
    const hadShipTo = !!(_norm(master.ship_to_street) || _norm(master.ship_to_city));
    if (!hadShipTo) payload.ship_to_use_alternate = true;
    setSavingMaster(true);
    setSaveError(null);
    window.PzApi.saveCustomerMaster(prefill.client_contractor_id, payload)
      .then(r => {
        setSavingMaster(false);
        if (r && r.ok) {
          setMaster(prev => ({ ...(prev || {}), ...payload }));
          setSavedNote(true);
          setSaveConfirm(null);
          doBooking();                        // continue AWB booking after successful save
        } else {
          // Save failed — do NOT book; the operator asked for save-then-book.
          setSaveError((r && r.error) || 'Failed to save shipping details to Customer Master.');
        }
      })
      .catch(e => {
        setSavingMaster(false);
        setSaveError((e && e.message) || 'Failed to save shipping details to Customer Master.');
      });
  };

  const _apiStatus = carrierStatus && carrierStatus.carrier_api_status;
  const isPending = !_apiStatus || _apiStatus === 'pending';
  const _footerLabel = isPending ? 'Carrier API pending'
    : _apiStatus === 'shadow' ? 'Shadow DHL AWB'
    : 'Live DHL Express AWB';

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  // When a box profile is selected, auto-fill dimensions and flag override state
  const handleBoxSelect = (code) => {
    set('box_type_code', code);
    if (!code) return;
    const box = boxTypes.find(b => b.code === code);
    if (!box) return;
    setForm(prev => ({
      ...prev,
      box_type_code: code,
      length_cm:  (box.length_cm  || '').toString(),
      width_cm:   (box.width_cm   || '').toString(),
      height_cm:  (box.height_cm  || '').toString(),
    }));
    setBoxOverridden(false);
  };

  // Mark override when operator manually edits dims after box selection
  const handleDimChange = (k, v) => {
    setBoxOverridden(!!form.box_type_code);
    set(k, v);
  };

  const handleSubmit = () => {
    if (loading || isPending) return;
    const missing = [];
    if (!form.weight_kg)      missing.push('Weight (kg)');
    if (!form.length_cm)      missing.push('Length (cm)');
    if (!form.width_cm)       missing.push('Width (cm)');
    if (!form.height_cm)      missing.push('Height (cm)');
    if (!form.declared_value) missing.push('Declared value');
    if (!form.name && !form.company_name) missing.push('Company Name or Contact Full Name');
    if (!form.street)         missing.push('Street');
    if (!form.city)           missing.push('City');
    if (!form.country_code)   missing.push('Country code');
    if (!form.description)    missing.push('Description');
    if (missing.length) { setApiError(`Missing required fields: ${missing.join(', ')}`); return; }
    // DHL rejects receiver contact without a phone (minLength 1) — block
    // locally with the exact reason instead of a DHL 422 round-trip.
    if (!(form.phone || '').trim()) {
      setApiError('Receiver phone is required by DHL Express.');
      return;
    }

    // Customer Master save-confirmation gate — NO booking until resolved.
    // FAIL VISIBLE: a missing/unloadable baseline is a blocking panel, not a
    // silent pass-through (2026-07-06 incident: fail-open booked AWB
    // 1129315655 uncompared). Booking proceeds ONLY via an explicit operator
    // choice — matching baseline, No/Yes on the diff panel, or "Continue
    // without saving" on the baseline panel.
    if (masterState !== 'loaded' || !master) {
      setSaveError(null);
      setSaveConfirm({
        baselineIssue: masterState === 'missing-id' ? 'missing-id' : 'failed',
      });
      return;
    }

    // Differences between modal shipping data and the client's Customer
    // Master record must be explicitly kept-once, saved, or cancelled.
    const cmp = computeMasterDiffs();
    if (cmp && cmp.diffs.length > 0) {
      const masterPhoneEmpty = !_norm(master.ship_to_phone);
      const phoneOnly = cmp.diffs.length === 1
        && cmp.diffs[0].formKey === 'phone' && masterPhoneEmpty;
      setSaveError(null);
      setSaveConfirm({ diffs: cmp.diffs, info: cmp.info, phoneOnly });
      return;
    }

    doBooking();
  };

  const doBooking = () => {
    setLoading(true);
    setApiError(null);

    window.PzApi.createCarrierShipment(batchId, {
      declared_value:      parseFloat(form.declared_value),
      currency:            form.currency,
      weight_kg:           parseFloat(form.weight_kg),
      dimensions: {
        length_cm: parseFloat(form.length_cm),
        width_cm:  parseFloat(form.width_cm),
        height_cm: parseFloat(form.height_cm),
      },
      recipient_address: {
        name:         form.name || form.company_name,
        company:      form.company_name || undefined,
        street:       form.street,
        city:         form.city,
        postal_code:  form.postal_code,
        country_code: form.country_code.toUpperCase(),
        phone:        form.phone || undefined,
        email:        form.email || undefined,
      },
      product_code:       form.product_code || 'P',
      description:        form.description || 'Jewellery',
      customer_reference: form.customer_reference || null,
      shipment_reference: form.shipment_reference || null,
      receiver_vat_id:    form.receiver_vat_id || null,
      receiver_eori:      form.receiver_eori || null,
      special_instructions: form.special_instructions || null,
      box_type_code:      form.box_type_code || null,
    })
      .then(r => {
        // PzApi wraps responses as { ok, data } / { ok:false, error }.
        // Success MUST be read from r.data.tracking_ref — reading r.tracking_ref
        // rendered every successful booking as a failure and caused operators
        // to retry, double-booking live AWBs (2026-07-06 incident).
        const data = (r && r.ok) ? r.data : null;
        // Success OR idempotency replay both switch to the result view —
        // a replayed COMPLETE (even a legacy row with null tracking_ref)
        // means the shipment already exists; never present it as a failure
        // that invites a retry (2026-07-06 duplicate-AWB incident).
        if (data && (data.tracking_ref || data.replayed)) {
          setResult(data);
        } else {
          const msg = (r && (r.error || (r.data && (r.data.detail || r.data.error))))
            || 'AWB creation failed — check backend logs.';
          setApiError(typeof msg === 'object' ? JSON.stringify(msg) : msg);
        }
        setLoading(false);
      })
      .catch(e => {
        setApiError((e && e.message) ? e.message : 'AWB creation failed — check backend logs.');
        setLoading(false);
      });
  };

  const inputStyle = {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: '1px solid var(--border)', background: 'var(--bg)',
    color: 'var(--text)', fontSize: 13, fontFamily: 'inherit', boxSizing: 'border-box',
  };
  const selStyle = { ...inputStyle, cursor: 'pointer' };
  const labelStyle = { fontSize: 11, color: 'var(--text-3)', fontWeight: 500, marginBottom: 4, display: 'block' };
  const fieldStyle = { marginBottom: 14 };
  const sectionHead = {
    fontSize: 11, fontWeight: 700, color: 'var(--text-3)',
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10, marginTop: 4,
  };

  const overlay = {
    position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 1000,
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 20px',
  };
  const card = {
    background: 'var(--card)', borderRadius: 12, width: 600, maxWidth: '96vw',
    maxHeight: '92vh', overflowY: 'auto', boxShadow: '0 20px 60px var(--shadow-heavy)',
  };
  const header = {
    padding: '18px 24px', borderBottom: '1px solid var(--border)',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0,
    background: 'var(--card)', zIndex: 1,
  };

  if (result) {
    const isReplay  = !!result.replayed;
    const hasRef    = !!result.tracking_ref;
    const isLegacy  = isReplay && !hasRef;   // pre-migration COMPLETE row: no stored AWB
    const isDnu     = !!result.do_not_use;   // LOCAL flag — not a DHL void
    // Mark this label as do-not-use (duplicate/unused). Local status only:
    // no DHL API call, tracking number unchanged, PDFs preserved for audit.
    const markDoNotUse = () => {
      if (!hasRef) return;
      if (!window.confirm('This does not cancel anything at DHL. It only marks this label as not to be used or handed to courier.')) return;
      const reason = window.prompt('Reason (required, stored for audit — e.g. "duplicate label, using other AWB"):', 'duplicate/unused label');
      if (!reason || !reason.trim()) return;
      window.PzApi.markCarrierShipmentDoNotUse(result.batch_id || batchId, result.tracking_ref, { reason: reason.trim() })
        .then(r => {
          if (r && r.ok) setResult({ ...result, ...r.data });
          else window.alert((r && r.error) || 'Failed to mark label as do-not-use.');
        })
        .catch(e => window.alert((e && e.message) || 'Failed to mark label as do-not-use.'));
    };
    return (
      <div style={overlay} onClick={() => { onSuccess && onSuccess(result); onClose(); }} data-testid="awb-generate-modal">
        <div onClick={e => e.stopPropagation()} style={card}>
          <div style={header}>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--badge-green-text)' }}>
              {isReplay ? 'AWB Already Exists' : 'AWB Created'}
            </div>
            <button onClick={() => { onSuccess && onSuccess(result); onClose(); }}
              style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}
              aria-label="Close">×</button>
          </div>
          <div style={{ padding: '24px' }} data-testid="awb-generate-success">
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
              {isReplay
                ? 'A shipment already exists for these package values — no new DHL shipment was created.'
                : 'DHL Express AWB generated successfully'}
            </div>
            {isLegacy ? (
              <div style={{
                padding: '16px 18px', background: 'var(--bg-subtle)', borderRadius: 8,
                border: '1px solid var(--border)', marginBottom: 20,
              }} data-testid="awb-legacy-completed">
                <div style={{ fontSize: 13, color: 'var(--text)' }}>
                  AWB completed earlier — the tracking number predates the reference store.
                  {result.saved_labels_exist
                    ? ' Check the saved labels on the server for this batch.'
                    : ' No saved label was found on the server for this batch.'}
                </div>
              </div>
            ) : (
              <div style={{
                padding: '16px 18px', background: 'var(--bg-subtle)', borderRadius: 8,
                border: '1px solid var(--badge-green-border)', marginBottom: 20,
              }}>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 4 }}>TRACKING NUMBER (AWB)</div>
                <div style={{
                  fontSize: 22, fontWeight: 800, fontFamily: 'monospace',
                  color: 'var(--badge-green-text)', letterSpacing: 1,
                }} data-testid="awb-tracking-ref">{result.tracking_ref}</div>
                <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)' }}>
                  Mode: {result.mode} · State: {result.state}
                  {result.simulated && <span style={{ marginLeft: 8, color: 'var(--badge-amber-text)' }}>(SIMULATED)</span>}
                </div>
              </div>
            )}
            {isDnu && (
              <div style={{
                padding: '10px 14px', background: 'var(--badge-red-bg)',
                border: '1px solid var(--badge-red-border)', borderRadius: 6,
                color: 'var(--badge-red-text)', fontSize: 12.5, fontWeight: 700, marginBottom: 16,
              }} data-testid="awb-dnu-badge">
                DO NOT USE — duplicate/unused label
                {result.do_not_use_reason ? (
                  <div style={{ fontWeight: 500, marginTop: 4, fontSize: 11.5 }}>
                    Reason: {result.do_not_use_reason}
                    {result.do_not_use_at ? ` · ${result.do_not_use_at}` : ''}
                  </div>
                ) : null}
                <div style={{ fontWeight: 500, marginTop: 4, fontSize: 11 }}>
                  Local status only — the DHL booking itself is unchanged. Downloads below are archived audit copies.
                </div>
              </div>
            )}
            {(result.label_download_url || result.waybill_doc_download_url
              || result.shipment_receipt_download_url || result.commercial_documents_url) && (
              <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
                {[
                  // Primary downloads; when marked do-not-use they switch to the
                  // archived audit variant (?archived=true) — never a courier copy.
                  [result.label_download_url,            '⬇ Transport Label',       'awb-download-label',     true],
                  [result.waybill_doc_download_url,      '⬇ Waybill Doc (courier)', 'awb-download-waybill',   true],
                  [result.shipment_receipt_download_url, '⬇ Shipment Receipt',      'awb-download-receipt',   true],
                  [result.commercial_documents_url,      '⬇ Commercial Documents',  'awb-download-documents', false],
                ].map(([href, label, tid, gated]) => href ? (
                  <a key={tid}
                    href={(isDnu && gated) ? `${href}?archived=true` : href} download
                    style={{ ...inputStyle, width: 'auto', padding: '8px 16px', cursor: 'pointer',
                             textDecoration: 'none', display: 'inline-block',
                             ...((isDnu && gated) ? { color: 'var(--badge-red-text)', borderColor: 'var(--badge-red-border)' } : {}) }}
                    data-testid={tid}>
                    {(isDnu && gated) ? `Archived duplicate label — ${label.replace('⬇ ', '')}` : label}
                  </a>
                ) : null)}
              </div>
            )}
            {isReplay && hasRef && !isDnu && (
              <div style={{ marginBottom: 20 }}>
                <button onClick={markDoNotUse} data-testid="awb-mark-dnu"
                  style={{ ...inputStyle, width: 'auto', padding: '8px 16px', cursor: 'pointer',
                           color: 'var(--badge-red-text)', borderColor: 'var(--badge-red-border)', background: 'var(--bg)' }}>
                  ⚑ Mark as Do Not Use
                </button>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6 }}>
                  If this label is a duplicate you will not ship, mark it so it is not printed or handed to DHL. This is a local flag — it does not cancel anything at DHL.
                </div>
              </div>
            )}
            {/* Shipment summary — echoes the recorded shipment intent */}
            <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)',
                          borderRadius: 8, padding: '10px 16px', marginBottom: 20, fontSize: 12 }}
              data-testid="awb-result-summary">
              {[
                ['Batch',          result.batch_id || batchId],
                ['Proforma',       (prefill && prefill.proforma_number) || '—'],
                ['Customer',       form.company_name || form.name || '—'],
                ['Destination',    [form.city, form.country_code].filter(Boolean).join(', ') || '—'],
                ['Service',        result.service_code || form.product_code || '—'],
                ['Weight',         result.weight_kg != null ? `${result.weight_kg} kg` : (form.weight_kg ? `${form.weight_kg} kg` : '—')],
                ['Dimensions',     result.dimensions
                                     ? `${result.dimensions.length_cm}×${result.dimensions.width_cm}×${result.dimensions.height_cm} cm`
                                     : `${form.length_cm}×${form.width_cm}×${form.height_cm} cm`],
                ['Box type',       result.box_type_code || form.box_type_code || '— (manual dimensions)'],
                ['Declared value', result.declared_value != null
                                     ? `${result.declared_value} ${result.currency || ''}`
                                     : `${form.declared_value} ${form.currency}`],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '3px 0' }}>
                  <span style={{ color: 'var(--text-3)' }}>{k}</span>
                  <span style={{ fontWeight: 600, color: 'var(--text)', textAlign: 'right' }}>{v}</span>
                </div>
              ))}
            </div>
            {!result.label_download_url && !isLegacy && (
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 20 }}>
                Label PDF saved to server. Contact ops to retrieve or print the shipping label.
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              {hasRef && (
                <button
                  onClick={() => { navigator.clipboard && navigator.clipboard.writeText(result.tracking_ref); }}
                  style={{ ...inputStyle, width: 'auto', padding: '8px 16px', cursor: 'pointer' }}
                >Copy AWB</button>
              )}
              <Btn variant="primary" onClick={() => { onSuccess && onSuccess(result); onClose(); }}>Done</Btn>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Derive selected box for tare weight hint
  const selectedBox = boxTypes.find(b => b.code === form.box_type_code);

  return (
    <div style={overlay} onClick={onClose} data-testid="awb-generate-modal">
      <div onClick={e => e.stopPropagation()} style={card}>
        <div style={header}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Generate DHL Express AWB</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}
            aria-label="Close">×</button>
        </div>
        <div style={{ padding: '20px 24px' }}>
          {isPending && (
            <div style={{
              padding: '10px 14px', background: 'var(--badge-amber-bg, #fef3c7)',
              borderRadius: 6, border: '1px solid var(--badge-amber-border, #d97706)',
              color: 'var(--badge-amber-text, #92400e)', fontSize: 12, marginBottom: 16,
            }} data-testid="awb-pending-banner">
              Carrier API is pending. Live/shadow AWB generation is disabled.
              Set CARRIER_API_STATUS=shadow or CARRIER_API_STATUS=live to activate.
            </div>
          )}

          {/* ── DHL Service ── */}
          <div style={sectionHead}>DHL Service</div>
          <div style={fieldStyle}>
            <label htmlFor="awb-product_code" style={labelStyle}>Service / Product *</label>
            <select id="awb-product_code" value={form.product_code}
              onChange={e => set('product_code', e.target.value)}
              style={selStyle} data-testid="awb-field-product_code">
              {services.length > 0
                ? services.map(s => (
                    <option key={s.code} value={s.code}>{s.name} ({s.code}) — {s.delivery}</option>
                  ))
                : <option value="P">Express Worldwide (P) — End of day</option>
              }
            </select>
          </div>

          {/* ── Package ── */}
          <div style={sectionHead}>Package</div>
          <div style={fieldStyle}>
            <label htmlFor="awb-box_type" style={labelStyle}>Box Profile</label>
            <select id="awb-box_type" value={form.box_type_code}
              onChange={e => handleBoxSelect(e.target.value)}
              style={selStyle} data-testid="awb-field-box_type_code">
              <option value="">— Enter dimensions manually —</option>
              {boxTypes.map(b => (
                <option key={b.code} value={b.code}>
                  {b.name || b.code} ({b.length_cm}×{b.width_cm}×{b.height_cm} cm, tare {b.tare_weight_kg} kg)
                </option>
              ))}
            </select>
            {boxTypesLoaded && boxTypes.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}
                   data-testid="awb-box-empty-state">
                No active box profiles found in Box Master.
              </div>
            )}
            {boxOverridden && (
              <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginTop: 4 }}>
                Dimensions overridden from box profile — will be sent as entered
              </div>
            )}
            {selectedBox && !boxOverridden && (
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>
                Tare weight: {selectedBox.tare_weight_kg} kg — add to cargo weight to get total package weight
              </div>
            )}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
            {[['weight_kg','Weight (kg)', true],['length_cm','L (cm)', true],['width_cm','W (cm)', true],['height_cm','H (cm)', true]].map(([k, lbl, req]) => (
              <div key={k}>
                <label htmlFor={`awb-${k}`} style={labelStyle}>{lbl}{req ? ' *' : ''}</label>
                <input id={`awb-${k}`} type="number" min="0" step="0.1" value={form[k]}
                  onChange={e => k === 'weight_kg' ? set(k, e.target.value) : handleDimChange(k, e.target.value)}
                  style={inputStyle} data-testid={`awb-field-${k}`} />
              </div>
            ))}
          </div>

          {/* ── Declared Value ── */}
          <div style={sectionHead}>Declared Value</div>
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 1fr', gap: 10, marginBottom: 14 }}>
            <div>
              <label htmlFor="awb-declared_value" style={labelStyle}>Declared Value *</label>
              <input id="awb-declared_value" type="number" min="0" step="0.01" value={form.declared_value}
                onChange={e => set('declared_value', e.target.value)} style={inputStyle}
                data-testid="awb-field-declared_value" />
              {!form.declared_value && (
                <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginTop: 3 }}
                  data-testid="awb-declared-missing-hint">
                  Declared value not found from proforma total — enter it manually.
                </div>
              )}
            </div>
            <div>
              <label htmlFor="awb-currency" style={labelStyle}>Currency *</label>
              <select id="awb-currency" value={form.currency}
                onChange={e => set('currency', e.target.value)}
                style={selStyle} data-testid="awb-field-currency">
                {['EUR','USD','PLN','GBP'].map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>

          {/* ── Description & References ── */}
          <div style={sectionHead}>Description & References</div>
          <div style={fieldStyle}>
            <label htmlFor="awb-description" style={labelStyle}>Shipment Description * (appears on customs label)</label>
            <input id="awb-description" value={form.description}
              onChange={e => set('description', e.target.value)} style={inputStyle}
              data-testid="awb-field-description" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
            <div>
              <label htmlFor="awb-customer_reference" style={labelStyle}>Customer Reference (proforma/order no.)</label>
              <input id="awb-customer_reference" value={form.customer_reference}
                onChange={e => set('customer_reference', e.target.value)} style={inputStyle}
                data-testid="awb-field-customer_reference" />
            </div>
            <div>
              <label htmlFor="awb-shipment_reference" style={labelStyle}>Shipment Reference (internal)</label>
              <input id="awb-shipment_reference" value={form.shipment_reference}
                onChange={e => set('shipment_reference', e.target.value)} style={inputStyle}
                data-testid="awb-field-shipment_reference" />
            </div>
          </div>

          {/* ── Recipient ── */}
          <div style={sectionHead}>Recipient</div>
          <div style={fieldStyle}>
            <label htmlFor="awb-company_name" style={labelStyle}>Company Name *</label>
            <input id="awb-company_name" value={form.company_name}
              onChange={e => set('company_name', e.target.value)}
              style={inputStyle} data-testid="awb-field-company_name" />
          </div>
          <div style={fieldStyle}>
            <label htmlFor="awb-name" style={labelStyle}>Contact Full Name</label>
            <input id="awb-name" value={form.name} onChange={e => set('name', e.target.value)}
              placeholder="Optional — leave blank if unknown"
              style={inputStyle} data-testid="awb-field-name" />
          </div>
          <div style={fieldStyle}>
            <label htmlFor="awb-street" style={labelStyle}>Street Address *</label>
            <input id="awb-street" value={form.street} onChange={e => set('street', e.target.value)}
              style={inputStyle} data-testid="awb-field-street" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
            <div>
              <label htmlFor="awb-city" style={labelStyle}>City *</label>
              <input id="awb-city" value={form.city} onChange={e => set('city', e.target.value)}
                style={inputStyle} data-testid="awb-field-city" />
            </div>
            <div>
              <label htmlFor="awb-postal_code" style={labelStyle}>Postal Code</label>
              <input id="awb-postal_code" value={form.postal_code} onChange={e => set('postal_code', e.target.value)}
                style={inputStyle} data-testid="awb-field-postal_code" />
            </div>
            <div>
              <label htmlFor="awb-country_code" style={labelStyle}>Country *</label>
              <input id="awb-country_code" value={form.country_code}
                onChange={e => set('country_code', e.target.value.toUpperCase())}
                maxLength={2} placeholder="PL" style={inputStyle} data-testid="awb-field-country_code" />
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
            <div>
              <label htmlFor="awb-phone" style={labelStyle}>Phone * (required by DHL)</label>
              <input id="awb-phone" value={form.phone} onChange={e => set('phone', e.target.value)}
                style={inputStyle} data-testid="awb-field-phone" />
              {!(form.phone || '').trim() && (
                <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginTop: 3 }}
                  data-testid="awb-phone-missing-hint">
                  Receiver phone is required by DHL Express.
                </div>
              )}
            </div>
            <div>
              <label htmlFor="awb-email" style={labelStyle}>Email</label>
              <input id="awb-email" type="email" value={form.email} onChange={e => set('email', e.target.value)}
                style={inputStyle} data-testid="awb-field-email" />
            </div>
          </div>

          {/* ── Customs / Tax IDs ── */}
          <div style={sectionHead}>Customs Identifiers</div>
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>
            Prefilled from Customer Master where available. Leave blank if not applicable.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
            <div>
              <label htmlFor="awb-receiver_vat_id" style={labelStyle}>Receiver VAT ID (EU)</label>
              <input id="awb-receiver_vat_id" value={form.receiver_vat_id}
                onChange={e => set('receiver_vat_id', e.target.value)} style={inputStyle}
                data-testid="awb-field-receiver_vat_id" />
            </div>
            <div>
              <label htmlFor="awb-receiver_eori" style={labelStyle}>Receiver EORI</label>
              <input id="awb-receiver_eori" value={form.receiver_eori}
                onChange={e => set('receiver_eori', e.target.value)} style={inputStyle}
                data-testid="awb-field-receiver_eori" />
            </div>
          </div>

          {/* ── Misc ── */}
          <div style={fieldStyle}>
            <label htmlFor="awb-instructions" style={labelStyle}>Special Instructions</label>
            <input id="awb-instructions" value={form.special_instructions}
              onChange={e => set('special_instructions', e.target.value)} style={inputStyle}
              data-testid="awb-field-instructions" />
          </div>

          {apiError && (
            <div style={{
              padding: '10px 14px', background: 'var(--badge-red-bg)', borderRadius: 6,
              color: 'var(--badge-red-text)', fontSize: 12, marginBottom: 16,
            }} data-testid="awb-error">{apiError}</div>
          )}

          {savedNote && (
            <div style={{
              padding: '8px 14px', background: 'var(--badge-green-bg)', borderRadius: 6,
              border: '1px solid var(--badge-green-border)',
              color: 'var(--badge-green-text)', fontSize: 12, marginBottom: 16,
            }} data-testid="awb-master-saved-note">
              Shipping details saved to Customer Master
            </div>
          )}

          {/* Customer Master save-confirmation — booking is HELD until the
              operator picks Yes (save + continue), No (this AWB only), or
              Cancel (no save, no booking). Master is never written silently. */}
          {saveConfirm && saveConfirm.baselineIssue && (
            <div style={{
              padding: '14px 16px', background: 'var(--bg-subtle)', borderRadius: 8,
              border: '1px solid var(--badge-red-border)', marginBottom: 16,
            }} data-testid="awb-baseline-panel">
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
                {saveConfirm.baselineIssue === 'missing-id'
                  ? 'No Customer Master baseline is available, so shipping details cannot be compared.'
                  : 'Customer Master could not be loaded, so shipping details cannot be compared.'}
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 10 }}>
                Nothing will be saved to Customer Master. Book only if you are sure the shipping details above are correct.
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Btn variant="primary"
                  onClick={() => { setSaveConfirm(null); doBooking(); }}
                  data-testid="awb-baseline-continue">
                  Continue without saving
                </Btn>
                <Btn variant="ghost"
                  onClick={() => { setSaveConfirm(null); }}
                  data-testid="awb-baseline-cancel">
                  Cancel
                </Btn>
              </div>
            </div>
          )}

          {saveConfirm && !saveConfirm.baselineIssue && (
            <div style={{
              padding: '14px 16px', background: 'var(--bg-subtle)', borderRadius: 8,
              border: '1px solid var(--badge-amber-border)', marginBottom: 16,
            }} data-testid="awb-master-save-confirm">
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
                {saveConfirm.phoneOnly
                  ? 'Receiver phone is required by DHL Express. Save this phone to Customer Master shipping contact?'
                  : 'These shipping details are different from Customer Master. Save them to this customer\'s shipping details?'}
              </div>
              <div style={{ fontSize: 11.5, marginBottom: 10 }}>
                {saveConfirm.diffs.map(d => (
                  <div key={d.formKey} style={{ display: 'flex', gap: 8, padding: '2px 0' }}
                    data-testid={`awb-master-diff-${d.formKey}`}>
                    <span style={{ color: 'var(--text-3)', minWidth: 120 }}>{d.label}</span>
                    <span style={{ color: 'var(--text-3)', textDecoration: 'line-through' }}>{d.from || '(empty)'}</span>
                    <span style={{ color: 'var(--text)', fontWeight: 600 }}>→ {d.to}</span>
                  </div>
                ))}
                {saveConfirm.info && saveConfirm.info.map(d => (
                  <div key={d.formKey} style={{ display: 'flex', gap: 8, padding: '2px 0', color: 'var(--text-3)' }}
                    data-testid={`awb-master-info-${d.formKey}`}>
                    <span style={{ minWidth: 120 }}>{d.label}</span>
                    <span>{d.from || '(empty)'} → {d.to} · not saved from here — edit in Customer Master</span>
                  </div>
                ))}
              </div>
              {saveError && (
                <div style={{ fontSize: 11.5, color: 'var(--badge-red-text)', marginBottom: 8 }}
                  data-testid="awb-master-save-error">{saveError}</div>
              )}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Btn variant="primary" onClick={saveShippingToMaster} disabled={savingMaster}
                  data-testid="awb-master-save-yes">
                  {savingMaster ? 'Saving…'
                    : (saveConfirm.phoneOnly ? 'Yes' : 'Yes, save to Customer Master and continue')}
                </Btn>
                <Btn variant="ghost" disabled={savingMaster}
                  onClick={() => { setSaveConfirm(null); doBooking(); }}
                  data-testid="awb-master-save-no">
                  {saveConfirm.phoneOnly ? 'No, use only once' : 'No, use only for this AWB'}
                </Btn>
                <Btn variant="ghost" disabled={savingMaster}
                  onClick={() => { setSaveConfirm(null); setSaveError(null); }}
                  data-testid="awb-master-save-cancel">
                  Cancel
                </Btn>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 11, color: isPending ? 'var(--badge-amber-text, #92400e)' : 'var(--text-3)' }}>
              {_footerLabel} · batch: <code>{batchId}</code>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <Btn variant="ghost" onClick={onClose} disabled={loading}>Cancel</Btn>
              <Btn variant="primary" onClick={handleSubmit} disabled={loading || isPending || !!saveConfirm} data-testid="awb-submit-btn">
                {loading ? 'Creating AWB…' : 'Create AWB'}
              </Btn>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

// ── Action toolbar — owns all 17 toolbar buttons ──────────────────────────────
function ProformaActionBar({
  editMode, editSaving, handleSaveEdit, handleCancelEdit,
  canEdit, handleEnterEdit,
  canCancel, setShowCancelModal, draftState,
  canPurge, setShowPurgeModal, purgeDisabledReason,
  handleDuplicate, cloning,
  handleApprove, canApprove, approving, approveDisabledReason, approveError,
  canPost, setShowPostModal, postDisabledReason,
  canConvert, setShowConvertModal, convertDisabledReason,
  setShowPreview,
  handleDownloadPdf, canPrint,
  setShowSendModal, canSend, sendDisabledReason,
  batchId, setShowAwbModal,
  contractorId, setShowInvoiceHistory,
  proformaLabel, onBack,
}) {
  // Wireframe toolbar (Slice 3): [← Back] | eyebrow PRO FORMA DRAFT + number |
  // editing/status chip | right-aligned wireframe-outline button row.
  // ALL live actions stay visible (operator decision 2026-07-10 — no ⋯ menu
  // relocation); every gate, title, and data-testid is preserved verbatim.
  return (
    <div style={{
      padding: '16px 32px', background: 'var(--card)',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0, flexWrap: 'wrap',
    }}>
      <button
        onClick={onBack}
        title="Back to proforma list"
        data-testid="tb-back"
        style={{
          background: 'none', border: '1px solid var(--border)', cursor: 'pointer',
          padding: '7px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
          color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: 6,
          whiteSpace: 'nowrap',
        }}
      >
        ← Back to list
      </button>
      <div style={{ width: 1, height: 28, background: 'var(--border)' }} />
      <div style={{ flex: 1, minWidth: 0 }} data-testid="pf-draft-eyebrow">
        <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 2 }}>
          Pro Forma Draft
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'monospace', color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {proformaLabel}
        </div>
      </div>
      {editMode
        ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px', borderRadius: 4, background: 'var(--accent-subtle)', color: 'var(--accent)', border: '1px solid var(--accent-border)', fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>✎ Editing</span>
        : <PfProformaStatusChip draftState={draftState} />}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {editMode ? (
          <React.Fragment>
            <Btn
              variant="outline" small
              onClick={handleCancelEdit}
              disabled={editSaving}
              title="Discard changes and exit edit mode"
              data-testid="tb-edit-cancel"
            >
              ✕ Cancel Edit
            </Btn>
            <Btn
              variant="gold" small
              onClick={handleSaveEdit}
              disabled={editSaving}
              title="Save changes to draft header fields"
              data-testid="tb-edit-save"
            >
              {editSaving ? '⏳ Saving…' : '✓ Save changes'}
            </Btn>
          </React.Fragment>
        ) : (
          <React.Fragment>
            {canEdit && (
              <Btn
                variant="outline" small
                onClick={handleEnterEdit}
                title="Edit draft header fields (remarks, currency, payment terms, exchange rate)"
                data-testid="tb-edit"
              >
                {/* Label stays "✎ Edit" — the Sprint-36 dead-button pin forbids
                    the literal string (test_no_edit_draft_control_in_toolbar). */}
                ✎ Edit
              </Btn>
            )}
            <Btn
              variant="outline" small
              onClick={() => setShowPreview(true)}
              title="Preview print layout — Proforma or CMR · Classic / Modern / Bold"
              data-testid="tb-preview"
            >
              ◫ Preview
            </Btn>
            <Btn
              variant="outline" small
              onClick={handleDownloadPdf}
              disabled={!canPrint}
              title={canPrint
                ? 'Open wFirma proforma PDF in new tab'
                : 'PDF only available after posting to wFirma'}
              data-testid="proforma-detail-download-pdf"
            >
              ⎙ Print
            </Btn>
            <Btn
              variant="outline" small
              onClick={() => setShowSendModal(true)}
              disabled={!canSend}
              title={canSend
                ? 'Send proforma PDF to customer via email'
                : (sendDisabledReason || 'Email send not available')}
              data-testid="tb-send"
            >
              ➤ Send
            </Btn>
            {/* M8 — DHL Express AWB generation. WIRED: POST /api/v1/carrier/{batch_id}/shipment.
                Requires CARRIER_API_STATUS=live + DHL credentials in environment.
                Booking flow (AwbGenerateModal) is untouched by the wireframe rebuild. */}
            <Btn
              variant="outline" small
              onClick={() => setShowAwbModal(true)}
              disabled={!batchId}
              title={batchId
                ? 'Generate DHL Express AWB — opens shipment form'
                : 'No batch loaded — open a proforma with a batch to generate AWB'}
              data-testid="tb-awb-generate"
            >
              ⚡ AWB Generate
            </Btn>
            <Btn
              variant="outline" small
              onClick={() => contractorId && setShowInvoiceHistory(true)}
              disabled={!contractorId}
              title={contractorId
                ? 'View prior invoice history from wFirma for this customer'
                : 'Backend/customer mapping pending: wFirma contractor ID missing'}
              data-testid="tb-invoice-history"
            >
              📋 Prior Invoices
            </Btn>
            <Btn
              variant="outline" small
              onClick={handleApprove}
              disabled={!canApprove || approving}
              title={canApprove
                ? 'Mark this draft as approved — locks lines before posting to wFirma'
                : approveDisabledReason}
              data-testid="tb-approve"
            >
              {approving ? '⏳ Approving…' : '✓ Approve'}
            </Btn>
            {approveError && (
              <span style={{ color: 'var(--badge-red-text)', fontSize: 11, maxWidth: 180, alignSelf: 'center' }}>{approveError}</span>
            )}
            <Btn
              variant="gold" small
              onClick={() => setShowPostModal(true)}
              disabled={!canPost}
              title={canPost
                ? 'Post this draft to wFirma as a proforma invoice'
                : postDisabledReason}
              data-testid="tb-post"
            >
              ↑ Post to wFirma
            </Btn>
            <Btn
              variant="outline" small
              onClick={() => canConvert && setShowConvertModal(true)}
              disabled={!canConvert}
              title={canConvert
                ? 'Convert this posted proforma to a wFirma invoice'
                : convertDisabledReason}
              style={{ color: 'var(--badge-amber-text)', borderColor: 'var(--badge-amber-border)' }}
              data-testid="tb-convert"
            >
              ⚠ Convert to Invoice
            </Btn>
            <Btn
              variant="outline" small
              onClick={() => canCancel && setShowCancelModal(true)}
              disabled={!canCancel}
              title={canCancel
                ? 'Cancel this draft — soft-cancel, no data deleted'
                : (draftState === 'cancelled' ? 'Already cancelled' : 'Cannot cancel in current state')}
              data-testid="tb-delete"
            >
              🗑 Cancel Draft
            </Btn>
            {draftState === 'cancelled' && (
              <Btn
                variant="outline" small
                onClick={() => canPurge && setShowPurgeModal(true)}
                disabled={!canPurge}
                title={canPurge ? 'Permanently delete this local-only cancelled draft' : purgeDisabledReason}
                style={{ color: 'var(--badge-red-text)', borderColor: 'var(--badge-red-border)' }}
                data-testid="tb-purge"
              >
                ⛔ Delete permanently
              </Btn>
            )}
            <Btn
              variant="outline" small
              onClick={handleDuplicate}
              disabled={cloning}
              title="Clone this draft as a new unposted draft"
              data-testid="tb-duplicate"
            >
              {cloning ? '⏳ Cloning…' : '⎘ Duplicate'}
            </Btn>
            <Btn
              variant="outline" small
              disabled
              title={
                'Document-package generation (proforma PDF · packing list · CMR · CN23) is not yet wired — ' +
                'backend gap M4: POST /api/v1/proforma/draft/{id}/generate-documents (see BACKEND_GAP_REGISTER.md §2, priority LOW). ' +
                'For now use ◫ Preview to view the layouts and ⎙ Print for the wFirma proforma PDF.'
              }
              data-testid="tb-generate"
            >
              ⚙ Generate ▾
            </Btn>
            <Btn
              variant="outline" small
              disabled
              title="More actions"
              data-testid="tb-more"
            >
              ⋯
            </Btn>
          </React.Fragment>
        )}
      </div>
    </div>
  );
}

// ── Proforma status header — readiness pill, customer chip, shipment chip ─────
function ProformaStatusHeader({
  alreadyPosted, readinessPost, postBlocked, postBlockers,
  approveBlocked, approveBlockers,
  stateAllowsApprove, alreadyApproved,
  canPost, canConvert,
  customer, _cmrTotalPcs, liveDraft, draft,
}) {
  const pill = alreadyPosted
    ? { label: 'Posted', tone: 'green' }
    : (readinessPost == null)
      ? { label: 'Checking readiness…', tone: 'neutral' }
      : (postBlocked
          ? { label: `Not ready · ${postBlockers.length} blocker${postBlockers.length === 1 ? '' : 's'}`, tone: 'red' }
          : { label: 'Ready', tone: 'green' });
  const toneBg = t => t === 'green' ? 'var(--badge-green-bg)' : t === 'red' ? 'var(--badge-red-bg)' : 'var(--bg-subtle)';
  const toneFg = t => t === 'green' ? 'var(--badge-green-text)' : t === 'red' ? 'var(--badge-red-text)' : 'var(--text-2)';
  const toneBd = t => t === 'green' ? 'var(--badge-green-border)' : t === 'red' ? 'var(--badge-red-border)' : 'var(--border)';
  const custMapped = !!customer.wfirmaId;
  const pieces = (typeof _cmrTotalPcs === 'number' && _cmrTotalPcs > 0) ? _cmrTotalPcs : null;
  const awb = liveDraft.batch_id || (draft && draft.batch_id) || null;
  const nextAction = (postBlocked && postBlockers.length)
    ? postBlockers[0].repair_action
    : (approveBlocked && approveBlockers.length)
      ? approveBlockers[0].repair_action
      : (stateAllowsApprove && !alreadyApproved)
        ? 'Approve draft'
        : canPost ? 'Post to wFirma'
        : canConvert ? 'Convert to invoice'
        : alreadyPosted ? '— posted; no action required'
        : 'Review draft';
  const chip = (testid, label, tone) => (
    <span data-testid={testid} style={{
      fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 12,
      background: toneBg(tone), color: toneFg(tone), border: `1px solid ${toneBd(tone)}`,
      whiteSpace: 'nowrap',
    }}>{label}</span>
  );
  return (
    <div data-testid="proforma-status-header" style={{
      background: 'var(--card)',
      borderBottom: '1px solid var(--border)',
      padding: '10px 32px',
      display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
    }}>
      {chip('proforma-readiness-pill', pill.label, pill.tone)}
      {chip('proforma-customer-status-chip',
        custMapped ? `Customer: ${customer.wfirmaName || customer.name} ✓` : `Customer: ${customer.name} · unmapped`,
        custMapped ? 'green' : 'neutral')}
      {chip('proforma-shipment-status-chip',
        pieces ? `Shipment: ${pieces} pcs${awb ? ` · AWB ${awb}` : ''}` : 'Shipment: pending',
        pieces ? 'neutral' : 'neutral')}
      <span data-testid="proforma-next-action" style={{
        fontSize: 12, color: 'var(--text)', fontWeight: 600, marginLeft: 'auto',
      }}>Next: {nextAction}</span>
    </div>
  );
}

// ── Product mapping resolver — wires up wFirma search/adopt/create-and-adopt ──
// Renders per-code controls attached to the "N product(s) not matched in
// wfirma_products" readiness blocker. Operator-initiated only; no auto-calls.
//
// Safety invariants (campaign gate — non-negotiable):
//   1. No API call fires on mount. All calls are triggered by explicit operator click.
//   2. wfirmaGoodsSearch and wfirmaGoodsAdopt are read/mirror-only — safe on click.
//   3. wfirmaGoodsCreateAndAdopt is a LIVE wFirma write. It MUST only fire after
//      the operator clicks data-testid="btn-confirm-create-adopt-{code}" inside the
//      explicit confirmation panel (phase === 'confirm_create'). There is no other
//      code path that calls it.
//   4. If the server returns 403 (WFIRMA_CREATE_PRODUCT_ALLOWED is false), the
//      create button transitions to DISABLED with the exact server reason text.

// Parse product codes embedded in a "not matched in wfirma_products" blocker
// reason string. Format: "N product(s) not matched in wfirma_products
// (missing wfirma_product_id): CODE1, CODE2, CODE3…"
function _parseUnmappedProductCodes(blockers) {
  const codes = [];
  const seen = new Set();
  for (const b of (blockers || [])) {
    const r = b.reason || '';
    if (r.includes('wfirma_product')) {
      // Extract codes after the closing "): " of the parenthetical
      const idx = r.lastIndexOf('): ');
      if (idx !== -1) {
        const part = r.slice(idx + 3).replace(/…$/, '').trim();
        for (const c of part.split(',')) {
          const code = c.trim();
          if (code && code !== '...' && !seen.has(code)) {
            seen.add(code);
            codes.push(code);
          }
        }
      }
    }
  }
  return codes;
}

function ProductMappingResolver({ unmappedCodes, draftLines, reloadReadiness }) {
  // Per-code state map.
  // Phases: idle | searching | found | not_found | adopting | adopted |
  //         confirm_create | creating
  const [perCode, setPerCode] = React.useState({});

  const gs = (code) => perCode[code] || { phase: 'idle', result: null, error: null, createBlocked: null };
  const ss = (code, patch) =>
    setPerCode(prev => ({ ...prev, [code]: { ...gs(code), ...patch } }));

  // doSearch — safe read-only wFirma lookup. Only fires on explicit operator click.
  const doSearch = async (code) => {
    ss(code, { phase: 'searching', error: null, createBlocked: null });
    const r = await window.PzApi.wfirmaGoodsSearch(code);
    if (!r.ok) {
      ss(code, { phase: 'idle', error: `Search failed: ${r.error || 'unknown error'}` });
      return;
    }
    const d = r.data || {};
    if (d.found) {
      ss(code, { phase: 'found', result: d.result || {} });
    } else {
      ss(code, { phase: 'not_found' });
    }
  };

  // doAdopt — mirror-only (no wFirma write). Safe on operator click.
  const doAdopt = async (code) => {
    ss(code, { phase: 'adopting', error: null });
    const r = await window.PzApi.wfirmaGoodsAdopt(code);
    if (!r.ok) {
      const d = (r.data) || {};
      const detail = (d.status === 'not_in_wfirma')
        ? 'Not found in wFirma — use Create & adopt instead'
        : (r.error || 'Adopt failed');
      ss(code, { phase: 'found', error: detail });
      return;
    }
    ss(code, { phase: 'adopted' });
    reloadReadiness && reloadReadiness();
  };

  // doConfirmCreate — LIVE wFirma write. Only callable after the operator
  // explicitly clicks data-testid="btn-confirm-create-adopt-{code}".
  // This function MUST NOT be called from any other code path.
  const doConfirmCreate = async (code) => {
    // item_type from draft editable_lines (best-effort; empty falls back to deng)
    const line = (draftLines || []).find(ln => (ln.product_code || '').trim() === code);
    const itemType = (line && line.item_type) || '';
    ss(code, { phase: 'creating', error: null, createBlocked: null });
    const r = await window.PzApi.wfirmaGoodsCreateAndAdopt(code, { item_type: itemType, description_en: '' });
    if (!r.ok) {
      if (r.status === 403) {
        // Flag disabled — disable the button and surface the exact server reason
        const d = (r.data) || {};
        const reasons = d.blocking_reasons || [r.error || 'wfirma_create_product_allowed is false'];
        ss(code, { phase: 'not_found', createBlocked: reasons[0] });
      } else if (r.status === 409) {
        // Already in wFirma — switch to Adopt flow
        const d = (r.data) || {};
        ss(code, {
          phase: 'found',
          result: { wfirma_id: d.wfirma_product_id },
          error: 'Already in wFirma — click Adopt to link it locally.',
        });
      } else {
        ss(code, { phase: 'not_found', error: r.error || 'Create failed — see server logs' });
      }
      return;
    }
    ss(code, { phase: 'adopted' });
    reloadReadiness && reloadReadiness();
  };

  if (!unmappedCodes || unmappedCodes.length === 0) return null;

  const codeId = (c) => c.replace(/[^a-zA-Z0-9_-]/g, '-');

  return (
    <div data-testid="product-mapping-resolver" style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text)' }}>
        Resolve product mapping — register each code in wFirma to clear this blocker:
      </div>
      {unmappedCodes.map(code => {
        const st = gs(code);
        const tid = codeId(code);
        return (
          <div key={code} data-testid={`product-resolver-row-${tid}`}
               style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px dashed var(--border)' }}>
            <div style={{ fontSize: 11, marginBottom: 4 }}>
              <span style={{ fontFamily: 'monospace', color: 'var(--text)', fontWeight: 600 }}>{code}</span>
            </div>

            {st.error && (
              <div style={{ fontSize: 11, color: 'var(--badge-red-text)', marginBottom: 4 }}>
                {st.error}
              </div>
            )}

            {st.phase === 'idle' && (
              <button
                data-testid={`btn-resolve-mapping-${tid}`}
                onClick={() => doSearch(code)}
                style={{ background: 'var(--card)', color: 'var(--text)',
                         border: '1px solid var(--border)', borderRadius: 4,
                         fontSize: 12, padding: '4px 10px', cursor: 'pointer' }}>
                Resolve mapping
              </button>
            )}

            {st.phase === 'searching' && (
              <span style={{ fontSize: 11, color: 'var(--text-2, var(--text))' }}>
                ⏳ Searching in wFirma…
              </span>
            )}

            {st.phase === 'found' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, color: 'var(--badge-green-text, green)' }}>
                  {'✓ Found in wFirma'}
                  {st.result && st.result.wfirma_id ? ` (ID: ${st.result.wfirma_id})` : ''}
                </span>
                <button
                  data-testid={`btn-adopt-${tid}`}
                  onClick={() => doAdopt(code)}
                  style={{ background: 'var(--accent, #c9a456)', color: '#1a1a1a',
                           border: 'none', borderRadius: 4,
                           fontSize: 12, fontWeight: 600,
                           padding: '4px 10px', cursor: 'pointer' }}>
                  Adopt (link locally)
                </button>
              </div>
            )}

            {st.phase === 'adopting' && (
              <span style={{ fontSize: 11, color: 'var(--text-2, var(--text))' }}>
                ⏳ Adopting mapping…
              </span>
            )}

            {st.phase === 'adopted' && (
              <span data-testid={`product-resolver-adopted-${tid}`}
                    style={{ fontSize: 11, color: 'var(--badge-green-text, green)', fontWeight: 600 }}>
                ✓ Adopted — readiness reloading…
              </span>
            )}

            {/* not_found: show create-and-adopt. DISABLED with reason if server blocked
                it (403); otherwise enabled but gated behind explicit confirmation. */}
            {st.phase === 'not_found' && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-2, var(--text))', marginBottom: 4 }}>
                  Not found in wFirma.
                </div>
                {st.createBlocked ? (
                  <button
                    data-testid={`btn-create-adopt-${tid}`}
                    disabled
                    title={st.createBlocked}
                    style={{ background: 'var(--bg-subtle)', color: 'var(--text-3, #aaa)',
                             border: '1px solid var(--border)', borderRadius: 4,
                             fontSize: 12, padding: '4px 10px',
                             cursor: 'not-allowed', opacity: 0.6 }}>
                    {'Create in wFirma & adopt — blocked: '}
                    {st.createBlocked}
                  </button>
                ) : (
                  <button
                    data-testid={`btn-create-adopt-${tid}`}
                    onClick={() => ss(code, { phase: 'confirm_create' })}
                    style={{ background: 'var(--card)', color: 'var(--badge-red-text)',
                             border: '1px solid var(--badge-red-border)', borderRadius: 4,
                             fontSize: 12, fontWeight: 600,
                             padding: '4px 10px', cursor: 'pointer' }}>
                    Create in wFirma &amp; adopt ⚠
                  </button>
                )}
              </div>
            )}

            {/* confirm_create: explicit confirmation gate — the ONLY path to doConfirmCreate */}
            {st.phase === 'confirm_create' && (
              <div data-testid={`product-resolver-confirm-${tid}`}
                   style={{ padding: '8px 10px',
                            border: '1px solid var(--badge-red-border)',
                            borderRadius: 6, background: 'var(--bg)', marginTop: 4 }}>
                <div style={{ fontSize: 12, fontWeight: 700,
                              color: 'var(--badge-red-text)', marginBottom: 4 }}>
                  ⚠ This creates a NEW product in wFirma — a live accounting change. Confirm?
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-2, var(--text))', marginBottom: 8 }}>
                  {'Product code: '}
                  <strong style={{ fontFamily: 'monospace' }}>{code}</strong>
                  <br />
                  {'Will be blocked if '}
                  <code>WFIRMA_CREATE_PRODUCT_ALLOWED</code>
                  {' is not enabled on the server.'}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    data-testid={`btn-confirm-create-adopt-${tid}`}
                    onClick={() => doConfirmCreate(code)}
                    style={{ background: 'var(--badge-red-bg)',
                             color: 'var(--badge-red-text)',
                             border: '1px solid var(--badge-red-border)',
                             borderRadius: 4, fontSize: 12, fontWeight: 700,
                             padding: '4px 12px', cursor: 'pointer' }}>
                    Yes, create in wFirma
                  </button>
                  <button
                    data-testid={`btn-cancel-create-adopt-${tid}`}
                    onClick={() => ss(code, { phase: 'not_found' })}
                    style={{ background: 'var(--card)', color: 'var(--text)',
                             border: '1px solid var(--border)', borderRadius: 4,
                             fontSize: 12, padding: '4px 10px', cursor: 'pointer' }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {st.phase === 'creating' && (
              <span style={{ fontSize: 11, color: 'var(--text-2, var(--text))' }}>
                ⏳ Creating in wFirma…
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Unassigned-packing product_code assigner ──────────────────────────────────
// The write half of the read-only unassigned-packing over-bill evidence. When a
// packing list arrived design-only (no product_code stamped), the real pieces
// for a design are invisible to the availability sum, so a billed code shows
// "available 0" and the over-bill gate blocks with no explanation. Here the
// operator confirms design → product_code; the backend stamps ONLY the currently
// unassigned pieces (never invents availability, never auto-picks, refuses any
// code that is not a currently-surfaced over-bill repair) and readiness reloads.
function UnassignedPackingAssigner({ draftId, productCode, unassignedPacking, reloadReadiness }) {
  const [perDesign, setPerDesign] = React.useState({});
  const gs = (d) => perDesign[d] || { phase: 'idle', error: null };
  const ss = (d, patch) => setPerDesign(prev => ({ ...prev, [d]: { ...gs(d), ...patch } }));

  // doAssign — LOCAL write (X-Operator, no wFirma/fiscal write). Only fires from
  // the explicit confirm button. Stamps exactly the surfaced piece count.
  const doAssign = async (design, count) => {
    ss(design, { phase: 'assigning', error: null });
    const r = await window.PzApi.assignPackingProductCode(draftId, design, productCode, count);
    if (!(r && r.ok)) {
      ss(design, { phase: 'confirm', error: (r && (r.error || r.detail)) || 'Assignment failed — check backend logs.' });
      return;
    }
    ss(design, { phase: 'assigned' });
    reloadReadiness && reloadReadiness();
  };

  if (!unassignedPacking || unassignedPacking.length === 0) return null;
  const codeTid = String(productCode || '').replace(/[^a-zA-Z0-9_-]/g, '-');
  const dTid = (s) => String(s || '').replace(/[^a-zA-Z0-9_-]/g, '-');

  return (
    <div data-testid={`unassigned-packing-assigner-${codeTid}`} style={{ marginTop: 6 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
        {'Unassigned packing piece(s) exist for this code’s design(s) — confirm the identity to assign the product_code:'}
      </div>
      {unassignedPacking.map((u) => {
        const design = String(u.design_no || '');
        const count = Number(u.count || 0);
        const st = gs(design);
        const tid = dTid(design);
        return (
          <div key={design} data-testid={`unassigned-packing-row-${tid}`}
               style={{ marginBottom: 8, paddingBottom: 6, borderBottom: '1px dashed var(--border)' }}>
            <div style={{ fontSize: 11, color: 'var(--text)' }}>
              <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{design}</span>
              <span style={{ opacity: 0.75 }}>
                {`  ·  ${count} piece${count === 1 ? '' : 's'} (qty ${+u.quantity})`}
                {u.invoice_no ? `  ·  invoice ${u.invoice_no}` : ''}
                {'  ·  no product_code assigned'}
              </span>
            </div>

            {st.error && (
              <div data-testid={`unassigned-packing-error-${tid}`}
                   style={{ fontSize: 11, color: 'var(--badge-red-text)', marginTop: 4 }}>
                {st.error}
              </div>
            )}

            {st.phase === 'idle' && (
              <button
                data-testid={`btn-assign-packing-${codeTid}-${tid}`}
                onClick={() => ss(design, { phase: 'confirm', error: null })}
                style={{ marginTop: 4, background: 'var(--card)', color: 'var(--text)',
                         border: '1px solid var(--border)', borderRadius: 4,
                         fontSize: 12, padding: '4px 10px', cursor: 'pointer' }}>
                {`Assign ${productCode} to ${design}…`}
              </button>
            )}

            {st.phase === 'confirm' && (
              <div data-testid={`unassigned-packing-confirm-${codeTid}-${tid}`}
                   style={{ padding: '8px 10px', border: '1px solid var(--border)',
                            borderRadius: 6, background: 'var(--bg)', marginTop: 4 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
                  {'Confirm packing identity'}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-2, var(--text))', marginBottom: 8 }}>
                  {'Stamp product_code '}
                  <strong style={{ fontFamily: 'monospace' }}>{productCode}</strong>
                  {` onto the ${count} unassigned packing piece${count === 1 ? '' : 's'} for design `}
                  <strong style={{ fontFamily: 'monospace' }}>{design}</strong>
                  {'. This makes the real piece(s) countable so the over-bill gate re-checks on true data. It does not create availability or change quantity.'}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    data-testid={`btn-confirm-assign-packing-${codeTid}-${tid}`}
                    onClick={() => doAssign(design, count)}
                    style={{ background: 'var(--accent, #c9a456)', color: '#1a1a1a',
                             border: 'none', borderRadius: 4, fontSize: 12, fontWeight: 700,
                             padding: '4px 12px', cursor: 'pointer' }}>
                    {`Yes, assign to ${count} piece${count === 1 ? '' : 's'}`}
                  </button>
                  <button
                    data-testid={`btn-cancel-assign-packing-${codeTid}-${tid}`}
                    onClick={() => ss(design, { phase: 'idle', error: null })}
                    style={{ background: 'var(--card)', color: 'var(--text)',
                             border: '1px solid var(--border)', borderRadius: 4,
                             fontSize: 12, padding: '4px 10px', cursor: 'pointer' }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {st.phase === 'assigning' && (
              <span style={{ fontSize: 11, color: 'var(--text-2, var(--text))' }}>
                {'⏳ Assigning product_code…'}
              </span>
            )}

            {st.phase === 'assigned' && (
              <span data-testid={`unassigned-packing-assigned-${codeTid}-${tid}`}
                    style={{ fontSize: 11, color: 'var(--badge-green-text, green)', fontWeight: 600 }}>
                {'✓ Assigned — readiness reloading…'}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Blocker panel — consolidated "what's blocking" list ───────────────────────
function ProformaBlockerPanel({ postBlockers, approveBlockers }) {
  const seen = new Set();
  const rows = [];
  const add = (reason, repair, gates) => {
    if (!reason) return;
    const key = `${reason}::${gates}`;
    if (seen.has(key)) return;
    seen.add(key);
    rows.push({ reason, repair: repair || null, gates });
  };
  postBlockers.forEach(b => add(b.reason, b.repair_action, 'Post / Convert'));
  approveBlockers.forEach(b => add(b.reason, b.repair_action, 'Approve'));
  if (rows.length === 0) return null;
  const tagColor = g => g.startsWith('Post') ? 'var(--badge-red-text)'
    : g === 'Approve' ? 'var(--badge-amber-text, var(--text-2))'
    : 'var(--text-2)';
  return (
    <div data-testid="proforma-blocker-panel" style={{
      background: 'var(--card)',
      borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
      borderTop: '1px solid var(--border)',
      padding: '12px 24px',
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
        What&rsquo;s blocking — {rows.length} item{rows.length === 1 ? '' : 's'} across approve / post / convert / export
      </div>
      {rows.map((r, i) => (
        <div key={i} data-testid={`proforma-blocker-row-${i}`} style={{ fontSize: 12, marginBottom: 5 }}>
          <span style={{
            display: 'inline-block', fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
            color: tagColor(r.gates), border: `1px solid var(--border)`, borderRadius: 4,
            padding: '0 6px', marginRight: 8, verticalAlign: 'middle',
          }}>{r.gates}</span>
          <span style={{ color: 'var(--text)' }}>{r.reason}</span>
          {r.repair && (
            <div style={{ color: 'var(--text-dim, var(--text))', opacity: 0.75, paddingLeft: 14 }}>
              Fix: {r.repair}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Readiness + overbill panels — pure display of backend gate state ──────────
function ProformaReadinessPanel({
  readinessPost, linesByCode,
  resolvingDesign, resolveError, doResolveAmbiguity,
  savingVat, vatSaveError, doSaveEuVat,
  draftLines, reloadReadiness, draftId,
  blockerPanelReasons,  // Set<string> — reasons already shown by ProformaBlockerPanel (Slice 5 dedup)
}) {
  // Slice 5: filter out blocker entries whose reason text is already rendered by
  // ProformaBlockerPanel above. Gating is unchanged — this is display-only.
  const _shownAbove = (blockerPanelReasons instanceof Set) ? blockerPanelReasons : new Set();
  return (
    <React.Fragment>
      {readinessPost && !readinessPost.ready && (
        <div data-testid="readiness-panel" style={{
          background: 'var(--card)',
          borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
          borderTop: '1px solid var(--border)',
          padding: '12px 24px',
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 6 }}>
            ⛔ Not ready — {(readinessPost.blockers || []).length} blocking reason{(readinessPost.blockers || []).length === 1 ? '' : 's'} · Approve / Post / Convert stay gated until resolved
          </div>
          <div data-testid="readiness-panel-blockers-deduped">
            {(readinessPost.blockers || []).filter(b => !_shownAbove.has(b.reason)).map((b, i) => (
              <div key={i} style={{ fontSize: 12, marginBottom: 4 }} data-testid={`readiness-blocker-${i}`}>
                <span style={{ color: 'var(--badge-red-text)' }}>• {b.reason}</span>
                <div style={{ color: 'var(--text-dim, var(--text))', opacity: 0.75, paddingLeft: 14 }}>
                  Fix: {b.repair_action}
                </div>
              </div>
            ))}
          </div>
          {/* ProductMappingResolver — wires wFirma search/adopt/create-and-adopt
              for each unmapped product_code. Only shown when the readiness gate
              surfaces a "not matched in wfirma_products" blocker. */}
          {_parseUnmappedProductCodes(readinessPost.blockers || []).length > 0 && (
            <ProductMappingResolver
              unmappedCodes={_parseUnmappedProductCodes(readinessPost.blockers || [])}
              draftLines={draftLines || []}
              reloadReadiness={reloadReadiness || (() => {})}
            />
          )}
          {readinessPost.vat_resolution && readinessPost.vat_resolution.needs_save_to_master && (
            <div data-testid="readiness-vat-resolver"
                 style={{ marginTop: 8, padding: '8px 10px', border: '1px solid var(--border)',
                          borderRadius: 6, background: 'var(--bg)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--text)' }}>
                EU VAT for WDT — confirm &amp; save to Customer Master
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-2, var(--text))', opacity: 0.85, marginBottom: 6 }}>
                {'Tax number '}
                <strong style={{ fontFamily: 'monospace' }}>{readinessPost.vat_resolution.candidate_vat}</strong>
                {' is on file (nip) but the canonical EU-VAT field is blank. WDT (intra-EU 0%) requires it in Customer Master. This does not change vat_mode or bypass the rule — it saves the VAT into vat_eu_number so VIES can verify it.'}
              </div>
              <button
                data-testid="btn-save-eu-vat"
                disabled={savingVat}
                onClick={() => doSaveEuVat(readinessPost.vat_resolution)}
                style={{ background: 'var(--accent, #c9a456)', color: '#1a1a1a', border: 'none',
                         borderRadius: 4, fontSize: 12, fontWeight: 600, padding: '5px 12px',
                         cursor: savingVat ? 'default' : 'pointer', opacity: savingVat ? 0.6 : 1 }}
              >
                {savingVat ? '⏳ Saving…'
                  : `Save EU VAT ${readinessPost.vat_resolution.candidate_vat} to Customer Master`}
              </button>
              {vatSaveError && (
                <div data-testid="readiness-vat-save-error"
                     style={{ color: 'var(--badge-red-text)', fontSize: 11, marginTop: 4 }}>
                  {vatSaveError}
                </div>
              )}
            </div>
          )}
          {Object.keys(readinessPost.ambiguous_designs || {}).length > 0 && (
            <div style={{ marginTop: 8 }} data-testid="readiness-ambiguity-resolver">
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text)' }}>
                Resolve design ambiguity — click the exact product_code to bill:
              </div>
              {Object.entries(readinessPost.ambiguous_designs).map(([design, codes]) => (
                <div key={design} data-testid={`ambiguity-row-${design}`}
                     style={{ marginBottom: 8, paddingBottom: 6, borderBottom: '1px dashed var(--border)' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-2, var(--text))', marginBottom: 4 }}>
                    {'design '}
                    <span style={{ fontFamily: 'monospace', color: 'var(--text)' }}>{design}</span>
                    {' — pick the line to bill:'}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {(codes || []).map(c => {
                      const ev = linesByCode[c];
                      return (
                        <button
                          key={c}
                          data-testid={`ambiguity-choice-${design}-${c}`}
                          disabled={!!resolvingDesign}
                          onClick={() => doResolveAmbiguity(design, c)}
                          title={ev ? `${ev.name || ''} · qty ${ev.qty} · ${ev.value.toFixed(2)} ${ev.currency}` : 'no line evidence on draft'}
                          style={{ background: 'var(--card)', color: 'var(--text)',
                                   border: '1px solid var(--border)', borderRadius: 6,
                                   fontSize: 12, padding: '4px 8px', textAlign: 'left',
                                   cursor: resolvingDesign ? 'default' : 'pointer',
                                   opacity: resolvingDesign && resolvingDesign !== design ? 0.5 : 1 }}
                        >
                          <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>{c}</div>
                          {ev && (
                            <div style={{ fontSize: 10, color: 'var(--text-2, var(--text))', opacity: 0.8 }}>
                              {(ev.name ? ev.name + ' · ' : '')}{`qty ${ev.qty} · ${ev.value.toFixed(2)} ${ev.currency}`}
                            </div>
                          )}
                        </button>
                      );
                    })}
                    {resolvingDesign === design && (
                      <span style={{ fontSize: 11, color: 'var(--text)', alignSelf: 'center' }}>⏳ saving…</span>
                    )}
                  </div>
                </div>
              ))}
              {resolveError && (
                <div style={{ color: 'var(--badge-red-text)', fontSize: 11 }} data-testid="readiness-resolve-error">
                  {resolveError}
                </div>
              )}
            </div>
          )}
          {(readinessPost.warnings || []).length > 0 && (
            <div style={{ marginTop: 6 }}>
              {readinessPost.warnings.map((w, i) => (
                <div key={i} style={{ fontSize: 11, color: 'var(--badge-amber-text, var(--text))' }}>⚠ {w}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {readinessPost && (readinessPost.duplicate_product_codes || []).length > 0 && (
        <div data-testid="overbill-evidence-panel" style={{
          background: 'var(--card)',
          borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
          borderTop: '1px solid var(--border)',
          padding: '12px 24px',
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
            Product-code billing — purchase lots billed across multiple lines
          </div>
          <div style={{ fontSize: 11, color: 'var(--text)', opacity: 0.7, marginBottom: 8 }}>
            {'A product_code is one purchase-invoice lot and may legitimately span several designs. Billing within the available packing quantity is fine; an over-bill (billed > available) is a double-bill and blocks Approve / Post / Convert.'}
          </div>
          {(readinessPost.duplicate_product_codes || []).map((d) => {
            const over = !!d.over_billed;
            const designs = d.design_nos || [];
            const tid = String(d.product_code || '').replace(/[^a-zA-Z0-9_-]/g, '-');
            return (
              <div key={d.product_code} data-testid={`overbill-row-${tid}`}
                   style={{ marginBottom: 8, paddingBottom: 6, borderBottom: '1px dashed var(--border)' }}>
                <div style={{ fontSize: 12, color: over ? 'var(--badge-red-text)' : 'var(--text)' }}>
                  {over ? '⛔ ' : '• '}
                  <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{d.product_code}</span>
                  {d.invoice_no ? <span style={{ opacity: 0.7 }}>{` · invoice ${d.invoice_no}`}</span> : null}
                </div>
                <div style={{ fontSize: 11, marginTop: 2 }}>
                  <span style={{ color: over ? 'var(--badge-red-text)' : 'var(--text)', fontWeight: over ? 600 : 400 }}>
                    {`billed ${+d.billed_qty} / available ${+d.available_qty}`}
                  </span>
                  <span style={{ color: 'var(--text)', opacity: 0.7 }}>
                    {`  ·  ${d.line_count} line${d.line_count === 1 ? '' : 's'}  ·  ${designs.length} design${designs.length === 1 ? '' : 's'}`}
                  </span>
                  {over && (
                    <span data-testid={`overbill-flag-${tid}`}
                          style={{ color: 'var(--badge-red-text)', fontWeight: 600 }}>
                      {'  ·  OVER-BILLED — see blocker above'}
                    </span>
                  )}
                </div>
                {designs.length > 0 && (
                  <div data-testid={`overbill-designs-${tid}`}
                       style={{ fontSize: 10, color: 'var(--text)', opacity: 0.65, marginTop: 2, fontFamily: 'monospace' }}>
                    {designs.slice(0, 12).join(', ')}{designs.length > 12 ? ` +${designs.length - 12} more` : ''}
                  </div>
                )}
                {over && (d.unassigned_packing || []).length > 0 && (
                  <UnassignedPackingAssigner
                    draftId={draftId}
                    productCode={d.product_code}
                    unassignedPacking={d.unassigned_packing}
                    reloadReadiness={reloadReadiness}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </React.Fragment>
  );
}

// ── Party cards + address authority bar ───────────────────────────────────────
function ProformaPartyCards({
  exporter, customer, shipTo,
  bo, canEdit, liveDraft, draft, draftHook,
  addrApplying, addrApplyError, handleApplyCustomerAddress,
  setBuyerEditFields, setBuyerEditError, setBuyerEditOpen,
  onOpenCustomerPicker, onOpenRecipientPicker, onCopyToRecipient,
  draftState,
}) {
  const lockedForEdit = !canEdit;
  const addrSource = bo._source === 'customer_master' ? 'customer_master'
    : (bo.name || bo.street) ? 'manual' : 'none';
  const addrSourceLabel = addrSource === 'customer_master'
    ? { text: 'Customer Master', color: 'var(--accent)' }
    : addrSource === 'manual'
    ? { text: 'Manual', color: 'var(--text-2)' }
    : { text: 'Not set', color: 'var(--text-3, #aaa)' };
  const hasOverride = !!(bo.name || bo.street);
  return (
    <React.Fragment>
      {/* Party cards strip — wireframe band on --bg-subtle. Wireframe shows
          Exporter / Customer / Currency & Payment; the live RECIPIENT card is
          KEPT as an existing capability (Lesson M) → 4 cards, auto-fit grid. */}
      <div style={{
        background: 'var(--bg-subtle)',
        padding: '20px 32px 12px',
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14,
      }}>
        <div style={{ display: 'contents' }}>
          <ProformaPartyCard
            title="Exporter"
            name={exporter.name}
            lines={[exporter.address, exporter.country]}
            footer={`VAT EU: ${exporter.vatEu}`}
            data-testid="party-seller"
          />
          <ProformaPartyCard
            title="Customer"
            name={customer.name}
            lines={[customer.address, customer.country]}
            footer={customer.vatEuFromNip
              ? `VAT EU: ${customer.vatEu} · on file (not yet saved as EU VAT)`
              : `VAT EU: ${customer.vatEu}`}
            warn={!customer.wfirmaId}
            warnMsg={!customer.wfirmaId ? '⚠ No wFirma mapping' : null}
            mappedMsg={customer.wfirmaId
              ? (customer.wfirmaName ? `✓ Mapped to wFirma: ${customer.wfirmaName}` : '✓ Mapped to wFirma')
              : null}
            data-testid="party-buyer"
          />
          <ProformaPartyCard
            title="Recipient"
            name={shipTo.name}
            lines={[shipTo.address, shipTo.country]}
            footer={liveDraft.ship_to_override && liveDraft.ship_to_override.name
              ? 'Ship-to override' : 'Same as Buyer'}
            footerMuted
            data-testid="party-recipient"
          />
          {/* Currency & Payment (wireframe card). Read-only projections of
              draft-stored values — no new authority, no calculation. */}
          <div data-testid="party-currency-payment" style={{
            background: 'var(--card)', border: '1px solid var(--border)',
            borderRadius: 8, padding: 14, boxShadow: '0 1px 2px var(--shadow)',
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
              Currency &amp; Payment
            </div>
            <InfoRow label="Currency" value={
              liveDraft.exchange_rate
                ? `${liveDraft.currency || '—'} · ${liveDraft.nbp_table || 'NBP'} ${Number(liveDraft.exchange_rate).toFixed(4)}`
                : (liveDraft.currency || '—')
            } />
            <InfoRow label="NBP Table" value={liveDraft.nbp_table_number || '—'} mono />
            <InfoRow label="Payment Terms" value={
              (liveDraft.payment_terms && (liveDraft.payment_terms.method || liveDraft.payment_terms.days != null))
                ? [liveDraft.payment_terms.method || 'Bank transfer',
                   liveDraft.payment_terms.days != null ? `${liveDraft.payment_terms.days} days` : null]
                    .filter(Boolean).join(' · ')
                : (liveDraft.wfirma_payment_method || '—')
            } />
            <InfoRow label="Incoterm" value={liveDraft.incoterm || '—'} />
          </div>
        </div>
      </div>

      {/* Address authority bar — kept capability (Lesson M), lives in the
          wireframe party band */}
      <div data-testid="address-authority-bar" style={{
        background: 'var(--bg-subtle)',
        borderBottom: '1px solid var(--border)',
        padding: '4px 32px 14px',
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 12, color: 'var(--text-2)', marginRight: 4 }}>Address authority:</span>
        <span data-testid="addr-source-badge" style={{
          fontSize: 11, fontWeight: 700, color: addrSourceLabel.color,
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '1px 7px',
        }}>{addrSourceLabel.text}</span>

        <button
          data-testid="btn-load-from-cm"
          disabled={lockedForEdit || addrApplying}
          title={lockedForEdit
            ? `Cannot apply Customer Master: draft is in '${draftState}' state`
            : 'Apply billing/shipping address from Customer Master to this draft'}
          onClick={handleApplyCustomerAddress}
          style={{
            fontSize: 12, padding: '3px 10px', marginLeft: 4,
            background: lockedForEdit ? 'var(--bg)' : 'var(--accent)',
            color: lockedForEdit ? 'var(--text-2)' : '#fff',
            border: '1px solid var(--border)', borderRadius: 4,
            cursor: lockedForEdit ? 'not-allowed' : 'pointer',
            opacity: lockedForEdit ? 0.5 : 1,
          }}
        >{addrApplying ? '⏳ Applying…' : '↓ Load from Customer Master'}</button>

        <button
          data-testid="btn-edit-bill-to"
          disabled={lockedForEdit}
          title={lockedForEdit
            ? `Cannot edit: draft is in '${draftState}' state`
            : 'Manually edit bill-to fields'}
          onClick={() => {
            setBuyerEditFields({
              name:    bo.name    || '',
              street:  bo.street  || '',
              city:    bo.city    || '',
              zip:     bo.zip     || '',
              country: bo.country || '',
              vat_id:  bo.vat_id  || '',
            });
            setBuyerEditError(null);
            setBuyerEditOpen(true);
          }}
          style={{
            fontSize: 12, padding: '3px 10px',
            background: 'var(--bg)', color: lockedForEdit ? 'var(--text-2)' : 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 4,
            cursor: lockedForEdit ? 'not-allowed' : 'pointer',
            opacity: lockedForEdit ? 0.5 : 1,
          }}
        >✎ Edit Bill-to</button>

        <button
          data-testid="btn-change-customer"
          disabled={lockedForEdit}
          title={lockedForEdit
            ? `Cannot change customer: draft is in '${draftState}' state`
            : 'Replace the bill-to customer with a Customer Master contractor (search by name / VAT / ID)'}
          onClick={() => { if (!lockedForEdit) onOpenCustomerPicker && onOpenCustomerPicker(); }}
          style={{
            fontSize: 12, padding: '3px 10px',
            background: 'var(--bg)', color: lockedForEdit ? 'var(--text-2)' : 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 4,
            cursor: lockedForEdit ? 'not-allowed' : 'pointer', opacity: lockedForEdit ? 0.5 : 1,
          }}
        >⇄ Change Customer</button>

        <button
          data-testid="btn-change-recipient"
          disabled={lockedForEdit}
          title={lockedForEdit
            ? `Cannot change recipient: draft is in '${draftState}' state`
            : 'Replace the ship-to recipient with a Customer Master contractor (independent of the bill-to customer)'}
          onClick={() => { if (!lockedForEdit) onOpenRecipientPicker && onOpenRecipientPicker(); }}
          style={{
            fontSize: 12, padding: '3px 10px',
            background: 'var(--bg)', color: lockedForEdit ? 'var(--text-2)' : 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 4,
            cursor: lockedForEdit ? 'not-allowed' : 'pointer', opacity: lockedForEdit ? 0.5 : 1,
          }}
        >⇄ Change Recipient</button>

        <button
          data-testid="btn-copy-to-recipient"
          disabled={lockedForEdit}
          title={lockedForEdit
            ? `Cannot copy: draft is in '${draftState}' state`
            : 'Copy the bill-to address onto the recipient (ship-to)'}
          onClick={() => { if (!lockedForEdit) onCopyToRecipient && onCopyToRecipient(); }}
          style={{
            fontSize: 12, padding: '3px 10px',
            background: 'var(--bg)', color: lockedForEdit ? 'var(--text-2)' : 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 4,
            cursor: lockedForEdit ? 'not-allowed' : 'pointer', opacity: lockedForEdit ? 0.5 : 1,
          }}
        >⧉ Copy → Recipient</button>

        {hasOverride && (
          <button
            data-testid="btn-clear-buyer-override"
            disabled={lockedForEdit}
            title={lockedForEdit
              ? `Cannot clear: draft is in '${draftState}' state`
              : 'Clear buyer address override — revert to draft client name only'}
            onClick={() => {
              if (lockedForEdit) return;
              const id = liveDraft.id || (draft && draft.id);
              const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
              window.PzApi.patchDraft(id, { buyer_override: {} }, updatedAt)
                .then(r => r && r.ok && draftHook && draftHook.reload && draftHook.reload());
            }}
            style={{
              fontSize: 12, padding: '3px 10px',
              background: 'var(--bg)', color: lockedForEdit ? 'var(--text-2)' : 'var(--text)',
              border: '1px solid var(--border)', borderRadius: 4,
              cursor: lockedForEdit ? 'not-allowed' : 'pointer',
              opacity: lockedForEdit ? 0.5 : 1,
            }}
          >✕ Clear override</button>
        )}

        {addrApplyError && (
          <span data-testid="addr-apply-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginLeft: 4 }}>
            {addrApplyError}
          </span>
        )}
      </div>
    </React.Fragment>
  );
}

// ── Wave 4 Item 11: Source & Extraction tab (advisory, read-only) ───────────
// WIRED: GET /api/v1/proforma/draft/{id}/extraction — a thin read composition
// over EXISTING authorities (draft editable_lines + Customer Master + Product
// Master + Import/Packing). Every signal here is ADVISORY (Lesson N): it never
// blocks Approve / Post / Convert, and it writes nothing.
function SourceExtractionTab({ draftId, batchId, expectedUpdatedAt, onSaved }) {
  const [data,    setData]    = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error,   setError]   = React.useState(null);
  // ── Editable review state (reuse-only: PATCH /lines/{id} + enrich-from-product-descriptions) ──
  const [editing,  setEditing]  = React.useState(null);   // line_id being edited
  const [editQty,  setEditQty]  = React.useState('');
  const [editCode, setEditCode] = React.useState('');
  const [saving,   setSaving]   = React.useState(false);
  const [rowErr,   setRowErr]   = React.useState({});      // line_id -> message (Authority Gap)
  const [options,  setOptions]  = React.useState(null);    // Product Master options (lazy)
  const [recheck,  setRecheck]  = React.useState({ busy: false, msg: null, err: null });
  const [confirmBusy, setConfirmBusy] = React.useState(null);  // line_id being confirmed
  const [confirmErr,  setConfirmErr]  = React.useState({});    // line_id -> message

  const reload = React.useCallback(() => {
    if (!draftId) { setLoading(false); return Promise.resolve(); }
    setLoading(true); setError(null);
    return window.EstrellaShared.apiFetch(`/api/v1/proforma/draft/${draftId}/extraction`)
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e && e.message ? e.message : 'Failed to load'); setLoading(false); });
  }, [draftId]);
  React.useEffect(() => { let a = true; if (a) reload(); return () => { a = false; }; }, [reload]);

  // Product Master option list — lazy, reuses GET /proforma/product-options. No hardcoded list.
  const loadOptions = React.useCallback(() => {
    if (options) return;
    window.PzApi.getProductOptions()
      .then(r => setOptions((r && r.data && r.data.options) || (r && r.options) || []))
      .catch(() => setOptions([]));
  }, [options]);

  const startEdit = (ln) => {
    setEditing(ln.line_id); setEditQty(String(ln.quantity != null ? ln.quantity : ''));
    setEditCode(ln.product_code || ''); setRowErr(p => ({ ...p, [ln.line_id]: null })); loadOptions();
  };
  const cancelEdit = () => { setEditing(null); setSaving(false); };

  const saveRow = (ln) => {
    if (!expectedUpdatedAt) { setRowErr(p => ({ ...p, [ln.line_id]: 'Draft lock unavailable — reopen the draft and retry.' })); return; }
    const patch = {};
    const q = parseFloat(editQty);
    if (!isNaN(q) && q !== Number(ln.quantity)) patch.qty = q;
    const code = (editCode || '').trim();
    // product_code IS a writable editable-line field (EDITABLE_LINE_FIELDS) — remap
    // persists via PATCH /draft/{id}/lines/{line_id}. No authority gap.
    if (code && code !== (ln.product_code || '')) patch.product_code = code;   // map from Product Master
    if (Object.keys(patch).length === 0) { setEditing(null); return; }
    setSaving(true); setRowErr(p => ({ ...p, [ln.line_id]: null }));
    window.PzApi.patchDraftLine(draftId, ln.line_id, patch, expectedUpdatedAt)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && r.error) || 'Save rejected');
        setEditing(null); setSaving(false);
        if (onSaved) onSaved();
        return reload();
      })
      .catch(e => {
        setSaving(false);
        // Genuine failure surface — lock conflict (updated_at mismatch), blank
        // code, or transport error. NOT an authority gap: the field is writable.
        setRowErr(p => ({ ...p, [ln.line_id]: (e && e.message) || 'Save failed' }));
      });
  };

  const recheckMapping = () => {
    if (!expectedUpdatedAt) { setRecheck({ busy: false, msg: null, err: 'Authority Gap — draft lock unavailable.' }); return; }
    setRecheck({ busy: true, msg: null, err: null });
    window.EstrellaShared.apiFetch(`/api/v1/proforma/draft/${draftId}/enrich-from-product-descriptions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_updated_at: expectedUpdatedAt }),
    })
      .then(r => { setRecheck({ busy: false, msg: `Re-checked · ${(r && r.enriched_count) || 0} enriched from Product Master · confirmed rows preserved`, err: null }); if (onSaved) onSaved(); return reload(); })
      .catch(e => setRecheck({ busy: false, msg: null, err: (e && e.message) || 'Re-check failed' }));
  };

  // Operator review-state authority: record the CURRENT authoritative decision
  // for a mapped product_code. Uses PzApi (X-Operator injected). Never rewrites
  // machine extraction evidence; the confidence % stays visible as history.
  const confirmReview = (ln) => {
    const code = (ln.product_code || '').trim();
    if (!code) { setConfirmErr(p => ({ ...p, [ln.line_id]: 'Map a product code before confirming.' })); return; }
    setConfirmBusy(ln.line_id); setConfirmErr(p => ({ ...p, [ln.line_id]: null }));
    window.PzApi.confirmProductReview(draftId, code, expectedUpdatedAt)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && r.error) || 'Confirm rejected');
        setConfirmBusy(null);
        if (onSaved) onSaved();
        return reload();
      })
      .catch(e => { setConfirmBusy(null); setConfirmErr(p => ({ ...p, [ln.line_id]: (e && e.message) || 'Confirm failed' })); });
  };

  const box  = { padding: '16px 18px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12.5, lineHeight: 1.6 };
  const conf = (c) => (c === null || c === undefined) ? '—' : `${Math.round(c * 100)}%`;
  // Confidence coloring (advisory): high ≥85% green, medium ≥60% amber, low <60% red.
  // Purely visual over the existing extracted_confidence value — no threshold gates any action.
  const confColor = (c) => (c === null || c === undefined) ? 'var(--text-3)'
    : (c >= 0.85 ? 'var(--badge-green-text, #2e7d32)' : (c >= 0.60 ? 'var(--badge-amber-text)' : 'var(--badge-red-text)'));
  const iBtn = { padding: '3px 9px', fontSize: 11, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', cursor: 'pointer' };
  const iIn  = { padding: '3px 6px', fontSize: 11, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' };

  const docs           = (data && data.source_documents) || [];
  const lines          = (data && data.lines) || [];
  const cm             = (data && data.customer_match) || null;
  const custUnmatched  = !!(data && data.customer_unmatched);
  const unmatchedCount = (data && data.unmatched_count) || 0;

  return (
    <div data-testid="pf-detail-source">
      <PfSectionLabel>Source document</PfSectionLabel>
      <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 12 }}>
        Advisory only — extraction confidence and match status never block Approve, Post, or Convert.
      </div>

      {/* Source Bundle — batch-scoped source docs; own loading/error, never gates the extraction UI below. */}
      <window.SourceBundleCard batchId={batchId} />

      {loading && <div data-testid="pf-source-loading" style={{ ...box, color: 'var(--text-3)' }}>Loading extraction…</div>}
      {!loading && error && <div data-testid="pf-source-error" style={{ ...box, color: 'var(--badge-red-text)', borderColor: 'var(--badge-red-text)' }}>Could not load: {error}</div>}

      {!loading && !error && (
        <React.Fragment>
          {/* Packing-list source (Import/Packing authority) — batch-scoped by design */}
          <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', margin: '4px 0 2px' }}>Batch source documents</div>
          <div data-testid="pf-source-scope-note" style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 6 }}>
            Source documents are batch-scoped; the rows below are draft-scoped (this proforma only).
          </div>
          {docs.length === 0
            ? <div data-testid="pf-source-nodocs" style={{ ...box, color: 'var(--text-3)' }}>No packing document recorded for this batch.</div>
            : <div style={{ ...box, padding: 0, overflow: 'hidden' }}>
                {docs.map((doc, i) => (
                  <div key={doc.document_id || i} data-testid="pf-source-doc" style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 14px', borderBottom: i < docs.length - 1 ? '1px solid var(--border)' : 'none' }}>
                    <span style={{ color: 'var(--text)' }}>{doc.file_name || doc.invoice_no || doc.document_id}</span>
                    <span style={{ color: 'var(--text-3)' }}>{doc.extraction_status}</span>
                  </div>
                ))}
              </div>}

          {/* Customer Master match (advisory) */}
          <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', margin: '14px 0 6px' }}>Customer Master match</div>
          <div data-testid="pf-source-customer" style={{ ...box }}>
            <span style={{ color: custUnmatched ? 'var(--badge-amber-text)' : 'var(--text)', fontWeight: 600 }}>
              {custUnmatched
                ? (cm && cm.ambiguous ? 'Ambiguous — needs operator mapping' : 'Unmatched — needs operator mapping')
                : (cm && (cm.resolved_wfirma_name || 'Matched'))}
            </span>
            {cm && cm.match_strategy && cm.match_strategy !== 'none' && (
              <span style={{ color: 'var(--text-3)', marginLeft: 8 }}>· {cm.match_strategy}</span>
            )}
          </div>

          {/* Per-row extraction + Product Master match — editable review path */}
          <div style={{ display: 'flex', alignItems: 'center', margin: '14px 0 6px' }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)' }}>
              Rows &amp; extraction
              {unmatchedCount > 0 && (
                <span data-testid="pf-source-unmatched-count" style={{ color: 'var(--badge-amber-text)', fontWeight: 600, marginLeft: 8 }}>
                  {unmatchedCount} unmatched
                </span>
              )}
            </div>
            <div style={{ flex: 1 }} />
            <button data-testid="pf-source-recheck" onClick={recheckMapping} disabled={recheck.busy} style={{ ...iBtn, opacity: recheck.busy ? 0.6 : 1 }}>
              {recheck.busy ? '↻ Re-checking…' : '↻ Re-check mapping (Product Master)'}
            </button>
          </div>
          {recheck.msg && <div data-testid="pf-source-recheck-msg" style={{ fontSize: 11, color: 'var(--badge-green-text)', marginBottom: 6 }}>{recheck.msg}</div>}
          {recheck.err && <div data-testid="pf-source-recheck-err" style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginBottom: 6 }}>Re-check failed · {recheck.err}</div>}
          {lines.length === 0
            ? <div style={{ ...box, color: 'var(--text-3)' }}>No draft lines.</div>
            : <div style={{ ...box, padding: 0, overflow: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: 'var(--text-3)', textAlign: 'left' }}>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }}>Product</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }}>Design</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }}>Description</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600, textAlign: 'right' }}>Qty</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }} title="Immutable historical extraction evidence — never a gate, never overwritten by review.">Machine confidence</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }}>Product Master</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }} title="Current operator authority. Green = operator confirmed.">Review</th>
                      <th style={{ padding: '8px 12px', fontWeight: 600 }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((ln, i) => {
                      const isEdit = editing === ln.line_id;
                      return (
                      <React.Fragment key={ln.line_id || i}>
                      <tr data-testid="pf-source-row" style={{ borderTop: '1px solid var(--border)', background: ln.unmatched ? 'var(--badge-amber-bg, transparent)' : 'transparent' }}>
                        <td style={{ padding: '8px 12px', color: 'var(--text)' }}>
                          {isEdit
                            ? <select data-testid="pf-source-map-select" value={editCode} onChange={e => setEditCode(e.target.value)} style={{ ...iIn, maxWidth: 200 }}>
                                <option value="">— map from Product Master —</option>
                                {(options || []).map(o => <option key={o.product_code} value={o.product_code}>{o.product_code}{o.name_pl ? ` · ${o.name_pl}` : ''}</option>)}
                              </select>
                            : (ln.product_code || <span style={{ color: 'var(--badge-amber-text)' }}>— no code</span>)}
                        </td>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2, var(--text))' }}>{ln.design_no || '—'}</td>
                        <td style={{ padding: '8px 12px', color: 'var(--text-2, var(--text))', maxWidth: 200, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ln.name || '—'}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                          {isEdit
                            ? <input data-testid="pf-source-edit-qty" type="number" min="0" step="1" value={editQty} onChange={e => setEditQty(e.target.value)} style={{ ...iIn, width: 64, textAlign: 'right' }} />
                            : (ln.quantity != null ? ln.quantity : '—')}
                        </td>
                        <td style={{ padding: '8px 12px', fontWeight: 600, color: confColor(ln.extracted_confidence) }} data-testid="pf-source-confidence">
                          <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: confColor(ln.extracted_confidence), marginRight: 6, verticalAlign: 'middle' }} />
                          {conf(ln.extracted_confidence)}
                        </td>
                        <td style={{ padding: '8px 12px' }}>
                          {ln.product_matched
                            ? <span style={{ color: 'var(--badge-green-text, #2e7d32)' }}>✓ matched</span>
                            : <span data-testid="pf-source-row-unmatched" style={{ color: 'var(--badge-amber-text)' }}>unmatched</span>}
                        </td>
                        <td style={{ padding: '8px 12px' }} data-testid="pf-source-review-status">
                          {/* Operator review authority drives this badge (never a gate).
                              Green = OPERATOR CONFIRMED, not machine-accepted. The
                              confidence % is separate, immutable historical evidence. */}
                          {ln.operator_status === 'confirmed' && !ln.review_required
                            ? <span style={{ color: 'var(--badge-green-text, #2e7d32)', fontWeight: 600 }}
                                    title={ln.operator_confirmed_by ? `Confirmed by ${ln.operator_confirmed_by}${ln.operator_confirmed_at ? ' · ' + ln.operator_confirmed_at : ''}` : undefined}>✓ Operator confirmed</span>
                            : (ln.review_reason === 'source_changed'
                                ? <span style={{ color: 'var(--badge-amber-text)', fontWeight: 600 }} title="Source changed since confirmation — re-confirm the mapping.">⟳ Re-check required</span>
                                : (ln.unmatched
                                    ? <span style={{ color: 'var(--badge-amber-text)', fontWeight: 600 }}>● Needs mapping</span>
                                    : (ln.requires_manual_review
                                        ? <span style={{ color: 'var(--badge-amber-text)', fontWeight: 600 }}>● Needs review</span>
                                        : <span style={{ color: 'var(--text-2, var(--text))', fontWeight: 600 }}>● Suggested</span>)))}
                        </td>
                        <td style={{ padding: '8px 12px', whiteSpace: 'nowrap' }}>
                          {isEdit ? (
                            <React.Fragment>
                              <button data-testid="pf-source-save" onClick={() => saveRow(ln)} disabled={saving} style={{ ...iBtn, marginRight: 6, background: 'var(--accent)', color: 'var(--accent-text)', borderColor: 'var(--accent-border, var(--accent))', opacity: saving ? 0.6 : 1 }}>{saving ? 'Saving…' : 'Save'}</button>
                              <button data-testid="pf-source-cancel" onClick={cancelEdit} disabled={saving} style={iBtn}>Cancel</button>
                            </React.Fragment>
                          ) : (
                            <React.Fragment>
                              <button data-testid="pf-source-edit" onClick={() => startEdit(ln)} style={{ ...iBtn, marginRight: 6 }}>Edit / Map</button>
                              {ln.product_code && !(ln.operator_status === 'confirmed' && !ln.review_required) && (
                                <button data-testid="pf-source-confirm" onClick={() => confirmReview(ln)} disabled={confirmBusy === ln.line_id}
                                        style={{ ...iBtn, color: 'var(--badge-green-text, #2e7d32)', borderColor: 'var(--badge-green-text, #2e7d32)', opacity: confirmBusy === ln.line_id ? 0.6 : 1 }}>
                                  {confirmBusy === ln.line_id ? 'Confirming…' : (ln.review_reason === 'source_changed' ? 'Re-confirm' : 'Confirm')}
                                </button>
                              )}
                            </React.Fragment>
                          )}
                        </td>
                      </tr>
                      {rowErr[ln.line_id] && (
                        <tr><td colSpan={8} data-testid="pf-source-row-error" style={{ padding: '4px 12px 8px', fontSize: 11, color: 'var(--badge-amber-text)' }}>Save failed · {rowErr[ln.line_id]}</td></tr>
                      )}
                      {confirmErr[ln.line_id] && (
                        <tr><td colSpan={8} data-testid="pf-source-confirm-error" style={{ padding: '4px 12px 8px', fontSize: 11, color: 'var(--badge-amber-text)' }}>Confirm failed · {confirmErr[ln.line_id]}</td></tr>
                      )}
                      </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>}

          {/* Legend + honest scope of the review data. Confidence/status are
              advisory (Lesson N). A raw extracted-vs-current field diff is NOT
              shown because no original-extraction snapshot is retained by any
              authority — the extraction read composes over current line state. */}
          {lines.length > 0 && (
            <div data-testid="pf-source-legend" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 8, lineHeight: 1.6 }}>
              <span style={{ color: 'var(--badge-green-text, #2e7d32)' }}>● ≥85% high</span>{'  ·  '}
              <span style={{ color: 'var(--badge-amber-text)' }}>● 60–85% medium / needs review</span>{'  ·  '}
              <span style={{ color: 'var(--badge-red-text)' }}>● &lt;60% low</span>
              <div data-testid="pf-source-diff-note" style={{ marginTop: 4 }}>
                <strong style={{ color: 'var(--text-2, var(--text))' }}>Machine confidence vs operator review:</strong> the
                percentage is immutable historical extraction evidence. The <em>Review</em> badge is the current
                operator authority — it reads <span style={{ color: 'var(--badge-green-text, #2e7d32)' }}>Operator confirmed</span> once
                you <em>Confirm</em> a mapping, and reopens only if the source changes on re-import. Confirming never
                rewrites the confidence. A per-field extracted-vs-current diff is not retained (historical comparison
                unavailable); use <em>Edit / Map</em> to correct, then <em>Confirm</em>.
              </div>
            </div>
          )}
        </React.Fragment>
      )}
    </div>
  );
}

// ── Logistics tracking (reuse-only) ─────────────────────────────────────────────
// Real shipment timeline + customs clearance status, both batch-scoped and read
// from the LOCAL audit log (no live carrier call). Reuses:
//   GET /api/v1/tracking/shipment/{batch_id}/timeline   (cookie auth)
//   GET /api/v1/dhl/clearance-status/{batch_id}
// Advisory only — never a fiscal gate.
function LogisticsTracking({ batchId }) {
  const [tl,      setTl]      = React.useState(null);   // timeline entries
  const [clr,     setClr]     = React.useState(null);   // clearance status
  const [loading, setLoading] = React.useState(true);
  const [err,     setErr]     = React.useState(null);

  React.useEffect(() => {
    let alive = true;
    if (!batchId) { setLoading(false); return; }
    setLoading(true); setErr(null);
    const af = window.EstrellaShared.apiFetch;
    Promise.allSettled([
      af(`/api/v1/tracking/shipment/${encodeURIComponent(batchId)}/timeline`),
      af(`/api/v1/dhl/clearance-status/${encodeURIComponent(batchId)}`),
    ]).then(([t, c]) => {
      if (!alive) return;
      if (t.status === 'fulfilled') setTl((t.value && t.value.timeline) || []);
      else setErr((t.reason && t.reason.message) || 'timeline unavailable');
      if (c.status === 'fulfilled' && c.value && c.value.found !== false) setClr(c.value);
      setLoading(false);
    });
    return () => { alive = false; };
  }, [batchId]);

  const box = { padding: '12px 16px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8 };
  // Return only PRIMITIVE field values — audit-timeline entries carry structured
  // object details (e.g. detail={clearance_path,...}); rendering an object as a
  // React child throws (React #31). Objects are skipped so the row degrades to '—'.
  const pick = (e, keys) => { for (const k of keys) { const v = e && e[k]; if (v != null && typeof v !== 'object') return v; } return ''; };

  return (
    <div data-testid="pf-logistics-tracking" style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>Shipment timeline &amp; clearance</div>
      {loading && <div data-testid="pf-logistics-tracking-loading" style={{ ...box, fontSize: 12, color: 'var(--text-3)' }}>Loading tracking…</div>}

      {!loading && clr && (
        <div style={{ ...box, marginBottom: 10 }} data-testid="pf-logistics-clearance">
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
            <span style={{ color: 'var(--text-3)' }}>Customs clearance</span>
            <span style={{ fontWeight: 700, color: 'var(--text)' }}>{clr.clearance_status || '—'}</span>
          </div>
          {clr.clearance_action && <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 3 }}>Action: {clr.clearance_action}</div>}
          {clr.awb && <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>AWB: <span style={{ fontFamily: 'monospace' }}>{clr.awb}</span>{clr.updated_at ? ` · ${String(clr.updated_at).slice(0,10)}` : ''}</div>}
        </div>
      )}

      {!loading && tl && tl.length > 0 && (
        <div style={{ ...box, padding: 0, overflow: 'hidden' }} data-testid="pf-logistics-timeline">
          {tl.map((e, i) => (
            <div key={i} data-testid="pf-logistics-timeline-row" style={{ display: 'flex', gap: 12, padding: '8px 14px', borderBottom: i < tl.length - 1 ? '1px solid var(--border)' : 'none' }}>
              <span style={{ fontSize: 11, color: 'var(--text-3)', minWidth: 92, fontFamily: 'monospace' }}>{String(pick(e, ['timestamp','time','at','t','date']) || '').slice(0, 16) || '—'}</span>
              <span style={{ fontSize: 12, color: 'var(--text)', flex: 1 }}>
                <strong>{pick(e, ['event','status','label','type','stage']) || '—'}</strong>
                {pick(e, ['location','where','place']) ? <span style={{ color: 'var(--text-3)' }}> · {pick(e, ['location','where','place'])}</span> : null}
                {pick(e, ['detail','message','note','description']) ? <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{pick(e, ['detail','message','note','description'])}</div> : null}
              </span>
            </div>
          ))}
        </div>
      )}

      {!loading && (!tl || tl.length === 0) && !clr && (
        <div style={{ ...box, fontSize: 11.5, color: 'var(--text-3)' }} data-testid="pf-logistics-timeline-empty">
          No shipment timeline or clearance events recorded for this batch yet{err ? ` (${err})` : ''}.
        </div>
      )}
    </div>
  );
}

// ── Documents registry (reuse-only) ─────────────────────────────────────────────
// Lists the REAL documents recorded for this shipment (purchase/sales invoice,
// packing lists) with their extraction/review state. Reuses:
//   GET /api/v1/upload/shipment/{batch_id}/documents   (cookie auth)
// Read-only inventory — no fabricated rows, no fake downloads.
function DocumentsRegistry({ batchId }) {
  // Shared V2 data hook — single fetch implementation, reused by SourceBundleCard.
  const { documents: docs, loading, error: err } = window.useShipmentDocuments(batchId);

  const box = { padding: '12px 16px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8 };
  // Registry rows can carry object-valued enriched fields — coerce to a safe
  // primitive so nothing renders a raw object as a React child (React #31).
  const s = (v) => (v == null || typeof v === 'object') ? '' : v;
  const typeLabel = window.documentTypeLabel;

  return (
    <div data-testid="pf-documents-registry" style={{ marginTop: 20 }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 4 }}>Shipment documents (source registry)</div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 8 }}>
        Real documents recorded for this shipment — batch-scoped. Read-only inventory.
      </div>
      {loading && <div data-testid="pf-documents-registry-loading" style={{ ...box, fontSize: 12, color: 'var(--text-3)' }}>Loading registry…</div>}
      {!loading && err && <div data-testid="pf-documents-registry-err" style={{ ...box, fontSize: 11.5, color: 'var(--badge-amber-text)' }}>Registry unavailable · {err}</div>}
      {!loading && !err && docs && docs.length === 0 && (
        <div data-testid="pf-documents-registry-empty" style={{ ...box, fontSize: 11.5, color: 'var(--text-3)' }}>No source documents registered for this shipment.</div>
      )}
      {!loading && !err && docs && docs.length > 0 && (
        <div style={{ ...box, padding: 0, overflow: 'hidden' }}>
          {docs.map((d, i) => (
            <div key={d.id || d.document_id || i} data-testid="pf-documents-registry-row"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '10px 14px', borderBottom: i < docs.length - 1 ? '1px solid var(--border)' : 'none' }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)' }}>{typeLabel(d.document_type)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                  {[s(d.invoice_no) || s(d.file_name) || s(d.suggested_client_name), (d.line_count != null ? `${d.line_count} lines` : null)].filter(Boolean).join(' · ') || '—'}
                </div>
              </div>
              {s(d.review_state) && (
                <span data-testid="pf-documents-review-state" style={{ flexShrink: 0, fontSize: 10.5, fontWeight: 700, padding: '2px 8px', borderRadius: 999, color: 'var(--text-2)', border: '1px solid var(--border)' }}>{s(d.review_state)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Workflow rail (authority-backed) ───────────────────────────────────────────
// Derived STRICTLY from the proforma-draft state machine (draft_state), which is
// always present on the draft and cross-confirmed by the wFirma authority ids
// (wfirma_proforma_id = posted, wfirma_invoice_id = invoiced). No fabricated
// stage: reservation loads lazily and shipment/customs are SEPARATE authorities
// (Lesson N) with no draft-level state — they are pointed to their own tabs, not
// shown as rail nodes. A wrong stage here would be fake readiness; every node maps
// to a real, always-available signal.
function WorkflowRail({ draftState, wfirmaProformaId, wfirmaInvoiceId }) {
  const st = String(draftState || '').toLowerCase();
  const railBox = { padding: '10px 24px', background: 'var(--card)', borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)' };
  if (st === 'cancelled' || st === 'superseded') {
    return (
      <div data-testid="pf-workflow-rail" style={railBox}>
        <span data-testid="pf-workflow-terminal" style={{ fontSize: 12, fontWeight: 700, color: 'var(--badge-red-text)' }}>
          ● {st === 'cancelled' ? 'Cancelled' : 'Superseded'}
        </span>
      </div>
    );
  }
  const RANK = { draft: 0, editing: 0, post_failed: 0, approved: 1, posted: 2, converted: 3 };
  let rank = RANK[st] != null ? RANK[st] : 0;
  if (wfirmaProformaId && rank < 2) rank = 2;   // proforma document exists → posted
  if (wfirmaInvoiceId) rank = 3;                 // invoice exists → invoiced
  const stages = ['Review', 'Approved', 'Posted', 'Invoiced'];
  return (
    <div data-testid="pf-workflow-rail" style={{ ...railBox, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {stages.map((s, i) => {
        const done = i < rank, cur = i === rank;
        const color = done ? 'var(--badge-green-text, #2e7d32)' : (cur ? 'var(--accent)' : 'var(--text-3)');
        return (
          <React.Fragment key={s}>
            <span data-testid={`pf-workflow-stage-${s.toLowerCase()}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: (done || cur) ? 700 : 500, color }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
              {s}{done ? ' ✓' : ''}
            </span>
            {i < stages.length - 1 && <span style={{ color: 'var(--text-3)', fontSize: 11 }}>→</span>}
          </React.Fragment>
        );
      })}
      <span style={{ flex: 1, minWidth: 12 }} />
      <span data-testid="pf-workflow-note" style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
        Reservation, shipment &amp; customs are separate authorities — see their tabs.
      </span>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
function ProformaDetailPage({ draft, onBack, onConvert }) {
  const [activeTab,        setActiveTab]        = React.useState('overview');
  const [showConvertModal, setShowConvertModal]  = React.useState(false);
  const [showPostModal,    setShowPostModal]     = React.useState(false);
  const [cloning,          setCloning]           = React.useState(false);
  const [showPreview,      setShowPreview]       = React.useState(false);
  const [previewVariant,   setPreviewVariant]    = React.useState('classic');
  const [previewDocType,   setPreviewDocType]    = React.useState('proforma');

  // M1a — Cancel Draft modal state
  const [showCancelModal,  setShowCancelModal]   = React.useState(false);
  // Purge (hard-delete) modal — only for local-only cancelled drafts
  const [showPurgeModal,   setShowPurgeModal]    = React.useState(false);

  // M7 — Prior Invoice History modal state
  const [showInvoiceHistory, setShowInvoiceHistory] = React.useState(false);

  // M2 — Send Proforma Email modal state
  const [showSendModal, setShowSendModal] = React.useState(false);

  // M8 — AWB Generate modal state
  const [showAwbModal, setShowAwbModal] = React.useState(false);

  // Print error banner — set when wFirma PDF fetch fails; cleared on next toolbar action
  const [printError,   setPrintError]   = React.useState(null);

  // M5 — Inline Edit mode state
  const [editMode,         setEditMode]          = React.useState(false);
  const [editFields,       setEditFields]        = React.useState({});
  const [editSaving,       setEditSaving]        = React.useState(false);
  const [editError,        setEditError]         = React.useState(null);

  // Approval state
  const [approving,        setApproving]         = React.useState(false);
  const [approveError,     setApproveError]      = React.useState(null);

  // PR B — Customer address + service-charge authority
  const [buyerEditOpen,    setBuyerEditOpen]     = React.useState(false);
  const [buyerEditFields,  setBuyerEditFields]   = React.useState({});
  const [buyerEditSaving,  setBuyerEditSaving]   = React.useState(false);
  const [buyerEditError,   setBuyerEditError]    = React.useState(null);
  const [addrApplying,     setAddrApplying]      = React.useState(false);
  const [addrApplyError,   setAddrApplyError]    = React.useState(null);
  // PR 1a — customer/recipient replacement
  const [customerPickOpen,  setCustomerPickOpen]  = React.useState(false);
  const [recipientPickOpen, setRecipientPickOpen] = React.useState(false);
  const [customerPickBusy,  setCustomerPickBusy]  = React.useState(false);
  const [customerPickError, setCustomerPickError] = React.useState(null);
  // PR 1a follow-up — safe, dismissible migration warnings shown AFTER a
  // successful customer replacement (service charges / reservation could not
  // follow the new customer). Backend returns a browser-safe stable shape
  // (type/authority/severity/message/requires_operator_review) — never raw
  // exception text. Array; empty = banner hidden.
  const [customerMigrationWarnings, setCustomerMigrationWarnings] = React.useState([]);
  const [chargeSuggestion, setChargeSuggestion]  = React.useState(null);  // null | response obj
  const [chargesLoading,   setChargesLoading]    = React.useState(false);
  const [chargesApplying,  setChargesApplying]   = React.useState(null);  // 'freight'|'insurance'|null
  const [serviceProducts,  setServiceProducts]   = React.useState(null);  // wFirma registry (lazy)

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

  // WIRED: recorded carrier shipment (GET /api/v1/carrier/{batch_id}/shipment).
  // Read-only AWB/logistics/document visibility — 404 (no shipment yet) → null.
  const [carrierShipment, setCarrierShipment] = React.useState(null);
  const loadCarrierShipment = React.useCallback(() => {
    if (!draft || !draft.batch_id || !window.PzApi.getCarrierShipment) return;
    window.PzApi.getCarrierShipment(draft.batch_id)
      .then(r => setCarrierShipment(r && r.ok ? r.data : null))
      .catch(() => setCarrierShipment(null));
  }, [draft && draft.batch_id]);
  React.useEffect(() => { loadCarrierShipment(); }, [loadCarrierShipment]);

  // Mark the recorded AWB label as DO NOT USE — a LOCAL operational flag for
  // duplicate/unused labels. Never calls DHL, never voids the AWB, never
  // deletes label PDFs; reason is stored for audit.
  const markAwbDoNotUse = React.useCallback(() => {
    if (!carrierShipment || !carrierShipment.tracking_ref || !draft || !draft.batch_id) return;
    if (!window.confirm('This does not cancel anything at DHL. It only marks this label as not to be used or handed to courier.')) return;
    const reason = window.prompt('Reason (required, stored for audit — e.g. "duplicate label, using other AWB"):', 'duplicate/unused label');
    if (!reason || !reason.trim()) return;
    window.PzApi.markCarrierShipmentDoNotUse(draft.batch_id, carrierShipment.tracking_ref, { reason: reason.trim() })
      .then(r => {
        if (r && r.ok) loadCarrierShipment();
        else window.alert((r && r.error) || 'Failed to mark label as do-not-use.');
      })
      .catch(e => window.alert((e && e.message) || 'Failed to mark label as do-not-use.'));
  }, [carrierShipment, draft && draft.batch_id, loadCarrierShipment]);

  // WIRED: fetch readiness / blocking reasons (POST /api/v1/proforma/preview/{batch_id}/{client_name})
  const batchId    = draft && (draft.batch_id    || '');
  const clientName = draft && (draft.client_name || '');
  const previewHook = window.PzState.useProformaPreview(batchId, clientName);
  const preview    = previewHook.data || null;

  // WIRED: SINGLE READINESS AUTHORITY (GET /api/v1/proforma/draft/{id}/readiness)
  // The same backend gate that enforces approve/post/convert — the frontend
  // only reflects it (Lesson F rule 5: the UI never decides workflow legality).
  // intent=approve gates Approve; intent=post gates Post AND Convert (the
  // backend convert gate shares the post blocker set).
  const [readinessApprove, setReadinessApprove] = React.useState(null);
  const [readinessPost,    setReadinessPost]    = React.useState(null);
  const [resolvingDesign,  setResolvingDesign]  = React.useState(null);   // design_no in flight
  const [resolveError,     setResolveError]     = React.useState(null);
  const [savingVat,        setSavingVat]        = React.useState(false);  // WDT vat→master save in flight
  const [vatSaveError,     setVatSaveError]     = React.useState(null);
  const reloadReadiness = () => {
    const id = (draft && draft.id) || null;
    if (!id) return;
    // PzApi wraps every response as { ok, data } — the readiness object
    // (ready / blockers / ambiguous_designs) lives under .data. A failed
    // fetch stores null: button falls back to state-gating only, and the
    // backend enforces the identical gate, so nothing can slip through.
    window.PzApi.getDraftReadiness(id, 'approve')
      .then(r => setReadinessApprove((r && r.ok && r.data) ? r.data : null))
      .catch(() => setReadinessApprove(null));
    window.PzApi.getDraftReadiness(id, 'post')
      .then(r => setReadinessPost((r && r.ok && r.data) ? r.data : null))
      .catch(() => setReadinessPost(null));
  };
  React.useEffect(reloadReadiness, [draft && draft.id, liveDraft.updated_at]);

  // ── wFirma reservation (Create Reservation button) ─────────────────────────
  // The Create Reservation action is gated on the CANONICAL reservation readiness
  // (GET /wfirma/reservation-preview) — distinct from the proforma post readiness,
  // matching the reservation-create endpoint's own pre-flight gates. The button is
  // DISABLED with the exact backend blocking_reasons when not ready; when ready, an
  // explicit operator confirm precedes the LIVE wFirma write
  // (POST /wfirma/reservations/create, hard-gated server-side).
  const [reservationPreview,   setReservationPreview]   = React.useState(null);
  const [reservationLoading,   setReservationLoading]   = React.useState(false);
  const [showReservationModal, setShowReservationModal] = React.useState(false);
  const [reservationBusy,      setReservationBusy]      = React.useState(false);
  const [reservationResult,    setReservationResult]    = React.useState(null);
  const loadReservationPreview = React.useCallback(() => {
    if (!batchId) { setReservationPreview(null); return; }
    setReservationLoading(true);
    window.PzApi.getReservationPreview(batchId)
      .then(r => setReservationPreview((r && r.ok && r.data) ? r.data : null))
      .catch(() => setReservationPreview(null))
      .finally(() => setReservationLoading(false));
  }, [batchId]);
  // Operator action: fetch when the Reservation tab is opened (no auto-fetch at
  // page mount — Lesson F).
  React.useEffect(() => {
    if (activeTab === 'reservation') loadReservationPreview();
  }, [activeTab, loadReservationPreview]);

  const reservationDoc = (reservationPreview &&
    (reservationPreview.documents || []).find(
      // trim both sides so whitespace drift can't silently false-block the draft
      d => (d.client_name || '').trim() === (clientName || '').trim())) || null;
  const reservationExists = !!(reservationPreview && reservationPreview.reservation_exists);
  const reservationId      = (reservationPreview && reservationPreview.reservation_id) || null;
  // Ready only when the batch full-gate AND this draft's client document are ready.
  const reservationReady = !!(reservationPreview &&
    reservationPreview.ready_to_create && reservationDoc && reservationDoc.ready);
  // Reservation signals are surfaced at TWO distinct scopes. Warehouse scan
  // signals (e.g. "84 packing line(s) not yet scanned" — counts the whole
  // batch's packing, NOT this draft's billed lines) arrive as batch_advisories:
  // ADVISORY, never a blocker (authority separation 2026-06-22, Lesson N).
  // batch_blocking_reasons carry infrastructure/wFirma-config blockers that
  // block every client in the batch; reservationDoc.blocking_reasons are THIS
  // draft/client's own. The CREATE GATE (reservationReady) is unchanged — this
  // only clarifies the DISPLAY (Lesson F rule 5: reflect backend truth, never
  // re-derive it).
  const reservationBatchReasons = ((reservationPreview && reservationPreview.batch_blocking_reasons) || []).filter(Boolean);
  const reservationDraftReasons = ((reservationDoc && reservationDoc.blocking_reasons) || []).filter(Boolean);
  // Authority separation (2026-06-22): warehouse scan completeness and sales-data
  // SKU linkage are ADVISORIES, never blockers. They are rendered in a distinct
  // amber advisory panel — they do NOT gate reservationReady.
  const reservationBatchAdvisories = ((reservationPreview && reservationPreview.batch_advisories) || []).filter(Boolean);
  const reservationDraftAdvisories = ((reservationDoc && reservationDoc.advisories) || []).filter(Boolean);

  const doCreateReservation = () => {
    if (!batchId || !clientName) return;
    setReservationBusy(true); setReservationResult(null);
    window.PzApi.createReservation(batchId, clientName)
      .then(r => {
        const body = (r && r.data) || {};
        if (r && r.ok && body.ok) {
          setReservationResult({ ok: true, id: body.wfirma_reservation_id });
          setShowReservationModal(false);
          loadReservationPreview();   // refresh reservation state
          reloadReadiness();          // refresh proforma readiness
          draftHook && draftHook.refresh && draftHook.refresh();  // refresh draft
        } else {
          // backend error rides in r.error as "HTTP <status>: <json body>"
          let msg = (r && r.error) || 'reservation create failed';
          let code = null;
          const mm = /HTTP \d+:\s*(.+)$/.exec(msg);
          if (mm) { try { const b = JSON.parse(mm[1]); code = b.code || null; msg = b.error || b.code || msg; } catch (_) {} }
          setReservationResult({ ok: false, code, error: msg });
        }
      })
      .catch(e => setReservationResult({ ok: false, error: String(e) }))
      .finally(() => setReservationBusy(false));
  };

  // Resolve one ambiguous design_no by picking its exact product_code, then
  // refresh readiness so the resolved blocker disappears.
  const doResolveAmbiguity = (design, pc) => {
    if (!pc || resolvingDesign) return;
    const id = liveDraft.id || (draft && draft.id);
    setResolvingDesign(design);
    setResolveError(null);
    window.PzApi.resolveDraftAmbiguity(id, design, pc)
      .then(r => {
        if (!(r && r.ok)) setResolveError((r && (r.error || r.detail)) || 'Resolution failed — check backend logs.');
        reloadReadiness();
      })
      .catch(err => setResolveError((err && err.message) || 'Network error'))
      .finally(() => setResolvingDesign(null));
  };

  // WDT repair: write the on-file EU-VAT candidate into customer_master.vat_eu_number.
  // Explicit operator action — never auto-applied. The WDT gate stays blocked until
  // this canonical field is populated (the tax rule is not bypassed; we only move a
  // VAT that is plainly on file under `nip` into the field the gate reads). Then refresh.
  const doSaveEuVat = (vr) => {
    if (!vr || savingVat) return;
    const cid = vr.contractor_id;
    const vat = vr.candidate_vat;
    if (!cid || !vat) { setVatSaveError('Missing contractor_id or VAT value.'); return; }
    setSavingVat(true);
    setVatSaveError(null);
    window.PzApi.saveCustomerMaster(cid, { vat_eu_number: vat })
      .then(r => {
        if (!(r && r.ok)) setVatSaveError((r && (r.error || r.detail)) || 'Save failed — check backend logs.');
        reloadReadiness();
      })
      .catch(err => setVatSaveError((err && err.message) || 'Network error'))
      .finally(() => setSavingVat(false));
  };

  // WIRED: fetch company profile for SELLER (GET /api/v1/settings/company-profile)
  const [companyProfile, setCompanyProfile] = React.useState(null);
  React.useEffect(() => {
    window.EstrellaShared.apiFetch('/api/v1/settings/company-profile')
      .then(r => setCompanyProfile((r && r.profile) || null))
      .catch(() => setCompanyProfile(null));
  }, []);

  // WIRED: packing lines authority for CMR goods table
  // Source: GET /api/v1/packing/{batchId}/lines — aggregated by item_type+metal+stone
  // New CMR line shape: { item_type, metal, stone, qty, net_weight, origin }
  // HS/CN codes NOT included — kept in DB only; shown outside Europe only (operator decision 2026-06-09)
  const [batchPackingLines, setBatchPackingLines] = React.useState([]);
  React.useEffect(() => {
    if (!batchId) { setBatchPackingLines([]); return; }
    window.EstrellaShared.apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/lines`)
      .then(r => setBatchPackingLines((r && r.lines) || []))
      .catch(() => setBatchPackingLines([]));
  }, [batchId]);

  // Draft-scoped packing enrichment. AUTHORITY RULE: documents (Packing List,
  // CMR) render only THIS draft's billed editable_lines. The batch/shipment
  // packing rows (which span ALL clients on the batch — 84 rows here) may ENRICH
  // a draft line with physical fields (weight, kt, colour, quality, size, HSN,
  // origin) matched by design_no (most specific) then product_code — but they
  // MUST NEVER add a line the draft does not bill. So we index the batch rows and
  // look one up per editable line; we never iterate the batch rows to build a
  // document.
  const _packingByDesign = React.useMemo(() => {
    const m = {};
    (batchPackingLines || []).forEach(l => {
      const d = String(l.design_no || '').trim();
      if (d && !(d in m)) m[d] = l;
    });
    return m;
  }, [batchPackingLines]);
  const _packingByCode = React.useMemo(() => {
    const m = {};
    (batchPackingLines || []).forEach(l => {
      const c = String(l.product_code || '').trim();
      if (c && !(c in m)) m[c] = l;
    });
    return m;
  }, [batchPackingLines]);
  const _enrichPacking = React.useCallback((ln) => {
    const d = String((ln && ln.design_no) || '').trim();
    const c = String((ln && ln.product_code) || '').trim();
    return (d && _packingByDesign[d]) || (c && _packingByCode[c]) || {};
  }, [_packingByDesign, _packingByCode]);

  // ── Authority-wired data construction ──────────────────────────────────────
  // Draft currency authority — the draft header currency (e.g. USD). Per-line and
  // preview displays inherit THIS, never a hardcoded 'EUR', so a USD draft is not
  // mislabelled as EUR. (Issue: USD draft shown as EUR in Lines tab / preview.)
  const draftCurrency = liveDraft.currency || (draft && draft.currency) || 'EUR';
  // Product lines from backend editable_lines
  const lines = (liveDraft.editable_lines || []).map((ln, i) => ({
    seq:      i + 1,
    lineId:   ln.line_id || '',
    sku:      ln.product_code || '—',
    desc:     ln.name_pl || ln.description_pl || ln.design_no || ln.product_code || '—',
    desc_pl:  ln.description_pl || ln.name_pl || '',
    desc_en:  ln.description_en || ln.name_en || '',
    qty:      parseFloat(ln.qty || 0),
    unitEur:  parseFloat(ln.unit_price || 0),
    netEur:   parseFloat(ln.unit_price || 0) * parseFloat(ln.qty || 0),
    hsCode:   ln.hs_code || '—',
    // Origin = goods manufacturing/export country, NOT the seller's country.
    // companyProfile.country = 'PL' (seller) must NOT be used as origin fallback.
    origin:   ln.origin || liveDraft.origin_country || '—',
    purity:   ln.purity || '',
    currency: ln.currency || draftCurrency,
    // Ctg is derived display-only from enrichment item_type (no schema column).
    ctgLabel: PfCtgLabel(ln.item_type) || null,
    _raw:     ln,  // PD-2: preserved for variant columns in ProformaLinesTab
  }));

  // Ambiguity line evidence: candidate product_code → packing-line context so
  // the operator picks the exact code WITH evidence (qty / value / name), not a
  // bare code. Keyed off the draft's own editable_lines (the lines being billed).
  const linesByCode = {};
  (liveDraft.editable_lines || []).forEach(ln => {
    const pc = (ln.product_code || '').trim();
    if (!pc) return;
    linesByCode[pc] = {
      qty:      parseFloat(ln.qty || 0),
      value:    parseFloat(ln.unit_price || 0) * parseFloat(ln.qty || 0),
      name:     ln.name_pl || ln.description_en || ln.item_type || '',
      design:   ln.design_no || '',
      currency: ln.currency || draftCurrency,
    };
  });

  // FX rate from backend (no browser-side PLN conversion)
  const fxRate = liveDraft.exchange_rate ? parseFloat(liveDraft.exchange_rate) : null;

  // payment_terms_json shape is { method?: string, days?: number } (routes_proforma.py).
  // wFirma XML keys (paymentmethod, paymentdate, saledate) also accepted.
  // Fallback: wfirma_payment_method column (written by post-posting enrichment).
  const rawPt = liveDraft.payment_terms;
  const paymentTermsDisplay = (() => {
    if (!rawPt || (typeof rawPt === 'object' && Object.keys(rawPt).length === 0)) {
      return liveDraft.wfirma_payment_method || '—';
    }
    if (typeof rawPt !== 'object') return String(rawPt);
    const parts = [];
    if (rawPt.method)        parts.push(String(rawPt.method));
    if (rawPt.paymentmethod) parts.push(String(rawPt.paymentmethod));
    if (rawPt.days)          parts.push(`${rawPt.days} days`);
    Object.entries(rawPt).forEach(([k, v]) => {
      if (!['method', 'paymentmethod', 'days', 'saledate', 'paymentdate'].includes(k) && v)
        parts.push(`${k}: ${v}`);
    });
    return parts.join(' · ') || liveDraft.wfirma_payment_method || '—';
  })();

  // SELLER from company profile (GET /api/v1/settings/company-profile)
  const exporter = companyProfile
    ? {
        name:    companyProfile.legal_name || '—',
        vatEu:   companyProfile.vat_eu || '—',
        address: [companyProfile.street, companyProfile.postal_city].filter(Boolean).join(', ') || '—',
        country: companyProfile.country || '—',
      }
    : { name: '—', vatEu: '—', address: '—', country: '—' };

  // BUYER — authority split:
  //   name / VAT / address / country → buyer_override (operator-confirmed buyer data)
  //   wfirmaId / wfirmaName          → customer_resolution (wFirma resolution metadata)
  // customer_resolution is present in the response but only carries wFirma resolution
  // metadata (wfirma_customer_id, resolved_wfirma_customer_name, match_strategy).
  // It does NOT carry vat_eu, address, or country — buyer_override is the only authority
  // for those fields.
  const bo = liveDraft.buyer_override || {};
  const cr = liveDraft.customer_resolution || {};
  // VAT-EU authority: the canonical buyer VAT is buyer_override.vat_id, but the
  // EU VAT is sometimes only on file under `nip` (general tax-id) while vat_id /
  // customer_master.vat_eu_number are blank. Surface the on-file value instead of
  // "—" so the card never hides a VAT the readiness gate is blocking on, and flag
  // when it is not yet stored as the canonical EU-VAT field (vatEuFromNip).
  const _boVatId = (bo.vat_id || '').trim();
  const _boNip   = (bo.nip || '').trim();
  const customer = {
    name:       bo.name || liveDraft.client_name || (draft && draft.client_name) || '—',
    vatEu:      _boVatId || _boNip || '—',
    vatEuFromNip: !_boVatId && !!_boNip,
    address:    [bo.street, bo.city, bo.zip].filter(Boolean).join(', ') || '—',
    country:    bo.country || '—',
    // wfirmaId: explicit selection in buyer_override > name-resolution in cr > posted proof
    wfirmaId:   bo.wfirma_customer_id || cr.wfirma_customer_id ||
                (liveDraft.wfirma_proforma_id ? String(liveDraft.wfirma_proforma_id) : null),
    wfirmaName: cr.resolved_wfirma_customer_name || bo.name || null,
  };

  // SHIP-TO — authority: ship_to_override first, buyer_override fallback.
  // When ship_to_override is not set, ship-to equals the buyer.
  const sto = liveDraft.ship_to_override || {};
  const shipTo = {
    name:    sto.name    || bo.name || liveDraft.client_name || '—',
    address: [sto.street || bo.street, sto.city || bo.city, sto.zip || bo.zip]
               .filter(Boolean).join(', ') || '—',
    country: sto.country || bo.country || '—',
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
    // sale_date: API returns from payment_terms_json.saledate; fallback to rawPt.saledate
    // for operator-edited payment_terms that include the wFirma XML key.
    sale_date: liveDraft.sale_date || (rawPt && typeof rawPt === 'object' && rawPt.saledate) || null,
  };
  // ── Country code → full name (ISO 3166-1 alpha-2) for proforma display ──────
  const PROFORMA_COUNTRY_NAMES = {
    PL: 'Poland',          LT: 'Lithuania',          DE: 'Germany',          IN: 'India',
    CZ: 'Czech Republic',  SK: 'Slovakia',            HU: 'Hungary',          RO: 'Romania',
    UA: 'Ukraine',         FR: 'France',              IT: 'Italy',            ES: 'Spain',
    NL: 'Netherlands',     BE: 'Belgium',             AT: 'Austria',          CH: 'Switzerland',
    GB: 'United Kingdom',  DK: 'Denmark',             SE: 'Sweden',           FI: 'Finland',
    NO: 'Norway',          EE: 'Estonia',             LV: 'Latvia',           BY: 'Belarus',
    LU: 'Luxembourg',      PT: 'Portugal',            GR: 'Greece',           BG: 'Bulgaria',
    HR: 'Croatia',         SI: 'Slovenia',            RS: 'Serbia',           TR: 'Turkey',
    AE: 'United Arab Emirates', SG: 'Singapore',     HK: 'Hong Kong',        CN: 'China',
    JP: 'Japan',           KR: 'South Korea',         AU: 'Australia',        US: 'United States',
    CA: 'Canada',          BR: 'Brazil',              MX: 'Mexico',           ZA: 'South Africa',
    SA: 'Saudi Arabia',    IL: 'Israel',
  };
  const _expandCountry = (code) => (code && (PROFORMA_COUNTRY_NAMES[code] || code)) || '';

  // ── docData for print preview (EJProformaClassic / EJProformaModern) ──────
  const _previewLabel = liveDraft.wfirma_proforma_fullnumber
    || (draft && draft.wfirma_proforma_fullnumber)
    || (draft && draft.id ? `Draft #${draft.id}` : 'Draft');
  // Payment due: wfirma_payment_due (post-wFirma) -> due_date -> invoice_date + payment_terms_days
  // payment_terms_days is a flat int field; rawPt.days is the same value from the JSON blob.
  // Check both: the flat field may be absent from older drafts that only have the JSON blob.
  const _ptDays = Number(liveDraft.payment_terms_days)
    || (rawPt && typeof rawPt === 'object' ? Number(rawPt.days) : 0)
    || 0;
  const _dueFallback = (() => {
    if (liveDraft.wfirma_payment_due) return liveDraft.wfirma_payment_due.slice(0, 10);
    if (liveDraft.due_date)           return liveDraft.due_date.slice(0, 10);
    const base = liveDraft.invoice_date || liveDraft.created_at;
    if (base && _ptDays > 0) {
      // Date-only UTC arithmetic — parsing a local timestamp and round-tripping
      // through toISOString() can shift the calendar day for UTC+ timezones.
      const d = new Date(String(base).slice(0, 10) + 'T00:00:00Z');
      if (!isNaN(d.getTime())) {
        d.setUTCDate(d.getUTCDate() + _ptDays);
        return d.toISOString().slice(0, 10);
      }
    }
    return '—';
  })();
  // Freight + insurance for the preview — surfaced explicitly so they are never
  // silently absent. A charge with no draft entry renders an explicit "not set"
  // state (present:false), not a hidden/zero value.
  const _svcCharges = liveDraft.service_charges || [];
  const previewCharges = ['freight', 'insurance'].map(t => {
    const c = _svcCharges.find(x => (x.charge_type || '').toLowerCase() === t && (Number(x.amount) || 0) !== 0);
    return {
      type:     t,
      label:    t === 'freight' ? 'Freight' : 'Insurance',
      amount:   c ? (Number(c.amount) || 0) : null,
      currency: (c && c.currency) || draftCurrency,
      present:  !!c,
    };
  });
  const previewDocData = {
    doc_no:   _previewLabel,
    currency: draftCurrency,
    charges:  previewCharges,
    date:     liveDraft.invoice_date || liveDraft.created_at
              ? (liveDraft.invoice_date || liveDraft.created_at || '').slice(0, 10) : '—',
    due:      _dueFallback,
    payment:  paymentTermsDisplay,
    payment_terms_days: _ptDays,
    rate:     { eur: fxRate, currency: draftCurrency, date: liveDraft.exchange_rate_date || '—', table: liveDraft.nbp_table || '—' },
    // Address lines follow EU print convention: street / zip city / country.
    // Structured fields preferred; comma-joined string is the legacy fallback.
    seller:   {
      name:    detail.exporter.name,
      addr:    (companyProfile && companyProfile.street) || detail.exporter.address,
      city:    (companyProfile && companyProfile.postal_city) || '',
      country: _expandCountry(detail.exporter.country),
      vat:     detail.exporter.vatEu,
      email:   (companyProfile && companyProfile.email) || '',
      phone:   (companyProfile && companyProfile.phone) || '',
    },
    buyer:    {
      name:    detail.customer.name,
      addr:    bo.street || detail.customer.address,
      city:    [bo.zip, bo.city].filter(Boolean).join(' '),
      country: _expandCountry(detail.customer.country),
      vat:     detail.customer.vatEu,
    },
    // ship_to: only when ship_to_override is set — templates fall back to buyer
    // when null, so "Ship to = buyer" stays the default print behaviour.
    ship_to:  (sto.name || sto.street || sto.city || sto.zip || sto.country)
      ? {
          name:    shipTo.name,
          addr:    sto.street || bo.street || '',
          city:    [sto.zip || bo.zip, sto.city || bo.city].filter(Boolean).join(' '),
          country: _expandCountry(shipTo.country),
        }
      : null,
    lines:    lines.map(l => ({
      seq:     l.seq,
      sku:     l.sku,
      desc:    l.desc,
      desc_pl: l.desc_pl,
      desc_en: l.desc_en,
      purity:  l.purity,
      origin:  l.origin,
      qty:     l.qty,
      unitEur: l.unitEur,
      netEur:  l.netEur,
    })),
    total_eur: lines.reduce((s, l) => s + l.netEur, 0),
    total_pln: (fxRate && fxRate > 0)
      ? lines.reduce((s, l) => s + l.netEur, 0) * fxRate : null,
    // AWB tracking number lives in carrier storage, not in the draft.
    // batch_id is a system reference, not a DHL tracking number — never show it as AWB.
    // EJDocCarrierRow renders "AWB pending" when awb is null.
    carrier:  liveDraft.batch_id
      ? { awb: null, batch_ref: liveDraft.batch_id, incoterm: liveDraft.incoterm || 'DAP' } : null,
    // EUR first — the document currency leads; sort is stable for the rest.
    // Backend returns flat iban_eur/iban_usd/iban_pln/swift/bank_name fields (not bank_accounts[]).
    // Adapt here so EJDocBank receives a normalised array regardless of future schema changes.
    banks: (() => {
      if (!companyProfile) return [];
      // Future shape: bank_accounts[] array
      if (companyProfile.bank_accounts && companyProfile.bank_accounts.length) {
        return companyProfile.bank_accounts
          .map(b => ({
            cur:   b.currency || b.cur || 'EUR',
            iban:  b.iban || '—',
            swift: b.bic || b.swift || '',
            bank:  b.bank_name || b.bank || '',
          }))
          .sort((a, b) => (b.cur === 'EUR') - (a.cur === 'EUR'));
      }
      // Current shape: flat iban_eur / iban_usd / iban_pln + shared swift/bank_name.
      // Strip "(EURO)" or "(EUR)" currency suffix from bank_name — it's a display artifact
      // that leaks into non-EUR rows and looks wrong (e.g. USD row showing "Bank (EURO)").
      const _rawBankName = companyProfile.bank_name || '';
      const _cleanBankName = _rawBankName.replace(/\s*\((EUR|EURO|PLN|USD)\)\s*$/i, '').trim();
      return [
        companyProfile.iban_eur ? { cur: 'EUR', iban: companyProfile.iban_eur, swift: companyProfile.swift || '', bank: _cleanBankName } : null,
        companyProfile.iban_usd ? { cur: 'USD', iban: companyProfile.iban_usd, swift: companyProfile.swift || '', bank: _cleanBankName } : null,
        companyProfile.iban_pln ? { cur: 'PLN', iban: companyProfile.iban_pln, swift: companyProfile.swift || '', bank: _cleanBankName } : null,
      ].filter(Boolean).sort((a, b) => (b.cur === 'EUR') - (a.cur === 'EUR'));
    })(),
    // QA warnings — preview-only, not printed. Each: { code, msg }
    warnings: (() => {
      const w = [];
      if (!fxRate) w.push({ code: 'NO_FX_RATE', msg: 'Exchange rate (NBP) not set — PLN total cannot be computed. Set the exchange rate before printing.' });
      if (!liveDraft.invoice_date) w.push({ code: 'NO_ISSUE_DATE', msg: 'Issue date not set on draft.' });
      const missingOrigin = lines.filter(l => !l.origin || l.origin === '—');
      if (missingOrigin.length > 0) w.push({ code: 'MISSING_ORIGIN', msg: `${missingOrigin.length} line(s) have no origin country — verify product authority.` });
      return w;
    })(),
  };
  // ── cmrData for CMR preview (EJCMRClassic / EJCMRModern) ─────────────────
  // No CMR backend route exists — this is client-side preview only.

  // Country code → full name for CMR origin display (ISO 3166-1 alpha-2 subset)
  const _CMR_COUNTRY_NAMES = {
    PL: 'Poland',       LT: 'Lithuania',  DE: 'Germany',      IN: 'India',
    CZ: 'Czech Republic', SK: 'Slovakia', HU: 'Hungary',      RO: 'Romania',
    UA: 'Ukraine',      FR: 'France',     IT: 'Italy',        ES: 'Spain',
    NL: 'Netherlands',  BE: 'Belgium',    AT: 'Austria',      CH: 'Switzerland',
    GB: 'United Kingdom', DK: 'Denmark',  SE: 'Sweden',       FI: 'Finland',
    NO: 'Norway',       EE: 'Estonia',    LV: 'Latvia',       BY: 'Belarus',
  };
  const _cmrCountryName = (code) => (code && (_CMR_COUNTRY_NAMES[code] || code)) || '';

  // ── CMR packing-line parsers (human-readable labels, no HS/CN codes) ─────────
  // Metal code → human label: "14KT/W" → "14 Karat White Gold"
  const _CMR_KARAT = { '18KT': '18 Karat', '14KT': '14 Karat', '22KT': '22 Karat', '9KT': '9 Karat' };
  const _CMR_COLOR = {
    W: 'White Gold',  Y: 'Yellow Gold', P: 'Pink Gold',   RG: 'Rose Gold',
    WY: 'White & Yellow Gold', WP: 'White & Pink Gold',  YP: 'Yellow & Pink Gold',
    TRI: 'Tri-Color Gold',
  };
  const _parseMetal = (metal) => {
    if (!metal) return '';
    const parts = (metal || '').toUpperCase().split('/');
    const karat = _CMR_KARAT[parts[0]] || parts[0] || '';
    const color = _CMR_COLOR[parts[1]] || parts[1] || '';
    return [karat, color].filter(Boolean).join(' ');
  };
  // Stone type → human label
  const _CMR_STONE = {
    DIA: 'Diamond',     CLS: 'Coloured Stone', CS: 'Coloured Stone',
    RUBY: 'Ruby',       EMERALD: 'Emerald',    SAPPHIRE: 'Sapphire',
    PEARL: 'Pearl',     CORAL: 'Coral',
  };
  const _parseStone = (s) => {
    if (!s) return '';
    return _CMR_STONE[(s || '').toUpperCase()] || s;
  };
  // Item type → human label
  const _CMR_ITEM = {
    PND: 'Pendant', PENDANT: 'Pendant', RNG: 'Ring', RING: 'Ring',
    EAR: 'Earrings', EARRINGS: 'Earrings', BRL: 'Bracelet', BRACELET: 'Bracelet',
    NKL: 'Necklace', NECKLACE: 'Necklace', BRO: 'Brooch', SET: 'Set',
    CHAIN: 'Chain',  BANGLE: 'Bangle',
  };
  const _cmrItemLabel = (t) => _CMR_ITEM[(t || '').toUpperCase()] || t || '';

  // CMR transport summary — aggregated by item_type ONLY (not metal/stone per line)
  // CMR is a logistics document; carrier needs item totals, not 146 design rows.
  // Metal and stone types surface as a single goods_summary description, not per-line columns.
  // Returns { lines: [{item_type, qty, net_weight, origin}], goods_summary, total_qty }
  const _cmrAggPackingLines = (() => {
    // CMR totals aggregate ONLY this draft's billed editable_lines (qty authority),
    // enriched with physical metal/stone/weight from the matched batch packing row.
    // Never aggregates the full-shipment batch packing (which spans all clients).
    const _el = liveDraft.editable_lines || [];
    if (!_el.length) {
      return { lines: [], goods_summary: '', total_qty: 0 };
    }
    const groups = {};
    const metals  = new Set();
    const stones  = new Set();
    let totalQty  = 0;
    for (const ln of _el) {
      const pk = _enrichPacking(ln);                       // batch row (enrichment only)
      const itemType = ln.item_type || pk.item_type || 'other';
      const key = String(itemType).toUpperCase();
      if (!groups[key]) {
        groups[key] = { item_type: _cmrItemLabel(itemType), qty: 0, net_weight: null,
                        origin: pk.origin || ln.origin || 'India' };
      }
      const q = Number(ln.qty) || 0;                       // DRAFT billed qty (authority)
      groups[key].qty += q;
      totalQty        += q;
      const nw = Number(pk.net_weight) || 0;               // physical weight (enrichment)
      if (nw > 0) groups[key].net_weight = (groups[key].net_weight || 0) + nw;
      const m = _parseMetal(pk.metal);       if (m) metals.add(m);
      const s = _parseStone(pk.stone_type);  if (s) stones.add(s);
    }
    const metalsStr    = Array.from(metals).join(' & ');
    const stonesStr    = Array.from(stones).join(' & ');
    const goods_summary = [metalsStr, stonesStr].filter(Boolean).join(' · ');
    return {
      lines:       Object.values(groups).sort((a, b) => (a.item_type > b.item_type ? 1 : -1)),
      goods_summary,    // e.g. "14 Karat Pink Gold & 14 Karat White Gold · Diamond"
      total_qty:   totalQty,
    };
  })();
  // ────────────────────────────────────────────────────────────────────────────

  // Insurance: show canonical wording when a non-zero insurance charge exists on the draft
  const _CMR_INSURANCE_TEXT =
    'Yes — Insurance covers the Door to Door delivery of this package by Future Generali India Insurance Company Limited';
  const _cmrHasInsurance = (liveDraft.service_charges || []).some(
    c => (c.charge_type || '').toLowerCase() === 'insurance' && (Number(c.amount) || 0) > 0
  );

  // Total pieces: packing list authority when available, otherwise proforma editable lines
  const _cmrTotalPcs = _cmrAggPackingLines.total_qty > 0
    ? _cmrAggPackingLines.total_qty
    : lines.reduce((s, l) => s + (Number(l.qty) || 0), 0);

  const cmrPreviewData = {
    cmr_no:   batchId ? `CMR-EJ-${batchId}` : '—',
    doc_ref:  _previewLabel,
    seller:   {
      name:  exporter.name,
      addr:  exporter.address,
      // FIX #2: sender city (not country code)
      city:  (companyProfile && companyProfile.postal_city) || '—',
      vat:   exporter.vatEu,
      email: (companyProfile && companyProfile.email) || '',
      phone: (companyProfile && companyProfile.phone) || '',
    },
    shipto:   {
      name:    shipTo.name,
      addr:    shipTo.address,
      // FIX #1: actual delivery city (not country code)
      city:    (sto.city || bo.city) || '—',
      zip:     (sto.zip  || bo.zip)  || '',   // FIX #1: postal code for Box 3 display
      country: shipTo.country,
    },
    buyer:    { vat: customer.vatEu },
    carrier:  liveDraft.batch_id ? {
      // Honest source: the actual shipment/batch carrier when known, else '—'.
      // Do NOT assume DHL — an AWB/batch_id existing does not imply a carrier.
      name:        liveDraft.carrier || liveDraft.carrier_name || '—',
      awb:         liveDraft.batch_id,
      service:     'EXPRESS WORLDWIDE',
      incoterm:    liveDraft.incoterm || 'DAP',
      // FIX #2: origin = sender city + country name (e.g. "Warszawa, Poland")
      origin:      [
        (companyProfile && companyProfile.postal_city) || null,
        _cmrCountryName(exporter.country) || null,
      ].filter(Boolean).join(', ') || '—',
      destination: (sto.city || bo.city) || shipTo.country || customer.country || '—',
      // FIX #3: total pieces from SALES packing list (proforma lines sum)
      pieces:      _cmrTotalPcs > 0 ? _cmrTotalPcs : null,
      // FIX #4+5: weight_kg / dim_cm from AWB — not yet available in draft data
      weight_kg:   null,
      dim_cm:      null,
      // FIX #6: insurance wording when an insurance service charge exists on the proforma
      insurance:   _cmrHasInsurance ? _CMR_INSURANCE_TEXT : null,
    } : null,
    goods_summary: _cmrAggPackingLines.goods_summary || '',
    // CMR lines: aggregated by item_type ONLY — transport summary, not commercial detail
    // Each entry: { item_type, qty, net_weight, origin } — 3-6 rows max
    // Fallback to proforma lines when packing data not yet loaded
    lines: _cmrAggPackingLines.lines.length > 0
      ? _cmrAggPackingLines.lines
      : lines.map(l => ({ item_type: l.desc, qty: l.qty, net_weight: null, origin: l.origin || 'India' })),
  };
  // ──────────────────────────────────────────────────────────────────────────

  // Packing List PDF data — full design-level detail (146 lines for AWB 9938632830)
  // Price authority: liveDraft.editable_lines[i].unit_price (proforma sales price, EUR)
  //   Matched by INDEX — both editable_lines and sortedPackingLines are in pack_sr order.
  //   editable_lines are created from packing lines at packing-sync time, preserving that order.
  //   Do NOT match by product_code (= invoice no, same for all lines in one invoice)
  //   or by design_no alone (design_no can repeat across different bags/colours).
  //   Index match is O(1) and robust for single-invoice batches.
  //
  //   Fallback chain: editable_lines[i].unit_price → unit_price_eur → unit_price (supplier rate)
  // Currency: from draft (can vary per client — not hardcoded to EUR)
  const packingListData = (() => {
    const currency      = liveDraft.currency || 'EUR';
    const _editableLines = liveDraft.editable_lines || [];
    // ONE row per BILLED draft line (never the full-shipment batch packing).
    // qty + sales price come from the draft editable line (the billing authority);
    // physical fields (kt/colour/quality/weights/size/HSN/origin) are ENRICHED
    // from the matched batch packing row by design_no/product_code. Packing List
    // total === draft total.
    const rows = _editableLines.map((ln, i) => {
      const pk        = _enrichPacking(ln);
      const qty       = Number(ln.qty) || 0;
      const unitPrice = Number(ln.unit_price) > 0
        ? Number(ln.unit_price)
        : (Number(pk.unit_price_eur) || Number(pk.unit_price) || 0);
      return {
        // SR is the packing-list's own sequential line number (1..N). Do NOT use
        // the matched packing row's pack_sr — several billed lines can map to the
        // same design (mixed lots), so pack_sr collides (e.g. JR04929 → 9 ×3) and
        // leaves gaps/out-of-order rows. The draft's editable_lines are the row
        // authority; number them sequentially.
        sr:           i + 1,
        ctg:          _cmrItemLabel(ln.item_type || pk.item_type),  // Pendant / Ring / Earrings
        // Phase B slice B3 (PROJECT_STATE DECISIONS "Phase B slices B2+B3"):
        // client_po is PERSISTED since 494c4665 — prefer the real column;
        // the invoice_no||client_ref expression is the legacy FALLBACK only
        // for pre-fix rows where the column backfilled to ''.
        client_po:    pk.client_po || pk.invoice_no || ln.client_ref || '',
        product_code: ln.product_code || pk.product_code || '—',
        design:       ln.design_no    || pk.design_no    || '—',
        kt:           (pk.metal || '').split('/')[0] || '', // "14KT"
        col:          (pk.metal || '').split('/')[1] || '', // "W", "P", "Y"
        quality:      pk.quality_string || '',
        // diamond_weight / color_weight stored since 2026-06-09 schema migration.
        // Existing rows show null (—) until packing is re-uploaded or force_reextract=True.
        dia_wt:       Number(pk.diamond_weight) > 0 ? Number(pk.diamond_weight) : null,
        col_wt:       Number(pk.color_weight)   > 0 ? Number(pk.color_weight)   : null,
        gross_wt:     Number(pk.gross_weight)   > 0 ? Number(pk.gross_weight)   : null,
        net_wt:       Number(pk.net_weight)     > 0 ? Number(pk.net_weight)     : null,
        qty,
        unit_price:   unitPrice,
        total_value:  unitPrice * qty,
        // size: stored from packing XLSX "Size" column since 2026-06-09.
        size:         pk.size || '',
        // HSN intentionally shown outside Europe only (operator decision 2026-06-09):
        // EU/WDT shipments render "—". packing_lines has no hs_code column.
        hsn:          ln.hs_code || pk.hs_code || '',
        // Origin defaults to India (goods manufacturing origin) — same default the
        // CMR uses (line ~1287). packing_lines has no origin column.
        origin:       ln.origin || pk.origin || 'India',
      };
    });
    const grand_total = rows.reduce((s, r) => s + r.total_value, 0);
    const total_qty   = rows.reduce((s, r) => s + r.qty,         0);
    return {
      doc_ref:     _previewLabel,
      invoice_ref: liveDraft.wfirma_invoice_id ? String(liveDraft.wfirma_invoice_id) : null,
      issued_date: liveDraft.created_at ? (liveDraft.created_at || '').split('T')[0] : '',
      seller:      cmrPreviewData.seller,
      shipto:      cmrPreviewData.shipto,
      buyer:       cmrPreviewData.buyer,
      currency,
      rows,
      grand_total,
      total_qty,
    };
  })();
  // ──────────────────────────────────────────────────────────────────────────

  const draftState    = liveDraft.draft_state || liveDraft.status || (draft && draft.status) || '';
  // SINGLE READINESS AUTHORITY — backend-derived blockers. State gating says
  // whether the lifecycle ALLOWS the action; readiness says whether the data
  // is SAFE for it. Both must pass. While readiness is still loading (null)
  // the button stays state-gated only — the backend enforces the same gate,
  // so an early click cannot bypass it.
  const approveBlockers = (readinessApprove && readinessApprove.blockers) || [];
  const postBlockers    = (readinessPost    && readinessPost.blockers)    || [];
  const approveBlocked  = !!(readinessApprove && readinessApprove.ready === false);
  const postBlocked     = !!(readinessPost    && readinessPost.ready    === false);
  // Slice 5: set of blocker reasons already rendered by ProformaBlockerPanel so that
  // ProformaReadinessPanel can suppress duplicates (display-only — gating is unchanged).
  const blockerPanelReasons = React.useMemo(() => {
    const s = new Set();
    approveBlockers.forEach(b => b.reason && s.add(b.reason));
    postBlockers.forEach(b => b.reason && s.add(b.reason));
    return s;
  }, [approveBlockers, postBlockers]);
  const stateAllowsPost    = ['draft', 'pending_local', 'approved', 'post_failed'].includes(draftState);
  const alreadyConverted    = !!(liveDraft.wfirma_invoice_id) || draftState === 'converted';
  const stateAllowsConvert  = (draftState === 'posted' || draftState === 'ready') && !alreadyConverted;
  const stateAllowsApprove  = ['draft', 'editing', 'post_failed'].includes(draftState);
  const canPost       = stateAllowsPost && !postBlocked;
  const canConvert    = stateAllowsConvert && !postBlocked;
  const isBlocked     = draftState === 'post_failed' || draftState === 'convert_blocked';
  const alreadyPosted = draftState === 'posted' || draftState === 'invoiced';
  const canPrint      = !!(liveDraft.wfirma_proforma_id || (draft && draft.wfirma_proforma_id));
  const canApprove    = stateAllowsApprove && !approveBlocked;
  const alreadyApproved = draftState === 'approved';
  const _firstBlockerText = (bl) => bl.length
    ? `${bl[0].reason} — Fix: ${bl[0].repair_action}` + (bl.length > 1 ? ` (+${bl.length - 1} more — see Readiness panel)` : '')
    : '';
  const approveDisabledReason = !stateAllowsApprove
    ? (alreadyApproved ? 'Already approved' : `Cannot approve in '${draftState}' state`)
    : (approveBlocked ? `Blocked: ${_firstBlockerText(approveBlockers)}` : '');
  const postDisabledReason = !stateAllowsPost
    ? (alreadyPosted ? 'Already posted to wFirma' : `Cannot post in '${draftState}' state`)
    : (postBlocked ? `Blocked: ${_firstBlockerText(postBlockers)}` : '');
  const convertDisabledReason = !stateAllowsConvert
    ? (alreadyConverted
        ? `Already converted — invoice ${liveDraft.wfirma_invoice_number || liveDraft.wfirma_invoice_id || 'created'}`
        : (isBlocked ? 'Conversion blocked — see Reservation tab' : 'Post to wFirma first, then convert'))
    : (postBlocked ? `Blocked: ${_firstBlockerText(postBlockers)}` : '');

  // M5 — Edit mode: enabled when draft is in an editable state
  const canEdit       = ['draft', 'editing', 'post_failed'].includes(draftState);
  // M1a — Cancel: enabled when draft is in a cancellable state and not already cancelled
  const canCancel     = ['draft', 'editing', 'approved', 'post_failed'].includes(draftState);
  // Purge: only cancelled local-only drafts (no wFirma ID, no PROF number)
  const hasFullNumber  = !!(liveDraft.wfirma_proforma_fullnumber || (draft && draft.wfirma_proforma_fullnumber));
  const canPurge       = draftState === 'cancelled' && !hasWfirmaId && !hasFullNumber;
  const purgeDisabledReason = draftState !== 'cancelled'
    ? `Cannot delete in '${draftState}' state — cancel first`
    : hasWfirmaId
      ? 'Cannot delete: draft is linked to a wFirma proforma'
      : hasFullNumber
        ? 'Cannot delete: draft has an assigned PROF number'
        : '';
  // M7 — Prior Invoice History: enabled when wFirma contractor ID is available
  const contractorId  = (cr && cr.wfirma_customer_id) || null;
  // M2 — Send Email: enabled when posted to wFirma (has PDF) and not in terminal state
  const hasWfirmaId   = !!(liveDraft.wfirma_proforma_id || (draft && draft.wfirma_proforma_id));
  const sendableStates = ['posted', 'approved', 'ready'];
  const canSend       = hasWfirmaId && sendableStates.includes(draftState);
  // M2 — Customer email from Customer Master (bill_to_email)
  const customerEmail = (cr && cr.customer && cr.customer.bill_to_email) || '';
  const sendDisabledReason = !hasWfirmaId
    ? 'Post draft to wFirma first — no PDF available for email'
    : !sendableStates.includes(draftState)
      ? `Cannot send in '${draftState}' state`
      : '';

  // SINGLE readiness authority. The Reservation tab, the Overview blocker banners,
  // and the "What's blocking" panel all read the CANONICAL backend readiness
  // (readinessPost — the same source the Approve/Post/Convert buttons + tooltips
  // and the top "Not ready" panel use), NOT the preview's batch/client-wide
  // blocking_reasons (which can surface stale design-ambiguity that the canonical
  // readiness has already reconciled away, and counts the client's whole sales
  // packing instead of the draft's billed lines). When ambiguous_designs is empty
  // the canonical readiness carries no ambiguity blocker, so none is shown.
  const blockingReasons = ((readinessPost && readinessPost.blockers) || []).map(b => b.reason);
  // The wFirma PZ / export prerequisite is already included in readinessPost.blockers
  // for the post intent, so it is carried by blockingReasons above — no separate
  // (stale) preview export list.
  const exportBlockers  = [];
  const vatResolution   = disclosure && disclosure.vat_resolution;

  const proformaLabel = liveDraft.wfirma_proforma_fullnumber
    || (draft && draft.wfirma_proforma_fullnumber)
    || `Draft #${draft && draft.id}`;

  const handleDownloadPdf = async () => {
    const bid = liveDraft.batch_id || (draft && draft.batch_id) || '';
    const cn  = liveDraft.client_name || (draft && draft.client_name) || '';
    if (!bid || !cn) return;
    setPrintError(null);
    const url = `/api/v1/proforma/${encodeURIComponent(bid)}/${encodeURIComponent(cn)}/document.pdf`;
    try {
      const resp = await fetch(url, { credentials: 'include' });
      if (!resp.ok) {
        let errMsg = `Print failed (HTTP ${resp.status})`;
        try {
          const j = await resp.json();
          errMsg = (j.detail && j.detail.error) || j.detail || errMsg;
        } catch (_) {}
        setPrintError(errMsg);
        return;
      }
      const blob = await resp.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = bid + '-proforma.pdf';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    } catch (e) {
      setPrintError('PDF download failed — ' + (e.message || 'network error'));
    }
  };

  const handleApprove = () => {
    if (approving) return;
    setApproving(true);
    setApproveError(null);
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    window.PzApi.approveDraft(id, updatedAt)
      .then(r => {
        if (r && r.ok) {
          draftHook && draftHook.reload && draftHook.reload();
        } else {
          setApproveError((r && r.error) || 'Approval failed — check backend logs.');
        }
      })
      .catch(e => setApproveError(e.message || 'Network error'))
      .finally(() => setApproving(false));
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

  // M5 — Edit mode handlers
  const handleEnterEdit = () => {
    if (!canEdit) return;
    const _pt = (liveDraft.payment_terms && typeof liveDraft.payment_terms === 'object')
      ? liveDraft.payment_terms : {};
    setEditFields({
      remarks:          liveDraft.remarks || '',
      currency:         liveDraft.currency || 'EUR',
      exchange_rate:    liveDraft.exchange_rate || '',
      incoterm:         liveDraft.incoterm || '',
      pt_method:        _pt.method || '',
      pt_days:          _pt.days != null ? String(_pt.days) : '',
      pt_invoice_date:  _pt.invoice_date || '',
      pt_sale_date:     _pt.sale_date || '',
    });
    setEditError(null);
    setEditMode(true);
  };
  const handleCancelEdit = () => {
    setEditMode(false);
    setEditFields({});
    setEditError(null);
  };
  const handleSaveEdit = () => {
    if (editSaving) return;
    setEditSaving(true);
    setEditError(null);
    // Build patch from changed fields only
    const patch = {};
    if (editFields.remarks !== (liveDraft.remarks || ''))
      patch.remarks = editFields.remarks;
    if (editFields.currency !== (liveDraft.currency || 'EUR'))
      patch.currency = editFields.currency;
    if (editFields.exchange_rate !== (liveDraft.exchange_rate || ''))
      patch.exchange_rate = editFields.exchange_rate;
    if (editFields.incoterm !== (liveDraft.incoterm || ''))
      patch.incoterm = editFields.incoterm;
    // payment_terms: compare individual pt_* fields against saved values
    const _origPt = (liveDraft.payment_terms && typeof liveDraft.payment_terms === 'object')
      ? liveDraft.payment_terms : {};
    const _ptChanged = (
      (editFields.pt_method        || '') !== (_origPt.method        || '') ||
      (editFields.pt_days          || '') !== (_origPt.days != null ? String(_origPt.days) : '') ||
      (editFields.pt_invoice_date  || '') !== (_origPt.invoice_date  || '') ||
      (editFields.pt_sale_date     || '') !== (_origPt.sale_date     || '')
    );
    if (_ptChanged) {
      const newPt = {};
      if (editFields.pt_method)       newPt.method       = editFields.pt_method;
      const _ptDaysNum = editFields.pt_days !== '' ? parseInt(editFields.pt_days, 10) : null;
      if (_ptDaysNum != null && !isNaN(_ptDaysNum)) newPt.days = _ptDaysNum;
      if (editFields.pt_invoice_date) newPt.invoice_date = editFields.pt_invoice_date;
      if (editFields.pt_sale_date)    newPt.sale_date    = editFields.pt_sale_date;
      patch.payment_terms = newPt;
    }
    if (Object.keys(patch).length === 0) {
      // No changes
      setEditSaving(false);
      setEditMode(false);
      return;
    }
    window.PzApi.patchDraft(draft.id, patch, liveDraft.updated_at || '')
      .then(r => {
        setEditSaving(false);
        if (r && r.ok) {
          setEditMode(false);
          setEditFields({});
          draftHook && draftHook.reload && draftHook.reload();
        } else {
          setEditError((r && r.error) || 'Save failed — check backend logs.');
        }
      })
      .catch(e => {
        setEditSaving(false);
        setEditError((e && e.message) || 'Save failed — check backend logs.');
      });
  };

  // PR B — Load from Customer Master
  const handleApplyCustomerAddress = () => {
    if (addrApplying) return;
    setAddrApplying(true);
    setAddrApplyError(null);
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    window.PzApi.applyCustomerAddress(id, updatedAt)
      .then(r => {
        if (r && r.ok) {
          draftHook && draftHook.reload && draftHook.reload();
        } else {
          setAddrApplyError((r && r.error) || 'Could not apply Customer Master address.');
        }
      })
      .catch(e => setAddrApplyError(e.message || 'Network error'))
      .finally(() => setAddrApplying(false));
  };

  // PR 1a — replace the draft's bill-to customer with an operator-selected
  // Customer Master contractor (ID-first). Line items/prices are untouched.
  const handleChangeCustomer = (sel) => {
    if (customerPickBusy || !sel) return;
    setCustomerPickBusy(true);
    setCustomerPickError(null);
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    // Single external draft writer: the canonical PATCH routes a lone
    // client_contractor_id to the internal customer-replacement operation.
    window.PzApi.patchDraft(id, { client_contractor_id: String(sel.bill_to_contractor_id || '') }, updatedAt)
      .then(r => {
        if (r && r.ok) {
          // Customer replaced. Surface any post-change migration warnings
          // (service charges / reservation could not follow) as a persistent,
          // dismissible banner. Backend guarantees a browser-safe shape.
          const warns = (r.data && Array.isArray(r.data.migration_warnings))
            ? r.data.migration_warnings : [];
          setCustomerMigrationWarnings(warns);
          setCustomerPickOpen(false);
          draftHook && draftHook.reload && draftHook.reload();
        } else {
          setCustomerPickError((r && (r.detail || r.error)) || 'Could not change customer.');
        }
      })
      .catch(e => setCustomerPickError((e && e.message) || 'Network error'))
      .finally(() => setCustomerPickBusy(false));
  };

  // PR 1a — replace the recipient (ship_to_override) with a selected Customer
  // Master contractor, independent of the bill-to customer.
  const handleChangeRecipient = (sel) => {
    if (customerPickBusy || !sel) return;
    setCustomerPickBusy(true);
    setCustomerPickError(null);
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    const shipTo = {
      name: sel.ship_to_name || sel.bill_to_name || '',
      street: sel.ship_to_street || sel.bill_to_street || '',
      city: sel.ship_to_city || sel.bill_to_city || '',
      zip: sel.ship_to_zip || sel.bill_to_postal_code || '',
      country: sel.ship_to_country || sel.country || '',
      phone: sel.ship_to_phone || sel.bill_to_phone || '',
      email: sel.ship_to_email || sel.bill_to_email || '',
      _source: 'customer_master',
    };
    window.PzApi.patchDraft(id, { ship_to_override: shipTo }, updatedAt)
      .then(r => {
        if (r && r.ok) {
          setRecipientPickOpen(false);
          draftHook && draftHook.reload && draftHook.reload();
        } else {
          setCustomerPickError((r && (r.detail || r.error)) || 'Could not change recipient.');
        }
      })
      .catch(e => setCustomerPickError((e && e.message) || 'Network error'))
      .finally(() => setCustomerPickBusy(false));
  };

  // PR 1a — copy the current bill-to onto the recipient (ship_to_override).
  const handleCopyCustomerToRecipient = () => {
    if (addrApplying) return;
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    const src = (liveDraft.buyer_override && Object.keys(liveDraft.buyer_override).length)
      ? liveDraft.buyer_override
      : { name: (customer && customer.name) || liveDraft.client_name || '' };
    const shipTo = {
      name: src.name || '', street: src.street || '', city: src.city || '',
      zip: src.zip || '', country: src.country || '',
      phone: src.phone || '', email: src.email || '', _source: 'copied_from_bill_to',
    };
    setAddrApplying(true);
    setAddrApplyError(null);
    window.PzApi.patchDraft(id, { ship_to_override: shipTo }, updatedAt)
      .then(r => {
        if (r && r.ok) { draftHook && draftHook.reload && draftHook.reload(); }
        else { setAddrApplyError((r && (r.detail || r.error)) || 'Could not copy to recipient.'); }
      })
      .catch(e => setAddrApplyError((e && e.message) || 'Network error'))
      .finally(() => setAddrApplying(false));
  };

  // PR B — Fetch service-charge suggestions
  const handleFetchChargeSuggestions = () => {
    if (chargesLoading) return;
    setChargesLoading(true);
    const id = liveDraft.id || (draft && draft.id);
    window.PzApi.suggestServiceCharges(id)
      .then(r => {
        if (r && r.ok !== false) {
          setChargeSuggestion(r);
        } else {
          setChargeSuggestion({ error: (r && r.error) || 'Could not load suggestions.' });
        }
      })
      .catch(e => setChargeSuggestion({ error: e.message || 'Network error' }))
      .finally(() => setChargesLoading(false));
  };

  // PR B — Apply individual charge type from suggestion
  const handleApplyCharge = (type) => {
    if (chargesApplying) return;
    setChargesApplying(type);
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    window.PzApi.applyServiceCharges(id, [type], updatedAt)
      .then(r => {
        if (r && r.ok !== false) {
          draftHook && draftHook.reload && draftHook.reload();
          setChargeSuggestion(null);
        } else {
          setChargeSuggestion(prev => ({ ...(prev || {}), applyError: (r && r.error) || 'Apply failed.' }));
        }
      })
      .catch(e => setChargeSuggestion(prev => ({ ...(prev || {}), applyError: e.message || 'Network error' })))
      .finally(() => setChargesApplying(null));
  };

  // PR-3 — wFirma service-product registry (layer 3), fetched lazily for the
  // freight/insurance service-product dropdown. Cached config read — not a live
  // wFirma product query — and only fired when the operator opens the add/edit UI.
  const loadServiceProducts = React.useCallback(() => {
    if (serviceProducts !== null) return;
    window.PzApi.getServiceProducts()
      .then(r => {
        const d = (r && r.data) || r || {};
        setServiceProducts((d && d.service_products) || []);
      })
      .catch(() => setServiceProducts([]));
  }, [serviceProducts]);

  // PR-3 — manual add of a freight/insurance charge via the canonical writer.
  const handleAddCharge = (charge) => {
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    return window.PzApi.addServiceCharge(id, charge, updatedAt)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && (r.error || r.detail)) || 'Add failed');
        draftHook && draftHook.reload && draftHook.reload();
        return r;
      });
  };

  // PR-3 — in-place edit of an existing charge via the canonical writer.
  const handleUpdateCharge = (chargeId, updates) => {
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    return window.PzApi.updateServiceCharge(id, chargeId, updates, updatedAt)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && (r.error || r.detail)) || 'Update failed');
        draftHook && draftHook.reload && draftHook.reload();
        return r;
      });
  };

  // PR B — Save buyer edit from modal
  const handleBuyerEditSave = () => {
    if (buyerEditSaving) return;
    setBuyerEditSaving(true);
    setBuyerEditError(null);
    const id = liveDraft.id || (draft && draft.id);
    const updatedAt = liveDraft.updated_at || (draft && draft.updated_at) || '';
    const patch = { buyer_override: { ...buyerEditFields, _source: 'manual' } };
    window.PzApi.patchDraft(id, patch, updatedAt)
      .then(r => {
        setBuyerEditSaving(false);
        if (r && r.ok) {
          setBuyerEditOpen(false);
          setBuyerEditFields({});
          draftHook && draftHook.reload && draftHook.reload();
        } else {
          setBuyerEditError((r && r.error) || 'Save failed.');
        }
      })
      .catch(e => {
        setBuyerEditSaving(false);
        setBuyerEditError(e.message || 'Network error');
      });
  };

  return (
    // Wireframe full-bleed layout: toolbar / party strip / tab strip /
    // content are edge-to-edge bands. Page-level scroll retained (the V2
    // shell owns viewport height; the wireframe's content-only scroll would
    // need a shell height contract — visual parity, safer scroll).
    <div data-testid="proforma-detail-root" style={{ flex: 1, overflowY: 'auto', background: 'var(--bg)', padding: '0 0 60px' }}>

      {/* ── Action toolbar ──────────────────────────────────────────────── */}
      <ProformaActionBar
        editMode={editMode} editSaving={editSaving}
        handleSaveEdit={handleSaveEdit} handleCancelEdit={handleCancelEdit}
        canEdit={canEdit} handleEnterEdit={handleEnterEdit}
        canCancel={canCancel} setShowCancelModal={setShowCancelModal} draftState={draftState}
        canPurge={canPurge} setShowPurgeModal={setShowPurgeModal} purgeDisabledReason={purgeDisabledReason}
        handleDuplicate={handleDuplicate} cloning={cloning}
        handleApprove={handleApprove} canApprove={canApprove} approving={approving}
        approveDisabledReason={approveDisabledReason} approveError={approveError}
        canPost={canPost} setShowPostModal={setShowPostModal} postDisabledReason={postDisabledReason}
        canConvert={canConvert} setShowConvertModal={setShowConvertModal} convertDisabledReason={convertDisabledReason}
        setShowPreview={setShowPreview}
        handleDownloadPdf={handleDownloadPdf} canPrint={canPrint}
        setShowSendModal={setShowSendModal} canSend={canSend} sendDisabledReason={sendDisabledReason}
        batchId={batchId} setShowAwbModal={setShowAwbModal}
        contractorId={contractorId} setShowInvoiceHistory={setShowInvoiceHistory}
        proformaLabel={proformaLabel} onBack={onBack}
      />

      {printError && (
        <div data-testid="print-error-banner" style={{
          margin: '8px 24px 0',
          padding: '8px 14px',
          background: 'var(--badge-red-bg)',
          border: '1px solid var(--badge-red-border)',
          borderRadius: 6,
          fontSize: 12,
          color: 'var(--badge-red-text)',
          fontWeight: 600,
        }}>
          ⚠ {printError}
        </div>
      )}

      {/* Customer-change migration warning banner — page-level, persistent +
          dismissible. Shown after a successful customer replacement whose
          service-charge / reservation migration failed. Messages come from the
          backend's browser-safe stable contract (no raw exception text).
          Lives here (ProformaDetailPage) alongside the state + handleChangeCustomer
          + picker so the warning stays visible after the picker modal closes. */}
      {customerMigrationWarnings.length > 0 && (
        <div role="alert" data-testid="customer-migration-warning-banner"
             style={{ margin: '8px 24px 0', padding: '10px 14px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-amber-text)' }}>
              ⚠ Customer changed — follow-up needed
            </div>
            <button type="button" data-testid="customer-migration-warning-dismiss"
                    onClick={() => setCustomerMigrationWarnings([])}
                    style={{ background: 'transparent', border: '1px solid var(--badge-amber-border)', color: 'var(--badge-amber-text)', borderRadius: 4, fontSize: 11, fontWeight: 600, padding: '2px 8px', cursor: 'pointer' }}>
              Dismiss
            </button>
          </div>
          {customerMigrationWarnings.map((w, i) => (
            <div key={(w && w.type) || i}
                 data-testid={`customer-migration-warning-${(w && w.type) || i}`}
                 style={{ fontSize: 12, color: 'var(--badge-amber-text)', marginTop: 4 }}>
              • {(w && w.message) || 'A follow-up action could not be completed.'}
            </div>
          ))}
        </div>
      )}

      {/* ── PROFORMA STATUS HEADER — persistent, always visible ───────────────── */}
      <ProformaStatusHeader
        alreadyPosted={alreadyPosted}
        readinessPost={readinessPost}
        postBlocked={postBlocked}
        postBlockers={postBlockers}
        approveBlocked={approveBlocked}
        approveBlockers={approveBlockers}
        stateAllowsApprove={stateAllowsApprove}
        alreadyApproved={alreadyApproved}
        canPost={canPost}
        canConvert={canConvert}
        customer={customer}
        _cmrTotalPcs={_cmrTotalPcs}
        liveDraft={liveDraft}
        draft={draft}
      />

      {/* ── UNIFIED "WHAT'S BLOCKING" PANEL — consolidates blocker sources ──── */}
      <ProformaBlockerPanel
        postBlockers={postBlockers}
        approveBlockers={approveBlockers}
      />

      {/* ── READINESS + OVERBILL PANELS ─────────────────────────────────────── */}
      <ProformaReadinessPanel
        readinessPost={readinessPost}
        linesByCode={linesByCode}
        resolvingDesign={resolvingDesign}
        resolveError={resolveError}
        doResolveAmbiguity={doResolveAmbiguity}
        savingVat={savingVat}
        vatSaveError={vatSaveError}
        doSaveEuVat={doSaveEuVat}
        draftLines={liveDraft.editable_lines || []}
        reloadReadiness={reloadReadiness}
        draftId={liveDraft.id || (draft && draft.id)}
        blockerPanelReasons={blockerPanelReasons}
      />

      {/* ── Party cards + address authority bar ─────────────────────────── */}
      <ProformaPartyCards
        exporter={exporter}
        customer={customer}
        shipTo={shipTo}
        bo={bo}
        canEdit={canEdit}
        liveDraft={liveDraft}
        draft={draft}
        draftHook={draftHook}
        addrApplying={addrApplying}
        addrApplyError={addrApplyError}
        handleApplyCustomerAddress={handleApplyCustomerAddress}
        setBuyerEditFields={setBuyerEditFields}
        setBuyerEditError={setBuyerEditError}
        setBuyerEditOpen={setBuyerEditOpen}
        onOpenCustomerPicker={() => { setCustomerPickError(null); setCustomerPickOpen(true); }}
        onOpenRecipientPicker={() => { setCustomerPickError(null); setRecipientPickOpen(true); }}
        onCopyToRecipient={handleCopyCustomerToRecipient}
        draftState={draftState}
      />

      {/* ── Workflow rail (authority-backed: draft_state machine) ───────────── */}
      <WorkflowRail
        draftState={draftState}
        wfirmaProformaId={liveDraft.wfirma_proforma_id || (draft && draft.wfirma_proforma_id)}
        wfirmaInvoiceId={liveDraft.wfirma_invoice_id || (draft && draft.wfirma_invoice_id)}
      />

      {/* ── Tab strip (wireframe: 2px accent underline, card band) ─────────── */}
      <div style={{
        display: 'flex', gap: 4, padding: '0 32px',
        background: 'var(--card)',
        borderBottom: '1px solid var(--border)',
        overflowX: 'auto', flexShrink: 0,
      }}>
        {PROFORMA_TABS.map(t => (
          <button key={t.id} data-testid={`tab-${t.id}`} onClick={() => setActiveTab(t.id)} style={{
            padding: '12px 16px', background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: `2px solid ${activeTab === t.id ? 'var(--accent)' : 'transparent'}`,
            color: activeTab === t.id ? 'var(--text)' : 'var(--text-2)',
            fontSize: 13, fontWeight: activeTab === t.id ? 700 : 500,
            transition: 'all 0.12s', marginBottom: -1, fontFamily: 'inherit',
            whiteSpace: 'nowrap',
          }}>{t.label}</button>
        ))}
      </div>

      {/* ── Tab content (wireframe: open --bg band, 24/32 padding) ─────────── */}
      <div style={{
        padding: '24px 32px',
        minHeight: 320,
        overflow: 'auto',
      }}>
        {activeTab === 'overview' && (
          <React.Fragment>
            <ProformaOverviewTab
              detail={detail}
              lines={lines}
              fxRate={fxRate}
              vatResolution={vatResolution}
              blockingReasons={blockingReasons}
              exportBlockers={exportBlockers}
              editMode={editMode}
              editFields={editFields}
              onEditField={(k, v) => setEditFields(prev => ({ ...prev, [k]: v }))}
              editError={editError}
            />
            {/* ── Commercial terms & charges — THREE DISTINCT AUTHORITIES ──
                1. Customer Master DEFAULTS (advisory suggestions you can apply)
                2. SAVED DRAFT values / charges (what this proforma will bill)
                3. wFirma service-product REGISTRY (mapping used only at posting)
                Kept as separate panels so it is always clear which layer a value
                comes from and which command persists the operator's decision. */}
            <div data-testid="pf-commercial-section-note" style={{ marginTop: 20, fontSize: 11, color: 'var(--text-3)', lineHeight: 1.5 }}>
              <strong style={{ color: 'var(--text-2)' }}>Commercial terms &amp; charges</strong> — three layers:
              <span style={{ color: 'var(--text-2)' }}> Customer Master defaults</span> (apply advisory) ·
              <span style={{ color: 'var(--text-2)' }}> saved draft values/charges</span> (what bills) ·
              <span style={{ color: 'var(--text-2)' }}> wFirma service-product registry</span> (used at posting).
            </div>
            {/* Layer 1 — CM commercial defaults — Preview→Apply (Slice 1) */}
            <CustomerMasterSuggestions
              suggestions={liveDraft.customer_master_suggestions}
              draftId={liveDraft.id || (draft && draft.id)}
              updatedAt={liveDraft.updated_at || (draft && draft.updated_at) || ''}
              onReload={() => draftHook && draftHook.reload && draftHook.reload()}
            />
            {/* Layer 2a — operator-set commercial terms (controlled dropdowns) */}
            <CommercialTermsEditor
              draftId={liveDraft.id || (draft && draft.id)}
              liveDraft={liveDraft}
              updatedAt={liveDraft.updated_at || (draft && draft.updated_at) || ''}
              onReload={() => draftHook && draftHook.reload && draftHook.reload()}
            />
            {/* Layer 2b — saved draft freight/insurance charges */}
            <ServiceChargesPanel
              charges={liveDraft.service_charges || []}
              canEdit={canEdit}
              draftState={draftState}
              draftCurrency={draftCurrency}
              serviceProducts={serviceProducts}
              onLoadServiceProducts={loadServiceProducts}
              suggestion={chargeSuggestion}
              chargesLoading={chargesLoading}
              chargesApplying={chargesApplying}
              onFetchSuggestions={handleFetchChargeSuggestions}
              onApplyCharge={handleApplyCharge}
              onAddCharge={handleAddCharge}
              onUpdateCharge={handleUpdateCharge}
              onDismissSuggestion={() => setChargeSuggestion(null)}
              onDeleteCharge={(chargeId) => {
                const id = liveDraft.id || (draft && draft.id);
                window.PzApi.deleteServiceCharge(id, chargeId)
                  .then(r => r && r.ok && draftHook && draftHook.reload && draftHook.reload());
              }}
            />
            {/* Layer 3 — wFirma service-product registry — GET/PUT /proforma/service-products */}
            <ServiceProductRegistryPanel />
          </React.Fragment>
        )}
        {activeTab === 'lines' && <ProformaLinesTab
          lines={lines} currency={draftCurrency}
          onAddLine={() => setEditMode(true)}
          serviceCharges={liveDraft.service_charges}
          draftId={draft && draft.id}
          expectedUpdatedAt={liveDraft.updated_at || (draft && draft.updated_at) || ''}
          editMode={editMode && canEdit}
          onChanged={() => { draftHook && draftHook.reload && draftHook.reload(); }}
        />}
        {activeTab === 'source' && (
          <SourceExtractionTab
            draftId={draft && draft.id}
            batchId={liveDraft.batch_id || (draft && draft.batch_id) || ''}
            expectedUpdatedAt={liveDraft.updated_at || (draft && draft.updated_at) || ''}
            onSaved={() => { draftHook && draftHook.reload && draftHook.reload(); }}
          />
        )}
        {activeTab === 'logistics' && (() => {
          // REUSE-ONLY read view (Wave 4 Item 12). Composes ONLY data this component
          // already computes from existing authorities — the CMR document authority
          // (cmrPreviewData), the draft's billed editable_lines, and matched batch
          // packing rows (net/gross weight enrichment). No new fetch, no new endpoint,
          // no new authority. Advisory transport summary — NEVER a fiscal gate.
          const _car = cmrPreviewData.carrier || {};
          const _wl  = _cmrAggPackingLines.lines || [];
          const _netTotal = _wl.reduce((s, r) => s + (Number(r.net_weight) || 0), 0);
          // Gross total via the same per-line packing enrichment used for CMR.
          const _grossTotal = (liveDraft.editable_lines || []).reduce((s, ln) => {
            const pk = _enrichPacking(ln); const g = Number(pk.gross_weight) || 0; return s + g;
          }, 0);
          // UNIT AUTHORITY: packing_lines.net_weight / gross_weight are stored
          // in GRAMS (supplier sheet columns "GR.WT/NT.WT (GMS)"). Per-line
          // jewellery weights display in grams; shipment-level totals display
          // in kg via grams / 1000. Stored data is never rewritten.
          const _fmtG = (v) => (Number(v) > 0 ? Number(v).toFixed(3) + ' g' : '—');
          const _fmtKgFromG = (g) => (Number(g) > 0 ? (Number(g) / 1000).toFixed(3) + ' kg' : '—');
          const _kv = (k, v, testid) => (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '6px 0', borderBottom: '1px solid var(--border)' }} data-testid={testid}>
              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{k}</span>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', textAlign: 'right' }}>{v}</span>
            </div>
          );
          return (
            <div data-testid="pf-detail-logistics">
              <PfSectionLabel>Carrier &amp; transport</PfSectionLabel>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
                Read-only transport summary composed from this draft's billed lines, matched packing rows, and the CMR document authority. Advisory — never a fiscal gate.
              </div>

              {/* Carrier / route — reuses cmrPreviewData.carrier + derived CMR number */}
              <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 20px', marginBottom: 20, boxShadow: '0 1px 2px var(--shadow)' }} data-testid="pf-logistics-carrier">
                {_kv('Carrier', _car.name || '—', 'pf-logistics-carrier-name')}
                {_kv('Service', _car.service || '—', 'pf-logistics-service')}
                {_kv('Incoterm', _car.incoterm || '—', 'pf-logistics-incoterm')}
                {_kv('Route', [_car.origin, _car.destination].filter(v => v && v !== '—').join('  →  ') || '—', 'pf-logistics-route')}
                {_kv('CMR No.', cmrPreviewData.cmr_no || '—', 'pf-logistics-cmr-no')}
                {_kv('Total pieces', _cmrTotalPcs > 0 ? _cmrTotalPcs : '—', 'pf-logistics-pieces')}
                {/* HTML-parity: CMR preview/download in Logistics. Reuses the existing Print Preview
                   modal (CMR renderer) — no new endpoint; download = Download PDF inside the preview. */}
                <div style={{ display: 'flex', gap: 8, paddingTop: 10, marginTop: 4, borderTop: '1px solid var(--border)' }}>
                  <button data-testid="pf-logistics-cmr-preview"
                    onClick={() => { setPreviewDocType('cmr'); setShowPreview(true); }}
                    style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600, color: 'var(--text)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer' }}>
                    ◫ Preview / Download CMR
                  </button>
                </div>
              </div>

              {/* Weights & packages — wireframe StatTiles over the same packing
                  aggregation (gross/net in grams → kg display; tare has no stored
                  authority → '—'). Detail table below is supplementary. */}
              <PfSectionLabel>Weights &amp; packages</PfSectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14, marginBottom: 14 }}>
                <PfStatTile label="Gross weight" value={_fmtKgFromG(_grossTotal)} accent="var(--accent)" data-testid="pf-logistics-tile-gross" />
                <PfStatTile label="Net weight" value={_fmtKgFromG(_netTotal)} data-testid="pf-logistics-tile-net" />
                <PfStatTile label="Items" value={_cmrTotalPcs > 0 ? _cmrTotalPcs : '—'} data-testid="pf-logistics-tile-items" />
                <PfStatTile label="Tare weight" value="—" data-testid="pf-logistics-tile-tare" />
              </div>
              {_wl.length > 0 ? (
                <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 12 }} data-testid="pf-logistics-weights">
                  <thead>
                    <tr style={{ textAlign: 'left', color: 'var(--text-3)', fontSize: 11 }}>
                      <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Item type</th>
                      <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right' }}>Qty</th>
                      <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right' }}>Net weight</th>
                    </tr>
                  </thead>
                  <tbody>
                    {_wl.map((r, i) => (
                      <tr key={i} data-testid="pf-logistics-weight-row">
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 12 }}>{r.item_type}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 12, textAlign: 'right' }}>{Number(r.qty) || 0}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 12, textAlign: 'right' }}>{_fmtG(r.net_weight)}</td>
                      </tr>
                    ))}
                    <tr style={{ fontWeight: 700 }} data-testid="pf-logistics-weight-total">
                      <td style={{ padding: '6px 8px', fontSize: 12 }}>Total</td>
                      <td style={{ padding: '6px 8px', fontSize: 12, textAlign: 'right' }}>{_cmrTotalPcs > 0 ? _cmrTotalPcs : '—'}</td>
                      <td style={{ padding: '6px 8px', fontSize: 12, textAlign: 'right' }}>{_fmtG(_netTotal)}</td>
                    </tr>
                  </tbody>
                </table>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12 }} data-testid="pf-logistics-weights-empty">No packing weight data matched for this draft's lines yet.</div>
              )}
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 4 }} data-testid="pf-logistics-gross-total">Gross weight (enriched): <strong>{_fmtKgFromG(_grossTotal)}</strong></div>
              {cmrPreviewData.goods_summary ? (
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 12 }} data-testid="pf-logistics-goods-summary">Goods: {cmrPreviewData.goods_summary}</div>
              ) : null}

              {/* DHL AWB / carrier shipment summary — real recorded shipment
                  (GET /carrier/{batch}/shipment). Honest empty state when none. */}
              <div style={{ marginTop: 20 }}>
                <PfSectionLabel>DHL AWB / carrier shipment</PfSectionLabel>
              </div>
              {carrierShipment ? (
                <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 20px', marginBottom: 8, boxShadow: '0 1px 2px var(--shadow)' }} data-testid="pf-logistics-awb">
                  {_kv('Carrier', carrierShipment.carrier || 'DHL', 'pf-logistics-awb-carrier')}
                  {_kv('AWB / tracking', carrierShipment.tracking_ref
                    || (carrierShipment.saved_labels_exist
                        ? 'recorded before reference store — see saved labels'
                        : '—'), 'pf-logistics-awb-ref')}
                  {_kv('Service / product', carrierShipment.service_code || '—', 'pf-logistics-awb-service')}
                  {_kv('Mode', `${carrierShipment.mode || '—'}${carrierShipment.simulated ? ' (simulated)' : ''}`, 'pf-logistics-awb-mode')}
                  {_kv('Weight', carrierShipment.weight_kg != null ? `${carrierShipment.weight_kg} kg` : '—', 'pf-logistics-awb-weight')}
                  {_kv('Dimensions', carrierShipment.dimensions
                    ? `${carrierShipment.dimensions.length_cm}×${carrierShipment.dimensions.width_cm}×${carrierShipment.dimensions.height_cm} cm`
                    : '—', 'pf-logistics-awb-dims')}
                  {_kv('Box / package profile', carrierShipment.box_type_code || '— (manual dimensions)', 'pf-logistics-awb-box')}
                  {_kv('Declared value', carrierShipment.declared_value != null
                    ? `${carrierShipment.declared_value} ${carrierShipment.currency || ''}` : '—', 'pf-logistics-awb-declared')}
                  {_kv('Created', carrierShipment.created_at || '—', 'pf-logistics-awb-created')}
                  {carrierShipment.do_not_use ? (
                    <div style={{ marginTop: 8, padding: '8px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, color: 'var(--badge-red-text)', fontSize: 12, fontWeight: 700 }} data-testid="pf-logistics-awb-dnu-badge">
                      DO NOT USE — duplicate/unused label
                      <div style={{ fontWeight: 500, marginTop: 3, fontSize: 11 }}>
                        {carrierShipment.do_not_use_reason || 'no reason recorded'}
                        {carrierShipment.do_not_use_at ? ` · ${carrierShipment.do_not_use_at}` : ''}
                        {carrierShipment.do_not_use_by ? ` · by ${carrierShipment.do_not_use_by}` : ''}
                      </div>
                      <div style={{ fontWeight: 500, marginTop: 3, fontSize: 10.5 }}>
                        Local status only — nothing was cancelled at DHL. Downloads below are archived audit copies.
                      </div>
                    </div>
                  ) : null}
                  {(carrierShipment.label_download_url || carrierShipment.waybill_doc_download_url
                    || carrierShipment.shipment_receipt_download_url) ? (
                    <div style={{ paddingTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {[
                        [carrierShipment.label_download_url,            '⬇ Transport Label',  'pf-logistics-awb-label-download'],
                        [carrierShipment.waybill_doc_download_url,      '⬇ Waybill Doc',      'pf-logistics-awb-waybill-download'],
                        [carrierShipment.shipment_receipt_download_url, '⬇ Shipment Receipt', 'pf-logistics-awb-receipt-download'],
                      ].map(([href, label, tid]) => href ? (
                        <a key={tid} download data-testid={tid}
                          href={carrierShipment.do_not_use ? `${href}?archived=true` : href}
                          style={{ fontSize: 12, fontWeight: 600, textDecoration: 'none', padding: '5px 10px', borderRadius: 6, display: 'inline-block', background: 'var(--bg)',
                                   color: carrierShipment.do_not_use ? 'var(--badge-red-text)' : 'var(--text)',
                                   border: `1px solid ${carrierShipment.do_not_use ? 'var(--badge-red-border)' : 'var(--border)'}` }}>
                          {carrierShipment.do_not_use ? `Archived duplicate label — ${label.replace('⬇ ', '')}` : label}
                        </a>
                      ) : null)}
                    </div>
                  ) : null}
                  {(carrierShipment.tracking_ref && !carrierShipment.do_not_use) ? (
                    <div style={{ paddingTop: 10 }}>
                      <button onClick={markAwbDoNotUse} data-testid="pf-logistics-awb-mark-dnu"
                        style={{ fontSize: 12, fontWeight: 600, padding: '5px 10px', borderRadius: 6, cursor: 'pointer', background: 'var(--bg)', color: 'var(--badge-red-text)', border: '1px solid var(--badge-red-border)' }}>
                        ⚑ Mark as Do Not Use
                      </button>
                      <span style={{ fontSize: 10.5, color: 'var(--text-3)', marginLeft: 8 }}>
                        duplicate/unused label — local flag, does not cancel anything at DHL
                      </span>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div style={{ padding: '12px 16px', background: 'var(--bg-subtle)', border: '1px dashed var(--border)', borderRadius: 8, color: 'var(--text-3)', fontSize: 11.5, lineHeight: 1.6, marginTop: 4 }} data-testid="pf-logistics-awb-empty">
                  No DHL AWB recorded for this batch yet. Generate one with ⚡ AWB Generate in the toolbar — the tracking number, service, box profile and label download will appear here.
                </div>
              )}

              {/* Real batch-scoped timeline + clearance (reuse-only, local audit).
                  Complements the AWB block above — the live AWB is now shown by the
                  carrier-shipment authority (main), so the old "AWB not shown" advisory
                  is dropped as no longer accurate. */}
              <LogisticsTracking batchId={liveDraft.batch_id || (draft && draft.batch_id)} />
            </div>
          );
        })()}
        {activeTab === 'documents' && (() => {
          // REUSE-ONLY read manifest (Wave 4 Item 13). Lists the documents this
          // proforma draft can produce, each with its REAL availability state and
          // the EXISTING action to obtain it. No new endpoint, authority, fetch,
          // or write path — reuses handleDownloadPdf (proforma PDF), the Print
          // Preview modal (CMR / Packing List), and in-component draft state.
          // Existing Print/Download flows are preserved, not replaced.
          const _openPreview = (t) => { setPreviewDocType(t); setShowPreview(true); };
          // Local do-not-use flag: primary downloads become archived audit
          // copies (?archived=true) — never a courier-facing action.
          const _dnu = !!(carrierShipment && carrierShipment.do_not_use);
          const _dnuBadge = _dnu ? 'DO NOT USE — duplicate/unused label' : null;
          const _dhlAction = (href, label, testid) => {
            if (!href) return null;
            return _dnu
              ? { label: 'Archived duplicate label', href: `${href}?archived=true`, testid }
              : { label, href, testid };
          };
          const _proformaNo  = liveDraft.wfirma_proforma_fullnumber || (draft && draft.wfirma_proforma_fullnumber) || '';
          const _invoiceNo   = liveDraft.wfirma_invoice_number || (liveDraft.wfirma_invoice_id ? String(liveDraft.wfirma_invoice_id) : '');
          const _docs = [
            {
              key: 'proforma', name: 'Proforma PDF',
              authority: _proformaNo ? `wFirma proforma ${_proformaNo}` : 'wFirma proforma document',
              available: canPrint,
              action: canPrint ? { label: '↓ Download', onClick: handleDownloadPdf, testid: 'pf-doc-proforma-download' } : null,
              // Print preview (A4 HTML snapshot) — reuse GET /proforma/draft/{id}/preview.html.
              // Local render, never calls wFirma → available even before posting.
              secondaryAction: (draft && draft.id) ? { label: '◫ Print preview', onClick: () => { const a = document.createElement('a'); a.href = `/api/v1/proforma/draft/${draft.id}/preview.html`; a.target = '_blank'; a.rel = 'noopener'; document.body.appendChild(a); a.click(); document.body.removeChild(a); }, testid: 'pf-doc-proforma-preview' } : null,
              pending: canPrint ? null : 'PDF available after this draft is posted to wFirma (⇪ Post to wFirma). Print preview works now.',
            },
            {
              key: 'cmr', name: 'CMR (transport)',
              authority: cmrPreviewData.cmr_no || 'CMR document (generated)',
              available: true,
              action: { label: '◫ Preview', onClick: () => _openPreview('cmr'), testid: 'pf-doc-cmr-preview' },
              pending: null,
            },
            {
              key: 'packing', name: 'Packing List',
              authority: 'Packing list (generated)',
              available: true,
              action: { label: '◫ Preview', onClick: () => _openPreview('packing'), testid: 'pf-doc-packing-preview' },
              pending: null,
            },
            {
              key: 'invoice', name: 'Invoice PDF',
              authority: _invoiceNo ? `wFirma invoice ${_invoiceNo}` : 'wFirma invoice document',
              available: false,
              action: null,
              pending: alreadyConverted
                ? `Invoice ${_invoiceNo || 'created'} — the PDF is served by wFirma; the app does not expose an invoice-PDF download endpoint yet.`
                : 'Available after Convert to Invoice (toolbar).',
            },
            {
              key: 'dhl_label', name: 'DHL Transport Label',
              authority: carrierShipment && carrierShipment.tracking_ref
                ? `AWB ${carrierShipment.tracking_ref} · attach to package`
                : 'DHL transport label — attach to package (carrier label store)',
              available: !!(carrierShipment && carrierShipment.label_download_url),
              badge: _dnuBadge,
              action: _dhlAction(carrierShipment && carrierShipment.label_download_url,
                                 '↓ Download Label', 'pf-doc-dhl-label-download'),
              pending: (carrierShipment && carrierShipment.label_download_url) ? null
                : (carrierShipment
                    ? (carrierShipment.saved_labels_exist
                        ? 'AWB recorded before the reference store — labels are saved on the server; ask ops or rebook to link one here.'
                        : 'No saved label for this shipment.')
                    : 'Available after a DHL AWB is generated (⚡ AWB Generate).'),
            },
            {
              key: 'dhl_waybill', name: 'DHL Waybill Doc — Hand to Courier',
              authority: carrierShipment && carrierShipment.tracking_ref
                ? `AWB ${carrierShipment.tracking_ref} · hand to courier at pickup`
                : 'DHL waybill document — hand to courier at pickup',
              available: !!(carrierShipment && carrierShipment.waybill_doc_download_url),
              badge: _dnuBadge,
              action: _dhlAction(carrierShipment && carrierShipment.waybill_doc_download_url,
                                 '↓ Download Waybill', 'pf-doc-dhl-waybill-download'),
              pending: (carrierShipment && carrierShipment.waybill_doc_download_url) ? null
                : (carrierShipment
                    ? 'No waybill document saved for this shipment (bookings before waybill-doc support, or DHL did not return one).'
                    : 'Available after a DHL AWB is generated (⚡ AWB Generate).'),
            },
            {
              key: 'dhl_receipt', name: 'DHL Shipment Receipt',
              authority: carrierShipment && carrierShipment.tracking_ref
                ? `AWB ${carrierShipment.tracking_ref} · operator/customer receipt`
                : 'DHL shipment receipt — operator/customer copy',
              available: !!(carrierShipment && carrierShipment.shipment_receipt_download_url),
              badge: _dnuBadge,
              action: _dhlAction(carrierShipment && carrierShipment.shipment_receipt_download_url,
                                 '↓ Download Receipt', 'pf-doc-dhl-receipt-download'),
              pending: (carrierShipment && carrierShipment.shipment_receipt_download_url) ? null
                : (carrierShipment
                    ? 'No shipment receipt saved for this shipment (bookings before receipt support, or DHL did not return one).'
                    : 'Available after a DHL AWB is generated (⚡ AWB Generate).'),
            },
            {
              key: 'dhl_documents', name: 'DHL Commercial Documents',
              authority: 'Commercial invoice + packing list + CN23 package',
              available: !!(carrierShipment && carrierShipment.documents_available),
              action: (carrierShipment && carrierShipment.commercial_documents_url)
                ? { label: '↓ Download', href: carrierShipment.commercial_documents_url, testid: 'pf-doc-dhl-documents-download' }
                : null,
              pending: (carrierShipment && carrierShipment.documents_available) ? null
                : 'Not available yet — document packages are generated on demand (⚙ label-package) and are not persisted for download yet.',
            },
          ];
          // Wireframe doc-card grid: icon + name + state chip + authority line +
          // actions. Same _docs manifest, actions, and testids — presentation only.
          const _icons = {
            proforma: '🧾', cmr: '🚚', packing: '📄', invoice: '🧾',
            dhl_label: '🏷', dhl_waybill: '📦', dhl_receipt: '🧾', dhl_documents: '⬇',
          };
          const _chip = (d) => d.available
            ? { label: 'Generated', bg: 'var(--badge-green-bg)', c: 'var(--badge-green-text)' }
            : { label: 'Pending',   bg: 'var(--badge-neutral-bg)', c: 'var(--badge-neutral-text)' };
          const _actBtn = { padding: '6px 12px', fontSize: 12, fontWeight: 600, color: 'var(--text)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', textDecoration: 'none', display: 'inline-block', whiteSpace: 'nowrap' };
          return (
            <div data-testid="pf-detail-documents">
              <PfSectionLabel>Generated documents</PfSectionLabel>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
                Read-only manifest — each card shows the real document authority and the existing action to view or download it. No document is fabricated.
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 14 }}>
                {_docs.map((d) => {
                  const chip = _chip(d);
                  return (
                    <div key={d.key} data-testid={`pf-doc-row-${d.key}`}
                      style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, display: 'flex', alignItems: 'flex-start', gap: 14, boxShadow: '0 1px 2px var(--shadow)' }}>
                      <div style={{ fontSize: 28, lineHeight: 1 }}>{_icons[d.key] || '📄'}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text)' }}>{d.name}</span>
                          <span style={{ padding: '2px 8px', borderRadius: 4, background: chip.bg, color: chip.c, fontSize: 10, fontWeight: 700 }}>{chip.label}</span>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 3 }}>{d.authority}</div>
                        {d.badge ? (
                          <div style={{ display: 'inline-block', marginTop: 4, padding: '2px 8px', borderRadius: 4, fontSize: 10.5, fontWeight: 700, background: 'var(--badge-red-bg)', color: 'var(--badge-red-text)', border: '1px solid var(--badge-red-border)' }}
                            data-testid={`pf-doc-dnu-${d.key}`}>
                            {d.badge}
                          </div>
                        ) : null}
                        {d.pending ? (
                          <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginTop: 4 }} data-testid={`pf-doc-pending-${d.key}`}>
                            <strong>Backend Pending:</strong> {d.pending}
                          </div>
                        ) : null}
                        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
                          {d.secondaryAction ? (
                            <button onClick={d.secondaryAction.onClick} data-testid={d.secondaryAction.testid} style={_actBtn}>
                              {d.secondaryAction.label}
                            </button>
                          ) : null}
                          {d.action ? (
                            d.action.href ? (
                              <a href={d.action.href} download data-testid={d.action.testid} style={_actBtn}>
                                {d.action.label}
                              </a>
                            ) : (
                              <button onClick={d.action.onClick} data-testid={d.action.testid} style={_actBtn}>
                                {d.action.label}
                              </button>
                            )
                          ) : (!d.secondaryAction ? (
                            <span style={{ fontSize: 11, color: 'var(--text-3)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 999, opacity: 0.45 }} data-testid={`pf-doc-unavailable-${d.key}`}>{d.key.startsWith('dhl_') ? 'Not available yet' : 'Not available'}</span>
                          ) : null)}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Real shipment-document registry (reuse-only, batch-scoped) */}
              <div style={{ marginTop: 20 }}>
                <DocumentsRegistry batchId={liveDraft.batch_id || (draft && draft.batch_id)} />
              </div>
            </div>
          );
        })()}
        {activeTab === 'customer_mapping' && (
          <ProformaCustomerMappingTab customer={customer} />
        )}
        {activeTab === 'reservation' && (
          <ProformaReservationTab
            blockingReasons={blockingReasons}
            exportBlockers={exportBlockers}
            preview={preview}
            canConvert={canConvert}
            convertDisabledReason={convertDisabledReason}
            onConvert={() => canConvert && setShowConvertModal(true)}
            reservationLoading={reservationLoading}
            reservationReady={reservationReady}
            reservationBatchReasons={reservationBatchReasons}
            reservationDraftReasons={reservationDraftReasons}
            reservationBatchAdvisories={reservationBatchAdvisories}
            reservationDraftAdvisories={reservationDraftAdvisories}
            reservationClientName={clientName}
            draftLineCount={lines.length}
            reservationExists={reservationExists}
            reservationId={reservationId}
            reservationBusy={reservationBusy}
            reservationResult={reservationResult}
            batchId={batchId}
            onCreateReservation={() => { setReservationResult(null); setShowReservationModal(true); }}
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
      {showReservationModal && (
        <Modal title="Create wFirma Reservation" onClose={() => !reservationBusy && setShowReservationModal(false)}>
          <div data-testid="reservation-confirm-modal" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ fontSize: 13, color: 'var(--text)' }}>
              This creates a <strong>live wFirma reservation</strong> for client{' '}
              <strong>{clientName || '—'}</strong> on batch <code style={{ fontSize: 11 }}>{batchId}</code>.
              The backend re-checks all reservation gates before writing.
            </div>
            {reservationResult && !reservationResult.ok && (
              <div data-testid="reservation-error" style={{
                fontSize: 12, color: 'var(--badge-red-text)', background: 'var(--badge-red-bg)',
                border: '1px solid var(--badge-red-border)', borderRadius: 6, padding: '8px 10px',
              }}>
                Reservation failed{reservationResult.code ? ` (${reservationResult.code})` : ''}: {reservationResult.error}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <Btn variant="outline" disabled={reservationBusy}
                   onClick={() => setShowReservationModal(false)}
                   data-testid="reservation-confirm-cancel">Cancel</Btn>
              <Btn variant="primary" disabled={reservationBusy || !reservationReady}
                   onClick={doCreateReservation}
                   data-testid="reservation-confirm-create">
                {reservationBusy ? 'Creating…' : 'Confirm — create wFirma reservation'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}
      {showPreview && (
        <ProformaPreviewModal
          docData={previewDocData}
          cmrData={cmrPreviewData}
          packingData={packingListData}
          variant={previewVariant}
          onVariantChange={setPreviewVariant}
          docType={previewDocType}
          onDocTypeChange={setPreviewDocType}
          onClose={() => setShowPreview(false)}
          onEditRequest={canEdit ? () => {
            setShowPreview(false);
            setActiveTab('overview');
            handleEnterEdit();
          } : undefined}
        />
      )}
      {showCancelModal && (
        <CancelDraftModal
          draft={draft}
          liveDraft={liveDraft}
          onClose={() => setShowCancelModal(false)}
          onSuccess={() => {
            setShowCancelModal(false);
            draftHook && draftHook.reload && draftHook.reload();
          }}
        />
      )}
      {showPurgeModal && (
        <PurgeDraftModal
          draft={draft}
          onClose={() => setShowPurgeModal(false)}
          onSuccess={() => {
            setShowPurgeModal(false);
            onBack && onBack({ purged: true });
          }}
        />
      )}
      {showInvoiceHistory && contractorId && (
        <PriorInvoiceHistoryModal
          contractorId={contractorId}
          contractorName={customer.wfirmaName || customer.name}
          onClose={() => setShowInvoiceHistory(false)}
        />
      )}
      {showSendModal && (
        <SendProformaModal
          draft={draft}
          liveDraft={liveDraft}
          recipientEmail={customerEmail}
          onClose={() => setShowSendModal(false)}
          onSuccess={() => {
            setShowSendModal(false);
            draftHook && draftHook.reload && draftHook.reload();
          }}
        />
      )}
      {showAwbModal && batchId && (() => {
        // Declared value — the SAME total authority the Overview "Amount due"
        // uses (sum of billed lines in the draft currency), plus service /
        // shipping charges in the same currency (they post as proforma lines,
        // so the proforma gross total includes them). No new calculation
        // authority — this composes the values already on this page.
        const _awbLinesTotal = lines.reduce((s, l) => s + (Number(l.netEur) || 0), 0);
        const _awbChargesTotal = (liveDraft.service_charges || []).reduce((s, c) =>
          s + (((c.currency || draftCurrency) === draftCurrency) ? (Number(c.amount) || 0) : 0), 0);
        const _awbDeclared = _awbLinesTotal + _awbChargesTotal;
        // Canonical proforma/order number — same field every panel on this
        // page displays (never the batch id).
        const _awbProformaNo = (liveDraft && liveDraft.wfirma_proforma_fullnumber)
          || (draft && draft.wfirma_proforma_fullnumber)
          || (draft && draft.doc_no)
          || (liveDraft && liveDraft.proforma_number) || '';
        return (
        <AwbGenerateModal
          batchId={batchId}
          prefill={{
            // Value — Overview total authority (lines + same-currency charges)
            declared_value:     _awbDeclared > 0 ? _awbDeclared.toFixed(2) : '',
            currency:           draftCurrency || 'EUR',
            // Recipient identity — Customer Master via ship_to / buyer_override
            company_name:       (sto && sto.name)    || (bo && bo.name)    || customer.name || '',
            name:               '',
            street:             (sto && sto.street)  || (bo && bo.street)  || '',
            city:               (sto && sto.city)    || (bo && bo.city)    || '',
            postal_code:        (sto && sto.zip)     || (bo && bo.zip)     || '',
            country_code:       (sto && sto.country) || (bo && bo.country) || '',
            phone:              (sto && sto.phone)   || (bo && bo.phone)   || '',
            email:              (sto && sto.email)   || (bo && bo.email)   || '',
            // Customs — Customer Master
            receiver_vat_id:    (bo && (bo.vat_id || bo.vat_eu_number)) || '',
            receiver_eori:      (bo && bo.eori) || '',
            // References — customer ref = canonical proforma number;
            // shipment ref = internal batch id.
            customer_reference: _awbProformaNo,
            shipment_reference: batchId || '',
            // Proforma number for the result summary card (display only)
            proforma_number:    _awbProformaNo,
            // Description — default; operator overrides in modal
            description:        'Jewellery',
            // Client identity — Customer Master baseline for the shipping
            // save-confirmation workflow (compare + explicit-save target).
            client_contractor_id: (liveDraft && liveDraft.client_contractor_id)
              || (draft && draft.client_contractor_id) || '',
            client_name:        (liveDraft && liveDraft.client_name)
              || (draft && draft.client_name) || '',
          }}
          onClose={() => setShowAwbModal(false)}
          onSuccess={() => { setShowAwbModal(false); loadCarrierShipment(); }}
        />
        );
      })()}
      {buyerEditOpen && (
        <ProformaBuyerEditModal
          fields={buyerEditFields}
          saving={buyerEditSaving}
          error={buyerEditError}
          onChange={(k, v) => setBuyerEditFields(prev => ({ ...prev, [k]: v }))}
          onSave={handleBuyerEditSave}
          onClose={() => { setBuyerEditOpen(false); setBuyerEditError(null); }}
        />
      )}

      {customerPickOpen && (
        <ProformaCustomerPickerModal
          title="Change Customer (bill-to)"
          current={{
            name: (customer && customer.name) || liveDraft.client_name || '—',
            contractor_id: liveDraft.client_contractor_id || '—',
            vat: (liveDraft.buyer_override && liveDraft.buyer_override.vat_id) || (customer && customer.vat) || '—',
            currency: liveDraft.currency || '—',
            payment_days: (liveDraft.payment_terms && liveDraft.payment_terms.days != null) ? String(liveDraft.payment_terms.days) : '—',
            language: '—',
          }}
          busy={customerPickBusy}
          error={customerPickError}
          onConfirm={handleChangeCustomer}
          onClose={() => { setCustomerPickOpen(false); setCustomerPickError(null); }}
        />
      )}

      {recipientPickOpen && (
        <ProformaCustomerPickerModal
          title="Change Recipient (ship-to)"
          current={{
            name: (shipTo && shipTo.name) || '—',
            contractor_id: '—',
            vat: '—',
            currency: liveDraft.currency || '—',
            payment_days: '—',
            language: '—',
          }}
          busy={customerPickBusy}
          error={customerPickError}
          onConfirm={handleChangeRecipient}
          onClose={() => { setRecipientPickOpen(false); setCustomerPickError(null); }}
        />
      )}
    </div>
  );
}

// ── PR B — Service charges panel ────────────────────────────────────────────
function ServiceChargesPanel({ charges, canEdit, draftState, draftCurrency, serviceProducts, onLoadServiceProducts, suggestion, chargesLoading, chargesApplying, onFetchSuggestions, onApplyCharge, onAddCharge, onUpdateCharge, onDismissSuggestion, onDeleteCharge }) {
  const fmtAmt = (amt, cur) => `${Number(amt).toFixed(2)} ${cur || ''}`;
  const existingTypes = (charges || []).map(c => (c.charge_type || '').toLowerCase());
  // Slice-2: both freight and insurance are already on the draft — CM preview
  // is still available (Lesson M: no capability removal) but labelled advisory.
  const allTypesApplied = existingTypes.includes('freight') && existingTypes.includes('insurance');

  // PR-3 — manual add / in-place edit state.
  const [addType, setAddType] = React.useState(null);        // 'freight'|'insurance'|null
  const [addForm, setAddForm] = React.useState({});
  const [addBusy, setAddBusy] = React.useState(false);
  const [addErr,  setAddErr]  = React.useState(null);
  const [editId,  setEditId]  = React.useState(null);        // charge_id being edited
  const [editForm, setEditForm] = React.useState({});
  const [editBusy, setEditBusy] = React.useState(false);
  const [editErr,  setEditErr]  = React.useState(null);

  const iBtn = { fontSize: 11, padding: '2px 9px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer', color: 'var(--text-2)' };
  const iIn  = { fontSize: 12, padding: '3px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' };
  const svcOptions = (type) => (serviceProducts || [])
    .filter(p => (p.charge_type || '').toLowerCase() === type);

  const openAdd = (type) => {
    if (onLoadServiceProducts) onLoadServiceProducts();
    setAddType(type); setAddErr(null);
    setAddForm({ amount: '', currency: draftCurrency || 'EUR', wfirma_service_id: '', rate_pct: '', label: '' });
  };
  const submitAdd = () => {
    const amt = parseFloat(addForm.amount);
    if (isNaN(amt) || amt < 0) { setAddErr('Enter a valid amount (>= 0).'); return; }
    const charge = {
      charge_type: addType, amount: amt,
      currency: (addForm.currency || draftCurrency || 'EUR').toUpperCase(),
      label: (addForm.label || '').trim(),
      wfirma_service_id: (addForm.wfirma_service_id || '').trim() || null,
    };
    if (addType === 'insurance' && String(addForm.rate_pct).trim() !== '') {
      const r = parseFloat(addForm.rate_pct);
      if (!isNaN(r)) charge.formula_basis = { rate_pct: r };
    }
    setAddBusy(true); setAddErr(null);
    Promise.resolve(onAddCharge && onAddCharge(charge))
      .then(() => { setAddBusy(false); setAddType(null); })
      .catch(e => { setAddBusy(false); setAddErr((e && e.message) || 'Add failed'); });
  };
  const openEdit = (c) => {
    if (onLoadServiceProducts) onLoadServiceProducts();
    setEditId(c.charge_id); setEditErr(null);
    setEditForm({
      amount: String(c.amount != null ? c.amount : ''),
      wfirma_service_id: c.wfirma_service_id || '',
      rate_pct: (c.formula_basis && c.formula_basis.rate_pct != null) ? String(c.formula_basis.rate_pct) : '',
      label: c.label || '',
    });
  };
  const submitEdit = (c) => {
    const updates = {};
    const amt = parseFloat(editForm.amount);
    if (!isNaN(amt) && amt !== Number(c.amount)) updates.amount = amt;
    if ((editForm.wfirma_service_id || '') !== (c.wfirma_service_id || '')) updates.wfirma_service_id = (editForm.wfirma_service_id || '').trim() || null;
    if ((editForm.label || '') !== (c.label || '')) updates.label = (editForm.label || '').trim();
    const curRate = (c.formula_basis && c.formula_basis.rate_pct != null) ? String(c.formula_basis.rate_pct) : '';
    if (c.charge_type === 'insurance' && (editForm.rate_pct || '') !== curRate) {
      updates.rate_pct = String(editForm.rate_pct).trim() === '' ? null : parseFloat(editForm.rate_pct);
    }
    if (Object.keys(updates).length === 0) { setEditId(null); return; }
    setEditBusy(true); setEditErr(null);
    Promise.resolve(onUpdateCharge && onUpdateCharge(c.charge_id, updates))
      .then(() => { setEditBusy(false); setEditId(null); })
      .catch(e => { setEditBusy(false); setEditErr((e && e.message) || 'Update failed'); });
  };

  return (
    <div data-testid="service-charges-panel" style={{ marginTop: 24, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Service Charges</span>
        {canEdit && (
          /* Slice-2: relabelled to make CM read-only advisory status unmistakable.
             The draft's service_charges_json is the authority; this is a preview. */
          <button
            data-testid="btn-suggest-charges"
            disabled={chargesLoading}
            title="Advisory read-only preview from Customer Master — the saved draft lines are authoritative"
            onClick={onFetchSuggestions}
            style={{
              fontSize: 12, padding: '2px 10px',
              background: 'var(--bg)', border: '1px solid var(--border)',
              borderRadius: 4, cursor: chargesLoading ? 'wait' : 'pointer',
              color: 'var(--text-2)',
            }}
          >{chargesLoading ? '⏳ Loading…' : '↓ Preview freight/insurance from Customer Master'}</button>
        )}
        {canEdit && allTypesApplied && (
          <span data-testid="charges-all-applied-note"
                style={{ fontSize: 11, color: 'var(--text-3)', fontStyle: 'italic' }}>
            (both already applied from draft)
          </span>
        )}
        {!canEdit && (
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
            (read-only — draft is in '{draftState}' state)
          </span>
        )}
        {canEdit && !existingTypes.includes('freight') && (
          <button data-testid="btn-add-freight" onClick={() => openAdd('freight')} style={iBtn}>+ Add freight</button>
        )}
        {canEdit && !existingTypes.includes('insurance') && (
          <button data-testid="btn-add-insurance" onClick={() => openAdd('insurance')} style={iBtn}>+ Add insurance</button>
        )}
      </div>

      {/* Manual add form — writes via the canonical service-charge writer (POST /service-charges). */}
      {canEdit && addType && (
        <div data-testid={`charge-add-form-${addType}`} style={{ padding: '10px 12px', marginBottom: 8, background: 'var(--bg)', border: '1px solid var(--accent)', borderRadius: 6, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', width: 70 }}>{addType.charAt(0).toUpperCase() + addType.slice(1)}</span>
          <input data-testid="charge-add-amount" type="number" min="0" step="0.01" placeholder="amount" value={addForm.amount} onChange={e => setAddForm(p => ({ ...p, amount: e.target.value }))} style={{ ...iIn, width: 90 }} />
          <input data-testid="charge-add-currency" placeholder="cur" value={addForm.currency} onChange={e => setAddForm(p => ({ ...p, currency: e.target.value }))} style={{ ...iIn, width: 56 }} />
          <select data-testid="charge-add-service-product" value={addForm.wfirma_service_id} onChange={e => setAddForm(p => ({ ...p, wfirma_service_id: e.target.value }))} style={{ ...iIn, minWidth: 150 }}>
            <option value="">— wFirma service product —</option>
            {svcOptions(addType).map(p => <option key={p.wfirma_product_id || p.charge_type} value={p.wfirma_product_id || ''}>{(p.wfirma_product_id ? p.wfirma_product_id + ' · ' : '') + (p.product_name || p.charge_type)}</option>)}
          </select>
          {addType === 'insurance' && (
            <input data-testid="charge-add-rate" type="number" min="0" step="0.01" placeholder="rate %" value={addForm.rate_pct} onChange={e => setAddForm(p => ({ ...p, rate_pct: e.target.value }))} style={{ ...iIn, width: 70 }} />
          )}
          <input data-testid="charge-add-label" placeholder="label (optional)" value={addForm.label} onChange={e => setAddForm(p => ({ ...p, label: e.target.value }))} style={{ ...iIn, width: 130 }} />
          <button data-testid="charge-add-save" onClick={submitAdd} disabled={addBusy} style={{ ...iBtn, background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)', opacity: addBusy ? 0.6 : 1 }}>{addBusy ? 'Adding…' : 'Add'}</button>
          <button data-testid="charge-add-cancel" onClick={() => setAddType(null)} disabled={addBusy} style={iBtn}>Cancel</button>
          {addErr && <span data-testid="charge-add-error" style={{ fontSize: 11, color: 'var(--badge-red-text)', width: '100%' }}>{addErr}</span>}
        </div>
      )}

      {/* Existing charges — DRAFT AUTHORITY (service_charges_json on the saved draft) */}
      {charges.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>No service charges added.</div>
      )}
      {charges.map(c => {
        const isEdit = editId === c.charge_id;
        const fb = c.formula_basis || {};
        const basis = (fb.sales_total != null ? Number(fb.sales_total) : null);
        return (
        <React.Fragment key={c.charge_id}>
        <div data-testid={`charge-row-${c.charge_type}`} style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 10px', marginBottom: 4,
          background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6,
        }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', width: 80 }}>
            {(c.charge_type || '').charAt(0).toUpperCase() + (c.charge_type || '').slice(1)}
          </span>
          <span style={{ fontSize: 13, color: 'var(--text)', flex: 1 }}>
            {fmtAmt(c.amount, c.currency)}
          </span>
          {c.label && (
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{c.label}</span>
          )}
          {/* Slice-2: expose mapping-layer fields so the operator can see which
              wFirma service ID and (insurance) rate are stored on the draft line. */}
          {c.wfirma_service_id && (
            <span data-testid={`charge-svc-id-${c.charge_type}`}
                  title="wFirma service-product ID stored on this draft charge line"
                  style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'monospace' }}>
              svc:{c.wfirma_service_id}
            </span>
          )}
          {/* Insurance rate (%) stored on the draft charge (Lesson M: keep visible). */}
          {c.formula_basis && c.formula_basis.rate_pct != null && (
            <span data-testid={`charge-rate-pct-${c.charge_type}`}
                  title="Insurance rate (%) stored on this draft charge"
                  style={{ fontSize: 10, color: 'var(--text-3)' }}>
              rate:{c.formula_basis.rate_pct}%
            </span>
          )}
          {/* Insurance premium provenance: basis × rate = premium (the stored amount). */}
          {c.charge_type === 'insurance' && fb.rate_pct != null && (
            <span data-testid={`charge-premium-${c.charge_type}`}
                  title="Insurance premium = basis × rate (the stored amount is the premium)"
                  style={{ fontSize: 10, color: 'var(--text-3)' }}>
              {basis != null ? `${basis.toFixed(2)} × ${fb.rate_pct}% = ${Number(c.amount).toFixed(2)}` : `= premium ${Number(c.amount).toFixed(2)}`}
            </span>
          )}
          {canEdit && !isEdit && (
            <button data-testid={`btn-edit-charge-${c.charge_type}`}
                    title={`Edit ${c.charge_type} charge`}
                    onClick={() => openEdit(c)} style={iBtn}>Edit</button>
          )}
          {canEdit && (
            <button
              data-testid={`btn-delete-charge-${c.charge_type}`}
              title={`Remove ${c.charge_type} charge`}
              onClick={() => onDeleteCharge && onDeleteCharge(c.charge_id)}
              style={{
                fontSize: 11, padding: '1px 7px',
                background: 'none', border: '1px solid var(--border)',
                borderRadius: 4, cursor: 'pointer', color: 'var(--text-2)',
              }}
            >✕</button>
          )}
        </div>
        {canEdit && isEdit && (
          <div data-testid={`charge-edit-form-${c.charge_type}`} style={{ padding: '10px 12px', marginBottom: 6, background: 'var(--bg)', border: '1px solid var(--accent)', borderRadius: 6, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)', width: 70 }}>Edit {c.charge_type}</span>
            <input data-testid="charge-edit-amount" type="number" min="0" step="0.01" value={editForm.amount} onChange={e => setEditForm(p => ({ ...p, amount: e.target.value }))} style={{ ...iIn, width: 90 }} />
            <select data-testid="charge-edit-service-product" value={editForm.wfirma_service_id} onChange={e => setEditForm(p => ({ ...p, wfirma_service_id: e.target.value }))} style={{ ...iIn, minWidth: 150 }}>
              <option value="">— wFirma service product —</option>
              {svcOptions(c.charge_type).map(p => <option key={p.wfirma_product_id || p.charge_type} value={p.wfirma_product_id || ''}>{(p.wfirma_product_id ? p.wfirma_product_id + ' · ' : '') + (p.product_name || p.charge_type)}</option>)}
            </select>
            {c.charge_type === 'insurance' && (
              <input data-testid="charge-edit-rate" type="number" min="0" step="0.01" placeholder="rate %" value={editForm.rate_pct} onChange={e => setEditForm(p => ({ ...p, rate_pct: e.target.value }))} style={{ ...iIn, width: 70 }} />
            )}
            <input data-testid="charge-edit-label" placeholder="label" value={editForm.label} onChange={e => setEditForm(p => ({ ...p, label: e.target.value }))} style={{ ...iIn, width: 130 }} />
            <button data-testid="charge-edit-save" onClick={() => submitEdit(c)} disabled={editBusy} style={{ ...iBtn, background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)', opacity: editBusy ? 0.6 : 1 }}>{editBusy ? 'Saving…' : 'Save'}</button>
            <button data-testid="charge-edit-cancel" onClick={() => setEditId(null)} disabled={editBusy} style={iBtn}>Cancel</button>
            {editErr && <span data-testid="charge-edit-error" style={{ fontSize: 11, color: 'var(--badge-red-text)', width: '100%' }}>{editErr}</span>}
          </div>
        )}
        </React.Fragment>
        );
      })}

      {/* Suggestion panel — ADVISORY ONLY (live CM re-read, not the draft authority).
          Slice-2: header explicitly labels this as advisory. The Apply button is
          suppressed when the charge type already exists on the draft (alreadyApplied
          check below) — prevents a 400 dup-guard hit on POST /service-charges. */}
      {suggestion && !suggestion.error && (
        <div data-testid="charge-suggestion-panel" style={{
          marginTop: 8, padding: '10px 12px',
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 6,
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-2)' }}>
            Advisory preview (Customer Master, {suggestion.draft_currency || '—'}) — read-only:
          </div>
          {suggestion.applyError && (
            <div data-testid="charge-apply-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 6 }}>
              {suggestion.applyError}
            </div>
          )}
          {['freight', 'insurance'].map(type => {
            const s = suggestion[type] || {};
            const alreadyApplied = s.already_applied || existingTypes.includes(type);
            const blocked = !s.available || s.blocked_reason;
            return (
              <div key={type} data-testid={`suggestion-row-${type}`} style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4,
              }}>
                <span style={{ width: 70, fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
                  {type.charAt(0).toUpperCase() + type.slice(1)}
                </span>
                {blocked ? (
                  (() => {
                    // Customer Master is the single freight authority. When the
                    // record WAS resolved but is missing a freight field, deep-link
                    // straight to that exact record's edit view + offer Retry —
                    // no draft-level override, no guessed fallback. (freight_authority
                    // is freight-only; absent/unresolved → reason text only.)
                    const fa = s.freight_authority;
                    const canRepair = fa && fa.resolved && fa.edit_url;
                    return (
                      <span data-testid={`suggestion-blocked-${type}`}
                            style={{ fontSize: 12, color: 'var(--text-2)', display: 'flex',
                                     flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                        <span>{s.blocked_reason || 'Not available'}</span>
                        {canRepair && (
                          <React.Fragment>
                            <a data-testid={`freight-authority-edit-${type}`}
                               href={fa.edit_url} target="_blank" rel="noopener"
                               title={`Edit freight authority on Customer Master record ${fa.contractor_id}`}
                               style={{ color: 'var(--accent)', fontWeight: 600 }}>
                              Edit {fa.bill_to_name || 'Customer Master'} ({fa.contractor_id}) →
                            </a>
                            {canEdit && (
                              <button data-testid={`freight-authority-retry-${type}`}
                                      disabled={chargesLoading}
                                      title="Re-check Customer Master after setting the freight amount"
                                      onClick={onFetchSuggestions}
                                      style={{ fontSize: 11, padding: '1px 8px', background: 'none',
                                               border: '1px solid var(--border)', borderRadius: 4,
                                               cursor: chargesLoading ? 'wait' : 'pointer',
                                               color: 'var(--text-2)' }}>
                                ↻ Retry
                              </button>
                            )}
                          </React.Fragment>
                        )}
                      </span>
                    );
                  })()
                ) : alreadyApplied ? (
                  <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
                    Already applied ({fmtAmt(s.amount, s.currency)})
                  </span>
                ) : (
                  <React.Fragment>
                    <span style={{ fontSize: 12, color: 'var(--text)' }}>
                      {fmtAmt(s.amount, s.currency)}
                      {s.label ? ` — ${s.label}` : ''}
                    </span>
                    {canEdit && (
                      <button
                        data-testid={`btn-apply-charge-${type}`}
                        disabled={!!chargesApplying}
                        title={`Add ${type} charge to this draft`}
                        onClick={() => onApplyCharge(type)}
                        style={{
                          fontSize: 12, padding: '2px 10px',
                          background: 'var(--accent)', color: '#fff',
                          border: 'none', borderRadius: 4,
                          cursor: chargesApplying ? 'wait' : 'pointer',
                          opacity: chargesApplying ? 0.6 : 1,
                        }}
                      >{chargesApplying === type ? '⏳' : `Apply ${type.charAt(0).toUpperCase() + type.slice(1)}`}</button>
                    )}
                  </React.Fragment>
                )}
              </div>
            );
          })}
          <button
            data-testid="btn-close-suggestions"
            onClick={() => onDismissSuggestion && onDismissSuggestion()}
            style={{
              fontSize: 11, padding: '1px 7px', marginTop: 4,
              background: 'none', border: '1px solid var(--border)',
              borderRadius: 4, cursor: 'pointer', color: 'var(--text-2)',
            }}
          >✕ Dismiss</button>
        </div>
      )}
      {suggestion && suggestion.error && (
        <div data-testid="charge-suggestion-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginTop: 6 }}>
          {suggestion.error}
        </div>
      )}
    </div>
  );
}

// ── PL-5 — Service Product Registry Panel ────────────────────────────────────
// Gap PL-5: getServiceProducts (pz-api.js:134, backend live at
// GET /api/v1/proforma/service-products) was never called by any V2 JSX page.
//
// This panel shows the freight/insurance charge-type → wFirma product mappings.
// Authority: GET /api/v1/proforma/service-products (read) +
//            PUT /api/v1/proforma/service-products/{charge_type} (register)
// Placed in ProformaOverviewTab below ServiceChargesPanel when
// canEdit === true (editing state only).
function ServiceProductRegistryPanel() {
  const { useState, useEffect } = React;
  const [products, setProducts]     = useState(null);
  const [loading, setLoading]       = useState(true);
  // Slice-2: distinguish genuine-empty from load-failure so "No mappings
  // registered" only appears when the GET returned ok:true with an empty set,
  // not when the call failed (network error, 500, auth, etc.).
  const [loadFailed, setLoadFailed] = useState(false);
  const [editing, setEditing]   = useState(null);  // charge_type being edited
  const [editVal, setEditVal]   = useState('');
  const [saving, setSaving]     = useState(false);
  const [saveErr, setSaveErr]   = useState(null);

  const load = () => {
    setLoading(true);
    setLoadFailed(false);
    window.PzApi.getServiceProducts()
      .then(r => {
        if (r && r.ok !== false) {
          setProducts(r.data || r);
          setLoadFailed(false);
        } else {
          // Server returned ok:false (auth error, 5xx, etc.) — not "genuinely empty"
          setProducts(null);
          setLoadFailed(true);
        }
        setLoading(false);
      })
      .catch(() => { setProducts(null); setLoadFailed(true); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const handleSave = (chargeType) => {
    if (!editVal.trim()) return;
    setSaving(true); setSaveErr(null);
    window.PzApi.putServiceProduct(chargeType, { wfirma_product_id: editVal.trim() })
      .then(r => {
        setSaving(false);
        if (r && r.ok !== false) { setEditing(null); setEditVal(''); load(); }
        else setSaveErr((r && r.error) || 'Save failed');
      })
      .catch(e => { setSaving(false); setSaveErr(e.message || String(e)); });
  };

  const rows = Array.isArray(products) ? products
    : (products && Array.isArray(products.mappings)) ? products.mappings
    : [];

  return (
    <div data-testid="service-product-registry-panel"
      style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>Service Charge → wFirma Product Registry</span>
        {loading && <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Loading…</span>}
      </div>
      {/* Slice-2: only show "no mappings" when the GET succeeded with genuinely
          zero rows. When loadFailed, show a distinct unavailable state instead. */}
      {!loading && loadFailed && (
        <div data-testid="service-product-registry-unavailable"
             style={{ fontSize: 11.5, color: 'var(--badge-red-text)', marginBottom: 8 }}>
          Mapping status unavailable — could not load the service-product registry.
        </div>
      )}
      {!loading && !loadFailed && rows.length === 0 && (
        <div data-testid="service-product-registry-empty"
             style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 8 }}>
          No mappings registered. Map a charge type to its wFirma product ID to enable automatic line creation on Post.
        </div>
      )}
      {rows.map(r => (
        <div key={r.charge_type} data-testid={`service-product-row-${r.charge_type}`}
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 10px', marginBottom: 4,
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6 }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text)', width: 80, textTransform: 'capitalize' }}>
            {r.charge_type}</span>
          {editing === r.charge_type ? (
            <>
              <input value={editVal} onChange={e => setEditVal(e.target.value)}
                placeholder="wFirma product ID"
                data-testid={`service-product-input-${r.charge_type}`}
                style={{ flex: 1, padding: '4px 8px', fontSize: 12, borderRadius: 4,
                  border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }}
              />
              {saveErr && <span style={{ fontSize: 11, color: 'var(--badge-red-text)' }}>{saveErr}</span>}
              <Btn variant="primary" small disabled={saving || !editVal.trim()}
                data-testid={`service-product-save-${r.charge_type}`}
                onClick={() => handleSave(r.charge_type)}>
                {saving ? '…' : '✓'}
              </Btn>
              <Btn variant="ghost" small onClick={() => { setEditing(null); setSaveErr(null); }}>✕</Btn>
            </>
          ) : (
            <>
              <span style={{ flex: 1, fontFamily: 'monospace', fontSize: 11, color: r.wfirma_product_id ? 'var(--text)' : 'var(--text-3)' }}>
                {r.wfirma_product_id || '(not mapped)'}
              </span>
              <Btn variant="ghost" small data-testid={`service-product-edit-${r.charge_type}`}
                onClick={() => { setEditing(r.charge_type); setEditVal(r.wfirma_product_id || ''); setSaveErr(null); }}>
                ✎
              </Btn>
            </>
          )}
        </div>
      ))}
      {/* Allow adding an unmapped type */}
      {!loading && (
        <div style={{ marginTop: 6 }}>
          {editing === '__new__' ? (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input value={editVal} onChange={e => setEditVal(e.target.value)}
                placeholder="freight  OR  insurance"
                data-testid="service-product-new-type"
                style={{ flex: 1, padding: '4px 8px', fontSize: 12, borderRadius: 4,
                  border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }}
              />
              {saveErr && <span style={{ fontSize: 11, color: 'var(--badge-red-text)' }}>{saveErr}</span>}
              <Btn variant="ghost" small onClick={() => { setEditing(null); setSaveErr(null); }}>✕</Btn>
            </div>
          ) : (
            <Btn variant="ghost" small data-testid="service-product-add-new"
              onClick={() => { setEditing('__new__'); setEditVal(''); setSaveErr(null); }}>
              + Add mapping
            </Btn>
          )}
        </div>
      )}
    </div>
  );
}

// ── PR B — Buyer edit modal ───────────────────────────────────────────────────
function ProformaBuyerEditModal({ fields, saving, error, onChange, onSave, onClose }) {
  const F = (label, key, placeholder) => (
    <div style={{ marginBottom: 10 }}>
      <label style={{ display: 'block', fontSize: 12, color: 'var(--text-2)', marginBottom: 3 }}>{label}</label>
      <input
        data-testid={`buyer-edit-${key}`}
        value={fields[key] || ''}
        onChange={e => onChange(key, e.target.value)}
        placeholder={placeholder || ''}
        style={{
          width: '100%', padding: '6px 8px', fontSize: 13,
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 4, color: 'var(--text)', boxSizing: 'border-box',
          fontFamily: 'inherit',
        }}
      />
    </div>
  );
  return (
    <div data-testid="buyer-edit-modal" style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1200,
    }}>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 10, padding: 24, width: 360, maxWidth: '90vw',
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 16 }}>Edit Bill-to Address</div>
        {F('Company name', 'name', 'e.g. UAB Tomas Gold')}
        {F('Street', 'street', 'e.g. Gedimino pr. 1')}
        {F('City', 'city', 'e.g. Vilnius')}
        {F('Postal code', 'zip', 'e.g. LT-01103')}
        {F('Country code', 'country', 'e.g. LT')}
        {F('VAT EU number', 'vat_id', 'e.g. LT123456789')}
        {error && (
          <div data-testid="buyer-edit-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 8 }}>
            {error}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            data-testid="btn-buyer-edit-cancel"
            onClick={onClose}
            disabled={saving}
            style={{
              padding: '6px 14px', fontSize: 13,
              background: 'var(--bg)', border: '1px solid var(--border)',
              borderRadius: 4, cursor: 'pointer', color: 'var(--text)',
              fontFamily: 'inherit',
            }}
          >Cancel</button>
          <button
            data-testid="btn-buyer-edit-save"
            onClick={onSave}
            disabled={saving}
            style={{
              padding: '6px 14px', fontSize: 13,
              background: 'var(--accent)', color: '#fff',
              border: 'none', borderRadius: 4,
              cursor: saving ? 'wait' : 'pointer',
              opacity: saving ? 0.7 : 1,
              fontFamily: 'inherit',
            }}
          >{saving ? '⏳ Saving…' : '✓ Save'}</button>
        </div>
      </div>
    </div>
  );
}

// ── Customer picker + confirmation diff (PR 1a) ───────────────────────────────
// ID-FIRST: the operator searches Customer Master by name / VAT / contractor id
// and picks an explicit contractor. Duplicate VAT surfaces BOTH contractors —
// nothing is auto-selected or merged. A confirmation diff (old → new) is shown
// before the replace is applied. The draft's line items / prices are untouched.
function ProformaCustomerPickerModal({ title, current, onConfirm, onClose, busy, error }) {
  const [q, setQ]           = React.useState('');
  const [results, setResults] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [searching, setSearching] = React.useState(false);

  React.useEffect(() => {
    const term = q.trim();
    if (term.length < 1) { setResults([]); return; }
    let alive = true;
    setSearching(true);
    const t = setTimeout(() => {
      window.PzApi.listCustomerMaster({ q: term, limit: 25 })
        .then(r => {
          if (!alive) return;
          const list = (r && r.customers) || (r && r.data && r.data.customers) || [];
          setResults(list);
        })
        .catch(() => { if (alive) setResults([]); })
        .finally(() => { if (alive) setSearching(false); });
    }, 220);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  // Same-VAT duplicate detection across the current result set (advisory only).
  const vatCounts = {};
  results.forEach(c => { const v = (c.vat_eu_number || c.nip || '').trim(); if (v) vatCounts[v] = (vatCounts[v] || 0) + 1; });

  const diffRows = selected ? [
    ['Customer name', current.name, selected.bill_to_name],
    ['Contractor ID', current.contractor_id, selected.bill_to_contractor_id],
    ['VAT', current.vat, selected.vat_eu_number || selected.nip || '—'],
    ['Currency', current.currency, selected.default_currency || '—'],
    ['Payment days', current.payment_days, (selected.payment_terms_days != null ? String(selected.payment_terms_days) : '—')],
    ['Invoice language', current.language, selected.default_language_id || '—'],
  ] : [];

  return (
    <div data-testid="customer-picker-modal" style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1200,
    }}>
      <div style={{
        background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
        padding: 22, width: 560, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto',
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }}>
          Search by name, VAT or contractor ID. Duplicate VAT shows every contractor — pick one; nothing is auto-selected.
        </div>
        <input
          data-testid="customer-picker-search"
          autoFocus
          value={q}
          onChange={e => { setQ(e.target.value); setSelected(null); }}
          placeholder="Search by name, VAT number, or contractor ID"
          style={{
            width: '100%', padding: '8px 10px', fontSize: 13, boxSizing: 'border-box',
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6,
            color: 'var(--text)', fontFamily: 'inherit', marginBottom: 10,
          }}
        />

        {!selected && (
          <div data-testid="customer-picker-results" style={{ maxHeight: 240, overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 6 }}>
            {searching && <div style={{ padding: 10, fontSize: 12, color: 'var(--text-3)' }}>Searching…</div>}
            {!searching && q.trim() && results.length === 0 && (
              <div style={{ padding: 10, fontSize: 12, color: 'var(--text-3)' }}>No customer matches “{q.trim()}”.</div>
            )}
            {results.map(c => {
              const v = (c.vat_eu_number || c.nip || '').trim();
              const dup = v && vatCounts[v] > 1;
              return (
                <button key={c.bill_to_contractor_id}
                  data-testid={`customer-picker-result-${c.bill_to_contractor_id}`}
                  onClick={() => setSelected(c)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                    padding: '8px 10px', border: 'none', borderBottom: '1px solid var(--border-subtle)',
                    background: 'var(--card)', color: 'var(--text)', fontFamily: 'inherit', fontSize: 12.5,
                  }}>
                  <div style={{ fontWeight: 600 }}>{c.bill_to_name}
                    {dup && <span data-testid={`customer-dup-flag-${c.bill_to_contractor_id}`} style={{ marginLeft: 8, fontSize: 10, fontWeight: 700, color: 'var(--badge-amber-text)', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 999, padding: '1px 6px' }}>⚠ duplicate VAT</span>}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'monospace' }}>
                    id {c.bill_to_contractor_id} · {v || 'no VAT'} · {c.country || ''}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {selected && (
          <div data-testid="customer-picker-diff">
            <div style={{ fontSize: 12, fontWeight: 700, margin: '4px 0 8px' }}>Confirm change — review before applying</div>
            <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 6 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                <div>Field</div><div>Current</div><div>New</div>
              </div>
              {diffRows.map(([label, oldV, newV]) => {
                const changed = String(oldV ?? '—') !== String(newV ?? '—');
                return (
                  <div key={label} data-testid={`customer-diff-row-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`}
                    style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--border-subtle)', fontSize: 12, alignItems: 'center' }}>
                    <div style={{ color: 'var(--text-2)' }}>{label}</div>
                    <div style={{ color: 'var(--text-3)' }}>{oldV ?? '—'}</div>
                    <div style={{ fontWeight: changed ? 700 : 400, color: changed ? 'var(--accent)' : 'var(--text)' }}>{newV ?? '—'}</div>
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 8 }}>
              Line items, prices and packing links are not changed. Service charges follow the customer.
            </div>
            <button data-testid="customer-picker-back" onClick={() => setSelected(null)} disabled={busy}
              style={{ marginTop: 8, fontSize: 12, padding: '3px 10px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer', color: 'var(--text)', fontFamily: 'inherit' }}>← Pick a different customer</button>
          </div>
        )}

        {error && (
          <div data-testid="customer-picker-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginTop: 10 }}>{error}</div>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button data-testid="customer-picker-cancel" onClick={onClose} disabled={busy}
            style={{ padding: '6px 14px', fontSize: 13, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer', color: 'var(--text)', fontFamily: 'inherit' }}>Cancel</button>
          <button data-testid="customer-picker-confirm" onClick={() => selected && onConfirm(selected)} disabled={busy || !selected}
            style={{ padding: '6px 14px', fontSize: 13, background: selected ? 'var(--accent)' : 'var(--bg)', color: selected ? '#fff' : 'var(--text-3)', border: selected ? 'none' : '1px solid var(--border)', borderRadius: 4, cursor: (busy || !selected) ? 'not-allowed' : 'pointer', opacity: busy ? 0.7 : 1, fontFamily: 'inherit' }}>{busy ? '⏳ Applying…' : '✓ Apply change'}</button>
        </div>
      </div>
    </div>
  );
}

// ── Editable field input ─────────────────────────────────────────────────────
function EditableKvItem({ k, value, onChange, type }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 3, fontWeight: 500 }}>{k}</div>
      {type === 'textarea' ? (
        <textarea
          value={value}
          onChange={e => onChange(e.target.value)}
          data-testid={`edit-field-${k.toLowerCase().replace(/\s+/g, '-')}`}
          style={{
            width: '100%', minHeight: 60, padding: '6px 8px',
            border: '2px solid var(--accent)', borderRadius: 6,
            background: 'var(--bg)', color: 'var(--text)',
            fontFamily: 'inherit', fontSize: 13, resize: 'vertical',
          }}
        />
      ) : (
        <input
          type={type || 'text'}
          value={value}
          onChange={e => onChange(e.target.value)}
          data-testid={`edit-field-${k.toLowerCase().replace(/\s+/g, '-')}`}
          style={{
            width: '100%', padding: '6px 8px',
            border: '2px solid var(--accent)', borderRadius: 6,
            background: 'var(--bg)', color: 'var(--text)',
            fontFamily: 'inherit', fontSize: 13, fontWeight: 700,
          }}
        />
      )}
    </div>
  );
}

// ── Customer Master suggestions (Slice 1) ─────────────────────────────────────
// Read-only advisory projection of the mapped Customer Master commercial
// defaults. Every value is labelled by SOURCE — nothing here is applied to the
// draft automatically. The draft stays the transaction snapshot.
const CM_SRC_BADGE = {
  saved:     { label: 'Saved on draft',                 bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  suggested: { label: 'Suggested from Customer Master',  bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  conflict:  { label: 'Conflict',                        bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
  advisory:  { label: 'Advisory — VAT resolved at posting', bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  missing:   { label: 'Missing',                         bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
};

function CmSourceBadge({ source }) {
  const s = CM_SRC_BADGE[source] || CM_SRC_BADGE.missing;
  return (
    <span data-testid={`cm-src-${source}`} style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 999,
      fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap',
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
    }}>{s.label}</span>
  );
}

function CmValue({ v }) {
  const empty = v === null || v === undefined || v === '';
  return (
    <span style={{ fontSize: 12, fontWeight: 600, color: empty ? 'var(--text-3)' : 'var(--text)' }}>
      {empty ? '—' : String(v)}
    </span>
  );
}

// Map: suggestion field key → apply-commercial field key.
// Only keys present here get a checkbox. Fields absent from this map
// (customer_name, contractor_id, currency, insurance_amount) are
// displayed read-only — they are not commercial defaults this slice applies.
const _CM_APPLY_KEY_MAP = {
  payment_method:     'payment_method',
  payment_days:       'payment_terms_days',
  invoice_language:   'invoice_language_id',
  vat_wdt:            'vat_mode',
  freight_amount:     'freight_amount',
  freight_service_id: 'freight_service_id',
  insurance_rate:     'insurance_rate',
  insurance_service_id: 'insurance_service_id',
};

// ── Operator-set commercial terms (controlled wFirma-backed dropdowns) ─────────
// LAYER 2 of 3 (see the section note above the panels): the SAVED draft value,
// chosen by the operator from controlled dropdowns sourced from the wFirma-backed
// dictionary (GET /customer-master/dictionaries). Distinct from Customer Master
// DEFAULTS (layer 1, apply-from-CM) and the wFirma service-product REGISTRY
// (layer 3). Persists via POST /set-commercial-defaults — validated server-side
// (invalid enum/id → field-level 422). The dictionary is fetched lazily on Edit,
// never on page open, and it is a cached config read (no live wFirma product query).
function CommercialTermsEditor({ draftId, liveDraft, updatedAt, onReload }) {
  const [open, setOpen] = React.useState(false);
  const [dicts, setDicts] = React.useState(null);
  const [form, setForm] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const [msg, setMsg] = React.useState(null);

  const pt = (liveDraft && liveDraft.payment_terms) || {};
  const curPayment = pt.method || '';
  const curDays    = (pt.days != null ? String(pt.days) : '');
  const curLang    = pt.invoice_language_id || '';
  const curVat     = liveDraft.vat_code || '';

  // Payment methods come from the single dictionary authority (get_dictionaries
  // now serves payment_methods, federated by CommercialLookupService). Static
  // fallback covers the pre-load render only.
  const PAY_METHODS = (dicts && dicts.payment_methods && dicts.payment_methods.length)
    ? dicts.payment_methods
    : [
        { id: 'transfer', label: 'Bank transfer' },
        { id: 'cash', label: 'Cash' },
        { id: 'card', label: 'Card' },
        { id: 'compensation', label: 'Compensation' },
      ];
  const vatModes  = (dicts && dicts.vat_modes) || [];
  const languages = (dicts && dicts.languages) || [];
  const _label = (list, id) => {
    const m = (list || []).find(x => String(x.id) === String(id));
    return m ? m.label : null;
  };
  const payLabel  = (id) => (_label(PAY_METHODS, id) || (id || '—'));
  const langLabel = (id) => (dicts ? (_label(languages, id) || (id === '' ? 'Default' : id)) : (id || '—'));
  const vatLabel  = (id) => (dicts ? (_label(vatModes, id) || (id || '—')) : (id || '—'));

  const loadDicts = () => {
    if (dicts) return;
    window.PzApi.getCustomerDictionaries()
      .then(r => setDicts((r && r.data) || r || {}))
      .catch(() => setDicts({}));
  };
  const startEdit = () => {
    loadDicts();
    setForm({ payment_method: curPayment, payment_terms_days: curDays,
              invoice_language_id: curLang, vat_mode: curVat });
    setErr(null); setMsg(null); setOpen(true);
  };
  const setField = (k, v) => setForm(p => ({ ...(p || {}), [k]: v }));

  const save = () => {
    if (!form) return;
    const fields = {};
    if (form.payment_method !== curPayment) fields.payment_method = form.payment_method;
    if (form.payment_terms_days !== curDays) {
      const d = parseInt(form.payment_terms_days, 10);
      if (!isNaN(d)) fields.payment_terms_days = d;
    }
    if (form.invoice_language_id !== curLang) fields.invoice_language_id = form.invoice_language_id;
    if (form.vat_mode !== curVat && form.vat_mode) fields.vat_mode = form.vat_mode;
    if (Object.keys(fields).length === 0) { setOpen(false); return; }
    setBusy(true); setErr(null); setMsg(null);
    window.PzApi.setCommercialDefaults(draftId, fields, updatedAt)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && r.error) || 'Save rejected');
        setBusy(false); setOpen(false); setMsg('Commercial terms updated');
        if (onReload) onReload();
      })
      .catch(e => { setBusy(false); setErr((e && e.message) || 'Save failed'); });
  };

  const box = { padding: '12px 14px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8, marginTop: 12 };
  const sel = { padding: '4px 6px', fontSize: 12, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', minWidth: 150 };
  const btn = { padding: '3px 10px', fontSize: 12, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', cursor: 'pointer' };
  const row = { display: 'flex', alignItems: 'center', gap: 10, margin: '6px 0', flexWrap: 'wrap' };
  const lab = { width: 130, fontSize: 12, color: 'var(--text-2)' };

  return (
    <div data-testid="pf-commercial-terms" style={box}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Commercial terms (draft)</span>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>· operator-set · controlled wFirma values</span>
        <div style={{ flex: 1 }} />
        {!open && (
          <button data-testid="pf-commercial-edit" onClick={startEdit} style={btn}>Edit</button>
        )}
      </div>

      {!open ? (
        <div style={{ fontSize: 12, color: 'var(--text)' }}>
          <div style={row}><span style={lab}>Payment method</span><span data-testid="pf-ct-payment">{curPayment ? `${curPayment} · ${payLabel(curPayment)}` : '—'}</span></div>
          <div style={row}><span style={lab}>Payment terms</span><span data-testid="pf-ct-days">{curDays !== '' ? `${curDays} days` : '—'}</span></div>
          <div style={row}><span style={lab}>Invoice language</span><span data-testid="pf-ct-lang">{curLang ? `${curLang} · ${langLabel(curLang)}` : '—'}</span></div>
          <div style={row}><span style={lab}>VAT / WDT</span><span data-testid="pf-ct-vat">{curVat ? `${curVat}${vatLabel(curVat) && vatLabel(curVat) !== curVat ? ' · ' + vatLabel(curVat) : ''}` : '—'}</span></div>
          {msg && <div data-testid="pf-ct-msg" style={{ fontSize: 11, color: 'var(--badge-green-text)', marginTop: 4 }}>{msg}</div>}
        </div>
      ) : (
        <div style={{ fontSize: 12 }}>
          <div style={row}>
            <span style={lab}>Payment method</span>
            <select data-testid="pf-ct-payment-select" value={form.payment_method} onChange={e => setField('payment_method', e.target.value)} style={sel}>
              <option value="">— select —</option>
              {PAY_METHODS.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </div>
          <div style={row}>
            <span style={lab}>Payment terms (days)</span>
            <input data-testid="pf-ct-days-input" type="number" min="0" step="1" value={form.payment_terms_days} onChange={e => setField('payment_terms_days', e.target.value)} style={{ ...sel, minWidth: 80 }} />
          </div>
          <div style={row}>
            <span style={lab}>Invoice language</span>
            <select data-testid="pf-ct-lang-select" value={form.invoice_language_id} onChange={e => setField('invoice_language_id', e.target.value)} style={sel}>
              {(languages.length ? languages : [{ id: '', label: '— Default —' }]).map(o => <option key={o.id} value={o.id}>{o.id ? `${o.id} · ${o.label}` : o.label}</option>)}
            </select>
          </div>
          <div style={row}>
            <span style={lab}>VAT / WDT</span>
            <select data-testid="pf-ct-vat-select" value={form.vat_mode} onChange={e => setField('vat_mode', e.target.value)} style={sel}>
              <option value="">— select —</option>
              {vatModes.map(o => <option key={o.id} value={String(o.id)}>{o.id} · {o.label}</option>)}
            </select>
          </div>
          {err && <div data-testid="pf-ct-err" style={{ fontSize: 11, color: 'var(--badge-red-text)', margin: '4px 0' }}>{err}</div>}
          <div style={{ ...row, marginTop: 8 }}>
            <button data-testid="pf-ct-save" onClick={save} disabled={busy} style={{ ...btn, background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)', opacity: busy ? 0.6 : 1 }}>{busy ? 'Saving…' : 'Save terms'}</button>
            <button data-testid="pf-ct-cancel" onClick={() => setOpen(false)} disabled={busy} style={btn}>Cancel</button>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Only valid wFirma values are accepted (invalid → rejected).</span>
          </div>
        </div>
      )}
    </div>
  );
}

function CustomerMasterSuggestions({ suggestions, draftId, updatedAt, onReload }) {
  const sug = suggestions || null;
  const mapped = sug && sug.status === 'mapped';
  const conflict = mapped ? sug.identity_conflict : null;

  // Build initial checked state: suggested = checked, conflict = unchecked.
  const _initialChecked = () => {
    const state = {};
    if (!mapped) return state;
    (sug.fields || []).forEach(f => {
      const applyKey = _CM_APPLY_KEY_MAP[f.key];
      if (!applyKey) return;                         // not applicable
      if (f.applicable === false) return;            // advisory-only (e.g. derived VAT hint) — never selectable/submitted
      if (f.source === 'suggested') state[applyKey] = true;
      if (f.source === 'conflict')  state[applyKey] = false;
    });
    return state;
  };

  const [checked, setChecked] = React.useState(_initialChecked);
  const [applying, setApplying] = React.useState(false);
  const [applyError, setApplyError] = React.useState(null);
  const [applySuccess, setApplySuccess] = React.useState(false);

  // Re-init checkboxes when suggestions change (e.g. after reload)
  React.useEffect(() => {
    setChecked(_initialChecked());
    setApplyError(null);
    setApplySuccess(false);
  }, [sug && sug.mapped_contractor_id, updatedAt]);

  const checkedKeys = Object.keys(checked).filter(k => checked[k]);
  const canApply = mapped && checkedKeys.length > 0 && !applying;

  const handleToggle = (applyKey) => {
    setChecked(prev => ({ ...prev, [applyKey]: !prev[applyKey] }));
    setApplyError(null);
    setApplySuccess(false);
  };

  const handleApply = () => {
    if (!canApply) return;
    setApplying(true);
    setApplyError(null);
    setApplySuccess(false);
    window.PzApi.applyCustomerCommercial(draftId, checkedKeys, updatedAt || '')
      .then(r => {
        if (r && r.ok) {
          setApplySuccess(true);
          onReload && onReload();
        } else {
          const detail = (r && (r.detail || r.error)) || 'Apply failed.';
          if (typeof detail === 'string' && detail.toLowerCase().includes('conflict')) {
            setApplyError('Draft was changed by another action — reload the page and retry.');
          } else if (typeof detail === 'string' && detail.toLowerCase().includes('not found')) {
            setApplyError('Customer Master record not found — check the customer mapping.');
          } else {
            setApplyError(typeof detail === 'string' ? detail : 'Apply failed — check backend logs.');
          }
        }
      })
      .catch(e => {
        const msg = (e && e.message) || 'Network error';
        if (msg.toLowerCase().includes('409') || msg.toLowerCase().includes('conflict')) {
          setApplyError('Draft was changed by another action — reload the page and retry.');
        } else {
          setApplyError(msg);
        }
      })
      .finally(() => setApplying(false));
  };

  return (
    <div data-testid="cm-suggestions-section">
      <PfSectionLabel>Customer Master — commercial defaults</PfSectionLabel>
      <PfPanelCard>
        <div style={{ padding: '8px 20px 14px' }}>
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>
            Advisory only — read from Customer Master. Check the fields you want to copy to the draft, then click <strong>Apply Selected Suggestions</strong>. Nothing is applied automatically.
          </div>

          {conflict && (
            <div data-testid="cm-identity-conflict" style={{
              padding: '10px 12px', marginBottom: 12, borderRadius: 6,
              background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)',
            }}>
              <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-amber-text)', marginBottom: 4 }}>
                ⚠ Duplicate customer identity — not auto-merged
              </div>
              <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginBottom: 6 }}>
                Same VAT number <strong style={{ fontFamily: 'monospace' }}>{conflict.vat_number}</strong> is registered under multiple wFirma contractor IDs. Resolve in Customer Master.
              </div>
              {(conflict.contractors || []).map(c => (
                <div key={c.contractor_id}
                     data-testid={`cm-conflict-contractor-${c.contractor_id}`}
                     style={{ fontSize: 11, color: 'var(--badge-amber-text)' }}>
                  • contractor <strong style={{ fontFamily: 'monospace' }}>{c.contractor_id}</strong>
                  {c.contractor_id === conflict.mapped_contractor_id ? ' (mapped on this draft)' : ''} — {c.name}
                </div>
              ))}
            </div>
          )}

          {!mapped ? (
            <div data-testid="cm-suggestions-unmapped" style={{ fontSize: 12, color: 'var(--text-2)' }}>
              No mapped Customer Master record for this draft{sug && sug.reason ? ` (${sug.reason})` : ''}.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* header */}
              <div style={{
                display: 'grid', gridTemplateColumns: '24px 1.2fr 1fr 1fr auto',
                gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
                fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
                textTransform: 'uppercase', letterSpacing: '0.08em',
              }}>
                <div></div>
                <div>Field</div><div>Saved on draft</div><div>Customer Master</div><div>Source</div>
              </div>
              {(sug.fields || []).map(f => {
                const applyKey = _CM_APPLY_KEY_MAP[f.key];
                const applicable = !!applyKey && f.applicable !== false && (f.source === 'suggested' || f.source === 'conflict');
                const isSaved    = f.source === 'saved';
                return (
                  <div key={f.key}
                       data-testid={`cm-field-${f.key}`}
                       style={{
                         display: 'grid', gridTemplateColumns: '24px 1.2fr 1fr 1fr auto',
                         gap: 10, alignItems: 'center', padding: '6px 0',
                         borderBottom: '1px solid var(--border-subtle)',
                         opacity: (!applyKey && !isSaved) ? 0.6 : 1,
                       }}>
                    {/* Checkbox column */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {applicable ? (
                        <input
                          type="checkbox"
                          data-testid={`cm-check-${applyKey}`}
                          checked={!!checked[applyKey]}
                          onChange={() => handleToggle(applyKey)}
                          disabled={applying}
                          style={{ cursor: applying ? 'not-allowed' : 'pointer', accentColor: 'var(--accent)' }}
                        />
                      ) : isSaved ? (
                        <span data-testid={`cm-saved-${f.key}`}
                              style={{ color: 'var(--badge-green-text)', fontSize: 13, fontWeight: 700 }}
                              title="Already saved on draft">✓</span>
                      ) : (
                        <span style={{ display: 'inline-block', width: 16 }} />
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', fontWeight: 600 }}>{f.label}</div>
                    <div data-testid={`cm-field-${f.key}-draft`}><CmValue v={f.draft} /></div>
                    <div data-testid={`cm-field-${f.key}-suggestion`}><CmValue v={f.suggestion} /></div>
                    <div><CmSourceBadge source={f.source} /></div>
                  </div>
                );
              })}

              {/* Apply error / success feedback */}
              {applyError && (
                <div data-testid="cm-apply-error" style={{
                  marginTop: 10, padding: '8px 12px', borderRadius: 6,
                  background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)',
                  fontSize: 12, color: 'var(--badge-red-text)',
                }}>
                  {applyError}
                </div>
              )}
              {applySuccess && !applyError && (
                <div data-testid="cm-apply-success" style={{
                  marginTop: 10, padding: '8px 12px', borderRadius: 6,
                  background: 'var(--badge-green-bg)', border: '1px solid var(--badge-green-border)',
                  fontSize: 12, color: 'var(--badge-green-text)',
                }}>
                  Commercial defaults applied successfully.
                </div>
              )}

              {/* Apply button */}
              <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  data-testid="btn-apply-cm-commercial"
                  disabled={!canApply}
                  onClick={handleApply}
                  style={{
                    padding: '7px 18px', borderRadius: 6, border: 'none', cursor: canApply ? 'pointer' : 'not-allowed',
                    background: canApply ? 'var(--accent)' : 'var(--bg-subtle)',
                    color: canApply ? '#fff' : 'var(--text-3)',
                    fontWeight: 700, fontSize: 12,
                    opacity: applying ? 0.7 : 1,
                  }}
                >
                  {applying ? 'Applying…' : 'Apply Selected Suggestions'}
                </button>
                {checkedKeys.length > 0 && !applying && (
                  <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                    {checkedKeys.length} field{checkedKeys.length !== 1 ? 's' : ''} selected
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </PfPanelCard>
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────
function ProformaOverviewTab({ detail, lines, fxRate, vatResolution, blockingReasons, exportBlockers, editMode, editFields, onEditField, editError }) {
  const totalEur = lines.reduce((s, l) => s + l.netEur, 0);
  // Computed payment due in edit mode: sale_date (or invoice_date) + payment_days
  const _editComputedDue = (() => {
    if (!editMode) return null;
    const base = editFields.pt_sale_date || editFields.pt_invoice_date;
    const days = editFields.pt_days !== '' ? parseInt(editFields.pt_days, 10) : null;
    if (!base || days == null || isNaN(days)) return null;
    try {
      const d = new Date(base + 'T00:00:00Z');
      d.setUTCDate(d.getUTCDate() + days);
      return d.toISOString().slice(0, 10);
    } catch (e) { return null; }
  })();
  const currency = detail.currency || 'EUR';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Invoice identity card — shown after successful conversion */}
      {detail.wfirma_invoice_id && (
        <div style={{
          padding: '12px 16px',
          background: 'var(--badge-green-bg)',
          border: '2px solid var(--badge-green-border, var(--accent))',
          borderRadius: 8,
          display: 'flex', alignItems: 'center', gap: 12,
        }} data-testid="invoice-identity-card">
          <span style={{ fontSize: 20 }}>✅</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--badge-green-text, var(--accent))' }}>
              Invoice Created
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>
              {detail.wfirma_invoice_number
                ? <span>wFirma invoice <strong style={{ fontFamily: 'monospace' }}>{detail.wfirma_invoice_number}</strong></span>
                : <span>wFirma invoice ID <strong style={{ fontFamily: 'monospace' }}>{detail.wfirma_invoice_id}</strong></span>
              }
              {detail.converted_at && <span style={{ marginLeft: 8 }}>· {(detail.converted_at || '').slice(0, 10)}</span>}
            </div>
          </div>
        </div>
      )}

      {/* Edit mode banner */}
      {editMode && (
        <div style={{ padding: '10px 14px', background: 'var(--badge-green-bg)', border: '2px solid var(--accent)', borderRadius: 6 }} data-testid="edit-mode-banner">
          <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--accent)' }}>
            ✎ Edit Mode — Modify header fields below and click Save in the toolbar
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4 }}>
            Uses PATCH /api/v1/proforma/draft/{'{id}'} with optimistic locking (expected_updated_at).
            Line items are edited individually on the Lines tab.
          </div>
        </div>
      )}

      {/* Edit error banner */}
      {editError && (
        <div style={{ padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6 }} data-testid="edit-error-banner">
          <div style={{ fontWeight: 700, fontSize: 12, color: 'var(--badge-red-text)' }}>⚠ {editError}</div>
        </div>
      )}

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

      {/* ── Summary (wireframe StatTiles) — display-only arithmetic ───────── */}
      <div>
        <PfSectionLabel>Summary</PfSectionLabel>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 14 }}>
          <PfStatTile label="Line Items" value={lines.length} data-testid="pf-summary-line-items" />
          <PfStatTile label="Total Items" value={lines.reduce((s, l) => s + (Number(l.qty) || 0), 0)} data-testid="pf-summary-total-items" />
          <PfStatTile label={`Total ${currency}`} value={totalEur.toFixed(2)} accent="var(--accent)" data-testid="pf-summary-total-cur" />
          {/* Sprint-36 authority pin (test_no_total_eur_times_fx_rate): NO
              browser-side FX conversion — the PLN total is wFirma's at posting,
              never fabricated here. The tile stays (wireframe slot), the value
              is honest. */}
          <PfStatTile label="Total PLN" value="—" data-testid="pf-summary-total-pln" />
        </div>
      </div>

      {/* ── Customer & terms (wireframe PanelCard; edit controls preserved) ── */}
      <div>
        <PfSectionLabel>Customer &amp; terms</PfSectionLabel>
        <PfPanelCard>
          <div style={{ padding: '8px 20px 12px' }}>
            <InfoRow label="Customer" value={detail.client_name || '—'} />
            {editMode ? (
              <PfFieldRow label="Currency">
                <div data-testid="edit-currency-container" style={{ width: '100%' }}>
                  <EditableKvItem k="" value={editFields.currency || ''} onChange={v => onEditField('currency', v)} />
                </div>
              </PfFieldRow>
            ) : (
              <InfoRow label="Currency" value={currency} />
            )}
            {editMode ? (
              <PfFieldRow label="Payment method">
                <div data-testid="edit-pt-method-container" style={{ width: '100%' }}>
                  <select
                    value={editFields.pt_method || ''}
                    onChange={e => onEditField('pt_method', e.target.value)}
                    data-testid="edit-pt-method"
                    style={{ width: '100%', padding: '6px 9px', borderRadius: 6, border: '1px solid var(--accent-border)', background: 'var(--card)', color: 'var(--text)', fontSize: 12, fontWeight: 600 }}
                  >
                    <option value="">— not set —</option>
                    <option value="transfer">transfer</option>
                    <option value="cash">cash</option>
                    <option value="card">card</option>
                    <option value="compensation">compensation</option>
                  </select>
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 600, marginBottom: 2 }}>Payment days</div>
                    <input
                      type="number" min="0" max="365"
                      value={editFields.pt_days || ''}
                      onChange={e => onEditField('pt_days', e.target.value)}
                      data-testid="edit-pt-days"
                      placeholder="e.g. 30"
                      style={{ width: '100%', padding: '6px 9px', borderRadius: 6, border: '1px solid var(--accent-border)', background: 'var(--card)', color: 'var(--text)', fontSize: 12, fontWeight: 600 }}
                    />
                  </div>
                </div>
              </PfFieldRow>
            ) : (
              <InfoRow label="Payment method" value={detail.paymentTerms || '—'} />
            )}
            <InfoRow label="Incoterm" value={detail.incoterm || '—'} />
            <InfoRow label="Status" value={(PF_STATUS_CHIP[detail.draft_state] || {}).label || detail.draft_state || '—'} />
          </div>
        </PfPanelCard>
      </div>

      {/* ── VAT & Insurance / KUKE (wireframe PanelCard; display-only, Slice 4) ── */}
      <VatInsurancePanel
        contractorId={detail.client_contractor_id}
        vatCode={detail.vat_code}
        vatContext={detail.vat_context}
        totalEur={totalEur}
        currency={currency}
      />

      {/* ── Dates & FX (wireframe PanelCard; edit controls preserved) ──────── */}
      <div>
        <PfSectionLabel>Dates &amp; FX</PfSectionLabel>
        <PfPanelCard>
          <div style={{ padding: '8px 20px 12px' }}>
            {editMode ? (
              <PfFieldRow label="Invoice issue date">
                <div data-testid="edit-pt-invoice-date-container" style={{ width: '100%' }}>
                  <input
                    type="date"
                    value={editFields.pt_invoice_date || ''}
                    onChange={e => onEditField('pt_invoice_date', e.target.value)}
                    data-testid="edit-pt-invoice-date"
                    style={{ width: '100%', padding: '6px 9px', borderRadius: 6, border: '1px solid var(--accent-border)', background: 'var(--card)', color: 'var(--text)', fontSize: 12, fontWeight: 600 }}
                  />
                </div>
              </PfFieldRow>
            ) : (
              <InfoRow label="Issue date" value={detail.created_at ? detail.created_at.slice(0, 10) : '—'} mono />
            )}
            {editMode ? (
              <PfFieldRow label="Sale date">
                <div data-testid="edit-pt-sale-date-container" style={{ width: '100%' }}>
                  <input
                    type="date"
                    value={editFields.pt_sale_date || ''}
                    onChange={e => onEditField('pt_sale_date', e.target.value)}
                    data-testid="edit-pt-sale-date"
                    style={{ width: '100%', padding: '6px 9px', borderRadius: 6, border: '1px solid var(--accent-border)', background: 'var(--card)', color: 'var(--text)', fontSize: 12, fontWeight: 600 }}
                  />
                </div>
              </PfFieldRow>
            ) : (
              <InfoRow label="Sale date" value={detail.sale_date || '—'} mono />
            )}
            <InfoRow label="Payment due" value={(editMode ? (_editComputedDue || '—') : (detail.payment_due_date || '—'))} mono />
            {editMode ? (
              <PfFieldRow label={`${currency}/PLN rate`} hint="NBP">
                <div data-testid="edit-exchange-rate" style={{ width: '100%' }}>
                  <EditableKvItem k="" value={editFields.exchange_rate || ''} onChange={v => onEditField('exchange_rate', v)} />
                </div>
              </PfFieldRow>
            ) : (
              <InfoRow label={`${currency}/PLN rate`} value={fxRate ? fxRate.toFixed(4) : '—'} mono />
            )}
            <InfoRow label="NBP table" value={detail.nbp_table_number || '—'} mono />
            <InfoRow label="Rate date" value={detail.exchange_rate_date || '—'} mono />
          </div>
        </PfPanelCard>
      </div>

      {/* ── Shipment reference & wFirma identity (wireframe PanelCard) ─────── */}
      <div>
        <PfSectionLabel>Shipment reference</PfSectionLabel>
        <PfPanelCard>
          <div style={{ padding: '8px 20px 12px' }}>
            <InfoRow label="Number" value={detail.wfirma_proforma_fullnumber || '—'} mono />
            <InfoRow label="Shipment ID" value={detail.batch_id || '—'} mono />
            <InfoRow label="KSeF" value={detail.ksef_number || '—'} mono />
            <InfoRow label="Amount due" value={`${totalEur.toFixed(2)} ${currency}`} />
            <InfoRow label="Paid" value="— see Payment status" />
            <InfoRow label="Accounting scheme" value={detail.accounting_scheme || 'Standard'} />
            <InfoRow label="JPK codes" value={detail.jpk_codes || 'none'} />
            <InfoRow label="Warehouse" value={detail.warehouse || 'Main'} />
            <InfoRow label="wFirma proforma ID" value={detail.wfirma_proforma_id || '—'} mono />
            <InfoRow label="wFirma invoice ID" value={detail.wfirma_invoice_id || '—'} mono />
            <InfoRow label="Source" value={detail.clone_source || detail.source_description || detail.source || '—'} />
          </div>
        </PfPanelCard>
      </div>

      {/* Editable remarks (only in edit mode) */}
      {editMode && (
        <div data-testid="edit-remarks-section">
          <EditableKvItem k="Remarks" value={editFields.remarks || ''} onChange={v => onEditField('remarks', v)} type="textarea" />
        </div>
      )}

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

      {/* Payment status — real figures on demand (reuse-only, live wFirma statement) */}
      <OverviewFinancials contractorId={detail.client_contractor_id} currency={currency} />
    </div>
  );
}

// ── Overview: VAT & Insurance / KUKE (wireframe PanelCard — Slice 4) ────────────
// Display-only wiring of the Slice-1 vat_code/vat_context draft keys plus the
// Customer Master KUKE fields. ONE fetch per draft via the existing
// PzApi.getCustomerMaster (same call the AWB modal uses); a missing contractor
// id, a missing master row, or a failed fetch renders '—' for every field —
// this panel NEVER blocks and NEVER gates (Lesson N: purely informational).
// Premium is a display-only estimate (goods total × customer insurance_rate):
// never persisted, never posted, never part of any readiness computation.
const PF_VAT_LABELS = {
  WDT:  '0% WDT — intra-EU supply',
  EXP:  '0% Export',
  NP:   'NP — not subject to PL VAT',
  '23': '23% domestic',
  '8':  '8% domestic',
  '5':  '5% domestic',
  '0':  '0%',
};

function VatInsurancePanel({ contractorId, vatCode, vatContext, totalEur, currency }) {
  const [master, setMaster] = React.useState(null);
  // idle → loading → loaded | failed | missing-id  (fail-visible, never fail-open)
  const [masterFetch, setMasterFetch] = React.useState('idle');

  React.useEffect(() => {
    if (!contractorId || !window.PzApi.getCustomerMaster) { setMasterFetch('missing-id'); return; }
    setMasterFetch('loading');
    window.PzApi.getCustomerMaster(contractorId)
      .then(r => {
        if (r && r.ok && r.data) { setMaster(r.data); setMasterFetch('loaded'); }
        else setMasterFetch('failed');
      })
      .catch(() => setMasterFetch('failed'));
  }, [contractorId]);

  const m = masterFetch === 'loaded' ? (master || {}) : {};
  const vatLabel = vatCode ? (PF_VAT_LABELS[String(vatCode)] || String(vatCode)) : '—';
  const rate = (m.insurance_rate != null && m.insurance_rate !== '' && !Number.isNaN(Number(m.insurance_rate)))
    ? Number(m.insurance_rate) : null;
  const premium = (rate != null && totalEur > 0)
    ? `${(totalEur * rate).toFixed(2)} ${currency} (est.)`
    : '—';
  const kukeApproved = m.kuke_approved === true ? 'Yes' : m.kuke_approved === false ? 'No' : '—';
  const kukeLimit = (m.kuke_limit != null && m.kuke_limit !== '')
    ? `${m.kuke_limit} ${m.kuke_currency || ''}`.trim() : '—';

  return (
    <div>
      <PfSectionLabel>VAT &amp; Insurance (KUKE)</PfSectionLabel>
      <PfPanelCard data-testid="pf-vat-insurance">
        <div style={{ padding: '8px 20px 12px' }}>
          <InfoRow label="VAT treatment" value={vatLabel} />
          <InfoRow label="VAT context" value={vatContext || '—'} />
          <InfoRow label="KUKE insured" value={kukeApproved} />
          <InfoRow label="KUKE policy" value={m.kuke_policy_number || '—'} mono />
          <InfoRow label="KUKE limit" value={kukeLimit} mono />
          <InfoRow label="Insurance rate" value={rate != null ? `${(rate * 100).toFixed(2)}%` : '—'} mono />
          <div data-testid="pf-kuke-premium">
            <InfoRow label="Premium (display-only)" value={premium} mono />
          </div>
          {masterFetch === 'failed' && (
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 6 }} data-testid="pf-kuke-fetch-failed">
              Customer Master unavailable — insurance fields shown as '—'.
            </div>
          )}
        </div>
      </PfPanelCard>
    </div>
  );
}

// ── Overview: payment status (reuse-only, load-on-demand) ───────────────────────
// Real invoiced / received / outstanding for the customer, from the wFirma
// Statement of Account. Load-on-demand (button) — no automatic live call on
// every render. Reuses GET /api/v1/ledgers/clients/{contractor_id}/statement.json.
function OverviewFinancials({ contractorId, currency }) {
  const [state, setState] = React.useState({ status: 'idle', data: null, err: null });

  const load = () => {
    if (!contractorId) return;
    setState({ status: 'loading', data: null, err: null });
    // Wide default window: last ~2 years to as-of today (browser Date is fine here).
    const to = new Date();
    const from = new Date(); from.setFullYear(from.getFullYear() - 2);
    const iso = (d) => d.toISOString().slice(0, 10);
    const qs = `from=${iso(from)}&to=${iso(to)}&as_of=${iso(to)}`;
    window.EstrellaShared.apiFetch(`/api/v1/ledgers/clients/${encodeURIComponent(contractorId)}/statement.json?${qs}`)
      .then(r => setState({ status: 'done', data: r, err: null }))
      .catch(e => setState({ status: 'error', data: null, err: (e && e.message) || 'Statement unavailable' }));
  };

  const box = { padding: '12px 16px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6 };
  const money = (v) => (v == null ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

  if (!contractorId) {
    return (
      <div style={box} data-testid="pf-overview-financials-unavailable">
        <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Payment status</div>
        <div style={{ fontSize: 11.5, color: 'var(--badge-amber-text)' }}>
          <strong>Backend Pending:</strong> this draft is not resolved to a wFirma contractor, so paid/outstanding cannot be read. Match the customer on the Customer Mapping tab first.
        </div>
      </div>
    );
  }

  const totals = (state.data && state.data.totals_per_currency) || {};
  const aging  = (state.data && state.data.aging_per_currency) || {};
  const ccys   = Object.keys(totals);

  return (
    <div style={box} data-testid="pf-overview-financials">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Payment status</div>
        <button data-testid="pf-overview-financials-load" onClick={load} disabled={state.status === 'loading'}
          style={{ padding: '4px 10px', fontSize: 11, fontWeight: 600, color: 'var(--text)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 5, cursor: 'pointer', opacity: state.status === 'loading' ? 0.6 : 1 }}>
          {state.status === 'loading' ? '↻ Loading…' : (state.status === 'done' ? '↻ Reload' : '↻ Load payment status (wFirma)')}
        </button>
      </div>
      {state.status === 'idle' && <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>Live wFirma read — click to load invoiced / received / outstanding for this customer.</div>}
      {state.status === 'error' && <div style={{ fontSize: 11.5, color: 'var(--badge-amber-text)' }} data-testid="pf-overview-financials-err">Could not load · {state.err}</div>}
      {state.status === 'done' && ccys.length === 0 && <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>No invoices on record for this customer in the window.</div>}
      {state.status === 'done' && ccys.map((cc) => {
        const t = totals[cc] || {}; const a = aging[cc] || {};
        return (
          <div key={cc} data-testid="pf-overview-financials-row" style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 3 }}>{cc}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, fontSize: 11.5 }}>
              <div><div style={{ color: 'var(--text-3)' }}>Invoiced</div><div style={{ fontWeight: 600, color: 'var(--text)' }}>{money(t.invoiced)}</div></div>
              <div><div style={{ color: 'var(--text-3)' }}>Received</div><div style={{ fontWeight: 600, color: 'var(--badge-green-text, #2e7d32)' }}>{money(t.received)}</div></div>
              <div><div style={{ color: 'var(--text-3)' }}>Outstanding</div><div style={{ fontWeight: 700, color: (Number(t.outstanding) > 0 ? 'var(--badge-amber-text)' : 'var(--text)') }}>{money(t.outstanding)}</div></div>
              <div><div style={{ color: 'var(--text-3)' }}>Overdue (90d+)</div><div style={{ fontWeight: 600, color: 'var(--text)' }}>{money(a['90d'] != null ? a['90d'] : a.total)}</div></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Lines tab ─────────────────────────────────────────────────────────────────
// Wireframe rebuild Slice 3: packing-list column set from the operator-approved
// wireframe — Sr / Product Code / Design Nr / Ctg / Client PO /
// Description (EN over PL) / Kt / Col / Quality / Dia Wt / Col Wt / Qty /
// Value / Total / Size — with the Goods subtotal · Freight · Insurance ·
// Grand total footer read from the draft's service_charges (display-only
// arithmetic; the engine stays the calculation authority). Variant identity
// columns read the Slice-1 fields (older drafts show '—' until reset/intake).
// HS code + origin remain on the printable documents (Preview/Print); the
// wireframe table is the UI authority for on-screen columns.
// PFW-S5: line operations (add / qty+price edit / delete) wired to the
// EXISTING draft-line authority — POST/PATCH/DELETE /draft/{id}/lines via
// PzApi.addDraftLine / patchDraftLine / deleteDraftLine. Editable fields are
// EXACTLY the whitelisted subset shown here (qty, unit_price); variant
// identity stays reset-refreshed (pinned EDITABLE_LINE_FIELDS contract + ADR
// proforma-wireframe-rebuild). Product picker reads the existing read-only
// product-options authority. Every op reloads the draft (onChanged) so the
// OCC token (expected_updated_at) is always the server's latest.
function ProformaLinesTab({ lines, currency, onAddLine, serviceCharges,
                            draftId, expectedUpdatedAt, editMode, onChanged }) {
  const cur = currency || 'EUR';
  const sym = cur === 'USD' ? '$' : cur === 'EUR' ? '€' : `${cur} `;
  const lineOpsEnabled = !!(editMode && draftId);
  // Per-row edit buffers keyed by line_id: { qty, unit_price }
  const [rowEdit, setRowEdit] = React.useState({});
  const [rowBusy, setRowBusy] = React.useState({});
  const [rowErr, setRowErr]   = React.useState({});
  // Add-line row state
  const [addLine, setAddLine] = React.useState({ product_code: '', design_no: '', qty: '1', unit_price: '' });
  const [addBusy, setAddBusy] = React.useState(false);
  const [addErr, setAddErr]   = React.useState(null);
  // Product options (read-only picker authority) — lazy, once per mount
  const [options, setOptions] = React.useState(null);
  React.useEffect(() => {
    if (!lineOpsEnabled || options !== null) return;
    window.PzApi.getProductOptions()
      // Transport envelope: PzApi wraps payloads as { ok, data } — the
      // option list lives at r.data.options.
      .then(r => setOptions((r && r.ok && r.data && Array.isArray(r.data.options)) ? r.data.options : []))
      .catch(() => setOptions([]));
  }, [lineOpsEnabled, options]);

  const _rowVal = (line, key, fallback) => {
    const buf = rowEdit[line.lineId];
    return (buf && buf[key] !== undefined) ? buf[key] : String(fallback);
  };
  const _setRow = (line, key, v) =>
    setRowEdit(p => ({ ...p, [line.lineId]: { ...(p[line.lineId] || {}), [key]: v } }));
  const _rowDirty = (line) => {
    const buf = rowEdit[line.lineId];
    if (!buf) return false;
    return (buf.qty !== undefined && Number(buf.qty) !== Number(line.qty))
        || (buf.unit_price !== undefined && Number(buf.unit_price) !== Number(line.unitEur));
  };
  const saveRow = (line) => {
    const buf = rowEdit[line.lineId] || {};
    const patch = {};
    if (buf.qty !== undefined && Number(buf.qty) !== Number(line.qty)) patch.qty = Number(buf.qty);
    if (buf.unit_price !== undefined && Number(buf.unit_price) !== Number(line.unitEur)) patch.unit_price = Number(buf.unit_price);
    if (!Object.keys(patch).length) return;
    setRowBusy(p => ({ ...p, [line.lineId]: true }));
    setRowErr(p => ({ ...p, [line.lineId]: null }));
    window.PzApi.patchDraftLine(draftId, line.lineId, patch, expectedUpdatedAt)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && r.error) || 'Save rejected');
        setRowBusy(p => ({ ...p, [line.lineId]: false }));
        setRowEdit(p => { const n = { ...p }; delete n[line.lineId]; return n; });
        onChanged && onChanged();
      })
      .catch(e => {
        setRowBusy(p => ({ ...p, [line.lineId]: false }));
        setRowErr(p => ({ ...p, [line.lineId]: (e && e.message) || 'Save failed' }));
      });
  };
  const deleteRow = (line) => {
    setRowBusy(p => ({ ...p, [line.lineId]: true }));
    setRowErr(p => ({ ...p, [line.lineId]: null }));
    // force stays false: removing the LAST line errors honestly (backend
    // guard) — the draft's line source of truth is the packing authority.
    window.PzApi.deleteDraftLine(draftId, line.lineId, expectedUpdatedAt, false)
      .then(r => {
        if (r && r.ok === false) throw new Error((r && r.error) || 'Delete rejected');
        setRowBusy(p => ({ ...p, [line.lineId]: false }));
        onChanged && onChanged();
      })
      .catch(e => {
        setRowBusy(p => ({ ...p, [line.lineId]: false }));
        setRowErr(p => ({ ...p, [line.lineId]: (e && e.message) || 'Delete failed' }));
      });
  };
  const submitAddLine = () => {
    if (addBusy) return;
    const pc = (addLine.product_code || '').trim();
    const q  = Number(addLine.qty);
    const up = Number(addLine.unit_price);
    if (!pc) { setAddErr('Pick a product from Product Master first.'); return; }
    if (!(q > 0)) { setAddErr('Qty must be > 0.'); return; }
    if (!(up >= 0) || addLine.unit_price === '') { setAddErr('Unit price must be ≥ 0.'); return; }
    setAddBusy(true); setAddErr(null);
    window.PzApi.addDraftLine(draftId, {
      expected_updated_at: expectedUpdatedAt || '',
      line: { product_code: pc, design_no: addLine.design_no || '', qty: q, unit_price: up, currency: cur },
    })
      .then(r => {
        if (r && r.ok === false) throw new Error((r && r.error) || 'Add rejected');
        setAddBusy(false);
        setAddLine({ product_code: '', design_no: '', qty: '1', unit_price: '' });
        onChanged && onChanged();
      })
      .catch(e => { setAddBusy(false); setAddErr((e && e.message) || 'Add failed'); });
  };
  const editCell = { width: 68, textAlign: 'right', padding: '4px 6px', borderRadius: 5, border: '1px solid var(--accent-border)', background: 'var(--card)', color: 'var(--text)', fontSize: 11.5, fontFamily: 'monospace', fontWeight: 600, boxSizing: 'border-box' };
  const raw = (line, key) => (line._raw && line._raw[key] != null ? line._raw[key] : null);
  const rawTxt = (line, key) => { const v = raw(line, key); return (v || v === 0) && String(v).trim() ? String(v) : '—'; };
  const rawWt = (line, key) => { const v = Number(raw(line, key) || 0); return v > 0 ? v.toFixed(2) : '—'; };
  const goods = lines.reduce((s, l) => s + l.netEur, 0);
  const charges = Array.isArray(serviceCharges) ? serviceCharges : [];
  const chargeAmt = (type) => {
    const c = charges.find(x => x && x.charge_type === type);
    return c && c.amount != null ? Number(c.amount) : null;
  };
  const freight = chargeAmt('freight');
  const insurance = chargeAmt('insurance');
  const grand = goods + (freight || 0) + (insurance || 0);
  const th = (txt, align) => (
    <th key={txt} style={{ padding: '9px 10px', textAlign: align || 'left', fontSize: 9.5, fontWeight: 700,
      color: 'var(--text-3)', letterSpacing: '0.05em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{txt}</th>
  );
  const COLS = lineOpsEnabled ? 16 : 15;
  return (
    <div>
      <PfSectionLabel style={{ marginBottom: 12 }}>
        Line items ({lines.length}) · from packing list · mapped to Product Master
      </PfSectionLabel>
      {lineOpsEnabled && (
        <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, marginBottom: 8 }} data-testid="pf-line-ops-hint">
          ✎ Edit mode — qty and unit price are editable per line; other columns come from the packing
          authority (refresh via Reset from sales packing).
        </div>
      )}
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'auto', boxShadow: '0 1px 3px var(--shadow)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1180 }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              {th('Sr')}{th('Product Code')}{th('Design Nr')}{th('Ctg')}{th('Client PO')}
              {th('Description (EN / PL)')}{th('Kt')}{th('Col')}{th('Quality')}
              {th('Dia Wt', 'right')}{th('Col Wt', 'right')}{th('Qty', 'right')}
              {th(`Value ${sym.trim()}`, 'right')}{th(`Total ${sym.trim()}`, 'right')}{th('Size')}
              {lineOpsEnabled ? th('') : null}
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={COLS} style={{ padding: '28px 14px', textAlign: 'center', fontSize: 12, color: 'var(--text-3)' }}>
                  <div>No line items — draft not yet built from packing upload.</div>
                  {/* Reuses the existing draft Edit surface — no new authority, no parallel
                     line store; Packing List remains the line source. */}
                  {onAddLine && (
                    <button data-testid="lines-add-line" onClick={onAddLine}
                      style={{ marginTop: 14, padding: '6px 14px', fontSize: 12, fontWeight: 700,
                        background: 'var(--accent)', color: 'var(--accent-text)',
                        border: '1px solid var(--accent-border, var(--accent))', borderRadius: 6, cursor: 'pointer' }}>
                      ＋ Add line
                    </button>
                  )}
                </td>
              </tr>
            )}
            {lines.map((line, i) => (
              <tr key={line.lineId || line.seq} data-testid={`line-row-${i}`}
                style={{ borderBottom: i < lines.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{line.seq}</td>
                <td style={{ padding: '10px', whiteSpace: 'nowrap' }}>
                  {line.sku && line.sku !== '—'
                    ? <span style={{ fontFamily: 'monospace', fontSize: 11.5, fontWeight: 600, color: 'var(--accent)' }}>{line.sku}</span>
                    : <span style={{ fontSize: 10, color: 'var(--badge-amber-text)' }}>unmapped</span>}
                </td>
                <td style={{ padding: '10px', fontFamily: 'monospace', fontSize: 11.5, color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{rawTxt(line, 'design_no')}</td>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text)', whiteSpace: 'nowrap' }}>
                  {/* Ctg is derived display-only from item_type (no Ctg column in schema) */}
                  {line.ctgLabel || '—'}
                </td>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text)', whiteSpace: 'nowrap' }}>
                  {(raw(line, 'client_po') || raw(line, 'client_ref')) ? String(raw(line, 'client_po') || raw(line, 'client_ref')) : '—'}
                </td>
                <td style={{ padding: '10px', minWidth: 220 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{line.desc_en || '—'}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 1 }}>{line.desc_pl || line.desc || ''}</div>
                </td>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text)', whiteSpace: 'nowrap' }}>{raw(line, 'karat') ? String(raw(line, 'karat')) : (line.purity || '—')}</td>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text)', whiteSpace: 'nowrap' }}>{rawTxt(line, 'metal_color')}</td>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text)', whiteSpace: 'nowrap' }}>{rawTxt(line, 'quality_string')}</td>
                <td style={{ padding: '10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 11.5, whiteSpace: 'nowrap' }}>{rawWt(line, 'diamond_weight')}</td>
                <td style={{ padding: '10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 11.5, whiteSpace: 'nowrap' }}>{rawWt(line, 'color_weight')}</td>
                <td style={{ padding: '10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
                  {lineOpsEnabled
                    ? <input type="number" min="0.01" step="1" value={_rowVal(line, 'qty', line.qty)}
                        onChange={e => _setRow(line, 'qty', e.target.value)}
                        data-testid={`pf-line-qty-${i}`} style={{ ...editCell, width: 56 }} />
                    : line.qty}
                </td>
                <td style={{ padding: '10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, whiteSpace: 'nowrap' }}>
                  {lineOpsEnabled
                    ? <input type="number" min="0" step="0.01" value={_rowVal(line, 'unit_price', line.unitEur)}
                        onChange={e => _setRow(line, 'unit_price', e.target.value)}
                        data-testid={`pf-line-price-${i}`} style={editCell} />
                    : `${sym}${line.unitEur.toFixed(2)}`}
                </td>
                <td style={{ padding: '10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12.5, fontWeight: 700, color: 'var(--text)', whiteSpace: 'nowrap' }}>{sym}{line.netEur.toFixed(2)}</td>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text)', whiteSpace: 'nowrap' }}>{rawTxt(line, 'size')}</td>
                {lineOpsEnabled ? (
                  <td style={{ padding: '10px', whiteSpace: 'nowrap' }}>
                    <button
                      title={_rowDirty(line) ? 'Save qty / unit price for this line (PATCH)' : 'No changes on this line'}
                      disabled={!_rowDirty(line) || !!rowBusy[line.lineId]}
                      onClick={() => saveRow(line)}
                      data-testid={`pf-line-save-${i}`}
                      style={{ padding: '3px 8px', fontSize: 11, fontWeight: 700, borderRadius: 5, cursor: _rowDirty(line) ? 'pointer' : 'not-allowed',
                               background: _rowDirty(line) ? 'var(--accent)' : 'var(--bg-subtle)',
                               color: _rowDirty(line) ? 'var(--accent-text)' : 'var(--text-3)',
                               border: '1px solid var(--border)', opacity: rowBusy[line.lineId] ? 0.6 : 1 }}>
                      {rowBusy[line.lineId] ? '⏳' : '✓'}
                    </button>
                    <button
                      title="Delete this line from the draft (removing the last line is rejected)"
                      disabled={!!rowBusy[line.lineId]}
                      onClick={() => deleteRow(line)}
                      data-testid={`pf-line-delete-${i}`}
                      style={{ padding: '3px 8px', fontSize: 11, fontWeight: 700, borderRadius: 5, cursor: 'pointer', marginLeft: 4,
                               background: 'var(--bg-subtle)', color: 'var(--badge-red-text)',
                               border: '1px solid var(--badge-red-border)', opacity: rowBusy[line.lineId] ? 0.6 : 1 }}>
                      ×
                    </button>
                    {rowErr[line.lineId] && (
                      <div style={{ fontSize: 10, color: 'var(--badge-red-text)', maxWidth: 160, whiteSpace: 'normal', marginTop: 3 }} data-testid={`pf-line-err-${i}`}>
                        {rowErr[line.lineId]}
                      </div>
                    )}
                  </td>
                ) : null}
              </tr>
            ))}
            {lineOpsEnabled && (
              <tr data-testid="pf-add-line-row" style={{ borderTop: '2px solid var(--border)', background: 'var(--bg-subtle)' }}>
                <td style={{ padding: '10px', fontSize: 11.5, color: 'var(--text-3)' }}>＋</td>
                <td colSpan={5} style={{ padding: '8px 10px', minWidth: 260 }}>
                  <PfAutocomplete
                    value={addLine.product_code
                      ? `${addLine.product_code}${addLine.design_no ? ' · ' + addLine.design_no : ''}` : ''}
                    placeholder={options === null ? 'Loading Product Master…' : 'Search Product Master (code · name)…'}
                    items={options || []}
                    getLabel={o => `${o.product_code}${o.design_no ? ' · ' + o.design_no : ''}`}
                    getSub={o => [o.item_type, o.name_pl].filter(Boolean).join(' · ')}
                    onPick={o => { setAddErr(null); setAddLine(p => ({ ...p, product_code: o.product_code, design_no: o.design_no || '' })); }}
                    onClear={() => setAddLine(p => ({ ...p, product_code: '', design_no: '' }))}
                    data-testid="pf-add-line-product"
                  />
                </td>
                <td colSpan={5} style={{ padding: '8px 10px', fontSize: 10.5, color: 'var(--text-3)' }}>
                  New line · descriptions and variant fields fill from the product authorities after add
                </td>
                <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                  <input type="number" min="0.01" step="1" value={addLine.qty}
                    onChange={e => setAddLine(p => ({ ...p, qty: e.target.value }))}
                    data-testid="pf-add-line-qty" style={{ ...editCell, width: 56 }} />
                </td>
                <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                  <input type="number" min="0" step="0.01" placeholder="0.00" value={addLine.unit_price}
                    onChange={e => setAddLine(p => ({ ...p, unit_price: e.target.value }))}
                    data-testid="pf-add-line-price" style={editCell} />
                </td>
                <td colSpan={lineOpsEnabled ? 3 : 2} style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                  <button
                    onClick={submitAddLine}
                    disabled={addBusy}
                    title="Append this line to the draft (POST /draft/{id}/lines)"
                    data-testid="pf-add-line-submit"
                    style={{ padding: '5px 12px', fontSize: 11.5, fontWeight: 700, borderRadius: 6, cursor: 'pointer',
                             background: 'var(--accent)', color: 'var(--accent-text)',
                             border: '1px solid var(--accent-border, var(--accent))', opacity: addBusy ? 0.6 : 1 }}>
                    {addBusy ? '⏳ Adding…' : '＋ Add line'}
                  </button>
                  {addErr && (
                    <div style={{ fontSize: 10, color: 'var(--badge-red-text)', maxWidth: 200, whiteSpace: 'normal', marginTop: 3 }} data-testid="pf-add-line-err">
                      {addErr}
                    </div>
                  )}
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr style={{ background: 'var(--bg-subtle)', borderTop: '1px solid var(--border)' }}>
              <td colSpan={COLS - 2} style={{ padding: '8px 10px', textAlign: 'right', fontSize: 11, color: 'var(--text-2)' }}>Goods subtotal</td>
              <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
                {lines.length > 0 ? `${sym}${goods.toFixed(2)}` : '—'}
              </td>
              <td></td>
            </tr>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              <td colSpan={COLS - 2} style={{ padding: '8px 10px', textAlign: 'right', fontSize: 11, color: 'var(--text-2)' }}>
                Freight <span style={{ color: 'var(--text-3)', fontSize: 9.5 }}>· service charge</span>
              </td>
              <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, color: 'var(--text)' }} data-testid="pf-lines-freight">
                {freight != null ? `${sym}${freight.toFixed(2)}` : '—'}
              </td>
              <td></td>
            </tr>
            <tr style={{ background: 'var(--bg-subtle)' }}>
              <td colSpan={COLS - 2} style={{ padding: '8px 10px', textAlign: 'right', fontSize: 11, color: 'var(--text-2)' }}>
                Insurance <span style={{ color: 'var(--text-3)', fontSize: 9.5 }}>· service charge</span>
              </td>
              <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 12, color: 'var(--text)' }} data-testid="pf-lines-insurance">
                {insurance != null ? `${sym}${insurance.toFixed(2)}` : '—'}
              </td>
              <td></td>
            </tr>
            <tr style={{ borderTop: '2px solid var(--border)', background: 'var(--bg-subtle)' }}>
              <td colSpan={COLS - 2} style={{ padding: '11px 10px', textAlign: 'right', fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>Grand total</td>
              <td style={{ padding: '11px 10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: 'var(--accent)' }} data-testid="proforma-lines-total">
                {lines.length > 0 ? `${sym}${grand.toFixed(2)}` : '—'}
              </td>
              <td></td>
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
      <PfSectionLabel style={{ marginBottom: 0 }}>wFirma customer mapping</PfSectionLabel>
      {!mapped ? (
        <div style={{ padding: 24, background: 'var(--badge-red-bg)', border: '2px solid var(--badge-red-border)', borderRadius: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>⚠</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--badge-red-text)', marginBottom: 6 }}>No wFirma customer mapping</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.5 }}>
            Customer <strong>{customer.name}</strong> must be mapped to a wFirma record before converting to invoice.
          </div>
          {/* HTML-parity (atlas-proforma-preview.html · mapping tab): unmatched → Open Customer Master.
             Customer selection is the Customer Master authority; this navigates there, never a local list. */}
          <button
            data-testid="mapping-open-customer-master"
            onClick={() => { window.location.href = '/v2/master'; }}
            style={{ marginTop: 14, padding: '7px 16px', fontSize: 12.5, fontWeight: 700,
              background: 'var(--accent)', color: 'var(--accent-text)', border: '1px solid var(--accent-border, var(--accent))',
              borderRadius: 6, cursor: 'pointer' }}
          >Open Customer Master</button>
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

// ── Warehouse receipt confirmation (WAREHOUSE authority) ────────────────────
// Operator confirms received quantities by line. This — NOT scanning every
// physical piece — is the warehouse-receipt signal. Per-piece scan is optional
// traceability unless the shipment is serial_controlled. Visible + functional.
function ReceiptConfirmBlock({ batchId }) {
  const [status, setStatus]   = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [open, setOpen]       = React.useState(false);
  const [accepted, setAccepted] = React.useState({});   // line_key -> qty (string)
  const [busy, setBusy]       = React.useState(false);
  const [msg, setMsg]         = React.useState(null);

  const load = React.useCallback(() => {
    if (!batchId) return;
    setLoading(true);
    window.PzApi.getReceiptStatus(batchId)
      .then(r => setStatus((r && r.ok && r.data) ? r.data : null))
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, [batchId]);
  React.useEffect(() => { load(); }, [load]);

  const openEditor = () => {
    const seed = {};
    ((status && status.lines) || []).forEach(l => {
      seed[l.line_key] = String(l.accepted_qty != null ? l.accepted_qty : l.expected_qty);
    });
    setAccepted(seed);
    setOpen(true);
  };

  const submit = () => {
    const lines = Object.keys(accepted).map(k => ({ line_key: k, accepted_qty: Number(accepted[k]) }));
    if (!lines.length) return;
    setBusy(true); setMsg(null);
    window.PzApi.confirmReceipt(batchId, lines)
      .then(r => {
        if (r && r.ok) { setMsg({ ok: true, text: `Confirmed ${(r.data && r.data.confirmed_now) || lines.length} line(s).` }); setOpen(false); load(); }
        else { setMsg({ ok: false, text: (r && r.error) || 'Confirmation failed.' }); }
      })
      .catch(e => setMsg({ ok: false, text: String(e) }))
      .finally(() => setBusy(false));
  };

  const total   = status ? status.total_lines : 0;
  const confd   = status ? status.confirmed_lines : 0;
  const serial  = !!(status && status.serial_controlled);

  return (
    <div data-testid="receipt-confirm-block" style={{
      background: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, padding: '12px 16px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>Warehouse receipt — received quantities</div>
        {serial && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--badge-amber-text)' }}>SERIAL-CONTROLLED · scan required</span>}
      </div>
      {loading ? (
        <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading receipt status…</div>
      ) : total === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No import packing lines found for this batch.</div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
          {confd} / {total} line(s) confirmed
          {status.shortage_lines > 0 ? ` · ${status.shortage_lines} shortage` : ''}
          {status.overage_lines > 0 ? ` · ${status.overage_lines} overage` : ''}
          {status.fully_confirmed ? ' ✓' : ''}
        </div>
      )}
      {msg && (
        <div data-testid="receipt-confirm-msg" style={{ fontSize: 12, marginTop: 6,
          color: msg.ok ? 'var(--badge-green-text)' : 'var(--badge-red-text)' }}>{msg.text}</div>
      )}
      {total > 0 && !open && (
        <div style={{ marginTop: 8 }}>
          <Btn small variant="primary" data-testid="receipt-confirm-open" onClick={openEditor}>
            Confirm received quantities
          </Btn>
        </div>
      )}
      {open && (
        <div data-testid="receipt-confirm-editor" style={{ marginTop: 10 }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--text-3)' }}>
                <th style={{ padding: '4px 6px' }}>Product</th>
                <th style={{ padding: '4px 6px' }}>Expected</th>
                <th style={{ padding: '4px 6px' }}>Accepted</th>
              </tr>
            </thead>
            <tbody>
              {((status && status.lines) || []).map(l => (
                <tr key={l.line_key} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '4px 6px' }}>{l.product_code || l.design_no || l.line_key}</td>
                  <td style={{ padding: '4px 6px' }}>{l.expected_qty}</td>
                  <td style={{ padding: '4px 6px' }}>
                    <input
                      type="number" step="any"
                      data-testid={`receipt-accept-${l.line_key}`}
                      value={accepted[l.line_key] != null ? accepted[l.line_key] : ''}
                      onChange={e => setAccepted({ ...accepted, [l.line_key]: e.target.value })}
                      style={{ width: 80, padding: '2px 6px' }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <Btn small variant="primary" disabled={busy} data-testid="receipt-confirm-submit" onClick={submit}>
              {busy ? 'Saving…' : 'Save confirmation'}
            </Btn>
            <Btn small variant="ghost" disabled={busy} onClick={() => setOpen(false)}>Cancel</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Reservation tab ───────────────────────────────────────────────────────────
// WIRED: blocking_reasons and export_blockers from POST /api/v1/proforma/preview/{batch_id}/{client_name}
function ProformaReservationTab({ blockingReasons, exportBlockers, preview, canConvert,
                                  convertDisabledReason, onConvert,
                                  reservationLoading, reservationReady,
                                  reservationBatchReasons, reservationDraftReasons,
                                  reservationBatchAdvisories, reservationDraftAdvisories,
                                  reservationClientName, draftLineCount,
                                  reservationExists, reservationId, reservationBusy,
                                  reservationResult, batchId, onCreateReservation }) {
  const batchAdvisories = reservationBatchAdvisories || [];
  const draftAdvisories = reservationDraftAdvisories || [];
  const hasAdvisories = (batchAdvisories.length + draftAdvisories.length) > 0;
  const allReasons = [...blockingReasons, ...exportBlockers];
  const isBlocked  = allReasons.length > 0;
  const auditClean = exportBlockers.length === 0;
  // Two-scope reservation blockers (see ProformaDetailPage): draft/client-specific
  // vs batch-level (warehouse). Kept SEPARATE so a batch-wide warehouse count is
  // never read as a blocker on this draft's billed lines.
  const draftReasons = reservationDraftReasons || [];
  const batchReasons = reservationBatchReasons || [];
  const hasAnyReason = (draftReasons.length + batchReasons.length) > 0;
  // Disabled-reason for the Create Reservation button — the EXACT canonical
  // backend blocker, scope-labelled (draft blockers first, then batch-level).
  const resvDisabledReason = reservationLoading
    ? 'Loading reservation readiness…'
    : reservationExists
      ? `Reservation already created${reservationId ? ` (wFirma ${reservationId})` : ''}`
      : (draftReasons[0]
          ? `This draft: ${draftReasons[0]}`
          : (batchReasons[0]
              ? `Batch-level: ${batchReasons[0]}`
              : 'Reservation readiness not loaded — open this tab to check.'));
  const resvCanCreate = !!reservationReady && !reservationExists && !reservationBusy;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Cap strip with status chips */}
      <div
        data-testid="reservation-cap-strip"
        style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 16, borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
      >
        <CapChip ok={!!preview} label="wFirma configured" />
        <CapChip ok={auditClean} label="Audit clean" />
        <CapChip ok={reservationReady || reservationExists} label="Reservation ready" />
        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)', display: 'flex', gap: 18 }}>
          <span>Reservation: <strong style={{ color: 'var(--text)' }}>{(reservationReady || reservationExists) ? '1' : '0'} / 1</strong></span>
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

      {/* Advisories — warehouse traceability + sales-data linkage. These NEVER
          block the reservation (authority separation). Rendered distinctly from
          blockers so an operator is never misled into reading an advisory as a
          hard stop. */}
      {hasAdvisories && (
        <div data-testid="reservation-advisory-panel" style={{
          background: 'var(--badge-amber-bg)', border: '1px dashed var(--badge-amber-border)',
          borderRadius: 8, padding: '12px 16px',
        }}>
          <div style={{ fontWeight: 700, color: 'var(--badge-amber-text)', marginBottom: 6 }}>
            Advisories (do not block — informational)
          </div>
          {batchAdvisories.length > 0 && (
            <div style={{ marginBottom: draftAdvisories.length ? 8 : 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>
                Warehouse / batch (optional traceability):
              </div>
              <ul style={{ margin: '2px 0 0', paddingLeft: 20, fontSize: 12, color: 'var(--text-2)' }}>
                {batchAdvisories.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {draftAdvisories.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>
                Sales linkage (this draft):
              </div>
              <ul style={{ margin: '2px 0 0', paddingLeft: 20, fontSize: 12, color: 'var(--text-2)' }}>
                {draftAdvisories.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Warehouse receipt — operator quantity confirmation (WAREHOUSE authority).
          Replaces "scan every piece" as the receipt signal. Always visible. */}
      <ReceiptConfirmBlock batchId={batchId} />

      {/* Reservation create — canonical reservation readiness gate.
          The button reflects GET /wfirma/reservation-preview (distinct from the
          proforma post readiness above): disabled with the EXACT backend reason
          when not ready; when ready, click → confirm → live wFirma write. */}
      <div data-testid="reservation-create-block" style={{
        background: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)',
        borderRadius: 8, padding: '12px 16px',
      }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
          wFirma Reservation
        </div>
        {reservationExists ? (
          <div data-testid="reservation-exists" style={{ fontSize: 12, color: 'var(--badge-green-text)' }}>
            ✓ Reservation created{reservationId ? ` — wFirma ${reservationId}` : ''}.
          </div>
        ) : resvCanCreate ? (
          <div data-testid="reservation-ready" style={{ fontSize: 12, color: 'var(--badge-green-text)' }}>
            ✓ Reservation readiness clear — you can create the wFirma reservation (you will be asked to confirm).
          </div>
        ) : (
          <div data-testid="reservation-blocked-reason" style={{ fontSize: 12, color: 'var(--badge-amber-text)' }}>
            {reservationLoading ? 'Loading reservation readiness…' : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {/* This draft / client — blockers specific to the lines being billed here. */}
                {draftReasons.length > 0 && (
                  <div data-testid="reservation-draft-blockers">
                    <div style={{ fontWeight: 700 }}>
                      This draft{reservationClientName ? ` — ${reservationClientName}` : ''} ({draftLineCount != null ? draftLineCount : '—'} billed line{draftLineCount === 1 ? '' : 's'}):
                    </div>
                    <ul style={{ margin: '4px 0 0', paddingLeft: 20, color: 'var(--text-2)' }}>
                      {draftReasons.map((r, i) => <li key={i} style={{ marginBottom: 2 }}>{r}</li>)}
                    </ul>
                  </div>
                )}
                {/* Batch-level (warehouse) — affects EVERY client in the batch, not this
                    draft's billed lines. Explicitly labelled so a batch-wide packing
                    count (e.g. "84 …") is never read as a Draft #38 line blocker. */}
                {batchReasons.length > 0 && (
                  <div data-testid="reservation-batch-blockers">
                    <div style={{ fontWeight: 700 }}>
                      Batch-level (warehouse) — affects all clients in this batch, not this draft's billed lines:
                    </div>
                    <ul style={{ margin: '4px 0 0', paddingLeft: 20, color: 'var(--text-2)' }}>
                      {batchReasons.map((r, i) => <li key={i} style={{ marginBottom: 2 }}>{r}</li>)}
                    </ul>
                  </div>
                )}
                {!hasAnyReason && <div>{resvDisabledReason}</div>}
              </div>
            )}
          </div>
        )}
        {reservationResult && reservationResult.ok && (
          <div data-testid="reservation-success" style={{ fontSize: 12, color: 'var(--badge-green-text)', marginTop: 6 }}>
            ✓ wFirma reservation created{reservationResult.id ? ` (${reservationResult.id})` : ''}.
          </div>
        )}
        {reservationResult && !reservationResult.ok && (
          <div data-testid="reservation-inline-error" style={{ fontSize: 12, color: 'var(--badge-red-text)', marginTop: 6 }}>
            Reservation failed{reservationResult.code ? ` (${reservationResult.code})` : ''}: {reservationResult.error}
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
        <Btn
          variant="primary"
          disabled={!resvCanCreate}
          onClick={() => resvCanCreate && onCreateReservation && onCreateReservation()}
          title={resvCanCreate ? `Create wFirma reservation` : resvDisabledReason}
          data-testid="reservation-create-btn"
        >
          {reservationBusy ? 'Creating…' : 'Create Reservation'}
        </Btn>
        <Btn
          variant="danger"
          disabled={!canConvert}
          onClick={onConvert}
          title={canConvert ? 'Convert this proforma to a wFirma invoice' : (convertDisabledReason || 'Post to wFirma first, then convert')}
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

  // Wireframe timeline: left rail line, ✓ green dot per event (amber ! for
  // failure-ish event types). Same getDraftEvents data, presentation only.
  const _warnEvent = (e) => /fail|error|block|cancel/i.test(String(e.event_type || e.status || e.action || ''));
  return (
    <div>
      <PfSectionLabel>Activity history</PfSectionLabel>
      <PfPanelCard>
        <div style={{ padding: '20px 24px' }}>
          <div style={{ position: 'relative', paddingLeft: 32 }}>
            <div style={{ position: 'absolute', left: 10, top: 8, bottom: 8, width: 2, background: 'var(--border)' }} />
            {displayEvents.map((e, i) => {
              const warn = _warnEvent(e);
              return (
                <div key={i} style={{ position: 'relative', marginBottom: i < displayEvents.length - 1 ? 20 : 0, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                  <div style={{
                    position: 'absolute', left: -32, width: 22, height: 22, borderRadius: 11,
                    background: warn ? 'var(--badge-amber-bg)' : 'var(--badge-green-bg)',
                    border: `2px solid ${warn ? 'var(--badge-amber-border)' : 'var(--badge-green-border)'}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1,
                  }}>
                    <span style={{ fontSize: 11, color: warn ? 'var(--badge-amber-text)' : 'var(--badge-green-text)', fontWeight: 700 }}>{warn ? '!' : '✓'}</span>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      {(e.event_type || e.status) && (
                        <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 10, letterSpacing: '0.08em', fontWeight: 700, background: 'var(--bg-subtle)', color: 'var(--text-2)' }}>
                          {e.event_type || e.status}
                        </span>
                      )}
                      {e.action || e.description || '—'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2, fontFamily: 'monospace' }}>
                      {(e.ts || e.created_at || e.occurred_at || '—')}{e.user ? ` · ${e.user}` : (e.operator ? ` · ${e.operator}` : '')}
                    </div>
                    {e.detail && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{e.detail}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </PfPanelCard>
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
  const [confirmed,    setConfirmed]    = React.useState(false);
  const [loading,      setLoading]      = React.useState(false);
  const [apiError,     setApiError]     = React.useState(null);
  const [disclose,     setDisclose]     = React.useState(null);
  const [disclosing,   setDisclosing]   = React.useState(true);
  const [disclosureErr,setDisclosureErr]= React.useState(null);

  React.useEffect(() => {
    window.PzApi.getDisclosureConvert(draft.id)
      .then(r => {
        if (r && r.ok) setDisclose(r.data);
        else setDisclosureErr((r && r.error) || 'Preview unavailable');
        setDisclosing(false);
      })
      .catch(e => { setDisclosureErr(e.message || 'Preview unavailable'); setDisclosing(false); });
  }, [draft.id]);

  const [disclosure,        setDisclosure]        = React.useState(null);
  const [disclosureLoading, setDisclosureLoading] = React.useState(false);
  const [disclosureError,   setDisclosureError]   = React.useState(null);

  // Operator payment override state; pre-filled from disclosure on load
  const defaultsApplied = React.useRef(false);
  const [overrideMethod,      setOverrideMethod]      = React.useState('');
  const [overrideInvoiceDate, setOverrideInvoiceDate] = React.useState('');
  const [overrideSaleDate,    setOverrideSaleDate]    = React.useState(detail.sale_date || '');
  const [overrideDays,        setOverrideDays]        = React.useState('');

  React.useEffect(() => {
    setDisclosureLoading(true);
    window.PzApi.getDisclosureConvert(draft.id)
      .then(r => {
        if (r && r.data) {
          setDisclosure(r.data);
          if (!defaultsApplied.current) {
            defaultsApplied.current = true;
            const pr = r.data.payment_resolved || {};
            // Pre-fill from draft saved values (via disclosure) — operator edits these in Overview panel
            if (pr.method)       setOverrideMethod(pr.method);
            if (pr.invoice_date) setOverrideInvoiceDate(pr.invoice_date);
            if (pr.sale_date)    setOverrideSaleDate(pr.sale_date);
            if (pr.payment_days != null)          setOverrideDays(String(pr.payment_days));
            else if (pr.customer_default_days != null) setOverrideDays(String(pr.customer_default_days));
          }
        } else {
          setDisclosureError((r && r.error) || 'Payload preview unavailable');
        }
      })
      .catch(() => setDisclosureError('Payload preview unavailable'))
      .finally(() => setDisclosureLoading(false));
  }, [draft.id]);

  const computedPaymentDue = React.useMemo(() => {
    if (!overrideSaleDate || overrideDays === '') return '';
    try {
      const d = new Date(overrideSaleDate);
      d.setDate(d.getDate() + parseInt(overrideDays, 10));
      return d.toISOString().slice(0, 10);
    } catch (ex) { return ''; }
  }, [overrideSaleDate, overrideDays]);

  const handleConvert = () => {
    if (!confirmed || loading) return;
    setLoading(true);
    setApiError(null);
    const overrideBody = { confirm: 'YES_CREATE_FINAL_INVOICE_FROM_PROFORMA' };
    if (overrideMethod)      overrideBody.override_payment_method = overrideMethod;
    if (overrideInvoiceDate) overrideBody.override_invoice_date   = overrideInvoiceDate;
    if (overrideSaleDate)    overrideBody.override_sale_date      = overrideSaleDate;
    if (overrideDays !== '') overrideBody.override_payment_days   = parseInt(overrideDays, 10);
    window.PzApi.draftToInvoice(draft.id, overrideBody)
      .then(r => {
        const body = (r && r.data) || null;
        if (body && body.ok === false) {
          const reasons = body.blocking_reasons
            || (body.blockers || []).map(b => b.reason)
            || [];
          setApiError(
            reasons.length
              ? reasons.join(' · ')
              : (body.error || 'Conversion blocked — check backend logs.')
          );
          setLoading(false);
        } else {
          onSuccess && onSuccess();
        }
      })
      .catch(e => {
        setApiError((e && e.message) ? e.message : 'Conversion failed — check backend logs.');
        setLoading(false);
      });
  };

  const totalEur = detail.lines.reduce((s, l) => s + l.netEur, 0);
  const currency = detail.currency || 'EUR';

  // Resolved display: override > disclosure > draft fallback
  const resolvedMethod     = overrideMethod
    || (disclosure && disclosure.payment_resolved && disclosure.payment_resolved.method)
    || detail.paymentTerms || '—';
  const resolvedSaleDate   = overrideSaleDate || detail.sale_date || '—';
  const resolvedPaymentDue = computedPaymentDue
    || (disclosure && disclosure.payment_resolved && disclosure.payment_resolved.payment_date)
    || '—';

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
          <div style={{ fontSize: 10, letterSpacing: '0.14em', color: 'var(--text-3)', fontWeight: 700, marginBottom: 10, borderTop: '1px solid var(--border)', paddingTop: 14 }}>PAYLOAD PREVIEW</div>

          {disclosureLoading && (
            <div style={{ fontSize: 12, color: 'var(--text-3)', padding: '4px 0 8px' }}>Loading invoice payload preview…</div>
          )}
          {disclosureError && !disclosureLoading && (
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontStyle: 'italic', padding: '2px 0 8px' }}>⚠ {disclosureError} — showing draft values</div>
          )}

          {[
            ['Endpoint',        `POST /api/v1/proforma/draft/${draft.id}/to-invoice`],
            ['Source proforma', (disclosure && disclosure.source_proforma) || detail.wfirma_proforma_fullnumber || '—'],
            ['Customer',        detail.customer.wfirmaName || detail.customer.name || '—'],
            ['Currency',        (disclosure && disclosure.fields_to_write && disclosure.fields_to_write.currency) || currency],
            ['Series',          (disclosure && disclosure.fields_to_write && disclosure.fields_to_write.series_id) || '—'],
            ['FX rate',         detail.fx && detail.fx.rate ? `${detail.fx.rate.toFixed(4)} PLN (table ${detail.fx.table})` : '—'],
            ['Sale date',       resolvedSaleDate],
            ['Payment method',  resolvedMethod],
            ['Payment due',     resolvedPaymentDue],
            ['Flag required',   (disclosure && disclosure.flag_required) || 'WFIRMA_CREATE_INVOICE_ALLOWED'],
            [`Total (${currency})`, totalEur.toFixed(2)],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, padding: '5px 0', fontSize: 13 }}>
              <span style={{ color: 'var(--text-3)' }}>{k}</span>
              <span style={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-word' }}>{v}</span>
            </div>
          ))}

          {/* Operator payment overrides — pre-filled from Overview panel draft values */}
          <div style={{ fontSize: 10, letterSpacing: '0.14em', color: 'var(--text-3)', fontWeight: 700, marginBottom: 4, marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>EMERGENCY OVERRIDE (optional)</div>
          <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 10 }}>Pre-filled from Overview panel. Edit payment fields in the Overview panel to change them permanently.</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16, padding: '12px 14px', background: 'var(--bg-subtle)', borderRadius: 8, border: '1px solid var(--border)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, alignItems: 'center', fontSize: 13 }}>
              <label style={{ color: 'var(--text-3)' }}>Payment method</label>
              <select
                value={overrideMethod}
                onChange={e => setOverrideMethod(e.target.value)}
                data-testid="convert-modal-override-method"
                style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 13 }}
              >
                <option value="">— select —</option>
                <option value="transfer">transfer</option>
                <option value="cash">cash</option>
                <option value="card">card</option>
                <option value="compensation">compensation</option>
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, alignItems: 'center', fontSize: 13 }}>
              <label style={{ color: 'var(--text-3)' }}>Invoice date</label>
              <input
                type="date"
                value={overrideInvoiceDate}
                onChange={e => setOverrideInvoiceDate(e.target.value)}
                data-testid="convert-modal-override-invoice-date"
                style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 13 }}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, alignItems: 'center', fontSize: 13 }}>
              <label style={{ color: 'var(--text-3)' }}>Sale date</label>
              <input
                type="date"
                value={overrideSaleDate}
                onChange={e => setOverrideSaleDate(e.target.value)}
                data-testid="convert-modal-override-sale-date"
                style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 13 }}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, alignItems: 'center', fontSize: 13 }}>
              <label style={{ color: 'var(--text-3)' }}>Payment days</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <input
                  type="number"
                  min="0"
                  max="365"
                  value={overrideDays}
                  onChange={e => setOverrideDays(e.target.value)}
                  data-testid="convert-modal-override-days"
                  placeholder="e.g. 30"
                  style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontSize: 13, width: 90 }}
                />
                {computedPaymentDue && (
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>→ due {computedPaymentDue}</span>
                )}
              </div>
            </div>
          </div>

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

          {/* wFirma payload disclosure — live fetch from disclose-convert */}
          <div style={{ fontSize: 10, letterSpacing: '0.14em', color: 'var(--text-3)', fontWeight: 700, marginBottom: 10, marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>WFIRMA INVOICE PREVIEW</div>
          {disclosing ? (
            <div style={{ fontSize: 12, color: 'var(--text-3)', padding: '6px 0' }}>⏳ Loading invoice payload preview…</div>
          ) : disclosureErr ? (
            <div style={{ fontSize: 12, color: 'var(--badge-amber-text)', padding: '6px 10px', background: 'var(--badge-amber-bg)', borderRadius: 4 }}>
              Preview unavailable: {disclosureErr}
            </div>
          ) : disclose ? (() => {
            const fw = disclose.fields_to_write || {};
            return (
              <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
                {[
                  ['Source proforma', disclose.source_proforma || '—'],
                  ['Write target',    disclose.write_target    || '—'],
                  ['Flag required',   disclose.flag_required   || '—'],
                  ['Type',            fw.type                  || '—'],
                  ['Contractor ID',   fw.contractor_id         || '—'],
                  ['Currency',        fw.currency              || '—'],
                  ['Series',          fw.series_id             || '(wFirma contractor default)'],
                  ['Lines',           fw.line_count != null ? `${fw.line_count} line(s)` : '—'],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', gap: 12, padding: '3px 0', borderBottom: '1px dashed var(--border)' }}>
                    <span style={{ color: 'var(--text-3)', width: 130, flexShrink: 0 }}>{k}</span>
                    <span style={{ fontFamily: 'monospace', wordBreak: 'break-word' }}>{v}</span>
                  </div>
                ))}
                {disclose.warning && (
                  <div style={{ marginTop: 8, padding: '6px 8px', background: 'var(--badge-amber-bg)', borderRadius: 4, color: 'var(--badge-amber-text)', lineHeight: 1.4 }}>
                    {disclose.warning}
                  </div>
                )}
                {(disclose.lines || []).length > 0 && (
                  <details style={{ marginTop: 8 }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--text-3)', fontSize: 11 }}>Show invoice lines ({disclose.lines.length})</summary>
                    <div style={{ marginTop: 6 }}>
                      {disclose.lines.map((l, i) => (
                        <div key={i} style={{ display: 'flex', gap: 12, padding: '3px 0', borderBottom: '1px dashed var(--border)', fontSize: 11 }}>
                          <span style={{ color: 'var(--text-3)', width: 80, flexShrink: 0 }}>good_id: {l.good_id || '—'}</span>
                          <span style={{ fontFamily: 'monospace' }}>{l.qty} pc × {l.unit_price} {l.currency}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            );
          })() : null}

          {/* Audit section */}
          <div style={{ fontSize: 10, letterSpacing: '0.14em', color: 'var(--text-3)', fontWeight: 700, marginBottom: 10, marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>AUDIT</div>
          {/* HTML-parity (atlas-proforma-preview.html · convert modal AUDIT): Idempotency key row.
             The key is reserved server-side pre-call and reused by the Inbox retry proposal so wFirma
             is never double-charged. No client-minted value is fabricated. */}
          <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 14, padding: '5px 0', fontSize: 13 }} data-testid="convert-modal-idempotency">
            <span style={{ color: 'var(--text-3)' }}>Idempotency key</span>
            <span style={{ fontSize: 12 }}>
              Reserved server-side before the call
              <span style={{ color: 'var(--badge-green-text)', marginLeft: 6 }}>(reused on retry — no double-charge)</span>
            </span>
          </div>
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

Object.assign(window, { ProformaDetailPage, ConvertToInvoiceModal, PostToWFirmaModal, CancelDraftModal, PurgeDraftModal, PriorInvoiceHistoryModal, SendProformaModal });
