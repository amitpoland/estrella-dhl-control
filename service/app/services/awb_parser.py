"""
awb_parser.py — Lightweight AWB/Waybill PDF field extractor.

Uses pdfplumber for text extraction + regex patterns matched against
DHL Express waybill format (the primary carrier in use).

All fields are best-effort. Missing fields return empty string / None.
Never raises — callers receive a partial dict on parse failures.

Public API
----------
  parse_awb_pdf(path: Path) -> Dict[str, Any]
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.logging import get_logger

log = get_logger(__name__)

# ── Regex patterns (DHL WPX format) ───────────────────────────────────────────

_RE_AWB        = re.compile(r'WAYBILL\s+(\d[\d\s]{6,20}\d)', re.IGNORECASE)
_RE_AWB2       = re.compile(r'\b(\d{10,12})\b')          # fallback: standalone number
_RE_REF        = re.compile(r'Ref:\s*([A-Z0-9/,\-\.]+)', re.IGNORECASE)
_RE_WEIGHT     = re.compile(r'(\d+[\.,]\d*)\s*kg', re.IGNORECASE)
_RE_PIECES     = re.compile(r'(?:Pce/Shpt|Pieces?)[:\s]+(\d+)', re.IGNORECASE)
_RE_SHIP_DATE  = re.compile(r'(\d{4}-\d{2}-\d{2})', re.IGNORECASE)
_RE_ORIGIN     = re.compile(r'Origin[:\s]+([A-Z]{3})', re.IGNORECASE)
_RE_FROM_CITY  = re.compile(r'From\s*:.*?(\w[\w\s,]+(?:India|China|Thailand|HongKong|Singapore|Japan))', re.IGNORECASE | re.DOTALL)
_RE_TO_CITY    = re.compile(r'To\s*:.*?(\w[\w\s,]+(?:Poland|Germany|France|UK|USA|Netherlands))', re.IGNORECASE | re.DOTALL)
_RE_FREIGHT_AC = re.compile(r'Freight\s+A/C[:\s]+([0-9]+)', re.IGNORECASE)
_RE_DUTY_AC    = re.compile(r'Duty\s+A/C[:\s]+([^\n]+)', re.IGNORECASE)
_RE_TAX_AC     = re.compile(r'Tax(?:es)?\s+A/C[:\s]+([^\n]+)', re.IGNORECASE)
_RE_CONTENTS   = re.compile(r'Contents?\s*:(.*?)(?:WAYBILL|License|$)', re.IGNORECASE | re.DOTALL)
_RE_ROUTE      = re.compile(r'([A-Z]{2}-[A-Z]{3}-[A-Z]{3})\s+([A-Z]{2}-[A-Z]{3}-[A-Z]{3})', re.IGNORECASE)
_RE_PRODUCT    = re.compile(r'\[P\]\s+(.+?)(?:\(|\n)', re.IGNORECASE)

# ── Customs value ("Custom Val" field) ─────────────────────────────────────────
# DHL waybills render this field inconsistently. The currency can lead OR trail
# the amount, can be glued to it, the amount can carry thousands separators, and
# the label varies ("Custom Val", "Customs Value", "Customs Val:", with an
# optional parenthetical). The previous single regex only matched the
# currency-SUFFIX form (`Custom Val: 732.00 USD`) with the number immediately
# after the colon; every other rendering silently produced customs_value=None,
# which downstream coerced to 0.00 and blocked clearance routing.
#
# Strategy: locate the label, then scan a short window after it for an amount
# with an optional adjacent currency code on EITHER side.
_KNOWN_CURRENCIES = {
    "USD", "EUR", "GBP", "INR", "CHF", "HKD", "SGD", "JPY",
    "CNY", "AED", "PLN", "THB", "AUD", "CAD",
}
_RE_CUSTOM_VAL_LABEL = re.compile(
    r'Custom(?:s)?\s*Val(?:ue)?\s*(?:\([^)]*\))?\s*[:\-]?\s*',
    re.IGNORECASE,
)
# amount with optional leading and/or trailing 3-letter currency code,
# allowing the currency to be glued to the number (USD732.00 / 732.00USD)
_RE_VALUE_CCY = re.compile(
    r'(?P<ccy_pre>[A-Z]{3})?\s*'
    r'(?P<amt>\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)'
    r'\s*(?P<ccy_post>[A-Z]{3})?'
)


def _clean(s: str) -> str:
    return " ".join(s.split()).strip()


def _extract_customs_value(text: str):
    """Best-effort extraction of the waybill 'Custom Val' field.

    Returns (value: Optional[float], currency: str, source: str). ``source``
    documents how the value was obtained so callers can log provenance:
      - "custom_val_label"  → matched amount adjacent to the Custom Val label
      - "label_no_value"    → label present but no amount found (VERIFY-GAP)
      - "no_label"          → the Custom Val label never appeared

    Handles currency on either side of the amount, glued or spaced, with
    optional thousands separators, and label variants (Custom Val / Customs
    Value / parenthetical suffixes).
    """
    for lbl in _RE_CUSTOM_VAL_LABEL.finditer(text):
        # Look at the remainder of the label's line first, then fall back to
        # the next non-empty line (some layouts wrap the value).
        tail = text[lbl.end(): lbl.end() + 64]
        candidates = [seg for seg in tail.split("\n") if seg.strip()][:2]
        for seg in candidates:
            m = _RE_VALUE_CCY.match(seg.strip())
            if not m or not m.group("amt"):
                # search anywhere in the segment, not just at its start
                m = _RE_VALUE_CCY.search(seg)
            if m and m.group("amt"):
                amt_str = m.group("amt").replace(",", "").replace(" ", "")
                try:
                    value = float(amt_str)
                except ValueError:
                    continue
                ccy = ""
                for grp in (m.group("ccy_post"), m.group("ccy_pre")):
                    if grp and grp.upper() in _KNOWN_CURRENCIES:
                        ccy = grp.upper()
                        break
                return value, ccy, "custom_val_label"
        # Label found but nothing parseable on its line(s)
        return None, "", "label_no_value"
    return None, "", "no_label"


def _extract_shipper_receiver(text: str):
    """Extract shipper and receiver name/address blocks."""
    shipper_name = shipper_address = receiver_name = receiver_address = ""

    # Look for "Shipper :" block
    m = re.search(r'Shipper\s*:\s*\n(.*?)(?=Receiver\s*:|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        block = m.group(1).strip().split('\n')
        block = [ln.strip() for ln in block if ln.strip() and 'Contact' not in ln]
        if block:
            shipper_name = block[0]
            shipper_address = ", ".join(block[1:5])

    # Look for "From :" block (alternative format)
    if not shipper_name:
        m = re.search(r'From\s*:\s*([^\n]+)', text, re.IGNORECASE)
        if m:
            shipper_name = _clean(m.group(1))

    # Receiver / To
    m = re.search(r'Receiver\s*:\s*\n(.*?)(?=Product Details|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        block = m.group(1).strip().split('\n')
        block = [ln.strip() for ln in block if ln.strip() and 'Contact' not in ln]
        if block:
            receiver_name = block[0]
            receiver_address = ", ".join(block[1:5])

    if not receiver_name:
        m = re.search(r'To\s*:\s*([^\n]+)', text, re.IGNORECASE)
        if m:
            receiver_name = _clean(m.group(1))

    return _clean(shipper_name), _clean(shipper_address), _clean(receiver_name), _clean(receiver_address)


def parse_awb_pdf(path: Path) -> Dict[str, Any]:
    """
    Extract structured fields from an AWB/waybill PDF.

    Returns a dict with keys matching awb_documents schema:
      awb_number, carrier, shipper_name, shipper_address,
      receiver_name, receiver_address, shipment_reference,
      customs_value, currency, declared_weight, piece_count,
      ship_date, contents, origin, destination,
      duty_account, tax_account
    Plus: raw_text (first 2000 chars), confidence (0-1)
    """
    result: Dict[str, Any] = {
        "awb_number":         "",
        "carrier":            "",
        "shipper_name":       "",
        "shipper_address":    "",
        "receiver_name":      "",
        "receiver_address":   "",
        "shipment_reference": "",
        "customs_value":      None,
        "currency":           "",
        "declared_weight":    None,
        "piece_count":        None,
        "ship_date":          "",
        "contents":           "",
        "origin":             "",
        "destination":        "",
        "duty_account":       "",
        "tax_account":        "",
        "raw_text":           "",
        "confidence":         0.0,
    }
    try:
        import pdfplumber
    except ImportError:
        log.warning("pdfplumber not installed — AWB text extraction skipped")
        return result

    try:
        text = ""
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:3]:
                t = page.extract_text() or ""
                text += t + "\n"
        result["raw_text"] = text[:2000]
    except Exception as exc:
        log.warning("AWB PDF open failed: %s — %s", path, exc)
        return result

    # ── AWB number ────────────────────────────────────────────────────────────
    m = _RE_AWB.search(text)
    if m:
        result["awb_number"] = re.sub(r'\s+', '', m.group(1))
    else:
        # Use filename as fallback (e.g. "2824221912 Tracking details.pdf")
        stem = path.stem
        m2 = _RE_AWB2.search(stem)
        if m2:
            result["awb_number"] = m2.group(1)

    # ── Carrier ───────────────────────────────────────────────────────────────
    text_upper = text.upper()
    if "DHL" in text_upper or "WAYBILL" in text_upper:
        result["carrier"] = "DHL"
    elif "FEDEX" in text_upper:
        result["carrier"] = "FedEx"
    elif "UPS" in text_upper:
        result["carrier"] = "UPS"

    # ── Shipper / Receiver ────────────────────────────────────────────────────
    sn, sa, rn, ra = _extract_shipper_receiver(text)
    result["shipper_name"]    = sn
    result["shipper_address"] = sa
    result["receiver_name"]   = rn
    result["receiver_address"] = ra

    # ── Reference ─────────────────────────────────────────────────────────────
    m = _RE_REF.search(text)
    if m:
        result["shipment_reference"] = _clean(m.group(1).rstrip(','))

    # ── Customs value + currency ───────────────────────────────────────────────
    cv_value, cv_ccy, cv_source = _extract_customs_value(text)
    if cv_value is not None:
        result["customs_value"] = cv_value
        if cv_ccy:
            result["currency"] = cv_ccy
        elif "USD" in text_upper:
            result["currency"] = "USD"
        elif "EUR" in text_upper:
            result["currency"] = "EUR"
        log.info(
            "AWB customs value parsed: value=%.2f currency=%s source=%s",
            cv_value, result["currency"] or "?", cv_source,
        )
    else:
        # None ≠ 0.00. Surface a verify-gap so downstream can distinguish
        # "genuinely zero" from "parser could not read it" (the bug that
        # silently blocked clearance routing for AWB 2315714531).
        result["customs_value_gap"] = cv_source  # "label_no_value" | "no_label"
        log.warning(
            "AWB customs value NOT extracted (source=%s) — leaving "
            "customs_value=None for downstream VERIFY-GAP handling, NOT 0.00",
            cv_source,
        )

    # ── Weight ────────────────────────────────────────────────────────────────
    m = _RE_WEIGHT.search(text)
    if m:
        try:
            result["declared_weight"] = float(m.group(1).replace(',', '.'))
        except ValueError:
            pass

    # ── Piece count ───────────────────────────────────────────────────────────
    m = _RE_PIECES.search(text)
    if m:
        try:
            result["piece_count"] = int(m.group(1))
        except ValueError:
            pass

    # ── Ship date ─────────────────────────────────────────────────────────────
    m = _RE_SHIP_DATE.search(text)
    if m:
        result["ship_date"] = m.group(1)

    # ── Origin / destination from route code ──────────────────────────────────
    m = _RE_ORIGIN.search(text)
    if m:
        result["origin"] = m.group(1).upper()
    m = _RE_ROUTE.search(text)
    if m:
        result["origin"]      = result["origin"] or m.group(1).split('-')[-1]
        result["destination"] = m.group(2).split('-')[-1]

    # ── Contents ──────────────────────────────────────────────────────────────
    m = _RE_CONTENTS.search(text)
    if m:
        raw = _clean(m.group(1))
        result["contents"] = raw[:300]

    # ── Freight / Duty / Tax accounts ─────────────────────────────────────────
    m = _RE_DUTY_AC.search(text)
    if m:
        result["duty_account"] = _clean(m.group(1))

    m = _RE_TAX_AC.search(text)
    if m:
        result["tax_account"] = _clean(m.group(1))

    # ── Confidence: count filled fields ───────────────────────────────────────
    key_fields = ["awb_number", "carrier", "shipper_name", "receiver_name",
                  "customs_value", "declared_weight", "ship_date"]
    filled = sum(1 for k in key_fields if result.get(k))
    result["confidence"] = round(filled / len(key_fields), 2)

    log.info("AWB parsed: awb=%s carrier=%s conf=%.2f",
             result["awb_number"], result["carrier"], result["confidence"])
    return result
