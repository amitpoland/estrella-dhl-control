const {
  apiFetch,
  fmtPLN,
  Badge,
  Card,
  Btn,
  Sel,
  Toast,
  SessionBanner,
  EstrellaMark,
  SubTabStrip,
  Sidebar,
  _resolveOperator
} = window.EstrellaShared;
const GOLD = "var(--accent)";
const NAV_TREE = [
  { id: "dashboard", label: "Dashboard", icon: "\u25A6" },
  { id: "inbox", label: "Inbox", icon: "\u2709", badge: "NEW" },
  { id: "shipments", label: "Shipments", icon: "\u2B21" },
  { id: "documents", label: "Documents", icon: "\u{1F4C4}" },
  { id: "accounting", label: "Accounting", icon: "\u229E", badge: "NEW" },
  { id: "inventory", label: "Inventory", icon: "\u25EB" },
  { id: "reports", label: "Reports", icon: "\u2261" },
  { id: "g_setup", label: "Setup", icon: "\u2699", defaultId: "admin", children: [
    { id: "admin", label: "Settings" },
    { id: "admin_users", label: "Admin \xB7 Users" },
    { id: "master", label: "Master Data" },
    { id: "carriers", label: "Carriers" },
    { id: "wfirma_setup", label: "wFirma" },
    { id: "api_status", label: "API Status" },
    { id: "diagnostics", label: "Diagnostics" },
    { id: "automation", label: "Automation" },
    { id: "intelligence_grp", label: "Parser / Learning" },
    { id: "coverage", label: "Coverage Matrix" },
    { id: "warehouse_scanner", label: "Warehouse Scanner", href: "/dashboard/warehouse.html" }
  ] }
];
const NAV_INDEX = {};
(function buildIndex(tree) {
  tree.forEach((n) => {
    NAV_INDEX[n.id] = n;
    if (n.children) buildIndex(n.children);
  });
})(NAV_TREE);
const ROUTE_REDIRECTS = {
  "pz_accounting": "accounting",
  "pz": "accounting",
  "dhl_clearance": "dhl",
  "customs_documents": "documents",
  "customs": "documents",
  "wfirma": "wfirma_setup",
  "ai_bridge": "automation",
  "learning": "intelligence_grp"
};
function navGroupOf(id) {
  for (const n of NAV_TREE) {
    if (n.children && n.children.some((c) => c.id === id)) return n;
  }
  return null;
}
const STATUS_MAP = {
  "Draft": { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" },
  "In Transit": { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
  "Pre-check Pending": { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
  "Pre-check Completed": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Awaiting DHL Email": { bg: "var(--badge-orange-bg)", text: "var(--badge-orange-text)", border: "var(--badge-orange-border)" },
  "DHL Email Received": { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
  "Reply Sent": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Reply Queued": { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
  "SAD Pending": { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
  "SAD Uploaded": { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
  "Customs Parsed": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Verification Needed": { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)", border: "var(--badge-red-border)" },
  "Customs Verified": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Locked": { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" },
  "Ready for PZ": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "PZ Failed": { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)", border: "var(--badge-red-border)" },
  "Generated": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Ready for Booking": { bg: "var(--badge-purple-bg)", text: "var(--badge-purple-text)", border: "var(--badge-purple-border)" },
  "Exported": { bg: "var(--badge-accent-bg)", text: "var(--badge-accent-text)", border: "var(--badge-accent-border)" },
  "Awaiting DHL": { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
  "Awaiting SAD": { bg: "var(--badge-orange-bg)", text: "var(--badge-orange-text)", border: "var(--badge-orange-border)" },
  "Action Required": { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)", border: "var(--badge-red-border)" },
  "In Preparation": { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" },
  "Completed": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Pending": { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
  "Live": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  "Awaiting Clearance": { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
  "Processing": { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
  "Reply Package Prepared": { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" }
};
function mapOverall(status) {
  const m = {
    success: "Ready for Booking",
    partial: "Ready for Booking",
    blocked: "Action Required",
    failed: "Action Required",
    awaiting_dhl_email: "Awaiting DHL",
    awaiting_sad: "Awaiting SAD",
    awaiting_clearance: "Awaiting Clearance",
    in_preparation: "In Preparation",
    draft: "Draft",
    ready: "Ready for PZ",
    processing: "In Preparation",
    collecting: "In Preparation"
  };
  return m[status] || (status ? status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Pending");
}
function mapDhlStatus(s) {
  if (!s) return "\u2014";
  const m = {
    awaiting_dhl_email: "Awaiting DHL Email",
    dhl_email_received: "DHL Email Received",
    reply_sent: "Reply Sent",
    reply_queued: "Reply Queued",
    pre_check_completed: "Pre-check Completed",
    pre_check_pending: "Pre-check Pending",
    reply_package_prepared: "Reply Package Prepared"
  };
  return m[s] || s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function mapSadStatus(s) {
  if (!s) return "SAD Pending";
  const m = {
    // frontend legacy values
    sad_pending: "SAD Pending",
    sad_uploaded: "SAD Uploaded",
    customs_parsed: "Customs Parsed",
    customs_verified: "Customs Verified",
    verification_needed: "Verification Needed",
    // backend _derive_sad_status() values
    missing: "SAD Pending",
    uploaded: "SAD Uploaded",
    uploaded_parsed: "Customs Parsed"
  };
  return m[s] || s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function mapPzStatus(s) {
  if (!s) return "Locked";
  const m = {
    locked: "Locked",
    ready: "Ready for PZ",
    generated: "Generated",
    exported: "Exported",
    // PZ Preview Authority Audit (2026-05-21) — surface engine failure on
    // the same badge that previously claimed "Ready for PZ". Single
    // authority for the PZ workflow status.
    failed: "PZ Failed",
    complete: "Generated"
  };
  return m[s] || s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function Modal({ title, onClose, children, wide }) {
  return /* @__PURE__ */ React.createElement("div", { style: {
    position: "fixed",
    inset: 0,
    background: "var(--overlay)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1e3,
    padding: 24
  }, onClick: (e) => e.target === e.currentTarget && onClose() }, /* @__PURE__ */ React.createElement("div", { style: {
    background: "var(--card)",
    borderRadius: 10,
    width: wide ? 680 : 480,
    maxWidth: "100%",
    maxHeight: "90vh",
    overflow: "auto",
    boxShadow: "0 20px 60px var(--shadow-heavy)",
    border: "1px solid var(--border)"
  } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "18px 24px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" } }, /* @__PURE__ */ React.createElement("h2", { style: { margin: 0, fontSize: 16, fontWeight: 700, fontFamily: '"DM Serif Display",serif', color: "var(--text)" } }, title), /* @__PURE__ */ React.createElement("button", { onClick: onClose, style: { background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "var(--text-3)" } }, "\xD7")), /* @__PURE__ */ React.createElement("div", { style: { padding: 24 } }, children)));
}
function FormField({ label, children, hint }) {
  return /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16 } }, /* @__PURE__ */ React.createElement("label", { style: { display: "block", fontSize: 11, fontWeight: 600, color: "var(--text-2)", marginBottom: 5, letterSpacing: "0.04em", textTransform: "uppercase" } }, label), children, hint && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 3 } }, hint));
}
function Inp({ value, onChange, placeholder, type = "text", style: s }) {
  return /* @__PURE__ */ React.createElement("input", { value, onChange, placeholder, type, style: {
    width: "100%",
    padding: "8px 10px",
    borderRadius: 6,
    border: "1px solid var(--border)",
    fontSize: 12,
    color: "var(--text)",
    background: "var(--bg-subtle)",
    outline: "none",
    boxSizing: "border-box",
    fontFamily: "inherit",
    ...s
  } });
}
function SectionHeader({ icon, title, subtitle, status }) {
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12, padding: "14px 20px", borderBottom: "1px solid var(--border)", background: "var(--bg-subtle)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 32, height: 32, borderRadius: 6, background: "var(--accent-subtle)", border: "1px solid var(--accent-border)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: "var(--accent)" } }, icon), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, title), subtitle && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 1 } }, subtitle)), status && /* @__PURE__ */ React.createElement(Badge, { status }));
}
function InfoRow({ label, value, mono }) {
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "6px 0", borderBottom: "1px solid var(--border-subtle)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-2)", fontWeight: 500 } }, label), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text)", fontWeight: 600, fontFamily: mono ? "monospace" : "inherit", textAlign: "right", maxWidth: "60%", wordBreak: "break-all" } }, value ?? "\u2014"));
}
function TopBar({ onNewShipment, onToggleDark, isDark, user, onLogout }) {
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const initials = user ? user.full_name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase() : "U";
  React.useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((o) => !o);
      }
      if (e.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  return /* @__PURE__ */ React.createElement(React.Fragment, null, searchOpen && /* @__PURE__ */ React.createElement("div", { onClick: () => setSearchOpen(false), style: { position: "fixed", inset: 0, zIndex: 8e3, background: "var(--overlay)", display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: 120 } }, /* @__PURE__ */ React.createElement("div", { onClick: (e) => e.stopPropagation(), style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, boxShadow: "0 16px 48px var(--shadow-heavy)", width: "100%", maxWidth: 560, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 16 } }, "\u2315"), /* @__PURE__ */ React.createElement(
    "input",
    {
      autoFocus: true,
      value: search,
      onChange: (e) => setSearch(e.target.value),
      placeholder: "Search AWB, MRN, batch ID\u2026",
      style: { flex: 1, border: "none", outline: "none", fontSize: 14, color: "var(--text)", background: "transparent", fontFamily: "inherit" }
    }
  ), /* @__PURE__ */ React.createElement("kbd", { style: { fontSize: 10, color: "var(--text-3)", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 4, padding: "2px 6px" } }, "Esc")), /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 16px 12px", fontSize: 11, color: "var(--text-3)" } }, "Type to search shipments, AWBs, MRNs\u2026"))), /* @__PURE__ */ React.createElement("header", { style: { height: 56, background: "var(--card)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", padding: "0 24px", gap: 12, flexShrink: 0 } }, /* @__PURE__ */ React.createElement("button", { onClick: () => setSearchOpen(true), style: { display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, cursor: "pointer", color: "var(--text-3)", fontSize: 12, fontFamily: "inherit", flex: 1, maxWidth: 280, textAlign: "left" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14 } }, "\u2315"), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, color: "var(--text-3)" } }, "Search\u2026"), /* @__PURE__ */ React.createElement("kbd", { style: { fontSize: 10, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 5px", color: "var(--text-3)" } }, "\u2318K")), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }), /* @__PURE__ */ React.createElement("button", { onClick: onToggleDark, title: isDark ? "Light mode" : "Dark mode", style: { background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 10px", cursor: "pointer", fontSize: 14, color: "var(--text-2)", fontFamily: "inherit" } }, isDark ? "\u2600" : "\u{1F33F}"), /* @__PURE__ */ React.createElement("button", { onClick: onNewShipment, style: { display: "flex", alignItems: "center", gap: 6, background: "var(--accent)", color: "var(--accent-text)", border: "none", borderRadius: 6, padding: "7px 14px", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16, lineHeight: 1 } }, "+"), " New Shipment"), user && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { width: 34, height: 34, borderRadius: "50%", background: "linear-gradient(135deg,var(--accent),var(--accent-light))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, color: "var(--accent-text)", boxShadow: "0 1px 3px rgba(0,0,0,.1)", border: "2px solid var(--accent-border)", letterSpacing: "0.02em" } }, initials), /* @__PURE__ */ React.createElement("div", { style: { lineHeight: 1.3 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.01em" } }, user.full_name), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 4, marginTop: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, fontWeight: 700, color: "var(--accent)", background: "var(--accent-subtle)", border: "1px solid var(--accent-border)", padding: "1px 6px", borderRadius: 10, textTransform: "uppercase", letterSpacing: "0.06em" } }, user.role), user.is_approved && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, color: "var(--badge-green-text)", background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", padding: "1px 5px", borderRadius: 10, fontWeight: 600 } }, "\u2713"))), /* @__PURE__ */ React.createElement("div", { style: { width: 1, height: 24, background: "var(--border)", margin: "0 2px" } }), /* @__PURE__ */ React.createElement("button", { onClick: onLogout, style: { background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, cursor: "pointer", fontSize: 11, fontWeight: 500, color: "var(--text-2)", padding: "5px 12px", fontFamily: "inherit", transition: "all .15s" }, onMouseEnter: (e) => {
    e.currentTarget.style.background = "var(--badge-red-bg)";
    e.currentTarget.style.color = "var(--badge-red-text)";
    e.currentTarget.style.borderColor = "var(--badge-red-border)";
  }, onMouseLeave: (e) => {
    e.currentTarget.style.background = "var(--bg-subtle)";
    e.currentTarget.style.color = "var(--text-2)";
    e.currentTarget.style.borderColor = "var(--border)";
  } }, "Logout"))));
}
function SectionLabel({ children, style }) {
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12, marginBottom: 12, ...style } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.12em", textTransform: "uppercase", whiteSpace: "nowrap" } }, children), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, height: 1, background: "var(--border)" } }));
}
function PanelCard({ title, subtitle, status, children, accent }) {
  return /* @__PURE__ */ React.createElement("div", { style: {
    background: "var(--card)",
    borderRadius: 10,
    boxShadow: "0 1px 2px var(--shadow)",
    overflow: "hidden",
    border: accent ? `1px solid var(--border)` : "1px solid var(--border)",
    borderLeft: accent ? `3px solid ${accent}` : "1px solid var(--border)"
  } }, (title || status) && /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, background: "var(--bg-subtle)" } }, /* @__PURE__ */ React.createElement("div", null, title && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, title), subtitle && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 2 } }, subtitle)), status && /* @__PURE__ */ React.createElement(Badge, { status })), /* @__PURE__ */ React.createElement("div", null, children));
}
function StatTile({ label, value, sub, accent }) {
  return /* @__PURE__ */ React.createElement("div", { style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, padding: "16px 20px", boxShadow: "0 1px 2px var(--shadow)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 } }, label), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 22, fontWeight: 700, color: accent || "var(--text)", fontFamily: '"DM Serif Display",serif', letterSpacing: "-0.01em", lineHeight: 1 } }, value ?? "\u2014"), sub && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 4 } }, sub));
}
const IntakeSectionHeader = ({ icon, label, sub }) => /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 14, paddingBottom: 10, borderBottom: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16 } }, icon), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)", letterSpacing: "-0.01em" } }, label), sub && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginTop: 1 } }, sub)));
const IntakeFileDropZone = ({ accept, multiple, hint, files, onChange, compact }) => {
  const ref = React.useRef();
  const label = files && files.length > 0 ? multiple ? files.map((f) => f.name).join(", ") : files[0].name : hint;
  return /* @__PURE__ */ React.createElement("label", { style: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: compact ? "12px 14px" : "18px 14px",
    borderRadius: 6,
    border: "2px dashed var(--badge-neutral-border)",
    cursor: "pointer",
    background: "var(--bg-subtle)",
    justifyContent: "center",
    flexDirection: "column",
    textAlign: "center",
    transition: "border-color .15s"
  } }, /* @__PURE__ */ React.createElement(
    "input",
    {
      ref,
      type: "file",
      accept,
      multiple: !!multiple,
      onChange: (e) => onChange(Array.from(e.target.files)),
      style: { display: "none" }
    }
  ), /* @__PURE__ */ React.createElement("span", { style: { fontSize: compact ? 16 : 22, color: "var(--text-3)" } }, files && files.length > 0 ? "\u2713" : accept.includes(".pdf") ? "\u{1F4C4}" : "\u{1F4CA}"), /* @__PURE__ */ React.createElement("span", { style: {
    fontSize: 11,
    color: files && files.length > 0 ? "var(--badge-green-text)" : "var(--text-2)",
    fontWeight: files && files.length > 0 ? 600 : 400
  } }, label));
};
const IntakeRemoveBtn = ({ onClick }) => /* @__PURE__ */ React.createElement(
  "button",
  {
    onClick,
    title: "Remove",
    style: {
      background: "var(--badge-red-bg)",
      border: "1px solid var(--badge-red-border)",
      borderRadius: 5,
      padding: "3px 8px",
      fontSize: 11,
      color: "var(--badge-red-text)",
      cursor: "pointer",
      fontFamily: "inherit",
      fontWeight: 600
    }
  },
  "\u2715 Remove"
);
const _NS_DOC_TYPES = [
  { id: "purchase_invoice", label: "Purchase Invoice", icon: "\u{1F4C4}", hint: "Commercial invoice from supplier (purchase price)", multi: true, needsClient: false, needsSupplier: true, accept: ".pdf", allowedExts: [".pdf"] },
  { id: "sales_proforma", label: "Sales Proforma Invoice", icon: "\u{1F4D1}", hint: "Proforma issued to client \u2014 sales price \xB7 pre-acceptance", multi: true, needsClient: true, needsSupplier: false, accept: ".pdf", allowedExts: [".pdf"] },
  { id: "sales_invoice", label: "Sales Invoice (Final)", icon: "\u{1F9FE}", hint: "Final commercial invoice issued to client", multi: true, needsClient: true, needsSupplier: false, accept: ".pdf", allowedExts: [".pdf"] },
  { id: "purchase_packing_list", label: "Purchase Packing List", icon: "\u{1F4CB}", hint: "Items + purchase prices \u2014 flows to customs (CIF / SAD)", multi: true, needsClient: false, needsSupplier: true, accept: ".pdf,.xlsx,.xls", allowedExts: [".pdf", ".xlsx", ".xls"] },
  { id: "sales_packing_list", label: "Sales Packing List", icon: "\u{1F4CB}", hint: "Same items + sales prices \u2014 flows to warehouse stock valuation", multi: true, needsClient: true, needsSupplier: false, accept: ".pdf,.xlsx,.xls", allowedExts: [".pdf", ".xlsx", ".xls"] },
  { id: "awb", label: "AWB / Tracking PDF", icon: "\u{1F4CE}", hint: "Air-waybill / tracking document", multi: false, needsClient: false, needsSupplier: false, accept: ".pdf", allowedExts: [".pdf"] },
  { id: "service_invoice", label: "Service Invoice", icon: "\u{1F4BC}", hint: "Shipping, insurance, customs-agent or handling invoice", multi: true, needsClient: false, needsSupplier: true, accept: ".pdf,.xlsx,.xls", allowedExts: [".pdf", ".xlsx", ".xls"] },
  { id: "carnet", label: "ATA Carnet / Temp Doc", icon: "\u{1F6C2}", hint: "Temporary import / export document", multi: false, needsClient: false, needsSupplier: false, accept: ".pdf", allowedExts: [".pdf"] },
  { id: "other", label: "Other Document", icon: "\u{1F4C1}", hint: "Any supporting document", multi: true, needsClient: false, needsSupplier: false, accept: ".pdf,.xlsx,.xls,.jpg,.jpeg,.png", allowedExts: [".pdf", ".xlsx", ".xls", ".jpg", ".jpeg", ".png"] }
];
const _NS_WIRED_TYPES = /* @__PURE__ */ new Set([
  "purchase_invoice",
  "purchase_packing_list",
  "sales_proforma",
  "sales_invoice",
  "sales_packing_list",
  "awb",
  "service_invoice",
  "carnet",
  "other"
]);
function AddDocumentModal({ batchId, onClose, onUploaded }) {
  const [docType, setDocType] = React.useState("purchase_invoice");
  const [file, setFile] = React.useState(null);
  const [slotError, setSlotError] = React.useState("");
  const [submitError, setSubmitError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [clientList, setClientList] = React.useState([]);
  const [supplierList, setSupplierList] = React.useState([]);
  const [defaultClientCid, setDefaultClientCid] = React.useState("");
  const [defaultSupplierCid, setDefaultSupplierCid] = React.useState("");
  const [clientOverride, setClientOverride] = React.useState("");
  const [supplierOverride, setSupplierOverride] = React.useState("");
  const docTypes = React.useMemo(
    () => _NS_DOC_TYPES.filter((t) => t.id !== "sad"),
    []
  );
  const type = docTypes.find((t) => t.id === docType) || docTypes[0];
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cm, sup, rClient, rSupplier] = await Promise.all([
          apiFetch("/api/v1/customer-master/?limit=500").catch(() => null),
          apiFetch("/api/v1/suppliers/?limit=500").catch(() => null),
          apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/contractor-resolution/client`).catch(() => null),
          apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/contractor-resolution/supplier`).catch(() => null)
        ]);
        if (cancelled) return;
        if (cm) {
          const arr = Array.isArray(cm) ? cm : cm.customers || [];
          setClientList(arr.map((c) => ({
            contractor_id: c.bill_to_contractor_id || c.id || "",
            name: c.bill_to_name || c.name || "",
            country: c.country || ""
          })).filter((x) => x.contractor_id && x.name));
        }
        if (sup) {
          setSupplierList((sup.suppliers || []).filter((x) => x.contractor_id && x.name));
        }
        if (rClient && rClient.matched_master_id) {
          const id = String(rClient.matched_master_id);
          setDefaultClientCid(id);
          setClientOverride(id);
        }
        if (rSupplier && rSupplier.matched_master_id) {
          const id = String(rSupplier.matched_master_id);
          setDefaultSupplierCid(id);
          setSupplierOverride(id);
        }
      } catch (_) {
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [batchId]);
  const fileInputRef = React.useRef(null);
  const handleFile = (e) => {
    const f = (e.target.files || [])[0];
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (!f) return;
    const allowed = (type.allowedExts || [".pdf"]).map((s) => s.toLowerCase());
    const dot = f.name.lastIndexOf(".");
    const ext = (dot >= 0 ? f.name.slice(dot) : "").toLowerCase();
    if (allowed.indexOf(ext) < 0) {
      setSlotError(`File type ${ext || "(none)"} not allowed for ${type.label}. Allowed: ${allowed.join(", ")}`);
      setFile(null);
      return;
    }
    setSlotError("");
    setFile(f);
  };
  const hasMasterClients = clientList.length > 0;
  const hasMasterSuppliers = supplierList.length > 0;
  const saveDisabled = !file || submitting;
  const handleSave = async () => {
    if (!file) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("document_type", docType);
      if (supplierOverride) fd.append("supplier_contractor_id", supplierOverride);
      if (clientOverride) fd.append("client_contractor_id", clientOverride);
      const r = await fetch(
        `/api/v1/shipment/${encodeURIComponent(batchId)}/add-document`,
        { method: "POST", body: fd, credentials: "include" }
      );
      if (!r.ok) {
        const msg = await r.text().catch(() => "Upload failed");
        throw new Error(msg);
      }
      const data = await r.json();
      if (onUploaded) onUploaded({ document_type: docType, ...data });
      onClose();
    } catch (e) {
      setSubmitError(e.message || "Upload failed.");
      setSubmitting(false);
    }
  };
  return /* @__PURE__ */ React.createElement(Modal, { title: "Add Document", onClose }, submitError && /* @__PURE__ */ React.createElement("div", { "data-testid": "add-doc-submit-error", style: {
    marginBottom: 14,
    padding: "10px 14px",
    borderRadius: 6,
    background: "var(--badge-red-bg)",
    border: "1px solid var(--badge-red-border)",
    fontSize: 12,
    color: "var(--badge-red-text)"
  } }, submitError), /* @__PURE__ */ React.createElement(FormField, { label: "Document Type", hint: type.hint }, /* @__PURE__ */ React.createElement(
    Sel,
    {
      "data-testid": "add-doc-type-select",
      value: docType,
      onChange: (e) => {
        setDocType(e.target.value);
        setFile(null);
        setSlotError("");
      }
    },
    docTypes.map((t) => /* @__PURE__ */ React.createElement("option", { key: t.id, value: t.id }, t.icon, " ", t.label))
  )), /* @__PURE__ */ React.createElement(FormField, { label: "File", hint: `Allowed: ${(type.allowedExts || []).join(", ")}` }, /* @__PURE__ */ React.createElement(
    "input",
    {
      ref: fileInputRef,
      "data-testid": "add-doc-file",
      type: "file",
      accept: type.accept || ".pdf",
      onChange: handleFile,
      style: { width: "100%", fontSize: 12 }
    }
  ), file && /* @__PURE__ */ React.createElement("div", { "data-testid": "add-doc-file-name", style: { fontSize: 11, marginTop: 4, color: "var(--text-2)" } }, "\u{1F4C4} ", file.name), slotError && /* @__PURE__ */ React.createElement("div", { "data-testid": "add-doc-slot-error", style: { fontSize: 11, marginTop: 4, color: "var(--badge-red-text)" } }, slotError)), (type.needsClient || type.needsSupplier) && /* @__PURE__ */ React.createElement("div", { style: {
    padding: "12px 14px",
    borderRadius: 6,
    background: "var(--bg-subtle)",
    border: "1px solid var(--border)",
    marginBottom: 14
  } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 } }, "Per-document contractor (override)"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: type.needsClient && type.needsSupplier ? "1fr 1fr" : "1fr", gap: 12 } }, type.needsClient && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "Client"), hasMasterClients ? /* @__PURE__ */ React.createElement(
    Sel,
    {
      "data-testid": "add-doc-client-override",
      value: clientOverride,
      onChange: (e) => setClientOverride(e.target.value)
    },
    /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 inherit shipment-level \u2014"),
    clientList.map((c) => /* @__PURE__ */ React.createElement("option", { key: c.contractor_id, value: c.contractor_id }, c.name, c.country ? ` (${c.country})` : ""))
  ) : /* @__PURE__ */ React.createElement(
    Inp,
    {
      "data-testid": "add-doc-client-fallback",
      value: clientOverride,
      onChange: (e) => setClientOverride(e.target.value),
      placeholder: "contractor id (master data empty)"
    }
  )), type.needsSupplier && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "Supplier"), hasMasterSuppliers ? /* @__PURE__ */ React.createElement(
    Sel,
    {
      "data-testid": "add-doc-supplier-override",
      value: supplierOverride,
      onChange: (e) => setSupplierOverride(e.target.value)
    },
    /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 inherit shipment-level \u2014"),
    supplierList.map((s) => /* @__PURE__ */ React.createElement("option", { key: s.contractor_id, value: s.contractor_id }, s.name, s.country ? ` (${s.country})` : ""))
  ) : /* @__PURE__ */ React.createElement(
    Inp,
    {
      "data-testid": "add-doc-supplier-fallback",
      value: supplierOverride,
      onChange: (e) => setSupplierOverride(e.target.value),
      placeholder: "contractor id (master data empty)"
    }
  )))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      "data-testid": "add-doc-cancel",
      onClick: onClose,
      disabled: submitting,
      style: {
        padding: "8px 16px",
        background: "transparent",
        border: "1px solid var(--border)",
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        color: "var(--text-2)",
        cursor: submitting ? "not-allowed" : "pointer"
      }
    },
    "Cancel"
  ), /* @__PURE__ */ React.createElement(
    "button",
    {
      "data-testid": "add-doc-save",
      onClick: handleSave,
      disabled: saveDisabled,
      style: {
        padding: "8px 18px",
        background: saveDisabled ? "var(--bg-subtle)" : "var(--accent)",
        border: "1px solid " + (saveDisabled ? "var(--border)" : "var(--accent)"),
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 700,
        color: saveDisabled ? "var(--text-3)" : "#fff",
        cursor: saveDisabled ? "not-allowed" : "pointer"
      },
      title: !file ? "Select a file first" : submitting ? "Uploading\u2026" : "Upload document"
    },
    submitting ? "Uploading\u2026" : "Save"
  )));
}
const PZ_DONE_LABELS = /* @__PURE__ */ new Set(["Generated", "Exported"]);
const PZ_PENDING_LABELS = /* @__PURE__ */ new Set(["Ready for PZ", "Locked"]);
const SAD_CLEARED_KEYS = /* @__PURE__ */ new Set(["uploaded_parsed", "customs_parsed", "customs_verified"]);
const TRACK_ATTENTION = /* @__PURE__ */ new Set(["exception", "customs"]);
const DHL_FLOW_LIVE_KEYS = /* @__PURE__ */ new Set([
  "dhl_email_received",
  "reply_queued",
  "reply_sent",
  "reply_package_prepared",
  "pre_check_pending",
  "pre_check_completed"
]);
const OP_PREDICATES = {
  warehouse: {
    unknown: (r) => (r.warehouseHint || "n/a") === "n/a",
    awaiting: (r) => r.warehouseHint === "empty",
    partial_received: (r) => r.warehouseHint === "partial",
    in_warehouse: (r) => r.warehouseHint === "clean" && !PZ_DONE_LABELS.has(r.pzStatus || ""),
    reserved: (r) => r.warehouseHint === "clean" && PZ_DONE_LABELS.has(r.pzStatus || "")
  },
  sales_accounting: {
    sales_ready: (r) => (r.salesHint || "n/a") === "present",
    sales_missing: (r) => {
      const h = r.salesHint || "n/a";
      return h === "none" || h === "n/a";
    },
    wfirma_preview: (r) => (r.wfirmaHint || "n/a") === "preview_built",
    wfirma_pending: (r) => {
      const h = r.wfirmaHint || "n/a";
      return h === "none" || h === "n/a";
    },
    pz_done: (r) => PZ_DONE_LABELS.has(r.pzStatus || ""),
    pz_pending: (r) => !PZ_DONE_LABELS.has(r.pzStatus || "")
  },
  dhl_customs: {
    awaiting_customs_docs: (r) => !r.has_sad && DHL_FLOW_LIVE_KEYS.has(r._raw && r._raw.dhl_status || ""),
    sad_present: (r) => !!r.has_sad,
    sad_missing: (r) => !r.has_sad,
    customs_cleared: (r) => !!r.has_sad && SAD_CLEARED_KEYS.has(r._raw && r._raw.sad_status || ""),
    dhl_in_transit: (r) => (r._raw && r._raw.tracking_status_key || "") === "in_transit",
    dhl_delivered: (r) => (r._raw && r._raw.tracking_status_key || "") === "delivered"
  }
};
const WAREHOUSE_LIFECYCLE_KEYS = ["unknown", "awaiting", "partial_received", "in_warehouse", "reserved"];
const deriveWarehouseLifecycle = (row) => {
  for (const k of WAREHOUSE_LIFECYCLE_KEYS) {
    if (OP_PREDICATES.warehouse[k](row)) return k;
  }
  return "unknown";
};
const ATTENTION_PREDICATES = {
  warehouse: (r) => OP_PREDICATES.warehouse.awaiting(r) || OP_PREDICATES.warehouse.partial_received(r),
  sales_accounting: (r) => OP_PREDICATES.sales_accounting.sales_missing(r) || OP_PREDICATES.sales_accounting.wfirma_pending(r) || OP_PREDICATES.sales_accounting.pz_pending(r),
  dhl_customs: (r) => OP_PREDICATES.dhl_customs.awaiting_customs_docs(r) || (r._raw && r._raw.sad_status || "") === "missing" || (r._raw && r._raw.dhl_status || "") === "dhl_email_received" || TRACK_ATTENTION.has(r._raw && r._raw.tracking_status_key || "")
};
const WAREHOUSE_LIFECYCLE_LABEL = {
  unknown: "No packing list",
  awaiting: "Awaiting receipt",
  partial_received: "Partially received",
  in_warehouse: "In warehouse",
  reserved: "Reserved (PZ created)"
};
function ReadinessBanner({ domain, status, ready, message, loading, error, "data-testid": testId }) {
  if (loading) {
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": testId || `readiness-banner-${domain}`,
        style: { padding: "7px 12px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, marginBottom: 10, fontSize: 11, color: "var(--text-3)" }
      },
      "\u27F3 Loading readiness\u2026"
    );
  }
  if (error || !status) {
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": testId || `readiness-banner-${domain}`,
        style: { padding: "7px 12px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, marginBottom: 10, fontSize: 11, color: "var(--text-3)" }
      },
      "Readiness data unavailable"
    );
  }
  const isNA = status === "n/a" || status === "none";
  const bgColor = isNA ? "var(--bg-subtle)" : ready ? "var(--badge-green-bg)" : status === "partial" || status === "warnings" || status === "missing" || status === "blocked" ? "var(--badge-amber-bg)" : "var(--badge-red-bg)";
  const borderColor = isNA ? "var(--border)" : ready ? "var(--badge-green-border)" : status === "partial" || status === "warnings" || status === "missing" || status === "blocked" ? "var(--badge-amber-border)" : "var(--badge-red-border)";
  const textColor = isNA ? "var(--text-3)" : ready ? "var(--badge-green-text)" : status === "partial" || status === "warnings" || status === "missing" || status === "blocked" ? "var(--badge-amber-text)" : "var(--badge-red-text)";
  const icon = isNA ? "\u25CB" : ready ? "\u2713" : "\u26A0";
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": testId || `readiness-banner-${domain}`,
      style: { padding: "7px 12px", background: bgColor, border: `1px solid ${borderColor}`, borderRadius: 6, marginBottom: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }
    },
    /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, color: textColor } }, icon),
    /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: textColor, textTransform: "capitalize" } }, status.replace(/_/g, " ")),
    message && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: textColor, opacity: 0.85 } }, "\u2014 ", message)
  );
}
function BrokerFollowupPanel({ batchId }) {
  const [drafts, setDrafts] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");
  const [forms, setForms] = React.useState({});
  const [busy, setBusy] = React.useState({});
  const [errors, setErrors] = React.useState({});
  const [confirmFor, setConfirmFor] = React.useState(null);
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const loadDrafts = React.useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await apiFetch("/dashboard/broker-followups");
      const all = data && data.drafts || [];
      const mine = all.filter((d) => d.batch_id === batchId);
      setDrafts(mine);
    } catch (ex) {
      setLoadError(ex.message || "Failed to load broker follow-ups");
    } finally {
      setLoading(false);
    }
  }, [batchId]);
  React.useEffect(() => {
    loadDrafts();
  }, [loadDrafts]);
  const updateForm = (draftId, field, value) => {
    setForms((prev) => ({ ...prev, [draftId]: { ...prev[draftId] || {}, [field]: value } }));
  };
  const isValidTo = (toVal) => !!toVal && EMAIL_RE.test(toVal.trim());
  const sendDraft = async (draft) => {
    const form = forms[draft.draft_id] || {};
    if (!isValidTo(form.to)) return;
    setBusy((prev) => ({ ...prev, [draft.draft_id]: true }));
    setErrors((prev) => ({ ...prev, [draft.draft_id]: "" }));
    try {
      const body = { to: form.to.trim(), cc: (form.cc || "").trim() };
      if (form.from_address && form.from_address.trim()) {
        body.from_address = form.from_address.trim();
      }
      await apiFetch(`/dashboard/broker-followups/${encodeURIComponent(batchId)}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      setConfirmFor(null);
      await loadDrafts();
    } catch (ex) {
      setErrors((prev) => ({ ...prev, [draft.draft_id]: ex.message || "Send failed" }));
    } finally {
      setBusy((prev) => ({ ...prev, [draft.draft_id]: false }));
    }
  };
  return /* @__PURE__ */ React.createElement(Card, { "data-testid": "broker-followup-panel", style: { marginTop: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F4E7} Broker Follow-up"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadDrafts, disabled: loading, "data-testid": "broker-followup-refresh-btn" }, loading ? "\u27F3 Loading\u2026" : "Refresh")), /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-description", style: { fontSize: 11, color: "var(--text-3)", marginBottom: 12 } }, "Drafts created automatically when the SAD references a missing invoice or the declared CIF value diverges from the invoice total. Operator must enter the recipient before any email is queued. This panel never modifies customs, PZ, or audit values."), loadError && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-load-error", style: { marginBottom: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)", color: "var(--badge-red-text)", fontSize: 11, fontWeight: 600 } }, loadError), !loading && !loadError && drafts.length === 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-empty", style: { fontSize: 11, color: "var(--text-3)" } }, "No broker follow-up drafts for this shipment."), drafts.map((draft) => {
    const form = forms[draft.draft_id] || {};
    const sent = draft.status === "sent" || draft.status === "queued";
    const toValid = isValidTo(form.to);
    const sendDisabled = sent || !toValid || !!busy[draft.draft_id];
    const err = errors[draft.draft_id];
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        key: draft.draft_id,
        "data-testid": "broker-followup-draft",
        "data-draft-id": draft.draft_id,
        "data-draft-status": draft.status,
        style: { marginBottom: 14, padding: "10px 12px", border: "1px solid var(--border-subtle)", borderRadius: 6, background: "var(--surface-2)" }
      },
      /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text)" } }, "AWB ", draft.awb || "\u2014", " \xB7 MRN ", draft.mrn || "\u2014"), /* @__PURE__ */ React.createElement("span", { "data-testid": "broker-followup-status-badge", style: { fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700, border: "1px solid", background: sent ? "var(--badge-green-bg)" : "var(--badge-amber-bg)", color: sent ? "var(--badge-green-text)" : "var(--badge-amber-text)", borderColor: sent ? "var(--badge-green-border)" : "var(--badge-amber-border)" } }, sent ? "Sent" : "Draft")),
      draft.missing_invoices && draft.missing_invoices.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-missing-invoices", style: { fontSize: 11, color: "var(--text-2)", marginBottom: 4 } }, "Missing invoice", draft.missing_invoices.length > 1 ? "s" : "", ": ", /* @__PURE__ */ React.createElement("strong", null, draft.missing_invoices.join(", "))),
      draft.cif_gap && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-cif-gap", style: { fontSize: 11, color: "var(--text-2)", marginBottom: 8 } }, "CIF gap \u2014 invoices $", Number(draft.cif_gap.invoices).toLocaleString(), " vs SAD $", Number(draft.cif_gap.sad).toLocaleString(), " (diff $", Number(draft.cif_gap.diff).toLocaleString(), ")"),
      /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.05em", marginTop: 8, marginBottom: 4 } }, "Subject"),
      /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-subject", style: { fontSize: 11, color: "var(--text)", marginBottom: 8, padding: "6px 8px", background: "var(--surface-1)", borderRadius: 4, border: "1px solid var(--border-subtle)" } }, draft.subject),
      /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 } }, "Body preview"),
      /* @__PURE__ */ React.createElement("pre", { "data-testid": "broker-followup-body", style: { fontSize: 11, color: "var(--text)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 220, overflow: "auto", padding: "8px 10px", background: "var(--surface-1)", borderRadius: 4, border: "1px solid var(--border-subtle)", margin: 0, marginBottom: 10 } }, draft.body),
      !sent && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-form", style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("label", { style: { fontSize: 10, color: "var(--text-3)" } }, "To ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-red-text)" } }, "*"), /* @__PURE__ */ React.createElement(
        "input",
        {
          "data-testid": "broker-followup-to",
          type: "email",
          required: true,
          placeholder: "broker@example.com",
          value: form.to || "",
          onChange: (e) => updateForm(draft.draft_id, "to", e.target.value),
          style: { display: "block", width: "100%", marginTop: 2, padding: "6px 8px", fontSize: 11, border: "1px solid var(--border-subtle)", borderRadius: 4, background: "var(--surface-1)", color: "var(--text)" }
        }
      )), /* @__PURE__ */ React.createElement("label", { style: { fontSize: 10, color: "var(--text-3)" } }, "CC (optional)", /* @__PURE__ */ React.createElement(
        "input",
        {
          "data-testid": "broker-followup-cc",
          type: "text",
          placeholder: "cc@example.com",
          value: form.cc || "",
          onChange: (e) => updateForm(draft.draft_id, "cc", e.target.value),
          style: { display: "block", width: "100%", marginTop: 2, padding: "6px 8px", fontSize: 11, border: "1px solid var(--border-subtle)", borderRadius: 4, background: "var(--surface-1)", color: "var(--text)" }
        }
      )), /* @__PURE__ */ React.createElement("details", { style: { gridColumn: "1 / -1", fontSize: 10, color: "var(--text-3)" } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer" } }, "Advanced \u2014 override sender"), /* @__PURE__ */ React.createElement(
        "input",
        {
          "data-testid": "broker-followup-from",
          type: "text",
          placeholder: "from-override@estrellajewels.eu",
          value: form.from_address || "",
          onChange: (e) => updateForm(draft.draft_id, "from_address", e.target.value),
          style: { display: "block", width: "100%", marginTop: 4, padding: "6px 8px", fontSize: 11, border: "1px solid var(--border-subtle)", borderRadius: 4, background: "var(--surface-1)", color: "var(--text)" }
        }
      ))),
      err && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-error", style: { marginBottom: 8, padding: "6px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: "var(--badge-red-bg)", color: "var(--badge-red-text)", border: "1px solid var(--badge-red-border)" } }, "\u26A0 ", err),
      sent && draft.sent_to && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-sent-info", style: { fontSize: 11, color: "var(--badge-green-text)", marginBottom: 4 } }, "\u2713 Sent to ", draft.sent_to, draft.sent_at ? ` at ${draft.sent_at}` : ""),
      /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
        Btn,
        {
          "data-testid": "broker-followup-send-btn",
          small: true,
          variant: "primary",
          disabled: sendDisabled,
          style: { opacity: sendDisabled ? 0.45 : 1, cursor: sendDisabled ? "not-allowed" : "pointer" },
          onClick: () => setConfirmFor(draft)
        },
        busy[draft.draft_id] ? "\u27F3 Sending\u2026" : sent ? "Sent" : "Send\u2026"
      ), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, sent ? "Email already queued for this draft." : !toValid ? "Enter a valid recipient to enable send." : "Confirmation required before queueing."))
    );
  }), confirmFor && (() => {
    const f = forms[confirmFor.draft_id] || {};
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "broker-followup-confirm-modal",
        role: "dialog",
        "aria-modal": "true",
        style: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1e3 }
      },
      /* @__PURE__ */ React.createElement("div", { style: { background: "var(--surface-1)", border: "1px solid var(--border-subtle)", borderRadius: 8, padding: 20, width: "min(560px, 90vw)", boxShadow: "0 8px 32px rgba(0,0,0,0.25)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, marginBottom: 10, color: "var(--text)" } }, "Confirm broker follow-up email"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 4 } }, /* @__PURE__ */ React.createElement("strong", null, "Batch:"), " ", confirmFor.batch_id), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 4 } }, /* @__PURE__ */ React.createElement("strong", null, "To:"), " ", f.to), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 4 } }, /* @__PURE__ */ React.createElement("strong", null, "CC:"), " ", f.cc || "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("strong", null, "Subject:"), " ", confirmFor.subject), /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-followup-confirm-warning", style: { marginBottom: 14, padding: "8px 10px", borderRadius: 4, background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", color: "var(--badge-amber-text)", fontSize: 11 } }, "\u26A0 This will queue an email. It will not modify customs/PZ values."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", gap: 8 } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: () => setConfirmFor(null), "data-testid": "broker-followup-confirm-cancel" }, "Cancel"), /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          variant: "primary",
          onClick: () => sendDraft(confirmFor),
          disabled: !!busy[confirmFor.draft_id],
          "data-testid": "broker-followup-confirm-send"
        },
        busy[confirmFor.draft_id] ? "\u27F3 Sending\u2026" : "Confirm & queue email"
      )))
    );
  })()));
}
function BrokerReplyAnalyzerPanel() {
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState(null);
  const analyze = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const data = await apiFetch("/dashboard/broker-reply/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      setResult(data);
    } catch (ex) {
      setError(ex.message || "Analyze failed");
    } finally {
      setBusy(false);
    }
  };
  const clear = () => {
    setText("");
    setResult(null);
    setError("");
  };
  const caseColor = (c) => c === "A" ? "var(--badge-green-text)" : c === "B" ? "var(--badge-amber-text)" : c === "C" ? "var(--badge-amber-text)" : c === "D" ? "var(--text-2)" : c === "E" ? "var(--badge-red-text)" : "var(--text-3)";
  return /* @__PURE__ */ React.createElement(Card, { "data-testid": "broker-reply-analyzer-panel", style: { marginTop: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F4CB} Paste Broker Reply")), /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-analyzer-description", style: { fontSize: 11, color: "var(--text-3)", marginBottom: 10 } }, "Paste the broker's email body to get a quick case classification (A\u2013E) and recommended next action. Read-only helper \u2014 no email is sent, no audit field is changed."), /* @__PURE__ */ React.createElement(
    "textarea",
    {
      "data-testid": "broker-reply-input",
      value: text,
      onChange: (e) => setText(e.target.value),
      placeholder: "Paste broker reply text here\u2026",
      rows: 8,
      style: { width: "100%", padding: "8px 10px", fontSize: 11, fontFamily: "inherit", border: "1px solid var(--border-subtle)", borderRadius: 4, background: "var(--surface-1)", color: "var(--text)", resize: "vertical" }
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, marginTop: 8 } }, /* @__PURE__ */ React.createElement(
    Btn,
    {
      "data-testid": "broker-reply-analyze-btn",
      small: true,
      variant: "primary",
      disabled: busy || !text.trim(),
      title: busy ? "Analyzing reply\u2026" : !text.trim() ? "Paste broker reply text above first" : "Analyze the pasted broker reply",
      style: { opacity: busy || !text.trim() ? 0.45 : 1, cursor: busy || !text.trim() ? "not-allowed" : "pointer" },
      onClick: analyze
    },
    busy ? "\u27F3 Analyzing\u2026" : "Analyze"
  ), /* @__PURE__ */ React.createElement(
    Btn,
    {
      "data-testid": "broker-reply-clear-btn",
      small: true,
      variant: "outline",
      disabled: busy || !text && !result && !error,
      title: busy ? "Analyze in progress \u2014 wait to clear" : !text && !result && !error ? "Nothing to clear" : "Clear the reply text and result",
      onClick: clear
    },
    "Clear"
  )), error && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-error", style: { marginTop: 10, padding: "8px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: "var(--badge-red-bg)", color: "var(--badge-red-text)", border: "1px solid var(--badge-red-border)" } }, "\u26A0 ", error), result && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result", style: { marginTop: 12, padding: "10px 12px", border: "1px solid var(--border-subtle)", borderRadius: 6, background: "var(--surface-2)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, "Case"), /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result-case", style: { fontSize: 16, fontWeight: 800, color: caseColor(result.case) } }, result.case || "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, "\xB7"), /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result-confidence", style: { fontSize: 11, fontWeight: 600, color: "var(--text-2)" } }, "Confidence: ", result.confidence)), result.extracted && (result.extracted.invoice_ids || []).length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result-invoices", style: { fontSize: 11, color: "var(--text-2)", marginBottom: 4 } }, "Invoice IDs: ", /* @__PURE__ */ React.createElement("strong", null, result.extracted.invoice_ids.join(", "))), result.extracted && (result.extracted.usd_amounts || []).length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result-amounts", style: { fontSize: 11, color: "var(--text-2)", marginBottom: 8 } }, "USD amounts: ", /* @__PURE__ */ React.createElement("strong", null, result.extracted.usd_amounts.join(", "))), result.recommended_action && /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result-recommendation", style: { marginTop: 8, padding: "8px 10px", borderRadius: 4, background: "var(--surface-1)", border: "1px solid var(--border-subtle)", fontSize: 11, color: "var(--text)", lineHeight: 1.4 } }, result.recommended_action), /* @__PURE__ */ React.createElement("div", { "data-testid": "broker-reply-result-safety-note", style: { fontSize: 10, color: "var(--text-3)", marginTop: 8 } }, "Suggestion only \u2014 does not run PZ, change customs values, send email, or apply overrides."))));
}
function MissingFunctionsMatrix() {
  const BADGE_STYLES = {
    Complete: { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" },
    Partial: { background: "#dbeafe", color: "#1e40af", border: "1px solid #bfdbfe" },
    Parked: { background: "#f3f4f6", color: "#374151", border: "1px solid #d1d5db" },
    "Missing UI": { background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a" },
    Risky: { background: "#fee2e2", color: "#991b1b", border: "1px solid #fecaca" },
    Superseded: { background: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe" },
    Missing: { background: "#fef9c3", color: "#713f12", border: "1px solid #fef08a" }
  };
  const Badge2 = ({ label }) => /* @__PURE__ */ React.createElement("span", { style: {
    ...BADGE_STYLES[label] || BADGE_STYLES["Parked"],
    display: "inline-block",
    padding: "1px 7px",
    borderRadius: 10,
    fontSize: 10,
    fontWeight: 700,
    whiteSpace: "nowrap"
  } }, label);
  const ROWS = [
    {
      module: "Proforma \u2192 Invoice converter",
      backend: "Parked",
      ui: "Missing UI",
      tests: "Parked",
      flow: "Parked",
      action: "Define spec; backend skeleton in routes_proposals"
    },
    {
      module: "PZ Chrome AutoFill preview",
      backend: "Complete",
      ui: "Partial",
      tests: "Partial",
      flow: "Partial",
      action: "Accessible from PZ / Accounting tab; no immediate action"
    },
    {
      module: "Packing list upload",
      backend: "Complete",
      ui: "Partial",
      tests: "Partial",
      flow: "Partial",
      action: "Verify packing list \u2192 warehouse scan flow end-to-end"
    },
    {
      module: "Barcode / label print",
      backend: "Parked",
      ui: "Parked",
      tests: "Missing",
      flow: "Parked",
      action: "Parked \u2014 no timeline; post-Phase 2"
    },
    {
      module: "DHL documents received",
      backend: "Complete",
      ui: "Partial",
      tests: "Partial",
      flow: "Risky",
      action: "Add document receipt confirmation step in DHL / Customs tab"
    },
    {
      module: "Agency documents received",
      backend: "Complete",
      ui: "Partial",
      tests: "Partial",
      flow: "Risky",
      action: "Run end-to-end SAD / PZC import test with real agency reply"
    },
    {
      module: "Service invoice receipt",
      backend: "Partial",
      ui: "Missing UI",
      tests: "Missing",
      flow: "Missing UI",
      action: "Add service invoice card \u2014 DHL + agency invoices tracked separately"
    },
    {
      module: "Shipment closure",
      backend: "Partial",
      ui: "Missing UI",
      tests: "Missing",
      flow: "Risky",
      action: "Add closure confirmation UI with readiness gate before any write"
    },
    {
      module: "wFirma create guard",
      backend: "Complete",
      ui: "Partial",
      tests: "Partial",
      flow: "Risky",
      action: "Verify guard prevents double API call; add idempotency check"
    },
    {
      module: "Old batch flow cleanup",
      backend: "Partial",
      ui: "Parked",
      tests: "Partial",
      flow: "Parked",
      action: "Admin cleanup tool; not operator-facing \u2014 low priority"
    }
  ];
  const thStyle = {
    textAlign: "left",
    padding: "6px 10px",
    borderBottom: "2px solid var(--border)",
    fontSize: 10,
    fontWeight: 700,
    color: "var(--text-3)",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    whiteSpace: "nowrap"
  };
  const tdStyle = {
    padding: "7px 10px",
    borderBottom: "1px solid var(--border)",
    fontSize: 11,
    verticalAlign: "middle"
  };
  return /* @__PURE__ */ React.createElement(Card, { "data-testid": "missing-functions-matrix", style: { marginBottom: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px 6px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u229F Missing / Parked Modules"), /* @__PURE__ */ React.createElement("span", { style: {
    fontSize: 10,
    padding: "2px 8px",
    borderRadius: 10,
    background: "#f3f4f6",
    color: "#374151",
    border: "1px solid #d1d5db",
    fontWeight: 600
  } }, "Phase 2 status")), /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        fontSize: 11,
        color: "#6b7280",
        marginBottom: 12,
        padding: "6px 10px",
        background: "#f9fafb",
        borderRadius: 5,
        border: "1px solid #e5e7eb"
      },
      "data-testid": "missing-functions-matrix-readonly-warning"
    },
    "\u26A0 This matrix is read-only and does not trigger actions."
  )), /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--surface-2)" } }, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Module"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Backend"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "UI"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Tests"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Operator flow"), /* @__PURE__ */ React.createElement("th", { style: { ...thStyle, minWidth: 220 } }, "Recommended next action"))), /* @__PURE__ */ React.createElement("tbody", null, ROWS.map((row, i) => /* @__PURE__ */ React.createElement("tr", { key: i, style: { background: i % 2 === 0 ? "transparent" : "var(--surface-2, #fafafa)" } }, /* @__PURE__ */ React.createElement(
    "td",
    {
      style: { ...tdStyle, fontWeight: 600, color: "var(--text)" },
      "data-testid": `mfm-row-${i}`
    },
    row.module
  ), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, /* @__PURE__ */ React.createElement(Badge2, { label: row.backend })), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, /* @__PURE__ */ React.createElement(Badge2, { label: row.ui })), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, /* @__PURE__ */ React.createElement(Badge2, { label: row.tests })), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, /* @__PURE__ */ React.createElement(Badge2, { label: row.flow })), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, color: "var(--text-2)", maxWidth: 280 } }, row.action)))))));
}
function BatchControlCenter({
  batchId,
  audit,
  batchReadiness,
  batchReadinessLoading,
  batchReadinessError,
  dhlReadiness,
  onTabSwitch
}) {
  if (!batchId) return null;
  const br = batchReadiness;
  const dr = dhlReadiness;
  const aud = audit || {};
  const hasSad = !!(aud.sad_file || aud.sad_imported_at);
  const hasPz = !!(aud.pz_pdf_filename || aud.pz_generated_at);
  const hasDhlContact = !!(aud.dhl_email_sent_at || dr && dr.dhl_status && dr.dhl_status !== "awaiting_start");
  const hasDhlReply = !!(dr && ["dhl_replied", "agency_forwarded", "customs_cleared"].includes(dr.dhl_status));
  const hasDsk = !!(dr && dr.dsk_docs_received) || !!(aud.dsk_uploaded_at || dr && dr.dhl_status && ["dhl_replied", "agency_forwarded", "customs_cleared"].includes(dr.dhl_status));
  const hasAgency = !!(dr && dr.agency_forwarded) || !!(dr && dr.dhl_status && ["agency_forwarded", "customs_cleared"].includes(dr.dhl_status));
  const hasSadPzc = !!(dr && dr.sad_received) || !!(dr && dr.dhl_status === "customs_cleared");
  const whReady = br && br.warehouse && br.warehouse.ready;
  const salesReady = br && br.sales && br.sales.ready;
  const wfirmaReady = br && br.wfirma && (br.wfirma.status === "ready" || br.wfirma.status === "created");
  const allReady = br && br.overall && br.overall.ready_for_closure;
  const nextStep = br && br.overall && br.overall.next_step;
  const blockedDomains = br && br.overall && br.overall.blocked_domains || [];
  const steps = [
    { label: "Batch created", done: !!batchId, tab: null },
    { label: "SAD / customs doc uploaded", done: hasSad, tab: "DHL / Customs" },
    { label: "PZ document generated", done: hasPz, tab: "PZ / Accounting" },
    { label: "DHL contacted", done: hasDhlContact, tab: "DHL / Customs" },
    { label: "DHL reply received", done: hasDhlReply, tab: "DHL / Customs" },
    { label: "DSK docs received", done: hasDsk, tab: "DHL / Customs" },
    { label: "Forwarded to agency", done: hasAgency, tab: "DHL / Customs" },
    { label: "SAD / PZC from agency", done: hasSadPzc, tab: "DHL / Customs" },
    { label: "Warehouse scanned", done: whReady, tab: "Warehouse" },
    { label: "Sales linked", done: salesReady, tab: "Sales" },
    { label: "wFirma reservation", done: wfirmaReady, tab: "PZ / Accounting" },
    { label: "Customs cleared", done: hasSadPzc && hasDsk, tab: "DHL / Customs" },
    { label: "Ready for closure", done: allReady, tab: null }
  ];
  const activeStepIdx = steps.findIndex((s) => !s.done);
  const cardStyle = { marginBottom: 16, padding: 16 };
  const stepRowStyle = { display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 12 };
  const pillStyle = (blocked) => ({
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 12,
    fontSize: 10,
    fontWeight: 600,
    marginLeft: 4,
    background: blocked ? "#fef2f2" : "#f0fdf4",
    color: blocked ? "#991b1b" : "#166534"
  });
  return /* @__PURE__ */ React.createElement(Card, { "data-testid": "batch-control-center", style: cardStyle }, /* @__PURE__ */ React.createElement(
    SectionHeader,
    {
      icon: "\u229E",
      title: "Batch Control Center",
      subtitle: allReady ? "All domains ready \u2014 batch can be closed" : nextStep || "Checking readiness\u2026"
    }
  ), batchReadinessLoading && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-3)", padding: "8px 0" } }, "\u27F3 Loading readiness\u2026"), batchReadinessError && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "#991b1b", padding: "8px 0" } }, "\u26A0 ", batchReadinessError), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 12 } }, steps.map((step, i) => {
    const isCurrent = i === activeStepIdx;
    const icon = step.done ? "\u2705" : isCurrent ? "\u{1F535}" : "\u2B1C";
    return /* @__PURE__ */ React.createElement("div", { key: i, style: { ...stepRowStyle, fontWeight: isCurrent ? 700 : 400 } }, /* @__PURE__ */ React.createElement("span", null, icon), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, color: step.done ? "var(--text-2)" : isCurrent ? "var(--text-1)" : "var(--text-3)" } }, step.label), step.tab && isCurrent && /* @__PURE__ */ React.createElement(
      "button",
      {
        style: { fontSize: 10, padding: "2px 8px", cursor: "pointer", border: "1px solid var(--border)", borderRadius: 4, background: "var(--surface-2)", color: "var(--text-1)" },
        onClick: () => onTabSwitch && onTabSwitch(step.tab)
      },
      "Go \u2192"
    ));
  })), blockedDomains.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: "var(--text-2)" } }, "Blocked: "), blockedDomains.map((d) => /* @__PURE__ */ React.createElement("span", { key: d, style: pillStyle(true) }, d))), nextStep && !allReady && /* @__PURE__ */ React.createElement("div", { style: { background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#92400e" } }, /* @__PURE__ */ React.createElement("strong", null, "Next: "), nextStep), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 12, padding: "8px 12px", background: "var(--surface-2)", borderRadius: 6, fontSize: 11, color: "var(--text-3)" } }, /* @__PURE__ */ React.createElement("strong", null, "Parked modules:"), " Proforma converter \xB7 Barcode / label print"));
}
function DecisionBanner({ decisionData, decisionLoading, fallbackStep }) {
  if (decisionLoading) return null;
  const action = decisionData && decisionData.primary_action;
  const displayText = action || fallbackStep;
  if (!displayText) return null;
  const isDecision = !!action;
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "decision-banner",
      style: {
        fontSize: 11,
        padding: "7px 10px",
        borderRadius: 5,
        border: `1px solid ${isDecision ? "var(--badge-blue-border, var(--border))" : "var(--border)"}`,
        background: isDecision ? "var(--badge-blue-bg, var(--bg-subtle))" : "var(--bg-subtle)",
        color: isDecision ? "var(--badge-blue-text, var(--text-2))" : "var(--text-2)"
      }
    },
    /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, isDecision ? "\u25B6 Next Action: " : "Next: "),
    /* @__PURE__ */ React.createElement("span", { "data-testid": "overall-next-step", "data-decision-action": "true" }, displayText)
  );
}
function OverallReadinessCard({ batchReadiness, loading, error, decisionData, decisionLoading }) {
  if (loading) {
    return /* @__PURE__ */ React.createElement(Card, { "data-testid": "overall-readiness-card" }, /* @__PURE__ */ React.createElement("div", { style: { padding: 16, fontSize: 12, color: "var(--text-3)" } }, "\u27F3 Loading readiness\u2026"));
  }
  if (error || !batchReadiness) {
    return /* @__PURE__ */ React.createElement(Card, { "data-testid": "overall-readiness-card" }, /* @__PURE__ */ React.createElement("div", { style: { padding: 16, fontSize: 12, color: "var(--text-3)" } }, error || "Readiness data unavailable"));
  }
  const overall = batchReadiness.overall || {};
  const ready = overall.ready_for_closure;
  const blocked = overall.blocked_domains || [];
  const nextStep = overall.next_step || "";
  const DOMAIN_ICONS = { warehouse: "\u{1F4E6}", sales: "\u{1F6D2}", wfirma: "\u2197", dhl: "\u2708" };
  const DOMAINS = ["warehouse", "sales", "wfirma", "dhl"];
  return /* @__PURE__ */ React.createElement(Card, { "data-testid": "overall-readiness-card" }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 12 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F50D} Batch Readiness"), /* @__PURE__ */ React.createElement("span", { style: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 4,
    background: ready ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
    color: ready ? "var(--badge-green-text)" : "var(--badge-amber-text)",
    border: `1px solid ${ready ? "var(--badge-green-border)" : "var(--badge-amber-border)"}`
  } }, ready ? "Ready for closure" : `${blocked.length} domain(s) blocked`)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 } }, DOMAINS.map((d) => {
    const dom = batchReadiness[d] || {};
    const isReady = dom.ready;
    const st = dom.status || "n/a";
    const isNA = st === "n/a" || st === "none";
    return /* @__PURE__ */ React.createElement("div", { key: d, style: {
      display: "flex",
      alignItems: "center",
      gap: 5,
      padding: "4px 10px",
      borderRadius: 5,
      fontSize: 11,
      fontWeight: 600,
      background: isNA ? "var(--bg-2)" : isReady ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
      color: isNA ? "var(--text-3)" : isReady ? "var(--badge-green-text)" : "var(--badge-amber-text)",
      border: `1px solid ${isNA ? "var(--border)" : isReady ? "var(--badge-green-border)" : "var(--badge-amber-border)"}`
    }, title: dom.message || "" }, /* @__PURE__ */ React.createElement("span", null, DOMAIN_ICONS[d] || "\u2022"), /* @__PURE__ */ React.createElement("span", { style: { textTransform: "capitalize" } }, d), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 400 } }, "\u2014 ", st.replace(/_/g, " ")));
  })), /* @__PURE__ */ React.createElement(DecisionBanner, { decisionData, decisionLoading, fallbackStep: nextStep })));
}
const DETAIL_TABS = ["Overview", "Documents", "DHL / Customs", "Warehouse", "Sales", "PZ / Accounting", "Timeline", "Intelligence", "Proposals"];
const WORKFLOW_STAGES = [
  { id: "intake", num: 1, label: "Intake" },
  { id: "precheck", num: 2, label: "Pre-check" },
  { id: "reply", num: 3, label: "DHL Reply" },
  { id: "sad", num: 4, label: "SAD / ZC429" },
  { id: "verified", num: 5, label: "Verified" },
  { id: "pz", num: 6, label: "PZ Generated" },
  { id: "wfirma", num: 7, label: "wFirma Booked" }
];
function WorkflowStrip({ audit }) {
  if (!audit) return null;
  const cd = audit.customs_declaration || {};
  const timeline = Array.isArray(audit.timeline) ? audit.timeline : [];
  const wfExport = audit.wfirma_export || {};
  const has = (event) => timeline.some((e) => e && e.event === event);
  const sadParsed = !!(cd.mrn || cd.duty_a00_pln != null || cd.sad_customs_rate || cd.exchange_rate);
  const sadVerified = !!cd.verification_passed;
  const sad = audit.sad_status || (sadVerified ? "customs_verified" : sadParsed ? "customs_parsed" : has("sad_uploaded") ? "uploaded_parsed" : "missing");
  const dhl = audit.dhl_status || (has("dsk_transfer_sent") ? "reply_sent" : has("dhl_email_received") ? "dhl_email_received" : has("dhl_precheck_completed") ? "pre_check_completed" : "");
  const pzExported = !!(wfExport.wfirma_pz_doc_id || "").trim() || has("wfirma_pz_created");
  const pz = audit.pz_status || (pzExported ? "exported" : has("pz_generated") ? "generated" : "");
  const stageState = (id) => {
    if (id === "intake") return "done";
    if (id === "precheck") return dhl === "pre_check_completed" || dhl === "reply_sent" || dhl === "reply_queued" ? "done" : dhl ? "active" : "pending";
    if (id === "reply") return dhl === "reply_sent" ? "done" : dhl === "reply_queued" || dhl === "reply_package_prepared" || dhl === "dhl_email_received" ? "active" : "pending";
    if (id === "sad") return sad === "customs_verified" || sad === "uploaded_parsed" || sad === "customs_parsed" ? "done" : dhl === "reply_sent" && sad !== "missing" ? "active" : "pending";
    if (id === "verified") return sad === "customs_verified" ? "done" : sad === "customs_parsed" || sad === "uploaded_parsed" ? "active" : "pending";
    if (id === "pz") return pz === "generated" || pz === "exported" ? "done" : sad === "customs_verified" ? "active" : "pending";
    if (id === "wfirma") return pz === "exported" ? "done" : pz === "generated" ? "active" : "pending";
    return "pending";
  };
  const colors = {
    done: { numBg: "#22A06B", numBorder: "#22A06B", numText: "#fff", labelColor: "#186838" },
    active: { numBg: "var(--accent-subtle)", numBorder: "var(--accent-border)", numText: "var(--accent)", labelColor: "var(--accent)" },
    pending: { numBg: "var(--card)", numBorder: "var(--border)", numText: "var(--text-3)", labelColor: "var(--text-3)" }
  };
  return /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 32px", background: "var(--card)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 0, flexShrink: 0, overflowX: "auto" } }, WORKFLOW_STAGES.map((stage, i) => {
    const s = stageState(stage.id);
    const c = colors[s];
    return /* @__PURE__ */ React.createElement(React.Fragment, { key: stage.id }, i > 0 && /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 12, height: 1, background: s === "done" ? "#22A06B" : "var(--border)", opacity: s === "done" ? 0.5 : 1 } }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", alignItems: "center", gap: 4, flexShrink: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { width: 26, height: 26, borderRadius: "50%", background: c.numBg, border: `2px solid ${c.numBorder}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: c.numText } }, s === "done" ? "\u2713" : stage.num), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 500, color: c.labelColor, whiteSpace: "nowrap" } }, stage.label)));
  }));
}
function SelfclearanceStatePill({ batchId }) {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState("");
  React.useEffect(() => {
    let cancelled = false;
    if (!batchId) return;
    (async () => {
      try {
        const r = await fetch(`/api/v1/dhl/selfclearance/state/${encodeURIComponent(batchId)}`, {
          credentials: "include"
        });
        if (!r.ok) {
          if (!cancelled) setErr(`HTTP ${r.status}`);
          return;
        }
        const j = await r.json();
        if (!cancelled) setData(j);
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [batchId]);
  if (err) return null;
  if (!data) return null;
  if (data.in_scope === false) return null;
  const state = data.state || "n/a";
  const inScope = !!data.in_scope;
  const shadow = data.p2_dispatch && data.p2_dispatch.shadow;
  const colorByState = {
    "awaiting_preemptive_send": "#6b7280",
    "awaiting_poland_arrival": "#2563eb",
    "followup_active": "#2563eb",
    "dhl_requested_clarification": "#d97706",
    "clarification_sent": "#2563eb",
    "awaiting_sad": "#2563eb",
    "sad_received": "#16a34a",
    "pz_unlocked": "#16a34a",
    "shipment_closed": "#16a34a",
    "dispatch_failed": "#dc2626",
    "scope_gate_violated": "#dc2626",
    "operator_override_active": "#d97706",
    "pz_failed": "#dc2626",
    "n/a": "#9ca3af"
  };
  const color = colorByState[state] || "#6b7280";
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "selfclearance-state-pill",
      style: {
        margin: "8px 0",
        padding: "8px 12px",
        border: "1px solid var(--border-subtle, #e5e7eb)",
        borderRadius: 6,
        background: "var(--surface, #fff)",
        display: "inline-flex",
        alignItems: "center",
        gap: 10,
        fontSize: 13
      },
      title: inScope ? `DHL self-clearance (Path A) state \u2014 operator controls on Windows Atlas` : `Not on Path A self-clearance \u2014 pill informational only`
    },
    /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600 } }, "Self-clearance:"),
    /* @__PURE__ */ React.createElement(
      "span",
      {
        style: {
          display: "inline-block",
          padding: "2px 8px",
          borderRadius: 12,
          background: color,
          color: "#fff",
          fontFamily: "monospace",
          fontSize: 12
        }
      },
      state
    ),
    inScope && shadow === true && /* @__PURE__ */ React.createElement("span", { style: { color: "#6b7280", fontSize: 12 } }, "(shadow)"),
    inScope && shadow === false && /* @__PURE__ */ React.createElement("span", { style: { color: "#16a34a", fontSize: 12 } }, "(live)"),
    !inScope && /* @__PURE__ */ React.createElement("span", { style: { color: "#9ca3af", fontSize: 12 } }, "(not Path A)")
  );
}
function ContractorResolutionRoleCard({
  batchId,
  role,
  label,
  suggestedSource,
  onToast
}) {
  const [verdict, setVerdict] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [chosenId, setChosenId] = React.useState("");
  React.useEffect(() => {
    if (!batchId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/contractor-resolution/${role}`).then((d) => {
      if (alive) {
        setVerdict(d);
        setChosenId(d.matched_master_id ? String(d.matched_master_id) : "");
      }
    }).catch((e) => {
      if (!alive) return;
      if (/\b404\b/.test(String(e.message || ""))) {
        setVerdict(null);
      } else {
        setError(e.message || String(e));
      }
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [batchId, role]);
  const reload = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/contractor-resolution/${role}`);
      setVerdict(d);
      setChosenId(d.matched_master_id ? String(d.matched_master_id) : "");
    } catch (e) {
      if (/\b404\b/.test(String(e.message || ""))) setVerdict(null);
      else setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [batchId, role]);
  const resolveNow = async () => {
    const parsed_name = window.prompt(
      `Parsed ${label} name (from packing list / filename):`,
      suggestedSource && suggestedSource[role] || ""
    );
    if (!parsed_name) return;
    const parsed_country = window.prompt(`Parsed country (ISO alpha-2, optional):`, "") || "";
    setBusy(true);
    setError(null);
    try {
      const body = { role, parsed_name, parsed_country };
      const r = await apiFetch(
        `/api/v1/packing/${encodeURIComponent(batchId)}/contractor-resolution`,
        { method: "POST", headers: { "X-Operator-User": "dashboard" }, body: JSON.stringify(body) }
      );
      setVerdict(r);
      setChosenId(r.matched_master_id ? String(r.matched_master_id) : "");
      onToast && onToast(`${label} resolver: ${r.status} (tier ${r.tier})`, "success");
    } catch (e) {
      setError(e.message || String(e));
      onToast && onToast(`${label} resolve failed: ${e.message || e}`, "error");
    } finally {
      setBusy(false);
    }
  };
  const confirmOrOverride = async () => {
    if (!verdict) return;
    setBusy(true);
    setError(null);
    try {
      const body = { role };
      const currentMatchId = verdict.matched_master_id ? String(verdict.matched_master_id) : "";
      if (chosenId && chosenId !== currentMatchId) {
        const cand = (verdict.candidates || []).find((c) => String(c.master_id) === chosenId);
        if (cand) {
          body.matched_master_type = cand.master_type;
          body.matched_master_id = cand.master_id;
          body.matched_wfirma_id = cand.wfirma_id;
        }
      }
      const r = await apiFetch(
        `/api/v1/packing/${encodeURIComponent(batchId)}/contractor-resolution/confirm`,
        { method: "POST", headers: { "X-Operator-User": "dashboard" }, body: JSON.stringify(body) }
      );
      setVerdict(r);
      onToast && onToast(`${label} ${r.status}` + (r.operator_override ? " (override)" : ""), "success");
    } catch (e) {
      setError(e.message || String(e));
      onToast && onToast(`${label} confirm failed: ${e.message || e}`, "error");
    } finally {
      setBusy(false);
    }
  };
  const statusStyle = (s) => {
    const map = {
      auto: { bg: "var(--badge-blue-bg)", fg: "var(--badge-blue-text)", brd: "var(--badge-blue-border)" },
      unresolved: { bg: "var(--badge-red-bg)", fg: "var(--badge-red-text)", brd: "var(--badge-red-border)" },
      confirmed: { bg: "var(--badge-green-bg)", fg: "var(--badge-green-text)", brd: "var(--badge-green-border)" },
      overridden: { bg: "var(--badge-amber-bg)", fg: "var(--badge-amber-text)", brd: "var(--badge-amber-border)" }
    };
    return map[s] || { bg: "var(--badge-neutral-bg)", fg: "var(--badge-neutral-text)", brd: "var(--badge-neutral-border)" };
  };
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": `contractor-resolution-${role}-card`,
      "data-status": verdict ? verdict.status : "none",
      style: {
        padding: 12,
        border: "1px solid var(--border)",
        borderRadius: 8,
        background: "var(--card)",
        marginBottom: 10
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, fontSize: 12, fontWeight: 700, color: "var(--text)" } }, label, " role"), verdict && (() => {
      const st = statusStyle(verdict.status);
      return /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": `contractor-resolution-${role}-status`,
          style: {
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 8px",
            borderRadius: 10,
            background: st.bg,
            color: st.fg,
            border: `1px solid ${st.brd}`,
            letterSpacing: "0.04em",
            textTransform: "uppercase"
          }
        },
        verdict.status
      );
    })(), verdict && /* @__PURE__ */ React.createElement(
      "span",
      {
        "data-testid": `contractor-resolution-${role}-tier`,
        style: { fontSize: 10, color: "var(--text-3)" }
      },
      "tier ",
      verdict.tier,
      " \xB7 conf ",
      Number(verdict.confidence || 0).toFixed(2)
    )),
    loading && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `contractor-resolution-${role}-loading`,
        style: { padding: 8, fontSize: 11, color: "var(--text-3)" }
      },
      "Loading\u2026"
    ),
    error && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `contractor-resolution-${role}-error`,
        style: {
          padding: 8,
          fontSize: 11,
          color: "var(--badge-red-text)",
          background: "var(--badge-red-bg)",
          border: "1px solid var(--badge-red-border)",
          borderRadius: 6
        }
      },
      error
    ),
    !loading && !verdict && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `contractor-resolution-${role}-empty`,
        style: { fontSize: 11, color: "var(--text-3)", marginBottom: 8 }
      },
      "No resolution stored yet. Click ",
      /* @__PURE__ */ React.createElement("strong", null, "Resolve"),
      " to match the packing list ",
      label.toLowerCase(),
      " against the local master cache."
    ),
    verdict && /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11, color: "var(--text-2)", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.04em" } }, "parsed"), /* @__PURE__ */ React.createElement("div", { "data-testid": `contractor-resolution-${role}-parsed-name`, style: { fontWeight: 600 } }, verdict.parsed_name || "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, [verdict.parsed_country, verdict.parsed_tax_id].filter(Boolean).join(" \xB7 ") || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.04em" } }, "matched"), /* @__PURE__ */ React.createElement("div", { "data-testid": `contractor-resolution-${role}-matched`, style: { fontWeight: 600 } }, (verdict.candidates || []).find((c) => String(c.master_id) === String(verdict.matched_master_id))?.display_name || (verdict.matched_master_id ? `#${verdict.matched_master_id}` : "\u2014")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, verdict.matched_master_type || "\u2014", verdict.matched_wfirma_id && /* @__PURE__ */ React.createElement("span", null, " \xB7 wFirma ", verdict.matched_wfirma_id)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "reason: ", verdict.reason || "\u2014"))),
    verdict && (verdict.candidates || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: {
      fontSize: 9,
      color: "var(--text-3)",
      textTransform: "uppercase",
      letterSpacing: "0.04em",
      marginBottom: 4
    } }, "Override (pick from candidates)"), /* @__PURE__ */ React.createElement(
      "select",
      {
        "data-testid": `contractor-resolution-${role}-override`,
        value: chosenId,
        onChange: (e) => setChosenId(e.target.value),
        style: {
          width: "100%",
          padding: "5px 8px",
          fontSize: 11,
          fontFamily: "inherit",
          background: "var(--bg-subtle)",
          color: "var(--text)",
          border: "1px solid var(--border)",
          borderRadius: 4
        }
      },
      /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 Keep automatic match \u2014"),
      (verdict.candidates || []).map((c, i) => /* @__PURE__ */ React.createElement("option", { key: c.master_id || i, value: String(c.master_id || "") }, c.display_name || `#${c.master_id}`, " \xB7 ", c.country || "?", c.score != null ? ` \xB7 score ${c.score}` : "", c.wfirma_id ? ` \xB7 wFirma ${c.wfirma_id}` : ""))
    )),
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": `contractor-resolution-${role}-resolve-btn`,
        disabled: busy || loading || !batchId,
        onClick: resolveNow,
        style: {
          padding: "5px 10px",
          fontSize: 11,
          fontWeight: 600,
          background: "var(--accent)",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          cursor: busy || loading || !batchId ? "not-allowed" : "pointer",
          opacity: busy || loading || !batchId ? 0.5 : 1,
          fontFamily: "inherit"
        }
      },
      busy ? "\u2026" : "Resolve"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": `contractor-resolution-${role}-confirm-btn`,
        disabled: busy || loading || !verdict,
        onClick: confirmOrOverride,
        title: !verdict ? "No resolution to confirm yet" : "",
        style: {
          padding: "5px 10px",
          fontSize: 11,
          fontWeight: 600,
          background: "var(--bg-subtle)",
          color: "var(--text)",
          border: "1px solid var(--accent)",
          borderRadius: 6,
          cursor: busy || loading || !verdict ? "not-allowed" : "pointer",
          opacity: busy || loading || !verdict ? 0.5 : 1,
          fontFamily: "inherit"
        }
      },
      chosenId && verdict && chosenId !== (verdict.matched_master_id ? String(verdict.matched_master_id) : "") ? "Override" : "Use this match"
    ), verdict && verdict.matched_master_id && /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": `contractor-resolution-${role}-open-master-btn`,
        onClick: () => {
          const tip = role === "client" ? "Open Master Data \u2192 Client Master \u2192 row id " + verdict.matched_master_id : "Open Master Data \u2192 Suppliers \u2192 row id " + verdict.matched_master_id;
          onToast && onToast(tip, "info");
        },
        style: {
          padding: "5px 10px",
          fontSize: 11,
          background: "var(--card)",
          color: "var(--text-2)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          cursor: "pointer",
          fontFamily: "inherit"
        }
      },
      "Open ",
      role === "client" ? "Client Master" : "Supplier Master"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": `contractor-resolution-${role}-create-new-btn`,
        disabled: true,
        title: `To add a new ${role === "client" ? "client" : "supplier"}: create the contractor record in wFirma (Contractors menu \u2192 New contractor), then click Resolve above to find it by name.`,
        style: {
          padding: "5px 10px",
          fontSize: 11,
          background: "var(--card)",
          color: "var(--text-3)",
          border: "1px dashed var(--border)",
          borderRadius: 6,
          cursor: "not-allowed",
          fontFamily: "inherit",
          opacity: 0.6
        }
      },
      "+ Create new (disabled \u2014 create in wFirma first)"
    )),
    verdict && verdict.status === "unresolved" && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `contractor-resolution-${role}-unresolved-warning`,
        style: {
          marginTop: 8,
          padding: "6px 10px",
          fontSize: 11,
          background: "var(--badge-amber-bg)",
          color: "var(--badge-amber-text)",
          border: "1px solid var(--badge-amber-border)",
          borderRadius: 6
        }
      },
      "Operator must pick a candidate (or create the master row separately) before proforma / PZ can use this ",
      label.toLowerCase(),
      "."
    )
  );
}
function ContractorResolutionPanel({ batchId, packingInfo }) {
  const suggested = React.useMemo(() => {
    const docs = packingInfo && packingInfo.documents || [];
    const first = docs[0] || {};
    return { client: first.suggested_client_name || "", supplier: "" };
  }, [packingInfo]);
  if (!batchId) return null;
  return /* @__PURE__ */ React.createElement(Card, { "data-testid": "contractor-resolution-panel", style: { marginTop: 20 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F9ED} Contractor resolution"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, "Match the packing-list contractors against the local Client / Supplier Master cache. Read-only against wFirma. No automatic create."))), /* @__PURE__ */ React.createElement(
    ContractorResolutionRoleCard,
    {
      batchId,
      role: "client",
      label: "Client",
      suggestedSource: suggested,
      onToast: (msg, kind) => {
      }
    }
  ), /* @__PURE__ */ React.createElement(
    ContractorResolutionRoleCard,
    {
      batchId,
      role: "supplier",
      label: "Supplier",
      suggestedSource: suggested,
      onToast: (msg, kind) => {
      }
    }
  ));
}
function BatchDetailPage({ batchId, onBack, onToast }) {
  const [audit, setAudit] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState("");
  const [activeTab, setActiveTab] = React.useState("Overview");
  const [timeline, setTimeline] = React.useState([]);
  const [busy, setBusy] = React.useState({});
  const [pzNumber, setPzNumber] = React.useState("");
  const [confirmingPz, setConfirmingPz] = React.useState(false);
  const [pzPreview, setPzPreview] = React.useState(null);
  const [pzPreviewLoading, setPzPreviewLoading] = React.useState(false);
  const [pzCreateBusy, setPzCreateBusy] = React.useState(false);
  const [pzCreateResult, setPzCreateResult] = React.useState(null);
  const [pzCreateConfirm, setPzCreateConfirm] = React.useState(false);
  const [pzAdoptInput, setPzAdoptInput] = React.useState("");
  const [pzAdoptBusy, setPzAdoptBusy] = React.useState(false);
  const [pzAdoptResult, setPzAdoptResult] = React.useState(null);
  const [pzAdoptOpen, setPzAdoptOpen] = React.useState(false);
  const [pzDocumentData, setPzDocumentData] = React.useState(null);
  const [pzDocumentLoading, setPzDocumentLoading] = React.useState(false);
  const [pzDocumentOpen, setPzDocumentOpen] = React.useState(false);
  const [proformaDocState, setProformaDocState] = React.useState({});
  const [convertState, setConvertState] = React.useState({});
  const [scanResult, setScanResult] = React.useState(null);
  const [confirmingMarkRec, setConfirmingMarkRec] = React.useState(false);
  const _markRecDefaults = { sender: "odprawacelna@dhl.com", subject: "", ticket: "", request_type: "unknown", note: "" };
  const [markRecFields, setMarkRecFields] = React.useState(_markRecDefaults);
  const [replyStatus, setReplyStatus] = React.useState(null);
  const [recheckBusy, setRecheckBusy] = React.useState(false);
  const [recheckPanel, setRecheckPanel] = React.useState(null);
  const [trackingData, setTrackingData] = React.useState(null);
  const [trackingBusy, setTrackingBusy] = React.useState(false);
  const [dbEvents, setDbEvents] = React.useState([]);
  const [intelData, setIntelData] = React.useState(null);
  const [intelLoading, setIntelLoading] = React.useState(false);
  const [proposals, setProposals] = React.useState([]);
  const [proposalsBusy, setProposalsBusy] = React.useState({});
  const [proposalsLoading, setProposalsLoading] = React.useState(false);
  const [warehouseAudit, setWarehouseAudit] = React.useState(null);
  const [warehouseAuditLoading, setWarehouseAuditLoading] = React.useState(false);
  const [salesLinkage, setSalesLinkage] = React.useState(null);
  const [salesLinkageLoading, setSalesLinkageLoading] = React.useState(false);
  const [reservationPreview, setReservationPreview] = React.useState(null);
  const [reservationPreviewLoading, setReservationPreviewLoading] = React.useState(false);
  const [createConfirm, setCreateConfirm] = React.useState(null);
  const [createBusy, setCreateBusy] = React.useState(false);
  const [createResults, setCreateResults] = React.useState({});
  const [docRegistry, setDocRegistry] = React.useState(null);
  const [docRegistryLoading, setDocRegistryLoading] = React.useState(false);
  const [expandedDocId, setExpandedDocId] = React.useState(null);
  const [addDocOpen, setAddDocOpen] = React.useState(false);
  const [expandedDiagDocId, setExpandedDiagDocId] = React.useState(null);
  const [reparseBusy, setReparseBusy] = React.useState(false);
  const [reparseSummary, setReparseSummary] = React.useState("");
  const [llmSuggestBusyDocId, setLlmSuggestBusyDocId] = React.useState(null);
  const [packingInfo, setPackingInfo] = React.useState(null);
  const [packingInfoLoading, setPackingInfoLoading] = React.useState(false);
  const [laneReadiness, setLaneReadiness] = React.useState(null);
  const [packingUploading, setPackingUploading] = React.useState(false);
  const [packingDeleting, setPackingDeleting] = React.useState({});
  const [timelineFilter, setTimelineFilter] = React.useState("all");
  const [batchReadiness, setBatchReadiness] = React.useState(null);
  const [batchReadinessLoading, setBatchReadinessLoading] = React.useState(false);
  const [batchReadinessError, setBatchReadinessError] = React.useState("");
  const [dhlReadiness, setDhlReadiness] = React.useState(null);
  const [dhlReadinessLoading, setDhlReadinessLoading] = React.useState(false);
  const [dhlReadinessError, setDhlReadinessError] = React.useState("");
  const [invState, setInvState] = React.useState(null);
  const [invStateLoading, setInvStateLoading] = React.useState(false);
  const [invStateError, setInvStateError] = React.useState("");
  const [decisionData, setDecisionData] = React.useState(null);
  const [decisionLoading, setDecisionLoading] = React.useState(false);
  const sadRef = React.useRef();
  const dhlDocsRef = React.useRef();
  const [dhlDocsBusy, setDhlDocsBusy] = React.useState(false);
  const [dhlDocsResult, setDhlDocsResult] = React.useState(null);
  const [dhlDocsError, setDhlDocsError] = React.useState("");
  const agencyDocsRef = React.useRef();
  const [agencyDocsBusy, setAgencyDocsBusy] = React.useState(false);
  const [agencyDocsResult, setAgencyDocsResult] = React.useState(null);
  const [agencyDocsError, setAgencyDocsError] = React.useState("");
  const svcInvoiceRef = React.useRef();
  const [svcInvoiceBusy, setSvcInvoiceBusy] = React.useState(false);
  const [svcInvoiceResult, setSvcInvoiceResult] = React.useState(null);
  const [svcInvoiceError, setSvcInvoiceError] = React.useState("");
  const [closureCheck, setClosureCheck] = React.useState(null);
  const [closureCheckLoading, setClosureCheckLoading] = React.useState(false);
  const [closureCheckError, setClosureCheckError] = React.useState("");
  const [closureConfirmBusy, setClosureConfirmBusy] = React.useState(false);
  const [closureConfirmResult, setClosureConfirmResult] = React.useState(null);
  const [dhlSendReplyResult, setDhlSendReplyResult] = React.useState(null);
  const [proformaPipeline, setProformaPipeline] = React.useState(null);
  const [proformaPipelineLoading, setProformaPipelineLoading] = React.useState(false);
  const setBusyKey = (k, v) => setBusy((p) => ({ ...p, [k]: v }));
  const load = React.useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const a = await apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}`);
      setAudit(a);
      const canon = (a.wfirma_export || {}).wfirma_pz_fullnumber || "";
      if (canon) setPzNumber(canon);
      else if (a.doc_no) setPzNumber(a.doc_no);
    } catch (e) {
      setErr(e.message);
    }
    setLoading(false);
  }, [batchId]);
  const loadTimeline = React.useCallback(async () => {
    try {
      const tl = await apiFetch(`/api/v1/tracking/shipment/${encodeURIComponent(batchId)}/timeline`);
      setTimeline(Array.isArray(tl) ? tl : tl.timeline || tl.events || []);
    } catch (e) {
    }
  }, [batchId]);
  const refreshProformaPipeline = React.useCallback(async () => {
    setProformaPipelineLoading(true);
    try {
      const d = await apiFetch(`/api/v1/proforma/pipeline/${encodeURIComponent(batchId)}`);
      setProformaPipeline(d);
    } catch (e) {
      setProformaPipeline(null);
    }
    setProformaPipelineLoading(false);
  }, [batchId]);
  const loadDbEvents = React.useCallback(async () => {
    try {
      const res = await apiFetch(`/api/v1/tracking/events/${encodeURIComponent(batchId)}`);
      setDbEvents(Array.isArray(res.events) ? res.events : []);
    } catch (e) {
    }
  }, [batchId]);
  const fetchTracking = React.useCallback(async (refresh = false) => {
    const awb = (audit || {}).tracking_no;
    if (!awb) return;
    const carr = (audit || {}).carrier || "DHL";
    setTrackingBusy(true);
    try {
      const url = refresh ? `/api/v1/tracking/${encodeURIComponent(awb)}/refresh?carrier=${encodeURIComponent(carr)}&batch_id=${encodeURIComponent(batchId)}` : `/api/v1/tracking/${encodeURIComponent(awb)}?carrier=${encodeURIComponent(carr)}&batch_id=${encodeURIComponent(batchId)}`;
      const method = refresh ? "POST" : "GET";
      const td = await apiFetch(url, { method });
      setTrackingData(td);
    } catch (e) {
      const _msg = String(e && e.message || e || "Network error");
      const _src = e && e.type === "auth" ? "unauthorized" : "network_error";
      setTrackingData({
        available: false,
        ok: false,
        source: _src,
        status: _src,
        fallback_available: true,
        message: _src === "unauthorized" ? "Session expired or DHL API credential issue." : "Could not reach the tracking service.",
        error: _msg,
        tracking_url: ""
      });
    } finally {
      setTrackingBusy(false);
    }
  }, [batchId, audit]);
  const loadIntelligence = React.useCallback(async () => {
    setIntelLoading(true);
    try {
      const d = await apiFetch(`/api/v1/intelligence/suggestions/${encodeURIComponent(batchId)}`);
      setIntelData(d);
    } catch (e) {
      setIntelData({ error: e.message });
    }
    setIntelLoading(false);
  }, [batchId]);
  const loadProposals = React.useCallback(async () => {
    setProposalsLoading(true);
    try {
      const d = await apiFetch(`/api/v1/action-proposals/${encodeURIComponent(batchId)}`);
      setProposals(d.proposals || []);
    } catch (e) {
      setProposals([]);
    }
    setProposalsLoading(false);
  }, [batchId]);
  const loadWarehouseAudit = React.useCallback(async () => {
    setWarehouseAuditLoading(true);
    try {
      const d = await apiFetch(`/api/v1/warehouse/audit/${encodeURIComponent(batchId)}`);
      setWarehouseAudit(d);
    } catch (e) {
      setWarehouseAudit({ error: e.message });
    }
    setWarehouseAuditLoading(false);
  }, [batchId]);
  const loadSalesLinkage = React.useCallback(async () => {
    setSalesLinkageLoading(true);
    try {
      const d = await apiFetch(`/api/v1/sales/linkage/${encodeURIComponent(batchId)}?mode=preview`);
      setSalesLinkage(d);
    } catch (e) {
      setSalesLinkage({ error: e.message });
    }
    setSalesLinkageLoading(false);
  }, [batchId]);
  const loadReservationPreview = React.useCallback(async () => {
    setReservationPreviewLoading(true);
    try {
      const d = await apiFetch(`/api/v1/wfirma/reservation-preview/${encodeURIComponent(batchId)}`);
      setReservationPreview(d);
    } catch (e) {
      setReservationPreview({ error: e.message });
    }
    setReservationPreviewLoading(false);
  }, [batchId]);
  const loadPzPreview = React.useCallback(async () => {
    setPzPreviewLoading(true);
    try {
      const d = await apiFetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_preview`);
      setPzPreview(d);
    } catch (e) {
      setPzPreview({ error: e.message });
    }
    setPzPreviewLoading(false);
  }, [batchId]);
  const resolveProducts = React.useCallback(async () => {
    setBusyKey("pzResolve", true);
    try {
      await apiFetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/products/resolve`, { method: "POST" });
      onToast("Products resolved \u2014 refreshing preview\u2026", "success");
      await loadPzPreview();
    } catch (e) {
      onToast("Resolve failed: " + e.message, "error");
    }
    setBusyKey("pzResolve", false);
  }, [batchId, onToast, loadPzPreview]);
  const submitPzCreate = React.useCallback(async () => {
    setPzCreateBusy(true);
    setPzCreateConfirm(false);
    try {
      const _op = _resolveOperator();
      const _hdrs = _op ? { "X-Operator": _op } : {};
      const d = await apiFetch(
        `/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_create`,
        { method: "POST", headers: _hdrs }
      );
      setPzCreateResult(d);
      onToast(`wFirma PZ created: ${d.wfirma_pz_doc_id}`, "success");
      await loadPzPreview();
    } catch (e) {
      let body = { status: "failed", error: e.message };
      try {
        body = JSON.parse((e.message || "").split(": ").slice(1).join(": ")) || body;
      } catch {
      }
      setPzCreateResult(body);
      onToast("PZ create failed: " + (body.error || e.message), "error");
    }
    setPzCreateBusy(false);
  }, [batchId, onToast, loadPzPreview]);
  const submitPzAdopt = React.useCallback(async () => {
    const val = pzAdoptInput.trim();
    if (!val) {
      onToast("Enter a PZ doc ID or document number first", "error");
      return;
    }
    const isNumericId = /^\d+$/.test(val);
    const payload = isNumericId ? { pz_doc_id: val } : { pz_number: val };
    setPzAdoptBusy(true);
    try {
      const _op = _resolveOperator();
      const _adoptHdrs = {
        "Content-Type": "application/json",
        ..._op ? { "X-Operator": _op } : {}
      };
      const d = await apiFetch(
        `/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_adopt`,
        { method: "POST", headers: _adoptHdrs, body: JSON.stringify(payload) }
      );
      setPzAdoptResult(d);
      if (d.status === "adopted" || d.status === "already_adopted") {
        onToast(`PZ adopted: ${d.wfirma_pz_doc_id}`, "success");
        setPzAdoptOpen(false);
        await loadPzPreview();
      } else {
        const reason = (d.blocking_reasons || []).join("; ") || d.error || "blocked";
        onToast("PZ adopt blocked: " + reason, "error");
      }
    } catch (e) {
      onToast("PZ adopt error: " + e.message, "error");
    }
    setPzAdoptBusy(false);
  }, [batchId, pzAdoptInput, onToast, loadPzPreview]);
  const loadPzDocument = React.useCallback(async () => {
    setPzDocumentLoading(true);
    try {
      const d = await apiFetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_document`);
      setPzDocumentData(d);
      setPzDocumentOpen(true);
    } catch (e) {
      onToast("PZ document fetch failed: " + e.message, "error");
    }
    setPzDocumentLoading(false);
  }, [batchId, onToast]);
  const loadProformaDocument = React.useCallback(async (clientName) => {
    setProformaDocState((prev) => ({ ...prev, [clientName]: { ...prev[clientName] || {}, loading: true } }));
    try {
      const d = await apiFetch(`/api/v1/proforma/${encodeURIComponent(batchId)}/${encodeURIComponent(clientName)}/document`);
      setProformaDocState((prev) => ({ ...prev, [clientName]: { data: d, loading: false, open: true } }));
    } catch (e) {
      const isNotLinked = e && (e.code === "PROFORMA_NOT_LINKED" || e.message && e.message.includes("PROFORMA_NOT_LINKED"));
      setProformaDocState((prev) => ({
        ...prev,
        [clientName]: {
          ...prev[clientName] || {},
          loading: false,
          open: true,
          error: isNotLinked ? "not_linked" : e.message || "fetch_failed"
        }
      }));
      if (!isNotLinked) onToast(`Proforma fetch failed for ${clientName}: ` + e.message, "error");
    }
  }, [batchId, onToast]);
  const loadConvertPreview = React.useCallback(async (clientName) => {
    setConvertState((prev) => ({
      ...prev,
      [clientName]: {
        ...prev[clientName] || {},
        previewLoading: true,
        error: null,
        open: true
      }
    }));
    try {
      const d = await apiFetch(
        `/api/v1/proforma/to-invoice-preview/${encodeURIComponent(batchId)}/${encodeURIComponent(clientName)}`
      );
      setConvertState((prev) => ({
        ...prev,
        [clientName]: {
          ...prev[clientName] || {},
          previewLoading: false,
          preview: d,
          confirmToken: "",
          result: null,
          open: true
        }
      }));
    } catch (e) {
      setConvertState((prev) => ({
        ...prev,
        [clientName]: {
          ...prev[clientName] || {},
          previewLoading: false,
          error: e.message,
          open: true
        }
      }));
      onToast(`Convert preview failed for ${clientName}: ` + e.message, "error");
    }
  }, [batchId, onToast]);
  const executeConvert = React.useCallback(async (clientName) => {
    const st = convertState[clientName] || {};
    if (!st.preview || st.preview.status !== "preview") {
      onToast("Preview must succeed before converting", "error");
      return;
    }
    const token = (st.confirmToken || "").trim();
    if (token !== "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA") {
      onToast("Type the exact confirm token to convert", "error");
      return;
    }
    const operator = (localStorage.getItem("pz_operator_name") || "").trim();
    if (!operator) {
      onToast("Set X-Operator (pz_operator_name) before converting", "error");
      return;
    }
    setConvertState((prev) => ({
      ...prev,
      [clientName]: {
        ...prev[clientName] || {},
        executing: true,
        error: null
      }
    }));
    try {
      const r = await fetch(
        `/api/v1/proforma/to-invoice/${encodeURIComponent(batchId)}/${encodeURIComponent(clientName)}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-Operator": operator
          },
          body: JSON.stringify({ confirm: token })
        }
      );
      const data = await r.json();
      if (!r.ok || data.ok !== true) {
        throw new Error(
          data.blocking_reasons && data.blocking_reasons.join("; ") || data.error || `HTTP ${r.status}`
        );
      }
      setConvertState((prev) => ({
        ...prev,
        [clientName]: {
          ...prev[clientName] || {},
          executing: false,
          result: data,
          error: null
        }
      }));
      onToast(`Invoice ${data.wfirma_invoice_number} issued`, "success");
    } catch (e) {
      setConvertState((prev) => ({
        ...prev,
        [clientName]: {
          ...prev[clientName] || {},
          executing: false,
          error: e.message
        }
      }));
      onToast(`Convert failed for ${clientName}: ` + e.message, "error");
    }
  }, [batchId, convertState, onToast]);
  const submitReservation = React.useCallback(async (clientName) => {
    setCreateBusy(true);
    try {
      const d = await apiFetch("/api/v1/execute/wfirma_create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ batch_id: batchId, payload: { client_name: clientName } })
      });
      if (!d.ok) {
        const reason = d.reason || d.error || "blocked";
        setCreateResults((prev) => ({ ...prev, [clientName]: d }));
        onToast(`Create blocked for ${clientName}: ${reason}`, "error");
      } else if (d.status === "skipped") {
        setCreateResults((prev) => ({ ...prev, [clientName]: d }));
        onToast(`Reservation already exists for ${clientName}`, "info");
        await Promise.all([loadReservationPreview(), loadBatchReadiness(), loadDecision()]);
      } else {
        setCreateResults((prev) => ({ ...prev, [clientName]: d }));
        onToast(`Reservation created for ${clientName} (${d.wfirma_reservation_id})`, "success");
        await Promise.all([loadReservationPreview(), loadBatchReadiness(), loadDecision()]);
      }
    } catch (e) {
      let body = { ok: false, code: "CLIENT_ERROR", error: e.message };
      try {
        body = JSON.parse((e.message || "").split(": ").slice(1).join(": ")) || body;
      } catch {
      }
      setCreateResults((prev) => ({ ...prev, [clientName]: body }));
      onToast(`Create failed for ${clientName}: ${body.error || e.message}`, "error");
    }
    setCreateBusy(false);
    setCreateConfirm(null);
  }, [batchId, onToast, loadReservationPreview, loadBatchReadiness, loadDecision]);
  const loadDocRegistry = React.useCallback(async () => {
    setDocRegistryLoading(true);
    try {
      const d = await apiFetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/documents`);
      setDocRegistry(d);
    } catch (e) {
      setDocRegistry({ error: e.message });
    }
    setDocRegistryLoading(false);
  }, [batchId]);
  const loadPackingInfo = React.useCallback(async () => {
    setPackingInfoLoading(true);
    try {
      const d = await apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}`);
      setPackingInfo(d);
    } catch (e) {
      setPackingInfo({ error: e.message });
    }
    setPackingInfoLoading(false);
  }, [batchId]);
  const loadLaneReadiness = React.useCallback(async () => {
    try {
      const d = await apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/lane-readiness`);
      setLaneReadiness(d);
    } catch (e) {
      setLaneReadiness({ error: e.message });
    }
  }, [batchId]);
  const loadBatchReadiness = React.useCallback(async () => {
    setBatchReadinessLoading(true);
    setBatchReadinessError("");
    try {
      const d = await apiFetch(`/api/v1/batch/${encodeURIComponent(batchId)}/readiness`);
      setBatchReadiness(d);
    } catch (e) {
      setBatchReadinessError(e.message || "Failed to load");
    }
    setBatchReadinessLoading(false);
  }, [batchId]);
  const loadDhlReadiness = React.useCallback(async () => {
    setDhlReadinessLoading(true);
    setDhlReadinessError("");
    try {
      const d = await apiFetch(`/api/v1/dhl/readiness/${encodeURIComponent(batchId)}`);
      setDhlReadiness(d);
    } catch (e) {
      setDhlReadinessError(e.message || "Failed to load");
    }
    setDhlReadinessLoading(false);
  }, [batchId]);
  const refreshAll = React.useCallback((scope) => {
    const fns = [
      load,
      loadDocRegistry,
      loadPackingInfo,
      loadLaneReadiness,
      loadDhlReadiness,
      loadBatchReadiness,
      loadSalesLinkage,
      loadReservationPreview,
      loadPzPreview,
      loadWarehouseAudit
    ];
    for (const fn of fns) {
      try {
        if (typeof fn === "function") fn();
      } catch (_) {
      }
    }
  }, [
    load,
    loadDocRegistry,
    loadPackingInfo,
    loadLaneReadiness,
    loadDhlReadiness,
    loadBatchReadiness,
    loadSalesLinkage,
    loadReservationPreview,
    loadPzPreview,
    loadWarehouseAudit
  ]);
  const loadInvState = React.useCallback(async () => {
    setInvStateLoading(true);
    setInvStateError("");
    try {
      const d = await apiFetch(`/api/v1/inventory/state/${encodeURIComponent(batchId)}`);
      setInvState(d);
    } catch (e) {
      setInvStateError(e.message || "Failed to load");
    }
    setInvStateLoading(false);
  }, [batchId]);
  const loadDecision = React.useCallback(async () => {
    setDecisionLoading(true);
    try {
      const d = await apiFetch(`/api/v1/agents/decision/${encodeURIComponent(batchId)}`);
      setDecisionData(d);
    } catch (e) {
    }
    setDecisionLoading(false);
  }, [batchId]);
  const proposalAction = async (proposalId, action, body) => {
    setProposalsBusy((p) => ({ ...p, [proposalId]: true }));
    try {
      await apiFetch(`/api/v1/action-proposals/${encodeURIComponent(proposalId)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      onToast(`Proposal ${action}d.`, "success");
      await loadProposals();
    } catch (e) {
      onToast(e.message || `Failed to ${action}`, "error");
    }
    setProposalsBusy((p) => ({ ...p, [proposalId]: false }));
  };
  React.useEffect(() => {
    load();
    loadTimeline();
    loadDbEvents();
    refreshProformaPipeline();
  }, [batchId]);
  React.useEffect(() => {
    if (audit) fetchTracking();
  }, [audit?.tracking_no]);
  React.useEffect(() => {
    if (activeTab === "Intelligence" && !intelData) loadIntelligence();
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "Proposals") loadProposals();
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "Warehouse" && !warehouseAudit) loadWarehouseAudit();
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab && activeTab.toLowerCase() === "overview" && !warehouseAudit) {
      loadWarehouseAudit();
    }
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "Sales" && !salesLinkage) loadSalesLinkage();
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "PZ / Accounting") {
      if (!reservationPreview) loadReservationPreview();
      if (!pzPreview) loadPzPreview();
    }
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "Documents" && !docRegistry) loadDocRegistry();
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "Documents" && !packingInfo) loadPackingInfo();
  }, [activeTab]);
  React.useEffect(() => {
    if (activeTab === "Documents" && !laneReadiness) loadLaneReadiness();
  }, [activeTab]);
  React.useEffect(() => {
    loadBatchReadiness();
    loadDecision();
    loadInvState();
  }, [batchId]);
  React.useEffect(() => {
    if (activeTab === "DHL / Customs" && !dhlReadiness) loadDhlReadiness();
  }, [activeTab]);
  const doAction = async (key, label, fn) => {
    setBusyKey(key, true);
    onToast(`Running: ${label}\u2026`, "info");
    try {
      await fn();
      onToast(`${label} completed.`, "success");
      await load();
    } catch (e) {
      onToast(`${label} failed: ${e.message}`, "error");
    } finally {
      setBusyKey(key, false);
    }
  };
  if (loading) return /* @__PURE__ */ React.createElement("div", { style: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-3)", flexDirection: "column", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 32, animation: "spin 1s linear infinite", display: "inline-block" } }, "\u27F3"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13 } }, "Loading shipment\u2026"));
  if (err) return /* @__PURE__ */ React.createElement("div", { style: { flex: 1, padding: 40 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: 16, borderRadius: 8, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)", color: "var(--badge-red-text)", fontSize: 13, marginBottom: 16 } }, err), /* @__PURE__ */ React.createElement(Btn, { variant: "outline", onClick: load }, "\u21BB Retry"));
  if (!audit) return null;
  const t = audit.totals || {};
  const inp = audit.inputs || {};
  const ver = audit.verification || {};
  const _fd_raw = audit.files_detail || {};
  const fd = _fd_raw.files || _fd_raw || {};
  const sf = audit.source_files || _fd_raw.source_files || {};
  const status = audit.status || "unknown";
  const v2Active = new URLSearchParams(window.location.search).get("actions_v2") === "1";
  const trackingNo = audit.tracking_no || "";
  const carrier = audit.carrier || "Unknown";
  const mrn = inp.zc429_mrn || audit.mrn || "\u2014";
  const dhlClearance = audit.clearance_status || "";
  const hasSad = !!inp.zc429 || ["sad_uploaded", "customs_parsed", "customs_verified", "verification_needed"].includes(audit.sad_status);
  const pzGenerated = !!fd.pz_pdf?.exists;
  const isPrimaryAction = (label) => !!(decisionData && decisionData.primary_action && decisionData.primary_action === label);
  const topProposalId = decisionData && decisionData.all_actions && decisionData.all_actions.length > 0 ? decisionData.all_actions[0].proposal_id || null : null;
  const wfirmaPrimary = !!(decisionData && decisionData.status === "action_required" && (isPrimaryAction("Create Reservation") || (decisionData.primary_action || "").toLowerCase().includes("wfirma")));
  const fileUrl = (key) => fd[key]?.url || "";
  const fileExists = (key) => !!fd[key]?.exists;
  return /* @__PURE__ */ React.createElement("div", { style: { flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement("div", { "data-testid": "detail-subheader", style: { padding: "14px 32px", background: "var(--card)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 18, flexShrink: 0, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("button", { onClick: onBack, style: { background: "none", border: "1px solid var(--border)", cursor: "pointer", display: "flex", alignItems: "center", gap: 6, color: "var(--text-2)", fontSize: 12, padding: "6px 12px", borderRadius: 6, fontFamily: "inherit", fontWeight: 500 } }, "\u2190 Back"), /* @__PURE__ */ React.createElement("div", { "data-testid": "detail-subheader-awb", style: { minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", letterSpacing: "0.10em", textTransform: "uppercase", fontWeight: 700, marginBottom: 2 } }, "AWB / Tracking"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, color: "var(--text)", fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 280 } }, trackingNo || batchId)), /* @__PURE__ */ React.createElement("div", { style: { width: 1, height: 32, background: "var(--border)" } }), /* @__PURE__ */ React.createElement("div", { "data-testid": "detail-subheader-importer", style: { minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", letterSpacing: "0.10em", textTransform: "uppercase", fontWeight: 700, marginBottom: 2 } }, "Importer"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 600, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 240 } }, inp.importer || inp.importer_name || audit.importer || audit.importer_name || audit.customs_declaration && audit.customs_declaration.importer_name || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" }, title: "No importer name in audit" }, "\u2014"))), /* @__PURE__ */ React.createElement("div", { style: { width: 1, height: 32, background: "var(--border)" } }), /* @__PURE__ */ React.createElement("div", { "data-testid": "detail-subheader-pieces", style: { minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", letterSpacing: "0.10em", textTransform: "uppercase", fontWeight: 700, marginBottom: 2 } }, "Lines"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 600, color: "var(--text)", fontFamily: "monospace" } }, t.line_count ?? audit.line_count ?? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "\u2014"))), audit.doc_no && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { width: 1, height: 32, background: "var(--border)" } }), /* @__PURE__ */ React.createElement("div", { "data-testid": "detail-subheader-doc-no", style: { minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", letterSpacing: "0.10em", textTransform: "uppercase", fontWeight: 700, marginBottom: 2 } }, "Doc No"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 600, color: "var(--text)", fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 180 } }, audit.doc_no))), /* @__PURE__ */ React.createElement("div", { style: { width: 1, height: 32, background: "var(--border)" } }), /* @__PURE__ */ React.createElement(Badge, { status: mapOverall(status) }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }), DETAIL_TABS.map((tab) => /* @__PURE__ */ React.createElement("button", { key: tab, onClick: () => setActiveTab(tab), style: { padding: "6px 14px", borderRadius: 6, border: "none", cursor: "pointer", background: activeTab === tab ? "var(--text)" : "transparent", color: activeTab === tab ? "#fff" : "var(--text-2)", fontSize: 12, fontWeight: activeTab === tab ? 600 : 400, fontFamily: "inherit" } }, tab)), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: load }, "\u21BB Refresh"), /* @__PURE__ */ React.createElement(
    Btn,
    {
      small: true,
      variant: "ghost",
      disabled: recheckBusy,
      title: "Re-run parsers against existing uploaded files",
      onClick: async () => {
        if (!window.confirm(`Recheck shipment ${trackingNo || batchId}?

This re-runs invoice, SAD, and DHL parsers against existing uploaded files.
Parsed values may be updated. PZ will NOT be regenerated automatically.`)) return;
        setRecheckBusy(true);
        setRecheckPanel(null);
        try {
          const res = await apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}/recheck`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "all" }) });
          setRecheckPanel(res);
          await load();
          await loadTimeline();
          onToast(res.ok ? "Recheck complete \u2014 values updated" : "Recheck completed with errors", res.ok ? "success" : "error");
        } catch (e) {
          setRecheckPanel({ ok: false, errors: [e.message] });
          onToast(`Recheck failed: ${e.message}`, "error");
        } finally {
          setRecheckBusy(false);
        }
      }
    },
    recheckBusy ? "\u27F3 Rechecking\u2026" : "\u27F3 Recheck"
  )), /* @__PURE__ */ React.createElement(WorkflowStrip, { audit }), (() => {
    const dhl = audit.dhl_status || "";
    const sad = audit.sad_status || "";
    const pz = audit.pz_status || "";
    let label = null, cta = null, tab = null;
    if (!dhl || dhl === "awaiting_dhl_email") {
      label = "Scan DHL inbox for clearance email";
      cta = "DHL / Customs";
      tab = "DHL / Customs";
    } else if (dhl === "dhl_email_received" || dhl === "reply_package_prepared") {
      label = "Send reply package to DHL Customs";
      cta = "DHL / Customs";
      tab = "DHL / Customs";
    } else if (!sad || sad === "missing" || sad === "sad_pending") {
      label = "Upload SAD / ZC429 from customs agent";
      cta = "DHL / Customs";
      tab = "DHL / Customs";
    } else if (sad === "verification_needed") {
      label = "Verify customs document values";
      cta = "DHL / Customs";
      tab = "DHL / Customs";
    } else if (!pz || pz === "locked") {
      label = "Generate PZ document";
      cta = "PZ / Accounting";
      tab = "PZ / Accounting";
    } else if (pz === "generated") {
      label = "Export PZ to wFirma";
      cta = "PZ / Accounting";
      tab = "PZ / Accounting";
    }
    if (!label) return null;
    return /* @__PURE__ */ React.createElement("div", { style: { margin: "12px 32px 0", padding: "12px 18px", background: "linear-gradient(90deg,var(--accent-subtle),#F8EDD0)", border: "1px solid var(--accent-border)", borderRadius: 8, display: "flex", alignItems: "center", gap: 14, flexShrink: 0 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16 } }, "\u2192"), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 } }, "Next Action"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 600, color: "var(--text)" } }, label)), /* @__PURE__ */ React.createElement("button", { onClick: () => setActiveTab(tab), style: { padding: "6px 14px", background: "var(--accent)", color: "var(--accent-text)", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 700, fontFamily: "inherit", whiteSpace: "nowrap" } }, cta, " \u2192"));
  })(), recheckPanel && /* @__PURE__ */ React.createElement("div", { style: { margin: "0 32px 0", padding: "10px 14px", background: recheckPanel.ok ? "var(--badge-green-bg)" : "var(--badge-red-bg)", border: `1px solid ${recheckPanel.ok ? "var(--badge-green-border)" : "var(--badge-red-border)"}`, borderRadius: 6, display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 200 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: recheckPanel.ok ? "var(--badge-green-text)" : "var(--badge-red-text)", marginBottom: 4 } }, recheckPanel.ok ? "\u2713 Recheck complete" : "\u2717 Recheck failed"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: "2px 12px" } }, Object.entries(recheckPanel.updated || {}).filter(([, v]) => v).map(([k]) => /* @__PURE__ */ React.createElement("span", { key: k, style: { fontSize: 10, color: "var(--badge-green-text)" } }, "\u2022 ", k.replace(/_/g, " "), " updated"))), (recheckPanel.warnings || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4 } }, recheckPanel.warnings.map((w, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 10, color: "var(--badge-amber-text)" } }, "\u26A0 ", w))), (recheckPanel.errors || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4 } }, recheckPanel.errors.map((e, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 10, color: "var(--badge-red-text)" } }, e))), recheckPanel.next_step && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4, fontSize: 10, color: "var(--text-2)", fontStyle: "italic" } }, recheckPanel.next_step)), /* @__PURE__ */ React.createElement("button", { onClick: () => setRecheckPanel(null), style: { background: "none", border: "none", cursor: "pointer", fontSize: 14, color: "var(--text-3)", padding: "0 4px", alignSelf: "flex-start" } }, "\u2715")), /* @__PURE__ */ React.createElement("div", { style: { padding: "24px 32px", display: "flex", flexDirection: "column", gap: 16 } }, audit.cache_freshness && audit.cache_freshness.stale && (() => {
    const cf = audit.cache_freshness;
    const cmd = `python3 -m service.app.tools.regenerate_stale_batches --apply --batch ${batchId}`;
    const reason = cf.rows_missing_fields && cf.rows_missing_fields.length > 0 ? `${cf.rows_missing_fields.length}/${cf.row_count} rows missing v2 fields` : `schema ${cf.row_schema_version || "(missing)"} \u2192 ${cf.current_row_schema_version}`;
    return /* @__PURE__ */ React.createElement("div", { style: {
      padding: "8px 14px",
      background: "var(--badge-amber-bg)",
      border: "1px solid var(--badge-amber-border)",
      borderRadius: 6,
      display: "flex",
      alignItems: "center",
      gap: 10,
      flexWrap: "wrap"
    }, title: `Run to regenerate: ${cmd}` }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14, color: "var(--badge-amber-text)" } }, "\u26A0"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "var(--badge-amber-text)" } }, "Cached audit is stale"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-2)" } }, "\xB7 ", reason), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "outline",
        title: `Copy regeneration command to clipboard:
${cmd}`,
        onClick: () => {
          if (navigator.clipboard) {
            navigator.clipboard.writeText(cmd).then(
              () => onToast && onToast("Regenerate command copied", "success"),
              () => onToast && onToast("Could not copy", "error")
            );
          }
        }
      },
      "\u29C9 Copy regen command"
    ));
  })(), activeTab === "Overview" && v2Active && /* @__PURE__ */ React.createElement(ActionsV2Panel, { batchId }), activeTab === "Overview" && /* @__PURE__ */ React.createElement(SelfclearanceStatePill, { batchId }), activeTab === "Overview" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
    BatchControlCenter,
    {
      batchId,
      audit,
      batchReadiness,
      batchReadinessLoading,
      batchReadinessError,
      dhlReadiness,
      onTabSwitch: setActiveTab
    }
  ), /* @__PURE__ */ React.createElement(
    "details",
    {
      "data-testid": "overview-detailed-readiness",
      style: { marginTop: 12, padding: "4px 0" }
    },
    /* @__PURE__ */ React.createElement("summary", { style: {
      cursor: "pointer",
      fontSize: 11,
      color: "var(--text-2)",
      padding: "6px 0",
      letterSpacing: "0.04em"
    } }, "Detailed readiness breakdown"),
    /* @__PURE__ */ React.createElement(
      OverallReadinessCard,
      {
        batchReadiness,
        loading: batchReadinessLoading,
        error: batchReadinessError,
        decisionData,
        decisionLoading
      }
    ),
    /* @__PURE__ */ React.createElement(MissingFunctionsMatrix, null)
  ), !invStateError && invState && invState.total === 0 && !invStateLoading ? /* @__PURE__ */ React.createElement(
    "details",
    {
      "data-testid": "inventory-batch-state-collapsed",
      style: {
        margin: "12px 0",
        padding: "10px 14px",
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        fontSize: 13
      }
    },
    /* @__PURE__ */ React.createElement("summary", { style: {
      cursor: "pointer",
      color: "#6b7280",
      fontSize: 11
    } }, "Inventory: 0 rows"),
    /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "inventory-batch-state-empty",
        style: { color: "#6b7280", fontSize: 12, marginTop: 8 }
      },
      "No inventory rows for this batch yet."
    )
  ) : /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "inventory-batch-state-strip",
      style: {
        margin: "12px 0",
        padding: "12px 14px",
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        fontSize: 13
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: 8
    } }, /* @__PURE__ */ React.createElement("strong", { style: { color: "#111827" } }, "Inventory state"), invStateLoading && /* @__PURE__ */ React.createElement(
      "span",
      {
        "data-testid": "inventory-batch-state-loading",
        style: { color: "#6b7280", fontSize: 12 }
      },
      "\u2026"
    ), !invStateLoading && invState && /* @__PURE__ */ React.createElement("span", { style: { color: "#6b7280", fontSize: 12 } }, "total ", invState.total, invState.degraded ? " \xB7 degraded" : "")),
    invStateError && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "inventory-batch-state-error",
        style: { color: "#991b1b", fontSize: 12 }
      },
      "\u26A0 ",
      invStateError
    ),
    !invStateError && invState && invState.total > 0 && /* @__PURE__ */ React.createElement("div", { style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
      gap: 8
    } }, Object.entries(invState.counts || {}).map(([stateName, count]) => /* @__PURE__ */ React.createElement(
      "div",
      {
        key: stateName,
        "data-testid": `inventory-batch-state-tile-${stateName}`,
        "data-pending": count === 0 ? "true" : void 0,
        style: {
          padding: "8px 10px",
          background: "#f9fafb",
          border: "1px solid #e5e7eb",
          borderRadius: 6
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 11,
        color: "#6b7280",
        textTransform: "lowercase"
      } }, stateName.replace(/_/g, " ").toLowerCase()),
      /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 18,
        color: count > 0 ? "#111827" : "#9ca3af",
        fontWeight: 600
      } }, count > 0 ? String(count) : "\u2014")
    )))
  ), (() => {
    const inp2 = audit && audit.inputs || {};
    const wf = audit && audit.wfirma_export || {};
    const tk = audit && audit.tracking || {};
    const SAD_DERIVED_KEYS = ["sad_uploaded", "customs_parsed", "customs_verified", "verification_needed"];
    const hasSadDerived = !!inp2.zc429 || SAD_DERIVED_KEYS.includes(audit && audit.sad_status || "");
    const pipelineRow = {
      warehouseHint: (() => {
        const wa = warehouseAudit;
        if (!wa || wa.error) return "n/a";
        const s = wa.summary || {};
        const total = Number(s.total_items || 0);
        const scanned = Number(s.scanned_items || 0);
        const missing = Number(s.missing_items || 0);
        if (total === 0) return "n/a";
        if (missing === 0 && scanned > 0) return "clean";
        if (scanned > 0) return "partial";
        return "empty";
      })(),
      pzStatus: mapPzStatus(audit && audit.pz_status),
      // wFirma surfaces "preview built" when any wFirma artifact
      // exists in the audit — same field the per-batch UI-3.1a
      // badge uses for the "Reserved" lifecycle key.
      wfirmaHint: wf.wfirma_pz_doc_id || audit && audit.wfirma_reservation_id ? "preview_built" : "n/a",
      // UI-3.6: batch detail now injects sales_status_hint so
      // Pipeline Summary reflects true packing-line presence.
      salesHint: audit && audit.sales_status_hint || "n/a",
      has_sad: hasSadDerived,
      mrn: audit && audit.mrn || inp2.zc429_mrn || "",
      _raw: {
        dhl_status: audit && audit.dhl_status || audit && audit.clearance_status || "",
        sad_status: audit && audit.sad_status || "",
        tracking_status_key: tk.status || "",
        tracking_status: tk.status_label || "",
        timestamp: audit && audit.timestamp || ""
      }
    };
    const warehouseLifecycle = deriveWarehouseLifecycle(pipelineRow);
    const warehouseLifecycleLabel = WAREHOUSE_LIFECYCLE_LABEL[warehouseLifecycle];
    const warehouseAttention = ATTENTION_PREDICATES.warehouse(pipelineRow);
    const salesAttention = ATTENTION_PREDICATES.sales_accounting(pipelineRow);
    const dhlAttention = ATTENTION_PREDICATES.dhl_customs(pipelineRow);
    const pillBase = { fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4, display: "inline-block", whiteSpace: "nowrap", border: "1px solid var(--border)" };
    const pillNeutral = { ...pillBase, background: "var(--badge-neutral-bg)", color: "var(--badge-neutral-text)", borderColor: "var(--badge-neutral-border)" };
    const pillAmber = { ...pillBase, background: "var(--badge-amber-bg)", color: "var(--badge-amber-text)", borderColor: "var(--badge-amber-border)" };
    const pillGreen = { ...pillBase, background: "var(--badge-green-bg)", color: "var(--badge-green-text)", borderColor: "var(--badge-green-border)" };
    const pillBlue = { ...pillBase, background: "var(--badge-blue-bg)", color: "var(--badge-blue-text)", borderColor: "var(--badge-blue-border)" };
    const pillRed = { ...pillBase, background: "var(--badge-red-bg)", color: "var(--badge-red-text)", borderColor: "var(--badge-red-border)" };
    const lifecycleTone = warehouseLifecycle === "reserved" ? pillGreen : warehouseLifecycle === "in_warehouse" ? pillBlue : warehouseLifecycle === "partial_received" ? pillAmber : warehouseLifecycle === "awaiting" ? pillRed : pillNeutral;
    const sectionStyle = { padding: 12, background: "var(--bg-subtle)", borderRadius: 6, border: "1px solid var(--border)" };
    const sectionHeadStyle = { fontSize: 11, fontWeight: 700, color: "var(--text-2)", marginBottom: 6, letterSpacing: "0.04em", textTransform: "uppercase" };
    return /* @__PURE__ */ React.createElement(
      Card,
      {
        "data-testid": "pipeline-summary-panel",
        style: { padding: 16, marginBottom: 16 }
      },
      /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)", marginBottom: 4 } }, "\u{1F4CB} Pipeline Summary"),
      /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 12 } }, "Read-only operational snapshot for this batch \u2014 same lifecycle lenses as the cross-batch cards, derived from the existing batch payload. Open any tab for full detail."),
      /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { "data-testid": "pipeline-summary-warehouse", "data-lifecycle-state": warehouseLifecycle, style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: sectionHeadStyle }, "Warehouse"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-warehouse-lifecycle-pill",
          "data-lifecycle-state": warehouseLifecycle,
          "data-nav-target": "Warehouse",
          onClick: () => setActiveTab("Warehouse"),
          title: "Open Warehouse tab",
          "aria-label": `${warehouseLifecycleLabel} \u2014 open Warehouse tab`,
          style: { ...lifecycleTone, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        warehouseLifecycleLabel
      ), batchReadiness && batchReadiness.warehouse && /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-warehouse-readiness-pill",
          "data-readiness-status": batchReadiness.warehouse.status || "",
          "data-nav-target": "Warehouse",
          onClick: () => setActiveTab("Warehouse"),
          title: "Open Warehouse tab",
          "aria-label": `Warehouse readiness ${batchReadiness.warehouse.status || "unknown"} \u2014 open Warehouse tab`,
          style: { ...pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "Readiness: ",
        batchReadiness.warehouse.status || "unknown"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-warehouse-packing-list-pill",
          "data-nav-target": "Warehouse",
          onClick: () => setActiveTab("Warehouse"),
          title: "Open Warehouse tab",
          "aria-label": "Packing list status \u2014 open Warehouse tab",
          style: { ...pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "Packing list: ",
        pipelineRow.warehouseHint === "n/a" ? "absent" : "present"
      ), warehouseAttention && /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-warehouse-attention",
          "data-nav-target": "Warehouse",
          onClick: () => setActiveTab("Warehouse"),
          title: "Open Warehouse tab",
          "aria-label": "Warehouse needs attention \u2014 open Warehouse tab",
          style: { ...pillAmber, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "\u26A0 Needs attention"
      ))), /* @__PURE__ */ React.createElement("div", { "data-testid": "pipeline-summary-sales-accounting", style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: sectionHeadStyle }, "Sales & Accounting"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-sales-pill",
          "data-sales-hint": pipelineRow.salesHint,
          "data-nav-target": "Sales",
          onClick: () => setActiveTab("Sales"),
          title: "Open Sales tab",
          "aria-label": "Sales linkage \u2014 open Sales tab",
          style: { ...pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "Sales: ",
        pipelineRow.salesHint === "present" ? "Linked" : "See Sales tab"
      ), (() => {
        const ps = proformaPipeline && proformaPipeline.pipeline_stage;
        let pillStyle = pillNeutral;
        let pillLabel = "Not prepared";
        let dataStage = ps || pipelineRow.wfirmaHint || "n/a";
        if (ps === "all_posted") {
          pillStyle = pillGreen;
          pillLabel = `Proforma: Posted (${proformaPipeline.by_state?.posted || ""})`;
        } else if (ps === "partial_posted") {
          pillStyle = pillGreen;
          pillLabel = `Proforma: Partial (${proformaPipeline.by_state?.posted || 0}/${proformaPipeline.client_count || 0})`;
        } else if (ps === "post_failed") {
          pillStyle = pillRed;
          pillLabel = `Proforma: Failed`;
        } else if (ps === "approved") {
          pillStyle = pillBlue;
          pillLabel = "Proforma: Approved";
        } else if (ps === "drafting") {
          pillStyle = pillAmber;
          pillLabel = "Proforma: Draft";
        } else if (pipelineRow.wfirmaHint === "preview_built") {
          pillStyle = pillBlue;
          pillLabel = "Preview built";
        }
        const needsAttn = proformaPipeline && proformaPipeline.needs_attention;
        if (needsAttn) pillStyle = { ...pillStyle, outline: "2px solid var(--badge-red-border)", outlineOffset: 1 };
        return /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            "data-testid": "pipeline-summary-wfirma-pill",
            "data-wfirma-hint": pipelineRow.wfirmaHint,
            "data-pipeline-stage": dataStage,
            "data-nav-target": "PZ / Accounting",
            onClick: () => setActiveTab("PZ / Accounting"),
            title: "Open PZ / Accounting tab",
            "aria-label": `wFirma / Proforma status: ${pillLabel} \u2014 open PZ / Accounting tab`,
            style: { ...pillStyle, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
          },
          "wFirma: ",
          proformaPipelineLoading ? "\u2026" : pillLabel
        );
      })(), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-pz-pill",
          "data-pz-status": pipelineRow.pzStatus,
          "data-nav-target": "PZ / Accounting",
          onClick: () => setActiveTab("PZ / Accounting"),
          title: "Open PZ / Accounting tab",
          "aria-label": `PZ status ${pipelineRow.pzStatus || "unknown"} \u2014 open PZ / Accounting tab`,
          style: { ...PZ_DONE_LABELS.has(pipelineRow.pzStatus) ? pillGreen : pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "PZ: ",
        pipelineRow.pzStatus || "\u2014"
      ), salesAttention && /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-sales-attention",
          "data-nav-target": "Sales",
          onClick: () => setActiveTab("Sales"),
          title: "Open Sales tab",
          "aria-label": "Sales & Accounting needs attention \u2014 open Sales tab",
          style: { ...pillAmber, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "\u26A0 Needs attention"
      ))), /* @__PURE__ */ React.createElement("div", { "data-testid": "pipeline-summary-dhl-customs", style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: sectionHeadStyle }, "DHL & Customs"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-dhl-status-pill",
          "data-dhl-status": pipelineRow._raw.dhl_status,
          "data-nav-target": "DHL / Customs",
          onClick: () => setActiveTab("DHL / Customs"),
          title: "Open DHL / Customs tab",
          "aria-label": `DHL status \u2014 open DHL / Customs tab`,
          style: { ...pipelineRow._raw.dhl_status === "dhl_email_received" ? pillAmber : pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "DHL: ",
        mapDhlStatus(pipelineRow._raw.dhl_status) || "\u2014"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-sad-pill",
          "data-sad-status": pipelineRow._raw.sad_status,
          "data-has-sad": pipelineRow.has_sad ? "true" : "false",
          "data-nav-target": "DHL / Customs",
          onClick: () => setActiveTab("DHL / Customs"),
          title: "Open DHL / Customs tab",
          "aria-label": "SAD status \u2014 open DHL / Customs tab",
          style: { ...pipelineRow.has_sad ? pillGreen : pillRed, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "SAD: ",
        pipelineRow.has_sad ? mapSadStatus(pipelineRow._raw.sad_status) : "SAD missing"
      ), pipelineRow.mrn && /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-mrn-pill",
          "data-nav-target": "DHL / Customs",
          onClick: () => setActiveTab("DHL / Customs"),
          title: "Open DHL / Customs tab",
          "aria-label": "Customs MRN \u2014 open DHL / Customs tab",
          style: { ...pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "MRN: ",
        /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace" } }, pipelineRow.mrn)
      ), (pipelineRow._raw.tracking_status_key || pipelineRow._raw.tracking_status) && /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-tracking-pill",
          "data-tracking-key": pipelineRow._raw.tracking_status_key,
          "data-nav-target": "DHL / Customs",
          onClick: () => setActiveTab("DHL / Customs"),
          title: "Open DHL / Customs tab",
          "aria-label": "Carrier tracking \u2014 open DHL / Customs tab",
          style: { ...pipelineRow._raw.tracking_status_key === "delivered" ? pillGreen : pipelineRow._raw.tracking_status_key === "in_transit" ? pillBlue : TRACK_ATTENTION.has(pipelineRow._raw.tracking_status_key) ? pillRed : pillNeutral, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "Tracking: ",
        pipelineRow._raw.tracking_status || pipelineRow._raw.tracking_status_key
      ), dhlAttention && /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          "data-testid": "pipeline-summary-dhl-attention",
          "data-nav-target": "DHL / Customs",
          onClick: () => setActiveTab("DHL / Customs"),
          title: "Open DHL / Customs tab",
          "aria-label": "DHL & Customs needs attention \u2014 open DHL / Customs tab",
          style: { ...pillAmber, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }
        },
        "\u26A0 Needs attention"
      ))))
    );
  })(), (() => {
    const CHECK_LABELS = {
      customs_docs_received: "Customs documents received",
      pz_generated: "PZ generated"
    };
    const NEXT_STEP_MAP = {
      customs_docs_received: "Upload SAD/PZC from the customs agency (DHL / Customs tab)",
      pz_generated: "Generate PZ document (PZ / Accounting tab)"
    };
    const cc = closureCheck;
    const alreadyDone = cc && cc.already_completed;
    const isReady = cc && cc.ready && !alreadyDone;
    const missing = cc && cc.missing || [];
    const checks = cc && cc.checks || {};
    const accountingChecks = cc && cc.accounting_checks || {};
    const accountingFollowup = !!(cc && cc.accounting_followup_required);
    const invoiceStatus = cc && cc.invoice_status || null;
    const _wfExport = audit && audit.wfirma_export || {};
    const _pzDocId = (_wfExport.wfirma_pz_doc_id || "").trim();
    const _pzOutput = (audit && audit.pz_output || {}).pdf || "";
    const pzGenerated2 = !!(audit && (audit.pz_pdf_filename || audit.pz_generated_at || audit.pz_generated || audit.pz_filename || audit.polish_desc_filename || _pzDocId || _pzOutput));
    const batchCompletedStatus = !!(audit && audit.status === "completed");
    const closureEvalDisabled = closureCheckLoading || !pzGenerated2 || batchCompletedStatus;
    const closureEvalDisabledReason = batchCompletedStatus ? "Shipment already completed \u2014 no further action needed" : !pzGenerated2 ? "PZ document must be generated first (PZ / Accounting tab)" : null;
    return /* @__PURE__ */ React.createElement(Card, { "data-testid": "closure-eval-card", style: { marginTop: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F512} Closure Evaluation"), cc && /* @__PURE__ */ React.createElement("span", { "data-testid": "closure-eval-status-badge", style: { fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700, border: "1px solid", background: alreadyDone ? "var(--badge-green-bg)" : isReady ? "var(--badge-green-bg)" : "var(--badge-amber-bg)", color: alreadyDone ? "var(--badge-green-text)" : isReady ? "var(--badge-green-text)" : "var(--badge-amber-text)", borderColor: alreadyDone ? "var(--badge-green-border)" : isReady ? "var(--badge-green-border)" : "var(--badge-amber-border)" } }, alreadyDone ? "Completed" : isReady ? "Ready" : "Blocked")), /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-description", style: { fontSize: 11, color: "var(--text-3)", marginBottom: 12 } }, "Checks hard blockers for closure: customs documents received and PZ generated. Service invoices are accounting signals only \u2014 not closure blockers. Evaluation only \u2014 does not close the shipment."), cc && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-checklist", style: { marginBottom: 12 } }, Object.entries(CHECK_LABELS).map(([key, label]) => {
      const done = checks[key];
      return /* @__PURE__ */ React.createElement("div", { key, style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, color: done ? "var(--badge-green-text)" : "var(--badge-amber-text)", width: 18 } }, done ? "\u2713" : "\u25CB"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: done ? "var(--text)" : "var(--text-3)", fontWeight: done ? 400 : 400 } }, label));
    })), cc && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-accounting-signals", style: { marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", marginBottom: 4 } }, "Service invoices (accounting)"), [["agency_invoice_received", "Agency invoice"], ["dhl_invoice_received", "DHL invoice"]].map(([key, label]) => {
      const done = accountingChecks[key];
      return /* @__PURE__ */ React.createElement("div", { key, style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, color: done ? "var(--badge-green-text)" : "var(--badge-amber-text)", width: 18 } }, done ? "\u2713" : "\u25CB"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: done ? "var(--text)" : "var(--text-3)" } }, label), !done && /* @__PURE__ */ React.createElement("span", { "data-testid": "closure-invoice-pending-label", style: { fontSize: 10, color: "var(--badge-amber-text)" } }, "pending accounting"));
    })), cc && missing.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-blocking-reasons", style: { marginBottom: 12, padding: "8px 10px", borderRadius: 6, background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--badge-amber-text)", textTransform: "uppercase", marginBottom: 6 } }, "Blocking"), missing.map((key) => /* @__PURE__ */ React.createElement("div", { key, style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, CHECK_LABELS[key] || key), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", opacity: 0.85 } }, NEXT_STEP_MAP[key] || "\u2014")))), cc && alreadyDone && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-already-completed", style: { marginBottom: 12, padding: "8px 10px", borderRadius: 6, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, color: "var(--badge-green-text)" } }, "\u2713 Shipment is already marked as completed."), audit && (audit.closure_approved_by || audit.closed_at) && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-metadata", style: { marginTop: 4, fontSize: 10, color: "var(--badge-green-text)", opacity: 0.85 } }, audit.closure_approved_by && /* @__PURE__ */ React.createElement("span", null, "Approved by: ", audit.closure_approved_by), audit.closure_approved_by && audit.closed_at && /* @__PURE__ */ React.createElement("span", null, " \xB7 "), audit.closed_at && /* @__PURE__ */ React.createElement("span", null, "Closed: ", new Date(audit.closed_at).toLocaleString()))), cc && isReady && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-next-step", style: { marginBottom: 12, padding: "8px 10px", borderRadius: 6, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--badge-green-text)", textTransform: "uppercase", marginBottom: 2 } }, "Next step"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-green-text)" } }, "All conditions met. Shipment is ready for final closure.")), cc && isReady && accountingFollowup && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-accounting-followup-notice", style: { marginBottom: 12, padding: "8px 10px", borderRadius: 6, background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, "Service invoices pending \u2014 accounting follow-up required after closure.")), closureCheckError && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-error", style: { marginBottom: 12, padding: "8px 10px", borderRadius: 6, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-red-text)", fontWeight: 600 } }, "Evaluation failed: ", closureCheckError)), /* @__PURE__ */ React.createElement("div", { style: { borderTop: "1px solid var(--border-subtle)", paddingTop: 10 } }, /* @__PURE__ */ React.createElement(
      Btn,
      {
        "data-testid": "closure-eval-btn",
        small: true,
        variant: "outline",
        disabled: closureEvalDisabled,
        title: closureEvalDisabled ? closureEvalDisabledReason || "Closure evaluation not yet available \u2014 finish prior steps first." : "Run a read-only check of all closure prerequisites.",
        style: { opacity: closureEvalDisabled && !closureCheckLoading ? 0.45 : 1, cursor: closureEvalDisabled && !closureCheckLoading ? "not-allowed" : "pointer" },
        onClick: async () => {
          setClosureCheckLoading(true);
          setClosureCheckError("");
          try {
            const result = await apiFetch(`/api/v1/closure/${encodeURIComponent(batchId)}/check`);
            setClosureCheck(result);
            await loadBatchReadiness();
          } catch (ex) {
            setClosureCheckError(ex.message || "Evaluation failed");
          } finally {
            setClosureCheckLoading(false);
          }
        }
      },
      closureCheckLoading ? "\u27F3 Evaluating\u2026" : "Evaluate Closure Readiness"
    ), !closureCheckLoading && closureEvalDisabledReason && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-disabled-reason", style: { fontSize: 10, color: "var(--badge-amber-text)", marginTop: 6, padding: "4px 8px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 4 } }, "\u26A0 ", closureEvalDisabledReason), /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-eval-safe-note", style: { fontSize: 10, color: "var(--text-3)", marginTop: 6 } }, "Read-only check \u2014 does not close or modify the shipment."), /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-confirm-section", style: { marginTop: 14, paddingTop: 10, borderTop: "1px solid var(--border-subtle)" } }, closureConfirmResult && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 8 } }, /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "closure-confirm-result",
        style: {
          padding: "6px 10px",
          borderRadius: 4,
          fontSize: 11,
          fontWeight: 600,
          background: closureConfirmResult.ok ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
          color: closureConfirmResult.ok ? "var(--badge-green-text)" : "var(--badge-amber-text)",
          border: "1px solid " + (closureConfirmResult.ok ? "var(--badge-green-border)" : "var(--badge-amber-border)")
        }
      },
      closureConfirmResult.ok ? closureConfirmResult.stage === "milestone_skip" || closureConfirmResult.reason && closureConfirmResult.reason.startsWith("milestone_skip:") ? "Skipped: already progressed (SAD/PZ/Completed)" : closureConfirmResult.status === "skipped" ? "\u2713 Shipment was already completed (no change)" : "\u2713 Shipment closure confirmed successfully" : "\u26A0 Closure blocked: " + (closureConfirmResult.reason || closureConfirmResult.error || "not ready")
    ), closureConfirmResult.log_write_failed && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-confirm-log-warn", style: { marginTop: 4, fontSize: 10, color: "var(--badge-amber-text)", fontWeight: 600 } }, "\u26A0 Action completed but log write failed"), closureConfirmResult.ok && !(closureConfirmResult.stage === "milestone_skip" || closureConfirmResult.reason?.startsWith("milestone_skip:")) && closureConfirmResult.status !== "skipped" && (audit && (audit.closure_approved_by || closureConfirmResult.closed_at)) && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-confirm-metadata", style: { marginTop: 4, fontSize: 10, color: "var(--badge-green-text)" } }, audit.closure_approved_by && /* @__PURE__ */ React.createElement("span", null, "Approved by: ", audit.closure_approved_by), audit.closure_approved_by && closureConfirmResult.closed_at && /* @__PURE__ */ React.createElement("span", null, " \xB7 "), closureConfirmResult.closed_at && /* @__PURE__ */ React.createElement("span", null, "Closed: ", new Date(closureConfirmResult.closed_at).toLocaleString())), closureConfirmResult.ok && closureConfirmResult.accounting_followup_required && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-confirm-accounting-notice", style: { marginTop: 4, fontSize: 10, color: "var(--badge-amber-text)", fontWeight: 600 } }, "Closed with accounting follow-up: service invoices pending.")), /* @__PURE__ */ React.createElement(
      Btn,
      {
        "data-testid": "closure-confirm-btn",
        small: true,
        variant: "primary",
        disabled: closureEvalDisabled || closureConfirmBusy || !(closureCheck && closureCheck.ready && !closureCheck.already_completed),
        title: closureEvalDisabled ? closureEvalDisabledReason || "Closure not yet available \u2014 earlier pipeline steps incomplete." : !closureCheck ? 'Run "Evaluate Closure Readiness" first \u2014 closure requires all checks to pass.' : closureCheck.already_completed ? "Shipment is already closed \u2014 no further action needed." : !closureCheck.ready ? "Closure not ready: " + (closureCheck.next_step || closureCheck.reason || "prerequisites missing") : "Apply final closure for this shipment.",
        style: {
          opacity: (closureEvalDisabled || !(closureCheck && closureCheck.ready && !closureCheck.already_completed)) && !closureConfirmBusy ? 0.45 : 1,
          cursor: (closureEvalDisabled || !(closureCheck && closureCheck.ready && !closureCheck.already_completed)) && !closureConfirmBusy ? "not-allowed" : "pointer"
        },
        onClick: async () => {
          const approvedBy = (prompt("Confirm closure \u2014 enter operator name:", "operator") || "").trim() || "operator";
          setClosureConfirmBusy(true);
          setClosureConfirmResult(null);
          try {
            const d = await apiFetch("/api/v1/execute/closure_confirm", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ batch_id: batchId, payload: { approved_by: approvedBy } })
            });
            setClosureConfirmResult(d);
            if (d.ok) {
              onToast(
                d.status === "skipped" ? "Shipment already completed" : "Closure confirmed \u2014 shipment marked completed",
                d.status === "skipped" ? "info" : "success"
              );
              await Promise.all([load(), loadBatchReadiness(), loadDecision()]);
            } else {
              onToast("Closure blocked: " + (d.reason || d.error || "not ready"), "error");
            }
          } catch (e) {
            const body = { ok: false, error: e.message };
            setClosureConfirmResult(body);
            onToast("Closure confirm failed: " + e.message, "error");
          } finally {
            setClosureConfirmBusy(false);
          }
        }
      },
      closureConfirmBusy ? "\u27F3 Confirming\u2026" : "\u{1F512} Confirm Closure"
    ), !(closureCheck && closureCheck.ready && !closureCheck.already_completed) && !closureEvalDisabled && /* @__PURE__ */ React.createElement("div", { "data-testid": "closure-confirm-not-ready-reason", style: { fontSize: 10, color: "var(--badge-amber-text)", marginTop: 4 } }, "Run Evaluate first \u2014 closure requires all checks to pass.")))));
  })(), /* @__PURE__ */ React.createElement(BrokerFollowupPanel, { batchId }), /* @__PURE__ */ React.createElement(BrokerReplyAnalyzerPanel, null)), activeTab === "Documents" && (() => {
    const deleteSourceFile = async (category, filename) => {
      if (!confirm(`Delete source file "${filename}"?`)) return;
      try {
        await apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}/files/source/${category}/${encodeURIComponent(filename)}`, { method: "DELETE" });
        load();
      } catch (e) {
        alert("Delete failed: " + e.message);
      }
    };
    const deleteOutputFile = async (filename) => {
      if (!confirm(`Delete output file "${filename}"?`)) return;
      try {
        const isPolishDesc = /^POLISH_DESC_/i.test(filename);
        if (isPolishDesc) {
          await apiFetch(
            `/dashboard/batches/${encodeURIComponent(batchId)}/polish-description`,
            { method: "DELETE" }
          );
        } else {
          await apiFetch(
            `/dashboard/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(filename)}`,
            { method: "DELETE" }
          );
        }
        load();
      } catch (e) {
        alert("Delete failed: " + e.message);
      }
    };
    const regenerateAll = async () => {
      if (!confirm("Delete all generated output files and reset for fresh processing?")) return;
      try {
        const d = await apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}/regenerate`, { method: "POST" });
        alert(`Deleted ${d.deleted_files?.length || 0} files. Ready for re-processing.`);
        load();
      } catch (e) {
        alert("Regenerate failed: " + e.message);
      }
    };
    const srcCatMap = {};
    (sf.invoices || []).forEach((f) => {
      srcCatMap[f.name] = "invoices";
    });
    (sf.sad || []).forEach((f) => {
      srcCatMap[f.name] = "sad";
    });
    (sf.awb || []).forEach((f) => {
      srcCatMap[f.name] = "awb";
    });
    return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" } }, "Uploaded Source Files"), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "outline",
        "data-testid": "source-files-add-doc",
        onClick: () => setAddDocOpen(true)
      },
      "+ Add Document"
    )), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, [
      ...(sf.invoices || []).map((f) => ({ name: f.name, type: "Invoice PDF", url: f.url, cat: "invoices" })),
      ...(sf.sad || []).map((f) => ({ name: f.name, type: "SAD / ZC429 PDF", url: f.url, cat: "sad" })),
      ...(sf.awb || []).map((f) => ({ name: f.name, type: "AWB PDF", url: f.url, cat: "awb" }))
    ].map((doc, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--card)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 36, height: 36, borderRadius: 6, background: "var(--badge-blue-bg)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 } }, "\u{1F4C4}"), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, doc.name), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginTop: 1 } }, doc.type)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, doc.url && /* @__PURE__ */ React.createElement("a", { href: doc.url, download: true, style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline" }, "\u2193")), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => deleteSourceFile(doc.cat, doc.name),
        title: "Delete file",
        style: { background: "none", border: "1px solid var(--badge-red-border)", borderRadius: 4, cursor: "pointer", padding: "3px 7px", fontSize: 11, color: "var(--badge-red-text)", lineHeight: 1 }
      },
      "\u2715"
    )))), !sf.invoices?.length && !sf.sad?.length && !sf.awb?.length && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-3)", padding: "20px 0" } }, "No source files recorded"))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" } }, "Generated Output Files"), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: regenerateAll,
        title: "Delete all outputs and regenerate fresh",
        style: { background: "none", border: "1px solid var(--accent)", borderRadius: 6, cursor: "pointer", padding: "4px 12px", fontSize: 10, color: "var(--accent)", fontWeight: 600, fontFamily: "inherit" }
      },
      "Regenerate All"
    )), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, [
      { key: "pz_pdf", label: "PZ PDF", icon: "\u{1F4C4}" },
      { key: "calc_xlsx", label: "Calculation XLSX", icon: "\u{1F4CA}" },
      { key: "audit_en", label: "Audit EN PDF", icon: "\u{1F4C4}" },
      { key: "audit_pl", label: "Audit PL PDF", icon: "\u{1F4C4}" },
      { key: "audit_memo", label: "Audit Memo PDF", icon: "\u{1F4C4}" },
      { key: "corrections", label: "Correction Report", icon: "\u{1F4C4}" }
    ].map((f) => {
      const exists = fileExists(f.key);
      const url = fileUrl(f.key);
      const fname = fd[f.key]?.name;
      return /* @__PURE__ */ React.createElement("div", { key: f.key, style: { display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--card)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 36, height: 36, borderRadius: 6, background: exists ? "var(--badge-blue-bg)" : "var(--badge-neutral-bg)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 } }, f.icon), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: exists ? "var(--text)" : "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, fname || f.label), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginTop: 1 } }, f.label)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, exists ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--badge-green-text)", fontWeight: 600 } }, "\u2713 Generated") : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "Not generated"), exists && url && /* @__PURE__ */ React.createElement("a", { href: url, download: true, style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline" }, "\u2193")), exists && fname && /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => deleteOutputFile(fname),
          title: "Delete file",
          style: { background: "none", border: "1px solid var(--badge-red-border)", borderRadius: 4, cursor: "pointer", padding: "3px 7px", fontSize: 11, color: "var(--badge-red-text)", lineHeight: 1 }
        },
        "\u2715"
      )));
    }), (() => {
      const fn = audit.polish_desc_filename;
      return /* @__PURE__ */ React.createElement("div", { "data-testid": "generated-output-polish-desc", style: { display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--card)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 36, height: 36, borderRadius: 6, background: fn ? "var(--badge-blue-bg)" : "var(--badge-neutral-bg)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 } }, "\u{1F4C4}"), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: fn ? "var(--text)" : "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, fn || "Polish Customs Description"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginTop: 1 } }, "Polish Customs Description (DHL)")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, fn ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--badge-green-text)", fontWeight: 600 } }, "\u2713 Generated") : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "Not generated"), fn && /* @__PURE__ */ React.createElement("a", { href: `/api/v1/dhl/download/${encodeURIComponent(fn)}`, download: true, style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline" }, "\u2193")), fn && /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => deleteOutputFile(fn),
          title: "Delete file",
          style: { background: "none", border: "1px solid var(--badge-red-border)", borderRadius: 4, cursor: "pointer", padding: "3px 7px", fontSize: 11, color: "var(--badge-red-text)", lineHeight: 1 }
        },
        "\u2715"
      )));
    })(), (() => {
      const fn = audit.dsk_filename;
      return /* @__PURE__ */ React.createElement("div", { "data-testid": "generated-output-dsk", style: { display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--card)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 36, height: 36, borderRadius: 6, background: fn ? "var(--badge-blue-bg)" : "var(--badge-neutral-bg)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 } }, "\u{1F4C4}"), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: fn ? "var(--text)" : "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, fn || "DSK Document"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginTop: 1 } }, "DSK Document (Broker Notification)")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, fn ? /* @__PURE__ */ React.createElement("span", { "data-testid": "generated-output-dsk-status", style: { fontSize: 10, color: "var(--badge-green-text)", fontWeight: 600 } }, "\u2713 Generated") : /* @__PURE__ */ React.createElement("span", { "data-testid": "generated-output-dsk-status", style: { fontSize: 10, color: "var(--text-3)" } }, "Not generated"), fn && /* @__PURE__ */ React.createElement("a", { "data-testid": "generated-output-dsk-download", href: `/api/v1/dhl/download/${encodeURIComponent(fn)}`, download: true, style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline" }, "\u2193")), fn && /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => deleteOutputFile(fn),
          title: "Delete file",
          style: { background: "none", border: "1px solid var(--badge-red-border)", borderRadius: 4, cursor: "pointer", padding: "3px 7px", fontSize: 11, color: "var(--badge-red-text)", lineHeight: 1 }
        },
        "\u2715"
      )));
    })()))), (() => {
      const pl = packingInfo && !packingInfo.error ? packingInfo : null;
      const docs = pl ? pl.documents || [] : [];
      const lineCount = pl ? (pl.packing_lines || []).length : 0;
      const hasDoc = docs.length > 0;
      const handlePackingUpload = async (e) => {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        e.target.value = "";
        setPackingUploading(true);
        try {
          const formData = new FormData();
          formData.append("file", f);
          await apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/upload`, {
            method: "POST",
            body: formData
          });
          await loadPackingInfo();
          await loadBatchReadiness();
          onToast("Packing list uploaded successfully.", "success");
        } catch (ex) {
          onToast("Packing upload failed: " + ex.message, "error");
        }
        setPackingUploading(false);
      };
      const handlePackingDelete = async (doc) => {
        const docId = doc.id;
        const fname = (doc.source_file_path || "").split("/").pop() || doc.file_name || docId;
        const sideRaw = (doc.side || "").toLowerCase();
        const isSalesDoc = sideRaw === "sales" || doc.document_type === "sales_packing_list";
        const sideWord = isSalesDoc ? "SALES" : "PURCHASE";
        if (!window.confirm(
          `Delete ${sideWord} packing file?

${fname}

This will permanently remove the file and all ${doc.row_count ?? "?"} extracted rows from the database. ` + (isSalesDoc ? "The proforma draft must be deleted first if one exists. " : "") + "This cannot be undone."
        )) return;
        setPackingDeleting((prev) => ({ ...prev, [docId]: true }));
        try {
          const r = await apiFetch(
            `/api/v1/packing/${encodeURIComponent(batchId)}/document/${encodeURIComponent(docId)}`,
            { method: "DELETE" }
          );
          onToast(`Packing file deleted \u2014 ${r.deleted_lines ?? 0} rows removed.`, "success");
          await loadPackingInfo();
          await loadBatchReadiness();
        } catch (ex) {
          const detail = ex.detail || ex.message || String(ex);
          if (ex.status === 409 || detail && detail.includes("PROFORMA")) {
            const msg = (typeof detail === "object" ? detail.message : detail) || "Cannot delete: active proforma draft exists. Delete the proforma first.";
            onToast(msg, "error");
          } else {
            onToast("Delete failed: " + (typeof detail === "string" ? detail : JSON.stringify(detail)), "error");
          }
        } finally {
          setPackingDeleting((prev) => {
            const n = { ...prev };
            delete n[docId];
            return n;
          });
        }
      };
      return /* @__PURE__ */ React.createElement(Card, { style: { marginTop: 20 }, "data-testid": "packing-list-card" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F4E6} Packing List"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, "Packing list upload feeds Warehouse Audit and Sales Linkage.")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          variant: "outline",
          "data-testid": "packing-list-reparse-all",
          onClick: async () => {
            if (reparseBusy) return;
            setReparseBusy(true);
            setReparseSummary("");
            try {
              const r = await fetch(`/api/v1/packing/${encodeURIComponent(batchId)}/reprocess`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({})
              });
              if (!r.ok) {
                const msg = await r.text().catch(() => "Reparse failed");
                throw new Error(msg);
              }
              const data = await r.json();
              const s = data && data.summary ? data.summary : {};
              setReparseSummary(`Reparse complete: ${s.files ?? 0} files, ${s.rows ?? 0} rows (${s.purchase ?? 0} purchase, ${s.sales ?? 0} sales)`);
              refreshAll("reparse");
            } catch (e) {
              setReparseSummary("Reparse failed: " + (e.message || "unknown"));
            } finally {
              setReparseBusy(false);
            }
          },
          disabled: reparseBusy || packingInfoLoading || packingUploading
        },
        reparseBusy ? "Reparsing\u2026" : "\u27F3 Reparse all"
      ), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadPackingInfo, disabled: packingInfoLoading || packingUploading }, packingInfoLoading ? "Loading\u2026" : "\u21BA Refresh"), /* @__PURE__ */ React.createElement("label", { style: { cursor: packingUploading ? "not-allowed" : "pointer", display: "inline-block" } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "file",
          accept: ".pdf,.xlsx,.xls",
          style: { display: "none" },
          onChange: handlePackingUpload,
          disabled: packingUploading,
          "data-testid": "packing-list-upload-input"
        }
      ), /* @__PURE__ */ React.createElement("span", { style: {
        display: "inline-block",
        fontSize: 11,
        fontWeight: 600,
        padding: "5px 12px",
        borderRadius: 6,
        border: "1px solid var(--accent)",
        color: packingUploading ? "var(--text-3)" : "var(--accent)",
        background: "transparent",
        fontFamily: "inherit",
        lineHeight: 1,
        pointerEvents: packingUploading ? "none" : "auto"
      } }, packingUploading ? "Uploading\u2026" : "\u2191 Upload")))), packingInfoLoading && !pl && /* @__PURE__ */ React.createElement("div", { style: { padding: 16, textAlign: "center", color: "var(--text-3)", fontSize: 12 } }, "Loading packing info\u2026"), reparseSummary && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "packing-list-reparse-summary",
          style: {
            fontSize: 11,
            color: "var(--text-2)",
            padding: "6px 8px",
            marginBottom: 8,
            borderRadius: 4,
            background: "var(--bg-subtle)",
            border: "1px solid var(--border-subtle)"
          }
        },
        reparseSummary
      ), packingInfo && packingInfo.error && /* @__PURE__ */ React.createElement("div", { style: { padding: 12, fontSize: 12, color: "var(--badge-red-text)" } }, "Could not load packing data: ", packingInfo.error), !packingInfoLoading && !hasDoc && !(packingInfo && packingInfo.error) && /* @__PURE__ */ React.createElement("div", { style: { padding: "20px 0", textAlign: "center", color: "var(--text-3)", fontSize: 12 }, "data-testid": "packing-list-empty-state" }, "No packing list uploaded yet. Upload a PDF or XLSX to enable warehouse audit and sales linkage."), hasDoc && /* @__PURE__ */ React.createElement("div", { "data-testid": "packing-list-status" }, /* @__PURE__ */ (() => null)(), docs.map((doc, i) => {
        const fileName = (doc.source_file_path || "").split("/").pop() || doc.file_name || doc.invoice_no || "\u2014";
        const uploadedAt = doc.created_at ? doc.created_at.slice(0, 16).replace("T", " ") : "\u2014";
        const isLatest = i === 0;
        const isFallback = !!doc.fallback_unparsed;
        const sideRaw = (doc.side || "").toLowerCase();
        const isSales = sideRaw === "sales" || doc.document_type === "sales_packing_list";
        const sideLabel = isSales ? "SALES" : "PURCHASE";
        const sideBadgeBg = isSales ? "var(--badge-purple-bg, #f3e8ff)" : "var(--badge-blue-bg)";
        const sideBadgeText = isSales ? "var(--badge-purple-text, #6b21a8)" : "var(--badge-blue-text)";
        const sideBadgeBorder = isSales ? "var(--badge-purple-border, #c4b5fd)" : "var(--badge-blue-border)";
        const badgeBg = isFallback ? "var(--badge-amber-bg)" : "var(--badge-green-bg)";
        const badgeText = isFallback ? "var(--badge-amber-text)" : "var(--badge-green-text)";
        const badgeBorder = isFallback ? "var(--badge-amber-border)" : "var(--badge-green-border)";
        const badgeIcon = isFallback ? "\u23F3" : "\u2713";
        const badgeLabel = isFallback ? doc.extraction_status === "extraction_failed" ? "extraction failed" : "extraction pending" : doc.extraction_status || "extracted";
        const diag = doc.parser_diagnostic || null;
        const hasDiag = diag && Object.keys(diag).length > 0;
        const diagOpen = expandedDiagDocId === (doc.id || "row-" + i);
        const matched = diag && Array.isArray(diag.mapped_columns) ? diag.mapped_columns.map((m) => `${m.raw}\u2192${m.canonical_field}`).slice(0, 12) : [];
        const unmatched = diag && Array.isArray(diag.unmatched_columns) ? diag.unmatched_columns.slice(0, 20) : [];
        const sheetNames = diag && Array.isArray(diag.workbook_sheet_names) ? diag.workbook_sheet_names.join(", ") : "";
        return /* @__PURE__ */ React.createElement(React.Fragment, { key: doc.id || i }, /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": isFallback ? "packing-list-row-fallback" : "packing-list-row-parsed",
            style: {
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 0",
              borderBottom: !diagOpen && i < docs.length - 1 ? "1px solid var(--border-subtle)" : "none"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: { width: 32, height: 32, borderRadius: 6, background: isFallback ? "var(--badge-amber-bg)" : "var(--badge-blue-bg)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15 } }, "\u{1F4C4}"),
          /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: fileName }, fileName), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", null, uploadedAt), /* @__PURE__ */ React.createElement(
            "span",
            {
              "data-testid": isSales ? "packing-list-row-side-sales" : "packing-list-row-side-purchase",
              style: {
                fontSize: 9,
                fontWeight: 700,
                padding: "1px 6px",
                borderRadius: 3,
                background: sideBadgeBg,
                color: sideBadgeText,
                border: "1px solid " + sideBadgeBorder,
                letterSpacing: 0.4
              }
            },
            sideLabel
          ), isSales && typeof doc.row_count === "number" && doc.row_count > 0 && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-2)" } }, doc.row_count, " rows extracted"), !isSales && isLatest && !isFallback && lineCount > 0 && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-2)" } }, lineCount, " rows extracted"), isFallback && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-amber-text)" } }, "Uploaded \u2014 extraction pending or failed"))),
          hasDiag && /* @__PURE__ */ React.createElement(
            "button",
            {
              "data-testid": `packing-list-diagnostic-toggle-${doc.id || i}`,
              onClick: () => setExpandedDiagDocId(diagOpen ? null : doc.id || "row-" + i),
              style: {
                padding: "2px 8px",
                fontSize: 10,
                fontWeight: 600,
                background: "transparent",
                border: "1px solid var(--border)",
                borderRadius: 4,
                cursor: "pointer",
                color: "var(--text-2)",
                fontFamily: "inherit"
              },
              title: "Parser diagnostic"
            },
            diagOpen ? "\u25BE Diagnostic" : "\u25B8 Diagnostic"
          ),
          doc.id && /* @__PURE__ */ React.createElement(
            "a",
            {
              "data-testid": `packing-list-download-${doc.id}`,
              href: `/api/v1/packing/${encodeURIComponent(batchId)}/document/${encodeURIComponent(doc.id)}/download`,
              download: true,
              title: "Download original file",
              style: { textDecoration: "none" }
            },
            /* @__PURE__ */ React.createElement("button", { style: {
              padding: "2px 8px",
              fontSize: 11,
              fontWeight: 600,
              background: "transparent",
              border: "1px solid var(--badge-blue-border)",
              borderRadius: 4,
              cursor: "pointer",
              color: "var(--badge-blue-text)",
              fontFamily: "inherit",
              lineHeight: 1
            } }, "\u2B07")
          ),
          doc.id && /* @__PURE__ */ React.createElement(
            "button",
            {
              "data-testid": `packing-list-delete-${doc.id}`,
              onClick: () => handlePackingDelete(doc),
              disabled: !!packingDeleting[doc.id],
              title: "Delete this packing file and all extracted rows",
              style: {
                padding: "2px 8px",
                fontSize: 11,
                fontWeight: 600,
                background: "transparent",
                border: "1px solid var(--badge-red-border)",
                borderRadius: 4,
                cursor: packingDeleting[doc.id] ? "not-allowed" : "pointer",
                color: packingDeleting[doc.id] ? "var(--text-3)" : "var(--badge-red-text)",
                fontFamily: "inherit",
                lineHeight: 1
              }
            },
            packingDeleting[doc.id] ? "\u2026" : "\u{1F5D1}"
          ),
          /* @__PURE__ */ React.createElement("span", { style: {
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 8px",
            borderRadius: 4,
            background: badgeBg,
            color: badgeText,
            border: "1px solid " + badgeBorder
          } }, badgeIcon, " ", badgeLabel)
        ), hasDiag && diagOpen && /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": `packing-list-diagnostic-${doc.id || i}`,
            style: {
              padding: "10px 12px 12px",
              fontSize: 11,
              background: "var(--bg-subtle)",
              border: "1px solid var(--border-subtle)",
              borderRadius: 6,
              marginTop: 4,
              marginBottom: 8,
              borderBottom: i < docs.length - 1 ? "1px solid var(--border-subtle)" : "none",
              fontFamily: "ui-monospace, monospace",
              color: "var(--text-2)",
              whiteSpace: "normal"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Reason: "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-amber-text)", fontWeight: 700 } }, diag.failure_reason || "none")),
          /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Parser: "), diag.parser_name || "\u2014", " v", diag.parser_version || "?", " (", diag.file_type || "\u2014", ")"),
          sheetNames && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Sheets: "), sheetNames),
          /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Header detected: "), diag.chosen_header ? `yes (row ${diag.chosen_header.row_index} on "${diag.chosen_header.sheet}")` : "no"),
          diag.exception_class && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4, color: "var(--badge-red-text)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Exception: "), diag.exception_class, ": ", diag.exception_message || ""),
          matched.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Matched aliases: "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-green-text)" } }, matched.join(", "))),
          unmatched.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Raw columns seen (unmatched): "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text)" } }, unmatched.map((c) => JSON.stringify(c)).join(", "))),
          Array.isArray(diag.candidate_header_rows) && diag.candidate_header_rows.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Candidate header rows:"), diag.candidate_header_rows.slice(0, 5).map((c, ci) => /* @__PURE__ */ React.createElement("div", { key: ci, style: { paddingLeft: 12 } }, "\u2022 ", c.sheet, " row ", c.row_index, " (", c.alias_hits, " hits): ", (c.raw_cells_sample || []).slice(0, 8).map((x) => JSON.stringify(x)).join(", ")))),
          Array.isArray(diag.column_mapping_audit) && diag.column_mapping_audit.length > 0 && /* @__PURE__ */ React.createElement(
            "div",
            {
              "data-testid": `packing-list-mapping-audit-${doc.id || i}`,
              style: { marginTop: 8, borderTop: "1px solid var(--border-subtle)", paddingTop: 6 }
            },
            /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", marginBottom: 4, fontWeight: 600 } }, "Excel column mapping (", diag.column_mapping_audit.length, " columns):"),
            diag.column_mapping_audit.map((m, mi) => {
              const methodColor = m.method === "supplier_template" ? "var(--badge-green-text)" : m.method === "alias" ? "var(--badge-green-text)" : m.method === "fuzzy" ? "var(--badge-blue-text)" : m.method === "fuzzy_warning" ? "var(--badge-amber-text)" : m.method === "llm" ? "var(--badge-purple-text)" : (
                /* unresolved */
                "var(--badge-red-text)"
              );
              const methodBg = m.method === "supplier_template" ? "var(--badge-green-bg)" : m.method === "alias" ? "var(--badge-green-bg)" : m.method === "fuzzy" ? "var(--badge-blue-bg)" : m.method === "fuzzy_warning" ? "var(--badge-amber-bg)" : m.method === "llm" ? "var(--badge-purple-bg)" : (
                /* unresolved */
                "var(--badge-red-bg)"
              );
              const methodLabel = m.method === "supplier_template" ? "template" : m.method;
              const isAdvisory = m.method === "llm" || m.method === "unresolved" || m.method === "fuzzy_warning";
              return /* @__PURE__ */ React.createElement(
                "div",
                {
                  key: mi,
                  "data-testid": `mapping-audit-row-${m.method}`,
                  style: {
                    display: "flex",
                    gap: 6,
                    alignItems: "center",
                    marginBottom: 3,
                    paddingLeft: 4,
                    flexWrap: "wrap"
                  }
                },
                /* @__PURE__ */ React.createElement(
                  "span",
                  {
                    style: {
                      color: "var(--text-2)",
                      minWidth: 0,
                      maxWidth: 140,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      flex: "0 0 auto"
                    },
                    title: m.original_header
                  },
                  m.original_header || "(empty)"
                ),
                /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "\u2192"),
                /* @__PURE__ */ React.createElement("span", { style: {
                  color: m.canonical_field ? "var(--text)" : "var(--badge-red-text)",
                  fontWeight: 600
                } }, m.canonical_field || "\u2014"),
                /* @__PURE__ */ React.createElement("span", { style: {
                  fontSize: 9,
                  fontWeight: 700,
                  padding: "1px 5px",
                  borderRadius: 3,
                  background: methodBg,
                  color: methodColor,
                  border: "1px solid " + methodBg,
                  flexShrink: 0
                } }, methodLabel),
                typeof m.confidence === "number" && m.method !== "alias" && m.method !== "supplier_template" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 10, flexShrink: 0 } }, Math.round(m.confidence * 100), "%"),
                isAdvisory && /* @__PURE__ */ React.createElement(
                  "span",
                  {
                    "data-testid": "mapping-advisory-flag",
                    style: { color: "var(--badge-amber-text)", fontSize: 9, flexShrink: 0 }
                  },
                  "\u26A0 review"
                )
              );
            }),
            diag.column_mapping_audit.some((m) => m.method === "llm") && /* @__PURE__ */ React.createElement(
              "div",
              {
                "data-testid": "mapping-llm-advisory-copy",
                style: {
                  marginTop: 6,
                  padding: "4px 8px",
                  background: "var(--badge-purple-bg)",
                  color: "var(--badge-purple-text)",
                  borderRadius: 4,
                  fontSize: 10,
                  fontStyle: "italic"
                }
              },
              "AI/LLM suggestions are advisory only. They do not create products, customers, PZ, or wFirma records. Supplier templates are reused only after operator approval. AI suggestions are not saved automatically."
            ),
            diag.column_mapping_audit.some((m) => m.method === "llm") && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
              Btn,
              {
                small: true,
                variant: "outline",
                "data-testid": "approve-header-mapping-btn",
                onClick: async () => {
                  const llmMappings = diag.column_mapping_audit.filter((m) => m.method === "llm" && m.canonical_field).map((m) => ({ raw_header: m.original_header, canonical_field: m.canonical_field, col_index: m.col_index, source_method: m.method, operator_confirmed: true }));
                  if (!llmMappings.length) return;
                  const preview = llmMappings.map((m) => `  "${m.raw_header}" \u2192 ${m.canonical_field}`).join("\n");
                  const confirmed = window.confirm(
                    `Save ${llmMappings.length} AI-suggested mapping(s) as supplier templates?

${preview}

This stores them for all future uploads from this supplier.`
                  );
                  if (!confirmed) return;
                  try {
                    const r = await fetch(
                      `/api/v1/packing/${encodeURIComponent(batchId)}/approve-header-mapping`,
                      {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ document_id: doc.id || "", mappings: llmMappings })
                      }
                    );
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                      onToast("Approval failed: " + (data.detail || r.statusText));
                    } else {
                      onToast(`${data.approved_count || 0} mapping(s) approved and saved as supplier templates.`);
                    }
                  } catch (e) {
                    onToast("Approve failed: " + (e.message || "unknown"));
                  }
                }
              },
              "Approve selected mappings for this supplier"
            ), /* @__PURE__ */ React.createElement(
              "span",
              {
                "data-testid": "approve-header-mapping-note",
                style: { fontSize: 9, color: "var(--text-3)" }
              },
              "Supplier templates are reused only after operator approval. AI suggestions are not saved automatically."
            )),
            diag.column_mapping_audit.some((m) => m.method === "unresolved" || m.method === "fuzzy_warning") && /* @__PURE__ */ React.createElement(
              "div",
              {
                "data-testid": "mapping-unresolved-notice",
                style: {
                  marginTop: 4,
                  padding: "3px 8px",
                  background: "var(--badge-amber-bg)",
                  color: "var(--badge-amber-text)",
                  borderRadius: 4,
                  fontSize: 10
                }
              },
              diag.column_mapping_audit.filter((m) => m.method === "unresolved").length,
              " unresolved column(s) \u2014 operator review required before use."
            ),
            diag.column_mapping_audit.some((m) => m.method === "unresolved" || m.method === "fuzzy_warning") && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
              Btn,
              {
                small: true,
                variant: "outline",
                "data-testid": "suggest-column-mapping-btn",
                disabled: llmSuggestBusyDocId !== null,
                onClick: async () => {
                  const docIdForLlm = doc.id || "";
                  if (!docIdForLlm || llmSuggestBusyDocId !== null) return;
                  setLlmSuggestBusyDocId(docIdForLlm);
                  try {
                    const r = await fetch(
                      `/api/v1/packing/${encodeURIComponent(batchId)}/suggest-column-mapping`,
                      {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ document_id: docIdForLlm })
                      }
                    );
                    if (!r.ok) {
                      const msg = await r.text().catch(() => r.statusText);
                      throw new Error(msg);
                    }
                    setPackingInfoLoading(true);
                    try {
                      const pr = await fetch(`/api/v1/packing/${encodeURIComponent(batchId)}`);
                      if (pr.ok) setPackingInfo(await pr.json());
                    } finally {
                      setPackingInfoLoading(false);
                    }
                  } catch (e) {
                    onToast("AI column mapping failed: " + (e.message || "unknown"));
                  } finally {
                    setLlmSuggestBusyDocId(null);
                  }
                }
              },
              llmSuggestBusyDocId === (doc.id || "") ? "Requesting AI suggestions\u2026" : "Suggest column mapping with AI"
            ), /* @__PURE__ */ React.createElement(
              "span",
              {
                "data-testid": "suggest-column-mapping-advisory-note",
                style: { fontSize: 9, color: "var(--text-3)" }
              },
              "Advisory only \u2014 does not create business records."
            )),
            diag.llm_mapping_meta && /* @__PURE__ */ React.createElement(
              "div",
              {
                "data-testid": "llm-mapping-meta",
                style: { marginTop: 4, fontSize: 9, color: "var(--text-3)" }
              },
              "AI run: ",
              diag.llm_mapping_meta.triggered_at || "?",
              " \xB7 advisory_only: true"
            )
          )
        ));
      })));
    })(), (() => {
      const lr = laneReadiness;
      if (!lr || lr.error) return null;
      const s = lr.sales || {};
      const p = lr.purchase || {};
      const switchToAccounting = () => {
        try {
          setActiveTab && setActiveTab("PZ / Accounting");
        } catch (_) {
        }
      };
      const pzReady = !!p.pz_ready;
      const noPacking = (p.packing_rows || 0) === 0;
      const purchaseBg = noPacking ? "var(--bg-subtle)" : pzReady ? "var(--badge-blue-bg)" : "var(--badge-amber-bg)";
      const purchaseBorder = noPacking ? "var(--border-subtle)" : pzReady ? "var(--badge-blue-border)" : "var(--badge-amber-border)";
      const purchaseText = noPacking ? "var(--text-2)" : pzReady ? "var(--badge-blue-text)" : "var(--badge-amber-text)";
      const blockedLabel = Array.isArray(p.pz_blocked_by) && p.pz_blocked_by.length > 0 ? p.pz_blocked_by.join(", ") : "";
      const showSales = (s.drafts_total || 0) > 0;
      return /* @__PURE__ */ React.createElement("div", { style: {
        marginTop: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8
      } }, showSales && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "lane-readiness-sales",
          style: {
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 14px",
            background: "var(--badge-purple-bg, #f3e8ff)",
            border: "1px solid var(--badge-purple-border, #c4b5fd)",
            borderRadius: 6
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          width: 28,
          height: 28,
          borderRadius: 6,
          background: "var(--badge-purple-bg, #f3e8ff)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 14
        } }, "\u{1F9FE}"),
        /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 0.6,
          color: "var(--badge-purple-text, #6b21a8)"
        } }, "SALES LANE"), /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 12,
          color: "var(--text)",
          marginTop: 2,
          display: "flex",
          gap: 14,
          flexWrap: "wrap"
        } }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, s.drafts_total || 0), " drafts"), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, s.drafts_needs_review || 0), " need review"), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, s.drafts_posted || 0), " posted"), (s.drafts_post_failed || 0) > 0 && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-red-text)" } }, /* @__PURE__ */ React.createElement("strong", null, s.drafts_post_failed), " post failed"))),
        /* @__PURE__ */ React.createElement(
          "button",
          {
            "data-testid": "lane-readiness-sales-open-accounting",
            onClick: switchToAccounting,
            style: {
              padding: "4px 10px",
              fontSize: 11,
              fontWeight: 600,
              background: "transparent",
              border: "1px solid var(--badge-purple-border, #c4b5fd)",
              borderRadius: 4,
              cursor: "pointer",
              color: "var(--badge-purple-text, #6b21a8)",
              fontFamily: "inherit"
            }
          },
          "Open Accounting"
        )
      ), !showSales && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "lane-readiness-sales-empty",
          style: {
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 14px",
            background: "var(--bg-subtle)",
            border: "1px solid var(--border-subtle)",
            borderRadius: 6,
            fontSize: 11,
            color: "var(--text-3)"
          }
        },
        /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12 } }, "\u{1F9FE}"),
        /* @__PURE__ */ React.createElement("span", { style: {
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 0.6,
          color: "var(--text-2)"
        } }, "SALES LANE"),
        /* @__PURE__ */ React.createElement("span", null, "\xB7 Sales drafts: 0 \u2014 run Reparse all after upload")
      ), /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "lane-readiness-purchase",
          style: {
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 14px",
            background: purchaseBg,
            border: "1px solid " + purchaseBorder,
            borderRadius: 6
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          width: 28,
          height: 28,
          borderRadius: 6,
          background: purchaseBg,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 14
        } }, "\u{1F4E6}"),
        /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 0.6,
          color: purchaseText
        } }, "PURCHASE LANE"), /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 12,
          color: "var(--text)",
          marginTop: 2,
          display: "flex",
          gap: 14,
          flexWrap: "wrap"
        } }, /* @__PURE__ */ React.createElement("span", null, "products: ", /* @__PURE__ */ React.createElement("strong", null, p.products_ready || 0), " / ", /* @__PURE__ */ React.createElement("strong", null, p.distinct_product_codes || 0), " ready"), (p.products_missing || 0) > 0 && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, p.products_missing), " missing"), /* @__PURE__ */ React.createElement("span", { "data-testid": "lane-readiness-purchase-pz-status" }, "PZ:", " ", pzReady ? /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--badge-blue-text)" } }, "READY") : noPacking ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "awaiting packing") : /* @__PURE__ */ React.createElement("span", null, "blocked by ", /* @__PURE__ */ React.createElement("strong", null, blockedLabel)))))
      ));
    })(), /* @__PURE__ */ React.createElement(ContractorResolutionPanel, { batchId, packingInfo }), (() => {
      const dr = docRegistry;
      const isErr = dr && dr.error;
      const docs = dr && !isErr ? dr.documents || [] : [];
      const sectionStyle = { padding: 14, marginTop: 20 };
      const tblStyle = { width: "100%", borderCollapse: "collapse", fontSize: 11 };
      const thStyle = { textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--border)", fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", fontSize: 10, letterSpacing: "0.04em" };
      const tdStyle = { padding: "6px 8px", borderBottom: "1px solid var(--border-subtle)", color: "var(--text-2)", verticalAlign: "top" };
      const pillStyle = (kind) => {
        const map = {
          ok: { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
          warn: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
          err: { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)", border: "var(--badge-red-border)" },
          info: { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
          neutral: { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" }
        };
        const c = map[kind] || map.neutral;
        return { fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: c.bg, color: c.text, border: `1px solid ${c.border}`, display: "inline-block", whiteSpace: "nowrap" };
      };
      const statusKind = (s) => {
        const v = (s || "").toLowerCase();
        if (v === "complete" || v === "completed" || v === "ok" || v === "success") return "ok";
        if (v === "pending" || v === "in_progress" || v === "processing") return "warn";
        if (v === "failed" || v === "error" || v === "rejected") return "err";
        return "neutral";
      };
      const statusBadge = (s) => /* @__PURE__ */ React.createElement("span", { style: pillStyle(statusKind(s)) }, s || "\u2014");
      return /* @__PURE__ */ React.createElement(Card, { style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F4DA} Document Registry"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, "Structured records from ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, "shipment_documents"), ", with extracted fields per row.")), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadDocRegistry, disabled: docRegistryLoading }, docRegistryLoading ? "Loading\u2026" : "\u21BA Refresh")), docRegistryLoading && !dr && /* @__PURE__ */ React.createElement("div", { style: { padding: 24, textAlign: "center", color: "var(--text-3)", fontSize: 12 } }, "Loading registry\u2026"), isErr && /* @__PURE__ */ React.createElement("div", { style: { padding: 12, fontSize: 12, color: "var(--badge-red-text)" } }, "Registry failed: ", dr.error), dr && !isErr && docs.length === 0 && /* @__PURE__ */ React.createElement("div", { style: { padding: 24, textAlign: "center", color: "var(--text-3)", fontSize: 12 } }, "No documents registered yet."), dr && !isErr && docs.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: tblStyle }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: { ...thStyle, width: 24 } }), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Filename"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Type"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Parser"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Extraction"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Review"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Hash"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Created"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Lines / Fields"))), /* @__PURE__ */ React.createElement("tbody", null, docs.map((d, i) => {
        const isOpen = expandedDocId === d.id;
        const fields = d.fields || [];
        const fieldsTotal = d.fields_total ?? fields.length;
        const isInvoice = d.document_type === "purchase_invoice" || d.document_type === "sales_invoice";
        const linesCount = d.lines_count;
        const linesPreview = d.lines_preview || [];
        let countCell;
        if (isInvoice) {
          if (typeof linesCount === "number") {
            countCell = linesCount > 0 ? /* @__PURE__ */ React.createElement("span", { "data-testid": "doc-registry-lines-count" }, linesCount, d.lines_truncated ? "+" : "", " lines") : d.extraction_status === "extraction_failed" ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-amber-text)" } }, "extraction failed") : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "no lines");
          } else {
            countCell = /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "\u2014");
          }
        } else {
          countCell = /* @__PURE__ */ React.createElement("span", null, fieldsTotal, d.fields_truncated ? "+" : "", fieldsTotal > 0 ? " fields" : "");
        }
        return /* @__PURE__ */ React.createElement(React.Fragment, { key: d.id || i }, /* @__PURE__ */ React.createElement("tr", { "data-testid": isInvoice ? "doc-registry-row-invoice" : "doc-registry-row-other", style: { cursor: "pointer" }, onClick: () => setExpandedDocId(isOpen ? null : d.id) }, /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, color: "var(--text-3)" } }, isOpen ? "\u25BE" : "\u25B8"), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace", color: "var(--text)", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: d.canonical_file_name || d.file_name }, d.canonical_file_name || d.file_name || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, d.document_type || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, statusBadge(d.parser_status)), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, statusBadge(d.extraction_status)), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, d.requires_manual_review ? /* @__PURE__ */ React.createElement("span", { style: pillStyle("err") }, "Review") : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "\u2014")), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace", fontSize: 10 }, title: d.file_hash }, (d.file_hash || "").slice(0, 8) || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, d.created_at ? d.created_at.slice(0, 16).replace("T", " ") : "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, countCell)), isOpen && /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("td", { colSpan: 9, style: { padding: "0 8px 12px", background: "var(--bg-subtle)", borderBottom: "1px solid var(--border-subtle)" } }, isInvoice && linesPreview.length > 0 ? /* @__PURE__ */ React.createElement("div", { "data-testid": "doc-registry-invoice-preview" }, /* @__PURE__ */ React.createElement("table", { style: { ...tblStyle, marginTop: 8, marginBottom: 4, marginLeft: 16 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "#"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Invoice"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Product"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Description"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Qty"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Unit"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Total"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Currency"))), /* @__PURE__ */ React.createElement("tbody", null, linesPreview.map((ln, li) => /* @__PURE__ */ React.createElement("tr", { key: ln.id || li }, /* @__PURE__ */ React.createElement("td", { style: tdStyle }, ln.line_position ?? li + 1), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace" } }, ln.invoice_no || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace" } }, ln.product_code || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: ln.description }, ln.description || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, ln.quantity ?? 0), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, typeof ln.unit_price === "number" ? ln.unit_price.toFixed(2) : ln.unit_price || 0), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, typeof ln.total_value === "number" ? ln.total_value.toFixed(2) : ln.total_value || 0), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, ln.currency || "\u2014"))))), d.lines_truncated && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", padding: "4px 16px 8px" } }, "Showing first ", linesPreview.length, " of ", linesCount, " lines.")) : isInvoice ? /* @__PURE__ */ React.createElement("div", { "data-testid": "doc-registry-invoice-empty", style: { fontSize: 11, color: "var(--text-3)", padding: "12px 4px" } }, d.extraction_status === "extraction_failed" ? "Invoice extraction failed. Re-upload or run Recheck after fixing the source PDF." : d.parser_status === "pending" || d.extraction_status === "pending" ? "Invoice extraction pending \u2014 run Recheck to parse." : "No invoice lines extracted for this document.") : fields.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", padding: "12px 4px" } }, "No extracted fields for this document.") : /* @__PURE__ */ React.createElement("table", { style: { ...tblStyle, marginTop: 8, marginBottom: 4, marginLeft: 16 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Field"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Value"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Confidence"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Verified"))), /* @__PURE__ */ React.createElement("tbody", null, fields.map((fd2, fi) => /* @__PURE__ */ React.createElement("tr", { key: fi }, /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace", color: "var(--text)" } }, fd2.field_name), /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace", maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: fd2.normalized_value }, fd2.normalized_value || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, typeof fd2.confidence === "number" ? fd2.confidence.toFixed(2) : "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, fd2.verified_status === "verified" ? /* @__PURE__ */ React.createElement("span", { style: pillStyle("ok") }, "Verified") : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, fd2.verified_status || "unverified")))))), !isInvoice && d.fields_truncated && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", padding: "4px 16px 8px" } }, "Showing first 50 of ", fieldsTotal, " fields."))));
      })))));
    })());
  })(), activeTab === "Timeline" && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, alignItems: "center" } }, [["all", "All Events"], ["ai_bridge", "\u21CC AI Bridge"]].map(([id, label]) => /* @__PURE__ */ React.createElement(
    "button",
    {
      key: id,
      onClick: () => setTimelineFilter(id),
      style: {
        fontSize: 11,
        padding: "4px 12px",
        borderRadius: 12,
        border: "1px solid var(--border)",
        cursor: "pointer",
        fontFamily: "inherit",
        background: timelineFilter === id ? "var(--accent)" : "transparent",
        color: timelineFilter === id ? "#fff" : "var(--text-muted)",
        fontWeight: timelineFilter === id ? 700 : 400
      }
    },
    label
  )), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-muted)", marginLeft: 6 } }, timelineFilter === "ai_bridge" ? `${timeline.filter((e) => (e.event || "").startsWith("ai_bridge") || e.event === "column_mapping_llm_requested").length} events` : `${timeline.length} events`)), (() => {
    const rawEvents = dbEvents.length > 0 ? dbEvents.map((e) => ({
      ...e,
      event_id: e.id,
      raw_description: e.description,
      requires_manual_review: !!e.requires_manual_review
    })) : Array.isArray(audit && audit.tracking_events) ? audit.tracking_events : [];
    const events = rawEvents;
    const STAGE_COLOR = {
      SHIPMENT_CREATED: "#6b7280",
      LABEL_CREATED: "#6b7280",
      PICKED_UP: "#2563eb",
      DEPARTED_ORIGIN: "#2563eb",
      ARRIVED_ORIGIN_HUB: "#2563eb",
      DEPARTED_ORIGIN_HUB: "#2563eb",
      IN_TRANSIT: "#2563eb",
      ARRIVED_DESTINATION_COUNTRY: "#0891b2",
      CUSTOMS_PENDING: "#d97706",
      CUSTOMS_DOCUMENTS_REQUESTED: "#dc2626",
      CUSTOMS_DOCUMENTS_SENT: "#16a34a",
      CUSTOMS_UNDER_REVIEW: "#d97706",
      CUSTOMS_CLEARED: "#16a34a",
      HANDED_TO_BROKER: "#7c3aed",
      OUT_FOR_DELIVERY: "#d97706",
      DELIVERED: "#16a34a",
      EXCEPTION: "#dc2626",
      CLOSED: "#6b7280"
    };
    const SOURCE_LABEL = {
      dhl_api: "DHL API",
      public_tracking: "Public",
      manual: "Manual",
      email: "Email",
      system: "System"
    };
    const allEventsForDisplay = events.slice().sort((a, b) => (b.event_time || "").localeCompare(a.event_time || ""));
    return /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 12px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" } }, "Goods Movement Timeline ", events.length > 0 && /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 400 } }, "\xB7 ", events.length, " event", events.length !== 1 ? "s" : "", dbEvents.length > 0 ? " (DB)" : "")), events.length > 0 && /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: async () => {
          try {
            await fetch(`/api/v1/tracking/events/export`, { method: "POST", credentials: "include" });
            window.open("/api/v1/tracking/events/export/download", "_blank");
          } catch (e) {
          }
        },
        style: { fontSize: 9, padding: "2px 7px", borderRadius: 3, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text-2)", cursor: "pointer" }
      },
      "\u2193 Export XLSX"
    )), events.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", fontStyle: "italic" } }, "No movement events recorded yet.") : /* @__PURE__ */ React.createElement("div", null, allEventsForDisplay.map((ev, i) => {
      const displayStage = ev.normalized_stage || ev.stage || "UNKNOWN";
      const stageColor = STAGE_COLOR[displayStage] || "#6b7280";
      const needsReview = ev.requires_manual_review;
      const isWorkflowOnly = ev.stage && !ev.normalized_stage;
      return /* @__PURE__ */ React.createElement("div", { key: ev.event_id || ev.id || i, style: { display: "flex", gap: 8, marginBottom: 6, alignItems: "flex-start" } }, /* @__PURE__ */ React.createElement("span", { style: { marginTop: 3, width: 7, height: 7, borderRadius: isWorkflowOnly ? "2px" : "50%", background: stageColor, flexShrink: 0, display: "inline-block" } }), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, alignItems: "center", flexWrap: "wrap", marginBottom: 1 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: stageColor } }, displayStage.replace(/_/g, " ")), isWorkflowOnly && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, padding: "1px 4px", borderRadius: 3, background: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe", fontWeight: 600 } }, "workflow"), needsReview && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, padding: "1px 4px", borderRadius: 3, background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a", fontWeight: 600 } }, "review"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, color: "var(--text-3)" } }, "via ", SOURCE_LABEL[ev.source] || ev.source)), (ev.raw_description || ev.description) && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", lineHeight: 1.3 } }, ev.raw_description || ev.description), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, fontSize: 9, color: "var(--text-3)", marginTop: 1 } }, ev.event_time && /* @__PURE__ */ React.createElement("span", null, ev.event_time.slice(0, 16).replace("T", " ")), ev.location && /* @__PURE__ */ React.createElement("span", null, "\u{1F4CD} ", ev.location), ev.confidence != null && ev.confidence < 0.9 && ev.confidence > 0 && /* @__PURE__ */ React.createElement("span", { style: { opacity: 0.6 } }, "conf ", Math.round(ev.confidence * 100), "%"))));
    })));
  })(), /* @__PURE__ */ React.createElement(Card, { style: { padding: 28 } }, (() => {
    const AI_BRIDGE_EVENTS = /* @__PURE__ */ new Set(["ai_bridge_task_created", "ai_bridge_result_received", "column_mapping_llm_requested"]);
    const filtered = timelineFilter === "ai_bridge" ? timeline.filter((e) => AI_BRIDGE_EVENTS.has(e.event)) : timeline;
    if (filtered.length === 0) return /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", color: "var(--text-3)", padding: 40 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 32, marginBottom: 8, opacity: 0.3 } }, "\u23F1"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13 } }, timelineFilter === "ai_bridge" ? "No AI Bridge events recorded" : "No timeline events recorded"));
    return /* @__PURE__ */ React.createElement("div", { style: { position: "relative", paddingLeft: 32 } }, /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", left: 7, top: 0, bottom: 0, width: 2, background: "var(--border)" } }), filtered.map((e, i) => {
      const done = e.done || e.status === "done" || e.completed;
      const EVENT_LABELS = {
        "column_mapping_llm_requested": "AI: column mapping suggestions requested"
      };
      const label = e.label || EVENT_LABELS[e.event] || e.event || e.action || e.message || `Event ${i + 1}`;
      const ts = e.ts || e.timestamp || e.time || e.date;
      const isAiBridge = AI_BRIDGE_EVENTS.has(e.event);
      return /* @__PURE__ */ React.createElement("div", { key: i, style: { position: "relative", marginBottom: 20, display: "flex", alignItems: "flex-start", gap: 14 } }, /* @__PURE__ */ React.createElement("div", { style: {
        position: "absolute",
        left: -32,
        width: 16,
        height: 16,
        borderRadius: "50%",
        background: isAiBridge ? "#EFF6FF" : done ? GOLD : "var(--card)",
        border: `2px solid ${isAiBridge ? "#93C5FD" : done ? GOLD : "var(--badge-neutral-border)"}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1,
        top: 1
      } }, isAiBridge && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 8, color: "#1D4ED8" } }, "\u21CC"), !isAiBridge && done && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 7, color: "var(--text)" } }, "\u2713")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 12,
        fontWeight: isAiBridge || done ? 600 : 400,
        color: isAiBridge ? "#1D4ED8" : done ? "var(--text)" : "var(--text-3)"
      } }, label), e.actor && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 1 } }, "actor: ", e.actor), ts && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 1 } }, new Date(ts).toLocaleString("pl-PL")), !ts && done && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 1 } }, "Completed")));
    }));
  })()), audit && (audit.ai_bridge_results || []).length > 0 && /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "#1D4ED8", marginBottom: 10 } }, "\u21CC AI Bridge Results"), (audit.ai_bridge_results || []).map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "8px 10px", background: "#EFF6FF", border: "1px solid #93C5FD", borderRadius: 6, marginBottom: 6, fontSize: 11 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "#1D4ED8", fontWeight: 600 } }, r.task_type || r.type || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-muted)", fontFamily: "monospace" } }, (r.task_id || "").slice(0, 12), "\u2026"), r.confidence && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-muted)" } }, "confidence: ", r.confidence), r.tool_used && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-muted)" } }, "tool: ", r.tool_used), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto", color: "var(--text-muted)" } }, r.timestamp ? new Date(r.timestamp).toLocaleString("pl-PL") : ""))))), audit && (audit.ai_bridge_errors || []).length > 0 && /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "#B91C1C", marginBottom: 10 } }, "\u26A0 AI Bridge Rejected Results"), (audit.ai_bridge_errors || []).map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "8px 10px", background: "#FEF2F2", border: "1px solid #FCA5A5", borderRadius: 6, marginBottom: 6, fontSize: 11 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "#B91C1C", fontWeight: 600 } }, "REJECTED"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-muted)", fontFamily: "monospace" } }, (r.task_id || "").slice(0, 12), "\u2026"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-muted)" } }, r.task_type || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto", color: "var(--text-muted)" } }, r.timestamp ? new Date(r.timestamp).toLocaleString("pl-PL") : "")), /* @__PURE__ */ React.createElement("div", { style: { color: "#B91C1C", marginTop: 4 } }, r.reason))))), activeTab === "Intelligence" && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u25C8 Live Intelligence Status"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadIntelligence, disabled: intelLoading }, intelLoading ? "\u27F3 Loading\u2026" : "\u21BB Refresh")), intelData?.error && /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 14px", background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)", borderRadius: 6, fontSize: 12, color: "var(--badge-red-text)" } }, intelData.error), intelLoading && !intelData && /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", color: "var(--text-3)", padding: 40 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 24, animation: "spin 1s linear infinite", display: "inline-block" } }, "\u27F3")), intelData && !intelData.error && (() => {
    const slaW = intelData.sla_warnings || [];
    const sug = intelData.suggestions || [];
    const risks = intelData.risk_warnings || [];
    const sla = intelData.sla_summary || {};
    const last = intelData.last_event;
    const next = intelData.next_step;
    const highSug = sug.filter((s) => s.confidence === "high");
    const highSla = slaW.filter((w) => w.severity === "HIGH");
    const highRisk = risks.filter((r) => r.severity === "HIGH");
    const totalAlerts = highSug.length + highSla.length + highRisk.length;
    return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 32, flexWrap: "wrap", alignItems: "center" } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.06em" } }, "Active Alerts"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 22, fontWeight: 800, color: totalAlerts > 0 ? "var(--badge-red-text)" : "var(--badge-green-text)" } }, totalAlerts)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.06em" } }, "SLA"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, color: highSla.length > 0 ? "var(--badge-red-text)" : slaW.length > 0 ? "var(--badge-amber-text)" : "var(--badge-green-text)" } }, sla.full_sla_pct != null ? `${sla.full_sla_pct}% used` : "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.06em" } }, "Timeline depth"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 600, color: "var(--text)" } }, intelData.timeline_depth, " events")), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, intelData.generated_at ? new Date(intelData.generated_at).toLocaleString("pl-PL") : ""))), /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.06em" } }, "Last Detected Event"), last ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-start" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "3px 10px", background: "var(--badge-blue-bg)", borderRadius: 4, fontSize: 11, fontWeight: 700, color: "var(--badge-blue-text)", fontFamily: "monospace", whiteSpace: "nowrap" } }, last.event), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 200 } }, last.actor && last.actor !== "system" && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 2 } }, "via ", last.actor), last.ts && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, new Date(last.ts).toLocaleString("pl-PL")), (last.detail?.awb || last.detail?.mrn || last.detail?.pln_amount) && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10, marginTop: 4, flexWrap: "wrap" } }, last.detail.awb && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "AWB: ", last.detail.awb), last.detail.mrn && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "MRN: ", last.detail.mrn), last.detail.pln_amount && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--badge-amber-text)", fontWeight: 700 } }, last.detail.pln_amount, " PLN")))) : /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-3)", fontStyle: "italic" } }, "No email-sourced events on timeline yet")), next && /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px", borderLeft: "3px solid var(--accent)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" } }, "Next Expected Step"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text)", lineHeight: 1.5 } }, next)), slaW.length > 0 && /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.06em" } }, "SLA Warnings (", slaW.length, ")"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, slaW.map((w, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "8px 12px", borderRadius: 6, background: w.severity === "HIGH" ? "var(--badge-red-bg)" : "var(--badge-amber-bg)", border: `1px solid ${w.severity === "HIGH" ? "var(--badge-red-border)" : "var(--badge-amber-border)"}`, display: "flex", gap: 12, alignItems: "flex-start" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: w.severity === "HIGH" ? "var(--badge-red-text)" : "var(--badge-amber-text)", whiteSpace: "nowrap", paddingTop: 1 } }, w.severity), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, color: "var(--text)", marginBottom: 2, fontFamily: "monospace" } }, w.code), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)" } }, w.message), w.elapsed_h != null && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, w.elapsed_h.toFixed(1), "h elapsed")))))), sug.length > 0 && /* @__PURE__ */ React.createElement(Card, { style: { padding: "14px 20px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.06em" } }, "Cowork Suggestions (", sug.length, ")"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, sug.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "8px 12px", borderRadius: 6, background: "var(--bg-subtle)", border: "1px solid var(--border)", display: "flex", gap: 12, alignItems: "flex-start" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, fontWeight: 700, color: s.confidence === "high" ? "var(--badge-red-text)" : s.confidence === "medium" ? "var(--badge-amber-text)" : "var(--text-3)", textTransform: "uppercase", whiteSpace: "nowrap", paddingTop: 2 } }, s.confidence), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text)", marginBottom: 2, fontFamily: "monospace" } }, s.trigger), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 3 } }, s.reason), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", fontStyle: "italic" } }, "\u2192 ", s.action)))))), totalAlerts === 0 && sug.length === 0 && !intelLoading && /* @__PURE__ */ React.createElement(Card, { style: { padding: 28, textAlign: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 28, marginBottom: 8 } }, "\u2713"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "var(--badge-green-text)", fontWeight: 600 } }, "No active alerts"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-3)", marginTop: 4 } }, "SLA on track \xB7 No triggers detected")));
  })()), activeTab === "Proposals" && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u26A1 Action Proposals"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadProposals, disabled: proposalsLoading }, proposalsLoading ? "Loading\u2026" : "\u21BA Refresh")), proposalsLoading && proposals.length === 0 && /* @__PURE__ */ React.createElement(Card, { style: { padding: 24, textAlign: "center", color: "var(--text-3)", fontSize: 12 } }, "Loading proposals\u2026"), !proposalsLoading && proposals.length === 0 && /* @__PURE__ */ React.createElement(Card, { style: { padding: 28, textAlign: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 28, marginBottom: 8 } }, "\u2713"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "var(--badge-green-text)", fontWeight: 600 } }, "No pending proposals"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-3)", marginTop: 4 } }, "All cowork triggers resolved \xB7 No action required")), proposals.map((p) => {
    const statusColor = {
      pending_review: "var(--badge-amber-text)",
      approved: "var(--badge-green-text)",
      queued: "#6366f1",
      rejected: "var(--badge-red-text)",
      sent: "var(--badge-green-text)",
      done: "var(--badge-green-text)"
    }[p.status] || "var(--text-3)";
    const statusBg = {
      pending_review: "var(--badge-amber-bg)",
      approved: "var(--badge-green-bg)",
      queued: "#ede9fe",
      rejected: "var(--badge-red-bg)",
      sent: "var(--badge-green-bg)",
      done: "var(--badge-green-bg)"
    }[p.status] || "var(--bg-2)";
    const draft = p.draft || {};
    const busy2 = proposalsBusy[p.proposal_id];
    const isPending = p.status === "pending_review";
    const isApproved = p.status === "approved";
    const isDone = p.status === "done";
    const isTrackingLookup = p.type === "tracking_lookup";
    const proposalIsPrimary = !!(topProposalId && topProposalId === p.proposal_id);
    const canApprove = p.can_approve;
    const approveDisabledReason = p.approve_blocked_reason;
    return /* @__PURE__ */ React.createElement(Card, { key: p.proposal_id, style: { padding: 16, borderLeft: `4px solid ${statusColor}`, outline: proposalIsPrimary && isPending ? "2px solid var(--badge-green-border)" : void 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "var(--text)", fontFamily: "monospace" } }, p.type), isTrackingLookup && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "#dbeafe", color: "#1d4ed8" } }, "COWORK TASK"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: statusBg, color: statusColor, textTransform: "uppercase" } }, p.status.replace(/_/g, " ")), p.confidence && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: p.confidence === "high" ? "var(--badge-red-text)" : p.confidence === "medium" ? "var(--badge-amber-text)" : "var(--text-3)", textTransform: "uppercase", fontWeight: 600 } }, p.confidence)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 4 } }, p.reason)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" } }, p.created_at ? new Date(p.created_at).toLocaleString("pl-PL") : "")), isTrackingLookup && /* @__PURE__ */ React.createElement("div", { style: { background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 6, padding: "8px 10px", fontSize: 11, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, color: "#1e40af", marginBottom: 4 } }, "\u{1F50D} ", draft.instruction || "Fetch latest status from public tracking page"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "#3b82f6" } }, "AWB:"), " ", draft.awb || p.awb || ""), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "#3b82f6" } }, "Carrier:"), " ", draft.carrier || ""), draft.tracking_url && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement(
      "a",
      {
        href: draft.tracking_url,
        target: "_blank",
        rel: "noopener noreferrer",
        style: { fontSize: 11, fontWeight: 600, color: "#1d4ed8", textDecoration: "none", padding: "3px 8px", border: "1px solid #93c5fd", borderRadius: 4, background: "#dbeafe" }
      },
      "\u2197 Open Public Tracking"
    ))), !isTrackingLookup && draft.to && /* @__PURE__ */ React.createElement("div", { style: { background: "var(--bg-2)", borderRadius: 6, padding: "8px 10px", fontSize: 11, marginBottom: 10, fontFamily: "monospace", lineHeight: 1.6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "To:"), " ", draft.to), draft.cc && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "CC:"), " ", draft.cc), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Subject:"), " ", draft.subject), (draft.attachments || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Attachments:"), " ", (draft.attachments || []).map((a) => /* @__PURE__ */ React.createElement("span", { key: a.label, style: { background: "var(--bg-3)", borderRadius: 3, padding: "1px 5px", marginRight: 4, color: "var(--text-2)" } }, a.label)))), p.approved_by && !isTrackingLookup && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-green-text)", marginBottom: 8 } }, "\u2713 Approved by ", p.approved_by, p.approved_at ? ` at ${new Date(p.approved_at).toLocaleString("pl-PL")}` : ""), p.status === "rejected" && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-red-text)", marginBottom: 8 } }, "\u2717 Rejected by ", p.rejected_by, ": ", p.reject_reason), isDone && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-green-text)", marginBottom: 8 } }, "\u2713 Done", p.done_at ? ` \xB7 ${p.done_at.slice(0, 19).replace("T", " ")}` : "", p.done_source ? ` via ${p.done_source}` : ""), p.email_id && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 8 } }, "Queue ID: ", /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace" } }, p.email_id)), isTrackingLookup && (isPending || isApproved) && !isDone && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "primary", disabled: busy2, onClick: () => {
      const status2 = window.prompt("Tracking status (in_transit / delivered / customs / out_for_delivery / exception / unknown):", "in_transit");
      if (!status2) return;
      const lastEv = window.prompt("Last event:", "");
      if (lastEv === null) return;
      const location = window.prompt("Location (e.g. WARSAW - PL):", "");
      setProposalsBusy((prev) => ({ ...prev, [p.proposal_id]: true }));
      apiFetch(`/api/v1/tracking/batch/${encodeURIComponent(batchId)}/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: status2,
          last_event: lastEv,
          location: location || "",
          source: "operator_manual",
          proposal_id: p.proposal_id
        })
      }).then(() => {
        onToast("Tracking updated.", "success");
        loadProposals();
        fetchTracking(true);
      }).catch((e) => onToast(e.message || "Failed", "error")).finally(() => setProposalsBusy((prev) => ({ ...prev, [p.proposal_id]: false })));
    } }, busy2 ? "\u2026" : "\u2713 Mark as Done"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", disabled: busy2, onClick: () => {
      const reason = window.prompt("Reject reason:");
      if (reason) proposalAction(p.proposal_id, "reject", { rejected_by: "admin", reason });
    } }, busy2 ? "\u2026" : "\u2717 Reject")), !isTrackingLookup && (isPending || isApproved) && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, isPending && approveDisabledReason && /* @__PURE__ */ React.createElement("div", { "data-testid": "proposal-approve-disabled-reason", style: { fontSize: 10, color: "var(--badge-amber-text)", padding: "4px 8px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 4 } }, "\u26A0 Approve disabled \u2014 ", approveDisabledReason), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" } }, isPending && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "primary",
        "data-testid": "proposal-approve-btn",
        disabled: busy2 || !canApprove,
        style: { opacity: !canApprove ? 0.45 : 1, cursor: !canApprove ? "not-allowed" : "pointer" },
        onClick: () => {
          const approver = window.prompt("Approve as (enter your name/email):");
          if (approver) proposalAction(p.proposal_id, "approve", { approved_by: approver });
        }
      },
      busy2 ? "\u2026" : "\u2713 Approve"
    ), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", disabled: busy2, onClick: () => {
      const reason = window.prompt("Reject reason:");
      if (reason) proposalAction(p.proposal_id, "reject", { rejected_by: "admin", reason });
    } }, busy2 ? "\u2026" : "\u2717 Reject")), isApproved && /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "primary", disabled: busy2, onClick: () => {
      if (window.confirm(`Queue email to ${draft.to}?

This will add the email to the send queue. No email is auto-sent.`)) {
        proposalAction(p.proposal_id, "queue", {});
      }
    } }, busy2 ? "Queuing\u2026" : "\u2192 Queue Email"))));
  })), activeTab === "Warehouse" && (() => {
    const wa = warehouseAudit;
    const isErr = wa && wa.error;
    const summary = wa && !isErr ? wa.summary || {} : {};
    const missing = wa && !isErr ? wa.missing_scans || [] : [];
    const stuck = wa && !isErr ? wa.stuck_inventory || [] : [];
    const invalid = wa && !isErr ? wa.invalid_flows || [] : [];
    const orphans = wa && !isErr ? wa.orphan_inventory || [] : [];
    const isTransit = !!(invState && (invState.synthetic === true || invState.total > 0 && invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)) && ((invState.counts || {}).PURCHASE_TRANSIT || 0) > 0);
    const displayMissing = isTransit ? [] : missing;
    const cleanGate = !isErr && displayMissing.length === 0 && stuck.length === 0 && invalid.length === 0 && orphans.length === 0;
    const sectionStyle = { padding: 14, marginBottom: 12 };
    const headStyle = { fontSize: 12, fontWeight: 700, color: "var(--text)", marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center" };
    const tblStyle = { width: "100%", borderCollapse: "collapse", fontSize: 11 };
    const thStyle = { textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--border)", fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", fontSize: 10, letterSpacing: "0.04em" };
    const tdStyle = { padding: "6px 8px", borderBottom: "1px solid var(--border-subtle)", color: "var(--text-2)" };
    const badge = (n, color) => /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: n === 0 ? "var(--badge-green-bg)" : color.bg, color: n === 0 ? "var(--badge-green-text)" : color.text } }, n);
    const wfExp = audit && audit.wfirma_export || {};
    const hasPzDocId = !!(wfExp.wfirma_pz_doc_id && String(wfExp.wfirma_pz_doc_id).trim());
    const lifecycleState = (() => {
      if (!wa || isErr) return "unknown";
      const total = Number(summary.total_items || 0);
      const scanned = Number(summary.scanned_items || 0);
      const dispatched = Number(summary.dispatched_items || 0);
      if (total === 0) return "unknown";
      if (dispatched > 0 && dispatched >= total) return "dispatched";
      if (dispatched > 0) return "partial_dispatch";
      if (isTransit) return "in_transit";
      if (scanned === 0) return "awaiting";
      if (scanned < total) return "partial_received";
      if (hasPzDocId) return "reserved";
      return "in_warehouse";
    })();
    const lifecycleLabel = {
      unknown: "No packing list",
      in_transit: "In transit / Awaiting warehouse receive",
      // C13D
      awaiting: "Awaiting receipt",
      partial_received: "Partially received",
      in_warehouse: "In warehouse",
      reserved: "Reserved (PZ created)",
      partial_dispatch: "Partial dispatch",
      dispatched: "Dispatched"
    }[lifecycleState] || "No packing list";
    const lifecycleTone = {
      unknown: { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" },
      in_transit: { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
      // C13D
      awaiting: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
      partial_received: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
      in_warehouse: { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
      reserved: { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
      partial_dispatch: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
      dispatched: { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" }
    }[lifecycleState] || { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" };
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } }, /* @__PURE__ */ React.createElement(
      ReadinessBanner,
      {
        "data-testid": "readiness-banner-warehouse",
        domain: "warehouse",
        status: batchReadiness && batchReadiness.warehouse ? batchReadiness.warehouse.status : null,
        ready: batchReadiness && batchReadiness.warehouse ? batchReadiness.warehouse.ready : false,
        message: batchReadiness && batchReadiness.warehouse ? batchReadiness.warehouse.message : null,
        loading: batchReadinessLoading && !batchReadiness,
        error: batchReadinessError
      }
    ), /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "warehouse-inventory-lifecycle-badge",
        "data-lifecycle-state": lifecycleState,
        style: { display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-2)" }
      },
      /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Inventory lifecycle:"),
      /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": "warehouse-inventory-lifecycle-pill",
          style: { fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: lifecycleTone.bg, color: lifecycleTone.text, border: `1px solid ${lifecycleTone.border}`, display: "inline-block", whiteSpace: "nowrap" }
        },
        lifecycleLabel
      ),
      /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "Derived from warehouse audit + wFirma PZ state \u2014 no manual control.")
    ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F4E6} Warehouse Audit"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadWarehouseAudit, disabled: warehouseAuditLoading }, warehouseAuditLoading ? "Loading\u2026" : "\u21BA Refresh")), warehouseAuditLoading && !wa && /* @__PURE__ */ React.createElement(Card, { style: { padding: 24, textAlign: "center", color: "var(--text-3)", fontSize: 12 } }, "Loading audit\u2026"), isErr && /* @__PURE__ */ React.createElement(Card, { style: { padding: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--badge-red-text)", fontWeight: 600 } }, "Audit failed: ", wa.error)), wa && !isErr && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Card, { style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "var(--text)" } }, "Completion Summary"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 18, flexWrap: "wrap", fontSize: 11, color: "var(--text-2)" } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Total:"), " ", /* @__PURE__ */ React.createElement("b", null, summary.total_items ?? 0)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Scanned:"), " ", /* @__PURE__ */ React.createElement("b", null, summary.scanned_items ?? 0)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Dispatched:"), " ", /* @__PURE__ */ React.createElement("b", null, summary.dispatched_items ?? 0)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Missing:"), " ", /* @__PURE__ */ React.createElement("b", { style: { color: (summary.missing_items || 0) > 0 ? "var(--badge-red-text)" : "var(--text)" } }, summary.missing_items ?? 0)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Completion:"), " ", /* @__PURE__ */ React.createElement("b", null, summary.completion_pct ?? 0, "%"))))), /* @__PURE__ */ React.createElement(Card, { style: { ...sectionStyle, background: cleanGate ? "var(--badge-green-bg)" : "var(--badge-amber-bg)", border: `1px solid ${cleanGate ? "var(--badge-green-border)" : "var(--badge-amber-border)"}` } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: cleanGate ? "var(--badge-green-text)" : "var(--badge-amber-text)" } }, cleanGate ? "\u2713 Audit clean \u2014 reservation gate OPEN" : "\u26A0 Audit issues present \u2014 reservation gate BLOCKED"), !cleanGate && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 4 } }, "Resolve all sections below before creating a wFirma reservation.")), /* @__PURE__ */ React.createElement(Card, { style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: headStyle }, /* @__PURE__ */ React.createElement("span", null, "Missing scans ", badge(displayMissing.length, { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)" })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", fontWeight: 400 } }, "Packing lines not yet scanned into warehouse")), isTransit && missing.length > 0 ? /* @__PURE__ */ React.createElement(
      "div",
      {
        style: { fontSize: 11, color: "var(--badge-blue-text)", background: "var(--badge-blue-bg)", border: "1px solid var(--badge-blue-border)", borderRadius: 4, padding: "6px 10px" },
        "data-testid": "warehouse-transit-note"
      },
      missing.length,
      " item(s) in transit (PURCHASE_TRANSIT) \u2014 goods are en route, not yet received at warehouse. No action required until delivery."
    ) : displayMissing.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, "No missing scans.") : /* @__PURE__ */ React.createElement("table", { style: tblStyle }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Expected scan code"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Product"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Design"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Pcs"))), /* @__PURE__ */ React.createElement("tbody", null, displayMissing.slice(0, 200).map((m, i) => /* @__PURE__ */ React.createElement("tr", { key: i }, /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace" } }, m._expected_scan_code || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, m.product_code || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, m.design_no || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, m.qty ?? m.quantity ?? "\u2014"))))), displayMissing.length > 200 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 6 } }, "Showing first 200 of ", displayMissing.length, ".")), /* @__PURE__ */ React.createElement(Card, { style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: headStyle }, /* @__PURE__ */ React.createElement("span", null, "Stuck inventory ", badge(stuck.length, { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)" })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", fontWeight: 400 } }, "Items at RECV* > 24h since last move")), stuck.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, "No stuck items.") : /* @__PURE__ */ React.createElement("table", { style: tblStyle }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Scan code"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Location"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Status"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Hours"))), /* @__PURE__ */ React.createElement("tbody", null, stuck.slice(0, 200).map((s, i) => /* @__PURE__ */ React.createElement("tr", { key: i }, /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace" } }, s.scan_code), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, s.current_location || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, s.current_status || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, s._stuck_hours ?? "\u2014")))))), /* @__PURE__ */ React.createElement(Card, { style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: headStyle }, /* @__PURE__ */ React.createElement("span", null, "Invalid flows ", badge(invalid.length, { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)" })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", fontWeight: 400 } }, "Out-of-order scan sequences")), invalid.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, "No flow violations.") : /* @__PURE__ */ React.createElement("table", { style: tblStyle }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Scan code"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Violation"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Actions observed"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "First event"))), /* @__PURE__ */ React.createElement("tbody", null, invalid.slice(0, 200).map((v, i) => /* @__PURE__ */ React.createElement("tr", { key: i }, /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace" } }, v.scan_code), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, v.violation), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, (v.actions_observed || []).join(" \u2192 ")), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, v.first_event_time ? v.first_event_time.slice(0, 16).replace("T", " ") : "\u2014")))))), /* @__PURE__ */ React.createElement(Card, { style: sectionStyle }, /* @__PURE__ */ React.createElement("div", { style: headStyle }, /* @__PURE__ */ React.createElement("span", null, "Orphan scans ", badge(orphans.length, { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)" })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", fontWeight: 400 } }, "Scanned codes not in packing data")), orphans.length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, "No orphan scans.") : /* @__PURE__ */ React.createElement("table", { style: tblStyle }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Scan code"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Location"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Status"), /* @__PURE__ */ React.createElement("th", { style: thStyle }, "Updated"))), /* @__PURE__ */ React.createElement("tbody", null, orphans.slice(0, 200).map((o, i) => /* @__PURE__ */ React.createElement("tr", { key: i }, /* @__PURE__ */ React.createElement("td", { style: { ...tdStyle, fontFamily: "ui-monospace,monospace" } }, o.scan_code), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, o.current_location || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, o.current_status || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: tdStyle }, o.updated_at ? o.updated_at.slice(0, 16).replace("T", " ") : "\u2014"))))))));
  })(), activeTab === "Sales" && (() => {
    const sl = salesLinkage;
    const isErr = sl && sl.error;
    const summary = sl && !isErr ? sl.summary || {} : {};
    const items = sl && !isErr ? sl.items || [] : [];
    const warnings = sl && !isErr ? sl.audit_warnings || [] : [];
    const blockingReasons = sl && !isErr ? sl.blocking_reasons || [] : [];
    const ready = sl && !isErr ? !!sl.ready_for_invoice : false;
    const blocked = sl && !isErr ? !!sl.blocked : false;
    const displayReasons = blockingReasons.length > 0 ? blockingReasons : warnings;
    const groups = {};
    for (const it of items) {
      const key = (it.client_name || "\u2014") + " | " + (it.client_ref || "");
      if (!groups[key]) groups[key] = { client_name: it.client_name || "\u2014", client_ref: it.client_ref || "", rows: [] };
      groups[key].rows.push(it);
    }
    const groupList = Object.values(groups);
    const sectionStyle = { padding: 14, marginBottom: 12 };
    const tblStyle = { width: "100%", borderCollapse: "collapse", fontSize: 11 };
    const thStyle = { textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--border)", fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", fontSize: 10, letterSpacing: "0.04em" };
    const tdStyle = { padding: "6px 8px", borderBottom: "1px solid var(--border-subtle)", color: "var(--text-2)" };
    const isTransit = !!(invState && (invState.synthetic === true || invState.total > 0 && invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)) && ((invState.counts || {}).PURCHASE_TRANSIT || 0) > 0);
    const STATUS_BADGE = {
      ready: { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", label: "Ready" },
      pending_dispatch: { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", label: "Pending dispatch" },
      not_ready: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", label: "Not ready" },
      missing_scan: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", label: "Pending arrival" },
      // C14A: amber not red; "pending arrival" while in transit
      in_transit: { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", label: "In transit" }
    };
    const statusBadge = (s) => {
      const c = STATUS_BADGE[s] || { bg: "var(--bg-2)", text: "var(--text-3)", label: s || "\u2014" };
      return /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: c.bg, color: c.text } }, c.label);
    };
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { "data-testid": "sales-tab-proforma-draft-panel" }, /* @__PURE__ */ React.createElement(ProformaDraftPanel, { batchId, onToast })), /* @__PURE__ */ React.createElement(
      ReadinessBanner,
      {
        "data-testid": "readiness-banner-sales",
        domain: "sales",
        status: batchReadiness && batchReadiness.sales ? batchReadiness.sales.status : null,
        ready: batchReadiness && batchReadiness.sales ? batchReadiness.sales.ready : false,
        message: batchReadiness && batchReadiness.sales ? batchReadiness.sales.message : null,
        loading: batchReadinessLoading && !batchReadiness,
        error: batchReadinessError
      }
    ));
  })(), activeTab === "PZ / Accounting" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(OperatorWorkflowCard, { batchId, onToast }), /* @__PURE__ */ React.createElement(GlobalPZLineageCard, { batchId, onToast }), /* @__PURE__ */ React.createElement(GlobalPZCorrectionProposalCard, { batchId, onToast }), /* @__PURE__ */ React.createElement(
    "details",
    {
      "data-testid": "legacy-pz-details",
      style: {
        marginBottom: 16,
        border: "1px solid var(--border,#e5e7eb)",
        borderRadius: 8,
        background: "var(--bg-soft,#f9fafb)",
        padding: 8
      }
    },
    /* @__PURE__ */ React.createElement(
      "summary",
      {
        "data-testid": "legacy-pz-summary",
        style: {
          cursor: "pointer",
          fontSize: 12,
          fontWeight: 700,
          color: "var(--text-2,#6b7280)",
          padding: "4px 8px"
        }
      },
      "Advanced / legacy reservation & PZ panel",
      /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 400, marginLeft: 8 } }, "(download buttons + raw section views)")
    ),
    /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement(
      SectionHeader,
      {
        icon: "\u229E",
        title: "Section 3 \u2014 PZ / Accounting",
        subtitle: "Goods receipt document, wFirma export, and audit files",
        status: hasSad ? pzGenerated ? "Generated" : "Ready for PZ" : "Locked"
      }
    ), !hasSad ? /* @__PURE__ */ React.createElement("div", { style: { padding: 28, textAlign: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 32, marginBottom: 10 } }, "\u{1F512}"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, color: "var(--text)", marginBottom: 4 } }, "PZ Locked"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2)" } }, "SAD / ZC429 required before PZ generation")) : /* @__PURE__ */ React.createElement("div", { style: { padding: 20 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 16 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "PZ Details"), /* @__PURE__ */ React.createElement(InfoRow, { label: "PZ Status", value: pzGenerated ? "Generated" : "Ready for PZ" }), (() => {
      const wf = audit && audit.wfirma_export || {};
      const canonName = (wf.wfirma_pz_fullnumber || "").trim();
      const sourceLabel = canonName ? "\u2713 canonical \xB7 auto-mapped from wFirma" : audit && audit.doc_no ? "\u26A0 manual entry \xB7 refresh mapping or re-create to canonicalise" : "";
      return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(InfoRow, { label: "PZ / Doc Number", value: pzNumber || "\u2014", mono: true }), sourceLabel && /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 10,
        color: "var(--text-3)",
        marginTop: -4,
        marginBottom: 6,
        paddingLeft: 2
      } }, sourceLabel), wf.wfirma_pz_doc_id && /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "wFirma PZ ID",
          value: wf.wfirma_pz_doc_id,
          mono: true
        }
      ));
    })(), /* @__PURE__ */ React.createElement(InfoRow, { label: "Net Value", value: fmtPLN(t.net) }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Gross Value", value: fmtPLN(t.gross) }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Duty A00", value: fmtPLN(t.duty) }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Line Count", value: audit.totals?.line_count ?? audit.line_count ?? "\u2014" }), (() => {
      const it = audit.invoice_totals || {};
      const pbu = it.product_counts_by_unit || {};
      const pcs = it.total_pcs ?? null;
      const prs = it.total_prs ?? null;
      if (pcs === null && prs === null) return null;
      const fmtCats = (obj) => Object.entries(obj || {}).filter(([, v]) => v > 0).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" \xB7 ");
      return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8 } }, /* @__PURE__ */ React.createElement(InfoRow, { label: "Total Units", value: String(it.total_units ?? pcs + prs) }), (pcs > 0 || prs > 0) && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, padding: "8px 10px", background: "var(--bg-subtle)", borderRadius: 5, border: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 } }, "Unit Breakdown"), pcs > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "baseline", gap: 6, fontSize: 11, marginBottom: 3 } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: "var(--badge-blue-text)", minWidth: 28 } }, "PCS"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: "var(--text)" } }, pcs), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 10 } }, fmtCats(pbu.PCS))), prs > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "baseline", gap: 6, fontSize: 11, marginBottom: 3 } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: "var(--badge-green-text)", minWidth: 28 } }, "PRS"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: "var(--text)" } }, prs), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 10 } }, fmtCats(pbu.PRS))), (() => {
        const qv = it.qty_validation;
        if (!qv) return null;
        const ok = qv.status === "ok";
        return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--border)", display: "flex", alignItems: "flex-start", gap: 5 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: ok ? "var(--badge-green-text)" : "var(--badge-red-text)", flexShrink: 0 } }, ok ? "\u2713" : "\u26A0"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: ok ? "var(--badge-green-text)" : "var(--badge-red-text)", lineHeight: 1.4 } }, ok ? qv.note || "Quantity consistent" : `Mismatch: ${qv.total_from_lines} from lines vs ${qv.calculated_total_items} calculated`));
      })()));
    })()), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "Verification Summary"), /* @__PURE__ */ React.createElement(InfoRow, { label: "Run Status", value: status === "success" ? "\u2713 Clean" : status === "partial" ? "\u26A0 Verification Gaps" : status === "blocked" ? "\u2717 Blocked" : status ? status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Not processed" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Amendment Flags", value: audit.amendment_flags?.length ? `${audit.amendment_flags.length} flag(s)` : "None" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Engine Version", value: audit.engine_version || "\u2014" }))), confirmingPz && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16, padding: 14, background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, marginBottom: 8, color: "var(--text)" } }, "Enter PZ Number or Document ID"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement(
      Inp,
      {
        "data-testid": "input-pz-number-confirm",
        value: pzNumber,
        onChange: (e) => setPzNumber(e.target.value),
        placeholder: "PZ 9/5/2026  or  185759075",
        style: { flex: 1 }
      }
    ), /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "gold",
        "data-testid": "btn-confirm-pz-number",
        disabled: !pzNumber || !pzNumber.trim() || !!busy.setPz,
        title: !pzNumber || !pzNumber.trim() ? "Enter a PZ number or document ID first" : "",
        onClick: async () => {
          const _t = (pzNumber || "").trim();
          if (!_t) return;
          const payload = /^\d+$/.test(_t) ? { pz_doc_id: _t } : { pz_number: _t };
          await doAction("setPz", "Confirm PZ Number", async () => {
            const r = await fetch(
              `/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_confirm`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                credentials: "include"
              }
            );
            let _rj = null;
            try {
              _rj = await r.json();
            } catch (_) {
            }
            if (!r.ok) {
              const reason = _rj?.detail?.error || Array.isArray(_rj?.detail) && _rj.detail[0]?.msg || _rj?.message || `Confirm PZ failed (${r.status})`;
              throw new Error(String(reason));
            }
            return _rj;
          });
          setConfirmingPz(false);
        }
      },
      busy.setPz ? "\u27F3 Confirming\u2026" : "Confirm"
    ), /* @__PURE__ */ React.createElement(Btn, { variant: "outline", onClick: () => setConfirmingPz(false) }, "Cancel"))), /* @__PURE__ */ React.createElement(CNHSNDecisionPanel, { batchId, onToast: (m) => alert(m) }), !v2Active && (() => {
      const sadDecision = audit && audit.agency_sad_decision || {};
      const sadDecisionPresent = sadDecision.safe_to_run_pz !== void 0;
      const canRunPZ = !sadDecisionPresent || sadDecision.safe_to_run_pz === true;
      const sadBlockReason = !canRunPZ ? sadDecision.reason || "Blocked by SAD validation" : "";
      const runPzDisabled = !!busy.runPz || status === "blocked" || !canRunPZ;
      const runPzTitle = status === "blocked" ? "Blocked \u2014 resolve verification mismatch before reprocessing" : status === "failed" ? "Previous run failed \u2014 click to retry" : status === "processing" ? "Previous run may be stuck \u2014 click to restart" : !canRunPZ ? `SAD validation: ${sadBlockReason}` : "";
      return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" } }, (() => {
        const vi = audit && audit.vision_invoice || null;
        if (!vi) return null;
        const items = Array.isArray(vi.line_items) ? vi.line_items : [];
        const fob = Number(vi.fob_usd) || items.reduce((s, it) => s + (Number(it.total_usd) || 0), 0);
        const qty = items.reduce((s, it) => s + (Number(it.quantity) || 0), 0);
        if (vi.operator_confirmed === true) {
          return /* @__PURE__ */ React.createElement(
            "span",
            {
              "data-testid": "vision-invoice-confirmed",
              title: `Confirmed by ${vi.confirmed_by || "operator"}${vi.confirmed_at ? " at " + vi.confirmed_at : ""}`,
              style: { display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, padding: "6px 10px", borderRadius: 4, background: "var(--badge-green-bg)", color: "var(--badge-green-text)", border: "1px solid var(--badge-green-border)" }
            },
            "\u2713 Scanned invoice confirmed (FOB $",
            fob.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
            ", ",
            qty,
            " pcs) \u2014 Run PZ to generate"
          );
        }
        const noItems = items.length === 0;
        return /* @__PURE__ */ React.createElement(
          Btn,
          {
            variant: "gold",
            "data-testid": "confirm-vision-invoice",
            disabled: !!busy.confirmVision || noItems,
            style: noItems ? { opacity: 0.5 } : {},
            title: noItems ? "OCR found no line items on the scanned invoice \u2014 manual entry required before PZ can run" : "Confirm the OCR/AI-read invoice line items so the PZ engine can generate the goods receipt",
            onClick: () => doAction("confirmVision", "Confirm scanned invoice", async () => {
              const res = await fetch(`/dashboard/batches/${encodeURIComponent(batchId)}/vision-invoice/confirm`, { method: "POST", credentials: "include" });
              if (!res.ok) {
                const t2 = await res.text().catch(() => "");
                throw new Error(`HTTP ${res.status}: ${t2.slice(0, 200)}`);
              }
              const body = await res.json().catch(() => ({}));
              if (body && body.next_step) onToast(body.next_step, "info");
              return body;
            })
          },
          busy.confirmVision ? "\u27F3 Confirming\u2026" : noItems ? "\u26D4 Scanned invoice \u2014 no line items" : `\u2713 Confirm scanned invoice (FOB $${fob.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}, ${qty} pcs) \u2192 unblock PZ`
        );
      })(), /* @__PURE__ */ React.createElement(Btn, { variant: "gold", disabled: runPzDisabled, style: !canRunPZ && !busy.runPz && status !== "blocked" ? { opacity: 0.5 } : {}, title: runPzTitle, onClick: () => doAction("runPz", "Run PZ", async () => {
        const res = await fetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/process`, { method: "POST", credentials: "include" });
        if (res.status === 409) {
          let body = {};
          try {
            body = await res.json();
          } catch {
          }
          if (body.error === "sad_validation_blocked") {
            let msg = `SAD validation blocked PZ run: ${body.reason || "unknown"}`;
            if (body.mrn_parsed) msg += ` \u2014 Parsed MRN: ${body.mrn_parsed}`;
            if (body.mrn_declared) msg += ` \u2014 Declared MRN: ${body.mrn_declared}`;
            throw new Error(msg);
          }
          let detail = "";
          try {
            const b = await res.json();
            detail = b.detail || JSON.stringify(b);
          } catch {
            detail = await res.text().catch(() => "");
          }
          throw new Error(`Cannot run PZ: ${detail.slice(0, 300)}`);
        }
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
        }
        return res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
      }) }, busy.runPz ? "\u27F3 Processing\u2026" : status === "blocked" ? "\u2717 PZ Blocked" : !canRunPZ ? "\u26D4 SAD validation failed" : status === "failed" ? "\u21BA Retry PZ" : status === "processing" ? "\u21BA Restart PZ" : pzGenerated ? "\u21BA Regenerate PZ" : "\u25B6 Run PZ"), pzGenerated && (() => {
        const wf = audit && audit.wfirma_export || {};
        const canonId = (wf.wfirma_pz_doc_id || "").trim();
        const canonName = (wf.wfirma_pz_fullnumber || "").trim();
        const mapped = !!(canonId && canonName);
        return mapped ? /* @__PURE__ */ React.createElement(
          Btn,
          {
            variant: "outline",
            title: `Re-fetch full_number from wFirma for ${canonId}`,
            onClick: async () => {
              await doAction("refreshPzMapping", "Refresh Mapping", async () => {
                const r = await fetch(
                  `/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz/refresh-mapping`,
                  {
                    method: "POST",
                    credentials: "include",
                    headers: { "X-Operator": localStorage.getItem("pz_operator_name") || "" }
                  }
                );
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
              });
              await load();
            }
          },
          "\u21BB Refresh Mapping"
        ) : /* @__PURE__ */ React.createElement(Btn, { variant: "outline", onClick: () => setConfirmingPz(true) }, "\u270E Confirm PZ Number");
      })(), [
        ["pz_pdf", "PZ PDF", "Run PZ to generate this file."],
        ["calc_xlsx", "Calc XLSX", "Run PZ to generate this file."],
        ["audit_en", "Audit EN", "Audit report not generated yet \u2014 run PZ."],
        ["audit_pl", "Audit PL", "Audit report not generated yet \u2014 run PZ."],
        ["audit_memo", "Memo", "Audit memo not generated yet \u2014 run PZ."],
        ["corrections", "Corrections", "No correction report \u2014 run PZ to generate."]
      ].map(([key, label, missingReason]) => fileExists(key) && fileUrl(key) ? /* @__PURE__ */ React.createElement("a", { key, href: fileUrl(key), target: "_blank", rel: "noreferrer", style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { variant: "outline", title: `Download ${label}` }, "\u2193 ", label)) : /* @__PURE__ */ React.createElement(
        Btn,
        {
          key,
          variant: "ghost",
          disabled: true,
          title: `File not generated yet \u2014 ${missingReason}`
        },
        "\u2193 ",
        label
      )));
    })(), pzGenerated && hasSad && (!audit.polish_desc_filename || !audit.dsk_filename) && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 12px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 5, fontSize: 11, color: "var(--badge-amber-text)" } }, /* @__PURE__ */ React.createElement("strong", null, "\u23ED Next step:"), " ", !audit.polish_desc_filename && !audit.dsk_filename ? 'Use Section 1 \u2192 "Generate Polish Desc." and "Generate DSK" to complete the customs package.' : !audit.polish_desc_filename ? 'Use Section 1 \u2192 "Generate Polish Desc." to complete the customs package.' : 'Use Section 1 \u2192 "Generate DSK" to complete the customs package.')))),
    /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement(
      SectionHeader,
      {
        icon: "\u{1F3ED}",
        title: "wFirma Warehouse",
        subtitle: "Import PZ \u2014 create warehouse receipt in wFirma",
        status: pzPreview?.wfirma_pz_doc_id ? "Created" : !hasSad ? "Locked" : !pzGenerated ? "Locked" : pzPreview?.ready ? "Ready" : pzPreview ? "Not ready" : "Loading"
      }
    ), !hasSad || !pzGenerated ? /* @__PURE__ */ React.createElement("div", { style: { padding: "20px 24px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", background: "var(--bg-subtle)", borderRadius: 6, border: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 20 } }, "\u{1F512}"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "var(--text)", marginBottom: 2 } }, "wFirma warehouse locked \u2014 PZ not generated"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)" } }, !hasSad ? "Upload SAD/ZC429 and run PZ first." : "Run PZ processing to unlock wFirma warehouse.")))) : /* @__PURE__ */ React.createElement("div", { style: { padding: "20px 24px" } }, pzPreview?.wfirma_pz_doc_id && /* @__PURE__ */ React.createElement("div", { "data-testid": "pz-already-created-banner", style: { marginBottom: 8, padding: "10px 14px", background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16 } }, "\u2713"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "var(--badge-green-text)" } }, "wFirma PZ created"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-green-text)", opacity: 0.85, fontFamily: "monospace" } }, pzPreview.wfirma_pz_doc_id, pzPreview.wfirma_pz_fullnumber && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 8, opacity: 0.7 } }, "\xB7 ", pzPreview.wfirma_pz_fullnumber)))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" } }, pzPreview.wfirma_pz_view_url && /* @__PURE__ */ React.createElement(
      "a",
      {
        "data-testid": "btn-pz-view-wfirma",
        href: pzPreview.wfirma_pz_view_url,
        target: "_blank",
        rel: "noopener noreferrer",
        style: { fontSize: 11, padding: "4px 10px", border: "1px solid var(--badge-green-border)", borderRadius: 4, color: "var(--badge-green-text)", textDecoration: "none", whiteSpace: "nowrap", background: "transparent" }
      },
      "View in wFirma \u2192"
    ), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "outline",
        "data-testid": "btn-view-pz",
        disabled: pzDocumentLoading,
        onClick: () => pzDocumentOpen ? setPzDocumentOpen(false) : loadPzDocument()
      },
      pzDocumentLoading ? "\u27F3 Loading\u2026" : pzDocumentOpen ? "\u25B2 Hide PZ" : "\u25BC View PZ"
    ))), pzDocumentOpen && pzDocumentData && /* @__PURE__ */ React.createElement("div", { "data-testid": "pz-document-panel", style: { marginBottom: 16, border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden", fontSize: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 14px", background: "var(--bg-subtle)", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: "var(--text)", fontSize: 13 } }, pzDocumentData.pz_number || `PZ ${pzDocumentData.pz_doc_id}`), pzDocumentData.status && /* @__PURE__ */ React.createElement(Badge, { label: pzDocumentData.status, status: pzDocumentData.status === "confirmed" ? "Completed" : "Pending", small: true, style: { marginLeft: 8 } })), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "ghost", "data-testid": "btn-pz-document-close", onClick: () => setPzDocumentOpen(false) }, "\u2715")), /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 14px", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "6px 20px", borderBottom: "1px solid var(--border-subtle)", fontSize: 11 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Document ID "), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", color: "var(--text-2)" } }, pzDocumentData.pz_doc_id)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Date "), /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, pzDocumentData.date || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Currency "), /* @__PURE__ */ React.createElement("span", null, pzDocumentData.currency || "PLN")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Source "), /* @__PURE__ */ React.createElement("span", null, pzDocumentData.pz_source === "created_via_app" ? "Created via app" : pzDocumentData.pz_source === "adopted_existing" ? "Adopted existing" : pzDocumentData.pz_source || "\u2014")), /* @__PURE__ */ React.createElement("div", { style: { gridColumn: "1 / -1" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Contractor "), /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, pzDocumentData.contractor_name || "\u2014"), pzDocumentData.contractor_id && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontFamily: "monospace", fontSize: 10, marginLeft: 6 } }, "ID ", pzDocumentData.contractor_id)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Warehouse ID "), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", color: "var(--text-2)" } }, pzDocumentData.warehouse_id || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Lines "), /* @__PURE__ */ React.createElement("b", null, pzDocumentData.line_count ?? pzDocumentData.lines?.length ?? "\u2014"))), pzDocumentData.description && /* @__PURE__ */ React.createElement("div", { "data-testid": "pz-document-notes", style: { padding: "8px 14px", borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-subtle)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 } }, "Audit notes"), /* @__PURE__ */ React.createElement("pre", { style: { margin: 0, fontFamily: "monospace", fontSize: 11, color: "var(--text-2)", whiteSpace: "pre-wrap", lineHeight: 1.5 } }, pzDocumentData.description)), pzDocumentData.lines?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--sidebar-bg)" } }, ["#", "Good ID", "Description", "Qty", "Unit price netto (PLN)", "Line total (PLN)"].map((h) => /* @__PURE__ */ React.createElement("th", { key: h, style: { padding: "5px 10px", textAlign: h === "Qty" || h.startsWith("Unit") || h.startsWith("Line") ? "right" : "left", fontSize: 10, fontWeight: 700, color: "white", whiteSpace: "nowrap" } }, h)))), /* @__PURE__ */ React.createElement("tbody", null, pzDocumentData.lines.map((ln, i) => {
      const lineTotal = (ln.count || 0) * (ln.price_netto || 0);
      return /* @__PURE__ */ React.createElement("tr", { key: i, style: { borderBottom: "1px solid var(--border-subtle)", background: i % 2 === 0 ? "transparent" : "var(--bg-subtle)" } }, /* @__PURE__ */ React.createElement("td", { style: { padding: "5px 10px", color: "var(--text-3)", fontSize: 10, textAlign: "right" } }, i + 1), /* @__PURE__ */ React.createElement("td", { style: { padding: "5px 10px", fontFamily: "monospace", color: "var(--text-2)", fontSize: 10, whiteSpace: "nowrap" } }, ln.good_id || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { padding: "5px 10px", color: "var(--text)", maxWidth: 320 } }, ln.name || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { padding: "5px 10px", textAlign: "right", fontVariantNumeric: "tabular-nums" } }, ln.count), /* @__PURE__ */ React.createElement("td", { style: { padding: "5px 10px", textAlign: "right", fontFamily: "monospace" } }, (ln.price_netto || 0).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })), /* @__PURE__ */ React.createElement("td", { style: { padding: "5px 10px", textAlign: "right", fontFamily: "monospace", fontWeight: 600 } }, lineTotal.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })));
    })), (pzDocumentData.netto_total > 0 || pzDocumentData.brutto_total > 0) && /* @__PURE__ */ React.createElement("tfoot", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--bg-subtle)", borderTop: "2px solid var(--border)" } }, /* @__PURE__ */ React.createElement("td", { colSpan: 4, style: { padding: "6px 10px", fontWeight: 700, fontSize: 11, color: "var(--text-2)" } }, "Totals"), /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px", textAlign: "right", fontFamily: "monospace", fontWeight: 700 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "Netto"), (pzDocumentData.netto_total || 0).toLocaleString("pl-PL", { minimumFractionDigits: 2 })), /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px", textAlign: "right", fontFamily: "monospace", fontWeight: 700 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "Brutto"), (pzDocumentData.brutto_total || 0).toLocaleString("pl-PL", { minimumFractionDigits: 2 })))))), !pzDocumentData.lines?.length && /* @__PURE__ */ React.createElement("div", { style: { padding: "12px 14px", color: "var(--text-3)", fontSize: 11 } }, "No line items in wFirma response."), /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "pz-document-pdf-note",
        style: {
          padding: "8px 14px",
          background: "var(--bg-subtle)",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap"
        }
      },
      /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10.5, color: "var(--text-3)", fontStyle: "italic", flex: "1 1 auto" } }, "PZ PDF download is not available through confirmed wFirma API. Verified PZ data shown from wFirma document API."),
      /* @__PURE__ */ React.createElement(
        "a",
        {
          "data-testid": "btn-pz-download-generated-pdf",
          href: `/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_document.pdf`,
          target: "_blank",
          rel: "noopener noreferrer",
          style: { fontSize: 11, fontWeight: 700, color: "var(--accent)", textDecoration: "underline", whiteSpace: "nowrap", flexShrink: 0 }
        },
        "\u2193 Generated PDF"
      )
    )), pzPreview?.pz_lifecycle && (() => {
      const _lf = pzPreview.pz_lifecycle;
      const _alarming = _lf.state === "PZ_RECOVERY_REQUIRED" || _lf.state === "PZ_DUPLICATE_DETECTED" || _lf.state === "PZ_LOCKED" || _lf.state === "PZ_RECONCILED";
      if (!_alarming) return null;
      let _tone, _headline, _subtitle;
      if (_lf.state === "PZ_RECOVERY_REQUIRED") {
        _tone = "red";
        _headline = "PZ recovery required";
        _subtitle = "PZ was created in wFirma, but local audit mapping is missing. Confirm the existing PZ to recover.";
      } else if (_lf.state === "PZ_DUPLICATE_DETECTED") {
        _tone = "red";
        _headline = "Duplicate wFirma PZ doc id detected";
        _subtitle = _lf.duplicate_owner_batch_id ? `Doc id is claimed by batch ${_lf.duplicate_owner_batch_id}. Resolve cross-batch conflict before proceeding.` : "A wFirma PZ doc id is claimed by another batch. Resolve cross-batch conflict before proceeding.";
      } else if (_lf.state === "PZ_LOCKED") {
        _tone = "neutral";
        _headline = "PZ locked";
        _subtitle = "Batch locked by accounting period close or operator hold.";
      } else {
        _tone = "amber";
        _headline = "PZ mapping cleared \u2014 recreate when ready";
        _subtitle = "The previous wFirma PZ was unlinked. A new PZ can be created when all gates pass.";
      }
      const _bg = {
        red: "var(--badge-red-bg)",
        amber: "var(--badge-amber-bg)",
        neutral: "var(--bg-subtle)"
      }[_tone];
      const _bd = {
        red: "var(--badge-red-border)",
        amber: "var(--badge-amber-border)",
        neutral: "var(--border)"
      }[_tone];
      const _fg = {
        red: "var(--badge-red-text)",
        amber: "var(--badge-amber-text)",
        neutral: "var(--text-2)"
      }[_tone];
      const _icon = _tone === "red" ? "\u2717" : _tone === "amber" ? "\u26A0" : "\u{1F512}";
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "pz-lifecycle-banner",
          "data-state": _lf.state,
          "data-primary-action": _lf.primary_action || "",
          style: {
            marginBottom: 12,
            padding: "12px 16px",
            background: _bg,
            border: `1px solid ${_bd}`,
            borderRadius: 6
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16, color: _fg } }, _icon), /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: _fg } }, _headline), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: _fg, opacity: 0.9, marginTop: 3 } }, _subtitle)))
      );
    })(), pzPreview?.pz_lock_status && !(pzPreview?.pz_lifecycle && (pzPreview.pz_lifecycle.state === "PZ_RECOVERY_REQUIRED" || pzPreview.pz_lifecycle.state === "PZ_DUPLICATE_DETECTED" || pzPreview.pz_lifecycle.state === "PZ_LOCKED" || pzPreview.pz_lifecycle.state === "PZ_RECONCILED")) && (() => {
      const ls = pzPreview.pz_lock_status;
      const tone = ls.recovery_required ? "red" : ls.locked ? "green" : pzPreview.unresolved_count > 0 || pzPreview.conflict_count > 0 || (pzPreview.unresolved_product_codes || []).length > 0 || (pzPreview.price_conflicts || []).length > 0 ? "amber" : ls.can_create ? "neutral" : "amber";
      const _bg = {
        green: "var(--badge-green-bg)",
        amber: "var(--badge-amber-bg)",
        red: "var(--badge-red-bg)",
        neutral: "var(--bg-subtle)"
      }[tone];
      const _bd = {
        green: "var(--badge-green-border)",
        amber: "var(--badge-amber-border)",
        red: "var(--badge-red-border)",
        neutral: "var(--border)"
      }[tone];
      const _fg = {
        green: "var(--badge-green-text)",
        amber: "var(--badge-amber-text)",
        red: "var(--badge-red-text)",
        neutral: "var(--text-2)"
      }[tone];
      const _icon = tone === "green" ? "\u2713" : tone === "red" ? "\u2717" : tone === "amber" ? "\u26A0" : "\u25CB";
      let headline, subtitle;
      if (ls.reason === "pz_created_by_system") {
        headline = "PZ created by system";
        subtitle = "wFirma PZ was generated from this shipment.";
      } else if (ls.reason === "pz_adopted_existing") {
        headline = "Existing wFirma PZ adopted";
        subtitle = "A pre-existing wFirma PZ was linked to this shipment.";
      } else if (ls.reason === "audit_write_recovery_required") {
        headline = "PZ audit write recovery required";
        subtitle = ls.terminal_event === "wfirma_pz_created" ? "The timeline shows a PZ was created in wFirma but the local audit was not updated. Use Confirm Existing PZ with the live wFirma doc id to recover." : "The timeline shows a PZ was adopted but the local audit was not updated. Use Confirm Existing PZ to recover.";
      } else if (ls.reason === "pz_doc_id_set") {
        headline = "PZ already linked";
        subtitle = "A wFirma PZ doc id is already on this shipment.";
      } else if (pzPreview.unresolved_count > 0 || (pzPreview.unresolved_product_codes || []).length > 0) {
        headline = "PZ not ready \u2014 unresolved products";
        subtitle = `${pzPreview.unresolved_count || (pzPreview.unresolved_product_codes || []).length} product code(s) need mapping. Click Resolve Products.`;
      } else if (pzPreview.conflict_count > 0 || (pzPreview.price_conflicts || []).length > 0) {
        headline = "PZ not ready \u2014 price conflicts";
        subtitle = "Different unit prices for the same product code. Review the planned lines.";
      } else if (ls.can_create) {
        headline = "Ready to create wFirma PZ";
        subtitle = "All product codes resolved. Click Create wFirma PZ to proceed.";
      } else {
        headline = "No PZ linked yet";
        subtitle = "Earlier pipeline steps must finish before PZ can be created or adopted.";
      }
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "pz-lock-status-banner",
          "data-reason": ls.reason,
          "data-can-create": String(!!ls.can_create),
          "data-can-adopt": String(!!ls.can_adopt),
          style: { marginBottom: 12, padding: "10px 14px", background: _bg, border: `1px solid ${_bd}`, borderRadius: 6 }
        },
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14, color: _fg } }, _icon), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 200 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: _fg } }, headline), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: _fg, opacity: 0.85, marginTop: 2 } }, subtitle)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 12, fontSize: 10, color: _fg, opacity: 0.85, flexWrap: "wrap" } }, ls.wfirma_pz_doc_id && /* @__PURE__ */ React.createElement("span", { "data-testid": "pz-lock-doc-id" }, "doc id: ", /* @__PURE__ */ React.createElement("code", { style: { fontFamily: "monospace" } }, ls.wfirma_pz_doc_id)), ls.pz_source && /* @__PURE__ */ React.createElement("span", { "data-testid": "pz-lock-source" }, "source: ", /* @__PURE__ */ React.createElement("code", { style: { fontFamily: "monospace" } }, ls.pz_source)), ls.terminal_event && /* @__PURE__ */ React.createElement("span", { "data-testid": "pz-lock-event" }, "event: ", /* @__PURE__ */ React.createElement("code", { style: { fontFamily: "monospace" } }, ls.terminal_event))))
      );
    })(), pzCreateResult && pzCreateResult.status === "created" && !pzPreview?.wfirma_pz_doc_id && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16, padding: "10px 14px", background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "var(--badge-green-text)" } }, "Created: ", pzCreateResult.wfirma_pz_doc_id)), pzPreview?.error && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16, padding: "8px 12px", background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)", borderRadius: 6, fontSize: 11, color: "var(--badge-red-text)" } }, "Preview error: ", pzPreview.error), pzPreview && !pzPreview.error && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 16, fontSize: 11, color: "var(--text-2)" } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "MRN: "), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", color: "var(--text)" } }, pzPreview.mrn || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Clearance: "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text)" } }, pzPreview.clearance_date || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Lines: "), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text)", fontWeight: 600 } }, pzPreview.line_count ?? "\u2014")), pzPreview.unresolved_count > 0 && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text)" } }, /* @__PURE__ */ React.createElement("span", null, "\u26A0 Unresolved: "), /* @__PURE__ */ React.createElement("strong", null, pzPreview.unresolved_count)), pzPreview.conflict_count > 0 && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text)" } }, /* @__PURE__ */ React.createElement("span", null, "\u26A0 Price conflicts: "), /* @__PURE__ */ React.createElement("strong", null, pzPreview.conflict_count))), pzPreview?.unresolved_product_codes?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 14, padding: "8px 12px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-amber-text)", marginBottom: 4 } }, "Unresolved product codes (", pzPreview.unresolved_product_codes.length, ")"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", fontFamily: "monospace", lineHeight: 1.7 } }, pzPreview.unresolved_product_codes.join(", "))), pzPreview?.planned_lines?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16, border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 14px", background: "var(--bg-subtle)", borderBottom: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.06em" } }, "Planned lines \u2014 ", pzPreview.planned_lines.length)), /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--sidebar-bg)" } }, ["Product code", "Good ID", "Qty", "Price PLN", "Status"].map((h) => /* @__PURE__ */ React.createElement("th", { key: h, style: { padding: "6px 10px", textAlign: "left", fontSize: 10, fontWeight: 700, color: "white", whiteSpace: "nowrap" } }, h)))), /* @__PURE__ */ React.createElement("tbody", null, pzPreview.planned_lines.map((pl, i) => /* @__PURE__ */ React.createElement("tr", { key: i, style: { borderBottom: "1px solid var(--border-subtle)", background: i % 2 === 0 ? "white" : "var(--bg-subtle)" } }, /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px", fontFamily: "monospace", color: "var(--text)", fontSize: 10 } }, pl.product_code), /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px", fontFamily: "monospace", color: "var(--text-2)", fontSize: 10 } }, pl.good_id || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px", textAlign: "right", color: "var(--text)" } }, pl.count), /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px", textAlign: "right", color: "var(--text)", fontFamily: "monospace" } }, pl.price_pln?.toLocaleString("pl-PL", { minimumFractionDigits: 2 })), /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 10px" } }, /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 10,
      fontWeight: 700,
      padding: "2px 7px",
      borderRadius: 10,
      background: pl.resolved ? "var(--badge-green-bg)" : "var(--badge-red-bg)",
      color: pl.resolved ? "var(--badge-green-text)" : "var(--badge-red-text)",
      border: `1px solid ${pl.resolved ? "var(--badge-green-border)" : "var(--badge-red-border)"}`
    } }, pl.resolved ? "\u2713" : "\u2717 unresolved")))))))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" } }, /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "outline",
        disabled: pzPreviewLoading,
        onClick: loadPzPreview,
        "data-testid": "btn-pz-refresh"
      },
      pzPreviewLoading ? "\u27F3 Loading\u2026" : "\u21BB Refresh PZ Preview"
    ), !(pzPreview?.pz_lifecycle && pzPreview.pz_lifecycle.hide_resolve_products) && /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "outline",
        disabled: !!busy.pzResolve,
        onClick: resolveProducts,
        "data-testid": "btn-pz-resolve",
        title: pzPreview?.unresolved_count > 0 ? "Match unresolved product codes to wFirma goods" : "Re-run product resolution"
      },
      busy.pzResolve ? "\u27F3 Resolving\u2026" : "\u2699 Resolve Products"
    ), !(pzPreview?.pz_lifecycle && pzPreview.pz_lifecycle.hide_create_button) && (!pzCreateConfirm ? /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "gold",
        "data-testid": "btn-pz-create",
        disabled: (
          // pz_lock_status.can_create is the authoritative gate.
          // Fallback to the legacy ad-hoc checks when lock_status
          // isn't yet present (older preview responses).
          (pzPreview?.pz_lock_status ? !pzPreview.pz_lock_status.can_create : !pzPreview?.ready || !!(pzPreview?.unresolved_count > 0) || !!(pzPreview?.conflict_count > 0) || !!pzPreview?.wfirma_pz_doc_id) || pzCreateBusy
        ),
        title: (() => {
          const ls = pzPreview?.pz_lock_status;
          if (!pzPreview) return "Loading PZ preview\u2026";
          if (pzCreateBusy) return "Creating PZ in wFirma\u2026";
          if (ls?.recovery_required) return "Audit write recovery required \u2014 use Confirm Existing PZ.";
          if (ls?.reason === "pz_created_by_system") return `Already created in wFirma (id ${ls.wfirma_pz_doc_id || pzPreview?.wfirma_pz_doc_id || "\u2014"})`;
          if (ls?.reason === "pz_adopted_existing") return `Already adopted (id ${ls.wfirma_pz_doc_id || pzPreview?.wfirma_pz_doc_id || "\u2014"})`;
          if (ls?.reason === "pz_doc_id_set") return `Already linked (id ${ls.wfirma_pz_doc_id || pzPreview?.wfirma_pz_doc_id || "\u2014"})`;
          if (pzPreview?.unresolved_count > 0) return `Unresolved products: ${pzPreview.unresolved_count} \u2014 click Resolve Products first`;
          if (pzPreview?.conflict_count > 0) return `Product mapping conflicts: ${pzPreview.conflict_count} \u2014 review before creating`;
          if (!pzPreview?.ready) return "Preview not ready \u2014 earlier pipeline steps incomplete";
          return "Create warehouse PZ in wFirma";
        })(),
        onClick: () => setPzCreateConfirm(true)
      },
      pzCreateBusy ? "\u27F3 Creating\u2026" : "\u2726 Create wFirma PZ"
    ) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, "Create one wFirma PZ for this batch?"), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "gold",
        disabled: pzCreateBusy,
        onClick: submitPzCreate,
        "data-testid": "btn-pz-create-confirm"
      },
      pzCreateBusy ? "\u27F3\u2026" : "Confirm"
    ), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "ghost", onClick: () => setPzCreateConfirm(false) }, "Cancel"))), !pzAdoptOpen ? /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: pzPreview?.pz_lifecycle?.primary_action === "confirm_existing_pz" ? "gold" : "outline",
        "data-testid": "btn-pz-adopt-open",
        "data-primary": String(pzPreview?.pz_lifecycle?.primary_action === "confirm_existing_pz"),
        disabled: (
          // pz_lock_status.can_adopt is the authoritative gate.
          // Recovery case (timeline event without doc_id) keeps
          // can_adopt=true so the operator can manually link the
          // live wFirma PZ back into audit.
          (pzPreview?.pz_lock_status ? !pzPreview.pz_lock_status.can_adopt : !!pzPreview?.wfirma_pz_doc_id) || pzAdoptBusy
        ),
        title: (() => {
          const ls = pzPreview?.pz_lock_status;
          if (ls?.recovery_required) return "Use this to link the live wFirma PZ back into audit (recovery).";
          if (ls?.reason === "pz_created_by_system") return "PZ was already created by the system \u2014 adoption not needed.";
          if (ls?.reason === "pz_adopted_existing") return "PZ has already been adopted for this shipment.";
          if (ls?.reason === "pz_doc_id_set") return "PZ doc id already set on this shipment.";
          return "Attach an existing wFirma PZ to this shipment";
        })(),
        onClick: () => {
          setPzAdoptOpen(true);
          setPzAdoptResult(null);
        }
      },
      "\u2714 Confirm Existing PZ"
    ) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, padding: "8px 12px", background: "var(--badge-blue-bg, #eff6ff)", border: "1px solid var(--badge-blue-border, #bfdbfe)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement(
      "input",
      {
        "data-testid": "input-pz-adopt",
        value: pzAdoptInput,
        onChange: (e) => setPzAdoptInput(e.target.value),
        placeholder: "PZ doc ID or number (e.g. 183167843)",
        style: { fontSize: 12, padding: "4px 8px", borderRadius: 4, border: "1px solid #cbd5e1", width: 220 }
      }
    ), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "gold",
        disabled: pzAdoptBusy || !pzAdoptInput.trim(),
        "data-testid": "btn-pz-adopt-confirm",
        onClick: submitPzAdopt
      },
      pzAdoptBusy ? "\u27F3\u2026" : "Adopt"
    ), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "ghost", onClick: () => {
      setPzAdoptOpen(false);
      setPzAdoptInput("");
    } }, "Cancel"), pzAdoptResult && pzAdoptResult.status === "blocked" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--badge-red-text, #b91c1c)" } }, (pzAdoptResult.blocking_reasons || [pzAdoptResult.error || "blocked"])[0]))))),
    /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement(
      SectionHeader,
      {
        icon: "\u{1F9FE}",
        title: "Service Invoices",
        subtitle: "DHL and agency invoices for customs closure",
        status: audit.dhl_invoice_received && audit.agency_invoice_received ? "All received" : audit.dhl_invoice_received || audit.agency_invoice_received ? "Partial" : "Pending"
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { padding: 20 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { "data-testid": "svc-invoice-dhl-status", style: {
      padding: "5px 12px",
      borderRadius: 20,
      fontSize: 11,
      fontWeight: 700,
      background: audit.dhl_invoice_received ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
      color: audit.dhl_invoice_received ? "var(--badge-green-text)" : "var(--badge-amber-text)",
      border: `1px solid ${audit.dhl_invoice_received ? "var(--badge-green-border)" : "var(--badge-amber-border)"}`
    } }, audit.dhl_invoice_received ? "\u2713 DHL Invoice received" : "\u25CB DHL Invoice not received"), /* @__PURE__ */ React.createElement("div", { "data-testid": "svc-invoice-agency-status", style: {
      padding: "5px 12px",
      borderRadius: 20,
      fontSize: 11,
      fontWeight: 700,
      background: audit.agency_invoice_received ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
      color: audit.agency_invoice_received ? "var(--badge-green-text)" : "var(--badge-amber-text)",
      border: `1px solid ${audit.agency_invoice_received ? "var(--badge-green-border)" : "var(--badge-amber-border)"}`
    } }, audit.agency_invoice_received ? "\u2713 Agency Invoice received" : "\u25CB Agency Invoice not received")), (audit.service_invoices || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 } }, "Registered (", (audit.service_invoices || []).length, ")"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 3 } }, (audit.service_invoices || []).map((inv, i) => /* @__PURE__ */ React.createElement("div", { key: i, "data-testid": "svc-invoice-file-row", style: { display: "flex", alignItems: "center", gap: 8, padding: "4px 8px", background: "var(--bg-subtle)", borderRadius: 5, border: "1px solid var(--border-subtle)" } }, /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 10,
      padding: "2px 6px",
      borderRadius: 10,
      fontWeight: 700,
      background: inv.vendor === "DHL" ? "var(--badge-blue-bg, #e0f0ff)" : "var(--badge-neutral-bg)",
      color: inv.vendor === "DHL" ? "var(--badge-blue-text, #0060b0)" : "var(--text-3)"
    } }, inv.vendor || "unknown"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-2)", fontFamily: "monospace" } }, inv.name))))), /* @__PURE__ */ React.createElement("div", { style: { borderTop: (audit.service_invoices || []).length > 0 ? "1px solid var(--border-subtle)" : "none", paddingTop: (audit.service_invoices || []).length > 0 ? 14 : 0, display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement("label", { "data-testid": "svc-invoice-upload-label", style: { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 6, border: "1px solid var(--badge-neutral-border)", cursor: svcInvoiceBusy ? "not-allowed" : "pointer", fontSize: 12, fontWeight: 600, color: svcInvoiceBusy ? "var(--text-3)" : "var(--text)", background: "transparent", opacity: svcInvoiceBusy ? 0.6 : 1, width: "fit-content" } }, /* @__PURE__ */ React.createElement(
      "input",
      {
        "data-testid": "svc-invoice-file-input",
        ref: svcInvoiceRef,
        type: "file",
        accept: ".pdf,.xml,.html,.htm,.jpg,.jpeg,.png",
        multiple: true,
        disabled: svcInvoiceBusy,
        style: { display: "none" },
        onChange: async (e) => {
          const files = Array.from(e.target.files || []);
          if (!files.length) return;
          setSvcInvoiceBusy(true);
          setSvcInvoiceResult(null);
          setSvcInvoiceError("");
          try {
            const fd2 = new FormData();
            files.forEach((f) => fd2.append("files", f));
            fd2.append("source", "operator");
            const r = await fetch(`/api/v1/service-invoices/${encodeURIComponent(batchId)}/upload`, {
              method: "POST",
              body: fd2,
              credentials: "include"
            });
            if (!r.ok) {
              const msg = await r.text().catch(() => `HTTP ${r.status}`);
              throw new Error(msg);
            }
            const result = await r.json();
            setSvcInvoiceResult(result);
            await Promise.all([load(), loadBatchReadiness(), loadDecision()]);
          } catch (ex) {
            setSvcInvoiceError(ex.message || "Upload failed");
          } finally {
            setSvcInvoiceBusy(false);
            if (svcInvoiceRef.current) svcInvoiceRef.current.value = "";
          }
        }
      }
    ), svcInvoiceBusy ? "\u27F3 Uploading\u2026" : "\u229E Upload service invoices"), /* @__PURE__ */ React.createElement("div", { "data-testid": "svc-invoice-accepted-extensions", style: { fontSize: 10, color: "var(--text-3)" } }, "Accepted: .pdf, .xml, .html, .htm, .jpg, .jpeg, .png")), svcInvoiceResult && /* @__PURE__ */ React.createElement("div", { "data-testid": "svc-invoice-upload-success", style: { marginTop: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-green-text)", marginBottom: 2 } }, "\u2713 ", (svcInvoiceResult.imported || []).length, " invoice(s) registered"), (svcInvoiceResult.skipped || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", marginTop: 2 } }, svcInvoiceResult.skipped.length, " skipped \u2014 check file types or duplicates")), svcInvoiceError && /* @__PURE__ */ React.createElement("div", { "data-testid": "svc-invoice-upload-error", style: { marginTop: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, color: "var(--badge-red-text)" } }, "Upload failed: ", svcInvoiceError))))
  )), activeTab === "DHL / Customs" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement(
    SectionHeader,
    {
      icon: "\u2708",
      title: "Section 1 \u2014 Shipment & DHL Clearance",
      subtitle: "DHL pre-check, email correspondence, reply package",
      status: dhlClearance ? mapDhlStatus(dhlClearance) : void 0
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
    "details",
    {
      "data-testid": "dhl-shipment-metadata-collapsed",
      style: { marginBottom: 12 }
    },
    /* @__PURE__ */ React.createElement("summary", { style: {
      cursor: "pointer",
      fontSize: 10,
      fontWeight: 700,
      color: "var(--text-3)",
      letterSpacing: "0.08em",
      textTransform: "uppercase"
    } }, "Shipment metadata"),
    /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8 } }, /* @__PURE__ */ React.createElement(InfoRow, { label: "AWB / Tracking", value: trackingNo || "\u2014", mono: true }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Carrier", value: carrier }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Batch ID", value: batchId, mono: true }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Invoice Files", value: (inp.invoices || []).length > 0 ? `${(inp.invoices || []).length} file(s)` : "None uploaded" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "AWB PDF", value: inp.awb ? "Uploaded \u2713" : "Not uploaded" }))
  ), trackingNo && (() => {
    const td = trackingData;
    const _apiModeGuard = td && td.api_status || "";
    const _isManualGuard = _apiModeGuard === "manual" || td && td.source === "manual";
    const isNoCreds = _apiModeGuard === "no_credentials" || _apiModeGuard === "disabled";
    if (isNoCreds && !_isManualGuard) return null;
    const STATUS_DOT = { delivered: "#16a34a", in_transit: "#2563eb", out_for_delivery: "#d97706", exception: "#dc2626", unknown: "#9ca3af" };
    const dotColor = td ? STATUS_DOT[td.status] || STATUS_DOT.unknown : STATUS_DOT.unknown;
    const _apiMode = td && td.api_status || "";
    const isManual = _apiMode === "manual" || td && td.source === "manual";
    const isPending = !isManual && (!td || _apiMode === "disabled" || _apiMode === "failed" || _apiMode === "no_credentials" || td.source === "api_disabled" || td.source === "api_failed" || td.source === "api_pending" || td.source === "no_credentials" || td.available === false && (_apiMode === "pending" || _apiMode === "no_credentials"));
    const _ERR_SOURCES = /* @__PURE__ */ new Set([
      "error",
      "unauthorized",
      "rate_limited",
      "carrier_error",
      "network_error",
      "config_error"
    ]);
    const isError = td && !td.available && _ERR_SOURCES.has(td.source);
    const isAuthErr = td && (td.source === "unauthorized" || td.status === "unauthorized");
    const isLive = td && td.available === true;
    const needsCoworkLookup = td && td.cowork_tracking_required && !td.cowork_result_received;
    const coworkResultReceived = td && td.cowork_result_received;
    const refreshBlocked = isPending && !isLive;
    return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 12, padding: "10px 12px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" } }, "Live Tracking"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, alignItems: "center" } }, td && td.tracking_terminal ? /* @__PURE__ */ React.createElement(
      "span",
      {
        title: `Tracking frozen: ${td.tracking_terminal_reason || "terminal status"} \u2014 no further DHL API calls`,
        style: { fontSize: 10, padding: "1px 6px", borderRadius: 4, background: "var(--badge-green-bg)", color: "var(--badge-green-text)", border: "1px solid var(--badge-green-border)", fontWeight: 700 }
      },
      "\u2713 Tracking stopped"
    ) : /* @__PURE__ */ React.createElement(
      "button",
      {
        disabled: trackingBusy,
        onClick: () => {
          if (refreshBlocked) {
            const m = td && td.api_status || "";
            const msg = m === "failed" ? "DHL API failed \u2014 retry or use manual" : "DHL API disabled \u2014 credentials are not active";
            onToast(msg, "info");
            return;
          }
          fetchTracking(true);
        },
        style: { fontSize: 10, cursor: trackingBusy ? "default" : "pointer", background: "none", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 6px", color: refreshBlocked ? "var(--text-3)" : "var(--text-2)", fontFamily: "inherit", opacity: refreshBlocked ? 0.5 : 1 }
      },
      trackingBusy ? "\u27F3" : "\u21BB"
    ))), isPending && !isError && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 4, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12 } }, "\u26A0"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-amber-text)" } }, (() => {
      const m = td && td.api_status || "";
      if (td && td.api_status === "no_credentials") return "FedEx API \u2014 No Credentials";
      if (m === "failed") return "DHL API failed";
      return "DHL API disabled";
    })())), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 8 } }, (() => {
      const m = td && td.api_status || "";
      if (m === "failed")
        return "Retry API or use public/manual tracking.";
      return "Credentials are not active. Use public tracking or manual update.";
    })()), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" } }, td && td.tracking_url ? /* @__PURE__ */ React.createElement(
      "a",
      {
        href: td.tracking_url,
        target: "_blank",
        rel: "noopener noreferrer",
        style: { display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 600, color: "var(--badge-blue-text)", textDecoration: "none", padding: "4px 10px", border: "1px solid var(--badge-blue-border)", borderRadius: 4, background: "var(--badge-blue-bg)" }
      },
      "\u2197 Open Public Tracking"
    ) : /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "Tracking URL unavailable")), needsCoworkLookup && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, padding: "8px 10px", background: "#fefce8", border: "1px solid #fde047", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#854d0e", marginBottom: 4 } }, "\u2197 Fallback tracking available"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "#92400e", marginBottom: 8 } }, "Open the public tracking page or report the latest status manually below."), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          const awb = audit.awb || audit.tracking_no || "";
          const status2 = window.prompt("Tracking status (in_transit / delivered / out_for_delivery / customs / exception / unknown):", "in_transit");
          if (!status2) return;
          const lastEv = window.prompt("Last event description:", "");
          if (lastEv === null) return;
          const lastLoc = window.prompt("Last location (e.g. WARSAW - PL):", "");
          const note = window.prompt("Optional note:", "");
          apiFetch(`/api/v1/tracking/${encodeURIComponent(awb)}/cowork-result`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              status: status2,
              last_event: lastEv,
              last_location: lastLoc || "",
              source: "operator_manual",
              batch_id: batchId,
              note: note || null
            })
          }).then(() => {
            onToast("Tracking result saved.", "success");
            fetchTracking(true);
          }).catch((e) => onToast(e.message || "Failed to save tracking result", "error"));
        },
        style: { fontSize: 11, fontWeight: 600, cursor: "pointer", background: "#854d0e", color: "#fff", border: "none", borderRadius: 4, padding: "5px 12px", fontFamily: "inherit" }
      },
      "Update tracking result manually"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: async () => {
          try {
            await apiFetch(`/api/v1/ai-bridge/tasks/${encodeURIComponent(batchId)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ task_type: "tracking_lookup", note: "Created from shipment detail view" })
            });
            onToast("Tracking task created in AI Bridge \u21CC", "success");
          } catch (e) {
            onToast("Failed to create task: " + e.message, "error");
          }
        },
        style: { fontSize: 11, fontWeight: 600, cursor: "pointer", background: "#1D4ED8", color: "#fff", border: "none", borderRadius: 4, padding: "5px 12px", fontFamily: "inherit" }
      },
      "\u21CC Create AI Bridge Task"
    )), coworkResultReceived && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, fontSize: 10, color: "var(--badge-green-text)" } }, "\u2713 Cowork tracking result received \xB7 ", td.cowork_result_at ? td.cowork_result_at.slice(0, 19).replace("T", " ") : "")), isError && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 5,
      padding: "3px 8px",
      background: isAuthErr ? "var(--badge-amber-bg)" : "var(--badge-red-bg)",
      border: `1px solid ${isAuthErr ? "var(--badge-amber-border)" : "var(--badge-red-border)"}`,
      borderRadius: 4,
      marginBottom: 6
    } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12 } }, isAuthErr ? "\u2699" : "\u2717"), /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 11,
      fontWeight: 700,
      color: isAuthErr ? "var(--badge-amber-text)" : "var(--badge-red-text)"
    } }, isAuthErr ? "DHL API \u2014 Configuration Issue" : td.source === "rate_limited" ? "DHL API \u2014 Rate Limited" : td.source === "carrier_error" ? "DHL API \u2014 Upstream Error" : td.source === "network_error" ? "DHL API \u2014 Network Error" : "Tracking Error")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 6 } }, td.message || td.error || "Tracking unavailable."), isAuthErr && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 8 } }, "Stored timeline and email evidence still display below \u2014 only the live API call is unavailable."), td.tracking_url && /* @__PURE__ */ React.createElement(
      "a",
      {
        href: td.tracking_url,
        target: "_blank",
        rel: "noopener noreferrer",
        style: {
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          fontSize: 11,
          fontWeight: 600,
          color: "var(--badge-blue-text)",
          textDecoration: "none",
          padding: "4px 10px",
          border: "1px solid var(--badge-blue-border)",
          borderRadius: 4,
          background: "var(--badge-blue-bg)"
        }
      },
      "\u2197 Open Public Tracking"
    )), isManual && !isLive && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", borderRadius: 4, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11 } }, "\u2713"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-green-text)" } }, "Tracking updated manually")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: 4 } }, "Manual tracking is saved.", td && td.updated_at && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, " \xB7 ", td.updated_at.slice(0, 19).replace("T", " "))), td && td.tracking_url && /* @__PURE__ */ React.createElement(
      "a",
      {
        href: td.tracking_url,
        target: "_blank",
        rel: "noopener noreferrer",
        style: { fontSize: 11, color: "var(--badge-blue-text)", textDecoration: "none" }
      },
      "\u2197 Open Public Tracking"
    )), isLive && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", borderRadius: 4, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11 } }, "\u2713"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-green-text)" } }, td.tracking_terminal ? "Delivered \u2014 tracking stopped" : "Live Tracking")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { width: 7, height: 7, borderRadius: "50%", background: dotColor, display: "inline-block", flexShrink: 0 } }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: dotColor } }, td.status_label)), td.last_location && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginBottom: 1 } }, "\u{1F4CD} ", td.last_location), td.last_update_display && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 1 } }, "\u{1F550} ", td.last_update_display), td.origin && td.destination && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, td.origin, " \u2192 ", td.destination), td.tracking_url && /* @__PURE__ */ React.createElement(
      "a",
      {
        href: td.tracking_url,
        target: "_blank",
        rel: "noopener noreferrer",
        style: { fontSize: 10, color: "var(--badge-blue-text)", textDecoration: "none" }
      },
      "\u2197 Open DHL Tracking"
    ), Array.isArray(td.events) && td.events.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, paddingTop: 8, borderTop: "1px dashed var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 } }, "Movement timeline (", td.events.length, " events)"), td.events.slice().reverse().slice(0, 10).map((ev, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", gap: 6, fontSize: 10, color: "var(--text-2)", marginBottom: 3, lineHeight: 1.3 } }, /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", color: "var(--text-3)", flexShrink: 0, minWidth: 95 } }, (ev.timestamp || "").slice(0, 16).replace("T", " ")), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-2)", flexShrink: 0, minWidth: 110, fontWeight: 600 } }, ev.location || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis" } }, ev.description || ev.status || ""))), td.events.length > 10 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "var(--text-3)", marginTop: 2, opacity: 0.7 } }, "+", td.events.length - 10, " earlier events")), audit.dhl_followup && (() => {
      const f = audit.dhl_followup || {};
      const isActive = !!f.active;
      const nextAt = f.next_followup_at ? new Date(f.next_followup_at) : null;
      const overdue = isActive && nextAt && nextAt <= /* @__PURE__ */ new Date();
      const bg = !isActive ? "var(--badge-neutral-bg)" : overdue ? "var(--badge-red-bg)" : "var(--badge-amber-bg)";
      const fg = !isActive ? "var(--text-3)" : overdue ? "var(--badge-red-text)" : "var(--badge-amber-text)";
      return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: 8, borderRadius: 4, background: bg, border: "1px solid var(--border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: fg, marginBottom: 3 } }, isActive ? overdue ? "\u{1F6A8} DHL Follow-up overdue" : "\u23F1 DHL Follow-up SLA active" : "\u2713 DHL Follow-up stopped"), f.trigger_reason && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, "Trigger: ", f.trigger_reason), f.first_followup_at && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "First follow-up: ", f.first_followup_at.slice(0, 16).replace("T", " ")), isActive && f.next_followup_at && /* @__PURE__ */ React.createElement("div", { style: { color: fg } }, "Next follow-up: ", f.next_followup_at.slice(0, 16).replace("T", " ")), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Sent so far: ", f.followup_count || 0), f.last_followup_at && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Last sent: ", f.last_followup_at.slice(0, 16).replace("T", " ")), !isActive && f.stop_reason && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)", marginTop: 2 } }, "Stop reason: ", f.stop_reason), isActive && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: async () => {
            const op = prompt("Operator name (for audit):", "admin");
            if (!op) return;
            await apiFetch(
              `/api/v1/dhl-followup/${encodeURIComponent(batchId)}/send-now`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approved_by: op })
              }
            );
            await load();
          },
          style: { fontSize: 10, padding: "2px 6px", border: "1px solid var(--border)", borderRadius: 3, background: "var(--card)", cursor: "pointer" }
        },
        "\u2197 Send follow-up now"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: async () => {
            const reason = prompt("Stop reason (required):");
            if (!reason) return;
            const op = prompt("Operator name:", "admin");
            if (!op) return;
            await apiFetch(
              `/api/v1/dhl-followup/${encodeURIComponent(batchId)}/stop`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reason, operator: op })
              }
            );
            await load();
          },
          style: { fontSize: 10, padding: "2px 6px", border: "1px solid var(--border)", borderRadius: 3, background: "var(--card)", cursor: "pointer" }
        },
        "\u23F9 Stop follow-up"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: async () => {
            await apiFetch(
              `/api/v1/dhl-followup/${encodeURIComponent(batchId)}/recalculate`,
              { method: "POST" }
            );
            await load();
          },
          style: { fontSize: 10, padding: "2px 6px", border: "1px solid var(--border)", borderRadius: 3, background: "var(--card)", cursor: "pointer" }
        },
        "\u21BB Recalculate"
      )));
    })(), audit.pending_triggers && audit.pending_triggers.dhl_email_check && audit.pending_triggers.dhl_email_check.active && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: 8, borderRadius: 4, background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--badge-amber-text)", marginBottom: 2 } }, "\u26A1 DHL customs trigger detected"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, audit.pending_triggers.dhl_email_check.reason || "Tracking shows customs activity \u2014 checking email automatically"), audit.pending_triggers.dhl_email_check.retries > 0 && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", marginTop: 2 } }, "Retries: ", audit.pending_triggers.dhl_email_check.retries)), (audit.risk_flags || []).includes("dhl_email_missing_after_tracking_trigger") && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: 8, borderRadius: 4, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--badge-red-text)", marginBottom: 2 } }, "\u{1F6A8} DHL email missing after customs trigger"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, "Tracking indicates customs process started, but no DHL email found after retries. Manual Zoho check required.")), td.intelligence && td.intelligence.expected_next && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, paddingTop: 8, borderTop: "1px dashed var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 } }, "Next Expected Action"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-neutral-bg)", color: "var(--text-2)", fontWeight: 600 } }, "Stage: ", td.intelligence.stage.replace(/_/g, " ")), td.intelligence.delay_flag && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-amber-bg)", color: "var(--badge-amber-text)", fontWeight: 700 } }, "\u26A0 Overdue ", td.intelligence.delay_hours, "h")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginBottom: 2 } }, "Expected: ", /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600 } }, td.intelligence.expected_next), td.intelligence.expected_within_hours != null && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 4, color: "var(--text-3)" } }, "(within ", td.intelligence.expected_within_hours, "h)")), td.intelligence.hours_since_last_event != null && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 2 } }, "Time since last event: ", td.intelligence.hours_since_last_event, "h"), td.intelligence.recommended_action && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: td.intelligence.delay_flag ? "var(--badge-amber-text)" : "var(--text-2)", marginTop: 4, padding: "4px 6px", background: td.intelligence.delay_flag ? "var(--badge-amber-bg)" : "var(--card)", borderRadius: 3, border: "1px solid var(--border)" } }, "\u{1F4A1} ", td.intelligence.recommended_action)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "var(--text-3)", marginTop: 6, opacity: 0.7 } }, "via ", td.source === "dhl_unified_api" ? "DHL Unified API" : td.source === "dhl_api" ? "DHL API" : td.source, td.cached_at ? ` \xB7 cached ${td.cached_at.slice(0, 19).replace("T", " ")}` : "")), !td && !trackingBusy && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "Checking status\u2026"), trackingBusy && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "Fetching status\u2026"));
  })()), (() => {
    const it = audit.invoice_totals || {};
    const ver2 = audit.verification || {};
    const cd = audit.customs_declaration || {};
    const cifUsd = ver2.invoice_cif_total_usd || it.total_cif_usd || 0;
    const cifZero = !cifUsd || cifUsd === 0;
    const fmtUsd = (v) => v ? `USD ${Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "USD 0.00";
    const totalFobUsd = it.total_fob_usd;
    const freightUsd = it.total_freight_usd;
    const exchRate = cd.exchange_rate || cd.sad_customs_rate;
    const freightPln = freightUsd && exchRate ? freightUsd * exchRate : null;
    const dec = audit.clearance_decision || {};
    const decPath = dec.clearance_path || "routing_pending";
    const isAgency = decPath === "agency_clearance" || decPath === "external_agency_clearance";
    const isCarrier = decPath === "dhl_self_clearance" || decPath === "carrier_self_clearance";
    const decPending = decPath === "routing_pending";
    const pathLabel = isAgency ? "\u{1F3E2} External Agency (>$2500)" : isCarrier ? "\u{1F69A} Carrier Self-Clearance (\u2264$2500)" : "\u23F3 Routing Pending (no CIF)";
    const pathColor = isAgency ? "var(--badge-amber-text)" : isCarrier ? "var(--badge-green-text)" : "var(--text-3)";
    const decCifUsd = dec.total_value_usd;
    const decResolved = dec.cif_state === "resolved" && decCifUsd != null && Number(decCifUsd) > 0;
    const cifSourceLabel = (src) => {
      if (!src) return "unresolved (no source)";
      if (src === "awb_customs.value_usd") return "AWB Custom Val (carrier-declared)";
      if (src.indexOf("dhl_precheck") === 0) return "DHL pre-check / OCR-AI fallback";
      if (src.indexOf("verification") === 0 || src.indexOf("invoice_totals") === 0) return "Invoice";
      return src.replace(/_/g, " ").replace(".", " ");
    };
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "DHL Clearance Values"), /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Invoice CIF (USD)",
        value: cifZero && decResolved ? /* @__PURE__ */ React.createElement("span", { "data-testid": "invoice-cif-not-parsed", style: { color: "var(--badge-amber-text)", fontWeight: 600 } }, "not parsed") : /* @__PURE__ */ React.createElement("span", { style: { color: cifZero ? "var(--badge-red-text)" : "inherit", fontWeight: cifZero ? 700 : "inherit" } }, fmtUsd(cifUsd))
      }
    ), decResolved && /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Resolved CIF (USD)",
        value: /* @__PURE__ */ React.createElement("span", { "data-testid": "resolved-cif-value", style: { color: "var(--badge-green-text)", fontWeight: 700 } }, fmtUsd(decCifUsd), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontWeight: 400, fontSize: 10, marginLeft: 6 } }, "\xB7 Source: ", cifSourceLabel(dec.cif_source)))
      }
    ), /* @__PURE__ */ React.createElement(InfoRow, { label: "Total Net (USD)", value: totalFobUsd != null ? `USD ${Number(totalFobUsd).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "Not parsed \u2014 process invoices" }), /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Freight (PLN)",
        "data-testid": "freight-pln-row",
        value: (() => {
          const fa = audit.freight_authority;
          if (!fa) {
            if (freightPln != null) return fmtPLN(freightPln);
            if (freightUsd != null && freightUsd > 0)
              return `USD ${Number(freightUsd).toLocaleString("en-US", { minimumFractionDigits: 2 })} (rate not available)`;
            return "Not declared";
          }
          if (fa.freight_status === "parsed_positive") {
            if (fa.freight_pln != null) return fmtPLN(fa.freight_pln);
            if (fa.freight_usd != null && fa.freight_usd > 0)
              return `USD ${Number(fa.freight_usd).toLocaleString("en-US", { minimumFractionDigits: 2 })} (rate not available)`;
            return "0.00 PLN";
          }
          if (fa.freight_status === "confidently_absent") return "0.00 PLN";
          if (fa.freight_status === "missing_invoice") return "Not declared";
          return /* @__PURE__ */ React.createElement("span", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
            "span",
            {
              "data-testid": "freight-needs-review",
              style: { color: "var(--badge-amber-text)", fontWeight: 600 }
            },
            "\u26A0 Needs review"
          ), /* @__PURE__ */ React.createElement(
            Btn,
            {
              small: true,
              variant: "outline",
              "data-testid": "btn-freight-ai-review",
              disabled: !!busy.freightAiReview,
              onClick: () => doAction(
                "freightAiReview",
                "Invoice freight review",
                () => apiFetch(
                  `/api/v1/ai-bridge/tasks/${encodeURIComponent(batchId)}`,
                  {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ task_type: "invoice_freight_review" })
                  }
                )
              )
            },
            busy.freightAiReview ? "\u27F3 Reviewing\u2026" : "\u{1F50D} Review invoice fields"
          ));
        })()
      }
    ), /* @__PURE__ */ React.createElement(InfoRow, { label: "DHL Clearance Status", value: dhlClearance ? mapDhlStatus(dhlClearance) : "Not started" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Polish Description", value: audit.polish_desc_filename ? "Generated \u2713" : "Not generated" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "DSK File", value: audit.dsk_filename ? "Generated \u2713" : "Not generated" }), (() => {
      const dskMeta = audit.dsk_meta;
      const dskVal = dskMeta ? dskMeta.value_usd : ver2.invoice_cif_total_usd || it.total_cif_usd || (decResolved ? decCifUsd : null);
      const dskSrc = dskMeta ? dskMeta.value_source : ver2.invoice_cif_total_usd || it.total_cif_usd ? "invoice CIF" : decResolved ? cifSourceLabel(dec.cif_source) : "invoice CIF";
      if (!dskVal) return null;
      return /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "DSK Value (USD)",
          value: `USD ${Number(dskVal).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${dskSrc.replace(/_/g, " ").replace("audit.", "").replace("invoice totals", "invoice CIF")})`
        }
      );
    })(), /* @__PURE__ */ React.createElement("div", { "data-testid": "clearance-routing-card", style: { marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 } }, "Clearance Routing"), /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Clearance Path",
        value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-path-label", style: { color: pathColor, fontWeight: 600 } }, pathLabel)
      }
    ), (() => {
      const decCif = dec.total_value_usd != null ? Number(dec.total_value_usd) : null;
      const decThreshold = dec.threshold_usd != null ? Number(dec.threshold_usd) : 2500;
      const decSource = dec.cif_source || (decCif ? "invoice CIF" : "unavailable");
      const decReason = dec.missing_reason || dec.decision_reason || "";
      const sourceLabel = {
        "verification.invoice_cif_total_usd": "verified invoice CIF",
        "invoice_totals.total_cif_usd": "invoice totals (CIF)",
        "invoice_totals.total_fob_usd": "invoice totals (FOB fallback \u2014 freight not allocated)",
        "dhl_precheck.invoice_cif_total_usd": "DHL pre-check CIF",
        "dhl_precheck.fob_total_usd": "DHL pre-check FOB",
        "awb_customs.value_usd": "AWB Custom Val (carrier-declared)",
        "audit.customs_declared_value_zero": "declared zero (source-confirmed)",
        "unavailable": "unavailable"
      }[decSource] || decSource;
      const cifState = dec.cif_state || (decSource === "unavailable" ? "unknown" : "resolved");
      const cifGap = dec.cif_extraction_gap || null;
      return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "Decision Value (USD)",
          value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-decision-value", style: { fontWeight: 600 } }, decCif != null && decCif > 0 ? `USD ${decCif.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "Not calculated")
        }
      ), /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "Threshold",
          value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-threshold", style: { fontFamily: "monospace", fontSize: 11 } }, "USD ", decThreshold.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
        }
      ), /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "Value Source",
          value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-value-source", style: { fontSize: 11, color: decSource === "unavailable" ? "var(--badge-amber-text)" : "var(--text-2)" } }, sourceLabel)
        }
      ), decPending && /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "Reason",
          value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-pending-reason", style: { fontSize: 11, color: "var(--badge-amber-text)" } }, "Routing Pending \u2014 ", dec.missing_reason || "CIF not calculated yet")
        }
      ), cifState === "unknown" && cifGap && /* @__PURE__ */ React.createElement("div", { "data-testid": "clearance-extraction-gap", style: { marginTop: 6, padding: "6px 8px", borderRadius: 4, background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-amber-text)" } }, "\u26A0 CIF unknown \u2014 extraction gap"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 2 } }, "First failed layer: ", /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace" } }, cifGap.first_failed_layer || "unknown")), cifGap.reason && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginTop: 2 } }, cifGap.reason), cifGap.next_action && /* @__PURE__ */ React.createElement("div", { "data-testid": "clearance-extraction-next-action", style: { fontSize: 11, color: "var(--text-1)", marginTop: 2, fontWeight: 600 } }, "Next: ", cifGap.next_action)), cifState === "declared_zero" && /* @__PURE__ */ React.createElement(
        InfoRow,
        {
          label: "CIF Status",
          value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-declared-zero", style: { fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, "Declared zero \u2014 source-confirmed (not a parser miss)")
        }
      ), (() => {
        const ve = audit.vision_extraction || null;
        const runs = ve && Array.isArray(ve.runs) ? ve.runs : [];
        if (!runs.length) return null;
        const last = runs[runs.length - 1] || {};
        const docs = Array.isArray(last.documents) ? last.documents : [];
        const written = docs.find((d) => d && d.extraction && d.extraction.ok && typeof d.write === "string" && (d.write.indexOf("value_usd") === 0 || d.write.indexOf("dhl_precheck") === 0));
        if (last.wrote && written) {
          const ex = written.extraction || {};
          const pg = ex.source_page != null ? ` from page ${ex.source_page}` : "";
          const conf = ex.confidence != null ? ` (confidence ${(ex.confidence * 100).toFixed(0)}%)` : "";
          return /* @__PURE__ */ React.createElement(
            InfoRow,
            {
              label: "Extraction Method",
              value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-extraction-method", style: { fontSize: 11, color: "var(--badge-green-text)", fontWeight: 600 } }, "Extracted by OCR/AI (Claude vision)", pg, conf, " \u2014 verify source before booking")
            }
          );
        }
        const attempted = docs.some((d) => d && d.extraction);
        if (attempted && cifState === "unknown") {
          return /* @__PURE__ */ React.createElement(
            InfoRow,
            {
              label: "Extraction Method",
              value: /* @__PURE__ */ React.createElement("span", { "data-testid": "clearance-extraction-method", style: { fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, "OCR/AI extraction attempted \u2014 no usable value found, operator review needed")
            }
          );
        }
        return null;
      })());
    })(), isAgency && /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Agency",
        value: /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-amber-text)", fontWeight: 600 } }, dec.agency || "Agencja Celna Spedycja")
      }
    ), isAgency && audit.agency_reply_package && /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Agency Email",
        value: /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-green-text)" } }, audit.agency_reply_package.status === "queued" ? "\u2713 Queued" : audit.agency_reply_package.status === "sent" ? "\u2713 Sent" : audit.agency_reply_package.status), audit.agency_reply_package.status === "sent" && audit.agency_reply_package.send_verified === false && /* @__PURE__ */ React.createElement("span", { title: "Operator must confirm via Zoho Sent folder. Audit risk_flag is set.", style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-amber-bg)", color: "var(--badge-amber-text)", border: "1px solid var(--badge-amber-border)", fontWeight: 700, whiteSpace: "nowrap" } }, "\u26A0 Send unverified"), audit.agency_reply_package.send_verified === true && /* @__PURE__ */ React.createElement("span", { title: `Verified at ${audit.agency_reply_package.verified_at || ""}`, style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-green-bg)", color: "var(--badge-green-text)", border: "1px solid var(--badge-green-border)", fontWeight: 700, whiteSpace: "nowrap" } }, "\u2713 Verified"))
      }
    ), decPending && !cifZero && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", marginTop: 4 } }, "\u26A0 Run Recheck to compute clearance path")), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 } }, "Email Routing"), /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "DHL TO",
        value: /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", fontSize: 11 } }, "odprawacelna@dhl.com")
      }
    ), isAgency && /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Agency TO",
        value: /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", fontSize: 11, color: "var(--badge-amber-text)" } }, "piotr@acspedycja.pl")
      }
    ), isAgency && /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Agency CC",
        value: /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", fontSize: 11, color: "var(--text-2)" } }, "biuro@acspedycja.pl, roman@acspedycja.pl, ganther")
      }
    ), /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "Internal CC",
        value: /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace", fontSize: 11, color: "var(--text-2)" } }, "info / import / account @estrellajewels.eu")
      }
    ), audit.dsk_received && /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "DSK Source",
        value: /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-green-text)", fontSize: 11 } }, "\u2713 ", audit.dsk_source || "administracja_centralna@dhl.com")
      }
    ), audit._clearance_drift_warning && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, padding: "4px 8px", borderRadius: 4, background: "var(--badge-amber-bg)", color: "var(--badge-amber-text)", fontSize: 10 } }, "\u26A0 Clearance decision may be stale \u2014 run Recheck")), cifZero && !decResolved && /* @__PURE__ */ React.createElement("div", { "data-testid": "cif-unresolved-banner", style: { marginTop: 10, padding: "10px 12px", background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-red-text)", marginBottom: 3 } }, "\u26A0 CIF unresolved \u2014 no customs value from any authority"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-red-text)", opacity: 0.9 } }, "Generate Description is blocked until the batch is re-processed with valid invoice PDFs, or the AWB customs value is confirmed.")), cifZero && decResolved && /* @__PURE__ */ React.createElement("div", { "data-testid": "cif-resolved-advisory", style: { marginTop: 10, padding: "10px 12px", background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-amber-text)", marginBottom: 3 } }, "\u2139 Invoice totals not parsed \u2014 clearance routing resolved CIF from ", cifSourceLabel(dec.cif_source)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", opacity: 0.9 } }, "Resolved CIF ", fmtUsd(decCifUsd), " is used for routing and Polish Description. Re-process invoices to populate per-invoice CIF rows.")));
  })()), !v2Active && (() => {
    const _it = audit.invoice_totals || {};
    const _ver = audit.verification || {};
    const _cif = _ver.invoice_cif_total_usd || _it.total_cif_usd || 0;
    const _cifZero = !_cif || _cif === 0;
    const _pdFile = audit.polish_desc_filename;
    const _pdExists = !!(audit.polish_desc_file_exists !== false && _pdFile);
    const _pdMissing = _pdFile && !_pdExists;
    const _pdReady = _pdFile && _pdExists;
    const _dec = audit.clearance_decision || {};
    const _decCifUsd = _dec.total_value_usd;
    const _decResolved = _dec.cif_state === "resolved" && _decCifUsd != null && Number(_decCifUsd) > 0;
    const _pdBlocked = !_decResolved;
    const _decCifLabel = _decResolved ? `USD ${Number(_decCifUsd).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "";
    const _dskRequired = _dec.require_dsk !== false;
    const _dskFile = audit.dsk_filename;
    const _dskExists = !!(audit.dsk_file_exists !== false && _dskFile);
    const _dskMissing = _dskFile && !_dskExists;
    const _dskReady = _dskFile && _dskExists;
    const _dskBlocked = !_decResolved;
    const _drp = audit.dhl_reply_package || {};
    const _drpStatus = _drp.status || (dhlClearance === "reply_sent" ? "sent" : dhlClearance === "reply_queued" ? "queued" : "");
    const _drpBuilt = !!(_drp.email_id || _drp.queue_id || _drpStatus);
    const _drpQueued = _drpStatus === "queued";
    const _drpSent = _drpStatus === "sent";
    const _drpQid = _drp.email_id || _drp.queue_id || "";
    const _isAgency = (_dec.clearance_path || "") === "external_agency_clearance";
    const _arp = audit.agency_reply_package || {};
    const _arpQueued = _arp.status === "queued";
    const _arpSent = _arp.status === "sent";
    const _arpQid = _arp.queue_id || _arp.email_id || "";
    const _td = trackingData || {};
    const _apiMode = (_td.api_status || "").toLowerCase();
    const _dhlApiDown = (_apiMode === "disabled" || _apiMode === "failed" || _apiMode === "no_credentials" || _td.source === "api_disabled" || _td.source === "api_failed" || _td.source === "api_pending" || _td.source === "no_credentials") && _apiMode !== "manual" && _td.source !== "manual";
    const _dhlApiLabel = _apiMode === "failed" ? "\u26A0 DHL API failed \u2014 retry or use manual workflow." : "\u26A0 DHL API disabled \u2014 using fallback (email/manual workflow).";
    return /* @__PURE__ */ React.createElement("div", { style: { padding: "0 20px 8px", display: "flex", flexDirection: "column", gap: 10 } }, _dhlApiDown && /* @__PURE__ */ React.createElement("div", { style: {
      padding: "6px 10px",
      borderRadius: 4,
      background: "var(--badge-amber-bg)",
      border: "1px solid var(--badge-amber-border)",
      fontSize: 11,
      color: "var(--badge-amber-text)"
    } }, _dhlApiLabel, " Live tracking falls back to public link."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginRight: 4 } }, "Customs Package"), _decResolved && /* @__PURE__ */ React.createElement("span", { "data-testid": "customs-pkg-resolved-cif", style: { fontSize: 10, color: "var(--badge-green-text)", fontWeight: 600 } }, "Resolved CIF = ", _decCifLabel), _pdReady ? /* @__PURE__ */ React.createElement("a", { href: `/api/v1/dhl/download/${encodeURIComponent(_pdFile)}`, target: "_blank", rel: "noreferrer", style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { variant: "success", title: "Download Polish Customs Description" }, "\u2193 Polish Description")) : _pdMissing ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--badge-red-text)", fontWeight: 600 } }, "\u26A0 Marked generated but file missing"), /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "danger",
        "data-testid": "btn-repair-polish-desc",
        disabled: !!busy.genDesc || _pdBlocked,
        title: _pdBlocked ? "Blocked: customs CIF unresolved \u2014 re-process invoices or confirm the AWB customs value" : "Re-generate the missing Polish Customs Description PDF",
        onClick: () => doAction("genDesc", "Repair Polish Description", () => apiFetch(`/api/v1/dhl/generate-description/${encodeURIComponent(batchId)}`, { method: "POST" }))
      },
      busy.genDesc ? "\u27F3 Repairing\u2026" : _pdBlocked ? "\u26A0 Repair (CIF unresolved)" : "\u26A0 Repair Polish Description"
    )) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "outline",
        "data-testid": "btn-generate-polish-desc",
        disabled: !!busy.genDesc || _pdBlocked,
        title: _pdBlocked ? "Blocked: customs CIF unresolved \u2014 re-process invoices or confirm the AWB customs value" : `Generate Polish Customs Description PDF (Resolved CIF = ${_decCifLabel})`,
        onClick: () => doAction("genDesc", "Generate Polish Description", () => apiFetch(`/api/v1/dhl/generate-description/${encodeURIComponent(batchId)}`, { method: "POST" }))
      },
      busy.genDesc ? "\u27F3 Generating\u2026" : _pdBlocked ? "\u229E Polish Desc. (CIF unresolved)" : "\u229E Generate Polish Description"
    ), /* @__PURE__ */ React.createElement(Btn, { variant: "ghost", disabled: true, title: "File not generated yet" }, "\u2193 Polish Description")), !_dskRequired ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-3)", fontStyle: "italic" } }, "\xB7 DSK not required for this shipment") : _dskReady ? /* @__PURE__ */ React.createElement("a", { href: `/api/v1/dsk/download/${encodeURIComponent(_dskFile)}`, target: "_blank", rel: "noreferrer", style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Btn, { variant: "success", title: "Download DSK PDF" }, "\u2193 DSK PDF")) : _dskMissing ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--badge-red-text)", fontWeight: 600 } }, "\u26A0 DSK marked generated but file missing"), /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "danger",
        "data-testid": "btn-repair-dsk",
        disabled: !!busy.genDsk || _dskBlocked,
        title: _dskBlocked ? "Blocked: customs CIF unresolved \u2014 re-process invoices or confirm the AWB customs value before generating a DSK" : "Re-generate the missing DSK PDF",
        onClick: () => doAction("genDsk", "Repair DSK", () => apiFetch("/api/v1/dsk/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch_id: batchId, awb: trackingNo || batchId, value_usd: ver.invoice_cif_total_usd || (audit.invoice_totals || {}).total_cif_usd || (_decResolved ? _decCifUsd : 0) }) }))
      },
      busy.genDsk ? "\u27F3 Repairing\u2026" : _dskBlocked ? "\u26A0 Repair DSK (CIF unresolved)" : "\u26A0 Repair DSK"
    )) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "outline",
        "data-testid": "btn-generate-dsk",
        disabled: !!busy.genDsk || _dskBlocked,
        title: _dskBlocked ? "Blocked: customs CIF unresolved \u2014 re-process invoices or confirm the AWB customs value before generating a DSK" : `Generate DSK PDF (Resolved CIF = ${_decCifLabel})`,
        onClick: () => doAction("genDsk", "Generate DSK", () => apiFetch("/api/v1/dsk/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch_id: batchId, awb: trackingNo || batchId, value_usd: ver.invoice_cif_total_usd || (audit.invoice_totals || {}).total_cif_usd || (_decResolved ? _decCifUsd : 0) }) }))
      },
      busy.genDsk ? "\u27F3 Generating\u2026" : _dskBlocked ? "\u229F DSK (CIF unresolved)" : "\u229F Generate DSK"
    ), /* @__PURE__ */ React.createElement(Btn, { variant: "ghost", disabled: true, title: "File not generated yet" }, "\u2193 DSK PDF"))), /* @__PURE__ */ React.createElement("details", { "data-testid": "dhl-advanced-tools", style: { borderTop: "1px solid var(--border-subtle)", paddingTop: 8 } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", userSelect: "none", marginBottom: 8 } }, "\u25B8 Advanced / Manual DHL tools"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginRight: 4 } }, "DHL Reply"), /* @__PURE__ */ React.createElement(Btn, { variant: "outline", disabled: !!busy.scan, onClick: async () => {
      setBusyKey("scan", true);
      try {
        const r = await apiFetch(`/api/v1/dhl/scan-inbox?batch_id=${encodeURIComponent(batchId)}`);
        setScanResult(r);
        onToast(`Inbox scanned \u2014 ${r.matched} matched.`, "success");
        await load();
        await loadTimeline();
      } catch (e) {
        onToast(`Scan failed: ${e.message}`, "error");
      } finally {
        setBusyKey("scan", false);
      }
    } }, busy.scan ? "\u27F3 Searching\u2026" : "\u2315 Find DHL Emails"), _drpSent ? /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 11,
      padding: "4px 10px",
      borderRadius: 4,
      background: "var(--badge-green-bg)",
      color: "var(--badge-green-text)",
      border: "1px solid var(--badge-green-border)",
      fontWeight: 600
    } }, "\u2713 Reply sent") : _drpQueued ? /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 11,
      padding: "4px 10px",
      borderRadius: 4,
      background: "var(--badge-amber-bg)",
      color: "var(--badge-amber-text)",
      border: "1px solid var(--badge-amber-border)",
      fontWeight: 600
    } }, "\u23F3 Reply queued") : _drpBuilt ? /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "gold",
        disabled: !!busy.sendReply,
        onClick: async () => {
          setBusyKey("sendReply", true);
          setDhlSendReplyResult(null);
          onToast("Running: Queue Reply to DHL\u2026", "info");
          try {
            const d = await apiFetch("/api/v1/execute/dhl_send_reply", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ batch_id: batchId, payload: {} })
            });
            setDhlSendReplyResult(d);
            if (!d.ok) {
              const reason = d.reason || d.error || "blocked";
              onToast(`Queue Reply to DHL blocked: ${reason}`, "error");
            } else if (d.status === "skipped") {
              onToast("DHL reply already queued.", "info");
              await Promise.all([loadDhlReadiness(), loadBatchReadiness(), loadDecision()]);
            } else {
              onToast("Queue Reply to DHL completed.", "success");
              await Promise.all([loadDhlReadiness(), loadBatchReadiness(), loadDecision()]);
            }
          } catch (e) {
            onToast(`Queue Reply to DHL failed: ${e.message}`, "error");
          } finally {
            setBusyKey("sendReply", false);
          }
        }
      },
      busy.sendReply ? "\u27F3 Queuing\u2026" : "\u2197 Queue Reply"
    ) : /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "outline",
        disabled: !!busy.buildPkg,
        onClick: () => doAction("buildPkg", "Build Reply Package", () => apiFetch("/api/v1/dsk/email-package", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch_id: batchId, awb: trackingNo || batchId }) }))
      },
      busy.buildPkg ? "\u27F3 Building\u2026" : "\u22A1 Build DHL Reply Package"
    ), _isAgency && /* @__PURE__ */ React.createElement(React.Fragment, null, _arpSent ? /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 11,
      padding: "4px 10px",
      borderRadius: 4,
      background: "var(--badge-green-bg)",
      color: "var(--badge-green-text)",
      border: "1px solid var(--badge-green-border)",
      fontWeight: 600
    } }, "\u2713 Agency sent") : _arpQueued ? /* @__PURE__ */ React.createElement("span", { style: {
      fontSize: 11,
      padding: "4px 10px",
      borderRadius: 4,
      background: "var(--badge-amber-bg)",
      color: "var(--badge-amber-text)",
      border: "1px solid var(--badge-amber-border)",
      fontWeight: 600
    } }, "\u23F3 Agency queued") : /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: _pdReady ? "gold" : "outline",
        disabled: !!busy.agencyEmail || !_pdReady,
        title: !_pdReady ? "Generate Polish Description first" : "Build & queue agency clearance email package",
        onClick: () => doAction(
          "agencyEmail",
          "Agency Email Package",
          () => apiFetch(`/api/v1/agency/email-package/${encodeURIComponent(batchId)}`, { method: "POST" })
        )
      },
      busy.agencyEmail ? "\u27F3 Building\u2026" : "\u{1F4E8} Build Agency Email"
    ))), dhlSendReplyResult && dhlSendReplyResult.status === "skipped" && (dhlSendReplyResult.stage === "milestone_skip" || dhlSendReplyResult.reason && dhlSendReplyResult.reason.startsWith("milestone_skip:")) && /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-reply-skip-msg", style: { marginTop: 6, fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, "Skipped: already progressed (SAD/PZ/Completed)"), dhlSendReplyResult && dhlSendReplyResult.log_write_failed && /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-reply-log-warn", style: { marginTop: 4, fontSize: 11, color: "var(--badge-amber-text)", fontWeight: 600 } }, "\u26A0 Action completed but log write failed"), (_drpQueued || _isAgency && _arpQueued) && /* @__PURE__ */ React.createElement("details", { style: { fontSize: 11 } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", color: "var(--text-2)", padding: "4px 0", userSelect: "none" } }, "\u25B8 More sending options"), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: "10px 12px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, display: "flex", gap: 8, flexWrap: "wrap" } }, _drpQueued && _drpQid && /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "gold",
        disabled: !!busy.sendDhlReply,
        title: "Send queued DHL reply via SMTP",
        onClick: () => doAction("sendDhlReply", "Send DHL Reply (SMTP)", async () => {
          const r = await apiFetch(`/api/v1/admin/email-queue/${encodeURIComponent(_drpQid)}/send`, { method: "POST" });
          if (r.error === "smtp_not_configured") onToast("SMTP not configured", "error");
          else if (r.ok && r.status === "sent") onToast("DHL reply sent \u2713", "success");
          else if (r.error) onToast(`Send failed: ${r.error_detail || r.error}`, "error");
          return r;
        })
      },
      busy.sendDhlReply ? "\u27F3\u2026" : "\u2197 DHL: SMTP"
    ), _isAgency && _arpQueued && _arpQid && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "gold",
        disabled: !!busy.sendAgency,
        title: "Send agency email via SMTP (Zoho App Password)",
        onClick: () => doAction("sendAgency", "Send Agency Email (SMTP)", async () => {
          const r = await apiFetch(
            `/api/v1/admin/email-queue/${encodeURIComponent(_arpQid)}/send`,
            { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method: "smtp" }) }
          );
          if (r.error === "SMTP_NOT_CONFIGURED" || r.error === "smtp_not_configured") onToast("SMTP not configured", "error");
          else if (r.ok && r.status === "sent") onToast(`Agency email sent \u2713`, "success");
          else if (r.error) onToast(`Send failed: ${r.error_detail || r.error}`, "error");
          return r;
        })
      },
      busy.sendAgency ? "\u27F3\u2026" : "\u2197 Agency: SMTP"
    ), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "outline",
        disabled: !!busy.sendAgencyMcp,
        title: "Fallback: Zoho Mail MCP \u2014 requires explicit confirmation",
        onClick: async () => {
          if (!confirm("\u26A0 Zoho MCP send will dispatch a real external email.\n\nProceed?")) return;
          const op = prompt("Approval \u2014 enter your name:", "admin");
          if (!op) return;
          setBusyKey("sendAgencyMcp", true);
          try {
            const r = await apiFetch(
              `/api/v1/admin/email-queue/${encodeURIComponent(_arpQid)}/send`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ method: "zoho_mcp", confirm_mcp_send: true, approved_by: op })
              }
            );
            if (r.error === "mcp_attachments_too_large") onToast("MCP refused: attachments exceed cap", "error");
            else if (r.ok && r.ready_for_mcp) onToast("MCP handoff ready", "info");
            else if (r.error) onToast(`MCP send failed: ${r.error_detail || r.error}`, "error");
            await load();
          } finally {
            setBusyKey("sendAgencyMcp", false);
          }
        }
      },
      busy.sendAgencyMcp ? "\u27F3 MCP\u2026" : "\u2197 Agency: MCP"
    ), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "ghost",
        disabled: !!busy.sendAgencyManual,
        title: "Emergency: copy package details for manual send",
        onClick: async () => {
          setBusyKey("sendAgencyManual", true);
          try {
            const r = await apiFetch(
              `/api/v1/admin/email-queue/${encodeURIComponent(_arpQid)}/send`,
              { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method: "manual_package" }) }
            );
            if (r.ok && r.package) {
              const lines = [
                "TO: " + (r.package.to || []).join(", "),
                "CC: " + (r.package.cc || []).join(", "),
                "Subject: " + r.package.subject,
                "",
                "Attachments (" + (r.package.attachments || []).length + "):",
                ...(r.package.attachments || []).map((a) => "  " + a.path)
              ].join("\n");
              await navigator.clipboard.writeText(lines).catch(() => {
              });
              onToast("Manual package copied to clipboard", "success");
            }
          } finally {
            setBusyKey("sendAgencyManual", false);
          }
        }
      },
      busy.sendAgencyManual ? "\u27F3\u2026" : "\u229F Agency: Manual"
    ))))));
  })(), !v2Active && /* @__PURE__ */ React.createElement("details", { "data-testid": "dhl-manual-mark-received", style: { padding: "0 20px 16px" } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", userSelect: "none", padding: "4px 0" } }, "\u25B8 Advanced / Manual DHL tools \u2014 Mark DHL email received"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", borderTop: "1px dashed var(--border)", paddingTop: 8, marginTop: 4 } }, /* @__PURE__ */ React.createElement(
    Btn,
    {
      variant: "ghost",
      disabled: !!busy.markRec,
      title: "Use only if Cowork email search returned 0 matches or is unavailable",
      onClick: () => {
        setMarkRecFields(_markRecDefaults);
        setConfirmingMarkRec(true);
      }
    },
    busy.markRec ? "\u27F3 Marking\u2026" : "\u21A9 Manual: Mark DHL Received"
  ))), /* @__PURE__ */ React.createElement("div", null, (() => {
    const clr = dhlClearance || "";
    const isActive = ["reply_package_prepared", "reply_queued", "reply_sent", "reply_failed"].includes(clr);
    if (!isActive) return null;
    const STEPS = [
      { key: "package", label: "Package Ready", states: ["reply_package_prepared", "reply_queued", "reply_sent", "reply_failed"] },
      { key: "queued", label: "Queued", states: ["reply_queued", "reply_sent", "reply_failed"] },
      { key: "sent", label: "Delivered", states: ["reply_sent"] },
      { key: "failed", label: "Failed", states: ["reply_failed"] }
    ];
    const isSent = clr === "reply_sent";
    const isFailed = clr === "reply_failed";
    const isQueued = clr === "reply_queued";
    const rs = replyStatus || {};
    return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 12, padding: "12px 14px", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" } }, "DHL Reply Delivery Status"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", disabled: !!busy.checkDelivery, onClick: async () => {
      setBusyKey("checkDelivery", true);
      try {
        const r = await apiFetch(`/api/v1/dhl/reply-status/${encodeURIComponent(batchId)}`);
        setReplyStatus(r);
        if (r.dhl_reply_status !== clr) {
          await load();
        }
      } catch (e) {
        onToast(`Status check failed: ${e.message}`, "error");
      } finally {
        setBusyKey("checkDelivery", false);
      }
    } }, busy.checkDelivery ? "\u27F3" : "\u21BB Check")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 0, marginBottom: 12 } }, STEPS.filter((s) => !(s.key === "failed" && !isFailed) && !(s.key === "sent" && isFailed)).map((s, i, arr) => {
      const done = s.states.includes(clr);
      const cur = s.key === "queued" && isQueued || s.key === "sent" && isSent || s.key === "failed" && isFailed || s.key === "package" && clr === "reply_package_prepared";
      const fail = s.key === "failed" && isFailed;
      const bg = fail ? "var(--badge-red-text)" : done ? GOLD : "var(--border)";
      return /* @__PURE__ */ React.createElement(React.Fragment, { key: s.key }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", alignItems: "center", gap: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { width: 22, height: 22, borderRadius: "50%", background: bg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: done ? "#fff" : "var(--text-3)", fontWeight: 700, border: `2px solid ${bg}` } }, fail ? "\u2717" : done ? "\u2713" : i + 1), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: cur ? fail ? "var(--badge-red-text)" : "var(--text)" : done ? "var(--text-2)" : "var(--text-3)", fontWeight: cur ? 700 : 400, whiteSpace: "nowrap" } }, s.label)), i < arr.length - 1 && /* @__PURE__ */ React.createElement("div", { style: { flex: 1, height: 2, background: s.states.includes(clr) ? GOLD : "var(--border)", marginBottom: 14 } }));
    })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", display: "flex", flexDirection: "column", gap: 3 } }, audit.dhl_reply_to && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "To: "), audit.dhl_reply_to), audit.dhl_reply_subject && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Subject: "), audit.dhl_reply_subject), audit.dhl_reply_queued_at && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Queued: "), audit.dhl_reply_queued_at.slice(0, 19).replace("T", " "), " UTC"), (rs.sent_at || audit.dhl_reply_sent_at) && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-green-text)", fontWeight: 600 } }, "\u2713 Delivered: ", (rs.sent_at || audit.dhl_reply_sent_at).slice(0, 19).replace("T", " "), " UTC"), isFailed && (rs.error || audit.dhl_reply_error) && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text)", fontWeight: 600 } }, "\u2717 Error: ", rs.error || audit.dhl_reply_error), isQueued && !rs.sent_at && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-amber-text)" } }, "\u23F3 Pending \u2014 email connector pickup required")));
  })()), confirmingMarkRec && /* @__PURE__ */ React.createElement("div", { style: { margin: "0 20px 16px", padding: 16, background: "var(--bg-subtle)", borderRadius: 6, border: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 14 } }, "Mark DHL Email as Received"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "DHL Ticket ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-amber-text)" } }, "\u2605")), /* @__PURE__ */ React.createElement(Inp, { value: markRecFields.ticket, onChange: (e) => setMarkRecFields((p) => ({ ...p, ticket: e.target.value })), placeholder: "e.g. T#1WA2604140000123", style: { width: "100%" } })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "Request Type"), /* @__PURE__ */ React.createElement(
    "select",
    {
      value: markRecFields.request_type,
      onChange: (e) => setMarkRecFields((p) => ({ ...p, request_type: e.target.value })),
      style: { width: "100%", padding: "6px 10px", borderRadius: 5, border: "1px solid var(--border)", background: "var(--card)", color: "var(--text)", fontSize: 12 }
    },
    /* @__PURE__ */ React.createElement("option", { value: "unknown" }, "Unknown"),
    /* @__PURE__ */ React.createElement("option", { value: "polish_description" }, "Polish Description (DHL self-clear)"),
    /* @__PURE__ */ React.createElement("option", { value: "dsk_broker" }, "DSK \u2014 Broker clearance")
  )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "Subject"), /* @__PURE__ */ React.createElement(Inp, { value: markRecFields.subject, onChange: (e) => setMarkRecFields((p) => ({ ...p, subject: e.target.value })), placeholder: "Email subject line", style: { width: "100%" } })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "Sender"), /* @__PURE__ */ React.createElement(Inp, { value: markRecFields.sender, onChange: (e) => setMarkRecFields((p) => ({ ...p, sender: e.target.value })), placeholder: "odprawacelna@dhl.com", style: { width: "100%" } }))), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, "Note ", /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 400 } }, "(optional \u2014 visible in audit)")), /* @__PURE__ */ React.createElement(Inp, { value: markRecFields.note, onChange: (e) => setMarkRecFields((p) => ({ ...p, note: e.target.value })), placeholder: "Manual entry reason, operator name, etc.", style: { width: "100%" } })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement(Btn, { variant: "gold", disabled: !!busy.markRec, onClick: async () => {
    setBusyKey("markRec", true);
    try {
      await apiFetch(`/api/v1/dhl/mark-email-received/${encodeURIComponent(batchId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(markRecFields)
      });
      onToast("DHL email marked received.", "success");
      setConfirmingMarkRec(false);
      await load();
    } catch (e) {
      onToast(`Mark received failed: ${e.message}`, "error");
    } finally {
      setBusyKey("markRec", false);
    }
  } }, busy.markRec ? "\u27F3 Saving\u2026" : "\u2713 Confirm Received"), /* @__PURE__ */ React.createElement(Btn, { variant: "outline", onClick: () => setConfirmingMarkRec(false) }, "Cancel"))), scanResult && (() => {
    const _isPending = scanResult.scan_method === "ai_bridge_pending";
    return /* @__PURE__ */ React.createElement("div", { style: { margin: "0 20px 16px", padding: 14, background: "var(--bg-subtle)", borderRadius: 6, border: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: scanResult.matched > 0 || _isPending ? 10 : 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" } }, _isPending ? "Scan In Progress" : "Last Scan Result"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)" } }, _isPending ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-blue-text)", fontWeight: 700 } }, "\u23F3 Cowork search pending \u2014 final result not yet available") : /* @__PURE__ */ React.createElement(React.Fragment, null, "Scanned ", scanResult.scanned, " \xB7 ", /* @__PURE__ */ React.createElement("span", { style: { color: scanResult.matched > 0 ? "var(--badge-amber-text)" : "var(--badge-green-text)", fontWeight: 700 } }, scanResult.matched, " matched")), scanResult.scanned_at && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 8, color: "var(--text-3)" } }, scanResult.scanned_at.slice(0, 16).replace("T", " "), " UTC"))), (scanResult.search_mode || scanResult.scan_method) && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: scanResult.matched > 0 ? 8 : 4, display: "flex", gap: 10, flexWrap: "wrap" } }, scanResult.search_mode && /* @__PURE__ */ React.createElement("span", null, "Mode: ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, scanResult.search_mode)), scanResult.awb_used && /* @__PURE__ */ React.createElement("span", null, "AWB: ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, scanResult.awb_used)), scanResult.scan_method && /* @__PURE__ */ React.createElement("span", null, "Source: ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, scanResult.scan_method))), scanResult.matched === 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, scanResult.scan_method === "ai_bridge_pending" ? scanResult.bridge_task?.message || "Email scan dispatched to AI Bridge." : scanResult.scan_method === "no_credentials" ? "Mailbox not connected \u2014 set ZOHO_MAIL_API_TOKEN in .env to enable inbox scan." : scanResult.awb_used ? `No match found for AWB ${scanResult.awb_used}. Checked subject, body, attachments, and forwarded content across DHL / agency / Ganther / internal senders.` : "No shipment-related emails found. Checked subject, body, attachments, and forwarded content."), scanResult.bridge_task && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: 8, borderRadius: 4, background: "var(--badge-blue-bg)", border: "1px solid var(--badge-blue-border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--badge-blue-text)", marginBottom: 2 } }, "\u23F3 Waiting for Cowork email search"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, "Task ID: ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, scanResult.bridge_task.task_id)), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", marginTop: 2 } }, "Cowork searches Zoho via MCP. Once it posts results back, the system auto-applies the DHL detection and advances clearance state.")), scanResult.cached && scanResult.scan_method === "email_intelligence_cache" && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: 8, borderRadius: 4, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--badge-green-text)" } }, "\u2713 Stored email intelligence found"), /* @__PURE__ */ React.createElement(
      "button",
      {
        disabled: !!busy.scan,
        onClick: async () => {
          setBusyKey("scan", true);
          try {
            const r = await apiFetch(`/api/v1/dhl/scan-inbox?batch_id=${encodeURIComponent(batchId)}&refresh=true`);
            setScanResult(r);
            onToast(`Re-scan dispatched`, "info");
          } catch (e) {
            onToast(`Re-scan failed: ${e.message}`, "error");
          } finally {
            setBusyKey("scan", false);
          }
        },
        style: { fontSize: 10, padding: "2px 8px", background: "none", border: "1px solid var(--badge-green-border)", borderRadius: 3, color: "var(--badge-green-text)", cursor: busy.scan ? "default" : "pointer" }
      },
      "\u21BB Re-run Cowork search"
    )), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, "Last scan: ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, (scanResult.cached.last_scanned_at || "").slice(0, 19).replace("T", " ")), scanResult.cached.source && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 8 } }, "\xB7 source: ", /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10 } }, scanResult.cached.source))), scanResult.cached.linked_batches && scanResult.cached.linked_batches.length > 1 && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", marginTop: 2 } }, "Linked batches: ", scanResult.cached.linked_batches.length)), scanResult.search_context && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, padding: 8, borderRadius: 4, background: "var(--card)", border: "1px solid var(--border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 } }, "Search context"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, "AWB searched: ", /* @__PURE__ */ React.createElement("code", null, scanResult.search_context.awb || "\u2014")), scanResult.search_context.invoice_numbers && scanResult.search_context.invoice_numbers.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)", marginTop: 2 } }, "Invoice numbers searched: ", /* @__PURE__ */ React.createElement("code", null, scanResult.search_context.invoice_numbers.slice(0, 5).join(", "), scanResult.search_context.invoice_numbers.length > 5 ? ` +${scanResult.search_context.invoice_numbers.length - 5} more` : "")), scanResult.search_context.dhl_ticket && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)", marginTop: 2 } }, "DHL ticket: ", /* @__PURE__ */ React.createElement("code", null, scanResult.search_context.dhl_ticket)), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", marginTop: 3 } }, "Search used AWB + invoice numbers \xB7 ", scanResult.search_context.search_terms_count, " search terms total")), (audit.email_search_risk || scanResult.email_scan_results && scanResult.email_scan_results.search_unreliable) && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, padding: 8, borderRadius: 4, background: "var(--badge-amber-bg)", border: "1px solid var(--badge-amber-border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--badge-amber-text)", marginBottom: 2 } }, "\u26A0 Manual Zoho verification required"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-2)" } }, "Cowork returned 0 matches, but strong identifiers (AWB/invoice numbers) exist. The search may have missed emails. Open Zoho UI and verify before treating as 'no email'."), audit.email_search_risk_reason && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", marginTop: 3 } }, audit.email_search_risk_reason)), scanResult.derived_events && scanResult.derived_events.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: 8, borderRadius: 4, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)", fontSize: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "var(--badge-green-text)", marginBottom: 4 } }, "\u2713 Detected workflow events (", scanResult.derived_events.length, ")"), scanResult.derived_events.slice(0, 5).map((ev, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { marginBottom: 2, color: "var(--text-2)" } }, /* @__PURE__ */ React.createElement("code", { style: { fontSize: 10, color: "var(--badge-green-text)" } }, ev.event), ev.source_email_subject && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 6, color: "var(--text-3)" } }, "\u2014 ", ev.source_email_subject))), scanResult.recommended_next_action && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--badge-green-border)", color: "var(--badge-green-text)" } }, /* @__PURE__ */ React.createElement("strong", null, "Recommended next:"), " ", scanResult.recommended_next_action.replace(/_/g, " "))), (scanResult.emails || []).slice(0, 5).map((em, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "8px 10px", borderRadius: 5, border: "1px solid var(--border)", background: "var(--card)", marginBottom: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "var(--text)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, em.subject || em.raw_subject || "\u2014"), em.awb && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-blue-bg)", color: "var(--badge-blue-text)", fontWeight: 700, whiteSpace: "nowrap" } }, "AWB ", em.awb), em.dhl_ticket && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-neutral-bg)", color: "var(--text-2)", whiteSpace: "nowrap" } }, em.dhl_ticket), em.detected_type && em.detected_type !== "unknown" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-amber-bg)", color: "var(--badge-amber-text)", whiteSpace: "nowrap" } }, em.detected_type.replace(/_/g, " ")), em.sender_role && em.sender_role !== "unknown" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "var(--badge-neutral-bg)", color: "var(--text-2)", whiteSpace: "nowrap" } }, em.sender_role)), em.from && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-2)", marginTop: 3 } }, em.from), em.matched_fields && em.matched_fields.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, "Matched: ", em.matched_fields.join(", ")), em.attachments && em.attachments.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, "Attachments: ", em.attachments.map((a) => `${a.filename} (${a.type})`).join(", ")), em.body_snippet && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, em.body_snippet.slice(0, 120)))), scanResult.matched > 5 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 4 } }, "+", scanResult.matched - 5, " more \u2014 see DHL Clearance page for full list"));
  })()), (() => {
    const cd = audit.customs_declaration || {};
    const fmtUSD = (v) => v != null ? "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : null;
    const invCurrency = (audit.invoice_totals || {}).currency || cd.currency || (audit.inputs || {}).currency || "USD";
    const sadParsed = !!(cd.mrn || cd.duty_a00_pln != null || cd.sad_customs_rate || cd.exchange_rate);
    const sadBadge = sadParsed ? "Customs Parsed" : hasSad ? "SAD Uploaded" : "SAD Pending";
    const criticalKeys = ["cif_match", "invoice_refs_match", "blocked_phrases_clean", "duty_rate_ok"];
    const complianceKeys = ["importer_match", "qty_match_by_type"];
    const isBlocked = criticalKeys.some((k) => ver[k] === false);
    const isReview = !isBlocked && (criticalKeys.some((k) => k in ver && ver[k] === null) || complianceKeys.some((k) => k in ver && ver[k] === false));
    const customsStatus = !hasSad ? "pending" : isBlocked ? "blocked" : isReview ? "review" : hasSad ? "safe" : "pending";
    const VER_GROUPS = [
      {
        label: "Critical",
        color: "var(--badge-red-text)",
        checks: [
          { key: "cif_match", label: "CIF value match", nullHint: "SAD CIF not parsed \u2014 verify manually", falseHint: "Invoice CIF differs from SAD CIF" },
          { key: "invoice_refs_match", label: "Invoice refs in SAD", nullHint: "Invoice refs not found in SAD format", falseHint: "Invoice reference not found in SAD document" },
          { key: "blocked_phrases_clean", label: "Invoice content clean", nullHint: null, falseHint: "Blocked phrases detected in invoice text" },
          { key: "duty_rate_ok", label: "Duty rate valid", nullHint: null, falseHint: "Duty rate check failed \u2014 review A00 calculation" }
        ]
      },
      {
        label: "Compliance",
        color: "var(--badge-amber-text)",
        checks: [
          { key: "importer_match", label: "Importer name match", nullHint: "Invoice importer not parsed \u2014 verify manually", falseHint: "Importer name differs between invoice and SAD" },
          { key: "exporter_match", label: "Exporter in SAD", nullHint: "Not in SAD \u2014 verify manually", falseHint: "Exporter name mismatch" },
          { key: "vat_match", label: "VAT number match", nullHint: "Invoice has no VAT field \u2014 expected", falseHint: "VAT number mismatch" },
          { key: "qty_match_by_type", label: "Qty by category", nullHint: "SAD uses combined description \u2014 verify manually", falseHint: "Quantity by type mismatch" }
        ]
      }
    ];
    const cifInv = ver.invoice_cif_total_usd;
    const cifSad = ver.sad_cif_total_usd;
    const cifDiff = ver.cif_difference_usd;
    const _cdDec = audit.clearance_decision || {};
    const cifResolved = _cdDec.cif_state === "resolved" && _cdDec.total_value_usd != null && Number(_cdDec.total_value_usd) > 0 ? Number(_cdDec.total_value_usd) : null;
    const cifInvParsed = cifInv != null && cifInv > 0;
    const cifCompareIsResolved = !cifInvParsed && cifResolved != null;
    const showCif = hasSad && (cifInv != null || cifSad != null || cifResolved != null);
    return /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement(
      SectionHeader,
      {
        icon: "\u229F",
        title: "Section 2 \u2014 Customs Documents",
        subtitle: "SAD / ZC429 upload, customs values, MRN verification",
        status: sadBadge
      }
    )), /* @__PURE__ */ React.createElement("div", { style: { paddingRight: 20, flexShrink: 0 } }, /* @__PURE__ */ React.createElement("span", { style: {
      background: customsStatus === "safe" ? "var(--badge-green-bg)" : customsStatus === "blocked" ? "var(--badge-red-bg)" : customsStatus === "review" ? "var(--badge-amber-bg)" : "var(--badge-neutral-bg)",
      color: customsStatus === "safe" ? "var(--badge-green-text)" : customsStatus === "blocked" ? "var(--badge-red-text)" : customsStatus === "review" ? "var(--badge-amber-text)" : "var(--badge-neutral-text)",
      border: `1px solid ${customsStatus === "safe" ? "var(--badge-green-border)" : customsStatus === "blocked" ? "var(--badge-red-border)" : customsStatus === "review" ? "var(--badge-amber-border)" : "var(--badge-neutral-border)"}`,
      borderRadius: 4,
      padding: "2px 10px",
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: "0.04em"
    } }, customsStatus === "safe" ? "\u{1F7E2} SAFE" : customsStatus === "blocked" ? "\u{1F534} BLOCKED" : customsStatus === "review" ? "\u{1F7E1} REVIEW" : "\u2014 PENDING"))), /* @__PURE__ */ React.createElement("div", { style: { padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "Document References"), /* @__PURE__ */ React.createElement(InfoRow, { label: "SAD / ZC429 Status", value: hasSad ? "Uploaded \u2713" : "Not uploaded" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "MRN", value: mrn, mono: true }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Clearance Date", value: cd.clearance_date || inp.clearance_date || "Not available in SAD" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Customs Agent", value: cd.customs_agent || inp.agent || "Not parsed from SAD" }), /* @__PURE__ */ React.createElement(
      InfoRow,
      {
        label: "VAT Settlement",
        value: (() => {
          const mode = inp.settlement_mode || audit.settlement_mode;
          const isArt33a = mode === "art33a" ? true : mode === "standard" ? false : hasSad ? Boolean(cd.art33a) : null;
          if (isArt33a === null) return "\u2014";
          return isArt33a ? /* @__PURE__ */ React.createElement("span", { title: "Art. 33a \u2014 VAT is not paid at customs. It is settled later in the company's periodic VAT return." }, "Art. 33a \u2014 deferred \u2139") : /* @__PURE__ */ React.createElement("span", { title: "Standard import \u2014 VAT is paid at customs upon clearance, together with duty." }, "Standard \u2014 paid at customs \u2139");
        })()
      }
    )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "Values & Checks"), /* @__PURE__ */ React.createElement(InfoRow, { label: "SAD Exchange Rate", value: cd.sad_customs_rate ? `${invCurrency}/PLN ${cd.sad_customs_rate}` : hasSad ? "Not in SAD" : "\u2014" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "NBP Accounting Rate", value: cd.nbp_rate ? `${invCurrency}/PLN ${cd.nbp_rate}` + (cd.nbp_table ? ` (${cd.nbp_table}, ${cd.nbp_date || ""})` : "") : hasSad ? "Fetched during Run PZ" : "\u2014" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Rate Delta", value: cd.rate_delta_pct != null ? `${cd.rate_delta_pct > 0 ? "+" : ""}${cd.rate_delta_pct.toFixed(3)}%` + (cd.rate_alert ? " \u26A0" : " \u2713") : hasSad ? "Calculated during Run PZ" : "\u2014" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "A00 Duty (PLN)", value: fmtPLN(cd.duty_a00_pln ?? t.duty) }), /* @__PURE__ */ React.createElement(InfoRow, { label: "B00 VAT (PLN)", value: cd.vat_b00_pln != null ? fmtPLN(cd.vat_b00_pln) + " (ref only \u2014 not in landed cost)" : hasSad ? "Not parsed from SAD" : "\u2014" }))), showCif && /* @__PURE__ */ React.createElement("div", { style: { margin: "0 20px 16px", padding: 12, background: "var(--bg-subtle)", borderRadius: 6, border: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "CIF Comparison"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px", fontSize: 11 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Invoice CIF:"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: "var(--text)" } }, cifInvParsed ? fmtUSD(cifInv) : cifResolved != null ? "not parsed" : fmtUSD(cifInv) || "\u2014"), cifResolved != null && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Resolved CIF:"), /* @__PURE__ */ React.createElement("span", { "data-testid": "cif-compare-resolved", style: { fontWeight: 600, color: "var(--badge-green-text)" } }, fmtUSD(cifResolved))), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "SAD CIF:"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: "var(--text)" } }, fmtUSD(cifSad) || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Difference:"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: cifSad === 0 && (cifInvParsed || cifResolved != null) ? "var(--badge-amber-text)" : !cifCompareIsResolved && cifDiff === 0 || cifCompareIsResolved && cifSad != null && Math.abs(cifSad - cifResolved) < 0.01 ? "var(--badge-green-text)" : "var(--badge-amber-text)" } }, cifSad === 0 && (cifInvParsed || cifResolved != null) ? "SAD CIF not parsed \u2014 [VERIFY-GAP]" : cifCompareIsResolved ? cifSad != null ? `${cifSad - cifResolved >= 0 ? "+" : ""}${fmtUSD(cifSad - cifResolved)} ${Math.abs(cifSad - cifResolved) < 0.01 ? "\u2713" : "\u26A0"} (vs resolved)` : "\u2014" : cifDiff != null ? `${cifDiff > 0 ? "+" : ""}${fmtUSD(cifDiff)} ${cifDiff === 0 ? "\u2713" : "\u26A0"}` : "\u2014"))), hasSad && ver && Object.keys(ver).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { margin: "0 20px 16px", padding: 14, background: "var(--bg-subtle)", borderRadius: 6, border: "1px solid var(--border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 } }, "Verification Checks"), audit.sad_invoice_authority && (() => {
      const sia = audit.sad_invoice_authority;
      const s = sia.status;
      const statusLabel = s === "matched_structured_n935" ? "\u2713 Verified (N935)" : s === "n935_absent" ? "Structured reference unavailable" : s === "n935_present_mismatch" ? "\u26A0 Mismatch \u2014 verify N935 refs" : "\u26A0 Needs review";
      const statusColor = s === "matched_structured_n935" ? "var(--badge-green-text)" : s === "n935_present_mismatch" ? "var(--badge-red-text)" : "var(--badge-amber-text)";
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "sad-invoice-authority-row",
          style: {
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            fontSize: 11,
            padding: "4px 0 8px",
            borderBottom: "1px solid var(--border-subtle)",
            marginBottom: 8
          }
        },
        /* @__PURE__ */ React.createElement("span", { style: {
          fontSize: 12,
          fontWeight: 700,
          flexShrink: 0,
          marginTop: 1,
          color: statusColor
        } }, s === "matched_structured_n935" ? "\u2713" : s === "n935_present_mismatch" ? "\u2717" : "\u26A0"),
        /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: "var(--text)" } }, "SAD Invoice Refs "), /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": "sad-invoice-authority-status",
            style: { color: statusColor, fontWeight: 600 }
          },
          statusLabel
        ), s === "matched_structured_n935" && sia.references.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, sia.references.join(" \xB7 ")), sia.review_reason && s !== "matched_structured_n935" && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 } }, sia.review_reason))
      );
    })(), VER_GROUPS.map((group, groupIdx) => {
      const visibleChecks = group.checks.filter((check) => check.key in ver);
      if (visibleChecks.length === 0) return null;
      const cr = audit.compliance_resolution || null;
      return /* @__PURE__ */ React.createElement("div", { key: group.label }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, fontWeight: 700, color: group.color, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4, marginTop: groupIdx > 0 ? 12 : 0 } }, group.label), visibleChecks.map((check) => {
        const v = ver[check.key];
        let state;
        if (v === true) {
          state = "ok";
        } else if (v === false) {
          state = "error";
        } else if (cr && cr[check.key] && cr[check.key].state === "intelligence_resolved") {
          state = "resolved";
        } else {
          state = "gap";
        }
        const stateColor = state === "ok" ? "var(--badge-green-text)" : state === "resolved" ? "var(--badge-blue-text)" : state === "error" ? "var(--badge-red-text)" : "var(--badge-amber-text)";
        const stateIcon = state === "ok" ? "\u2713" : state === "resolved" ? "\u25C9" : state === "error" ? "\u2717" : "\u26A0";
        const resolvedEvidence = state === "resolved" && cr && cr[check.key] ? cr[check.key].evidence : null;
        return /* @__PURE__ */ React.createElement("div", { key: check.key, "data-testid": `compliance-row-${check.key}`, style: { display: "flex", alignItems: "flex-start", gap: 8, fontSize: 11, padding: "4px 0", borderBottom: "1px solid var(--border-subtle)" } }, /* @__PURE__ */ React.createElement("span", { style: {
          fontSize: 12,
          fontWeight: 700,
          flexShrink: 0,
          marginTop: 1,
          color: stateColor
        } }, stateIcon), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: state === "error" ? "var(--badge-red-text)" : "var(--text)" } }, check.label), state === "resolved" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-blue-text)", marginLeft: 6, fontSize: 10 } }, "\u2014 Intelligence resolved"), state === "resolved" && resolvedEvidence && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", fontSize: 10, marginTop: 2 } }, resolvedEvidence), state === "gap" && check.nullHint && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", marginLeft: 6 } }, "\u2014 ", check.nullHint), state === "error" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-red-text)", marginLeft: 6 } }, "\u2014 ", check.falseHint)));
      }));
    }), ver.rate_note && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, padding: "6px 8px", background: "var(--bg)", borderRadius: 4, border: "1px solid var(--border-subtle)", fontSize: 10, color: "var(--text-3)" } }, "\u2139 ", ver.rate_note)), !v2Active && /* @__PURE__ */ React.createElement("div", { style: { padding: "0 20px 12px", display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "ghost",
        disabled: recheckBusy,
        onClick: async () => {
          setRecheckBusy(true);
          setRecheckPanel(null);
          try {
            const res = await apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}/recheck`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ mode: "sad" })
            });
            setRecheckPanel(res);
            await load();
            await loadTimeline();
            onToast(res.ok ? "SAD re-parsed \u2014 values updated" : "Recheck completed with errors", res.ok ? "success" : "error");
          } catch (e) {
            onToast("Recheck failed: " + e.message, "error");
          } finally {
            setRecheckBusy(false);
          }
        }
      },
      recheckBusy ? "\u27F3 Re-parsing\u2026" : "\u27F3 Re-parse SAD & Re-verify"
    ), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "Re-runs SAD parser against existing uploaded file")), /* @__PURE__ */ React.createElement("div", { style: { padding: "0 20px 16px", display: "flex", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement("label", { style: { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 6, border: "1px solid var(--badge-neutral-border)", cursor: "pointer", fontSize: 12, fontWeight: 600, color: "var(--text)", background: "transparent" } }, /* @__PURE__ */ React.createElement("input", { ref: sadRef, type: "file", accept: ".pdf", style: { display: "none" }, onChange: async (e) => {
      if (!e.target.files[0]) return;
      const fd2 = new FormData();
      fd2.append("sad", e.target.files[0]);
      await doAction("sadUp", "Upload SAD", async () => {
        const r = await fetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/sad`, { method: "POST", body: fd2, credentials: "include" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });
    } }), "\u229E Upload SAD / ZC429"), hasSad && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--badge-green-text)" } }, "\u2713 SAD uploaded \u2014 customs values parsed")));
  })()), activeTab === "DHL / Customs" && (() => {
    const dr = dhlReadiness;
    const isErr = dhlReadinessError && !dr;
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12 }, "data-testid": "dhl-readiness-panel" }, /* @__PURE__ */ React.createElement(
      ReadinessBanner,
      {
        "data-testid": "readiness-banner-dhl",
        domain: "dhl",
        status: batchReadiness && batchReadiness.dhl ? batchReadiness.dhl.status : null,
        ready: batchReadiness && batchReadiness.dhl ? batchReadiness.dhl.ready : false,
        message: batchReadiness && batchReadiness.dhl ? batchReadiness.dhl.message : null,
        loading: batchReadinessLoading && !batchReadiness,
        error: batchReadinessError
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u2708 DHL Customs Pipeline"), /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: loadDhlReadiness, disabled: dhlReadinessLoading }, dhlReadinessLoading ? "Loading\u2026" : "\u21BA Refresh")), dhlReadinessLoading && !dr && /* @__PURE__ */ React.createElement(Card, { style: { padding: 24, textAlign: "center", color: "var(--text-3)", fontSize: 12 } }, "Loading DHL pipeline\u2026"), isErr && /* @__PURE__ */ React.createElement(Card, { style: { padding: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--badge-red-text)", fontWeight: 600 } }, "DHL readiness failed: ", dhlReadinessError)), !dhlReadinessLoading && !isErr && !dr && /* @__PURE__ */ React.createElement(Card, { style: { padding: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-3)" } }, "No DHL readiness data available.")), dr && (() => {
      const STAGES = [
        { key: "awaiting_start", label: "Awaiting Start", icon: "\u25CB" },
        { key: "dhl_contacted", label: "DHL Contacted", icon: "\u{1F4E7}" },
        { key: "dhl_replied", label: "DHL Replied", icon: "\u{1F4E8}" },
        { key: "dsk_received", label: "DSK / Cesja Rcvd", icon: "\u{1F4C4}" },
        { key: "agency_forwarded", label: "Agency Forwarded", icon: "\u{1F4E4}" },
        { key: "sad_received", label: "SAD Received", icon: "\u2714" },
        { key: "customs_cleared", label: "Customs Cleared", icon: "\u2705" }
      ];
      const currentStage = dr.dhl_status || "awaiting_start";
      const currentIdx = STAGES.findIndex((s) => s.key === currentStage);
      const fmtTs = (ts) => {
        if (!ts) return "\u2014";
        try {
          return new Date(ts).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
        } catch {
          return ts;
        }
      };
      return /* @__PURE__ */ React.createElement(React.Fragment, null, dr.sla_breach && /* @__PURE__ */ React.createElement(Card, { style: { padding: "12px 16px", background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 700, color: "var(--badge-red-text)", marginBottom: 4 } }, "\u26A0 SLA Breach \u2014 no DHL response"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-red-text)", opacity: 0.85 } }, dr.sla_breach_reason || `No response after ${dr.days_since_last_outbound != null ? dr.days_since_last_outbound.toFixed(1) : "?"} day(s)`)), /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 14 } }, "Pipeline Stages"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, STAGES.map((s, i) => {
        const isCompleted = i < currentIdx;
        const isCurrent = i === currentIdx;
        const isPending = i > currentIdx;
        const dotColor = isCompleted ? "var(--badge-green-text)" : isCurrent ? dr.sla_breach ? "var(--badge-red-text)" : "var(--badge-blue-text)" : "var(--text-3)";
        return /* @__PURE__ */ React.createElement("div", { key: s.key, style: { display: "flex", alignItems: "center", gap: 10, opacity: isPending ? 0.45 : 1 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16, width: 22, textAlign: "center", color: dotColor } }, isCompleted ? "\u2713" : s.icon), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: isCurrent ? 700 : 400, color: isCurrent ? "var(--text)" : "var(--text-2)" } }, s.label), isCurrent && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "1px 7px", borderRadius: 4, background: dr.sla_breach ? "var(--badge-red-bg)" : "var(--badge-blue-bg)", color: dr.sla_breach ? "var(--badge-red-text)" : "var(--badge-blue-text)", fontWeight: 700, border: `1px solid ${dr.sla_breach ? "var(--badge-red-border)" : "var(--badge-blue-border)"}` } }, "Current"));
      })))), /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 } }, "Details"), [
        ["AWB", dr.awb || "\u2014"],
        ["Carrier", dr.carrier || "\u2014"],
        ["DHL Initial Sent", fmtTs(dr.dhl_initial_sent)],
        ["DHL Reply Received", fmtTs(dr.dhl_reply_received)],
        ["DSK Docs Received", fmtTs(dr.dsk_docs_received)],
        ["Agency Forwarded", fmtTs(dr.agency_forwarded)],
        ["SAD Received", fmtTs(dr.sad_received)],
        ["Customs Cleared", fmtTs(dr.customs_cleared)],
        ["Days since outbound", dr.days_since_last_outbound != null ? `${dr.days_since_last_outbound.toFixed(1)} day(s)` : "\u2014"]
      ].map(([label, value]) => /* @__PURE__ */ React.createElement("div", { key: label, style: { display: "flex", gap: 8, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-3)", minWidth: 160 } }, label), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text)", fontFamily: "monospace" } }, value))), (dr.missing_documents || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", marginBottom: 4 } }, "Missing documents"), (dr.missing_documents || []).map((d) => /* @__PURE__ */ React.createElement("div", { key: d, style: { fontSize: 11, color: "var(--badge-amber-text)" } }, "\u2022 ", d))))), dr.next_required_action && /* @__PURE__ */ React.createElement(Card, { style: { padding: "12px 16px", background: "var(--bg-subtle)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 } }, "Next required action"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text)", lineHeight: 1.5 }, "data-testid": "dhl-next-required-action" }, dr.next_required_action)), (() => {
        const sla = audit.agency_sla || {};
        if (!sla.started) return null;
        const textCol = sla.stopped ? "var(--badge-green-text)" : "var(--badge-blue-text)";
        const fmtSlaTs = (ts) => {
          if (!ts) return "";
          try {
            return new Date(ts).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
          } catch {
            return ts;
          }
        };
        return /* @__PURE__ */ React.createElement(Card, { style: { padding: "12px 16px", background: sla.stopped ? "var(--badge-green-bg)" : "var(--badge-blue-bg)", border: `1px solid ${sla.stopped ? "var(--badge-green-border)" : "var(--badge-blue-border)"}` }, "data-testid": "agency-sla-status" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: textCol } }, sla.stopped ? "\u2705 Agency SLA completed" : "\u23F3 Agency SLA active"), sla.started_at && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: textCol, opacity: 0.8, marginTop: 2 }, "data-testid": "agency-sla-started-at" }, "Started: ", fmtSlaTs(sla.started_at)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: textCol, opacity: 0.8, marginTop: 1 }, "data-testid": "agency-sla-start-trigger" }, "Trigger: Agency forward sent"), sla.stopped && sla.stopped_at && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: textCol, opacity: 0.8, marginTop: 2 }, "data-testid": "agency-sla-stopped-at" }, "Stopped: ", fmtSlaTs(sla.stopped_at)), sla.stopped && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: textCol, opacity: 0.8, marginTop: 1 }, "data-testid": "agency-sla-stop-trigger" }, "Trigger: SAD received"));
      })(), (() => {
        const sadParse = audit.agency_sad_parse || {};
        if (!sadParse.status) return null;
        const cfg = {
          parsed: { bg: "var(--badge-green-bg)", border: "var(--badge-green-border)", text: "var(--badge-green-text)", label: "\u{1F4C4} Agency SAD parsed" },
          partial: { bg: "var(--badge-warn-bg)", border: "var(--badge-warn-border)", text: "var(--badge-warn-text)", label: "\u26A0\uFE0F SAD partially parsed" },
          awaiting_file: { bg: "var(--badge-blue-bg)", border: "var(--badge-blue-border)", text: "var(--badge-blue-text)", label: "\u23F3 Waiting for file upload" }
        }[sadParse.status] || { bg: "var(--surface-2)", border: "var(--border)", text: "var(--text-3)", label: sadParse.status };
        return /* @__PURE__ */ React.createElement(Card, { style: { padding: "10px 16px", background: cfg.bg, border: `1px solid ${cfg.border}`, marginTop: 6 }, "data-testid": "agency-sad-parse-status" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: cfg.text } }, cfg.label), sadParse.confidence && sadParse.status !== "awaiting_file" && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: cfg.text, opacity: 0.8, marginTop: 2 }, "data-testid": "agency-sad-parse-confidence" }, "Confidence: ", sadParse.confidence));
      })(), (() => {
        const sadDecision = audit.agency_sad_decision || {};
        if (sadDecision.safe_to_run_pz === void 0) return null;
        const safe = sadDecision.safe_to_run_pz === true;
        const fmtTs2 = (ts) => {
          if (!ts) return "";
          try {
            return new Date(ts).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
          } catch {
            return ts;
          }
        };
        return /* @__PURE__ */ React.createElement(Card, { style: { padding: "10px 16px", background: safe ? "var(--badge-green-bg)" : "var(--badge-red-bg, #fff0f0)", border: `1px solid ${safe ? "var(--badge-green-border)" : "var(--badge-red-border, #f5c6c6)"}`, marginTop: 6 }, "data-testid": "agency-sad-decision" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: safe ? "var(--badge-green-text)" : "var(--badge-red-text, #c0392b)" } }, safe ? "\u2705 Safe to run PZ" : "\u26D4 Not safe to run PZ"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: safe ? "var(--badge-green-text)" : "var(--badge-red-text, #c0392b)", opacity: 0.85, marginTop: 2 }, "data-testid": "agency-sad-decision-reason" }, "Reason: ", sadDecision.reason), sadDecision.evaluated_at && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginTop: 2 }, "data-testid": "agency-sad-decision-evaluated-at" }, "Evaluated: ", fmtTs2(sadDecision.evaluated_at)), sadDecision.mrn_parsed && sadDecision.mrn_declared && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, paddingTop: 6, borderTop: "1px solid rgba(0,0,0,0.08)" }, "data-testid": "agency-sad-mrn-comparison" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-2)", marginBottom: 3 } }, "MRN Comparison"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: sadDecision.mrn_match === false ? "var(--badge-red-text, #c0392b)" : "var(--text-2)", fontWeight: sadDecision.mrn_match === false ? 700 : 400 }, "data-testid": "agency-sad-mrn-parsed" }, "Parsed:\xA0\xA0\xA0", sadDecision.mrn_parsed), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: sadDecision.mrn_match === false ? "var(--badge-red-text, #c0392b)" : "var(--text-2)", fontWeight: sadDecision.mrn_match === false ? 700 : 400 }, "data-testid": "agency-sad-mrn-declared" }, "Declared: ", sadDecision.mrn_declared), sadDecision.mrn_match === true && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-green-text)", marginTop: 2 }, "data-testid": "agency-sad-mrn-match-ok" }, "\u2713 match")));
      })());
    })(), (() => {
      const dr2 = dhlReadiness;
      const dskReceived = dr2 && dr2.dsk_docs_received;
      const missingDocs = dr2 && dr2.missing_documents || [];
      const dhlDocs = audit && audit.dhl_documents_received || {};
      return /* @__PURE__ */ React.createElement(Card, { "data-testid": "dhl-docs-received-card" }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F4C4} DHL Documents Received"), dskReceived && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "var(--badge-green-bg)", color: "var(--badge-green-text)", border: "1px solid var(--badge-green-border)", fontWeight: 700 } }, "Received")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 10 } }, "This confirms documents received from DHL before agency forwarding."), dskReceived ? /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-docs-received-status", style: { marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text)" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", minWidth: 120, display: "inline-block" } }, "Last received: "), /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "monospace" } }, (() => {
        try {
          return new Date(dskReceived).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
        } catch {
          return dskReceived;
        }
      })())), dhlDocs.source === "email_ingestor" && /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-docs-source-auto", style: { marginTop: 6, fontSize: 11, color: "var(--badge-blue-text)" } }, "\u{1F4E5} Auto-detected from email"), dhlDocs.source === "operator" && /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-docs-source-manual", style: { marginTop: 6, fontSize: 11, color: "var(--text-3)" } }, "\u{1F590} Manually registered"), missingDocs.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--badge-amber-text)", textTransform: "uppercase", marginBottom: 3 } }, "Still missing"), missingDocs.map((d) => /* @__PURE__ */ React.createElement("div", { key: d, style: { fontSize: 11, color: "var(--badge-amber-text)" } }, "\u2022 ", d)))) : /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-docs-not-received-state", style: { fontSize: 11, color: "var(--text-3)", marginBottom: 10 } }, "No DHL documents recorded yet.", missingDocs.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4 } }, "Expected: ", missingDocs.join(", "))), /* @__PURE__ */ React.createElement("details", { "data-testid": "dhl-docs-upload-tools", style: { borderTop: "1px solid var(--border-subtle)", paddingTop: 10 } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", userSelect: "none", marginBottom: 6 } }, "\u25B8 Advanced / Manual: Upload DHL documents"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement("label", { "data-testid": "dhl-docs-upload-label", style: { display: "inline-flex", alignItems: "center", gap: 8, padding: "7px 14px", borderRadius: 6, border: "1px solid var(--badge-neutral-border)", cursor: dhlDocsBusy ? "not-allowed" : "pointer", fontSize: 12, fontWeight: 600, color: dhlDocsBusy ? "var(--text-3)" : "var(--text)", background: "transparent", opacity: dhlDocsBusy ? 0.6 : 1, width: "fit-content" } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          "data-testid": "dhl-docs-file-input",
          ref: dhlDocsRef,
          type: "file",
          accept: ".pdf,.xml,.html,.htm,.jpg,.jpeg,.png",
          multiple: true,
          disabled: dhlDocsBusy,
          style: { display: "none" },
          onChange: async (e) => {
            const files = Array.from(e.target.files || []);
            if (!files.length) return;
            setDhlDocsBusy(true);
            setDhlDocsResult(null);
            setDhlDocsError("");
            try {
              const fd2 = new FormData();
              files.forEach((f) => fd2.append("files", f));
              const r = await fetch(`/api/v1/dhl-documents/${encodeURIComponent(batchId)}/upload`, {
                method: "POST",
                body: fd2,
                credentials: "include"
              });
              if (!r.ok) {
                const msg = await r.text().catch(() => `HTTP ${r.status}`);
                throw new Error(msg);
              }
              const result = await r.json();
              setDhlDocsResult(result);
              await Promise.all([load(), loadDhlReadiness(), loadBatchReadiness()]);
            } catch (ex) {
              setDhlDocsError(ex.message || "Upload failed");
            } finally {
              setDhlDocsBusy(false);
              if (dhlDocsRef.current) dhlDocsRef.current.value = "";
            }
          }
        }
      ), dhlDocsBusy ? "\u27F3 Uploading\u2026" : "\u229E Upload DHL documents"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "Accepted: .pdf, .xml, .html, .htm, .jpg, .jpeg, .png"))), dhlDocsResult && /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-docs-upload-success", style: { marginTop: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-green-text)" } }, "\u2713 ", dhlDocsResult.files_count || 0, " document(s) registered")), dhlDocsError && /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-docs-upload-error", style: { marginTop: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, color: "var(--badge-red-text)" } }, "Upload failed: ", dhlDocsError))));
    })(), (() => {
      const agencyReceived = audit && audit.agency_documents_received;
      const agencyDocs = audit && audit.agency_documents || [];
      const missingAgencyDocs = dhlReadiness && dhlReadiness.missing_documents || [];
      return /* @__PURE__ */ React.createElement(Card, { "data-testid": "agency-docs-received-card" }, /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "var(--text)" } }, "\u{1F5C2} Agency Documents Received"), agencyReceived && /* @__PURE__ */ React.createElement("span", { "data-testid": "agency-docs-received-badge", style: { fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "var(--badge-green-bg)", color: "var(--badge-green-text)", border: "1px solid var(--badge-green-border)", fontWeight: 700 } }, "Received")), /* @__PURE__ */ React.createElement("div", { "data-testid": "agency-docs-description", style: { fontSize: 11, color: "var(--text-3)", marginBottom: 10 } }, "Upload SAD/PZC or agency documents received from the customs agency."), agencyDocs.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "agency-docs-file-list", style: { marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", marginBottom: 4 } }, "Received documents"), agencyDocs.map((d, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--badge-green-text)" } }, "\u2713"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text)", fontFamily: "monospace" } }, d.name || d.path || "\u2014"), d.type && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "(", d.type, ")")))), missingAgencyDocs.length > 0 && !agencyReceived && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "var(--badge-amber-text)", textTransform: "uppercase", marginBottom: 3 } }, "Expected from agency"), missingAgencyDocs.map((d) => /* @__PURE__ */ React.createElement("div", { key: d, style: { fontSize: 11, color: "var(--badge-amber-text)" } }, "\u2022 ", d))), /* @__PURE__ */ React.createElement("details", { "data-testid": "agency-docs-upload-tools", style: { borderTop: "1px solid var(--border-subtle)", paddingTop: 10 } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", userSelect: "none", marginBottom: 6 } }, "\u25B8 Advanced / Manual: Upload agency documents"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, /* @__PURE__ */ React.createElement("label", { "data-testid": "agency-docs-upload-label", style: { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 6, border: "1px solid var(--badge-neutral-border)", cursor: agencyDocsBusy ? "not-allowed" : "pointer", fontSize: 12, fontWeight: 600, color: agencyDocsBusy ? "var(--text-3)" : "var(--text)", background: "transparent", opacity: agencyDocsBusy ? 0.6 : 1, width: "fit-content" } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          "data-testid": "agency-docs-file-input",
          ref: agencyDocsRef,
          type: "file",
          accept: ".pdf,.xml,.html,.htm,.jpg,.jpeg,.png",
          multiple: true,
          disabled: agencyDocsBusy,
          style: { display: "none" },
          onChange: async (e) => {
            const files = Array.from(e.target.files || []);
            if (!files.length) return;
            setAgencyDocsBusy(true);
            setAgencyDocsResult(null);
            setAgencyDocsError("");
            try {
              const fd2 = new FormData();
              files.forEach((f) => fd2.append("files", f));
              const r = await fetch(`/api/v1/agency-documents/${encodeURIComponent(batchId)}/upload`, {
                method: "POST",
                body: fd2,
                credentials: "include"
              });
              if (!r.ok) {
                const msg = await r.text().catch(() => `HTTP ${r.status}`);
                throw new Error(msg);
              }
              const result = await r.json();
              setAgencyDocsResult(result);
              await loadDhlReadiness();
              await loadBatchReadiness();
            } catch (ex) {
              setAgencyDocsError(ex.message || "Upload failed");
            } finally {
              setAgencyDocsBusy(false);
              if (agencyDocsRef.current) agencyDocsRef.current.value = "";
            }
          }
        }
      ), agencyDocsBusy ? "\u27F3 Uploading\u2026" : "\u229E Upload agency documents"), /* @__PURE__ */ React.createElement("div", { "data-testid": "agency-docs-accepted-extensions", style: { fontSize: 10, color: "var(--text-3)" } }, "Accepted: .pdf, .xml, .html, .htm, .jpg, .jpeg, .png"))), agencyDocsResult && /* @__PURE__ */ React.createElement("div", { "data-testid": "agency-docs-success", style: { marginTop: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-green-bg)", border: "1px solid var(--badge-green-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--badge-green-text)", marginBottom: 2 } }, "\u2713 ", agencyDocsResult.files_total || 0, " document(s) registered"), (agencyDocsResult.skipped || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", marginTop: 2 } }, agencyDocsResult.skipped.length, " skipped \u2014 check file types")), agencyDocsError && /* @__PURE__ */ React.createElement("div", { "data-testid": "agency-docs-error", style: { marginTop: 10, padding: "8px 10px", borderRadius: 6, background: "var(--badge-red-bg)", border: "1px solid var(--badge-red-border)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, color: "var(--badge-red-text)" } }, "Upload failed: ", agencyDocsError))));
    })());
  })()), createConfirm && (() => {
    const d = createConfirm.doc || {};
    const lines = d.rows || [];
    const total = d.total_value;
    const ccy = reservationPreview && reservationPreview.currency || (lines[0] || {}).currency || "USD";
    return /* @__PURE__ */ React.createElement(Modal, { title: "Confirm wFirma Reservation", onClose: () => !createBusy && setCreateConfirm(null) }, /* @__PURE__ */ React.createElement("div", { "data-testid": "wfirma-confirm-modal" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2)", marginBottom: 12, lineHeight: 1.5 } }, "You are about to submit ", /* @__PURE__ */ React.createElement("b", null, "one"), " reservation to wFirma. This action calls the wFirma API and reserves stock against this client's order."), /* @__PURE__ */ React.createElement("div", { style: { background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: 6, padding: "10px 12px", marginBottom: 14, fontSize: 12, lineHeight: 1.6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Client:"), " ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, createConfirm.client_name)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Document:"), " ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, d.sales_doc_no || "\u2014")), d.client_ref && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Ref:"), " ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, d.client_ref)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Lines:"), " ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, lines.length)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Total value:"), " ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, total != null ? Number(total).toLocaleString("pl-PL", { minimumFractionDigits: 2 }) + " " + ccy : "\u2014"))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 12 } }, "The system will re-run the live wFirma diagnostic before submission. If anything has changed since the preview, the request will be blocked."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, justifyContent: "flex-end" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "ghost", disabled: createBusy, onClick: () => setCreateConfirm(null) }, "Cancel"), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "default",
        disabled: createBusy,
        "data-testid": "wfirma-confirm-submit-btn",
        onClick: () => submitReservation(createConfirm.client_name)
      },
      createBusy ? "Submitting\u2026" : "Confirm & Create"
    ))));
  })(), addDocOpen && /* @__PURE__ */ React.createElement(
    AddDocumentModal,
    {
      batchId,
      onClose: () => setAddDocOpen(false),
      onUploaded: (info) => {
        refreshAll("add_document");
      }
    }
  ));
}
function StatusChip({ value, testId }) {
  const v = value == null || value === "" ? "n/a" : String(value);
  const def = STATUS_HINT_MAP[v] || { kind: "neutral", label: v };
  const palette = {
    ok: { bg: "var(--badge-green-bg)", text: "var(--badge-green-text)", border: "var(--badge-green-border)" },
    warn: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
    info: { bg: "var(--badge-blue-bg)", text: "var(--badge-blue-text)", border: "var(--badge-blue-border)" },
    err: { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)", border: "var(--badge-red-border)" },
    neutral: { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--border)" }
  };
  const c = palette[def.kind] || palette.neutral;
  return /* @__PURE__ */ React.createElement(
    "span",
    {
      "data-testid": testId,
      style: { display: "inline-block", padding: "1px 6px", background: c.bg, color: c.text, border: `1px solid ${c.border}`, borderRadius: 4, fontSize: 10, fontWeight: 700, whiteSpace: "nowrap" }
    },
    def.label
  );
}
function ShipmentsTable({ batches, onViewShipment, filterFn, emptyMsg }) {
  const rows = filterFn ? batches.filter(filterFn) : batches;
  if (!rows.length) return /* @__PURE__ */ React.createElement("div", { style: { padding: "40px 0", textAlign: "center", color: "var(--text-3)", fontSize: 13 } }, emptyMsg || "No shipments");
  return /* @__PURE__ */ React.createElement(Card, { style: { overflow: "hidden", marginTop: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 }, "data-testid": "shipments-table" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--bg-subtle)" } }, ["AWB / Tracking", "Carrier", "Warehouse", "Sales", "wFirma", "DHL", "Overall", "Net", "Gross", "Duty A00", "Actions"].map((h) => /* @__PURE__ */ React.createElement("th", { key: h, style: { padding: "10px 12px", textAlign: "left", fontSize: 10, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap" } }, h)))), /* @__PURE__ */ React.createElement("tbody", null, rows.map((row) => /* @__PURE__ */ React.createElement(
    "tr",
    {
      key: row.id,
      style: { borderBottom: "1px solid var(--border-subtle)" },
      "data-testid": "shipments-row",
      onMouseEnter: (e) => e.currentTarget.style.background = "var(--row-hover)",
      onMouseLeave: (e) => e.currentTarget.style.background = "transparent"
    },
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" } }, /* @__PURE__ */ React.createElement("button", { onClick: () => onViewShipment(row), style: { background: "none", border: "none", cursor: "pointer", color: "var(--badge-blue-text)", fontSize: 12, fontWeight: 600, fontFamily: "monospace", textDecoration: "underline", textDecorationStyle: "dotted" } }, row.awb)),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" } }, /* @__PURE__ */ React.createElement("span", { style: { display: "inline-block", padding: "1px 6px", background: row.carrier === "DHL" ? "var(--badge-blue-bg)" : "var(--badge-neutral-bg)", borderRadius: 4, fontSize: 10, fontWeight: 700, color: row.carrier === "DHL" ? "var(--badge-blue-text)" : "var(--badge-neutral-text)" } }, row.carrier)),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" } }, /* @__PURE__ */ React.createElement(StatusChip, { value: row.warehouseHint, testId: "shipments-cell-warehouse" })),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" } }, /* @__PURE__ */ React.createElement(StatusChip, { value: row.salesHint, testId: "shipments-cell-sales" })),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" } }, /* @__PURE__ */ React.createElement(StatusChip, { value: row.wfirmaHint, testId: "shipments-cell-wfirma" })),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" }, "data-testid": "shipments-cell-dhl" }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-2)", whiteSpace: "nowrap" } }, row.dhlStatus || "Not checked")),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" }, "data-testid": "shipments-cell-overall" }, /* @__PURE__ */ React.createElement(Badge, { status: row.overall, small: true, title: row.overall === "Action Required" && row.action_reason ? row.action_reason : void 0 })),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px", color: "var(--text)", fontWeight: 500, textAlign: "right" } }, row.net),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px", color: "var(--text)", fontWeight: 500, textAlign: "right" } }, row.gross),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px", color: "var(--accent)", fontWeight: 700, textAlign: "right" } }, row.duty),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "10px 12px" } }, /* @__PURE__ */ React.createElement(Btn, { small: true, variant: "outline", onClick: () => onViewShipment(row) }, "View"))
  ))))));
}
function StatRow({ label, value, accent, muted }) {
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "4px 0", borderBottom: "1px solid var(--border-subtle)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, color: muted ? "var(--text-3)" : "var(--text-2)" } }, label), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, fontWeight: 600, color: accent ? "var(--accent)" : "var(--text)", fontVariantNumeric: "tabular-nums" } }, value));
}
const ACTIONS_V2_SECTION_ORDER = [
  { key: "shipment", label: "Shipment", icon: "\u{1F69A}" },
  { key: "dhl_clearance", label: "DHL Clearance", icon: "\u2708" },
  { key: "customs_documents", label: "Customs Documents", icon: "\u229F" },
  { key: "pz_accounting", label: "PZ / Accounting", icon: "\u229E" },
  { key: "wfirma", label: "wFirma Export", icon: "\u2197" },
  { key: "cowork", label: "Agency / Cowork", icon: "\u{1F4E8}" },
  { key: "system", label: "System", icon: "\u2699" }
];
const ACTIONS_V2_STYLE = {
  primary: { bg: "var(--accent)", fg: "#fff", border: "var(--accent-border)" },
  secondary: { bg: "transparent", fg: "var(--text)", border: "var(--border)" },
  danger: { bg: "transparent", fg: "var(--badge-red-text)", border: "var(--badge-red-border)" },
  info: { bg: "var(--badge-blue-bg)", fg: "var(--badge-blue-text)", border: "var(--badge-blue-border)" }
};
const ACTIONS_V2_STATE_BADGE = {
  ready: { color: "var(--badge-green-text)", bg: "var(--badge-green-bg)", label: "ready" },
  done: { color: "var(--badge-blue-text)", bg: "var(--badge-blue-bg)", label: "done" },
  blocked: { color: "var(--badge-red-text)", bg: "var(--badge-red-bg)", label: "blocked" },
  pending: { color: "var(--badge-amber-text)", bg: "var(--badge-amber-bg)", label: "pending" },
  failed: { color: "var(--badge-red-text)", bg: "var(--badge-red-bg)", label: "failed" }
};
function ActionsV2Button({ action, onClick }) {
  const style = ACTIONS_V2_STYLE[action.style] || ACTIONS_V2_STYLE.secondary;
  const enabled = action.enabled;
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 4, minWidth: 0 } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      disabled: !enabled,
      onClick: () => enabled && onClick(action),
      title: action.reason || "",
      style: {
        padding: "8px 14px",
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: "inherit",
        cursor: enabled ? "pointer" : "not-allowed",
        opacity: enabled ? 1 : 0.55,
        background: style.bg,
        color: style.fg,
        border: "1px solid " + style.border,
        textAlign: "left",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis"
      }
    },
    action.label
  ), !enabled && action.reason && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", fontStyle: "italic", lineHeight: 1.3, maxWidth: 240 } }, action.reason));
}
function ActionsV2Section({ sectionKey, label, icon, actions, onActionClick }) {
  if (!actions || actions.length === 0) {
    return /* @__PURE__ */ React.createElement("div", { style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 18px", opacity: 0.55 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14 } }, icon), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "var(--text-2)", letterSpacing: "0.04em", textTransform: "uppercase" } }, label)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", fontStyle: "italic" } }, "No actions in this section."));
  }
  return /* @__PURE__ */ React.createElement("div", { style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 12 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14 } }, icon), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "var(--text)", letterSpacing: "0.04em", textTransform: "uppercase" } }, label), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", marginLeft: "auto" } }, actions.filter((a) => a.enabled).length, "/", actions.length, " enabled")), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 } }, actions.map((a) => /* @__PURE__ */ React.createElement(ActionsV2Button, { key: a.id, action: a, onClick: onActionClick }))));
}
function ActionsV2Panel({ batchId }) {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState({});
  const reload = React.useCallback(async () => {
    try {
      const res = await fetch(`/dashboard/batches/${encodeURIComponent(batchId)}/actions`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const j = await res.json();
      setData(j);
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
  }, [batchId]);
  React.useEffect(() => {
    reload();
  }, [reload]);
  const handleClick = async (action) => {
    if (action.requires_confirmation) {
      if (!window.confirm(`Confirm action: ${action.label}

${action.reason || ""}

${action.method} ${action.endpoint}`)) return;
    }
    setBusy((p) => ({ ...p, [action.id]: true }));
    try {
      if (action.method === "GET" && action.endpoint && !action.endpoint.startsWith("/dashboard/batches/")) {
        window.open(action.endpoint, "_blank", "noopener");
      } else {
        const hasBody = action.method !== "GET";
        const res = await fetch(action.endpoint, {
          method: action.method,
          credentials: "include",
          headers: hasBody ? { "Content-Type": "application/json" } : {},
          body: hasBody ? JSON.stringify(action.body || {}) : void 0
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const ct = res.headers.get("content-type") || "";
        if (ct.includes("json")) await res.json();
      }
      await reload();
    } catch (e) {
      window.alert(`Action failed: ${action.label}
${e.message}`);
    } finally {
      setBusy((p) => ({ ...p, [action.id]: false }));
    }
  };
  if (err) return /* @__PURE__ */ React.createElement("div", { style: { background: "var(--badge-red-bg)", color: "var(--badge-red-text)", border: "1px solid var(--badge-red-border)", borderRadius: 10, padding: 14, fontSize: 12 } }, "Actions V2 failed to load: ", err);
  if (!data) return /* @__PURE__ */ React.createElement("div", { style: { padding: 14, fontSize: 12, color: "var(--text-3)" } }, "Loading actions\u2026");
  const ns = data.normalized_state || {};
  const broken = data.broken_routes || [];
  return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement("div", { style: { background: "var(--accent-subtle)", border: "1px solid var(--accent-border)", borderRadius: 10, padding: "12px 16px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: "var(--accent)", letterSpacing: "0.06em", textTransform: "uppercase" } }, "Actions V2 (registry)"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-2)" } }, "pz_generated=", String(ns.pz_generated), " \xB7 wfirma_ready=", String(ns.wfirma_ready), " \xB7 agency_path=", String(ns.clearance_path === "external_agency_clearance")), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: broken.length ? "var(--badge-red-text)" : "var(--badge-green-text)", marginLeft: "auto" } }, broken.length ? `\u26A0 ${broken.length} broken endpoint(s)` : "\u2713 all endpoints validated")), ACTIONS_V2_SECTION_ORDER.map((sec) => /* @__PURE__ */ React.createElement(
    ActionsV2Section,
    {
      key: sec.key,
      sectionKey: sec.key,
      label: sec.label,
      icon: sec.icon,
      actions: (data.sections || {})[sec.key] || [],
      onActionClick: handleClick
    }
  )), broken.length > 0 && /* @__PURE__ */ React.createElement("details", { style: { background: "var(--badge-red-bg)", color: "var(--badge-red-text)", border: "1px solid var(--badge-red-border)", borderRadius: 10, padding: "10px 14px" } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", fontSize: 12, fontWeight: 600 } }, broken.length, " broken endpoint(s) \u2014 click to expand"), /* @__PURE__ */ React.createElement("ul", { style: { marginTop: 8, fontSize: 11, fontFamily: "monospace", listStyle: "none", padding: 0 } }, broken.map((b, i) => /* @__PURE__ */ React.createElement("li", { key: i, style: { padding: "4px 0" } }, b.action_id, ": ", b.method, " ", b.endpoint, " \u2014 ", b.reason)))));
}
const EE_STAGE_ICON = {
  dhl_request: "\u2709",
  our_dhl_reply: "\u2197",
  dhl_documents: "\u{1F4E6}",
  agency_forward: "\u27A1",
  agency_sad_reply: "\u229F",
  pz_generated: "\u229E",
  dhl_invoice: "$",
  agency_invoice: "$",
  shipment_closed: "\u2713"
};
const EE_STATUS_STYLE = {
  missing: { color: "var(--text-3)", bg: "transparent", label: "missing" },
  queued: { color: "var(--badge-amber-text)", bg: "var(--badge-amber-bg)", label: "queued" },
  received: { color: "var(--badge-blue-text)", bg: "var(--badge-blue-bg)", label: "received" },
  sent: { color: "var(--badge-green-text)", bg: "var(--badge-green-bg)", label: "sent" },
  processed: { color: "var(--accent)", bg: "var(--accent-subtle)", label: "processed" }
};
const BADGE_TONE = {
  ok: { bg: "var(--badge-green-bg)", color: "var(--badge-green-text)", border: "var(--badge-green-border)" },
  warn: { bg: "var(--badge-amber-bg)", color: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
  info: { bg: "var(--badge-blue-bg)", color: "var(--badge-blue-text)", border: "var(--badge-blue-border)" }
};
function DhlActionCard({ batchId, onAfterAction }) {
  const [state, setState] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState(null);
  const reload = React.useCallback(async () => {
    try {
      const res = await fetch(`/dashboard/batches/${encodeURIComponent(batchId)}/dhl-action-state`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setState(await res.json());
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
  }, [batchId]);
  React.useEffect(() => {
    reload();
  }, [reload]);
  const runAction = async (action) => {
    if (!action || action.disabled) return;
    let body = action.body || {};
    if (action.id === "approve_proactive_proposal") {
      const who = window.prompt("Approver (must differ from requester):", "");
      if (!who) return;
      body = { approved_by: who };
    } else if (action.id === "proactive_dispatch_request") {
      const op = window.prompt("Your operator id:", "");
      if (!op) return;
      body = { operator_id: op };
    }
    setBusy(action.id);
    try {
      const res = await fetch(action.endpoint, {
        method: action.method || "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = j.detail?.error || j.detail?.message || j.detail || j.error || `HTTP ${res.status}`;
        window.alert(`Action failed: ${typeof msg === "string" ? msg : JSON.stringify(msg)}`);
      } else {
        const ok = j.ok !== false;
        const summary = j.proposal_id ? `proposal_id=${j.proposal_id}` : j.email_id ? `email_id=${j.email_id}` : "OK";
        window.alert(`${action.label}: ${ok ? "OK" : "FAILED"} \u2014 ${summary}`);
      }
      await reload();
      if (typeof onAfterAction === "function") await onAfterAction();
    } finally {
      setBusy(null);
    }
  };
  if (err) return /* @__PURE__ */ React.createElement("div", { style: { padding: 10, fontSize: 11, color: "var(--badge-red-text)", background: "var(--badge-red-bg)", borderRadius: 6, border: "1px solid var(--badge-red-border)" } }, "DHL action state load failed: ", err);
  if (!state) return null;
  const a = state.primary_action;
  const sec = state.secondary_actions || [];
  const badges = state.badges || [];
  const infos = state.info_messages || [];
  return /* @__PURE__ */ React.createElement("div", { "data-testid": "dhl-action-card", style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 18px", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14 } }, "\u{1F3AF}"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "var(--text)", letterSpacing: "0.04em", textTransform: "uppercase" } }, "Next DHL action")), badges.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 } }, badges.map((b, i) => {
    const t = BADGE_TONE[b.tone] || BADGE_TONE.info;
    return /* @__PURE__ */ React.createElement("span", { key: i, style: { padding: "3px 9px", fontSize: 10, fontWeight: 600, borderRadius: 4, background: t.bg, color: t.color, border: `1px solid ${t.border}` } }, b.label);
  })), a ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, marginBottom: sec.length > 0 || infos.length > 0 ? 10 : 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      "data-action-id": a.id,
      disabled: a.disabled || busy === a.id,
      onClick: () => runAction(a),
      style: {
        padding: "8px 16px",
        fontSize: 12,
        fontWeight: 700,
        fontFamily: "inherit",
        borderRadius: 6,
        cursor: a.disabled || busy === a.id ? "not-allowed" : "pointer",
        border: "1px solid var(--accent-border)",
        background: a.disabled ? "var(--bg-subtle)" : "var(--accent-subtle)",
        color: a.disabled ? "var(--text-3)" : "var(--accent)",
        opacity: a.disabled || busy === a.id ? 0.6 : 1
      }
    },
    busy === a.id ? "\u27F3\u2026" : `\u25B6 ${a.label}`
  ), a.proposal_status && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "proposal: ", a.proposal_status, a.proposal_id ? ` (${String(a.proposal_id).slice(0, 8)}\u2026)` : "")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", lineHeight: 1.4 } }, a.reason), a.disabled && a.disabled_reason && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--badge-red-text)" } }, "\u26A0 ", a.disabled_reason)) : /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2)", marginBottom: infos.length > 0 ? 10 : 0 } }, state.state_summary), sec.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, marginBottom: infos.length > 0 ? 10 : 0, borderTop: "1px solid var(--border-subtle)", paddingTop: 8 } }, sec.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", flexDirection: "column", gap: 4 } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      "data-action-id": s.id,
      disabled: s.disabled || busy === s.id,
      onClick: () => runAction(s),
      style: {
        alignSelf: "flex-start",
        padding: "6px 14px",
        fontSize: 11,
        fontWeight: 600,
        fontFamily: "inherit",
        borderRadius: 5,
        cursor: s.disabled || busy === s.id ? "not-allowed" : "pointer",
        border: "1px solid var(--border)",
        background: "transparent",
        color: "var(--text)",
        opacity: s.disabled || busy === s.id ? 0.6 : 1
      }
    },
    busy === s.id ? "\u27F3\u2026" : s.label
  ), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, s.reason)))), infos.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { borderTop: "1px solid var(--border-subtle)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 4 } }, infos.map((msg, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 11, color: "var(--text-3)", fontStyle: "italic" } }, "\xB7 ", msg))));
}
function EmailEvidenceTimeline({ batchId }) {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState(null);
  const reload = React.useCallback(async () => {
    try {
      const res = await fetch(`/dashboard/batches/${encodeURIComponent(batchId)}/email-evidence`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
  }, [batchId]);
  React.useEffect(() => {
    reload();
  }, [reload]);
  const doRescan = async () => {
    setBusy("rescan");
    try {
      const res = await fetch(`/dashboard/batches/${encodeURIComponent(batchId)}/email-evidence/rescan`, { method: "POST", credentials: "include" });
      const j = await res.json();
      const scanned = j.total_scanned ?? j.scanned ?? 0;
      const ingested = j.ingested ?? 0;
      const query = j.query_used ? ` (${j.query_used})` : "";
      window.alert(`Rescan ${j.ok ? "OK" : "FAILED"}: scanned=${scanned}, ingested=${ingested}${query}${j.error ? ", err=" + j.error : ""}`);
      await reload();
    } finally {
      setBusy(null);
    }
  };
  const doProcess = async () => {
    setBusy("process");
    try {
      const res = await fetch(`/dashboard/batches/${encodeURIComponent(batchId)}/email-evidence/process`, { method: "POST", credentials: "include" });
      const j = await res.json();
      const acted = (j.result?.actions || []).length;
      window.alert(`Process ${j.ok ? "OK" : "FAILED"}: actions=${acted}, skipped=${j.result?.skipped ?? 0}`);
      await reload();
    } finally {
      setBusy(null);
    }
  };
  if (err) return /* @__PURE__ */ React.createElement("div", { style: { background: "var(--badge-red-bg)", color: "var(--badge-red-text)", border: "1px solid var(--badge-red-border)", borderRadius: 10, padding: 14, fontSize: 12 } }, "Email evidence load failed: ", err);
  if (!data) return null;
  if (!data.awb) return /* @__PURE__ */ React.createElement("div", { style: { padding: 12, fontSize: 12, color: "var(--text-3)", fontStyle: "italic" } }, "Email evidence not available \u2014 batch has no AWB.");
  const stages = data.stages || [];
  const messages = data.messages || [];
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(DhlActionCard, { batchId, onAfterAction: reload }), /* @__PURE__ */ React.createElement("div", { style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 18px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 12 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14 } }, "\u{1F4E7}"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "var(--text)", letterSpacing: "0.04em", textTransform: "uppercase" } }, "Email Evidence Timeline"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", marginLeft: 4 } }, "AWB ", data.awb), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "\xB7 ", messages.length, " messages stored"), data.last_scan_at && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)" } }, "\xB7 last scan ", data.last_scan_at), /* @__PURE__ */ React.createElement("div", { style: { marginLeft: "auto", display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement("button", { onClick: doRescan, disabled: busy === "rescan", style: { padding: "5px 12px", fontSize: 11, fontWeight: 600, fontFamily: "inherit", borderRadius: 5, border: "1px solid var(--border)", background: "transparent", color: "var(--text-2)", cursor: "pointer" } }, busy === "rescan" ? "\u27F3\u2026" : "\u21BB Rescan"), /* @__PURE__ */ React.createElement("button", { onClick: doProcess, disabled: busy === "process", style: { padding: "5px 12px", fontSize: 11, fontWeight: 600, fontFamily: "inherit", borderRadius: 5, border: "1px solid var(--accent-border)", background: "var(--accent-subtle)", color: "var(--accent)", cursor: "pointer" } }, busy === "process" ? "\u27F3\u2026" : "\u25B6 Process"))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 6, marginBottom: 14 } }, stages.map((st, i) => {
    const sty = EE_STATUS_STYLE[st.status] || EE_STATUS_STYLE.missing;
    return /* @__PURE__ */ React.createElement("div", { key: st.key, style: { padding: "8px 10px", borderRadius: 6, border: "1px solid var(--border)", background: sty.bg } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, color: "var(--text-3)" } }, i + 1), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13 } }, EE_STAGE_ICON[st.key] || "\xB7"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "var(--text)", flex: 1 } }, st.label)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: sty.color, textTransform: "uppercase", letterSpacing: "0.04em" } }, sty.label), st.timestamp && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "var(--text-3)", marginTop: 2 } }, st.timestamp), st.attachment_count > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "var(--text-3)", marginTop: 1 } }, "\u{1F4CE} ", st.attachment_count));
  })), messages.length > 0 && /* @__PURE__ */ React.createElement("details", { style: { borderTop: "1px solid var(--border)", paddingTop: 10 } }, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", fontSize: 11, fontWeight: 600, color: "var(--text-2)" } }, messages.length, " message(s) \u2014 click to expand"), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, fontSize: 11, fontFamily: "monospace", maxHeight: 240, overflowY: "auto" } }, messages.sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || "")).map((m, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "4px 6px", borderBottom: "1px solid var(--border-subtle)", display: "grid", gridTemplateColumns: "110px 90px 70px 1fr 50px", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 10 } }, m.timestamp || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-2)", fontSize: 10 } }, m.event_type || "other"), /* @__PURE__ */ React.createElement("span", { style: { color: m.direction === "outgoing" ? "var(--badge-green-text)" : "var(--badge-blue-text)", fontSize: 10, fontWeight: 600 } }, m.direction || ""), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text)", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: m.subject }, m.subject || ""), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 10, textAlign: "right" } }, m.attachment_count > 0 ? `\u{1F4CE}${m.attachment_count}` : "")))))));
}
function OperatorWorkflowCard({ batchId, onToast }) {
  const [proforma, setProforma] = React.useState(null);
  const [zc429, setZc429] = React.useState(null);
  const [cnhsn, setCnhsn] = React.useState(null);
  const [preview, setPreview] = React.useState(null);
  const [caps, setCaps] = React.useState(null);
  const [batchReady, setBatchReady] = React.useState(null);
  const [batchDet, setBatchDet] = React.useState(null);
  const [cm, setCm] = React.useState([]);
  const [cmEdit, setCmEdit] = React.useState(null);
  const [cmSaving, setCmSaving] = React.useState(false);
  const [cmSavedMsg, setCmSavedMsg] = React.useState(null);
  const [setupDetail, setSetupDetail] = React.useState(null);
  const [setupDetailLoading, setSetupDetailLoading] = React.useState(false);
  const [setupDetailErr, setSetupDetailErr] = React.useState("");
  const [setupProductPreview, setSetupProductPreview] = React.useState(null);
  const [setupProductPreviewLoading, setSetupProductPreviewLoading] = React.useState(false);
  const [setupProductPreviewErr, setSetupProductPreviewErr] = React.useState("");
  const [pendingList, setPendingList] = React.useState(null);
  const [pendingListLoading, setPendingListLoading] = React.useState(false);
  const [pendingListErr, setPendingListErr] = React.useState("");
  const [pendingModalOpen, setPendingModalOpen] = React.useState(false);
  const [pendingActionBusy, setPendingActionBusy] = React.useState({});
  const [pendingActionMsg, setPendingActionMsg] = React.useState({});
  const [pendingCompare, setPendingCompare] = React.useState({});
  const [pendingCompareBusy, setPendingCompareBusy] = React.useState({});
  const [setupCustomerResolve, setSetupCustomerResolve] = React.useState(null);
  const [setupCustomerResolveLoading, setSetupCustomerResolveLoading] = React.useState(false);
  const [setupCustomerResolveErr, setSetupCustomerResolveErr] = React.useState("");
  const [expanded, setExpanded] = React.useState({
    evidence: true,
    classification: false,
    products: false,
    customers: false,
    warehouse: false,
    preview: true,
    execute: true
  });
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const refresh = React.useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError("");
    const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
    const opts = { headers: hdrs, credentials: "include" };
    const safe = async (url) => {
      try {
        const r = await fetch(url, opts);
        return r.ok ? await r.json() : null;
      } catch {
        return null;
      }
    };
    const [pf, zc, cn, pv, cp, br, bd, cmResp] = await Promise.all([
      safe(`/dashboard/batches/${encodeURIComponent(batchId)}/proforma-readiness`),
      safe(`/dashboard/batches/${encodeURIComponent(batchId)}/zc429-lineage`),
      safe(`/dashboard/batches/${encodeURIComponent(batchId)}/cn-hsn-classification`),
      safe(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_preview`),
      safe(`/api/v1/wfirma/capabilities`),
      safe(`/api/v1/batch/${encodeURIComponent(batchId)}/readiness`),
      safe(`/dashboard/batches/${encodeURIComponent(batchId)}`),
      safe("/api/v1/customer-master/")
    ]);
    setProforma(pf);
    setZc429(zc);
    setCnhsn(cn);
    setPreview(pv);
    setCaps(cp);
    setBatchReady(br);
    setBatchDet(bd);
    setCm(cmResp && (cmResp.customers || []) || []);
    if (!pf && !zc && !cn) setError("All read-only endpoints failed");
    setLoading(false);
  }, [batchId]);
  const saveCmFields = React.useCallback(async (contractorId, fields) => {
    setCmSaving(true);
    setCmSavedMsg(null);
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const r = await fetch(`/api/v1/customer-master/${encodeURIComponent(contractorId)}`, {
        method: "PUT",
        headers: { ...hdrs, "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(fields)
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        setCmSavedMsg({ contractorId, msg: "Saved \u2713" });
        setCmEdit(null);
        refresh();
      } else {
        setCmSavedMsg({ contractorId, msg: j.detail || "Save failed" });
      }
    } catch {
      setCmSavedMsg({ contractorId, msg: "Network error" });
    }
    setCmSaving(false);
  }, [refresh]);
  const refreshSetupDetail = React.useCallback(async () => {
    setSetupDetailLoading(true);
    setSetupDetailErr("");
    try {
      const d = await apiFetch(
        `/api/v1/wfirma/shipment/${encodeURIComponent(batchId)}/setup-detail`
      );
      setSetupDetail(d);
    } catch (e) {
      setSetupDetailErr(e && e.message || "setup-detail fetch failed");
      setSetupDetail(null);
    }
    setSetupDetailLoading(false);
  }, [batchId]);
  const handleProductPreview = React.useCallback(async () => {
    setSetupProductPreviewLoading(true);
    setSetupProductPreviewErr("");
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const operator = (localStorage.getItem("pz_operator_name") || "").trim();
      const r = await fetch(
        `/api/v1/wfirma/goods/auto-register-preview/${encodeURIComponent(batchId)}`,
        {
          method: "POST",
          headers: { ...hdrs, "X-Operator": operator || "operator" },
          credentials: "include"
        }
      );
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        setSetupProductPreview(j);
      } else {
        setSetupProductPreviewErr(j && (j.detail || j.error) || `HTTP ${r.status}`);
        setSetupProductPreview(null);
      }
    } catch (e) {
      setSetupProductPreviewErr(e && e.message || "product preview failed");
      setSetupProductPreview(null);
    }
    setSetupProductPreviewLoading(false);
    refreshSetupDetail();
  }, [batchId, refreshSetupDetail]);
  const refreshPendingList = React.useCallback(async () => {
    setPendingListLoading(true);
    setPendingListErr("");
    try {
      const d = await apiFetch("/api/v1/wfirma/products?sync_status=pending_adoption");
      setPendingList(d && d.products || []);
    } catch (e) {
      setPendingListErr(e && e.message || "pending list fetch failed");
      setPendingList(null);
    }
    setPendingListLoading(false);
  }, []);
  const fetchPendingCompare = React.useCallback(async (productCode) => {
    setPendingCompareBusy((prev) => ({ ...prev, [productCode]: true }));
    try {
      const d = await apiFetch(
        `/api/v1/wfirma/goods/search-and-compare?product_code=${encodeURIComponent(productCode)}`
      );
      setPendingCompare((prev) => ({ ...prev, [productCode]: d && d.comparison || null }));
    } catch (e) {
      setPendingCompare((prev) => ({
        ...prev,
        [productCode]: { error: e && e.message || "compare failed" }
      }));
    }
    setPendingCompareBusy((prev) => ({ ...prev, [productCode]: false }));
  }, []);
  const _postPendingAction = React.useCallback(async (productCode, endpoint, actionLabel) => {
    setPendingActionBusy((prev) => ({ ...prev, [productCode]: actionLabel }));
    setPendingActionMsg((prev) => ({ ...prev, [productCode]: "" }));
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const operator = (localStorage.getItem("pz_operator_name") || "").trim();
      const r = await fetch(
        `/api/v1/wfirma/goods/${endpoint}/${encodeURIComponent(productCode)}`,
        {
          method: "POST",
          headers: { ...hdrs, "X-Operator": operator || "operator" },
          credentials: "include"
        }
      );
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        setPendingActionMsg((prev) => ({ ...prev, [productCode]: `${actionLabel} succeeded` }));
        await refreshPendingList();
      } else {
        const detail = j && (j.detail || j.error);
        const msg = typeof detail === "string" ? detail : detail && detail.error ? detail.error : `HTTP ${r.status}`;
        setPendingActionMsg((prev) => ({ ...prev, [productCode]: `${actionLabel} failed: ${msg}` }));
      }
    } catch (e) {
      setPendingActionMsg((prev) => ({ ...prev, [productCode]: `${actionLabel} error: ${e.message || e}` }));
    }
    setPendingActionBusy((prev) => ({ ...prev, [productCode]: "" }));
  }, [refreshPendingList]);
  const handlePendingAdopt = React.useCallback((pc) => _postPendingAction(pc, "adopt", "Adopt as-is"), [_postPendingAction]);
  const handlePendingUpdateAndAdopt = React.useCallback((pc) => _postPendingAction(pc, "update-and-adopt", "Update then adopt"), [_postPendingAction]);
  const handlePendingCreateAndAdopt = React.useCallback((pc) => _postPendingAction(pc, "create-and-adopt", "Create new"), [_postPendingAction]);
  const openPendingModal = React.useCallback(() => {
    setPendingModalOpen(true);
    refreshPendingList();
  }, [refreshPendingList]);
  const closePendingModal = React.useCallback(() => {
    setPendingModalOpen(false);
  }, []);
  const handleCustomerResolve = React.useCallback(async () => {
    setSetupCustomerResolveLoading(true);
    setSetupCustomerResolveErr("");
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const operator = (localStorage.getItem("pz_operator_name") || "").trim();
      const r = await fetch(
        `/api/v1/wfirma/customers/auto-resolve-preview/${encodeURIComponent(batchId)}`,
        {
          method: "POST",
          headers: { ...hdrs, "X-Operator": operator || "operator" },
          credentials: "include"
        }
      );
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        setSetupCustomerResolve(j);
      } else {
        setSetupCustomerResolveErr(j && (j.detail || j.error) || `HTTP ${r.status}`);
        setSetupCustomerResolve(null);
      }
    } catch (e) {
      setSetupCustomerResolveErr(e && e.message || "customer resolve failed");
      setSetupCustomerResolve(null);
    }
    setSetupCustomerResolveLoading(false);
    refreshSetupDetail();
  }, [batchId, refreshSetupDetail]);
  const handleSetupSaveCmFor = React.useCallback((cmRow) => {
    if (!cmRow || !cmRow.wfirma_customer_id) {
      setSetupDetailErr(
        `Cannot Save CM for "${cmRow && cmRow.client_name || ""}" \u2014 no Customer Master record yet. Use Resolve first, then Save CM.`
      );
      return;
    }
    const cid = cmRow.wfirma_customer_id;
    const cmRec = (cm || []).find((r) => r && r.bill_to_contractor_id === cid);
    if (!cmRec) {
      setSetupDetailErr(
        `Customer Master row not found for contractor ${cid}. Refreshing list\u2026`
      );
      refresh();
      return;
    }
    setCmEdit({ contractorId: cid, fields: {
      bill_to_name: cmRec.bill_to_name || "",
      bill_to_nip: cmRec.nip || cmRec.bill_to_nip || "",
      bill_to_street: cmRec.bill_to_street || "",
      bill_to_city: cmRec.bill_to_city || "",
      bill_to_postal_code: cmRec.bill_to_postal_code || "",
      bill_to_country: cmRec.bill_to_country || "",
      ship_to_name: cmRec.ship_to_name || "",
      ship_to_street: cmRec.ship_to_street || "",
      ship_to_city: cmRec.ship_to_city || "",
      ship_to_postal_code: cmRec.ship_to_postal_code || "",
      preferred_payment_method: cmRec.preferred_payment_method || "",
      payment_terms_days: cmRec.payment_terms_days != null ? String(cmRec.payment_terms_days) : "",
      default_currency: cmRec.default_currency || "",
      preferred_proforma_series_id: cmRec.preferred_proforma_series_id || "",
      preferred_invoice_series_id: cmRec.preferred_invoice_series_id || ""
    } });
    setSetupDetailErr("");
    setTimeout(() => {
      const el = document.querySelector(`[data-testid="workflow-cm-card-${cid}"]`);
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  }, [cm, refresh]);
  React.useEffect(() => {
    refresh();
    refreshSetupDetail();
  }, [refresh, refreshSetupDetail]);
  const stages = React.useMemo(() => {
    const sadPresent = !!(proforma && proforma.pz && proforma.pz.sad_received) || !!(cnhsn && cnhsn.sad_cn_code);
    const zcPresent = !!(zc429 && zc429.has_zc429);
    const evWarn = !!(zc429 && (zc429.warnings || []).length);
    const evidenceColor = sadPresent && zcPresent ? "green" : evWarn ? "red" : sadPresent ? "amber" : "amber";
    const cnLevel = cnhsn && cnhsn.result && cnhsn.result.worst_level || "";
    const cnDecided = !!(cnhsn && cnhsn.decision && cnhsn.decision.approved);
    const cnBlocked = !!(cnhsn && cnhsn.result && cnhsn.result.is_blocking) && !cnDecided;
    const classColor = cnBlocked ? "red" : cnDecided ? "green" : cnLevel === "invalid_input" || !cnhsn ? "gray" : cnLevel === "chapter_match" || cnLevel === "different_chapter" ? "amber" : "green";
    const prodMissing = proforma && proforma.products && proforma.products.missing || 0;
    const prodTotal = proforma && proforma.products && proforma.products.total || 0;
    const productsColor = prodTotal === 0 ? "gray" : prodMissing === 0 ? "green" : "amber";
    const custMissing = proforma && proforma.customers && proforma.customers.missing || 0;
    const custAmbig = proforma && proforma.customers && proforma.customers.ambiguous || 0;
    const custTotal = proforma && proforma.customers && proforma.customers.total || 0;
    const customersColor = custTotal === 0 ? "gray" : custMissing === 0 && custAmbig === 0 ? "green" : "amber";
    const wh = batchReady && batchReady.warehouse ? batchReady.warehouse : null;
    const sales = batchReady && batchReady.sales ? batchReady.sales : null;
    const whReady = !!(wh && wh.ready);
    const salesReady = !!(sales && sales.ready);
    const warehouseColor = !batchReady ? "gray" : whReady && salesReady ? "green" : "amber";
    const localPzExists = !!(batchDet && batchDet.files && batchDet.files.pdf && batchDet.files.pdf.exists);
    const previewBlockers = preview && Array.isArray(preview.blockers) ? preview.blockers : [];
    const previewErr = !!(preview && (preview.detail || previewBlockers.length > 0));
    const previewReady = !!(preview && preview.ready);
    const wouldCreate = !!(preview && preview.would_create_pz);
    const alreadyCreated = !!(preview && preview.already_created);
    const previewColor = !preview ? "gray" : alreadyCreated ? "green" : previewErr ? "amber" : previewReady ? "green" : "amber";
    const flagOn = !!(caps && (caps.create_pz_allowed || caps.wfirma_create_pz_allowed || caps.flags && (caps.flags.create_pz_allowed || caps.flags.wfirma_create_pz_allowed)));
    const blockersBefore = (cnBlocked ? 1 : 0) + (prodMissing > 0 ? 1 : 0) + (custMissing + custAmbig > 0 ? 1 : 0) + (!whReady ? 1 : 0) + (!sadPresent ? 1 : 0);
    const executeEnabled = previewReady && wouldCreate && flagOn && !alreadyCreated && blockersBefore === 0;
    const executeColor = executeEnabled ? "green" : alreadyCreated ? "green" : "amber";
    return {
      evidence: {
        color: evidenceColor,
        label: sadPresent && zcPresent ? "SAD + ZC429" : sadPresent ? "legacy SAD only" : "waiting",
        count: zc429 ? (zc429.attachments || []).length : 0,
        sadPresent,
        zcPresent
      },
      classification: {
        color: classColor,
        label: cnDecided ? "accepted" : cnBlocked ? "blocked" : cnLevel || "no data",
        count: cnBlocked ? 1 : 0,
        decided: cnDecided
      },
      products: {
        color: productsColor,
        label: `${prodTotal - prodMissing}/${prodTotal} mapped`,
        count: prodMissing,
        flagOn: !!(proforma && proforma.products && proforma.products.create_flag_on)
      },
      customers: {
        color: customersColor,
        label: `${custTotal - custMissing - custAmbig}/${custTotal} mapped`,
        count: custMissing + custAmbig,
        flagOn: !!(proforma && proforma.customers && proforma.customers.create_flag_on)
      },
      warehouse: {
        color: warehouseColor,
        label: whReady && salesReady ? "ready" : !batchReady ? "unknown" : "action needed",
        count: (!whReady ? 1 : 0) + (!salesReady ? 1 : 0),
        message: wh && wh.message || "",
        sales_message: sales && sales.message || ""
      },
      preview: {
        color: previewColor,
        label: alreadyCreated ? "wFirma PZ created" : previewReady ? "wFirma PZ preview ready" : previewErr ? "wFirma PZ preview blocked" : localPzExists ? "local PZ generated; wFirma PZ not ready" : "not ready",
        count: preview && (preview.unresolved_product_codes || []).length || 0,
        localPzExists,
        previewErr
      },
      execute: {
        color: executeColor,
        label: alreadyCreated ? "PZ created" : executeEnabled ? "ready" : "locked",
        count: 0,
        enabled: executeEnabled
      }
    };
  }, [zc429, cnhsn, proforma, preview, caps, batchReady, batchDet]);
  const STAGE_ORDER = [
    ["evidence", "Customs docs"],
    ["classification", "Classification"],
    ["products", "Products"],
    ["customers", "Customers"],
    ["warehouse", "Warehouse"],
    ["preview", "Review"],
    ["execute", "Post"]
  ];
  const card = {
    background: "var(--card,#fff)",
    border: "1px solid var(--border,#e5e7eb)",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16
  };
  const dot = (color) => ({
    width: 12,
    height: 12,
    borderRadius: 6,
    display: "inline-block",
    background: color === "green" ? "#15803d" : color === "amber" ? "#d97706" : color === "red" ? "#dc2626" : "#9ca3af"
  });
  const bar = {
    display: "flex",
    alignItems: "center",
    gap: 4,
    flexWrap: "wrap",
    marginBottom: 12
  };
  const stagePill = (s, key, label) => {
    const colorBg = s[key].color === "green" ? "#dcfce7" : s[key].color === "amber" ? "#fef3c7" : s[key].color === "red" ? "#fee2e2" : "#f3f4f6";
    const colorTx = s[key].color === "green" ? "#15803d" : s[key].color === "amber" ? "#b45309" : s[key].color === "red" ? "#991b1b" : "#374151";
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        key,
        "data-testid": `workflow-pill-${key}`,
        style: {
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 10px",
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 700,
          background: colorBg,
          color: colorTx,
          cursor: "pointer"
        },
        onClick: () => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
      },
      /* @__PURE__ */ React.createElement("span", { style: dot(s[key].color) }),
      label,
      s[key].count > 0 && /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": `workflow-pill-count-${key}`,
          style: {
            background: "#fff",
            color: colorTx,
            padding: "0 6px",
            borderRadius: 8,
            fontSize: 10
          }
        },
        s[key].count
      )
    );
  };
  const sectionShell = (key, title, body) => /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": `workflow-section-${key}`,
      style: {
        border: "1px solid var(--border,#e5e7eb)",
        borderRadius: 6,
        marginBottom: 8,
        background: "#fff"
      }
    },
    /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `workflow-section-header-${key}`,
        onClick: () => setExpanded((prev) => ({ ...prev, [key]: !prev[key] })),
        style: {
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          cursor: "pointer",
          background: "var(--bg-soft,#f9fafb)"
        }
      },
      /* @__PURE__ */ React.createElement("span", { style: dot(stages[key].color) }),
      /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, fontSize: 13 } }, title),
      /* @__PURE__ */ React.createElement("span", { style: {
        fontSize: 11,
        color: "var(--text-2,#6b7280)",
        marginLeft: "auto"
      } }, stages[key].label, stages[key].count > 0 ? ` \u2014 ${stages[key].count}` : ""),
      /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-2,#6b7280)" } }, expanded[key] ? "\u25BE" : "\u25B8")
    ),
    expanded[key] && /* @__PURE__ */ React.createElement("div", { style: { padding: 12 } }, body)
  );
  const evidenceBody = (() => {
    const sadPresent = stages.evidence.sadPresent;
    const zcPresent = stages.evidence.zcPresent;
    const sadCn = cnhsn && cnhsn.sad_cn_code || "";
    const ev = zc429 && zc429.event || {};
    const eid = (zc429 && zc429.intake_event_id || "").slice(0, 12);
    return /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-evidence-body", style: { fontSize: 12 } }, /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-evidence-sad",
        style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }
      },
      /* @__PURE__ */ React.createElement("span", null, sadPresent ? "\u2705" : "\u25FB\uFE0E"),
      /* @__PURE__ */ React.createElement("strong", null, "SAD / MRN present:"),
      /* @__PURE__ */ React.createElement("span", null, sadPresent ? "YES" : "NO"),
      sadPresent && sadCn ? /* @__PURE__ */ React.createElement("span", { style: { color: "#6b7280" } }, "(CN ", sadCn, ")") : null
    ), /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-evidence-zc",
        style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }
      },
      /* @__PURE__ */ React.createElement("span", null, zcPresent ? "\u2705" : "\u25FB\uFE0E"),
      /* @__PURE__ */ React.createElement("strong", null, "ZC429 lineage present:"),
      /* @__PURE__ */ React.createElement("span", null, zcPresent ? "YES" : "NO")
    ), sadPresent && !zcPresent && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-evidence-amber-note",
        style: {
          marginTop: 6,
          padding: 6,
          fontSize: 11,
          background: "#fef3c7",
          color: "#b45309",
          borderRadius: 4
        }
      },
      "\u26A0 Legacy SAD/MRN present. DHL ZC429 email attachments not yet ingested."
    ), zcPresent && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "AWB:"), " ", ev.awb || "\u2014"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "ZC / MRN:"), " ", ev.zc_number || "\u2014"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Sender:"), " ", ev.sender || "\u2014"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Received:"), " ", ev.received_at || "\u2014"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Intake event:"), " ", /* @__PURE__ */ React.createElement(
      "span",
      {
        style: { fontFamily: "ui-monospace,Menlo,monospace" },
        title: zc429.intake_event_id
      },
      eid,
      "\u2026"
    )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Attachments:"), " ", (zc429.attachments || []).length, zc429.classified_counts ? /* @__PURE__ */ React.createElement("span", { style: { color: "#6b7280", marginLeft: 6 } }, "(", zc429.classified_counts.zc429 || 0, " ZC429,", " ", zc429.classified_counts.invoices || 0, " inv,", " ", zc429.classified_counts.awb || 0, " awb,", " ", zc429.classified_counts.mail_evidence || 0, " mail,", " ", zc429.classified_counts.others || 0, " other)") : null)));
  })();
  const classificationBody = (() => {
    const dec = cnhsn && cnhsn.decision;
    if (dec && dec.approved) {
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "workflow-classification-accepted",
          style: { fontSize: 12 }
        },
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: {
          background: "#dcfce7",
          color: "#15803d",
          padding: "2px 8px",
          borderRadius: 12,
          fontSize: 11,
          fontWeight: 700
        } }, "Accepted"), /* @__PURE__ */ React.createElement("span", null, "SAD CN ", /* @__PURE__ */ React.createElement("strong", null, dec.sad_cn_code || cnhsn.sad_cn_code || "\u2014")), /* @__PURE__ */ React.createElement("span", { style: { color: "#6b7280" } }, "by ", dec.operator || "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { color: "#6b7280" } }, "at ", dec.recorded_at ? dec.recorded_at.slice(0, 19).replace("T", " ") : "\u2014")),
        dec.reason && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4, color: "#6b7280", fontSize: 11 } }, /* @__PURE__ */ React.createElement("em", null, dec.reason)),
        /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4, fontSize: 10, color: "#9ca3af" } }, "correction id ", (dec.correction_id || "").slice(0, 12), "\u2026")
      );
    }
    return /* @__PURE__ */ React.createElement(
      CNHSNDecisionPanel,
      {
        batchId,
        onToast: onToast || ((m) => alert(m))
      }
    );
  })();
  const productsBody = (() => {
    if (!proforma) return /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#6b7280" } }, "\u2014");
    const p = proforma.products || {};
    const sdProducts = setupDetail && setupDetail.products || null;
    const flagOn = !!(sdProducts && sdProducts.create_flag_on);
    const missingRows = sdProducts && sdProducts.missing || [];
    return /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-products-body", style: { fontSize: 12 } }, /* @__PURE__ */ React.createElement("div", null, p.mapped || 0, " of ", p.total || 0, " product codes mapped to wFirma."), p.missing > 0 && /* @__PURE__ */ React.createElement("div", { style: { color: "#b45309", marginTop: 4 } }, "\u26A0 ", p.missing, " product code(s) missing.", " ", p.create_flag_on ? "Operator may run Auto-register from the Proforma Readiness panel below." : "Auto-register is not enabled (contact your admin)."), missingRows.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-products-detail-table", style: { marginTop: 10, border: "1px solid var(--border-subtle)", borderRadius: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "6px 8px", background: "var(--bg-subtle)", fontSize: 11, fontWeight: 600, color: "var(--text)" } }, "Missing wFirma product registrations \u2014 ", missingRows.length), /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--bg-subtle)", borderTop: "1px solid var(--border-subtle)" } }, /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "product_code"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "design"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "type"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "right" } }, "qty"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "right" } }, "value"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "client"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "action"))), /* @__PURE__ */ React.createElement("tbody", null, missingRows.map((row, idx) => /* @__PURE__ */ React.createElement(
      "tr",
      {
        key: row.product_code || idx,
        "data-testid": `setup-products-row-${row.product_code}`,
        style: { borderTop: "1px solid var(--border-subtle)" }
      },
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px", fontFamily: "monospace" } }, row.product_code),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.design_no || "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.item_type || "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px", textAlign: "right" } }, row.qty != null ? Number(row.qty) : "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px", textAlign: "right" } }, row.total_value != null ? Number(row.total_value).toFixed(2) : "\u2014", row.currency ? " " + row.currency : ""),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.client_name || "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          "data-testid": `btn-setup-product-preview-${row.product_code}`,
          title: "Read-only preview of wFirma product registration. No write fires.",
          onClick: handleProductPreview,
          disabled: setupProductPreviewLoading
        },
        setupProductPreviewLoading ? "Loading\u2026" : "Preview"
      ), flagOn && /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          primary: true,
          "data-testid": `btn-setup-product-register-${row.product_code}`,
          title: "Register product in wFirma. Requires WFIRMA_CREATE_PRODUCT_ALLOWED=true. Handler wired in follow-up PR.",
          disabled: true,
          style: { marginLeft: 6 }
        },
        "Register"
      ))
    )))), !flagOn && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "setup-products-write-disabled-note",
        style: { padding: "6px 8px", fontSize: 10, color: "var(--text-3)", borderTop: "1px solid var(--border-subtle)" }
      },
      "\u24D8 Register buttons hidden \u2014 WFIRMA_CREATE_PRODUCT_ALLOWED=false. Preview is always available (dry-run)."
    )), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, color: "#6b7280" } }, "Detail panel below provides per-row write actions."));
  })();
  const customersBody = (() => {
    if (!proforma) return /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#6b7280" } }, "\u2014");
    const c = proforma.customers || {};
    const allDetails = c.details || [];
    const cmByName = {};
    (cm || []).forEach((r) => {
      if (r.bill_to_name) cmByName[r.bill_to_name.toLowerCase().trim()] = r;
    });
    const matchedStatuses = /* @__PURE__ */ new Set(["exact_match", "normalized_match", "prefix_match", "reverse_prefix_match"]);
    const CmField = ({ label, val }) => {
      if (val == null || val === "") return null;
      return /* @__PURE__ */ React.createElement("div", { style: { display: "contents" } }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", fontSize: 11 } }, label), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text)", fontWeight: 500 } }, String(val)));
    };
    const CmEditForm = ({ rec, onSave, onCancel }) => {
      const cid = rec.bill_to_contractor_id;
      const editing = cmEdit && cmEdit.contractorId === cid ? cmEdit.fields : null;
      const savedMsg = cmSavedMsg && cmSavedMsg.contractorId === cid ? cmSavedMsg.msg : null;
      const startEdit = () => setCmEdit({ contractorId: cid, fields: {
        bill_to_name: rec.bill_to_name || "",
        bill_to_nip: rec.nip || rec.bill_to_nip || "",
        bill_to_street: rec.bill_to_street || "",
        bill_to_city: rec.bill_to_city || "",
        bill_to_postal_code: rec.bill_to_postal_code || "",
        bill_to_country: rec.bill_to_country || "",
        ship_to_name: rec.ship_to_name || "",
        ship_to_street: rec.ship_to_street || "",
        ship_to_city: rec.ship_to_city || "",
        ship_to_postal_code: rec.ship_to_postal_code || "",
        preferred_payment_method: rec.preferred_payment_method || "",
        payment_terms_days: rec.payment_terms_days != null ? String(rec.payment_terms_days) : "",
        default_currency: rec.default_currency || "",
        preferred_proforma_series_id: rec.preferred_proforma_series_id || "",
        preferred_invoice_series_id: rec.preferred_invoice_series_id || ""
      } });
      const setF = (k, v) => setCmEdit((e) => ({ ...e, fields: { ...e.fields, [k]: v } }));
      const handleSave = () => {
        if (!editing) return;
        const payload = { ...editing };
        if (payload.payment_terms_days !== "") payload.payment_terms_days = Number(payload.payment_terms_days);
        else delete payload.payment_terms_days;
        saveCmFields(cid, payload);
      };
      if (!editing) {
        return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: startEdit,
            "data-testid": `btn-cm-edit-${cid}`,
            title: "Edit document defaults in Customer Master. No wFirma write fires from here."
          },
          "Edit"
        ), savedMsg && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: savedMsg.startsWith("Saved") ? "var(--badge-green-text)" : "var(--badge-red-text)" } }, savedMsg));
      }
      const inp = (k, placeholder, type) => /* @__PURE__ */ React.createElement(
        "input",
        {
          value: editing[k],
          onChange: (e) => setF(k, e.target.value),
          type: type || "text",
          placeholder,
          style: {
            width: "100%",
            fontSize: 11,
            padding: "2px 4px",
            border: "1px solid var(--border)",
            borderRadius: 3,
            background: "var(--input-bg, #fff)",
            color: "var(--text)"
          }
        }
      );
      const fgrp = (label, k, placeholder, type) => /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 1 } }, label), inp(k, placeholder, type));
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": `cm-edit-form-${cid}`,
          style: {
            marginTop: 8,
            padding: 8,
            background: "var(--card-hover)",
            border: "1px solid var(--border)",
            borderRadius: 4
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 11,
          fontWeight: 700,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 8
        } }, "Edit Customer Master \u2014 ", rec.bill_to_name),
        /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--badge-amber-text)", marginBottom: 8 } }, "Saves to Customer Master only. No PZ, no invoice, no wFirma write, no gate bypass."),
        /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 } }, /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 600,
          fontSize: 10,
          color: "var(--text-3)",
          gridColumn: "1/-1",
          textTransform: "uppercase",
          marginTop: 4
        } }, "Bill-to"), fgrp("Name", "bill_to_name", "Company name"), fgrp("VAT / NIP", "bill_to_nip", "e.g. PL1234567890"), fgrp("Street", "bill_to_street", "Street and number"), fgrp("City", "bill_to_city", "City"), fgrp("Postal code", "bill_to_postal_code", "e.g. 00-001"), fgrp("Country", "bill_to_country", "e.g. PL"), /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 600,
          fontSize: 10,
          color: "var(--text-3)",
          gridColumn: "1/-1",
          textTransform: "uppercase",
          marginTop: 4
        } }, "Ship-to (if different)"), fgrp("Ship-to name", "ship_to_name", "Leave blank to use bill-to"), fgrp("Ship-to street", "ship_to_street", "Street and number"), fgrp("Ship-to city", "ship_to_city", "City"), fgrp("Ship-to postal", "ship_to_postal_code", "e.g. 00-001"), /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 600,
          fontSize: 10,
          color: "var(--text-3)",
          gridColumn: "1/-1",
          textTransform: "uppercase",
          marginTop: 4
        } }, "Payment & Document"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 1 } }, "Payment method"), /* @__PURE__ */ React.createElement(
          "select",
          {
            value: editing.preferred_payment_method,
            onChange: (e) => setF("preferred_payment_method", e.target.value),
            style: {
              width: "100%",
              fontSize: 11,
              padding: "2px 4px",
              border: "1px solid var(--border)",
              borderRadius: 3,
              background: "var(--input-bg, #fff)",
              color: "var(--text)"
            }
          },
          /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 not set \u2014"),
          /* @__PURE__ */ React.createElement("option", { value: "transfer" }, "Transfer"),
          /* @__PURE__ */ React.createElement("option", { value: "cash" }, "Cash"),
          /* @__PURE__ */ React.createElement("option", { value: "card" }, "Card"),
          /* @__PURE__ */ React.createElement("option", { value: "compensation" }, "Compensation")
        )), fgrp("Payment terms (days)", "payment_terms_days", "e.g. 14", "number"), fgrp("Currency", "default_currency", "e.g. EUR"), fgrp("Proforma series ID", "preferred_proforma_series_id", "wFirma series ID"), fgrp("Invoice series ID", "preferred_invoice_series_id", "wFirma series ID")),
        /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, display: "flex", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            primary: true,
            onClick: handleSave,
            disabled: cmSaving,
            "data-testid": `btn-cm-save-${cid}`
          },
          cmSaving ? "Saving\u2026" : "Save to Customer Master"
        ), /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: () => {
              setCmEdit(null);
              setCmSavedMsg(null);
            },
            "data-testid": `btn-cm-cancel-${cid}`
          },
          "Cancel"
        ), cmSavedMsg && cmSavedMsg.contractorId === cid && /* @__PURE__ */ React.createElement("span", { style: {
          fontSize: 11,
          color: cmSavedMsg.msg.startsWith("Saved") ? "var(--badge-green-text)" : "var(--badge-red-text)"
        } }, cmSavedMsg.msg))
      );
    };
    return /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-customers-body", style: { fontSize: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 6 } }, c.resolved || 0, " of ", c.total || 0, " clients mapped", (c.missing > 0 || c.ambiguous > 0) && /* @__PURE__ */ React.createElement("span", { style: { color: "#b45309", marginLeft: 8 } }, "\u2014 ", c.missing > 0 ? `${c.missing} missing` : "", c.missing > 0 && c.ambiguous > 0 ? ", " : "", c.ambiguous > 0 ? `${c.ambiguous} ambiguous` : "")), (c.missing > 0 || c.ambiguous > 0) && /* @__PURE__ */ React.createElement("div", { style: { color: "#b45309", marginBottom: 8, fontSize: 11 } }, "\u26A0", " ", c.create_flag_on ? 'Auto-resolve available: click "Preview customer auto-resolve" below.' : "Create contractor in wFirma \u2192 Contractors \u2192 New contractor, then click Preview customer auto-resolve."), allDetails.map((d, i) => {
      const lookupKey = (d.matched_name || d.client_name || "").toLowerCase().trim();
      const rec = cmByName[lookupKey];
      const isResolved = matchedStatuses.has(d.status);
      const isAmbiguous = d.status === "ambiguous";
      const isMissing = d.status === "missing";
      const statusColor = isResolved ? "var(--badge-green-text)" : isAmbiguous ? "var(--badge-amber-text)" : "var(--badge-red-text)";
      const statusBg = isResolved ? "var(--badge-green-bg)" : isAmbiguous ? "var(--badge-amber-bg)" : "var(--badge-red-bg)";
      const shipDiffers = rec && rec.ship_to_name && rec.ship_to_name !== rec.bill_to_name;
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: i,
          "data-testid": `workflow-cm-card-${i}`,
          style: {
            marginBottom: 10,
            padding: 10,
            background: "var(--card-hover)",
            border: "1px solid var(--card-border)",
            borderRadius: 4
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 8,
          marginBottom: 6
        } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, fontSize: 13, color: "var(--text)" } }, d.client_name), /* @__PURE__ */ React.createElement("span", { style: {
          background: statusBg,
          color: statusColor,
          padding: "1px 7px",
          borderRadius: 4,
          fontSize: 10,
          fontWeight: 700,
          textTransform: "uppercase",
          whiteSpace: "nowrap",
          flexShrink: 0
        } }, isResolved ? "mapped" : d.status)),
        rec ? /* @__PURE__ */ React.createElement("div", { style: {
          display: "grid",
          gridTemplateColumns: "120px 1fr",
          gap: "3px 12px",
          marginBottom: 4
        } }, (rec.bill_to_name || rec.bill_to_nip) && /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 10,
          fontWeight: 700,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          gridColumn: "1/-1",
          marginTop: 4,
          marginBottom: 2
        } }, "Buyer / Bill-to"), /* @__PURE__ */ React.createElement(CmField, { label: "Name", val: rec.bill_to_name }), /* @__PURE__ */ React.createElement(CmField, { label: "VAT / NIP", val: rec.bill_to_nip }), (rec.bill_to_street || rec.bill_to_city) && /* @__PURE__ */ React.createElement(
          CmField,
          {
            label: "Address",
            val: [
              rec.bill_to_street,
              rec.bill_to_city,
              rec.bill_to_postal_code,
              rec.bill_to_country
            ].filter(Boolean).join(", ")
          }
        ), shipDiffers && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 10,
          fontWeight: 700,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          gridColumn: "1/-1",
          marginTop: 4,
          marginBottom: 2
        } }, "Receiver / Ship-to"), /* @__PURE__ */ React.createElement(CmField, { label: "Name", val: rec.ship_to_name }), (rec.ship_to_street || rec.ship_to_city) && /* @__PURE__ */ React.createElement(
          CmField,
          {
            label: "Address",
            val: [
              rec.ship_to_street,
              rec.ship_to_city,
              rec.ship_to_postal_code
            ].filter(Boolean).join(", ")
          }
        )), (rec.preferred_payment_method || rec.payment_terms_days != null || rec.default_currency) && /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 10,
          fontWeight: 700,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          gridColumn: "1/-1",
          marginTop: 4,
          marginBottom: 2
        } }, "Payment"), /* @__PURE__ */ React.createElement(CmField, { label: "Method", val: rec.preferred_payment_method }), rec.payment_terms_days != null && /* @__PURE__ */ React.createElement(CmField, { label: "Terms", val: `${rec.payment_terms_days} days` }), /* @__PURE__ */ React.createElement(CmField, { label: "Currency", val: rec.default_currency }), (rec.preferred_proforma_series_id || rec.preferred_invoice_series_id) && /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 10,
          fontWeight: 700,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          gridColumn: "1/-1",
          marginTop: 4,
          marginBottom: 2
        } }, "Document settings"), /* @__PURE__ */ React.createElement(CmField, { label: "Proforma series", val: rec.preferred_proforma_series_id }), /* @__PURE__ */ React.createElement(CmField, { label: "Invoice series", val: rec.preferred_invoice_series_id })) : /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#6b7280", marginBottom: 4 } }, "No Customer Master record \u2014 edit to create defaults."),
        rec && rec.bill_to_contractor_id && /* @__PURE__ */ React.createElement(
          CmEditForm,
          {
            rec,
            onSave: saveCmFields,
            onCancel: () => {
              setCmEdit(null);
              setCmSavedMsg(null);
            }
          }
        ),
        /* @__PURE__ */ React.createElement("details", { style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement("summary", { style: {
          fontSize: 10,
          color: "var(--text-3)",
          cursor: "pointer",
          userSelect: "none"
        } }, "wFirma mapping details"), /* @__PURE__ */ React.createElement("div", { style: {
          marginTop: 4,
          display: "grid",
          gridTemplateColumns: "120px 1fr",
          gap: "2px 8px",
          fontSize: 10,
          color: "var(--text-2)"
        } }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Status"), /* @__PURE__ */ React.createElement("div", null, d.status || "\u2014"), d.wfirma_customer_id && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "wFirma ID"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("code", null, d.wfirma_customer_id))), d.matched_name && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Matched name"), /* @__PURE__ */ React.createElement("div", null, d.matched_name)), d.candidates && d.candidates.length > 0 && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Candidates"), /* @__PURE__ */ React.createElement("div", null, d.candidates.slice(0, 4).join(", "), d.candidates.length > 4 ? ` (+${d.candidates.length - 4})` : "")), isMissing && /* @__PURE__ */ React.createElement("div", { style: { gridColumn: "1/-1", color: "#b45309", marginTop: 2 } }, "Not yet mapped. Create contractor in wFirma, then re-run auto-resolve.")))
      );
    }), allDetails.length === 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#6b7280" } }, "No customer details available."));
  })();
  const warehouseBody = (() => {
    if (!batchReady) return /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#6b7280" } }, "\u2014");
    const wh = batchReady.warehouse || null;
    const sales = batchReady.sales || null;
    return /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-warehouse-body", style: { fontSize: 12 } }, /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-warehouse-line",
        style: { display: "flex", gap: 8, alignItems: "center" }
      },
      /* @__PURE__ */ React.createElement("span", null, wh && wh.ready ? "\u2705" : "\u26A0"),
      /* @__PURE__ */ React.createElement("strong", null, "Warehouse:"),
      /* @__PURE__ */ React.createElement("span", null, wh && wh.message || "\u2014")
    ), /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-sales-line",
        style: { display: "flex", gap: 8, alignItems: "center", marginTop: 4 }
      },
      /* @__PURE__ */ React.createElement("span", null, sales && sales.ready ? "\u2705" : "\u26A0"),
      /* @__PURE__ */ React.createElement("strong", null, "Sales scan:"),
      /* @__PURE__ */ React.createElement("span", null, sales && sales.message || "\u2014")
    ));
  })();
  const previewBody = (() => {
    const localPzExists = stages.preview.localPzExists;
    const previewErr = stages.preview.previewErr;
    return /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-preview-body", style: { fontSize: 12 } }, /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-preview-local",
        style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }
      },
      /* @__PURE__ */ React.createElement("span", null, localPzExists ? "\u2705" : "\u25FB\uFE0E"),
      /* @__PURE__ */ React.createElement("strong", null, "Local PZ calculation:"),
      /* @__PURE__ */ React.createElement("span", null, localPzExists ? "generated (PDF + XLSX on disk)" : "not generated")
    ), /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-preview-wfirma",
        style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }
      },
      /* @__PURE__ */ React.createElement("span", null, preview && preview.already_created ? "\u2705" : preview && preview.ready ? "\u2705" : "\u25FB\uFE0E"),
      /* @__PURE__ */ React.createElement("strong", null, "wFirma PZ export:"),
      /* @__PURE__ */ React.createElement("span", null, !preview ? "\u2014" : preview.already_created ? `already created (id ${preview.wfirma_pz_doc_id || "\u2014"})` : preview.ready ? "preview ready" : previewErr ? "blocked by guard" : "not ready")
    ), previewErr && (() => {
      const structured = Array.isArray(preview && preview.blockers) ? preview.blockers : [];
      const engineErr = preview && preview.engine_error || "";
      if (structured.length > 0) {
        const hasEngine = structured.some((b) => b && b.code === "ENGINE_ERROR");
        const isError = structured.some((b) => b && b.severity === "error");
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": "workflow-preview-guard",
            style: {
              marginTop: 4,
              padding: 6,
              fontSize: 11,
              background: isError ? "#fee2e2" : "#fef3c7",
              color: isError ? "#991b1b" : "#b45309",
              borderRadius: 4
            }
          },
          hasEngine ? "\u26D4" : "\u26A0",
          " ",
          hasEngine ? "PZ engine failed:" : "PZ not ready:",
          " ",
          structured.map((b, i) => /* @__PURE__ */ React.createElement("span", { key: b && b.code || i }, i > 0 ? " \xB7 " : "", b && b.message || "", b && b.code ? /* @__PURE__ */ React.createElement("span", { style: {
            marginLeft: 4,
            fontFamily: "ui-monospace,Menlo,monospace",
            color: "#9ca3af"
          } }, "(", b.code, ")") : null)),
          engineErr && !hasEngine ? /* @__PURE__ */ React.createElement("div", { style: { marginTop: 2 } }, engineErr) : null
        );
      }
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "workflow-preview-guard",
          style: {
            marginTop: 4,
            padding: 6,
            fontSize: 11,
            background: "#fef3c7",
            color: "#b45309",
            borderRadius: 4
          }
        },
        "\u26A0 ",
        preview.detail && preview.detail.error || "pz_preview unavailable",
        preview.detail && preview.detail.code ? /* @__PURE__ */ React.createElement("span", { style: {
          marginLeft: 6,
          fontFamily: "ui-monospace,Menlo,monospace",
          color: "#9ca3af"
        } }, "(", preview.detail.code, ")") : null
      );
    })(), !previewErr && preview && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4, color: "#6b7280" } }, "MRN ", preview.mrn || "\u2014", " \xB7 warehouse ", preview.warehouse_id || "\u2014", (preview.unresolved_product_codes || []).length > 0 && /* @__PURE__ */ React.createElement("span", { style: { color: "#b45309", marginLeft: 6 } }, "\xB7 ", preview.unresolved_product_codes.length, " unresolved product code(s)"), (preview.price_conflicts || []).length > 0 && /* @__PURE__ */ React.createElement("span", { style: { color: "#b45309", marginLeft: 6 } }, "\xB7 ", preview.price_conflicts.length, " price conflict(s)")));
  })();
  const executeBody = /* @__PURE__ */ React.createElement(ExecutePZGate, { batchId, onToast });
  if (loading) {
    return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "workflow-card" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, marginBottom: 8 } }, "\u{1F6E0} Operator Workflow"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "#6b7280" } }, "Loading\u2026"));
  }
  const sectionGroupHeader = (label, color) => /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 10px",
    marginBottom: 8,
    marginTop: 4,
    background: color === "a" ? "#eff6ff" : "#f0fdf4",
    borderLeft: `3px solid ${color === "a" ? "#3b82f6" : "#16a34a"}`,
    borderRadius: "0 4px 4px 0"
  } }, /* @__PURE__ */ React.createElement("span", { style: {
    fontSize: 12,
    fontWeight: 700,
    color: color === "a" ? "#1d4ed8" : "#15803d"
  } }, label));
  return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "workflow-card" }, /* @__PURE__ */ React.createElement("div", { style: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 12
  } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700 } }, "\u{1F6E0} Operator Workflow"), /* @__PURE__ */ React.createElement(
    Btn,
    {
      "data-testid": "workflow-refresh",
      onClick: refresh,
      variant: "outline",
      small: true,
      style: { marginLeft: "auto" }
    },
    "Refresh"
  )), error && /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "workflow-error",
      style: { fontSize: 11, color: "var(--badge-red-text)", marginBottom: 8 }
    },
    error
  ), /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-section-b" }, sectionGroupHeader("B \u2014 PZ Generation & Customs", "b"), (() => {
    const allStagesDone = stages.evidence.color === "green" && stages.classification.color === "green" && stages.products.color === "green" && stages.customers.color === "green" && stages.warehouse.color === "green" && stages.preview.color === "green" && stages.execute.color === "green";
    return allStagesDone ? /* @__PURE__ */ React.createElement(
      "div",
      {
        style: {
          background: "var(--badge-green-bg)",
          border: "1px solid var(--badge-green-border)",
          color: "var(--badge-green-text)",
          borderRadius: 8,
          padding: "12px 16px",
          marginBottom: 8,
          fontSize: 12,
          fontWeight: 600
        },
        "data-testid": "workflow-completion-banner"
      },
      "\u2713 All steps complete \u2014 ready to post to accounting"
    ) : null;
  })(), /* @__PURE__ */ React.createElement("div", { "data-testid": "workflow-pipeline", style: bar }, STAGE_ORDER.map(([k, label], i) => /* @__PURE__ */ React.createElement(React.Fragment, { key: k }, stagePill(stages, k, label), i < STAGE_ORDER.length - 1 && /* @__PURE__ */ React.createElement("span", { style: { color: "#9ca3af" } }, "\u2192")))), (() => {
    const next = [];
    if (stages.classification.color === "red")
      next.push("Resolve CN/HSN block (different chapter detected).");
    if (stages.products.count > 0)
      next.push(`Map ${stages.products.count} product code(s) to wFirma (Auto-register or manual).`);
    if (stages.customers.count > 0)
      next.push(`Resolve ${stages.customers.count} customer identity row(s).`);
    if (stages.warehouse.color === "amber" && stages.warehouse.message)
      next.push(stages.warehouse.message);
    if (stages.evidence.sadPresent && !stages.evidence.zcPresent)
      next.push("Ingest DHL ZC429 email (operator action).");
    if (!stages.evidence.sadPresent)
      next.push("Awaiting customs document (SAD / ZC429) \u2014 required before PZ can run.");
    if (next.length === 0) return null;
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "workflow-next-actions",
        style: {
          background: "#fffbeb",
          border: "1px solid #fcd34d",
          borderRadius: 6,
          padding: 8,
          marginBottom: 12,
          fontSize: 12,
          color: "#92400e"
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, marginBottom: 4 } }, "Next required actions"),
      /* @__PURE__ */ React.createElement("ul", { style: { margin: 0, paddingLeft: 18 } }, next.slice(0, 2).map((n, i) => /* @__PURE__ */ React.createElement("li", { key: i }, n)))
    );
  })(), sectionShell("evidence", "1. DHL / ZC429 evidence", evidenceBody), sectionShell("classification", "2. Tariff classification", classificationBody), sectionShell("products", "3. Products registered in accounting", productsBody), sectionShell("customers", "4. Customers matched to orders", customersBody), setupDetail && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-detail-panel", style: {
    margin: "8px 0",
    padding: "10px 12px",
    border: "1px solid var(--border-subtle)",
    borderRadius: 4,
    background: "var(--bg-subtle)",
    fontSize: 12
  } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-readiness-prepare", style: {
    padding: "4px 8px",
    borderRadius: 3,
    fontSize: 11,
    fontWeight: 600,
    background: setupDetail.readiness.can_prepare_proforma ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
    color: setupDetail.readiness.can_prepare_proforma ? "var(--badge-green-text)" : "var(--badge-amber-text)"
  } }, "Can prepare proforma: ", setupDetail.readiness.can_prepare_proforma ? "\u2713" : "\u2717"), /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-readiness-post", style: {
    padding: "4px 8px",
    borderRadius: 3,
    fontSize: 11,
    fontWeight: 600,
    background: setupDetail.readiness.can_post_to_wfirma ? "var(--badge-green-bg)" : "var(--badge-red-bg)",
    color: setupDetail.readiness.can_post_to_wfirma ? "var(--badge-green-text)" : "var(--badge-red-text)"
  } }, "Can post to wFirma: ", setupDetail.readiness.can_post_to_wfirma ? "\u2713" : "\u2717"), /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-transit-truth", style: { fontSize: 11, color: "var(--text-3)" } }, "Transit truth: ", setupDetail.readiness.purchase_transit_count, " pcs PURCHASE_TRANSIT (", setupDetail.readiness.batch_lifecycle, ")")), setupDetail.readiness.blockers_for_preparation.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-blockers-prepare", style: { marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "var(--badge-amber-text)" } }, "Preparation blockers:"), /* @__PURE__ */ React.createElement("ul", { style: { margin: "2px 0 0 18px", padding: 0, fontSize: 11 } }, setupDetail.readiness.blockers_for_preparation.map((b, i) => /* @__PURE__ */ React.createElement("li", { key: i }, b)))), setupDetail.readiness.blockers_for_posting.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-blockers-post", style: { marginBottom: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "var(--badge-red-text)" } }, "Posting blockers (preserves fiscal/customs gates):"), /* @__PURE__ */ React.createElement("ul", { style: { margin: "2px 0 0 18px", padding: 0, fontSize: 11 } }, setupDetail.readiness.blockers_for_posting.map((b, i) => /* @__PURE__ */ React.createElement("li", { key: i }, b)))), (setupDetail.customers.details || []).length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-customers-detail-table", style: { marginTop: 8, border: "1px solid var(--border-subtle)", borderRadius: 3, background: "var(--bg)" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "6px 8px", background: "var(--bg-subtle)", fontSize: 11, fontWeight: 600 } }, "Customer setup \u2014 per-client action"), /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--bg-subtle)", borderTop: "1px solid var(--border-subtle)" } }, /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "client_name"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "status"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "wfirma_id"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "CM row"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "action_needed"), /* @__PURE__ */ React.createElement("th", { style: { padding: "4px 6px", textAlign: "left" } }, "operator actions"))), /* @__PURE__ */ React.createElement("tbody", null, setupDetail.customers.details.map((row, idx) => {
    const cFlagOn = !!setupDetail.customers.create_flag_on;
    const slug = String(row.client_name || "").replace(/[^A-Za-z0-9]+/g, "-").toLowerCase();
    const needCreate = row.action_needed === "create_in_wfirma";
    return /* @__PURE__ */ React.createElement(
      "tr",
      {
        key: row.client_name || idx,
        "data-testid": `setup-customers-row-${slug}`,
        style: { borderTop: "1px solid var(--border-subtle)" }
      },
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.client_name || "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.status),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px", fontFamily: "monospace" } }, row.wfirma_customer_id || "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.cm_record_present ? row.cm_bill_to_name || "present" : "\u2014"),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, row.action_needed),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 6px" } }, /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          "data-testid": `btn-setup-customer-save-cm-${slug}`,
          title: "Open Customer Master editor for this client. Writes only to local Customer Master; no wFirma call.",
          onClick: () => handleSetupSaveCmFor(row),
          disabled: !row.cm_record_present || cmSaving
        },
        "Save CM"
      ), /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          "data-testid": `btn-setup-customer-resolve-${slug}`,
          title: "Re-run customer auto-resolve against wFirma cache. Dry-run preview only \u2014 no contractor creation.",
          onClick: handleCustomerResolve,
          disabled: setupCustomerResolveLoading,
          style: { marginLeft: 6 }
        },
        setupCustomerResolveLoading ? "Loading\u2026" : "Resolve"
      ), cFlagOn && needCreate && /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          primary: true,
          "data-testid": `btn-setup-customer-create-wfirma-${slug}`,
          title: "Create contractor in wFirma. Requires WFIRMA_CREATE_CUSTOMER_ALLOWED=true. Handler wired in follow-up PR.",
          disabled: true,
          style: { marginLeft: 6 }
        },
        "Create in wFirma"
      ))
    );
  }))), !setupDetail.customers.create_flag_on && /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "setup-customers-write-disabled-note",
      style: { padding: "6px 8px", fontSize: 10, color: "var(--text-3)", borderTop: "1px solid var(--border-subtle)" }
    },
    "\u24D8 Create-in-wFirma buttons hidden \u2014 WFIRMA_CREATE_CUSTOMER_ALLOWED=false. Save CM and Resolve are dry-run safe."
  )), setupDetailErr && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-detail-error", style: { marginTop: 6, fontSize: 11, color: "var(--badge-red-text)" } }, "setup-detail fetch error: ", setupDetailErr), (setupProductPreview || setupProductPreviewErr) && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-product-preview-result", style: { marginTop: 10, padding: "8px 10px", background: "var(--bg)", border: "1px solid var(--border-subtle)", borderRadius: 3, fontSize: 11 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, marginBottom: 4 } }, "Product preview result (dry-run, no writes)"), setupProductPreviewErr && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text)" } }, "error: ", setupProductPreviewErr), setupProductPreview && /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 12px" } }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "scanned"), /* @__PURE__ */ React.createElement("div", null, setupProductPreview.total_codes != null ? setupProductPreview.total_codes : setupProductPreview.scanned ?? "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "mirrored (mapped)"), /* @__PURE__ */ React.createElement("div", null, setupProductPreview.mirrored_count != null ? setupProductPreview.mirrored_count : setupProductPreview.matched_count ?? "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "missing"), /* @__PURE__ */ React.createElement("div", null, setupProductPreview.missing_count != null ? setupProductPreview.missing_count : Array.isArray(setupProductPreview.missing) ? setupProductPreview.missing.length : "\u2014"), Array.isArray(setupProductPreview.missing) && setupProductPreview.missing.length > 0 && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "missing codes"), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "monospace", fontSize: 10 } }, setupProductPreview.missing.slice(0, 12).join(", "), setupProductPreview.missing.length > 12 ? ` \u2026 (+${setupProductPreview.missing.length - 12} more)` : "")))), /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "pending-adoption-panel",
      style: {
        marginTop: 10,
        padding: "8px 10px",
        background: "var(--bg)",
        border: "1px solid var(--border-subtle)",
        borderRadius: 3,
        fontSize: 11
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: 4
    } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600 } }, "Pending wFirma adoption decisions"), /* @__PURE__ */ React.createElement(
      Btn,
      {
        variant: "outline",
        "data-testid": "pending-adoption-open-modal",
        onClick: openPendingModal
      },
      "Resolve pending products"
    )),
    /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Each new product_code found in wFirma must be explicitly adopted. PZ + Proforma stay blocked until an operator chooses.")
  ), pendingModalOpen && /* @__PURE__ */ React.createElement(
    Modal,
    {
      title: "Resolve pending wFirma products",
      onClose: closePendingModal,
      wide: true
    },
    /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "pending-adoption-modal-body",
        style: { fontSize: 11 }
      },
      pendingListLoading && /* @__PURE__ */ React.createElement("div", null, "Loading pending rows\u2026"),
      pendingListErr && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "pending-adoption-error",
          style: { color: "var(--badge-red-text)" }
        },
        "error: ",
        pendingListErr
      ),
      !pendingListLoading && !pendingListErr && Array.isArray(pendingList) && pendingList.length === 0 && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "pending-adoption-empty",
          style: { color: "var(--text-3)" }
        },
        "No pending products. All product_codes resolved."
      ),
      !pendingListLoading && Array.isArray(pendingList) && pendingList.length > 0 && // Scrollable list — handles batches with many pending
      // rows (raised by reviewer-challenge as scale concern).
      /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "pending-adoption-list",
          style: { maxHeight: 480, overflowY: "auto" }
        },
        pendingList.map((p) => {
          const pc = p.product_code;
          const cmp = pendingCompare[pc];
          const busy = pendingActionBusy[pc];
          const msg = pendingActionMsg[pc];
          const isErrMsg = msg && (msg.includes("failed") || msg.includes("error"));
          return /* @__PURE__ */ React.createElement(
            "div",
            {
              key: pc,
              "data-testid": `pending-row-${pc}`,
              style: {
                padding: 8,
                border: "1px solid var(--border-subtle)",
                borderRadius: 3,
                marginBottom: 6
              }
            },
            /* @__PURE__ */ React.createElement("div", { style: {
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4
            } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, fontFamily: "monospace" } }, pc), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", fontSize: 10 } }, "wfid=", p.wfirma_product_id || "\u2014", " \xB7 name=", p.product_name_pl || "\u2014", " \xB7 unit=", p.unit || "\u2014")),
            /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 4 } }, /* @__PURE__ */ React.createElement(
              Btn,
              {
                variant: "outline",
                "data-testid": `pending-compare-${pc}`,
                onClick: () => fetchPendingCompare(pc),
                disabled: !!pendingCompareBusy[pc]
              },
              pendingCompareBusy[pc] ? "\u27F3 Comparing\u2026" : "Compare with wFirma"
            ), cmp && /* @__PURE__ */ React.createElement(
              "div",
              {
                "data-testid": `pending-comparison-${pc}`,
                style: {
                  marginTop: 4,
                  padding: 6,
                  fontSize: 10,
                  background: "var(--bg)",
                  border: "1px dashed var(--border-subtle)"
                }
              },
              cmp.error ? /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text)" } }, cmp.error) : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("b", null, "recommendation:"), " ", cmp.recommendation), cmp.advisory && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 2 } }, cmp.advisory), Array.isArray(cmp.differences) && cmp.differences.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 2 } }, /* @__PURE__ */ React.createElement("b", null, "differences:"), cmp.differences.map((d, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontFamily: "monospace" } }, "\xB7 ", d.field, " [", d.severity, "] local=", JSON.stringify(d.local), " wfirma=", JSON.stringify(d.wfirma)))))
            )),
            /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
              Btn,
              {
                "data-testid": `pending-action-adopt-${pc}`,
                onClick: () => handlePendingAdopt(pc),
                disabled: !!busy
              },
              busy === "Adopt as-is" ? "\u27F3 Adopting\u2026" : "Adopt as-is"
            ), /* @__PURE__ */ React.createElement(
              Btn,
              {
                "data-testid": `pending-action-update-${pc}`,
                onClick: () => handlePendingUpdateAndAdopt(pc),
                disabled: !!busy
              },
              busy === "Update then adopt" ? "\u27F3 Updating\u2026" : "Update then adopt"
            ), /* @__PURE__ */ React.createElement(
              Btn,
              {
                "data-testid": `pending-action-create-${pc}`,
                onClick: () => handlePendingCreateAndAdopt(pc),
                disabled: !!busy
              },
              busy === "Create new" ? "\u27F3 Creating\u2026" : "Create new"
            )),
            msg && /* @__PURE__ */ React.createElement(
              "div",
              {
                "data-testid": `pending-message-${pc}`,
                style: {
                  marginTop: 4,
                  fontSize: 10,
                  color: isErrMsg ? "var(--badge-red-text)" : "var(--badge-green-text)"
                }
              },
              msg
            )
          );
        })
      ),
      /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, textAlign: "right" } }, /* @__PURE__ */ React.createElement(
        Btn,
        {
          "data-testid": "pending-adoption-close",
          onClick: closePendingModal
        },
        "Close (no mutation)"
      ))
    )
  ), (setupCustomerResolve || setupCustomerResolveErr) && /* @__PURE__ */ React.createElement("div", { "data-testid": "setup-customer-resolve-result", style: { marginTop: 10, padding: "8px 10px", background: "var(--bg)", border: "1px solid var(--border-subtle)", borderRadius: 3, fontSize: 11 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, marginBottom: 4 } }, "Customer resolve result (dry-run, no contractor creation)"), setupCustomerResolveErr && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text)" } }, "error: ", setupCustomerResolveErr), setupCustomerResolve && /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 12px" } }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "processed"), /* @__PURE__ */ React.createElement("div", null, setupCustomerResolve.total_clients != null ? setupCustomerResolve.total_clients : setupCustomerResolve.processed ?? "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "resolved"), /* @__PURE__ */ React.createElement("div", null, setupCustomerResolve.resolved_count != null ? setupCustomerResolve.resolved_count : setupCustomerResolve.matched_count ?? "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "ambiguous"), /* @__PURE__ */ React.createElement("div", null, setupCustomerResolve.ambiguous_count ?? "\u2014"), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "still missing"), /* @__PURE__ */ React.createElement("div", null, setupCustomerResolve.missing_count != null ? setupCustomerResolve.missing_count : "\u2014"), Array.isArray(setupCustomerResolve.results) && setupCustomerResolve.results.length > 0 && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "details"), /* @__PURE__ */ React.createElement("div", null, setupCustomerResolve.results.slice(0, 10).map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 10 } }, /* @__PURE__ */ React.createElement("b", null, r.client_name || r.name || "\u2014"), " \u2192 ", r.status || r.result || "\u2014", r.wfirma_customer_id ? ` (wfid=${r.wfirma_customer_id})` : ""))))))), sectionShell("warehouse", "5. Packing list / Sales linkage", warehouseBody), sectionShell("preview", "6. Goods receipt ready to post", previewBody), sectionShell("execute", "7. Create goods receipt in wFirma", executeBody)));
}
function CNHSNDecisionPanel({ batchId, onToast }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const refresh = React.useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError("");
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const r2 = await fetch(
        `/dashboard/batches/${encodeURIComponent(batchId)}/cn-hsn-classification`,
        { headers: hdrs, credentials: "include" }
      );
      if (!r2.ok) {
        setError(`HTTP ${r2.status}`);
        setData(null);
      } else setData(await r2.json());
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [batchId]);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const postDecision = React.useCallback(async (path, label, defaultReason) => {
    const reason = window.prompt(
      `${label}

Enter a justification (min 20 characters):`,
      defaultReason
    );
    if (!reason || reason.trim().length < 20) {
      alert("Reason must be at least 20 characters.");
      return;
    }
    setBusy(path);
    try {
      const r2 = await fetch(
        `/dashboard/batches/${encodeURIComponent(batchId)}/cn-decision/${path}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            ...window.__apiHeaders ? window.__apiHeaders() : {}
          },
          body: JSON.stringify({ reason: reason.trim() })
        }
      );
      const body = await r2.json().catch(() => ({}));
      if (onToast) onToast(r2.ok ? `Decision recorded: ${path} (id ${body.correction_id || "\u2014"})` : `Decision failed: ${body.detail || r2.status}`);
      await refresh();
    } catch (e) {
      if (onToast) onToast(`Decision error: ${e}`);
    } finally {
      setBusy("");
    }
  }, [batchId, refresh, onToast]);
  if (loading) {
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-panel",
        style: { marginBottom: 16, padding: 12, border: "1px solid var(--border,#e5e7eb)", borderRadius: 6, fontSize: 12 }
      },
      "Loading CN/HSN classification\u2026"
    );
  }
  if (error || !data) {
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-panel",
        style: { marginBottom: 16, padding: 12, border: "1px solid var(--badge-red-border)", borderRadius: 6, fontSize: 12, color: "var(--badge-red-text)" }
      },
      "CN/HSN classification load failed: ",
      error || "no data"
    );
  }
  if (!data.has_data) return null;
  const r = data.result || {};
  const level = r.worst_level || "invalid_input";
  const blocking = !!r.is_blocking;
  const colorMap = {
    exact_code_match: { bg: "#dcfce7", text: "#15803d", label: "Exact match" },
    hs6_match: { bg: "#dcfce7", text: "#15803d", label: "HS6 compatible" },
    heading_match: { bg: "#dcfce7", text: "#15803d", label: "Heading compatible" },
    chapter_match: { bg: "#fef3c7", text: "#b45309", label: "Chapter only \u2014 review" },
    different_chapter: { bg: "#fee2e2", text: "#991b1b", label: "Different chapter \u2014 hard block" },
    invalid_input: { bg: "#f3f4f6", text: "#374151", label: "Cannot compare" }
  };
  const c = colorMap[level] || colorMap.invalid_input;
  const decision = data.decision || null;
  const decided = !!(decision && decision.decision_type);
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "cn-hsn-panel",
      style: { marginBottom: 16, padding: 16, border: `2px solid ${c.text}33`, borderRadius: 8, background: c.bg }
    },
    /* @__PURE__ */ React.createElement("div", { style: {
      fontWeight: 700,
      fontSize: 13,
      marginBottom: 8,
      color: c.text,
      display: "flex",
      alignItems: "center",
      gap: 8
    } }, "\u{1F9FE} CN \u2194 HSN Classification", /* @__PURE__ */ React.createElement(
      "span",
      {
        "data-testid": "cn-hsn-status-chip",
        style: {
          padding: "2px 8px",
          borderRadius: 12,
          fontSize: 11,
          fontWeight: 700,
          background: "#fff",
          color: c.text,
          border: `1px solid ${c.text}`
        }
      },
      c.label
    )),
    /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2,#555)", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "SAD CN code:"), " ", /* @__PURE__ */ React.createElement("span", { "data-testid": "cn-hsn-sad", style: { fontFamily: "ui-monospace,Menlo,monospace" } }, data.sad_cn_code || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Invoice HSN codes:"), " ", /* @__PURE__ */ React.createElement("span", { "data-testid": "cn-hsn-invoice", style: { fontFamily: "ui-monospace,Menlo,monospace" } }, (data.invoice_hsns || []).join(", ") || "\u2014")), r.aggregation_detected && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-aggregation",
        style: { marginTop: 4 }
      },
      "SAD aggregates multiple invoice HSNs."
    ), r.mixed_metals_detected && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-mixed",
        style: { marginTop: 4 }
      },
      "Invoice contains mixed HSN headings (e.g. silver vs gold)."
    )),
    (r.notes || []).length > 0 && /* @__PURE__ */ React.createElement("ul", { "data-testid": "cn-hsn-notes", style: { margin: "6px 0 8px 18px", fontSize: 11 } }, r.notes.map((n, i) => /* @__PURE__ */ React.createElement("li", { key: i }, n))),
    !decided && level === "chapter_match" && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-buttons",
        style: { display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }
      },
      /* @__PURE__ */ React.createElement(
        Btn,
        {
          "data-testid": "cn-accept-sad",
          disabled: !!busy,
          variant: "primary",
          onClick: () => postDecision(
            "accept-sad",
            "Accept SAD CN as authoritative for this shipment",
            `SAD CN ${data.sad_cn_code} accepted \u2014 invoice HSNs share HS chapter; aggregation acceptable for jewelry classification`
          )
        },
        "\u2713 Accept SAD CN"
      ),
      /* @__PURE__ */ React.createElement(
        Btn,
        {
          "data-testid": "cn-correct-internal",
          disabled: !!busy,
          variant: "outline",
          onClick: () => postDecision(
            "correct-internal",
            "Record an internal CN/HSN correction (does NOT mutate SAD source)",
            `Internal correction: invoice HSN to be reclassified at next intake; SAD CN ${data.sad_cn_code} retained as filed`
          )
        },
        "\u270E Correct internally"
      ),
      /* @__PURE__ */ React.createElement(
        Btn,
        {
          "data-testid": "cn-escalate-agent",
          disabled: !!busy,
          variant: "danger",
          onClick: () => postDecision(
            "escalate-agent",
            "Escalate CN/HSN mismatch to the customs agent",
            `Escalation: SAD CN ${data.sad_cn_code} vs invoice HSN ${(data.invoice_hsns || []).join(", ")} \u2014 request clarification from customs agent`
          )
        },
        "\u2709 Send back to agent"
      )
    ),
    !decided && level === "different_chapter" && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-hard-block",
        style: { fontSize: 12, color: "var(--badge-red-text)", marginTop: 6 }
      },
      "\u26D4 Different HS chapters. Contact the clearing agent for a corrected SAD before proceeding. PZ remains blocked."
    ),
    decided && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "cn-hsn-decision-recorded",
        style: {
          marginTop: 8,
          padding: 8,
          background: "#fff",
          border: "1px solid #e5e7eb",
          borderRadius: 6,
          fontSize: 11
        }
      },
      /* @__PURE__ */ React.createElement("strong", null, "Decision recorded:"),
      " ",
      decision.decision_type,
      " ",
      "\u2014 operator: ",
      decision.operator || "\u2014",
      " ",
      "\u2014 at ",
      decision.recorded_at,
      /* @__PURE__ */ React.createElement("br", null),
      /* @__PURE__ */ React.createElement("em", null, decision.reason)
    )
  );
}
function ExecutePZGate({ batchId, onToast }) {
  const [data, setData] = React.useState(null);
  const [caps, setCaps] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const refresh = React.useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError("");
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const [r1, r2] = await Promise.all([
        fetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_preview`, { headers: hdrs }),
        fetch(`/api/v1/wfirma/capabilities`, { headers: hdrs })
      ]);
      if (!r1.ok) {
        setError(`pz_preview HTTP ${r1.status}`);
        setData(null);
      } else setData(await r1.json());
      if (r2.ok) setCaps(await r2.json());
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [batchId]);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const onExecute = React.useCallback(async () => {
    if (!batchId) return;
    if (!window.confirm(
      "Create goods receipt in wFirma?\n\nThis writes a wFirma PZ document. Proceed only after PZ Preview verification."
    )) return;
    setBusy(true);
    try {
      const _op = _resolveOperator();
      const _hdrs = {
        ...window.__apiHeaders ? window.__apiHeaders() : {},
        ..._op ? { "X-Operator": _op } : {}
      };
      const r = await fetch(
        `/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_create`,
        { method: "POST", headers: _hdrs }
      );
      const body = await r.json().catch(() => ({}));
      if (onToast) onToast(r.ok ? "PZ executed" : `PZ execute failed: ${body.error || r.status}`);
      await refresh();
    } catch (e) {
      if (onToast) onToast(`PZ execute error: ${e}`);
    } finally {
      setBusy(false);
    }
  }, [batchId, refresh, onToast]);
  const card = {
    background: "var(--card,#fff)",
    border: "1px solid var(--border,#e5e7eb)",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16
  };
  const h2 = {
    fontSize: 14,
    fontWeight: 700,
    marginBottom: 12,
    display: "flex",
    alignItems: "center",
    gap: 8
  };
  const chip = (color) => ({
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 12,
    fontSize: 11,
    fontWeight: 700,
    background: color === "green" ? "#dcfce7" : color === "amber" ? "#fef3c7" : color === "gray" ? "#f3f4f6" : "#fee2e2",
    color: color === "green" ? "#15803d" : color === "amber" ? "#b45309" : color === "gray" ? "#374151" : "#991b1b"
  });
  const label = { color: "var(--text-2,#6b7280)", fontSize: 11, marginBottom: 2 };
  if (loading) {
    return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "execute-pz-gate" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u26A1 Create goods receipt in wFirma"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2,#6b7280)" } }, "Loading\u2026"));
  }
  const ready = !!(data && data.ready);
  const wouldCreate = !!(data && data.would_create_pz);
  const alreadyCreated = !!(data && data.already_created);
  const flagOn = !!(caps && (caps.create_pz_allowed || caps.wfirma_create_pz_allowed || caps.flags && (caps.flags.create_pz_allowed || caps.flags.wfirma_create_pz_allowed)));
  const enabled = ready && wouldCreate && flagOn && !alreadyCreated && !busy;
  const _lifecycle = data && data.pz_lifecycle;
  const _lfSuppressCreateDisabled = !!(_lifecycle && _lifecycle.override_create_disabled_message);
  const _lfRecoveryState = !!(_lifecycle && (_lifecycle.state === "PZ_RECOVERY_REQUIRED" || _lifecycle.state === "PZ_DUPLICATE_DETECTED" || _lifecycle.state === "PZ_LOCKED"));
  const reasons = [];
  if (_lfRecoveryState) {
    if (_lifecycle.state === "PZ_RECOVERY_REQUIRED") {
      reasons.push("PZ recovery required \u2014 use Confirm Existing PZ in the wFirma Warehouse card above");
    } else if (_lifecycle.state === "PZ_DUPLICATE_DETECTED") {
      reasons.push("Duplicate wFirma PZ doc id \u2014 resolve cross-batch conflict before creating");
    } else if (_lifecycle.state === "PZ_LOCKED") {
      reasons.push("Batch locked by accounting period close or operator hold");
    }
  } else if (!alreadyCreated) {
    if (!flagOn && !_lfSuppressCreateDisabled) reasons.push("PZ creation is disabled (admin setting)");
    if (!ready) reasons.push("PZ preview not ready \u2014 resolve issues in steps 1\u20136 above");
    if (!wouldCreate) reasons.push("Preview check: no PZ would be created \u2014 verify product and customer mapping");
    if (data && (data.unresolved_product_codes || []).length > 0) {
      reasons.push(`${data.unresolved_product_codes.length} product code(s) unresolved`);
    }
    if (data && (data.price_conflicts || []).length > 0) {
      reasons.push(`${data.price_conflicts.length} price conflict(s)`);
    }
  }
  return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "execute-pz-gate" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u26A1 Create goods receipt in wFirma"), reasons.length > 0 && !enabled && /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "execute-pz-reasons",
      style: { fontSize: 11, color: "#b45309", marginBottom: 8 }
    },
    /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, marginBottom: 4 } }, "What's needed:"),
    reasons.map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i }, "\u26A0 ", r))
  ), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 8 } }, /* @__PURE__ */ React.createElement(
    "span",
    {
      style: chip(enabled ? "green" : alreadyCreated ? "green" : "amber"),
      "data-testid": "execute-pz-status-chip"
    },
    alreadyCreated ? "\u2713 Already created" : enabled ? "Ready to post" : "Blocked \u2014 resolve items above"
  )), /* @__PURE__ */ React.createElement(
    "details",
    {
      "data-testid": "execute-pz-summary",
      style: { fontSize: 11, color: "var(--text-2,#6b7280)", marginBottom: 8 }
    },
    /* @__PURE__ */ React.createElement("summary", { style: {
      cursor: "pointer",
      fontSize: 11,
      color: "var(--text-2,#6b7280)",
      padding: "2px 0"
    } }, "Technical diagnostics"),
    /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: label }, "PZ preview ready: "), String(ready)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: label }, "Would create PZ: "), String(wouldCreate)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: label }, "Already created: "), String(alreadyCreated)), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: label }, "Creation enabled: "), String(flagOn)), data && data.wfirma_pz_doc_id ? /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: label }, "wFirma PZ document: "), data.wfirma_pz_doc_id) : null)
  ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement(
    Btn,
    {
      "data-testid": "execute-pz-refresh",
      onClick: refresh,
      variant: "outline",
      small: true
    },
    "Refresh"
  ), /* @__PURE__ */ React.createElement(
    Btn,
    {
      "data-testid": "execute-pz-button",
      onClick: onExecute,
      disabled: !enabled,
      title: enabled ? "" : reasons.join("; "),
      variant: "primary"
    },
    busy ? "\u27F3 Creating\u2026" : "Create goods receipt in wFirma"
  )), error && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, fontSize: 11, color: "var(--badge-red-text)" } }, error));
}
function GlobalPZLineageCard({ batchId, onToast }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const refresh = React.useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError("");
    try {
      const r = await fetch(
        `/api/v1/pz/lineage/${encodeURIComponent(batchId)}`,
        { headers: window.__apiHeaders ? window.__apiHeaders() : {} }
      );
      if (!r.ok) {
        setError(`HTTP ${r.status}`);
        setData(null);
      } else {
        setData(await r.json());
      }
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [batchId]);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const card = {
    background: "var(--card,#fff)",
    border: "1px solid var(--border,#e5e7eb)",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16
  };
  const h2 = {
    fontSize: 14,
    fontWeight: 700,
    marginBottom: 12,
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap"
  };
  const dimRow = { display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 };
  const statusBadge = (status) => {
    const map = {
      FULL_MATCH: { bg: "#dcfce7", color: "#15803d", label: "FULL MATCH" },
      WARNING_MATCH: { bg: "#fef3c7", color: "#b45309", label: "WARNING MATCH" },
      PARTIAL_MATCH: { bg: "#fee2e2", color: "#991b1b", label: "PARTIAL MATCH" },
      UNMATCHED: { bg: "#fee2e2", color: "#991b1b", label: "UNMATCHED" }
    };
    const s = map[status] || { bg: "#f3f4f6", color: "#374151", label: status || "\u2014" };
    return {
      display: "inline-block",
      padding: "3px 10px",
      borderRadius: 12,
      fontSize: 12,
      fontWeight: 700,
      background: s.bg,
      color: s.color,
      label: s.label
    };
  };
  const dimBadge = (dim) => {
    const map = {
      FULL: { bg: "#dcfce7", color: "#15803d" },
      WARNING: { bg: "#fef3c7", color: "#b45309" },
      PARTIAL: { bg: "#fee2e2", color: "#991b1b" },
      UNMATCHED: { bg: "#fee2e2", color: "#991b1b" },
      "N/A": { bg: "#f3f4f6", color: "#6b7280" }
    };
    const s = map[dim] || { bg: "#f3f4f6", color: "#6b7280" };
    return {
      display: "inline-block",
      padding: "2px 7px",
      borderRadius: 8,
      fontSize: 11,
      fontWeight: 600,
      background: s.bg,
      color: s.color
    };
  };
  const linkRowBg = (status) => {
    if (status === "OVERFLOW" || status === "PARTIAL") return "#fffbeb";
    if (status === "EMPTY") return "#fef2f2";
    return "transparent";
  };
  if (loading) return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-lineage-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F517} Global Jewellery PZ Lineage"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2,#6b7280)" } }, "Loading lineage\u2026"));
  if (error) return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-lineage-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F517} Global Jewellery PZ Lineage"), /* @__PURE__ */ React.createElement(
    "div",
    {
      style: { fontSize: 12, color: "#991b1b" },
      "data-testid": "global-pz-lineage-error"
    },
    "Could not load lineage: ",
    error
  ));
  if (!data || !data.is_global_supplier) return null;
  if (data.error) return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-lineage-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F517} Global Jewellery PZ Lineage"), /* @__PURE__ */ React.createElement(
    "div",
    {
      style: { fontSize: 12, color: "#991b1b" },
      "data-testid": "global-pz-lineage-parse-error"
    },
    "Lineage unavailable: ",
    data.error
  ));
  const overall = data.match_status || "UNMATCHED";
  const ovStyle = statusBadge(overall);
  return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-lineage-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F517} Global Jewellery PZ Lineage", /* @__PURE__ */ React.createElement(
    "span",
    {
      style: {
        display: ovStyle.display,
        padding: ovStyle.padding,
        borderRadius: ovStyle.borderRadius,
        fontSize: ovStyle.fontSize,
        fontWeight: ovStyle.fontWeight,
        background: ovStyle.bg,
        color: ovStyle.color
      },
      "data-testid": "global-pz-lineage-overall-badge"
    },
    ovStyle.label
  ), overall !== "FULL_MATCH" && /* @__PURE__ */ React.createElement(
    "span",
    {
      style: { fontSize: 11, color: "#b45309" },
      "data-testid": "global-pz-lineage-warning-notice"
    },
    "\u26A0 Operator review required before finalising PZ"
  )), /* @__PURE__ */ React.createElement("div", { style: dimRow, "data-testid": "global-pz-lineage-dimensions" }, [
    ["Shipment totals", data.shipment_total_match, "dim-shipment"],
    ["Invoice positions", data.invoice_position_match, "dim-invoice"],
    ["Packing row assign", data.packing_row_assignment_match, "dim-packing"],
    ["PZ visibility", data.pz_line_visibility_match, "dim-pz"]
  ].map(([label, val, tid]) => {
    const s = dimBadge(val || "UNMATCHED");
    return /* @__PURE__ */ React.createElement("div", { key: tid, style: { display: "flex", flexDirection: "column", alignItems: "flex-start" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-2,#6b7280)", marginBottom: 2 } }, label), /* @__PURE__ */ React.createElement("span", { style: s, "data-testid": `global-pz-lineage-${tid}` }, val || "\u2014"));
  })), /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 8,
        fontSize: 11,
        marginBottom: 12,
        padding: 8,
        background: "var(--bg-subtle,#f9fafb)",
        borderRadius: 4
      },
      "data-testid": "global-pz-lineage-totals"
    },
    /* @__PURE__ */ React.createElement("div", null, "Invoice positions: ", /* @__PURE__ */ React.createElement("strong", null, data.invoice_position_count || 0)),
    /* @__PURE__ */ React.createElement("div", null, "Packing rows: ", /* @__PURE__ */ React.createElement("strong", null, data.packing_row_count || 0)),
    /* @__PURE__ */ React.createElement("div", null, "Total inv qty: ", /* @__PURE__ */ React.createElement("strong", null, data.total_invoice_qty || 0)),
    /* @__PURE__ */ React.createElement("div", null, "Total pack qty: ", /* @__PURE__ */ React.createElement("strong", null, data.total_packing_qty || 0)),
    /* @__PURE__ */ React.createElement("div", null, "Invoice FOB: ", /* @__PURE__ */ React.createElement("strong", null, "$", (data.total_invoice_fob_usd || 0).toFixed(2))),
    /* @__PURE__ */ React.createElement("div", null, "Packing FOB: ", /* @__PURE__ */ React.createElement("strong", null, "$", (data.total_packing_fob_usd || 0).toFixed(2)))
  ), (data.position_links || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: {
    fontSize: 11,
    fontWeight: 700,
    marginBottom: 6,
    color: "var(--text-2,#6b7280)"
  } }, "Invoice position links"), /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" }, "data-testid": "global-pz-lineage-links-table" }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: {
    background: "var(--bg-subtle,#f9fafb)",
    borderBottom: "1px solid var(--border,#e5e7eb)"
  } }, ["Pos", "Item", "Unit", "Metal", "Stone", "Inv qty", "Pack qty", "Status", "Reason"].map((h) => /* @__PURE__ */ React.createElement("th", { key: h, style: {
    padding: "4px 6px",
    textAlign: "left",
    fontWeight: 600,
    whiteSpace: "nowrap"
  } }, h)))), /* @__PURE__ */ React.createElement("tbody", null, (data.position_links || []).map((lk, i) => {
    const st = dimBadge(
      lk.match_status === "FULL" ? "FULL" : lk.match_status === "OVERFLOW" ? "WARNING" : lk.match_status === "PARTIAL" ? "PARTIAL" : lk.match_status === "EMPTY" ? "UNMATCHED" : "UNMATCHED"
    );
    return /* @__PURE__ */ React.createElement(
      "tr",
      {
        key: i,
        style: {
          borderBottom: "1px solid var(--border,#e5e7eb)",
          background: linkRowBg(lk.match_status)
        },
        "data-testid": `global-pz-link-row-${i}`
      },
      /* @__PURE__ */ React.createElement("td", { style: { padding: "3px 6px" } }, lk.position_no),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "3px 6px" } }, lk.invoice_item_type),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "3px 6px" } }, lk.unit),
      /* @__PURE__ */ React.createElement("td", { style: {
        padding: "3px 6px",
        maxWidth: 90,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      } }, lk.metal_en),
      /* @__PURE__ */ React.createElement("td", { style: {
        padding: "3px 6px",
        maxWidth: 110,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      } }, lk.stone_en),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "3px 6px", textAlign: "right" } }, lk.invoice_qty),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "3px 6px", textAlign: "right" } }, lk.packing_qty_sum),
      /* @__PURE__ */ React.createElement("td", { style: { padding: "3px 6px" } }, /* @__PURE__ */ React.createElement("span", { style: st }, lk.match_status)),
      /* @__PURE__ */ React.createElement("td", { style: {
        padding: "3px 6px",
        color: "#b45309",
        maxWidth: 200,
        fontSize: 10
      } }, lk.confidence_reason || "")
    );
  }))))), (data.unmatched_packing_serials || []).length > 0 && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "6px 8px",
        background: "#fef2f2",
        borderRadius: 4,
        fontSize: 11,
        marginBottom: 8,
        color: "#991b1b"
      },
      "data-testid": "global-pz-lineage-unmatched"
    },
    "\u26A0 Unmatched packing serials: ",
    (data.unmatched_packing_serials || []).join(", ")
  ), (data.duplicate_assignments || []).length > 0 && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "6px 8px",
        background: "#fef2f2",
        borderRadius: 4,
        fontSize: 11,
        marginBottom: 8,
        color: "#991b1b"
      },
      "data-testid": "global-pz-lineage-duplicates"
    },
    "\u26A0 Duplicate packing serials detected: ",
    (data.duplicate_assignments || []).join(", ")
  ), (data.notes || []).length > 0 && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: { fontSize: 10, color: "var(--text-2,#6b7280)", marginTop: 4 },
      "data-testid": "global-pz-lineage-notes"
    },
    (data.notes || []).map((n, i) => /* @__PURE__ */ React.createElement("div", { key: i }, n))
  ), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, display: "flex", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: refresh,
      style: {
        fontSize: 11,
        padding: "3px 8px",
        cursor: "pointer",
        border: "1px solid var(--border,#e5e7eb)",
        borderRadius: 4,
        background: "var(--bg,#fff)"
      },
      "data-testid": "global-pz-lineage-refresh"
    },
    "Refresh"
  ), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-2,#6b7280)" } }, "Read-only \xB7 no PZ mutation")));
}
function GlobalPZCorrectionProposalCard({ batchId, onToast }) {
  const [proposal, setProposal] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [lcState, setLcState] = React.useState(null);
  const [lifecycleEnabled, setLifecycleEnabled] = React.useState(false);
  const [confirmOpt, setConfirmOpt] = React.useState(null);
  const [reason, setReason] = React.useState("");
  const [executing, setExecuting] = React.useState(false);
  const [execResult, setExecResult] = React.useState(null);
  const [showSuppress, setShowSuppress] = React.useState(false);
  const [suppressReason, setSuppressReason] = React.useState("");
  const [showCommit, setShowCommit] = React.useState(false);
  const [commitReason, setCommitReason] = React.useState("");
  const refresh = React.useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError("");
    setConfirmOpt(null);
    setReason("");
    setExecResult(null);
    setShowSuppress(false);
    setSuppressReason("");
    setShowCommit(false);
    setCommitReason("");
    try {
      const hdrs = window.__apiHeaders ? window.__apiHeaders() : {};
      const [propResp, lcResp] = await Promise.all([
        fetch(`/api/v1/pz/lineage/${encodeURIComponent(batchId)}/correction-proposal`, { headers: hdrs }),
        fetch(`/api/v1/pz/lineage/${encodeURIComponent(batchId)}/correction-state`, { headers: hdrs })
      ]);
      if (!propResp.ok) {
        setError(`HTTP ${propResp.status}`);
        setProposal(null);
      } else {
        setProposal(await propResp.json());
      }
      if (lcResp.status === 503 || lcResp.status === 403) {
        setLifecycleEnabled(false);
        setLcState(null);
      } else if (lcResp.ok) {
        setLifecycleEnabled(true);
        setLcState(await lcResp.json());
      } else {
        setLifecycleEnabled(false);
        setLcState(null);
      }
    } catch (e) {
      setError(String(e));
      setProposal(null);
    } finally {
      setLoading(false);
    }
  }, [batchId]);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const handleStage = React.useCallback(async () => {
    if (!confirmOpt || !reason.trim()) return;
    setExecuting(true);
    try {
      const r = await fetch(
        `/api/v1/pz/lineage/${encodeURIComponent(batchId)}/correction-stage`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...window.__apiHeaders ? window.__apiHeaders() : {} },
          body: JSON.stringify({ option_id: confirmOpt, operator_reason: reason.trim() })
        }
      );
      const json = await r.json();
      if (!r.ok) {
        setExecResult({ ok: false, error: json.detail || `HTTP ${r.status}` });
        onToast && onToast("error", `Stage failed: ${json.detail || r.status}`);
      } else {
        setExecResult({
          ok: true,
          option_id: confirmOpt,
          already_executed: false,
          pre_line_count: null,
          post_line_count: null
        });
        setLcState(json);
        onToast && onToast("success", `Staged: ${confirmOpt}`);
        setConfirmOpt(null);
        setReason("");
      }
    } catch (e) {
      setExecResult({ ok: false, error: String(e) });
      onToast && onToast("error", `Stage error: ${e}`);
    } finally {
      setExecuting(false);
    }
  }, [batchId, confirmOpt, reason, onToast]);
  const handleResetStage = React.useCallback(async () => {
    setExecuting(true);
    try {
      const r = await fetch(
        `/api/v1/pz/lineage/${encodeURIComponent(batchId)}/correction-stage`,
        { method: "DELETE", headers: { ...window.__apiHeaders ? window.__apiHeaders() : {} } }
      );
      const json = await r.json();
      if (!r.ok) {
        onToast && onToast("error", `Reset failed: ${json.detail || r.status}`);
      } else {
        setLcState(json);
        onToast && onToast("info", "Stage reset \u2014 choose a different option");
      }
    } catch (e) {
      onToast && onToast("error", `Reset error: ${e}`);
    } finally {
      setExecuting(false);
    }
  }, [batchId, onToast]);
  const handleSuppress = React.useCallback(async () => {
    if (!suppressReason.trim()) return;
    setExecuting(true);
    try {
      const r = await fetch(
        `/api/v1/pz/lineage/${encodeURIComponent(batchId)}/correction-suppress`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...window.__apiHeaders ? window.__apiHeaders() : {} },
          body: JSON.stringify({ reason: suppressReason.trim() })
        }
      );
      const json = await r.json();
      if (!r.ok) {
        onToast && onToast("error", `Suppress failed: ${json.detail || r.status}`);
      } else {
        setLcState(json);
        setShowSuppress(false);
        setSuppressReason("");
        onToast && onToast("success", "Correction workflow closed (suppressed)");
      }
    } catch (e) {
      onToast && onToast("error", `Suppress error: ${e}`);
    } finally {
      setExecuting(false);
    }
  }, [batchId, suppressReason, onToast]);
  const _CONFIRM_SENTINEL = "I confirm this will create a new wFirma PZ document and cannot be undone without manual wFirma intervention";
  const handleCommit = React.useCallback(async () => {
    if (!commitReason.trim()) return;
    setExecuting(true);
    try {
      const r = await fetch(
        `/api/v1/pz/lineage/${encodeURIComponent(batchId)}/correction-commit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...window.__apiHeaders ? window.__apiHeaders() : {} },
          body: JSON.stringify({
            operator_reason: commitReason.trim(),
            idempotency_key: `${batchId}-${Date.now()}`,
            confirm_understanding: _CONFIRM_SENTINEL
          })
        }
      );
      const json = await r.json();
      if (!r.ok) {
        setExecResult({ ok: false, error: json.detail || `HTTP ${r.status}` });
        onToast && onToast("error", `Commit failed: ${json.detail || r.status}`);
      } else {
        setLcState(json);
        setShowCommit(false);
        setCommitReason("");
        onToast && onToast("success", `PZ committed to wFirma (state: ${json.state})`);
      }
    } catch (e) {
      onToast && onToast("error", `Commit error: ${e}`);
    } finally {
      setExecuting(false);
    }
  }, [batchId, commitReason, onToast]);
  const card = {
    background: "var(--card,#fff)",
    border: "1px solid var(--border,#e5e7eb)",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16
  };
  const h2 = {
    fontSize: 14,
    fontWeight: 700,
    marginBottom: 12,
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap"
  };
  const riskStyle = (level) => {
    const map = {
      NONE: { bg: "#dcfce7", color: "#15803d" },
      LOW: { bg: "#fef3c7", color: "#b45309" },
      MEDIUM: { bg: "#fed7aa", color: "#c2410c" },
      HIGH: { bg: "#fee2e2", color: "#991b1b" }
    };
    const s = map[level] || { bg: "#f3f4f6", color: "#6b7280" };
    return {
      display: "inline-block",
      padding: "2px 7px",
      borderRadius: 8,
      fontSize: 11,
      fontWeight: 600,
      background: s.bg,
      color: s.color
    };
  };
  const recStyle = (optionId) => {
    if (optionId === "KEEP_CURRENT") return { bg: "#dcfce7", color: "#15803d", label: "KEEP CURRENT" };
    if (optionId === "NO_ACTION") return { bg: "#f3f4f6", color: "#374151", label: "NO ACTION" };
    return { bg: "#fef3c7", color: "#b45309", label: optionId };
  };
  const stateColors = {
    PROPOSED: { bg: "#f3f4f6", color: "#374151" },
    OPERATOR_REVIEWED: { bg: "#eff6ff", color: "#1d4ed8" },
    STAGED: { bg: "#fef3c7", color: "#b45309" },
    EXECUTING: { bg: "#fff7ed", color: "#c2410c" },
    COMPLETED: { bg: "#dcfce7", color: "#15803d" },
    FAILED: { bg: "#fee2e2", color: "#991b1b" },
    TERMINAL_SUPPRESSED: { bg: "#f3f4f6", color: "#6b7280" }
  };
  const optionButtonLabel = (opt) => {
    if (opt.option_id === "KEEP_CURRENT") return "Close (keep current)";
    if (opt.option_id === "ALIGN_TO_AUTHORITY") return "Align to authority";
    if (opt.option_id === "SPLIT_TO_STYLE_LEVEL") return "Split to style level";
    if (opt.option_id === "NO_ACTION") return "Close (no action)";
    return opt.option_id;
  };
  if (loading) return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-correction-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u2699 PZ Correction Proposal"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2,#6b7280)" } }, "Loading proposal\u2026"));
  if (error) {
    if (error === "HTTP 404") return null;
    return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-correction-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u2699 PZ Correction Proposal"), /* @__PURE__ */ React.createElement(
      "div",
      {
        style: { fontSize: 12, color: "#991b1b" },
        "data-testid": "global-pz-correction-error"
      },
      "Could not load correction proposal: ",
      error
    ));
  }
  if (!proposal || !proposal.is_global_supplier) return null;
  const rec = proposal.recommended_option || "KEEP_CURRENT";
  const recS = recStyle(rec);
  const options = (proposal.options || []).filter((o) => o.option_id !== "CANCEL_AND_RECREATE");
  const lcSt = lcState ? lcState.state : null;
  const scol = lcSt ? stateColors[lcSt] || stateColors.PROPOSED : null;
  const isTerminal = lcSt === "COMPLETED" || lcSt === "TERMINAL_SUPPRESSED";
  const isStaged = lcSt === "STAGED";
  const isFailed = lcSt === "FAILED";
  return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "global-pz-correction-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u2699 PZ Correction Proposal", /* @__PURE__ */ React.createElement(
    "span",
    {
      style: {
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 12,
        fontSize: 12,
        fontWeight: 700,
        background: recS.bg,
        color: recS.color
      },
      "data-testid": "global-pz-correction-recommended-badge"
    },
    recS.label
  ), lifecycleEnabled && lcSt && /* @__PURE__ */ React.createElement(
    "span",
    {
      style: {
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 8,
        fontSize: 11,
        fontWeight: 600,
        background: scol.bg,
        color: scol.color
      },
      "data-testid": "global-pz-correction-lifecycle-state"
    },
    lcSt
  ), /* @__PURE__ */ React.createElement(
    "span",
    {
      style: { fontSize: 11, color: "var(--text-2,#6b7280)", fontWeight: 400 },
      "data-testid": "global-pz-correction-readonly-label"
    },
    "No wFirma mutation \xB7 local staging only"
  )), !lifecycleEnabled && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "7px 10px",
        borderRadius: 6,
        fontSize: 11,
        marginBottom: 12,
        background: "#fff7ed",
        color: "#c2410c",
        border: "1px solid #fed7aa"
      },
      "data-testid": "global-pz-correction-lifecycle-disabled"
    },
    "Lifecycle mode not enabled. Stage/commit actions unavailable. Set ",
    /* @__PURE__ */ React.createElement("code", null, "pz_correction_lifecycle_enabled=true"),
    " in .env to enable."
  ), /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(3,1fr)",
        gap: 8,
        fontSize: 11,
        marginBottom: 14,
        padding: 8,
        background: "var(--bg-subtle,#f9fafb)",
        borderRadius: 4
      },
      "data-testid": "global-pz-correction-stats"
    },
    /* @__PURE__ */ React.createElement("div", null, "Current PZ lines: ", /* @__PURE__ */ React.createElement("strong", null, proposal.current_pz_line_count ?? "\u2014")),
    /* @__PURE__ */ React.createElement("div", null, "Authority rows: ", /* @__PURE__ */ React.createElement("strong", null, proposal.authority_row_count ?? "\u2014")),
    /* @__PURE__ */ React.createElement("div", null, "Lineage links: ", /* @__PURE__ */ React.createElement("strong", null, proposal.lineage_link_count ?? "\u2014"))
  ), rec === "KEEP_CURRENT" && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "8px 12px",
        background: "#f0fdf4",
        borderRadius: 6,
        fontSize: 12,
        color: "#15803d",
        marginBottom: 12,
        border: "1px solid #bbf7d0"
      },
      "data-testid": "global-pz-correction-keep-notice"
    },
    "Existing PZ can remain. Lineage explains the grouped structure."
  ), isTerminal && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "8px 12px",
        borderRadius: 6,
        fontSize: 12,
        marginBottom: 12,
        background: lcSt === "COMPLETED" ? "#f0fdf4" : "#f3f4f6",
        color: lcSt === "COMPLETED" ? "#15803d" : "#6b7280",
        border: `1px solid ${lcSt === "COMPLETED" ? "#bbf7d0" : "#e5e7eb"}`
      },
      "data-testid": "global-pz-correction-terminal-banner"
    },
    lcSt === "COMPLETED" ? `\u2713 Correction complete. wFirma PZ created.${lcState.result_summary ? ` (${lcState.result_summary})` : ""}` : `Correction workflow closed (suppressed). Reason: ${lcState.suppression_reason || "\u2014"}`
  ), isStaged && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "8px 12px",
        borderRadius: 6,
        fontSize: 12,
        marginBottom: 12,
        background: "#fef3c7",
        border: "1px solid #fde68a",
        color: "#92400e"
      },
      "data-testid": "global-pz-correction-staged-banner"
    },
    "Staged option: ",
    /* @__PURE__ */ React.createElement("strong", null, lcState.staged_option_id),
    " \xB7 Ready to commit to wFirma or reset."
  ), lcSt === "EXECUTING" && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "8px 12px",
        borderRadius: 6,
        fontSize: 12,
        marginBottom: 12,
        background: "#fff7ed",
        border: "1px solid #fed7aa",
        color: "#c2410c"
      },
      "data-testid": "global-pz-correction-executing-banner"
    },
    "\u23F3 wFirma push in progress\u2026 Refresh to check status."
  ), isFailed && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "8px 12px",
        borderRadius: 6,
        fontSize: 12,
        marginBottom: 12,
        background: "#fef2f2",
        border: "1px solid #fecaca",
        color: "#991b1b"
      },
      "data-testid": "global-pz-correction-failed-banner"
    },
    "Push failed: ",
    lcState.result_summary || "unknown error",
    ". Reset stage to retry with a different option, or suppress to close."
  ), execResult && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "8px 12px",
        borderRadius: 6,
        fontSize: 12,
        marginBottom: 12,
        background: execResult.ok ? "#f0fdf4" : "#fef2f2",
        color: execResult.ok ? "#15803d" : "#991b1b",
        border: `1px solid ${execResult.ok ? "#bbf7d0" : "#fecaca"}`
      },
      "data-testid": "global-pz-correction-result"
    },
    execResult.ok ? execResult.already_executed ? "Already executed \u2014 returning existing record." : `Staged: ${execResult.option_id}. Lines: ${execResult.pre_line_count ?? "\u2014"} \u2192 ${execResult.post_line_count ?? "\u2014"}.` : `Stage failed: ${execResult.error}`
  ), !isTerminal && !isStaged && lcSt !== "EXECUTING" && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: { display: "flex", flexDirection: "column", gap: 8 },
      "data-testid": "global-pz-correction-options"
    },
    options.map((opt) => {
      const lbl = optionButtonLabel(opt);
      const isRec = opt.option_id === rec;
      const isPending = confirmOpt === opt.option_id;
      const isNoOp = opt.option_id === "KEEP_CURRENT" || opt.option_id === "NO_ACTION";
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: opt.option_id,
          style: {
            padding: "8px 10px",
            borderRadius: 6,
            border: `1px solid ${isPending ? "#93c5fd" : "var(--border,#e5e7eb)"}`,
            background: isPending ? "#eff6ff" : isRec ? "var(--bg-subtle,#f9fafb)" : "transparent"
          },
          "data-testid": `global-pz-correction-option-${opt.option_id}`
        },
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "flex-start", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700 } }, opt.label), isRec && /* @__PURE__ */ React.createElement("span", { style: {
          fontSize: 10,
          background: "#dcfce7",
          color: "#15803d",
          borderRadius: 4,
          padding: "1px 5px",
          fontWeight: 600
        } }, "Recommended"), /* @__PURE__ */ React.createElement(
          "span",
          {
            style: riskStyle(opt.risk_level),
            "data-testid": `global-pz-correction-risk-${opt.option_id}`
          },
          opt.risk_level || "NONE"
        )), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2,#6b7280)" } }, opt.description), (opt.notes || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "#b45309", marginTop: 3 } }, opt.notes.map((n, i) => /* @__PURE__ */ React.createElement("div", { key: i }, n)))), /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0 } }, isNoOp ? (
          /* KEEP_CURRENT / NO_ACTION → open suppress panel directly */
          /* @__PURE__ */ React.createElement(
            "button",
            {
              onClick: () => {
                setShowSuppress(true);
                setSuppressReason(`Operator chose ${opt.option_id} \u2014 no wFirma push needed`);
              },
              disabled: executing || !lifecycleEnabled,
              style: {
                fontSize: 11,
                padding: "4px 10px",
                borderRadius: 4,
                cursor: executing || !lifecycleEnabled ? "not-allowed" : "pointer",
                border: "1px solid var(--border,#e5e7eb)",
                background: "var(--bg,#fff)",
                color: "var(--text,#111)",
                opacity: executing || !lifecycleEnabled ? 0.6 : 1
              },
              "data-testid": `global-pz-correction-btn-${opt.option_id}`
            },
            lbl
          )
        ) : (
          /* ALIGN_TO_AUTHORITY / SPLIT_TO_STYLE_LEVEL → open stage confirmation */
          /* @__PURE__ */ React.createElement(
            "button",
            {
              onClick: () => setConfirmOpt(isPending ? null : opt.option_id),
              disabled: executing || !lifecycleEnabled,
              style: {
                fontSize: 11,
                padding: "4px 10px",
                borderRadius: 4,
                cursor: executing || !lifecycleEnabled ? "not-allowed" : "pointer",
                border: `1px solid ${isPending ? "#3b82f6" : "var(--border,#e5e7eb)"}`,
                background: isPending ? "#3b82f6" : "var(--bg,#fff)",
                color: isPending ? "#fff" : "var(--text,#111)",
                opacity: executing || !lifecycleEnabled ? 0.6 : 1
              },
              "data-testid": `global-pz-correction-btn-${opt.option_id}`
            },
            isPending ? "Cancel" : lbl
          )
        ))),
        isPending && !isNoOp && /* @__PURE__ */ React.createElement(
          "div",
          {
            style: {
              marginTop: 10,
              padding: "10px 12px",
              background: "#fff",
              borderRadius: 6,
              border: "1px solid #bfdbfe"
            },
            "data-testid": "global-pz-correction-confirm-modal"
          },
          /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, marginBottom: 6 } }, "Confirm stage: ", opt.option_id),
          /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#374151", marginBottom: 8 } }, "This will write to local ", /* @__PURE__ */ React.createElement("code", null, "pz_rows.json"), " only. No wFirma calls. wFirma push is a separate operator step. A backup will be created automatically."),
          /* @__PURE__ */ React.createElement(
            "textarea",
            {
              placeholder: "Operator reason (required)\u2026",
              value: reason,
              onChange: (e) => setReason(e.target.value),
              rows: 2,
              style: {
                width: "100%",
                fontSize: 11,
                padding: "4px 6px",
                borderRadius: 4,
                border: "1px solid #d1d5db",
                resize: "vertical",
                boxSizing: "border-box"
              },
              "data-testid": "global-pz-correction-reason-input"
            }
          ),
          /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginTop: 6 } }, /* @__PURE__ */ React.createElement(
            "button",
            {
              onClick: handleStage,
              disabled: executing || !reason.trim(),
              style: {
                fontSize: 11,
                padding: "4px 12px",
                borderRadius: 4,
                cursor: executing || !reason.trim() ? "not-allowed" : "pointer",
                background: "#2563eb",
                color: "#fff",
                border: "none",
                opacity: executing || !reason.trim() ? 0.5 : 1
              },
              "data-testid": "global-pz-correction-confirm-btn"
            },
            executing ? "Staging\u2026" : "Confirm stage"
          ), /* @__PURE__ */ React.createElement(
            "button",
            {
              onClick: () => {
                setConfirmOpt(null);
                setReason("");
              },
              disabled: executing,
              style: {
                fontSize: 11,
                padding: "4px 10px",
                borderRadius: 4,
                cursor: "pointer",
                border: "1px solid var(--border,#e5e7eb)",
                background: "var(--bg,#fff)"
              },
              "data-testid": "global-pz-correction-cancel-btn"
            },
            "Cancel"
          ))
        )
      );
    })
  ), lifecycleEnabled && isStaged && /* @__PURE__ */ React.createElement(
    "div",
    {
      style: { marginTop: 12, display: "flex", flexDirection: "column", gap: 8 },
      "data-testid": "global-pz-correction-staged-actions"
    },
    !showCommit ? /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setShowCommit(true),
        disabled: executing,
        style: {
          fontSize: 11,
          padding: "6px 14px",
          borderRadius: 4,
          cursor: "pointer",
          background: "#15803d",
          color: "#fff",
          border: "none",
          opacity: executing ? 0.5 : 1
        },
        "data-testid": "global-pz-correction-commit-btn"
      },
      "Commit to wFirma\u2026"
    ) : /* @__PURE__ */ React.createElement(
      "div",
      {
        style: {
          padding: "10px 12px",
          background: "#f0fdf4",
          borderRadius: 6,
          border: "1px solid #bbf7d0"
        },
        "data-testid": "global-pz-correction-commit-panel"
      },
      /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, marginBottom: 4, color: "#166534" } }, "Commit staged correction to wFirma"),
      /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 11,
        color: "#374151",
        marginBottom: 6,
        background: "#fef3c7",
        padding: "6px 8px",
        borderRadius: 4,
        border: "1px solid #fde68a"
      } }, "\u26A0 This will create a new wFirma PZ document. This cannot be undone without manual wFirma intervention."),
      /* @__PURE__ */ React.createElement(
        "textarea",
        {
          placeholder: "Operator reason (required)\u2026",
          value: commitReason,
          onChange: (e) => setCommitReason(e.target.value),
          rows: 2,
          style: {
            width: "100%",
            fontSize: 11,
            padding: "4px 6px",
            borderRadius: 4,
            border: "1px solid #d1d5db",
            resize: "vertical",
            boxSizing: "border-box"
          },
          "data-testid": "global-pz-correction-commit-reason-input"
        }
      ),
      /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginTop: 6 } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: handleCommit,
          disabled: executing || !commitReason.trim(),
          style: {
            fontSize: 11,
            padding: "4px 12px",
            borderRadius: 4,
            cursor: executing || !commitReason.trim() ? "not-allowed" : "pointer",
            background: "#15803d",
            color: "#fff",
            border: "none",
            opacity: executing || !commitReason.trim() ? 0.5 : 1
          },
          "data-testid": "global-pz-correction-commit-confirm-btn"
        },
        executing ? "Committing\u2026" : "Confirm commit to wFirma"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => {
            setShowCommit(false);
            setCommitReason("");
          },
          disabled: executing,
          style: {
            fontSize: 11,
            padding: "4px 10px",
            borderRadius: 4,
            cursor: "pointer",
            border: "1px solid var(--border,#e5e7eb)",
            background: "var(--bg,#fff)"
          },
          "data-testid": "global-pz-correction-commit-cancel-btn"
        },
        "Cancel"
      ))
    ),
    /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: handleResetStage,
        disabled: executing,
        style: {
          fontSize: 11,
          padding: "4px 10px",
          borderRadius: 4,
          cursor: "pointer",
          border: "1px solid var(--border,#e5e7eb)",
          background: "var(--bg,#fff)",
          opacity: executing ? 0.5 : 1
        },
        "data-testid": "global-pz-correction-reset-stage-btn"
      },
      "\u2190 Change option (reset stage)"
    )
  ), lifecycleEnabled && !isTerminal && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10 } }, !showSuppress ? /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: () => setShowSuppress(true),
      disabled: executing,
      style: {
        fontSize: 10,
        padding: "3px 8px",
        cursor: "pointer",
        border: "1px solid var(--border,#e5e7eb)",
        borderRadius: 4,
        background: "var(--bg,#fff)",
        color: "var(--text-2,#6b7280)",
        opacity: executing ? 0.5 : 1
      },
      "data-testid": "global-pz-correction-suppress-btn"
    },
    "Close workflow without wFirma push\u2026"
  ) : /* @__PURE__ */ React.createElement(
    "div",
    {
      style: {
        padding: "10px 12px",
        background: "#fef2f2",
        borderRadius: 6,
        border: "1px solid #fecaca"
      },
      "data-testid": "global-pz-correction-suppress-panel"
    },
    /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, marginBottom: 4, color: "#991b1b" } }, "Close correction workflow (no wFirma push)"),
    /* @__PURE__ */ React.createElement(
      "textarea",
      {
        placeholder: "Reason for closing (required)\u2026",
        value: suppressReason,
        onChange: (e) => setSuppressReason(e.target.value),
        rows: 2,
        style: {
          width: "100%",
          fontSize: 11,
          padding: "4px 6px",
          borderRadius: 4,
          border: "1px solid #fca5a5",
          resize: "vertical",
          boxSizing: "border-box"
        },
        "data-testid": "global-pz-correction-suppress-reason-input"
      }
    ),
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginTop: 6 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: handleSuppress,
        disabled: executing || !suppressReason.trim(),
        style: {
          fontSize: 11,
          padding: "4px 12px",
          borderRadius: 4,
          cursor: executing || !suppressReason.trim() ? "not-allowed" : "pointer",
          background: "#dc2626",
          color: "#fff",
          border: "none",
          opacity: executing || !suppressReason.trim() ? 0.5 : 1
        },
        "data-testid": "global-pz-correction-suppress-confirm-btn"
      },
      executing ? "Closing\u2026" : "Confirm close"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          setShowSuppress(false);
          setSuppressReason("");
        },
        disabled: executing,
        style: {
          fontSize: 11,
          padding: "4px 10px",
          borderRadius: 4,
          cursor: "pointer",
          border: "1px solid var(--border,#e5e7eb)",
          background: "var(--bg,#fff)"
        },
        "data-testid": "global-pz-correction-suppress-cancel-btn"
      },
      "Cancel"
    ))
  )), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, display: "flex", gap: 8, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: refresh,
      style: {
        fontSize: 11,
        padding: "3px 8px",
        cursor: "pointer",
        border: "1px solid var(--border,#e5e7eb)",
        borderRadius: 4,
        background: "var(--bg,#fff)"
      },
      "data-testid": "global-pz-correction-refresh"
    },
    "Refresh"
  ), /* @__PURE__ */ React.createElement(
    "span",
    {
      style: { fontSize: 10, color: "var(--text-2,#6b7280)" },
      "data-testid": "global-pz-correction-readonly-label"
    },
    "No wFirma mutation \xB7 local staging only"
  )));
}
function ZC429EvidenceCard({ batchId, onToast }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const refresh = React.useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError("");
    try {
      const r = await fetch(
        `/dashboard/batches/${encodeURIComponent(batchId)}/zc429-lineage`,
        { headers: window.__apiHeaders ? window.__apiHeaders() : {} }
      );
      if (!r.ok) {
        setError(`HTTP ${r.status}`);
        setData(null);
      } else {
        setData(await r.json());
      }
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [batchId]);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const card = {
    background: "var(--card,#fff)",
    border: "1px solid var(--border,#e5e7eb)",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16
  };
  const h2 = {
    fontSize: 14,
    fontWeight: 700,
    marginBottom: 12,
    display: "flex",
    alignItems: "center",
    gap: 8
  };
  const chip = (color) => ({
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 12,
    fontSize: 11,
    fontWeight: 700,
    background: color === "green" ? "#dcfce7" : color === "amber" ? "#fef3c7" : "#fee2e2",
    color: color === "green" ? "#15803d" : color === "amber" ? "#b45309" : "#991b1b"
  });
  const grid = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 8,
    marginBottom: 12
  };
  const kv = { fontSize: 12 };
  const label = { color: "var(--text-2,#6b7280)", fontSize: 11, marginBottom: 2 };
  const mono = { fontFamily: "ui-monospace,Menlo,monospace", fontSize: 11 };
  if (loading) {
    return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "zc429-evidence-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F4DC} ZC429 / SAD Evidence"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--text-2,#6b7280)" } }, "Loading evidence chain\u2026"));
  }
  if (error) {
    return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "zc429-evidence-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F4DC} ZC429 / SAD Evidence"), /* @__PURE__ */ React.createElement(
      "div",
      {
        style: { fontSize: 12, color: "#991b1b" },
        "data-testid": "zc429-evidence-error"
      },
      "Could not load evidence chain: ",
      error
    ));
  }
  if (!data || !data.has_zc429) {
    const rs = data && data.recovery_state || "email_not_found";
    const rd = data && data.recovery_detail || {};
    const stateLabel = {
      email_not_found: "No plwawecs email yet",
      email_found_no_attachments: "Email found \xB7 attachments missing",
      email_found_attachments_pending_intake: "Attachments stored \xB7 intake pending",
      intake_completed: "Complete"
    }[rs] || "Not received";
    const stateColor = rs === "email_not_found" ? "amber" : rs === "email_found_no_attachments" || rs === "email_found_attachments_pending_intake" ? "amber" : "amber";
    return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "zc429-evidence-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F4DC} ZC429 / SAD Evidence", /* @__PURE__ */ React.createElement("span", { style: chip(stateColor), "data-testid": "zc429-status-chip" }, stateLabel)), /* @__PURE__ */ React.createElement(
      "div",
      {
        style: { fontSize: 12, color: "var(--text-2,#6b7280)" },
        "data-testid": "zc429-waiting-message"
      },
      "Waiting for DHL ZC429 / SAD email. The legal-evidence chain will appear here as soon as the WAW agency notification is ingested."
    ), /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "zc429-recovery-state",
        "data-recovery-state": rs,
        style: {
          marginTop: 10,
          padding: 8,
          fontSize: 11,
          background: "#fffbeb",
          border: "1px solid #fcd34d",
          borderRadius: 6,
          color: "#92400e"
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, marginBottom: 4 } }, "Recovery state: ", /* @__PURE__ */ React.createElement("span", { "data-testid": "zc429-recovery-state-name" }, rs)),
      /* @__PURE__ */ React.createElement("div", { "data-testid": "zc429-recovery-instruction" }, rd.instruction || ""),
      /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4, color: "#78350f" } }, "plwawecs messages: ", /* @__PURE__ */ React.createElement("strong", { "data-testid": "zc429-recovery-msgs" }, rd.plwawecs_messages_found || 0), " \xB7 ", "attachments stored: ", /* @__PURE__ */ React.createElement("strong", { "data-testid": "zc429-recovery-atts" }, rd.attachments_in_evidence || 0), " \xB7 ", "lineage rows: ", /* @__PURE__ */ React.createElement("strong", { "data-testid": "zc429-recovery-lineage" }, rd.lineage_rows || 0)),
      /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, fontSize: 10, color: "#b91c1c" } }, "\u26A0 Never use the printed-email PDF as a substitute for real attachment binaries. Backfill must use the original downloaded files.")
    ), data && data.warnings && data.warnings.length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "zc429-warnings", style: { marginTop: 10 } }, data.warnings.map((w, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 11, color: "#b45309" } }, "\u26A0\uFE0F ", w))));
  }
  const counts = data.classified_counts || {};
  const ev = data.event || {};
  const sha = (s) => (s || "").slice(0, 12);
  return /* @__PURE__ */ React.createElement("div", { style: card, "data-testid": "zc429-evidence-card" }, /* @__PURE__ */ React.createElement("div", { style: h2 }, "\u{1F4DC} ZC429 / SAD Evidence", /* @__PURE__ */ React.createElement("span", { style: chip("green"), "data-testid": "zc429-status-chip" }, "ZC429 received")), /* @__PURE__ */ React.createElement("div", { style: grid, "data-testid": "zc429-event-block" }, /* @__PURE__ */ React.createElement("div", { style: kv }, /* @__PURE__ */ React.createElement("div", { style: label }, "AWB"), /* @__PURE__ */ React.createElement("div", { style: mono }, ev.awb || "\u2014")), /* @__PURE__ */ React.createElement("div", { style: kv }, /* @__PURE__ */ React.createElement("div", { style: label }, "ZC / MRN"), /* @__PURE__ */ React.createElement("div", { style: mono }, ev.zc_number || "\u2014")), /* @__PURE__ */ React.createElement("div", { style: kv }, /* @__PURE__ */ React.createElement("div", { style: label }, "Sender"), /* @__PURE__ */ React.createElement("div", null, ev.sender || "\u2014")), /* @__PURE__ */ React.createElement("div", { style: kv }, /* @__PURE__ */ React.createElement("div", { style: label }, "Received"), /* @__PURE__ */ React.createElement("div", null, ev.received_at || "\u2014")), /* @__PURE__ */ React.createElement("div", { style: kv }, /* @__PURE__ */ React.createElement("div", { style: label }, "Intake event"), /* @__PURE__ */ React.createElement("div", { style: mono, title: data.intake_event_id }, sha(data.intake_event_id), "\u2026")), /* @__PURE__ */ React.createElement("div", { style: kv }, /* @__PURE__ */ React.createElement("div", { style: label }, "Processing version"), /* @__PURE__ */ React.createElement("div", { style: mono }, ev.processing_version || "\u2014"))), /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "zc429-classified-counts",
      style: {
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
        marginBottom: 12,
        fontSize: 12
      }
    },
    /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("b", null, counts.zc429 || 0), " ZC429"),
    /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("b", null, counts.awb || 0), " AWB"),
    /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("b", null, counts.invoices || 0), " invoices"),
    /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("b", null, counts.mail_evidence || 0), " mail evidence"),
    /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("b", null, counts.others || 0), " others"),
    /* @__PURE__ */ React.createElement("div", { style: { marginLeft: "auto", color: "var(--text-2,#6b7280)" } }, "Total attachments: ", /* @__PURE__ */ React.createElement("b", null, (data.attachments || []).length))
  ), /* @__PURE__ */ React.createElement("div", { "data-testid": "zc429-attachments", style: { marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: label }, "Attachments"), /* @__PURE__ */ React.createElement("div", { style: {
    maxHeight: 220,
    overflowY: "auto",
    border: "1px solid var(--border,#e5e7eb)",
    borderRadius: 6
  } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 11 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--bg-soft,#f9fafb)" } }, /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: "6px 8px" } }, "Filename"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: "6px 8px" } }, "Type"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "right", padding: "6px 8px" } }, "Size"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: "6px 8px" } }, "SHA256"))), /* @__PURE__ */ React.createElement("tbody", null, (data.attachments || []).map((a, i) => /* @__PURE__ */ React.createElement(
    "tr",
    {
      key: i,
      "data-testid": `zc429-att-${i}`,
      style: { borderTop: "1px solid var(--border,#e5e7eb)" }
    },
    /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 8px" }, title: a.stored_path }, a.filename),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 8px" } }, a.classified_type),
    /* @__PURE__ */ React.createElement("td", { style: { padding: "6px 8px", textAlign: "right" } }, (a.size || 0).toLocaleString(), " B"),
    /* @__PURE__ */ React.createElement(
      "td",
      {
        style: { ...mono, padding: "6px 8px" },
        title: a.sha256
      },
      sha(a.sha256),
      "\u2026"
    )
  )))))), /* @__PURE__ */ React.createElement("div", { "data-testid": "zc429-processing-history", style: { marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: label }, "Processing history"), (data.processing_history || []).length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2,#6b7280)" } }, "(no entries)") : /* @__PURE__ */ React.createElement("ul", { style: { margin: 0, paddingLeft: 18, fontSize: 11 } }, data.processing_history.map((h, i) => /* @__PURE__ */ React.createElement("li", { key: i }, /* @__PURE__ */ React.createElement("span", { style: mono }, h.created_at), " \u2014 ", h.note, h.actor ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-2,#6b7280)" } }, " (", h.actor, ")") : null)))), /* @__PURE__ */ React.createElement("div", { "data-testid": "zc429-linked-timeline" }, /* @__PURE__ */ React.createElement("div", { style: label }, "Linked timeline events"), (data.linked_timeline_events || []).length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-2,#6b7280)" } }, "(none)") : /* @__PURE__ */ React.createElement("ul", { style: { margin: 0, paddingLeft: 18, fontSize: 11 } }, data.linked_timeline_events.map((e, i) => /* @__PURE__ */ React.createElement("li", { key: i }, /* @__PURE__ */ React.createElement("span", { style: mono }, e.ts), " \u2014 ", /* @__PURE__ */ React.createElement("b", null, e.event), e.trigger_source ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-2,#6b7280)" } }, " via ", e.trigger_source) : null)))), (data.warnings || []).length > 0 && /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "zc429-warnings",
      style: {
        marginTop: 12,
        padding: 8,
        background: "#fef3c7",
        borderRadius: 6
      }
    },
    data.warnings.map((w, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 11, color: "#b45309" } }, "\u26A0\uFE0F ", w))
  ));
}
function ProformaReadinessCard({ batchId, onToast }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState("");
  const [custInputs, setCustInputs] = React.useState({});
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}/proforma-readiness`);
      setData(d);
    } catch (e) {
      onToast && onToast("Failed to load Proforma readiness: " + e.message, "error");
    }
    setLoading(false);
  }, [batchId, onToast]);
  React.useEffect(() => {
    refresh();
  }, [refresh]);
  const runAction = async (label, fn) => {
    setBusy(label);
    try {
      const r = await fn();
      if (r && r.status) {
        onToast && onToast(`${label}: ${r.status}`, r.status === "created" || r.status === "sent" ? "success" : "info");
      } else if (Array.isArray(r) || typeof r === "object") {
        onToast && onToast(`${label}: done`, "success");
      }
      await refresh();
    } catch (e) {
      onToast && onToast(`${label} failed: ${e.message}`, "error");
    }
    setBusy("");
  };
  const previewProducts = () => runAction(
    "Preview product auto-register",
    () => apiFetch(`/api/v1/wfirma/goods/auto-register-preview/${encodeURIComponent(batchId)}`, {
      method: "POST"
    })
  );
  const writeProducts = () => {
    if (!confirm("Auto-register all missing product codes in wFirma? This calls live goods/add for each missing code.")) return;
    return runAction(
      "Auto-register products",
      () => apiFetch(`/api/v1/wfirma/goods/auto-register/${encodeURIComponent(batchId)}`, {
        method: "POST"
      })
    );
  };
  const previewCustomers = () => runAction(
    "Preview customer auto-resolve",
    () => apiFetch(`/api/v1/wfirma/customers/auto-resolve-preview/${encodeURIComponent(batchId)}`, {
      method: "POST"
    })
  );
  const createCustomer = (clientName) => {
    const inp = custInputs[clientName] || {};
    if (!confirm(`Create wFirma contractor for "${clientName}"? VAT="${inp.vat_id || ""}" Country="${inp.country_code || ""}"`)) return;
    return runAction(
      `Create customer "${clientName}"`,
      () => apiFetch("/api/v1/wfirma/customers/auto-create-from-name", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_name: clientName,
          vat_id: (inp.vat_id || "").trim(),
          country_code: (inp.country_code || "").trim()
        })
      })
    );
  };
  const setCustField = (clientName, field, value) => {
    setCustInputs((prev) => ({
      ...prev,
      [clientName]: { ...prev[clientName] || {}, [field]: value }
    }));
  };
  if (loading || !data) {
    return /* @__PURE__ */ React.createElement(Card, null, /* @__PURE__ */ React.createElement(SectionHeader, { icon: "\u25C7", title: "Proforma Readiness", subtitle: "Identity-resolution checks for this batch" }), /* @__PURE__ */ React.createElement("div", { style: { padding: 20, color: "var(--text-3)", fontSize: 12 } }, "Loading\u2026"));
  }
  const products = data.products || {};
  const customers = data.customers || {};
  const bridge = data.bridge || {};
  const pz = data.pz || {};
  const proforma = data.proforma || {};
  return /* @__PURE__ */ React.createElement(Card, { style: { marginBottom: 16 } }, /* @__PURE__ */ React.createElement(
    SectionHeader,
    {
      icon: "\u25C7",
      title: "Proforma Readiness",
      subtitle: "Identity-resolution checks for this batch",
      status: proforma.ready ? "Ready" : "Blocked"
    }
  ), /* @__PURE__ */ React.createElement("div", { "data-testid": "proforma-verdict", style: {
    padding: "12px 16px",
    background: proforma.ready ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
    borderTop: "1px solid var(--card-border)",
    borderBottom: "1px solid var(--card-border)",
    fontSize: 12,
    fontWeight: 600,
    color: proforma.ready ? "var(--badge-green-text)" : "var(--badge-amber-text)"
  } }, /* @__PURE__ */ React.createElement("div", null, proforma.ready ? "READY for Proforma issuance" : `BLOCKED \u2014 ${(proforma.blocking_reasons || []).length} item(s)`), !proforma.ready && proforma.next_action && /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 400, fontSize: 11, marginTop: 4, color: "var(--text-2)" } }, "Next: ", proforma.next_action)), /* @__PURE__ */ React.createElement("div", { style: { padding: 16, display: "grid", gap: 18 } }, /* @__PURE__ */ React.createElement("section", { "data-testid": "readiness-products" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "1 \xB7 Product Identity"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 12, marginBottom: 8 } }, /* @__PURE__ */ React.createElement(InfoRow, { label: "Total codes", value: products.total ?? 0 }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Mapped to wFirma", value: products.mapped ?? 0 }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Missing", value: products.missing ?? 0 })), !products.create_flag_on && products.missing > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "product-flag-off", style: { fontSize: 11, color: "var(--badge-red-text)", background: "var(--badge-red-bg)", padding: "6px 10px", borderRadius: 4, marginBottom: 8 } }, "Auto-register is not available (contact your admin)"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(Btn, { onClick: previewProducts, disabled: !!busy, small: true }, "Preview product auto-register"), /* @__PURE__ */ React.createElement(Btn, { onClick: writeProducts, disabled: !!busy || !products.create_flag_on || (products.missing ?? 0) === 0, small: true, variant: "primary" }, "Register missing items in accounting"))), /* @__PURE__ */ React.createElement("section", { "data-testid": "readiness-customers" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "2 \xB7 Customer Identity"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 8 } }, /* @__PURE__ */ React.createElement(InfoRow, { label: "Total", value: customers.total ?? 0 }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Resolved", value: customers.resolved ?? 0 }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Missing", value: customers.missing ?? 0 }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Ambiguous", value: customers.ambiguous ?? 0 })), !customers.create_flag_on && customers.missing > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "customer-flag-off", style: { fontSize: 11, color: "var(--badge-amber-text)", background: "var(--badge-amber-bg)", padding: "8px 10px", borderRadius: 4, marginBottom: 8, lineHeight: 1.5 } }, /* @__PURE__ */ React.createElement("b", null, "Action required:"), ' The clients listed as "missing" below have no wFirma contractor record.', " ", "You must create them manually in ", /* @__PURE__ */ React.createElement("b", null, "wFirma \u2192 Contractors \u2192 New contractor"), " (using the same name and VAT number as shown), then click ", /* @__PURE__ */ React.createElement("b", null, "Preview customer auto-resolve"), " above to retry the match."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, marginBottom: 12 } }, /* @__PURE__ */ React.createElement(Btn, { onClick: previewCustomers, disabled: !!busy, small: true }, "Preview customer auto-resolve")), (customers.details || []).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--badge-neutral-bg)" } }, /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: 6, fontWeight: 700, color: "var(--text-3)", fontSize: 10, textTransform: "uppercase" } }, "Client"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: 6, fontWeight: 700, color: "var(--text-3)", fontSize: 10, textTransform: "uppercase" } }, "Status"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: 6, fontWeight: 700, color: "var(--text-3)", fontSize: 10, textTransform: "uppercase" } }, "VAT"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: 6, fontWeight: 700, color: "var(--text-3)", fontSize: 10, textTransform: "uppercase" } }, "Country"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "right", padding: 6, fontWeight: 700, color: "var(--text-3)", fontSize: 10, textTransform: "uppercase" } }, "Action"))), /* @__PURE__ */ React.createElement("tbody", null, customers.details.map((c, i) => {
    const isMissing = c.status === "missing";
    const isResolved = ["exact_match", "normalized_match", "prefix_match", "reverse_prefix_match"].includes(c.status);
    return /* @__PURE__ */ React.createElement("tr", { key: i, style: { borderBottom: "1px solid var(--card-border)" } }, /* @__PURE__ */ React.createElement("td", { style: { padding: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600 } }, c.client_name), c.matched_name && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, "\u2192 ", c.matched_name), c.ship_to_mode && c.ship_to_mode !== "same_as_bill_to" && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "ship-to-row",
        style: { fontSize: 10, marginTop: 3 }
      },
      /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Odbiorca:\xA0"),
      /* @__PURE__ */ React.createElement("span", { style: {
        display: "inline-block",
        padding: "1px 6px",
        borderRadius: 3,
        fontWeight: 600,
        background: c.ship_to_warning ? "var(--badge-amber-bg)" : "var(--badge-neutral-bg)",
        color: c.ship_to_warning ? "var(--badge-amber-text)" : "var(--text-2)"
      } }, c.ship_to_mode),
      c.ship_to_wfirma_customer_id && /* @__PURE__ */ React.createElement("span", { style: {
        marginLeft: 6,
        fontFamily: "monospace",
        color: "var(--text-2)"
      } }, "id ", c.ship_to_wfirma_customer_id),
      c.ship_to_warning && /* @__PURE__ */ React.createElement("span", { style: {
        marginLeft: 6,
        color: "var(--badge-amber-text)"
      } }, "\u26A0 separate_contractor needs a receiver id")
    )), /* @__PURE__ */ React.createElement("td", { style: { padding: 6 } }, /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-block",
      padding: "2px 6px",
      borderRadius: 3,
      fontSize: 10,
      fontWeight: 700,
      background: isResolved ? "var(--badge-green-bg)" : isMissing ? "var(--badge-red-bg)" : "var(--badge-amber-bg)",
      color: isResolved ? "var(--badge-green-text)" : isMissing ? "var(--badge-red-text)" : "var(--badge-amber-text)"
    } }, c.status)), /* @__PURE__ */ React.createElement("td", { style: { padding: 6 } }, isMissing ? /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: (custInputs[c.client_name] || {}).vat_id || "",
        onChange: (v) => setCustField(c.client_name, "vat_id", v),
        placeholder: "e.g. PL5252812119",
        style: { fontSize: 11, padding: "3px 6px" }
      }
    ) : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-3)" } }, "\u2014")), /* @__PURE__ */ React.createElement("td", { style: { padding: 6 } }, isMissing ? /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: (custInputs[c.client_name] || {}).country_code || "",
        onChange: (v) => setCustField(c.client_name, "country_code", v),
        placeholder: "PL",
        style: { fontSize: 11, padding: "3px 6px", width: 60 }
      }
    ) : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-3)" } }, "\u2014")), /* @__PURE__ */ React.createElement("td", { style: { padding: 6, textAlign: "right" } }, isMissing && /* @__PURE__ */ React.createElement(Btn, { onClick: () => createCustomer(c.client_name), disabled: !!busy, small: true }, "Create")));
  }))))), /* @__PURE__ */ React.createElement("section", { "data-testid": "readiness-bridge" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "3 \xB7 Design \u2192 Product Bridge"), /* @__PURE__ */ React.createElement(InfoRow, { label: "Mappings", value: bridge.design_product_mappings ?? 0 }), bridge.ambiguous_design_codes && Object.keys(bridge.ambiguous_design_codes).length > 0 && /* @__PURE__ */ React.createElement("div", { "data-testid": "bridge-ambiguous", style: { marginTop: 8, padding: 10, background: "var(--badge-amber-bg)", borderRadius: 4, color: "var(--badge-amber-text)", fontSize: 11 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, marginBottom: 4 } }, "Ambiguous design codes"), Object.entries(bridge.ambiguous_design_codes).map(([d, codes]) => /* @__PURE__ */ React.createElement("div", { key: d, style: { fontFamily: "monospace" } }, d, " \u2192 ", (codes || []).join(", "))))), /* @__PURE__ */ React.createElement("section", { "data-testid": "readiness-pz" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "4 \xB7 PZ / SAD prerequisites"), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 8 } }, /* @__PURE__ */ React.createElement(InfoRow, { label: "SAD received", value: pz.sad_received ? "YES" : "NO" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "wFirma PZ doc id", value: pz.wfirma_pz_doc_id || "\u2014", mono: true }), /* @__PURE__ */ React.createElement(InfoRow, { label: "pz_rows.json on disk", value: pz.pz_rows_json_present ? "YES" : "NO" }), /* @__PURE__ */ React.createElement(InfoRow, { label: "Ready for PZ create", value: pz.ready_for_pz_create ? "YES" : "NO" }))), /* @__PURE__ */ React.createElement("section", { "data-testid": "readiness-verdict" }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 } }, "5 \xB7 Proforma verdict"), (proforma.blocking_reasons || []).length === 0 ? /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--badge-green-text)" } }, "No blockers \u2014 Proforma can be issued.") : /* @__PURE__ */ React.createElement("ul", { style: { margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--text-2)" } }, proforma.blocking_reasons.map((r, i) => /* @__PURE__ */ React.createElement("li", { key: i }, r)))), (data.errors || []).length > 0 && /* @__PURE__ */ React.createElement("section", { "data-testid": "readiness-errors", style: { padding: 8, background: "var(--badge-red-bg)", borderRadius: 4, fontSize: 11, color: "var(--badge-red-text)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, marginBottom: 4 } }, "Aggregator errors:"), data.errors.map((e, i) => /* @__PURE__ */ React.createElement("div", { key: i }, "\u2022 ", e)))));
}
const PROFORMA_DRAFT_TOKENS = {
  approve: "YES_APPROVE_LOCAL_PROFORMA_DRAFT",
  reopen: "YES_REOPEN_LOCAL_PROFORMA_DRAFT",
  post: "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"
};
const PROFORMA_DRAFT_EDITABLE_STATES = ["draft", "editing", "post_failed"];
function _draftStateChipColors(state) {
  const map = {
    draft: { bg: "var(--badge-amber-bg)", tx: "var(--badge-amber-text)" },
    editing: { bg: "var(--badge-amber-bg)", tx: "var(--badge-amber-text)" },
    approved: { bg: "var(--badge-blue-bg)", tx: "var(--badge-blue-text)" },
    posting: { bg: "var(--badge-blue-bg)", tx: "var(--badge-blue-text)" },
    posted: { bg: "var(--badge-green-bg)", tx: "var(--badge-green-text)" },
    post_failed: { bg: "var(--badge-red-bg)", tx: "var(--badge-red-text)" },
    cancelled: { bg: "var(--badge-red-bg)", tx: "var(--badge-red-text)" },
    superseded: { bg: "var(--badge-red-bg)", tx: "var(--badge-red-text)" },
    // V1 — adopted-from-audit draft represents a wFirma proforma that
    // already exists; informational (blue), not action-needed.
    adopted_from_audit: { bg: "var(--badge-blue-bg)", tx: "var(--badge-blue-text)" }
  };
  return map[state] || { bg: "var(--badge-amber-bg)", tx: "var(--badge-amber-text)" };
}
const _DRAFT_STATE_LABELS = {
  draft: "Draft",
  editing: "Editing",
  approved: "Locked for posting",
  posting: "Sending\u2026",
  posted: "Sent to accounting",
  post_failed: "Send failed",
  cancelled: "Cancelled",
  superseded: "Replaced",
  adopted_from_audit: "Adopted from wFirma"
};
function ProformaDraftStateChip({ state }) {
  const c = _draftStateChipColors(state);
  return /* @__PURE__ */ React.createElement(
    "span",
    {
      "data-testid": `draft-state-chip-${state}`,
      style: {
        background: c.bg,
        color: c.tx,
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.04em"
      }
    },
    _DRAFT_STATE_LABELS[state] || state
  );
}
function parseBulkPriceText(text) {
  const lines = (text || "").split("\n").map((l) => l.trim()).filter(Boolean);
  const prices = [];
  const errors = [];
  const seen = /* @__PURE__ */ new Set();
  for (const line of lines) {
    const idx = line.indexOf(",");
    if (idx === -1) {
      errors.push(`No comma in: ${line}`);
      continue;
    }
    const code = line.slice(0, idx).trim();
    const rawPrice = line.slice(idx + 1).trim();
    if (!code) {
      errors.push(`Empty product_code in: ${line}`);
      continue;
    }
    const up = parseFloat(rawPrice);
    if (isNaN(up) || up <= 0) {
      errors.push(`Invalid price for ${code}: "${rawPrice}" (must be > 0)`);
      continue;
    }
    if (seen.has(code)) {
      errors.push(`Duplicate product_code: ${code}`);
      continue;
    }
    seen.add(code);
    prices.push({ product_code: code, unit_price: up });
  }
  return { ok: errors.length === 0 && prices.length > 0, prices, errors };
}
function ProformaDraftPanel({ batchId, onToast, clientList = [] }) {
  const [drafts, setDrafts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [openId, setOpenId] = React.useState(null);
  const [openDraft, setOpenDraft] = React.useState(null);
  const [openBusy, setOpenBusy] = React.useState(false);
  const [events, setEvents] = React.useState(null);
  const [eventsOpen, setEventsOpen] = React.useState(false);
  const [showLink, setShowLink] = React.useState(false);
  const [packDocs, setPackDocs] = React.useState([]);
  const [packDocsLoading, setPackDocsLoading] = React.useState(false);
  const [clientNames, setClientNames] = React.useState({});
  const [ignoredDocs, setIgnoredDocs] = React.useState(/* @__PURE__ */ new Set());
  const [linkBusy, setLinkBusy] = React.useState(false);
  const refreshList = React.useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiFetch(`/api/v1/proforma/drafts/${encodeURIComponent(batchId)}`);
      setDrafts(d && d.drafts || []);
    } catch (e) {
      onToast && onToast("Failed to load Proforma drafts: " + e.message, "error");
    }
    setLoading(false);
  }, [batchId, onToast]);
  React.useEffect(() => {
    refreshList();
  }, [refreshList]);
  const openOne = React.useCallback(async (draftId) => {
    setOpenId(draftId);
    setOpenBusy(true);
    setEventsOpen(false);
    setEvents(null);
    setBulkPriceText("");
    setBulkPriceResult(null);
    setBulkPriceNeedsConfirm(null);
    setVisibility(null);
    setVisOpen(false);
    try {
      const d = await apiFetch(`/api/v1/proforma/draft/${draftId}`);
      setOpenDraft(d.draft);
      setPriceRecoveryOpen(!!(d.draft && d.draft.needs_pricing_refresh));
    } catch (e) {
      onToast && onToast("Failed to load draft: " + e.message, "error");
      setOpenDraft(null);
    }
    setOpenBusy(false);
  }, [onToast]);
  const closeOne = () => {
    setOpenId(null);
    setOpenDraft(null);
    setEvents(null);
    setEventsOpen(false);
    setVisibility(null);
    setVisOpen(false);
  };
  const loadVisibility = React.useCallback(async () => {
    if (!openId) return;
    try {
      const d = await apiFetch(`/api/v1/proforma/draft/${openId}/visibility`);
      setVisibility(d);
      setVisOpen(true);
    } catch (e) {
      onToast && onToast("Visibility load failed: " + e.message, "error");
    }
  }, [openId, onToast]);
  const reloadOpen = React.useCallback(async () => {
    if (!openId) return;
    try {
      const d = await apiFetch(`/api/v1/proforma/draft/${openId}`);
      setOpenDraft(d.draft);
    } catch (e) {
      onToast && onToast("Failed to refresh draft: " + e.message, "error");
    }
  }, [openId, onToast]);
  const [productOptions, setProductOptions] = React.useState([]);
  const [customerOptions, setCustomerOptions] = React.useState([]);
  const [applyingCustomer, setApplyingCustomer] = React.useState(null);
  React.useEffect(() => {
    if (!openId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch("/api/v1/proforma/product-options");
        if (!cancelled) setProductOptions(r && r.options || []);
      } catch (_) {
        if (!cancelled) setProductOptions([]);
      }
      try {
        const r = await apiFetch("/api/v1/customer-master/");
        if (!cancelled) setCustomerOptions(r && r.customers || []);
      } catch (_) {
        if (!cancelled) setCustomerOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openId]);
  const loadEvents = React.useCallback(async () => {
    if (!openId) return;
    try {
      const d = await apiFetch(`/api/v1/proforma/draft/${openId}/events`);
      setEvents(d.events || []);
      setEventsOpen(true);
    } catch (e) {
      onToast && onToast("Failed to load events: " + e.message, "error");
    }
  }, [openId, onToast]);
  const openLinkPanel = React.useCallback(async () => {
    setShowLink(true);
    setPackDocsLoading(true);
    setPackDocs([]);
    setClientNames({});
    setIgnoredDocs(/* @__PURE__ */ new Set());
    try {
      const d = await apiFetch(`/api/v1/packing/${encodeURIComponent(batchId)}/packing-documents`);
      const docs = d && d.documents || [];
      setPackDocs(docs);
      const initial = {};
      const initialIgnored = /* @__PURE__ */ new Set();
      docs.forEach((doc) => {
        initial[doc.id] = doc.suggested_client_name || "";
        if (doc.is_duplicate) initialIgnored.add(doc.id);
      });
      setClientNames(initial);
      setIgnoredDocs(initialIgnored);
    } catch (e) {
      onToast && onToast("Failed to load packing documents: " + e.message, "error");
    }
    setPackDocsLoading(false);
  }, [batchId, onToast]);
  const submitLinkAsSales = React.useCallback(async () => {
    const mappings = packDocs.filter((doc) => !ignoredDocs.has(doc.id) && !(doc.is_duplicate && doc.line_count === 0) && (clientNames[doc.id] || "").trim()).map((doc) => ({ packing_document_id: doc.id, client_name: clientNames[doc.id].trim() }));
    if (!mappings.length) {
      onToast && onToast("Enter at least one client name to link (or restore an ignored row).", "error");
      return;
    }
    setLinkBusy(true);
    try {
      const res = await apiFetch(
        `/api/v1/packing/${encodeURIComponent(batchId)}/link-as-sales`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_mappings: mappings })
        }
      );
      const linked = res && res.linked || 0;
      const skipped = res && res.failed || 0;
      const created = res && res.draft_sync && res.draft_sync.created || 0;
      const synced = res && res.draft_sync && res.draft_sync.synced || 0;
      const parts = [`Linked ${linked} client(s).`];
      if (skipped) parts.push(`${skipped} skipped.`);
      parts.push(`Drafts created: ${created}, synced: ${synced}.`);
      onToast && onToast(parts.join(" "), linked > 0 ? "success" : "warning");
      setShowLink(false);
      refreshList();
    } catch (e) {
      onToast && onToast("Link failed: " + e.message, "error");
    }
    setLinkBusy(false);
  }, [batchId, packDocs, clientNames, ignoredDocs, onToast, refreshList]);
  const _writeCall = React.useCallback(async (label, url, opts = {}) => {
    const op = _resolveOperator();
    if (!op) {
      onToast && onToast(`${label}: operator name required`, "error");
      throw new Error("operator missing");
    }
    const headers = {
      "X-Operator": op,
      "Content-Type": "application/json",
      ...opts.headers || {}
    };
    try {
      const r = await apiFetch(url, { ...opts, headers });
      onToast && onToast(`${label} ok`, "success");
      await reloadOpen();
      await refreshList();
      return r;
    } catch (e) {
      onToast && onToast(`${label} failed: ${e.message}`, "error");
      throw e;
    }
  }, [onToast, reloadOpen, refreshList]);
  const onApplyCustomerDefaults = React.useCallback(async (c) => {
    if (!openId || !openDraft || !c) return;
    const op = _resolveOperator();
    if (!op) {
      onToast && onToast("Customer apply: operator name required", "error");
      return;
    }
    const _trim = (v) => v == null ? "" : String(v).trim();
    const _put = (target, key, value) => {
      const v = _trim(value);
      if (v) target[key] = v;
    };
    const buyer = {};
    _put(buyer, "type", "company");
    _put(buyer, "name", c.bill_to_name || c.client_name);
    _put(buyer, "vat_id", c.nip || c.vat_eu_number || c.vat_id);
    _put(buyer, "country", c.country);
    _put(buyer, "street", c.bill_to_street);
    _put(buyer, "city", c.bill_to_city);
    _put(buyer, "zip", c.bill_to_postal_code);
    _put(buyer, "email", c.bill_to_email);
    _put(buyer, "phone", c.bill_to_phone || c.bill_to_mobile);
    const ship = {};
    _put(ship, "type", "company");
    _put(ship, "name", c.ship_to_name || c.bill_to_name || c.client_name);
    _put(ship, "street", c.ship_to_street || c.bill_to_street);
    _put(ship, "city", c.ship_to_city || c.bill_to_city);
    _put(ship, "zip", c.ship_to_postal_code || c.bill_to_postal_code);
    _put(ship, "country", c.ship_to_country || c.country);
    _put(ship, "email", c.ship_to_email || c.bill_to_email);
    _put(ship, "phone", c.ship_to_phone || c.bill_to_phone || c.bill_to_mobile);
    const terms = {};
    if (c.payment_terms_days != null && _trim(c.payment_terms_days) !== "") {
      _put(terms, "days", String(c.payment_terms_days));
    }
    let currentUpdatedAt = openDraft.updated_at;
    const headers = { "X-Operator": op, "Content-Type": "application/json" };
    const _patch = async (phaseLabel, payload) => {
      const r = await apiFetch(`/api/v1/proforma/draft/${openId}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({
          expected_updated_at: currentUpdatedAt,
          patch: payload
        })
      });
      if (r && r.draft && r.draft.updated_at) {
        currentUpdatedAt = r.draft.updated_at;
      }
      return r;
    };
    setApplyingCustomer({
      phase: "buyer",
      message: "Applying customer defaults\u2026"
    });
    try {
      if (Object.keys(buyer).length) {
        await _patch("buyer", { buyer_override: buyer });
      }
      setApplyingCustomer({
        phase: "ship_to",
        message: "Buyer saved \xB7 saving ship-to\u2026"
      });
      if (Object.keys(ship).length) {
        await _patch("ship_to", { ship_to_override: ship });
      }
      setApplyingCustomer({
        phase: "payment_terms",
        message: "Ship-to saved \xB7 saving payment terms\u2026"
      });
      if (Object.keys(terms).length) {
        await _patch("payment_terms", { payment_terms: terms });
      }
      setApplyingCustomer({
        phase: "done",
        message: "Customer defaults applied"
      });
      onToast && onToast("Customer defaults applied", "success");
      await reloadOpen();
      await refreshList();
      setTimeout(() => setApplyingCustomer(null), 1500);
    } catch (e) {
      setApplyingCustomer({
        phase: "error",
        message: "Failed: " + (e && e.message || e)
      });
      onToast && onToast("Apply customer defaults failed: " + (e && e.message || e), "error");
    }
  }, [openId, openDraft, onToast, reloadOpen, refreshList]);
  const onPatchField = (field, value) => _writeCall(`PATCH ${field}`, `/api/v1/proforma/draft/${openId}`, {
    method: "PATCH",
    body: JSON.stringify({
      expected_updated_at: openDraft.updated_at,
      patch: { [field]: value }
    })
  });
  const onPatchLine = (lineId, patch) => _writeCall(
    `PATCH line ${lineId}`,
    `/api/v1/proforma/draft/${openId}/lines/${lineId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        expected_updated_at: openDraft.updated_at,
        patch
      })
    }
  );
  const [chargePrefill, setChargePrefill] = React.useState(null);
  const [priceRecoveryOpen, setPriceRecoveryOpen] = React.useState(false);
  const [bulkPriceText, setBulkPriceText] = React.useState("");
  const [bulkPriceResult, setBulkPriceResult] = React.useState(null);
  const [bulkPriceNeedsConfirm, setBulkPriceNeedsConfirm] = React.useState(null);
  const [visibility, setVisibility] = React.useState(null);
  const [visOpen, setVisOpen] = React.useState(false);
  const onApplyBulkPrices = React.useCallback(async (withConfirm) => {
    const parsed = parseBulkPriceText(bulkPriceText);
    if (!parsed.ok) {
      setBulkPriceResult({ ok: false, detail: parsed.errors.join("; ") });
      return;
    }
    const bodyObj = {
      expected_updated_at: openDraft.updated_at,
      prices: parsed.prices
    };
    if (withConfirm) bodyObj.confirm_overwrite = "YES_OVERWRITE_EXISTING_PRICES";
    try {
      const r = await _writeCall(
        "Bulk price recovery",
        `/api/v1/proforma/draft/${openId}/bulk-price-recovery`,
        {
          method: "POST",
          body: JSON.stringify(bodyObj)
        }
      );
      if (r && r.ok) {
        setBulkPriceResult(r);
        setBulkPriceNeedsConfirm(null);
      } else if (r && r.requires_confirm_overwrite) {
        setBulkPriceNeedsConfirm(r.codes_with_existing_price || []);
        setBulkPriceResult(null);
      } else {
        setBulkPriceResult({ ok: false, detail: r && r.detail || "Unknown error" });
      }
    } catch (e) {
      setBulkPriceResult({ ok: false, detail: e.message });
    }
  }, [openId, openDraft, bulkPriceText, _writeCall]);
  const onAddCharge = (charge) => _writeCall(
    "Add service charge",
    `/api/v1/proforma/draft/${openId}/service-charges`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_updated_at: openDraft.updated_at,
        charge
      })
    }
  );
  const onAddLine = (line) => _writeCall("Add line", `/api/v1/proforma/draft/${openId}/lines`, {
    method: "POST",
    body: JSON.stringify({
      expected_updated_at: openDraft.updated_at,
      line
    })
  });
  const onDeleteLine = (lineId) => _writeCall(
    `Delete line ${lineId}`,
    `/api/v1/proforma/draft/${openId}/lines/${lineId}`,
    {
      method: "DELETE",
      body: JSON.stringify({
        expected_updated_at: openDraft.updated_at
      })
    }
  );
  const onPreviewHtml = React.useCallback(() => {
    if (!openDraft) return;
    try {
      window.open(
        `/api/v1/proforma/draft/${openDraft.id}/preview.html`,
        "_blank"
      );
    } catch (_) {
    }
  }, [openDraft]);
  const [previewModal, setPreviewModal] = React.useState(null);
  const onPreviewJsonDebug = React.useCallback(async () => {
    if (!openDraft) return;
    setPreviewModal({ loading: true });
    try {
      const r = await apiFetch(
        `/api/v1/proforma/preview/${encodeURIComponent(batchId)}/` + encodeURIComponent(openDraft.client_name),
        { method: "POST" }
      );
      const body = await (r.text ? r.text() : r);
      let parsed;
      try {
        parsed = JSON.parse(body);
      } catch {
        parsed = body;
      }
      setPreviewModal({ loading: false, ok: r.ok !== false, body: parsed });
    } catch (e) {
      setPreviewModal({
        loading: false,
        ok: false,
        error: String(e && e.message || e)
      });
    }
  }, [openDraft, batchId]);
  const onPreviewDownload = React.useCallback(() => {
    if (!previewModal || !previewModal.body) return;
    const blob = new Blob(
      [JSON.stringify(previewModal.body, null, 2)],
      { type: "application/json" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `proforma-preview-${batchId}-${openDraft.client_name}.json`.replace(/[^A-Za-z0-9._-]/g, "_");
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [previewModal, batchId, openDraft]);
  const onCustomerRemapOpen = React.useCallback(() => {
    try {
      window.open("/dashboard/dashboard.html#customer-master", "_blank");
    } catch (_) {
    }
  }, []);
  const onRemoveCharge = (chargeId) => _writeCall(
    "Remove service charge",
    `/api/v1/proforma/draft/${openId}/service-charges/${chargeId}?expected_updated_at=${encodeURIComponent(openDraft.updated_at)}`,
    { method: "DELETE" }
  );
  const onSuggestFreight = React.useCallback(async () => {
    try {
      const r = await apiFetch(`/api/v1/proforma/draft/${openId}/suggest-freight`);
      if (r && r.ok && r.suggestion) {
        setChargePrefill({
          charge_type: "freight",
          amount: r.suggestion.amount,
          currency: r.draft_currency || openDraft.currency || "EUR",
          label: r.suggestion.label || ""
        });
      } else {
        const reason = r && r.reason ? r.reason : "no freight data configured";
        onToast && onToast(`Freight suggestion blocked: ${reason}`, "warn");
      }
    } catch (e) {
      onToast && onToast(`Suggest freight failed: ${e.message}`, "error");
    }
  }, [openId, openDraft, onToast]);
  const onSuggestInsurance = React.useCallback(async () => {
    try {
      const r = await apiFetch(`/api/v1/proforma/draft/${openId}/suggest-insurance`);
      if (r && r.ok && r.suggestion) {
        setChargePrefill({
          charge_type: "insurance",
          amount: r.suggestion.amount,
          currency: r.draft_currency || openDraft.currency || "EUR",
          label: r.suggestion.label || ""
        });
      } else {
        const reason = r && r.reason ? r.reason : "no insurance data configured";
        onToast && onToast(`Insurance suggestion blocked: ${reason}`, "warn");
      }
    } catch (e) {
      onToast && onToast(`Suggest insurance failed: ${e.message}`, "error");
    }
  }, [openId, openDraft, onToast]);
  const onApprove = () => {
    const token = window.prompt(
      `Type the approval token to lock this draft as approved:

  ${PROFORMA_DRAFT_TOKENS.approve}`,
      ""
    );
    if (token !== PROFORMA_DRAFT_TOKENS.approve) {
      onToast && onToast("Approve cancelled \u2014 token mismatch", "info");
      return;
    }
    return _writeCall(
      "Approve draft",
      `/api/v1/proforma/draft/${openId}/approve`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: openDraft.updated_at,
          confirm_token: PROFORMA_DRAFT_TOKENS.approve
        })
      }
    );
  };
  const onReopen = () => {
    const token = window.prompt(
      `Type the re-open token to unlock this draft:

  ${PROFORMA_DRAFT_TOKENS.reopen}`,
      ""
    );
    if (token !== PROFORMA_DRAFT_TOKENS.reopen) {
      onToast && onToast("Re-open cancelled \u2014 token mismatch", "info");
      return;
    }
    return _writeCall(
      "Re-open draft",
      `/api/v1/proforma/draft/${openId}/re-open`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: openDraft.updated_at,
          confirm_token: PROFORMA_DRAFT_TOKENS.reopen
        })
      }
    );
  };
  const onCancel = () => {
    const reason = window.prompt("Reason for cancelling this draft (required):", "");
    if (!reason || !reason.trim()) {
      onToast && onToast("Cancel aborted \u2014 reason required", "info");
      return;
    }
    if (!window.confirm("Cancel this draft? This is local-only and does NOT delete a wFirma Proforma. Cancelled drafts are read-only.")) return;
    return _writeCall(
      "Cancel draft",
      `/api/v1/proforma/draft/${openId}/cancel`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: openDraft.updated_at,
          reason: reason.trim()
        })
      }
    );
  };
  const onReset = () => {
    if (!window.confirm(
      "Reset this draft from the latest sales packing? CURRENT EDITABLE LINES WILL BE REPLACED. Buyer/ship-to/payment-terms/remarks are preserved."
    )) return;
    return _writeCall(
      "Reset from sales packing",
      `/api/v1/proforma/draft/${openId}/reset-from-sales-packing`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: openDraft.updated_at,
          reset_all: false
        })
      }
    );
  };
  const onResetAll = () => {
    if (!window.confirm(
      "RESET ALL: replace lines AND wipe buyer / ship-to / payment-terms / remarks / service-charges. Continue?"
    )) return;
    return _writeCall(
      "Reset (full) from sales packing",
      `/api/v1/proforma/draft/${openId}/reset-from-sales-packing`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: openDraft.updated_at,
          reset_all: true
        })
      }
    );
  };
  const onEnrichProductNames = () => {
    if (!openDraft || !isEditable) return;
    if (!(openDraft.editable_lines || []).length) return;
    _writeCall(
      "Enrich product names",
      `/api/v1/proforma/draft/${openId}/enrich-from-product-descriptions`,
      {
        method: "POST",
        body: JSON.stringify({ expected_updated_at: openDraft.updated_at })
      }
    ).then((result) => {
      if (result && result.ok) {
        const n = result.enriched_count || 0;
        const m = result.missing_count || 0;
        onToast && onToast(`Enriched ${n} line${n !== 1 ? "s" : ""} (${m} without description)`, "success");
      }
    });
  };
  const onPostToWfirma = () => {
    if (!openDraft || openDraft.draft_state !== "approved") return;
    if (!window.confirm(
      '\u26A0\uFE0F POSTS A REAL PROFORMA TO wFirma.\n\nThis is a live external write. The draft will transition to "posting" before the call. On success it becomes "posted" with the returned wFirma id. On failure it becomes "post_failed" \u2014 you must re-open + edit + approve again to retry.\n\nContinue?'
    )) return;
    const token = window.prompt(
      `Type the post token to authorise the live wFirma write:

  ${PROFORMA_DRAFT_TOKENS.post}`,
      ""
    );
    if (token !== PROFORMA_DRAFT_TOKENS.post) {
      onToast && onToast("Post cancelled \u2014 token mismatch", "info");
      return;
    }
    return _writeCall(
      "Post to wFirma",
      `/api/v1/proforma/draft/${openId}/post`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: openDraft.updated_at,
          confirm_token: PROFORMA_DRAFT_TOKENS.post
        })
      }
    ).then((result) => {
      if (result && result.service_charges_note) {
        onToast && onToast(
          "\u26A0 " + result.service_charges_note,
          "warning"
        );
      }
      return result;
    });
  };
  if (loading) {
    return /* @__PURE__ */ React.createElement(Card, { "data-testid": "proforma-draft-panel-loading" }, /* @__PURE__ */ React.createElement(SectionHeader, { icon: "\u25C7", title: "Local Proforma Drafts", subtitle: "Loading\u2026" }), /* @__PURE__ */ React.createElement("div", { style: { padding: 20, color: "var(--text-3)", fontSize: 12 } }, "Loading\u2026"));
  }
  if (!drafts.length) {
    return /* @__PURE__ */ React.createElement(Card, { "data-testid": "proforma-draft-panel-empty", style: { marginBottom: 16 } }, /* @__PURE__ */ React.createElement(
      SectionHeader,
      {
        icon: "\u25C7",
        title: "Local Proforma Drafts",
        subtitle: "No proforma drafts yet. Upload a client sales file, or use the link button below if purchase packing files are already uploaded."
      }
    ), !showLink ? /* @__PURE__ */ React.createElement("div", { style: { padding: "0 16px 16px" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": "btn-link-packing-as-sales",
        onClick: openLinkPanel,
        style: {
          fontSize: 12,
          padding: "6px 14px",
          borderRadius: 6,
          background: "#0B3D2E",
          color: "#fff",
          border: "none",
          cursor: "pointer"
        }
      },
      "\u27F3 Link packing files as client sales"
    ), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 10, fontSize: 11, color: "var(--text-3)" } }, "Use this if client packing files were uploaded but drafts were not created.")) : /* @__PURE__ */ React.createElement("div", { "data-testid": "link-packing-panel", style: { padding: "0 16px 16px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, fontSize: 13, marginBottom: 8 } }, "Assign client names to uploaded packing files"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 12 } }, "Names pre-filled from filenames where possible. Leave blank to skip a file."), packDocsLoading && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)", fontSize: 12 } }, "Loading packing documents\u2026"), !packDocsLoading && !packDocs.length && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "link-packing-no-docs",
        style: { color: "var(--text-3)", fontSize: 12 }
      },
      "No purchase packing files found for this batch."
    ), !packDocsLoading && packDocs.length > 0 && /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 12, marginBottom: 12 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { borderBottom: "1px solid var(--border-1)", color: "var(--text-3)" } }, /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: "4px 8px" } }, "Invoice / File"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "right", padding: "4px 8px" } }, "Lines"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: "4px 8px" } }, "Client name"), /* @__PURE__ */ React.createElement("th", { style: { textAlign: "left", padding: "4px 8px" } }, "Action"))), /* @__PURE__ */ React.createElement("tbody", null, packDocs.filter((doc) => !(doc.is_duplicate && doc.line_count === 0)).map((doc) => {
      const isIgnored = ignoredDocs.has(doc.id);
      const isUnassigned = !isIgnored && !(clientNames[doc.id] || "").trim();
      return /* @__PURE__ */ React.createElement(
        "tr",
        {
          key: doc.id,
          "data-testid": isIgnored ? `link-packing-doc-ignored-${doc.id}` : isUnassigned ? `link-packing-doc-unassigned-${doc.id}` : void 0,
          style: {
            borderBottom: "1px solid var(--border-0)",
            opacity: isIgnored ? 0.38 : 1,
            background: isUnassigned ? "var(--badge-amber-bg)" : "transparent",
            transition: "opacity 0.15s"
          }
        },
        /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 8px" } }, doc.is_duplicate && /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": `link-packing-doc-dup-badge-${doc.id}`,
            style: {
              fontSize: 9,
              fontWeight: 700,
              background: "#7c3aed22",
              color: "#7c3aed",
              borderRadius: 3,
              padding: "1px 4px",
              marginRight: 4,
              verticalAlign: "middle"
            }
          },
          "DUP"
        ), isUnassigned && /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": `link-packing-doc-needs-client-${doc.id}`,
            style: {
              fontSize: 9,
              fontWeight: 700,
              background: "var(--badge-amber-bg)",
              color: "var(--badge-amber-text)",
              border: "1px solid var(--badge-amber-border)",
              borderRadius: 3,
              padding: "1px 4px",
              marginRight: 4,
              verticalAlign: "middle"
            }
          },
          "Needs client"
        ), /* @__PURE__ */ React.createElement("span", { "data-testid": `link-packing-doc-invoice-${doc.id}` }, doc.invoice_no || "\u2014"), /* @__PURE__ */ React.createElement("div", { style: {
          color: "var(--text-3)",
          fontSize: 10,
          maxWidth: 200,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap"
        } }, doc.source_file_path ? doc.source_file_path.split(/[/\\]/).pop() : "")),
        /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 8px", color: "var(--text-3)", textAlign: "right" } }, /* @__PURE__ */ React.createElement("span", { "data-testid": `link-packing-doc-lines-${doc.id}` }, doc.line_count != null ? doc.line_count : "\u2014")),
        /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 8px" } }, clientList.length > 0 && /* @__PURE__ */ React.createElement("datalist", { id: `cm-clients-${doc.id}` }, clientList.map((c, ci) => /* @__PURE__ */ React.createElement("option", { key: ci, value: c.name }))), /* @__PURE__ */ React.createElement(
          "input",
          {
            "data-testid": `link-packing-client-input-${doc.id}`,
            type: "text",
            list: clientList.length > 0 ? `cm-clients-${doc.id}` : void 0,
            placeholder: "Client name (type or pick from Customer Master)",
            value: clientNames[doc.id] || "",
            onChange: (e) => setClientNames((prev) => ({ ...prev, [doc.id]: e.target.value })),
            disabled: isIgnored,
            style: {
              fontSize: 12,
              padding: "3px 8px",
              borderRadius: 4,
              width: 220,
              border: "1px solid var(--border-1)",
              background: "var(--bg-1)",
              color: "var(--text-1)"
            }
          }
        )),
        /* @__PURE__ */ React.createElement("td", { style: { padding: "4px 8px" } }, doc.is_duplicate && /* @__PURE__ */ React.createElement(
          "button",
          {
            "data-testid": `link-packing-doc-ignore-btn-${doc.id}`,
            onClick: () => setIgnoredDocs((prev) => {
              const next = new Set(prev);
              if (next.has(doc.id)) next.delete(doc.id);
              else next.add(doc.id);
              return next;
            }),
            title: isIgnored ? "Restore: include this file in linking" : "Ignore: skip this duplicate file",
            style: {
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 4,
              cursor: "pointer",
              border: "1px solid var(--border-1)",
              background: isIgnored ? "#0B3D2E22" : "#7c3aed22",
              color: isIgnored ? "#0B3D2E" : "#7c3aed",
              fontWeight: 600
            }
          },
          isIgnored ? "\u21A9 Restore" : "\u2715 Ignore"
        ))
      );
    }))), !packDocsLoading && (() => {
      const ghostCount = packDocs.filter((doc) => doc.is_duplicate && doc.line_count === 0).length;
      return ghostCount > 0 ? /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "link-packing-ghost-count",
          style: {
            fontSize: 11,
            color: "var(--text-3)",
            padding: "6px 8px",
            fontStyle: "italic"
          }
        },
        ghostCount,
        " duplicate upload",
        ghostCount !== 1 ? "s" : "",
        " hidden (zero lines)"
      ) : null;
    })(), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": "btn-link-packing-submit",
        onClick: submitLinkAsSales,
        disabled: linkBusy || packDocsLoading || !packDocs.length,
        style: {
          fontSize: 12,
          padding: "6px 14px",
          borderRadius: 6,
          background: linkBusy ? "#555" : "#0B3D2E",
          color: "#fff",
          border: "none",
          cursor: linkBusy ? "default" : "pointer"
        }
      },
      linkBusy ? "Linking\u2026" : "\u2713 Link & Create Drafts"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        "data-testid": "btn-link-packing-cancel",
        onClick: () => setShowLink(false),
        style: {
          fontSize: 12,
          padding: "6px 14px",
          borderRadius: 6,
          background: "transparent",
          color: "var(--text-2)",
          border: "1px solid var(--border-1)",
          cursor: "pointer"
        }
      },
      "Cancel"
    ))));
  }
  const isEditable = openDraft && PROFORMA_DRAFT_EDITABLE_STATES.includes(openDraft.draft_state);
  const isPosted = openDraft && openDraft.draft_state === "posted";
  const isCancelled = openDraft && openDraft.draft_state === "cancelled";
  const isPostFailed = openDraft && openDraft.draft_state === "post_failed";
  const isPosting = openDraft && openDraft.draft_state === "posting";
  return /* @__PURE__ */ React.createElement(
    Card,
    {
      "data-testid": "proforma-draft-panel",
      className: "ej-doc-suite",
      style: {
        marginBottom: 16,
        // Phase 7 — adopt Estrella Document Suite brand tokens (scoped to
        // this panel only via CSS custom properties; no global theme
        // change). Maps the design's emerald/gold/cream palette onto the
        // existing structural styles without removing any.
        ["--ej-brand"]: "#0B3D2E",
        ["--ej-brand-2"]: "#0F5A45",
        ["--ej-brand-3"]: "#DCEDE5",
        ["--ej-gold"]: "#C9A24B",
        ["--ej-gold-2"]: "#B0892F",
        ["--ej-gold-tint"]: "#F6EFD9",
        ["--ej-cream"]: "#FBF8F1"
      }
    },
    /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "proforma-draft-masthead",
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px",
          background: "linear-gradient(90deg, var(--ej-brand) 0 65%, var(--ej-gold) 65% 100%)",
          color: "#fff"
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12 } }, /* @__PURE__ */ React.createElement(
        "span",
        {
          "aria-hidden": "true",
          style: {
            width: 28,
            height: 28,
            borderRadius: "50%",
            background: "linear-gradient(135deg,#0B3D2E 0%,#0F5A45 100%)",
            color: "var(--ej-gold)",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 14,
            letterSpacing: "-0.05em",
            boxShadow: "0 0 0 2px var(--ej-gold-tint)"
          }
        },
        "EJ"
      ), /* @__PURE__ */ React.createElement("div", { style: { lineHeight: 1.1 } }, /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 9,
        letterSpacing: "0.2em",
        textTransform: "uppercase",
        color: "var(--ej-gold-tint)",
        fontWeight: 600
      } }, "Estrella Jewels \xB7 Document Suite"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, marginTop: 2 } }, "Pro Forma \xB7 Faktura proforma"))),
      /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 9,
        letterSpacing: "0.18em",
        textTransform: "uppercase",
        color: "var(--ej-gold-tint)",
        fontWeight: 600
      } }, drafts.length, " draft", drafts.length === 1 ? "" : "s")
    ),
    /* @__PURE__ */ React.createElement(
      SectionHeader,
      {
        icon: "\u25C7",
        title: "Local Proforma Drafts",
        subtitle: `${drafts.length} draft(s) \u2014 edit locally before posting to wFirma`
      }
    ),
    /* @__PURE__ */ React.createElement("div", { "data-testid": "proforma-draft-list", style: { padding: 12 } }, drafts.map((d) => /* @__PURE__ */ React.createElement(
      "div",
      {
        key: d.id,
        "data-testid": `proforma-draft-row-${d.id}`,
        style: {
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 12px",
          borderBottom: "1px solid var(--card-border)",
          background: openId === d.id ? "var(--card-hover)" : "transparent",
          cursor: "pointer"
        },
        onClick: () => openId === d.id ? closeOne() : openOne(d.id)
      },
      /* @__PURE__ */ React.createElement(ProformaDraftStateChip, { state: d.draft_state }),
      /* @__PURE__ */ React.createElement("div", { style: { flex: 1, fontSize: 13 } }, /* @__PURE__ */ React.createElement("strong", null, d.client_name), " \xB7 ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "v", d.draft_version), d.wfirma_proforma_id && /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": `draft-wfirma-id-${d.id}`,
          style: {
            marginLeft: 10,
            fontSize: 11,
            color: "var(--text-3)",
            fontFamily: "monospace"
          }
        },
        "wFirma id: ",
        d.wfirma_proforma_id,
        d.wfirma_proforma_fullnumber && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 6 } }, "(", d.wfirma_proforma_fullnumber, ")")
      ), d.draft_state === "post_failed" && d.error_hint && /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": `draft-error-hint-${d.id}`,
          style: {
            marginLeft: 8,
            fontSize: 10,
            color: "var(--badge-red-text)",
            fontFamily: "monospace",
            background: "var(--badge-red-bg)",
            padding: "1px 5px",
            borderRadius: 3,
            maxWidth: 260,
            display: "inline-block",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            verticalAlign: "middle"
          },
          title: d.error_hint
        },
        "\u2717 ",
        d.error_hint
      ), d.reservation_status && d.reservation_status !== "created" && /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": `draft-reservation-status-${d.id}`,
          style: {
            marginLeft: 8,
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: d.reservation_status === "failed" ? "var(--badge-red-text)" : "var(--text-3)",
            background: d.reservation_status === "failed" ? "var(--badge-red-bg)" : "var(--bg-subtle)",
            padding: "1px 5px",
            borderRadius: 3
          }
        },
        "res: ",
        d.reservation_status
      ), d.last_packing_sync_at && !d.packing_sync_warning && /* @__PURE__ */ React.createElement(
        "span",
        {
          "data-testid": `draft-sync-chip-${d.id}`,
          style: {
            marginLeft: 8,
            fontSize: 9.5,
            color: "var(--text-3)",
            background: "var(--bg-subtle)",
            padding: "1px 5px",
            borderRadius: 3
          },
          title: `Lines synced from packing upload: ${d.last_packing_sync_at.slice(0, 19).replace("T", " ")}`
        },
        "\u21BB packing synced"
      )),
      /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)" } }, d.draft_state === "posting" && d.posting_started_at ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-blue-text)" } }, "posting since ", d.posting_started_at.slice(0, 19).replace("T", " ")) : /* @__PURE__ */ React.createElement(React.Fragment, null, "updated ", (d.updated_at || "").slice(0, 19).replace("T", " ")))
    ))),
    openId && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "proforma-draft-detail",
        style: { borderTop: "2px solid var(--card-border)", padding: 16 }
      },
      openBusy && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12 } }, "Loading draft\u2026"),
      openDraft && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 12
      } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(ProformaDraftStateChip, { state: openDraft.draft_state }), (() => {
        const linkExists = !!(openDraft.invoice_link_id || openDraft.has_invoice_link);
        const eligible = openDraft.status === "issued" && openDraft.draft_state === "posted" && !linkExists;
        const blockers = [];
        if (openDraft.status !== "issued")
          blockers.push("draft.status must be 'issued'");
        if (openDraft.draft_state !== "posted")
          blockers.push("draft_state must be 'posted'");
        if (linkExists)
          blockers.push("invoice link already exists");
        return /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": "draft-invoice-eligibility-badge",
            title: eligible ? "Invoice conversion eligible" : blockers.join("; "),
            style: {
              marginLeft: 8,
              padding: "2px 8px",
              borderRadius: 10,
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              background: eligible ? "var(--badge-green-bg)" : "var(--badge-amber-bg)",
              color: eligible ? "var(--badge-green-text)" : "var(--badge-amber-text)"
            }
          },
          eligible ? "Invoice eligible" : "Invoice blocked"
        );
      })(), /* @__PURE__ */ React.createElement("strong", { style: { marginLeft: 10, fontSize: 14 } }, openDraft.client_name), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 8, fontSize: 11, color: "var(--text-3)" } }, "draft #", openDraft.id, " \xB7 v", openDraft.draft_version)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement(Btn, { small: true, onClick: loadEvents, "data-testid": "btn-draft-events" }, eventsOpen ? "\u25B2 Hide history" : "\u25BC History"), /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          onClick: () => {
            if (visOpen) {
              setVisOpen(false);
            } else {
              loadVisibility();
            }
          },
          "data-testid": "btn-draft-visibility"
        },
        visOpen ? "\u25B2 Visibility" : "\u25BC Visibility"
      ), /* @__PURE__ */ React.createElement(Btn, { small: true, onClick: closeOne }, "Close"))), /* @__PURE__ */ React.createElement(
        ProformaCustomerCard,
        {
          resolution: openDraft.customer_resolution,
          clientName: openDraft.client_name,
          onRemapOpen: onCustomerRemapOpen
        }
      ), (isPosted || openDraft.draft_state === "adopted_from_audit") && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-posted-banner",
          className: "ej-doc-toolbar",
          style: {
            borderRadius: 4,
            marginBottom: 12,
            overflow: "hidden",
            border: "1px solid var(--ej-gold)"
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          padding: "10px 14px",
          background: "var(--ej-brand)",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          fontSize: 12
        } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(
          "span",
          {
            "aria-hidden": "true",
            style: {
              fontSize: 9,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--ej-gold)",
              fontWeight: 700
            }
          },
          "Pro Forma \xB7 Issued"
        ), /* @__PURE__ */ React.createElement("strong", { style: { fontWeight: 700 } }, "POSTED to wFirma")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 14, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
          "a",
          {
            "data-testid": "draft-view-proforma-link",
            href: `/api/v1/proforma/${encodeURIComponent(openDraft.batch_id)}/${encodeURIComponent(openDraft.client_name)}/document`,
            target: "_blank",
            rel: "noreferrer",
            style: {
              color: "var(--ej-gold)",
              fontWeight: 700,
              textDecoration: "underline",
              fontSize: 11
            }
          },
          "View Proforma \u2192"
        ), /* @__PURE__ */ React.createElement(
          "a",
          {
            "data-testid": "draft-download-proforma-pdf",
            href: `/api/v1/proforma/${encodeURIComponent(openDraft.batch_id)}/${encodeURIComponent(openDraft.client_name)}/document.pdf`,
            target: "_blank",
            rel: "noreferrer",
            style: {
              color: "var(--ej-gold)",
              fontWeight: 700,
              textDecoration: "underline",
              fontSize: 11
            }
          },
          "\u2193 Download PDF"
        ))),
        /* @__PURE__ */ React.createElement("div", { style: {
          padding: "8px 14px",
          background: "var(--ej-cream)",
          color: "var(--ej-gold-2)",
          fontSize: 10.5,
          display: "flex",
          gap: 14,
          flexWrap: "wrap"
        } }, /* @__PURE__ */ React.createElement("span", null, "id ", /* @__PURE__ */ React.createElement(
          "code",
          {
            "data-testid": "draft-posted-wfirma-id",
            style: {
              color: "var(--ej-brand)",
              fontWeight: 600
            }
          },
          openDraft.wfirma_proforma_id || "\u2014"
        )), openDraft.wfirma_proforma_fullnumber && /* @__PURE__ */ React.createElement("span", null, "nr ", /* @__PURE__ */ React.createElement(
          "code",
          {
            "data-testid": "draft-posted-fullnumber",
            style: {
              color: "var(--ej-brand)",
              fontWeight: 600
            }
          },
          openDraft.wfirma_proforma_fullnumber
        )), /* @__PURE__ */ React.createElement("span", null, "currency ", /* @__PURE__ */ React.createElement("strong", { style: { color: "var(--ej-brand)" } }, openDraft.currency || "\u2014")))
      ), isPosting && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-posting-banner",
          style: {
            padding: "10px 14px",
            marginBottom: 12,
            background: "var(--badge-blue-bg)",
            border: "1px solid var(--badge-blue-border)",
            borderRadius: 4,
            fontSize: 12,
            color: "var(--badge-blue-text)",
            display: "flex",
            gap: 10,
            alignItems: "center"
          }
        },
        /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, "\u23F3 Posting to wFirma\u2026"),
        openDraft.posting_started_at && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10 } }, "started ", openDraft.posting_started_at.slice(0, 19).replace("T", " "), openDraft.posting_started_by && ` by ${openDraft.posting_started_by}`)
      ), isPostFailed && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-post-failed-banner",
          style: {
            padding: "10px 14px",
            marginBottom: 12,
            background: "var(--badge-red-bg)",
            border: "1px solid var(--badge-red-border)",
            borderRadius: 4,
            fontSize: 12
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 700,
          color: "var(--badge-red-text)",
          marginBottom: 4
        } }, "\u2717 Posting failed"),
        openDraft.post_failed_at && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)", marginBottom: 4 } }, openDraft.post_failed_at.slice(0, 19).replace("T", " ")),
        openDraft.error_hint && /* @__PURE__ */ React.createElement(
          "pre",
          {
            "data-testid": "draft-post-failed-error",
            style: {
              margin: 0,
              fontSize: 10.5,
              fontFamily: "monospace",
              color: "var(--badge-red-text)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all"
            }
          },
          openDraft.error_hint
        ),
        /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, fontSize: 10, color: "var(--text-3)" } }, "Re-open the draft to edit, then re-approve and re-post.")
      ), isPosted && openDraft.posted_by && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-posted-attribution",
          style: {
            marginBottom: 8,
            fontSize: 10,
            color: "var(--text-3)",
            textAlign: "right"
          }
        },
        "Posted by ",
        /* @__PURE__ */ React.createElement("strong", null, openDraft.posted_by),
        openDraft.posted_at && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 6 } }, openDraft.posted_at.slice(0, 19).replace("T", " "))
      ), openDraft.last_packing_sync_at && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-packing-sync-badge",
          style: {
            marginBottom: 8,
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 10,
            color: openDraft.packing_sync_warning ? "var(--badge-amber-text, #92400e)" : "var(--text-3)"
          }
        },
        /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600 } }, openDraft.packing_sync_warning ? "\u26A0 Auto-synced (blocked)" : "\u21BB Auto-synced from packing list"),
        /* @__PURE__ */ React.createElement("span", null, openDraft.last_packing_sync_at.slice(0, 19).replace("T", " ")),
        openDraft.packing_sync_warning && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, opacity: 0.75 } }, "(", openDraft.packing_sync_warning, ")")
      ), openDraft.needs_pricing_refresh && isEditable && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-pricing-refresh-banner",
          style: {
            padding: "10px 14px",
            marginBottom: 12,
            background: "var(--badge-amber-bg, #fffbeb)",
            border: "1px solid var(--badge-amber-border, #fbbf24)",
            borderRadius: 4,
            fontSize: 12
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 700,
          color: "var(--badge-amber-text, #92400e)",
          marginBottom: 4
        } }, "\u26A0 Pricing refresh required"),
        /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 8 } }, (openDraft.editable_lines || []).filter((l) => !(l.unit_price > 0)).length, " line(s) have unit_price \u2264 0. This draft cannot be approved until all prices are filled."),
        /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            "data-testid": "btn-toggle-bulk-price-recovery",
            onClick: () => setPriceRecoveryOpen((v) => !v)
          },
          priceRecoveryOpen ? "\u25B2 Hide bulk price entry" : "\u25BC Bulk price entry"
        )
      ), priceRecoveryOpen && isEditable && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-bulk-price-panel",
          style: {
            padding: "10px 14px",
            marginBottom: 12,
            background: "var(--bg-subtle)",
            border: "1px solid var(--border-1)",
            borderRadius: 4,
            fontSize: 12
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, marginBottom: 6 } }, "Bulk price entry"),
        /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 8 } }, "One ", /* @__PURE__ */ React.createElement("code", null, "product_code, unit_price"), " per line. Currency: ", openDraft.currency || "EUR", ". Prices must be > 0."),
        /* @__PURE__ */ React.createElement(
          "textarea",
          {
            "data-testid": "bulk-price-textarea",
            placeholder: "EJL/26-27/148-1, 61.00\nEJL/26-27/148-2, 45.50",
            value: bulkPriceText,
            onChange: (e) => setBulkPriceText(e.target.value),
            rows: 8,
            style: {
              width: "100%",
              fontFamily: "monospace",
              fontSize: 12,
              padding: "6px 8px",
              borderRadius: 4,
              boxSizing: "border-box",
              border: "1px solid var(--border-1)",
              background: "var(--bg-1)",
              color: "var(--text-1)"
            }
          }
        ),
        bulkPriceResult && /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": "bulk-price-result",
            style: {
              marginTop: 8,
              padding: "6px 10px",
              background: bulkPriceResult.ok ? "var(--badge-green-bg, #f0fdf4)" : "var(--badge-red-bg)",
              border: `1px solid ${bulkPriceResult.ok ? "var(--badge-green-border, #86efac)" : "var(--badge-red-border)"}`,
              borderRadius: 4,
              fontSize: 11
            }
          },
          bulkPriceResult.ok ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
            "span",
            {
              "data-testid": "bulk-price-updated-count",
              style: { fontWeight: 700 }
            },
            "\u2713 Updated ",
            bulkPriceResult.updated_count,
            " line(s)."
          ), bulkPriceResult.still_zero_count > 0 && /* @__PURE__ */ React.createElement(
            "span",
            {
              "data-testid": "bulk-price-still-zero",
              style: {
                marginLeft: 8,
                color: "var(--badge-amber-text, #92400e)"
              }
            },
            bulkPriceResult.still_zero_count,
            " still zero."
          ), (bulkPriceResult.unmatched_codes || []).length > 0 && /* @__PURE__ */ React.createElement(
            "div",
            {
              "data-testid": "bulk-price-unmatched",
              style: { marginTop: 4, color: "var(--text-3)" }
            },
            "Unmatched: ",
            bulkPriceResult.unmatched_codes.join(", ")
          )) : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-red-text)" } }, bulkPriceResult.detail)
        ),
        bulkPriceNeedsConfirm && /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": "bulk-price-confirm-overwrite",
            style: {
              marginTop: 8,
              padding: "8px 10px",
              background: "var(--badge-amber-bg, #fffbeb)",
              border: "1px solid var(--badge-amber-border, #fbbf24)",
              borderRadius: 4,
              fontSize: 11
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: {
            fontWeight: 700,
            color: "var(--badge-amber-text, #92400e)",
            marginBottom: 4
          } }, "\u26A0 Overwrite warning"),
          /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 6 } }, "These codes already have prices and will be overwritten:", " ", /* @__PURE__ */ React.createElement("strong", { "data-testid": "bulk-price-overwrite-codes" }, bulkPriceNeedsConfirm.join(", "))),
          /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement(
            Btn,
            {
              small: true,
              "data-testid": "btn-bulk-price-confirm-overwrite",
              onClick: () => onApplyBulkPrices(true)
            },
            "Confirm overwrite"
          ), /* @__PURE__ */ React.createElement(Btn, { small: true, onClick: () => setBulkPriceNeedsConfirm(null) }, "Cancel"))
        ),
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginTop: 8 } }, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            variant: "primary",
            "data-testid": "btn-apply-bulk-prices",
            onClick: () => onApplyBulkPrices(false),
            disabled: !bulkPriceText.trim()
          },
          "Apply bulk prices"
        ), /* @__PURE__ */ React.createElement(Btn, { small: true, onClick: () => {
          setBulkPriceText("");
          setBulkPriceResult(null);
          setBulkPriceNeedsConfirm(null);
        } }, "Clear"))
      ), visOpen && visibility && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-visibility-panel",
          style: {
            marginBottom: 14,
            borderRadius: 6,
            overflow: "hidden",
            border: "1px solid var(--card-border)",
            fontSize: 12
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          padding: "8px 12px",
          background: visibility.readiness && visibility.readiness.blockers && visibility.readiness.blockers.length > 0 ? "var(--badge-red-bg, #fef2f2)" : visibility.readiness && visibility.readiness.warnings && visibility.readiness.warnings.length > 0 ? "var(--badge-amber-bg, #fffbeb)" : "#f0fdf4",
          borderBottom: "1px solid var(--card-border)"
        } }, /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 700,
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 4,
          color: "var(--text-3)"
        } }, "Readiness", /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": "draft-commercial-state",
            style: {
              marginLeft: 8,
              fontWeight: 600,
              fontSize: 10,
              textTransform: "none",
              letterSpacing: 0,
              color: visibility.readiness && visibility.readiness.ready_for_posting ? "#166534" : "var(--text-2)"
            }
          },
          "\xB7 ",
          visibility.readiness && visibility.readiness.commercial_state || "\u2014"
        )), visibility.readiness && (visibility.readiness.blockers || []).map((b, i) => /* @__PURE__ */ React.createElement(
          "div",
          {
            key: i,
            "data-testid": "draft-readiness-blocker",
            style: {
              color: "var(--badge-red-text, #991b1b)",
              marginBottom: 2,
              display: "flex",
              gap: 5,
              alignItems: "flex-start"
            }
          },
          /* @__PURE__ */ React.createElement("span", null, "\u2717"),
          /* @__PURE__ */ React.createElement("span", null, b)
        )), visibility.readiness && (visibility.readiness.warnings || []).map((w, i) => /* @__PURE__ */ React.createElement(
          "div",
          {
            key: i,
            "data-testid": "draft-readiness-warning",
            style: {
              color: "var(--badge-amber-text, #92400e)",
              marginBottom: 2,
              display: "flex",
              gap: 5,
              alignItems: "flex-start"
            }
          },
          /* @__PURE__ */ React.createElement("span", null, "\u26A0"),
          /* @__PURE__ */ React.createElement("span", null, w)
        )), visibility.readiness && (visibility.readiness.safe_to_defer || []).map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: {
          color: "var(--text-3)",
          marginBottom: 2,
          display: "flex",
          gap: 5,
          alignItems: "flex-start"
        } }, /* @__PURE__ */ React.createElement("span", null, "\u2139"), /* @__PURE__ */ React.createElement("span", null, s))), visibility.readiness && !(visibility.readiness.blockers || []).length && !(visibility.readiness.warnings || []).length && /* @__PURE__ */ React.createElement("div", { style: { color: "#166534", fontSize: 11 } }, "\u2713 No issues detected")),
        /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 0, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": "draft-shipment-panel",
            style: {
              padding: "8px 12px",
              flex: "1 1 180px",
              borderRight: "1px solid var(--card-border)",
              borderBottom: "1px solid var(--card-border)"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: {
            fontWeight: 700,
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-3)",
            marginBottom: 4
          } }, "Shipment"),
          visibility.shipment_panel && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "AWB "), /* @__PURE__ */ React.createElement("strong", { "data-testid": "draft-shipment-awb" }, visibility.shipment_panel.awb || "\u2014")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Carrier "), visibility.shipment_panel.carrier || "\u2014"), visibility.shipment_panel.service_product && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Service "), visibility.shipment_panel.service_product), visibility.shipment_panel.clearance_path && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Clearance "), visibility.shipment_panel.clearance_path))
        ), /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": "draft-company-completeness",
            style: {
              padding: "8px 12px",
              flex: "1 1 180px",
              borderRight: "1px solid var(--card-border)",
              borderBottom: "1px solid var(--card-border)"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: {
            fontWeight: 700,
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-3)",
            marginBottom: 4
          } }, "Company profile", visibility.company_completeness && /* @__PURE__ */ React.createElement("span", { style: {
            marginLeft: 6,
            fontWeight: 600,
            fontSize: 10,
            textTransform: "none",
            letterSpacing: 0,
            color: visibility.company_completeness.score >= 0.8 ? "#166534" : visibility.company_completeness.score >= 0.5 ? "#92400e" : "#991b1b"
          } }, Math.round((visibility.company_completeness.score || 0) * 100), "%")),
          visibility.company_completeness && !visibility.company_completeness.present && /* @__PURE__ */ React.createElement("div", { style: { color: "var(--badge-red-text, #991b1b)", fontWeight: 600 } }, "Not configured"),
          visibility.company_completeness && (visibility.company_completeness.missing_mandatory || []).map((f, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { color: "var(--badge-red-text, #991b1b)" } }, "\u2717 ", f)),
          visibility.company_completeness && (visibility.company_completeness.missing_recommended || []).slice(0, 3).map((f, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { color: "var(--badge-amber-text, #92400e)" } }, "\u26A0 ", f))
        ), /* @__PURE__ */ React.createElement(
          "div",
          {
            "data-testid": "draft-document-status",
            style: {
              padding: "8px 12px",
              flex: "1 1 180px",
              borderBottom: "1px solid var(--card-border)"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: {
            fontWeight: 700,
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-3)",
            marginBottom: 4
          } }, "Document"),
          visibility.document_status && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "Preview "), /* @__PURE__ */ React.createElement("span", { style: { color: "#166534" } }, "\u2713 ready")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "wFirma "), visibility.document_status.wfirma_issued ? /* @__PURE__ */ React.createElement("span", { style: { color: "#166534" } }, "\u2713 ", visibility.document_status.wfirma_proforma_fullnumber || visibility.document_status.wfirma_proforma_id) : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "not issued")))
        )),
        visibility.product_lines_panel && visibility.product_lines_panel.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 12px" } }, /* @__PURE__ */ React.createElement("div", { style: {
          fontWeight: 700,
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--text-3)",
          marginBottom: 4
        } }, "Product lines \xB7 names & HS codes"), /* @__PURE__ */ React.createElement(
          "table",
          {
            "data-testid": "draft-product-lines-panel",
            style: { width: "100%", fontSize: 11, borderCollapse: "collapse" }
          },
          /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { color: "var(--text-3)", textAlign: "left" } }, /* @__PURE__ */ React.createElement("th", { style: { paddingBottom: 3 } }, "code"), /* @__PURE__ */ React.createElement("th", null, "name_pl"), /* @__PURE__ */ React.createElement("th", null, "name_en"), /* @__PURE__ */ React.createElement("th", null, "hs_code"), /* @__PURE__ */ React.createElement("th", null, "origin"))),
          /* @__PURE__ */ React.createElement("tbody", null, visibility.product_lines_panel.map((row, i) => /* @__PURE__ */ React.createElement("tr", { key: i, style: { borderTop: "1px solid var(--card-border)" } }, /* @__PURE__ */ React.createElement("td", { style: {
            padding: "2px 4px 2px 0",
            fontFamily: "monospace",
            fontWeight: 600
          } }, row.product_code || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { padding: "2px 4px" } }, row.name_pl || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-red-text, #991b1b)" } }, "missing"), row.name_pl_source === "product_descriptions" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 9, marginLeft: 3 } }, "(db)")), /* @__PURE__ */ React.createElement("td", { style: { padding: "2px 4px" } }, row.name_en || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 10 } }, "\u2014"), row.name_en_source === "product_descriptions" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 9, marginLeft: 3 } }, "(db)")), /* @__PURE__ */ React.createElement("td", { style: { padding: "2px 4px", fontFamily: "monospace" } }, row.hs_code || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--badge-amber-text, #92400e)" } }, "\u2014"), row.hs_source === "product_local" && /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)", fontSize: 9, marginLeft: 3 } }, "(db)")), /* @__PURE__ */ React.createElement("td", { style: { padding: "2px 4px", fontFamily: "monospace" } }, row.origin_country || "\u2014"))))
        ))
      ), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 14 } }, /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 11,
        fontWeight: 700,
        color: "var(--text-3)",
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        marginBottom: 6
      } }, "Lines \xB7 currency ", openDraft.currency || "\u2014"), /* @__PURE__ */ React.createElement(
        "table",
        {
          "data-testid": "draft-lines-table",
          style: { width: "100%", fontSize: 12, borderCollapse: "collapse" }
        },
        /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { color: "var(--text-3)", textAlign: "left" } }, /* @__PURE__ */ React.createElement("th", null, "#"), /* @__PURE__ */ React.createElement("th", null, "product_code"), /* @__PURE__ */ React.createElement("th", null, "item_type"), /* @__PURE__ */ React.createElement("th", null, "name_pl"), /* @__PURE__ */ React.createElement("th", null, "design_no"), /* @__PURE__ */ React.createElement("th", null, "qty"), /* @__PURE__ */ React.createElement("th", null, "unit_price"), /* @__PURE__ */ React.createElement("th", null, "currency"), /* @__PURE__ */ React.createElement("th", null))),
        /* @__PURE__ */ React.createElement("tbody", null, (openDraft.editable_lines || []).map((ln) => /* @__PURE__ */ React.createElement(
          ProformaDraftLineRow,
          {
            key: ln.line_id,
            line: ln,
            editable: isEditable,
            onPatch: (patch) => onPatchLine(ln.line_id, patch),
            onDelete: onDeleteLine,
            sourceLines: openDraft.source_lines || []
          }
        )))
      ), !(openDraft.editable_lines || []).length && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-lines-empty-hint",
          style: {
            padding: "10px 12px",
            fontSize: 12,
            borderRadius: 4,
            marginTop: 4,
            background: "var(--badge-amber-bg, #fffbeb)",
            border: "1px solid var(--badge-amber-border, #fbbf24)",
            color: "var(--badge-amber-text, #92400e)"
          }
        },
        /* @__PURE__ */ React.createElement("strong", null, "No product lines yet."),
        isEditable && /* @__PURE__ */ React.createElement("span", null, " ", "Click ", /* @__PURE__ */ React.createElement("strong", null, "Reload items from warehouse data"), " to populate from the uploaded packing list. If no packing list has been linked yet, use ", /* @__PURE__ */ React.createElement("strong", null, "Link packing as sales"), " above first."),
        !isEditable && " This draft has no lines."
      ), isEditable && /* @__PURE__ */ React.createElement(
        ProformaAddLineForm,
        {
          draftCurrency: openDraft.currency,
          onAdd: onAddLine,
          productOptions
        }
      )), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 14 } }, /* @__PURE__ */ React.createElement("div", { style: {
        fontSize: 11,
        fontWeight: 700,
        color: "var(--text-3)",
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        marginBottom: 6
      } }, "Service charges"), /* @__PURE__ */ React.createElement(
        "table",
        {
          "data-testid": "draft-charges-table",
          style: { width: "100%", fontSize: 12, borderCollapse: "collapse" }
        },
        /* @__PURE__ */ React.createElement("tbody", null, (openDraft.service_charges || []).map((c) => /* @__PURE__ */ React.createElement("tr", { key: c.charge_id }, /* @__PURE__ */ React.createElement("td", null, c.charge_type), /* @__PURE__ */ React.createElement("td", null, c.amount), /* @__PURE__ */ React.createElement("td", null, c.currency), /* @__PURE__ */ React.createElement("td", null, c.label || ""), /* @__PURE__ */ React.createElement("td", null, isEditable && /* @__PURE__ */ React.createElement(Btn, { small: true, onClick: () => onRemoveCharge(c.charge_id) }, "Remove")))))
      ), isEditable && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginBottom: 6 } }, /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          onClick: onSuggestFreight,
          "data-testid": "btn-suggest-freight"
        },
        "Suggest freight from master"
      ), /* @__PURE__ */ React.createElement(
        Btn,
        {
          small: true,
          onClick: onSuggestInsurance,
          "data-testid": "btn-suggest-insurance"
        },
        "Calculate insurance"
      )), /* @__PURE__ */ React.createElement(
        ProformaDraftAddChargeForm,
        {
          onAdd: onAddCharge,
          draftCurrency: openDraft.currency,
          lineCurrencies: Array.from(new Set(
            (openDraft.editable_lines || []).map((l) => (l.currency || "").toUpperCase()).filter((c) => c)
          )),
          prefill: chargePrefill
        }
      ))), /* @__PURE__ */ React.createElement("div", { style: {
        display: "grid",
        gridTemplateColumns: "1fr",
        gap: 12,
        marginBottom: 14,
        fontSize: 12
      } }, isEditable && /* @__PURE__ */ React.createElement(
        ProformaBillToPicker,
        {
          customers: customerOptions,
          status: applyingCustomer,
          onApply: onApplyCustomerDefaults,
          testid: "draft-bill-to-picker-top"
        }
      ), /* @__PURE__ */ React.createElement(
        ProformaDraftRemarksEditor,
        {
          value: openDraft.remarks || "",
          editable: isEditable,
          onSave: (v) => onPatchField("remarks", v)
        }
      ), /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-overrides-summary",
          style: {
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 8,
            fontSize: 12
          }
        },
        /* @__PURE__ */ React.createElement(
          ProformaJsonObjectEditor,
          {
            label: "Buyer override",
            testidPrefix: "draft-buyer",
            pickerMode: "buyer",
            fields: [
              { key: "type", label: "Type", placeholder: "company / individual" },
              { key: "name", label: "Name", placeholder: "Company or individual name" },
              { key: "vat_id", label: "VAT ID", placeholder: "Tax ID (companies)" },
              { key: "street", label: "Street", placeholder: "Street + No." },
              { key: "city", label: "City", placeholder: "City" },
              { key: "zip", label: "ZIP", placeholder: "Postal code" },
              { key: "country", label: "Country", placeholder: "ISO country" },
              { key: "email", label: "Email", placeholder: "name@\u2026" },
              { key: "phone", label: "Phone", placeholder: "+..." }
            ],
            value: openDraft.buyer_override,
            editable: isEditable,
            onSave: (v) => onPatchField("buyer_override", v),
            extras: ({ pickFromCustomer }) => /* @__PURE__ */ React.createElement(
              ProformaCustomerPicker,
              {
                customers: customerOptions,
                onPick: pickFromCustomer,
                testid: "draft-buyer-customer-picker"
              }
            )
          }
        ),
        /* @__PURE__ */ React.createElement(
          ProformaJsonObjectEditor,
          {
            label: "Ship-to override",
            testidPrefix: "draft-ship-to",
            pickerMode: "ship_to",
            fields: [
              { key: "type", label: "Type", placeholder: "company / individual" },
              { key: "name", label: "Name", placeholder: "Recipient name" },
              { key: "street", label: "Street", placeholder: "Street + No." },
              { key: "city", label: "City", placeholder: "City" },
              { key: "zip", label: "ZIP", placeholder: "Postal code" },
              { key: "country", label: "Country", placeholder: "ISO country" },
              { key: "phone", label: "Phone", placeholder: "+..." },
              { key: "email", label: "Email", placeholder: "name@\u2026" }
            ],
            value: openDraft.ship_to_override,
            editable: isEditable,
            onSave: (v) => onPatchField("ship_to_override", v),
            extras: ({ pickFromCustomer }) => /* @__PURE__ */ React.createElement(
              ProformaCustomerPicker,
              {
                customers: customerOptions,
                onPick: pickFromCustomer,
                testid: "draft-ship-to-customer-picker"
              }
            )
          }
        ),
        /* @__PURE__ */ React.createElement(
          ProformaJsonObjectEditor,
          {
            label: "Payment terms",
            testidPrefix: "draft-payment-terms",
            pickerMode: "payment_terms",
            fields: [
              { key: "days", label: "Days", placeholder: "e.g. 30" },
              { key: "method", label: "Method", placeholder: "transfer / cash / \u2026" },
              { key: "note", label: "Note", placeholder: "Free text" }
            ],
            value: openDraft.payment_terms,
            editable: isEditable,
            onSave: (v) => onPatchField("payment_terms", v),
            extras: ({ pickFromCustomer }) => /* @__PURE__ */ React.createElement(
              ProformaCustomerPicker,
              {
                customers: customerOptions,
                onPick: pickFromCustomer,
                testid: "draft-payment-terms-customer-picker"
              }
            )
          }
        )
      )), /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-action-row",
          style: {
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            borderTop: "1px solid var(--card-border)",
            paddingTop: 12
          }
        },
        isEditable && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            variant: "primary",
            onClick: onApprove,
            "data-testid": "btn-draft-approve"
          },
          "Approve"
        ), /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onPreviewHtml,
            "data-testid": "btn-draft-preview-html",
            title: "Open a human-readable proforma draft preview in a new tab. Browser-printable to PDF. Read-only \u2014 does not post."
          },
          "Preview / print draft"
        ), false, (openDraft.editable_lines || []).length > 0 && /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            variant: "outline",
            onClick: onEnrichProductNames,
            "data-testid": "btn-enrich-product-names",
            title: "Copy item_type, name_pl, description from product_descriptions. Overwrites prior values \u2014 use after sales packing changes."
          },
          "Enrich product names"
        ), /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onReset,
            "data-testid": "btn-draft-reset"
          },
          "Reload items from warehouse data"
        ), /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onResetAll,
            "data-testid": "btn-draft-reset-all"
          },
          "Reset ALL"
        )),
        !isEditable && openDraft.draft_state === "approved" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onPreviewHtml,
            "data-testid": "btn-draft-preview-html-approved",
            title: "Open a human-readable proforma draft preview in a new tab. Read-only \u2014 does not post."
          },
          "Preview / print draft"
        )),
        openDraft.draft_state === "approved" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onReopen,
            "data-testid": "btn-draft-reopen"
          },
          "Re-open for edit"
        ), /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            variant: "primary",
            onClick: onPostToWfirma,
            "data-testid": "btn-draft-post",
            style: {
              background: "var(--badge-red-bg)",
              color: "var(--badge-red-text)"
            }
          },
          "Send to accounting (wFirma)"
        )),
        isPostFailed && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onReopen,
            "data-testid": "btn-draft-reopen-after-fail"
          },
          "Re-open for edit"
        ), /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": "draft-post-failed-note",
            style: {
              fontSize: 11,
              color: "var(--badge-red-text)",
              alignSelf: "center"
            }
          },
          "Post failed \u2014 re-open to fix, then re-approve and re-post."
        )),
        !isPosted && !isCancelled && !isPosting && /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: onCancel,
            "data-testid": "btn-draft-cancel"
          },
          "Cancel draft"
        ),
        (isPosted || isCancelled) && /* @__PURE__ */ React.createElement(
          "span",
          {
            "data-testid": "draft-readonly-note",
            style: {
              fontSize: 11,
              color: "var(--text-3)",
              alignSelf: "center"
            }
          },
          isPosted ? "Posted \u2014 read-only." : "Cancelled \u2014 read-only."
        )
      ), eventsOpen && events && /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "draft-events-drawer",
          style: {
            marginTop: 14,
            padding: 12,
            background: "var(--card-hover)",
            borderRadius: 4,
            fontSize: 11
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, marginBottom: 6 } }, "Event history (", events.length, ")"),
        events.map((e) => /* @__PURE__ */ React.createElement("div", { key: e.id, style: {
          marginBottom: 4,
          fontFamily: "monospace"
        } }, /* @__PURE__ */ React.createElement("code", null, (e.occurred_at || "").slice(0, 19).replace("T", " ")), " \xB7 ", /* @__PURE__ */ React.createElement("strong", null, e.event), " \xB7 ", /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, e.operator || "\u2014")))
      ))
    ),
    previewModal && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "draft-preview-modal",
        style: {
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0,0,0,0.4)",
          zIndex: 9e3,
          display: "flex",
          alignItems: "center",
          justifyContent: "center"
        },
        onClick: () => setPreviewModal(null)
      },
      /* @__PURE__ */ React.createElement(
        "div",
        {
          onClick: (e) => e.stopPropagation(),
          style: {
            background: "var(--card)",
            borderRadius: 6,
            width: "80%",
            maxWidth: 920,
            maxHeight: "80vh",
            display: "flex",
            flexDirection: "column",
            border: "1px solid var(--card-border)"
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          padding: 12,
          borderBottom: "1px solid var(--card-border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center"
        } }, /* @__PURE__ */ React.createElement("strong", null, "Proforma preview (read-only \u2014 does not post)"), /* @__PURE__ */ React.createElement("div", null, previewModal.body && /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            variant: "primary",
            onClick: onPreviewDownload,
            "data-testid": "btn-draft-preview-download"
          },
          "Download JSON"
        ), /* @__PURE__ */ React.createElement(
          Btn,
          {
            small: true,
            onClick: () => setPreviewModal(null),
            style: { marginLeft: 6 },
            "data-testid": "btn-draft-preview-close"
          },
          "Close"
        ))),
        /* @__PURE__ */ React.createElement("div", { style: {
          padding: 12,
          overflow: "auto",
          fontFamily: "monospace",
          fontSize: 11,
          whiteSpace: "pre-wrap"
        } }, previewModal.loading ? "Loading preview\u2026" : previewModal.error ? `Error: ${previewModal.error}` : JSON.stringify(previewModal.body, null, 2))
      )
    )
  );
}
function ProformaDraftLineRow({ line, editable, onPatch, onDelete, sourceLines }) {
  const [qty, setQty] = React.useState(String(line.qty));
  const [price, setPrice] = React.useState(String(line.unit_price));
  const [pc, setPc] = React.useState(line.product_code || "");
  const [design, setDesign] = React.useState(line.design_no || "");
  const [ccy, setCcy] = React.useState(line.currency || "");
  const [itype, setItype] = React.useState(line.item_type || "");
  const [namePl, setNamePl] = React.useState(line.name_pl || "");
  const _h = (setter) => (e) => setter(e.target.value);
  React.useEffect(() => {
    setQty(String(line.qty));
    setPrice(String(line.unit_price));
    setPc(line.product_code || "");
    setDesign(line.design_no || "");
    setCcy(line.currency || "");
    setItype(line.item_type || "");
    setNamePl(line.name_pl || "");
  }, [
    line.qty,
    line.unit_price,
    line.product_code,
    line.design_no,
    line.currency,
    line.item_type,
    line.name_pl,
    line.line_id
  ]);
  const dirty = parseFloat(qty) !== Number(line.qty) || parseFloat(price) !== Number(line.unit_price) || pc.trim() !== (line.product_code || "").trim() || design.trim() !== (line.design_no || "").trim() || ccy.trim().toUpperCase() !== (line.currency || "").toUpperCase() || itype.trim() !== (line.item_type || "").trim() || namePl !== (line.name_pl || "");
  const sourceMatch = (sourceLines || []).find(
    (s) => Number(s.line_id) === Number(line.line_id)
  );
  const sourcePc = sourceMatch && sourceMatch.product_code || "";
  const pcManualOverride = !!(line.product_code && sourcePc && line.product_code !== sourcePc);
  const namePlFull = line.name_pl || "";
  const namePlShort = namePlFull.length > 35 ? namePlFull.slice(0, 35) + "\u2026" : namePlFull;
  const save = () => {
    const patch = {};
    if (parseFloat(qty) !== Number(line.qty)) patch.qty = parseFloat(qty);
    if (parseFloat(price) !== Number(line.unit_price)) patch.unit_price = parseFloat(price);
    if (pc.trim() !== (line.product_code || "").trim()) patch.product_code = pc.trim();
    if (design.trim() !== (line.design_no || "").trim()) patch.design_no = design.trim();
    if (ccy.trim().toUpperCase() !== (line.currency || "").toUpperCase()) {
      patch.currency = ccy.trim().toUpperCase();
    }
    if (itype.trim() !== (line.item_type || "").trim()) patch.item_type = itype.trim();
    if (namePl !== (line.name_pl || "")) patch.name_pl = namePl;
    if (Object.keys(patch).length) onPatch(patch);
  };
  return /* @__PURE__ */ React.createElement("tr", { "data-testid": `draft-line-${line.line_id}` }, /* @__PURE__ */ React.createElement("td", null, line.line_id), /* @__PURE__ */ React.createElement("td", null, editable ? /* @__PURE__ */ React.createElement(
    Inp,
    {
      value: pc,
      onChange: _h(setPc),
      "data-testid": `draft-line-pc-input-${line.line_id}`,
      style: { width: 130, fontFamily: "monospace", fontSize: 11 }
    }
  ) : /* @__PURE__ */ React.createElement("code", null, line.product_code), pcManualOverride && /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": `draft-line-pc-override-${line.line_id}`,
      title: `Original source product_code: ${sourcePc}`,
      style: {
        marginTop: 2,
        fontSize: 10,
        fontWeight: 700,
        color: "var(--badge-amber-text)",
        background: "var(--badge-amber-bg)",
        display: "inline-block",
        padding: "1px 4px",
        borderRadius: 3
      }
    },
    "MANUAL OVERRIDE"
  )), /* @__PURE__ */ React.createElement(
    "td",
    {
      style: { fontSize: 11 },
      title: "item_type \u2014 Enrich copies from product_descriptions; operator may override here"
    },
    editable ? /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: itype,
        onChange: _h(setItype),
        "data-testid": `draft-line-item-type-input-${line.line_id}`,
        style: { width: 110, fontSize: 11 }
      }
    ) : /* @__PURE__ */ React.createElement("span", { style: { color: line.item_type ? "var(--text-2)" : "var(--text-3)" } }, line.item_type || "\u2014")
  ), /* @__PURE__ */ React.createElement(
    "td",
    {
      style: { maxWidth: 220 },
      title: namePlFull || "name_pl \u2014 Enrich copies from product_descriptions; operator may override here",
      "data-testid": `draft-line-name-pl-${line.line_id}`
    },
    editable ? /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: namePl,
        onChange: _h(setNamePl),
        "data-testid": `draft-line-name-pl-input-${line.line_id}`,
        style: { width: 200, fontSize: 11 }
      }
    ) : /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-block",
      maxWidth: 200,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
      color: line.name_pl ? "var(--text)" : "var(--text-3)"
    } }, namePlShort || "\u2014")
  ), /* @__PURE__ */ React.createElement("td", null, editable ? /* @__PURE__ */ React.createElement(
    Inp,
    {
      value: design,
      onChange: _h(setDesign),
      "data-testid": `draft-line-design-input-${line.line_id}`,
      style: { width: 110, fontSize: 11 }
    }
  ) : line.design_no || "\u2014"), /* @__PURE__ */ React.createElement("td", { style: { width: 90 } }, editable ? /* @__PURE__ */ React.createElement(
    Inp,
    {
      value: qty,
      onChange: _h(setQty),
      "data-testid": `draft-line-qty-input-${line.line_id}`
    }
  ) : line.qty), /* @__PURE__ */ React.createElement("td", { style: { width: 110 } }, editable ? /* @__PURE__ */ React.createElement(
    Inp,
    {
      value: price,
      onChange: _h(setPrice),
      "data-testid": `draft-line-price-input-${line.line_id}`
    }
  ) : line.unit_price), /* @__PURE__ */ React.createElement("td", null, editable ? /* @__PURE__ */ React.createElement(
    Inp,
    {
      value: ccy,
      onChange: _h(setCcy),
      "data-testid": `draft-line-ccy-input-${line.line_id}`,
      style: { width: 60 }
    }
  ) : line.currency), /* @__PURE__ */ React.createElement("td", null, editable && dirty && /* @__PURE__ */ React.createElement(
    Btn,
    {
      small: true,
      variant: "primary",
      onClick: save,
      "data-testid": `btn-line-save-${line.line_id}`
    },
    "Save"
  ), editable && onDelete && /* @__PURE__ */ React.createElement(
    Btn,
    {
      small: true,
      onClick: () => {
        if (window.confirm(
          `Delete line ${line.product_code || line.line_id}?`
        )) {
          onDelete(line.line_id);
        }
      },
      "data-testid": `btn-line-delete-${line.line_id}`,
      style: { marginLeft: 4 }
    },
    "Delete"
  )));
}
function ProformaCustomerCard({ resolution, clientName, onRemapOpen }) {
  if (!resolution) return null;
  const r = resolution;
  const matched = !!r.wfirma_customer_id;
  const status = r.match_strategy || r.status || "none";
  const badgeBg = matched ? "var(--badge-green-bg)" : r.ambiguous ? "var(--badge-amber-bg)" : "var(--badge-red-bg)";
  const badgeFg = matched ? "var(--badge-green-text)" : r.ambiguous ? "var(--badge-amber-text)" : "var(--badge-red-text)";
  const badgeLabel = matched ? "mapped" : r.ambiguous ? "ambiguous" : "unmatched";
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "draft-customer-card",
      style: {
        marginBottom: 14,
        padding: 10,
        background: "var(--card-hover)",
        border: "1px solid var(--card-border)",
        borderRadius: 4,
        fontSize: 12
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "flex-start",
      gap: 8,
      marginBottom: 8
    } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 2 } }, "Buyer"), /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, fontSize: 14, color: "var(--text)" } }, clientName || "\u2014")), /* @__PURE__ */ React.createElement("span", { style: {
      background: badgeBg,
      color: badgeFg,
      padding: "2px 8px",
      borderRadius: 4,
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
      whiteSpace: "nowrap",
      flexShrink: 0
    } }, badgeLabel)),
    !matched && /* @__PURE__ */ React.createElement("div", { style: {
      marginBottom: 8,
      padding: "6px 8px",
      borderRadius: 3,
      background: r.ambiguous ? "var(--badge-amber-bg)" : "var(--badge-red-bg)",
      fontSize: 11,
      color: r.ambiguous ? "var(--badge-amber-text)" : "var(--badge-red-text)"
    } }, r.ambiguous ? "Multiple wFirma contractors match this name \u2014 use Customer Master to set the correct one." : "No wFirma contractor found. Create the contractor in wFirma, then re-run auto-resolve.", onRemapOpen && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 8 } }, /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        onClick: onRemapOpen,
        "data-testid": "btn-draft-customer-remap",
        title: "Opens the Customer Master tab \u2014 no write fires from this screen."
      },
      "Open Customer Master"
    ))),
    /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", { style: { fontSize: 10, color: "var(--text-3)", cursor: "pointer", userSelect: "none" } }, "wFirma mapping details"), /* @__PURE__ */ React.createElement("div", { style: {
      marginTop: 6,
      display: "grid",
      gridTemplateColumns: "160px 1fr",
      gap: "3px 8px",
      fontSize: 11
    } }, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "wFirma customer ID"), /* @__PURE__ */ React.createElement("div", { "data-testid": "draft-customer-wfirma-id" }, matched ? /* @__PURE__ */ React.createElement("code", null, r.wfirma_customer_id) : /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "\u2014 unmatched \u2014")), r.resolved_wfirma_name && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "wFirma stored name"), /* @__PURE__ */ React.createElement("div", null, r.resolved_wfirma_name)), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--text-3)" } }, "Match strategy"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      "span",
      {
        style: {
          background: badgeBg,
          color: badgeFg,
          padding: "1px 6px",
          borderRadius: 4,
          fontSize: 10,
          fontWeight: 700,
          textTransform: "uppercase"
        },
        "data-testid": "draft-customer-match-strategy"
      },
      status
    ), r.ambiguous && r.candidates && r.candidates.length > 0 && /* @__PURE__ */ React.createElement("span", { style: { marginLeft: 8, color: "var(--text-3)", fontSize: 11 } }, "candidates: ", r.candidates.slice(0, 4).join(", "), r.candidates.length > 4 ? ` (+${r.candidates.length - 4})` : ""))))
  );
}
function ProformaBillToPicker({ customers, status, onApply, testid }) {
  if (!customers || !customers.length) {
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": testid,
        style: {
          padding: 8,
          border: "1px dashed var(--card-border)",
          borderRadius: 4,
          fontSize: 11,
          color: "var(--text-3)"
        }
      },
      "Bill-to: customer master is empty \u2014 register a customer first."
    );
  }
  const _id = (c) => String(c.bill_to_contractor_id || c.bill_to_name || c.client_name || "");
  const _label = (c) => {
    const name = c.bill_to_name || c.client_name || "?";
    const country = c.country || "";
    const nip = c.nip || c.vat_eu_number || c.vat_id || "";
    return name + (country ? " \xB7 " + country : "") + (nip ? " \xB7 VAT " + nip : "");
  };
  const banner = (() => {
    if (!status) return null;
    const colour = status.phase === "error" ? "#b45309" : status.phase === "done" ? "#065f46" : "var(--text-2)";
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `${testid}-status`,
        style: { fontSize: 11, marginTop: 4, color: colour }
      },
      status.message
    );
  })();
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": testid,
      style: {
        padding: 8,
        border: "1px solid var(--card-border)",
        borderRadius: 4
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: {
      fontSize: 11,
      fontWeight: 700,
      color: "var(--text-3)",
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      marginBottom: 4
    } }, "Bill-to customer"),
    /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--text-3)", marginBottom: 4 } }, "One pick fills buyer, ship-to, and payment terms from the customer master and saves them onto the draft."),
    /* @__PURE__ */ React.createElement(
      "select",
      {
        onChange: (e) => {
          const id = e.target.value;
          const c = customers.find((x) => _id(x) === id);
          e.target.value = "";
          if (c) onApply(c);
        },
        "data-testid": `${testid}-select`,
        disabled: status && status.phase !== "done" && status.phase !== "error",
        style: { fontSize: 12, padding: "4px 6px", minWidth: 280 }
      },
      /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 select bill-to customer \u2014"),
      customers.map((c) => /* @__PURE__ */ React.createElement("option", { key: _id(c), value: _id(c) }, _label(c)))
    ),
    banner
  );
}
function ProformaCustomerPicker({ customers, onPick, testid }) {
  if (!customers || !customers.length) return null;
  const _id = (c) => String(c.bill_to_contractor_id || c.bill_to_name || c.client_name || "");
  const _label = (c) => {
    const name = c.bill_to_name || c.client_name || "?";
    const country = c.country || "";
    const nip = c.nip || c.vat_eu_number || c.vat_id || "";
    return name + (country ? " \xB7 " + country : "") + (nip ? " \xB7 VAT " + nip : "");
  };
  return /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 6, fontSize: 11 } }, /* @__PURE__ */ React.createElement("label", { style: { color: "var(--text-3)", marginRight: 6 } }, "Pick from master:"), /* @__PURE__ */ React.createElement(
    "select",
    {
      onChange: (e) => {
        const id = e.target.value;
        const c = customers.find((x) => _id(x) === id);
        if (c) onPick(c);
        e.target.value = "";
      },
      "data-testid": testid,
      style: {
        fontSize: 12,
        padding: "4px 6px",
        minWidth: 240
      }
    },
    /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 select customer \u2014"),
    customers.map((c) => /* @__PURE__ */ React.createElement("option", { key: _id(c), value: _id(c) }, _label(c)))
  ));
}
function ProformaJsonObjectEditor({
  label,
  fields,
  value,
  editable,
  onSave,
  testidPrefix,
  extras,
  onTypeChange,
  pickerMode
}) {
  const [draft, setDraft] = React.useState({ ...value || {} });
  React.useEffect(() => {
    setDraft({ ...value || {} });
  }, [value]);
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
  const stripped = React.useMemo(() => {
    const out = {};
    Object.keys(draft || {}).forEach((k) => {
      const v = (draft[k] == null ? "" : String(draft[k])).trim();
      if (v !== "") out[k] = v;
    });
    return out;
  }, [draft]);
  const dirty = React.useMemo(() => {
    const a = JSON.stringify(stripped);
    const b = JSON.stringify(value || {});
    return a !== b;
  }, [stripped, value]);
  const isEmpty = Object.keys(value || {}).length === 0;
  const pickFromCustomer = (c) => {
    const next = { ...draft };
    const set_if_blank = (k, v) => {
      const cur = (next[k] == null ? "" : String(next[k])).trim();
      const inc = (v == null ? "" : String(v)).trim();
      if (!cur && inc) next[k] = inc;
    };
    const mode = pickerMode || "buyer";
    if (mode === "payment_terms") {
      set_if_blank("days", c.payment_terms_days);
    } else if (mode === "ship_to") {
      set_if_blank("name", c.ship_to_name || c.bill_to_name || c.client_name);
      set_if_blank("street", c.ship_to_street || c.bill_to_street);
      set_if_blank("city", c.ship_to_city || c.bill_to_city);
      set_if_blank("zip", c.ship_to_postal_code || c.bill_to_postal_code);
      set_if_blank("country", c.ship_to_country || c.country);
      set_if_blank("email", c.ship_to_email || c.bill_to_email);
      set_if_blank("phone", c.ship_to_phone || c.bill_to_phone || c.bill_to_mobile);
      if (!next.type) next.type = "company";
    } else {
      set_if_blank("name", c.bill_to_name || c.client_name);
      set_if_blank("vat_id", c.nip || c.vat_eu_number || c.vat_id);
      set_if_blank("country", c.country);
      set_if_blank("street", c.bill_to_street);
      set_if_blank("city", c.bill_to_city);
      set_if_blank("zip", c.bill_to_postal_code);
      set_if_blank("email", c.bill_to_email);
      set_if_blank("phone", c.bill_to_phone || c.bill_to_mobile);
      if (!next.type) next.type = "company";
    }
    setDraft(next);
  };
  const hasTypeField = !!fields.find((f) => f.key === "type");
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": `${testidPrefix}-editor`,
      style: {
        padding: 8,
        border: "1px solid var(--card-border)",
        borderRadius: 4
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: 6
    } }, /* @__PURE__ */ React.createElement("div", { style: {
      fontSize: 11,
      fontWeight: 700,
      color: "var(--text-3)",
      letterSpacing: "0.06em",
      textTransform: "uppercase"
    } }, label), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "var(--text-3)" } }, isEmpty ? "\u2014 default \u2014" : "override active")),
    editable && extras && (typeof extras === "function" ? extras({ pickFromCustomer }) : extras),
    editable && hasTypeField && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": `${testidPrefix}-type-row`,
        style: {
          display: "flex",
          gap: 10,
          marginBottom: 6,
          fontSize: 11
        }
      },
      /* @__PURE__ */ React.createElement("label", { style: { color: "var(--text-3)" } }, "Type:"),
      ["company", "individual"].map((t) => /* @__PURE__ */ React.createElement("label", { key: t, style: {
        display: "inline-flex",
        gap: 4,
        cursor: "pointer"
      } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "radio",
          name: `${testidPrefix}-type`,
          value: t,
          checked: (draft.type || "company") === t,
          onChange: (e) => set("type", e.target.value),
          "data-testid": `${testidPrefix}-type-${t}`
        }
      ), t))
    ),
    fields.filter((f) => f.key !== "type").map((f) => /* @__PURE__ */ React.createElement("div", { key: f.key, style: {
      display: "flex",
      gap: 6,
      marginBottom: 4,
      alignItems: "baseline"
    } }, /* @__PURE__ */ React.createElement("label", { style: { width: 120, fontSize: 11, color: "var(--text-3)" } }, f.label), editable ? /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: draft[f.key] || "",
        onChange: (e) => set(f.key, e.target.value),
        placeholder: f.placeholder || "",
        "data-testid": `${testidPrefix}-${f.key}`
      }
    ) : /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12 } }, draft[f.key] || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "\u2014")))),
    editable && dirty && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "primary",
        onClick: () => onSave(stripped),
        "data-testid": `btn-${testidPrefix}-save`
      },
      "Save"
    ), /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        onClick: () => setDraft({ ...value || {} }),
        style: { marginLeft: 6 },
        "data-testid": `btn-${testidPrefix}-reset`
      },
      "Revert"
    ))
  );
}
function ProformaAddLineForm({ draftCurrency, onAdd, productOptions }) {
  const [pc, setPc] = React.useState("");
  const [design, setDes] = React.useState("");
  const [qty, setQty] = React.useState("1");
  const [price, setPrice] = React.useState("0");
  const [ccy, setCcy] = React.useState(draftCurrency || "USD");
  const canAdd = pc.trim() !== "" && parseFloat(qty) > 0;
  const handlePcChange = (v) => {
    setPc(v);
    const opt = (productOptions || []).find((o) => o.product_code === v.trim());
    if (opt && !design.trim() && opt.design_no) setDes(opt.design_no);
  };
  const submit = () => {
    const payload = {
      product_code: pc.trim(),
      design_no: design.trim(),
      qty: parseFloat(qty),
      unit_price: parseFloat(price),
      currency: (ccy || draftCurrency || "USD").toUpperCase()
    };
    const p = onAdd(payload);
    if (p && typeof p.then === "function") {
      p.then(() => {
        setPc("");
        setDes("");
        setQty("1");
        setPrice("0");
      }).catch(() => {
      });
    } else {
      setPc("");
      setDes("");
      setQty("1");
      setPrice("0");
    }
  };
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "draft-add-line-form",
      style: {
        display: "flex",
        gap: 6,
        marginTop: 6,
        alignItems: "baseline",
        flexWrap: "wrap",
        fontSize: 12
      }
    },
    /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--text-3)" } }, "Add line:"),
    /* @__PURE__ */ React.createElement(
      "input",
      {
        list: "proforma-add-line-product-codes",
        value: pc,
        onChange: (e) => handlePcChange(e.target.value),
        placeholder: "product_code (canonical) \u2014 type or pick",
        "data-testid": "add-line-pc",
        style: {
          width: 220,
          padding: "8px 10px",
          borderRadius: 6,
          border: "1px solid var(--border)",
          fontSize: 12
        }
      }
    ),
    /* @__PURE__ */ React.createElement("datalist", { id: "proforma-add-line-product-codes" }, (productOptions || []).map((o) => /* @__PURE__ */ React.createElement("option", { key: o.product_code, value: o.product_code }, o.item_type ? `${o.item_type} \xB7 ` : "", o.name_pl || ""))),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: design,
        onChange: (e) => setDes(e.target.value),
        placeholder: "design_no",
        "data-testid": "add-line-design",
        style: { width: 120 }
      }
    ),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: qty,
        onChange: (e) => setQty(e.target.value),
        placeholder: "qty",
        "data-testid": "add-line-qty",
        style: { width: 60 }
      }
    ),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: price,
        onChange: (e) => setPrice(e.target.value),
        placeholder: "unit_price",
        "data-testid": "add-line-price",
        style: { width: 80 }
      }
    ),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: ccy,
        onChange: (e) => setCcy(e.target.value),
        placeholder: "currency",
        "data-testid": "add-line-ccy",
        style: { width: 60 }
      }
    ),
    /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "primary",
        onClick: submit,
        disabled: !canAdd,
        "data-testid": "btn-add-line"
      },
      "Add"
    )
  );
}
function ProformaDraftRemarksEditor({ value, editable, onSave }) {
  const [v, setV] = React.useState(value || "");
  React.useEffect(() => {
    setV(value || "");
  }, [value]);
  return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: {
    fontSize: 11,
    fontWeight: 700,
    color: "var(--text-3)",
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    marginBottom: 4
  } }, "Remarks"), editable ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
    "textarea",
    {
      "data-testid": "draft-remarks-input",
      value: v,
      onChange: (e) => setV(e.target.value),
      style: {
        width: "100%",
        minHeight: 60,
        fontSize: 12,
        padding: 6,
        border: "1px solid var(--card-border)"
      }
    }
  ), v !== (value || "") && /* @__PURE__ */ React.createElement(
    Btn,
    {
      small: true,
      variant: "primary",
      onClick: () => onSave(v),
      "data-testid": "btn-remarks-save"
    },
    "Save remarks"
  )) : /* @__PURE__ */ React.createElement("div", { style: { whiteSpace: "pre-wrap", minHeight: 60 } }, value || /* @__PURE__ */ React.createElement("span", { style: { color: "var(--text-3)" } }, "\u2014 none \u2014")));
}
function ProformaDraftAddChargeForm({
  onAdd,
  draftCurrency,
  lineCurrencies,
  prefill
}) {
  const _firstLineCcy = Array.isArray(lineCurrencies) && lineCurrencies.length ? String(lineCurrencies[0] || "").toUpperCase() : "";
  const _defaultCcy = _firstLineCcy || String(draftCurrency || "").toUpperCase() || "USD";
  const [type, setType] = React.useState("freight");
  const [amount, setAmount] = React.useState("");
  const [ccy, setCcy] = React.useState(_defaultCcy);
  const [label, setLabel] = React.useState("");
  React.useEffect(() => {
    if (!_firstLineCcy) return;
    setCcy((cur) => !cur || cur === _defaultCcy ? _firstLineCcy : cur);
  }, [_firstLineCcy]);
  React.useEffect(() => {
    if (!prefill) return;
    if (prefill.charge_type) setType(prefill.charge_type);
    if (prefill.amount != null) setAmount(String(prefill.amount));
    if (prefill.currency) setCcy(String(prefill.currency).toUpperCase());
    if (prefill.label != null) setLabel(prefill.label);
  }, [prefill]);
  const ccyMismatch = (() => {
    if (!Array.isArray(lineCurrencies) || !lineCurrencies.length) return false;
    return !lineCurrencies.includes(String(ccy || "").toUpperCase());
  })();
  const submit = () => {
    const a = parseFloat(amount);
    if (!isFinite(a) || a < 0) return;
    if (ccyMismatch) return;
    onAdd({
      charge_type: type,
      amount: a,
      currency: String(ccy || "").toUpperCase(),
      label
    });
    setAmount("");
    setLabel("");
  };
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      "data-testid": "draft-add-charge-form",
      style: {
        display: "flex",
        gap: 6,
        marginTop: 6,
        flexWrap: "wrap",
        alignItems: "baseline"
      }
    },
    /* @__PURE__ */ React.createElement(
      Sel,
      {
        value: type,
        onChange: (e) => setType(e.target.value),
        "data-testid": "add-charge-type"
      },
      /* @__PURE__ */ React.createElement("option", { value: "freight" }, "freight"),
      /* @__PURE__ */ React.createElement("option", { value: "insurance" }, "insurance")
    ),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: amount,
        onChange: (e) => setAmount(e.target.value),
        placeholder: "amount",
        "data-testid": "add-charge-amount"
      }
    ),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: ccy,
        onChange: (e) => setCcy(String(e.target.value || "").toUpperCase()),
        placeholder: "ccy",
        "data-testid": "add-charge-ccy"
      }
    ),
    /* @__PURE__ */ React.createElement(
      Inp,
      {
        value: label,
        onChange: (e) => setLabel(e.target.value),
        placeholder: "label (optional)",
        "data-testid": "add-charge-label"
      }
    ),
    /* @__PURE__ */ React.createElement(
      Btn,
      {
        small: true,
        variant: "primary",
        onClick: submit,
        disabled: ccyMismatch,
        "data-testid": "btn-add-charge"
      },
      "Add"
    ),
    ccyMismatch && /* @__PURE__ */ React.createElement(
      "div",
      {
        "data-testid": "add-charge-ccy-mismatch",
        style: { flexBasis: "100%", fontSize: 11, color: "#b45309" }
      },
      "Currency ",
      String(ccy || "").toUpperCase() || "\u2014",
      " does not match this draft's line currencies (",
      lineCurrencies.join(", "),
      "). Update the charge currency to match before adding."
    )
  );
}
function PlaceholderPage({ title, icon, desc }) {
  return /* @__PURE__ */ React.createElement("div", { style: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, color: "var(--text-3)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 48, opacity: 0.3 } }, icon), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 18, fontWeight: 700, color: "var(--text-2)", fontFamily: '"DM Serif Display",serif' } }, title), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "var(--text-3)" } }, desc || "Coming soon"));
}
const CONF_META = {
  unconfirmed: { label: "Unconfirmed", color: "var(--badge-neutral-text)", bg: "var(--badge-neutral-bg)", border: "var(--badge-neutral-border)", bar: "#9AABB8", tip: "0\u20132 parses \u2014 stored but not applied as hints yet" },
  emerging: { label: "Emerging", color: "var(--badge-amber-text)", bg: "var(--badge-amber-bg)", border: "var(--badge-amber-border)", bar: "#E8C040", tip: "3\u20139 confirmed \u2014 used as secondary fallback" },
  stable: { label: "Stable", color: "var(--badge-blue-text)", bg: "var(--badge-blue-bg)", border: "var(--badge-blue-border)", bar: "#4A90D9", tip: "10\u201324 confirmed \u2014 primary extraction hint" },
  trusted: { label: "Trusted", color: "var(--badge-green-text)", bg: "var(--badge-green-bg)", border: "var(--badge-green-border)", bar: "#48C878", tip: "25+ confirmed \u2014 fully reliable, used without fallback" }
};
const CONF_THRESHOLDS = [{ n: 25, k: "trusted" }, { n: 10, k: "stable" }, { n: 3, k: "emerging" }, { n: 0, k: "unconfirmed" }];
function nextThreshold(count) {
  for (const { n, k } of CONF_THRESHOLDS) {
    if (count >= n) {
      const next = CONF_THRESHOLDS[CONF_THRESHOLDS.findIndex((t) => t.k === k) - 1];
      return next ? next.n : null;
    }
  }
  return 3;
}
function ConfBadge({ level }) {
  const m = CONF_META[level] || CONF_META.unconfirmed;
  return /* @__PURE__ */ React.createElement("span", { title: m.tip, style: { display: "inline-flex", alignItems: "center", padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700, background: m.bg, color: m.color, border: `1px solid ${m.border}`, letterSpacing: "0.03em", cursor: "default" } }, m.label);
}
function ConfBar({ count, level }) {
  const m = CONF_META[level] || CONF_META.unconfirmed;
  const next = nextThreshold(count);
  const pct = next ? Math.min(100, Math.round(count / next * 100)) : 100;
  return /* @__PURE__ */ React.createElement("div", { title: next ? `${count} / ${next} confirmations to next level` : "Maximum confidence reached", style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, height: 5, background: "var(--border)", borderRadius: 3, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { height: "100%", width: `${pct}%`, background: m.bar, borderRadius: 3, transition: "width 0.4s" } })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap", minWidth: 48 } }, next ? `${count} / ${next}` : `${count} \u2713`));
}
function SeverityBadge({ severity }) {
  const cfg = {
    HIGH: { bg: "var(--badge-red-bg)", text: "var(--badge-red-text)", border: "var(--badge-red-border)" },
    MEDIUM: { bg: "var(--badge-amber-bg)", text: "var(--badge-amber-text)", border: "var(--badge-amber-border)" },
    LOW: { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" }
  }[severity] || { bg: "var(--badge-neutral-bg)", text: "var(--badge-neutral-text)", border: "var(--badge-neutral-border)" };
  return /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 10, background: cfg.bg, color: cfg.text, border: `1px solid ${cfg.border}`, letterSpacing: "0.04em" } }, severity);
}
const NAV_TREE_INLINE = NAV_TREE;
class TabErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }
  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error && (error.message || String(error)) || "unknown error"
    };
  }
  componentDidCatch(error, info) {
    try {
      console.error("[TabErrorBoundary] caught render error:", error, info);
    } catch (_e) {
    }
  }
  render() {
    if (this.state.hasError) {
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          "data-testid": "tab-error-boundary-fallback",
          style: {
            padding: "40px 32px",
            maxWidth: 720,
            margin: "24px auto",
            background: "var(--card)",
            border: "1px solid var(--badge-red-border)",
            borderRadius: 8,
            color: "var(--text)",
            fontFamily: "inherit"
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: {
          fontSize: 11,
          fontWeight: 700,
          color: "var(--badge-red-text)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 8
        } }, "Render error"),
        /* @__PURE__ */ React.createElement("div", { style: { fontSize: 16, fontWeight: 600, marginBottom: 10 } }, "DHL / Customs tab failed to render"),
        /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "var(--text-2)", marginBottom: 14, lineHeight: 1.5 } }, "Refresh the page or contact support with the browser console error."),
        /* @__PURE__ */ React.createElement(
          "div",
          {
            style: {
              fontSize: 11,
              fontFamily: "monospace",
              color: "var(--text-3)",
              background: "var(--bg-subtle)",
              padding: "8px 10px",
              borderRadius: 4,
              wordBreak: "break-all"
            },
            "data-testid": "tab-error-boundary-message"
          },
          this.state.message
        )
      );
    }
    return this.props.children;
  }
}
function ShipmentDetailApp() {
  const [user, setUser] = React.useState(null);
  const [isDark, setIsDark] = React.useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);
  const [toast, setToast] = React.useState(null);
  const [sessionError, setSessionError] = React.useState(null);
  const params = new URLSearchParams(window.location.search);
  const batchId = (params.get("id") || "").trim();
  const notify = (msg, type = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };
  React.useEffect(() => {
    if (!batchId) {
      window.location.replace("/dashboard/dashboard.html");
      return;
    }
    fetch("/auth/me", { credentials: "include" }).then((r) => {
      if (r.status === 401 || r.status === 403) {
        setSessionError("auth");
        return null;
      }
      return r.ok ? r.json() : null;
    }).then((u) => {
      if (u) setUser(u);
    }).catch(() => setSessionError("network"));
  }, []);
  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "");
  }, [isDark]);
  const handleLogout = async () => {
    await fetch("/auth/logout", { method: "POST", credentials: "include" });
    window.location.href = "/login";
  };
  const goBack = () => {
    window.location.href = "/dashboard/dashboard.html";
  };
  const handleNav = (navId) => {
    window.location.href = "/dashboard/dashboard.html#" + encodeURIComponent(navId);
  };
  if (!batchId) return null;
  return /* @__PURE__ */ React.createElement(React.Fragment, null, sessionError && /* @__PURE__ */ React.createElement(SessionBanner, { type: sessionError, onDismiss: () => setSessionError(null) }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", height: "100vh" } }, /* @__PURE__ */ React.createElement(
    Sidebar,
    {
      active: "shipments",
      onNav: handleNav,
      collapsed: sidebarCollapsed,
      onToggle: () => setSidebarCollapsed((v) => !v),
      navTree: NAV_TREE_INLINE
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(
    TopBar,
    {
      onNewShipment: () => window.location.href = "/dashboard/dashboard.html",
      onToggleDark: () => setIsDark((v) => !v),
      isDark,
      user,
      onLogout: handleLogout
    }
  ), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, overflow: "auto" } }, /* @__PURE__ */ React.createElement(BatchDetailPage, { batchId, onBack: goBack, onToast: notify })))), toast && /* @__PURE__ */ React.createElement(Toast, { msg: toast.msg, type: toast.type }));
}
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(/* @__PURE__ */ React.createElement(ShipmentDetailApp, null));
