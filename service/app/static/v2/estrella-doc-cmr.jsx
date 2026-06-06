/* global React */
// estrella-doc-cmr.jsx — Estrella Document Suite: CMR / Delivery Note print variants
// Adapted from design-canvas prototype (2026-06-06) for real draft data.
//
// cmrData shape (supplied by ProformaDetailPage when carrier data is available):
//   .cmr_no      string                 CMR reference number
//   .doc_ref     string                 linked proforma number
//   .seller      { name, addr, city, vat, email, phone }
//   .shipto      { name, addr, city, country }
//   .buyer       { vat }               buyer VAT (CMR field 2 consignee)
//   .carrier     { name, awb, service, incoterm, origin, destination,
//                  pickup, eta, weight_kg, dim_cm, pieces, insurance, path } | null
//   .lines[]     { sku, desc, purity, qty, origin }
//
// Depends on: estrella-doc-tokens.css (loaded in index.html)
// Exports:    window.EJCMRClassic, window.EJCMRModern
//
// NOTE: No backend route generates a CMR PDF in this system.
// These components provide print-preview only — the CMR Print button in the
// toolbar is disabled with reason "No CMR backend route".

// ── CMR box (numbered field, like the legal form) ────────────────────────────
function EJCMRBox({ n, label, children, border }) {
  return (
    <div style={{
      padding: "8px 10px",
      borderLeft: border === "left" ? "1px solid #CBD5E1" : "none",
      fontSize: 10,
    }}>
      <div style={{ fontSize: 8, color: "#64748B", fontWeight: 600, marginBottom: 3 }}>
        <span style={{
          background: "#0B3D2E", color: "#fff",
          padding: "1px 5px", borderRadius: 2, marginRight: 5,
        }}>{n}</span>
        {label}
      </div>
      <div>{children}</div>
    </div>
  );
}

// ── Signature box ────────────────────────────────────────────────────────────
function EJCMRSigBox({ n, label, who, border }) {
  return (
    <div style={{
      padding: "10px 12px",
      borderLeft: border === "left" ? "1px solid #CBD5E1" : "none",
      minHeight: 100,
    }}>
      <div style={{ fontSize: 8, color: "#64748B", fontWeight: 600, marginBottom: 4 }}>
        <span style={{
          background: "#0B3D2E", color: "#fff",
          padding: "1px 5px", borderRadius: 2, marginRight: 5,
        }}>{n}</span>
        {label}
      </div>
      <div style={{
        borderTop: "1px dashed #CBD5E1", marginTop: 60, paddingTop: 4,
        fontSize: 9, color: "#94A3B8",
      }}>{who || "—"}</div>
    </div>
  );
}

// ── Inline DHL chip ──────────────────────────────────────────────────────────
function EJCMRCarrierChip({ name }) {
  if (!name) return null;
  const isDHL = name.toUpperCase().includes("DHL");
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      background: isDHL ? "#FFCC00" : "#E2E8F0",
      color: isDHL ? "#D40511" : "#334155",
      fontWeight: 900, fontSize: 11,
      padding: "2px 7px", borderRadius: 3,
      letterSpacing: "0.04em",
    }}>
      {isDHL ? "DHL" : name.slice(0, 6).toUpperCase()}
    </span>
  );
}

