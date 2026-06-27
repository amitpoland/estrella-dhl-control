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

const PROFORMA_TABS = [
  { id: 'overview',         label: 'Overview'         },
  { id: 'lines',            label: 'Lines'            },
  { id: 'customer_mapping', label: 'Customer Mapping' },
  { id: 'reservation',      label: 'Reservation'      },
  { id: 'history',          label: 'History'          },
];

// ── Toolbar button ────────────────────────────────────────────────────────────
function TbBtn({ children, onClick, disabled, title, warn, style: xs, ...rest }) {
  const [hov, setHov] = React.useState(false);
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      onMouseEnter={() => !disabled && setHov(true)}
      onMouseLeave={() => setHov(false)}
      {...rest}
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
        background: 'var(--bg)',
        border: `1px solid ${warn ? 'var(--badge-amber-border)' : 'var(--border)'}`,
        borderRadius: 8, padding: '14px 16px',
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

// ── Print-preview modal ────────────────────────────────────────────────────────
// READ-ONLY. Never mutates draft state. Uses real docData/cmrData from ProformaDetailPage.
// Requires: estrella-doc-tokens.css + estrella-doc-proforma.jsx + estrella-doc-cmr.jsx loaded in index.html.
function ProformaPreviewModal({ docData, variant, onVariantChange, docType, onDocTypeChange, cmrData, packingData, onClose }) {
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
              ↓ Download PDF
            </button>
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
  }, []);

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
    })
      .then(r => {
        if (r && r.tracking_ref) {
          setResult(r);
        } else {
          const msg = (r && (r.detail || r.error)) || 'AWB creation failed — check backend logs.';
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
    return (
      <div style={overlay} onClick={() => { onSuccess && onSuccess(result); onClose(); }} data-testid="awb-generate-modal">
        <div onClick={e => e.stopPropagation()} style={card}>
          <div style={header}>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--badge-green-text)' }}>AWB Created</div>
            <button onClick={() => { onSuccess && onSuccess(result); onClose(); }}
              style={{ background: 'none', border: 'none', fontSize: 24, cursor: 'pointer', color: 'var(--text-3)', lineHeight: 1 }}
              aria-label="Close">×</button>
          </div>
          <div style={{ padding: '24px' }} data-testid="awb-generate-success">
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
              DHL Express AWB generated successfully
            </div>
            <div style={{
              padding: '16px 18px', background: 'var(--bg-subtle)', borderRadius: 8,
              border: '1px solid var(--badge-green-border)', marginBottom: 20,
            }}>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 4 }}>TRACKING NUMBER (AWB)</div>
              <div style={{
                fontSize: 22, fontWeight: 800, fontFamily: 'monospace',
                color: 'var(--badge-green-text)', letterSpacing: 1,
              }}>{result.tracking_ref}</div>
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)' }}>
                Mode: {result.mode} · State: {result.state}
                {result.simulated && <span style={{ marginLeft: 8, color: 'var(--badge-amber-text)' }}>(SIMULATED)</span>}
              </div>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 20 }}>
              Label PDF saved to server. Contact ops to retrieve or print the shipping label.
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button
                onClick={() => { navigator.clipboard && navigator.clipboard.writeText(result.tracking_ref); }}
                style={{ ...inputStyle, width: 'auto', padding: '8px 16px', cursor: 'pointer' }}
              >Copy AWB</button>
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
              <label htmlFor="awb-phone" style={labelStyle}>Phone</label>
              <input id="awb-phone" value={form.phone} onChange={e => set('phone', e.target.value)}
                style={inputStyle} data-testid="awb-field-phone" />
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

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 11, color: isPending ? 'var(--badge-amber-text, #92400e)' : 'var(--text-3)' }}>
              {_footerLabel} · batch: <code>{batchId}</code>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <Btn variant="ghost" onClick={onClose} disabled={loading}>Cancel</Btn>
              <Btn variant="primary" onClick={handleSubmit} disabled={loading || isPending} data-testid="awb-submit-btn">
                {loading ? 'Creating AWB…' : 'Create AWB'}
              </Btn>
            </div>
          </div>

        </div>
      </div>
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
  const [chargeSuggestion, setChargeSuggestion]  = React.useState(null);  // null | response obj
  const [chargesLoading,   setChargesLoading]    = React.useState(false);
  const [chargesApplying,  setChargesApplying]   = React.useState(null);  // 'freight'|'insurance'|null

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
  // Reservation blockers are surfaced at TWO distinct scopes so a BATCH-level
  // warehouse blocker (e.g. "84 packing line(s) not yet scanned" — counts the
  // whole batch's packing, NOT this draft's billed lines) is never mistaken for a
  // Draft blocker. batch_blocking_reasons (warehouse + wFirma config) block every
  // client in the batch; reservationDoc.blocking_reasons are THIS draft/client's
  // own. The CREATE GATE (reservationReady) is unchanged — this only clarifies the
  // DISPLAY (Lesson F rule 5: reflect backend truth, never re-derive it).
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
    origin:   ln.origin || (liveDraft.origin_country) || (companyProfile && companyProfile.country) || '—',
    purity:   ln.purity || '',
    currency: ln.currency || draftCurrency,
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
  // Known keys render human-readable; unknown extras keep k: v so nothing is hidden.
  const rawPt = liveDraft.payment_terms;
  const paymentTermsDisplay = (() => {
    if (!rawPt) return '—';
    if (typeof rawPt !== 'object') return String(rawPt);
    const parts = [];
    if (rawPt.method) parts.push(String(rawPt.method));
    if (rawPt.days)   parts.push(`${rawPt.days} days`);
    Object.entries(rawPt).forEach(([k, v]) => {
      if (k !== 'method' && k !== 'days' && v) parts.push(`${k}: ${v}`);
    });
    return parts.join(' · ') || '—';
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
  const _ptDays = Number(liveDraft.payment_terms_days) || 0;
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
    carrier:  liveDraft.batch_id
      ? { awb: liveDraft.batch_id, incoterm: liveDraft.incoterm || 'DAP' } : null,
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
      // Current shape: flat iban_eur / iban_usd / iban_pln + shared swift/bank_name
      return [
        companyProfile.iban_eur ? { cur: 'EUR', iban: companyProfile.iban_eur, swift: companyProfile.swift || '', bank: companyProfile.bank_name || '' } : null,
        companyProfile.iban_usd ? { cur: 'USD', iban: companyProfile.iban_usd, swift: companyProfile.swift || '', bank: companyProfile.bank_name || '' } : null,
        companyProfile.iban_pln ? { cur: 'PLN', iban: companyProfile.iban_pln, swift: companyProfile.swift || '', bank: companyProfile.bank_name || '' } : null,
      ].filter(Boolean).sort((a, b) => (b.cur === 'EUR') - (a.cur === 'EUR'));
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
      name:        'DHL Express',
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
        client_po:    pk.invoice_no || ln.client_ref || '',
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
  const stateAllowsPost    = ['draft', 'pending_local', 'approved', 'post_failed'].includes(draftState);
  const stateAllowsConvert = draftState === 'posted' || draftState === 'ready';
  const stateAllowsApprove = ['draft', 'editing', 'post_failed'].includes(draftState);
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
    ? (isBlocked ? 'Conversion blocked — see Reservation tab' : 'Post to wFirma first, then convert')
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
    setEditFields({
      remarks:       liveDraft.remarks || '',
      payment_terms: typeof liveDraft.payment_terms === 'object'
        ? JSON.stringify(liveDraft.payment_terms) : (liveDraft.payment_terms || ''),
      currency:      liveDraft.currency || 'EUR',
      exchange_rate: liveDraft.exchange_rate || '',
      incoterm:      liveDraft.incoterm || '',
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
    // payment_terms: try to parse as JSON object, fallback to string
    const origPt = typeof liveDraft.payment_terms === 'object'
      ? JSON.stringify(liveDraft.payment_terms) : (liveDraft.payment_terms || '');
    if (editFields.payment_terms !== origPt) {
      let ptVal = editFields.payment_terms;
      try { ptVal = JSON.parse(ptVal); } catch (_) { /* keep as string */ }
      patch.payment_terms = ptVal;
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
    <div data-testid="proforma-detail-root" style={{ flex: 1, overflowY: 'auto', background: 'var(--bg)', padding: '20px 24px 60px' }}>

      {/* ── Action toolbar ──────────────────────────────────────────────── */}
      <div style={{
        padding: '12px 16px', background: 'var(--card)',
        border: '1px solid var(--border)', borderRadius: '12px 12px 0 0', borderBottom: 0,
        display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap',
      }}>

        {/* Group 1 — CRUD */}
        {editMode ? (
          <React.Fragment>
            <TbBtn
              onClick={handleSaveEdit}
              disabled={editSaving}
              title="Save changes to draft header fields"
              data-testid="tb-edit-save"
            >
              {editSaving ? '⏳ Saving…' : '✓ Save'}
            </TbBtn>
            <TbBtn
              onClick={handleCancelEdit}
              disabled={editSaving}
              title="Discard changes and exit edit mode"
              data-testid="tb-edit-cancel"
            >
              ✕ Cancel Edit
            </TbBtn>
          </React.Fragment>
        ) : canEdit ? (
          <TbBtn
            onClick={handleEnterEdit}
            title="Edit draft header fields (remarks, currency, payment terms, exchange rate)"
            data-testid="tb-edit"
          >
            ✎ Edit
          </TbBtn>
        ) : null}
        <TbBtn
          onClick={() => canCancel && setShowCancelModal(true)}
          disabled={!canCancel}
          title={canCancel
            ? 'Cancel this draft — soft-cancel, no data deleted'
            : (draftState === 'cancelled' ? 'Already cancelled' : 'Cannot cancel in current state')}
          data-testid="tb-delete"
        >
          🗑 Cancel Draft
        </TbBtn>
        {draftState === 'cancelled' && (
          <TbBtn
            onClick={() => canPurge && setShowPurgeModal(true)}
            disabled={!canPurge}
            title={canPurge ? 'Permanently delete this local-only cancelled draft' : purgeDisabledReason}
            data-testid="tb-purge"
          >
            ⛔ Delete permanently
          </TbBtn>
        )}
        <TbBtn
          onClick={handleDuplicate}
          disabled={cloning}
          title="Clone this draft as a new unposted draft"
          data-testid="tb-duplicate"
        >
          {cloning ? '⏳' : '⎘'} {cloning ? 'Cloning…' : 'Duplicate'}
        </TbBtn>
        <TbBtn
          onClick={handleApprove}
          disabled={!canApprove || approving}
          title={canApprove
            ? 'Mark this draft as approved — locks lines before posting to wFirma'
            : approveDisabledReason}
          data-testid="tb-approve"
        >
          {approving ? '⏳ Approving…' : '✓ Approve'}
        </TbBtn>
        {approveError && (
          <span style={{ color: 'var(--badge-red-text)', fontSize: 11, maxWidth: 180 }}>{approveError}</span>
        )}

        <TbSep />

        {/* Group 2 — wFirma write actions */}
        <TbBtn
          onClick={() => setShowPostModal(true)}
          disabled={!canPost}
          title={canPost
            ? 'Post this draft to wFirma as a proforma invoice'
            : postDisabledReason}
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
            : convertDisabledReason}
          data-testid="tb-convert"
        >
          ⚠ Convert to Invoice
        </TbBtn>

        <TbSep />

        {/* Group 3 — Output */}
        <TbBtn
          onClick={() => setShowPreview(true)}
          title="Preview print layout — Proforma or CMR · Classic / Modern / Bold"
          data-testid="tb-preview"
        >
          ◫ Preview
        </TbBtn>
        <TbBtn
          onClick={handleDownloadPdf}
          disabled={!canPrint}
          title={canPrint
            ? 'Open wFirma proforma PDF in new tab'
            : 'PDF only available after posting to wFirma'}
          data-testid="proforma-detail-download-pdf"
        >
          ⎙ Print
        </TbBtn>
        <TbBtn
          onClick={() => setShowSendModal(true)}
          disabled={!canSend}
          title={canSend
            ? 'Send proforma PDF to customer via email'
            : (sendDisabledReason || 'Email send not available')}
          data-testid="tb-send"
        >
          ➤ Send
        </TbBtn>
        <TbBtn
          disabled
          title={
            'Document-package generation (proforma PDF · packing list · CMR · CN23) is not yet wired — ' +
            'backend gap M4: POST /api/v1/proforma/draft/{id}/generate-documents (see BACKEND_GAP_REGISTER.md §2, priority LOW). ' +
            'For now use ◫ Preview to view the layouts and ⎙ Print for the wFirma proforma PDF.'
          }
          data-testid="tb-generate"
        >
          ⚙ Generate ▾
        </TbBtn>
        {/* M8 — DHL Express AWB generation. WIRED: POST /api/v1/carrier/{batch_id}/shipment.
            Requires CARRIER_API_STATUS=live + DHL credentials in environment. */}
        <TbBtn
          onClick={() => setShowAwbModal(true)}
          disabled={!batchId}
          title={batchId
            ? 'Generate DHL Express AWB — opens shipment form'
            : 'No batch loaded — open a proforma with a batch to generate AWB'}
          data-testid="tb-awb-generate"
        >
          ⚡ AWB Generate
        </TbBtn>

        <TbSep />

        {/* Group 4 — History / Intelligence */}
        <TbBtn
          onClick={() => contractorId && setShowInvoiceHistory(true)}
          disabled={!contractorId}
          title={contractorId
            ? 'View prior invoice history from wFirma for this customer'
            : 'Backend/customer mapping pending: wFirma contractor ID missing'}
          data-testid="tb-invoice-history"
        >
          📋 Prior Invoices
        </TbBtn>
        <TbBtn
          disabled
          title="More actions"
          data-testid="tb-more"
        >
          ⋯
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

      {/* ── PROFORMA STATUS HEADER (Sprint 03.1-A) — persistent, always visible.
          PURE RE-PRESENTATION of existing backend-authoritative props/state
          (readinessPost / customer / pieces / lifecycle). No authority computed
          here — readiness comes from the backend `ready` field only. */}
      {(() => {
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
            borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
            borderTop: '1px solid var(--border)',
            padding: '12px 24px',
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
      })()}

      {/* ── UNIFIED "WHAT'S BLOCKING" PANEL (Sprint 03.1-B) — consolidates the
          blocker sources that were previously scattered (readiness post-blockers
          in the main panel + export blockers / blocking reasons surfaced only in
          the Overview & Reservation tabs), each tagged by the action it gates.
          PURE RE-PRESENTATION of existing arrays — no new authority, no new
          computation. The interactive readiness panel below remains for the
          design-ambiguity resolver (capability preserved). */}
      {(() => {
        const seen = new Set();
        const rows = [];
        const add = (reason, repair, gates) => {
          if (!reason) return;
          const key = `${reason}::${gates}`;
          if (seen.has(key)) return;
          seen.add(key);
          rows.push({ reason, repair: repair || null, gates });
        };
        // Canonical readiness only (readinessPost / readinessApprove). The
        // Reservation / Export rows previously fed from the stale preview are
        // gone — readinessPost.blockers already carries the reservation + wFirma
        // PZ/export blockers (post intent), so they appear here under Post/Convert.
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
      })()}

      {/* ── READINESS PANEL — single backend authority (split-authority fix) ──
          Renders the SAME gate the backend enforces on approve/post/convert:
          every blocker with its exact repair action (Lesson M), plus the
          design-ambiguity selector (operator picks the exact product_code per
          design_no — persisted batch-scoped and audited; requirement 4). */}
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
          {(readinessPost.blockers || []).map((b, i) => (
            <div key={i} style={{ fontSize: 12, marginBottom: 4 }} data-testid={`readiness-blocker-${i}`}>
              <span style={{ color: 'var(--badge-red-text)' }}>• {b.reason}</span>
              <div style={{ color: 'var(--text-dim, var(--text))', opacity: 0.75, paddingLeft: 14 }}>
                Fix: {b.repair_action}
              </div>
            </div>
          ))}
          {/* WDT EU-VAT repair — explicit "save to Customer Master" action. The
              VAT is on file (nip) but blank in the canonical vat_eu_number field
              the WDT gate reads; this writes it there on operator confirm. The
              gate stays blocked until saved — no tax bypass. */}
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

      {/* ── Product-code billing evidence (display-only, surfaces #686) ────────
          Renders the readiness gate's duplicate_product_codes: every purchase lot
          (product_code) billed across >1 draft line, with billed vs available
          packing quantity. A product_code is ONE purchase-invoice lot that may
          legitimately span several designs/pieces — billing within the available
          quantity is fine (shown here for transparency, never hidden); billing
          MORE than available is an over-bill (double-bill) which the backend gate
          ALSO raises as a blocker above. Pure reflection of the backend authority
          — no local computation, no write actions (Lesson F rule 5). */}
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
            // product_code can contain '/' (e.g. EJL/26-27/299-2) — slugify for a
            // selector-safe data-testid; the React key keeps the raw value.
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
              </div>
            );
          })}
        </div>
      )}

      {/* ── Party cards (SELLER / BUYER / RECIPIENT) ────────────────────── */}
      <div style={{
        background: 'var(--card)',
        borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
        padding: '22px 24px 12px',
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16,
      }}>
        <div style={{ display: 'contents' }}>

          {/* SELLER — authority: GET /api/v1/settings/company-profile */}
          <ProformaPartyCard
            title="SELLER"
            name={exporter.name}
            lines={[exporter.address, exporter.country]}
            footer={`VAT EU: ${exporter.vatEu}`}
            data-testid="party-seller"
          />

          {/* BUYER — authority: draft buyer_override (name/vat_id/address) */}
          <ProformaPartyCard
            title="BUYER"
            name={customer.name}
            lines={[customer.address, customer.country]}
            footer={customer.vatEuFromNip
              ? `VAT EU: ${customer.vatEu} · on file (not yet saved as EU VAT)`
              : `VAT EU: ${customer.vatEu}`}
            warn={!customer.wfirmaId}
            warnMsg={!customer.wfirmaId ? 'Not mapped to wFirma customer' : null}
            mappedMsg={customer.wfirmaId
              ? (customer.wfirmaName ? `✓ Mapped: ${customer.wfirmaName}` : '✓ Mapped to wFirma')
              : null}
            data-testid="party-buyer"
          />

          {/* RECIPIENT — ship_to_override if set, otherwise same as buyer */}
          <ProformaPartyCard
            title="RECIPIENT"
            name={shipTo.name}
            lines={[shipTo.address, shipTo.country]}
            footer={liveDraft.ship_to_override && liveDraft.ship_to_override.name
              ? 'Ship-to override' : 'Same as Buyer'}
            footerMuted
            data-testid="party-recipient"
          />
        </div>
      </div>

      {/* ── Address authority bar ──────────────────────────────────────────── */}
      {(() => {
        const addrSource = bo._source === 'customer_master' ? 'customer_master'
          : (bo.name || bo.street) ? 'manual' : 'none';
        const addrSourceLabel = addrSource === 'customer_master'
          ? { text: 'Customer Master', color: 'var(--accent)' }
          : addrSource === 'manual'
          ? { text: 'Manual', color: 'var(--text-2)' }
          : { text: 'Not set', color: 'var(--text-3, #aaa)' };
        const lockedForEdit = !canEdit;
        const hasOverride = !!(bo.name || bo.street);
        return (
          <div data-testid="address-authority-bar" style={{
            background: 'var(--card)',
            borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
            borderBottom: '1px solid var(--border)',
            padding: '8px 24px',
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
              <span data-testid="addr-apply-error" style={{ fontSize: 12, color: 'var(--danger, #c0392b)', marginLeft: 4 }}>
                {addrApplyError}
              </span>
            )}
          </div>
        );
      })()}

      {/* ── Tab strip ──────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: 0, padding: '0 24px',
        background: 'var(--card)',
        borderLeft: '1px solid var(--border)', borderRight: '1px solid var(--border)',
        borderBottom: '1px solid var(--border)',
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
      <div style={{
        background: 'var(--card)',
        border: '1px solid var(--border)', borderTop: 0,
        borderRadius: '0 0 12px 12px',
        padding: '24px',
        minHeight: 320,
        overflow: 'auto',
        boxShadow: '0 4px 12px var(--shadow)',
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
            <ServiceChargesPanel
              charges={liveDraft.service_charges || []}
              canEdit={canEdit}
              draftState={draftState}
              suggestion={chargeSuggestion}
              chargesLoading={chargesLoading}
              chargesApplying={chargesApplying}
              onFetchSuggestions={handleFetchChargeSuggestions}
              onApplyCharge={handleApplyCharge}
              onDismissSuggestion={() => setChargeSuggestion(null)}
              onDeleteCharge={(chargeId) => {
                const id = liveDraft.id || (draft && draft.id);
                window.PzApi.deleteServiceCharge(id, chargeId)
                  .then(r => r && r.ok && draftHook && draftHook.reload && draftHook.reload());
              }}
            />
          </React.Fragment>
        )}
        {activeTab === 'lines' && <ProformaLinesTab lines={lines} currency={draftCurrency} />}
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
      {showAwbModal && batchId && (
        <AwbGenerateModal
          batchId={batchId}
          prefill={{
            // Value — from draft authority
            declared_value:     detail.total_eur ? detail.total_eur.toFixed(2) : '',
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
            // References — from draft
            customer_reference: (draft && draft.doc_no) || (liveDraft && liveDraft.proforma_number) || '',
            shipment_reference: batchId || '',
            // Description — default; operator overrides in modal
            description:        'Jewellery',
          }}
          onClose={() => setShowAwbModal(false)}
          onSuccess={() => setShowAwbModal(false)}
        />
      )}
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
    </div>
  );
}

// ── PR B — Service charges panel ────────────────────────────────────────────
function ServiceChargesPanel({ charges, canEdit, draftState, suggestion, chargesLoading, chargesApplying, onFetchSuggestions, onApplyCharge, onDismissSuggestion, onDeleteCharge }) {
  const fmtAmt = (amt, cur) => `${Number(amt).toFixed(2)} ${cur || ''}`;
  const existingTypes = (charges || []).map(c => (c.charge_type || '').toLowerCase());

  return (
    <div data-testid="service-charges-panel" style={{ marginTop: 24, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Service Charges</span>
        {canEdit && (
          <button
            data-testid="btn-suggest-charges"
            disabled={chargesLoading}
            title="Load freight and insurance suggestions from Customer Master"
            onClick={onFetchSuggestions}
            style={{
              fontSize: 12, padding: '2px 10px',
              background: 'var(--bg)', border: '1px solid var(--border)',
              borderRadius: 4, cursor: chargesLoading ? 'wait' : 'pointer',
              color: 'var(--text-2)',
            }}
          >{chargesLoading ? '⏳ Loading…' : '↓ Suggest from Customer Master'}</button>
        )}
        {!canEdit && (
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
            (read-only — draft is in '{draftState}' state)
          </span>
        )}
      </div>

      {/* Existing charges */}
      {charges.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>No service charges added.</div>
      )}
      {charges.map(c => (
        <div key={c.charge_id} data-testid={`charge-row-${c.charge_type}`} style={{
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
      ))}

      {/* Suggestion panel */}
      {suggestion && !suggestion.error && (
        <div data-testid="charge-suggestion-panel" style={{
          marginTop: 8, padding: '10px 12px',
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 6,
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-2)' }}>
            Suggestions (Customer Master, {suggestion.draft_currency || '—'}):
          </div>
          {suggestion.applyError && (
            <div data-testid="charge-apply-error" style={{ fontSize: 12, color: 'var(--danger, #c0392b)', marginBottom: 6 }}>
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
        <div data-testid="charge-suggestion-error" style={{ fontSize: 12, color: 'var(--danger, #c0392b)', marginTop: 6 }}>
          {suggestion.error}
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
          <div data-testid="buyer-edit-error" style={{ fontSize: 12, color: 'var(--danger, #c0392b)', marginBottom: 8 }}>
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

// ── Overview tab ──────────────────────────────────────────────────────────────
function ProformaOverviewTab({ detail, lines, fxRate, vatResolution, blockingReasons, exportBlockers, editMode, editFields, onEditField, editError }) {
  const totalEur = lines.reduce((s, l) => s + l.netEur, 0);
  const currency = detail.currency || 'EUR';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

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

      {/* KV grid — 4 columns, all values from backend authority */}
      {/* In edit mode: editable fields for remarks, currency, exchange_rate, payment_terms */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px 28px' }}>
        <KvItem k="Number" v={detail.wfirma_proforma_fullnumber} mono />
        <KvItem k="Shipment" v={detail.batch_id} mono />
        <KvItem k="KSeF" v={detail.ksef_number} muted={!detail.ksef_number} />
        {editMode
          ? <EditableKvItem k="Payment terms" value={editFields.payment_terms || ''} onChange={v => onEditField('payment_terms', v)} />
          : <KvItem k="Payment method" v={detail.paymentTerms} />
        }

        <KvItem k="Issue date" v={detail.created_at ? detail.created_at.slice(0, 10) : null} mono />
        <KvItem k="Payment due" v={detail.payment_due_date} mono />
        <KvItem k="Sale date" v={detail.sale_date} mono />
        <KvItem k="Paid" v={`0.00 ${currency}`} muted />

        <KvItem k="Amount due" v={`${totalEur.toFixed(2)} ${currency}`} />
        <KvItem k="Accounting scheme" v={detail.accounting_scheme || 'Standard'} />
        <KvItem k="JPK codes" v={detail.jpk_codes || 'none'} muted={!detail.jpk_codes} />
        {editMode
          ? <EditableKvItem k="Exchange rate" value={editFields.exchange_rate || ''} onChange={v => onEditField('exchange_rate', v)} />
          : <KvItem
              k={`Total · FX ${fxRate ? fxRate.toFixed(4) : '—'} PLN`}
              v={`${totalEur.toFixed(2)} ${currency}`}
            />
        }

        <KvItem k="Warehouse" v={detail.warehouse || 'Main'} />
        <KvItem k="wFirma proforma ID" v={detail.wfirma_proforma_id} mono />
        <KvItem k="wFirma invoice ID" v={detail.wfirma_invoice_id} mono />
        {editMode
          ? <EditableKvItem k="Currency" value={editFields.currency || ''} onChange={v => onEditField('currency', v)} />
          : <KvItem k="Source" v={detail.clone_source || detail.source_description || detail.source || '—'} />
        }
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
    </div>
  );
}

// ── Lines tab ─────────────────────────────────────────────────────────────────
function ProformaLinesTab({ lines, currency }) {
  // Amount columns are labelled with the DRAFT currency (e.g. USD), never a
  // hardcoded EUR. The underlying line fields are named unitEur/netEur for
  // historical reasons but carry the draft-currency amount.
  const cur = currency || 'EUR';
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 12 }}>
        Line items ({lines.length})
      </div>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              {['#', 'SKU', 'DESCRIPTION', 'HS CODE', 'ORIGIN', 'QTY', `UNIT ${cur}`, `NET ${cur}`].map((h, i) => (
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
              <td colSpan="7" style={{ padding: '11px 12px', textAlign: 'right', fontSize: 12, fontWeight: 700 }}>Total · {cur}</td>
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

Object.assign(window, { ProformaDetailPage, ConvertToInvoiceModal, PostToWFirmaModal, CancelDraftModal, PurgeDraftModal, PriorInvoiceHistoryModal, SendProformaModal });
