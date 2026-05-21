/* global React, EJ_SAMPLE, EJLogo, EJAddress, EJCarrierStrip, EJThumb, EJBank, EJCompliance, EJ_tri */
const S = EJ_SAMPLE;

// ============================================================
// PROFORMA — Variant A · CLASSIC
// Tall masthead, centered title, traditional party blocks
// ============================================================
function ProformaClassic({ tweaks = {} }) {
  const showCarrier = tweaks.carrier !== false;
  const showPhotos = tweaks.photos !== false;
  return (
    <div className="a4">
      <div className="ej-pattern"/>
      <div className="ej-band"/>
      <div className="pad" style={{ paddingTop: 28 }}>
        {/* Masthead */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <EJLogo size="lg"/>
          <div style={{ textAlign: "right" }}>
            <div className="ej-eyebrow ej-eyebrow-gold">Pro Forma · Predfaktúra</div>
            <div className="ej-h1" style={{ marginTop: 2 }}>Faktura proforma</div>
            <div className="ej-mono" style={{ fontSize: 14, color: "#0B3D2E", fontWeight: 600, marginTop: 4 }}>{S.doc_no}</div>
          </div>
        </div>

        {/* Meta strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 0, border: "1px solid #E2E8F0", borderRadius: 4, marginBottom: 18 }}>
          {[
            ["Issued", S.date],
            ["Payment due", S.due],
            ["Method", S.payment],
            ["FX · NBP", `1 EUR = ${S.rate.eur} PLN · ${S.rate.date}`],
          ].map(([k, v], i) => (
            <div key={k} style={{ padding: "10px 12px", borderRight: i < 3 ? "1px solid #E2E8F0" : "none" }}>
              <div className="ej-eyebrow">{k}</div>
              <div style={{ marginTop: 2, fontWeight: 600 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Party row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 16 }}>
          <EJAddress label={EJ_tri("seller")} party={S.seller}/>
          <EJAddress label={EJ_tri("buyer")} party={S.buyer}/>
          <EJAddress label={EJ_tri("shipto")} party={S.shipto}/>
        </div>

        {/* Carrier strip */}
        {showCarrier && (
          <div style={{ marginBottom: 16 }}>
            <div className="ej-eyebrow" style={{ marginBottom: 6 }}>{EJ_tri("carrier")}</div>
            <EJCarrierStrip/>
          </div>
        )}

        {/* Lines */}
        <table className="ej-table" style={{ marginBottom: 12 }}>
          <thead>
            <tr>
              <th style={{ width: 22 }}>#</th>
              {showPhotos && <th style={{ width: 40 }}/>}
              <th>Description · Nazwa · Popis</th>
              <th style={{ width: 70 }}>SKU</th>
              <th style={{ width: 50 }}>Origin</th>
              <th className="ej-r" style={{ width: 36 }}>Qty</th>
              <th className="ej-r" style={{ width: 70 }}>Unit · EUR</th>
              <th className="ej-c" style={{ width: 40 }}>Tax</th>
              <th className="ej-r" style={{ width: 80 }}>Net · EUR</th>
            </tr>
          </thead>
          <tbody>
            {S.lines.map((l, i) => (
              <tr key={l.sku}>
                <td style={{ color: "#94A3B8" }}>{i + 1}</td>
                {showPhotos && <td><EJThumb kind={l.thumb}/></td>}
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc_en}</div>
                  <div style={{ color: "#64748B", fontSize: 9.5 }}>{l.desc_pl}</div>
                  <div style={{ color: "#64748B", fontSize: 9.5 }}>{l.desc_sk}</div>
                  {l.purity !== "Service" && <div style={{ marginTop: 3 }}><span className="ej-pill ej-pill-gold">{l.purity}</span></div>}
                </td>
                <td className="ej-mono" style={{ fontSize: 9.5 }}>{l.sku}</td>
                <td>{l.origin}</td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{l.unit_price.toFixed(2)}</td>
                <td className="ej-c">0% WDT</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{l.net.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Totals */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 18 }}>
          <div style={{ width: 320, border: "1px solid #E2E8F0", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderBottom: "1px solid #E2E8F0", fontSize: 10 }}>
              <span>Subtotal · EUR</span><span className="ej-mono">{S.total_eur.toFixed(2)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderBottom: "1px solid #E2E8F0", fontSize: 10 }}>
              <span>VAT (0% WDT)</span><span className="ej-mono">0.00</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 12px", background: "#0B3D2E", color: "#fff", fontSize: 12, fontWeight: 700 }}>
              <span>Total due</span><span className="ej-mono">EUR {S.total_eur.toFixed(2)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 12px", background: "#FBF8F1", fontSize: 9, color: "#B0892F" }}>
              <span>= PLN reference</span><span className="ej-mono">{S.total_pln.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* Bank */}
        <div style={{ marginBottom: 14 }}>
          <EJBank/>
        </div>

        {/* Compliance */}
        <EJCompliance/>

        {/* Signature row */}
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 32, fontSize: 9, color: "#64748B" }}>
          <div style={{ borderTop: "1px solid #CBD5E1", paddingTop: 4, width: 220 }}>Authorised signatory · Estrella Jewels</div>
          <div style={{ borderTop: "1px solid #CBD5E1", paddingTop: 4, width: 220, textAlign: "right" }}>Buyer signature</div>
        </div>
      </div>

      {/* Footer rule */}
      <div style={{ position: "absolute", bottom: 22, left: 48, right: 48, display: "flex", justifyContent: "space-between", fontSize: 8.5, color: "#94A3B8", borderTop: "1px solid #E2E8F0", paddingTop: 10 }}>
        <span>{S.seller.sales}</span>
        <span>{S.seller.email} · {S.seller.web}</span>
        <span>{S.seller.phone}</span>
      </div>
    </div>
  );
}

