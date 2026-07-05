// Pro Forma List (Screen A) — Wave-3 gap closure
// PL-1: Pipeline KPI strip (GET /api/v1/proforma/pipeline/{batch_id})
// PL-2: Enhanced 8-col table with checkbox + Match chip (existing drafts endpoint)
// PL-3: NewProformaDraftModal (POST /api/v1/proforma/create/{batch_id}/{client_name})
// PL-4: ImportPackingListModal (POST /api/v1/proforma/draft/{id}/import-sales-prices)
// PL-5: getServiceProducts wire is surfaced in proforma-detail.jsx ServiceProductRegistryPanel
//
// WIRING: GET /api/v1/proforma/drafts/{batch_id} (per-batch list)
//         GET /api/v1/proforma/pipeline/{batch_id} (KPI strip)
//         POST /api/v1/proforma/create/{batch_id}/{client_name} (new draft)
//         POST /api/v1/proforma/draft/{id}/import-sales-prices (import TSV prices)
// batch_id from URL ?batch_id=
//
// Census authority: DECISIONS.md — Wave-3 UI uses EXISTING backend routes only.

const { useState, useEffect, useRef } = React;

// ── Status chip ──────────────────────────────────────────────────────────────

const STATUS_CHIP = {
  draft:              { label: 'Draft',          bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  editing:            { label: 'Editing',        bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
  approved:           { label: 'Approved',       bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  posting:            { label: 'Posting...',     bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  posted:             { label: 'Posted',         bg: 'var(--badge-blue-bg)',    text: 'var(--badge-blue-text)',    border: 'var(--badge-blue-border)' },
  post_failed:        { label: 'Post Failed',    bg: 'var(--badge-red-bg)',     text: 'var(--badge-red-text)',     border: 'var(--badge-red-border)' },
  adopted_from_audit: { label: 'Adopted',        bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
  cancelled:          { label: 'Cancelled',      bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
};

function ProformaStatusChip({ status }) {
  const s = STATUS_CHIP[status] || { label: status || 'Unknown', bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 4,
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
      fontSize: 10.5, fontWeight: 600, letterSpacing: '0.02em',
    }}>
      {s.label}
    </span>
  );
}

// ── PL-1: Pipeline KPI strip ─────────────────────────────────────────────────
// Authority: GET /api/v1/proforma/pipeline/{batch_id}
// Shows per-state counts: draft, editing, approved, posted, post_failed/error

function PipelineKpiStrip({ batchId }) {
  const [pipeline, setPipeline] = useState(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setLoading(true);
    window.PzApi.getProformaPipeline(batchId)
      .then(r => { if (!cancelled) { setPipeline(r && r.ok !== false ? (r.data || r) : null); setLoading(false); }})
      .catch(() => { if (!cancelled) { setPipeline(null); setLoading(false); }});
    return () => { cancelled = true; };
  }, [batchId]);

  if (!batchId || loading) return null;
  if (!pipeline) return null;

  const counts = pipeline.by_state || pipeline.counts || pipeline.draft_counts || pipeline.state_counts || {};
  const kpis = [
    { label: 'Draft',    key: 'draft',       accent: 'var(--text-3)' },
    { label: 'Editing',  key: 'editing',     accent: 'var(--badge-amber-text)' },
    { label: 'Approved', key: 'approved',    accent: 'var(--badge-blue-text)' },
    { label: 'Posted',   key: 'posted',      accent: 'var(--badge-green-text)' },
    { label: 'Error',    key: 'post_failed', accent: 'var(--badge-red-text)' },
  ];
  const stage  = pipeline.pipeline_stage || pipeline.stage || '';
  const total  = pipeline.total_drafts || pipeline.client_count || Object.values(counts).reduce((s, v) => s + (Number(v) || 0), 0);

  return (
    <div data-testid="proforma-pipeline-kpi-strip"
      style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap', alignItems: 'stretch' }}>
      {kpis.map(k => {
        const val = counts[k.key] ?? 0;
        return (
          <div key={k.key} data-testid={`kpi-${k.key}`}
            style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
              padding: '10px 16px', minWidth: 90, flex: '1 1 90px' }}>
            <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em',
              color: 'var(--text-3)', marginBottom: 4 }}>{k.label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: val > 0 ? k.accent : 'var(--text-3)',
              fontFamily: '"DM Serif Display", serif' }}>{val}</div>
          </div>
        );
      })}
      <div data-testid="kpi-total"
        style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8,
          padding: '10px 16px', minWidth: 90, flex: '1 1 90px' }}>
        <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em',
          color: 'var(--text-3)', marginBottom: 4 }}>Total</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)',
          fontFamily: '"DM Serif Display", serif' }}>{total}</div>
        {stage && <div style={{ fontSize: 9.5, color: 'var(--text-3)', marginTop: 2 }}>{stage}</div>}
      </div>
    </div>
  );
}

