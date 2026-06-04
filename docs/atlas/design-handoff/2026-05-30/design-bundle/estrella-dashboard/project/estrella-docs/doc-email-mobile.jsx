/* global React, EJ_SAMPLE, EJLogo, EJCarrierMark */
const E = EJ_SAMPLE;

// ============================================================
// EMAIL — HTML version (table-based, email-safe markup)
// rendered inside an "email client" chrome for preview
// ============================================================
function EmailHtml() {
  return (
    <div className="email-shell">
      <div className="email-chrome">
        <div className="email-from">
          <div className="email-avatar">EJ</div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 12, color: "#0B3D2E" }}>Estrella Jewels Sales</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>sales@estrellajewels.eu → anastazia@panaks.sk</div>
          </div>
        </div>
        <div style={{ fontSize: 10, color: "#94A3B8" }}>2026-05-08 · 09:42 CEST</div>
      </div>
      <div className="email-subject">Pro forma 95/2026 · Estrella Jewels — please confirm</div>

      <div className="email-body">
        <table cellPadding="0" cellSpacing="0" style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            <tr>
              <td style={{ padding: "20px 24px", background: "#0B3D2E" }}>
                <table cellPadding="0" cellSpacing="0" style={{ width: "100%" }}>
                  <tbody>
                    <tr>
                      <td>
                        <EJLogo size="md" mono/>
                      </td>
                      <td style={{ textAlign: "right", color: "#fff" }}>
                        <div style={{ fontSize: 9, letterSpacing: "0.18em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600 }}>Pro Forma · Faktura proforma</div>
                        <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>{E.doc_no}</div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>

            <tr>
              <td style={{ padding: "24px 24px 8px", fontSize: 13, color: "#0F172A", lineHeight: 1.55 }}>
                <p style={{ margin: "0 0 12px" }}>Dobrý deň, Anastazia,</p>
                <p style={{ margin: "0 0 12px" }}>Please find your pro forma <strong>{E.doc_no}</strong> for the items reserved last week. Total <strong>EUR {E.total_eur.toFixed(2)}</strong>, payable by {E.due}. Once we receive the wire we'll dispatch via DHL Express the same day.</p>
                <p style={{ margin: 0, color: "#475569", fontSize: 11 }}>V prílohe nájdete proforma faktúru a CMR. Tovar bude odoslaný hneď po prijatí platby.</p>
              </td>
            </tr>

            <tr>
              <td style={{ padding: "16px 24px" }}>
                <table cellPadding="0" cellSpacing="0" style={{ width: "100%", border: "1px solid #E2E8F0", borderRadius: 6, overflow: "hidden" }}>
                  <tbody>
                    <tr style={{ background: "#FBF8F1" }}>
                      <td style={{ padding: "10px 14px", borderRight: "1px solid #F0E5C8", fontSize: 10 }}>
                        <div style={{ color: "#B0892F", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", fontSize: 8.5 }}>Total due</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", fontFamily: "Söhne Mono, monospace" }}>EUR {E.total_eur.toFixed(2)}</div>
                      </td>
                      <td style={{ padding: "10px 14px", borderRight: "1px solid #F0E5C8", fontSize: 10 }}>
                        <div style={{ color: "#B0892F", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", fontSize: 8.5 }}>Due by</div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: "#0B3D2E" }}>{E.due}</div>
                      </td>
                      <td style={{ padding: "10px 14px", fontSize: 10 }}>
                        <div style={{ color: "#B0892F", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", fontSize: 8.5 }}>Carrier</div>
                        <div style={{ fontSize: 12, fontWeight: 700, color: "#0B3D2E", display: "flex", alignItems: "center", gap: 6 }}>
                          <EJCarrierMark name="DHL"/> Express · ETA {E.carrier.eta}
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>

            <tr>
              <td style={{ padding: "8px 24px" }}>
                <table cellPadding="0" cellSpacing="0" style={{ width: "100%", fontSize: 11 }}>
                  <thead>
                    <tr style={{ background: "#F8FAFC", borderBottom: "2px solid #0B3D2E" }}>
                      <th style={{ padding: "8px 10px", textAlign: "left", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "#64748B" }}>Item</th>
                      <th style={{ padding: "8px 10px", textAlign: "right", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "#64748B", width: 50 }}>Qty</th>
                      <th style={{ padding: "8px 10px", textAlign: "right", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "#64748B", width: 70 }}>Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {E.lines.map(l => (
                      <tr key={l.sku} style={{ borderBottom: "1px solid #F1F5F9" }}>
                        <td style={{ padding: "10px" }}>
                          <div style={{ fontWeight: 600 }}>{l.desc_en}</div>
                          <div style={{ color: "#94A3B8", fontSize: 9, fontFamily: "Söhne Mono, monospace" }}>{l.sku} · {l.purity}</div>
                        </td>
                        <td style={{ padding: "10px", textAlign: "right", fontFamily: "Söhne Mono, monospace" }}>{l.qty}</td>
                        <td style={{ padding: "10px", textAlign: "right", fontFamily: "Söhne Mono, monospace", fontWeight: 600 }}>{l.net.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </td>
            </tr>

            <tr>
              <td style={{ padding: "8px 24px 16px" }}>
                <table cellPadding="0" cellSpacing="0">
                  <tbody>
                    <tr>
                      <td style={{ padding: "12px 22px", background: "#0B3D2E", borderRadius: 4, fontWeight: 600, color: "#fff", fontSize: 12 }}>↓ Download PDF</td>
                      <td style={{ width: 8 }}/>
                      <td style={{ padding: "12px 22px", background: "#fff", border: "1px solid #C9A24B", borderRadius: 4, fontWeight: 600, color: "#0B3D2E", fontSize: 12 }}>View in browser</td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>

            <tr>
              <td style={{ padding: "8px 24px 16px" }}>
                <div style={{ padding: 12, background: "#F0F6F4", borderLeft: "3px solid #0B3D2E", fontSize: 10.5, color: "#475569", lineHeight: 1.55 }}>
                  <strong style={{ color: "#0B3D2E" }}>Bank — EUR:</strong> <span style={{ fontFamily: "Söhne Mono, monospace" }}>PL59 1090 2851 0000 0001 4434 7174</span> · SWIFT WBKPPLPP · Santander Bank Polska. Quote <strong>{E.doc_no}</strong> in the wire reference.
                </div>
              </td>
            </tr>

            <tr>
              <td style={{ padding: "16px 24px", background: "#F8FAFC", fontSize: 9.5, color: "#94A3B8", textAlign: "center", lineHeight: 1.5 }}>
                Estrella Jewels Sp. z o.o. · ul. Sabały 58, 02-174 Warszawa · NIP PL5252812119<br/>
                <a href="#" style={{ color: "#94A3B8" }}>info@estrellajewels.eu</a> · <a href="#" style={{ color: "#94A3B8" }}>www.estrellajewels.eu</a> · GDPR Art.6(1)(b)(c)
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================
// MOBILE — buyer-facing summary view inside iPhone frame
// ============================================================
function MobileView() {
  return (
    <div className="phone">
      <div className="phone-notch"/>
      <div className="phone-screen">
        <div className="m-statusbar">
          <span>9:41</span>
          <span style={{ display: "flex", gap: 4 }}>
            <span>•••</span><span>📶</span><span>100%</span>
          </span>
        </div>

        <div style={{ background: "#0B3D2E", color: "#fff", padding: "14px 16px" }}>
          <EJLogo size="sm" mono/>
        </div>

        <div style={{ padding: "16px", background: "#fff" }}>
          <div style={{ fontSize: 9, letterSpacing: "0.16em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600 }}>Pro Forma</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#0B3D2E", marginTop: 2 }}>{E.doc_no}</div>
          <div style={{ fontSize: 10, color: "#64748B", marginTop: 2 }}>{E.date} · Due {E.due}</div>

          <div style={{ marginTop: 16, padding: 14, background: "#FBF8F1", borderRadius: 6, border: "1px solid #F0E5C8" }}>
            <div style={{ fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "#B0892F", fontWeight: 600 }}>Total due</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#0B3D2E", fontFamily: "Söhne Mono, monospace", marginTop: 2 }}>EUR {E.total_eur.toFixed(2)}</div>
            <div style={{ fontSize: 9, color: "#64748B", marginTop: 4 }}>≈ PLN {E.total_pln.toFixed(2)} · NBP {E.rate.eur}</div>
          </div>

          <div style={{ marginTop: 14, padding: 12, background: "#F0F6F4", borderRadius: 6, display: "flex", alignItems: "center", gap: 10 }}>
            <EJCarrierMark name="DHL"/>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 11, color: "#0B3D2E" }}>DHL Express · DAP</div>
              <div style={{ fontSize: 9, color: "#475569" }}>Warszawa → Trenčín · ETA {E.carrier.eta}</div>
            </div>
            <div style={{ fontSize: 9, color: "#64748B", fontFamily: "Söhne Mono, monospace" }}>{E.carrier.awb}</div>
          </div>

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "#64748B", fontWeight: 600, marginBottom: 6 }}>Items</div>
            {E.lines.map((l, i) => (
              <div key={l.sku} style={{ padding: "10px 0", borderBottom: i < E.lines.length - 1 ? "1px solid #F1F5F9" : "none", display: "flex", gap: 10 }}>
                <div style={{ width: 36, height: 36, background: "#FBF8F1", borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: 9, color: "#C9A24B", fontWeight: 700 }}>{l.qty}×</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#0F172A", lineHeight: 1.3 }}>{l.desc_en}</div>
                  <div style={{ fontSize: 9, color: "#94A3B8", fontFamily: "Söhne Mono, monospace", marginTop: 1 }}>{l.sku}</div>
                </div>
                <div style={{ fontSize: 11, fontWeight: 600, fontFamily: "Söhne Mono, monospace", color: "#0B3D2E" }}>{l.net.toFixed(2)}</div>
              </div>
            ))}
          </div>

          <div style={{ position: "sticky", bottom: 0, marginTop: 18, paddingTop: 12, background: "#fff", display: "flex", flexDirection: "column", gap: 8 }}>
            <button style={{ padding: "14px", background: "#0B3D2E", color: "#fff", border: "none", borderRadius: 8, fontWeight: 600, fontSize: 13 }}>↓ Download PDF</button>
            <button style={{ padding: "14px", background: "#fff", color: "#0B3D2E", border: "1px solid #C9A24B", borderRadius: 8, fontWeight: 600, fontSize: 13 }}>Pay via SEPA · Copy IBAN</button>
            <button style={{ padding: "10px", background: "transparent", color: "#64748B", border: "none", fontSize: 11 }}>Forward to accounting →</button>
          </div>
        </div>

        <div className="m-home"/>
      </div>
    </div>
  );
}

Object.assign(window, { EmailHtml, MobileView });
