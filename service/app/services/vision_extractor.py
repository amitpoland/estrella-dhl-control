"""
vision_extractor.py — Image-only document CIF/AWB fallback via vision LLM.

Purpose
-------
When a DHL waybill / commercial invoice is an image-only (scanned) PDF, every
text-based extraction layer in the platform produces nothing and the customs
CIF collapses to UNKNOWN (see ``cif_resolver``). This module is the automatic
fallback that the rest of the pipeline was missing:

    image-only PDF  →  rasterize pages  →  Claude vision extraction
                    →  schema validation  →  authority-key write  →  CIF resolves

It does NOT replace the deterministic text parsers — it runs only *after* they
have failed AND the document is confirmed image-only (via
``document_text_quality.assess_pdf_text_quality``). It never books accounting,
never fabricates ``0.0``, and writes only the exact authority keys the
``cif_resolver`` ladder already consumes, merge-not-replace.

OCR honesty
-----------
There is no Tesseract / pdf2image binary installed on this host. The "OCR"
layer here is a vision LLM reading rasterized page images directly (PyMuPDF /
fitz renders the page to PNG; Claude vision reads the PNG). Provenance records
``extraction_method="vision_llm"`` truthfully — it does not claim a raster-OCR
step that did not happen.

Governance
----------
- All AI execution goes through ``ai_gateway.call_vision`` (single AI
  authority). No anthropic client is constructed here.
- Model escalation between the two attempts is expressed via complexity/
  confidence (moderate→complex), never by passing a model-name string.
- AI output is schema-validated before any write. Validation failure → no
  write, CIF stays UNKNOWN, gap is preserved.
- USD-only: a non-USD AWB custom value is never auto-converted to a USD
  authority key.
- Retry-safety: a per-source-file version signature (size+mtime) prevents the
  same document version from being re-extracted on every recheck.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────

MAX_RASTER_PAGES: int = 4      # customs values live on the first pages
RASTER_DPI:       int = 200    # legible enough for small printed customs values
# A vision-extracted authority value is written only at or above this
# confidence. Below it, the value is recorded in provenance for operator review
# but NOT promoted to an authority key (CIF stays UNKNOWN with a gap).
MIN_WRITE_CONFIDENCE: float = 0.5
# Tolerance for CIF vs (FOB+Freight+Insurance) component reconciliation.
CIF_COMPONENT_VARIANCE_TOL: float = 0.02  # 2%
# Reject any monetary amount above this — a parse artefact, not a real value.
MAX_PLAUSIBLE_AMOUNT: float = 1e9

# The strict field set the model is asked to return.
_SCHEMA_FIELDS = (
    "awb_number",
    "custom_val_amount",
    "custom_val_currency",
    "invoice_no",
    "fob_usd",
    "freight_usd",
    "insurance_usd",
    "cif_usd",
    "supplier",
    "confidence",
    "source_page",
    "source_text_or_visual_reason",
)

_NUMERIC_MONEY_FIELDS = ("custom_val_amount", "fob_usd", "freight_usd", "insurance_usd", "cif_usd")

# Doc kinds
DOC_WAYBILL = "dhl_waybill"
DOC_INVOICE = "commercial_invoice"


# ── Rasterization ─────────────────────────────────────────────────────────────

def rasterize_pdf(
    pdf_path: str,
    max_pages: int = MAX_RASTER_PAGES,
    dpi: int = RASTER_DPI,
) -> List[Tuple[int, bytes]]:
    """Render the leading pages of ``pdf_path`` to PNG bytes using PyMuPDF.

    Returns a list of ``(page_index, png_bytes)`` for up to ``max_pages`` pages.
    Returns ``[]`` (never raises) when fitz is unavailable or the PDF cannot be
    opened/rendered — the caller treats an empty list as "cannot rasterize".
    """
    try:
        import fitz  # PyMuPDF  # noqa: PLC0415
    except Exception as exc:
        log.warning("[vision_extractor] PyMuPDF (fitz) unavailable: %s", exc)
        return []

    out: List[Tuple[int, bytes]] = []
    doc = None
    try:
        doc = fitz.open(pdf_path)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        n = min(len(doc), max_pages)
        for i in range(n):
            try:
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                out.append((i, pix.tobytes("png")))
            except Exception as exc:
                log.info("[vision_extractor] page %d render failed for %s: %s", i, pdf_path, exc)
                continue
    except Exception as exc:
        log.warning("[vision_extractor] cannot open %s for rasterization: %s", pdf_path, exc)
        return []
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass
    return out


# ── Prompt construction ───────────────────────────────────────────────────────

def _build_prompt(doc_kind: str) -> Tuple[str, str]:
    """Return (system, user) prompts requesting strict JSON for ``doc_kind``."""
    schema_desc = (
        "{\n"
        '  "awb_number": string|null,                 // air waybill number if visible\n'
        '  "custom_val_amount": number|null,          // declared customs value AMOUNT only\n'
        '  "custom_val_currency": string|null,        // ISO code of the customs value, e.g. "USD"\n'
        '  "invoice_no": string|null,\n'
        '  "fob_usd": number|null,                    // goods value in USD if shown\n'
        '  "freight_usd": number|null,\n'
        '  "insurance_usd": number|null,\n'
        '  "cif_usd": number|null,                    // CIF total in USD if shown\n'
        '  "supplier": string|null,\n'
        '  "confidence": number,                      // 0..1, your confidence in these values\n'
        '  "source_page": number|null,                // 1-based page where you read the value\n'
        '  "source_text_or_visual_reason": string     // the exact text/label you read it from\n'
        "}"
    )
    kind_hint = {
        DOC_WAYBILL: (
            "This is a DHL / air waybill scan. The most important field is the "
            "declared customs value (often labelled 'Customs Value', 'Value for "
            "Customs', 'Declared Value', or 'Custom Val') and its currency."
        ),
        DOC_INVOICE: (
            "This is a commercial invoice scan. The most important fields are the "
            "goods value (FOB), freight, insurance, and the CIF total, all in the "
            "invoice currency. Report amounts in USD only if the invoice is in USD. "
            "ALWAYS set 'custom_val_currency' to the invoice currency you can read "
            "(e.g. 'USD', 'EUR'); if you cannot read the currency, use null."
        ),
    }.get(doc_kind, "This is a shipment customs document scan.")

    system = (
        "You are a precise customs document extraction engine. You read scanned "
        "shipment documents and return ONLY structured JSON. You never guess: if "
        "a value is not legibly present in the image, return null for it. You "
        "never invent a customs value of 0 — absence is null, not zero. You only "
        "report a currency you can actually see on the document."
    )
    user = (
        f"{kind_hint}\n\n"
        "Extract the following fields and return ONLY a single JSON object "
        "(no prose, no markdown fences) matching exactly this schema:\n\n"
        f"{schema_desc}\n\n"
        "Rules:\n"
        "- Numbers must be plain numerics (no currency symbols, no thousands "
        "separators).\n"
        "- Always report 'custom_val_currency' as the ISO code you actually see "
        "for the primary amount (e.g. 'USD', 'EUR'); use null only if no currency "
        "is legible. Never assume USD.\n"
        "- If a field is not visible, use null. Do NOT use 0 to mean 'unknown'.\n"
        "- 'confidence' reflects how sure you are that the amounts are correct.\n"
        "- 'source_text_or_visual_reason' must quote the label/text you read the "
        "primary value from, so a human can verify it."
    )
    return system, user


def _parse_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from a model response. Never raises."""
    if not raw:
        return None
    text = raw.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # Direct parse first.
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Fall back to the first {...} span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


