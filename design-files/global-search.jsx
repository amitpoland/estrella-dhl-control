// ─────────────────────────────────────────────────────────────────────────────
// GlobalSearch — Cmd-K overlay. Type any AWB / PI / INV / batch / client /
// SKU and jump straight to its detail page. Quick-filter chips at the top
// scope the search by type.
//
// Backend hook (stubbed): GET /api/v1/search?q=&types=
// ─────────────────────────────────────────────────────────────────────────────

const SEARCH_INDEX = [
  // Shipments
  { type: 'shipment', label: 'SHIP-2026-0421', sub: 'Aurum Watches GmbH · EUR 18,420 · DHL · Ready to ship',         page: 'shipments', kw: 'aurum eur dhl ready' },
  { type: 'shipment', label: 'SHIP-2026-0420', sub: 'Audemars Piguet · CHF 88,400 · DHL · Customs',                   page: 'shipments', kw: 'audemars chf dhl customs urgent' },
  { type: 'shipment', label: 'SHIP-2026-0419', sub: 'Crown Jewelers Ltd · USD 18,200 · DHL · Customs',                page: 'shipments', kw: 'crown jewelers usd dhl customs' },
  { type: 'shipment', label: 'SHIP-2026-0418', sub: 'Crown Jewelers Ltd · USD 24,100 · FedEx · In transit',           page: 'shipments', kw: 'crown jewelers usd fedex transit' },
  // AWB / tracking
  { type: 'awb',      label: 'AWB 1234567890', sub: 'Linked to SHIP-2026-0421 · DHL Express',                         page: 'shipments', kw: 'dhl waybill 1234567890' },
  { type: 'awb',      label: 'AWB 998877665',  sub: 'Linked to SHIP-2026-0418 · FedEx',                               page: 'shipments', kw: 'fedex waybill 998877665' },
  { type: 'awb',      label: 'AWB 1234567802', sub: 'Linked to SHIP-2026-0420 · DHL · in clearance',                  page: 'shipments', kw: 'dhl waybill audemars customs' },
  // Documents
  { type: 'doc',      label: 'PI-2026/0143',    sub: 'Proforma · Maison Royale SARL · EUR 9,840.50',                  page: 'documents', kw: 'proforma maison royale eur' },
  { type: 'doc',      label: 'PI-2026/0142',    sub: 'Proforma · Aurum Watches GmbH · EUR 18,420',                    page: 'documents', kw: 'proforma aurum watches eur' },
  { type: 'doc',      label: 'INV-2026/0089',   sub: 'Sales Invoice · Crown Jewelers Ltd · USD 24,100',               page: 'documents', kw: 'invoice sales crown usd' },
  { type: 'doc',      label: 'PZ-2026-014',     sub: 'Purchase PZ · Manufaktura Złota · EUR 18,420',                  page: 'documents', kw: 'pz purchase manufaktura eur' },
  { type: 'doc',      label: 'SAD-PL-26-118472',sub: 'Customs declaration · cleared · ZC429-26-04482',                page: 'documents', kw: 'sad customs zc429 cleared' },
  // Clients / suppliers
  { type: 'client',   label: 'Aurum Watches GmbH',   sub: 'Customer · DE · 4 open shipments · EUR ledger',            page: 'master',    kw: 'aurum customer de' },
  { type: 'client',   label: 'Crown Jewelers Ltd',   sub: 'Customer · UK · 5 open shipments · USD ledger',            page: 'master',    kw: 'crown customer uk usd' },
  { type: 'client',   label: 'Patek Philippe SA',    sub: 'Supplier · CH · 2 inbound shipments · CHF ledger',         page: 'master',    kw: 'patek supplier ch chf' },
  // Batches
  { type: 'batch',    label: 'B-2026-014',     sub: 'Inbound batch · 4 pieces · Manufaktura Złota · ready to receive',page: 'inventory', kw: 'batch manufaktura inbound' },
  { type: 'batch',    label: 'B-2026-013',     sub: 'Inbound batch · 7 pieces · Patek Philippe · cleared',            page: 'inventory', kw: 'batch patek cleared' },
];

const SEARCH_FILTERS = [
  { id: 'all',      label: 'All',          types: null },
  { id: 'shipment', label: 'Shipments',    types: ['shipment','awb'] },
  { id: 'doc',      label: 'Documents',    types: ['doc'] },
  { id: 'client',   label: 'Clients',      types: ['client'] },
  { id: 'batch',    label: 'Batches',      types: ['batch'] },
];

const TYPE_BADGE = {
  shipment: { label: 'Shipment', bg: 'var(--badge-purple-bg)', fg: 'var(--badge-purple-text)', bd: 'var(--badge-purple-border)' },
  awb:      { label: 'AWB',      bg: 'var(--badge-blue-bg)',   fg: 'var(--badge-blue-text)',   bd: 'var(--badge-blue-border)' },
  doc:      { label: 'Document', bg: 'var(--accent-subtle)',   fg: 'var(--accent)',            bd: 'var(--accent-border)' },
  client:   { label: 'Party',    bg: 'var(--badge-green-bg)',  fg: 'var(--badge-green-text)',  bd: 'var(--badge-green-border)' },
  batch:    { label: 'Batch',    bg: 'var(--badge-amber-bg)',  fg: 'var(--badge-amber-text)',  bd: 'var(--badge-amber-border)' },
};

