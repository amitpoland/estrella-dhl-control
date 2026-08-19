// advance-packing.jsx — pre-shipment (advance) packing lists, operator surface.
//
// Two mounts, one component file, no new nav entry and no new page:
//
//   window.AdvancePackingHub   → Shipments page.  Upload a list the supplier
//                                sent BEFORE dispatch, and see which lists are
//                                still waiting for their shipment.
//   window.AdvancePackingCard  → Shipment Detail.  Link an announced list to
//                                THIS shipment, then read the variance.
//
// Calls /api/v1/packing-advance only.  Everything an advance list must never
// do is enforced server-side (no product_code, no scan_code, no inventory
// seed, no wFirma, no PZ); this surface deliberately offers no affordance for
// any of them, and shows expected quantities as ANNOUNCED, never as stock.

(function () {
  'use strict';

  // The V2 shell deliberately does NOT load dashboard-shared.js -- index.html
  // ships an apiFetch-only EstrellaShared shim and puts the visual atoms on
  // window (same as inventory-page.jsx). Destructuring the atoms off
  // EstrellaShared here yielded undefined components and React error #130.
  const { apiFetch } = window.EstrellaShared;
  const { Btn, Card, EmptyState } = window;

  const STATUS_STYLE = {
    match:   { bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   label: 'match' },
    short:   { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   label: 'short' },
    over:    { bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   label: 'over' },
    missing: { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     label: 'not shipped' },
    extra:   { bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     label: 'not announced' },
  };

  function StatusPill({ status }) {
    const s = STATUS_STYLE[status] || { bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', label: status };
    return (
      <span style={{ background: s.bg, color: s.text, borderRadius: 4, padding: '1px 6px',
                     fontSize: 10, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        {s.label}
      </span>
    );
  }

  function _fmtDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString('pl-PL', {
        timeZone: 'Europe/Warsaw', hour12: false,
        day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
      });
    } catch (_) { return String(iso).slice(0, 16).replace('T', ' '); }
  }

  function _qty(n) {
    const v = Number(n);
    if (!isFinite(v)) return '—';
    return Number.isInteger(v) ? String(v) : v.toFixed(2);
  }

  function _err(e) {
    return (e && e.message) ? e.message : 'Request failed.';
  }

  // ── Reconciliation table ───────────────────────────────────────────────────
  // Announced (advance) vs shipped (final purchase packing), by design_no.
  // This is a COMMERCIAL comparison. It never claims anything about what was
  // physically received — warehouse_receipt owns accepted/shortage/overage —
  // so the column is labelled "Shipped", not "Received".
  function Reconciliation({ documentId }) {
    const [data,    setData]    = React.useState(null);
    const [error,   setError]   = React.useState('');
    const [loading, setLoading] = React.useState(true);
    const [onlyVariance, setOnlyVariance] = React.useState(true);

    const load = React.useCallback(() => {
      setLoading(true);
      apiFetch(`/api/v1/packing-advance/${encodeURIComponent(documentId)}/reconciliation`)
        .then(d => { setData(d); setError(''); })
        .catch(e => setError(_err(e)))
        .then(() => setLoading(false));
    }, [documentId]);

    React.useEffect(load, [load]);

    if (loading) return <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Reconciling…</div>;
    if (error)   return <div style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>{error}</div>;
    if (!data)   return null;

    const s    = data.summary || {};
    const all  = data.lines || [];
    const rows = onlyVariance ? all.filter(l => l.status !== 'match') : all;

    return (
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center',
                      marginBottom: 10, fontSize: 12, color: 'var(--text-2)' }}>
          <span><b style={{ color: 'var(--text)' }}>{s.designs}</b> designs</span>
          <span>announced <b style={{ color: 'var(--text)' }}>{_qty(s.expected_total)}</b></span>
          <span>shipped <b style={{ color: 'var(--text)' }}>{_qty(s.actual_total)}</b></span>
          {s.fully_matched
            ? <StatusPill status="match" />
            : Object.keys(s.by_status || {}).filter(k => k !== 'match')
                .map(k => <StatusPill key={k} status={k} />)}
          <label style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
            <input type="checkbox" checked={onlyVariance}
                   onChange={e => setOnlyVariance(e.target.checked)} />
            Variances only
          </label>
          <Btn small variant="outline" onClick={load}>↻</Btn>
        </div>

        {rows.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
            {onlyVariance
              ? 'Every announced design was shipped in the announced quantity.'
              : 'No lines.'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--text-3)', fontSize: 10,
                             textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  <th style={{ padding: '4px 8px 4px 0' }}>Design</th>
                  <th style={{ padding: '4px 8px', textAlign: 'right' }}>Announced</th>
                  <th style={{ padding: '4px 8px', textAlign: 'right' }}>Shipped</th>
                  <th style={{ padding: '4px 8px', textAlign: 'right' }}>Variance</th>
                  <th style={{ padding: '4px 0 4px 8px' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(l => (
                  <tr key={l.design_no} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '5px 8px 5px 0', fontFamily: 'monospace' }}>{l.design_no || '—'}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right' }}>{_qty(l.expected_qty)}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right' }}>{_qty(l.actual_qty)}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right',
                                 color: l.variance_qty === 0 ? 'var(--text-3)' : 'var(--text)' }}>
                      {l.variance_qty > 0 ? '+' : ''}{_qty(l.variance_qty)}
                    </td>
                    <td style={{ padding: '5px 0 5px 8px' }}><StatusPill status={l.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-3)', lineHeight: 1.5 }}>
          Announced vs shipped, by design. This compares two commercial documents —
          it does not assert physical receipt. Accepted, shortage and overage
          quantities stay with the warehouse receipt.
        </div>
      </div>
    );
  }

  // ── Shipment Detail card ───────────────────────────────────────────────────
  function AdvancePackingCard({ batchId }) {
    const [linkedDoc,   setLinkedDoc]   = React.useState(null);
    const [candidates,  setCandidates]  = React.useState([]);
    const [chosen,      setChosen]      = React.useState('');
    const [busy,        setBusy]        = React.useState(false);
    const [error,       setError]       = React.useState('');
    const [loading,     setLoading]     = React.useState(true);

    const load = React.useCallback(() => {
      if (!batchId) return;
      setLoading(true);
      Promise.all([
        apiFetch('/api/v1/packing-advance?linked=true').catch(() => null),
        apiFetch('/api/v1/packing-advance?linked=false').catch(() => null),
      ]).then(([linked, unlinked]) => {
        const mine = ((linked && linked.documents) || [])
          .filter(d => d.linked_batch_id === batchId);
        setLinkedDoc(mine[0] || null);
        setCandidates((unlinked && unlinked.documents) || []);
        setError('');
      }).catch(e => setError(_err(e))).then(() => setLoading(false));
    }, [batchId]);

    React.useEffect(load, [load]);

    const doLink = () => {
      if (!chosen) return;
      setBusy(true); setError('');
      apiFetch(`/api/v1/packing-advance/${encodeURIComponent(chosen)}/link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batchId }),
      }).then(() => { setChosen(''); load(); })
        .catch(e => setError(_err(e)))
        .then(() => setBusy(false));
    };

    return (
      <div data-testid="advance-packing-card">
      <Card style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
            📥 Advance Packing List
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
            what the supplier announced before dispatch
          </div>
        </div>

        {error && (
          <div style={{ fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 8 }}>{error}</div>
        )}

        {loading ? (
          <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading…</div>
        ) : linkedDoc ? (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 10 }}>
              Linked to <span style={{ fontFamily: 'monospace' }}>{linkedDoc.batch_id}</span>
              {' · '}{linkedDoc.line_count} announced lines
              {' · '}uploaded {_fmtDate(linkedDoc.created_at)}
            </div>
            <Reconciliation documentId={linkedDoc.id} />
          </div>
        ) : candidates.length === 0 ? (
          <EmptyState state="empty"
            message="No advance list is waiting. Advance lists are uploaded on the Shipments page, before the goods ship." />
        ) : (
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>
              Record which announced list this shipment fulfils. The link is set
              once and neither document is rewritten.
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <select value={chosen} onChange={e => setChosen(e.target.value)}
                      disabled={busy}
                      style={{ flex: '1 1 320px', minWidth: 0, padding: '6px 8px', fontSize: 12,
                               fontFamily: 'inherit', borderRadius: 6,
                               border: '1px solid var(--border)', background: 'var(--surface)',
                               color: 'var(--text)' }}>
                <option value="">Select an announced list…</option>
                {candidates.map(d => (
                  <option key={d.id} value={d.id}>
                    {d.batch_id} · {d.line_count} lines · {_fmtDate(d.created_at)}
                  </option>
                ))}
              </select>
              <Btn small onClick={doLink} disabled={!chosen || busy}>
                {busy ? 'Linking…' : 'Link to this shipment'}
              </Btn>
            </div>
          </div>
        )}
      </Card>
      </div>
    );
  }

  // ── Shipments-page hub ─────────────────────────────────────────────────────
  function AdvancePackingHub({ onToast }) {
    const [docs,      setDocs]      = React.useState([]);
    const [loading,   setLoading]   = React.useState(true);
    const [uploading, setUploading] = React.useState(false);
    const [error,     setError]     = React.useState('');
    const [open,      setOpen]      = React.useState(null);   // expanded doc id
    const [showGone,  setShowGone]  = React.useState(false);  // include withdrawn
    const [wdDoc,     setWdDoc]     = React.useState(null);   // doc being withdrawn
    const [wdReason,  setWdReason]  = React.useState('');
    const [wdBusy,    setWdBusy]    = React.useState(false);

    const load = React.useCallback(() => {
      setLoading(true);
      apiFetch('/api/v1/packing-advance' + (showGone ? '?include_withdrawn=true' : ''))
        .then(d => { setDocs((d && d.documents) || []); setError(''); })
        .catch(e => setError(_err(e)))
        .then(() => setLoading(false));
    }, [showGone]);

    React.useEffect(load, [load]);

    const upload = (file) => {
      if (!file) return;
      setUploading(true); setError('');
      const fd = new FormData();
      fd.append('file', file);
      apiFetch('/api/v1/packing-advance/upload', {
        method: 'POST',
        body: fd,
      }).then(r => {
        if (onToast) onToast(`Advance list stored: ${r.rows_stored} of ${r.rows_parsed} lines · ${r.batch_id}`);
        load();
      }).catch(e => setError(_err(e)))
        .then(() => setUploading(false));
    };

    // Withdrawing is the operator's own repair for a wrong upload or a wrong
    // link — the alternative was SQL. It retracts, it does not delete, so the
    // reason is mandatory and the corrected list is a fresh upload.
    const withdraw = (id) => {
      const reason = wdReason.trim();
      if (!reason) return;
      setWdBusy(true); setError('');
      apiFetch(`/api/v1/packing-advance/${encodeURIComponent(id)}/withdraw`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      }).then(() => {
        if (onToast) onToast('Advance list withdrawn. Upload the corrected list when you have it.');
        setWdDoc(null); setWdReason('');
        load();
      }).catch(e => setError(_err(e)))
        .then(() => setWdBusy(false));
    };

    const waiting = docs.filter(d => !d.linked_batch_id && !d.withdrawn_reason).length;

    return (
      <div data-testid="advance-packing-hub">
      <Card style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
            📥 Advance Packing Lists
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-3)', flex: '1 1 240px' }}>
            Goods announced before dispatch. Expected quantities only — no stock,
            no product codes, no barcodes until the real shipment arrives.
          </div>
          <label style={{ fontSize: 11, color: 'var(--text-2)', display: 'inline-flex',
                          alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={showGone}
                   onChange={e => setShowGone(e.target.checked)} />
            show withdrawn
          </label>
          <Btn small variant="outline" onClick={load} disabled={loading || uploading}>↻</Btn>
          <label style={{ cursor: uploading ? 'not-allowed' : 'pointer' }}>
            <input type="file" accept=".pdf,.xlsx,.xls" disabled={uploading}
                   style={{ display: 'none' }}
                   onChange={e => { upload(e.target.files && e.target.files[0]); e.target.value = ''; }} />
            <span style={{ display: 'inline-block', padding: '5px 10px', fontSize: 12, fontWeight: 600,
                           borderRadius: 6, border: '1px solid var(--accent)',
                           color: uploading ? 'var(--text-3)' : 'var(--accent)',
                           pointerEvents: uploading ? 'none' : 'auto' }}>
              {uploading ? 'Uploading…' : '↑ Upload advance list'}
            </span>
          </label>
        </div>

        {error && (
          <div style={{ fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 8 }}>{error}</div>
        )}

        {loading ? (
          <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading…</div>
        ) : docs.length === 0 ? (
          <EmptyState state="empty"
            message="No advance packing lists. Upload the list a supplier sends before the goods ship — it records expected quantities and waits for its shipment." />
        ) : (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 8 }}>
              {docs.length} list{docs.length === 1 ? '' : 's'}
              {waiting > 0 && <> · <b style={{ color: 'var(--text)' }}>{waiting}</b> waiting for a shipment</>}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--text-3)', fontSize: 10,
                               textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    <th style={{ padding: '4px 8px 4px 0' }}>Advance batch</th>
                    <th style={{ padding: '4px 8px', textAlign: 'right' }}>Lines</th>
                    <th style={{ padding: '4px 8px' }}>Uploaded</th>
                    <th style={{ padding: '4px 8px' }}>Shipment</th>
                    <th style={{ padding: '4px 0 4px 8px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map(d => (
                    <React.Fragment key={d.id}>
                      <tr style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ padding: '5px 8px 5px 0', fontFamily: 'monospace' }}>
                          {d.batch_id}
                          {d.withdrawn_reason && (
                            <div style={{ fontFamily: 'inherit', fontSize: 10, color: 'var(--badge-red-text)' }}>
                              withdrawn — {d.withdrawn_reason}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '5px 8px', textAlign: 'right' }}>{d.line_count}</td>
                        <td style={{ padding: '5px 8px', color: 'var(--text-2)' }}>{_fmtDate(d.created_at)}</td>
                        <td style={{ padding: '5px 8px', fontFamily: 'monospace' }}>
                          {d.linked_batch_id
                            ? d.linked_batch_id
                            : <span style={{ fontFamily: 'inherit', color: 'var(--text-3)' }}>
                                {d.withdrawn_reason
                                  ? 'never linked'
                                  : 'waiting — link it from the shipment'}
                              </span>}
                        </td>
                        <td style={{ padding: '5px 0 5px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                          {d.linked_batch_id && (
                            <Btn small variant="outline"
                                 onClick={() => setOpen(open === d.id ? null : d.id)}>
                              {open === d.id ? 'Hide' : 'Reconcile'}
                            </Btn>
                          )}
                          {!d.withdrawn_reason && (
                            <Btn small variant="outline" style={{ marginLeft: 6 }}
                                 onClick={() => { setWdDoc(wdDoc === d.id ? null : d.id); setWdReason(''); }}>
                              {wdDoc === d.id ? 'Keep' : 'Withdraw'}
                            </Btn>
                          )}
                        </td>
                      </tr>
                      {wdDoc === d.id && (
                        <tr>
                          <td colSpan={5} style={{ padding: '6px 0 10px' }}>
                            {/* Capped: the Shipments page is wider than the
                                viewport, and a flexible input would push the
                                confirm button off-screen. */}
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center',
                                          flexWrap: 'wrap', maxWidth: 820 }}>
                              <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
                                Why is this list being withdrawn? It stays on record — upload the corrected list afterwards.
                              </span>
                              <input value={wdReason} autoFocus
                                     disabled={wdBusy}
                                     placeholder="e.g. supplier sent the wrong file"
                                     onChange={e => setWdReason(e.target.value)}
                                     onKeyDown={e => { if (e.key === 'Enter') withdraw(d.id); }}
                                     style={{ flex: '1 1 220px', fontSize: 12, padding: '4px 8px',
                                              borderRadius: 6, border: '1px solid var(--border)',
                                              background: 'var(--bg)', color: 'var(--text)' }} />
                              <Btn small variant="danger" disabled={wdBusy || !wdReason.trim()}
                                   onClick={() => withdraw(d.id)}>
                                {wdBusy ? 'Withdrawing…' : 'Withdraw list'}
                              </Btn>
                            </div>
                          </td>
                        </tr>
                      )}
                      {open === d.id && (
                        <tr>
                          <td colSpan={5} style={{ padding: '8px 0 12px', borderTop: '1px solid var(--border)' }}>
                            <Reconciliation documentId={d.id} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Card>
      </div>
    );
  }

  window.AdvancePackingHub  = AdvancePackingHub;
  window.AdvancePackingCard = AdvancePackingCard;

})();
