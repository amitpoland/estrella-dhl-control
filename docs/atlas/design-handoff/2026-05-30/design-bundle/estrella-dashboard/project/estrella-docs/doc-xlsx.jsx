/* global React, EJ_SAMPLE, EJLogo */
const X = EJ_SAMPLE;

// XLSX PZ workbook — multi-sheet preview rendered as styled HTML
// shows what the branded .xlsx looks like when opened in Excel/Numbers

const PZ_LINES = [
  { lp: 1, code: "EJ-RG-585-0142", name_pl: "Pierścionek 585 — diament VS/G", name_en: "14KT Gold Ring · Diam Stud", uom: "szt.", qty: 1, fob_usd: 145.20, freight_usd: 12.10, ins_usd: 1.45, cif_usd: 158.75, cif_pln: 645.30, duty_pln: 16.13, net_pln: 661.43, vat_pln: 152.13, brutto_pln: 813.56 },
  { lp: 2, code: "EJ-NK-750-0089", name_pl: "Naszyjnik 750 — łańcuszek figaro", name_en: "18KT Gold Necklace · Figaro chain", uom: "szt.", qty: 2, fob_usd: 410.00, freight_usd: 34.20, ins_usd: 4.10, cif_usd: 448.30, cif_pln: 1822.51, duty_pln: 45.56, net_pln: 1868.07, vat_pln: 429.66, brutto_pln: 2297.73 },
  { lp: 3, code: "EJ-ER-585-0205", name_pl: "Kolczyki 585 — sztyfty cyrkonia", name_en: "14KT Gold Earrings · CZ stud", uom: "para", qty: 4, fob_usd: 88.40, freight_usd: 7.37, ins_usd: 0.88, cif_usd: 96.65, cif_pln: 392.93, duty_pln: 9.82, net_pln: 402.75, vat_pln: 92.63, brutto_pln: 495.38 },
  { lp: 4, code: "EJ-BR-925-0312", name_pl: "Bransoletka srebrna 925", name_en: "925 Silver Bracelet", uom: "szt.", qty: 3, fob_usd: 38.00, freight_usd: 3.17, ins_usd: 0.38, cif_usd: 41.55, cif_pln: 168.92, duty_pln: 4.22, net_pln: 173.14, vat_pln: 39.82, brutto_pln: 212.96 },
];
const TOT = PZ_LINES.reduce((a, l) => ({
  qty: a.qty + l.qty,
  fob: a.fob + l.fob_usd, freight: a.freight + l.freight_usd, ins: a.ins + l.ins_usd, cif: a.cif + l.cif_usd,
  cif_pln: a.cif_pln + l.cif_pln, duty: a.duty + l.duty_pln, net: a.net + l.net_pln, vat: a.vat + l.vat_pln, brutto: a.brutto + l.brutto_pln,
}), { qty: 0, fob: 0, freight: 0, ins: 0, cif: 0, cif_pln: 0, duty: 0, net: 0, vat: 0, brutto: 0 });

function SheetTabs({ active = "Calc" }) {
  const tabs = ["Summary", "Calc", "Verify", "FX · NBP", "Notes"];
  return (
    <div style={{ display: "flex", background: "#E8EEF1", borderTop: "1px solid #C7CDD4", paddingLeft: 8, height: 24, alignItems: "stretch" }}>
      {tabs.map((t) => (
        <div key={t} style={{
          padding: "0 14px", display: "flex", alignItems: "center", fontSize: 10, fontWeight: 600,
          background: t === active ? "#fff" : "#E8EEF1",
          borderRight: "1px solid #C7CDD4",
          borderTop: t === active ? "2px solid #0B3D2E" : "2px solid transparent",
          color: t === active ? "#0B3D2E" : "#475569",
          marginTop: t === active ? -1 : 0,
        }}>{t}</div>
      ))}
    </div>
  );
}

