/* global React */
const { useState } = React;

// ============================================================
// Shared atoms used across all Estrella documents
// Palette: #0B3D2E (emerald) / #C9A24B (gold)
// ============================================================

const T = {
  // Tri-lingual labels: PL / EN / SK
  proforma: { pl: "Faktura proforma", en: "Pro Forma Invoice", sk: "Predfaktúra" },
  cmr: { pl: "List przewozowy CMR", en: "Delivery Note · CMR", sk: "Dodací list · CMR" },
  statement: { pl: "Wyciąg z konta", en: "Statement of Account", sk: "Výpis z účtu" },
  pz: { pl: "Dokument PZ — kalkulacja", en: "Goods Receipt — Landed Cost", sk: "Príjemka — kalkulácia" },
  seller: { pl: "Sprzedawca", en: "Seller", sk: "Predávajúci" },
  buyer: { pl: "Nabywca", en: "Bill to", sk: "Odberateľ" },
  shipto: { pl: "Odbiorca", en: "Ship to", sk: "Doručiť na" },
  no: { pl: "Nr", en: "No.", sk: "Č." },
  date: { pl: "Data wystawienia", en: "Invoice date", sk: "Dátum vystavenia" },
  due: { pl: "Termin płatności", en: "Payment due", sk: "Splatnosť" },
  total: { pl: "Razem", en: "Total", sk: "Spolu" },
  net: { pl: "Wartość netto", en: "Net", sk: "Bez DPH" },
  gross: { pl: "Wartość brutto", en: "Gross", sk: "S DPH" },
  qty: { pl: "Ilość", en: "Qty", sk: "Množstvo" },
  price: { pl: "Cena netto", en: "Unit price", sk: "Jed. cena" },
  desc: { pl: "Nazwa", en: "Description", sk: "Popis" },
  bank: { pl: "Dane bankowe", en: "Bank details", sk: "Bankové údaje" },
  carrier: { pl: "Transport", en: "Shipment", sk: "Doprava" },
};

const tri = (key, langs = ["en", "pl", "sk"]) =>
  langs.map((l) => T[key]?.[l]).filter(Boolean).join(" · ");

// Sample data shared across all docs (real values from uploaded PDFs)
const SAMPLE = {
  doc_no: "PROF 95/2026",
  invoice_no: "WDT 48/2026",
  cmr_no: "CMR-EJ-26-0095",
  date: "2026-05-08",
  due: "2026-05-15",
  payment: "Bank transfer · SEPA",
  rate: { eur: 4.2286, date: "2026-05-07", table: "087/A/NBP/2026" },
  seller: {
    name: "ESTRELLA JEWELS Sp. z o.o. SPÓŁKA KOMANDYTOWA",
    addr: "ul. Wybrzeże Kościuszkowskie 31/33",
    city: "00-379 Warszawa, Polska",
    sales: "Ulica Sabały 58, 02-174 Warszawa",
    vat: "PL5252812119",
    phone: "+48 22 258 33 98",
    email: "info@estrellajewels.eu",
    web: "www.estrellajewels.eu",
  },
  buyer: {
    name: "Anastazia Panakova — Zlatníctvo Panaks",
    addr: "T.G. Masaryka 21",
    city: "91451 Trenčianske Teplice",
    country: "Slovakia",
    vat: "SK1020315978",
  },
  shipto: {
    name: "Zlatníctvo Panaks",
    addr: "Námestie SNP 79/7",
    city: "91101 Trenčianske Teplice",
    country: "Slovakia",
  },
  carrier: {
    name: "DHL Express",
    service: "EXPRESS WORLDWIDE",
    awb: "1012 1782 15",
    pickup: "2026-05-09",
    eta: "2026-05-12",
    origin: "Warszawa, PL",
    destination: "Trenčín, SK",
    pieces: 1,
    weight_kg: 0.42,
    dim_cm: "22×18×8",
    incoterm: "DAP",
    path: "Path B · Agency",
    insurance: "EUR 200",
  },
  bank: [
    { cur: "EUR", iban: "PL59 1090 2851 0000 0001 4434 7174", swift: "WBKPPLPP", bank: "Santander Bank Polska S.A." },
    { cur: "USD", iban: "PL31 1090 2851 0000 0001 4434 7150", swift: "WBKPPLPP", bank: "Santander Bank Polska S.A." },
    { cur: "PLN", iban: "PL14 1090 2851 0000 0001 4434 7099", swift: "WBKPPLPP", bank: "Santander Bank Polska S.A." },
  ],
  lines: [
    {
      sku: "EJ-RG-585-0142",
      desc_en: "14KT Yellow Gold Ring · Diamond Stud (0.08ct VS/G)",
      desc_pl: "Pierścionek ze złota próby 585 — diament VS/G",
      desc_sk: "Prsteň zo žltého zlata 585 — diamant VS/G",
      origin: "IN",
      purity: "585 / 14K · Diam VS/G",
      qty: 1,
      unit_price: 139.31,
      net: 139.31,
      gross: 139.31,
      thumb: "ring",
    },
    {
      sku: "FRT-IN-PL",
      desc_en: "Freight — DHL Express, Mumbai → Warsaw",
      desc_pl: "Fracht — DHL Express, Mumbai → Warszawa",
      desc_sk: "Doprava — DHL Express, Mumbai → Varšava",
      origin: "—",
      purity: "Service",
      qty: 1,
      unit_price: 75.6,
      net: 75.6,
      gross: 75.6,
      thumb: "freight",
    },
    {
      sku: "INS-FGI-DOOR",
      desc_en: "Insurance — Future Generali India, door-to-door cover",
      desc_pl: "Ubezpieczenie — Future Generali India, door-to-door",
      desc_sk: "Poistenie — Future Generali India, door-to-door",
      origin: "—",
      purity: "Service",
      qty: 1,
      unit_price: 8.49,
      net: 8.49,
      gross: 8.49,
      thumb: "shield",
    },
  ],
  total_eur: 223.4,
  total_pln: 944.67,
  paid: 0,
};

