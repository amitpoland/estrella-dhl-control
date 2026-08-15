"""Canonical Packing List HTML presentation — THE sole Packing List visual definition.

Preview displays this HTML. Chrome headless prints this same HTML to PDF.
Do not maintain a parallel JSX Packing List layout for operator Preview.
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional


def _fmt_money(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    # Match commercial packing list en-IN grouping + 2 dp
    s = f"{n:,.2f}"
    # Keep 2 decimal places like the printed packing list.
    return s


def _fmt_wt(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n <= 0:
        return "—"
    return f"{n:.4f}"


def _party_html(n: str, label: str, data: Optional[Dict[str, Any]], *, border_left: bool = False) -> str:
    p = data or {}
    border = "border-left:1px solid #CBD5E1;" if border_left else ""
    parts = [
        f'<div style="padding:8px 10px;{border}font-size:10px;">',
        f'<div style="font-size:8px;color:#64748B;font-weight:600;margin-bottom:3px;">'
        f'<span style="background:#0B3D2E;color:#fff;padding:1px 5px;border-radius:2px;'
        f'margin-right:5px;">{escape(n)}</span>{escape(label)}</div>',
    ]
    if p.get("name"):
        parts.append(
            f'<div style="font-weight:600;font-size:10px;color:#0F172A;">{escape(str(p["name"]))}</div>'
        )
    if p.get("addr"):
        parts.append(
            f'<div style="font-size:9px;color:#475569;margin-top:1px;">{escape(str(p["addr"]))}</div>'
        )
    loc_bits = [str(x) for x in (p.get("zip"), p.get("city")) if x]
    loc = " ".join(loc_bits)
    if loc or p.get("country"):
        country = f", {p['country']}" if p.get("country") else ""
        parts.append(
            f'<div style="font-size:9px;color:#475569;">{escape(loc + country)}</div>'
        )
    if p.get("vat"):
        parts.append(
            f'<div style="font-size:8.5px;color:#64748B;margin-top:2px;">'
            f'VAT EU · {escape(str(p["vat"]))}</div>'
        )
    if p.get("email"):
        parts.append(
            f'<div style="font-size:8.5px;color:#64748B;">{escape(str(p["email"]))}</div>'
        )
    parts.append("</div>")
    return "".join(parts)


def _logo_data_uri() -> str:
    """Embed Estrella logo so Chrome file:// print does not depend on HTTP."""
    candidates = [
        Path(__file__).resolve().parents[1] / "static" / "v2" / "assets" / "estrella-logo.png",
        Path(__file__).resolve().parents[1] / "static" / "assets" / "estrella-logo.png",
    ]
    for path in candidates:
        if path.is_file():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    return ""


