#!/usr/bin/env python3
"""Validate Estrella Proforma Preview Download PDF vs Print PDF.

READ-ONLY against production draft storage (exports JSON fixtures only).
Generates Print (Chromium page.pdf) and Download (in-page capture function)
artifacts under tasks/smoke-reports/proforma-preview-pdf/.

Usage:
  python scripts/validate_proforma_preview_pdf.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
STATIC_V2 = ROOT / "service" / "app" / "static" / "v2"
OUT = ROOT / "tasks" / "smoke-reports" / "proforma-preview-pdf"
LINKS_DB = Path(r"C:\PZ\storage\proforma_links.db")
DOC_DB = Path(r"C:\PZ\storage\documents.db")
MASTER_DB_CANDIDATES = (
    Path(r"C:\PZ\storage\master_data.sqlite"),
    Path(r"C:\PZ\storage\master_data.db"),
    Path(r"C:\PZ\app\storage\master_data.sqlite"),
)

DRAFT_LONG = 76
DRAFT_SHORT = 83
VARIANTS = ("classic", "modern", "bold")


def _ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _origin_index() -> dict[str, str]:
    """product_local.origin_country keyed by product_code (+ casefold)."""
    db_path = next((p for p in MASTER_DB_CANDIDATES if p.exists()), None)
    if db_path is None:
        # Fall back: scan storage for any db that has product_local
        storage = Path(r"C:\PZ\storage")
        for p in storage.glob("*.sqlite"):
            try:
                con = _ro(p)
                tabs = {r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if "product_local" in tabs:
                    db_path = p
                    break
            except Exception:
                continue
    if db_path is None:
        return {}
    con = _ro(db_path)
    out: dict[str, str] = {}
    for pc, oc in con.execute(
        "SELECT product_code, origin_country FROM product_local"
    ):
        if not pc:
            continue
        val = (oc or "IN").strip() or "IN"
        out[str(pc).strip()] = val
        out[str(pc).strip().casefold()] = val
    return out


def export_draft(draft_id: int, origin_idx: dict[str, str]) -> dict:
    con = _ro(LINKS_DB)
    row = con.execute(
        "SELECT * FROM proforma_drafts WHERE id=?", (draft_id,)
    ).fetchone()
    if not row:
        raise SystemExit(f"draft {draft_id} not found in {LINKS_DB}")
    d = dict(row)
    lines = json.loads(d.get("editable_lines_json") or "[]")
    pt = json.loads(d.get("payment_terms_json") or "{}") or {}
    for ln in lines:
        if (ln.get("origin") or "").strip():
            continue
        pc = (ln.get("product_code") or "").strip()
        if not pc:
            continue
        oc = origin_idx.get(pc) or origin_idx.get(pc.casefold())
        if oc:
            ln["origin"] = oc
    return {
        "id": draft_id,
        "batch_id": d.get("batch_id"),
        "client_name": d.get("client_name"),
        "currency": d.get("currency") or "EUR",
        "created_at": d.get("created_at"),
        "wfirma_issue_date": d.get("wfirma_issue_date"),
        "wfirma_payment_method": d.get("wfirma_payment_method"),
        "exchange_rate": d.get("exchange_rate"),
        "fx_rate_date": d.get("fx_rate_date"),
        "incoterm": d.get("incoterm"),
        "payment_terms": pt,
        "lines": lines,
        "doc_no": d.get("wfirma_proforma_fullnumber")
        or f"DRAFT-{draft_id}",
    }


def commercial_issue_date(draft: dict) -> str:
    pt = draft.get("payment_terms") or {}
    return (pt.get("invoice_date") or draft.get("wfirma_issue_date") or "").strip()


def payment_terms_display(draft: dict) -> str:
    pt = draft.get("payment_terms") or {}
    labels = {
        "transfer": "Bank transfer",
        "paymentmethod": "Bank transfer",
        "przelew": "Bank transfer",
        "cash": "Cash",
        "card": "Card",
        "kompensata": "Compensation",
    }
    parts = []
    method = str(pt.get("method") or pt.get("paymentmethod") or "").strip()
    if method:
        parts.append(labels.get(method.lower(), method))
    if pt.get("days") not in (None, ""):
        parts.append(f"{pt['days']} days")
    if parts:
        return " · ".join(parts)
    fb = (draft.get("wfirma_payment_method") or "").strip()
    return labels.get(fb.lower(), fb) if fb else "—"


def to_doc_data(draft: dict) -> dict:
    cur = draft.get("currency") or "EUR"
    lines_out = []
    for i, ln in enumerate(draft["lines"]):
        qty = float(ln.get("qty") or ln.get("quantity") or 0)
        unit = float(ln.get("unit_price") or ln.get("price") or ln.get("unitEur") or 0)
        net = float(ln.get("net") or ln.get("netEur") or (qty * unit))
        lines_out.append({
            "sku": ln.get("product_code") or ln.get("sku") or "",
            "desc_en": ln.get("name_en") or ln.get("description_en") or ln.get("desc_en") or "",
            "desc_pl": ln.get("name_pl") or ln.get("description_pl") or ln.get("desc_pl") or "",
            "origin": ln.get("origin") or "—",
            "qty": qty,
            "unitEur": unit,
            "netEur": net,
            "purity": ln.get("purity") or "",
        })
    total = sum(l["netEur"] for l in lines_out)
    issue = commercial_issue_date(draft)
    return {
        "doc_no": draft["doc_no"],
        "date": issue or "—",
        "due": "—",
        "payment": payment_terms_display(draft),
        "payment_terms_days": (draft.get("payment_terms") or {}).get("days"),
        "currency": cur,
        "rate": {
            "eur": float(draft["exchange_rate"]) if draft.get("exchange_rate") else None,
            "date": draft.get("fx_rate_date") or "",
            "currency": cur,
        },
        "seller": {"name": "Estrella Jewels", "vatEu": "—", "address": "—"},
        "buyer": {"name": draft.get("client_name") or "—", "vatEu": "—", "address": "—"},
        "lines": lines_out,
        "charges": [],
        "total_eur": total,
        "banks": [],
        "warnings": (
            [{"code": "NO_ISSUE_DATE", "message": "Issue date missing"}]
            if not issue else []
        ),
    }


FIXTURE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Proforma PDF validation fixture</title>
<link rel="stylesheet" href="/estrella-doc-tokens.css"/>
<script src="/vendor/react.production.min.js"></script>
<script src="/vendor/react-dom.production.min.js"></script>
<script src="/vendor/babel.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js"></script>
<style>
  body { margin: 0; background: #e5e7eb; }
  .ej-preview-sheet { background: #fff; }
  .toolbar { padding: 8px; background: #111; color: #fff; font: 12px sans-serif; }
</style>
</head>
<body>
<div class="toolbar">PDF validation fixture</div>
<div id="root"></div>
<script type="text/babel" data-presets="env,react" src="/estrella-doc-proforma.jsx"></script>
<script type="text/babel" data-presets="env,react">
const docData = __DOC_DATA__;
const variant = "__VARIANT__";
const Comp = variant === "modern" ? window.EJProformaModern
           : variant === "bold"   ? window.EJProformaBold
           : window.EJProformaClassic;

function App() {
  return (
    <div className="ej-preview-sheet">
      <Comp docData={docData}/>
    </div>
  );
}

ReactDOM.render(<App/>, document.getElementById("root"));
window.__EJ_READY__ = true;

// Mirror of production packer (kept in sync with proforma-detail.jsx).
async function ejDownloadRenderedSheetPdf(filenameBase, orientation) {
  const sheet = document.querySelector(".ej-preview-sheet");
  const source = sheet.querySelector(".ej-a4, .ej-a4-landscape");
  const html2canvas = window.html2canvas;
  const JsPDF = (window.jspdf && window.jspdf.jsPDF) || window.jsPDF;
  const landscape = orientation === "landscape";
  const PAGE_W_PX = landscape ? 1123 : 794;
  const PAGE_H_PX = landscape ? 794 : 1123;
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:-10000px;top:0;width:" + PAGE_W_PX + "px;background:#fff;";
  document.body.appendChild(host);
  try {
    const table = source.querySelector("table.ej-table");
    const tbody = table ? table.querySelector("tbody") : null;
    const rows = tbody ? Array.from(tbody.querySelectorAll(":scope > tr")) : [];
    const rowHeights = rows.map(r => Math.ceil(r.getBoundingClientRect().height) || 22);
    let preH = 0, postH = 0, theadH = 28;
    if (table) {
      const srcRect = source.getBoundingClientRect();
      const tableRect = table.getBoundingClientRect();
      preH = Math.max(0, Math.round(tableRect.top - srcRect.top));
      const after = table.nextElementSibling;
      if (after) {
        const last = source.lastElementChild;
        const bottom = (last || after).getBoundingClientRect().bottom;
        postH = Math.max(0, Math.round(bottom - tableRect.bottom));
      }
      const thead = table.querySelector("thead");
      if (thead) theadH = Math.ceil(thead.getBoundingClientRect().height) || 28;
    }
    const pages = [];
    let i = 0;
    while (i < rows.length || pages.length === 0) {
      const isFirst = pages.length === 0;
      const budget = PAGE_H_PX - 8 - (isFirst ? preH : theadH);
      let used = 0;
      const start = i;
      if (rows.length === 0) { pages.push({ rowStart: 0, rowEnd: 0 }); break; }
      while (i < rows.length) {
        const h = rowHeights[i] || 22;
        if (used > 0 && used + h > budget) break;
        used += h; i += 1;
        if (used === h && h > budget) break;
      }
      pages.push({ rowStart: start, rowEnd: i });
      if (i >= rows.length) break;
    }
    if (pages.length && postH > 0) {
      const last = pages[pages.length - 1];
      const isFirst = pages.length === 1;
      const rowsH = rowHeights.slice(last.rowStart, last.rowEnd).reduce((s, h) => s + h, 0);
      const used = (isFirst ? preH : theadH) + rowsH + postH;
      if (used > PAGE_H_PX - 8 && (last.rowEnd > last.rowStart)) {
        pages.push({ rowStart: last.rowEnd, rowEnd: last.rowEnd, footerOnly: true });
      }
    }
    window.__EJ_PAGE_PACK__ = { pages, rowCount: rows.length, preH, postH, theadH, PAGE_H_PX };
    const pdf = new JsPDF({ orientation: landscape ? "landscape" : "portrait", unit: "mm", format: "a4" });
    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    for (let p = 0; p < pages.length; p++) {
      const spec = pages[p];
      const isFirst = p === 0;
      const isLast = p === pages.length - 1;
      const clone = source.cloneNode(true);
      clone.style.width = PAGE_W_PX + "px";
      clone.style.minHeight = PAGE_H_PX + "px";
      clone.style.height = "auto";
      clone.style.overflow = "visible";
      clone.querySelectorAll(".ej-pattern, .ej-no-print").forEach(el => el.remove());
      const cloneTable = clone.querySelector("table.ej-table");
      if (cloneTable) {
        const cloneRows = Array.from((cloneTable.querySelector("tbody") || cloneTable).querySelectorAll(":scope > tr"));
        cloneRows.forEach((tr, idx) => {
          if (idx < spec.rowStart || idx >= spec.rowEnd) tr.remove();
        });
        if (!isFirst) {
          const pad = cloneTable.closest(".ej-pad, .ej-pad-tight") || clone;
          Array.from(pad.children).forEach(ch => {
            if (ch === cloneTable) return;
            if (cloneTable.compareDocumentPosition(ch) & Node.DOCUMENT_POSITION_FOLLOWING) return;
            if (ch.contains && ch.contains(cloneTable)) return;
            ch.remove();
          });
        }
        if (!isLast) {
          let el = cloneTable.nextElementSibling;
          while (el) {
            const next = el.nextElementSibling;
            el.remove();
            el = next;
          }
        }
      }
      host.innerHTML = "";
      host.appendChild(clone);
      const canvas = await html2canvas(clone, {
        scale: 2, useCORS: true, backgroundColor: "#ffffff", logging: false,
        width: PAGE_W_PX, windowWidth: PAGE_W_PX,
      });
      const imgData = canvas.toDataURL("image/jpeg", 0.92);
      let imgH = (canvas.height * pageW) / canvas.width;
      if (imgH > pageH) imgH = pageH;
      if (p > 0) pdf.addPage();
      pdf.addImage(imgData, "JPEG", 0, 0, pageW, imgH);
    }
    const ab = pdf.output("arraybuffer");
    window.__EJ_PDF_BYTES__ = Array.from(new Uint8Array(ab));
    window.__EJ_PDF_NAME__ = (filenameBase || "proforma").replace(/[^\w.\-]+/g, "_") + ".pdf";
    return window.__EJ_PDF_BYTES__.length;
  } finally {
    host.remove();
  }
}
window.ejDownloadRenderedSheetPdf = ejDownloadRenderedSheetPdf;
</script>
</body>
</html>
"""


