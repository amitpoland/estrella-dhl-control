"""Canonical CMR HTML presentation — THE sole CMR visual definition.

Preview displays this HTML. Chrome headless prints this same HTML to PDF.
Do not maintain a parallel JSX CMR layout for operator Preview.
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional


def _logo_data_uri() -> str:
    candidates = [
        Path(__file__).resolve().parents[1] / "static" / "v2" / "assets" / "estrella-logo.png",
        Path(__file__).resolve().parents[1] / "static" / "assets" / "estrella-logo.png",
    ]
    for path in candidates:
        if path.is_file():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    return ""


def _box(n: str, label: str, body: str, *, border_left: bool = False) -> str:
    border = "border-left:1px solid #CBD5E1;" if border_left else ""
    return (
        f'<div style="padding:8px 10px;{border}font-size:10px;">'
        f'<div style="font-size:8px;color:#64748B;font-weight:600;margin-bottom:3px;">'
        f'<span style="background:#0B3D2E;color:#fff;padding:1px 5px;border-radius:2px;'
        f'margin-right:5px;">{escape(n)}</span>{escape(label)}</div>'
        f'<div>{body}</div></div>'
    )


def _sig_box(n: str, label: str, who: str, *, border_left: bool = False) -> str:
    border = "border-left:1px solid #CBD5E1;" if border_left else ""
    return (
        f'<div style="padding:10px 12px;{border}min-height:100px;">'
        f'<div style="font-size:8px;color:#64748B;font-weight:600;margin-bottom:4px;">'
        f'<span style="background:#0B3D2E;color:#fff;padding:1px 5px;border-radius:2px;'
        f'margin-right:5px;">{escape(n)}</span>{escape(label)}</div>'
        f'<div style="border-top:1px dashed #CBD5E1;margin-top:60px;padding-top:4px;'
        f'font-size:9px;color:#94A3B8;">{escape(who or "—")}</div></div>'
    )


def _carrier_chip(name: Optional[str]) -> str:
    if not name:
        return ""
    is_dhl = "DHL" in str(name).upper()
    bg = "#FFCC00" if is_dhl else "#E2E8F0"
    fg = "#D40511" if is_dhl else "#334155"
    label = "DHL" if is_dhl else str(name)[:6].upper()
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f'background:{bg};color:{fg};font-weight:900;font-size:11px;padding:2px 7px;'
        f'border-radius:3px;letter-spacing:0.04em;">{escape(label)}</span>'
    )


def render_commercial_cmr_html(document: Dict[str, Any]) -> str:
    """Return full HTML matching EJCMRClassic visual structure."""
    d = document or {}
    seller = d.get("seller") or {}
    shipto = d.get("shipto") or {}
    buyer = d.get("buyer") or {}
    carrier = d.get("carrier")
    lines: List[Dict[str, Any]] = list(d.get("lines") or [])
    total_kg = float((carrier or {}).get("weight_kg") or 0) if carrier else 0.0
    tot_qty = sum(float(l.get("qty") or 0) for l in lines)
    tot_nw = sum(float(l.get("net_weight") or 0) for l in lines if l.get("net_weight"))

    logo_src = _logo_data_uri()
    logo_html = (
        f'<img src="{logo_src}" alt="Estrella Jewels" style="height:36px;"/>'
        if logo_src
        else '<div style="font-weight:700;color:#0B3D2E;font-size:14px;letter-spacing:0.12em;">'
             "ESTRELLA JEWELS</div>"
    )

    seller_body = (
        f'<div style="font-weight:600;">{escape(str(seller.get("name") or "—"))}</div>'
        + (f'<div>{escape(str(seller["addr"]))}</div>' if seller.get("addr") else "")
        + (f'<div>{escape(str(seller["city"]))}</div>' if seller.get("city") else "")
        + (
            f'<div style="margin-top:3px;color:#475569;">VAT EU · {escape(str(seller["vat"]))}</div>'
            if seller.get("vat")
            else ""
        )
    )
    shipto_body = (
        f'<div style="font-weight:600;">{escape(str(shipto.get("name") or "—"))}</div>'
        + (f'<div>{escape(str(shipto["addr"]))}</div>' if shipto.get("addr") else "")
        + (
            f'<div>{escape(str(shipto.get("city") or ""))}'
            f'{(", " + escape(str(shipto["country"]))) if shipto.get("country") else ""}</div>'
            if shipto.get("city") or shipto.get("country")
            else ""
        )
        + (
            f'<div style="margin-top:3px;color:#475569;">VAT EU · {escape(str(buyer["vat"]))}</div>'
            if buyer.get("vat")
            else ""
        )
    )
    place_delivery = ", ".join(
        str(x) for x in (shipto.get("city") or "—", shipto.get("zip"), shipto.get("country")) if x
    )
    taking_over = "—"
    if carrier:
        taking_over = f'{carrier.get("origin") or "—"} · {carrier.get("pickup") or "—"}'
    docs_attached = (
        f'Proforma {d.get("doc_ref")} · Packing list' if d.get("doc_ref") else "Packing list"
    )

    goods_block = ""
    if d.get("goods_summary"):
        origin_span = (
            f'<span style="margin-left:10px;color:#64748B;">Country of Origin: '
            f'{escape(str(d["goods_origin_country"]))}</span>'
            if d.get("goods_origin_country")
            else ""
        )
        goods_block = (
            '<div style="border-top:1px solid #CBD5E1;padding:8px 10px;background:#F8FAFC;font-size:9.5px;">'
            f'<span style="color:#475569;font-weight:600;">Goods: </span>'
            f'<span>{escape(str(d["goods_summary"]))}</span>{origin_span}</div>'
        )

    line_rows = ""
    if not lines:
        line_rows = (
            '<div style="padding:12px 10px;font-size:10px;color:#94A3B8;border-top:1px solid #E2E8F0;">'
            "No goods lines</div>"
        )
    else:
        for i, l in enumerate(lines, 1):
            nw = l.get("net_weight")
            nw_s = f"{float(nw):.3f} g" if nw is not None else "—"
            line_rows += (
                '<div style="display:grid;grid-template-columns:40px 1fr 110px 80px 60px;'
                'border-top:1px solid #E2E8F0;font-size:10px;">'
                f'<div style="padding:8px;border-right:1px solid #E2E8F0;">{i}</div>'
                f'<div style="padding:8px;border-right:1px solid #E2E8F0;font-weight:600;">'
                f'{escape(str(l.get("item_type") or "—"))}</div>'
                f'<div style="padding:8px;border-right:1px solid #E2E8F0;font-size:9px;color:#475569;">'
                "Polybag + Jewellery box</div>"
                f'<div style="padding:8px;border-right:1px solid #E2E8F0;text-align:right;">'
                f"{escape(nw_s)}</div>"
                f'<div style="padding:8px;text-align:right;">{int(float(l.get("qty") or 0))}</div>'
                "</div>"
            )

    if tot_nw > 0:
        tot_wt = f"{(tot_nw / 1000):.3f} kg"
    elif total_kg > 0:
        tot_wt = f"{total_kg:.3f} kg"
    else:
        tot_wt = "—"

    no_carrier = ""
    if not carrier:
        no_carrier = (
            '<div style="padding:12px 14px;background:#FBF8F1;border:1px dashed #CBD5E1;'
            'border-radius:4px;color:#94A3B8;font-size:10px;margin-bottom:14px;text-align:center;">'
            "Carrier AWB not yet assigned — CMR carrier fields will populate when shipment is dispatched."
            "</div>"
        )

    carrier_body = ""
    if carrier:
        carrier_body = (
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
            f'{_carrier_chip(carrier.get("name"))}'
            + (
                f'<span style="font-weight:600;">{escape(str(carrier["service"]))}</span>'
                if carrier.get("service")
                else ""
            )
            + "</div>"
            + (
                f'<div style="font-family:ui-monospace,monospace;font-size:10px;">'
                f'AWB {escape(str(carrier["awb"]))}</div>'
                if carrier.get("awb")
                else ""
            )
        )
    else:
        carrier_body = '<div style="color:#94A3B8;font-size:9px;">Awaiting dispatch</div>'

    incoterm_body = "—"
    if carrier:
        incoterm_body = (
            f'<span style="display:inline-block;background:#E8F5E9;color:#0B3D2E;'
            f'padding:2px 8px;border-radius:999px;font-size:9px;font-weight:600;">'
            f'{escape(str(carrier.get("incoterm") or "—"))}</span>'
        )
        if carrier.get("insurance"):
            incoterm_body += (
                f'<div style="margin-top:4px;color:#64748B;font-size:9px;">'
                f'Insurance {escape(str(carrier["insurance"]))} · door-to-door</div>'
            )

    doc_ref = d.get("doc_ref") or ""
    footer_extra = (
        f" Goods remain property of Estrella Jewels until full payment is received per Proforma {escape(str(doc_ref))}."
        if doc_ref
        else ""
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>CMR {escape(str(d.get("cmr_no") or ""))}</title>
<style>
  @page {{ size: A4 portrait; margin: 10mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #0F172A; background: #fff; }}
  .ej-a4 {{ width: 190mm; margin: 0 auto; }}
  .ej-band {{ height: 6px; background: linear-gradient(90deg,#0B3D2E 0%,#0B3D2E 70%,#C9A84C 70%,#C9A84C 100%); }}
  .ej-pad {{ padding: 18px 16px 24px; }}
  .ej-eyebrow {{ font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase; color: #64748B; font-weight: 600; }}
  .ej-eyebrow-gold {{ color: #C9A84C; }}
  .ej-h1 {{ font-size: 22px; font-weight: 700; color: #0B3D2E; margin: 0; }}
  .ej-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
</style></head>
<body>
<div class="ej-a4">
  <div class="ej-band"></div>
  <div class="ej-pad" style="padding-top:24px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px;">
      {logo_html}
      <div style="text-align:right;">
        <div class="ej-eyebrow ej-eyebrow-gold">International consignment note</div>
        <div class="ej-h1" style="margin-top:2px;">CMR · Delivery Note</div>
        <div class="ej-mono" style="font-size:13px;color:#0B3D2E;font-weight:600;margin-top:4px;">
          {escape(str(d.get("cmr_no") or "—"))}
        </div>
      </div>
    </div>
    {no_carrier}
    <div style="border:1.5px solid #0B3D2E;border-radius:4px;overflow:hidden;margin-bottom:14px;">
      <div style="display:grid;grid-template-columns:1fr 1fr;">
        {_box("1", "Sender · Nadawca", seller_body)}
        {_box("2", "Consignee · Odbiorca", shipto_body, border_left=True)}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;border-top:1px solid #CBD5E1;">
        {_box("3", "Place of delivery", escape(place_delivery))}
        {_box("4", "Place / date of taking over", escape(taking_over), border_left=True)}
        {_box("5", "Documents attached", escape(docs_attached), border_left=True)}
      </div>
      {goods_block}
      <div style="display:grid;grid-template-columns:40px 1fr 110px 80px 60px;border-top:1.5px solid #0B3D2E;background:#F8FAFC;">
        {"".join(
            f'<div style="padding:6px 8px;border-right:{"1px solid #CBD5E1" if i < 4 else "none"};'
            f'font-size:8.5px;color:#64748B;font-weight:600;">'
            f'<span style="background:#0B3D2E;color:#fff;padding:1px 4px;border-radius:2px;'
            f'margin-right:4px;font-size:7px;">{n}</span>{lbl}</div>'
            for i, (n, lbl) in enumerate(
                [("6", "No."), ("7", "Item Category"), ("8", "Packaging"), ("9", "Net Weight"), ("10", "Qty")]
            )
        )}
      </div>
      {line_rows}
      <div style="display:grid;grid-template-columns:40px 1fr 110px 80px 60px;border-top:1.5px solid #0B3D2E;background:#FBF8F1;font-size:10px;font-weight:600;">
        <div style="padding:8px;border-right:1px solid #CBD5E1;">—</div>
        <div style="padding:8px;border-right:1px solid #CBD5E1;">{len(lines)} item type(s)</div>
        <div style="padding:8px;border-right:1px solid #CBD5E1;">1 outer carton</div>
        <div style="padding:8px;text-align:right;border-right:1px solid #CBD5E1;">{escape(tot_wt)}</div>
        <div style="padding:8px;text-align:right;">{int(tot_qty) if tot_qty else "—"}</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;border:1px solid #CBD5E1;border-radius:4px;margin-bottom:14px;">
      {_box("16", "Carrier · Przewoźnik", carrier_body)}
      {_box("17", "Successive carriers", "—", border_left=True)}
      {_box("20", "Special agreements · Incoterm", incoterm_body, border_left=True)}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;border:1px solid #CBD5E1;border-radius:4px;">
      {_sig_box("22", "Sender's signature & stamp", "Estrella Jewels")}
      {_sig_box("23", "Carrier's signature & stamp", (carrier or {}).get("name") or "—", border_left=True)}
      {_sig_box("24", "Goods received · signature & stamp", shipto.get("name") or "—", border_left=True)}
    </div>
    <div style="margin-top:14px;font-size:9px;color:#64748B;line-height:1.5;">
      This consignment note is governed by the Convention on the Contract for the International
      Carriage of Goods by Road (CMR, Geneva 1956). The sender acknowledges the goods have been
      packaged and labelled in accordance with carrier requirements.{footer_extra}
    </div>
  </div>
</div>
</body></html>
"""