function GlobalSearch({ open, onClose, onNav }) {
  const [q, setQ] = React.useState('');
  const [filter, setFilter] = React.useState('all');
  const [highlightIdx, setHighlightIdx] = React.useState(0);
  const inputRef = React.useRef(null);

  React.useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 30);
      setQ('');
      setHighlightIdx(0);
    }
  }, [open]);

  const filterConf = SEARCH_FILTERS.find(f => f.id === filter);
  const filtered = React.useMemo(() => {
    const query = q.trim().toLowerCase();
    let pool = SEARCH_INDEX;
    if (filterConf.types) pool = pool.filter(r => filterConf.types.includes(r.type));
    if (!query) return pool.slice(0, 8);
    return pool.filter(r =>
      r.label.toLowerCase().includes(query) ||
      r.sub.toLowerCase().includes(query) ||
      r.kw.includes(query)
    ).slice(0, 20);
  }, [q, filter]);

  // Keyboard navigation
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); setHighlightIdx(i => Math.min(i + 1, filtered.length - 1)); }
      else if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlightIdx(i => Math.max(i - 1, 0)); }
      else if (e.key === 'Enter') {
        const target = filtered[highlightIdx];
        if (target) { onNav(target.page); onClose(); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, filtered, highlightIdx, onNav, onClose]);

  if (!open) return null;
  return (
    <div onClick={(e) => e.target === e.currentTarget && onClose()} style={{
      position: 'fixed', inset: 0, background: 'var(--overlay)',
      zIndex: 2000, display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
      paddingTop: '12vh',
    }}>
      <div style={{
        width: 620, maxWidth: 'calc(100vw - 32px)',
        background: 'var(--card)', borderRadius: 10,
        border: '1px solid var(--border)',
        boxShadow: '0 24px 80px var(--shadow-heavy)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        {/* Input */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '14px 18px', gap: 10, borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 18, color: 'var(--text-3)' }}>⌕</span>
          <input ref={inputRef} value={q} onChange={e => { setQ(e.target.value); setHighlightIdx(0); }}
            placeholder="Search AWB, PI, INV, batch, client, SKU…"
            style={{
              flex: 1, border: 'none', outline: 'none', background: 'transparent',
              fontSize: 16, color: 'var(--text)', fontFamily: 'inherit',
            }}/>
          <span style={{ fontSize: 9.5, fontFamily: 'monospace', color: 'var(--text-3)', padding: '2px 6px', background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 3 }}>esc</span>
        </div>

        {/* Filter chips */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-subtle)' }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginRight: 4 }}>Filter</span>
          {SEARCH_FILTERS.map(f => {
            const active = filter === f.id;
            return (
              <button key={f.id} onClick={() => setFilter(f.id)} style={{
                background: active ? 'var(--accent)' : 'transparent',
                color: active ? 'var(--accent-text)' : 'var(--text-2)',
                border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border)'),
                borderRadius: 4, padding: '3px 10px', fontSize: 10.5,
                fontWeight: 600, cursor: 'pointer',
              }}>{f.label}</button>
            );
          })}
        </div>

        {/* Results */}
        <div style={{ maxHeight: 380, overflowY: 'auto' }}>
          {filtered.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 12 }}>
              No results for "{q}"
            </div>
          )}
          {filtered.map((r, idx) => {
            const tb = TYPE_BADGE[r.type];
            const hot = idx === highlightIdx;
            return (
              <button key={r.label + idx} onClick={() => { onNav(r.page); onClose(); }}
                onMouseEnter={() => setHighlightIdx(idx)}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 18px', background: hot ? 'var(--accent-subtle)' : 'transparent',
                  border: 'none', borderLeft: hot ? '3px solid var(--accent)' : '3px solid transparent',
                  cursor: 'pointer', textAlign: 'left',
                }}>
                <span style={{
                  fontSize: 9, padding: '1px 6px', borderRadius: 2,
                  background: tb.bg, color: tb.fg, border: `1px solid ${tb.bd}`,
                  fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
                  minWidth: 64, textAlign: 'center',
                }}>{tb.label}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)', fontFamily: r.type === 'awb' || r.type === 'shipment' ? 'monospace' : 'inherit' }}>{r.label}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.sub}</div>
                </div>
                <span style={{ fontSize: 11, color: hot ? 'var(--accent)' : 'var(--text-3)' }}>{hot ? '⏎' : '›'}</span>
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 18px', borderTop: '1px solid var(--border)',
          background: 'var(--bg-subtle)', fontSize: 10, color: 'var(--text-3)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span><kbd style={kbdStyle}>↑</kbd> <kbd style={kbdStyle}>↓</kbd> navigate</span>
            <span><kbd style={kbdStyle}>⏎</kbd> open</span>
            <span><kbd style={kbdStyle}>esc</kbd> close</span>
          </div>
          <span>{filtered.length} {filtered.length === 1 ? 'result' : 'results'} · GET /api/v1/search</span>
        </div>
      </div>
    </div>
  );
}

const kbdStyle = {
  display: 'inline-block', fontFamily: 'monospace',
  padding: '0 4px', background: 'var(--card)',
  border: '1px solid var(--border)', borderRadius: 3,
  fontSize: 9, minWidth: 12, textAlign: 'center',
};

window.GlobalSearch = GlobalSearch;