# ── Validation ────────────────────────────────────────────────────────────────

def _coerce_money(value: Any) -> Optional[float]:
    """Coerce a model-returned amount to a positive plausible float, else None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("$", "").strip()
            if not cleaned:
                return None
            v = float(cleaned)
        else:
            v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0 or v > MAX_PLAUSIBLE_AMOUNT:
        return None
    return round(v, 2)


def validate_extraction(
    data: Dict[str, Any], doc_kind: str
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate + normalize a parsed vision extraction.

    Returns ``(clean_fields, errors)``. ``clean_fields`` contains only the
    fields that survived validation (coerced numerics, uppercased currency,
    derived CIF where justified). ``errors`` lists every rejection/variance so
    provenance can explain a partial or failed extraction. A non-empty
    ``errors`` list does NOT necessarily mean "unusable" — the caller decides
    based on which authority field it needs and whether that field is clean.
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        return {}, ["extraction is not a JSON object"]

    clean: Dict[str, Any] = {}

    # Numerics
    for f in _NUMERIC_MONEY_FIELDS:
        if f in data and data[f] is not None:
            coerced = _coerce_money(data[f])
            if coerced is None:
                errors.append(f"{f}={data[f]!r} rejected (non-positive / unparseable / implausible)")
            else:
                clean[f] = coerced

    # Currency — uppercase, keep only short alpha codes
    cur = data.get("custom_val_currency")
    if cur is not None:
        cur_s = str(cur).strip().upper()
        if cur_s and re.fullmatch(r"[A-Z]{2,5}", cur_s):
            clean["custom_val_currency"] = cur_s
        elif cur_s:
            errors.append(f"custom_val_currency={cur!r} rejected (not an ISO-like code)")

    # Pass-through string identifiers
    for f in ("awb_number", "invoice_no", "supplier", "source_text_or_visual_reason"):
        v = data.get(f)
        if v is not None and str(v).strip():
            clean[f] = str(v).strip()

    # source_page → int if sane
    sp = data.get("source_page")
    if sp is not None:
        try:
            spi = int(sp)
            if 1 <= spi <= 50:
                clean["source_page"] = spi
        except (TypeError, ValueError):
            pass

    # Confidence — clamp to [0,1]; default 0.0 when absent/unparseable
    conf = data.get("confidence")
    try:
        conff = float(conf)
        clean["confidence"] = max(0.0, min(1.0, conff))
    except (TypeError, ValueError):
        clean["confidence"] = 0.0
        errors.append("confidence missing/unparseable — defaulted to 0.0")

    # CIF reconciliation: derive when all components present and CIF absent;
    # check variance when both present.
    fob = clean.get("fob_usd")
    fr = clean.get("freight_usd")
    ins = clean.get("insurance_usd")
    cif = clean.get("cif_usd")
    if fob is not None and fr is not None and ins is not None:
        computed = round(fob + fr + ins, 2)
        if cif is None:
            clean["cif_usd"] = computed
            clean["cif_derived"] = True
        else:
            denom = cif if cif else 1.0
            variance = abs(cif - computed) / denom
            if variance > CIF_COMPONENT_VARIANCE_TOL:
                errors.append(
                    f"CIF {cif} vs FOB+Freight+Insurance {computed} variance "
                    f"{variance:.1%} exceeds {CIF_COMPONENT_VARIANCE_TOL:.0%}"
                )

    return clean, errors


# ── Single-document vision extraction ─────────────────────────────────────────

def _png_to_image_block(png_bytes: bytes) -> Dict[str, str]:
    return {
        "media_type": "image/png",
        "data": base64.b64encode(png_bytes).decode("ascii"),
    }


def extract_fields_via_vision(
    pdf_path: str,
    doc_kind: str,
    object_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the two-attempt vision extraction over one PDF.

    Attempt 1 (primary): moderate complexity / high confidence → cheaper tier.
    Attempt 2 (secondary fallback): complex / low confidence → escalated tier.
    Escalation is expressed via complexity/confidence so the gateway selects the
    stronger model — no model-name string is passed (governance).

    Returns a provenance dict (never raises)::

        {
          "ok":                  bool,
          "extraction_method":   "vision_llm" | "vision_llm_fallback" | "failed",
          "model_attempt":       "primary" | "secondary" | None,
          "extraction_confidence": float,
          "fields":              { validated clean fields },
          "source_file":         str (basename),
          "source_page":         int | None,
          "source_reason":       str | None,
          "failed_layers":       [str, ...],
          "validation_errors":   [str, ...],
          "pages_rasterized":    int,
        }
    """
    from . import ai_gateway  # noqa: PLC0415

    prov: Dict[str, Any] = {
        "ok": False,
        "extraction_method": "failed",
        "model_attempt": None,
        "extraction_confidence": 0.0,
        "fields": {},
        "source_file": os.path.basename(pdf_path) if pdf_path else None,
        "source_page": None,
        "source_reason": None,
        "failed_layers": [],
        "validation_errors": [],
        "pages_rasterized": 0,
    }

    if not ai_gateway.is_available():
        prov["failed_layers"].append("ai_gateway_unavailable")
        return prov

    pages = rasterize_pdf(pdf_path)
    prov["pages_rasterized"] = len(pages)
    if not pages:
        prov["failed_layers"].append("rasterize_failed")
        return prov

    images = [_png_to_image_block(png) for _, png in pages]
    system, user = _build_prompt(doc_kind)

    attempts = [
        ("primary", "vision_llm", {"complexity": "moderate", "confidence_score": 0.9}),
        ("secondary", "vision_llm_fallback", {"complexity": "complex", "confidence_score": 0.2}),
    ]

    for attempt_name, method_label, knobs in attempts:
        raw = ai_gateway.call_vision(
            system=system,
            user=user,
            images=images,
            task_type="customs_vision_extraction",
            service_name="vision_extractor",
            object_id=object_id,
            risk_level="high",
            max_tokens=1200,
            **knobs,
        )
        if raw is None:
            prov["failed_layers"].append(f"{attempt_name}_no_response")
            continue

        parsed = _parse_json(raw)
        if parsed is None:
            prov["failed_layers"].append(f"{attempt_name}_unparseable_json")
            continue

        clean, errs = validate_extraction(parsed, doc_kind)
        prov["validation_errors"] = errs

        # Did we get any usable authority-relevant value at all?
        has_value = any(
            clean.get(k) is not None
            for k in ("cif_usd", "fob_usd", "custom_val_amount")
        )
        if not has_value:
            prov["failed_layers"].append(f"{attempt_name}_no_usable_value")
            continue

        prov["ok"] = True
        prov["extraction_method"] = method_label
        prov["model_attempt"] = attempt_name
        prov["extraction_confidence"] = float(clean.get("confidence", 0.0))
        prov["fields"] = clean
        prov["source_page"] = clean.get("source_page")
        prov["source_reason"] = clean.get("source_text_or_visual_reason")
        return prov

    return prov


