/* global React */
// estrella-doc-cmr.jsx — Estrella Document Suite: CMR / Delivery Note print variants
// Adapted from design-canvas prototype (2026-06-06) for real draft data.
//
// cmrData shape (supplied by ProformaDetailPage when carrier data is available):
//   .cmr_no      string                 CMR reference number
//   .doc_ref     string                 linked proforma number
//   .seller      { name, addr, city, vat, email, phone }
//   .shipto      { name, addr, city, zip, country }
//   .buyer       { vat }               buyer VAT (CMR field 2 consignee)
//   .carrier     { name, awb, service, incoterm, origin, destination,
//                  pickup, eta, weight_kg, dim_cm, pieces, insurance, path } | null
//   .goods_summary  string  — one-line metal+stone description: "14 Karat White Gold & Pink Gold · Diamond"
//   .lines[]     { item_type, qty, net_weight, origin }
//                where: item_type = "Pendant" | "Ring" | "Earrings" | ...  (human-readable)
//                       qty       = total pieces for this item type
//                       net_weight = total kg or null when not in packing list
//                       origin    = country of manufacture (e.g. "India")
//                Source authority: SALES packing list lines, aggregated by item_type ONLY.
//                Metal and stone types appear in goods_summary header — NOT per line.
//                HS/CN codes are NOT included in CMR output — kept in DB only.
//                Maximum ~3–6 rows. CMR is a transport document, not a commercial detail sheet.
//
// Depends on: estrella-doc-tokens.css (loaded in index.html)
// Exports:    window.EJCMRClassic, window.EJCMRModern
//
// NOTE: No backend route generates a CMR PDF in this system.
// Use the Download PDF button in the preview toolbar (window.print with A4 CSS).

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
  const lines = d.lines || [];
  const totalKg = carrier ? Number(carrier.weight_kg || 0) : 0;
  const _totQty = lines.reduce((s, l) => s + (Number(l.qty) || 0), 0);
  const _totNw  = lines.reduce((s, l) => s + (l.net_weight || 0), 0);

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
              {d.shipto
                ? [d.shipto.city || "—", d.shipto.zip || null, d.shipto.country || null]
                    .filter(Boolean).join(", ")
                : "—"}
            </EJCMRBox>
            <EJCMRBox n="4" label="Place / date of taking over" border="left">
              {carrier ? `${carrier.origin || "—"} · ${carrier.pickup || "—"}` : "—"}
            </EJCMRBox>
            <EJCMRBox n="5" label="Documents attached" border="left">
              {d.doc_ref ? `Proforma ${d.doc_ref} · Packing list · Hallmark cert` : "Packing list · Hallmark cert"}
            </EJCMRBox>
          </div>

          {/* Goods description block — metal + stone summary, country of origin */}
          {d.goods_summary && (
            <div style={{
              borderTop: "1px solid #CBD5E1", padding: "8px 10px",
              background: "#F8FAFC", fontSize: 9.5,
            }}>
              <span style={{ color: "#475569", fontWeight: 600 }}>Goods: </span>
              <span>{d.goods_summary}</span>
              <span style={{ marginLeft: 10, color: "#64748B" }}>Country of Origin: India</span>
            </div>
          )}

          {/* Goods header row */}
          <div style={{
            display: "grid", gridTemplateColumns: "40px 1fr 110px 80px 60px",
            borderTop: "1.5px solid #0B3D2E", background: "#F8FAFC",
          }}>
            {[["6", "No."], ["7", "Item Category"], ["8", "Packaging"], ["9", "Net Weight"], ["10", "Qty"]].map(([n, lbl], i) => (
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

          {/* Lines — item_type totals only (transport summary) */}
          {lines.length === 0 ? (
            <div style={{ padding: "12px 10px", fontSize: 10, color: "#94A3B8", borderTop: "1px solid #E2E8F0" }}>
              No goods lines
            </div>
          ) : lines.map((l, i) => (
            <div key={`${l.item_type || ""}${i}`} style={{
              display: "grid", gridTemplateColumns: "40px 1fr 110px 80px 60px",
              borderTop: "1px solid #E2E8F0", fontSize: 10,
            }}>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0" }}>{i + 1}</div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0", fontWeight: 600 }}>
                {l.item_type || "—"}
              </div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0", fontSize: 9, color: "#475569" }}>Polybag + Jewellery box</div>
              <div style={{ padding: "8px 8px", borderRight: "1px solid #E2E8F0", textAlign: "right" }} className="ej-num">
                {l.net_weight != null ? `${Number(l.net_weight).toFixed(3)} kg` : "—"}
              </div>
              <div style={{ padding: "8px 8px", textAlign: "right" }} className="ej-num">{Number(l.qty) || 0}</div>
            </div>
          ))}

          {/* Totals row */}
          <div style={{
            display: "grid", gridTemplateColumns: "40px 1fr 110px 80px 60px",
            borderTop: "1.5px solid #0B3D2E", background: "#FBF8F1",
            fontSize: 10, fontWeight: 600,
          }}>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>—</div>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>{lines.length} item type(s)</div>
            <div style={{ padding: "8px", borderRight: "1px solid #CBD5E1" }}>1 outer carton</div>
            <div style={{ padding: "8px", textAlign: "right", borderRight: "1px solid #CBD5E1" }} className="ej-num">
              {_totNw > 0 ? `${_totNw.toFixed(3)} kg` : (totalKg > 0 ? `${totalKg.toFixed(3)} kg` : "—")}
            </div>
            <div style={{ padding: "8px", textAlign: "right" }} className="ej-num">{_totQty || "—"}</div>
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
  const lines = d.lines || [];
  const _totQty = lines.reduce((s, l) => s + (Number(l.qty) || 0), 0);

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
          <div className="ej-eyebrow">Delivery Note · List przewozowy</div>
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

        {/* Goods description header */}
        {d.goods_summary && (
          <div style={{
            padding: "10px 14px", background: "#F8FAFC",
            border: "1px solid #E2E8F0", borderRadius: 6, marginBottom: 16, fontSize: 10,
          }}>
            <span style={{ fontWeight: 600, color: "#0B3D2E" }}>Goods: </span>
            <span>{d.goods_summary}</span>
            <span style={{ marginLeft: 10, color: "#64748B" }}>· Country of Origin: India</span>
          </div>
        )}

        {/* Contents */}
        <div className="ej-eyebrow" style={{ marginBottom: 8 }}>
          Item summary · {lines.length} type(s) · {_totQty} pcs total
        </div>
        <table className="ej-table" style={{ marginBottom: 22 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              <th>Item Category</th>
              <th style={{ width: 160 }}>Packaging</th>
              <th style={{ width: 60 }}>Origin</th>
              <th className="ej-r" style={{ width: 90 }}>Net Weight</th>
              <th className="ej-r" style={{ width: 55 }}>Qty</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: "#94A3B8", padding: "14px 10px" }}>No goods lines</td>
              </tr>
            )}
            {lines.map((l, i) => (
              <tr key={`${l.item_type || ""}${i}`}>
                <td><span style={{ fontWeight: 600 }}>{l.item_type || "—"}</span></td>
                <td style={{ fontSize: 9.5, color: "#475569" }}>Polybag + Jewellery box</td>
                <td>{l.origin || "India"}</td>
                <td className="ej-r ej-num">
                  {l.net_weight != null ? `${Number(l.net_weight).toFixed(3)} kg` : "—"}
                </td>
                <td className="ej-r ej-num">{Number(l.qty) || 0}</td>
              </tr>
            ))}
            {lines.length > 0 && (
              <tr style={{ fontWeight: 600, background: "#F8FAFC" }}>
                <td>Total</td>
                <td></td>
                <td></td>
                <td className="ej-r ej-num">
                  {_totQty > 0 ? (
                    lines.reduce((s, l) => s + (l.net_weight || 0), 0) > 0
                      ? `${lines.reduce((s, l) => s + (l.net_weight || 0), 0).toFixed(3)} kg`
                      : "—"
                  ) : "—"}
                </td>
                <td className="ej-r ej-num">{_totQty}</td>
              </tr>
            )}
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
