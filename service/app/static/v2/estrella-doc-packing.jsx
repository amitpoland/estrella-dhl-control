// estrella-doc-packing.jsx — Estrella Document Suite: Packing List PDF
// Full commercial packing list — one row per design line (146 rows for a typical shipment).
//
// packingData shape (supplied by ProformaDetailPage):
//   .doc_ref     string         — Proforma number (e.g. "PROF 123/2026")
//   .invoice_ref string | null  — Invoice number after wFirma conversion; null until then
//   .issued_date string         — ISO date (e.g. "2026-06-09")
//   .seller      { name, addr, city, vat, email, phone }
//   .shipto      { name, addr, city, zip, country }
//   .buyer       { vat }
//   .currency    string         — "EUR", "USD", etc. (per-client authority)
//   .rows[]      { sr, ctg, client_po, design, kt, col, quality,
//                  dia_wt, col_wt, net_wt, qty, unit_price, total_value, size }
//                where:
//                  ctg        = "Pendant" | "Ring" | "Earrings" (human-readable)
//                  kt         = "14KT" | "18KT"
//                  col        = "W" | "P" | "Y"
//                  quality    = stone quality (VS1, SI1...) or "" when not available
//                  dia_wt     = diamond weight in carats (null when not yet parsed)
//                  col_wt     = colour-stone weight in carats (null when not yet parsed)
//                  net_wt     = total net weight per piece in kg (null when not available)
//                  unit_price = sales price per piece (EUR authority — same as proforma)
//                  total_value = unit_price × qty
//   .grand_total  number       — sum of all total_value; must equal proforma total
//   .total_qty    number       — sum of all qty; must equal packing list total
//
// Value authority: sales price (same as Proforma + Invoice). NOT landed cost / PZ authority.
// Currency can differ per client — always taken from draft.currency, never hardcoded.
//
// Visual: same Estrella brand tokens as EJCMRClassic (logo, party blocks, band).
// Layout: portrait A4. Multi-page handled by browser via @media print CSS in ProformaPreviewModal.
//
// Exports: window.EJPackingList

'use strict';

// ── Column definitions ────────────────────────────────────────────────────────
const _PKG_COLS = [
  { key: 'sr',          label: 'Sr',          w: 30,  align: 'center' },
  { key: 'ctg',         label: 'Category',    w: 64,  align: 'left'   },
  { key: 'client_po',   label: 'Client PO',   w: 82,  align: 'left'   },
  { key: 'design',      label: 'Design',      w: 108, align: 'left'   },
  { key: 'kt',          label: 'Kt',          w: 34,  align: 'center' },
  { key: 'col',         label: 'Col',         w: 26,  align: 'center' },
  { key: 'quality',     label: 'Quality',     w: 52,  align: 'center' },
  { key: 'dia_wt',      label: 'Dia Wt',      w: 48,  align: 'right'  },
  { key: 'col_wt',      label: 'Col Wt',      w: 48,  align: 'right'  },
  { key: 'qty',         label: 'Qty',         w: 34,  align: 'right'  },
  { key: 'unit_price',  label: 'Value',       w: 58,  align: 'right'  },
  { key: 'total_value', label: 'Total Value', w: 72,  align: 'right'  },
  { key: 'size',        label: 'Size',        w: 44,  align: 'center' },
];

// Build gridTemplateColumns string from col widths
const _PKG_GRID = _PKG_COLS.map(c => `${c.w}px`).join(' ');