// ── PL-3: New Proforma Draft Modal ────────────────────────────────────────────
// Authority: POST /api/v1/proforma/create/{batch_id}/{client_name}
// 4 source option buttons + info banner

function NewProformaDraftModal({ batchId, onClose, onCreated }) {
  const [clientName, setClientName]   = useState('');
  const [source, setSource]           = useState('from_packing');
  const [creating, setCreating]       = useState(false);
  const [error, setError]             = useState(null);

  const SOURCES = [
    { id: 'from_packing',  icon: '📦', label: 'From packing list',   hint: 'Auto-populate lines from shipment packing data' },
    { id: 'from_existing', icon: '⎘',  label: 'Clone existing draft', hint: 'Duplicate a draft from this batch or another' },
    { id: 'manual',        icon: '✎',  label: 'Empty draft',          hint: 'Start with a blank form — add lines manually' },
    { id: 'from_sales',    icon: '↙',  label: 'From sales packing',   hint: 'Pull lines from the customer sales packing list' },
  ];

  const handleCreate = () => {
    if (!clientName.trim()) { setError('Client name is required.'); return; }
    setCreating(true);
    setError(null);
    window.EstrellaShared.apiFetch(
      `/api/v1/proforma/create/${encodeURIComponent(batchId)}/${encodeURIComponent(clientName.trim())}`,
      { method: 'POST', body: JSON.stringify({ source }) }
    ).then(r => {
      setCreating(false);
      if (r && r.ok !== false && (r.stage === 'issued' || r.stage === 'pending_local' || r.draft_id || (r.data && r.data.draft_id))) {
        onCreated && onCreated(r);
      } else {
        setError((r && (r.error || r.message)) || 'Failed to create draft.');
      }
    }).catch(e => { setCreating(false); setError(e.message || String(e)); });
  };

  return (
    <div data-testid="new-proforma-draft-modal"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1200,
        display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12,
        padding: 28, width: 480, maxWidth: '95vw', boxShadow: '0 8px 32px var(--shadow)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>New Pro Forma Draft</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 18, color: 'var(--text-3)' }}>✕</button>
        </div>

        {/* Info banner */}
        <div style={{ background: 'var(--badge-blue-bg)', border: '1px solid var(--badge-blue-border)',
          borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 11.5, color: 'var(--badge-blue-text)' }}>
          Creates a new draft for the selected client within batch <code style={{ fontSize: 11 }}>{batchId}</code>.
          The draft will be visible in this list immediately after creation.
        </div>

        {/* Client name */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--text-2)',
            textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
            Client name *
          </label>
          <input
            data-testid="new-draft-client-name"
            value={clientName}
            onChange={e => setClientName(e.target.value)}
            placeholder="e.g. Verhoeven Diamonds NV"
            style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--bg)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box' }}
          />
        </div>

        {/* Source option buttons (4) */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase',
            letterSpacing: '0.06em', marginBottom: 8 }}>Source</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {SOURCES.map(s => (
              <button key={s.id} data-testid={`new-draft-source-${s.id}`}
                onClick={() => setSource(s.id)}
                style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 12px',
                  borderRadius: 8, border: `2px solid ${source === s.id ? 'var(--accent)' : 'var(--border)'}`,
                  background: source === s.id ? 'var(--accent-subtle)' : 'var(--card)',
                  cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit', transition: 'border-color 0.15s' }}>
                <span style={{ fontSize: 18 }}>{s.icon}</span>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{s.label}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2, lineHeight: 1.4 }}>{s.hint}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div style={{ marginBottom: 12, padding: '8px 12px', background: 'var(--badge-red-bg)',
            border: '1px solid var(--badge-red-border)', borderRadius: 6,
            fontSize: 12, color: 'var(--badge-red-text)' }}>{error}</div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn variant="ghost" onClick={onClose} disabled={creating} data-testid="new-draft-cancel">Cancel</Btn>
          <Btn variant="primary" onClick={handleCreate} disabled={creating || !clientName.trim()}
            data-testid="new-draft-create">
            {creating ? 'Creating…' : '+ Create Draft'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── PL-4: Import Packing List Modal ───────────────────────────────────────────
// Authority: POST /api/v1/proforma/draft/{id}/import-sales-prices
// 4-step wizard: select draft → paste TSV → confirm lines → done

function ImportPackingListModal({ batchId, drafts, onClose, onImported }) {
  const [step, setStep]       = useState(1);  // 1=select, 2=paste, 3=confirm, 4=done
  const [draftId, setDraftId] = useState('');
  const [tsv, setTsv]         = useState('');
  const [importing, setImporting] = useState(false);
  const [result, setResult]   = useState(null);
  const [error, setError]     = useState(null);

  const editableDrafts = (drafts || []).filter(d =>
    !['posted', 'cancelled', 'adopted_from_audit'].includes(d.draft_state || d.status));

  const handleImport = () => {
    if (!draftId || !tsv.trim()) { setError('Select a draft and paste the TSV data.'); return; }
    setImporting(true);
    setError(null);
    window.EstrellaShared.apiFetch(
      `/api/v1/proforma/draft/${encodeURIComponent(draftId)}/import-sales-prices`,
      { method: 'POST', body: JSON.stringify({ tsv_data: tsv.trim() }) }
    ).then(r => {
      setImporting(false);
      if (r && r.ok !== false) {
        setResult(r.data || r);
        setStep(4);
        onImported && onImported();
      } else {
        setError((r && (r.error || r.message)) || 'Import failed.');
        setStep(3);
      }
    }).catch(e => { setImporting(false); setError(e.message || String(e)); });
  };

  const STEP_LABELS = ['Select draft', 'Paste data', 'Confirm', 'Done'];

  return (
    <div data-testid="import-packing-list-modal"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1200,
        display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget && step < 4) onClose(); }}>
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12,
        padding: 28, width: 520, maxWidth: '95vw', boxShadow: '0 8px 32px var(--shadow)' }}>
        {/* Step indicator */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 22 }}>
          {STEP_LABELS.map((l, i) => (
            <div key={l} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1 }}>
                <div style={{ width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', fontSize: 11, fontWeight: 700,
                  background: step > i + 1 ? 'var(--badge-green-bg)' : step === i + 1 ? 'var(--accent)' : 'var(--bg-subtle)',
                  color: step > i + 1 ? 'var(--badge-green-text)' : step === i + 1 ? 'var(--accent-text)' : 'var(--text-3)',
                  border: `2px solid ${step === i + 1 ? 'var(--accent)' : 'var(--border)'}` }}>
                  {step > i + 1 ? '✓' : i + 1}
                </div>
                <div style={{ fontSize: 9.5, color: step === i + 1 ? 'var(--text)' : 'var(--text-3)',
                  fontWeight: step === i + 1 ? 700 : 400, marginTop: 4, textAlign: 'center' }}>{l}</div>
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div style={{ width: 24, height: 2, background: step > i + 1 ? 'var(--badge-green-bg)' : 'var(--border)',
                  flexShrink: 0, marginBottom: 20 }} />
              )}
            </div>
          ))}
        </div>

        {/* Step 1: Select draft */}
        {step === 1 && (
          <div>
            <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>Select draft to import into</h3>
            {editableDrafts.length === 0 ? (
              <div style={{ padding: '16px 0', color: 'var(--text-3)', fontSize: 13 }}>
                No editable drafts in this batch. Create a draft first.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflowY: 'auto', marginBottom: 16 }}>
                {editableDrafts.map(d => (
                  <button key={d.id} data-testid={`import-select-draft-${d.id}`}
                    onClick={() => setDraftId(String(d.id))}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
                      borderRadius: 8, border: `2px solid ${draftId === String(d.id) ? 'var(--accent)' : 'var(--border)'}`,
                      background: draftId === String(d.id) ? 'var(--accent-subtle)' : 'var(--card)',
                      cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 700, color: 'var(--text)' }}>#{d.id}</span>
                    <span style={{ fontSize: 13, color: 'var(--text)' }}>{d.client_name || '—'}</span>
                    <ProformaStatusChip status={d.draft_state || d.status} />
                  </button>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
              <Btn variant="primary" disabled={!draftId} onClick={() => setStep(2)} data-testid="import-step2-btn">Next →</Btn>
            </div>
          </div>
        )}

        {/* Step 2: Paste TSV */}
        {step === 2 && (
          <div>
            <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>Paste packing list prices</h3>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 12, lineHeight: 1.5 }}>
              Paste tab-separated values (TSV) from the customer sales packing list.
              Columns: <code style={{ fontSize: 11 }}>design_no · qty · unit_price · description_en</code>
            </div>
            <textarea
              data-testid="import-tsv-input"
              value={tsv}
              onChange={e => setTsv(e.target.value)}
              rows={8}
              placeholder={'design_no\tqty\tunit_price\tdescription_en\nRG-10025\t10\t45.00\tGold ring 18k'}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)',
                background: 'var(--bg)', color: 'var(--text)', fontSize: 12, fontFamily: 'monospace',
                boxSizing: 'border-box', resize: 'vertical' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 12 }}>
              <Btn variant="ghost" onClick={() => setStep(1)}>← Back</Btn>
              <div style={{ display: 'flex', gap: 8 }}>
                <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
                <Btn variant="primary" disabled={!tsv.trim()} onClick={() => setStep(3)} data-testid="import-step3-btn">Review →</Btn>
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Confirm */}
        {step === 3 && (
          <div>
            <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>Confirm import</h3>
            <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6,
              padding: '10px 14px', marginBottom: 14, fontSize: 12, color: 'var(--text-2)' }}>
              Importing into draft <strong>#{draftId}</strong>.
              {tsv.trim().split('\n').length - 1} data row(s) detected.
              This will overwrite existing line prices for matched design numbers.
            </div>
            {error && (
              <div style={{ marginBottom: 12, padding: '8px 12px', background: 'var(--badge-red-bg)',
                border: '1px solid var(--badge-red-border)', borderRadius: 6,
                fontSize: 12, color: 'var(--badge-red-text)' }}>{error}</div>
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <Btn variant="ghost" onClick={() => { setStep(2); setError(null); }}>← Back</Btn>
              <div style={{ display: 'flex', gap: 8 }}>
                <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
                <Btn variant="primary" onClick={handleImport} disabled={importing} data-testid="import-confirm-btn">
                  {importing ? 'Importing…' : '↙ Import prices'}
                </Btn>
              </div>
            </div>
          </div>
        )}

        {/* Step 4: Done */}
        {step === 4 && (
          <div style={{ textAlign: 'center', padding: '12px 0' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
            <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700, color: 'var(--badge-green-text)' }}>Import complete</h3>
            {result && (
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 16 }}>
                {result.lines_updated || result.updated || '?'} line(s) updated
                {result.lines_skipped != null ? ` · ${result.lines_skipped} skipped` : ''}.
              </div>
            )}
            <Btn variant="primary" onClick={onClose} data-testid="import-done-btn">Close</Btn>
          </div>
        )}
      </div>
    </div>
  );
}

