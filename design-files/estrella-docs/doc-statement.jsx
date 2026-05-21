/* global React, EJ_SAMPLE, EJLogo, EJBank */

const STMT = {
  no: "STMT-PANAKS-2026-Q2",
  customer: EJ_SAMPLE.buyer,
  period: "2026-04-01 → 2026-05-08",
  opening: 1842.50,
  rows: [
    { d: "2026-04-02", doc: "WDT 41/2026", type: "Invoice",     ref: "PROF 51/2026", debit: 624.20, credit: 0,      due: "2026-04-09", status: "paid" },
    { d: "2026-04-09", doc: "PAY-IN 0418",  type: "Payment",     ref: "SEPA wire",     debit: 0,      credit: 624.20, due: "—",          status: "received" },
    { d: "2026-04-15", doc: "WDT 44/2026", type: "Invoice",     ref: "PROF 56/2026", debit: 899.00, credit: 0,      due: "2026-04-22", status: "paid" },
    { d: "2026-04-22", doc: "PAY-IN 0451",  type: "Payment",     ref: "SEPA wire",     debit: 0,      credit: 899.00, due: "—",          status: "received" },
    { d: "2026-04-28", doc: "WDT 46/2026", type: "Invoice",     ref: "PROF 78/2026", debit: 1240.00,credit: 0,      due: "2026-05-05", status: "overdue" },
    { d: "2026-05-02", doc: "CN 04/2026",  type: "Credit note", ref: "WDT 46/2026",  debit: 0,      credit: 95.00,  due: "—",          status: "applied" },
    { d: "2026-05-08", doc: "PROF 95/2026",type: "Pro forma",   ref: "Open",          debit: 223.40, credit: 0,      due: "2026-05-15", status: "open"    },
  ],
};
const closing = STMT.opening + STMT.rows.reduce((a, r) => a + (r.debit - r.credit), 0);

// ---------------- Aging buckets ----------------
const aging = {
  current: 223.40,
  d1_30:   1145.00,
  d31_60:  0,
  d61_90:  0,
  d90:     0,
};
const totalOpen = Object.values(aging).reduce((a, b) => a + b, 0);

function statusPill(s) {
  const m = {
    paid:     ["ej-pill-green",  "Paid"],
    received: ["ej-pill-green",  "Received"],
    overdue:  ["ej-pill-red",    "Overdue"],
    applied:  ["",               "Applied"],
    open:     ["ej-pill-gold",   "Open"],
  };
  const [cls, lab] = m[s] || ["", s];
  return <span className={`ej-pill ${cls}`}>{lab}</span>;
}

