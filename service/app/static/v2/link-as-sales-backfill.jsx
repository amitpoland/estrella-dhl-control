// link-as-sales-backfill.jsx — V2 backfill action (proforma/sales domain).
//
// Promotes purchase packing documents to the SALES side with an operator-
// selected Customer Master contractor as the customer authority. Backend:
// POST /api/v1/packing/{batch}/link-as-sales (PR #696) persists
// client_contractor_id onto the sales chain so proforma drafts resolve by it.
//
// Authority rules:
//   1. The operator-selected Customer Master contractor_id IS the customer
//      authority and is sent as client_contractor_id (rule 1-2).
//   2. Once a contractor is selected, client_name is display-only — the picked
//      contractor's name (rule 3). The free-text name is editable ONLY in the
//      no-contractor name-fallback mode.
//   3. No contractor selected → clearly-labelled name-fallback (rule 4); the
//      free-text name is sent with a BLANK client_contractor_id.
//   4. Never infers contractor_id from text after selection (rule 5).
//
// Layer rules (Lesson F): calls PzApi transport only — no business logic, no
// auto-fetch on mount (operator opens the panel), explicit write button + toast.
// Hosted on ProformaListPage (batch-scoped, proforma domain). Uses global Btn
// from components.jsx. CSS custom properties only; data-testid on every control.