// ── ProformaCrossBatchLanding — wireframe FULL PORT of the /proforma landing ───
// Wireframe (pair-05 LEFT): cross-batch "Pro Forma Drafts" — 5 KPI tiles +
// drafts table (Draft No · Customer · Shipment · Items · Total · Match · Status)
// + toolbar. READS ONLY via the existing GET /proforma/search (searchProformaDrafts);
// no new endpoint, no write-path change. Write toolbar actions (Push/Send) route
// to the existing confirmed per-draft flow (protected-financial-write — not
// re-triggered here). Batch-context actions (Import/Create) require a batch and
// are honestly gated with reason (Lesson M). Print is backend-GATED (no endpoint).
function _pfBucket(state) {
  const s = String(state || '').toLowerCase();
  if (s.includes('extract')) return 'extracting';
  if (s.includes('push') || s.includes('post')) return 'pushed';
  if (s.includes('error') || s.includes('fail')) return 'error';
  if (s.includes('ready')) return 'ready';
  if (s.includes('review') || s.includes('operator')) return 'operator_review';
  return 'operator_review';
}

function _PfKpi({ label, value, accent }) {
  return (
    <div data-testid="pf-landing-kpi" style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', flex: 1, minWidth: 120 }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text)', marginTop: 4, fontFamily: '"DM Serif Display", serif' }}>{value}</div>
    </div>
  );
}