// ============================================================
// STATEMENT — Variant A · CLASSIC
// ============================================================
function StatementClassic() {
  return (
    <div className="a4">
      <div className="ej-band"/>
      <div className="pad" style={{ paddingTop: 28 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <EJLogo size="lg"/>
          <div style={{ textAlign: "right" }}>
            <div className="ej-eyebrow ej-eyebrow-gold">Account Statement · Wyciąg · Výpis</div>
            <div className="ej-h1" style={{ marginTop: 2 }}>Statement of Account</div>
            <div className="ej-mono" style={{ fontSize: 13, color: "#0B3D2E", fontWeight: 600, marginTop: 4 }}>{STMT.no}</div>
          </div>
        </div>

        {/* Customer + period */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 0, border: "1px solid #E2E8F0", borderRadius: 4, marginBottom: 18 }}>
          <div style={{ padding: "12px 14px", borderRight: "1px solid #E2E8F0" }}>
            <div className="ej-eyebrow">Account holder</div>
            <div style={{ fontWeight: 600, marginTop: 3 }}>{STMT.customer.name}</div>
            <div style={{ fontSize: 10, color: "#475569" }}>{STMT.customer.addr}, {STMT.customer.city}, {STMT.customer.country}</div>
            <div style={{ fontSize: 10, color: "#475569" }}>VAT EU · {STMT.customer.vat}</div>
          </div>
          <div style={{ padding: "12px 14px", borderRight: "1px solid #E2E8F0" }}>
            <div className="ej-eyebrow">Period</div>
            <div style={{ fontWeight: 600, marginTop: 3 }}>{STMT.period}</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>Currency · EUR</div>
          </div>
          <div style={{ padding: "12px 14px" }}>
            <div className="ej-eyebrow">Closing balance</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: closing > 0 ? "#B91C1C" : "#16A34A", marginTop: 3 }} className="ej-mono">EUR {closing.toFixed(2)}</div>
            <div style={{ fontSize: 9, color: "#94A3B8" }}>{closing > 0 ? "Outstanding" : "Settled"}</div>
          </div>
        </div>

        {/* Aging */}
        <div style={{ marginBottom: 18 }}>
          <div className="ej-eyebrow" style={{ marginBottom: 6 }}>Aging analysis · open items</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", border: "1px solid #E2E8F0", borderRadius: 4 }}>
            {[
              ["Current", aging.current, "#0B3D2E"],
              ["1–30 d", aging.d1_30, "#C9A24B"],
              ["31–60 d", aging.d31_60, "#B45309"],
              ["61–90 d", aging.d61_90, "#B45309"],
              ["90+ d", aging.d90, "#B91C1C"],
              ["Total open", totalOpen, "#0F172A"],
            ].map(([k, v, c], i) => (
              <div key={k} style={{ padding: "10px 12px", borderRight: i < 5 ? "1px solid #E2E8F0" : "none", background: i === 5 ? "#F8FAFC" : "transparent" }}>
                <div className="ej-eyebrow">{k}</div>
                <div className="ej-mono" style={{ fontWeight: 700, fontSize: 12, color: c, marginTop: 3 }}>{v.toFixed(2)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Ledger table */}
        <table className="ej-table" style={{ marginBottom: 16 }}>
          <thead>
            <tr>
              <th style={{ width: 70 }}>Date</th>
              <th style={{ width: 90 }}>Document</th>
              <th style={{ width: 80 }}>Type</th>
              <th>Reference</th>
              <th style={{ width: 70 }}>Due</th>
              <th className="ej-r" style={{ width: 70 }}>Debit</th>
              <th className="ej-r" style={{ width: 70 }}>Credit</th>
              <th className="ej-r" style={{ width: 80 }}>Balance</th>
              <th style={{ width: 70 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ background: "#F8FAFC" }}>
              <td colSpan="7" style={{ fontWeight: 600 }}>Opening balance</td>
              <td className="ej-r ej-mono" style={{ fontWeight: 700 }}>{STMT.opening.toFixed(2)}</td>
              <td/>
            </tr>
            {(() => {
              let bal = STMT.opening;
              return STMT.rows.map((r) => {
                bal += r.debit - r.credit;
                return (
                  <tr key={r.doc}>
                    <td className="ej-mono">{r.d}</td>
                    <td className="ej-mono" style={{ fontWeight: 600 }}>{r.doc}</td>
                    <td>{r.type}</td>
                    <td style={{ color: "#64748B" }}>{r.ref}</td>
                    <td className="ej-mono">{r.due}</td>
                    <td className="ej-r ej-mono">{r.debit ? r.debit.toFixed(2) : "—"}</td>
                    <td className="ej-r ej-mono" style={{ color: "#16A34A" }}>{r.credit ? r.credit.toFixed(2) : "—"}</td>
                    <td className="ej-r ej-mono" style={{ fontWeight: 600 }}>{bal.toFixed(2)}</td>
                    <td>{statusPill(r.status)}</td>
                  </tr>
                );
              });
            })()}
            <tr style={{ background: "#FBF8F1" }}>
              <td colSpan="7" style={{ fontWeight: 700 }}>Closing balance</td>
              <td className="ej-r ej-mono" style={{ fontWeight: 700, color: "#B91C1C" }}>{closing.toFixed(2)}</td>
              <td/>
            </tr>
          </tbody>
        </table>

        <EJBank/>

        <div style={{ marginTop: 16, padding: 12, background: "#FBF8F1", borderLeft: "3px solid #C9A24B", fontSize: 9.5, color: "#475569", lineHeight: 1.55 }}>
          <strong style={{ color: "#0B3D2E" }}>Reconciliation note:</strong> Please remit the closing balance of <span className="ej-mono" style={{ fontWeight: 600 }}>EUR {closing.toFixed(2)}</span> to the EUR account above, quoting <span className="ej-mono">{STMT.no}</span> in the wire reference. Discrepancies must be reported within 14 days; balances are otherwise accepted as correct under Polish commercial law.
        </div>
      </div>
    </div>
  );
}

// ============================================================
// STATEMENT — Variant B · MODERN  (KPI cards + minimalist ledger)
// ============================================================
function StatementModern() {
  return (
    <div className="a4">
      <div className="pad-tight" style={{ paddingTop: 36 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 28 }}>
          <EJLogo/>
          <div style={{ display: "flex", gap: 6 }}>
            <span className="ej-pill ej-pill-green">STATEMENT</span>
            <span className="ej-pill">EUR</span>
            <span className="ej-pill ej-pill-red">{closing > 0 ? "OUTSTANDING" : "SETTLED"}</span>
          </div>
        </div>

        <div style={{ marginBottom: 22 }}>
          <div className="ej-eyebrow">Account Statement · Wyciąg · Výpis</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
            <div className="ej-h1" style={{ fontSize: 32, color: "#0B3D2E" }}>{STMT.customer.name}</div>
          </div>
          <div style={{ fontSize: 10, color: "#64748B", marginTop: 4 }}>{STMT.no} · {STMT.period}</div>
          <div style={{ height: 2, width: 64, background: "#C9A24B", marginTop: 12 }}/>
        </div>

        {/* KPI cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 22 }}>
          {[
            ["Opening balance", STMT.opening, "#64748B"],
            ["Total invoiced", STMT.rows.reduce((a, r) => a + r.debit, 0), "#0B3D2E"],
            ["Total received", STMT.rows.reduce((a, r) => a + r.credit, 0), "#16A34A"],
            ["Closing balance", closing, "#B91C1C"],
          ].map(([k, v, c]) => (
            <div key={k} style={{ padding: 14, border: "1px solid #E2E8F0", borderRadius: 6 }}>
              <div className="ej-eyebrow">{k}</div>
              <div className="ej-mono" style={{ fontSize: 18, fontWeight: 700, color: c, marginTop: 4 }}>EUR {v.toFixed(2)}</div>
            </div>
          ))}
        </div>

        {/* Aging visual bar */}
        <div style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <div className="ej-eyebrow">Aging · open items · EUR {totalOpen.toFixed(2)}</div>
            <div className="ej-mono" style={{ fontSize: 9, color: "#64748B" }}>{Math.round((aging.current / totalOpen) * 100)}% current · {Math.round((aging.d1_30 / totalOpen) * 100)}% 1–30d</div>
          </div>
          <div style={{ display: "flex", height: 24, borderRadius: 4, overflow: "hidden", border: "1px solid #E2E8F0" }}>
            {[
              [aging.current, "#0B3D2E", "Current"],
              [aging.d1_30,   "#C9A24B", "1–30 d"],
              [aging.d31_60,  "#B45309", "31–60 d"],
              [aging.d61_90,  "#B45309", "61–90 d"],
              [aging.d90,     "#B91C1C", "90+ d"],
            ].filter(([v]) => v > 0).map(([v, c, k]) => (
              <div key={k} style={{ flex: v, background: c, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 600 }}>
                {k}
              </div>
            ))}
          </div>
        </div>

        {/* Ledger */}
        <table className="ej-table" style={{ marginBottom: 22 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              <th style={{ width: 70 }}>Date</th>
              <th style={{ width: 90 }}>Document</th>
              <th>Reference</th>
              <th className="ej-r" style={{ width: 70 }}>Debit</th>
              <th className="ej-r" style={{ width: 70 }}>Credit</th>
              <th className="ej-r" style={{ width: 80 }}>Balance</th>
              <th style={{ width: 70 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              let bal = STMT.opening;
              return STMT.rows.map((r) => {
                bal += r.debit - r.credit;
                return (
                  <tr key={r.doc}>
                    <td className="ej-mono">{r.d}</td>
                    <td className="ej-mono" style={{ fontWeight: 600 }}>{r.doc}</td>
                    <td>
                      <div>{r.type}</div>
                      <div style={{ color: "#94A3B8", fontSize: 9 }}>{r.ref}</div>
                    </td>
                    <td className="ej-r ej-mono">{r.debit ? r.debit.toFixed(2) : "—"}</td>
                    <td className="ej-r ej-mono" style={{ color: "#16A34A" }}>{r.credit ? r.credit.toFixed(2) : "—"}</td>
                    <td className="ej-r ej-mono" style={{ fontWeight: 600 }}>{bal.toFixed(2)}</td>
                    <td>{statusPill(r.status)}</td>
                  </tr>
                );
              });
            })()}
          </tbody>
        </table>

        <EJBank/>
      </div>
      <div style={{ position: "absolute", bottom: 18, left: 40, right: 40, fontSize: 8.5, color: "#94A3B8", display: "flex", justifyContent: "space-between" }}>
        <span>Reconciliation window 14 days · Polish commercial law</span>
        <span>{EJ_SAMPLE.seller.email}</span>
      </div>
    </div>
  );
}

// ============================================================
// STATEMENT — Variant C · BOLD (left rail summary)
// ============================================================
function StatementBold() {
  return (
    <div className="a4" style={{ display: "flex" }}>
      <div className="ej-rail">
        <EJLogo size="md" mono/>
        <div>
          <div style={{ fontSize: 8.5, letterSpacing: "0.18em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600, marginBottom: 6 }}>Statement</div>
          <div style={{ fontSize: 18, fontWeight: 700, lineHeight: 1.15 }}>{STMT.customer.name}</div>
          <div style={{ fontSize: 10, opacity: 0.75, marginTop: 4 }}>VAT EU · {STMT.customer.vat}</div>
        </div>

        <div>
          <div style={{ fontSize: 8.5, letterSpacing: "0.16em", textTransform: "uppercase", opacity: 0.6, fontWeight: 600 }}>Closing balance</div>
          <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1, marginTop: 6, color: "#C9A24B" }}>EUR {closing.toFixed(2)}</div>
          <div style={{ fontSize: 9.5, opacity: 0.75, marginTop: 4 }}>{closing > 0 ? "Due " + STMT.rows.find(r => r.status === "open")?.due : "Account settled"}</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 10 }}>
          <SmallStat k="Period"    v={STMT.period}/>
          <SmallStat k="Opening"   v={"EUR " + STMT.opening.toFixed(2)}/>
          <SmallStat k="Invoiced"  v={"EUR " + STMT.rows.reduce((a,r)=>a+r.debit,0).toFixed(2)}/>
          <SmallStat k="Received"  v={"EUR " + STMT.rows.reduce((a,r)=>a+r.credit,0).toFixed(2)}/>
          <SmallStat k="Open items" v={"EUR " + totalOpen.toFixed(2)}/>
        </div>

        <div style={{ marginTop: "auto", padding: 12, background: "rgba(201,162,75,0.12)", borderRadius: 4, fontSize: 9, lineHeight: 1.5 }}>
          <div style={{ color: "#C9A24B", fontWeight: 600, marginBottom: 4 }}>Quote when paying</div>
          <div className="ej-mono">{STMT.no}</div>
        </div>
      </div>

      <div style={{ flex: 1, padding: "32px 36px", display: "flex", flexDirection: "column" }}>
        <div className="ej-eyebrow" style={{ marginBottom: 6 }}>Aging buckets</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 6, marginBottom: 22 }}>
          {[
            ["Current", aging.current, "#0B3D2E"],
            ["1–30 d", aging.d1_30, "#C9A24B"],
            ["31–60 d", aging.d31_60, "#B45309"],
            ["61–90 d", aging.d61_90, "#B45309"],
            ["90+ d", aging.d90, "#B91C1C"],
          ].map(([k, v, c]) => (
            <div key={k} style={{ padding: 10, borderRadius: 4, background: v > 0 ? c : "#F8FAFC", color: v > 0 ? "#fff" : "#94A3B8" }}>
              <div style={{ fontSize: 8.5, letterSpacing: "0.12em", textTransform: "uppercase", fontWeight: 600, opacity: v > 0 ? 0.85 : 1 }}>{k}</div>
              <div className="ej-mono" style={{ fontSize: 14, fontWeight: 700, marginTop: 4 }}>{v.toFixed(2)}</div>
            </div>
          ))}
        </div>

        <table className="ej-table" style={{ marginBottom: 18 }}>
          <thead>
            <tr>
              <th style={{ width: 70 }}>Date</th>
              <th style={{ width: 90 }}>Document</th>
              <th>Type · Ref</th>
              <th className="ej-r" style={{ width: 70 }}>Debit</th>
              <th className="ej-r" style={{ width: 70 }}>Credit</th>
              <th className="ej-r" style={{ width: 80 }}>Balance</th>
              <th style={{ width: 70 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              let bal = STMT.opening;
              return STMT.rows.map((r) => {
                bal += r.debit - r.credit;
                return (
                  <tr key={r.doc}>
                    <td className="ej-mono">{r.d}</td>
                    <td className="ej-mono" style={{ fontWeight: 600 }}>{r.doc}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{r.type}</div>
                      <div style={{ color: "#94A3B8", fontSize: 9 }}>{r.ref}</div>
                    </td>
                    <td className="ej-r ej-mono">{r.debit ? r.debit.toFixed(2) : "—"}</td>
                    <td className="ej-r ej-mono" style={{ color: "#16A34A" }}>{r.credit ? r.credit.toFixed(2) : "—"}</td>
                    <td className="ej-r ej-mono" style={{ fontWeight: 600 }}>{bal.toFixed(2)}</td>
                    <td>{statusPill(r.status)}</td>
                  </tr>
                );
              });
            })()}
          </tbody>
        </table>

        <div style={{ marginTop: "auto" }}><EJBank/></div>
      </div>
    </div>
  );
}

function SmallStat({ k, v }) {
  return (
    <div>
      <div style={{ fontSize: 8.5, letterSpacing: "0.14em", textTransform: "uppercase", opacity: 0.6, fontWeight: 600 }}>{k}</div>
      <div style={{ fontSize: 11, fontWeight: 600, marginTop: 1 }}>{v}</div>
    </div>
  );
}

Object.assign(window, { StatementClassic, StatementModern, StatementBold });