# ── Orchestrator: image-only CIF fallback ─────────────────────────────────────

def _file_signature(path: Path) -> str:
    """Return a cheap version signature (size+mtime) for retry-safety."""
    try:
        st = path.stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except Exception:
        return "missing"


def _merge_awb_custom_val(audit: Dict[str, Any], amount: float, currency: str,
                          prov: Dict[str, Any]) -> None:
    """Write an AWB custom value (USD) into ``awb_customs`` merge-not-replace."""
    existing = dict(audit.get("awb_customs") or {})
    existing["value_usd"] = amount
    existing["currency"] = currency
    existing["gap"] = False
    existing["source"] = "vision_llm"
    existing["vision_source_page"] = prov.get("source_page")
    audit["awb_customs"] = existing


def _merge_precheck_invoice(audit: Dict[str, Any], fields: Dict[str, Any]) -> None:
    """Write invoice CIF/FOB into ``dhl_precheck`` merge-not-replace."""
    existing = dict(audit.get("dhl_precheck") or {})
    cif = fields.get("cif_usd")
    fob = fields.get("fob_usd")
    if cif is not None:
        existing["invoice_cif_total_usd"] = cif
    if fob is not None:
        existing["fob_total_usd"] = fob
    existing["vision_extracted"] = True
    existing["cif_source"] = "vision_llm"
    audit["dhl_precheck"] = existing