def render_commercial_packing_list_html(document: Dict[str, Any]) -> str:
    """Return the sole Packing List HTML presentation (Preview iframe + Chrome PDF)."""
    d = document or {}
    rows: List[Dict[str, Any]] = list(d.get("rows") or [])
    cur = str(d.get("currency") or "EUR")
    try:
        grand_total = float(d["grand_total"]) if d.get("grand_total") is not None else sum(
            float(r.get("total_value") or 0) for r in rows
        )
    except (TypeError, ValueError):
        grand_total = 0.0
    try:
        total_qty = int(d["total_qty"]) if d.get("total_qty") is not None else sum(
            int(r.get("qty") or 0) for r in rows
        )
    except (TypeError, ValueError):
        total_qty = 0

    logo_src = _logo_data_uri()
    logo_html = (
        f'<img class="ej-document-logo" src="{logo_src}" alt="Estrella Jewels"/>'
        if logo_src
        else '<div style="font-weight:700;color:#0B3D2E;font-size:14px;letter-spacing:0.12em;">'
             "ESTRELLA JEWELS</div>"
    )

    meta_items = [
        ("Date", str(d.get("issued_date") or "—")),
        ("Proforma", str(d.get("doc_ref") or "—")),
        ("Invoice", str(d.get("invoice_ref") or "Pending conversion")),
        ("Currency", cur),
        ("Lines", str(len(rows))),
        ("Total Qty", str(total_qty)),
        ("Grand Total", f"{cur} {_fmt_money(grand_total)}"),
    ]
    meta_html = "".join(
        f'<div><span style="color:#64748B;font-weight:600;">{escape(k)}: </span>'
        f'<span style="font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:500;">'
        f"{escape(v)}</span></div>"
        for k, v in meta_items
    )

    body_rows = []
    if not rows:
        body_rows.append(
            '<tr><td colspan="18" style="text-align:center;color:#94A3B8;padding:20px;'
            'font-size:11px;">No packing lines loaded.</td></tr>'
        )
    else:
        for ri, r in enumerate(rows):
            bg = "#FFFFFF" if ri % 2 == 0 else "#FAFBFC"
            en = (r.get("description_en") or "").strip()
            pl = (r.get("description_pl") or "").strip()
            if en or pl:
                desc_parts = []
                if en:
                    desc_parts.append(f"<div>{escape(en)}</div>")
                if pl:
                    desc_parts.append(
                        f'<div style="color:#475569;font-style:italic;margin-top:1px;">'
                        f"{escape(pl)}</div>"
                    )
                desc = "".join(desc_parts)
            else:
                desc = "—"
            body_rows.append(
                f'<tr style="background:{bg};">'
                f'<td class="c n" style="padding:3px;">{escape(str(r.get("sr") or ""))}</td>'
                f'<td style="padding:3px;">{escape(str(r.get("ctg") or "—"))}</td>'
                f'<td class="m" style="padding:3px;font-size:7px;">{escape(str(r.get("client_po") or "—"))}</td>'
                f'<td class="m" style="padding:3px;font-size:7px;">{escape(str(r.get("product_code") or "—"))}</td>'
                f'<td style="font-weight:600;padding:3px;">{escape(str(r.get("design") or "—"))}</td>'
                f'<td style="padding:3px 4px;white-space:normal;line-height:1.25;">{desc}</td>'
                f'<td class="c m" style="padding:3px;">{escape(str(r.get("kt") or "—"))}</td>'
                f'<td class="c m" style="padding:3px;">{escape(str(r.get("col") or "—"))}</td>'
                f'<td class="c" style="padding:3px;">{escape(str(r.get("quality") or "—"))}</td>'
                f'<td class="r n" style="padding:3px;color:#94A3B8;">{_fmt_wt(r.get("dia_wt"))}</td>'
                f'<td class="r n" style="padding:3px;color:#94A3B8;">{_fmt_wt(r.get("col_wt"))}</td>'
                f'<td class="r n" style="padding:3px;color:#94A3B8;">{_fmt_wt(r.get("gross_wt"))}</td>'
                f'<td class="r n" style="padding:3px;color:#94A3B8;">{_fmt_wt(r.get("net_wt"))}</td>'
                f'<td class="r n" style="padding:3px;font-weight:600;">{escape(str(r.get("qty") if r.get("qty") is not None else ""))}</td>'
                f'<td class="r n" style="padding:3px;">{_fmt_money(r.get("unit_price"))}</td>'
                f'<td class="r n" style="padding:3px;font-weight:600;">{_fmt_money(r.get("total_value"))}</td>'
                f'<td class="c m" style="padding:3px;font-size:7px;">{escape(str(r.get("size") or "—"))}</td>'
                f'<td class="c m" style="padding:3px;font-size:7px;">{escape(str(r.get("origin") or "—"))}</td>'
                f"</tr>"
            )

    invoice_ref_block = ""
    if d.get("invoice_ref"):
        invoice_ref_block = (
            f'<div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10px;'
            f'color:#475569;margin-top:1px;">Invoice · {escape(str(d["invoice_ref"]))}</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Packing List — {escape(str(d.get("doc_ref") or ""))}</title>
<style>
  :root {{
    --ej-ink:#0F172A; --ej-mute:#64748B; --ej-line:#E2E8F0; --ej-brand:#0B3D2E;
    --ej-gold:#C9A24B; --ej-cream:#FBF8F1; --ej-paper:#FFFFFF;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; background:#fff; color:var(--ej-ink);
    font-family: Inter, "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  @page {{ size: A4 landscape; margin: 0.5cm; }}
  .ej-band {{ height:6px; background:linear-gradient(90deg, var(--ej-brand) 0 65%, var(--ej-gold) 65% 100%); }}
  .ej-pad {{ padding: 20px 28px; }}
  .ej-document-logo {{ display:block; max-width:180px; max-height:52px; object-fit:contain; }}
  .ej-eyebrow {{ font-size:9px; letter-spacing:0.14em; text-transform:uppercase; font-weight:600; color:var(--ej-gold); }}
  .ej-h1 {{ font-size:22px; font-weight:700; color:var(--ej-brand); margin:0; }}
  table.ej-table {{ width:100%; border-collapse:collapse; font-size:7.5px; table-layout:fixed; margin-bottom:14px; }}
  table.ej-table th {{ text-align:left; font-weight:700; color:var(--ej-brand); border-bottom:1px solid var(--ej-line);
    padding:5px 3px; background:#fff; }}
  table.ej-table td {{ border-bottom:1px solid var(--ej-line); vertical-align:top; }}
  .c {{ text-align:center; }} .r {{ text-align:right; }}
  .n, .m {{ font-family: ui-monospace, Menlo, Consolas, monospace; }}
  thead {{ display: table-header-group; }}
  tfoot {{ display: table-footer-group; }}
  tr {{ page-break-inside: avoid; }}
</style>
</head>
<body>
<div class="ej-band"></div>
<div class="ej-pad">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
    {logo_html}
    <div style="text-align:right;">
      <div class="ej-eyebrow">Commercial Packing List</div>
      <div class="ej-h1" style="margin-top:2px;">Packing List</div>
      <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#0B3D2E;font-weight:600;margin-top:3px;">
        {escape(str(d.get("doc_ref") or "—"))}
      </div>
      {invoice_ref_block}
    </div>
  </div>

  <div style="border:1.5px solid #0B3D2E;border-radius:4px;overflow:hidden;margin-bottom:10px;
              display:grid;grid-template-columns:1fr 1fr;">
    {_party_html("1", "Seller · Exporter", d.get("seller"))}
    {_party_html("2", "Consignee · Ship-To", d.get("shipto"), border_left=True)}
  </div>

  <div style="display:flex;gap:22px;flex-wrap:wrap;padding:5px 10px;background:#F8FAFC;
              border:1px solid #E2E8F0;border-radius:4px;margin-bottom:10px;font-size:8.5px;">
    {meta_html}
  </div>

  <table class="ej-table">
    <thead>
      <tr style="border-top:2px solid #0B3D2E;">
        <th style="width:22px;text-align:center;">Sr</th>
        <th style="width:52px;">Category</th>
        <th style="width:68px;">Client PO</th>
        <th style="width:86px;">Product Code</th>
        <th style="width:96px;">Design</th>
        <th style="width:180px;">Product Description (EN / PL)</th>
        <th style="width:30px;text-align:center;">Kt</th>
        <th style="width:24px;text-align:center;">Col</th>
        <th style="width:46px;text-align:center;">Quality</th>
        <th style="width:44px;text-align:right;">Dia Wt (ct)</th>
        <th style="width:44px;text-align:right;">Col Wt (ct)</th>
        <th style="width:48px;text-align:right;">Gross Wt (g)</th>
        <th style="width:44px;text-align:right;">Net Wt (g)</th>
        <th style="width:28px;text-align:right;">Qty</th>
        <th style="width:58px;text-align:right;">Value&nbsp;({escape(cur)})</th>
        <th style="width:68px;text-align:right;">Total Value</th>
        <th style="width:40px;text-align:center;">Size</th>
        <th style="width:40px;text-align:center;">Origin</th>
      </tr>
    </thead>
    <tbody>
      {"".join(body_rows)}
    </tbody>
    <tfoot>
      <tr style="border-top:2px solid #0B3D2E;background:#FBF8F1;font-weight:700;">
        <td colspan="2" style="padding:5px 6px;color:#0B3D2E;font-size:8.5px;">{len(rows)} design(s)</td>
        <td colspan="11" style="padding:5px 4px;"></td>
        <td class="r n" style="padding:5px 6px;font-size:8.5px;">{total_qty}</td>
        <td style="padding:5px 4px;"></td>
        <td class="r n" style="padding:5px 6px;font-size:8.5px;">{escape(cur)} {_fmt_money(grand_total)}</td>
        <td colspan="2" style="padding:5px 4px;"></td>
      </tr>
    </tfoot>
  </table>

  <div style="display:flex;justify-content:space-between;font-size:8px;color:#94A3B8;
              border-top:1px solid #E2E8F0;padding-top:8px;">
    <span>Issued under the authority of Proforma {escape(str(d.get("doc_ref") or "—"))}.
      Value authority: commercial sales price. Not for customs valuation.</span>
    <span>Currency: {escape(cur)} · {escape(str(d.get("issued_date") or "—"))}</span>
  </div>
</div>
</body>
</html>
"""
