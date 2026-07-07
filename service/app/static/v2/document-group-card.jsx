// document-group-card.jsx — V2 reusable, priority-ordered document-group renderer.
// Exports: window.DOCUMENT_GROUPS, window.DocumentGroupCard, window.SourceBundleCard,
//          window.documentTypeLabel
//
// Renders a NAMED, priority-ordered group of shipment documents from
// window.useShipmentDocuments. Future groups (customs, shipping, generated) reuse
// the SAME renderer by adding a key to DOCUMENT_GROUPS — no new component. Loading
// and error states are ISOLATED to this card and never gate any other UI.
// Read-only; display-only; never writes. IIFE-scoped.
(function () {
  const DOCUMENT_GROUPS = {
    source: {
      label: 'Source Bundle',
      types: ['purchase_invoice', 'purchase_packing_list', 'sales_packing_list'],
    },
    // Future: customs / shipping / generated — add a key here; reuse DocumentGroupCard.
  };

  const _TYPE_LABELS = {
    purchase_invoice: 'Purchase invoice', sales_invoice: 'Sales invoice',
    purchase_packing_list: 'Purchase packing list', sales_packing_list: 'Sales packing list',
  };
  // Coerce any object-valued enriched field to a safe primitive (avoid React #31).
  const _s = (v) => (v == null || typeof v === 'object') ? '' : v;
  function documentTypeLabel(t) { return _TYPE_LABELS[t] || (_s(t) || 'Document'); }

  const _box = { padding: '12px 16px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8 };

  function DocumentGroupCard({ groupKey, batchId }) {
    const group = DOCUMENT_GROUPS[groupKey];
    const { documents, loading, error } = window.useShipmentDocuments(batchId);
    if (!group) return null;

    // Index by document_type (first match per type wins; render order = group.types priority).
    const byType = {};
    (documents || []).forEach((d) => {
      const t = _s(d && d.document_type);
      if (t && !byType[t]) byType[t] = d;
    });

    return (
      <div data-testid={`pf-source-bundle-${groupKey}`} style={{ marginTop: 4, marginBottom: 14 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>{group.label}</div>
        {loading && (
          <div data-testid="pf-source-bundle-loading" style={{ ..._box, fontSize: 12, color: 'var(--text-3)' }}>Loading source bundle…</div>
        )}
        {!loading && error && (
          <div data-testid="pf-source-bundle-error" style={{ ..._box, fontSize: 11.5, color: 'var(--badge-amber-text)' }}>Source bundle unavailable · {_s(error)}</div>
        )}
        {!loading && !error && (
          <div style={{ ..._box, padding: 0, overflow: 'hidden' }}>
            {group.types.map((t, i) => {
              const d = byType[t];
              const last = i === group.types.length - 1;
              return (
                <div key={t} data-testid="pf-source-bundle-row"
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '10px 14px', borderBottom: last ? 'none' : '1px solid var(--border)' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: d ? 'var(--text)' : 'var(--text-3)' }}>{documentTypeLabel(t)}</div>
                    {d
                      ? <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                          {[_s(d.invoice_no) || _s(d.file_name) || _s(d.suggested_client_name), (d.line_count != null ? `${d.line_count} lines` : null)].filter(Boolean).join(' · ') || '—'}
                        </div>
                      : <div data-testid="pf-source-bundle-missing" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>— not uploaded</div>}
                  </div>
                  {d && _s(d.review_state) && (
                    <span data-testid="pf-source-bundle-review" style={{ flexShrink: 0, fontSize: 10.5, fontWeight: 700, padding: '2px 8px', borderRadius: 999, color: 'var(--text-2)', border: '1px solid var(--border)' }}>{_s(d.review_state)}</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  function SourceBundleCard({ batchId }) {
    return <DocumentGroupCard groupKey="source" batchId={batchId} />;
  }

  window.DOCUMENT_GROUPS   = DOCUMENT_GROUPS;
  window.DocumentGroupCard = DocumentGroupCard;
  window.SourceBundleCard  = SourceBundleCard;
  window.documentTypeLabel = documentTypeLabel;
})();
