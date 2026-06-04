/* global React, EJ_SAMPLE, EJLogo, EJAddress, EJCarrierStrip, EJCarrierMark, EJThumb */
const SC = EJ_SAMPLE;

// ============================================================
// CMR / Delivery Note — Variant A · CLASSIC
// 24-field CMR-inspired layout with delivery note section
// ============================================================
function CMRClassic() {
  return (
    <div className="a4">
      <div className="ej-band"/>
      <div className="pad" style={{ paddingTop: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
          <EJLogo size="lg"/>
          <div style={{ textAlign: "right" }}>
            <div className="ej-eyebrow ej-eyebrow-gold">International consignment note</div>
            <div className="ej-h1" style={{ marginTop: 2 }}>CMR · Delivery Note</div>
            <div className="ej-mono" style={{ fontSize: 13, color: "#0B3D2E", fontWeight: 600, marginTop: 4 }}>{SC.cmr_no}</div>
          </div>
        </div>

        {/* CMR grid — boxed fields like the legal form */}
        <div style={{ border: "1.5px solid #0B3D2E", borderRadius: 4, overflow: "hidden", marginBottom: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
            {/* 1 Sender */}
            <CMRBox n="1" label="Sender · Nadawca · Odosielateľ">
              <div style={{ fontWeight: 600 }}>{SC.seller.name}</div>
              <div>{SC.seller.addr}</div>
              <div>{SC.seller.city}</div>
              <div style={{ marginTop: 3, color: "#475569" }}>VAT EU · {SC.seller.vat}</div>
            </CMRBox>
            {/* 2 Consignee */}
            <CMRBox n="2" label="Consignee · Odbiorca · Príjemca" border="left">
              <div style={{ fontWeight: 600 }}>{SC.shipto.name}</div>
              <div>{SC.shipto.addr}</div>
              <div>{SC.shipto.city}, {SC.shipto.country}</div>
              <div style={{ marginTop: 3, color: "#475569" }}>VAT EU · {SC.buyer.vat}</div>
            </CMRBox>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", borderTop: "1px solid #CBD5E1" }}>
            <CMRBox n="3" label="Place of delivery">{SC.shipto.city}, {SC.shipto.country}</CMRBox>
            <CMRBox n="4" label="Place / date of taking over" border="left">{SC.carrier.origin} · {SC.carrier.pickup}</CMRBox>
            <CMRBox n="5" label="Documents attached" border="left">Proforma {SC.doc_no} · Packing list · Hallmark cert</CMRBox>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "60px 1fr 100px 80px 80px", borderTop: "1.5px solid #0B3D2E", background: "#F8FAFC" }}>
            <div style={{ padding: "6px 8px", borderRight: "1px solid #CBD5E1", fontSize: 8.5, color: "#64748B", fontWeight: 600 }}>6 Marks</div>
            <div style={{ padding: "6px 8px", borderRight: "1px solid #CBD5E1", fontSize: 8.5, color: "#64748B", fontWeight: 600 }}>7 Description of goods · Nature</div>
            <div style={{ padding: "6px 8px", borderRight: "1px solid #CBD5E1", fontSize: 8.5, color: "#64748B", fontWeight: 600 }}>8 Method of pkg</div>
            <div style={{ padding: "6px 8px", borderRight: "1px solid #CBD5E1", fontSize: 8.5, color: "#64748B", fontWeight: 600 }}>9 Gross kg</div>
            <div style={{ padding: "6px 8px", fontSize: 8.5, color: "#64748B", fontWeight: 600 }}>10 Volume m³</div>
          </div>
          {SC.lines.filter((l) => l.purity !== "Service").map((l, i) => (
            <div key={l.sku} style={{ display: "grid", gridTemplateColumns: "60px 1fr 100px 80px 80px", borderTop: "1px solid #E2E8F0", fontSize: 10 }}>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>EJ-{i + 1}</div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>
                <div style={{ fontWeight: 600 }}>{l.desc_en}</div>
                <div style={{ color: "#64748B", fontSize: 9.5 }}>{l.desc_pl}</div>
                <div style={{ color: "#64748B", fontSize: 9 }}>SKU {l.sku} · Origin {l.origin} · {l.purity}</div>
              </div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>Sealed jewellery box · 1 carton</div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0", textAlign: "right" }} className="ej-num">{SC.carrier.weight_kg.toFixed(2)}</div>
              <div style={{ padding: "8px 8px", textAlign: "right" }} className="ej-num">0.003</div>
            </div>
          ))}
          <div style={{ display: "grid", gridTemplateColumns: "60px 1fr 100px 80px 80px", borderTop: "1.5px solid #0B3D2E", background: "#FBF8F1", fontSize: 10, fontWeight: 600 }}>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>Total</div>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>{SC.lines.filter((l) => l.purity !== "Service").length} item line(s) · 1 piece total</div>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>1 carton</div>
            <div style={{ padding: "8px", textAlign: "right", borderRight: "1px solid #CBD5E1" }} className="ej-num">{SC.carrier.weight_kg.toFixed(2)}</div>
            <div style={{ padding: "8px", textAlign: "right" }} className="ej-num">0.003</div>
          </div>
        </div>

        {/* Carrier + signatures */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0, border: "1px solid #CBD5E1", borderRadius: 4, marginBottom: 14 }}>
          <CMRBox n="16" label="Carrier · Przewoźnik">
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <EJCarrierMark name={SC.carrier.name}/>
              <span style={{ fontWeight: 600 }}>{SC.carrier.service}</span>
            </div>
            <div className="ej-mono">AWB {SC.carrier.awb}</div>
          </CMRBox>
          <CMRBox n="17" label="Successive carriers" border="left">—</CMRBox>
          <CMRBox n="20" label="Special agreements · Incoterm" border="left">
            <span className="ej-pill ej-pill-green">{SC.carrier.incoterm}</span> &nbsp;
            <span className="ej-pill">{SC.carrier.path}</span>
            <div style={{ marginTop: 4, color: "#64748B", fontSize: 9 }}>Insurance {SC.carrier.insurance} · door-to-door</div>
          </CMRBox>
        </div>

        {/* Sig boxes */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0, border: "1px solid #CBD5E1", borderRadius: 4 }}>
          <SigBox n="22" label="Sender's signature & stamp" who="Estrella Jewels"/>
          <SigBox n="23" label="Carrier's signature & stamp" who={SC.carrier.name} border="left"/>
          <SigBox n="24" label="Goods received · signature & stamp" who={SC.shipto.name} border="left"/>
        </div>

        <div style={{ marginTop: 14, fontSize: 9, color: "#64748B", lineHeight: 1.5 }}>
          This consignment note is governed by the Convention on the Contract for the International Carriage of Goods by Road (CMR, Geneva 1956). The sender acknowledges the goods have been packaged and labelled in accordance with carrier requirements. Goods remain property of Estrella Jewels until full payment is received per Proforma {SC.doc_no}.
        </div>
      </div>
    </div>
  );
}