function ProformaCrossBatchLanding({ onDrill }) {
  const [rows, setRows]       = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError]     = React.useState(null);
  const [selected, setSelected] = React.useState({});

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    window.PzApi.searchProformaDrafts({}).then(res => {
      if (cancelled) return;
      if (!res || !res.ok) { setError((res && res.error) || 'Failed to load drafts'); setLoading(false); return; }
      const d = res.data || {};
      setRows(d.results || d.rows || d.drafts || []);
      setLoading(false);
    }).catch(e => { if (!cancelled) { setError(e.message || String(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const kpi = { extracting: 0, operator_review: 0, ready: 0, pushed: 0, error: 0 };
  rows.forEach(r => { kpi[_pfBucket(r.draft_state)] += 1; });

  const allSel = rows.length > 0 && rows.every(r => selected[r.id || r.draft_id]);
  const toggleAll = () => allSel ? setSelected({}) : setSelected(Object.fromEntries(rows.map(r => [r.id || r.draft_id, true])));
  const disWrite = { padding: '6px 12px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--text-3)', fontSize: 11.5, fontWeight: 600, cursor: 'not-allowed', opacity: 0.6 };

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '20px 32px', background: 'var(--bg)' }} data-testid="proforma-landing-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', margin: 0 }}>Pro Forma Drafts</h2>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 3 }}>Packing List is the source · extraction → review → push to wFirma</div>
        </div>
        <div data-testid="pf-landing-toolbar" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button data-testid="pf-tb-import" disabled title="Open a shipment batch to import a packing list (batch-scoped action)" style={disWrite}>↙ Import Packing List</button>
          <button data-testid="pf-tb-create" disabled title="Open a shipment batch to create a draft (batch-scoped action)" style={disWrite}>+ Create Draft</button>
          <button data-testid="pf-tb-push" disabled title="Open a draft to push to wFirma (confirmed per-draft write)" style={disWrite}>↑ Push to wFirma</button>
          <button data-testid="pf-tb-send" disabled title="Open a draft to send (confirmed per-draft email)" style={disWrite}>✉ Send</button>
          <button data-testid="pf-tb-print" disabled title="Print — backend-gated (no print endpoint)" style={disWrite}>⎙ Print</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <_PfKpi label="Extracting"      value={kpi.extracting} />
        <_PfKpi label="Operator Review" value={kpi.operator_review} accent="var(--badge-amber-text)" />
        <_PfKpi label="Ready"           value={kpi.ready} accent="var(--badge-blue-text)" />
        <_PfKpi label="Pushed"          value={kpi.pushed} accent="var(--badge-green-text)" />
        <_PfKpi label="Error"           value={kpi.error} accent="var(--badge-red-text)" />
      </div>

      {loading && <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}><span className="spinner" /> Loading drafts…</div>}
      {error && !loading && <div data-testid="pf-landing-error" style={{ padding: 24, textAlign: 'center', color: 'var(--badge-red-text)' }}>Failed to load drafts: {error}</div>}
      {!loading && !error && rows.length === 0 && <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}>No proforma drafts yet.</div>}

      {!loading && !error && rows.length > 0 && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ padding: '12px 12px', width: 36 }}><input type="checkbox" checked={allSel} onChange={toggleAll} data-testid="pf-landing-select-all" style={{ cursor: 'pointer' }} /></th>
                {['Draft No', 'Customer', 'Shipment', 'Items', 'Total', 'Match', 'Status'].map(h => (
                  <th key={h} style={{ padding: '12px 14px', textAlign: 'left', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const id = r.id || r.draft_id;
                const matched = r.customer_resolved ? 'Matched' : r.customer_ambiguous ? 'Ambiguous' : 'Unmatched';
                const items = r.line_count ?? r.items ?? '—';
                const total = (r.total != null ? r.total : (r.amount != null ? r.amount : null));
                return (
                  <tr key={id || i} data-testid={`pf-landing-row-${id}`} onClick={() => onDrill && onDrill(r)}
                    style={{ borderBottom: i < rows.length - 1 ? '1px solid var(--border-subtle)' : 'none', cursor: onDrill ? 'pointer' : 'default' }}>
                    <td style={{ padding: '10px 12px' }} onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={!!selected[id]} onChange={() => setSelected(p => ({ ...p, [id]: !p[id] }))} data-testid={`pf-landing-cb-${id}`} style={{ cursor: 'pointer' }} />
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 12, fontFamily: 'monospace', color: 'var(--text)' }}>{r.wfirma_proforma_fullnumber || id || '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text)' }}>{r.client_name || '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 11, fontFamily: 'monospace', color: 'var(--text-2)' }}>{r.batch_id || '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text-2)' }}>{items}</td>
                    <td style={{ padding: '10px 14px', fontSize: 12, fontFamily: 'monospace', color: 'var(--text-2)' }}>{total != null ? `${Number(total).toLocaleString()} ${r.currency || ''}`.trim() : '—'}</td>
                    <td style={{ padding: '10px 14px', fontSize: 11 }}>{matched}</td>
                    <td style={{ padding: '10px 14px' }}>{window.ProformaStatusChip ? <window.ProformaStatusChip status={r.draft_state} /> : <span style={{ fontSize: 11 }}>{r.draft_state || '—'}</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── ProformaListPage — main component ─────────────────────────────────────────

function ProformaListPage({ onDrill }) {
  const batchId = (new URLSearchParams(window.location.search)).get('batch_id') || '';

  // Live draft list
  const draftsHook = window.PzState.useProformaDrafts(batchId);
  const drafts = (draftsHook.data && draftsHook.data.drafts) ? draftsHook.data.drafts : [];

  // PL-2: checkbox selection state
  const [selected, setSelected] = useState({});
  const toggleSelect = (id) => setSelected(prev => ({ ...prev, [id]: !prev[id] }));
  const allSelected  = drafts.length > 0 && drafts.every(d => selected[d.id]);
  const toggleAll    = () => {
    if (allSelected) setSelected({});
    else setSelected(Object.fromEntries(drafts.map(d => [d.id, true])));
  };

  // PL-3 modal
  const [showNewModal, setShowNewModal] = useState(false);
  // PL-4 modal
  const [showImportModal, setShowImportModal] = useState(false);

  if (!batchId) {
    // Wireframe FULL PORT: the /proforma landing is the cross-batch drafts view.
    return <ProformaCrossBatchLanding onDrill={onDrill} />;
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '20px 32px', background: 'var(--bg)' }} data-testid="proforma-list-page">
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', margin: 0 }}>Pro Forma Drafts</h2>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 3 }}>
            Batch: <code style={{ fontSize: 11 }}>{batchId}</code>
            {' '}&mdash; {drafts.length} draft(s) &middot; Click a row to open detail
          </div>
        </div>
        {/* PL-3 + PL-4 toolbar controls */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn variant="ghost" small data-testid="btn-import-packing-list"
            onClick={() => setShowImportModal(true)}>
            ↙ Import prices
          </Btn>
          <Btn variant="primary" small data-testid="btn-new-proforma-draft"
            onClick={() => setShowNewModal(true)}>
            + New Draft
          </Btn>
        </div>
      </div>

      {/* PL-1: Pipeline KPI strip */}
      <PipelineKpiStrip batchId={batchId} />

      {/* Link-as-sales backfill (existing, preserved) */}
      {window.LinkAsSalesBackfill && (
        <window.LinkAsSalesBackfill batchId={batchId} onLinked={draftsHook.reload} />
      )}

      {/* Loading / error / empty */}
      {draftsHook.loading && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}>
          <span className="spinner" /> Loading drafts...
        </div>
      )}
      {draftsHook.error && !draftsHook.loading && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--badge-red-text)' }}>
          Failed to load drafts: {draftsHook.error}
          <br /><Btn variant="ghost" small data-testid="btn-proforma-list-retry" onClick={draftsHook.reload}>Retry</Btn>
        </div>
      )}
      {!draftsHook.loading && !draftsHook.error && drafts.length === 0 && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-2)' }}>
          No proforma drafts found for this batch.
          <div style={{ marginTop: 12 }}>
            <Btn variant="primary" small data-testid="btn-new-draft-empty-state"
              onClick={() => setShowNewModal(true)}>+ Create first draft</Btn>
          </div>
        </div>
      )}

      {/* PL-2: Enhanced drafts table with checkbox + Match chip */}
      {!draftsHook.loading && drafts.length > 0 && (
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10,
          overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                {/* Checkbox all */}
                <th style={{ padding: '12px 12px', width: 36 }}>
                  <input type="checkbox" checked={allSelected}
                    onChange={toggleAll} data-testid="select-all-drafts"
                    style={{ cursor: 'pointer' }} />
                </th>
                {['Draft ID', 'Client', 'State', 'Match', 'Currency', 'Lines', 'Updated'].map((h, i) => (
                  <th key={h} style={{ padding: '12px 14px', textAlign: 'left', fontSize: 10.5, fontWeight: 700,
                    color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drafts.map((d, i) => {
                const lineCount = d.line_count ?? '—';
                const isSelected = !!selected[d.id];
                // Match chip: reflect customer resolution from draft fields
                const matchState = d.customer_resolved ? 'matched'
                  : d.customer_ambiguous ? 'ambiguous' : 'unmapped';
                const matchChip = {
                  matched:   { label: 'Matched',   bg: 'var(--badge-green-bg)',   text: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
                  ambiguous: { label: 'Ambiguous', bg: 'var(--badge-amber-bg)',   text: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
                  unmapped:  { label: 'Unmapped',  bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' },
                }[matchState];
                return (
                  <tr
                    key={d.id}
                    data-testid={`draft-row-${d.id}`}
                    style={{ borderBottom: i < drafts.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                      background: isSelected ? 'var(--accent-subtle)' : 'transparent' }}
                    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--row-hover)'; }}
                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}
                  >
                    {/* Checkbox */}
                    <td style={{ padding: '12px 12px' }}
                      onClick={e => { e.stopPropagation(); toggleSelect(d.id); }}>
                      <input type="checkbox" checked={isSelected}
                        onChange={() => toggleSelect(d.id)}
                        data-testid={`select-draft-${d.id}`}
                        style={{ cursor: 'pointer' }} />
                    </td>
                    <td style={{ padding: '14px 14px', fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
                      color: 'var(--text)', cursor: 'pointer' }}
                      onClick={() => onDrill(d)}>
                      #{d.id}
                      {d.wfirma_proforma_fullnumber && (
                        <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'sans-serif' }}>{d.wfirma_proforma_fullnumber}</div>
                      )}
                    </td>
                    <td style={{ padding: '14px 14px', fontSize: 13, fontWeight: 600, color: 'var(--text)',
                      cursor: 'pointer' }} onClick={() => onDrill(d)}>{d.client_name || '—'}</td>
                    <td style={{ padding: '14px 14px', cursor: 'pointer' }} onClick={() => onDrill(d)}>
                      <ProformaStatusChip status={d.draft_state || d.status} />
                    </td>
                    {/* PL-2: Match chip */}
                    <td style={{ padding: '14px 14px' }}>
                      <span data-testid={`match-chip-${d.id}`} style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        padding: '2px 8px', borderRadius: 4,
                        background: matchChip.bg, color: matchChip.text, border: `1px solid ${matchChip.border}`,
                        fontSize: 10, fontWeight: 600, letterSpacing: '0.02em',
                      }}>{matchChip.label}</span>
                    </td>
                    <td style={{ padding: '14px 14px', fontSize: 13, color: 'var(--text)',
                      cursor: 'pointer' }} onClick={() => onDrill(d)}>{d.currency || '—'}</td>
                    <td style={{ padding: '14px 14px', fontSize: 13, color: 'var(--text)',
                      cursor: 'pointer' }} onClick={() => onDrill(d)}>{lineCount}</td>
                    <td style={{ padding: '14px 14px', fontSize: 11, color: 'var(--text-2)',
                      cursor: 'pointer' }} onClick={() => onDrill(d)}>
                      {(d.updated_at || d.created_at || '—').slice(0, 16).replace('T', ' ')}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* PL-3: New Draft Modal */}
      {showNewModal && (
        <NewProformaDraftModal
          batchId={batchId}
          onClose={() => setShowNewModal(false)}
          onCreated={() => { setShowNewModal(false); draftsHook.reload && draftsHook.reload(); }}
        />
      )}

      {/* PL-4: Import Packing List Modal */}
      {showImportModal && (
        <ImportPackingListModal
          batchId={batchId}
          drafts={drafts}
          onClose={() => setShowImportModal(false)}
          onImported={() => { setShowImportModal(false); draftsHook.reload && draftsHook.reload(); }}
        />
      )}
    </div>
  );
}

Object.assign(window, { ProformaListPage, ProformaStatusChip });
