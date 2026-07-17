"""
doc_package.py — Path-DOC: outbound customs/shipping document package generator.

Generates a PDF package for outbound physical dispatch:
  1. Commercial invoice — fetched from wFirma (READ-ONLY).
  2. Packing list PDF  — generated locally from packing_lines / editable_lines_json.
  3. CN23 customs declaration PDF — generated locally; included ONLY for non-EU
     destinations (customer_master.country ∉ EU-27).

No carrier API, no credentials, no carrier_api_status gating.
No wFirma writes.

Key types
---------
LabelPackageInputs  — body supplied by the operator at generation time.
LabelPackageResult  — returned on success.
LabelPackageGaps    — returned when mandatory inputs are missing (422 caller).

EU set: EU_COUNTRIES from models/vat_resolver.py (EU-27 + PL included).
"""
from __future__ import annotations

import io
import json
import logging
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── EU-27 set (re-exported from vat_resolver to stay DRY) ────────────────────
from ...models.vat_resolver import EU_COUNTRIES  # noqa: E402  (after dataclasses)

# ── Advisory channel ──────────────────────────────────────────────────────────
_ADVISORY_CHANNEL = "doc_package_advisory"


# ── Input / output types ──────────────────────────────────────────────────────

def package_weight_kg(goods_weight_g: float, tare_weight_kg: float) -> float:
    """Total package weight in kg from the two weight authorities.

    UNIT AUTHORITY: packing_lines.net_weight / gross_weight are stored in
    GRAMS (supplier sheet columns "GR.WT/NT.WT (GMS)"); box tare comes from
    box_types.tare_weight_kg in KG. Grams are converted BEFORE adding:
        package_weight_kg = goods_weight_g / 1000 + tare_weight_kg
    Stored data is never rewritten — conversion happens only at composition.
    """
    return float(goods_weight_g or 0) / 1000.0 + float(tare_weight_kg or 0)


@dataclass
class LabelPackageInputs:
    """Operator-supplied inputs required to generate the package.

    Dimensions and tare are resolved from the box_types master by the route
    before calling assemble_label_package(); the module receives concrete values.
    """
    # Mandatory always — resolved from box_types master by the route
    length_cm:     float
    width_cm:      float
    height_cm:     float
    tare_weight_kg: float = 0.0   # from box.tare_weight_kg
    # Required for non-EU only
    incoterm:      Optional[str] = None
    receiver_eori: Optional[str] = None
    # Optional — used to locate the proforma/draft
    client_name:   Optional[str] = None


@dataclass
class LabelPackageResult:
    """Returned on successful generation."""
    content:      bytes
    filename:     str
    content_type: str                           # "application/pdf" or "application/zip"
    components:   List[str] = field(default_factory=list)   # ["invoice", "packing_list", "cn23"]
    advisories:   List[str] = field(default_factory=list)   # soft warnings surfaced to operator


@dataclass
class LabelPackageGaps:
    """Returned when mandatory inputs are missing — caller raises 422."""
    gaps: List[Dict[str, str]]   # [{"field": "...", "reason": "..."}]


# ── Advisory helper (local; does not depend on campaign branch) ───────────────

def _write_soft_advisory(audit_path: Path, code: str, message: str) -> None:
    """Append a soft advisory action_proposal to audit.json. Best-effort."""
    if not audit_path.exists():
        return
    try:
        audit: Dict[str, Any] = json.loads(audit_path.read_text(encoding="utf-8"))
        proposals: List[Dict[str, Any]] = audit.setdefault("action_proposals", [])
        # Dedup by (channel + type)
        for p in proposals:
            if p.get("channel") == _ADVISORY_CHANNEL and p.get("type") == code:
                if p.get("status") == "pending_review":
                    return
        proposals.append({
            "proposal_id":  str(uuid.uuid4()),
            "type":         code,
            "channel":      _ADVISORY_CHANNEL,
            "status":       "pending_review",
            "reason":       message,
            "confidence":   "high",
            "advisory":     True,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "approved_by":  None,
            "approved_at":  None,
            "rejected_by":  None,
            "rejected_at":  None,
            "reject_reason": None,
            "draft":        {},
            "email_id":     None,
            "queued_at":    None,
        })
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.debug("_write_soft_advisory failed (non-fatal): %s", exc)


# ── Font registration (mirrors statement_pdf_renderer pattern) ────────────────

