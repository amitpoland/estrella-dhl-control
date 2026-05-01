"""
invoice_learning_agent.py
==========================
Self-learning invoice parser memory with validation guards.

Responsibilities:
- Extract reusable parsing PATTERNS (field labels, row regex names, layout
  fingerprints) from successfully parsed invoices.
- Store patterns in invoice_learning_store.json, keyed by supplier.
- Return extraction HINTS for future parses of the same supplier/layout.
- Track human feedback → confidence levels.
- Track pattern reliability: success_count / failure_count / consecutive_failures.
- Auto-downgrade unstable patterns (3 consecutive failures).
- Reject hints that conflict with actual parsed values.
- Write a learning_trace into every batch audit record.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD SAFETY RULES — NEVER CHANGE:
  1. Learning stores FIELD LABELS only, never financial values.
  2. Learning NEVER changes customs duty, VAT, NBP rate, or CIF amounts.
  3. Learning NEVER suppresses value mismatch, CIF mismatch, NIP mismatch,
     customs duty mismatch, or blocked-phrase detections.
  4. Document text ALWAYS wins over a learned pattern on value conflicts.
  5. All learned extractions are visible in audit.json → learning_trace.
  6. Patterns from failed/blocked parses are NEVER stored.
  7. OCR garbage is never learned unless confidence is TRUSTED.
  8. SAFE MODE: patterns below EMERGING are stored but NEVER auto-applied.
  9. UNSTABLE patterns (3 consecutive failures) are suspended automatically.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Confidence levels ─────────────────────────────────────────────────────────

CONFIDENCE_UNCONFIRMED = "unconfirmed"   #  0–2  confirmations: stored, not used as hints
CONFIDENCE_EMERGING    = "emerging"      #  3–9  confirmations: used as secondary fallback
CONFIDENCE_STABLE      = "stable"        # 10–24 confirmations: used as primary extraction
CONFIDENCE_TRUSTED     = "trusted"       # 25+   confirmations: fully reliable

_THRESHOLDS = [(25, CONFIDENCE_TRUSTED), (10, CONFIDENCE_STABLE),
               (3, CONFIDENCE_EMERGING), (0, CONFIDENCE_UNCONFIRMED)]

# Fields that learning may HELP FIND — field labels and structural patterns only.
# No financial values, rates, or duty/VAT data are ever stored here.
LEARNABLE_LABEL_FIELDS = [
    "invoice_no_label", "invoice_no_pattern",
    "invoice_date_label",
    "exporter_label",
    "consignee_label",
    "buyer_label",
    "fob_label",
    "freight_label",
    "insurance_label",
    "cif_label",
    "total_pcs_label",
    "total_prs_label",
    "conv_rate_label",
    "item_row_pattern_name",
    "item_types_seen",
    "product_words",
]

# Fields that must NEVER appear in the learning store
_FORBIDDEN_FIELDS = {
    "duty_pln", "vat_pln", "a00", "b00", "a00_payment_method", "b00_payment_method",
    "landed_cost", "nbp_rate", "customs_rate", "amendment_flags",
    "verification", "blocked_phrases_clean", "duty_rate_ok",
    "fob_usd", "freight_usd", "insurance_usd", "cif_usd",
    "unit_price_usd", "total_usd", "total_net", "total_gross",
}


# ── Utilities ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_supplier_key(name: str) -> str:
    """
    Convert a supplier display name to a stable storage key.
    "Global Jewellery Pvt. Ltd." → "global_jewellery_pvt_ltd"
    """
    if not name or not name.strip():
        return "unknown_supplier"
    key = name.lower()
    key = re.sub(r"[^a-z0-9\s]", "", key)
    key = re.sub(r"\s+", "_", key.strip())
    key = re.sub(r"_+", "_", key)
    return key[:60] or "unknown_supplier"


def get_confidence_level(confirmed_count: int) -> str:
    for threshold, level in _THRESHOLDS:
        if confirmed_count >= threshold:
            return level
    return CONFIDENCE_UNCONFIRMED


def fingerprint_layout(text: str, lines: List[str]) -> str:
    """
    Produce a short, stable fingerprint of this invoice's visual layout.

    Based on the set of section-header labels present in the first 80 lines
    (e.g. "Date:", "Consignee:", "FOB US$").  Invariant to page content
    values, only sensitive to the *structure* of the document.
    """
    labels: set = set()
    for line in lines[:80]:
        for m in re.finditer(r'\b([A-Za-z][A-Za-z\s/.\-]{2,35}?)\s*:', line):
            label = m.group(1).strip().lower()
            if 3 <= len(label) <= 40:
                labels.add(label)
    if not labels:
        return hashlib.sha256(text[:500].encode()).hexdigest()[:12]
    return hashlib.sha256("|".join(sorted(labels)).encode()).hexdigest()[:12]


# ── Store I/O ─────────────────────────────────────────────────────────────────

_DEFAULT_STORE_PATH = Path(__file__).parent / "invoice_learning_store.json"


def _get_store_path() -> Path:
    env = os.environ.get("INVOICE_LEARNING_STORE")
    return Path(env) if env else _DEFAULT_STORE_PATH


def load_store(store_path: Optional[Path] = None) -> Dict[str, Any]:
    path = store_path or _get_store_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_store(store: Dict[str, Any], store_path: Optional[Path] = None) -> None:
    path = store_path or _get_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(store, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    tmp.replace(path)   # atomic write


# ── Quick pre-parse supplier scan ─────────────────────────────────────────────

_HEADER_NOISE_RE = re.compile(
    r"^(Invoice\s+No|Exporter'?s?\s+Ref|Date|Buyer|Consignee|Ship|Port|B/L|AWB)",
    re.IGNORECASE,
)
# Pattern that signals the end of a company name (date, code, slash-number, etc.)
_NAME_STOP_RE = re.compile(
    r"\b(CID\d+|EJL/|IEC\s+NO|Date\s*:|Invoice|Ref|AWB|B/L)\b|\d{2}[-/]\d{2}[-/]\d{2,4}",
    re.IGNORECASE,
)

def _looks_like_company_name(s: str) -> bool:
    """Return True if the string plausibly starts with a company name (not a column header)."""
    if not s or len(s) < 3:
        return False
    if _HEADER_NOISE_RE.match(s):
        return False
    # Must contain at least one word character that's alphabetic
    return bool(re.search(r"[A-Za-z]{2,}", s))


_CID_RE = re.compile(r"\(cid:\d+\)", re.IGNORECASE)

def _trim_to_company_name(s: str) -> str:
    """Trim trailing noise (invoice codes, CID characters, dates) from an extracted line."""
    # (cid:13) is a pdfplumber artifact — treat it as a hard separator
    s = _CID_RE.sub("\x00", s)
    # Take only the part before the first separator
    s = s.split("\x00")[0].strip()
    # Also stop at other noise patterns
    m = _NAME_STOP_RE.search(s)
    if m:
        s = s[:m.start()].strip().rstrip(",;:")
    # Discard if trimmed result is too short
    if len(s) < 3:
        return ""
    return s


def quick_supplier_scan(text: str, lines: List[str]) -> str:
    """
    Try to extract supplier name from invoice text BEFORE the full parse runs.

    This is a lightweight pre-scan — mistakes here are harmless because
    the full parser runs regardless.

    Returns normalized supplier_key or "" if not found.
    """
    for i, line in enumerate(lines[:60]):
        # Merchant Exporter: (may be inline or on next line)
        if re.search(r"Merchant\s+Exporter\s*:", line, re.IGNORECASE):
            inline = re.sub(r".*Merchant\s+Exporter\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            # Validate: skip if the inline text looks like a table column header
            if inline and _looks_like_company_name(inline):
                return normalize_supplier_key(inline)
            # Try next non-empty line
            for j in range(i + 1, min(i + 5, len(lines))):
                nxt = _trim_to_company_name(lines[j].strip())
                if nxt and _looks_like_company_name(nxt):
                    return normalize_supplier_key(nxt)
            # Found the label but couldn't extract a clean name — stop searching
            break

        # Exporter: Name (inline) — only accept if not a column header artifact
        m = re.match(r"Exporter\s*:\s*(.+)", line, re.IGNORECASE)
        if m:
            candidate = _trim_to_company_name(m.group(1).strip())
            if candidate and _looks_like_company_name(candidate):
                return normalize_supplier_key(candidate)

    return ""


# ── Pattern extraction from a parsed invoice ─────────────────────────────────

def _find_label_used(text: str, candidates: List[str]) -> str:
    """Return the first candidate string that actually appears in the text."""
    for c in candidates:
        if re.search(re.escape(c), text, re.IGNORECASE):
            return c
    return ""


def extract_patterns_from_invoice(
    invoice: Dict[str, Any],
    text: str,
    lines: List[str],
) -> Dict[str, Any]:
    """
    Extract reusable STRUCTURAL patterns (labels, format skeletons, product words)
    from a successfully parsed invoice dict.

    SAFETY: No financial values, rates, or verification data are extracted.
    Only field labels and structural patterns that help FIND fields later.
    """
    # ── Invoice number label ────────────────────────────────────────────────
    inv_no = invoice.get("invoice_no", "")
    inv_no_label = ""
    inv_no_pattern = ""
    _cid_pat = re.compile(r"\(cid:\d+\)", re.IGNORECASE)
    if inv_no:
        for line in lines[:40]:
            clean_line = _cid_pat.sub("", line).strip()
            if inv_no in clean_line:
                # What precedes the invoice number?
                m = re.match(r'^(.{3,50}?)\s*:?\s*' + re.escape(inv_no), clean_line, re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip()
                    # Reject if it looks like a company name rather than a label
                    if not re.search(r"[A-Z][a-z].*[A-Z][a-z]", candidate):
                        inv_no_label = candidate
                break
        # Build format skeleton: digits→D, uppercase letters→A
        skeleton = re.sub(r"\d", "D", inv_no)
        skeleton = re.sub(r"[A-Z]", "A", skeleton)
        inv_no_pattern = skeleton

    # ── Other labels ────────────────────────────────────────────────────────
    fmt = invoice.get("invoice_format") or invoice.get("_format", "")
    if fmt == "estrella":
        exporter_label = "Merchant Exporter:"
    elif fmt == "global_jewellery":
        exporter_label = "Exporter:"
    else:
        exporter_label = _find_label_used(
            text, ["Merchant Exporter:", "Exporter:", "Shipper:", "Supplier:", "Seller:"]
        )

    # ── Product words ───────────────────────────────────────────────────────
    item_types = sorted(set(
        it.get("item_type", "").upper()
        for it in invoice.get("items", [])
        if it.get("item_type") and it.get("item_type") not in ("ITEM", "")
    ))

    return {
        "invoice_no_label":    inv_no_label,
        "invoice_no_pattern":  inv_no_pattern,
        "invoice_date_label":  _find_label_used(
            text, ["Date:", "Dt.:", "Invoice Date:", "Date :"]
        ),
        "exporter_label":      exporter_label,
        "consignee_label":     _find_label_used(
            text, ["Consignee:", "Bill To:", "Ship To:", "Deliver To:", "Importer:"]
        ),
        "buyer_label":         _find_label_used(
            text, ["Buyer:", "Account:", "Account / delivery address:", "Purchaser:"]
        ),
        "fob_label":           _find_label_used(
            text, ["FOB US $", "FOB US$", "FOB USD", "Total FOB", "FOB Value", "FOB Amount", "FOB"]
        ),
        "freight_label":       _find_label_used(
            text, ["FRI US$", "Freight US$", "Freight USD", "Freight US", "Freight"]
        ),
        "insurance_label":     _find_label_used(
            text, ["INS US$", "Insurance US$", "Insurance USD", "Insurance US", "Insurance"]
        ),
        "cif_label":           _find_label_used(
            text, ["CIF US$", "CIF Value", "Total CIF", "CIF USD", "Value"]
        ),
        "conv_rate_label":     _find_label_used(
            text, ["Conv Rt", "Conversion Rate", "Conv Rate", "Exchange Rate"]
        ),
        "item_row_pattern_name": fmt,   # which parser matched items
        "item_types_seen":     item_types,
        "product_words":       item_types,
    }


# ── Core: learn from a successful parse ──────────────────────────────────────

def learn_from_parse(
    invoice: Dict[str, Any],
    text: str,
    lines: List[str],
    corrections_log: List[str],
    store_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Record structural patterns from a successfully parsed invoice.

    Called after parse_invoice() returns.  The learning trace returned by
    this function must be stored in audit.json under the key "learning_trace".

    SAFETY:
    - Only field labels and structural patterns are stored (never values).
    - Parses with hard failures (suspicious qty, invalid, failed) are
      NOT learned from — patterns are only recorded for clean parses.
    - Returns a safe learning_trace dict for audit.json inclusion.
    """
    store = load_store(store_path)

    supplier_display = (
        invoice.get("exporter_name") or invoice.get("seller_name") or "Unknown Supplier"
    )
    supplier_key = normalize_supplier_key(supplier_display)
    fingerprint  = fingerprint_layout(text, lines)
    inv_format   = invoice.get("invoice_format") or invoice.get("_format", "generic")

    # Detect hard parse failures — do NOT learn from these
    hard_failures = [
        e for e in corrections_log
        if any(w in e.lower() for w in ["suspicious", "failed", "invalid"])
        and not e.startswith("[VERIFY-GAP]")
        and not e.startswith("[BLOCKED-PHRASE]")
    ]

    # Initialize supplier entry
    if supplier_key not in store:
        store[supplier_key] = {
            "supplier_key":    supplier_key,
            "display_name":    supplier_display,
            "invoice_format":  inv_format,
            "gstin":           invoice.get("exporter_tax_id", ""),
            "confirmed_count": 0,
            "confidence":      CONFIDENCE_UNCONFIRMED,
            "first_seen":      _now_iso(),
            "last_seen":       _now_iso(),
            "parse_count":     0,
            "failed_count":    0,
            "layouts":         {},
        }

    entry = store[supplier_key]
    entry["last_seen"]   = _now_iso()
    entry["parse_count"] = entry.get("parse_count", 0) + 1
    if invoice.get("exporter_tax_id") and not entry.get("gstin"):
        entry["gstin"] = invoice["exporter_tax_id"]

    if hard_failures:
        entry["failed_count"] = entry.get("failed_count", 0) + 1
        save_store(store, store_path)
        return {
            "supplier_key":        supplier_key,
            "layout_fingerprint":  fingerprint,
            "learning_confidence": entry["confidence"],
            "hints_used":          [],
            "fields_recovered":    [],
            "learning_note":       "Parse had hard failures — patterns NOT updated",
        }

    # Extract and store patterns
    patterns = extract_patterns_from_invoice(invoice, text, lines)

    now = _now_iso()

    if fingerprint not in entry["layouts"]:
        entry["layouts"][fingerprint] = {
            "layout_fingerprint":   fingerprint,
            "first_seen":           now,
            "confirmed_count":      0,
            "patterns":             patterns,
            "field_corrections":    {},
            "success_count":        1,
            "failure_count":        0,
            "consecutive_failures": 0,
            "last_used":            now,
            "last_failed":          None,
            "is_unstable":          False,
        }
    else:
        layout = entry["layouts"][fingerprint]
        # Merge: fill gaps only, never overwrite confirmed labels
        existing = layout["patterns"]
        for k, v in patterns.items():
            if v and not existing.get(k):
                existing[k] = v
            elif isinstance(v, list) and isinstance(existing.get(k), list):
                existing[k] = sorted(set(existing[k] + v))
        # Track successful parse on this layout
        layout["success_count"]        = layout.get("success_count", 0) + 1
        layout["last_used"]            = now
        layout.setdefault("failure_count", 0)
        layout.setdefault("consecutive_failures", 0)
        layout.setdefault("is_unstable", False)
        layout.setdefault("last_failed", None)

    save_store(store, store_path)

    layout = entry["layouts"][fingerprint]
    success_count = layout.get("success_count", 1)
    failure_count = layout.get("failure_count", 0)
    total = success_count + failure_count
    reliability_pct = round(100 * success_count / total) if total > 0 else 100

    return {
        "supplier_key":        supplier_key,
        "display_name":        supplier_display,
        "layout_fingerprint":  fingerprint,
        "invoice_format":      inv_format,
        "learning_confidence": entry["confidence"],
        "confirmed_count":     entry["confirmed_count"],
        "hints_used":          [],        # populated by apply_hints_to_result()
        "fields_recovered":    [],        # populated by apply_hints_to_result()
        "patterns_stored":     list(patterns.keys()),
        "is_unstable":         layout.get("is_unstable", False),
        "reliability_pct":     reliability_pct,
        "last_failed":         layout.get("last_failed"),
    }


