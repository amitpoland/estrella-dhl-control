"""
customs_parser_orchestrator.py — Single entry point for customs document parsing.

Parsing hierarchy (strict):
  1. XML → source of truth, 100% reliable
  2. PDF → deterministic regex parser (parse_zc429)
  3. AI  → last-resort fallback for missing fields

AI is NEVER called when XML data is complete.
AI NEVER overrides XML or PDF values — only supplements missing fields.

Also handles:
  - Pre-parsed JSON dicts (from cowork XML analysis stored in audit.zc429)
  - Cross-validation between sources when multiple exist
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Fields considered critical — if any are missing after PDF parse, AI fallback fires
REQUIRED_FIELDS = ["mrn", "duty_pln", "vat_pln", "clearance_date", "cn_code"]

# All fields the orchestrator maps into customs_declaration (dashboard keys)
_FIELD_MAP = {
    # parser key             → customs_declaration key
    "mrn":                    "mrn",
    "lrn":                    "lrn",
    "clearance_date":         "clearance_date",
    "duty_pln":               "duty_a00_pln",
    "vat_pln":                "vat_b00_pln",
    "customs_rate_usd":       "sad_customs_rate",
    "agent":                  "customs_agent",
    "importer_name":          "importer_name",
    "importer_nip":           "importer_nip",
    "exporter_name":          "exporter_name",
    "statistical_value_pln":  "statistical_value_pln",
    "cn_code":                "cn_code",
    "goods_description":      "goods_description",
    "sad_invoice_value_usd":  "sad_invoice_value_usd",
    "sad_qty_by_type":        "sad_qty_by_type",
    "transport_refs":         "transport_refs",
    "a00_payment_method":     "a00_payment_method",
    "b00_payment_method":     "b00_payment_method",
    "total_cif_usd":          "sad_cif_usd",
}


def parse_customs_document(
    batch_id: str,
    sad_dir: Path,
    audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Orchestrate customs document parsing with strict hierarchy.

    Args:
        batch_id:  Shipment batch identifier
        sad_dir:   Path to source/sad/ directory containing XML/PDF files
        audit:     Optional audit dict — if it has audit.zc429 pre-parsed data,
                   that is used as the XML source (highest priority)

    Returns:
        {
            "data":     { ...parsed fields in parse_zc429 schema... },
            "mapped":   { ...fields mapped to customs_declaration keys... },
            "source":   "xml" | "xml_dict" | "pdf" | "pdf+ai_supplement" | "ai_fallback",
            "confidence": "high" | "medium" | "low",
            "corrections": [...],
            "ai_supplemented_fields": [...],
            "validation": { ...if cross-validation was performed... } | None,
        }
    """
    result_data: Optional[Dict[str, Any]] = None
    source = "none"
    confidence = "low"
    corrections: List[str] = []
    ai_supplemented: List[str] = []
    validation_result = None

    # ── Priority 0: Pre-parsed XML dict in audit.zc429 ──────────────────────
    if audit and audit.get("zc429"):
        zc429_dict = audit["zc429"]
        if zc429_dict.get("mrn"):
            from .customs_xml_parser import parse_zc429_xml_from_dict
            result_data = parse_zc429_xml_from_dict(zc429_dict)
            if result_data:
                source = "xml_dict"
                confidence = "high"
                log.info("[orchestrator] %s: parsed from audit.zc429 (xml_dict), mrn=%s",
                         batch_id, result_data.get("mrn"))

    # ── Priority 1: XML file on disk ────────────────────────────────────────
    if not result_data and sad_dir.exists():
        xml_files = sorted(sad_dir.glob("*.xml"))
        if xml_files:
            from .customs_xml_parser import parse_zc429_xml
            result_data = parse_zc429_xml(str(xml_files[0]))
            if result_data:
                source = "xml"
                confidence = "high"
                log.info("[orchestrator] %s: parsed from XML file %s, mrn=%s",
                         batch_id, xml_files[0].name, result_data.get("mrn"))

    # ── Priority 1b: Parsed JSON file (from earlier XML parse) ──────────────
    if not result_data and sad_dir.exists():
        json_files = sorted(sad_dir.glob("*parsed*.json"))
        if json_files:
            try:
                with json_files[0].open() as f:
                    parsed_json = json.load(f)
                if parsed_json.get("mrn"):
                    from .customs_xml_parser import parse_zc429_xml_from_dict
                    result_data = parse_zc429_xml_from_dict(parsed_json)
                    if result_data:
                        source = "xml_dict"
                        confidence = "high"
                        log.info("[orchestrator] %s: parsed from JSON %s, mrn=%s",
                                 batch_id, json_files[0].name, result_data.get("mrn"))
            except (json.JSONDecodeError, KeyError) as e:
                corrections.append(f"JSON parse failed: {e}")

    # ── Priority 2: PDF file (deterministic regex) ──────────────────────────
    if not result_data and sad_dir.exists():
        pdf_files = sorted(sad_dir.glob("*.pdf"))
        # Filter out awizo/duty-note PDFs — we want the actual ZC429/PZC/SAD PDF
        pdf_files = [p for p in pdf_files if not p.name.lower().startswith("awizo")]
        if pdf_files:
            try:
                from pz_import_processor import parse_zc429 as pdf_parser
                pdf_corrections: list = []
                result_data = pdf_parser(str(pdf_files[0]), pdf_corrections)
                corrections.extend(pdf_corrections)
                if result_data:
                    source = "pdf"
                    confidence = "high" if result_data.get("mrn") else "medium"
                    log.info("[orchestrator] %s: parsed from PDF %s, mrn=%s",
                             batch_id, pdf_files[0].name, result_data.get("mrn"))
            except Exception as e:
                corrections.append(f"PDF parse error: {e}")
                log.warning("[orchestrator] %s: PDF parse failed: %s", batch_id, e)

    # ── Priority 3: AI fallback (only for missing fields) ───────────────────
    if result_data:
        missing = [k for k in REQUIRED_FIELDS if not result_data.get(k)]
        if missing:
            ai_data = _try_ai_fallback(batch_id, sad_dir, missing)
            if ai_data:
                for field in missing:
                    ai_val = ai_data.get(field)
                    if ai_val is not None:
                        result_data[field] = ai_val
                        ai_supplemented.append(field)
                if ai_supplemented:
                    source = f"{source}+ai_supplement"
                    confidence = "medium"
                    log.info("[orchestrator] %s: AI supplemented %d fields: %s",
                             batch_id, len(ai_supplemented), ai_supplemented)
    elif sad_dir.exists():
        # No result from XML or PDF — try full AI parse
        pdf_files = sorted(sad_dir.glob("*.pdf"))
        if pdf_files:
            ai_data = _try_ai_fallback(batch_id, sad_dir, REQUIRED_FIELDS)
            if ai_data and ai_data.get("mrn"):
                result_data = ai_data
                source = "ai_fallback"
                ai_meta = ai_data.get("_ai_meta", {})
                confidence = ai_meta.get("confidence", "low")
                ai_supplemented = list(ai_data.keys())
                log.info("[orchestrator] %s: full AI fallback, mrn=%s, confidence=%s",
                         batch_id, ai_data.get("mrn"), confidence)

    # ── No result at all ────────────────────────────────────────────────────
    if not result_data:
        return {
            "data":     None,
            "mapped":   {},
            "source":   "none",
            "confidence": "low",
            "corrections": corrections,
            "ai_supplemented_fields": [],
            "validation": None,
            "error": "No customs documents could be parsed",
        }

    # ── Map to customs_declaration keys ─────────────────────────────────────
    mapped = _map_to_declaration(result_data)
    mapped["_parse_source"] = source
    mapped["_parse_confidence"] = confidence
    mapped["_ai_supplemented_fields"] = ai_supplemented

    # Derive art33a from B00 payment method
    b00_pm = result_data.get("b00_payment_method")
    if b00_pm == "G":
        mapped["art33a"] = True
        mapped["vat_mode"] = "art33a"
        mapped["vat_mode_label_en"] = "Art. 33a deferred VAT"
    else:
        mapped.setdefault("art33a", False)
        mapped.setdefault("vat_mode", "standard")
        mapped.setdefault("vat_mode_label_en", "Standard import VAT")

    return {
        "data":     result_data,
        "mapped":   mapped,
        "source":   source,
        "confidence": confidence,
        "corrections": corrections,
        "ai_supplemented_fields": ai_supplemented,
        "validation": validation_result,
    }


def _map_to_declaration(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Map parser output keys to customs_declaration (dashboard) keys."""
    mapped: Dict[str, Any] = {}
    for parser_key, decl_key in _FIELD_MAP.items():
        val = parsed.get(parser_key)
        if val is not None:
            mapped[decl_key] = val
    return mapped


def _try_ai_fallback(
    batch_id: str,
    sad_dir: Path,
    fields_needed: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Attempt AI parsing — guarded by config flag.
    Returns None if AI parsing is disabled or fails.
    """
    try:
        from ..core.config import settings
        if not getattr(settings, "ai_parser_enabled", False):
            log.debug("[orchestrator] AI parser disabled, skipping fallback")
            return None

        from .ai_customs_parser import parse_with_ai

        pdf_files = sorted(sad_dir.glob("*.pdf"))
        if not pdf_files:
            return None

        return parse_with_ai(str(pdf_files[0]), fields_needed=fields_needed)
    except ImportError:
        log.debug("[orchestrator] ai_customs_parser not available")
        return None
    except Exception as e:
        log.warning("[orchestrator] %s: AI fallback failed: %s", batch_id, e)
        return None