// ── Number formatters ─────────────────────────────────────────────────────────
const _fmtMoney = (v, cur) =>
  v == null ? '—' : `${Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const _fmtWt    = (v) => v != null && Number(v) > 0 ? Number(v).toFixed(4) : '—';
const _fmtQty   = (v) => v != null ? Number(v) : '—';

// ── Header cell ───────────────────────────────────────────────────────────────
function PKGHeader({ col, isLast }) {
  return (
    <div style={{
      padding: '4px 4px',
      borderRight: isLast ? 'none' : '1px solid #CBD5E1',
      fontSize: 7.5, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase',
      color: '#475569', textAlign: col.align,
      background: '#F1F5F9',
    }}>
      {col.label}
    </div>
  );
}

// ── Data cell ─────────────────────────────────────────────────────────────────
function PKGCell({ value, align, isLast, bold, muted, mono }) {
  return (
    <div style={{
      padding: '3px 4px',
      borderRight: isLast ? 'none' : '1px solid #F1F5F9',
      fontSize: 8, textAlign: align || 'left',
      color: muted ? '#94A3B8' : '#1E293B',
      fontWeight: bold ? 600 : 400,
      fontFamily: mono ? 'var(--ej-mono, monospace)' : undefined,
      overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis',
    }}>
      {value === null || value === undefined ? '—' : value}
    </div>
  );
}

// ── Party block (same style as CMR Classic) ───────────────────────────────────
function PKGPartyBlock({ label, data }) {
  if (!data) return null;
  return (
    <div>
      <div style={{ fontSize: 7.5, letterSpacing: '0.16em', textTransform: 'uppercase', color: '#64748B', fontWeight: 600, marginBottom: 4 }}>
        {label}
      </div>
      {data.name && <div style={{ fontWeight: 600, fontSize: 10, color: '#0F172A' }}>{data.name}</div>}
      {data.addr && <div style={{ fontSize: 9, color: '#475569', marginTop: 1 }}>{data.addr}</div>}
      {(data.city || data.zip) && (
        <div style={{ fontSize: 9, color: '#475569' }}>
          {[data.zip, data.city].filter(Boolean).join(' ')}
          {data.country ? `, ${data.country}` : ''}
        </div>
      )}
      {data.vat  && <div style={{ fontSize: 8.5, color: '#64748B', marginTop: 3 }}>VAT EU · {data.vat}</div>}
      {data.email && <div style={{ fontSize: 8.5, color: '#64748B' }}>{data.email}</div>}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
function EJPackingList({ packingData }) {
  const d    = packingData || {};
  const rows = d.rows     || [];
  const cur  = d.currency || 'EUR';

  // Grand total and quantity for the footer
  const grandTotal = d.grand_total != null
    ? d.grand_total
    : rows.reduce((s, r) => s + (r.total_value || 0), 0);
  const totalQty = d.total_qty != null
    ? d.total_qty
    : rows.reduce((s, r) => s + (r.qty || 0), 0);

  // Format cell value for a given column key
  const cellVal = (r, key) => {
    switch (key) {
      case 'sr':          return r.sr;
      case 'ctg':         return r.ctg        || '—';
      case 'client_po':   return r.client_po  || '—';
      case 'design':      return r.design     || '—';
      case 'kt':          return r.kt         || '—';
      case 'col':         return r.col        || '—';
      case 'quality':     return r.quality    || '—';
      case 'dia_wt':      return _fmtWt(r.dia_wt);
      case 'col_wt':      return _fmtWt(r.col_wt);
      case 'qty':         return _fmtQty(r.qty);
      case 'unit_price':  return _fmtMoney(r.unit_price,  cur);
      case 'total_value': return _fmtMoney(r.total_value, cur);
      case 'size':        return r.size || '—';
      default:            return '—';
    }
  };

  const isMono  = (key) => ['sr', 'qty', 'unit_price', 'total_value', 'dia_wt', 'col_wt'].includes(key);
  const isMuted = (key) => ['dia_wt', 'col_wt', 'size'].includes(key);

  return (
    <div className="ej-a4">
      {/* Top colour band — same as CMR */}
      <div className="ej-band"/>

      <div className="ej-pad" style={{ paddingTop: 24 }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div className="ej-logo">
            <svg width="34" height="34" viewBox="0 0 36 36" aria-hidden="true">
              <circle cx="18" cy="18" r="16.5" fill="#0B3D2E"/>
              <path d="M18 7 L27 18 L18 29 L9 18 Z" fill="none" stroke="#C9A24B" strokeWidth="1.5"/>
              <path d="M18 12.5 L23.5 18 L18 23.5 L12.5 18 Z" fill="#C9A24B"/>
            </svg>
            <div className="ej-logo-text">
              <span className="ej-logo-name">ESTRELLA JEWELS</span>
              <span className="ej-logo-tag">Fine Gold · Est. 2014</span>
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="ej-eyebrow ej-eyebrow-gold">Commercial Packing List</div>
            <div className="ej-h1" style={{ marginTop: 2, fontSize: 22 }}>Packing List</div>
            <div className="ej-mono" style={{ fontSize: 12, color: '#0B3D2E', fontWeight: 600, marginTop: 3 }}>
              {d.doc_ref || '—'}
            </div>
            {d.invoice_ref && (
              <div className="ej-mono" style={{ fontSize: 10, color: '#475569', marginTop: 1 }}>
                Invoice · {d.invoice_ref}
              </div>
            )}
          </div>
        </div>

        {/* Meta strip — date + references */}
        <div style={{
          display: 'flex', gap: 24, padding: '8px 12px',
          background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 5, marginBottom: 14,
          fontSize: 9,
        }}>
          <div>
            <span style={{ color: '#64748B', fontWeight: 600 }}>Date: </span>
            <span className="ej-mono">{d.issued_date || '—'}</span>
          </div>
          <div>
            <span style={{ color: '#64748B', fontWeight: 600 }}>Proforma: </span>
            <span className="ej-mono">{d.doc_ref || '—'}</span>
          </div>
          <div>
            <span style={{ color: '#64748B', fontWeight: 600 }}>Invoice: </span>
            <span className="ej-mono">{d.invoice_ref || <span style={{ color: '#94A3B8' }}>Pending conversion</span>}</span>
          </div>
          <div>
            <span style={{ color: '#64748B', fontWeight: 600 }}>Currency: </span>
            <span className="ej-mono">{cur}</span>
          </div>
          <div>
            <span style={{ color: '#64748B', fontWeight: 600 }}>Total Lines: </span>
            <span className="ej-mono">{rows.length}</span>
          </div>
          <div>
            <span style={{ color: '#64748B', fontWeight: 600 }}>Total Qty: </span>
            <span className="ej-mono">{totalQty}</span>
          </div>
        </div>

        {/* Party blocks — same layout as CMR */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <PKGPartyBlock label="Seller · Exporter" data={d.seller}/>
          <PKGPartyBlock label="Ship-To · Consignee" data={d.shipto}/>
        </div>

        {/* Table header */}
        <div style={{
          display: 'grid', gridTemplateColumns: _PKG_GRID,
          background: '#F1F5F9', borderTop: '2px solid #0B3D2E',
          borderBottom: '1px solid #CBD5E1',
        }}>
          {_PKG_COLS.map((col, i) => (
            <PKGHeader key={col.key} col={col} isLast={i === _PKG_COLS.length - 1}/>
          ))}
        </div>

        {/* Table rows */}
        {rows.length === 0 ? (
          <div style={{ padding: '20px', textAlign: 'center', color: '#94A3B8', fontSize: 11 }}>
            No packing lines loaded — open this batch on the proforma detail page.
          </div>
        ) : rows.map((r, ri) => (
          <div
            key={r.sr || ri}
            style={{
              display: 'grid', gridTemplateColumns: _PKG_GRID,
              borderBottom: '1px solid #F1F5F9',
              background: ri % 2 === 0 ? '#FFFFFF' : '#FAFBFC',
            }}
          >
            {_PKG_COLS.map((col, i) => (
              <PKGCell
                key={col.key}
                value={cellVal(r, col.key)}
                align={col.align}
                isLast={i === _PKG_COLS.length - 1}
                bold={col.key === 'design'}
                mono={isMono(col.key)}
                muted={isMuted(col.key) && !cellVal(r, col.key) || cellVal(r, col.key) === '—'}
              />
            ))}
          </div>
        ))}

        {/* Totals footer */}
        <div style={{
          display: 'grid', gridTemplateColumns: _PKG_GRID,
          borderTop: '2px solid #0B3D2E', background: '#FBF8F1',
          fontSize: 8.5, fontWeight: 700, marginBottom: 20,
        }}>
          {_PKG_COLS.map((col, i) => {
            const isLast = i === _PKG_COLS.length - 1;
            if (col.key === 'ctg') {
              return (
                <div key={col.key} style={{ padding: '5px 4px', borderRight: '1px solid #CBD5E1', color: '#0B3D2E' }}>
                  {rows.length} design(s)
                </div>
              );
            }
            if (col.key === 'qty') {
              return (
                <div key={col.key} style={{ padding: '5px 4px', borderRight: isLast ? 'none' : '1px solid #CBD5E1', textAlign: 'right' }} className="ej-num">
                  {totalQty}
                </div>
              );
            }
            if (col.key === 'total_value') {
              return (
                <div key={col.key} style={{ padding: '5px 4px', borderRight: isLast ? 'none' : '1px solid #CBD5E1', textAlign: 'right' }} className="ej-num">
                  {cur} {_fmtMoney(grandTotal, cur)}
                </div>
              );
            }
            return (
              <div key={col.key} style={{ padding: '5px 4px', borderRight: isLast ? 'none' : '1px solid #CBD5E1' }}/>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', fontSize: 8.5, color: '#94A3B8',
          borderTop: '1px solid #E2E8F0', paddingTop: 10, marginTop: 4,
        }}>
          <span>This packing list is issued under the authority of Proforma {d.doc_ref || '—'}.</span>
          <span>Value authority: commercial sales price in {cur}. Not for customs valuation.</span>
        </div>

      </div>
    </div>
  );
}

Object.assign(window, { EJPackingList });