(function () {
  const { useState, useCallback } = React;

  const _vat = (c) => (c && (c.vat_eu_number || c.nip)) || '';

  // ── Customer Master search-select ───────────────────────────────────────────
  function CmContractorPicker({ docId, selected, onPick, onClear }) {
    const [q, setQ] = useState('');
    const [results, setResults] = useState(null);   // null=not searched, []=no match
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    const tid = `las-cm-picker-${docId}`;

    const search = useCallback(async () => {
      const term = (q || '').trim();
      if (!term) { setResults(null); return; }
      setBusy(true); setErr('');
      const r = await window.PzApi.listCustomerMaster({ q: term });
      setBusy(false);
      if (!r || !r.ok) { setErr((r && r.error) || 'search failed'); setResults([]); return; }
      const list = (r.data && r.data.customers) || [];
      setResults(Array.isArray(list) ? list : []);
    }, [q]);

    if (selected) {
      return (
        <div data-testid={`${tid}-selected`} style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 8, padding: '8px 10px', background: 'var(--accent-subtle)',
          border: '1px solid var(--accent-border)', borderRadius: 6,
        }}>
          <div style={{ fontSize: 12, color: 'var(--text)' }}>
            <strong>{selected.bill_to_name || '—'}</strong>
            <span style={{ color: 'var(--text-2)' }}>
              {' · '}contractor <code style={{ fontSize: 11 }}>{selected.bill_to_contractor_id}</code>
              {selected.country ? ` · ${selected.country}` : ''}
              {_vat(selected) ? ` · VAT ${_vat(selected)}` : ''}
            </span>
            <span style={{
              marginLeft: 8, padding: '1px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700,
              background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)',
              border: '1px solid var(--badge-green-border)',
            }} data-testid={`${tid}-authority`}>Customer Master authority</span>
          </div>
          <Btn variant="ghost" small onClick={onClear} data-testid={`${tid}-change`}>Change</Btn>
        </div>
      );
    }

    return (
      <div data-testid={tid}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') search(); }}
            placeholder="Search Customer Master by name…"
            data-testid={`${tid}-input`}
            style={{
              flex: 1, padding: '6px 9px', fontSize: 12, color: 'var(--text)',
              background: 'var(--surface-1)', border: '1px solid var(--border)',
              borderRadius: 6, outline: 'none',
            }}
          />
          <Btn variant="outline" small onClick={search} disabled={busy || !q.trim()}
               data-testid={`${tid}-search`}>{busy ? 'Searching…' : 'Search'}</Btn>
        </div>
        {err && <div data-testid={`${tid}-error`} style={{ fontSize: 11, color: 'var(--badge-red-text)', marginTop: 4 }}>{err}</div>}
        {results && results.length === 0 && !busy && (
          <div data-testid={`${tid}-empty`} style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 6 }}>
            No Customer Master match for “{q}”. Leave unselected to use name-fallback, or refine the search.
          </div>
        )}
        {results && results.length > 0 && (
          <div style={{ marginTop: 6, maxHeight: 180, overflow: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 6 }}>
            {results.map(c => (
              <Btn
                key={c.bill_to_contractor_id}
                variant="ghost"
                small
                onClick={() => onPick(c)}
                data-testid={`${tid}-opt-${c.bill_to_contractor_id}`}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', borderRadius: 0,
                  whiteSpace: 'normal', fontWeight: 400, color: 'var(--text)',
                  borderBottom: '1px solid var(--border-subtle)',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--row-hover)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <span>
                  <strong>{c.bill_to_name || '—'}</strong>
                  <span style={{ color: 'var(--text-2)' }}>
                    {' · '}<code style={{ fontSize: 11 }}>{c.bill_to_contractor_id}</code>
                    {c.country ? ` · ${c.country}` : ''}{_vat(c) ? ` · VAT ${_vat(c)}` : ''}
                  </span>
                </span>
              </Btn>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── Backfill panel ──────────────────────────────────────────────────────────
  function LinkAsSalesBackfill({ batchId, onLinked }) {
    const [open, setOpen] = useState(false);
    const [docs, setDocs] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [picks, setPicks] = useState({});    // docId -> CM contractor record
    const [names, setNames] = useState({});    // docId -> editable fallback name
    const [submitting, setSubmitting] = useState(false);
    const [result, setResult] = useState(null);
    const [toast, setToast] = useState(null);

    const load = useCallback(async () => {
      setLoading(true); setError(''); setResult(null);
      const r = await window.PzApi.getPackingDocuments(batchId);
      setLoading(false);
      if (!r || !r.ok) { setError((r && r.error) || 'failed to load packing documents'); setDocs([]); return; }
      const list = ((r.data && r.data.documents) || [])
        .filter(d => !(d.is_duplicate && (d.line_count || 0) === 0));   // hide ghost dups
      setDocs(list);
      const n = {};
      list.forEach(d => { n[d.id] = d.suggested_client_name || ''; });
      setNames(n);
    }, [batchId]);

    const openPanel = useCallback(() => { setOpen(true); load(); }, [load]);

    const pick = (docId, c) => setPicks(p => ({ ...p, [docId]: c }));
    const clearPick = (docId) => setPicks(p => { const n = { ...p }; delete n[docId]; return n; });
    const setName = (docId, v) => setNames(n => ({ ...n, [docId]: v }));

    // Build the mappings the operator will submit. Contractor picked → its name
    // is display-only authority; otherwise the editable free-text name + blank cid.
    const mappings = (docs || []).map(d => {
      const cm = picks[d.id];
      return {
        packing_document_id: d.id,
        client_name: cm ? (cm.bill_to_name || '') : ((names[d.id] || '').trim()),
        client_contractor_id: cm ? String(cm.bill_to_contractor_id || '') : '',
      };
    }).filter(m => (m.client_name || '').trim());

    const fallbackCount = mappings.filter(m => !m.client_contractor_id).length;
    const authorityCount = mappings.length - fallbackCount;

    const submit = useCallback(async () => {
      if (!mappings.length) { setToast({ msg: 'Select a contractor or enter a client name for at least one document.', type: 'warn' }); return; }
      setSubmitting(true); setResult(null);
      const r = await window.PzApi.linkAsSales(batchId, mappings);
      setSubmitting(false);
      if (!r || !r.ok) { setToast({ msg: (r && r.error) || 'link-as-sales failed', type: 'error' }); return; }
      setResult(r.data);
      setToast({ msg: `Linked ${r.data.linked || 0} client(s) to sales.`, type: 'success' });
      onLinked && onLinked();
    }, [mappings, batchId, onLinked]);

    if (!open) {
      return (
        <div data-testid="link-as-sales-backfill" style={{ marginBottom: 16 }}>
          <Btn variant="outline" small onClick={openPanel} data-testid="btn-open-link-as-sales-backfill">
            ＋ Backfill sales from packing documents
          </Btn>
        </div>
      );
    }

    return (
      <div data-testid="link-as-sales-backfill" style={{
        marginBottom: 16, background: 'var(--card)', border: '1px solid var(--border)',
        borderRadius: 10, boxShadow: '0 1px 3px var(--shadow)', overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 16px', background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)',
        }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Backfill sales from packing documents</div>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>
              Select the Customer Master contractor per document — contractor identity is the customer authority (drives VAT/WDT/invoice routing).
            </div>
          </div>
          <Btn variant="ghost" small onClick={() => setOpen(false)} data-testid="btn-close-link-as-sales-backfill">Close</Btn>
        </div>

        <div style={{ padding: 16 }}>
          {loading && <div data-testid="las-loading" style={{ fontSize: 12, color: 'var(--text-2)' }}>Loading packing documents…</div>}
          {error && !loading && (
            <div data-testid="las-error" style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>
              {error} <Btn variant="ghost" small onClick={load} data-testid="btn-las-retry">Retry</Btn>
            </div>
          )}
          {!loading && !error && docs && docs.length === 0 && (
            <div data-testid="las-empty" style={{ fontSize: 12, color: 'var(--text-2)' }}>
              No linkable packing documents for this batch.
            </div>
          )}

          {!loading && docs && docs.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {docs.map(d => {
                const cm = picks[d.id];
                return (
                  <div key={d.id} data-testid={`las-doc-${d.id}`} style={{
                    border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                        Packing doc <code style={{ fontSize: 11 }}>{d.id}</code> · {d.line_count} line(s)
                      </div>
                      {!cm && (
                        <span data-testid={`las-fallback-warn-${d.id}`} style={{
                          padding: '1px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                          background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)',
                          border: '1px solid var(--badge-amber-border)',
                        }}>Name-fallback — no Customer Master selected</span>
                      )}
                    </div>

                    <CmContractorPicker
                      docId={d.id}
                      selected={cm || null}
                      onPick={(c) => pick(d.id, c)}
                      onClear={() => clearPick(d.id)}
                    />

                    {!cm && (
                      <div style={{ marginTop: 8 }}>
                        <label style={{ fontSize: 11, color: 'var(--text-2)', display: 'block', marginBottom: 3 }}>
                          Free-text client name (fallback authority — no contractor selected):
                        </label>
                        <input
                          value={names[d.id] || ''}
                          onChange={e => setName(d.id, e.target.value)}
                          placeholder="Parsed/typed client name"
                          data-testid={`las-fallback-name-${d.id}`}
                          style={{
                            width: '100%', padding: '6px 9px', fontSize: 12, color: 'var(--text)',
                            background: 'var(--surface-1)', border: '1px solid var(--border)',
                            borderRadius: 6, outline: 'none',
                          }}
                        />
                      </div>
                    )}
                    {cm && (
                      <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-3)' }}>
                        Client name is display-only once a contractor is selected: <strong>{cm.bill_to_name}</strong>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Summary + submit */}
              <div data-testid="las-summary" style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                gap: 12, paddingTop: 6, borderTop: '1px solid var(--border-subtle)', flexWrap: 'wrap',
              }}>
                <div style={{ fontSize: 11, color: 'var(--text-2)' }}>
                  {authorityCount} with Customer Master authority
                  {fallbackCount > 0 && (
                    <span data-testid="las-fallback-summary" style={{ color: 'var(--badge-amber-text)' }}>
                      {' · '}{fallbackCount} name-fallback (parsed/free-text name)
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                  <Btn
                    variant="primary"
                    disabled={submitting || mappings.length === 0}
                    onClick={submit}
                    data-testid="btn-link-as-sales-submit"
                  >
                    {submitting ? 'Linking…' : `Link ${mappings.length} to sales & sync drafts`}
                  </Btn>
                  {mappings.length === 0 && (
                    <span data-testid="las-submit-disabled-reason" style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
                      Select a contractor or enter a client name for at least one document to enable.
                    </span>
                  )}
                </div>
              </div>
              {fallbackCount > 0 && (
                <div data-testid="las-fallback-banner" style={{
                  fontSize: 11, color: 'var(--badge-amber-text)', background: 'var(--badge-amber-bg)',
                  border: '1px solid var(--badge-amber-border)', borderRadius: 6, padding: '7px 10px',
                }}>
                  No Customer Master selected for {fallbackCount} document(s). These will use parsed/free-text name fallback — customer authority will resolve by name, not contractor_id.
                </div>
              )}
            </div>
          )}

          {/* Result */}
          {result && (
            <div data-testid="las-result" style={{
              marginTop: 14, padding: 12, background: 'var(--bg-subtle)',
              border: '1px solid var(--border)', borderRadius: 8,
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
                Linked {result.linked || 0} · skipped {result.failed || 0}
                {result.draft_sync && typeof result.draft_sync.created !== 'undefined' && (
                  <span style={{ fontWeight: 500, color: 'var(--text-2)' }}>
                    {' '}· drafts created {result.draft_sync.created || 0}, synced {result.draft_sync.synced || 0}
                  </span>
                )}
              </div>
              {(result.results || []).map(r => (
                <div key={r.packing_document_id} data-testid={`las-result-row-${r.packing_document_id}`} style={{ fontSize: 11, color: 'var(--text-2)', padding: '3px 0' }}>
                  <code style={{ fontSize: 10 }}>{r.packing_document_id}</code> →{' '}
                  {r.ok ? (
                    <span>
                      <strong>{r.client_name || '—'}</strong>
                      {' · '}authority:{' '}
                      <strong style={{ color: r.client_contractor_id ? 'var(--badge-green-text)' : 'var(--badge-amber-text)' }}>
                        {r.client_contractor_id ? `contractor ${r.client_contractor_id}` : 'name-fallback'}
                      </strong>
                      {typeof r.sales_lines_written !== 'undefined' ? ` · ${r.sales_lines_written} sales line(s)` : ''}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--badge-red-text)' }}>{r.reason || 'failed'}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {toast && (
          <div data-testid="las-toast" style={{
            position: 'fixed', bottom: 24, right: 24, zIndex: 1200,
            padding: '10px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600,
            background: toast.type === 'error' ? 'var(--badge-red-bg)' : toast.type === 'warn' ? 'var(--badge-amber-bg)' : 'var(--badge-green-bg)',
            color: toast.type === 'error' ? 'var(--badge-red-text)' : toast.type === 'warn' ? 'var(--badge-amber-text)' : 'var(--badge-green-text)',
            border: `1px solid ${toast.type === 'error' ? 'var(--badge-red-border)' : toast.type === 'warn' ? 'var(--badge-amber-border)' : 'var(--badge-green-border)'}`,
            boxShadow: '0 6px 20px var(--shadow-heavy)',
          }} onClick={() => setToast(null)}>{toast.msg}</div>
        )}
      </div>
    );
  }

  Object.assign(window, { LinkAsSalesBackfill, CmContractorPicker });
})();