def run_image_only_cif_fallback(
    output_dir: Any,
    batch_id: str,
) -> Dict[str, Any]:
    """Self-contained image-only CIF fallback.

    Re-reads the audit, and only acts when CIF is still UNKNOWN. Inspects the
    AWB and invoice source PDFs for image-only quality, runs vision extraction
    on image-only ones, and on a clean USD result writes the exact authority
    keys the ``cif_resolver`` ladder consumes (merge-not-replace), then records
    a ``vision_extraction`` provenance block and writes the audit atomically.

    Called LAST from both the intake precheck and the dashboard recheck, after
    those have done their own writes — so it always reads a fully-written audit
    and never clobbers a concurrent write of its own.

    Returns a summary dict (never raises). Safe to call when nothing is needed —
    it no-ops and reports why.
    """
    from .cif_resolver import resolve_cif, CIF_UNKNOWN  # noqa: PLC0415
    from ..utils.io import write_json_atomic, read_json  # noqa: PLC0415
    from . import document_text_quality as dtq  # noqa: PLC0415

    out = Path(output_dir)
    audit_path = out / "audit.json"
    summary: Dict[str, Any] = {
        "batch_id": batch_id,
        "ran": False,
        "wrote": False,
        "reason": "",
        "documents": [],
    }

    try:
        audit = read_json(audit_path)
    except Exception as exc:
        summary["reason"] = f"audit unreadable: {exc}"
        return summary
    if not isinstance(audit, dict):
        summary["reason"] = "audit not a dict"
        return summary

    # Only act when CIF is genuinely UNKNOWN — never override a resolved/declared value.
    cif_state = resolve_cif(audit).get("cif_state")
    if cif_state != CIF_UNKNOWN:
        summary["reason"] = f"cif_state={cif_state} — no fallback needed"
        return summary

    # Candidate documents: AWB first (carrier custom val), then invoices.
    candidates: List[Tuple[str, Path]] = []
    awb_dir = out / "source" / "awb"
    inv_dir = out / "source" / "invoices"
    if awb_dir.is_dir():
        for p in sorted(awb_dir.glob("*.pdf")):
            candidates.append((DOC_WAYBILL, p))
    if inv_dir.is_dir():
        for p in sorted(inv_dir.glob("*.pdf")):
            candidates.append((DOC_INVOICE, p))

    if not candidates:
        summary["reason"] = "no AWB/invoice source PDFs present"
        return summary

    # Retry-safety ledger: which (file, signature) we have already attempted.
    prior = audit.get("vision_extraction") or {}
    prior_attempts: Dict[str, str] = dict(prior.get("attempted_signatures") or {})

    expected_labels = ["customs", "value", "invoice", "cif", "fob", "declared"]

    summary["ran"] = True
    wrote = False
    doc_records: List[Dict[str, Any]] = []
    attempted_now = dict(prior_attempts)

    for doc_kind, pdf in candidates:
        sig = _file_signature(pdf)
        key = pdf.name
        rec: Dict[str, Any] = {
            "file": pdf.name,
            "doc_kind": doc_kind,
            "signature": sig,
        }

        # Retry-safety: skip a document version we already attempted.
        if prior_attempts.get(key) == sig:
            rec["skipped"] = "already_attempted_this_version"
            doc_records.append(rec)
            continue

        quality = dtq.assess_pdf_text_quality(str(pdf), expected_labels=expected_labels)
        should, reason = dtq.needs_vision_fallback(quality, value_missing=True)
        rec["image_only"] = quality.get("image_only_pdf")
        rec["extracted_text_chars"] = quality.get("extracted_text_chars")
        rec["decision"] = reason
        if not should:
            rec["skipped"] = "not_image_only"
            attempted_now[key] = sig  # record so we don't re-assess every recheck
            doc_records.append(rec)
            continue

        prov = extract_fields_via_vision(str(pdf), doc_kind, object_id=batch_id)
        attempted_now[key] = sig  # one attempt per version, success or fail
        rec["extraction"] = {
            "ok": prov["ok"],
            "method": prov["extraction_method"],
            "model_attempt": prov["model_attempt"],
            "confidence": prov["extraction_confidence"],
            "failed_layers": prov["failed_layers"],
            "validation_errors": prov["validation_errors"],
            "source_page": prov["source_page"],
            "source_reason": prov["source_reason"],
        }

        if not prov["ok"]:
            doc_records.append(rec)
            continue

        fields = prov["fields"]
        conf = prov["extraction_confidence"]
        if conf < MIN_WRITE_CONFIDENCE:
            rec["write"] = f"withheld_low_confidence({conf:.2f}<{MIN_WRITE_CONFIDENCE})"
            doc_records.append(rec)
            continue

        if doc_kind == DOC_WAYBILL:
            amount = fields.get("custom_val_amount")
            cur = (fields.get("custom_val_currency") or "").upper()
            if amount is None:
                rec["write"] = "no_custom_val_amount"
            elif cur != "USD":
                # USD-only, and the currency must be EXPLICITLY USD. A blank /
                # unknown currency is never assumed to be USD — unknown stays
                # unknown, we never relabel an unidentified amount as USD authority.
                rec["write"] = (
                    f"withheld_non_usd({cur})" if cur else "withheld_unknown_currency"
                )
            else:
                _merge_awb_custom_val(audit, amount, "USD", prov)
                rec["write"] = f"awb_customs.value_usd={amount}"
                wrote = True
        else:  # DOC_INVOICE
            # fob_usd / cif_usd are USD-named, but a non-compliant model may put a
            # foreign amount in them. The currency must be EXPLICITLY USD to write:
            # a legibly non-USD currency, AND a blank / unreadable one, both withhold
            # every USD-named write rather than relabel a possibly-foreign amount as
            # USD authority (a wrong CIF that looks "resolved" is worse than a
            # preserved UNKNOWN gap). Same USD-only discipline as the waybill path.
            doc_cur = (fields.get("custom_val_currency") or "").upper()
            if doc_cur != "USD":
                rec["write"] = (
                    f"withheld_non_usd_invoice({doc_cur})" if doc_cur
                    else "withheld_unknown_currency_invoice"
                )
            elif fields.get("cif_usd") is not None or fields.get("fob_usd") is not None:
                _merge_precheck_invoice(audit, fields)
                wrote = True
                rec["write"] = (
                    f"dhl_precheck.invoice_cif_total_usd={fields.get('cif_usd')} "
                    f"fob_total_usd={fields.get('fob_usd')}"
                )
            else:
                rec["write"] = "no_cif_or_fob"

        doc_records.append(rec)
        # Stop once a write resolves CIF — re-check resolver against the in-memory audit.
        if wrote and resolve_cif(audit).get("cif_state") != CIF_UNKNOWN:
            break

    # Record provenance (merge-not-replace on the vision_extraction block).
    vision_block = dict(audit.get("vision_extraction") or {})
    runs = list(vision_block.get("runs") or [])
    runs.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "batch_id": batch_id,
        "documents": doc_records,
        "wrote": wrote,
    })
    vision_block["runs"] = runs[-10:]  # cap history
    vision_block["attempted_signatures"] = attempted_now
    # Reflect the ACTUAL outcome of the last document that ran a vision attempt.
    # A no-op run (everything skipped / already-attempted) records None, not a
    # false "vision_llm" provenance that implies a model was called.
    _methods = [
        d["extraction"]["method"]
        for d in doc_records
        if isinstance(d.get("extraction"), dict) and d["extraction"].get("method")
    ]
    vision_block["last_method"] = _methods[-1] if _methods else None
    audit["vision_extraction"] = vision_block

    try:
        write_json_atomic(audit_path, audit)
    except Exception as exc:
        summary["reason"] = f"audit write failed: {exc}"
        summary["documents"] = doc_records
        return summary

    summary["wrote"] = wrote
    summary["documents"] = doc_records
    summary["reason"] = "wrote authority key(s)" if wrote else "ran, no usable value written"
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# ADVISORY invoice line-item extraction (image-only invoices) — PZ unblock layer
# ══════════════════════════════════════════════════════════════════════════════
#
# Separate, isolated capability from the CIF fallback above. An image-only
# commercial invoice that defeats the text parser collapses CIF to UNKNOWN
# *and* produces no FOB / line items / supplier — so the PZ engine
# (process_batch) cannot compute a goods receipt at all. The CIF fallback
# resolves the customs value; this layer recovers the *purchase-accounting*
# inputs the PZ engine needs.
#
# Authority isolation (Lesson F) — this writes ONLY the advisory
# ``audit["vision_invoice"]`` block. It is:
#   - operator_confirmed=false on every machine write (sticky: once an operator
#     confirms the block, this layer never overwrites it);
#   - NEVER consumed by cif_resolver.resolve_cif (the CIF ladder does not read
#     vision_invoice — pinned by test_vision_invoice_negative_scope);
#   - NEVER written into invoice_totals / rows / customs_declaration (engine
#     authority is untouched — the operator-confirmed → process_batch injection
#     is a separate, gated PR).
# The frontend reflects truth; it does not produce it. This block is a
# *proposal* awaiting operator confirmation, not booked accounting authority.


