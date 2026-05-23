"""
ai_customs_parser.py — AI-powered customs document parser (FALLBACK ONLY).

This is the LAST resort when XML and PDF deterministic parsers fail.
It uses an LLM to extract structured fields from PDF text.

Hard rules:
  - Extraction only — NO financial recalculation
  - Returns null for any field not confidently identified
  - Must include confidence level
  - NEVER called when XML data is available and complete
  - NEVER overrides XML or PDF parser values
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Schema that the AI must return — matches parse_zc429() output format
_EXTRACTION_SCHEMA = {
    "mrn": "string — MRN number (e.g. 26PL44302D00A1J5R7)",
    "lrn": "string — LRN number",
    "clearance_date": "string — date in YYYY-MM-DD format",
    "duty_pln": "number — A00 customs duty in PLN",
    "vat_pln": "number — B00 VAT in PLN",
    "total_cif_usd": "number — total CIF value in USD",
    "customs_rate_usd": "number — exchange rate PLN/USD used by customs",
    "statistical_value_pln": "number — statistical value in PLN",
    "sad_invoice_value_usd": "number — total invoice value in USD from SAD",
    "agent": "string — customs agent / declarant name",
    "importer_name": "string — importer company name",
    "importer_nip": "string — importer NIP/tax ID",
    "exporter_name": "string — exporter company name",
    "cn_code": "string — HS/CN tariff codes, comma-separated",
    "goods_description": "string — goods description",
    "a00_payment_method": "string — A00 payment method code (R=standard, G=deferred)",
    "b00_payment_method": "string — B00 payment method code (R=standard, G=Art.33a deferred)",
}

_SYSTEM_PROMPT = """You are a customs document data extractor. You extract structured data from Polish ZC429/SAD/PZC customs declaration documents.

CRITICAL RULES:
1. ONLY extract values that are EXPLICITLY printed in the document
2. NEVER calculate, derive, or estimate any values
3. Return null for any field you cannot find or are not confident about
4. Financial values must be extracted EXACTLY as printed — no rounding, no conversion
5. All monetary amounts are in the currency stated in the document (usually PLN)
6. Exchange rates must be extracted exactly as printed

Return a JSON object with these fields (use null for unknown):
{schema}

Return ONLY the JSON object, no other text."""


def parse_with_ai(
    file_path: str,
    *,
    fields_needed: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Extract customs fields from a PDF using an LLM.

    Args:
        file_path:     Path to the PDF file
        fields_needed: Optional list of specific fields to extract (optimization hint)

    Returns:
        Dict with extracted fields + _ai_meta, or None on failure.
    """
    from ..core.config import settings

    api_key = getattr(settings, "anthropic_api_key", None)
    if not api_key:
        log.warning("[ai_parser] ANTHROPIC_API_KEY not set — AI parsing unavailable")
        return None

    if not getattr(settings, "ai_parser_enabled", False):
        log.debug("[ai_parser] ai_parser_enabled=False — AI parsing disabled by config")
        return None

    # Extract text from PDF
    pdf_text = _extract_pdf_text(file_path)
    if not pdf_text:
        log.warning("[ai_parser] no text extracted from %s", file_path)
        return None

    # Build prompt
    schema_str = "\n".join(f'  "{k}": {v}' for k, v in _EXTRACTION_SCHEMA.items())
    system = _SYSTEM_PROMPT.format(schema=schema_str)

    focus_hint = ""
    if fields_needed:
        focus_hint = f"\n\nFocus especially on extracting these fields: {', '.join(fields_needed)}"

    user_msg = f"Extract customs data from this document:{focus_hint}\n\n---\n{pdf_text[:8000]}"

    # Call via AI Gateway (single authority — no direct Anthropic client here)
    try:
        from . import ai_gateway  # noqa: PLC0415

        t0 = time.monotonic()
        raw_text = ai_gateway.call(
            system=system,
            user=user_msg,
            task_type="customs_extraction",
            service_name="ai_customs_parser",
            object_id=Path(file_path).name,
            complexity="moderate",
            risk_level="medium",
            context_size=len(pdf_text),
            confidence_score=1.0,
            max_tokens=2000,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if raw_text is None:
            return None

        raw_text = raw_text.strip()

        # Parse JSON response
        import json
        # Handle markdown-wrapped JSON
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw_text)

        # Count fields
        fields_extracted = sum(1 for v in parsed.values() if v is not None)
        fields_null = sum(1 for v in parsed.values() if v is None)

        # Determine confidence
        if fields_extracted >= 12:
            confidence = "high"
        elif fields_extracted >= 6:
            confidence = "medium"
        else:
            confidence = "low"

        parsed["_ai_meta"] = {
            "confidence":        confidence,
            "fields_extracted":  fields_extracted,
            "fields_null":       fields_null,
            "extraction_time_ms": elapsed_ms,
        }

        log.info("[ai_parser] extracted %d fields (confidence=%s) in %dms from %s",
                 fields_extracted, confidence, elapsed_ms, Path(file_path).name)

        return parsed

    except Exception as e:
        log.error("[ai_parser] API call failed: %s", e)
        return None


def _extract_pdf_text(file_path: str) -> Optional[str]:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages[:10]:  # Cap at 10 pages
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        return "\n\n".join(text_parts) if text_parts else None

    except Exception as e:
        log.error("[ai_parser] PDF text extraction failed: %s", e)
        return None
