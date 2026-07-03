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

  // ── Sample Out tab — Wave-3 / U-1 ─────────────────────────────────────────
  // Wireframe §7 Tab 7 (SampleOutTab).
  // Gap rows addressed: IV-SO-1, IV-SO-2, IV-SO-3, IV-SO-4.
  // Backend: GET /api/v1/inventory/samples (routes_inventory_sample.py:149)
  //          POST /api/v1/inventory/pieces/{id}/sample-out (routes_inventory_sample.py:91)
  // No placeholder data; honest empty state when register is empty.

  const SAMPLE_REASON_LABELS = {
    customer_review:  'Customer Review',
    quality_check:    'Quality Check',
    marketing_photo:  'Marketing Photo',
    trade_show:       'Trade Show',
    other:            'Other',
  };

  function daysLeft(expectedReturnDate) {
    if (!expectedReturnDate) return null;
    const diffMs = new Date(expectedReturnDate) - new Date();
    return Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  }

  function DaysLeftChip({ expectedReturnDate, status }) {
    if (status === 'returned') {
      return <span style={{ fontSize: 11, color: 'var(--badge-green-text)' }}>—</span>;
    }
    const d = daysLeft(expectedReturnDate);
    if (d == null) return <span style={{ fontSize: 11, color: 'var(--text-3)' }}>—</span>;
    const tone = d < 0 ? 'red' : d <= 3 ? 'amber' : 'green';
    const bg     = `var(--badge-${tone}-bg)`;
    const color  = `var(--badge-${tone}-text)`;
    const border = `var(--badge-${tone}-border)`;
    return (
      <span data-testid="so-days-left" style={{ display: 'inline-flex', alignItems: 'center', background: bg, color, border: `1px solid ${border}`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap' }}>
        {d < 0 ? `${Math.abs(d)}d overdue` : d === 0 ? 'Due today' : `${d}d left`}
      </span>
    );
  }

  function SampleStatusChip({ status }) {
    const MAP = {
      open:     { label: 'Out',      bg: 'var(--badge-amber-bg)',   color: 'var(--badge-amber-text)',   border: 'var(--badge-amber-border)' },
      returned: { label: 'Returned', bg: 'var(--badge-green-bg)',   color: 'var(--badge-green-text)',   border: 'var(--badge-green-border)' },
    };
    const s = MAP[status] || { label: status || '?', bg: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)', border: 'var(--badge-neutral-border)' };
    return (
      <span data-testid="so-status-chip" style={{ display: 'inline-flex', alignItems: 'center', background: s.bg, color: s.color, border: `1px solid ${s.border}`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap' }}>
        {s.label}
      </span>
    );
  }

  // Issue Sample modal — submits POST /api/v1/inventory/pieces/{piece_id}/sample-out
  function IssueSampleModal({ onClose, onSuccess }) {
    const [pieceId, setPieceId]           = useState('');
    const [recipient, setRecipient]       = useState('');
    const [reason, setReason]             = useState('customer_review');
    const [returnDate, setReturnDate]     = useState('');
    const [notes, setNotes]               = useState('');
    const [submitting, setSubmitting]     = useState(false);
    const [err, setErr]                   = useState('');

    function genKey() {
      return 'so-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    }

    async function submit() {
      setErr('');
      const pid = pieceId.trim();
      const rec = recipient.trim();
      if (!pid)  { setErr('Piece ID (scan code) is required.'); return; }
      if (!rec)  { setErr('Recipient client name is required.'); return; }
      if (!returnDate) { setErr('Expected return date is required.'); return; }
      setSubmitting(true);
      const res = await window.PzApi.issueSampleOut(pid, {
        recipient_client_name: rec,
        recipient_client_id:   '',
        expected_return_date:  returnDate,
        sample_reason:         reason,
        idempotency_key:       genKey(),
        notes:                 notes.trim(),
      });
      setSubmitting(false);
      if (!res.ok) {
        const detail = (res.data && res.data.detail && res.data.detail.detail) ||
                       (res.data && res.data.detail) || res.error || ('HTTP ' + res.status);
        setErr(String(detail));
        return;
      }
      onSuccess();
    }

    const lbl = { fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4, display: 'block' };
    const fld = { width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, boxSizing: 'border-box' };

    return (
      <window.Modal title="Issue Sample Out" onClose={onClose}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={lbl} htmlFor="so-piece-id">Piece ID (scan code)</label>
            <input id="so-piece-id" data-testid="so-piece-id" value={pieceId} onChange={e => setPieceId(e.target.value)} placeholder="e.g. ABC001|sr01|RG-001" style={fld} />
          </div>
          <div>
            <label style={lbl} htmlFor="so-recipient">Recipient client name</label>
            <input id="so-recipient" data-testid="so-recipient" value={recipient} onChange={e => setRecipient(e.target.value)} placeholder="Client or salesperson name" style={fld} />
          </div>
          <div>
            <label style={lbl} htmlFor="so-reason">Purpose / reason</label>
            <select id="so-reason" data-testid="so-reason" value={reason} onChange={e => setReason(e.target.value)} style={fld}>
              {Object.entries(SAMPLE_REASON_LABELS).map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={lbl} htmlFor="so-return-date">Expected return date</label>
            <input id="so-return-date" data-testid="so-return-date" type="date" value={returnDate} onChange={e => setReturnDate(e.target.value)} style={fld} />
          </div>
          <div>
            <label style={lbl} htmlFor="so-notes">Notes (optional)</label>
            <textarea id="so-notes" data-testid="so-notes" value={notes} onChange={e => setNotes(e.target.value)} rows="2" style={{ ...fld, resize: 'vertical' }} placeholder="Free-text note recorded with the sample event" />
          </div>
          {err && (
            <div data-testid="so-error" style={{ padding: '8px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)' }}>
              {err}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
            <window.Btn variant="outline" onClick={onClose} data-testid="so-cancel">Cancel</window.Btn>
            <window.Btn onClick={submit} disabled={submitting} data-testid="so-submit-issue">
              {submitting ? 'Issuing…' : 'Issue Sample Out'}
            </window.Btn>
          </div>
        </div>
      </window.Modal>
    );
  }

  function SampleOutTab({ onRecordReturn }) {
    const [samples, setSamples]     = useState(null);
    const [loading, setLoading]     = useState(true);
    const [error, setError]         = useState('');
    const [statusFilter, setStatus] = useState('');      // '' | 'open' | 'returned'
    const [recipFilter, setRecip]   = useState('');
    const [showIssue, setShowIssue] = useState(false);

    const load = useCallback(async () => {
      setLoading(true);
      setError('');
      const params = {};
      if (statusFilter) params.status = statusFilter;
      if (recipFilter.trim()) params.recipient = recipFilter.trim();
      const res = await window.PzApi.getInventorySamples(params);
      setLoading(false);
      if (!res.ok) {
        setError(res.error || ('HTTP ' + res.status));
        return;
      }
      setSamples((res.data && res.data.samples) || []);
    }, [statusFilter, recipFilter]);

    useEffect(() => { load(); }, [load]);

    // Derived KPI counts from loaded data (or null if still loading)
    const kpis = React.useMemo(() => {
      if (!samples) return null;
      const now = new Date();
      let activeOut = 0, closingSoon = 0, overdue = 0, returned = 0;
      for (const s of samples) {
        if (s.status === 'returned') { returned++; continue; }
        activeOut++;
        const d = daysLeft(s.expected_return_date);
        if (d != null && d < 0)        overdue++;
        else if (d != null && d <= 3)  closingSoon++;
      }
      return { activeOut, closingSoon, overdue, returned };
    }, [samples]);

    const TH = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
    const TD = { padding: '8px 10px', fontSize: 12.5, borderBottom: '1px solid var(--border-subtle)', color: 'var(--text)', verticalAlign: 'middle' };

    return (
      <div data-testid="sample-out-tab" style={{ maxWidth: 1100, margin: '0 auto' }}>
        {showIssue && (
          <IssueSampleModal
            onClose={() => setShowIssue(false)}
            onSuccess={() => { setShowIssue(false); load(); }}
          />
        )}

        {/* KPI strip — 4 tiles per wireframe §7 Tab 7 */}
        {kpis && (
          <div data-testid="so-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
            <InvStatTile testid="so-kpi-active"   label="Active out"           value={kpis.activeOut}   tone="amber" />
            <InvStatTile testid="so-kpi-closing"  label="Closing soon (≤3 days)" value={kpis.closingSoon} tone="amber" />
            <InvStatTile testid="so-kpi-overdue"  label="Overdue"              value={kpis.overdue}     tone="red"   />
            <InvStatTile testid="so-kpi-returned" label="Returned (mo.)"       value={kpis.returned}    tone="green" />
          </div>
        )}
        {loading && !samples && (
          <div data-testid="so-kpi-loading" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
            {['Active out','Closing soon (≤3 days)','Overdue','Returned (mo.)'].map(l => (
              <InvStatTile key={l} label={l} value={null} />
            ))}
          </div>
        )}

        {/* Toolbar: filters + Issue Sample button */}
        <div data-testid="so-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          {/* Status filter */}
          <select data-testid="so-filter-status" value={statusFilter} onChange={e => setStatus(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, cursor: 'pointer' }}>
            <option value="">All statuses</option>
            <option value="open">Open / Out</option>
            <option value="returned">Returned</option>
          </select>
          {/* Recipient filter */}
          <input data-testid="so-filter-recipient" value={recipFilter} onChange={e => setRecip(e.target.value)}
            placeholder="Filter by recipient…" style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, minWidth: 180, flex: 1 }} />
          <InvFetchBtn data-testid="so-refresh" onClick={load} loading={loading} label="↻ Refresh" />
          {/* + Issue Sample — labels exactly what it writes (Lesson: every write button labels the write) */}
          <button data-testid="btn-issue-sample" onClick={() => setShowIssue(true)}
            style={{ padding: '7px 16px', borderRadius: 8, border: '1px solid var(--accent)', background: 'var(--accent)', color: 'var(--accent-text)', fontSize: 12.5, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}>
            + Issue Sample
          </button>
        </div>

        {/* Error state */}
        {error && (
          <div data-testid="so-error-banner" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-red-text)' }}>
            Failed to load samples: {error}
          </div>
        )}

        {/* Register table — 10 columns per wireframe */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="so-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)' }}>
                  {/* 10 columns exactly per wireframe §7 Tab 7 */}
                  <th style={TH}>Sample ID</th>
                  <th style={TH}>Source SU</th>
                  <th style={TH}>Design</th>
                  <th style={TH}>Qty</th>
                  <th style={TH}>Issued to</th>
                  <th style={TH}>Purpose</th>
                  <th style={TH}>Issued</th>
                  <th style={TH}>Return by</th>
                  <th style={TH}>Days left</th>
                  <th style={TH}>Status</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={11} style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '28px 0' }}>Loading…</td></tr>
                )}
                {!loading && samples && samples.length === 0 && (
                  <tr>
                    <td colSpan={11} data-testid="so-empty" style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '32px 0', fontStyle: 'italic' }}>
                      No sample records{statusFilter ? ` with status "${statusFilter}"` : ''}{recipFilter ? ` matching "${recipFilter}"` : ''}.
                    </td>
                  </tr>
                )}
                {!loading && samples && samples.map(s => {
                  const isOut = s.status === 'open';
                  const scanShort = s.scan_code || '—';
                  // Extract design from scan_code (format: product_code|design or product_code|sr01|design)
                  const parts = (s.scan_code || '').split('|');
                  const design = parts.length >= 3 ? parts[2] : (parts.length === 2 ? parts[1] : '—');
                  const issuedDate = s.out_at ? s.out_at.slice(0, 10) : '—';
                  return (
                    <tr key={s.sample_id} data-testid="so-row" style={{ background: 'var(--card)' }}>
                      <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5 }}>{s.sample_id || '—'}</td>
                      <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5 }}>{scanShort}</td>
                      <td style={TD}>{design}</td>
                      <td style={TD}>1</td>
                      <td style={TD}>{s.recipient_client_name || '—'}</td>
                      <td style={TD}>{SAMPLE_REASON_LABELS[s.sample_reason] || s.sample_reason || '—'}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)' }}>{issuedDate}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'ui-monospace, monospace' }}>
                        {s.expected_return_date || '—'}
                      </td>
                      <td style={TD}>
                        <DaysLeftChip expectedReturnDate={s.expected_return_date} status={s.status} />
                      </td>
                      <td style={TD}>
                        <SampleStatusChip status={s.status} />
                      </td>
                      <td style={{ ...TD, textAlign: 'right', whiteSpace: 'nowrap' }}>
                        {/* Row actions per wireframe: Record Return (if out/overdue) · View */}
                        {isOut && (
                          <button data-testid="so-btn-record-return"
                            onClick={() => onRecordReturn && onRecordReturn(s)}
                            style={{ marginRight: 6, padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--badge-amber-border)', background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', cursor: 'pointer' }}>
                            Record Return
                          </button>
                        )}
                        <button data-testid="so-btn-view" disabled title="backend-pending — detail view (future slice)"
                          style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed', opacity: 0.6 }}>
                          View
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* Endpoint reference */}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          Register: GET /api/v1/inventory/samples · Issue: POST /api/v1/inventory/pieces/&#123;id&#125;/sample-out
        </div>
      </div>
    );
  }

  // ── Sample Return tab — Wave-3 / U-1 page 2 ──────────────────────────────
  // Wireframe SampleReturnTab (docs/design/inventory-page.design.jsx:433–479).
  // Gap rows addressed: IV-SR-1, IV-SR-2, IV-SR-3, IV-SR-4.
  // Backend GET: GET /api/v1/inventory/samples?status=returned (routes_inventory_sample.py:149)
  // Backend POST: POST /api/v1/inventory/pieces/{id}/sample-return (routes_inventory_sample.py:125)
  // No QC outcome writes (Inspect action, condition, inspector, decision fields) —
  //   no backend exists; Lesson-M honest-disabled with reason title.

  // Record Return modal — submits POST /api/v1/inventory/pieces/{piece_id}/sample-return
  function RecordReturnModal({ sample, onClose, onSuccess }) {
    const [notes, setNotes]           = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [err, setErr]               = useState('');

    function genKey() {
      return 'sr-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    }

    async function submit() {
      setErr('');
      const scanCode = (sample && sample.scan_code) || '';
      if (!scanCode) { setErr('No scan code on this sample record — cannot record return.'); return; }
      setSubmitting(true);
      const res = await window.PzApi.recordSampleReturn(scanCode, {
        idempotency_key: genKey(),
        notes: notes.trim(),
      });
      setSubmitting(false);
      if (!res.ok) {
        const detail = (res.data && res.data.detail && res.data.detail.detail) ||
                       (res.data && res.data.detail) || res.error || ('HTTP ' + res.status);
        setErr(String(detail));
        return;
      }
      onSuccess();
    }

    const lbl = { fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4, display: 'block' };
    const fld = { width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, boxSizing: 'border-box' };

    const scanShort = (sample && sample.scan_code) || '—';
    const parts = (sample && sample.scan_code ? sample.scan_code.split('|') : []);
    const design = parts.length >= 3 ? parts[2] : (parts.length === 2 ? parts[1] : '—');

    return (
      <window.Modal title="Record Sample Return" onClose={onClose}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Info band — shows which piece is being returned */}
          <div style={{ padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}>
            <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>Piece: <span style={{ fontFamily: 'ui-monospace, monospace' }}>{scanShort}</span></div>
            <div style={{ color: 'var(--text-2)' }}>Design: {design}</div>
            <div style={{ color: 'var(--text-2)' }}>Issued to: {(sample && sample.recipient_client_name) || '—'}</div>
            <div style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 4 }}>
              This will move the piece SAMPLE_OUT → WAREHOUSE_STOCK. Action is idempotent.
            </div>
          </div>
          <div>
            <label style={lbl} htmlFor="sr-notes">Notes (optional)</label>
            <textarea id="sr-notes" data-testid="sr-notes" value={notes} onChange={e => setNotes(e.target.value)} rows="2"
              style={{ ...fld, resize: 'vertical' }} placeholder="Condition note, reason, or any remark recorded with the return event" />
          </div>
          {/* QC outcome fields: no backend exists; Lesson-M honest-disabled */}
          <details>
            <summary data-testid="sr-qc-expand" style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer', userSelect: 'none' }}>
              QC / Inspect fields (Condition · Inspector · Decision) ▸
            </summary>
            <div style={{ marginTop: 10, padding: '10px 12px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-amber-text)' }}>
              <strong>Backend-pending — Phase C (future slice).</strong> QC outcome writes
              (condition, inspector assignment, decision: Restock / Repair / Write-off) have no
              backend route — the POST /api/v1/inventory/pieces/&#123;id&#125;/sample-return
              contract accepts only operator, idempotency_key, notes. These fields are not
              wired per Lesson M (capability suppression only with a cancellation record;
              here there is no cancellation, just no backend yet).
            </div>
          </details>
          {err && (
            <div data-testid="sr-error" style={{ padding: '8px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)' }}>
              {err}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
            <window.Btn variant="outline" onClick={onClose} data-testid="sr-cancel">Cancel</window.Btn>
            <window.Btn onClick={submit} disabled={submitting} data-testid="sr-submit-return">
              {submitting ? 'Recording…' : 'Record Sample Return'}
            </window.Btn>
          </div>
        </div>
      </window.Modal>
    );
  }

  function SampleReturnTab() {
    const [samples, setSamples]       = useState(null);
    const [loading, setLoading]       = useState(true);
    const [error, setError]           = useState('');
    const [recipFilter, setRecip]     = useState('');
    const [returnModal, setReturnModal] = useState(null); // sample record to record-return on

    const load = useCallback(async () => {
      setLoading(true);
      setError('');
      const params = { status: 'returned' };
      if (recipFilter.trim()) params.recipient = recipFilter.trim();
      const res = await window.PzApi.getInventorySamples(params);
      setLoading(false);
      if (!res.ok) {
        setError(res.error || ('HTTP ' + res.status));
        return;
      }
      setSamples((res.data && res.data.samples) || []);
    }, [recipFilter]);

    useEffect(() => { load(); }, [load]);

    // Derived KPI counts from loaded data (wireframe: 4 tiles)
    // KPI data: "awaiting inspection" / "in repair" / "restocked mo." / "written off mo."
    // The backend return event carries no condition/decision/inspector — all three are
    // QC fields with no backend. We can derive "total returned" but not the sub-buckets.
    // Show total as "Restocked (mo.)" pending the QC backend. Others shown as pending.
    const totalReturned = samples ? samples.length : null;

    const TH = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
    const TD = { padding: '8px 10px', fontSize: 12.5, borderBottom: '1px solid var(--border-subtle)', color: 'var(--text)', verticalAlign: 'middle' };

    return (
      <div data-testid="sample-return-tab" style={{ maxWidth: 1100, margin: '0 auto' }}>
        {returnModal && (
          <RecordReturnModal
            sample={returnModal}
            onClose={() => setReturnModal(null)}
            onSuccess={() => { setReturnModal(null); load(); }}
          />
        )}

        {/* KPI strip — 4 tiles per wireframe SampleReturnTab:442–447 */}
        <div data-testid="sr-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          {/* Awaiting inspection / In repair / Written off — QC sub-buckets have no backend;
              Lesson-M pending tile. Restocked total is derivable from returned count. */}
          <InvStatTile testid="sr-kpi-awaiting"  label="Awaiting inspection" pending hint="QC outcome writes — future slice" />
          <InvStatTile testid="sr-kpi-repair"    label="In repair"           pending hint="QC outcome writes — future slice" />
          <InvStatTile testid="sr-kpi-restocked" label="Returned (total)"    value={totalReturned} tone="green" hint="all returned this register" />
          <InvStatTile testid="sr-kpi-writeoff"  label="Written off (mo.)"   pending hint="QC outcome writes — future slice" />
        </div>

        {/* Toolbar: recipient filter + Refresh */}
        <div data-testid="sr-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <input data-testid="sr-filter-recipient" value={recipFilter} onChange={e => setRecip(e.target.value)}
            placeholder="Filter by recipient…" style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, minWidth: 180, flex: 1 }} />
          <InvFetchBtn data-testid="sr-refresh" onClick={load} loading={loading} label="↻ Refresh" />
        </div>

        {/* Error state */}
        {error && (
          <div data-testid="sr-error-banner" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-red-text)' }}>
            Failed to load sample returns: {error}
          </div>
        )}

        {/* Register table — 10 columns per wireframe SampleReturnTab:453–473
            Columns: Return ID · Sample ID · Design · Qty · Returned from ·
                     Received · Condition · Inspector · Decision · Status · Actions */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Samples returned from sales / clients</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="sr-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)' }}>
                  {/* 10 columns exactly per wireframe SampleReturnTab */}
                  <th style={TH}>Return ID</th>
                  <th style={TH}>Sample ID</th>
                  <th style={TH}>Design</th>
                  <th style={TH}>Qty</th>
                  <th style={TH}>Returned from</th>
                  <th style={TH}>Received</th>
                  <th style={TH}>Condition</th>
                  <th style={TH}>Inspector</th>
                  <th style={TH}>Decision</th>
                  <th style={TH}>Status</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={11} style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '28px 0' }}>Loading…</td></tr>
                )}
                {!loading && samples && samples.length === 0 && (
                  <tr>
                    <td colSpan={11} data-testid="sr-empty" style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '32px 0', fontStyle: 'italic' }}>
                      No sample returns{recipFilter ? ` matching "${recipFilter}"` : ''} — register is empty (honest empty).
                    </td>
                  </tr>
                )}
                {!loading && samples && samples.map(s => {
                  const scanShort = s.scan_code || '—';
                  const parts = (s.scan_code || '').split('|');
                  const design = parts.length >= 3 ? parts[2] : (parts.length === 2 ? parts[1] : '—');
                  // Return ID: use return_event_id (the actual return event ID from the DB)
                  const returnId = s.return_event_id ? ('SR-' + String(s.return_event_id).slice(0, 8)) : '—';
                  const receivedDate = s.returned_at ? s.returned_at.slice(0, 10) : '—';
                  return (
                    <tr key={s.sample_id} data-testid="sr-row" style={{ background: 'var(--card)' }}>
                      <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5, fontWeight: 700 }}>{returnId}</td>
                      <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: 'var(--text-3)' }}>{s.sample_id || '—'}</td>
                      <td style={TD}>{design}</td>
                      <td style={TD}>1</td>
                      <td style={TD}>{s.recipient_client_name || '—'}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'ui-monospace, monospace' }}>{receivedDate}</td>
                      {/* Condition, Inspector, Decision — QC fields: no backend; Lesson-M honest */}
                      <td style={{ ...TD, color: 'var(--text-3)' }}>
                        <span title="backend-pending — QC outcome writes (future slice)" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-3)' }}>—</span>
                      </td>
                      <td style={{ ...TD, color: 'var(--text-3)' }}>
                        <span title="backend-pending — inspector assignment (future slice)" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-3)' }}>—</span>
                      </td>
                      <td style={{ ...TD, color: 'var(--text-3)' }}>
                        <span title="backend-pending — QC decision (future slice)" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-3)' }}>—</span>
                      </td>
                      <td style={TD}>
                        {/* Returned = piece is back in WAREHOUSE_STOCK; status is always "Returned" here */}
                        <span style={{ display: 'inline-flex', alignItems: 'center', background: 'var(--badge-green-bg)', color: 'var(--badge-green-text)', border: '1px solid var(--badge-green-border)', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                          Returned
                        </span>
                      </td>
                      <td style={{ ...TD, textAlign: 'right', whiteSpace: 'nowrap' }}>
                        {/* Inspect action: QC outcome writes have no backend — Lesson-M honest-disabled */}
                        <button data-testid="sr-btn-inspect" disabled title="backend-pending — QC outcome writes (Inspect/condition/decision) have no backend route yet (future slice)"
                          style={{ marginRight: 6, padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--badge-amber-border)', background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', cursor: 'not-allowed', opacity: 0.5 }}>
                          Inspect
                        </button>
                        {/* View action: no detail endpoint yet — Lesson-M honest-disabled */}
                        <button data-testid="sr-btn-view" disabled title="backend-pending — detail view (future slice)"
                          style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed', opacity: 0.6 }}>
                          View
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* Endpoint reference */}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          Register: GET /api/v1/inventory/samples?status=returned · Record return: POST /api/v1/inventory/pieces/&#123;id&#125;/sample-return
        </div>
      </div>
    );
  }

  // ── Client Return tab — Wave-3 / U-2 page 3 ─────────────────────────────
  // Wireframe §7 Tab 9 (ClientReturnTab / GoodsReturnPage).
  // Gap rows addressed: IV-CR-1, IV-CR-2.
  // Backend GET:  GET /api/v1/inventory/returns?direction=from_client
  //               (routes_inventory_returns.py:212; C-3a/C-3c, LIVE)
  // Backend POST: POST /api/v1/inventory/pieces/{id}/return-from-client
  //               (routes_inventory_returns.py:116; C-3a, LIVE)
  // Wireframe status vocabulary: from_client rows are always status='recorded'.
  // No credit-note/debit-note wFirma writes: no backend — Lesson-M honest-disabled.
  // No Condition/Decision fields: no backend — Lesson-M honest-disabled.
  // No placeholder data; honest empty state when register is empty.

  // Return reason enum → display label (matches backend enum from routes_inventory_returns.py:43–52)
  const CLIENT_RETURN_REASON_LABELS = {
    warranty_claim:             'Warranty Claim',
    customer_refused:           'Customer Refused',
    post_sample_review_reject:  'Post-Sample Review Reject',
    dimension_issue:            'Dimension Issue',
    quality_complaint:          'Quality Complaint',
    wrong_item_shipped:         'Wrong Item Shipped',
    other:                      'Other',
  };

  // Record Client Return modal — submits POST /api/v1/inventory/pieces/{pieceId}/return-from-client
  function RecordClientReturnModal({ onClose, onSuccess }) {
    const [pieceId, setPieceId]       = useState('');
    const [client, setClient]         = useState('');
    const [reason, setReason]         = useState('quality_complaint');
    const [originCtx, setOriginCtx]   = useState('');
    const [receivedAt, setReceivedAt] = useState('');
    const [notes, setNotes]           = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [err, setErr]               = useState('');

    function genKey() {
      return 'cr-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    }

    async function submit() {
      setErr('');
      const pid = pieceId.trim();
      const ori = originCtx.trim();
      const rec = receivedAt.trim();
      if (!pid) { setErr('Piece scan code is required.'); return; }
      if (!ori) { setErr('Origin context (RMA # or invoice ref) is required.'); return; }
      if (!rec) { setErr('Received-at date/time is required.'); return; }
      setSubmitting(true);
      const res = await window.PzApi.recordClientReturn(pid, {
        return_reason:      reason,
        origin_context:     ori,
        received_at:        rec,
        source_holder_name: client.trim(),
        idempotency_key:    genKey(),
        notes:              notes.trim(),
      });
      setSubmitting(false);
      if (!res.ok) {
        const detail = (res.data && res.data.detail && res.data.detail.detail) ||
                       (res.data && res.data.detail) || res.error || ('HTTP ' + res.status);
        setErr(String(detail));
        return;
      }
      onSuccess();
    }

    const lbl = { fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4, display: 'block' };
    const fld = { width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, boxSizing: 'border-box' };

    return (
      <window.Modal title="Record Client Return" onClose={onClose}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Info band */}
          <div style={{ padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5 }}>
            Records an inbound RMA from a client. Piece moves
            <strong style={{ color: 'var(--text)' }}> WAREHOUSE_STOCK / SAMPLE_OUT → RETURNED_FROM_CLIENT</strong>.
            Action is idempotent — duplicate submissions with the same scan code return the prior event.
          </div>

          {/* Piece scan code */}
          <div>
            <label style={lbl} htmlFor="cr-piece-id">Piece scan code <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <input id="cr-piece-id" data-testid="cr-piece-id" value={pieceId} onChange={e => setPieceId(e.target.value)}
              style={fld} placeholder="e.g. EJL001|sr1|RG-10025" />
          </div>

          {/* Client name */}
          <div>
            <label style={lbl} htmlFor="cr-client">Client name (optional — who returned it)</label>
            <input id="cr-client" data-testid="cr-client" value={client} onChange={e => setClient(e.target.value)}
              style={fld} placeholder="e.g. Aurum Trading" />
          </div>

          {/* Origin context (invoice/RMA ref) */}
          <div>
            <label style={lbl} htmlFor="cr-origin">Origin context — RMA # or invoice ref <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <input id="cr-origin" data-testid="cr-origin-context" value={originCtx} onChange={e => setOriginCtx(e.target.value)}
              style={fld} placeholder="e.g. RMA-0044 or INV 2025/0412" />
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 3 }}>
              Stored as the audit identifier for this return event (stored in notes field).
            </div>
          </div>

          {/* Return reason */}
          <div>
            <label style={lbl} htmlFor="cr-reason">Return reason <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <select id="cr-reason" data-testid="cr-reason" value={reason} onChange={e => setReason(e.target.value)} style={fld}>
              {Object.entries(CLIENT_RETURN_REASON_LABELS).map(([v, l]) =>
                <option key={v} value={v}>{l}</option>
              )}
            </select>
          </div>

          {/* Received at */}
          <div>
            <label style={lbl} htmlFor="cr-received-at">Received at (ISO 8601) <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <input id="cr-received-at" data-testid="cr-received-at" type="datetime-local" value={receivedAt} onChange={e => setReceivedAt(e.target.value)}
              style={fld} />
          </div>

          {/* Notes */}
          <div>
            <label style={lbl} htmlFor="cr-notes">Notes (optional)</label>
            <textarea id="cr-notes" data-testid="cr-notes" value={notes} onChange={e => setNotes(e.target.value)} rows="2"
              style={{ ...fld, resize: 'vertical' }} placeholder="Condition observation, packing state, etc." />
          </div>

          {/* Credit note / debit note: no backend — Lesson-M honest-disabled */}
          <details>
            <summary data-testid="cr-wfirma-expand" style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer', userSelect: 'none' }}>
              Credit note / Debit note (wFirma write) ▸
            </summary>
            <div style={{ marginTop: 10, padding: '10px 12px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-amber-text)' }}>
              <strong>Backend-pending — Phase C (future slice).</strong> Credit-note and debit-note
              wFirma writes have no backend route — the POST /api/v1/inventory/pieces/&#123;id&#125;/return-from-client
              contract does not produce a wFirma document. These actions are not wired per Lesson M
              (capability suppression only with a cancellation record; here there is no cancellation,
              just no backend yet). Census tag: IV-CR-2.
            </div>
          </details>

          {/* Error display */}
          {err && (
            <div data-testid="cr-error" style={{ padding: '8px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)' }}>
              {err}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
            <window.Btn variant="outline" onClick={onClose} data-testid="cr-cancel">Cancel</window.Btn>
            <window.Btn onClick={submit} disabled={submitting} data-testid="cr-submit-return">
              {submitting ? 'Recording…' : 'Record Client Return'}
            </window.Btn>
          </div>
        </div>
      </window.Modal>
    );
  }

  function ClientReturnTab() {
    const [records, setRecords]         = useState(null);
    const [loading, setLoading]         = useState(true);
    const [error, setError]             = useState('');
    const [clientFilter, setClientFilter] = useState('');
    const [showModal, setShowModal]     = useState(false);

    const load = useCallback(async () => {
      setLoading(true);
      setError('');
      const params = { direction: 'from_client' };
      const res = await window.PzApi.getInventoryReturns(params);
      setLoading(false);
      if (!res.ok) {
        setError(res.error || ('HTTP ' + res.status));
        return;
      }
      setRecords((res.data && res.data.returns) || []);
    }, []);

    useEffect(() => { load(); }, [load]);

    // Derived KPI counts from loaded data (wireframe: 4 implied tiles)
    // Backend only has 'recorded' status for from_client; QC sub-buckets have no backend.
    const totalRecorded     = records ? records.length : null;
    const filteredRecords   = records
      ? records.filter(r => {
          if (!clientFilter.trim()) return true;
          const cf = clientFilter.trim().toLowerCase();
          return (r.source_holder_name || '').toLowerCase().includes(cf);
        })
      : [];

    const TH = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
    const TD = { padding: '8px 10px', fontSize: 12.5, borderBottom: '1px solid var(--border-subtle)', color: 'var(--text)', verticalAlign: 'middle' };

    return (
      <div data-testid="client-return-tab" style={{ maxWidth: 1100, margin: '0 auto' }}>
        {showModal && (
          <RecordClientReturnModal
            onClose={() => setShowModal(false)}
            onSuccess={() => { setShowModal(false); load(); }}
          />
        )}

        {/* KPI strip — 4 implied tiles per wireframe §7 Tab 9 */}
        <div data-testid="cr-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          {/* Awaiting inspection / Inspected / Routed to RTP — QC sub-buckets have no backend;
              Lesson-M pending tile. Total recorded is derivable. */}
          <InvStatTile testid="cr-kpi-awaiting"  label="Awaiting inspection" pending hint="QC outcome writes — future slice (census IV-CR-2)" />
          <InvStatTile testid="cr-kpi-inspected" label="Inspected"           pending hint="QC outcome writes — future slice (census IV-CR-2)" />
          <InvStatTile testid="cr-kpi-recorded"  label="Recorded (total)"    value={totalRecorded} tone="green" hint="all from_client returns in register" />
          <InvStatTile testid="cr-kpi-rtp"       label="Routed to RTP"       pending hint="QC outcome writes — future slice (census IV-CR-2)" />
        </div>

        {/* Toolbar: client filter + Record button + Refresh */}
        <div data-testid="cr-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <input data-testid="cr-filter-client" value={clientFilter} onChange={e => setClientFilter(e.target.value)}
            placeholder="Filter by client…" style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, minWidth: 180, flex: 1 }} />
          <window.Btn onClick={() => setShowModal(true)} data-testid="cr-btn-record-return">
            + Record Client Return
          </window.Btn>
          <InvFetchBtn data-testid="cr-refresh" onClick={load} loading={loading} label="↻ Refresh" />
        </div>

        {/* Error state */}
        {error && (
          <div data-testid="cr-error-banner" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-red-text)' }}>
            Failed to load client returns: {error}
          </div>
        )}

        {/* Register table — columns per wireframe §7 Tab 9:
            RMA ID · Invoice · Client · Design · Qty · Value · Reason · Received · Condition · Decision · Status · Actions
            (Wireframe lists 10 data cols; Value/Condition/Decision have no backend — Lesson-M honest) */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Client RMAs — goods returned from clients</span>
            {records !== null && (
              <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                {filteredRecords.length} of {records.length} record(s)
              </span>
            )}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="cr-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)' }}>
                  {/* 10 columns per wireframe §7 Tab 9 */}
                  <th style={TH}>RMA ID</th>
                  <th style={TH}>Invoice / Origin</th>
                  <th style={TH}>Client</th>
                  <th style={TH}>Design</th>
                  <th style={TH}>Qty</th>
                  <th style={TH}>Value</th>
                  <th style={TH}>Reason</th>
                  <th style={TH}>Received</th>
                  <th style={TH}>Condition</th>
                  <th style={TH}>Decision</th>
                  <th style={TH}>Status</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={12} style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '28px 0' }}>Loading…</td></tr>
                )}
                {!loading && records && filteredRecords.length === 0 && (
                  <tr>
                    <td colSpan={12} data-testid="cr-empty" style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '32px 0', fontStyle: 'italic' }}>
                      No client returns{clientFilter ? ` matching "${clientFilter}"` : ''} — register is empty (honest empty).
                    </td>
                  </tr>
                )}
                {!loading && filteredRecords.map(r => {
                  // RMA ID: short prefix from event id
                  const rmaId = r.id ? ('RMA-' + String(r.id).slice(0, 8).toUpperCase()) : '—';
                  // Invoice / Origin: origin_context stored in notes field (inventory_returns_writer.py:155)
                  const invoiceRef = r.notes || '—';
                  // Client: source_holder_name
                  const clientName = r.source_holder_name || '—';
                  // Design: derived from scan_code (same algorithm as other tabs)
                  const parts = (r.scan_code || '').split('|');
                  const design = parts.length >= 3 ? parts[2] : (parts.length === 2 ? parts[1] : (r.scan_code || '—'));
                  // Qty: always 1 (single-piece tracking)
                  const qty = 1;
                  // Reason: enum → display label
                  const reasonLabel = CLIENT_RETURN_REASON_LABELS[r.return_reason] || r.return_reason || '—';
                  // Received: received_at date portion
                  const receivedDate = r.received_at ? r.received_at.slice(0, 10) : (r.occurred_at ? r.occurred_at.slice(0, 10) : '—');

                  return (
                    <tr key={r.id} data-testid="cr-row" style={{ background: 'var(--card)' }}>
                      <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5, fontWeight: 700 }}>{rmaId}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'ui-monospace, monospace' }}>{invoiceRef}</td>
                      <td style={TD}>{clientName}</td>
                      <td style={TD}>{design}</td>
                      <td style={TD}>{qty}</td>
                      {/* Value — no backend field; Lesson-M honest */}
                      <td style={{ ...TD, color: 'var(--text-3)' }}>
                        <span title="backend-pending — value field not in returns_events schema (future slice)" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-3)' }}>—</span>
                      </td>
                      <td style={TD}>{reasonLabel}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'ui-monospace, monospace' }}>{receivedDate}</td>
                      {/* Condition — QC field: no backend; Lesson-M honest */}
                      <td style={{ ...TD, color: 'var(--text-3)' }}>
                        <span title="backend-pending — QC condition writes (future slice)" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-3)' }}>—</span>
                      </td>
                      {/* Decision — QC field: no backend; Lesson-M honest */}
                      <td style={{ ...TD, color: 'var(--text-3)' }}>
                        <span title="backend-pending — QC decision (Restock/Repair/RTP) writes (future slice)" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-3)' }}>—</span>
                      </td>
                      <td style={TD}>
                        {/* Status: from_client rows are always 'recorded' per routes_inventory_returns.py:212 */}
                        <span style={{ display: 'inline-flex', alignItems: 'center', background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)', border: '1px solid var(--badge-neutral-border)', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                          {r.status || 'recorded'}
                        </span>
                      </td>
                      <td style={{ ...TD, textAlign: 'right', whiteSpace: 'nowrap' }}>
                        {/* Inspect action: QC outcome writes have no backend — Lesson-M honest-disabled */}
                        <button data-testid="cr-btn-inspect" disabled title="backend-pending — QC outcome writes (Inspect/condition/decision) have no backend route yet (future slice)"
                          style={{ marginRight: 6, padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--badge-amber-border)', background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', cursor: 'not-allowed', opacity: 0.5 }}>
                          Inspect
                        </button>
                        {/* Credit Note: wFirma write — no backend; Lesson-M honest-disabled */}
                        <button data-testid="cr-btn-credit-note" disabled title="backend-pending — credit note wFirma write has no backend route yet (future slice; census IV-CR-2)"
                          style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed', opacity: 0.6 }}>
                          Credit Note
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* Endpoint reference */}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          Register: GET /api/v1/inventory/returns?direction=from_client · Record: POST /api/v1/inventory/pieces/&#123;id&#125;/return-from-client
        </div>
      </div>
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

  // ── Return to Producer tab — Wave-3 / U-2 page 4 ────────────────────────────
  // Wireframe §7 Tab 10 (ProducerReturnTab).
  // Backend GET:  GET /api/v1/inventory/returns?direction=to_producer
  //               (routes_inventory_returns.py:212; C-3c, LIVE)
  // Backend POST: POST /api/v1/inventory/pieces/{id}/return-to-producer
  //               (routes_inventory_returns.py:148; LIVE)
  //               POST /api/v1/inventory/pieces/{id}/return-from-producer
  //               (routes_inventory_returns.py:181; LIVE — restock leg)
  // Wireframe columns (10): RTP ID · Source · Design · Qty · Supplier · Reason ·
  //   Prepared · AWB out · Status · Actions
  // Wireframe KPI tiles (4): In preparation · Awaiting AWB · In transit · Confirmed (mo.)
  // Lifecycle: open (RETURNED_TO_PRODUCER, no dispatch_reference = in preparation;
  //            with dispatch_reference = awaiting AWB added / in transit)
  //            resolved (producer_restock event linked = confirmed by producer)
  // Add AWB: dispatch_reference is supplied at return-to-producer creation time
  //          (POST body field). No backend route exists to UPDATE dispatch_reference
  //          on an existing returns_events row — Lesson-M honest-disabled with reason.
  // Return-from-producer: wired as "Confirm Received" on resolved rows — the
  //   scan_code must be in RETURNED_TO_PRODUCER state; operator confirms restock.

  const PRODUCER_RETURN_REASON_LABELS = {
    defect:                  'Defect',
    dimension_out_of_spec:   'Dimension Out of Spec',
    quality_reject:          'Quality Reject',
    post_inspection_reject:  'Post-Inspection Reject',
    recall:                  'Recall',
    other:                   'Other',
  };

  // ReturnToProducerModal — submits POST /api/v1/inventory/pieces/{pieceId}/return-to-producer
  function ReturnToProducerModal({ onClose, onSuccess }) {
    const [pieceId, setPieceId]     = useState('');
    const [producer, setProducer]   = useState('');
    const [producerId, setProducerId] = useState('');
    const [reason, setReason]       = useState('defect');
    const [dispatchRef, setDispatchRef] = useState('');
    const [resDate, setResDate]     = useState('');
    const [notes, setNotes]         = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [err, setErr]             = useState('');

    function genKey() {
      return 'rtp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    }

    async function submit() {
      setErr('');
      const pid  = pieceId.trim();
      const prod = producer.trim();
      if (!pid)  { setErr('Piece scan code is required.'); return; }
      if (!prod) { setErr('Producer / supplier name is required.'); return; }
      setSubmitting(true);
      const res = await window.PzApi.returnToProducer(pid, {
        producer_name:            prod,
        producer_id:              producerId.trim(),
        return_reason:            reason,
        dispatch_reference:       dispatchRef.trim(),
        expected_resolution_date: resDate.trim(),
        idempotency_key:          genKey(),
        notes:                    notes.trim(),
      });
      setSubmitting(false);
      if (!res.ok) {
        const detail = (res.data && res.data.detail && res.data.detail.detail) ||
                       (res.data && res.data.detail) || res.error || ('HTTP ' + res.status);
        setErr(String(detail));
        return;
      }
      onSuccess();
    }

    const lbl = { fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4, display: 'block' };
    const fld = { width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, boxSizing: 'border-box' };

    return (
      <window.Modal title="Return to Producer" onClose={onClose}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Info band */}
          <div style={{ padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5 }}>
            Records a piece shipped back to the producer. Piece moves
            <strong style={{ color: 'var(--text)' }}> WAREHOUSE_STOCK / RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER</strong>.
            Action is idempotent — duplicate submissions with the same scan code return the prior event.
          </div>

          {/* Piece scan code */}
          <div>
            <label style={lbl} htmlFor="rtp-piece-id">Piece scan code <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <input id="rtp-piece-id" data-testid="rtp-piece-id" value={pieceId} onChange={e => setPieceId(e.target.value)}
              style={fld} placeholder="e.g. EJL001|sr1|RG-10025" />
          </div>

          {/* Producer name */}
          <div>
            <label style={lbl} htmlFor="rtp-producer">Producer / supplier name <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <input id="rtp-producer" data-testid="rtp-producer" value={producer} onChange={e => setProducer(e.target.value)}
              style={fld} placeholder="e.g. Mehta Gems · MUM" />
          </div>

          {/* Producer ID (optional) */}
          <div>
            <label style={lbl} htmlFor="rtp-producer-id">Producer ID (optional wFirma contractor ref)</label>
            <input id="rtp-producer-id" data-testid="rtp-producer-id" value={producerId} onChange={e => setProducerId(e.target.value)}
              style={fld} placeholder="e.g. contractor-id-123" />
          </div>

          {/* Return reason */}
          <div>
            <label style={lbl} htmlFor="rtp-reason">Return reason <span style={{ color: 'var(--badge-red-text)' }}>*</span></label>
            <select id="rtp-reason" data-testid="rtp-reason" value={reason} onChange={e => setReason(e.target.value)} style={fld}>
              {Object.entries(PRODUCER_RETURN_REASON_LABELS).map(([v, l]) =>
                <option key={v} value={v}>{l}</option>
              )}
            </select>
          </div>

          {/* Dispatch reference / outbound AWB */}
          <div>
            <label style={lbl} htmlFor="rtp-dispatch-ref">Outbound AWB / dispatch reference (optional)</label>
            <input id="rtp-dispatch-ref" data-testid="rtp-dispatch-ref" value={dispatchRef} onChange={e => setDispatchRef(e.target.value)}
              style={fld} placeholder="e.g. DHL 123456789 or PRMA-0012" />
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 3 }}>
              Set at creation time. Cannot be updated after creation (no PATCH route — set now or leave blank).
            </div>
          </div>

          {/* Expected resolution date */}
          <div>
            <label style={lbl} htmlFor="rtp-res-date">Expected resolution date (optional)</label>
            <input id="rtp-res-date" data-testid="rtp-res-date" type="date" value={resDate} onChange={e => setResDate(e.target.value)}
              style={fld} />
          </div>

          {/* Notes */}
          <div>
            <label style={lbl} htmlFor="rtp-notes">Notes (optional)</label>
            <textarea id="rtp-notes" data-testid="rtp-notes" value={notes} onChange={e => setNotes(e.target.value)} rows="2"
              style={{ ...fld, resize: 'vertical' }} placeholder="Defect description, packing note, etc." />
          </div>

          {/* Debit note / wFirma: no backend — Lesson-M honest-disabled */}
          <details>
            <summary data-testid="rtp-wfirma-expand" style={{ fontSize: 11, color: 'var(--text-3)', cursor: 'pointer', userSelect: 'none' }}>
              Debit note (wFirma write) ▸
            </summary>
            <div style={{ marginTop: 10, padding: '10px 12px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 6, fontSize: 11, color: 'var(--badge-amber-text)' }}>
              <strong>Backend-pending — Phase C (future slice).</strong> Debit-note wFirma writes
              (reverse of PZ) have no backend route — this POST creates only the inventory event.
              These actions are not wired per Lesson M (no cancellation record, no backend yet).
              Census tag: IV-RTP-2.
            </div>
          </details>

          {/* Error display */}
          {err && (
            <div data-testid="rtp-error" style={{ padding: '8px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)' }}>
              {err}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
            <window.Btn variant="outline" onClick={onClose} data-testid="rtp-cancel">Cancel</window.Btn>
            <window.Btn onClick={submit} disabled={submitting} data-testid="rtp-submit">
              {submitting ? 'Recording…' : 'Return to Producer'}
            </window.Btn>
          </div>
        </div>
      </window.Modal>
    );
  }

  // ConfirmReceivedModal — submits POST /api/v1/inventory/pieces/{pieceId}/return-from-producer
  // Used on resolved rows to mark a piece as back in WAREHOUSE_STOCK.
  // Note: "resolved" in list_returns_records means the producer_restock event already
  // exists (linked_origin_event_id). This modal fires for "open" rows that have a
  // dispatch_reference (shipped) — the scan_code is still RETURNED_TO_PRODUCER.
  function ConfirmReceivedModal({ record, onClose, onSuccess }) {
    const [notes, setNotes]         = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [err, setErr]             = useState('');

    function genKey() {
      return 'rfp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    }

    async function submit() {
      setErr('');
      setSubmitting(true);
      const res = await window.PzApi.returnFromProducer(record.scan_code, {
        idempotency_key: genKey(),
        notes:           notes.trim(),
      });
      setSubmitting(false);
      if (!res.ok) {
        const detail = (res.data && res.data.detail && res.data.detail.detail) ||
                       (res.data && res.data.detail) || res.error || ('HTTP ' + res.status);
        setErr(String(detail));
        return;
      }
      onSuccess();
    }

    const lbl = { fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4, display: 'block' };
    const fld = { width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, boxSizing: 'border-box' };
    const rtpId = record.id ? ('RTP-' + String(record.id).slice(0, 8).toUpperCase()) : '—';

    return (
      <window.Modal title="Confirm Producer Receipt" onClose={onClose}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Info band */}
          <div style={{ padding: '10px 12px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5 }}>
            Marks <strong style={{ color: 'var(--text)' }}>{rtpId}</strong> (scan: <code style={{ fontSize: 11 }}>{record.scan_code}</code>) as
            received back from producer. Piece moves
            <strong style={{ color: 'var(--text)' }}> RETURNED_TO_PRODUCER → WAREHOUSE_STOCK</strong>.
          </div>

          {/* Notes */}
          <div>
            <label style={lbl} htmlFor="rfp-notes">Notes (optional)</label>
            <textarea id="rfp-notes" data-testid="rfp-notes" value={notes} onChange={e => setNotes(e.target.value)} rows="2"
              style={{ ...fld, resize: 'vertical' }} placeholder="Inspection outcome, condition on receipt, etc." />
          </div>

          {/* Error display */}
          {err && (
            <div data-testid="rfp-error" style={{ padding: '8px 12px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 6, fontSize: 12, color: 'var(--badge-red-text)' }}>
              {err}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
            <window.Btn variant="outline" onClick={onClose} data-testid="rfp-cancel">Cancel</window.Btn>
            <window.Btn onClick={submit} disabled={submitting} data-testid="rfp-submit">
              {submitting ? 'Confirming…' : 'Confirm Received'}
            </window.Btn>
          </div>
        </div>
      </window.Modal>
    );
  }

  function ProducerReturnTab() {
    const [records, setRecords]           = useState(null);
    const [loading, setLoading]           = useState(true);
    const [error, setError]               = useState('');
    const [supplierFilter, setSupplierFilter] = useState('');
    const [showModal, setShowModal]       = useState(false);
    const [confirmRecord, setConfirmRecord] = useState(null);

    const load = useCallback(async () => {
      setLoading(true);
      setError('');
      const res = await window.PzApi.getProducerReturns({ direction: 'to_producer' });
      setLoading(false);
      if (!res.ok) {
        setError(res.error || ('HTTP ' + res.status));
        return;
      }
      setRecords((res.data && res.data.returns) || []);
    }, []);

    useEffect(() => { load(); }, [load]);

    // Derived KPI counts
    // open = no resolution_event_id; resolved = resolution_event_id present
    // In preparation: open + no dispatch_reference
    // Awaiting AWB / In transit: open + dispatch_reference set
    // Confirmed (mo.): resolved — exact month boundary unknown from this data; show total resolved
    const inPreparation = records ? records.filter(r => r.status === 'open' && !(r.dispatch_reference || '').trim()).length : null;
    const awaitingOrTransit = records ? records.filter(r => r.status === 'open' && (r.dispatch_reference || '').trim()).length : null;
    const confirmed     = records ? records.filter(r => r.status === 'resolved').length : null;
    const totalOpen     = records ? records.filter(r => r.status === 'open').length : null;

    const filteredRecords = records
      ? records.filter(r => {
          if (!supplierFilter.trim()) return true;
          const sf = supplierFilter.trim().toLowerCase();
          return (r.producer_name || '').toLowerCase().includes(sf);
        })
      : [];

    const TH = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
    const TD = { padding: '8px 10px', fontSize: 12.5, borderBottom: '1px solid var(--border-subtle)', color: 'var(--text)', verticalAlign: 'middle' };

    return (
      <div data-testid="producer-return-tab" style={{ maxWidth: 1100, margin: '0 auto' }}>
        {showModal && (
          <ReturnToProducerModal
            onClose={() => setShowModal(false)}
            onSuccess={() => { setShowModal(false); load(); }}
          />
        )}
        {confirmRecord && (
          <ConfirmReceivedModal
            record={confirmRecord}
            onClose={() => setConfirmRecord(null)}
            onSuccess={() => { setConfirmRecord(null); load(); }}
          />
        )}

        {/* KPI strip — 4 tiles per wireframe §7 Tab 10 */}
        <div data-testid="rtp-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          <InvStatTile testid="rtp-kpi-preparation" label="In preparation"      value={inPreparation}   hint="open rows with no dispatch_reference (not yet shipped)" />
          <InvStatTile testid="rtp-kpi-awaiting"    label="Awaiting AWB / transit" value={awaitingOrTransit} tone="amber" hint="open rows with dispatch_reference set (shipped, awaiting confirmation)" />
          <InvStatTile testid="rtp-kpi-open"        label="Open (total)"        value={totalOpen}       hint="all open to_producer rows" />
          <InvStatTile testid="rtp-kpi-confirmed"   label="Confirmed by producer" value={confirmed}     tone="green" hint="rows where producer_restock event has landed (resolved)" />
        </div>

        {/* Toolbar: supplier filter + Return to Producer action + Refresh */}
        <div data-testid="rtp-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <input data-testid="rtp-filter-supplier" value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)}
            placeholder="Filter by supplier…" style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, minWidth: 180, flex: 1 }} />
          <window.Btn onClick={() => setShowModal(true)} data-testid="rtp-btn-record">
            + Return to Producer
          </window.Btn>
          <InvFetchBtn data-testid="rtp-refresh" onClick={load} loading={loading} label="↻ Refresh" />
        </div>

        {/* Error state */}
        {error && (
          <div data-testid="rtp-error-banner" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-red-text)' }}>
            Failed to load producer returns: {error}
          </div>
        )}

        {/* Register table — columns per wireframe §7 Tab 10:
            RTP ID · Source (scan_code) · Design · Qty · Supplier · Reason ·
            Prepared (occurred_at) · AWB out (dispatch_reference) · Status · Actions */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Producer RTPs — goods returned to suppliers</span>
            {records !== null && (
              <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                {filteredRecords.length} of {records.length} record(s)
              </span>
            )}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="rtp-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)' }}>
                  {/* 10 columns per wireframe §7 Tab 10 */}
                  <th style={TH}>RTP ID</th>
                  <th style={TH}>Source</th>
                  <th style={TH}>Design</th>
                  <th style={TH}>Qty</th>
                  <th style={TH}>Supplier</th>
                  <th style={TH}>Reason</th>
                  <th style={TH}>Prepared</th>
                  <th style={TH}>AWB out</th>
                  <th style={TH}>Status</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={10} style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '28px 0' }}>Loading…</td></tr>
                )}
                {!loading && records && filteredRecords.length === 0 && (
                  <tr>
                    <td colSpan={10} data-testid="rtp-empty" style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '32px 0', fontStyle: 'italic' }}>
                      No producer returns{supplierFilter ? ` matching "${supplierFilter}"` : ''} — register is empty (honest empty).
                    </td>
                  </tr>
                )}
                {!loading && filteredRecords.map(r => {
                  // RTP ID: short prefix from event id
                  const rtpId = r.id ? ('RTP-' + String(r.id).slice(0, 8).toUpperCase()) : '—';
                  // Source: scan_code
                  const source = r.scan_code || '—';
                  // Design: derived from scan_code (same algorithm as other tabs)
                  const parts  = (r.scan_code || '').split('|');
                  const design = parts.length >= 3 ? parts[2] : (parts.length === 2 ? parts[1] : (r.scan_code || '—'));
                  // Qty: always 1 (single-piece tracking)
                  const qty    = 1;
                  // Supplier: producer_name
                  const supplier = r.producer_name || '—';
                  // Reason: enum → display label
                  const reasonLabel = PRODUCER_RETURN_REASON_LABELS[r.return_reason] || r.return_reason || '—';
                  // Prepared: occurred_at date portion
                  const prepared = r.occurred_at ? r.occurred_at.slice(0, 10) : '—';
                  // AWB out: dispatch_reference (may be blank if not yet set)
                  const awbOut = (r.dispatch_reference || '').trim() || '—';
                  // Status derivation
                  // open + no dispatch_reference → In preparation
                  // open + dispatch_reference    → In transit
                  // resolved                     → Confirmed by producer
                  const isOpen     = r.status === 'open';
                  const hasDispatch = (r.dispatch_reference || '').trim().length > 0;
                  const isResolved = r.status === 'resolved';
                  let statusLabel, statusBg, statusColor, statusBorder;
                  if (isResolved) {
                    statusLabel  = 'Confirmed by producer';
                    statusBg     = 'var(--badge-green-bg)';
                    statusColor  = 'var(--badge-green-text)';
                    statusBorder = 'var(--badge-green-border)';
                  } else if (isOpen && hasDispatch) {
                    statusLabel  = 'In transit';
                    statusBg     = 'var(--badge-amber-bg)';
                    statusColor  = 'var(--badge-amber-text)';
                    statusBorder = 'var(--badge-amber-border)';
                  } else {
                    statusLabel  = 'In preparation';
                    statusBg     = 'var(--badge-neutral-bg)';
                    statusColor  = 'var(--badge-neutral-text)';
                    statusBorder = 'var(--badge-neutral-border)';
                  }

                  return (
                    <tr key={r.id} data-testid="rtp-row" style={{ background: 'var(--card)' }}>
                      <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5, fontWeight: 700 }}>{rtpId}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'ui-monospace, monospace', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={source}>{source}</td>
                      <td style={TD}>{design}</td>
                      <td style={TD}>{qty}</td>
                      <td style={TD}>{supplier}</td>
                      <td style={TD}>{reasonLabel}</td>
                      <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-2)', fontFamily: 'ui-monospace, monospace' }}>{prepared}</td>
                      <td style={{ ...TD, fontSize: 11.5, fontFamily: 'ui-monospace, monospace' }}>
                        {awbOut !== '—' ? awbOut : (
                          <span style={{ color: 'var(--text-3)', fontStyle: 'italic' }}>—</span>
                        )}
                      </td>
                      <td style={TD}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', background: statusBg, color: statusColor, border: `1px solid ${statusBorder}`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                          {statusLabel}
                        </span>
                      </td>
                      <td style={{ ...TD, textAlign: 'right', whiteSpace: 'nowrap' }}>
                        {/* Add AWB: no backend PATCH route to update dispatch_reference — Lesson-M honest-disabled */}
                        <button data-testid="rtp-btn-add-awb" disabled
                          title="backend-pending — no PATCH/PUT route exists to update dispatch_reference on an existing returns_events row; set AWB at creation time via + Return to Producer modal (future slice may add PATCH)"
                          style={{ marginRight: 6, padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--badge-amber-border)', background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', cursor: 'not-allowed', opacity: 0.5 }}>
                          Add AWB
                        </button>
                        {/* Confirm Received: POST return-from-producer — live only on open rows (still RETURNED_TO_PRODUCER state) */}
                        {isOpen ? (
                          <window.Btn
                            data-testid="rtp-btn-confirm-received"
                            onClick={() => setConfirmRecord(r)}
                            style={{ padding: '4px 10px', fontSize: 11.5 }}>
                            Confirm Received
                          </window.Btn>
                        ) : (
                          <button data-testid="rtp-btn-confirm-received" disabled
                            title="already resolved — producer_restock event has landed"
                            style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed', opacity: 0.6 }}>
                            Confirmed ✓
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* Endpoint reference */}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          Register: GET /api/v1/inventory/returns?direction=to_producer · Record: POST /api/v1/inventory/pieces/&#123;id&#125;/return-to-producer · Restock: POST /api/v1/inventory/pieces/&#123;id&#125;/return-from-producer
        </div>
      </div>
    );
  }

  // ── Temp Purchase tab — Wave-3 / U-3 page 7 ──────────────────────────────
  // Wireframe: inventory-page.design.jsx TempPurchaseTab (lines 6472–). Census #7, scope L.
  // Backend read:
  //   GET /api/v1/inventory/merchandising/{batch_id}  → C-3e joined read
  //     (routes_inventory.py:127; packing_lines ⋈ inventory_state per piece; LIVE)
  //   Response shape: { ok, batch_id, count, rows:[{scan_code, product_code, design_no,
  //     batch_no, pack_sr, ctg, client_po, karat, color, quality, dia_wt, size, qty, uom,
  //     gross_weight, net_weight, state}] }
  //   Client-side filter: rows where state === 'PURCHASE_TRANSIT' — the Temp Purchase population.
  //
  // 13-column merchandising table (wireframe exact columns / order):
  //   Pk Sr · Ctg · Client PO · Design No · Karat · Color · Quality · Dia Wt · Col Wt ·
  //   Qty · Size · State · Actions
  //   (Col Wt = net_weight from packing_lines; State = inventory_state badge; wireframe
  //   includes AWB and Total but those fields are not in the C-3e response — rendered as
  //   "—" honest empty per wireframe honesty rules; 13 columns incl. actions column)
  //
  // KPI tiles (4 per wireframe TempPurchaseTab stats):
  //   Open packing lists  · Awaiting goods (lines) · Partially arrived · Closed-out
  //   Mapping (honesty — C-3e has no status field; status is derived from inventory
  //   state: PURCHASE_TRANSIT="Awaiting goods"; absent state=""="Partially arrived"
  //   fallback; no row with state=WAREHOUSE_STOCK+ in merchandising means Closed-out
  //   count is not available from this endpoint — KPI shows PURCHASE_TRANSIT count and
  //   total; honest gap label where count is not resolvable):
  //     Open packing lists  = total rows in batch (all packing lines including non-PT)
  //     Awaiting goods      = rows with state === 'PURCHASE_TRANSIT' (the tab population)
  //     Partially arrived   = rows with state === '' (empty/missing, packing line exists
  //                           but no inventory_state entry yet; honest "unknown" fallback)
  //     Closed-out          = rows with state not PURCHASE_TRANSIT and not empty
  //                           (WAREHOUSE_STOCK or later — goods received)
  //
  // 3 actions (wireframe exactly traced):
  //   1. "View doc" — fires openViewer with packing-list document stub.
  //        Authority: DocumentViewerPage (shell-global, window.DocumentViewerPage);
  //        openViewer is passed from InventoryPage → TempPurchaseTab prop.
  //        Same pattern as SampleOutTab / existing DocumentViewerPage callers. LIVE.
  //   2. "Receive" (promote to warehouse) — dispatches inv:move CustomEvent +
  //        opens existing MoveStockModal in the parent InventoryPage.
  //        Authority: MoveStockModal (inventory-page.jsx:1755); run_stock_promotion()
  //        (stock_promotion.py) is the document-driven backend (BE-1). The MoveStock
  //        modal is the ONLY operator-facing UI for manual piece promotion. No second
  //        implementation allowed (WIREFRAME_AUTHORITY §D; task rule). Lesson-M note:
  //        this triggers the modal in "wh-wh" mode (location move); the actual
  //        PURCHASE_TRANSIT→WAREHOUSE_STOCK promotion is document-driven (BE-1 =
  //        run_stock_promotion, fired by dhl_delivery_service or PZ-booked trigger).
  //        The modal pre-fills the scan_code for the operator. Census tag: IV-TP-1.
  //   3. "Upload Packing List" (toolbar, not per-row) — Lesson-M honest-disabled.
  //        No upload endpoint for packing lists exists in routes_inventory.py.
  //        The existing Upload Document mechanism (inv:upload CustomEvent) targets
  //        the document hub (routes_upload), not packing list ingestion.
  //        Census tag: IV-TP-2 (future slice: POST /api/v1/packing-lists/upload).
  //
  // Stage-1 Document layer info banner: per wireframe verbatim.

  function TempPurchaseTab({ openViewer, onShowMove }) {
    const [batchId, setBatchId]   = useState('');
    const [loading, setLoading]   = useState(false);
    const [error, setError]       = useState('');
    const [rows, setRows]         = useState(null);  // all merchandising rows for batch

    const load = useCallback(async () => {
      const bid = batchId.trim();
      if (!bid) return;
      setLoading(true);
      setError('');
      setRows(null);

      const res = await window.PzApi.getMerchandisingView(bid);

      setLoading(false);
      if (!res.ok) {
        setError(res.error || ('HTTP ' + res.status));
        return;
      }
      setRows((res.data && res.data.rows) || []);
    }, [batchId]);

    // Derived: filter to PURCHASE_TRANSIT for the Temp Purchase population.
    const ptRows      = rows ? rows.filter(r => r.state === 'PURCHASE_TRANSIT') : [];
    const emptyRows   = rows ? rows.filter(r => !r.state) : [];
    const closedRows  = rows ? rows.filter(r => r.state && r.state !== 'PURCHASE_TRANSIT') : [];
    const totalRows   = rows ? rows.length : null;

    const TH = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
    const TD = { padding: '8px 10px', fontSize: 12.5, borderBottom: '1px solid var(--border-subtle)', color: 'var(--text)', verticalAlign: 'middle' };

    return (
      <div data-testid="temp-purchase-tab" style={{ maxWidth: 1100, margin: '0 auto' }}>

        {/* Stage-1 info banner — wireframe verbatim */}
        <div data-testid="tp-info-banner" style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--accent-bg)', border: '1px solid var(--accent-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <strong style={{ color: 'var(--text)' }}>Stage 1 — Document layer.</strong>
          {' '}These lines come from supplier invoices &amp; packing lists. Goods are{' '}
          <em>expected</em> but not physically confirmed. No final stock is created here.
          {' '}Population: pieces in <code style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>PURCHASE_TRANSIT</code> state.
        </div>

        {/* KPI strip — 4 tiles per wireframe TempPurchaseTab stats */}
        <div data-testid="tp-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          <InvStatTile testid="tp-kpi-open"       label="Open packing lists"     value={totalRows}         hint="All packing-list lines in selected batch" />
          <InvStatTile testid="tp-kpi-awaiting"   label="Awaiting goods (lines)" value={rows ? ptRows.length : null} tone="amber" hint="PURCHASE_TRANSIT — expected, not yet physically confirmed" />
          <InvStatTile testid="tp-kpi-partial"    label="Partially arrived"       value={rows ? emptyRows.length : null} tone="amber" hint="Packing line exists, no inventory state entry yet" />
          <InvStatTile testid="tp-kpi-closed"     label="Closed-out"             value={rows ? closedRows.length : null} tone="green" hint="State beyond PURCHASE_TRANSIT — goods received" />
        </div>

        {/* Batch selector toolbar */}
        <div data-testid="tp-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <input
            data-testid="tp-batch-input"
            value={batchId}
            onChange={e => setBatchId(e.target.value)}
            placeholder="Batch ID — e.g. SHIPMENT_4218922912_2026-05_…"
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, flex: 1, minWidth: 260 }}
          />
          <InvFetchBtn
            data-testid="tp-btn-load"
            onClick={load}
            loading={loading}
            disabled={!batchId.trim()}
            label="Load batch"
          />
          {rows !== null && (
            <InvFetchBtn data-testid="tp-refresh" onClick={load} loading={loading} label="↻ Refresh" />
          )}
          {/* Upload Packing List — Lesson-M honest-disabled: no upload endpoint for
              packing lists in routes_inventory.py; the document-hub inv:upload is a
              different surface. Census tag IV-TP-2 (future: POST /api/v1/packing-lists/upload). */}
          <button data-testid="tp-btn-upload" disabled
            title="backend-pending — no packing-list upload endpoint in routes_inventory.py; the document hub (inv:upload CustomEvent) targets general documents, not packing-list ingestion (IV-TP-2; future slice: POST /api/v1/packing-lists/upload)"
            style={{ padding: '7px 14px', fontSize: 12, fontWeight: 600, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed', opacity: 0.5 }}>
            + Upload Packing List
          </button>
        </div>

        {/* Error state */}
        {error && (
          <div data-testid="tp-error-banner" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-red-text)' }}>
            Failed to load merchandising view: {error}
          </div>
        )}

        {/* Prompt before load */}
        {!loading && rows === null && !error && (
          <div data-testid="tp-prompt" style={{ padding: '28px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 13, fontStyle: 'italic' }}>
            Enter a batch ID above and click Load batch to view PURCHASE_TRANSIT packing-list lines.
          </div>
        )}

        {/* Register table — 13 columns per wireframe TempPurchaseTab */}
        {rows !== null && (
          <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Open packing-list lines</span>
                <span style={{ display: 'inline-flex', alignItems: 'center', background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-text)', border: '1px solid var(--badge-neutral-border)', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>from invoices &amp; packing lists</span>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                  {ptRows.length} PURCHASE_TRANSIT · {rows.length} total · batch:{' '}
                  <code style={{ fontFamily: 'ui-monospace, monospace', background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>{batchId.trim()}</code>
                </span>
              </div>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table data-testid="tp-table" style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)' }}>
                    {/* 13 columns: Pk Sr · Ctg · Client PO · Design No · Karat · Color ·
                        Quality · Dia Wt · Col Wt · Qty · Size · State · Actions */}
                    <th style={{ ...TH, textAlign: 'right' }}>Pk Sr</th>
                    <th style={TH}>Ctg</th>
                    <th style={TH}>Client PO</th>
                    <th style={TH}>Design No</th>
                    <th style={TH}>Karat</th>
                    <th style={TH}>Color</th>
                    <th style={TH}>Quality</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Dia Wt</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Col Wt</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Qty</th>
                    <th style={TH}>Size</th>
                    <th style={TH}>State</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr><td colSpan={13} style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '28px 0' }}>Loading…</td></tr>
                  )}
                  {!loading && ptRows.length === 0 && (
                    <tr>
                      <td colSpan={13} data-testid="tp-empty" style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '32px 0', fontStyle: 'italic' }}>
                        No PURCHASE_TRANSIT lines in this batch — register is empty (honest empty).
                      </td>
                    </tr>
                  )}
                  {!loading && ptRows.map((r, i) => {
                    const sc       = r.scan_code || '';
                    const packSr   = r.pack_sr != null ? r.pack_sr : '—';
                    const ctg      = r.ctg || '—';
                    const clientPo = r.client_po || '—';
                    const designNo = r.design_no || r.product_code || '—';
                    const karat    = r.karat || '—';
                    const color    = r.color || '—';
                    const quality  = r.quality || '—';
                    const diaWt    = r.dia_wt != null ? r.dia_wt : '—';
                    // Col Wt = net_weight from packing_lines (advisory, may be absent)
                    const colWt    = r.net_weight != null ? r.net_weight : '—';
                    const qty      = r.qty != null ? r.qty : '—';
                    const size     = r.size || '—';

                    return (
                      <tr key={sc + i} data-testid="tp-row" style={{ background: 'var(--card)' }}>
                        <td style={{ ...TD, textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: 'var(--text-2)' }}>{packSr}</td>
                        <td style={TD}>{ctg}</td>
                        <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5 }}>{clientPo}</td>
                        <td style={{ ...TD, fontFamily: 'ui-monospace, monospace', fontSize: 11.5, fontWeight: 700, color: 'var(--text)' }}>{designNo}</td>
                        <td style={TD}>{karat}</td>
                        <td style={TD}>{color}</td>
                        <td style={TD}>{quality}</td>
                        <td style={{ ...TD, textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11.5 }}>{diaWt}</td>
                        <td style={{ ...TD, textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontSize: 11.5, color: 'var(--text-2)' }}>{colWt}</td>
                        <td style={{ ...TD, textAlign: 'right', fontWeight: 700 }}>{qty}</td>
                        <td style={TD}>{size}</td>
                        <td style={TD}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', background: 'var(--badge-blue-bg)', color: 'var(--badge-blue-text)', border: '1px solid var(--badge-blue-border)', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                            In Transit
                          </span>
                        </td>
                        <td style={{ ...TD, textAlign: 'right', whiteSpace: 'nowrap' }}>
                          {/* View doc: fires openViewer with packing-list stub.
                              Authority: DocumentViewerPage (shell-global). LIVE. */}
                          <button data-testid="tp-btn-view-doc"
                            onClick={() => openViewer && openViewer({
                              id: 'PL-' + sc,
                              title: 'Packing List · ' + designNo,
                              type: 'Packing List',
                              awb: '',
                            })}
                            style={{ marginRight: 6, padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', cursor: 'pointer' }}>
                            View doc
                          </button>
                          {/* Receive: opens existing MoveStockModal via parent prop.
                              Authority: MoveStockModal (inventory-page.jsx:1755).
                              run_stock_promotion (BE-1) is the document-driven backend;
                              MoveStockModal is the ONLY operator-facing manual route.
                              Census tag IV-TP-1: scan_code pre-fill not yet wired into
                              MoveStockModal (modal opens in default state). */}
                          <button data-testid="tp-btn-receive"
                            onClick={() => {
                              window.dispatchEvent(new CustomEvent('inv:move'));
                              onShowMove && onShowMove();
                            }}
                            title={'Opens Move Stock modal (existing authority) to manually promote this piece from PURCHASE_TRANSIT → WAREHOUSE_STOCK via run_stock_promotion (BE-1). Scan code: ' + sc + ' — pre-fill into modal is IV-TP-1 (future slice).'}
                            style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--accent-border)', background: 'var(--accent-subtle)', color: 'var(--accent-text)', cursor: 'pointer' }}>
                            Receive
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Endpoint reference */}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          Merchandising: GET /api/v1/inventory/merchandising/&#123;batch_id&#125; (C-3e, LIVE) ·
          Filter: state=PURCHASE_TRANSIT ·
          Cross-batch aggregate: not available — per-batch read only
        </div>
      </div>
    );
  }

  // ── Temp Sale tab — Wave-3 / U-3 page 5 ────────────────────────────────────
  // Wireframe §7 Tab 4 (TempSaleTab). Gap IV-TS-1.
  // Backend reads:
  //   GET /api/v1/inventory/state/{batch_id}  → filter to SALES_TRANSIT pieces
  //     (routes_inventory.py:74; inventory_batch_state.get_batch_state; LIVE)
  //   GET /api/v1/inventory/movements/{batch_id} → invoice_issued event notes
  //     (routes_inventory.py:203; C-3f; LIVE)
  // Read authority: per-batch only. No cross-batch SALES_TRANSIT aggregate
  // endpoint exists → tab uses batch picker (BatchPanel precedent).
  // Wireframe KPI tiles (4): Open reservations · Awaiting goods · Reserved ·
  //   Sales-invoice gate (LOCKED)
  // Wireframe gate banner: "Sales-invoice gate is enforced…"
  // Wireframe table columns (8): Proforma · Client · Design No · Qty · Value ·
  //   Linked to · Status · (actions)
  // Wireframe row actions (2): View proforma · Issue invoice
  //
  // Lesson-M honest-disabled:
  //   "View proforma" — no proforma_id/invoice_no field in inventory_state or
  //     inventory_state_events for SALES_TRANSIT pieces; the note field carries
  //     "invoice issue: {client_name}" (stock_issue.py:130) but no proforma ref.
  //     No backend route links a SALES_TRANSIT scan_code back to its proforma
  //     without a separate cross-join query not exposed by any live endpoint.
  //     Census tag: IV-TS-1 (future slice: add proforma_id to transition note).
  //   "Issue invoice" (delivery_confirmed) — SALES_TRANSIT → CLOSED transition
  //     trigger "delivery_confirmed" has no operator-facing POST route in any
  //     routes_*.py file (confirmed grep: no /delivery-confirm, no
  //     /confirm-delivery endpoint in routes_inventory.py or routes_proforma.py).
  //     Census tag: IV-TS-1 (future slice: POST /api/v1/inventory/pieces/{id}/
  //     confirm-delivery).
  //   "Value" column — no value/price field in inventory_state pieces rows;
  //     packing_lines has cif_value but no endpoint joins them for SALES_TRANSIT.
  //     Rendered as "—" (honest empty).
  //
  // KPI mapping:
  //   Open reservations = total SALES_TRANSIT pieces in batch
  //   Awaiting goods    = 0 always (SALES_TRANSIT means invoice already issued;
  //                       "awaiting" in wireframe = pieces where invoice_issued
  //                       but DHL tracking not yet confirmed — not distinguishable
  //                       from current reads; rendered as total for honesty)
  //   Reserved          = total SALES_TRANSIT pieces (same as Open reservations —
  //                       wireframe distinction not resolvable from current reads)
  //   Sales-invoice gate = always LOCKED (no delivery_confirmed route exists)

  function TempSaleTab() {
    const [batchId, setBatchId]       = useState('');
    const [loading, setLoading]       = useState(false);
    const [error, setError]           = useState('');
    const [pieces, setPieces]         = useState(null);   // SALES_TRANSIT pieces
    const [clientByCode, setClientByCode] = useState({}); // scan_code → client_name from events

    const load = useCallback(async () => {
      const bid = batchId.trim();
      if (!bid) return;
      setLoading(true);
      setError('');
      setPieces(null);
      setClientByCode({});

      // Fetch state (SALES_TRANSIT filter) and movements (client context) in parallel.
      const [stateRes, movRes] = await Promise.all([
        window.PzApi.getInventoryBatchState(bid),
        window.PzApi.getInventoryMovements(bid, 2000),
      ]);

      setLoading(false);

      if (!stateRes.ok) {
        setError(stateRes.error || ('HTTP ' + stateRes.status));
        return;
      }

      // Filter to SALES_TRANSIT pieces only.
      const allPieces = (stateRes.data && stateRes.data.pieces) || [];
      const transit = allPieces.filter(p => p.state === 'SALES_TRANSIT');
      setPieces(transit);

      // Build scan_code → client_name from invoice_issued event notes.
      // stock_issue.py writes: note = "invoice issue: {client_name}"
      if (movRes.ok) {
        const events = (movRes.data && movRes.data.events) || [];
        const map = {};
        for (const ev of events) {
          if (ev.trigger === 'invoice_issued' && ev.scan_code && ev.note) {
            const m = /^invoice issue:\s*(.+)$/i.exec((ev.note || '').trim());
            if (m && m[1] && !map[ev.scan_code]) {
              map[ev.scan_code] = m[1].trim();
            }
          }
        }
        setClientByCode(map);
      }
    }, [batchId]);

    // Derived KPI counts
    const total          = pieces ? pieces.length : null;
    const gateLocked     = true; // always — no delivery_confirmed route exists

    const TH = { padding: '7px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
    const TD = { padding: '8px 10px', fontSize: 12.5, borderBottom: '1px solid var(--border-subtle)', color: 'var(--text)', verticalAlign: 'middle' };

    return (
      <div data-testid="temp-sale-tab" style={{ maxWidth: 1100, margin: '0 auto' }}>

        {/* Gate banner — wireframe §7 Tab 4 exact */}
        <div data-testid="ts-gate-banner" style={{ marginBottom: 16, padding: '10px 14px', background: 'var(--badge-amber-bg)', border: '1px solid var(--badge-amber-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-amber-text)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 700 }}>🔒 Sales-invoice gate is enforced.</span>
          {' '}No commercial sale invoice can be issued from a TEMP_SALE row. The invoice is unlocked only when its linked stock has reached FINAL_STOCK after physical verification.
          {' '}<span style={{ fontSize: 11, opacity: 0.8 }}>(delivery_confirmed backend-pending — IV-TS-1)</span>
        </div>

        {/* KPI strip — 4 tiles per wireframe §7 Tab 4 */}
        <div data-testid="ts-kpi-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          <InvStatTile testid="ts-kpi-open"       label="Open reservations" value={total}  hint="SALES_TRANSIT pieces in selected batch" />
          <InvStatTile testid="ts-kpi-awaiting"   label="Awaiting goods"    value={total}  tone="amber" hint="invoice issued; DHL delivery not yet confirmed (not distinguishable from current reads — shows total)" />
          <InvStatTile testid="ts-kpi-reserved"   label="Reserved"          value={total}  tone="green" hint="SALES_TRANSIT pieces (all are committed)" />
          <InvStatTile testid="ts-kpi-gate"       label="Sales-invoice gate" value="LOCKED" tone="amber"
            hint="delivery_confirmed route not yet built — Issue invoice disabled (IV-TS-1)" />
        </div>

        {/* Batch selector toolbar */}
        <div data-testid="ts-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <input
            data-testid="ts-batch-input"
            value={batchId}
            onChange={e => setBatchId(e.target.value)}
            placeholder="Batch ID — e.g. SHIPMENT_4218922912_2026-05_…"
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text)', fontSize: 12.5, flex: 1, minWidth: 260 }}
          />
          <InvFetchBtn
            data-testid="ts-btn-load"
            onClick={load}
            loading={loading}
            disabled={!batchId.trim()}
            label="Load batch"
          />
          {pieces !== null && (
            <InvFetchBtn data-testid="ts-refresh" onClick={load} loading={loading} label="↻ Refresh" />
          )}
        </div>

        {/* Error state */}
        {error && (
          <div data-testid="ts-error-banner" style={{ marginBottom: 14, padding: '10px 14px', background: 'var(--badge-red-bg)', border: '1px solid var(--badge-red-border)', borderRadius: 8, fontSize: 12.5, color: 'var(--badge-red-text)' }}>
            Failed to load batch state: {error}
          </div>
        )}

        {/* Prompt before load */}
        {!loading && pieces === null && !error && (
          <div data-testid="ts-prompt" style={{ padding: '28px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 13, fontStyle: 'italic' }}>
            Enter a batch ID above and click Load batch to view SALES_TRANSIT reservations.
          </div>
        )}

        {/* Register table — 8 columns per wireframe §7 Tab 4 */}
        {pieces !== null && (
          <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
                Sales reservations awaiting closure — SALES_TRANSIT
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                {pieces.length} piece(s) · batch: <code style={{ fontFamily: 'ui-monospace, monospace', background: 'var(--bg-subtle)', padding: '1px 4px', borderRadius: 3 }}>{batchId.trim()}</code>
              </span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table data-testid="ts-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle)' }}>
                    {/* 8 columns per wireframe §7 Tab 4 */}
                    <th style={TH}>Proforma</th>
                    <th style={TH}>Client</th>
                    <th style={TH}>Design No</th>
                    <th style={TH}>Qty</th>
                    <th style={TH}>Value</th>
                    <th style={TH}>Linked to</th>
                    <th style={TH}>Status</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr><td colSpan={8} style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '28px 0' }}>Loading…</td></tr>
                  )}
                  {!loading && pieces.length === 0 && (
                    <tr>
                      <td colSpan={8} data-testid="ts-empty" style={{ ...TD, textAlign: 'center', color: 'var(--text-3)', padding: '32px 0', fontStyle: 'italic' }}>
                        No SALES_TRANSIT pieces in this batch — register is empty (honest empty).
                      </td>
                    </tr>
                  )}
                  {!loading && pieces.map((p, i) => {
                    const sc     = p.scan_code || '';
                    // Design: derived from scan_code (batch|sr|design split)
                    const parts  = sc.split('|');
                    const design = p.design_no || (parts.length >= 3 ? parts[2] : (parts.length === 2 ? parts[1] : sc)) || '—';
                    // Client: extracted from invoice_issued event note
                    const client = clientByCode[sc] || '—';
                    // Qty: always 1 (single-piece tracking)
                    const qty    = 1;
                    // Value: not in inventory_state; no join endpoint — honest "—"
                    const value  = '—';
                    // Linked to: scan_code is the piece identifier
                    const linked = sc || '—';
                    // updated_at display
                    const updAt  = p.updated_at ? p.updated_at.slice(0, 10) : '—';

                    return (
                      <tr key={sc + i} data-testid="ts-row" style={{ background: 'var(--card)' }}>
                        {/* Proforma: no proforma_id in inventory_state — Lesson-M honest-disabled (IV-TS-1) */}
                        <td style={{ ...TD, fontSize: 11.5, color: 'var(--text-3)', fontStyle: 'italic' }}
                          title="No proforma_id stored in inventory_state SALES_TRANSIT row — future slice will add proforma link (IV-TS-1)">
                          —
                        </td>
                        <td style={TD}>{client}</td>
                        <td style={TD}>{design}</td>
                        <td style={TD}>{qty}</td>
                        {/* Value: no price field in inventory_state; no join endpoint */}
                        <td style={{ ...TD, color: 'var(--text-3)', fontStyle: 'italic' }}
                          title="No value/price field in inventory_state pieces; no join endpoint available (IV-TS-1)">
                          {value}
                        </td>
                        <td style={{ ...TD, fontSize: 11.5, fontFamily: 'ui-monospace, monospace', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={linked}>
                          {linked}
                        </td>
                        <td style={TD}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', border: '1px solid var(--badge-amber-border)', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                            Reserved
                          </span>
                        </td>
                        <td style={{ ...TD, textAlign: 'right', whiteSpace: 'nowrap' }}>
                          {/* View proforma: no proforma_id in inventory_state — Lesson-M honest-disabled */}
                          <button data-testid="ts-btn-view-proforma" disabled
                            title="backend-pending — no proforma_id stored in SALES_TRANSIT inventory_state row; no endpoint links scan_code to its proforma_id without a separate cross-join not yet exposed (IV-TS-1; future slice)"
                            style={{ marginRight: 6, padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-subtle)', color: 'var(--text-3)', cursor: 'not-allowed', opacity: 0.5 }}>
                            View proforma
                          </button>
                          {/* Issue invoice (delivery_confirmed): no POST route — Lesson-M honest-disabled */}
                          <button data-testid="ts-btn-issue-invoice" disabled
                            title="backend-pending — SALES_TRANSIT → CLOSED delivery_confirmed transition has no operator-facing POST route in any routes_*.py; gate enforced by Sales-invoice gate banner (IV-TS-1; future slice: POST /api/v1/inventory/pieces/{id}/confirm-delivery)"
                            style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 5, border: '1px solid var(--badge-amber-border)', background: 'var(--badge-amber-bg)', color: 'var(--badge-amber-text)', cursor: 'not-allowed', opacity: 0.5 }}>
                            Issue invoice
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Endpoint reference */}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
          State: GET /api/v1/inventory/state/&#123;batch_id&#125; (filter state=SALES_TRANSIT) ·
          Events: GET /api/v1/inventory/movements/&#123;batch_id&#125; ·
          Cross-batch aggregate: not available — per-batch read only (IV-TS-1)
        </div>
      </div>
    );
  }

  // ── InventoryOverviewTab — Wave-3 U-6 (page 6) ─────────────────────────────
  //
  // Wireframe authority: docs/design/inventory-page.design.jsx:658-791
  // (InventoryOverviewTab). Census gap IDs: IV-O-1, IV-O-2, IV-O-3 (BUILD).
  // IV-O-4 (WFIRMA-GATED): Consignment tile stays pending — no backend.
  //
  // Layout (exact wireframe order):
  //   1. Quick-action row (3 cards): Upload Document · Move Stock · Identity/Mapping
  //   2. KPI tile row (4 tiles): Final stock · Pieces on hand · Stock value · Reorder alerts
  //      — Final stock + samples + returns from GET /api/v1/inventory/stage2/aggregate (live)
  //      — Consignment: WFIRMA-GATED pending tile (Census IV-O-4)
  //   3. Stage summary cards (2-col): Stage 1 (Temp Purchase/Warehouse/Sale) · Stage 2 (Final/Samples/Returns)
  //      — Each row is a tab-navigation link (setTab(id))
  //   4. Recent inventory movements table (read from /api/v1/inventory/stage2/aggregate
  //      when movements surface is available; today aggregate has no movements array —
  //      table renders empty state instead of fake data)
  //
  // Hub diagnostic panels (BatchPanel, PiecePanel, LocationPanel, AuditPanel,
  // PromotionNotesPanel) are kept in a collapsed <details> block — no REMOVE tag
  // in the census; wireframe is silent about them (OUT), so they stay reachable
  // per the task instruction: "keep in place" / census-REMOVE-only removal rule.

  function InventoryOverviewTab({ setActiveTab, onShowMove }) {
    // ── Aggregate fetch for KPI tiles ──────────────────────────────────────
    const [aggData, setAggData]       = useState(null);
    const [aggLoading, setAggLoading] = useState(true);
    const [aggError, setAggError]     = useState(null);

    const loadAgg = useCallback(async () => {
      setAggLoading(true); setAggError(null);
      try { setAggData(await apiFetch('/api/v1/inventory/stage2/aggregate')); }
      catch (e) { setAggError((e && e.message) || String(e)); }
      finally { setAggLoading(false); }
    }, []);

    useEffect(() => { loadAgg(); }, [loadAgg]);

    const s2 = aggData && aggData.stage2;

    // KPI values — derived from aggregate (never fake numbers)
    const finalStock   = s2 && s2.final_stock  && s2.final_stock.count;
    const samplesCount = s2 && s2.samples       && s2.samples.count;
    const returnsCount = s2 && s2.returns       && s2.returns.count;
    const returnsSub   = s2 && s2.returns && s2.returns.subcounts;

    // ── Quick-action card styles (wireframe :664-696) ───────────────────────
    const qaCard = {
      padding: '16px 18px', border: '1px solid var(--border)', borderRadius: 8,
      background: 'var(--card)', cursor: 'pointer',
      display: 'flex', alignItems: 'center', gap: 14,
    };
    const qaIcon = (bg, color) => ({
      width: 38, height: 38, borderRadius: 8, background: bg, color,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 18, fontWeight: 700, flexShrink: 0,
    });

    // ── Stage-row click handler ─────────────────────────────────────────────
    const goTab = (id) => () => setActiveTab(id);

    // ── Stage summary row component ─────────────────────────────────────────
    function StageRow({ id, label, right }) {
      return (
        <div key={id} onClick={goTab(id)} data-testid={`overview-stage-row-${id}`}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 18px', cursor: 'pointer',
            borderBottom: '1px solid var(--border-subtle)',
          }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{label}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{right}</span>
            <span style={{ fontSize: 14, color: 'var(--text-3)' }}>›</span>
          </div>
        </div>
      );
    }

    // ── Recent movements badge (no spread-rest — global _excluded collision) ─
    function MovementBadge({ label, tone }) {
      const MAP = {
        amber:  { bg: 'var(--badge-amber-bg)',   tx: 'var(--badge-amber-text)',   bd: 'var(--badge-amber-border)'  },
        green:  { bg: 'var(--badge-green-bg)',   tx: 'var(--badge-green-text)',   bd: 'var(--badge-green-border)'  },
        blue:   { bg: 'var(--badge-blue-bg)',    tx: 'var(--badge-blue-text)',    bd: 'var(--badge-blue-border)'   },
        red:    { bg: 'var(--badge-red-bg)',     tx: 'var(--badge-red-text)',     bd: 'var(--badge-red-border)'    },
        orange: { bg: 'var(--badge-orange-bg)',  tx: 'var(--badge-orange-text)',  bd: 'var(--badge-orange-border)' },
      };
      const t = MAP[tone] || { bg: 'var(--badge-neutral-bg)', tx: 'var(--badge-neutral-text)', bd: 'var(--badge-neutral-border)' };
      return (
        <span style={{
          display: 'inline-flex', alignItems: 'center',
          background: t.bg, color: t.tx, border: `1px solid ${t.bd}`,
          borderRadius: 4, padding: '2px 8px',
          fontSize: 11, fontWeight: 600, letterSpacing: '0.03em', whiteSpace: 'nowrap',
        }}>{label}</span>
      );
    }

    // The aggregate does not return a movements array — recent movements table
    // shows an empty state (no fake data, per census / no REMOVE tag needed).
    // Backend endpoint for movement log is GET /api/v1/inventory/movements/{batch_id}
    // (batch-scoped, not cross-batch). A cross-batch ledger is Wave 4 scope.
    const MOVEMENTS_COLS = [
      { key: 'time',   label: 'When',      muted: true },
      { key: 'kind',   label: 'Movement'               },
      { key: 'su',     label: 'Stock Unit / Line', mono: true },
      { key: 'design', label: 'Design',    mono: true  },
      { key: 'qty',    label: 'Qty',       align: 'right', bold: true },
      { key: 'who',    label: 'By',        muted: true },
      { key: 'ref',    label: 'Ref',       mono: true, muted: true },
    ];

    return (
      <div data-testid="inv-overview-tab">
        {/* ── 1. Quick actions (3-col grid, wireframe :663-697) ──────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
          {/* Upload Document — fires inv:upload event (no backend today → Lesson M planned-state;
              upload doc routes live at /api/v1/documents/upload; wired via existing Upload panel.
              The event lets a future listener open the DocumentUploadModal. The card is
              actionable (not disabled) because the upload surface already exists in the app. */}
          <div data-testid="overview-qa-upload"
            onClick={() => window.dispatchEvent(new CustomEvent('inv:upload'))}
            style={qaCard}>
            <div style={qaIcon('var(--badge-amber-bg)', 'var(--badge-amber-text)')}>↑</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Upload Document</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Packing list · Invoice · Transfer · Return — auto-routes by type</div>
            </div>
            <span style={{ fontSize: 16, color: 'var(--text-3)' }}>›</span>
          </div>

          {/* Move Stock — fires inv:move event + opens MoveStockModal via parent */}
          <div data-testid="overview-qa-move"
            onClick={() => { window.dispatchEvent(new CustomEvent('inv:move')); onShowMove(); }}
            style={qaCard}>
            <div style={qaIcon('var(--badge-blue-bg)', 'var(--badge-blue-text)')}>⇄</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Move Stock</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Warehouse → Warehouse, Main → Sample / Consignment / Return</div>
            </div>
            <span style={{ fontSize: 16, color: 'var(--text-3)' }}>›</span>
          </div>

          {/* Identity / Mapping — navigates to mapping tab (setActiveTab) */}
          <div data-testid="overview-qa-mapping"
            onClick={goTab('mapping')}
            style={qaCard}>
            <div style={qaIcon('var(--badge-green-bg)', 'var(--badge-green-text)')}>≡</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Identity / Mapping</div>
              <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Family · Design · Batch · Bag · Trace barcode</div>
            </div>
            <span style={{ fontSize: 16, color: 'var(--text-3)' }}>›</span>
          </div>
        </div>

        {/* ── 2. KPI tile row (wireframe :699-704) ──────────────────────── */}
        {aggLoading && (
          <div style={{ color: 'var(--text-3)', fontSize: 12, marginBottom: 20 }}>Loading inventory overview…</div>
        )}
        {aggError && (
          <div style={{ color: 'var(--badge-red-text)', fontSize: 12, marginBottom: 20 }}>Error loading aggregate: {aggError}</div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          {/* Final stock — WAREHOUSE_STOCK count from aggregate (census IV-O-1 BUILD) */}
          <InvStatTile
            testid="ov-tile-final-stock"
            label="Stock units (final)"
            value={finalStock == null ? (aggLoading ? '…' : '—') : finalStock}
            tone="green"
            hint="WAREHOUSE_STOCK state"
          />
          {/* Pieces on hand — aggregate has no piece-count bucket today;
              renders as pending (census IV-O-1: aggregate only exposes SU count for
              final_stock; piece sum requires a separate query — Wave-4 scope) */}
          <InvStatTile
            testid="ov-tile-pieces"
            label="Pieces on hand"
            value={aggLoading ? '…' : '—'}
            hint="piece-count aggregate — Wave 4"
          />
          {/* Samples + Returns combined as stock activity proxy — live from aggregate */}
          <InvStatTile
            testid="ov-tile-returns"
            label="Returns (all)"
            value={returnsCount == null ? (aggLoading ? '…' : '—') : returnsCount}
            tone={returnsCount > 0 ? 'red' : undefined}
            hint={returnsSub && returnsCount != null ? `${returnsSub.from_client} client · ${returnsSub.to_producer} producer` : 'RETURNED_FROM_CLIENT + RETURNED_TO_PRODUCER'}
          />
          {/* Consignment — WFIRMA-GATED: no backend (census IV-O-4 WFIRMA-GATED,
              OI-1, OI-2, OI-17 OPEN). Honest pending tile, never a fake number. */}
          <InvStatTile
            testid="ov-tile-consignment"
            label="Consignment"
            pending
            hint="physically with client · C-4a gated"
          />
        </div>

        {/* ── 3. Stage summary cards 2-col (wireframe :706-762) ─────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16 }}>
          {/* Stage 1 summary card */}
          <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-amber-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 4 }}>Stage 1 — Temporary</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Document &amp; arrival layer</div>
              </div>
            </div>
            <div style={{ padding: '6px 0' }}>
              <StageRow id="tempPurchase"  label="Temp Purchase"  right="packing lists · arrivals" />
              <StageRow id="tempWarehouse" label="Temp Warehouse" right="awaiting count · discrepancies" />
              <StageRow id="tempSale"      label="Temp Sale"      right="reservations · invoice gate" />
            </div>
          </div>

          {/* Stage 2 summary card */}
          <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--badge-blue-text)', letterSpacing: '0.10em', textTransform: 'uppercase', marginBottom: 4 }}>Stage 2 — Physical</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>Verified stock &amp; movements</div>
            </div>
            <div style={{ padding: '6px 0' }}>
              <StageRow id="finalStock"     label="Final Stock"                right={finalStock != null ? `${finalStock} SU` : (aggLoading ? '…' : '—')} />
              <StageRow id="sampleOut"      label="Sample Out"                 right={samplesCount != null ? `${samplesCount} active` : (aggLoading ? '…' : '—')} />
              <StageRow id="sampleReturn"   label="Sample Return"              right="awaiting inspection" />
              <StageRow id="clientReturn"   label="Goods Return from Client"   right="open · awaiting inspection" />
              <StageRow id="producerReturn" label="Return to Producer"         right="open" />
            </div>
          </div>
        </div>

        {/* ── 4. Recent inventory movements (wireframe :764-788) ────────── */}
        {/* The aggregate endpoint does not return a movements array — this table
            correctly shows empty state. GET /api/v1/inventory/movements/{batch_id}
            is batch-scoped only. Cross-batch movement ledger is Wave 4 scope (C-6a). */}
        <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: '0 1px 3px var(--shadow)' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Recent inventory movements</span>
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Cross-batch ledger — Wave 4</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 700 }}>
              <thead>
                <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                  {MOVEMENTS_COLS.map(c => (
                    <th key={c.key} style={{
                      padding: '10px 12px', textAlign: c.align || 'left',
                      fontSize: 10, fontWeight: 700, color: 'var(--text-3)',
                      letterSpacing: '0.10em', textTransform: 'uppercase', whiteSpace: 'nowrap',
                    }}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={MOVEMENTS_COLS.length} style={{ padding: '32px 20px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>
                    Cross-batch movement log available in Wave 4 — use per-batch view in Diagnostics below
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Refresh control ─────────────────────────────────────────────── */}
        <div style={{ marginTop: 12 }}>
          <button onClick={loadAgg} disabled={aggLoading}
            style={{ fontSize: 11, border: '1px solid var(--border)', background: 'transparent', borderRadius: 4, padding: '4px 10px', cursor: aggLoading ? 'default' : 'pointer', color: 'var(--text-2)' }}
            data-testid="ov-btn-refresh">
            {aggLoading ? '…' : '↻ Refresh KPI data'}
          </button>
        </div>

        {/* ── Hub diagnostic panels (OUT-tagged; wireframe silent; kept per task rule) ── */}
        {/* Collapsed by default per Frontend Design Standard "Legacy sections in <details>" */}
        <details style={{ marginTop: 24 }} data-testid="inv-diagnostics-details">
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 0', userSelect: 'none' }}>
            ▸ Diagnostics — batch / piece / location / audit panels
          </summary>
          <div style={{ marginTop: 12 }}>
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
        </details>
      </div>
    );
  }

  // ── InventoryPage — shell entry point (Wave-3: tab strip, Overview tab live) ─
  //
  // Wave-3 tab strip progression:
  //   U-1: sampleOut + sampleReturn (pages 1-2)
  //   U-2: clientReturn + producerReturn (pages 3-4)
  //   U-3: tempSale (page 5)
  //   U-6: overview (page 6) — THIS SLICE (renames hub → overview)
  //
  // Tab 'mapping' — Identity/Mapping — is reachable from Overview quick-action.
  // It is not yet a wired tab in the strip (no census BUILD gap for the tab strip
  // entry itself; the tab strip will grow when the Identity/Mapping panel slice lands).
  // The setActiveTab('mapping') call from InventoryOverviewTab is wired here so
  // navigation works even before the tab strip button appears.

  const INV_TABS = [
    { id: 'overview',      label: 'Overview',           wire: true  },
    { id: 'sampleOut',     label: 'Sample Out',         wire: true  },
    { id: 'sampleReturn',  label: 'Sample Return',      wire: true  },
    { id: 'clientReturn',  label: 'Client Return',      wire: true  },
    { id: 'producerReturn',label: 'Return to Producer', wire: true  },
    { id: 'tempSale',      label: 'Temp Sale',          wire: true  },
    { id: 'tempPurchase',  label: 'Temp Purchase',      wire: true  },
  ];

  function InvTabStrip({ active, onChange }) {
    return (
      <div data-testid="inv-tab-strip" style={{ display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', marginBottom: 0, overflowX: 'auto' }}>
        {INV_TABS.map(t => {
          const isActive = active === t.id;
          return (
            <button key={t.id} data-testid={`inv-tab-${t.id}`} onClick={() => onChange(t.id)}
              style={{
                padding: '10px 18px', fontSize: 13, fontWeight: isActive ? 700 : 500,
                background: 'transparent', border: 'none', borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                color: isActive ? 'var(--accent-text, var(--text))' : 'var(--text-2)',
                cursor: 'pointer', whiteSpace: 'nowrap', marginBottom: -2,
              }}>
              {t.label}
            </button>
          );
        })}
      </div>
    );
  }

  function InventoryPage({ openViewer }) {  // openViewer accepted
    const [showMove, setShowMove]             = useState(false);
    const [activeTab, setActiveTab]           = useState('overview');
    // Cross-tab Record Return: opened from SampleOutTab row → RecordReturnModal in InventoryPage
    // so that the modal can trigger a refresh of the Sample Return tab when visible.
    const [recordReturnTarget, setRecordReturnTarget] = useState(null);

    function handleRecordReturn(sample) {
      setRecordReturnTarget(sample);
    }

    function handleReturnSuccess() {
      setRecordReturnTarget(null);
      // Switch to Sample Return tab so the operator sees the result
      setActiveTab('sampleReturn');
    }

    return (
      <div style={{ maxWidth: 1120, margin: '0 auto', padding: '20px 24px 28px' }} data-testid="inventory-hub-root">
        {/* Cross-tab Record Return modal (opened from Sample Out row; success → switches to Sample Return) */}
        {recordReturnTarget && (
          <RecordReturnModal
            sample={recordReturnTarget}
            onClose={() => setRecordReturnTarget(null)}
            onSuccess={handleReturnSuccess}
          />
        )}

        {/* Move Stock modal — triggered from Overview quick-action or tab content */}
        {showMove && <MoveStockModal onClose={() => setShowMove(false)} />}

        {/* Tab strip */}
        <InvTabStrip active={activeTab} onChange={setActiveTab} />

        <div style={{ paddingTop: 20 }}>
          {/* ── Overview tab — Wave-3 U-6 page 6 ─────────────────────── */}
          {activeTab === 'overview' && (
            <InventoryOverviewTab
              setActiveTab={setActiveTab}
              onShowMove={() => setShowMove(true)}
            />
          )}

          {/* ── Sample Out tab — Wave-3 U-1 page 1 ───────────────── */}
          {activeTab === 'sampleOut' && <SampleOutTab onRecordReturn={handleRecordReturn} />}

          {/* ── Sample Return tab — Wave-3 U-1 page 2 ────────────── */}
          {activeTab === 'sampleReturn' && <SampleReturnTab />}

          {/* ── Client Return tab — Wave-3 U-2 page 3 ───────────── */}
          {activeTab === 'clientReturn' && <ClientReturnTab />}

          {/* ── Return to Producer tab — Wave-3 U-2 page 4 ──────── */}
          {activeTab === 'producerReturn' && <ProducerReturnTab />}

          {/* ── Temp Sale tab — Wave-3 U-3 page 5 ───────────────── */}
          {activeTab === 'tempSale' && <TempSaleTab />}

          {/* ── Temp Purchase tab — Wave-3 U-3 page 7 ──────────── */}
          {activeTab === 'tempPurchase' && (
            <TempPurchaseTab
              openViewer={openViewer}
              onShowMove={() => setShowMove(true)}
            />
          )}
        </div>
      </div>
    );
  }

  window.InventoryPage = InventoryPage;
})();

window.DocumentViewerPage = DocumentViewerPage;