def _build_invoice_lineitem_prompt() -> Tuple[str, str]:
    """Return (system, user) prompts requesting a structured invoice summary.

    Distinct from ``_build_prompt`` (the CIF/AWB extractor). This asks for the
    purchase-accounting inputs — supplier, FOB, and per-line goods — that the PZ
    engine needs, and is explicit that itemization may be impossible.
    """
    schema_desc = (
        "{\n"
        '  "supplier": string|null,                    // seller / exporter name\n'
        '  "invoice_no": string|null,\n'
        '  "currency": string|null,                    // ISO code you actually see, e.g. "USD"\n'
        '  "fob_usd": number|null,                     // total goods value, USD only\n'
        '  "itemization_available": boolean,           // true ONLY if you can read discrete line rows\n'
        '  "line_items": [                             // [] when itemization_available is false\n'
        "    {\n"
        '      "description": string,                  // the goods description text\n'
        '      "hsn": string|null,                     // HS / customs code if shown\n'
        '      "quantity": number|null,\n'
        '      "unit_price": number|null,\n'
        '      "total": number|null,\n'
        '      "gross_weight_g": number|null,          // grams\n'
        '      "net_weight_g": number|null             // grams\n'
        "    }\n"
        "  ],\n"
        '  "confidence": number,                       // 0..1 in the values above\n'
        '  "source_page": number|null,\n'
        '  "source_reason": string                     // the label/heading you read the table from\n'
        "}"
    )
    system = (
        "You are a precise commercial-invoice extraction engine. You read scanned "
        "invoices and return ONLY structured JSON. You never guess: a value not "
        "legibly present is null, never 0. If you cannot read discrete line-item "
        "rows, set itemization_available=false and return line_items=[] — do NOT "
        "fabricate rows. Report a currency only if you can actually see it; never "
        "assume USD."
    )
    user = (
        "This is a commercial invoice scan. Extract the supplier, invoice number, "
        "currency, total goods value (FOB), and every goods line you can read.\n\n"
        "Return ONLY a single JSON object (no prose, no markdown fences) matching "
        f"exactly this schema:\n\n{schema_desc}\n\n"
        "Rules:\n"
        "- Numbers must be plain numerics (no symbols, no thousands separators).\n"
        "- Report 'currency' as the ISO code you actually see; null if not legible. "
        "Never assume USD. Only populate 'fob_usd' if the invoice is in USD.\n"
        "- If a field is not visible, use null. Do NOT use 0 to mean 'unknown'.\n"
        "- If the line-item table is unreadable, set itemization_available=false and "
        "line_items=[]. A partial but honest result beats invented rows.\n"
        "- 'source_reason' must quote the table heading / label you read from."
    )
    return system, user


def _validate_line_item(item: Any) -> Optional[Dict[str, Any]]:
    """Validate one model-returned line item. Returns a clean dict or None.

    A line item is kept only if it carries a description AND at least one
    numeric. Numerics reuse ``_coerce_money`` (positive, plausible, rounded).
    """
    if not isinstance(item, dict):
        return None
    clean: Dict[str, Any] = {}
    desc = item.get("description")
    if desc is not None and str(desc).strip():
        clean["description"] = str(desc).strip()
    hsn = item.get("hsn")
    if hsn is not None and str(hsn).strip():
        clean["hsn"] = str(hsn).strip()
    for src, dst in (
        ("quantity", "quantity"),
        ("unit_price", "unit_price_usd"),
        ("total", "total_usd"),
        ("gross_weight_g", "gross_weight_g"),
        ("net_weight_g", "net_weight_g"),
    ):
        v = _coerce_money(item.get(src))
        if v is not None:
            clean[dst] = v
    if "description" not in clean:
        return None
    has_number = any(k in clean for k in ("quantity", "unit_price_usd", "total_usd"))
    if not has_number:
        return None
    return clean