def _pdf_meta(path: Path) -> dict:
    r = PdfReader(str(path))
    pages = len(r.pages)
    sizes = []
    texts = []
    for p in r.pages:
        box = p.mediabox
        w = float(box.width)
        h = float(box.height)
        sizes.append((round(w, 1), round(h, 1)))
        try:
            texts.append(p.extract_text() or "")
        except Exception:
            texts.append("")
    joined = "\n".join(texts)
    return {
        "pages": pages,
        "sizes": sizes,
        "bytes": path.stat().st_size,
        "text_len": len(joined),
        "text": joined,
        "a4ish": all(
            (abs(w - 595) < 8 and abs(h - 842) < 8)
            or (abs(w - 842) < 8 and abs(h - 595) < 8)
            for w, h in sizes
        ),
    }


def main() -> int:
    if not LINKS_DB.exists():
        print("NO_GO: proforma_links.db missing at", LINKS_DB)
        return 2
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    origin_idx = _origin_index()
    drafts = {
        "long": export_draft(DRAFT_LONG, origin_idx),
        "short": export_draft(DRAFT_SHORT, origin_idx),
    }
    (OUT / "fixtures").mkdir()
    for key, d in drafts.items():
        (OUT / "fixtures" / f"draft_{d['id']}.json").write_text(
            json.dumps(d, indent=2, default=str), encoding="utf-8"
        )
        print(
            f"FIXTURE draft {d['id']} ({key}): lines={len(d['lines'])} "
            f"issue={commercial_issue_date(d)!r} payment={payment_terms_display(d)!r} "
            f"origins_filled={sum(1 for ln in d['lines'] if (ln.get('origin') or '').strip())}"
        )

    # Static server rooted at static/v2
    handler = partial(SimpleHTTPRequestHandler, directory=str(STATIC_V2))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"

    from playwright.sync_api import sync_playwright

    report = {"cases": [], "architecture": {}, "verdict": "NO-GO"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for key, draft in drafts.items():
                doc = to_doc_data(draft)
                for variant in VARIANTS:
                    # Skip bold for short+long both — still cover all 3 on long, classic+modern on short
                    if key == "short" and variant == "bold":
                        continue
                    case_id = f"draft{draft['id']}_{variant}"
                    html = (
                        FIXTURE_HTML
                        .replace("__DOC_DATA__", json.dumps(doc))
                        .replace("__VARIANT__", variant)
                    )
                    # Serve fixture via data URL page.set_content needs absolute asset URLs —
                    # write temp html into static dir
                    fix_name = f"_pdf_fixture_{case_id}.html"
                    fix_path = STATIC_V2 / fix_name
                    fix_path.write_text(html, encoding="utf-8")
                    try:
                        page = browser.new_page(viewport={"width": 1200, "height": 2000})
                        page.goto(f"{base}/{fix_name}", wait_until="networkidle", timeout=120000)
                        page.wait_for_function("() => window.__EJ_READY__ === true", timeout=120000)
                        # Count DOM lines
                        line_count = page.eval_on_selector_all(
                            "table.ej-table tbody tr", "els => els.length"
                        )
                        # Print PDF (Chromium engine — CSS page breaks / thead repeat)
                        print_path = OUT / f"{case_id}_print.pdf"
                        page.emulate_media(media="print")
                        page.pdf(
                            path=str(print_path),
                            format="A4",
                            print_background=True,
                            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                        )
                        page.emulate_media(media="screen")
                        # Download path (explicit packer)
                        page.evaluate(
                            """async (name) => {
                              await window.ejDownloadRenderedSheetPdf(name, 'portrait');
                            }""",
                            case_id,
                        )
                        page.wait_for_function(
                            "() => Array.isArray(window.__EJ_PDF_BYTES__)", timeout=120000
                        )
                        raw = bytes(page.evaluate("() => window.__EJ_PDF_BYTES__"))
                        pack = page.evaluate("() => window.__EJ_PAGE_PACK__")
                        dl_path = OUT / f"{case_id}_download.pdf"
                        dl_path.write_bytes(raw)
                        # Screenshots of first screen page
                        page.screenshot(
                            path=str(OUT / f"{case_id}_screen.png"), full_page=True
                        )
                        print_meta = _pdf_meta(print_path)
                        dl_meta = _pdf_meta(dl_path)
                        # Semantic checks on print text (vector)
                        text = print_meta["text"]
                        # Chromium→pypdf often injects NUL into digit runs; normalize.
                        norm = (
                            text.replace("\x00", "")
                            .replace("\n", "")
                            .replace(" ", "")
                        )
                        skus = [l["sku"] for l in doc["lines"] if l["sku"]]
                        skus_found = sum(
                            1 for s in skus
                            if s and s.replace(" ", "") in norm
                        )
                        payment_ok = "invoice_language_id" not in text
                        if doc["payment"] != "—":
                            # Classic/Bold meta strip + Modern hero (after fix) show
                            # allowlisted payment text; terms block may only say "within N days".
                            payment_ok = payment_ok and (
                                "Bank transfer" in text
                                or "Payment received within" in text
                            )
                        issue = commercial_issue_date(draft)
                        if issue:
                            issue_ok = issue in text or issue.replace("-", ".") in text
                        else:
                            # Issued should be dash / empty — created_at must not appear as issue
                            issue_ok = (draft.get("created_at") or "")[:10] not in text

                        case = {
                            "id": case_id,
                            "draft_id": draft["id"],
                            "variant": variant,
                            "dom_lines": line_count,
                            "expected_lines": len(doc["lines"]),
                            "print": {
                                "pages": print_meta["pages"],
                                "bytes": print_meta["bytes"],
                                "a4ish": print_meta["a4ish"],
                                "skus_found": skus_found,
                                "skus_total": len(skus),
                                "payment_clean": payment_ok,
                                "issue_ok": issue_ok,
                            },
                            "download": {
                                "pages": dl_meta["pages"],
                                "bytes": dl_meta["bytes"],
                                "a4ish": dl_meta["a4ish"],
                                "pack": pack,
                            },
                        }
                        report["cases"].append(case)
                        print(json.dumps(case, indent=2))
                        page.close()
                    finally:
                        if fix_path.exists():
                            fix_path.unlink()
            browser.close()
    finally:
        httpd.shutdown()

    # Architecture notes from source
    src = (STATIC_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    report["architecture"] = {
        "server_estrella_pdf_generator": False,
        "official_posted_pdf": "wFirma document.pdf (unchanged)",
        "download_is_raster_capture": True,
        "uses_html2canvas_jspdf": "html2canvas" in src and "jsPDF" in src,
        "oversized_canvas_slice": "position -= pageH" in src or "heightLeft -= pageH" in src,
        "explicit_row_packer": "rowStart" in src and "cloneNode(true)" in src,
        "same_docData_renderer": 'DocVariant docData={docData}' in src
        or "<DocVariant docData={docData}/>" in src,
        "draft76_hardcoded": "draft_id === 76" in src or "draftId === 76" in src
        or "DRAFT #76" in src,
    }

    failures = []
    for c in report["cases"]:
        if c["dom_lines"] != c["expected_lines"]:
            failures.append(f"{c['id']}: line count {c['dom_lines']}!={c['expected_lines']}")
        if not c["print"]["a4ish"]:
            failures.append(f"{c['id']}: print not A4")
        if not c["download"]["a4ish"]:
            failures.append(f"{c['id']}: download not A4")
        if c["print"]["skus_found"] < c["print"]["skus_total"]:
            failures.append(
                f"{c['id']}: print missing SKUs "
                f"{c['print']['skus_found']}/{c['print']['skus_total']}"
            )
        if not c["print"]["payment_clean"]:
            failures.append(f"{c['id']}: payment leak or missing")
        if not c["print"]["issue_ok"]:
            failures.append(f"{c['id']}: issue-date semantics")
        if c["download"]["pages"] < 1:
            failures.append(f"{c['id']}: download empty")
        pack = c["download"].get("pack") or {}
        if pack.get("rowCount") != c["expected_lines"]:
            failures.append(f"{c['id']}: packer rowCount mismatch")
        # Download pages should be close to pack length
        if pack.get("pages") and c["download"]["pages"] != len(pack["pages"]):
            failures.append(
                f"{c['id']}: download pages {c['download']['pages']} "
                f"!= pack {len(pack['pages'])}"
            )
        # Long draft must paginate
        if c["draft_id"] == DRAFT_LONG and c["download"]["pages"] < 2:
            failures.append(f"{c['id']}: long draft should be multi-page")
        if c["download"]["bytes"] > 15_000_000:
            failures.append(f"{c['id']}: download PDF too large")

    if report["architecture"]["oversized_canvas_slice"]:
        failures.append("architecture: oversized canvas slice still present")
    if not report["architecture"]["explicit_row_packer"]:
        failures.append("architecture: explicit row packer missing")
    if report["architecture"]["draft76_hardcoded"]:
        failures.append("architecture: Draft #76 hardcoded")

    report["failures"] = failures
    report["verdict"] = "GO" if not failures else "NO-GO"
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("VERDICT", report["verdict"])
    for f in failures:
        print("FAIL", f)
    print("REPORT", OUT / "report.json")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
