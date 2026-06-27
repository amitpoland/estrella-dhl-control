/* global React */
// estrella-doc-proforma.jsx — Estrella Document Suite: Pro Forma print variants
// Adapted from design-canvas prototype (2026-06-06) for real draft data.
//
// docData shape (supplied by ProformaDetailPage):
//   .doc_no            string            proforma number / label
//   .date              string            issue date (ISO or formatted)
//   .due               string|null       payment due date (used by EJTermsBlock for dynamic sentence)
//   .payment           string            human-readable payment terms display string
//   .payment_terms_days number|0         explicit payment window in days — primary authority for EJTermsBlock
//   .currency          string            draft currency code (e.g. "USD"); labels use this, not a hardcoded EUR
//   .rate              { eur: number, currency: string, date: string, table: string }  (eur = the PLN rate, mislabelled for legacy)
//   .charges[]         { type, label, amount: number|null, currency, present }  freight / insurance (present=false → "not set")
//   .seller            { name, addr, city, vat, email, phone, web }
//   .buyer             { name, addr, city, country, vat }
//   .ship_to           { name, addr, city, country } | null   recipient when ship_to_override set
//   .lines[]           { seq, sku, desc, purity, origin, qty, unitEur, netEur }  (unitEur/netEur named for legacy; carry the DRAFT-currency amount)
//   .total_eur         number            goods subtotal in the draft currency (legacy name)
//   .total_pln         number|null
//   .carrier           { awb, incoterm } | null   optional
//   .banks[]           { cur, iban, swift, bank }  — adapted from flat iban_eur/usd/pln by proforma-detail.jsx
//
// Depends on: estrella-doc-tokens.css (loaded in index.html)
// Exports: window.EJProformaClassic, window.EJProformaModern

// ── Logo — single authority ───────────────────────────────────────────────────
// Set ESTRELLA_DOCUMENT_LOGO_SRC to a real file path once the logo asset is
// provided (e.g. "/static/assets/estrella-logo.png"). Until then the SVG mark
// fallback is used.  All six document components (Classic, Modern, Bold, CMR,
// Packing) import EJDocumentLogo from this file — do NOT copy the SVG inline.
const ESTRELLA_DOCUMENT_LOGO_SRC = "/v2/assets/estrella-logo.png";

function EJDocMark({ size = 36, mono = false }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      <circle cx="18" cy="18" r="16.5"
        fill={mono ? "transparent" : "#0B3D2E"}
        stroke={mono ? "rgba(255,255,255,0.4)" : "none"}
        strokeWidth="1"
      />
      <path d="M18 7 L27 18 L18 29 L9 18 Z"
        fill="none" stroke="#C9A24B" strokeWidth="1.5"
      />
      <path d="M18 12.5 L23.5 18 L18 23.5 L12.5 18 Z"
        fill="#C9A24B"
      />
    </svg>
  );
}

// EJDocumentLogo — THE single logo component used by all V2 document variants.
// Image-first: renders <img> when ESTRELLA_DOCUMENT_LOGO_SRC is set.
// SVG fallback: renders inline mark + wordmark until real logo file is provided.
function EJDocumentLogo({ size = "md", mono = false, className = "" }) {
  const h = size === "lg" ? 48 : size === "sm" ? 26 : 36;
  if (ESTRELLA_DOCUMENT_LOGO_SRC) {
    return (
      <img
        className={"ej-document-logo" + (className ? " " + className : "")}
        src={ESTRELLA_DOCUMENT_LOGO_SRC}
        alt="Estrella Jewels"
        style={{ maxWidth: 180, maxHeight: h, objectFit: "contain", display: "block" }}
      />
    );
  }
  return (
    <div className={"ej-logo" + (className ? " " + className : "")}>
      <EJDocMark size={h} mono={mono}/>
      <div className="ej-logo-text">
        <span className="ej-logo-name" style={mono ? { color: "#fff" } : {}}>
          ESTRELLA JEWELS
        </span>
      </div>
    </div>
  );
}
// Backward-compat alias (internal use within this file only)
const EJDocLogo = EJDocumentLogo;

// ── Address card ─────────────────────────────────────────────────────────────
function EJDocAddress({ label, party }) {
  if (!party) return null;
  return (
    <div className="ej-addr">
      <div className="ej-addr-label">{label}</div>
      <div className="ej-addr-name">{party.name || "—"}</div>
      {party.addr    && <div>{party.addr}</div>}
      {party.city    && <div>{party.city}{party.country ? `, ${party.country}` : ""}</div>}
      {!party.city && party.country && <div>{party.country}</div>}
      {party.vat     && (
        <div style={{ marginTop: 4, color: "#475569" }}>VAT EU · {party.vat}</div>
      )}
    </div>
  );
}

