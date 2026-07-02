// ─────────────────────────────────────────────────────────────────────────────
// inventory-page.jsx — Sprint 30: Live Inventory Hub wired to V2 shell
//
// Replaces the Sprint 1 MOCK prototype.
// Live components extracted from inventory-v2.html (Sprint 29).
// Uses window.EstrellaShared.apiFetch (same auth-aware shim as all V2 pages).
//
// Exports:
//   window.InventoryPage      — live read-only hub (5 panels, 8 endpoints)
//   window.DocumentViewerPage — shell-global document viewer (used by all pages)
//
// Endpoints (read-only, no write calls):
//   GET /api/v1/inventory/stage2/aggregate   — Stage 2 overview (auto-load)
//   GET /api/v1/inventory/state/{batch_id}   — Batch inventory state
//   GET /api/v1/inventory/pieces/{piece_id}  — Piece lookup by ID
//   GET /api/v1/warehouse/inventory/{scan}   — Piece lookup by scan code
//   GET /api/v1/warehouse/locations          — Location browser (auto-load)
//   GET /api/v1/warehouse/locations/{code}/inventory — Location detail
//   GET /api/v1/warehouse/audit-summary/{batch_id}   — Audit summary
//   GET /api/v1/warehouse/audit/{batch_id}           — Full audit
// ─────────────────────────────────────────────────────────────────────────────

// ── Document Viewer (shell-global, used by proforma/pz/inbox via openViewer) ─