// ============================================================
// PROFORMA — Variant B · MODERN (mono-heavy, lots of negative space)
// ============================================================
function ProformaModern({ tweaks = {} }) {
  const showCarrier = tweaks.carrier !== false;
  const showPhotos = tweaks.photos !== false;
  return (
    <div className="a4">
      <div className="pad-tight" style={{ paddingTop: 36 }}>
        {/* Top bar */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 36 }}>
          <EJLogo/>
          <div style={{ display: "flex", gap: 6 }}>
            <span className="ej-pill ej-pill-green">PRO FORMA</span>
            <span className="ej-pill">EUR</span>
            <span className="ej-pill">WDT 0%</span>
          </div>
        </div>

        {/* Hero */}
        <div style={{ marginBottom: 28 }}>
          <div className="ej-eyebrow" style={{ marginBottom: 6 }}>Pro Forma · Faktura proforma · Predfaktúra</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
            <div className="ej-h1" style={{ fontSize: 36, color: "#0B3D2E" }}>{S.doc_no}</div>
            <div style={{ fontSize: 11, color: "#64748B" }}>Issued {S.date} · Due {S.due}</div>
          </div>
          <div style={{ height: 2, width: 64, background: "#C9A24B", marginTop: 14 }}/>
        </div>

        {/* 2-col grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 28 }}>
          <div>
            <div className="ej-eyebrow" style={{ marginBottom: 6 }}>From</div>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{S.seller.name}</div>
            <div style={{ color: "#475569", fontSize: 10 }}>{S.seller.addr}</div>
            <div style={{ color: "#475569", fontSize: 10 }}>{S.seller.city}</div>
            <div style={{ color: "#475569", fontSize: 10, marginTop: 4 }}>VAT EU · {S.seller.vat}</div>
          </div>
          <div>
            <div className="ej-eyebrow" style={{ marginBottom: 6 }}>For</div>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{S.buyer.name}</div>
            <div style={{ color: "#475569", fontSize: 10 }}>{S.buyer.addr}</div>
            <div style={{ color: "#475569", fontSize: 10 }}>{S.buyer.city}, {S.buyer.country}</div>
            <div style={{ color: "#475569", fontSize: 10, marginTop: 4 }}>VAT EU · {S.buyer.vat}</div>
            <div style={{ marginTop: 8, fontSize: 9.5, color: "#64748B" }}>Ship to · {S.shipto.addr}, {S.shipto.city}</div>
          </div>
        </div>

        {/* Carrier compact */}
        {showCarrier && (
          <div style={{ marginBottom: 24 }}>
            <EJCarrierStrip/>
          </div>
        )}

        {/* Lines — minimal */}
        <table className="ej-table" style={{ marginBottom: 18 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              {showPhotos && <th style={{ width: 36 }}/>}
              <th>Item</th>
              <th style={{ width: 80 }}>SKU</th>
              <th style={{ width: 50 }}>Origin</th>
              <th className="ej-r" style={{ width: 36 }}>Qty</th>
              <th className="ej-r" style={{ width: 70 }}>Unit</th>
              <th className="ej-r" style={{ width: 80 }}>Net EUR</th>
            </tr>
          </thead>
          <tbody>
            {S.lines.map((l) => (
              <tr key={l.sku}>
                {showPhotos && <td><EJThumb kind={l.thumb}/></td>}
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc_en}</div>
                  <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.desc_pl} · {l.desc_sk}</div>
                </td>
                <td className="ej-mono" style={{ fontSize: 9.5 }}>{l.sku}</td>
                <td>{l.origin}</td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{l.unit_price.toFixed(2)}</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{l.net.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Totals — full width band */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", borderTop: "1px solid #E2E8F0", borderBottom: "1px solid #E2E8F0", marginBottom: 24 }}>
          {[
            ["Items", S.lines.length],
            ["Subtotal", `EUR ${S.total_eur.toFixed(2)}`],
            ["VAT", "0% WDT · 0.00"],
            ["Total due", `EUR ${S.total_eur.toFixed(2)}`, true],
          ].map(([k, v, hi], i) => (
            <div key={k} style={{ padding: "12px 14px", borderRight: i < 3 ? "1px solid #E2E8F0" : "none", background: hi ? "#0B3D2E" : "transparent", color: hi ? "#fff" : undefined }}>
              <div className="ej-eyebrow" style={{ color: hi ? "rgba(255,255,255,0.7)" : undefined }}>{k}</div>
              <div className="ej-mono" style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Bank */}
        <div style={{ marginBottom: 18 }}><EJBank/></div>

        {/* Compliance */}
        <EJCompliance/>
      </div>

      <div style={{ position: "absolute", bottom: 18, left: 40, right: 40, fontSize: 8.5, color: "#94A3B8", display: "flex", justifyContent: "space-between" }}>
        <span>FX · NBP {S.rate.table} · 1 EUR = {S.rate.eur} PLN</span>
        <span>{S.seller.email} · {S.seller.phone}</span>
      </div>
    </div>
  );
}

// ============================================================
// PROFORMA — Variant C · BOLD (left rail, large numerics)
// ============================================================
function ProformaBold({ tweaks = {} }) {
  const showCarrier = tweaks.carrier !== false;
  const showPhotos = tweaks.photos !== false;
  return (
    <div className="a4" style={{ display: "flex" }}>
      {/* Left rail */}
      <div className="ej-rail">
        <EJLogo size="md" mono/>
        <div>
          <div style={{ fontSize: 8.5, letterSpacing: "0.18em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600, marginBottom: 6 }}>Pro Forma</div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{S.doc_no}</div>
          <div style={{ fontSize: 10, opacity: 0.75, marginTop: 4 }}>Faktura proforma · Predfaktúra</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Meta label="Issued" v={S.date}/>
          <Meta label="Payment due" v={S.due}/>
          <Meta label="Method" v={S.payment}/>
          <Meta label="FX · NBP" v={`1 EUR = ${S.rate.eur} PLN`}/>
        </div>

        <div style={{ marginTop: "auto", fontSize: 9, opacity: 0.75, lineHeight: 1.5 }}>
          <div style={{ color: "#C9A24B", fontWeight: 600, marginBottom: 4 }}>Estrella Jewels</div>
          {S.seller.sales}<br/>
          {S.seller.email}<br/>
          {S.seller.phone}
        </div>
      </div>

      {/* Right body */}
      <div style={{ flex: 1, padding: "32px 36px", overflow: "hidden" }}>
        {/* Parties */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
          <EJAddress label="Bill to · Nabywca"  party={S.buyer}/>
          <EJAddress label="Ship to · Odbiorca" party={S.shipto}/>
        </div>

        {/* Carrier */}
        {showCarrier && <div style={{ marginBottom: 18 }}><EJCarrierStrip/></div>}

        {/* Lines */}
        <table className="ej-table" style={{ marginBottom: 16 }}>
          <thead>
            <tr>
              {showPhotos && <th style={{ width: 36 }}/>}
              <th>Description</th>
              <th style={{ width: 70 }}>SKU</th>
              <th style={{ width: 44 }}>Origin</th>
              <th className="ej-r" style={{ width: 32 }}>Qty</th>
              <th className="ej-r" style={{ width: 64 }}>Unit</th>
              <th className="ej-r" style={{ width: 70 }}>Net</th>
            </tr>
          </thead>
          <tbody>
            {S.lines.map((l) => (
              <tr key={l.sku}>
                {showPhotos && <td><EJThumb kind={l.thumb} size={28}/></td>}
                <td>
                  <div style={{ fontWeight: 600, fontSize: 10 }}>{l.desc_en}</div>
                  <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.desc_pl}</div>
                </td>
                <td className="ej-mono" style={{ fontSize: 9 }}>{l.sku}</td>
                <td>{l.origin}</td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{l.unit_price.toFixed(2)}</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{l.net.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Big total */}
        <div style={{ marginBottom: 18, padding: 16, background: "#FBF8F1", borderLeft: "4px solid #C9A24B", borderRadius: 4 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
            <div>
              <div className="ej-eyebrow ej-eyebrow-gold">Total due · WDT 0% intra-EU</div>
              <div style={{ fontSize: 32, fontWeight: 700, color: "#0B3D2E", lineHeight: 1, marginTop: 4 }}>EUR {S.total_eur.toFixed(2)}</div>
              <div style={{ fontSize: 10, color: "#B0892F", marginTop: 2 }}>≈ PLN {S.total_pln.toFixed(2)} · NBP {S.rate.date}</div>
            </div>
            <span className="ej-pill ej-pill-gold" style={{ fontSize: 10 }}>Due {S.due}</span>
          </div>
        </div>

        <EJBank/>
        <div style={{ marginTop: 16 }}><EJCompliance/></div>
      </div>
    </div>
  );
}

function Meta({ label, v }) {
  return (
    <div>
      <div style={{ fontSize: 8.5, letterSpacing: "0.16em", textTransform: "uppercase", opacity: 0.6, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 11, fontWeight: 600, marginTop: 2 }}>{v}</div>
    </div>
  );
}

Object.assign(window, { ProformaClassic, ProformaModern, ProformaBold });