// ============================================================
// XLSX — Variant A · CLASSIC (Calc sheet, full ledger style)
// ============================================================
function XlsClassic() {
  return (
    <div className="a4" style={{ background: "#fff", padding: 0 }}>
      {/* Excel toolbar mock */}
      <div style={{ background: "#0B3D2E", color: "#fff", padding: "10px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <EJLogo size="sm" mono/>
          <div style={{ borderLeft: "1px solid rgba(255,255,255,0.25)", paddingLeft: 12 }}>
            <div style={{ fontSize: 10, opacity: 0.7 }}>PZ Calculation Workbook</div>
            <div style={{ fontWeight: 600 }}>PZ_039_044_calc.xlsx</div>
          </div>
        </div>
        <div style={{ fontSize: 10, opacity: 0.85 }}>
          Doc no. <span className="ej-mono" style={{ fontWeight: 600 }}>PZ 12/3/2026</span> · NBP {X.rate.eur} · {X.rate.date}
        </div>
      </div>

      {/* Header bar */}
      <div className="xls" style={{ padding: "14px 18px", background: "#FBF8F1", borderBottom: "1px solid #C9A24B" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 10 }}>
          {[
            ["Sheet", "Calc"],
            ["Lines", PZ_LINES.length],
            ["Total qty", TOT.qty],
            ["CIF (USD)", TOT.cif.toFixed(2)],
            ["Net (PLN)", TOT.net.toFixed(2)],
            ["Brutto (PLN)", TOT.brutto.toFixed(2)],
          ].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 8.5, color: "#B0892F", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase" }}>{k}</div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#0B3D2E", marginTop: 2, fontVariantNumeric: "tabular-nums" }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Excel grid */}
      <div className="xls" style={{ padding: "8px 8px 0" }}>
        <table>
          <thead>
            <tr>
              <th className="corner" style={{ width: 24 }}/>
              {["A · Lp", "B · Code", "C · Name PL / EN", "D · UOM", "E · Qty", "F · FOB $", "G · Frt $", "H · Ins $", "I · CIF $", "J · CIF PLN", "K · Duty PLN", "L · Net PLN", "M · VAT 23%", "N · Brutto PLN"].map((h, i) => (
                <th key={h} style={{ minWidth: i === 2 ? 200 : 60 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PZ_LINES.map((l, i) => (
              <tr key={l.code}>
                <td className="row-h" style={{ textAlign: "center" }}>{i + 2}</td>
                <td>{l.lp}</td>
                <td style={{ fontFamily: "var(--ej-mono)" }}>{l.code}</td>
                <td>
                  <div>{l.name_pl}</div>
                  <div style={{ color: "#64748B", fontSize: 9 }}>{l.name_en}</div>
                </td>
                <td>{l.uom}</td>
                <td className="num">{l.qty}</td>
                <td className="num">{l.fob_usd.toFixed(2)}</td>
                <td className="num">{l.freight_usd.toFixed(2)}</td>
                <td className="num">{l.ins_usd.toFixed(2)}</td>
                <td className="num" style={{ background: "#F0F6F4" }}>{l.cif_usd.toFixed(2)}</td>
                <td className="num">{l.cif_pln.toFixed(2)}</td>
                <td className="num">{l.duty_pln.toFixed(2)}</td>
                <td className="num" style={{ background: "#F0F6F4" }}>{l.net_pln.toFixed(2)}</td>
                <td className="num">{l.vat_pln.toFixed(2)}</td>
                <td className="num" style={{ background: "#F6EFD9", fontWeight: 600 }}>{l.brutto_pln.toFixed(2)}</td>
              </tr>
            ))}
            <tr className="total">
              <td className="row-h" style={{ textAlign: "center" }}>{PZ_LINES.length + 2}</td>
              <td colSpan="4" style={{ fontWeight: 700 }}>RAZEM / TOTAL</td>
              <td className="num">{TOT.qty}</td>
              <td className="num">{TOT.fob.toFixed(2)}</td>
              <td className="num">{TOT.freight.toFixed(2)}</td>
              <td className="num">{TOT.ins.toFixed(2)}</td>
              <td className="num">{TOT.cif.toFixed(2)}</td>
              <td className="num">{TOT.cif_pln.toFixed(2)}</td>
              <td className="num">{TOT.duty.toFixed(2)}</td>
              <td className="num">{TOT.net.toFixed(2)}</td>
              <td className="num">{TOT.vat.toFixed(2)}</td>
              <td className="num">{TOT.brutto.toFixed(2)}</td>
            </tr>
          </tbody>
        </table>

        {/* Verify panel */}
        <div style={{ marginTop: 14, padding: 10, background: "#F0F6F4", border: "1px solid #0B3D2E", borderLeft: "4px solid #0B3D2E", fontSize: 10 }}>
          <div style={{ fontWeight: 700, color: "#0B3D2E", marginBottom: 6 }}>✓ Verification — clean</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6 }}>
            {["A00 duty matches ZC429 · ✓", "CIF reconciled ±$1 · ✓", "Freight allocated by value · ✓",
              "Importer = ESTRELLA JEWELS · ✓", "All lines bilingual · ✓", "Amendment flags: none"].map(c => (
              <div key={c} style={{ fontFamily: "var(--ej-mono)", fontSize: 9 }}>{c}</div>
            ))}
          </div>
        </div>

        {/* Audit log */}
        <div style={{ marginTop: 10, padding: 10, fontSize: 9.5, color: "#475569", border: "1px dashed #CBD5E1" }}>
          <div style={{ fontWeight: 600, marginBottom: 4, color: "#0B3D2E" }}>UWAGI · NOTES</div>
          1. Dotyczy faktur 1226-Y, 1227-Y, 1228-Y · 2. Koszty frachtu i cła rozliczono proporcjonalnie do wartości pozycji · 3. Cło z A00 ZC429 = 75,73 PLN · 4. Odprawa celna przez: DHL Express
        </div>
      </div>

      <div style={{ position: "absolute", bottom: 24, left: 0, right: 0 }}>
        <SheetTabs active="Calc"/>
      </div>
    </div>
  );
}

// ============================================================
// XLSX — Variant B · MODERN (Summary sheet, dashboard-style)
// ============================================================
function XlsModern() {
  return (
    <div className="a4" style={{ background: "#fff", padding: 0 }}>
      <div style={{ background: "#fff", padding: "20px 24px", borderBottom: "1px solid #E2E8F0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <EJLogo/>
        <div style={{ textAlign: "right" }}>
          <div className="ej-eyebrow ej-eyebrow-gold">PZ workbook · Summary</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E" }}>PZ 12/3/2026</div>
          <div style={{ fontSize: 9.5, color: "#64748B" }} className="ej-mono">PZ_039_044_calc.xlsx · NBP 1 USD = 4.0660</div>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {/* KPI tiles */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 18 }}>
          {[
            ["Lines",     PZ_LINES.length, ""],
            ["Total qty", TOT.qty,         "pcs"],
            ["CIF total", "$ " + TOT.cif.toFixed(2), "USD landed"],
            ["Brutto",    "PLN " + TOT.brutto.toFixed(2), "incl. 23% VAT"],
          ].map(([k, v, sub]) => (
            <div key={k} style={{ padding: 14, border: "1px solid #E2E8F0", borderRadius: 6, background: "#fff" }}>
              <div className="ej-eyebrow">{k}</div>
              <div className="ej-mono" style={{ fontSize: 18, fontWeight: 700, color: "#0B3D2E", marginTop: 4 }}>{v}</div>
              <div style={{ fontSize: 9, color: "#94A3B8", marginTop: 2 }}>{sub}</div>
            </div>
          ))}
        </div>

        {/* Cost waterfall */}
        <div style={{ marginBottom: 18 }}>
          <div className="ej-eyebrow" style={{ marginBottom: 8 }}>Landed cost waterfall · PLN</div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 110, padding: "0 6px", borderBottom: "1px solid #E2E8F0" }}>
            {[
              ["FOB", TOT.fob * 4.066, "#0B3D2E"],
              ["+ Freight", TOT.freight * 4.066, "#0F5A45"],
              ["+ Insurance", TOT.ins * 4.066, "#1A7757"],
              ["= CIF (PLN)", TOT.cif_pln, "#C9A24B"],
              ["+ Duty A00", TOT.duty, "#B0892F"],
              ["= Net", TOT.net, "#0B3D2E"],
              ["+ VAT 23%", TOT.vat, "#94A3B8"],
              ["= Brutto", TOT.brutto, "#C9A24B"],
            ].map(([k, v, c]) => {
              const max = TOT.brutto;
              return (
                <div key={k} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                  <div className="ej-mono" style={{ fontSize: 9, color: c, fontWeight: 600 }}>{v.toFixed(0)}</div>
                  <div style={{ width: "100%", height: (v / max) * 80, background: c, borderRadius: "2px 2px 0 0" }}/>
                  <div style={{ fontSize: 8, color: "#475569", textAlign: "center", lineHeight: 1.2 }}>{k}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Compact line ledger */}
        <table className="ej-table" style={{ marginBottom: 16 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              <th style={{ width: 24 }}>#</th>
              <th>Item</th>
              <th className="ej-r" style={{ width: 36 }}>Qty</th>
              <th className="ej-r" style={{ width: 60 }}>CIF $</th>
              <th className="ej-r" style={{ width: 70 }}>CIF PLN</th>
              <th className="ej-r" style={{ width: 60 }}>Duty</th>
              <th className="ej-r" style={{ width: 70 }}>Net PLN</th>
              <th className="ej-r" style={{ width: 70 }}>Brutto PLN</th>
            </tr>
          </thead>
          <tbody>
            {PZ_LINES.map((l) => (
              <tr key={l.code}>
                <td style={{ color: "#94A3B8" }}>{l.lp}</td>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.name_en}</div>
                  <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.code} · {l.name_pl}</div>
                </td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{l.cif_usd.toFixed(2)}</td>
                <td className="ej-r ej-num">{l.cif_pln.toFixed(2)}</td>
                <td className="ej-r ej-num">{l.duty_pln.toFixed(2)}</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{l.net_pln.toFixed(2)}</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600, color: "#B0892F" }}>{l.brutto_pln.toFixed(2)}</td>
              </tr>
            ))}
            <tr style={{ background: "#FBF8F1" }}>
              <td/>
              <td style={{ fontWeight: 700 }}>RAZEM / TOTAL</td>
              <td className="ej-r ej-num" style={{ fontWeight: 700 }}>{TOT.qty}</td>
              <td className="ej-r ej-num" style={{ fontWeight: 700 }}>{TOT.cif.toFixed(2)}</td>
              <td className="ej-r ej-num" style={{ fontWeight: 700 }}>{TOT.cif_pln.toFixed(2)}</td>
              <td className="ej-r ej-num" style={{ fontWeight: 700 }}>{TOT.duty.toFixed(2)}</td>
              <td className="ej-r ej-num" style={{ fontWeight: 700 }}>{TOT.net.toFixed(2)}</td>
              <td className="ej-r ej-num" style={{ fontWeight: 700, color: "#B0892F" }}>{TOT.brutto.toFixed(2)}</td>
            </tr>
          </tbody>
        </table>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ padding: 12, background: "#F0F6F4", border: "1px solid #DCEDE5", borderRadius: 4, fontSize: 9.5 }}>
            <div style={{ fontWeight: 700, color: "#0B3D2E", marginBottom: 4 }}>Verification — clean</div>
            <div>A00 duty matches ZC429 · CIF ±$1 · Importer EJ · 0 amendment flags</div>
          </div>
          <div style={{ padding: 12, background: "#FBF8F1", border: "1px solid #F6EFD9", borderRadius: 4, fontSize: 9.5 }}>
            <div style={{ fontWeight: 700, color: "#B0892F", marginBottom: 4 }}>Notes (UWAGI)</div>
            Freight & duty allocated proportionally by value within each invoice. Customs cleared by DHL Express.
          </div>
        </div>
      </div>

      <div style={{ position: "absolute", bottom: 24, left: 0, right: 0 }}>
        <SheetTabs active="Summary"/>
      </div>
    </div>
  );
}

// ============================================================
// XLSX — Variant C · BOLD (full-page Calc with brand frame)
// ============================================================
function XlsBold() {
  return (
    <div className="a4" style={{ background: "#fff", padding: 0, display: "flex", flexDirection: "column" }}>
      <div className="ej-rail" style={{ width: "100%", padding: "16px 24px", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <EJLogo size="md" mono/>
          <div style={{ borderLeft: "1px solid rgba(255,255,255,0.25)", paddingLeft: 16 }}>
            <div style={{ fontSize: 9, opacity: 0.7, letterSpacing: "0.18em", textTransform: "uppercase", color: "#C9A24B" }}>Goods Receipt — Calc</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>PZ 12/3/2026</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 24 }}>
          <RailKpi k="Lines" v={PZ_LINES.length}/>
          <RailKpi k="CIF" v={"$ " + TOT.cif.toFixed(0)}/>
          <RailKpi k="Net PLN" v={TOT.net.toFixed(0)}/>
          <RailKpi k="Brutto" v={TOT.brutto.toFixed(0)} hi/>
        </div>
      </div>

      <div className="xls" style={{ padding: "16px 24px", flex: 1 }}>
        <table>
          <thead>
            <tr>
              {["Lp", "Kod / SKU", "Nazwa PL · EN", "Qty", "CIF $", "CIF PLN", "Duty", "Net PLN", "VAT 23%", "Brutto PLN"].map((h, i) => (
                <th key={h} style={{ minWidth: i === 2 ? 220 : 60 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PZ_LINES.map((l) => (
              <tr key={l.code}>
                <td>{l.lp}</td>
                <td style={{ fontFamily: "var(--ej-mono)" }}>{l.code}</td>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.name_pl}</div>
                  <div style={{ color: "#64748B", fontSize: 9 }}>{l.name_en}</div>
                </td>
                <td className="num">{l.qty}</td>
                <td className="num">{l.cif_usd.toFixed(2)}</td>
                <td className="num">{l.cif_pln.toFixed(2)}</td>
                <td className="num">{l.duty_pln.toFixed(2)}</td>
                <td className="num" style={{ background: "#F0F6F4" }}>{l.net_pln.toFixed(2)}</td>
                <td className="num">{l.vat_pln.toFixed(2)}</td>
                <td className="num" style={{ background: "#F6EFD9", fontWeight: 700 }}>{l.brutto_pln.toFixed(2)}</td>
              </tr>
            ))}
            <tr className="total">
              <td colSpan="3" style={{ fontWeight: 700 }}>RAZEM / TOTAL</td>
              <td className="num">{TOT.qty}</td>
              <td className="num">{TOT.cif.toFixed(2)}</td>
              <td className="num">{TOT.cif_pln.toFixed(2)}</td>
              <td className="num">{TOT.duty.toFixed(2)}</td>
              <td className="num">{TOT.net.toFixed(2)}</td>
              <td className="num">{TOT.vat.toFixed(2)}</td>
              <td className="num" style={{ background: "#C9A24B", color: "#fff" }}>{TOT.brutto.toFixed(2)}</td>
            </tr>
          </tbody>
        </table>

        <div style={{ marginTop: 16, padding: 14, background: "#0B3D2E", color: "#fff", borderRadius: 4 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.16em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600 }}>Verification result</div>
              <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4 }}>✓ CLEAN — 0 amendment flags · A00 reconciled · CIF ±$1</div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <span className="ej-pill" style={{ background: "#fff", color: "#0B3D2E" }}>process_batch()</span>
              <span className="ej-pill" style={{ background: "#C9A24B", color: "#fff", borderColor: "#C9A24B" }}>Ready for wFirma</span>
            </div>
          </div>
        </div>
      </div>

      <div><SheetTabs active="Calc"/></div>
    </div>
  );
}

function RailKpi({ k, v, hi }) {
  return (
    <div>
      <div style={{ fontSize: 8.5, letterSpacing: "0.14em", textTransform: "uppercase", opacity: 0.7, fontWeight: 600 }}>{k}</div>
      <div className="ej-mono" style={{ fontSize: 16, fontWeight: 700, marginTop: 2, color: hi ? "#C9A24B" : "#fff" }}>{v}</div>
    </div>
  );
}

Object.assign(window, { XlsClassic, XlsModern, XlsBold });