def _register_fonts() -> tuple:
    """Return (font_regular, font_bold). Lazy — only called when building PDF."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os, reportlab as _rl

        reg_name, bold_name = "EJDoc", "EJDoc-Bold"
        if reg_name in pdfmetrics.getRegisteredFontNames():
            return reg_name, bold_name

        _rl_font_dir = os.path.join(os.path.dirname(_rl.__file__), "fonts")
        candidates = [
            # Windows
            (r"C:\Windows\Fonts\arial.ttf",       r"C:\Windows\Fonts\arialbd.ttf"),
            (r"C:\Windows\Fonts\DejaVuSans.ttf",  r"C:\Windows\Fonts\DejaVuSans-Bold.ttf"),
            # macOS
            ("/Library/Fonts/Arial Unicode.ttf",   "/Library/Fonts/Arial Unicode.ttf"),
            # Linux
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            # ReportLab bundled
            (os.path.join(_rl_font_dir, "Vera.ttf"),
             os.path.join(_rl_font_dir, "VeraBd.ttf")),
        ]
        for reg, bold in candidates:
            if os.path.exists(reg) and os.path.exists(bold):
                try:
                    pdfmetrics.registerFont(TTFont(reg_name, reg))
                    pdfmetrics.registerFont(TTFont(bold_name, bold))
                    return reg_name, bold_name
                except Exception:
                    continue
        return "Helvetica", "Helvetica-Bold"
    except ImportError:
        return "Helvetica", "Helvetica-Bold"


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_audit(batch_id: str, storage_root: Path) -> Dict[str, Any]:
    audit_path = storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        return {}
    try:
        return json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_packing_lines(batch_id: str, storage_root: Path) -> List[Dict[str, Any]]:
    """Load packing_lines for the batch from packing.db."""
    packing_db = storage_root / "packing.db"
    if not packing_db.exists():
        return []
    try:
        conn = sqlite3.connect(str(packing_db))
        conn.row_factory = sqlite3.Row
        # diamond_weight / color_weight (carats) added 2026-06-09; select them so
        # the backend Packing List PDF can emit the stone-weight columns (they
        # were previously loaded only by the V2 renderer, never the PDF).
        # Fall back gracefully for legacy packing.db files that predate those
        # columns — a missing column must never blank the whole packing list.
        try:
            rows = conn.execute(
                "SELECT product_code, design_no, item_type, quantity, "
                "gross_weight, net_weight, diamond_weight, color_weight, "
                "metal, karat FROM packing_lines "
                "WHERE batch_id=?",
                (batch_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT product_code, design_no, item_type, quantity, "
                "gross_weight, net_weight, metal, karat FROM packing_lines "
                "WHERE batch_id=?",
                (batch_id,),
            ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d.setdefault("diamond_weight", None)
            d.setdefault("color_weight", None)
            result.append(d)
        return result
    except Exception as exc:
        log.debug("[%s] _load_packing_lines failed: %s", batch_id, exc)
        return []


def _load_proforma_draft(batch_id: str, client_name: Optional[str],
                          storage_root: Path) -> Optional[Any]:
    """Return the best proforma_draft for (batch, client), or None."""
    proforma_db = storage_root / "proforma_links.db"
    if not proforma_db.exists():
        return None
    try:
        from ..proforma_invoice_link_db import (
            get_draft, list_drafts_for_batch,
        )
    except ImportError:
        return None
    try:
        if client_name:
            return get_draft(proforma_db, batch_id, client_name)
        # No client_name: take the first posted draft
        drafts = list_drafts_for_batch(proforma_db, batch_id)
        for d in sorted(drafts, key=lambda x: x.updated_at or "", reverse=True):
            if d.wfirma_proforma_id:
                return d
        return drafts[0] if drafts else None
    except Exception as exc:
        log.debug("[%s] _load_proforma_draft failed: %s", batch_id, exc)
        return None


class _CustomerView:
    """Lightweight view of customer_master fields needed by doc_package.
    Uses direct SQL so it works with both full and test-minimal schemas.
    Includes both bill_to_* and ship_to_* fields for the receiver-address logic.
    """
    __slots__ = (
        "bill_to_name", "country", "bill_to_street", "bill_to_city",
        "bill_to_postal_code", "bill_to_email", "bill_to_phone", "eori",
        # ship_to_* (primary receiver address when ship_to_use_alternate=1)
        "ship_to_name", "ship_to_person", "ship_to_street", "ship_to_city",
        "ship_to_zip", "ship_to_country", "ship_to_phone", "ship_to_email",
        "ship_to_use_alternate", "ship_to_contractor_id",
    )

    def __init__(self, row: sqlite3.Row) -> None:
        keys = row.keys() if hasattr(row, "keys") else []
        def _g(k: str) -> Optional[str]:
            return str(row[k]).strip() if k in keys and row[k] else None
        def _b(k: str) -> bool:
            return bool(int(row[k])) if k in keys and row[k] else False
        self.bill_to_name       = _g("bill_to_name")
        self.country            = _g("country") or ""
        self.bill_to_street     = _g("bill_to_street")
        self.bill_to_city       = _g("bill_to_city")
        self.bill_to_postal_code= _g("bill_to_postal_code")
        self.bill_to_email      = _g("bill_to_email")
        self.bill_to_phone      = _g("bill_to_phone")
        self.eori               = _g("eori")
        # ship_to fields (alternate delivery address)
        self.ship_to_name           = _g("ship_to_name")
        self.ship_to_person         = _g("ship_to_person")
        self.ship_to_street         = _g("ship_to_street")
        self.ship_to_city           = _g("ship_to_city")
        self.ship_to_zip            = _g("ship_to_zip")
        self.ship_to_country        = _g("ship_to_country")
        self.ship_to_phone          = _g("ship_to_phone")
        self.ship_to_email          = _g("ship_to_email")
        self.ship_to_use_alternate  = _b("ship_to_use_alternate")
        self.ship_to_contractor_id  = _g("ship_to_contractor_id")


def _load_customer(contractor_id: str, storage_root: Path) -> Optional[_CustomerView]:
    """Read customer_master via direct SQL — resilient to schema variations."""
    cm_db = storage_root / "customer_master.sqlite"
    if not cm_db.exists():
        return None
    try:
        conn = sqlite3.connect(str(cm_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customer_master WHERE bill_to_contractor_id=? LIMIT 1",
            (contractor_id,),
        ).fetchone()
        conn.close()
        return _CustomerView(row) if row else None
    except Exception as exc:
        log.debug("_load_customer failed for %r: %s", contractor_id, exc)
        return None


def _resolve_customer_from_batch(batch_id: str, client_name: Optional[str],
                                   storage_root: Path) -> Optional[Any]:
    """
    Attempt to resolve a CustomerMaster row from batch context.
    Priority: client_name → contractor_id from shipment_documents → None.
    """
    if client_name:
        # Try via name match in wfirma_customers → customer_master
        try:
            wfirma_db = storage_root / "wfirma.db"
            if wfirma_db.exists():
                wconn = sqlite3.connect(str(wfirma_db))
                wconn.row_factory = sqlite3.Row
                row = wconn.execute(
                    "SELECT wfirma_customer_id FROM wfirma_customers "
                    "WHERE client_name=? LIMIT 1",
                    (client_name,),
                ).fetchone()
                wconn.close()
                if row and row["wfirma_customer_id"]:
                    return _load_customer(row["wfirma_customer_id"], storage_root)
        except Exception:
            pass
    # Fallback: supplier_contractor_id from shipment_documents (client side)
    docs_db = storage_root / "documents.db"
    if docs_db.exists():
        try:
            dconn = sqlite3.connect(str(docs_db))
            dconn.row_factory = sqlite3.Row
            row = dconn.execute(
                "SELECT client_contractor_id FROM shipment_documents "
                "WHERE batch_id=? AND client_contractor_id != '' LIMIT 1",
                (batch_id,),
            ).fetchone()
            dconn.close()
            if row and row["client_contractor_id"]:
                return _load_customer(row["client_contractor_id"], storage_root)
        except Exception:
            pass
    return None


def _load_company_profile(storage_root: Path) -> Optional[Any]:
    md_db = storage_root / "master_data.sqlite"
    if not md_db.exists():
        return None
    try:
        from ..master_data_db import get_company_profile
        return get_company_profile(md_db)
    except Exception:
        return None


def _load_invoice_lines(batch_id: str, storage_root: Path) -> List[Dict[str, Any]]:
    docs_db = storage_root / "documents.db"
    if not docs_db.exists():
        return []
    try:
        conn = sqlite3.connect(str(docs_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT product_code, description, quantity, hs_code, hsn_code, "
            "gross_weight, unit_price, total_value, currency "
            "FROM invoice_lines WHERE batch_id=? AND active=1",
            (batch_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_product_description(product_code: str, storage_root: Path) -> Optional[str]:
    """Return description_en for a product_code, or None."""
    docs_db = storage_root / "documents.db"
    if not docs_db.exists():
        return None
    try:
        conn = sqlite3.connect(str(docs_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT description_en, name_pl FROM product_descriptions "
            "WHERE product_code=?",
            (product_code,),
        ).fetchone()
        conn.close()
        if row:
            return (row["description_en"] or row["name_pl"] or "").strip() or None
        return None
    except Exception:
        return None


def _load_hs_override(product_code: str, storage_root: Path) -> Optional[str]:
    md_db = storage_root / "master_data.sqlite"
    if not md_db.exists():
        return None
    try:
        conn = sqlite3.connect(str(md_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT hs_code_override, origin_country FROM product_local "
            "WHERE product_code=?",
            (product_code,),
        ).fetchone()
        conn.close()
        if row:
            return row["hs_code_override"] or None
        return None
    except Exception:
        return None


# ── PDF generators ────────────────────────────────────────────────────────────

def render_packing_list_pdf(
    batch_id: str,
    storage_root: Path,
    company: Any,        # CompanyProfile or None
    customer: Any,       # CustomerMaster or None
    draft: Any,          # ProformaDraft or None
    delivery_addr: Optional[Dict[str, str]] = None,
) -> bytes:
    """
    Generate an A4 packing list PDF.

    Data sources (in priority order):
      1. packing_lines (packing.db) — per-piece rows
      2. proforma_draft.editable_lines_json — fallback if packing_lines empty
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(f"ReportLab unavailable: {exc}") from exc

    font, font_bold = _register_fonts()
    styles = getSampleStyleSheet()
    H1  = ParagraphStyle("H1",  parent=styles["Normal"], fontName=font_bold,
                          fontSize=14, leading=18)
    H2  = ParagraphStyle("H2",  parent=styles["Normal"], fontName=font_bold,
                          fontSize=10, leading=13)
    TXT = ParagraphStyle("TXT", parent=styles["Normal"], fontName=font,
                          fontSize=9,  leading=12)
    SML = ParagraphStyle("SML", parent=styles["Normal"], fontName=font,
                          fontSize=8,  leading=11, textColor=colors.HexColor("#555555"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=20*mm, rightMargin=20*mm,
                             topMargin=20*mm, bottomMargin=20*mm)
    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("PACKING LIST", H1))
    story.append(Spacer(1, 4*mm))

    prof_ref = ""
    if draft and draft.wfirma_proforma_fullnumber:
        prof_ref = draft.wfirma_proforma_fullnumber
    elif draft and draft.wfirma_proforma_id:
        prof_ref = draft.wfirma_proforma_id

    meta_rows = []
    if company:
        meta_rows.append(["Shipper:", company.legal_name or ""])
    # Consignee name: resolved via Customer Master resolve_delivery_address()
    client_name_str = ""
    if delivery_addr:
        client_name_str = delivery_addr.get("name", "")
    elif customer:
        client_name_str = getattr(customer, "bill_to_name", "") or ""
    if client_name_str:
        meta_rows.append(["Consignee:", client_name_str])
    if prof_ref:
        meta_rows.append(["Reference (PROF):", prof_ref])
    meta_rows.append(["Batch:", batch_id])
    meta_rows.append(["Date:", datetime.utcnow().strftime("%Y-%m-%d")])

    if meta_rows:
        mt = Table(meta_rows, colWidths=[45*mm, None])
        mt.setStyle(TableStyle([
            ("FONTNAME",  (0, 0), (0, -1), font_bold),
            ("FONTNAME",  (1, 0), (1, -1), font),
            ("FONTSIZE",  (0, 0), (-1, -1), 9),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(mt)

    story.append(Spacer(1, 6*mm))

    # ── Lines ─────────────────────────────────────────────────────────────────
    packing_lines = _load_packing_lines(batch_id, storage_root)
    lines_source = "packing_lines"

    if not packing_lines and draft and draft.editable_lines_json:
        try:
            raw = json.loads(draft.editable_lines_json or "[]") or []
            packing_lines = [
                {
                    "product_code": ln.get("product_code", ""),
                    "design_no":    ln.get("design_no", ""),
                    "item_type":    ln.get("design_no", ln.get("product_code", "")),
                    "quantity":     ln.get("qty", 0),
                    "gross_weight": 0.0,
                    "net_weight":   0.0,
                }
                for ln in raw
            ]
            lines_source = "proforma_draft"
        except Exception:
            pass

    # Weights: gross/net in GRAMS (packing sheet), diamond/color in CARATS.
    # Net and stone-weight columns were previously omitted from this PDF even
    # though the data exists (2026-07-16 repair); a missing value renders "—",
    # never fabricated.
    headers = ["#", "Product Code / Design", "Type", "Qty",
               "Gross Wt (g)", "Net Wt (g)", "Dia Wt (ct)", "Col Wt (ct)"]
    data = [headers]
    total_qty = 0
    total_gw = 0.0
    total_nw = 0.0
    for i, ln in enumerate(packing_lines, 1):
        pc    = (ln.get("product_code") or ln.get("design_no") or "")[:30]
        itype = (ln.get("item_type") or "")[:20]
        qty   = int(ln.get("quantity") or 0)
        gw    = float(ln.get("gross_weight") or 0)
        nw    = float(ln.get("net_weight") or 0)
        dia   = float(ln.get("diamond_weight") or 0)
        col   = float(ln.get("color_weight") or 0)
        total_qty += qty
        total_gw  += gw
        total_nw  += nw
        data.append([str(i), pc, itype, str(qty),
                     f"{gw:.1f}" if gw else "—",
                     f"{nw:.1f}" if nw else "—",
                     f"{dia:.2f}" if dia else "—",
                     f"{col:.2f}" if col else "—"])

    if len(data) > 1:
        data.append(["", "TOTAL", "", str(total_qty),
                     f"{total_gw:.1f}" if total_gw else "—",
                     f"{total_nw:.1f}" if total_nw else "—",
                     "", ""])

    col_ws = [8*mm, 55*mm, 24*mm, 12*mm, 20*mm, 20*mm, 18*mm, 18*mm]
    tbl = Table(data, colWidths=col_ws, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, 0),  font_bold),
        ("FONTNAME",      (0, 1), (-1, -1), font),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#0B3D2E")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F3EE")]),
        ("FONTNAME",      (0, -1),(-1, -1), font_bold),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
    ]))
    story.append(tbl)

    if lines_source == "proforma_draft":
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            "Note: weights sourced from proforma draft (packing data unavailable).",
            SML,
        ))

    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC | "
        "ESTRELLA JEWELS Sp. z o. o. Spółka Komandytowa", SML,
    ))

    doc.build(story)
    return buf.getvalue()


