// shared.jsx — Shared document mark and logo used by all three renderer modules.
// Extracted from estrella-doc-proforma.jsx (Phase D-2) to avoid duplicating
// EJDocumentLogo across EJDocProforma, EJDocCMR, and EJDocPacking.

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

export { EJDocMark, EJDocumentLogo };