def validate_invoice_extraction(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate + normalize a parsed invoice line-item extraction.

    Returns ``(clean, errors)``. ``clean`` always carries ``line_items`` (a
    possibly-empty list) and ``itemization_unavailable`` (True when no usable
    rows survived). Never raises.
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        return {"line_items": [], "itemization_unavailable": True, "confidence": 0.0}, [
            "extraction is not a JSON object"
        ]

    clean: Dict[str, Any] = {}

    for f in ("supplier", "invoice_no", "source_reason"):
        v = data.get(f)
        if v is not None and str(v).strip():
            clean[f] = str(v).strip()

    cur = data.get("currency")
    if cur is not None:
        cur_s = str(cur).strip().upper()
        if cur_s and re.fullmatch(r"[A-Z]{2,5}", cur_s):
            clean["currency"] = cur_s
        elif cur_s:
            errors.append(f"currency={cur!r} rejected (not an ISO-like code)")

    fob = _coerce_money(data.get("fob_usd"))
    if fob is not None:
        clean["fob_usd"] = fob

    raw_items = data.get("line_items")
    items: List[Dict[str, Any]] = []
    if isinstance(raw_items, list):
        for it in raw_items:
            ci = _validate_line_item(it)
            if ci is not None:
                items.append(ci)
            elif it:
                errors.append("dropped an unparseable / numberless line item")
    clean["line_items"] = items
    # itemization_unavailable reflects the ACTUAL persisted state: do we hold
    # any usable rows? (Independent of what the model claimed.)
    clean["itemization_unavailable"] = len(items) == 0

    sp = data.get("source_page")
    if sp is not None:
        try:
            spi = int(sp)
            if 1 <= spi <= 50:
                clean["source_page"] = spi
        except (TypeError, ValueError):
            pass

    conf = data.get("confidence")
    try:
        clean["confidence"] = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        clean["confidence"] = 0.0
        errors.append("confidence missing/unparseable — defaulted to 0.0")

    return clean, errors


def extract_invoice_lineitems_via_vision(
    pdf_path: str,
    object_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Two-attempt vision extraction of an invoice's structured summary.

    Same model-escalation discipline as ``extract_fields_via_vision`` (governance
    via complexity/confidence knobs, never a model-name string). Returns a
    provenance dict (never raises) whose ``fields`` carry the validated invoice
    summary on success.
    """
    from . import ai_gateway  # noqa: PLC0415

    prov: Dict[str, Any] = {
        "ok": False,
        "extraction_method": "failed",
        "model_attempt": None,
        "extraction_confidence": 0.0,
        "fields": {},
        "source_file": os.path.basename(pdf_path) if pdf_path else None,
        "source_page": None,
        "source_reason": None,
        "failed_layers": [],
        "validation_errors": [],
        "pages_rasterized": 0,
    }

    if not ai_gateway.is_available():
        prov["failed_layers"].append("ai_gateway_unavailable")
        return prov

    pages = rasterize_pdf(pdf_path)
    prov["pages_rasterized"] = len(pages)
    if not pages:
        prov["failed_layers"].append("rasterize_failed")
        return prov

    images = [_png_to_image_block(png) for _, png in pages]
    system, user = _build_invoice_lineitem_prompt()

    attempts = [
        ("primary", "vision_llm", {"complexity": "moderate", "confidence_score": 0.9}),
        ("secondary", "vision_llm_fallback", {"complexity": "complex", "confidence_score": 0.2}),
    ]

    for attempt_name, method_label, knobs in attempts:
        raw = ai_gateway.call_vision(
            system=system,
            user=user,
            images=images,
            task_type="invoice_lineitem_extraction",
            service_name="vision_extractor",
            object_id=object_id,
            risk_level="high",
            max_tokens=2400,
            **knobs,
        )
        if raw is None:
            prov["failed_layers"].append(f"{attempt_name}_no_response")
            continue

        parsed = _parse_json(raw)
        if parsed is None:
            prov["failed_layers"].append(f"{attempt_name}_unparseable_json")
            continue

        clean, errs = validate_invoice_extraction(parsed)
        prov["validation_errors"] = errs

        # Usable if we recovered ANY purchase-accounting input — line items,
        # an FOB total, or at least a supplier identity.
        has_value = bool(clean.get("line_items")) or (
            clean.get("fob_usd") is not None
        ) or bool(clean.get("supplier"))
        if not has_value:
            prov["failed_layers"].append(f"{attempt_name}_no_usable_value")
            continue

        prov["ok"] = True
        prov["extraction_method"] = method_label
        prov["model_attempt"] = attempt_name
        prov["extraction_confidence"] = float(clean.get("confidence", 0.0))
        prov["fields"] = clean
        prov["source_page"] = clean.get("source_page")
        prov["source_reason"] = clean.get("source_reason")
        return prov

    return prov


def _merge_vision_invoice(
    audit: Dict[str, Any], clean: Dict[str, Any], prov: Dict[str, Any]
) -> bool:
    """Write the advisory ``vision_invoice`` block, sticky + field-merge.

    Returns True when the block was written, False when withheld because the
    operator already confirmed it (sticky — a confirmed proposal is authority
    the operator owns; the machine never silently overwrites it).
    """
    existing = dict(audit.get("vision_invoice") or {})
    if existing.get("operator_confirmed") is True:
        return False  # sticky: never overwrite an operator-confirmed proposal

    merged = dict(existing)
    merged["operator_confirmed"] = False
    merged["status"] = "proposed"  # lifecycle: proposed → confirmed → injected
    merged["source"] = "vision_llm"
    merged["extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    merged["confidence"] = float(
        prov.get("extraction_confidence", clean.get("confidence", 0.0))
    )
    if prov.get("source_file"):
        merged["source_file"] = prov.get("source_file")
    if clean.get("source_page") is not None:
        merged["source_page"] = clean["source_page"]

    # Scalar field-merge: a null in this run keeps the prior value (don't lose a
    # supplier we read last time just because this page didn't show it).
    for f in ("supplier", "invoice_no", "currency"):
        if clean.get(f) is not None:
            merged[f] = clean[f]

    # USD-only discipline (mirrors the CIF fallback): fob_usd is a USD figure by
    # contract. Only accept it when the invoice currency this run reads as USD.
    # An unknown / non-USD currency is NOT USD — withhold the value rather than
    # mislabel a foreign amount as dollars. A prior USD fob is left untouched.
    _inv_currency = (clean.get("currency") or merged.get("currency") or "").upper()
    if clean.get("fob_usd") is not None and _inv_currency == "USD":
        merged["fob_usd"] = clean["fob_usd"]

    # Line items: overwrite only when this run produced rows; otherwise keep any
    # rows already held. itemization_unavailable then reflects the FINAL state.
    new_items = clean.get("line_items") or []
    if new_items:
        merged["line_items"] = new_items
    else:
        merged.setdefault("line_items", [])
    merged["itemization_unavailable"] = len(merged.get("line_items") or []) == 0

    merged["provenance"] = {
        "method": prov.get("extraction_method"),
        "model_attempt": prov.get("model_attempt"),
        "source_reason": prov.get("source_reason"),
        "validation_errors": prov.get("validation_errors"),
    }
    audit["vision_invoice"] = merged
    return True


def run_image_only_invoice_extraction(
    output_dir: Any,
    batch_id: str,
) -> Dict[str, Any]:
    """Advisory image-only invoice recovery for the PZ purchase-accounting layer.

    Re-reads the audit and acts ONLY when:
      - the operator has NOT already confirmed a vision_invoice proposal, AND
      - the engine has NOT already parsed real invoice line items (a populated
        ``rows`` + a positive ``invoice_totals.total_fob_usd``).
    For each image-only invoice PDF it runs vision extraction and writes the
    advisory ``vision_invoice`` block (merge-not-replace, sticky). It never
    touches CIF authority keys, invoice_totals, rows, or customs_declaration.

    Called LAST from intake + recheck (after the CIF fallback). Returns a
    summary dict (never raises); safe to call when nothing is needed.
    """
    from ..utils.io import write_json_atomic, read_json  # noqa: PLC0415
    from . import document_text_quality as dtq  # noqa: PLC0415

    out = Path(output_dir)
    audit_path = out / "audit.json"
    summary: Dict[str, Any] = {
        "batch_id": batch_id,
        "ran": False,
        "wrote": False,
        "reason": "",
        "documents": [],
    }

    try:
        audit = read_json(audit_path)
    except Exception as exc:
        summary["reason"] = f"audit unreadable: {exc}"
        return summary
    if not isinstance(audit, dict):
        summary["reason"] = "audit not a dict"
        return summary

    vi = audit.get("vision_invoice") or {}
    if vi.get("operator_confirmed") is True:
        summary["reason"] = "vision_invoice operator_confirmed — not re-extracting"
        return summary

    # Need check — skip when the engine already produced real purchase-accounting
    # line items. This layer exists only for the image-only failure case.
    # NB: an absent/None rows AND a zero/None total_fob_usd both mean "no parse" —
    # _coerce_money rejects 0 (returns None), so a declared-zero total never reads
    # as a successful engine parse. Only a populated rows list together with a
    # strictly-positive FOB total counts as "engine already parsed".
    rows = audit.get("rows")
    it = audit.get("invoice_totals") or {}
    engine_parsed = (
        isinstance(rows, list)
        and len(rows) > 0
        and _coerce_money(it.get("total_fob_usd")) is not None
    )
    if engine_parsed:
        summary["reason"] = "engine already parsed invoice line items — advisory extraction not needed"
        return summary

    inv_dir = out / "source" / "invoices"
    candidates = sorted(inv_dir.glob("*.pdf")) if inv_dir.is_dir() else []
    if not candidates:
        summary["reason"] = "no invoice source PDFs present"
        return summary

    prior_sigs: Dict[str, str] = dict(vi.get("attempted_signatures") or {})
    expected_labels = ["description", "qty", "quantity", "amount", "total", "hsn", "pcs"]

    summary["ran"] = True
    wrote = False
    doc_records: List[Dict[str, Any]] = []
    attempted_now = dict(prior_sigs)

    for pdf in candidates:
        sig = _file_signature(pdf)
        key = pdf.name
        rec: Dict[str, Any] = {"file": pdf.name, "signature": sig}

        if prior_sigs.get(key) == sig:
            rec["skipped"] = "already_attempted_this_version"
            doc_records.append(rec)
            continue

        quality = dtq.assess_pdf_text_quality(str(pdf), expected_labels=expected_labels)
        should, reason = dtq.needs_vision_fallback(quality, value_missing=True)
        rec["image_only"] = quality.get("image_only_pdf")
        rec["extracted_text_chars"] = quality.get("extracted_text_chars")
        rec["decision"] = reason
        if not should:
            rec["skipped"] = "not_image_only"
            attempted_now[key] = sig
            doc_records.append(rec)
            continue

        prov = extract_invoice_lineitems_via_vision(str(pdf), object_id=batch_id)
        attempted_now[key] = sig
        rec["extraction"] = {
            "ok": prov["ok"],
            "method": prov["extraction_method"],
            "model_attempt": prov["model_attempt"],
            "confidence": prov["extraction_confidence"],
            "failed_layers": prov["failed_layers"],
            "validation_errors": prov["validation_errors"],
            "source_page": prov["source_page"],
            "source_reason": prov["source_reason"],
        }

        if not prov["ok"]:
            doc_records.append(rec)
            continue

        conf = prov["extraction_confidence"]
        if conf < MIN_WRITE_CONFIDENCE:
            rec["write"] = f"withheld_low_confidence({conf:.2f}<{MIN_WRITE_CONFIDENCE})"
            doc_records.append(rec)
            continue

        did = _merge_vision_invoice(audit, prov["fields"], prov)
        if did:
            wrote = True
            n_items = len(prov["fields"].get("line_items") or [])
            rec["write"] = (
                f"vision_invoice updated (line_items={n_items}, "
                f"fob_usd={prov['fields'].get('fob_usd')}, operator_confirmed=false)"
            )
        else:
            rec["write"] = "withheld_operator_confirmed"
        doc_records.append(rec)
        if wrote:
            break  # one good invoice proposal is enough

    # Record the attempt ledger + run history on the block (merge-not-replace).
    # Pure computation off the in-memory snapshot — done BEFORE taking the lock.
    vi2 = dict(audit.get("vision_invoice") or {})
    vi2["attempted_signatures"] = attempted_now
    runs = list(vi2.get("runs") or [])
    runs.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "batch_id": batch_id,
        "documents": doc_records,
        "wrote": wrote,
    })
    vi2["runs"] = runs[-10:]

    # Atomic TOCTOU stickiness guard + merge-write under the per-batch lock.
    # The operator may CONFIRM a proposal (operator_confirmed=true) in another
    # request between our initial read at the top and now; our in-memory `audit`
    # still carries the pre-confirmation block. Acquire the same per-batch write
    # lock `confirm_vision_invoice` holds, re-read the authoritative audit from
    # disk INSIDE the lock, and either (a) abort if a confirmation landed — the
    # operator owns that block — or (b) overlay ONLY our advisory vision_invoice
    # onto the fresh on-disk audit, so we never clobber a concurrent writer of any
    # other key (#646 / #570-class lost update). Both callers (intake, recheck)
    # invoke this OUTSIDE any held batch lock, so acquiring it here cannot deadlock.
    from ..utils.batch_lock import batch_write_lock  # noqa: PLC0415

    def _merge_write_locked() -> bool:
        """Re-read fresh, abort on a landed confirmation, overlay vision_invoice,
        write. Returns True if written, False if aborted (operator owns block)."""
        try:
            fresh = read_json(audit_path)
        except Exception:
            fresh = None
        if not isinstance(fresh, dict):
            fresh = audit  # no readable disk copy — fall back to our snapshot
        if (fresh.get("vision_invoice") or {}).get("operator_confirmed") is True:
            return False
        fresh["vision_invoice"] = vi2
        write_json_atomic(audit_path, fresh)
        return True

    try:
        try:
            with batch_write_lock(batch_id):
                wrote_ok = _merge_write_locked()
        except TimeoutError as exc:
            # Lock contention must not strand the advisory proposal. Best-effort
            # vision-safe fallback: identical merge-write semantics, unlocked.
            log.warning(
                "[vision] batch lock timeout for %s (%s) — vision-safe fallback write",
                batch_id, exc,
            )
            wrote_ok = _merge_write_locked()
    except Exception as exc:
        summary["reason"] = f"audit write failed: {exc}"
        summary["documents"] = doc_records
        return summary

    if not wrote_ok:
        summary["wrote"] = False
        summary["documents"] = doc_records
        summary["reason"] = "operator confirmed vision_invoice mid-run — write aborted (sticky)"
        return summary

    summary["wrote"] = wrote
    summary["documents"] = doc_records
    summary["reason"] = (
        "wrote advisory vision_invoice proposal" if wrote else "ran, no usable invoice summary written"
    )
    return summary


def _vision_invoice_has_proposal(vi: Any) -> bool:
    """True when ``vision_invoice`` carries a confirmable proposal.

    A block that only holds the run ledger (``runs`` / ``attempted_signatures``)
    with no supplier, no FOB, and no line items is NOT a proposal — there is
    nothing for the operator to attest. Confirming such a shell would mint an
    ``operator_confirmed=true`` authority over empty content.
    """
    if not isinstance(vi, dict):
        return False
    if vi.get("supplier"):
        return True
    if vi.get("fob_usd") is not None:
        return True
    if vi.get("line_items"):
        return True
    return False


def confirm_vision_invoice(
    output_dir: Any,
    batch_id: str,
    *,
    confirmed_by: str,
    suppliers_db_path: Any = None,
) -> Dict[str, Any]:
    """Operator confirmation of an advisory ``vision_invoice`` proposal.

    **SOLE WRITER of ``operator_confirmed=true``.** This is the only function in
    the codebase that promotes a machine vision proposal to operator-attested
    authority. The machine extractor (``run_image_only_invoice_extraction`` via
    ``_merge_vision_invoice``) only ever writes ``operator_confirmed=false`` and
    is sticky against this flag — it never sets it true and never overwrites a
    confirmed block. Keeping exactly one writer of this flag is the authority-
    forge guard the PR-2 runbook requires.

    Authority isolation (ADR-031). This function:
      - writes ONLY inside ``audit["vision_invoice"]``;
      - never touches ``invoice_totals``, ``rows``, ``awb_customs``,
        ``clearance_decision``, ``customs_declaration``, SAD/ZC429, or
        ``wfirma_export`` — those stay byte-identical;
      - reads the existing proposal and does NOT re-run extraction;
      - snapshots the machine-original values (confidence + extracted fields)
        before flipping the flag, so the original proposal stays auditable;
      - records confirmation lineage (``confirmed_by`` / ``confirmed_at``) and
        advances the lifecycle ``status`` proposed → confirmed.

    Supplier cross-validation against the contractor/customer master is
    **advisory only** — surfaced in the return payload and stored under
    ``supplier_crosscheck`` (non-authoritative); it never blocks the confirm and
    never mutates supplier authority.

    Idempotent: a second confirm on an already-confirmed block is a no-op that
    returns ``already_confirmed=true``. Returns ``ok=False, reason="no_proposal"``
    when there is nothing confirmable (route maps to 409). Never re-runs
    extraction; never raises on the expected paths.
    """
    from ..utils.io import write_json_atomic, read_json  # noqa: PLC0415
    from ..utils.batch_lock import batch_write_lock  # noqa: PLC0415
    from ..core import timeline as _tl  # noqa: PLC0415

    out = Path(output_dir)
    audit_path = out / "audit.json"
    result: Dict[str, Any] = {
        "ok": False,
        "batch_id": batch_id,
        "reason": "",
        "operator_confirmed": False,
        "supplier_crosscheck": None,
    }

    operator = (confirmed_by or "").strip()
    if not operator:
        result["reason"] = "missing_operator_identity"
        return result

    try:
        with batch_write_lock(batch_id):
            try:
                audit = read_json(audit_path)
            except Exception as exc:
                result["reason"] = f"audit unreadable: {exc}"
                return result
            if not isinstance(audit, dict):
                result["reason"] = "audit not a dict"
                return result

            vi = audit.get("vision_invoice")
            if not _vision_invoice_has_proposal(vi):
                result["reason"] = "no_proposal"
                return result
            vi = dict(vi)

            # Idempotent: an already-confirmed block is owned by the operator.
            if vi.get("operator_confirmed") is True:
                result["ok"] = True
                result["operator_confirmed"] = True
                result["already_confirmed"] = True
                result["reason"] = "already_confirmed"
                result["confirmed_by"] = vi.get("confirmed_by")
                result["confirmed_at"] = vi.get("confirmed_at")
                result["supplier_crosscheck"] = vi.get("supplier_crosscheck")
                return result

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Snapshot the machine-original proposal before attestation, so the
            # original (unconfirmed) confidence and extracted values remain
            # auditable after the flag flips. First-confirm only (idempotent
            # path returns above), so we never clobber an existing snapshot.
            if not vi.get("machine_original"):
                vi["machine_original"] = {
                    "supplier": vi.get("supplier"),
                    "invoice_no": vi.get("invoice_no"),
                    "currency": vi.get("currency"),
                    "fob_usd": vi.get("fob_usd"),
                    "line_items": vi.get("line_items"),
                    "confidence": vi.get("confidence"),
                    "extracted_at": vi.get("extracted_at"),
                    "source_file": vi.get("source_file"),
                    "source_page": vi.get("source_page"),
                }

            # Advisory supplier cross-validation against the supplier master.
            # Never blocks, never mutates supplier authority — payload only.
            crosscheck: Dict[str, Any] = {
                "supplier_name": vi.get("supplier"),
                "checked": False,
                "matched": False,
                "wfirma_id": None,
                "matched_name": None,
            }
            supplier_name = (vi.get("supplier") or "").strip()
            if suppliers_db_path is not None and supplier_name:
                try:
                    from .suppliers_db import find_by_name_normalized  # noqa: PLC0415

                    match = find_by_name_normalized(Path(suppliers_db_path), supplier_name)
                    crosscheck["checked"] = True
                    if match is not None:
                        crosscheck["matched"] = True
                        crosscheck["wfirma_id"] = match.wfirma_id
                        crosscheck["matched_name"] = match.name
                except Exception as exc:  # advisory only — never fail the confirm
                    crosscheck["error"] = f"crosscheck_unavailable: {exc}"
            vi["supplier_crosscheck"] = crosscheck

            # Attestation — the single place operator_confirmed becomes true.
            vi["operator_confirmed"] = True
            vi["status"] = "confirmed"
            vi["source"] = "vision_llm"
            vi["confirmed_by"] = operator
            vi["confirmed_at"] = now

            audit["vision_invoice"] = vi
            try:
                write_json_atomic(audit_path, audit)
            except Exception as exc:
                result["reason"] = f"audit write failed: {exc}"
                return result

            # Timeline event (non-fatal). Kept INSIDE the batch lock: log_event
            # does its own read-append-write of the whole audit, so running it
            # outside the lock opens a lost-update window — a concurrent writer
            # landing between the confirm write and log_event's read-modify-write
            # could clobber the just-confirmed block (the #570 lost-update
            # class). Holding the lock serializes it against lock-honouring
            # writers. It must never fail the confirm, hence the bare except.
            try:
                _tl.log_event(
                    audit_path,
                    event="vision_invoice_confirmed",
                    trigger_source="operator_confirm",
                    actor=operator,
                    detail={
                        "supplier": supplier_name or None,
                        "fob_usd": vi.get("fob_usd"),
                        "line_items": len(vi.get("line_items") or []),
                        "supplier_matched": crosscheck.get("matched"),
                    },
                )
            except Exception:
                pass
    except TimeoutError as exc:
        result["reason"] = f"batch busy: {exc}"
        return result

    result["ok"] = True
    result["operator_confirmed"] = True
    result["reason"] = "operator confirmed vision_invoice proposal"
    result["confirmed_by"] = operator
    result["confirmed_at"] = now
    result["supplier_crosscheck"] = crosscheck
    return result