// ── Empty carrier placeholder ─────────────────────────────────────────────────
function EJCMRNoCarrier() {
  return (
    <div style={{
      padding: "12px 14px", background: "#FBF8F1", border: "1px dashed #CBD5E1",
      borderRadius: 4, color: "#94A3B8", fontSize: 10, marginBottom: 14, textAlign: "center",
    }}>
      Carrier AWB not yet assigned — CMR carrier fields will populate when shipment is dispatched.
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VARIANT A — CLASSIC
// 24-field CMR-inspired boxed layout · signature blocks
// ═══════════════════════════════════════════════════════════════════════════════
function EJCMRClassic({ cmrData }) {
  const d = cmrData || {};
  const carrier = d.carrier || null;
  const lines = (d.lines || []).filter(l => l.purity !== "Service");
  const totalKg = carrier ? Number(carrier.weight_kg || 0) : 0;

  return (
    <div className="ej-a4">
      <div className="ej-band"/>
      <div className="ej-pad" style={{ paddingTop: 24 }}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
          <div className="ej-logo">
            <svg width="36" height="36" viewBox="0 0 36 36" aria-hidden="true">
              <circle cx="18" cy="18" r="16.5" fill="#0B3D2E"/>
              <path d="M18 7 L27 18 L18 29 L9 18 Z" fill="none" stroke="#C9A24B" strokeWidth="1.5"/>
              <path d="M18 12.5 L23.5 18 L18 23.5 L12.5 18 Z" fill="#C9A24B"/>
            </svg>
            <div className="ej-logo-text">
              <span className="ej-logo-name">ESTRELLA JEWELS</span>
              <span className="ej-logo-tag">Fine Gold · Est. 2014</span>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="ej-eyebrow ej-eyebrow-gold">International consignment note</div>
            <div className="ej-h1" style={{ marginTop: 2 }}>CMR · Delivery Note</div>
            <div className="ej-mono" style={{ fontSize: 13, color: "#0B3D2E", fontWeight: 600, marginTop: 4 }}>
              {d.cmr_no || "—"}
            </div>
          </div>
        </div>

        {!carrier && <EJCMRNoCarrier/>}

        {/* CMR grid — boxed fields */}
        <div style={{ border: "1.5px solid #0B3D2E", borderRadius: 4, overflow: "hidden", marginBottom: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
            <EJCMRBox n="1" label="Sender · Nadawca">
              <div style={{ fontWeight: 600 }}>{d.seller && d.seller.name || "—"}</div>
              {d.seller && d.seller.addr && <div>{d.seller.addr}</div>}
              {d.seller && d.seller.city && <div>{d.seller.city}</div>}
              {d.seller && d.seller.vat  && (
                <div style={{ marginTop: 3, color: "#475569" }}>VAT EU · {d.seller.vat}</div>
              )}
            </EJCMRBox>
            <EJCMRBox n="2" label="Consignee · Odbiorca" border="left">
              <div style={{ fontWeight: 600 }}>{d.shipto && d.shipto.name || "—"}</div>
              {d.shipto && d.shipto.addr && <div>{d.shipto.addr}</div>}
              {d.shipto && d.shipto.city && (
                <div>{d.shipto.city}{d.shipto.country ? `, ${d.shipto.country}` : ""}</div>
              )}
              {d.buyer && d.buyer.vat && (
                <div style={{ marginTop: 3, color: "#475569" }}>VAT EU · {d.buyer.vat}</div>
              )}
            </EJCMRBox>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", borderTop: "1px solid #CBD5E1" }}>
            <EJCMRBox n="3" label="Place of delivery">
              {d.shipto ? `${d.shipto.city || "—"}, ${d.shipto.country || ""}` : "—"}
            </EJCMRBox>
            <EJCMRBox n="4" label="Place / date of taking over" border="left">
              {carrier ? `${carrier.origin || "—"} · ${carrier.pickup || "—"}` : "—"}
            </EJCMRBox>
            <EJCMRBox n="5" label="Documents attached" border="left">
              {d.doc_ref ? `Proforma ${d.doc_ref} · Packing list · Hallmark cert` : "Packing list · Hallmark cert"}
            </EJCMRBox>
          </div>

          {/* Goods header row */}
          <div style={{
            display: "grid", gridTemplateColumns: "60px 1fr 110px 80px 80px",
            borderTop: "1.5px solid #0B3D2E", background: "#F8FAFC",
          }}>
            {[["6", "Marks"], ["7", "Description of goods · Nature"], ["8", "Method of pkg"],
              ["9", "Gross kg"], ["10", "Volume m³"]].map(([n, lbl], i) => (
              <div key={n} style={{
                padding: "6px 8px",
                borderRight: i < 4 ? "1px solid #CBD5E1" : "none",
                fontSize: 8.5, color: "#64748B", fontWeight: 600,
              }}>
                <span style={{ background: "#0B3D2E", color: "#fff", padding: "1px 4px", borderRadius: 2, marginRight: 4, fontSize: 7 }}>{n}</span>
                {lbl}
              </div>
            ))}
          </div>

          {/* Lines */}
          {lines.length === 0 ? (
            <div style={{ padding: "12px 10px", fontSize: 10, color: "#94A3B8", borderTop: "1px solid #E2E8F0" }}>
              No goods lines
            </div>
          ) : lines.map((l, i) => (
            <div key={l.sku || i} style={{
              display: "grid", gridTemplateColumns: "60px 1fr 110px 80px 80px",
              borderTop: "1px solid #E2E8F0", fontSize: 10,
            }}>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>EJ-{i + 1}</div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>
                <div style={{ fontWeight: 600 }}>{l.desc || l.sku || "—"}</div>
                {l.purity && <div style={{ color: "#64748B", fontSize: 9 }}>{l.purity} · Origin {l.origin || "—"} · SKU {l.sku}</div>}
              </div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>Sealed jewellery box</div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0", textAlign: "right" }} className="ej-num">
                {totalKg > 0 ? totalKg.toFixed(3) : "—"}
              </div>
              <div style={{ padding: "8px 8px", textAlign: "right" }} className="ej-num">—</div>
            </div>
          ))}

          {/* Totals row */}
          <div style={{
            display: "grid", gridTemplateColumns: "60px 1fr 110px 80px 80px",
            borderTop: "1.5px solid #0B3D2E", background: "#FBF8F1",
            fontSize: 10, fontWeight: 600,
          }}>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>Total</div>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>
              {lines.length} item line(s)
            </div>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>1 carton</div>
            <div style={{ padding: "8px", textAlign: "right", borderRight: "1px solid #CBD5E1" }} className="ej-num">
              {totalKg > 0 ? totalKg.toFixed(3) : "—"}
            </div>
            <div style={{ padding: "8px", textAlign: "right" }} className="ej-num">—</div>
          </div>
        </div>

        {/* Carrier strip */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0, border: "1px solid #CBD5E1", borderRadius: 4, marginBottom: 14 }}>
          <EJCMRBox n="16" label="Carrier · Przewoźnik">
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <EJCMRCarrierChip name={carrier && carrier.name}/>
              {carrier && carrier.service && <span style={{ fontWeight: 600 }}>{carrier.service}</span>}
            </div>
            {carrier && carrier.awb && (
              <div className="ej-mono" style={{ fontSize: 10 }}>AWB {carrier.awb}</div>
            )}
            {!carrier && <div style={{ color: "#94A3B8", fontSize: 9 }}>Awaiting dispatch</div>}
          </EJCMRBox>
          <EJCMRBox n="17" label="Successive carriers" border="left">—</EJCMRBox>
          <EJCMRBox n="20" label="Special agreements · Incoterm" border="left">
            {carrier && (
              <>
                <span className="ej-pill ej-pill-green" style={{ marginRight: 4 }}>
                  {carrier.incoterm || "DAP"}
                </span>
                {carrier.insurance && (
                  <div style={{ marginTop: 4, color: "#64748B", fontSize: 9 }}>
                    Insurance {carrier.insurance} · door-to-door
                  </div>
                )}
              </>
            )}
            {!carrier && <span style={{ color: "#94A3B8", fontSize: 9 }}>—</span>}
          </EJCMRBox>
        </div>

        {/* Signature boxes */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0, border: "1px solid #CBD5E1", borderRadius: 4 }}>
          <EJCMRSigBox n="22" label="Sender's signature & stamp" who="Estrella Jewels"/>
          <EJCMRSigBox n="23" label="Carrier's signature & stamp" who={carrier && carrier.name} border="left"/>
          <EJCMRSigBox n="24" label="Goods received · signature & stamp" who={d.shipto && d.shipto.name} border="left"/>
        </div>

        <div style={{ marginTop: 14, fontSize: 9, color: "#64748B", lineHeight: 1.5 }}>
          This consignment note is governed by the Convention on the Contract for the International
          Carriage of Goods by Road (CMR, Geneva 1956). The sender acknowledges the goods have been
          packaged and labelled in accordance with carrier requirements.
          {d.doc_ref ? ` Goods remain property of Estrella Jewels until full payment is received per Proforma ${d.doc_ref}.` : ""}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VARIANT B — MODERN
// Large CMR reference hero · route diagram · spec strip · signature blocks
// ═══════════════════════════════════════════════════════════════════════════════
function EJCMRModern({ cmrData }) {
  const d = cmrData || {};
  const carrier = d.carrier || null;
  const lines = (d.lines || []).filter(l => l.purity !== "Service");

  return (
    <div className="ej-a4">
      <div className="ej-pad-tight" style={{ paddingTop: 36 }}>

        {/* Top bar */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
          <div className="ej-logo">
            <svg width="36" height="36" viewBox="0 0 36 36" aria-hidden="true">
              <circle cx="18" cy="18" r="16.5" fill="#0B3D2E"/>
              <path d="M18 7 L27 18 L18 29 L9 18 Z" fill="none" stroke="#C9A24B" strokeWidth="1.5"/>
              <path d="M18 12.5 L23.5 18 L18 23.5 L12.5 18 Z" fill="#C9A24B"/>
            </svg>
            <div className="ej-logo-text">
              <span className="ej-logo-name">ESTRELLA JEWELS</span>
              <span className="ej-logo-tag">Fine Gold · Est. 2014</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <span className="ej-pill ej-pill-green">SHIPMENT</span>
            <span className="ej-pill">CMR</span>
            {carrier && (
              <span className="ej-pill ej-pill-gold">{carrier.incoterm || "DAP"}</span>
            )}
          </div>
        </div>

        {/* Hero */}
        <div style={{ marginBottom: 24 }}>
          <div className="ej-eyebrow">Delivery Note · List przewozowy · Dodací list</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 4 }}>
            <div className="ej-h1" style={{ fontSize: 34, color: "#0B3D2E" }}>{d.cmr_no || "—"}</div>
            {carrier && carrier.awb && (
              <>
                <span className="ej-mono" style={{ color: "#64748B" }}>·</span>
                <div className="ej-mono" style={{ fontSize: 14, color: "#475569" }}>AWB {carrier.awb}</div>
              </>
            )}
          </div>
          <div style={{ height: 2, width: 64, background: "#C9A24B", marginTop: 12 }}/>
        </div>

        {!carrier && <EJCMRNoCarrier/>}

        {/* Route diagram */}
        {carrier && (
          <div style={{
            display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 24,
            padding: "20px 24px", border: "1px solid #E2E8F0", borderRadius: 8,
            marginBottom: 24, background: "#F8FAFC",
          }}>
            <div>
              <div className="ej-eyebrow">Origin · Pickup</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", marginTop: 4 }}>
                {carrier.origin || "—"}
              </div>
              {carrier.pickup && <div style={{ fontSize: 10, color: "#64748B" }}>{carrier.pickup}</div>}
              {d.seller && d.seller.name && (
                <div style={{ fontSize: 9.5, marginTop: 6, color: "#475569" }}>{d.seller.name}</div>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <EJCMRCarrierChip name={carrier.name}/>
              <svg width="120" height="20" viewBox="0 0 120 20">
                <line x1="0" y1="10" x2="100" y2="10" stroke="#0B3D2E" strokeWidth="1.5" strokeDasharray="3 3"/>
                <polygon points="100,4 116,10 100,16" fill="#0B3D2E"/>
              </svg>
              {carrier.service && <div style={{ fontSize: 9, color: "#64748B" }}>{carrier.service}</div>}
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="ej-eyebrow">Destination · ETA</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", marginTop: 4 }}>
                {carrier.destination || "—"}
              </div>
              {carrier.eta && <div style={{ fontSize: 10, color: "#64748B" }}>{carrier.eta}</div>}
              {d.shipto && d.shipto.name && (
                <div style={{ fontSize: 9.5, marginTop: 6, color: "#475569" }}>{d.shipto.name}</div>
              )}
            </div>
          </div>
        )}

        {/* Spec strip */}
        {carrier && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", border: "1px solid #E2E8F0", borderRadius: 4, marginBottom: 22 }}>
            {[
              ["Pieces",    carrier.pieces ? `${carrier.pieces} pcs` : "—"],
              ["Gross weight", carrier.weight_kg ? `${carrier.weight_kg} kg` : "—"],
              ["Dimensions", carrier.dim_cm ? `${carrier.dim_cm} cm` : "—"],
              ["Insurance", carrier.insurance || "—"],
              ["Incoterm",  carrier.incoterm || "DAP"],
            ].map(([k, v], i) => (
              <div key={k} style={{ padding: "10px 12px", borderRight: i < 4 ? "1px solid #E2E8F0" : "none" }}>
                <div className="ej-eyebrow">{k}</div>
                <div style={{ fontWeight: 600, marginTop: 2, fontSize: 11 }}>{v}</div>
              </div>
            ))}
          </div>
        )}

        {/* Contents */}
        <div className="ej-eyebrow" style={{ marginBottom: 8 }}>Contents · {lines.length} line item(s)</div>
        <table className="ej-table" style={{ marginBottom: 22 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              <th>Item · Description</th>
              <th style={{ width: 90 }}>SKU</th>
              <th style={{ width: 60 }}>Origin</th>
              <th style={{ width: 110 }}>Purity / Detail</th>
              <th className="ej-r" style={{ width: 50 }}>Qty</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: "#94A3B8", padding: "14px 10px" }}>No goods lines</td>
              </tr>
            )}
            {lines.map((l, i) => (
              <tr key={l.sku || i}>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc || l.sku || "—"}</div>
                </td>
                <td className="ej-mono" style={{ fontSize: 9.5 }}>{l.sku || "—"}</td>
                <td>{l.origin || "—"}</td>
                <td>
                  {l.purity && <span className="ej-pill ej-pill-gold">{l.purity}</span>}
                </td>
                <td className="ej-r ej-num">{l.qty}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Signature blocks */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          {[
            ["Sender",    d.seller && d.seller.name || "Estrella Jewels"],
            ["Carrier",   carrier && carrier.name || "—"],
            ["Consignee", d.shipto && d.shipto.name || "—"],
          ].map(([k, n]) => (
            <div key={k} style={{ paddingTop: 36, borderTop: "1px solid #CBD5E1" }}>
              <div style={{ fontSize: 9, color: "#64748B", fontWeight: 600 }}>{k} · signature &amp; stamp</div>
              <div style={{ fontSize: 10, marginTop: 2 }}>{n}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{
        position: "absolute", bottom: 18, left: 40, right: 40,
        fontSize: 8.5, color: "#94A3B8",
        display: "flex", justifyContent: "space-between",
        borderTop: "1px solid #E2E8F0", paddingTop: 10,
      }}>
        <span>Per CMR Convention (Geneva 1956)</span>
        {d.seller && d.seller.email && (
          <span>{d.seller.email}{d.seller.phone ? ` · ${d.seller.phone}` : ""}</span>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { EJCMRClassic, EJCMRModern });