// ── Bank block ───────────────────────────────────────────────────────────────
// IBAN print convention: 4-character groups ("PL61 1090 1014 ...")
function _formatIban(iban) {
  const raw = String(iban || "").replace(/\s+/g, "");
  if (!raw || raw === "—") return "—";
  return raw.replace(/(.{4})/g, "$1 ").trim();
}

function EJDocBank({ banks }) {
  if (!banks || banks.length === 0) {
    return (
      <div className="ej-bank">
        <div className="ej-eyebrow" style={{ marginBottom: 4 }}>
          Bank details · Dane bankowe
        </div>
        <div style={{ color: "#94A3B8", fontSize: 10 }}>
          Bank details available on the final invoice.
        </div>
      </div>
    );
  }
  return (
    <div className="ej-bank">
      <div className="ej-eyebrow" style={{ marginBottom: 6 }}>
        Bank details · Dane bankowe
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {banks.map((b, i) => (
          <div key={b.iban || `${b.cur}-${i}`} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10 }}>
            <span className="ej-bank-cur">{b.cur}</span>
            <span className="ej-mono" style={{ fontWeight: 600 }}>{_formatIban(b.iban)}</span>
            {b.swift && <span style={{ color: "#64748B" }}>· SWIFT {b.swift}</span>}
            {b.bank  && <span style={{ color: "#64748B" }}>· {b.bank}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Compliance footer — Privacy / GDPR only ───────────────────────────────────
// Payment terms are handled by EJTermsBlock (single authority).
// Returns & Warranty removed — not applicable to B2B trade documents.
function EJDocCompliance() {
  return (
    <div style={{ fontSize: 9, color: "#475569", lineHeight: 1.55, marginTop: 10 }}>
      <div style={{ fontSize: 8.5, letterSpacing: "0.14em", textTransform: "uppercase",
        fontWeight: 600, color: "#64748B", marginBottom: 4 }}>Privacy · GDPR</div>
      Data controller: Estrella Jewels Sp. z o.o., Sp. K. Personal data processed
      solely for contract performance under GDPR Art. 6(1)(b)(c). Data will not be
      shared with third parties beyond what is required for customs and shipping compliance.
    </div>
  );
}

// ── Carrier info row ─────────────────────────────────────────────────────────
function EJDocCarrierRow({ carrier }) {
  if (!carrier) return null;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "auto 1fr 1fr",
      gap: 0, border: "1px solid var(--ej-line)", borderRadius: "var(--ej-radius)",
      background: "var(--ej-paper)", overflow: "hidden", marginBottom: 16,
    }}>
      <div style={{ background: "#0B3D2E", color: "#fff", padding: "10px 14px", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          background: "#FFCC00", color: "#D40511", fontWeight: 900, fontSize: 11,
          padding: "2px 6px", borderRadius: 3,
        }}>DHL</span>
        <div style={{ fontSize: 8.5, lineHeight: 1.2 }}>
          <div style={{ fontWeight: 700 }}>EXPRESS</div>
          {carrier.awb
            ? <div style={{ opacity: 0.75 }}>AWB {carrier.awb}</div>
            : <div style={{ opacity: 0.55, fontStyle: "italic" }}>AWB pending</div>
          }
        </div>
      </div>
      <div style={{ padding: "10px 12px", borderRight: "1px solid var(--ej-line)" }}>
        <div style={{ fontSize: 8, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--ej-mute)", fontWeight: 600, marginBottom: 3 }}>Incoterm</div>
        <div style={{ fontSize: 11, fontWeight: 600 }}>{carrier.incoterm || "DAP"}</div>
      </div>
      <div style={{ padding: "10px 12px" }}>
        <div style={{ fontSize: 8, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--ej-mute)", fontWeight: 600, marginBottom: 3 }}>Shipment ref</div>
        <div style={{ fontSize: 11, fontWeight: 600, fontFamily: "var(--ej-mono)" }}>
          {carrier.awb || (carrier.batch_ref ? `Batch: ${carrier.batch_ref}` : "—")}
        </div>
      </div>
    </div>
  );
}

// ── Diamond Declaration (Kimberley Process + WDC + WFDB) ─────────────────────
function EJDiamondDecl() {
  return (
    <div className="ej-diamond-decl" style={{ fontSize: 9, color: "#334155", lineHeight: 1.55, marginTop: 14,
      padding: "10px 12px", background: "#FBF8F1", borderLeft: "3px solid #C9A24B",
      borderRadius: 2, pageBreakInside: "avoid", breakInside: "avoid" }}>
      <div style={{ fontSize: 8.5, letterSpacing: "0.14em", textTransform: "uppercase",
        fontWeight: 600, color: "#B0892F", marginBottom: 5 }}>
        Diamond Declaration · Deklaracja diamentowa
      </div>
      <p style={{ margin: "0 0 5px" }}>
        (1) The diamonds herein invoiced have been purchased from legitimate sources not involved in funding
        conflict, in compliance with United Nations Resolutions and the Kimberley Process Certification Scheme
        (KPCS) and corresponding national laws. The seller hereby guarantees that these diamonds are conflict
        free and confirm adherence to the WDC SoW Guidelines.
      </p>
      <p style={{ margin: "0 0 5px" }}>
        (2) The diamonds herein invoiced are exclusively of natural origin and untreated based on personal
        knowledge and/or written guarantees provided by the suppliers of these diamonds. The acceptance of
        goods herein invoiced will be as per The WFDB guidelines.
      </p>
      <p style={{ margin: 0 }}>We declare that diamonds invoiced is not from Russian origin.</p>
    </div>
  );
}

// ── Payment and Ownership Terms ───────────────────────────────────────────────
// paymentDays: liveDraft.payment_terms_days (integer, may be 0/null)
// dueDate:     liveDraft due-date string (ISO or "—") — computed from wFirma or invoice_date + days
// issueDate:   liveDraft.invoice_date / created_at string — only used when both present to compute days
function EJTermsBlock({ paymentDays, dueDate, issueDate }) {
  let paymentSentence;
  const days = Number(paymentDays) || 0;
  const hasDue = dueDate && dueDate !== "—";

  if (days > 0) {
    // Authoritative: explicit payment_terms_days from draft
    paymentSentence = `Payment received within ${days} days from Invoice Date.`;
  } else if (hasDue && issueDate && issueDate !== "—") {
    // Derive days from issue → due gap (ISO dates, UTC arithmetic)
    const msPerDay = 86400000;
    const iso = (s) => String(s || "").slice(0, 10);
    const diff = Math.round(
      (Date.parse(iso(dueDate) + "T00:00:00Z") - Date.parse(iso(issueDate) + "T00:00:00Z")) / msPerDay
    );
    if (!isNaN(diff) && diff > 0) {
      paymentSentence = `Payment received within ${diff} days from Invoice Date.`;
    } else {
      paymentSentence = `Payment due by ${dueDate}.`;
    }
  } else {
    // Fallback — no payment_terms_days and no computable due date
    if (typeof console !== "undefined") {
      console.warn("[EJTermsBlock] No payment_terms_days or due date — falling back to 30-day default.");
    }
    paymentSentence = "Payment received within 30 days from Invoice Date.";
  }

  return (
    <div className="ej-terms" style={{ fontSize: 9, color: "#475569", lineHeight: 1.55, marginTop: 10,
      pageBreakInside: "avoid", breakInside: "avoid" }}>
      <div style={{ fontSize: 8.5, letterSpacing: "0.14em", textTransform: "uppercase",
        fontWeight: 600, color: "#64748B", marginBottom: 4 }}>
        Warunki płatności / Payment and Ownership Terms
      </div>
      {paymentSentence}{" "}Ownership of goods remains with the seller until full
      payment is received. This transaction is governed by the laws of Poland and recognized under applicable
      EU and international trade conventions.
    </div>
  );
}

// ── Signature Block — bilingual PL/EN, two-column ─────────────────────────────
function EJSignatureBlock({ documentType }) {
  const noun = documentType === "invoice" ? "faktury" : "pro formy";
  return (
    <div className="ej-sig-block" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginTop: 24,
      pageBreakInside: "avoid", breakInside: "avoid" }}>
      <div>
        <div style={{ borderTop: "1px solid #CBD5E1", height: 36, marginBottom: 6 }}/>
        <div style={{ fontSize: 9, color: "#334155" }}>Imię i nazwisko osoby uprawnionej</div>
        <div style={{ fontSize: 9, color: "#334155" }}>do wystawiania {noun}</div>
        <em style={{ fontSize: 8.5, color: "#64748B" }}>seller's signature</em>
      </div>
      <div>
        <div style={{ borderTop: "1px solid #CBD5E1", height: 36, marginBottom: 6 }}/>
        <div style={{ fontSize: 9, color: "#334155" }}>Imię i nazwisko osoby uprawnionej</div>
        <div style={{ fontSize: 9, color: "#334155" }}>do odbioru {noun}</div>
        <em style={{ fontSize: 8.5, color: "#64748B" }}>buyer's signature</em>
      </div>
    </div>
  );
}

// ── Official Company Footer ────────────────────────────────────────────────────
function EJCompanyFooter() {
  return (
    <div className="ej-company-footer" style={{ marginTop: 14, borderTop: "1px solid #E2E8F0", paddingTop: 8,
      fontSize: 8.5, color: "#94A3B8", lineHeight: 1.5,
      pageBreakInside: "avoid", breakInside: "avoid" }}>
      <strong style={{ color: "#64748B" }}>Estrella Jewels Sp. z o.o., Sp. K.</strong>
      {" · "}Siedziba: Ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa, Polska
      {" · "}Sprzedaż: Ul. Sabały 58, 02-174 Warszawa, Polska
      {" · "}info@estrellajewels.eu · www.estrellajewels.eu · tel.: 0048 22 2583398
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VARIANT A — CLASSIC
// Tall masthead, green/gold band header, formal party blocks, full table
// ═══════════════════════════════════════════════════════════════════════════════
function EJProformaClassic({ docData }) {
  const d = docData || {};
  const lines = d.lines || [];
  const cur = d.currency || "EUR";                       // draft currency, not hardcoded EUR
  const charges = d.charges || [];                        // freight / insurance (value or "not set")
  const chargesPresent = charges.filter(c => c && c.present);
  const totalEur = typeof d.total_eur === "number" ? d.total_eur : lines.reduce((s, l) => s + (l.netEur || 0), 0);
  // Only fold SAME-currency charges into the grand total — a charge in another
  // currency (e.g. PLN freight on a USD draft) is shown in its own currency and
  // NOT summed, so the printed total is never a cross-currency misstatement.
  const grandTotal = totalEur + chargesPresent
    .filter(c => (c.currency || cur) === cur)
    .reduce((s, c) => s + (Number(c.amount) || 0), 0);
  const totalPln = typeof d.total_pln === "number" ? d.total_pln : null;

  return (
    <div className="ej-a4">
      <div className="ej-pattern"/>
      <div className="ej-band"/>
      <div className="ej-pad" style={{ paddingTop: 28 }}>

        {/* Masthead */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <EJDocLogo size="lg"/>
          <div style={{ textAlign: "right" }}>
            <div className="ej-eyebrow ej-eyebrow-gold">Pro Forma · Faktura proforma</div>
            <div className="ej-h1" style={{ marginTop: 2 }}>Faktura proforma</div>
            <div className="ej-mono" style={{ fontSize: 14, color: "#0B3D2E", fontWeight: 600, marginTop: 4 }}>
              {d.doc_no || "—"}
            </div>
          </div>
        </div>

        {/* Meta strip */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0,
          border: "1px solid #E2E8F0", borderRadius: 4, marginBottom: 18,
        }}>
          {[
            ["Issued",        d.date    || "—"],
            ["Payment due",   d.due     || "—"],
            ["Payment terms", d.payment || "—"],
            ["FX · NBP",   d.rate && d.rate.eur
              ? `1 ${cur} = ${Number(d.rate.eur).toFixed(4)} PLN · ${d.rate.date || ""}`
              : "—"],
          ].map(([k, v], i) => (
            <div key={k} style={{ padding: "10px 12px", borderRight: i < 3 ? "1px solid #E2E8F0" : "none" }}>
              <div className="ej-eyebrow">{k}</div>
              <div style={{ marginTop: 2, fontWeight: 600, fontSize: 10 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Party row — ship_to authority: ship_to_override when set, buyer otherwise */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 16 }}>
          <EJDocAddress label="Sprzedawca · Seller" party={d.seller}/>
          <EJDocAddress label="Nabywca · Bill to"  party={d.buyer}/>
          <EJDocAddress label="Odbiorca · Ship to" party={d.ship_to || d.buyer}/>
        </div>

        {/* Carrier row (if AWB known) */}
        {d.carrier && <EJDocCarrierRow carrier={d.carrier}/>}

        {/* Lines */}
        <table className="ej-table" style={{ marginBottom: 12 }}>
          <thead>
            <tr>
              <th style={{ width: 22 }}>#</th>
              <th>Description · Nazwa</th>
              <th style={{ width: 80 }}>SKU / Code</th>
              <th style={{ width: 48 }}>Origin</th>
              <th className="ej-r" style={{ width: 36 }}>Qty</th>
              <th className="ej-r" style={{ width: 72 }}>Unit · {cur}</th>
              <th className="ej-c" style={{ width: 44 }}>Tax</th>
              <th className="ej-r" style={{ width: 80 }}>Net · {cur}</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={8} style={{ color: "#94A3B8", padding: "16px 10px" }}>
                  No line items
                </td>
              </tr>
            )}
            {lines.map((l, i) => (
              <tr key={l.sku || i}>
                <td style={{ color: "#94A3B8" }}>{i + 1}</td>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc_en || l.desc || l.sku || "—"}</div>
                  {l.desc_pl && l.desc_pl !== (l.desc_en || l.desc) && (
                    <div style={{ fontSize: 9, color: "#64748B", marginTop: 1 }}>{l.desc_pl}</div>
                  )}
                  {l.purity && l.purity !== "Service" && (
                    <div style={{ marginTop: 3 }}>
                      <span className="ej-pill ej-pill-gold">{l.purity}</span>
                    </div>
                  )}
                </td>
                <td className="ej-mono" style={{ fontSize: 9.5 }}>{l.sku || "—"}</td>
                <td>{l.origin || "—"}</td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{Number(l.unitEur || 0).toFixed(2)}</td>
                <td className="ej-c">0% WDT</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{Number(l.netEur || 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Totals */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 18 }}>
          <div style={{ width: 320, border: "1px solid #E2E8F0", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderBottom: "1px solid #E2E8F0", fontSize: 10 }}>
              <span>Subtotal (goods) · {cur}</span>
              <span className="ej-mono">{totalEur.toFixed(2)}</span>
            </div>
            {charges.map(c => (
              <div key={c.type} data-ej-charge={c.type} style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderBottom: "1px solid #E2E8F0", fontSize: 10 }}>
                <span>{c.label}</span>
                <span className="ej-mono" style={{ color: c.present ? undefined : "#94A3B8" }}>
                  {c.present ? `${c.currency || cur} ${Number(c.amount).toFixed(2)}` : "— not set"}
                </span>
              </div>
            ))}
            <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderBottom: "1px solid #E2E8F0", fontSize: 10 }}>
              <span>VAT (0% WDT)</span>
              <span className="ej-mono">0.00</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 12px", background: "#0B3D2E", color: "#fff", fontSize: 12, fontWeight: 700 }}>
              <span>{grandTotal > totalEur ? "Total incl. freight & insurance" : "Total due"}</span>
              <span className="ej-mono">{cur} {grandTotal.toFixed(2)}</span>
            </div>
            {totalPln !== null && (
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 12px", background: "#FBF8F1", fontSize: 9, color: "#B0892F" }}>
                <span>= PLN reference</span>
                <span className="ej-mono">{totalPln.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>

        {/* Bank */}
        <div style={{ marginBottom: 14 }}>
          <EJDocBank banks={d.banks || []}/>
        </div>

        <div className="ej-final-stack">
          <EJTermsBlock paymentDays={d.payment_terms_days} dueDate={d.due} issueDate={d.date}/>
          <EJDiamondDecl/>
          <EJDocCompliance/>
          <div className="ej-signature-footer-lock">
            <EJSignatureBlock documentType="proforma"/>
            <EJCompanyFooter/>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VARIANT B — MODERN
// Large doc number hero, KPI totals band, compact party layout
// ═══════════════════════════════════════════════════════════════════════════════
function EJProformaModern({ docData }) {
  const d = docData || {};
  const lines = d.lines || [];
  const cur = d.currency || "EUR";
  const charges = d.charges || [];
  const chargesPresent = charges.filter(c => c && c.present);
  const totalEur = typeof d.total_eur === "number" ? d.total_eur : lines.reduce((s, l) => s + (l.netEur || 0), 0);
  // Same-currency charges only (cross-currency charges are shown, not summed).
  const grandTotal = totalEur + chargesPresent
    .filter(c => (c.currency || cur) === cur)
    .reduce((s, c) => s + (Number(c.amount) || 0), 0);
  const totalPln = typeof d.total_pln === "number" ? d.total_pln : null;

  return (
    <div className="ej-a4">
      <div className="ej-pad-tight" style={{ paddingTop: 36 }}>

        {/* Top bar */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 36 }}>
          <EJDocLogo size="md"/>
          <div style={{ display: "flex", gap: 6 }}>
            <span className="ej-pill ej-pill-green">PRO FORMA</span>
            <span className="ej-pill">{cur}</span>
            <span className="ej-pill">WDT 0%</span>
          </div>
        </div>

        {/* Hero doc number */}
        <div style={{ marginBottom: 28 }}>
          <div className="ej-eyebrow" style={{ marginBottom: 6 }}>
            Pro Forma · Faktura proforma
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
            <div className="ej-h1" style={{ fontSize: 36, color: "#0B3D2E" }}>{d.doc_no || "—"}</div>
            <div style={{ fontSize: 11, color: "#64748B" }}>
              Issued {d.date || "—"} · Due {d.due || "—"}
            </div>
          </div>
          <div style={{ height: 2, width: 64, background: "#C9A24B", marginTop: 14 }}/>
        </div>

        {/* Party columns — third column appears only when ship_to_override is set */}
        <div style={{ display: "grid", gridTemplateColumns: d.ship_to ? "1fr 1fr 1fr" : "1fr 1fr", gap: 24, marginBottom: 28 }}>
          <div>
            <div className="ej-eyebrow" style={{ marginBottom: 6 }}>From · Sprzedawca</div>
            {d.seller ? (
              <>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{d.seller.name || "—"}</div>
                {d.seller.addr && <div style={{ color: "#475569", fontSize: 10 }}>{d.seller.addr}</div>}
                {d.seller.city && <div style={{ color: "#475569", fontSize: 10 }}>{d.seller.city}</div>}
                {d.seller.vat  && <div style={{ color: "#475569", fontSize: 10, marginTop: 4 }}>VAT EU · {d.seller.vat}</div>}
              </>
            ) : <div style={{ color: "#94A3B8", fontSize: 10 }}>—</div>}
          </div>
          <div>
            <div className="ej-eyebrow" style={{ marginBottom: 6 }}>For · Nabywca</div>
            {d.buyer ? (
              <>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{d.buyer.name || "—"}</div>
                {d.buyer.addr    && <div style={{ color: "#475569", fontSize: 10 }}>{d.buyer.addr}</div>}
                {d.buyer.city    && <div style={{ color: "#475569", fontSize: 10 }}>{d.buyer.city}</div>}
                {d.buyer.country && <div style={{ color: "#475569", fontSize: 10 }}>{d.buyer.country}</div>}
                {d.buyer.vat     && <div style={{ color: "#475569", fontSize: 10, marginTop: 4 }}>VAT EU · {d.buyer.vat}</div>}
              </>
            ) : <div style={{ color: "#94A3B8", fontSize: 10 }}>—</div>}
          </div>
          {d.ship_to && (
            <div>
              <div className="ej-eyebrow" style={{ marginBottom: 6 }}>Ship to · Odbiorca</div>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>{d.ship_to.name || "—"}</div>
              {d.ship_to.addr    && <div style={{ color: "#475569", fontSize: 10 }}>{d.ship_to.addr}</div>}
              {d.ship_to.city    && <div style={{ color: "#475569", fontSize: 10 }}>{d.ship_to.city}</div>}
              {d.ship_to.country && <div style={{ color: "#475569", fontSize: 10 }}>{d.ship_to.country}</div>}
            </div>
          )}
        </div>

        {/* Carrier */}
        {d.carrier && <EJDocCarrierRow carrier={d.carrier}/>}

        {/* Lines */}
        <table className="ej-table" style={{ marginBottom: 18 }}>
          <thead>
            <tr style={{ borderTop: "2px solid #0B3D2E" }}>
              <th>Item · Description</th>
              <th style={{ width: 80 }}>SKU / Code</th>
              <th style={{ width: 48 }}>Origin</th>
              <th className="ej-r" style={{ width: 36 }}>Qty</th>
              <th className="ej-r" style={{ width: 70 }}>Unit {cur}</th>
              <th className="ej-r" style={{ width: 80 }}>Net {cur}</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={6} style={{ color: "#94A3B8", padding: "16px 10px" }}>No line items</td>
              </tr>
            )}
            {lines.map((l, i) => (
              <tr key={l.sku || i}>
                <td>
                  <div style={{ fontWeight: 600 }}>{l.desc_en || l.desc || l.sku || "—"}</div>
                  {l.desc_pl && l.desc_pl !== (l.desc_en || l.desc) && (
                    <div style={{ fontSize: 9, color: "#64748B", marginTop: 1 }}>{l.desc_pl}</div>
                  )}
                  {l.purity && l.purity !== "Service" && (
                    <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.purity}</div>
                  )}
                </td>
                <td className="ej-mono" style={{ fontSize: 9.5 }}>{l.sku || "—"}</td>
                <td>{l.origin || "—"}</td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{Number(l.unitEur || 0).toFixed(2)}</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{Number(l.netEur || 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* KPI totals band */}
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr",
          borderTop: "1px solid #E2E8F0", borderBottom: "1px solid #E2E8F0", marginBottom: 24,
        }}>
          {[
            ["Items",      lines.length,               false],
            ["Subtotal",   `${cur} ${totalEur.toFixed(2)}`,false],
            ["VAT",        "0% WDT · 0.00",             false],
            [grandTotal > totalEur ? "Total incl. charges" : "Total due", `${cur} ${grandTotal.toFixed(2)}`, true],
          ].map(([k, v, hi], i) => (
            <div key={k} style={{
              padding: "12px 14px",
              borderRight: i < 3 ? "1px solid #E2E8F0" : "none",
              background: hi ? "#0B3D2E" : "transparent",
              color: hi ? "#fff" : undefined,
            }}>
              <div className="ej-eyebrow" style={{ color: hi ? "rgba(255,255,255,0.7)" : undefined }}>{k}</div>
              <div className="ej-mono" style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Freight / insurance — explicit value or "not set" (never silently absent) */}
        <div data-ej-charges="1" style={{ display: "flex", gap: 18, fontSize: 9.5, color: "#475569", marginBottom: 10 }}>
          {charges.map(c => (
            <span key={c.type} data-ej-charge={c.type}>
              {c.label}: <span className="ej-mono" style={{ color: c.present ? "#0B3D2E" : "#94A3B8", fontWeight: 600 }}>
                {c.present ? `${c.currency || cur} ${Number(c.amount).toFixed(2)}` : "— not set"}</span>
            </span>
          ))}
        </div>

        {/* PLN reference */}
        {totalPln !== null && (
          <div style={{ fontSize: 9, color: "#B0892F", marginBottom: 12 }}>
            PLN reference: {totalPln.toFixed(2)} · NBP {d.rate && d.rate.table ? d.rate.table : ""}
          </div>
        )}

        {/* Bank */}
        <div style={{ marginBottom: 18 }}>
          <EJDocBank banks={d.banks || []}/>
        </div>

        <div className="ej-final-stack">
          <EJTermsBlock paymentDays={d.payment_terms_days} dueDate={d.due} issueDate={d.date}/>
          <EJDiamondDecl/>
          <EJDocCompliance/>
          <div className="ej-signature-footer-lock">
            <EJSignatureBlock documentType="proforma"/>
            <EJCompanyFooter/>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VARIANT C — BOLD
// Full-bleed emerald left rail · gold accent · oversized total · compact body
// ═══════════════════════════════════════════════════════════════════════════════
function EJProformaBold({ docData }) {
  const d = docData || {};
  const lines = d.lines || [];
  const cur = d.currency || "EUR";
  const charges = d.charges || [];
  const chargesPresent = charges.filter(c => c && c.present);
  const totalEur = typeof d.total_eur === "number" ? d.total_eur : lines.reduce((s, l) => s + (l.netEur || 0), 0);
  // Same-currency charges only (cross-currency charges are shown, not summed).
  const grandTotal = totalEur + chargesPresent
    .filter(c => (c.currency || cur) === cur)
    .reduce((s, c) => s + (Number(c.amount) || 0), 0);
  const totalPln = typeof d.total_pln === "number" ? d.total_pln : null;

  return (
    <div className="ej-a4" style={{ display: "flex" }}>
      {/* Left rail */}
      <div className="ej-rail">
        <EJDocLogo size="md" mono/>
        <div>
          <div style={{ fontSize: 8.5, letterSpacing: "0.18em", textTransform: "uppercase", color: "#C9A24B", fontWeight: 600, marginBottom: 6 }}>
            Pro Forma
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>{d.doc_no || "—"}</div>
          <div style={{ fontSize: 10, opacity: 0.75, marginTop: 4 }}>Faktura proforma</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[
            ["Issued",        d.date    || "—"],
            ["Payment due",   d.due     || "—"],
            ["Payment terms", d.payment || "—"],
            ["FX · NBP",     d.rate && d.rate.eur ? `1 ${cur} = ${Number(d.rate.eur).toFixed(4)} PLN` : "—"],
          ].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 8.5, letterSpacing: "0.16em", textTransform: "uppercase", opacity: 0.6, fontWeight: 600 }}>{k}</div>
              <div style={{ fontSize: 11, fontWeight: 600, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: "auto", fontSize: 9, opacity: 0.75, lineHeight: 1.5 }}>
          <div style={{ color: "#C9A24B", fontWeight: 600, marginBottom: 4 }}>Estrella Jewels</div>
          {d.seller && d.seller.addr && <div>{d.seller.addr}</div>}
          {d.seller && d.seller.city && <div>{d.seller.city}</div>}
          {d.seller && d.seller.email && <div>{d.seller.email}</div>}
          {d.seller && d.seller.phone && <div>{d.seller.phone}</div>}
        </div>
      </div>

      {/* Right body */}
      <div style={{ flex: 1, padding: "32px 36px", overflow: "hidden", display: "flex", flexDirection: "column" }}>

        {/* Parties — ship_to authority: ship_to_override when set, buyer otherwise */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
          <EJDocAddress label="Bill to · Nabywca"  party={d.buyer}/>
          <EJDocAddress label="Ship to · Odbiorca" party={d.ship_to || d.buyer}/>
        </div>

        {/* Carrier */}
        {d.carrier && <EJDocCarrierRow carrier={d.carrier}/>}

        {/* Lines */}
        <table className="ej-table" style={{ marginBottom: 16 }}>
          <thead>
            <tr>
              <th>Description · Nazwa</th>
              <th style={{ width: 70 }}>SKU</th>
              <th style={{ width: 44 }}>Origin</th>
              <th className="ej-r" style={{ width: 32 }}>Qty</th>
              <th className="ej-r" style={{ width: 64 }}>Unit {cur}</th>
              <th className="ej-r" style={{ width: 70 }}>Net {cur}</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={6} style={{ color: "#94A3B8", padding: "14px 10px" }}>No line items</td>
              </tr>
            )}
            {lines.map((l, i) => (
              <tr key={l.sku || i}>
                <td>
                  <div style={{ fontWeight: 600, fontSize: 10 }}>{l.desc_en || l.desc || l.sku || "—"}</div>
                  {l.desc_pl && l.desc_pl !== (l.desc_en || l.desc) && (
                    <div style={{ fontSize: 9, color: "#64748B", marginTop: 1 }}>{l.desc_pl}</div>
                  )}
                  {l.purity && l.purity !== "Service" && (
                    <div style={{ color: "#94A3B8", fontSize: 9 }}>{l.purity}</div>
                  )}
                </td>
                <td className="ej-mono" style={{ fontSize: 9 }}>{l.sku || "—"}</td>
                <td>{l.origin || "—"}</td>
                <td className="ej-r ej-num">{l.qty}</td>
                <td className="ej-r ej-num">{Number(l.unitEur || 0).toFixed(2)}</td>
                <td className="ej-r ej-num" style={{ fontWeight: 600 }}>{Number(l.netEur || 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Big total block */}
        <div style={{ marginBottom: 18, padding: 16, background: "#FBF8F1", borderLeft: "4px solid #C9A24B", borderRadius: 4 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
            <div>
              <div className="ej-eyebrow ej-eyebrow-gold">{grandTotal > totalEur ? "Total incl. freight & insurance · WDT 0% intra-EU" : "Total due · WDT 0% intra-EU"}</div>
              <div style={{ fontSize: 32, fontWeight: 700, color: "#0B3D2E", lineHeight: 1, marginTop: 4 }}>
                {cur} {grandTotal.toFixed(2)}
              </div>
              <div data-ej-charges="1" style={{ fontSize: 9.5, color: "#475569", marginTop: 4, display: "flex", gap: 14 }}>
                <span>Goods {cur} {totalEur.toFixed(2)}</span>
                {charges.map(c => (
                  <span key={c.type} data-ej-charge={c.type}>
                    {c.label} {c.present
                      ? <span className="ej-mono" style={{ color: "#0B3D2E", fontWeight: 600 }}>{c.currency || cur} {Number(c.amount).toFixed(2)}</span>
                      : <span style={{ color: "#94A3B8" }}>— not set</span>}
                  </span>
                ))}
              </div>
              {totalPln !== null && (
                <div style={{ fontSize: 10, color: "#B0892F", marginTop: 2 }}>
                  ≈ PLN {totalPln.toFixed(2)}
                  {d.rate && d.rate.date ? ` · NBP ${d.rate.date}` : ""}
                </div>
              )}
            </div>
            <span className="ej-pill ej-pill-gold" style={{ fontSize: 10 }}>Due {d.due || "—"}</span>
          </div>
        </div>

        <EJDocBank banks={d.banks || []}/>
        <div className="ej-final-stack" style={{ marginTop: 16 }}>
          <EJTermsBlock paymentDays={d.payment_terms_days} dueDate={d.due} issueDate={d.date}/>
          <EJDiamondDecl/>
          <EJDocCompliance/>
          <div className="ej-signature-footer-lock">
            <EJSignatureBlock documentType="proforma"/>
            <EJCompanyFooter/>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { EJProformaClassic, EJProformaModern, EJProformaBold });
