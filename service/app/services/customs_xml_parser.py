"""
customs_xml_parser.py — Parse ZC429/SAD XML into the canonical customs schema.

XML is the source of truth for customs data. This parser extracts structured
fields directly from the ZC429 XML elements — no regex, no AI, 100% deterministic.

Returns the same dict schema as parse_zc429() (the PDF parser) so both can be
used interchangeably by the orchestrator.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def parse_zc429_xml(xml_path: str) -> Optional[Dict[str, Any]]:
    """
    Parse a ZC429 XML file into the canonical customs declaration schema.

    Returns dict matching parse_zc429() output keys, or None on parse failure.
    """
    path = Path(xml_path)
    if not path.exists():
        log.error("[xml_parser] file not found: %s", xml_path)
        return None

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
    except ET.ParseError as e:
        log.error("[xml_parser] XML parse error: %s", e)
        return None

    # Strip namespaces for easier access
    ns_stripped = _strip_namespaces(root)

    result = _extract_from_tree(ns_stripped)
    if result:
        result["_parse_meta"] = {
            "source": "xml",
            "file": path.name,
            "confidence": "high",
        }
    return result


def parse_zc429_xml_from_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert an already-parsed ZC429 dict (e.g. from ZC429_parsed.json) into
    the canonical customs_declaration schema.

    This handles the case where XML was parsed externally (by cowork or another
    tool) and stored as JSON in the audit.
    """
    if not data:
        return None

    items = data.get("goods_items") or []

    # Aggregate from goods items
    total_invoiced_usd = 0.0
    total_stat_pln = 0.0
    all_invoice_refs: List[str] = []
    cn_codes: List[str] = []
    descriptions: List[str] = []
    qty_by_type: Dict[str, str] = {}
    clearance_date: Optional[str] = None

    a00_payment_method: Optional[str] = None
    b00_payment_method: Optional[str] = None

    for g in items:
        total_invoiced_usd += _safe_float(g.get("invoiced_usd") or g.get("invoiced"))
        total_stat_pln += _safe_float(g.get("statistical_value_pln") or g.get("statisticalValue"))
        for inv in (g.get("invoices") or []):
            if inv not in all_invoice_refs:
                all_invoice_refs.append(inv)
        hs = g.get("hs_code") or g.get("HS_code") or ""
        if hs:
            cn_codes.append(hs)
        desc = g.get("description") or ""
        if desc:
            descriptions.append(desc)
        if hs and desc:
            qty_by_type[hs] = desc
        rd = g.get("release_date") or g.get("releaseDate")
        if rd and not clearance_date:
            clearance_date = str(rd)[:10]
        # Payment methods from goods items (first item wins)
        if not a00_payment_method:
            a00_payment_method = g.get("a00_payment_method") or g.get("A00_payment_method")
        if not b00_payment_method:
            b00_payment_method = g.get("b00_payment_method") or g.get("B00_payment_method")

    # Total duties
    total_a00 = _safe_float(
        data.get("total_A00_duty_pln")
        or data.get("total_A00_duty")
    )
    total_b00 = _safe_float(
        data.get("total_B00_vat_pln")
        or data.get("total_B00_vat")
    )

    # Exchange rate: statistical_value_pln / invoiced_usd
    customs_rate = None
    if total_invoiced_usd > 0:
        customs_rate = round(total_stat_pln / total_invoiced_usd, 4)

    # Acceptance date fallback for clearance_date
    if not clearance_date:
        acc = data.get("acceptance_date") or data.get("declarationAcceptanceDate") or ""
        if acc:
            clearance_date = str(acc)[:10]

    # Transport refs
    awb = data.get("awb") or data.get("transportDocument_ref") or ""
    transport_refs = [awb] if awb else []

    return {
        # Core identity
        "mrn":              data.get("mrn"),
        "lrn":              data.get("lrn"),
        "clearance_date":   clearance_date,
        # Financial
        "duty_pln":         total_a00,
        "vat_pln":          total_b00,
        "total_cif_usd":    total_invoiced_usd,
        "customs_rate_usd": customs_rate,
        "statistical_value_pln": total_stat_pln,
        "sad_invoice_value_usd": total_invoiced_usd,
        "sad_additions_pln":     0.0,
        # Parties
        "agent":            None,  # Not typically in XML
        "importer_name":    None,  # Could be derived from NIP
        "importer_nip":     data.get("importer_nip"),
        "exporter_name":    data.get("exporter"),
        # Goods
        "cn_code":          ", ".join(cn_codes),
        "goods_description": "; ".join(descriptions),
        "sad_qty_by_type":  qty_by_type,
        # Refs
        "invoice_refs":         all_invoice_refs,
        "invoice_refs_method":  "xml_goods_items",
        "inferred_refs":        [],
        "transport_refs":       transport_refs,
        # Payment methods
        "a00_payment_method":   a00_payment_method,
        "b00_payment_method":   b00_payment_method,
        # Meta
        "_parse_meta": {
            "source":     "xml_dict",
            "confidence": "high",
        },
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _strip_namespaces(root: ET.Element) -> ET.Element:
    """Remove XML namespace prefixes for simpler element access."""
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        for k in list(elem.attrib):
            if "}" in k:
                new_k = k.split("}", 1)[1]
                elem.attrib[new_k] = elem.attrib.pop(k)
    return root


def _extract_from_tree(root: ET.Element) -> Optional[Dict[str, Any]]:
    """Extract customs data from a namespace-stripped XML tree."""
    # Try common ZC429 XML structures
    # Polish customs use various schemas; try the most common paths

    mrn = _find_text(root, ".//MRN") or _find_text(root, ".//mrn")
    lrn = _find_text(root, ".//LRN") or _find_text(root, ".//lrn")

    if not mrn:
        # Try Declaration/Header patterns
        mrn = _find_text(root, ".//Declaration/MRN")
        lrn = _find_text(root, ".//Declaration/LRN")

    if not mrn:
        log.warning("[xml_parser] no MRN found — may not be a ZC429 XML")
        return None

    # Acceptance date
    acc_date = (
        _find_text(root, ".//AcceptanceDateTime")
        or _find_text(root, ".//declarationAcceptanceDate")
        or _find_text(root, ".//IssueDateTime")
    )
    clearance_date = str(acc_date)[:10] if acc_date else None

    # Goods items
    items: List[Dict[str, Any]] = []
    goods_elements = (
        root.findall(".//GovernmentAgencyGoodsItem")
        or root.findall(".//GoodsItem")
        or root.findall(".//goods_item")
    )

    total_a00 = 0.0
    total_b00 = 0.0
    total_invoiced = 0.0
    total_stat = 0.0
    cn_codes: List[str] = []
    descriptions: List[str] = []
    all_invoice_refs: List[str] = []
    qty_by_type: Dict[str, str] = {}
    a00_payment_method: Optional[str] = None
    b00_payment_method: Optional[str] = None

    for gi in goods_elements:
        item = _parse_goods_item(gi)
        items.append(item)
        total_a00 += item.get("a00_duty", 0.0)
        total_b00 += item.get("b00_vat", 0.0)
        total_invoiced += item.get("invoiced_usd", 0.0)
        total_stat += item.get("statistical_value_pln", 0.0)
        if item.get("cn_code"):
            cn_codes.append(item["cn_code"])
        if item.get("description"):
            descriptions.append(item["description"])
        if item.get("cn_code") and item.get("description"):
            qty_by_type[item["cn_code"]] = item["description"]
        for inv_ref in item.get("invoice_refs", []):
            if inv_ref not in all_invoice_refs:
                all_invoice_refs.append(inv_ref)
        # Payment methods — take from first item that has them
        if not a00_payment_method and item.get("a00_payment_method"):
            a00_payment_method = item["a00_payment_method"]
        if not b00_payment_method and item.get("b00_payment_method"):
            b00_payment_method = item["b00_payment_method"]
        # Use release_date from goods items if available (more precise than acceptance date)
        if item.get("release_date") and not clearance_date:
            clearance_date = str(item["release_date"])[:10]

    # If no goods items found, try flat duty elements
    if not goods_elements:
        a00_el = root.find(".//DutyTaxFee[TypeCode='A00']")
        if a00_el is not None:
            total_a00 = _safe_float(_find_text(a00_el, ".//PaymentAmount"))
        b00_el = root.find(".//DutyTaxFee[TypeCode='B00']")
        if b00_el is not None:
            total_b00 = _safe_float(_find_text(b00_el, ".//PaymentAmount"))

    # Parties
    importer_nip = (
        _find_text(root, ".//Importer/nip")
        or _find_text(root, ".//Consignee/ID")
        or _find_text(root, ".//ImporterID")
    )
    exporter = (
        _find_text(root, ".//Exporter/name")
        or _find_text(root, ".//Exporter/Name")
        or _find_text(root, ".//Consignor/Name")
    )
    importer_name = _find_text(root, ".//Consignee/Name") or _find_text(root, ".//Importer/Name")
    agent = _find_text(root, ".//Declarant/Name") or _find_text(root, ".//Agent/Name")
    # Declarant contact info
    agent_contact = _find_text(root, ".//Declarant/ContactPerson/name")
    agent_email = _find_text(root, ".//Declarant/ContactPerson/eMailAddress")
    # Representative
    rep_contact = _find_text(root, ".//Representative/ContactPerson/name")

    # Transport
    awb = (
        _find_text(root, ".//TransportDocument/referenceNumber")
        or _find_text(root, ".//TransportDocument/ID")
        or ""
    )
    transport_refs = [awb] if awb else []

    # Exchange rate
    customs_rate = None
    rate_el = _find_text(root, ".//CurrencyExchange/RateNumeric")
    if rate_el:
        customs_rate = _safe_float(rate_el)
    elif total_invoiced > 0 and total_stat > 0:
        customs_rate = round(total_stat / total_invoiced, 4)

    return {
        "mrn":              mrn,
        "lrn":              lrn,
        "clearance_date":   clearance_date,
        "duty_pln":         total_a00,
        "vat_pln":          total_b00,
        "total_cif_usd":    total_invoiced,
        "customs_rate_usd": customs_rate,
        "statistical_value_pln": total_stat,
        "sad_invoice_value_usd": total_invoiced,
        "sad_additions_pln":     0.0,
        "agent":            agent,
        "importer_name":    importer_name,
        "importer_nip":     importer_nip,
        "exporter_name":    exporter,
        "cn_code":          ", ".join(cn_codes),
        "goods_description": "; ".join(descriptions),
        "sad_qty_by_type":  qty_by_type,
        "invoice_refs":         all_invoice_refs,
        "invoice_refs_method":  "xml_elements",
        "inferred_refs":        [],
        "transport_refs":       transport_refs,
        "a00_payment_method":   a00_payment_method,
        "b00_payment_method":   b00_payment_method,
    }


def _parse_goods_item(el: ET.Element) -> Dict[str, Any]:
    """Parse a single goods item element."""
    cn_code = (
        _find_text(el, ".//CommodityCode/harmonisedSystemSubheadingCode")
        or _find_text(el, ".//CommodityCode")
        or _find_text(el, ".//Commodity/Classification/ID")
        or ""
    )
    desc = (
        _find_text(el, "descriptionOfGoods")
        or _find_text(el, ".//Description")
        or _find_text(el, ".//GoodsDescription")
        or ""
    )
    invoiced = _safe_float(
        _find_text(el, "itemAmountInvoiced")
        or _find_text(el, ".//InvoiceAmount")
        or _find_text(el, ".//ItemAmount")
    )
    stat_val = _safe_float(
        _find_text(el, "statisticalValue")
        or _find_text(el, ".//StatisticalValueAmount")
        or _find_text(el, ".//StatisticalValue")
    )

    # Duties and payment methods
    a00 = 0.0
    b00 = 0.0
    a00_method = None
    b00_method = None
    for dtf in el.findall(".//DutyTaxFee"):
        code = _find_text(dtf, "TypeCode") or _find_text(dtf, "DutyRegimeCode") or ""
        amount = _safe_float(_find_text(dtf, ".//PaymentAmount") or _find_text(dtf, ".//TaxAmount"))
        method = _find_text(dtf, "MethodOfPayment") or _find_text(dtf, "methodOfPayment") or None
        if "A00" in code:
            a00 = amount
            a00_method = method
        elif "B00" in code:
            b00 = amount
            b00_method = method
    # Also check DutiesAndTaxes elements (Polish ZC429 XML schema)
    for dtf in el.findall(".//DutiesAndTaxes"):
        code = _find_text(dtf, "taxType") or ""
        amount = _safe_float(_find_text(dtf, "payableTaxAmount"))
        method = _find_text(dtf, "methodOfPayment") or None
        if code == "A00":
            a00 = amount
            a00_method = method
        elif code == "B00":
            b00 = amount
            b00_method = method

    # Invoice refs — check both AdditionalDocument and SupportingDocument
    inv_refs: List[str] = []
    for doc in el.findall(".//AdditionalDocument") + el.findall(".//SupportingDocument"):
        doc_type = _find_text(doc, "TypeCode") or _find_text(doc, "type") or ""
        doc_id = _find_text(doc, "ID") or _find_text(doc, "referenceNumber") or ""
        if doc_type in ("N935", "N380") and doc_id:
            # Strip date suffix (e.g. "EJL/26-27/098 Z 25.04.2026" → "EJL/26-27/098")
            clean_id = doc_id.split(" Z ")[0].strip() if " Z " in doc_id else doc_id.strip()
            if clean_id not in inv_refs:
                inv_refs.append(clean_id)

    # Release date
    release_date = _find_text(el, "releaseDate") or _find_text(el, ".//ReleaseDate")

    return {
        "cn_code":              cn_code,
        "description":          desc,
        "invoiced_usd":         invoiced,
        "statistical_value_pln": stat_val,
        "a00_duty":             a00,
        "b00_vat":              b00,
        "a00_payment_method":   a00_method,
        "b00_payment_method":   b00_method,
        "invoice_refs":         inv_refs,
        "release_date":         release_date,
    }


def _find_text(el: ET.Element, path: str) -> Optional[str]:
    """Find element text, return None if not found or empty."""
    found = el.find(path)
    if found is not None and found.text:
        return found.text.strip()
    return None


def _safe_float(val: Any) -> float:
    """Convert to float safely, return 0.0 on failure.

    DELIBERATELY NOT the packing normaliser in invoice_packing_extractor, and
    must not be "harmonised" with it. Customs XML (PUESC/ZC429/SAD) is
    machine-generated in the Polish locale: the comma is ALWAYS the decimal
    separator and values are never digit-grouped. A netMass of "1,554" is
    1.554 kg. The packing rule reads a comma followed by exactly three digits
    as a thousands separator -- correct for EJL packing lists, but it would
    turn that same weight into 1554.0 here.
    """
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return 0.0
