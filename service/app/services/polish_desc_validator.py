"""
polish_desc_validator.py — Mandatory format validator for the Polish customs
description PDF that accompanies every DHL proactive dispatch.

The approved baseline (locked 2026-05-08) is the line-for-line invoice
rendering produced for AWB 6049349806. Any future polish description must
match that contract before a proposal can be approved, queued, or sent.

This module is the single source of truth for "is this PDF safe to send to
DHL Warsaw?". It is called from:

  1. ``active_shipment_monitor._ensure_polish_description`` — after the
     engine produces the PDF, the result is stored on the audit so the
     operator UI and the gates below can short-circuit fast.

  2. ``routes_action_proposals.approve_proposal`` — for proposals of type
     ``dhl_proactive_dispatch``, approval is hard-blocked when validation
     fails.

  3. ``routes_action_proposals.queue_proposal`` — same hard-block on the
     queue/send path. The validation result is re-checked at queue time
     so a stale audit cannot let an invalid PDF through.

Rules enforced (each maps to one entry in the returned ``failed_rules`` list):

  R01  full invoice numbers visible (EJL/26-27/<NN>)
  R02  one section per invoice
  R03  per-line rows mirror source invoices line-by-line (when available)
  R04  no synthetic distribution values
  R05  HSN codes preserved exactly from invoices (when available)
  R06  14KT renders as "próby 585"
  R07  SL925 renders as "srebro próby 925"
  R08  forbidden phrases absent (18KT, "Diamond & Colour Stone",
       "kamienie kolorowe", "(N/A)", and the synthetic split values
       152.63 / 152.64)
  R09  consolidated summary section present
  R10  grand CIF total present and equal to invoice CIF totals from audit
  R11  invoice-level CIF totals present
  R12  per-invoice quantities match audit / source (no synthetic redistribution)

Returns a single ``ValidationResult`` dict consumed by all three gates.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


# ── Forbidden phrases (R08) — hard-coded baseline ──────────────────────────
_FORBIDDEN_PHRASES: List[Tuple[str, str]] = [
    ("18KT",                        "18-karat gold not in source — likely engine fallback"),
    ("Diamond & Colour Stone",      "legacy template wording, not present on source invoices"),
    ("kamienie kolorowe",           "Polish 'colour stones' wording, not present on source invoices"),
    ("(N/A)",                       "synthetic placeholder for missing invoice ref"),
    ("FAKTURA / INVOICE 1: N/A",    "synthetic invoice block label"),
    ("Faktury / Invoices: 1 szt.",  "single-invoice header when multiple invoices exist"),
]

# Synthetic-distribution markers — values that the divmod fallback produces
# (FOB / N where N = number of invoices). For the AWB 6049349806 shape these
# were USD 152.63 / USD 152.64; we ban those exact strings as the canonical
# fingerprint of the bug. Real invoice rates that happen to be 152.63/152.64
# will also fail, but that is acceptable: legitimate values can be added to
# this list's exception set when first observed.
_SYNTHETIC_SPLIT_VALUES: List[str] = ["152.63", "152.64"]


# ── Required structural markers (R02, R09, R11) ───────────────────────────
_REQUIRED_SECTION_MARKERS = [
    ("R09", re.compile(r"PODSUMOWANIE\s*/\s*CONSOLIDATED CUSTOMS SUMMARY", re.IGNORECASE)),
    ("R10", re.compile(r"RAZEM\s+CIF\s*/\s*TOTAL CIF", re.IGNORECASE)),
]


def _read_pdf_text(pdf_path: str) -> str:
    """Best-effort PDF text extraction. Empty string on failure (the
    validator surfaces an explicit unreadable_pdf rule failure rather than
    raising, so the gate decides what to do)."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:
        log.warning("[polish_desc_validator] pdf read failed for %s: %s", pdf_path, exc)
        return ""


def _expected_invoice_refs(audit: Dict[str, Any]) -> List[str]:
    """Resolve the invoice reference list the polish desc must mirror.
    Priority: audit.inputs.invoice_refs → parsed from invoice_names.
    Each ref is normalized to canonical form 'EJL/26-27/<NN>'."""
    refs = (audit.get("inputs") or {}).get("invoice_refs") or []
    if refs:
        return [_canonicalize_ref(str(r)) for r in refs]
    names = audit.get("invoice_names") or []
    out: List[str] = []
    for name in names:
        m = re.search(r"EJL[-/]\d{2}[-/]\d{2}[-/](\d+)", name, re.IGNORECASE)
        if m:
            out.append(f"EJL/26-27/{m.group(1)}")
            continue
        # Fallback: leading numeric token
        stem = Path(name).stem
        token = stem.split()[0] if stem.split() else stem
        if token.isdigit():
            out.append(f"EJL/26-27/{token}")
    return out


