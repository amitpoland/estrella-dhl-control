// estrella-doc-packing.jsx — Estrella Document Suite: Packing List PDF (Landscape A4)
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
//                  ctg        = "Pendant" | "Ring" | "Earrings"  (human-readable)
//                  kt         = "14KT" | "18KT"
//                  col        = "W" | "P" | "Y"
//                  quality    = stone quality string (VS1, SI1…) or ""
//                  dia_wt     = diamond weight in ct (null when not yet parsed)
//                  col_wt     = colour-stone weight in ct (null when not yet parsed)
//                  unit_price = sales price per piece (authority = proforma / sales)
//                  total_value = unit_price × qty
//   .grand_total  number       — sum of all total_value; must equal proforma total
//   .total_qty    number       — sum of all qty
//
// Value authority: sales price (same as Proforma + Invoice). NOT landed cost / PZ.
// Currency from draft.currency (per-client). Falls back to 'EUR' only as default.
//
// Visual: A4 landscape (1123×794px) · same CMR Classic brand tokens · ej-table for rows.
// Multi-page: min-height layout, browser handles natural pagination on print.
//
// Exports: window.EJPackingList

'use strict';

// ── Party box (same CMR Classic number-badge style) ──────────────────────────
function PKGPartyBox({ n, label, data, border }) {
  const borderStyle = border === 'left' ? '1px solid #CBD5E1' : 'none';
  return (
    <div style={{ padding: '8px 10px', borderLeft: borderStyle, fontSize: 10 }}>
      <div style={{ fontSize: 8, color: '#64748B', fontWeight: 600, marginBottom: 3 }}>
        <span style={{ background: '#0B3D2E', color: '#fff', padding: '1px 5px', borderRadius: 2, marginRight: 5 }}>{n}</span>
        {label}
      </div>
      {data && data.name  && <div style={{ fontWeight: 600, fontSize: 10, color: '#0F172A' }}>{data.name}</div>}
      {data && data.addr  && <div style={{ fontSize: 9, color: '#475569', marginTop: 1 }}>{data.addr}</div>}
      {data && (data.city || data.zip) && (
        <div style={{ fontSize: 9, color: '#475569' }}>
          {[data.zip, data.city].filter(Boolean).join(' ')}
          {data.country ? `, ${data.country}` : ''}
        </div>
      )}
      {data && data.vat   && <div style={{ fontSize: 8.5, color: '#64748B', marginTop: 2 }}>VAT EU · {data.vat}</div>}
      {data && data.email && <div style={{ fontSize: 8.5, color: '#64748B' }}>{data.email}</div>}
    </div>
  );
}

// ── Number formatters ────────────────────────────────────────────────────────
const _pkgFmtMoney = (v) =>
  v == null ? '—' : Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const _pkgFmtWt = (v) =>
  v != null && Number(v) > 0 ? Number(v).toFixed(4) : '—';