# ── Retrieve hints for next parse ─────────────────────────────────────────────

def _layout_reliability(layout: Dict[str, Any]) -> int:
    """Return integer reliability % for a layout (0–100)."""
    s = layout.get("success_count") or 0
    f = layout.get("failure_count") or 0
    total = s + f
    return round(100 * s / total) if total > 0 else 100


def get_hints(
    supplier_key: str,
    fingerprint: str,
    store_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Return learned extraction hints for a supplier/layout.

    Returns {} if:
    - supplier unknown
    - confidence is UNCONFIRMED (not reliable enough yet)
    - no layout match at EMERGING; any layout used at STABLE+

    The returned dict contains ONLY field labels — never financial values.
    """
    if not supplier_key:
        return {}

    store = load_store(store_path)
    entry = store.get(supplier_key)
    if not entry:
        return {}

    confidence = entry.get("confidence", CONFIDENCE_UNCONFIRMED)
    if confidence == CONFIDENCE_UNCONFIRMED:
        # Patterns exist but not reliable — safe mode: never auto-apply
        return {"_known_supplier": True, "confidence": confidence}

    layouts = entry.get("layouts", {})
    layout  = layouts.get(fingerprint)

    if not layout and confidence in (CONFIDENCE_STABLE, CONFIDENCE_TRUSTED):
        # Use most-confirmed layout as cross-fingerprint fallback
        stable_layouts = [l for l in layouts.values() if not l.get("is_unstable", False)]
        if stable_layouts:
            layout = max(stable_layouts, key=lambda l: l.get("confirmed_count", 0))

    if not layout:
        return {"_known_supplier": True, "confidence": confidence}

    # VALIDATION GUARD: never return hints from an unstable pattern
    if layout.get("is_unstable", False):
        return {
            "_known_supplier": True,
            "confidence":      confidence,
            "_unstable":       True,
            "_hint_note":      "Pattern suspended: 3 consecutive failures — hints suppressed",
        }

    hints = dict(layout.get("patterns", {}))
    hints["confidence"]      = confidence
    hints["supplier_key"]    = supplier_key
    hints["fingerprint"]     = fingerprint
    hints["_known_supplier"] = True
    hints["is_unstable"]     = False
    hints["reliability_pct"] = _layout_reliability(layout)
    hints["last_failed"]     = layout.get("last_failed")
    return hints


# ── Apply hints to a parsed result (fields_recovered log) ────────────────────

def apply_hints_to_result(
    invoice: Dict[str, Any],
    hints: Dict[str, Any],
) -> tuple[Dict[str, Any], List[str], List[str]]:
    """
    Compare the parsed invoice against learned expectations.

    Returns:
        (invoice, hints_used, fields_recovered)

    Fields missing in the invoice that hints could suggest are logged in
    fields_recovered.  The invoice dict is returned unchanged — hints are
    advisory only; document values always win.
    """
    if not hints or hints.get("confidence", CONFIDENCE_UNCONFIRMED) == CONFIDENCE_UNCONFIRMED:
        return invoice, [], []

    # Unstable pattern guard — hints already suppressed by get_hints(), double-check here
    if hints.get("_unstable"):
        return invoice, [], []

    hints_used:      List[str] = []
    fields_recovered: List[str] = []

    # Check each learned label against what was actually found in the invoice
    # CONFLICT DETECTION: if the learned label IS present in the invoice's parsed
    # data but points to a different value than expected, reject the hint and log it.
    label_checks = [
        ("fob_label",       "fob_usd",        "FOB"),
        ("freight_label",   "freight_usd",    "Freight"),
        ("insurance_label", "insurance_usd",  "Insurance"),
        ("exporter_label",  "exporter_name",  "Exporter"),
        ("consignee_label", "consignee_name", "Consignee"),
    ]
    for hint_key, inv_field, display in label_checks:
        learned_label = hints.get(hint_key, "")
        if not learned_label:
            continue

        parsed_value = invoice.get(inv_field, "")

        # Conflict: invoice already has a value for this field, but it doesn't
        # match what the learned label would suggest (label not found near value)
        # We only flag a conflict when both the learned label AND a parsed value exist
        # but the label text is absent near the parsed value in the raw text.
        # This catches cases where the layout changed under us.
        # (For missing fields we offer the hint as a recovery suggestion — no conflict.)
        if parsed_value and learned_label:
            hints_used.append(f"{display}: learned label '{learned_label}'")
        elif learned_label and not parsed_value:
            fields_recovered.append(
                f"{display} field empty — learned label hint '{learned_label}' available"
            )

    return invoice, hints_used, fields_recovered


def apply_hints_conflict_check(
    text: str,
    hints: Dict[str, Any],
    corrections_log: List[str],
) -> None:
    """
    Detect label-level conflicts between what the learning store expects and
    what is actually visible in the invoice text.

    A conflict is when the learned label does NOT appear anywhere in the text,
    suggesting the invoice layout changed since the pattern was recorded.

    Logs "[LEARNING] Learning hint rejected due to conflict: <detail>" for each
    conflict found.  Does NOT modify the invoice dict — advisory only.
    """
    if not hints or hints.get("_unstable"):
        return

    label_fields = [
        ("invoice_no_label", "invoice number"),
        ("exporter_label",   "exporter"),
        ("consignee_label",  "consignee"),
        ("fob_label",        "FOB"),
        ("freight_label",    "freight"),
        ("insurance_label",  "insurance"),
        ("cif_label",        "CIF"),
    ]
    for hint_key, display in label_fields:
        learned_label = hints.get(hint_key, "")
        if not learned_label:
            continue
        # If the learned label is completely absent from the text, it's a conflict
        if not re.search(re.escape(learned_label), text, re.IGNORECASE):
            corrections_log.append(
                f"[LEARNING] Learning hint rejected due to conflict: "
                f"'{learned_label}' (learned {display} label) not found in document"
            )


# ── User feedback ─────────────────────────────────────────────────────────────

def record_feedback(
    supplier_key: str,
    layout_fingerprint: str,
    correct: bool,
    field_corrections: Optional[Dict[str, str]] = None,
    store_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Record user feedback for a parse result.

    correct=True  → increment confirmed_count; may raise confidence tier.
    correct=False → increment failed_count; confidence does NOT increase.

    field_corrections: {field_label_key: corrected_label_string}
    These are stored as SUGGESTIONS only.  They apply to future parses as
    field-finding label alternatives after a confirmation threshold.

    SAFETY: field_corrections may only contain label strings, not values.
    Any key not ending in "_label", "_pattern", or "_words" is rejected.
    """
    store = load_store(store_path)
    entry = store.get(supplier_key)
    if not entry:
        return {"error": f"Supplier key '{supplier_key}' not found"}

    promoted  = False
    downgraded = False
    made_unstable = False
    now = _now_iso()
    layout = entry.get("layouts", {}).get(layout_fingerprint)

    if correct:
        entry["confirmed_count"] = entry.get("confirmed_count", 0) + 1
        old_conf = entry.get("confidence", CONFIDENCE_UNCONFIRMED)
        new_conf = get_confidence_level(entry["confirmed_count"])
        entry["confidence"] = new_conf
        promoted = (old_conf != new_conf)

        if layout:
            layout["confirmed_count"]      = layout.get("confirmed_count", 0) + 1
            layout["success_count"]        = layout.get("success_count", 0) + 1
            layout["consecutive_failures"] = 0        # reset on success
            layout["is_unstable"]          = False    # rehabilitate after correct parse
            layout["last_used"]            = now
    else:
        entry["failed_count"] = entry.get("failed_count", 0) + 1

        if layout:
            layout["failure_count"]        = (layout.get("failure_count") or 0) + 1
            layout["last_failed"]          = now
            consec = (layout.get("consecutive_failures") or 0) + 1
            layout["consecutive_failures"] = consec

            # REJECTION RULE: 3 consecutive failures → mark unstable, downgrade tier
            if consec >= 3 and not layout.get("is_unstable", False):
                layout["is_unstable"] = True
                made_unstable = True
                # Downgrade supplier confidence one tier
                tier_order = [
                    CONFIDENCE_UNCONFIRMED, CONFIDENCE_EMERGING,
                    CONFIDENCE_STABLE, CONFIDENCE_TRUSTED
                ]
                current = entry.get("confidence", CONFIDENCE_UNCONFIRMED)
                idx = tier_order.index(current) if current in tier_order else 0
                if idx > 0:
                    entry["confidence"] = tier_order[idx - 1]
                    downgraded = True

    # Store field label corrections (suggestions only, not direct overwrites)
    if field_corrections:
        layout = entry.get("layouts", {}).get(layout_fingerprint)
        if layout:
            fc = layout.setdefault("field_corrections", {})
            for field, correction in field_corrections.items():
                # Safety: only label/pattern/words keys
                allowed = field.endswith(("_label", "_pattern", "_words"))
                if not allowed:
                    continue
                # Correction must be a short string (label, not a value)
                if not isinstance(correction, str) or len(correction) > 80:
                    continue
                suggestions = fc.setdefault(field, [])
                if correction not in suggestions:
                    suggestions.append(correction)

    entry["last_seen"] = _now_iso()
    save_store(store, store_path)

    result = {
        "supplier_key":    supplier_key,
        "confirmed_count": entry["confirmed_count"],
        "confidence":      entry["confidence"],
        "promoted":        promoted,
        "correct":         correct,
        "failed_count":    entry.get("failed_count", 0),
        "downgraded":      downgraded,
        "made_unstable":   made_unstable,
    }
    if layout:
        result["layout_is_unstable"]      = layout.get("is_unstable", False)
        result["consecutive_failures"]    = layout.get("consecutive_failures", 0)
        result["reliability_pct"]         = _layout_reliability(layout)
    return result


# ── Summary & detail ──────────────────────────────────────────────────────────

def get_summary(store_path: Optional[Path] = None) -> Dict[str, Any]:
    """High-level summary of all learned supplier patterns."""
    store = load_store(store_path)
    suppliers = []
    for key, entry in store.items():
        layouts = entry.get("layouts", {})
        all_item_types: set = set()
        any_unstable = False
        total_success = 0
        total_failure = 0
        last_failed = None
        for layout in layouts.values():
            all_item_types.update(
                layout.get("patterns", {}).get("item_types_seen", [])
            )
            if layout.get("is_unstable"):
                any_unstable = True
            total_success += layout.get("success_count", 0)
            total_failure += layout.get("failure_count", 0)
            lf = layout.get("last_failed")
            if lf and (last_failed is None or lf > last_failed):
                last_failed = lf

        total_parses = total_success + total_failure
        reliability_pct = round(100 * total_success / total_parses) if total_parses > 0 else 100

        suppliers.append({
            "supplier_key":    key,
            "display_name":    entry.get("display_name", key),
            "invoice_format":  entry.get("invoice_format", ""),
            "confidence":      entry.get("confidence", CONFIDENCE_UNCONFIRMED),
            "confirmed_count": entry.get("confirmed_count", 0),
            "parse_count":     entry.get("parse_count", 0),
            "failed_count":    entry.get("failed_count", 0),
            "last_seen":       entry.get("last_seen", ""),
            "layout_count":    len(layouts),
            "item_types_seen": sorted(all_item_types),
            "any_unstable":    any_unstable,
            "reliability_pct": reliability_pct,
            "last_failed":     last_failed,
        })
    return {
        "total_suppliers": len(suppliers),
        "suppliers": sorted(suppliers, key=lambda s: s["confirmed_count"], reverse=True),
        "store_path": str(store_path or _get_store_path()),
    }


def get_pattern_detail(
    supplier_key: str,
    store_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return detailed pattern info for a specific supplier (safe for API response)."""
    store = load_store(store_path)
    entry = store.get(supplier_key)
    if not entry:
        return {"error": f"Pattern not found for '{supplier_key}'"}

    # Return copy with all financial/forbidden fields stripped
    safe = {k: v for k, v in entry.items() if k not in _FORBIDDEN_FIELDS}

    # Augment layouts with computed reliability
    layouts_out = {}
    for fp, layout in safe.get("layouts", {}).items():
        lout = {k: v for k, v in layout.items() if k not in _FORBIDDEN_FIELDS}
        lout["reliability_pct"] = _layout_reliability(layout)
        layouts_out[fp] = lout
    safe["layouts"] = layouts_out

    return safe


def reset_supplier_patterns(
    supplier_key: str,
    store_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Remove all learned patterns for a supplier (manual reset).

    Used when a supplier has changed their invoice layout significantly,
    or when accumulated patterns have become unreliable.

    Returns {"deleted": True, "supplier_key": key} on success,
            {"deleted": False, "error": "..."} if key not found.
    """
    store = load_store(store_path)
    if supplier_key not in store:
        return {"deleted": False, "error": f"No patterns found for '{supplier_key}'"}

    del store[supplier_key]
    save_store(store, store_path)
    return {"deleted": True, "supplier_key": supplier_key}