function CMRBox({ n, label, children, border }) {
  return (
    <div style={{ padding: "8px 10px", borderLeft: border === "left" ? "1px solid #CBD5E1" : "none", fontSize: 10 }}>
      <div style={{ fontSize: 8, color: "#64748B", fontWeight: 600, marginBottom: 3 }}>
        <span style={{ background: "#0B3D2E", color: "#fff", padding: "1px 5px", borderRadius: 2, marginRight: 5 }}>{n}</span>
        {label}
      </div>
      <div>{children}</div>
    </div>
  );
}
function SigBox({ n, label, who, border }) {
  return (
    <div style={{ padding: "10px 12px", borderLeft: border === "left" ? "1px solid #CBD5E1" : "none", minHeight: 100 }}>
      <div style={{ fontSize: 8, color: "#64748B", fontWeight: 600, marginBottom: 4 }}>
        <span style={{ background: "#0B3D2E", color: "#fff", padding: "1px 5px", borderRadius: 2, marginRight: 5 }}>{n}</span>
        {label}
      </div>
      <div style={{ borderTop: "1px dashed #CBD5E1", marginTop: 60, paddingTop: 4, fontSize: 9, color: "#94A3B8" }}>{who}</div>
    </div>
  );
}

// ============================================================
// CMR — Variant B · MODERN delivery note (less form, more spec sheet)
// ============================================================
function CMRModern() {
  return (
    <div className="a4">
      <div className="pad-tight" style={{ paddingTop: 36 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
          <EJLogo/>
          <div style={{ display: "flex", gap: 6 }}>
            <span className="ej-pill ej-pill-green">SHIPMENT</span>
            <span className="ej-pill">CMR</span>
            <span className="ej-pill ej-pill-gold">{SC.carrier.incoterm}</span>
          </div>
        </div>

        <div style={{ marginBottom: 24 }}>
          <div className="ej-eyebrow">Delivery Note · List przewozowy · Dodací list</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <div className="ej-h1" style={{ fontSize: 34, color: "#0B3D2E" }}>{SC.cmr_no}</div>
            <span className="ej-mono" style={{ color: "#64748B" }}>·</span>
            <div className="ej-mono" style={{ fontSize: 14, color: "#475569" }}>AWB {SC.carrier.awb}</div>
          </div>
          <div style={{ height: 2, width: 64, background: "#C9A24B", marginTop: 12 }}/>
        </div>

        {/* Big route diagram */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 24, padding: "20px 24px", border: "1px solid #E2E8F0", borderRadius: 8, marginBottom: 24, background: "#F8FAFC" }}>
          <div>
            <div className="ej-eyebrow">Origin · Pickup</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", marginTop: 4 }}>{SC.carrier.origin}</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>{SC.carrier.pickup}</div>
            <div style={{ fontSize: 9.5, marginTop: 6, color: "#475569" }}>{SC.seller.name}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
            <EJCarrierMark name={SC.carrier.name}/>
            <svg width="120" height="20" viewBox="0 0 120 20">
              <line x1="0" y1="10" x2="100" y2="10" stroke="#0B3D2E" strokeWidth="1.5" strokeDasharray="3 3"/>
              <polygon points="100,4 116,10 100,16" fill="#0B3D2E"/>
            </svg>
            <div style={{ fontSize: 9, color: "#64748B" }}>{SC.carrier.service}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="ej-eyebrow">Destination · ETA</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", marginTop: 4 }}>{SC.carrier.destination}</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>{SC.carrier.eta}</div>
            <div style={{ fontSize: 9.5, marginTop: 6, color: "#475569" }}>{SC.shipto.name}</div>
          </div>
        </div>

        {/* Spec strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", border: "1px solid #E2E8F0", borderRadius: 4, marginBottom: 22 }}>
          {[
            ["Pieces", `${SC.carrier.pieces} pcs`],
            ["Gross weight", `${SC.carrier.weight_kg} kg`],
            ["Dimensions", SC.carrier.dim_cm + " cm"],
            ["Volume", "0.003 m³"],
            ["Insurance", SC.carrier.insurance],
            ["Clearance", SC.carrier.path],
          ].map(([k, v], i) => (
            <div key={k} style={{ padding: "10px 12px", borderRight: i < 5 ? "1px solid #E2E8F0" : "none" }}>
              <div className="ej-eyebrow">{k}</div>
              <div style={{ fontWeight: 600, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Items */}
        <div className="ej-eyebrow" style={{ marginBottom: 8 }}>Contents</div>
        <table className="ej-table" style={{ marginBottom: 22 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              <th style={{ width: 36 }}/>
              <th>Item</th>
              <th style={{ width: 90 }}>SKU</th>
              <th style={{ width: 60 }}>Origin</th>
              <th style={{ width: 110 }}>Purity / Detail</th>
              <th className="ej-r" style={{ width: 50 }}>Qty</th>
              <th className="ej-r" style={{ width: 60 }}>kg</th>
            </tr>
          </thead>
          <tbody>
            {SC.lines.filter((l) => l.purity !== "Service").map((l) => (
              <tr key={l.sku}>
                <td><EJThumb kind={l.thumb}/></td>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc_en}</div>
                  <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.desc_pl}</div>
                </td>
                <td className="ej-mono" style={{ fontSize: 9.5 }}>{l.sku}</td>
                <td>{l.origin}</td>
                <td><span className="ej-pill ej-pill-gold">{l.purity}</span></td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{SC.carrier.weight_kg.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Sigs */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          {[
            ["Sender", SC.seller.name],
            ["Carrier", SC.carrier.name],
            ["Consignee", SC.shipto.name],
          ].map(([k, n]) => (
            <div key={k} style={{ paddingTop: 36, borderTop: "1px solid #CBD5E1" }}>
              <div style={{ fontSize: 9, color: "#64748B", fontWeight: 600 }}>{k} · signature & stamp</div>
              <div style={{ fontSize: 10, marginTop: 2 }}>{n}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ position: "absolute", bottom: 18, left: 40, right: 40, fontSize: 8.5, color: "#94A3B8", display: "flex", justifyContent: "space-between", borderTop: "1px solid #E2E8F0", paddingTop: 10 }}>
        <span>Per CMR Convention (Geneva 1956)</span>
        <span>{SC.seller.email} · {SC.seller.phone}</span>
      </div>
    </div>
  );
}

// ============================================================
// CMR — Variant C · BOLD (minimal CMR + huge delivery summary)
// ============================================================
function CMRBold() {
  return (
    <div className="a4" style={{ display: "flex" }}>
      <div className="ej-rail">
        <EJLogo size="md" mono/>
        <div>
          <div style={{ fontSize: 8.5, letterSpacing: "0.18em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600, marginBottom: 6 }}>Delivery · CMR</div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{SC.cmr_no}</div>
          <div style={{ fontSize: 10, opacity: 0.75, marginTop: 4 }}>List przewozowy · Dodací list</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <RailMeta k="Carrier" v={SC.carrier.name}/>
          <RailMeta k="Service" v={SC.carrier.service}/>
          <RailMeta k="AWB" v={SC.carrier.awb} mono/>
          <RailMeta k="Pickup" v={SC.carrier.pickup}/>
          <RailMeta k="ETA" v={SC.carrier.eta}/>
          <RailMeta k="Incoterm" v={SC.carrier.incoterm}/>
          <RailMeta k="Path" v={SC.carrier.path}/>
        </div>
        <div style={{ marginTop: "auto", padding: 12, background: "rgba(255,255,255,0.06)", borderRadius: 4, fontSize: 9, lineHeight: 1.5 }}>
          <div style={{ color: "#C9A24B", fontWeight: 600, marginBottom: 4 }}>Per CMR Convention</div>
          Geneva 1956 · sender certifies goods are correctly packed & labelled.
        </div>
      </div>

      <div style={{ flex: 1, padding: "32px 36px", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {/* Route hero */}
        <div style={{ marginBottom: 24 }}>
          <div className="ej-eyebrow">From → To</div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 8 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#0B3D2E" }}>{SC.carrier.origin}</div>
              <div style={{ fontSize: 10, color: "#64748B", marginTop: 2 }}>{SC.seller.name}</div>
              <div style={{ fontSize: 10, color: "#64748B" }}>{SC.seller.addr}, {SC.seller.city}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 80, height: 1, background: "#0B3D2E" }}/>
              <svg width="14" height="14" viewBox="0 0 14 14"><polygon points="0,2 14,7 0,12" fill="#0B3D2E"/></svg>
              <div style={{ width: 80, height: 1, background: "#0B3D2E" }}/>
            </div>
            <div style={{ flex: 1, textAlign: "right" }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#0B3D2E" }}>{SC.carrier.destination}</div>
              <div style={{ fontSize: 10, color: "#64748B", marginTop: 2 }}>{SC.shipto.name}</div>
              <div style={{ fontSize: 10, color: "#64748B" }}>{SC.shipto.addr}, {SC.shipto.city}, {SC.shipto.country}</div>
            </div>
          </div>
        </div>

        {/* Big stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 24 }}>
          {[
            ["Pieces", SC.carrier.pieces, "package(s)"],
            ["Gross", SC.carrier.weight_kg + " kg", "incl. packaging"],
            ["Dimensions", SC.carrier.dim_cm, "cm L×W×H"],
            ["Insurance", SC.carrier.insurance, "door-to-door"],
          ].map(([k, v, sub]) => (
            <div key={k} style={{ padding: 14, background: "#FBF8F1", borderRadius: 6, borderLeft: "3px solid #C9A24B" }}>
              <div className="ej-eyebrow ej-eyebrow-gold">{k}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", marginTop: 4 }}>{v}</div>
              <div style={{ fontSize: 9, color: "#94A3B8", marginTop: 2 }}>{sub}</div>
            </div>
          ))}
        </div>

        {/* Items */}
        <div className="ej-eyebrow" style={{ marginBottom: 8 }}>Contents · {SC.lines.filter(l => l.purity !== "Service").length} line item(s)</div>
        <table className="ej-table" style={{ marginBottom: 18 }}>
          <thead>
            <tr>
              <th style={{ width: 36 }}/>
              <th>Item</th>
              <th style={{ width: 80 }}>SKU</th>
              <th style={{ width: 50 }}>Origin</th>
              <th>Purity / Detail</th>
              <th className="ej-r" style={{ width: 36 }}>Qty</th>
            </tr>
          </thead>
          <tbody>
            {SC.lines.filter((l) => l.purity !== "Service").map((l) => (
              <tr key={l.sku}>
                <td><EJThumb kind={l.thumb} size={28}/></td>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc_en}</div>
                  <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.desc_sk}</div>
                </td>
                <td className="ej-mono" style={{ fontSize: 9 }}>{l.sku}</td>
                <td>{l.origin}</td>
                <td><span className="ej-pill ej-pill-gold">{l.purity}</span></td>
                <td className="ej-r ej-num">{l.qty}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ marginTop: "auto", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          {[["Sender", SC.seller.name], ["Carrier", SC.carrier.name], ["Consignee", SC.shipto.name]].map(([k, n]) => (
            <div key={k} style={{ paddingTop: 28, borderTop: "1px solid #CBD5E1" }}>
              <div style={{ fontSize: 9, color: "#64748B", fontWeight: 600 }}>{k} · signature & stamp</div>
              <div style={{ fontSize: 10, marginTop: 2 }}>{n}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RailMeta({ k, v, mono }) {
  return (
    <div>
      <div style={{ fontSize: 8.5, letterSpacing: "0.16em", textTransform: "uppercase", opacity: 0.6, fontWeight: 600 }}>{k}</div>
      <div style={{ fontSize: 11, fontWeight: 600, marginTop: 2, fontFamily: mono ? "var(--ej-mono)" : undefined }}>{v}</div>
    </div>
  );
}

Object.assign(window, { CMRClassic, CMRModern, CMRBold });