def _canonicalize_ref(raw: str) -> str:
    """Normalize 'EJL-26-27-121' / '121' / 'EJL/26-27/121' → 'EJL/26-27/121'."""
    s = raw.strip()
    if s.isdigit():
        return f"EJL/26-27/{s}"
    return s.replace("-", "/")


def _expected_grand_cif(audit: Dict[str, Any]) -> Optional[float]:
    it = audit.get("invoice_totals") or {}
    cif = it.get("total_cif_usd")
    if cif is None:
        return None
    try:
        return float(cif)
    except Exception:
        return None


def _expected_quantities(audit: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """Returns (PCS, PRS) from invoice_totals, or (None, None) if unset."""
    it = audit.get("invoice_totals") or {}
    pcs = it.get("total_pcs")
    prs = it.get("total_prs")
    try:
        return (int(pcs) if pcs is not None else None,
                int(prs) if prs is not None else None)
    except Exception:
        return (None, None)


def _expected_hsn_codes(audit: Dict[str, Any]) -> List[str]:
    """Pull HSN/CN codes seen in audit.customs_declaration if present.
    Empty list when not available — R05 then degrades to 'present-only'."""
    cd = audit.get("customs_declaration") or {}
    raw = cd.get("cn_code") or ""
    if not raw:
        return []
    # Split on commas / whitespace; keep only digit-heavy tokens
    tokens = re.split(r"[,\s]+", raw)
    return [t for t in tokens if t and t.isdigit() and len(t) >= 6]


# ── R03 / R12 — heavy cross-check against source invoices ────────────────
def _parse_source_invoice_lines(
    batch_outputs_dir: Path, invoice_filenames: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Best-effort source-invoice parse for the line-by-line cross-check.
    Returns: { '<inv_ref>': { 'lines': [{hsn, qty, rate, amount, uom}],
                              'cif': float, 'fob': float, 'pcs': int, 'prs': int } }
    Falls back to {} when invoices not on disk (R03/R12 then degrade to
    structural-only and the audit invoice_totals carry the cross-check)."""
    out: Dict[str, Dict[str, Any]] = {}
    inv_dir = batch_outputs_dir / "source" / "invoices"
    if not inv_dir.is_dir():
        return out
    try:
        import pdfplumber
    except Exception:
        return out

    line_re = re.compile(
        r"(\S.+?)\s+(\d{6,8})\s+(PCS|PRS)\s+([\d.]+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})"
    )
    cif_re = re.compile(r"TOTAL\s+CIF\s+VALUE\s+US\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
    fob_total_re = re.compile(r"TOTAL\s+FOB\s+VALUE\s+US\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
    fob_re = re.compile(r"FOB\s+US\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
    pcs_re = re.compile(r"TOTAL\s+PCS\s+([\d.]+)", re.IGNORECASE)
    prs_re = re.compile(r"PRS\s+([\d.]+)\s*\n", re.IGNORECASE)
    ref_re = re.compile(r"EJL[/-]26[/-]27[/-](\d+)", re.IGNORECASE)

    for fn in invoice_filenames:
        path = inv_dir / fn
        if not path.is_file():
            continue
        try:
            with pdfplumber.open(path) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception:
            continue

        m = ref_re.search(fn) or ref_re.search(text)
        if not m:
            continue
        ref = f"EJL/26-27/{m.group(1)}"

        lines: List[Dict[str, Any]] = []
        for lm in line_re.finditer(text):
            try:
                lines.append({
                    "hsn":    lm.group(2),
                    "uom":    lm.group(3),
                    "qty":    float(lm.group(4)),
                    "rate":   float(lm.group(5).replace(",", "")),
                    "amount": float(lm.group(6).replace(",", "")),
                })
            except Exception:
                pass

        cif_m = cif_re.search(text)
        cif_val: Optional[float] = None
        if cif_m:
            try: cif_val = float(cif_m.group(1).replace(",", ""))
            except Exception: cif_val = None
        if cif_val is None:
            fobtot = fob_total_re.search(text)
            if fobtot:
                try: cif_val = float(fobtot.group(1).replace(",", ""))
                except Exception: cif_val = None

        fob_m = fob_re.search(text)
        fob_val: Optional[float] = None
        if fob_m:
            try: fob_val = float(fob_m.group(1).replace(",", ""))
            except Exception: fob_val = None

        pcs_m = pcs_re.search(text)
        prs_m = prs_re.search(text)
        try:
            pcs_v = int(float(pcs_m.group(1))) if pcs_m else 0
        except Exception:
            pcs_v = 0
        try:
            prs_v = int(float(prs_m.group(1))) if prs_m else 0
        except Exception:
            prs_v = 0

        out[ref] = {"lines": lines, "cif": cif_val, "fob": fob_val,
                    "pcs": pcs_v, "prs": prs_v}
    return out


# ── Core validator ────────────────────────────────────────────────────────
def validate_polish_customs_description(
    pdf_path: str,
    audit: Dict[str, Any],
    batch_outputs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Validate that ``pdf_path`` matches the approved Polish customs
    description format. Returns a dict the calling gate consumes::

        {
          "valid":        bool,
          "validated_at": ISO timestamp,
          "pdf_path":     <input path>,
          "failed_rules": [ {"rule": "R01", "detail": "..."}, ... ],
          "passed_rules": [ "R02", "R06", ... ],
          "summary":      "short human summary",
          "expected": {
             "invoice_refs":   [...],
             "grand_cif":      float|None,
             "pcs": int|None, "prs": int|None,
             "hsn_codes":      [...],
          },
        }

    The validator NEVER raises. Callers convert to HTTP 422 / audit error
    markers based on ``valid``.
    """
    failed: List[Dict[str, str]] = []
    passed: List[str] = []
    def _fail(rule: str, detail: str) -> None: failed.append({"rule": rule, "detail": detail})
    def _ok(rule: str) -> None: passed.append(rule)

    # ── Read PDF ──
    if not pdf_path or not Path(pdf_path).is_file():
        return {
            "valid":        False,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "pdf_path":     pdf_path,
            "failed_rules": [{"rule": "R00", "detail": f"PDF file not found: {pdf_path}"}],
            "passed_rules": [],
            "summary":      "validation failed: PDF not found",
            "expected":     {},
        }
    text = _read_pdf_text(pdf_path)
    if not text:
        return {
            "valid":        False,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "pdf_path":     pdf_path,
            "failed_rules": [{"rule": "R00", "detail": "PDF text extraction returned empty"}],
            "passed_rules": [],
            "summary":      "validation failed: unreadable PDF",
            "expected":     {},
        }

    # Lower-cased copy for case-insensitive checks
    text_lc = text.lower()

    # ── Resolve expectations from audit ──
    expected_refs = _expected_invoice_refs(audit)
    grand_cif     = _expected_grand_cif(audit)
    exp_pcs, exp_prs = _expected_quantities(audit)
    exp_hsn_audit = _expected_hsn_codes(audit)

    # ── R01: full invoice numbers visible ──
    # When audit carries invoice refs (inputs.invoice_refs / invoice_names),
    # every ref must appear in the PDF text. When neither location has
    # refs (parse-light path), this rule degrades to "the PDF must contain
    # at least one full EJL/<period>/<NN> token" so we still catch a
    # totally ref-less PDF without false-failing on legacy audits.
    section_pat = re.compile(r"FAKTURA\s*/\s*INVOICE:\s*(EJL/\d{2}-\d{2}/\d+)", re.IGNORECASE)
    sections = section_pat.findall(text)
    if expected_refs:
        missing_refs = [r for r in expected_refs if r not in text]
        if missing_refs:
            _fail("R01", f"missing invoice refs: {missing_refs}")
        else:
            _ok("R01")
    else:
        # Degraded mode: PDF self-asserts at least one full ref token
        if not sections:
            _fail("R01", "audit has no invoice refs AND PDF has no full EJL/.../NNN ref")
        else:
            _ok("R01")

    # ── R02: each invoice has its own section ──
    if expected_refs:
        missing_sections = [r for r in expected_refs if r not in sections]
        if missing_sections:
            _fail("R02", f"missing per-invoice section headers: {missing_sections}")
        else:
            _ok("R02")
    else:
        if not sections:
            _fail("R02", "no FAKTURA / INVOICE: section headers detected")
        else:
            _ok("R02")

    # ── R08: forbidden phrases absent ──
    forb_hits: List[str] = []
    for phrase, why in _FORBIDDEN_PHRASES:
        if phrase.lower() in text_lc:
            forb_hits.append(f"{phrase!r} — {why}")
    for v in _SYNTHETIC_SPLIT_VALUES:
        if v in text:
            forb_hits.append(f"synthetic split value '{v}' present")
    if forb_hits:
        _fail("R08", "; ".join(forb_hits))
    else:
        _ok("R08")

    # ── R04: no obvious synthetic distribution markers ──
    # Heuristic: presence of identical per-line value across many lines that
    # also matches FOB/N — already covered by _SYNTHETIC_SPLIT_VALUES which
    # is the canonical fingerprint. R04 passes when R08 passes for those
    # values.
    if all(v not in text for v in _SYNTHETIC_SPLIT_VALUES):
        _ok("R04")
    else:
        _fail("R04", f"synthetic split fingerprint present: {[v for v in _SYNTHETIC_SPLIT_VALUES if v in text]}")

    # ── R06: 14KT terminology ──
    has_14kt_token = bool(re.search(r"\b14[\s-]?KT\b|14-?karat", text, re.IGNORECASE))
    has_proba_585  = "próby 585" in text or "proby 585" in text
    if has_14kt_token and not has_proba_585:
        _fail("R06", "PDF mentions 14KT but does not include the Polish 'próby 585' rendering")
    elif has_proba_585:
        _ok("R06")
    else:
        # No 14KT goods in this shipment — rule trivially holds
        _ok("R06")

    # ── R07: SL925 → "srebro próby 925" ──
    has_sl925_token = bool(re.search(r"\bSL\s*925\b|silver", text, re.IGNORECASE))
    has_srebro_925  = re.search(r"srebr[oa]\s+pr[óo]by\s*925", text, re.IGNORECASE)
    # If silver/SL925 appears, "srebro próby 925" must appear
    silver_hits = bool(re.search(r"\bSL\s*925\b", text, re.IGNORECASE))
    if silver_hits and not has_srebro_925:
        _fail("R07", "PDF mentions SL925 but does not include the Polish 'srebro próby 925' rendering")
    else:
        _ok("R07")

    # ── R09: consolidated summary present ──
    for rule, pat in _REQUIRED_SECTION_MARKERS:
        if pat.search(text):
            _ok(rule)
        else:
            _fail(rule, f"missing required section marker for {rule}: pattern={pat.pattern!r}")

    # ── R11: per-invoice CIF totals present ──
    inv_cif_pat = re.compile(
        r"(?:Razem\s+CIF\s+faktury|Invoice\s+CIF\s+total).*?USD\s*[\d,]+\.\d{2}",
        re.IGNORECASE | re.DOTALL,
    )
    inv_cif_count = len(inv_cif_pat.findall(text))
    if expected_refs and inv_cif_count < len(expected_refs):
        _fail("R11", f"per-invoice CIF rows expected={len(expected_refs)} found={inv_cif_count}")
    else:
        _ok("R11")

    # ── R10: grand CIF total present and matches audit ──
    # Anchor to the explicit grand-total wording ("RAZEM CIF / TOTAL CIF")
    # so this does NOT collide with per-invoice "Razem CIF faktury /
    # Invoice CIF total" rows (R11). Take the dollar amount that follows
    # within the same paragraph.
    grand_cif_pat = re.compile(
        r"RAZEM\s+CIF\s*/\s*TOTAL\s+CIF[^$\n]*?USD\s*([\d,]+\.\d{2})",
        re.IGNORECASE,
    )
    m = grand_cif_pat.search(text)
    if not m:
        _fail("R10", "grand CIF total row not found")
    elif grand_cif is None:
        _ok("R10")  # PDF has it; audit does not — accept
    else:
        try:
            pdf_cif = float(m.group(1).replace(",", ""))
            if abs(pdf_cif - grand_cif) > 0.01:
                _fail("R10", f"grand CIF mismatch: pdf={pdf_cif} audit={grand_cif}")
            else:
                _ok("R10")
        except Exception:
            _fail("R10", "could not parse grand CIF from PDF")

    # ── R03 / R12 / R05 — heavy cross-check (best effort) ──
    src_invoices: Dict[str, Dict[str, Any]] = {}
    inv_names = audit.get("invoice_names") or []
    if batch_outputs_dir is not None and inv_names:
        src_invoices = _parse_source_invoice_lines(batch_outputs_dir, inv_names)

    if src_invoices:
        # R03: each parsed line's amount must appear in PDF text
        missing_amounts: List[str] = []
        for ref, data in src_invoices.items():
            for ln in data["lines"]:
                amt_str = f"{ln['amount']:,.2f}"
                if amt_str not in text:
                    missing_amounts.append(f"{ref} amount {amt_str}")
        if missing_amounts:
            _fail("R03", f"per-line invoice amounts missing in PDF: {missing_amounts[:8]}")
        else:
            _ok("R03")

        # R05: each source HSN must appear in PDF
        all_src_hsn = sorted({ln["hsn"] for d in src_invoices.values() for ln in d["lines"]})
        missing_hsn = [h for h in all_src_hsn if h not in text]
        if missing_hsn:
            _fail("R05", f"HSN codes from invoices missing in PDF: {missing_hsn}")
        else:
            _ok("R05")

        # R12: per-invoice qty must match source
        qty_mismatch: List[str] = []
        for ref, data in src_invoices.items():
            src_pcs = data["pcs"] or sum(int(ln["qty"]) for ln in data["lines"] if ln["uom"] == "PCS")
            src_prs = data["prs"] or sum(int(ln["qty"]) for ln in data["lines"] if ln["uom"] == "PRS")
            # Look up per-invoice line in the polish desc: "Suma sztuk … X PCS · Y PRS"
            ipat = re.compile(
                rf"FAKTURA\s*/\s*INVOICE:\s*{re.escape(ref)}.+?Suma\s+sztuk[^:]*:\s*(\d+)\s*PCS.*?(\d+)\s*PRS",
                re.IGNORECASE | re.DOTALL,
            )
            mq = ipat.search(text)
            if mq:
                pdf_pcs, pdf_prs = int(mq.group(1)), int(mq.group(2))
                if pdf_pcs != src_pcs or pdf_prs != src_prs:
                    qty_mismatch.append(
                        f"{ref}: pdf={pdf_pcs} PCS / {pdf_prs} PRS  source={src_pcs} PCS / {src_prs} PRS"
                    )
            else:
                qty_mismatch.append(f"{ref}: per-invoice qty row not found")
        if qty_mismatch:
            _fail("R12", "; ".join(qty_mismatch))
        else:
            _ok("R12")
    else:
        # Degraded mode: cross-check against audit-level counts.
        # Match "X PCS … Y PRS" anywhere on a line that contains "Razem"
        # (Polish for "Total") — robust to the Polish 'ilość' diacritics
        # that sometimes round-trip as variants through pdfplumber.
        if exp_pcs is not None or exp_prs is not None:
            grand_qty_pat = re.compile(
                r"Razem[^\n]*?(\d+)\s*PCS[^\n]*?(\d+)\s*PRS",
                re.IGNORECASE,
            )
            mq = grand_qty_pat.search(text)
            if mq:
                pdf_pcs, pdf_prs = int(mq.group(1)), int(mq.group(2))
                if (exp_pcs is not None and pdf_pcs != exp_pcs) or \
                   (exp_prs is not None and pdf_prs != exp_prs):
                    _fail("R12", f"qty mismatch: pdf={pdf_pcs}/{pdf_prs} audit={exp_pcs}/{exp_prs}")
                else:
                    _ok("R12")
            else:
                _fail("R12", "grand quantity row not found in PDF")
        else:
            _ok("R12")
        # R03 / R05 cannot be cross-checked without source — pass
        # structurally (operator is responsible if no source on disk).
        _ok("R03")
        if exp_hsn_audit:
            missing_hsn = [h for h in exp_hsn_audit if h not in text]
            if missing_hsn:
                _fail("R05", f"HSN codes in audit.customs_declaration missing from PDF: {missing_hsn}")
            else:
                _ok("R05")
        else:
            _ok("R05")

    valid = (len(failed) == 0)
    return {
        "valid":        valid,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "pdf_path":     pdf_path,
        "failed_rules": failed,
        "passed_rules": passed,
        "summary":      ("polish description format ✓"
                         if valid else
                         f"polish description failed {len(failed)} rule(s): "
                         + ", ".join(f["rule"] for f in failed)),
        "expected": {
            "invoice_refs":  expected_refs,
            "grand_cif":     grand_cif,
            "pcs":           exp_pcs,
            "prs":           exp_prs,
            "hsn_codes":     exp_hsn_audit,
        },
    }