function DocumentViewerPage({ doc, onBack }) {
  const [page, setPageNum] = React.useState(1);
  const [zoom, setZoom] = React.useState(100);
  const totalPages = doc?.totalPages || 2;

  const meta = [
    { label: 'Document type',  value: doc?.type || 'Packing List' },
    { label: 'Document #',     value: doc?.id || 'PL-EJL-26-27-013' },
    { label: 'Title',          value: doc?.title || 'Packing list of shipment 5pcs · 04 Apr 2026' },
    { label: 'Linked AWB',     value: doc?.awb || 'DHL-1234567890' },
    { label: 'Linked shipment',value: doc?.shipment || 'SHP-2026-0142' },
    { label: 'Uploaded',       value: doc?.uploaded || '04 Apr 2026 · 09:14' },
    { label: 'Uploaded by',    value: doc?.uploadedBy || 'Anna K.' },
    { label: 'Size',           value: doc?.size || '184 KB' },
    { label: 'Format',         value: doc?.format || 'XLSX' },
    { label: 'Hash',           value: doc?.hash || 'sha256:a4f9…b182' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: 'var(--bg)' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 24px', borderBottom: '1px solid var(--border)',
        background: 'var(--card)', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Btn small variant="ghost" onClick={onBack}>&larr; Back</Btn>
          <div style={{ width: 1, height: 22, background: 'var(--border)' }} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{doc?.title || 'Packing list of shipment'}</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'monospace' }}>{doc?.id || 'PL-EJL-26-27-013'} &middot; {doc?.format || 'XLSX'}</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Btn small variant="ghost" onClick={() => setPageNum(Math.max(1, page - 1))} disabled={page === 1}>&lsaquo;</Btn>
          <span style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 48, textAlign: 'center', fontFamily: 'monospace' }}>{page} / {totalPages}</span>
          <Btn small variant="ghost" onClick={() => setPageNum(Math.min(totalPages, page + 1))} disabled={page === totalPages}>&rsaquo;</Btn>
          <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px' }} />
          <Btn small variant="ghost" onClick={() => setZoom(Math.max(50, zoom - 10))}>&minus;</Btn>
          <span style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 44, textAlign: 'center', fontFamily: 'monospace' }}>{zoom}%</span>
          <Btn small variant="ghost" onClick={() => setZoom(Math.min(200, zoom + 10))}>+</Btn>
          <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px' }} />
          <Btn small variant="outline">Open in new tab</Btn>
          <Btn small variant="outline">&darr; Download</Btn>
          <Btn small>&darr; Download all (.zip)</Btn>
        </div>
      </div>

      {/* Body — viewer + side panel */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 1, overflow: 'auto', padding: 24, background: 'var(--bg-subtle)', display: 'flex', justifyContent: 'center', alignItems: 'flex-start' }}>
          <div style={{
            width: 800 * (zoom / 100), minHeight: 1000 * (zoom / 100),
            background: 'white', boxShadow: '0 4px 20px var(--shadow)',
            padding: '40px 48px', color: '#222',
            fontFamily: 'sans-serif', fontSize: 11 * (zoom / 100),
          }}>
            <div style={{ background: '#131C2E', color: 'white', padding: '14px 20px', textAlign: 'center', fontWeight: 700, letterSpacing: '0.05em', marginBottom: 16, fontSize: 14 * (zoom / 100) }}>
              SHIPMENT PACKING LIST
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 9 * (zoom / 100), fontWeight: 700, color: '#666', textTransform: 'uppercase', marginBottom: 4 }}>Bill to:</div>
                <div style={{ fontWeight: 700 }}>Juliany EOOD</div>
                <div>G.S. Rakovski &numero;70</div>
                <div>1000 Sofia, Bulgaria</div>
                <div>VAT UE: BG121281167</div>
              </div>
              <div>
                <div style={{ fontSize: 9 * (zoom / 100), fontWeight: 700, color: '#666', textTransform: 'uppercase', marginBottom: 4 }}>Ship to:</div>
                <div style={{ fontWeight: 700 }}>Juliany EOOD</div>
                <div>ul. Georgi Benkovski 14-16</div>
                <div>1000 Sofia, Bulgaria</div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid #ddd' }}>
              <div><strong>Invoice #:</strong> EJL/26-27/013 &middot; PROF 70/2026</div>
              <div><strong>Dated:</strong> 07.04.2026</div>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 9.5 * (zoom / 100) }}>
              <thead>
                <tr style={{ background: '#f3f1ea' }}>
                  {['Pk Sr','Ctg','Client PO','Design No','Karat','Color','Quality','Dia Wt','Col Wt','Qty','Size','Value','Total'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', border: '1px solid #ccc', textAlign: 'left', fontSize: 9 * (zoom / 100) }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ['1','PND','PROF 70/2026','EJ-PND-0142-A','18KT','W','VS-GH','0.75','—','2','—','480.00','960.00'],
                  ['2','PND','PROF 70/2026','EJ-PND-0142-B','18KT','W','VS-GH','0.82','—','3','—','510.00','1,530.00'],
                  ['3','Loose Metal','—','LM-18W-04','18KT','W','—','—','12.40','1','—','612.00','612.00'],
                ].map((row, i) => (
                  <tr key={i}>
                    {row.map((c, j) => (
                      <td key={j} style={{ padding: '5px 8px', border: '1px solid #ddd' }}>{c}</td>
                    ))}
                  </tr>
                ))}
                <tr style={{ background: '#f3f1ea', fontWeight: 700 }}>
                  <td colSpan="9" style={{ padding: '6px 8px', border: '1px solid #ccc', textAlign: 'right' }}>Grand Total</td>
                  <td style={{ padding: '6px 8px', border: '1px solid #ccc' }}>6</td>
                  <td colSpan="2" style={{ padding: '6px 8px', border: '1px solid #ccc' }}></td>
                  <td style={{ padding: '6px 8px', border: '1px solid #ccc' }}>3,102.00</td>
                </tr>
              </tbody>
            </table>
            <div style={{ marginTop: 16, fontSize: 10 * (zoom / 100), color: '#666' }}>No frt charges.</div>
          </div>
        </div>

        {/* Side panel */}
        <div style={{
          width: 320, flexShrink: 0, borderLeft: '1px solid var(--border)',
          background: 'var(--card)', overflowY: 'auto', padding: 20,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 12 }}>Document metadata</div>
          {meta.map(m => (
            <div key={m.label} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 2 }}>{m.label}</div>
              <div style={{ fontSize: 12.5, color: 'var(--text)', fontFamily: m.label === 'Hash' || m.label.includes('#') ? 'monospace' : undefined, wordBreak: 'break-all' }}>{m.value}</div>
            </div>
          ))}
          <div style={{ height: 1, background: 'var(--border)', margin: '20px 0' }} />
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Linked entities</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>&rarr; Shipment SHP-2026-0142</a>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>&rarr; AWB DHL-1234567890</a>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>&rarr; TempPurchase (3 lines)</a>
            <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>&rarr; Proforma PROF 70/2026</a>
          </div>
          <div style={{ height: 1, background: 'var(--border)', margin: '20px 0' }} />
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 10 }}>Other documents in this shipment</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {['Commercial Invoice EJL/26-27/013', 'AWB Print', 'SAD ZC429', 'PZ Receipt'].map(name => (
              <div key={name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', background: 'var(--bg-subtle)', borderRadius: 6, fontSize: 12 }}>
                <span style={{ color: 'var(--text-2)' }}>{name}</span>
                <Btn small variant="ghost">View</Btn>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Inventory Hub — live panels extracted from inventory-v2.html (Sprint 29) ─
// All components are scoped to this IIFE to avoid global name collisions.

(function () {
  'use strict';
  const { useState, useEffect, useCallback } = React;
  const apiFetch = window.EstrellaShared.apiFetch;

  // ── Shared UI atoms (private to this module) ──────────────────────────────

  function InvLabel({ children }) {
    return <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 6 }}>{children}</div>;
  }

  // NO spread-rest here — Babel-standalone hoists the compiled destructure
  // helper's `_excluded` prop-list to a GLOBAL var OUTSIDE this IIFE, and a
  // later-loaded script's own `_excluded` OVERWRITES it, leaking onChange
  // into the spread and putting the raw state setter on the <input> (typing
  // then stores the event object into state → "batchId.trim is not a
  // function", the whole tree unmounts). Found by the B2 render check
  // 2026-07-03; pre-existing (AuditPanel crashed identically). Explicit
  // 'data-testid' destructuring keeps call sites byte-identical and makes
  // this file immune to the helper collision. Page-wide class recorded in
  // PROJECT_STATE DECISIONS — other files' spread-rest components remain
  // exposed until their own slice.
  function InvInput({ value, onChange, placeholder, type, 'data-testid': testid }) {
    return (
      <input type={type || 'text'} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{ width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12, fontFamily: 'monospace', outline: 'none' }}
        data-testid={testid}
      />
    );
  }

  // NO spread-rest — same global `_excluded` helper-collision immunity as
  // InvInput above.
  function InvFetchBtn({ onClick, loading, label, disabled, 'data-testid': testid }) {
    return (
      <button onClick={onClick} disabled={disabled || loading}
        style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--accent-border)', background: loading ? 'var(--bg-subtle)' : 'var(--accent-subtle)', color: loading ? 'var(--text-3)' : 'var(--accent-text)', fontSize: 12, fontWeight: 600, cursor: disabled || loading ? 'not-allowed' : 'pointer', opacity: disabled ? 0.45 : 1 }}
        data-testid={testid}
      >
        {loading ? '…' : label}
      </button>
    );
  }

  function StatBadge({ count, label, tone, sub }) {
    const c = tone === 'green' ? '--badge-green' : tone === 'amber' ? '--badge-amber' : tone === 'red' ? '--badge-red' : '--badge-neutral';
    return (
      <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px', boxShadow: '0 1px 2px var(--shadow)' }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 6 }}>{label}</div>
        <div style={{ fontSize: 26, fontWeight: 700, color: count == null ? 'var(--text-3)' : `var(${c}-text)` }}>
          {count == null ? '—' : count}
        </div>
        {sub && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{sub}</div>}
      </div>
    );
  }

  function StateChip({ state }) {
    const MAP = {
      WAREHOUSE_STOCK:        { label: 'In Stock',          bg: 'var(--badge-green-bg)',  text: 'var(--badge-green-text)',  border: 'var(--badge-green-border)' },
      PURCHASE_TRANSIT:       { label: 'In Transit',        bg: 'var(--badge-blue-bg)',   text: 'var(--badge-blue-text)',   border: 'var(--badge-blue-border)' },
      SALES_TRANSIT:          { label: 'Sales Transit',     bg: 'var(--badge-blue-bg)',   text: 'var(--badge-blue-text)',   border: 'var(--badge-blue-border)' },
      DIRECT_DISPATCH_READY:  { label: 'Dispatch Ready',    bg: 'var(--badge-amber-bg)',  text: 'var(--badge-amber-text)',  border: 'var(--badge-amber-border)' },
      CLIENT_DISPATCHED:      { label: 'Dispatched',        bg: 'var(--badge-purple-bg)', text: 'var(--badge-purple-text)', border: 'var(--badge-purple-border)' },
      CLOSED:                 { label: 'Closed',            bg: 'var(--badge-neutral-bg)',text: 'var(--badge-neutral-text)',border: 'var(--badge-neutral-border)' },
      SAMPLE_OUT:             { label: 'Sample Out',        bg: 'var(--badge-amber-bg)',  text: 'var(--badge-amber-text)',  border: 'var(--badge-amber-border)' },
      RETURNED_FROM_CLIENT:   { label: 'Return / Client',   bg: 'var(--badge-red-bg)',    text: 'var(--badge-red-text)',    border: 'var(--badge-red-border)' },
      RETURNED_TO_PRODUCER:   { label: 'Return / Producer', bg: 'var(--badge-red-bg)',    text: 'var(--badge-red-text)',    border: 'var(--badge-red-border)' },
    };
    const s = MAP[state] || { label: state || '?', bg: 'var(--badge-neutral-bg)', text: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', background: s.bg, color: s.text, border: `1px solid ${s.border}`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap' }}>
        {s.label}
      </span>
    );
  }

  function ResultBox({ data, error }) {
    if (!data && !error) return null;
    if (error) return <div style={{ marginTop: 10, padding: '10px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-red-text)', fontFamily: 'monospace' }}>{error}</div>;
    return <pre style={{ marginTop: 10, padding: '12px 14px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 11, color: 'var(--text)', overflowX: 'auto', maxHeight: 360, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace', lineHeight: 1.5 }}>{JSON.stringify(data, null, 2)}</pre>;
  }

  // Wireframe KPI tile (B1, ported from design/inventory-page.design.jsx
  // :28-43 InvStatTile). A `pending` tile shows a clean BACKEND-PENDING ·
  // PHASE C badge instead of a value (used where the aggregate genuinely has
  // no data — never a fake number).
  function InvStatTile({ label, value, hint, tone, pending, testid }) {
    const toneColor = tone === 'red'   ? 'var(--badge-red-text)'
                    : tone === 'amber' ? 'var(--badge-amber-text)'
                    : tone === 'green' ? 'var(--badge-green-text)'
                    : 'var(--text)';
    return (
      <div data-testid={testid} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px', boxShadow: '0 1px 2px var(--shadow)' }}>
        <div style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.10em', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6, lineHeight: 1.25 }}>{label}</div>
        {pending ? (
          <span style={{ display: 'inline-flex', alignItems: 'center', fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', padding: '3px 7px', borderRadius: 3, background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', border: '1px solid var(--badge-amber-border)' }}>
            BACKEND-PENDING · PHASE C
          </span>
        ) : (
          <div style={{ fontSize: 22, fontWeight: 600, color: toneColor, lineHeight: 1.25 }}>{value == null ? '—' : value}</div>
        )}
        {hint && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{hint}</div>}
      </div>
    );
  }

  function InvPanel({ title, subtitle, children, testid }) {
    return (
      <div data-testid={testid} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)', marginBottom: 20 }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
          {subtitle && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{subtitle}</div>}
        </div>
        <div style={{ padding: '16px 20px' }}>{children}</div>
      </div>
    );
  }

  // ── Stage 2 Overview — auto-fetches on mount ────────────────────────────────

  function Stage2Panel() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
      setLoading(true); setError(null);
      try { setData(await apiFetch('/api/v1/inventory/stage2/aggregate')); }
      catch (e) { setError((e && e.message) || String(e)); }
      finally { setLoading(false); }
    }, []);

    useEffect(() => { load(); }, [load]);

    const s2 = data && data.stage2;
    return (
      <InvPanel title="Stage 2 overview" subtitle="Physical inventory counts — auto-loaded from /api/v1/inventory/stage2/aggregate" testid="panel-stage2">
        {loading && <div style={{ color: 'var(--text-3)', fontSize: 12 }}>Loading…</div>}
        {error && <div style={{ color: 'var(--badge-red-text)', fontSize: 12 }}>Error: {error}</div>}
        {s2 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
            <InvStatTile testid="tile-final-stock" label="Final stock" value={s2.final_stock && s2.final_stock.count} tone="green" hint="WAREHOUSE_STOCK" />
            <InvStatTile testid="tile-samples-out" label="Samples out" value={s2.samples && s2.samples.count} tone="amber" hint="SAMPLE_OUT" />
            <InvStatTile testid="tile-returns" label="Returns" value={s2.returns && s2.returns.count} tone="red"
              hint={s2.returns && s2.returns.subcounts ? `${s2.returns.subcounts.from_client} client · ${s2.returns.subcounts.to_producer} producer` : null}
            />
            {/* Consignment: the aggregate genuinely returns not-available (no
                CONSIGNMENT state/table) — a clean pending tile, never a fake
                number. The engineer-facing basis stays in data.limitations. */}
            <InvStatTile testid="tile-consignment" label="Consignment" pending hint="physically with client · title retained" />
          </div>
        )}
        {/* B1: the raw diagnostic limitations paragraph was removed from the UI
            (its content lives in the API response for engineers; the
            Consignment pending tile carries the operator-facing signal). */}
        <div style={{ marginTop: 10 }}>
          <button onClick={load} disabled={loading} style={{ fontSize: 11, border: '1px solid var(--border)', background: 'transparent', borderRadius: 4, padding: '4px 10px', cursor: loading ? 'default' : 'pointer', color: 'var(--text-2)' }} data-testid="btn-refresh-stage2">
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </InvPanel>
    );
  }

  // ── Batch state panel ───────────────────────────────────────────────────────

  function BatchPanel() {
    const [batchId, setBatchId] = useState('');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    const doFetch = useCallback(async () => {
      if (!batchId.trim()) return;
      setLoading(true); setData(null); setError(null);
      try { setData(await apiFetch(`/api/v1/inventory/state/${encodeURIComponent(batchId.trim())}`)); }
      catch (e) { setError((e && e.message) || String(e)); }
      finally { setLoading(false); }
    }, [batchId]);

    const counts = data && data.counts;
    const STATES = ['WAREHOUSE_STOCK','PURCHASE_TRANSIT','SALES_TRANSIT','DIRECT_DISPATCH_READY','CLIENT_DISPATCHED','SAMPLE_OUT','RETURNED_FROM_CLIENT','RETURNED_TO_PRODUCER','CLOSED'];

    return (
      <InvPanel title="Batch inventory state" subtitle="Per-state piece counts for a shipment batch" testid="panel-batch">
        <InvLabel>Batch ID</InvLabel>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <div style={{ flex: 1 }}>
            <InvInput value={batchId} onChange={setBatchId} placeholder="e.g. SHIPMENT_4218922912_2026-05_…" data-testid="input-batch-id" />
          </div>
          <InvFetchBtn onClick={doFetch} loading={loading} label="Load state" disabled={!batchId.trim()} data-testid="btn-batch-state" />
        </div>
        {error && <div style={{ color: 'var(--badge-red-text)', fontSize: 12 }}>{error}</div>}
        {data && (
          <>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              {STATES.filter(s => counts && counts[s] > 0).map(s => (
                <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <StateChip state={s} />
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{counts[s]}</span>
                </div>
              ))}
              {counts && STATES.every(s => !counts[s]) && <span style={{ fontSize: 12, color: 'var(--text-3)' }}>No pieces found for this batch.</span>}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
              Total: <strong>{data.total || 0}</strong> · Source: <code style={{ fontFamily: 'monospace', background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>{data.source || '—'}</code>
              {data.degraded && <span style={{ color: 'var(--badge-amber-text)' }}> · ⚠ degraded</span>}
            </div>
            {data.pieces && data.pieces.length > 0 && (
              <details style={{ marginTop: 12 }}>
                <summary style={{ fontSize: 12, color: 'var(--text-2)', cursor: 'pointer' }}>Show {data.pieces.length} piece records ▸</summary>
                <div style={{ marginTop: 8, overflowX: 'auto', maxHeight: 260, overflowY: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                        {['Scan code', 'State', 'Design', 'Updated'].map(h => (
                          <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: 10 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.pieces.slice(0, 200).map((p, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                          <td style={{ padding: '5px 10px', fontFamily: 'monospace', fontSize: 11 }}>{p.scan_code || '—'}</td>
                          <td style={{ padding: '5px 10px' }}><StateChip state={p.state} /></td>
                          <td style={{ padding: '5px 10px', color: 'var(--text-2)' }}>{p.design_no || '—'}</td>
                          <td style={{ padding: '5px 10px', color: 'var(--text-3)' }}>{(p.updated_at || '—').slice(0, 16).replace('T', ' ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {data.pieces.length > 200 && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6 }}>Showing first 200 of {data.pieces.length}.</div>}
                </div>
              </details>
            )}
          </>
        )}
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-3)' }}>Read-only. No write calls are made from this panel.</div>
      </InvPanel>
    );
  }

  // ── Piece / scan-code lookup ────────────────────────────────────────────────

  function PiecePanel() {
    const [pieceId, setPieceId]       = useState('');
    const [scanCode, setScanCode]     = useState('');
    const [activeMode, setActiveMode] = useState('');
    const [loading, setLoading]       = useState(false);
    const [data, setData]             = useState(null);
    const [error, setError]           = useState(null);

    const fetchPiece = useCallback(async () => {
      if (!pieceId.trim()) return;
      setActiveMode('piece'); setLoading(true); setData(null); setError(null);
      try { setData(await apiFetch(`/api/v1/inventory/pieces/${encodeURIComponent(pieceId.trim())}`)); }
      catch (e) { setError((e && e.message) || String(e)); }
      finally { setLoading(false); }
    }, [pieceId]);

    const fetchScan = useCallback(async () => {
      if (!scanCode.trim()) return;
      setActiveMode('scan'); setLoading(true); setData(null); setError(null);
      try { setData(await apiFetch(`/api/v1/warehouse/inventory/${encodeURIComponent(scanCode.trim())}`)); }
      catch (e) { setError((e && e.message) || String(e)); }
      finally { setLoading(false); }
    }, [scanCode]);

    const st  = data && data.state;
    const loc = data && data.location;
    const cur = data && data.current;

    return (
      <InvPanel title="Piece / scan-code lookup" subtitle="Fetch piece state + location by piece_id or scan barcode" testid="panel-piece">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 10 }}>
          <div>
            <InvLabel>Piece ID (inventory truth key)</InvLabel>
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}><InvInput value={pieceId} onChange={setPieceId} placeholder="e.g. piece_id" data-testid="input-piece-id" /></div>
              <InvFetchBtn onClick={fetchPiece} loading={loading && activeMode === 'piece'} label="Lookup" disabled={!pieceId.trim()} data-testid="btn-lookup-piece" />
            </div>
          </div>
          <div>
            <InvLabel>Scan code / trace barcode</InvLabel>
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}><InvInput value={scanCode} onChange={setScanCode} placeholder="e.g. PND-CLASSIC·EJ-…" data-testid="input-scan-code" /></div>
              <InvFetchBtn onClick={fetchScan} loading={loading && activeMode === 'scan'} label="Lookup" disabled={!scanCode.trim()} data-testid="btn-lookup-scan" />
            </div>
          </div>
        </div>
        {error && <div style={{ color: 'var(--badge-red-text)', fontSize: 12, marginBottom: 8 }}>{error}</div>}
        {data && activeMode === 'piece' && (
          <div>
            {!data.found ? (
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Piece not found.</div>
            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 12 }}>
                  <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Inventory state</div>
                    {st && (
                      <>
                        <StateChip state={st.state} />
                        <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-2)' }}>Scan: <code style={{ fontFamily: 'monospace' }}>{st.scan_code}</code></div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Updated: {(st.updated_at || '—').slice(0, 16).replace('T', ' ')}</div>
                      </>
                    )}
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Location</div>
                    {loc ? (
                      <>
                        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{loc.current_location || '—'}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-2)' }}>Status: {loc.current_status || '—'}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>Updated: {(loc.updated_at || '—').slice(0, 16).replace('T', ' ')}</div>
                      </>
                    ) : <div style={{ fontSize: 11, color: 'var(--text-3)' }}>No warehouse location recorded.</div>}
                  </div>
                </div>
                {data.timeline && data.timeline.length > 0 && (
                  <details>
                    <summary style={{ fontSize: 12, color: 'var(--text-2)', cursor: 'pointer' }}>Timeline ({data.timeline.length} events) ▸</summary>
                    <div style={{ marginTop: 8, fontSize: 11 }}>
                      {data.timeline.slice(0, 50).map((ev, i) => (
                        <div key={i} style={{ display: 'flex', gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                          <span style={{ color: 'var(--text-3)', fontFamily: 'monospace', minWidth: 130 }}>{(ev.occurred_at || '').slice(0, 16).replace('T', ' ')}</span>
                          <span style={{ color: 'var(--badge-blue-text)', minWidth: 70 }}>{ev.kind}</span>
                          <span style={{ color: 'var(--text)' }}>{ev.summary}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </>
            )}
          </div>
        )}
        {data && activeMode === 'scan' && (
          <div>
            {!cur && !data.packing_line ? (
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Scan code not found in warehouse records.</div>
            ) : (
              <>
                {cur && (
                  <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 12 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Current location</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{cur.current_location || '—'}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 2 }}>Status: {cur.current_status} · Design: {cur.design_no} · Batch: {cur.batch_id}</div>
                  </div>
                )}
                {data.packing_line && <div style={{ fontSize: 11, color: 'var(--badge-amber-text)', marginBottom: 8 }}>⚠ {data.note || 'In packing — not yet scanned.'}</div>}
                {data.history && data.history.length > 0 && (
                  <details>
                    <summary style={{ fontSize: 12, color: 'var(--text-2)', cursor: 'pointer' }}>Movement history ({data.history.length}) ▸</summary>
                    <div style={{ marginTop: 8, fontSize: 11 }}>
                      {data.history.map((h, i) => (
                        <div key={i} style={{ display: 'flex', gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                          <span style={{ color: 'var(--text-3)', fontFamily: 'monospace', minWidth: 130 }}>{(h.event_time || '').slice(0, 16).replace('T', ' ')}</span>
                          <span style={{ color: 'var(--badge-blue-text)', minWidth: 70 }}>{h.action}</span>
                          <span style={{ color: 'var(--text)' }}>{h.from_location ? `${h.from_location} → ` : ''}{h.to_location}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </>
            )}
          </div>
        )}
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-3)' }}>Read-only. No write calls are made from this panel.</div>
      </InvPanel>
    );
  }

  // ── Location browser — auto-fetches on mount ────────────────────────────────

  function LocationPanel() {
    const [locations, setLocations]     = useState(null);
    const [locLoading, setLocLoading]   = useState(true);
    const [locError, setLocError]       = useState(null);
    const [selectedCode, setSelectedCode] = useState('');
    const [detailLoading, setDetailLoading] = useState(false);
    const [detail, setDetail]           = useState(null);
    const [detailError, setDetailError] = useState(null);

    const loadLocations = useCallback(async () => {
      setLocLoading(true); setLocError(null);
      try { setLocations(await apiFetch('/api/v1/warehouse/locations')); }
      catch (e) { setLocError((e && e.message) || String(e)); }
      finally { setLocLoading(false); }
    }, []);

    useEffect(() => { loadLocations(); }, [loadLocations]);

    const loadDetail = useCallback(async (code) => {
      if (!code) return;
      setDetailLoading(true); setDetail(null); setDetailError(null);
      try { setDetail(await apiFetch(`/api/v1/warehouse/locations/${encodeURIComponent(code)}/inventory`)); }
      catch (e) { setDetailError((e && e.message) || String(e)); }
      finally { setDetailLoading(false); }
    }, []);

    return (
      <InvPanel title="Location browser" subtitle="Warehouse locations — auto-loaded; click a location to see its inventory" testid="panel-locations">
        {locLoading && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading locations…</div>}
        {locError && <div style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>{locError}</div>}
        {locations && (
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
            {(locations.locations || []).map(loc => (
              <button key={loc.location_code} onClick={() => { setSelectedCode(loc.location_code); loadDetail(loc.location_code); }}
                data-testid={`btn-location-${loc.location_code}`}
                style={{
                  padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: selectedCode === loc.location_code ? 700 : 400,
                  border: `1px solid ${selectedCode === loc.location_code ? 'var(--accent)' : 'var(--border)'}`,
                  background: selectedCode === loc.location_code ? 'var(--accent-subtle)' : 'var(--card)',
                  color: selectedCode === loc.location_code ? 'var(--accent-text)' : 'var(--text-2)',
                  cursor: 'pointer',
                }}>
                {loc.location_code}
                {loc.location_type && <span style={{ marginLeft: 4, fontSize: 10, color: 'var(--text-3)' }}>({loc.location_type})</span>}
              </button>
            ))}
            {(!locations.locations || locations.locations.length === 0) && <span style={{ fontSize: 12, color: 'var(--text-3)' }}>No locations configured.</span>}
          </div>
        )}
        {detailLoading && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Loading inventory for {selectedCode}…</div>}
        {detailError && <div style={{ fontSize: 12, color: 'var(--badge-red-text)' }}>{detailError}</div>}
        {detail && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>
              {detail.location_code} · {detail.count} item{detail.count !== 1 ? 's' : ''}
            </div>
            {detail.count === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Location is empty.</div>
            ) : (
              <div style={{ overflowX: 'auto', maxHeight: 240, overflowY: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                      {['Scan code', 'Status', 'Design', 'Bag'].map(h => (
                        <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: 10 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.items || []).map((it, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '5px 10px', fontFamily: 'monospace', fontSize: 11 }}>{it.scan_code}</td>
                        <td style={{ padding: '5px 10px' }}><span style={{ fontSize: 11, color: 'var(--text-2)' }}>{it.current_status}</span></td>
                        <td style={{ padding: '5px 10px', color: 'var(--text-2)' }}>{it.design_no || '—'}</td>
                        <td style={{ padding: '5px 10px', color: 'var(--text-3)' }}>{it.bag_id || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-3)' }}>Read-only. No write calls are made from this panel.</div>
      </InvPanel>
    );
  }

  // ── Warehouse audit panel ───────────────────────────────────────────────────

  function AuditPanel() {
    const [batchId, setBatchId]       = useState('');
    const [activeMode, setActiveMode] = useState('');
    const [loading, setLoading]       = useState(false);
    const [data, setData]             = useState(null);
    const [error, setError]           = useState(null);

    const fetchSummary = useCallback(async () => {
      if (!batchId.trim()) return;
      setActiveMode('summary'); setLoading(true); setData(null); setError(null);
      try { setData(await apiFetch(`/api/v1/warehouse/audit-summary/${encodeURIComponent(batchId.trim())}`)); }
      catch (e) { setError((e && e.message) || String(e)); }
      finally { setLoading(false); }
    }, [batchId]);

    const fetchFull = useCallback(async () => {
      if (!batchId.trim()) return;
      setActiveMode('full'); setLoading(true); setData(null); setError(null);
      try { setData(await apiFetch(`/api/v1/warehouse/audit/${encodeURIComponent(batchId.trim())}`)); }
      catch (e) { setError((e && e.message) || String(e)); }
      finally { setLoading(false); }
    }, [batchId]);

    const pct     = data && (data.completion_pct || (data.summary && data.summary.completion_pct));
    const total   = data && (data.total_items || (data.summary && data.summary.total_items));
    const scanned = data && (data.scanned_items || (data.summary && data.summary.scanned_items));

    return (
      <InvPanel title="Warehouse audit" subtitle="Scan completion and anomaly detection for a batch" testid="panel-audit">
        <InvLabel>Batch ID</InvLabel>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <div style={{ flex: 1 }}><InvInput value={batchId} onChange={setBatchId} placeholder="e.g. SHIPMENT_…" data-testid="input-audit-batch-id" /></div>
          <InvFetchBtn onClick={fetchSummary} loading={loading && activeMode === 'summary'} label="Summary" disabled={!batchId.trim()} data-testid="btn-audit-summary" />
          <InvFetchBtn onClick={fetchFull}    loading={loading && activeMode === 'full'}    label="Full audit" disabled={!batchId.trim()} data-testid="btn-audit-full" />
        </div>
        {error && <div style={{ color: 'var(--badge-red-text)', fontSize: 12 }}>{error}</div>}
        {data && pct != null && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: pct >= 100 ? 'var(--ok-green)' : pct >= 80 ? 'var(--badge-amber-text)' : 'var(--badge-red-text)', borderRadius: 4, transition: 'width 0.4s' }} />
              </div>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', minWidth: 44 }}>{pct != null ? pct.toFixed(1) : '—'}%</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{scanned} scanned · {total} total · {data.missing_items || (data.summary && data.summary.missing_items) || 0} missing</div>
          </div>
        )}
        {data && activeMode === 'full' && (
          <div style={{ fontSize: 12 }}>
            {data.missing_scans && data.missing_scans.length > 0 && <div style={{ color: 'var(--badge-amber-text)', marginBottom: 4 }}>⚠ {data.missing_scans.length} unscanned item(s)</div>}
            {data.stuck_inventory && data.stuck_inventory.length > 0 && <div style={{ color: 'var(--badge-amber-text)', marginBottom: 4 }}>⚠ {data.stuck_inventory.length} stuck at RECV location(s)</div>}
            {data.invalid_flows && data.invalid_flows.length > 0 && <div style={{ color: 'var(--badge-red-text)', marginBottom: 4 }}>✗ {data.invalid_flows.length} invalid scan flow(s)</div>}
            {data.orphan_inventory && data.orphan_inventory.length > 0 && <div style={{ color: 'var(--badge-red-text)', marginBottom: 4 }}>✗ {data.orphan_inventory.length} orphan inventory record(s)</div>}
            {data.missing_scans && data.stuck_inventory && data.invalid_flows && data.orphan_inventory &&
              data.missing_scans.length === 0 && data.stuck_inventory.length === 0 && data.invalid_flows.length === 0 && data.orphan_inventory.length === 0 &&
              <div style={{ color: 'var(--ok-green)', fontWeight: 600 }}>✓ No anomalies detected.</div>}
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--text-2)' }}>Show raw JSON ▸</summary>
              <ResultBox data={data} error={null} />
            </details>
          </div>
        )}
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-3)' }}>Read-only. No write calls are made from this panel.</div>
      </InvPanel>
    );
  }

  // ── Promotion Notes panel (Phase B slice B2 — the BE-2 v1 document viewer;
  //    PROJECT_STATE DECISIONS "Phase B slices B2+B3") ─────────────────────────
  //    Read-only viewer over the Stock Promotion Note document trail
  //    (BE-1/BE-2/BE-2b: every production Temp→Final promotion yields exactly
  //    one Note). Transports live in pz-api.js (getPromotionNotes /
  //    getPromotionNote — note_no is slash-bearing, encoded per segment).

  function PromotionNotesPanel() {
    const [batchId, setBatchId]         = useState('');
    const [loading, setLoading]         = useState(false);
    const [data, setData]               = useState(null);
    const [error, setError]             = useState(null);
    const [openNote, setOpenNote]       = useState(null);
    const [noteLoading, setNoteLoading] = useState('');

    const fetchNotes = useCallback(async () => {
      if (!batchId.trim()) return;
      setLoading(true); setData(null); setError(null); setOpenNote(null);
      const r = await window.PzApi.getPromotionNotes(batchId.trim());
      setLoading(false);
      if (!r.ok) { setError(r.error || ('HTTP ' + r.status)); return; }
      setData(r.data || null);
    }, [batchId]);

    const toggleNote = useCallback(async (noteNo) => {
      if (openNote && openNote.note_no === noteNo) { setOpenNote(null); return; }
      setNoteLoading(noteNo);
      const r = await window.PzApi.getPromotionNote(noteNo);
      setNoteLoading('');
      if (r.ok) setOpenNote(r.data || null);
      else setError(r.error || ('HTTP ' + r.status));
    }, [openNote]);

    const th = { textAlign: 'left', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.04em', padding: '6px 8px', borderBottom: '1px solid var(--border)' };
    const td = { fontSize: 12, color: 'var(--text)', padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' };

    return (
      <InvPanel title="Promotion notes" subtitle="Stock Promotion Note document trail — one Note per Temp→Final movement (SPN series)" testid="panel-promotion-notes">
        <InvLabel>Batch ID</InvLabel>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <div style={{ flex: 1 }}><InvInput value={batchId} onChange={setBatchId} placeholder="e.g. SHIPMENT_…" data-testid="input-notes-batch-id" /></div>
          <InvFetchBtn onClick={fetchNotes} loading={loading} label="Load notes" disabled={!batchId.trim()} data-testid="btn-notes-fetch" />
        </div>
        {error && <div style={{ color: 'var(--badge-red-text)', fontSize: 12 }}>{error}</div>}
        {data && data.total === 0 && (
          <div data-testid="notes-empty" style={{ padding: '12px', border: '1px dashed var(--border)', borderRadius: 6, fontSize: 12, color: 'var(--text-3)' }}>
            No promotion notes for this batch — no Temp→Final movement has been documented yet (honest empty).
          </div>
        )}
        {data && data.total > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="notes-table">
            <thead>
              <tr>
                <th style={th}>Note no</th><th style={th}>Trigger</th><th style={th}>Pieces</th>
                <th style={th}>Operator</th><th style={th}>Created</th><th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {data.notes.map(n => (
                <React.Fragment key={n.note_no}>
                  <tr data-testid="notes-row">
                    <td style={{ ...td, fontFamily: 'ui-monospace, monospace', fontWeight: 700 }}>{n.note_no}</td>
                    <td style={td}>{n.trigger}</td>
                    <td style={td}>{n.piece_count}</td>
                    <td style={td}>{n.operator || '—'}</td>
                    <td style={{ ...td, color: 'var(--text-3)' }}>{(n.created_at || '').slice(0, 19)}</td>
                    <td style={td}>
                      <button onClick={() => toggleNote(n.note_no)} data-testid="btn-note-expand"
                        style={{ fontSize: 11, border: '1px solid var(--border)', background: 'transparent', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', color: 'var(--text-2)' }}>
                        {noteLoading === n.note_no ? '…' : (openNote && openNote.note_no === n.note_no ? 'Hide' : 'Lines')}
                      </button>
                    </td>
                  </tr>
                  {openNote && openNote.note_no === n.note_no && (
                    <tr>
                      <td colSpan={6} style={{ padding: '4px 8px 12px' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="notes-lines">
                          <thead>
                            <tr><th style={th}>Scan code</th><th style={th}>Design</th><th style={th}>Before</th><th style={th}>After</th></tr>
                          </thead>
                          <tbody>
                            {(openNote.lines || []).map(l => (
                              <tr key={l.scan_code}>
                                <td style={{ ...td, fontFamily: 'ui-monospace, monospace' }}>{l.scan_code}</td>
                                <td style={td}>{l.design_no || '—'}</td>
                                <td style={td}>{l.state_before}</td>
                                <td style={td}>{l.state_after}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-3)' }}>Read-only. No write calls are made from this panel.</div>
      </InvPanel>
    );
  }

  // ── Move Stock modal (Phase B FOLD — Lesson M relocation of Move Location
  //    into the Inventory authority; PROJECT_STATE DECISIONS "Phase B FOLD").
  //    Ported from the wireframe MoveStockModal (design/inventory-page.design.jsx
  //    lines 1023-1142), RESTYLED to that modal. The wireframe's stock_unit
  //    PASTE input is FORBIDDEN by the operator rule (no raw internal-ID
  //    paste) — replaced by the only non-paste live feed: source-location
  //    SELECT → pieces-at-location CHECKBOX list → destination-location SELECT.
  //    Behavior carried from move-location-page: sequential per-piece moves,
  //    per-piece results, five error states, synthetic-disable. Pending-badged
  //    (backend-pending — Phase C): unlocated-stock selection + Stage transition.

  const MS_ERROR_HINTS = {
    INVALID_INPUT:     '400 INVALID_INPUT — a required field (piece, destination, operator, idempotency key) was missing or blank',
    PIECE_NOT_FOUND:   '404 PIECE_NOT_FOUND — piece unknown to inventory_state / packing_lines',
    WRONG_STATE:       '409 WRONG_STATE — piece not in WAREHOUSE_STOCK, cannot move',
    DB_UNAVAILABLE:    '503 DB_UNAVAILABLE — warehouse DB not initialised on the server',
    MIGRATION_PENDING: '503 MIGRATION_PENDING — idempotency migration not applied: operator must run 20260512_002516_idempotency_key against warehouse.db',
  };
  function msClassifyError(res) {
    const txt = String((res && res.error) || '');
    for (const code of Object.keys(MS_ERROR_HINTS)) if (txt.includes(code)) return code;
    if (res && res.status === 400) return 'INVALID_INPUT';
    if (res && res.status === 404) return 'PIECE_NOT_FOUND';
    if (res && res.status === 409) return 'WRONG_STATE';
    if (res && res.status === 503) return 'DB_UNAVAILABLE';
    return 'UNKNOWN';
  }

  function MoveStockModal({ onClose }) {
    const [moveType, setMoveType]   = useState('wh-wh');   // wh-wh | stage(pending)
    const [locs, setLocs]           = useState(null);
    const [locErr, setLocErr]       = useState('');
    const [source, setSource]       = useState('');
    const [pieces, setPieces]       = useState(null);
    const [pieceErr, setPieceErr]   = useState('');
    const [loadingPieces, setLoadingPieces] = useState(false);
    const [selected, setSelected]   = useState({});        // scan_code -> true
    const [dest, setDest]           = useState('');
    const [note, setNote]           = useState('');
    const [moving, setMoving]       = useState(false);
    const [results, setResults]     = useState(null);

    useEffect(() => {
      window.PzApi.getWarehouseLocations().then(r => {
        if (!r.ok) { setLocErr(r.error || ('HTTP ' + r.status)); return; }
        setLocs((r.data && r.data.locations) || []);
      });
    }, []);

    const loadPieces = useCallback((code) => {
      setSource(code); setSelected({}); setResults(null); setPieces(null); setPieceErr('');
      if (!code) return;
      setLoadingPieces(true);
      window.PzApi.getLocationInventory(code).then(r => {
        setLoadingPieces(false);
        if (!r.ok) { setPieceErr(r.error || ('HTTP ' + r.status)); return; }
        setPieces((r.data && r.data.items) || []);
      });
    }, []);

    const toggle = (sc) => setSelected(s => ({ ...s, [sc]: !s[sc] }));
    const selectedCodes = Object.keys(selected).filter(k => selected[k]);
    const canMove = moveType === 'wh-wh' && selectedCodes.length > 0 && dest.trim() && dest !== source && !moving;

    const submit = async () => {
      if (!canMove) return;
      setMoving(true); setResults([]);
      const rows = [];
      for (const code of selectedCodes) {
        const r = await window.PzApi.movePieceLocation(code, {
          toLocation: dest.trim(), idempotencyKey: crypto.randomUUID(), note,
        });
        if (r.ok) rows.push({ scan_code: code, outcome: (r.data && r.data.status) || 'moved', code: '', hint: '', detail: (r.data && r.data.to_location) || '' });
        else { const ec = msClassifyError(r); rows.push({ scan_code: code, outcome: 'failed', code: ec, hint: MS_ERROR_HINTS[ec] || ('HTTP ' + r.status), detail: r.error || '' }); }
        setResults(rows.slice());
      }
      setMoving(false);
    };

    const fld = { width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', fontSize: 12, color: 'var(--text)', background: 'var(--card)', outline: 'none', fontFamily: 'inherit' };
    const lbl = { display: 'block', fontSize: 10, fontWeight: 700, color: 'var(--text-2)', marginBottom: 5, letterSpacing: '0.06em', textTransform: 'uppercase' };
    const locName = (l) => `${l.location_code}${l.warehouse ? ' — ' + l.warehouse : ''}`;

    return (
      <window.Modal title="Move Stock" onClose={onClose} wide>
        <div data-testid="move-stock-modal">
          {/* Move-type toggle — wh→wh wired; stage transition pending (Phase C) */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16, padding: 4, background: 'var(--bg-subtle)', borderRadius: 8, border: '1px solid var(--border)' }}>
            {[
              { id: 'wh-wh', testid: 'ms-type-wh-wh', title: 'Warehouse → Warehouse', desc: 'Physical location transfer', pending: false },
              { id: 'stage', testid: 'ms-type-stage', title: 'Stage transition', desc: 'Main → Sample / Consignment / RTP', pending: true },
            ].map(opt => (
              <button key={opt.id} data-testid={opt.testid} onClick={() => !opt.pending && setMoveType(opt.id)}
                disabled={opt.pending}
                title={opt.pending ? 'backend-pending — Phase C' : ''}
                style={{ padding: '12px 14px', textAlign: 'left', borderRadius: 6, cursor: opt.pending ? 'not-allowed' : 'pointer',
                  opacity: opt.pending ? 0.55 : 1,
                  background: moveType === opt.id ? 'var(--card)' : 'transparent',
                  border: moveType === opt.id ? '1px solid var(--accent)' : '1px solid transparent' }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  {opt.title}
                  {opt.pending && <span style={{ fontSize: 8.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', border: '1px solid var(--badge-amber-border)' }}>BACKEND-PENDING · PHASE C</span>}
                </div>
                <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{opt.desc}</div>
              </button>
            ))}
          </div>

          {/* Honest-mechanics banner */}
          <div data-testid="ms-banner" style={{ marginBottom: 14, padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 11.5, color: 'var(--text-2)' }}>
            Batch = sequential single-piece moves (backend is per-piece). Metadata-only write — lifecycle state is not changed. Selection is from the source-location list (no ID paste).
          </div>

          {/* Source location select */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
            <div>
              <label style={lbl}>Source location</label>
              {locErr && <div style={{ fontSize: 11, color: 'var(--badge-red-text)' }}>{locErr}</div>}
              <select data-testid="ms-source" value={source} onChange={e => loadPieces(e.target.value)} style={fld}>
                <option value="">— select a location —</option>
                {(locs || []).map(l => <option key={l.location_code} value={l.location_code}>{locName(l)}</option>)}
              </select>
            </div>
            <div>
              <label style={lbl}>Destination location</label>
              <select data-testid="ms-destination" value={dest} onChange={e => setDest(e.target.value)} style={fld}>
                <option value="">— select a destination —</option>
                {(locs || []).filter(l => l.location_code !== source).map(l => <option key={l.location_code} value={l.location_code}>{locName(l)}</option>)}
              </select>
            </div>
          </div>

          {/* Pieces at source */}
          {loadingPieces && <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 12 }}>Loading pieces…</div>}
          {pieceErr && <div style={{ fontSize: 12, color: 'var(--badge-red-text)', marginBottom: 12 }}>{pieceErr}</div>}
          {pieces && pieces.length === 0 && (
            <div data-testid="ms-empty" style={{ marginBottom: 12, padding: 12, border: '1px dashed var(--border)', borderRadius: 6, fontSize: 12, color: 'var(--text-3)' }}>
              No pieces at this location (honest empty — inventory_current_location has no rows here).
            </div>
          )}
          {pieces && pieces.length > 0 && (
            <table data-testid="ms-table" style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 14 }}>
              <thead><tr>
                {['', 'Piece (scan_code)', 'Design', 'Product code', 'Status'].map(h => (
                  <th key={h} style={{ padding: '6px 8px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.04em', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {pieces.map(p => {
                  const synthetic = !!p.synthetic;
                  const sc = p.scan_code;
                  return (
                    <tr key={sc}>
                      <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
                        <input type="checkbox" data-testid="ms-row-checkbox" checked={!!selected[sc]} disabled={synthetic}
                          title={synthetic ? 'projection — not movable (would 409 WRONG_STATE)' : ''} onChange={() => toggle(sc)} />
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 12, fontFamily: 'ui-monospace, monospace', borderBottom: '1px solid var(--border-subtle)' }}>{sc}</td>
                      <td style={{ padding: '6px 8px', fontSize: 12, borderBottom: '1px solid var(--border-subtle)' }}>{p.design_no || '—'}</td>
                      <td style={{ padding: '6px 8px', fontSize: 12, borderBottom: '1px solid var(--border-subtle)' }}>{p.product_code || '—'}</td>
                      <td style={{ padding: '6px 8px', fontSize: 12, color: 'var(--text-3)', borderBottom: '1px solid var(--border-subtle)' }}>{p.current_status || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {/* Note */}
          <div style={{ marginBottom: 14 }}>
            <label style={lbl}>Reason / note</label>
            <textarea data-testid="ms-note" value={note} onChange={e => setNote(e.target.value)} rows="2" style={{ ...fld, resize: 'vertical' }} placeholder="Optional — recorded on each piece's movement event" />
          </div>

          {/* Pending-badge: unlocated stock selection has no non-paste feed yet */}
          <div data-testid="ms-pending-unlocated" style={{ marginBottom: 16, padding: '10px 12px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-amber-text)' }}>
            <strong>Backend-pending — Phase C.</strong> Moving freshly-received stock not yet placed at a location is not available here — that needs a non-paste by-stage picker (no ID-paste box by design).
          </div>

          {results && (
            <div data-testid="ms-results" style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>Per-piece results ({results.length}/{selectedCodes.length})</div>
              {results.map(r => (
                <div key={r.scan_code} data-testid="ms-result-row" style={{ padding: '6px 8px', fontSize: 12, borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 10 }}>
                  <span style={{ fontFamily: 'ui-monospace, monospace' }}>{r.scan_code}</span>
                  <span style={{ fontWeight: 700, color: r.outcome === 'failed' ? 'var(--badge-red-text)' : 'var(--badge-green-text)' }}>{r.outcome}</span>
                  {r.code && <span style={{ color: 'var(--badge-red-text)' }}>{r.hint}</span>}
                  {!r.code && r.detail && <span style={{ color: 'var(--text-3)' }}>→ {r.detail}</span>}
                </div>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <window.Btn variant="outline" onClick={onClose} data-testid="ms-cancel">Cancel</window.Btn>
            <window.Btn variant="gold" onClick={submit} disabled={!canMove} data-testid="ms-submit">
              {moving ? 'Moving…' : `Move ${selectedCodes.length} piece(s) → location`}
            </window.Btn>
          </div>
        </div>
      </window.Modal>
    );
  }

  // ── InventoryPage — shell entry point ───────────────────────────────────────

  function InventoryPage({ openViewer }) {  // openViewer accepted; read panels are read-only
    // Title + subtitle are provided by the shell <PageHeader> (index.html inventory route).
    // The read panels below make no write calls; the ONLY write surface is the
    // Move Stock modal (Phase B FOLD — Lesson M relocation of Move Location).
    const [showMove, setShowMove] = useState(false);
    return (
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '28px 24px' }} data-testid="inventory-hub-root">
        {/* Move Stock action — the folded Move Location capability (no standalone page) */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
          <button data-testid="btn-open-move-stock" onClick={() => setShowMove(true)}
            style={{ padding: '8px 16px', borderRadius: 8, border: '1px solid var(--accent)', background: 'var(--accent)', color: 'var(--accent-text)', fontSize: 12.5, fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            ⇄ Move Stock
          </button>
        </div>
        {showMove && <MoveStockModal onClose={() => setShowMove(false)} />}

        <Stage2Panel />
        <BatchPanel />
        <PiecePanel />
        <LocationPanel />
        <AuditPanel />
        <PromotionNotesPanel />

        <div style={{ marginTop: 8, padding: '12px 16px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11, color: 'var(--text-3)', lineHeight: 1.5 }}>
          <strong style={{ color: 'var(--text-2)' }}>Read-only endpoints:</strong>{' '}
          /inventory/stage2/aggregate &middot; /inventory/state/&#123;batch_id&#125; &middot;
          /inventory/pieces/&#123;piece_id&#125; &middot; /warehouse/inventory/&#123;scan_code&#125; &middot;
          /warehouse/locations &middot; /warehouse/locations/&#123;code&#125;/inventory &middot;
          /warehouse/audit-summary/&#123;batch_id&#125; &middot; /warehouse/audit/&#123;batch_id&#125; &middot;
          /inventory/promotion-notes/&#123;batch_id&#125; &middot; /inventory/promotion-note/&#123;note_no&#125;
        </div>
      </div>
    );
  }

  window.InventoryPage = InventoryPage;
})();

window.DocumentViewerPage = DocumentViewerPage;