def render_cn23_pdf(
    batch_id: str,
    storage_root: Path,
    inputs: LabelPackageInputs,
    company: Any,
    customer: Any,
    draft: Any,
    delivery_addr: Optional[Dict[str, str]] = None,
) -> bytes:
    """
    Generate a CN23 customs declaration PDF for non-EU international shipments.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable,
        )
    except ImportError as exc:
        raise RuntimeError(f"ReportLab unavailable: {exc}") from exc

    font, font_bold = _register_fonts()
    styles = getSampleStyleSheet()
    H1  = ParagraphStyle("H1CN",  parent=styles["Normal"], fontName=font_bold,
                          fontSize=13, leading=16)
    H2  = ParagraphStyle("H2CN",  parent=styles["Normal"], fontName=font_bold,
                          fontSize=9,  leading=12)
    TXT = ParagraphStyle("TXTCN", parent=styles["Normal"], fontName=font,
                          fontSize=8.5, leading=11)
    SML = ParagraphStyle("SMLCN", parent=styles["Normal"], fontName=font,
                          fontSize=7.5, leading=10, textColor=colors.HexColor("#555555"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=15*mm, rightMargin=15*mm,
                             topMargin=15*mm, bottomMargin=15*mm)
    story = []

    # ── Title ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("CN23 — CUSTOMS DECLARATION / DÉCLARATION EN DOUANE", H1))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=colors.HexColor("#0B3D2E"), spaceAfter=4*mm))

    # ── Shipper / Sender ──────────────────────────────────────────────────────
    shipper_lines = []
    if company:
        shipper_lines.append(company.legal_name or "")
        if company.street:    shipper_lines.append(company.street)
        if company.postal_city: shipper_lines.append(company.postal_city)
        if company.country:   shipper_lines.append(company.country)
        if company.nip:       shipper_lines.append(f"NIP: {company.nip}")
        if company.eori:      shipper_lines.append(f"EORI: {company.eori}")

    # Receiver block: resolved via Customer Master resolve_delivery_address()
    receiver_lines = []
    if delivery_addr:
        recv_name    = delivery_addr.get("name", "")
        recv_street  = delivery_addr.get("street", "")
        recv_city    = delivery_addr.get("city", "")
        recv_zip     = delivery_addr.get("postal_code", "")
        recv_country = delivery_addr.get("country", "")
        recv_phone   = delivery_addr.get("phone", "")
        recv_email   = delivery_addr.get("email", "")
        if recv_name:    receiver_lines.append(recv_name)
        if recv_street:  receiver_lines.append(recv_street)
        if recv_city:
            receiver_lines.append(f"{recv_zip} {recv_city}".strip() if recv_zip else recv_city)
        if recv_country: receiver_lines.append(recv_country)
        if recv_email:   receiver_lines.append(recv_email)
        if recv_phone:   receiver_lines.append(recv_phone)
        if inputs.receiver_eori: receiver_lines.append(f"EORI: {inputs.receiver_eori}")

    parties = Table([
        [Paragraph("<b>Sender / Expéditeur</b>", H2),
         Paragraph("<b>Addressee / Destinataire</b>", H2)],
        [Paragraph("<br/>".join(shipper_lines), TXT),
         Paragraph("<br/>".join(receiver_lines), TXT)],
    ], colWidths=[85*mm, 85*mm])
    parties.setStyle(TableStyle([
        ("VALIGN",  (0, 0), (-1, -1), "TOP"),
        ("BOX",     (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
        ("INNERGRID",(0,0), (-1,-1),  0.3, colors.HexColor("#CCCCCC")),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
    ]))
    story.append(parties)
    story.append(Spacer(1, 5*mm))

    # ── Contents ──────────────────────────────────────────────────────────────
    story.append(Paragraph("<b>Contents / Description des articles</b>", H2))
    story.append(Spacer(1, 2*mm))

    invoice_lines = _load_invoice_lines(batch_id, storage_root)
    packing_lines = _load_packing_lines(batch_id, storage_root)

    # Build goods rows: try invoice_lines first, then packing_lines
    goods_rows = []
    if invoice_lines:
        for ln in invoice_lines:
            pc   = (ln.get("product_code") or "").strip()
            desc = (ln.get("description") or "").strip()
            if not desc and pc:
                desc = _load_product_description(pc, storage_root) or ""
            if not desc:
                desc = "Jewellery / Biżuteria"
            hs_code = (ln.get("hs_code") or ln.get("hsn_code") or "").strip()
            if not hs_code and pc:
                hs_code = _load_hs_override(pc, storage_root) or ""
            goods_rows.append({
                "description": desc[:80],
                "quantity":    int(ln.get("quantity") or 1),
                "hs_code":     hs_code or "7113",
                "value_usd":   float(ln.get("total_value") or ln.get("unit_price") or 0),
                "currency":    (ln.get("currency") or "USD").strip(),
                "weight_g":    float(ln.get("gross_weight") or 0),
                "origin":      "PL",  # Estrella ships from PL
            })
    elif packing_lines:
        for ln in packing_lines:
            pc    = (ln.get("product_code") or "").strip()
            itype = (ln.get("item_type") or "Jewellery").strip()
            desc  = _load_product_description(pc, storage_root) or f"{itype} / Biżuteria"
            hs_code = _load_hs_override(pc, storage_root) or "7113"
            goods_rows.append({
                "description": desc[:80],
                "quantity":    int(ln.get("quantity") or 1),
                "hs_code":     hs_code,
                "value_usd":   float(ln.get("unit_price_eur") or 0),
                "currency":    "EUR",
                "weight_g":    float(ln.get("gross_weight") or 0),
                "origin":      "PL",
            })

    # Fallback if completely empty
    if not goods_rows:
        goods_rows = [{
            "description": "Jewellery / Biżuteria", "quantity": 1,
            "hs_code": "7113", "value_usd": 0.0, "currency": "USD",
            "weight_g": 0.0, "origin": "PL",
        }]

    cdata = [["Description", "Qty", "HS Code", "Origin", "Value", "Wt (g)"]]
    total_val = 0.0
    ccy = ""
    for r in goods_rows:
        total_val += r["value_usd"]
        ccy = ccy or r["currency"]
        cdata.append([
            r["description"], str(r["quantity"]), r["hs_code"],
            r["origin"],
            f"{r['value_usd']:.2f} {r['currency']}" if r["value_usd"] else "—",
            f"{r['weight_g']:.1f}" if r["weight_g"] else "—",
        ])
    cdata.append(["TOTAL", str(sum(r["quantity"] for r in goods_rows)),
                  "", "",
                  f"{total_val:.2f} {ccy}" if total_val else "—",
                  f"{sum(r['weight_g'] for r in goods_rows):.1f}"])

    ct = Table(cdata, colWidths=[72*mm, 10*mm, 22*mm, 16*mm, 32*mm, 18*mm],
               repeatRows=1)
    ct.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, 0),  font_bold),
        ("FONTNAME",      (0, 1), (-1, -1), font),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#0B3D2E")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F3EE")]),
        ("FONTNAME",      (0, -1),(-1, -1), font_bold),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
    ]))
    story.append(ct)
    story.append(Spacer(1, 5*mm))

    # ── Declared value / weight / dims ────────────────────────────────────────
    audit = _load_audit(batch_id, storage_root)
    inv_totals = audit.get("invoice_totals") or {}
    cif_usd = float(inv_totals.get("total_cif_usd") or total_val or 0)
    currency_final = (inv_totals.get("currency") or ccy or "USD").strip()

    goods_weight_g_cn23 = sum(r["weight_g"] for r in goods_rows)
    declared_weight_kg = package_weight_kg(goods_weight_g_cn23, inputs.tare_weight_kg)

    prof_ref = ""
    if draft and draft.wfirma_proforma_fullnumber:
        prof_ref = draft.wfirma_proforma_fullnumber

    meta2 = [
        ["Declared value (CIF):", f"{cif_usd:.2f} {currency_final}"],
        ["Gross weight (kg):", f"{declared_weight_kg:.3f}"],
        ["Dimensions (cm):",
         f"{inputs.length_cm:.0f} × {inputs.width_cm:.0f} × {inputs.height_cm:.0f}"],
        ["Incoterm:", inputs.incoterm or "—"],
        ["Reference (PROF):", prof_ref or "—"],
        ["Type of shipment:", "Sale of goods / Sprzedaż towarów"],
    ]
    mt2 = Table(meta2, colWidths=[55*mm, None])
    mt2.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (0, -1), font_bold),
        ("FONTNAME",  (1, 0), (1, -1), font),
        ("FONTSIZE",  (0, 0), (-1, -1), 8.5),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BOX",       (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#DDDDDD")),
    ]))
    story.append(mt2)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph(
        "I certify that the particulars given in this declaration are correct "
        "and that this item does not contain any dangerous article or articles "
        "prohibited by legislation.", TXT,
    ))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC | "
        "ESTRELLA JEWELS Sp. z o. o. Spółka Komandytowa | "
        "ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa, PL", SML,
    ))

    doc.build(story)
    return buf.getvalue()


# ── Merge / package helpers ────────────────────────────────────────────────────

def _merge_pdfs(pdf_list: List[bytes]) -> Optional[bytes]:
    """Merge multiple PDF byte strings into one using pypdf if available.

    Returns None when pypdf is unavailable OR when any PDF is invalid/unreadable
    (e.g. a stub/fake PDF in tests) — caller falls back to ZIP in that case.
    """
    try:
        from pypdf import PdfWriter, PdfReader
        writer = PdfWriter()
        for pdf_bytes in pdf_list:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except ImportError:
        return None  # pypdf not installed → ZIP
    except Exception as exc:
        log.debug("_merge_pdfs failed (will fall back to ZIP): %s", exc)
        return None  # invalid PDF input → ZIP


def _make_zip(named_pdfs: List[tuple]) -> bytes:
    """Pack [(filename, bytes), ...] into a ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in named_pdfs:
            zf.writestr(name, data)
    return buf.getvalue()


