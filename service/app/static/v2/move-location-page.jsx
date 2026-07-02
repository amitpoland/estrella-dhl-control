// Move Location — slice B×7-1 (first inventory-family promotion; renamed
// move_stock → move_location per operator decision (i): this page is a physical
// location (shelf/zone) metadata helper — "Move Stock" is reserved for the
// document-event-driven business stage promotion, scoped as slice B×7-1b).
//
// AUTHORITY: INVENTORY (piece-level location metadata). This page performs a
// LOCAL metadata-only write — physical location changes; lifecycle state does
// NOT change (single-writer discipline: inventory_state_engine is untouched).
// NO wFirma / fiscal write of any kind.
//
// Endpoints (exactly two — see PzApi):
//   GET  /api/v1/inventory/state/{batch_id}                (list pieces)
//   POST /api/v1/inventory/pieces/{piece_id}/location      (move one piece)
//
// OPERATOR UX RULE (PROJECT_STATE DECISIONS "slice B×7-1", verbatim intent):
//   1. Manual selection with checkboxes (this slice).
//   2. Excel upload by design number / batch / piece count — FUTURE SLICE.
//   3. Optional barcode scanner — NEVER required. A scanner simply types into
//      the filter box below; nothing on this page demands a scan event.
//   Business workflow first. Software scanning second. No mandatory scan gate.
//
// Backend is SINGLE-PIECE-ONLY: multi-select executes SEQUENTIAL per-piece
// moves, each with its own idempotency key; per-piece results are rendered.
// No atomic-batch claim is made anywhere on this page.
(function () {
  const { useState } = React;

  // Distinct, operator-actionable rendering for every backend error code.
  const ERROR_HINTS = {
    INVALID_INPUT:     '400 INVALID_INPUT — a required field (piece, destination, operator, idempotency key) was missing or blank',
    PIECE_NOT_FOUND:   '404 PIECE_NOT_FOUND — piece unknown to inventory_state / packing_lines',
    WRONG_STATE:       '409 WRONG_STATE — piece not in WAREHOUSE_STOCK, cannot move',
    DB_UNAVAILABLE:    '503 DB_UNAVAILABLE — warehouse DB not initialised on the server',
    MIGRATION_PENDING: '503 MIGRATION_PENDING — idempotency migration not applied: operator must run 20260512_002516_idempotency_key against warehouse.db',
  };

  function classifyError(res) {
    const txt = String((res && res.error) || '');
    for (const code of Object.keys(ERROR_HINTS)) {
      if (txt.includes(code)) return code;
    }
    if (res && res.status === 400) return 'INVALID_INPUT';
    if (res && res.status === 404) return 'PIECE_NOT_FOUND';
    if (res && res.status === 409) return 'WRONG_STATE';
    if (res && res.status === 503) return 'DB_UNAVAILABLE';
    return 'UNKNOWN';
  }

  const cellStyle = { padding: '7px 10px', fontSize: 12, color: 'var(--text)', borderBottom: '1px solid var(--border-subtle)' };
  const headStyle = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.04em', textAlign: 'left', borderBottom: '1px solid var(--border)' };
  const inputStyle = { padding: '7px 10px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text)', fontFamily: 'inherit' };

  function MoveLocationPage() {
    const [batchId, setBatchId]   = useState('');
    const [loading, setLoading]   = useState(false);
    const [payload, setPayload]   = useState(null);   // getInventoryState response
    const [loadErr, setLoadErr]   = useState('');
    const [filter, setFilter]     = useState('');
    const [selected, setSelected] = useState({});     // scan_code -> true
    const [dest, setDest]         = useState('');
    const [note, setNote]         = useState('');
    const [moving, setMoving]     = useState(false);
    const [results, setResults]   = useState(null);   // [{scan_code, outcome, code, hint, detail}]

    const load = () => {
      const b = batchId.trim();
      if (!b) return;
      setLoading(true); setLoadErr(''); setPayload(null); setSelected({}); setResults(null);
      window.PzApi.getInventoryState(b).then(r => {
        setLoading(false);
        if (!r.ok) { setLoadErr(r.error || ('HTTP ' + r.status)); return; }
        setPayload(r.data || null);
      });
    };

    const pieces = ((payload && payload.pieces) || []).filter(p => {
      const q = filter.trim().toLowerCase();
      if (!q) return true;
      return String(p.scan_code || '').toLowerCase().includes(q)
          || String(p.design_no || '').toLowerCase().includes(q)
          || String(p.product_code || '').toLowerCase().includes(q);
    });

    const toggle = (code) => setSelected(s => ({ ...s, [code]: !s[code] }));
    const selectedCodes = Object.keys(selected).filter(k => selected[k]);
    const canSubmit = selectedCodes.length > 0 && dest.trim().length > 0 && !moving;

    const submit = async () => {
      if (!canSubmit) return;
      setMoving(true);
      setResults([]);
      const rows = [];
      // SEQUENTIAL single-piece moves — the backend has no batch endpoint.
      // Each piece gets its OWN idempotency key so a partial retry never
      // replays an unrelated piece's move.
      for (const code of selectedCodes) {
        const r = await window.PzApi.movePieceLocation(code, {
          toLocation:     dest.trim(),
          idempotencyKey: crypto.randomUUID(),
          note:           note,
        });
        if (r.ok) {
          rows.push({ scan_code: code, outcome: (r.data && r.data.status) || 'moved',
                      code: '', hint: '', detail: (r.data && r.data.to_location) || '' });
        } else {
          const ec = classifyError(r);
          rows.push({ scan_code: code, outcome: 'failed',
                      code: ec, hint: ERROR_HINTS[ec] || ('HTTP ' + r.status), detail: r.error || '' });
        }
        setResults(rows.slice());
      }
      setMoving(false);
    };

    return (
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '28px 24px' }} data-testid="move-location-root">

        {/* Honest-mechanics banner — always visible */}
        <div data-testid="ms-banner" style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--text-2)' }}>
          Batch = sequential single-piece moves (backend is per-piece). Each selected piece is
          moved by its own idempotent call; per-piece results appear below. Metadata-only write —
          lifecycle state is not changed. Scanner optional: a barcode scanner just types into the
          filter box; no scan is ever required.
        </div>

        {/* Batch loader */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          <input data-testid="ms-batch-input" value={batchId} onChange={e => setBatchId(e.target.value)}
            placeholder="Batch id (e.g. SHIPMENT_…)" style={{ ...inputStyle, flex: 1 }} />
          <button data-testid="ms-load" onClick={load} disabled={!batchId.trim() || loading}
            style={{ ...inputStyle, cursor: 'pointer', fontWeight: 600 }}>
            {loading ? 'Loading…' : 'Load pieces'}
          </button>
        </div>

        {loadErr && (
          <div data-testid="ms-load-error" style={{ marginBottom: 14, padding: '10px 14px', border: '1px solid var(--badge-red-text)', borderRadius: 8, fontSize: 12, color: 'var(--badge-red-text)' }}>
            {loadErr}
          </div>
        )}

        {payload && payload.total === 0 && (
          <div data-testid="ms-empty" style={{ marginBottom: 14, padding: '14px', border: '1px dashed var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--text-3)' }}>
            No pieces in this batch — inventory_state has no rows for it (honest empty; nothing to move).
          </div>
        )}

        {payload && payload.total > 0 && (
          <>
            <input data-testid="ms-filter" value={filter} onChange={e => setFilter(e.target.value)}
              placeholder="Filter by design no / piece id / product code (scanner types here — optional, never required)"
              style={{ ...inputStyle, width: '100%', marginBottom: 10 }} />

            <table data-testid="ms-table" style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 14 }}>
              <thead>
                <tr>
                  <th style={headStyle}></th>
                  <th style={headStyle}>Piece (scan_code)</th>
                  <th style={headStyle}>Design</th>
                  <th style={headStyle}>Product code</th>
                  <th style={headStyle}>State</th>
                  <th style={headStyle}>Updated</th>
                </tr>
              </thead>
              <tbody>
                {pieces.map(p => {
                  const synthetic = !!p.synthetic;
                  return (
                    <tr key={p.scan_code}>
                      <td style={cellStyle}>
                        <input type="checkbox" data-testid="ms-row-checkbox"
                          checked={!!selected[p.scan_code]}
                          disabled={synthetic}
                          title={synthetic ? 'purchase-transit projection — not movable (would 409 WRONG_STATE)' : ''}
                          onChange={() => toggle(p.scan_code)} />
                      </td>
                      <td style={{ ...cellStyle, fontFamily: 'ui-monospace, monospace' }}>{p.scan_code}</td>
                      <td style={cellStyle}>{p.design_no || '—'}</td>
                      <td style={cellStyle}>{p.product_code || '—'}</td>
                      <td style={cellStyle}>
                        {p.state}
                        {synthetic && <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--badge-amber-text)' }}>projection — not movable</span>}
                      </td>
                      <td style={{ ...cellStyle, color: 'var(--text-3)' }}>{p.updated_at || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
              <input data-testid="ms-destination" value={dest} onChange={e => setDest(e.target.value)}
                placeholder="Destination location code" style={{ ...inputStyle, flex: 1, minWidth: 220 }} />
              <input data-testid="ms-note" value={note} onChange={e => setNote(e.target.value)}
                placeholder="Note (optional)" style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
              <button data-testid="ms-submit" onClick={submit} disabled={!canSubmit}
                style={{ ...inputStyle, cursor: canSubmit ? 'pointer' : 'not-allowed', fontWeight: 700, background: canSubmit ? 'var(--accent)' : 'var(--bg-subtle)' }}>
                {moving ? 'Moving…' : `Move ${selectedCodes.length} selected piece(s) → location (sequential per-piece writes)`}
              </button>
            </div>
          </>
        )}

        {results && (
          <div data-testid="ms-results">
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>
              Per-piece results ({results.length}/{selectedCodes.length})
            </div>
            {results.map(r => (
              <div key={r.scan_code} data-testid="ms-result-row"
                style={{ padding: '7px 10px', fontSize: 12, borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 10 }}>
                <span style={{ fontFamily: 'ui-monospace, monospace' }}>{r.scan_code}</span>
                <span style={{ fontWeight: 700, color: r.outcome === 'failed' ? 'var(--badge-red-text)' : 'var(--badge-green-text)' }}>
                  {r.outcome}
                </span>
                {r.code && <span style={{ color: 'var(--badge-red-text)' }}>{r.hint}</span>}
                {!r.code && r.detail && <span style={{ color: 'var(--text-3)' }}>→ {r.detail}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  window.MoveLocationPage = MoveLocationPage;
})();
