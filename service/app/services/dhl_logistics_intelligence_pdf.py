"""
dhl_logistics_intelligence_pdf.py — Estrella-branded Logistics Intelligence PDF.

Pure renderer: takes the intelligence + KPI dict already produced by the
projector. No I/O, no DB, no workflow writes. Brand tokens match
statement_pdf_renderer (Document Suite emerald / gold / cream).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_EJ_BRAND = colors.HexColor("#0B3D2E")
_EJ_GOLD = colors.HexColor("#C9A24B")
_EJ_CREAM = colors.HexColor("#FBF8F1")
_EJ_INK = colors.HexColor("#0F172A")
_EJ_INK_2 = colors.HexColor("#475569")
_EJ_LINE = colors.HexColor("#E2E8F0")
_EJ_RED = colors.HexColor("#B91C1C")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "LITitle", parent=base["Heading1"], fontSize=16, textColor=_EJ_BRAND,
            spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "h2": ParagraphStyle(
            "LIH2", parent=base["Heading2"], fontSize=11, textColor=_EJ_BRAND,
            spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "LIBody", parent=base["Normal"], fontSize=8, textColor=_EJ_INK,
            leading=11,
        ),
        "muted": ParagraphStyle(
            "LIMuted", parent=base["Normal"], fontSize=7, textColor=_EJ_INK_2,
            leading=9,
        ),
        "cell": ParagraphStyle(
            "LICell", parent=base["Normal"], fontSize=7, textColor=_EJ_INK,
            leading=9,
        ),
    }


def _fmt(v: Any) -> str:
    if v is None or v == "":
        return "—"
    return str(v)


def _table(data: List[List[Any]], col_widths: Optional[List[float]] = None) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _EJ_BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("TEXTCOLOR", (0, 1), (-1, -1), _EJ_INK),
        ("BACKGROUND", (0, 1), (-1, -1), _EJ_CREAM),
        ("GRID", (0, 0), (-1, -1), 0.3, _EJ_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def render_logistics_intelligence_pdf(payload: Dict[str, Any]) -> bytes:
    """Render Control Tower intelligence PDF. Totals must match screen payload."""
    styles = _styles()
    intel = payload.get("intelligence") or {}
    kpis = payload.get("kpis") or {}
    summary = intel.get("executive_summary") or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Estrella Logistics Intelligence",
    )
    story: List[Any] = []

    story.append(Paragraph("ESTRELLA JEWELS", styles["muted"]))
    story.append(Paragraph("Logistics Intelligence — Control Tower", styles["title"]))
    story.append(Paragraph(
        f"Generated { _fmt(payload.get('generated_at_warsaw') or payload.get('generated_at_utc')) } · Europe/Warsaw · "
        f"read-only projection over corrected shipment facts",
        styles["muted"],
    ))
    story.append(Spacer(1, 6))

    # Executive summary
    story.append(Paragraph("Executive summary", styles["h2"]))
    exec_rows = [[
        Paragraph("Operational active", styles["cell"]),
        Paragraph(_fmt(summary.get("operational_active", kpis.get("operational_active"))), styles["cell"]),
        Paragraph("Needs attention", styles["cell"]),
        Paragraph(_fmt(kpis.get("needs_attention")), styles["cell"]),
    ], [
        Paragraph("Intervention queue", styles["cell"]),
        Paragraph(_fmt(summary.get("intervention_queue")), styles["cell"]),
        Paragraph("Critical / Action", styles["cell"]),
        Paragraph(
            f"{_fmt(summary.get('critical'))} / {_fmt(summary.get('action_required'))}",
            styles["cell"],
        ),
    ], [
        Paragraph("Top bottleneck", styles["cell"]),
        Paragraph(_fmt(summary.get("top_bottleneck")), styles["cell"]),
        Paragraph("Excess vs target", styles["cell"]),
        Paragraph(_fmt(summary.get("top_bottleneck_excess_hours")) + "h", styles["cell"]),
    ]]
    story.append(_table(
        [[Paragraph("Metric", styles["cell"]), Paragraph("Value", styles["cell"]),
          Paragraph("Metric", styles["cell"]), Paragraph("Value", styles["cell"])]] + exec_rows,
        col_widths=[40 * mm, 45 * mm, 40 * mm, 45 * mm],
    ))

    # Intervention queue
    story.append(Paragraph("Intervention queue (advice only)", styles["h2"]))
    queue = intel.get("intervention_queue") or []
    q_data = [[
        Paragraph("AWB", styles["cell"]),
        Paragraph("Party", styles["cell"]),
        Paragraph("Issue", styles["cell"]),
        Paragraph("Age", styles["cell"]),
        Paragraph("Suggested action", styles["cell"]),
        Paragraph("Owner", styles["cell"]),
    ]]
    for item in queue[:25]:
        q_data.append([
            Paragraph(_fmt(item.get("awb")), styles["cell"]),
            Paragraph(_fmt(item.get("party"))[:40], styles["cell"]),
            Paragraph(_fmt(item.get("issue"))[:50], styles["cell"]),
            Paragraph(_fmt(item.get("age_human")), styles["cell"]),
            Paragraph(_fmt(item.get("suggested_action"))[:70], styles["cell"]),
            Paragraph(_fmt(item.get("owner")), styles["cell"]),
        ])
    if len(q_data) == 1:
        q_data.append([Paragraph("None", styles["cell"]), "", "", "", "", ""])
    story.append(_table(q_data, col_widths=[28 * mm, 30 * mm, 35 * mm, 18 * mm, 50 * mm, 18 * mm]))

    # Transit performance
    story.append(Paragraph("Transit performance (typical = median)", styles["h2"]))
    tp = intel.get("transit_performance") or {}
    t_data = [[
        Paragraph("Scope", styles["cell"]),
        Paragraph("Transition", styles["cell"]),
        Paragraph("Typical", styles["cell"]),
        Paragraph("P90", styles["cell"]),
        Paragraph("Target", styles["cell"]),
        Paragraph("Δ 30d", styles["cell"]),
        Paragraph("N", styles["cell"]),
    ]]
    for scope in ("inbound", "outbound"):
        for dto in (tp.get(scope) or {}).values():
            if not dto.get("n"):
                continue
            delta = dto.get("delta_pct_vs_previous_30d")
            t_data.append([
                Paragraph(scope, styles["cell"]),
                Paragraph(_fmt(dto.get("label")), styles["cell"]),
                Paragraph(_fmt(dto.get("typical_human")), styles["cell"]),
                Paragraph(_fmt(dto.get("p90_human")), styles["cell"]),
                Paragraph(_fmt(dto.get("target_human")), styles["cell"]),
                Paragraph(("+" if delta and delta > 0 else "") + _fmt(delta) + ("%" if delta is not None else ""), styles["cell"]),
                Paragraph(_fmt(dto.get("n")), styles["cell"]),
            ])
    story.append(_table(t_data, col_widths=[22 * mm, 50 * mm, 22 * mm, 22 * mm, 22 * mm, 20 * mm, 14 * mm]))

    # Bottlenecks
    story.append(Paragraph("Top bottlenecks (excess vs configured target)", styles["h2"]))
    b_data = [[
        Paragraph("Transition", styles["cell"]),
        Paragraph("Excess", styles["cell"]),
        Paragraph("N", styles["cell"]),
        Paragraph("Contribution", styles["cell"]),
        Paragraph("Δ vs prev 30d", styles["cell"]),
    ]]
    for b in (intel.get("bottlenecks") or [])[:10]:
        b_data.append([
            Paragraph(_fmt(b.get("label")), styles["cell"]),
            Paragraph(_fmt(b.get("excess_vs_target_hours")) + "h", styles["cell"]),
            Paragraph(_fmt(b.get("n")), styles["cell"]),
            Paragraph(_fmt(b.get("contribution_hours")) + "h", styles["cell"]),
            Paragraph(_fmt(b.get("delta_pct_vs_previous_30d")), styles["cell"]),
        ])
    if len(b_data) == 1:
        b_data.append([Paragraph("No excess vs target", styles["cell"]), "", "", "", ""])
    story.append(_table(b_data, col_widths=[70 * mm, 25 * mm, 20 * mm, 30 * mm, 30 * mm]))

    # Lanes
    story.append(Paragraph("Lane performance", styles["h2"]))
    l_data = [[
        Paragraph("Lane", styles["cell"]),
        Paragraph("N", styles["cell"]),
        Paragraph("Median", styles["cell"]),
        Paragraph("P90", styles["cell"]),
        Paragraph("Target hit %", styles["cell"]),
        Paragraph("Exception %", styles["cell"]),
        Paragraph("Trend Δ", styles["cell"]),
    ]]
    for lane in (intel.get("lane_performance") or [])[:15]:
        l_data.append([
            Paragraph(_fmt(lane.get("lane_id")), styles["cell"]),
            Paragraph(_fmt(lane.get("n")), styles["cell"]),
            Paragraph(_fmt(lane.get("median_human")), styles["cell"]),
            Paragraph(_fmt(lane.get("p90_human")), styles["cell"]),
            Paragraph(_fmt(lane.get("target_hit_pct")), styles["cell"]),
            Paragraph(_fmt(lane.get("exception_rate_pct")), styles["cell"]),
            Paragraph(_fmt(lane.get("trend_delta_pct")), styles["cell"]),
        ])
    if len(l_data) == 1:
        l_data.append([Paragraph("No delivered lane samples", styles["cell"]), "", "", "", "", "", ""])
    story.append(_table(l_data, col_widths=[28 * mm, 14 * mm, 24 * mm, 24 * mm, 28 * mm, 28 * mm, 24 * mm]))

    # Slowest current
    story.append(Paragraph("Slowest current shipments", styles["h2"]))
    s_data = [[
        Paragraph("AWB", styles["cell"]),
        Paragraph("Party", styles["cell"]),
        Paragraph("Stage", styles["cell"]),
        Paragraph("Time in stage", styles["cell"]),
        Paragraph("Risk", styles["cell"]),
    ]]
    for s in (intel.get("slowest_current_shipments") or [])[:12]:
        s_data.append([
            Paragraph(_fmt(s.get("awb")), styles["cell"]),
            Paragraph(_fmt(s.get("party"))[:36], styles["cell"]),
            Paragraph(_fmt(s.get("current_stage"))[:36], styles["cell"]),
            Paragraph(_fmt(s.get("time_in_stage_human")), styles["cell"]),
            Paragraph(_fmt(s.get("risk")), styles["cell"]),
        ])
    story.append(_table(s_data, col_widths=[32 * mm, 45 * mm, 50 * mm, 28 * mm, 25 * mm]))

    # Data quality
    dq = intel.get("data_quality_notes") or {}
    story.append(Paragraph("Data-quality notes (visible, not hidden)", styles["h2"]))
    story.append(Paragraph(
        "Tracking missing: {tm} · Invalid order: {io} · Delivered w/o ts: {dw} · Missing party: {mp}".format(
            tm=_fmt(dq.get("tracking_evidence_missing")),
            io=_fmt(dq.get("invalid_timestamp_order")),
            dw=_fmt(dq.get("delivered_without_timestamp")),
            mp=_fmt(dq.get("missing_party_identity")),
        ),
        styles["body"],
    ))

    # Cost
    cost = intel.get("cost_intelligence") or {}
    story.append(Paragraph("Cost Intelligence", styles["h2"]))
    if cost.get("quoted_cost_available"):
        story.append(Paragraph(
            "Quoted Cost totals by currency (no cross-currency merge): "
            + ", ".join(f"{k} {v}" for k, v in (cost.get("totals_by_currency") or {}).items()),
            styles["body"],
        ))
    else:
        story.append(Paragraph(_fmt(cost.get("quoted_cost_gap")), styles["body"]))
    story.append(Paragraph(
        "Actual DHL Cost: UNAVAILABLE — " + _fmt(cost.get("actual_cost_gap")),
        styles["muted"],
    ))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Targets are explicit management constants — not inferred from historical P90. "
        "Suggested actions are advice only and never execute customs or financial writes. "
        f"PDF totals = projection payload · {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}",
        styles["muted"],
    ))

    doc.build(story)
    return buf.getvalue()