# ── Main assembler ────────────────────────────────────────────────────────────

def assemble_label_package(
    batch_id:     str,
    inputs:       LabelPackageInputs,
    storage_root: Path,
) -> "LabelPackageResult | LabelPackageGaps":
    """
    Assemble the outbound label / customs package for a batch.

    ALWAYS included:
      - Commercial invoice PDF (fetched from wFirma — requires posted proforma)
      - Packing list PDF (generated locally)

    CONDITIONALLY included (non-EU destinations only):
      - CN23 customs declaration PDF

    Returns LabelPackageResult on success or LabelPackageGaps when mandatory
    inputs are missing (caller raises 422).

    Soft gaps (blank receiver address, missing weight) are written as advisory
    action_proposals to audit.json but do NOT block generation.
    """
    audit_path = storage_root / "outputs" / batch_id / "audit.json"
    advisories: List[str] = []

    # ── 1. Load context ────────────────────────────────────────────────────────
    company  = _load_company_profile(storage_root)
    draft    = _load_proforma_draft(batch_id, inputs.client_name, storage_root)
    customer = _resolve_customer_from_batch(batch_id, inputs.client_name, storage_root)
    audit    = _load_audit(batch_id, storage_root)

    # Determine destination country
    dest_country = (getattr(customer, "country", None) or "").strip().upper()
    is_eu = dest_country in EU_COUNTRIES

    # ── 2. Mandatory validation ────────────────────────────────────────────────
    gaps: List[Dict[str, str]] = []

    # Dimensions — always required
    if not (inputs.length_cm and inputs.width_cm and inputs.height_cm):
        gaps.append({
            "field":  "dimensions",
            "reason": "length_cm, width_cm, height_cm are required for all shipments",
        })

    # Commercial invoice — requires posted proforma
    if draft is None or not (getattr(draft, "wfirma_proforma_id", None) or "").strip():
        gaps.append({
            "field":  "proforma",
            "reason": (
                "Commercial invoice unavailable — no proforma has been posted to wFirma "
                "for this batch/client. Post the proforma first (WF2.4)."
            ),
        })

    # Non-EU extras
    if not is_eu:
        if not inputs.incoterm:
            gaps.append({
                "field":  "incoterm",
                "reason": "Incoterm is required for non-EU international shipments (CN23)",
            })
        if not inputs.receiver_eori:
            gaps.append({
                "field":  "receiver_eori",
                "reason": (
                    "Receiver EORI is required for non-EU shipments. "
                    "Set it in customer_master or supply it in the request."
                ),
            })

    if gaps:
        return LabelPackageGaps(gaps=gaps)

    # ── 3. Soft gap checks (advisory, do not block) ───────────────────────────

    # Receiver address: resolved via Customer Master resolve_delivery_address()
    # Authority: ship_to_use_alternate=True AND address populated → ship_to;
    #            otherwise → bill_to fallback with advisory.
    delivery_addr: Optional[Dict[str, str]] = None
    _using_ship_to = False
    if customer:
        from ..customer_master import resolve_delivery_address
        delivery_addr = resolve_delivery_address(customer)
        if delivery_addr.get("source") == "ship_to":
            _using_ship_to = True
        else:
            # Fallback to bill_to — write advisory
            cust_name = getattr(customer, "bill_to_name", "?") or "?"
            msg = (
                f"Receiver {cust_name}: ship_to address not active or not set "
                "in customer_master — falling back to bill_to address. "
                "Verify delivery address before dispatch."
            )
            _write_soft_advisory(audit_path, "ship_to_missing", msg)
            advisories.append(msg)
            if not delivery_addr.get("street"):
                msg2 = (
                    f"Receiver {cust_name} has no street address "
                    "(neither ship_to nor bill_to) — label may be incomplete."
                )
                _write_soft_advisory(audit_path, "receiver_address_incomplete", msg2)
                advisories.append(msg2)

    # Weight: sum packing_lines gross weight + box tare
    packing_lines = _load_packing_lines(batch_id, storage_root)
    goods_weight_g = sum(float(ln.get("gross_weight") or 0) for ln in packing_lines)
    tare_g = (inputs.tare_weight_kg or 0) * 1000.0
    total_gw = goods_weight_g + tare_g

    if goods_weight_g == 0:
        msg = (
            "Gross weight is 0 for all packing lines — confirm weight before dispatch. "
            f"Total weight will be box tare only ({tare_g:.0f} g)."
        )
        _write_soft_advisory(audit_path, "weight_zero", msg)
        advisories.append(msg)

    # ── 4. Fetch commercial invoice from wFirma ───────────────────────────────
    wfirma_id = (getattr(draft, "wfirma_proforma_id", "") or "").strip()
    from .. import wfirma_client
    invoice_pdf: bytes = wfirma_client.fetch_invoice_pdf(wfirma_id)

    # ── 5. Generate packing list ──────────────────────────────────────────────
    packing_pdf: bytes = render_packing_list_pdf(
        batch_id, storage_root, company, customer, draft,
        delivery_addr=delivery_addr,
    )

    # ── 6. Generate CN23 (non-EU only) ────────────────────────────────────────
    cn23_pdf: Optional[bytes] = None
    if not is_eu:
        cn23_pdf = render_cn23_pdf(
            batch_id, storage_root, inputs, company, customer, draft,
            delivery_addr=delivery_addr,
        )

    # ── 7. Assemble package ───────────────────────────────────────────────────
    prof_ref = (
        (getattr(draft, "wfirma_proforma_fullnumber", "") or "")
        .replace("/", "-").replace(" ", "_")
    ) or batch_id[-12:]

    components = ["invoice", "packing_list"]
    if cn23_pdf:
        components.append("cn23")

    pdfs_to_merge = [invoice_pdf, packing_pdf]
    filenames = [
        (f"invoice_{prof_ref}.pdf", invoice_pdf),
        (f"packing_list_{prof_ref}.pdf", packing_pdf),
    ]
    if cn23_pdf:
        pdfs_to_merge.append(cn23_pdf)
        filenames.append((f"cn23_{prof_ref}.pdf", cn23_pdf))

    merged = _merge_pdfs(pdfs_to_merge)
    if merged:
        return LabelPackageResult(
            content      = merged,
            filename     = f"label_package_{prof_ref}.pdf",
            content_type = "application/pdf",
            components   = components,
            advisories   = advisories,
        )
    else:
        # pypdf unavailable → ZIP
        zip_bytes = _make_zip(filenames)
        return LabelPackageResult(
            content      = zip_bytes,
            filename     = f"label_package_{prof_ref}.zip",
            content_type = "application/zip",
            components   = components,
            advisories   = advisories,
        )