// ── Main component ────────────────────────────────────────────────────────────
function EJPackingList({ packingData }) {
  const d    = packingData || {};
  const rows = d.rows       || [];
  const cur  = d.currency   || 'EUR';

  const grandTotal = d.grand_total != null
    ? d.grand_total
    : rows.reduce((s, r) => s + (r.total_value || 0), 0);
  const totalQty = d.total_qty != null
    ? d.total_qty
    : rows.reduce((s, r) => s + (r.qty || 0), 0);

  return (
    <div className="ej-a4-landscape">

      {/* Top green/gold band — same as CMR */}
      <div className="ej-band"/>

      <div className="ej-pad">

        {/* ── Header: logo left, title right ── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div className="ej-logo">
            <svg width="32" height="32" viewBox="0 0 36 36" aria-hidden="true">
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
            <div className="ej-h1" style={{ fontSize: 22, marginTop: 2 }}>Packing List</div>
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

        {/* ── Seller / Ship-To boxes — CMR Classic bordered grid ── */}
        <div style={{
          border: '1.5px solid #0B3D2E', borderRadius: 4, overflow: 'hidden', marginBottom: 10,
          display: 'grid', gridTemplateColumns: '1fr 1fr',
        }}>
          <PKGPartyBox n="1" label="Seller · Exporter" data={d.seller}/>
          <PKGPartyBox n="2" label="Consignee · Ship-To" data={d.shipto} border="left"/>
        </div>

        {/* ── Document meta strip ── */}
        <div style={{
          display: 'flex', gap: 22, flexWrap: 'wrap',
          padding: '5px 10px', background: '#F8FAFC',
          border: '1px solid #E2E8F0', borderRadius: 4, marginBottom: 10, fontSize: 8.5,
        }}>
          {[
            ['Date',        d.issued_date || '—'],
            ['Proforma',    d.doc_ref     || '—'],
            ['Invoice',     d.invoice_ref || 'Pending conversion'],
            ['Currency',    cur],
            ['Lines',       rows.length],
            ['Total Qty',   totalQty],
            ['Grand Total', `${cur} ${_pkgFmtMoney(grandTotal)}`],
          ].map(([k, v]) => (
            <div key={k}>
              <span style={{ color: '#64748B', fontWeight: 600 }}>{k}: </span>
              <span className="ej-mono" style={{ fontWeight: 500 }}>{v}</span>
            </div>
          ))}
        </div>

        {/* ── 13-column packing table ── */}
        <table className="ej-table" style={{ fontSize: 8, marginBottom: 14 }}>
          <thead>
            <tr style={{ borderTop: '2px solid #0B3D2E' }}>
              <th style={{ width: 30, textAlign: 'center',  padding: '5px 4px' }}>Sr</th>
              <th style={{ width: 78, padding: '5px 4px' }}>Category</th>
              <th style={{ width: 100, padding: '5px 4px' }}>Client PO</th>
              <th style={{ width: 150, padding: '5px 4px' }}>Design</th>
              <th style={{ width: 36, textAlign: 'center',  padding: '5px 4px' }}>Kt</th>
              <th style={{ width: 30, textAlign: 'center',  padding: '5px 4px' }}>Col</th>
              <th style={{ width: 62, textAlign: 'center',  padding: '5px 4px' }}>Quality</th>
              <th style={{ width: 56, textAlign: 'right',   padding: '5px 4px' }}>Dia Wt</th>
              <th style={{ width: 56, textAlign: 'right',   padding: '5px 4px' }}>Col Wt</th>
              <th style={{ width: 36, textAlign: 'right',   padding: '5px 4px' }}>Qty</th>
              <th style={{ width: 74, textAlign: 'right',   padding: '5px 4px' }}>Value&nbsp;({cur})</th>
              <th style={{ width: 88, textAlign: 'right',   padding: '5px 4px' }}>Total Value</th>
              <th style={{ width: 52, textAlign: 'center',  padding: '5px 4px' }}>Size</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={13} style={{ textAlign: 'center', color: '#94A3B8', padding: '20px', fontSize: 11 }}>
                  No packing lines loaded — open this batch from the proforma detail page.
                </td>
              </tr>
            ) : rows.map((r, ri) => (
              <tr key={r.sr || ri} style={{ background: ri % 2 === 0 ? '#FFFFFF' : '#FAFBFC' }}>
                <td className="ej-c ej-num"  style={{ padding: '3px 4px' }}>{r.sr}</td>
                <td                          style={{ padding: '3px 4px' }}>{r.ctg       || '—'}</td>
                <td className="ej-mono"      style={{ padding: '3px 4px', fontSize: 7.5 }}>{r.client_po || '—'}</td>
                <td style={{ fontWeight: 600, padding: '3px 4px' }}>{r.design || '—'}</td>
                <td className="ej-c ej-mono" style={{ padding: '3px 4px' }}>{r.kt        || '—'}</td>
                <td className="ej-c ej-mono" style={{ padding: '3px 4px' }}>{r.col       || '—'}</td>
                <td className="ej-c"         style={{ padding: '3px 4px' }}>{r.quality   || '—'}</td>
                <td className="ej-r ej-num"  style={{ padding: '3px 4px', color: '#94A3B8' }}>{_pkgFmtWt(r.dia_wt)}</td>
                <td className="ej-r ej-num"  style={{ padding: '3px 4px', color: '#94A3B8' }}>{_pkgFmtWt(r.col_wt)}</td>
                <td className="ej-r ej-num"  style={{ padding: '3px 4px', fontWeight: 600 }}>{r.qty}</td>
                <td className="ej-r ej-num"  style={{ padding: '3px 4px' }}>{_pkgFmtMoney(r.unit_price)}</td>
                <td className="ej-r ej-num"  style={{ padding: '3px 4px', fontWeight: 600 }}>{_pkgFmtMoney(r.total_value)}</td>
                <td className="ej-c ej-mono" style={{ padding: '3px 4px', fontSize: 7.5 }}>{r.size || '—'}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ borderTop: '2px solid #0B3D2E', background: '#FBF8F1', fontWeight: 700 }}>
              <td colSpan={2} style={{ padding: '5px 6px', color: '#0B3D2E', fontSize: 8.5 }}>
                {rows.length} design(s)
              </td>
              <td colSpan={7} style={{ padding: '5px 4px' }}/>
              <td className="ej-r ej-num" style={{ padding: '5px 6px', fontSize: 8.5 }}>{totalQty}</td>
              <td style={{ padding: '5px 4px' }}/>
              <td className="ej-r ej-num" style={{ padding: '5px 6px', fontSize: 8.5 }}>
                {cur} {_pkgFmtMoney(grandTotal)}
              </td>
              <td style={{ padding: '5px 4px' }}/>
            </tr>
          </tfoot>
        </table>

        {/* ── Footer ── */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', fontSize: 8, color: '#94A3B8',
          borderTop: '1px solid #E2E8F0', paddingTop: 8,
        }}>
          <span>Issued under the authority of Proforma {d.doc_ref || '—'}. Value authority: commercial sales price. Not for customs valuation.</span>
          <span>Currency: {cur} · {d.issued_date || '—'}</span>
        </div>

      </div>
    </div>
  );
}

Object.assign(window, { EJPackingList });