// ============================================================
// Logo — real Estrella Jewels brandmark (PNG)
// `mono` inverts to white via CSS filter for use on dark rails.
// `lockup` controls layout: "horizontal" (default) shows the
// supplied wordmark; "stacked" wraps it in a green/gold band.
// ============================================================
function Logo({ size = "md", mono = false, lockup = "horizontal", tag = true }) {
  const h = size === "lg" ? 64 : size === "sm" ? 36 : size === "xs" ? 26 : 48;
  const filter = mono
    ? "brightness(0) invert(1)"               // pure white silhouette
    : "none";
  return (
    <div className="ej-logo" style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
      <img
        src={(window.__resources && window.__resources.logo) || "estrella-docs/logo-transparent.png"}
        alt="Estrella Jewels"
        style={{
          height: h,
          width: "auto",
          display: "block",
          filter,
          imageRendering: "-webkit-optimize-contrast",
        }}
      />
      {tag && size === "lg" && !mono && (
        <div style={{
          paddingLeft: 12, marginLeft: 4,
          borderLeft: "1px solid #C9A24B",
          fontSize: 8.5, letterSpacing: "0.22em", textTransform: "uppercase",
          color: "#B0892F", fontWeight: 600, lineHeight: 1.4,
        }}>
          Fine Gold<br/>Est. 2014
        </div>
      )}
    </div>
  );
}

// ============================================================
// Carrier logos — small inline SVG marks
// ============================================================
function CarrierMark({ name = "DHL" }) {
  if (name === "DHL Express" || name === "DHL")
    return <span className="ej-cb ej-cb-dhl">DHL</span>;
  if (name === "FedEx")
    return <span className="ej-cb ej-cb-fedex">Fed<span>Ex</span></span>;
  if (name === "UPS")
    return <span className="ej-cb ej-cb-ups">UPS</span>;
  return <span className="ej-cb">{name}</span>;
}

// ============================================================
// Address card
// ============================================================
function Address({ label, party }) {
  return (
    <div className="ej-addr">
      <div className="ej-addr-label">{label}</div>
      <div className="ej-addr-name">{party.name}</div>
      <div>{party.addr}</div>
      <div>{party.city}{party.country ? `, ${party.country}` : ""}</div>
      {party.vat && <div style={{ marginTop: 4, color: "#475569" }}>VAT EU · {party.vat}</div>}
    </div>
  );
}

// ============================================================
// Carrier strip — full-width band of shipping facts
// ============================================================
function CarrierStrip({ c = SAMPLE.carrier }) {
  return (
    <div className="ej-carrier">
      <div style={{ background: "#0B3D2E", color: "#fff", display: "flex", alignItems: "center", gap: 8, minWidth: 130 }}>
        <CarrierMark name={c.name} />
        <div style={{ fontSize: 8.5, lineHeight: 1.2 }}>
          <div style={{ fontWeight: 700 }}>{c.service}</div>
          <div style={{ opacity: 0.75 }}>AWB {c.awb}</div>
        </div>
      </div>
      <div>
        <div className="ej-carrier-label">Pickup → ETA</div>
        <div className="ej-carrier-val">{c.pickup} → {c.eta}</div>
      </div>
      <div>
        <div className="ej-carrier-label">Origin → Destination</div>
        <div className="ej-carrier-val">{c.origin} → {c.destination}</div>
      </div>
      <div>
        <div className="ej-carrier-label">Pieces · Weight · Dim</div>
        <div className="ej-carrier-val">{c.pieces} pcs · {c.weight_kg} kg · {c.dim_cm}</div>
      </div>
      <div>
        <div className="ej-carrier-label">Incoterm · Path</div>
        <div className="ej-carrier-val">{c.incoterm} · {c.path}</div>
      </div>
      <div>
        <div className="ej-carrier-label">Insurance</div>
        <div className="ej-carrier-val">{c.insurance}</div>
      </div>
    </div>
  );
}

// ============================================================
// Item thumbnail (inline SVG icon — placeholder for real photo)
// ============================================================
function Thumb({ kind = "ring", size = 32 }) {
  const stroke = "#0B3D2E";
  const gold = "#C9A24B";
  if (kind === "freight")
    return (
      <svg width={size} height={size} viewBox="0 0 32 32" style={{ background: "#FBF8F1", borderRadius: 4 }}>
        <rect x="3" y="11" width="18" height="12" fill="none" stroke={stroke} strokeWidth="1.4"/>
        <path d="M21 14h5l3 4v5h-8z" fill="none" stroke={stroke} strokeWidth="1.4"/>
        <circle cx="9" cy="25" r="2" fill={gold}/>
        <circle cx="24" cy="25" r="2" fill={gold}/>
      </svg>
    );
  if (kind === "shield")
    return (
      <svg width={size} height={size} viewBox="0 0 32 32" style={{ background: "#FBF8F1", borderRadius: 4 }}>
        <path d="M16 4l10 4v8c0 6-4.5 10-10 12-5.5-2-10-6-10-12V8z" fill="none" stroke={stroke} strokeWidth="1.4"/>
        <path d="M11 16l4 4 6-7" fill="none" stroke={gold} strokeWidth="1.6"/>
      </svg>
    );
  // ring
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{ background: "#FBF8F1", borderRadius: 4 }}>
      <circle cx="16" cy="20" r="7" fill="none" stroke={gold} strokeWidth="1.8"/>
      <path d="M11 11l5-5 5 5-2 3h-6z" fill={gold} opacity="0.85"/>
      <circle cx="16" cy="9" r="1.4" fill={stroke}/>
    </svg>
  );
}

// ============================================================
// Bank details list
// ============================================================
function BankBlock({ banks = SAMPLE.bank }) {
  return (
    <div className="ej-bank">
      <div className="ej-eyebrow" style={{ marginBottom: 6 }}>{tri("bank")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {banks.map((b) => (
          <div key={b.cur} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10 }}>
            <span className="ej-bank-cur">{b.cur}</span>
            <span className="ej-mono" style={{ fontWeight: 600 }}>{b.iban}</span>
            <span style={{ color: "#64748B" }}>· SWIFT {b.swift}</span>
            <span style={{ color: "#64748B" }}>· {b.bank}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// Footer compliance
// ============================================================
function ComplianceFooter() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, fontSize: 9, color: "#64748B", lineHeight: 1.5 }}>
      <div>
        <div className="ej-eyebrow" style={{ marginBottom: 4 }}>Payment terms</div>
        Payment due within 7 days of invoice date. Goods remain property of Estrella Jewels until full payment is received. Late payment incurs statutory interest under Polish commercial law.
      </div>
      <div>
        <div className="ej-eyebrow" style={{ marginBottom: 4 }}>Returns &amp; warranty</div>
        14-day return policy on undamaged goods in original packaging. Warranty: 2 years on manufacturing defects per EU directive 1999/44/EC. Hallmarked items certified per Polish Office of Measures.
      </div>
      <div>
        <div className="ej-eyebrow" style={{ marginBottom: 4 }}>Privacy · GDPR</div>
        Data controller: Estrella Jewels Sp. z o.o. Personal data processed solely for contract performance and tax obligations under GDPR Art. 6(1)(b)(c). Retention 5 years.
      </div>
    </div>
  );
}

// Export to window for cross-script use
Object.assign(window, {
  EJ_T: T, EJ_tri: tri, EJ_SAMPLE: SAMPLE,
  EJLogo: Logo, EJCarrierMark: CarrierMark, EJAddress: Address,
  EJCarrierStrip: CarrierStrip, EJThumb: Thumb, EJBank: BankBlock,
  EJCompliance: ComplianceFooter,
});
